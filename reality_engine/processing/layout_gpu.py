"""C1b: GPU layout detection for annual reports (GTX 1050 Ti, 4 GB).

Pipeline per PDF::

    triage (CPU, every page) -> render routed pages at 150 dpi ->
    DocLayout-YOLO (GPU, batches of 4) -> table cells (PyMuPDF find_tables,
    CPU) -> text from the PyMuPDF layer inside each box -> column reading
    order -> chunker_v2 blocks

Triage routes a page to the GPU only when it is one of: a table candidate
(three or more numeric rows), a two-column page, a page with an almost empty
text layer, or a deck slide.  Clean single-column prose stays on the CPU and
keeps the font-size heading rules, so the GPU is spent where structure is hard.

The DocStructBench weights are read from ``.tmp/c1b/models`` (downloaded once
from Hugging Face).  ``import torch`` happens before ``onnxruntime`` because
the CUDA 12 cuDNN 9 DLLs must load first; ``YOLO_CONFIG_DIR`` and
``MPLCONFIGDIR`` are pointed under ``.tmp/c1b`` before doclayout-yolo imports
matplotlib, otherwise it tries to write into AppData.

The table engine is PyMuPDF's cell grid (CPU).  RapidTable's SLANet-plus ONNX
weights are not bundled with the package -- its config points at ModelScope,
which is outside the allowed download list -- so it is not used here.
"""
from __future__ import annotations

import os
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
C1B = ROOT / ".tmp" / "c1b"
for folder in ("yolo", "mpl", "models"):
    (C1B / folder).mkdir(parents=True, exist_ok=True)
os.environ.setdefault("YOLO_CONFIG_DIR", str(C1B / "yolo"))
os.environ.setdefault("MPLCONFIGDIR", str(C1B / "mpl"))

import fitz  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402  (must precede onnxruntime)

from reality_engine.processing import chunker_v2 as cv  # noqa: E402

WEIGHTS = C1B / "models" / "doclayout_yolo_docstructbench_imgsz1024.pt"
DPI = 150
BATCH = int(os.environ.get("LAYOUT_BATCH", "4"))
CONF = 0.25
CLASSES = {
    0: "title", 1: "plain text", 2: "abandon", 3: "figure", 4: "figure_caption",
    5: "table", 6: "table_caption", 7: "table_footnote", 8: "isolate_formula",
    9: "formula_caption",
}
TABLE_CLASS = 5
DROP_CLASSES = {2, 8, 9}
NUM = cv._NUMERIC

_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        from doclayout_yolo import YOLOv10
        if not WEIGHTS.exists():
            raise FileNotFoundError(
                f"DocLayout-YOLO weights missing at {WEIGHTS}; download "
                "juliozhao/DocLayout-YOLO-DocStructBench")
        _MODEL = YOLOv10(str(WEIGHTS))
    return _MODEL


def vram_peak_mb() -> float:
    return round(torch.cuda.max_memory_allocated() / 2 ** 20, 1) if torch.cuda.is_available() else 0.0


def gpu_name() -> str:
    return torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

def _line_starts(page) -> list[tuple[float, float, float, float, str]]:
    out: list[tuple[float, float, float, float, str]] = []
    try:
        data = page.get_text("dict")
    except Exception:
        return out
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if len(text) >= 15:
                x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))
                out.append((x0, x1, y0, y1, text))
    return out


def _two_columns(page, text: str) -> bool:
    """True only when the page really is set in two columns.

    Round 2 counted any line starting left of 40% or right of 50% as a column,
    so indented bullets, address blocks and centred cover pages routed to the
    GPU (63% of AR pages).  A real two-column page has two dense columns of
    long lines that both run down the page, a wide gap between them, and a
    right column that reaches the right margin.
    """
    starts = _line_starts(page)
    if len(starts) < 12:
        return False
    width = page.rect.width or 1
    height = page.rect.height or 1
    left = [(x0, x1, y0, y1) for x0, x1, y0, y1, _ in starts
            if x0 < width * 0.3 and x1 < width * 0.56 and x1 - x0 > width * 0.22]
    right = [(x0, x1, y0, y1) for x0, x1, y0, y1, _ in starts
             if x0 >= width * 0.44 and x1 > width * 0.82 and x1 - x0 > width * 0.22]
    if len(left) < 6 or len(right) < 6:
        return False
    if len(right) < len(starts) * 0.3:
        return False
    median = statistics.median
    if median([x0 for x0, _, _, _ in right]) - median([x0 for x0, _, _, _ in left]) < width * 0.3:
        return False
    for column in (left, right):
        spread = max(y1 for _, _, _, y1 in column) - min(y0 for _, _, _, y0 in column)
        if spread < height * 0.3:
            return False
    return True


