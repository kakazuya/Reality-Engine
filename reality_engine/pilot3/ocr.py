"""Local OCR of the pages that have no text layer -> table ocr_page (T-049 E). RapidOCR (ONNX) only: no model call, no network.

CLI: python -m reality_engine.pilot3.ocr --out <ocr.db> [--symbols KEC,BAJFINANCE,HINDALCO] [--max-seconds 540] [--limit N]
                                          [--pages-db D:\\RealityEngine\\pilot3\\pages.db] [--dpi 300] [--max-side 2400]
                                          [--device cpu|dml] [--reverse]

Pages come from three places: (1) the real collection ``pages.db`` (``docs_collect.py``) -- its ``doc_page`` rows
with method ``needs_ocr`` for the symbol, PDF path from ``doc.source_path``, the doc_key kept exactly as build.py
writes it into ``doc_page`` so a rebuild can join the OCR text to that page; (2) sandbox ``doc_text`` rows with
method needs_ocr (PDF under ``<sym>_loop/raw``) for documents pages.db does not hold; (3) the decks_full PDFs that
deck_figures cites but docs does not hold, for pages whose text layer is empty.  A page already stored under a key
that names the same document (a sandbox ``doc_alias`` key or the decks_full sha key) is skipped, so no page is read
twice.  ``--pages-db ''`` disables source (1).
Each page is rendered at 300 DPI in grayscale (PyMuPDF), read by RapidOCR, and stored with the page text, the
word boxes in PDF points (so kpi.py's row/column tolerances behave as on a text layer) and the mean OCR confidence.
The run is resumable: pages already in ``ocr_page`` are skipped, ``--max-seconds`` stops cleanly between pages.
``method`` is ``ocr_rapid`` (``hp_ocr.py`` writes the same table with ``ocr_textrec``); kpi.py copies
it and ``ocr_conf`` onto every kpi_series row read from such a page.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from reality_engine import raw_store
from reality_engine.pilot3 import PAGES_DB, kpi, profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS ocr_page (
  symbol TEXT NOT NULL, doc_key TEXT NOT NULL, page INTEGER NOT NULL, doc_type TEXT, known_at TEXT,
  text TEXT NOT NULL, words_json TEXT NOT NULL, ocr_conf REAL, n_boxes INTEGER, dpi INTEGER,
  seconds REAL, method TEXT NOT NULL DEFAULT 'ocr_rapid',
  PRIMARY KEY (symbol, doc_key, page)
);
"""
DOC_PRIORITY = {"deck": 0, "results": 1, "press_release": 2, "transcript": 3, "annual_report": 4, "announcement": 5}
_ROW_TOL = 8.0   # points; same row clustering as kpi.page_rows


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    return fitz


def _open_ro(path: Path | str | None) -> sqlite3.Connection | None:
    """Read-only connection to ``path``, or None when it is not set or not on this machine."""
    p = Path(path) if path else None
    return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True) if p and p.is_file() else None


def _sort_key(r) -> tuple:
    """(doc_type, known_at, doc_key, page, pdf): decks, results, press releases, ... newest first."""
    return (DOC_PRIORITY.get(r[0], 9), -int(str(r[1] or "0")[:10].replace("-", "") or 0), r[2], r[3])


