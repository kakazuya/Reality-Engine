"""Find a company's documents across every store and report their real state.

The five stores disagree about ids, dates and status.  This tool resolves one
symbol/ISIN/doc-type/date window against all of them and prints, per hit: the
filing date with its source column (never ``doc_date``, which is a crawl date),
whether ``local_path`` exists on disk, the indexed chunk count, and the
read/extract status of that store.

Examples:
    python -m reality_engine.toolbelt.find_docs --symbol DEEDEV --doc-type CONCALL_TRANSCRIPT
    python -m reality_engine.toolbelt.find_docs --symbol TITAGARH --since 2026-01-01 --until 2026-10-24

    from reality_engine.toolbelt.find_docs import find
    docs = find(symbol="DEEDEV", doc_type="CONCALL_TRANSCRIPT")["documents"]
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

from ._common import REPO_ROOT, add_format, connect, main_guard, print_result

_ALIASES = {
    "AR": "ANNUAL_REPORT",
    "ANNUAL": "ANNUAL_REPORT",
    "CONCALL": "CONCALL_TRANSCRIPT",
    "TRANSCRIPT": "CONCALL_TRANSCRIPT",
    "DECK": "INVESTOR_PRESENTATION",
    "PRESENTATION": "INVESTOR_PRESENTATION",
}
_CORP_STATUS = {0: "pending", 1: "processed", 2: "flagged"}


def _norm_doc_type(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().upper().replace("-", "_").replace(" ", "_")
    return _ALIASES.get(key, key)


def _date_expr(until: str | None) -> str | None:
    if not until:
        return None
    until = until.strip()
    return until + "T23:59:59" if len(until) == 10 else until


def _path_exists(local_path: str | None) -> bool:
    if not local_path:
        return False
    p = Path(str(local_path).replace("\\", "/"))
    if p.is_absolute():
        return p.exists()
    return (REPO_ROOT / p).exists() or (Path.cwd() / p).exists()


def _chunk_count(con, table: str, column: str, key: Any) -> int | None:
    """Count rows in the store's own piece table; ``None`` when that table is absent."""
    if con is None or not key:
        return None
    try:
        return int(con.execute(
            f"SELECT count(*) FROM {table} WHERE {column}=?", (key,)).fetchone()[0])
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise


def _base_row(store: str, doc_id: Any, symbol: str | None, isin: str | None,
              doc_type: str | None, title: str | None, filing_date: str | None,
              date_source: str | None, local_path: str | None, read_status: str) -> dict[str, Any]:
    return {
        "store": store,
        "id": doc_id,
        "symbol": symbol,
        "isin": isin,
        "doc_type": doc_type,
        "title": (title or "")[:200] or None,
        "filing_date": filing_date or None,
        "date_source": date_source if filing_date else None,
        "undated": not filing_date,
        "local_path": local_path,
        "path_exists": _path_exists(local_path),
        "chunk_count": None,
        "read_status": read_status,
    }


def _corporate(con, symbol, isin, doc_type, since, until, limit) -> list[dict[str, Any]]:
    where, params = [], []
    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())
    if isin:
        where.append("isin = ?")
        params.append(isin.upper())
    if doc_type:
        where.append("doc_type = ?")
        params.append(doc_type)
    date = "COALESCE(bse_dissem_ts, publication_date, call_date)"
    if since:
        where.append(f"{date} >= ?")
        params.append(since)
    if until:
        where.append(f"{date} <= ?")
        params.append(until)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = (f"SELECT id, symbol, isin, doc_type, title, bse_dissem_ts, publication_date, "
           f"call_date, local_file_path, is_processed FROM corporate_documents {clause} "
           f"ORDER BY {date} DESC LIMIT ?")
    out = []
    for row in con.execute(sql, (*params, limit)).fetchall():
        for value, source in ((row[5], "bse_dissem_ts"), (row[6], "publication_date"),
                              (row[7], "call_date")):
            if value:
                filing_date, date_source = value, source
                break
        else:
            filing_date, date_source = None, None
        status = _CORP_STATUS.get(row[9], f"is_processed={row[9]}")
        out.append(_base_row("corporate_documents", row[0], row[1], row[2], row[3], row[4],
                             filing_date, date_source, row[8], status))
    return out


def _raw(con, symbol, isin, doc_type, since, until, limit) -> list[dict[str, Any]]:
    where, params = [], []
    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())
    if isin:
        where.append("isin = ?")
        params.append(isin.upper())
    if doc_type:
        where.append("upper(source_type) = ?")
        params.append(doc_type)
    if since:
        where.append("published_date >= ?")
        params.append(since)
    if until:
        where.append("published_date <= ?")
        params.append(until)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = (f"SELECT doc_id, symbol, isin, source_type, title, published_date, local_file_path "
           f"FROM raw_documents {clause} ORDER BY published_date DESC LIMIT ?")
    out = []
    for row in con.execute(sql, (*params, limit)).fetchall():
        record = _base_row("raw_documents", row[0], row[1], row[2], row[3], row[4],
                           row[5], "published_date" if row[5] else None, row[6],
                           "not_indexed")
        record["chunk_count"] = _chunk_count(con, "document_chunks", "doc_id", row[0])
        record["read_status"] = "indexed" if record["chunk_count"] else "not_indexed"
        out.append(record)
    return out


