"""
Slice 3 — Portfolio/ROC ledger + calibration feedback
(tasks/next_wave_attribution.md §2 Slice 3).

Portfolio accounting over thesis actions plus the calibration feedback that
drives learned weights back into ``model_explainer_rankings``. This closes
the loop: residual → calibration → weights → next attribution.

Ownership: this module owns ONLY the ``portfolio_actions`` table (own DDL,
precedent: ``skill_loop.ensure_schema``). It CALLS ``skill_loop.run_folds`` /
``skill_loop.apply_if_improved`` and ``Repository.upsert_validation_scores`` —
it never reimplements them, never edits those modules, and never touches
``model_explainer_rankings`` directly.

Conventions (deterministic, no invented magnitudes):
* ``pnl_pct`` / ``unrealized_pct`` are PERCENT units (×100), consistent with
  ``daily_price_delivery.change_pct`` and Slice 1 ``realized_move_pct``.
* BUY is a long position (direction +1), SELL a short-equivalent cash-exit
  position (direction −1): ``pnl = direction × (exit/entry − 1) × 100``.
* Sessions are trading days counted per symbol over dates actually present
  in ``daily_price_delivery`` — calendar days are never assumed.
* Stop is checked BEFORE target on each bar (conservative: a same-bar touch
  of both counts as stopped out), mirroring ``validation_harness`` thesis
  scoring. High/low fall back to close when absent.
* An open BUY/SELL with no reachable target/stop (or NULL levels) closes
  only on the 60-session horizon.
* HOLDs are non-positional (no capital at risk, ``pnl_pct`` always 0.0).
  A HOLD resolves once 5 forward sessions are observable and is scored by
  directional agreement (see :func:`summarize`).
"""

from __future__ import annotations

import datetime
import logging
import math
import random as _random
import statistics as _statistics
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("reality_engine.portfolio_ledger")

#: Actions this ledger records. BUY/SELL open capital-at-risk positions;
#: HOLD is non-positional and exists so the hit-rate denominator is honest.
ACTIONS: Tuple[str, ...] = ("BUY", "SELL", "HOLD")

#: Forward sessions after which an open BUY/SELL is force-closed at the
#: latest close.
HORIZON_SESSIONS: int = 60

#: Forward sessions after which a HOLD resolves. Matches the default
#: calibration ``horizon_days`` so HOLD windows and learning windows agree.
HOLD_WINDOW_SESSIONS: int = 5

#: Vol-scaled bracket rule (P0 honest book; GARCH is a P3 refinement).
#: Brackets scale with the trailing-20-session population std of
#: close-to-close % moves (same history rule as the Slice 1 noise floor):
#: BUY target = entry x (1 + 3σ), BUY stop = entry x (1 - 1σ); SELL
#: mirrors (target below entry, stop above). σ is clamped to [0.5, 8.0]
#: percent points (<5 sessions falls back to 2.0), so the target width
#: spans [1.5%, 24%] and the stop [0.5%, 8%] — a ~3:1 risk-reward that
#: varies per name instead of the old fixed 18%/6%.
BRACKET_LOOKBACK: int = 20
BRACKET_MIN_SESSIONS: int = 5
BRACKET_SIGMA_FALLBACK_PCT: float = 2.0
BRACKET_SIGMA_MIN_PCT: float = 0.5
BRACKET_SIGMA_MAX_PCT: float = 8.0
BRACKET_TARGET_SIGMA_MULT: float = 3.0
BRACKET_STOP_SIGMA_MULT: float = 1.0

#: Mode tag for portfolio aggregate rows in ``model_validation_scores``.
#: Namespaced so ensemble folds (``mode="ensemble"``) never see them.
PORTFOLIO_SCORES_MODE: str = "portfolio"

_PORTFOLIO_DDL = """
CREATE TABLE IF NOT EXISTS portfolio_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('BUY','SELL','HOLD')),
    action_date TEXT NOT NULL,
    entry_price REAL,
    target_price REAL,
    stop_loss REAL,
    thesis_ref TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    closed_date TEXT,
    exit_price REAL,
    pnl_pct REAL,
    UNIQUE(symbol, action_date, action)
);
"""

_PORTFOLIO_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_portfolio_status_date "
    "ON portfolio_actions(status, action_date)"
)


def _resolve_manager(manager: Optional[Any]) -> Any:
    """Return the given manager, else the live default (lazy import)."""
    if manager is not None:
        return manager
    from reality_engine.db.database import db_manager
    return db_manager


def ensure_portfolio_schema(manager: Optional[Any] = None) -> None:
    """Create the ``portfolio_actions`` ledger + status/date index. Idempotent."""
    mgr = _resolve_manager(manager)
    with mgr.session() as conn:
        conn.execute(_PORTFOLIO_DDL)
        conn.execute(_PORTFOLIO_INDEX)


def _fnum(x: Any) -> Optional[float]:
    """Finite float or None (None / garbage / NaN / ±inf → None)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _sign(x: Any) -> int:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def _table_exists(conn: Any, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def quarantined_master_symbols(conn: Any) -> set:
    """Symbols whose master row carries a quarantined synthetic ISIN.

    Joins ``master_companies`` against ``substrate_quarantine`` (the trust
    layer materializes ``synthetic_isin_companies`` there as
    ``(table_name='master_companies', row_key=isin)``), plus a defensive
    ``LIKE 'INE_AUTO%'`` fallback when the trust layer was never applied.
    Read-only; empty set when either table is absent. Never deletes rows.
    """
    out: set = set()
    try:
        if not _table_exists(conn, "master_companies"):
            return set()
        try:
            cols = {c[1] for c in conn.execute(
                "PRAGMA table_info('master_companies')").fetchall()}
        except Exception:
            cols = set()
        sym_col = "nse_symbol" if "nse_symbol" in cols else (
            "symbol" if "symbol" in cols else None)
        if sym_col is None:
            return set()
        rows = conn.execute(
            f"SELECT isin, {sym_col} AS sym FROM master_companies").fetchall()
    except Exception as exc:
        logger.debug("quarantine master scan failed: %s", exc)
        return set()
    auto = {str(r["isin"]).strip() for r in rows if str(r["isin"] or "").startswith("INE_AUTO")}
    qkeys: set = set()
    try:
        if _table_exists(conn, "substrate_quarantine"):
            qrows = conn.execute(
                "SELECT row_key FROM substrate_quarantine "
                "WHERE table_name = 'master_companies'").fetchall()
            qkeys = {str(r[0]).strip() for r in qrows if r[0] is not None}
    except Exception as exc:
        logger.debug("quarantine key scan failed: %s", exc)
    bad_isins = auto | {k for k in qkeys if k.startswith("INE_AUTO") or k in auto}
    # A quarantined row_key is the synthetic ISIN; also honor any row_key
    # that directly names a symbol (defensive: trust-layer key_expr drift).
    name_keys = {k.upper() for k in qkeys if not k.startswith("INE")}
    for r in rows:
        try:
            isin = str(r["isin"] or "").strip()
            sym = str(r["sym"] or "").strip().upper()
        except Exception:
            continue
        if not sym:
            continue
        if isin in bad_isins or sym in name_keys:
            out.add(sym)
    return out


def _trailing_sigma_pct(conn: Any, symbol: str, asof_date: str) -> float:
    """Trailing-20-session population std of close-to-close % moves.

    Same history rule as the Slice 1 noise floor: sessions with
    ``date <= asof_date`` ordered DESC, limit 20; per-session move from
    (close, prev_close) falling back to ``change_pct``; <5 sessions falls
    back to 2.0; clamped to [0.5, 8.0] percent points. Read-only.
    """
    import statistics as _stats
    try:
        rows = conn.execute(
            "SELECT close, prev_close, change_pct FROM daily_price_delivery "
            "WHERE symbol = ? AND date <= ? ORDER BY date DESC LIMIT ?",
            (symbol, asof_date, BRACKET_LOOKBACK),
        ).fetchall()
    except Exception as exc:
        logger.debug("bracket history lookup for %s failed: %s", symbol, exc)
        return BRACKET_SIGMA_FALLBACK_PCT
    moves = []
    for r in rows:
        try:
            c, p = r["close"], r["prev_close"]
            if c is not None and p is not None and float(p) != 0.0:
                v = (float(c) - float(p)) / float(p) * 100.0
                if math.isfinite(v):
                    moves.append(float(v))
                    continue
        except (TypeError, ValueError):
            pass
        try:
            v = float(r["change_pct"])
            if math.isfinite(v):
                moves.append(float(v))
        except (TypeError, ValueError):
            continue
    if len(moves) < BRACKET_MIN_SESSIONS:
        return BRACKET_SIGMA_FALLBACK_PCT
    try:
        sigma = float(_stats.pstdev(moves))
    except Exception:
        return BRACKET_SIGMA_FALLBACK_PCT
    if not math.isfinite(sigma):
        return BRACKET_SIGMA_FALLBACK_PCT
    return max(BRACKET_SIGMA_MIN_PCT, min(BRACKET_SIGMA_MAX_PCT, sigma))


def bracket_for_entry(entry_price: float, sigma_pct: float, action: str) -> Dict[str, float]:
    """Pure bracket math: entry x (1 +/- k x sigma), mirrored for SELL.

    BUY => ``target > entry > stop``; SELL => ``target < entry < stop``.
    ``sigma_pct`` is clamped to [0.5, 8.0]; entry must be finite and > 0.
    Returns ``{target_price, stop_loss, sigma_pct, target_width_pct,
    stop_width_pct}`` (widths in percent of entry). Raises ValueError on
    bad entry/action.
    """
    entry = _fnum(entry_price)
    if entry is None or entry <= 0:
        raise ValueError(f"bracket_for_entry: entry must be finite > 0, got {entry_price!r}")
    act = str(action or "").strip().upper()
    if act not in ("BUY", "SELL"):
        raise ValueError(f"bracket_for_entry: action must be BUY or SELL, got {action!r}")
    try:
        sig = float(sigma_pct)
    except (TypeError, ValueError):
        sig = BRACKET_SIGMA_FALLBACK_PCT
    if not math.isfinite(sig):
        sig = BRACKET_SIGMA_FALLBACK_PCT
    sig = max(BRACKET_SIGMA_MIN_PCT, min(BRACKET_SIGMA_MAX_PCT, sig))
    tw = BRACKET_TARGET_SIGMA_MULT * sig / 100.0
    sw = BRACKET_STOP_SIGMA_MULT * sig / 100.0
    if act == "BUY":
        target = round(entry * (1.0 + tw), 2)
        stop = round(entry * (1.0 - sw), 2)
    else:
        target = round(entry * (1.0 - tw), 2)
        stop = round(entry * (1.0 + sw), 2)
    if stop <= 0:
        raise ValueError(f"bracket_for_entry: stop underflow for entry={entry} sigma={sig}")
    return {"target_price": target, "stop_loss": stop, "sigma_pct": sig,
            "target_width_pct": tw * 100.0, "stop_width_pct": sw * 100.0}


def vol_scaled_bracket(symbol: str, entry_price: float, action: str,
                       asof_date: str, manager: Optional[Any] = None,
                       conn: Optional[Any] = None) -> Dict[str, float]:
    """Trailing-sigma bracket for one (symbol, entry) at ``asof_date``.

    Reads up to 20 sessions of ``daily_price_delivery`` history at/before
    ``asof_date`` (never forward), then applies :func:`bracket_for_entry`.
    Pass an open ``conn`` to reuse the caller's session, else ``manager``.
    SELL mirrors (target below entry, stop above).
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        raise ValueError("vol_scaled_bracket requires a symbol")
    if conn is not None:
        sigma = _trailing_sigma_pct(conn, sym, str(asof_date))
        return bracket_for_entry(entry_price, sigma, action)
    mgr = _resolve_manager(manager)
    with mgr.session() as c:
        sigma = _trailing_sigma_pct(c, sym, str(asof_date))
    return bracket_for_entry(entry_price, sigma, action)



