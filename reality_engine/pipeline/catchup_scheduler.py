"""
Missed-Days Catcher + Twice-Daily Scheduler
============================================

Catches up missing trading days (and macro sources) whenever the computer was
off, and runs the nightly improvement loop (prune -> distill -> EOD correction
-> event correction) idempotently at fixed IST times (04:00 pre-close check and
23:00 post-close full run).

Design rules honoured
---------------------
* Owns ONLY this file (plus nightly_runner.py and the .kilo scripts). It reads
  the peer processing modules (backfill, distillation, pruning, eod_corrector)
  through their existing public entry points and injects them for testing -- it
  never edits them.
* IST timezone handled with stdlib ``datetime.timezone(timedelta(hours=5,
  minutes=30))`` (no pytz dependency). All date maths compare against IST.
* Idempotent: the script can be invoked at 16:00 and 23:00; each run only acts
  on gaps that actually exist. Re-running the same day is a no-op for already
  loaded data (INSERT OR REPLACE everywhere downstream).
* Graceful offline handling: if the computer was off for N trading days, every
  one of those days is backfilled AND corrected sequentially (not just the
  latest).
* 16:00 pre-close guard: when invoked in pre-close mode (the 16:00 IST window)
  the catcher fetches the morning aux feeds + runs pruning, but SKIPS EOD
  correction for *today* unless today's bhavcopy has already landed (market
  still open / file not yet published).

Run:
    python -m reality_engine.pipeline.catchup_scheduler [--dry-run] [--check-only]
           [--mode pre-close|post-close|auto]

    --check-only : only compute + print missing trading days and macro sources.
    --dry-run    : report what would happen without mutating raw price data
                   (skips network backfill + macro distillation; still previews
                   pruning and EOD correction in dry-run mode).
    --mode       : override the auto-derived run mode (pre-close | post-close).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

# Project root importable when run as a plain script.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from reality_engine import config  # noqa: E402  (creates data dirs, safe)

logger = logging.getLogger("reality_engine.catchup")

# ---------------------------------------------------------------------------
# IST timezone helpers
# ---------------------------------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))

# Macro source_type prefixes tracked by get_missing_macro_sources (mirrors
# repository.list_macro_raw_documents macro_prefixes).
MACRO_SOURCE_PREFIXES: Sequence[str] = (
    "union_budget",
    "state_budget",
    "economic_survey",
    "pib",
    "rbi",
)

# Known NSE holiday table names (checked at runtime; ignored if absent).
_HOLIDAY_TABLE_CANDIDATES = ("nse_holidays", "trading_holidays", "market_holidays")

# Safety cap so a pathological multi-month outage cannot loop forever.
MAX_CATCHUP_CALENDAR_DAYS = 180

# 16:00 IST pre-close window: only skip TODAY's EOD when its bhavcopy is absent.
# We treat the scheduled 16:00 run as pre-close; 23:00 as post-close.
PRE_CLOSE_HOUR_MIN = 9    # 09:00 IST
PRE_CLOSE_HOUR_MAX = 17   # 17:00 IST (covers the 16:00 scheduled slot)


def now_ist() -> datetime:
    """Return the current wall-clock time in IST (tz-aware)."""
    return datetime.now(IST)


def _default_db():
    from reality_engine.db.database import db_manager
    return db_manager


def is_trading_day(d: date, holidays: Optional[Set[str]] = None) -> bool:
    """Mon-Fri and not in the (optional) NSE holiday set."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if holidays and d.isoformat() in holidays:
        return False
    return True


def _load_holidays(db_manager) -> Set[str]:
    """Return the set of holiday YYYY-MM-DD strings if a holiday table exists."""
    try:
        with db_manager.session() as conn:
            for tbl in _HOLIDAY_TABLE_CANDIDATES:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (tbl,),
                ).fetchone()
                if row:
                    cur = conn.execute(f"SELECT date FROM {tbl}")  # date / holiday_date col
                    out: Set[str] = set()
                    for r in cur.fetchall():
                        val = r[0]
                        if val:
                            out.add(str(val)[:10])
                    return out
    except Exception:
        pass
    return set()


