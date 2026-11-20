"""T-229 stage A: a point-in-time factor panel built from the 91 Telegram stores.

Stage A builds and validates the panel only; no IC is computed here.  Every
factor for a month-end uses only the rows the store had by that session:

* ``fin_quarter_xbrl`` / ``fin_quarter_printed`` rows carrying a
  ``preferred_from`` window are the candidates.  The figure of a
  (fiscal_period, line_item) at day D is the candidate with the newest
  availability session at or before D, where availability applies the T-118
  rule: a filing after 15:30 IST counts from the next session.  ``preferred_to``
  therefore only decides which later row takes over; the time rule decides the
  day.  A restatement filed after the close never leaks into that close.
* Shareholding, pledge, guidance and KPI rows use ``known_at`` the same way.
* ``price_delivery`` rows are dated on the session they describe; targets are
  forward returns of ``adj_close`` from the same calendar.

Universe: the 91 ``cNN/cNN.db`` stores under the Telegram build root (the
``c40_crash_*`` copy is skipped).  All stores are opened read-only.

    python -m reality_engine.research.factor_store91 --out .tmp/t229

Outputs under ``--out``: ``panel.parquet`` (company-month x factors x targets),
``validation.csv`` (store vs T-118/T-207 truth panel), ``validation_worst.csv``
(the 10 worst disagreements per overlapping factor), ``coverage_factor.csv``
and ``coverage_month.csv``.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from reality_engine.db.readonly import connect_ro
from reality_engine.research.factor_weights import (
    IST,
    build_panel_parquet,
    default_snapshot,
    pit_sessions,
    spearman_ic,
)

STORE_ROOT = Path("D:/RealityEngine/tg_build/measure10")
START_DEFAULT = "2024-06-28"
TRUTH_START = "2024-06-01"
TRUTH_END = "2026-11-04"
TRUTH_PANEL_NAME = "truth_panel.parquet"

HORIZONS = {"3m": 63, "6m": 126, "12m": 252}

# factor order is the brief's order; the T-207 name is used wherever one exists.
FACTORS = [
    "q_rev_yoy", "q_pat_yoy", "ttm_rev_yoy", "ttm_pat_yoy", "op_margin", "op_margin_chg",
    "earnings_yield", "sales_yield", "fin_cost_to_rev", "net_debt_chg_4q",
    "promoter_chg_1q", "promoter_chg_4q", "fpi_chg_4q", "mf_chg_4q", "pledge_pct",
    "delivery_3m", "mom_12_1", "vol_12m", "size",
    "guidance_rev", "guidance_growth", "order_cover",
]
FIN_FACTORS = [
    "q_rev_yoy", "q_pat_yoy", "ttm_rev_yoy", "ttm_pat_yoy", "op_margin", "op_margin_chg",
    "earnings_yield", "sales_yield", "fin_cost_to_rev",
]
# factors T-207's panel builder computes under the same name; validation compares these.
PANEL_COUNTERPARTS = {
    "q_pat_yoy": "q_pat_yoy",
    "ttm_rev_yoy": "ttm_rev_yoy",
    "ttm_pat_yoy": "ttm_pat_yoy",
    "op_margin": "op_margin",
    "op_margin_chg": "op_margin_chg",
    "earnings_yield": "earnings_yield",
    "sales_yield": "sales_yield",
    "fin_cost_to_rev": "fin_cost_to_rev",
    "promoter_chg_1q": "promoter_chg_1q",
    "promoter_chg_4q": "promoter_chg_4q",
    "delivery_3m": "delivery_3m",
    "mom_12_1": "mom_12_1",
    "vol_12m": "vol_12m",
    "size": "size",
}
FACTOR_PROVENANCE = {
    **{f: "prov_fin" for f in FIN_FACTORS},
    **{f: "prov_owner" for f in ("promoter_chg_1q", "promoter_chg_4q", "fpi_chg_4q", "mf_chg_4q", "pledge_pct")},
    "net_debt_chg_4q": "prov_mcap",
    "delivery_3m": "prov_px", "mom_12_1": "prov_px", "vol_12m": "prov_px", "size": "prov_mcap",
    "guidance_rev": "prov_guidance", "guidance_growth": "prov_guidance",
    "order_cover": "prov_kpi",
}
PERIOD_RE = re.compile(r"^(Q[1-4]|H1|9M|FY)(?:FY)?(\d{2}|\d{4})$")
REV_LINES = ("revenue_from_operations", "total_income")
PAT_LINES = ("pat", "pat_continuing")
QTR_LINES = ("revenue_from_operations", "total_income", "pat", "pat_continuing", "total_expenses",
             "finance_cost", "depreciation")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def store_paths(root: Path | str = STORE_ROOT) -> list[Path]:
    """The 91 main store files; a ``cNN_ocr.db``, ``pages.db`` or crash copy is not one."""
    root = Path(root)
    out: list[Path] = []
    for folder in sorted(root.glob("c[0-9][0-9]")):
        path = folder / f"{folder.name}.db"
        if path.exists():
            out.append(path)
    return out


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return _fetchone(con, "SELECT 1 FROM sqlite_master WHERE name=?", (name,)) is not None


def _fetchall(con: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    cursor = con.cursor()
    cursor.execute(sql, params)
    return cursor.fetchall()


def _fetchone(con: sqlite3.Connection, sql: str, params: tuple = ()) -> tuple | None:
    cursor = con.cursor()
    cursor.execute(sql, params)
    return cursor.fetchone()


def _read(con: sqlite3.Connection, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, con)


def _num(frame: pd.DataFrame, cols: tuple[str, ...] | list[str]) -> pd.DataFrame:
    for col in cols:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def avail_sessions(known_at: pd.Series, sessions: pd.DatetimeIndex) -> pd.Series:
    """First trading session on which each stored timestamp was usable.

    Store ``known_at`` values are naive IST timestamps (``2024-05-27T18:06:07``);
    a date-only value means midnight, so it is usable that session.  The
    after-15:30 rule lives in ``factor_weights.pit_sessions``.
    """
    ts = pd.to_datetime(pd.Series(known_at), errors="coerce")
    if ts.empty:
        return pd.Series(pd.NaT, index=ts.index, dtype="datetime64[ns]")
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(IST, ambiguous="NaT", nonexistent="NaT")
    return pit_sessions(ts.dt.tz_convert("UTC"), sessions)


def session_calendar(paths: list[Path]) -> pd.DatetimeIndex:
    """Union of NSE session dates across the stores (BSE when a store has no NSE rows)."""
    dates: set[str] = set()
    for path in paths:
        con: sqlite3.Connection = connect_ro(path, timeout_s=60)
        try:
            rows = _fetchall(con, "SELECT DISTINCT date FROM price_delivery WHERE exchange='NSE'")
            if not rows:
                rows = _fetchall(con, "SELECT DISTINCT date FROM price_delivery")
        finally:
            con.close()
        dates.update(str(row[0]) for row in rows if row[0])
    return pd.DatetimeIndex(sorted(pd.to_datetime(list(dates))))


def month_end_sessions(sessions: pd.DatetimeIndex, start: str, end: str | None = None) -> pd.DatetimeIndex:
    """Last trading session of every month from ``start`` (itself a month-end) onward."""
    dates = pd.DatetimeIndex(sessions)
    lo = pd.Timestamp(start)
    dates = dates[dates >= lo]
    if end is not None:
        dates = dates[dates <= pd.Timestamp(end)]
    frame = pd.DataFrame({"date": dates})
    frame["month"] = frame["date"].dt.to_period("M")
    return pd.DatetimeIndex(frame.groupby("month")["date"].max().sort_values())


def _basename(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("\\", "/").split("/")[-1]


def _prov(row: pd.Series, table_col: str = "source_table", source_col: str = "source") -> str:
    page = row.get("page")
    page_txt = "" if pd.isna(page) else f"p{int(page)}"
    return (f"{row.get(table_col)}:{_basename(row.get(source_col))}:{page_txt}"
            f"@{row.get('known_at')}:{row.get('fiscal_period', '')}")


# --------------------------------------------------------------------------- #
# Load one store (read-only)
# --------------------------------------------------------------------------- #
def _load_fin(con: sqlite3.Connection) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if _has_table(con, "fin_quarter_xbrl"):
        frames.append(_read(con, """
            SELECT symbol, fiscal_period, period_end, basis, line_item, value, scale, known_at,
                   'fin_quarter_xbrl' AS source_table, source_file AS source, NULL AS page
            FROM fin_quarter_xbrl WHERE preferred_from IS NOT NULL
        """))
    if _has_table(con, "fin_quarter_printed"):
        frames.append(_read(con, """
            SELECT symbol, fiscal_period, period_end, basis, line_item, value, scale, known_at,
                   'fin_quarter_printed' AS source_table, doc_key AS source, page
            FROM fin_quarter_printed WHERE preferred_from IS NOT NULL
        """))
    if not frames:
        return pd.DataFrame(columns=["symbol", "fiscal_period", "period_end", "basis", "line_item",
                                     "value_inr", "known_at", "source_table", "source", "page", "avail"])
    fin = pd.concat(frames, ignore_index=True)
    fin = _num(fin, ("value", "scale", "page"))
    fin["period_end"] = pd.to_datetime(fin["period_end"], errors="coerce")
    fin["value_inr"] = fin["value"] * fin["scale"].fillna(1.0)
    return fin.dropna(subset=["value_inr", "period_end"]).reset_index(drop=True)


def _load_prices(con: sqlite3.Connection) -> pd.DataFrame:
    if not _has_table(con, "price_delivery"):
        return pd.DataFrame(columns=["adj_close", "delivery_pct"])
    px = _read(con, "SELECT date, exchange, close, adj_close, delivery_pct FROM price_delivery")
    if px.empty:
        return pd.DataFrame(columns=["adj_close", "delivery_pct"])
    px = _num(px, ("close", "adj_close", "delivery_pct"))
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px = px.dropna(subset=["date"])
    px["_nse"] = (px["exchange"].astype("string").str.upper() == "NSE").astype(int)
    px = px.sort_values(["date", "_nse"]).drop_duplicates("date", keep="last").sort_values("date")
    px["adj"] = px["adj_close"].where(px["adj_close"].notna(), px["close"])
    return px.set_index("date")[["adj", "delivery_pct"]]


def _load_valuation(con: sqlite3.Connection) -> pd.DataFrame:
    if not _has_table(con, "valuation_daily"):
        return pd.DataFrame(columns=["market_cap", "net_debt"])
    val = _read(con, "SELECT date, market_cap, net_debt FROM valuation_daily")
    if val.empty:
        return pd.DataFrame(columns=["market_cap", "net_debt"])
    val = _num(val, ("market_cap", "net_debt"))
    val["date"] = pd.to_datetime(val["date"], errors="coerce")
    val = val.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")
    return val.set_index("date")[["market_cap", "net_debt"]]


def _load_shp(con: sqlite3.Connection) -> pd.DataFrame:
    if not _has_table(con, "shp_category"):
        return pd.DataFrame(columns=["quarter_end", "category", "pct", "known_at", "source_file", "avail"])
    shp = _read(con, "SELECT quarter_end, category, pct, known_at, source_file FROM shp_category")
    if shp.empty:
        return shp
    shp = _num(shp, ("pct",))
    shp["quarter_end"] = pd.to_datetime(shp["quarter_end"], errors="coerce")
    # keep every filing row: a revised quarter must not overwrite its own original
    # before the revision is known.  NSE/BSE twins are collapsed per day in the factor.
    return shp.dropna(subset=["quarter_end", "pct"]).sort_values(
        ["quarter_end", "known_at"]).reset_index(drop=True)


def _load_pledge(con: sqlite3.Connection) -> pd.DataFrame:
    if not _has_table(con, "shp_pledge"):
        return pd.DataFrame(columns=["quarter_end", "pledge_flag", "pledged_pct", "known_at", "avail"])
    pl = _read(con, "SELECT quarter_end, pledge_flag, pledged_pct, known_at FROM shp_pledge")
    if pl.empty:
        return pl
    pl = _num(pl, ("pledged_pct",))
    pl["quarter_end"] = pd.to_datetime(pl["quarter_end"], errors="coerce")
    return pl.dropna(subset=["quarter_end"]).sort_values(
        ["quarter_end", "known_at"]).reset_index(drop=True)


def _load_guidance(con: sqlite3.Connection) -> pd.DataFrame:
    if not _has_table(con, "guidance"):
        return pd.DataFrame(columns=["id", "metric", "low", "high", "unit", "revision_of", "known_at", "avail"])
    gd = _read(con, """
        SELECT id, metric, target_period, low, high, unit, revision_of, known_at, doc_key, page
        FROM guidance
    """)
    if gd.empty:
        return gd
    gd = _num(gd, ("id", "low", "high", "revision_of", "page"))
    return gd


def _load_kpi(con: sqlite3.Connection) -> pd.DataFrame:
    if not _has_table(con, "kpi_series"):
        return pd.DataFrame(columns=["metric", "value", "scale", "known_at", "avail"])
    kpi = _read(con, """
        SELECT metric, dimension, value, unit, scale, fiscal_period, known_at, doc_key, page
        FROM kpi_series WHERE metric = 'order_book'
    """)
    if kpi.empty:
        return kpi
    return _num(kpi, ("value", "scale", "page"))


def load_store(path: Path, sessions: pd.DatetimeIndex) -> dict[str, Any]:
    """Every row one store can offer, read-only, with its PIT availability session."""
    con: sqlite3.Connection = connect_ro(path, timeout_s=60)
    try:
        symbol = path.stem.upper()
        isin = ""
        if _has_table(con, "company"):
            row = _fetchone(con, "SELECT symbol FROM company LIMIT 1")
            if row and row[0]:
                symbol = str(row[0])
            row = _fetchone(
                con, "SELECT isin FROM price_delivery WHERE isin IS NOT NULL ORDER BY date DESC LIMIT 1"
            ) if _has_table(con, "price_delivery") else None
            if row and row[0]:
                isin = str(row[0])
            else:
                row = _fetchone(
                    con,
                    "SELECT isin FROM company WHERE isin IS NOT NULL AND isin NOT LIKE 'INE_AUTO%' LIMIT 1",
                )
                isin = str(row[0]) if row and row[0] else ""
        px = _load_prices(con)
        val = _load_valuation(con)
        fin = _load_fin(con)
        shp = _load_shp(con)
        pledge = _load_pledge(con)
        guidance = _load_guidance(con)
        kpi = _load_kpi(con)
    finally:
        con.close()

    for frame in (fin, shp, pledge, guidance, kpi):
        if not frame.empty:
            frame["avail"] = avail_sessions(frame["known_at"], sessions)
    basis = ""
    if not fin.empty:
        counts = fin["basis"].value_counts()
        basis = "consolidated" if counts.get("consolidated", 0) >= counts.get("standalone", 0) else "standalone"
        if basis not in counts.index:
            basis = str(counts.index[0])
        fin = fin[fin["basis"] == basis].reset_index(drop=True)
    return {
        "path": path, "store": path.parent.name, "symbol": symbol, "isin": isin, "basis": basis,
        "px": px, "val": val, "fin": fin, "shp": shp, "pledge": pledge,
        "guidance": guidance, "kpi": kpi,
    }


# --------------------------------------------------------------------------- #
# Point-in-time election and quarterly grid
# --------------------------------------------------------------------------- #
def elect_asof(facts: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    """One preferred row per (fiscal_period, line_item) as of ``day``.

    Only rows the store's election typed with a ``preferred_from`` window are
    candidates (the loader already dropped the rest).  The newest availability
    session at or before ``day`` wins, so ``preferred_to`` hands the key to the
    next row on the session its filing became usable -- not before.
    """
    if facts is None or facts.empty:
        return facts
    sub = facts[facts["avail"].notna() & (facts["avail"] <= day)]
    if sub.empty:
        return sub
    return sub.sort_values(["avail", "known_at"]).drop_duplicates(
        ["fiscal_period", "line_item"], keep="last"
    )


def _period_parts(label: Any) -> tuple[str, int] | None:
    text = re.sub(r"\s+", "", str(label or "")).upper()
    match = PERIOD_RE.match(text)
    if not match:
        return None
    kind, year = match.group(1), match.group(2)
    fiscal_year = int(year)
    if fiscal_year >= 1900:
        fiscal_year -= 2000
    return kind, fiscal_year


def quarter_end(kind: int, fiscal_year: int) -> pd.Timestamp:
    """Calendar quarter end for an Indian fiscal quarter (Q1 = Apr-Jun)."""
    end = pd.Timestamp(year=2000 + fiscal_year, month=3, day=31)
    return pd.Timestamp(end - pd.DateOffset(months=3 * (4 - kind)))


def _line(frame: pd.DataFrame, names: tuple[str, ...]) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return pd.to_numeric(frame[name], errors="coerce")
    return pd.Series(np.full(len(frame.index), np.nan), index=frame.index, dtype=float)


def quarter_grid(elected: pd.DataFrame) -> pd.DataFrame:
    """Quarterly values from the elected rows, deriving a missing quarter from YTD.

    A reported Q row wins; else Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M, the
    same fallback ``factor_weights.quarter_facts`` applies to XBRL filings.
    Only the six lines the factors need are carried.
    """
    if elected is None or elected.empty:
        return pd.DataFrame()
    vals = elected.pivot_table(index="fiscal_period", columns="line_item",
                               values="value_inr", aggfunc="last")
    vals.index = [re.sub(r"\s+", "", str(label)).upper() for label in vals.index]
    vals = vals[~vals.index.duplicated(keep="last")]
    quarters: dict[tuple[int, int], pd.Series] = {}
    fiscal_years: set[int] = set()
    for label in vals.index:
        parts = _period_parts(label)
        if parts is None:
            continue
        kind, fiscal_year = parts
        fiscal_years.add(fiscal_year)
        if kind.startswith("Q"):
            quarters[(fiscal_year, int(kind[1]))] = vals.loc[label]
    for fiscal_year in sorted(fiscal_years):
        h1 = vals.loc[f"H1FY{fiscal_year:02d}"] if f"H1FY{fiscal_year:02d}" in vals.index else None
        nine = vals.loc[f"9MFY{fiscal_year:02d}"] if f"9MFY{fiscal_year:02d}" in vals.index else None
        annual = vals.loc[f"FY{fiscal_year:02d}"] if f"FY{fiscal_year:02d}" in vals.index else None
        q1 = quarters.get((fiscal_year, 1))
        if q1 is not None and h1 is not None and (fiscal_year, 2) not in quarters:
            quarters[(fiscal_year, 2)] = h1 - q1
        if h1 is not None and nine is not None and (fiscal_year, 3) not in quarters:
            quarters[(fiscal_year, 3)] = nine - h1
        if nine is not None and annual is not None and (fiscal_year, 4) not in quarters:
            quarters[(fiscal_year, 4)] = annual - nine
    if not quarters:
        return pd.DataFrame()
    frame = pd.DataFrame({quarter_end(kind, fiscal_year): series
                          for (fiscal_year, kind), series in quarters.items()})
    grid = frame.T.sort_index()
    grid = grid[~grid.index.duplicated(keep="last")]
    if not any(line in grid.columns for line in QTR_LINES):
        return pd.DataFrame()
    out = pd.DataFrame(index=grid.index)
    out["rev"] = _line(grid, REV_LINES)
    out["pat"] = _line(grid, PAT_LINES)
    out["exp"] = _line(grid, ("total_expenses",))
    out["fin"] = _line(grid, ("finance_cost",)).fillna(0.0)
    out["dep"] = _line(grid, ("depreciation",)).fillna(0.0)
    out["op"] = (out["rev"] - (out["exp"] - out["fin"] - out["dep"])).where(out["exp"].notna())
    return out


def financial_factors(grid: pd.DataFrame) -> dict[str, float]:
    """TTM / quarter factors from one company's elected quarter grid.

    Mirrors ``factor_weights.quarter_facts``: four consecutive quarters for a
    TTM (span 250-290 days), eight for a YoY pair (620-660).  The year-ago base
    is matched by period end (330-400 days earlier), never by row position: a
    quarter that prints only as an annual column leaves a hole, and a positional
    shift would then compare two different fiscal quarters.
    """
    out: dict[str, float] = {}
    if grid is None or grid.empty:
        return out
    q = grid.sort_index()
    index = q.index
    count = len(q)
    rev, pat, op, fin = _line(q, ("rev",)), _line(q, ("pat",)), _line(q, ("op",)), _line(q, ("fin",))

    def span(start: int, end: int) -> int:
        return int((index[end] - index[start]).days)

    def year_ago(end: int) -> int | None:
        """Row index of the fiscal quarter one year before row ``end``."""
        for pos in range(end, -1, -1):
            days = int((index[end] - index[pos]).days)
            if 330 <= days <= 400:
                return pos
            if days > 400:
                return None
        return None

    ok_4 = count >= 4 and 250 <= span(count - 4, count - 1) <= 290
    base = year_ago(count - 1)

    if base is not None:
        cur, prev = rev.iloc[-1], rev.iloc[base]
        if pd.notna(cur) and pd.notna(prev) and prev > 0:
            out["q_rev_yoy"] = float(cur / prev - 1.0)
        cur, prev = pat.iloc[-1], pat.iloc[base]
        if pd.notna(cur) and cur > 0 and pd.notna(prev) and prev != 0:
            out["q_pat_yoy"] = float(cur / prev - 1.0)

    ttm_rev = ttm_pat = ttm_op = ttm_fin = np.nan
    if ok_4:
        ttm_rev = rev.iloc[-4:].sum(min_count=4)
        ttm_pat = pat.iloc[-4:].sum(min_count=4)
        ttm_op = op.iloc[-4:].sum(min_count=4)
        ttm_fin = fin.iloc[-4:].sum(min_count=4)
        out["ttm_rev"] = float(ttm_rev) if pd.notna(ttm_rev) else np.nan
        out["ttm_pat"] = float(ttm_pat) if pd.notna(ttm_pat) else np.nan
        if pd.notna(ttm_rev) and ttm_rev != 0:
            if pd.notna(ttm_op):
                out["op_margin"] = float(ttm_op / ttm_rev)
            out["fin_cost_to_rev"] = float(ttm_fin / ttm_rev)
    prev_rev = prev_pat = prev_op = np.nan
    if base is not None and base >= 3 and 250 <= span(base - 3, base) <= 290:
        prev_rev = rev.iloc[base - 3: base + 1].sum(min_count=4)
        prev_pat = pat.iloc[base - 3: base + 1].sum(min_count=4)
        prev_op = op.iloc[base - 3: base + 1].sum(min_count=4)
    if pd.notna(ttm_rev) and pd.notna(prev_rev) and prev_rev > 0:
        out["ttm_rev_yoy"] = float(ttm_rev / prev_rev - 1.0)
    if pd.notna(ttm_pat) and pd.notna(prev_pat) and prev_pat > 0:
        out["ttm_pat_yoy"] = float(ttm_pat / prev_pat - 1.0)
    if (pd.notna(ttm_rev) and pd.notna(ttm_op) and pd.notna(prev_op)
            and pd.notna(prev_rev) and prev_rev != 0):
        out["op_margin_chg"] = float(ttm_op / ttm_rev - prev_op / prev_rev)
    return out


# --------------------------------------------------------------------------- #
# Factor blocks (all pure: a loaded store plus one month-end)
# --------------------------------------------------------------------------- #
def price_factors(px: pd.DataFrame, day: pd.Timestamp) -> dict[str, Any]:
    """Momentum, volatility and delivery as of an exact session."""
    out: dict[str, Any] = {"mom_12_1": np.nan, "vol_12m": np.nan, "delivery_3m": np.nan,
                           "price": np.nan, "prov_px": ""}
    if px is None or px.empty:
        return out
    index = pd.DatetimeIndex(px.index)
    pos = int(index.searchsorted(day))
    if pos >= len(index) or index[pos] != day:
        return out
    adj = pd.to_numeric(px["adj"], errors="coerce").to_numpy(dtype=float)
    out["price"] = float(adj[pos]) if np.isfinite(adj[pos]) else np.nan
    if pos >= 252 and np.isfinite(adj[pos]) and np.isfinite(adj[pos - 21]) and adj[pos - 252] > 0:
        out["mom_12_1"] = float(adj[pos - 21] / adj[pos - 252] - 1.0)
    if pos >= 252:
        window = adj[pos - 251: pos + 1]
        if np.isfinite(window).all() and (window > 0).all():
            returns = np.diff(np.log(window))
            if len(returns) >= 2:
                out["vol_12m"] = float(np.std(returns, ddof=1))
    delivery = pd.to_numeric(px["delivery_pct"], errors="coerce").to_numpy(dtype=float)
    window = delivery[max(0, pos - 62): pos + 1]
    if np.isfinite(window).any():
        out["delivery_3m"] = float(np.nanmean(window))
    out["prov_px"] = f"price_delivery:NSE {day.date()}"
    return out


def ownership_factors(shp: pd.DataFrame, pledge: pd.DataFrame, day: pd.Timestamp) -> dict[str, Any]:
    """Promoter / FPI / MF percentage-point changes and the printed pledge %.

    The change is against the previous available quarter row and the fourth
    previous one, as T-207's ``promoter_history`` does.
    """
    out: dict[str, Any] = {
        "promoter_chg_1q": np.nan, "promoter_chg_4q": np.nan, "fpi_chg_4q": np.nan,
        "mf_chg_4q": np.nan, "pledge_pct": np.nan, "prov_owner": "",
    }
    if shp is not None and not shp.empty and "avail" in shp.columns:
        sub = shp[shp["avail"].notna() & (shp["avail"] <= day)]
        # a revised quarter replaces its own original only from the revision's
        # availability session; NSE/BSE twins of one filing collapse to one row.
        sub = sub.sort_values(["quarter_end", "known_at", "pct"])
        sub = sub.drop_duplicates(["quarter_end", "category"], keep="last")
        for category, one, four in (("promoter", "promoter_chg_1q", "promoter_chg_4q"),
                                    ("fpi_total", None, "fpi_chg_4q"),
                                    ("mutual_funds", None, "mf_chg_4q")):
            rows = sub[sub["category"] == category].sort_values("quarter_end")
            if rows.empty:
                continue
            values = pd.to_numeric(rows["pct"], errors="coerce").to_numpy(dtype=float)
            if one is not None and len(values) >= 2 and np.isfinite(values[-2]):
                out[one] = float(values[-1] - values[-2])
            if four is not None and len(values) >= 5 and np.isfinite(values[-5]):
                out[four] = float(values[-1] - values[-5])
            last = rows.iloc[-1]
            out["prov_owner"] = f"shp_category:{_basename(last.get('source_file'))}@{last.get('known_at')}"
    if pledge is not None and not pledge.empty and "avail" in pledge.columns:
        sub = pledge[pledge["avail"].notna() & (pledge["avail"] <= day)]
        sub = sub.sort_values(["quarter_end", "known_at"]).drop_duplicates("quarter_end", keep="last")
        if not sub.empty:
            last = sub.iloc[-1]
            if pd.notna(last.get("pledged_pct")):
                out["pledge_pct"] = float(last["pledged_pct"])
            elif str(last.get("pledge_flag", "")).strip() in ("0", "0.0", "N", "n", "False"):
                out["pledge_pct"] = 0.0
    return out


def _midpoint(low: Any, high: Any) -> float | None:
    values = [float(v) for v in (low, high) if pd.notna(v)]
    if not values:
        return None
    return float(np.mean(values))


def guidance_factors(guidance: pd.DataFrame, day: pd.Timestamp, ttm_rev_yoy: float) -> dict[str, Any]:
    """Latest revenue-growth guidance: revised up (+1) / down (-1) / none (0).

    ``guidance_growth`` is the guided midpoint (percent) minus the trailing TTM
    revenue growth, so a positive number means the company guides above what it
    has already delivered.
    """
    out: dict[str, Any] = {"guidance_rev": np.nan, "guidance_growth": np.nan, "prov_guidance": ""}
    if guidance is None or guidance.empty or "avail" not in guidance.columns:
        return out
    metric = guidance["metric"].astype("string").str.lower()
    sub = guidance[(metric == "revenue_growth") & guidance["avail"].notna() & (guidance["avail"] <= day)]
    if sub.empty:
        return out
    sub = sub.sort_values(["known_at", "id"])
    last = sub.iloc[-1]
    out["guidance_rev"] = 0.0
    revision_of = last.get("revision_of")
    if pd.notna(revision_of):
        prior = guidance[guidance["id"] == revision_of]
        if not prior.empty:
            before = _midpoint(prior.iloc[0].get("low"), prior.iloc[0].get("high"))
            after = _midpoint(last.get("low"), last.get("high"))
            if before is not None and after is not None and after != before:
                out["guidance_rev"] = 1.0 if after > before else -1.0
    midpoint = _midpoint(last.get("low"), last.get("high"))
    unit = str(last.get("unit") or "").strip().lower()
    if midpoint is not None and unit in ("pct", "percent", "%") and pd.notna(ttm_rev_yoy):
        out["guidance_growth"] = float(midpoint / 100.0 - ttm_rev_yoy)
    page = last.get("page")
    page_txt = "" if pd.isna(page) else f"p{int(page)}"
    out["prov_guidance"] = (f"guidance:{_basename(last.get('doc_key'))}:{page_txt}"
                            f"@{last.get('known_at')}:{last.get('target_period')}")
    return out


def kpi_factors(kpi: pd.DataFrame, day: pd.Timestamp, ttm_rev: float) -> dict[str, Any]:
    """Order-book cover: the latest stated order book over the current TTM revenue."""
    out: dict[str, Any] = {"order_cover": np.nan, "prov_kpi": ""}
    if kpi is None or kpi.empty or "avail" not in kpi.columns or not pd.notna(ttm_rev) or ttm_rev <= 0:
        return out
    sub = kpi[kpi["avail"].notna() & (kpi["avail"] <= day)]
    if "dimension" in sub.columns:
        total = sub[sub["dimension"].fillna("total").astype("string").str.lower() == "total"]
        if not total.empty:
            sub = total
    if sub.empty:
        return out
    sub = sub.sort_values(["known_at", "value"])
    last = sub.iloc[-1]
    raw_value = last.get("value")
    raw_scale = last.get("scale")
    value = float(raw_value) if pd.notna(raw_value) else np.nan
    scale = float(raw_scale) if pd.notna(raw_scale) else 1.0
    if pd.notna(value):
        out["order_cover"] = float(value * (scale if pd.notna(scale) else 1.0) / ttm_rev)
        page = last.get("page")
        page_txt = "" if pd.isna(page) else f"p{int(page)}"
        out["prov_kpi"] = f"kpi_series:{_basename(last.get('doc_key'))}:{page_txt}@{last.get('known_at')}"
    return out


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #
def panel_row(store: dict[str, Any], day: pd.Timestamp) -> dict[str, Any]:
    """Every factor one company has at one month-end, plus its source row."""
    row: dict[str, Any] = {
        "date": day, "store": store["store"], "symbol": store["symbol"], "isin": store["isin"],
        "basis": store.get("basis", ""),
        **{factor: np.nan for factor in FACTORS},
        "price": np.nan, "mcap": np.nan, "net_debt": np.nan, "ttm_rev": np.nan, "ttm_pat": np.nan,
        "prov_fin": "", "prov_mcap": "", "prov_px": "", "prov_owner": "",
        "prov_guidance": "", "prov_kpi": "", "sector": "",
    }
    row.update(price_factors(store["px"], day))
    val = store["val"]
    if val is not None and not val.empty:
        pos = int(val.index.searchsorted(day, side="right")) - 1
        if pos >= 0:
            snap = val.iloc[pos]
            row["mcap"] = snap.get("market_cap", np.nan)
            row["net_debt"] = snap.get("net_debt", np.nan)
            row["prov_mcap"] = (f"valuation_daily:{val.index[pos].date()}"
                                f"@{snap.get('known_at', val.index[pos].date())}")

    fin = store["fin"]
    elected = elect_asof(fin, day) if fin is not None and not fin.empty else pd.DataFrame()
    grid = quarter_grid(elected) if not elected.empty else pd.DataFrame()
    fin_values = financial_factors(grid)
    row.update({k: fin_values.get(k, np.nan) for k in FIN_FACTORS})
    row["ttm_rev"] = fin_values.get("ttm_rev", np.nan)
    row["ttm_pat"] = fin_values.get("ttm_pat", np.nan)
    if not elected.empty:
        sources = elected[elected["line_item"].isin(REV_LINES + PAT_LINES)]
        if not sources.empty:
            latest = sources.sort_values(["period_end", "avail"]).iloc[-1]
            row["prov_fin"] = _prov(latest)

    mcap = row["mcap"]
    if pd.notna(mcap) and mcap > 0:
        row["size"] = float(np.log(mcap))
        if pd.notna(row["ttm_pat"]):
            row["earnings_yield"] = float(row["ttm_pat"] / mcap)
        row["sales_yield"] = float(row["ttm_rev"] / mcap) if pd.notna(row["ttm_rev"]) else np.nan

    row.update(ownership_factors(store["shp"], store["pledge"], day))
    row.update(guidance_factors(store["guidance"], day, row["ttm_rev_yoy"]))
    row.update(kpi_factors(store["kpi"], day, row["ttm_rev"]))
    return row


def build_panel(stores: list[dict[str, Any]], month_ends: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per (store, month-end); every value is point in time."""
    rows = [panel_row(store, day) for store in stores for day in month_ends]
    panel = pd.DataFrame(rows)
    if panel.empty:
        return panel
    panel = panel.sort_values(["store", "date"]).reset_index(drop=True)
    # net debt change over four quarters, scaled by the current TTM revenue so
    # the factor is not just company size.
    previous = panel.groupby("store", sort=False)["net_debt"].shift(12)
    previous_date = panel.groupby("store", sort=False)["date"].shift(12)
    gap = (panel["date"] - previous_date).dt.days
    ok = gap.between(330, 400) & previous.notna() & panel["net_debt"].notna() & (panel["ttm_rev"] > 0)
    panel["net_debt_chg_4q"] = ((panel["net_debt"] - previous) / panel["ttm_rev"]).where(ok)
    return panel.sort_values(["date", "store"]).reset_index(drop=True)


