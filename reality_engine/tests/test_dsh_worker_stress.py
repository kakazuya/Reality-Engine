"""Regression tests for the 2026-10-22 dsh-worker MCP stress pass.

Each test pins one failure found in tasks/codex_tasks/DSH_MCP_STRESS_2026-10-22.md.
Offline only: the fake launcher fixture, temporary repositories, no dsh, no
provider call, no project database.  Processes are only ever killed by the PID
this test itself spawned.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO / "plugins" / "dsh-worker" / "server"
SERVER = SERVER_DIR / "dsh_worker_mcp.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAKE_LAUNCHER = FIXTURES / "dsh_worker_fake_launcher.py"
TEST_TMP = REPO / "plugins" / "dsh-worker" / "runtime" / "test-tmp"
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(FIXTURES))

import core  # noqa: E402
import procutil  # noqa: E402
import progress  # noqa: E402
import store  # noqa: E402
import supervisor  # noqa: E402
from dsh_worker_testenv import make_temp_dir, remove_tree, run_async  # noqa: E402

OFF_PEAK = "2026-10-21T03:00:00+05:30"
IST = timezone(timedelta(hours=5, minutes=30))


class StressBase(unittest.TestCase):
    # A space and a Devanagari letter in the repository path on purpose.
    PREFIX = "dsh stress ू "

    def setUp(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        self.root = make_temp_dir(TEST_TMP, self.PREFIX)
        scripts = self.root / "reality_engine" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "go_session.py").write_text(
            "def session_id(*a, **k):\n    return 'provider-session-test'\n", encoding="utf-8"
        )
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith(("FAKE_", "DSH_WORKER_")):
                self.env.pop(key)
        self.env.pop("DSH_SESSION_LABEL", None)
        # The offline suite runs against a fake repository; the host's real data
        # root (set when this suite runs inside a worktree) must not leak in.
        self.env.pop("REALITY_DATA_ROOT", None)
        self.env.update(
            {
                "DSH_WORKER_REPO_ROOT": str(self.root),
                "DSH_WORKER_RUNTIME_DIR": str(self.root / "runtime"),
                "DSH_WORKTREES_ROOT": str(self.root / "worktrees"),
                "DSH_WORKER_LAUNCHER": str(FAKE_LAUNCHER),
                "DSH_WORKER_TESTING": "1",
                "DSH_WORKER_FAKE_NOW": OFF_PEAK,
                "FAKE_HEARTBEAT_FLAGS": "1",
                "FAKE_LAUNCHER_MODE": "fast",
                "FAKE_LAUNCHER_SLEEP": "5",
                "FAKE_LAUNCHER_OUTPUT": "fake final answer",
                "FAKE_LAUNCHER_PARTIAL": "partial output\n",
            }
        )
        self._managers: list[core.Manager] = []
        self.addCleanup(self._cleanup)

    def manager(self, **overrides: str) -> core.Manager:
        env = dict(self.env)
        env.update(overrides)
        manager = core.Manager(core.load_config(env))
        self._managers.append(manager)
        return manager

    def _cleanup(self) -> None:
        jobs = self.root / "runtime" / "jobs"
        if jobs.exists():
            cleaner = core.Manager(core.load_config(self.env))
            for job_dir in jobs.iterdir():
                if store.valid_job_id(job_dir.name):
                    try:
                        cleaner.cancel_worker(job_dir.name, confirm=True, reason="test cleanup")
                    except Exception:
                        pass
        for _ in range(30):
            try:
                remove_tree(self.root)
                return
            except OSError:
                time.sleep(0.2)

    def wait(self, manager: core.Manager, job_id: str, predicate, timeout: float = 20.0):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = manager.get_status(job_id)
            if predicate(last):
                return last
            time.sleep(0.1)
        self.fail(f"predicate not met; last status: {json.dumps(last, default=str)[:2000]}")

    def fake_job(self, job_id: str, status: dict | None, job: dict | None = None) -> Path:
        job_dir = self.root / "runtime" / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        record = {"schema": 1, "job_id": job_id, "workspace": str(self.root), "permission": "read-only"}
        record.update(job or {})
        (job_dir / "job.json").write_text(json.dumps(record), encoding="utf-8")
        if status is not None:
            (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
        return job_dir


class RecordRobustnessTests(StressBase):
    def test_non_integer_pid_fields_do_not_crash_status_or_list(self):
        self.fake_job("20261021T000001Z-0000aaaa", {"phase": "running", "supervisor_pid": "abc", "worker_pid": 5.5})
        self.fake_job("20261021T000002Z-0000bbbb", {"phase": "finished", "supervisor_pid": True})
        bad = self.root / "runtime" / "jobs" / "20261021T000003Z-0000cccc"
        bad.mkdir(parents=True)
        (bad / "job.json").write_text("[1, 2]", encoding="utf-8")
        manager = self.manager()
        status = manager.get_status("20261021T000001Z-0000aaaa")
        self.assertEqual(status["phase"], "unknown", status)
        self.assertFalse(status["final"])
        self.assertIn("supervisor_pid", status["process"]["record_invalid_fields"])
        listing = manager.list_workers()
        ids = {job["job_id"] for job in listing["jobs"]}
        self.assertIn("20261021T000002Z-0000bbbb", ids)
        self.assertIn("20261021T000003Z-0000cccc", {u["job_id"] for u in listing["unreadable"]})

    def test_start_failed_record_without_workspace_does_not_break_filtered_list(self):
        job_dir = self.root / "runtime" / "jobs" / "20261021T000004Z-0000dddd"
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(json.dumps({"job_id": "x", "start_failed": True}), encoding="utf-8")
        manager = self.manager()
        self.assertTrue(manager.list_workers(workspace=".")["ok"])
        status = manager.get_status("20261021T000004Z-0000dddd")
        self.assertEqual(status["phase"], "failed")
        self.assertEqual(status["outcome"], "start_failed")

    def test_transiently_unreadable_status_is_unknown_not_lost(self):
        manager = self.manager(FAKE_LAUNCHER_MODE="slow", FAKE_LAUNCHER_SLEEP="6")
        job_id = manager.start_worker(brief="lock test")["job_id"]
        self.wait(manager, job_id, lambda s: s["running"])
        original = core.read_json_bounded

        def locked(path, max_bytes=262_144):
            if Path(path).name == "status.json":
                return None, "invalid"
            return original(path, max_bytes)

        core.read_json_bounded = locked
        try:
            status = manager.get_status(job_id)
        finally:
            core.read_json_bounded = original
        self.assertEqual(status["phase"], "unknown", status)
        self.assertFalse(status["final"])
        self.assertFalse(status["failed"])
        self.assertTrue(manager.get_status(job_id)["running"])

    def test_relative_repo_root_is_rejected(self):
        env = dict(self.env, DSH_WORKER_REPO_ROOT=".")
        with self.assertRaises(core.PluginError) as caught:
            core.load_config(env)
        self.assertEqual(caught.exception.code, "repo_root_relative")

    def test_utf8_result_truncation_never_splits_a_character(self):
        path = self.root / "r.md"
        path.write_text("न" * 400, encoding="utf-8")  # 3 bytes per character
        for cap in (256, 257, 258, 259):
            text, truncated, _ = store.read_text_bounded(path, cap)
            self.assertTrue(truncated)
            self.assertNotIn("\ufffd", text)
            self.assertEqual(set(text), {"न"})


class VisibilityTests(StressBase):
    def test_streaming_result_is_not_ready_and_progress_reports_events(self):
        manager = self.manager(FAKE_LAUNCHER_MODE="slow", FAKE_LAUNCHER_SLEEP="3", FAKE_LAUNCHER_EVENTS="1")
        job_id = manager.start_worker(brief="progress test")["job_id"]
        running = self.wait(manager, job_id, lambda s: s["running"] and s["result_bytes"] > 0)
        self.assertFalse(running["result_ready"])
        self.assertTrue(running["result_is_streaming"])
        prog = running["progress"]
        self.assertFalse(prog["done"])
        self.assertIn("streaming, not final", prog["summary"])
        self.assertIsNotNone(prog["latest_finish_by"])
        self.assertEqual(prog["latest_finish_reason"], "controller_lease_deadline")
        events = self.wait(
            manager, job_id, lambda s: (s["progress"]["events"] or {}).get("tool_calls") == 3
        )["progress"]["events"]
        self.assertEqual(events["tool_calls_by_tool"], {"read": 1, "pwsh": 1, "write": 1})
        self.assertEqual(events["tool_failures"], 1)
        self.assertEqual(events["model_steps"], 1)
        self.assertEqual(events["output_tokens"], 42)
        self.assertEqual(events["last_tool"], "write")
        self.assertEqual(events["recent_file_writes"], ["out/report.md"])
        dumped = json.dumps(events)
        self.assertNotIn("hunter2", dumped)  # shell command text never surfaces
        self.assertNotIn("secret thinking", dumped)
        final = self.wait(manager, job_id, lambda s: s["final"])
        self.assertTrue(final["progress"]["done"])
        self.assertTrue(final["progress"]["succeeded"])
        self.assertTrue(final["result_ready"])
        self.assertTrue(final["progress"]["summary"].startswith("done: finished"))

    def test_empty_answer_is_flagged(self):
        manager = self.manager(FAKE_LAUNCHER_OUTPUT="")
        job_id = manager.start_worker(brief="empty")["job_id"]
        final = self.wait(manager, job_id, lambda s: s["final"])
        self.assertEqual(final["phase"], "finished")
        self.assertTrue(final["progress"]["answer_empty"])
        self.assertFalse(final["progress"]["succeeded"])
        self.assertFalse(final["result_ready"])
        self.assertTrue(any("empty answer" in w for w in final["warnings"]))

    def test_read_only_job_has_no_false_lock_retained_warning(self):
        manager = self.manager()
        job_id = manager.start_worker(brief="ro")["job_id"]
        final = self.wait(manager, job_id, lambda s: s["final"])
        self.assertFalse(any("lock retained" in w for w in final["warnings"]), final["warnings"])

    def test_failure_reason_surfaces_launcher_cause_without_reasoning(self):
        cases = {
            "OPENCODE_GO_API_KEY_2 is not set": "api_key_env_missing",
            "dsh not found at C:/x/dsh.exe; install with: bun add -g @deepseek-ai/dsh": "dsh_binary_missing",
            "06:31 IST is in DeepSeek peak hours (Mon-Fri 06:30-09:30, 11:30-15:30 IST)": "peak_hours_refused",
            "dsh: provider request timed out after 600s": "provider_timeout",
            "dsh: provider returned HTTP 502 Bad Gateway": "provider_http_error",
        }
        for message, cause in cases.items():
            with self.subTest(cause=cause):
                manager = self.manager(
                    FAKE_LAUNCHER_STDERR="dsh: reasoning: private chain\n" + message + " token=" + "a" * 40
                )
                job_id = manager.start_worker(brief="fail")["job_id"]
                final = self.wait(manager, job_id, lambda s: s["final"])
                reason = final["failure_reason"]
                self.assertEqual(reason["likely_cause"], cause, reason)
                dumped = json.dumps(reason)
                self.assertNotIn("private chain", dumped)
                self.assertNotIn("a" * 40, dumped)
                self.assertIn(cause, final["progress"]["summary"])

    def test_event_scanner_incremental_partial_line_and_flood(self):
        path = self.root / "ev.jsonl"
        call = json.dumps({"type": "tool_call", "tool": "edit", "input": {"file_path": "a.py"}})
        path.write_text(call + "\n" + call[:20], encoding="utf-8")
        scanner = progress.EventScanner()
        first = scanner.scan(path)
        self.assertEqual(first["tool_calls"], 1)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(call[20:] + "\n")
        self.assertEqual(scanner.scan(path)["tool_calls"], 2)
        # Flood: ~20 MB of events; each scan is bounded and catches up over calls.
        filler = (json.dumps({"type": "thinking", "text": "x" * 1000}) + "\n").encode()
        with path.open("ab") as fh:
            fh.write(filler * 20_000)
            fh.write((call + "\n").encode())
        started = time.monotonic()
        summary = scanner.scan(path)
        self.assertFalse(summary["caught_up"])
        self.assertLess(time.monotonic() - started, 5.0)
        for _ in range(5):
            summary = scanner.scan(path)
        self.assertTrue(summary["caught_up"])
        self.assertEqual(summary["tool_calls"], 3)
        # A replaced (truncated) file is rescanned from zero.
        path.write_text(call + "\n", encoding="utf-8")
        self.assertEqual(scanner.scan(path)["tool_calls"], 1)


class FakeClock:
    """One fake wall+monotonic clock advanced together in tests."""

    def __init__(self, start: datetime) -> None:
        self.wall = start
        self.mono = 0.0

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds


class ProgressDigestTests(StressBase):
    """Model-free supervisor digests: cadence, incremental scan, stall, final."""

    JOB_ID = "20261024T000000Z-0000aaaa"
    START = "2026-10-24T00:00:00+00:00"

    def _writer(self, clock: FakeClock, interval: int = 1200):
        job_dir = self.root / "digest-job"
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir, progress.DigestWriter(
            job_dir,
            self.JOB_ID,
            self.START,
            interval,
            clock=clock.now,
            monotonic=clock.monotonic,
        )

    @staticmethod
    def _call(tool: str, path: str | None = None) -> str:
        payload = {"type": "tool_call", "tool": tool, "input": {}}
        if path is not None:
            payload["input"] = {"file_path": path}
        return json.dumps(payload) + "\n"

    def test_cadence_with_fake_clock_and_final_digest(self):
        clock = FakeClock(datetime(2026, 10, 24, tzinfo=timezone.utc))
        job_dir, writer = self._writer(clock)
        events = job_dir / "result.md.events.jsonl"
        events.write_text(self._call("read", "tasks/FRAMEWORK.md"), encoding="utf-8")
        # The first tick only primes the interval: nothing is due yet.
        self.assertIsNone(writer.tick(phase="running", last_activity=clock.now()))
        clock.advance(1199)
        self.assertIsNone(writer.tick(phase="running", last_activity=clock.now()))
        clock.advance(1)
        first = writer.tick(phase="running", last_activity=clock.now(), lease_remaining=900)
        self.assertIsNotNone(first)
        self.assertEqual(first["digest"], 1)
        self.assertEqual(first["elapsed_seconds"], 1200)
        self.assertEqual(first["tool_calls"], 1)
        self.assertFalse(first["final"])
        digest_path = job_dir / "progress.jsonl"
        self.assertEqual(len(digest_path.read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(progress.read_digests(job_dir)[0]["digest"], 1)
        clock.advance(1200)
        second = writer.tick(
            phase="running",
            last_activity=clock.now() - timedelta(minutes=21),
            lease_remaining=120,
        )
        self.assertEqual(second["digest"], 2)
        self.assertTrue(second["stall"])
        # A finish does not wait for cadence: the final digest always lands.
        clock.advance(5)
        final = writer.tick(phase="finished", last_activity=clock.now(), final=True)
        self.assertTrue(final["final"])
        self.assertEqual(final["phase"], "finished")
        self.assertEqual(final["digest"], 3)
        self.assertFalse(final["stall"])
        self.assertEqual(len(progress.read_digests(job_dir)), 3)
        markdown = (job_dir / "progress.md").read_text(encoding="utf-8")
        self.assertIn("Digest 3", markdown)
        self.assertIn("## Earlier (2)", markdown)
        self.assertIn("phase: finished (final)", markdown)

    def test_incremental_offset_resume_and_deltas(self):
        clock = FakeClock(datetime(2026, 10, 24, tzinfo=timezone.utc))
        job_dir, writer = self._writer(clock)
        events = job_dir / "result.md.events.jsonl"
        events.write_text(
            self._call("read", "a.py")
            + self._call("edit", "a.py")
            + json.dumps({"type": "text", "text": "First update.\nSecond line."}) + "\n",
            encoding="utf-8",
        )
        self.assertIsNone(writer.tick(phase="running"))
        clock.advance(1200)
        first = writer.tick(phase="running")
        self.assertEqual(first["tool_calls"], 2)
        self.assertEqual(first["tool_calls_delta"], 2)
        self.assertEqual(first["tool_calls_by_tool"], {"read": 1, "edit": 1})
        self.assertEqual(first["files_written"], ["a.py"])
        self.assertEqual(
            first["worker_text_tail"], ["First update.", "Second line."]
        )
        # Only the appended bytes are read; totals accumulate, deltas do not.
        with events.open("a", encoding="utf-8") as fh:
            fh.write(self._call("write", "b.py"))
            fh.write(json.dumps({"type": "status", "phase": "step_end", "usage": {"outputTokens": 42}}) + "\n")
        clock.advance(1200)
        second = writer.tick(phase="running")
        self.assertEqual(second["tool_calls"], 3)
        self.assertEqual(second["tool_calls_delta"], 1)
        self.assertEqual(second["tool_calls_by_tool_delta"], {"write": 1})
        self.assertEqual(second["files_written"], ["b.py"])
        self.assertEqual(second["files_written_count"], 1)
        self.assertEqual(second["model_steps_delta"], 1)
        self.assertEqual(second["output_tokens"], 42)
        self.assertEqual(second["output_tokens_delta"], 42)
        # A half-written trailing line is not consumed twice.
        with events.open("a", encoding="utf-8") as fh:
            fh.write('{"type": "tool_call", "tool": "edit", "inp')
        clock.advance(1200)
        third = writer.tick(phase="running")
        self.assertEqual(third["tool_calls"], 3)
        self.assertEqual(third["tool_calls_delta"], 0)
        with events.open("a", encoding="utf-8") as fh:
            fh.write('ut": {"file_path": "c.py"}}' + "\n")
        clock.advance(1200)
        fourth = writer.tick(phase="running")
        self.assertEqual(fourth["tool_calls"], 4)
        self.assertEqual(fourth["tool_calls_delta"], 1)
        self.assertEqual(
            [item["digest"] for item in progress.read_digests(job_dir)],
            [4, 3, 2, 1],
        )

    def test_stall_flag_worker_note_and_lease(self):
        clock = FakeClock(datetime(2026, 10, 24, tzinfo=timezone.utc))
        job_dir, writer = self._writer(clock)
        (job_dir / "PROGRESS_NOTES.md").write_text(
            "first note\nsecond note\n", encoding="utf-8"
        )
        self.assertIsNone(writer.tick(phase="running"))
        clock.advance(1200)
        fresh = writer.tick(
            phase="running",
            last_activity=clock.now() - timedelta(minutes=5),
            lease_remaining=600,
        )
        self.assertFalse(fresh["stall"])
        self.assertEqual(fresh["idle_seconds"], 300)
        self.assertEqual(fresh["lease_seconds_left"], 600)
        self.assertEqual(fresh["note"], "second note")
        clock.advance(1200)
        stalled = writer.tick(
            phase="running", last_activity=clock.now() - timedelta(minutes=21)
        )
        self.assertTrue(stalled["stall"])
        self.assertEqual(stalled["idle_seconds"], 1260)
        self.assertTrue(progress.digest_line(stalled).startswith("running · elapsed"))
        self.assertIn("STALL no activity > 20m", progress.digest_line(stalled))

    def test_since_parser(self):
        now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
        self.assertIsNone(core._since_datetime(None))
        self.assertEqual(
            core._since_datetime("2026-10-24T11:00:00Z", now),
            now - timedelta(hours=1),
        )
        self.assertEqual(core._since_datetime("30m", now), now - timedelta(minutes=30))
        self.assertEqual(core._since_datetime("2h", now), now - timedelta(hours=2))
        with self.assertRaises(core.PluginError) as ctx:
            core._since_datetime("yesterday", now)
        self.assertEqual(ctx.exception.code, "since_invalid")

    def test_progress_interval_validation(self):
        manager = self.manager()
        for bad in (-1, 86_401, True, "ten"):
            with self.subTest(value=bad):
                with self.assertRaises(core.PluginError) as ctx:
                    manager.start_worker(brief="bad cadence", progress_interval_seconds=bad)
                self.assertEqual(ctx.exception.code, "progress_interval_invalid")
        with self.assertRaises(core.PluginError):
            manager.start_job("no-such-job", progress_interval_seconds=-5)


class StartGuardTests(StressBase):
    def test_peak_boundaries_ist_utc_and_weekend(self):
        cases = {
            "2026-10-21T06:29:59+05:30": False,
            "2026-10-21T06:30:00+05:30": True,
            "2026-10-21T09:29:59+05:30": True,
            "2026-10-21T09:30:00+05:30": False,
            "2026-10-21T11:29:59+05:30": False,
            "2026-10-21T11:30:00+05:30": True,
            "2026-10-21T15:29:59+05:30": True,
            "2026-10-21T15:30:00+05:30": False,
            "2026-10-24T08:00:00+05:30": False,  # Saturday
            "2026-10-25T12:00:00+05:30": False,  # Sunday
            "2026-10-21T01:00:00+00:00": True,  # 06:30 IST expressed in UTC
            "2026-10-21T00:59:59+00:00": False,
            "2026-10-21T10:00:00+00:00": False,  # 15:30 IST
        }
        for stamp, expected in cases.items():
            with self.subTest(stamp=stamp):
                self.assertIs(core.is_peak(datetime.fromisoformat(stamp)), expected)

    def test_start_refused_just_before_peak_window(self):
        refused = self.manager(DSH_WORKER_FAKE_NOW="2026-10-21T06:28:30+05:30")
        with self.assertRaises(core.PluginError) as caught:
            refused.start_worker(brief="x")
        self.assertEqual(caught.exception.code, "peak_hours_imminent")
        allowed = self.manager(DSH_WORKER_FAKE_NOW="2026-10-21T06:27:30+05:30")
        job_id = allowed.start_worker(brief="x")["job_id"]
        self.wait(allowed, job_id, lambda s: s["final"])

    def test_preflight_refuses_missing_dsh_and_missing_key(self):
        manager = self.manager(DSH_WORKER_PREFLIGHT="1", DSH_WORKER_DSH_PATH=str(self.root / "nope.exe"))
        with self.assertRaises(core.PluginError) as caught:
            manager.start_worker(brief="x")
        self.assertEqual(caught.exception.code, "dsh_missing")
        fake_dsh = self.root / "dsh.exe"
        fake_dsh.write_bytes(b"")
        env = {"DSH_WORKER_PREFLIGHT": "1", "DSH_WORKER_DSH_PATH": str(fake_dsh)}
        manager = self.manager(**env)
        manager.config.environ.pop(core.KEY_ENV, None)
        with self.assertRaises(core.PluginError) as caught:
            manager.start_worker(brief="x")
        self.assertEqual(caught.exception.code, "api_key_missing")
        self.assertNotIn("=", caught.exception.message)

    def test_concurrent_mutating_starts_admit_exactly_one_writer(self):
        managers = [
            self.manager(FAKE_LAUNCHER_MODE="slow", FAKE_LAUNCHER_SLEEP="4") for _ in range(4)
        ]
        outcomes: list[object] = []
        barrier = threading.Barrier(len(managers))

        def go(manager):
            barrier.wait()
            try:
                outcomes.append(manager.start_worker(brief="w", permission="workspace-write"))
            except core.PluginError as exc:
                outcomes.append(exc.code)

        threads = [threading.Thread(target=go, args=(m,)) for m in managers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        started = [o for o in outcomes if isinstance(o, dict)]
        self.assertEqual(len(started), 1, outcomes)
        self.assertEqual(sorted(o for o in outcomes if isinstance(o, str)), ["workspace_busy"] * 3)
        # A read-only worker may run alongside, with an explicit warning.
        ro = managers[1].start_worker(brief="r")
        self.assertTrue(any("read-only worker" in w for w in ro["warnings"]))
        winner = next(m for m in managers if started[0]["job_id"] in m._control_tokens)
        self.wait(winner, started[0]["job_id"], lambda s: s["final"])
        # Lock is released after the writer finishes: a new writer starts.
        again = managers[2].start_worker(brief="w2", permission="workspace-write")
        self.wait(managers[2], again["job_id"], lambda s: s["final"])


class LifecycleTests(StressBase):
    def test_other_session_claims_adopts_and_messages_after_restart(self):
        first = self.manager(
            FAKE_LAUNCHER_MODE="control",
            FAKE_LAUNCHER_SLEEP="20",
            DSH_SESSION_LABEL="session-first",
        )
        job_id = first.start_worker(brief="adopt")["job_id"]
        self.wait(first, job_id, lambda s: s["running"] and s["heartbeat"].get("control_available"))
        restarted = self.manager(DSH_SESSION_LABEL="session-restarted")
        status = restarted.get_status(job_id)
        self.assertEqual(status["owner_session"], "session-first")
        self.assertFalse(status["progress"]["controller_lease_renewable_here"])
        with self.assertRaises(core.PluginError) as caught:
            restarted.renew_worker_lease(job_id, 120)
        self.assertEqual(caught.exception.code, "controller_unavailable")
        renewed = restarted.renew_worker_lease(job_id, 120, adopt=True)
        self.assertTrue(renewed["adopted"])
        self.assertEqual(renewed["controller_lease"]["adoptions"], 1)
        self.assertTrue(restarted.get_status(job_id)["progress"]["controller_lease_renewable_here"])
        # Messaging now works from the other server: the token is persisted
        # DPAPI-encrypted (CurrentUser), not memory-only.
        sent = restarted.message_worker(job_id, "status?")
        self.assertTrue(sent["ok"], sent)
        self.assertTrue((Path(status["paths"]["job_dir"]) / "nudge.json").is_file())
        # Explicit claim transfers the recorded owner session; renewal then
        # needs no adopt=true, and the cap is two hours.
        claimed = restarted.claim_worker(job_id, "stress restart takeover")
        self.assertTrue(claimed["ok"], claimed)
        self.assertEqual(claimed["owner_session"], "session-restarted")
        self.assertEqual(claimed["previous_owner_session"], "session-first")
        owned = restarted.renew_worker_lease(job_id, 7200)
        self.assertTrue(owned["ok"], owned)
        self.assertEqual(owned["controller_lease"]["lease_seconds"], 7200)
        with self.assertRaises(core.PluginError) as caught:
            restarted.renew_worker_lease(job_id, 7201)
        self.assertEqual(caught.exception.code, "lease_extension_invalid")
        self.assertTrue(restarted.cancel_worker(job_id, confirm=True)["ok"])

    def test_expired_lease_cannot_be_adopted(self):
        first = self.manager(FAKE_LAUNCHER_MODE="slow", FAKE_LAUNCHER_SLEEP="30", DSH_WORKER_TEST_LEASE_SECONDS="2")
        job_id = first.start_worker(brief="expire")["job_id"]
        final = self.wait(first, job_id, lambda s: s["final"], timeout=30)
        self.assertEqual(final["outcome"], "controller_lease_expired")
        with self.assertRaises(core.PluginError) as caught:
            self.manager().renew_worker_lease(job_id, 120, adopt=True)
        self.assertEqual(caught.exception.code, "job_not_running")

    def test_worker_killed_alone_fails_with_reason(self):
        manager = self.manager(FAKE_LAUNCHER_MODE="slow", FAKE_LAUNCHER_SLEEP="30")
        job_id = manager.start_worker(brief="kill worker")["job_id"]
        status = self.wait(manager, job_id, lambda s: s["process"]["worker_alive"])
        procutil.kill_tree(int(status["process"]["worker_pid"]))
        final = self.wait(manager, job_id, lambda s: s["final"])
        self.assertEqual(final["phase"], "failed")
        self.assertEqual(final["outcome"], "launcher_error")
        self.assertIsNotNone(final["failure_reason"])

    def test_kill_tree_terminates_child_processes(self):
        script = self.root / "tree_parent.py"
        script.write_text(
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            "open(sys.argv[1], 'w', encoding='utf-8').write(str(child.pid))\n"
            "time.sleep(120)\n",
            encoding="utf-8",
        )
        pid_file = self.root / "tree.pid"
        parent = subprocess.Popen([sys.executable, str(script), str(pid_file)])
        try:
            deadline = time.monotonic() + 15
            child_pid: int | None = None
            while time.monotonic() < deadline:
                try:
                    child_pid = int(pid_file.read_text(encoding="utf-8").strip())
                    break
                except (OSError, ValueError):
                    time.sleep(0.05)
            self.assertIsNotNone(child_pid, "parent never published its child pid")
            self.assertTrue(procutil.process_alive(parent.pid))
            self.assertTrue(procutil.process_alive(child_pid))
            # taskkill may be denied to a restricted sandbox token; the native
            # parent-PID tree walk must still terminate both processes.
            self.assertTrue(procutil.kill_tree(parent.pid, timeout=15))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and (
                procutil.process_alive(parent.pid) or procutil.process_alive(child_pid)
            ):
                time.sleep(0.1)
            self.assertFalse(procutil.process_alive(parent.pid))
            self.assertFalse(procutil.process_alive(child_pid))
        finally:
            if parent.poll() is None:
                parent.kill()

    def test_supervisor_killed_alone_takes_worker_and_lock_needs_cancel(self):
        manager = self.manager(FAKE_LAUNCHER_MODE="slow", FAKE_LAUNCHER_SLEEP="60")
        job_id = manager.start_worker(brief="kill sup", permission="workspace-write")["job_id"]
        status = self.wait(manager, job_id, lambda s: s["process"]["worker_alive"])
        worker_pid = int(status["process"]["worker_pid"])
        worker_ticks = int(status["process"]["worker_creation_time"])
        # Kill only the supervisor (no tree): the worker must die with its job
        # object.  terminate_process avoids taskkill, which restricted agent
        # sandbox tokens may be denied.
        killed = procutil.terminate_process(int(status["process"]["supervisor_pid"]))
        self.assertTrue(killed, "could not terminate the recorded supervisor")
        lost = self.wait(manager, job_id, lambda s: s["phase"] == "lost")
        self.assertFalse(procutil.process_alive(worker_pid, worker_ticks), "job object must kill the worker")
        self.assertTrue(lost["final"])
        with self.assertRaises(core.PluginError) as caught:
            manager.start_worker(brief="second", permission="workspace-write")
        self.assertEqual(caught.exception.code, "workspace_busy")
        self.assertTrue(manager.cancel_worker(job_id, confirm=True)["lock_released"])
        fast = self.manager()
        follow = fast.start_worker(brief="second", permission="workspace-write")
        self.wait(fast, follow["job_id"], lambda s: s["final"])

    def test_pid_reuse_is_not_reported_alive(self):
        me = os.getpid()
        self.fake_job(
            "20261021T000005Z-0000eeee",
            {
                "phase": "running",
                "started_at": "2026-10-21T00:00:00+00:00",
                "supervisor_pid": me,
                "supervisor_creation_time": 12345,  # wrong creation time = recycled PID
                "worker_pid": me,
                "worker_creation_time": 12345,
            },
        )
        status = self.manager().get_status("20261021T000005Z-0000eeee")
        self.assertFalse(status["process"]["supervisor_alive"])
        self.assertEqual(status["phase"], "lost")

    def test_cancel_variants(self):
        manager = self.manager()
        refused = manager.cancel_worker("20261021T000006Z-0000ffff")
        self.assertEqual(refused["error"]["code"], "confirmation_required")
        with self.assertRaises(core.PluginError) as caught:
            manager.cancel_worker("20261021T000006Z-0000ffff", confirm=True)
        self.assertEqual(caught.exception.code, "job_not_found")
        with self.assertRaises(core.PluginError):
            manager.cancel_worker("dsh-20261022T010730-dea93bc4", confirm=True)  # harness run ids are not jobs
        job_id = manager.start_worker(brief="done")["job_id"]
        self.wait(manager, job_id, lambda s: s["final"])
        result = manager.cancel_worker(job_id, confirm=True)
        self.assertTrue(result["already_final"])
        self.assertEqual(result["phase"], "finished")

    def test_supervisor_status_write_failure_is_not_fatal(self):
        original = supervisor.atomic_write_json

        def boom(*_a, **_k):
            raise PermissionError("locked by antivirus")

        supervisor.atomic_write_json = boom
        try:
            self.assertFalse(supervisor._write_status_soft(self.root, {"phase": "running"}))
        finally:
            supervisor.atomic_write_json = original
        self.assertTrue(supervisor._write_status_soft(self.root, {"phase": "running"}))


class InspectRunTests(StressBase):
    def _harness_status(self, out: Path, *, pid: int, started: datetime, state: str, exit_code=None):
        out.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "dsh-heartbeat-status/1",
            "run_id": "dsh-test",
            "state": state,
            "pid": pid,
            "started_at": started.isoformat(timespec="seconds"),
            "ended_at": None if exit_code is None else datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "exit_code": exit_code,
            "failure": None if exit_code in (None, 0) else "dsh_failed",
            "model": "deepseek-v4.1-flash",
            "reasoning_effort": "max",
            "heartbeat": {
                "last_activity_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "last_activity_kind": "tool_call",
                "activity_count": 7,
                "hard_timeout_seconds": None,
            },
        }
        out.with_name(out.name + ".status.json").write_text(json.dumps(record), encoding="utf-8")
        out.with_name(out.name + ".events.jsonl").write_text(
            json.dumps({"type": "tool_call", "tool": "edit", "input": {"file_path": "x.py"}}) + "\n",
            encoding="utf-8",
        )

    def test_inspect_running_finished_reused_and_outside(self):
        manager = self.manager()
        out = self.root / "tasks" / "H99 result.md"
        me = os.getpid()
        created = procutil.process_creation_time(me)
        created_at = datetime.fromtimestamp((created - 116_444_736_000_000_000) / 1e7, timezone.utc)
        self._harness_status(out, pid=me, started=created_at + timedelta(seconds=2), state="running")
        out.write_text("streamed so far", encoding="utf-8")
        view = manager.inspect_run("tasks/H99 result.md.status.json")
        self.assertEqual(view["phase"], "running", view)
        self.assertEqual(view["pid_check"], "alive")
        self.assertFalse(view["result_ready"])
        self.assertTrue(view["result_is_streaming"])
        self.assertEqual(view["progress"]["events"]["recent_file_writes"], ["x.py"])
        self.assertFalse(view["messaging"]["available"])
        # Same PID but a start far from its creation time: recycled PID.
        self._harness_status(out, pid=me, started=created_at + timedelta(days=2), state="running")
        reused = manager.inspect_run(str(out))
        self.assertEqual(reused["pid_check"], "pid_reused")
        self.assertEqual(reused["phase"], "lost")
        self._harness_status(out, pid=me, started=created_at, state="completed", exit_code=0)
        done = manager.inspect_run(str(out))
        self.assertEqual(done["phase"], "finished")
        self.assertTrue(done["result_ready"])
        with self.assertRaises(core.PluginError) as caught:
            manager.inspect_run(str(REPO / "AGENTS.md"))
        self.assertEqual(caught.exception.code, "out_file_outside_repo")
        with self.assertRaises(core.PluginError) as caught:
            manager.inspect_run("tasks/missing.md")
        self.assertEqual(caught.exception.code, "run_not_found")


class McpSurfaceTests(StressBase):
    async def _session(self, fn, cwd: str | None = None):
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=self.env, cwd=cwd)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)

    @staticmethod
    async def _call(session, name, args=None):
        result = await session.call_tool(name, args or {}, read_timeout_seconds=30)
        data = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
        if data is None:
            for block in result.content:
                if getattr(block, "type", None) == "text":
                    try:
                        data = json.loads(block.text)
                    except ValueError:
                        data = {"text": block.text, "is_error": result.is_error}
                    break
        return data

    def test_server_from_foreign_cwd_info_invalid_args_and_unicode(self):
        foreign = self.root / "runtime" / "jobs" / "some job dir"
        foreign.mkdir(parents=True)

        async def scenario(session):
            info = await self._call(session, "server_info")
            self.assertTrue(info["ok"], info)
            self.assertEqual(Path(info["repo_root"]), self.root.resolve())
            self.assertEqual(Path(info["cwd"]), foreign.resolve())
            self.assertTrue(info["launcher_capabilities"]["heartbeat_supported"])
            bad_type = await self._call(session, "start_worker", {"brief": "x", "missed_replies": "two"})
            self.assertTrue(bad_type.get("is_error") or bad_type.get("ok") is False, bad_type)
            missing = await self._call(session, "worker_status", {})
            self.assertTrue(missing.get("is_error") or missing.get("ok") is False, missing)
            both = await self._call(session, "start_worker", {"brief": "x", "task_file": "y"})
            self.assertEqual(both["error"]["code"], "brief_required")
            big = await self._call(session, "start_worker", {"brief": "x" * 262_145})
            self.assertEqual(big["error"]["code"], "brief_too_large")
            started = await self._call(session, "start_worker", {"brief": "हिंदी ब्रीफ ✓ 价格"})
            self.assertTrue(started["ok"], started)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 20
            while loop.time() < deadline:
                status = await self._call(session, "worker_status", {"job_id": started["job_id"]})
                if status["final"]:
                    break
                await asyncio.sleep(0.1)
            self.assertTrue(status["progress"]["done"], status)
            brief = (self.root / "runtime" / "jobs" / started["job_id"] / "brief.md").read_text(encoding="utf-8")
            self.assertTrue(brief.startswith("हिंदी ब्रीफ ✓ 价格"), brief[:200])
            self.assertIn("PROGRESS_NOTES.md", brief)
            self.assertNotIn("?", brief[len("हिंदी ब्रीफ ✓ 价格"):])  # instruction is not a question
            long_msg = await self._call(
                session, "message_worker", {"job_id": started["job_id"], "message": "न" * 4001}
            )
            self.assertEqual(long_msg["error"]["code"], "message_too_long")
            listed = await self._call(session, "list_workers", {})
            self.assertTrue(listed["jobs"][0]["summary"].startswith("done:"))

        run_async(self._session(scenario, cwd=str(foreign)), 90)

    def test_server_exit_while_job_runs_is_reported(self):
        self.env.update({"FAKE_LAUNCHER_MODE": "slow", "FAKE_LAUNCHER_SLEEP": "20"})

        async def start(session):
            return await self._call(session, "start_worker", {"brief": "server exit"})

        started = run_async(self._session(start), 60)
        self.assertIn("survives_server_exit", started)
        if not started["survives_server_exit"]:
            # Python's MCP client puts the server in a KILL_ON_JOB_CLOSE job
            # without BREAKAWAY_OK, so the supervisor cannot escape: the start
            # response must say so instead of implying survival.
            self.assertTrue(any("break away" in w for w in started["warnings"]), started["warnings"])
        manager = self.manager()
        status = self.wait(
            manager,
            started["job_id"],
            lambda s: s["final"] or s["process"]["supervisor_alive"],
        )
        if started["survives_server_exit"]:
            self.assertTrue(status["running"], status)
        else:
            self.assertIn(status["phase"], {"lost", "failed", "cancelled"}, status)
            self.assertFalse(status["process"]["worker_alive"])


class SharedControlProcessTests(StressBase):
    """Phase 1 acceptance: two real MCP server processes share one job.

    Each server is a separate Python process with its own session label.  The
    tests keep both sessions open for the job's lifetime because the Python MCP
    client's host job object may kill the server's children on exit.
    """

    def _git(self, *args: str, repo: Path | None = None) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo or self.root), *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
        self.assertEqual(
            completed.returncode, 0, completed.stdout + "\n" + completed.stderr
        )
        return completed.stdout.strip()

    def _init_git_repo(self) -> str:
        self._git("init", "-b", "main")
        self._git("config", "user.name", "dsh stress test")
        self._git("config", "user.email", "dsh-stress@example.invalid")
        (self.root / "README.md").write_text("initial\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "initial")
        return self._git("rev-parse", "HEAD")

    def _env(self, label: str, **extra: str) -> dict[str, str]:
        env = dict(self.env)
        env["DSH_SESSION_LABEL"] = label
        env.update(extra)
        return env

    @staticmethod
    def _params(env: dict[str, str]) -> StdioServerParameters:
        return StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)

    async def _with_sessions(self, envs: list[dict[str, str]], fn):
        async with contextlib.AsyncExitStack() as stack:
            sessions: list[ClientSession] = []
            for env in envs:
                read, write = await stack.enter_async_context(stdio_client(self._params(env)))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                sessions.append(session)
            return await fn(*sessions)

    @staticmethod
    async def _call(session, name: str, args: dict | None = None):
        result = await session.call_tool(name, args or {}, read_timeout_seconds=60)
        data = getattr(result, "structured_content", None) or getattr(
            result, "structuredContent", None
        )
        if data is None:
            for block in result.content:
                if getattr(block, "type", None) == "text":
                    try:
                        data = json.loads(block.text)
                    except ValueError:
                        data = {"text": block.text, "is_error": result.is_error}
                    break
        return data

    async def _wait_tool_status(self, session, job_id: str, predicate, timeout: float = 30.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        last = None
        while loop.time() < deadline:
            last = await self._call(session, "worker_status", {"job_id": job_id})
            if predicate(last):
                return last
            await asyncio.sleep(0.1)
        self.fail(f"status predicate not met: {json.dumps(last, default=str)[:2000]}")

    def test_two_server_worktree_demo_steering_and_auto_commit(self):
        base_commit = self._init_git_repo()
        env_x = self._env(
            "session-X",
            FAKE_LAUNCHER_MODE="control",
            FAKE_LAUNCHER_SLEEP="6",
            FAKE_LAUNCHER_WRITE_FILE="worker_out.txt",
        )
        env_y = self._env(
            "session-Y",
            FAKE_LAUNCHER_MODE="control",
            FAKE_LAUNCHER_SLEEP="6",
        )

        async def scenario(session_x, session_y):
            started = await self._call(
                session_x,
                "start_worker",
                {
                    "brief": "Phase 1 acceptance worktree task",
                    "permission": "workspace-write",
                    "use_worktree": True,
                },
            )
            self.assertTrue(started["ok"], started)
            job_id = started["job_id"]
            await self._wait_tool_status(
                session_x,
                job_id,
                lambda s: s["running"] and s["heartbeat"].get("control_available"),
            )
            listed = await self._call(session_y, "list_workers", {})
            row = next(item for item in listed["jobs"] if item["job_id"] == job_id)
            self.assertEqual(row["owner_session"], "session-X")
            self.assertEqual(row["worktree_branch"], f"dsh/{job_id}")

            sent = await self._call(
                session_y,
                "message_worker",
                {"job_id": job_id, "message": "hello from session Y"},
            )
            self.assertTrue(sent["ok"], sent)
            renewed = await self._call(
                session_y,
                "renew_worker_lease",
                {"job_id": job_id, "extend_seconds": 7200, "adopt": True},
            )
            self.assertTrue(renewed["ok"], renewed)
            self.assertEqual(renewed["controller_lease"]["lease_seconds"], 7200)
            claimed = await self._call(
                session_y,
                "claim_worker",
                {"job_id": job_id, "reason": "acceptance takeover"},
            )
            self.assertTrue(claimed["ok"], claimed)
            self.assertEqual(claimed["owner_session"], "session-Y")
            self.assertEqual(claimed["previous_owner_session"], "session-X")
            owned = await self._call(
                session_y,
                "renew_worker_lease",
                {"job_id": job_id, "extend_seconds": 7200},
            )
            self.assertTrue(owned["ok"], owned)
            self.assertFalse(owned["adopted"])
            final = await self._wait_tool_status(
                session_y, job_id, lambda s: s["final"], timeout=40
            )
            self.assertEqual(final["phase"], "finished", final)
            return started, final

        started, final = run_async(
            self._with_sessions([env_x, env_y], scenario), 150
        )
        job_id = started["job_id"]
        job_dir = Path(started["status_path"]).parent
        tree = final["worktree"]
        self.assertTrue(tree["committed"], tree)
        self.assertEqual(tree["branch"], f"dsh/{job_id}")
        self.assertEqual(tree["base_commit"], base_commit)
        self.assertEqual(tree["commits"], 1)
        self.assertEqual(tree["files_changed"], 1)
        self.assertRegex(tree["head"], r"^[0-9a-f]{40}$")
        worktree = Path(tree["path"])
        body = self._git("log", "-1", "--format=%B", repo=worktree)
        self.assertIn(f"DSH-Job: {job_id}", body)
        self.assertIn("[dsh " + job_id + "]", body.splitlines()[0])
        self.assertEqual(self._git("rev-parse", f"dsh/{job_id}"), tree["head"])
        self.assertEqual(self._git("rev-parse", "main"), base_commit)

        launcher = json.loads((job_dir / "launcher_argv.json").read_text(encoding="utf-8"))
        self.assertEqual(
            launcher["env_reality_data_root"],
            str((self.root / "reality_engine" / "data").resolve()),
        )
        steering_text = (job_dir / "steering.jsonl").read_text(encoding="utf-8")
        steering = [json.loads(line) for line in steering_text.splitlines()]
        kinds = {entry["kind"] for entry in steering}
        self.assertTrue({"start", "message", "claim", "renew"} <= kinds, kinds)
        self.assertIn("session-X", {entry["session"] for entry in steering})
        self.assertTrue(any(entry["session"] == "session-Y" for entry in steering))
        for entry in steering:
            self.assertLessEqual(len(entry["text"]), 200)
        # The plaintext token is decryptable by this user but never persisted or audited.
        token = store.dpapi_unprotect((job_dir / store.TOKEN_FILE).read_bytes()).decode("utf-8")
        self.assertGreaterEqual(len(token), 32)
        for text in (
            steering_text,
            (job_dir / "job.json").read_text(encoding="utf-8"),
            (job_dir / "status.json").read_text(encoding="utf-8"),
            json.dumps(final),
        ):
            self.assertNotIn(token, text)

    def test_data_job_run_visible_from_second_server(self):
        registry_path = self.root / "test-jobs.yaml"
        registry_path.write_text(
            yaml.safe_dump(
                {
                    "schema": "dsh-worker-jobs/1",
                    "jobs": [
                        {
                            "name": "fake_data_job",
                            "description": "offline fake data job (no network, no DB)",
                            "argv": [
                                "python",
                                "-c",
                                "import pathlib, time; time.sleep(1); "
                                "print('fake data job ran'); "
                                "pathlib.Path('fake_job_out.txt').write_text('ok')",
                            ],
                            "cwd": ".",
                            "env": {},
                            "writes": ["fake_job_out.txt"],
                            "resource_locks": ["db:test-standalone.db"],
                            "cadence": "daily",
                            "success_check": None,
                            "off_peak_only": False,
                            "market_hours": "any",
                            "needs_paid_api": False,
                            "needs_gpu": False,
                            "enabled": True,
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        env_x = self._env(
            "data-job-X", DSH_WORKER_JOBS_FILE=str(registry_path)
        )
        env_y = self._env(
            "data-job-Y", DSH_WORKER_JOBS_FILE=str(registry_path)
        )

        async def scenario(session_x, session_y):
            started = await self._call(session_x, "start_job", {"name": "fake_data_job"})
            self.assertTrue(started["ok"], started)
            run_id = started["run_id"]
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 20
            entry = None
            while loop.time() < deadline:
                listed = await self._call(session_y, "list_jobs", {})
                entry = next(
                    item for item in listed["jobs"] if item["name"] == "fake_data_job"
                )
                if entry["last_run"] is not None:
                    break
                await asyncio.sleep(0.1)
            self.assertIsNotNone(entry and entry["last_run"], entry)
            final = await self._wait_tool_status(
                session_y, run_id, lambda s: s["final"], timeout=40
            )
            self.assertEqual(final["phase"], "finished", final)
            log = await self._call(
                session_y, "job_log", {"run_id": run_id, "tail": 50}
            )
            self.assertTrue(log["ok"], log)
            self.assertTrue(
                any("fake data job ran" in line for line in log["stdout"]), log
            )
            listed = await self._call(session_y, "list_jobs", {})
            entry = next(
                item for item in listed["jobs"] if item["name"] == "fake_data_job"
            )
            self.assertIsNotNone(entry["last_success"], entry)
            self.assertFalse(entry["never_ran"], entry)
            return started, final

        started, final = run_async(
            self._with_sessions([env_x, env_y], scenario), 120
        )
        self.assertTrue((self.root / "fake_job_out.txt").is_file())

    def test_two_server_lease_race_loses_no_renewals(self):
        self._init_git_repo()
        env_x = self._env(
            "session-race-X",
            FAKE_LAUNCHER_MODE="control",
            FAKE_LAUNCHER_SLEEP="12",
        )
        env_y = self._env(
            "session-race-Y",
            FAKE_LAUNCHER_MODE="control",
            FAKE_LAUNCHER_SLEEP="12",
        )
        env_z = self._env(
            "session-race-Z",
            FAKE_LAUNCHER_MODE="control",
            FAKE_LAUNCHER_SLEEP="12",
        )
        renewals_per_server = 6

        async def scenario(session_x, session_y, session_z):
            started = await self._call(
                session_x, "start_worker", {"brief": "lease race", "permission": "read-only"}
            )
            job_id = started["job_id"]
            await self._wait_tool_status(
                session_x,
                job_id,
                lambda s: s["running"] and s["heartbeat"].get("control_available"),
            )

            async def spam(session):
                responses = []
                for _ in range(renewals_per_server):
                    responses.append(
                        await self._call(
                            session,
                            "renew_worker_lease",
                            {"job_id": job_id, "extend_seconds": 7200, "adopt": True},
                        )
                    )
                return responses

            results = await asyncio.gather(spam(session_y), spam(session_z))
            for response in (item for group in results for item in group):
                self.assertTrue(response["ok"], response)
            status = await self._call(session_x, "worker_status", {"job_id": job_id})
            self.assertEqual(
                status["controller_lease"]["renewals"], renewals_per_server * 2
            )
            cancelled = await self._call(
                session_y, "cancel_worker", {"job_id": job_id, "confirm": True}
            )
            self.assertTrue(cancelled["ok"], cancelled)
            return job_id

        job_id = run_async(
            self._with_sessions([env_x, env_y, env_z], scenario), 150
        )
        job_dir = self.root / "runtime" / "jobs" / job_id
        lines = [
            json.loads(line)
            for line in (job_dir / "steering.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        renews = [line for line in lines if line["kind"] == "renew"]
        self.assertEqual(len(renews), renewals_per_server * 2)
        self.assertEqual(
            {line["session"] for line in renews}, {"session-race-Y", "session-race-Z"}
        )


if __name__ == "__main__":
    unittest.main()
