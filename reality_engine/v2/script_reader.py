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
    # only a statement phrase names the basis ("Consolidated Unaudited Financial Results", "Standalone Balance
    # Sheet"), never a company name ("Consolidated Finvest Limited": third review R3-5)
    if "standalone" in top and "consolidated" in top:
        return ""                                   # both named anywhere on top ("Standalone Standalone & & Consolidated"
        #                                             Consolidated", side-by-side statements): a column header decides
    found = {m.group(1) for m in _BASIS_PHRASE.finditer(top)}
    return found.pop() if len(found) == 1 else ""   # both printed ("Standalone and Consolidated"): undecided (F3)


def column_basis(col_header: str) -> str:
    """The basis a column's own header stack prints ("Standalone As at 30th September, 2025"), when it prints
    exactly one; '' otherwise.  It overrides the page basis (c01 side-by-side balance sheet, witness review)."""
    h = (col_header or "").lower()
    found = {b for b in ("standalone", "consolidated") if b in h}
    return found.pop() if len(found) == 1 else ""


_BASIS_PHRASE = re.compile(r"\b(consolidated|standalone)\s+(un-?audited|audited|financial|statement|results?|"
                           r"balance|segment|cash|profit|statements?|assets|figures)\b")


def page_title(words: list[tuple[float, float, float, float, str]]) -> str:
    """The page's top 40 words: enough for column_kind to take the period type from a title ("Balance Sheet",
    "for the year ended")."""
    return " ".join(w[4] for w in sorted(words, key=lambda w: (round(w[1]), w[0]))[:40])


_ID_LABEL = re.compile(r"\b(din|cin|pan|gstin|membership|registration|frn|firm\s+reg|place|date|page|tel|telephone|"
                       r"phone|fax|mobile|pin|pincode|email|e-mail|website|isin|scrip|code)\b", re.I)


def figure_ok(text: str) -> bool:
    """A printed figure the script may serve: brackets balanced ("19.59)" is a negative whose "(" the layer split
    off), and not an identifier (a leading zero before more digits: a DIN "07027180", "00005573")."""
    t = text.strip()
    if t.count("(") != t.count(")") or t.count("[") != t.count("]"):
        return False
    digits = re.sub(r"[^\d.]", "", t)
    return not re.match(r"0\d", digits)


_MINUS = ("-", "–", "—", "−")
_FOOTNOTE = re.compile(r"[*#†‡^]{1,3}|\d{1,2}|\(\d{1,2}\)|\d{1,2}[*#]")
_NOTE_END = re.compile(r"\b(note|notes|note\s+no\.?|refer|ref\.?)\s*$", re.I)


def _lone_bracket_beside(words: list[tuple[float, float, float, float, str]], order: list[int], i: int,
                         h: float = 8.0, cols: list[dict[str, Any]] | None = None) -> bool:
    """The figure's sign may sit in other words of its cell (T-226 F1, F2, re-review F-A): every word between the
    previous figure (or the label) and this figure is read, and every word up to the next figure.  Refused: an
    opening bracket left unclosed on the left ("(", "(Rs.", "( ₹"), a closing bracket unopened on the right, or a
    minus on the left that is not an empty-cell mark of ANOTHER column (a dash centred inside another column's
    range is that column's blank cell; any other minus belongs to this figure)."""
    k = order.index(i)
    left_idx: list[int] = []
    for j in reversed(order[:k]):
        if _FOOTNOTE.fullmatch(words[j][4].strip()):
            continue                                    # a footnote mark between sign and figure (third review R3-1)
        if any(ch.isdigit() for ch in words[j][4]):
            break
        left_idx.append(j)
    opened = sum(words[j][4].count("(") - words[j][4].count(")") for j in left_idx)
    if opened > 0:
        return True
    home = None
    xc = (words[i][0] + words[i][2]) / 2
    for c in cols or []:
        if c["x0"] - 1 <= xc <= c["x1"] + 1:
            home = c
    for j in left_idx:
        t = words[j]
        nxt = order[order.index(j) + 1]
        if t[4].strip() in _MINUS and not re.match(r"[A-Za-z]", words[nxt][4]):   # "- Current Tax" is a bullet
            dc = (t[0] + t[2]) / 2
            other = any(c is not home and c["x0"] - 0.5 * h <= dc <= c["x1"] + 0.5 * h for c in cols or [])
            if not other:
                return True
    closed = 0
    for j in order[k + 1:]:
        if any(ch.isdigit() for ch in words[j][4]):
            break
        closed += words[j][4].count(")") - words[j][4].count("(")
    return closed > 0


