# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# The pandas stubs type df[col] as Series | Unknown and df[list] as DataFrame | Series | Unknown;
# stages A/B carry the same false positives.  Everything else is checked.
"""T-229 stage C: text and deck factors on the 91 stores, incremental to the hard numbers.

Stage C quantifies the two new text/deck sources onto revenue, cost, debt or capital and tests
whether they predict forward excess returns **over** the stage-B survivors:

* T-228 driver claims (``--claims``): verified rows only, availability through the same
  ``known_at`` -> session rule as stages A/B (a filing after 15:30 IST counts from the next
  session).
* T-230 deck observations (``--obs``): verified company-scope rows only, never ``adjusted=1``,
  never ``series_kind='bridge'``.

Every factor value at a month-end uses only rows usable by that session.  The panel, targets and
IC machinery are the stage-A/B ones; nothing here re-derives a target or changes a stage-A/B
output.  Everything is conditional on "91 companies picked in Nov 2026".

    python -m reality_engine.research.factor_store91_stagec --out .tmp/t229

Outputs under ``--out``: ``stage_c.md``, ``coverage_c.csv``, ``ic_c.csv``, ``placebo_c.csv``,
``power_c.csv``, ``incremental_c.csv`` and ``deck_agreement.csv``.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from reality_engine.research.factor_store91 import (
    avail_sessions,
    session_calendar,
    store_paths,
)
from reality_engine.research.factor_store91_stageb import (
    HORIZON_MONTHS,
    HORIZONS,
    LAGS,
    MIN_MONTHS,
    MIN_NAMES,
    POWER_Z,
    _md,
    _zranks,
    ic_stats,
    monthly_ic,
    placebo_check,
    truth_targets,
)
from reality_engine.research.factor_weights import (
    default_snapshot,
    newey_west_tstat,
    spearman_ic,
)

PANEL_DEFAULT = Path("D:/RealityEngine/t229/panel.parquet")
CLAIMS_DEFAULT = Path("D:/RealityEngine/t228/claims_91.db")
OBS_DEFAULT = Path("D:/RealityEngine/t230/obs_91.db")
OUT_DEFAULT = Path(".tmp/t229")
STORE_ROOT = "D:/RealityEngine/tg_build/measure10"

CLAIM_FACTORS = [
    "claim_order_inflow_12m",
    "claim_capex_12m",
    "claim_dilution_12m",
    "claim_rev_growth",
    "claim_count_12m",
]
DECK_FACTORS = ["deck_order_cover", "deck_capacity_growth"]
STAGE_C_FACTORS = CLAIM_FACTORS + DECK_FACTORS

# the six stage-B survivors whose selection the incremental test controls for
SURVIVORS = ["sales_yield", "earnings_yield", "promoter_chg_4q", "delivery_3m", "q_pat_yoy", "size"]

ANNOUNCEMENT_KINDS = {"announcement", "press_release", "bse_announcement"}
# capacity.add stages a committed addition can carry; blank is the common, unlabelled case,
# while under_review / potential are the speculative pipeline and are excluded.
CAPACITY_STAGES = {"", "operating", "under_construction", "approved"}
CLAIM_CRORE = {
    "inr_cr": 1.0,
    "inr_crore": 1.0,
    "inr_crores": 1.0,
    "inr_lakh": 0.01,
    "inr_lakhs": 0.01,
    "inr_mn": 0.1,
    "inr_million": 0.1,
    "inr_bn": 100.0,
    "inr_billion": 100.0,
}
# Filing / press-release boilerplate that carries no order identity; a shared token outside this
# set is the "same customer / description" signal that collapses a re-announced order.
ORDER_STOPWORDS = set("""
a about above additional after again against agreed agreement all also an and announcement
annexure any are as at attached available basis be been being below between both brief broad
bse by can code company completion conditions consideration contract contracts corporate could
crore crores cr date dear details disclosure do does doing done down during each enclosed entity
exchange excluding find floor for form from further given gst has have hereby id if in including
india indian inform information inr intimation into is issued it its just letter limited listing
ltd m/s madam maharashtra make made may might month months more most must name nature no nor not
obligations of office off on once only or order orders other our out over page per period phase
please plot pursuant received ref regulation regulations requirements rs same scope sebi shall
should significant sir size so some station sub subject such symbol tel terms testing than that
the their them then there these they this those timeframe to too total under until up upon us
value valued very was we website were what when where which while who will with within work
worth would year years your
""".split())
ORDER_REPEAT_DAYS = 30
ORDER_VALUE_TOLERANCE = 0.01
LABEL = "91 companies picked in Nov 2026"


# --------------------------------------------------------------------------- #
# Read-only snapshots of the two evidence databases
# --------------------------------------------------------------------------- #
def snapshot_copy(src: Path, out_dir: Path, name: str) -> Path | None:
    """Byte copy a WAL database under ``--out`` so it opens read-only without side files."""
    if not src.exists():
        print(f"database missing: {src}", flush=True)
        return None
    dst = out_dir / name
    for suffix in ("", "-wal", "-shm"):
        source = Path(str(src) + suffix)
        target = Path(str(dst) + suffix)
        if source.exists():
            shutil.copy2(source, target)
        elif target.exists():
            target.unlink()  # a sidecar from the previous snapshot must not replay
    return dst


def load_claims(path: Path, sessions: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Verified T-228 claims with their PIT availability session and the brief's filters.

    ``speaker_scope='company'`` is applied when the stage-2 column exists (the 91-store stage-1
    database predates it).  ``dup_of`` rows are the stage-2 dedupe's losers and are dropped.
    """
    stats: dict[str, Any] = {"verified": 0, "missing_known_at": 0, "rows": 0,
                             "dropped_scope": 0, "dropped_duplicate": 0}
    con = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        columns = {row[1] for row in con.execute("PRAGMA table_info(claim)")}
        optional = [name for name in ("source_kind", "source_table", "speaker_scope", "dup_of")
                    if name in columns]
        select = ", ".join(["id", "symbol", "known_at", "node", "sign", "value_low", "value_high",
                            "unit", "segment", "effective_period", "statement", "quote_span",
                            "context", *optional])
        raw = pd.read_sql_query(f"SELECT {select} FROM claim WHERE status = 'verified'", con)
        frame = cast(pd.DataFrame, raw)
        stats["verified"] = len(frame)
        stats["missing_known_at"] = int(pd.read_sql_query(
            "SELECT COUNT(*) AS n FROM claim WHERE status = 'verified' "
            "AND (known_at IS NULL OR known_at = '')", con)["n"].iloc[0])
    finally:
        con.close()
    if frame.empty:
        return frame, stats

    frame = frame.rename(columns={"id": "row_id"})
    if "speaker_scope" in frame.columns:
        scope = frame["speaker_scope"].fillna("").astype(str)
        stats["dropped_scope"] = int((scope != "company").sum())
        frame = frame[scope == "company"]
    if "dup_of" in frame.columns:
        duplicate = frame["dup_of"].fillna("").astype(str) != ""
        stats["dropped_duplicate"] = int(duplicate.sum())
        frame = frame[~duplicate]
    frame["avail"] = avail_sessions(frame["known_at"], sessions)
    frame = frame[frame["avail"].notna()]
    order = np.lexsort((frame["known_at"].to_numpy(), frame["avail"].to_numpy(),
                        frame["symbol"].to_numpy()))
    frame = cast(pd.DataFrame, frame.iloc[order])
    stats["rows"] = len(frame)
    return frame.reset_index(drop=True), stats


