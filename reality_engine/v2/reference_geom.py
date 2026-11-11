"""T-177: settle reference cells by where the value is printed, not only by how many readers agree.

A text-only reader gets the page in reading order.  On a results page that order is column-major (every row label,
then a column of numbers), so a blank cell shifts every later number one row down and two readers can make the
same shift ("Exceptional items 45271" on a page where that cell is blank).  A vote cannot see that; the PDF can:
each printed word has a box.  Here every reader cell (row label, column header, value) is placed on the page:

* **row**: the value's word sits on a line whose text to its left spells the row label (also one line above or
  below it for a wrapped label);
* **column**: a word of the column header that carries a digit ("30.09.2025", "FY23"), else any header word, is
  printed above the value and overlaps it horizontally.

A cell is settled when its row is confirmed by position and no check contradicts it:

    script+position   two or more readers gave it and the row is confirmed
    position          one reader gave it, row and column both confirmed
    script            two or more readers gave it, the label or value could not be located (a chart, a scan)
    (empty)           not settled: ``conflict`` names why (row_elsewhere, column_elsewhere, lone_unlocated ...)

    python -m reality_engine.v2.reference_geom --pages <pages.csv> --pdf-pages <dir of p001.pdf ...> \
        --runs <dirA> <dirB> [...] --out <dir>

``--pdf-pages`` holds one single-page PDF per ``page_id``.  Writes ``reference_cells.csv`` (one row per printed
cell where placed, else per reader cell), ``unread_numbers.csv`` (numbers printed in a table column, on a labelled
line, that no reader gave) and prints the counts.  No model call.
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from reality_engine.v2.reference_pages import _load_pages_csv, _load_run_rows, _norm_space, _norm_value
from reality_engine.v2.reference_vote import cells_of, label_key, same_label, unify_labels

COLS = ["page_id", "split", "row_label", "col_header", "value_text", "unit_text", "readers", "agree_n", "row_ok",
        "col_ok", "settled_by", "conflict", "label_aliases", "col_aliases", "line_text", "x0", "y0", "x1", "y1"]
_NUM = re.compile(r"^[-(]?[\d,]*\d(?:\.\d+)?\)?[%x]?$")
_STRIP = "*†‡#^~`₹$€£:;|"


def word_value(text: str) -> str:
    """A printed word as a value key: braces read as brackets ("{367)"), marks and currency signs dropped."""
    t = str(text or "").strip().strip(_STRIP).replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    return _norm_value(t)


_BLANK = {"-", "--", "–", "—", "nil", "na", "n.a.", "n/a", "nm"}


def _is_num(text: str) -> bool:
    """A number, or the mark a table prints in an empty cell."""
    t = str(text or "").strip().casefold()
    return t in _BLANK or bool(_NUM.match(word_value(text).replace("-", "", 1) or "x"))


def page_words(pdf: Path) -> list[tuple[float, float, float, float, str]]:
    """Word boxes in reading axes (delegates to page_words.pdf_words for page 1)."""
    from reality_engine.v2 import page_words as _pw

    return _pw.pdf_words(pdf, 1)


def lines_of(words: list[tuple[float, float, float, float, str]]) -> list[list[int]]:
    """Word indexes grouped into printed lines (same vertical centre within half a word height), left to right."""
    order = sorted(range(len(words)), key=lambda i: ((words[i][1] + words[i][3]) / 2, words[i][0]))
    lines: list[list[int]] = []
    centre = height = 0.0
    for i in order:
        yc, h = (words[i][1] + words[i][3]) / 2, max(words[i][3] - words[i][1], 3.0)
        if lines and abs(yc - centre) <= 0.5 * max(h, height):
            lines[-1].append(i)
        else:
            lines.append([i])
            centre, height = yc, h
    for line in lines:
        line.sort(key=lambda i: words[i][0])
    return lines


class Page:
    def __init__(self, words: list[tuple[float, float, float, float, str]]):
        self.words = words
        self.lines = lines_of(words)
        self.line_of = {i: n for n, line in enumerate(self.lines) for i in line}
        self.by_value: dict[str, list[int]] = defaultdict(list)
        for i, w in enumerate(words):
            key = word_value(w[4])
            if key:
                self.by_value[key].append(i)
                if key.endswith("%"):
                    self.by_value[key[:-1]].append(i)

    def text_left(self, line: int, x: float | None) -> str:
        """The line's label text: its non-number words left of ``x`` (the whole line when ``x`` is None).  Read
        leftwards from ``x``: once label words are found, a wide gap (a page column's gutter) ends the label, so
        prose in the next page column is not part of it."""
        idx = [i for i in self.lines[line] if x is None or self.words[i][2] <= x + 1]
        if x is None:
            return " ".join(self.words[i][4] for i in idx if not _is_num(self.words[i][4]))
        picked: list[int] = []
        edge = None
        for i in reversed(idx):
            w = self.words[i]
            if _is_num(w[4]) and not picked:
                continue                              # numbers of the columns between the label and the value
            if edge is not None and edge - w[2] > max(9.0, 1.5 * (w[3] - w[1])):
                break
            if not _is_num(w[4]) or picked:
                picked.append(i)
                edge = w[0]
        return " ".join(self.words[i][4] for i in reversed(picked))

    def has_number(self, line: int) -> bool:
        return any(_is_num(self.words[i][4]) for i in self.lines[line])

    def row_texts(self, i: int) -> list[str]:
        """Label text for the value word ``i``: its own line, then joined with a number-less line above/below."""
        n, x = self.line_of[i], self.words[i][0]
        own = self.text_left(n, x)
        whole = " ".join(self.words[j][4] for j in self.lines[n]
                         if self.words[j][2] <= x + 1 and re.search(r"[A-Za-z]", self.words[j][4]))
        out = [own] + ([whole] if whole and whole != own else [])
        above = self.text_left(n - 1, x) if n > 0 and not self.has_number(n - 1) else ""
        below = self.text_left(n + 1, x) if n + 1 < len(self.lines) and not self.has_number(n + 1) else ""
        if above:
            out.append(f"{above} {own}")
        if below:
            out.append(f"{own} {below}")
        if above and below:
            out.append(f"{above} {own} {below}")
        return out

    def occurrences(self, value: str) -> list[int]:
        key = _norm_value(value)
        return self.by_value.get(key) or self.by_value.get(key.rstrip("%")) or []

    def title_above(self, i: int, keys: set[str]) -> bool:
        """Is the label a number-less line printed above the value (a chart panel's title)?"""
        n = self.line_of[i]
        for m in range(n):
            if self.has_number(m):
                continue
            key = label_key(self.text_left(m, None))
            if key and any(k and (k in key or same_label(k, key)) for k in keys):
                return True
        return False

    def header_above(self, i: int, header: str, below: bool = False) -> bool | None:
        """Is a word of the column header printed above the value word and over it (``below``: under it, as a
        chart's axis label is)?  None: header has no words on the page."""
        tokens = [re.sub(r"[^a-z0-9]+", "", t.casefold()) for t in re.split(r"[\s>/|]+", header)]
        tokens = [t for t in tokens if t]
        strong = [t for t in tokens if any(ch.isdigit() for ch in t)] or tokens
        if not strong:
            return None
        x0, y0, x1 = self.words[i][0], self.words[i][1], self.words[i][2]
        pad = max(6.0, 0.25 * (x1 - x0))
        found = False
        for w in self.words:
            if re.sub(r"[^a-z0-9]+", "", w[4].casefold()) not in strong:
                continue
            found = True
            y1 = self.words[i][3]
            if (w[1] >= y1 - 1 if below else w[3] <= y0 + 1) and w[0] <= x1 + pad and w[2] >= x0 - pad:
                return True
        return False if found else None


def _label_fits(label_key_: str, texts: list[str]) -> bool:
    bare = re.sub(r"\d{1,2}$", "", label_key_)        # a footnote mark printed as a separate word ("EBITDA 1")
    if bare != label_key_ and len(bare) >= 3 and _label_fits(bare, texts):
        return True
    for text in texts:
        key = label_key(text)
        if not key:
            continue
        if key == label_key_ or len(label_key_) >= 4 and (key.endswith(label_key_) or key.startswith(label_key_))                 or len(key) >= 8 and label_key_.startswith(key) or same_label(key, label_key_) and (
                min(len(key), len(label_key_)) >= max(4, 0.5 * max(len(key), len(label_key_)))
                or key not in label_key_ and label_key_ not in key):
            return True
    return False


def place(page: Page, cell: dict[str, Any]) -> tuple[bool | None, bool | None, int | None]:
    """(row_ok, col_ok, word index).  None = could not be located."""
    occ = page.occurrences(cell["value"])
    if not occ:
        return None, None, None
    keys = {cell["lk"], label_key(cell["label"])}
    on_row = [i for i in occ if any(_label_fits(k, page.row_texts(i)) for k in keys if k)]
    if not on_row:
        chart = [i for i in occ if page.header_above(i, cell["col"], below=True) and page.title_above(i, keys)]
        if chart:                      # a chart: the title above the panel is the row, the axis label the column
            return True, True, chart[0]
        whole = label_key(" ".join(w[4] for w in page.words))
        located = any(k and k in whole for k in keys)
        return (False if located else None), None, None
    cols = [(page.header_above(i, cell["col"]), i) for i in on_row]
    for want in (True, None, False):
        hit = [i for ok, i in cols if ok is want]
        if hit:
            return True, want, hit[0]
    return True, None, on_row[0]


def settle_page(readers: list[list[dict[str, str]]], words: list[tuple[float, float, float, float, str]] | None,
                text: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    per_reader = [cells_of(r) for r in readers]
    canon = unify_labels(per_reader)
    answering = sum(1 for c in per_reader if c)
    page = Page(words) if words else None
    text_norm = _norm_space(text or " ".join(w[4] for w in words or [])).casefold()
    text_nocomma = text_norm.replace(",", "")
    placed: dict[int, list[tuple[int, dict[str, Any], bool | None]]] = defaultdict(list)
    loose: dict[tuple[str, str], list[tuple[int, dict[str, Any], bool | None]]] = defaultdict(list)
    for ri, cells in enumerate(per_reader):
        for c in cells:
            if c["value"].strip().casefold() in _BLANK:
                continue                                   # an empty cell, not a figure
            c["lk"] = str(canon.get(c["lk"], c["lk"]))
            row_ok, col_ok, at = place(page, c) if page else (None, None, None)
            if at is not None:
                placed[at].append((ri, c, col_ok))
            else:
                loose[(c["lk"], c["norm"])].append((ri, c, row_ok))
    out: list[dict[str, Any]] = []
    for at, given in sorted(placed.items(), key=lambda kv: (page.words[kv[0]][1], page.words[kv[0]][0])):  # type: ignore[union-attr]
        w = page.words[at]  # type: ignore[union-attr]
        by_label = Counter(c["lk"] for _ri, c, _ok in given)
        lk = by_label.most_common(1)[0][0]
        mine = [(ri, c, ok) for ri, c, ok in given if c["lk"] == lk]
        agree = len({ri for ri, _c, _ok in mine})
        names = Counter(c["label"] for _ri, c, _ok in mine)
        heads = Counter(c["col"] for _ri, c, _ok in mine)
        col_votes = [ok for _ri, _c, ok in mine]
        col_ok = True if any(v is True for v in col_votes) else (False if all(v is False for v in col_votes) else None)
        col_true = {id(c) for _ri, c, ok in mine if ok is True}
        pick = max((c for _ri, c, _ok in mine),
                   key=lambda c: (id(c) in col_true, names[c["label"]], heads[c["col"]]))
        conflict = ""
        if len(by_label) > 1:
            conflict = "two_labels_fit_line"
        elif col_ok is False:
            conflict = "column_elsewhere"
        elif agree < 2 and col_ok is None:
            conflict = "lone_column_unlocated"
        settled = "" if conflict else ("script+position" if agree >= 2 else "position")
        out.append({"row_label": pick["label"], "col_header": pick["col"], "value_text": pick["value"],
                    "unit_text": pick["unit"], "readers": answering, "agree_n": agree, "row_ok": True,
                    "col_ok": "" if col_ok is None else col_ok, "settled_by": settled, "conflict": conflict,
                    "label_aliases": " || ".join(n for n in names if n != pick["label"]),
                    "col_aliases": " || ".join(h for h in heads if h != pick["col"]),
                    "line_text": page.row_texts(at)[0], "x0": round(w[0], 1), "y0": round(w[1], 1),  # type: ignore[union-attr]
                    "x1": round(w[2], 1), "y1": round(w[3], 1)})
    for (_lk, _norm), given in loose.items():
        agree = len({ri for ri, _c, _ok in given})
        names = Counter(c["label"] for _ri, c, _ok in given)
        pick = max((c for _ri, c, _ok in given), key=lambda c: names[c["label"]])
        row_ok = False if any(ok is False for _ri, _c, ok in given) else None
        v = _norm_space(pick["value"]).casefold()
        verbatim = bool(v) and (v in text_norm or v.replace(",", "") in text_nocomma)
        if row_ok is False:
            settled, conflict = "", "row_elsewhere"
        elif agree >= 2 and verbatim:
            settled, conflict = "script", ""
        else:
            settled, conflict = "", ("lone_unlocated" if verbatim else "value_not_printed")
        out.append({"row_label": pick["label"], "col_header": pick["col"], "value_text": pick["value"],
                    "unit_text": pick["unit"], "readers": answering, "agree_n": agree,
                    "row_ok": "" if row_ok is None else row_ok, "col_ok": "", "settled_by": settled,
                    "conflict": conflict, "label_aliases": " || ".join(n for n in names if n != pick["label"]),
                    "col_aliases": "", "line_text": "", "x0": "", "y0": "", "x1": "", "y1": ""})
    unread: list[dict[str, Any]] = []
    if page:
        nums_at = [(i, n) for n, line in enumerate(page.lines) for i in line if _is_num(page.words[i][4])]
        for i, n in nums_at:
            if i in placed or page.words[i][4].strip() in _BLANK:
                continue
            label = page.text_left(n, None)
            if not re.search(r"[A-Za-z]{3}", label):
                continue
            x0, x1 = page.words[i][0], page.words[i][2]
            column = {m for j, m in nums_at if m != n and page.words[j][0] <= x1 and page.words[j][2] >= x0}
            if len(column) >= 2:                   # a table column: numbers on two or more other lines under it
                unread.append({"line_text": label, "value_text": page.words[i][4],
                               "x0": round(x0, 1), "y0": round(page.words[i][1], 1)})
    return out, unread


def run(pages_csv: Path, pdf_pages: Path, runs: list[Path], out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    rows, unread_rows, per_page = [], [], []
    for meta in _load_pages_csv(pages_csv):
        pid = meta["page_id"]
        pdf = pdf_pages / f"{pid}.pdf"
        words = page_words(pdf) if pdf.exists() else None
        cells, unread = settle_page([_load_run_rows(r, pid) for r in runs], words)
        rows += [{"page_id": pid, "split": meta.get("split", ""), **c} for c in cells]
        unread_rows += [{"page_id": pid, "split": meta.get("split", ""), **u} for u in unread]
        per_page.append({"page_id": pid, "split": meta.get("split", ""), "doc_type": meta.get("doc type", ""),
                         "stratum": meta.get("stratum", ""), "words": len(words or []), "cells": len(cells),
                         "settled": sum(1 for c in cells if c["settled_by"]),
                         "open": sum(1 for c in cells if not c["settled_by"]), "unread": len(unread)})
    with open(out / "reference_cells.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    with open(out / "unread_numbers.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["page_id", "split", "line_text", "value_text", "x0", "y0"])
        w.writeheader()
        w.writerows(unread_rows)
    with open(out / "page_summary.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(per_page[0]))
        w.writeheader()
        w.writerows(per_page)
    return {"cells": len(rows), "by_status": Counter(r["settled_by"] or f"open:{r['conflict']}" for r in rows),
            "unread": len(unread_rows), "pages": per_page}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="T-177: settle reference cells by printed position")
    ap.add_argument("--pages", required=True, type=Path)
    ap.add_argument("--pdf-pages", required=True, type=Path)
    ap.add_argument("--runs", nargs="+", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    s = run(args.pages, args.pdf_pages, args.runs, args.out)
    print(f"cells {s['cells']}, numbers on table lines no reader gave {s['unread']}")
    for status, n in sorted(s["by_status"].items(), key=lambda kv: -kv[1]):
        print(f"  {status}: {n}")
    for p in s["pages"]:
        print(f"  {p['page_id']} {p['split']:6} {p['doc_type']:13} {p['stratum']:16} cells {p['cells']:4} "
              f"settled {p['settled']:4} open {p['open']:4} unread {p['unread']:4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
