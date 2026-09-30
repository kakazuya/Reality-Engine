"""
Tax-aware SIP backtest — Nifty-50 equal-weight benchmark leg (Slice: SIPBench).

Runs a monthly SIP (``1L on 2021-10-27 + 50k on the 1st of each month``)
into the Nifty-50 universe at EOD closes, with FIFO equity tax lots,
sector caps, a cash buffer for unallocated SIP, and monthly EOD rebalancing.
Reports pre/post-tax NAV paths, post-tax XIRR, max drawdown against the
40% tolerance band, rolling 1yr/3yr returns, Sharpe/Sortino, and cash /
sector exposure paths.

Price convention (frozen, mirrors ``portfolio_ledger.horizon_excess``): a
close is usable when finite and > 0, read from ``daily_price_delivery``;
entry/exit always at market closes, never forward-filled for trading (a
symbol with no close on a rebalance date is simply not traded that day;
valuation carries the last close on/before the date).

Tax schedule (VERIFIED 2026-09-24 via web search before hardcoding):
* Holding period for listed equity: LONG when ``(sell-buy).days > 365``
  (more than 12 months); exactly 365 days is still short. The 364-vs-366
  boundary is covered by ``test_sip_backtest.py``.
* Finance (No. 2) Act, 2024, effective 2024-07-23: STCG 20% (was 15% under
  Section 111A), LTCG 12.5% on gains above Rs 1.25L per financial year
  (was 10% above Rs 1L under Section 112A), no indexation.
  Sources: incometaxindia.gov.in "Tax on long-term capital gains"
  (https://www.incometaxindia.gov.in/w/tax-on-long-term-capital-gains​),
  reducetax.in Capital Gains Tax Guide FY 2025-26
  (https://reducetax.in/guides/capital-gain), Zerodha support LTCG/STCG
  table for Budget 2024.
* STT 0.1% each side on delivery equity is statutory (buy and sell);
  ``OTHER_CHARGE_RATE`` (exchange txn + GST + SEBI + stamp, 5 bps all-in)
  is an ASSUMED prior, flagged wherever it flows.

Scope limits (stated, not hidden):
* Benchmark breadth exists only from ``BREADTH_START`` (2025-09-01); the
  book before that is equal-weight N50 closes and ``flags`` says so.
* No leverage: buys are scaled to available cash; uninvested SIP
  (sector-cap overflow, late joiners, short cash) sits in cash at 0%.
* Fractional shares are allowed (backtest convention; flagged): 50k/month
  across 50 names is ~1k/name, below several N50 single-share prices.
* LTCG exemption is tracked per financial year within the run; loss
  carry-forward across years is NOT modelled (netting only within a sale).
* Risk-free rate for Sharpe/Sortino is 0 (cash earns 0).

Ownership: this module owns the SIP schedule, FIFO tax lots, cost
constants, sector caps, cash buffer, monthly EOD rebalance, and rolling /
risk metrics. Signal-leg weights plug in via ``weights_fn`` (pure
``(symbol, date) -> float``; ``None`` = equal-weight benchmark). Signal
modules (e.g. ``sip_signals.py``) import from here; nothing here imports
them. Explicit non-goals: ``record_action``, predictors, seed, grid,
ingestion, embed server.
"""

from __future__ import annotations

import bisect
import datetime
import logging
import math
import statistics as _statistics
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("reality_engine.sip_backtest")

#: First SIP date: Rs 1L seeding investment.
SIP_START: str = "2021-10-27"
#: Coverage end (price window 2021-10-27 -> 2026-09-23, 1,268 days).
SIP_END: str = "2026-09-23"
#: Seeding investment on SIP_START (Rs).
SIP_INITIAL: float = 100000.0
#: Monthly SIP on the 1st of each month (Rs).
SIP_MONTHLY: float = 50000.0
#: Max fraction of portfolio value any one sector may occupy.
SECTOR_CAP: float = 0.10
#: Max-drawdown tolerance band (decimal; 0.40 = 40%).
MAX_DD_TOLERANCE: float = 0.40
#: Index-breadth coverage starts here; the book before it is equal-weight
#: N50 closes and every artifact flags that.
BREADTH_START: str = "2025-09-01"
#: Statutory delivery-equity STT, 0.1% on buy and on sell.
STT_BUY_RATE: float = 0.001
STT_SELL_RATE: float = 0.001
#: ASSUMED all-in other charges (exchange + GST + SEBI + stamp), 5 bps.
OTHER_CHARGE_RATE: float = 0.0005
#: Days after which a listed-equity lot turns long (> 12 months).
LTCG_MIN_HOLD_DAYS: int = 365

