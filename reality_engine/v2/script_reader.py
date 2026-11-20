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
from collections import Counter, defaultdict
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
                         "section": section, "table_id": band[0], "table_unit": table_unit(page, band),
                         "box": tuple(round(v, 1) for v in words[i][:4])})
    return rows


_AS_AT_OCR = re.compile(r"(?<![a-z])as\s*-?\s*at(?!tach)", re.I)                # "As atatst", "Asat3ist", "As at30th"
_YEAR_OCR = re.compile(r"(?<![a-z])[yv]?[ec]ar\s+ended\b", re.I)            # "ear ended", "ycar ended"
_OTHER_KIND_OCR = re.compile(r"half|nine|six|months?|quarter|qtr|period|\bH[12]\b|\bFY|\b9M\b|\bQ[1-4]\b", re.I)


def column_kind(col_header: str, title: str) -> str:
    """``cell_judge.column_kind``; when it finds none, an OCR-damaged "As at" (a balance-sheet date) or "Year ended"
    in the header itself, never when the header names any other period word (20 Nov: 1,408 dated cells lost their
    kind to "As atatst", "Asat3ist", "ear ended")."""
    kind = cj.column_kind(col_header, title)
    if kind != "unprinted" or _OTHER_KIND_OCR.search(col_header or "") or not cj.period_end(col_header):
        return kind
    if _AS_AT_OCR.search(col_header or ""):
        return "as_at"
    if _YEAR_OCR.search(col_header or ""):
        return "year"
    return kind


_FY_LABEL = re.compile(r"(?<![a-z0-9])(?:(Q[1-4])|(H[12]|HY[12]|[12]H)|(9M))?\s*['’]?\s*FY\s*['’]?\s*(\d{2}|20\d{2})"
                       r"(?:\s*[-–/]\s*(\d{2}))?(?![0-9])(?!\s*[EP]\b)(?![EP])", re.I)  # "FY26E", "FY27P": estimates
_PERIOD_TOKEN = re.compile(r"half|nine|six|months?|quarter|qtr|\bH[12]\b|\bHY[12]\b|\b[12]H\b|\b9M\b|\bQ[1-4]\b|"
                           r"\bFY", re.I)


def fiscal_label_period(col_header: str, fy_end: int) -> tuple[str, str] | None:
    """A deck column named by fiscal label ("FY24", "Q2 FY25", "H1FY25", "9M FY26", "FY24-25") as (period end, kind),
    from the company's own fiscal year-end month ``fy_end`` (the month every XBRL FY fact of the store ends in).
    Exactly one label in the header, else None.  The date is inferred, not printed: ``witness_gate`` serves such a
    cell only on an XBRL witness of its own (20 Nov: 875 deck cells lost to "no period")."""
    found = list(_FY_LABEL.finditer(col_header or ""))
    if len(found) != 1:
        return None
    rest = col_header[:found[0].start()] + " " + col_header[found[0].end():]
    if _PERIOD_TOKEN.search(rest):
        return None                                 # "HY1 FY25" outside the label: the label's kind is not the column's
    q, h, nine, y, y2 = found[0].groups()
    if nine:
        return None                                 # the XBRL judge holds no nine-month facts: never served (F4)
    year = int(y2 or y)
    year = year + 2000 if year < 100 else year
    if y2 and int(y) % 100 + 1 != int(y2) % 100:
        return None                                 # "FY24-26": not one fiscal year
    months_back, kind = 0, "year"
    if q:
        months_back, kind = 3 * (4 - int(q[1])), "quarter"
    elif h:
        months_back, kind = (6 if "1" in h else 0), "half"
    elif nine:
        months_back, kind = 3, "nine"
    m = fy_end - months_back
    while m <= 0:
        m, year = m + 12, year - 1
    return cj._month_end(year, m), kind


def _canonical_header(end: str, kind: str) -> str:
    """A printed-style header the XBRL judge parses, for a period inferred from a fiscal label."""
    word = {"quarter": "Quarter ended", "half": "Half year ended", "nine": "Nine months ended",
            "year": "Year ended"}[kind]
    return f"{word} {end[8:10]}.{end[5:7]}.{end[:4]}"


def fy_end_month(xbrl: Any) -> int | None:
    """The one month every XBRL full-year fact of the store ends in; None when none or several."""
    months = {end[5:7] for key, end in getattr(xbrl, "by_period", {}) if key == cj.FY and end}
    return int(months.pop()) if len(months) == 1 else None


