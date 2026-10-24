"""Backfill ``raw_documents.symbol`` / ``.isin`` (+ ``.symbol_source``).

Annual-report ``title`` is literally 'ANNUAL_REPORT', so a document's company
was only recoverable from ``local_file_path`` (``...\\pdfs\\<SYMBOL>\\...``),
``document_chunks.isin`` / ``.symbol`` or ``corporate_documents``.  This script
copies that identity onto the document row, in strict precedence order:

1. ``corporate_documents`` matched on ``local_file_path`` or ``source_url``
2. the most common non-empty ``document_chunks.isin`` / ``.symbol`` per doc_id
3. the ``pdfs\\<SYMBOL>\\`` path segment

The method that supplied the row's symbol is recorded in ``symbol_source``.
Existing non-empty values are never overwritten.  ``--dry-run`` reads the DB
read-only and prints the same coverage report without writing.

Usage:
    python -m reality_engine.scripts.backfill_raw_document_symbols --dry-run
    python -m reality_engine.scripts.backfill_raw_document_symbols
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from reality_engine import config as cfg

METHOD_CORP = "corporate_documents"
METHOD_CHUNKS = "document_chunks"
METHOD_PATH = "local_file_path"
PDFS_SEGMENT = re.compile(r"[\\/]pdfs[\\/]([^\\/]+)[\\/]", re.IGNORECASE)
# Macro/news documents are not companies: their chunks carry no useful symbol,
# and scanning 500-chunk macro PDFs for a blank identity is the expensive path.
COMPANY_SOURCE_TYPES = frozenset({
    "ANNUAL_REPORT", "CONCALL_TRANSCRIPT", "INVESTOR_PRESENTATION",
    "OFFER_DOCUMENT", "ANNOUNCEMENT", "Earnings_Concall",
})


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def ensure_columns(conn: sqlite3.Connection) -> None:
    """Additive ALTER TABLE for an existing live DB (idempotent)."""
    cols = _columns(conn, "raw_documents")
    for col in ("symbol", "isin", "symbol_source"):
        if col not in cols:
            conn.execute(f"ALTER TABLE raw_documents ADD COLUMN {col} TEXT")


def coverage(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cols = _columns(conn, "raw_documents")
    has_symbol = "symbol" in cols
    has_isin = "isin" in cols
    has_source = "symbol_source" in cols
    rows = conn.execute(
        "SELECT source_type, COUNT(*) FROM raw_documents GROUP BY source_type ORDER BY COUNT(*) DESC"
    ).fetchall()
    if not (has_symbol or has_isin):
        return [{"source_type": row[0], "total": row[1], "with_symbol": 0,
                 "with_isin": 0, "with_source": 0} for row in rows]
    symbol_expr = ("SUM(COALESCE(NULLIF(symbol, ''), '') <> '')"
                   if has_symbol else "0")
    isin_expr = ("SUM(COALESCE(NULLIF(isin, ''), '') <> '')" if has_isin else "0")
    source_expr = ("SUM(COALESCE(symbol_source, '') <> '')" if has_source else "0")
    rows = conn.execute(
        f"SELECT source_type, COUNT(*), {symbol_expr}, {isin_expr}, {source_expr} "
        "FROM raw_documents GROUP BY source_type ORDER BY COUNT(*) DESC"
    ).fetchall()
    return [
        {"source_type": row[0], "total": row[1], "with_symbol": row[2],
         "with_isin": row[3], "with_source": row[4]}
        for row in rows
    ]


def _corp_maps(conn: sqlite3.Connection) -> Tuple[dict, dict]:
    path_map: dict[str, Tuple[Optional[str], Optional[str]]] = {}
    url_map: dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for local, url, symbol, isin in conn.execute(
        "SELECT local_file_path, source_url, symbol, isin FROM corporate_documents "
        "WHERE COALESCE(local_file_path, '') <> '' OR COALESCE(source_url, '') <> ''"
    ):
        symbol = (symbol or "").strip() or None
        isin = (isin or "").strip() or None
        if not symbol and not isin:
            continue
        if local:
            path_map.setdefault(str(local), (symbol, isin))
        if url:
            url_map.setdefault(str(url), (symbol, isin))
    return path_map, url_map


def _missing_docs(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cols = _columns(conn, "raw_documents")
    symbol_col = "symbol" if "symbol" in cols else "NULL AS symbol"
    isin_col = "isin" if "isin" in cols else "NULL AS isin"
    rows = conn.execute(
        f"SELECT doc_id, source_type, local_file_path, source_url, {symbol_col}, {isin_col} "
        "FROM raw_documents"
    ).fetchall()
    out = []
    for doc_id, source_type, local, url, symbol, isin in rows:
        if (symbol or "").strip() and (isin or "").strip():
            continue
        out.append({"doc_id": int(doc_id), "source_type": source_type,
                    "local_file_path": local, "source_url": url,
                    "symbol": (symbol or "").strip() or None,
                    "isin": (isin or "").strip() or None})
    return out


def _wanted(doc: Dict[str, Any],
            symbol: Optional[str], isin: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Only return values that fill a currently-empty column."""
    return (symbol if symbol and not doc.get("symbol") else None,
            isin if isin and not doc.get("isin") else None)