def _check_framing_invariant(act: str, entry: Optional[float],
                             target: Optional[float], stop: Optional[float]) -> None:
    """Enforce the honest-book framing invariant (P0; SELL = avoided loss).

    BUY => target > entry > stop; SELL => target < entry < stop; HOLD =>
    target and stop None (non-positional; a legacy entry level is tolerated
    for already-written rows but never used for scoring). Partial levels on
    BUY/SELL are allowed (a leg with no reachable target/stop closes only
    on the 60-session horizon) but any two present legs must already frame
    the right way. Raises ValueError on violation.
    """
    if act == "HOLD":
        if target is not None or stop is not None:
            raise ValueError(
                "record_action: HOLD is non-positional; target/stop must be None, "
                f"got target={target!r} stop={stop!r}")
        return
    if act == "BUY":
        if target is not None and entry is not None and not target > entry:
            raise ValueError(
                f"record_action: BUY requires target > entry, got target={target!r} entry={entry!r}")
        if entry is not None and stop is not None and not entry > stop:
            raise ValueError(
                f"record_action: BUY requires entry > stop, got entry={entry!r} stop={stop!r}")
        if target is not None and stop is not None and not target > stop:
            raise ValueError(
                f"record_action: BUY requires target > stop, got target={target!r} stop={stop!r}")
        return
    if act == "SELL":
        if target is not None and entry is not None and not target < entry:
            raise ValueError(
                f"record_action: SELL requires target < entry, got target={target!r} entry={entry!r}")
        if entry is not None and stop is not None and not entry < stop:
            raise ValueError(
                f"record_action: SELL requires entry < stop, got entry={entry!r} stop={stop!r}")
        if target is not None and stop is not None and not target < stop:
            raise ValueError(
                f"record_action: SELL requires target < stop, got target={target!r} stop={stop!r}")
        return


def record_action(
    symbol: str,
    action: str,
    action_date: str,
    entry_price: Optional[float],
    target_price: Optional[float],
    stop_loss: Optional[float],
    thesis_ref: Optional[str] = None,
    manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """Record one thesis action. Idempotent via UNIQUE(symbol, action_date, action).

    Framing invariant (P0 honest book, SELL = avoided-loss-vs-holding in the
    cash segment): BUY => target > entry > stop; SELL => target < entry <
    stop; HOLD => target/stop None (non-positional, ``pnl_pct`` 0.0 on
    resolution; a legacy entry level is tolerated but never scored). BUY/SELL
    open positions closed later by :func:`mark_to_market`. A framing violation
    raises ValueError before any write, except a re-record of an existing
    (symbol, date, action) which returns the stored row unchanged.
    """
    sym = str(symbol or "").strip().upper()
    act = str(action or "").strip().upper()
    if not sym:
        raise ValueError("record_action requires a symbol")
    if act not in ACTIONS:
        raise ValueError(f"record_action: action must be one of {ACTIONS}, got {action!r}")
    ad = str(action_date or "").strip()
    if not ad:
        raise ValueError("record_action requires an action_date 'YYYY-MM-DD'")

    def _level(name: str, v: Any) -> Optional[float]:
        if v is None:
            return None
        f = _fnum(v)
        if f is None or f <= 0:
            raise ValueError(f"record_action: {name} must be a finite price > 0, got {v!r}")
        return f
    entry = _level("entry_price", entry_price)
    target = _level("target_price", target_price)
    stop = _level("stop_loss", stop_loss)

    mgr = _resolve_manager(manager)
    ensure_portfolio_schema(mgr)
    with mgr.session() as conn:
        existing = conn.execute(
            "SELECT * FROM portfolio_actions WHERE symbol = ? AND action_date = ? AND action = ?",
            (sym, ad, act),
        ).fetchone()
        if existing is not None:
            return dict(existing)
        _check_framing_invariant(act, entry, target, stop)
        conn.execute(
            "INSERT INTO portfolio_actions "
            "(symbol, action, action_date, entry_price, target_price, stop_loss, thesis_ref) "
            "VALUES (?,?,?,?,?,?,?)",
            (sym, act, ad, entry, target, stop, thesis_ref),
        )
        row = conn.execute(
            "SELECT * FROM portfolio_actions WHERE symbol = ? AND action_date = ? AND action = ?",
            (sym, ad, act),
        ).fetchone()
        return dict(row)


def _load_forward_bars(
    conn: Any, symbol: str, after_date: str, asof_date: str
) -> List[Dict[str, Any]]:
    """Ascending usable bars for ``symbol`` in (after_date, asof_date].

    A bar is usable when its close is finite and > 0; high/low fall back to
    close when absent, mirroring ``validation_harness`` bar loading.
    """
    rows = conn.execute(
        "SELECT date, close, high, low FROM daily_price_delivery "
        "WHERE symbol = ? AND date > ? AND date <= ? ORDER BY date ASC",
        (symbol, after_date, asof_date),
    ).fetchall()
    bars: List[Dict[str, Any]] = []
    for r in rows:
        close = _fnum(r["close"])
        if close is None or close <= 0:
            continue
        hi = _fnum(r["high"])
        lo = _fnum(r["low"])
        bars.append({
            "date": str(r["date"]),
            "close": close,
            "high": close if hi is None else hi,
            "low": close if lo is None else lo,
        })
    return bars


def mark_to_market(asof_date: str, manager: Optional[Any] = None) -> Dict[str, Any]:
    """Revalue open positions vs ``daily_price_delivery`` closes ≤ ``asof_date``.

    For each open BUY/SELL with a usable entry and at least one forward bar,
    walks forward bars in order: stop is checked before target on each bar;
    SELL triggers are mirrored (stop when high ≥ stop, target when low ≤
    target) under the framing invariant (SELL => target < entry < stop, so
    a SELL stop-out exits ABOVE entry and books avoided-loss-vs-holding
    correctly). A position still open after the walk closes at the latest
    close once more than ``HORIZON_SESSIONS`` (60) forward sessions exist.
    HOLDs resolve (status closed, ``pnl_pct`` 0.0, exit = 5th forward close)
    once ``HOLD_WINDOW_SESSIONS`` (5) forward sessions exist.

    Quarantined masters (``substrate_quarantine`` synthetic ``INE_AUTO_*``
    rows) are skipped: their rows stay open and untouched, never deleted.
    Pure price lookup + own-table writes only. Returns
    ``{marked, closed, open_pnl_sum}`` where ``marked`` counts open BUY/SELL
    actually revalued (forward price found), ``closed`` counts rows closed by
    this call (positions and HOLD resolutions), and ``open_pnl_sum`` is the
    Σ unrealized pct over positions still open afterwards (0.0 when none).
    """
    asof = str(asof_date or "").strip()
    if not asof:
        raise ValueError("mark_to_market requires an asof_date 'YYYY-MM-DD'")
    mgr = _resolve_manager(manager)
    ensure_portfolio_schema(mgr)
    marked = 0
    closed = 0
    open_pnl = 0.0
    with mgr.session() as conn:
        try:
            quarantined = quarantined_master_symbols(conn)
        except Exception:
            quarantined = set()
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM portfolio_actions WHERE status = 'open' ORDER BY action_id"
        ).fetchall()]
        if quarantined:
            rows = [r for r in rows
                    if str(r.get("symbol") or "").strip().upper() not in quarantined]
        bars_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for r in rows:
            sym = r["symbol"]
            ad = r["action_date"]
            key = (sym, ad)
            if key not in bars_cache:
                try:
                    bars_cache[key] = _load_forward_bars(conn, sym, ad, asof)
                except Exception as exc:
                    logger.debug("MTM bar load failed for %s: %s", sym, exc)
                    bars_cache[key] = []
            bars = bars_cache[key]
            if r["action"] == "HOLD":
                if len(bars) >= HOLD_WINDOW_SESSIONS:
                    res = bars[HOLD_WINDOW_SESSIONS - 1]
                    conn.execute(
                        "UPDATE portfolio_actions SET status = 'closed', closed_date = ?, "
                        "exit_price = ?, pnl_pct = 0.0 WHERE action_id = ?",
                        (res["date"], res["close"], r["action_id"]),
                    )
                    closed += 1
                continue
            entry = _fnum(r["entry_price"])
            if entry is None or entry <= 0 or not bars:
                continue
            marked += 1
            direction = 1.0 if r["action"] == "BUY" else -1.0
            target = _fnum(r["target_price"])
            stop = _fnum(r["stop_loss"])
            exit_px: Optional[float] = None
            exit_date: Optional[str] = None
            for b in bars:
                if r["action"] == "BUY":
                    stop_hit = stop is not None and b["low"] <= stop
                    tgt_hit = target is not None and b["high"] >= target
                else:  # SELL: mirrored triggers
                    stop_hit = stop is not None and b["high"] >= stop
                    tgt_hit = target is not None and b["low"] <= target
                if stop_hit:
                    exit_px, exit_date = stop, b["date"]
                    break
                if tgt_hit:
                    exit_px, exit_date = target, b["date"]
                    break
            if exit_px is None:
                if len(bars) > HORIZON_SESSIONS:
                    exit_px, exit_date = bars[-1]["close"], bars[-1]["date"]
                else:
                    open_pnl += direction * (bars[-1]["close"] / entry - 1.0) * 100.0
                    continue
            pnl = direction * (exit_px / entry - 1.0) * 100.0
            conn.execute(
                "UPDATE portfolio_actions SET status = 'closed', closed_date = ?, "
                "exit_price = ?, pnl_pct = ? WHERE action_id = ?",
                (exit_date, exit_px, pnl, r["action_id"]),
            )
            closed += 1
    return {"marked": marked, "closed": closed, "open_pnl_sum": open_pnl}


