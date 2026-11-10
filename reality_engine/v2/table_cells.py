"""T-132: every printed table cell of a PDF page from word boxes (text layer only), no model.

Rules (docs/V2_SCHEMA_CONTRACT.md section 10):

a. The header stack is built upward from the table: a row is kept only when its words lie inside the table's
   x-range (words outside are trimmed, a word crossing an edge drops the row) and it is not prose (one run of
   eight or more words with no digit, or a line ending in ``.``); a row with a non-date figure (a slide call-out:
   ``Rs 353 crores``) or without a date, period, unit or audit status is skipped, three consecutive skips stop the
   stack and the stack holds at most five rows.  A statement continued on the next page (or a second table with no
   header of its own) reuses the last header set.  Every header phrase is placed by x-position, never by order: it
   owns each column centre inside its own x-span, else the nearest column within tolerance, else nothing, so a date
   line the text layer split onto a second y-row keeps its own column; a block too short to sample every column takes
   the printed date row as its columns.  A measure group row over its period sub-columns (``REVENUE | EBITDA``)
   enters ``col_header`` as ``measure=<text>``.  A tall label box shares its TOP EDGE with the figures printed on
   its baseline even when its centre sits nearer another row.  ``col_header`` joins the rows top to bottom with
   ``' > '``.
b. A section label ("Expenses") ends where a new numbered row group starts (first token is a row
   number: ``2``, ``II``, ``IV``, ``(2)``).  Parenthesised sub-labels (``(a)``) stay inside the section.
   The printed row-number column is dropped from ``row_label`` and from the cells.  A label line
   printed under a row, or above the row whose numbers sit on its own line, belongs to that row: it is
   joined into its ``row_label`` rather than becoming the next row's section.
c. Figures split by the text layer ("2, 028", "1 ,234.5") merge, including the tail of a decimal
   whose point glyph is missing (``7,601.5`` + ``1``; ``2,016`` + ``32``); ``(1,234.5)`` and
   ``-1,234.5`` are negative; ``-`` / an en dash is value NULL with ``value_text`` kept;
   ``12.3%`` is percent.
   A comma-grouped figure must use Western (1,234,567) or Indian (12,34,567) grouping exactly
   (last group three digits, earlier groups two or three consistently); anything else keeps
   ``value_text`` with ``value`` NULL.  A date fragment (``31,2026``, ``30.09.2026``) is not a
   cell at all.
d. The unit is read from the scale word anywhere in the header rows and the lines above the
   table ("f Lakhs" from a split "₹ in Lakhs", "Rs. in Crores", "INR Mn"), else the page's top
   15%, else the row label's own currency with the scale word printed beside it ("(US$ Mn)" is
   USD million, "Revenue in ₹ Cr" is Rs crore), else the row label ("EBIT ( ₹ crores)").
   The row's own unit cell ("Rs Mn", "₹ Cr", "US$ Bn", "Mn Min", "Nos") is split from the
   label by x-position and read first; then the label's own scale word, then the nearest
   table note or section title ("Amount in US$ Mn, except ratios"), then the page unit.
   crore 1e7, lakh 1e5, million/mn 1e6,
   billion/bn 1e9, thousand 1e3.  Percent stays in percent points (``unit_text='%'``,
   ``scale=1``).  A row that names its own unit keeps that unit and scale: a per-share row is
   ``inr_per_share`` (share capital and face value rows are money), a count/number-of row is
   ``count``, a ratio/times/days row is ``ratio``, an ``in Rs`` / ``₹ per tonne`` row is ``Rs``,
   a ``US$`` row is USD at scale 1, and a per-tonne / per-unit / per-key / ARPU / ARR / RevPAR /
   realisation row is ``Rs`` with
   scale 1 (money per unit, never the page's crore scale).
   A bare currency with no scale word anywhere is not scale 1: it takes the scale printed
   beside the row or the table, and with none printed ``scale`` and ``value`` are NULL.
   No unit found means ``scale`` and ``value`` are NULL: never guess a scale.
e. ``period_id`` comes from the column header and the document date through
   :func:`reality_engine.v2.periods.period_row`.  Wrapped header lines are assembled before the
   date is parsed ("March 31," over "2026"); ``Q1 25-26``, ``FY25-26``, ``9M FY27``, ``H1 26-27``,
   ``Dec-24`` / ``Mar'24``, ``9M 25-26`` and ``YTD FY26`` (with the filing date) resolve.  A bare
   date header is the quarter ending that day in a results P&L and a POINT on a balance-sheet page
   or a deck; a bare ``9M`` / ``FY`` / ``Quarter ended`` takes the printed FY range or the latest
   period ending before the filing date.  ``Year ended`` / ``Year Ended`` / ``twelve months`` is FY
   (and its text-layer garble ``Vear Ended`` too), ``Nine months`` 9M, ``Half year`` / ``Six
   months`` / ``6 months`` H1; only a bare date with no span text keeps the quarter rule.  A span
   the header stack split apart (``As > on > 30.06.2025``) is still read as ``As on``.  A balance
   or segment
   asset/liability row (``Segment Assets``, ``Segment Liabilities``, ``Statement of Assets and
   Liabilities``, ``balance sheet``, ``Total assets|liabilities|equity``, ``Net worth``) is a POINT
   on the column's printed date (or the end of a ``Q1 FY27`` header), never the quarter's flow.
   A header date that does not parse to a real date within
   three years of the filing date is dropped, never guessed.  A cell whose header names no
   resolvable period (and is not a difference column) is not stored.
f. ``basis`` is standalone/consolidated from the page title (top 20%), else NULL.
g. An infographic page yields no cells: a table block needs at least two rows, each with at least
   two numbers aligned to the column anchors, and a label longer than 80 characters or carrying
   a sentence break (``'. '`` before a capital) drops its row.  A cell with no row label or no
   usable column header is not stored.
h. ``bbox`` is the merged token's box and ``method`` is ``'text_layer'``, or
   ``'text_layer;delta'`` for a difference / growth / bps column, which is stored with
   ``period_id`` NULL and never read as a period's value.  A garbled label adds ``;garbled`` (j).
i. A row whose label is punctuation only (``-------``), a two-letter fragment (``St``), a long
   punctuation run or a printed figure (``CT2, Yes 529.40``) is not stored; a punctuation-only
   line does not become the next rows' section.
j. A broken text layer prints a label that is not words (``l:Jnallocable / el``, ``Financial
   riabilities``): the cell keeps its value and its printed label, and ``method`` carries
   ``;garbled`` when over 30% of the label's letters sit in tokens that are neither dictionary
   words nor known names (a row number, an acronym or a capitalised name).  The vocabulary is the
   repo's business lexicon plus common statement words, so the flag is advisory and never drops
   a value.  A bare ratio printed under a line item (``as a % of NR``, ``% of revenue``,
   ``margin %``) takes that line item's name as its parent (``Advertising & Sales Promotion >
   as a % of NR``), with a printed ``Add:`` / ``Less:`` prefix stripped.
"""
from __future__ import annotations

import calendar
import re
import statistics
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import pymupdf

from reality_engine.v2.periods import period_row

__all__ = ["extract", "extract_page", "is_delta", "label_unit", "period_from_header"]

_DAY = timedelta(days=1)
_ROW_TOL = 3.0
_MERGE_GAP = 5.0
_PHRASE_GAP = 8.0           # two printed cells of one header line, never merged
_ANCHOR_TOL = 6.0
_PLAUSIBLE_DAYS = 3 * 366 + 31   # a header date must sit within 3 years of the filing

NUM = re.compile(
    r"^\(?[-–—−]?(?:(?:₹|Rs\.?|INR)\s*)?\d[\d,]*(?:\.\d+)?\)?%?$"
    r"|^[-–—−]$"
    r"|^\(?\d*\.\d+\)?%?$")
NUMISH = re.compile(r"^\(?[-–—−]?(?:₹|Rs\.?|INR)?\s*\d[\d,]*(?:\.\d*)?\)?%?$")
ROWNUM = re.compile(r"^\d{1,2}\.?$")
_PLACEHOLDER = re.compile(r"^[-–—−]$")
_ROMAN = re.compile(r"^C{0,3}(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$", re.I)


def _is_row_number(text: str) -> bool:
    """A printed row number: digits or a canonical Roman numeral (not 'CIL', a company name)."""
    raw = (text or "").strip().rstrip(".")
    if raw.isdigit():
        return 1 <= len(raw) <= 2
    return bool(len(raw) <= 4 and re.fullmatch(r"[IVXLC]+", raw, re.I) and _ROMAN.match(raw))

# A body-row marker: '1.', 'II.', '(iv)', '(2)'.  A lettered sub-label ('(a)', 'a)') is
# not a marker: it stays inside its section (contract 10.b).
MARKER = re.compile(r"^\((?:\d{1,2}|[IVXLC]{1,4})\)$|^(?:\d{1,2}|[IVXLC]{1,4})\.$")
SUB_LABEL = re.compile(r"^\(?[a-z]\)$", re.I)
DELTA_WORD = re.compile(
    r"\b(?:inc\s*/?\s*dec|increase\s*/\s*decrease|change|variation|var|yoy|y-o-y|y\s*on\s*y|qoq|"
    r"q-o-q|q\s*on\s*q|growth|delta|bps)\b", re.I)
GROWTH = re.compile(
    r"\b(?:yoy|y-o-y|y\s*on\s*y|qoq|q-o-q|q\s*on\s*q|growth|change|var(?:iation)?|"
    r"inc\s*/?\s*dec|increase\s*/\s*decrease|delta|bps)\b|%", re.I)
# A scale word on its own: the text layer splits "₹ in Lakhs" into "f Lakhs" and appends a stray
# letter ("Croresl"), so no currency prefix is required, one stray trailing letter is allowed and
# a scale word anywhere in the header rows counts (contract 10.d).
_SCALE_WORD = re.compile(
    r"\b(crores?|cr|lakhs?|lacs?|millions?|mn|billions?|bn|thousands?)[a-z]?\b", re.I)

_MONTHS = {name: i for i, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MONTH_NAMES = set(_MONTHS) | {
    "january", "february", "march", "april", "june", "july", "august", "september", "sept",
    "october", "november", "december"}
_SCALES = {
    "crore": (1e7, "crore"), "crores": (1e7, "crore"), "cr": (1e7, "crore"),
    "lakh": (1e5, "lakh"), "lakhs": (1e5, "lakh"), "lac": (1e5, "lakh"), "lacs": (1e5, "lakh"),
    "million": (1e6, "million"), "millions": (1e6, "million"), "mn": (1e6, "million"),
    "billion": (1e9, "billion"), "billions": (1e9, "billion"), "bn": (1e9, "billion"),
    "thousand": (1e3, "thousand"), "thousands": (1e3, "thousand"),
}

_DATE_DMY = re.compile(r"(?<!\d)(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})(?!\d)")
_DATE_FULL = re.compile(r"^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}$")
_DATE_DMY_WORD = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s\-]([A-Za-z]{3,9})[\s,\-]+(\d{2,4})(?!\d)")
_DATE_MDY = re.compile(
    r"([A-Za-z]{3,9})[\s\-]+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,\s*|\s+)(\d{4}|\d{2})(?!\d)")
_DATE_MY = re.compile(r"([A-Za-z]{3,9})\s*[-'’]\s*((?:19|20)\d{2}|\d{2})(?!\d)")
_DATE_MY_SPACE = re.compile(r"([A-Za-z]{3,9})\s+((?:19|20)\d{2})(?!\d)")
_DATE_MD = re.compile(r"\b([A-Za-z]{3,9})\s+\d{1,2}(?:st|nd|rd|th)?\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_DATE_VALUE = re.compile(
    r"^\d{1,2},$"
    r"|^\d{1,2},\d{4}$"
    r"|^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}$"
    r"|^\d{1,2}[.\-/]\d{4}$")
_KINDS = (
    (re.compile(r"\bnine\s+months?\b|\b9\s*m(?:onths?)?\b", re.I), "9M"),
    (re.compile(r"\bsix\s+months?\b|\b6\s*months?\b|\bhalf[\s-]?year\b|\bh\s*1\b", re.I), "H1"),
    (re.compile(r"\bquarter\b|\bq\s*[1-4]\b", re.I), "Q"),
    # 'Vear Ended' is the text layer losing the Y of 'Year' (HDFC AMC prints it) and
    # 'twelve months' is a full year in words (contract 10.i, round-4 class 2).
    (re.compile(r"\b[vy]ear[\s-]?ended\b|\bfor\s+the\s+[vy]ear\b|\bfy\b|"
                r"\btwelve\s+months?\b|\b12\s*m(?:onths?)?\b", re.I), "FY"),
    # A header segment that is only 'Year' (over its date row) is the full year.
    (re.compile(r"^(?:the\s+)?year$", re.I), "FY"),
    # 'as at / as on / as of' is the balance-sheet reading and is consulted LAST: a segment
    # table's 'Quarter ended / As of' column set is a flow unless the row is a balance
    # (round-8 class 1, Bharti's segment tables).
    (re.compile(r"\bas\s*(?:at|on|of)\b", re.I), "POINT"),
)
# A fiscal year printed as a range ('2025-26', 'FY 25-26'); '25-26' alone is a span label.
_FY_RANGE = re.compile(r"(?<!\d)((?:19|20)\d{2}|\d{2})\s*[-–/]\s*((?:19|20)\d{2}|\d{2})(?!\d)")
# A bare date header ('31-12-2024') is a POINT on a balance-sheet page and a quarter on a
# results P&L (contract 10.e); the page title says which.
_BS_TITLE = re.compile(r"\b(?:balance\s*sheet|financial\s*position|assets\s+and\s+liabilities)\b",
                       re.I)
_PL_TITLE = re.compile(r"\b(?:profit\s*(?:&|and)\s*loss|profit\s+or\s+loss|operations|"
                       r"income\s+statement)\b", re.I)
# A row that names its own unit is not read at the page's money scale (contract 10.d).
_PER_SHARE = re.compile(r"\bper\s+(?:equity\s+|common\s+|diluted\s+|basic\s+)?share\b|"
                        r"\beps\b|\bdps\b|\bearnings?\s+per\b|\bdividend\s+per\b", re.I)
_CAPITAL = re.compile(r"\bcapital\b|\bface\s+value\b", re.I)
_RATIO_ROW = re.compile(r"\(\s*in\s*(?:times|times\)|no\.|nos\.|days?)\s*\)|\bratio\b|"
                        r"\btimes\b|\bturnover\b|\bcoverage\b|\bper\s+day\b", re.I)
_PERCENT_ROW = re.compile(r"\(\s*in\s*%\s*\)|\(\s*%\s*\)|\(\s*in\s*bps\s*\)|\bmargins?\b", re.I)
# The currency a row prints in its own label beats the page's money unit (contract 10.d,
# round-5 class 2): 'Average Revenue Per User (ARPU) US$' is USD at scale 1, '(US$ Mn)' is
# USD millions, and a section prefix 'Revenue in ₹ Cr' names a crore scale.
_CURRENCY = re.compile(r"(?<![A-Za-z])(us\s*\$|usd|a\s*\$|aud|rs\.?|inr|₹)(?![A-Za-z])", re.I)
# A row stated per physical unit or per user is that unit's money, never the page's crore
# scale: 'Overall Average Realization' is Rs per tonne, 'RevPAR in ₹' Rs per room night and
# ARPU / ARR are Rs per user (contract 10.d, round-4 class 4).
_PER_UNIT = re.compile(
    r"\bper\s+(?:tonne|ton|te|mt|unit|key|room\s*night|night|kg|litre|liter)\b|"
    r"/\s*(?:te|tonne|ton|mt|unit)\b|\b(?:arpu|arr|revpar)\b|\breali[sz]ations?\b", re.I)
