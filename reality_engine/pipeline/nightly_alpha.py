"""
Wave A — Unattended Nightly Run Chain (fetch -> predict -> correct).

Sequential stages with per-stage try/except and JSON status:

  fetch_predict part (19:45 slot):
    (1a) master sync via ``master_sync.sync_all``
    (1b) backfill gap via ``backfill_bhavcopy_history(days=auto)``
         auto = missing trading days + 5 buffer, capped at 60
    (1c) fundamentals refresh top-200 (reuses phase1_runner universe selection
         + ``fundamentals_client.fetch_all_fundamentals``; no refetch logic here)
    (1d) verify-checkpoint gate — ABORTS predict stages when it fails
    (2a) legacy screen full-universe top-20 (universe="all")
    (2b) ensemble screen same universe; each screen is snapshotted to
         ``data/logs/`` IMMEDIATELY after it runs because ``eod_scrip_calls``
         has no date-purge (second screen would clobber the first on
         overlapping symbols — same pattern as the prior manual runs)
    (2c) run-daily-alpha both modes (ensemble + legacy) with immediate rename
         to ``daily_alpha_{ensemble,legacy}.*`` to avoid filename collision
         (ReportWriter always writes ``daily_alpha.{json,md,html}``)
  correct_validate part (23:00 slot):
    EOD self-correction via ``EODCorrector.correct_eod`` (closed-session
    guard intact — never bypassed, never reimplemented here)

Health summary ``data/logs/nightly_<YYYY-MM-DD>.json`` carries stage
statuses, row deltas, checkpoint %, top-20 overlap and exit_code.

Overlap protection: exclusive lock file ``data/logs/nightly.lock``
(Windows-safe ``os.open`` with ``O_CREAT | O_EXCL``; stale lock broken
after 6h via mtime). Non-zero exit on any stage failure.

Run:
    python reality_engine/cli.py nightly [--dry-run] [--part fetch_predict|correct_validate|all]
    python -m reality_engine.pipeline.nightly_alpha [--dry-run] [--part all]

--dry-run resolves dates, prints the planned stages and performs ZERO
DB/network writes (no lock file, no health JSON, no stage calls).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("reality_engine.nightly_alpha")

# ---------------------------------------------------------------------------
# IST timezone helpers (mirrors catchup_scheduler; stdlib only, no pytz)
# ---------------------------------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))

LOCK_NAME = "nightly.lock"
STALE_LOCK_SECONDS = 6 * 3600  # 6h
BACKFILL_BUFFER = 5
BACKFILL_CAP = 60

VALID_PARTS: Tuple[str, ...] = ("fetch_predict", "correct_validate", "all")

FETCH_STAGES: Tuple[str, ...] = (
    "master_sync",
    "backfill",
    "fundamentals",
    "checkpoint",
    "screen_legacy",
    "screen_ensemble",
    "daily_alpha_ensemble",
    "daily_alpha_legacy",
)
CORRECT_STAGES: Tuple[str, ...] = ("eod_correct",)

DELTA_TABLES: Tuple[str, ...] = (
    "master_companies",
    "daily_price_delivery",
    "quarterly_financials",
    "annual_financials",
    "company_forensic_health",
    "corporate_documents",
    "eod_scrip_calls",
)


def now_ist() -> datetime:
    """Return the current wall-clock time in IST (tz-aware)."""
    return datetime.now(IST)


def today_ist_str(override: Optional[str] = None) -> str:
    """Resolve the run date (YYYY-MM-DD); override wins, else today IST."""
    if override:
        return date.fromisoformat(override.strip()[:10]).isoformat()
    return now_ist().date().isoformat()


def compact_date(date_iso: str) -> str:
    """Compact YYYY-MM-DD -> YYYYMMDD for snapshot filenames (prior-run style)."""
    return date_iso.replace("-", "")


def default_log_dir() -> Path:
    from reality_engine import config

    d = Path(config.DATA_DIR) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_lock_path(log_dir: Optional[Path] = None) -> Path:
    base = Path(log_dir) if log_dir is not None else default_log_dir()
    return base / LOCK_NAME


# ---------------------------------------------------------------------------
# Overlap protection (Windows-safe exclusive create)
# ---------------------------------------------------------------------------
def acquire_lock(lock_path: Path) -> int:
    """Acquire the exclusive nightly lock; raise RuntimeError if held.

    Stale locks older than 6h (mtime) are broken and retried once.
    Returns the OS file descriptor the caller must pass to release_lock.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
        try:
            os.write(fd, f"{os.getpid()} {now_ist().isoformat()}\n".encode("utf-8"))
        except Exception:
            pass
        return fd
    except FileExistsError:
        pass
    # Lock exists — check staleness via mtime.
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError as exc:
        raise RuntimeError(f"nightly lock unreadable: {lock_path} ({exc})")
    if age > STALE_LOCK_SECONDS:
        logger.warning("breaking stale nightly lock (age %.1fh): %s", age / 3600.0, lock_path)
        try:
            os.unlink(str(lock_path))
        except OSError as exc:
            raise RuntimeError(f"nightly lock held (stale break failed): {lock_path} ({exc})")
        try:
            fd = os.open(str(lock_path), flags)
            try:
                os.write(fd, f"{os.getpid()} {now_ist().isoformat()}\n".encode("utf-8"))
            except Exception:
                pass
            return fd
        except FileExistsError:
            pass
        raise RuntimeError(f"nightly lock contention on {lock_path} (lost stale race)")
    raise RuntimeError(
        f"another nightly run holds the lock: {lock_path} (age {age:.0f}s < 6h)"
    )


