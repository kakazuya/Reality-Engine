"""R-015 (T-222): read the printed cash-flow statement of every held annual report into ``fin_annual_line``.

``fin_annual_line`` held cash-flow rows only from XBRL (FY25 onward); the annual reports print the statement for
two years each (current and prior column), so FY23-FY24 cash flows sat in the store as page text with no row.

How a statement is read (no model):
1. Pages: every annual-report page whose text ``doc_map.yaml`` labels ``cash_flow`` AND whose printed title (top of
   the page) names a cash-flow statement; the next page is read too when the first one stops before the financing
   total (a statement often runs over two pages).
2. Words: ``v2.page_words.words_for`` (PDF text layer, OCR boxes where the layer is bad), grouped into printed
   lines.  A statement printed beside another one (changes in equity on the left) is cut at its title's left edge.
3. Columns: the header line(s) carrying two period-end dates ("31st March, 2024", "31.03.2024", "March 31, 2024")
   give the current and prior column centres; each number on a line goes to the nearer column, numbers far from
   both (note numbers, page-margin tabs) are dropped.
4. Unit from the page ("in Lakhs", "INR Millions", "in Crore"); no unit printed = no rows (unsure = no row).
5. Lines: the three activity totals, net change, opening and closing cash, profit before tax, depreciation, PP&E
   purchase and sale, tax, dividends and interest paid get their canonical ``line_item`` (same names as the XBRL
   rows; payments are stored with the sign turned, payment positive and a net refund negative, as XBRL does; the
   net line ``ppe_purchase_net_of_sale`` keeps its printed sign); each canonical line counts only in its own block,
   the FX effect only below the financing total, nothing is named after the closing cash (the cash-balance table
   under it); every other printed line is kept as ``cf_printed_line`` with its caption and printed sign.
6. Checks, per column: CFO + CFI + CFF = net change (or opening + the three = closing), within the printed
   rounding.  A column that fails, or prints no total, writes nothing and is reported.  Where XBRL rows exist for
   that year and basis, the store keeps XBRL (filed figures stay as filed) and the printed totals are only compared
   with it: the agreement rate measures this reader.
7. One row per (year, basis, line): the current column of that year's own report first, else the prior column of
   the next year's report (its ``definition`` says so).  ``known_at`` is the report's own filing time.

    python -m reality_engine.pilot3.ar_statements run --root D:/RealityEngine/tg_build/measure10 [--stores c16] [--dry]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import statistics
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from reality_engine.pilot3 import doc_map, fiscal
from reality_engine.v2.page_words import words_for
from reality_engine.v2.reference_geom import lines_of

SOURCE_TABLE = "ar_statement"
Word = tuple[float, float, float, float, str]

_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
# A period-end date as printed in a column header.
_DATE_RES = (
    re.compile(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[,.]?\s*(20\d\d)", re.I),
    re.compile(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(\d{1,2})\s*(?:st|nd|rd|th)?[,.]?\s*(20\d\d)", re.I),
    re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](20\d\d)"),
)
_TITLE = re.compile(r"cash\s*-?\s*flows?\s+statement|statement\s+of\s+cash\s*-?\s*flows?|cash\s*-?\s*flows?\s+for\s+the", re.I)
_NOT_TITLE = re.compile(r"notes?\s+to\s+(the\s+)?(consolidated\s+|standalone\s+)?financial|^\s*notes?\b", re.I)
_UNITS = (
    (re.compile(r"\b(lakhs?|lacs?)\b", re.I), "inr_lakh", 1e5),
    (re.compile(r"\b(crores?|crs?\.?)\b", re.I), "inr_crore", 1e7),
    (re.compile(r"\b(millions?|mn)\b", re.I), "inr_million", 1e6),
    (re.compile(r"\bthousands?\b|['\u2019`]\s*000\b", re.I), "inr_thousand", 1e3),
)
_NUM = re.compile(r"^\(?-?[\d,]*\d(\.\d+)?\)?$")
_DASH = {"-", "–", "—", "--", "nil", "Nil", "NIL"}

# canonical line -> label pattern; first match wins, checked in this order.  ``total`` lines take the LAST numbered
# line that matches (the header line of a block carries no numbers, the total does).
# property, plant and equipment: not 'intangible', not a bare 'investment property'
_PPE = (r"(property,?\s+plant|\bplant\b|fixed\s+assets|\bppe\b|capital\s+work|(?<!in)tangible\s+assets"
        r"|(?<!investment\s)\bpropert(y|ies)\b)")
LINES: tuple[tuple[str, re.Pattern, bool], ...] = (
    # only below the financing total, or naming cash (see ``canonical``): an operating 'foreign currency
    # translation' adjustment is not the effect on cash
    ("fx_effect_on_cash", re.compile(r"exchange|foreign\s+currency|translation", re.I), False),
    ("net_change_in_cash", re.compile(r"^(?!.*(other\s+than|bank\s+balances?|deposits?|margin)).*\bnet\s+(\(?increase\)?|\(?decrease\)?|change|changes|movement)\b.*cash|^total\s+cash\s+flow|net\s+cash\s+flows?\s+(for|during)\s+the\s+year", re.I), False),
    ("cash_at_beginning", re.compile(r"cash.*(beginning|opening|start)|(opening|beginning)\s+(balance\s+of\s+)?cash", re.I), False),
    ("cash_at_end", re.compile(r"cash.*(\bend\b|closing)|closing\s+(balance\s+of\s+)?cash", re.I), False),
    ("cash_flow_from_operations", re.compile(r"operating\s+activit", re.I), True),
    ("cash_flow_from_investing", re.compile(r"investing\s+activit", re.I), True),
    ("cash_flow_from_financing", re.compile(r"financing\s+activit", re.I), True),
    ("profit_before_tax", re.compile(r"(profit|loss|income).*before\s+(income\s+)?tax", re.I), False),
    ("depreciation", re.compile(r"depreciation", re.I), False),
    ("income_tax_paid", re.compile(r"(income\s+)?tax(es)?\s+(paid|\(paid\))|direct\s+tax(es)?\s+paid|tax\s+paid|payment\s+of\s+(income\s+)?tax", re.I), False),
    ("ppe_purchase_net_of_sale", re.compile(
        r"((purchase|acquisition|addition)s?\b.*(sale|disposal|proceeds)|(sale|disposal|proceeds)\b.*(purchase|acquisition|addition)"
        r"|net\s+of\s+(sale|disposal)).*" + _PPE + "|" + _PPE + r".*\(net\)", re.I), False),
    ("purchase_of_ppe", re.compile(r"(purchase|acquisition|payment|addition|expenditure)s?\b.*" + _PPE + r"|capital\s+expenditure", re.I), False),
    ("sale_of_ppe", re.compile(r"(proceeds|sale|disposal).*" + _PPE, re.I), False),
    ("dividends_paid", re.compile(r"^(?!.*non[- ]controlling)(?!.*minority).*(dividends?\s+(paid|\(paid\))|payment\s+of\s+dividend|dividend\s+payment)", re.I), False),
)
# printed as a payment: stored with the sign turned (payment positive) like the XBRL rows of the same name;
# ``ppe_purchase_net_of_sale`` is a net figure and keeps its printed sign
# lines that count only inside their own block (an operating adjustment 'loss on sale of PPE' is not a sale)
_SECTION_OF_LINE = {"income_tax_paid": "operating", "purchase_of_ppe": "investing", "sale_of_ppe": "investing",
                    "ppe_purchase_net_of_sale": "investing", "dividends_paid": "financing"}
_PAYMENTS = {"purchase_of_ppe", "income_tax_paid", "dividends_paid", "interest_paid"}
# interest paid on borrowings: not lease interest, not interest received
_INTEREST_PAID = re.compile(r"^(?!.*(lease|received|non[- ]?controlling|minority|accrued|proceeds|dividend|income))"
                            r".*(interest|finance\s+(cost|charge)s?|borrowing\s+costs?)", re.I)
_NOTES_START = re.compile(r"notes?\s+to\s+(the\s+)?|accounting\s+polic|corporate\s+information|statement\s+of\s+changes", re.I)
# page furniture printed with a number ('Annual Report 2024-25  105'): never a statement line
_FURNITURE = re.compile(r"annual\s+report|integrated\s+report|^page\b|^\W*$|statutory\s+reports|financial\s+statements\s*$"
                        r"|indirect\s+method|prepared\s+under|ind\s*as\s*-?\s*7\b|figures\s+in\s+brackets"
                        r"|previous\s+year'?s?\s+figures|regrouped|^notes?\s*:", re.I)
# the statement ends at its signature block
_SIGNATURE = re.compile(r"as\s+per\s+our\s+(attached\s+)?report|in\s+terms\s+of\s+our\s+report|for\s+and\s+on\s+behalf\s+of|chartered\s+accountants", re.I)
_SKIP_LABEL = re.compile(r"^(particulars|notes?|for the year|year ended|as at|\(?[a-e]\)?\.?)$", re.I)


@dataclass
class Line:
    label: str
    values: list  # [current, prior] floats or None
    decimals: int
    quote: str
    page: int
    section: str = ""


@dataclass
class Statement:
    doc_key: str
    page: int
    basis: str
    unit: str
    scale: float
    ends: list  # [current_end, prior_end] ISO dates
    lines: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    starts: dict = field(default_factory=dict)  # period end -> printed start, for a 'from - to' (part-year) column


def _date_of(text: str) -> list[tuple[int, int, str]]:
    """(start, end, ISO date) of every period-end date printed in ``text``."""
    out = []
    for n, rx in enumerate(_DATE_RES):
        for m in rx.finditer(text):
            g = m.groups()
            try:
                if n == 0:
                    d, mo, y = int(g[0]), _MONTHS[g[1][:3].lower()], int(g[2])
                elif n == 1:
                    mo, d, y = _MONTHS[g[0][:3].lower()], int(g[1]), int(g[2])
                else:
                    d, mo, y = int(g[0]), int(g[1]), int(g[2])
                if 1 <= d <= 31 and 1 <= mo <= 12:
                    out.append((m.start(), m.end(), f"{y:04d}-{mo:02d}-{d:02d}"))
            except (KeyError, ValueError):
                continue
    return sorted(out)


def fiscal_label(end: str) -> str:
    """FY label of a period end: March 2024 -> FY24 (a year ending Dec under default March preserves FY{yy})."""
    m = int(end[5:7])
    return fiscal.fy_label(end, 12 if m == 12 and fiscal.current() == 3 else None)


def number(tok: str) -> tuple[float, int] | None:
    """Printed number -> (value, decimals); '(1,234.50)' -> (-1234.5, 2); '-' -> (0.0, 0)."""
    t = tok.strip().rstrip("\u031c").replace("\u2212", "-")
    if t in _DASH:
        return 0.0, 0
    t = t.strip("*#")
    if not t or not _NUM.match(t):
        # a damaged bracket ('22.69)' / '(12.02') still reads as a negative
        if re.match(r"^\(?[\d,]*\d(\.\d+)?\)?$", t or "x") is None:
            return None
    neg = t.startswith("(") or t.endswith(")") or t.startswith("-")
    core = t.strip("()-").replace(",", "")
    try:
        v = float(core)
    except ValueError:
        return None
    dec = len(core.split(".")[1]) if "." in core else 0
    return (-v if neg else v), dec


def _is_number_word(tok: str) -> bool:
    return number(tok) is not None and any(c.isdigit() for c in tok) or tok.strip() in _DASH


# the title of another block printed on the same line as the cash-flow title (not a unit or a date)
_OTHER_BLOCK = re.compile(r"notes?\s+to|statement\s+of|balance\s+sheet|changes\s+in\s+equity|profit\s+and\s+loss", re.I)


def _crop(words: list[Word]) -> list[Word]:
    """A cash-flow statement printed beside another page block (changes in equity on the left, notes on the right,
    each with its own title on the same printed line): keep the words between the left edge of the cash-flow
    title's word group and the left edge of the next title group on that line.  A title alone on its line (centred
    or not) crops nothing."""
    for line in lines_of(words)[:12]:
        text, spans = _spans(words, line)
        m = _TITLE.search(text)
        if not m:
            continue
        j = next((n for n, (a, b, _) in enumerate(spans) if b > m.start()), None)
        e = next((n for n, (a, b, _) in enumerate(spans) if b >= m.end()), len(line) - 1)
        if j is None:
            return words
        while j > 0 and words[line[j]][0] - words[line[j - 1]][2] < 15:
            j -= 1
        while e + 1 < len(line) and words[line[e + 1]][0] - words[line[e]][2] < 15:
            e += 1
        left = " ".join(words[i][4] for i in line[:j])
        right = " ".join(words[i][4] for i in line[e + 1:])
        # a block that is the statement's own '(contd.)' half is kept
        x0 = (words[line[j]][0] - 6 if j > 0 and _OTHER_BLOCK.search(left) and not _TITLE.search(left)
              else float("-inf"))
        x1 = (words[line[e + 1]][0] - 6 if e + 1 < len(line) and _OTHER_BLOCK.search(right) and not _TITLE.search(right)
              else float("inf"))
        if x0 == float("-inf") and x1 == float("inf"):
            return words
        return [w for w in words if x0 <= w[0] < x1]
    return words


def _part_year(start: str, end: str) -> bool:
    """A 'from - to' period shorter than a year ('11 February 2024 to 31 March 2025' is longer: still flagged when
    it is not a plain twelve months); '01 April 2024 to 31 March 2025' is a full year."""
    from datetime import date
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return False
    return not 360 <= days <= 366


def _halves(words: list[Word]) -> list[list[Word]]:
    """A statement printed in two halves side by side, each under the cash-flow title (the right one with or
    without '(Contd.)'): [left words, right words] in reading order; otherwise [words]."""
    for line in lines_of(words)[:12]:
        text, spans = _spans(words, line)
        found = list(_TITLE.finditer(text))
        if len(found) < 2:
            continue
        j = next((n for n, (a, b, _) in enumerate(spans) if b > found[1].start()), None)
        e = next((n for n, (a, b, _) in enumerate(spans) if b >= found[0].end()), None)
        if j is None or e is None or j <= e:
            return [words]
        # walk left over the right title's own words ('CONSOLIDATED CASH FLOW ...'), never into the left title
        while j > e + 1 and words[line[j]][0] - words[line[j - 1]][2] < 15:
            j -= 1
        if words[line[j]][0] - words[line[j - 1]][2] < 15:
            return [words]   # the two titles run together: no gap to split at
        x = words[line[j]][0] - 6
        return [[w for w in words if w[0] < x], [w for w in words if w[0] >= x]]
    return [words]


def _unit(text: str) -> tuple[str, float] | None:
    head = text[:1500]
    for rx, unit, scale in _UNITS:
        if rx.search(head):
            return unit, scale
    return None


_CONS = re.compile(r"consolidated", re.I)
_STAND = re.compile(r"stand[- ]?alone", re.I)


def _basis(words: list[Word], lines: list[list[int]]) -> str | None:
    """'consolidated' / 'standalone' from the statement's own title line and the lines beside it; a running header
    or tab bar naming both ('Standalone | Consolidated') decides nothing."""
    texts = [" ".join(words[i][4] for i in ln) for ln in lines[:12]]
    t = next((n for n, x in enumerate(texts) if _TITLE.search(x)), None)
    near = texts[max(t - 1, 0): t + 2] if t is not None else []
    for scope in (near, texts):
        joined = " ".join(scope)
        c, s_ = bool(_CONS.search(joined)), bool(_STAND.search(joined))
        if c != s_:
            return "consolidated" if c else "standalone"
    return None


def _spans(words: list[Word], line: list[int]) -> tuple[str, list[tuple[int, int, int]]]:
    pos, spans = 0, []
    for i in line:
        spans.append((pos, pos + len(words[i][4]), i))
        pos += len(words[i][4]) + 1
    return " ".join(words[i][4] for i in line), spans


def _centre(words: list[Word], spans, a: int, b: int) -> float | None:
    ws = [i for s, e, i in spans if s < b and e > a]
    if not ws:
        return None
    return (min(words[i][0] for i in ws) + max(words[i][2] for i in ws)) / 2


def _columns(words: list[Word], lines: list[list[int]]) -> tuple[list[float], list[str]] | None:
    """Centres (x) of the current and prior columns and their period ends, from the header lines."""
    for n, line in enumerate(lines[:30]):
        text, spans = _spans(words, line)
        dates = _date_of(text)
        # a 'from - to' column ('11 February 2024 to 31 March 2025'): its period end is the 'to' date
        dates = [d for n_, d in enumerate(dates)
                 if not (n_ + 1 < len(dates) and re.fullmatch(r"\s*(to|-|–|—)\s*", text[d[1]:dates[n_ + 1][0]], re.I))]
        # ... or a 'from ... to' that wraps: the line ends in 'to' and its 'to' date is on the next printed line,
        # under it; that date takes its place (same column)
        if dates and re.fullmatch(r"\s*(to|-|–|—)\s*", text[dates[-1][1]:], re.I) and n + 1 < len(lines):
            below, bspans = _spans(words, lines[n + 1])
            bd = _date_of(below)
            if bd:
                dates[-1] = (dates[-1][0], dates[-1][1], bd[0][2])
        # the first adjacent pair from the left: a block printed to the right of the statement ('(Contd.)' and its
        # own header) must not lend its columns
        for (a0, b0, e0), (a1, b1, e1) in zip(dates, dates[1:]):
            c0, c1 = _centre(words, spans, a0, b0), _centre(words, spans, a1, b1)
            if c0 is not None and c1 is not None and c1 > c0 and e0 > e1:
                return [c0, c1], [e0, e1]
        # fiscal-year headers: '2024-25  2023-24' / 'FY 2024-25'
        fys = [(i, int(m.group(1))) for i in line
               if (m := re.fullmatch(r"(?:FY\s*)?(20\d\d)\s*-\s*\d{2,4}", words[i][4].strip(" ,.)")))]
        if len(fys) == 2 and fys[0][1] == fys[1][1] + 1:
            centres = [(words[i][0] + words[i][2]) / 2 for i, _ in fys]
            return centres, [fiscal.fy_end_date(fys[0][1] + 1), fiscal.fy_end_date(fys[1][1] + 1)]
        # a date split over two printed lines ('As At March' / '31, 2025   31, 2024'): two year tokens at the
        # right, the month from the line above (fiscal year-end month when none is printed)
        years = [(i, int(words[i][4].strip(" ,.)")[-4:])) for i in line
                 if re.fullmatch(r"20\d\d", words[i][4].strip(" ,.)"))]
        if len(years) == 2 and years[0][1] == years[1][1] + 1 and n > 0:
            above, _ = _spans(words, lines[n - 1])
            mo = next((v for k, v in _MONTHS.items() if re.search(rf"\b{k}", above, re.I)), fiscal.current())
            text_days = re.findall(r"(\d{1,2})\s*,", text)
            day = int(text_days[0]) if text_days else (31 if mo in (1, 3, 5, 7, 8, 10, 12) else 30)
            centres = []
            for i, _ in years:
                # the year and the day printed before it form the column header
                j = line.index(i)
                left = words[line[j - 1]][0] if j > 0 and re.fullmatch(r"\d{1,2}(st|nd|rd|th)?,?", words[line[j - 1]][4]) else words[i][0]
                centres.append((left + words[i][2]) / 2)
            return centres, [f"{years[0][1]:04d}-{mo:02d}-{day:02d}", f"{years[1][1]:04d}-{mo:02d}-{day:02d}"]
    return None


def _norm(words: list[Word]) -> list[Word]:
    return [(w[0], w[1], w[2], w[3], unicodedata.normalize("NFKC", w[4])) for w in words]


_HEADER_LINE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|year\s+ended|as\s+at", re.I)


def _columns_from_body(words: list[Word], lines: list[list[int]]) -> tuple[list[float], list[str]] | None:
    """Headers printed as 'Current Year / Previous Year' or with the year on its own line: the column centres come
    from the numbers themselves (the two most-filled x clusters, current on the left) and the period ends from the
    date in the statement's title (prior = one year earlier).  The CFO+CFI+CFF check then decides."""
    title_end = None
    for line in lines[:12]:
        text = " ".join(words[i][4] for i in line)
        if _TITLE.search(text) or re.search(r"year\s+ended|period\s+ended|\bto\b", text, re.I):
            dates = _date_of(text)
            if dates:
                title_end = dates[-1][2]
                break
    if title_end is None:
        return None
    xs = sorted((words[i][0] + words[i][2]) / 2 for ln in lines for i in ln
                if re.fullmatch(r"\(?-?[\d,]*\d\.\d{1,2}\)?|\(?\d{1,3}(,\d{2,3})+\)?", words[i][4]))
    if len(xs) < 10:
        return None
    clusters, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] > 20:
            clusters.append(cur)
            cur = [x]
        else:
            cur.append(x)
    clusters.append(cur)
    big = sorted(sorted(clusters, key=len, reverse=True)[:2], key=lambda c: c[0])
    if len(big) < 2 or len(big[1]) < 5:
        return None
    centres = [statistics.median(c) for c in big]
    y = int(title_end[:4])
    ends = [title_end, f"{y - 1:04d}{title_end[4:]}"]
    # current is the left column unless the header prints 'Previous' left of 'Current'
    for line in lines[:15]:
        text = " ".join(words[i][4] for i in line).lower()
        if "current" in text and "previous" in text and text.index("previous") < text.index("current"):
            ends.reverse()
            break
        # a header printed oldest first ('31.03.2023   31.03.2024', or years alone): the older is the left column
        years = [int(y) for y in re.findall(r"(?<!\d)(20\d\d)(?!\d)", text)]
        if len(years) == 2 and years[1] == years[0] + 1 and not _TITLE.search(text) and not re.search(r"\bto\b|-\s*20", text):
            if years[0] < years[1]:
                ends.reverse()
            break
    return centres, ends