def _ar(con, symbol, isin, since, until, limit) -> list[dict[str, Any]]:
    where, params = [], []
    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())
    if isin:
        where.append("isin = ?")
        params.append(isin.upper())
    if since:
        where.append("filed_at >= ?")
        params.append(since)
    if until:
        where.append("filed_at <= ?")
        params.append(until)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = (f"SELECT doc_id, symbol, isin, symbol || ' annual report' AS title, filed_at, "
           f"filed_at_source, path, status FROM ar_docs {clause} ORDER BY filed_at DESC LIMIT ?")
    out = []
    for row in con.execute(sql, (*params, limit)).fetchall():
        record = _base_row("ar_docs", row[0], row[1], row[2], "ANNUAL_REPORT", row[3],
                           row[4], (row[5] or "filed_at") if row[4] else None, row[6],
                           row[7] or "unknown")
        record["chunk_count"] = _chunk_count(con, "ar_pieces", "doc_id", row[0])
        out.append(record)
    return out


def _deck(con, symbol, isin, since, until, limit) -> list[dict[str, Any]]:
    where, params = [], []
    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())
    if isin:
        where.append("isin = ?")
        params.append(isin.upper())
    if since:
        where.append("known_at >= ?")
        params.append(since)
    if until:
        where.append("known_at <= ?")
        params.append(until)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = (f"SELECT source_id, symbol, isin, title, known_at, local_path, status, sha256 "
           f"FROM deck_sources {clause} ORDER BY known_at DESC LIMIT ?")
    out = []
    for row in con.execute(sql, (*params, limit)).fetchall():
        record = _base_row("deck_sources", row[0], row[1], row[2],
                           "INVESTOR_PRESENTATION", row[3], row[4],
                           "known_at" if row[4] else None, row[5], row[6] or "unknown")
        record["chunk_count"] = _chunk_count(con, "pages", "sha256", row[7])
        out.append(record)
    return out


def _cc(con, symbol, isin, since, until, limit) -> list[dict[str, Any]]:
    where, params = [], []
    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())
    if isin:
        where.append("isin = ?")
        params.append(isin.upper())
    if since:
        where.append("filed_at >= ?")
        params.append(since)
    if until:
        where.append("filed_at <= ?")
        params.append(until)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = (f"SELECT doc_id, symbol, isin, symbol || ' concall transcript' AS title, filed_at, "
           f"date_source, status FROM cc_docs {clause} ORDER BY filed_at DESC LIMIT ?")
    out = []
    for row in con.execute(sql, (*params, limit)).fetchall():
        record = _base_row("cc_docs", row[0], row[1], row[2], "CONCALL_TRANSCRIPT", row[3],
                           row[4], (row[5] or "filed_at") if row[4] else None, None,
                           row[6] or "unknown")
        record["chunk_count"] = _chunk_count(con, "cc_items", "doc_id", row[0])
        out.append(record)
    return out


def find(symbol: str | None = None, isin: str | None = None, doc_type: str | None = None,
         since: str | None = None, until: str | None = None, limit: int = 50,
         timeout_s: float = 60.0) -> dict[str, Any]:
    """Query all five document stores; returns rows sorted by filing date, newest first."""
    if not any((symbol, isin, doc_type, since, until)):
        raise ValueError("give at least one of --symbol, --isin, --doc-type, --since, --until")
    doc_type = _norm_doc_type(doc_type)
    until_full = _date_expr(until)
    equity = connect("equity_intelligence", timeout_s)
    try:
        documents: list[dict[str, Any]] = []
        # corporate_documents/raw_documents hold every type; the satellites are typed.
        documents += _corporate(equity, symbol, isin, doc_type, since, until_full, limit)
        documents += _raw(equity, symbol, isin, doc_type, since, until_full, limit)
        if doc_type in (None, "ANNUAL_REPORT"):
            ar = connect("ar_facts", timeout_s)
            try:
                documents += _ar(ar, symbol, isin, since, until_full, limit)
            finally:
                ar.close()
        if doc_type in (None, "INVESTOR_PRESENTATION"):
            deck = connect("deck_figures", timeout_s)
            try:
                documents += _deck(deck, symbol, isin, since, until_full, limit)
            finally:
                deck.close()
        if doc_type in (None, "CONCALL_TRANSCRIPT"):
            cc = connect("concall_facts", timeout_s)
            try:
                documents += _cc(cc, symbol, isin, since, until_full, limit)
            finally:
                cc.close()
        documents.sort(key=lambda r: r["filing_date"] or "", reverse=True)
        documents = documents[:limit]
        counts: dict[str, int] = {}
        for row in documents:
            counts[row["store"]] = counts.get(row["store"], 0) + 1
        return {
            "filters": {"symbol": symbol, "isin": isin, "doc_type": doc_type,
                        "since": since, "until": until},
            "count": len(documents),
            "by_store": counts,
            "documents": documents,
        }
    finally:
        equity.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m reality_engine.toolbelt.find_docs",
        description="Resolve documents across corporate_documents, raw_documents, ar_docs, "
                    "deck_sources and cc_docs.")
    ap.add_argument("--symbol", help="NSE/BSE symbol (e.g. DEEDEV)")
    ap.add_argument("--isin", help="ISIN (e.g. INE050001010)")
    ap.add_argument("--doc-type", help="ANNUAL_REPORT / CONCALL_TRANSCRIPT / INVESTOR_PRESENTATION / ...")
    ap.add_argument("--since", help="filing date lower bound (YYYY-MM-DD)")
    ap.add_argument("--until", help="filing date upper bound (YYYY-MM-DD)")
    ap.add_argument("--limit", type=int, default=50, help="max documents (default: 50)")
    add_format(ap)
    args = ap.parse_args(argv)
    result = find(args.symbol, args.isin, args.doc_type, args.since, args.until, args.limit)
    print_result(result, args.format,
                 columns=["store", "id", "symbol", "doc_type", "filing_date",
                          "date_source", "path_exists", "chunk_count", "read_status"])
    return 0


if __name__ == "__main__":
    main_guard(main)