def release_lock(fd: int, lock_path: Path) -> None:
    """Release a lock acquired via acquire_lock (close + unlink, best-effort)."""
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        os.unlink(str(lock_path))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Planning helpers
# ---------------------------------------------------------------------------
def plan_stages(part: str) -> List[str]:
    """Ordered stage names for a --part value."""
    if part == "fetch_predict":
        return list(FETCH_STAGES)
    if part == "correct_validate":
        return list(CORRECT_STAGES)
    return list(FETCH_STAGES) + list(CORRECT_STAGES)


def resolve_backfill_days(missing_count: int) -> int:
    """auto days = missing + 5 buffer, capped at 60; 0 when up-to-date."""
    if missing_count <= 0:
        return 0
    return min(int(missing_count) + BACKFILL_BUFFER, BACKFILL_CAP)


def _get_missing_count(db_manager: Any, today: date) -> int:
    """Best-effort missing-trading-day count (read-only; 0 on any error)."""
    try:
        from reality_engine.pipeline import catchup_scheduler as cs

        missing = cs.get_missing_trading_days(db_manager, today)
        return len(missing or [])
    except Exception as exc:
        logger.debug("missing-day probe failed: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Snapshot + overlap (immediate — eod_scrip_calls has no date-purge)
# ---------------------------------------------------------------------------
def _rows_from_frame(df: Any) -> List[Dict[str, Any]]:
    """Coerce a screener DataFrame (or record list) to plain dict rows."""
    if df is None:
        return []
    if isinstance(df, list):
        return [dict(r) for r in df if isinstance(r, dict)]
    to_dict = getattr(df, "to_dict", None)
    if callable(to_dict):
        try:
            recs = to_dict(orient="records")  # pandas DataFrame
            if isinstance(recs, list):
                return [dict(r) for r in recs]
        except Exception:
            pass
    try:
        return [dict(r) for r in list(df)]
    except Exception:
        return []


def _snapshot_score(row: Dict[str, Any]) -> float:
    for key in ("composite_score", "ensemble_composite", "composite", "score"):
        try:
            val = row.get(key)
            if val is not None:
                return float(val)
        except (TypeError, ValueError):
            continue
    return 0.0


def snapshot_top20(
    df: Any,
    mode: str,
    date_iso: str,
    log_dir: Path,
) -> Path:
    """Write the top-20 snapshot immediately after a screen.

    Filename matches prior manual runs:
    ``screen_{legacy,ensemble}_top20_YYYYMMDD.json``.
    Content: ``{date, mode, count, top20:[{symbol, composite_rank,
    composite_score}]}`` in rank order.
    """
    if mode not in ("legacy", "ensemble"):
        raise ValueError(f"snapshot mode must be legacy|ensemble, got {mode!r}")
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    rows = _rows_from_frame(df)[:20]
    top20: List[Dict[str, Any]] = []
    for i, r in enumerate(rows, start=1):
        sym = str(r.get("symbol") or r.get("nse_symbol") or "").strip().upper()
        if not sym:
            continue
        try:
            rank = int(r.get("composite_rank", i))
        except (TypeError, ValueError):
            rank = i
        top20.append(
            {
                "symbol": sym,
                "composite_rank": rank,
                "composite_score": _snapshot_score(r),
            }
        )
    # Re-rank sequentially so snapshots are canonical even if the frame
    # carried funnel gaps.
    top20.sort(key=lambda e: (e["composite_rank"], e["symbol"]))
    for i, e in enumerate(top20, start=1):
        e["composite_rank"] = i
    path = log_dir / f"screen_{mode}_top20_{compact_date(date_iso)}.json"
    payload = {"date": date_iso, "mode": mode, "count": len(top20), "top20": top20}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    logger.info("snapshot %s top-20 -> %s (%d rows)", mode, path, len(top20))
    return path


def load_snapshot_symbols(path: Path) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [str(e.get("symbol", "")).upper() for e in data.get("top20", []) if e.get("symbol")]


def compute_overlap(
    legacy_symbols: Sequence[str], ensemble_symbols: Sequence[str]
) -> Dict[str, Any]:
    leg = [str(s).upper() for s in legacy_symbols]
    ens = [str(s).upper() for s in ensemble_symbols]
    leg_set, ens_set = set(leg), set(ens)
    overlap = sorted(leg_set & ens_set)
    return {
        "legacy_count": len(leg),
        "ensemble_count": len(ens),
        "overlap_count": len(overlap),
        "overlap": overlap,
        "only_in_legacy": [s for s in leg if s not in ens_set],
        "only_in_ensemble": [s for s in ens if s not in leg_set],
    }


# ---------------------------------------------------------------------------
# Row deltas + checkpoint %
# ---------------------------------------------------------------------------
def _count_rows(db_manager: Any, table: str) -> int:
    try:
        with db_manager.session() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
            if row is None:
                return 0
            try:
                return int(row["c"])
            except (KeyError, TypeError, ValueError):
                return int(row[0])
    except Exception:
        return 0


def snapshot_counts(db_manager: Any) -> Dict[str, int]:
    if db_manager is None:
        return {t: 0 for t in DELTA_TABLES}
    return {t: _count_rows(db_manager, t) for t in DELTA_TABLES}


def diff_counts(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for t in DELTA_TABLES:
        b = int(before.get(t, 0))
        a = int(after.get(t, 0))
        out[t] = {"before": b, "after": a, "delta": a - b}
    return out


def checkpoint_pct(summary: Dict[str, Any]) -> Dict[str, float]:
    try:
        target = int(summary.get("target_universe_count") or 0) or 1
        tech = int(summary.get("technical_data_complete_count") or 0)
        funda = int(summary.get("fundamental_data_complete_count") or 0)
        return {
            "technical_pct": round(tech / target * 100.0, 2),
            "fundamental_pct": round(funda / target * 100.0, 2),
        }
    except Exception:
        return {"technical_pct": 0.0, "fundamental_pct": 0.0}


# ---------------------------------------------------------------------------
# Lazy singletons (only materialised for stages that actually run)
# ---------------------------------------------------------------------------
def _default_db():
    from reality_engine.db.database import db_manager

    return db_manager


def _resolve_target_date(db_manager: Any, date_iso: str) -> str:
    """Latest price date when available (closed session), else the run date."""
    try:
        if db_manager is not None:
            from reality_engine.db.repository import Repository

            latest = Repository(db_manager).get_latest_price_delivery_date()
        else:
            from reality_engine.db.repository import repo

            latest = repo.get_latest_price_delivery_date()
        if latest:
            return str(latest)[:10]
    except Exception as exc:
        logger.debug("latest-date probe failed: %s", exc)
    return date_iso


def _rename_alpha_outputs(exported: Dict[str, Any], mode: str) -> Dict[str, str]:
    """Rename ReportWriter outputs immediately to avoid collision.

    ``export_daily_alpha_report`` always writes ``daily_alpha.{json,md,html}``;
    the second mode would overwrite the first unless renamed at once.
    Produces ``daily_alpha_{mode}.{json,md,html}`` siblings in the same dir.
    """
    renamed: Dict[str, str] = {}
    for key, ext in (("json", ".json"), ("markdown", ".md"), ("html", ".html")):
        src = exported.get(key)
        if not src:
            continue
        src_p = Path(str(src))
        dst_p = src_p.parent / f"daily_alpha_{mode}{ext}"
        try:
            if dst_p.exists() and dst_p != src_p:
                dst_p.unlink()
            if src_p.exists():
                src_p.rename(dst_p)
                renamed[key] = str(dst_p)
            else:
                renamed[key] = str(src_p)
        except Exception as exc:
            logger.warning("alpha rename %s -> %s failed: %s", src_p, dst_p, exc)
            renamed[key] = str(src_p)
    return renamed


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------
def run_nightly(
    dry_run: bool = False,
    part: str = "all",
    date_str: Optional[str] = None,
    universe: str = "nifty200",
    top_n: int = 20,
    # Injected dependencies (temp DBs + fakes in tests; live singletons otherwise)
    db_manager: Any = None,
    master_sync_mgr: Any = None,
    backfill_mgr: Any = None,
    phase1_runner_obj: Any = None,
    fundamentals_client_obj: Any = None,
    screener: Any = None,
    orchestrator: Any = None,
    report_writer: Any = None,
    eod_corrector_obj: Any = None,
    log_dir: Optional[Path] = None,
    lock_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the Wave A nightly chain and return a JSON-serialisable summary.

    ``exit_code``: 0 all executed stages ok/skipped; 1 any stage failed or
    the checkpoint gate aborted predict; 2 lock contention.
    """
    if part not in VALID_PARTS:
        raise ValueError(f"part must be one of {VALID_PARTS}, got {part!r}")
    date_iso = today_ist_str(date_str)
    today = date.fromisoformat(date_iso)
    base_log = Path(log_dir) if log_dir is not None else default_log_dir()
    base_log.mkdir(parents=True, exist_ok=True)
    lock_p = Path(lock_path) if lock_path is not None else (base_log / LOCK_NAME)
    planned = plan_stages(part)

    # ---- Dry-run: plan only, zero DB/network writes (no lock, no files) ----
    if dry_run:
        missing_n = 0
        if db_manager is not None:
            # Read-only probe so the plan quotes a real backfill size.
            missing_n = _get_missing_count(db_manager, today)
        plan = {
            "dry_run": True,
            "part": part,
            "date_ist": date_iso,
            "planned_stages": planned,
            "backfill_days_planned": resolve_backfill_days(missing_n),
            "missing_trading_days": missing_n,
            "universe_eod": universe,
            "screen_universe": "all",
            "top_n": top_n,
            "exit_code": 0,
        }
        print(json.dumps(plan, indent=2))
        return plan

    # ---- Overlap protection ----
    try:
        lock_fd = acquire_lock(lock_p)
    except RuntimeError as exc:
        summary = {
            "dry_run": False,
            "part": part,
            "date_ist": date_iso,
            "planned_stages": planned,
            "stages": {},
            "error": str(exc),
            "exit_code": 2,
        }
        print(json.dumps(summary, indent=2))
        logger.error("nightly lock contention: %s", exc)
        return summary

    stages: Dict[str, Any] = {}
    legacy_symbols: List[str] = []
    ensemble_symbols: List[str] = []
    snapshot_files: Dict[str, str] = {}
    alpha_files: Dict[str, Any] = {}
    checkpoint_summary: Dict[str, Any] = {}
    overlap: Dict[str, Any] = {
        "legacy_count": 0,
        "ensemble_count": 0,
        "overlap_count": 0,
        "overlap": [],
        "only_in_legacy": [],
        "only_in_ensemble": [],
    }
    exit_code = 0

    def _mark_failed(name: str, exc: BaseException) -> None:
        stages[name] = {"status": "failed", "error": str(exc)}

    try:
        db = db_manager or _default_db()
        do_fetch = part in ("fetch_predict", "all")
        do_correct = part in ("correct_validate", "all")
        counts_before = snapshot_counts(db) if do_fetch else {t: 0 for t in DELTA_TABLES}
        target_date = _resolve_target_date(db, date_iso)

        # ================= fetch_predict =================
        if do_fetch:
            # (1a) master sync
            try:
                mgr = master_sync_mgr
                if mgr is None:
                    from reality_engine.ingestion.master_sync import master_sync as mgr
                res = mgr.sync_all()
                stages["master_sync"] = {"status": "ok", "result": res}
            except Exception as exc:
                _mark_failed("master_sync", exc)

            # (1b) backfill gap (auto = missing + 5, cap 60)
            try:
                bm = backfill_mgr
                if bm is None:
                    from reality_engine.pipeline.backfill import backfill_manager as bm
                try:
                    from reality_engine.pipeline import catchup_scheduler as cs

                    missing = cs.get_missing_trading_days(db, today) or []
                except Exception:
                    missing = []
                days = resolve_backfill_days(len(missing))
                if days <= 0:
                    stages["backfill"] = {
                        "status": "skipped",
                        "reason": "no missing trading days",
                        "missing": missing,
                    }
                else:
                    end_dt = datetime(today.year, today.month, today.day, tzinfo=IST)
                    inserted = bm.backfill_bhavcopy_history(days_count=days, end_date=end_dt)
                    stages["backfill"] = {
                        "status": "ok",
                        "missing": missing,
                        "days_requested": days,
                        "sessions_ingested": int(inserted or 0),
                    }
                    # Re-resolve the closed-session anchor after new rows land.
                    target_date = _resolve_target_date(db, date_iso)
            except Exception as exc:
                _mark_failed("backfill", exc)

            # (1c) fundamentals refresh top-200 (reuse helpers, never refetch inline)
            try:
                pr = phase1_runner_obj
                if pr is None:
                    from reality_engine.pipeline.phase1_runner import phase1_runner as pr
                repo_obj = getattr(pr, "repo", None)
                if repo_obj is None:
                    from reality_engine.db.repository import repo as repo_obj
                companies: List[Dict[str, Any]] = []
                try:
                    companies = repo_obj.get_nifty200_companies() or []
                except Exception:
                    companies = []
                if not companies:
                    try:
                        companies = repo_obj.get_all_companies(active_only=True)[:200]
                    except Exception:
                        companies = []
                else:
                    companies = companies[:200]
                fc = fundamentals_client_obj
                if fc is None:
                    from reality_engine.ingestion.fundamentals_client import (
                        fundamentals_client as fc,
                    )
                res = fc.fetch_all_fundamentals(
                    companies,
                    max_workers=4,
                    rate_limit_sec=0.5,
                    max_companies=200,
                    persist=True,
                )
                keep = {k: v for k, v in (res or {}).items() if k != "failed_symbols"}
                stages["fundamentals"] = {
                    "status": "ok",
                    "universe": "nifty200",
                    "attempted": (res or {}).get("attempted", len(companies)),
                    "result": keep,
                }
            except Exception as exc:
                _mark_failed("fundamentals", exc)

            # (1d) verify-checkpoint gate
            checkpoint_ok = False
            try:
                pr = phase1_runner_obj
                if pr is None:
                    from reality_engine.pipeline.phase1_runner import phase1_runner as pr
                summary = pr.validate_top_200_checkpoint() or {}
                checkpoint_summary = dict(summary)
                checkpoint_ok = bool(summary.get("checkpoint_passed"))
                stages["checkpoint"] = {
                    "status": "ok" if checkpoint_ok else "failed",
                    "checkpoint_passed": checkpoint_ok,
                    "summary": {k: v for k, v in summary.items() if not k.startswith("exported")},
                }
                if not checkpoint_ok:
                    exit_code = 1
            except Exception as exc:
                _mark_failed("checkpoint", exc)

            if not checkpoint_ok:
                # ABORT predict stages (screens + alphas) on gate failure.
                for name in (
                    "screen_legacy",
                    "screen_ensemble",
                    "daily_alpha_ensemble",
                    "daily_alpha_legacy",
                ):
                    stages[name] = {"status": "aborted", "reason": "checkpoint gate failed"}
                exit_code = 1
            else:
                # Fresh anchor for screens (closed session).
                target_date = _resolve_target_date(db, date_iso)
                scr = screener
                if scr is None:
                    from reality_engine.processing.composite_screener import (
                        composite_screener as scr,
                    )
                # (2a) legacy screen full-universe top-20 + immediate snapshot
                try:
                    df_leg = scr.run_screener(
                        target_date=target_date, top_n=top_n, universe="all"
                    )
                    snap = snapshot_top20(df_leg, "legacy", date_iso, base_log)
                    snapshot_files["legacy"] = str(snap)
                    legacy_symbols = load_snapshot_symbols(snap)
                    stages["screen_legacy"] = {
                        "status": "ok",
                        "universe": "all",
                        "top_n": top_n,
                        "target_date": target_date,
                        "snapshot": str(snap),
                        "count": len(legacy_symbols),
                    }
                except Exception as exc:
                    _mark_failed("screen_legacy", exc)
                # (2b) ensemble screen same universe + immediate snapshot
                try:
                    df_ens = scr.ensemble_screen(
                        target_date=target_date, top_n=top_n, universe="all"
                    )
                    snap = snapshot_top20(df_ens, "ensemble", date_iso, base_log)
                    snapshot_files["ensemble"] = str(snap)
                    ensemble_symbols = load_snapshot_symbols(snap)
                    stages["screen_ensemble"] = {
                        "status": "ok",
                        "universe": "all",
                        "top_n": top_n,
                        "target_date": target_date,
                        "snapshot": str(snap),
                        "count": len(ensemble_symbols),
                    }
                except Exception as exc:
                    _mark_failed("screen_ensemble", exc)

                if legacy_symbols or ensemble_symbols:
                    overlap = compute_overlap(legacy_symbols, ensemble_symbols)

                # (2c) run-daily-alpha both modes, rename immediately per mode
                try:
                    orch = orchestrator
                    if orch is None:
                        from reality_engine.agent.orchestrator import AgentOrchestrator

                        orch = AgentOrchestrator()
                    wr = report_writer
                    if wr is None:
                        from reality_engine.reporting.writer import ReportWriter

                        wr = ReportWriter()
                    rep_ens = orch.synthesize_daily_alpha_report(
                        target_date=target_date,
                        universe="nifty200",
                        top_n=5,
                        screener_pool_size=top_n,
                        use_ensemble=True,
                    )
                    exp_ens = wr.export_daily_alpha_report(rep_ens)
                    alpha_files["ensemble"] = _rename_alpha_outputs(exp_ens, "ensemble")
                    stages["daily_alpha_ensemble"] = {
                        "status": "ok",
                        "mode": "ensemble",
                        "target_date": target_date,
                        "files": alpha_files["ensemble"],
                    }
                except Exception as exc:
                    _mark_failed("daily_alpha_ensemble", exc)
                try:
                    orch = orchestrator
                    if orch is None:
                        from reality_engine.agent.orchestrator import AgentOrchestrator

                        orch = AgentOrchestrator()
                    wr = report_writer
                    if wr is None:
                        from reality_engine.reporting.writer import ReportWriter

                        wr = ReportWriter()
                    # Re-resolve: the ensemble export was renamed away, so the
                    # legacy export lands on fresh daily_alpha.* paths.
                    rep_leg = orch.synthesize_daily_alpha_report(
                        target_date=target_date,
                        universe="nifty200",
                        top_n=5,
                        screener_pool_size=top_n,
                        use_ensemble=False,
                    )
                    exp_leg = wr.export_daily_alpha_report(rep_leg)
                    alpha_files["legacy"] = _rename_alpha_outputs(exp_leg, "legacy")
                    stages["daily_alpha_legacy"] = {
                        "status": "ok",
                        "mode": "legacy",
                        "target_date": target_date,
                        "files": alpha_files["legacy"],
                    }
                except Exception as exc:
                    _mark_failed("daily_alpha_legacy", exc)
        else:
            for name in FETCH_STAGES:
                stages[name] = {"status": "skipped", "reason": f"part={part}"}

        # ================= correct_validate =================
        if do_correct:
            try:
                ec = eod_corrector_obj
                if ec is None:
                    from reality_engine.processing.eod_corrector import EODCorrector

                    ec = EODCorrector(db)
                # Closed-session anchor: latest price date carries rows by
                # definition, so the corrector's guard stays intact.
                eod_date = _resolve_target_date(db, date_iso)
                res = ec.correct_eod(universe=universe, target_date=eod_date, dry_run=False)
                stages["eod_correct"] = {
                    "status": "ok",
                    "universe": universe,
                    "target_date": eod_date,
                    "symbols_corrected": (res or {}).get("symbols_corrected", 0),
                    "result": res,
                }
            except Exception as exc:
                # Guard intact: intraday/missing dates raise ValueError here
                # and surface as a failed stage (non-zero exit), never silent.
                _mark_failed("eod_correct", exc)
        else:
            stages["eod_correct"] = {"status": "skipped", "reason": f"part={part}"}

        counts_after = snapshot_counts(db) if do_fetch else dict(counts_before)
        row_deltas = diff_counts(counts_before, counts_after)
        cpct = checkpoint_pct(checkpoint_summary) if checkpoint_summary else {
            "technical_pct": 0.0,
            "fundamental_pct": 0.0,
        }

        if any((stages.get(n) or {}).get("status") == "failed" for n in planned):
            exit_code = 1

        summary = {
            "dry_run": False,
            "part": part,
            "date_ist": date_iso,
            "target_date": target_date if do_fetch else None,
            "stages": stages,
            "row_deltas": row_deltas,
            "checkpoint": {
                "passed": bool(checkpoint_summary.get("checkpoint_passed")) if checkpoint_summary else None,
                **cpct,
                "summary": checkpoint_summary,
            },
            "top20_overlap": overlap,
            "snapshot_files": snapshot_files,
            "alpha_files": alpha_files,
            "exit_code": exit_code,
        }
        health_path = base_log / f"nightly_{date_iso}.json"
        try:
            with open(health_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, default=str)
            summary["health_file"] = str(health_path)
        except Exception as exc:
            logger.warning("health summary write failed: %s", exc)
        print(json.dumps(summary, indent=2, default=str))
        return summary
    finally:
        release_lock(lock_fd, lock_p)


# ---------------------------------------------------------------------------
# Module CLI (mirrors cli.py nightly wiring)
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Wave A unattended nightly chain: fetch -> predict -> correct."
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan stages, zero DB/network writes.")
    parser.add_argument(
        "--part",
        choices=list(VALID_PARTS),
        default="all",
        help="Split work across slots: fetch_predict (19:45) | correct_validate (23:00) | all (default: all)",
    )
    parser.add_argument("--date", default=None, help="Override IST run date YYYY-MM-DD.")
    parser.add_argument("--universe", default="nifty200", help="EOD correction universe (default: nifty200). Screens always run full-universe.")
    parser.add_argument("--top", type=int, default=20, help="Top N for both screens (default: 20).")
    args = parser.parse_args(argv)
    summary = run_nightly(
        dry_run=args.dry_run,
        part=args.part,
        date_str=args.date,
        universe=args.universe,
        top_n=args.top,
    )
    return int(summary.get("exit_code", 0))


if __name__ == "__main__":
    sys.exit(main())
