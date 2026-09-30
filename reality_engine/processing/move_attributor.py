"""
Slice 1 — Move attribution ledger (tasks/next_wave_attribution.md §2 Slice 1).

Cause→effect model: for each (symbol, date) explain *why* the price moved from
information available at the time, isolate the residual as mispricing, and flag
whether the move cleared the per-scrip noise floor.

v1 semantics (exact, no invented magnitudes — O2 lesson):
  share_lens      = w_lens x (1 if predicted_dir == sign(realized) else 0)
  explained_total = sum(shares) clamped to [0, 1]
  residual        = 1 - explained_total
  is_material     = |realized| > noise_floor

Noise-floor rationale: a move is material iff it exceeds the scrip's own 1σ
daily noise — the per-scrip learned floor from AGENTS.md §3 #5, expressed in
move units (percent points, same scale as ``realized_move_pct``). The floor is
the trailing-20-closed-session population std of close-to-close % moves from
``daily_price_delivery`` for that symbol (sessions with ``date <=
attribution_date``, ordered DESC, limit 20); <5 sessions falls back to 2.0 and
the result is clamped to [0.5, 8.0]. The composite-scale (0–100) floor stays
where it belongs (screener gating) and is not referenced here.

Shares are fractions of *directional* explanation, never predicted returns.
Understating magnitude effects is a documented v1 limitation. ALL evaluated
rows are stored with the material flag — immaterial moves are flagged, never
filtered.

v1 predictor-honesty rule (goal-loop iteration 3; confirmed by live evidence):
  LEVELS GATE — static substrate levels (moat score, policy ENI stock,
  ripple significance stock) gate action quality/solvency through the action
  resolver; they are state, not news, and carry no directional share here.
  FLOWS VOTE — only dated deltas plus prior-day momentum carry directional
  share: this module passes the attribution ``date`` as ``asof_date`` to the
  quality/policy/supply predictors, which vote on the additive substrate
  history (``moat_history`` / ``policy_eni_history`` / ``ripple_history``
  beside the live level tables) -- moat_score delta and aggregate-ENI delta
  in a 30-day lookback window, supply same-session arrivals plus
  revision-delta history. Absent/stale/flat history votes 0; a standing
  level never votes. Residual honesty beats explained fiction.

Ownership: this module owns the ``move_attribution`` table (own DDL, precedent:
``skill_loop.ensure_schema`` / ``pruning_engine.ensure_pruning_schema``). It
calls ``EODCorrector`` predictor methods and
``EnsembleRanker.get_ensemble_weights_for_context`` — never reimplements or
edits them — and copies the ``validation_harness._investor_map``
forensic-holdings-max pattern without importing private code.
"""

from __future__ import annotations

import logging
import math
import statistics
from typing import Any, Dict, List, Optional

logger = logging.getLogger("reality_engine.move_attributor")

# Canonical all-peers lens families (mirrors ensemble_ranker / eod_corrector /
# composite_screener — kept as a literal to avoid an import cycle).
LENS_FAMILIES = (
    "factor_statistical",
    "business_quality",
    "policy_macro",
    "supply_chain",
)

_DEFAULT_INVESTOR = "all"
_DEFAULT_REGIME = "*"

_MOVE_ATTRIBUTION_DDL = """
CREATE TABLE IF NOT EXISTS move_attribution (
    attribution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    attribution_date TEXT NOT NULL,
    realized_move_pct REAL NOT NULL,
    noise_floor REAL NOT NULL,
    is_material INTEGER NOT NULL,
    explained_total REAL NOT NULL,
    residual REAL NOT NULL,
    lens_factor_statistical_dir INTEGER,
    lens_business_quality_dir INTEGER,
    lens_policy_macro_dir INTEGER,
    lens_supply_chain_dir INTEGER,
    lens_factor_statistical_w REAL,
    lens_business_quality_w REAL,
    lens_policy_macro_w REAL,
    lens_supply_chain_w REAL,
    lens_factor_statistical_share REAL,
    lens_business_quality_share REAL,
    lens_policy_macro_share REAL,
    lens_supply_chain_share REAL,
    investor_majority TEXT NOT NULL DEFAULT 'all',
    regime_tag TEXT NOT NULL DEFAULT '*',
    UNIQUE(symbol, attribution_date)
);
"""

