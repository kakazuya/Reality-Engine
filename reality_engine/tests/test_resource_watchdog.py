"""Resource watchdog safety tests (2026-10-24): opt-in restarts, laptop profile, orphan scope, incidents, report.

Everything here is offline and side-effect free: psutil, the start/kill helpers and every output path the
watchdog writes are patched or redirected into a temporary folder, so no process is started or killed.
Run: python -m unittest reality_engine.tests.test_resource_watchdog -v
"""

import contextlib
import io
import itertools
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from reality_engine.scripts import resource_watchdog as wd

_SEQ = itertools.count()


@contextlib.contextmanager
def scratch():
    """A writable scratch dir for one test. Not tempfile.mkdtemp: on Windows its 0o700 DACL can block a sandboxed
    test token from writing inside it, so the dir is created plainly and inherits its parent's permissions."""
    d = Path(tempfile.gettempdir()) / f"resource_watchdog_test_{os.getpid()}_{next(_SEQ)}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


class Recorder:
    """Stands in for Incidents: remembers what would have been recorded, writes nothing."""

    def __init__(self):
        self.records = []

    def add(self, kind, key, detail):
        self.records.append((kind, key, detail))


FLAGGED_FREE_JOB = {"name": "free-job", "auto_restart": True, "tags": ("network",)}


def run_restart(job, procs=None, target="run_x.cmd"):
    """restart_or_report with every side effect patched; returns (recorder, started, killed)."""
    inc, started, killed = Recorder(), [], []
    with mock.patch.object(wd, "start_cmd", lambda t: started.append(t)), \
         mock.patch.object(wd, "kill_tree", lambda p: killed.append(p)), \
         mock.patch.object(wd, "orphan_workers", return_value=[]), \
         mock.patch.object(wd.time, "sleep"):
        js = {"restarts": [], "target": target}
        wd.restart_or_report(job, js, procs if procs is not None else [object()],
                             ("job_stopped", "not running"), time.time(), inc)
    return inc, started, killed


class TestRestartGate(unittest.TestCase):
    def test_laptop_profile_skips_restart_even_for_a_flagged_free_job(self):
        with mock.patch.object(wd, "PROFILE", "laptop"):
            inc, started, killed = run_restart(FLAGGED_FREE_JOB)
        self.assertEqual(started, [], "the laptop profile must never start a job")
        self.assertEqual(killed, [], "the laptop profile must never kill a managed job")
        self.assertEqual(inc.records[0][0], "job_stopped")
        self.assertIn("NOT restarting", inc.records[0][2])
        self.assertIn("monitor-only", inc.records[0][2])

    def test_pc_profile_still_restarts_a_job_that_opted_in(self):
        # locks in that the gate is a profile/flag decision, not "restarts are simply dead"
        procs = [object(), object()]
        with mock.patch.object(wd, "PROFILE", "pc"):
            inc, started, killed = run_restart(FLAGGED_FREE_JOB, procs=procs)
        self.assertEqual(started, ["run_x.cmd"])
        self.assertEqual(len(killed), len(procs))
        self.assertIn("restarting: run_x.cmd", inc.records[0][2])

    def test_paid_gpu_and_pc_only_refuse_even_when_flagged(self):
        for tag in ("paid", "gpu", "pc_only"):
            job = {"name": tag, "auto_restart": True, "tags": (tag,)}
            with mock.patch.object(wd, "PROFILE", "pc"):
                why = wd.blocked_reason(job)
                inc, started, killed = run_restart(job)
            self.assertIsNotNone(why, tag)
            self.assertIn(tag, why)
            self.assertEqual(started, [], tag)
            self.assertEqual(killed, [], tag)
            self.assertIn(f"tagged {tag}", inc.records[0][2])

    def test_restarts_are_opt_in_by_default(self):
        with mock.patch.object(wd, "PROFILE", "pc"):
            self.assertIn("auto_restart", wd.blocked_reason({"name": "x", "tags": ()}))
            self.assertIsNone(wd.blocked_reason({"name": "x", "tags": (), "auto_restart": True}))

    def test_every_managed_job_is_opt_in_and_refused_here(self):
        for job in wd.JOBS:
            self.assertFalse(job.get("auto_restart", False), job["name"])
            self.assertTrue(job.get("tags"), job["name"])
            with mock.patch.object(wd, "PROFILE", "pc"):
                self.assertIsNotNone(wd.blocked_reason(job), job["name"])


