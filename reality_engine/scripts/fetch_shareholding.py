"""Quarterly shareholding pattern (PIPELINE_TODO B3, 2026-10-19). Tables in equity_intelligence.db:

  shp_index     one row per NSE shareholding filing (corporate-share-holdings-master, month windows, equities + SME):
                symbol, isin, quarter_end, broadcast_at (IST, the point-in-time stamp), submission_date, promoter_pct,
                public_pct, revised flag, record_id, xbrl url. Raw JSON pages: raw_market/nse_shp_index/.
  shp_facts     every fact of the filing's category-level contexts (promoter group, mutual funds, insurance, FPI,
                domestic / foreign institutions, governments, public non-institutions ...): file, context, concept,
                value. Named-holder contexts (D_*: names, PANs) are skipped. XBRL kept gzipped in raw_market/nse_shp_xbrl/.
  shareholding  view: per filing promoter_pct, promoter_pledged_pct and promoter_encumbered_pct (pledged / all
                encumbered shares as % of the promoter group's own holding: CENTRUM 73.9M of 203.7M = 36.26%),
                fii_pct (foreign institutions incl. FPI), dii_pct (domestic institutions), mf_pct, insurance_pct,
                retail_pct (resident individuals), fpi_limit_utilised_pct, broadcast_at.
Percentages in the XBRL are fractions (0.5901); the view multiplies by 100.

    python -m reality_engine.scripts.fetch_shareholding --index --start 2019-01      # listing
    python -m reality_engine.scripts.fetch_shareholding --symbols                    # per-symbol listing, full history
    python -m reality_engine.scripts.fetch_shareholding --xbrl [--limit N]          # download (resumable, ~0.4 s each)
    python -m reality_engine.scripts.fetch_shareholding --parse                      # parse downloaded files
"""
import argparse
import datetime as dt
import gzip
import json
import re
import sqlite3
import time
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
DB = DATA / "equity_intelligence.db"
RAW = DATA / "raw_market"
DDL = """
CREATE TABLE IF NOT EXISTS shp_index (record_id TEXT PRIMARY KEY, idx TEXT, symbol TEXT, isin TEXT, name TEXT,
    quarter_end TEXT, broadcast_at TEXT, submission_date TEXT, promoter_pct REAL, public_pct REAL, revised TEXT,
    xbrl TEXT, file TEXT);
CREATE INDEX IF NOT EXISTS idx_shp_isin ON shp_index(isin, quarter_end);
CREATE TABLE IF NOT EXISTS shp_facts (file TEXT, context TEXT, concept TEXT, value TEXT, PRIMARY KEY (file, context, concept));
CREATE TABLE IF NOT EXISTS shp_parsed (file TEXT PRIMARY KEY, n_facts INTEGER, status TEXT, parsed_at TEXT);
"""
MON = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
FACT = re.compile(r"<in-bse-shp:([A-Za-z0-9]+) contextRef=\"([^\"]+)\"[^>]*>([^<]*)<")


def d_iso(s):
    """'30-SEP-2026' / '08-OCT-2026 15:06:04' -> ISO (IST as published)"""
    if not s:
        return None
    m = re.match(r"(\d{2})-([A-Z]{3})-(\d{4})(?: (\d{2}:\d{2}:\d{2}))?", s.strip().upper())
    if not m:
        return None
    d = f"{m.group(3)}-{MON[m.group(2)]:02d}-{m.group(1)}"
    return d + (f"T{m.group(4)}" if m.group(4) else "")


def fetcher():
    from reality_engine.scripts.fetch_nse_api_raw import NseFetcher
    return NseFetcher("nse_shp_index", dt.date.today(), dt.date.today())


