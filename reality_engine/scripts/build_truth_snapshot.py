"""
Truth layer: build a dated, read-only research snapshot of clean daily prices.

Reads the live SQLite DB (read-only) and the raw scrip lists / BSE corporate actions in
``reality_engine/data/raw_market/``, and writes one DuckDB file:

    reality_engine/data/snapshots/truth_<YYYY-MM-DD>.duckdb

Research code reads snapshots, never the live DB (FRAMEWORK.md §6, layer 1).

Steps
  1. Identity. Every NSE symbol and BSE scrip code is mapped to an ISIN as of each date.
     A company (``entity_id``) is the 7-character ISIN issuer code (``INE117A``): it
     survives splits, face-value changes and renames, which change the ISIN's serial part
     but not the issuer part. Demerged companies get a new issuer code, so they are
     correctly separate entities.
  2. Unified daily rows per exchange (``px_nse``, ``px_bse``), equity only, with delivery.
  3. Corporate actions from NSE and BSE, parsed into price factors:
       split  (face value old -> new)      f = new / old
       bonus  a:b (a new for b held)       f = b / (a + b)
       rights a:b @ premium p, face v      f = TERP / P, TERP = (b*P + a*(v+p)) / (a+b)
       consolidation (BSE gives no ratio)  ratio inferred from the ex-date price jump
       dividend D                          total-return factor (P - D) / P
     where P is the last close before the ex-date. Prices before the ex-date are multiplied
     by f; volumes are divided by f.
  4. Unexplained jumps: overnight moves near a clean ratio (1/2, 1/5, 2x, 10x, ...) with no
     recorded action are added as *inferred* events and flagged.
  5. Adjusted series and the primary series (NSE when it traded that day, else BSE).
  6. ``truth_report``: coverage, unmapped rows, unparsed actions, residual jumps.

  7. Research tables (snapshot_research_tables.py, Q2 2026-10-19): results, AR, decks, concalls, Telegram, BSE
     announcements, insider / SAST / deals, FII-DII, policy, PIB - each with known_at_utc; pit_report, snapshot_meta.
Built as truth_<date>.duckdb.building and renamed when complete; the last 7 snapshots are kept. Backtests record the
snapshot date they read (snapshot_meta.snapshot_date).

Usage:
    python -m reality_engine.scripts.build_truth_snapshot [--date YYYY-MM-DD] [--prices-only]
"""

import argparse
import glob
import json
import math
import re
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

from reality_engine import config as cfg

RAW = cfg.DATA_DIR / "raw_market"
SNAP_DIR = cfg.DATA_DIR / "snapshots"
NSE_EQUITY_SERIES = ("EQ", "BE", "BZ", "SM", "ST")
EQUITY_ISIN_SQL = "regexp_matches(isin, '^INE[A-Z0-9]{4}[0-9]{2}[A-Z0-9]{2}[0-9]$')"
NSE_OLD_FORMAT_LAST = "2021-10-26"   # mkt_nse_eq_daily up to here, mkt_nse_full_daily after
CLEAN_RATIOS = [1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 2 / 3, 2 / 5, 3 / 4, 4 / 5,
                2, 3, 4, 5, 10, 20, 3 / 2, 5 / 2, 5 / 4]