def _wrapped_above(page: Any, n: int, label_right: float) -> bool:
    """The label's first printed line is the figure-less line just above (T-226 F6: "Less: Provision for doubtful"
    over "Debts 123.40"): that line starts where this label starts, does not end in a colon, and runs out to the
    width of the table's longest label, which is where a long label wraps.  A short heading ("Segment Revenue")
    does not reach that width."""
    if n == 0:
        return False
    w = page.words
    above, here = page.lines[n - 1], page.lines[n]
    # a note number ("5") on the first line does not make it a figure row (re-review F-C): only a figure that is
    # more than a 1-2 digit integer does
    if any(page._digit_figure(j) and not re.fullmatch(r"\d{1,2}", w[j][4].strip()) for j in above):
        return False
    top_here = min(w[j][1] for j in here)
    bottom_above = max(w[j][3] for j in above)
    if top_here - bottom_above > 3.0 * page.h:        # wide line spacing still wraps (re-review F-B); a refusal
        return False
    x_here = min(w[j][0] for j in here)
    x_above = min(w[j][0] for j in above)
    if abs(x_here - x_above) > 3.0 * page.h:
        return False
    text = " ".join(w[j][4] for j in sorted(above, key=lambda j: w[j][0]) if not
                    re.fullmatch(r"\d{1,2}", w[j][4].strip())).strip()
    if not text or text.endswith(":"):
        return False
    if max(w[j][2] for j in above) >= 0.8 * label_right:
        return True
    if _JOINER_END.search(text):                       # "... Plant and Equipments," / "... for the"
        return True
    own = " ".join(w[j][4] for j in sorted(here, key=lambda j: w[j][0]))
    if _PAREN_START.match(own):                        # "(Including Capital Work ...)" continues the line above
        return True
    # otherwise a heading heads two or more figure rows; a first line with one figure row under it is a wrap
    rows = 0
    for m in range(n, min(len(page.lines), n + 3)):
        if any(page._digit_figure(j) and not re.fullmatch(r"\d{1,2}", w[j][4].strip()) for j in page.lines[m]):
            rows += 1
        else:
            break
    return rows < 2


_JOINER_END = re.compile(r"(,|\b(of|and|for|to|in|on|the|from|by|with|&|or|at|under|towards|including))\s*$", re.I)
_PAREN_START = re.compile(r"^\(\s*(?![a-z]{1,4}\)|[ivx]{1,5}\)|\d{1,2}\))[A-Za-z]{3,}")


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
    label_right = 0.0                                   # right edge of the table's longest row label
    for line in page.lines:
        figs = [i for i in line if page._digit_figure(i)]
        if figs:
            x = min(words[i][0] for i in figs)
            lab = [j for j in line if words[j][2] <= x and not rg._is_num(words[j][4])]
            if lab:
                label_right = max(label_right, max(words[j][2] for j in lab))
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
        if not good_label(label) or _ID_LABEL.search(label) or _wrapped_above(page, n, label_right):
            continue
        if _NOTE_END.search(label):
            continue                                    # "... Note 12.3": the first figure is a note reference (R3-2)
        band = page.header_band(n)
        if not band or n not in page._block(n, band):
            continue                                    # not a data line of the table under its header (T-226 F5)
        cols = page.columns_for(n)
        order = sorted(line, key=lambda j: words[j][0])
        homes = [next((k for k, c in enumerate(cols) if c["x0"] - 1 <= (words[i][0] + words[i][2]) / 2 <= c["x1"] + 1),
                      None) for i in figs]
        placed_homes = [h for h in homes if h is not None]
        if len(placed_homes) != len(set(placed_homes)):
            continue                                    # two figures under one column: a split number ("20 971")
        for i in figs:
            if not figure_ok(words[i][4]) or _lone_bracket_beside(words, order, i, page.h, cols):
                continue
            xc = (words[i][0] + words[i][2]) / 2
            col = next((c for c in cols if c["x0"] - 1 <= xc <= c["x1"] + 1), None)
            if not col or not col.get("stack"):
                continue
            head = " ".join(col["stack"])
            if len({d.lower() for d in _DATES.findall(head)}) > 1:
                continue                                # two dates over one column: a merged neighbour header
            rows.append({"table": "", "row_label": label, "col_header": head, "value": words[i][4], "unit": "",
                         "section": section, "table_id": band[0],
                         "box": tuple(round(v, 1) for v in words[i][:4])})
    return rows