def _cell_unit(table: float | None, page: float | None, doc: float | None = None) -> float | None:
    """The table's own unit; else the page's single unit; else the document's single unit (an OCR page of a filing
    whose other pages all print "lakh": c01, 20 Nov); None when the table prints several.  A wrong unit can only
    lose a witness: the XBRL witness needs the figure at this unit to EQUAL a fact, and the veto ignores the unit."""
    if table is None:
        return page if page is not None else doc
    return table or None


def doc_unit(page_texts: Iterable[str]) -> float | None:
    """The one unit every unit-naming page of a document names; None when none or several."""
    found: set[float] = set()
    for t in page_texts:
        found |= _units_in(t or "")
    return found.pop() if len(found) == 1 else None


def settled(words: list[tuple[float, float, float, float, str]], doc_unit: float | None = None,
            fy_end: int | None = None) -> list[dict[str, Any]]:
    """``read_page`` cells the checker places (row and column), with basis, period end and period kind."""
    rows = read_page(words)
    if not rows:
        return []
    out, _ = rg.settle_page([[{k: v for k, v in r.items() if k not in ("box", "section", "table_id", "table_unit")}
                              for r in rows]], words)
    basis = page_basis(words)
    title = page_title(words)
    section = {r["box"][:2]: r["section"] for r in rows}  # by printed box: a repeated label has one per line
    table_of = {r["box"][:2]: r["table_id"] for r in rows}
    unit = page_unit(words)
    t_unit = {r["box"][:2]: r["table_unit"] for r in rows}
    cells = []
    for o in out:
        if o.get("settled_by") not in ("position", "script+position"):
            continue
        cells.append({"row_label": o["row_label"], "col_header": o["col_header"], "value_text": o["value_text"],
                      "basis": column_basis(o["col_header"]) or basis, "title": title,
                      "period_end": cj.period_end(o["col_header"]) or "",
                      "kind": column_kind(o["col_header"], title), "section": section.get((o["x0"], o["y0"]), ""),
                      "repeated": bool(o.get("label_repeated")), "table_id": table_of.get((o["x0"], o["y0"])),
                      "unit_scale": 1.0 if _PER_SHARE.search(f'{section.get((o["x0"], o["y0"]), "")} {o["row_label"]}')
                      else _cell_unit(t_unit.get((o["x0"], o["y0"])), unit, doc_unit),
                      "box": (o["x0"], o["y0"], o["x1"], o["y1"])})
    if fy_end:
        for c in cells:
            if not c["period_end"]:
                got = fiscal_label_period(c["col_header"], fy_end)
                if got and c["kind"] in ("unprinted", got[1]):
                    c["period_end"], c["kind"], c["period_inferred"] = got[0], got[1], True
                    c["judge_header"] = _canonical_header(got[0], got[1])
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


def _judge_title(c: dict[str, Any]) -> str:
    """The table title the XBRL judge gets: the page title with every basis word removed, then the cell's own basis,
    so the judge compares the figure with that basis's facts only (second witness review W2: with the page's
    "Standalone ... Consolidated" title kept, the judge named no basis and agreed with the other statement; third
    review F1: every spelling ``cell_judge.basis_of`` reads, "Stand Alone" and "Stand-alone" too)."""
    t = re.sub(r"(?i)\b(stand[\s-]*alone|consolidated)\b", " ", c.get("title", "") or "")
    return f'{t} {c.get("basis", "")}'.strip()


