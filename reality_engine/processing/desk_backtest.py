"""
Desk backtest — Rs 10cr Oct-2021 lump-sum book + 4x4 excess harness.

Lump-sum Rs 10,00,00,000 cash on 2021-10-27 (no SIP schedule, no leverage:
buys scale to available cash, uninvested cash sits at 0%). Fractional shares
are a backtest-only convention (flagged on every artifact).

Price convention (frozen, shared with ``sip_backtest`` / ``horizon_excess``):
a close is usable iff finite and > 0, read from ``daily_price_delivery``;
trades happen at closes only, never forward-filled for trading; valuation
carries the last close on/before the date.

Tax/cost stack (reused, never redefined here): FIFO lots, STT 0.1%/side and
the Finance (No. 2) Act 2024 STCG/LTCG schedule, FY LTCG-exemption tracking,
intra-FY harvest, no cross-year loss carry-forward — all imported from
:mod:`reality_engine.processing.sip_backtest` (``TAX_SCHEDULE`` lives there
only). Risk-free rate is 0 throughout. The 50 bps round-trip impact prior and
the 5 bps all-in other-charges prior are ASSUMED priors, flagged wherever
they flow; the slippage audit replaces the impact prior with measurement.

Vol brackets (blocker 0b fix): trailing-20-session sigma clamped to
[0.5, 8.0] pct points (<5 sessions falls back to 2.0), ``k_target = 3`` /
``k_stop = 1`` (~3:1 risk unit), SELL mirrored so
``target < entry < stop``. The framing invariant is asserted at write and
aborts the run on violation (P0 honest book; never regress R-1).

Sweep rule (Sec 1.7): when no thesis clears the gates on a date, unallocated
capital is swept into the defensive sleeve (cash at 0% modelled yield, plus
listed gold/silver ETF legs on their own closes under the same cost stack
when ETF symbols are supplied) up to 40% of NAV. Sweep fraction and trigger
are printed on every NAV path.

Excess harness: horizons 30/90/180/365 (calendar days) x Nifty 50 /
Nifty Midcap 150 / Nifty Smallcap 250 / Nifty Microcap 250, realized-window
exits ``min(close, entry+h)`` (T9), XS-matched (same-day cross-sectional
control on the same population) primary with index-relative secondary,
ISO-week cohorts, cluster-robust stats + cohort hit CI + shuffle-entry
placebo per cell, per-universe n + unmapped list on every table.

Strategy legs F1 (forensic avoidance), F2 (vol-scaled continuation
momentum, pre-registered kill), F3 (regime-carry + defensive sleeve) are
paper-only diagnosers here: every leg stamps ``paper_only=True,
promoted=False`` and no leg can promote through this module.

Ownership: this module owns ONLY the desk lump-sum runner, the 4x4 grid,
the cost/drawdown reporters and the artifact builder. Explicit non-goals:
``record_action`` / seed / brackets above (owned by ``portfolio_ledger``),
tax tables / FIFO / SIP schedule (owned by ``sip_backtest``), repository /
schema / database / ingestion (never touched), ledger-table rewrites, weight
changes. Read-only on the DB (SELECTs only); the only writer is the optional
artifact JSON file.
"""

from __future__ import annotations

import bisect
import datetime
import logging
import math
import random as _random
import statistics as _statistics
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from reality_engine.processing import portfolio_ledger as pl
from reality_engine.processing import sip_backtest as sb

logger = logging.getLogger("reality_engine.desk_backtest")

#: Lump-sum inception (same day as ``sip_backtest.SIP_START``; lump sum, no SIP).
DESK_START: str = "2021-10-27"
#: Lump-sum cash credited on the first trading day on/after DESK_START (Rs).
DESK_INITIAL_CASH: float = 100000000.0
#: Desk horizons (calendar days); reuses the ledger default tuple.
DESK_HORIZONS: Tuple[int, ...] = tuple(int(h) for h in pl.HORIZON_DEFAULTS)
#: Sector cap (fraction of portfolio value per sector; overflow stays cash).
DESK_SECTOR_CAP: float = sb.SECTOR_CAP
#: Breadth bound (index-breadth coverage starts here; book before is flagged).
DESK_BREADTH_START: str = sb.BREADTH_START
#: Max defensive-sleeve fraction of NAV (cash/gold/silver sweep).
SWEEP_MAX_FRACTION: float = 0.40
#: Risk-free rate for Sharpe/Sortino (cash earns 0).
RISK_FREE_RATE: float = 0.0
#: Frozen bootstrap lens weights (cited, never changed here):
#: composite_screener.py:63-66 / ensemble_ranker.py:50-53.
#: Kept as a literal (not imported) so this module never pulls pandas/numpy
#: engines; values MUST match the cited sources.
DESK_BOOTSTRAP_WEIGHTS: Dict[str, float] = {
    "factor_statistical": 0.30,
    "business_quality": 0.25,
    "policy_macro": 0.25,
    "supply_chain": 0.20,
}
#: Bracket sigma multiples (mirror the ledger constants; never retuned here).
K_TARGET: float = pl.BRACKET_TARGET_SIGMA_MULT
K_STOP: float = pl.BRACKET_STOP_SIGMA_MULT
#: Shuffle-placebo draws per (entry, horizon); fixed seed => deterministic.
DESK_PLACEBO_DRAWS: int = 50
DESK_PLACEBO_SEED: int = 20260925
#: |placebo mean| at or under this (decimal) counts as "~=0".
DESK_PLACEBO_TOLERANCE: float = 0.010
#: Quarantine predicate (AGENTS.md rule 13): synthetic INE_AUTO_* masters
#: (live: 1,356 keys) plus substrate_quarantine row_keys are excluded on
#: every inference read, never deleted.
QUARANTINE_PREDICATE: str = (
    "master isin LIKE 'INE_AUTO%' OR isin IN "
    "(SELECT row_key FROM substrate_quarantine "
    "WHERE table_name='master_companies'); excluded on every read, never deleted"
)
#: Strategy-leg status: paper only, none promoted (CEO verdict 2026-09-25).
STRATEGY_STATUS: Dict[str, Dict[str, Any]] = {
    "F1": {"paper_only": True, "promoted": False,
           "note": "forensic-avoidance; Gate0+Gate1 F1-F7, PIT lags"},
    "F2": {"paper_only": True, "promoted": False,
           "note": "vol-scaled continuation-momentum; >=2σ + factor agreement, "
                   "pre-registered kill: 30D net <+500bps => kill, no k-tuning"},
    "F3": {"paper_only": True, "promoted": False,
           "note": "regime-carry + defensive sleeve; sizing/exits gated post-bar"},
}

_EPS: float = 1e-9


# ---------------------------------------------------------------------------
# Small pure helpers (generic date/number plumbing; tax math lives in sb)
# ---------------------------------------------------------------------------

def _parse(date_str: Any) -> datetime.date:
    return datetime.date.fromisoformat(str(date_str or "").strip()[:10])