def _aligned_numeric_columns(page, rect, min_words: int = 2) -> int:
    """Number of x-aligned numeric columns inside ``rect``."""
    try:
        words = page.get_text("words", clip=rect)
    except Exception:
        return 0
    xs: list[float] = []
    for word in words:
        token = (word[4] or "").strip().strip("₹$()%.,;: ")
        if not token or not NUM.fullmatch(token):
            continue
        xs.append(float(word[0]))
    groups: list[list[float]] = []
    for x in sorted(xs):
        if groups and x - groups[-1][-1] <= 6:
            groups[-1].append(x)
        else:
            groups.append([x])
    return sum(1 for group in groups if len(group) >= min_words)


def _page_table_reason(page) -> str | None:
    """Three rows that each carry three numbers, else None.

    Deliberately cheap: PyMuPDF's full ``find_tables`` costs about a second on
    a dense AR page, so triage only looks at word positions.  Counting numeric
    words per y-row avoids the page-number/footer columns that a bare x-column
    check mistakes for a table.  The strict cell-grid test runs later, inside
    a YOLO table box.
    """
    try:
        words = page.get_text("words")
    except Exception:
        return None
    rows: dict[int, int] = {}
    total = 0
    for word in words:
        token = (word[4] or "").strip().strip("₹$()%.,;: ")
        if not token or not NUM.fullmatch(token):
            continue
        total += 1
        key = round(float(word[1]) / 6)
        rows[key] = rows.get(key, 0) + 1
    wide_rows = sum(1 for count in rows.values() if count >= 4)
    return "dense" if wide_rows >= 3 and total >= 18 else None


def triage(page, text: str, deck: bool = False) -> str | None:
    """Why this page needs the GPU, or None when the CPU path is enough.

    Two-column prose is no longer routed: the cheap column splitter in
    ``_font_blocks`` reads left then right with the font-size heading rules, so
    the GPU is spent on tables and near-empty (image/scan) pages only.
    """
    if deck:
        return "deck_slide"
    stripped = (text or "").strip()
    if len(stripped) < 40:
        return "near_empty_text"
    grid = _page_table_reason(page)
    if grid:
        return f"table_candidate_{grid}"
    return None


# ---------------------------------------------------------------------------
# Render + GPU detection
# ---------------------------------------------------------------------------

def _render(page) -> np.ndarray:
    pix = page.get_pixmap(dpi=DPI)
    array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return np.ascontiguousarray(array[:, :, :3])


def _detect(images: list[np.ndarray]) -> list[list[dict]]:
    model = _model()
    try:
        results = model.predict(images, imgsz=1024, conf=CONF, device="cuda:0", verbose=False)
    except Exception:
        results = [model.predict(image, imgsz=1024, conf=CONF, device="cuda:0",
                                 verbose=False)[0] for image in images]
    if not isinstance(results, (list, tuple)) or len(results) != len(images):
        results = [results]
    out: list[list[dict]] = []
    for result in results:
        boxes = result.boxes
        found = []
        for box in boxes:
            cls = int(box.cls)
            if cls in DROP_CLASSES:
                continue
            name = CLASSES.get(cls, str(cls))
            found.append({"cls": cls, "name": name,
                          "rect": [float(v) for v in box.xyxy[0].tolist()],
                          "conf": float(box.conf)})
        out.append(found)
    return out


def _dedupe(boxes: list[dict]) -> list[dict]:
    """Drop a box mostly covered by a bigger one (YOLO returns overlaps)."""
    ordered = sorted(boxes, key=lambda b: -(b["rect"][2] - b["rect"][0]) * (b["rect"][3] - b["rect"][1]))
    kept: list[dict] = []
    for box in ordered:
        x0, y0, x1, y1 = box["rect"]
        area = max(1.0, (x1 - x0) * (y1 - y0))
        covered = 0.0
        for other in kept:
            ox0, oy0, ox1, oy1 = other["rect"]
            ix0, iy0 = max(x0, ox0), max(y0, oy0)
            ix1, iy1 = min(x1, ox1), min(y1, oy1)
            if ix0 < ix1 and iy0 < iy1:
                covered = max(covered, (ix1 - ix0) * (iy1 - iy0) / area)
        if covered < 0.8:
            kept.append(box)
    return kept


def _reading_order(boxes: list[dict], width: float) -> list[dict]:
    if not boxes:
        return []
    full = [b for b in boxes if (b["rect"][2] - b["rect"][0]) > width * 0.7]
    left = [b for b in boxes if b not in full and b["rect"][0] < width * 0.45]
    right = [b for b in boxes if b not in full and b["rect"][0] >= width * 0.45]
    if len(left) >= 3 and len(right) >= 3:
        return (sorted(full, key=lambda b: b["rect"][1])
                + sorted(left, key=lambda b: b["rect"][1])
                + sorted(right, key=lambda b: b["rect"][1]))
    return sorted(boxes, key=lambda b: (b["rect"][1], b["rect"][0]))