def _read_lines(words: list[Word], centres: list[float], page: int) -> list[Line]:
    out: list[Line] = []
    lines = lines_of(words)
    gap = abs(centres[1] - centres[0])
    for line in lines:
        label_words, vals = [], [None, None]
        decs = [0, 0]
        kept = []
        for i in line:
            tok = words[i][4]
            if words[i][0] > centres[1] + 0.7 * gap:
                continue  # right of the prior column: another block printed beside the statement
            kept.append(i)
            xc = (words[i][0] + words[i][2]) / 2
            d = [abs(xc - c) for c in centres]
            k = 0 if d[0] <= d[1] else 1
            parsed = number(tok) if (any(ch.isdigit() for ch in tok) or tok.strip() in _DASH) else None
            if parsed is not None and d[k] <= 0.6 * gap and words[i][0] > centres[0] - 1.6 * gap:
                if vals[k] is None:
                    vals[k], decs[k] = parsed
                continue
            if parsed is not None and words[i][0] > centres[0] - 0.9 * gap:
                continue  # a note number or margin tab near the columns
            label_words.append(tok)
        label = " ".join(label_words).strip()
        if vals == [None, None]:
            if label:
                out.append(Line(label, vals, 0, label, page))
            continue
        quote = " ".join(words[i][4] for i in kept)
        if _HEADER_LINE.search(quote) and all(v is None or (v == int(v) and 1990 <= abs(v) <= 2100) for v in vals):
            continue  # a column header ('31st March 2024   31st March 2023'), not a figure
        out.append(Line(label, vals, max(decs), quote, page))
    stop = next((n for n, ln in enumerate(out) if _SIGNATURE.search(ln.label)), len(out))
    out = [ln for ln in out[:stop] if not (ln.values != [None, None] and _FURNITURE.search(ln.label))]
    # a label printed over two lines ('Trade payables, other liabilities' / 'and provisions  547.10 (122.25)'):
    # a numbered line whose label starts in lower case takes the label of the bare line above it
    merged: list[Line] = []
    for ln in out:
        if (merged and ln.values != [None, None] and merged[-1].values == [None, None] and ln.label[:1].islower()):
            ln.label = f"{merged[-1].label} {ln.label}"
            merged[-1] = ln
            continue
        # ... and a bare continuation after a numbered line: lower-case, or one or two words that are not a block
        # header ('(Increase)/Decrease in Financial and Other' / 'Assets')
        # only when the numbered label is visibly cut ('... in Financial and Other' / 'Assets'): it ends in a
        # joining word, or the tail is a bracket ('(A+B+C)'); a sub-header ('Current Liabilities') after a complete
        # label is not joined
        cut = bool(merged) and bool(re.search(r"\b(and|of|in|at|on|for|to|the|from|with|by|other|financial|non)\s*$|[&,/-]\s*$",
                                              merged[-1].label, re.I))
        short_tail = ((cut or (ln.label.startswith("(") and "cont" not in ln.label.lower()))
                      and len(ln.label.split()) <= 2 and not ln.label.rstrip().endswith(":")
                      and not re.search(r"activit|^[a-e]\W|adjust|^less|^add|particulars|changes?\s+in|working", ln.label, re.I)
                      and not _SIGNATURE.search(ln.label) and not _NOTES_START.search(ln.label)
                      and not _FURNITURE.search(ln.label) and not _TITLE.search(ln.label)
                      and not re.search(r"\bnotes?\b|\d", ln.label, re.I))
        if (merged and ln.values == [None, None] and merged[-1].values != [None, None]
                and (ln.label[:1].islower() or short_tail) and len(ln.label) < 60):
            merged[-1].label = f"{merged[-1].label} {ln.label}"
            continue
        merged.append(ln)
    return merged