def _fnum(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _bps(x: Any) -> Optional[float]:
    v = _fnum(x)
    return None if v is None else v * 10000.0


def _close_on_or_before(
    per: Dict[str, float], day: str, ordered: List[str],
) -> Optional[float]:
    i = bisect.bisect_right(ordered, day) - 1
    if i < 0:
        return None
    return per.get(ordered[i])


def _bars_on_or_after(
    bars: List[Tuple[str, float]], target: str,
) -> Tuple[Optional[str], Optional[float]]:
    dates = [d for d, _ in bars]
    i = bisect.bisect_left(dates, str(target))
    if i >= len(bars):
        return None, None
    return bars[i]


def _resolve_manager(manager: Optional[Any]) -> Any:
    if manager is not None:
        return manager
    from reality_engine.db.database import db_manager
    return db_manager


# ---------------------------------------------------------------------------
# Quarantine + read-only market load
# ---------------------------------------------------------------------------

def desk_quarantined_symbols(conn: Any) -> set:
    """Quarantined master symbols for this connection (read-only).

    Delegates to ``portfolio_ledger.quarantined_master_symbols``: synthetic
    ``INE_AUTO_*`` masters plus ``substrate_quarantine`` row_keys. Never
    deletes rows; empty set when the tables are absent.
    """
    try:
        return set(pl.quarantined_master_symbols(conn) or set())
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("desk quarantine scan failed: %s", exc)
        return set()


def _universe_for_row(is_nifty50: Any, tier: Any) -> Optional[str]:
    """Batch mirror of ``resolve_action_universe`` (same frozen rule)."""
    try:
        nifty = int(is_nifty50) == 1
    except (TypeError, ValueError):
        nifty = bool(is_nifty50)
    if nifty:
        return pl.UNIVERSE_INDEX["nifty50"]
    t = str(tier or "").strip().upper()
    if t == "MID":
        return pl.UNIVERSE_INDEX["midcap150"]
    if t == "SMALL":
        return pl.UNIVERSE_INDEX["smallcap250"]
    if t == "MICRO":
        return pl.UNIVERSE_INDEX["microcap250"]
    return None


def load_desk_market(
    manager: Optional[Any] = None,
    symbols: Optional[List[str]] = None,
    start: str = DESK_START,
    end: Optional[str] = None,
    load_index: bool = True,
) -> Dict[str, Any]:
    """Read-only desk market bundle (never writes).

    Closes come from ``daily_price_delivery`` (finite, > 0 only); quarantine
    symbols are excluded from symbols, prices and coverage alike. Returns
    ``{symbols, sector_map, universe_map, price_map, index_map,
    trading_days, flags, coverage}`` where ``coverage`` carries
    per-universe n, the unmapped-symbol list and the quarantined-excluded
    count (printed with every table via :func:`format_coverage_4x4`).
    """
    start_iso = _parse(start).isoformat()
    end_iso = _parse(end).isoformat() if end is not None else None
    mgr = _resolve_manager(manager)
    wanted = [pl.UNIVERSE_INDEX[k]
              for k in ("nifty50", "midcap150", "smallcap250", "microcap250")]
    with mgr.session() as conn:
        if not sb._table_exists(conn, "daily_price_delivery"):
            return {"symbols": [], "sector_map": {}, "universe_map": {},
                    "price_map": {}, "index_map": {}, "trading_days": [],
                    "flags": {"start": start_iso, "end": end_iso,
                              "n_symbols": 0},
                    "coverage": {"per_universe_n": {u: 0 for u in wanted},
                                 "unmapped": [], "quarantined_excluded": 0,
                                 "n_symbols": 0}}
        quarantined = desk_quarantined_symbols(conn)
        have_masters = sb._table_exists(conn, "master_companies")
        if symbols is None:
            if not have_masters:
                syms: List[str] = []
                meta: Dict[str, Dict[str, Any]] = {}
            else:
                rows = conn.execute(
                    "SELECT nse_symbol, isin, sector, is_nifty50, market_cap_tier "
                    "FROM master_companies").fetchall()
                syms = []
                meta = {}
                for r in rows:
                    try:
                        s = str(r["nse_symbol"]).strip().upper()
                    except Exception:
                        continue
                    if not s or s in quarantined:
                        continue
                    syms.append(s)
                    try:
                        sec = str(r["sector"] or "").strip() or "Unknown"
                    except Exception:
                        sec = "Unknown"
                    meta[s] = {"sector": sec,
                               "universe": _universe_for_row(
                                   r["is_nifty50"], r["market_cap_tier"])}
                syms.sort()
        else:
            wanted_in = [str(s).strip().upper() for s in symbols if str(s).strip()]
            meta = {}
            if have_masters and wanted_in:
                placeholders = ",".join("?" for _ in wanted_in)
                try:
                    rows = conn.execute(
                        "SELECT nse_symbol, sector, is_nifty50, market_cap_tier "
                        "FROM master_companies WHERE nse_symbol IN (%s)"
                        % placeholders, tuple(wanted_in)).fetchall()
                except Exception:
                    rows = []
                for r in rows:
                    try:
                        s = str(r["nse_symbol"]).strip().upper()
                        sec = str(r["sector"] or "").strip() or "Unknown"
                    except Exception:
                        continue
                    meta[s] = {"sector": sec,
                               "universe": _universe_for_row(
                                   r["is_nifty50"], r["market_cap_tier"])}
            syms = [s for s in wanted_in if s not in quarantined]
            for s in syms:
                meta.setdefault(s, {"sector": "Unknown", "universe": None})
        n_quarantined = 0
        if symbols is not None:
            n_quarantined = sum(
                1 for s in symbols if str(s).strip().upper() in quarantined)
        elif have_masters:
            try:
                rows = conn.execute(
                    "SELECT nse_symbol FROM master_companies").fetchall()
                n_quarantined = sum(
                    1 for r in rows
                    if str(r["nse_symbol"] or "").strip().upper() in quarantined)
            except Exception:
                n_quarantined = len(quarantined)
        sector_map = {s: meta.get(s, {}).get("sector", "Unknown") for s in syms}
        universe_map = {s: meta.get(s, {}).get("universe") for s in syms}
        price_map: Dict[str, Dict[str, float]] = {s: {} for s in syms}
        if syms:
            placeholders = ",".join("?" for _ in syms)
            q = ("SELECT symbol, date, close FROM daily_price_delivery "
                 "WHERE date >= ? AND symbol IN (%s)" % placeholders)
            args: List[Any] = [start_iso, *syms]
            if end_iso is not None:
                q += " AND date <= ?"
                args.append(end_iso)
            try:
                rows = conn.execute(q, tuple(args)).fetchall()
            except Exception as exc:
                logger.debug("desk price load failed: %s", exc)
                rows = []
            for r in rows:
                try:
                    sym = str(r["symbol"]).strip().upper()
                    day = str(r["date"])[:10]
                    close = _fnum(r["close"])
                except Exception:
                    continue
                if sym not in price_map or close is None or close <= 0:
                    continue
                if day < start_iso or (end_iso is not None and day > end_iso):
                    continue
                price_map[sym][day] = close
        index_map: Dict[str, Dict[str, float]] = {}
        if load_index and sb._table_exists(conn, "nse_index_breadth"):
            for u in wanted:
                q = ("SELECT date, close FROM nse_index_breadth "
                     "WHERE index_name = ? AND date >= ?")
                args2: List[Any] = [u, start_iso]
                if end_iso is not None:
                    q += " AND date <= ?"
                    args2.append(end_iso)
                q += " ORDER BY date ASC"
                try:
                    rows = conn.execute(q, tuple(args2)).fetchall()
                except Exception:
                    rows = []
                per: Dict[str, float] = {}
                for r in rows:
                    try:
                        day = str(r["date"])[:10]
                        close = _fnum(r["close"])
                    except Exception:
                        continue
                    if close is None or close <= 0:
                        continue
                    per[day] = close
                index_map[u] = per
    day_set = set()
    for per in price_map.values():
        day_set.update(per.keys())
    trading_days = sorted(day_set)
    first_px = {s: (min(per.keys()) if per else None)
                for s, per in price_map.items()}
    first_day = trading_days[0] if trading_days else None
    late_joiners = sorted(
        s for s, d in first_px.items()
        if d is not None and first_day is not None and d > first_day)
    per_universe_n = {u: 0 for u in wanted}
    unmapped: List[str] = []
    for s in syms:
        u = universe_map.get(s)
        if u in per_universe_n:
            per_universe_n[u] += 1
        else:
            unmapped.append(s)
    unmapped.sort()
    flags = {
        "start": start_iso,
        "end": end_iso or (trading_days[-1] if trading_days else None),
        "initial_cash": DESK_INITIAL_CASH,
        "lump_sum": True,
        "sip": False,
        "no_leverage": True,
        "fractional_shares": "backtest-only",
        "sector_cap": DESK_SECTOR_CAP,
        "sweep_max": SWEEP_MAX_FRACTION,
        "risk_free": RISK_FREE_RATE,
        "stt_buy_rate": sb.STT_BUY_RATE,
        "stt_sell_rate": sb.STT_SELL_RATE,
        "other_charge_rate": sb.OTHER_CHARGE_RATE,
        "other_charges_assumed": True,
        "impact_prior": pl.EXCESS_COST,
        "impact_prior_assumed": True,
        "equal_weight_pre_breadth": start_iso < DESK_BREADTH_START,
        "breadth_start": DESK_BREADTH_START,
        "n_symbols": len(syms),
        "n_symbols_day_one": sum(
            1 for s in syms
            if first_px[s] is not None and first_day is not None
            and first_px[s] <= first_day),
        "late_joiners": late_joiners,
        "trading_days": len(trading_days),
        "quarantine_predicate": QUARANTINE_PREDICATE,
    }
    coverage = {
        "per_universe_n": per_universe_n,
        "unmapped": unmapped,
        "quarantined_excluded": n_quarantined,
        "n_symbols": len(syms),
    }
    return {"symbols": syms, "sector_map": sector_map,
            "universe_map": universe_map, "price_map": price_map,
            "index_map": index_map, "trading_days": trading_days,
            "flags": flags, "coverage": coverage}


# ---------------------------------------------------------------------------
# Thesis framing + vol-scaled brackets (ledger-owned math, reused)
# ---------------------------------------------------------------------------

def assert_thesis_framing(
    action: Any,
    entry: Any,
    target: Any,
    stop: Any,
) -> None:
    """Assert the honest-book framing invariant; abort on violation.

    Desk contract (P0, strict): BUY requires all three legs with
    ``target > entry > stop``; SELL requires all three legs with
    ``target < entry < stop``; HOLD requires all three legs None.
    Missing or mis-framed BUY/SELL legs raise ValueError (the run aborts;
    SELL nastiness never regresses R-1).
    """
    act = str(action or "").strip().upper()
    if act not in ("BUY", "SELL", "HOLD"):
        raise ValueError(
            "desk_backtest: action must be BUY/SELL/HOLD, got %r" % (action,))

    def _lvl(name: str, v: Any) -> float:
        f = _fnum(v)
        if f is None or f <= 0:
            raise ValueError(
                "desk_backtest: %s %s level must be a finite price > 0, "
                "got %r" % (act, name, v))
        return f

    if act == "HOLD":
        if entry is not None or target is not None or stop is not None:
            raise ValueError(
                "desk_backtest: HOLD is non-positional; entry/target/stop "
                "must be None, got entry=%r target=%r stop=%r"
                % (entry, target, stop))
        return
    e, t, s = _lvl("entry", entry), _lvl("target", target), _lvl("stop", stop)
    if act == "BUY":
        if not (t > e > s):
            raise ValueError(
                "desk_backtest: BUY requires target > entry > stop, got "
                "target=%r entry=%r stop=%r" % (target, entry, stop))
        return
    if not (t < e < s):
        raise ValueError(
            "desk_backtest: SELL requires target < entry < stop, got "
            "target=%r entry=%r stop=%r" % (target, entry, stop))

def trailing_sigma_pct(closes: List[Any]) -> float:
    """Trailing sigma (pct points) from ascending closes; clamped [0.5, 8.0].

    Close-to-close % moves over the last ``BRACKET_LOOKBACK`` sessions
    (population std, same history rule as the ledger noise floor); fewer
    than ``BRACKET_MIN_SESSIONS`` moves falls back to 2.0. Pure (no DB).
    """
    vals = [c for c in (_fnum(x) for x in (closes or []))
            if c is not None and c > 0]
    moves = [(vals[i] / vals[i - 1] - 1.0) * 100.0
             for i in range(1, len(vals)) if vals[i - 1] != 0]
    moves = [m for m in moves[-pl.BRACKET_LOOKBACK:] if math.isfinite(m)]
    if len(moves) < pl.BRACKET_MIN_SESSIONS:
        return pl.BRACKET_SIGMA_FALLBACK_PCT
    try:
        sigma = float(_statistics.pstdev(moves))
    except Exception:
        return pl.BRACKET_SIGMA_FALLBACK_PCT
    if not math.isfinite(sigma):
        return pl.BRACKET_SIGMA_FALLBACK_PCT
    return max(pl.BRACKET_SIGMA_MIN_PCT,
               min(pl.BRACKET_SIGMA_MAX_PCT, sigma))


def desk_bracket(
    entry_price: float,
    closes_history: List[Any],
    action: Any,
) -> Dict[str, float]:
    """Vol-scaled bracket for one entry (ledger math, asserted framing).

    ``sigma`` from :func:`trailing_sigma_pct`, levels from
    ``portfolio_ledger.bracket_for_entry`` (``k_target=3`` / ``k_stop=1``,
    SELL mirrored). Fixed 18%/6% brackets are forbidden.
    """
    sigma = trailing_sigma_pct(closes_history)
    out = pl.bracket_for_entry(entry_price, sigma, action)
    assert_thesis_framing(action, entry_price,
                           out["target_price"], out["stop_loss"])
    return out


# ---------------------------------------------------------------------------
# Cost bridge gross -> net (diagnostic; book NAV pays real FIFO/STT/tax)
# ---------------------------------------------------------------------------

def apply_cost_stack(
    gross_excess: float,
    tax_drag: float = 0.0,
    impact: Optional[float] = None,
    stt_buy: Optional[float] = None,
    stt_sell: Optional[float] = None,
    other: Optional[float] = None,
) -> Dict[str, Any]:
    """Split a gross excess (decimal) into the measured-cost bridge.

    Contract (desk spec Sec 1.8): per round trip, the cost stack is the
    50bps impact prior + STT 0.1% buy + 0.1% sell + 5bps other (single
    all-in leg, ASSUMED prior) + FIFO STCG/LTCG tax drag, so
    ``net = gross - impact - stt_buy - stt_sell - other - tax`` in decimal;
    e.g. gross 0.02 nets 0.012 (1200bps). The impact/other priors are
    ASSUMED until the slippage audit lands; STT rates and the tax schedule
    are the shared engine constants.
    """
    g = _fnum(gross_excess) or 0.0
    imp = pl.EXCESS_COST if impact is None else float(impact)
    sb_rate = sb.STT_BUY_RATE if stt_buy is None else float(stt_buy)
    ss_rate = sb.STT_SELL_RATE if stt_sell is None else float(stt_sell)
    oth = sb.OTHER_CHARGE_RATE if other is None else float(other)
    tax = _fnum(tax_drag) or 0.0
    return {"gross": g, "impact_prior": imp,
            "stt_buy": sb_rate, "stt_sell": ss_rate,
            "other": oth, "tax_drag": tax,
            "net": g - imp - sb_rate - ss_rate - oth - tax,
            "impact_prior_assumed": True, "other_charges_assumed": True}


def cost_bridge_bps(
    gross_excess: float,
    tax_drag: float = 0.0,
) -> Dict[str, Any]:
    """Same bridge in basis points (for 4x4 cell footers)."""
    b = apply_cost_stack(gross_excess, tax_drag)
    return {"gross_bps": b["gross"] * 10000.0,
            "impact_prior_bps": b["impact_prior"] * 10000.0,
            "stt_buy_bps": b["stt_buy"] * 10000.0,
            "stt_sell_bps": b["stt_sell"] * 10000.0,
            "other_bps": b["other"] * 10000.0,
            "tax_drag_bps": b["tax_drag"] * 10000.0,
            "net_bps": b["net"] * 10000.0,
            "impact_prior_assumed": True, "other_charges_assumed": True}


# ---------------------------------------------------------------------------
# Drawdown / Calmar / time-under-water + sleeve attribution
# ---------------------------------------------------------------------------

def drawdown_report(
    dates: List[str],
    navs: List[float],
) -> Dict[str, Any]:
    """Drawdown report over a post-tax NAV series (risk-free 0).

    Extends ``sip_backtest.nav_drawdown`` with CAGR, Calmar (CAGR/max_dd)
    and time-under-water in days (peak -> recovery; to series end when never
    recovered; 0 when no drawdown).
    """
    base = sb.nav_drawdown(list(dates or []), list(navs or []))
    out: Dict[str, Any] = dict(base)
    out.update({"cagr": None, "calmar": None, "time_under_water_days": 0,
                "recovery_date": None})
    if not dates or not navs or len(dates) != len(navs) or len(dates) < 2:
        return out
    try:
        first = _fnum(navs[0])
        last = _fnum(navs[-1])
        first_day = _parse(dates[0])
        last_day = _parse(dates[-1])
    except Exception:
        return out
    if first is None or last is None or first <= 0 or last <= 0:
        return out
    span = (last_day - first_day).days
    if span > 0:
        try:
            cagr = (last / first) ** (365.0 / span) - 1.0
            out["cagr"] = cagr if math.isfinite(cagr) else None
        except Exception:
            out["cagr"] = None
    max_dd = _fnum(base.get("max_dd")) or 0.0
    if max_dd > 0 and out["cagr"] is not None:
        try:
            out["calmar"] = out["cagr"] / max_dd
        except Exception:
            out["calmar"] = None
    if max_dd <= 0 or not base.get("peak_date") or not base.get("trough_date"):
        return out
    try:
        peak_day = _parse(str(base["peak_date"]))
        peak_val: Optional[float] = None
        trough_i = 0
        for i, (d, n) in enumerate(zip(dates, navs)):
            if str(d)[:10] == base["trough_date"]:
                trough_i = i
                break
        for i, (d, n) in enumerate(zip(dates, navs)):
            if str(d)[:10] == base["peak_date"]:
                peak_val = _fnum(n)
                break
        if peak_val is None:
            return out
        rec = None
        for i in range(trough_i, len(dates)):
            v = _fnum(navs[i])
            if v is not None and v >= peak_val:
                rec = str(dates[i])[:10]
                break
        if rec is None:
            out["recovery_date"] = None
            out["time_under_water_days"] = (last_day - peak_day).days
        else:
            out["recovery_date"] = rec
            out["time_under_water_days"] = (
                _parse(rec) - peak_day).days
    except Exception:
        pass
    return out


def sleeve_drawdown_attribution(
    dates: List[str],
    nav_with_sweep: List[float],
    nav_without_sweep: List[float],
) -> Dict[str, Any]:
    """Sleeve-attributed drawdown reduction (graded, not narrated).

    Positive ``reduction`` means the defensive sleeve lowered max drawdown.
    """
    dd_with = sb.nav_drawdown(list(dates or []), list(nav_with_sweep or []))
    dd_without = sb.nav_drawdown(list(dates or []), list(nav_without_sweep or []))
    red = (_fnum(dd_without.get("max_dd")) or 0.0) - (
        _fnum(dd_with.get("max_dd")) or 0.0)
    return {"max_dd_with_sweep": dd_with.get("max_dd"),
            "max_dd_without_sweep": dd_without.get("max_dd"),
            "reduction": red, "reduction_bps": red * 10000.0}


# ---------------------------------------------------------------------------
# Lump-sum book runner (Rs 10cr, thesis-or-sweep)
# ---------------------------------------------------------------------------

ThesisFn = Callable[[str, str], Any]


def _parse_thesis(raw: Any, symbol: str, day: str,
                  close: Optional[float]) -> Dict[str, Any]:
    """Normalise a thesis_fn return to {action, target, stop, entry}.

    Accepts ``"BUY"`` / ``"SELL"`` / ``"HOLD"`` / None, or a dict with those
    keys plus optional explicit levels (framing asserted by the caller;
    violation aborts the run).
    """
    if raw is None:
        return {"action": "HOLD", "target": None, "stop": None,
                "entry": close}
    if isinstance(raw, str):
        act = raw.strip().upper()
        if act not in ("BUY", "SELL", "HOLD"):
            raise ValueError(
                "desk_backtest: thesis_fn must return BUY/SELL/HOLD, got %r "
                "for %s @ %s" % (raw, symbol, day))
        return {"action": act, "target": None, "stop": None, "entry": close}
    if isinstance(raw, dict):
        act = str(raw.get("action") or "HOLD").strip().upper()
        if act not in ("BUY", "SELL", "HOLD"):
            raise ValueError(
                "desk_backtest: thesis_fn must return BUY/SELL/HOLD, got %r "
                "for %s @ %s" % (raw.get("action"), symbol, day))
        return {"action": act, "target": raw.get("target"),
                "stop": raw.get("stop"),
                "entry": raw.get("entry", close)}
    raise ValueError(
        "desk_backtest: thesis_fn must return a string or dict, got %r "
        "for %s @ %s" % (raw, symbol, day))


def _is_harvest_day(day: str, days: List[str]) -> bool:
    """Last trading day of March (intra-FY harvest just before FY end)."""
    try:
        i = days.index(day)
    except ValueError:
        return False
    try:
        if _parse(day).month != 3:
            return False
    except Exception:
        return False
    if i + 1 >= len(days):
        return True
    try:
        return _parse(days[i + 1]).month != 3
    except Exception:
        return False


def run_desk_book(
    symbols: List[str],
    price_map: Dict[str, Dict[str, float]],
    sector_map: Dict[str, str],
    trading_days: List[str],
    thesis_fn: Optional[ThesisFn] = None,
    universe_map: Optional[Dict[str, Optional[str]]] = None,
    start: str = DESK_START,
    end: Optional[str] = None,
    sector_cap: Optional[float] = None,
    sweep_max: float = SWEEP_MAX_FRACTION,
    gold_symbols: Tuple[str, ...] = (),
    silver_symbols: Tuple[str, ...] = (),
    harvest: bool = True,
) -> Dict[str, Any]:
    """Run the Rs 10cr lump-sum thesis-or-sweep book (pure; no DB).

    ``thesis_fn(symbol, date)`` returns an action or action dict (see
    :func:`_parse_thesis`); None means every name HOLDs and the 40% sweep
    holds the book defensive. Sells realise FIFO gains and pay tax from
    proceeds (``sip_backtest`` lots); buys scale to deployable cash (no
    leverage). SELL legs score avoided-loss-vs-holding (cash-segment
    honest): a SELL exits the holding at the close; the short-excess
    secondary lives in the 4x4 grid, never as book P&L.
    """
    cap = DESK_SECTOR_CAP if sector_cap is None else float(sector_cap)
    smax = float(sweep_max)
    syms = [str(s).strip().upper() for s in (symbols or []) if str(s).strip()]
    days = sorted(d for d in (trading_days or [])
                  if _parse(d).isoformat() >= _parse(start).isoformat()
                  and (end is None or _parse(d).isoformat()
                       <= _parse(end).isoformat()))
    sector_of = {s: str((sector_map or {}).get(s) or "Unknown") for s in syms}
    etfs = [str(e).strip().upper()
            for e in (list(gold_symbols or []) + list(silver_symbols or []))
            if str(e).strip()]
    gold_set = {str(e).strip().upper() for e in (gold_symbols or [])
                if str(e).strip()}
    all_syms = list(syms) + [e for e in etfs if e not in syms]
    for e in etfs:
        if e in gold_set:
            sector_of.setdefault(e, "Gold")
        else:
            sector_of.setdefault(e, "Silver")
    ordered: Dict[str, List[str]] = {
        s: sorted((price_map or {}).get(s, {}).keys()) for s in all_syms}
    first_px = {s: (ordered[s][0] if ordered[s] else None) for s in all_syms}
    late_joiners = sorted(
        s for s in syms
        if first_px[s] is not None and days and first_px[s] > days[0])
    flags: Dict[str, Any] = {
        "desk_start": _parse(start).isoformat(),
        "initial_cash": DESK_INITIAL_CASH,
        "lump_sum": True, "sip": False, "no_leverage": True,
        "fractional_shares": "backtest-only",
        "sector_cap": cap, "sweep_max": smax,
        "gold_symbols": sorted(gold_set),
        "silver_symbols": sorted(
            {e for e in etfs if e not in gold_set}),
        "harvest": bool(harvest),
        "stt_buy_rate": sb.STT_BUY_RATE,
        "stt_sell_rate": sb.STT_SELL_RATE,
        "other_charge_rate": sb.OTHER_CHARGE_RATE,
        "other_charges_assumed": True,
        "impact_prior": pl.EXCESS_COST,
        "impact_prior_assumed": True,
        "risk_free": RISK_FREE_RATE,
        "sell_scoring": "avoided-loss-vs-holding primary; "
                        "short-excess secondary in grid only",
        "equal_weight_pre_breadth": (
            _parse(start).isoformat() < DESK_BREADTH_START),
        "breadth_start": DESK_BREADTH_START,
        "late_joiners": late_joiners,
        "quarantine_predicate": QUARANTINE_PREDICATE,
        "strategies": {k: dict(v) for k, v in STRATEGY_STATUS.items()},
    }
    empty: Dict[str, Any] = {
        "nav_daily": [], "cash_path": [], "sweep_path": [], "sector_path": [],
        "pre_tax_xirr": None, "post_tax_xirr": None,
        "max_dd": sb.nav_drawdown([], []),
        "drawdown": drawdown_report([], []),
        "rolling": {"1yr": [], "3yr": []},
        "sharpe": None, "sortino": None, "taxes_paid": 0.0,
        "tax_by_fy": {}, "contributions": 0.0, "flags": flags,
        "lots": [], "late_joiners": late_joiners,
        "entries_log": [], "n_buys": 0, "n_sells": 0, "n_harvest_sells": 0,
        "n_sweep_buys": 0,
    }
    if not syms or not days:
        return empty
    cash_day = sb.resolve_trade_date(_parse(start).isoformat(), days)
    if cash_day is None:
        return empty

    lots_by: Dict[str, List[Any]] = {s: [] for s in all_syms}
    qty_of: Dict[str, float] = {s: 0.0 for s in all_syms}
    cash = 0.0
    contributions = 0.0
    taxes_paid = 0.0
    tax_by_fy: Dict[str, float] = {}
    exempt_used: Dict[str, float] = {}
    n_buys = n_sells = n_harvest = n_sweep_buys = 0
    nav_daily: List[Dict[str, Any]] = []
    cash_path: List[Dict[str, Any]] = []
    sweep_path: List[Dict[str, Any]] = []
    sector_path: List[Dict[str, Any]] = []
    flow_dates: List[str] = []
    flow_amounts: List[float] = []
    entries_log: List[Dict[str, Any]] = []
    open_buy_idx: Dict[str, List[int]] = {s: [] for s in all_syms}

    def _close(s: str, day: str) -> Optional[float]:
        per = (price_map or {}).get(s, {})
        if day in per:
            c = _fnum(per[day])
            if c is not None and c > 0:
                return float(per[day])
        return None

    def _value(s: str, day: str) -> float:
        last = _close_on_or_before((price_map or {}).get(s, {}), day,
                                   ordered.get(s, []))
        q = qty_of.get(s, 0.0)
        return q * last if last else 0.0

    def _sell_all(s: str, px: float, day: str, harvest_tag: bool = False) -> None:
        nonlocal cash, taxes_paid, n_sells, n_harvest
        if qty_of.get(s, 0.0) <= _EPS:
            return
        proceeds, gains = sb.sell_fifo(lots_by[s], qty_of[s], px, day)
        tax, inc = sb.tax_on_sale(gains, day, exempt_used)
        fy = sb.fy_of(day)
        exempt_used[fy] = exempt_used.get(fy, 0.0) + inc
        cash += proceeds - tax
        taxes_paid += tax
        tax_by_fy[fy] = tax_by_fy.get(fy, 0.0) + tax
        qty_of[s] = sum(l.qty for l in lots_by[s])
        if harvest_tag:
            n_harvest += 1
        else:
            n_sells += 1
        for i in open_buy_idx.get(s, []):
            if entries_log[i].get("closed_date") is None:
                entries_log[i]["closed_date"] = day
        open_buy_idx[s] = []

    for day in days:
        if day == cash_day:
            cash += DESK_INITIAL_CASH
            contributions += DESK_INITIAL_CASH
            flow_dates.append(day)
            flow_amounts.append(-DESK_INITIAL_CASH)
        if day < cash_day:
            nav_daily.append({"date": day, "nav_pre": 0.0,
                              "nav_post": 0.0, "cash": 0.0,
                              "sweep_fraction": 0.0, "sweep_active": False})
            cash_path.append({"date": day, "cash": 0.0, "cash_fraction": 1.0})
            sweep_path.append({"date": day, "sweep_active": False,
                               "sweep_fraction": 0.0, "sweep_value": 0.0,
                               "etf_value": 0.0})
            sector_path.append({"date": day, "weights": {}})
            continue

        closes: Dict[str, float] = {}
        for s in all_syms:
            c = _close(s, day)
            if c is not None:
                closes[s] = c
        listed = [s for s in syms
                  if first_px[s] is not None and first_px[s] <= day]
        holdings_val = sum(_value(s, day) for s in all_syms)
        nav = holdings_val + cash

        buys: List[str] = []
        sells: List[str] = []
        if thesis_fn is not None:
            for s in listed:
                raw = thesis_fn(s, day)
                th = _parse_thesis(raw, s, day, closes.get(s))
                if isinstance(raw, dict) and (
                        th["entry"] is not None or th["target"] is not None
                        or th["stop"] is not None):
                    assert_thesis_framing(th["action"], th["entry"],
                                          th["target"], th["stop"])
                if th["action"] == "BUY":
                    buys.append(s)
                elif th["action"] == "SELL":
                    sells.append(s)
                    entries_log.append(
                        {"symbol": s, "action": "SELL",
                         "entry_date": day, "closed_date": None})

        sweep_active = not buys and not sells
        sweep_fraction = 0.0
        sweep_reserve = 0.0
        if sweep_active and nav > 0 and cash > 0:
            sweep_fraction = min(smax, cash / nav)
            sweep_reserve = sweep_fraction * nav

        for s in sells:
            if s in closes and qty_of.get(s, 0.0) > _EPS:
                _sell_all(s, closes[s], day)

        if harvest and _is_harvest_day(day, days):
            for s in list(syms):
                if qty_of.get(s, 0.0) <= _EPS or s not in closes:
                    continue
                lots = lots_by[s]
                if not lots:
                    continue
                px = closes[s]
                cost = sum(l.qty * l.cost_per_share for l in lots)
                unreal = (qty_of[s] * px
                          * (1.0 - sb.STT_SELL_RATE - sb.OTHER_CHARGE_RATE)
                          - cost)
                if unreal >= -_EPS:
                    continue
                try:
                    oldest = min(_parse(l.buy_date) for l in lots)
                    short = (_parse(day) - oldest).days <= sb.LTCG_MIN_HOLD_DAYS
                except Exception:
                    short = True
                if short:
                    _sell_all(s, px, day, harvest_tag=True)

        holdings_val = sum(_value(s, day) for s in all_syms)
        nav_after = holdings_val + cash
        deployable = max(0.0, cash - sweep_reserve)
        candidates = [s for s in buys if s in closes]
        if candidates and deployable > _EPS:
            tot = float(len(candidates))
            capped = sb._apply_sector_cap(
                {s: 1.0 / tot for s in candidates}, sector_of, cap)
            equity_budget = max(0.0, nav_after - sweep_reserve)
            targets = {s: capped.get(s, 0.0) * equity_budget
                       for s in candidates}
            vals = {s: _value(s, day) for s in candidates}
            desired = {s: targets[s] - vals.get(s, 0.0) for s in candidates}
            need = sum(g for g in desired.values() if g > _EPS)
            scale = min(1.0, deployable / need) if need > _EPS else 0.0
            for s in candidates:
                gap = desired[s]
                if gap <= _EPS:
                    continue
                spend = gap * scale
                if spend <= _EPS:
                    continue
                gross = spend / (1.0 + sb.STT_BUY_RATE + sb.OTHER_CHARGE_RATE)
                q = gross / closes[s]
                if sb.add_lot(lots_by[s], s, day, q, closes[s]) is not None:
                    cash -= spend
                    qty_of[s] = sum(l.qty for l in lots_by[s])
                    n_buys += 1
                    entries_log.append(
                        {"symbol": s, "action": "BUY",
                         "entry_date": day, "closed_date": None})
                    open_buy_idx[s].append(len(entries_log) - 1)

        etf_names = [e for e in etfs if e in closes]
        if sweep_active and etf_names and sweep_reserve > _EPS and cash > _EPS:
            per_etf = sweep_reserve / len(etf_names)
            for e in etf_names:
                spend = min(per_etf, cash)
                if spend <= _EPS:
                    continue
                gross = spend / (1.0 + sb.STT_BUY_RATE + sb.OTHER_CHARGE_RATE)
                q = gross / closes[e]
                if sb.add_lot(lots_by[e], e, day, q, closes[e]) is not None:
                    cash -= spend
                    qty_of[e] = sum(l.qty for l in lots_by[e])
                    n_sweep_buys += 1

        holdings_val = sum(_value(s, day) for s in all_syms)
        nav_post = holdings_val + cash
        nav_pre = nav_post + taxes_paid
        etf_value = sum(_value(e, day) for e in etfs)
        nav_daily.append({"date": day, "nav_pre": nav_pre,
                          "nav_post": nav_post, "cash": cash,
                          "sweep_fraction": sweep_fraction,
                          "sweep_active": sweep_active})
        cash_path.append({"date": day, "cash": cash,
                          "cash_fraction": cash / nav_post if nav_post > 0 else 1.0})
        sweep_path.append({"date": day, "sweep_active": sweep_active,
                           "sweep_fraction": sweep_fraction,
                           "sweep_value": sweep_fraction * nav_post,
                           "etf_value": etf_value})
        sec_w: Dict[str, float] = {}
        if nav_post > 0:
            for s in all_syms:
                sec = sector_of.get(s, "Unknown")
                sec_w[sec] = sec_w.get(sec, 0.0) + _value(s, day) / nav_post
        sector_path.append({"date": day, "weights": sec_w})

    nav_dates = [r["date"] for r in nav_daily]
    post_navs = [r["nav_post"] for r in nav_daily]
    pre_navs = [r["nav_pre"] for r in nav_daily]
    post_xirr = sb.xirr(flow_dates + [days[-1]],
                        flow_amounts + ([post_navs[-1]] if post_navs else []))
    pre_xirr = sb.xirr(flow_dates + [days[-1]],
                       flow_amounts + ([pre_navs[-1]] if pre_navs else []))
    return {
        "nav_daily": nav_daily,
        "cash_path": cash_path,
        "sweep_path": sweep_path,
        "sector_path": sector_path,
        "pre_tax_xirr": pre_xirr,
        "post_tax_xirr": post_xirr,
        "max_dd": sb.nav_drawdown(nav_dates, post_navs),
        "drawdown": drawdown_report(nav_dates, post_navs),
        "rolling": sb.rolling_returns(nav_dates, post_navs),
        "sharpe": sb.sharpe_ratio(post_navs),
        "sortino": sb.sortino_ratio(post_navs),
        "taxes_paid": taxes_paid,
        "tax_by_fy": tax_by_fy,
        "contributions": contributions,
        "flags": flags,
        "lots": [lot.to_dict() for s in all_syms for lot in lots_by[s]],
        "late_joiners": late_joiners,
        "entries_log": entries_log,
        "n_buys": n_buys,
        "n_sells": n_sells,
        "n_harvest_sells": n_harvest,
        "n_sweep_buys": n_sweep_buys,
    }


# ---------------------------------------------------------------------------
# 4x4 excess harness (XS primary + index secondary, cohorts, placebo)
# ---------------------------------------------------------------------------

def _bars_from_map(price_map: Dict[str, Dict[str, float]]
                   ) -> Dict[str, List[Tuple[str, float]]]:
    out: Dict[str, List[Tuple[str, float]]] = {}
    for s, per in (price_map or {}).items():
        pts: List[Tuple[str, float]] = []
        for d, c in (per or {}).items():
            v = _fnum(c)
            if v is None or v <= 0:
                continue
            try:
                day = str(d)[:10]
                _parse(day)
            except Exception:
                continue
            pts.append((day, float(v)))
        pts.sort()
        out[str(s)] = pts
    return out


def realized_window(
    stock_bars: List[Tuple[str, float]],
    entry_date: str,
    horizon_days: int,
    closed_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Realized window ``min(close, entry+h)`` on market closes (T9).

    Entry is the first close on/after ``entry_date``; the horizon leg is
    the first close on/after ``entry_date + h``; the closed leg (when a
    parseable ``closed_date >= entry_date`` is given) is the first close
    on/after it. The realized exit is the earlier of the two legs. Either
    leg missing -> ``{"skipped": reason}`` (never forward-filled).
    """
    try:
        h = int(horizon_days)
    except (TypeError, ValueError):
        return {"skipped": "bad-horizon"}
    if h <= 0:
        return {"skipped": "bad-horizon"}
    try:
        entry_day = _parse(entry_date)
    except Exception:
        return {"skipped": "bad-entry-date"}
    e_date, e_close = _bars_on_or_after(stock_bars, entry_day.isoformat())
    if e_close is None:
        return {"skipped": "missing-stock-entry"}
    h_target = (entry_day + datetime.timedelta(days=h)).isoformat()
    x_date, x_close = _bars_on_or_after(stock_bars, h_target)
    c_date, c_close = None, None
    if closed_date:
        try:
            c_day = _parse(closed_date)
        except Exception:
            c_day = None
        if c_day is not None and c_day >= entry_day:
            c_date, c_close = _bars_on_or_after(stock_bars, c_day.isoformat())
    if x_close is None and c_close is None:
        return {"skipped": "missing-stock-exit"}
    if x_close is None:
        x_date, x_close = c_date, c_close
    elif (c_close is not None and c_date is not None
            and c_date <= (x_date or "9999-12-31")):
        x_date, x_close = c_date, c_close
    try:
        holding = (_parse(str(x_date)) - entry_day).days
    except Exception:
        holding = h
    return {"entry_date": e_date, "entry_close": e_close,
            "exit_date": x_date, "exit_close": x_close,
            "holding_days": holding}


def excess_for_entry(
    action: Any,
    entry_date: str,
    horizon_days: int,
    closed_date: Optional[str],
    symbol: str,
    stock_bars: List[Tuple[str, float]],
    peer_bars: Dict[str, List[Tuple[str, float]]],
    index_bars: List[Tuple[str, float]],
    cost: Optional[float] = None,
) -> Dict[str, Any]:
    """XS-matched + index-relative excess for one thesis entry (decimal).

    SELL legs are avoided-loss-vs-holding: both legs sign-flipped (mirroring
    ``horizon_excess`` direction semantics), so
    ``excess = stock_ret - control_ret - cost`` holds verbatim for BUY and
    SELL. The XS control is the equal-weight mean close of same-universe
    peers (excluding the entry symbol itself) over the SAME realized window;
    either leg missing -> ``{"skipped": reason}``.
    """
    c = pl.EXCESS_COST if cost is None else float(cost)
    act = str(action or "").strip().upper()
    if act not in ("BUY", "SELL"):
        return {"skipped": "hold-excluded" if act == "HOLD" else "bad-action"}
    rw = realized_window(stock_bars, entry_date, horizon_days, closed_date)
    if "skipped" in rw:
        return rw
    sym = str(symbol or "").strip().upper()
    e_date = str(rw["entry_date"])
    x_date = str(rw["exit_date"])
    e_close = float(rw["entry_close"])
    x_close = float(rw["exit_close"])
    if e_close <= 0 or x_close <= 0:
        return {"skipped": "missing-stock-entry"}
    xs_entry_vals: List[float] = []
    xs_exit_vals: List[float] = []
    norm_peers = {str(p).strip().upper(): b for p, b in (peer_bars or {}).items()}
    for p, bars in norm_peers.items():
        if p == sym:
            continue
        _, pe = _bars_on_or_after(bars, e_date)
        _, px = _bars_on_or_after(bars, x_date)
        if pe is None or px is None or pe <= 0 or px <= 0:
            continue
        xs_entry_vals.append(pe)
        xs_exit_vals.append(px)
    if not xs_entry_vals:
        return {"skipped": "missing-xs-control"}
    xs_e = sum(xs_entry_vals) / len(xs_entry_vals)
    xs_x = sum(xs_exit_vals) / len(xs_exit_vals)
    _, ie = _bars_on_or_after(index_bars or [], e_date)
    _, ix = _bars_on_or_after(index_bars or [], x_date)
    if ie is None or ix is None or ie <= 0 or ix <= 0:
        return {"skipped": "missing-index-exit"}
    direction = 1.0 if act == "BUY" else -1.0
    stock_ret = direction * (x_close / e_close - 1.0)
    xs_ret = direction * (xs_x / xs_e - 1.0)
    index_ret = direction * (ix / ie - 1.0)
    return {"stock_entry": e_close, "stock_exit": x_close,
            "exit_date": x_date, "holding_days": int(rw["holding_days"]),
            "stock_ret": stock_ret, "xs_ret": xs_ret, "index_ret": index_ret,
            "xs_excess": stock_ret - xs_ret - c,
            "index_excess": stock_ret - index_ret - c,
            "n_xs_peers": len(xs_entry_vals)}


def _cell_bps(stats: Dict[str, Any], pstats: Dict[str, Any]) -> Dict[str, Any]:
    ci = stats.get("clustered_ci")
    pci = (pstats or {}).get("ci")
    mean = stats.get("mean_excess")
    pmean = (pstats or {}).get("mean")
    return {
        "n": stats.get("n", 0),
        "cohorts": stats.get("cohorts", 0),
        "mean_excess_bps": _bps(mean),
        "clustered_mean_bps": _bps(stats.get("clustered_mean")),
        "clustered_se_bps": (None if stats.get("clustered_se") is None
                             else stats["clustered_se"] * 10000.0),
        "clustered_ci_bps": (None if not ci else
                             [ci[0] * 10000.0, ci[1] * 10000.0]),
        "hit": stats.get("hit_rate"),
        "hit_ci_lower": stats.get("hit_ci_lower"),
        "cohort_hit_ci_lower": stats.get("cohort_hit_ci_lower"),
        "cohort_means_bps": {w: v * 10000.0 for w, v in
                             (stats.get("cohort_means") or {}).items()},
        "placebo_n": (pstats or {}).get("n", 0),
        "placebo_mean_bps": _bps(pmean),
        "placebo_ci_bps": (None if not pci else
                           [pci[0] * 10000.0, pci[1] * 10000.0]),
        "placebo_hit_rate": (pstats or {}).get("hit_rate"),
        "placebo_delta_bps": (None if mean is None or pmean is None else
                              (mean - pmean) * 10000.0),
    }


def excess_4x4(
    entries: List[Dict[str, Any]],
    price_map: Dict[str, Dict[str, float]],
    index_map: Dict[str, Dict[str, float]],
    universe_of: Optional[Dict[str, Optional[str]]] = None,
    horizons: Optional[Tuple[int, ...]] = None,
    n_draws: int = DESK_PLACEBO_DRAWS,
    seed: int = DESK_PLACEBO_SEED,
    cost: Optional[float] = None,
    manager: Optional[Any] = None,
    quarantined: Optional[Any] = None,
    pool_start: Optional[str] = None,
) -> Dict[str, Any]:
    """4x4 excess grid: horizons x universes with cohorts + placebo.

    Primary leg is XS-matched (same-day cross-sectional control on the same
    population); ``index_relative`` carries the secondary index leg for
    comparison. Per cell: n, cohorts, clustered mean/CI (bps), hit rate
    with trade-level Wilson lower + cohort-robust hit lower, and the
    shuffle-entry-date placebo (same names, same realized holding, ~0
    required). Regime splits reuse the point-in-time trailing-50 Nifty 50
    close-vs-mean rule. Read-only; never writes.
    """
    hz = tuple(int(h) for h in (DESK_HORIZONS if horizons is None else horizons))
    if not hz or any(h <= 0 for h in hz):
        raise ValueError(
            "excess_4x4: horizons must be positive ints, got %r" % (horizons,))
    try:
        draws = int(n_draws)
    except (TypeError, ValueError):
        raise ValueError(
            "excess_4x4: n_draws must be a non-negative int, got %r" % (n_draws,))
    if draws < 0:
        raise ValueError(
            "excess_4x4: n_draws must be a non-negative int, got %r" % (n_draws,))
    c = pl.EXCESS_COST if cost is None else float(cost)
    wanted = [pl.UNIVERSE_INDEX[k]
              for k in ("nifty50", "midcap150", "smallcap250", "microcap250")]
    wanted_set = set(wanted)
    uni_of = {str(k).strip().upper(): (None if v is None else str(v))
              for k, v in (universe_of or {}).items()}
    qset = {str(s).strip().upper() for s in (quarantined or []) if str(s).strip()}
    stock_bars = {str(k).strip().upper(): v
                  for k, v in _bars_from_map(price_map).items()}
    index_bars = _bars_from_map(index_map)
    nifty_bars = index_bars.get(pl.UNIVERSE_INDEX["nifty50"], [])
    mgr = manager

    def _uni(sym: str) -> Optional[str]:
        u = uni_of.get(sym)
        if u is not None:
            return u if u in wanted_set else u
        if mgr is not None:
            try:
                return pl.resolve_action_universe(sym, mgr)
            except Exception:
                return None
        return None

    uni_symbols: Dict[str, List[str]] = {u: [] for u in wanted}
    for s in stock_bars:
        if s in qset:
            continue
        u = uni_of.get(s)
        if u is None and mgr is not None:
            try:
                u = pl.resolve_action_universe(s, mgr)
            except Exception:
                u = None
        if u in wanted_set:
            uni_symbols[u].append(s)

    skipped: Dict[str, int] = {}
    uncovered: set = set()
    metas: List[Dict[str, Any]] = []
    for e in entries or []:
        sym = str((e or {}).get("symbol") or "").strip().upper()
        act = str((e or {}).get("action") or "").strip().upper()
        if not sym:
            skipped["bad-action"] = skipped.get("bad-action", 0) + len(hz)
            continue
        if act not in ("BUY", "SELL"):
            skipped["hold-excluded" if act == "HOLD" else "bad-action"] = (
                skipped.get("hold-excluded" if act == "HOLD" else "bad-action",
                            0) + len(hz))
            continue
        if sym in qset:
            skipped["quarantined-excluded"] = skipped.get(
                "quarantined-excluded", 0) + len(hz)
            continue
        uni = _uni(sym)
        if uni is None:
            uncovered.add(sym)
            skipped["unmapped-universe"] = skipped.get(
                "unmapped-universe", 0) + len(hz)
            continue
        if uni not in wanted_set:
            skipped["universe-not-requested"] = skipped.get(
                "universe-not-requested", 0) + len(hz)
            continue
        try:
            entry_iso = _parse((e or {}).get("entry_date")).isoformat()
        except Exception:
            skipped["bad-entry-date"] = skipped.get("bad-entry-date", 0) + len(hz)
            continue
        closed_raw = (e or {}).get("closed_date")
        closed_iso: Optional[str] = None
        if closed_raw:
            try:
                closed_iso = _parse(closed_raw).isoformat()
            except Exception:
                closed_iso = None
        regime = pl._p1_regime_from_bars(entry_iso, nifty_bars)
        week = pl._week_monday(entry_iso)
        metas.append({"symbol": sym, "action": act, "entry_date": entry_iso,
                      "closed_date": closed_iso, "universe": uni,
                      "regime": regime, "week": week})

    real_xs: Dict[Tuple[str, int, str], List[Tuple[str, float]]] = {}
    real_idx: Dict[Tuple[str, int, str], List[Tuple[str, float]]] = {}
    hold_of: Dict[Tuple[int, int], Optional[int]] = {}
    for mi, m in enumerate(metas):
        sbars = stock_bars.get(m["symbol"], [])
        peers = {p: stock_bars[p] for p in uni_symbols.get(m["universe"], [])
                 if p in stock_bars}
        ibars = index_bars.get(m["universe"], [])
        for h in hz:
            res = excess_for_entry(m["action"], m["entry_date"], h,
                                   m["closed_date"], m["symbol"], sbars,
                                   peers, ibars, c)
            if "skipped" in res:
                skipped[str(res["skipped"])] = skipped.get(
                    str(res["skipped"]), 0) + 1
                hold_of[(mi, h)] = None
                continue
            real_xs.setdefault(
                (m["universe"], h, m["regime"]),
                []).append((m["week"], float(res["xs_excess"])))
            real_idx.setdefault(
                (m["universe"], h, m["regime"]),
                []).append((m["week"], float(res["index_excess"])))
            hold_of[(mi, h)] = int(res["holding_days"])

    pool_lo = _parse(pool_start).isoformat() if pool_start else DESK_START
    pools: Dict[str, List[str]] = {}
    for u in wanted:
        dates = [d for d, _ in index_bars.get(u, [])]
        hs = [hold_of[(mi, h)] for mi, m in enumerate(metas)
              if m["universe"] == u for h in hz
              if hold_of.get((mi, h)) is not None
              and hold_of[(mi, h)] is not None and hold_of[(mi, h)] >= 0]
        if not dates or not hs:
            pools[u] = []
            continue
        try:
            last = _parse(dates[-1])
            cutoff = (last - datetime.timedelta(days=max(hs))).isoformat()
        except Exception:
            pools[u] = []
            continue
        pools[u] = [d for d in dates if pool_lo <= d <= cutoff]

    rng = _random.Random(seed)
    placebo_xs: Dict[Tuple[str, int, str], List[float]] = {}
    placebo_idx: Dict[Tuple[str, int, str], List[float]] = {}
    placebo_skipped = 0
    order = sorted(range(len(metas)),
                   key=lambda i: (metas[i]["universe"],
                                  metas[i]["entry_date"], metas[i]["symbol"]))
    for mi in order:
        m = metas[mi]
        sbars = stock_bars.get(m["symbol"], [])
        peers = {p: stock_bars[p] for p in uni_symbols.get(m["universe"], [])
                 if p in stock_bars}
        ibars = index_bars.get(m["universe"], [])
        pool = pools.get(m["universe"], [])
        for h in hz:
            H = hold_of.get((mi, h))
            if H is None or H < 0 or not pool or not sbars or not ibars:
                placebo_skipped += draws
                continue
            for _ in range(draws):
                entry = rng.choice(pool)
                v = excess_for_entry(m["action"], entry, H, None,
                                     m["symbol"], sbars, peers, ibars, c)
                if "skipped" in v:
                    placebo_skipped += 1
                    continue
                preg = pl._p1_regime_from_bars(entry, nifty_bars)
                placebo_xs.setdefault((m["universe"], h, preg), []).append(
                    float(v["xs_excess"]))
                placebo_idx.setdefault((m["universe"], h, preg), []).append(
                    float(v["index_excess"]))

    cells: Dict[str, Dict[str, Any]] = {}
    for uni in wanted:
        cells[uni] = {}
        for h in hz:
            pooled_xs: List[Tuple[str, float]] = []
            pooled_idx: List[Tuple[str, float]] = []
            pall_xs: List[float] = []
            pall_idx: List[float] = []
            by_regime: Dict[str, Any] = {}
            by_regime_idx: Dict[str, Any] = {}
            for regime in ("uptrend", "drawdown", "unknown"):
                items = real_xs.get((uni, h, regime), [])
                iitems = real_idx.get((uni, h, regime), [])
                pooled_xs.extend(items)
                pooled_idx.extend(iitems)
                pvals = placebo_xs.get((uni, h, regime), [])
                ivals = placebo_idx.get((uni, h, regime), [])
                pall_xs.extend(pvals)
                pall_idx.extend(ivals)
                by_regime[regime] = _cell_bps(pl._p1_cell_stats(items),
                                             pl._p1_placebo_stats(pvals))
                by_regime_idx[regime] = _cell_bps(
                    pl._p1_cell_stats(iitems), pl._p1_placebo_stats(ivals))
            pooled = _cell_bps(pl._p1_cell_stats(pooled_xs),
                               pl._p1_placebo_stats(pall_xs))
            pooled["by_regime"] = by_regime
            pooled["regimes_present"] = sorted(
                {m["regime"] for m in metas if m["universe"] == uni
                 and real_xs.get((uni, h, m["regime"]))})
            pooled["index_relative"] = _cell_bps(
                pl._p1_cell_stats(pooled_idx),
                pl._p1_placebo_stats(pall_idx))
            pooled["index_relative"]["by_regime"] = by_regime_idx
            cells[uni][str(h)] = pooled

    per_universe_entries = {u: sum(1 for m in metas if m["universe"] == u)
                            for u in wanted}
    coverage = {
        "per_universe_n": {u: len(uni_symbols.get(u, [])) for u in wanted},
        "per_universe_entries": per_universe_entries,
        "unmapped": sorted(uncovered),
        "quarantined_excluded": sum(
            1 for e in entries or []
            if str((e or {}).get("symbol") or "").strip().upper() in qset),
        "n_entries": len(entries or []),
        "n_evaluated": len(metas),
        "placebo_seed": seed,
        "placebo_draws_per_entry_horizon": draws,
        "placebo_pool_start": pool_lo,
        "pool": {u: {"start": (pools[u][0] if pools[u] else None),
                     "end": (pools[u][-1] if pools[u] else None),
                     "n_dates": len(pools[u])} for u in wanted},
    }
    meta = {
        "generated_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "horizons": list(hz),
        "universes": wanted,
        "cost_netting": ("net of %.0fbps ASSUMED impact prior + STT "
                         "0.1%%/side + 5bps other (assumed) + FIFO taxes; "
                         "slippage audit replaces the prior"
                         % (c * 10000.0,)),
        "placebo_skipped": placebo_skipped,
    }
    notes = [
        ("Primary leg is XS-matched (same-day cross-sectional control on "
         "the same population); index_relative is the secondary leg for "
         "comparison only (carries benchmark bias)."),
        ("Real leg scores the min(closed, entry+h) realized window: on "
         "closed rows every horizon column can be identical by construction "
         "(T9 diagnostic — the horizon axis then carries no information)."),
        ("Placebo preserves each (entry, horizon) realized holding length "
         "with pure market-close windows; draws classify by the SHUFFLED "
         "date's point-in-time regime, so delta = entry skill, not window "
         "length. |placebo| <= 100bps counts as ~=0."),
        ("SELL legs are avoided-loss-vs-holding (both legs sign-flipped); "
         "the grid never books short-notional P&L."),
    ]
    return {"meta": meta, "cells": cells, "coverage": coverage,
            "skipped": skipped, "notes": notes}


def format_coverage_4x4(grid: Dict[str, Any]) -> str:
    """One-line-per-universe coverage footer + unmapped list (for tables)."""
    cov = (grid or {}).get("coverage", {})
    per_n = cov.get("per_universe_n", {}) or {}
    per_e = cov.get("per_universe_entries", {}) or {}
    lines = []
    for u in (grid or {}).get("meta", {}).get("universes", []) or sorted(per_n):
        lines.append("%s: n_symbols=%s n_entries=%s"
                     % (u, per_n.get(u, 0), per_e.get(u, 0)))
    lines.append("unmapped: %s" % (
        ", ".join(cov.get("unmapped", []) or []) or "none"))
    lines.append("quarantined_excluded: %s" % cov.get("quarantined_excluded", 0))
    lines.append("skipped: %s" % (cov.get("n_entries", 0) and
                                  (grid or {}).get("skipped", {}) or {}))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Strategy legs F1 / F2 / F3 (paper-only diagnosers; none promoted)
# ---------------------------------------------------------------------------

def f1_forensic_avoid(
    symbol: str,
    entry_date: str,
    features: Dict[str, Any],
    asof: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """F1 forensic-distress avoidance flag (paper only, fail-closed).

    Composite distress from PIT features (Gate0 solvency + Gate1 F1-F7:
    loss, leverage, growth-without-margin, margin collapse, F-5 score).
    Any feature whose ``asof`` postdates ``entry_date`` abstains (no leak);
    missing inputs abstain (HOLD), never pass.
    """
    sym = str(symbol or "").strip().upper()
    try:
        entry_iso = _parse(entry_date).isoformat()
    except Exception:
        return {"symbol": sym, "avoid": False, "reason": "bad-entry-date",
                "paper_only": True, "promoted": False}
    asof = dict(asof or {})
    for k, d in asof.items():
        try:
            if _parse(d).isoformat() > entry_iso:
                return {"symbol": sym, "entry_date": entry_iso,
                        "avoid": False, "reason": "pit-violation:%s" % (k,),
                        "paper_only": True, "promoted": False}
        except Exception:
            return {"symbol": sym, "entry_date": entry_iso,
                    "avoid": False, "reason": "bad-asof:%s" % (k,),
                    "paper_only": True, "promoted": False}
    f = dict(features or {})
    if not f:
        return {"symbol": sym, "entry_date": entry_iso, "avoid": False,
                "reason": "missing-inputs-abstain",
                "paper_only": True, "promoted": False}
    try:
        ni_neg = bool(f.get("ni_negative", False))
        de_high = bool(f.get("de_gt_1_5", False))
        sgi = bool(f.get("sgi_gt_1_5", False))
        mcol = bool(f.get("margin_collapse", False))
        ljump = bool(f.get("leverage_jump", False))
        f5 = f.get("f5_score")
        f5 = int(f5) if f5 is not None else None
    except (TypeError, ValueError):
        return {"symbol": sym, "entry_date": entry_iso, "avoid": False,
                "reason": "bad-features-abstain",
                "paper_only": True, "promoted": False}
    reasons = []
    if f5 is not None and f5 <= 1:
        reasons.append("F-5<=1")
    if ni_neg and mcol:
        reasons.append("loss+margin-collapse")
    if ni_neg and de_high:
        reasons.append("loss+DE>1.5")
    if de_high and ljump:
        reasons.append("leverage-jump")
    if sgi and mcol:
        reasons.append("growth-without-margin")
    avoid = bool(reasons)
    return {"symbol": sym, "entry_date": entry_iso, "avoid": avoid,
            "reason": "+".join(reasons) if reasons else "clean-or-flag-only",
            "paper_only": True, "promoted": False}


def f2_continuation_signal(
    symbol: str,
    entry_date: str,
    realized_pct: Any,
    sigma_pct: Any,
    prev_sign: Any,
    entry_sign: Any,
) -> Dict[str, Any]:
    """F2 vol-scaled continuation-momentum gate (paper only).

    Enters only genuine dislocations (``|realized| >= 2σ``) with factor
    agreement (``sign(prev-day) == sign(entry-day)``). Lone-residual,
    sub-2σ and reversal names stay out (T1/T3/T6).
    """
    sym = str(symbol or "").strip().upper()
    try:
        entry_iso = _parse(entry_date).isoformat()
    except Exception:
        return {"symbol": sym, "enter": False, "reason": "bad-entry-date",
                "paper_only": True, "promoted": False}
    r = _fnum(realized_pct)
    s = _fnum(sigma_pct)
    try:
        ps = int(prev_sign)
        es = int(entry_sign)
    except (TypeError, ValueError):
        ps, es = 0, 0
    if r is None or s is None or s <= 0:
        return {"symbol": sym, "entry_date": entry_iso, "enter": False,
                "reason": "bad-inputs", "paper_only": True, "promoted": False}
    dislocation = abs(r) / s
    agree = ps != 0 and ps == es
    enter = dislocation >= 2.0 and agree
    return {"symbol": sym, "entry_date": entry_iso, "enter": enter,
            "dislocation": dislocation, "factor_agree": agree,
            "reason": ("continuation" if enter else
                       ("sub-2σ" if dislocation < 2.0 else "no-factor-agree")),
            "paper_only": True, "promoted": False}


def f2_kill(net_30d_bps: Any, bar_bps: float = 500.0) -> Dict[str, Any]:
    """F2 pre-registered kill rule: 30D net < +500bps => kill, no k-tuning."""
    v = _fnum(net_30d_bps)
    bar = float(bar_bps)
    kill = True if v is None else v < bar
    return {"kill": kill, "net_30d_bps": v, "bar_bps": bar,
            "paper_only": True, "promoted": False}


def f3_carry_allocation(
    regime: Any,
    quality_ok: Any,
    max_names: int = 40,
) -> Dict[str, Any]:
    """F3 regime-carry allocation (paper only; sizing gated post-bar).

    RISK-OFF arms the 40% defensive sleeve; RISK-ON holds 0-10%. Unproven
    carry never sizes here — weight is diagnostic only.
    """
    reg = str(regime or "").strip().upper()
    ok = bool(quality_ok)
    if reg == "RISK-OFF":
        sleeve = SWEEP_MAX_FRACTION
    elif reg == "RISK-ON":
        sleeve = 0.10
    else:
        sleeve = SWEEP_MAX_FRACTION
    return {"regime": reg or "UNKNOWN", "quality_ok": ok,
            "weight": (1.0 / max(1, int(max_names)) if ok else 0.0),
            "sleeve_fraction": sleeve if ok else SWEEP_MAX_FRACTION,
            "paper_only": True, "promoted": False}


# ---------------------------------------------------------------------------
# Artifact builder + harness wiring
# ---------------------------------------------------------------------------

def build_desk_artifact(
    book: Optional[Dict[str, Any]] = None,
    grid: Optional[Dict[str, Any]] = None,
    market: Optional[Dict[str, Any]] = None,
    strategies: Tuple[str, ...] = ("F1", "F2", "F3"),
) -> Dict[str, Any]:
    """Assemble the desk output artifact (JSON-serialisable)."""
    sched = [{"effective_from": str(r.get("effective_from")),
              "stcg_rate": float(r.get("stcg_rate")),
              "ltcg_rate": float(r.get("ltcg_rate")),
              "ltcg_exempt": float(r.get("ltcg_exempt"))}
             for r in sb.TAX_SCHEDULE]
    meta = {
        "generated_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "desk_start": DESK_START,
        "initial_cash": DESK_INITIAL_CASH,
        "horizons": list(DESK_HORIZONS),
        "universes": [pl.UNIVERSE_INDEX[k] for k in
                      ("nifty50", "midcap150", "smallcap250", "microcap250")],
        "price_convention": ("close usable iff finite>0 from "
                             "daily_price_delivery; trades at closes only; "
                             "no fwd-fill for trading; valuation carries "
                             "last close"),
        "cost_schedule": {
            "source": "sip_backtest TAX_SCHEDULE (Finance (No. 2) Act 2024)",
            "regimes": sched,
            "ltcg_min_hold_days": sb.LTCG_MIN_HOLD_DAYS,
            "stt_buy_rate": sb.STT_BUY_RATE,
            "stt_sell_rate": sb.STT_SELL_RATE,
            "other_charge_rate": sb.OTHER_CHARGE_RATE,
            "other_charges_assumed": True,
            "impact_prior": pl.EXCESS_COST,
            "impact_prior_assumed": True,
            "fy_exemption_tracking": True,
            "cross_year_carry": False,
        },
        "sector_cap": DESK_SECTOR_CAP,
        "sweep_max": SWEEP_MAX_FRACTION,
        "risk_free": RISK_FREE_RATE,
        "fractional_shares": "backtest-only",
        "sell_scoring": "avoided-loss-vs-holding primary; short-excess "
                        "secondary in grid only",
        "sell_framing": "target<entry<stop asserted at write; abort on violation",
        "bootstrap_weights": dict(DESK_BOOTSTRAP_WEIGHTS),
        "quarantine_predicate": QUARANTINE_PREDICATE,
        "breadth_start": DESK_BREADTH_START,
    }
    book_summary = None
    if book is not None:
        nav = book.get("nav_daily") or []
        book_summary = {
            "contributions": book.get("contributions"),
            "nav_last": nav[-1]["nav_post"] if nav else None,
            "nav_last_date": nav[-1]["date"] if nav else None,
            "taxes_paid": book.get("taxes_paid"),
            "tax_by_fy": book.get("tax_by_fy"),
            "post_tax_xirr": book.get("post_tax_xirr"),
            "pre_tax_xirr": book.get("pre_tax_xirr"),
            "max_dd": book.get("max_dd"),
            "drawdown": book.get("drawdown"),
            "sharpe": book.get("sharpe"),
            "sortino": book.get("sortino"),
            "n_buys": book.get("n_buys"),
            "n_sells": book.get("n_sells"),
            "n_harvest_sells": book.get("n_harvest_sells"),
            "n_sweep_buys": book.get("n_sweep_buys"),
            "flags": book.get("flags"),
        }
    coverage = None
    if grid is not None:
        coverage = grid.get("coverage")
    elif market is not None:
        coverage = market.get("coverage")
    return {
        "meta": meta,
        "book_summary": book_summary,
        "cells": (grid or {}).get("cells"),
        "coverage": coverage,
        "skipped": (grid or {}).get("skipped"),
        "drawdown": (book or {}).get("drawdown"),
        "strategies": {s: dict(STRATEGY_STATUS.get(s, {"paper_only": True,
                                                       "promoted": False}))
                       for s in strategies},
        "scope_caveats": [
            "F1/F2/F3 paper only; none promoted (CEO verdict: NO live edge).",
            "Book before %s is equal-weight closes (flagged)." % DESK_BREADTH_START,
            "Fractional shares are backtest-only; live sizes whole shares.",
            "5bps other charges + 50bps impact are ASSUMED priors until the "
            "slippage audit lands.",
            "No cross-year loss carry-forward modelled; FY exemption tracked "
            "within the run.",
            "Risk-free rate 0 throughout; k_target=3/k_stop=1 fixed "
            "(sensitivity +/-1 in appendix only).",
            "Small/micro cells need call-row coverage (hierarchical "
            "shrinkage stays BLOCKED until it lands).",
            "Blended positional-pnl + HOLD-agreement win rates are never "
            "quoted as hit rates.",
        ],
        "notes": (grid or {}).get("notes", []),
    }


def save_desk_artifact(artifact: Dict[str, Any], path: Any) -> str:
    """Persist a desk artifact as JSON (the module's only writer)."""
    import json as _json
    dest = Path(str(path))
    if dest.parent and str(dest.parent) not in ("", "."):
        dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_json.dumps(artifact, indent=2, sort_keys=True,
                                default=str), encoding="utf-8")
    return str(dest)


def run_desk_backtest(
    manager: Optional[Any] = None,
    thesis_fn: Optional[ThesisFn] = None,
    symbols: Optional[List[str]] = None,
    start: str = DESK_START,
    end: Optional[str] = None,
    save_to: Optional[Any] = None,
    n_draws: int = DESK_PLACEBO_DRAWS,
    seed: int = DESK_PLACEBO_SEED,
    **book_kwargs: Any,
) -> Dict[str, Any]:
    """Wire market load -> lump-sum book -> 4x4 grid -> artifact.

    Read-only on the DB (SELECTs only; never touches ledger tables); the
    only write is the optional artifact file via ``save_to``.
    """
    mkt = load_desk_market(manager, symbols=symbols, start=start, end=end)
    book = run_desk_book(
        mkt["symbols"], mkt["price_map"], mkt["sector_map"],
        mkt["trading_days"], thesis_fn=thesis_fn,
        universe_map=mkt["universe_map"], start=start, end=end,
        **book_kwargs)
    grid = excess_4x4(book.get("entries_log", []), mkt["price_map"],
                      mkt["index_map"], mkt["universe_map"],
                      n_draws=n_draws, seed=seed)
    artifact = build_desk_artifact(book=book, grid=grid, market=mkt)
    artifact["coverage_footer"] = format_coverage_4x4(grid)
    if save_to is not None:
        artifact["artifact_path"] = save_desk_artifact(artifact, save_to)
    return artifact
