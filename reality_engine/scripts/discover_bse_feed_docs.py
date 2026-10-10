"""
Add filings from the harvested BSE announcement feed (analysis/bse_announcements.db, every BSE company, 2020-01 ->
2026-09) to corporate_documents when we do not hold them yet, so run_annual_report_ingest --download-only fetches them.

Why: corporate_documents was filled from Screener links, which cover ~2,400 companies; the BSE feed covers every
BSE-listed company (SME included) and carries the exchange dissemination time.

Mapping (feed SUBCATNAME -> doc_type):
  'Earnings Call Transcript' -> CONCALL_TRANSCRIPT
Investor presentations are handled by fetch_decks.py (deck_sources), not here.

A feed row is skipped when its attachment is already in corporate_documents (same PDF file name) or the scrip code has
no known ISIN. New rows: source='bse_official', discovery_source='bse_feed', bse_newsid/bse_dissem_ts/bse_subcat filled,
doc_date = dissemination date.

    python -m reality_engine.scripts.discover_bse_feed_docs --since 2022-01-01 [--dry-run]
"""
import argparse
import re
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEED = ROOT / "analysis" / "bse_announcements.db"
LIVE = ROOT / "reality_engine" / "data" / "equity_intelligence.db"
SUBCATS = {"Earnings Call Transcript": "CONCALL_TRANSCRIPT"}


def key(u):
    return re.sub(r"(\.pdf)+$", "", re.split(r"[\\/=]", (u or "").strip())[-1], flags=re.I).lower()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2022-01-01")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    feed = sqlite3.connect(f"file:{FEED}?mode=ro", uri=True, timeout=60)
    db = sqlite3.connect(LIVE, timeout=120)
    have = {key(u) for (u,) in db.execute("SELECT source_url FROM corporate_documents WHERE source_url IS NOT NULL")}
    have_news = {str(n) for (n,) in db.execute("SELECT bse_newsid FROM corporate_documents WHERE bse_newsid IS NOT NULL")}
    code2 = {}
    for c, i, s in db.execute("SELECT sc_code, MAX(isin), MAX(symbol) FROM mkt_bse_eq_daily WHERE isin LIKE 'INE%' GROUP BY sc_code"):
        code2[str(c)] = (i, s)
    for c, i, s in db.execute("SELECT bse_code, isin, nse_symbol FROM master_companies WHERE bse_code IS NOT NULL AND isin LIKE 'INE%'"):
        code2[str(c)] = (i, s or code2.get(str(c), (None, None))[1])
    now = datetime.now().isoformat(timespec="seconds")
    for sub, doc_type in SUBCATS.items():
        # many companies file transcripts under 'Analyst / Investor Meet' instead; those count when the subject says so
        rows = feed.execute("SELECT NEWSID, SCRIP_CD, ATTACHMENTNAME, HEADLINE, DissemDT, symbol FROM ann "
                            "WHERE (SUBCATNAME=? OR (? = 'Earnings Call Transcript' AND SUBCATNAME='Analyst / Investor Meet' "
                            "       AND (HEADLINE LIKE '%transcript%' OR NEWSSUB LIKE '%transcript%'))) "
                            "AND DissemDT >= ? AND ATTACHMENTNAME IS NOT NULL AND ATTACHMENTNAME <> ''",
                            (sub, sub, a.since)).fetchall()
        new, dup, no_isin = [], 0, 0
        for nid, code, att, head, dis, sym in rows:
            if key(att) in have or str(nid) in have_news:
                dup += 1
                continue
            isin, msym = code2.get(str(code), (None, None))
            if not isin:
                no_isin += 1
                continue
            url = f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{att}"
            new.append((isin, msym or sym or str(code), doc_type, (head or doc_type)[:300], dis[:10], url, "bse_official", "bse_feed",
                        str(nid), dis, sub, now))
            have.add(key(att))
        print(f"{sub}: feed rows since {a.since} {len(rows)}; already held {dup}; no ISIN {no_isin}; new {len(new)}")
        if not a.dry_run and new:
            with db:
                db.executemany("""INSERT OR IGNORE INTO corporate_documents (isin, symbol, doc_type, title, doc_date, source_url, source,
                                  discovery_source, bse_newsid, bse_dissem_ts, bse_subcat, bse_joined_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", new)


if __name__ == "__main__":
    main()
