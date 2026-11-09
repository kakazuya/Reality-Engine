"""T-132: every printed table cell of a PDF page from word boxes (text layer only), no model.

Rules (docs/V2_SCHEMA_CONTRACT.md section 10):

a. The header stack is built upward from the table: a row is kept only when its words lie inside the table's
   x-range (words outside are trimmed, a word crossing an edge drops the row) and it is not prose (one run of
   eight or more words with no digit, or a line ending in ``.``); a row with a non-date figure (a slide call-out:
   ``Rs 353 crores``) or without a date, period, unit or audit status is skipped, three consecutive skips stop the
   stack and the stack holds at most five rows.  A statement continued on the next page (or a second table with no
   header of its own) reuses the last header set.  A header row that prints one phrase per column is assigned in
   column order; otherwise a phrase owns a column only inside its x-span (a monotone skip match, never a later
   column across an unmatched phrase).  ``col_header`` joins the rows top to bottom with ``' > '``.
b. A section label ("Expenses") ends where a new numbered row group starts (first token is a row
   number: ``2``, ``II``, ``IV``, ``(2)``).  Parenthesised sub-labels (``(a)``) stay inside the section.
   The printed row-number column is dropped from ``row_label`` and from the cells.  A label line
   printed under a row, or above the row whose numbers sit on its own line, belongs to that row: it is
   joined into its ``row_label`` rather than becoming the next row's section.
c. Figures split by the text layer ("2, 028", "1 ,234.5") merge; ``(1,234.5)`` and ``-1,234.5``
   are negative; ``-`` / an en dash is value NULL with ``value_text`` kept; ``12.3%`` is percent.
   A comma-grouped figure must use Western (1,234,567) or Indian (12,34,567) grouping exactly
   (last group three digits, earlier groups two or three consistently); anything else keeps
   ``value_text`` with ``value`` NULL.  A date fragment (``31,2026``, ``30.09.2026``) is not a
   cell at all.
d. The unit is read from the scale word anywhere in the header rows and the lines above the
   table ("f Lakhs" from a split "₹ in Lakhs", "Rs. in Crores", "INR Mn"), else the page's top
   15%, else the row label ("EBIT ( ₹ crores)").  crore 1e7, lakh 1e5, million/mn 1e6,
   billion/bn 1e9, thousand 1e3.  Percent stays in percent points (``unit_text='%'``,
   ``scale=1``).  A row that names its own unit keeps scale 1 and that unit: a per-share row is
   ``inr_per_share`` (share capital and face value rows are money), a count/number-of row is
   ``count``, a ratio/times/days row is ``ratio``, and an ``in Rs`` / ``₹ per tonne`` row is ``Rs``.
   No unit found means ``scale`` and ``value`` are NULL: never guess a scale.
e. ``period_id`` comes from the column header and the document date through
   :func:`reality_engine.v2.periods.period_row`.  Wrapped header lines are assembled before the
   date is parsed ("March 31," over "2026"); ``Q1 25-26``, ``FY25-26``, ``9M FY27``, ``H1 26-27``,
   ``Dec-24`` / ``Mar'24``, ``9M 25-26`` and ``YTD FY26`` (with the filing date) resolve.  A bare
   date header is the quarter ending that day in a results P&L and a POINT on a balance-sheet page
   or a deck; a bare ``9M`` / ``FY`` / ``Quarter ended`` takes the printed FY range or the latest
   period ending before the filing date.  A header date that does not parse to a real date within
   three years of the filing date is dropped, never guessed.  A cell whose header names no
   resolvable period (and is not a difference column) is not stored.
f. ``basis`` is standalone/consolidated from the page title (top 20%), else NULL.
g. An infographic page yields no cells: a table block needs at least two rows, each with at least
   two numbers aligned to the column anchors, and a label longer than 80 characters or carrying
   a sentence break (``'. '`` before a capital) drops its row.  A cell with no row label or no
   usable column header is not stored.
h. ``bbox`` is the merged token's box and ``method`` is ``'text_layer'``, or
   ``'text_layer;delta'`` for a difference / growth / bps column, which is stored with
   ``period_id`` NULL and never read as a period's value.
"""
from __future__ import annotations