# ---------------------------------------------------------------------------
# 1. Missing trading days
# ---------------------------------------------------------------------------
def get_missing_trading_days(
    db_manager: Any = None,
    today: Optional[date] = None,
    holidays: Optional[Set[str]] = None,
) -> List[str]:
    """Return missing trading-day YYYY-MM-DD strings since the last loaded price date.

    Gap is computed as every Mon-Fri (minus NSE holidays) strictly after the
    MAX(date) in ``daily_price_delivery`` up to and including ``today`` (IST).
    A fresh/empty DB returns [] (nothing to compare against -- use run-phase1).
    """
    db = db_manager or _default_db()
    today = today or now_ist().date()
    if holidays is None:
        holidays = _load_holidays(db)

    with db.session() as conn:
        row = conn.execute("SELECT MAX(date) FROM daily_price_delivery").fetchone()
        last = row[0] if row else None
    if not last:
        return []

    last_d = date.fromisoformat(str(last)[:10])
    start = last_d + timedelta(days=1)

    # Bound the scan to avoid runaway on a multi-month outage.
    end = today
    if (end - start).days > MAX_CATCHUP_CALENDAR_DAYS:
        start = end - timedelta(days=MAX_CATCHUP_CALENDAR_DAYS)

    missing: List[str] = []
    cur = start
    while cur <= end:
        if is_trading_day(cur, holidays):
            missing.append(cur.isoformat())
        cur += timedelta(days=1)
    return missing


# ---------------------------------------------------------------------------
# 2. Missing macro sources (24h window)
# ---------------------------------------------------------------------------
def get_missing_macro_sources(
    db_manager: Any = None,
    now: Optional[datetime] = None,
    window_hours: float = 24.0,
) -> List[str]:
    """Return macro source_type prefixes not ingested within the last ``window_hours``."""
    db = db_manager or _default_db()
    now = now or now_ist()
    missing: List[str] = []
    with db.session() as conn:
        for prefix in MACRO_SOURCE_PREFIXES:
            row = conn.execute(
                "SELECT MAX(published_date) AS m FROM raw_documents "
                "WHERE LOWER(source_type) LIKE ?",
                (f"{prefix}%",),
            ).fetchone()
            last = row["m"] if row else None
            if not last:
                missing.append(prefix)
                continue
            try:
                last_d = date.fromisoformat(str(last)[:10])
            except Exception:
                missing.append(prefix)
                continue
            # Treat last ingest as midnight IST that day.
            last_dt = datetime(last_d.year, last_d.month, last_d.day, tzinfo=IST)
            age_hours = (now - last_dt).total_seconds() / 3600.0
            if age_hours > window_hours:
                missing.append(prefix)
    return missing


# ---------------------------------------------------------------------------
# 3. Run-mode resolution + 16:00 pre-close guard
# ---------------------------------------------------------------------------
def resolve_mode(mode: str, now: Optional[datetime] = None) -> str:
    """Resolve the effective run mode.

    auto -> 'pre_close' during the 09:00-17:00 IST window (covers the 16:00
    scheduled slot), else 'post_close' (covers the 23:00 slot and overnight).
    """
    if mode in ("pre-close", "post-close"):
        return mode
    now = now or now_ist()
    if PRE_CLOSE_HOUR_MIN <= now.hour <= PRE_CLOSE_HOUR_MAX:
        return "pre-close"
    return "post-close"


def should_skip_eod_for_date(
    date_str: str,
    mode: str,
    today_str: str,
    has_data: bool,
) -> bool:
    """Pre-close guard: skip TODAY's EOD correction if its bhavcopy isn't ready.

    * post-close mode never skips (full run, today should be loaded).
    * pre-close mode skips today's EOD only when today's price data is absent
      (i.e. the market bhavcopy has not yet been published).
    """
    if mode != "pre-close":
        return False
    if date_str != today_str:
        return False
    return not has_data


def _has_price_data(db_manager, date_str: str) -> bool:
    try:
        with db_manager.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM daily_price_delivery WHERE date = ?",
                (date_str,),
            ).fetchone()
            return bool(row and row["c"])
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 4. Pipeline stages (each best-effort, never fatal)
# ---------------------------------------------------------------------------
def _run_backfill(backfill_manager, missing: List[str], today: date, logger) -> Dict[str, Any]:
    if not missing:
        return {"requested": 0, "note": "no missing trading days"}
    # Backfill the most recent (len(missing)+5) trading sessions ending today,
    # which safely covers every missing day plus a small buffer for partial loads.
    days_count = len(missing) + 5
    try:
        end_date = datetime(today.year, today.month, today.day, tzinfo=IST)
        inserted = backfill_manager.backfill_bhavcopy_history(
            days_count=days_count, end_date=end_date
        )
        return {"requested": days_count, "sessions_ingested": int(inserted or 0)}
    except Exception as exc:  # network/offline -> log, do not crash the catcher
        logger.warning("backfill failed (offline?): %s", exc)
        return {"requested": days_count, "error": str(exc)}


