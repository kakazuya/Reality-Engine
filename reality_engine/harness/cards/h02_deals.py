"""H02 Card F: bulk/block deal accumulation, point-in-time from the snapshot.

The card fixes the signal: deals -> ISIN, net buy >= Rs 1 crore per
(issuer, date) for a declared client set, promoter/insider clients removed,
entry at t+1 open because the deal feed is end-of-day.  This module owns the
declared client definitions and the normalization/dedupe logic; it never
reads prices or outcomes.  The evaluator lives in run_h02.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Declared before any outcome was seen (see H02_preregistration.md).
M1_PATTERN = (
    r"(?:MUTUAL FUND|\bMF\b|ASSET MANAGEMENT|\bAMC\b|INSURANCE|LIFE INSURANCE|"
    r"PENSION|PROVIDENT|FUND|FUNDS|CAPITAL MANAGEMENT|INVESTMENT MANAGEMENT|"
    r"SOVEREIGN|GOVERNMENT OF|MONETARY AUTHORITY|NORGES|ABU DHABI|\bGIC\b|TRUST)"
)
M1_EXCLUDE = r"(?:SHARE BROKING|SECURITIES PRIVATE|STOCK BROKING|COMMODITIES)"
BROKER_PROP = M1_EXCLUDE

EVENT_THRESHOLD_INR = 10_000_000.0  # Rs 1 crore
EVIDENCE_START = "2021-01-01"
EVIDENCE_END = "2025-12-31"
WARMUP_START = "2019-01-01"
HORIZONS = (20, 60)
CONFIRM_WINDOW = (-20, 5)


def normalize_client(value):
    """Uppercase, ASCII alphanumerics, single spaces. Entity resolution only."""
    text = str(value or "").upper()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def marquee_mask(names):
    """Declared M1 regex, applied to normalized client names."""
    text = pd.Series(names, dtype="string").fillna("")
    hit = text.str.contains(M1_PATTERN, regex=True, case=False, na=False)
    excluded = text.str.contains(M1_EXCLUDE, regex=True, case=False, na=False)
    return hit & ~excluded


def broker_prop_mask(names):
    text = pd.Series(names, dtype="string").fillna("")
    return text.str.contains(BROKER_PROP, regex=True, case=False, na=False)


def pit_indices(days, dates):
    """Signal session = last session on/before the date; entry = next session.

    Deal feeds are date-only end-of-day.  Signal may be the deal-date session
    itself; entry is always strictly after the deal date, never its close.
    """
    days = np.asarray(days, dtype="datetime64[D]")
    dates = np.asarray(dates, dtype="datetime64[D]")
    signal = np.searchsorted(days, dates, side="right") - 1
    entry = np.searchsorted(days, dates, side="right")
    return signal, entry


def shuffle_dates_within_stock_year(dates, issuers, rng):
    """Permute deal dates among events of the same issuer-year only."""
    dates = np.asarray(dates, dtype="datetime64[D]").copy()
    issuers = np.asarray(issuers).astype(str)
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    groups = {}
    for i, (issuer, year) in enumerate(zip(issuers, years)):
        groups.setdefault((issuer, int(year)), []).append(i)
    for ids in groups.values():
        if len(ids) > 1:
            idx = np.asarray(ids, dtype=int)
            dates[idx] = rng.permutation(dates[idx])
    return dates


def _dedupe_frame(frame):
    """One-to-one cross-exchange and BULK/BLOCK duplicate removal.

    The same trade can be reported by NSE and BSE and again in the bulk and
    block feeds.  Rows are paired one-for-one inside each
    (date, client, side, qty, price, issuer) key so genuine repeat trades with
    identical size/price are not all collapsed.  Same-exchange, same-type
    repeats are retained and flagged, never silently treated as one trade.
    """
    key = ["date", "client_n", "side", "qty", "px", "issuer"]
    frame = frame.copy()
    frame["_order"] = np.arange(len(frame))
    frame = frame.sort_values(key + ["exch", "deal_type", "_order"], kind="mergesort")
    frame["_xrank"] = frame.groupby(key + ["exch"], sort=False).cumcount()
    frame["_is_nse"] = (frame["exch"] == "NSE").astype(np.int32)
    frame["_nse_count"] = frame.groupby(key, sort=False)["_is_nse"].transform("sum")
    cross = (frame["exch"] == "BSE") & (frame["_xrank"] < frame["_nse_count"])
    cross_n = int(cross.sum())
    left = frame.loc[~cross].copy()
    key2 = key + ["exch"]
    left["_is_bulk"] = (left["deal_type"] == "BULK").astype(np.int32)
    left["_bulk_count"] = left.groupby(key2, sort=False)["_is_bulk"].transform("sum")
    left["_drank"] = left.groupby(key2 + ["deal_type"], sort=False).cumcount()
    bulkblock = (left["deal_type"] == "BLOCK") & (left["_drank"] < left["_bulk_count"])
    bulkblock_n = int(bulkblock.sum())
    out = left.loc[~bulkblock].drop(
        columns=["_order", "_xrank", "_is_nse", "_nse_count", "_is_bulk",
                 "_bulk_count", "_drank"])
    out = out.sort_values(["date", "issuer", "client_n", "side", "qty", "px"],
                          kind="mergesort").reset_index(drop=True)
    return out, {"cross_exchange_duplicates_removed": cross_n,
                 "bulk_block_duplicates_removed": bulkblock_n,
                 "rows_before_dedupe": int(len(frame)),
                 "rows_after_dedupe": int(len(out))}


def _load_raw_deals(path):
    """Load both exchange feeds and map to issuer through the snapshot only."""
    import duckdb

    con = duckdb.connect(":memory:")
    try:
        con.execute(f"ATTACH '{str(path).replace(chr(92), '/')}' AS snap (READ_ONLY)")
        con.execute("SET threads=4")
        # Issuer is the only unambiguous BSE code mapping in the snapshot.
        # Multiple ISINs for one code are historical ISIN changes; entity is
        # the same.  A code mapping to more than one issuer is refused.
        con.execute("""
            CREATE TEMP TABLE bse_map AS
            SELECT bse_code, min(isin) AS isin, min(issuer) AS issuer
            FROM snap.security_master
            WHERE bse_code IS NOT NULL
            GROUP BY bse_code
            HAVING count(DISTINCT issuer) = 1
        """)
        norm = ("upper(trim(regexp_replace(regexp_replace(coalesce(%s,''), "
                "'[^A-Za-z0-9 ]', ' ', 'g'), '\\s+', ' ', 'g')))")
        frame = con.execute(f"""
            WITH nse_candidates AS (
              SELECT d.rowid AS source_rowid, d.date, d.deal_type, d.symbol,
                     d.client_name, d.buy_sell, d.quantity::DOUBLE AS qty,
                     d.price::DOUBLE AS px, h.isin, sm.issuer, 'NSE' AS exch
              FROM snap.nse_deals d
              LEFT JOIN snap.symbol_isin_history h
                ON h.exchange='NSE' AND h.symbol=d.symbol
               AND d.date BETWEEN h.first_date AND h.last_date
              LEFT JOIN snap.security_master sm ON sm.isin=h.isin
              WHERE d.date BETWEEN '{WARMUP_START}' AND '{EVIDENCE_END}'
            ), nse_one AS (
              SELECT * FROM nse_candidates
              QUALIFY row_number() OVER (PARTITION BY source_rowid ORDER BY isin) = 1
            ), bse_one AS (
              SELECT d.rowid AS source_rowid, d.date, d.deal_type, d.sc_code AS symbol,
                     d.client_name, d.buy_sell, d.quantity::DOUBLE AS qty,
                     d.price::DOUBLE AS px, m.isin, m.issuer, 'BSE' AS exch
              FROM snap.bse_deals d
              LEFT JOIN bse_map m ON m.bse_code=d.sc_code
              WHERE d.date BETWEEN '{WARMUP_START}' AND '{EVIDENCE_END}'
            )
            SELECT * FROM nse_one UNION ALL SELECT * FROM bse_one
        """).df()
        frame["date"] = frame["date"].astype(str).str[:10]
        frame["client_n"] = frame["client_name"].map(normalize_client)
        frame["side"] = frame["buy_sell"].astype(str).str.strip().str.upper()
        frame["qty"] = frame["qty"].astype(float).round(4)
        frame["px"] = frame["px"].astype(float).round(4)
        frame["value"] = frame["qty"] * frame["px"]
        frame["row_id"] = frame["exch"] + ":" + frame["source_rowid"].astype(str)
        # The SQL above already emits one row per source row.  A date-valid
        # NSE symbol mapping is unique in this snapshot (checked: zero
        # ambiguous deal rows, 2019-2025); an ambiguity would have surfaced
        # as a duplicate row_id here.
        if frame["row_id"].duplicated().any():
            raise ValueError("Deal mapping produced duplicate source rows")
        frame["mapping_ambiguous"] = False
        return frame
    finally:
        con.close()


def load_insider_pairs(path):
    """Company-specific promoter/insider name pairs from snapshot PIT tables.

    NSE PIT names are mapped through the symbol->ISIN history valid on the
    disclosure date.  BSE PIT names carry the target ISIN directly.  SAST is
    deliberately not used as a name source: it also contains institutional
    acquirers, and adding them would remove genuine marquee clients.
    """
    import duckdb

    con = duckdb.connect(":memory:")
    try:
        con.execute(f"ATTACH '{str(path).replace(chr(92), '/')}' AS snap (READ_ONLY)")
        con.execute("SET threads=4")
        norm = ("upper(trim(regexp_replace(regexp_replace(coalesce(%s,''), "
                "'[^A-Za-z0-9 ]', ' ', 'g'), '\\s+', ' ', 'g')))")
        pairs = con.execute(f"""
            WITH nse AS (
              SELECT DISTINCT sm.issuer AS issuer, {norm % 'ni.acquirer_name'} AS n
              FROM snap.nse_insider ni
              JOIN snap.symbol_isin_history h
                ON h.exchange='NSE' AND h.symbol=ni.symbol
               AND substr(ni.disseminated_at,1,10) BETWEEN h.first_date AND h.last_date
              JOIN snap.security_master sm ON sm.isin=h.isin
              WHERE ni.acquirer_name IS NOT NULL
            ), bse AS (
              SELECT DISTINCT sm.issuer AS issuer,
                     {norm % "json_extract_string(bi.raw_json, '$.\"Name(s) of the promoter and/or persons in promoter group\"')"} AS n
              FROM snap.bse_insider bi
              JOIN snap.security_master sm ON sm.isin=bi.isin
              WHERE json_extract_string(bi.raw_json, '$.\"Name(s) of the promoter and/or persons in promoter group\"') IS NOT NULL
            )
            SELECT * FROM nse UNION SELECT * FROM bse
        """).df()
        pairs = pairs.dropna().drop_duplicates()
        audit = {"insider_pairs": int(len(pairs)),
                 "insider_issuers": int(pairs["issuer"].nunique()),
                 "insider_names": int(pairs["n"].nunique())}
        return pairs, audit
    finally:
        con.close()


@dataclass
class DealData:
    raw: pd.DataFrame
    deduped: pd.DataFrame
    clean: pd.DataFrame
    m1: pd.DataFrame
    m2: pd.DataFrame
    m2_list: pd.DataFrame
    insider_pairs: pd.DataFrame
    audit: dict = field(default_factory=dict)
    insider_audit: dict = field(default_factory=dict)

    @property
    def evidence(self):
        return self.clean

    def events(self, definition):
        if definition == "M1":
            return aggregate_events(self.m1)
        if definition == "M2":
            return aggregate_events(self.m2)
        raise ValueError(definition)


def exclude_promoters(frame, pairs):
    """Remove client rows that are insiders of the deal's own issuer."""
    lookup = set(zip(pairs["issuer"].astype(str), pairs["n"].astype(str)))
    keep = []
    for issuer, client in zip(frame["issuer"].astype(str), frame["client_n"].astype(str)):
        keep.append((issuer, client) not in lookup)
    keep = np.asarray(keep, dtype=bool)
    token = frame["client_n"].astype(str).str.contains("PROMOTER", regex=False)
    excluded = ~keep | token.to_numpy()
    return frame.loc[~excluded].copy(), int(excluded.sum())


