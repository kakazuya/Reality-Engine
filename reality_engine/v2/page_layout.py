"""Page text laid out as printed, from word boxes (T-180): one output line per printed line, horizontal position
kept, so a reader sees which number sits on which row and under which column.

The PDF text layer in reading order lists a results table column by column (every row label, then each column of
numbers), so a blank cell shifts every later number one row and two readers can make the same shift.  Word boxes
carry the geometry; this module turns them into a fixed-width rendering:

    Revenue from Operations              204089     189640     391298
    Exceptional items (Refer Note 4)          -          -      12345

Sources of word boxes: the PDF text layer (``reference_geom.page_words``, sideways pages turned upright) or OCR
word boxes in PDF points (``ocr_page``), so text-layer and image-only pages reach the reader the same way.

    python -m reality_engine.v2.page_layout <one-page.pdf> [--width 180]
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

from reality_engine.v2.reference_geom import lines_of, page_words

Word = tuple[float, float, float, float, str]


def layout_text(words: list[Word], width: int = 180) -> str:
    """Fixed-width text: each word starts at the column its left edge maps to (at least one space after the
    previous word on the line); blank lines mark vertical gaps larger than two line heights."""
    if not words:
        return ""
    left = min(w[0] for w in words)
    right = max(w[2] for w in words)
    widths = [(w[2] - w[0]) / max(len(w[4]), 1) for w in words if w[4].strip()]
    char_w = max(statistics.median(widths) if widths else 5.0, (right - left) / width)
    out: list[str] = []
    prev_bottom = None
    for line in lines_of(words):
        top = min(words[i][1] for i in line)
        height = max(words[i][3] - words[i][1] for i in line)
        if prev_bottom is not None and top - prev_bottom > 2 * max(height, 4.0):
            out.append("")
        text = ""
        for i in line:
            col = int(round((words[i][0] - left) / char_w))
            text += " " * max(col - len(text), 1 if text else 0) + words[i][4]
        out.append(text.rstrip())
        prev_bottom = max(words[i][3] for i in line)
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="print a one-page PDF laid out as printed")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--width", type=int, default=180)
    args = ap.parse_args(argv)
    text = layout_text(page_words(args.pdf), args.width)
    # A cp1252 console cannot print the rupee sign a page prints: write UTF-8 to the same stream (T-188).
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
