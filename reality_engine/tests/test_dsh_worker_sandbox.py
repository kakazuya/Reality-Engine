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
import gitutil  # noqa: E402
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

    def test_data_scope_requires_named_writes(self) -> None:
        # A data job with writes=[] holds no db: lock, so it could write any DB:
        # refuse it instead of silently granting un-locked full access.
        with self.assertRaises(core.PluginError) as raised:
            self.manager.start_worker(
                brief="probe", write_scope="data", confirm_data_write=True
            )
        self.assertEqual(raised.exception.code, "writes_required")

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
            confirm_repo_root_write=True,
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
        # A workspace-write job is sandboxed: the bootstrap marker must be set.
        self.assertEqual(launcher["env_sandboxed"], "1")

    def test_status_scope_wins_over_a_rewritten_job_record(self) -> None:
        # A worker whose workspace is the main checkout can edit job.json; the
        # supervisor's status.json is the launch-time record and must win.
        started = self.manager.start_worker(
            brief="scope spoof probe",
            permission="workspace-write",
            confirm_repo_root_write=True,
        )
        self.addCleanup(
            self.manager.cancel_worker, started["job_id"], True, "test cleanup"
        )
        job_dir = Path(self.env["DSH_WORKER_RUNTIME_DIR"]) / "jobs" / started["job_id"]
        record = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        record["write_scope"] = "data"
        (job_dir / "job.json").write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self.manager.get_status(started["job_id"])["write_scope"], "workspace")
        rows = self.manager.list_workers(limit=5)["jobs"]
        row = next(item for item in rows if item["job_id"] == started["job_id"])
        self.assertEqual(row["write_scope"], "workspace")

    def test_repo_root_mutating_start_requires_confirmation(self) -> None:
        # A mutating repo-root worker can rewrite the context-pack builder,
        # supervisor.py, .git/config and other jobs' records, so it needs an
        # explicit confirmation flag.  Read-only workers are unaffected.
        with self.assertRaises(core.PluginError) as raised:
            self.manager.start_worker(brief="root writer", permission="workspace-write")
        self.assertEqual(
            raised.exception.code, "repo_root_write_requires_confirmation"
        )
        started = self.manager.start_worker(
            brief="root writer",
            permission="workspace-write",
            confirm_repo_root_write=True,
        )
        self.addCleanup(
            self.manager.cancel_worker, started["job_id"], True, "test cleanup"
        )
        self.assertTrue(started["confirm_repo_root_write"])
        job_dir = Path(self.env["DSH_WORKER_RUNTIME_DIR"]) / "jobs" / started["job_id"]
        record = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertTrue(record["confirm_repo_root_write"])
        status = self.manager.get_status(started["job_id"])
        self.assertTrue(status["confirm_repo_root_write"])
        rows = self.manager.list_workers(limit=5)["jobs"]
        row = next(item for item in rows if item["job_id"] == started["job_id"])
        self.assertTrue(row["confirm_repo_root_write"])
        # A read-only repo-root worker writes nothing and needs no flag.
        reader = self.manager.start_worker(brief="reader", permission="read-only")
        self.addCleanup(
            self.manager.cancel_worker, reader["job_id"], True, "test cleanup"
        )
        self.assertFalse(reader["confirm_repo_root_write"])

    def test_context_pack_is_not_regenerated_while_a_repo_root_writer_runs(self) -> None:
        # NEW-2/4: attach_context_pack executes a builder in the repo root.  While
        # a mutating repo-root worker can rewrite that file, regeneration must be
        # skipped (stale pack + warning), never executed by this manager.
        pack = self.root / "tasks" / "worker_context" / "CONTEXT.md"
        pack.parent.mkdir(parents=True, exist_ok=True)
        pack.write_text("# old pack\n", encoding="utf-8")
        stamp = time.time() - 30 * 3600
        os.utime(pack, (stamp, stamp))
        builder = self.root / "reality_engine" / "scripts" / "build_worker_context.py"
        builder.parent.mkdir(parents=True, exist_ok=True)
        marker = self.root / "BUILDER-RAN.txt"
        builder.write_text(
            f"open({str(marker)!r}, 'w').write('ran')\n", encoding="utf-8"
        )
        writer = self.manager.start_worker(
            brief="root writer",
            permission="workspace-write",
            confirm_repo_root_write=True,
            context_pack=True,
        )
        self.addCleanup(
            self.manager.cancel_worker, writer["job_id"], True, "test cleanup"
        )
        # The writer's OWN start takes the lock before attaching the pack, so
        # its own unverifiable lock already suppresses builder execution.  This
        # assertion holds in every environment, not only where the fake builder
        # happens to fail to import.
        self.assertFalse(writer["context_pack"]["regenerated"], writer["context_pack"])
        self.assertEqual(
            writer["context_pack"].get("regeneration_skipped"),
            "repo_root_writer_active",
        )
        self.assertFalse(marker.exists(), "the writer's own start executed the builder")
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not self.manager._repo_root_writer_active():
            time.sleep(0.1)
        self.assertTrue(self.manager._repo_root_writer_active())
        reader = self.manager.start_worker(
            brief="Goal: read only", permission="read-only", context_pack=True
        )
        self.addCleanup(
            self.manager.cancel_worker, reader["job_id"], True, "test cleanup"
        )
        self.assertFalse(reader["context_pack"]["regenerated"], reader["context_pack"])
        self.assertEqual(
            reader["context_pack"].get("regeneration_skipped"),
            "repo_root_writer_active",
        )
        self.assertFalse(marker.exists(), "the manager executed the builder")
        self.assertTrue(
            any("skipped regeneration" in warning for warning in reader["warnings"]),
            reader["warnings"],
        )
        self.assertEqual(pack.read_text(encoding="utf-8"), "# old pack\n")

    def test_context_pack_guard_fails_closed_on_an_unreadable_lock(self) -> None:
        # Outside the sandbox the lock record can be a partial write, bad JSON
        # or unreadable.  Only a MISSING lock proves no repo-root writer exists;
        # an existing but unverifiable record must skip regeneration too.
        lock = self.manager._lock_path(self.manager.config.repo_root)
        self.assertFalse(self.manager._repo_root_writer_active())
        lock.parent.mkdir(parents=True, exist_ok=True)
        for corrupt in ("{not json", "", "[]"):
            lock.write_text(corrupt, encoding="utf-8")
            self.assertTrue(self.manager._repo_root_writer_active(), corrupt)
        lock.unlink()
        self.assertFalse(self.manager._repo_root_writer_active())

    def test_data_job_records_scope_and_holds_db_lock(self) -> None:
        started = self.manager.start_worker(
            brief="data probe",
            write_scope="data",
            confirm_data_write=True,
            confirm_repo_root_write=True,
            writes=["db:probe.db"],
            approved_by="Shivam (test approval)",
        )
        self.addCleanup(
            self.manager.cancel_worker, started["job_id"], True, "test cleanup"
        )
        self.assertEqual(started["write_scope"], "data")
        self.assertEqual(started["writes"], ["probe.db"])
        self.assertEqual(started["approved_by"], "Shivam (test approval)")
        self.assertEqual(started["permission"], "danger-full-access")
        job_dir = Path(self.env["DSH_WORKER_RUNTIME_DIR"]) / "jobs" / started["job_id"]
        record = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(record["write_scope"], "data")
        self.assertEqual(record["resource_locks"], ["db:probe.db"])
        self.assertEqual(record["permission_requested"], "read-only")
        self.assertEqual(record["approved_by"], "Shivam (test approval)")
        status = self.manager.get_status(started["job_id"])
        self.assertEqual(status["write_scope"], "data")
        self.assertEqual(status["writes"], ["probe.db"])
        self.assertEqual(status["approved_by"], "Shivam (test approval)")
        self.assertIn("db:probe.db", status["resource_locks"])
        # The supervisor spawns the launcher asynchronously; wait only for its
        # env dump (the lock check below must not depend on the worker running).
        launcher_path = job_dir / "launcher_argv.json"
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not launcher_path.is_file():
            time.sleep(0.1)
        launcher = json.loads(launcher_path.read_text(encoding="utf-8"))
        # A danger-full-access job is not file-sandboxed: no mkdir patch marker.
        self.assertIsNone(launcher["env_sandboxed"])
        # The reservation is taken before the supervisor is spawned, so the
        # second start is refused immediately -- no need to wait for running.
        with self.assertRaises(core.PluginError) as raised:
            self.manager.start_worker(
                brief="second data probe",
                write_scope="data",
                confirm_data_write=True,
                confirm_repo_root_write=True,
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

    def _init_repo(self) -> str:
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")
        (self.repo / "file.txt").write_text("one\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")
        return self._git("rev-parse", "HEAD").strip()

    def _rewrite_git_pointer(self, worktree: Path, gitdir: str) -> None:
        """What a worker does with ``.git`` (hidden file: unlink then write)."""
        pointer = worktree / ".git"
        pointer.unlink()
        pointer.write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

    def _commit_request(self, worktree: Path, job: dict) -> dict:
        tmp = worktree / ".tmp"
        tmp.mkdir(exist_ok=True)
        (tmp / "commit.request.json").write_text(
            json.dumps({"message": "worker commit"}), encoding="utf-8"
        )
        supervisor._handle_commit_request(job, self.root / "job", job["_status"], tmp)
        return json.loads((tmp / "commit.result.json").read_text(encoding="utf-8"))

    def test_worker_commit_request_commits_a_worktree(self) -> None:
        base = self._init_repo()
        worktree = self.root / "wt"
        self._git("worktree", "add", "-q", "-b", "dsh/test", str(worktree))
        identity = gitutil.checkout_identity(worktree)
        self.assertIsNotNone(identity)
        # A pre-commit hook in the repository must not run for a worker commit.
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        escaped = self.root / "hook-escaped.txt"
        hook.write_text(
            f"#!/bin/sh\necho hooked > '{escaped.as_posix()}'\n", encoding="utf-8"
        )
        (worktree / "file.txt").write_text("one\ntwo\n", encoding="utf-8")
        status: dict = {"worker_commits": []}
        job = {
            "job_id": "20261025T000000Z-abcdef12",
            "repo_root": str(self.repo),
            "workspace": str(worktree),
            "brief_first_line": "worker commit",
            "git": identity,
            "worktree": {"enabled": True, "path": str(worktree), "base_commit": base},
            "_status": status,
        }
        result = self._commit_request(worktree, job)
        self.assertTrue(result["ok"], result)
        self.assertFalse((worktree / ".tmp" / "commit.request.json").exists())
        self.assertFalse(escaped.exists(), "pre-commit hook ran")
        subject = subprocess.run(
            ["git", "log", "-1", "--format=%s"], cwd=worktree, capture_output=True, text=True
        ).stdout.strip()
        self.assertIn("worker commit", subject)
        self.assertEqual(len(status["worker_commits"]), 1)

    def test_commit_request_works_for_an_existing_worktree_workspace(self) -> None:
        """A workspace pointed at an existing worktree (no job worktree record)."""
        base = self._init_repo()
        worktree = self.root / "existing-wt"
        self._git("worktree", "add", "-q", "-b", "dsh/existing", str(worktree))
        identity = gitutil.checkout_identity(worktree)
        self.assertIsNotNone(identity)
        (worktree / "file.txt").write_text("one\nexisting\n", encoding="utf-8")
        status: dict = {"worker_commits": []}
        job = {
            "job_id": "20261025T000001Z-abcdef12",
            "repo_root": str(self.repo),
            "workspace": str(worktree),
            "worktree": None,
            "brief_first_line": "existing worktree",
            "git": identity,
            "_status": status,
        }
        result = self._commit_request(worktree, job)
        self.assertTrue(result["ok"], result)
        subject = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=worktree,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertIn("worker commit", subject)
        self.assertEqual(base, self._git("rev-parse", "main").strip())

    def test_identity_round_trips_a_non_ascii_worktree_path(self) -> None:
        # Regression: git paths were decoded with the process locale (cp1252 on
        # a non-UTF-8 host), so a workspace containing non-ASCII characters no
        # longer matched its captured toplevel and the commit was refused as
        # git_workspace_moved.  PYTHONUTF8=0 pins the failing mode independently
        # of the shell this suite runs in.
        unicode_root = self.root / "dsh stress ू dir"
        repo = unicode_root / "repo"
        repo.mkdir(parents=True)

        def git(*args: str) -> None:
            subprocess.run(
                ["git", *args], cwd=repo, check=True, capture_output=True
            )

        git("init", "-q", "-b", "main")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        (repo / "file.txt").write_text("one\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        worktree = unicode_root / "worktrees" / "wt"
        git("worktree", "add", "-q", "-b", "dsh/test", str(worktree))

        code = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import gitutil\n"
            "identity = gitutil.checkout_identity(sys.argv[2])\n"
            "print(gitutil.identity_error(sys.argv[2], identity, sys.argv[3]))\n"
        )
        env = dict(os.environ)
        env["PYTHONUTF8"] = "0"
        env.pop("PYTHONIOENCODING", None)
        finished = subprocess.run(
            [sys.executable, "-c", code, str(SERVER_DIR), str(worktree), str(repo)],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(finished.stdout.strip(), "None", finished.stderr)

    def test_commit_refuses_a_worker_owned_gitdir_and_never_runs_its_hook(self) -> None:
        # D1(a): the worker rewrites .git to a gitdir it owns, whose pre-commit
        # hook would escape.  The commit must be refused and the hook must not run.
        base = self._init_repo()
        worktree = self.root / "wt"
        self._git("worktree", "add", "-q", "-b", "dsh/test", str(worktree))
        identity = gitutil.checkout_identity(worktree)
        fake = self.root / "fake-git"
        fake.mkdir()
        subprocess.run(["git", "init", "-q", str(fake)], check=True, cwd=self.root)
        hook = fake / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        escaped = self.root / "handler-hook-escaped.txt"
        hook.write_text(
            f"#!/bin/sh\necho escaped > '{escaped.as_posix()}'\n", encoding="utf-8"
        )
        self._rewrite_git_pointer(worktree, str(fake))
        (worktree / "file.txt").write_text("one\ntwo\n", encoding="utf-8")
        status: dict = {"worker_commits": []}
        job = {
            "job_id": "20261025T000002Z-abcdef12",
            "repo_root": str(self.repo),
            "workspace": str(worktree),
            "brief_first_line": "fake gitdir",
            "git": identity,
            "worktree": {"enabled": True, "path": str(worktree), "base_commit": base},
            "_status": status,
        }
        result = self._commit_request(worktree, job)
        self.assertFalse(result["ok"], result)
        self.assertEqual((result.get("commit") or {}).get("reason"), "git_dir_tampered")
        self.assertFalse(escaped.exists(), "fake pre-commit hook ran")
        self.assertEqual(self._git("rev-parse", "main").strip(), base)
        # Nothing was committed to the worker-owned fake repository either.
        fake_head = subprocess.run(
            ["git", "-C", str(fake), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(fake_head.returncode, 0)

    def test_commit_refuses_a_git_pointer_redirected_at_another_repo(self) -> None:
        # D1(b): .git redirected at a scratch repository must not commit there.
        base = self._init_repo()
        worktree = self.root / "wt"
        self._git("worktree", "add", "-q", "-b", "dsh/test", str(worktree))
        identity = gitutil.checkout_identity(worktree)
        other = self.root / "other"
        other.mkdir()
        subprocess.run(["git", "init", "-q"], check=True, cwd=other)
        subprocess.run(
            ["git", "config", "user.email", "other@example.com"], check=True, cwd=other
        )
        subprocess.run(["git", "config", "user.name", "Other"], check=True, cwd=other)
        (other / "other.txt").write_text("other\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], check=True, cwd=other)
        subprocess.run(["git", "commit", "-q", "-m", "other base"], check=True, cwd=other)
        other_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=other, capture_output=True, text=True
        ).stdout.strip()
        self._rewrite_git_pointer(worktree, str(other / ".git"))
        (worktree / "file.txt").write_text("one\ntwo\n", encoding="utf-8")
        status: dict = {"worker_commits": []}
        job = {
            "job_id": "20261025T000003Z-abcdef12",
            "repo_root": str(self.repo),
            "workspace": str(worktree),
            "brief_first_line": "redirected",
            "git": identity,
            # No worktree record: the stored identity is what allows the commit
            # path at all, and it is derived from the pre-launch checkout.
            "worktree": None,
            "_status": status,
        }
        result = self._commit_request(worktree, job)
        self.assertFalse(result["ok"], result)
        self.assertEqual((result.get("commit") or {}).get("reason"), "git_dir_tampered")
        other_after = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=other, capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(other_after, other_head)
        self.assertEqual(
            subprocess.run(
                ["git", "log", "-1", "--format=%s"], cwd=other, capture_output=True, text=True
            ).stdout.strip(),
            "other base",
        )
        self.assertEqual(self._git("rev-parse", "main").strip(), base)

    def test_commit_refuses_the_main_checkout_identity(self) -> None:
        base = self._init_repo()
        identity = gitutil.checkout_identity(self.repo)
        self.assertIsNotNone(identity)
        (self.repo / "file.txt").write_text("one\ntwo\n", encoding="utf-8")
        tmp = self.root / "scratch"
        tmp.mkdir()
        status: dict = {"worker_commits": []}
        job = {
            "job_id": "20261025T000004Z-abcdef12",
            "repo_root": str(self.repo),
            "workspace": str(self.repo),
            "worktree": None,
            "brief_first_line": "main checkout",
            "git": identity,
            "_status": status,
        }
        result = self._commit_request(self.repo, job)
        self.assertFalse(result["ok"], result)
        self.assertEqual(
            (result.get("commit") or {}).get("reason"), "git_main_checkout_refused"
        )
        self.assertEqual(self._git("rev-parse", "main").strip(), base)

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

    def test_snapshot_uses_the_stored_identity_and_refuses_a_tampered_pointer(self) -> None:
        # NEW-1: the post-run snapshot must never derive a git dir from the
        # worker-writable <workspace>/.git.  A fake gitdir with a native
        # fsmonitor program is exactly what the review executed through it.
        base = self._init_repo()
        worktree = self.root / "wt"
        self._git("worktree", "add", "-q", "-b", "dsh/test", str(worktree))
        identity = gitutil.checkout_identity(worktree)
        self.assertIsNotNone(identity)
        (worktree / "file.txt").write_text("one\ntwo\n", encoding="utf-8")
        # The normal path still works through the stored identity.
        before = gitutil.snapshot(worktree, identity=identity, repo_root=self.repo)
        self.assertTrue(before["available"], before)
        self.assertIn("file.txt", before["paths"])
        self.assertEqual(os.path.normcase(before["root"]), os.path.normcase(str(worktree)))

        outside = self.root / "outside"
        outside.mkdir()
        fake = self.root / "fake-git"
        subprocess.run(
            ["git", "init", "-q", "--separate-git-dir", str(fake), str(self.root / "fake-wt")],
            check=True,
            cwd=self.root,
        )
        config = fake / "config"
        config.write_text(
            config.read_text(encoding="utf-8")
            + f"\n[core]\n\tworktree = {outside.as_posix()}\n"
            + f"\tfsmonitor = {Path(sys.executable).as_posix()}\n",
            encoding="utf-8",
        )
        marker = self.root / "FSMONITOR-EXECUTED.txt"
        # Git execs the fsmonitor program in core.worktree; python.exe runs the
        # file named "2" that git passes as its first argument.
        (outside / "2").write_text(
            f"open({str(marker)!r}, 'w').write('ran\\n')\n", encoding="utf-8"
        )
        self._rewrite_git_pointer(worktree, str(fake))

        after = gitutil.snapshot(worktree, identity=identity, repo_root=self.repo)
        self.assertFalse(after["available"], after)
        self.assertEqual(after["reason"], "git_dir_tampered")
        self.assertFalse(marker.exists(), "a git command ran against the worker gitdir")

        # Legacy job records have no stored identity: no snapshot, no git run.
        legacy = gitutil.snapshot(worktree)
        self.assertFalse(legacy["available"], legacy)
        self.assertEqual(legacy["reason"], "git_identity_missing")
        self.assertFalse(marker.exists(), "a git command ran without a stored identity")

    def test_snapshot_allows_the_main_checkout_identity(self) -> None:
        # The main checkout is never a commit target, but its own snapshot must
        # still work when the manager captured its identity at start.
        base = self._init_repo()
        (self.repo / "file.txt").write_text("one\ntwo\n", encoding="utf-8")
        identity = gitutil.checkout_identity(self.repo)
        snap = gitutil.snapshot(self.repo, identity=identity, repo_root=self.repo)
        self.assertTrue(snap["available"], snap)
        self.assertIn("file.txt", snap["paths"])
        self.assertEqual(self._git("rev-parse", "main").strip(), base)

    def test_commit_ignores_filter_and_gpg_config(self) -> None:
        # NEW-3: a committed .gitattributes + repo config must not run a clean
        # filter, and commit.gpgSign/gpg.program must not run a program.
        base = self._init_repo()
        worktree = self.root / "wt"
        self._git("worktree", "add", "-q", "-b", "dsh/test", str(worktree))
        identity = gitutil.checkout_identity(worktree)
        filter_marker = self.root / "FILTER-RAN.txt"
        gpg_marker = self.root / "GPG-RAN.txt"
        gpg = self.root / "gpg.cmd"
        gpg.write_text(
            "@echo off\r\n"
            f'echo ran > "{gpg_marker}"\r\n'
            "exit /b 1\r\n",
            encoding="utf-8",
        )
        config = self.repo / ".git" / "config"
        config.write_text(
            config.read_text(encoding="utf-8")
            + "\n[filter \"evil\"]\n"
            + f"\tclean = {Path(sys.executable).as_posix()}\n"
            + "[gpg]\n"
            + f"\tprogram = {gpg.as_posix()}\n"
            + "[commit]\n"
            + "\tgpgsign = true\n",
            encoding="utf-8",
        )
        (worktree / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
        # If the filter ran, python.exe would execute this file content.
        (worktree / "file.txt").write_text(
            f"open({str(filter_marker)!r}, 'w').write('ran')\n", encoding="utf-8"
        )
        result = gitutil.commit_worktree(
            worktree,
            job_id="20261025T000005Z-abcdef12",
            subject="filter probe",
            base_commit=base,
            git=identity,
            repo_root=self.repo,
        )
        self.assertTrue(result["committed"], result)
        self.assertFalse(filter_marker.exists(), "clean filter ran")
        self.assertFalse(gpg_marker.exists(), "gpg.program ran")
        # The file is stored raw: no filter output replaced its content.
        stored = subprocess.run(
            ["git", "show", "HEAD:file.txt"],
            cwd=worktree,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("FILTER-RAN", stored)

        # <git_dir>/info/attributes cannot be replaced by --attr-source, so a
        # driver selected there is refused instead of executed.
        info = self.repo / ".git" / "worktrees" / "wt" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "attributes").write_text("* filter=evil\n", encoding="utf-8")
        (worktree / "file.txt").write_text(
            f"open({str(filter_marker)!r}, 'w').write('ran')\nsecond\n",
            encoding="utf-8",
        )
        refused = gitutil.commit_worktree(
            worktree,
            job_id="20261025T000006Z-abcdef12",
            subject="info attributes probe",
            base_commit=base,
            git=identity,
            repo_root=self.repo,
        )
        self.assertFalse(refused["committed"], refused)
        self.assertEqual(refused["reason"], "git_attributes_driver_refused")
        self.assertFalse(filter_marker.exists(), "clean filter ran from info/attributes")

    def test_commit_refuses_a_junction_in_the_workspace(self) -> None:
        # NEW-5: git add -A followed a worker-created junction and committed data
        # from outside the workspace.
        if sys.platform != "win32":
            self.skipTest("junctions are a Windows reparse-point feature")
        base = self._init_repo()
        worktree = self.root / "wt"
        self._git("worktree", "add", "-q", "-b", "dsh/test", str(worktree))
        identity = gitutil.checkout_identity(worktree)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("outside-secret\n", encoding="utf-8")
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(worktree / "link"), str(outside)],
            capture_output=True,
            text=True,
        )
        if made.returncode != 0:
            self.skipTest(f"cannot create a junction here: {made.stderr.strip()[:200]}")
        self.addCleanup(
            lambda: subprocess.run(
                ["cmd", "/c", "rmdir", str(worktree / "link")],
                capture_output=True,
                text=True,
            )
        )
        (worktree / "file.txt").write_text("one\nworker edit\n", encoding="utf-8")
        result = gitutil.commit_worktree(
            worktree,
            job_id="20261025T000007Z-abcdef12",
            subject="junction probe",
            base_commit=base,
            git=identity,
            repo_root=self.repo,
        )
        self.assertFalse(result["committed"], result)
        self.assertEqual(result["reason"], "reparse_point_in_workspace")
        tree = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=worktree,
            capture_output=True,
            text=True,
        ).stdout
        self.assertNotIn("secret.txt", tree)
        self.assertEqual(self._git("rev-parse", "main").strip(), base)

    def test_commit_replays_the_identity_captured_from_global_config(self) -> None:
        # This repository keeps user.name/user.email in the GLOBAL config, which
        # the hardened runner deliberately does not read.  The manager captures
        # them at start and the commit replays them, or every real worktree
        # commit would fail with "Author identity unknown".
        base = self._init_repo()
        subprocess.run(
            ["git", "config", "--unset", "user.name"], cwd=self.repo, check=False
        )
        subprocess.run(
            ["git", "config", "--unset", "user.email"], cwd=self.repo, check=False
        )
        global_config = self.root / "global.gitconfig"
        global_config.write_text(
            "[user]\n\tname = Captured Author\n\temail = captured@example.invalid\n",
            encoding="utf-8",
        )
        previous = os.environ.get("GIT_CONFIG_GLOBAL")
        os.environ["GIT_CONFIG_GLOBAL"] = str(global_config)
        try:
            worktree = self.root / "wt"
            self._git("worktree", "add", "-q", "-b", "dsh/test", str(worktree))
            identity = gitutil.checkout_identity(worktree)
        finally:
            if previous is None:
                os.environ.pop("GIT_CONFIG_GLOBAL", None)
            else:
                os.environ["GIT_CONFIG_GLOBAL"] = previous
        self.assertIsNotNone(identity)
        self.assertEqual(identity.get("user.name"), "Captured Author")
        self.assertEqual(identity.get("user.email"), "captured@example.invalid")
        (worktree / "file.txt").write_text("one\ntwo\n", encoding="utf-8")
        result = gitutil.commit_worktree(
            worktree,
            job_id="20261025T000008Z-abcdef12",
            subject="identity replay",
            base_commit=base,
            git=identity,
            repo_root=self.repo,
        )
        self.assertTrue(result["committed"], result)
        author = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>"],
            cwd=worktree,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(author, "Captured Author <captured@example.invalid>")

    def test_request_history_is_capped(self) -> None:
        status: dict = {"worker_commits": []}
        for index in range(supervisor.MAX_REQUEST_HISTORY + 10):
            supervisor._append_history(status, "worker_commits", {"at": str(index)})
        self.assertEqual(len(status["worker_commits"]), supervisor.MAX_REQUEST_HISTORY)
        self.assertEqual(status["worker_commits"][-1]["at"], str(supervisor.MAX_REQUEST_HISTORY + 9))


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
    def _run_with_bootstrap(self, work: Path, sandboxed: bool, code: str):
        env = dict(os.environ)
        env.update(
            {
                "PYTHONPATH": str(REPO / "plugins" / "dsh-worker" / "worker_bootstrap"),
                "TMP": str(work),
                "TEMP": str(work),
                "TMPDIR": str(work),
            }
        )
        if sandboxed:
            env["DSH_WORKER_SANDBOXED"] = "1"
        else:
            env.pop("DSH_WORKER_SANDBOXED", None)
        return subprocess.run(
            [sys.executable, "-c", code, str(work)], env=env, capture_output=True, text=True
        )

    def test_bootstrap_keeps_tempfile_mkdtemp_writable(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        root = make_temp_dir(TEST_TMP, "sandbox-bootstrap-")
        self.addCleanup(lambda: remove_tree(root))
        scratch = root / ".tmp"
        scratch.mkdir()
        code = (
            "import os, tempfile\n"
            "d = tempfile.mkdtemp()\n"
            "open(os.path.join(d, 'x'), 'w').write('ok')\n"
            "print('ok')\n"
        )
        finished = self._run_with_bootstrap(scratch, True, code)
        self.assertEqual(finished.returncode, 0, finished.stderr)

    def test_bootstrap_only_patches_a_sandboxed_windows_worker(self) -> None:
        # D3: the patch must not widen 0o700 for every Python process.  With the
        # supervisor's marker the directory inherits the sandbox DACL; without
        # it (or off win32) os.mkdir stays untouched and keeps the explicit DACL.
        if sys.platform != "win32":
            self.skipTest("the 0o700 DACL problem only exists on Windows")
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        root = make_temp_dir(TEST_TMP, "sandbox-marker-")
        self.addCleanup(lambda: remove_tree(root, attempts=5))
        scratch = root / ".tmp"
        scratch.mkdir()
        code = (
            "import os, sys\n"
            "d = os.path.join(sys.argv[1], 'mine')\n"
            "os.mkdir(d, 0o700)\n"
            "print(d)\n"
        )

        def run(name: str, sandboxed: bool) -> Path:
            work = scratch / name
            work.mkdir()
            finished = self._run_with_bootstrap(work, sandboxed, code)
            self.assertEqual(finished.returncode, 0, finished.stderr)
            return Path(finished.stdout.strip())

        acl = lambda path: subprocess.run(
            ["icacls", str(path)], capture_output=True, text=True
        )

        def access_aces(output: str) -> str:
            # icacls always appends the SACL integrity label ("Mandatory Label\
            # Low Mandatory Level:(I)(OI)(CI)(NW)"), whose (I) is inherited from
            # the parent directory even when the DACL has no inherited ACE.
            return "\n".join(
                line
                for line in output.splitlines()
                if not line.lstrip().startswith("Mandatory Label")
            )

        patched = run("patched", True)
        patched_acl = acl(patched)
        self.assertIn(
            "(I)",
            access_aces(patched_acl.stdout),
            patched_acl.stdout + patched_acl.stderr,
        )

        plain = run("plain", False)
        plain_acl = acl(plain)
        self.assertNotIn(
            "(I)",
            access_aces(plain_acl.stdout),
            plain_acl.stdout + plain_acl.stderr,
        )


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


class TmpReparsePointTests(unittest.TestCase):
    def test_tmp_junction_is_refused_not_followed(self) -> None:
        # LOW from the final review: a worker can replace <workspace>/.tmp with a
        # junction; the unsandboxed supervisor must not read requests from it or
        # write answers through it.
        if sys.platform != "win32":
            self.skipTest("junctions are a Windows reparse-point feature")
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        root = make_temp_dir(TEST_TMP, "sandbox-tmp-junction-")
        self.addCleanup(lambda: remove_tree(root))
        outside = root / "outside"
        outside.mkdir()
        request = outside / "commit.request.json"
        request.write_text(json.dumps({"message": "worker commit"}), encoding="utf-8")
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(root / ".tmp"), str(outside)],
            capture_output=True,
            text=True,
        )
        if made.returncode != 0:
            self.skipTest(f"cannot create a junction here: {made.stderr.strip()[:200]}")
        self.addCleanup(
            lambda: subprocess.run(
                ["cmd", "/c", "rmdir", str(root / ".tmp")],
                capture_output=True,
                text=True,
            )
        )
        job = {"job_id": "x", "workspace": str(root), "repo_root": str(root)}
        self.assertIsNone(supervisor._tmp_dir(job, root))
        status: dict = {"worker_commits": [], "detached": []}
        supervisor._poll_aux(job, root, status)
        self.assertTrue(status["tmp_reparse_point"])
        self.assertTrue(
            any("tmp_reparse_point" in warning for warning in status["warnings"]),
            status["warnings"],
        )
        self.assertFalse((outside / "commit.result.json").exists())
        self.assertTrue(request.is_file(), "the request must not be consumed")
        # The answer path re-checks too (a swap between read and write).
        supervisor._finish_request(
            root / ".tmp" / "commit.request.json",
            root / ".tmp" / "commit.result.json",
            {"ok": True},
        )
        self.assertFalse((outside / "commit.result.json").exists())
        self.assertTrue(request.is_file(), "the request must not be answered")


if __name__ == "__main__":
    unittest.main()