def select_m2(frame):
    """Top-20 repeat clients by distinct deal-days in 2021 only.

    Broker/prop names are removed with the declared M1 exclusion tokens.
    Promoter/insider rows were already removed company-specifically.
    """
    year = frame["date"].str[:4] == "2021"
    pool = frame.loc[year & ~broker_prop_mask(frame["client_n"])].copy()
    days = (pool.groupby("client_n", sort=False)["date"].nunique()
            .sort_values(ascending=False, kind="mergesort"))
    # Deterministic tie-break by normalized client name.
    ordered = sorted(days.items(), key=lambda kv: (-int(kv[1]), kv[0]))[:20]
    keep = {name for name, _ in ordered}
    selected = pool.loc[pool["client_n"].isin(keep)]
    rows = []
    for name, n_days in ordered:
        subset = selected.loc[selected["client_n"] == name]
        rows.append({"client_n": name,
                     "client_name": subset["client_name"].iloc[0] if len(subset) else name,
                     "distinct_deal_days_2021": int(n_days),
                     "deal_value_inr_2021": float(subset["value"].sum()),
                     "deal_rows_2021": int(len(subset))})
    return pd.DataFrame(rows), keep


def aggregate_events(frame, threshold=EVENT_THRESHOLD_INR):
    """Net client-set buy value per (issuer, date); event if >= Rs 1 crore."""
    if frame.empty:
        return pd.DataFrame(columns=["issuer", "date", "buy_value", "sell_value",
                                     "net_value", "buy_qty", "buy_vwap",
                                     "n_rows", "clients"])
    buy = frame.loc[frame["side"] == "BUY"]
    sell = frame.loc[frame["side"] == "SELL"]
    b = buy.groupby(["issuer", "date"], sort=False).agg(
        buy_value=("value", "sum"), buy_qty=("qty", "sum"), n_buy=("value", "size"))
    s = sell.groupby(["issuer", "date"], sort=False).agg(
        sell_value=("value", "sum"), n_sell=("value", "size"))
    out = b.join(s, how="outer").fillna(0.0)
    out["net_value"] = out["buy_value"] - out["sell_value"]
    out = out.loc[out["net_value"] >= threshold].copy()
    out["buy_vwap"] = np.where(out["buy_qty"] > 0,
                               out["buy_value"] / out["buy_qty"], np.nan)
    out["n_rows"] = (out["n_buy"] + out["n_sell"]).astype(int)
    # Keep a short client list for the audit CSV; no outcome is used.
    groups = frame.groupby(["issuer", "date"], sort=False)["client_name"].apply(
        lambda s: "; ".join(sorted(set(s))[:5]))
    out["clients"] = groups.reindex(out.index).fillna("")
    out = out.reset_index()
    out["date"] = out["date"].astype(str).str[:10]
    return out


