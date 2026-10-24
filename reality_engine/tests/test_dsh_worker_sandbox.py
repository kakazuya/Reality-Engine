"""Task 03 sandbox/tooling tests: temp env, write scopes, first-edit metric.

Offline: no model call, no data job, no live database.  The real dsh sandbox is
exercised separately by the acceptance demo in the Task 03 report; these tests
cover the supervisor/plugin logic that decides what the sandbox is asked to do.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO / "plugins" / "dsh-worker" / "server"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEST_TMP = REPO / "plugins" / "dsh-worker" / "runtime" / "test-tmp"

sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(FIXTURES))

import core  # noqa: E402
import progress  # noqa: E402
import supervisor  # noqa: E402
from dsh_worker_testenv import make_temp_dir, remove_tree  # noqa: E402

OFF_PEAK = "2026-10-21T03:00:00+05:30"
FAKE_LAUNCHER = FIXTURES / "dsh_worker_fake_launcher.py"


def _event(kind: str, **fields) -> str:
    return json.dumps({"type": kind, **fields}) + "\n"


class OrientationMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        self.root = make_temp_dir(TEST_TMP, "sandbox-metric-")
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        remove_tree(self.root)

    def test_first_edit_index_counts_only_prior_tool_calls(self) -> None:
        events = self.root / "events.jsonl"
        events.write_text(
            _event("tool_call", tool="read", input={"file_path": "a.py"})
            + _event("tool_call", tool="grep", input={"pattern": "x"})
            + _event("tool_call", tool="write", input={"file_path": "b.py"})
            + _event("tool_call", tool="edit", input={"file_path": "b.py"}),
            encoding="utf-8",
        )
        summary = progress.EventScanner().scan(events)
        self.assertEqual(summary["tool_calls"], 4)
        self.assertEqual(summary["tool_calls_before_first_edit"], 2)

    def test_no_edit_means_no_metric(self) -> None:
        events = self.root / "events.jsonl"
        events.write_text(
            _event("tool_call", tool="read", input={"file_path": "a.py"}),
            encoding="utf-8",
        )
        summary = progress.EventScanner().scan(events)
        self.assertIsNone(summary["tool_calls_before_first_edit"])

    def test_digest_carries_metric_and_write_scope(self) -> None:
        job_dir = self.root / "job"
        job_dir.mkdir()
        (job_dir / "result.md.events.jsonl").write_text(
            _event("tool_call", tool="read", input={"file_path": "a.py"})
            + _event("tool_call", tool="write", input={"file_path": "b.py"}),
            encoding="utf-8",
        )
        writer = progress.DigestWriter(
            job_dir, "job-1", "2026-10-21T03:00:00+00:00", 60, write_scope="data"
        )
        record = writer.emit(phase="running", final=True)
        self.assertEqual(record["tool_calls_before_first_edit"], 1)
        self.assertEqual(record["write_scope"], "data")
        self.assertIsNotNone(record["orientation_seconds"])
        line = json.loads((job_dir / progress.PROGRESS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(line["tool_calls_before_first_edit"], 1)
        self.assertIn("first edit after 1 calls", progress.digest_line(line))


class WriteScopeValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        self.root = make_temp_dir(TEST_TMP, "sandbox-scope-")
        (self.root / "reality_engine" / "scripts").mkdir(parents=True)
        (self.root / "reality_engine" / "scripts" / "go_session.py").write_text(
            'def session_id(job, model, key="", lane_no=None):\n'
            '    return "provider-session-test"\n',
            encoding="utf-8",
        )
        self.env = os.environ.copy()
        for name in ("DSH_SESSION_LABEL", "REALITY_DATA_ROOT"):
            self.env.pop(name, None)
        self.env.update(
            {
                "DSH_WORKER_REPO_ROOT": str(self.root),
                "DSH_WORKER_RUNTIME_DIR": str(self.root / "runtime"),
                "DSH_WORKTREES_ROOT": str(self.root / "worktrees"),
                "DSH_WORKER_LAUNCHER": str(FAKE_LAUNCHER),
                "DSH_WORKER_TESTING": "1",
                "DSH_WORKER_FAKE_NOW": OFF_PEAK,
                "FAKE_LAUNCHER_MODE": "slow",
                "FAKE_LAUNCHER_SLEEP": "20",
                "FAKE_HEARTBEAT_FLAGS": "1",
            }
        )
        self.manager = core.Manager(core.load_config(self.env))
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        try:
            jobs = list((Path(self.env["DSH_WORKER_RUNTIME_DIR"]) / "jobs").iterdir())
        except OSError:
            jobs = []
        for job_dir in jobs:
            try:
                job_id = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))["job_id"]
                self.manager.cancel_worker(job_id, confirm=True, reason="test cleanup")
            except Exception:
                pass
        for _ in range(20):
            try:
                remove_tree(self.root)
                return
            except OSError:
                time.sleep(0.2)

    def test_data_scope_needs_confirmation(self) -> None:
        with self.assertRaises(core.PluginError) as raised:
            self.manager.start_worker(brief="probe", write_scope="data")
        self.assertEqual(raised.exception.code, "confirm_data_write_required")

    def test_full_scope_needs_confirmation(self) -> None:
        with self.assertRaises(core.PluginError) as raised:
            self.manager.start_worker(brief="probe", write_scope="full")
        self.assertEqual(raised.exception.code, "confirm_full_access_required")

    def test_unknown_scope_and_misplaced_writes_are_refused(self) -> None:
        with self.assertRaises(core.PluginError) as raised:
            self.manager.start_worker(brief="probe", write_scope="root")
        self.assertEqual(raised.exception.code, "write_scope_invalid")
        with self.assertRaises(core.PluginError) as raised:
            self.manager.start_worker(brief="probe", writes=["equity_intelligence.db"])
        self.assertEqual(raised.exception.code, "writes_requires_data_scope")

    def test_status_progress_and_list_show_the_first_edit_metric(self) -> None:
        # Rebuild the manager with an event stream and a job long enough for
        # the supervisor's orientation poll to see the first edit.
        self.env.update(
            {
                "FAKE_LAUNCHER_MODE": "slow",
                "FAKE_LAUNCHER_SLEEP": "6",
                "FAKE_LAUNCHER_EVENTS": "1",
            }
        )
        manager = core.Manager(core.load_config(self.env))
        started = manager.start_worker(
            brief="orientation probe",
            workspace=".",
            permission="workspace-write",
            progress_interval_seconds=1,
        )
        self.addCleanup(manager.cancel_worker, started["job_id"], True, "test cleanup")
        deadline = time.monotonic() + 40.0
        status = None
        while time.monotonic() < deadline:
            status = manager.get_status(started["job_id"])
            if status.get("final"):
                break
            time.sleep(0.1)
        self.assertIsNotNone(status)
        # read, pwsh, then write = two tool calls before the first edit.
        self.assertEqual(status["tool_calls_before_first_edit"], 2)
        self.assertIsNotNone(status["orientation_seconds"])
        self.assertEqual(status["write_scope"], "workspace")
        job_dir = Path(self.env["DSH_WORKER_RUNTIME_DIR"]) / "jobs" / started["job_id"]
        digests = progress.read_digests(job_dir)
        self.assertTrue(
            any(
                record.get("tool_calls_before_first_edit") == 2
                and record.get("write_scope") == "workspace"
                for record in digests
            ),
            digests,
        )
        rows = manager.list_workers(limit=5)["jobs"]
        row = next(item for item in rows if item["job_id"] == started["job_id"])
        self.assertEqual(row["tool_calls_before_first_edit"], 2)
        self.assertIsNotNone(row["orientation_seconds"])
        # Progress notes live in the workspace .tmp, not the runtime job dir.
        launcher = json.loads((job_dir / "launcher_argv.json").read_text(encoding="utf-8"))
        self.assertTrue(launcher["env_progress_notes"].startswith(str(self.root)))
        self.assertIn(".tmp", launcher["env_progress_notes"])
        self.assertTrue((self.root / ".tmp").is_dir())

    def test_data_job_records_scope_and_holds_db_lock(self) -> None:
        started = self.manager.start_worker(
            brief="data probe",
            write_scope="data",
            confirm_data_write=True,
            writes=["db:probe.db"],
        )
        self.addCleanup(
            self.manager.cancel_worker, started["job_id"], True, "test cleanup"
        )
        self.assertEqual(started["write_scope"], "data")
        self.assertEqual(started["writes"], ["probe.db"])
        self.assertEqual(started["permission"], "danger-full-access")
        record = json.loads(
            (Path(self.env["DSH_WORKER_RUNTIME_DIR"]) / "jobs" / started["job_id"] / "job.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(record["write_scope"], "data")
        self.assertEqual(record["resource_locks"], ["db:probe.db"])
        self.assertEqual(record["permission_requested"], "read-only")
        status = self.manager.get_status(started["job_id"])
        self.assertEqual(status["write_scope"], "data")
        self.assertEqual(status["writes"], ["probe.db"])
        self.assertIn("db:probe.db", status["resource_locks"])
        # The lock is taken before the worker is launched; wait for the launch
        # so the second start cannot race the supervisor's lock acquisition.
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if self.manager.get_status(started["job_id"]).get("phase") == "running":
                break
            time.sleep(0.1)
        else:
            self.fail("data job never reached running; cannot test the DB lock")
        # A second data job naming the same DB is refused.
        with self.assertRaises(core.PluginError) as raised:
            self.manager.start_worker(
                brief="second data probe",
                write_scope="data",
                confirm_data_write=True,
                writes=["probe.db"],
            )
        self.assertEqual(raised.exception.code, "resource_busy")


class CommitRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        self.root = make_temp_dir(TEST_TMP, "sandbox-commit-")
        self.addCleanup(self._cleanup)
        self.repo = self.root / "repo"
        self.repo.mkdir()

    def _cleanup(self) -> None:
        for _ in range(20):
            try:
                remove_tree(self.root)
                return
            except OSError:
                time.sleep(0.2)

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout

    def test_worker_commit_request_commits_a_worktree(self) -> None:
        self._git("init", "-q")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")
        (self.repo / "file.txt").write_text("one\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")
        base = self._git("rev-parse", "HEAD").strip()
        worktree = self.root / "wt"
        self._git("worktree", "add", "-q", "-b", "dsh/test", str(worktree))
        (worktree / "file.txt").write_text("one\ntwo\n", encoding="utf-8")
        tmp = worktree / ".tmp"
        tmp.mkdir()
        (tmp / "commit.request.json").write_text(
            json.dumps({"message": "worker commit"}), encoding="utf-8"
        )
        job = {
            "job_id": "20261025T000000Z-abcdef12",
            "brief_first_line": "worker commit",
            "worktree": {"enabled": True, "path": str(worktree), "base_commit": base},
        }
        status: dict = {"worker_commits": []}
        supervisor._handle_commit_request(job, self.root / "job", status, tmp)
        result = json.loads((tmp / "commit.result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["ok"], result)
        self.assertFalse((tmp / "commit.request.json").exists())
        subject = subprocess.run(
            ["git", "log", "-1", "--format=%s"], cwd=worktree, capture_output=True, text=True
        ).stdout.strip()
        self.assertIn("worker commit", subject)
        self.assertEqual(len(status["worker_commits"]), 1)

    def test_commit_request_works_for_an_existing_worktree_workspace(self) -> None:
        """A workspace pointed at an existing worktree (no job worktree record)."""
        self._git("init", "-q")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")
        (self.repo / "file.txt").write_text("one\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")
        worktree = self.root / "existing-wt"
        self._git("worktree", "add", "-q", "-b", "dsh/existing", str(worktree))
        (worktree / "file.txt").write_text("one\nexisting\n", encoding="utf-8")
        tmp = worktree / ".tmp"
        tmp.mkdir()
        (tmp / "commit.request.json").write_text(
            json.dumps({"message": "existing worktree commit"}), encoding="utf-8"
        )
        job = {
            "job_id": "20261025T000001Z-abcdef12",
            "workspace": str(worktree),
            "worktree": None,
            "brief_first_line": "existing worktree",
        }
        status: dict = {"worker_commits": []}
        supervisor._handle_commit_request(job, self.root / "job", status, tmp)
        result = json.loads((tmp / "commit.result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["ok"], result)
        subject = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=worktree,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertIn("existing worktree commit", subject)

    def test_commit_request_is_worktree_only(self) -> None:
        tmp = self.root / "scratch"
        tmp.mkdir()
        (tmp / "commit.request.json").write_text("{}", encoding="utf-8")
        status: dict = {"worker_commits": []}
        supervisor._handle_commit_request(
            {"job_id": "x", "worktree": None}, self.root, status, tmp
        )
        result = json.loads((tmp / "commit.result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["error"], "commit_request_requires_worktree")


class ProgressNotesTests(unittest.TestCase):
    def test_workspace_notes_preferred_with_legacy_fallback(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        root = make_temp_dir(TEST_TMP, "sandbox-notes-")
        self.addCleanup(lambda: remove_tree(root))
        job_dir = root / "job"
        job_dir.mkdir()
        workspace_tmp = root / "workspace" / ".tmp"
        workspace_tmp.mkdir(parents=True)
        (job_dir / progress.PROGRESS_NOTES_FILE).write_text("legacy line\n", encoding="utf-8")
        (workspace_tmp / progress.PROGRESS_NOTES_FILE).write_text(
            "old\nworkspace line\n", encoding="utf-8"
        )
        self.assertEqual(
            progress.latest_note(job_dir, workspace_tmp / progress.PROGRESS_NOTES_FILE),
            "workspace line",
        )
        # Compatibility: a job that only wrote the legacy job-dir path still
        # gets its note folded into the digest.
        (workspace_tmp / progress.PROGRESS_NOTES_FILE).unlink()
        self.assertEqual(
            progress.latest_note(job_dir, workspace_tmp / progress.PROGRESS_NOTES_FILE),
            "legacy line",
        )


class WorkerBootstrapTests(unittest.TestCase):
    def test_bootstrap_keeps_tempfile_mkdtemp_writable(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        root = make_temp_dir(TEST_TMP, "sandbox-bootstrap-")
        self.addCleanup(lambda: remove_tree(root))
        scratch = root / ".tmp"
        scratch.mkdir()
        bootstrap = REPO / "plugins" / "dsh-worker" / "worker_bootstrap"
        env = dict(os.environ)
        env.update(
            {
                "PYTHONPATH": str(bootstrap),
                "TMP": str(scratch),
                "TEMP": str(scratch),
                "TMPDIR": str(scratch),
            }
        )
        code = (
            "import os, tempfile\n"
            "d = tempfile.mkdtemp()\n"
            "open(os.path.join(d, 'x'), 'w').write('ok')\n"
            "print('ok')\n"
        )
        finished = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)


class DetachedRequestTests(unittest.TestCase):
    def test_detached_launch_is_data_scope_only(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        root = make_temp_dir(TEST_TMP, "sandbox-detach-")
        self.addCleanup(lambda: remove_tree(root))
        tmp = root / ".tmp"
        tmp.mkdir()
        (tmp / "launch.request.json").write_text(
            json.dumps({"cmd": "cmd /c echo hi"}), encoding="utf-8"
        )
        status: dict = {"detached": []}
        supervisor._handle_launch_request(
            {"job_id": "x", "workspace": str(root), "write_scope": "workspace"},
            root,
            status,
            tmp,
        )
        result = json.loads((tmp / "launch.result.json").read_text(encoding="utf-8"))
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"], "launch_detached_requires_write_scope_data_or_full"
        )

    def test_detached_rejects_a_log_outside_allowed_roots(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        root = make_temp_dir(TEST_TMP, "sandbox-detach-log-")
        self.addCleanup(lambda: remove_tree(root))
        tmp = root / ".tmp"
        tmp.mkdir()
        (tmp / "launch.request.json").write_text(
            json.dumps({"cmd": "cmd /c echo hi", "log": str(Path.home() / "escape.log")}),
            encoding="utf-8",
        )
        status: dict = {"detached": []}
        supervisor._handle_launch_request(
            {"job_id": "x", "workspace": str(root), "write_scope": "data"},
            root,
            status,
            tmp,
        )
        result = json.loads((tmp / "launch.result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["error"], "log_outside_allowed_roots")


if __name__ == "__main__":
    unittest.main()
