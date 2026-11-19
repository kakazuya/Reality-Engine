"""Script-first page reading (T-226, Shivam 19 Nov 2026: rely less on models; losing a right cell is fine, serving a
wrong one never is).

Two parts, no model anywhere:

1. ``read_page(words)``: every printed figure on a table line gets label = the printed text left of its line and
   column header = the header stack the checker's column model (``reference_geom.Page.columns_for``) prints over its
   column.  Refused (no cell): a label that does not start like a row (a lower-case wrapped continuation) or is OCR
   debris, and a column whose header stack prints two different dates (the column model merged a neighbour's header).
   ``reference_geom.settle_page`` then runs as for a model's read.

2. ``cross_gate(cells, filed)``: the checker shares the reader's geometry, so it cannot catch this reader's own column
   errors (measured 19 Nov: 1,268 of 14,696 checker-passed script cells sat under another column).  The independent
   test is the filings themselves: each results filing reprints earlier periods in its comparison columns.  A cell
   passes only when filings at least ``MIN_DAYS_APART`` days apart (so never the same results filed on NSE and BSE
   minutes apart) print the same value for the same (basis, row label, period end, period kind), and no filing prints
   another value for that key.  A misread column puts a figure under a date that moves every quarter, so its key
   finds a different value in the other filing (``conflict``) instead of agreeing.  Restated figures also land in
   ``conflict``: lost, never wrong.
"""
from __future__ import annotations

import datetime as _dt
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from reality_engine.v2 import cell_judge as cj
from reality_engine.v2 import reference_geom as rg
from reality_engine.v2.reference_pages import _norm_value

MIN_DAYS_APART = 45

