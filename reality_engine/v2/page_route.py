"""T-189: route every page of a store's ``doc_page`` to exactly one reading route.

A page is worth a model read only when it prints figures a reader can copy.  The evidence measured on 11 Nov
(30 hand-read frozen2 pages, ``D:/RealityEngine/v2/reference_pages_frozen2/handread/score_local.csv``): every
reader invented figures on 2-4 pages that print none (cover letters, intimations, contents, auditor prose), so
those pages must never reach a reader; and on table/chart pages the page IMAGE is the input the measured reader
wins on (Dots image grid P 83.8 / R 89.6 against ~62 / ~67 on layout text).

Routes (exactly one per page):

* ``no_figures``      - fewer than 4 printed figures, or a cover letter / intimation / contents / auditor prose
                        page (a marker such as "Dear Sir/Madam", "Sub:", "Pursuant to Regulation", "Table of
                        Contents", "Independent Auditor's Report") with low number density.  No reader.
* ``needs_ocr``       - the text layer gives no usable words (``page_words.quality`` none/jumbled) and no OCR
                        words exist yet.  Rerun the CLI with ``--ocr-db`` once the OCR arrives.
* ``table_or_chart``  - ``page_reader.is_table_page`` or ``page_reader._chart_like`` is true, or the page holds a
                        picture (5%+ of the page area) and prints figures.  The page image is the reader's input.
* ``text_ok``         - everything else: prose with a clean text layer, keep the text layer.

Usage:
    python -m reality_engine.v2.page_route --store <db> [--ocr-db <db> ...] --out <csv>
        [--symbols A,B] [--doc-types deck,results] [--limit N]
        [--needs-ocr-pdf-dir <dir>]

The CSV has ``doc_key,page,doc_type,route,reason,word_source,quality``; counts are printed per route and per
doc_type.  ``--needs-ocr-pdf-dir`` exports every ``needs_ocr`` page as ``<safe doc_key>__p<page>.pdf`` plus
``route_export.csv`` (stem -> doc_key, page) for ``hp_ocr.py plan --pdf-dir``; ``hp_ocr.pdf_dir_plan`` reads that
sidecar so the OCR rows land back on the real doc_key/page.
"""
from __future__ import annotations

import argparse
import csv
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from reality_engine.db.readonly import connect_ro
from reality_engine.v2 import page_layout, page_words, page_reader
from reality_engine.v2 import reference_pages as rp

ROUTES = ("no_figures", "needs_ocr", "table_or_chart", "text_ok")
MIN_FIGURES = 4          # fewer printed figures than this is not worth a reader
MARKER_MAX_FIGURES = 8   # a cover letter keeps its reference numbers; a table page prints many more
IMAGE_AREA_SHARE = 0.05  # a chart/table picture covers a real part of the page; a logo does not

# Cover letters, intimations, contents pages, auditor prose: pages whose few numbers are dates and references.
_MARKERS = re.compile(
    r"dear\s+sir|dear\s+madam|^\s*sub\s*:|pursuant\s+to\s+regulation|table\s+of\s+contents|"
    r"independent\s+auditor|auditor'?s\s+report|covering\s+letter|kind\s+attention|"
    r"we\s+wish\s+to\s+inform|this\s+is\s+to\s+inform", re.I | re.M)

