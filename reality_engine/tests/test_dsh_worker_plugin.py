"""Offline tests for the local dsh-worker Codex plugin.

No test calls DeepSeek, dsh, a paid API, or a project database.  Integration
tests speak real MCP over stdio to the plugin server and use a fake launcher in
a temporary repository.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO / "plugins" / "dsh-worker"
SERVER_DIR = PLUGIN_ROOT / "server"
SERVER = SERVER_DIR / "dsh_worker_mcp.py"
FAKE_LAUNCHER = Path(__file__).resolve().parent / "fixtures" / "dsh_worker_fake_launcher.py"

sys.path.insert(0, str(SERVER_DIR))

import core  # noqa: E402
import heartbeat  # noqa: E402
import procutil  # noqa: E402
import supervisor  # noqa: E402

OFF_PEAK = "2026-10-21T03:00:00+05:30"
PEAK = "2026-10-21T07:00:00+05:30"
FAKE_GO_SESSION = '''"""Fake stable provider session for offline plugin tests."""
def session_id(job, model, key="", lane_no=None):
    return "provider-session-test"
'''


class PluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        scripts = self.root / "reality_engine" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "go_session.py").write_text(FAKE_GO_SESSION, encoding="utf-8")
        self.env = os.environ.copy()
        self.env.update(
            {
                "DSH_WORKER_REPO_ROOT": str(self.root),
                "DSH_WORKER_RUNTIME_DIR": str(self.root / "runtime"),
                # Execute the reviewed repo fixture directly; TemporaryDirectory
                # holds only fixture data, never an executable created there.
                "DSH_WORKER_LAUNCHER": str(FAKE_LAUNCHER),
                "DSH_WORKER_TESTING": "1",
                "DSH_WORKER_FAKE_NOW": OFF_PEAK,
                "FAKE_LAUNCHER_MODE": "fast",
                "FAKE_LAUNCHER_SLEEP": "5",
                "FAKE_LAUNCHER_OUTPUT": "fake final answer",
                "FAKE_LAUNCHER_PARTIAL": "partial output\n",
                # The plugin now refuses to start without the real heartbeat
                # and control-token contract.  The fake advertises that contract
                # by default; tests that check refusal turn this off.
                "FAKE_HEARTBEAT_FLAGS": "1",
            }
        )
        self._manager = None
        self.addCleanup(self._cleanup)

    def _manager_instance(self):
        if self._manager is None:
            self._manager = core.Manager(core.load_config(self.env))
        return self._manager

    def _reset_manager(self) -> None:
        self._manager = None

    def _cleanup(self) -> None:
        runtime = Path(self.env["DSH_WORKER_RUNTIME_DIR"])
        jobs_dir = runtime / "jobs"
        if jobs_dir.exists():
            for job_dir in list(jobs_dir.iterdir()):
                if not job_dir.is_dir() or not (job_dir / "job.json").exists():
                    continue
                try:
                    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
                    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if status.get("supervisor_pid") == os.getpid():
                    continue
                job_id = job.get("job_id")
                if not isinstance(job_id, str):
                    continue
                try:
                    self._manager_instance().cancel_worker(job_id, confirm=True, reason="test cleanup")
                except Exception:
                    pass
        for _ in range(20):
            try:
                self.tmp.cleanup()
                return
            except OSError:
                time.sleep(0.2)

    # ----------------------------------------------------------- MCP helpers
    async def _with_session(self, fn):
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER)],
            env=self.env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)

    def _run(self, coro, timeout: float = 60.0):
        return asyncio.run(asyncio.wait_for(coro, timeout))

    @staticmethod
    def _payload(result):
        data = getattr(result, "structured_content", None)
        if data is None:
            data = getattr(result, "structuredContent", None)
        if data is None:
            for block in result.content:
                if getattr(block, "type", None) == "text":
                    data = json.loads(block.text)
                    break
        if data is None:
            raise AssertionError(f"tool returned no JSON payload: {result!r}")
        return data

    async def _call(self, session, name, arguments=None):
        result = await session.call_tool(name, arguments or {}, read_timeout_seconds=30)
        return self._payload(result)

    def _wait_status(self, job_id: str, predicate, timeout: float = 15.0):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = self._manager_instance().get_status(job_id)
            if predicate(last):
                return last
            time.sleep(0.1)
        self.fail(f"status predicate not met; last status: {last}")

    async def _await_tool_status(self, session, job_id, predicate, timeout: float = 20.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        last = None
        while loop.time() < deadline:
            last = await self._call(session, "worker_status", {"job_id": job_id})
            if predicate(last):
                return last
            await asyncio.sleep(0.1)
        self.fail(f"status predicate not met; last status: {last}")

    # --------------------------------------------------------------- tests
    def test_manifest_and_layout(self):
        self.assertFalse((PLUGIN_ROOT / ".codex-plugin").exists())
        mcp = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        server = mcp["mcpServers"]["dsh-worker"]
        self.assertEqual(server["type"], "stdio")
        self.assertEqual(
            server["command"],
            "C:/Users/warri/AppData/Local/Programs/Python/Python314/python.exe",
        )
        self.assertEqual(server["args"], ["server/dsh_worker_mcp.py"])
        self.assertEqual(server["cwd"], ".")
        self.assertNotIn("API_KEY", json.dumps(mcp))
        self.assertNotIn("TOKEN", json.dumps(mcp))
        skill = (PLUGIN_ROOT / "skills" / "dsh-worker" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\nname: dsh-worker\n"))
        self.assertIn("transport_unavailable", skill)
        marketplace = json.loads(
            (REPO / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
        )
        entry = next(item for item in marketplace["plugins"] if item["name"] == "dsh-worker")
        self.assertEqual(entry["source"]["path"], "./plugins/dsh-worker")
        self.assertTrue(entry["source"]["path"].startswith("./"))
        self.assertNotIn("..", entry["source"]["path"])
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")

    def test_mcp_startup_has_no_unresolved_placeholders(self):
        """Codex does not expand ${PLUGIN_ROOT} in a legacy plugin .mcp.json.

        The literal placeholder was appended to the install-cache root, so the
        stdio process never started. Startup paths must be plugin-relative.
        """
        mcp = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        server = mcp["mcpServers"]["dsh-worker"]
        unresolved = re.findall(r"\$\{[^}]+\}", json.dumps(server))
        self.assertEqual(
            unresolved,
            [],
            "unsupported unresolved startup placeholder(s): " + ", ".join(unresolved),
        )
        self.assertEqual(server["cwd"], ".")
        script = Path(server["args"][0])
        self.assertFalse(script.is_absolute(), "script path must be relative to cwd")
        self.assertFalse(Path(server["cwd"]).is_absolute())
        for relative in (script, Path(server["cwd"])):
            self.assertNotIn("..", relative.parts)
        self.assertTrue((PLUGIN_ROOT / script).is_file(), "script must exist under plugin root")
        self.assertTrue((PLUGIN_ROOT / server["cwd"]).is_dir())

    def test_peak_and_path_validation(self):
        peak_env = dict(self.env)
        peak_env["DSH_WORKER_FAKE_NOW"] = PEAK
        with self.assertRaises(core.PluginError) as ctx:
            core.Manager(core.load_config(peak_env)).start_worker(brief="work", workspace=".")
        self.assertEqual(ctx.exception.code, "peak_hours")

        with tempfile.TemporaryDirectory() as outside:
            outside_path = Path(outside)
            with self.assertRaises(core.PluginError) as ctx:
                self._manager_instance().start_worker(brief="work", workspace=str(outside_path))
            self.assertEqual(ctx.exception.code, "workspace_outside_repo")
            secret = outside_path / "brief.md"
            secret.write_text("outside", encoding="utf-8")
            with self.assertRaises(core.PluginError) as ctx:
                self._manager_instance().start_worker(task_file=str(secret))
            self.assertEqual(ctx.exception.code, "task_file_outside_repo")
            with self.assertRaises(core.PluginError) as ctx:
                self._manager_instance().start_worker(task_file=f"../{outside_path.name}/brief.md")
            self.assertEqual(ctx.exception.code, "task_file_outside_repo")

        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(brief="a", task_file="brief.md")
        self.assertEqual(ctx.exception.code, "brief_required")
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker()
        self.assertEqual(ctx.exception.code, "brief_required")
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(brief="   \n")
        self.assertEqual(ctx.exception.code, "brief_empty")
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().get_status("../escape")
        self.assertEqual(ctx.exception.code, "job_id_invalid")

    def test_start_defaults_argv_and_result(self):
        started = self._manager_instance().start_worker(
            brief="Do the fake task", workspace=".", max_result_bytes=1024
        )
        self.assertTrue(started["ok"], started)
        job_id = started["job_id"]
        job = json.loads((Path(started["status_path"]).parent / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["model"], "deepseek-v4.1-flash")
        self.assertEqual(job["effort"], "max")
        self.assertEqual(job["account"], "2")
        self.assertEqual(job["permission"], "read-only")
        self.assertEqual(job["heartbeat"]["interval_seconds"], 900)
        self.assertEqual(job["heartbeat"]["missed_replies_allowed"], 2)
        self.assertEqual(job["heartbeat"]["mode"], "launcher_heartbeat")
        self.assertFalse(job["heartbeat"]["degraded"])
        self.assertIsNone(job["limits"]["hard_timeout_seconds"])
        self.assertEqual(job["limits"]["hard_timeout_kind"], "none")
        self.assertEqual(job["provider_session"], "provider-session-test")
        self.assertIsNone(job["conversation_id"])
        argv = job["launcher"]["argv"]
        self.assertIn("--allow-paid", argv)
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--account") + 1], "2")
        self.assertEqual(argv[argv.index("--model") + 1], "deepseek-v4.1-flash")
        self.assertNotIn("--peak-ok", argv)
        self.assertIn("--heartbeat-interval", argv)
        self.assertIn("--control-token-env", argv)
        self.assertNotIn("--timeout", argv, "omitted timeout must not add a wall-clock kill")
        token = self._manager_instance()._control_tokens[job_id]
        self.assertNotIn(token, json.dumps(job))
        self.assertNotIn(token, (Path(started["status_path"]).parent / "job.json").read_text(encoding="utf-8"))
        argv_path = Path(started["status_path"]).parent / "launcher_argv.json"
        deadline = time.monotonic() + 10
        while not argv_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not argv_path.exists():
            job_dir = argv_path.parent
            for name in ("supervisor.log", "stdout.log", "stderr.log", "status.json"):
                path = job_dir / name
                print(f"--- {name} ---")
                print(path.read_text(encoding="utf-8", errors="replace") if path.exists() else "(missing)")
        record = json.loads(argv_path.read_text(encoding="utf-8"))
        self.assertEqual(record["task"], "Do the fake task")
        final = self._wait_status(job_id, lambda s: s["final"])
        self.assertEqual(final["phase"], "finished")
        self.assertEqual(final["exit_code"], 0)
        self.assertTrue(final["result_ready"])
        result = self._manager_instance().worker_result(job_id)
        self.assertEqual(result["content"].strip(), "fake final answer")
        self.assertFalse(result["truncated"])
        self.assertEqual(result["max_bytes"], 1024)
        self.assertNotIn("secret", json.dumps(result).lower())
        listed = self._manager_instance().list_workers()
        self.assertTrue(any(item["job_id"] == job_id for item in listed["jobs"]))

    def test_missing_heartbeat_or_control_capability_is_refused(self):
        no_heartbeat = dict(self.env)
        no_heartbeat["FAKE_HEARTBEAT_FLAGS"] = "0"
        no_heartbeat.pop("FAKE_NO_CONTROL_TOKEN_FLAG", None)
        with self.assertRaises(core.PluginError) as ctx:
            core.Manager(core.load_config(no_heartbeat)).start_worker(brief="no heartbeat")
        self.assertEqual(ctx.exception.code, "heartbeat_unavailable")
        self.assertIn("automatic hard-timeout fallback was removed", ctx.exception.message)

        no_control = dict(self.env)
        no_control["FAKE_HEARTBEAT_FLAGS"] = "1"
        no_control["FAKE_NO_CONTROL_TOKEN_FLAG"] = "1"
        with self.assertRaises(core.PluginError) as ctx:
            core.Manager(core.load_config(no_control)).start_worker(brief="no control token")
        self.assertEqual(ctx.exception.code, "control_token_unavailable")
        self.assertIn("--control-token-env", ctx.exception.message)

    def test_stale_status_ignores_status_log_and_heartbeat_mtimes(self):
        runtime = Path(self.env["DSH_WORKER_RUNTIME_DIR"])
        job_id = "20261021T010101Z-cafebabe"
        job_dir = runtime / "jobs" / job_id
        job_dir.mkdir(parents=True)
        old = "2026-10-20T00:00:00+00:00"
        now = core.utc_now().isoformat(timespec="seconds")
        pid = os.getpid()
        ticks = procutil.process_creation_time(pid)
        job = {
            "schema": 1,
            "job_id": job_id,
            "created_at": old,
            "workspace": str(self.root),
            "permission": "read-only",
            "heartbeat": {"interval_seconds": 900, "missed_replies_allowed": 2},
        }
        (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
        status = {
            "phase": "running",
            "started_at": old,
            "updated_at": now,
            "supervisor_pid": pid,
            "supervisor_creation_time": ticks,
            "worker_pid": pid,
            "worker_creation_time": ticks,
            "worker_activity_at": old,
        }
        (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
        heartbeat_record = {
            "schema": heartbeat.STATUS_SCHEMA,
            "run_id": "stale-run",
            "state": "running",
            "dsh_conversation_id": "stale-conversation",
            "pid": pid,
            "started_at": old,
            "heartbeat": {
                "idle_seconds": 900,
                "response_window_seconds": 900,
                "max_unanswered": 2,
                "last_activity_at": old,
                "last_activity_kind": "text",
                "consecutive_unanswered": 0,
                "activity_count": 1,
                "pings": [],
                "events": [],
            },
        }
        (job_dir / "heartbeat.json").write_text(json.dumps(heartbeat_record), encoding="utf-8")
        for name in ("result.md", "result.md.log", "stdout.log", "stderr.log"):
            (job_dir / name).write_text("fresh-looking but not worker progress\n", encoding="utf-8")
        stale_env = dict(self.env)
        stale_env["DSH_WORKER_STALE_AFTER_SECONDS"] = "30"
        manager = core.Manager(core.load_config(stale_env))
        first = manager.get_status(job_id)
        self.assertTrue(first["running"], first)
        self.assertTrue(first["stale"], first)
        self.assertEqual(core.parse_iso(first["last_activity_at"]), core.parse_iso(old))

        # Periodic supervisor/status/heartbeat writes advance mtimes and
        # updated_at but do not advance the nested worker-activity timestamp.
        for _ in range(3):
            status["updated_at"] = core.utc_now().isoformat(timespec="seconds")
            (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
            heartbeat_record["heartbeat"]["last_activity_at"] = old
            (job_dir / "heartbeat.json").write_text(json.dumps(heartbeat_record), encoding="utf-8")
            for name in ("result.md", "result.md.log", "stdout.log", "stderr.log"):
                (job_dir / name).write_text("more supervisor output\n", encoding="utf-8")
            time.sleep(0.02)
        again = manager.get_status(job_id)
        self.assertTrue(again["stale"], again)
        self.assertEqual(core.parse_iso(again["last_activity_at"]), core.parse_iso(old))

        # A persisted awaiting flag must not hide a wedged launcher past its
        # absolute lease.  Expired/missing deadlines fail closed; a live lease
        # is surfaced as awaiting_input and is exempt from ordinary staleness.
        heartbeat_record["heartbeat"]["awaiting_input"] = True
        heartbeat_record["heartbeat"]["awaiting_deadline"] = "2000-01-01T00:00:00+00:00"
        (job_dir / "heartbeat.json").write_text(json.dumps(heartbeat_record), encoding="utf-8")
        expired_wait = manager.get_status(job_id)
        self.assertFalse(expired_wait["awaiting_input"], expired_wait)
        self.assertTrue(expired_wait["stale"], expired_wait)

        heartbeat_record["heartbeat"].pop("awaiting_deadline", None)
        (job_dir / "heartbeat.json").write_text(json.dumps(heartbeat_record), encoding="utf-8")
        missing_deadline = manager.get_status(job_id)
        self.assertFalse(missing_deadline["awaiting_input"], missing_deadline)
        self.assertTrue(missing_deadline["stale"], missing_deadline)

        heartbeat_record["heartbeat"]["awaiting_deadline"] = (
            core.utc_now() + core.timedelta(minutes=5)
        ).isoformat(timespec="seconds")
        (job_dir / "heartbeat.json").write_text(json.dumps(heartbeat_record), encoding="utf-8")
        live_wait = manager.get_status(job_id)
        self.assertTrue(live_wait["awaiting_input"], live_wait)
        self.assertFalse(live_wait["stale"], live_wait)
        heartbeat_record["heartbeat"]["awaiting_input"] = False
        heartbeat_record["heartbeat"].pop("awaiting_deadline", None)
        (job_dir / "heartbeat.json").write_text(json.dumps(heartbeat_record), encoding="utf-8")

        # A real nested activity update is what clears staleness.
        heartbeat_record["heartbeat"]["last_activity_at"] = core.utc_now().isoformat(timespec="seconds")
        status["worker_activity_at"] = heartbeat_record["heartbeat"]["last_activity_at"]
        (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
        (job_dir / "heartbeat.json").write_text(json.dumps(heartbeat_record), encoding="utf-8")
        fresh = manager.get_status(job_id)
        self.assertFalse(fresh["stale"], fresh)

    def test_controller_lease_expiry_stops_endless_worker_and_preserves_partial(self):
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "20"
        self.env["DSH_WORKER_TEST_LEASE_SECONDS"] = "2"
        self._reset_manager()
        started = self._manager_instance().start_worker(brief="endless responsive task")
        job_id = started["job_id"]
        job_dir = Path(started["status_path"]).parent
        lease_path = job_dir / "controller_lease.json"
        self.assertTrue(lease_path.exists())
        final = self._wait_status(job_id, lambda s: s["final"], timeout=10.0)
        self.assertEqual(final["phase"], "failed", final)
        self.assertEqual(final["outcome"], "controller_lease_expired", final)
        self.assertFalse(final["process"]["worker_alive"], final)
        self.assertTrue(final["partial"], final)
        self.assertIn("partial output", (job_dir / "result.md").read_text(encoding="utf-8"))
        self.assertFalse(lease_path.exists(), "finalization must remove the lease")

    def test_missing_lease_stops_responsive_worker(self):
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "20"
        self.env["DSH_WORKER_TEST_LEASE_SECONDS"] = "30"
        self._reset_manager()
        started = self._manager_instance().start_worker(brief="missing lease task")
        job_id = started["job_id"]
        job_dir = Path(started["status_path"]).parent
        self._wait_status(job_id, lambda s: s["running"] and s["result_bytes"] > 0 and not s["result_ready"])
        (job_dir / "controller_lease.json").unlink()
        final = self._wait_status(job_id, lambda s: s["final"], timeout=8.0)
        self.assertEqual(final["outcome"], "controller_lease_expired", final)
        self.assertFalse(final["process"]["worker_alive"], final)
        self.assertTrue(final["partial"], final)

    def test_controller_lease_renewal_is_explicit_and_restart_cannot_extend(self):
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "20"
        self.env["DSH_WORKER_TEST_LEASE_SECONDS"] = "4"
        self._reset_manager()
        started = self._manager_instance().start_worker(brief="renewable task")
        job_id = started["job_id"]
        job_dir = Path(started["status_path"]).parent
        lease_path = job_dir / "controller_lease.json"
        before = json.loads(lease_path.read_text(encoding="utf-8"))
        # Read-only status/result/list calls and fake worker activity must not
        # renew.  The fake launcher keeps updating status/heartbeat files.
        self._wait_status(job_id, lambda s: s["running"])
        self._manager_instance().worker_result(job_id, 1024)
        self._manager_instance().list_workers()
        time.sleep(0.3)
        unchanged = json.loads(lease_path.read_text(encoding="utf-8"))
        self.assertEqual(unchanged["deadline"], before["deadline"])
        # Renewal is reset-from-now, not add-to-current-deadline, and the store
        # records whole seconds.  Ask for an explicitly longer interval than the
        # 4-second initial lease so the new deadline cannot tie the old one.
        renewed = self._manager_instance().renew_worker_lease(job_id, extend_seconds=10)
        self.assertTrue(renewed["ok"], renewed)
        self.assertGreater(
            core.parse_iso(renewed["controller_lease"]["deadline"]),
            core.parse_iso(before["deadline"]),
        )
        self.assertEqual(renewed["controller_lease"]["lease_seconds"], 10)
        self.assertEqual(renewed["controller_lease"]["renewals"], 1)
        after_renew = renewed["controller_lease"]["deadline"]

        # A restarted MCP server does not hold the memory-only owner id and
        # cannot extend the persisted lease.
        restarted = core.Manager(core.load_config(self.env))
        with self.assertRaises(core.PluginError) as ctx:
            restarted.renew_worker_lease(job_id, extend_seconds=4)
        self.assertEqual(ctx.exception.code, "controller_unavailable")
        self.assertEqual(
            json.loads(lease_path.read_text(encoding="utf-8"))["deadline"], after_renew
        )

        # A copied/wrong-owner lease is rejected rather than extended.
        copied = json.loads(lease_path.read_text(encoding="utf-8"))
        copied["owner_id"] = "wrong-owner"
        lease_path.write_text(json.dumps(copied), encoding="utf-8")
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().renew_worker_lease(job_id, extend_seconds=4)
        self.assertEqual(ctx.exception.code, "lease_invalid")
        self.assertEqual(
            json.loads(lease_path.read_text(encoding="utf-8"))["deadline"], after_renew
        )

        self._manager_instance().cancel_worker(job_id, confirm=True)
        self.assertFalse(lease_path.exists(), "cancellation must remove the lease")

    def test_repository_mutation_lock_covers_parent_and_subdirectory(self):
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "20"
        self._reset_manager()
        first = self._manager_instance().start_worker(
            brief="root writer", workspace=".", permission="workspace-write"
        )
        self.assertTrue(first["ok"], first)
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(
                brief="subdir writer",
                workspace="reality_engine",
                permission="workspace-write",
            )
        self.assertEqual(ctx.exception.code, "workspace_busy")
        self.assertIn("existing_job_id", ctx.exception.details)
        self.assertIn("recovery", ctx.exception.details)
        self._manager_instance().cancel_worker(first["job_id"], confirm=True)

    def test_lock_fails_closed_and_is_not_released_under_live_worker(self):
        runtime = Path(self.env["DSH_WORKER_RUNTIME_DIR"])
        locks = runtime / "locks"
        locks.mkdir(parents=True)
        job_id = "20261021T020202Z-deadbeef"
        job_dir = runtime / "jobs" / job_id
        job_dir.mkdir(parents=True)
        pid = os.getpid()
        ticks = procutil.process_creation_time(pid)
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "job_id": job_id,
                    "created_at": core.iso(),
                    "workspace": str(self.root),
                    "permission": "read-only",
                }
            ),
            encoding="utf-8",
        )
        # Supervisor is gone, but the recorded worker is this live test process.
        status = {
            "phase": "running",
            "started_at": core.iso(),
            "supervisor_pid": 999_999,
            "supervisor_creation_time": 1,
            "worker_pid": pid,
            "worker_creation_time": ticks,
        }
        (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
        manager = self._manager_instance()
        lock = {"job_id": job_id, "supervisor_pid": 999_999, "supervisor_creation_time": 1}
        self.assertTrue(manager._lock_active(lock))
        lock_path = locks / core.MUTATION_LOCK_NAME
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        self.assertFalse(manager._release_lock(self.root, job_id))
        self.assertTrue(lock_path.exists(), "lock must survive while the recorded worker lives")

        # The same recorded PID without a creation time is unverifiable: fail closed.
        status["worker_creation_time"] = None
        (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
        self.assertTrue(manager._lock_active(lock))

        # Only a final status with both recorded processes proven dead frees it.
        status.update(
            {
                "phase": "finished",
                "supervisor_pid": 999_999,
                "supervisor_creation_time": 1,
                "worker_pid": 999_999,
                "worker_creation_time": 1,
            }
        )
        (job_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
        self.assertFalse(manager._lock_active(lock))
        self.assertTrue(manager._release_lock(self.root, job_id))
        self.assertFalse(lock_path.exists())

    def test_artifact_hint_is_newly_dirty_only_and_says_so(self):
        baseline = {"available": True, "paths": ["already.py", "unchanged.py"]}
        final = {"available": True, "paths": ["already.py", "new.py"]}
        result = core.gitutil.changed_since(baseline, final)
        self.assertEqual(result["paths"], ["new.py"])
        self.assertEqual(result["scope"], "newly_dirty_paths_only")
        self.assertIn("already dirty at start are excluded", result["note"])
        self.assertIn("full working-tree diff", result["note"])

    def test_mutating_windows_containment_fails_closed(self):
        if os.name != "nt":
            self.skipTest("Windows-specific containment policy")
        self.assertIsNotNone(
            supervisor._containment_error({"permission": "workspace-write"})
        )
        self.assertIsNone(supervisor._containment_error({"permission": "read-only"}))

    def test_mcp_initialize_tools_prompt_start_partial_and_cancel(self):
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "30"
        self.env["FAKE_LAUNCHER_OUTPUT"] = "final-after-slow\n"
        self._reset_manager()

        async def scenario(session):
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            self.assertEqual(
                names,
                {
                    "start_worker",
                    "worker_status",
                    "worker_result",
                    "message_worker",
                    "cancel_worker",
                    "list_workers",
                    "renew_worker_lease",
                    "inspect_run",
                    "server_info",
                },
            )
            by_name = {tool.name: tool for tool in tools.tools}
            cancel_tool = by_name["cancel_worker"]
            self.assertIs(cancel_tool.annotations.destructive_hint, True)
            self.assertIs(by_name["start_worker"].annotations.open_world_hint, True)
            self.assertIs(by_name["message_worker"].annotations.open_world_hint, True)
            self.assertIs(by_name["worker_status"].annotations.open_world_hint, False)
            self.assertIs(by_name["worker_result"].annotations.open_world_hint, False)
            begin = time.monotonic()
            started = await self._call(
                session,
                "start_worker",
                {"brief": "Slow fake task", "workspace": ".", "permission": "workspace-write"},
            )
            elapsed = time.monotonic() - begin
            self.assertTrue(started["ok"], started)
            job_id = started["job_id"]
            status = await self._await_tool_status(
                session, job_id, lambda s: s["running"] and s["result_bytes"] > 0 and not s["result_ready"]
            )
            self.assertTrue(status["process"]["worker_alive"])
            self.assertFalse(status["final"])
            partial = await self._call(
                session, "worker_result", {"job_id": job_id, "max_bytes": 4096}
            )
            self.assertFalse(partial["final"])
            self.assertIn("partial output", partial["content"])
            rejected = await self._call(session, "cancel_worker", {"job_id": job_id})
            self.assertFalse(rejected["ok"])
            self.assertEqual(rejected["error"]["code"], "confirmation_required")
            cancelled = await self._call(
                session, "cancel_worker", {"job_id": job_id, "confirm": True}
            )
            self.assertTrue(cancelled["ok"], cancelled)
            after = await self._call(session, "worker_status", {"job_id": job_id})
            self.assertTrue(after["final"])
            self.assertEqual(after["phase"], "cancelled")
            self.assertFalse(after["process"]["worker_alive"])
            preserved = await self._call(session, "worker_result", {"job_id": job_id})
            self.assertIn("partial output", preserved["content"])
            self.assertNotIn("secret reasoning", preserved["content"])
            return elapsed, started, after

        elapsed, started, final = self._run(self._with_session(scenario))
        self.assertLess(elapsed, 5.0, "start_worker must return before the job finishes")
        self.assertEqual(final["phase"], "cancelled")

    def test_server_shutdown_does_not_leave_uncontrolled_writer(self):
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "30"
        self._reset_manager()

        async def start_only(session):
            return await self._call(session, "start_worker", {"brief": "shutdown scope"})

        started = self._run(self._with_session(start_only))
        job_id = started["job_id"]
        time.sleep(1.0)
        status = self._manager_instance().get_status(job_id)
        # The MCP client owns a Windows job object for the server process tree.
        # Closing the session can therefore kill the supervisor and worker before
        # finalization; what must never remain is an uncontrolled live writer.
        self.assertFalse(status["process"]["worker_alive"], status)
        self.assertFalse(status["process"]["supervisor_alive"], status)
        self.assertIn(status["phase"], {"lost", "cancelled", "finished", "failed"}, status)

    def test_message_transport_unavailable_and_control_seam(self):
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "20"
        self._reset_manager()

        async def unavailable(session):
            started = await self._call(session, "start_worker", {"brief": "no control"})
            job_id = started["job_id"]
            await self._await_tool_status(session, job_id, lambda s: s["running"])
            response = await self._call(
                session, "message_worker", {"job_id": job_id, "message": "status?"}
            )
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "transport_unavailable")
            await self._call(session, "cancel_worker", {"job_id": job_id, "confirm": True})

        self._run(self._with_session(unavailable))

        self.env["FAKE_LAUNCHER_MODE"] = "control"
        self.env["FAKE_LAUNCHER_SLEEP"] = "20"
        self.env["FAKE_HEARTBEAT_FLAGS"] = "1"
        self._reset_manager()

        async def control(session):
            started = await self._call(session, "start_worker", {"brief": "control task"})
            job_id = started["job_id"]
            status = await self._await_tool_status(
                session,
                job_id,
                lambda s: s["running"] and s["heartbeat"].get("control_available"),
            )
            self.assertIn("conv-test-1", json.dumps(status["heartbeat"]))
            self.assertTrue(status["heartbeat"]["control_token_available"])
            nudge_path = Path(started["status_path"]).parent / "nudge.json"
            if nudge_path.exists():
                nudge_path.unlink()
            too_long = await self._call(
                session,
                "message_worker",
                {"job_id": job_id, "message": "x" * 4001},
            )
            self.assertFalse(too_long["ok"], too_long)
            self.assertEqual(too_long["error"]["code"], "message_too_long")
            self.assertEqual(too_long["error"]["limit"], 4000)
            self.assertFalse(nudge_path.exists(), "overlong text must not be sent/truncated")
            delivered = await self._call(
                session,
                "message_worker",
                {"job_id": job_id, "message": "please continue", "conversation_id": "conv-test-1"},
            )
            self.assertTrue(delivered["ok"], delivered)
            self.assertTrue(delivered["ack_is_not_a_worker_response"])
            self.assertFalse(delivered["worker_response"])
            self.assertTrue(nudge_path.exists())
            nudge = json.loads(nudge_path.read_text(encoding="utf-8"))
            self.assertEqual(nudge["run_id"], "fake-run-1")
            self.assertEqual(nudge["session_id"], "conv-test-1")
            self.assertEqual(nudge["message"][0]["text"], "please continue")
            mismatch = await self._call(
                session,
                "message_worker",
                {"job_id": job_id, "message": "wrong session", "conversation_id": "wrong-id"},
            )
            self.assertFalse(mismatch["ok"])
            self.assertEqual(mismatch["error"]["code"], "session_mismatch")
            still_running = await self._call(session, "worker_status", {"job_id": job_id})
            self.assertEqual(still_running["phase"], "running")
            restarted_manager = core.Manager(core.load_config(self.env))
            restarted_status = restarted_manager.get_status(job_id)
            self.assertFalse(restarted_status["heartbeat"]["control_available"])
            self.assertFalse(restarted_status["heartbeat"]["control_token_available"])
            self.assertEqual(
                restarted_status["heartbeat"]["control_unavailable_reason"],
                "control_token_not_in_this_mcp_server",
            )
            after_restart = restarted_manager.message_worker(
                job_id, "after restart", conversation_id="conv-test-1"
            )
            self.assertFalse(after_restart["ok"])
            self.assertEqual(after_restart["error"]["code"], "transport_unavailable")
            await self._call(session, "cancel_worker", {"job_id": job_id, "confirm": True})

        self._run(self._with_session(control))

    def test_message_route_selection_distinguishes_followup_from_status(self):
        control = {
            "schema": heartbeat.CONTROL_SCHEMA,
            "state": "awaiting-input",
            "host": "127.0.0.1",
            "port": 1234,
            "run_id": "run-1",
            "session_id": "conv-1",
            "awaiting_input": True,
        }
        status = {"run_id": "run-1", "conversation_id": "conv-1"}
        error, followup = heartbeat._validate_control(
            control, status, "conv-1", kind="followup"
        )
        self.assertIsNone(error)
        self.assertEqual(followup["path"], "/followup")
        self.assertTrue(followup["awaiting_input"])
        error, nudge = heartbeat._validate_control(
            control, status, "conv-1", kind="status"
        )
        self.assertIsNone(error)
        self.assertEqual(nudge["path"], "/ping")

    def test_heartbeat_capable_launcher_flags_and_status(self):
        self.env["FAKE_HEARTBEAT_FLAGS"] = "1"
        self.env["FAKE_LAUNCHER_MODE"] = "heartbeat"
        self.env["FAKE_LAUNCHER_SLEEP"] = "5"
        self._reset_manager()

        started = self._manager_instance().start_worker(brief="heartbeat task")
        job_id = started["job_id"]
        job = json.loads((Path(started["status_path"]).parent / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["heartbeat"]["mode"], "launcher_heartbeat")
        self.assertFalse(job["heartbeat"]["degraded"])
        argv = job["launcher"]["argv"]
        self.assertEqual(argv[argv.index("--heartbeat-interval") + 1], "900")
        self.assertEqual(argv[argv.index("--heartbeat-misses") + 1], "2")
        self.assertIn("--status-file", argv)
        self.assertIn("--control-token-env", argv)
        self.assertEqual(
            argv[argv.index("--control-token-env") + 1],
            heartbeat.CONTROL_TOKEN_ENV,
        )
        token = self._manager_instance()._control_tokens.get(job_id)
        self.assertIsInstance(token, str)
        self.assertGreaterEqual(len(token), 32)
        job_text = (Path(started["status_path"]).parent / "job.json").read_text(encoding="utf-8")
        self.assertNotIn(token, job_text)
        status = self._wait_status(job_id, lambda s: s["running"] and s["heartbeat"]["present"])
        self.assertEqual(status["heartbeat"]["adapter"]["conversation_id"], "conv-test-1")
        self.assertEqual(status["session"]["conversation_id"], "conv-test-1")
        self.assertEqual(status["heartbeat"]["adapter"]["schema"], heartbeat.STATUS_SCHEMA)
        self.assertNotEqual(status["session"]["provider_session"], status["session"]["conversation_id"])
        final = self._wait_status(job_id, lambda s: s["final"])
        if final["phase"] != "finished":
            job_dir = Path(started["status_path"]).parent
            print("FINAL", json.dumps(final, indent=2))
            for name in ("supervisor.log", "stderr.log", "stdout.log"):
                path = job_dir / name
                print(f"--- {name} ---")
                print(path.read_text(encoding="utf-8", errors="replace") if path.exists() else "(missing)")
        self.assertEqual(final["phase"], "finished")

    def test_optional_hard_timeout_with_heartbeat(self):
        self.env["FAKE_HEARTBEAT_FLAGS"] = "1"
        self.env["FAKE_LAUNCHER_MODE"] = "fast"
        self._reset_manager()
        started = self._manager_instance().start_worker(
            brief="heartbeat with explicit cutoff", hard_timeout_seconds=120
        )
        job = json.loads((Path(started["status_path"]).parent / "job.json").read_text(encoding="utf-8"))
        argv = job["launcher"]["argv"]
        self.assertIn("--heartbeat-interval", argv)
        self.assertEqual(argv[argv.index("--timeout") + 1], "120")
        self.assertEqual(job["limits"]["hard_timeout_seconds"], 120)
        self._wait_status(started["job_id"], lambda s: s["final"])

    def test_actual_heartbeat_client_accepts_contract_fixture(self):
        """Cross-check the fixture against the landed dsh_heartbeat client."""
        from reality_engine.scripts.dsh_heartbeat import ControlTransport

        self.env["FAKE_HEARTBEAT_FLAGS"] = "1"
        self.env["FAKE_LAUNCHER_MODE"] = "control"
        self.env["FAKE_LAUNCHER_SLEEP"] = "5"
        self._reset_manager()
        started = self._manager_instance().start_worker(brief="control contract cross-check")
        job_id = started["job_id"]
        self._wait_status(
            job_id, lambda s: s["running"] and s["heartbeat"].get("control_available")
        )
        token = self._manager_instance()._control_tokens[job_id]
        control_path = Path(started["status_path"]).parent / "result.md.control.json"
        wrong_run = ControlTransport(control_path, token=token, run_id="wrong-run")
        rejected_run = wrong_run.ping(
            ping_id="wrong-run-ping", sequence=1, message="wrong run"
        )
        self.assertFalse(rejected_run.ok, rejected_run)
        self.assertEqual(rejected_run.status_code, 403)
        wrong_session = ControlTransport(
            control_path, token=token, run_id="fake-run-1", session_id="wrong-session"
        )
        rejected_session = wrong_session.ping(
            ping_id="wrong-session-ping",
            sequence=1,
            message="wrong session",
            session_id="wrong-session",
        )
        self.assertFalse(rejected_session.ok, rejected_session)
        self.assertEqual(rejected_session.status_code, 409)
        transport = ControlTransport(control_path, token=token, run_id="fake-run-1")
        delivery = transport.ping(
            ping_id="cross-check-ping", sequence=1, message="cross-check"
        )
        self.assertTrue(delivery.ok, delivery)
        self.assertTrue(delivery.queued)
        self._manager_instance().cancel_worker(job_id, confirm=True)

    def test_result_bounds_and_failed_run_does_not_return_reasoning(self):
        self.env["FAKE_LAUNCHER_MODE"] = "fast"
        self.env["FAKE_LAUNCHER_OUTPUT"] = "x" * 200_000
        self._reset_manager()
        started = self._manager_instance().start_worker(brief="big result")
        job_id = started["job_id"]
        self._wait_status(job_id, lambda s: s["final"])
        bounded = self._manager_instance().worker_result(job_id, max_bytes=512)
        self.assertLessEqual(len(bounded["content"].encode("utf-8")), 512)
        self.assertTrue(bounded["truncated"])
        self.assertGreater(bounded["result_bytes"], 100_000)
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().worker_result(job_id, max_bytes=10)
        self.assertEqual(ctx.exception.code, "result_limit_invalid")

        self.env["FAKE_LAUNCHER_MODE"] = "fail"
        self.env["FAKE_LAUNCHER_OUTPUT"] = "unused"
        self._reset_manager()
        failed = self._manager_instance().start_worker(brief="fail task")
        failed_id = failed["job_id"]
        failed_status = self._wait_status(failed_id, lambda s: s["final"])
        self.assertEqual(failed_status["phase"], "failed")
        self.assertEqual(failed_status["exit_code"], 3)
        result = self._manager_instance().worker_result(failed_id)
        self.assertNotIn("secret reasoning", result["content"])
        self.assertNotIn("secret reasoning", json.dumps(result.get("warnings")))
        self.assertIn("partial output", result["content"])

    def test_concurrency_and_read_only_policy(self):
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "20"
        self._reset_manager()
        first = self._manager_instance().start_worker(brief="writer one", permission="workspace-write")
        self.assertTrue(first["ok"], first)
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(brief="writer two", permission="workspace-write")
        self.assertEqual(ctx.exception.code, "workspace_busy")
        read_only = self._manager_instance().start_worker(brief="reader", permission="read-only")
        self.assertTrue(read_only["ok"], read_only)
        self._manager_instance().cancel_worker(read_only["job_id"], confirm=True)
        self._manager_instance().cancel_worker(first["job_id"], confirm=True)
        third = self._manager_instance().start_worker(brief="writer three", permission="workspace-write")
        self.assertTrue(third["ok"], third)
        self._manager_instance().cancel_worker(third["job_id"], confirm=True)

    def test_stale_and_lost_classification(self):
        runtime = Path(self.env["DSH_WORKER_RUNTIME_DIR"])
        jobs = runtime / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        job_id = "20261021T000000Z-deadbeef"
        job_dir = jobs / job_id
        job_dir.mkdir()
        old = "2026-10-20T00:00:00+00:00"
        (job_dir / "job.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "job_id": job_id,
                    "created_at": old,
                    "workspace": str(self.root),
                    "permission": "read-only",
                    "heartbeat": {"interval_seconds": 900, "missed_replies_allowed": 2},
                }
            ),
            encoding="utf-8",
        )
        current_pid = os.getpid()
        current_ticks = procutil.process_creation_time(current_pid)
        (job_dir / "status.json").write_text(
            json.dumps(
                {
                    "phase": "running",
                    "started_at": old,
                    "updated_at": old,
                    "supervisor_pid": current_pid,
                    "supervisor_creation_time": current_ticks,
                    "worker_pid": current_pid,
                    "worker_creation_time": current_ticks,
                }
            ),
            encoding="utf-8",
        )
        stale_env = dict(self.env)
        stale_env["DSH_WORKER_STALE_AFTER_SECONDS"] = "30"
        stale = core.Manager(core.load_config(stale_env)).get_status(job_id)
        self.assertTrue(stale["running"], stale)
        self.assertTrue(stale["stale"], stale)

        (job_dir / "status.json").write_text(
            json.dumps(
                {
                    "phase": "running",
                    "started_at": old,
                    "updated_at": old,
                    "supervisor_pid": 999_999,
                    "worker_pid": 999_999,
                }
            ),
            encoding="utf-8",
        )
        lost = self._manager_instance().get_status(job_id)
        self.assertEqual(lost["phase"], "lost")
        self.assertTrue(lost["final"])
        self.assertFalse(lost["running"])

    def test_heartbeat_launch_args_unit(self):
        capabilities = heartbeat.LauncherCapabilities(
            frozenset(
                {
                    "--heartbeat-interval",
                    "--heartbeat-misses",
                    "--status-file",
                    "--control-token-env",
                }
            )
        )
        args, record = heartbeat.heartbeat_launch_args(capabilities, Path("C:/job"), 900, 2)
        self.assertIn("--heartbeat-interval", args)
        self.assertEqual(record["mode"], "launcher_heartbeat")
        self.assertFalse(record["degraded"])
        self.assertTrue(capabilities.control_token_supported)
        with self.assertRaises(RuntimeError):
            heartbeat.heartbeat_launch_args(
                heartbeat.LauncherCapabilities(frozenset({"--timeout"})),
                Path("C:/job"),
                900,
                2,
            )
        with self.assertRaises(RuntimeError):
            heartbeat.heartbeat_launch_args(
                heartbeat.LauncherCapabilities(
                    frozenset({"--heartbeat-interval", "--heartbeat-misses", "--status-file"})
                ),
                Path("C:/job"),
                900,
                2,
            )
        self.assertIsNone(heartbeat.message_length_error("x" * 4000))
        self.assertIsNotNone(heartbeat.message_length_error("x" * 4001))
        # JavaScript counts UTF-16 code units; astral characters must not slip
        # past a 4000-character Python len() check and get truncated.
        self.assertIsNotNone(heartbeat.message_length_error("\U0001f600" * 2001))


if __name__ == "__main__":
    unittest.main()
