"""Fetch annual-report files BSE lists but we never downloaded, and register them as ANNUAL_REPORT filings (2026-10-16).

Two sources:
  - the latest file BSE's AnnualReport API lists for a scrip-year (table bse_annual_reports) when we only fetched an
    older file of that year: companies re-upload corrected reports (Venus Remedies FY2026: the first upload was another
    company's AGM notice);
  - extra file keys given with --keys SCRIP:KEY (files seen on BSE that the listing table does not hold).
Each new file gets a corporate_documents row copied from a sibling report of the same scrip (isin, symbol), with
source 'bse_official', discovery_source 'bse_ar_refetch' and publication_date = BSE's dt_tm when known. The AR ingest
workers pick new rows up on their next pass (no restart). Re-runnable: a source_url already present is skipped.

    python -m reality_engine.scripts.fetch_missed_ar_files                 # dry run: list
    python -m reality_engine.scripts.fetch_missed_ar_files --apply --keys 526953:29971821-bfab-4659-a9d8-7cf5dc170d02
"""
import argparse
import collections
import hashlib
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from reality_engine.config import PDFS_DIR

from curl_cffi import requests

from reality_engine.scripts.fetch_bse_annual_report_dates import file_key

DATA = Path(__file__).resolve().parents[1] / "data"
URL = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{}.pdf"
HDR = {"Referer": "https://www.bseindia.com/"}


def todo(eq, extra):
    have = {file_key(u) for (u,) in eq.execute(
        "SELECT source_url FROM corporate_documents WHERE doc_type='ANNUAL_REPORT' AND source_url IS NOT NULL")}
    by = collections.defaultdict(list)
    for scrip, year, key, dt in eq.execute("SELECT scripcode, year, file_key, dt_tm FROM bse_annual_reports"):
        by[(scrip, year)].append((dt or "", key.lower(), year))
    out = []
    for (scrip, year), files in by.items():
        files.sort()
        dt, key, _ = files[-1]
        if key not in have and any(k in have for _, k, _ in files[:-1]):
            out.append((scrip, key, dt, year))
    for s in extra:
        scrip, _, key = s.partition(":")
        if key.lower() not in have:
            out.append((scrip, key.lower(), None, None))
    return out, have


def sibling(eq, scrip):
    """isin/symbol of an existing report of this BSE scrip (via the listing's file keys)."""
    keys = [k for (k,) in eq.execute("SELECT file_key FROM bse_annual_reports WHERE scripcode=?", (scrip,))]
    for k in keys:
        r = eq.execute("SELECT isin, symbol FROM corporate_documents WHERE doc_type='ANNUAL_REPORT' AND source_url LIKE ?",
                       (f"%{k}%",)).fetchone()
        if r:
            return r
    return eq.execute("SELECT isin, nse_symbol FROM master_companies WHERE bse_code=?", (scrip,)).fetchone()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--keys", default="", help="extra SCRIP:FILEKEY items, comma separated")
    a = ap.parse_args()
    eq = sqlite3.connect(DATA / "equity_intelligence.db", timeout=300)
    items, _ = todo(eq, [s for s in a.keys.split(",") if s.strip()])
    print(f"{len(items)} files to fetch")
    for scrip, key, dt, year in items:
        sib = sibling(eq, scrip)
        if not sib:
            print(f"  {scrip} {key}: no company for this scrip, skipped"); continue
        isin, sym = sib
        url = URL.format(key)
        if not a.apply:
            print(f"  {sym} ({scrip}) FY{year} {dt} {url}"); continue
        r = requests.get(url, headers=HDR, impersonate="chrome", timeout=120)
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            print(f"  {sym} {key}: HTTP {r.status_code}, {len(r.content)} bytes, not a PDF; skipped"); continue
        sha = hashlib.sha256(r.content).hexdigest()
        if eq.execute("SELECT 1 FROM corporate_documents WHERE sha256_hash=?", (sha,)).fetchone():
            print(f"  {sym} {key}: same bytes already stored under another URL; skipped"); continue
        d = PDFS_DIR / sym / "ANNUAL_REPORT"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{datetime.now():%Y%m%d}_{sha[:8]}_{key}.pdf"
        path.write_bytes(r.content)
        today = datetime.now().strftime("%Y-%m-%d")
        old = eq.execute("SELECT id, doc_type FROM corporate_documents WHERE source_url=?", (url,)).fetchone()
        if old:   # BSE's AR list names a file we stored as another doc type (e.g. OTHER_FILING without a file)
            eq.execute("""UPDATE corporate_documents SET doc_type='ANNUAL_REPORT', title='ANNUAL_REPORT', local_file_path=?,
                          file_size_bytes=?, sha256_hash=?, publication_date=COALESCE(publication_date, ?) WHERE id=?""",
                       (str(path), len(r.content), sha, dt, old[0]))
            eq.commit()
            print(f"  {sym} ({scrip}) FY{year}: row {old[0]} was {old[1]}; now ANNUAL_REPORT with the file")
            time.sleep(1.5); continue
        eq.execute("""INSERT INTO corporate_documents (isin, symbol, doc_type, title, doc_date, source_url, local_file_path,
                      file_size_bytes, sha256_hash, source, discovery_source, event_date, event_source, publication_date,
                      pit_source, pit_tier, pit_applied_at)
                      VALUES (?,?,'ANNUAL_REPORT','ANNUAL_REPORT',?,?,?,?,?,'bse_official','bse_ar_refetch',?,?,?,?,?,?)""",
                   (isin, sym, today, url, str(path), len(r.content), sha, (dt or today)[:10],
                    "bse_ar_api" if dt else "fetch_date", dt, "bse_ar_api" if dt else None, 1 if dt else None,
                    datetime.now().isoformat(timespec="seconds") if dt else None))
        eq.commit()
        print(f"  {sym} ({scrip}) FY{year}: stored {len(r.content):,} bytes -> {path.name}")
        time.sleep(1.5)


if __name__ == "__main__":
    main()