# A label that prints '(MMT)' is a million-tonne physical volume, not a bare count
# (round-7 class 6).
_MMT_ROW = re.compile(r"\(\s*mmt\s*\)|\bmmt\b", re.I)
_COUNT_ROW = re.compile(
    r"\bno\.?\s+of\b|\bnos\.?\b|\(\s*nos\.?\s*\)|\bnumber\s+of\b|\b000'?s\b|\bqty\b|"
    r"\bquantity\b|\bemployees\b|\bstores\b|\bkeys\b|\btonnes?\b|\(\s*te\s*\)|"
    r"\(in\s+mill\.?\s*te\)|\bmmt\b|\bmw\b|\bshares\s+outstanding\b|\bshare\s+count\b|"
    r"\bcustomers\b|\boutlets\b|\brooms\b|\btowers?\b|\bteus?\b", re.I)
# A balance or segment asset/liability row is a balance on the column's date, never the
# quarter's flow, even under a 'Quarter ended' header (contract 10.i, round-4 class 3).
_POINT_ROW = re.compile(
    r"\bsegment\s+(?:assets?|l[.,:;']?iab\w*)\b|\bstatement\s+of\s+assets\b|"
    r"\bbalance\s+sheet\b|\btotal\s+(?:assets|liabilities|equity)\b|\bnet\s+worth\b", re.I)
# A row label that is punctuation, a two-letter fragment or a printed figure is not a label
# (round-4 class 6): '-------', 'St', 'CT2, Yes 529.40'.
_LONG_PUNCT = re.compile(r"[-–—_.]{4,}")
_VALUE_RUN = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{2,3})*\.\d{2,}|(?<!\d)\d{1,2},\d{3}(?!\d)")
# A bare ratio printed under a line item ('as a % of NR', '% of revenue', 'margin %') takes the
# line item as its parent; the printed 'Less:' / 'Add:' prefix is not part of the name
# (contract 10.a, round-5 class 3).
_BARE_RATIO = re.compile(
    r"^(?:as\s+(?:a|an)?\s*%|%\s*(?:of|to|on)\b|as\s+(?:a\s+)?percentage|"
    r"percent(?:age)?\s+of\b|margin\s*%?$)", re.I)
_ROW_PREFIX = re.compile(r"^(?:add|less|including|excluding)\s*[:\-]\s*", re.I)
# A cash-flow statement's own cross-check: the later column's opening cash equals the
# earlier column's closing cash (round-7 class 5).
_CASH_TITLE = re.compile(r"\bcash\s*flows?\b", re.I)
_CASH_OPEN = re.compile(r"\b(?:opening|beginning)\b", re.I)
_CASH_CLOSE = re.compile(r"\b(?:closing|end)\b", re.I)
# Round 8, class 1: a balance or level is a POINT at the column date; a flow is the column's
# period.  The vocabulary is the stock/flow of ``label_map.STOCK_METRICS`` (the same kinds the
# period engine sums by) plus the market-cap and cash-level labels a deck prints.
_STOCK_ROW = re.compile(
    r"\bnet\s+(?:debt|worth)\b|\bgross\s+debt\b|\bdebt\s+equity\b|"
    r"\b(?:current|quick|liquid)\s+ratio\b|\bbook\s+value\b|"
    r"\b(?:total\s+|long[\s-]term\s+|short[\s-]term\s+|lease\s+)?borrowings?\b|"
    r"\b(?:total\s+|shareholders['’]?\s+|owners['’]?\s+|net\s+)?(?:equity|worth)\b(?!\s+and\b)|"
    r"\bcapital\s+employed\b|\bmarket\s+cap(?:itali[sz]ation)?\b|\benterprise\s+value\b|"
    r"\bcash\s+(?:and\s+)?(?:cash\s+)?(?:equivalents?|balance|level)\b|"
    r"\bpopulation\s+covered\b|\bcoverage(?:\s*%|\s+ratio)?\b|"
    r"\b(?:cumulative\s+)?investments?\b(?!\s+income)|"
    r"\btotal\s+(?:assets?|liabilities)\b|\bsegment\s+(?:assets?|liabilities)\b|"
    r"\baum\b|\border\s+book\b|\bdeposits\b|\badvances\b|\bworking\s+capital\b|"
    r"\bdebtors?\b|\breceivables\b|\bpayables\b|\binventor(?:y|ies)\b|\bprovisions?\b|"
    r"\bnet\s+block\b|\bfixed\s+assets\b|\bcapital\s+work\s+in\s+progress\b|"
    # An operating count is a level on the column's date, not a quarterly flow (round 8:
    # Bharti Africa's customer base, network towers and India's Lean co-locations).  An
    # 'additions' / 'net additions' row carries a flow word and stays a flow.
    r"\bcustomers?\b|\bsubscribers?\b|\btowers?\b|\bco-?locations?\b", re.I)
# A cash-flow line that merely names a stock ('purchase of investments', 'net cash generated')
# is a flow and keeps the column's period.  The flow words are checked BEFORE the stock words:
# an 'equity' / 'investments' / 'inventory' / 'cash' inside a flow label ('return on equity',
# 'inventory turnover', 'gain on investments', 'FX restatement of cash') never turns the
# column's printed period into a point (round-9 step 1).  'changes in working capital' is the
# flow; working capital itself is a balance (the debt-to-working-capital ratio is a point).
_FLOW_ROW = re.compile(
    r"\b(?:generated|used|raised|purchased|purchases|sold|sale[sd]?|proceeds|invested|"
    r"net\s+cash|changes?\s+in(?:\s+working\s+capital)?|additions?|depreciation|"
    r"amorti[sz]ation|dividend\s+received|interest\s+(?:paid|received|income)|finance\s+cost|"
    r"increase|decrease|adjustments?|investment\s+in|impairment\s+loss|"
    r"gains?|loss(?:es)?|turnover|returns?|restatements?|effects?|margins?|"
    r"income|expenses?)\b", re.I)
# 'in 000s' / "000's" is a thousand-fold scale printed beside the row or over its table.
_THOUSAND = re.compile(r"\b0{3}'?s\b|\bthousands?\b", re.I)
# A level KPI printed as people ('Population Covered 2 Bn') is a count, never rupees.
_COUNT_LEVEL = re.compile(
    r"\bpopulation\b|\bsubscribers?\b|\bhouseholds?\b|\bcoverage\b|\bconnections?\b|"
    r"\bhomes?\s+(?:passed|covered)\b|\bsite[sd]?\b|\bvillages?\b|\btowns?\b", re.I)
# Round 8, class 7: two printed ratio rows merged onto one label line.  The row's own name is
# the one printed second (the first line's label was glued to it).
_RATIO_NAME = re.compile(
    r"\b(?:gross|net|operating|ebitda|ebit|pat|pbt|profit)\s+(?:profit\s+)?margins?\b|"
    r"\b(?:current\s+liability\s+ratio|debt\s+equity\s+ratio|quick\s+ratio|current\s+ratio|"
    r"debtors?\s+turnover|inventory\s+turnover|interest\s+coverage|bad\s+debts?|"
    r"coverage\s+ratio)\b", re.I)
# A row-number prefix ('1.', '3.3.7', 'IV)') on a measure or section title.
_SECTION_NUMBER = re.compile(r"^\s*(?:\d{1,2}(?:\.\d{1,2})*\.?|[IVXLC]{1,4}[.)])\s+")
# A table's own measure section at the left: 'Segment Revenue', 'Segment Results', 'Revenue'.
_MEASURE_SECTION = re.compile(
    r"^(?:segment\s+)?(?:revenue|revenues|results|ebitda|ebit|pat|pbt|profit|income|"
    r"contribution(?:\s+margin)?|investments|capex)$", re.I)


# ------------------------------------------------------------------------------- word boxes

def _rows_of(words: list[Any], tol: float = _ROW_TOL) -> list[list[Any]]:
    rows: list[list[Any]] = []
    current: list[Any] = []
    y: float | None = None
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        centre = (w[1] + w[3]) / 2
        if y is None or abs(centre - y) <= tol:
            current.append(w)
            y = centre if y is None else y
        else:
            rows.append(sorted(current, key=lambda t: t[0]))
            current, y = [w], centre
    if current:
        rows.append(sorted(current, key=lambda t: t[0]))
    # A tall label box shares its TOP EDGE with the figures printed on its baseline, but its
    # centre can sit nearer the row above or below. Re-home every non-figure token onto the
    # numeric row whose top edge it shares, then label and figures are one row again
    # (contract 10.j, round-5 class 4).
    tops: list[float | None] = []
    for row in rows:
        numbers = [float(token[1]) for token in row if NUM.match(str(token[4]))]
        tops.append(min(numbers) if numbers else None)
    moved = True
    while moved:
        moved = False
        for index, row in enumerate(rows):
            for token in list(row):
                if NUM.match(str(token[4])):
                    continue
                top = float(token[1])
                own = tops[index]
                if own is not None and abs(top - own) <= 2.0:
                    continue
                for other in range(len(rows)):
                    match = tops[other]
                    if other != index and match is not None and abs(top - match) <= 2.0:
                        row.remove(token)
                        rows[other].append(token)
                        moved = True
                        break
    rows = [sorted(row, key=lambda t: t[0]) for row in rows if row]
    # A label printed BELOW the top edge of the figures above it starts the next row: a tall
    # figure box can share its centre with the label line under it, and that label is never
    # the figure's own name (Coal India's 'Finance Costs' took Employee Benefits' numbers,
    # round-6 class 7).  A label on its row's baseline is kept.
    split: list[list[Any]] = []
    for row in rows:
        numbers = [token for token in row if NUM.match(str(token[4]))]
        if not numbers:
            split.append(row)
            continue
        top = min(float(token[1]) for token in numbers)
        baseline = max(float(token[3]) for token in numbers)
        keep: list[Any] = []
        rest: list[Any] = []
        for token in row:
            if NUM.match(str(token[4])):
                keep.append(token)
                continue
            # A label joins the figures when it is printed on their baseline, starts on their
            # top edge, or sits inside their y-box.  A label that starts above a row but
            # finishes below it belongs to the row printed under it (Coal India's
            # 'Depreciation, Amortization', round-6 class 7).  The Coal India deck prints
            # 28-point numbers around a 21-point label, so reading order puts the label after
            # its own figures and the text layer's order is not the row (round-7 class 3).
            same_top = abs(float(token[1]) - top) <= 1.5
            same_baseline = abs(float(token[3]) - baseline) <= 2.0
            inside = float(token[1]) >= top - 2.0 and float(token[3]) <= baseline + 2.0
            if same_top or same_baseline or inside:
                keep.append(token)
            else:
                rest.append(token)
        if keep:
            split.append(keep)
        if rest:
            split.append(rest)
    rows = [sorted(row, key=lambda t: t[0]) for row in split if row]
    rows.sort(key=lambda row: min(float(token[1]) for token in row))
    return rows


def _joinable(previous: dict[str, Any], word: Any, text: str) -> bool:
    gap = word[0] - previous["x1"]
    if gap > _MERGE_GAP:
        return False
    left = previous["text"]
    if gap <= 3.0 and _DATE_FULL.match(left + text):
        return True                         # the layer split a date: '3' + '1.03.2026'
    if gap <= 2.5 and left[-1].isdigit() and text[0].isdigit():
        if len(left) == 3 and len(text) == 3 and left.isdigit() and text.isdigit():
            return False            # two adjacent 3-digit columns, not one split figure
        # A lost thousands separator ('5 088') or the tail of a decimal the text layer cut
        # off ('7,601.5' + '1'; '2,016' + '32' with the point glyph missing).
        joined = left + text
        dotted = f"{left}.{text}"
        return bool(re.fullmatch(r"\d{1,7}", joined)
                    or (NUMISH.match(joined) and _grouping_ok(joined))
                    or (len(text) <= 2 and NUMISH.match(dotted) and _grouping_ok(dotted)))
    if left[-1] in ",.-–—−(₹" or text[0] in ",.)%":
        return bool(NUMISH.match(left + text))
    # A closing bracket split off with its unit: '(400' + 'bps)' is the printed '(400 bps)'.
    if (gap <= 2.5 and re.fullmatch(r"\(?[-–—−]?\d[\d,]*(?:\.\d+)?", left)
            and re.fullmatch(r"(?:bps|bp|pp|%|crores?|cr|lakhs?|millions?|mn|billions?|bn)\)",
                             text, re.I)):
        return True
    return False


