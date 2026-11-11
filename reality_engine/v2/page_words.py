"""T-182: word boxes for any page of any held document.

One source for the layout renderer (page_layout) and the position check
(reference_geom): the PDF text layer turned upright when it is present and
readable, otherwise the OCR word boxes stored in ocr_page.  A quality verdict
(ok / none / jumbled) accompanies the boxes so callers can tell which source
was used and why.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from reality_engine import raw_store
from reality_engine.db.readonly import connect_ro
from reality_engine.v2 import page_layout

Word = tuple[float, float, float, float, str]

_OPEN: OrderedDict[str, Any] = OrderedDict()

# Quality thresholds (T-175 will tune).
MIN_NON_SPACE_CHARS = 20
VOWELLESS_SHARE_THRESHOLD = 0.3
LONG_WORD_SHARE_THRESHOLD = 0.2
LONG_WORD_CHARS = 25
SINGLE_CHAR_SHARE_THRESHOLD = 0.6
_VOWELS = set("aeiouAEIOU")


@dataclass
class PageWords:
    source: str
    words: list[Word] = field(default_factory=list)
    quality: str = "none"
    reason: str = ""


def open_pdf(pdf_path: Path | str) -> Any:
    """The pymupdf document for ``pdf_path``, kept open for the next pages (the last 3 files stay open), so a
    page loop opens each PDF once instead of once per page.  Do not close the returned document.  A Drive temp
    (``raw_store.local`` writes it under ``raw_fetch_`` and deletes it on exit) is never cached."""
    import pymupdf

    key = str(Path(pdf_path).resolve())
    cacheable = "raw_fetch_" not in key
    doc = _OPEN.get(key) if cacheable else None
    if doc is None:
        doc = pymupdf.open(key)
        if cacheable:
            _OPEN[key] = doc
            while len(_OPEN) > 3:
                _, old = _OPEN.popitem(last=False)
                old.close()
    else:
        _OPEN.move_to_end(key)
    return doc


def pdf_words(pdf_path: Path | str, page_no: int) -> list[Word]:
    """Text-layer word boxes for page_no (1-based) of a (possibly multi-page) PDF,
    with a sideways page turned upright (same logic as reference_geom.page_words)."""
    return pdf_words_of(open_pdf(pdf_path), page_no)


def pdf_words_of(doc: Any, page_no: int) -> list[Word]:
    page = doc[page_no - 1]
    raw: Any = page.get_text("words")
    words: list[Word] = [
        (float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])) for w in raw
    ]
    dirs: Counter[tuple[int, int]] = Counter()
    layout: Any = page.get_text("dict")
    for block in layout.get("blocks", []):
        for line in block.get("lines", []):
            d = line.get("dir") or (1.0, 0.0)
            dirs[(round(d[0]), round(d[1]))] += sum(
                len(sp.get("text", "")) for sp in line.get("spans", [])
            )
    dx, dy = dirs.most_common(1)[0][0] if dirs else (1, 0)
    if (dx, dy) == (1, 0):
        return words
    out: list[Word] = []
    for x0, y0, x1, y1, text in words:
        us = [x0 * dx + y0 * dy, x1 * dx + y1 * dy]
        vs = [-x0 * dy + y0 * dx, -x1 * dy + y1 * dx]
        out.append((min(us), min(vs), max(us), max(vs), text))
    return out


def _no_vowel(word: str) -> bool:
    return not any(c in _VOWELS for c in word)


def quality(words: list[Word]) -> tuple[str, str]:
    """Verdict on a list of word boxes: ('none', reason) / ('jumbled', reason) / ('ok', '')."""
    text = " ".join(w[4] for w in words)
    non_space = len(text.replace(" ", ""))
    if non_space < MIN_NON_SPACE_CHARS:
        return "none", f"fewer than {MIN_NON_SPACE_CHARS} non-space characters"
    total = len(words)
    if total == 0:
        return "none", f"fewer than {MIN_NON_SPACE_CHARS} non-space characters"
    alpha4 = [w for w in words if w[4].isalpha() and len(w[4]) >= 4]
    if alpha4:
        nv = sum(1 for w in alpha4 if _no_vowel(w[4]))
        if nv / len(alpha4) > VOWELLESS_SHARE_THRESHOLD:
            return "jumbled", "share of alphabetic words of 4+ letters with no vowel > 0.3"
    long_n = sum(1 for w in words if len(w[4]) > LONG_WORD_CHARS)
    if long_n / total > LONG_WORD_SHARE_THRESHOLD:
        return "jumbled", "share of words longer than 25 characters > 0.2"
    single_n = sum(1 for w in words if len(w[4]) == 1)
    if single_n / total > SINGLE_CHAR_SHARE_THRESHOLD:
        return "jumbled", "share of single-character words > 0.6"
    return "ok", ""


def _ocr_method(ocr_dbs: Iterable[Any], doc_key: str, page_no: int) -> str:
    methods: list[str] = []
    for db in ocr_dbs or ():
        con: Any = None
        close = False
        if hasattr(db, "execute"):
            con = db
        else:
            p = Path(db)
            if not p.is_file():
                continue
            con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
            close = True
        try:
            try:
                for (m,) in con.execute(
                    "SELECT method FROM ocr_page WHERE doc_key=? AND page=?", (doc_key, page_no)
                ):
                    methods.append(m or "")
            except sqlite3.Error:
                pass
        finally:
            if close:
                con.close()
    priority = {"ocr_textrec": 0, "ocr_rapid": 1}
    if not methods:
        return "ocr_rapid"
    methods.sort(key=lambda m: priority.get(m, 2))
    return methods[0]


def ocr_words(ocr_dbs: Iterable[Any], doc_key: str, page_no: int) -> list[Word]:
    rows: list[tuple[str, str]] = []
    for db in ocr_dbs or ():
        con: Any = None
        close = False
        if hasattr(db, "execute"):
            con = db
        else:
            p = Path(db)
            if not p.is_file():
                continue
            con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
            close = True
        try:
            try:
                for wj, method in con.execute(
                    "SELECT words_json, method FROM ocr_page WHERE doc_key=? AND page=?", (doc_key, page_no)
                ):
                    rows.append((wj, method or ""))
            except sqlite3.Error:
                pass
        finally:
            if close:
                con.close()
    if not rows:
        return []
    priority = {"ocr_textrec": 0, "ocr_rapid": 1}
    rows.sort(key=lambda r: priority.get(r[1], 2))
    wj, _method = rows[0]
    try:
        data = json.loads(wj)
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[Word] = []
    for item in data or []:
        try:
            x0, y0, x1, y1 = float(item[0]), float(item[1]), float(item[2]), float(item[3])
        except (TypeError, ValueError, IndexError):
            continue
        text = str(item[4]) if len(item) > 4 else ""
        out.append((x0, y0, x1, y1, text))
    return out


def words_for(store_db: Any, doc_key: str, page_no: int, ocr_dbs: Iterable[Any] = ()) -> PageWords:
    store = raw_store.default_store()
    source_key = None
    con: Any = connect_ro(store_db)          # a missing store or doc table is an error, not an empty page
    try:
        row = con.execute("SELECT source_key FROM doc WHERE doc_key=?", (doc_key,)).fetchone()
        if row:
            source_key = row[0]
    finally:
        con.close()
    pdf_error = ""

    text_words: list[Word] = []
    text_q = "none"
    text_r = ""
    got_text = False
    if source_key and store.exists(source_key):
        try:
            with store.local(source_key) as p:
                text_words = pdf_words(p, page_no)
            got_text = True
        except Exception as exc:                # corrupt or encrypted PDF: say so in the verdict's reason
            text_words = []
            pdf_error = f"pdf unreadable: {type(exc).__name__}: {exc}"[:200]
            got_text = False
        text_q, text_r = quality(text_words)
        if text_q == "ok":
            return PageWords(source="script_text", words=text_words, quality=text_q, reason=text_r)

    ocr_list = ocr_words(ocr_dbs, doc_key, page_no)
    if text_q != "ok" and ocr_list:
        method = _ocr_method(ocr_dbs, doc_key, page_no)
        oq, or_ = quality(ocr_list)
        return PageWords(source=method, words=ocr_list, quality=oq, reason=or_)

    if text_words:
        return PageWords(source="script_text", words=text_words, quality=text_q, reason=text_r)
    if not source_key:
        why = "doc has no source PDF"
    elif not store.exists(source_key):
        why = "source PDF neither local nor on Drive"
    else:
        why = pdf_error or text_r or "no words"
    return PageWords(source="none", words=[], quality="none", reason=why)


def _survey(store_db: str, ocr_dbs: list[str], out: str) -> None:
    con: Any = connect_ro(store_db)
    try:
        rows = con.execute(
            """SELECT d.doc_key, d.symbol, d.doc_type, d.pages,
                      COALESCE(SUM(CASE WHEN p.method='script_text' THEN 1 ELSE 0 END),0) AS tp,
                      COALESCE(SUM(CASE WHEN p.method IN ('ocr_rapid','ocr_textrec') THEN 1 ELSE 0 END),0) AS op,
                      COALESCE(SUM(CASE WHEN p.method='needs_ocr' THEN 1 ELSE 0 END),0) AS np
               FROM doc d LEFT JOIN doc_page p ON p.doc_key=d.doc_key
               GROUP BY d.doc_key, d.symbol, d.doc_type, d.pages
               ORDER BY d.doc_key"""
        ).fetchall()
    finally:
        con.close()

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["doc_key", "symbol", "doc_type", "pages", "text_pages", "ocr_pages", "none_pages"])
        for r in rows:
            w.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6]])

    docs = len(rows)
    pages = sum((r[3] or 0) for r in rows)
    tp = sum(r[4] for r in rows)
    op = sum(r[5] for r in rows)
    np_ = sum(r[6] for r in rows)
    print(f"survey: {docs} docs, {pages} pages: text_pages={tp}, ocr_pages={op}, none_pages={np_}")


def _show(store_db: str, doc_key: str, page_no: int) -> None:
    pw = words_for(store_db, doc_key, page_no, ())
    print(f"source: {pw.source}")
    print(f"quality: {pw.quality} {pw.reason}".rstrip())
    print(page_layout.layout_text(pw.words))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="word boxes for any page of any held document")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("survey")
    s.add_argument("--store", required=True)
    s.add_argument("--ocr-db", action="append", default=[])
    s.add_argument("--out", required=True)
    sh = sub.add_parser("show")
    sh.add_argument("--store", required=True)
    sh.add_argument("--doc-key", required=True)
    sh.add_argument("--page", type=int, required=True)
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    if args.cmd == "survey":
        _survey(args.store, args.ocr_db, args.out)
    elif args.cmd == "show":
        _show(args.store, args.doc_key, args.page)
    dt = time.perf_counter() - t0
    print(f"seconds: {dt:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