def run_index(db, start, end):
    from reality_engine.scripts.fetch_nse_api_raw import API
    f = fetcher()
    out = RAW / "nse_shp_index"
    out.mkdir(parents=True, exist_ok=True)
    a = start
    while a <= end:
        b = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        for idx in ("equities", "sme"):
            data = None
            for attempt in range(4):
                try:
                    j = f.get(f"{API}corporate-share-holdings-master?index={idx}&from_date={a:%d-%m-%Y}&to_date={b:%d-%m-%Y}").json()
                    data = j if isinstance(j, list) else (j.get("data") or [])
                    break
                except Exception:  # noqa: BLE001
                    f.s = None; time.sleep(5 * (attempt + 1))
            if data is None:
                print(a, idx, "failed"); continue
            (out / f"{idx}_{a:%Y-%m}.json").write_text(json.dumps(data), encoding="utf-8")
            rows = [(str(r.get("recordId")), idx, r.get("symbol"), r.get("isin"), r.get("name"), d_iso(r.get("date")),
                     d_iso(r.get("broadcastDate")), d_iso(r.get("submissionDate")),
                     float(r["pr_and_prgrp"]) if str(r.get("pr_and_prgrp") or "").replace(".", "", 1).isdigit() else None,
                     float(r["public_val"]) if str(r.get("public_val") or "").replace(".", "", 1).isdigit() else None,
                     r.get("revisedData"), r.get("xbrl"),
                     (r.get("xbrl") or "").rsplit("/", 1)[-1] or None) for r in data if r.get("recordId")]
            with db:
                db.executemany("INSERT OR REPLACE INTO shp_index VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            print(f"{a:%Y-%m} {idx}: {len(rows)}", flush=True)
            time.sleep(1.0)
        a = b + dt.timedelta(days=1)


def to_rows(data, idx):
    return [(str(r.get("recordId")), idx, r.get("symbol"), r.get("isin"), r.get("name"), d_iso(r.get("date")),
             d_iso(r.get("broadcastDate")), d_iso(r.get("submissionDate")),
             float(r["pr_and_prgrp"]) if str(r.get("pr_and_prgrp") or "").replace(".", "", 1).isdigit() else None,
             float(r["public_val"]) if str(r.get("public_val") or "").replace(".", "", 1).isdigit() else None,
             r.get("revisedData"), r.get("xbrl"), (r.get("xbrl") or "").rsplit("/", 1)[-1] or None)
            for r in data if r.get("recordId")]


def run_symbols(db):
    """Per-symbol listing (the date-range listing is nearly empty before 2021: 17-42 filings a quarter in 2019-20).
    Symbols: every NSE symbol in symbol_isin_history (delisted included) + SME symbols + symbols already indexed."""
    from urllib.parse import quote

    from reality_engine.scripts.fetch_nse_api_raw import API
    out = RAW / "nse_shp_index" / "by_symbol"
    out.mkdir(parents=True, exist_ok=True)
    syms = {r[0] for r in db.execute("SELECT DISTINCT symbol FROM symbol_isin_history WHERE exchange = 'NSE'")}
    syms |= {r[0] for r in db.execute("SELECT DISTINCT symbol FROM mkt_nse_sme_daily")}
    syms |= {r[0] for r in db.execute("SELECT DISTINCT symbol FROM shp_index WHERE symbol IS NOT NULL")}
    done = {p.stem for p in out.glob("*.json")}
    todo = sorted(s for s in syms if s and s.replace("&", "_") not in done)
    f = fetcher()
    print(f"symbols {len(syms)}, to list {len(todo)}", flush=True)
    for n, sym in enumerate(todo, 1):
        data, used = None, None
        for idx in ("equities", "sme"):
            for attempt in range(3):
                try:
                    j = f.get(f"{API}corporate-share-holdings-master?index={idx}&symbol={quote(sym)}").json()
                    data = j if isinstance(j, list) else (j.get("data") or [])
                    break
                except Exception:  # noqa: BLE001
                    f.s = None; time.sleep(5 * (attempt + 1))
            if data:
                used = idx
                break
        (out / f"{sym.replace('&', '_')}.json").write_text(json.dumps(data or []), encoding="utf-8")
        if data:
            with db:
                db.executemany("INSERT OR REPLACE INTO shp_index VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", to_rows(data, used))
        if n % 200 == 0:
            print(f"symbols {n}/{len(todo)}; shp_index {db.execute('SELECT COUNT(*) FROM shp_index').fetchone()[0]}",
                  flush=True)
        time.sleep(0.6)


def run_xbrl(db, limit):
    out = RAW / "nse_shp_xbrl"
    out.mkdir(parents=True, exist_ok=True)
    have = {p.name[:-3] for p in out.glob("*.xml.gz")}
    todo = [(u, fn) for u, fn in db.execute("SELECT xbrl, file FROM shp_index WHERE xbrl LIKE 'http%.xml' "
                                            "ORDER BY quarter_end DESC") if fn not in have]
    todo = todo[:limit] if limit else todo
    f = fetcher()
    ok = err = 0
    for n, (u, fn) in enumerate(todo, 1):
        try:
            body = f.get(u).content
            if body.lstrip()[:1] == b"<":
                (out / (fn + ".gz")).write_bytes(gzip.compress(body)); ok += 1
            else:
                err += 1
        except Exception:  # noqa: BLE001
            f.s = None; err += 1
        if n % 500 == 0:
            print(f"shp xbrl {n}/{len(todo)} ok {ok} err {err}", flush=True)
        time.sleep(0.4)
    print(f"shp xbrl done {len(todo)} ok {ok} err {err}")


def run_parse(db):
    done = {r[0] for r in db.execute("SELECT file FROM shp_parsed")}
    files = [p for p in (RAW / "nse_shp_xbrl").glob("*.xml.gz") if p.name[:-3] not in done]
    for n, p in enumerate(files, 1):
        fn = p.name[:-3]
        try:
            t = gzip.decompress(p.read_bytes()).decode("utf-8", "replace")
            rows = [(fn, c, k, v.strip()) for k, c, v in FACT.findall(t) if not c.startswith("D_")
                    and not c.startswith("DetailsOfSBO") and "******" not in v]
            with db:
                db.executemany("INSERT OR REPLACE INTO shp_facts VALUES (?,?,?,?)", rows)
                db.execute("INSERT OR REPLACE INTO shp_parsed VALUES (?,?,?,?)",
                           (fn, len(rows), "ok" if rows else "no_facts", dt.datetime.now().isoformat(timespec="seconds")))
        except Exception as e:  # noqa: BLE001
            with db:
                db.execute("INSERT OR REPLACE INTO shp_parsed VALUES (?,?,?,?)", (fn, 0, f"error {e}"[:200], None))
        if n % 2000 == 0:
            print(f"parsed {n}/{len(files)}", flush=True)
    pct = "ShareholdingAsAPercentageOfTotalNumberOfShares"
    with db:
        db.execute("DROP VIEW IF EXISTS shareholding")
        db.execute(f"""CREATE VIEW shareholding AS
            SELECT i.symbol, i.isin, i.quarter_end, i.broadcast_at, i.revised, i.record_id, i.file,
              100 * MAX(CASE WHEN f.context = 'ShareholdingOfPromoterAndPromoterGroup_ContextI' AND f.concept = '{pct}'
                        THEN CAST(f.value AS REAL) END) AS promoter_pct,
              100 * MAX(CASE WHEN f.context = 'ShareholdingOfPromoterAndPromoterGroup_ContextI'
                        AND f.concept = 'EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares'
                        THEN CAST(f.value AS REAL) END) AS promoter_pledged_pct,
              100 * MAX(CASE WHEN f.context = 'ShareholdingOfPromoterAndPromoterGroup_ContextI'
                        AND f.concept = 'EncumberedSharesHeldAsPercentageOfTotalNumberOfShares'
                        THEN CAST(f.value AS REAL) END) AS promoter_encumbered_pct,
              100 * MAX(CASE WHEN f.context = 'InstitutionsForeign_ContextI' AND f.concept = '{pct}'
                        THEN CAST(f.value AS REAL) END) AS fii_pct,
              100 * MAX(CASE WHEN f.context = 'InstitutionsDomestic_ContextI' AND f.concept = '{pct}'
                        THEN CAST(f.value AS REAL) END) AS dii_pct,
              100 * MAX(CASE WHEN f.context = 'MutualFundsOrUTI_ContextI' AND f.concept = '{pct}'
                        THEN CAST(f.value AS REAL) END) AS mf_pct,
              100 * MAX(CASE WHEN f.context = 'InsuranceCompanies_ContextI' AND f.concept = '{pct}'
                        THEN CAST(f.value AS REAL) END) AS insurance_pct,
              100 * SUM(CASE WHEN f.context LIKE 'ResidentIndividual%' AND f.concept = '{pct}'
                        THEN CAST(f.value AS REAL) END) AS retail_pct,
              100 * MAX(CASE WHEN f.context = 'MainI' AND f.concept = 'PercentageOfLimitsUtilized'
                        THEN CAST(f.value AS REAL) END) AS fpi_limit_utilised_pct
            FROM shp_index i JOIN shp_facts f ON f.file = i.file GROUP BY i.record_id""")
    print("parsed:", db.execute("SELECT status, COUNT(*) FROM shp_parsed GROUP BY 1").fetchall())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--symbols", action="store_true", help="per-symbol listing (full history)")
    ap.add_argument("--xbrl", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--start", default="2019-01")
    ap.add_argument("--end", default=dt.date.today().strftime("%Y-%m"))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=600)
    db.executescript(DDL)
    if a.index:
        run_index(db, dt.date.fromisoformat(a.start + "-01"), dt.date.fromisoformat(a.end + "-01"))
    if a.symbols:
        run_symbols(db)
    if a.xbrl:
        run_xbrl(db, a.limit)
    if a.parse:
        run_parse(db)


if __name__ == "__main__":
    main()