def settled(words: list[tuple[float, float, float, float, str]]) -> list[dict[str, Any]]:
    """``read_page`` cells the checker places (row and column), with basis, period end and period kind."""
    rows = read_page(words)
    if not rows:
        return []
    out, _ = rg.settle_page([[{k: v for k, v in r.items() if k not in ("box", "section", "table_id")} for r in rows]], words)
    basis = page_basis(words)
    title = page_title(words)
    section = {r["box"][:2]: r["section"] for r in rows}  # by printed box: a repeated label has one per line
    table_of = {r["box"][:2]: r["table_id"] for r in rows}
    unit = page_unit(words)
    cells = []
    for o in out:
        if o.get("settled_by") not in ("position", "script+position"):
            continue
        cells.append({"row_label": o["row_label"], "col_header": o["col_header"], "value_text": o["value_text"],
                      "basis": column_basis(o["col_header"]) or basis, "title": title,
                      "period_end": cj.period_end(o["col_header"]) or "",
                      "kind": cj.column_kind(o["col_header"], title), "section": section.get((o["x0"], o["y0"]), ""),
                      "repeated": bool(o.get("label_repeated")), "table_id": table_of.get((o["x0"], o["y0"])),
                      "unit_scale": unit, "box": (o["x0"], o["y0"], o["x1"], o["y1"])})
    cells = _decimals_consistent(cells)
    # a label printed on two lines of one column is two rows; when both carry the same section heading the rows
    # cannot be told apart (a cash-flow "Dividend received" under operating adjustments and under investing, with
    # a stale heading on both): refuse them all.
    seen: dict[tuple[str, str, str], int] = defaultdict(int)
    for c in cells:
        seen[(c["row_label"], c["col_header"], c["section"])] += 1
    return [c for c in cells if seen[(c["row_label"], c["col_header"], c["section"])] == 1
            and not generic_unanchored(c["row_label"], c["section"])]


_GENERIC_WORDS = {"total", "grand", "sub", "subtotal", "others", "other", "net", "less", "add", "balance", "closing",
                  "opening", "amount", "sum", "gross"}
_PERIODISH = re.compile(r"\b(ended|quarter|year|months?|half|audited|unaudited|particulars)\b", re.I)


def generic_unanchored(label: str, section: str) -> bool:
    """A bare "Total" / "Others" / "Net" says nothing about what it totals; served only under a section heading
    that is not header text ("Quarter ended Nine months ended Year ended" names columns, not a line: c88 note
    table, round 6 read)."""
    words = [t for t in label_key(label).split() if len(t) > 1 and not re.fullmatch(r"[ivx]+", t)]
    if not words or not set(words) <= _GENERIC_WORDS:   # "Total (A)", "Net Total" (re-review F-E)
        return False
    return not section.strip() or bool(_PERIODISH.search(section))


