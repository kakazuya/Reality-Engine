"""Seed the audited portfolio track record from existing history.

Reads the last M closed EOD dates with move-attribution coverage (the join
of ``move_attribution`` x ``daily_price_delivery`` dates, never wall-clock),
takes up to N material (``is_material=1``) rows per date, resolves each
through the orchestrator's ``_resolve_thesis_action`` path (the same resolver
the theses use, with a ``funda`` dict built from the ``eod_scrip_calls`` row),
and records every resolved BUY/SELL/HOLD via
``portfolio_ledger.record_action`` (HOLDs keep the denominator honest).

Entry price is the NEXT-session close when usable, else the call row's
``current_market_price``; target/stop are vol-scaled trailing-sigma brackets
(``portfolio_ledger.vol_scaled_bracket`` at the entry, SELL mirrored) — the
call row's fixed 18/6 terms are never used, so seeded SELL rows always
satisfy the framing invariant. Pairs with no call row, no usable entry, or
resolver exceptions are skipped (logged + counted, never fatal).

Scope: Nifty-50 test ground (``master_companies.is_nifty50 = 1``) plus any
symbol already covered by the call row when the master flag is absent
(hermetic fixtures); substrate-quarantined masters (synthetic ``INE_AUTO_*``
rows) are excluded via join, never deleted. Excess is rebuilt on market
closes (``horizon_excess``/``excess_table``), never on book ``exit_price``,
with weekly cohort clustering in ``excess_table``.

Idempotent: ``record_action`` re-records via
UNIQUE(symbol, action_date, action) return the existing row unchanged, so
re-runs reproduce the same summary. Prints a seed summary JSON, then runs
``mark_to_market`` at the latest EOD date + ``summarize`` and prints the
embryonic ROC JSON. Exits non-zero only on real failure.

Usage: ``python -m reality_engine.scripts.seed_track_record [days] [per_date]``
(defaults: 25 days, no per-date cap).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine.agent.orchestrator import AgentOrchestrator  # noqa: E402
from reality_engine.db.repository import Repository  # noqa: E402
from reality_engine.processing import portfolio_ledger as pl  # noqa: E402

logger = logging.getLogger("reality_engine.seed_track_record")

DEFAULT_DAYS = 25
SEED_THESIS_PREFIX = "seed_track_record"


def _fnum(x: Any) -> Optional[float]:
    """Finite float or None (None / garbage / NaN / +-inf -> None)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _usable_price(x: Any) -> Optional[float]:
    """Finite price > 0, else None (mirrors record_action level validation)."""
    v = _fnum(x)
    return v if v is not None and v > 0 else None


def _coverage_dates(conn: Any, days: int) -> List[str]:
    """Last ``days`` EOD dates present in BOTH attribution and price tables."""
    rows = conn.execute(
        "SELECT DISTINCT m.attribution_date AS d FROM move_attribution m "
        "WHERE EXISTS (SELECT 1 FROM daily_price_delivery p "
        "WHERE p.date = m.attribution_date) "
        "ORDER BY d DESC LIMIT ?",
        (max(1, int(days)),),
    ).fetchall()
    return sorted(str(r["d"]) for r in rows if r["d"] is not None)


def _material_rows(conn: Any, date: str, per_date: Optional[int]) -> List[Any]:
    """Material attribution rows for one date (deterministic symbol order)."""
    sql = (
        "SELECT * FROM move_attribution "
        "WHERE attribution_date = ? AND is_material = 1 ORDER BY symbol ASC"
    )
    args: tuple = (date,)
    if per_date is not None:
        sql += " LIMIT ?"
        args += (int(per_date),)
    return conn.execute(sql, args).fetchall()


