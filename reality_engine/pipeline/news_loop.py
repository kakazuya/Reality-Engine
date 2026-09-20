"""
News loop — scheduled daily news ingest + infographic capture + prune.

One daily tick runs the "extract the info, then delete the papers" chain over
the official-outlet RSS registry:

  1. ``fetch``        — ``news_feed_client.fetch_feeds(limit=FEED_LIMIT)`` then
                        ``persist`` (raw_documents upsert + one FTS chunk each);
  2. ``images``       — ``news_vision.capture_images(..., keep_files=False)``:
                        download each infographic, OCR it into
                        ``intelligence_fts`` + ``news_visual_artifacts``, then
                        drop the bitmap (the dense record is the durable copy);
  3. ``prune``        — ``news_retention.prune_news(before_days=PRUNE_DAYS)``:
                        delete only rows whose extraction proof exists;
  4. ``prune_images`` — ``news_retention.prune_news_images(...)``: unlink aged
                        bitmaps, keep every dense record (re-fetchable via
                        ``media_url``).

Deletion is the DESIGNED behaviour of this loop (the operator asked for
extract-then-delete), so the scheduled target passes ``--run`` — an explicit
apply flag, never implicit. The default invocation is ``--dry-run`` (zero
writes, zero deletes) so an accidental call cannot destroy anything.

Every step is fail-closed and independently wrapped: one dead feed or a missing
table never aborts the other steps, and any failed step makes the tick exit 1.
Runs are recorded in ``data/logs/news/`` (JSON summary + ``run_log.jsonl``),
keyed off the same exclusive-lock + stale-lock pattern as
``pipeline/forecast_tester.py`` (its own ``news.lock``, so it never contends
with the continuous / forecast / capacity loops).

Owns ONLY this file + ``reality_engine/scripts/run_news_loop.cmd``.
Never edits peer modules. Never touches ``model_explainer_rankings``.
"""

from __future__ import annotations

import argparse
import errno
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("reality_engine.news_loop")

LOOP_SUBDIR = "news"
LOCK_NAME = "news.lock"
RUN_LOG_NAME = "run_log.jsonl"
STALE_LOCK_SECONDS = 45 * 60
TASK_NAME = "RealityEngine-NewsLoop"
TASK_START_TIME = "06:30"
TASK_INTERVAL_MINUTES = 1440  # daily; news moves once a day, not on ticks
FEED_LIMIT = 60  # items per feed
IMAGE_LIMIT = 40  # infographics per tick
PRUNE_DAYS = 30


def repo_root() -> Path:
    return _PROJECT_ROOT


