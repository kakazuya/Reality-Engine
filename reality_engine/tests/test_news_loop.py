"""
News loop driver tests (temp loop dir + injected fakes — never the network,
never schtasks, never the live DB).

Covers the behaviours the daily scheduler depends on:
  * a dry run performs zero writes and zero deletes (no destructive kwargs)
  * the apply path persists, captures with keep_files=False and prunes files
  * a raising fetch step does not abort the other three steps; rc becomes 1
  * an in-flight tick blocks an overlapping tick (rc 2); a stale lock is broken
  * --install builds an exact ``/sc DAILY /st 06:30`` schtasks argv (never run)
  * main() with no args is a dry run — an accidental call cannot delete
  * the summary json + run-log line are written for a faked-backend run
  * importing the module performs no I/O
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from reality_engine.pipeline import news_loop as nl

REPO_ROOT = Path(nl.__file__).resolve().parents[2]
TASK_CMD = f'wscript.exe "{REPO_ROOT / "reality_engine" / "scripts" / "run_hidden.vbs"}" "{REPO_ROOT / "reality_engine" / "scripts" / "run_news_loop.cmd"}"'

RECORDS = [
    {"title": "Nifty closes higher", "text": "Nifty 50 closed up 0.4%.",
     "media_url": "https://cdn.example.com/a.png", "source_type": "News_nse"},
    {"title": "RBI holds rates", "text": "Policy rate unchanged.",
     "media_url": "", "source_type": "News_rbi"},
]
FETCH_STATS = {"feeds_requested": 2, "feeds_ok": 2, "feeds_failed": 0,
               "items": 5, "records": 2}
CAPTURE_COUNTS = {"attempted": 2, "downloaded": 1, "ocr_ok": 1, "chunks_written": 1,
                  "artifacts_written": 1, "files_deleted": 1, "skipped_no_media": 1,
                  "skipped_duplicate_media": 0, "skipped_existing": 0,
                  "skipped_low_signal": 0, "errors": []}
PRUNE_COUNTS = {"cutoff": "2026-08-21", "candidates": 4, "raw_deleted": 3,
                "fts_deleted": 3, "files_deleted": 0, "skipped_unextracted": 1,
                "skipped_structural": 2, "errors": []}
PRUNE_IMAGE_COUNTS = {"cutoff": "2026-08-21", "candidates": 2, "files_deleted": 2,
                      "rows_cleared": 2, "skipped_no_chunk": 0, "errors": []}


class _Spy:
    """Callable test double recording ``(args, kwargs)`` and returning a fixed value."""

    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result

    @property
    def called(self):
        return bool(self.calls)


class NewsLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.loop_dir = Path(self.tmp.name) / "loop"
        self.addCleanup(self.tmp.cleanup)

    # -- helpers --------------------------------------------------------
    def _patch_backends(self, *, fetch=None, persist=None, capture=None,
                        prune=None, prune_images=None):
        patches = [
            mock.patch("reality_engine.ingestion.news_feed_client.fetch_feeds",
                       fetch if fetch is not None else _Spy((RECORDS, FETCH_STATS))),
            mock.patch("reality_engine.ingestion.news_feed_client.persist",
                       persist if persist is not None else _Spy(
                           {"raw_written": 2, "raw_updated": 1, "fts_written": 2})),
            mock.patch("reality_engine.processing.news_vision.capture_images",
                       capture if capture is not None else _Spy(dict(CAPTURE_COUNTS))),
            mock.patch("reality_engine.pipeline.news_retention.prune_news",
                       prune if prune is not None else _Spy(dict(PRUNE_COUNTS))),
            mock.patch("reality_engine.pipeline.news_retention.prune_news_images",
                       prune_images if prune_images is not None else _Spy(dict(PRUNE_IMAGE_COUNTS))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _run_log_records(self):
        path = self.loop_dir / nl.RUN_LOG_NAME
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    # -- 1. dry run -----------------------------------------------------
    def test_dry_run_performs_zero_writes_and_deletes(self):
        persist, capture = _Spy(), _Spy()
        prune, prune_images = _Spy(dict(PRUNE_COUNTS)), _Spy(dict(PRUNE_IMAGE_COUNTS))
        self._patch_backends(persist=persist, capture=capture,
                             prune=prune, prune_images=prune_images)

        result = nl.run_once(loop_dir=self.loop_dir, db_manager=object(), dry_run=True)

        self.assertEqual(result["rc"], 0)
        self.assertTrue(result["dry_run"])
        self.assertFalse(persist.called, "dry run must not persist")
        self.assertFalse(capture.called, "dry run must not download/OCR images")
        self.assertEqual(result["steps"]["images"]["status"], "skipped")
        self.assertEqual(result["steps"]["fetch"]["items"], 5)
        self.assertEqual(result["steps"]["fetch"]["raw_written"], 0)

        # The prune probes still report, but never destructively.
        self.assertEqual(len(prune.calls), 1)
        self.assertEqual(len(prune_images.calls), 1)
        for spy in (prune, prune_images):
            _, kwargs = spy.calls[0]
            self.assertTrue(kwargs["dry_run"])
            self.assertFalse(kwargs["delete_files"], "dry run must not delete files")
        self.assertFalse(self.loop_dir.joinpath(nl.LOCK_NAME).exists(), "lock must be released")

    # -- 2. apply path --------------------------------------------------
    def test_apply_run_persists_captures_and_prunes(self):
        fetch, persist = _Spy((RECORDS, FETCH_STATS)), _Spy(
            {"raw_written": 2, "raw_updated": 1, "fts_written": 2})
        capture = _Spy(dict(CAPTURE_COUNTS))
        prune, prune_images = _Spy(dict(PRUNE_COUNTS)), _Spy(dict(PRUNE_IMAGE_COUNTS))
        self._patch_backends(fetch=fetch, persist=persist, capture=capture,
                             prune=prune, prune_images=prune_images)

        result = nl.run_once(loop_dir=self.loop_dir, db_manager=object(), dry_run=False)

        self.assertEqual(result["rc"], 0)
        self.assertEqual(fetch.calls[0][1], {"limit": nl.FEED_LIMIT})
        self.assertEqual(persist.calls[0][0], (RECORDS,))
        self.assertEqual(result["steps"]["fetch"]["raw_written"], 2)
        self.assertEqual(result["steps"]["fetch"]["fts_written"], 2)

        self.assertEqual(capture.calls[0][0], (RECORDS,))
        self.assertEqual(capture.calls[0][1]["limit"], nl.IMAGE_LIMIT)
        self.assertFalse(capture.calls[0][1]["keep_files"],
                         "the bitmap must be dropped once OCR text is stored")
        self.assertEqual(result["steps"]["images"]["chunks_written"], 1)

        for spy in (prune, prune_images):
            _, kwargs = spy.calls[0]
            self.assertFalse(kwargs["dry_run"])
            self.assertTrue(kwargs["delete_files"])
            self.assertEqual(kwargs["before_days"], nl.PRUNE_DAYS)
        self.assertEqual(result["steps"]["prune"]["raw_deleted"], 3)
        self.assertEqual(result["steps"]["prune_images"]["files_deleted"], 2)

        summary = Path(result["summary_file"])
        self.assertTrue(summary.exists())
        self.assertRegex(summary.name, r"^news_\d{8}_\d{4}\.json$")
        payload = json.loads(summary.read_text(encoding="utf-8"))
        self.assertEqual(payload["rc"], 0)
        self.assertEqual(sorted(payload["steps"]),
                         ["fetch", "images", "prune", "prune_images"])

        runs = self._run_log_records()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["rc"], 0)
        self.assertEqual(runs[0]["summary_file"], str(summary))
        self.assertEqual(runs[0]["steps"]["prune_images"]["rows_cleared"], 2)

    # -- 3. fail-closed steps -------------------------------------------
    def test_failing_fetch_does_not_abort_the_other_steps(self):
        def boom(*args, **kwargs):
            raise RuntimeError("feed registry exploded")

        capture, prune = _Spy(dict(CAPTURE_COUNTS)), _Spy(dict(PRUNE_COUNTS))
        prune_images = _Spy(dict(PRUNE_IMAGE_COUNTS))
        self._patch_backends(fetch=boom, capture=capture, prune=prune,
                             prune_images=prune_images)

        result = nl.run_once(loop_dir=self.loop_dir, db_manager=object(), dry_run=False)

        self.assertEqual(result["steps"]["fetch"]["status"], "failed")
        self.assertIn("feed registry exploded", result["steps"]["fetch"]["error"])
        for step in ("images", "prune", "prune_images"):
            self.assertEqual(result["steps"][step]["status"], "ok", step)
        self.assertTrue(capture.called)
        self.assertTrue(prune.called)
        self.assertTrue(prune_images.called)
        self.assertEqual(result["rc"], 1, "a failed step must fail the tick")
        self.assertEqual(self._run_log_records()[-1]["rc"], 1)

    def test_failing_prune_does_not_abort_the_others(self):
        def boom(*args, **kwargs):
            raise RuntimeError("no such table: raw_documents")

        capture = _Spy(dict(CAPTURE_COUNTS))
        prune_images = _Spy(dict(PRUNE_IMAGE_COUNTS))
        self._patch_backends(capture=capture, prune=boom, prune_images=prune_images)

        result = nl.run_once(loop_dir=self.loop_dir, db_manager=object(), dry_run=False)

        self.assertEqual(result["steps"]["fetch"]["status"], "ok")
        self.assertEqual(result["steps"]["prune"]["status"], "failed")
        self.assertEqual(result["steps"]["prune_images"]["status"], "ok")
        self.assertTrue(prune_images.called)
        self.assertEqual(result["rc"], 1)

    # -- 4. locking -----------------------------------------------------
    def test_lock_contention_returns_skipped_rc2(self):
        self._patch_backends()
        self.loop_dir.mkdir(parents=True, exist_ok=True)
        fd = nl.acquire_lock(self.loop_dir / nl.LOCK_NAME)
        try:
            result = nl.run_once(loop_dir=self.loop_dir, dry_run=False)
            self.assertTrue(result["skipped"])
            self.assertEqual(result["rc"], 2)
            self.assertIn("news lock held", result["reason"])
            self.assertEqual(self._run_log_records()[-1]["rc"], 2)
        finally:
            nl.release_lock(fd, self.loop_dir / nl.LOCK_NAME)
        self.assertFalse(self.loop_dir.joinpath(nl.LOCK_NAME).exists())

    def test_stale_lock_is_broken(self):
        lock = self.loop_dir / nl.LOCK_NAME
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("dead run", encoding="utf-8")
        old = time.time() - (nl.STALE_LOCK_SECONDS + 60)
        os.utime(lock, (old, old))
        fd = nl.acquire_lock(lock)
        try:
            self.assertTrue(lock.exists())
        finally:
            nl.release_lock(fd, lock)

    # -- 5. scheduled task management -----------------------------------
    def test_install_builds_daily_schtasks_command(self):
        run = _Spy(SimpleNamespace(returncode=0, stdout="SUCCESS", stderr=""))
        with mock.patch.object(nl.os, "name", "nt"), \
                mock.patch.object(nl.subprocess, "run", run):
            result = nl.install_task()

        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"], "SUCCESS")
        self.assertEqual(run.calls[0][0][0], [
            "schtasks", "/create", "/tn", "RealityEngine-NewsLoop",
            "/sc", "DAILY", "/st", "06:30", "/tr", TASK_CMD, "/f",
        ])
        self.assertNotIn("/mo", run.calls[0][0][0], "daily, not minute-interval")

    def test_uninstall_and_status_use_the_shared_task_name(self):
        run = _Spy(SimpleNamespace(returncode=0, stdout="ok", stderr=""))
        with mock.patch.object(nl.os, "name", "nt"), \
                mock.patch.object(nl.subprocess, "run", run):
            self.assertTrue(nl.uninstall_task()["ok"])
            self.assertTrue(nl.task_status()["registered"])

        self.assertEqual(run.calls[0][0][0], ["schtasks", "/delete", "/tn", nl.TASK_NAME, "/f"])
        self.assertEqual(run.calls[1][0][0],
                         ["schtasks", "/query", "/tn", nl.TASK_NAME, "/fo", "LIST", "/v"])

    def test_non_windows_install_returns_a_cron_fallback(self):
        with mock.patch.object(nl.os, "name", "posix"):
            result = nl.install_task()
        self.assertFalse(result["ok"])
        self.assertEqual(result["cron"], f"30 6 * * * cd {REPO_ROOT} && "
                                         "python -m reality_engine.pipeline.news_loop --run")

    # -- 6. main() defaults ---------------------------------------------
    def test_main_defaults_to_dry_run(self):
        run_once = _Spy({"rc": 0, "dry_run": True, "steps": {}})
        with mock.patch.object(nl, "run_once", run_once):
            self.assertEqual(nl.main([]), 0)
            self.assertTrue(run_once.calls[0][1]["dry_run"], "no flags must never delete")
            self.assertEqual(nl.main(["--run"]), 0)
            self.assertFalse(run_once.calls[1][1]["dry_run"])
            self.assertEqual(nl.main(["--dry-run", "--run"]), 0)
            self.assertTrue(run_once.calls[2][1]["dry_run"], "--dry-run wins over --run")

    def test_main_returns_2_on_lock_contention(self):
        with mock.patch.object(nl, "run_once", _Spy({"skipped": True, "rc": 2})):
            self.assertEqual(nl.main([]), 2)

    def test_cmd_target_runs_the_apply_chain(self):
        cmd_path = REPO_ROOT / "reality_engine" / "scripts" / "run_news_loop.cmd"
        self.assertIn(str(cmd_path), TASK_CMD, "scheduler must route through the .cmd entry point")
        text = cmd_path.read_text(encoding="utf-8")
        self.assertIn("-m reality_engine.pipeline.news_loop --run %*", text)
        self.assertIn('cd /d "%~dp0..\\.."', text)
        self.assertIn("exit /b %ERRORLEVEL%", text)

    def test_hidden_launcher_hides_the_window(self):
        launcher = REPO_ROOT / "reality_engine" / "scripts" / "run_hidden.vbs"
        text = launcher.read_text(encoding="utf-8")
        self.assertIn(", 0, True)", text, "window style 0 (hidden) with wait")
        self.assertIn("WScript.Quit rc", text, "exit code must propagate to Task Scheduler")

    # -- 7. import hygiene ----------------------------------------------
    def test_import_is_clean_and_performs_no_io(self):
        data_dir = Path(self.tmp.name) / "data"
        env = dict(os.environ,
                   REALITY_ENGINE_DATA_DIR=str(data_dir),
                   REALITY_ENGINE_DB_PATH=str(data_dir / "equity_intelligence.db"))
        proc = subprocess.run(
            [sys.executable, "-c", "import reality_engine.pipeline.news_loop"],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((proc.stdout or "").strip(), "")
        self.assertEqual((proc.stderr or "").strip(), "")
        self.assertFalse(data_dir.exists(), "importing the module must not touch the data dir")


if __name__ == "__main__":
    unittest.main()