_MOVE_ATTRIBUTION_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_move_attrib_date "
    "ON move_attribution(attribution_date)"
)

# family -> (direction column, weight column, share column)
_FAMILY_COLUMNS = {
    "factor_statistical": (
        "lens_factor_statistical_dir",
        "lens_factor_statistical_w",
        "lens_factor_statistical_share",
    ),
    "business_quality": (
        "lens_business_quality_dir",
        "lens_business_quality_w",
        "lens_business_quality_share",
    ),
    "policy_macro": (
        "lens_policy_macro_dir",
        "lens_policy_macro_w",
        "lens_policy_macro_share",
    ),
    "supply_chain": (
        "lens_supply_chain_dir",
        "lens_supply_chain_w",
        "lens_supply_chain_share",
    ),
}

_INSERT_COLUMNS = (
    "symbol",
    "attribution_date",
    "realized_move_pct",
    "noise_floor",
    "is_material",
    "explained_total",
    "residual",
    "lens_factor_statistical_dir",
    "lens_business_quality_dir",
    "lens_policy_macro_dir",
    "lens_supply_chain_dir",
    "lens_factor_statistical_w",
    "lens_business_quality_w",
    "lens_policy_macro_w",
    "lens_supply_chain_w",
    "lens_factor_statistical_share",
    "lens_business_quality_share",
    "lens_policy_macro_share",
    "lens_supply_chain_share",
    "investor_majority",
    "regime_tag",
)

_UPSERT_SQL = (
    "INSERT INTO move_attribution (" + ", ".join(_INSERT_COLUMNS) + ") "
    "VALUES (" + ", ".join(["?"] * len(_INSERT_COLUMNS)) + ") "
    "ON CONFLICT(symbol, attribution_date) DO UPDATE SET "
    + ", ".join(
        f"{c}=excluded.{c}"
        for c in _INSERT_COLUMNS
        if c not in ("symbol", "attribution_date")
    )
)


def _resolve_manager(manager: Optional[Any]) -> Any:
    if manager is not None:
        return manager
    from reality_engine.db.database import db_manager
    return db_manager


def ensure_move_attribution_schema(manager: Optional[Any] = None) -> None:
    """Create the ``move_attribution`` ledger + date index if absent. Idempotent."""
    mgr = _resolve_manager(manager)
    with mgr.session() as conn:
        conn.execute(_MOVE_ATTRIBUTION_DDL)
        conn.execute(_MOVE_ATTRIBUTION_INDEX)


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


def _read_eod_row(manager: Any, symbol: str, date: str) -> Optional[Dict[str, Any]]:
    try:
        with manager.session() as conn:
            row = conn.execute(
                "SELECT * FROM daily_price_delivery WHERE symbol = ? AND date = ? LIMIT 1",
                (symbol, date),
            ).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def _realized_move(row: Dict[str, Any]) -> float:
    """Close-to-close pct from (close, prev_close); falls back to ``change_pct``."""
    realized: Optional[float] = None
    try:
        close = row.get("close")
        prev = row.get("prev_close")
        if close is not None and prev is not None and float(prev) != 0.0:
            realized = (float(close) - float(prev)) / float(prev) * 100.0
    except (TypeError, ValueError):
        realized = None
    if realized is None:
        try:
            cp = row.get("change_pct")
            if cp is not None:
                realized = float(cp)
        except (TypeError, ValueError):
            realized = None
    if realized is None or not math.isfinite(realized):
        raise ValueError(
            "attribute_move: EOD row carries no usable close/prev_close/change_pct"
        )
    return float(realized)


_FLOOR_LOOKBACK = 20
_FLOOR_MIN_SESSIONS = 5
_FLOOR_FALLBACK = 2.0
_FLOOR_MIN = 0.5
_FLOOR_MAX = 8.0


