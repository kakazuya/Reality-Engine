"""
SIP signal legs (Leg A / Leg B) over the shared SIP/tax/metrics engine.

Scope (stated, not hidden — see module docstring caveat):
  * The 2021-2026 attribution spine is factor/technical-only by construction.
    P0 book rows span 2026-08-17 -> 09-18 and F1 attribution votes span
    2026-06-29 -> 09-23, so any pre-2026-08 signal-vs-benchmark delta is a
    factor/technical-only delta, NOT a multi-lens delta.
  * Leg A (P0-signal rotation): monthly rebalance tilts toward BUY names
    where P0 signals exist; falls back to benchmark (equal) weights outside
    the signal window or when no fresh BUY vote exists.
  * Leg B (F1 broken-thesis fade, paper): SELL-side avoidance — skips names
    with a fresh broken-thesis vote where votes exist (fresh SELL action,
    fresh quality/supply -1 attribution vote, or standing snapshot
    quality-broken substrate), redistributing over the survivors.

Ownership: the SIP schedule, FIFO tax lots, STT+charges, sector caps, cash
buffer, monthly EOD rebalance, and rolling/metrics engine live in
``reality_engine.processing.sip_backtest`` (owned by SIPBench). This module
owns ONLY the signal maps + weights_fn closures + the delta report. The
engine is imported lazily inside :func:`signal_vs_benchmark_report` so this
module (and its tests) work before/after the engine lands.

Read-only, except the report's optional JSON artifact write. Quarantined
synthetic masters (``substrate_quarantine`` / ``INE_AUTO_*``) are excluded
from every signal read, never deleted (AGENTS.md rule 13).
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("reality_engine.sip_signals")

#: First calendar month in which P0/F1 signals exist. Rebalance dates before
#: this fall back to benchmark weights (documented, not silent).
SIGNAL_WINDOW_START: str = "2026-08-01"

#: Lookback (calendar days) for a BUY/SELL/attribution vote to count as
#: "fresh" at a monthly rebalance date. Point-in-time: only votes with
#: vote_date in (rebalance - lookback, rebalance] apply.
VOTE_LOOKBACK_DAYS: int = 30

#: Leg A tilt: a fresh-BUY name gets this multiple of a non-BUY name's score
#: before normalization. Assumption, stated in every artifact's notes.
LEG_A_TILT: float = 2.0

#: Scope caveat stamped on every artifact this module produces. Any
#: 2021-2025 leg-vs-benchmark delta is factor/technical-only, not multi-lens.
SCOPE_CAVEAT: str = (
    "SCOPE: P0 book rows span 2026-08-17->09-18 and F1 attribution votes "
    "span 2026-06-29->09-23 only. The 2021-2026 attribution spine is "
    "factor/technical-only by construction, so any pre-2026-08 "
    "signal-vs-benchmark delta is factor/technical-only, NOT multi-lens. "
    "No multi-lens claim is made for pre-2026 years."
)

#: Cost caveat: round-trip cost is the engine's 50bps ASSUMED prior
#: (slippage audit is tracker backlog #6) — repeated here so leg artifacts
#: never look cheaper than the assumption.
COST_CAVEAT: str = (
    "COSTS: 50bps round-trip is an ASSUMED prior (flagged unmeasured); "
    "see the engine artifact flags for the applied schedule."
)


@dataclass
class SignalMaps:
    """Pre-read, point-in-time-safe signal votes (all ISO date strings)."""

    #: action/attribution date -> BUY symbols (portfolio_actions, N50-agnostic)
    buy_by_date: Dict[str, Set[str]] = field(default_factory=dict)
    #: action date -> SELL symbols (fresh broken-thesis exit votes)
    sell_by_date: Dict[str, Set[str]] = field(default_factory=dict)
    #: attribution date -> symbols with a fresh supply_chain -1 vote
    supply_neg_by_date: Dict[str, Set[str]] = field(default_factory=dict)
    #: attribution date -> symbols with a fresh business_quality -1 vote
    quality_neg_by_date: Dict[str, Set[str]] = field(default_factory=dict)
    #: symbol -> reason for STANDING snapshot quality-broken substrate
    #: (moat-only; ENI unobservable without screener lookups — flagged).
    #: Single-snapshot, NOT point-in-time: applied as a standing exclusion.
    quality_broken: Dict[str, str] = field(default_factory=dict)
    #: Read metadata for audit (quarantined excluded, vote counts, window).
    meta: Dict[str, Any] = field(default_factory=dict)


def _resolve_manager(manager: Optional[Any]) -> Any:
    if manager is not None:
        return manager
    from reality_engine.db.database import db_manager

    return db_manager


def _table_exists(conn: Any, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
            is not None
        )
    except Exception:
        return False


def _norm_sym(sym: Any) -> str:
    return str(sym or "").strip().upper()


def _parse_day(day: Any) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat(str(day or "").strip()[:10])
    except (TypeError, ValueError):
        return None


def load_signal_maps(manager: Optional[Any] = None) -> SignalMaps:
    """Read all signal votes (read-only, quarantine-excluded).

    * BUY/SELL votes from ``portfolio_actions`` (P0 book, 2026-08-17 ->).
    * supply -1 / quality -1 votes from ``move_attribution`` lens dirs
      (live: supply -1 is 0 rows, quality -1 is 0 rows — recorded honestly
      in ``meta``; the fade then rests on SELL + snapshot quality).
    * Standing quality-broken set from ``moat_evaluations`` via the shared
      :func:`move_attributor.quality_broken_reason` (moat-only; ENI=None
      never fires — flagged, not hidden). Single-snapshot substrate, so
      this component is a standing exclusion, not a fresh signal.
    Missing tables yield empty maps (graceful, never crash).
    """
    from reality_engine.processing.move_attributor import (
        quality_broken_reason as _quality_broken_reason,
    )

    try:
        from reality_engine.processing.portfolio_ledger import (
            quarantined_master_symbols as _quarantined,
        )
    except Exception:
        _quarantined = None  # type: ignore[assignment]

    maps = SignalMaps()
    mgr = _resolve_manager(manager)
    quarantined: Set[str] = set()
    try:
        with mgr.session() as conn:
            if not _table_exists(conn, "master_companies"):
                maps.meta = {"empty": "no master_companies table"}
                return maps
            if _quarantined is not None:
                try:
                    quarantined = set(_quarantined(conn) or set())
                except Exception:
                    quarantined = set()

            n_buy_votes = 0
            n_sell_votes = 0
            if _table_exists(conn, "portfolio_actions"):
                try:
                    rows = conn.execute(
                        "SELECT symbol, action, action_date FROM portfolio_actions "
                        "WHERE action IN ('BUY','SELL')"
                    ).fetchall()
                except Exception as exc:
                    logger.debug("sip_signals book read failed: %s", exc)
                    rows = []
                for r in rows:
                    try:
                        sym = _norm_sym(r["symbol"])
                        act = str(r["action"] or "").strip().upper()
                        day = str(r["action_date"] or "").strip()[:10]
                    except Exception:
                        continue
                    if not sym or sym in quarantined or not day:
                        continue
                    if act == "BUY":
                        maps.buy_by_date.setdefault(day, set()).add(sym)
                        n_buy_votes += 1
                    elif act == "SELL":
                        maps.sell_by_date.setdefault(day, set()).add(sym)
                        n_sell_votes += 1

            n_supply_neg = 0
            n_quality_neg = 0
            if _table_exists(conn, "move_attribution"):
                try:
                    arows = conn.execute(
                        "SELECT symbol, attribution_date, "
                        "lens_supply_chain_dir, lens_business_quality_dir "
                        "FROM move_attribution "
                        "WHERE lens_supply_chain_dir = -1 "
                        "OR lens_business_quality_dir = -1"
                    ).fetchall()
                except Exception as exc:
                    logger.debug("sip_signals attribution read failed: %s", exc)
                    arows = []
                for r in arows:
                    try:
                        sym = _norm_sym(r["symbol"])
                        day = str(r["attribution_date"] or "").strip()[:10]
                        sdir = int(r["lens_supply_chain_dir"] or 0)
                        qdir = int(r["lens_business_quality_dir"] or 0)
                    except Exception:
                        continue
                    if not sym or sym in quarantined or not day:
                        continue
                    if sdir == -1:
                        maps.supply_neg_by_date.setdefault(day, set()).add(sym)
                        n_supply_neg += 1
                    if qdir == -1:
                        maps.quality_neg_by_date.setdefault(day, set()).add(sym)
                        n_quality_neg += 1

            n_broken = 0
            if _table_exists(conn, "moat_evaluations"):
                try:
                    mrows = conn.execute(
                        "SELECT ticker, total_moat_score, moat_trajectory "
                        "FROM moat_evaluations"
                    ).fetchall()
                except Exception as exc:
                    logger.debug("sip_signals moat read failed: %s", exc)
                    mrows = []
                for r in mrows:
                    try:
                        sym = _norm_sym(r["ticker"])
                    except Exception:
                        continue
                    if not sym or sym in quarantined:
                        continue
                    try:
                        broken, reason = _quality_broken_reason(
                            r["moat_trajectory"], r["total_moat_score"], None
                        )
                    except Exception:
                        continue
                    if broken:
                        maps.quality_broken[sym] = str(reason or "broken")
                        n_broken += 1
    except Exception as exc:
        logger.debug("sip_signals load failed: %s", exc)

    maps.meta = {
        "signal_window_start": SIGNAL_WINDOW_START,
        "vote_lookback_days": VOTE_LOOKBACK_DAYS,
        "quarantined_excluded": len(quarantined),
        "n_buy_votes": n_buy_votes,
        "n_sell_votes": n_sell_votes,
        "n_supply_neg_votes": n_supply_neg,
        "n_quality_neg_votes": n_quality_neg,
        "n_quality_broken_snapshot": n_broken,
        "quality_broken_is_snapshot_not_pit": True,
        "policy_eni_unobservable_here": True,
    }
    return maps


def _votes_in_window(
    by_date: Dict[str, Set[str]], asof: datetime.date, lookback: int = VOTE_LOOKBACK_DAYS
) -> Set[str]:
    """Symbols with a vote date in (asof - lookback, asof] (PIT-safe)."""
    cutoff = (asof - datetime.timedelta(days=lookback)).isoformat()
    end = asof.isoformat()
    out: Set[str] = set()
    for day, syms in by_date.items():
        if cutoff < str(day) <= end:
            out |= set(syms)
    return out


def active_buy_set(maps: SignalMaps, asof: Any) -> Set[str]:
    """Fresh BUY symbols at ``asof`` (empty outside the signal window)."""
    day = _parse_day(asof)
    if day is None or day.isoformat() < SIGNAL_WINDOW_START:
        return set()
    return _votes_in_window(maps.buy_by_date, day)


def active_fade_set(maps: SignalMaps, asof: Any) -> Set[str]:
    """Fresh-avoidance symbols at ``asof`` (empty outside the window).

    Union of fresh SELL votes, fresh supply -1 / quality -1 attribution
    votes, and the STANDING snapshot quality-broken set (the snapshot
    component is window-independent by construction — flagged in meta).
    """
    day = _parse_day(asof)
    if day is None or day.isoformat() < SIGNAL_WINDOW_START:
        return set()
    out = _votes_in_window(maps.sell_by_date, day)
    out |= _votes_in_window(maps.supply_neg_by_date, day)
    out |= _votes_in_window(maps.quality_neg_by_date, day)
    out |= set(maps.quality_broken or {})
    return out


def weights_for_rebalance(
    symbols: List[Any],
    asof: Any,
    mode: str,
    maps: SignalMaps,
) -> Dict[str, float]:
    """Normalized ``{SYMBOL: weight}`` for one rebalance date (pure, no I/O).

    * ``"A"`` — P0 rotation: fresh-BUY names score ``LEG_A_TILT``, others
      1.0; no fresh BUYs (or pre-window) -> equal weights = benchmark.
    * ``"B"`` — F1 fade: faded names score 0.0, survivors share equally;
      empty fade set, or fade covering everything -> equal weights.
    * anything else -> equal weights (benchmark).
    Empty symbol list -> ``{}``. Scores always normalize to sum 1.0.
    """
    syms = [_norm_sym(s) for s in (symbols or [])]
    syms = [s for s in syms if s]
    if not syms:
        return {}
    n = len(syms)
    m = str(mode or "").strip().upper()
    if m == "A":
        buys = active_buy_set(maps, asof) & set(syms)
        if not buys:
            return {s: 1.0 / n for s in syms}
        scores = {s: (LEG_A_TILT if s in buys else 1.0) for s in syms}
    elif m == "B":
        faded = active_fade_set(maps, asof) & set(syms)
        survivors = [s for s in syms if s not in faded]
        if not faded or not survivors:
            return {s: 1.0 / n for s in syms}
        share = 1.0 / len(survivors)
        return {s: (share if s in survivors else 0.0) for s in syms}
    else:
        return {s: 1.0 / n for s in syms}
    total = sum(scores.values())
    if not total:
        return {s: 1.0 / n for s in syms}
    return {s: v / total for s, v in scores.items()}


def make_weights_fn(
    symbols: List[Any],
    mode: str,
    maps: SignalMaps,
) -> Callable[[Any, Any], float]:
    """Engine ``weights_fn`` closure: ``(symbol, date) -> weight``.

    Binds the rebalance universe + mode + pre-read maps; the engine calls
    it per (symbol, date) and applies its own sector caps/cash handling.
    Unknown symbols score 0.0 (engine cash-holds them).
    """
    syms = [_norm_sym(s) for s in (symbols or [])]
    syms = [s for s in syms if s]
    cache: Dict[str, Dict[str, float]] = {}

    def _fn(symbol: Any, date: Any) -> float:
        day = _parse_day(date)
        key = day.isoformat() if day is not None else str(date or "")[:10]
        weights = cache.get(key)
        if weights is None:
            weights = weights_for_rebalance(syms, key, mode, maps)
            cache[key] = weights
        return float(weights.get(_norm_sym(symbol), 0.0))

    _fn.mode = str(mode or "").strip().upper()  # type: ignore[attr-defined]
    _fn.symbols = list(syms)  # type: ignore[attr-defined]
    return _fn


def _num(artifact: Any, *keys: str, default: float = float("nan")) -> float:
    node: Any = artifact
    for k in keys:
        if isinstance(node, dict) and k in node:
            node = node[k]
        else:
            return default
    try:
        v = float(node)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return v


def _post_tax_delta(leg: Dict[str, Any], bench: Dict[str, Any]) -> Dict[str, Any]:
    """Post-tax leg-vs-benchmark delta (pp / % where stated)."""
    try:
        leg_final = leg["nav_daily"][-1]["nav_post"] if leg.get("nav_daily") else float("nan")
        bench_final = bench["nav_daily"][-1]["nav_post"] if bench.get("nav_daily") else float("nan")
    except (TypeError, ValueError, KeyError, IndexError):
        leg_final, bench_final = float("nan"), float("nan")
    return {
        "d_post_tax_xirr_pp": (_num(leg, "post_tax_xirr") - _num(bench, "post_tax_xirr")) * 100.0,
        "d_pre_tax_xirr_pp": (_num(leg, "pre_tax_xirr") - _num(bench, "pre_tax_xirr")) * 100.0,
        "d_final_nav_post_tax_pct": _pct(leg_final, bench_final),
        "d_taxes_paid": _num(leg, "taxes_paid") - _num(bench, "taxes_paid"),
        "d_max_dd_pp": (_num(leg, "max_dd", "max_dd") - _num(bench, "max_dd", "max_dd")) * 100.0,
        "scope": "post-tax; pre-2026-08 component is factor/technical-only",
    }


def _pct(a: float, b: float) -> float:
    try:
        if b == 0 or a != a or b != b:  # NaN check without math import
            return float("nan")
        return (a / b - 1.0) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return float("nan")


def signal_vs_benchmark_report(
    manager: Optional[Any] = None,
    symbols: Optional[List[Any]] = None,
    start: str = "2021-10-27",
    end: Optional[str] = None,
    out_path: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run benchmark + Leg A + Leg B on the shared engine; report deltas.

    Same SIP schedule, costs, sector caps, cash buffer, and tax engine for
    all three legs (engine-owned). Returns ``{benchmark, leg_a, leg_b,
    deltas, scope_caveat, notes, signal_meta}``; optionally persists JSON
    to ``out_path``. The engine import is lazy — raises RuntimeError with
    a clear message when ``sip_backtest`` has not landed yet.
    """
    try:
        from reality_engine.processing.sip_backtest import (  # type: ignore[import]
            SIP_END,
            load_market,
            run_benchmark,
            run_sip,
        )
    except Exception as exc:
        raise RuntimeError(
            "signal_vs_benchmark_report requires "
            "reality_engine.processing.sip_backtest (engine not landed yet)"
        ) from exc

    end_iso = end or SIP_END
    market = load_market(manager, symbols=symbols, start=start, end=end_iso)
    syms = list(market.get("symbols") or [])
    maps = load_signal_maps(manager)

    bench = run_benchmark(
        syms,
        market.get("price_map"),
        market.get("sector_map"),
        market.get("trading_days"),
        start=start,
        end=end_iso,
    )
    leg_a = run_sip(
        syms,
        market.get("price_map"),
        market.get("sector_map"),
        market.get("trading_days"),
        weights_fn=make_weights_fn(syms, "A", maps),
        start=start,
        end=end_iso,
    )
    leg_b = run_sip(
        syms,
        market.get("price_map"),
        market.get("sector_map"),
        market.get("trading_days"),
        weights_fn=make_weights_fn(syms, "B", maps),
        start=start,
        end=end_iso,
    )

    artifact: Dict[str, Any] = {
        "benchmark": bench,
        "leg_a_p0_rotation": leg_a,
        "leg_b_f1_fade": leg_b,
        "deltas_vs_benchmark_post_tax": {
            "leg_a_p0_rotation": _post_tax_delta(leg_a, bench),
            "leg_b_f1_fade": _post_tax_delta(leg_b, bench),
        },
        "scope_caveat": SCOPE_CAVEAT,
        "cost_caveat": COST_CAVEAT,
        "notes": [
            "Leg A tilts %.1fx toward fresh-BUY names where P0 votes exist, "
            "else benchmark weights (see weights_for_rebalance)." % LEG_A_TILT,
            "Leg B skips fresh SELL / supply -1 / quality -1 names plus "
            "standing snapshot quality-broken names where votes exist.",
            "Live vote census: supply -1 rows = %s, quality -1 rows = %s; "
            "when both are 0 the F1 fade rests on SELL + snapshot quality."
            % (
                maps.meta.get("n_supply_neg_votes"),
                maps.meta.get("n_quality_neg_votes"),
            ),
            "Quality-broken is single-snapshot moat substrate (ENI "
            "unobservable here) — a standing exclusion, not a fresh signal.",
        ],
        "signal_meta": maps.meta,
        "market_flags": market.get("flags"),
    }
    if out_path is not None:
        import json as _json
        from pathlib import Path as _Path

        dest = _Path(str(out_path))
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(_json.dumps(artifact, indent=2, default=str))
            artifact["artifact_path"] = str(dest)
        except Exception as exc:
            logger.warning("sip_signals artifact write failed: %s", exc)
    return artifact