def load_observations(path: Path, sessions: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Verified, company-scope deck observations; never adjusted, never a bridge row."""
    stats: dict[str, Any] = {"rows": 0, "missing_known_at": 0}
    con = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        raw = pd.read_sql_query(
            """SELECT observation_id, symbol, known_at, measure, value, unit, unit_family, scale,
                      period, period_kind, segment, stage, series_kind, adjusted, entity_scope
               FROM observation
               WHERE status = 'verified'
                 AND measure IN ('order.book', 'capacity.add', 'capacity.total')
                 AND entity_scope = 'company'
                 AND adjusted = 0
                 AND (series_kind IS NULL OR series_kind != 'bridge')""",
            con,
        )
        frame = cast(pd.DataFrame, raw)
        stats["missing_known_at"] = int(pd.read_sql_query(
            "SELECT COUNT(*) AS n FROM observation WHERE status = 'verified' "
            "AND (known_at IS NULL OR known_at = '')", con)["n"].iloc[0])
    finally:
        con.close()
    if frame.empty:
        return frame, stats
    frame["avail"] = avail_sessions(frame["known_at"], sessions)
    frame = frame[frame["avail"].notna()]
    order = np.lexsort((frame["known_at"].to_numpy(), frame["avail"].to_numpy(),
                        frame["symbol"].to_numpy()))
    frame = cast(pd.DataFrame, frame.iloc[order])
    stats["rows"] = len(frame)
    return frame.reset_index(drop=True), stats


# --------------------------------------------------------------------------- #
# Claims -> factors
# --------------------------------------------------------------------------- #
def _announcement_mask(frame: pd.DataFrame) -> pd.Series:
    """Order wins are announcement-sourced; transcript/guidance order books are stocks/targets."""
    source_kind = (frame["source_kind"].fillna("").astype(str) if "source_kind" in frame.columns
                   else pd.Series("", index=frame.index))
    source_table = (frame["source_table"].fillna("").astype(str) if "source_table" in frame.columns
                    else pd.Series("", index=frame.index))
    return (source_kind.isin(list(ANNOUNCEMENT_KINDS))
            | source_table.isin(list(ANNOUNCEMENT_KINDS)))


def _claim_crore(values: pd.Series, units: pd.Series) -> pd.Series:
    """Only inr_cr / lakh / mn / bn are converted; any other printed unit is skipped."""
    numeric = pd.to_numeric(pd.Series(np.asarray(values, dtype=float)), errors="coerce").to_numpy(
        dtype=float)
    unit = pd.Series(np.asarray(units, dtype=object)).astype("string").str.strip().str.lower()
    multiplier = unit.map(CLAIM_CRORE).to_numpy(dtype=float)
    return pd.Series(numeric * multiplier)


def _midpoint(low: pd.Series, high: pd.Series) -> pd.Series:
    values = np.column_stack([
        pd.to_numeric(pd.Series(low), errors="coerce").to_numpy(dtype=float),
        pd.to_numeric(pd.Series(high), errors="coerce").to_numpy(dtype=float),
    ])
    known = ~np.isnan(values)
    count = known.sum(axis=1)
    total = np.where(known, values, 0.0).sum(axis=1)
    return pd.Series(np.where(count > 0, total / np.maximum(count, 1), np.nan))


def _sum_crore(rows: pd.DataFrame, skipped: set[int]) -> tuple[float, int]:
    """Trailing-window sum of a claim set in crore; unsupported-unit rows are counted, not used."""
    if rows.empty:
        return float("nan"), 0
    rows = rows.drop_duplicates(["row_id"])
    mid = _midpoint(pd.Series(np.asarray(rows["value_low"], dtype=object)),
                    pd.Series(np.asarray(rows["value_high"], dtype=object)))
    crore = _claim_crore(mid, pd.Series(np.asarray(rows["unit"], dtype=object)))
    bad = np.asarray(crore.isna(), dtype=bool)
    skipped.update(int(value) for value in np.asarray(rows["row_id"])[bad])
    if not (~bad).any():
        return float("nan"), int(bad.sum())
    return float(np.nansum(crore.to_numpy(dtype=float)[~bad])), int(bad.sum())


def _period_key(value: Any) -> str:
    """Normalise a printed execution period so FY26 / FY '26 / fy26 are one key."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _latest_per_key(rows: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Latest verified claim per key (a restated plan replaces its earlier value)."""
    return rows.sort_values(["avail", "known_at"]).drop_duplicates(keys, keep="last")


def _description_tokens(*texts: Any) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        tokens.update(re.findall(r"[a-z][a-z0-9]+", str(text or "").lower()))
    return {token for token in tokens if token not in ORDER_STOPWORDS}


def _order_inflow(rows: pd.DataFrame, skipped: set[int]) -> float:
    """Sum distinct order wins; the same order announced twice counts once.

    Two rows are the same announcement when their availability sessions are within 30 days, their
    values are within 1% and the customer/description texts share at least two non-boilerplate
    tokens.  A shared filing boilerplate therefore cannot collapse two different orders.
    """
    if rows.empty:
        return float("nan")
    rows = rows.drop_duplicates(["row_id"]).sort_values(
        ["avail", "known_at"]).reset_index(drop=True)
    mid = _midpoint(pd.Series(np.asarray(rows["value_low"], dtype=object)),
                    pd.Series(np.asarray(rows["value_high"], dtype=object)))
    crore = _claim_crore(mid, pd.Series(np.asarray(rows["unit"], dtype=object))).to_numpy(
        dtype=float)
    bad = np.isnan(crore)
    skipped.update(int(value) for value in np.asarray(rows["row_id"])[bad])
    kept: list[tuple[pd.Timestamp, float, set[str]]] = []
    total = 0.0
    for position in np.flatnonzero(~bad):
        claim = rows.iloc[int(position)]
        value = float(crore[position])
        tokens = _description_tokens(claim.get("statement"), claim.get("quote_span"),
                                     claim.get("context"))
        repeated = any(
            abs((claim["avail"] - day).days) <= ORDER_REPEAT_DAYS
            and abs(value - earlier) <= ORDER_VALUE_TOLERANCE * max(abs(value), abs(earlier))
            and len(tokens & earlier_tokens) >= 2
            for day, earlier, earlier_tokens in kept
        )
        if not repeated:
            kept.append((claim["avail"], value, tokens))
            total += value
    return total if kept else float("nan")


def claim_factors(panel: pd.DataFrame, claims: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """One row per (store, month-end) with the five claim factors, point in time."""
    empty = pd.DataFrame(columns=["store", "date", *CLAIM_FACTORS])
    stats: dict[str, Any] = {"unsupported_unit_rows": 0, "unknown_symbol_claims": 0,
                             "stores": 0, "capacity_unit_skips": 0}
    if claims.empty:
        return empty, stats
    skipped: set[int] = set()
    store_of = dict(zip(panel.drop_duplicates("store")["symbol"],
                        panel.drop_duplicates("store")["store"]))
    snapshot = {}
    for record in panel[["store", "date", "ttm_rev", "mcap", "ttm_rev_yoy"]].itertuples(
            index=False, name=None):
        snapshot[(record[0], pd.Timestamp(record[1]))] = (record[2], record[3], record[4])
    dates_of = {store: sorted(pd.Timestamp(day) for day in group["date"].unique())
                for store, group in panel.groupby("store", sort=False)}
    rows: list[dict[str, Any]] = []
    for symbol, group in claims.groupby("symbol", sort=False):
        store = store_of.get(symbol)
        if store is None:
            stats["unknown_symbol_claims"] += int(len(group))
            continue
        stats["stores"] += 1
        group = pd.DataFrame(group)
        group = group.sort_values(["avail", "known_at"])
        for day in dates_of.get(store, []):
            seen = group[group["avail"] <= day]
            if seen.empty:
                continue
            window = seen[seen["avail"] > day - pd.Timedelta(days=365)]
            ttm_rev, mcap, ttm_growth = snapshot.get((store, day), (np.nan, np.nan, np.nan))
            row: dict[str, Any] = {"store": store, "date": day,
                                   **{factor: np.nan for factor in CLAIM_FACTORS}}

            wins = window[(window["node"] == "revenue.order_book") & _announcement_mask(window)]
            if not wins.empty:
                inflow = _order_inflow(wins, skipped)
                if pd.notna(inflow) and pd.notna(ttm_rev) and ttm_rev > 0:
                    row["claim_order_inflow_12m"] = inflow * 1e7 / ttm_rev

            capex = window[window["node"] == "capex.amount"].copy()
            if not capex.empty:
                capex["_segment_key"] = (capex["segment"].fillna("").astype(str).str.strip()
                                         .str.lower())
                capex["_period_key"] = capex["effective_period"].map(_period_key)
                latest = _latest_per_key(capex, ["_segment_key", "_period_key"])
                amount, _ = _sum_crore(latest, skipped)
                if pd.notna(mcap) and mcap > 0:
                    row["claim_capex_12m"] = amount * 1e7 / mcap

            dilution = window[(window["node"] == "equity.shares")
                              & window["unit"].astype("string").str.lower().isin(
                                  [name for name in CLAIM_CRORE])]
            if not dilution.empty:
                raised, _ = _sum_crore(dilution, skipped)
                if pd.notna(mcap) and mcap > 0:
                    row["claim_dilution_12m"] = raised * 1e7 / mcap

            pct = seen[(seen["node"] == "revenue.total")
                       & (seen["unit"].astype("string") == "pct")]
            if not pct.empty and pd.notna(ttm_growth):
                last = pct.iloc[-1]
                mid = _midpoint(pd.Series([last["value_low"]]), pd.Series([last["value_high"]]))
                if mid.notna().iloc[0]:
                    row["claim_rev_growth"] = float(mid.iloc[0]) / 100.0 - float(ttm_growth)

            row["claim_count_12m"] = float(len(window))
            rows.append(row)
    stats["unsupported_unit_rows"] = len(skipped)
    return pd.DataFrame(rows) if rows else empty, stats


# --------------------------------------------------------------------------- #
# Deck observations -> factors
# --------------------------------------------------------------------------- #
def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def deck_factors(panel: pd.DataFrame, obs: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Latest verified deck order book / TTM revenue, and capacity add / total growth."""
    empty = pd.DataFrame(columns=["store", "date", *DECK_FACTORS])
    stats: dict[str, Any] = {"stores": 0, "order_book_symbols": 0,
                             "capacity_no_total": 0, "capacity_stage_skipped": 0}
    if obs.empty:
        return empty, stats
    store_of = dict(zip(panel.drop_duplicates("store")["symbol"],
                        panel.drop_duplicates("store")["store"]))
    snapshot = {}
    for record in panel[["store", "date", "ttm_rev"]].itertuples(index=False, name=None):
        snapshot[(record[0], pd.Timestamp(record[1]))] = record[2]
    dates_of = {store: sorted(pd.Timestamp(day) for day in group["date"].unique())
                for store, group in panel.groupby("store", sort=False)}
    frame = obs.copy()
    frame["unit_key"] = [_norm(value) for value in frame["unit"]]
    frame["segment_key"] = [_norm(value) for value in frame["segment"]]
    frame["stage_key"] = [_norm(value) for value in frame["stage"]]
    frame["empty_segment"] = frame["segment_key"] == ""
    books = frame[frame["measure"] == "order.book"]
    order = np.lexsort((books["value"].to_numpy(dtype=float),
                        books["empty_segment"].to_numpy(dtype=bool),
                        books["avail"].to_numpy()))
    books = cast(pd.DataFrame, books.iloc[order])
    adds = frame[(frame["measure"] == "capacity.add")
                 & frame["stage_key"].isin(list(CAPACITY_STAGES))]
    order = np.lexsort((adds["value"].to_numpy(dtype=float), adds["avail"].to_numpy()))
    adds = cast(pd.DataFrame, adds.iloc[order])
    totals = frame[frame["measure"] == "capacity.total"]
    rows: list[dict[str, Any]] = []
    missing_total: set[str] = set()
    stage_skips: set[str] = set()
    for symbol, group in frame.groupby("symbol", sort=False):
        store = store_of.get(symbol)
        if store is None:
            continue
        stats["stores"] += 1
        group = pd.DataFrame(group)
        symbol_books = books[books["symbol"] == symbol]
        symbol_adds = adds[adds["symbol"] == symbol]
        symbol_totals = totals[totals["symbol"] == symbol]
        symbol_stage_skips = frame[(frame["symbol"] == symbol)
                                   & (frame["measure"] == "capacity.add")
                                   & ~frame["stage_key"].isin(list(CAPACITY_STAGES))]
        if not symbol_stage_skips.empty:
            stage_skips.add(symbol)
        if not symbol_books.empty:
            stats["order_book_symbols"] += 1
        for day in dates_of.get(store, []):
            ttm_rev = snapshot.get((store, day), np.nan)
            row: dict[str, Any] = {"store": store, "date": day,
                                   **{factor: np.nan for factor in DECK_FACTORS}}
            seen_books = symbol_books[symbol_books["avail"] <= day]
            if not seen_books.empty and pd.notna(ttm_rev) and ttm_rev > 0:
                last = seen_books.iloc[-1]
                scaled = float(last["value"]) * float(last["scale"])
                row["deck_order_cover"] = scaled / float(ttm_rev)

            seen_adds = symbol_adds[symbol_adds["avail"] <= day]
            if not seen_adds.empty:
                add = seen_adds.iloc[-1]
                candidates = symbol_totals[(symbol_totals["avail"] <= day)
                                           & (symbol_totals["unit_key"] == add["unit_key"])
                                           & (symbol_totals["segment_key"] == add["segment_key"])]
                if candidates.empty:
                    missing_total.add(symbol)  # units/segment differ: never divide them
                else:
                    total = cast(pd.DataFrame, candidates).sort_values("avail", kind="stable").iloc[-1]
                    denominator = float(total["value"]) * float(total["scale"])
                    if denominator > 0:
                        row["deck_capacity_growth"] = (float(add["value"]) * float(add["scale"])
                                                       / denominator)
            rows.append(row)
    stats["capacity_no_total"] = len(missing_total)
    stats["capacity_stage_skipped"] = len(stage_skips)
    return (pd.DataFrame(rows) if rows else empty), stats


# --------------------------------------------------------------------------- #
# Targets, coverage, ICs
# --------------------------------------------------------------------------- #
def attach_targets(panel: pd.DataFrame, dates: list[Any]) -> pd.DataFrame:
    """Truth-snapshot NIFTY-500 excess returns, exactly stage B's arithmetic."""
    targets = truth_targets(default_snapshot(), dates)
    wide = targets.pivot_table(index=["date", "isin"], columns="horizon",
                               values="excess").reset_index()
    wide.columns = ["date", "truth_isin", *[f"texcess_{h}" for h in wide.columns[2:]]]
    frame = panel.copy()
    frame["truth_isin"] = (frame["link_isin"].fillna(frame["isin"])
                           if "link_isin" in frame.columns else frame["isin"])
    return frame.merge(wide, on=["date", "truth_isin"], how="left")


def coverage_table(frame: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    """Companies, months with a value, and month-ends with >= 20 names after the window closes."""
    rows: list[dict[str, Any]] = []
    for factor in factors:
        raw_series: Any = frame.groupby("date")[factor].apply(
            lambda s: int(s.notna().sum()))
        per_month = pd.Series(raw_series)
        entry: dict[str, Any] = {
            "factor": factor,
            "companies_with_value": int(frame.loc[frame[factor].notna(), "store"].nunique()),
            "months_with_value": int((per_month > 0).sum()),
            "months_ge20": int((per_month >= MIN_NAMES).sum()),
            "median_names": float(per_month[per_month > 0].median()) if (per_month > 0).any() else 0.0,
            "max_names": int(per_month.max()) if len(per_month) else 0,
        }
        for horizon in HORIZONS:
            pair = frame[["date", factor, f"texcess_{horizon}"]].replace(
                [np.inf, -np.inf], np.nan).dropna()
            entry[f"months_ge20_{horizon}"] = int(
                pair.groupby("date").size().ge(MIN_NAMES).sum())
        entry["gate"] = any(entry[f"months_ge20_{h}"] >= MIN_MONTHS for h in HORIZONS)
        rows.append(entry)
    return pd.DataFrame(rows)


def ic_table(frame: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for factor in factors:
        for horizon in HORIZONS:
            target = f"texcess_{horizon}"
            pair = frame[["date", factor, target]].replace([np.inf, -np.inf], np.nan).dropna()
            series = monthly_ic(pair, factor, target)
            stats = ic_stats(series, horizon)
            mean_names = float(pair.groupby("date").size().mean()) if len(pair) else np.nan
            rows.append({"factor": factor, "horizon": horizon, **stats,
                         "mean_names": mean_names})
    return pd.DataFrame(rows)


def power_table(frame: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    """Smallest mean IC detectable at 80% power for 6m and 12m, given the overlap."""
    rows: list[dict[str, Any]] = []
    for factor in factors:
        for horizon in ("6m", "12m"):
            series = monthly_ic(frame, factor, f"texcess_{horizon}")
            months = int(series.notna().sum())
            if months == 0:
                continue
            sd = float(series.std(ddof=1)) if months > 1 else np.nan
            effective = months / HORIZON_MONTHS[horizon]
            rows.append({
                "factor": factor, "horizon": horizon, "months": months,
                "effective_windows": effective, "sd_monthly_ic": sd,
                "min_detectable_mean_ic": POWER_Z * sd / np.sqrt(effective)
                if pd.notna(sd) and effective > 0 else np.nan,
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Incremental test: residualise each text/deck factor on the stage-B survivors
# --------------------------------------------------------------------------- #
def rank_residual(frame: pd.DataFrame, factor: str, controls: list[str]) -> pd.Series:
    """Per-date OLS residual of ``factor`` on the controls, all rank-standardised.

    Rank-standardising before the regression keeps a fat-tailed ratio (a claim sum over a small
    market cap) from setting the slope, and matches the Spearman IC the residual is scored with.
    """
    out = pd.Series(np.nan, index=frame.index, dtype=float)
    for _, group in frame.groupby("date", sort=False):
        group = pd.DataFrame(group)
        subset = group[[factor, *controls]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(subset) < len(controls) + 3:
            continue
        target = _zranks(subset[factor].to_numpy(dtype=float))
        design = np.column_stack([np.ones(len(subset)),
                                  *[_zranks(subset[control].to_numpy(dtype=float))
                                    for control in controls]])
        beta, *_ = np.linalg.lstsq(design, target, rcond=None)
        out.loc[subset.index] = target - design @ beta
    return out


def incremental_table(frame: pd.DataFrame, passes: list[str],
                      permutations: int = 200, seed: int = 229) -> pd.DataFrame:
    """Raw IC, residual IC, NW t and placebo p of each factor over the six survivors."""
    rows: list[dict[str, Any]] = []
    for factor in passes:
        residual = rank_residual(frame, factor, SURVIVORS)
        work: pd.DataFrame = frame.assign(_resid=residual)
        scored = pd.DataFrame(work[["date", "_resid", *[f"texcess_{h}" for h in HORIZONS]]])
        placebo = placebo_check(scored, ["_resid"], n_perm=permutations, seed=seed)
        placebo = placebo.set_index("horizon")
        for horizon in HORIZONS:
            target = f"texcess_{horizon}"
            pair = pd.DataFrame(work[["date", factor, "_resid", target]].replace(
                [np.inf, -np.inf], np.nan).dropna())
            raw = ic_stats(monthly_ic(pair, factor, target), horizon)
            resid = ic_stats(monthly_ic(pair, "_resid", target), horizon)
            p_value = np.nan
            if horizon in placebo.index:
                p_values = pd.to_numeric(placebo["p_value"], errors="coerce")
                p_value = float(p_values.loc[horizon])
            rows.append({
                "factor": factor, "horizon": horizon, "months": resid["months"],
                "raw_mean_ic": raw["mean_ic"], "residual_mean_ic": resid["mean_ic"],
                "residual_nw_t": resid["nw_t"], "placebo_p": p_value,
                "survivors": "+".join(SURVIVORS),
            })
    return pd.DataFrame(rows)


def deck_agreement(frame: pd.DataFrame) -> pd.DataFrame:
    """Deck order book cover against the store KPI order_cover where both exist."""
    pair = frame[["date", "store", "deck_order_cover", "order_cover"]].replace(
        [np.inf, -np.inf], np.nan).dropna()
    if pair.empty:
        return pd.DataFrame(columns=["pairs", "companies", "rho_pooled", "rho_monthly_median",
                                     "within_10pct"])
    expected = pair["order_cover"].abs()
    within = (pair["deck_order_cover"] - pair["order_cover"]).abs() / expected.where(expected > 0)
    monthly = pd.Series(pair.groupby("date").apply(
        lambda g: spearman_ic(g["deck_order_cover"], g["order_cover"], min_n=3)
    )).dropna()
    return pd.DataFrame([{
        "pairs": len(pair), "companies": int(pair["store"].nunique()),
        "rho_pooled": spearman_ic(pair["deck_order_cover"], pair["order_cover"], min_n=3),
        "rho_monthly_median": float(monthly.median()) if len(monthly) else np.nan,
        "within_10pct": float((within <= 0.10).mean()),
    }])


# --------------------------------------------------------------------------- #
# Output and runner
# --------------------------------------------------------------------------- #
def _table(tables: dict[str, pd.DataFrame], key: str) -> pd.DataFrame:
    frame = tables.get(key)
    return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def write_stage_c_md(out_dir: Path, tables: dict[str, pd.DataFrame],
                     headline: dict[str, Any]) -> None:
    parts = [f"# T-229 stage C full tables — {LABEL}\n",
             "Generated by `python -m reality_engine.research.factor_store91_stagec`.\n"]
    parts.append("## Coverage and the gate\n")
    parts.append(_md(_table(tables, "coverage"), floatfmt=".4f"))
    parts.append("\n## ICs\n")
    parts.append(_md(_table(tables, "ic"), floatfmt=".4f"))
    parts.append("\n## Placebo (200 within-date permutations, BH 10%)\n")
    parts.append(_md(_table(tables, "placebo"), floatfmt=".4f"))
    parts.append("\n## Power\n")
    parts.append(_md(_table(tables, "power"), floatfmt=".4f"))
    parts.append("\n## Incremental over the stage-B survivors\n")
    parts.append(_md(_table(tables, "incremental"), floatfmt=".4f"))
    parts.append("\n## Deck order cover vs KPI order_cover\n")
    parts.append(_md(_table(tables, "agreement"), floatfmt=".4f"))
    parts.append("\n## Headline numbers\n")
    for key, value in headline.items():
        parts.append(f"- {key}: {value}")
    (out_dir / "stage_c.md").write_text("\n".join(parts), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-229 stage C: text and deck factors")
    parser.add_argument("--panel", default=str(PANEL_DEFAULT), help="stage-A panel.parquet")
    parser.add_argument("--claims", default=str(CLAIMS_DEFAULT), help="T-228 claims database")
    parser.add_argument("--obs", default=str(OBS_DEFAULT), help="T-230 deck observations database")
    parser.add_argument("--stores", default=STORE_ROOT)
    parser.add_argument("--out", default=str(OUT_DEFAULT))
    parser.add_argument("--permutations", type=int, default=200)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(args.panel)
    panel["date"] = pd.to_datetime(panel["date"])
    dates = [pd.Timestamp(day) for day in sorted(panel["date"].unique())]
    print(f"{LABEL}; panel {len(panel)} rows, {panel['store'].nunique()} companies, "
          f"{len(dates)} month-ends", flush=True)

    sessions = session_calendar(store_paths(args.stores))
    frame = attach_targets(panel, dates)

    claim_stats: dict[str, Any] = {"verified": 0}
    claim_path = snapshot_copy(Path(args.claims), out, "claims_snapshot.db")
    if claim_path is not None:
        claims, claim_stats = load_claims(claim_path, sessions)
        if claim_stats["verified"] and claim_stats["missing_known_at"] > 0.05 * claim_stats["verified"]:
            print(f"STOP: {claim_stats['missing_known_at']} of {claim_stats['verified']} verified "
                  "claims have no known_at (>5%)", flush=True)
            return 2
        claim_df, _ = claim_factors(panel, claims)
        if not claim_df.empty:
            frame = frame.merge(claim_df, on=["store", "date"], how="left")
        print(f"claims: {claim_stats['rows']} usable verified rows, "
              f"{claim_stats['dropped_scope']} scope drops, "
              f"{claim_stats['dropped_duplicate']} duplicate drops", flush=True)

    obs_stats: dict[str, Any] = {"rows": 0}
    obs_path = snapshot_copy(Path(args.obs), out, "obs_snapshot.db")
    if obs_path is not None:
        obs, obs_stats = load_observations(obs_path, sessions)
        if obs_stats["rows"] and obs_stats["missing_known_at"] > 0.05 * obs_stats["rows"]:
            print(f"STOP: {obs_stats['missing_known_at']} of {obs_stats['rows']} verified "
                  "observations have no known_at (>5%)", flush=True)
            return 2
        deck_df, deck_stats = deck_factors(panel, obs)
        if not deck_df.empty:
            frame = frame.merge(deck_df, on=["store", "date"], how="left")
        print(f"deck observations: {obs_stats['rows']} usable rows, "
              f"{deck_stats['order_book_symbols']} companies with an order book, "
              f"{deck_stats['capacity_no_total']} companies with a capacity add and no "
              "same-unit total", flush=True)
    for factor in STAGE_C_FACTORS:
        if factor not in frame.columns:
            frame[factor] = np.nan

    coverage = coverage_table(frame, STAGE_C_FACTORS)
    coverage.to_csv(out / "coverage_c.csv", index=False)
    # the deck order-book definition is checked against the store's own KPI cover before any gate
    agreement = deck_agreement(frame)
    agreement.to_csv(out / "deck_agreement.csv", index=False)
    print(agreement.to_string(index=False), flush=True)
    print(coverage.to_string(index=False), flush=True)
    passes = coverage.loc[coverage["gate"], "factor"].tolist()
    if len(passes) < 2:
        for stale in ("ic_c.csv", "placebo_c.csv", "power_c.csv", "incremental_c.csv"):
            path = out / stale
            if path.exists():
                path.unlink()  # a previous run's ICs must not sit beside a stop report
        headline = {"universe": LABEL, "factors passing the gate": len(passes),
                    "reason": "fewer than 2 factors reach 12 month-ends with 20 names"}
        write_stage_c_md(out, {"coverage": coverage, "agreement": agreement}, headline)
        print("STOP: fewer than 2 factors pass the coverage gate; coverage reported", flush=True)
        return 2

    ic = ic_table(frame, STAGE_C_FACTORS)
    ic.to_csv(out / "ic_c.csv", index=False)
    tested = ic[ic["months"] >= MIN_MONTHS]
    print(tested.to_string(index=False), flush=True)

    placebo = placebo_check(frame, STAGE_C_FACTORS, n_perm=args.permutations)
    placebo.to_csv(out / "placebo_c.csv", index=False)
    power = power_table(frame, passes)
    power.to_csv(out / "power_c.csv", index=False)
    incremental = incremental_table(frame, passes, permutations=args.permutations)
    incremental.to_csv(out / "incremental_c.csv", index=False)

    headline = {
        "universe": LABEL,
        "panel rows": len(frame),
        "claims verified / usable": f"{claim_stats.get('verified', 0)} / {claim_stats.get('rows', 0)}",
        "claim rows skipped for unit": claim_stats.get("unsupported_unit_rows", 0),
        "deck observations usable": obs_stats.get("rows", 0),
        "factors passing the gate": ", ".join(passes),
        "claim factors with no order-win source": (
            "yes" if frame["claim_order_inflow_12m"].notna().sum() == 0 else "no"),
        "placebo cells BH 10%": int(placebo["bh_reject_10"].sum()),
        "incremental cells with residual NW |t| >= 2": int(
            (incremental["residual_nw_t"].abs() >= 2).sum()),
    }
    write_stage_c_md(out, {"coverage": coverage, "ic": ic, "placebo": placebo, "power": power,
                           "incremental": incremental, "agreement": agreement}, headline)
    print(f"\nwrote {out/'stage_c.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
