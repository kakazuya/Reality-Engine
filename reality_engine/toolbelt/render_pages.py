"""Render PDF pages to PNG, or dump the text layer with the pipeline's low-text rule.

The deck reader (``extract_deck_figures.py``) renders each page to a longest side
of 1600 px (``MAX_SIDE``) at JPEG quality 85, and skips pages with fewer than 3
text-layer numbers and under 15% image coverage.  The AR pipeline treats a page
with under 40 characters as ``no_text`` (``ar_queue.page_kind`` and
``factor_loaders._MIN_TEXT_LAYER_CHARS``).  Both rules are reproduced here so a
worker sees the same routing the production pipelines would use.

Examples:
    python -m reality_engine.toolbelt.render_pages --pdf .tmp/x.pdf --pages 3,5-7 --dpi 150
    python -m reality_engine.toolbelt.render_pages --pdf .tmp/x.pdf --text --pages all

    from reality_engine.toolbelt.render_pages import render
    pages = render(".tmp/x.pdf", pages="1", dpi=150)["pages"]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from ._common import add_format, main_guard, parse_pages, print_result

# Source: reality_engine/scripts/extract_deck_figures.py (MAX_SIDE, JPEG_Q,
# GATE_TEXT_NUMBERS, GATE_IMG_COV) and ar_queue.page_kind (40-char floor).
DECK_MAX_SIDE = 1600
GATE_TEXT_NUMBERS = 3
GATE_IMG_COV = 0.15
MIN_TEXT_CHARS = 40
EXPECTED_CHARS_PER_SQ_IN = 15.0
DEFAULT_DPI = 150


def _pymupdf():
    try:
        import pymupdf  # type: ignore
    except ImportError:  # older installs expose the fitz name
        import fitz as pymupdf  # type: ignore
    return pymupdf


def _text_numbers(text: str) -> list[str]:
    """Numbers in the text layer, the reference the deck gate counts."""
    return re.findall(r"\d[\d,.]*", text or "")


def _page_geometry(page) -> tuple[float, float]:
    rect = page.rect
    return max(rect.width, 0.0), max(rect.height, 0.0)


def _image_coverage(page, pymupdf) -> float:
    rect = page.rect
    area = abs(rect) or 1.0
    img_area = sum(abs(pymupdf.Rect(info["bbox"]) & rect) for info in page.get_image_info())
    return min(1.0, img_area / area)


def _text_stats(page, pymupdf) -> dict[str, Any]:
    text = page.get_text() or ""
    chars = len(text.strip())
    width, height = _page_geometry(page)
    area_sq_in = max((width / 72.0) * (height / 72.0), 0.001)
    coverage = min(1.0, chars / (area_sq_in * EXPECTED_CHARS_PER_SQ_IN))
    numbers = _text_numbers(text)
    img_cov = _image_coverage(page, pymupdf)
    if len(numbers) >= GATE_TEXT_NUMBERS:
        deck_route = "vision"
    elif img_cov < GATE_IMG_COV:
        deck_route = "skip"  # text page with at most 2 numbers: nothing for a reader
    else:
        deck_route = "vision"  # deck OCR-gates here; without OCR, reading is the safe mirror
    return {
        "chars": chars,
        "text_coverage": round(coverage, 4),
        "low_text": chars < MIN_TEXT_CHARS,
        "text_numbers": len(numbers),
        "image_coverage": round(img_cov, 3),
        "deck_route": deck_route,
        "text": text,
    }


def render(pdf: str | Path, pages: str | None = None, dpi: int = DEFAULT_DPI,
           max_side: int = 0, out_dir: str | Path | None = None,
           text: bool = False) -> dict[str, Any]:
    """Render selected pages (or dump text); ``max_side`` overrides ``dpi`` when > 0."""
    if dpi < 1:
        raise ValueError("--dpi must be >= 1")
    pymupdf = _pymupdf()
    source = Path(pdf)
    if not source.exists():
        raise FileNotFoundError(f"PDF not found: {source}")
    out = Path(out_dir) if out_dir else Path(".tmp") / "render_pages"
    results: list[dict[str, Any]] = []
    with pymupdf.open(source) as doc:
        selected = parse_pages(pages, doc.page_count)
        for page_no in selected:
            page = doc[page_no - 1]
            if text:
                results.append({"page": page_no, **_text_stats(page, pymupdf)})
                continue
            if max_side > 0:
                width, height = _page_geometry(page)
                zoom = max_side / max(width, height, 1.0)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                used_dpi = round(72.0 * zoom, 1)
            else:
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                used_dpi = dpi
            out.mkdir(parents=True, exist_ok=True)
            target = out / f"{source.stem}_p{page_no}.png"
            target.write_bytes(pix.tobytes("png"))
            results.append({"page": page_no, "png": str(target), "width": pix.width,
                            "height": pix.height, "bytes": target.stat().st_size,
                            "dpi": used_dpi})
    return {"pdf": str(source), "text_mode": text, "dpi": dpi, "max_side": max_side,
            "pages": results}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m reality_engine.toolbelt.render_pages",
        description="Render PDF pages to PNG or dump text with a text_coverage score.")
    ap.add_argument("--pdf", required=True, help="PDF path")
    ap.add_argument("--pages", help="e.g. 3,5-7 or all (default: all)")
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI,
                    help=f"raster density (default: {DEFAULT_DPI}; deck pipeline caps the longest side at 1600 px)")
    ap.add_argument("--max-side", type=int, default=0,
                    help=f"cap the longest side in px ({DECK_MAX_SIDE} reproduces the deck renderer)")
    ap.add_argument("--out", help="PNG output directory (default: .tmp/render_pages)")
    ap.add_argument("--text", action="store_true", help="dump the text layer instead of rendering")
    add_format(ap)
    args = ap.parse_args(argv)
    result = render(args.pdf, args.pages, args.dpi, args.max_side, args.out, args.text)
    print_result(result, args.format,
                 columns=["page", "png", "width", "height", "bytes", "chars",
                          "text_coverage", "low_text", "deck_route"])
    return 0


if __name__ == "__main__":
    main_guard(main)
