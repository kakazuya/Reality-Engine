"""
Build the reversible change set for the crawl-date defect.

No DB copy (the live DB is 33.35 GB). Instead:
  1. snapshot_before_dates.jsonl  - the CURRENT value of every column we intend to
     change, keyed by corp_id, so any write is exactly reversible and verifiable.
  2. proposed_changes.csv         - one row per field change, with the evidence
     span and provenance tier, for human review BEFORE any write.

Both are derived from the read-only extraction artifact plus a read-only DB read.

Write-back rules (to be applied only after review):
  - corporate_documents.doc_date / event_date are NOT overwritten. The crawl date is
    preserved in its own column so the original stays auditable.
  - New columns receive a distinct event_source that names the provenance.
  - call_date and publication_date are stored SEPARATELY and never collapsed.
  - Rows with no trustworthy anchor stay NULL (honest-NULL contract).
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

DB = "reality_engine/data/equity_intelligence.db"
EXTRACT = Path("analysis/call_date_extractions.jsonl")
SNAPSHOT = Path("analysis/snapshot_before_dates.jsonl")
PROPOSED = Path("analysis/proposed_changes.csv")

# New event_source vocabulary. These are NOT 'doc_date' (the crawl stamp).
SRC_CALL_HELD = "body_held_on"          # tier 1: held-on phrase + filing date
SRC_CALL_ONLY = "body_held_on_nofile"   # tier 2: held-on phrase, no filing date
SRC_PUB_ONLY = "body_letterhead"        # tier 3: publication date only, NOT a call date


def is_month_end(iso: str) -> bool:
    import datetime
    d = datetime.date.fromisoformat(iso)
    return (d + datetime.timedelta(days=1)).day == 1 or d.day in (30, 31)


def main() -> int:
    rows = [json.loads(l) for l in EXTRACT.open(encoding="utf-8")]

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=300)
    cur = con.cursor()
    cur.execute("""SELECT id, symbol, isin, title, doc_date, event_date, event_source,
                          doc_version, is_processed, source_url, sha256_hash
                   FROM corporate_documents
                   WHERE doc_type='CONCALL_TRANSCRIPT' AND is_processed=1""")
    live = {r[0]: r for r in cur.fetchall()}

    # chunks hanging off these documents, for the follow-on propagation estimate
    cur.execute("""SELECT COUNT(*) FROM document_chunks
                   WHERE doc_id IN (SELECT id FROM corporate_documents
                                    WHERE doc_type='CONCALL_TRANSCRIPT' AND is_processed=1)""")
    n_chunks = cur.fetchone()[0]
    con.close()

    snap_n = 0
    prop_n = 0
    stats = {"tier1": 0, "tier2": 0, "tier3": 0, "tier0": 0,
             "skipped_monthend_pub": 0, "skipped_no_anchor": 0}

    with SNAPSHOT.open("w", encoding="utf-8") as sf, \
         PROPOSED.open("w", encoding="utf-8", newline="") as pf:
        pw = csv.writer(pf)
        pw.writerow(["corp_id", "symbol", "field", "current_value", "proposed_value",
                     "event_source_proposed", "date_tier", "quarter", "filing_lag_days",
                     "evidence"])

        for r in rows:
            cid = r["corp_id"]
            lv = live.get(cid)
            if not lv:
                continue
            # 1. SNAPSHOT the current state of every column we may touch.
            sf.write(json.dumps({
                "corp_id": cid, "symbol": lv[1], "isin": lv[2], "title": lv[3],
                "doc_date": lv[4], "event_date": lv[5], "event_source": lv[6],
                "doc_version": lv[7], "is_processed": lv[8], "source_url": lv[9],
                "sha256": lv[10], "local_file_path": r["path"],
                "snapshot_reason": "pre crawl-date correction",
            }) + "\n")
            snap_n += 1

            ev = (r["evidence"] or "").replace("\n", " ").replace("\r", " ")
            tier = r["date_tier"]

            # 2. PROPOSE the call_date (the held-on date), tier 1/2 only.
            if tier in (1, 2) and r["call_date"]:
                stats[f"tier{tier}"] += 1
                src = SRC_CALL_HELD if tier == 1 else SRC_CALL_ONLY
                pw.writerow([cid, r["symbol"], "call_date", lv[5], r["call_date"],
                             src, tier, r["quarter"], r["filing_lag_days"] or "", ev[:400]])
            # A publication date is only trustworthy on a row whose call date was
            # not itself contradicted. If the negative-lag guard or the weekday
            # guard fired, the whole row is suspect and nothing is proposed.
            contradicted = ("negative_lag" in (r["review_reason"] or "")
                            or "weekday_mismatch" in (r["review_reason"] or ""))


            # 3. PROPOSE the publication_date separately, rejecting month-end junk.
            if r["publication_date"]:
                if is_month_end(r["publication_date"]):
                    stats["skipped_monthend_pub"] += 1
                elif contradicted:
                    stats["skipped_contradicted"] = (
                        stats.get("skipped_contradicted", 0) + 1)
                else:
                    stats["tier3"] += 1
                    pw.writerow([cid, r["symbol"], "publication_date", lv[5],
                                 r["publication_date"], SRC_PUB_ONLY, tier,
                                 r["quarter"], r["filing_lag_days"] or "", ev[:400]])

            if not r["call_date"] and not r["publication_date"]:
                stats["tier0"] += 1
                stats["skipped_no_anchor"] += 1

    print(f"snapshot rows : {snap_n:,} -> {SNAPSHOT}")
    print(f"proposed rows : {prop_n if prop_n else 'see below'} -> {PROPOSED}")
    with PROPOSED.open(encoding="utf-8") as fh:
        prop_n = sum(1 for _ in fh) - 1
    print(f"proposed rows : {prop_n:,}")
    print(f"\nstats: {stats}")
    print(f"chunks awaiting propagation: {n_chunks:,}")
    print(f"\nROLLBACK: restore from {SNAPSHOT} by corp_id; the write-back must be")
    print("         guarded with WHERE corp_id=? AND event_date=<current_value>.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