def _section_of(label: str, current: str) -> str:
    low = label.lower()
    for name in ("operating", "investing", "financing"):
        if re.search(rf"{name}\s+activit", low):
            return name
    return current


def canonical(lines: list[Line]) -> dict[str, Line]:
    """Canonical line -> the printed line it comes from."""
    out: dict[str, Line] = {}
    section = ""
    interest: list[Line] = []
    for ln in lines:
        section = _section_of(ln.label, section)
        ln.section = section
        if "cash_at_end" in out:
            ln.section = "cash_components"   # the cash-balance table printed under the closing cash names nothing
            continue
        if ln.values == [None, None] or not ln.label or _SKIP_LABEL.match(ln.label):
            continue
        low = ln.label.lower()
        for name, rx, total in LINES:
            if not rx.search(low):
                continue
            if _SECTION_OF_LINE.get(name, section) != section:
                continue
            if name == "fx_effect_on_cash" and "cash_flow_from_financing" not in out and "cash" not in low:
                continue  # an operating 'foreign currency translation' adjustment, not the effect on cash
            if name.startswith("cash_flow_from") and re.search(r"before|working\s+capital|exceptional", low):
                continue
            if name == "cash_at_end" and "beginning" in low:
                continue
            if total or name not in out:
                out[name] = ln
            break
        else:
            if section == "financing" and _INTEREST_PAID.search(low):
                interest.append(ln)
    # interest paid: a financing line naming interest or finance cost, one that says 'paid' first
    if interest:
        out["interest_paid"] = next((ln for ln in interest if re.search(r"\bpaid\b|payment", ln.label, re.I)), interest[0])
    return out


