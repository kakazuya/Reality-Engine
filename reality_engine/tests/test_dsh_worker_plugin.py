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
import sqlite3
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO / "plugins" / "dsh-worker"
SERVER_DIR = PLUGIN_ROOT / "server"
SERVER = SERVER_DIR / "dsh_worker_mcp.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAKE_LAUNCHER = FIXTURES / "dsh_worker_fake_launcher.py"
# Every test temp dir lives under the plugin's gitignored runtime, not the
# platform temp: the agent sandbox may only write inside the repository.
TEST_TMP = PLUGIN_ROOT / "runtime" / "test-tmp"

sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(FIXTURES))
sys.path.insert(0, str(REPO / "reality_engine" / "scripts"))

import build_worker_context  # noqa: E402
import context_pack  # noqa: E402
import core  # noqa: E402
import heartbeat  # noqa: E402
import jobs  # noqa: E402
import procutil  # noqa: E402
import progress  # noqa: E402
import store  # noqa: E402
import supervisor  # noqa: E402
from dsh_worker_testenv import make_temp_dir, remove_tree, run_async  # noqa: E402

OFF_PEAK = "2026-10-21T03:00:00+05:30"
PEAK = "2026-10-21T07:00:00+05:30"
FAKE_GO_SESSION = '''"""Fake stable provider session for offline plugin tests."""
def session_id(job, model, key="", lane_no=None):
    return "provider-session-test"
'''


class PluginTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        self.root = make_temp_dir(TEST_TMP, "plugin-tests-")
        scripts = self.root / "reality_engine" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "go_session.py").write_text(FAKE_GO_SESSION, encoding="utf-8")
        self.env = os.environ.copy()
        self.env.pop("DSH_SESSION_LABEL", None)
        # The offline suite runs against a fake repository; the host's real data
        # root (set when this suite runs inside a worktree) must not leak in.
        self.env.pop("REALITY_DATA_ROOT", None)
        self.env.update(
            {
                "DSH_WORKER_REPO_ROOT": str(self.root),
                "DSH_WORKER_RUNTIME_DIR": str(self.root / "runtime"),
                # Worktrees are always created under the test temp root.
                "DSH_WORKTREES_ROOT": str(self.root / "worktrees"),
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
                remove_tree(self.root)
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
        return run_async(coro, timeout)

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

        # An existing directory outside the configured repository is refused;
        # TEST_TMP is the parent of this test's temp repo.
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(brief="work", workspace=str(TEST_TMP))
        self.assertEqual(ctx.exception.code, "workspace_outside_repo")
        outside_brief = TEST_TMP / f"outside-brief-{os.getpid()}.md"
        outside_brief.write_text("outside", encoding="utf-8")
        self.addCleanup(lambda: outside_brief.unlink(missing_ok=True))
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(task_file=str(outside_brief))
        self.assertEqual(ctx.exception.code, "task_file_outside_repo")
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(task_file=f"../{outside_brief.name}")
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
        self.assertEqual(job["progress_interval_seconds"], 1200)
        self.assertEqual(started["progress_interval_seconds"], 1200)
        self.assertEqual(Path(started["progress_path"]).name, "progress.jsonl")
        self.assertEqual(Path(started["progress_notes_path"]).name, "PROGRESS_NOTES.md")
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
        # The brief carries the standing context header + the caller's text and
        # appends a standing progress instruction; it is never a question.
        self.assertTrue(record["task"].startswith("## Worker context pack (auto-attached)"))
        self.assertIn("Do the fake task", record["task"])
        self.assertIn("CONTEXT.md", record["task"])
        self.assertIn("PROGRESS_NOTES.md", record["task"])
        self.assertNotIn("?", core.PROGRESS_NOTES_INSTRUCTION)
        self.assertEqual(
            record["env_progress_notes"],
            str(Path(started["progress_notes_path"]).resolve()),
        )
        final = self._wait_status(job_id, lambda s: s["final"])
        self.assertEqual(final["phase"], "finished")
        self.assertEqual(final["exit_code"], 0)
        self.assertTrue(final["result_ready"])
        # A short job produces exactly the final digest (default cadence 20m).
        digest_path = Path(started["progress_path"])
        deadline = time.monotonic() + 10
        while not digest_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(digest_path.exists())
        digests = progress.read_digests(digest_path.parent)
        self.assertEqual(len(digests), 1, digests)
        self.assertTrue(digests[0]["final"])
        self.assertEqual(digests[0]["phase"], "finished")
        self.assertEqual(digests[0]["digest"], 1)
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
        self.env["DSH_WORKER_TEST_LEASE_SECONDS"] = "6"
        self._reset_manager()
        started = self._manager_instance().start_worker(brief="endless responsive task")
        job_id = started["job_id"]
        job_dir = Path(started["status_path"]).parent
        lease_path = job_dir / "controller_lease.json"
        self.assertTrue(lease_path.exists())
        # The fake launcher needs to start and write its partial output before
        # the lease expires; 2 s was a startup race on a loaded machine.
        final = self._wait_status(job_id, lambda s: s["final"], timeout=20.0)
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

        # Another MCP server process (different session label) can see the job
        # but cannot renew an unclaimed lease.  claim_worker takes ownership,
        # after which renewal needs no adopt=true; the cap is 7200 s.
        other_env = dict(self.env)
        other_env["DSH_SESSION_LABEL"] = "session-other"
        other = core.Manager(core.load_config(other_env))
        status = other.get_status(job_id)
        self.assertEqual(status["owner_session"], self._manager_instance().config.session_label)
        self.assertEqual(status["steering"]["session_label"], "session-other")
        with self.assertRaises(core.PluginError) as ctx:
            other.renew_worker_lease(job_id, extend_seconds=4)
        self.assertEqual(ctx.exception.code, "controller_unavailable")
        self.assertIn("claim_worker", ctx.exception.message)
        self.assertEqual(
            json.loads(lease_path.read_text(encoding="utf-8"))["deadline"], after_renew
        )
        claimed = other.claim_worker(job_id, "acceptance takeover")
        self.assertTrue(claimed["ok"], claimed)
        self.assertEqual(claimed["owner_session"], "session-other")
        self.assertEqual(claimed["previous_owner_session"], self._manager_instance().config.session_label)
        self.assertEqual(other.get_status(job_id)["owner_session"], "session-other")
        renewed_other = other.renew_worker_lease(job_id, extend_seconds=7200)
        self.assertTrue(renewed_other["ok"], renewed_other)
        self.assertEqual(renewed_other["controller_lease"]["lease_seconds"], 7200)
        self.assertFalse(renewed_other["adopted"])
        with self.assertRaises(core.PluginError) as ctx:
            other.renew_worker_lease(job_id, extend_seconds=7201)
        self.assertEqual(ctx.exception.code, "lease_extension_invalid")
        after_renew = renewed_other["controller_lease"]["deadline"]
        steering = [
            json.loads(line)
            for line in (job_dir / "steering.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertIn("claim", {entry["kind"] for entry in steering})
        self.assertIn("renew", {entry["kind"] for entry in steering})
        self.assertTrue(any(entry["session"] == "session-other" for entry in steering))

        # A copied/wrong-owner lease is rejected rather than extended.  A fake
        # job record is used so no real supervisor races the assertion.
        fake_id = "20261021T030303Z-0000aaaa"
        fake_dir = Path(self.env["DSH_WORKER_RUNTIME_DIR"]) / "jobs" / fake_id
        fake_dir.mkdir(parents=True)
        pid = os.getpid()
        ticks = procutil.process_creation_time(pid)
        (fake_dir / "job.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "job_id": fake_id,
                    "created_at": core.iso(),
                    "workspace": str(self.root),
                    "permission": "read-only",
                    "controller_lease_owner_id": "owner-a",
                    "owner_session": "session-other",
                }
            ),
            encoding="utf-8",
        )
        (fake_dir / "status.json").write_text(
            json.dumps(
                {
                    "phase": "running",
                    "started_at": core.iso(),
                    "supervisor_pid": pid,
                    "supervisor_creation_time": ticks,
                    "worker_pid": pid,
                    "worker_creation_time": ticks,
                }
            ),
            encoding="utf-8",
        )
        (fake_dir / "controller_lease.json").write_text(
            json.dumps(
                {
                    "schema": store.LEASE_SCHEMA,
                    "job_id": fake_id,
                    "owner_id": "wrong-owner",
                    "created_at": core.iso(),
                    "renewed_at": core.iso(),
                    "deadline": core.iso(core.utc_now() + core.timedelta(seconds=600)),
                    "lease_seconds": 600,
                    "renewals": 0,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(core.PluginError) as ctx:
            other.renew_worker_lease(fake_id, extend_seconds=4)
        self.assertEqual(ctx.exception.code, "lease_invalid")

        self._manager_instance().cancel_worker(job_id, confirm=True)
        self.assertFalse(lease_path.exists(), "cancellation must remove the lease")

    def test_workspace_must_be_repo_root_or_registered_worktree(self):
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "20"
        self._reset_manager()
        first = self._manager_instance().start_worker(
            brief="root writer",
            workspace=".",
            permission="workspace-write",
            confirm_repo_root_write=True,
        )
        self.assertTrue(first["ok"], first)
        # A subdirectory is not its own checkout, so it is not a workspace.
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(
                brief="subdir writer",
                workspace="reality_engine",
                permission="workspace-write",
            )
        self.assertEqual(ctx.exception.code, "workspace_not_registered")
        # The root workspace is a single checkout: a second root writer waits.
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(
                brief="second root writer",
                workspace=".",
                permission="workspace-write",
                confirm_repo_root_write=True,
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
                    "worker_progress",
                    "renew_worker_lease",
                    "claim_worker",
                    "inspect_run",
                    "server_info",
                    "merge_worker",
                    "remove_worktree",
                    "push",
                    "list_jobs",
                    "start_job",
                    "job_log",
                },
            )
            by_name = {tool.name: tool for tool in tools.tools}
            self.assertIn("7200", by_name["renew_worker_lease"].description)
            self.assertIn("steering.jsonl", by_name["claim_worker"].description)
            self.assertIn("use_worktree", by_name["start_worker"].description)
            self.assertIn("merge --abort", by_name["merge_worker"].description)
            self.assertIn("confirm=true", by_name["push"].description)
            self.assertIn("jobs.yaml", by_name["list_jobs"].description)
            self.assertIn("stall", by_name["worker_progress"].description)
            self.assertIn("Status check", by_name["message_worker"].description)
            self.assertIn("progress_interval_seconds", by_name["start_worker"].description)
            self.assertIn("confirm_repo_root_write", by_name["start_worker"].description)
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
                {
                    "brief": "Slow fake task",
                    "workspace": ".",
                    "permission": "workspace-write",
                    "confirm_repo_root_write": True,
                },
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
            # A status ping is explicitly framed as non-final, so the worker
            # answers one line and keeps working.
            status_text = nudge["message"][0]["text"]
            self.assertTrue(status_text.startswith(core.STATUS_CHECK_PREFIX), status_text)
            self.assertTrue(status_text.endswith("please continue"))
            followup_path = Path(started["status_path"]).parent / "followup.json"
            followup_delivery = await self._call(
                session,
                "message_worker",
                {
                    "job_id": job_id,
                    "message": "what should the next step be?",
                    "kind": "followup",
                    "conversation_id": "conv-test-1",
                },
            )
            self.assertTrue(followup_delivery["ok"], followup_delivery)
            followup = json.loads(followup_path.read_text(encoding="utf-8"))
            self.assertEqual(
                followup["message"][0]["text"], "what should the next step be?"
            )
            self.assertNotIn(core.STATUS_CHECK_PREFIX, followup["message"][0]["text"])
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
            # The DPAPI-encrypted token is readable by any server process of
            # this Windows user, so control survives a server restart.
            self.assertTrue(restarted_status["heartbeat"]["control_available"])
            self.assertTrue(restarted_status["heartbeat"]["control_token_available"])
            self.assertIsNone(
                restarted_status["heartbeat"]["control_unavailable_reason"]
            )
            after_restart = restarted_manager.message_worker(
                job_id, "after restart", conversation_id="conv-test-1"
            )
            self.assertTrue(after_restart["ok"], after_restart)
            after_text = json.loads(nudge_path.read_text(encoding="utf-8"))["message"][0]["text"]
            self.assertTrue(after_text.startswith(core.STATUS_CHECK_PREFIX), after_text)
            self.assertTrue(after_text.endswith("after restart"))
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

    def test_worker_progress_digests_shape_and_list_row(self):
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "30"
        self.env["FAKE_LAUNCHER_EVENTS"] = "1"
        self._reset_manager()

        async def scenario(session):
            started = await self._call(
                session,
                "start_worker",
                {"brief": "progress surface", "progress_interval_seconds": 1},
            )
            self.assertTrue(started["ok"], started)
            job_id = started["job_id"]
            await self._await_tool_status(session, job_id, lambda s: s["running"])
            digest_path = Path(started["progress_path"])
            # Wait for the first periodic digest (1 s cadence).
            deadline = time.monotonic() + 20
            response: dict = {}
            while time.monotonic() < deadline:
                response = await self._call(
                    session, "worker_progress", {"job_id": job_id}
                )
                digests = response.get("digests") or []
                # The first scheduled digest can land before the launcher has
                # written its first event line under load; wait for one that
                # has seen the stream instead of asserting on an empty sample.
                if digests and int(digests[0].get("tool_calls") or 0) >= 3:
                    break
                await asyncio.sleep(0.1)
            self.assertTrue(digest_path.exists(), "no progress.jsonl appeared")
            self.assertTrue(response.get("digests"), response)
            self.assertEqual(response["job_id"], job_id)
            newest = response["digests"][0]
            for key in (
                "at",
                "phase",
                "elapsed_seconds",
                "tool_calls",
                "tool_calls_by_tool",
                "tool_calls_delta",
                "model_steps",
                "output_tokens",
                "last_tool",
                "last_tool_target",
                "files_written",
                "files_written_count",
                "idle_seconds",
                "lease_seconds_left",
                "stall",
                "worker_text_tail",
                "note",
            ):
                self.assertIn(key, newest)
            self.assertEqual(newest["job_id"], job_id)
            self.assertFalse(newest["final"])
            self.assertGreaterEqual(newest["tool_calls"], 3)
            self.assertEqual(newest["last_tool"], "write")
            self.assertTrue(
                any(
                    "out/report.md" in record["files_written"]
                    for record in response["digests"]
                ),
                response["digests"],
            )
            # Newest first, and all running jobs when job_id is omitted.
            positions = [record["at"] for record in response["digests"]]
            self.assertEqual(positions, sorted(positions, reverse=True))
            all_running = await self._call(session, "worker_progress", {})
            self.assertIn(job_id, all_running["jobs_scanned"])
            self.assertTrue(
                any(record["job_id"] == job_id for record in all_running["digests"])
            )
            future = await self._call(
                session,
                "worker_progress",
                {"job_id": job_id, "since": "2099-01-01T00:00:00Z"},
            )
            self.assertEqual(future["count"], 0)
            self.assertEqual(future["digests"], [])
            bad_since = await self._call(
                session, "worker_progress", {"job_id": job_id, "since": "yesterday"}
            )
            self.assertEqual(bad_since["error"]["code"], "since_invalid")
            listed = await self._call(session, "list_workers", {})
            row = next(item for item in listed["jobs"] if item["job_id"] == job_id)
            self.assertIsNotNone(row["last_digest_at"])
            self.assertIn("tool calls", row["digest_summary"])

            await self._call(session, "cancel_worker", {"job_id": job_id, "confirm": True})
            # Cancellation still leaves a final digest behind.
            deadline = time.monotonic() + 15
            last: dict = {}
            while time.monotonic() < deadline:
                last = await self._call(session, "worker_progress", {"job_id": job_id})
                if last.get("digests") and last["digests"][0].get("final"):
                    break
                await asyncio.sleep(0.1)
            self.assertTrue(last["digests"], last)
            self.assertTrue(last["digests"][0]["final"], last["digests"][0])
            self.assertEqual(last["digests"][0]["phase"], "cancelled")

        self._run(self._with_session(scenario), timeout=120)

    def test_progress_interval_zero_disables_digests(self):
        self._reset_manager()
        started = self._manager_instance().start_worker(
            brief="no digests", progress_interval_seconds=0
        )
        self.assertEqual(started["progress_interval_seconds"], 0)
        final = self._wait_status(started["job_id"], lambda s: s["final"])
        self.assertEqual(final["phase"], "finished")
        self.assertFalse(Path(started["progress_path"]).exists())
        self.assertFalse(Path(started["progress_md_path"]).exists())
        listed = self._manager_instance().list_workers()
        row = next(item for item in listed["jobs"] if item["job_id"] == started["job_id"])
        self.assertIsNone(row["last_digest_at"])
        self.assertIsNone(row["digest_summary"])

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
        first = self._manager_instance().start_worker(
            brief="writer one", permission="workspace-write", confirm_repo_root_write=True
        )
        self.assertTrue(first["ok"], first)
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(
                brief="writer two", permission="workspace-write", confirm_repo_root_write=True
            )
        self.assertEqual(ctx.exception.code, "workspace_busy")
        read_only = self._manager_instance().start_worker(brief="reader", permission="read-only")
        self.assertTrue(read_only["ok"], read_only)
        self._manager_instance().cancel_worker(read_only["job_id"], confirm=True)
        self._manager_instance().cancel_worker(first["job_id"], confirm=True)
        third = self._manager_instance().start_worker(
            brief="writer three", permission="workspace-write", confirm_repo_root_write=True
        )
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

    # ------------------------------------------------------ shared control
    def test_control_token_persisted_encrypted_and_shared_across_sessions(self):
        self.env["FAKE_LAUNCHER_MODE"] = "control"
        self.env["FAKE_LAUNCHER_SLEEP"] = "20"
        self._reset_manager()
        started = self._manager_instance().start_worker(brief="shared control task")
        job_id = started["job_id"]
        job_dir = Path(started["status_path"]).parent
        self.assertTrue(started["control_token_persisted"])
        status = self._wait_status(
            job_id, lambda s: s["running"] and s["heartbeat"].get("control_available")
        )
        token = self._manager_instance()._control_tokens[job_id]
        token_file = job_dir / store.TOKEN_FILE
        self.assertTrue(token_file.is_file())
        self.assertNotIn(token.encode(), token_file.read_bytes(), "token must be encrypted")
        self.assertEqual(
            store.dpapi_unprotect(token_file.read_bytes()).decode("utf-8"), token
        )
        for name in ("job.json", "status.json"):
            self.assertNotIn(token, (job_dir / name).read_text(encoding="utf-8"))
        self.assertNotIn(token, json.dumps(status))
        self.assertNotIn(token, json.dumps(self._manager_instance().worker_result(job_id)))

        # A second MCP server (different session identity) decrypts the same
        # persisted token and can steer the job.
        other_env = dict(self.env)
        other_env["DSH_SESSION_LABEL"] = "session-B"
        other = core.Manager(core.load_config(other_env))
        other_status = other.get_status(job_id)
        self.assertTrue(other_status["heartbeat"]["control_token_available"])
        self.assertTrue(other_status["heartbeat"]["control_available"])
        self.assertEqual(
            other_status["owner_session"], self._manager_instance().config.session_label
        )
        listed = other.list_workers()
        row = next(item for item in listed["jobs"] if item["job_id"] == job_id)
        self.assertEqual(row["owner_session"], self._manager_instance().config.session_label)
        self.assertIsNotNone(row["last_steerer"])
        delivered = other.message_worker(job_id, "steer from session B")
        self.assertTrue(delivered["ok"], delivered)
        self.assertTrue((job_dir / "nudge.json").is_file())
        claimed = other.claim_worker(job_id, "session B takes over")
        self.assertTrue(claimed["ok"], claimed)
        renewed = other.renew_worker_lease(job_id, extend_seconds=7200)
        self.assertTrue(renewed["ok"], renewed)
        self.assertEqual(renewed["controller_lease"]["lease_seconds"], 7200)
        self.assertEqual(other.get_status(job_id)["last_steerer"], "session-B")
        cancelled = other.cancel_worker(job_id, confirm=True, reason="shared control done")
        self.assertTrue(cancelled["ok"], cancelled)

        steering_text = (job_dir / "steering.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(token, steering_text)
        steering = [json.loads(line) for line in steering_text.splitlines()]
        kinds = {entry["kind"] for entry in steering}
        self.assertTrue({"start", "message", "claim", "renew", "cancel"} <= kinds, kinds)
        sessions = {entry["session"] for entry in steering}
        self.assertIn("session-B", sessions)
        self.assertIn(self._manager_instance().config.session_label, sessions)
        for entry in steering:
            self.assertLessEqual(len(entry["text"]), core.MAX_STEERING_TEXT)
            self.assertIsInstance(entry["at"], str)

    def test_legacy_job_without_persisted_token_reports_unavailable(self):
        job_id = "20261021T030404Z-0000bbbb"
        job_dir = Path(self.env["DSH_WORKER_RUNTIME_DIR"]) / "jobs" / job_id
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
                    "owner_session": "legacy-session",
                }
            ),
            encoding="utf-8",
        )
        (job_dir / "status.json").write_text(
            json.dumps(
                {
                    "phase": "running",
                    "started_at": core.iso(),
                    "supervisor_pid": pid,
                    "supervisor_creation_time": ticks,
                    "worker_pid": pid,
                    "worker_creation_time": ticks,
                }
            ),
            encoding="utf-8",
        )
        (job_dir / "result.md.control.json").write_text(
            json.dumps(
                {
                    "schema": heartbeat.CONTROL_SCHEMA,
                    "state": "bound",
                    "host": "127.0.0.1",
                    "port": 9,
                    "pid": pid,
                    "run_id": "legacy-run",
                    "session_id": "legacy-conversation",
                }
            ),
            encoding="utf-8",
        )
        status = self._manager_instance().get_status(job_id)
        self.assertFalse(status["heartbeat"]["control_token_available"])
        self.assertFalse(status["heartbeat"]["control_available"])
        self.assertTrue(status["heartbeat"]["control_descriptor_available"])
        self.assertEqual(
            status["heartbeat"]["control_unavailable_reason"], "control_token_missing"
        )
        response = self._manager_instance().message_worker(job_id, "legacy?")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "transport_unavailable")

    # ----------------------------------------------------------- worktrees
    def _git(self, *args: str, expect_ok: bool = True) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
        if expect_ok:
            self.assertEqual(
                completed.returncode, 0, completed.stdout + "\n" + completed.stderr
            )
        return completed.stdout.strip()

    def _init_git_repo(self) -> str:
        self._git("init", "-b", "main")
        self._git("config", "user.name", "dsh worker test")
        self._git("config", "user.email", "dsh-worker-test@example.invalid")
        (self.root / "README.md").write_text("initial\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "initial")
        return self._git("rev-parse", "HEAD")

    def _start_worktree_job(
        self, write_file=None, write_text="worker change\n", brief="worktree task", test_cmd=None
    ):
        if write_file:
            self.env["FAKE_LAUNCHER_WRITE_FILE"] = write_file
            self.env["FAKE_LAUNCHER_WRITE_TEXT"] = write_text
        self._reset_manager()
        started = self._manager_instance().start_worker(
            brief=brief,
            permission="workspace-write",
            use_worktree=True,
            test_cmd=test_cmd,
        )
        final = self._wait_status(started["job_id"], lambda s: s["final"])
        self.assertEqual(final["phase"], "finished", final)
        return started, final

    def _commit_main(self, relative: str, text: str, message: str) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", message)
        return self._git("rev-parse", "HEAD")

    def _write_jobs_registry(self, entries: list[dict]) -> Path:
        path = self.root / "test-jobs.yaml"
        path.write_text(
            yaml.safe_dump(
                {"schema": "dsh-worker-jobs/1", "jobs": entries}, sort_keys=False
            ),
            encoding="utf-8",
        )
        self.env["DSH_WORKER_JOBS_FILE"] = str(path)
        self._reset_manager()
        return path

    @staticmethod
    def _fake_job(
        name: str,
        command: str,
        *,
        enabled: bool = True,
        locks: list[str] | None = None,
        success_check: dict | None = None,
        cadence: str = "daily",
        off_peak_only: bool = False,
    ) -> dict:
        return {
            "name": name,
            "description": f"offline fake job {name}",
            "argv": ["python", "-c", command],
            "cwd": ".",
            "env": {},
            "writes": ["none (offline fake)"],
            "resource_locks": locks or [],
            "cadence": cadence,
            "success_check": success_check,
            "off_peak_only": off_peak_only,
            "market_hours": "any",
            "needs_paid_api": False,
            "needs_gpu": False,
            "enabled": enabled,
        }

    def _make_test_db(self, value: str) -> Path:
        data_root = self.root / "reality_engine" / "data"
        data_root.mkdir(parents=True, exist_ok=True)
        path = data_root / "test-standalone.db"
        connection = sqlite3.connect(path)
        try:
            connection.execute("DROP TABLE IF EXISTS runs")
            connection.execute("CREATE TABLE runs (d TEXT)")
            connection.execute("INSERT INTO runs (d) VALUES (?)", (value,))
            connection.commit()
        finally:
            # sqlite3 connections live in reference cycles; the context manager
            # does not close them, and an open handle blocks Windows cleanup.
            connection.close()
        return path

    def test_worktree_start_auto_commit_branch_and_data_env(self):
        base_commit = self._init_git_repo()
        self.env["FAKE_LAUNCHER_WRITE_FILE"] = "worker_out.txt"
        self.env["FAKE_LAUNCHER_WRITE_TEXT"] = "written in the worktree\n"
        self._reset_manager()
        started = self._manager_instance().start_worker(
            brief="Add worker file\n\nsecond line should not be the subject",
            permission="workspace-write",
            use_worktree=True,
        )
        self.assertTrue(started["ok"], started)
        job_id = started["job_id"]
        job_dir = Path(started["status_path"]).parent
        worktree = Path(started["workspace"])
        self.assertEqual(worktree, (self.root / "worktrees" / job_id).resolve())
        self.assertEqual(started["worktree"]["branch"], f"dsh/{job_id}")
        self.assertEqual(started["worktree"]["base_commit"], base_commit)
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["owner_session"], self._manager_instance().config.session_label)
        self.assertEqual(job["worktree"]["base"], "HEAD")
        self.assertEqual(job["data_root"], str((self.root / "reality_engine" / "data").resolve()))
        # The context header is first; the one-line worktree preamble follows
        # it so the worker knows gitignored data comes from REALITY_DATA_ROOT.
        brief = (job_dir / "brief.md").read_text(encoding="utf-8")
        self.assertTrue(brief.startswith("## Worker context pack (auto-attached)"), brief[:200])
        self.assertIn(core.WORKTREE_PREAMBLE, brief)
        self.assertIn("Add worker file", brief)
        final = self._wait_status(job_id, lambda s: s["final"])
        self.assertEqual(final["phase"], "finished", final)
        # The baseline and final snapshots both ran through the stored identity:
        # a normal job still gets artifact hints (NEW-1 must not disable them).
        baseline = json.loads((job_dir / "baseline.json").read_text(encoding="utf-8"))
        raw_status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
        self.assertTrue(baseline["available"], baseline)
        self.assertTrue(raw_status["artifacts"]["available"], raw_status["artifacts"])
        self.assertIn("worker_out.txt", raw_status["artifacts"]["paths"])
        tree = final["worktree"]
        self.assertTrue(tree["committed"], tree)
        self.assertEqual(tree["branch"], f"dsh/{job_id}")
        self.assertEqual(tree["base"], "HEAD")
        self.assertEqual(tree["base_commit"], base_commit)
        self.assertRegex(tree["head"], r"^[0-9a-f]{40}$")
        self.assertEqual(tree["commits"], 1)
        self.assertEqual(tree["files_changed"], 1)
        self.assertEqual(tree["files_changed_paths"], ["worker_out.txt"])
        self.assertTrue(tree["commit_message"].startswith("Add worker file [dsh "), tree)
        self.assertEqual((job_dir / "worker_out.txt").exists(), False)
        # Branch, commit subject/trailer and clean worktree.
        self.assertEqual(
            self._git("rev-parse", f"dsh/{job_id}").strip(), tree["head"]
        )
        subject = subprocess.run(
            ["git", "-C", str(worktree), "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout.strip()
        self.assertEqual(subject, f"Add worker file [dsh {job_id}]")
        body = subprocess.run(
            ["git", "-C", str(worktree), "log", "-1", "--format=%B"],
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout
        self.assertIn(f"DSH-Job: {job_id}", body)
        dirty = subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout.strip()
        self.assertEqual(dirty, "")
        # Main checkout HEAD is untouched.
        self.assertEqual(self._git("rev-parse", "main"), base_commit)
        result = self._manager_instance().worker_result(job_id)
        self.assertEqual(result["worktree"]["head"], tree["head"])
        # The worker env points at the main checkout's data root by absolute path.
        launcher = json.loads((job_dir / "launcher_argv.json").read_text(encoding="utf-8"))
        self.assertEqual(
            launcher["env_reality_data_root"],
            str((self.root / "reality_engine" / "data").resolve()),
        )

    def test_worktree_empty_diff_makes_no_commit(self):
        base_commit = self._init_git_repo()
        self._reset_manager()
        started = self._manager_instance().start_worker(
            brief="No changes task", permission="workspace-write", use_worktree=True
        )
        job_id = started["job_id"]
        final = self._wait_status(job_id, lambda s: s["final"])
        self.assertEqual(final["phase"], "finished", final)
        tree = final["worktree"]
        self.assertFalse(tree["committed"], tree)
        self.assertEqual(tree["commit_reason"], "no_changes")
        self.assertEqual(tree["commits"], 0)
        self.assertEqual(tree["files_changed"], 0)
        self.assertEqual(tree["head"], base_commit)

    def test_worktree_writers_run_in_parallel_and_lock_per_worktree(self):
        base_commit = self._init_git_repo()
        self.env["FAKE_LAUNCHER_MODE"] = "slow"
        self.env["FAKE_LAUNCHER_SLEEP"] = "20"
        self.env["FAKE_LAUNCHER_WRITE_FILE"] = "change.txt"
        self._reset_manager()
        manager = self._manager_instance()
        first = manager.start_worker(
            brief="writer one", permission="workspace-write", use_worktree=True
        )
        second = manager.start_worker(
            brief="writer two", permission="workspace-write", use_worktree=True
        )
        self.assertTrue(first["ok"], first)
        self.assertTrue(second["ok"], second)
        self.assertNotEqual(first["workspace"], second["workspace"])
        locks = Path(self.env["DSH_WORKER_RUNTIME_DIR"]) / "locks"
        for started in (first, second):
            name = store.workspace_lock_name(Path(started["workspace"]), self.root)
            self.assertTrue((locks / name).is_file(), started)
        status = manager.get_status(first["job_id"])
        self.assertTrue(status["running"], status)
        # Same worktree, second writer: busy.  The main checkout is still free
        # of a *writer* only because both are in worktrees.
        with self.assertRaises(core.PluginError) as ctx:
            manager.start_worker(
                brief="same worktree",
                workspace=first["workspace"],
                permission="workspace-write",
            )
        self.assertEqual(ctx.exception.code, "workspace_busy")
        cancelled = manager.cancel_worker(second["job_id"], confirm=True)
        self.assertTrue(cancelled["ok"], cancelled)
        self.assertTrue(manager.cancel_worker(first["job_id"], confirm=True)["ok"])
        # Cancelled worktrees leave their changes uncommitted (no auto-commit).
        second_dir = Path(second["status_path"]).parent
        job = json.loads((second_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["worktree"]["base_commit"], base_commit)

    def test_invalid_worktree_base_is_refused_without_leftovers(self):
        self._init_git_repo()
        self._reset_manager()
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().start_worker(
                brief="bad base", permission="workspace-write", use_worktree=True, base="no-such-ref"
            )
        self.assertEqual(ctx.exception.code, "worktree_failed")
        worktrees_root = self.root / "worktrees"
        self.assertFalse(worktrees_root.exists() and any(worktrees_root.iterdir()))
        self.assertEqual(self._git("branch", "--list", "dsh/*"), "")

    # --------------------------------------------------------------- merge queue
    def test_merge_worker_success_runs_tests_and_removes_worktree(self):
        self._init_git_repo()
        self.env["DSH_WORKER_MERGIRAF"] = "0"
        declared = f'"{sys.executable}" -c "print(\'declared job test ran\')"'
        started, _final = self._start_worktree_job(
            write_file="merged.txt", test_cmd=declared
        )
        job_id = started["job_id"]
        pre_head = self._commit_main("main_only.txt", "main\n", "main advances")
        result = self._manager_instance().merge_worker(job_id, run_tests=True)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["merged"], result)
        self.assertEqual(result["outcome"], "merged")
        self.assertFalse(result["mergiraf_available"], result)
        self.assertEqual(result["pre_head"], pre_head)
        self.assertNotEqual(result["head"], pre_head)
        self.assertEqual(self._git("rev-parse", "main"), result["head"])
        parents = self._git("rev-list", "--parents", "-n", "1", result["head"]).split()
        self.assertEqual(len(parents), 3, "merge commit must have two parents")
        body = self._git("show", "-s", "--format=%B", result["head"])
        self.assertIn(f"[dsh {job_id}]", body.splitlines()[0])
        self.assertIn(f"DSH-Job: {job_id}", body)
        self.assertTrue((self.root / "merged.txt").is_file())
        self.assertEqual(result["files_changed"], 1)
        self.assertEqual(result["files_changed_paths"], ["merged.txt"])
        self.assertTrue(result["tests"]["passed"], result["tests"])
        # The job's declared test command ran, not the compile-only default.
        self.assertIn("declared job test ran", result["tests"]["stdout_tail"])
        self.assertNotIn("compileall", result["tests"]["command"])
        self.assertFalse(result["pushed"])
        refusal = self._manager_instance().push("main")
        self.assertFalse(refusal["ok"])
        self.assertEqual(refusal["error"]["code"], "confirmation_required")
        removed = self._manager_instance().remove_worktree(job_id, delete_branch=True)
        self.assertTrue(removed["worktree_removed"], removed)
        self.assertTrue(removed["branch_deleted"], removed)
        self.assertFalse(Path(started["workspace"]).exists())
        self.assertEqual(self._git("branch", "--list", f"dsh/{job_id}"), "")

    def test_merge_worker_default_quick_suite_runs(self):
        self._init_git_repo()
        self.env["DSH_WORKER_MERGIRAF"] = "0"
        started, _final = self._start_worktree_job(write_file="default_suite.txt")
        self._commit_main("main_only.txt", "main\n", "main advances")
        result = self._manager_instance().merge_worker(started["job_id"], run_tests=True)
        self.assertTrue(result["merged"], result)
        self.assertTrue(result["tests"]["passed"], result["tests"])
        self.assertIn("compileall", result["tests"]["command"])

    def test_merge_worker_test_failure_rolls_back(self):
        self._init_git_repo()
        self.env["DSH_WORKER_MERGIRAF"] = "0"
        started, _final = self._start_worktree_job(write_file="would_merge.txt")
        job_id = started["job_id"]
        pre_head = self._commit_main("main_only.txt", "main\n", "main advances")
        failing = f'"{sys.executable}" -c "import sys; sys.exit(7)"'
        result = self._manager_instance().merge_worker(job_id, test_cmd=failing)
        self.assertFalse(result["merged"], result)
        self.assertEqual(result["outcome"], "tests_failed")
        self.assertTrue(result["rolled_back"], result)
        self.assertTrue(result["target_clean"], result)
        self.assertEqual(result["head"], pre_head)
        self.assertEqual(result["tests"]["exit_code"], 7)
        self.assertEqual(self._git("rev-parse", "main"), pre_head)
        self.assertEqual(self._git("rev-list", "--merges", "--count", "main"), "0")
        self.assertEqual(self._git("status", "--porcelain", "--untracked-files=no"), "")
        self.assertFalse((self.root / "would_merge.txt").exists())

    def test_merge_worker_conflict_is_reported_and_aborted_clean(self):
        self._init_git_repo()
        self.env["DSH_WORKER_MERGIRAF"] = "0"
        started, _final = self._start_worktree_job(
            write_file="conflict.txt", write_text="worker\n"
        )
        job_id = started["job_id"]
        pre_head = self._commit_main("conflict.txt", "main\n", "main edits the same file")
        result = self._manager_instance().merge_worker(job_id, run_tests=False)
        self.assertFalse(result["merged"], result)
        self.assertEqual(result["outcome"], "conflict")
        self.assertEqual(result["conflicted_files"], ["conflict.txt"])
        self.assertGreaterEqual(result["hunks"]["conflict.txt"]["hunks"], 1)
        self.assertTrue(result["aborted"], result)
        self.assertTrue(result["target_clean"], result)
        self.assertEqual(self._git("rev-parse", "main"), pre_head)
        self.assertEqual(
            (self.root / "conflict.txt").read_text(encoding="utf-8"), "main\n"
        )
        merge_head = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "--verify", "--quiet", "MERGE_HEAD"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(merge_head.returncode, 0)
        self.assertEqual(self._git("status", "--porcelain", "--untracked-files=no"), "")

    def test_merge_worker_refuses_dirty_or_missing_target(self):
        self._init_git_repo()
        self.env["DSH_WORKER_MERGIRAF"] = "0"
        started, _final = self._start_worktree_job(write_file="dirty.txt")
        job_id = started["job_id"]
        (self.root / "dirty.txt").write_text("local\n", encoding="utf-8")
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().merge_worker(job_id, run_tests=False)
        self.assertEqual(ctx.exception.code, "target_dirty")
        self.assertIn("dirty.txt", ctx.exception.details.get("files", []))
        (self.root / "dirty.txt").unlink()
        with self.assertRaises(core.PluginError) as ctx:
            self._manager_instance().merge_worker(
                job_id, target="no-such-branch", run_tests=False
            )
        self.assertEqual(ctx.exception.code, "target_not_found")

    # ------------------------------------------------------------------ data jobs
    def test_jobs_yaml_audit_inventory_and_schema(self):
        registry = jobs.load_registry(PLUGIN_ROOT / "jobs.yaml")
        expected = {
            # 3.1 market chain
            "market_raw_exchange", "nse_api_raw", "bse_api_raw", "nsdl_fpi_raw",
            "fii_dii_moneycontrol", "load_market_raw", "security_master",
            "nse_pr_circuits", "nse_industry", "shareholding", "etf_nav",
            "index_tri", "board_meetings", "bse_announcements",
            "discover_bse_feed_docs", "bse_annual_report_dates", "commodity_series",
            "nse_sme_bhavcopy", "index_ohlc_breadth",
            "market_breadth_financially_free", "index_membership",
            "price_delivery_backfill", "insider_trades_normalized",
            "nse_pit_monthly_legacy", "results_xbrl_legacy",
            "integrated_results_xbrl",
            # 3.2 document corpus
            "pib_english", "pib_regional", "pib_legacy_ingest", "policy_register",
            "macro_documents", "ar_download", "ar_fact_extraction", "ar_chunking",
            "deck_discovery", "deck_figure_extraction", "concall_extraction",
            "weekly_sebi_ingest", "telegram_ingest", "video_youtube_ingest",
            "news_loop", "inbox_ingest",
            # 3.3 derived / promotion
            "truth_snapshot", "nightly_chain", "peer_substrate_promotion",
            "data_quality_gates", "query_speed_check",
            # 3.4 ops
            "boot_recover", "resource_watchdog", "deepseek_heartbeat", "db_backup",
            "capacity_loop", "continuous_loop", "forecast_tester",
            "routines_dispatcher", "drive_upload", "db_merge_migrations",
            # worker orientation pack (Task 01)
            "worker_context",
        }
        self.assertEqual(len(expected), 58)
        self.assertEqual(set(registry["order"]), expected)
        self.assertEqual(registry["schema"], jobs.REGISTRY_SCHEMA)
        sql_checks = 0
        file_checks = 0
        for name, entry in registry["jobs"].items():
            self.assertFalse(entry["enabled"], f"{name} must ship disabled")
            self.assertIn("success_check", entry)
            for field in (
                "argv", "cwd", "env", "description", "writes", "resource_locks",
                "cadence", "off_peak_only", "market_hours", "needs_paid_api",
                "needs_gpu", "enabled",
            ):
                self.assertIn(field, entry, f"{name}.{field}")
            if entry["success_check"] is not None:
                check = entry["success_check"]
                if check.get("kind") == "file":
                    file_checks += 1
                    self.assertEqual(check["path"], "tasks/worker_context/CONTEXT.md")
                    self.assertGreater(check["max_age_hours"], 0)
                else:
                    sql_checks += 1
                    self.assertTrue(check["sql"].lower().startswith(("select", "with")))
        self.assertGreaterEqual(sql_checks, 30, "most data jobs need SQL freshness checks")
        self.assertEqual(file_checks, 1)
        self.assertFalse(registry["jobs"]["concall_extraction"]["enabled"])
        self.assertTrue(registry["jobs"]["deck_figure_extraction"]["needs_gpu"])

    def test_list_jobs_freshness_history_and_disabled_refusal(self):
        check = {
            "db": "test-standalone.db",
            "sql": "SELECT max(d) AS value FROM runs",
            "expect": {"kind": "max_date", "max_age_days": 30},
        }
        self._make_test_db("2020-01-01")
        entries = [
            self._fake_job(
                "fake_fresh",
                "import pathlib; print('fresh job ran'); "
                "pathlib.Path('fresh_out.txt').write_text('ok')",
                success_check=check,
            ),
            self._fake_job("fake_disabled", "print('disabled job ran')", enabled=False),
        ]
        self._write_jobs_registry(entries)
        manager = self._manager_instance()
        listed = manager.list_jobs()
        self.assertEqual(listed["count"], 2)
        fresh = next(item for item in listed["jobs"] if item["name"] == "fake_fresh")
        self.assertTrue(fresh["never_ran"], fresh)
        self.assertTrue(fresh["stale"], fresh)
        self.assertFalse(fresh["freshness"]["ok"], fresh["freshness"])
        with self.assertRaises(core.PluginError) as ctx:
            manager.start_job("fake_disabled")
        self.assertEqual(ctx.exception.code, "job_disabled")
        started = manager.start_job("fake_fresh")
        self.assertTrue(started["ok"], started)
        final = self._wait_status(started["job_id"], lambda s: s["final"])
        self.assertEqual(final["phase"], "finished", final)
        self.assertTrue(final["progress"]["succeeded"], final)
        self.assertFalse(final["progress"]["answer_empty"], final)
        self.assertFalse(any("EMPTY answer" in w for w in final["warnings"]), final)
        self.assertTrue((self.root / "fresh_out.txt").is_file())
        self._make_test_db(core.utc_now().date().isoformat())
        listed = manager.list_jobs()
        fresh = next(item for item in listed["jobs"] if item["name"] == "fake_fresh")
        self.assertFalse(fresh["never_ran"], fresh)
        self.assertIsNotNone(fresh["last_success"], fresh)
        self.assertTrue(fresh["freshness"]["ok"], fresh["freshness"])
        self.assertFalse(fresh["stale"], fresh)
        confirmed = manager.start_job("fake_disabled", confirm=True)
        confirmed_final = self._wait_status(confirmed["job_id"], lambda s: s["final"])
        self.assertEqual(confirmed_final["phase"], "finished", confirmed_final)

    def test_resource_lock_contention(self):
        hold = self._fake_job(
            "hold_db", "import time; time.sleep(20)",
            enabled=False, locks=["db:equity_intelligence.db"],
        )
        same = self._fake_job(
            "same_db", "print('same lock')",
            enabled=False, locks=["db:equity_intelligence.db"],
        )
        other = self._fake_job(
            "other_gpu", "print('other lock')", enabled=False, locks=["gpu"],
        )
        self._write_jobs_registry([hold, same, other])
        manager = self._manager_instance()
        started = manager.start_job("hold_db", confirm=True)
        # No wait for the supervisor to reach "running": the manager's
        # reservation closes the start window, so the second start is refused
        # immediately (the old pre-check released the lock before the
        # supervisor took it).
        with self.assertRaises(core.PluginError) as ctx:
            manager.start_job("same_db", confirm=True)
        self.assertEqual(ctx.exception.code, "resource_busy")
        self.assertIn(
            "db:equity_intelligence.db", ctx.exception.details.get("resource_locks", [])
        )
        allowed = manager.start_job("other_gpu", confirm=True)
        self.assertEqual(
            self._wait_status(allowed["job_id"], lambda s: s["final"])["phase"],
            "finished",
        )
        self.assertTrue(manager.cancel_worker(started["job_id"], confirm=True)["ok"])

    # ------------------------------------------------- worker context pack
    def _write_context_pack(self, text: str = "# generated pack\n") -> Path:
        pack = self.root / "tasks" / "worker_context" / "CONTEXT.md"
        pack.parent.mkdir(parents=True, exist_ok=True)
        pack.write_text(text, encoding="utf-8")
        return pack

    @staticmethod
    def _age_path(path: Path, hours: float, base: datetime | None = None) -> None:
        anchor = base or datetime.now(timezone.utc)
        stamp = (anchor - timedelta(hours=hours)).timestamp()
        os.utime(path, (stamp, stamp))

    def test_start_worker_attaches_context_pack_header(self):
        pack = self._write_context_pack()
        started = self._manager_instance().start_worker(
            brief=(
                "Goal: attach the pack\n\n"
                "## Acceptance checks\n1. the brief starts with the header\n\n"
                "## Test command(s)\n"
                "python -m unittest reality_engine.tests.test_dsh_worker_plugin"
            )
        )
        self.assertTrue(started["ok"], started)
        self.assertFalse(started["context_pack"]["regenerated"], started["context_pack"])
        job_dir = Path(started["status_path"]).parent
        brief = (job_dir / "brief.md").read_text(encoding="utf-8")
        self.assertTrue(brief.startswith("## Worker context pack (auto-attached)"), brief[:300])
        self.assertIn(str(pack), brief)
        self.assertIn("Goal: attach the pack", brief)
        self.assertEqual([w for w in started["warnings"] if "brief_lint:" in w], [])

    def test_start_worker_context_pack_false_and_lint_warning(self):
        started = self._manager_instance().start_worker(
            brief="do the thing", context_pack=False
        )
        self.assertTrue(started["ok"], started)
        self.assertEqual(started["context_pack"]["enabled"], False)
        job_dir = Path(started["status_path"]).parent
        brief = (job_dir / "brief.md").read_text(encoding="utf-8")
        self.assertFalse(brief.startswith("## Worker context pack"), brief[:300])
        self.assertIn("do the thing", brief)
        lint = [w for w in started["warnings"] if w.startswith("brief_lint:")]
        self.assertEqual(len(lint), 3, lint)
        self.assertTrue(any("Goal" in w for w in lint))
        self.assertTrue(any("Acceptance checks" in w for w in lint))
        self.assertTrue(any("Test command" in w for w in lint))

    def test_start_worker_regenerates_stale_pack(self):
        pack = self._write_context_pack("# old pack\n")
        self._age_path(pack, 30, datetime.fromisoformat(OFF_PEAK))
        (self.root / "reality_engine" / "__init__.py").write_text("", encoding="utf-8")
        builder = self.root / "reality_engine" / "scripts" / "build_worker_context.py"
        builder.write_text(
            "from pathlib import Path\n"
            "path = Path.cwd() / 'tasks' / 'worker_context' / 'CONTEXT.md'\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "path.write_text('# regenerated by fake builder\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        started = self._manager_instance().start_worker(brief="Goal: x")
        self.assertTrue(started["ok"], started)
        self.assertTrue(started["context_pack"]["regenerated"], started["context_pack"])
        self.assertEqual(pack.read_text(encoding="utf-8"), "# regenerated by fake builder\n")

    def test_start_worker_stale_pack_failure_is_warning(self):
        pack = self._write_context_pack("# old pack\n")
        self._age_path(pack, 30, datetime.fromisoformat(OFF_PEAK))
        started = self._manager_instance().start_worker(brief="Goal: x")
        self.assertTrue(started["ok"], started)
        self.assertFalse(started["context_pack"]["regenerated"], started["context_pack"])
        self.assertTrue(
            any("context_pack:" in w for w in started["warnings"]), started["warnings"]
        )
        brief = (Path(started["status_path"]).parent / "brief.md").read_text(encoding="utf-8")
        self.assertIn("Goal: x", brief)
        self.assertIn("# old pack", pack.read_text(encoding="utf-8"))

    def test_context_pack_header_mismatch_is_stale(self):
        """A fresh mtime is not enough: header HEAD and data root must match."""
        data_root = self.root / "reality_engine" / "data"
        base = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
        stamp = base.timestamp()

        def write(header_head: str, header_data_root: str) -> Path:
            pack = self._write_context_pack(
                "# Worker context pack\n\n"
                f"Generated: 2026-10-25T12:00:00+05:30 · git HEAD: `{header_head}` · "
                f"data root: `{header_data_root}`\n"
            )
            os.utime(pack, (stamp, stamp))
            return pack

        foreign = write("deadbee", "C:/some/other/data")
        self.assertFalse(context_pack.is_stale(foreign, base))
        info = context_pack.ensure_pack(self.root, data_root, base)
        self.assertTrue(info["stale"], info)
        self.assertEqual(info.get("error"), "builder_missing")

        # A matching header needs the real short HEAD (the temp root sits inside
        # this repository, so git resolves upward to REPO).
        head = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip() or "deadbee"
        local = write(head, str(data_root.resolve()))
        self.assertFalse(
            context_pack.is_stale(local, base, repo_root=self.root, data_root=data_root)
        )
        self.assertFalse(
            context_pack.is_stale(
                write(head, str(data_root.resolve())),
                base,
                repo_root=REPO,
                data_root=data_root,
            )
        )
        self.assertTrue(
            context_pack.is_stale(
                write("deadbee", str(data_root.resolve())),
                base,
                repo_root=REPO,
                data_root=data_root,
            )
        )

    def test_file_success_check_for_worker_context(self):
        pack = self._write_context_pack()
        data_root = self.root / "reality_engine" / "data"
        check = {
            "kind": "file",
            "path": "tasks/worker_context/CONTEXT.md",
            "max_age_hours": 26,
        }
        fresh = jobs.run_success_check(check, data_root, repo_root=self.root)
        self.assertTrue(fresh["ok"], fresh)
        self._age_path(pack, 30)
        stale = jobs.run_success_check(check, data_root, repo_root=self.root)
        self.assertFalse(stale["ok"], stale)
        pack.unlink()
        missing = jobs.run_success_check(check, data_root, repo_root=self.root)
        self.assertEqual(missing["error"], "file_missing")

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


class WorkerContextBuilderTests(unittest.TestCase):
    """Offline tests for the generated orientation pack (no live DBs)."""

    def setUp(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        self.root = make_temp_dir(TEST_TMP, "context-builder-")
        self.addCleanup(remove_tree, self.root)
        engine = self.root / "reality_engine"
        engine.mkdir(parents=True)
        # A regular package (not a namespace portion) so a PYTHONPATH entry for
        # the real checkout cannot shadow the fixture in the builder subprocess.
        (engine / "__init__.py").write_text("", encoding="utf-8")
        (engine / "db").mkdir(parents=True)
        (engine / "db" / "readonly.py").write_text(
            '"""Read-only SQLite connections."""\nVALUE = 1\n', encoding="utf-8"
        )
        (engine / "scripts").mkdir()
        (engine / "scripts" / "run_thing.py").write_text(
            '"""Run the thing."""\n', encoding="utf-8"
        )
        (engine / "tests").mkdir()
        (engine / "tests" / "test_readonly.py").write_text(
            "from reality_engine.db.readonly import connect_ro\n", encoding="utf-8"
        )
        plugin = self.root / "plugins" / "fake" / "server"
        plugin.mkdir(parents=True)
        (plugin / "core.py").write_text('"""Fake plugin core."""\n', encoding="utf-8")
        runtime = self.root / "plugins" / "fake" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "fixture_ignored.py").write_text(
            '"""Ignored runtime fixture."""\n', encoding="utf-8"
        )
        cache = self.root / "plugins" / "reality-data" / "server" / "catalog_cache.json"
        cache.parent.mkdir(parents=True)
        cache.write_text(
            json.dumps(
                {
                    "databases": {
                        "truth_duckdb": {
                            "kind": "duckdb",
                            "path": str(self.root / "snap.duckdb"),
                            "tables": {
                                "px_nse_adj": {
                                    "columns": [["isin", "VARCHAR"], ["date", "DATE"]],
                                    "rows": 2540,
                                    "rows_approx": False,
                                    "date_coverage": {
                                        "column": "date",
                                        "min": "2019-01-01",
                                        "max": "2026-10-19",
                                    },
                                }
                            },
                        },
                        "equity_intelligence": {
                            "kind": "sqlite",
                            "path": str(self.root / "eq.db"),
                            "tables": {
                                "security_master": {
                                    "columns": [["isin", "TEXT"], ["symbol", "TEXT"]],
                                    "rows": 4285,
                                    "rows_approx": False,
                                },
                                "document_chunks": {
                                    "columns": [["chunk_id", "INTEGER"], ["doc_id", "INTEGER"]],
                                    "rows": 2259771,
                                    "rows_approx": False,
                                },
                                # No catalog row count: exercises the bounded
                                # COUNT(*) fallback (the live one is a view).
                                "shareholding": {
                                    "columns": [["isin", "TEXT"], ["promoter_pct", "REAL"]],
                                    "rows": None,
                                },
                            },
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        descriptions = self.root / "plugins" / "reality-data" / "catalog_descriptions.yaml"
        descriptions.write_text(
            "truth_duckdb:\n"
            "  description: Curated snapshot description.\n"
            "  tables:\n"
            "    px_nse_adj:\n"
            "      description: Curated adjusted-price table.\n"
            "equity_intelligence:\n"
            "  description: Curated main DB.\n"
            "  tables:\n"
            "    security_master:\n"
            "      description: Curated identity table.\n"
            "      key_columns: [symbol, isin]\n",
            encoding="utf-8",
        )
        tasks = self.root / "tasks"
        (tasks / "dsh_tasks").mkdir(parents=True)
        (tasks / "dsh_tasks" / "A.md").write_text("Use run_thing.py\n", encoding="utf-8")
        (tasks / "STATE.md").write_text(
            "# STATE\n\npreamble\n\n## First section\nalpha\n\n## Second section\nbeta\n",
            encoding="utf-8",
        )
        (tasks / "optimizations").mkdir()
        (tasks / "optimizations" / "00_SHARED_CONTEXT.md").write_text(
            "# shared\n\n## Known sandbox limits\n\n| problem | fix |\n|---|---|\n| x | y |\n\n"
            "## Next\nz\n",
            encoding="utf-8",
        )
        self.data = self.root / "reality_engine" / "data"
        self.data.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.data / "equity_intelligence.db")
        connection.execute(
            "CREATE TABLE shareholding (isin TEXT PRIMARY KEY, promoter_pct REAL) WITHOUT ROWID"
        )
        connection.executemany(
            "INSERT INTO shareholding VALUES (?, ?)",
            [("INE1", 55.0), ("INE2", 60.0), ("INE3", 50.0)],
        )
        connection.commit()
        connection.close()
        (self.data / "hotline").mkdir(parents=True)
        (self.data / "hotline" / "decisions.md").write_text(
            "- first decision\n"
            "- second decision mentions task-notification and sk-secretvalue\n",
            encoding="utf-8",
        )
        self.out = tasks / "worker_context"

    def _build(self, hour: int = 12):
        return build_worker_context.build(
            repo_root=self.root,
            data_root=self.data,
            out_dir=self.out,
            now=datetime(2026, 10, 25, hour, 0, tzinfo=timezone.utc),
        )

    def test_build_is_deterministic_and_covers_all_sections(self):
        stats = self._build()
        text = (self.out / "CONTEXT.md").read_text(encoding="utf-8")
        headings = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(len(headings), 7, headings)
        self.assertLessEqual(stats["tokens_estimate"], 25000)
        self.assertLess(stats["seconds"], 60)
        self.assertEqual(stats["databases"], 2)
        self.assertIn("security_master", text)
        self.assertIn("2.3M", text)
        self.assertIn("reality_engine/db/readonly.py", text)
        self.assertIn("Read-only SQLite connections.", text)
        self.assertIn("test_readonly.py", text)
        self.assertIn("Second section", text)
        self.assertIn("2019-01-01..2026-10-19", text)
        # The secret filter drops secret values, not every line mentioning one;
        # the legitimate decision line survives (only its sk- value is masked).
        self.assertNotIn("sk-secretvalue", text)
        self.assertIn("task-notification", text)
        self.assertNotIn("line(s) omitted", text)
        self.assertNotIn("KEY", text)
        self.assertNotIn("TOKEN", text)
        # The connect_ro snippet must be runnable as pasted.
        self.assertIn('DATA = Path(os.environ["REALITY_DATA_ROOT"])', text)
        self.assertIn("import os", text)
        # A WITHOUT ROWID/view has no rowid: rows come from a bounded COUNT(*).
        self.assertIn("| equity_intelligence.shareholding | 3 |", text)
        schema = self.out / "schemas" / "equity_intelligence.md"
        self.assertTrue(schema.is_file())
        self.assertIn("chunk_id", schema.read_text(encoding="utf-8"))
        # Same content, different clock: identical except the generated header line.
        again = self._build(hour=13)
        text2 = (self.out / "CONTEXT.md").read_text(encoding="utf-8")
        strip = lambda value: "\n".join(
            line for line in value.splitlines() if not line.startswith("Generated:")
        )
        self.assertEqual(strip(text), strip(text2))
        self.assertEqual(stats["schemas"], again["schemas"])

    def test_curated_catalog_descriptions_are_loaded(self):
        self.assertEqual(
            build_worker_context.DESCRIPTIONS_RELATIVE.as_posix(),
            "plugins/reality-data/catalog_descriptions.yaml",
        )
        self._build()
        text = (self.out / "CONTEXT.md").read_text(encoding="utf-8")
        self.assertIn("Curated identity table.", text)
        self.assertIn("Curated adjusted-price table.", text)
        self.assertIn("Curated main DB.", text)
        # Curated key columns win over the PREFERRED_KEYS projection.
        self.assertIn("`symbol`, `isin`", text)

    def test_repo_map_python_counts_prune_skipped_dirs(self):
        self._build()
        text = (self.out / "CONTEXT.md").read_text(encoding="utf-8")
        # plugins/fake has server/core.py plus an ignored runtime/ fixture.
        self.assertIn("fake/ (1 py)", text)

    def test_is_stale_uses_injected_clock(self):
        pack = self.root / "pack.md"
        pack.write_text("x", encoding="utf-8")
        base = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
        stamp = base.timestamp()
        os.utime(pack, (stamp, stamp))
        self.assertFalse(context_pack.is_stale(pack, base))
        self.assertTrue(context_pack.is_stale(pack, base + timedelta(hours=27)))
        self.assertTrue(context_pack.is_stale(self.root / "missing.md", base))

    def test_lint_brief(self):
        conformant = (
            "## Goal\nx\n\n## Acceptance checks\n1. y\n\n"
            "## Test command(s)\npython -m unittest x\n"
        )
        self.assertEqual(context_pack.lint_brief(conformant), [])
        warnings = context_pack.lint_brief("just do it")
        self.assertEqual(len(warnings), 3, warnings)
        self.assertTrue(all(w.startswith("brief_lint:") for w in warnings))
        # A bare command line counts even without the heading.
        self.assertEqual(
            context_pack.lint_brief(
                "## Goal\nx\n## Acceptance checks\n1. y\npython -m pytest -q"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