import calendar
import re
import statistics
from datetime import date, timedelta
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
ROWNUM = re.compile(r"^(?:\d{1,2}\.?|[IVXLC]{1,4}\.?)$")
# A body-row marker: '1.', 'II.', '(iv)', '(2)'.  A lettered sub-label ('(a)', 'a)') is
# not a marker: it stays inside its section (contract 10.b).
MARKER = re.compile(r"^\((?:\d{1,2}|[IVXLC]{1,4})\)$|^(?:\d{1,2}|[IVXLC]{1,4})\.$")
SUB_LABEL = re.compile(r"^\(?[a-z]\)$", re.I)
DELTA_WORD = re.compile(
    r"\b(?:inc\s*/?\s*dec|increase\s*/\s*decrease|change|variation|var|yoy|y-o-y|qoq|q-o-q|"
    r"growth|delta|bps)\b", re.I)
GROWTH = re.compile(
    r"\b(?:yoy|y-o-y|qoq|q-o-q|growth|change|var(?:iation)?|inc\s*/?\s*dec|"
    r"increase\s*/\s*decrease|delta|bps)\b|%", re.I)
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
    (re.compile(r"\bas\s*(?:at|on|of)\b", re.I), "POINT"),
    (re.compile(r"\bnine\s+months?\b|\b9\s*m(?:onths?)?\b", re.I), "9M"),
    (re.compile(r"\bsix\s+months?\b|\bhalf[\s-]?year\b|\bh1\b", re.I), "H1"),
    (re.compile(r"\bquarter\b|\bq[1-4]\b", re.I), "Q"),
    (re.compile(r"\byear[\s-]?ended\b|\bfor\s+the\s+year\b|\bfy\b", re.I), "FY"),
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
_OWN_UNIT = re.compile(r"(?:rs\.?|₹|inr)\s*(?:/|per)\b|\bin\s+(?:rs\.?|₹|inr)\b", re.I)
_USD_UNIT = re.compile(r"\b(?:us\s*\$|usd|a\s*\$|aud)\b", re.I)
_COUNT_ROW = re.compile(
    r"\bno\.?\s+of\b|\bnos\.?\b|\(\s*nos\.?\s*\)|\bnumber\s+of\b|\b000'?s\b|\bqty\b|"
    r"\bquantity\b|\bemployees\b|\bstores\b|\bkeys\b|\btonnes?\b|\(\s*te\s*\)|"
    r"\(in\s+mill\.?\s*te\)|\bmmt\b|\bmw\b|\bshares\s+outstanding\b|\bshare\s+count\b|"
    r"\bcustomers\b|\boutlets\b|\brooms\b|\btowers?\b|\bteus?\b", re.I)


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
    return rows


def _joinable(previous: dict[str, Any], word: Any, text: str) -> bool:
    gap = word[0] - previous["x1"]
    if gap > _MERGE_GAP:
        return False
    left = previous["text"]
    if gap <= 3.0 and _DATE_FULL.match(left + text):
        return True                         # the layer split a date: '3' + '1.03.2026'
    if gap <= 2.5 and left[-1].isdigit() and text[0].isdigit():
        return bool(re.fullmatch(r"\d{1,7}", left + text))   # a lost thousands separator
    if left[-1] in ",.-–—−(₹" or text[0] in ",.)%":
        return bool(NUMISH.match(left + text))
    return False