def check_column(c: dict[str, Line], k: int) -> tuple[bool, str]:
    """CFO + CFI + CFF = net change, or opening + the three = closing, within the printed rounding."""
    def v(name):
        ln = c.get(name)
        return None if ln is None else ln.values[k]

    cfo, cfi, cff = v("cash_flow_from_operations"), v("cash_flow_from_investing"), v("cash_flow_from_financing")
    if None in (cfo, cfi, cff):
        return False, "a total is missing"
    dec = max(c[n].decimals for n in ("cash_flow_from_operations", "cash_flow_from_investing", "cash_flow_from_financing"))
    tol = 3.5 * 10 ** (-dec) + 0.0005 * max(abs(cfo), abs(cfi), abs(cff))
    fx = v("fx_effect_on_cash") or 0.0
    s = cfo + cfi + cff
    net, beg, end = v("net_change_in_cash"), v("cash_at_beginning"), v("cash_at_end")
    if net is not None and abs(s - net) <= tol:
        return True, "cfo+cfi+cff=net change"
    if beg is not None and end is not None and abs(beg + s - end) <= tol + 0.001 * abs(end):
        return True, "opening+cfo+cfi+cff=closing"
    if fx and beg is not None and end is not None and abs(beg + s + fx - end) <= tol + 0.001 * abs(end):
        return True, "opening+cfo+cfi+cff+fx effect=closing"
    if fx and net is not None and abs(s + fx - net) <= tol:
        return True, "cfo+cfi+cff+fx effect=net change"
    if net is None and (beg is None or end is None):
        return False, "no net change or opening/closing printed"
    return False, f"sum {s:.2f} vs net {net} / opening {beg} closing {end}"


