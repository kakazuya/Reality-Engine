"""Clock-time agent routines: due slots, LAST.md chaining, tick dispatcher.

Never spawns omp, never touches the live DB or Task Scheduler.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reality_engine.pipeline import routines as rt

IST = timezone(timedelta(hours=5, minutes=30))


def _now(h, m=0, d=21, month=9, year=2026, weekday=None):
    """weekday is ignored; date is 2026-09-21 (Monday) unless d/month override."""
    return datetime(year, month, d, h, m, tzinfo=IST)


def _routine(**kwargs):
    base = {
        "name": "morning",
        "enabled": True,
        "kind": "daily",
        "at": "09:00",
        "weekday": None,
        "prompt_file": "prompt.md",
        "max_time": "20m",
        "model": None,
        "chain": True,
    }
    base.update(kwargs)
    return base


class DueSlotTest(unittest.TestCase):
    def test_daily_not_due_before_slot(self):
        self.assertFalse(rt.is_due(_routine(), _now(8, 59), last_run=None))

    def test_daily_due_at_slot_when_never_run(self):
        self.assertTrue(rt.is_due(_routine(), _now(9, 0), last_run=None))

    def test_daily_catch_up_same_day_after_missed_morning(self):
        self.assertTrue(rt.is_due(_routine(), _now(15, 30), last_run=None))

    def test_daily_not_due_once_this_slots_run_landed(self):
        last = _now(9, 5).isoformat()
        self.assertFalse(rt.is_due(_routine(), _now(15, 30), last_run=last))

    def test_daily_due_again_the_next_day(self):
        last = _now(9, 5).isoformat()
        tomorrow = _now(9, 0, d=22)
        self.assertTrue(rt.is_due(_routine(), tomorrow, last_run=last))

    def test_weekdays_skip_saturday(self):
        sat = datetime(2026, 9, 26, 9, 0, tzinfo=IST)  # Saturday
        self.assertFalse(rt.is_due(_routine(kind="weekdays"), sat, last_run=None))

    def test_weekdays_fire_monday(self):
        self.assertTrue(rt.is_due(_routine(kind="weekdays"), _now(9, 0), last_run=None))

    def test_weekly_only_on_configured_weekday(self):
        # 2026-09-21 is Monday (weekday 0). Routine set for Wednesday (2).
        self.assertFalse(
            rt.is_due(_routine(kind="weekly", weekday=2, at="09:00"), _now(9, 0), last_run=None)
        )
        wed = datetime(2026, 9, 23, 9, 0, tzinfo=IST)
        self.assertTrue(
            rt.is_due(_routine(kind="weekly", weekday=2, at="09:00"), wed, last_run=None)
        )

    def test_hourly_due_on_new_hour_not_inside_same_hour(self):
        last = _now(10, 7).isoformat()
        self.assertFalse(rt.is_due(_routine(kind="hourly", at=None), _now(10, 40), last_run=last))
        self.assertTrue(rt.is_due(_routine(kind="hourly", at=None), _now(11, 1), last_run=last))

    def test_disabled_never_due(self):
        self.assertFalse(rt.is_due(_routine(enabled=False), _now(9, 0), last_run=None))


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.catalog = self.root / "routines.json"
        self.prompts = self.root / "prompts"

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_then_list_round_trip(self):
        added = rt.add_routine(
            catalog_path=self.catalog,
            prompts_dir=self.prompts,
            name="morning-alpha",
            kind="daily",
            at="09:00",
            prompt="Screen Nifty200 and write three theses.",
        )
        self.assertEqual(added["name"], "morning-alpha")
        listed = rt.list_routines(self.catalog)
        self.assertEqual([r["name"] for r in listed], ["morning-alpha"])
        prompt = self.prompts / "morning-alpha.md"
        self.assertTrue(prompt.exists())
        self.assertIn("Screen Nifty200", prompt.read_text(encoding="utf-8"))

    def test_add_rejects_duplicate_and_bad_name(self):
        rt.add_routine(
            catalog_path=self.catalog,
            prompts_dir=self.prompts,
            name="ok",
            kind="daily",
            at="09:00",
            prompt="x",
        )
        with self.assertRaises(ValueError):
            rt.add_routine(
                catalog_path=self.catalog,
                prompts_dir=self.prompts,
                name="ok",
                kind="daily",
                at="09:00",
                prompt="x",
            )
        with self.assertRaises(ValueError):
            rt.add_routine(
                catalog_path=self.catalog,
                prompts_dir=self.prompts,
                name="../evil",
                kind="daily",
                at="09:00",
                prompt="x",
            )


class ChainCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "routines"
        self.prompt = Path(self.tmp.name) / "prompt.md"
        self.prompt.write_text("# task\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_has_no_last_and_no_session_continue(self):
        cmd = rt.build_agent_command(
            _routine(prompt_file=str(self.prompt)),
            state_dir=self.state,
            run_index=1,
        )
        self.assertIn("--no-session", cmd)
        self.assertNotIn("--continue", cmd)
        attached = [a for a in cmd if a.startswith("@")]
        self.assertEqual(attached, [f"@{self.prompt}"])

    def test_second_run_attaches_last_output(self):
        last = self.state / "morning" / rt.LAST_NAME
        last.parent.mkdir(parents=True)
        last.write_text("previous work product\n", encoding="utf-8")
        cmd = rt.build_agent_command(
            _routine(prompt_file=str(self.prompt)),
            state_dir=self.state,
            run_index=2,
        )
        attached = [a for a in cmd if a.startswith("@")]
        self.assertEqual(attached, [f"@{self.prompt}", f"@{last}"])

    def test_chain_off_skips_last_attachment(self):
        last = self.state / "morning" / rt.LAST_NAME
        last.parent.mkdir(parents=True)
        last.write_text("previous\n", encoding="utf-8")
        cmd = rt.build_agent_command(
            _routine(prompt_file=str(self.prompt), chain=False),
            state_dir=self.state,
            run_index=2,
        )
        attached = [a for a in cmd if a.startswith("@")]
        self.assertEqual(attached, [f"@{self.prompt}"])

    def test_model_flag_when_set(self):
        cmd = rt.build_agent_command(
            _routine(prompt_file=str(self.prompt), model="opencode-go/grok-4.6"),
            state_dir=self.state,
            run_index=1,
        )
        self.assertIn("--model", cmd)
        self.assertIn("opencode-go/grok-4.6", cmd)


class RunAndTickTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.catalog = self.root / "routines.json"
        self.prompts = self.root / "prompts"
        self.state = self.root / "state"
        rt.add_routine(
            catalog_path=self.catalog,
            prompts_dir=self.prompts,
            name="morning",
            kind="daily",
            at="09:00",
            prompt="Keep working the alpha list.",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _fake(self, text, rc=0):
        seen = {}

        def runner(cmd, timeout_seconds, log_path=None):
            seen["cmd"] = list(cmd)
            if log_path is not None:
                Path(log_path).parent.mkdir(parents=True, exist_ok=True)
                Path(log_path).write_text(text, encoding="utf-8")
            return {
                "rc": rc,
                "timed_out": False,
                "duration_seconds": 1.2,
                "stdout": text,
                "stdout_tail": text,
                "stderr_tail": "",
                "log_file": str(log_path) if log_path else None,
            }

        return runner, seen

    def test_run_writes_last_md_from_stdout_stripping_working_banner(self):
        runner, _ = self._fake("Working...\nDone: scored 09-16.\n## Next\nfit weights\n")
        result = rt.run_routine(
            name="morning",
            catalog_path=self.catalog,
            state_dir=self.state,
            now=_now(9, 1),
            agent_runner=runner,
        )
        self.assertEqual(result["rc"], 0)
        last = (self.state / "morning" / rt.LAST_NAME).read_text(encoding="utf-8")
        self.assertNotIn("Working...", last)
        self.assertIn("Done: scored 09-16.", last)
        self.assertIn("## Next", last)

    def test_next_tick_feeds_last_output_as_input(self):
        r1, _ = self._fake("first increment\n")
        rt.run_routine(
            name="morning",
            catalog_path=self.catalog,
            state_dir=self.state,
            now=_now(9, 1),
            agent_runner=r1,
        )
        fed = {}

        def r2(cmd, timeout_seconds, log_path=None):
            attached = [a for a in cmd if a.startswith("@")]
            fed["attached"] = attached
            if len(attached) >= 2:
                fed["last"] = Path(attached[1][1:]).read_text(encoding="utf-8")
            return {
                "rc": 0,
                "timed_out": False,
                "duration_seconds": 1.2,
                "stdout": "second increment\n",
                "stdout_tail": "second increment\n",
                "stderr_tail": "",
                "log_file": None,
            }

        rt.run_routine(
            name="morning",
            catalog_path=self.catalog,
            state_dir=self.state,
            now=_now(9, 1, d=22),
            agent_runner=r2,
        )
        self.assertEqual(len(fed["attached"]), 2)
        self.assertTrue(fed["attached"][1].endswith(rt.LAST_NAME))
        self.assertIn("first increment", fed["last"])

    def test_last_md_keeps_the_tail_when_stdout_is_huge(self):
        body = ("head " * 2000) + "UNIQUE_TAIL_MARKER"
        runner, _ = self._fake(body)
        rt.run_routine(
            name="morning",
            catalog_path=self.catalog,
            state_dir=self.state,
            now=_now(9, 1),
            agent_runner=runner,
        )
        last = (self.state / "morning" / rt.LAST_NAME).read_text(encoding="utf-8")
        self.assertLessEqual(len(last), rt.MAX_LAST_CHARS + 50)
        self.assertTrue(last.rstrip().endswith("UNIQUE_TAIL_MARKER"))

    def test_tick_runs_only_due_routines(self):
        rt.add_routine(
            catalog_path=self.catalog,
            prompts_dir=self.prompts,
            name="nightly",
            kind="daily",
            at="23:00",
            prompt="Night pass.",
        )
        ran = []

        def runner(cmd, timeout_seconds, log_path=None):
            marker = cmd[-1]
            ran.append(marker)
            return {
                "rc": 0,
                "timed_out": False,
                "duration_seconds": 0.1,
                "stdout": marker,
                "stdout_tail": marker,
                "stderr_tail": "",
                "log_file": None,
            }

        result = rt.tick(
            catalog_path=self.catalog,
            state_dir=self.state,
            now=_now(9, 30),
            agent_runner=runner,
        )
        self.assertEqual(result["ran_names"], ["morning"])
        self.assertTrue(any("morning" in m for m in ran))
        self.assertFalse(any("nightly" in m for m in ran))

    def test_tick_skips_when_lock_held(self):
        self.state.mkdir(parents=True)
        fd = rt.acquire_lock(self.state / rt.LOCK_NAME)
        try:
            result = rt.tick(
                catalog_path=self.catalog,
                state_dir=self.state,
                now=_now(9, 30),
                agent_runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")),
            )
            self.assertTrue(result["skipped"])
        finally:
            rt.release_lock(fd, self.state / rt.LOCK_NAME)

    def test_stale_lock_is_broken(self):
        self.state.mkdir(parents=True)
        lock = self.state / rt.LOCK_NAME
        lock.write_text("dead", encoding="utf-8")
        old = time.time() - (rt.STALE_LOCK_SECONDS + 60)
        os.utime(lock, (old, old))
        fd = rt.acquire_lock(lock)
        try:
            self.assertTrue(lock.exists())
        finally:
            rt.release_lock(fd, lock)


if __name__ == "__main__":
    unittest.main()
