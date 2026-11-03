"""Local OCR of the pages that have no text layer -> table ocr_page (T-049 E). RapidOCR (ONNX) only: no model call, no network.

CLI: python -m reality_engine.pilot3.ocr --out <ocr.db> [--symbols KEC,BAJFINANCE,HINDALCO] [--max-seconds 540] [--limit N]
                                          [--dpi 300] [--max-side 2400] [--device cpu|dml]

Pages come from the same two places kpi.py reads: sandbox ``doc_text`` rows with method needs_ocr (PDF under
``<sym>_loop/raw``), and the decks_full PDFs that deck_figures cites but docs does not hold, for pages whose text layer
is empty.  Each page is rendered at 300 DPI in grayscale (PyMuPDF), read by RapidOCR, and stored with the page text, the
word boxes in PDF points (so kpi.py's row/column tolerances behave as on a text layer) and the mean OCR confidence.
The run is resumable: pages already in ``ocr_page`` are skipped, ``--max-seconds`` stops cleanly between pages.
``method`` is ``ocr_rapid``; kpi.py copies it and ``ocr_conf`` onto every kpi_series row read from such a page.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from reality_engine.pilot3 import kpi

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


def pending(sym: str, sandbox: Path, raw_root: Path | None, done: set) -> list[tuple]:
    """[(doc_key, page, doc_type, known_at, pdf_path)] still to OCR: decks_full first, then sandbox pages by doc type
    (decks, results, press releases, ...) newest first."""
    fitz = _fitz()
    dbp = sandbox / f"{kpi.COMPANIES[sym]}_loop" / f"{kpi.COMPANIES[sym]}.db"
    con = sqlite3.connect(f"file:{dbp.as_posix()}?mode=ro", uri=True)
    out = []
    # 1) decks the sandbox does not hold (FY25-FY27 presentations): empty text-layer pages
    if raw_root is not None:
        held = {r[0] for r in con.execute("SELECT source_key FROM docs WHERE source_key IS NOT NULL")}
        for sha, known_at in con.execute("SELECT sha256, min(known_at) FROM deck_figures GROUP BY sha256 ORDER BY 2 DESC"):
            if sha in held:
                continue
            path = raw_root / "decks_full" / sha[:2] / f"{sha}.pdf"
            if not path.exists():
                continue
            key = f"decks_full/{sha[:2]}/{sha}.pdf"
            try:
                pdf = fitz.open(str(path))
            except Exception:
                continue
            for i in range(pdf.page_count):
                if (key, i + 1) not in done and len(pdf[i].get_text("text").strip()) < 20:
                    out.append((key, i + 1, "deck", known_at, path))
            pdf.close()
    # 2) sandbox pages that doc_text marked needs_ocr
    rows = con.execute(
        f"SELECT t.doc_key, t.page, d.doc_type, d.known_at FROM doc_text t JOIN docs d USING(doc_key) "
        f"WHERE t.method='needs_ocr' AND d.doc_type IN ({','.join('?' * len(kpi.KPI_DOC_TYPES))})",
        kpi.KPI_DOC_TYPES).fetchall()
    rows.sort(key=lambda r: (DOC_PRIORITY.get(r[2], 9), -int(str(r[3] or "0")[:10].replace("-", "") or 0), r[0], r[1]))
    for doc_key, page, doc_type, known_at in rows:
        p = sandbox / f"{kpi.COMPANIES[sym]}_loop" / "raw" / doc_key
        if p.exists() and (doc_key, page) not in done:
            out.append((doc_key, page, doc_type, known_at, p))
    con.close()
    return out


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
        dpi: int, device: str, max_side: int = 2400, reverse: bool = False) -> dict:
    fitz = _fitz()
    t0 = time.time()
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    stats: dict = {}
    for sym in symbols:
        done = {(r[0], r[1]) for r in con.execute("SELECT doc_key, page FROM ocr_page WHERE symbol=?", (sym,))}
        todo = pending(sym, sandbox, raw_root, done)
        st = stats.setdefault(sym, {"pending_at_start": len(todo), "done": 0, "seconds_ocr": 0.0, "boxes": 0, "empty": 0})
        if reverse:      # a second worker starting from the other end of the list (own --out db, merge afterwards)
            todo.reverse()
        if limit:
            todo = todo[:limit]
        pdf, pdf_path = None, None
        for doc_key, page, doc_type, known_at, path in todo:
            if time.time() - t0 > max_seconds:
                stats["stopped_at_time_limit"] = True
                break
            try:
                if pdf_path != path:
                    if pdf is not None:
                        pdf.close()
                    pdf, pdf_path = fitz.open(str(path)), path
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
    """{doc_key: {page: (text, words, conf)}} of one symbol from an ocr_page table."""
    res: dict = {}
    try:
        cur = con.execute("SELECT doc_key, page, text, words_json, ocr_conf FROM ocr_page WHERE symbol=? AND n_boxes>0", (sym,))
    except sqlite3.OperationalError:
        return res
    for doc_key, page, text, wj, conf in cur:
        res.setdefault(doc_key, {})[page] = (text, [tuple(w) for w in json.loads(wj)], conf)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default="KEC,BAJFINANCE,HINDALCO")
    ap.add_argument("--sandbox-root", default=str(kpi.SANDBOX_ROOT))
    ap.add_argument("--raw-root", default=str(kpi.RAW_ROOT), help="'' to skip the decks_full PDFs")
    ap.add_argument("--max-seconds", type=float, default=540)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--max-side", type=int, default=2400, help="longest side RapidOCR works at (the 300 DPI render is scaled down to it)")
    ap.add_argument("--reverse", action="store_true", help="work from the end of the pending list (second worker)")
    ap.add_argument("--device", choices=["cpu", "dml"], default="cpu")
    a = ap.parse_args(argv)
    stats = run(a.out, [s.strip().upper() for s in a.symbols.split(",") if s.strip()], Path(a.sandbox_root),
                Path(a.raw_root) if a.raw_root else None, a.max_seconds, a.limit, a.dpi, a.device, a.max_side, a.reverse)
    for k, v in stats.items():
        print(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