def read_statement(store_db: str, doc_key: str, page: int, text: str, next_text: str | None) -> Statement | None:
    pw = words_for(store_db, doc_key, page)
    if not pw.words:
        return None
    halves = _halves(_norm(pw.words))
    words = _crop(halves[0])
    lines = lines_of(words)
    head = " ".join(words[i][4] for ln in lines[:8] for i in ln)
    if not _TITLE.search(head) or _NOT_TITLE.search(head[:80]):
        return None
    cols = _columns(words, lines) or _columns_from_body(words, lines)
    unit = _unit(" ".join(words[i][4] for ln in lines[:14] for i in ln)) or _unit(text)
    st = Statement(doc_key, page, _basis(words, lines) or "", unit[0] if unit else "", unit[1] if unit else 0.0,
                   cols[1] if cols else [])
    if not cols:
        st.problems.append("no two period-end columns in the header")
        return st
    if not unit:
        st.problems.append("no unit printed")
        return st
    for n, ln in enumerate(lines[:30]):
        text = " ".join(words[i][4] for i in ln)
        ds = _date_of(text)
        for (a0, b0, d0), (a1, b1, d1) in zip(ds, ds[1:]):
            if re.fullmatch(r"\s*(to|-|–|—)\s*", text[b0:a1], re.I) and d1 in st.ends:
                if _part_year(d0, d1):
                    st.starts[d1] = d0
        if ds and re.fullmatch(r"\s*(to|-|–|—)\s*", text[ds[-1][1]:], re.I) and n + 1 < len(lines):
            below = _date_of(" ".join(words[i][4] for i in lines[n + 1]))
            if below and below[0][2] in st.ends:
                if _part_year(ds[-1][2], below[0][2]):
                    st.starts[below[0][2]] = ds[-1][2]
    st.lines = _read_lines(words, cols[0], page)
    if len(halves) == 2:
        # the right half continues the statement under its own header: its own columns, the same period ends
        right = halves[1]
        rl = lines_of(right)
        c2 = _columns(right, rl) or _columns_from_body(right, rl)
        if c2 and c2[1] == st.ends:
            st.lines += _read_lines(right, c2[0], page)
        # else: the right half is not a continuation (notes to the statement under the same title): left half
        # alone, and the CFO+CFI+CFF check decides
    have = canonical(st.lines)
    ends_early = "cash_flow_from_financing" not in have or not ({"net_change_in_cash", "cash_at_end"} & set(have))
    if ends_early and next_text is not None:
        nw = words_for(store_db, doc_key, page + 1)
        if nw.words:
            w2 = _crop(_norm(nw.words))
            l2 = lines_of(w2)
            h2 = " ".join(w2[i][4] for ln in l2[:6] for i in ln)
            # a new statement starts on that page (the consolidated one after the standalone): not a continuation
            other_basis = _basis(w2, l2) not in (None, st.basis)
            starts_new = any(re.search(r"operating\s+activit", " ".join(w2[i][4] for i in ln), re.I) for ln in l2[:12])
            new_title = bool(_TITLE.search(h2)) and not re.search(r"cont", h2, re.I)
            if (not re.search(r"balance\s+sheet|statement\s+of\s+changes|statement\s+of\s+profit", h2, re.I)
                    and not (new_title and (other_basis or starts_new)) and not starts_new):
                c2 = _columns(w2, l2)
                centres = c2[0] if c2 and c2[1] == st.ends else cols[0]
                more = _read_lines(w2, centres, page + 1)
                stop = next((n for n, ln in enumerate(more) if _NOTES_START.search(ln.label) or (
                    n > 2 and _TITLE.search(ln.label) and not re.search(r"cont", ln.label, re.I)
                    and any(re.search(r"operating\s+activit", x.label, re.I) for x in more[n + 1:]))), len(more))
                st.lines += more[:stop]
    return st


