"""T-132: build the v2 table store from a pilot3 store's decks and results PDFs.

    python -m reality_engine.v2.build_cells --store <pilot3.db> --out <dir> \
        [--since 2025-04-01] [--types deck,results] [--symbols A,B]

Reads ``doc`` rows from the pilot3 store read-only, extracts every printed table cell with
:mod:`reality_engine.v2.table_cells` (text layer only, no model) and writes ``doc``,
``period`` and ``table_cell`` into ``<out>/company/<ISIN>.db`` (ISIN from the store's
``company`` table), created with :mod:`reality_engine.v2.schema`.

A PDF whose sha256 is already in a company's file is skipped: the same deck is often filed
twice.  A page with no text layer is counted, not OCR'd.  A PDF that crashes pymupdf is
logged and skipped; the run stops after ten of them.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Any

from reality_engine.db.readonly import connect_ro
from reality_engine.v2 import schema
from reality_engine.v2.periods import period_row
from reality_engine.v2.table_cells import extract

PARSE_VERSION = "t132-cells-1"
_CRASH_LIMIT = 10


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_isins(conn: Any) -> dict[str, str]:
    """symbol -> current ISIN, preferring a company row with no ``isin_to``."""
    rows = list(conn.execute("SELECT symbol, isin, isin_from, isin_to FROM company"))
    by_symbol: dict[str, list[Any]] = {}
    for row in rows:
        by_symbol.setdefault(row[0], []).append(row)
    current: dict[str, str] = {}
    for symbol, candidates in by_symbol.items():
        live = [row for row in candidates if row[3] is None] or candidates
        best = max(live, key=lambda row: row[2] or "")
        current[symbol] = best[1]
    return current


def _period_of_id(period_id: str) -> dict[str, Any]:
    if period_id.startswith("/"):
        return period_row(None, period_id[1:])
    start, _, end = period_id.partition("/")
    return period_row(start, end)


def _open_company(directory: Path, isin: str) -> sqlite3.Connection:
    path = directory / f"{isin}.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    schema.create(conn)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    return conn


def _write_document(conn: sqlite3.Connection, doc: Any, sha256: str, pages: int,
                    cells: list[dict[str, Any]]) -> None:
    doc_key = str(doc["doc_key"])
    old = conn.execute("SELECT sha256 FROM doc WHERE doc_key=?", (doc_key,)).fetchone()
    if old is not None:
        conn.execute("DELETE FROM table_cell WHERE doc_key=?", (doc_key,))
        conn.execute("DELETE FROM doc WHERE doc_key=?", (doc_key,))
    conn.execute(
        "INSERT INTO doc (doc_key, sha256, doc_type, title, filing_date, known_at, pages, "
        "parse_version, source, source_key) VALUES (?,?,?,?,?,?,?,?,'pilot3',?)",
        (doc_key, sha256, doc["doc_type"], doc["title"], doc["filing_date"], doc["known_at"],
         pages, PARSE_VERSION, doc["source_key"]))
    for period_id in sorted({cell["period_id"] for cell in cells if cell["period_id"]}):
        row = _period_of_id(period_id)
        conn.execute("INSERT OR IGNORE INTO period VALUES (?,?,?,?,?)",
                     (row["period_id"], row["start_date"], row["end_date"], row["kind"],
                      row["fiscal_label"]))
    conn.executemany(
        "INSERT INTO table_cell (doc_key, page, table_no, row_no, col_no, row_label, "
        "col_header, period_id, basis, value_text, value, unit_text, scale, bbox, method) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'text_layer')",
        [(doc_key, cell["page"], cell["table_no"], cell["row_no"], cell["col_no"],
          cell["row_label"], cell["col_header"], cell["period_id"], cell["basis"],
          cell["value_text"], cell["value"], cell["unit_text"], cell["scale"], cell["bbox"])
         for cell in cells])


def _doc_rows(conn: Any, since: str, types: list[str], symbols: list[str] | None) -> list[Any]:
    sql = ("SELECT doc_key, symbol, doc_type, title, filing_date, known_at, source_key "
           "FROM doc WHERE filing_date >= ? AND doc_type IN ("
           + ",".join("?" * len(types)) + ")")
    params: list[Any] = [since, *types]
    if symbols:
        sql += " AND symbol IN (" + ",".join("?" * len(symbols)) + ")"
        params += symbols
    sql += " ORDER BY symbol, filing_date, doc_key"
    return list(conn.execute(sql, params))


def _blank_stats() -> dict[str, float]:
    return {"documents": 0, "pages": 0, "no_text": 0, "no_table": 0, "cells": 0,
            "period": 0, "scale": 0, "no_header": 0, "seconds": 0.0}


def _print_stats(kind: str, stats: dict[str, float]) -> None:
    def share(key: str) -> float:
        return 100.0 * stats[key] / stats["cells"] if stats["cells"] else 0.0

    print(f"{kind}: documents {int(stats['documents']):,} pages {int(stats['pages']):,} "
          f"skipped {int(stats['no_text'] + stats['no_table']):,} "
          f"({int(stats['no_text']):,} no text, {int(stats['no_table']):,} no table) "
          f"cells {int(stats['cells']):,} period {share('period'):.1f}% "
          f"scale {share('scale'):.1f}% no_header {share('no_header'):.1f}% "
          f"{stats['seconds']:.1f}s")


def build(store: Path, out: Path, since: str = "2025-04-01",
          types: tuple[str, ...] = ("deck", "results"),
          symbols: list[str] | None = None) -> dict[str, dict[str, float]]:
    out.mkdir(parents=True, exist_ok=True)
    directory = out / "company"
    directory.mkdir(parents=True, exist_ok=True)
    source = connect_ro(store, timeout_s=60)
    source.row_factory = sqlite3.Row
    try:
        isins = _current_isins(source)
        docs = _doc_rows(source, since, list(types), symbols)
        stats = {kind: _blank_stats() for kind in types}
        connections: dict[str, sqlite3.Connection] = {}
        missing = duplicates = unmapped = crashed = 0
        try:
            for doc in docs:
                started = time.perf_counter()
                kind = str(doc["doc_type"])
                row_stats = stats[kind]
                row_stats["documents"] += 1
                pdf = Path(str(doc["source_key"]))
                isin = isins.get(str(doc["symbol"]))
                if not isin:
                    unmapped += 1
                    continue
                if not pdf.is_file():
                    missing += 1
                    print(f"MISSING {doc['doc_key']}: {pdf}")
                    continue
                sha256 = _sha256(pdf)
                conn = connections.get(isin)
                if conn is None:
                    conn = connections[isin] = _open_company(directory, isin)
                if conn.execute("SELECT 1 FROM doc WHERE sha256=? LIMIT 1",
                                (sha256,)).fetchone():
                    duplicates += 1
                    continue
                page_stats: dict[str, int] = {}
                try:
                    cells = extract(str(pdf), doc["filing_date"], page_stats)
                except Exception as exc:                     # a broken PDF, not a broken run
                    crashed += 1
                    print(f"CRASH {doc['doc_key']}: {exc}")
                    if crashed >= _CRASH_LIMIT:
                        print(f"STOPPED after {crashed} PDFs crashed pymupdf")
                        break
                    continue
                _write_document(conn, doc, sha256, page_stats.get("pages", 0), cells)
                conn.commit()
                row_stats["pages"] += page_stats.get("pages", 0)
                row_stats["no_text"] += page_stats.get("pages_no_text", 0)
                row_stats["no_table"] += page_stats.get("pages_no_table", 0)
                row_stats["cells"] += len(cells)
                row_stats["period"] += sum(1 for cell in cells if cell["period_id"])
                row_stats["scale"] += sum(1 for cell in cells if cell["scale"] is not None)
                row_stats["no_header"] += sum(1 for cell in cells if not cell["col_header"])
                row_stats["seconds"] += time.perf_counter() - started
        finally:
            for conn in connections.values():
                conn.close()
        print(f"skipped duplicates {duplicates:,} (sha256 already in the company file), "
              f"missing PDFs {missing:,}, unmapped symbols {unmapped:,}, crashed PDFs {crashed:,}")
        for kind in types:
            _print_stats(kind, stats[kind])
        total = _blank_stats()
        for row_stats in stats.values():
            for key in total:
                total[key] += row_stats[key]
        _print_stats("total", total)
        return stats
    finally:
        source.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the v2 table store from decks and results")
    parser.add_argument("--store", required=True, type=Path, help="pilot3 store (read-only)")
    parser.add_argument("--out", required=True, type=Path, help="v2 store root")
    parser.add_argument("--since", default="2025-04-01")
    parser.add_argument("--types", default="deck,results")
    parser.add_argument("--symbols", default=None, help="comma separated")
    args = parser.parse_args(argv)
    types = tuple(kind.strip() for kind in args.types.split(",") if kind.strip())
    symbols = [name.strip() for name in args.symbols.split(",")] if args.symbols else None
    build(args.store, args.out, args.since, types, symbols)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