def _xbrl_refuses(c: dict[str, Any], xbrl: Any) -> bool:
    """The XBRL judge, given the page title as the table title (statement type, basis, scale: T-226 F4), calls the
    cell ``disagree``, or agrees only with the sign flipped (a lost minus: T-226 F1)."""
    title = _judge_title(c)
    v = cj.judge({"row_label": c["row_label"], "col_header": c.get("judge_header") or c.get("col_header", ""),
                  "value_text": c["value_text"], "unit_text": "", "table_title": title}, xbrl)
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
        title = c.get("title", "") or ""
        head = c.get("col_header", "") or ""
        if (_BALANCE_SECTION.search(f'{c.get("section", "")} {c["row_label"]}') and c["kind"] != "as_at") or \
                (c["kind"] != "as_at" and cj._BS_TITLE.search(title) and not _FLOW_TITLE.search(title)) or \
                (c["kind"] != "as_at" and cj._BS_TITLE.search(head) and not _FLOW_TITLE.search(head)) or \
                (c["kind"] == "as_at" and cj._CF_TITLE.search(c.get("title", "") or "")
                 and not cj._BS_TITLE.search(c.get("title", "") or "")):
            # a balance under a flow column (Dhampur "3. Segment Assets: Sugar 1,881.57" under "Quarter Ended"),
            # or a flow under an "As at" header on a cash-flow page: the value is right, its period type is not
            # (20 Nov unseen-company hand reads 13 #24, #26 and 14 #20: a balance-sheet-only page under
            # "Financial Year ended")
            c["gate"] = "kind_section_mismatch"
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
        if _inferred(c):
            # a date read from "FY24" or voted by XBRL neither confirms nor refuses another filing's cell (round 21:
            # an OCR misread "1,089.17" in an XBRL-dated column made a conflict that refused the right 1,099.17)
            if c["period_end"] >= filed[c["doc_key"]].isoformat():
                c["gate"] = "inferred_future"       # "FY26-27" in a May 2026 deck: guidance, not a reported period
            else:                                   # (fifth review F2)
                c["gate"] = "xbrl_disagrees" if xbrl is not None and _xbrl_refuses(c, xbrl) else "inferred"
            continue
        label =f'{c.get("section", "")} {c["row_label"]}' if c.get("repeated") else c["row_label"]
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
    gid = 0
    for rel, hits in found.items():
        if len({k for k, _ in hits}) < 2:
            continue                                    # the same identity must hold in two or more columns
        for _, members in hits:
            gid += 1
            for c in members:
                c["arith"] = True
                c["arith_rel"] = c["arith_rel"] or rel[0]
                c.setdefault("arith_groups", []).append(gid)
    return cells


_HARD_REFUSALS = {"no_period", "per_share_no_decimal", "year_kind_doubtful", "not_a_figure", "basis_unknown",
                  "no_filing_date", "conflict", "xbrl_disagrees", "inferred_future",
                  "kind_section_mismatch"}


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
    title = _judge_title(c)
    v = cj.judge({"row_label": c["row_label"], "col_header": c.get("judge_header") or c.get("col_header", ""),
                  "value_text": c["value_text"], "unit_text": "", "table_title": title}, xbrl)
    if v.verdict != "agree" or v.sign_flip or v.printed is None:
        return False
    if v.basis != c.get("basis"):
        return False                                # the judge must read the cell's own basis only: the other
        #                                             statement, or none named (both bases mixed: third review F1)
    raw = cj.basis_of(c.get("title", ""))
    if raw and raw != c.get("basis") and not column_basis(c.get("col_header", "")):
        return False                                # the page title names one basis, the cell another (a header
        #                                             snapped from a neighbour column): the check above cannot see
        #                                             it, as the judge's title carries the cell's basis (fifth review F3)
    if any(x > 0 for x in v.xbrl) and any(x < 0 for x in v.xbrl):
        return False                                # the key is filed with both signs: a lost minus would agree
        #                                             with the opposite-sign fact (third review F2)
    used = v.printed / p[0]
    if abs(used - unit) > 1e-9 * unit:
        return False
    tol = 0.5 * 10 ** -p[1] * unit + 1e-6
    if any(abs(v.printed - x) <= tol for x in v.xbrl):
        c["_xline"] = v.line_item                   # the XBRL line the figure equals (T-227: store line_item)
        return True
    return False


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
    row_vals: dict[tuple, set[float]] = defaultdict(set)
    for c in cells:
        if c["gate"] in _HARD_REFUSALS:
            continue                                    # a refused misread must not make a flat row look dated (W3)
        num = cj.number(c["value_text"])
        if num is None:
            continue
        row_vals[(c.get("doc_key"), c.get("page"), c.get("table_id"), round(c["box"][1]) if c.get("box") else None)].add(
            num[0])
    # an identity is sign-blind (a whole block that lost its brackets still adds up: W1), so it witnesses its
    # members only when one member of that same identity instance is XBRL-agreed with its sign
    anchored: set[tuple] = set()
    for c in cells:
        if c["_xa"]:
            for g in c.get("arith_groups", []):
                anchored.add((c.get("doc_key"), c.get("page"), g))
    confirmed: set[tuple] = set()
    for c in cells:
        row = (c.get("doc_key"), c.get("page"), c.get("table_id"), round(c["box"][1]) if c.get("box") else None)
        if (c["_xa"] or (c["gate"] == "pass" and not _inferred(c))) and len(row_vals[row]) > 1:
            confirmed.add(_column_key(c))              # share capital, equal in every period, proves no date (F3)
    for c in cells:
        if c["gate"] in _HARD_REFUSALS:
            c["status"], c["witness"] = "refused", ""
            continue
        w = []
        if c.get("arith") and _column_key(c) in confirmed and any(
                (c.get("doc_key"), c.get("page"), g) in anchored for g in c.get("arith_groups", [])):
            w.append("arith")
        if c.pop("_xa", False):
            w.append("xbrl")
        if c["gate"] == "pass":
            w.append("cross")
        c["witness"] = "+".join(w)
        if _inferred(c) and "xbrl" not in w:
            c["status"] = "refused"                 # a date read from "FY24" is served only on its own XBRL witness
        elif "arith" in w or "xbrl" in w:
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
    found = _units_in(text)
    return found.pop() if len(found) == 1 else None


