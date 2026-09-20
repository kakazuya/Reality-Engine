"""
Capacity loop — scheduled explainer-capacity governor (report-only by default).

Each tick runs ``capacity_governor.evaluate()`` over every (regime, investor)
cohort and records decided + skipped cohorts in ``data/logs/capacity/``. It
NEVER writes ``model_explainer_rankings`` unless invoked with
``--apply-capacity --cohort REGIME/INVESTOR`` — an explicit, deliberate call,
never a scheduled flag. This is the repo's unattended-calibration ban made
structural: the scheduled task target passes no apply flag.

Owns ONLY this file + ``reality_engine/scripts/run_capacity_loop.cmd``.
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

logger = logging.getLogger("reality_engine.capacity_loop")

LOOP_SUBDIR = "capacity"
LOCK_NAME = "capacity.lock"
RUN_LOG_NAME = "run_log.jsonl"
STALE_LOCK_SECONDS = 45 * 60
TASK_NAME = "RealityEngine-CapacityLoop"
TASK_INTERVAL_MINUTES = 360  # 6h: capacity moves on accumulated evidence, not ticks


def repo_root() -> Path:
    return _PROJECT_ROOT


def default_loop_dir() -> Path:
    from reality_engine import config

    return Path(config.DATA_DIR) / "logs" / LOOP_SUBDIR


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def acquire_lock(lock_path: Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age > STALE_LOCK_SECONDS:
            logger.warning("breaking stale capacity lock (%.0fs old)", age)
            lock_path.unlink(missing_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise RuntimeError(f"capacity lock held: {lock_path}") from exc
        raise
    os.write(fd, f"{os.getpid()} {_utc_now_iso()}\n".encode("utf-8"))
    return fd


def release_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    Path(lock_path).unlink(missing_ok=True)


def _parse_cohorts(raw: Optional[Sequence[str]]) -> List[tuple]:
    out = []
    for item in raw or []:
        if "/" in str(item):
            r, inv = str(item).split("/", 1)
            out.append((r.strip(), inv.strip()))
    return out


def run_once(db_manager=None, loop_dir: Optional[Path] = None,
             apply_cohorts: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """One capacity tick. Report-only unless apply_cohorts names decided cohorts."""
    from reality_engine.processing import capacity_governor as cg

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
        evaluation = cg.evaluate(db)
        record.update({
            "rc": 0,
            "decided": len(evaluation["decided"]),
            "skipped": len(evaluation["skipped"]),
            "skip_reasons": sorted({d.get("reason", "?")[:80] for d in evaluation["skipped"]}),
        })
        applied = []
        wanted = _parse_cohorts(apply_cohorts)
        if wanted:
            by_key = {(d["regime_tag"], d["investor_majority"]): d
                      for d in evaluation["decided"]}
            for key in wanted:
                decision = by_key.get(key)
                if decision is None:
                    applied.append({"cohort": f"{key[0]}/{key[1]}", "applied": False,
                                    "reason": "not decided this tick — refusing"})
                    continue
                try:
                    res = cg.apply_decision(db, decision)
                    applied.append({"cohort": f"{key[0]}/{key[1]}", "applied": True, **res})
                except Exception as exc:
                    applied.append({"cohort": f"{key[0]}/{key[1]}", "applied": False,
                                    "reason": str(exc)[:200]})
            record["applied"] = applied
        summary_path = loop_dir / f"capacity_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        summary_path.write_text(json.dumps(
            {"started_at": record["started_at"], "evaluation": evaluation,
             "applied": applied}, default=str, indent=2), encoding="utf-8")
        record["summary_file"] = str(summary_path)
        record["duration_seconds"] = round(time.time() - started, 1)
        _append_run_log(loop_dir, record)
        return {"decided": len(evaluation["decided"]), "skipped": len(evaluation["skipped"]),
                "skip_reasons": record["skip_reasons"], "applied": applied,
                "summary_file": str(summary_path), "evaluation": evaluation}
    finally:
        release_lock(fd, lock_path)


def _append_run_log(loop_dir: Path, record: Dict[str, Any]) -> Path:
    path = Path(loop_dir) / RUN_LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return path


# ---------------------------------------------------------------------------
# Scheduled task management
# ---------------------------------------------------------------------------
def _task_command() -> str:
    scripts = repo_root() / "reality_engine" / "scripts"
    return f'wscript.exe "{scripts / "run_hidden.vbs"}" "{scripts / "run_capacity_loop.cmd"}"'


def install_task(interval_minutes: int = TASK_INTERVAL_MINUTES) -> Dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "reason": "not Windows",
                "cron": f"0 */{max(1, interval_minutes // 60)} * * * cd {repo_root()} && python -m reality_engine.pipeline.capacity_loop"}
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
    parser = argparse.ArgumentParser(
        description="Capacity governor: evaluate explainer-capacity moves (report-only unless --apply-capacity).")
    parser.add_argument("--apply-capacity", action="store_true",
                        help="DELIBERATE: apply decided cohorts named in --cohort (never scheduled)")
    parser.add_argument("--cohort", action="append", default=None,
                        help="REGIME/INVESTOR to apply (repeatable); only meaningful with --apply-capacity")
    parser.add_argument("--loop-dir", default=None)
    parser.add_argument("--install", action="store_true", help="Register the 6h Windows scheduled task")
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
    if args.cohort and not args.apply_capacity:
        print("--cohort without --apply-capacity is a no-op (report-only); refusing to guess intent")
        return 1
    result = run_once(loop_dir=Path(args.loop_dir) if args.loop_dir else None,
                      apply_cohorts=args.cohort if args.apply_capacity else None)
    if result.get("skipped"):
        print(json.dumps(result, indent=2))
        return 2
    print(json.dumps({k: v for k, v in result.items() if k != "evaluation"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