def _is_nifty50_symbol(conn: Any, symbol: str) -> Optional[bool]:
    """True/False when ``master_companies`` carries the flag; None when unknown."""
    try:
        row = conn.execute(
            "SELECT is_nifty50 FROM master_companies WHERE nse_symbol = ? LIMIT 1",
            (symbol,),
        ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        return bool(int(row[0]))
    except (TypeError, ValueError):
        return bool(row[0])


def _is_quarantined_symbol(conn: Any, symbol: str) -> bool:
    """True when the symbol joins a quarantined synthetic master (never deleted)."""
    try:
        return bool(symbol in pl.quarantined_master_symbols(conn))
    except Exception:
        return False


def _call_row(conn: Any, symbol: str, date: str) -> Optional[Dict[str, Any]]:
    """The eod_scrip_calls presence/mode row for one (symbol, date) pair, if any."""
    row = conn.execute(
        "SELECT date, symbol, isin, current_market_price, "
        "is_solvency_approved FROM eod_scrip_calls "
        "WHERE symbol = ? AND date = ? LIMIT 1",
        (symbol, date),
    ).fetchone()
    return dict(row) if row else None


def _next_close(conn: Any, symbol: str, after_date: str) -> Any:
    """Next-session close after ``after_date`` for ``symbol`` (None if none)."""
    row = conn.execute(
        "SELECT close FROM daily_price_delivery "
        "WHERE symbol = ? AND date > ? ORDER BY date ASC LIMIT 1",
        (symbol, after_date),
    ).fetchone()
    return row["close"] if row else None


def run_seed(
    *,
    days: int = DEFAULT_DAYS,
    per_date: Optional[int] = None,
    manager: Optional[Any] = None,
    orch: Optional[Any] = None,
) -> Dict[str, Any]:
    """Seed the track record, MTM at the latest EOD, and summarize.

    Nifty-50 test ground with quarantine joins; target/stop are vol-scaled
    trailing-sigma brackets (SELL mirrored). Excess is rebuilt on market
    closes via ``horizon_excess``/``excess_table`` (weekly cohorts), never
    on book ``exit_price``.

    Returns ``{dates, candidates, recorded{BUY,SELL,HOLD},
    skipped{no_call,no_price,resolver,quarantined,non_nifty50},
    actions_now_open, mark_to_market, roc, excess}``. Never raises on a
    per-pair problem (skip + count); raises only on real failure
    (unreachable DB, missing source tables).
    """
    if manager is None:
        from reality_engine.db.database import db_manager

        manager = db_manager
    mgr = manager
    if orch is None:
        orch = AgentOrchestrator(repository=Repository(mgr))
    if per_date is not None:
        per_date = int(per_date)
    recorded = {"BUY": 0, "SELL": 0, "HOLD": 0}
    skipped = {"no_call": 0, "no_price": 0, "resolver": 0,
               "quarantined": 0, "non_nifty50": 0}
    candidates = 0
    with mgr.session() as conn:
        dates = _coverage_dates(conn, int(days))

    for date in dates:
        with mgr.session() as conn:
            attribs = [dict(r) for r in _material_rows(conn, date, per_date)]
        for attr in attribs:
            symbol = str(attr.get("symbol") or "").strip().upper()
            candidates += 1
            if not symbol:
                skipped["resolver"] += 1
                logger.warning("seed skip (resolver): blank symbol on %s", date)
                continue
            try:
                with mgr.session() as conn:
                    if _is_quarantined_symbol(conn, symbol):
                        skipped["quarantined"] += 1
                        logger.warning("seed skip (quarantined): %s @ %s", symbol, date)
                        continue
                    nifty_flag = _is_nifty50_symbol(conn, symbol)
                    call = _call_row(conn, symbol, date)
                if call is None:
                    skipped["no_call"] += 1
                    logger.warning("seed skip (no_call): %s @ %s", symbol, date)
                    continue
                # Nifty-50 test ground: skip non-flagged symbols, except when
                # the master row is unknown (hermetic fixtures carry no flag).
                if nifty_flag is False:
                    skipped["non_nifty50"] += 1
                    logger.warning("seed skip (non_nifty50): %s @ %s", symbol, date)
                    continue
                with mgr.session() as conn:
                    nxt = _next_close(conn, symbol, date)
                entry = _usable_price(nxt)
                if entry is None:
                    entry = _usable_price(call.get("current_market_price"))
                if entry is None:
                    skipped["no_price"] += 1
                    logger.warning("seed skip (no_price): %s @ %s", symbol, date)
                    continue
                try:
                    approved = int(call.get("is_solvency_approved") or 0)
                except (TypeError, ValueError):
                    approved = 0
                funda = {"forensic_solvency": {"is_solvency_approved": approved}}
                try:
                    action, _block = orch._resolve_thesis_action(
                        symbol,
                        candidate_row={
                            "symbol": symbol,
                            "isin": str(call.get("isin") or ""),
                        },
                        attribution=attr,
                        attribution_date=date,
                        funda=funda,
                    )
                except Exception as exc:
                    skipped["resolver"] += 1
                    logger.warning(
                        "seed skip (resolver): %s @ %s: %s", symbol, date, exc
                    )
                    continue
                if action not in ("BUY", "SELL", "HOLD"):
                    skipped["resolver"] += 1
                    logger.warning(
                        "seed skip (resolver): %s @ %s bad action %r",
                        symbol,
                        date,
                        action,
                    )
                    continue
                if action == "HOLD":
                    tgt, stp = None, None
                else:
                    try:
                        with mgr.session() as conn:
                            _br = pl.vol_scaled_bracket(symbol, entry, action, date,
                                                        conn=conn)
                        tgt, stp = _br["target_price"], _br["stop_loss"]
                    except Exception as exc:
                        skipped["resolver"] += 1
                        logger.warning(
                            "seed skip (resolver): bracket failed %s @ %s: %s",
                            symbol, date, exc,
                        )
                        continue
                try:
                    pl.record_action(
                        symbol,
                        action,
                        date,
                        entry if action != "HOLD" else None,
                        tgt,
                        stp,
                        thesis_ref=f"{SEED_THESIS_PREFIX}:{date}",
                        manager=mgr,
                    )
                except Exception as exc:
                    skipped["resolver"] += 1
                    logger.warning(
                        "seed skip (resolver): record failed %s @ %s: %s",
                        symbol,
                        date,
                        exc,
                    )
                    continue
                recorded[action] += 1
            except Exception as exc:  # last resort: never crash the seed
                skipped["resolver"] += 1
                logger.warning(
                    "seed skip (resolver): %s @ %s unexpected: %s",
                    symbol,
                    date,
                    exc,
                )

    with mgr.session() as conn:
        open_now = conn.execute(
            "SELECT COUNT(*) FROM portfolio_actions WHERE status = 'open'"
        ).fetchone()[0]
        latest = conn.execute("SELECT MAX(date) FROM daily_price_delivery").fetchone()[
            0
        ]
    seed_summary = {
        "dates": dates,
        "candidates": candidates,
        "recorded": recorded,
        "skipped": skipped,
        "actions_now_open": int(open_now),
    }
    mtm = (
        pl.mark_to_market(str(latest), manager=mgr)
        if latest
        else {"marked": 0, "closed": 0, "open_pnl_sum": 0.0}
    )
    roc = pl.summarize(manager=mgr)
    # Excess on market closes (never book exit_price), weekly cohorts in
    # excess_table; defensive so a thin fixture DB never fails the seed.
    try:
        excess = pl.excess_table(manager=mgr)
    except Exception as exc:
        logger.debug("seed excess rebuild failed: %s", exc)
        excess = {"horizons": list(pl.HORIZON_DEFAULTS), "universes": [],
                  "cells": {}, "skipped": {"excess-failed": 1},
                  "actions_evaluated": 0, "uncovered_actions": 0}
    return {**seed_summary, "mark_to_market": mtm, "roc": roc, "excess": excess}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Seed the portfolio track record from attribution history."
    )
    ap.add_argument(
        "days",
        nargs="?",
        type=int,
        default=DEFAULT_DAYS,
        help="last M EOD dates with attribution coverage (default: 25)",
    )
    ap.add_argument(
        "per_date",
        nargs="?",
        type=int,
        default=None,
        help="cap on material rows per date (default: no cap)",
    )
    args = ap.parse_args(argv)
    if args.days < 1:
        ap.error("days must be >= 1")
    if args.per_date is not None and args.per_date < 1:
        ap.error("per_date must be >= 1")
    try:
        out = run_seed(days=args.days, per_date=args.per_date)
    except Exception:
        logger.exception("seed_track_record failed")
        return 1
    print(
        json.dumps(
            {k: out[k] for k in ("dates", "candidates", "recorded", "skipped",
                                 "actions_now_open")},
            indent=2,
        )
    )
    print(
        json.dumps(
            {"mark_to_market": out["mark_to_market"], "roc": out["roc"],
             "excess": out.get("excess")},
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
