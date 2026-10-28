"""Measure the query-layer index migration on COPIES under .tmp/ (never live DBs).

Copies are table-level (same rows/index shape as live; a 54 GB file copy buys
nothing for a B-tree measurement).  ``ar_facts`` is copied for a deterministic
sample of ISINs because it is 32M rows and the measured query is per-ISIN; the
per-company sort cost the index removes is preserved.

    python tasks/answer_bench/measure_indexes.py

Writes .tmp/idx/copies/*.db and .tmp/idx/measure.json, prints a table.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ["REALITY_DATA_ROOT"])
OUT = REPO / ".tmp" / "idx"
COPIES = OUT / "copies"


def copy_table(live: Path, dst: Path, table: str, select_sql: str, params=()) -> None:
    """CREATE TABLE dst.<table> AS <select_sql> with the live DB attached read-only.

    The *source* connection is the ``mode=ro`` one; the destination file is
    attached writable to it, so nothing can write the live database.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{live.as_posix()}?mode=ro", uri=True)
    try:
        con.execute("ATTACH DATABASE ? AS dst", (str(dst),))
        con.execute(f"CREATE TABLE dst.{table} AS {select_sql}", params)
        con.commit()
    finally:
        con.close()


def timed(con: sqlite3.Connection, sql: str, params=(), runs: int = 3) -> dict:
    times = []
    rows = 0
    for _ in range(runs):
        started = time.perf_counter()
        rows = len(con.execute(sql, params).fetchall())
        times.append(time.perf_counter() - started)
    plan = [str(tuple(r)) for r in con.execute("EXPLAIN QUERY PLAN " + sql, params)]
    return {"seconds": round(min(times), 4), "rows": rows, "plan": plan}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    COPIES.mkdir(parents=True, exist_ok=True)
    result: dict = {}

    # 1. corporate_documents(isin, publication_date) ----------------------
    path = COPIES / "corp.db"
    if not path.exists():
        copy_table(ROOT / "equity_intelligence.db", path, "corp",
                   "SELECT id, isin, symbol, doc_type, title, publication_date, "
                   "bse_dissem_ts, call_date, doc_date FROM corporate_documents")
    con = sqlite3.connect(path)
    sample = con.execute("SELECT isin FROM corp WHERE isin IS NOT NULL "
                         "GROUP BY isin ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
    q = ("SELECT id, doc_type, publication_date FROM corp WHERE isin=? "
         "AND publication_date IS NOT NULL ORDER BY publication_date DESC LIMIT 20")
    result["corporate_documents"] = {
        "rows": con.execute("SELECT count(*) FROM corp").fetchone()[0],
        "isin": sample, "before": timed(con, q, (sample,)),
        "index": "CREATE INDEX IF NOT EXISTS idx_corpdocs_isin_pub "
                 "ON corporate_documents(isin, publication_date)"}
    con.execute("CREATE INDEX IF NOT EXISTS idx_corpdocs_isin_pub ON corp(isin, publication_date)")
    con.commit()
    result["corporate_documents"]["after"] = timed(con, q, (sample,))
    con.close()

    # 2. ann(symbol, DissemDT) -------------------------------------------
    path = COPIES / "ann.db"
    if not path.exists():
        copy_table(ROOT / "bse_announcements.db", path, "ann",
                   "SELECT NEWSID, SCRIP_CD, symbol, NEWS_DT, DissemDT, NEWSSUB, "
                   "HEADLINE FROM ann")
    con = sqlite3.connect(path)
    sample = con.execute("SELECT symbol FROM ann WHERE symbol IS NOT NULL "
                         "GROUP BY symbol ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
    q = ("SELECT NEWSID, DissemDT FROM ann WHERE symbol=? AND DissemDT<=? "
         "ORDER BY DissemDT DESC LIMIT 20")
    result["ann"] = {
        "rows": con.execute("SELECT count(*) FROM ann").fetchone()[0], "symbol": sample,
        "before": timed(con, q, (sample, "2026-10-19")),
        "index": "CREATE INDEX IF NOT EXISTS idx_ann_sym_dissem ON ann(symbol, DissemDT)"}
    con.execute("CREATE INDEX IF NOT EXISTS idx_ann_sym_dissem ON ann(symbol, DissemDT)")
    con.commit()
    result["ann"]["after"] = timed(con, q, (sample, "2026-10-19"))
    con.close()

    # 3. document_chunks(symbol|isin, published_date) ---------------------
    path = COPIES / "chunks.db"
    if not path.exists():
        copy_table(ROOT / "equity_intelligence.db", path, "chunks",
                   "SELECT chunk_id, doc_id, chunk_index, symbol, isin, published_date, "
                   "content FROM document_chunks")
    con = sqlite3.connect(path)
    sample = con.execute("SELECT symbol FROM chunks WHERE symbol IS NOT NULL AND symbol<>'' "
                         "GROUP BY symbol ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
    q = ("SELECT chunk_id, doc_id, chunk_index, published_date, substr(content,1,200) "
         "FROM chunks WHERE symbol=? AND published_date<=? "
         "ORDER BY published_date DESC LIMIT 400")
    result["document_chunks"] = {
        "rows": con.execute("SELECT count(*) FROM chunks").fetchone()[0], "symbol": sample,
        "before": timed(con, q, (sample, "2026-10-19")),
        "index": "CREATE INDEX IF NOT EXISTS idx_docchunks_symbol_published "
                 "ON document_chunks(symbol, published_date DESC)"}
    con.execute("CREATE INDEX IF NOT EXISTS idx_docchunks_symbol_published "
                "ON chunks(symbol, published_date DESC)")
    con.commit()
    result["document_chunks"]["after"] = timed(con, q, (sample, "2026-10-19"))
    con.close()

    # 4. ar_facts(isin, filed_at) -- 500-ISIN sample, same per-company scale
    path = COPIES / "arfacts.db"
    if not path.exists():
        src = sqlite3.connect(f"file:{(ROOT / 'ar_facts.db').as_posix()}?mode=ro", uri=True)
        isins = [r[0] for r in src.execute(
            "SELECT isin FROM ar_facts WHERE isin IS NOT NULL "
            "GROUP BY isin ORDER BY count(*) DESC LIMIT 500")]
        src.close()
        copy_table(ROOT / "ar_facts.db", path, "facts",
                   "SELECT doc_id, isin, filed_at, page, item, quote FROM ar_facts "
                   "WHERE isin IN (%s)" % ",".join("?" * len(isins)), isins)
    con = sqlite3.connect(path)
    sample = con.execute("SELECT isin FROM facts GROUP BY isin "
                         "ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
    q = ("SELECT doc_id, page, filed_at, item FROM facts WHERE isin=? AND filed_at<=? "
         "AND (lower(item) LIKE ? OR lower(quote) LIKE ?) ORDER BY filed_at DESC LIMIT 40")
    args = (sample, "2026-10-19", "%revenue%", "%revenue%")
    result["ar_facts"] = {
        "rows": con.execute("SELECT count(*) FROM facts").fetchone()[0], "isin": sample,
        "before": timed(con, q, args),
        "index": "CREATE INDEX IF NOT EXISTS ar_facts_isin_filed "
                 "ON ar_facts(isin, filed_at DESC)"}
    con.execute("CREATE INDEX IF NOT EXISTS ar_facts_isin_filed ON facts(isin, filed_at DESC)")
    con.commit()
    result["ar_facts"]["after"] = timed(con, q, args)
    con.close()

    # 5. small tables: ar_docs(symbol), policy_events(policy_name) --------
    path = COPIES / "small.db"
    if not path.exists():
        copy_table(ROOT / "ar_facts.db", path, "ar_docs",
                   "SELECT doc_id, symbol, isin, filed_at FROM ar_docs")
        copy_table(ROOT / "equity_intelligence.db", path, "policy_events",
                   "SELECT id, policy_name, published_at FROM policy_events")
    con = sqlite3.connect(path)
    sample_symbol = con.execute("SELECT symbol FROM ar_docs WHERE symbol IS NOT NULL LIMIT 1").fetchone()[0]
    sample_policy = con.execute("SELECT policy_name FROM policy_events WHERE policy_name IS NOT NULL LIMIT 1").fetchone()[0]
    q1 = "SELECT doc_id FROM ar_docs WHERE symbol=? LIMIT 20"
    q2 = "SELECT id FROM policy_events WHERE policy_name=? LIMIT 20"
    result["small"] = {
        "ar_docs_before": timed(con, q1, (sample_symbol,)),
        "policy_before": timed(con, q2, (sample_policy,))}
    con.execute("CREATE INDEX IF NOT EXISTS ar_docs_symbol ON ar_docs(symbol)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_policy_name ON policy_events(policy_name)")
    con.commit()
    result["small"]["ar_docs_after"] = timed(con, q1, (sample_symbol,))
    result["small"]["policy_after"] = timed(con, q2, (sample_policy,))
    con.close()

    (OUT / "measure.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    for name in ("corporate_documents", "ann", "document_chunks", "ar_facts"):
        item = result[name]
        print(f"{name:22s} rows={item['rows']:>9,} "
              f"before={item['before']['seconds']:.4f}s -> after={item['after']['seconds']:.4f}s")
    print("small:", {k: v["seconds"] for k, v in result["small"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
