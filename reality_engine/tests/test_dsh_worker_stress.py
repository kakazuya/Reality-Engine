"""Regression tests for the 2026-10-22 dsh-worker MCP stress pass.

Each test pins one failure found in tasks/codex_tasks/DSH_MCP_STRESS_2026-10-22.md.
Offline only: the fake launcher fixture, temporary repositories, no dsh, no
provider call, no project database.  Processes are only ever killed by the PID
this test itself spawned.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO / "plugins" / "dsh-worker" / "server"
SERVER = SERVER_DIR / "dsh_worker_mcp.py"
FAKE_LAUNCHER = Path(__file__).resolve().parent / "fixtures" / "dsh_worker_fake_launcher.py"
sys.path.insert(0, str(SERVER_DIR))

import core  # noqa: E402
import procutil  # noqa: E402
import progress  # noqa: E402
import store  # noqa: E402
import supervisor  # noqa: E402

OFF_PEAK = "2026-10-21T03:00:00+05:30"
IST = timezone(timedelta(hours=5, minutes=30))


class StressBase(unittest.TestCase):
    # A space and a Devanagari letter in the repository path on purpose.
    PREFIX = "dsh stress ू "

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix=self.PREFIX)
        self.root = Path(self.tmp.name)
        scripts = self.root / "reality_engine" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "go_session.py").write_text(
            "def session_id(*a, **k):\n    return 'provider-session-test'\n", encoding="utf-8"
        )
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith(("FAKE_", "DSH_WORKER_")):
                self.env.pop(key)
        self.env.update(
            {
                "DSH_WORKER_REPO_ROOT": str(self.root),
                "DSH_WORKER_RUNTIME_DIR": str(self.root / "runtime"),
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
                self.tmp.cleanup()
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
    def test_restarted_server_adopts_lease_explicitly(self):
        first = self.manager(FAKE_LAUNCHER_MODE="slow", FAKE_LAUNCHER_SLEEP="8")
        job_id = first.start_worker(brief="adopt")["job_id"]
        self.wait(first, job_id, lambda s: s["running"])
        restarted = self.manager()
        status = restarted.get_status(job_id)
        self.assertFalse(status["progress"]["controller_lease_renewable_here"])
        with self.assertRaises(core.PluginError) as caught:
            restarted.renew_worker_lease(job_id, 120)
        self.assertEqual(caught.exception.code, "controller_unavailable")
        renewed = restarted.renew_worker_lease(job_id, 120, adopt=True)
        self.assertTrue(renewed["adopted"])
        self.assertEqual(renewed["controller_lease"]["adoptions"], 1)
        self.assertTrue(restarted.get_status(job_id)["progress"]["controller_lease_renewable_here"])
        # Messaging still needs the memory-only token: explicit, not silent.
        sent = restarted.message_worker(job_id, "status?")
        self.assertFalse(sent["ok"])
        self.assertEqual(sent["error"]["code"], "transport_unavailable")
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

    def test_supervisor_killed_alone_takes_worker_and_lock_needs_cancel(self):
        manager = self.manager(FAKE_LAUNCHER_MODE="slow", FAKE_LAUNCHER_SLEEP="60")
        job_id = manager.start_worker(brief="kill sup", permission="workspace-write")["job_id"]
        status = self.wait(manager, job_id, lambda s: s["process"]["worker_alive"])
        worker_pid = int(status["process"]["worker_pid"])
        worker_ticks = int(status["process"]["worker_creation_time"])
        # Kill only the supervisor (no /T): the worker must die with its job object.
        killed = subprocess.run(
            ["taskkill", "/PID", str(status["process"]["supervisor_pid"]), "/F"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(killed.returncode, 0, killed.stdout + killed.stderr)
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
            self.assertEqual(brief, "हिंदी ब्रीफ ✓ 价格")
            long_msg = await self._call(
                session, "message_worker", {"job_id": started["job_id"], "message": "न" * 4001}
            )
            self.assertEqual(long_msg["error"]["code"], "message_too_long")
            listed = await self._call(session, "list_workers", {})
            self.assertTrue(listed["jobs"][0]["summary"].startswith("done:"))

        asyncio.run(asyncio.wait_for(self._session(scenario, cwd=str(foreign)), 90))

    def test_server_exit_while_job_runs_is_reported(self):
        self.env.update({"FAKE_LAUNCHER_MODE": "slow", "FAKE_LAUNCHER_SLEEP": "20"})

        async def start(session):
            return await self._call(session, "start_worker", {"brief": "server exit"})

        started = asyncio.run(asyncio.wait_for(self._session(start), 60))
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


if __name__ == "__main__":
    unittest.main()
