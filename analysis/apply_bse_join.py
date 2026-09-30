"""
Join corporate_documents to the harvested BSE announcement feed by PDF name (additive, idempotent).

Key: corporate_documents.source_url 'Pname=<guid>.pdf'  <->  ann.ATTACHMENTNAME.
Adds bse_newsid, bse_dissem_ts (exact dissemination timestamp, IST), bse_news_dt, bse_subcat,
bse_joined_at. Never touches doc_date / event_date / call_date / publication_date.
Safe to re-run as the harvest grows: only rows with bse_newsid IS NULL are considered.

  python analysis/apply_bse_join.py            # dry run, read-only
  python analysis/apply_bse_join.py --apply
  python analysis/apply_bse_join.py --rollback
"""
from __future__ import annotations

import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

LIVE = "reality_engine/data/equity_intelligence.db"
ANN = "analysis/bse_announcements.db"
NEW_COLS = ["bse_newsid TEXT", "bse_dissem_ts TEXT", "bse_news_dt TEXT", "bse_subcat TEXT", "bse_joined_at TEXT"]
PN = re.compile(r"(?:Pname=|/AttachHis/)([^&/?]+\.pdf)", re.I)


def main() -> int:
    mode = "apply" if "--apply" in sys.argv else "rollback" if "--rollback" in sys.argv else "dry"
    ro = mode == "dry"
    live = sqlite3.connect(f"file:{LIVE}?mode=ro" if ro else LIVE, uri=ro, timeout=600)
    cols = {r[1] for r in live.execute("PRAGMA table_info(corporate_documents)")}

    if mode == "rollback":
        with live:
            n = live.execute("UPDATE corporate_documents SET bse_newsid=NULL, bse_dissem_ts=NULL,"
                             " bse_news_dt=NULL, bse_subcat=NULL, bse_joined_at=NULL"
                             " WHERE bse_newsid IS NOT NULL").rowcount
        print(f"rolled back {n:,}")
        return 0

    ann = sqlite3.connect(f"file:{ANN}?mode=ro", uri=True)
    feed = {}
    for nid, att, dis, nd, sub in ann.execute(
            "SELECT NEWSID, lower(ATTACHMENTNAME), DissemDT, NEWS_DT, SUBCATNAME FROM ann"):
        feed[att] = (nid, dis, nd, sub)
    print(f"feed rows: {len(feed):,}")

    have = "bse_newsid" in cols
    q = ("SELECT id, doc_type, source_url FROM corporate_documents WHERE (source_url LIKE '%Pname=%' OR source_url LIKE '%/AttachHis/%')"
         + (" AND bse_newsid IS NULL" if have else ""))
    tot, hit, updates = Counter(), Counter(), []
    stamp = datetime.now().isoformat(timespec="seconds")
    for id_, dtype, url in live.execute(q):
        m = PN.search(url or "")
        if not m:
            continue
        tot[dtype] += 1
        f = feed.get(m.group(1).lower())
        if f:
            hit[dtype] += 1
            updates.append((f[0], f[1], f[2], f[3], stamp, id_))
    for k in sorted(tot):
        print(f"  {k:24s} {hit[k]:>7,} / {tot[k]:>7,}  ({100*hit[k]/tot[k]:.1f}%)")
    print(f"total to join: {len(updates):,}")

    if mode == "dry":
        print("DRY RUN - nothing written. Re-run with --apply.")
        return 0

    with live:
        for c in NEW_COLS:
            if c.split()[0] not in cols:
                live.execute(f"ALTER TABLE corporate_documents ADD COLUMN {c}")
        for i in range(0, len(updates), 5000):
            live.executemany("UPDATE corporate_documents SET bse_newsid=?, bse_dissem_ts=?, bse_news_dt=?,"
                             " bse_subcat=?, bse_joined_at=? WHERE id=? AND bse_newsid IS NULL", updates[i:i + 5000])
    print(f"joined {len(updates):,} rows at {stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