def _run_distillation(distillation_engine, logger) -> Dict[str, Any]:
    try:
        res = distillation_engine.distill_all_macro_documents()
        details = res.get("details", []) if isinstance(res, dict) else []
        events = [
            d.get("event_id")
            for d in details
            if d.get("event_id") and d.get("events_created", 0) > 0
        ]
        return {
            "distilled": res.get("distilled", 0) if isinstance(res, dict) else 0,
            "event_ids": events,
        }
    except Exception as exc:
        logger.warning("macro distillation failed: %s", exc)
        return {"distilled": 0, "event_ids": [], "error": str(exc)}


def _maybe_run_monthly_distillation(
    manager, distillation_pruner, dry_run: bool, logger
) -> Dict[str, Any]:
    """Run the 20+4 -> moat -> purge24 distillation only when >=24 candidates exist."""
    if dry_run:
        return {"ran": False, "skipped": True, "reason": "dry_run"}
    try:
        with manager.session() as conn:
            cnt = conn.execute(
                """
                SELECT COUNT(*) AS c FROM document_chunks dc
                JOIN raw_documents rd ON dc.doc_id = rd.doc_id
                WHERE dc.embedding IS NOT NULL
                  AND (LOWER(COALESCE(rd.source_type,'')) LIKE '%youtube%'
                       OR LOWER(COALESCE(rd.source_type,'')) LIKE '%analyst%'
                       OR LOWER(COALESCE(rd.source_type,'')) LIKE '%concall%'
                       OR LOWER(COALESCE(rd.source_type,'')) LIKE '%mpc%'
                       OR LOWER(COALESCE(rd.source_type,'')) LIKE '%earnings%'
                       OR LOWER(COALESCE(rd.source_type,'')) LIKE '%transcript%')
                  AND COALESCE(rd.is_structural_milestone,0) <> 1
                  AND COALESCE(rd.source_type,'') NOT LIKE '%Structural Milestone%'
                """
            ).fetchone()["c"]
        if cnt < 24:
            return {"ran": False, "candidates": int(cnt), "reason": "fewer than 24 (20+4) candidates"}
        # Pick the symbol with the most embedded candidates as the distill target.
        symbol = None
        try:
            with manager.session() as conn:
                has_sym = any(
                    c[1] == "symbol"
                    for c in conn.execute("PRAGMA table_info('document_chunks')").fetchall()
                )
                if has_sym:
                    row = conn.execute(
                        """
                        SELECT dc.symbol AS sym, COUNT(*) c FROM document_chunks dc
                        JOIN raw_documents rd ON dc.doc_id = rd.doc_id
                        WHERE dc.embedding IS NOT NULL
                          AND (LOWER(COALESCE(rd.source_type,'')) LIKE '%youtube%'
                               OR LOWER(COALESCE(rd.source_type,'')) LIKE '%concall%')
                          AND COALESCE(rd.is_structural_milestone,0) <> 1
                        GROUP BY dc.symbol ORDER BY c DESC LIMIT 1
                        """
                    ).fetchone()
                    if row and row["sym"]:
                        symbol = str(row["sym"])
        except Exception:
            symbol = None
        if not symbol:
            symbol = "HAL"  # canonical default per run_moe_eod EOD_UNIVERSE
        res = distillation_pruner.run_monthly_distillation(symbol)
        return {"ran": True, "symbol": symbol, "result": res}
    except Exception as exc:
        logger.warning("monthly distillation skipped: %s", exc)
        return {"ran": False, "error": str(exc)}


def _run_pruning(pruning_engine, distillation_pruner, manager, dry_run: bool, logger) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        prune = pruning_engine.prune_decayed_signals(dry_run=dry_run)
        out["prune_decayed_signals"] = prune
    except Exception as exc:
        logger.warning("prune_decayed_signals failed: %s", exc)
        out["prune_decayed_signals"] = {"error": str(exc)}
    out["monthly_distillation"] = _maybe_run_monthly_distillation(
        manager, distillation_pruner, dry_run, logger
    )
    return out