def _session_move_pct(close: Any, prev_close: Any, change_pct: Any) -> Optional[float]:
    """Per-session close-to-close % move in percent points, or None if unusable."""
    try:
        if close is not None and prev_close is not None and float(prev_close) != 0.0:
            v = (float(close) - float(prev_close)) / float(prev_close) * 100.0
            if math.isfinite(v):
                return float(v)
    except (TypeError, ValueError):
        pass
    try:
        if change_pct is not None:
            v = float(change_pct)
            if math.isfinite(v):
                return float(v)
    except (TypeError, ValueError):
        return None
    return None


def _noise_floor_for(manager: Any, symbol: str, date: str) -> float:
    """Vol-adaptive per-scrip floor in percent points (same units as realized)."""
    try:
        with manager.session() as conn:
            rows = conn.execute(
                "SELECT close, prev_close, change_pct FROM daily_price_delivery "
                "WHERE symbol = ? AND date <= ? ORDER BY date DESC LIMIT ?",
                (symbol, date, _FLOOR_LOOKBACK),
            ).fetchall()
    except Exception as exc:
        logger.debug("noise floor history lookup for %s failed: %s", symbol, exc)
        return _FLOOR_FALLBACK
    moves = [
        m
        for r in rows
        for m in [_session_move_pct(r["close"], r["prev_close"], r["change_pct"])]
        if m is not None
    ]
    if len(moves) < _FLOOR_MIN_SESSIONS:
        return _FLOOR_FALLBACK
    try:
        floor = float(statistics.pstdev(moves))
    except Exception:
        return _FLOOR_FALLBACK
    if not math.isfinite(floor):
        return _FLOOR_FALLBACK
    return max(_FLOOR_MIN, min(_FLOOR_MAX, floor))


def _investor_for_symbol(manager: Any, symbol: str) -> str:
    """Forensic-holdings-max investor cohort; default ``"all"``.

    Copies the ``validation_harness._investor_map`` pattern (single-symbol)
    without importing private code.
    """
    try:
        with manager.session() as conn:
            cols = {
                c[1]
                for c in conn.execute(
                    "PRAGMA table_info('company_forensic_health')"
                ).fetchall()
            }
            if not cols or "symbol" not in cols:
                return _DEFAULT_INVESTOR
            r = conn.execute(
                "SELECT * FROM company_forensic_health WHERE symbol = ? LIMIT 1",
                (symbol,),
            ).fetchone()
            if not r:
                return _DEFAULT_INVESTOR
            d = dict(r)
            try:
                holdings = [
                    ("promoter", float(d.get("promoter_holding_pct") or 0.0)),
                    ("FII", float(d.get("fii_holding_pct") or 0.0)),
                    ("DII", float(d.get("dii_holding_pct") or 0.0)),
                    ("retail", float(d.get("public_holding_pct") or 0.0)),
                ]
            except (TypeError, ValueError):
                return _DEFAULT_INVESTOR
            if all(h <= 0 for _, h in holdings):
                return _DEFAULT_INVESTOR
            return max(holdings, key=lambda kv: kv[1])[0]
    except Exception:
        return _DEFAULT_INVESTOR