def _empty_summary() -> Dict[str, Any]:
    return {
        "open_count": 0,
        "closed_count": 0,
        "win_rate": None,
        "mean_pnl": None,
        "total_pnl": 0.0,
        "by_action": {a: {"count": 0, "closed": 0, "wins": 0, "hit": None} for a in ACTIONS},
    }


def _load_attribution_map(conn: Any) -> Dict[Tuple[str, str], Tuple[Any, Any]]:
    """(symbol, date) -> (realized_move_pct, residual) from Slice 1 ledger.

    Defensive: missing table or any error yields {} (HOLDs then score 0.0 —
    conservative, unresolved = miss, mirroring ``validation_harness``).
    Read-only; never creates anything.
    """
    try:
        if not _table_exists(conn, "move_attribution"):
            return {}
        out: Dict[Tuple[str, str], Tuple[Any, Any]] = {}
        for r in conn.execute(
            "SELECT symbol, attribution_date, realized_move_pct, residual FROM move_attribution"
        ).fetchall():
            out[(str(r["symbol"]), str(r["attribution_date"]))] = (
                r["realized_move_pct"], r["residual"])
        return out
    except Exception as exc:
        logger.debug("attribution map load failed: %s", exc)
        return {}


def _hold_win_score(row: Dict[str, Any], attrib: Dict[Tuple[str, str], Tuple[Any, Any]]) -> float:
    """Agreement score for one closed HOLD (see :func:`summarize`)."""
    if not attrib:
        return 0.0
    key = (str(row["symbol"]), str(row["action_date"]))
    if key not in attrib:
        return 0.0
    realized, resid = attrib[key]
    entry = _fnum(row["entry_price"])
    exit_px = _fnum(row["exit_price"])
    if entry is None or entry <= 0 or exit_px is None or exit_px <= 0:
        return 0.0
    s_res = _sign(_sign(realized) * (_fnum(resid) or 0.0))
    s_fwd = _sign(exit_px / entry - 1.0)
    if s_res == s_fwd:
        return 1.0
    if s_fwd == 0:
        return 0.5  # flat forward print vindicates a HOLD
    return 0.0


def summarize(manager: Optional[Any] = None) -> Dict[str, Any]:
    """Read-only book summary: ``{open_count, closed_count, win_rate,
    mean_pnl, total_pnl, by_action}``.

    * ``win_rate`` = (positional wins with ``pnl_pct`` > 0 + HOLD agreement
      wins) / all closed rows; None when nothing is closed.
    * ``mean_pnl`` / ``total_pnl`` are over closed BUY/SELL only
      (capital-at-risk basis; HOLDs risk nothing and score 0.0 by
      construction). ``mean_pnl`` is None when no position is closed;
      ``total_pnl`` is 0.0 when empty. Percent units.
    * ``by_action`` maps each of BUY/SELL/HOLD to
      ``{count, closed, wins, hit}``; ``count`` covers open+closed rows,
      ``hit`` is wins/closed (None when none resolved).

    HOLD win (deterministic, signs only — no invented magnitudes): a
    resolved HOLD (5 forward sessions observed, status closed) scores 1.0
    when the direction of the unexplained component —
    ``sign(realized_move_pct) × residual`` from the Slice 1
    ``move_attribution`` ledger — agrees with the direction of the HOLD's
    own 5-session forward move ``(exit_price/entry_price − 1)``; an exactly
    flat forward print scores 0.5; missing attribution evidence (or missing
    entry/exit) scores 0.0.

    Never writes: when ``portfolio_actions`` is absent it returns zeros
    without creating anything (safe as a live-DB probe). Quarantined
    masters (``substrate_quarantine`` synthetic ``INE_AUTO_*`` rows) are
    excluded from every count, never deleted.
    """
    mgr = _resolve_manager(manager)
    with mgr.session() as conn:
        if not _table_exists(conn, "portfolio_actions"):
            return _empty_summary()
        rows = [dict(r) for r in conn.execute("SELECT * FROM portfolio_actions").fetchall()]
        try:
            quarantined = quarantined_master_symbols(conn)
        except Exception:
            quarantined = set()
        if quarantined:
            rows = [r for r in rows
                    if str(r.get("symbol") or "").strip().upper() not in quarantined]
        if not rows:
            return _empty_summary()
        attrib: Dict[Tuple[str, str], Tuple[Any, Any]] = {}
        if any(r["action"] == "HOLD" and r["status"] == "closed" for r in rows):
            attrib = _load_attribution_map(conn)

        open_count = sum(1 for r in rows if r["status"] == "open")
        closed_rows = [r for r in rows if r["status"] == "closed"]
        pos = [r for r in closed_rows if r["action"] in ("BUY", "SELL")]
        holds = [r for r in closed_rows if r["action"] == "HOLD"]

        pos_wins = 0
        pos_pnls: List[float] = []
        for r in pos:
            pnl = _fnum(r["pnl_pct"])
            if pnl is None:
                continue
            pos_pnls.append(pnl)
            if pnl > 0:
                pos_wins += 1
        hold_scores = [_hold_win_score(r, attrib) for r in holds]
        wins = float(pos_wins) + sum(hold_scores)
        n_closed = len(closed_rows)
        by_action: Dict[str, Dict[str, Any]] = {}
        for a in ACTIONS:
            recs = [r for r in rows if r["action"] == a]
            cl = [r for r in recs if r["status"] == "closed"]
            if a == "HOLD":
                w = sum(_hold_win_score(r, attrib) for r in cl)
            else:
                w = float(sum(
                    1 for r in cl
                    if (_fnum(r["pnl_pct"]) is not None and _fnum(r["pnl_pct"]) > 0)))
            by_action[a] = {
                "count": len(recs),
                "closed": len(cl),
                "wins": w,
                "hit": (w / len(cl)) if cl else None,
            }
        return {
            "open_count": open_count,
            "closed_count": n_closed,
            "win_rate": (wins / n_closed) if n_closed else None,
            "mean_pnl": (sum(pos_pnls) / len(pos_pnls)) if pos_pnls else None,
            "total_pnl": float(sum(pos_pnls)),
            "by_action": by_action,
        }


def publish_portfolio_scores(
    manager: Optional[Any] = None,
    asof_date: Optional[str] = None,
    horizon_days: int = 5,
) -> int:
    """Persist book aggregates via ``Repository.upsert_validation_scores``.

    One whole-cohort row under ``mode="portfolio"`` (namespaced so ensemble
    folds never see it): ``n``/``thesis_n`` = closed count,
    ``hit_rate``/``thesis_hit_rate`` = win rate, ``mean_fwd_ret`` = mean
    positional pnl in percent units. Writes nothing when nothing is closed.
    Returns the repo rowcount (0 when skipped).
    """
    mgr = _resolve_manager(manager)
    s = summarize(mgr)
    if not s["closed_count"]:
        return 0
    asof = str(asof_date or "").strip() or datetime.datetime.now(
        datetime.timezone.utc).date().isoformat()
    record = {
        "asof_date": asof,
        "horizon_days": int(horizon_days),
        "mode": PORTFOLIO_SCORES_MODE,
        "lens_family": None,
        "regime_tag": "unknown",
        "investor_majority": "all",
        "n": int(s["closed_count"]),
        "hit_rate": s["win_rate"],
        "mean_fwd_ret": s["mean_pnl"],
        "universe_mean_ret": None,
        "ic": None,
        "thesis_hit_rate": s["win_rate"],
        "thesis_n": int(s["closed_count"]),
    }
    from reality_engine.db.repository import Repository
    return int(Repository(mgr).upsert_validation_scores([record]))