def _run_eod_corrections(
    eod_corrector, manager, missing: List[str], mode: str, today_str: str,
    universe: str, dry_run: bool, logger,
) -> List[Dict[str, Any]]:
    """Sequentially correct EOD for every missing trading day that has data."""
    results: List[Dict[str, Any]] = []
    for d in missing:
        has = _has_price_data(manager, d)
        if should_skip_eod_for_date(d, mode, today_str, has):
            logger.info("[eod] pre-close guard: skipping today's EOD (no bhavcopy yet) %s", d)
            results.append({"date": d, "skipped": True, "reason": "pre_close_no_data"})
            continue
        if not has:
            logger.info("[eod] no price data for %s (skipped)", d)
            results.append({"date": d, "skipped": True, "reason": "no_data"})
            continue
        try:
            r = eod_corrector.correct_eod(
                universe=universe, target_date=d, dry_run=dry_run
            )
            results.append({
                "date": d,
                "symbols_corrected": r.get("symbols_corrected", 0),
                "noise_floors_updated": r.get("noise_floors_updated", 0),
                "lens_rank_changes": r.get("lens_rank_changes", 0),
            })
        except Exception as exc:
            logger.warning("[eod] correction failed for %s: %s", d, exc)
            results.append({"date": d, "error": str(exc)})
    return results


def _run_event_corrections(eod_corrector, event_ids: List[str], dry_run: bool, logger) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for ev in event_ids:
        try:
            r = eod_corrector.correct_event(ev, dry_run=dry_run)
            results.append({"event_id": ev, "lens_rank_changes": r.get("lens_rank_changes", 0)})
        except Exception as exc:
            logger.warning("[event] correction failed for %s: %s", ev, exc)
            results.append({"event_id": ev, "error": str(exc)})
    return results


