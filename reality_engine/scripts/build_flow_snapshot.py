"""T-235 stage 2: extend the truth price series back to 2010 for the capital-flow study.

The 2019+ truth snapshot already carries split/bonus/dividend-adjusted prices and the
official Nifty 500 TRI. T-236 loaded the 2010-2018 bhavcopies into ``mkt_nse_eq_daily``
(2010-01..2021-10) and the 2017+ tables. This script writes one self-contained DuckDB
that a research run can read exactly like a truth snapshot:

* ``px_daily`` / ``px_nse``: 2010-2018 NSE rows (adjusted) UNION the base snapshot's
  2019+ rows. 2010-2011 rows have no ISIN in the bhavcopy and are mapped by symbol
  (earliest observed window), so a rename does not split an entity.
* ``index_tri``: the base official rows plus a 2010-2018 BSE 500 total-return proxy,
  derived with ``fetch_index_tri.derive`` and rescaled to the Nifty 500 TRI level on
  2019-01-01, so returns across the seam are continuous.
* ``nse_deals`` / ``bse_deals`` / ``nse_insider``: base PIT rows UNION the 2010-2018
  rows (deal known after the close of the deal day; insider known at dissemination).
* ``symbol_isin_history``: rebuilt from the combined NSE panel, first date extended to
  2010-01-04 when a symbol maps to one ISIN only.
* ``shp_index``, ``results_key``, ``company_industry``, ``entity``: copied/rebuilt.

BSE 2010-2018 prices are deliberately *not* loaded: the live BSE table has no ISIN for
any row and its delivery column is corrupt (100% on a quarter to a third of rows).
NSE alone carries 1,500-2,000 symbols a year.

Usage:
    python -m reality_engine.scripts.build_flow_snapshot --out .tmp/t235/snap_ext.duckdb
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from reality_engine import config as cfg
from reality_engine.scripts.build_truth_snapshot import (
    EQUITY_ISIN_SQL,
    nearest_clean_ratio,
    parse_action,
)
from reality_engine.scripts.fetch_index_tri import derive

START = "2010-01-01"
SPLICE = "2019-01-01"
NSE_SERIES = ("EQ", "BE", "BZ", "SM", "ST")
BASE_TABLES = ("px_daily", "px_nse", "shp_index", "results_key", "company_industry",
               "corporate_actions", "security_master")


def _sqlite_attach(con, db: Path) -> None:
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{db.as_posix()}' AS re (TYPE sqlite, READ_ONLY)")


def _base_first(con) -> pd.DataFrame:
    """Per entity: its first 2019+ base row and the cumulative factors that row carries."""
    return con.execute(
        """SELECT entity_id, min(date) base_date,
                  arg_min(cum_price_factor, date) cum_price_factor,
                  arg_min(cum_div_factor, date) cum_div_factor
           FROM base.px_daily WHERE date >= DATE '2019-01-01' GROUP BY 1"""
    ).df()


def _nse_1018(con, start: str, splice: str) -> None:
    series = ",".join(f"'{s}'" for s in NSE_SERIES)
    con.execute(
        f"""CREATE OR REPLACE TABLE px_nse_1018 AS
            WITH obs AS (
                SELECT symbol, isin, TRY_CAST(date AS DATE) d
                  FROM re.mkt_nse_eq_daily
                 WHERE TRY_CAST(date AS DATE) >= DATE '{start}' AND isin IS NOT NULL AND {EQUITY_ISIN_SQL}
                UNION ALL
                SELECT symbol, isin, CAST(first_date AS DATE)
                  FROM base.symbol_isin_history WHERE exchange = 'NSE'
            ), win AS (
                SELECT symbol, isin, min(d) first_date, max(d) last_date, count(*) n_days
                  FROM obs GROUP BY 1, 2
            ), earliest AS (
                SELECT symbol, arg_min(isin, first_date) isin FROM win GROUP BY 1
            ), raw AS (
                SELECT TRY_CAST(date AS DATE) date, symbol, series, isin, open, high, low,
                       close, prev_close, volume, turnover_inr AS value_inr, num_trades,
                       deliverable_qty, delivery_pct
                  FROM re.mkt_nse_eq_daily
                 WHERE TRY_CAST(date AS DATE) >= DATE '{start}' AND TRY_CAST(date AS DATE) < DATE '{splice}'
                   AND series IN ({series})
            )
            SELECT r.date, r.symbol, r.series, coalesce(r.isin, e.isin) AS isin,
                   r.open, r.high, r.low, r.close, r.prev_close, r.volume, r.value_inr,
                   r.num_trades, r.deliverable_qty, r.delivery_pct,
                   CASE WHEN regexp_matches(coalesce(r.isin, e.isin), '^INE[A-Z0-9]{{4}}[0-9]{{2}}[A-Z0-9]{{2}}[0-9]$')
                        THEN substr(coalesce(r.isin, e.isin), 1, 7) END AS entity_id,
                   'nse_cm_1018' AS src
              FROM raw r LEFT JOIN earliest e ON e.symbol = r.symbol
             WHERE coalesce(r.isin, e.isin) IS NOT NULL"""
    )


def _corp_actions(con, start: str, splice: str, base_first: pd.DataFrame) -> pd.DataFrame:
    """Parse NSE actions, price them against the raw 2010-2018 panel, keep valid factors."""
    raw = con.execute(
        f"""SELECT isin, symbol, subject, TRY_CAST(ex_date AS DATE) ex_date, face_value
            FROM re.corporate_actions
            WHERE TRY_CAST(ex_date AS DATE) >= DATE '{start}'
              AND TRY_CAST(ex_date AS DATE) < DATE '2019-02-01'"""
    ).df()
    ev = []
    for r in raw.itertuples(index=False):
        kind, params = parse_action(r.subject, r.face_value)
        ev.append({"entity_id": (r.isin or "")[:7], "isin": r.isin, "ex_date": r.ex_date,
                   "kind": kind, "params": json.dumps(params or {}), "text": r.subject,
                   "source": "nse_live"})
    ca = pd.DataFrame(ev)
    ca = ca[ca["ex_date"].notna()]
    con.execute("CREATE OR REPLACE TEMP TABLE ca_raw AS SELECT * FROM ca")
    con.execute(
        """CREATE OR REPLACE TEMP TABLE px_primary_1018 AS
           SELECT entity_id, date, px_close AS "close", px_open AS open,
                  lag(px_close) OVER (PARTITION BY entity_id ORDER BY date) prev_close,
                  lag(date) OVER (PARTITION BY entity_id ORDER BY date) prev_date
             FROM (SELECT entity_id, date, arg_max(close, coalesce(value_inr, 0)) AS px_close,
                          arg_max(open, coalesce(value_inr, 0)) AS px_open
                     FROM px_nse_1018 WHERE entity_id IS NOT NULL GROUP BY 1, 2)"""
    )
    cap = con.execute(
        """WITH c AS (
             SELECT a.*, TRY_CAST(json_extract(params, '$.factor') AS DOUBLE) factor,
                    row_number() OVER (PARTITION BY entity_id, ex_date, kind
                                       ORDER BY (json_extract(params, '$.factor') IS NULL)) rn
               FROM ca_raw a
              WHERE kind IN ('split','bonus','consolidation','rights','dividend','restructure')
                AND entity_id <> '')
           SELECT c.*, p.prev_close, p.close ex_close, p.open ex_open
             FROM c LEFT JOIN px_primary_1018 p
               ON p.entity_id = c.entity_id AND p.date = c.ex_date
            WHERE rn = 1"""
    ).df()

    def price_factor(r):
        k, p = r["kind"], json.loads(r["params"])
        P = r["prev_close"]
        obs = (r["ex_open"] or r["ex_close"]) / P if P and (r["ex_open"] or r["ex_close"]) else None
        if k in ("split", "bonus"):
            return p.get("factor"), obs, "parsed" if p.get("factor") else "missing_ratio"
        if k == "consolidation":
            if p.get("factor"):
                return p["factor"], obs, "parsed"
            c = nearest_clean_ratio(obs, 0.15) if obs else None
            return (c, obs, "inferred_from_price") if c and c > 1 else (None, obs, "missing_ratio")
        if k == "rights" and P and p.get("a") and p.get("b") and p.get("face_value") is not None:
            R = (p.get("face_value") or 0) + (p.get("premium") or 0)
            terp = (p["b"] * P + p["a"] * R) / (p["a"] + p["b"])
            return (terp / P if R < P else 1.0), obs, "parsed"
        return None, obs, "n/a"

    out = cap.apply(lambda r: pd.Series(price_factor(r),
                                        index=["price_factor", "observed_ratio", "factor_status"]), axis=1)
    cap = pd.concat([cap, out], axis=1)
    cap["tr_factor"] = cap.apply(
        lambda r: (r["prev_close"] - json.loads(r["params"]).get("amount")) / r["prev_close"]
        if r["kind"] == "dividend" and r["prev_close"] and json.loads(r["params"]).get("amount")
        and json.loads(r["params"])["amount"] < r["prev_close"] else None, axis=1)
    capk = cap["kind"].isin(["split", "bonus", "consolidation", "rights"]) & cap["price_factor"].notna()
    combined = (cap[capk].groupby(["entity_id", "ex_date"])["price_factor"]
                .apply(lambda s: float(pd.Series(s).prod())).rename("combined_factor").reset_index())
    cap = cap.merge(combined, on=["entity_id", "ex_date"], how="left")
    cap["residual"] = cap.apply(
        lambda r: math.log(r["observed_ratio"] / r["combined_factor"])
        if r["kind"] in ("split", "bonus", "consolidation") and r["combined_factor"] and r["observed_ratio"] else None,
        axis=1)
    good = cap[cap["kind"].isin(["split", "bonus", "consolidation", "rights"]) & cap["price_factor"].notna()]
    good = good[(good["residual"].isna()) | (good["residual"].abs() < 0.35)]
    # An action after the entity's first base date is already inside that base row's
    # cumulative factor; keeping it here would double-count it.
    first = base_first.set_index("entity_id")["base_date"]
    keep = [not (e in first.index and ex > first.loc[e])
            for e, ex in zip(good["entity_id"], good["ex_date"])]
    good = good[keep]
    factors = good[["entity_id", "ex_date", "kind", "price_factor"]]
    divs = cap[cap["tr_factor"].notna()][["entity_id", "ex_date", "tr_factor"]]
    divs = divs[[not (e in first.index and ex > first.loc[e])
                 for e, ex in zip(divs["entity_id"], divs["ex_date"])]]
    con.execute("CREATE OR REPLACE TEMP TABLE adj_factor_1018 AS SELECT * FROM factors")
    print(f"  corp actions: cap={len(cap):,} factors={len(factors):,} divs={len(divs):,} cols={list(divs.columns)}")
    if divs.empty:
        divs = pd.DataFrame({"entity_id": pd.Series(dtype=str), "ex_date": pd.Series(dtype="datetime64[ns]"),
                             "tr_factor": pd.Series(dtype=float)})
    con.execute("CREATE OR REPLACE TEMP TABLE div_factor_1018 AS SELECT * FROM divs")

    # Unrecorded clean-ratio jumps: same logic as build_truth_snapshot step 4, with two
    # guards the 2010-2018 penny-stock tape needs. Below Rs 5 a 5-paise tick is a 33-100%
    # "jump" that lands on 3/2, 2 or 1/2, so price level is a hard floor; and a company
    # cannot have two genuine capital actions inside 120 days.
    jumps = con.execute(
        """SELECT p.entity_id, p.date, p.prev_date, p.prev_close, p.open, p.close,
                  coalesce(p.open, p.close) / p.prev_close r
             FROM px_primary_1018 p
            WHERE p.prev_close >= 5 AND coalesce(p.open, p.close) > 0
              AND (coalesce(p.open, p.close) / p.prev_close < 0.6
                OR coalesce(p.open, p.close) / p.prev_close > 1.7)
              AND NOT EXISTS (SELECT 1 FROM ca_raw c
                               WHERE c.entity_id = p.entity_id
                                 AND c.kind IN ('split','bonus','consolidation','rights','restructure')
                                 AND c.ex_date BETWEEN p.prev_date AND p.date + INTERVAL 3 DAY)"""
    ).df()
    jumps["clean_ratio"] = jumps.apply(
        lambda r: nearest_clean_ratio(r["r"])
        or (nearest_clean_ratio(r["close"] / r["prev_close"]) if r["close"] and r["prev_close"] else None),
        axis=1)
    inferred = jumps[jumps["clean_ratio"].notna()].copy()
    inferred = pd.DataFrame({"entity_id": inferred["entity_id"], "ex_date": inferred["date"],
                             "kind": "inferred", "price_factor": inferred["clean_ratio"]})
    inferred = inferred.sort_values(["entity_id", "ex_date"])
    keep, last = [], {}
    for r in inferred.itertuples():
        prev = last.get(r.entity_id)
        if prev is None or (r.ex_date - prev).days >= 120:
            keep.append(r.Index)
            last[r.entity_id] = r.ex_date
    inferred = inferred.loc[keep]
    factors = pd.concat([factors, inferred], ignore_index=True)
    con.execute("CREATE OR REPLACE TEMP TABLE adj_factor_1018 AS SELECT * FROM factors")
    con.execute("CREATE OR REPLACE TABLE flow_adj_factor AS SELECT * FROM factors")
    con.execute("CREATE OR REPLACE TABLE flow_div_factor AS SELECT * FROM divs")
    return cap


def _adjust(con, base_first: pd.DataFrame) -> None:
    con.execute("CREATE OR REPLACE TEMP TABLE base_first AS SELECT * FROM base_first")
    for src, col in (("adj_factor_1018", "price_factor"), ("div_factor_1018", "tr_factor")):
        con.execute(
            f"""CREATE OR REPLACE TEMP TABLE {src}_cum AS
                WITH g AS (SELECT entity_id, CAST(ex_date AS DATE) ex_date, sum(ln({col})) l
                             FROM {src} WHERE {col} > 0 GROUP BY 1, 2)
                SELECT entity_id, ex_date,
                       sum(l) OVER (PARTITION BY entity_id ORDER BY ex_date) run_l,
                       sum(l) OVER (PARTITION BY entity_id) tot_l FROM g"""
        )
    con.execute(
        """CREATE OR REPLACE TABLE px_nse_1018_adj AS
           WITH a AS (
               SELECT x.*, f.run_l f_run FROM px_nse_1018 x
               ASOF LEFT JOIN adj_factor_1018_cum f ON x.entity_id = f.entity_id AND x.date >= f.ex_date
           ), b AS (
               SELECT a.*, d.run_l d_run FROM a
               ASOF LEFT JOIN div_factor_1018_cum d ON a.entity_id = d.entity_id AND a.date >= d.ex_date
           )
           SELECT b.* EXCLUDE (f_run, d_run),
                  exp(coalesce(ft.tot_l, 0) - coalesce(b.f_run, 0)) * coalesce(bf.cum_price_factor, 1) AS cum_price_factor,
                  exp(coalesce(dt.tot_l, 0) - coalesce(b.d_run, 0)) * coalesce(bf.cum_div_factor, 1) AS cum_div_factor
             FROM b
             LEFT JOIN (SELECT DISTINCT entity_id, tot_l FROM adj_factor_1018_cum) ft ON ft.entity_id = b.entity_id
             LEFT JOIN (SELECT DISTINCT entity_id, tot_l FROM div_factor_1018_cum) dt ON dt.entity_id = b.entity_id
             LEFT JOIN base_first bf ON bf.entity_id = b.entity_id"""
    )
    con.execute(
        """CREATE OR REPLACE TABLE px_nse_1018_adj AS
           SELECT *, open * cum_price_factor adj_open, high * cum_price_factor adj_high,
                  low * cum_price_factor adj_low, close * cum_price_factor adj_close,
                  volume / cum_price_factor adj_volume,
                  close * cum_price_factor * cum_div_factor tr_close
             FROM px_nse_1018_adj"""
    )


def _index_proxy(con) -> pd.DataFrame:
    rows = con.execute(
        """SELECT CAST(date AS VARCHAR) d, close, div_yield FROM re.mkt_bse_index_daily
           WHERE trim(index_code) = 'BSE500' AND close IS NOT NULL AND date < '2019-01-02'
           ORDER BY date"""
    ).df()
    tri = derive([(r.d, r.close, r.div_yield) for r in rows.itertuples(index=False)])
    proxy = pd.DataFrame(tri, columns=["date", "tri"])
    official = con.execute(
        """SELECT tri FROM base.index_tri WHERE index_name = 'NIFTY 500'
           AND date = DATE '2019-01-01'"""
    ).fetchone()
    if official and not proxy.empty and proxy["date"].iloc[-1] == "2019-01-01":
        scale = float(official[0]) / float(proxy["tri"].iloc[-1])
        proxy["tri"] = proxy["tri"] * scale
        proxy = proxy[proxy["date"] < "2019-01-01"].copy()
        proxy["price"] = None
        proxy["index_name"] = "NIFTY 500"
        proxy["source"] = "bseindia.com BSE500 price + div_yield (proxy)"
        proxy["method"] = "derived_proxy_bse500"
        proxy["fetched_at"] = pd.Timestamp.now().isoformat(timespec="seconds")
    else:
        proxy = pd.DataFrame(columns=["index_name", "date", "tri", "price", "source", "method", "fetched_at"])
    return proxy


def build(truth: Path, db: Path, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / "duckdb_tmp_build"
    tmp.mkdir(exist_ok=True)
    con = duckdb.connect(str(out))
    con.execute("SET memory_limit='4GB'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    _sqlite_attach(con, db)
    con.execute(f"ATTACH '{truth.as_posix()}' AS base (TYPE duckdb, READ_ONLY)")
    rep: dict[str, object] = {}
    try:
        _nse_1018(con, START, SPLICE)
        first = _base_first(con)
        cap = _corp_actions(con, START, SPLICE, first)
        _adjust(con, first)

        # 2010-2018 primary series (NSE only; one row per entity/date).
        con.execute(
            """CREATE OR REPLACE TABLE px_daily_1018 AS
               SELECT 'NSE' exch, entity_id, date, isin, symbol, series segment,
                      open, high, low, close, volume, value_inr, deliverable_qty, delivery_pct,
                      cum_price_factor, cum_div_factor, adj_open, adj_high, adj_low,
                      adj_close, adj_volume, tr_close
                 FROM (SELECT *, row_number() OVER (PARTITION BY entity_id, date
                                                    ORDER BY value_inr DESC NULLS LAST) rn
                         FROM px_nse_1018_adj WHERE entity_id IS NOT NULL)
                WHERE rn = 1"""
        )
        proxy = _index_proxy(con)
        con.execute("CREATE OR REPLACE TEMP TABLE proxy AS SELECT * FROM proxy")
        con.execute(
            """CREATE OR REPLACE TABLE index_tri AS
               SELECT index_name, CAST(date AS VARCHAR) AS date, tri, price, source, method, fetched_at
                 FROM proxy
               UNION ALL
               SELECT index_name, CAST(date AS VARCHAR) AS date, tri, price, source, method, fetched_at
                 FROM base.index_tri WHERE TRY_CAST(date AS DATE) >= DATE '2019-01-01'"""
        )
        # Deals: base PIT rows (2019+) union the live pre-2019 rows with a next-session stamp.
        con.execute(
            """CREATE OR REPLACE TABLE nse_deals AS
               SELECT * FROM base.nse_deals
               UNION ALL
               SELECT date, deal_type, symbol, security, client_name, buy_sell, quantity, price,
                      remarks, seq, 'date_close', CAST(date AS TIMESTAMP) + INTERVAL '18 hours 29 minutes 59 seconds',
                      'day'
                 FROM re.mkt_nse_deals WHERE date < '2019-01-01'"""
        )
        con.execute(
            """CREATE OR REPLACE TABLE bse_deals AS
               SELECT * FROM base.bse_deals
               UNION ALL
               SELECT date, deal_type, sc_code, scrip_name, client_name, buy_sell, quantity, price,
                      seq, 'date_close', CAST(date AS TIMESTAMP) + INTERVAL '18 hours 29 minutes 59 seconds',
                      'day'
                 FROM re.mkt_bse_deals WHERE date < '2019-01-01'"""
        )
        # Insider: base 2019+ rows, plus pre-2019 rows stamped at dissemination (IST -> UTC).
        con.execute(
            """CREATE OR REPLACE TABLE nse_insider AS
               SELECT * FROM base.nse_insider
               UNION ALL
               SELECT did, pid, symbol, company, acquirer_name, person_category, security_type,
                      transaction_type, acquisition_mode, securities_qty, securities_value,
                      buy_qty, buy_value, sell_qty, sell_value, before_shares, before_pct,
                      after_shares, after_pct, acq_from, acq_to, intimation_date, disseminated_at,
                      exchange, xbrl, raw_json, acq_from_raw, acq_to_raw, intimation_date_raw,
                      'disseminated_at',
                      CAST(TRY_CAST(disseminated_at AS TIMESTAMP) - INTERVAL '5 hours 30 minutes' AS TIMESTAMP),
                      'minute'
                 FROM re.mkt_nse_insider
                WHERE intimation_date >= '2015-11-01' AND intimation_date < '2019-01-01'
                  AND TRY_CAST(disseminated_at AS TIMESTAMP) IS NOT NULL"""
        )
        con.execute("CREATE OR REPLACE TABLE shp_index AS SELECT * FROM base.shp_index")
        con.execute("CREATE OR REPLACE TABLE results_key AS SELECT * FROM base.results_key")
        con.execute("CREATE OR REPLACE TABLE company_industry AS SELECT * FROM base.company_industry")
        con.execute("CREATE OR REPLACE TABLE corporate_actions AS SELECT * FROM base.corporate_actions")
        # Combined price panel. px_nse stays the raw exchange table (the study reads only
        # its delivery column); px_nse_1018_adj carries the adjustment columns.
        con.execute(
            """CREATE OR REPLACE TABLE px_nse AS
               SELECT date, symbol, series, isin, open, high, low, close, prev_close, volume,
                      value_inr, num_trades, deliverable_qty, delivery_pct, src, entity_id
                 FROM px_nse_1018_adj
               UNION ALL
               SELECT date, symbol, series, isin, open, high, low, close, prev_close, volume,
                      value_inr, num_trades, deliverable_qty, delivery_pct, src, entity_id
                 FROM base.px_nse"""
        )
        con.execute("CREATE OR REPLACE TABLE px_daily AS SELECT * FROM px_daily_1018 UNION ALL SELECT * FROM base.px_daily")
        con.execute(
            """CREATE OR REPLACE TABLE entity AS
               SELECT entity_id, min(date) first_date, max(date) last_date, count(*) n_days,
                      arg_max(isin, date) latest_isin, arg_max(symbol, date) latest_symbol,
                      bool_or(exch = 'NSE') on_nse, bool_or(exch = 'BSE') bse_only_days
                 FROM px_daily GROUP BY 1"""
        )
        # Symbol windows: extend a one-ISIN symbol back to 2010 so 2010-2011 rows and
        # pre-2019 insider/deal rows resolve; keep observed windows when a symbol changed hands.
        con.execute(
            """CREATE OR REPLACE TABLE symbol_isin_history AS
               WITH w AS (
                   SELECT 'NSE' exchange, symbol, isin, min(date) first_date, max(date) last_date,
                          count(*) n_days
                     FROM px_nse WHERE isin IS NOT NULL AND regexp_matches(isin, '^INE[A-Z0-9]{4}[0-9]{2}[A-Z0-9]{2}[0-9]$')
                    GROUP BY 1, 2, 3
               ), one AS (SELECT symbol FROM w GROUP BY 1 HAVING count(*) = 1)
               SELECT exchange, symbol, isin, CAST(least(first_date, CASE WHEN symbol IN (SELECT symbol FROM one)
                        THEN DATE '2010-01-04' ELSE first_date END) AS VARCHAR) first_date,
                      CAST(last_date AS VARCHAR) last_date, n_days
                 FROM w"""
        )
        # BSE code windows for pre-2019 BSE deals: current master mapping, 2010-2018 window.
        con.execute(
            """CREATE OR REPLACE TABLE bse_code_isin AS
               SELECT * FROM base.bse_code_isin
               UNION ALL
               SELECT s.bse_code, s.isin, DATE '2010-01-04', DATE '2018-12-31', 'security_master'
                 FROM base.security_master s
                WHERE s.bse_code IS NOT NULL AND s.isin LIKE 'IN%'
                  AND NOT EXISTS (SELECT 1 FROM base.bse_code_isin b WHERE b.sc_code = s.bse_code)"""
        )
        # Diagnostics.
        seam = con.execute(
            """WITH a AS (SELECT entity_id, max(date) d, arg_max(adj_close, date) ac
                           FROM px_daily_1018 GROUP BY 1),
                    b AS (SELECT entity_id, min(date) d, arg_min(adj_close, date) ac
                            FROM base.px_daily GROUP BY 1)
               SELECT count(*) n, sum(CASE WHEN abs(ln(b.ac / a.ac)) > 0.5 THEN 1 ELSE 0 END) bad
                 FROM a JOIN b USING (entity_id) WHERE b.d <= a.d + INTERVAL 10 DAY"""
        ).fetchone()
        rep.update({
            "rows_px_daily_1018": con.execute("SELECT count(*) FROM px_daily_1018").fetchone()[0],
            "rows_px_daily": con.execute("SELECT count(*) FROM px_daily").fetchone()[0],
            "entities_1018": con.execute("SELECT count(DISTINCT entity_id) FROM px_daily_1018").fetchone()[0],
            "corp_actions_parsed": int(len(cap)),
            "corp_actions_price": int((cap["price_factor"].notna()).sum()),
            "corp_actions_div": int(cap["tr_factor"].notna().sum()),
            "inferred_jumps": int(con.execute("SELECT count(*) FROM adj_factor_1018 WHERE kind='inferred'").fetchone()[0]),
            "index_proxy_days": int(len(proxy)),
            "index_proxy_scale_last": float(proxy["tri"].iloc[-1]) if not proxy.empty else None,
            "nse_deals": con.execute("SELECT count(*) FROM nse_deals").fetchone()[0],
            "bse_deals": con.execute("SELECT count(*) FROM bse_deals").fetchone()[0],
            "nse_insider": con.execute("SELECT count(*) FROM nse_insider").fetchone()[0],
            "symbol_windows": con.execute("SELECT count(*) FROM symbol_isin_history").fetchone()[0],
            "seam_entities_checked": int(seam[0] or 0),
            "seam_jumps_gt_2x": int(seam[1] or 0),
            "px_start": str(con.execute("SELECT min(date) FROM px_daily").fetchone()[0]),
            "px_end": str(con.execute("SELECT max(date) FROM px_daily").fetchone()[0]),
        })
    finally:
        con.close()
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--truth", default=str(cfg.DATA_DIR / "snapshots" / "truth_2026-11-04.duckdb"))
    ap.add_argument("--db", default=str(cfg.DB_PATH))
    ap.add_argument("--out", default=".tmp/t235/snap_ext.duckdb")
    args = ap.parse_args(argv)
    rep = build(Path(args.truth), Path(args.db), Path(args.out))
    print(json.dumps(rep, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