def _units_in(text: str) -> set[float]:
    return {scale for rx, scale in cj._UNITS if scale != 1.0 and rx.search(text)}


def table_unit(page: Any, band: list[int]) -> float | None:
    """The unit the table itself prints: in its header band or on the figure-less lines just above it (the title and
    "(Rs. in lakh)" line), up to the previous table's last figure line or six lines up.  Exactly one unit there ->
    that unit; none -> None (the caller falls back to the page's single unit); several -> 0.0 (undecided, no
    fallback).  A page whose notes say "crore" while its table prints "lakh" lost every XBRL witness to the page
    rule (round 14, c01)."""
    m = band[0] - 1
    while m >= 0 and band[0] - m <= 6 and not any(page._digit_figure(j) for j in page.lines[m]):
        m -= 1
    text = " ".join(page.words[j][4] for n in range(m + 1, band[-1] + 1) for j in page.lines[n])
    found = _units_in(text)
    if not found:
        return None
    return found.pop() if len(found) == 1 else 0.0


_DOT_THOUSANDS = re.compile(r"\(?[-−]?\d{1,3}\.\d{3,5}\)?")


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
        counts = Counter(d[1] for d in dec if d)
        usual, n_usual = counts.most_common(1)[0] if counts else (0, 0)
        for c, d in zip(col, dec):
            # fewer decimals than the column prints: a dropped point ("3419685") or a dropped last digit ("293.2"
            # for 293.25, an OCR page, round 13 read; the XBRL rounding tolerance of one decimal let it agree)
            if d and d[0] != 0 and d[1] < usual and n_usual >= 3 and n_usual > len(col) / 2:
                continue
            # "1.877" for 1,877: an OCR page read the thousands comma as a point, the same way in two filings, so
            # cross-filing agreement passed it (c04 cash flow, 20 Nov). Three to five decimals behind at most three
            # digits, outside a per-share line, is that misread: refused, also when the whole column is misread
            # (usual 3: c04 p10) and in lakh grouping ("1.73403" for 1,73,403: c01 p2) (fourth review F1).
            if _DOT_THOUSANDS.fullmatch(c["value_text"].strip()) \
                    and not _PER_SHARE.search(f'{c.get("section", "")} {c["row_label"]}'):
                continue
            out.append(c)
    return out


def _quarter_ends_before(day: _dt.date, months: int = 24) -> list[str]:
    out, y, m = [], day.year, day.month
    for _ in range(months + 3):
        end = cj._month_end(y, m)
        if m % 3 == 0 and end and end < day.isoformat():
            out.append(end)
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def date_columns_by_xbrl(cells: list[dict[str, Any]], filed: Mapping[str, _dt.date], xbrl: Any) -> int:
    """A column whose header prints its period type but lost its date (OCR: "Year ended 31, 2024", "Quarter ended")
    takes a date only from XBRL agreement: each quarter end of the two years before the filing (of the months the
    kind allows, from the company's fiscal year end) is tried on every cell of the column; the column is dated when
    two or more of its cells agree exactly at ONE date and no cell agrees at another.  Its cells are then
    ``period_inferred`` and served only on their own XBRL witness (as fiscal labels are).  Returns columns dated."""
    if xbrl is None:
        return 0
    fy = fy_end_month(xbrl)
    allowed = {"quarter": None, "as_at": None}
    if fy:
        allowed.update({"year": {fy}, "half": {fy, (fy - 7) % 12 + 1}})   # no nine: the judge holds none (F4)
    cols: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for c in cells:
        if not c.get("period_end") and c.get("kind") in allowed and c.get("doc_key") in filed:
            cols[_column_key(c)].append(c)
    dated = 0
    for col in cols.values():
        kind, day = col[0]["kind"], filed[col[0]["doc_key"]]
        months = allowed[kind]
        cands = [e for e in _quarter_ends_before(day) if months is None or int(e[5:7]) in months]
        votes: dict[str, int] = defaultdict(int)
        for c in col:
            for e in cands:
                if _xbrl_agrees(dict(c, judge_header=_canonical_header(e, kind) if kind != "as_at"
                                     else f"As at {e[8:10]}.{e[5:7]}.{e[:4]}"), xbrl):
                    votes[e] += 1
        if len(votes) == 1 and next(iter(votes.values())) >= 2:
            e = next(iter(votes))
            hdr = _canonical_header(e, kind) if kind != "as_at" else f"As at {e[8:10]}.{e[5:7]}.{e[:4]}"
            for c in col:
                c["period_end"], c["period_inferred"], c["judge_header"] = e, True, hdr
            dated += 1
    return dated