def run_attribution_calibration(
    manager: Optional[Any] = None,
    mode: str = "ensemble",
    horizon_days: int = 5,
) -> Dict[str, Any]:
    """Run one attribution-calibration round and gate learned weights.

    1. Publishes current portfolio aggregates to ``model_validation_scores``
       (feedback in).
    2. Calls ``skill_loop.run_folds`` (``persist=False`` — reporting only,
       so rounds are persisted exactly once) for the observable round
       summary.
    3. Calls ``skill_loop.apply_if_improved`` — the existing gate — which
       re-runs the identical folds, persists them, and applies the fitted
       weights into ``model_explainer_rankings`` ONLY on out-of-sample
       improvement. The gate is the safety: this function never touches
       ``model_explainer_rankings`` directly.

    Returns the round summary dict (folds detail included) enriched with
    ``applied`` (bool), ``scores_published`` (int), plus ``weights`` /
    ``calibration`` when applied or ``reason`` when not.
    """
    from reality_engine.processing import skill_loop as sl

    mgr = _resolve_manager(manager)
    ensure_portfolio_schema(mgr)
    published = publish_portfolio_scores(
        mgr, horizon_days=int(horizon_days))
    with mgr.session() as conn:
        summary = sl.run_folds(
            conn, mode=mode, horizon_days=int(horizon_days), persist=False)
    with mgr.session() as conn:
        gate = sl.apply_if_improved(
            conn, mode=mode, horizon_days=int(horizon_days))
    out = dict(summary)
    out["applied"] = bool(gate.get("applied"))
    out["scores_published"] = int(published)
    if out["applied"]:
        out["weights"] = gate.get("weights")
        out["calibration"] = gate.get("calibration")
    else:
        out["reason"] = gate.get("reason", "no out-of-sample improvement")
    return out


# ====================================================================
# Horizon excess vs universe index (goal-loop iteration 1).
#
# ADDITIVE annex: nothing above this line is modified. HOLDs are excluded
# from excess throughout (non-positional, they carry no entry levels),
# mirroring the ``mark_to_market`` HOLD non-positional rule documented at
# module top.
# ====================================================================

#: Short universe key -> ``nse_index_breadth.index_name``. All four names
#: verified present in ``nse_index_breadth``.
UNIVERSE_INDEX: Dict[str, str] = {
    "nifty50": "Nifty 50",
    "midcap150": "Nifty Midcap 150",
    "smallcap250": "Nifty Smallcap 250",
    "microcap250": "Nifty Microcap 250",
}

#: Full index name -> short universe key.
INDEX_TO_UNIVERSE: Dict[str, str] = {v: k for k, v in UNIVERSE_INDEX.items()}

#: Default calendar-day forward horizons for the goal loop.
HORIZON_DEFAULTS: Tuple[int, ...] = (30, 90, 180, 365)

#: Round-trip market-impact haircut, decimal units (50 bps).
EXCESS_COST: float = 0.005