@dataclass
class Row:
    fiscal_year: str
    period_end: str
    basis: str
    line_item: str
    caption: str
    value: float
    unit: str
    scale: float
    doc_key: str
    page: int
    quote: str
    known_at: str
    definition: str
    is_derived: int = 0
    own: bool = False      # the current column of the year's own report
    source: str = ""       # doc_key#p<page>#<column>: the one statement column the row comes from


def rows_of(st: Statement, known_at: str, check_log: list) -> list[Row]:
    c = canonical(st.lines)
    out: list[Row] = []
    for k, col in ((0, "current"), (1, "prior")):
        ok, why = check_column(c, k)
        end = st.ends[k]
        fy = fiscal_label(end)
        check_log.append({"doc_key": st.doc_key, "page": st.page, "basis": st.basis, "column": col,
                          "fiscal_year": fy, "ok": ok, "why": why})
        if not ok:
            continue
        own, source = end == max(st.ends), f"{st.doc_key}#p{st.page}#{col}"
        named = {id(ln): name for name, ln in c.items()}
        for ln in st.lines:
            v = ln.values[k]
            if v is None or not ln.label:
                continue
            name = named.get(id(ln), "cf_printed_line")
            value = -v if name in _PAYMENTS else v   # a printed outflow (x) becomes a positive payment; a net refund stays negative
            out.append(Row(fy, end, st.basis, name, ln.label[:200], value, st.unit, st.scale, st.doc_key, ln.page,
                           ln.quote[:300], known_at,
                           f"ar_statement_reader: {col} column, {why}"
                           + (", sign turned: payment positive, net refund negative" if name in _PAYMENTS else "")
                           + (f", section {ln.section}" if ln.section else "")
                           + (f", part year from {st.starts[end]}" if end in st.starts else ""), 0, own, source))
        if "purchase_of_ppe" in c and c["purchase_of_ppe"].values[k] is not None:
            p = -c["purchase_of_ppe"].values[k]
            out.append(Row(fy, end, st.basis, "capex", "capex = -(purchase of PPE), cash-flow sign (outflow negative)",
                           -p, st.unit, st.scale, st.doc_key, c["purchase_of_ppe"].page, c["purchase_of_ppe"].quote[:300],
                           known_at, f"ar_statement_reader: derived from the {col} column", 1, own, source))
    return out