def _tokens(row: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for word in row:
        text = str(word[4]).strip()
        if not text:
            continue
        if out and _joinable(out[-1], word, text):
            left = out[-1]["text"]
            joined = left + text
            dotted = f"{left}.{text}"
            if (left[-1:].isdigit() and text[:1].isdigit()
                    and not (NUMISH.match(joined) and _grouping_ok(joined))
                    and NUMISH.match(dotted) and _grouping_ok(dotted)):
                out[-1]["text"] = dotted      # the point glyph itself was lost
            else:
                out[-1]["text"] = joined
            out[-1]["x1"] = max(out[-1]["x1"], float(word[2]))
            out[-1]["y1"] = max(out[-1]["y1"], float(word[3]))
            continue
        out.append({"x0": float(word[0]), "y0": float(word[1]),
                    "x1": float(word[2]), "y1": float(word[3]), "text": text})
    for token in out:
        token["num"] = bool(NUM.match(token["text"])) \
            and not _DATE_VALUE.match(token["text"])
    return out


_DATE_TOKEN = re.compile(
    r"^(?:(?:19|20)\d{2}"
    r"|[A-Za-z]{3,9}[ .\-'’]\d{2,4}"
    r"|\d{1,2}[ .\-][A-Za-z]{3,9}(?:[ .\-]\d{2,4})?"
    r"|\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}"
    r"|\d{1,2},\d{4}"
    r"|(?:Q[1-4]|H[12]|9M|FY)\s*(?:FY\s*)?\d{2,4}(?:\s*[-–]\s*\d{2,4})?)$", re.I)
_ALPHA = re.compile(r"[A-Za-z]")


def _numeric_count(row: list[dict[str, Any]]) -> int:
    """Data numbers in a row; a date header row or a lone row number is not data."""
    texts = [token["text"] for token in row if token["text"].strip()]
    if len(texts) >= 2 and all(_DATE_TOKEN.match(text) for text in texts):
        return 0                              # '2023 2024 2025 Jun-25 ...' is a header row
    numbers = [token for token in row if token["num"]]
    if numbers and all(_DATE_TOKEN.match(token["text"]) for token in numbers):
        return 0                              # 'No. 2025 2024': a wrapped date row
    if len(numbers) == 1 and _is_row_number(numbers[0]["text"]):
        first = next((token for token in row if token["text"].strip()), None)
        if first is numbers[0]:
            return 0
    return len(numbers)


def _anchors_of(block: list[list[dict[str, Any]]]) -> list[float]:
    # A dash placeholder ('-') is centred in its cell, not right-aligned like a figure, so its
    # right edge is half a column off; letting it vote would double a column of dashes into
    # two anchors and shift every later column (round-9 step 4, Adani's port-volume tables).
    xs = sorted(token["x1"] for row in block for token in row
                if token["num"] and not _PLACEHOLDER.match(token["text"]))
    clusters: list[list[float]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= _ANCHOR_TOL:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    # A column must print in a third of the block's *figure rows*: a table whose rows are
    # separated by several label lines still has the same three columns (round-7 class 5).
    need = max(2, 0.3 * len(block))
    return [sum(cluster) / len(cluster) for cluster in clusters if len(cluster) >= need]


_SPACED_DIGITS = re.compile(r"(?<=\d) +(?=[\d.])")


def _squash_digits(text: str) -> str:
    """'3 1.03 .2025' -> '31.03.2025': the text layer spaced the digits of one printed date.

    Only a run that is exactly one date is squashed, so a row of years ('2024 2025 2026') or
    two columns' dates stays as printed (contract 10.e, round-6 class 6).
    """
    if " " not in text:
        return text
    squashed = text
    for _ in range(3):
        squashed = _SPACED_DIGITS.sub("", squashed)
    return squashed if _DATE_FULL.match(squashed) else text


def _phrases(row: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phrases: list[dict[str, Any]] = []
    for token in sorted(row, key=lambda t: t["x0"]):
        if phrases and token["x0"] - phrases[-1]["x1"] <= _PHRASE_GAP:
            phrases[-1]["x1"] = max(phrases[-1]["x1"], token["x1"])
            phrases[-1]["text"] += " " + token["text"]
        else:
            phrases.append({"x0": token["x0"], "x1": token["x1"], "text": token["text"]})
    for phrase in phrases:
        phrase["text"] = _squash_digits(phrase["text"])
    return phrases


def _centers(anchors: list[float]) -> tuple[list[float], float]:
    """Approximate centre of each right-aligned column and the typical column width."""
    gap = min((b - a for a, b in zip(anchors, anchors[1:])), default=40.0)
    gap = max(gap, 1.0)
    centers = []
    for k, anchor in enumerate(anchors):
        width = anchor - anchors[k - 1] if k else gap
        centers.append(anchor - max(width, 1.0) / 2)
    return centers, gap


def _month_word(text: str) -> bool:
    return re.sub(r"[^a-z]", "", text.lower()) in _MONTH_NAMES


def _month_row(row: list[dict[str, Any]]) -> bool:
    """A wrapped date row printed as month names only ('December September December ...')."""
    words = [token["text"] for token in row if token["text"].strip()]
    months = [word for word in words if _month_word(word)]
    return len(months) >= 2 and all(
        _month_word(word) or len(re.sub(r"\W", "", word)) <= 1 for word in words)


def _date_parts(row: list[dict[str, Any]]) -> bool:
    """Day/year numbers of a wrapped date row ('31 2025 30 2025 ...', '31.03' over '.2' '024')."""
    words = [token for token in row if token["text"].strip()]
    if any(_ALPHA.search(token["text"]) for token in words if not token["num"]):
        return False                                  # a label row, never a date-parts row
    numbers = [token["text"] for token in words if token["num"]]
    part = re.compile(r"\d{1,2}|\d{3}|\d{4}|\d{1,2},\d{4}|"
                      r"(?:3[01]|[12]\d|0?[1-9])[.\-/](?:1[0-2]|0?[1-9])"
                      r"(?:[.\-/]\d{2,4})?")
    return bool(numbers) and all(part.fullmatch(text) for text in numbers)


def _date_phrase(text: str) -> bool:
    return bool(_DATE_DMY.search(text) or _DATE_DMY_WORD.search(text)
                or _DATE_MDY.search(text) or _DATE_MY.search(text)
                or _DATE_MY_SPACE.search(text) or _DATE_MD.search(text)
                or _YEAR.search(text)
                or any(_month_word(word) for word in text.split()))


def _kind_like(text: str) -> bool:
    return bool(_kind_in(text) or re.search(
        r"\b(?:quarter|half|year|months?|ended|ytd|nine|six|as\s+(?:at|on|of))\b",
        text, re.I))


def _refined_centers(header_rows: list[list[dict[str, Any]]], anchors: list[float],
                     left: float) -> tuple[list[float], float]:
    """Column centres from the date row when the header stack prints one."""
    centers, gap = _centers(anchors)
    for row in reversed(header_rows):
        phrases = _phrases([t for t in row if t["x1"] >= left])
        if (len(phrases) >= max(2, (len(centers) + 1) // 2)
                and all(_date_phrase(p["text"]) for p in phrases)):
            refined = list(centers)
            for phrase in phrases:
                centre = (phrase["x0"] + phrase["x1"]) / 2
                k = min(range(len(refined)), key=lambda j: abs(refined[j] - centre))
                refined[k] = centre
            centers = refined
            break
    else:
        # The text layer split the date row onto two y-rows ('31.03' over '.2' + '024'):
        # the date phrases of the whole stack still name the columns by x-position, one
        # printed date per column in left-to-right order.
        combined = [phrase for row in reversed(header_rows)
                    for phrase in _merge_date_phrases(
                        _phrases([t for t in row if t["x1"] >= left]))
                    if _date_phrase(phrase["text"])]
        if len(combined) == len(centers):
            centers = sorted((phrase["x0"] + phrase["x1"]) / 2 for phrase in combined)
    return centers, gap


def _phrase_columns(phrase: dict[str, Any], centers: list[float],
                    tolerance: float) -> list[int]:
    """The columns one printed header cell is printed over, by x-position, never by order.

    A phrase owns every column whose centre lies inside its own x-span (a group heading over
    two columns owns both); when it covers none it owns the nearest column within the column
    tolerance, and a phrase printed off the table owns nothing (contract 10.a).
    """
    inside = [k for k, centre in enumerate(centers)
              if phrase["x0"] - 4.0 <= centre <= phrase["x1"] + 4.0]
    if inside:
        return inside
    centre = (phrase["x0"] + phrase["x1"]) / 2
    nearest = min(range(len(centers)), key=lambda k: abs(centers[k] - centre))
    return [nearest] if abs(centers[nearest] - centre) <= tolerance else []


def _unit_only(text: str) -> bool:
    """A scale line ("(₹ in crores)", "f Lakhs") names the unit, not a column.

    A measure cell may print its own unit in brackets ('Total Income (₹ crores)'); the line
    is a unit note only when it opens with the unit/amount word (round-7 class 2).
    """
    if not _SCALE_WORD.search(text) or any(ch.isdigit() for ch in text) or _kind_like(text):
        return False
    stripped = text.strip()
    if re.match(r"^[(\[{~]?\s*(?:rs|inr|₹|usd|us\s*\$|aud|a\s*\$|f|in|amount|amounts|"
                r"figures?|all)(?=\s|$)", stripped, re.I):
        return True
    # The text layer also leaves a scale word alone or folded onto the line above ('crore)',
    # 'I~ in Croresl'): the line names the unit, not a column (round-9 step 4).
    scale_words = {"crore", "crores", "lakh", "lakhs", "lac", "lacs", "million", "millions",
                   "mn", "billion", "billions", "bn", "thousand", "thousands", "in", "rs",
                   "inr", "amount", "amounts", "figures", "figure", "all", "f", "the",
                   "except", "ratios"}
    words = [re.sub(r"[^A-Za-z]", "", word).lower() for word in stripped.split()]
    words = [word for word in words if word]
    return (bool(words) and not _MEASURE_WORD.search(text)
            and all(word in scale_words or word.rstrip("l") in scale_words for word in words))


def _span_heading(phrase: dict[str, Any], gap: float) -> bool:
    """A group heading ('Quarter ended', 'As at') printed over its columns, not a date.

    A quarter label ('Q1 FY27') names one column, never a group of them.
    """
    return (_kind_like(phrase["text"]) and not _date_phrase(phrase["text"])
            and not _direct_label(phrase["text"])
            and phrase["x1"] - phrase["x0"] <= 4.0 * gap)


_PERIOD_WORD = re.compile(r"^(?:Q[1-4]|H[12]|9\s*M|FY)$", re.I)
_YEAR_RANGE = re.compile(r"^\d{2,4}\s*[-–/]\s*\d{2,4}$")


_SPACED_PIECE = re.compile(r"^[\d.,/\-]+$")


def _merge_date_phrases(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """'3' | '1.03' | '.2025' on one header line is one printed date (round-6 class 6)."""
    out: list[dict[str, Any]] = []
    index = 0
    while index < len(phrases):
        merged = dict(phrases[index])
        pieces = [phrases[index]["text"]]
        cursor = index + 1
        while (cursor < len(phrases) and len(pieces) < 4
               and _SPACED_PIECE.match(pieces[-1])
               and _SPACED_PIECE.match(phrases[cursor]["text"])):
            candidate = " ".join(pieces + [phrases[cursor]["text"]])
            squashed = _squash_digits(candidate)
            if _DATE_FULL.match(squashed):
                merged["text"] = squashed
                merged["x1"] = phrases[cursor]["x1"]
                pieces.append(phrases[cursor]["text"])
                cursor += 1
                break
            pieces.append(phrases[cursor]["text"])
            cursor += 1
        if merged["text"] != phrases[index]["text"]:
            index = cursor
        else:
            index += 1
        out.append(merged)
    return out


def _join_period_phrases(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """'9M' over '25-26' is one printed header cell, split by a wider text-layer gap."""
    out: list[dict[str, Any]] = []
    index = 0
    while index < len(phrases):
        phrase = phrases[index]
        if (index + 1 < len(phrases) and _PERIOD_WORD.match(phrase["text"])
                and _YEAR_RANGE.match(phrases[index + 1]["text"])):
            merged = dict(phrase)
            merged["text"] = f"{phrase['text']} {phrases[index + 1]['text']}"
            merged["x1"] = phrases[index + 1]["x1"]
            out.append(merged)
            index += 2
            continue
        out.append(phrase)
        index += 1
    return out


def _split_merged_dates(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A header cell that merged two printed dates is two column headers (round-7 class 4).

    'YEAR ENDED > 31.03.2025 I 31.03.2024' prints the separator 'I' between the two year
    columns, so the text layer's phrase gap merges them; each date owns the share of the
    printed x-span its characters occupy.
    """
    out: list[dict[str, Any]] = []
    for phrase in phrases:
        matches = list(_DATE_DMY.finditer(phrase["text"]))
        if len(matches) < 2:
            out.append(phrase)
            continue
        width = phrase["x1"] - phrase["x0"]
        length = max(len(phrase["text"]), 1)
        for match in matches:
            out.append({"x0": phrase["x0"] + width * match.start() / length,
                        "x1": phrase["x0"] + width * match.end() / length,
                        "text": match.group(0)})
    return out


_TITLE_GLUE = frozenset("""
a an and as at by for from in of on or the to with quarter quarters half year years
ended ending month months nine six twelve annual interim period periods ytd h1 h2
audited unaudited reviewed restated standalone consolidated
""".split())


def _title_phrase(text: str) -> bool:
    """A table title printed over the header row is not a column header (round-7 class 5).

    Adani Ports prints 'Q3 FY26 & 9M FY26 key financials (consolidated)' directly over its
    header row; the title names the whole table, never one column's period.
    """
    if not (_date_phrase(text) or _direct_label(text) or _kind_like(text)):
        return False
    rest = text
    for pattern in (_DATE_DMY, _DATE_DMY_WORD, _DATE_MDY, _DATE_MY_SPACE, _DATE_MY):
        rest = pattern.sub(" ", rest)
    rest = re.sub(r"\b(?:Q[1-4]|H[12]|9\s*M|FY)\s*[-/]?\s*(?:FY\s*)?\d{2,4}"
                  r"(?:\s*[-–]\s*\d{2,4})?\b", " ", rest, flags=re.I)
    rest = re.sub(r"\b\d{1,4}\b", " ", rest)
    if re.search(r"\b(?:financials?|highlights?|performance|presentation|snapshot)\b",
                 rest, re.I):
        return True                     # '& 9M FY26 key financials (consolidated)'
    words = [word for word in re.findall(r"[A-Za-z]+", rest)
             if word.lower() not in _TITLE_GLUE and word.lower() not in _MONTH_NAMES]
    # A bare column label ('Var. vs FY24') leaves two words after its period is removed and
    # used to be taken for a table title, losing the whole growth column (round-8 class 0).
    return len(words) >= 3


_MEASURE_WORD = re.compile(
    r"\b(?:revenue|revenues|income|incomes|ebitda|ebit|pat|pbt|profit|profits|margin|margins|"
    r"results?|cost|costs|expense|expenses|turnover|sales|aum|nav|nii|premium|volumes?|"
    r"shipments?|production|orders?|eps|ebt)\b", re.I)


def _measure_text(text: str) -> bool:
    """A short word group that names what a column measures ('REVENUE', 'EBITDA MARGIN').

    A measure may print its unit in brackets ('Total Income (Rs crores)', 'EBIT Margin (%)');
    the unit is stripped before the word test (round-7 class 2).
    """
    text = re.sub(r"\s*\([^()]*\)\s*$", "", text.strip()).strip()
    return (bool(text) and text[:1].isalpha() and bool(_ALPHA.search(text))
            and not any(ch.isdigit() for ch in text)
            and len(text.split()) <= 3 and len(text) <= 24
            and not _kind_like(text) and not _date_phrase(text) and not DELTA_WORD.search(text)
            and not _SCALE_WORD.search(text) and not _STATUS.search(text))


def _measure_heading(phrase: dict[str, Any], gap: float) -> bool:
    """A measure printed over its period sub-columns ('REVENUE', 'EBITDA MARGIN')."""
    return ((_measure_text(phrase["text"]) or bool(_UNIT_PHRASE.match(phrase["text"])))
            and phrase["x1"] - phrase["x0"] <= 6.0 * gap)


# A printed sub-header that names a unit, not a measure: "'000 TEUs', 'MMT', 'MW', 'Nos'.
_UNIT_PHRASE = re.compile(
    r"^[‘’'\"]?\d{3}\s*(?:teus?|te|mt|mmt|mw|nos?)$|^(?:mmt|mt|te|teus?|mw|nos?|sq\.?\s*ft)$",
    re.I)


def _join_arrow_phrases(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """'Of which →' printed left of 'Coal' is one sub-heading; the arrow is a qualifier."""
    out: list[dict[str, Any]] = []
    index = 0
    while index < len(phrases):
        phrase = phrases[index]
        if (phrase["text"].strip().endswith(("→", "->", "à", "=>"))
                and index + 1 < len(phrases)):
            out.append(dict(phrases[index + 1]))
            index += 2
            continue
        out.append(phrase)
        index += 1
    return out


def _join_bracket_phrases(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """'Total Income (' + '₹ crores)' is one printed header cell (round-7 class 2)."""
    out: list[dict[str, Any]] = []
    for phrase in phrases:
        if (out and out[-1]["text"].count("(") > out[-1]["text"].count(")")
                and phrase["text"].endswith(")")):
            out[-1]["text"] = f"{out[-1]['text']} {phrase['text']}"
            out[-1]["x1"] = max(out[-1]["x1"], phrase["x1"])
            continue
        out.append(dict(phrase))
    return out


def _header_fragment(phrase: dict[str, Any], gap: float) -> bool:
    """A title fragment ('& Reported', '– Quarter') over a header row is not a column."""
    text = phrase["text"]
    if any(ch.isdigit() for ch in text) or _date_phrase(text) or _direct_label(text):
        return False
    if (_SCALE_WORD.search(text) or _STATUS.search(text) or DELTA_WORD.search(text)
            or _measure_text(text)):
        return False
    return not _kind_like(text)


_KIND_HEAD = re.compile(
    r"\b(?:quarter\s+ended|nine\s+months?\s+ended|half[\s-]?year(?:\s+ended)?|"
    r"six\s+months?\s+ended|[vy]ear\s+ended|as\s+(?:at|on|of))\b", re.I)


def _split_kind_phrases(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Printed heading cells the text layer merged, split at their own positions.

    'Quarter ended I As of year ended I' prints three cells separated by 'I'; a single cell
    that names both readings ('Quarter ended / As of' over its columns) stays one heading.
    Each piece owns the share of the printed x-span its characters occupy (round-9 step 1).
    """
    out: list[dict[str, Any]] = []
    for phrase in phrases:
        text = phrase["text"]
        bounds: list[tuple[int, int, str]] = []
        cursor = 0
        separated = bool(re.search(r"\s+(?:I|\|)\s+", text))
        for separator in re.finditer(r"\s+(?:I|\|)\s+", text):
            bounds.append((cursor, separator.start(), text[cursor:separator.start()]))
            cursor = separator.end()
        bounds.append((cursor, len(text), text[cursor:]))
        if not separated:
            out.append(phrase)
            continue
        pieces: list[tuple[int, int, str]] = []
        for start, end, piece in bounds:
            piece = piece.strip()
            if not piece:
                continue
            matches = list(_KIND_HEAD.finditer(piece))
            if len(matches) < 2:
                offset = text.find(piece, start)
                pieces.append((offset, offset + len(piece), piece))
                continue
            for match in matches:
                base = text.find(piece, start)
                pieces.append((base + match.start(), base + match.end(),
                               re.sub(r"\s+", " ", match.group(0))))
        if len(pieces) < 2:
            out.append(phrase)
            continue
        width = phrase["x1"] - phrase["x0"]
        length = max(len(text), 1)
        for start, end, piece in pieces:
            out.append({"x0": phrase["x0"] + width * start / length,
                        "x1": phrase["x0"] + width * end / length, "text": piece})
    return out


def _run_labels(phrases: list[dict[str, Any]], centers: list[float],
                gap: float, even: bool = True) -> tuple[list[str | None], bool]:
    """Which printed heading names each column, by x-position, never by order.

    A heading row that spans most of the table covers a RUN of columns: the boundary between
    two headings is the midpoint of the printed gap between them, so 'Quarter Ended | Year
    Ended' names the columns left of the boundary and the ones right of it (round-9 step 2:
    HDFC AMC's quarter band and Titan's 3-month/Year bands).  A partial heading row (a
    'Q-on-Q Growth' pair, Adani's 'Coal | Other Dry') names only the columns under it.
    Returns (labels, wide) where wide says the row covers the whole table.
    """
    if not phrases:
        return [None] * len(centers), False
    ordered = sorted(phrases, key=lambda phrase: phrase["x0"])
    if len(ordered) == 1:
        return [ordered[0]["text"]] * len(centers), True
    if even and len(centers) % len(ordered) == 0 and len(ordered) <= len(centers):
        # The measures repeat once per period group and divide the columns evenly:
        # Revenue | EBITDA | PAT | Revenue | EBITDA | PAT over six columns (round-7 class 2).
        block = len(centers) // len(ordered)
        return ([ordered[min(k // block, len(ordered) - 1)]["text"]
                 for k in range(len(centers))], True)
    span = max(phrase["x1"] for phrase in ordered) - min(phrase["x0"] for phrase in ordered)
    width = centers[-1] - centers[0] if len(centers) > 1 else 0.0
    if width and span >= 0.6 * width:
        cuts = [(a["x1"] + b["x0"]) / 2 for a, b in zip(ordered, ordered[1:])]
        labels: list[str | None] = []
        for centre in centers:
            index = 0
            while index < len(cuts) and centre > cuts[index]:
                index += 1
            labels.append(ordered[index]["text"])
        return labels, True
    limit = 1.05 * width / (len(centers) - 1) if len(centers) > 1 else gap
    labels = []
    for centre in centers:
        nearest = min(ordered, key=lambda phrase: abs(
            (phrase["x0"] + phrase["x1"]) / 2 - centre))
        distance = abs((nearest["x0"] + nearest["x1"]) / 2 - centre)
        labels.append(nearest["text"] if distance <= limit else None)
    return labels, False


def _period_row(words: list[dict[str, Any]]) -> bool:
    """A long header row that is only periods ('Q1 FY27 Q1 FY26 YoY Q1 FY27 ...')."""
    phrases = _split_merged_dates(_merge_date_phrases(
        _join_period_phrases(_phrases(words))))
    return (len(phrases) >= 2
            and all(len(phrase["text"].split()) <= 4
                    and (_direct_label(phrase["text"]) or is_delta(phrase["text"])
                         or _PERIOD_WORD.match(phrase["text"])
                         or _YEAR_RANGE.match(phrase["text"]))
                    for phrase in phrases))


def _dimension_row(words: list[dict[str, Any]]) -> bool:
    """A sub-header row of short dimension names over their period sub-columns.

    Adani's port-volume tables print 'Coal | Other Dry | '000 TEUs | MMT' directly over the
    period row; the row names what each pair of columns measures (round-9 step 4).
    """
    phrases = _join_arrow_phrases(_join_bracket_phrases(_phrases(words)))
    if len(phrases) < 2:
        return False
    text = " ".join(token["text"] for token in words)
    if _date_phrase(text) or _kind_like(text) or _STATUS.search(text):
        return False
    return all(len(phrase["text"]) <= 28 and len(phrase["text"].split()) <= 4
               and (not any(ch.isdigit() for ch in phrase["text"])
                    or bool(_UNIT_PHRASE.match(phrase["text"])))
               for phrase in phrases)


def _callout_phrase(text: str) -> bool:
    """A long printed line that names the slide's period is a call-out, not a column."""
    return len(text) > 40 and _date_phrase(text) and _kind_like(text)


def _headers(header_rows: list[list[dict[str, Any]]], anchors: list[float],
             left: float) -> list[str | None]:
    centers, gap = _refined_centers(header_rows, anchors, left)
    tolerance = 0.9 * gap
    columns: list[list[str]] = [[] for _ in anchors]
    spans: list[dict[str, Any]] = []
    layers: list[tuple[str, list[dict[str, Any]]]] = []
    for row in header_rows:
        phrases = _phrases([t for t in row if t["x1"] >= left])
        phrases = _join_bracket_phrases(phrases)
        phrases = [phrase for phrase in phrases
                   if not _unit_only(phrase["text"]) and not _garbled_date(phrase["text"])]
        phrases = _split_merged_dates(_merge_date_phrases(_join_period_phrases(phrases)))
        phrases = _join_arrow_phrases(phrases)
        phrases = _split_kind_phrases(phrases)
        phrases = [phrase for phrase in phrases
                   if not _title_phrase(phrase["text"])
                   and not _callout_phrase(phrase["text"])]
        if not phrases:
            continue
        headings = [phrase for phrase in phrases if _span_heading(phrase, gap)]
        if len(headings) == len(phrases):
            if len(headings) == 1 and _PERIOD_WORD.match(headings[0]["text"].strip()):
                continue           # a lone '9M' call-out beside the header is not a group
            spans.extend(headings)                    # a group-heading row, assigned below
            continue
        informative = [phrase for phrase in phrases if not _header_fragment(phrase, gap)]
        if not informative:
            continue
        grouped = [phrase for phrase in informative if _measure_heading(phrase, gap)]
        if len(grouped) == len(informative):
            # A row over its period sub-columns names what each column measures.  A row of
            # segment names ('HDFC MF | Industry') is a dimension instead (round-7 class 8).
            kind = ("measure" if any(_MEASURE_WORD.search(phrase["text"])
                                     for phrase in informative) else "dimension")
            layers.append((kind, informative))
            continue
        # A period header printed once over a run of measure columns spans those columns:
        # Adani's 'Q1 FY27' over Revenue | EBITDA | PAT owns all three (round-7 class 2).
        if (2 <= len(informative) < len(centers) and len(centers) % len(informative) == 0
                and all(_date_phrase(phrase["text"]) or _direct_label(phrase["text"])
                        for phrase in informative)):
            block = len(centers) // len(informative)
            for index, phrase in enumerate(sorted(informative, key=lambda p: p["x0"])):
                for k in range(index * block, index * block + block):
                    columns[k].append(phrase["text"])
            continue
        # One printed header cell per column, aligned by x-position, never by order: a date
        # line the text layer split onto two y-rows, or one heading over two columns, claims
        # only the columns its own x-span covers (contract 10.a, round-4 class 1).
        matched = 0
        for phrase in informative:
            if (_span_heading(phrase, gap) and not _date_phrase(phrase["text"])
                    and not _direct_label(phrase["text"])):
                continue                          # a lone group heading in a mixed row
            for k in _phrase_columns(phrase, centers, tolerance):
                columns[k].append(phrase["text"])
                matched += 1
        if matched:
            continue
        if len(informative) == len(centers):          # degenerate geometry: printed order only
            for k, phrase in enumerate(informative):
                columns[k].append(phrase["text"])
    prefixes: list[list[str]] = [[] for _ in anchors]
    runs: list[list[tuple[int, str]]] = []
    for position, (kind, row_phrases) in enumerate(layers):
        labels, wide = _run_labels(row_phrases, centers, gap)
        refine = bool(runs) and position == len(layers) - 1 and len(layers) > 1
        if wide and not refine:
            runs = []
            current: list[tuple[int, str]] = []
            for k, label in enumerate(labels):
                if label is None:
                    if current:
                        runs.append(current)
                        current = []
                    continue
                if current and label != current[-1][1]:
                    runs.append(current)
                    current = []
                current.append((k, label))
            if current:
                runs.append(current)
        elif runs:
            # A sub-heading row refines the group run it is printed over: 'Coal | Other Dry'
            # split the Dry columns in half and never name the Total columns (round-9 step 4).
            labels = [None] * len(centers)
            spacing = ((centers[-1] - centers[0]) / (len(centers) - 1)
                       if len(centers) > 1 else gap)
            for run in runs:
                low = min(centers[k] for k, _ in run) - 0.6 * spacing
                high = max(centers[k] for k, _ in run) + 0.6 * spacing
                members = [phrase for phrase in row_phrases
                           if low <= (phrase["x0"] + phrase["x1"]) / 2 <= high]
                if not members:
                    continue
                members.sort(key=lambda phrase: phrase["x0"])
                step = len(run) / len(members)
                for index, phrase in enumerate(members):
                    for position in range(int(index * step), int((index + 1) * step)):
                        labels[run[position][0]] = phrase["text"]
        for k, label in enumerate(labels):
            if label:
                prefixes[k].append(f"{kind}={label}")
    if spans:
        # A column belongs to the printed group heading its x-position falls under: two
        # headings over one table ('Quarter ended' / 'Year ended') split at their midpoint.
        for k, label in enumerate(_run_labels(spans, centers, gap, even=False)[0]):
            if label:
                prefixes[k].append(label)
    return [" > ".join(prefixes[k] + columns[k]) if (prefixes[k] or columns[k]) else None
            for k in range(len(columns))]


# ------------------------------------------------------------------------------------- values

def _grouping_ok(number: str) -> bool:
    """True for Western (1,234,567) or Indian (12,34,567) comma grouping only."""
    whole = number.split(".", 1)[0]
    if "," not in whole:
        return True
    groups = whole.split(",")
    if not 1 <= len(groups[0]) <= 3 or len(groups[-1]) != 3:
        return False
    middle = groups[1:-1]
    return (all(len(group) in (2, 3) for group in middle)
            and len({len(group) for group in middle}) <= 1)


def _number(text: str) -> tuple[float | None, bool]:
    """Printed token -> (number, is_percent); a dash placeholder is (None, False)."""
    raw = text.strip()
    percent = raw.endswith("%")
    if raw in ("-", "–", "—", "−"):
        return None, percent
    # '(400 bps)' / '(35 pp)': the closing bracket split off with its unit, and the bracket is
    # the printed minus (round-8 class 5).
    bracketed = re.fullmatch(r"\((\d[\d,]*(?:\.\d+)?)\s*(bps|bp|pp|%)\)", raw, re.I)
    if bracketed and _grouping_ok(bracketed.group(1)):
        return -float(bracketed.group(1).replace(",", "")), bracketed.group(2) == "%"
    clean = raw
    for marker in ("₹", "Rs.", "Rs", "INR"):
        clean = clean.replace(marker, "")
    clean = clean.strip()
    negative = clean.startswith("(") and clean.endswith(")")
    clean = clean.strip("()").replace("–", "-").replace("—", "-").replace("−", "-")
    clean = clean.rstrip("%").strip()
    if not _grouping_ok(clean):
        return None, percent                       # '860,19' is not a number
    try:
        value = float(clean.replace(",", ""))
    except ValueError:
        return None, percent
    return (-value if negative else value), percent


def _currency_of(text: str) -> str | None:
    """The currency a printed fragment names: US$ / USD, A$ / AUD, Rs / INR / ₹."""
    match = _CURRENCY.search(text or "")
    if not match:
        return None
    token = match.group(1).replace(" ", "").lower()
    return ("USD" if token in ("us$", "usd")
            else "AUD" if token in ("a$", "aud")
            else "INR" if token == "inr" else "Rs")


def _unit_of(text: str) -> tuple[str, float] | None:
    matches = list(_SCALE_WORD.finditer(text))
    if not matches:
        return None
    scale, word = _SCALES[matches[-1].group(1).lower()]
    return f"{_currency_of(text) or 'Rs'} {word}", scale


def _top_text(page: Any, height: float) -> str:
    clip = pymupdf.Rect(0, 0, page.rect.width, height * 0.15)
    return str(page.get_text("text", clip=clip))


def _basis(page: Any) -> str | None:
    clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.20)
    text = str(page.get_text("text", clip=clip)).lower()
    found = {name for name in ("standalone", "consolidated")
             if re.search(rf"\b{name}\b", text)}
    return found.pop() if len(found) == 1 else None


# ------------------------------------------------------------------------------------ periods

def _add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _fy_start(day: date) -> date:
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def _year(text: str) -> int:
    value = int(text)
    return 2000 + value if value < 100 else value


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _filing_day(filing_date: Any) -> date | None:
    if filing_date is None:
        return None
    if isinstance(filing_date, date):
        return filing_date
    try:
        return date.fromisoformat(str(filing_date)[:10])
    except ValueError:
        return None


def _plausible(day: date, filing_date: Any = None) -> bool:
    """A real date inside the run's window: 2000-2100, within 3 years of the filing date."""
    if not 2000 <= day.year <= 2100:
        return False
    filed = _filing_day(filing_date)
    return filed is None or abs((day - filed).days) <= _PLAUSIBLE_DAYS


def _last_date(text: str, filing_date: Any = None) -> date | None:
    candidates: list[tuple[int, date]] = []
    for match in _DATE_DMY.finditer(text):
        try:
            candidates.append((match.end(), date(_year(match.group(3)), int(match.group(2)),
                                                 int(match.group(1)))))
        except ValueError:
            pass
    for match in _DATE_DMY_WORD.finditer(text):
        month = _MONTHS.get(match.group(2)[:3].lower())
        if month:
            try:
                candidates.append((match.end(), date(_year(match.group(3)), month,
                                                     int(match.group(1)))))
            except ValueError:
                pass
    for match in _DATE_MDY.finditer(text):
        month = _MONTHS.get(match.group(1)[:3].lower())
        if month:
            try:
                candidates.append((match.end(), date(_year(match.group(3)), month,
                                                     int(match.group(2)))))
            except ValueError:
                pass
    for pattern in (_DATE_MY, _DATE_MY_SPACE):
        for match in pattern.finditer(text):
            month = _MONTHS.get(match.group(1)[:3].lower())
            if month:
                candidates.append((match.end(), _month_end(_year(match.group(2)), month)))
    candidates = [item for item in candidates if _plausible(item[1], filing_date)]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _garbled_date(text: str) -> bool:
    """A date-shaped fragment that does not parse to a plausible date (contract 10.e)."""
    if _DATE_VALUE.match(text) or _last_date(text) is not None:
        return False
    return bool(re.search(r"\d{1,2}[.\-/]\d{1,3}[.\-/]\d{2,4}|\d{1,2},\d{4}", text))


def _fy_start_of_range(text: str) -> date | None:
    """'9M 25-26' / 'FY 2025-26' -> 1 April 2025."""
    for match in reversed(list(_FY_RANGE.finditer(text))):
        first, second = _year(match.group(1)), _year(match.group(2))
        if second == first + 1:
            return date(first, 4, 1)
    return None


def _names_a_date(text: str) -> bool:
    """The header prints a month, a year or a date fragment that did not resolve."""
    return bool(re.search(r"\b(?:19|20)\d{2}\b|\d{1,2}[.\-/]\d{1,2}", text)
                or any(_month_word(word) for word in re.findall(r"[A-Za-z]+", text)))


def _latest_period(kind: str, filing_day: date) -> str | None:
    """'9M' / 'FY' / 'H1' / 'Q' with no printed year: the latest period ending before the filing."""
    months = {"FY": (3,), "9M": (12,), "H1": (3, 9), "Q": (3, 6, 9, 12)}.get(kind)
    if not months:
        return None
    ends = [_month_end(year, month) for year in (filing_day.year, filing_day.year - 1)
            for month in months if _month_end(year, month) < filing_day]
    if not ends:
        return None
    end = max(ends)
    start = _fy_start(end) if kind in ("FY", "9M") else _add_months(
        date(end.year, end.month, 1), -({"H1": 5, "Q": 2}.get(kind) or 0))
    return _period_id(start, end)


def _period_id(start: date | None, end: date) -> str | None:
    try:
        return str(period_row(start, end)["period_id"])
    except ValueError:
        return None


def _quarter_id(quarter: int, fy_end_year: int) -> str | None:
    fy_start = date(fy_end_year - 1, 4, 1)
    return _period_id(_add_months(fy_start, 3 * (quarter - 1)),
                      _add_months(fy_start, 3 * quarter) - _DAY)


def _half_id(half: int, fy_end_year: int) -> str | None:
    fy_start = date(fy_end_year - 1, 4, 1)
    return _period_id(_add_months(fy_start, 6 * (half - 1)),
                      _add_months(fy_start, 6 * half) - _DAY)


_YTD = re.compile(r"\bYTD\s*(?:FY)?\s*(\d{2,4})\b", re.I)


def _ytd_label(text: str, filing_date: Any = None) -> str | None:
    """'YTD FY26' -> the fiscal year to the latest quarter end before the filing date."""
    match = _YTD.search(text)
    day = _filing_day(filing_date)
    if not match or day is None:
        return None
    year = _year(match.group(1))
    ends = [_month_end(y, month) for y in (day.year, day.year - 1)
            for month in (3, 6, 9, 12) if _month_end(y, month) < day]
    if not ends:
        return None
    end = max(ends)
    fiscal_start = date(end.year if end.month >= 4 else end.year - 1, 4, 1)
    if fiscal_start.year + 1 != year:
        return None
    return _period_id(fiscal_start, end)


def _direct_label(text: str) -> str | None:
    match = re.search(r"\bQ([1-4])\s*[-/]?\s*FY\s*(\d{2,4})\b", text, re.I)
    if match:
        return _quarter_id(int(match.group(1)), _year(match.group(2)))
    match = re.search(r"\bH([12])\s*[-/]?\s*FY\s*(\d{2,4})\b", text, re.I)
    if match:
        return _half_id(int(match.group(1)), _year(match.group(2)))
    match = re.search(r"\b9\s*M\s*FY\s*(\d{2,4})\b", text, re.I)
    if match:
        fy_start = date(_year(match.group(1)) - 1, 4, 1)
        return _period_id(fy_start, _add_months(fy_start, 9) - _DAY)
    # 'Q1 25-26' / 'Q2 26-27': the quarter of FY 2025-26 / 2026-27.
    match = re.search(r"\bQ([1-4])\s*(\d{2,4})\s*[-–]\s*(\d{2,4})\b", text)
    if match:
        return _quarter_id(int(match.group(1)), _year(match.group(3)))
    match = re.search(r"\bH([12])\s*(\d{2,4})\s*[-–]\s*(\d{2,4})\b", text, re.I)
    if match:
        return _half_id(int(match.group(1)), _year(match.group(3)))
    match = re.search(r"\b9\s*M\s*(\d{2,4})\s*[-–]\s*(\d{2,4})\b", text, re.I)
    if match:
        fy_start = date(_year(match.group(1)), 4, 1)
        return _period_id(fy_start, _add_months(fy_start, 9) - _DAY)
    match = re.search(r"\bFY\s*(\d{2,4})\s*[-–/]\s*(\d{2,4})\b", text, re.I)
    if match:
        fy_start = date(_year(match.group(1)), 4, 1)
        return _period_id(fy_start, _add_months(fy_start, 12) - _DAY)
    match = re.search(r"\bFY\s*(\d{2,4})\b", text, re.I)
    if match:
        fy_start = date(_year(match.group(1)) - 1, 4, 1)
        return _period_id(fy_start, _add_months(fy_start, 12) - _DAY)
    return None


def _kind_in(segment: str) -> str | None:
    """The most specific period word in one header row: as-at, 9M, half, quarter, year."""
    for pattern, kind in _KINDS:
        if pattern.search(segment):
            return kind
    return None


def _date_kind(text: str, filing_date: Any = None, doc_type: str | None = None,
               balance_sheet: bool | None = None,
               page_span: str | None = None) -> str | None:
    kind = None
    joined = " ".join(segment.strip() for segment in text.split(" > ") if segment.strip())
    for segment in reversed([s.strip() for s in text.split(" > ") if s.strip()]):
        kind = _kind_in(segment)
        if kind:
            break
    if kind is None:
        kind = _kind_in(joined)      # 'As > on' split by the header stack is still 'As on'
    day = _last_date(joined, filing_date)          # assemble a wrapped date row first
    if day is None:
        day = _last_date(text, filing_date)
    if kind is None and day is not None and page_span:
        # The page title names the statement period and the header stack lost it: a cash-flow
        # page 'for the half year ended' prints half-year columns (round-6 class 5).
        kind = page_span
    if kind == "RATIO" and day is not None:
        # A Key Financial Ratios page prints period ENDS as bare dates (30.09.25 / 31.03.25 /
        # 30.09.24) in an H1 filing: a 30-September column is the half year ending that day and
        # a 31-March column the fiscal year, never a quarter (round-9 step 3).
        first = date(day.year, day.month, 1)
        if day.month == 3:
            return _period_id(_add_months(first, -11), day)
        if day.month == 9:
            return _period_id(_add_months(first, -5), day)
        kind = None
    if kind is None:
        # A bare date names no period word.  A balance sheet and a deck print as-at columns,
        # a results P&L prints the quarter ending that day (contract 10.e).
        if day is None:
            return None
        if balance_sheet or doc_type == "deck":
            return _period_id(None, day)
        if doc_type == "results" or balance_sheet is False:
            return _period_id(_add_months(date(day.year, day.month, 1), -2), day)
        return _period_id(None, day)
    if day is None:
        fy_start = _fy_start_of_range(joined) or _fy_start_of_range(text)
        months = {"Q": 3, "H1": 6, "9M": 9, "FY": 12}.get(kind)
        if fy_start is not None and months:
            return _period_id(fy_start, _add_months(fy_start, months) - _DAY)
        if kind == "FY":
            years = re.findall(r"\b((?:19|20)\d{2})\b", text)
            if years:                                 # 'Full Year Ended > 2024'
                day = date(int(years[-1]), 3, 31)
                if not _plausible(day, filing_date):
                    return None
                return _period_id(_add_months(date(day.year, day.month, 1), -11), day)
        if kind == "9M":
            years = re.findall(r"\b((?:19|20)\d{2})\b", text)
            if years:                                 # '9M > December > 31,2024'
                year = int(years[-1])
                if _plausible(date(year, 12, 31), filing_date):
                    return _period_id(date(year, 4, 1), date(year, 12, 31))
        filed = _filing_day(filing_date)
        if filed is not None and doc_type != "deck" and not _names_a_date(joined):
            return _latest_period(kind, filed)     # bare '9M' / 'FY' / 'Quarter ended'
        return None
    first_of_month = date(day.year, day.month, 1)
    if kind == "POINT":
        return _period_id(None, day)
    if kind == "Q":
        return _period_id(_add_months(first_of_month, -2), day)
    if kind == "H1":
        return _period_id(_add_months(first_of_month, -5), day)
    if kind == "9M":
        return _period_id(_fy_start(day), day)
    return _period_id(_add_months(first_of_month, -11), day)


def period_from_header(header: str | None, filing_date: Any = None,
                       doc_type: str | None = None,
                       balance_sheet: bool | None = None,
                       page_span: str | None = None) -> str | None:
    """The period a printed column header names, or None when it does not resolve."""
    if not header:
        return None
    segments = [segment.strip() for segment in header.split(" > ") if segment.strip()]
    if not segments:
        return None
    last = segments[-1]
    if GROWTH.search(last) and _last_date(last, filing_date) is None:
        return None                                   # a difference or growth column
    resolved = _ytd_label(header, filing_date)
    if resolved:
        return resolved
    # 'H1 > FY27' is the half of FY27, not the whole fiscal year: the span word and the year
    # are printed on two header lines, and the year line alone must not win (round-6 class 5).
    split_label = re.search(r"\b(Q\s*[1-4]|H\s*[12]|9\s*M)\s*[-/]?\s*FY\s*(\d{2,4})\b",
                            " ".join(segments), re.I)
    if split_label:
        span = re.sub(r"\s+", "", split_label.group(1))
        resolved = _direct_label(f"{span} FY{split_label.group(2)}")
        if resolved:
            return resolved
    resolved = _direct_label(last)
    bare_month = bool(re.fullmatch(r"[A-Za-z]{3,9}\s*[-'’ ]\s*\d{2,4}", last))
    if resolved and not (bare_month and doc_type == "results"):
        return resolved
    # A bare month-year under a 'Quarter Ended' page title ('Mar-25') names the quarter, not
    # the fiscal year the month happens to end: the page title decides (round-9 step 1).
    span = None if (bare_month and doc_type == "results") else page_span
    resolved = _date_kind(header, filing_date, doc_type, balance_sheet, span)
    if resolved:
        return resolved
    for segment in reversed(segments[:-1]):
        resolved = _direct_label(segment)
        if resolved:
            return resolved
    return None


def is_delta(header: str | None) -> bool:
    """A difference or growth column ('Inc/Dec%', 'YoY (%)', 'Change'), never a period's value."""
    if not header or not DELTA_WORD.search(header):
        return False
    last = [segment for segment in header.split(" > ") if segment.strip()][-1]
    return bool(DELTA_WORD.search(last)) or _last_date(last) is None


def _label_currency(label: str) -> tuple[str, float] | None:
    """The currency a label names WITH the scale word printed beside it (contract 10.d).

    A currency alone is not a unit: 'EBIT Rs' under a '(Rs Mn)' title is Rs million, never
    Rs at scale 1 (round-6 class 1).
    """
    match = _CURRENCY.search(label)
    if not match:
        return None
    scale = _SCALE_WORD.search(label, match.end())
    if scale is None:
        return None
    factor, word = _SCALES[scale.group(1).lower()]
    return f"{_currency_of(match.group(1)) or 'Rs'} {word}", factor


def label_unit(label: str | None) -> tuple[str, float] | None:
    """A row that names its own unit: no crore/lakh scale, unit from the label (10.d)."""
    if not label:
        return None
    if _PERCENT_ROW.search(label):
        return ("%", 1.0)
    if _MMT_ROW.search(label):
        return ("MMT", 1.0)            # a physical million-tonne count, not a bare count
    if _PER_SHARE.search(label) and not _CAPITAL.search(label):
        return ("inr_per_share", 1.0)
    if _PER_UNIT.search(label):
        return (_currency_of(label) or "Rs", 1.0)   # money per unit, never the page scale
    if _RATIO_ROW.search(label):
        return ("ratio", 1.0)
    if _COUNT_ROW.search(label) or _COUNT_LEVEL.search(label):
        return ("count", 1.0)
    return _label_currency(label)                    # only with a printed scale word


_HEADER_MMT = re.compile(r"\bmmt\b|\bmt\b", re.I)
_HEADER_TEU = re.compile(r"['’]?0{3}\s*teus?\b|\bteus?\b", re.I)


def _header_unit(header: str | None) -> tuple[str, float] | None:
    """A column header that prints its own physical unit: 'MMT', "'000 TEUs' (step 4)."""
    text = header or ""
    if _HEADER_TEU.search(text):
        return ("count", 1000.0)
    if _HEADER_MMT.search(text):
        return ("MMT", 1.0)
    return None


_UNIT_CELL_WORDS = re.compile(
    r"^(?:nos?\.?|no\.|numbers?|times|%|te|mt|mw|mmt|mn\s*min|'?000'?s|"
    r"inr|rs\.?|₹|us\s*\$|usd|a\s*\$|aud)$", re.I)


def _unit_cell_text(text: str) -> bool:
    """A printed unit cell beside a label: 'Rs Mn', '₹ Cr', 'US$ Bn', 'Mn Min', 'Nos', '%'.

    A row prints its unit in its own cell, so the cell is the row's unit, not part of its
    name: 'EBIT | Rs Mn | 680,996' is EBIT in Rs million (contract 10.d, round-6 class 1).
    """
    text = " ".join((text or "").split())
    if not text or len(text) > 14:
        return False
    return bool(_SCALE_WORD.search(text) or _UNIT_CELL_WORDS.match(text))


def _row_unit(text: str, label: str | None = None) -> tuple[str, float | None] | None:
    """A row's unit cell as a unit: 'Rs Mn'/'₹ Cr' by scale, 'Nos' a count, 'Times' a ratio.

    A bare currency unit cell ('US$' beside 'Average Revenue Per User (ARPU)') names the
    currency, never the page's Rs: a per-unit label keeps scale 1, any other label keeps
    scale NULL with the currency printed (round-7 class 1).
    """
    found = _unit_of(text)
    low = " ".join((text or "").lower().split())
    if label and _COUNT_LEVEL.search(label) and low in _SCALES:
        return ("count", _SCALES[low][0])  # 'Population Covered 2 Bn' is people, never Rs
    if found:
        return found
    if _THOUSAND.fullmatch(low):
        return ("count", 1000.0)          # "Volume* (in 000's)": a thousand-fold count
    if re.fullmatch(r"nos?\.?|no\.|numbers?", low):
        return ("count", 1.0)
    if re.fullmatch(r"times|ratio", low):
        return ("ratio", 1.0)
    if low in ("%", "pp", "bps", "bp"):
        return (low if low in ("%", "pp") else "bps", 1.0)
    if re.fullmatch(r"te|mt|mw|mmt|kg|mn\s*min|'?000'?s", low):
        return ("count", 1.0)
    currency = _currency_of(text)
    if currency:
        per_unit = bool(label) and bool(_PER_UNIT.search(label) or _PER_SHARE.search(label))
        return (currency, 1.0 if per_unit else None)
    return None


def _table_unit(header_rows: list[list[dict[str, Any]]],
                page_unit: tuple[str, float] | None) -> tuple[str, float] | None:
    """The unit note printed nearest above the table, else the page's unit (round-6 class 2).

    'Amount in US$ Mn, except ratios' over its table overrides the document default.
    """
    for row in reversed(header_rows):
        text = " ".join(str(token["text"]) for token in row if str(token["text"]).strip())
        if not text:
            continue
        if _THOUSAND.search(text):
            return ("count", 1000.0)      # 'Volume* (in 000's) RHS' over its table
        if any(ch.isdigit() for ch in text):
            continue
        found = _unit_of(text)
        if found:
            return found
    return _unit_of(" ".join(str(token["text"]) for row in header_rows
                              for token in row if str(token["text"]).strip())) or page_unit


def _prose_row(words: list[dict[str, Any]]) -> bool:
    """A prose line: one long run of words with no digit, or a sentence ending in ``.``."""
    text = " ".join(token["text"] for token in words).strip()
    if text.endswith("."):
        return True
    return (len(words) >= 8 and not any(ch.isdigit() for ch in text)
            and len(_phrases(words)) == 1)


def _plain_number(text: str) -> bool:
    """A printed figure (not a date or a period label) is data, not a column heading."""
    return bool(NUM.match(text)) and any(ch.isdigit() for ch in text) \
        and not _DATE_TOKEN.match(text) and not _DATE_VALUE.match(text)


_STATUS = re.compile(r"\b(?:audited|unaudited|reviewed|restated)\b", re.I)


def _header_like(words: list[dict[str, Any]]) -> bool:
    """A column-heading row names a date, period, unit or audit status (a logo does not)."""
    text = " ".join(token["text"] for token in words)
    return bool(_date_phrase(text) or _kind_like(text) or _direct_label(text)
                or _SCALE_WORD.search(text) or _STATUS.search(text))


def _measure_row(words: list[dict[str, Any]]) -> bool:
    """A measure group row ('REVENUE | EBITDA | EBITDA MARGIN') over its period sub-columns."""
    phrases = _join_bracket_phrases(_phrases(words))
    if len(phrases) < 2 or any(any(ch.isdigit() for ch in phrase["text"]) for phrase in phrases):
        return False
    text = " ".join(token["text"] for token in words)
    if _date_phrase(text) or _kind_like(text) or _STATUS.search(text):
        return False
    return all(_measure_text(phrase["text"]) for phrase in phrases)


def _measure_title(words: list[dict[str, Any]]) -> str | None:
    """A one-cell measure heading over a table: 'Segment Revenue', 'Revenue', 'EBITDA'.

    Bharti prints its segment tables as numbered sections ('1. Segment Revenue', '2. Segment
    Results') with the measure names at the left and the periods across the columns, so the
    measure is a row label, never a two-cell group row (round-8 class 2).
    """
    phrases = _join_bracket_phrases(_phrases(words))
    if len(phrases) != 1:
        return None
    return _measure_name(phrases[0]["text"])


def _measure_name(text: str | None) -> str | None:
    """A one-cell measure heading as its name: '1. Segment Revenue' -> 'Segment Revenue'."""
    raw = (text or "").strip().rstrip("*#†‡").strip()
    numbered = bool(_SECTION_NUMBER.match(raw))
    text = _SECTION_NUMBER.sub("", raw).strip().rstrip("*#†‡").strip()
    if not text or not _MEASURE_WORD.search(text) or not _measure_text(text):
        return None
    if numbered or _MEASURE_SECTION.match(text):
        return text
    return None


def _split_ratio_label(label: str | None) -> str | None:
    """Two printed ratio rows merged onto one label line: keep the row printed second.

    'Gross Profit Margin on Net Sales Net Profit Margin on Net Sales' is two labels the text
    layer glued together; the row's own name is the second one (round-8 class 7).
    """
    text = (label or "").strip()
    matches = list(_RATIO_NAME.finditer(text))
    if len(matches) < 2:
        return None
    second = matches[1]
    if second.start() < len(text) * 0.15:
        return None
    tail = text[second.start():].strip(" ,;-")
    return tail if len(_letters(tail)) >= 6 else None


def _table_title(header_rows: list[list[dict[str, Any]]],
                 stack: list[list[dict[str, Any]]]) -> str | None:
    """The nearest table or segment title printed over the header stack (round-8 class 3).

    Bharti prints 'Airtel Business' / 'Passive Infrastructure Services' / 'Homes' over its
    notes' tables; the title is the parent of every row in that table, not a lost line.
    """
    if not stack:
        return None
    top = min(float(token["y0"]) for token in stack[0])
    for row in reversed(header_rows):
        words = [token for token in row if token["text"].strip()]
        if not words or max(float(token["y1"]) for token in words) >= top:
            continue
        text = _SECTION_NUMBER.sub("", " ".join(token["text"] for token in words)).strip()
        if not text or len(text.split()) > 6 or text.endswith("."):
            continue
        if len(_letters(text)) < 3 or text[:1].islower() or len(text.split()) == 1:
            # 'th' / a fragment / a bullet tail ('additions and European subsea expansion') /
            # a one-word logo ('Pidilite') is not a table title (round-9 step 5).
            continue
        if (text.isupper() or re.search(r"\b(?:limited|ltd|plc|company|corporation|inc)\b",
                                        text, re.I)
                or re.match(r"^(?:audited|unaudited|consolidated|standalone)\b", text, re.I)):
            continue                           # a letterhead/statement title, not a table's title
        if (any(ch.isdigit() for ch in text) or _unit_only(text) or _measure_row(words)
                or _header_like(words) or _prose_label(text)
                or re.match(r"^(?:particulars|notes?|consolidated|standalone)$", text, re.I)
                or re.search(r"\b(?:statement|results?|financials?|presentation|highlights|"
                             r"ratios?|profit\s*(?:&|and)\s*loss|balance\s*sheet|"
                             r"financial\s+position|annual\s+report)\b", text, re.I)):
            continue
        return text
    return None


def _title_measure(title: str | None) -> str | None:
    """A table title that names its measure: '4.1 Revenue Analysis' -> 'Revenue'."""
    if not title:
        return None
    text = re.sub(r"\b(?:analysis|summary|performance|details?)\b", " ", title, flags=re.I)
    text = " ".join(text.split()).strip()
    return _measure_name(text)


def _header_stack(header_rows: list[list[dict[str, Any]]], anchors: list[float],
                  left: float, right: float | None = None) -> list[list[dict[str, Any]]]:
    """Header rows upward from the table, inside its x-range, stopping at the first prose row."""
    gap = min((b - a for a, b in zip(anchors, anchors[1:])), default=60.0)
    if right is None:
        right = anchors[-1] + max(1.5 * gap, 40.0)  # a span heading may pass the last anchor
    kept: list[list[dict[str, Any]]] = []
    skips = 0
    continuous = False                          # the row printed under this one was kept
    for row in reversed(header_rows):
        words = [token for token in row if token["text"].strip()]
        if not words:
            continue
        if any(token["x0"] < left < token["x1"] for token in words):
            # A header cell ('Unit') may straddle the label/figure edge derived from the
            # figures: drop that word, never the whole header row (round-9 step 4).  A slide
            # title that runs in from the left leaves only a fragment ('FY27 vs. Q1 FY26'):
            # that is not a header row.
            words = [token for token in words if not token["x0"] < left < token["x1"]]
            probe = [token for token in words
                     if token["x0"] >= left and (token["x1"] <= right
                                                 or token["x0"] < right - 4.0)]
            headerish = [phrase for phrase in _phrases(probe)
                         if _date_phrase(phrase["text"]) or _direct_label(phrase["text"])
                         or _UNIT_PHRASE.match(phrase["text"])
                         or _SCALE_WORD.search(phrase["text"])]
            if len(headerish) < 2 and not _date_parts(probe):
                skips += 1
                continuous = False
                if kept and skips >= 3:
                    break
                continue
            if not words:
                skips += 1
                continuous = False
                if kept and skips >= 3:
                    break
                continue
        # A word that only crosses the RIGHT edge (a 'Remarks' column beside the figures, a
        # long heading) is trimmed, never drops the header row: the Coal India Key Financial
        # Ratios table lost its date row that way (round-8 class 0).
        inside = [token for token in words
                  if token["x0"] >= left and (token["x1"] <= right
                                              or token["x0"] < right - 4.0)]
        if not inside:
            # A call-out printed left of the table is still a non-header row: three of them
            # stop the stack, so it never reaches the slide's own title row (round-9 step 5).
            skips += 1
            continuous = False
            if kept and skips >= 3:
                break
            continue                            # entirely outside the table
        if _prose_row(inside):
            break
        row_text = " ".join(token["text"] for token in inside)
        if (re.search(r"\bvs\.?\b", row_text, re.I)
                and not re.search(r"\b(?:var|variance|change|growth|inc|dec)\b", row_text, re.I)):
            skips += 1
            continuous = False
            if kept and skips >= 3:
                break
            continue                            # a slide title ('Port volume - Q1 FY27 vs. ...')
        if len(row_text) > 80 and not _date_phrase(row_text) \
                and not _period_row(inside):
            skips += 1
            continuous = False
            if kept and skips >= 3:
                break
            continue                            # a statement title, not a column header
        phrases = _phrases(inside)
        spread = min((b["x0"] - a["x1"] for a, b in zip(phrases, phrases[1:])), default=0.0)
        if _measure_row(inside) and (
                any(_MEASURE_WORD.search(phrase["text"]) for phrase in phrases)
                or len(phrases) < len(anchors) or spread >= 0.4 * gap
                or len({phrase["text"].lower() for phrase in phrases}) < len(phrases)):
            # A real measure/dimension row spans the columns; a slide title over the table
            # ('Key Financial Ratios') prints three words at text spacing, not column spacing.
            kept.append(inside)
            skips = 0
            continuous = True
            if len(kept) >= 6:
                break
            continue
        near_below = (bool(kept) and continuous and abs(
            min(float(token["y0"]) for token in inside)
            - min(float(token["y0"]) for token in kept[-1])) <= 32.0)
        if near_below and _dimension_row(inside):
            # A sub-header directly over the period row names what its column pairs measure
            # ('Coal | Other Dry | '000 TEUs | MMT', round-9 step 4).
            kept.append(inside)
            skips = 0
            if len(kept) >= 6:
                break
            continue
        if not _header_like(inside) \
                or (any(_plain_number(token["text"]) for token in inside)
                    and not _date_parts(inside) and not _date_phrase(row_text)):
            skips += 1
            continuous = False
            if kept and skips >= 3:
                break                           # the stack is above the slide's call-outs
            continue                            # a heading row, but not this table's
        kept.append(inside)
        skips = 0
        continuous = True
        if len(kept) >= 6:
            break
    return list(reversed(kept))


_SENTENCE = re.compile(r"(?<![A-Za-z])[a-z]{3,}\.\s+[A-Z]")   # 'growth. Growth', not 'Cons. D'
_BULLET = re.compile(r"^\s*[•●▪·‣◦*]")


def _prose_label(label: str | None) -> bool:
    """A sentence or a paragraph is not a row label.

    A slide bullet ('• Growth was well- supported ...') is prose, never a row name
    (contract 10.a, round-6 class 8), and a long sentence with no bracket is prose too.
    """
    if not label:
        return False
    if len(label) > 80 or _SENTENCE.search(label) or _BULLET.match(label):
        return True
    return len(label.split()) > 12 and "(" not in label and ":" not in label


# --------------------------------------------------------------------------------------- page

def _append_label(cells: list[dict[str, Any]], text: str) -> None:
    """The wrapped label line printed under a row belongs to that row (contract 10.a)."""
    text = re.sub(r"^\(?[a-z]\)\s+", "", text.strip()).strip()   # a printed '(e)' is no name
    for cell in cells:
        label = cell["row_label"]
        cell["row_label"] = f"{label} {text}" if label else text


_CONTINUATION = re.compile(r"(?:[&,]|\b(?:and|of|before|to|with|from))$", re.I)


def _open_bracket(text: str) -> bool:
    return text.count("(") > text.count(")") or text.count("[") > text.count("]")


_CONT_MARKER = re.compile(
    r"^\(?(?:i{1,3}|iv|v|vi{0,3}|ix|x|[a-z])\)?\s*[.,)]\s+\S", re.I)


_LABEL_LAST = {"employee", "depreciation", "finance", "trade", "share", "non", "deferred"}
_LABEL_NEXT = {"benefits", "benefit", "expense", "expenses", "costs", "payables",
               "receivable", "receivables", "based", "current", "tax"}


def _label_continues(above: str, below: str) -> bool:
    """The next printed line finishes the label above it (contract 10.a, round-6 class 3).

    A wrapped label is one row: 'Cash profit from operations before Derivative &' +
    'Exchange Fluctuations', 'Logistics (other than Trucking &' + 'International Freight
    Network)', a line ending in 'of'/'and'/'before' or leaving a bracket open, and a single
    word printed directly under a label that already filled its column ('Enterprises').
    A restatement label split by the text layer keeps both halves: 'Previously reported
    Employee' + 'Benefits Expense' (round-9 step 5).  A roman/letter marker starting the next
    line ('ii, Income tax effect') begins its own printed row, never a wrap (round-7 class 7).
    """
    above = (above or "").strip()
    below = (below or "").strip()
    if not above or not below:
        return False
    if _CONT_MARKER.match(below):
        return False
    if _CONTINUATION.search(above) or _open_bracket(above):
        return True
    if below[0].islower() or below[0] in ")]}":
        return True
    last = re.sub(r"[^a-z]", "", above.split()[-1].lower())
    first = re.sub(r"[^a-z]", "", below.split()[0].lower())
    if last in _LABEL_LAST and first in _LABEL_NEXT:
        return True
    return len(below.split()) == 1 and len(above) >= 40


def _wrap_fragment(text: str) -> bool:
    """A line printed under a row to finish its label: '(no. of months of Gross Sales)'."""
    first = text.split(" ", 1)[0]
    if MARKER.match(first) or SUB_LABEL.match(first):
        return False
    if text.startswith("(") or (text[:1].islower() and text[:1].isalpha()):
        return True
    return text.startswith("[") and text.endswith("]")   # '[Share capital + other equity]'


def _point_period(header: str, filing_date: Any = None, doc_type: str | None = None,
                  balance_sheet: bool | None = None,
                  page_span: str | None = None) -> str | None:
    """The column's own printed date as a POINT period (a balance item, contract 10.i).

    A column labelled only by its period ('Q1 FY27', '9M 25-26') is a point at that period's
    end date: a balance printed under a quarter heading is the balance on the last day.
    """
    day = _last_date(" ".join(segment for segment in header.split(" > ") if segment.strip()),
                     filing_date)
    if day is None:
        span = period_from_header(header, filing_date, doc_type, balance_sheet, page_span)
        if not span:
            return None
        if span.startswith("/"):
            return span
        day = _filing_day(span.partition("/")[2])
    return _period_id(None, day) if day else None


def _prior_period(period_id: str) -> str | None:
    """The period of the same length ending the day before ``period_id`` starts."""
    if not period_id or period_id.startswith("/"):
        return None
    start, _, end = period_id.partition("/")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return None
    months = (last.year - first.year) * 12 + last.month - first.month + 1
    return _period_id(_add_months(first, -months), first - _DAY)


def _column_values(item: dict[str, Any], anchors: list[float],
                   tolerance: float) -> dict[int, float]:
    values: dict[int, float] = {}
    for token in item["data"]:
        column = min(range(len(anchors)), key=lambda k: abs(anchors[k] - token["x1"]))
        if abs(anchors[column] - token["x1"]) > tolerance:
            continue
        value, percent = _number(token["text"])
        if value is not None and not percent:
            values[column] = value
    return values


def _cash_headers(prepared: list[dict[str, Any]], headers: list[str | None],
                  anchors: list[float], tolerance: float, filing_date: Any,
                  doc_type: str | None, balance_sheet: bool | None,
                  page_span: str | None) -> tuple[list[str | None], dict[int, str]]:
    """Order a cash-flow table's columns from its own opening/closing cash (round-7 class 5).

    When a column's opening cash equals the next column's closing cash, that column is the
    later period.  If the header stack lost the span words and both columns resolved to the
    same period, the earlier column is one period back, never the same period twice.
    """
    opening_row = next((item for item in prepared if item["is_data"]
                        and _CASH_OPEN.search(item["label"] or "")), None)
    closing_row = next((item for item in prepared if item["is_data"]
                        and _CASH_CLOSE.search(item["label"] or "")), None)
    overrides: dict[int, str] = {}
    if opening_row is None or closing_row is None:
        return headers, overrides
    opening = _column_values(opening_row, anchors, tolerance)
    closing = _column_values(closing_row, anchors, tolerance)
    later = [k for k in range(len(anchors) - 1)
             if k in opening and k + 1 in closing
             and abs(opening[k] - closing[k + 1]) <= 0.011]
    for k in later:
        if k + 1 >= len(headers):
            continue
        current = period_from_header(headers[k], filing_date, doc_type, balance_sheet, page_span)
        earlier = period_from_header(headers[k + 1], filing_date, doc_type, balance_sheet,
                                     page_span)
        if current and earlier and current == earlier:
            prior = _prior_period(earlier)
            if prior:
                overrides[k + 1] = prior
    return headers, overrides


def _letters(text: str) -> str:
    return re.sub(r"[^A-Za-z]", "", text)


# A broken text layer prints a label that is not words ('l:Jnallocable / el', 'Financial
# riabilities'): the cell keeps its value but is flagged 'text_layer;garbled' when over 30% of
# the label's letters sit in tokens that are neither dictionary words nor known names
# (contract 10.j, round-5 class 5). The vocabulary is the repo's own business lexicon plus the
# common English words printed on statement rows; it only decides a flag, never a value.
_LEXICON_DIR = Path(__file__).resolve().parents[1] / "pilot3" / "lexicon"
_COMMON_WORDS = """
a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had
has have having he her here hers him his how i if in into is it its itself just me more most my
no nor not now of off on once only or other our ours out over own same she should so some such
than that the their theirs them then there these they this those through to too under until up
very was we were what when where which while who whom why will with would you your
account accounts accrued accrued addition adjusted adjustment administrative advertising after
against aggregate amortisation amortization amount amounts annual annum applicable average
balance balances bank basic benefits borrowings capital carried cash change changes charge
charges closing commission compensation comprehensive consolidated consumption contribution
cost costs crore crores current customer customers day days debt deferred deficit deposit
deposits depreciation derived diluted direct dividend dividends during earning earnings ebit
ebitda employee employees equity equivalent except excluding expense expenses export finance
financial fixed foreign from fund funds gross group growth held higher holding holdings income
including increase incurred indirect insurance interest inventory inventories investment
investments inventory key lakh lakhs land lease leases less liabilities liability loan loans
long loss losses machinery made margin margins market material materials maximum minimum
million minority money month months net non number of operating operation operations other
others outflow outstanding paid par particular payments payable payables period per percent
percentage plant pledged post power ppe preferred profit profits property provision provisions
purchase purchases quarter rate rates ratio raw realised realized receivable receivables
reconciliation relating rent repair reserve reserves retained return revenue revenues
reversal sale sales salary segment segments services share shares short statement stock
stocks subsidiary surplus tax taxation terms total treasury turnover unallocated unit units
value variable wages weighted working written year years half quarter quarter ended
capitalisation capitalisation capital work progress
january february march april may june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec
audited unaudited reviewed restated standalone consolidated annual quarterly monthly yearly
above accordance across acquire acquiring added addition adjusted administration applicable
arising arrangement arrangement associate associates attributable authoritative authorised
authorized bad basis beginning benefit benefits brands cancellation capitalised capitalised
catering certificate claim claims closure coast components comprise comprising considered
connections contract contracts controlling convertible core countries creditors currency
debentures decrease defined designated derivative derivatives differences disposal doubtful
dues donation effective eliminations enterprises equipment etc exchange exchange fluctuations
foreign given government grant grants holders institution intangible interests issued licence
license majority maturities maturity matter measurement minority modification mutual
noncurrent obligations original owners parent parties passu pertains placed plans portion
preference prepared principal prior proceeds redemption refer refund refunded repayment
related relevant reclassified reporting respect revaluation scrap scrapping section small
spectrum stations strong subsequently subscription subsidiaries tangible terminated termination
thereof towards tower towers transactions transferred translating translation translations
twelve unallocated unrealised usage valuation various waiver worth
sq ft nos no location locations effect rest world annualised general selling without port ports
container premise premises scheme hotel mature include includes onwards lean cable
un allocable overdraft disputed
""".split()


@lru_cache(maxsize=1)
def _vocabulary() -> frozenset[str]:
    """Dictionary words for the garbled-label test: common English plus the repo's lexicons."""
    words = set(_COMMON_WORDS)
    try:
        for path in _LEXICON_DIR.glob("*.yaml"):
            words.update(word.lower() for word in re.findall(
                r"[A-Za-z]{2,}", path.read_text(encoding="utf-8")))
    except OSError:
        pass
    return frozenset(words)


def _known_word(word: str) -> bool:
    vocabulary = _vocabulary()
    if word in vocabulary:
        return True
    for suffix, replacement in (("ied", "y"), ("ies", "y"), ("ments", "ment"), ("ment", ""),
                                ("es", ""), ("s", ""), ("ed", ""), ("d", ""), ("ing", "")):
        if not word.endswith(suffix) or len(word) <= len(suffix) + 2:
            continue
        stems = [word[:-len(suffix)] + replacement]
        stems.append(stems[0][:-1] if len(stems[0]) > 3 and stems[0][-1] == stems[0][-2]
                     else stems[0])
        for stem in stems:
            if stem in vocabulary or (suffix in ("ed", "d", "ing") and stem + "e" in vocabulary):
                return True
    return False


_LETTER_EDGES = ".,;:()[]{}!?\"'“”‘’–—-%*#"


def _unknown_letters(token: str) -> int:
    """Letters of one printed token that spell no dictionary word and no known name."""
    letters = sum(1 for char in token if char.isalpha())
    if not letters:
        return 0
    unknown = 0
    for piece in re.split(r"[-&/'’()]", token):
        core = re.sub(r"[^A-Za-z]", "", piece)
        if not core:
            continue
        if re.search(r"[^A-Za-z$*#0-9]", piece.strip(_LETTER_EDGES)):
            unknown += len(core)               # ':' / '@' printed inside a word
        elif core.isupper() or core[0].isupper() or _is_row_number(core) \
                or _known_word(core.lower()):
            continue                           # an acronym, a name, a row number or a word
        else:
            unknown += len(core)
    return unknown


def label_quality(label: str | None) -> str | None:
    """'garbled' when over 30% of a label's letters sit in non-words, else None (10.j)."""
    text = label or ""
    letters = sum(1 for char in text if char.isalpha())
    if letters < 4:
        return None
    unknown = sum(_unknown_letters(token) for token in text.split())
    return "garbled" if unknown > 0.30 * letters else None


def _garbled_label(label: str | None) -> bool:
    """A row label that is a fragment, punctuation or a printed figure: no stored row (10.j)."""
    text = (label or "").strip()
    if len(_letters(text)) < 3:
        return True
    if _LONG_PUNCT.search(text):
        return True
    return bool(_VALUE_RUN.search(_DATE_DMY.sub(" ", text)))


def header_unresolved(header: str | None, filing_date: Any = None,
                      doc_type: str | None = None,
                      balance_sheet: bool | None = None,
                      page_span: str | None = None) -> bool:
    """A stored cell needs a header that names its period, or a flagged difference column."""
    if not header:
        return True
    if is_delta(header):
        return False
    return period_from_header(header, filing_date, doc_type, balance_sheet,
                              page_span) is None


def _date_anchors(stack: list[list[dict[str, Any]]]) -> list[float]:
    """Right edges of a full printed date row: one phrase per column, so they are the columns."""
    for row in reversed(stack):
        phrases = _phrases([token for token in row if token["text"].strip()])
        if (2 <= len(phrases) <= 8
                and all(_date_phrase(phrase["text"]) for phrase in phrases)):
            return sorted(phrase["x1"] for phrase in phrases)
    return []


def _cells_of_block(rows: list[list[dict[str, Any]]], indices: list[int], table_no: int,
                    header_rows: list[list[dict[str, Any]]], page_unit: tuple[str, float] | None,
                    basis: str | None, filing_date: Any, page_no: int,
                    fallback_headers: list[str | None] | None = None,
                    doc_type: str | None = None,
                    page_balance_sheet: bool | None = None,
                    page_span: str | None = None,
                    cash_flow: bool = False
                    ) -> tuple[list[dict[str, Any]], list[str | None] | None]:
    block = [rows[i] for i in indices]
    anchors = _anchors_of(block)
    if not anchors:
        return [], None
    label_x = [token["x0"] for row in block for token in row
               if not token["num"] and len(token["text"]) > 2]
    label_right = [token["x1"] for row in block for token in row
                   if not token["num"] and len(token["text"]) > 2
                   and token["x1"] <= anchors[-1]]
    if len(anchors) > 1 and label_right and anchors[0] < statistics.median(label_right):
        anchors = anchors[1:]                     # the printed row-number column
    gap = min((b - a for a, b in zip(anchors, anchors[1:])), default=60.0)
    left = anchors[0] - max(gap, 40.0)
    right = anchors[-1] + max(1.5 * gap, 40.0)     # a heading may pass the last anchor
    stack = _header_stack(header_rows, anchors, left, right)
    dates = _date_anchors(stack)
    if len(dates) > len(anchors):
        # A short first block under-samples the printed columns (two of five anchors): the
        # date row prints one phrase per column, so it defines the columns and every row is
        # aligned to them by x-position (contract 10.a, round-4 class 1).
        anchors = dates
        gap = min((b - a for a, b in zip(anchors, anchors[1:])), default=60.0)
        left = anchors[0] - max(gap, 40.0)
        right = anchors[-1] + max(1.5 * gap, 40.0)
    headers = _headers(stack, anchors, left)
    if fallback_headers and not any(headers):
        headers = fallback_headers                 # a statement continued from another page
    title = _table_title(header_rows, stack)
    if not title:
        # A one-cell section name printed between the header row and the first figures
        # ('1. Segment Revenue') is the parent of the rows below it, never their measure
        # (round-9 step 2: measure comes from header rows over the columns only).
        for row in reversed(header_rows[-3:]):
            name = _measure_title(row)
            if name and row[-1]["x1"] <= anchors[0] + 6.0:
                title = name
                break
            if _header_like(row) or _unit_only(" ".join(
                    token["text"] for token in row)):
                break
    if not any(_measure_row(kept) for kept in stack):
        # The measure group row can sit above the five-row header window ('Revenue | EBITDA |
        # PAT' over a JV table's period sub-columns); it still names what the column measures
        # (contract 10.i, round-6 class 4).  Only a row printed directly over the period row is
        # a measure row: a legend printed higher up is not.
        period_row_y = next((min(float(token["y0"]) for token in kept) for kept in stack
                             if all(_date_phrase(phrase["text"])
                                    or _direct_label(phrase["text"])
                                    for phrase in _phrases(kept))), None)
        above = [(row, min(float(token["y0"]) for token in row)) for row in header_rows
                 if row and (period_row_y is None
                             or min(float(token["y0"]) for token in row) < period_row_y)]
        if above and period_row_y is not None:
            row, _ = max(above, key=lambda item: item[1])
            words = [token for token in row if token["text"].strip()
                     and left <= token["x0"] and token["x1"] <= right]
            if words and _measure_row(words):
                stack.append(words)              # directly above the period header row
                headers = _headers(stack, anchors, left)
    unit = _table_unit(header_rows, page_unit)
    tolerance = max(8.0, 0.45 * gap)

    def column_of(token: dict[str, Any]) -> int:
        column = min(range(len(anchors)), key=lambda k: abs(anchors[k] - token["x1"]))
        limit = tolerance
        if _PLACEHOLDER.match(token["text"]):
            limit = max(tolerance, gap)     # a placeholder is centred in its cell
        return column if abs(anchors[column] - token["x1"]) <= limit else -1

    def aligned(row: list[dict[str, Any]]) -> int:
        return sum(1 for token in row if token["num"] and token["x1"] > left + 2
                   and column_of(token) >= 0)

    data_rows = [row for row in block if aligned(row) >= 2]
    if len(data_rows) < 2:
        return [], headers                        # scattered call-outs, not a table
    labeled_rows = [row for row in data_rows
                    if any(token["x1"] <= left + 2 and _ALPHA.search(token["text"])
                           for token in row)]
    label_lines = [row for row in block if _numeric_count(row) < 2
                   and any(_ALPHA.search(token["text"]) for token in row)]
    if len(labeled_rows) < 0.5 * len(data_rows) and len(label_lines) < 0.5 * len(data_rows):
        return [], headers                        # scattered call-outs, not a labelled table

    prepared: list[dict[str, Any]] = []
    for row_no, index in enumerate(indices):
        row = rows[index]
        # The label column ends where the row's first figure starts, not at the anchor-derived
        # edge: a long label ('Equity-oriented') runs past the edge but is still a label
        # (round-7 class 8).
        data_edge = min((token["x0"] for token in row
                         if token["num"] and token["x1"] > left + 2), default=left + 2)
        label_tokens = [token for token in row if token["x1"] <= data_edge]
        beside = [token for token in row if not token["num"] and token["x1"] > data_edge]
        data = [token for token in row if token["num"] and token["x1"] > left + 2]
        first = next((token for token in row if token["text"].strip()), None)
        at_label = first is not None and first["x1"] <= data_edge
        numbered = bool(at_label and first is not None and _is_row_number(first["text"]))
        marked = bool(at_label and first is not None and MARKER.match(first["text"]))
        if numbered and first is not None:
            label_tokens = [token for token in label_tokens if token is not first]
        # The row's own unit cell ('Rs Mn', '₹ Cr', 'US$ Bn') is printed beside its label and
        # is not part of the name: 'EBIT | Rs Mn | 680,996' is EBIT in Rs million (10.d).
        phrases = _phrases(label_tokens)
        unit_phrases: list[dict[str, Any]] = []
        while len(phrases) > 1 and _unit_cell_text(phrases[-1]["text"]):
            unit_phrases.insert(0, phrases.pop())
        if len(phrases) == 1 and data and _unit_cell_text(phrases[0]["text"]):
            unit_phrases.insert(0, phrases.pop())    # the unit cell is the whole left column
        unit_phrases.extend(phrase for phrase in _phrases(beside)
                            if _unit_cell_text(phrase["text"]))
        label = " ".join(phrase["text"] for phrase in phrases).strip()
        unit_cell = " ".join(phrase["text"] for phrase in unit_phrases).strip()
        prepared.append({
            "row_no": row_no, "data": data, "label": label, "numbered": numbered,
            "marked": marked, "is_data": aligned(row) >= 2, "unit_cell": unit_cell,
            # A comment / remarks column printed to the right of the last figure is never a
            # label or a section for the rows below (round-9 step 5, Coal India's ratios).
            "outer": bool(phrases) and phrases[0]["x0"] > anchors[-1] + max(0.15 * gap, 6.0),
            "x0": phrases[0]["x0"] if phrases else 0.0,
            "top": min((float(token["y0"]) for token in row), default=0.0),
            "baseline": max((float(token["y1"]) for token in row), default=0.0),
            "y": sum((token["y0"] + token["y1"]) / 2 for token in row) / max(len(row), 1)})

    data_items = [item for item in prepared if item["is_data"]]
    if data_items and not data_items[0]["label"] and header_rows:
        # The row's own label printed just above the first figure line is the table's first
        # row, not a header: the Coal India ratios' 'Debt Equity Ratio' (round-8 class 0).
        last = header_rows[-1]
        text = " ".join(token["text"] for token in last
                        if token["text"].strip() and token["x1"] <= left + 2)
        text = _SECTION_NUMBER.sub("", text).strip()
        if text and not _prose_label(text) and _letters(text) \
                and not _header_like(last):
            data_items[0]["label"] = text
    if len(data_items) >= 2 and sum(1 for item in data_items if not item["label"]) \
            > sum(1 for item in data_items if item["label"]):
        # A two-flow table prints its labels and its figures on separate lines, each label
        # line above the figures printed under its baseline (the Coal India deck): 'Finance
        # Costs' keeps its -290 and Depreciation its -670 (contract 10.a, round-6 class 7).
        groups: dict[int, list[str]] = {}
        for item in prepared:
            if item["is_data"] or not item["label"]:
                continue
            target = next((row for row in data_items
                           if abs(row["baseline"] - item["baseline"]) <= 2.0
                           or 0.0 <= row["top"] - item["top"] <= 6.0), None)
            if target is None:
                target = next((row for row in data_items
                               if row["top"] >= item["baseline"] - 2.0), data_items[-1])
            groups.setdefault(id(target), []).append(item["label"])
            item["label"] = ""
        for item in data_items:
            parts = groups.get(id(item))
            if parts:
                item["label"] = " ".join(parts)

    balance_sheet = page_balance_sheet
    period_overrides: dict[int, str] = {}
    if cash_flow:
        headers, period_overrides = _cash_headers(
            prepared, headers, anchors, tolerance, filing_date, doc_type, balance_sheet,
            page_span)

    cells: list[dict[str, Any]] = []
    section = title or ""
    section_x: float | None = None
    pending: list[str] = []
    last_cells: list[dict[str, Any]] = []
    line_label: str | None = None
    for position, item in enumerate(prepared):
        if not item["is_data"]:
            label = item["label"]
            if not label or _prose_label(label) or item["outer"]:
                continue
            if not _letters(label) or (len(_letters(label)) < 3 and not SUB_LABEL.match(label)
                                       and not item["marked"] and not item["numbered"]):
                continue                           # '-------' / 'St': a separator, not a section
            # The measure is read from the header rows above the period columns, never from a
            # row label: 'INCOME' / 'Revenue from operations' / 'Segment Results' printed in
            # the label column is the row's section, not a column's measure (round-9 step 2).
            previous = next((j for j in range(position - 1, -1, -1)
                             if prepared[j]["is_data"]), None)
            following = next((j for j in range(position + 1, len(prepared))
                              if prepared[j]["is_data"]), None)
            # The line above continues into this one: 'Cash profit from operations before
            # Derivative &' + 'Exchange Fluctuations' is one label, never a heading over the
            # next row (contract 10.a, round-6 class 3).
            if pending and _label_continues(pending[-1], label):
                pending.append(label)
                continue
            if (last_cells and previous is not None and previous == position - 1
                    and line_label and _label_continues(line_label, label)):
                _append_label(last_cells, label)   # the tail printed under its own row
                continue
            near = prepared[following] if following is not None else None
            if near is not None and near["label"] and _label_continues(label, near["label"]):
                # The label's first half printed one line above its figures: 'Previously
                # reported Employee' + 'Benefits Expense' is one two-line label (round 9).
                near["label"] = f"{label} {near['label']}"
                continue
            if near is not None and (not near["label"] or _wrap_fragment(near["label"])
                                     or ((near["marked"] or near["numbered"])
                                         and near["x0"] <= item["x0"] + 2)):
                pending.append(label)              # a wrapped label line above its numbers
                continue
            next_closer = following is not None and (
                previous is None
                or prepared[following]["y"] - item["y"] <= item["y"] - prepared[previous]["y"])
            if next_closer:
                section = label                    # a heading over the group of rows below
                section_x = item["x0"]
                line_label = None
            elif last_cells and _wrap_fragment(label):
                _append_label(last_cells, label)   # the label's last line, printed below it
            elif item["marked"] or item["numbered"]:
                pending.append(label)              # a body row whose numbers sit below it
            elif _wrap_fragment(label):
                continue                           # an orphan continuation line: no row label
            else:
                section = label
                section_x = item["x0"]
                line_label = None
            continue
        if item["numbered"] or item["marked"]:
            if section_x is None or item["x0"] <= section_x + 2:
                section = ""                       # a new row group at the same indent
                section_x = None
        parts = pending + ([item["label"]] if item["label"] else [])
        pending = []
        own_label = " ".join(parts)
        own_label = re.sub(r"^\(?[a-z]\)\s+(?=[\[(])", "", own_label).strip()  # '(e) [x]'
        split = _split_ratio_label(own_label)
        if split:
            own_label = split              # two printed rows merged into one label (round-8)
        bare_ratio = bool(own_label) and bool(_BARE_RATIO.match(own_label))
        if bare_ratio and line_label:
            # 'as a % of NR' printed under a line item belongs to that item (round-5 class 3).
            parent = _ROW_PREFIX.sub("", line_label).strip()
            row_label = " > ".join(part for part in (section, parent, own_label) if part) or None
        else:
            row_label = " > ".join(part for part in (section, own_label) if part) or None
        if own_label and not bare_ratio:
            line_label = own_label
        if not row_label or _garbled_label(row_label):
            last_cells = []                       # no readable label: not a stored cell
            continue
        quality = label_quality(row_label)
        # Scale, in the printed order that names it: the row's own unit cell, the label's
        # own scale word, the table note or section title, then the page unit.  A per-unit
        # row keeps scale 1; with no scale printed anywhere the scale is NULL, never 1
        # (contract 10.d, round-6 class 1).
        row_unit = _row_unit(item["unit_cell"], own_label) if item["unit_cell"] else None
        # The row's own unit cell is the printed unit and beats the label's word: a bare
        # 'US$' cell beside 'Average Revenue Per User (ARPU)' is USD, not the page's Rs
        # (round-7 class 1).  A bare currency with no per-unit label keeps scale NULL.
        cell_unit = (row_unit or label_unit(own_label) or _unit_of(own_label)
                     or _label_currency(row_label) or _unit_of(row_label) or unit)
        flow_row = bool(_FLOW_ROW.search(own_label or row_label))
        point_row = bool(not flow_row and (
            _POINT_ROW.search(row_label)
            or _STOCK_ROW.search(own_label or row_label)))
        emitted: list[dict[str, Any]] = []
        for token in item["data"]:
            column = column_of(token)
            header = headers[column] if 0 <= column < len(headers) else None
            if not header:
                continue                          # no usable column header: not a stored cell
            period = period_overrides.get(column)
            if period is None:
                if header_unresolved(header, filing_date, doc_type, balance_sheet, page_span):
                    continue                      # no usable column header: not a stored cell
                period = (_point_period(header, filing_date, doc_type, balance_sheet, page_span)
                          if point_row else None) or period_from_header(
                    header, filing_date, doc_type, balance_sheet, page_span)
            value, percent = _number(token["text"])
            if percent:
                unit_text, scale, value = "%", 1.0, value
            elif re.search(r"\b(?:bps|bp|pp)\b", token["text"], re.I):
                unit_text, scale = ("pp" if re.search(r"\bpp\b", token["text"], re.I)
                                    else "bps"), 1.0
            elif re.search(r"\bbps\b", header, re.I):
                unit_text, scale = "bps", 1.0     # a bps column is basis points, not money
            else:
                fallback = cell_unit or _header_unit(header)
                if fallback is not None:
                    unit_text, scale = fallback
                    value = None if value is None or scale is None else round(value * scale, 2)
                else:
                    unit_text, scale, value = None, None, None
            delta = is_delta(header)
            method = ";".join(["text_layer"] + (["delta"] if delta else [])
                              + ([quality] if quality else []))
            emitted.append({
                "page": page_no, "table_no": table_no, "row_no": item["row_no"],
                "col_no": column, "row_label": row_label,
                "col_header": header,
                "period_id": None if delta else period,
                "basis": basis, "value_text": token["text"], "value": value,
                "unit_text": unit_text, "scale": scale,
                "bbox": f"{token['x0']:.1f},{token['y0']:.1f},{token['x1']:.1f},{token['y1']:.1f}",
                "method": method})
        cells.extend(emitted)
        last_cells = emitted
    _flag_junk_cells(cells)
    return cells, headers


def _flag_junk_cells(cells: list[dict[str, Any]]) -> None:
    """A decimal-free figure ~20x BOTH its column neighbours lost its decimal point.

    Havells' OCR prints 300.78 as '30078' beside 723.06 and 517.83 in its own row, and 310.00
    above it in the same column; no real figure in a financial table is a hundredfold jump
    across one row (round-8 class 5).
    """
    by_column: dict[int, list[dict[str, Any]]] = {}
    for cell in cells:
        if cell["value"] is None:
            continue
        unit = cell["unit_text"] or ""
        if unit in ("%", "bps", "pp", "ratio", "count", "inr_per_share"):
            continue
        by_column.setdefault(int(cell["col_no"]), []).append(cell)
    for column_cells in by_column.values():
        column_cells.sort(key=lambda cell: int(cell["row_no"]))
        for index, cell in enumerate(column_cells):
            text = cell["value_text"] or ""
            if "." in text or "%" in text or len(re.sub(r"\D", "", text)) < 5:
                continue
            above = column_cells[index - 1]["value"] if index else None
            below = (column_cells[index + 1]["value"]
                     if index + 1 < len(column_cells) else None)
            references = [abs(value) for value in (above, below) if value]
            if len(references) == 2 and abs(cell["value"]) >= 1000.0 and all(
                    abs(cell["value"]) / reference >= 50.0 for reference in references):
                cell["value"] = None
                cell["method"] = f"{cell['method']};junk_suspect"


def _page_balance_sheet(page: Any) -> bool | None:
    """A page titled Balance Sheet prints as-at columns; a P&L prints quarters."""
    clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.30)
    text = " ".join(str(page.get_text("text", clip=clip)).split())
    # A segment page titled '... Assets and Liabilities as of and for the quarter ended' has a
    # flow column set; it is not a balance sheet (round-8 class 1, Bharti's segment tables).
    if re.search(r"\b(?:quarter|half[\s-]?year|nine\s+months?|twelve\s+months?|year|month[s]?)"
                 r"\s+ended\b", text, re.I):
        return False
    if _BS_TITLE.search(text):
        return True
    if _PL_TITLE.search(text):
        return False
    return None


_HALF_TITLE = re.compile(r"\bhalf[\s-]?year\b|\bsix\s+months?\b|\bh1\b", re.I)
_NINE_TITLE = re.compile(r"\bnine\s+months?\b|\b9\s*m\b", re.I)
_QUARTER_TITLE = re.compile(r"\bquarter\b", re.I)
_FY_TITLE = re.compile(r"\b(?:year|twelve\s+months|annual)\b", re.I)
_RATIO_TITLE = re.compile(r"\bratios?\b", re.I)


def _page_span(page: Any) -> str | None:
    """The statement period the page title names: a cash-flow page 'for the half year ended'.

    A page that names both a quarter and a year ('quarter and year ended') names neither.
    """
    clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.20)
    text = " ".join(str(page.get_text("text", clip=clip)).split())
    if _RATIO_TITLE.search(text):
        return "RATIO"          # a Key Financial Ratios page: bare dates are period ends
    quarter = bool(_QUARTER_TITLE.search(text))
    if _HALF_TITLE.search(text) and not quarter:
        return "H1"
    if _NINE_TITLE.search(text) and not quarter:
        return "9M"
    year = bool(_FY_TITLE.search(text))
    if quarter and not year:
        return "Q"
    if year and not quarter:
        return "FY"
    return None


def _same_columns(current: list[int], index: int,
                  rows: list[list[dict[str, Any]]]) -> bool:
    """The next figure row prints in the columns the block already has (round-7 class 5).

    Two tables stacked on one slide print their figures at different anchors; a table's own
    rows, however many label lines separate them, share the anchors.
    """
    anchors = _anchors_of([rows[j] for j in current])
    numbers = [token for token in rows[index] if token["num"]]
    if not anchors or len(numbers) < 2:
        return True
    return sum(1 for token in numbers
               if min(abs(anchor - token["x1"]) for anchor in anchors) <= 6.0) >= 2


def _next_row_same_columns(current: list[int], index: int,
                           rows: list[list[dict[str, Any]]]) -> bool:
    """The next full figure row after ``index`` keeps the block's columns."""
    for j in range(index + 1, min(len(rows), index + 6)):
        if _numeric_count(rows[j]) >= 2:
            return _same_columns(current, j, rows)
    return False


_FOOTER = re.compile(r"^\s*Page\s+\d+\s+(?:of|/)\s*\d+\s*$", re.I)


def _page_cells(page: Any, pno: int, filing_date: Any,
                carry: list[str | None] | None,
                doc_type: str | None = None) -> tuple[list[dict[str, Any]],
                                                      list[str | None] | None]:
    """One page's cells plus the last column headers seen, for a continued statement."""
    height = float(page.rect.height)
    basis = _basis(page)
    top_text = _top_text(page, height)
    page_unit = _unit_of(top_text)
    page_balance_sheet = _page_balance_sheet(page)
    page_span = _page_span(page)
    cash_flow = bool(_CASH_TITLE.search(str(page.get_text(
        "text", clip=pymupdf.Rect(0, 0, page.rect.width, height * 0.25)))))
    rows = [_tokens(row) for row in _rows_of(page.get_text("words"))]
    # A remarks / commentary column printed to the right of every figure is not part of the
    # table: its lines must not break the block or become section names (round-9 step 5).
    # Only rows with two or more figures define the table's right edge (not a page number).
    numeric_right = max((token["x1"] for row in rows if _numeric_count(row) >= 2
                         for token in row if token["num"]), default=0.0)
    if numeric_right:
        rows = [row for row in rows
                if any(token["num"] for token in row) or not row
                or min(float(token["x0"]) for token in row) <= numeric_right]

    blocks: list[list[int]] = []
    current: list[int] = []
    gap = 0
    gap_rows: list[list[dict[str, Any]]] = []
    last_number_y: float | None = None
    for i, row in enumerate(rows):
        numbers = _numeric_count(row)
        if numbers and _FOOTER.match(" ".join(token["text"] for token in row)):
            numbers = 0                        # 'Page 14 of 59' is a footer, not a table row
        if numbers and any(token["text"].strip().lower() == "page" for token in row):
            numbers = 0                        # 'Page' | '13' | 'of 59' split by the text layer
        if numbers >= 2 and i and _month_row(rows[i - 1]) and _date_parts(row):
            for token in row:                     # the day/year half of a wrapped date row
                token["num"] = False
            numbers = 0
        top = min((float(token["y0"]) for token in row), default=0.0)
        if numbers >= 2:
            if (current and last_number_y is not None and gap >= 2
                    and top - last_number_y > 45.0
                    and any(_header_like(words) for words in gap_rows if words)):
                # A second table printed below the first (Adani's financial table over its
                # operational table) brings its own header row; one merged block would mix
                # both tables' column anchors (round-7 class 5).  Two prose label lines
                # between a table's own figure rows are not a new table.
                if sum(1 for j in current if _numeric_count(rows[j]) >= 2) >= 2:
                    blocks.append(current)
                current, gap = [], 0
            current.append(i)
            gap = 0
            gap_rows = []
            last_number_y = top
        elif current and gap < 2 and numbers == 0:
            current.append(i)
            gap += 1
            gap_rows.append(row)
        else:
            if sum(1 for j in current if _numeric_count(rows[j]) >= 2) >= 2:
                blocks.append(current)
            current, gap, gap_rows = ([i] if numbers >= 2 else []), 0, []
            last_number_y = top if numbers >= 2 else None
    if sum(1 for j in current if _numeric_count(rows[j]) >= 2) >= 2:
        blocks.append(current)

    cells: list[dict[str, Any]] = []
    previous_end = -1
    for table_no, indices in enumerate(blocks):
        while indices and _numeric_count(rows[indices[-1]]) < 2:
            indices = indices[:-1]
        if not indices:
            previous_end = blocks[table_no][-1]
            continue
        found, headers = _cells_of_block(
            rows, indices, table_no, rows[previous_end + 1:indices[0]],
            page_unit, basis, filing_date, pno, carry, doc_type, page_balance_sheet,
            page_span, cash_flow)
        if found:
            if headers and any(headers):
                carry = headers
            cells.extend(found)
            previous_end = indices[-1]
        # A block that produced no cell (a title's date, a header row's '3 months') is not a
        # table: its rows stay in the header context of the block below it, so the header
        # row it swallowed still names the real table (round-7 class 5).
    return cells, carry


def extract_page(page: Any, pno: int, filing_date: Any = None,
                 doc_type: str | None = None) -> list[dict[str, Any]]:
    """Every table cell printed on one page, as ``table_cell`` column dicts (minus ids)."""
    return _page_cells(page, pno, filing_date, None, doc_type)[0]


def extract(pdf_path: str, filing_date: Any = None, stats: dict[str, int] | None = None,
            doc_type: str | None = None) -> list[dict[str, Any]]:
    """Every table cell of a PDF; ``stats`` (optional) collects pages, no-text and no-table pages."""
    if stats is None:
        stats = {}
    for key in ("pages", "pages_no_text", "pages_no_table"):
        stats.setdefault(key, 0)
    cells: list[dict[str, Any]] = []
    carry: list[str | None] | None = None
    with pymupdf.open(pdf_path) as document:
        stats["pages"] += len(document)
        for number in range(len(document)):
            page = document[number]
            if not str(page.get_text("text")).strip():
                stats["pages_no_text"] += 1
                continue
            found, carry = _page_cells(page, number + 1, filing_date, carry, doc_type)
            if not found:
                stats["pages_no_table"] += 1
            cells.extend(found)
    return cells
