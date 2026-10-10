"""
Date the annual reports in corporate_documents from BSE's own annual-report list.

Our ANNUAL_REPORT rows were found via Screener links, so doc_date is the crawl date (2026-08-28/29 on ~26k rows).
BSE's AnnualReport API lists, per scrip code, every report with its year and the timestamp it was filed (dt_tm),
keyed by the same PDF file name we stored in source_url. That timestamp is the point-in-time date.

  fetch: one call per BSE scrip code -> table bse_annual_reports (raw rows kept as returned; resumable)
  apply: match by PDF file name; fills publication_date with dt_tm and sets pit_source='bse_ar_api', pit_tier=1
         only where publication_date is empty (rows already dated from the BSE feed keep bse_dissem_ts, which
         v_document_pit prefers anyway). Undo: UPDATE ... SET publication_date=NULL WHERE pit_source='bse_ar_api'.

Needs curl_cffi (BSE's API answers plain requests with an Akamai 403).

    python -m reality_engine.scripts.fetch_bse_annual_report_dates fetch
    python -m reality_engine.scripts.fetch_bse_annual_report_dates apply
    python -m reality_engine.scripts.fetch_bse_annual_report_dates report
"""
import argparse
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from curl_cffi import requests

DB = Path(__file__).resolve().parents[1] / "data" / "equity_intelligence.db"
API = "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport/w?scripcode={}"
HDR = {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}
SCHEMA = """CREATE TABLE IF NOT EXISTS bse_annual_reports (
  scripcode TEXT, year TEXT, file_name TEXT, file_key TEXT, dt_tm TEXT, fetched_at TEXT,
  PRIMARY KEY (scripcode, file_key));
CREATE TABLE IF NOT EXISTS bse_annual_reports_fetch (scripcode TEXT PRIMARY KEY, status INTEGER, n INTEGER, fetched_at TEXT);"""


def file_key(name):
    """'\\f246affb-....pdf.pdf' or '.../AttachHis/f246affb-....pdf' -> 'f246affb-...'; '73304533022.pdf' -> '73304533022'."""
    base = re.split(r"[\\/]", (name or "").strip())[-1]
    return re.sub(r"(\.pdf)+$", "", base, flags=re.I).lower()


def fetch(db, pause):
    db.executescript(SCHEMA)
    codes = [r[0] for r in db.execute(
        "SELECT DISTINCT m.bse_code FROM corporate_documents d JOIN master_companies m ON m.isin=d.isin "
        "WHERE d.doc_type='ANNUAL_REPORT' AND m.bse_code IS NOT NULL AND m.bse_code<>''")]
    done = {r[0] for r in db.execute("SELECT scripcode FROM bse_annual_reports_fetch WHERE status=200")}
    todo = [c for c in codes if str(c) not in done]
    print(f"scrip codes {len(codes)}, to fetch {len(todo)}", flush=True)
    s = requests.Session(impersonate="chrome120")
    for i, code in enumerate(todo, 1):
        code = str(code)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            r = s.get(API.format(code), headers=HDR, timeout=30)
            rows = r.json().get("Table", []) if r.status_code == 200 else []
            status = r.status_code
        except Exception as e:
            rows, status = [], -1
            print("error", code, str(e)[:80], flush=True)
        with db:
            db.executemany("INSERT OR REPLACE INTO bse_annual_reports VALUES (?,?,?,?,?,?)",
                           [(code, t.get("year"), t.get("file_name"), file_key(t.get("file_name")), t.get("dt_tm"), now)
                            for t in rows if t.get("file_name")])
            db.execute("INSERT OR REPLACE INTO bse_annual_reports_fetch VALUES (?,?,?,?)", (code, status, len(rows), now))
        if status in (403, 429):
            print("throttled", status, "at", code, "- sleeping 120 s", flush=True)
            time.sleep(120)
        if i % 100 == 0:
            print(f"{i}/{len(todo)}", flush=True)
        time.sleep(pause)


def apply(db):
    keys = {k: (dt, y) for k, dt, y in db.execute("SELECT file_key, dt_tm, year FROM bse_annual_reports WHERE dt_tm IS NOT NULL")}
    rows = db.execute("SELECT id, source_url FROM corporate_documents WHERE doc_type='ANNUAL_REPORT' AND publication_date IS NULL").fetchall()
    now = datetime.now().isoformat(timespec="seconds")
    upd = [(keys[file_key(u)][0], now, i) for i, u in rows if file_key(u) in keys]
    with db:
        db.executemany("UPDATE corporate_documents SET publication_date=?, pit_source='bse_ar_api', pit_tier=1, pit_applied_at=? "
                       "WHERE id=?", upd)
    print(f"undated annual reports {len(rows)}, dated now {len(upd)}")


def report(db):
    q = lambda s: db.execute(s).fetchall()
    print("fetch status", q("SELECT status, COUNT(*) FROM bse_annual_reports_fetch GROUP BY 1"))
    print("annual reports by PIT basis", q("SELECT pit_basis, COUNT(*) FROM v_document_pit WHERE doc_type='ANNUAL_REPORT' GROUP BY 1"))
    print("by filing year", q("SELECT substr(pit_date,1,4), COUNT(*) FROM v_document_pit WHERE doc_type='ANNUAL_REPORT' GROUP BY 1 ORDER BY 1"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["fetch", "apply", "report"])
    ap.add_argument("--pause", type=float, default=0.8, help="seconds between API calls")
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=120)
    {"fetch": lambda: fetch(db, a.pause), "apply": lambda: apply(db), "report": lambda: report(db)}[a.what]()


if __name__ == "__main__":
    main()
