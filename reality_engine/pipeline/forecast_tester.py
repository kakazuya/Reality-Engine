"""
Forecast Tester — scheduled price-action forecast testing (Wave B driver).

Each tick scores every resolvable past ``eod_scrip_calls`` date (trading-day
horizons 5/20/60, ensemble + legacy) via ``ValidationHarness``. Scoring writes
are UPSERT-keyed in the repo layer, so re-running is idempotent — never
double-counting, so no new tables, no L1 rows written here, no ability-added
calibration. Runs are recorded in ``data/logs/forecast/`` (JSON summary +
``run_log.jsonl``), keyed off the same IST clock + exclusive lock pattern as
``pipeline/continuous_loop.py``.

Owns ONLY this file + ``reality_engine/scripts/run_forecast_tester.cmd``.
Never edits peer modules. Never touches model_explainer_rankings.
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

logger = logging.getLogger("reality_engine.forecast_tester")

LOOP_SUBDIR = "forecast"
LOCK_NAME = "forecast.lock"
RUN_LOG_NAME = "run_log.jsonl"
STALE_LOCK_SECONDS = 45 * 60
TASK_NAME = "RealityEngine-ForecastTester"
TASK_INTERVAL_MINUTES = 60  # hourly; scoring is evidence-cheap, analyst-light
HORIZONS = (5, 20, 60)
MODES = ("ensemble", "legacy")


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
            logger.warning("breaking stale forecast lock (%.0fs old)", age)
            lock_path.unlink(missing_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise RuntimeError(f"forecast lock held: {lock_path}") from exc
        raise
    os.write(fd, f"{os.getpid()} {_utc_now_iso()}\n".encode("utf-8"))
    return fd


def release_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    Path(lock_path).unlink(missing_ok=True)


def resolvable_call_dates(db, horizons: Sequence[int] = HORIZONS) -> List[str]:
    """Call dates with >= min(horizons) FORWARD trading bars per scoring rule.

    Latest resolvable = latest bar - min horizon (calendar-safe bound; the
    harness itself re-checks per-symbol trading-day counts and skips partials).
    """
    need = min(int(h) for h in horizons)
    with db.session() as conn:
        try:
            calls = [r[0] for r in conn.execute(
                "SELECT DISTINCT date FROM eod_scrip_calls ORDER BY date").fetchall()]
            maxbar = conn.execute(
                "SELECT MAX(date) FROM daily_price_delivery").fetchone()[0]
        except Exception as exc:
            logger.debug("resolvable probe failed: %s", exc)
            return []
    if not calls or not maxbar:
        return []
    cutoff = str(maxbar)[:10]
    with db.session() as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT date FROM daily_price_delivery WHERE date > ? ORDER BY date",
                (str(calls[0])[:10],)).fetchall()
            fwd = [str(r[0])[:10] for r in rows]
        except Exception:
            fwd = []
    out = []
    for d in (str(c)[:10] for c in calls):
        n_fwd = sum(1 for b in fwd if b > d)
        if n_fwd >= need:
            out.append(d)
    return out


def run_once(db_manager=None, loop_dir: Optional[Path] = None,
             horizons: Sequence[int] = HORIZONS,
             dry_run: bool = False) -> Dict[str, Any]:
    """One forecast-test tick. Scores every resolvable call date not yet fully scored."""
    from reality_engine.processing.validation_harness import ValidationHarness

    loop_dir = Path(loop_dir) if loop_dir else default_loop_dir()
    loop_dir.mkdir(parents=True, exist_ok=True)
    lock_path = loop_dir / LOCK_NAME
    started = time.time()
    record: Dict[str, Any] = {"started_at": _utc_now_iso(), "rc": None}
    try:
        fd = acquire_lock(lock_path)
    except RuntimeError as exc:
        record.update({"rc": 2, "note": f"lock held: {exc}"})
        _append_run_log(loop_dir, record)
        return {"skipped": True, "reason": str(exc)}
    try:
        from reality_engine.db.database import db_manager as live
        db = db_manager or live
        dates = resolvable_call_dates(db, horizons)
        record["resolvable_dates"] = len(dates)
        per_date, total_rows = [], 0
        harness = None if dry_run else ValidationHarness(db)
        for d in dates:
            entry: Dict[str, Any] = {"asof_date": d, "modes": {}}
            for mode in MODES:
                try:
                    if dry_run:
                        out = {"rows_written": 0, "dry_run": True}
                    else:
                        out = harness.score_predictions(
                            d, horizon_days=tuple(int(h) for h in horizons), mode=mode)
                    entry["modes"][mode] = {
                        "rows_written": int(out.get("rows_written", 0)),
                        "horizons": {str(k): v.get("n") for k, v in (out.get("horizons") or {}).items()},
                    }
                    total_rows += entry["modes"][mode]["rows_written"]
                except Exception as exc:
                    entry["modes"][mode] = {"error": str(exc)[:200]}
            per_date.append(entry)
        record.update({"rc": 0, "dates_scored": len(dates), "rows_written": total_rows})
        summary_path = loop_dir / f"forecast_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        summary_path.write_text(json.dumps(
            {"started_at": record["started_at"], "dates": per_date}, default=str, indent=2),
            encoding="utf-8")
        record["summary_file"] = str(summary_path)
        _append_run_log(loop_dir, record)
        return {"dates_scored": len(dates), "rows_written": total_rows,
                "summary_file": str(summary_path), "per_date": per_date}
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
    return f'wscript.exe "{scripts / "run_hidden.vbs"}" "{scripts / "run_forecast_tester.cmd"}"'


def install_task(interval_minutes: int = TASK_INTERVAL_MINUTES) -> Dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "reason": "not Windows",
                "cron": f"{interval_minutes % 60} * * * * cd {repo_root()} && python -m reality_engine.pipeline.forecast_tester"}
    proc = subprocess.run(
        ["schtasks", "/create", "/tn", TASK_NAME, "/sc", "MINUTE",
         "/mo", str(int(interval_minutes)), "/tr", _task_command(), "/f"],
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
    parser = argparse.ArgumentParser(description="Forecast tester: score resolvable prediction runs.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve dates, zero writes")
    parser.add_argument("--loop-dir", default=None)
    parser.add_argument("--install", action="store_true", help="Register the hourly Windows scheduled task")
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
    result = run_once(loop_dir=Path(args.loop_dir) if args.loop_dir else None,
                      dry_run=args.dry_run)
    if result.get("skipped"):
        print(json.dumps(result, indent=2))
        return 2
    print(json.dumps({k: v for k, v in result.items()}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
