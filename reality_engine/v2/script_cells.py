"""Store writer for script-read cells (T-226 reader, Shivam 20 Nov: option 1).

Reads every results page of one company store with ``script_reader`` (no model), runs the witness gate
(arithmetic identities, exact XBRL, cross-filing agreement, the XBRL date and basis votes) and writes the served
cells into the store's own ``script_cell`` table, beside the rows the store already serves:

- ``verified``: an independent witness agrees (``witness`` names it: arith, xbrl, cross);
- ``unverified``: two filings 45+ days apart print the same value, nothing else (served labelled);
- refused cells are not written (unsure = no row).

Each row keeps what was printed (row label, column header, value text, page position) and what was resolved
(period end, period kind, basis, unit scale, numeric value in rupees), plus ``period_inferred`` / ``basis_inferred``
when the date or basis came from a fiscal label or an XBRL vote rather than the printed header.  A rebuild replaces
the table for that store; nothing else in the store is touched.  ``script_cell_run`` keeps one row per build.

    python -m reality_engine.v2.script_cells <store.db> [--ocr <store_ocr.db>] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from reality_engine.v2 import cell_judge as cj
from reality_engine.v2 import page_words
from reality_engine.v2 import script_reader as sr

READER = "script"
VERSION = "t226-r26"          # the rule set measured in round 26 (docs/V2_SCHEMA_CONTRACT.md s16)

SCHEMA = """
CREATE TABLE IF NOT EXISTS script_cell (
    doc_key TEXT, page INTEGER, symbol TEXT, known_at TEXT, reader TEXT, version TEXT,
    table_title TEXT, section TEXT, row_label TEXT, col_header TEXT, value_text TEXT,
    value REAL, unit_scale REAL, period_end TEXT, period_kind TEXT, basis TEXT,
    period_inferred INTEGER, basis_inferred INTEGER,
    status TEXT, witness TEXT, gate TEXT,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL
);
CREATE INDEX IF NOT EXISTS script_cell_lookup ON script_cell(symbol, period_end, basis);
CREATE TABLE IF NOT EXISTS script_cell_run (
    run_at TEXT, version TEXT, pages INTEGER, cells_read INTEGER, verified INTEGER, unverified INTEGER,
    refused INTEGER, seconds REAL, errors INTEGER, note TEXT
);
"""


def read_store(store_db: str | Path, ocr_dbs: list[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every results page of the store read and gated; returns (cells, stats).  Read-only on the store."""
    con = sqlite3.connect(f"file:{Path(store_db).as_posix()}?mode=ro", uri=True)
    try:
        docs = {d: (k, s) for d, k, s in con.execute("SELECT doc_key, known_at, symbol FROM doc")}
        filed = {d: _dt.date.fromisoformat(k[:10]) for d, (k, _) in docs.items() if k}
        pages = con.execute("SELECT p.doc_key, p.page FROM doc_page p JOIN doc d USING(doc_key) "
                            "WHERE d.doc_type='results' AND length(p.text) > 400 ORDER BY 1, 2").fetchall()
        dunit = {d: sr.doc_unit(t for (t,) in con.execute("SELECT text FROM doc_page WHERE doc_key=?", (d,)))
                 for d in {d for d, _ in pages}}
    finally:
        con.close()
    xbrl = cj.XbrlIndex.from_store(store_db)
    fy = sr.fy_end_month(xbrl)
    cells: list[dict[str, Any]] = []
    errors = 0
    for doc, pg in pages:
        pw = page_words.words_for(store_db, doc, pg, ocr_dbs or [])
        if not pw.words:
            continue
        try:
            got = sr.settled(pw.words, dunit[doc], fy)
            sr.arith_witness(got)
        except Exception:  # noqa: BLE001 - one bad page must not stop the store; counted in the run row
            errors += 1
            continue
        for c in got:
            c["doc_key"], c["page"] = doc, pg
        cells += got
    sr.date_columns_by_xbrl(cells, filed, xbrl)
    sr.basis_columns_by_xbrl(cells, xbrl)
    sr.witness_gate(cells, filed, xbrl=xbrl)
    for c in cells:
        c["known_at"], c["symbol"] = docs.get(c["doc_key"], ("", ""))
    stats = {"pages": len(pages), "cells_read": len(cells), "errors": errors,
             "verified": sum(c["status"] == "verified" for c in cells),
             "unverified": sum(c["status"] == "unverified" for c in cells)}
    stats["refused"] = stats["cells_read"] - stats["verified"] - stats["unverified"]
    return cells, stats


def _row(c: dict[str, Any]) -> tuple:
    num = cj.number(c["value_text"])
    scale = c.get("unit_scale") or None
    value = num[0] * scale if num and scale else None
    box = c.get("box") or (None, None, None, None)
    return (c["doc_key"], c["page"], c.get("symbol") or "", c.get("known_at") or "", READER, VERSION,
            c.get("title", ""), c.get("section", ""), c["row_label"], c.get("col_header", ""), c["value_text"],
            value, scale, c.get("period_end") or "", c.get("kind") or "", c.get("basis") or "",
            int(bool(c.get("period_inferred"))), int(bool(c.get("basis_inferred"))),
            c["status"], c.get("witness", ""), c.get("gate", ""), *box)


def write_store(store_db: str | Path, cells: list[dict[str, Any]], stats: dict[str, Any], seconds: float) -> int:
    """Replace ``script_cell`` with the served cells (verified, unverified); one ``script_cell_run`` row."""
    served = [c for c in cells if c["status"] in ("verified", "unverified")]
    con = sqlite3.connect(str(store_db))
    try:
        con.executescript(SCHEMA)
        with con:
            con.execute("DELETE FROM script_cell")
            con.executemany(f"INSERT INTO script_cell VALUES ({','.join('?' * 25)})", [_row(c) for c in served])
            con.execute("INSERT INTO script_cell_run VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (_dt.datetime.now().isoformat(timespec="seconds"), VERSION, stats["pages"],
                         stats["cells_read"], stats["verified"], stats["unverified"], stats["refused"],
                         round(seconds, 1), stats["errors"], ""))
    finally:
        con.close()
    return len(served)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("store")
    ap.add_argument("--ocr", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    t = time.time()
    ocr = a.ocr or [p for p in [str(Path(a.store).with_name(Path(a.store).stem + "_ocr.db"))] if Path(p).exists()]
    cells, stats = read_store(a.store, ocr)
    if not a.dry_run:
        stats["written"] = write_store(a.store, cells, stats, time.time() - t)
    stats["seconds"] = round(time.time() - t, 1)
    print(json.dumps({"store": a.store, **stats}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
