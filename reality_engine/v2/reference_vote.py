"""T-177: settle reference cells by a vote of several readers, matching on row label and value, not on exact text.

``reference_pages reconcile`` keys a cell on the exact table title, row label and column header text, so two readers
that copy the same grid but write "31st March, 2022" and "31 March, 2022" agree on nothing (24% agreed on the 60-page
run).  Readers also emit a grid in different orders (row by row, or column by column), so position in the reply is
not a key either.  Here a cell is (row label reduced to letters and digits with any leading "(a)" / "1." dropped,
value, n-th time that value occurs under that label).  A cell is settled by script when at least two readers give it
and the value is printed in the page text layer.  A value that two readers give under DIFFERENT row labels in the
same column is marked ``label_dispute``: the number is on the page but its row is not agreed, so it is read by hand.

    python -m reality_engine.v2.reference_vote --pages <pages.csv> --runs <dirA> <dirB> [<dirC> ...] --out <dir>

Writes ``reference_cells.csv`` (page_id, split, row_label, col_header, value_text, unit_text, readers, agree_n,
verbatim, label_dispute, settled_by) and ``disputes.csv`` (the cells not settled, with the labels each reader gave).
No model call; reads the saved ``p*.rows.json`` of each run.
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from reality_engine.v2.reference_pages import _load_pages_csv, _load_run_rows, _norm_space, _norm_value, _page_text_for

CELL_COLS = ["page_id", "split", "row_label", "col_header", "value_text", "unit_text", "readers", "agree_n",
             "verbatim", "label_dispute", "settled_by"]
_ENUM = re.compile(r"^\s*(?:\(?[a-z]{1,2}\)|\(?[ivx]{1,4}\)|\(?\d{1,2}\)|\d{1,2}\.|[a-z]\.)\s+", re.I)
_ORDINAL = re.compile(r"(?<=\d)(st|nd|rd|th)\b", re.I)


def label_key(label: Any) -> str:
    """Row label without a leading enumerator, reduced to lower-case letters and digits."""
    text = _ENUM.sub("", str(label or ""), count=1)
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def col_key(header: Any) -> str:
    """Column header without brackets, ordinal suffixes or punctuation ("31st March, 2022 (Audited)" = "31 March 2022")."""
    text = re.sub(r"\([^)]*\)", " ", str(header or ""))
    text = _ORDINAL.sub("", text)
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def cells_of(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """A reader's located cells; rows with no table, label or header (prose, a chart) are never reference cells."""
    seen: Counter[tuple[str, str]] = Counter()
    out = []
    for r in rows:
        if not any(_norm_space(r.get(k)) for k in ("table", "row_label", "col_header")):
            continue
        norm = _norm_value(r.get("value"))
        if not norm:
            continue
        lk = label_key(r.get("row_label"))
        seen[(lk, norm)] += 1
        out.append({"key": (lk, norm, seen[(lk, norm)]), "lk": lk, "ck": col_key(r.get("col_header")), "norm": norm,
                    "label": _norm_space(r.get("row_label")), "col": _norm_space(r.get("col_header")),
                    "value": _norm_space(r.get("value")), "unit": _norm_space(r.get("unit"))})
    return out


def is_verbatim(value: str, text_norm: str, text_nocomma: str) -> bool:
    v = _norm_space(value).casefold()
    if not v:
        return False
    return v in text_norm or v.replace(",", "") in text_nocomma