def excess_returns(returns: pd.DataFrame) -> pd.DataFrame:
    """Excess return = raw return minus the equal-weight mean of that month's names."""
    out = returns.copy()
    out["excess"] = out["ret"] - out.groupby(["date", "horizon"], sort=False)["ret"].transform("mean")
    return out


def attach_targets(panel: pd.DataFrame, stores: list[dict[str, Any]],
                   sessions: pd.DatetimeIndex, month_ends: pd.DatetimeIndex) -> pd.DataFrame:
    """Forward 3/6/12-month adjusted-close returns and their month excess."""
    calendar = {day: index for index, day in enumerate(sessions)}
    records: list[tuple[str, pd.Timestamp, str, float]] = []
    for store in stores:
        px = store["px"]
        if px is None or px.empty:
            continue
        close = pd.to_numeric(px["adj"], errors="coerce")
        for day in month_ends:
            index = calendar.get(day)
            if index is None or day not in close.index:
                continue
            start = close.loc[day]
            if not pd.notna(start) or start <= 0:
                continue
            for label, offset in HORIZONS.items():
                if index + offset >= len(sessions):
                    continue
                future = sessions[index + offset]
                end = close.get(future)
                if end is not None and pd.notna(end):
                    records.append((store["store"], day, label, float(end / start - 1.0)))
    if not records:
        return panel
    returns = pd.DataFrame(records, columns=["store", "date", "horizon", "ret"])
    returns = excess_returns(returns)
    raw = returns.pivot(index=["store", "date"], columns="horizon", values="ret").add_prefix("ret_")
    exc = returns.pivot(index=["store", "date"], columns="horizon", values="excess").add_prefix("excess_")
    panel = panel.merge(raw.reset_index(), on=["store", "date"], how="left")
    panel = panel.merge(exc.reset_index(), on=["store", "date"], how="left")
    return panel


