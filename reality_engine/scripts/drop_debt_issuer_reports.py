"""Drop annual reports filed under BSE debt-instrument scrips (scrip codes 9xxxxx: NCDs/bonds), keeping rating reports
(Shivam, 2026-10-16: "if any of them contains ratings report then only keep those, rest can be dropped").

These are issuers' annual reports (mostly unlisted NBFCs and state corporations) filed under bond symbols such as
9TCAP28; they are not equities. A report is kept when its first 3 pages read as a credit-rating document (rating
rationale / rating letter / rating action). Reversible:
  - facts move to ar_facts.db table ar_facts_dropped (+ dropped_reason, dropped_ts); none are deleted outright;
  - ar_docs.status -> 'dropped_debt';
  - corporate_documents.doc_type -> 'ANNUAL_REPORT_DEBT_ISSUER', so the AR workers' inventory never reads them again.
Input: RAW_ROOT/ar_queue/wrong_company_scan_all.csv (bse_code column from ar_wrong_company_scan.py).

    python -m reality_engine.scripts.drop_debt_issuer_reports            # dry run
    python -m reality_engine.scripts.drop_debt_issuer_reports --apply
"""
import argparse
import csv
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from reality_engine.config import raw_dir

import pymupdf

DATA = Path(__file__).resolve().parents[1] / "data"
RATING = re.compile(r"rating rationale|rationale for the rating|press release.{0,80}rating|has (assigned|reaffirmed|"
                    r"upgraded|downgraded)|rating action|rating letter|ratings? (assigned|reaffirmed)", re.I)


def is_rating_doc(path):
    try:
        d = pymupdf.open(path)
        return bool(RATING.search(" ".join(d[i].get_text() for i in range(min(3, len(d))))))
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(open(raw_dir("ar_queue") / "wrong_company_scan_all.csv", encoding="utf-8"))
            if (r["bse_code"] or "").startswith("9")]
    keep = [r for r in rows if is_rating_doc(r["path"])]
    drop = [r for r in rows if r not in keep]
    print(f"{len(rows)} reports under debt scrips: keep {len(keep)} rating reports, drop {len(drop)}")
    if not a.apply:
        print("dry run: nothing changed (use --apply)"); return
    ar = sqlite3.connect(DATA / "ar_facts.db", timeout=300)
    eq = sqlite3.connect(DATA / "equity_intelligence.db", timeout=300)
    ar.execute("CREATE TABLE IF NOT EXISTS ar_facts_dropped AS SELECT *, '' AS dropped_reason, '' AS dropped_ts FROM ar_facts WHERE 0")
    ts, moved = datetime.now().isoformat(timespec="seconds"), 0
    for r in drop:
        d = int(r["doc_id"])
        ar.execute("INSERT INTO ar_facts_dropped SELECT *, ?, ? FROM ar_facts WHERE doc_id=?",
                   (f"debt-instrument scrip {r['bse_code']} ({r['symbol']}), not a rating report", ts, d))
        moved += ar.execute("DELETE FROM ar_facts WHERE doc_id=?", (d,)).rowcount
        ar.execute("UPDATE ar_docs SET status='dropped_debt', ts=? WHERE doc_id=?", (ts, d))
        ar.commit()
        eq.execute("UPDATE corporate_documents SET doc_type='ANNUAL_REPORT_DEBT_ISSUER' WHERE id=? AND doc_type='ANNUAL_REPORT'", (d,))
        eq.commit()
    print(f"dropped {len(drop)} reports, {moved:,} facts moved to ar_facts_dropped")


if __name__ == "__main__":
    main()