def vote_page(readers: list[list[dict[str, str]]], text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text_norm = _norm_space(text).casefold()
    text_nocomma = text_norm.replace(",", "")
    per_reader = [cells_of(r) for r in readers]
    answering = sum(1 for cells in per_reader if cells)
    holders: dict[tuple[str, str, int], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    order: list[tuple[str, str, int]] = []
    by_value: dict[tuple[str, str], set[tuple[int, str]]] = defaultdict(set)   # (value, column) -> {(reader, label)}
    for ri, cells in enumerate(per_reader):
        for c in cells:
            if c["key"] not in holders:
                order.append(c["key"])
            holders[c["key"]].append((ri, c))
            by_value[(c["norm"], c["ck"])].add((ri, c["lk"]))
    cells_out, disputes = [], []
    for key in order:
        given = holders[key]
        pick = given[0][1]
        agree_n = len({ri for ri, _ in given})
        verbatim = is_verbatim(pick["value"], text_norm, text_nocomma)
        others = {(ri, lk) for ri, lk in by_value[(pick["norm"], pick["ck"])] if lk != pick["lk"]}
        label_dispute = agree_n < 2 and any(ri not in {g for g, _ in given} for ri, _ in others)
        settled = "script" if agree_n >= 2 and verbatim else ""
        cell = {"row_label": pick["label"], "col_header": pick["col"], "value_text": pick["value"],
                "unit_text": pick["unit"], "readers": answering, "agree_n": agree_n, "verbatim": verbatim,
                "label_dispute": label_dispute, "settled_by": settled}
        cells_out.append(cell)
        if not settled:
            disputes.append({**cell, **{f"reader_{ri}": c["label"] for ri, c in given}})
    return cells_out, disputes


def run(pages_csv: Path, runs: list[Path], out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    all_cells, all_disputes, per_page = [], [], []
    for meta in _load_pages_csv(pages_csv):
        pid = meta["page_id"]
        text = _page_text_for(meta["store"], meta["doc key"], int(meta["page"]))
        cells, disputes = vote_page([_load_run_rows(r, pid) for r in runs], text)
        all_cells += [{"page_id": pid, "split": meta.get("split", ""), **row} for row in cells]
        all_disputes += [{"page_id": pid, "split": meta.get("split", ""), **row} for row in disputes]
        per_page.append((pid, meta.get("doc type", ""), meta.get("stratum", ""), len(cells),
                         sum(1 for c in cells if c["settled_by"]), sum(1 for c in cells if c["label_dispute"])))
    with open(out / "reference_cells.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CELL_COLS)
        w.writeheader()
        w.writerows(all_cells)
    with open(out / "disputes.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CELL_COLS + [f"reader_{i}" for i in range(len(runs))], restval="")
        w.writeheader()
        w.writerows(all_disputes)
    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for _pid, dtype, _stratum, n, settled, _ld in per_page:
        by_type[dtype][0] += 1
        by_type[dtype][1] += n
        by_type[dtype][2] += settled
    return {"pages": len(per_page), "pages_with_cells": sum(1 for p in per_page if p[3]), "cells": len(all_cells),
            "settled": sum(1 for c in all_cells if c["settled_by"]),
            "agree2": sum(1 for c in all_cells if c["agree_n"] >= 2),
            "verbatim": sum(1 for c in all_cells if c["verbatim"]),
            "label_dispute": sum(1 for c in all_cells if c["label_dispute"]), "disputes": len(all_disputes),
            "by_type": dict(by_type),
            "low_pages": sorted((p for p in per_page if p[3] and p[4] / p[3] < 0.6), key=lambda p: p[4] / p[3])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="T-177: settle reference cells by a vote of readers")
    ap.add_argument("--pages", required=True, type=Path)
    ap.add_argument("--runs", nargs="+", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    s = run(args.pages, args.runs, args.out)
    print(f"pages {s['pages']} (with cells {s['pages_with_cells']}), cells {s['cells']}, two or more readers agree "
          f"{s['agree2']}, verbatim {s['verbatim']}, settled by script {s['settled']}, label disputes "
          f"{s['label_dispute']}, disputes {s['disputes']}")
    for dtype, (n, cells, settled) in sorted(s["by_type"].items()):
        print(f"  {dtype}: pages {n}, cells {cells}, settled {settled}")
    for pid, dtype, stratum, n, settled, ld in s["low_pages"]:
        print(f"  low: {pid} {dtype} {stratum} cells {n} settled {settled} label_disputes {ld}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