def _bulk_write(conn: sqlite3.Connection, docs: Sequence[Dict[str, Any]],
                dry_run: bool) -> int:
    """One UPDATE ... FROM for all filled docs (fast on the 53 GB WAL DB)."""
    updates = [doc for doc in docs if doc.get("_source")]
    if dry_run or not updates:
        return len(updates)
    conn.execute(
        "CREATE TEMP TABLE _doc_identity "
        "(doc_id INTEGER PRIMARY KEY, symbol TEXT, isin TEXT, source TEXT)")
    conn.executemany(
        "INSERT OR REPLACE INTO _doc_identity VALUES (?, ?, ?, ?)",
        [(doc["doc_id"], doc.get("symbol"), doc.get("isin"), doc["_source"])
         for doc in updates])
    conn.execute(
        """
        UPDATE raw_documents AS r
        SET symbol = COALESCE(NULLIF(r.symbol, ''), d.symbol),
            isin = COALESCE(NULLIF(r.isin, ''), d.isin),
            symbol_source = CASE
                WHEN COALESCE(r.symbol, '') = '' AND COALESCE(d.symbol, '') <> '' THEN d.source
                WHEN COALESCE(r.symbol, '') = '' AND COALESCE(d.isin, '') <> '' THEN d.source
                ELSE r.symbol_source END
        FROM _doc_identity AS d
        WHERE r.doc_id = d.doc_id
        """
    )
    conn.execute("DROP TABLE _doc_identity")
    return len(updates)


def _mark(doc: Dict[str, Any], symbol: Optional[str], isin: Optional[str],
          source: str) -> bool:
    """Fill empty columns in memory and remember which method supplied them."""
    changed = False
    if symbol and not doc.get("symbol"):
        doc["symbol"] = symbol
        doc["_source"] = source
        changed = True
    if isin and not doc.get("isin"):
        doc["isin"] = isin
        doc.setdefault("_source", source)
        changed = True
    return changed


def _pass_corporate(conn, docs):
    path_map, url_map = _corp_maps(conn)
    filled = 0
    for doc in docs:
        hit = (path_map.get(doc.get("local_file_path") or "")
               or url_map.get(doc.get("source_url") or ""))
        if not hit:
            continue
        symbol, isin = _wanted(doc, *hit)
        if _mark(doc, symbol, isin, METHOD_CORP):
            filled += 1
    return filled


def _chunk_winners(conn, doc_ids: Sequence[int]) -> Dict[int, Tuple[Optional[str], Optional[str]]]:
    if not doc_ids:
        return {}
    placeholders = ",".join("?" * len(doc_ids))
    rows = conn.execute(
        "SELECT doc_id, symbol, isin, COUNT(*) FROM document_chunks "
        f"WHERE doc_id IN ({placeholders}) "
        "AND (COALESCE(symbol, '') <> '' OR COALESCE(isin, '') <> '') "
        "GROUP BY doc_id, symbol, isin",
        list(doc_ids),
    ).fetchall()
    symbol_counts: dict[int, Counter] = defaultdict(Counter)
    isin_counts: dict[int, Counter] = defaultdict(Counter)
    for doc_id, symbol, isin, count in rows:
        if (symbol or "").strip():
            symbol_counts[int(doc_id)][symbol.strip()] += int(count)
        if (isin or "").strip():
            isin_counts[int(doc_id)][isin.strip()] += int(count)

    def mode(counter: Counter) -> Optional[str]:
        return counter.most_common(1)[0][0] if counter else None

    return {doc_id: (mode(symbol_counts[doc_id]), mode(isin_counts[doc_id]))
            for doc_id in set(symbol_counts) | set(isin_counts)}