# ----------------------------------------------------------------------------
# corporate-action text parsing
# ----------------------------------------------------------------------------
def _f(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_action(text: str, face_value=None):
    """Return (kind, params) for one corporate-action subject line, or (None, None)."""
    t = " ".join(str(text or "").split())
    low = t.lower()
    # Bonus preference shares / debentures (e.g. "Scheme Of Arrangement - Bonus Ncrps 4:1") do not
    # dilute equity and leave the share price unchanged; never treat them as an equity bonus.
    if any(k in low for k in ("ncrps", "preference", "debenture", "ncd")):
        return "restructure", {}
    m = re.search(r"(?:from|frm)\s*(?:rs|re)?\.?\s*([\d.]+)\s*/?-?\s*(?:per share)?\s*(?:to|-)\s*(?:rs|re)?\.?\s*([\d.]+)", low)
    if ("split" in low or "sub-division" in low or "sub division" in low) and m:
        old, new = _f(m.group(1)), _f(m.group(2))
        if old and new and new < old:
            return "split", {"factor": new / old}
    if "consolidat" in low:
        if m:
            old, new = _f(m.group(1)), _f(m.group(2))
            if old and new and new > old:
                return "consolidation", {"factor": new / old}
        return "consolidation", {"factor": None}
    if "bonus" in low:
        m2 = re.search(r"(\d+)\s*:\s*(\d+)", low)
        if m2:
            a, b = int(m2.group(1)), int(m2.group(2))
            if a > 0 and b > 0:
                return "bonus", {"factor": b / (a + b)}
        return "bonus", {"factor": None}
    if "right" in low:
        m2 = re.search(r"(\d+)\s*:\s*(\d+)", low)
        prem = re.search(r"premium\s*(?:of)?\s*(?:rs|re)?\.?\s*([\d.]+)", low)
        if m2:
            return "rights", {"a": int(m2.group(1)), "b": int(m2.group(2)),
                              "premium": _f(prem.group(1)) if prem else None, "face_value": _f(face_value)}
        return "rights", {}
    if "dividend" in low or "div -" in low:
        m3 = re.search(r"(?:rs|re)\.?\s*([\d.]+)", low)
        if m3:
            return "dividend", {"amount": _f(m3.group(1))}
        return "dividend", {}
    if any(k in low for k in ("demerger", "spin off", "spin-off", "scheme of arrangement", "amalgamation", "merger")):
        return "restructure", {}
    return None, None


def nearest_clean_ratio(r: float, tol: float = 0.06):
    best = min(CLEAN_RATIOS, key=lambda c: abs(math.log(r / c)))
    return best if abs(math.log(r / best)) < tol else None


# ----------------------------------------------------------------------------
def build(out_path: Path):
    con = duckdb.connect(str(out_path))
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{cfg.DB_PATH.as_posix()}' AS re (TYPE sqlite, READ_ONLY)")
    con.execute("SET preserve_insertion_order=false")
    sq = con.execute

    # ---------------- masters ----------------
    rows = []
    for f in glob.glob(str(RAW / "masters" / "bse_scrips_*.json")):
        for x in json.load(open(f, encoding="utf-8")):
            rows.append({"sc_code": str(x.get("SCRIP_CD", "")).strip(), "isin": (x.get("ISIN_NUMBER") or "").strip(),
                         "bse_symbol": (x.get("scrip_id") or "").strip(), "name": (x.get("Scrip_Name") or "").strip(),
                         "status": x.get("Status"), "bse_group": (x.get("GROUP") or "").strip(),
                         "face_value": _f(x.get("FACE_VALUE"))})
    bse_master = pd.DataFrame(rows).drop_duplicates(["sc_code", "isin"])
    sq("CREATE OR REPLACE TABLE bse_master AS SELECT * FROM bse_master")
    nse_l = pd.read_csv(RAW / "masters" / "nse_EQUITY_L.csv", dtype=str)
    nse_l.columns = [c.strip() for c in nse_l.columns]
    sme_l = pd.read_csv(RAW / "masters" / "nse_SME_EQUITY_L.csv", dtype=str)
    sme_l.columns = [c.strip() for c in sme_l.columns]
    nse_master = pd.concat([
        pd.DataFrame({"symbol": nse_l["SYMBOL"].str.strip(), "isin": nse_l["ISIN NUMBER"].str.strip(),
                      "name": nse_l["NAME OF COMPANY"].str.strip(), "segment": "MAIN"}),
        pd.DataFrame({"symbol": sme_l["SYMBOL"].str.strip(), "isin": sme_l["ISIN_NUMBER"].str.strip(),
                      "name": sme_l["NAME_OF_COMPANY"].str.strip(), "segment": "SME"})])
    sq("CREATE OR REPLACE TABLE nse_master AS SELECT * FROM nse_master")

    # ---------------- step 1: identity windows ----------------
    eq = ",".join(f"'{s}'" for s in NSE_EQUITY_SERIES)
    sq(f"""
    CREATE OR REPLACE TABLE nse_symbol_isin AS
    WITH obs AS (
        SELECT symbol, isin, CAST(date AS DATE) d FROM re.mkt_nse_eq_daily
         WHERE series IN ({eq}) AND {EQUITY_ISIN_SQL}
        UNION ALL
        SELECT symbol, isin, CAST(date AS DATE) FROM re.daily_price_delivery
         WHERE series IN ('EQ','BE') AND {EQUITY_ISIN_SQL}
    )
    SELECT symbol, isin, min(d) first_date, max(d) last_date, 'observed' src FROM obs GROUP BY 1, 2
    UNION ALL
    SELECT m.symbol, m.isin, DATE '2019-01-01', current_date, 'nse_listing'
      FROM nse_master m
     WHERE regexp_matches(m.isin, '^INE[A-Z0-9]{{4}}[0-9]{{2}}[A-Z0-9]{{2}}[0-9]$')
       AND NOT EXISTS (SELECT 1 FROM obs o WHERE o.symbol = m.symbol AND o.isin = m.isin)
    """)
    sq("""
    CREATE OR REPLACE TABLE bse_code_isin AS
    SELECT sc_code, isin, min(CAST(date AS DATE)) first_date, max(CAST(date AS DATE)) last_date, 'observed' src
      FROM re.mkt_bse_eq_daily WHERE file_format = 'udiff' AND isin LIKE 'IN%' GROUP BY 1, 2
    UNION ALL
    SELECT m.sc_code, m.isin, DATE '2019-01-01', current_date, 'bse_listing'
      FROM bse_master m
     WHERE m.isin LIKE 'IN%' AND m.sc_code IN (SELECT DISTINCT sc_code FROM re.mkt_bse_eq_daily)
       AND NOT EXISTS (SELECT 1 FROM re.mkt_bse_eq_daily u
                        WHERE u.file_format = 'udiff' AND u.sc_code = m.sc_code AND u.isin = m.isin)
    """)

    # ---------------- step 2: unified exchange rows ----------------
    # NSE: old format carries ISIN; full file is mapped symbol -> ISIN as of the date
    # (ASOF picks the latest window starting on or before the date; else the earliest one).
    sq(f"""
    CREATE OR REPLACE TABLE px_nse AS
    WITH old AS (
        SELECT CAST(date AS DATE) date, symbol, series, isin, open, high, low, close, prev_close,
               volume, turnover_inr AS value_inr, num_trades, deliverable_qty, delivery_pct, 'nse_cm' src
          FROM re.mkt_nse_eq_daily
         WHERE series IN ({eq}) AND date <= '{NSE_OLD_FORMAT_LAST}'
    ), full_rows AS (
        SELECT CAST(date AS DATE) date, symbol, series, open, high, low, close, prev_close,
               volume, turnover_lacs * 1e5 AS value_inr, num_trades, deliverable_qty, delivery_pct
          FROM re.mkt_nse_full_daily
         WHERE series IN ({eq}) AND date > '{NSE_OLD_FORMAT_LAST}'
    ), w AS (SELECT * FROM nse_symbol_isin),
    asof_hit AS (
        SELECT f.*, w.isin FROM full_rows f ASOF LEFT JOIN w ON f.symbol = w.symbol AND f.date >= w.first_date
    ), earliest AS (
        SELECT symbol, arg_min(isin, first_date) isin FROM w GROUP BY 1
    )
    SELECT * FROM old
    UNION ALL
    SELECT a.date, a.symbol, a.series, coalesce(a.isin, e.isin), a.open, a.high, a.low, a.close, a.prev_close,
           a.volume, a.value_inr, a.num_trades, a.deliverable_qty, a.delivery_pct, 'nse_full'
      FROM asof_hit a LEFT JOIN earliest e ON a.symbol = e.symbol
    """)
    sq("""
    CREATE OR REPLACE TABLE px_bse AS
    WITH raw AS (
        SELECT CAST(date AS DATE) date, sc_code, isin, coalesce(symbol, '') symbol, name, sc_group, open, high, low,
               close, prev_close, volume, turnover_inr AS value_inr, num_trades, file_format
          FROM re.mkt_bse_eq_daily
         WHERE (file_format = 'legacy' AND sc_type = 'Q')
            OR (file_format = 'udiff' AND substr(isin, 8, 2) = '01' AND isin LIKE 'INE%')
    ), w AS (SELECT * FROM bse_code_isin),
    asof_hit AS (
        SELECT r.*, w.isin AS map_isin FROM raw r ASOF LEFT JOIN w ON r.sc_code = w.sc_code AND r.date >= w.first_date
    ), earliest AS (SELECT sc_code, arg_min(isin, first_date) isin FROM w GROUP BY 1)
    SELECT a.date, a.sc_code, coalesce(a.isin, a.map_isin, e.isin) isin, a.symbol, a.name, a.sc_group,
           a.open, a.high, a.low, a.close, a.prev_close, a.volume, a.value_inr, a.num_trades,
           d.deliverable_qty, d.delivery_pct, 'bse_' || a.file_format src
      FROM asof_hit a
      LEFT JOIN earliest e ON a.sc_code = e.sc_code
      LEFT JOIN re.mkt_bse_delivery_daily d ON CAST(d.date AS DATE) = a.date AND d.sc_code = a.sc_code
    """)
    for t in ("px_nse", "px_bse"):
        sq(f"ALTER TABLE {t} ADD COLUMN entity_id VARCHAR")
        # Company equity only: INE + 4-char issuer + 2-digit type + 2-char serial + check digit.
        # Excludes ETFs / MF units (INF..., whose issuer code is the fund house, shared by many
        # schemes), partly-paid / DVR lines (IN9...), and synthetic INE_AUTO* placeholders.
        sq(f"UPDATE {t} SET entity_id = substr(isin, 1, 7) WHERE {EQUITY_ISIN_SQL}")

    # ---------------- step 3: corporate actions ----------------
    ev = []
    for r in sq("SELECT isin, symbol, subject, action_type, CAST(ex_date AS DATE), face_value "
                "FROM re.corporate_actions WHERE ex_date IS NOT NULL").fetchall():
        kind, p = parse_action(r[2], r[5])
        ev.append({"entity_id": (r[0] or "")[:7], "isin": r[0], "ex_date": r[4], "kind": kind, "params": json.dumps(p or {}),
                   "text": r[2], "source": "nse"})
    # NSE SME feed: its "isin" field is an internal number, so map symbol -> ISIN as of the ex-date.
    sym_windows = sq("SELECT symbol, isin, first_date, last_date FROM nse_symbol_isin").df()

    def sym_to_isin(sym, d):
        w = sym_windows[sym_windows["symbol"] == sym]
        if w.empty:
            return None
        hit = w[(w["first_date"] <= pd.Timestamp(d)) & (w["last_date"] >= pd.Timestamp(d))]
        return (hit if not hit.empty else w).iloc[0]["isin"]

    for f in glob.glob(str(RAW / "nse_corpact_sme" / "*.json")):
        for x in json.load(open(f, encoding="utf-8")):
            try:
                exd = datetime.strptime(x["exDate"], "%d-%b-%Y").date()
            except (KeyError, TypeError, ValueError):
                continue
            isin = sym_to_isin((x.get("symbol") or "").strip(), exd)
            kind, p = parse_action(x.get("subject"), x.get("faceVal"))
            ev.append({"entity_id": (isin or "")[:7], "isin": isin, "ex_date": exd, "kind": kind,
                       "params": json.dumps(p or {}), "text": x.get("subject"), "source": "nse_sme"})
    code_isin = dict(sq("SELECT sc_code, arg_max(isin, last_date) FROM bse_code_isin GROUP BY 1").fetchall())
    for f in glob.glob(str(RAW / "bse_corpact" / "*.json")):
        for x in json.load(open(f, encoding="utf-8")):
            isin = code_isin.get(str(x.get("scrip_code")))
            exd = datetime.strptime(x["exdate"], "%Y%m%d").date() if x.get("exdate") else None
            kind, p = parse_action(x.get("Purpose"))
            ev.append({"entity_id": (isin or "")[:7], "isin": isin, "ex_date": exd, "kind": kind,
                       "params": json.dumps(p or {}), "text": x.get("Purpose"), "source": "bse"})
    ca = pd.DataFrame(ev)
    ca = ca[ca["ex_date"].notna()]
    sq("CREATE OR REPLACE TABLE corp_action_raw AS SELECT * FROM ca")

    # primary daily close per entity (NSE first), used for factor computation and jump checks
    sq("""
    CREATE OR REPLACE TABLE px_primary_raw AS
    WITH n AS (SELECT entity_id, date, arg_max(close, coalesce(value_inr, 0)) AS close,
                      arg_max(open, coalesce(value_inr, 0)) AS open, sum(value_inr) value_inr FROM px_nse
                WHERE entity_id IS NOT NULL GROUP BY 1, 2),
         b AS (SELECT entity_id, date, arg_max(close, coalesce(value_inr, 0)) AS close,
                      arg_max(open, coalesce(value_inr, 0)) AS open, sum(value_inr) value_inr FROM px_bse
                WHERE entity_id IS NOT NULL GROUP BY 1, 2)
    SELECT coalesce(n.entity_id, b.entity_id) entity_id, coalesce(n.date, b.date) date,
           coalesce(n.close, b.close) AS "close", coalesce(n.open, b.open) AS "open",
           CASE WHEN n.close IS NOT NULL THEN 'NSE' ELSE 'BSE' END exch
      FROM n FULL OUTER JOIN b ON n.entity_id = b.entity_id AND n.date = b.date
    """)
    sq("""
    CREATE OR REPLACE TABLE px_primary_raw AS
    SELECT *, lag(close) OVER (PARTITION BY entity_id ORDER BY date) prev_close,
              lag(date) OVER (PARTITION BY entity_id ORDER BY date) prev_date
      FROM px_primary_raw
    """)

    # one row per (entity, ex_date, kind): prefer a parsed factor; NSE text over BSE text
    cap = sq("""
    WITH c AS (
        SELECT a.*, json_extract(params, '$.factor')::DOUBLE factor,
               row_number() OVER (PARTITION BY entity_id, ex_date, kind
                                  ORDER BY (json_extract(params, '$.factor') IS NULL), (source <> 'nse')) rn
          FROM corp_action_raw a
         WHERE kind IN ('split', 'bonus', 'consolidation', 'rights', 'dividend', 'restructure') AND entity_id <> ''
    )
    SELECT c.entity_id, c.ex_date, c.kind, c.params, c.text, c.source, c.factor,
           p.prev_close, p.close AS ex_close, p.open AS ex_open
      FROM c
      LEFT JOIN px_primary_raw p ON p.entity_id = c.entity_id AND p.date = c.ex_date
     WHERE rn = 1
    """).df()

    def price_factor(r):
        k, p = r["kind"], json.loads(r["params"])
        P = r["prev_close"]
        obs = (r["ex_open"] or r["ex_close"]) / P if P and (r["ex_open"] or r["ex_close"]) else None
        if k in ("split", "bonus"):
            return r["factor"], obs, "parsed" if r["factor"] else "missing_ratio"
        if k == "consolidation":
            if r["factor"]:
                return r["factor"], obs, "parsed"
            c = nearest_clean_ratio(obs, 0.15) if obs else None
            return (c, obs, "inferred_from_price") if c and c > 1 else (None, obs, "missing_ratio")
        if k == "rights" and P and p.get("a") and p.get("b") and p.get("face_value") is not None:
            R = (p["face_value"] or 0) + (p.get("premium") or 0)
            terp = (p["b"] * P + p["a"] * R) / (p["a"] + p["b"])
            return (terp / P if R < P else 1.0), obs, "parsed"
        return None, obs, "n/a"

    out = cap.apply(lambda r: pd.Series(price_factor(r), index=["price_factor", "observed_ratio", "factor_status"]),
                    axis=1)
    cap = pd.concat([cap, out], axis=1)
    cap["tr_factor"] = cap.apply(
        lambda r: (r["prev_close"] - json.loads(r["params"]).get("amount")) / r["prev_close"]
        if r["kind"] == "dividend" and r["prev_close"] and json.loads(r["params"]).get("amount")
        and json.loads(r["params"])["amount"] < r["prev_close"] else None, axis=1)
    # Validate against the observed ex-date move using the COMBINED factor of all capital actions
    # on that entity and day (a split and a bonus on the same ex-date is common: 10->5 plus 1:1 = 1/4).
    capk = cap["kind"].isin(["split", "bonus", "consolidation", "rights"]) & cap["price_factor"].notna()
    combined = (cap[capk].groupby(["entity_id", "ex_date"])["price_factor"]
                .apply(lambda s: float(pd.Series(s).prod())).rename("combined_factor").reset_index())
    cap = cap.merge(combined, on=["entity_id", "ex_date"], how="left")
    cap["residual"] = cap.apply(
        lambda r: math.log(r["observed_ratio"] / r["combined_factor"])
        if r["kind"] in ("split", "bonus", "consolidation") and r["combined_factor"] and r["observed_ratio"] else None,
        axis=1)
    sq("CREATE OR REPLACE TABLE corp_action AS SELECT * FROM cap")

    # ---------------- step 4: unexplained jumps -> inferred events ----------------
    jumps = sq("""
    SELECT p.entity_id, p.date, p.prev_date, p.prev_close, p.open, p.close, p.exch,
           coalesce(p.open, p.close) / p.prev_close r
      FROM px_primary_raw p
     WHERE p.prev_close > 0 AND coalesce(p.open, p.close) > 0
       AND (coalesce(p.open, p.close) / p.prev_close < 0.6 OR coalesce(p.open, p.close) / p.prev_close > 1.7)
       AND NOT EXISTS (SELECT 1 FROM corp_action c
                        WHERE c.entity_id = p.entity_id AND c.kind IN ('split','bonus','consolidation','rights','restructure')
                          AND c.ex_date BETWEEN p.prev_date AND p.date + INTERVAL 3 DAY)
    """).df()
    # A corporate action shows as a clean ratio at the open or the close; the other can be noisy.
    jumps["clean_ratio"] = jumps.apply(
        lambda r: nearest_clean_ratio(r["r"])
        or (nearest_clean_ratio(r["close"] / r["prev_close"]) if r["close"] and r["prev_close"] else None), axis=1)
    sq("CREATE OR REPLACE TABLE unexplained_jumps AS SELECT * FROM jumps")
    inferred = jumps[jumps["clean_ratio"].notna()].copy()
    inferred = pd.DataFrame({"entity_id": inferred["entity_id"], "ex_date": inferred["date"],
                             "kind": "inferred", "price_factor": inferred["clean_ratio"]})

    # ---------------- step 5: adjustment factors and adjusted series ----------------
    good = cap[cap["kind"].isin(["split", "bonus", "consolidation", "rights"]) & cap["price_factor"].notna()]
    good = good[(good["residual"].isna()) | (good["residual"].abs() < 0.35)]
    factors = pd.concat([good[["entity_id", "ex_date", "kind", "price_factor"]], inferred], ignore_index=True)
    divs = cap[cap["tr_factor"].notna()][["entity_id", "ex_date", "tr_factor"]]
    sq("CREATE OR REPLACE TABLE adj_factor AS SELECT * FROM factors")
    sq("CREATE OR REPLACE TABLE div_factor AS SELECT * FROM divs")
    # Cumulative factor for date d = product of factors with ex_date > d
    #   = exp(total_ln - running_ln up to the last ex_date <= d), via an ASOF join.
    for src, col in (("adj_factor", "price_factor"), ("div_factor", "tr_factor")):
        sq(f"""
        CREATE OR REPLACE TABLE {src}_cum AS
        WITH g AS (SELECT entity_id, CAST(ex_date AS DATE) ex_date, sum(ln({col})) l
                     FROM {src} WHERE {col} > 0 GROUP BY 1, 2)
        SELECT entity_id, ex_date,
               sum(l) OVER (PARTITION BY entity_id ORDER BY ex_date) run_l,
               sum(l) OVER (PARTITION BY entity_id) tot_l
          FROM g
        """)
    for t in ("px_nse", "px_bse"):
        sq(f"""
        CREATE OR REPLACE TABLE {t}_adj AS
        WITH a AS (
            SELECT x.*, f.run_l f_run FROM {t} x
            ASOF LEFT JOIN adj_factor_cum f ON x.entity_id = f.entity_id AND x.date >= f.ex_date
        ), b AS (
            SELECT a.*, d.run_l d_run FROM a
            ASOF LEFT JOIN div_factor_cum d ON a.entity_id = d.entity_id AND a.date >= d.ex_date
        )
        SELECT b.* EXCLUDE (f_run, d_run),
               exp(coalesce(ft.tot_l, 0) - coalesce(b.f_run, 0)) cum_price_factor,
               exp(coalesce(dt.tot_l, 0) - coalesce(b.d_run, 0)) cum_div_factor
          FROM b
          LEFT JOIN (SELECT DISTINCT entity_id, tot_l FROM adj_factor_cum) ft ON ft.entity_id = b.entity_id
          LEFT JOIN (SELECT DISTINCT entity_id, tot_l FROM div_factor_cum) dt ON dt.entity_id = b.entity_id
        """)
        sq(f"""
        CREATE OR REPLACE TABLE {t}_adj AS
        SELECT *, open * cum_price_factor adj_open, high * cum_price_factor adj_high,
               low * cum_price_factor adj_low, close * cum_price_factor adj_close,
               volume / cum_price_factor adj_volume,
               close * cum_price_factor * cum_div_factor tr_close
          FROM {t}_adj
        """)

    # primary series: NSE row when the entity traded on NSE that day, else BSE
    sq("""
    CREATE OR REPLACE TABLE px_daily AS
    WITH n AS (SELECT *, row_number() OVER (PARTITION BY entity_id, date ORDER BY value_inr DESC NULLS LAST) rn
                 FROM px_nse_adj WHERE entity_id IS NOT NULL),
         b AS (SELECT *, row_number() OVER (PARTITION BY entity_id, date ORDER BY value_inr DESC NULLS LAST) rn
                 FROM px_bse_adj WHERE entity_id IS NOT NULL)
    SELECT 'NSE' exch, entity_id, date, isin, symbol, series AS segment, open, high, low, close, volume,
           value_inr, deliverable_qty, delivery_pct, cum_price_factor, cum_div_factor,
           adj_open, adj_high, adj_low, adj_close, adj_volume, tr_close
      FROM n WHERE rn = 1
    UNION ALL
    SELECT 'BSE', b.entity_id, b.date, b.isin, b.symbol, b.sc_group, b.open, b.high, b.low, b.close, b.volume,
           b.value_inr, b.deliverable_qty, b.delivery_pct, b.cum_price_factor, b.cum_div_factor,
           b.adj_open, b.adj_high, b.adj_low, b.adj_close, b.adj_volume, b.tr_close
      FROM b WHERE rn = 1
       AND NOT EXISTS (SELECT 1 FROM n WHERE n.entity_id = b.entity_id AND n.date = b.date AND n.rn = 1)
    """)
    sq("""
    CREATE OR REPLACE TABLE entity AS
    SELECT entity_id, min(date) first_date, max(date) last_date, count(*) n_days,
           arg_max(isin, date) latest_isin, arg_max(symbol, date) latest_symbol,
           bool_or(exch = 'NSE') on_nse, bool_or(exch = 'BSE') bse_only_days
      FROM px_daily GROUP BY 1
    """)

    # ---------------- step 6: report ----------------
    rep = {}
    rep["built_at"] = datetime.now().isoformat(timespec="seconds")
    rep["source_db"] = str(cfg.DB_PATH)
    for t in ("px_nse", "px_bse", "px_daily", "entity", "corp_action", "adj_factor", "div_factor", "unexplained_jumps"):
        rep[f"rows_{t}"] = sq(f"SELECT count(*) FROM {t}").fetchone()[0]
    rep["nse_rows_unmapped"] = sq("SELECT count(*) FROM px_nse WHERE entity_id IS NULL").fetchone()[0]
    rep["bse_rows_unmapped"] = sq("SELECT count(*) FROM px_bse WHERE entity_id IS NULL").fetchone()[0]
    rep["actions_by_kind_status"] = sq("SELECT kind, factor_status, count(*) FROM corp_action GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
    rep["cap_actions_bad_residual"] = sq("""SELECT count(*) FROM corp_action WHERE kind IN ('split','bonus','consolidation')
                                             AND abs(residual) >= 0.35""").fetchone()[0]
    rep["jumps_inferred"] = int(len(inferred))
    rep["jumps_unexplained_no_clean_ratio"] = int(jumps["clean_ratio"].isna().sum())
    rep["residual_big_moves_after_adjustment"] = sq("""
        WITH d AS (SELECT entity_id, date, adj_close / lag(adj_close) OVER (PARTITION BY entity_id ORDER BY date) r
                     FROM px_daily)
        SELECT count(*) FROM d WHERE r < 0.6 OR r > 1.7""").fetchone()[0]
    rep["entities"] = sq("SELECT count(*), sum(CASE WHEN on_nse THEN 1 ELSE 0 END) FROM entity").fetchone()
    sq("CREATE OR REPLACE TABLE truth_report AS SELECT * FROM (SELECT ?::VARCHAR AS report_json)", [json.dumps(rep, default=str)])
    con.close()
    return rep


KEEP = 7   # dated snapshots kept (PIPELINE_TODO Q2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=date.today().isoformat(), help="snapshot label")
    ap.add_argument("--prices-only", action="store_true", help="skip the research tables (snapshot_research_tables)")
    args = ap.parse_args()
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    out = SNAP_DIR / f"truth_{args.date}.duckdb"
    tmp = SNAP_DIR / f"truth_{args.date}.duckdb.building"   # renamed only when complete: readers never see a half file
    tmp.unlink(missing_ok=True)
    t0 = datetime.now()
    rep = build(tmp)
    if not args.prices_only:
        from reality_engine.scripts.snapshot_research_tables import add_research_tables
        con = duckdb.connect(str(tmp))
        research = add_research_tables(con)
        rep["research_tables"] = len(research)
        rep["research_count_fail"] = [r[0] for r in research if r[4] is False]
        rep["research_time_unparsed"] = [r[0] for r in research if r[7]]
        con.execute("CREATE OR REPLACE TABLE snapshot_meta AS SELECT ?::VARCHAR snapshot_date, ?::TIMESTAMP built_from, "
                    "now()::TIMESTAMP built_to, ?::VARCHAR report_json",
                    [args.date, t0, json.dumps(rep, default=str)])
        con.close()
    out.unlink(missing_ok=True)
    tmp.rename(out)
    old = sorted(SNAP_DIR.glob("truth_????-??-??.duckdb"))[:-KEEP]
    for f in old:
        f.unlink()
    rep["removed_old_snapshots"] = [f.name for f in old]
    print(json.dumps(rep, indent=1, default=str))
    print(f"snapshot: {out}")


if __name__ == "__main__":
    main()
