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
import os
import re
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

# Lower wins when an ocr.db holds more than one reading of a page.  T-242: the Nemotron fill (ocr_nemotron_vl)
# only transcribes lines, so it is the fallback under the two box-accurate readers.
OCR_METHOD_PRIORITY = {"ocr_textrec": 0, "ocr_rapid": 1, "ocr_nemotron_vl": 2}

_OPEN: OrderedDict[str, Any] = OrderedDict()

# Quality thresholds (T-175 will tune).
MIN_NON_SPACE_CHARS = 20
VOWELLESS_SHARE_THRESHOLD = 0.3
LONG_WORD_SHARE_THRESHOLD = 0.2
LONG_WORD_CHARS = 25
SINGLE_CHAR_SHARE_THRESHOLD = 0.6
_VOWELS = set("aeiouAEIOU")

# T-208 round 3: the page's tokens must mostly be words the build knows.  Same rule and 0.75 threshold as round 2
# (a page token is clean when it is a word of the build's label lexicon or of the repo's English word list, or a
# clean number), measured on the page's WORD BOXES.  A page below the threshold is read from its OCR words.
DICTIONARY_SCORE_THRESHOLD = 0.75
MIN_SCORED_TOKENS = 30
_LEXICON = Path(__file__).resolve().parents[1] / "pilot3" / "lexicon"
_ENGLISH = Path(__file__).resolve().parents[1] / "pilot3" / "en_vocab.txt"
_NUMBER_TOKEN = re.compile(r"^[0-9][0-9,.\-()]*$")
_EDGE_PUNCT = ".,;:()[]'\"\u2019\u2018\u201c\u201d"
_DICTIONARY: frozenset[str] | None = None


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

    # Path.resolve() hit the filesystem (GetFinalPathName) once per page: 28 s of the c01 route.  The key only has
    # to be one spelling per file, and a build passes the same spelling every time, so abspath + case fold do it.
    key = os.path.normcase(os.path.abspath(os.fspath(pdf_path)))
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


def dictionary() -> frozenset[str]:
    """Words the build knows: every label pattern of ``pilot3/lexicon/*.yaml``, ``business_abbrev.txt`` and the
    repo's English word list (``pilot3/en_vocab.txt``).  Read once per process."""
    global _DICTIONARY
    if _DICTIONARY is None:
        words: set[str] = set()

        def add(text: str) -> None:
            words.update(w for w in re.split(r"[^a-z0-9]+", text.lower()) if w)

        import yaml

        for path in sorted(_LEXICON.glob("*.yaml")):
            try:
                stack: list[Any] = [yaml.safe_load(path.read_text(encoding="utf-8"))]
            except (OSError, yaml.YAMLError):
                continue
            while stack:
                item = stack.pop()
                if isinstance(item, str):
                    add(item)
                elif isinstance(item, list):
                    stack.extend(item)
                elif isinstance(item, dict):
                    stack.extend(item.keys())
                    stack.extend(item.values())
        for path in (_LEXICON / "business_abbrev.txt", _ENGLISH):
            try:
                add(path.read_text(encoding="utf-8"))
            except OSError:
                continue
        _DICTIONARY = frozenset(words)
    return _DICTIONARY


def dictionary_score(words: list[Word]) -> dict | None:
    """``{share, clean, scored}`` of the page's tokens, or None under ``MIN_SCORED_TOKENS`` scored tokens.

    Single characters and bare separators are not scored; a number is clean whatever its digits, so a garbled
    text layer is caught by its WORDS (``Revpnul'``), not by its figures."""
    vocabulary = dictionary()
    clean = scored = 0
    for word in words:
        text = str(word[4]).strip()
        if len(text) <= 1 or not any(c.isalnum() for c in text):
            continue
        scored += 1
        if _NUMBER_TOKEN.match(text) or text.strip(_EDGE_PUNCT).lower() in vocabulary:
            clean += 1
    if scored < MIN_SCORED_TOKENS:
        return None
    return {"share": clean / scored, "clean": clean, "scored": scored}


def quality(words: list[Word], check_figures: bool = True) -> tuple[str, str]:
    """Verdict on a list of word boxes: ('none', reason) / ('jumbled', reason) / ('ok', '').  ``check_figures``:
    judge a text layer's figures too (T-225); OCR words are not judged on them, so a page cannot be sent to OCR twice."""
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
    from reality_engine.v2.reference_geom import GARBLED_SHARE, layer_garbled   # lazy: reference_geom imports us

    if check_figures and layer_garbled(words):                    # figures misread by a scan layer ("18,527,91J"): OCR them (T-225)
        return "jumbled", f"malformed figure share >= {GARBLED_SHARE}"
    verdict = dictionary_score(words)
    if verdict is not None and verdict["share"] < DICTIONARY_SCORE_THRESHOLD:
        return "jumbled", (f"label-dictionary share {verdict['share']:.2f} < {DICTIONARY_SCORE_THRESHOLD} "
                           f"({verdict['clean']} of {verdict['scored']} tokens clean)")
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
    priority = OCR_METHOD_PRIORITY
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
    priority = OCR_METHOD_PRIORITY
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


def sibling_ocr_db(store_db: Any) -> Path:
    """The OCR database a store keeps beside itself: ``<stem>_ocr.db`` (T-238).

    ``pilot3 build --part ocr`` writes it next to its build (``<out dir>/<stem>_ocr.db``) and ``hp_ocr.py`` puts
    the TextRecognizer pass at the same path, so every caller of :func:`words_for` (route, reader, recheck) finds a
    page's OCR words without an explicit ``--ocr-db`` argument."""
    path = Path(str(store_db))
    return path.with_name(f"{path.stem}_ocr.db")


def words_for(store_db: Any, doc_key: str, page_no: int, ocr_dbs: Iterable[Any] = (),
              source_key: str | None = None) -> PageWords:
    """``source_key`` is the doc row's source PDF when the caller already read it (route: one query per document
    instead of one store connection per page); None reads it from the store as before."""
    store = raw_store.default_store()
    own = sibling_ocr_db(store_db)
    ocr_dbs = tuple(ocr_dbs or ()) + ((own,) if own.is_file() else ())
    if source_key is None:
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
        oq, or_ = quality(ocr_list, check_figures=False)
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