# ---------------------------------------------------------------------------
# Tables + page text
# ---------------------------------------------------------------------------

def _grid_tables(page) -> list[tuple[fitz.Rect, list]]:
    """One ``find_tables`` pass per page, cached for every table box."""
    try:
        found = page.find_tables()
    except Exception:
        return []
    out: list[tuple[fitz.Rect, list]] = []
    for table in getattr(found, "tables", []):
        try:
            data = table.extract()
        except Exception:
            continue
        if len(data) < 2 or max((len(row) for row in data), default=0) < 2:
            continue
        out.append((fitz.Rect(table.bbox), data))
    return out


def _table_text(page, rect: fitz.Rect, stats: dict,
                page_tables: list[tuple[fitz.Rect, list]] | None = None
                ) -> tuple[str, bool]:
    """Table text plus whether this box really is a table.

    A YOLO ``table`` box is not evidence: round 2 counted 1,190 boxes over
    1,838 pages.  Keep the box as a table only when PyMuPDF finds a cell grid
    inside it or at least three x-aligned numeric columns; otherwise the box
    becomes ordinary text in the reading order.
    """
    rows_out: list[str] = []
    if page_tables is None:
        page_tables = _grid_tables(page)
    for table_rect, data in page_tables:
        cx = (table_rect.x0 + table_rect.x1) / 2
        cy = (table_rect.y0 + table_rect.y1) / 2
        if not (rect.x0 - 2 <= cx <= rect.x1 + 2 and rect.y0 - 2 <= cy <= rect.y1 + 2):
            continue
        for row in data:
            cells = [(cell or "").replace("\n", " ").strip() for cell in row]
            if any(cells):
                rows_out.append(" | ".join(cells))
    if rows_out:
        stats["table_cells"] = stats.get("table_cells", 0) + len(rows_out)
        stats["table_grid"] = stats.get("table_grid", 0) + 1
        return "\n".join(rows_out), True
    if _aligned_numeric_columns(page, rect, min_words=2) >= 3:
        stats["table_numeric"] = stats.get("table_numeric", 0) + 1
        return _clean(page.get_textbox(rect) or ""), True
    stats["table_rejected"] = stats.get("table_rejected", 0) + 1
    return _clean(page.get_textbox(rect) or ""), False