def _pass_chunks(conn, docs, batch=400):
    # Only company document types: macro/news chunks never carry a company
    # symbol, and querying their 500-chunk PDFs is the slow path on 53 GB.
    docs = [doc for doc in docs
            if not (doc.get("symbol") and doc.get("isin"))
            and doc.get("source_type") in COMPANY_SOURCE_TYPES]
    filled = 0
    for start in range(0, len(docs), batch):
        batch_docs = docs[start:start + batch]
        winners = _chunk_winners(conn, [d["doc_id"] for d in batch_docs])
        for doc in batch_docs:
            symbol, isin = _wanted(doc, *winners.get(doc["doc_id"], (None, None)))
            if _mark(doc, symbol, isin, METHOD_CHUNKS):
                filled += 1
        if start and (start // batch) % 10 == 0:
            print(f"  [chunks] {start:,}/{len(docs):,} docs", flush=True)
    return filled


def _pass_path(conn, docs):
    filled = 0
    for doc in docs:
        if doc.get("symbol"):
            continue
        match = PDFS_SEGMENT.search(doc.get("local_file_path") or "")
        if not match:
            continue
        symbol = match.group(1).strip().upper()
        if symbol and _mark(doc, symbol, None, METHOD_PATH):
            filled += 1
    return filled


def backfill(conn: sqlite3.Connection, dry_run: bool = False,
             batch: int = 400) -> Dict[str, Any]:
    """Run the three passes in precedence order; return before/after coverage."""
    before = coverage(conn)
    if not dry_run:
        ensure_columns(conn)
    docs = _missing_docs(conn)
    print(f"  [backfill] {len(docs):,} docs missing symbol/isin", flush=True)
    results = {
        "corporate_documents": _pass_corporate(conn, docs),
        "document_chunks": _pass_chunks(conn, docs, batch=batch),
        "local_file_path": _pass_path(conn, docs),
    }
    print(f"  [backfill] filled in memory: {results}", flush=True)
    _bulk_write(conn, docs, dry_run)
    after = coverage(conn)
    ar_left = sum(row["total"] - row["with_symbol"] for row in after
                  if row["source_type"] == "ANNUAL_REPORT")
    return {"before": before, "after": after, "filled": results,
            "docs_missing_identity": len(docs), "ar_without_symbol": ar_left,
            "dry_run": dry_run}


def report(result: Dict[str, Any]) -> None:
    before = {row["source_type"]: row for row in result["before"]}
    after = {row["source_type"]: row for row in result["after"]}
    print("=" * 88)
    print(f"  RAW_DOCUMENTS SYMBOL BACKFILL{' (DRY RUN - nothing written)' if result['dry_run'] else ''}")
    print("=" * 88)
    print(f"  docs missing symbol/isin before: {result['docs_missing_identity']:,}")
    print(f"  filled by method: " + "  ".join(
        f"{k}={v:,}" for k, v in result["filled"].items()))
    print(f"  annual reports still without a symbol: {result['ar_without_symbol']:,}")
    print("\n  coverage by source_type (symbol before -> after)")
    print(f"  {'source_type':<34}{'total':>9}{'before':>9}{'after':>9}{'delta':>9}")
    for source in sorted(after, key=lambda s: -after[s]["total"]):
        a, b = after[source], before.get(source, {"total": 0, "with_symbol": 0})
        print(f"  {source:<34}{a['total']:>9,}{b['with_symbol']:>9,}"
              f"{a['with_symbol']:>9,}{a['with_symbol'] - b['with_symbol']:>9,}")
    print("=" * 88)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(cfg.DB_PATH), help="SQLite DB path (default: config DB)")
    ap.add_argument("--dry-run", action="store_true", help="read-only; print the report only")
    ap.add_argument("--batch", type=int, default=400, help="document_chunks doc-id batch size")
    args = ap.parse_args()

    path = Path(args.db)
    if args.dry_run:
        from reality_engine.db.readonly import connect_ro

        conn = connect_ro(path, timeout_s=120)
    else:
        conn = sqlite3.connect(str(path), timeout=180, isolation_level=None)
        conn.execute("PRAGMA busy_timeout = 180000")
        conn.execute("BEGIN IMMEDIATE")
    try:
        result = backfill(conn, dry_run=args.dry_run, batch=args.batch)
        if not args.dry_run:
            conn.execute("COMMIT")
    except Exception:
        if not args.dry_run:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
        raise
    finally:
        conn.close()
    report(result)


if __name__ == "__main__":
    main()
