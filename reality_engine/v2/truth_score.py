"""Hand-read truth against reader runs and the position check (Shivam, 11 Nov 2026).

A person (or Opus, reading the page image and the text layer together) writes the page's figures in the reader's grid
format (``reference_pages.GRID_PROMPT``): ``TABLE:`` / ``UNIT:`` / ``COLUMNS:`` and one line per printed row.  A page
with no figures holds only ``#`` comment lines.  This module then measures, per reader run:

* precision: reader cells that match a truth cell (same value; label the same row; column compatible) over all reader
  cells that carry a figure;
* recall: truth cells that some reader cell matches, over truth cells;
* the position check against the truth, cell by cell: confirmed-and-right, confirmed-but-wrong (the check passed a
  wrong cell), unconfirmed-but-right (a checker miss), unconfirmed-and-wrong (the check rightly held it back).

That last table answers "how much of the gap is the reader and how much is the checker".

    python -m reality_engine.v2.truth_score --truth <dir of <page_id>.truth.txt> --pdf-pages <dir> \
        --runs <run dir> [...] [--out <csv>]
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path
from typing import Any

from reality_engine.v2.reference_geom import page_words, settle_page
from reality_engine.v2.reference_pages import _load_run_rows, _norm_value, parse_grid
from reality_engine.v2.reference_vote import label_key, same_label

_TOKEN = re.compile(r"[a-z]+|\d+")


def truth_cells(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    return [r for r in parse_grid("\n".join(line for line in text.splitlines() if not line.startswith("#")))]


def _col_ok(reader_col: str, truth_col: str) -> bool:
    """Column compatible: every digit token of the truth header's last level is in the reader header, and when the
    truth header has a last-level word ('India SA', 'Total'), the reader header names it too."""
    t_last = truth_col.split(">")[-1].casefold()
    r = set(_TOKEN.findall(reader_col.casefold()))
    t_digits = {t for t in _TOKEN.findall(t_last) if t.isdigit()}
    t_words = {t for t in _TOKEN.findall(t_last) if not t.isdigit() and len(t) > 1}
    if t_digits and not t_digits <= r:
        return False
    if t_words and not (t_words & r):
        return False
    t_upper = {t for t in _TOKEN.findall(truth_col.casefold()) if t.isdigit()}
    return not (t_upper and r & {t for t in _TOKEN.findall(reader_col.casefold()) if t.isdigit()} and not t_upper & r)


def _label_ok(reader_label: str, truth_label: str) -> bool:
    a, b = label_key(reader_label), label_key(truth_label)
    if not a or not b:
        return False
    return a == b or same_label(a, b) or (len(a) >= 4 and (b.endswith(a) or a.endswith(b)))


def match(cell: dict[str, str], truth: list[dict[str, str]], used: set[int]) -> int | None:
    v = _norm_value(cell.get("value") or cell.get("value_text"))
    lab = cell.get("row_label", "")
    col = cell.get("col_header", "")
    for i, t in enumerate(truth):
        if i in used or _norm_value(t["value"]) != v:
            continue
        if _label_ok(lab, t["row_label"]) and _col_ok(col, t["col_header"]):
            return i
        if _label_ok(col, t["row_label"]) and _col_ok(lab, t["col_header"]):     # a transposed table: same cell
            return i
    return None


_SERIAL = re.compile(r"^\s*(s\.?\s*no|sl\.?\s*no|sr\.?\s*no|serial|number|no\.?)(\W|$)", re.I)


def wrong_kind(cell: dict[str, str], truth: list[dict[str, str]]) -> str:
    """Why a reader cell is wrong: not a figure (a serial number, a sentence), the row label lost, the value misread
    (not a truth value at all), or the right value under the wrong row or column."""
    value = cell.get("value") or ""
    if len(value) > 24 or _SERIAL.match(cell.get("col_header") or "") or _SERIAL.match(cell.get("row_label") or ""):
        return "not_a_figure"
    v = _norm_value(value)
    same = [t for t in truth if _norm_value(t["value"]) == v]
    if not same:
        return "value_misread"
    if not (cell.get("row_label") or "").strip():
        return "label_missing"
    return "wrong_row_or_column"


def score_page(rows: list[dict[str, str]], truth: list[dict[str, str]], words: Any) -> Counter:
    c: Counter = Counter()
    figures = [r for r in rows if any(ch.isdigit() for ch in (r.get("value") or ""))]
    cells, _unread = settle_page([figures], words)
    confirmed = {(x["row_label"], x["col_header"], _norm_value(x["value_text"])) for x in cells
                 if x["settled_by"] == "position"}
    used: set[int] = set()
    for r in figures:
        hit = match(r, truth, used)
        right = hit is not None
        if right:
            used.add(hit)
        conf = (r["row_label"], r["col_header"], _norm_value(r["value"])) in confirmed
        c["cells"] += 1
        c["right"] += right
        if not right:
            c["wrong_" + wrong_kind(r, truth)] += 1
        c[("confirmed" if conf else "unconfirmed") + ("_right" if right else "_wrong")] += 1
    c["truth"] += len(truth)
    c["found"] += len(used)
    return c


def run(truth_dir: Path, pdf_pages: Path, runs: list[Path]) -> list[dict[str, Any]]:
    out = []
    pages = sorted(p.name.split(".")[0] for p in truth_dir.glob("*.truth.txt"))
    for rd in runs:
        tot: Counter = Counter()
        for pid in pages:
            truth = truth_cells(truth_dir / f"{pid}.truth.txt")
            pdf = pdf_pages / f"{pid}.pdf"
            c = score_page(_load_run_rows(rd, pid), truth, page_words(pdf) if pdf.exists() else None)
            tot.update(c)
            out.append({"run": rd.name, "page": pid, **{k: c[k] for k in KEYS}})
        out.append({"run": rd.name, "page": "ALL", **{k: tot[k] for k in KEYS}})
    return out


KEYS = ["truth", "cells", "right", "found", "confirmed_right", "confirmed_wrong", "unconfirmed_right", "unconfirmed_wrong",
        "wrong_not_a_figure", "wrong_value_misread", "wrong_label_missing", "wrong_wrong_row_or_column"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="hand-read truth vs reader runs and the position check")
    ap.add_argument("--truth", required=True, type=Path)
    ap.add_argument("--pdf-pages", required=True, type=Path)
    ap.add_argument("--runs", nargs="+", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    rows = run(a.truth, a.pdf_pages, a.runs)
    if a.out:
        with a.out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["run", "page"] + KEYS)
            w.writeheader()
            w.writerows(rows)
    for r in rows:
        if r["page"] != "ALL":
            continue
        cells = r["cells"] or 1
        conf = r["confirmed_right"] + r["confirmed_wrong"]
        print(f"{r['run']:22} precision {r['right']}/{r['cells']} = {r['right'] / cells:.1%}  recall {r['found']}/{r['truth']}"
              f" = {r['found'] / (r['truth'] or 1):.1%}  | confirmed {conf}: wrong {r['confirmed_wrong']}"
              f" | unconfirmed {r['unconfirmed_right'] + r['unconfirmed_wrong']}: right (checker miss)"
              f" {r['unconfirmed_right']}, wrong {r['unconfirmed_wrong']} | wrong by kind: not a figure "
              f"{r['wrong_not_a_figure']}, misread {r['wrong_value_misread']}, label lost {r['wrong_label_missing']}, "
              f"row/column {r['wrong_wrong_row_or_column']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
