"""T-132 round 2: draw a random cell sample from a v2 table store for manual grading.

    python -m reality_engine.v2.cell_sample --store-dir <dir> --n 100 \
        --type deck|results --seed 9 --out .tmp/sample_deck.csv

Writes one row per sampled cell with the document, page, row label, column header, period, the
printed and scaled value, the unit, the extraction method ('text_layer' or 'text_layer;delta' for
a difference/growth column) and a 300-character snippet of the page text around the printed
value so a reviewer can grade the cell without opening the PDF.
"""
from __future__ import annotations

import argparse
import csv
import random
import re
from pathlib import Path
from typing import Any

import pymupdf

from reality_engine.db.readonly import connect_ro

__all__ = ["load_cells", "write_sample", "main"]

_COLUMNS = ("doc", "page", "label", "header", "period_id", "value_text",
            "unit_text", "scale", "value", "method", "snippet")
_SQL = (
    "SELECT c.doc_key, c.page, c.row_label, c.col_header, c.period_id, c.value_text, "
    "c.unit_text, c.scale, c.value, c.method, d.source_key "
    "FROM table_cell c JOIN doc d ON d.doc_key = c.doc_key "
    "WHERE d.doc_type = ? AND c.value IS NOT NULL")


def load_cells(store_dir: Path, doc_type: str) -> list[dict[str, Any]]:
    """Every cell of one document type with a parsed value, from every company file."""
    cells: list[dict[str, Any]] = []
    for path in sorted((store_dir / "company").glob("*.db")):
        conn = connect_ro(path)
        try:
            cursor = conn.execute(_SQL, (doc_type,))
            rows = list(cursor) if cursor is not None else []
            for row in rows:
                values = tuple(row) if row is not None else ()
                cells.append(dict(zip(
                    ("doc_key", "page", "label", "header", "period_id", "value_text",
                     "unit_text", "scale", "value", "method", "source_key"), values)))
        finally:
            conn.close()
    return cells


def _snippet(page: Any, value_text: str, width: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(page.get_text("text"))).strip()
    if not value_text:
        return text[:width]
    index = text.find(value_text)
    if index < 0:
        return text[:width]
    start = max(0, index - (width - len(value_text)) // 2)
    return text[start:start + width]


def write_sample(cells: list[dict[str, Any]], out: Path, n: int = 100,
                 seed: int = 9) -> list[dict[str, Any]]:
    """Draw ``n`` cells with a fixed seed and write them to ``out`` as CSV."""
    rows = random.Random(seed).sample(cells, min(n, len(cells)))
    texts: dict[tuple[str, int], str] = {}
    for row in rows:
        key = (str(row["doc_key"]), int(row["page"]))
        if key not in texts:
            snippet = ""
            source = row.get("source_key")
            if source and Path(str(source)).is_file():
                try:
                    with pymupdf.open(str(source)) as document:
                        if 0 < key[1] <= len(document):
                            snippet = _snippet(document[key[1] - 1], str(row["value_text"]))
                except Exception:                     # a missing or broken PDF gives no snippet
                    snippet = ""
            texts[key] = snippet
        row["snippet"] = texts[key]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_COLUMNS)
        for row in rows:
            writer.writerow([row["doc_key"], row["page"], row["label"], row["header"],
                             row["period_id"], row["value_text"], row["unit_text"],
                             row["scale"], row["value"], row.get("method", "text_layer"),
                             row["snippet"]])
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sample cells from a v2 table store")
    parser.add_argument("--store-dir", required=True, type=Path)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--type", required=True, choices=("deck", "results"))
    parser.add_argument("--seed", type=int, default=9)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    cells = load_cells(args.store_dir, args.type)
    rows = write_sample(cells, args.out, args.n, args.seed)
    documents = len({row["doc_key"] for row in rows})
    print(f"{args.type}: sampled {len(rows)} of {len(cells):,} cells "
          f"from {documents} documents -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
