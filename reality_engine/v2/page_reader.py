"""T-183: production page reader.

Every table page of a store's documents is read by a FREE model in grid format
from layout text; each cell is position-checked (verified/unverified); unread
numbers are re-asked once. Resumable, threaded, written to page_read/page_cell.

Usage:
    python -m reality_engine.v2.page_reader --store <db> [--ocr-db <db> ...] --out <db>
        [--symbols A,B] [--doc-types deck,results] [--limit N] [--reader <MODELS name>]
        [--workers 3]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from reality_engine.db.readonly import connect_ro
from reality_engine.v2 import page_layout, page_words, reference_geom as rg
from reality_engine.v2 import reference_pages as rp

Word = tuple[float, float, float, float, str]


def select_pages(store_db: Any, symbols: Iterable[str] | None = None, doc_types: tuple[str, ...] = ("deck", "results", "annual_report"), limit: int | None = None) -> list[dict[str, Any]]:
    syms = [s.strip() for s in (symbols or []) if str(s).strip()] or None
    wanted = {rp._doc_type_norm(t) for t in doc_types}
    con = connect_ro(store_db)
    try:
        sql = ("SELECT d.doc_key, d.symbol, d.doc_type, d.known_at, p.page, p.text, p.method "
               "FROM doc d JOIN doc_page p ON p.doc_key=d.doc_key")
        params: list[Any] = []
        if syms:
            sql += " WHERE d.symbol IN (" + ",".join("?" * len(syms)) + ")"
            params.extend(syms)
        _cur = con.execute(sql, params)
        _raw = _cur.fetchall() if _cur is not None else None
        rows: list[Any] = list(_raw) if _raw is not None else []
    finally:
        con.close()
    out: list[dict[str, Any]] = []
    for doc_key, symbol, doc_type, known_at, page, text, method in rows:
        dt = rp._doc_type_norm(doc_type)
        if dt not in wanted:
            continue
        t = text or ""
        num_count = len(re.findall(r"\d+(?:[.,]\d+)*", t))
        if not (num_count >= 8 or (method or "") == "needs_ocr"):
            continue
        out.append({"doc_key": doc_key, "symbol": symbol, "doc_type": dt,
                    "known_at": known_at, "page": page})
    out.sort(key=lambda r: (r["doc_key"], r["page"]))
    if limit is not None:
        out = out[:limit]
    return out


def is_table_page(words: list[Word]) -> bool:
    if not words:
        return False
    page = rg.Page(words)
    lines = rg.lines_of(words)
    labeled = 0
    for n, line in enumerate(lines):
        nums = sum(1 for i in line if rg._is_num(words[i][4]))
        has_label = any((not rg._is_num(words[i][4])) and any(c.isalpha() for c in words[i][4]) for i in line)
        if nums >= 2 and (has_label or bool(re.search(r"[A-Za-z]{2}", page.text_left(n, None)))):
            labeled += 1
    if labeled >= 2:
        return True
    num_words = sum(1 for w in words if rg._is_num(w[4]))
    return num_words >= 12


def _chart_like(words: list[Word]) -> bool:
    if not words:
        return False
    page = rg.Page(words)
    num_total = 0
    no_label = 0
    for n, line in enumerate(page.lines):
        line_has_label = any((not rg._is_num(words[i][4])) and any(c.isalpha() for c in words[i][4]) for i in line)
        for i in line:
            if rg._is_num(words[i][4]):
                num_total += 1
                if not line_has_label and not re.search(r"[A-Za-z]{2}", page.text_left(n, None)):
                    no_label += 1
    if num_total == 0:
        return False
    return (no_label / num_total) > 0.5


def _normalize_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for r in raw_rows or []:
        if not isinstance(r, dict):
            continue
        out.append(rp._normalize_row(r))
    return out


def read_page(store_db: Any, doc_key: str, page_no: int, reader: str, ocr_dbs: Iterable[Any] = ()) -> dict[str, Any]:
    con = connect_ro(store_db)
    try:
        _cur = con.execute("SELECT symbol, doc_type, known_at FROM doc WHERE doc_key=?", (doc_key,))
        row = _cur.fetchone() if _cur is not None else None
    finally:
        con.close()
    symbol, doc_type, known_at = "", "", ""
    if row:
        symbol, doc_type, known_at = row[0] or "", rp._doc_type_norm(row[1] or ""), row[2] or ""

    pw = page_words.words_for(store_db, doc_key, page_no, ocr_dbs)
    words = pw.words
    result: dict[str, Any] = {
        "doc_key": doc_key,
        "page": page_no,
        "symbol": symbol,
        "doc_type": doc_type,
        "known_at": known_at,
        "word_source": pw.source,
        "quality": pw.quality,
        "reason": pw.reason,
        "status": "",
        "reader": reader,
        "input": "layout",
        "passes": 1,
        "seconds": 0.0,
        "in_tok": 0,
        "out_tok": 0,
        "rows": 0,
        "cells": 0,
        "verified": 0,
        "unread": 0,
        "error": "",
        "read_at": datetime.now().isoformat(timespec="seconds"),
        "cells_list": [],
    }

    # no words
    if not words or (pw.quality != "ok" and not pw.source.startswith("ocr")):
        result["status"] = "no_words"
        result["reason"] = pw.reason
        return result

    if not is_table_page(words):
        result["status"] = "no_table"
        return result

    layout = page_layout.layout_text(words)
    chart = _chart_like(words)
    image_b64 = None
    if chart:
        try:
            image_b64 = rp._page_image_b64(store_db, doc_key, page_no)
        except Exception as exc:
            image_b64 = None
        result["input"] = "layout_image" if image_b64 else "layout"

    prompt = rp.GRID_PROMPT + (rp.LAYOUT_NOTE + layout + "\n>>>" if layout.strip() else "")

    # first pass
    res = rp._model_call(reader, prompt, image_b64)
    # retry once on error
    if res.get("error"):
        time.sleep(20)
        res = rp._model_call(reader, prompt, image_b64)
    if res.get("error"):
        result["status"] = "error"
        result["error"] = str(res.get("error") or "")
        result["seconds"] = float(res.get("seconds") or 0.0)
        result["in_tok"] = int(res.get("in_tok") or 0)
        result["out_tok"] = int(res.get("out_tok") or 0)
        return result

    found = rp.parse_grid(res.get("output") or "")
    if not found:
        found = rp._parse_rows(res.get("output") or "")
    parsed = _normalize_rows(found)
    all_rows = list(parsed)
    cells, unread = rg.settle_page([all_rows], words)

    seconds = float(res.get("seconds") or 0.0)
    in_tok = int(res.get("in_tok") or 0)
    out_tok = int(res.get("out_tok") or 0)
    passes = 1

    # second pass
    if len(unread) >= 5:
        distinct = sorted({u.get("line_text", "") for u in unread if u.get("line_text")})
        prompt2 = (rp.GRID_PROMPT + "Transcribe ONLY the rows on these printed lines, which were missed:\n"
                   + "\n".join(distinct) + "\n" + rp.LAYOUT_NOTE + layout + "\n>>>")
        res2 = rp._model_call(reader, prompt2, image_b64)
        if res2.get("error"):
            time.sleep(20)
            res2 = rp._model_call(reader, prompt2, image_b64)
        if not res2.get("error"):
            found2 = rp.parse_grid(res2.get("output") or "")
            if not found2:
                found2 = rp._parse_rows(res2.get("output") or "")
            new_rows = _normalize_rows(found2)
            all_rows = all_rows + new_rows
            cells, unread = rg.settle_page([all_rows], words)
            passes = 2
            seconds += float(res2.get("seconds") or 0.0)
            in_tok += int(res2.get("in_tok") or 0)
            out_tok += int(res2.get("out_tok") or 0)

    # build cell list
    cell_list = []
    for c in cells:
        x0 = c.get("x0")
        y0 = c.get("y0")
        x1 = c.get("x1")
        y1 = c.get("y1")
        cell_list.append({
            "doc_key": doc_key,
            "page": page_no,
            "symbol": symbol,
            "known_at": known_at,
            "reader": reader,
            "table_title": "",
            "row_label": c.get("row_label", "") or "",
            "col_header": c.get("col_header", "") or "",
            "value_text": c.get("value_text", "") or "",
            "unit_text": c.get("unit_text", "") or "",
            "status": "verified" if c.get("settled_by") == "position" else "unverified",
            "conflict": c.get("conflict", "") or "",
            "x0": (float(x0) if x0 not in ("", None) else None),
            "y0": (float(y0) if y0 not in ("", None) else None),
            "x1": (float(x1) if x1 not in ("", None) else None),
            "y1": (float(y1) if y1 not in ("", None) else None),
        })

    result["status"] = "read"
    result["passes"] = passes
    result["seconds"] = seconds
    result["in_tok"] = in_tok
    result["out_tok"] = out_tok
    result["rows"] = len(all_rows)
    result["cells"] = len(cells)
    result["verified"] = sum(1 for c in cell_list if c["status"] == "verified")
    result["unread"] = len(unread)
    result["cells_list"] = cell_list
    return result


def _create_out_db(out_path: Path) -> sqlite3.Connection:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(out_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS page_read (
        doc_key TEXT, page INTEGER, symbol TEXT, doc_type TEXT, known_at TEXT,
        word_source TEXT, quality TEXT, reason TEXT, status TEXT, reader TEXT,
        input TEXT, passes INTEGER, seconds REAL, in_tok INTEGER, out_tok INTEGER,
        rows INTEGER, cells INTEGER, verified INTEGER, unread INTEGER, error TEXT, read_at TEXT,
        PRIMARY KEY (doc_key, page, reader)
    );
    CREATE TABLE IF NOT EXISTS page_cell (
        doc_key TEXT, page INTEGER, symbol TEXT, known_at TEXT, reader TEXT,
        table_title TEXT, row_label TEXT, col_header TEXT, value_text TEXT, unit_text TEXT,
        status TEXT, conflict TEXT, x0 REAL, y0 REAL, x1 REAL, y1 REAL
    );
    """)
    con.commit()
    return con


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-183 production page reader")
    ap.add_argument("--store", required=True)
    ap.add_argument("--ocr-db", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--doc-types", default="deck,results,annual_report")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--reader", required=True)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args(argv)

    if not rp._is_free(args.reader):
        raise SystemExit(f"reader {args.reader!r} is not a free model; refusing")

    store_db = args.store
    ocr_dbs = args.ocr_db or []
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    doc_types = tuple(s.strip() for s in args.doc_types.split(",") if s.strip())

    pages = select_pages(store_db, symbols=symbols, doc_types=doc_types, limit=args.limit)

    out_path = Path(args.out)
    con = _create_out_db(out_path)
    _cur = con.execute("SELECT doc_key, page FROM page_read WHERE reader=?", (args.reader,))
    done = {(r[0], r[1]) for r in (_cur.fetchall() if _cur is not None else [])}
    con.close()

    todo = [p for p in pages if (p["doc_key"], p["page"]) not in done]

    results: list[dict[str, Any]] = []
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futures = {ex.submit(read_page, store_db, p["doc_key"], p["page"], args.reader, ocr_dbs): p for p in todo}
            for fut in as_completed(futures):
                results.append(fut.result())

    con = sqlite3.connect(str(out_path))
    for res in results:
        _cur = con.execute("SELECT 1 FROM page_read WHERE doc_key=? AND page=? AND reader=?",
                           (res["doc_key"], res["page"], res["reader"]))
        exists = _cur.fetchone() if _cur is not None else None
        if exists:
            continue
        con.execute(
            """INSERT INTO page_read (doc_key, page, symbol, doc_type, known_at, word_source, quality, reason,
               status, reader, input, passes, seconds, in_tok, out_tok, rows, cells, verified, unread, error, read_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (res["doc_key"], res["page"], res["symbol"], res["doc_type"], res["known_at"], res["word_source"],
             res["quality"], res["reason"], res["status"], res["reader"], res["input"], res["passes"],
             res["seconds"], res["in_tok"], res["out_tok"], res["rows"], res["cells"], res["verified"],
             res["unread"], res["error"], res["read_at"]))
        for cell in res.get("cells_list", []):
            con.execute(
                """INSERT INTO page_cell (doc_key, page, symbol, known_at, reader, table_title, row_label,
                   col_header, value_text, unit_text, status, conflict, x0, y0, x1, y1)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cell["doc_key"], cell["page"], cell["symbol"], cell["known_at"], cell["reader"],
                 cell["table_title"], cell["row_label"], cell["col_header"], cell["value_text"],
                 cell["unit_text"], cell["status"], cell["conflict"], cell["x0"], cell["y0"],
                 cell["x1"], cell["y1"]))
    con.commit()

    # summary
    _cur = con.execute("SELECT status, COUNT(*) FROM page_read WHERE reader=? GROUP BY status", (args.reader,))
    status_rows = _cur.fetchall() if _cur is not None else []
    by_status = {r[0]: r[1] for r in status_rows}
    _cur = con.execute("SELECT COALESCE(SUM(cells),0) FROM page_read WHERE reader=?", (args.reader,))
    _r = _cur.fetchone() if _cur is not None else None
    cells_total = (_r[0] if _r is not None else 0)
    _cur = con.execute("SELECT COALESCE(SUM(verified),0) FROM page_read WHERE reader=?", (args.reader,))
    _r = _cur.fetchone() if _cur is not None else None
    verified_total = (_r[0] if _r is not None else 0)
    _cur = con.execute("SELECT COALESCE(SUM(unread),0) FROM page_read WHERE reader=?", (args.reader,))
    _r = _cur.fetchone() if _cur is not None else None
    unread_total = (_r[0] if _r is not None else 0)
    _cur = con.execute("SELECT COALESCE(SUM(seconds),0) FROM page_read WHERE reader=?", (args.reader,))
    _r = _cur.fetchone() if _cur is not None else None
    seconds_total = (_r[0] if _r is not None else 0)
    con.close()
    vshare = (verified_total / cells_total) if cells_total else 0.0
    print(f"pages: {by_status} cells={cells_total} verified_share={vshare:.3f} "
          f"unread_total={unread_total} seconds={seconds_total:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