_DATES = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"
                    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[ ,'-]*\d{2,4}\b", re.I)
_MARK = re.compile(r"^\s*(\(?[a-z0-9ivx]{1,4}[).]\s*)+")


def good_label(label: str) -> bool:
    """A row label the script may serve: starts like a row (not a wrapped continuation in lower case) and has real
    words (3+ letters, a vowel, no tripled letter, no doubled first letter) making up at least half its letters - OCR debris ("AAGA&A",
    "GA &", "[i)") is refused."""
    t = label.strip()
    if not t or t[0].islower():
        return False
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'/-]+", t) if len(w) >= 3]
    if not words:
        return False
    if any(re.search(r"(.)\1\1", w) or re.match(r"(.)\1", w.lower()) or not re.search(r"[aeiouy]", w.lower())
           for w in words):                         # tripled letter, a doubled first letter ("AAGA"), no vowel
        return False
    return len(" ".join(words)) >= 0.5 * len(re.sub(r"[\s\d().,:-]", "", t))


def page_basis(words: list[tuple[float, float, float, float, str]]) -> str:
    """consolidated / standalone from the page's top 80 words (titles); '' when neither is printed."""
    top = " ".join(w[4] for w in sorted(words, key=lambda w: (round(w[1]), w[0]))[:80]).lower()
    found = [(top.find(b), b) for b in ("consolidated", "standalone") if b in top]
    return min(found)[1] if found else ""


def page_title(words: list[tuple[float, float, float, float, str]]) -> str:
    """The page's top 40 words: enough for column_kind to take the period type from a title ("Balance Sheet",
    "for the year ended")."""
    return " ".join(w[4] for w in sorted(words, key=lambda w: (round(w[1]), w[0]))[:40])


_ID_LABEL = re.compile(r"\b(din|cin|pan|gstin|membership|registration|frn|firm\s+reg|place|date)\b", re.I)


def figure_ok(text: str) -> bool:
    """A printed figure the script may serve: brackets balanced ("19.59)" is a negative whose "(" the layer split
    off), and not an identifier (a leading zero before more digits: a DIN "07027180", "00005573")."""
    t = text.strip()
    if t.count("(") != t.count(")") or t.count("[") != t.count("]"):
        return False
    digits = re.sub(r"[^\d.]", "", t)
    return not re.match(r"0\d", digits)


def _lone_bracket_beside(words: list[tuple[float, float, float, float, str]], order: list[int], i: int) -> bool:
    """A bare "(" just left of the figure or ")" just right of it: the sign sits in a separate word."""
    k = order.index(i)
    left = words[order[k - 1]][4].strip() if k > 0 else ""
    right = words[order[k + 1]][4].strip() if k + 1 < len(order) else ""
    return left.endswith("(") and not any(ch.isdigit() for ch in left) or right.startswith(")") and not any(
        ch.isdigit() for ch in right)


def kind_ok(col_header: str, kind: str, period_end: str) -> bool:
    """A ``year`` column whose header also names a half or nine months ("Year Ended Half September 30, 2025": the
    "Half Year Ended" phrase split across columns) or whose year does not end in March is refused (December
    year-end companies lose these cells until their year end is known)."""
    if kind != "year":
        return True
    if re.search(r"\b(half|nine|months?|quarter)\b", col_header, re.I):
        return False
    return period_end[5:7] == "03"


def read_page(words: list[tuple[float, float, float, float, str]]) -> list[dict[str, Any]]:
    """Cells of a table page read with no model, each with its printed box (``box``)."""
    page = rg.Page(words)
    rows: list[dict[str, Any]] = []
    section, seen_figures = "", False
    for n, line in enumerate(page.lines):
        if page.title_line(n):
            continue
        figs = [i for i in line if page._digit_figure(i)]
        if not figs:
            text = page.text_left(n, None).strip()
            if seen_figures and good_label(text) and len(text.split()) <= 8:
                section = text                          # a figure-less heading inside the table ("Segment Assets")
            continue
        seen_figures = True
        label = page.text_left(n, words[figs[0]][0])
        if not good_label(label) or _ID_LABEL.search(label):
            continue
        cols = page.columns_for(n)
        order = sorted(line, key=lambda j: words[j][0])
        homes = [next((k for k, c in enumerate(cols) if c["x0"] - 1 <= (words[i][0] + words[i][2]) / 2 <= c["x1"] + 1),
                      None) for i in figs]
        placed_homes = [h for h in homes if h is not None]
        if len(placed_homes) != len(set(placed_homes)):
            continue                                    # two figures under one column: a split number ("20 971")
        for i in figs:
            if not figure_ok(words[i][4]) or _lone_bracket_beside(words, order, i):
                continue
            xc = (words[i][0] + words[i][2]) / 2
            col = next((c for c in cols if c["x0"] - 1 <= xc <= c["x1"] + 1), None)
            if not col or not col.get("stack"):
                continue
            head = " ".join(col["stack"])
            if len({d.lower() for d in _DATES.findall(head)}) > 1:
                continue                                # two dates over one column: a merged neighbour header
            rows.append({"table": "", "row_label": label, "col_header": head, "value": words[i][4], "unit": "",
                         "section": section, "box": tuple(round(v, 1) for v in words[i][:4])})
    return rows


def settled(words: list[tuple[float, float, float, float, str]]) -> list[dict[str, Any]]:
    """``read_page`` cells the checker places (row and column), with basis, period end and period kind."""
    rows = read_page(words)
    if not rows:
        return []
    out, _ = rg.settle_page([[{k: v for k, v in r.items() if k not in ("box", "section")} for r in rows]], words)
    basis = page_basis(words)
    title = page_title(words)
    section = {r["box"][:2]: r["section"] for r in rows}  # by printed box: a repeated label has one per line
    cells = []
    for o in out:
        if o.get("settled_by") not in ("position", "script+position"):
            continue
        cells.append({"row_label": o["row_label"], "col_header": o["col_header"], "value_text": o["value_text"],
                      "basis": basis, "period_end": cj.period_end(o["col_header"]) or "",
                      "kind": cj.column_kind(o["col_header"], title), "section": section.get((o["x0"], o["y0"]), ""),
                      "repeated": bool(o.get("label_repeated")),
                      "box": (o["x0"], o["y0"], o["x1"], o["y1"])})
    # a label printed on two lines of one column is two rows; when both carry the same section heading the rows
    # cannot be told apart (a cash-flow "Dividend received" under operating adjustments and under investing, with
    # a stale heading on both): refuse them all.
    seen: dict[tuple[str, str, str], int] = defaultdict(int)
    for c in cells:
        seen[(c["row_label"], c["col_header"], c["section"])] += 1
    return [c for c in cells if seen[(c["row_label"], c["col_header"], c["section"])] == 1]


def label_key(label: str) -> str:
    """Row label as a gate key: list marks ("(a)", "IV.", "1)") and punctuation dropped."""
    return re.sub(r"[^a-z]+", " ", _MARK.sub("", label.lower())).strip()


_PER_SHARE = re.compile(r"\b(basic|diluted|eps|per\s+share|earnings\s+per)\b", re.I)


def per_share_ok(label: str, value: str) -> bool:
    """A per-share line (EPS, basic, diluted) prints its decimals; "154" for 1.54 is a scan layer that dropped the
    point, and it drops it the same way in every filing (c31, 19 Nov), so agreement cannot catch it."""
    return not _PER_SHARE.search(label) or "." in value or value.strip("()-") in ("0", "")


def cross_gate(cells: Iterable[dict[str, Any]], filed: Mapping[str, _dt.date],
               xbrl: Any = None) -> list[dict[str, Any]]:
    """Set ``gate`` on each cell (each needs ``doc_key``): ``pass`` / ``conflict`` / ``single_filing`` /
    ``no_period`` / ``per_share_no_decimal`` / ``xbrl_disagrees``.  Only ``pass`` may be served verified.

    ``xbrl``: a ``cell_judge.XbrlIndex``; a cell the XBRL judge calls ``disagree`` refuses its whole key (a misread
    or a mislabel repeated the same way in every filing agrees with itself: c88's discontinued-operations
    "(691)" under a bare "Profit / (Loss) Before Tax").  The judge's own label mapping is imperfect, so this loses
    some right cells; that is the accepted cost."""
    cells = list(cells)
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in cells:
        if not c.get("period_end") or c.get("kind") in ("", "unprinted"):
            c["gate"] = "no_period"
            continue
        if not per_share_ok(c["row_label"], c["value_text"]):
            c["gate"] = "per_share_no_decimal"
            continue
        if not kind_ok(c.get("col_header", ""), c["kind"], c["period_end"]):
            c["gate"] = "year_kind_doubtful"
            continue
        if not figure_ok(c["value_text"]) or _ID_LABEL.search(c["row_label"]):
            c["gate"] = "not_a_figure"
            continue
        label = f'{c.get("section", "")} {c["row_label"]}' if c.get("repeated") else c["row_label"]
        groups[(c.get("basis", ""), label_key(label), c["period_end"], c["kind"])].append(c)
    for group in groups.values():
        values = {_norm_value(c["value_text"]) for c in group}
        dates = sorted({filed[c["doc_key"]] for c in group})
        if len(values) > 1:
            gate = "conflict"
        elif xbrl is not None and any(cj.judge({"row_label": c["row_label"], "col_header": c.get("col_header", ""),
                                                "value_text": c["value_text"], "unit_text": "",
                                                "table_title": c.get("basis", "")}, xbrl).verdict == "disagree"
                                      for c in group):
            gate = "xbrl_disagrees"
        elif (dates[-1] - dates[0]).days >= MIN_DAYS_APART:
            gate = "pass"
        else:
            gate = "single_filing"
        for c in group:
            c["gate"] = gate
    return cells