class FakeProc:
    """The bits of psutil.Process orphan_workers() touches."""

    def __init__(self, pid, name, cmdline, ppid=1, cwd="C:\\", handles=10, age=3600):
        self.pid = pid
        self.info = {"name": name, "cmdline": cmdline, "ppid": ppid}
        self._cwd, self._handles, self._age = cwd, handles, age

    def cwd(self):
        return self._cwd

    def num_handles(self):
        return self._handles

    def create_time(self):
        return time.time() - self._age


class TestOrphanScope(unittest.TestCase):
    def test_only_processes_inside_the_project_folder_are_orphans(self):
        spawn = ("python.exe", ["python.exe", "-c", "from multiprocessing.spawn import spawn_main; "
                                "spawn_main(parent_pid=999, pipe_handle=1)"])
        pieces = ("python.exe", ["python.exe", "-m", "reality_engine.scripts.ingest_annual_reports",
                                 "--pieces-json", "piece.json"])
        wide = ("find.exe", ["find.exe", "/", "-name", "*hash*"])
        with scratch() as d:
            root = d.resolve()
            outside = str(Path(tempfile.gettempdir()).resolve() / "somewhere_else")
            procs = [
                FakeProc(1, *spawn, ppid=999, cwd=str(root)),      # ours: multiprocessing orphan
                FakeProc(2, *spawn, ppid=999, cwd=outside),
                FakeProc(3, *pieces, ppid=999, cwd=str(root)),     # ours: AR pieces child
                FakeProc(4, *pieces, ppid=999, cwd=outside),
                FakeProc(5, *wide, ppid=999, cwd=str(root)),       # ours: whole-disk find
                FakeProc(6, *wide, ppid=999, cwd=outside),
            ]
            with mock.patch.object(wd, "ROOT", root), \
                 mock.patch.object(wd.psutil, "process_iter", lambda attrs=None: procs), \
                 mock.patch.object(wd.psutil, "pid_exists", lambda pid: False):
                found = wd.orphan_workers()
        self.assertEqual([p.pid for p in found], [1, 3, 5])


class TestIncidentsAndReport(unittest.TestCase):
    def test_incidents_are_written_and_deduplicated(self):
        with scratch() as d:
            path = d / "incidents.jsonl"
            with mock.patch.object(wd, "INCIDENTS", path), mock.patch.object(wd.log, "warning"):
                inc = wd.Incidents()
                inc.add("job_stopped", "ar-ingest", "first")
                inc.add("job_stopped", "ar-ingest", "second")
                rows = wd.load_incidents()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "job_stopped")
        self.assertEqual(rows[0]["key"], "ar-ingest")
        self.assertEqual(rows[0]["count"], 2)
        self.assertEqual(rows[0]["detail"], "second")

    def test_dry_run_incidents_are_printed_not_written(self):
        out = io.StringIO()
        with scratch() as d:
            path = d / "incidents.jsonl"
            with mock.patch.object(wd, "INCIDENTS", path), contextlib.redirect_stdout(out):
                wd.Incidents(dry_run=True).add("job_stopped", "ar-ingest", "not running")
                self.assertFalse(path.exists())
        self.assertIn("INCIDENT would be recorded", out.getvalue())
        self.assertIn("ar-ingest", out.getvalue())

    def test_report_renders_status_and_incidents(self):
        with scratch() as d:
            with mock.patch.object(wd, "INCIDENTS", d / "incidents.jsonl"), \
                 mock.patch.object(wd, "REPORT", d / "report.md"), \
                 mock.patch.object(wd, "READER_REPORT", d / "reader.md"), \
                 mock.patch.object(wd, "QUERY_SPEED_REPORT", d / "query.md"), \
                 mock.patch.object(wd, "BOOT_STATUS", d / "boot.json"), \
                 mock.patch.object(wd.log, "warning"):
                wd.Incidents().add("job_stopped", "ar-ingest", "not running; NOT restarting: monitor-only")
                wd.write_report(["profile: laptop (monitor-only)", "machine: CPU 3%"])
            text = (d / "report.md").read_text(encoding="utf-8")
        self.assertIn("# Resource watchdog report", text)
        self.assertIn("## Now", text)
        self.assertIn("- profile: laptop (monitor-only)", text)
        self.assertIn("**job_stopped** [ar-ingest]", text)
        self.assertIn("NOT restarting", text)