def default_loop_dir() -> Path:
    from reality_engine import config

    return Path(config.DATA_DIR) / "logs" / LOOP_SUBDIR


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def acquire_lock(lock_path: Path) -> int:
    """Exclusive tick lock; stale locks (>45min) are broken."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age > STALE_LOCK_SECONDS:
            logger.warning("breaking stale news lock (%.0fs old)", age)
            lock_path.unlink(missing_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise RuntimeError(f"news lock held: {lock_path}") from exc
        raise
    os.write(fd, f"{os.getpid()} {_utc_now_iso()}\n".encode("utf-8"))
    return fd


def release_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    Path(lock_path).unlink(missing_ok=True)


def run_once(loop_dir: Optional[Path] = None, db_manager: Any = None,
             dry_run: bool = False, feed_limit: int = FEED_LIMIT,
             image_limit: int = IMAGE_LIMIT, prune_days: int = PRUNE_DAYS
             ) -> Dict[str, Any]:
    """One news tick: fetch -> capture infographics -> prune news + images.

    ``dry_run=True`` fetches and reports only: nothing is persisted, no image is
    downloaded, no row is deleted and no bitmap is unlinked.

    Every step is independently fail-closed (``status`` = ``ok`` | ``failed`` |
    ``skipped`` + ``error``); the tick's ``rc`` is 1 when any step failed.
    ``db_manager=None`` lets each backend resolve the live manager itself.
    """
    from reality_engine.ingestion import news_feed_client as nfc
    from reality_engine.processing import news_vision as nv
    from reality_engine.pipeline import news_retention as nr

    loop_dir = Path(loop_dir) if loop_dir else default_loop_dir()
    loop_dir.mkdir(parents=True, exist_ok=True)
    lock_path = loop_dir / LOCK_NAME
    started = time.time()
    record: Dict[str, Any] = {"started_at": _utc_now_iso(), "rc": None,
                              "dry_run": bool(dry_run)}
    try:
        fd = acquire_lock(lock_path)
    except RuntimeError as exc:
        record.update({"rc": 2, "note": f"lock held: {exc}"})
        _append_run_log(loop_dir, record)
        return {"skipped": True, "rc": 2, "reason": str(exc)}
    try:
        steps: Dict[str, Any] = {}
        records: List[Dict[str, Any]] = []

        # --- 1. fetch + persist (official-outlet RSS) ---------------------
        try:
            records, stats = nfc.fetch_feeds(limit=feed_limit)
            records = list(records or [])
            step: Dict[str, Any] = {
                "status": "ok",
                "feeds_ok": int((stats or {}).get("feeds_ok", 0)),
                "feeds_failed": int((stats or {}).get("feeds_failed", 0)),
                "items": int((stats or {}).get("items", 0)),
                "records": len(records),
            }
            if dry_run:
                step.update({"raw_written": 0, "raw_updated": 0, "fts_written": 0,
                             "dry_run": True})
            else:
                written = nfc.persist(records)
                step.update({
                    "raw_written": int((written or {}).get("raw_written", 0)),
                    "raw_updated": int((written or {}).get("raw_updated", 0)),
                    "fts_written": int((written or {}).get("fts_written", 0)),
                })
            steps["fetch"] = step
        except Exception as exc:
            steps["fetch"] = {"status": "failed", "error": str(exc)[:200]}

        # --- 2. infographic capture (skipped whole on a dry run) ----------
        if dry_run:
            steps["images"] = {"status": "skipped", "reason": "dry_run"}
        else:
            try:
                capture = nv.capture_images(records, db=db_manager,
                                            limit=image_limit, keep_files=False)
                steps["images"] = {"status": "ok", **dict(capture or {})}
            except Exception as exc:
                steps["images"] = {"status": "failed", "error": str(exc)[:200]}

        # --- 3. prune extracted news rows --------------------------------
        try:
            pruned = nr.prune_news(before_days=prune_days, dry_run=dry_run,
                                   delete_files=not dry_run, db=db_manager)
            steps["prune"] = {"status": "ok", **dict(pruned or {})}
        except Exception as exc:
            steps["prune"] = {"status": "failed", "error": str(exc)[:200]}

        # --- 4. prune aged infographic bitmaps ---------------------------
        try:
            pruned_images = nr.prune_news_images(before_days=prune_days, dry_run=dry_run,
                                                 delete_files=not dry_run, db=db_manager)
            steps["prune_images"] = {"status": "ok", **dict(pruned_images or {})}
        except Exception as exc:
            steps["prune_images"] = {"status": "failed", "error": str(exc)[:200]}

        rc = 1 if any(s.get("status") == "failed" for s in steps.values()) else 0
        record.update({"rc": rc, "steps": steps,
                       "duration_seconds": round(time.time() - started, 1)})
        summary_path = loop_dir / f"news_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        summary_path.write_text(json.dumps(record, default=str, indent=2),
                                encoding="utf-8")
        record["summary_file"] = str(summary_path)
        _append_run_log(loop_dir, record)
        return {"started_at": record["started_at"], "rc": rc, "dry_run": bool(dry_run),
                "steps": steps, "duration_seconds": record["duration_seconds"],
                "summary_file": str(summary_path)}
    finally:
        release_lock(fd, lock_path)


def _run_log_path(loop_dir: Path) -> Path:
    return Path(loop_dir) / RUN_LOG_NAME


def _append_run_log(loop_dir: Path, record: Dict[str, Any]) -> Path:
    path = _run_log_path(loop_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return path


# ---------------------------------------------------------------------------
# Scheduled task management
# ---------------------------------------------------------------------------
def _task_command() -> str:
    scripts = repo_root() / "reality_engine" / "scripts"
    return f'wscript.exe "{scripts / "run_hidden.vbs"}" "{scripts / "run_news_loop.cmd"}"'


def _cron_line(start_time: str = TASK_START_TIME) -> str:
    try:
        hour, minute = (int(p) for p in str(start_time).split(":", 1))
    except Exception:
        hour, minute = 6, 30
    return (f"{minute} {hour} * * * cd {repo_root()} && "
            f"python -m reality_engine.pipeline.news_loop --run")


def install_task(start_time: str = TASK_START_TIME) -> Dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "reason": "not Windows", "cron": _cron_line(start_time)}
    proc = subprocess.run(
        ["schtasks", "/create", "/tn", TASK_NAME, "/sc", "DAILY",
         "/st", str(start_time), "/tr", _task_command(), "/f"],
        capture_output=True, text=True, check=False)
    return {"ok": proc.returncode == 0, "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip()}


def uninstall_task() -> Dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "reason": "not Windows"}
    proc = subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                          capture_output=True, text=True, check=False)
    return {"ok": proc.returncode == 0, "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip()}


def task_status() -> Dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "reason": "not Windows"}
    proc = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST", "/v"],
                          capture_output=True, text=True, check=False)
    return {"ok": proc.returncode == 0, "registered": proc.returncode == 0,
            "stdout": (proc.stdout or "").strip(), "stderr": (proc.stderr or "").strip()}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="News loop: ingest official-outlet RSS, capture infographics, prune extracted news.")
    parser.add_argument("--run", action="store_true",
                        help="Full chain incl. persistence, capture and deletion (the scheduled path)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only: zero writes, zero deletes (default)")
    parser.add_argument("--loop-dir", default=None)
    parser.add_argument("--install", action="store_true",
                        help="Register the daily Windows scheduled task (06:30)")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.install:
        res = install_task()
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if args.uninstall:
        res = uninstall_task()
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if args.status:
        res = task_status()
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    dry_run = args.dry_run or not args.run
    result = run_once(loop_dir=Path(args.loop_dir) if args.loop_dir else None,
                      dry_run=dry_run)
    if result.get("skipped"):
        print(json.dumps(result, indent=2))
        return 2
    print(json.dumps(result, indent=2, default=str))
    return int(result.get("rc", 1))


if __name__ == "__main__":
    sys.exit(main())
