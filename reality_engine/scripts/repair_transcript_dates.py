"""Repair concall-transcript dates in the search layer (2026-10-18).

Some transcripts were chunked with doc_date (the crawl date, mostly 2026) as their published date instead of the real
filing date: 5,725 from the 2026-10-18 --local-only run and 318 older ones. A wrong date is a look-ahead / mis-dating bug
for backtests. Real date = corporate_documents COALESCE(bse_dissem_ts, publication_date, call_date), first 10 chars.

Fixes, per affected raw_documents row: raw_documents.published_date; document_chunks.published_date and the
'[Metadata: ... | Date: X]' header inside content; intelligence_fts document_date + document_text (by rowid);
the vector store's vectors_meta.jsonl (document_date + text). The vectors themselves still embed the old header date
token: re-embed these docs with whichever model the embedding test picks.

    python -m reality_engine.scripts.repair_transcript_dates [--dry-run]
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
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=600)
    real = {os.path.normcase(p): (d or "")[:10] for p, d in db.execute(
        "select local_file_path, coalesce(bse_dissem_ts, publication_date, call_date) from corporate_documents "
        "where doc_type='CONCALL_TRANSCRIPT' and local_file_path<>''")}
    bad = {}
    for doc_id, p, pub in db.execute("select doc_id, local_file_path, published_date from raw_documents "
                                     "where source_type='CONCALL_TRANSCRIPT'"):
        r = real.get(os.path.normcase(p or ""))
        if r and (pub or "")[:10] != r:
            bad[doc_id] = r
    print(f"documents with a wrong date: {len(bad)}")
    if a.dry_run or not bad:
        return
    new_date_of_chunk = {}
    ids = list(bad)
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for cid, did, content in db.execute(
                f"select chunk_id, doc_id, content from document_chunks where doc_id in ({','.join('?' * len(part))})", part):
            new_date_of_chunk[str(cid)] = (bad[did], fix_header(content, bad[did]))
    with db:
        db.executemany("update raw_documents set published_date=? where doc_id=?", [(d, k) for k, d in bad.items()])
        db.executemany("update document_chunks set published_date=?, content=? where chunk_id=?",
                       [(d, c, int(cid)) for cid, (d, c) in new_date_of_chunk.items()])
    print(f"chunks fixed: {len(new_date_of_chunk)}")
    rows = [(rid, str(cid)) for rid, cid in db.execute(
        "select rowid, chunk_id from intelligence_fts where source_type='CONCALL_TRANSCRIPT'")]
    upd = [(new_date_of_chunk[c][0], new_date_of_chunk[c][1], rid) for rid, c in rows if c in new_date_of_chunk]
    with db:
        db.executemany("update intelligence_fts set document_date=?, document_text=? where rowid=?", upd)
    print(f"fts rows fixed: {len(upd)}")
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
    (ROOT / "reality_engine/data/embed_test/redated_doc_ids.json").write_text(json.dumps(sorted(bad)), encoding="utf-8")


if __name__ == "__main__":
    main()