#: Verified equity tax regimes by sell date (see module docstring).
#: ``effective_from`` is the first sell date under that regime.
TAX_SCHEDULE: Tuple[Dict[str, Any], ...] = (
    {
        "effective_from": "1900-01-01",
        "label": "pre-Finance-(No.2)-Act-2024",
        "stcg_rate": 0.15,
        "ltcg_rate": 0.10,
        "ltcg_exempt": 100000.0,
    },
    {
        "effective_from": "2024-07-23",
        "label": "Finance-(No.2)-Act-2024",
        "stcg_rate": 0.20,
        "ltcg_rate": 0.125,
        "ltcg_exempt": 125000.0,
    },
)

#: Rolling windows (calendar days) reported post-tax.
ROLLING_WINDOWS: Tuple[Tuple[str, int], ...] = (("1yr", 365), ("3yr", 1095))

#: Trading sessions per year for Sharpe/Sortino annualisation.
TRADING_DAYS_PER_YEAR: int = 252

_EPS: float = 1e-9


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def _parse(date_str: Any) -> datetime.date:
    return datetime.date.fromisoformat(str(date_str or "").strip()[:10])


def _fnum(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _add_months(year: int, month: int, delta: int) -> Tuple[int, int]:
    total = (year * 12 + (month - 1)) + delta
    return total // 12, total % 12 + 1


def build_sip_schedule(
    start: str = SIP_START,
    end: str = SIP_END,
    initial: float = SIP_INITIAL,
    monthly: float = SIP_MONTHLY,
) -> List[Dict[str, Any]]:
    """SIP targets: ``initial`` on ``start``, ``monthly`` on each 1st after.

    The seed date's own month has no extra 1st entry (the seed IS that
    month's investment). Returns ascending ``[{target_date, amount}]``.
    """
    start_day = _parse(start)
    end_day = _parse(end)
    if end_day < start_day:
        return []
    out = [{"target_date": start_day.isoformat(), "amount": float(initial)}]
    k = 1
    while True:
        y, m = _add_months(start_day.year, start_day.month, k)
        first = datetime.date(y, m, 1)
        if first > end_day:
            break
        out.append({"target_date": first.isoformat(), "amount": float(monthly)})
        k += 1
    return out


def resolve_trade_date(target: str, trading_days: List[str]) -> Optional[str]:
    """First trading day on/after ``target`` (next-trading-day holiday rule).

    ``trading_days`` must be sorted ascending ISO dates. None when no
    trading day remains (target past coverage).
    """
    iso = _parse(target).isoformat()
    i = bisect.bisect_left(trading_days, iso)
    if i >= len(trading_days):
        return None
    return trading_days[i]


def fy_of(date_str: str) -> str:
    """Indian financial year label: Apr 2024–Mar 2025 -> ``'FY25'``."""
    d = _parse(date_str)
    fy_end = d.year + 1 if d.month >= 4 else d.year
    return "FY%02d" % (fy_end % 100,)


def rate_for(sell_date: str) -> Dict[str, Any]:
    """Applicable :data:`TAX_SCHEDULE` regime for a sell date."""
    iso = _parse(sell_date).isoformat()
    regime = TAX_SCHEDULE[0]
    for cand in TAX_SCHEDULE:
        if str(cand["effective_from"]) <= iso:
            regime = cand
    return regime


# ---------------------------------------------------------------------------
# FIFO tax lots
# ---------------------------------------------------------------------------

@dataclass
class Lot:
    """One FIFO purchase lot; ``cost_per_share`` includes buy STT+charges."""

    symbol: str
    buy_date: str
    qty: float
    buy_price: float
    cost_per_share: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "buy_date": self.buy_date,
            "qty": self.qty,
            "buy_price": self.buy_price,
            "cost_per_share": self.cost_per_share,
        }