def resolve_action_universe(symbol: str, manager: Optional[Any] = None) -> Optional[str]:
    """Map a stock symbol to its universe index breadth name.

    Rule (frozen contract): ``master_companies.is_nifty50 = 1`` ->
    ``'Nifty 50'``; else ``market_cap_tier`` MID -> ``'Nifty Midcap 150'``,
    SMALL -> ``'Nifty Smallcap 250'``, MICRO -> ``'Nifty Microcap 250'``.
    Anything else (LARGE non-nifty50, NULL/unknown tier, unknown symbol,
    missing table) returns None: the action is uncovered, never force-fit.
    Read-only; never creates anything.
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    mgr = _resolve_manager(manager)
    try:
        with mgr.session() as conn:
            if not _table_exists(conn, "master_companies"):
                return None
            row = conn.execute(
                "SELECT is_nifty50, market_cap_tier FROM master_companies "
                "WHERE nse_symbol = ?",
                (sym,),
            ).fetchone()
    except Exception as exc:
        logger.debug("universe lookup failed for %s: %s", sym, exc)
        return None
    if row is None:
        return None
    try:
        is_nifty = int(row["is_nifty50"]) == 1
    except (TypeError, ValueError):
        is_nifty = bool(row["is_nifty50"])
    if is_nifty:
        return UNIVERSE_INDEX["nifty50"]
    tier = str(row["market_cap_tier"] or "").strip().upper()
    if tier == "MID":
        return UNIVERSE_INDEX["midcap150"]
    if tier == "SMALL":
        return UNIVERSE_INDEX["smallcap250"]
    if tier == "MICRO":
        return UNIVERSE_INDEX["microcap250"]
    return None


def _stock_close_on_or_after(
    conn: Any, symbol: str, target: str
) -> Tuple[Optional[str], Optional[float]]:
    """(date, close) of the first usable stock close on/after ``target``."""
    row = conn.execute(
        "SELECT date, close FROM daily_price_delivery "
        "WHERE symbol = ? AND date >= ? ORDER BY date ASC LIMIT 1",
        (symbol, target),
    ).fetchone()
    if row is None:
        return None, None
    close = _fnum(row["close"])
    if close is None or close <= 0:
        return None, None
    return str(row["date"]), close


def _index_close_on_or_after(
    conn: Any, index_name: str, target: str
) -> Tuple[Optional[str], Optional[float]]:
    """(date, close) of the first usable index close on/after ``target``."""
    row = conn.execute(
        "SELECT date, close FROM nse_index_breadth "
        "WHERE index_name = ? AND date >= ? ORDER BY date ASC LIMIT 1",
        (index_name, target),
    ).fetchone()
    if row is None:
        return None, None
    close = _fnum(row["close"])
    if close is None or close <= 0:
        return None, None
    return str(row["date"]), close


def horizon_excess(
    action_row: Dict[str, Any],
    horizon_days: int,
    manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """Index-relative excess for one BUY/SELL action at one calendar-day horizon.

    Entry/exit are market closes, symmetric on both legs (the index leg has
    no thesis level, so thesis ``entry_price`` is deliberately unused):
    entry is the first available close ON OR AFTER ``action_date``. For open
    positions the exit is the first available close ON OR AFTER
    ``action_date + horizon_days`` (stock leg from
    ``daily_price_delivery``, index leg from ``nse_index_breadth``). When
    the action row is closed (a parseable ``closed_date``, set by
    ``mark_to_market`` on stop/target exits), the exit is
    ``min(closed leg, horizon leg)`` where the closed leg is the first
    stock close on/after ``closed_date``. Rationale: stopped-out positions
    score their realized window vs the index over the SAME window (both
    legs share the resolved exit date), not a buy-and-hold window past
    the stop. Either leg missing -> ``{"skipped": reason}`` (never
    forward-filled, never crash).

    Returns ``{stock_entry, stock_exit, exit_date, stock_ret, index_name,
    index_entry, index_exit, index_ret, excess}`` in DECIMAL units (note:
    unlike ``mark_to_market``/``summarize`` percent units, the 50 bps
    haircut ``0.005`` is decimal). ``exit_date`` is the resolved stock exit
    date; the index exit is the first index close on/after that same date,
    so both legs share the window and no filling is done to align them.

    SELL legs are short-notional: both ``stock_ret`` and ``index_ret`` are
    sign-flipped (mirroring ``mark_to_market`` direction semantics), so
    ``excess = stock_ret - index_ret - 0.005`` holds verbatim for BUY and
    SELL. HOLDs always return ``{"skipped": "hold-excluded"}`` — they are
    non-positional and carry no entry levels.
    """
    row = dict(action_row or {})
    action = str(row.get("action") or "").strip().upper()
    if action == "HOLD":
        return {"skipped": "hold-excluded"}
    if action not in ("BUY", "SELL"):
        return {"skipped": "bad-action"}
    try:
        horizon = int(horizon_days)
    except (TypeError, ValueError):
        return {"skipped": "bad-horizon"}
    if horizon <= 0:
        return {"skipped": "bad-horizon"}
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol:
        return {"skipped": "bad-action"}
    try:
        entry_day = datetime.date.fromisoformat(
            str(row.get("action_date") or "").strip())
    except ValueError:
        return {"skipped": "bad-action-date"}
    entry_iso = entry_day.isoformat()
    target_iso = (entry_day + datetime.timedelta(days=horizon)).isoformat()

    mgr = _resolve_manager(manager)
    with mgr.session() as conn:
        index_name = resolve_action_universe(symbol, mgr)
        if index_name is None:
            return {"skipped": "unmapped-universe"}
        if not _table_exists(conn, "daily_price_delivery"):
            return {"skipped": "missing-stock-entry"}
        _, stock_entry = _stock_close_on_or_after(conn, symbol, entry_iso)
        if stock_entry is None:
            return {"skipped": "missing-stock-entry"}
        exit_date, stock_exit = _stock_close_on_or_after(conn, symbol, target_iso)
        closed_raw = str(row.get("closed_date") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        if closed_raw and (status == "closed" or status == ""):
            try:
                closed_day = datetime.date.fromisoformat(closed_raw[:10])
            except ValueError:
                closed_day = None
            if closed_day is not None and closed_day >= entry_day:
                c_date, c_close = _stock_close_on_or_after(
                    conn, symbol, closed_day.isoformat())
                if (c_close is not None and c_date is not None
                        and (exit_date is None or c_date <= exit_date)):
                    exit_date, stock_exit = c_date, c_close
        if stock_exit is None:
            return {"skipped": "missing-stock-exit"}
        if not _table_exists(conn, "nse_index_breadth"):
            return {"skipped": "missing-index-entry"}
        _, index_entry = _index_close_on_or_after(conn, index_name, entry_iso)
        if index_entry is None:
            return {"skipped": "missing-index-entry"}
        _, index_exit = _index_close_on_or_after(
            conn, index_name, exit_date if exit_date is not None else target_iso)
        if index_exit is None:
            return {"skipped": "missing-index-exit"}
    direction = 1.0 if action == "BUY" else -1.0
    stock_ret = direction * (stock_exit / stock_entry - 1.0)
    index_ret = direction * (index_exit / index_entry - 1.0)
    return {
        "stock_entry": stock_entry,
        "stock_exit": stock_exit,
        "exit_date": exit_date,
        "stock_ret": stock_ret,
        "index_name": index_name,
        "index_entry": index_entry,
        "index_exit": index_exit,
        "index_ret": index_ret,
        "excess": stock_ret - index_ret - EXCESS_COST,
    }


def _normalize_universe_names(universes: Optional[List[Any]]) -> List[str]:
    """Short keys or full index names -> ordered full index names.

    None means all four legs in canonical order. Unknown keys raise
    ValueError (fail fast on typos instead of silently dropping a leg).
    """
    if universes is None:
        return [UNIVERSE_INDEX[k]
                for k in ("nifty50", "midcap150", "smallcap250", "microcap250")]
    out: List[str] = []
    for u in universes:
        s = str(u or "").strip()
        if s in UNIVERSE_INDEX:
            full = UNIVERSE_INDEX[s]
        elif s in INDEX_TO_UNIVERSE:
            full = s
        else:
            raise ValueError(
                f"excess_table: unknown universe {u!r}; expected one of "
                f"{sorted(UNIVERSE_INDEX)} or {sorted(INDEX_TO_UNIVERSE)}")
        if full not in out:
            out.append(full)
    return out


def _week_monday(date_str: Any) -> str:
    """Monday (ISO) of the week containing ``date_str``; 'unknown' if unparsable."""
    try:
        day = datetime.date.fromisoformat(str(date_str or "").strip())
    except ValueError:
        return "unknown"
    return (day - datetime.timedelta(days=day.weekday())).isoformat()


def excess_table(
    horizons: Tuple[int, ...] = HORIZON_DEFAULTS,
    universes: Optional[List[Any]] = None,
    manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """Group CLOSED BUY/SELL actions by (universe, horizon) with excess stats.

    Each cell is ``{n, mean_excess, hit_rate_excess_gt0, cohorts}`` where
    ``hit_rate_excess_gt0`` is the fraction with excess > 0 and ``cohorts``
    maps the action-date Monday (ISO) to ``{n, mean_excess}``. ``n`` counts
    actions whose BOTH legs resolved; skipped (action, horizon) pairs are
    counted under ``skipped`` by reason, never crash, never filled.
    HOLDs are excluded (non-positional, no entry levels). Unmappable
    actions count under ``uncovered_actions`` (and per-horizon
    ``unmapped-universe`` skips), never force-fit.

    Read-only; an absent ``portfolio_actions`` table yields empty cells
    without creating anything (safe as a live-DB probe). Quarantined
    masters (``substrate_quarantine`` synthetic ``INE_AUTO_*`` rows) are
    excluded, never deleted.
    """
    hz = tuple(int(h) for h in horizons)
    if not hz or any(h <= 0 for h in hz):
        raise ValueError(
            f"excess_table: horizons must be positive ints, got {horizons!r}")
    wanted = _normalize_universe_names(universes)
    wanted_set = set(wanted)
    mgr = _resolve_manager(manager)
    with mgr.session() as conn:
        if not _table_exists(conn, "portfolio_actions"):
            rows: List[Dict[str, Any]] = []
        else:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM portfolio_actions WHERE status = 'closed' "
                "AND action IN ('BUY','SELL') ORDER BY action_id"
            ).fetchall()]
            try:
                quarantined = quarantined_master_symbols(conn)
            except Exception:
                quarantined = set()
            if quarantined:
                rows = [r for r in rows
                        if str(r.get("symbol") or "").strip().upper() not in quarantined]
    acc: Dict[Tuple[str, int], List[Tuple[str, float]]] = {}
    skipped: Dict[str, int] = {}
    uncovered = 0
    for r in rows:
        uni = resolve_action_universe(str(r.get("symbol")), mgr)
        if uni is None:
            uncovered += 1
            skipped["unmapped-universe"] = skipped.get("unmapped-universe", 0) + len(hz)
            continue
        if uni not in wanted_set:
            skipped["universe-not-requested"] = skipped.get(
                "universe-not-requested", 0) + len(hz)
            continue
        week = _week_monday(r.get("action_date"))
        for h in hz:
            res = horizon_excess(r, h, mgr)
            if "skipped" in res:
                reason = str(res["skipped"])
                skipped[reason] = skipped.get(reason, 0) + 1
                continue
            acc.setdefault((uni, h), []).append((week, float(res["excess"])))
    cells: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for uni in wanted:
        cells[uni] = {}
        for h in hz:
            items = acc.get((uni, h), [])
            vals = [v for _, v in items]
            n = len(vals)
            cohorts: Dict[str, Dict[str, Any]] = {}
            if n:
                by_week: Dict[str, List[float]] = {}
                for week, v in items:
                    by_week.setdefault(week, []).append(v)
                for week in sorted(by_week):
                    wv = by_week[week]
                    cohorts[week] = {"n": len(wv),
                                     "mean_excess": sum(wv) / len(wv)}
            cells[uni][str(h)] = {
                "n": n,
                "mean_excess": (sum(vals) / n) if n else None,
                "hit_rate_excess_gt0": (
                    sum(1 for v in vals if v > 0) / n) if n else None,
                "cohorts": cohorts,
            }
    return {
        "horizons": list(hz),
        "universes": wanted,
        "cells": cells,
        "skipped": skipped,
        "actions_evaluated": len(rows),
        "uncovered_actions": uncovered,
    }


# ====================================================================
# P1 measurement grid: horizon x regime x universe excess + shuffle
# placebo (goal-loop P1; tasks/next_wave_plan_2026-09-23.md §4-§6).
#
# ADDITIVE annex: read-only. record_action / brackets / seed untouched.
# HOLDs stay excluded (non-positional, mirroring ``horizon_excess``).
# Verdict helpers evaluate the tracker promotion bar — they never write
# rankings or weights.
# ====================================================================

#: Grid horizons (calendar days; the realized window is
#: min(close, entry+h), so closed rows can render every horizon identical
#: — the T9 diagnostic, reported honestly in the artifact notes).
P1_HORIZONS: Tuple[int, ...] = HORIZON_DEFAULTS
#: Shuffle-placebo draws per action. 200 draws/action over the ~250-session
#: resolvable pool gives SE ≈ 7bps, so ~=0 resolves ±15bps at 95% — tight
#: against the +500bps bar.
P1_N_PLACEBO_DRAWS: int = 200
#: Fixed seed: the placebo is deterministic, re-runnable byte-identical.
P1_PLACEBO_SEED: int = 20260924
#: Earliest shuffled-entry date (index-breadth bound; never before the
#: benchmark exists).
P1_PLACEBO_POOL_START: str = "2025-09-01"
#: Netting haircut, decimal (50bps ASSUMED prior — no measured cost exists;
#: the slippage audit is tracker backlog #6, so verdicts flag it as assumed).
P1_NET_COST: float = EXCESS_COST

#: |placebo mean| at or under this (decimal) counts as "~=0" — an order of
#: magnitude below the +500bps promotion bar.
P1_PLACEBO_TOLERANCE: float = 0.010

#: Promotion thresholds (tracker §4/§5; EVALUATED here, never set here).
P1_BAR_EXCESS: float = 0.050
P1_BAR_WEEKLY_COHORTS: int = 30
P1_BAR_HIT_LOWER: float = 0.5

#: Two-sided 95% t critical values by df; df > 30 (or unknown) uses 1.96.
_T95: Dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
    7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
    13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
    19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
    25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}

#: Cell regimes. The regime is a point-in-time trailing-50 Nifty 50
#: close-vs-mean split (never peeks past the action date); "unknown" is
#: never force-fit.
P1_REGIMES: Tuple[str, ...] = ("uptrend", "drawdown", "unknown")


def _p1_bars_on_or_after(
    bars: List[Tuple[str, float]], target: str,
) -> Tuple[Optional[str], Optional[float]]:
    """First (date, close) in ascending ``bars`` on/after ``target``."""
    import bisect as _bisect
    dates = [d for d, _ in bars]
    i = _bisect.bisect_left(dates, str(target))
    if i >= len(bars):
        return None, None
    return bars[i]


def _p1_load_close_bars(
    conn: Any, table: str, name_col: str, name_val: str,
) -> List[Tuple[str, float]]:
    """Ascending ``[(date, close)]`` with finite positive closes (read-only)."""
    if table not in ("daily_price_delivery", "nse_index_breadth"):
        return []
    if name_col not in ("symbol", "index_name"):
        return []
    try:
        rows = conn.execute(
            "SELECT date, close FROM %s WHERE %s = ? ORDER BY date ASC"
            % (table, name_col),
            (name_val,),
        ).fetchall()
    except Exception:
        return []
    out: List[Tuple[str, float]] = []
    for r in rows:
        try:
            c = _fnum(r["close"])
        except Exception:
            continue
        if c is None or c <= 0:
            continue
        try:
            d = str(r["date"])
        except Exception:
            continue
        out.append((d, c))
    return out


def _p1_regime_from_bars(
    action_date: Any, index_bars: List[Tuple[str, float]],
) -> str:
    """Pure point-in-time regime for one action date (no DB, no peeking).

    Trailing-50 closes ending at the last bar on/before ``action_date``:
    ``"uptrend"`` when that close >= its trailing mean, else
    ``"drawdown"``. Fewer than 20 trailing bars, no bar on/before the
    date, or an unparsable date -> ``"unknown"``.
    """
    try:
        anchor = datetime.date.fromisoformat(
            str(action_date or "").strip()[:10]).isoformat()
    except ValueError:
        return "unknown"
    import bisect as _bisect
    dates = [d for d, _ in index_bars]
    i = _bisect.bisect_right(dates, anchor) - 1
    if i < 0:
        return "unknown"
    window = index_bars[max(0, i - 49):i + 1]
    if len(window) < 20:
        return "unknown"
    px = index_bars[i][1]
    mean = sum(c for _, c in window) / len(window)
    return "uptrend" if px >= mean else "drawdown"


def _p1_pure_excess(
    action: Any,
    entry_date: Any,
    holding_days: Any,
    stock_bars: List[Tuple[str, float]],
    index_bars: List[Tuple[str, float]],
    cost: float = P1_NET_COST,
) -> Optional[float]:
    """Market-close pure-holding-window excess (the placebo leg).

    No closed_date, no fills: entry/exit are the first closes on/after
    ``entry_date`` / ``entry_date + holding_days`` on BOTH legs, so the
    window is identical for stock and index. SELL mirrors (short-notional,
    same formula as :func:`horizon_excess`). Either leg unresolvable ->
    None (never forward-filled, never crash). Decimal units, net of cost.
    """
    act = str(action or "").strip().upper()
    if act not in ("BUY", "SELL"):
        return None
    try:
        entry_day = datetime.date.fromisoformat(
            str(entry_date or "").strip()[:10])
        holding = int(holding_days)
    except (TypeError, ValueError):
        return None
    if holding < 0:
        return None
    entry_iso = entry_day.isoformat()
    exit_target = (entry_day + datetime.timedelta(days=holding)).isoformat()
    _, se = _p1_bars_on_or_after(stock_bars, entry_iso)
    if se is None:
        return None
    xd, sx = _p1_bars_on_or_after(stock_bars, exit_target)
    if sx is None:
        return None
    _, ie = _p1_bars_on_or_after(index_bars, entry_iso)
    if ie is None:
        return None
    _, ix = _p1_bars_on_or_after(index_bars, xd)
    if ix is None:
        return None
    direction = 1.0 if act == "BUY" else -1.0
    return direction * (sx / se - 1.0) - direction * (ix / ie - 1.0) - cost


def _p1_wilson_lower(hits: Any, n: Any, z: float = 1.96) -> Optional[float]:
    """Wilson 95% lower bound for a hit rate (None when n == 0)."""
    try:
        n = int(n)
        hits = int(hits)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    hits = max(0, min(n, hits))
    p = hits / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return max(0.0, center - half)


def _p1_t95(df: Any) -> Optional[float]:
    """Two-sided 95% t critical for ``df`` (None when df < 1)."""
    try:
        df = int(df)
    except (TypeError, ValueError):
        return 1.96
    if df < 1:
        return None
    return _T95.get(df, 1.96)


def _p1_cell_stats(items: List[Tuple[str, float]]) -> Dict[str, Any]:
    """Stats for one cell from ``[(week_monday, excess)]`` (decimal units).

    ``hit_ci_lower`` is the trade-level Wilson 95% lower bound (reported,
    NOT the gate); the gate uses ``cohort_hit_ci_lower``, the t(G-1)
    interval over weekly-cohort hit rates. ``clustered_*`` is the t(G-1)
    interval over weekly-cohort mean excess. Clustered fields are None
    when G < 2 (an underpowered cell must fail loudly, not approximately).
    """
    vals = [float(v) for _, v in items]
    n = len(vals)
    if not n:
        return {"n": 0, "mean_excess": None, "hit_rate": None,
                "hit_ci_lower": None, "cohorts": 0, "cohort_means": {},
                "clustered_mean": None, "clustered_se": None,
                "clustered_ci": None, "cohort_hit_ci_lower": None}
    by_week: Dict[str, List[float]] = {}
    for w, v in items:
        by_week.setdefault(str(w), []).append(float(v))
    cmeans = {w: sum(vv) / len(vv) for w, vv in sorted(by_week.items())}
    chits = {w: sum(1 for v in vv if v > 0) / len(vv)
             for w, vv in sorted(by_week.items())}
    vals_list = list(cmeans.values())
    hits_list = list(chits.values())
    n_hits = sum(1 for v in vals if v > 0)
    out: Dict[str, Any] = {
        "n": n,
        "mean_excess": sum(vals) / n,
        "hit_rate": n_hits / n,
        "hit_ci_lower": _p1_wilson_lower(n_hits, n),
        "cohorts": len(cmeans),
        "cohort_means": cmeans,
        "clustered_mean": None,
        "clustered_se": None,
        "clustered_ci": None,
        "cohort_hit_ci_lower": None,
    }
    g = len(cmeans)
    if g >= 2:
        cmean = sum(vals_list) / g
        se = _statistics.stdev(vals_list) / math.sqrt(g) if g >= 2 else None
        t = _p1_t95(g - 1)
        hse = _statistics.stdev(hits_list) / math.sqrt(g)
        ht = _p1_t95(g - 1)
        out["clustered_mean"] = cmean
        out["clustered_se"] = se
        out["clustered_ci"] = (
            [cmean - t * se, cmean + t * se]
            if se is not None and t is not None else None)
        out["cohort_hit_ci_lower"] = (
            sum(hits_list) / g - ht * hse if ht is not None else None)
    return out


def _p1_placebo_stats(vals: List[float]) -> Dict[str, Any]:
    """Normal-approx stats for a placebo draw pool (large n by design)."""
    n = len(vals)
    if not n:
        return {"n": 0, "mean": None, "sd": None, "se": None, "ci": None,
                "hit_rate": None}
    mean = sum(vals) / n
    sd = _statistics.pstdev(vals) if n >= 2 else 0.0
    se = sd / math.sqrt(n) if n >= 2 else None
    return {"n": n, "mean": mean, "sd": sd, "se": se,
            "ci": ([mean - 1.96 * se, mean + 1.96 * se]
                   if se is not None else None),
            "hit_rate": sum(1 for v in vals if v > 0) / n}


def _p1_mute_lens_evidence(conn: Any) -> Dict[str, Any]:
    """Attribution degenerate-lens aggregates (read-only, best-effort).

    The P1 verdict cites this: with three of four lens families emitting
    zero direction on every row, no lens-conditioned strategy can clear a
    promotion bar on current substrate.
    """
    ev: Dict[str, Any] = {"available": False}
    try:
        if not _table_exists(conn, "move_attribution"):
            return ev
        n = conn.execute("SELECT COUNT(*) FROM move_attribution").fetchone()[0]
        if not n:
            return ev
        avg = conn.execute(
            "SELECT AVG(explained_total), AVG(residual) FROM move_attribution"
        ).fetchone()
        dirs: Dict[str, Any] = {}
        for label, col in (
                ("factor", "lens_factor_statistical_dir"),
                ("quality", "lens_business_quality_dir"),
                ("policy", "lens_policy_macro_dir"),
                ("supply", "lens_supply_chain_dir")):
            try:
                dirs[label] = conn.execute(
                    "SELECT COUNT(*) FROM move_attribution WHERE %s != 0" % col
                ).fetchone()[0]
            except Exception:
                dirs[label] = None
        try:
            tags = sorted({str(r[0]) for r in conn.execute(
                "SELECT DISTINCT regime_tag FROM move_attribution").fetchall()})
        except Exception:
            tags = []
        ev = {"available": True, "n_attribution": int(n),
              "explained_mean": float(avg[0]) if avg[0] is not None else None,
              "residual_mean": float(avg[1]) if avg[1] is not None else None,
              "nonzero_dirs": dirs, "regime_tags": tags}
    except Exception as exc:
        logger.debug("p1 mute-lens evidence failed: %s", exc)
    return ev


def _p1_verdict(
    strategy: str,
    universe: str,
    horizon: int,
    pooled: Dict[str, Any],
    by_regime: Dict[str, Dict[str, Any]],
    placebo_mean: Optional[float],
) -> Dict[str, Any]:
    """Promotion verdict for one strategy leg against the tracker bar."""
    checks: List[Dict[str, Any]] = []
    reasons: List[str] = []

    cm = pooled.get("clustered_mean")
    if cm is None:
        checks.append({"id": "clustered-mean", "bar": "+500bps net",
                       "value": pooled.get("mean_excess"), "pass": False,
                       "detail": "G<2 weekly cohorts: clustered mean undefined"})
        reasons.append("underpowered: fewer than 2 weekly cohorts")
    elif cm >= P1_BAR_EXCESS:
        checks.append({"id": "clustered-mean", "bar": "+500bps net",
                       "value": cm, "pass": True,
                       "detail": "cohort-clustered mean clears +500bps net"})
    else:
        checks.append({"id": "clustered-mean", "bar": "+500bps net",
                       "value": cm, "pass": False,
                       "detail": "cohort-clustered mean %.0fbps < +500bps net"
                       % (cm * 10000.0,)})
        reasons.append("clustered mean %.0fbps below +500bps"
                       % (cm * 10000.0,))

    cohorts = int(pooled.get("cohorts") or 0)
    if cohorts >= P1_BAR_WEEKLY_COHORTS:
        checks.append({"id": "cohorts", "bar": ">=30 weekly", "value": cohorts,
                       "pass": True, "detail": "weekly-cohort count met"})
    else:
        checks.append({"id": "cohorts", "bar": ">=30 weekly", "value": cohorts,
                       "pass": False,
                       "detail": "%d weekly cohorts < 30" % (cohorts,)})
        reasons.append("only %d weekly cohorts (bar: >=30)" % (cohorts,))

    chl = pooled.get("cohort_hit_ci_lower")
    if chl is None:
        checks.append({"id": "hit-ci", "bar": "cluster lower > 0.5",
                       "value": pooled.get("hit_rate"), "pass": False,
                       "detail": "G<2: cluster-robust hit CI undefined"})
        reasons.append("hit-rate CI undefined (fewer than 2 cohorts)")
    elif chl > P1_BAR_HIT_LOWER:
        checks.append({"id": "hit-ci", "bar": "cluster lower > 0.5",
                       "value": chl, "pass": True,
                       "detail": "cluster-robust hit lower bound clears 0.5"})
    else:
        checks.append({"id": "hit-ci", "bar": "cluster lower > 0.5",
                       "value": chl, "pass": False,
                       "detail": "cluster-robust hit lower %.3f <= 0.5" % (chl,)})
        reasons.append("hit-rate cluster lower %.3f <= 0.5" % (chl,))

    present = [r for r in ("uptrend", "drawdown")
               if (by_regime.get(r) or {}).get("n")]
    rmeans = {r: (by_regime.get(r) or {}).get("mean_excess") for r in present}
    if len(present) >= 2 and all(v is not None for v in rmeans.values()):
        signs = {1 if v > 0 else (-1 if v < 0 else 0) for v in rmeans.values()}
        if len(signs) == 1 and 0 not in signs:
            checks.append({"id": "regimes", "bar": "same sign, >=2 regimes",
                           "value": rmeans, "pass": True,
                           "detail": "same sign in %s" % (sorted(present),)})
        else:
            checks.append({"id": "regimes", "bar": "same sign, >=2 regimes",
                           "value": rmeans, "pass": False,
                           "detail": "sign flips across regimes: %s" % (rmeans,)})
            reasons.append("regime signs differ: %s" % (rmeans,))
    else:
        checks.append({"id": "regimes", "bar": "same sign, >=2 regimes",
                       "value": rmeans, "pass": False,
                       "detail": "single-regime sample: %s" % (present,)})
        reasons.append("single-regime sample %s (bar: >=2 regimes)"
                       % (present,))

    if placebo_mean is None:
        checks.append({"id": "placebo", "bar": "|placebo| <= 100bps",
                       "value": None, "pass": False,
                       "detail": "placebo unresolvable"})
        reasons.append("placebo unresolvable")
    elif abs(placebo_mean) <= P1_PLACEBO_TOLERANCE:
        checks.append({"id": "placebo", "bar": "|placebo| <= 100bps",
                       "value": placebo_mean, "pass": True,
                       "detail": "shuffle placebo %.0fbps ~= 0 (falsification clean)"
                       % (placebo_mean * 10000.0,)})
    else:
        checks.append({"id": "placebo", "bar": "|placebo| <= 100bps",
                       "value": placebo_mean, "pass": False,
                       "detail": "shuffle placebo %.0fbps exceeds ~=0 tolerance"
                       % (placebo_mean * 10000.0,)})
        reasons.append("placebo %.0fbps exceeds ~=0 tolerance"
                       % (placebo_mean * 10000.0,))

    verdict = "promote" if all(c["pass"] for c in checks) else "reject"
    return {"strategy": strategy, "universe": universe, "horizon": horizon,
            "n": pooled.get("n"), "cohorts": cohorts,
            "clustered_mean_excess": cm,
            "checks": checks, "verdict": verdict, "reasons": reasons,
            "cost_note": ("net of %.0fbps ASSUMED prior; no measured cost "
                          "exists — slippage audit is tracker backlog #6"
                          % (P1_NET_COST * 10000.0,))}


def p1_grid(
    horizons: Tuple[int, ...] = P1_HORIZONS,
    universes: Optional[List[Any]] = ("nifty50",),  # type: ignore[assignment]
    n_draws: int = P1_N_PLACEBO_DRAWS,
    seed: int = P1_PLACEBO_SEED,
    manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """P1 measurement grid (read-only): horizon x regime x universe excess.

    Real leg: CLOSED BUY/SELL actions, quarantined masters excluded, scored
    by :func:`horizon_excess` (market closes, ``min(closed, entry+h)``
    realized window, net of the assumed cost prior). Regime is the
    point-in-time trailing-50 Nifty 50 close-vs-mean split.

    Placebo leg: per action, ``n_draws`` shuffled entry dates from the
    resolvable index pool (``P1_PLACEBO_POOL_START`` .. last index date
    minus that universe's max holding, so every pure window resolves),
    scored with the SAME holding length as the realized window
    (:func:`_p1_pure_excess` — no closed_date, identical window both legs).
    Draws are classified by the regime of the SHUFFLED date (PIT).

    Per (universe, horizon, regime) cell: n, mean excess (net), hit rate
    with CIs, weekly cohorts with cluster-robust (t) intervals, placebo
    mean/CI, and placebo delta (real mean − placebo mean). Strategy
    verdicts (BUY/SELL) are evaluated at the first horizon — the only one
    resolvable as a pure forward window — since realized windows render
    every horizon identical on closed rows.

    Read-only: an absent ``portfolio_actions`` table yields structured
    empty cells. Never writes rankings or weights (use :func:`save_p1_grid`
    to persist the returned artifact).
    """
    hz = tuple(int(h) for h in horizons)
    if not hz or any(h <= 0 for h in hz):
        raise ValueError(
            "p1_grid: horizons must be positive ints, got %r" % (horizons,))
    try:
        draws = int(n_draws)
    except (TypeError, ValueError):
        raise ValueError(
            "p1_grid: n_draws must be a non-negative int, got %r" % (n_draws,))
    if draws < 0:
        raise ValueError(
            "p1_grid: n_draws must be a non-negative int, got %r" % (n_draws,))
    wanted = _normalize_universe_names(
        list(universes) if universes is not None else None)
    wanted_set = set(wanted)
    mgr = _resolve_manager(manager)

    with mgr.session() as conn:
        has_book = _table_exists(conn, "portfolio_actions")
        book_total = 0
        rows: List[Dict[str, Any]] = []
        quarantined: set = set()
        n_quarantined_excluded = 0
        if has_book:
            book_total = conn.execute(
                "SELECT COUNT(*) FROM portfolio_actions").fetchone()[0]
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM portfolio_actions WHERE status = 'closed' "
                "AND action IN ('BUY','SELL') ORDER BY action_id").fetchall()]
            try:
                quarantined = quarantined_master_symbols(conn)
            except Exception:
                quarantined = set()
            if quarantined:
                kept = []
                for r in rows:
                    if str(r.get("symbol") or "").strip().upper() in quarantined:
                        n_quarantined_excluded += 1
                    else:
                        kept.append(r)
                rows = kept
        index_bars: Dict[str, List[Tuple[str, float]]] = {}
        for u in wanted:
            index_bars[u] = _p1_load_close_bars(
                conn, "nse_index_breadth", "index_name", u)
        regime_bars = index_bars.get(UNIVERSE_INDEX["nifty50"])
        if regime_bars is None:
            regime_bars = _p1_load_close_bars(
                conn, "nse_index_breadth", "index_name",
                UNIVERSE_INDEX["nifty50"])
        try:
            eod_max = conn.execute(
                "SELECT MAX(date) FROM daily_price_delivery").fetchone()[0]
        except Exception:
            eod_max = None
        try:
            breadth_max = conn.execute(
                "SELECT MAX(date) FROM nse_index_breadth").fetchone()[0]
        except Exception:
            breadth_max = None
        evidence = _p1_mute_lens_evidence(conn)
        syms = sorted({str(r.get("symbol") or "").strip().upper()
                       for r in rows if str(r.get("symbol") or "").strip()})
        stock_bars: Dict[str, List[Tuple[str, float]]] = {}
        for s in syms:
            stock_bars[s] = _p1_load_close_bars(
                conn, "daily_price_delivery", "symbol", s)

    real_items: Dict[Tuple[str, int, str], List[Tuple[str, float]]] = {}
    real_meta: List[Dict[str, Any]] = []
    skipped: Dict[str, int] = {}
    if n_quarantined_excluded:
        skipped["quarantined-excluded"] = n_quarantined_excluded
    for r in rows:
        uni = resolve_action_universe(str(r.get("symbol")), mgr)
        if uni is None:
            skipped["unmapped-universe"] = skipped.get(
                "unmapped-universe", 0) + len(hz)
            continue
        if uni not in wanted_set:
            skipped["universe-not-requested"] = skipped.get(
                "universe-not-requested", 0) + len(hz)
            continue
        regime = _p1_regime_from_bars(r.get("action_date"), regime_bars or [])
        week = _week_monday(r.get("action_date"))
        try:
            entry_day = datetime.date.fromisoformat(
                str(r.get("action_date") or "").strip()[:10])
            closed_day = datetime.date.fromisoformat(
                str(r.get("closed_date") or "").strip()[:10])
            holding = (closed_day - entry_day).days
        except ValueError:
            holding = -1
        real_meta.append({"action_id": r.get("action_id"),
                          "symbol": str(r.get("symbol")),
                          "strategy": str(r.get("action")),
                          "action_date": str(r.get("action_date")),
                          "closed_date": str(r.get("closed_date")),
                          "universe": uni, "regime": regime, "week": week,
                          "holding_days": holding})
        for h in hz:
            res = horizon_excess(r, h, mgr)
            if "skipped" in res:
                skipped[str(res["skipped"])] = skipped.get(
                    str(res["skipped"]), 0) + 1
                continue
            real_items.setdefault(
                (uni, h, regime), []).append((week, float(res["excess"])))

    holdings: Dict[str, List[int]] = {}
    for m in real_meta:
        if isinstance(m["holding_days"], int) and m["holding_days"] >= 0:
            holdings.setdefault(m["universe"], []).append(m["holding_days"])
    pools: Dict[str, List[str]] = {}
    for u in wanted:
        dates = [d for d, _ in index_bars.get(u, [])]
        if not dates or u not in holdings or not holdings[u]:
            pools[u] = []
            continue
        try:
            last = datetime.date.fromisoformat(dates[-1])
            cutoff = (last - datetime.timedelta(
                days=max(holdings[u]))).isoformat()
        except ValueError:
            pools[u] = []
            continue
        pools[u] = [d for d in dates
                    if P1_PLACEBO_POOL_START <= d <= cutoff]

    rng = _random.Random(seed)
    placebo_items: Dict[Tuple[str, int, str], List[float]] = {}
    placebo_skipped = 0
    for m in real_meta:
        holding = m["holding_days"]
        if not isinstance(holding, int) or holding < 0:
            placebo_skipped += draws
            continue
        pool = pools.get(m["universe"], [])
        if not pool:
            placebo_skipped += draws
            continue
        bars = stock_bars.get(str(m["symbol"]).upper(), [])
        ibars = index_bars.get(m["universe"], [])
        for _ in range(draws):
            entry = rng.choice(pool)
            v = _p1_pure_excess(m["strategy"], entry, holding, bars, ibars)
            if v is None:
                placebo_skipped += 1
                continue
            preg = _p1_regime_from_bars(entry, regime_bars or [])
            for h in hz:
                placebo_items.setdefault(
                    (m["universe"], h, preg), []).append(v)

    cells: Dict[str, Dict[str, Any]] = {}
    for uni in wanted:
        cells[uni] = {}
        for h in hz:
            pooled_items: List[Tuple[str, float]] = []
            by_regime: Dict[str, Dict[str, Any]] = {}
            for regime in P1_REGIMES:
                items = real_items.get((uni, h, regime), [])
                pooled_items.extend(items)
                pvals = placebo_items.get((uni, h, regime), [])
                pstats = _p1_placebo_stats(pvals)
                stats = _p1_cell_stats(items)
                stats["placebo_n"] = pstats["n"]
                stats["placebo_mean"] = pstats["mean"]
                stats["placebo_ci"] = pstats["ci"]
                stats["placebo_hit_rate"] = pstats["hit_rate"]
                if stats["mean_excess"] is not None and pstats["mean"] is not None:
                    stats["placebo_delta"] = stats["mean_excess"] - pstats["mean"]
                else:
                    stats["placebo_delta"] = None
                by_regime[regime] = stats
            pooled = _p1_cell_stats(pooled_items)
            pall: List[float] = []
            for regime in P1_REGIMES:
                pall.extend(placebo_items.get((uni, h, regime), []))
            pp = _p1_placebo_stats(pall)
            pooled["placebo_n"] = pp["n"]
            pooled["placebo_mean"] = pp["mean"]
            pooled["placebo_ci"] = pp["ci"]
            pooled["placebo_hit_rate"] = pp["hit_rate"]
            pooled["placebo_delta"] = (
                pooled["mean_excess"] - pp["mean"]
                if pooled["mean_excess"] is not None and pp["mean"] is not None
                else None)
            pooled["regimes_present"] = sorted(
                {m["regime"] for m in real_meta
                 if m["universe"] == uni and (by_regime.get(m["regime"]) or {}).get("n")})
            cells[uni][str(h)] = {"pooled": pooled, "by_regime": by_regime}

    verdicts: List[Dict[str, Any]] = []
    first_h = hz[0]
    # Verdict legs re-resolve each action's OWN excess (keyed by action_id):
    # real_items loses row identity, so replay horizon_excess per meta row
    # once per horizon (cheap at this n) instead of aliasing shared weeks.
    # Rebuild per-action values deterministically (cheap at this n).
    per_action: Dict[Tuple[Any, int], Optional[float]] = {}
    for m in real_meta:
        with mgr.session() as _c:
            _row = _c.execute(
                "SELECT * FROM portfolio_actions WHERE action_id = ?",
                (m["action_id"],)).fetchone()
        _rd = dict(_row) if _row is not None else None
        for h in hz:
            if _rd is None:
                per_action[(m["action_id"], h)] = None
                continue
            _res = horizon_excess(_rd, h, mgr)
            per_action[(m["action_id"], h)] = (
                None if "skipped" in _res else float(_res["excess"]))
    for uni in wanted:
        strategies = sorted({m["strategy"] for m in real_meta
                             if m["universe"] == uni})
        for strategy in strategies:
            strat_meta = [m for m in real_meta
                          if m["universe"] == uni and m["strategy"] == strategy]
            s_items = [(m["week"], per_action[(m["action_id"], first_h)])
                       for m in strat_meta
                       if per_action[(m["action_id"], first_h)] is not None]
            s_by_regime: Dict[str, Dict[str, Any]] = {}
            for regime in P1_REGIMES:
                r_items = [(m["week"], per_action[(m["action_id"], first_h)])
                           for m in strat_meta if m["regime"] == regime
                           if per_action[(m["action_id"], first_h)] is not None]
                s_by_regime[regime] = _p1_cell_stats(r_items)
            s_pooled = _p1_cell_stats(s_items)
            s_pall: List[float] = []
            for m in strat_meta:
                holding = m["holding_days"]
                if not isinstance(holding, int) or holding < 0:
                    continue
                pool = pools.get(uni, [])
                if not pool:
                    continue
                bars = stock_bars.get(str(m["symbol"]).upper(), [])
                ibars = index_bars.get(uni, [])
                sub = _random.Random(
                    (seed + abs(hash((m["symbol"], m["action_date"])))) % (2 ** 31))
                for _ in range(draws):
                    entry = sub.choice(pool)
                    v = _p1_pure_excess(
                        m["strategy"], entry, holding, bars, ibars)
                    if v is not None:
                        s_pall.append(v)
            s_pp = _p1_placebo_stats(s_pall)
            verdicts.append(_p1_verdict(
                strategy, uni, first_h, s_pooled, s_by_regime, s_pp["mean"]))
            verdicts[-1]["placebo"] = s_pp
            verdicts[-1]["n_trades"] = s_pooled.get("n")

    meta = {
        "generated_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "eod_max": eod_max,
        "breadth_max": breadth_max,
        "horizons": list(hz),
        "universes": wanted,
        "n_draws_per_action": draws,
        "placebo_seed": seed,
        "placebo_pool_start": P1_PLACEBO_POOL_START,
        "book_total": book_total,
        "actions_evaluated": len(rows),
        "quarantined_excluded": n_quarantined_excluded,
        "cost_netting": ("%.0fbps ASSUMED prior (EXCESS_COST); no measured "
                         "cost exists — slippage audit is tracker backlog #6"
                         % (P1_NET_COST * 10000.0,)),
        "pool": {u: {"start": (pools[u][0] if pools[u] else None),
                     "end": (pools[u][-1] if pools[u] else None),
                     "n_dates": len(pools[u])} for u in wanted},
        "placebo_skipped": placebo_skipped,
    }
    notes = [
        ("Real leg scores the min(closed, entry+h) realized window: on closed "
         "rows every horizon column is identical by construction (T9 "
         "diagnostic — the horizon axis carries no information here)."),
        ("Placebo preserves each action's realized holding length with pure "
         "market-close windows; draws classify by the SHUFFLED date's "
         "point-in-time regime, so delta = entry skill, not window length."),
        ("Verdicts evaluate at horizon %d, the only horizon resolvable as a "
         "pure forward window past EOD %s." % (first_h, eod_max)),
    ]
    return {"meta": meta, "cells": cells, "skipped": skipped,
            "verdicts": verdicts, "evidence": evidence, "notes": notes}


def save_p1_grid(grid: Dict[str, Any], path: Any) -> str:
    """Persist a :func:`p1_grid` artifact as JSON (the annex's only writer).

    Creates parent directories; returns the path string. Never touches
    rankings, weights, or any ledger table.
    """
    import json as _json
    from pathlib import Path as _Path
    dest = _Path(str(path))
    if dest.parent and str(dest.parent) not in ("", "."):
        dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_json.dumps(grid, indent=2, sort_keys=True, default=str),
                    encoding="utf-8")
    return str(dest)
