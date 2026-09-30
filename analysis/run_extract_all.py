"""
Run the call-date extractor over every processed concall and emit a reviewable
JSONL artifact. READ-ONLY: opens SQLite with mode=ro and never writes to the DB.

Output: analysis/call_date_extractions.jsonl  (one JSON object per document)
Next:   a human reviews the artifact; only then is any write-back considered.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_call_date import extract  # noqa: E402

DB = "reality_engine/data/equity_intelligence.db"
OUT = Path("analysis/call_date_extractions.jsonl")


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=300)
    cur = con.cursor()
    cur.execute("""SELECT id, symbol, isin, sha256_hash, doc_date, event_date, title,
                          local_file_path
                   FROM corporate_documents
                   WHERE doc_type='CONCALL_TRANSCRIPT' AND is_processed=1
                   ORDER BY id""")
    rows = cur.fetchall()
    con.close()
    print(f"processed concall docs: {len(rows)}", file=sys.stderr)

    t0 = time.time()
    tiers: Counter[str] = Counter()
    stats: Counter[str] = Counter()
    lags: Counter[int] = Counter()
    written = 0

    with open(OUT, "w", encoding="utf-8") as fh:
        for n, (cid, sym, isin, sha, db_doc_date, db_event_date, title, path) in enumerate(rows, 1):
            if not path:
                stats["no_local_path"] += 1
                continue
            try:
                r = extract(path, sym)
            except Exception as exc:  # noqa: BLE001
                stats[f"extract_error:{type(exc).__name__}"] += 1
                continue

            rec = asdict(r)
            rec.update({
                "corp_id": cid, "symbol": sym, "isin": isin, "sha256": sha,
                "db_doc_date": db_doc_date, "db_event_date": db_event_date,
                "db_title": title,
                # The stamping verdict, kept separate from parse quality.
                "db_date_matches_call": (r.call_date == db_event_date) if r.call_date else None,
                "db_date_matches_publication": (r.publication_date == db_event_date)
                                             if r.publication_date else None,
            })
            fh.write(json.dumps(rec) + "\n")
            written += 1

            tiers[r.date_tier] += 1
            stats[r.status] += 1
            if r.needs_review:
                stats["needs_review"] += 1
            if r.filing_lag_days is not None:
                lags[r.filing_lag_days] += 1
            if n % 1000 == 0:
                el = time.time() - t0
                print(f"  {n}/{len(rows)}  {el:.0f}s  "
                      f"({n/max(el,1):.1f} doc/s)", file=sys.stderr)

    el = time.time() - t0
    print(f"\ndone: {written} rows -> {OUT}  ({el:.0f}s, {written/max(el,1):.1f} doc/s)")
    print("\ndate_tier (1=held_on+filing 2=held_on only 3=publication proxy 0=none):")
    for k in sorted(tiers):
        print(f"  tier {k}: {tiers[k]:>6,}  ({tiers[k]/max(written,1):.1%})")
    print("\nstatus:")
    for k, v in stats.most_common():
        print(f"  {k:<28}{v:>7,}")
    print(f"\nfiling lag (publication - call) days: {dict(sorted(lags.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