def add_lot(
    lots: List[Lot],
    symbol: str,
    buy_date: str,
    qty: float,
    buy_price: float,
    stt_rate: float = STT_BUY_RATE,
    other_rate: float = OTHER_CHARGE_RATE,
) -> Optional[Lot]:
    """Append a buy lot with STT+charges folded into the cost base."""
    q = _fnum(qty)
    px = _fnum(buy_price)
    if q is None or px is None or q <= 0 or px <= 0:
        return None
    lot = Lot(
        symbol=str(symbol).strip().upper(),
        buy_date=_parse(buy_date).isoformat(),
        qty=q,
        buy_price=px,
        cost_per_share=px * (1.0 + stt_rate + other_rate),
    )
    lots.append(lot)
    return lot


def sell_fifo(
    lots: List[Lot],
    qty: float,
    sell_price: float,
    sell_date: str,
    stt_rate: float = STT_SELL_RATE,
    other_rate: float = OTHER_CHARGE_RATE,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Sell ``qty`` FIFO from ``lots`` (mutated); net proceeds + gain records.

    Proceeds are net of sell STT+charges; each gain record carries
    ``{symbol, buy_date, qty, gain, holding_days}``. ``qty`` is clamped to
    total held (float-dust safe); empty lots are dropped.
    """
    px = _fnum(sell_price)
    want = _fnum(qty)
    if px is None or px <= 0 or want is None or want <= 0 or not lots:
        return 0.0, []
    day = _parse(sell_date)
    held = sum(max(0.0, lot.qty) for lot in lots)
    want = min(want, held)
    proceeds = 0.0
    gains: List[Dict[str, Any]] = []
    net_rate = 1.0 - stt_rate - other_rate
    remaining = want
    kept: List[Lot] = []
    for lot in lots:
        if remaining <= _EPS:
            if lot.qty > _EPS:
                kept.append(lot)
            continue
        dq = min(lot.qty, remaining)
        cost = dq * lot.cost_per_share
        leg = dq * px * net_rate
        holding = (day - _parse(lot.buy_date)).days
        proceeds += leg
        gains.append({
            "symbol": lot.symbol,
            "buy_date": lot.buy_date,
            "qty": dq,
            "gain": leg - cost,
            "holding_days": holding,
        })
        lot.qty -= dq
        remaining -= dq
        if lot.qty > _EPS:
            kept.append(lot)
    lots[:] = kept
    return proceeds, gains


def tax_on_sale(
    gains: List[Dict[str, Any]],
    sell_date: str,
    fy_exempt_used: Dict[str, float],
) -> Tuple[float, float]:
    """Tax for one sale's FIFO gain records; pure (no mutation).

    Splits by holding clock (long iff ``holding_days > 365``), nets within
    each bucket, taxes ST gains in full and LT gains above the regime's
    remaining FY exemption. Returns ``(tax, exempt_used_increment)``; the
    caller adds the increment to ``fy_exempt_used[fy_of(sell_date)]``.
    """
    regime = rate_for(sell_date)
    fy = fy_of(sell_date)
    st = 0.0
    lt = 0.0
    for g in gains or []:
        amt = _fnum(g.get("gain")) or 0.0
        try:
            held = int(g.get("holding_days"))
        except (TypeError, ValueError):
            held = 0
        if held > LTCG_MIN_HOLD_DAYS:
            lt += amt
        else:
            st += amt
    st_tax = float(regime["stcg_rate"]) * max(0.0, st)
    used = _fnum((fy_exempt_used or {}).get(fy)) or 0.0
    remaining = max(0.0, float(regime["ltcg_exempt"]) - used)
    lt_net = max(0.0, lt)
    taxable_lt = max(0.0, lt_net - remaining)
    lt_tax = float(regime["ltcg_rate"]) * taxable_lt
    return st_tax + lt_tax, min(remaining, lt_net)


# ---------------------------------------------------------------------------
# Read-only market load (repository price access)
# ---------------------------------------------------------------------------

def _resolve_manager(manager: Optional[Any]) -> Any:
    if manager is not None:
        return manager
    from reality_engine.db.database import db_manager
    return db_manager


def _table_exists(conn: Any, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?", (name,)
        ).fetchone()
    except Exception:
        return False
    return row is not None


def load_market(
    manager: Optional[Any] = None,
    symbols: Optional[List[str]] = None,
    start: str = SIP_START,
    end: str = SIP_END,
) -> Dict[str, Any]:
    """Read-only market bundle for the backtest (never writes).

    ``symbols`` defaults to ``master_companies`` rows with
    ``is_nifty50 = 1``. Closes come from ``daily_price_delivery``
    (finite, > 0 only — the ``horizon_excess`` usable-close rule).
    ``sector_map`` falls back to ``'Unknown'``; symbols first listed after
    the first trading day are reported as ``late_joiners`` (their SIP
    share is cash-held until listed). ``flags`` always carries
    ``equal_weight_pre_breadth`` (True when ``start`` predates breadth
    coverage — the book then is equal-weight N50 closes by construction).
    """
    start_iso = _parse(start).isoformat()
    end_iso = _parse(end).isoformat()
    mgr = _resolve_manager(manager)
    empty_flags = {
        "equal_weight_pre_breadth": start_iso < BREADTH_START,
        "breadth_start": BREADTH_START,
        "n_symbols": 0,
        "n_symbols_day_one": 0,
        "late_joiners": [],
        "start": start_iso,
        "end": end_iso,
        "trading_days": 0,
    }
    try:
        with mgr.session() as conn:
            if not _table_exists(conn, "daily_price_delivery"):
                return {"symbols": [], "sector_map": {},
                        "price_map": {}, "trading_days": [],
                        "flags": empty_flags}
            if symbols is None:
                if not _table_exists(conn, "master_companies"):
                    syms: List[str] = []
                else:
                    rows = conn.execute(
                        "SELECT nse_symbol FROM master_companies "
                        "WHERE is_nifty50 = 1 ORDER BY nse_symbol ASC"
                    ).fetchall()
                    syms = [str(r["nse_symbol"]).strip().upper()
                            for r in rows if r["nse_symbol"]]
            else:
                syms = [str(s).strip().upper() for s in symbols if str(s).strip()]
            sector_map: Dict[str, str] = {}
            if syms and _table_exists(conn, "master_companies"):
                for r in conn.execute(
                        "SELECT nse_symbol, sector FROM master_companies"
                ).fetchall():
                    try:
                        key = str(r["nse_symbol"]).strip().upper()
                    except Exception:
                        continue
                    if key in syms:
                        sec = str(r["sector"] or "").strip() or "Unknown"
                        sector_map[key] = sec
            for s in syms:
                sector_map.setdefault(s, "Unknown")
            price_map: Dict[str, Dict[str, float]] = {s: {} for s in syms}
            if syms:
                placeholders = ",".join("?" for _ in syms)
                rows = conn.execute(
                    "SELECT symbol, date, close FROM daily_price_delivery "
                    "WHERE date >= ? AND date <= ? AND symbol IN (%s)"
                    % placeholders,
                    (start_iso, end_iso, *syms),
                ).fetchall()
                for r in rows:
                    try:
                        sym = str(r["symbol"]).strip().upper()
                        day = str(r["date"])[:10]
                        close = _fnum(r["close"])
                    except Exception:
                        continue
                    if sym not in price_map or close is None or close <= 0:
                        continue
                    if not (start_iso <= day <= end_iso):
                        continue
                    price_map[sym][day] = close
    except Exception as exc:
        logger.debug("load_market failed: %s", exc)
        return {"symbols": [], "sector_map": {},
                "price_map": {}, "trading_days": [],
                "flags": empty_flags}
    day_set = set()
    for per in price_map.values():
        day_set.update(per.keys())
    trading_days = sorted(d for d in day_set if start_iso <= d <= end_iso)
    first_px: Dict[str, Optional[str]] = {
        s: (min(per.keys()) if per else None) for s, per in price_map.items()
    }
    first_day = trading_days[0] if trading_days else None
    late_joiners = sorted(
        s for s, d in first_px.items()
        if d is not None and first_day is not None and d > first_day
    )
    no_px_day_one = sorted(
        s for s, d in first_px.items()
        if d is None or (first_day is not None and d > first_day)
    )
    flags = {
        "equal_weight_pre_breadth": start_iso < BREADTH_START,
        "breadth_start": BREADTH_START,
        "n_symbols": len(syms),
        "n_symbols_day_one": len(syms) - len(no_px_day_one),
        "late_joiners": late_joiners,
        "start": start_iso,
        "end": end_iso,
        "trading_days": len(trading_days),
    }
    return {
        "symbols": syms,
        "sector_map": sector_map,
        "price_map": price_map,
        "trading_days": trading_days,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Metrics (pure; post-tax NAV in, no DB)
# ---------------------------------------------------------------------------

def nav_drawdown(dates: List[str], navs: List[float]) -> Dict[str, Any]:
    """Peak-to-trough drawdown over a NAV series (decimal units).

    Returns ``{max_dd, peak_date, trough_date, within_tolerance,
    tolerance}`` where ``within_tolerance`` checks the 40% band.
    Empty / non-positive series -> zeros with ``within_tolerance`` True.
    """
    tolerance = MAX_DD_TOLERANCE
    if not dates or not navs or len(dates) != len(navs):
        return {"max_dd": 0.0, "peak_date": None, "trough_date": None,
                "within_tolerance": True, "tolerance": tolerance}
    peak = -math.inf
    peak_date: Optional[str] = None
    max_dd = 0.0
    best_peak: Optional[str] = None
    best_trough: Optional[str] = None
    for d, n in zip(dates, navs):
        v = _fnum(n) or 0.0
        if v > peak:
            peak = v
            peak_date = str(d)
        if peak > 0 and v >= 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
                best_peak = peak_date
                best_trough = str(d)
    return {"max_dd": max_dd, "peak_date": best_peak,
            "trough_date": best_trough,
            "within_tolerance": max_dd <= tolerance, "tolerance": tolerance}


def _rolling_for_window(
    dates: List[str], navs: List[float], window_days: int,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not dates:
        return out
    try:
        first_day = _parse(dates[0])
    except Exception:
        return out
    for i, end_d in enumerate(dates):
        try:
            end_day = _parse(end_d)
        except Exception:
            continue
        if (end_day - first_day).days < window_days:
            continue
        anchor = (end_day - datetime.timedelta(days=window_days)).isoformat()
        j = bisect.bisect_left(dates, anchor, 0, i)
        if j >= i:
            continue
        base = _fnum(navs[j])
        last = _fnum(navs[i])
        if base is None or last is None or base <= 0:
            continue
        out.append({"start": dates[j], "end": end_d,
                    "return": last / base - 1.0})
    return out


def rolling_returns(
    dates: List[str], navs: List[float],
) -> Dict[str, List[Dict[str, Any]]]:
    """Post-tax rolling returns: ``{'1yr': [...], '3yr': [...]}``.

    Each entry is ``{start, end, return}`` (decimal); ``end`` runs over
    every trading day with >= ``window`` calendar days of history, ``start``
    is the first trading day on/after ``end - window``.
    """
    return {name: _rolling_for_window(dates, navs, w)
            for name, w in ROLLING_WINDOWS}


def _daily_returns(navs: List[float]) -> List[float]:
    rets: List[float] = []
    prev: Optional[float] = None
    for n in navs or []:
        v = _fnum(n)
        if v is None or v <= 0:
            prev = None
            continue
        if prev is not None and prev > 0:
            rets.append(v / prev - 1.0)
        prev = v
    return rets


def sharpe_ratio(
    navs: List[float], periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> Optional[float]:
    """Annualised Sharpe on daily simple returns, risk-free 0.

    None when fewer than 2 returns or zero variance (no signal to scale).
    """
    rets = _daily_returns(navs)
    if len(rets) < 2:
        return None
    try:
        sd = _statistics.pstdev(rets)
    except Exception:
        return None
    if sd <= 0:
        return None
    return sum(rets) / len(rets) / sd * math.sqrt(periods_per_year)


def sortino_ratio(
    navs: List[float], periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> Optional[float]:
    """Annualised Sortino on daily simple returns, target 0.

    None when fewer than 2 returns or no downside deviation.
    """
    rets = _daily_returns(navs)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    downside = math.sqrt(sum(min(0.0, r) ** 2 for r in rets) / len(rets))
    if downside <= 0:
        return None
    return mean / downside * math.sqrt(periods_per_year)


def xirr(dates: List[str], amounts: List[float]) -> Optional[float]:
    """Annual-compounded XIRR (actual/365); None when no sign change.

    ``amounts``: contributions negative, final NAV positive.
    Bisection on [-0.9999, 10.0], 200 iterations, deterministic.
    """
    if not dates or not amounts or len(dates) != len(amounts):
        return None
    try:
        base = min(_parse(d) for d in dates)
        times = [(_parse(d) - base).days / 365.0 for d in dates]
        flows = [float(a) for a in amounts]
    except Exception:
        return None
    if not any(a > 0 for a in flows) or not any(a < 0 for a in flows):
        return None

    def _npv(r: float) -> float:
        denom = 1.0 + r
        if denom <= 0:
            return math.inf
        return sum(a / (denom ** t) for a, t in zip(flows, times))

    lo, hi = -0.9999, 10.0
    flo, fhi = _npv(lo), _npv(hi)
    if not (math.isfinite(flo) and math.isfinite(fhi)):
        return None
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        fmid = _npv(mid)
        if not math.isfinite(fmid):
            return None
        if flo * fmid <= 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# SIP engine
# ---------------------------------------------------------------------------

WeightsFn = Callable[[str, str], float]


def _close_on_or_before(
    per: Dict[str, float], day: str, ordered: List[str],
) -> Optional[float]:
    i = bisect.bisect_right(ordered, day) - 1
    if i < 0:
        return None
    return per.get(ordered[i])


def _apply_sector_cap(
    weights: Dict[str, float],
    sector_of: Dict[str, str],
    cap: float,
) -> Dict[str, float]:
    """Scale overweight sectors down to ``cap``; overflow stays cash."""
    sector_tot: Dict[str, float] = {}
    for s, w in weights.items():
        sector_tot[sector_of.get(s, "Unknown")] = (
            sector_tot.get(sector_of.get(s, "Unknown"), 0.0) + w
        )
    out: Dict[str, float] = {}
    for s, w in weights.items():
        tot = sector_tot.get(sector_of.get(s, "Unknown"), 0.0)
        if tot > cap > 0:
            out[s] = w * (cap / tot)
        else:
            out[s] = w
    return out


def run_sip(
    symbols: List[str],
    price_map: Dict[str, Dict[str, float]],
    sector_map: Dict[str, str],
    trading_days: List[str],
    schedule: Optional[List[Dict[str, Any]]] = None,
    weights_fn: Optional[WeightsFn] = None,
    start: str = SIP_START,
    end: Optional[str] = None,
    monthly_rebalance: bool = True,
    sector_cap: float = SECTOR_CAP,
) -> Dict[str, Any]:
    """Run the tax-aware SIP book over ``trading_days``.

    ``weights_fn(symbol, date) -> float`` is pure point-in-time (no
    cash/NAV context); ``None`` means equal-weight benchmark. Each monthly
    SIP date rebalances at the EOD close when ``monthly_rebalance`` is
    True (sells realise FIFO gains and pay tax from proceeds); when False
    only new cash is deployed (buys only, never sells). Sector weights are
    capped at ``sector_cap`` of portfolio value with the overflow left in
    cash; symbols with no close on/before the date are cash-held (late
    joiners until listed). Buys scale to available cash — no leverage.

    Artifact keys: ``nav_daily[{date,nav_pre,nav_post,cash}]``,
    ``cash_path``, ``sector_path``, ``pre_tax_xirr``, ``post_tax_xirr``,
    ``max_dd{...}``, ``rolling{1yr,3yr}``, ``sharpe``, ``sortino``,
    ``taxes_paid``, ``tax_by_fy``, ``contributions``, ``flags{...}``,
    ``lots``, ``late_joiners``, ``n_buys``, ``n_sells``. ``nav_pre``
    adds back cumulative taxes paid (pre-tax view); ``nav_post`` is the
    realised post-tax book.
    """
    syms = [str(s).strip().upper() for s in (symbols or []) if str(s).strip()]
    days = sorted(d for d in (trading_days or [])
                  if _parse(d).isoformat() >= _parse(start).isoformat()
                  and (end is None or _parse(d).isoformat() <= _parse(end).isoformat()))
    sector_of = {s: str((sector_map or {}).get(s) or "Unknown") for s in syms}
    ordered: Dict[str, List[str]] = {
        s: sorted((price_map or {}).get(s, {}).keys()) for s in syms
    }
    first_px = {s: (ordered[s][0] if ordered[s] else None) for s in syms}
    late_joiners = sorted(
        s for s in syms
        if first_px[s] is not None and days and first_px[s] > days[0]
    )
    flags: Dict[str, Any] = {
        "equal_weight_pre_breadth": _parse(start).isoformat() < BREADTH_START,
        "breadth_start": BREADTH_START,
        "monthly_rebalance": bool(monthly_rebalance),
        "sector_cap": sector_cap,
        "weights": "equal-weight" if weights_fn is None else "signal",
        "late_joiners": late_joiners,
        "n_symbols_day_one": sum(
            1 for s in syms
            if first_px[s] is not None and days and first_px[s] <= days[0]
        ),
        "stt_buy_rate": STT_BUY_RATE,
        "stt_sell_rate": STT_SELL_RATE,
        "other_charge_rate": OTHER_CHARGE_RATE,
        "other_charges_assumed": True,
        "fractional_shares_assumed": True,
    }
    empty: Dict[str, Any] = {
        "nav_daily": [], "cash_path": [], "sector_path": [],
        "pre_tax_xirr": None, "post_tax_xirr": None,
        "max_dd": nav_drawdown([], []), "rolling": {"1yr": [], "3yr": []},
        "sharpe": None, "sortino": None, "taxes_paid": 0.0,
        "tax_by_fy": {}, "contributions": 0.0, "flags": flags,
        "lots": [], "late_joiners": late_joiners,
        "n_buys": 0, "n_sells": 0,
    }
    if not syms or not days:
        return empty
    sched = (schedule if schedule is not None
             else build_sip_schedule(start, days[-1]))
    contrib_by_day: Dict[str, float] = {}
    for entry in sched or []:
        try:
            amt = float(entry.get("amount"))
            tgt = _parse(entry.get("target_date")).isoformat()
        except (TypeError, ValueError):
            continue
        if amt <= 0 or tgt > days[-1]:
            continue
        td = resolve_trade_date(tgt, days)
        if td is None:
            continue
        contrib_by_day[td] = contrib_by_day.get(td, 0.0) + amt

    lots_by: Dict[str, List[Lot]] = {s: [] for s in syms}
    qty_of: Dict[str, float] = {s: 0.0 for s in syms}
    cash = 0.0
    contributions = 0.0
    taxes_paid = 0.0
    tax_by_fy: Dict[str, float] = {}
    exempt_used: Dict[str, float] = {}
    n_buys = 0
    n_sells = 0
    nav_daily: List[Dict[str, Any]] = []
    cash_path: List[Dict[str, Any]] = []
    sector_path: List[Dict[str, Any]] = []
    flow_dates: List[str] = []
    flow_amounts: List[float] = []

    for day in days:
        if day in contrib_by_day:
            cash += contrib_by_day[day]
            contributions += contrib_by_day[day]
            flow_dates.append(day)
            flow_amounts.append(-contrib_by_day[day])

        closes: Dict[str, float] = {}
        for s in syms:
            per = (price_map or {}).get(s, {})
            if day in per and (_fnum(per[day]) or 0) > 0:
                closes[s] = float(per[day])
        listed = [s for s in syms if first_px[s] is not None and first_px[s] <= day]
        holdings_val = 0.0
        val_of: Dict[str, float] = {}
        for s in syms:
            last = _close_on_or_before((price_map or {}).get(s, {}), day, ordered[s])
            v = qty_of[s] * last if last else 0.0
            val_of[s] = v
            holdings_val += v

        if day in contrib_by_day and listed:
            raw: Dict[str, float] = {}
            if weights_fn is None:
                for s in listed:
                    raw[s] = 1.0
            else:
                for s in listed:
                    w = _fnum(weights_fn(s, day))
                    raw[s] = max(0.0, w) if w is not None else 0.0
            tot_raw = sum(raw.values())
            total = holdings_val + cash
            targets: Dict[str, float] = {s: 0.0 for s in syms}
            if tot_raw > 0 and total > 0:
                capped = _apply_sector_cap(
                    {s: raw[s] / tot_raw for s in listed}, sector_of, sector_cap)
                for s in listed:
                    targets[s] = capped.get(s, 0.0) * total
            if monthly_rebalance:
                for s in listed:
                    if s not in closes:
                        continue
                    delta = targets.get(s, 0.0) - val_of.get(s, 0.0)
                    if delta < -_EPS and qty_of[s] > _EPS:
                        sell_qty = min(qty_of[s], -delta / closes[s])
                        proceeds, gains = sell_fifo(
                            lots_by[s], sell_qty, closes[s], day)
                        tax, inc = tax_on_sale(gains, day, exempt_used)
                        fy = fy_of(day)
                        exempt_used[fy] = exempt_used.get(fy, 0.0) + inc
                        cash += proceeds - tax
                        taxes_paid += tax
                        tax_by_fy[fy] = tax_by_fy.get(fy, 0.0) + tax
                        qty_of[s] = sum(l.qty for l in lots_by[s])
                        n_sells += 1
                holdings_val = 0.0
                for s in syms:
                    last = _close_on_or_before(
                        (price_map or {}).get(s, {}), day, ordered[s])
                    val_of[s] = qty_of[s] * last if last else 0.0
                    holdings_val += val_of[s]
                total = holdings_val + cash
            desired: Dict[str, float] = {}
            need = 0.0
            for s in listed:
                if s not in closes:
                    continue
                gap = targets.get(s, 0.0) - val_of.get(s, 0.0)
                if gap > _EPS:
                    desired[s] = gap
                    need += gap
            scale = min(1.0, cash / need) if need > _EPS else 0.0
            for s, gap in desired.items():
                spend = gap * scale
                if spend <= _EPS:
                    continue
                gross = spend / (1.0 + STT_BUY_RATE + OTHER_CHARGE_RATE)
                q = gross / closes[s]
                if add_lot(lots_by[s], s, day, q, closes[s]) is not None:
                    cash -= spend
                    qty_of[s] = sum(l.qty for l in lots_by[s])
                    n_buys += 1
            holdings_val = 0.0
            for s in syms:
                last = _close_on_or_before(
                    (price_map or {}).get(s, {}), day, ordered[s])
                val_of[s] = qty_of[s] * last if last else 0.0
                holdings_val += val_of[s]

        nav_post = holdings_val + cash
        nav_pre = nav_post + taxes_paid
        nav_daily.append({"date": day, "nav_pre": nav_pre,
                          "nav_post": nav_post, "cash": cash})
        cash_path.append({"date": day, "cash": cash,
                          "cash_fraction": cash / nav_post if nav_post > 0 else 1.0})
        sec_w: Dict[str, float] = {}
        if nav_post > 0:
            for s in syms:
                sec = sector_of[s]
                sec_w[sec] = sec_w.get(sec, 0.0) + val_of.get(s, 0.0) / nav_post
        sector_path.append({"date": day, "weights": sec_w})

    nav_dates = [r["date"] for r in nav_daily]
    post_navs = [r["nav_post"] for r in nav_daily]
    pre_navs = [r["nav_pre"] for r in nav_daily]
    post_xirr = xirr(flow_dates + [days[-1]],
                     flow_amounts + ([post_navs[-1]] if post_navs else []))
    pre_xirr = xirr(flow_dates + [days[-1]],
                    flow_amounts + ([pre_navs[-1]] if pre_navs else []))
    return {
        "nav_daily": nav_daily,
        "cash_path": cash_path,
        "sector_path": sector_path,
        "pre_tax_xirr": pre_xirr,
        "post_tax_xirr": post_xirr,
        "max_dd": nav_drawdown(nav_dates, post_navs),
        "rolling": rolling_returns(nav_dates, post_navs),
        "sharpe": sharpe_ratio(post_navs),
        "sortino": sortino_ratio(post_navs),
        "taxes_paid": taxes_paid,
        "tax_by_fy": tax_by_fy,
        "contributions": contributions,
        "flags": flags,
        "lots": [lot.to_dict() for s in syms for lot in lots_by[s]],
        "late_joiners": late_joiners,
        "n_buys": n_buys,
        "n_sells": n_sells,
    }


def run_benchmark(
    symbols: List[str],
    price_map: Dict[str, Dict[str, float]],
    sector_map: Dict[str, str],
    trading_days: List[str],
    schedule: Optional[List[Dict[str, Any]]] = None,
    start: str = SIP_START,
    end: Optional[str] = None,
    monthly_rebalance: bool = True,
    sector_cap: float = SECTOR_CAP,
) -> Dict[str, Any]:
    """Buy-hold N50 equal-weight SIP leg: :func:`run_sip`, ``weights_fn=None``.

    Rebalances to equal weight at each monthly SIP EOD (so drift + new
    cash restore balance); sells there realise FIFO tax — buy-hold rarely
    sells, and both pre- and post-tax XIRR are reported in the artifact.
    """
    return run_sip(
        symbols, price_map, sector_map, trading_days,
        schedule=schedule, weights_fn=None, start=start, end=end,
        monthly_rebalance=monthly_rebalance, sector_cap=sector_cap,
    )