def label_key(label: str) -> str:
    """Row label as a gate key: list marks ("(a)", "IV.", "1)") and punctuation dropped."""
    return re.sub(r"[^a-z]+", " ", _MARK.sub("", label.lower())).strip()


_PER_SHARE = re.compile(r"\b(basic|diluted|eps|per\s+(equity\s+|ordinary\s+)?shares?|earnings\s+per)\b", re.I)


def per_share_ok(label: str, value: str) -> bool:
    """A per-share line (EPS, basic, diluted) prints its decimals; "154" for 1.54 is a scan layer that dropped the
    point, and it drops it the same way in every filing (c31, 19 Nov), so agreement cannot catch it."""
    return not _PER_SHARE.search(label) or "." in value or value.strip("()-") in ("0", "")


def _xbrl_refuses(c: dict[str, Any], xbrl: Any) -> bool:
    """The XBRL judge, given the page title as the table title (statement type, basis, scale: T-226 F4), calls the
    cell ``disagree``, or agrees only with the sign flipped (a lost minus: T-226 F1)."""
    title = f'{c.get("title", "")} {c.get("basis", "")}'.strip()
    v = cj.judge({"row_label": c["row_label"], "col_header": c.get("col_header", ""), "value_text": c["value_text"],
                  "unit_text": "", "table_title": title}, xbrl)
    return v.verdict == "disagree" or bool(v.sign_flip)


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
        if not per_share_ok(f'{c.get("section", "")} {c["row_label"]}', c["value_text"]):  # wrapped "Per equity"
            c["gate"] = "per_share_no_decimal"
            continue
        if not kind_ok(c.get("col_header", ""), c["kind"], c["period_end"]):
            c["gate"] = "year_kind_doubtful"
            continue
        if not figure_ok(c["value_text"]) or _ID_LABEL.search(c["row_label"]):
            c["gate"] = "not_a_figure"
            continue
        if not c.get("basis"):
            c["gate"] = "basis_unknown"                 # neither or both bases printed (T-226 F3)
            continue
        if c["doc_key"] not in filed:
            c["gate"] = "no_filing_date"
            continue
        label = f'{c.get("section", "")} {c["row_label"]}' if c.get("repeated") else c["row_label"]
        groups[(c["basis"], label_key(label), c["period_end"], c["kind"])].append(c)
    for group in groups.values():
        values = {_norm_value(c["value_text"]) for c in group}
        dates = sorted({filed[c["doc_key"]] for c in group})
        if len(values) > 1:
            gate = "conflict"
        elif xbrl is not None and any(_xbrl_refuses(c, xbrl) for c in group):
            gate = "xbrl_disagrees"
        elif (dates[-1] - dates[0]).days >= MIN_DAYS_APART:
            gate = "pass"
        else:
            gate = "single_filing"
        for c in group:
            c["gate"] = gate
    return cells


# --- independent witnesses (T-226, Shivam 19 Nov: build the arithmetic and XBRL gates) ---------------------------
#
# The checker and the reader share one geometry, and a misreading repeated the same way in every filing agrees with
# itself, so neither the checker nor cross-filing agreement can prove a figure.  A figure is served VERIFIED only when
# a witness that does not depend on how the page was read agrees with it:
#   arithmetic: the figure sits in a printed identity that adds up (a row equals the sum of the rows just above it,
#     or the sum or difference of two rows above it) and the SAME identity over the same rows holds in at least two
#     columns of the page, so a coincidence in one column cannot verify anything;
#   XBRL: the XBRL judge finds the figure's line and period and agrees exactly, with the sign.
# Cross-filing agreement alone serves the cell UNVERIFIED (labelled); every refusal rule above still refuses.

ARITH_LOOKBACK = 15
ARITH_MAX_RUN = 10


def _num(text: str) -> tuple[float, int] | None:
    return cj.number(text)