# --------------------------------------------------------------------------- #
# Validation against the T-118 / T-207 truth panel
# --------------------------------------------------------------------------- #
def build_truth_panel(out_dir: Path, start: str = TRUTH_START, end: str = TRUTH_END,
                      rebuild: bool = False) -> Path:
    """Build the T-118 monthly panel from the read-only truth snapshot (streaming)."""
    path = out_dir / TRUTH_PANEL_NAME
    if path.exists() and not rebuild:
        return path
    meta = build_panel_parquet(default_snapshot(), start, end, path, memory_limit="2GB", threads=2)
    print(f"truth panel: {meta['rows']} rows, {meta['companies']} companies, "
          f"{meta['rebalances']} month-ends {meta['first_date']}..{meta['last_date']}", flush=True)
    return path


def load_truth(truth_path: Path, dates: Any) -> pd.DataFrame:
    """The T-207 panel columns validation needs, for the panel's month-ends."""
    columns = ["date", "isin", "symbol", "sector", *dict.fromkeys(PANEL_COUNTERPARTS.values())]
    truth = pd.read_parquet(truth_path, columns=columns)
    truth["date"] = pd.to_datetime(truth["date"])
    truth = truth[truth["date"].isin(pd.DatetimeIndex(dates))]
    return truth.drop_duplicates(["date", "isin"])