def quality_broken_reason(
    moat_trajectory: Any = None,
    total_moat_score: Any = None,
    policy_agg_eni: Any = None,
) -> Any:
    """Broken-thesis bands as (broken: bool, reason: str) — pure, no I/O.

    ``quality_broken = (trajectory == 'Deteriorating') OR (total_moat_score <
    2.5) OR (agg ENI < 0)``. The bands are substrate-natural, not
    threshold-shopped (live counts, goal-loop iteration 4):

    * ``deteriorating_trajectory``: 1 of 2,653 moats is Deteriorating
      (TATASTEEL) — the old trajectory-only rule saw one name.
    * ``low_moat_score``: score < 2.5 is the stored ``None``-width band
      (Narrow 1526 / None 949 / Wide 178 of 2,653) — below-Narrow means no
      moat at all, so strength on such names is exit/avoid.
    * ``negative_policy_eni``: 35 distinct tickers carry neg-ENI in material
      unexplained-strength rows (28 distinct low-moat tickers likewise, of
      1,758 such rows) — policy headwind against the move.

    First firing clause wins (order above); intact substrate returns
    ``(False, "intact")``. Missing/unknown inputs (None, NaN, garbage) never
    fire a clause — unknown is not broken. Used by the thesis-action resolver,
    which stamps both values onto the attribution block for audit.
    """
    try:
        if str(moat_trajectory or "").strip() == "Deteriorating":
            return True, "deteriorating_trajectory"
    except Exception:
        pass
    try:
        if total_moat_score is not None:
            _score = float(total_moat_score)
            if math.isfinite(_score) and _score < 2.5:
                return True, f"low_moat_score({_score:g}<2.5)"
    except (TypeError, ValueError):
        pass
    try:
        if policy_agg_eni is not None:
            _eni = float(policy_agg_eni)
            if math.isfinite(_eni) and _eni < 0:
                return True, f"negative_policy_eni({_eni:g}<0)"
    except (TypeError, ValueError):
        pass
    return False, "intact"


def _build_attribution(
    manager: Any, corrector: Any, ranker: Any, symbol: str, date: str
) -> Dict[str, Any]:
    """Compute (but do not persist) the attribution dict for one (symbol, date)."""
    row = _read_eod_row(manager, symbol, date)
    if not row:
        raise ValueError(
            f"attribute_move: no daily_price_delivery row for {symbol} on {date}"
        )
    realized = _realized_move(row)
    floor = _noise_floor_for(manager, symbol, date)
    prev_change = corrector._get_prev_day_change(symbol, date)
    predicted = {
        "factor_statistical": int(corrector._predict_factor(symbol, prev_change)),
        "business_quality": int(corrector._predict_quality(symbol, date)),
        "policy_macro": int(corrector._predict_policy(symbol, date)),
        "supply_chain": int(corrector._predict_supply(symbol, date)),
    }
    raw_weights = ranker.get_ensemble_weights_for_context({"stock_id": symbol}) or {}
    weights = {
        fam: float(raw_weights.get(fam, 0.0) or 0.0) for fam in LENS_FAMILIES
    }
    investor = _investor_for_symbol(manager, symbol)

    rdir = _sign(realized)
    shares = {
        fam: weights[fam] * (1.0 if predicted[fam] == rdir else 0.0)
        for fam in LENS_FAMILIES
    }
    explained = max(0.0, min(1.0, float(sum(shares.values()))))
    residual = 1.0 - explained

    out: Dict[str, Any] = {
        "symbol": symbol,
        "attribution_date": date,
        "realized_move_pct": realized,
        "noise_floor": float(floor),
        "is_material": 1 if abs(realized) > floor else 0,
        "explained_total": explained,
        "residual": residual,
        "investor_majority": investor,
        "regime_tag": _DEFAULT_REGIME,
    }
    for fam in LENS_FAMILIES:
        dcol, wcol, scol = _FAMILY_COLUMNS[fam]
        out[dcol] = predicted[fam]
        out[wcol] = weights[fam]
        out[scol] = shares[fam]
    return out


def _upsert_attribution(conn: Any, attribution: Dict[str, Any]) -> None:
    conn.execute(
        _UPSERT_SQL, tuple(attribution[c] for c in _INSERT_COLUMNS)
    )


def attribute_move(
    symbol: str, date: str, manager: Optional[Any] = None
) -> Dict[str, Any]:
    """Attribute one (symbol, date) move and persist the ledger row (upsert).

    NEVER skips immaterial moves — they are stored with ``is_material=0``.
    Raises ``ValueError`` when the symbol has no EOD row on ``date`` (nothing
    to attribute) or the row carries no usable price.
    """
    mgr = _resolve_manager(manager)
    ensure_move_attribution_schema(mgr)
    sym = str(symbol).strip().upper()
    day = str(date).strip()
    if not sym or not day:
        raise ValueError("attribute_move requires a non-empty symbol and date")
    from reality_engine.processing.eod_corrector import EODCorrector
    from reality_engine.processing.ensemble_ranker import EnsembleRanker
    attribution = _build_attribution(
        mgr, EODCorrector(mgr), EnsembleRanker(mgr), sym, day
    )
    with mgr.session() as conn:
        _upsert_attribution(conn, attribution)
    return attribution