def pick_statements(candidates: list[Row]) -> list[Row]:
    """One statement column per (year, basis), whole: the year's own report (current column) first, else the latest
    report's prior column.  Rows of two reports are never mixed (a restated or renamed line would duplicate)."""
    best: dict[tuple, tuple] = {}
    for r in candidates:
        rank = (r.own, r.known_at, r.source)
        key = (r.fiscal_year, r.basis)
        if key not in best or rank > best[key]:
            best[key] = rank
    return [r for r in candidates if (r.own, r.known_at, r.source) == best[(r.fiscal_year, r.basis)]]


def _xbrl(conn: sqlite3.Connection) -> dict:
    out = {}
    for fy, basis, item, value, scale in conn.execute(
            "SELECT fiscal_year, basis, line_item, value, scale FROM fin_annual_line WHERE statement='CF' "
            "AND source_table='facts' AND period_type='FY'"):
        out[(fy, basis, item)] = (value or 0) * (scale or 1)
    return out


def run_store(db: Path, store: str, dry: bool = False) -> dict:
    head_chars, sections = doc_map.load()
    conn = sqlite3.connect(db if not dry else f"file:{db.as_posix()}?mode=ro", uri=dry)
    sym, isin = conn.execute("SELECT symbol, isin FROM company LIMIT 1").fetchone()
    with fiscal.use(fiscal.fy_end_month(conn, sym)):
        docs = conn.execute("SELECT doc_key, filing_date, known_at FROM doc WHERE doc_type='annual_report'").fetchall()
        statements, check_log = [], []
        for doc_key, filing_date, known_at in docs:
            pages = dict(conn.execute("SELECT page, text FROM doc_page WHERE doc_key=?", (doc_key,)).fetchall())
            for page in sorted(pages):
                if "cash_flow" not in doc_map.label(pages[page] or "", "annual_report", sections, head_chars):
                    continue
                st = read_statement(str(db), doc_key, page, pages[page] or "", pages.get(page + 1))
                if st is None:
                    continue
                st.known_at = known_at or filing_date or ""
                statements.append(st)
        # a statement with no printed basis is standalone unless it is the report's second statement
        by_doc: dict[str, list[Statement]] = {}
        for st in statements:
            by_doc.setdefault(st.doc_key, []).append(st)
        for sts in by_doc.values():
            unknown = [st for st in sts if not st.basis]
            named = {st.basis for st in sts if st.basis}
            for st in unknown:
                if len(unknown) == 1 and "standalone" not in named:
                    st.basis = "standalone"   # the report's only unnamed statement, and no other standalone one
                else:
                    st.problems.append("basis not printed and the report holds another unnamed statement")
        candidates: list[Row] = []
        for st in statements:
            if st.problems:
                check_log.append({"doc_key": st.doc_key, "page": st.page, "basis": st.basis, "column": "",
                                  "fiscal_year": "", "ok": False, "why": "; ".join(st.problems)})
                continue
            candidates += rows_of(st, st.known_at, check_log)
        xbrl = _xbrl(conn)
        # XBRL agreement on the printed totals; XBRL years keep XBRL rows only
        agree = []
        chosen = pick_statements(candidates)
        xbrl_years = {(fy, b) for fy, b, _ in xbrl}
        rows = []
        for r in chosen:
            if r.line_item in ("cash_flow_from_operations", "cash_flow_from_investing", "cash_flow_from_financing"):
                x = xbrl.get((r.fiscal_year, r.basis, r.line_item))
                if x is not None:
                    v = r.value * r.scale
                    agree.append({"fiscal_year": r.fiscal_year, "basis": r.basis, "line_item": r.line_item,
                                  "printed": v, "xbrl": x, "ok": abs(v - x) <= 0.005 * max(abs(x), 1) + r.scale})
            if (r.fiscal_year, r.basis) not in xbrl_years:
                rows.append(r)
        if not dry:
            conn.execute("DELETE FROM fin_annual_line WHERE source_table=? AND symbol=?", (SOURCE_TABLE, sym))
            conn.executemany(
                "INSERT INTO fin_annual_line (symbol, isin, fiscal_year, period_end, basis, statement, line_item, caption, "
                "value, unit, scale, doc_key, page, quote, source_db, source_table, source_rowid, known_at, "
                "known_at_source, is_reported, is_derived, definition, period_type) "
                "VALUES (?,?,?,?,?,'CF',?,?,?,?,?,?,?,?,'doc_page',?,?,?,'doc.known_at',?,?,?,'FY')",
                [(sym, isin, r.fiscal_year, r.period_end, r.basis, r.line_item, r.caption, r.value, r.unit, r.scale,
                  r.doc_key, r.page, r.quote, SOURCE_TABLE, f"{r.doc_key}#p{r.page}", r.known_at, 1 - r.is_derived,
                  r.is_derived, r.definition) for r in rows])
            conn.commit()
    conn.close()
    return {"store": store, "symbol": sym, "statements": len(statements),
            "columns_ok": sum(1 for c in check_log if c["ok"]), "columns_failed": sum(1 for c in check_log if not c["ok"]),
            "rows": len(rows), "years": sorted({(r.fiscal_year, r.basis) for r in rows}),
            "xbrl_compared": len(agree), "xbrl_agree": sum(1 for a in agree if a["ok"]),
            "checks": check_log, "xbrl": agree, "row_list": rows}