def pending(sym: str, sandbox: Path, raw_root: Path | None, done: set,
            pages_db: Path | str | None = None) -> list[tuple]:
    """[(doc_key, page, doc_type, known_at, pdf_path)] still to OCR: pages.db needs_ocr pages (key = the doc_key
    build.py writes to doc_page), then decks_full, then sandbox pages by doc type, newest first.  A page stored
    already under a key that names the same document (sandbox alias, decks_full sha) is skipped."""
    fitz = _fitz()
    store = raw_store.default_store()
    dbp = sandbox / f"{sym.lower()}_loop" / f"{sym.lower()}.db"
    con = sqlite3.connect(f"file:{dbp.as_posix()}?mode=ro", uri=True)
    out: list[tuple] = []
    claimed: set[tuple] = set()          # (pages.db doc_key, page) this list will OCR from pages.db
    doc_keys: dict[str, set] = {}        # pages.db doc_key -> every key that page may already be stored under
    alias: dict[str, str] = {}           # sandbox doc_key -> pages.db doc_key (same document)
    pg = _open_ro(pages_db)
    if pg is not None:
        from reality_engine.pilot3 import registry

        alias = {a: k for a, k in registry.plan_docs(sym, pg, con)["alias"].items() if not k.startswith(f"{sym}:")}
        for dk, sha in pg.execute("SELECT doc_key, sha256 FROM doc WHERE symbol=?", (sym,)):
            doc_keys[dk] = {dk} | {s for s, k in alias.items() if k == dk}
            if sha:
                doc_keys[dk].add(f"decks_full/{sha[:2]}/{sha}.pdf")
        rows = pg.execute("SELECT p.doc_key, p.page, d.doc_type, d.known_at, d.source_path FROM doc_page p "
                          "JOIN doc d ON d.doc_key=p.doc_key WHERE d.symbol=? AND p.method='needs_ocr'", (sym,)).fetchall()
        for dk, page, doc_type, known_at, source_path in rows:
            if any((k, page) in done for k in doc_keys.get(dk, (dk,))):
                continue
            path = Path(source_path) if source_path else None
            if path is None or not store.exists(path):
                continue                                # no PDF on this machine and none on Drive: nothing to render
            claimed.add((dk, page))
            out.append((doc_type, known_at, dk, page, path))
        pg.close()
    # 1) decks the sandbox does not hold (FY25-FY27 presentations): empty text-layer pages
    if raw_root is not None:
        held = {r[0] for r in con.execute("SELECT source_key FROM docs WHERE source_key IS NOT NULL")}
        for sha, known_at in con.execute("SELECT sha256, min(known_at) FROM deck_figures GROUP BY sha256 ORDER BY 2 DESC"):
            if sha in held:
                continue
            path = raw_root / "decks_full" / sha[:2] / f"{sha}.pdf"
            if not store.exists(path):
                continue
            key = f"decks_full/{sha[:2]}/{sha}.pdf"
            keys = {key} | {dk for dk, ks in doc_keys.items() if key in ks}
            try:
                pdf = fitz.open(str(path))
            except Exception:
                continue
            for i in range(pdf.page_count):
                page = i + 1
                if any((k, page) in done for k in keys) or any((dk, page) in claimed for dk in keys):
                    continue
                if len(pdf[i].get_text("text").strip()) < 20:
                    out.append(("deck", known_at, key, page, path))
            pdf.close()
    # 2) sandbox pages that doc_text marked needs_ocr, for documents pages.db does not hold
    rows = con.execute(
        f"SELECT t.doc_key, t.page, d.doc_type, d.known_at FROM doc_text t JOIN docs d USING(doc_key) "
        f"WHERE t.method='needs_ocr' AND d.doc_type IN ({','.join('?' * len(kpi.KPI_DOC_TYPES))})",
        kpi.KPI_DOC_TYPES).fetchall()
    for doc_key, page, doc_type, known_at in rows:
        if doc_key in alias or (doc_key, page) in done:
            continue
        p = sandbox / f"{sym.lower()}_loop" / "raw" / doc_key
        if p.exists():
            out.append((doc_type, known_at, doc_key, page, p))
    con.close()
    out.sort(key=_sort_key)
    return [(r[2], r[3], r[0], r[1], r[4]) for r in out]


_ENG: list = []


def engine(device: str = "cpu", max_side: int = 2400):
    if not _ENG:
        from rapidocr import RapidOCR
        params = {"Global.log_level": "ERROR", "Global.max_side_len": max_side}
        if device == "dml":
            params["EngineConfig.onnxruntime.use_dml"] = True
        _ENG.append(RapidOCR(params=params))
    return _ENG[0]


def render_gray(page, dpi: int = 300):
    """Grayscale numpy image (H, W, 3) of the page at `dpi`; 3 channels because the detector expects them."""
    import numpy as np
    fitz = _fitz()
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return np.repeat(a[:, :, None], 3, axis=2)


def boxes_to_words(boxes, txts, scores, dpi: int) -> list[list]:
    """OCR line boxes -> word tuples [x0, y0, x1, y1, text, conf] in PDF points; a line is split on spaces with the
    box width shared by character count."""
    k = 72.0 / dpi
    words = []
    for box, t, s in zip(boxes, txts, scores):
        xs = [float(p[0]) * k for p in box]
        ys = [float(p[1]) * k for p in box]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        toks = t.split()
        if not toks:
            continue
        total = sum(len(w) for w in toks) + (len(toks) - 1)
        pos = 0
        for w in toks:
            a = x0 + (x1 - x0) * pos / total
            b = x0 + (x1 - x0) * (pos + len(w)) / total
            words.append([round(a, 2), round(y0, 2), round(b, 2), round(y1, 2), w, round(float(s), 3)])
            pos += len(w) + 1
    return words


def words_to_text(words: list[list]) -> str:
    """Page text from the words: rows clustered by y (kpi.page_rows), words left to right, rows joined by newline."""
    rows = kpi.page_rows([(w[0], w[1], w[2], w[3], w[4]) for w in words])
    return "\n".join(r.text() for r in rows)


