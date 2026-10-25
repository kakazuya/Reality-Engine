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

def _line_starts(page) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    try:
        data = page.get_text("dict")
    except Exception:
        return out
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if len(text) >= 15:
                out.append((line.get("bbox", (0, 0, 0, 0))[0], text))
    return out


def _two_columns(page, text: str) -> bool:
    starts = _line_starts(page)
    if len(starts) < 10:
        return False
    width = page.rect.width or 1
    left = sum(1 for x0, _ in starts if x0 < width * 0.4)
    right = sum(1 for x0, _ in starts if x0 > width * 0.5)
    return left >= 4 and right >= 4 and right >= len(starts) * 0.15


def triage(page, text: str, deck: bool = False) -> str | None:
    """Why this page needs the GPU, or None for clean single-column prose."""
    if deck:
        return "deck_slide"
    stripped = (text or "").strip()
    if len(stripped) < 40:
        return "near_empty_text"
    if _two_columns(page, stripped):
        return "two_columns"
    dense = sum(1 for line in stripped.splitlines()
                if len(NUM.findall(line)) >= 3)
    if dense >= 3:
        return "table_candidate"
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

def _table_text(page, rect: fitz.Rect, stats: dict) -> str:
    rows_out: list[str] = []
    try:
        found = page.find_tables(clip=rect)
        tables = list(getattr(found, "tables", []))
    except Exception:
        tables = []
    for table in tables:
        try:
            data = table.extract()
        except Exception:
            continue
        for row in data:
            cells = [(cell or "").replace("\n", " ").strip() for cell in row]
            if any(cells):
                rows_out.append(" | ".join(cells))
    if rows_out:
        stats["table_cells"] = stats.get("table_cells", 0) + len(rows_out)
        return "\n".join(rows_out)
    stats["table_text_fallback"] = stats.get("table_text_fallback", 0) + 1
    return page.get_textbox(rect) or ""


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
    for box in boxes:
        rect = box["rect"]
        if rect.is_empty or rect.width < 4 or rect.height < 4:
            continue
        if box["cls"] == TABLE_CLASS:
            text = _clean(_table_text(page, rect, stats))
            kind = "table"
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


def _font_blocks(page) -> tuple[str, list[tuple[int, int, str]]]:
    """Text + font-size heading blocks for a clean page (no GPU)."""
    try:
        data = page.get_text("dict")
    except Exception:
        return "", []
    rows: list[tuple[str, float]] = []
    sizes: list[float] = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if not text:
                continue
            size = max((span.get("size", 0.0) for span in line.get("spans", [])), default=0.0)
            sizes.append(size)
            rows.append((text, size))
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