_DATE = re.compile(
    r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|"
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+\d{2,4}\b|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{2,4}\b", re.I)
_CIN = re.compile(r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b")
_PHONE = re.compile(r"(?:\+?91[\s-]?)?\b\d{10}\b|\b\d{5}\s\d{5}\b")
_PIN = re.compile(r"\bPIN\s*[:.-]?\s*\d{6}\b|\bpin\s*code\s*[:.-]?\s*\d{6}\b", re.I)
_REG = re.compile(r"\b(?:reg(?:istration)?\.?\s*(?:no|number)|tel|phone|ph|fax|cin|gstin|pan)\b[^\n]{0,40}", re.I)
_PAGE_LINE = re.compile(r"(?im)^\s*(?:page\s+)?\d{1,3}(?:\s+of\s+\d{1,3})?\s*$")
_PAGE_ANY = re.compile(r"\bpage\s+\d{1,3}(?:\s+of\s+\d{1,3})?\b", re.I)
_PARA_NUM = re.compile(r"(?m)^\s*\(?\d{1,2}[.)]\s+")
_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?(?![\w])")
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def figures_in(text: str) -> list[str]:
    """The number tokens of a page that are printed figures, not dates / years / page numbers / phones / PINs /
    CINs / registration codes."""
    text = text or ""
    text = _DATE.sub(" ", text)
    text = _CIN.sub(" ", text)
    text = _PIN.sub(" ", text)
    text = _PHONE.sub(" ", text)
    text = _REG.sub(" ", text)
    text = _PAGE_ANY.sub(" ", text)
    text = _PAGE_LINE.sub(" ", text)          # a standalone footer/header page number
    text = _PARA_NUM.sub(" ", text)           # "1. The company ..." auditor paragraph numbering
    out: list[str] = []
    for tok in _NUM.findall(text):
        bare = tok.rstrip("%").replace(",", "")
        try:
            value = float(bare)
        except ValueError:
            continue
        if bare.isdigit() and len(bare) == 4 and 1900 <= int(bare) <= 2099:
            continue                          # a year, not a figure
        out.append(tok)
    return out


def _has_marker(text: str) -> bool:
    return bool(_MARKERS.search(text or ""))


def _images_share(pdf_path: Any, page_no: int) -> float:
    """Largest picture on the page as a share of the page area (a chart or a pasted table; a logo stays small)."""
    if not pdf_path:
        return 0.0
    try:
        from reality_engine import raw_store

        with raw_store.default_store().local(pdf_path) as local:
            doc = page_words.open_pdf(local)
            if page_no < 1 or page_no > len(doc):
                return 0.0
            page = doc[page_no - 1]
            area = abs(page.rect.width * page.rect.height) or 1.0
            share = 0.0
            for info in page.get_image_info():
                x0, y0, x1, y1 = info.get("bbox") or (0, 0, 0, 0)
                share = max(share, abs((x1 - x0) * (y1 - y0)) / area)
            return share
    except Exception:
        return 0.0


def _page_meta(store_db: Any, doc_key: str, page_no: int) -> tuple[str, str, str, str, str]:
    """(symbol, doc_type, page text, doc_page method, source PDF) of one page."""
    con = connect_ro(store_db)
    try:
        _cur = con.execute(
            "SELECT d.symbol, d.doc_type, p.text, p.method, d.source_key FROM doc d "
            "LEFT JOIN doc_page p ON p.doc_key=d.doc_key AND p.page=? WHERE d.doc_key=?", (page_no, doc_key))
        row = _cur.fetchone() if _cur is not None else None
    finally:
        con.close()
    if not row:
        return "", "", "", "", ""
    return (row[0] or "", rp._doc_type_norm(row[1] or ""), row[2] or "", row[3] or "", row[4] or "")


def route_detail(store_db: Any, doc_key: str, page_no: int, ocr_dbs: Iterable[Any] = (),
                 words: page_words.PageWords | None = None) -> dict[str, str]:
    """One page's route with its reason and the word source behind it."""
    _symbol, _doc_type, text, method, pdf_path = _page_meta(store_db, doc_key, page_no)
    pw = words
    quality = "ok"
    word_source = "store_text"

    if method == "needs_ocr" or not text.strip():
        if pw is None:
            pw = page_words.words_for(store_db, doc_key, page_no, ocr_dbs)
        quality = pw.quality
        word_source = pw.source
        if pw.source.startswith("ocr") and pw.quality == "ok" and pw.words:
            text = page_layout.layout_text(pw.words)          # the OCR words are the page's text
        elif pw.quality in ("none", "jumbled"):
            return {"route": "needs_ocr", "word_source": pw.source, "quality": pw.quality,
                    "reason": f"text layer {pw.quality}: {pw.reason or 'no usable words'}"
                              + ("; OCR words are jumbled too" if pw.source.startswith("ocr") else
                                 "; no OCR words yet")}

    figs = figures_in(text)
    if _has_marker(text) and len(figs) < MARKER_MAX_FIGURES:
        return {"route": "no_figures", "word_source": word_source, "quality": quality,
                "reason": f"cover/intimation/contents/auditor words with {len(figs)} figures"}
    if len(figs) < MIN_FIGURES:
        return {"route": "no_figures", "word_source": word_source, "quality": quality,
                "reason": f"{len(figs)} printed figures (fewer than {MIN_FIGURES})"}

    if pw is None:
        pw = page_words.words_for(store_db, doc_key, page_no, ocr_dbs)
    quality = pw.quality
    word_source = pw.source
    if pw.quality in ("none", "jumbled"):
        if pw.source.startswith("ocr"):
            return {"route": "needs_ocr", "word_source": pw.source, "quality": pw.quality,
                    "reason": f"OCR words are {pw.quality}: {pw.reason}"}
        return {"route": "needs_ocr", "word_source": pw.source, "quality": pw.quality,
                "reason": f"text layer {pw.quality}: {pw.reason or 'no usable words'}; OCR pending"}
    if page_reader.is_table_page(pw.words):
        return {"route": "table_or_chart", "word_source": word_source, "quality": quality,
                "reason": "table: labeled lines of printed figures"}
    if page_reader._chart_like(pw.words):
        return {"route": "table_or_chart", "word_source": word_source, "quality": quality,
                "reason": "chart-like: figures printed without labels"}
    share = _images_share(pdf_path, page_no)
    if share >= IMAGE_AREA_SHARE:
        return {"route": "table_or_chart", "word_source": word_source, "quality": quality,
                "reason": f"picture covering {share:.0%} of the page with {len(figs)} figures"}
    return {"route": "text_ok", "word_source": word_source, "quality": quality,
            "reason": f"prose with a clean text layer, {len(figs)} figures and no table or chart"}


def route_page(store_db: Any, doc_key: str, page_no: int, ocr_dbs: Iterable[Any] = ()) -> tuple[str, str]:
    """(route, reason) for one page; route is one of ``ROUTES``."""
    info = route_detail(store_db, doc_key, page_no, ocr_dbs)
    return info["route"], info["reason"]


def _export_page(store_db: Any, doc_key: str, page_no: int, out_dir: Path) -> str:
    """Write one page as a single-page PDF; return the file stem, or "" when the PDF is unavailable."""
    _symbol, _doc_type, _text, _method, pdf_path = _page_meta(store_db, doc_key, page_no)
    if not pdf_path:
        return ""
    stem = _FILENAME_SAFE.sub("_", doc_key).strip("_")[:120] + f"__p{page_no}"
    try:
        import pymupdf

        from reality_engine import raw_store

        with raw_store.default_store().local(pdf_path) as local:
            src = page_words.open_pdf(local)
            if page_no < 1 or page_no > len(src):
                return ""
            with pymupdf.open() as one:
                one.insert_pdf(src, from_page=page_no - 1, to_page=page_no - 1)
                one.save(str(out_dir / f"{stem}.pdf"))
        return stem
    except Exception:
        return ""


def _pages(store_db: str, symbols: list[str] | None, doc_types: list[str] | None):
    con = connect_ro(store_db)
    try:
        sql = "SELECT doc_key, symbol, doc_type, pages FROM doc"
        params: list[Any] = []
        if symbols:
            sql += " WHERE symbol IN (" + ",".join("?" * len(symbols)) + ")"
            params.extend(symbols)
        _cur = con.execute(sql + " ORDER BY doc_key", params)
        rows = (_cur.fetchall() or []) if _cur is not None else []
        for doc_key, symbol, doc_type, pages in rows:
            dt = rp._doc_type_norm(doc_type or "")
            if doc_types and dt not in doc_types:
                continue
            if not pages:
                continue
            _pcur = con.execute("SELECT page FROM doc_page WHERE doc_key=? ORDER BY page", (doc_key,))
            for (page,) in ((_pcur.fetchall() or []) if _pcur is not None else []):
                yield doc_key, symbol, dt, int(page)
    finally:
        con.close()


def run(store_db: str, ocr_dbs: list[str], out: str, symbols: list[str] | None = None,
        doc_types: list[str] | None = None, limit: int | None = None,
        needs_ocr_pdf_dir: str | None = None) -> list[dict[str, str]]:
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    export_dir = Path(needs_ocr_pdf_dir) if needs_ocr_pdf_dir else None
    exported: list[dict[str, Any]] = []
    if export_dir:
        export_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, str]] = []
    t0 = time.perf_counter()
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["doc_key", "page", "doc_type", "route", "reason",
                                                "word_source", "quality"])
        writer.writeheader()
        for doc_key, _symbol, doc_type, page in _pages(store_db, symbols, doc_types):
            info = route_detail(store_db, doc_key, page, ocr_dbs)
            row = {"doc_key": doc_key, "page": page, "doc_type": doc_type, "route": info["route"],
                   "reason": info["reason"], "word_source": info["word_source"], "quality": info["quality"]}
            results.append(row)
            writer.writerow(row)
            if export_dir and info["route"] == "needs_ocr":
                stem = _export_page(store_db, doc_key, page, export_dir)
                if stem:
                    exported.append({"stem": stem, "doc_key": doc_key, "page": page})
            if limit is not None and len(results) >= limit:
                break
    if export_dir:
        with (export_dir / "route_export.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["stem", "doc_key", "page"])
            w.writeheader()
            w.writerows(exported)
    seconds = time.perf_counter() - t0

    by_route = Counter(r["route"] for r in results)
    by_type: dict[str, Counter[str]] = {}
    for r in results:
        by_type.setdefault(r["doc_type"] or "?", Counter())[r["route"]] += 1
    print(f"routed {len(results)} pages in {seconds:.1f}s ({len(results) / seconds * 60 if seconds else 0:.0f}/min)")
    print("routes: " + ", ".join(f"{k}={by_route.get(k, 0)}" for k in ROUTES))
    print(f"{'doc_type':<16}" + "".join(f"{k:>14}" for k in ROUTES))
    for doc_type in sorted(by_type):
        print(f"{doc_type:<16}" + "".join(f"{by_type[doc_type].get(k, 0):>14}" for k in ROUTES))
    if export_dir:
        print(f"needs_ocr pages exported: {len(exported)} -> {export_dir}")
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-189 route every doc_page to one reading route")
    ap.add_argument("--store", required=True)
    ap.add_argument("--ocr-db", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--doc-types", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--needs-ocr-pdf-dir", default=None)
    args = ap.parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    doc_types = [rp._doc_type_norm(s) for s in args.doc_types.split(",")] if args.doc_types else None
    run(args.store, args.ocr_db, args.out, symbols, doc_types, args.limit, args.needs_ocr_pdf_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