def arith_witness(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set ``arith`` (True/False) and ``arith_rel`` on the cells of ONE page (``settled`` output: needs ``box``,
    ``col_header``, ``value_text``).  Rows are matched across columns by printed line (box top)."""
    cols: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for c in cells:
        c["arith"], c["arith_rel"] = False, ""
        if _num(c["value_text"]) is None:
            continue
        xc = (c["box"][0] + c["box"][2]) / 2
        cols[(c.get("table_id"), c["col_header"], int(xc // 25))].append(c)
    found: dict[tuple, list[tuple[tuple[str, int], list[dict[str, Any]]]]] = defaultdict(list)
    for key, col in cols.items():
        col.sort(key=lambda c: c["box"][1])
        vals = [_num(c["value_text"]) for c in col]
        rows = [round(c["box"][1]) for c in col]
        for j in range(len(col)):
            vj, dj = vals[j]  # type: ignore[misc]
            if abs(vj) < 1 and dj == 0 or vj == 0:
                continue
            lo = max(0, j - ARITH_LOOKBACK)
            for i in range(max(lo, j - ARITH_MAX_RUN), j - 1):          # contiguous run i..j-1 sums to j
                terms = vals[i:j]
                if sum(1 for t in terms if t and t[0] != 0) < 2:  # type: ignore[index]
                    continue
                dec = max([dj] + [t[1] for t in terms])  # type: ignore[index]
                if abs(sum(t[0] for t in terms) - vj) <= 0.5 * 10 ** -dec * len(terms) + 1e-9:  # type: ignore[index]
                    found[("run", tuple(rows[i:j + 1]))].append((key, col[i:j + 1]))
            for a in range(lo, j):
                va, da = vals[a]  # type: ignore[misc]
                if va == 0:
                    continue
                for b in range(a + 1, j):
                    vb, db = vals[b]  # type: ignore[misc]
                    if vb == 0:
                        continue
                    tol = 0.5 * 10 ** -max(dj, da, db) * 2 + 1e-9
                    if abs(va + vb - vj) <= tol:
                        found[("sum", rows[a], rows[b], rows[j])].append((key, [col[a], col[b], col[j]]))
                    elif abs(va - vb - vj) <= tol:
                        found[("diff", rows[a], rows[b], rows[j])].append((key, [col[a], col[b], col[j]]))
    for rel, hits in found.items():
        if len({k for k, _ in hits}) < 2:
            continue                                    # the same identity must hold in two or more columns
        for _, members in hits:
            for c in members:
                c["arith"] = True
                c["arith_rel"] = c["arith_rel"] or rel[0]
    return cells


_HARD_REFUSALS = {"no_period", "per_share_no_decimal", "year_kind_doubtful", "not_a_figure", "basis_unknown",
                  "no_filing_date", "conflict", "xbrl_disagrees"}


def _xbrl_agrees(c: dict[str, Any], xbrl: Any) -> bool:
    """XBRL witness: the judge agrees, at the page's OWN printed unit (or rupees on a per-share line), and the
    printed figure equals an XBRL fact up to rounding of its printed decimals only (review F1: with no unit the judge
    tries every scale, so "3419685" for 34,196.85 lakh agreed in thousands; F2: the judge's 0.1 % tolerance let
    30,843 agree with 30,834).  A page with no printed unit gives no XBRL witness."""
    p = cj.number(c["value_text"])
    if p is None or p[0] == 0:
        return False
    per_share = bool(_PER_SHARE.search(f'{c.get("section", "")} {c["row_label"]}'))
    unit = 1.0 if per_share else c.get("unit_scale")
    if not unit:
        return False
    title = f'{c.get("title", "")} {c.get("basis", "")}'.strip()
    v = cj.judge({"row_label": c["row_label"], "col_header": c.get("col_header", ""), "value_text": c["value_text"],
                  "unit_text": "", "table_title": title}, xbrl)
    if v.verdict != "agree" or v.sign_flip or v.printed is None:
        return False
    if v.basis and v.basis != c.get("basis"):
        return False                                # agreed with the other statement (standalone vs consolidated)
    used = v.printed / p[0]
    if abs(used - unit) > 1e-9 * unit:
        return False
    tol = 0.5 * 10 ** -p[1] * unit + 1e-6
    return any(abs(v.printed - x) <= tol for x in v.xbrl)


def _column_key(c: dict[str, Any]) -> tuple:
    """One printed column of one page: document, page, header text and the figure's x position (25 pt bins)."""
    box = c.get("box") or (0, 0, 0, 0)
    return (c.get("doc_key"), c.get("page"), c.get("table_id"), c.get("col_header"),
            int(((box[0] + box[2]) / 2) // 25))


def witness_gate(cells: Iterable[dict[str, Any]], filed: Mapping[str, _dt.date],
                 xbrl: Any = None) -> list[dict[str, Any]]:
    """``cross_gate`` first (its refusal rules and the cross-filing key), then ``status`` per cell:
    ``verified`` (an arithmetic or XBRL witness; ``witness`` names which, plus ``cross`` when filings also agree),
    ``unverified`` (cross-filing agreement only, served labelled), ``refused``.  Cells need ``arith`` from
    ``arith_witness`` (run per page before this)."""
    cells = cross_gate(cells, filed, xbrl)
    # an arithmetic identity proves the figures add up, not which period the column header names (a reader that
    # put the wrong date over a whole column still adds up): the column's period must be confirmed by one of its
    # own cells through XBRL or a second filing, and then holds for every cell printed in that column
    for c in cells:
        c["_xa"] = c["gate"] not in _HARD_REFUSALS and xbrl is not None and _xbrl_agrees(c, xbrl)
    row_vals: dict[tuple, set[str]] = defaultdict(set)
    for c in cells:
        row_vals[(c.get("doc_key"), c.get("page"), c.get("table_id"), round(c["box"][1]) if c.get("box") else None)].add(
            _norm_value(c["value_text"]))
    confirmed: set[tuple] = set()
    for c in cells:
        row = (c.get("doc_key"), c.get("page"), c.get("table_id"), round(c["box"][1]) if c.get("box") else None)
        if (c["_xa"] or c["gate"] == "pass") and len(row_vals[row]) > 1:
            confirmed.add(_column_key(c))              # share capital, equal in every period, proves no date (F3)
    for c in cells:
        if c["gate"] in _HARD_REFUSALS:
            c["status"], c["witness"] = "refused", ""
            continue
        w = []
        if c.get("arith") and _column_key(c) in confirmed:
            w.append("arith")
        if c.pop("_xa", False):
            w.append("xbrl")
        if c["gate"] == "pass":
            w.append("cross")
        c["witness"] = "+".join(w)
        if "arith" in w or "xbrl" in w:
            c["status"] = "verified"
        elif "cross" in w:
            c["status"] = "unverified"
        else:
            c["status"] = "refused"
    return cells


def page_unit(words: list[tuple[float, float, float, float, str]]) -> float | None:
    """The page's printed unit (lakh 1e5, crore 1e7, million 1e6, thousand 1e3) when exactly one is printed anywhere
    on the page; None when none or several (review F1)."""
    text = " ".join(w[4] for w in words)
    found = {scale for rx, scale in cj._UNITS if scale != 1.0 and rx.search(text)}
    return found.pop() if len(found) == 1 else None


def _decimals_consistent(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A figure printed without decimals in a column whose other figures (three or more) print them is a scan layer
    that dropped the point ("3419685" for 34,196.85): refused (review F1)."""
    by_col: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for c in cells:
        box = c["box"]
        by_col[(c.get("table_id"), c["col_header"], int(((box[0] + box[2]) / 2) // 25))].append(c)
    out = []
    for col in by_col.values():
        dec = [cj.number(c["value_text"]) for c in col]
        with_dec = sum(1 for d in dec if d and d[1] > 0)
        for c, d in zip(col, dec):
            if d and d[1] == 0 and abs(d[0]) >= 10 and with_dec >= 3 and with_dec > len(col) / 2:
                continue
            out.append(c)
    return out
