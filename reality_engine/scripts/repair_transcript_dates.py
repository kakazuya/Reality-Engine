"""Repair filing dates in the search layer (2026-10-18; --types widens it beyond concall transcripts).

Some transcripts were chunked with doc_date (the crawl date, mostly 2026) as their published date instead of the real
filing date: 5,725 from the 2026-10-18 --local-only run and 318 older ones. A wrong date is a look-ahead / mis-dating bug
for backtests. Real date = corporate_documents COALESCE(bse_dissem_ts, publication_date, call_date), first 10 chars.

Fixes, per affected raw_documents row: raw_documents.published_date; document_chunks.published_date and the
'[Metadata: ... | Date: X]' header inside content; intelligence_fts document_date + document_text (by rowid);
the vector store's vectors_meta.jsonl (document_date + text). The vectors themselves still embed the old header date
token: re-embed these docs with whichever model the embedding test picks.

    python -m reality_engine.scripts.repair_transcript_dates [--types CONCALL_TRANSCRIPT,ANNUAL_REPORT,...] [--dry-run]
"""
import argparse
import json
import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "reality_engine/data/equity_intelligence.db"
META = ROOT / "reality_engine/data/lancedb/vectors_meta.jsonl"
HDR = re.compile(r"^(\[Metadata:[^\]\n]*?Date: )(\d{4}-\d{2}-\d{2})")


def fix_header(text, new):
    return HDR.sub(lambda m: m.group(1) + new, text or "", count=1)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--types", default="CONCALL_TRANSCRIPT", help="raw_documents.source_type list, comma-separated")
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=600)
    types = [t.strip() for t in a.types.split(",") if t.strip()]
    bad = {}
    for doc_id, real in db.execute(
            f"""SELECT r.doc_id, substr(COALESCE(cd.bse_dissem_ts, cd.publication_date, cd.call_date), 1, 10)
                FROM raw_documents r JOIN corporate_documents cd
                  ON cd.source_url = r.source_url AND cd.doc_type = r.source_type
                WHERE r.source_type IN ({','.join('?' * len(types))})
                  AND COALESCE(cd.bse_dissem_ts, cd.publication_date, cd.call_date) IS NOT NULL
                  AND substr(r.published_date, 1, 10) <>
                      substr(COALESCE(cd.bse_dissem_ts, cd.publication_date, cd.call_date), 1, 10)""", types):
        bad[doc_id] = min(real, bad.get(doc_id, real))   # two filings of one PDF: the earlier public date
    print(f"documents with a wrong date: {len(bad)}")
    if a.dry_run or not bad:
        return
    # streamed in batches of documents: the first version held every chunk's text at once and pushed RAM to 0.5 GB
    # free on 1.4M annual-report/deck chunks (2026-10-18)
    date_of_chunk = {}
    ids = list(bad)
    for i in range(0, len(ids), 200):
        part = ids[i:i + 200]
        rows = db.execute(f"select chunk_id, doc_id, content from document_chunks where doc_id in ({','.join('?' * len(part))})",
                          part).fetchall()
        with db:
            db.executemany("update document_chunks set published_date=?, content=? where chunk_id=?",
                           [(bad[did], fix_header(c, bad[did]), cid) for cid, did, c in rows])
        for cid, did, _ in rows:
            date_of_chunk[str(cid)] = bad[did]
    with db:
        db.executemany("update raw_documents set published_date=? where doc_id=?", [(d, k) for k, d in bad.items()])
    print(f"chunks fixed: {len(date_of_chunk)}")
    todo = [(rid, date_of_chunk[str(cid)]) for rid, cid in db.execute(
        f"select rowid, chunk_id from intelligence_fts where source_type in ({','.join('?' * len(types))})", types)
        if str(cid) in date_of_chunk]
    for i in range(0, len(todo), 2000):
        part = dict(todo[i:i + 2000])
        rows = db.execute(f"select rowid, document_text from intelligence_fts where rowid in ({','.join('?' * len(part))})",
                          list(part)).fetchall()
        with db:
            db.executemany("update intelligence_fts set document_date=?, document_text=? where rowid=?",
                           [(part[r], fix_header(t, part[r]), r) for r, t in rows])
    print(f"fts rows fixed: {len(todo)}")
    new_date_of_chunk = {k: (d, None) for k, d in date_of_chunk.items()}
    if META.exists():
        tmp = META.with_suffix(".jsonl.tmp"); n = 0
        with META.open(encoding="utf-8") as src, tmp.open("w", encoding="utf-8") as dst:
            for line in src:
                m = json.loads(line); hit = new_date_of_chunk.get(str(m.get("id")))
                if hit:
                    m["document_date"] = hit[0]; m["text"] = fix_header(m.get("text"), hit[0]); n += 1
                    line = json.dumps(m, separators=(",", ":")) + "\n"
                dst.write(line)
        os.replace(tmp, META)
        print(f"vector-store metadata rows fixed: {n}")
    (ROOT / "reality_engine/data/embed_test").mkdir(parents=True, exist_ok=True)
    out = ROOT / "reality_engine/data/embed_test/redated_doc_ids.json"
    prev = json.loads(out.read_text()) if out.exists() else []
    out.write_text(json.dumps(sorted(set(prev) | set(bad))), encoding="utf-8")


if __name__ == "__main__":
    main()