def _fetch_aux_feeds(manager, mode: str, dry_run: bool, logger) -> Dict[str, Any]:
    """Best-effort morning aux-feed fetch (Vahan/MF/RBI/PIB) for the pre-close check.

    Only runs in non-dry mode. Failures are logged and never fatal.
    """
    if dry_run:
        return {"skipped": True, "reason": "dry_run"}
    try:
        from reality_engine.ingestion import headless_fetcher  # type: ignore
        # Only call a module-level convenience entrypoint if it exists; never
        # auto-instantiate a browser-launching class (keeps runs/tests cheap).
        fetcher_fn = getattr(headless_fetcher, "fetch_headless_feeds", None) \
            or getattr(headless_fetcher, "fetch_all", None)
        if callable(fetcher_fn):
            fetcher_fn()
            return {"fetched": True}
        return {"fetched": False, "reason": "no_fetcher_entrypoint"}
    except Exception as exc:
        logger.info("[aux] aux feed fetch skipped: %s", exc)
        return {"fetched": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# 5. Top-level catchup orchestrator
# ---------------------------------------------------------------------------
def run_catchup(
    dry_run: bool = False,
    mode: str = "auto",
    today: Optional[date] = None,
    universe: str = "nifty200",
    # Injected dependencies (real singletons by default) -- enables deterministic tests.
    db_manager: Any = None,
    backfill_manager: Any = None,
    distillation_engine: Any = None,
    pruning_engine: Any = None,
    distillation_pruner: Any = None,
    eod_corrector: Any = None,
) -> Dict[str, Any]:
    """Detect gaps and run the full catch-up + nightly improvement loop.

    Returns a JSON-serialisable summary dict (also printed/logged by the caller).
    """
    db = db_manager or _default_db()
    now = now_ist() if today is None else datetime(today.year, today.month, today.day, tzinfo=IST)
    today = today or now.date()
    today_str = today.isoformat()
    mode = resolve_mode(mode, now)

    missing_days = get_missing_trading_days(db, today)
    missing_macro = get_missing_macro_sources(db, now)

    summary: Dict[str, Any] = {
        "dry_run": bool(dry_run),
        "mode": mode,
        "today_ist": today_str,
        "missing_trading_days": missing_days,
        "missing_trading_day_count": len(missing_days),
        "missing_macro_sources": missing_macro,
        "actions": {},
    }

    # ---- Aux feeds (always attempt in non-dry; powers the 16:00 pre-close check) ----
    summary["actions"]["aux_feeds"] = _fetch_aux_feeds(db, mode, dry_run, logger)

    # ---- Price backfill (network; skipped in dry-run) ----
    if dry_run:
        summary["actions"]["backfill"] = {"skipped": True, "reason": "dry_run",
                                          "would_request_days": (len(missing_days) + 5) if missing_days else 0}
    else:
        bm = backfill_manager
        if bm is None:
            from reality_engine.pipeline.backfill import backfill_manager as bm  # noqa: F811
        summary["actions"]["backfill"] = _run_backfill(bm, missing_days, today, logger)

    # ---- Macro distillation (network; skipped in dry-run) ----
    if dry_run:
        summary["actions"]["distillation"] = {"skipped": True, "reason": "dry_run"}
    else:
        de = distillation_engine
        if de is None:
            from reality_engine.processing.distillation_engine import distillation_engine as de  # noqa: F811
        summary["actions"]["distillation"] = _run_distillation(de, logger)

    # ---- Pruning (dry-run safe) ----
    pe = pruning_engine
    dp = distillation_pruner
    if pe is None:
        from reality_engine.processing import pruning_engine as pe  # noqa: F811
    if dp is None:
        from reality_engine.processing import distillation_pruner as dp  # noqa: F811
    summary["actions"]["pruning"] = _run_pruning(pe, dp, db, dry_run, logger)

    # ---- EOD correction for each missing trading day (sequential) ----
    ec = eod_corrector
    if ec is None:
        from reality_engine.processing.eod_corrector import EODCorrector
        ec = EODCorrector(db)
    event_ids = []
    if not dry_run and summary["actions"].get("distillation", {}).get("event_ids"):
        event_ids = summary["actions"]["distillation"]["event_ids"]
    summary["actions"]["eod_corrections"] = _run_eod_corrections(
        ec, db, missing_days, mode, today_str, universe, dry_run, logger
    )

    # ---- Event correction for macro_events created in the catch-up window ----
    summary["actions"]["event_corrections"] = _run_event_corrections(
        ec, event_ids, dry_run, logger
    )

    return summary


# ---------------------------------------------------------------------------
# 6. Logging + CLI
# ---------------------------------------------------------------------------
def _setup_logging(today_str: str) -> Path:
    log_dir = config.DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"catchup_{today_str}.log"
    root = logging.getLogger("reality_engine")
    root.setLevel(logging.INFO)
    # Avoid duplicate handlers on repeated calls.
    if not any(getattr(h, "baseFilename", "").endswith(log_path.name) for h in root.handlers):
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(fh)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               and getattr(h, "stream", None) in (sys.stdout, None) for h in root.handlers):
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(sh)
    return log_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reality Engine missed-days catcher + twice-daily scheduler runner."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without mutating raw data.")
    parser.add_argument("--check-only", action="store_true",
                        help="Only report missing trading days + macro sources, then exit.")
    parser.add_argument("--mode", choices=["auto", "pre-close", "post-close"], default="auto",
                        help="Override run mode (default: auto from IST hour).")
    parser.add_argument("--today", default=None,
                        help="Override 'today' (YYYY-MM-DD) for testing/dry runs.")
    parser.add_argument("--universe", default="nifty200", help="EOD correction universe.")
    args = parser.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else None
    today_str = (today or now_ist().date()).isoformat()
    log_path = _setup_logging(today_str)

    if args.check_only:
        db = _default_db()
        missing_days = get_missing_trading_days(db, today)
        missing_macro = get_missing_macro_sources(db, (now_ist() if today is None else datetime(today.year, today.month, today.day, tzinfo=IST)))
        report = {
            "today_ist": today_str,
            "mode": resolve_mode(args.mode),
            "missing_trading_days": missing_days,
            "missing_trading_day_count": len(missing_days),
            "missing_macro_sources": missing_macro,
        }
        print(json.dumps(report, indent=2))
        logger.info("check-only report: %s", json.dumps(report))
        print(f"[catchup] log: {log_path}")
        return 0

    summary = run_catchup(
        dry_run=args.dry_run,
        mode=args.mode,
        today=today,
        universe=args.universe,
    )
    print(json.dumps(summary, indent=2, default=str))
    logger.info("catchup summary: %s", json.dumps(summary, default=str))
    print(f"[catchup] log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