class TestDiskChecks(unittest.TestCase):
    def test_free_space_covers_c_and_the_realityengine_folder_only(self):
        self.assertEqual(set(wd.DISK_FREE_MIN_GB), {"C:\\", "D:\\"})
        with mock.patch.object(wd, "disk_paths", return_value=[Path("C:\\"), Path("D:\\RealityEngine")]), \
             mock.patch.object(wd.psutil, "disk_usage", return_value=SimpleNamespace(free=5e9)):
            lines, low = wd.disk_checks()
        self.assertEqual([k for k, _ in low], ["C:\\", "D:\\RealityEngine"])
        self.assertTrue(lines[0].startswith("disk C: 5 GB free (min 20)"), lines[0])
        self.assertTrue(lines[1].startswith("disk D:\\RealityEngine 5 GB free (min 30)"), lines[1])

    def test_a_folder_under_a_volume_without_a_floor_is_not_checked(self):
        with mock.patch.object(wd, "REALITY_DATA_DISK", Path("Q:\\not_ours")):
            self.assertEqual([p.anchor for p in wd.disk_paths()], ["C:\\"])


class TestMachineProfile(unittest.TestCase):
    def test_env_wins_then_file_then_pc(self):
        with scratch() as d:
            f = d / "profile.txt"
            f.write_text("laptop\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(wd, "PROFILE_FILE", f):
                self.assertEqual(wd.machine_profile(), "laptop")
            with mock.patch.dict(os.environ, {"REALITY_WATCHDOG_PROFILE": "pc"}), \
                 mock.patch.object(wd, "PROFILE_FILE", f):
                self.assertEqual(wd.machine_profile(), "pc")
            with mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.object(wd, "PROFILE_FILE", Path(d) / "missing.txt"):
                self.assertEqual(wd.machine_profile(), "pc")


class TestOneCheck(unittest.TestCase):
    def test_dry_run_one_check_acts_on_nothing(self):
        with scratch() as d:
            out = io.StringIO()
            with mock.patch.object(wd, "PROFILE", "laptop"), \
                 mock.patch.object(wd, "LOGS", d / "logs"), \
                 mock.patch.object(wd, "LOCK", d / "watchdog.pid"), \
                 mock.patch.object(wd, "STATE", d / "state.json"), \
                 mock.patch.object(wd, "INCIDENTS", d / "incidents.jsonl"), \
                 mock.patch.object(wd, "REPORT", d / "report.md"), \
                 mock.patch.object(wd.time, "sleep"), \
                 mock.patch.object(wd.subprocess, "Popen") as popen, \
                 contextlib.redirect_stdout(out):
                wd.run(once=True, dry_run=True)
            text = out.getvalue()
            self.assertEqual(list(d.iterdir()), [], "a dry run must write no file at all")
            self.assertEqual(popen.call_count, 0, "a dry run must start no process")
            self.assertIn("INCIDENT would be recorded: job_stopped [ar-ingest]", text)
            self.assertIn("profile: laptop (monitor-only", text)
            self.assertIn("disk C:", text)
            self.assertIn("disk D:\\RealityEngine", text)


if __name__ == "__main__":
    unittest.main()