def load_deals(path):
    """Full declared deal pipeline up to (but excluding) any price outcome."""
    raw_all = _load_raw_deals(path)
    audit = {"raw_rows": int(len(raw_all)),
             "raw_value_inr": float(raw_all["value"].sum())}
    mapped = raw_all.loc[raw_all["isin"].notna() & raw_all["issuer"].notna()
                         & ~raw_all["mapping_ambiguous"]].copy()
    audit["unmatched_rows"] = int(len(raw_all) - len(mapped))
    audit["unmatched_value_inr"] = float(raw_all.loc[~raw_all.index.isin(mapped.index), "value"].sum())
    by_year = []
    for year in range(2019, 2026):
        part = raw_all.loc[raw_all["date"].str[:4] == str(year)]
        ok = part.loc[part["isin"].notna() & part["issuer"].notna()
                      & ~part["mapping_ambiguous"]]
        by_year.append({"year": year,
                        "rows": int(len(part)),
                        "mapped_rows": int(len(ok)),
                        "unmatched_rows": int(len(part) - len(ok)),
                        "value_inr": float(part["value"].sum()),
                        "mapped_value_inr": float(ok["value"].sum()),
                        "unmatched_value_inr": float(part["value"].sum() - ok["value"].sum())})
    audit["by_year"] = by_year

    deduped, dedupe_audit = _dedupe_frame(mapped)
    audit.update(dedupe_audit)
    # M2 must be selected from data available in the first evidence year only;
    # dedupe and promoter removal are outcome-independent.
    pairs, insider_audit = load_insider_pairs(path)
    clean, excluded = exclude_promoters(deduped, pairs)
    audit["promoter_insider_rows_excluded"] = excluded
    audit["promoter_insider_value_excluded_inr"] = float(
        deduped.loc[~deduped.index.isin(clean.index), "value"].sum())
    audit["deduped_rows"] = int(len(deduped))
    audit["clean_rows"] = int(len(clean))
    audit["clean_value_inr"] = float(clean["value"].sum())
    audit["evidence_rows"] = int((clean["date"] >= EVIDENCE_START).sum())
    audit["evidence_value_inr"] = float(clean.loc[clean["date"] >= EVIDENCE_START, "value"].sum())

    evidence = clean.loc[(clean["date"] >= EVIDENCE_START)
                         & (clean["date"] <= EVIDENCE_END)].copy()
    evidence["m1"] = marquee_mask(evidence["client_n"])
    m1 = evidence.loc[evidence["m1"]].copy()
    m2_list, m2_names = select_m2(evidence)
    m2 = evidence.loc[evidence["client_n"].isin(m2_names)].copy()
    audit["m1_rows"] = int(len(m1))
    audit["m1_clients"] = int(m1["client_n"].nunique())
    audit["m2_rows"] = int(len(m2))
    audit["m2_clients"] = int(m2_list["client_n"].nunique())
    return DealData(raw=raw_all, deduped=deduped, clean=evidence, m1=m1, m2=m2,
                    m2_list=m2_list, insider_pairs=pairs, audit=audit,
                    insider_audit=insider_audit)


def top_clients(frame, n=100):
    """Top clients by gross deal value, with declared flag columns."""
    grouped = frame.groupby("client_n", sort=False).agg(
        client_name=("client_name", "first"),
        deal_value_inr=("value", "sum"),
        rows=("value", "size"),
        first_date=("date", "min"),
        last_date=("date", "max")).reset_index()
    grouped["m1_match"] = marquee_mask(grouped["client_n"])
    grouped["broker_prop"] = broker_prop_mask(grouped["client_n"])
    grouped = grouped.sort_values(["deal_value_inr", "client_n"],
                                  ascending=[False, True]).head(n)
    return grouped.reset_index(drop=True)