def run(root: Path, stores: list[str] | None, dry: bool, out_dir: Path | None = None) -> list[dict]:
    results = []
    for d in sorted(root.glob("c[0-9][0-9]")):
        db = d / f"{d.name}.db"
        if db.is_file() and (not stores or d.name in stores):
            r = run_store(db, d.name, dry)
            results.append(r)
            print(json.dumps({k: v for k, v in r.items() if k not in ("checks", "xbrl", "row_list")}), flush=True)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "ar_cf_checks.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["store", "symbol", "doc_key", "page", "basis", "column", "fiscal_year", "ok", "why"])
            for r in results:
                for c in r["checks"]:
                    w.writerow([r["store"], r["symbol"], c["doc_key"], c["page"], c["basis"], c["column"],
                                c["fiscal_year"], c["ok"], c["why"]])
        with open(out_dir / "ar_cf_xbrl.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["store", "symbol", "fiscal_year", "basis", "line_item", "printed_inr", "xbrl_inr", "ok"])
            for r in results:
                for a in r["xbrl"]:
                    w.writerow([r["store"], r["symbol"], a["fiscal_year"], a["basis"], a["line_item"],
                                a["printed"], a["xbrl"], a["ok"]])
        with open(out_dir / "ar_cf_rows.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["store", "symbol", "fiscal_year", "basis", "line_item", "caption", "value", "unit", "page",
                        "quote", "definition"])
            for r in results:
                for x in r["row_list"]:
                    w.writerow([r["store"], r["symbol"], x.fiscal_year, x.basis, x.line_item, x.caption, x.value,
                                x.unit, x.page, x.quote, x.definition])
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--root", required=True)
    r.add_argument("--stores", default=None)
    r.add_argument("--dry", action="store_true", help="read only; write the review CSVs, not the store")
    r.add_argument("--out", default=None, help="folder for ar_cf_checks.csv / ar_cf_xbrl.csv / ar_cf_rows.csv")
    a = ap.parse_args(argv)
    res = run(Path(a.root), a.stores.split(",") if a.stores else None, a.dry, Path(a.out) if a.out else None)
    tot = {k: sum(r[k] for r in res) for k in ("statements", "columns_ok", "columns_failed", "rows", "xbrl_compared", "xbrl_agree")}
    print(json.dumps(tot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