def attach_sector(panel: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Link every store to the truth panel's ISIN (symbol fallback) and get its sector.

    The sector label is today's, exactly T-207's caveat.  It is used only to
    null the margin factors for financials, whose "expenses" are not COGS.
    """
    out = panel.copy()
    known = set(truth["isin"].dropna().astype(str))
    linked = out["isin"].astype("string").where(out["isin"].astype("string").isin(known))
    missing = linked.isna()
    if missing.any():
        symbol_map = truth.drop_duplicates("symbol").set_index("symbol")["isin"]
        linked.loc[missing] = out.loc[missing, "symbol"].map(symbol_map)
    out["link_isin"] = linked
    sector = truth.drop_duplicates("isin").set_index("isin")["sector"]
    out["sector"] = out["link_isin"].map(sector)
    financial = out["sector"].fillna("").str.contains("Financial", case=False)
    out.loc[financial, ["op_margin", "op_margin_chg", "fin_cost_to_rev"]] = np.nan
    return out


def validate(panel: pd.DataFrame, truth: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """Store factors vs the T-207 panel on the same company-months."""
    right = truth.rename(columns={
        "isin": "link_isin",
        **{name: f"panel_{name}" for name in PANEL_COUNTERPARTS.values()},
    })
    merged = panel.merge(right, on=["date", "link_isin"], how="inner", suffixes=("", "_truth"))
    stats: list[dict[str, Any]] = []
    worst: list[pd.DataFrame] = []
    for factor in FACTORS:
        panel_factor = PANEL_COUNTERPARTS.get(factor)
        entry: dict[str, Any] = {"factor": factor, "panel_factor": panel_factor or "",
                                 "overlap": 0, "rho": np.nan, "within_5pct": np.nan,
                                 "median_rel_diff": np.nan,
                                 "note": "" if panel_factor else "no T-207 counterpart (new factor)"}
        if panel_factor is None:
            stats.append(entry)
            continue
        panel_col = f"panel_{panel_factor}"
        pair = merged[["date", "symbol", "store", factor, panel_col,
                       FACTOR_PROVENANCE.get(factor, "prov_fin")]].copy()
        pair[factor] = pd.to_numeric(pair[factor], errors="coerce")
        pair[panel_col] = pd.to_numeric(pair[panel_col], errors="coerce")
        pair = pair.replace([np.inf, -np.inf], np.nan).dropna(subset=[factor, panel_col])
        entry["overlap"] = int(len(pair))
        if len(pair) < 5:
            entry["note"] = "too few overlapping company-months"
            stats.append(entry)
            continue
        entry["rho"] = float(spearman_ic(pair[factor], pair[panel_col], min_n=5))
        denom = pair[panel_col].abs().replace(0.0, np.nan)
        pair["rel_diff"] = (pair[factor] - pair[panel_col]).abs() / denom
        entry["within_5pct"] = float((pair["rel_diff"] <= 0.05).mean())
        entry["median_rel_diff"] = float(pair["rel_diff"].median())
        stats.append(entry)
        top = pair.nlargest(10, "rel_diff").copy()
        top["factor"] = factor
        top["panel_factor"] = panel_factor
        top["prov_column"] = FACTOR_PROVENANCE.get(factor, "prov_fin")
        worst.append(top)
    validation = pd.DataFrame(stats)
    validation.to_csv(out_dir / "validation.csv", index=False)
    if worst:
        pd.concat(worst, ignore_index=True).to_csv(out_dir / "validation_worst.csv", index=False)
    return validation


# --------------------------------------------------------------------------- #
# Coverage
# --------------------------------------------------------------------------- #
def coverage(panel: pd.DataFrame, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-factor company counts per month-end and per-month target coverage."""
    dates = sorted(panel["date"].unique())
    factor_rows = []
    for factor in FACTORS:
        counts = [int(panel.loc[panel["date"] == day, factor].notna().sum()) for day in dates]
        counts = [count for count in counts if count > 0]
        factor_rows.append({
            "factor": factor,
            "months_with_value": len(counts),
            "min_names": int(np.min(counts)) if counts else 0,
            "median_names": float(np.median(counts)) if counts else 0.0,
            "max_names": int(np.max(counts)) if counts else 0,
            "total_values": int(panel[factor].notna().sum()),
        })
    factor_cov = pd.DataFrame(factor_rows)
    month_rows = []
    for day in dates:
        block = panel[panel["date"] == day]
        month_rows.append({
            "date": pd.Timestamp(day).date().isoformat(),
            "companies": int(len(block)),
            "with_3m_target": int(block["ret_3m"].notna().sum()) if "ret_3m" in block else 0,
            "with_6m_target": int(block["ret_6m"].notna().sum()) if "ret_6m" in block else 0,
            "with_12m_target": int(block["ret_12m"].notna().sum()) if "ret_12m" in block else 0,
        })
    month_cov = pd.DataFrame(month_rows)
    factor_cov.to_csv(out_dir / "coverage_factor.csv", index=False)
    month_cov.to_csv(out_dir / "coverage_month.csv", index=False)
    return factor_cov, month_cov


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-229 stage A: store-derived PIT factor panel")
    parser.add_argument("--stores", default=str(STORE_ROOT), help="tg_build/measure10 root")
    parser.add_argument("--out", default=".tmp/t229", help="output directory")
    parser.add_argument("--start", default=START_DEFAULT, help="first month-end (inclusive)")
    parser.add_argument("--end", default=None, help="last calendar day (inclusive)")
    parser.add_argument("--rebuild-truth", action="store_true", help="rebuild the truth panel parquet")
    parser.add_argument("--skip-validate", action="store_true", help="panel + coverage only (dev)")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = store_paths(args.stores)
    if not paths:
        print(f"no store found under {args.stores}", file=sys.stderr)
        return 1
    print(f"stores: {len(paths)}", flush=True)
    sessions = session_calendar(paths)
    month_ends = month_end_sessions(sessions, args.start, args.end)
    print(f"calendar: {len(sessions)} sessions {sessions[0].date()}..{sessions[-1].date()}; "
          f"month-ends: {len(month_ends)} {month_ends[0].date()}..{month_ends[-1].date()}", flush=True)

    stores = [load_store(path, sessions) for path in paths]
    rows_read = 0
    missing_known = 0
    for store in stores:
        for frame in ("fin", "shp", "pledge", "guidance", "kpi"):
            block = store[frame]
            if block is None or block.empty:
                continue
            rows_read += len(block)
            missing_known += int(block["known_at"].isna().sum())
    share = missing_known / rows_read if rows_read else 0.0
    print(f"known_at: {missing_known}/{rows_read} rows missing ({share:.2%})", flush=True)
    if share > 0.05:
        print("STOP: more than 5% of panel facts would need a known_at the row does not have", file=sys.stderr)
        return 2

    panel = build_panel(stores, month_ends)
    panel = attach_targets(panel, stores, sessions, month_ends)

    panel_path = out_dir / "panel.parquet"
    if not args.skip_validate:
        truth_path = build_truth_panel(out_dir, rebuild=args.rebuild_truth)
        truth = load_truth(truth_path, panel["date"].unique())
        panel = attach_sector(panel, truth)
        validation = validate(panel, truth, out_dir)
        print(validation.to_string(index=False), flush=True)
    panel.to_parquet(panel_path, index=False)
    factor_cov, month_cov = coverage(panel, out_dir)
    print(f"\npanel: {len(panel)} rows, {panel['store'].nunique()} companies, "
          f"{panel['date'].nunique()} month-ends -> {panel_path}", flush=True)
    print(factor_cov.to_string(index=False), flush=True)
    print(month_cov.to_string(index=False), flush=True)

    months_ok = month_cov[month_cov["with_6m_target"] >= 20]["date"].nunique()
    print(f"month-ends with >=20 realised 6m targets: {months_ok}", flush=True)
    if months_ok < 15:
        print("STOP: fewer than 15 month-ends have >=20 names with a realised 6m target", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