def _resolve_symbols(manager: Any, universe: Any) -> List[str]:
    if isinstance(universe, (list, tuple, set)):
        return [str(s).strip().upper() for s in universe if str(s).strip()]
    u = str(universe or "nifty200").strip()
    try:
        with manager.session() as conn:
            if u.lower() in ("nifty200", "nifty 200", "nifty200_universe"):
                rows = conn.execute(
                    "SELECT nse_symbol FROM master_companies "
                    "WHERE is_nifty200 = 1 AND COALESCE(is_active, 1) = 1 "
                    "ORDER BY nse_symbol ASC"
                ).fetchall()
            elif u.lower() in ("nifty50", "nifty 50", "nifty50_universe"):
                rows = conn.execute(
                    "SELECT nse_symbol FROM master_companies "
                    "WHERE is_nifty50 = 1 AND COALESCE(is_active, 1) = 1 "
                    "ORDER BY nse_symbol ASC"
                ).fetchall()
            elif u.lower() in ("all", "*", "universe_all"):
                rows = conn.execute(
                    "SELECT nse_symbol FROM master_companies "
                    "WHERE COALESCE(is_active, 1) = 1 ORDER BY nse_symbol ASC"
                ).fetchall()
            else:
                return [u.upper()]
            return [str(r[0]).upper() for r in rows if r[0]]
    except Exception as exc:
        logger.debug("attribution universe resolution failed: %s", exc)
        return [u.upper()] if u else []
    return []


def _last_eod_dates(manager: Any, days: int) -> List[str]:
    try:
        n = max(0, int(days))
    except (TypeError, ValueError):
        n = 0
    try:
        with manager.session() as conn:
            rows = conn.execute(
                "SELECT DISTINCT date FROM daily_price_delivery "
                "ORDER BY date DESC LIMIT ?",
                (n,),
            ).fetchall()
            return sorted(str(r[0]) for r in rows if r[0])
    except Exception:
        return []


def attribute_universe(
    universe: Any = "nifty200",
    days: int = 25,
    manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """Attribute the last ``days`` closed EOD sessions for ``universe`` symbols.

    One transaction per symbol (not per row, not the whole run); pairs with no
    EOD row are skipped. Returns ``{symbols, dates, rows_written,
    median_residual, material_count}``.
    """
    mgr = _resolve_manager(manager)
    ensure_move_attribution_schema(mgr)
    symbols = _resolve_symbols(mgr, universe)
    dates = _last_eod_dates(mgr, days)

    from reality_engine.processing.eod_corrector import EODCorrector
    from reality_engine.processing.ensemble_ranker import EnsembleRanker
    corrector = EODCorrector(mgr)
    ranker = EnsembleRanker(mgr)

    rows_written = 0
    material_count = 0
    residuals: List[float] = []
    for sym in symbols:
        sym_rows: List[Dict[str, Any]] = []
        for day in dates:
            try:
                sym_rows.append(_build_attribution(mgr, corrector, ranker, sym, day))
            except ValueError:
                continue
        if not sym_rows:
            continue
        with mgr.session() as conn:
            for attribution in sym_rows:
                _upsert_attribution(conn, attribution)
        rows_written += len(sym_rows)
        residuals.extend(float(a["residual"]) for a in sym_rows)
        material_count += sum(1 for a in sym_rows if a["is_material"])
    return {
        "symbols": list(symbols),
        "dates": list(dates),
        "rows_written": rows_written,
        "median_residual": float(statistics.median(residuals)) if residuals else 0.0,
        "material_count": material_count,
    }