def _tokens(row: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for word in row:
        text = str(word[4]).strip()
        if not text:
            continue
        if out and _joinable(out[-1], word, text):
            out[-1]["text"] += text
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
    if len(numbers) == 1 and ROWNUM.match(numbers[0]["text"]):
        first = next((token for token in row if token["text"].strip()), None)
        if first is numbers[0]:
            return 0
    return len(numbers)


def _anchors_of(block: list[list[dict[str, Any]]]) -> list[float]:
    xs = sorted(token["x1"] for row in block for token in row if token["num"])
    clusters: list[list[float]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= _ANCHOR_TOL:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    need = max(2, 0.3 * len(block))
    return [sum(cluster) / len(cluster) for cluster in clusters if len(cluster) >= need]


def _phrases(row: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phrases: list[dict[str, Any]] = []
    for token in sorted(row, key=lambda t: t["x0"]):
        if phrases and token["x0"] - phrases[-1]["x1"] <= _PHRASE_GAP:
            phrases[-1]["x1"] = max(phrases[-1]["x1"], token["x1"])
            phrases[-1]["text"] += " " + token["text"]
        else:
            phrases.append({"x0": token["x0"], "x1": token["x1"], "text": token["text"]})
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
    """Day/year numbers of a wrapped date row ('31 2025 30 2025 ...')."""
    numbers = [token["text"] for token in row if token["num"]]
    return bool(numbers) and all(
        re.fullmatch(r"\d{1,2}|\d{4}|\d{1,2},\d{4}", text) for text in numbers)


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
    return centers, gap


def _period_blocks(phrases: list[dict[str, Any]],
                   centers: list[float]) -> list[tuple[int, int]] | None:
    """Partition columns into consecutive blocks, one per phrase, centred on the phrase."""
    count, width = len(phrases), len(centers)
    if count > width:
        return None
    infinity = float("inf")
    best = [[infinity] * (width + 1) for _ in range(count + 1)]
    back = [[0] * (width + 1) for _ in range(count + 1)]
    best[0][0] = 0.0
    for i in range(1, count + 1):
        centre = (phrases[i - 1]["x0"] + phrases[i - 1]["x1"]) / 2
        for end in range(i, width - (count - i) + 1):
            for start in range(i - 1, end):
                if best[i - 1][start] == infinity:
                    continue
                mean = sum(centers[start:end]) / (end - start)
                cost = best[i - 1][start] + (mean - centre) ** 2
                if cost < best[i][end]:
                    best[i][end] = cost
                    back[i][end] = start
    if best[count][width] == infinity:
        return None
    blocks: list[tuple[int, int]] = []
    end = width
    for i in range(count, 0, -1):
        start = back[i][end]
        blocks.append((start, end))
        end = start
    return list(reversed(blocks))


def _unit_only(text: str) -> bool:
    """A scale line ("(₹ in crores)", "f Lakhs") names the unit, not a column."""
    return bool(_SCALE_WORD.search(text)) and not any(ch.isdigit() for ch in text) \
        and not _kind_like(text)


def _span_heading(phrase: dict[str, Any], gap: float) -> bool:
    """A group heading ('Quarter ended', 'As at') printed over its columns, not a date."""
    return (_kind_like(phrase["text"]) and not _date_phrase(phrase["text"])
            and phrase["x1"] - phrase["x0"] <= 4.0 * gap)


_PERIOD_WORD = re.compile(r"^(?:Q[1-4]|H[12]|9\s*M|FY)$", re.I)
_YEAR_RANGE = re.compile(r"^\d{2,4}\s*[-–/]\s*\d{2,4}$")


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


def _headers(header_rows: list[list[dict[str, Any]]], anchors: list[float],
             left: float) -> list[str | None]:
    centers, gap = _refined_centers(header_rows, anchors, left)
    tolerance = 0.9 * gap
    columns: list[list[str]] = [[] for _ in anchors]
    spans: list[dict[str, Any]] = []
    for row in header_rows:
        phrases = _phrases([t for t in row if t["x1"] >= left])
        phrases = [phrase for phrase in phrases
                   if not _unit_only(phrase["text"]) and not _garbled_date(phrase["text"])]
        phrases = _join_period_phrases(phrases)
        if not phrases:
            continue
        widths = [phrase["x1"] - phrase["x0"] for phrase in phrases]
        headings = [phrase for phrase in phrases if _span_heading(phrase, gap)]
        if len(headings) == len(phrases):
            spans.extend(phrases)                     # a group-heading row, assigned below
            continue
        if len(phrases) == 1:
            phrase = phrases[0]
            centre = (phrase["x0"] + phrase["x1"]) / 2
            k = min(range(len(centers)), key=lambda j: abs(centers[j] - centre))
            if abs(centers[k] - centre) <= tolerance:
                columns[k].append(phrase["text"])
            continue
        all_dates = all(_date_phrase(phrase["text"]) for phrase in phrases)
        all_kinds = all(_kind_like(phrase["text"]) for phrase in phrases)
        if len(phrases) == len(centers):
            for k, phrase in enumerate(phrases):      # one printed cell per column, in order
                columns[k].append(phrase["text"])
            continue
        if ((all_dates and len(phrases) >= len(centers) - 1) or all_kinds) \
                and len(phrases) <= len(centers) and max(widths) <= 4.0 * gap:
            blocks = _period_blocks(phrases, centers)
            if blocks:
                for (start, end), phrase in zip(blocks, phrases):
                    centre = (phrase["x0"] + phrase["x1"]) / 2
                    mean = sum(centers[start:end]) / (end - start)
                    if abs(mean - centre) > tolerance:
                        continue                          # the phrase covers no whole column
                    for k in range(start, end):
                        columns[k].append(phrase["text"])
                continue
        phrase_centers = [(p["x0"] + p["x1"]) / 2 for p in phrases]
        diffs = sorted(b - a for a, b in zip(centers, centers[1:])) or [40.0]
        wide = max(tolerance, 0.45 * diffs[len(diffs) // 2])
        # A monotone skip match: phrases and columns are both left to right, so a header
        # cell may own a column or none, never a later column across an unmatched phrase.
        i = j = 0
        while i < len(phrases) and j < len(centers):
            gap_to_column = phrase_centers[i] - centers[j]
            if abs(gap_to_column) <= wide:
                columns[j].append(phrases[i]["text"])
                i += 1
                j += 1
            elif gap_to_column < 0:
                i += 1
            else:
                j += 1
    if spans:
        # A column belongs to the printed group heading nearest its centre: two headings
        # over one table ('Quarter ended' / 'Nine months ended') must not both name it.
        for k, centre in enumerate(centers):
            nearest = min(spans, key=lambda phrase: abs(
                (phrase["x0"] + phrase["x1"]) / 2 - centre))
            columns[k].insert(0, nearest["text"])
    return [" > ".join(parts) if parts else None for parts in columns]


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


def _unit_of(text: str) -> tuple[str, float] | None:
    matches = list(_SCALE_WORD.finditer(text))
    if not matches:
        return None
    scale, word = _SCALES[matches[-1].group(1).lower()]
    currency = "INR" if re.search(r"\binr\b", text, re.I) else "Rs"
    return f"{currency} {word}", scale


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
               balance_sheet: bool | None = None) -> str | None:
    kind = None
    for segment in reversed([s.strip() for s in text.split(" > ") if s.strip()]):
        kind = _kind_in(segment)
        if kind:
            break
    joined = " ".join(segment.strip() for segment in text.split(" > ") if segment.strip())
    day = _last_date(joined, filing_date)          # assemble a wrapped date row first
    if day is None:
        day = _last_date(text, filing_date)
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
                       balance_sheet: bool | None = None) -> str | None:
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
    resolved = _direct_label(last)
    if resolved:
        return resolved
    resolved = _date_kind(header, filing_date, doc_type, balance_sheet)
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


def label_unit(label: str | None) -> tuple[str, float] | None:
    """A row that names its own unit: no crore/lakh scale, unit from the label (10.d)."""
    if not label:
        return None
    if _PERCENT_ROW.search(label):
        return ("%", 1.0)
    if _PER_SHARE.search(label) and not _CAPITAL.search(label):
        return ("inr_per_share", 1.0)
    if _USD_UNIT.search(label):
        currency = "AUD" if re.search(r"\ba\s*\$|\baud\b", label, re.I) else "USD"
        if re.search(r"\bmn\b|\bmillion\b", label, re.I):
            return (f"{currency} million", 1e6)
        if re.search(r"\bbn\b|\bbillion\b", label, re.I):
            return (f"{currency} billion", 1e9)
        return (currency, 1.0)
    if _OWN_UNIT.search(label):
        return ("Rs", 1.0)
    if _RATIO_ROW.search(label):
        return ("ratio", 1.0)
    if _COUNT_ROW.search(label):
        return ("count", 1.0)
    return None


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


def _header_stack(header_rows: list[list[dict[str, Any]]], anchors: list[float],
                  left: float, right: float | None = None) -> list[list[dict[str, Any]]]:
    """Header rows upward from the table, inside its x-range, stopping at the first prose row."""
    gap = min((b - a for a, b in zip(anchors, anchors[1:])), default=60.0)
    if right is None:
        right = anchors[-1] + max(1.5 * gap, 40.0)  # a span heading may pass the last anchor
    kept: list[list[dict[str, Any]]] = []
    skips = 0
    for row in reversed(header_rows):
        words = [token for token in row if token["text"].strip()]
        if not words:
            continue
        if any((token["x0"] < left < token["x1"])
               or (token["x0"] < right < token["x1"]) for token in words):
            skips += 1
            if kept and skips >= 3:
                break                           # the stack is above the slide's call-outs
            continue                            # a line that runs across the table edge
        inside = [token for token in words
                  if token["x0"] >= left and token["x1"] <= right]
        if not inside:
            continue                            # entirely outside the table
        if _prose_row(inside):
            break
        if not _header_like(inside) \
                or (any(_plain_number(token["text"]) for token in inside)
                    and not _date_parts(inside)):
            skips += 1
            if kept and skips >= 3:
                break                           # the stack is above the slide's call-outs
            continue                            # a heading row, but not this table's
        kept.append(inside)
        skips = 0
        if len(kept) >= 5:
            break
    return list(reversed(kept))


_SENTENCE = re.compile(r"(?<![A-Za-z])[a-z]{3,}\.\s+[A-Z]")   # 'growth. Growth', not 'Cons. D'


def _prose_label(label: str | None) -> bool:
    """A sentence or a paragraph is not a row label."""
    return bool(label) and (len(label) > 80 or bool(_SENTENCE.search(label)))


# --------------------------------------------------------------------------------------- page

def _append_label(cells: list[dict[str, Any]], text: str) -> None:
    """The wrapped label line printed under a row belongs to that row (contract 10.a)."""
    for cell in cells:
        label = cell["row_label"]
        cell["row_label"] = f"{label} {text}" if label else text


def _wrap_fragment(text: str) -> bool:
    """A line printed under a row to finish its label: '(no. of months of Gross Sales)'."""
    first = text.split(" ", 1)[0]
    if MARKER.match(first) or SUB_LABEL.match(first):
        return False
    if text.startswith("(") or (text[:1].islower() and text[:1].isalpha()):
        return True
    return text.endswith(")") and len(text) <= 60 and not any(ch.isdigit() for ch in text)


def header_unresolved(header: str | None, filing_date: Any = None,
                      doc_type: str | None = None,
                      balance_sheet: bool | None = None) -> bool:
    """A stored cell needs a header that names its period, or a flagged difference column."""
    if not header:
        return True
    if is_delta(header):
        return False
    return period_from_header(header, filing_date, doc_type, balance_sheet) is None


def _cells_of_block(rows: list[list[dict[str, Any]]], indices: list[int], table_no: int,
                    header_rows: list[list[dict[str, Any]]], page_unit: tuple[str, float] | None,
                    basis: str | None, filing_date: Any, page_no: int,
                    fallback_headers: list[str | None] | None = None,
                    doc_type: str | None = None,
                    page_balance_sheet: bool | None = None
                    ) -> tuple[list[dict[str, Any]], list[str | None] | None]:
    block = [rows[i] for i in indices]
    anchors = _anchors_of(block)
    if not anchors:
        return [], None
    label_x = [token["x0"] for row in block for token in row
               if not token["num"] and len(token["text"]) > 2]
    if len(anchors) > 1 and label_x and anchors[0] < statistics.median(label_x):
        anchors = anchors[1:]                     # the printed row-number column
    gap = min((b - a for a, b in zip(anchors, anchors[1:])), default=60.0)
    left = anchors[0] - max(gap, 40.0)
    right = anchors[-1] + max(1.5 * gap, 40.0)     # a heading may pass the last anchor
    headers = _headers(_header_stack(header_rows, anchors, left, right), anchors, left)
    if fallback_headers and not any(headers):
        headers = fallback_headers                 # a statement continued from another page
    unit = _unit_of(" ".join(token["text"] for row in header_rows for token in row)) or page_unit
    tolerance = max(8.0, 0.45 * gap)

    def aligned(row: list[dict[str, Any]]) -> int:
        return sum(1 for token in row
                   if token["num"] and token["x1"] > left + 2
                   and min(abs(anchor - token["x1"]) for anchor in anchors) <= tolerance)

    data_rows = [row for row in block if aligned(row) >= 2]
    if len(data_rows) < 2:
        return [], headers                        # scattered call-outs, not a table
    labeled_rows = [row for row in data_rows
                    if any(token["x1"] <= left + 2 and _ALPHA.search(token["text"])
                           for token in row)]
    if len(labeled_rows) < 0.5 * len(data_rows):
        return [], headers                        # scattered call-outs, not a labelled table

    prepared: list[dict[str, Any]] = []
    for row_no, index in enumerate(indices):
        row = rows[index]
        label_tokens = [token for token in row if token["x1"] <= left + 2]
        data = [token for token in row if token["num"] and token["x1"] > left + 2]
        first = next((token for token in row if token["text"].strip()), None)
        at_label = first is not None and first["x1"] <= left + 2
        numbered = bool(at_label and first is not None and ROWNUM.match(first["text"]))
        marked = bool(at_label and first is not None and MARKER.match(first["text"]))
        if numbered and first is not None:
            label_tokens = [token for token in label_tokens if token is not first]
        label = " ".join(token["text"] for token in label_tokens).strip()
        prepared.append({
            "row_no": row_no, "data": data, "label": label, "numbered": numbered,
            "marked": marked, "is_data": aligned(row) >= 2,
            "x0": label_tokens[0]["x0"] if label_tokens else 0.0,
            "y": sum((token["y0"] + token["y1"]) / 2 for token in row) / max(len(row), 1)})

    balance_sheet = page_balance_sheet

    cells: list[dict[str, Any]] = []
    section = ""
    section_x: float | None = None
    pending: list[str] = []
    last_cells: list[dict[str, Any]] = []
    for position, item in enumerate(prepared):
        if not item["is_data"]:
            label = item["label"]
            if not label or _prose_label(label):
                continue
            previous = next((j for j in range(position - 1, -1, -1)
                             if prepared[j]["is_data"]), None)
            following = next((j for j in range(position + 1, len(prepared))
                              if prepared[j]["is_data"]), None)
            near = prepared[following] if following is not None else None
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
            elif last_cells and _wrap_fragment(label):
                _append_label(last_cells, label)   # the label's last line, printed below it
            elif item["marked"] or item["numbered"]:
                pending.append(label)              # a body row whose numbers sit below it
            elif _wrap_fragment(label):
                continue                           # an orphan continuation line: no row label
            else:
                section = label
                section_x = item["x0"]
            continue
        if item["numbered"] or item["marked"]:
            if section_x is None or item["x0"] <= section_x + 2:
                section = ""                       # a new row group at the same indent
                section_x = None
        parts = pending + ([item["label"]] if item["label"] else [])
        pending = []
        own_label = " ".join(parts)
        row_label = " > ".join(part for part in (section, own_label) if part) or None
        if not row_label:
            last_cells = []                       # no printed row label: not a stored cell
            continue
        cell_unit = label_unit(own_label) or _unit_of(own_label) or label_unit(row_label) or unit
        if not _ALPHA.search(row_label):
            last_cells = []                       # '%' or '-' alone is not a row label
            continue
        emitted: list[dict[str, Any]] = []
        for token in item["data"]:
            column = min(range(len(anchors)), key=lambda k: abs(anchors[k] - token["x1"]))
            if abs(anchors[column] - token["x1"]) > tolerance:
                column = -1
            header = headers[column] if 0 <= column < len(headers) else None
            if not header or header_unresolved(header, filing_date, doc_type, balance_sheet):
                continue                          # no usable column header: not a stored cell
            value, percent = _number(token["text"])
            if percent:
                unit_text, scale, value = "%", 1.0, value
            elif cell_unit is not None:
                unit_text, scale = cell_unit
                value = None if value is None else round(value * scale, 2)
            else:
                unit_text, scale, value = None, None, None
            delta = is_delta(header)
            emitted.append({
                "page": page_no, "table_no": table_no, "row_no": item["row_no"],
                "col_no": column, "row_label": row_label,
                "col_header": header,
                "period_id": None if delta else period_from_header(
                    header, filing_date, doc_type, balance_sheet),
                "basis": basis, "value_text": token["text"], "value": value,
                "unit_text": unit_text, "scale": scale,
                "bbox": f"{token['x0']:.1f},{token['y0']:.1f},{token['x1']:.1f},{token['y1']:.1f}",
                "method": "text_layer;delta" if delta else "text_layer"})
        cells.extend(emitted)
        last_cells = emitted
    return cells, headers


def _page_balance_sheet(page: Any) -> bool | None:
    """A page titled Balance Sheet prints as-at columns; a P&L prints quarters."""
    clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.30)
    text = " ".join(str(page.get_text("text", clip=clip)).split())
    if _BS_TITLE.search(text):
        return True
    if _PL_TITLE.search(text):
        return False
    return None


def _page_cells(page: Any, pno: int, filing_date: Any,
                carry: list[str | None] | None,
                doc_type: str | None = None) -> tuple[list[dict[str, Any]],
                                                      list[str | None] | None]:
    """One page's cells plus the last column headers seen, for a continued statement."""
    height = float(page.rect.height)
    basis = _basis(page)
    page_unit = _unit_of(_top_text(page, height))
    page_balance_sheet = _page_balance_sheet(page)
    rows = [_tokens(row) for row in _rows_of(page.get_text("words"))]

    blocks: list[list[int]] = []
    current: list[int] = []
    gap = 0
    for i, row in enumerate(rows):
        numbers = _numeric_count(row)
        if numbers >= 2 and i and _month_row(rows[i - 1]) and _date_parts(row):
            for token in row:                     # the day/year half of a wrapped date row
                token["num"] = False
            numbers = 0
        if numbers >= 2:
            current.append(i)
            gap = 0
        elif current and gap < 2 and numbers == 0:
            current.append(i)
            gap += 1
        else:
            if sum(1 for j in current if _numeric_count(rows[j]) >= 2) >= 2:
                blocks.append(current)
            current, gap = ([i] if numbers >= 2 else []), 0
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
            page_unit, basis, filing_date, pno, carry, doc_type, page_balance_sheet)
        if headers and any(headers):
            carry = headers
        cells.extend(found)
        previous_end = indices[-1]
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