def ocr_page(page, dpi: int = 300, device: str = "cpu", max_side: int = 2400) -> tuple[str, list[list], float, int]:
    """-> (text, words, mean_confidence, n_boxes) for one fitz page."""
    res = engine(device, max_side)(render_gray(page, dpi))
    if res is None or res.boxes is None or not len(res.txts or ()):
        return "", [], 0.0, 0
    words = boxes_to_words(res.boxes, res.txts, res.scores, dpi)
    conf = sum(float(s) for s in res.scores) / len(res.scores)
    return words_to_text(words), words, conf, len(res.txts)


def run(out: str, symbols: list[str], sandbox: Path, raw_root: Path | None, max_seconds: float, limit: int | None,
        dpi: int, device: str, max_side: int = 2400, reverse: bool = False,
        pages_db: Path | str | None = PAGES_DB) -> dict:
    fitz = _fitz()
    store = raw_store.default_store()
    t0 = time.time()
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    stats: dict = {}
    for sym in symbols:
        done = {(r[0], r[1]) for r in con.execute("SELECT doc_key, page FROM ocr_page WHERE symbol=?", (sym,))}
        todo = pending(sym, sandbox, raw_root, done, pages_db)
        st = stats.setdefault(sym, {"pending_at_start": len(todo), "done": 0, "seconds_ocr": 0.0, "boxes": 0, "empty": 0})
        if reverse:      # a second worker starting from the other end of the list (own --out db, merge afterwards)
            todo.reverse()
        if limit:
            todo = todo[:limit]
        pdf, pdf_path = None, None
        # A company's PDFs are fetched once and deleted when this loop ends (T-102): a raw file may be only on Drive.
        with store.prefetch([item[4] for item in todo]):
            for doc_key, page, doc_type, known_at, path in todo:
                if time.time() - t0 > max_seconds:
                    stats["stopped_at_time_limit"] = True
                    break
                try:
                    if pdf_path != path:
                        if pdf is not None:
                            pdf.close()
                        with store.local(path) as source:
                            pdf, pdf_path = fitz.open(str(source)), path
                    t1 = time.time()
                    text, words, conf, nb = ocr_page(pdf[page - 1], dpi, device, max_side)
                    dt = time.time() - t1
                except Exception as ex:  # keep going, count it
                    st["errors"] = st.get("errors", 0) + 1
                    st["last_error"] = f"{type(ex).__name__}: {ex}"[:120]
                    continue
                con.execute("INSERT OR REPLACE INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (sym, doc_key, page, doc_type, known_at, text, json.dumps(words, separators=(",", ":")),
                             round(conf, 4), nb, dpi, round(dt, 2), "ocr_rapid"))
                st["done"] += 1
                st["seconds_ocr"] = round(st["seconds_ocr"] + dt, 1)
                st["boxes"] += nb
                st["empty"] += int(nb == 0)
                if st["done"] % 20 == 0:
                    con.commit()
            if pdf is not None:
                pdf.close()
        con.commit()
        st["pages_per_min"] = round(60 * st["done"] / st["seconds_ocr"], 1) if st["seconds_ocr"] else 0
        if stats.get("stopped_at_time_limit"):
            break
    con.close()
    stats["seconds"] = round(time.time() - t0, 1)
    return stats


def load_ocr(con: sqlite3.Connection, sym: str) -> dict:
    """{doc_key: {page: (text, words, conf, method)}} of one symbol from an ocr_page table."""
    res: dict = {}
    try:
        cur = con.execute("SELECT doc_key, page, text, words_json, ocr_conf, method FROM ocr_page "
                          "WHERE symbol=? AND n_boxes>0", (sym,))
    except sqlite3.OperationalError:
        return res
    for doc_key, page, text, wj, conf, method in cur:
        res.setdefault(doc_key, {})[page] = (text, [tuple(w) for w in json.loads(wj)], conf, method)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default=None, help="default: the profile's companies, else the default database's")
    ap.add_argument("--sandbox-root", default=str(kpi.SANDBOX_ROOT))
    ap.add_argument("--raw-root", default=str(kpi.RAW_ROOT), help="'' to skip the decks_full PDFs")
    ap.add_argument("--pages-db", default=str(PAGES_DB), help="docs_collect pages.db: its needs_ocr pages are read too ('' disables)")
    ap.add_argument("--max-seconds", type=float, default=540)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--max-side", type=int, default=2400, help="longest side RapidOCR works at (the 300 DPI render is scaled down to it)")
    ap.add_argument("--reverse", action="store_true", help="work from the end of the pending list (second worker)")
    ap.add_argument("--device", choices=["cpu", "dml"], default="cpu")
    a = ap.parse_args(argv)
    stats = run(a.out, [s.strip().upper() for s in (a.symbols or ",".join(profile.symbols())).split(",") if s.strip()],
                Path(a.sandbox_root),
                Path(a.raw_root) if a.raw_root else None, a.max_seconds, a.limit, a.dpi, a.device, a.max_side, a.reverse,
                Path(a.pages_db) if a.pages_db else None)
    for k, v in stats.items():
        print(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
