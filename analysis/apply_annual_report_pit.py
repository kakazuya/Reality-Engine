"""
Annual-report PIT labels from the BSE filename (additive, idempotent). No network.

BSE 'bseplus/AnnualReport' filenames come in three shapes:
  A) <scrip><MMYY>.pdf            -> fiscal_period_end (period covered). NOT a publication date.
  B) <id><scrip>_DD_MM_YY.pdf     -> publication_date (upload date; tier 2, inferred - spot-checked
                                     against PDF text, typically 0-1 day after the AGM/notice date).
  C) <id><scrip>.pdf              -> nothing derivable; stays unknown (honest NULL).
Rows already carrying bse_dissem_ts or publication_date are not touched.

  python analysis/apply_annual_report_pit.py            # dry run
  python analysis/apply_annual_report_pit.py --apply
  python analysis/apply_annual_report_pit.py --rollback
"""
from __future__ import annotations

import calendar
import re
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime

DB = "reality_engine/data/equity_intelligence.db"
SHAPE_B = re.compile(r"/AnnualReport/(\d+)/(\d+)_(\d\d)_(\d\d)_(\d\d)\.pdf$", re.I)
SHAPE_A = re.compile(r"/AnnualReport/(\d+)/(\d+)\.pdf$", re.I)


def parse(url: str):
    m = SHAPE_B.search(url)
    if m:
        scrip, stem, dd, mm, yy = m.groups()
        if stem.endswith(scrip):
            try:
                return "pub", date(2000 + int(yy), int(mm), int(dd)).isoformat()
            except ValueError:
                return None
    m = SHAPE_A.search(url)
    if m:
        scrip, stem = m.groups()
        if stem.startswith(scrip) and len(stem) == len(scrip) + 4:
            mm, yy = int(stem[-4:-2]), int(stem[-2:])
            if 1 <= mm <= 12 and 0 <= yy <= 26:
                y = 2000 + yy
                return "fpe", date(y, mm, calendar.monthrange(y, mm)[1]).isoformat()
    return None


def main() -> int:
    mode = "apply" if "--apply" in sys.argv else "rollback" if "--rollback" in sys.argv else "dry"
    ro = mode == "dry"
    con = sqlite3.connect(f"file:{DB}?mode=ro" if ro else DB, uri=ro, timeout=600)
    cols = {r[1] for r in con.execute("PRAGMA table_info(corporate_documents)")}

    if mode == "rollback":
        with con:
            a = con.execute("UPDATE corporate_documents SET fiscal_period_end=NULL WHERE doc_type='ANNUAL_REPORT'").rowcount
            b = con.execute("UPDATE corporate_documents SET publication_date=NULL, pit_source=NULL, pit_tier=NULL,"
                            " pit_applied_at=NULL WHERE pit_source='bse_ar_filename_dmy'").rowcount
        print(f"rolled back fiscal_period_end={a:,} publication_date={b:,}")
        return 0

    have_pub = "publication_date" in cols and "bse_dissem_ts" in cols
    q = ("SELECT id, source_url FROM corporate_documents WHERE doc_type='ANNUAL_REPORT' "
         "AND source_url LIKE '%/bseplus/AnnualReport/%'")
    if have_pub:
        q += " AND bse_dissem_ts IS NULL AND publication_date IS NULL"
    pubs, fpes, c = [], [], Counter()
    for id_, url in con.execute(q):
        r = parse(url or "")
        if not r:
            c["unparsed"] += 1
        elif r[0] == "pub":
            pubs.append((r[1], id_)); c["pub"] += 1
        else:
            fpes.append((r[1], id_)); c["fpe"] += 1
    print(dict(c))
    if pubs:
        ds = sorted(p[0] for p in pubs)
        print(f"pub date range {ds[0]} .. {ds[-1]}")
    if mode == "dry":
        print("DRY RUN - nothing written.")
        return 0

    stamp = datetime.now().isoformat(timespec="seconds")
    with con:
        if "fiscal_period_end" not in cols:
            con.execute("ALTER TABLE corporate_documents ADD COLUMN fiscal_period_end TEXT")
        con.executemany("UPDATE corporate_documents SET fiscal_period_end=? WHERE id=?", fpes)
        con.executemany("UPDATE corporate_documents SET publication_date=?, pit_source='bse_ar_filename_dmy',"
                        f" pit_tier=2, pit_applied_at='{stamp}' WHERE id=? AND publication_date IS NULL", pubs)
    print(f"applied fiscal_period_end={len(fpes):,} publication_date={len(pubs):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