def _clean(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def _structured_page(page, boxes: list[dict], stats: dict) -> tuple[str, list[tuple[int, int, str]]]:
    scale = 72.0 / DPI
    width = page.rect.width
    boxes = _dedupe(boxes)
    for box in boxes:
        x0, y0, x1, y1 = box["rect"]
        box["rect"] = fitz.Rect(x0 * scale, y0 * scale, x1 * scale, y1 * scale) & page.rect
    boxes = _reading_order(boxes, width)
    lines: list[str] = []
    blocks: list[tuple[int, int, str]] = []
    pos = 0
    page_tables: list[tuple[fitz.Rect, list]] | None = None
    for box in boxes:
        rect = box["rect"]
        if rect.is_empty or rect.width < 4 or rect.height < 4:
            continue
        if box["cls"] == TABLE_CLASS:
            if page_tables is None:
                page_tables = _grid_tables(page)
            text, real = _table_text(page, rect, stats, page_tables)
            kind = "table" if real else "text"
            if real:
                stats["tables"] = stats.get("tables", 0) + 1
        else:
            text = _clean(page.get_textbox(rect) or "")
            kind = "heading" if box["cls"] == 0 else "text"
            if kind == "heading":
                stats["headings"] = stats.get("headings", 0) + 1
        if not text:
            continue
        lines.append(text)
        blocks.append((pos, pos + len(text), kind))
        pos += len(text) + 1
    return "\n".join(lines), blocks


def _dict_rows(page, clip=None) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    try:
        data = page.get_text("dict", clip=clip) if clip is not None else page.get_text("dict")
    except Exception:
        return rows
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if not text:
                continue
            size = max((span.get("size", 0.0) for span in line.get("spans", [])), default=0.0)
            rows.append((text, size))
    return rows


def _columns(page):
    """Left/right column rects when the page really has two text columns."""
    starts = _line_starts(page)
    width = page.rect.width or 1
    left_x1 = [x1 for x0, x1, _, _, _ in starts
               if x0 < width * 0.3 and x1 < width * 0.56 and x1 - x0 > width * 0.22]
    right_x0 = [x0 for x0, x1, _, _, _ in starts
                if x0 >= width * 0.44 and x1 > width * 0.82 and x1 - x0 > width * 0.22]
    if len(left_x1) < 6 or len(right_x0) < 6:
        return None
    gutter = (statistics.median(left_x1) + statistics.median(right_x0)) / 2
    if not width * 0.4 <= gutter <= width * 0.6:
        return None
    return (fitz.Rect(0, 0, gutter, page.rect.height),
            fitz.Rect(gutter, 0, width, page.rect.height))


def _font_blocks(page) -> tuple[str, list[tuple[int, int, str]]]:
    """Text + font-size heading blocks for a clean page (no GPU).

    A genuine two-column page is read left column then right column, which is
    the only ordering fix the GPU used to provide for prose.
    """
    rows: list[tuple[str, float]] = []
    text = page.get_text("text")
    if _two_columns(page, text):
        columns = _columns(page)
        if columns:
            rows = _dict_rows(page, columns[0]) + _dict_rows(page, columns[1])
    if not rows:
        rows = _dict_rows(page)
    sizes = [size for _, size in rows]
    body = statistics.median(sizes) if sizes else 10.0
    lines: list[str] = []
    blocks: list[tuple[int, int, str]] = []
    pos = 0
    for text, size in rows:
        kind = ("heading" if size > body * 1.15 and len(text) < 90
                and len(NUM.findall(text)) == 0 else "text")
        lines.append(text)
        blocks.append((pos, pos + len(text), kind))
        pos += len(text) + 1
    return "\n".join(lines), blocks


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_pdf(path, dpi: int = DPI, batch_size: int = BATCH,
              max_pages: int = 0, deck: bool = False
              ) -> tuple[list[str], list[cv.Block], dict]:
    """Structured page texts + chunker_v2 blocks for one PDF."""
    global DPI, BATCH
    DPI, BATCH = dpi, batch_size
    pages: list[str] = []
    blocks: list[cv.Block] = []
    stats = {"pages": 0, "routed": 0, "reasons": {}, "tables": 0,
             "headings": 0, "table_cells": 0, "table_text_fallback": 0,
             "gpu": gpu_name()}
    pending: list[tuple[int, object, str]] = []  # (page_index, page, reason)
    structured: dict[int, tuple[str, list[tuple[int, int, str]]]] = {}
    doc = fitz.open(path)

    def flush_batch() -> None:
        if not pending:
            return
        images = [_render(page) for _, page, _ in pending]
        detections = _detect(images)
        for (index, page, _reason), boxes in zip(pending, detections):
            text, kinded = _structured_page(page, boxes, stats)
            if not text.strip():
                text, kinded = _font_blocks(page)
                stats["empty_after_layout"] = stats.get("empty_after_layout", 0) + 1
            structured[index] = (text, kinded)
        pending.clear()

    for index, page in enumerate(doc):
        if max_pages and index >= max_pages:
            break
        raw = page.get_text("text")
        reason = triage(page, raw, deck)
        if os.environ.get("LAYOUT_DEBUG"):
            print(f"  page {index + 1}/{doc.page_count} -> {reason}", flush=True)
        if reason is None:
            structured[index] = _font_blocks(page)
        else:
            stats["routed"] += 1
            stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
            pending.append((index, page, reason))
            if len(pending) >= BATCH:
                flush_batch()
    flush_batch()
    doc.close()
    joined = 0
    for index in sorted(structured):
        text, kinded = structured[index]
        _emit(joined, text, kinded, blocks)
        pages.append(text)
        joined += len(text) + 1
    stats["pages"] = len(pages)
    return pages, blocks, stats


def _emit(page_start: int, text: str, kinded: list[tuple[int, int, str]],
          blocks: list[cv.Block]) -> None:
    for start, end, kind in kinded:
        blocks.append(cv.Block(page_start + start, page_start + end, kind,
                               1 if kind == "heading" else 0))


def inspect_pdf(path, page_numbers: set[int] | None = None, deck: bool = False,
                max_pages: int = 0) -> list[dict]:
    """Per-page routing decision + structured text (the hand-check helper)."""
    doc = fitz.open(path)
    out: list[dict] = []
    for index, page in enumerate(doc):
        if max_pages and index >= max_pages:
            break
        if page_numbers and (index + 1) not in page_numbers:
            continue
        raw = page.get_text("text")
        reason = triage(page, raw, deck)
        if reason is None:
            text, _ = _font_blocks(page)
            out.append({"page": index + 1, "reason": None, "text": text, "blocks": []})
            continue
        boxes = _detect([_render(page)])[0]
        stats: dict = {}
        text, kinded = _structured_page(page, boxes, stats)
        out.append({"page": index + 1, "reason": reason, "text": text,
                    "blocks": kinded, "tables": stats.get("tables", 0),
                    "headings": stats.get("headings", 0)})
    doc.close()
    return out