def _inferred(c: dict[str, Any]) -> bool:
    """A cell whose period or basis was not printed but inferred (fiscal label, XBRL vote): served only on its own
    XBRL witness, and kept out of cross-filing pairing."""
    return bool(c.get("period_inferred") or c.get("basis_inferred"))


def basis_columns_by_xbrl(cells: list[dict[str, Any]], xbrl: Any) -> int:
    """A column whose page and header name neither basis, or both ("Standalone & Consolidated" over one column grid),
    takes a basis only from XBRL: the column is consolidated (standalone) when two or more of its cells agree exactly
    as consolidated (standalone) and none agrees as the other basis; a company whose two statements print equal
    figures stays undecided.  Its cells are ``basis_inferred`` (served only on their own XBRL witness).  Run after
    ``date_columns_by_xbrl``.  Returns columns given a basis (20 Nov: 2,336 cells refused as basis unknown)."""
    if xbrl is None:
        return 0
    cols: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for c in cells:
        if not c.get("basis") and c.get("period_end") and c.get("kind") not in ("", "unprinted"):
            cols[_column_key(c)].append(c)
    done = 0
    for col in cols.values():
        votes = {b: sum(_xbrl_agrees(dict(c, basis=b), xbrl) for c in col) for b in ("consolidated", "standalone")}
        won = [b for b, n in votes.items() if n >= 2]
        other = {"consolidated": "standalone", "standalone": "consolidated"}[won[0]] if len(won) == 1 else ""
        # "none agrees as the other" proves nothing where the other statement has no facts: at least one cell must
        # be refused by the other basis's own facts; and no cell's section caption may name the other basis
        # (sixth review F1: a standalone block over equal figures, with no standalone facts, was voted consolidated)
        if other and votes[other] == 0 and any(_xbrl_refuses(dict(c, basis=other), xbrl) for c in col) \
                and not any(cj.basis_of(c.get("section", "")) == other for c in col):
            for c in col:
                c["basis"], c["basis_inferred"] = won[0], True
            done += 1
    return done


_FLOW_TITLE = re.compile(r"profit|loss|income|results|revenue|cash\s*-?\s*flow", re.I)  # a page holding flows too
_BALANCE_SECTION = re.compile(r"segment\s+(assets|liabilit)|capital\s+employed", re.I)
_CONSOLIDATED_WORD = re.compile(r"c[o0]ns[o0]l|\bc\s?\w{0,8}dated\b", re.I)    # "Cansolldated", "C fidated"


def single_basis_company(cells: list[dict[str, Any]], xbrl: Any) -> int:
    """A company whose quarterly XBRL holds standalone facts and no consolidated fact at all files no consolidated
    results: a cell whose page and header name neither basis is standalone, unless its page title carries a
    consolidated word (also OCR-damaged: "Cansolldated", "C fidated").  Cells are ``basis_inferred`` (served only on
    their own XBRL witness).  20 Nov: 23 of 81 unmeasured stores served nothing, almost all standalone-only filers
    whose pages never print "Standalone".  Run before ``basis_columns_by_xbrl``.  Returns cells given the basis."""
    if xbrl is None:
        return 0
    bases = {basis for key, _end, basis, _item in getattr(xbrl, "by_key", {}) if key == cj.Q}
    if bases != {"standalone"}:
        return 0
    done = 0
    for c in cells:
        if not c.get("basis") and not _CONSOLIDATED_WORD.search(c.get("title", "") or ""):
            c["basis"], c["basis_inferred"] = "standalone", True
            done += 1
    return done
