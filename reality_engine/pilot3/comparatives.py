"""Printed comparative columns of the quarterly results tables (T-057), part ``comparatives``.

A quarterly results PDF prints, beside the current quarter, the preceding and year-ago quarters, the
year-to-date and the last full year.  ``fin_quarter_xbrl`` holds only the window's quarters, so YoY, QoQ and
TTM cannot be computed from XBRL alone.  This part rebuilds every P&L column from the page's **word boxes**
(``page.get_text("words")``, rows by y-centre, columns by x) -- the stored page text scatters a table --
maps each printed label to the canonical line item the XBRL store uses (``lexicon/results_lines.yaml``),
and stores a cell only when a check confirms it: the XBRL value of that quarter (``xbrl_ok``) or one of the
table's own identities (``sum_ok``).  Everything else is ``unchecked`` (stored, never used by ratios) or
dropped to ``<out>_comparatives_review.csv``.  A repaired token (an OCR letter read as a digit) enters only
when a check confirms exactly that value.

Point in time: ``known_at`` is the ``doc.known_at`` of the document that printed the cell -- never the XBRL
time of another filing, so a past date only sees what that day had.

The part rewrites ONE company's rows at a time: the table is created ``IF NOT EXISTS`` and only
``--symbols`` rows are deleted (``schema.create`` would drop every company's rows -- HANDOFF 4 Nov).
"""
from __future__ import annotations

import csv
import itertools
import re
import sqlite3
import time
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from reality_engine.pilot3 import profile, schema

TABLE = "fin_quarter_printed"
# What ratios.py and pilot3_fin may use.  ``repeat_ok`` (T-057 round 2): the same symbol, basis,
# period_end, period_type and line item, printed by a DIFFERENT filing (a different date) at the same
# value within tolerance -- two independent readings of two PDFs agree.
CHECK_OK = ("xbrl_ok", "sum_ok", "repeat_ok")
CONFIRMED = ("xbrl_ok", "sum_ok")   # what one page's own checks can confirm while it is read
ROLE_ORDER = ("current", "preceding", "year_ago", "ytd", "prior_ytd", "last_fy")
RULE_Y = 3.5          # a new row when the y-centre moves more than this many points (kpi.py:1538)
MERGE_X = 6.0         # two number fragments closer than this are one printed number ("20,21 1" -> 20,211)
LEXICON = Path(__file__).with_name("lexicon") / "results_lines.yaml"

# A rupee table; a US-dollar one is never read (INFY p3-p5 and the lower half of p21).
_DOLLAR = re.compile(r"us\s*\$|usd|\bu\.s\.\s*\$|in\s+us\s+dollar")
_AUDITOR = re.compile(r"independent\s+auditor|auditor'?s\s+report|review\s+report|we\s+have\s+reviewed")
_CASH_PAGE = re.compile(r"cash\s+flows?|statement\s+of\s+changes\s+in\s+equity")
_SEGMENT = re.compile(r"\bsegment")
_RECON = re.compile(r"reconciliation\s+of|non[-\s]?ifrs")   # a non-IFRS reconciliation is not the P&L table
_TITLE = re.compile(r"\bresults\b")
# A ratio or margin row is never a rupee line; a cost line printed in brackets is not a P&L expense.
_PCT_LABEL = re.compile(r"%|\bmargin")
_COST_ITEMS = ("finance_cost", "depreciation", "employee_cost", "total_expenses", "other_expenses",
               "cost_of_materials")
_INCOME_ITEMS = ("revenue_from_operations", "total_income", "interest_income", "net_premium", "gross_premium")
_PROFIT_ITEMS = ("pat", "pbt", "pbt_before_exceptional", "operating_profit", "net_surplus", "profit_before_tax")
_PL_BOTTOM = _PROFIT_ITEMS + ("total_expenses", "tax", "eps_basic", "eps_diluted", "total_comprehensive_income")
_TOTAL_ITEMS = ("total_income", "total_expenses", "pbt", "pat", "tax", "revenue_from_operations")
_MONTHS = {"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
           "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9,
           "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
           "december": 12}
def _month(text: str) -> int | None:
    """Month number of a printed (possibly OCR-noisy) month word: ``Detember`` -> 12, ``Scptcmbcr`` -> 9."""
    low = (text or "").lower().strip(".,()")
    for key in (low[:9], low[:4], low[:3]):
        if key in _MONTHS:
            return _MONTHS[key]
    if len(low) >= 5:
        best, score = None, 0.0
        for name, number in _MONTHS.items():
            ratio = SequenceMatcher(None, low, name).ratio()
            if ratio > score:
                best, score = number, ratio
        if score >= 0.8:
            return best
    return None


_SINGLE_OCR = set("OoIltrsSE")
_OCR = {"O": "0", "o": "0", "I": "1", "l": "1", "t": "1", "r": "1", "s": "5", "S": "5", "E": "8"}
_DATE_ONE = re.compile(r"^(\d{1,2})\s*[.,/\-]\s*(\d{1,2})\s*[.,/\-]\s*(\d{2,4})$")
_YEAR = re.compile(r"^(19|20)\d{2}$")
_DAY = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[.,]?$")
_DAY_MONTH_YEAR = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})[,.]?\s+((?:19|20)\d{2})")
_MONTH_DAY_YEAR = re.compile(r"\b([a-z]{3,9})\s*[,.]?\s*(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*((?:19|20)\d{2})")
_MONTH_YEAR = re.compile(r"\b([a-z]{3,9})\s*[,.]?\s*((?:19|20)\d{2})")
_NUM = re.compile(r"^[\(\)\d.,\-–—]+$")
_MIXED = re.compile(r"^[0-9OoIltrsSE.,\-()]+$")


# ------------------------------------------------------------------ lexicon ---------------------------------------------------------------
_LEX: list[tuple[str, str]] | None = None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def lexicon() -> list[tuple[str, str]]:
    """``[(normalised pattern, canonical line item)]``, longest pattern first (so it wins a tie)."""
    global _LEX
    if _LEX is None:
        import yaml

        data = yaml.safe_load(LEXICON.read_text(encoding="utf-8")) or {}
        out = []
        for item, patterns in data.items():
            for pattern in patterns if isinstance(patterns, list) else [patterns]:
                out.append((_norm(pattern), str(item)))
        out.sort(key=lambda pair: -len(pair[0]))
        _LEX = out
    return _LEX


def _fuzzy_score(pattern: str, label: str) -> float:
    """Every token of the pattern matched by a distinct label token in the same order (``tot il`` -> ``total``)."""
    want, have = pattern.split(), label.split()
    if len(want) < 2:
        return 0.0
    total, last, first = 0.0, -1, None
    for token in want:
        best, at = 0.0, None
        for i in range(last + 1, len(have)):
            score = SequenceMatcher(None, token, have[i]).ratio()
            if score > best:
                best, at = score, i
        if at is None or best < 0.74:
            return 0.0
        last = at
        first = at if first is None else first
        total += best
    if first is not None and (last - first + 1) > len(want) + 1:   # a couple of words apart at most
        return 0.0
    return total / len(want)


def match_line(label: str) -> str | None:
    """Canonical line item for a printed label, or None.  The most specific pattern wins: more matched tokens
    first (``total revenue from operalions`` -> ``revenue_from_operations``, not ``total_income``), then an
    exact phrase, then OCR-tolerant token similarity.  A percentage or margin row never maps (KEC's
    ``Operating Margin excluding exceptional item (%)`` is not the exceptional-items rupee line)."""
    if _PCT_LABEL.search((label or "").lower()):
        return None
    text = _norm(label)
    if not text:
        return None
    words = text.split()
    best, found = 0.0, None
    for pattern, item in lexicon():
        tokens = pattern.split()
        if len(tokens) == 1:
            if pattern in words:
                score = 1.0
            elif len(pattern) >= 4:      # an OCR-mangled single word still matches ("Baic" -> basic)
                ratio = max((SequenceMatcher(None, pattern, word).ratio() for word in words if len(word) >= 4),
                            default=0.0)
                score = ratio if ratio >= 0.78 else 0.0
            else:
                score = 0.0
        elif pattern in text:
            score = 1.02
        else:
            score = _fuzzy_score(pattern, text)
            if score < 0.8:
                continue
        score *= len(tokens)
        if score > best:
            best, found = score, item
    return found


# ------------------------------------------------------------------ word boxes ------------------------------------------------------------
def rows_from_words(words, tol: float = RULE_Y) -> list[list[tuple]]:
    """Rebuild printed rows from word boxes: sort by y-centre then x, new row past ``tol`` points (kpi.py:1538)."""
    ordered = sorted(words, key=lambda w: ((w[1] + w[3]) / 2.0, w[0]))
    rows: list[list[tuple]] = []
    current: list[tuple] = []
    y = None
    for word in ordered:
        centre = (word[1] + word[3]) / 2.0
        if y is None or abs(centre - y) <= tol:
            current.append(word)
            y = centre if y is None else y
        else:
            rows.append(current)
            current = [word]
            y = centre
    if current:
        rows.append(current)
    return [[w for w in sorted(row, key=lambda t: t[0])] for row in rows]


def _page_words(page) -> list[tuple]:
    """Word boxes of a page in its VISIBLE orientation.

    MARUTI's 2026-01-28/04-28 filings and INFY's 2026-01-14 print the table sideways: in the raw PDF the
    words of a 270-degree page sort into garbage (``6 5 4 3 2 I``), so the boxes go through the page's own
    ``rotation_matrix`` before they are grouped into rows.  A page with no text layer is returned empty (its
    pages are listed as needing OCR, never guessed)."""
    words = page.get_text("words")
    if not words or not page.rotation:
        return words
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    matrix = page.rotation_matrix
    out: list[tuple] = []
    for word in words:
        rect = fitz.Rect(word[:4]) * matrix
        out.append((rect.x0, rect.y0, rect.x1, rect.y1, *word[4:]))
    return out


def _frag(text: str) -> bool:
    """Could this word be (part of) a printed number?  OCR letters are candidates, a percent is not."""
    word = (text or "").strip()
    if not word or word.endswith("%"):
        return False
    if _NUM.fullmatch(word):
        return True
    if len(word) == 1 and word in _SINGLE_OCR:
        return True
    return bool(len(word) >= 2 and _MIXED.fullmatch(word) and sum(ch.isdigit() for ch in word) >= 2)


def _tokens(row) -> list[dict]:
    """Number tokens of a row: adjacent fragments of ONE number merged, ``raw`` keeps the printed words (spaced)."""
    out: list[dict] = []
    for word in row:
        if _frag(word[4]):
            if out and word[0] - out[-1]["x1"] <= MERGE_X and \
                    re.search(r"[0-9OoIltrsSE]", "".join(out[-1]["words"]) + word[4]):
                token = out[-1]
                token["words"].append(word[4])
                token["x1"] = word[2]
            else:
                out.append({"x0": word[0], "x1": word[2], "words": [word[4]]})
    for token in out:
        token["raw"] = " ".join(token["words"])
        token["text"] = "".join(token["words"])
    return out


def _label(row) -> str:
    return " ".join(w[4] for w in row if not _frag(w[4]))


def _strip_row_number(row) -> list[tuple]:
    """Drop a printed row number: ``1 Interest earned …`` but keep ``18,037 15,715 …``."""
    if len(row) >= 2 and _frag(row[0][4]) and not _frag(row[1][4]):
        return row[1:]
    return row


# ------------------------------------------------------------------ numbers ---------------------------------------------------------------
def _parse_cell(item: str, text: str, decimals: int, eps_decimals: int | None = None) -> tuple[float, bool] | None:
    """A printed cell under the table's decimal count; EPS keeps its own (never scaled, printed to paise).

    An EPS token whose separator the scan lost (``466 90``) is read under the table's EPS decimals; only a
    check then confirms the value."""
    if item.startswith("eps_"):
        m = re.search(r"[.,](\d{1,2})[.,]?$", text.strip())
        digits = len(m[1]) if m else (eps_decimals or 0)
        return read_number(text, digits)
    return read_number(text, decimals)


def _decimals(tokens) -> int:
    """Decimal places of the table: the majority reading of the last separator."""
    votes: dict[int, int] = defaultdict(int)
    for text in tokens:
        m = re.search(r"[.,](\d+)$", text)
        if not m:
            continue
        n = len(m[1])
        votes[0 if n == 3 else (n if n <= 2 else 0)] += 1
    if not votes:
        return 2
    return max(votes, key=lambda key: (votes[key], -key))


def read_number(raw_text: str, decimals: int) -> tuple[float, bool] | None:
    """``(value, repaired)`` under the table's decimal count; separators are re-read, never guessed.

    ``506.155`` in an integer table is 506,155; ``17.369.35`` is 17,369.35; ``79362,78`` is 79,362.78;
    ``533-402`` is 533,402; brackets are negative; a lone dash is zero.  A letter read as a digit marks the
    token repaired (it may only be stored when a check confirms exactly that value)."""
    text = (raw_text or "").strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if text in ("-", "–", "—", ""):
        return 0.0, False
    repaired = bool(re.search(r"[A-Za-z]", text))
    for letter, digit in _OCR.items():
        text = text.replace(letter, digit)
    if not re.fullmatch(r"[\d.,\-–—]+", text):
        return None
    digits = re.sub(r"[^0-9]", "", text)
    if not digits:
        return None
    value = int(digits) / (10.0 ** decimals)
    return (-value if negative else value), repaired


# ------------------------------------------------------------------ dates and roles -------------------------------------------------------
def _month_end(year: int, month: int) -> str:
    last = {1: 31, 2: 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 3: 31, 4: 30, 5: 31,
            6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[month]
    return f"{year:04d}-{month:02d}-{last:02d}"


def _shift(date_text: str, months: int) -> str:
    """Move a quarter end by ``months``: always the target month's last day (30 Jun - 3 -> 31 Mar)."""
    y, m = int(date_text[:4]), int(date_text[5:7])
    m += months
    while m <= 0:
        m, y = m + 12, y - 1
    while m > 12:
        m, y = m - 12, y + 1
    return _month_end(y, m)


def _fy_of(end: str) -> str:
    y, m = int(end[:4]), int(end[5:7])
    return f"FY{str(y + 1 if m >= 4 else y)[2:]}"


def _quarter(period_end: str, ptype: str) -> tuple[str, str, str]:
    """``(fiscal_period, period_start, period_type)`` for a printed column."""
    y, m = int(period_end[:4]), int(period_end[5:7])
    fy = y + 1 if m >= 4 else y
    if ptype == "fy":
        return f"FY{str(fy)[2:]}", f"{fy - 1}-04-01", "fy"
    if ptype == "ytd":
        label = "H1" if m == 9 else ("9M" if m == 12 else "FY")
        return f"{label}FY{str(fy)[2:]}", f"{fy - 1}-04-01", "ytd"
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(m)
    start = {6: f"{y}-04-01", 9: f"{y}-07-01", 12: f"{y}-10-01", 3: f"{y}-01-01"}.get(m, f"{y}-01-01")
    return f"Q{q or '?'}FY{str(fy)[2:]}", start, "quarter"


def _role_set(end: str, count: int) -> list[str]:
    """Positions a results table of this quarter and column count prints them in."""
    if count == 6:
        return ["current", "preceding", "year_ago", "ytd", "prior_ytd", "last_fy"]
    if count == 5:
        return ["current", "preceding", "year_ago", "ytd", "prior_ytd"]
    if count == 4:
        return ["current", "preceding", "year_ago", "last_fy"]
    return list(ROLE_ORDER[:count])


def _expected_date(role: str, end: str) -> tuple[int, int]:
    """``(month, year)`` a role prints, from the current period end."""
    y, m = int(end[:4]), int(end[5:7])
    if role in ("current", "ytd"):
        return m, y
    if role == "preceding":
        return (m - 3, y) if m > 3 else (m + 9, y - 1)
    if role in ("year_ago", "prior_ytd"):
        return m, y - 1
    if role == "last_fy":          # the last completed fiscal year ends in March
        return 3, y
    return m, y


def _date_match(got: tuple, want: tuple) -> bool:
    gm, gy = got
    wm, wy = want
    if gm is not None and gm != wm:
        return False
    if gy is not None and gy != wy:
        return False
    return gm is not None or gy is not None


def _merge_date_words(row) -> list[tuple]:
    """Join a header date split across word boxes: ``31 .1 2.2025`` -> ``31.12.2025``."""
    out: list[tuple] = []
    i = 0
    while i < len(row):
        taken = None
        size = 1
        for size in (3, 2):
            if i + size <= len(row):
                text = "".join(w[4].strip() for w in row[i:i + size])
                if _DATE_ONE.match(text):
                    taken = (row[i][0], row[i][1], row[i + size - 1][2], row[i + size - 1][3], text) \
                        + tuple(row[i][5:])
                    break
        if taken is not None:
            out.append(taken)
            i += size
        else:
            out.append(row[i])
            i += 1
    return out


def _header_cells(row) -> list[dict]:
    """Date cells of a header row in x order: ``{month, day, year}`` (any may be None)."""
    cells: list[dict] = []
    pending: dict | None = None
    for word in _merge_date_words(row):
        text = word[4].strip()
        low = text.lower().strip(".,()")
        one = _DATE_ONE.match(text)
        if one:
            day, month, year = int(one[1]), int(one[2]), int(one[3])
            if year < 100:
                year += 2000
            cells.append({"month": month if 1 <= month <= 12 else None, "day": day if 1 <= day <= 31 else None,
                          "year": year})
            pending = None
            continue
        joined = re.match(r"^([A-Za-z]{3,9})(\d{1,2})[.,]?$", text)
        month = _month(joined[1] if joined else re.sub(r"[^a-z]", "", low))
        if joined and month:
            day = int(joined[2])
            cells.append({"month": month, "day": day if 1 <= day <= 31 else None, "year": None})
            pending = None
            continue
        if month:
            pending = {"month": month, "day": None, "year": None}
            cells.append(pending)
            continue
        if pending is not None and _DAY.match(text):
            day = int(_DAY.match(text)[1])  # type: ignore[index]
            if 1 <= day <= 31 and pending["day"] is None:
                pending["day"] = day
                continue
        if _YEAR.match(text):
            if pending is not None and pending["year"] is None:
                pending["year"] = int(text)
            elif cells and cells[-1]["year"] is None:
                cells[-1]["year"] = int(text)
            else:
                cells.append({"month": None, "day": None, "year": int(text)})
    return cells


def _header_dates(header_rows, count: int) -> list[tuple] | None:
    """One ``(month, year)`` per column: the row with ``count`` date cells, then the year row beside it."""
    for i, row in enumerate(header_rows):
        cells = _header_cells(row)
        if len(cells) != count:
            continue
        if any(c["month"] is not None or c["year"] is not None for c in cells):
            for other in header_rows[i + 1:i + 3] + header_rows[max(0, i - 2):i]:
                years = [int(w[4].strip()) for w in other if _YEAR.match(w[4].strip())]
                if len(years) == count:
                    for cell, year in zip(cells, years):
                        if cell["year"] is None:
                            cell["year"] = year
                    break
            return [(c["month"], c["year"]) for c in cells]
    return None


# ------------------------------------------------------------------ page reading ----------------------------------------------------------
def _unit(text: str) -> float | None:
    """Rupee scale from the page's unit words (crore/lakh/million/thousand), None when the page prints none.

    Tolerant to OCR and spacing: ``Rs. inCrore``, ``(tin crore)``, ``(f in Million)`` and ``llNR crore`` all read."""
    compact = re.sub(r"[^a-z]", "", text.lower())
    best = None
    for word, scale in (("crore", 1e7), ("lakh", 1e5), ("million", 1e6), ("thousand", 1e3), ("billion", 1e9)):
        at = compact.find(word)
        if at >= 0 and (best is None or at < best[0]):
            best = (at, scale)
    return best[1] if best else None


def _columns(data_rows) -> list[float]:
    """Column anchors: the x1 a column's numbers end at, kept when the cluster appears on many rows."""
    xs = []
    for row in data_rows:
        tokens = _tokens(_strip_row_number(row))
        if len(tokens) < 3:
            continue
        xs.extend(token["x1"] for token in tokens)
    if not xs:
        return []
    clusters: list[list[float]] = []
    for value in sorted(xs):
        if clusters and value - clusters[-1][-1] <= 3.0:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    top = max(len(c) for c in clusters)
    return [sum(c) / len(c) for c in clusters if len(c) >= max(3, 0.35 * top)]


def _assign_tokens(row, anchors: list[float]) -> dict[int, dict]:
    """Every number token of a row to its nearest column (by right edge), when it is close enough."""
    gap = min((b - a for a, b in zip(anchors, anchors[1:])), default=40.0)
    tol = max(6.0, 0.45 * gap)
    out: dict[int, dict] = {}
    for token in _tokens(_strip_row_number(row)):
        at = min(range(len(anchors)), key=lambda i: abs(anchors[i] - token["x1"]))
        if abs(anchors[at] - token["x1"]) > tol:
            continue
        out.setdefault(at, token)
    return out


def _title_ok(text: str) -> bool:
    """A statement title, tolerant to OCR: ``Financial Rcsulls`` (and the badly scanned ``Finan.ial R6ulis``)
    still says results.  A page whose head says financial + quarter/months is a results statement too; the page's
    own P&L shape (an income and a profit line) filters a notes page."""
    if _TITLE.search(text):
        return True
    words = re.findall(r"[a-z]+", text)
    if any(len(word) >= 5 and word[0] == "r" and SequenceMatcher(None, word, "results").ratio() >= 0.6
           for word in words):
        return True
    financial = any(SequenceMatcher(None, word, "financial").ratio() >= 0.75 for word in words if len(word) >= 5)
    period = any(SequenceMatcher(None, word, name).ratio() >= 0.7
                 for word in words if len(word) >= 5 for name in ("months", "quarter"))
    return financial and period


def _pl_shape(values, rows3: int = 0) -> bool:
    """A P&L table carries an income line and a profit line; a notes, ratio or segment page does not.

    OCR can destroy every label while the numbers stay (MARUTI's 2026-10-27 consolidated page): a long statement
    table (12+ rows with three numeric columns) whose few readable lines are all P&L lines still counts."""
    items = {item for col in values.values() for item in col}
    if items & set(_INCOME_ITEMS) and items & set(_PL_BOTTOM):
        return True
    allowed = set(_PL_BOTTOM) | set(_COST_ITEMS) | {"other_income"}
    return rows3 >= 12 and len(items) >= 2 and not (items - allowed)


def _less_before_profit(data_rows) -> bool:
    """A ``Less:`` line above the profit line means the page is a reconciliation, not the P&L."""
    for row in data_rows:
        item = match_line(_label(row))
        if item in _PROFIT_ITEMS:
            return False
        if re.match(r"^les\b|^less?\b", _norm(_label(row))):
            return True
    return False


def _page_head(rows) -> str:
    return " ".join(w[4] for row in rows[:12] for w in row).lower()


def _layout_hint(header_rows, anchors) -> list[str] | None:
    """A 4-column Q2/Q3 table that prints a quarter pair AND a half-year pair (``Three months ended … Six months
    ended …``) is ``current, year_ago, ytd, prior_ytd`` -- not the Q1 four-column layout (INFY's IFRS statement)."""
    if len(anchors) != 4:
        return None
    text = " ".join(w[4] for row in header_rows for w in row).lower().replace("-", " ")
    if "six months" in text or "nine months" in text or "half year" in text:
        return ["current", "year_ago", "ytd", "prior_ytd"]
    return None


def read_page(rows) -> dict | None:
    """A P&L table page rebuilt from word-box ``rows``, or None when the page is not one.

    The page needs a title with "results" (OCR tolerant), no US-dollar unit, no auditor's report, no segment
    heading, a header of period words and at least 8 rows with 3 or more numeric columns; balance sheet, cash
    flow, ratio and segment pages are never read here.  It must carry a P&L shape -- an income line and a
    profit line -- so a notes page whose few matched rows are costs is refused."""
    if not rows:
        return None
    text = " ".join(w[4] for row in rows for w in row)
    low = text.lower()
    if _DOLLAR.search(low):
        return None
    head = _page_head(rows)
    if _AUDITOR.search(head):
        return None
    if _CASH_PAGE.search(head):          # the cash-flow statement and the equity statement are not P&L tables
        return None
    if _SEGMENT.search(head):            # a segment reconciliation is never a P&L table
        return None
    if _RECON.search(head):              # INFY's IFRS press release reconciles adjusted non-IFRS measures
        return None
    if not _title_ok(" ".join(w[4] for row in rows[:16] for w in row).lower()):
        return None
    first = None
    for i, row in enumerate(rows):
        if match_line(_label(row)):
            first = i
            break
    if first is None:
        return None
    header_rows, data_rows = rows[:first], rows[first:]
    rows3 = sum(1 for row in data_rows if len(_tokens(_strip_row_number(row))) >= 3)
    if rows3 < 8:
        return None
    anchors = _columns(data_rows)
    if len(anchors) < 3:
        return None
    if _less_before_profit(data_rows):
        return None
    values: dict = defaultdict(lambda: defaultdict(list))
    labels: dict[str, str] = {}
    for index, row in enumerate(data_rows):
        item = match_line(_label(row))
        if item is None:
            continue
        cells = _assign_tokens(row, anchors)
        if len(cells) < 2:          # a badly scanned table keeps a row whose cells partly print (MARUTI)
            continue
        labels.setdefault(item, _label(row).strip())
        quote = " ".join(w[4] for w in row)
        for at, token in cells.items():
            token["quote"] = quote
            token["row"] = index
            token["label"] = _label(row)
            values[at][item].append(token)
    if not values or not _pl_shape(values, rows3):
        return None
    decimals = _decimals([t["text"] for col in values.values() for tokens in col.values() for t in tokens])
    return {"anchors": anchors, "dates": _header_dates(header_rows, len(anchors)), "values": values,
            "labels": labels, "text": text, "head": head, "header_rows": header_rows[:12],
            "decimals": decimals, "scale": _unit(text), "hint": _layout_hint(header_rows, anchors)}


# ------------------------------------------------------------------ XBRL side -------------------------------------------------------------
def xbrl_index(conn: sqlite3.Connection, symbol: str) -> dict:
    """``{(basis, period_end): {item: value}}`` for the symbol's XBRL quarters."""
    values: dict = defaultdict(dict)
    for basis, end, item, value in conn.execute(
            "SELECT basis, period_end, line_item, value FROM fin_quarter_xbrl "
            "WHERE symbol=? AND basis IN ('standalone','consolidated')", (symbol,)):
        values[(basis, end)][item] = value
    return values


def _close(got: float, want: float, tol: float) -> bool:
    return abs(got - want) <= tol


def _page_basis(text: str, head: str | None = None) -> str | None:
    """Standalone / consolidated from the page title (the head rows), never from a note lower on the page.

    Tolerant to OCR: ``ca"nsolidated`` and ``Consolidstcd`` still say consolidated."""
    for source in (head, text):
        low = (source or "").lower()
        if not low:
            continue
        found: dict[str, int] = {}
        for name in ("standalone", "consolidated"):
            at = low.find(name)
            if at < 0:
                for word in re.findall(r"[a-z]{7,}", low):
                    if SequenceMatcher(None, word, name).ratio() >= 0.8:
                        at = low.find(word)
                        break
            if at >= 0:
                found[name] = at
        if not found:
            continue
        if len(found) == 1:
            return next(iter(found))
        return "standalone" if found["standalone"] < found["consolidated"] else "consolidated"
    return None


# ------------------------------------------------------------------ checks ---------------------------------------------------------------
# item = the signed sum of its inputs; tolerance = 2 units of the last printed decimal
_IDENTITIES = (
    ("total_income", (("revenue_from_operations", 1.0), ("other_income", 1.0))),
    ("pbt_before_exceptional", (("total_income", 1.0), ("total_expenses", -1.0))),
    ("pbt", (("pbt_before_exceptional", 1.0), ("exceptional_items", 1.0))),
    ("pat", (("pbt", 1.0), ("tax", -1.0))),
    ("total_comprehensive_income", (("pat", 1.0), ("other_comprehensive_income", 1.0))),
)
_BANK_IDENTITIES = (
    ("total_income", (("interest_income", 1.0), ("other_income", 1.0))),
    ("expenditure_excl_provisions", (("interest_expended", 1.0), ("operating_expenses", 1.0))),
    ("operating_profit", (("total_income", 1.0), ("expenditure_excl_provisions", -1.0))),
    ("pbt", (("operating_profit", 1.0), ("provisions_and_contingencies", -1.0))),
    ("pat", (("pbt", 1.0), ("tax", -1.0))),
)


def _check_column(cells: dict, tol: float, ambiguous: set[str] | None = None) -> list[tuple]:
    """Mark ``sum_ok`` on the cells of every identity that holds; return ``(item, inputs, target, want)`` failures.

    A failure whose input row (or target row) was printed more than once (``ambiguous``) proves nothing: the
    chosen row may simply be the wrong one (BAJFINANCE's total income), so the cell is kept and only logged."""
    ambiguous = ambiguous or set()
    identities = _BANK_IDENTITIES if ("interest_income" in cells or "operating_profit" in cells) else _IDENTITIES
    fails: list[tuple] = []
    for item, inputs in identities:
        target = cells.get(item)
        if target is None:
            continue
        if all(name in cells for name, _sign in inputs):
            want = sum(cells[name]["value"] * sign for name, sign in inputs)
            if _close(want, target["value"], tol):
                target["ident"] = "sum_ok"
                for name, _sign in inputs:
                    cells[name]["ident"] = "sum_ok"
            elif item in ambiguous or any(name in ambiguous for name, _sign in inputs):
                fails.append((item, [name for name, _sign in inputs], target["value"], want, True))
            else:
                fails.append((item, [name for name, _sign in inputs], target["value"], want, False))
        elif item == "pbt" and "pbt_before_exceptional" in cells and _close(
                cells["pbt_before_exceptional"]["value"], target["value"], tol):
            target["ident"] = "sum_ok"     # no exceptional line printed: pbt equals pbt before exceptional
            cells["pbt_before_exceptional"]["ident"] = "sum_ok"
    return fails


def _eps_ok(cells: dict, shares: float | None) -> None:
    """EPS ~ pat / shares within 1.5%, when a share count is known."""
    eps, pat = cells.get("eps_basic"), cells.get("pat")
    if eps and pat and shares and shares > 0:
        want = pat["value"] / shares
        if abs(eps["value"] - want) <= max(0.015 * abs(want), 0.02):
            eps["ident"] = "sum_ok"


# ------------------------------------------------------------------ extraction ------------------------------------------------------------
def has_table(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone())


def _open_pdf(path: Path | str | None, symbol: str):
    candidates = [Path(path)] if path else []
    current = profile.active() if profile.under_profile() else None
    raw_root = getattr(current, "raw_root", None)
    if path and raw_root:
        candidates.append(Path(raw_root) / symbol / "quarterly_results" / Path(path).name)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            import pymupdf as fitz
        except ImportError:  # pragma: no cover
            import fitz
        try:
            return fitz.open(str(candidate))
        except Exception:
            return None
    return None


def _shares(conn, symbol: str, basis: str, day: str) -> float | None:
    row = conn.execute("SELECT shares_outstanding FROM share_capital WHERE symbol=? AND event IS NULL AND basis=? "
                       "AND as_of_date<=? ORDER BY as_of_date DESC, known_at DESC LIMIT 1",
                       (symbol, basis, day)).fetchone()
    return row[0] if row and row[0] else None


def run(conn: sqlite3.Connection, symbols=None, review_path: Path | str | None = None) -> dict:
    """Read every ``results`` document's P&L pages for ``symbols`` and rewrite their ``fin_quarter_printed`` rows."""
    schema.ensure(conn, (TABLE,))
    want = [s.strip().upper() for s in (symbols or profile.symbols()) if s and s.strip()]
    review: list[dict] = []
    stats: dict = {}
    for symbol in want:
        conn.execute(f"DELETE FROM {TABLE} WHERE symbol=?", (symbol,))
        stats[symbol] = _extract_symbol(conn, symbol, review)
    conn.commit()
    if review_path:
        path = Path(review_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["symbol", "doc_key", "page", "line_item", "column_role",
                                                    "raw_token", "check", "detail"])
            writer.writeheader()
            writer.writerows(review)
        stats["review_csv"] = str(path)
    stats["review_rows"] = len(review)
    return stats


def _extract_symbol(conn: sqlite3.Connection, symbol: str, review: list[dict]) -> dict:
    started = time.time()
    isin = conn.execute("SELECT isin FROM company WHERE symbol=? ORDER BY isin_from DESC LIMIT 1", (symbol,)).fetchone()
    isin = isin[0] if isin else None
    xbrl = xbrl_index(conn, symbol)
    docs = conn.execute(
        "SELECT doc_key, known_at, source_key, sha256 FROM doc WHERE symbol=? AND doc_type='results' "
        "AND source_key IS NOT NULL AND known_at IS NOT NULL ORDER BY known_at", (symbol,)).fetchall()
    rows: list[tuple] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    files: list[dict] = []
    tables = pages = missing = 0
    for doc_key, known_at, source_key, sha in docs:
        if sha and sha in seen:
            duplicates.append(doc_key)
            continue
        if sha:
            seen.add(sha)
        pdf = _open_pdf(source_key, symbol)
        if pdf is None:
            missing += 1
            files.append({"doc_key": doc_key, "known_at": known_at[:10], "pages": 0, "tables": 0, "rows": 0,
                          "basis": {}, "empty_pages": [], "reason": "pdf_not_open"})
            continue
        entry = {"doc_key": doc_key, "known_at": known_at[:10], "pages": 0, "tables": 0, "rows": 0,
                 "basis": {}, "empty_pages": [], "reason": ""}
        previous = None
        for page_no in range(1, pdf.page_count + 1):
            entry["pages"] += 1
            pages += 1
            word_rows = rows_from_words(_page_words(pdf[page_no - 1]))
            if not word_rows:
                entry["empty_pages"].append(page_no)          # no text layer: needs OCR, never guessed
                previous = None
                continue
            table = read_page(word_rows)
            if table is None:
                table = _continuation(word_rows, previous)
            if table is None:
                previous = None
                continue
            tables += 1
            entry["tables"] += 1
            previous = table
            new = _table_rows(conn, symbol, isin, doc_key, page_no, known_at, table, xbrl, review)
            entry["rows"] += len(new)
            for row in new:
                entry["basis"][row[7]] = entry["basis"].get(row[7], 0) + 1
            rows.extend(new)
        if not entry["rows"] and not entry["reason"]:
            entry["reason"] = "no_pl_table"
        files.append(entry)
        pdf.close()
    rows = _apply_repeats(rows)
    conn.executemany(f"INSERT INTO {TABLE} VALUES ({','.join('?' * 23)})", rows)
    status: dict = defaultdict(int)
    for row in rows:
        status[row[20]] += 1
    return {"rows": len(rows), "tables": tables, "pages_read": pages, "pdf_not_read": missing,
            "quarters": len({r[3] for r in rows if r[5] == "quarter"}),
            "xbrl_ok": status.get("xbrl_ok", 0), "sum_ok": status.get("sum_ok", 0),
            "repeat_ok": status.get("repeat_ok", 0), "unchecked": status.get("unchecked", 0),
            "duplicate_docs": duplicates, "empty_pages": sum(len(f["empty_pages"]) for f in files),
            "restatements": _restatements(rows), "files": files, "seconds": round(time.time() - started, 1)}


def _continuation(word_rows, previous: dict | None) -> dict | None:
    """A table continued on the next page with no title inherits title, columns and unit, when the x-bins match.

    It must belong to the same statement: the same column count and x-bins as the page before it, at least one
    line item that page also printed, no segment ratio row and no cash-flow/segment heading."""
    if previous is None:
        return None
    head = _page_head(word_rows)
    if _DOLLAR.search(head) or _AUDITOR.search(head) or _CASH_PAGE.search(head) or _SEGMENT.search(head) \
            or _RECON.search(head):
        return None
    first = None
    for i, row in enumerate(word_rows):
        if match_line(_label(row)):
            first = i
            break
    if first is None:
        return None
    data_rows = word_rows[first:]
    anchors = _columns(data_rows)
    if len(anchors) != len(previous["anchors"]) or any(
            abs(a - b) > 10.0 for a, b in zip(anchors, previous["anchors"])):
        return None
    if _less_before_profit(data_rows):
        return None
    table = dict(previous)
    table["values"] = defaultdict(lambda: defaultdict(list))
    for index, row in enumerate(data_rows):
        item = match_line(_label(row))
        if item is None:
            continue
        cells = _assign_tokens(row, anchors)
        if len(cells) < 3:
            continue
        table["labels"].setdefault(item, _label(row).strip())
        quote = " ".join(w[4] for w in row)
        for at, token in cells.items():
            token["quote"] = quote
            token["row"] = index
            token["label"] = _label(row)
            table["values"][at][item].append(token)
    if not table["values"]:
        return None
    if not set(table["labels"]) & set(previous["labels"]):
        return None                      # no line item in common: not the same statement
    return table


def _restatements(rows: list[tuple]) -> list[dict]:
    seen: dict = {}
    out = []
    for row in rows:
        key = (row[7], row[9], row[3], row[5], row[6])  # basis, item, period_end, period_type, role
        if key in seen and abs(seen[key] - row[11]) > 1e-6:
            out.append({"line_item": row[9], "period_end": row[3], "role": row[6],
                        "value": row[11], "earlier": seen[key], "known_at": row[18]})
        seen.setdefault(key, row[11])
    return out


def _eps_decimals(values: dict) -> int:
    """Decimal places the table prints EPS to (the majority length of its last separator); a dash-printed
    zero keeps that count, so a 0 against an XBRL 0.11 is not inside 2 units of the last printed decimal."""
    votes: dict[int, int] = defaultdict(int)
    for col in values.values():
        for item, tokens in col.items():
            if not item.startswith("eps_"):
                continue
            for token in tokens:
                m = re.search(r"[.,](\d{1,2})[.,]?$", token["text"].strip())
                if m:
                    votes[len(m[1])] += 1
    return max(votes, key=lambda key: (votes[key], key)) if votes else 0


def _tol(item: str, decimals: int, scale: float, text: str | None = None,
         eps_decimals: int | None = None) -> float:
    """2 units of the last printed decimal: rupees of the table's scale for a rupee line, its OWN printed
    decimals for a per-share line (never scaled -- a crore-scaled EPS tolerance would accept any value)."""
    if item.startswith("eps_") or item.endswith("_per_share"):
        digits = eps_decimals
        if digits is None:
            digits = 0
            if text:
                m = re.search(r"[.,](\d{1,2})[.,]?$", text.strip())
                digits = len(m[1]) if m else 0
        return 2.0 / (10.0 ** digits)
    return 2.0 / (10.0 ** decimals) * scale


def _row_label(values: dict, item: str, row: int) -> str:
    for col in values.values():
        for token in col.get(item, []):
            if token["row"] == row:
                return _norm(token.get("label", ""))
    return ""


def _choose_rows(values: dict, roles: list, end: str, xbrl: dict, basis: str, scale: float, decimals: int,
                 tol: float, eps_decimals: int = 0) -> dict:
    """One printed row per line item: the row whose CURRENT column equals XBRL wins (EPS printed three times),
    then a row whose label starts with ``Total`` for a total, then the earliest row."""
    current = roles.index("current") if "current" in roles else None
    chosen: dict = {}
    for item in {name for col in values.values() for name in col}:
        rows_present = sorted({t["row"] for col in values.values() for t in col.get(item, [])})
        best = rows_present[0] if rows_present else None
        if current is not None and len(rows_present) > 1:
            for row in rows_present:
                token = next((t for t in values[current].get(item, []) if t["row"] == row), None)
                if token is None:
                    continue
                parsed = _parse_cell(item, token["text"], decimals, eps_decimals)
                if parsed and _xbrl_ok(xbrl, basis, end, item,
                                       parsed[0] * (1.0 if item.startswith("eps_") else scale),
                                       _tol(item, decimals, scale, token["text"], eps_decimals)):
                    best = row
                    break
        if current is None or len(rows_present) > 1:
            if best == rows_present[0] and item in _TOTAL_ITEMS:
                totals = [row for row in rows_present if _row_label(values, item, row).startswith("total")]
                if totals:
                    best = totals[0]
        chosen[item] = best
    return chosen


def _fallback_end(known_at: str) -> str | None:
    """Last resort for a header the OCR destroyed: the latest quarter end at most 60 days before the filing.

    It is only a candidate; ``_table_rows`` keeps the page only when the XBRL or the page's own arithmetic then
    confirms it, and records ``period from filing date`` in ``check_detail``."""
    day = (known_at or "")[:10]
    try:
        known = date.fromisoformat(day)
    except ValueError:
        return None
    year, month = known.year, known.month
    for _ in range(2):
        for m in (12, 9, 6, 3):
            candidate = date.fromisoformat(_month_end(year, m))
            if candidate <= known and (known - candidate).days <= 60:
                return candidate.isoformat()
        year -= 1
    return None


def _printed_tolerance(raw: str | None, value: float) -> float | None:
    """Rupees of the last printed decimal of a stored cell, read back from its raw token (``14,491.79`` -> 200,000
    on a crore table).  None when the token cannot be read as a number."""
    text = re.sub(r"\s+", "", raw or "")
    if not text:
        return None
    m = re.search(r"[.,](\d{1,2})[.,]?$", text)
    decimals = len(m[1]) if m else 0
    parsed = read_number(text, decimals)
    if parsed is None or not parsed[0]:
        return None
    return 2.0 / (10.0 ** decimals) * abs(value / parsed[0])


def _apply_repeats(rows: list[tuple]) -> list[tuple]:
    """``repeat_ok``: the same symbol, basis, period_end, period_type and line item, printed by a DIFFERENT filing
    (another date) at the same value within tolerance.  Two independent readings of two PDFs agree.  Each row keeps
    its own ``known_at``: the filing date is still what a past date may see, even though its agreement came later."""
    groups: dict = defaultdict(list)
    for i, row in enumerate(rows):
        groups[(row[0], row[7], row[3], row[5], row[9])].append(i)
    out = list(rows)
    marked = 0
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        for i in idxs:
            row = out[i]
            if row[20] != "unchecked":
                continue
            tol_i = _printed_tolerance(row[14], row[11])
            for j in idxs:
                if j == i or out[j][18][:10] == row[18][:10]:
                    continue
                tol_j = _printed_tolerance(out[j][14], out[j][11])
                tol = max((t for t in (tol_i, tol_j) if t is not None), default=0.0)
                if abs(row[11] - out[j][11]) <= tol + 1e-9:
                    detail = f"repeat of {out[j][18][:10]}"
                    out[i] = row[:20] + ("repeat_ok", (detail + "; " + row[21]) if row[21] else detail) + row[22:]
                    marked += 1
                    break
    return out


def _debit_costs(columns: dict) -> bool | None:
    """A cost line printed in brackets means the table is not the P&L (a segment reconciliation); only a table
    where EVERY cost line prints in brackets by convention may stand, with the magnitudes read positive.  Returns
    True when such a page was negated, False when no cost is negative, None when the page is refused."""
    cells = [(item, cell) for col in columns.values() for item, cell in col.items() if item in _COST_ITEMS]
    negative = [cell for _item, cell in cells if cell["value"] < 0]
    if not negative:
        return False
    if len(negative) != len(cells):
        return None
    for cell in negative:
        cell["value"] = -cell["value"]
        cell["bracketed"] = True
    return True


def _derive_tax(columns: dict) -> None:
    """Where only the current and deferred components print, the total is their sum, ``is_reported`` 0."""
    for cells in columns.values():
        if "tax" in cells or "current_tax" not in cells or "deferred_tax" not in cells:
            continue
        cur, dfr = cells["current_tax"], cells["deferred_tax"]
        cells["tax"] = {"value": cur["value"] + dfr["value"], "raw": f"{cur['raw']} {dfr['raw']}",
                        "repaired": False, "caption": f"{cur['caption']} + {dfr['caption']}",
                        "quote": f"{cur['quote']} | {dfr['quote']}", "item": "tax", "row": None, "derived": True}


def _table_rows(conn, symbol, isin, doc_key, page_no, known_at, table, xbrl, review) -> list[tuple]:
    """Resolve this table's roles, parse its cells, run the checks, and return the rows to store."""
    anchors = table["anchors"]
    head_text = " ".join(w[4] for row in (table.get("header_rows") or []) for w in row)
    end = _period_end(table.get("dates"), known_at, head_text or table["text"])
    fallback = False
    if not end:
        end = _fallback_end(known_at)
        fallback = bool(end)
    if not end:
        return []
    values = table["values"]
    count = len(anchors)
    decimals = table["decimals"]
    values_by_item: dict = {}
    for at, col in values.items():
        for item, tokens in col.items():
            values_by_item.setdefault(item, set()).update(t["row"] for t in tokens)
    ambiguous = {item for item, rows in values_by_item.items() if len(rows) > 1}
    basis_hint = _page_basis(table["text"], table.get("head"))
    choice = _roles(table.get("dates"), end, count, values, xbrl, basis_hint, table["scale"], decimals,
                    table.get("hint"))
    if choice is None:
        review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": None,
                       "column_role": None, "raw_token": None, "check": "no_scale_or_roles",
                       "detail": f"unit={table['scale']}"})
        return []
    roles, basis, scale = choice["roles"], choice["basis"], choice["scale"]
    rupee_tol = _tol("total_income", decimals, scale)
    eps_dec = _eps_decimals(values)
    shares = _shares(conn, symbol, basis, known_at)
    chosen = _choose_rows(values, roles, end, xbrl, basis, scale, decimals, rupee_tol, eps_dec)
    columns: dict[str, dict] = {}
    for at, role in enumerate(roles):
        if role is None:
            continue
        cells = {}
        for item, tokens in values.get(at, {}).items():
            if item == "face_value":
                continue
            best = next((t for t in tokens if t["row"] == chosen.get(item)), tokens[0])
            parsed = _parse_cell(item, best["text"], decimals, eps_dec)
            if parsed is None:
                review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": item,
                               "column_role": role, "raw_token": best["raw"], "check": "unreadable", "detail": ""})
                continue
            cells[item] = {"value": parsed[0] * (1.0 if item.startswith("eps_") else scale),
                           "raw": best["raw"], "repaired": parsed[1], "caption": table["labels"].get(item, ""),
                           "quote": best["quote"], "item": item, "row": best["row"]}
        columns[role] = cells
    _derive_tax(columns)
    bracketed = _debit_costs(columns)
    if bracketed is None:
        review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": None,
                       "column_role": None, "raw_token": None, "check": "not_pl_costs",
                       "detail": "a cost line prints in brackets inside a mixed page"})
        return []
    for cells in columns.values():
        cells["_fails"] = _check_column(cells, rupee_tol, ambiguous)
        _eps_ok(cells, shares)
    if bracketed and not any(isinstance(cell, dict) and cell.get("ident") == "sum_ok"
                             for cells in columns.values() for cell in cells.values()):
        review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": None,
                       "column_role": None, "raw_token": None, "check": "not_pl_costs",
                       "detail": "every cost in brackets but no identity holds"})
        return []
    # across columns: current + preceding = ytd on a Q2 table; EPS current + preceding ~ ytd within 0.02
    if end[5:7] == "09" and {"ytd", "current", "preceding"} <= set(columns):
        for item in (set(columns["current"]) & set(columns["preceding"]) & set(columns["ytd"])) - {"_fails"}:
            cur, pre, ytd = columns["current"][item], columns["preceding"][item], columns["ytd"][item]
            ok = abs(cur["value"] + pre["value"] - ytd["value"]) <= (0.02 if item == "eps_basic" else rupee_tol)
            if ok:
                for cell in (cur, pre, ytd):
                    cell.setdefault("ident", "sum_ok")
    # status per cell: xbrl_ok beats sum_ok beats unchecked; a failed or unconfirmed-repaired cell stores nothing
    out: list[tuple] = []
    for role, cells in columns.items():
        period_end, ptype = _role_period(role, end)
        for item, cell in cells.items():
            if item == "_fails":
                continue
            cell["status"] = "xbrl_ok" if _xbrl_ok(
                xbrl, basis, period_end, item, cell["value"], _tol(item, decimals, scale, cell["raw"], eps_dec)) \
                else cell.get("ident", "unchecked")
            cell["period_end"], cell["ptype"] = period_end, ptype
        for item, names, target, want, unsure in cells.get("_fails", []):
            cell = cells.get(item)
            if cell is None or cell["status"] in CHECK_OK:
                continue
            check = "sum_ambiguous" if unsure else "sum_failed"
            review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": item,
                           "column_role": role, "raw_token": cell["raw"], "check": check,
                           "detail": f"{item}={target} not {want}"})
            if not unsure:
                cell["drop"] = True
        for item, cell in list(cells.items()):
            if item == "_fails":
                continue
            if cell.get("drop") or (cell["repaired"] and cell["status"] not in CHECK_OK):
                if not cell.get("drop"):
                    review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": item,
                                   "column_role": role, "raw_token": cell["raw"], "check": "repair_unconfirmed",
                                   "detail": ""})
                del cells[item]
    # derived revenue: no row prints it, total income - other income does (HINDUNILVR); never for a bank or
    # an insurer, whose "revenue" is interest income / net premium and has its own row
    for role, cells in columns.items():
        if ({"interest_income", "operating_profit", "net_premium"} & set(cells)) and \
                "revenue_from_operations" not in cells:
            continue
        if "revenue_from_operations" not in cells and "total_income" in cells and "other_income" in cells:
            ti, oi = cells["total_income"], cells["other_income"]
            cells["revenue_from_operations"] = {
                "value": ti["value"] - oi["value"], "raw": f"{ti['raw']} {oi['raw']}", "item": "revenue_from_operations",
                "caption": f"{ti['caption']} - {oi['caption']}", "quote": f"{ti['quote']} | {oi['quote']}",
                "ident": "sum_ok", "repaired": False, "row": None, "derived": True,
                "period_end": ti["period_end"], "ptype": ti["ptype"], "status": "sum_ok"}
    for role, cells in columns.items():
        for item, cell in cells.items():
            if item == "_fails":
                continue
            fiscal, start, ptype = _quarter(cell["period_end"], cell["ptype"])
            unit = "inr_per_share" if item.startswith("eps_") else "inr"
            detail = []
            if table["scale"] is None:
                detail.append("scale from XBRL")
            if cell["repaired"]:
                detail.append("repaired")
            if cell.get("derived"):
                detail.append("derived")
            if cell.get("bracketed"):
                detail.append("bracketed costs")
            if fallback:
                detail.append("period from filing date")
            if choice.get("header_used"):
                detail.append("header_used")
            out.append((symbol, isin, start, cell["period_end"], fiscal, ptype, role, basis, "P&L", item,
                        cell["caption"], cell["value"], unit, 1.0, cell["raw"], cell["quote"], doc_key, page_no,
                        known_at, "doc.known_at", cell["status"], "; ".join(detail) or None,
                        0 if cell.get("derived") else 1))
    if fallback and not any(row[20] in CONFIRMED for row in out):
        return []                       # a guess with nothing confirming it stores nothing
    return out


def _xbrl_ok(xbrl: dict, basis: str, period_end: str, item: str, value: float, tol: float) -> bool:
    want = xbrl.get((basis, period_end), {}).get(item)
    return want is not None and _close(value, want, tol)


def _period_end(dates, known_at: str, text: str = "") -> str | None:
    """The current period end: the latest quarter end the header prints on or before the filing date.

    The header's per-column dates come first; a noisy header (HINDUNILVR's year-only row, INFY's split title)
    falls back to the title's own "ended 30th September, 2026"."""
    day = known_at[:10]
    low = (text or "").lower()
    found: list[tuple[int, int]] = []
    for month, year in (dates or []):
        if month in (3, 6, 9, 12) and year:
            found.append((year, month))
    for regex, month_at, year_at in ((_DAY_MONTH_YEAR, 2, 3), (_MONTH_DAY_YEAR, 1, 3), (_MONTH_YEAR, 1, 2)):
        for hit in regex.finditer(low):
            month = _month(hit[month_at])
            if month in (3, 6, 9, 12):
                found.append((int(hit[year_at]), month))
    best = None
    for year, month in found:
        candidate = _month_end(year, month)
        if candidate <= day and (date.fromisoformat(day) - date.fromisoformat(candidate)).days <= 160:
            best = max(best or candidate, candidate)
    return best


def _roles(dates, end: str, count: int, values: dict, xbrl: dict, basis_hint: str | None,
           scale: float | None, decimals: int, hint: list[str] | None = None) -> dict | None:
    """Column roles (header order first, a header layout hint second, layout by quarter last), basis and scale,
    checked against XBRL; the earlier candidate wins a tie."""
    default = _role_set(end, count)
    chance = None
    if dates and len(dates) == count:
        header, covered = _roles_from_dates(dates, end, default, count)
        if covered and header != default:
            chance = header
    bases = [basis_hint] if basis_hint else (["consolidated", "standalone"] if xbrl else ["unchecked"])
    target = list(hint) if hint else None
    candidates: list[list[str]] = []
    for roles in (target, chance, default):
        if roles is not None and roles not in candidates:
            candidates.append(roles)
    best = None
    for roles in candidates:
        for basis in bases:
            for sc in ([scale] if scale else [1e5, 1e6, 1e7]):
                if basis not in ("standalone", "consolidated"):
                    score = 0
                else:
                    score = _score_roles(roles, end, values, xbrl, basis, sc, decimals)
                if best is None or score > best[0]:
                    best = (score, roles, basis, sc)
    if best is None or (best[0] == 0 and scale is None):
        return None
    _score, roles, basis, sc = best
    if best[0] == 0 and basis_hint is None:
        basis = "unchecked"          # neither the title nor the XBRL match settles the basis
    periods = {role: _role_period(role, end) for role in roles if role}
    return {"roles": roles, "basis": basis, "scale": sc, "periods": periods, "score": best[0],
            "header_used": bool(chance and roles == chance)}


def _roles_from_dates(dates, end: str, default: list[str], count: int) -> tuple[list[str], bool]:
    """Header order: the day/month/year each column prints, checked against the role's expected date.

    Quarter columns come first and the ytd/year columns after them in every Indian results layout, so each
    group of roles is permuted over its own slots and the permutation the dates support best wins; the layout's
    own order breaks a tie (HDFCBANK's year-ago column is misread 39.09.2026 -- the count and the quarter
    decide).  A company that puts the year-ago before the preceding quarter (HINDUNILVR) is still read right."""
    expected = {role: _expected_date(role, end) for role in default}
    quarter = [r for r in default if r in ("current", "preceding", "year_ago")]
    group = [r for r in default if r not in ("current", "preceding", "year_ago")]

    def best_order(roles: list[str], start: int) -> list[str]:
        best, best_score = list(roles), -1
        for perm in itertools.permutations(roles):
            score = 0
            for i, role in enumerate(perm):
                at = start + i
                if dates and at < len(dates) and _date_match(dates[at], expected[role]):
                    score += 1
            score = score * 10 + sum(1 for i, role in enumerate(perm) if role == roles[i])
            if score > best_score:
                best, best_score = list(perm), score
        return best

    roles = (best_order(quarter, 0) + best_order(group, len(quarter)))[:count]
    return roles, bool(dates) and len(dates) == count


def _score_roles(roles, end, values, xbrl, basis: str, scale: float, decimals: int) -> int:
    tol = _tol("total_income", decimals, scale)
    eps_dec = _eps_decimals(values)
    score = 0
    for at, role in enumerate(roles):
        if not role:
            continue
        period_end, _ptype = _role_period(role, end)
        for item, tokens in values.get(at, {}).items():
            for token in tokens:
                parsed = _parse_cell(item, token["text"], decimals, eps_dec)
                if parsed is None:
                    continue
                value = parsed[0] * (1.0 if item.startswith("eps_") else scale)
                if _xbrl_ok(xbrl, basis, period_end, item, value,
                            _tol(item, decimals, scale, token["text"], eps_dec)):
                    score += 10 if role == "current" else 5
    if end[5:7] == "09" and all(r in roles for r in ("current", "preceding", "ytd")):
        i, j, k = roles.index("current"), roles.index("preceding"), roles.index("ytd")
        for item in (set(values.get(i, {})) & set(values.get(j, {})) & set(values.get(k, {}))):
            got = []
            for at in (i, j, k):
                parsed = _parse_cell(item, values[at][item][0]["text"], decimals)
                got.append(None if parsed is None else parsed[0])
            if any(g is None for g in got):
                continue
            if item == "eps_basic":
                score += 5 if abs(got[0] + got[1] - got[2]) <= 0.02 else 0
            else:
                score += 5 if abs(got[0] + got[1] - got[2]) * scale <= tol else 0
    return score


def shift_period(end: str, months: int) -> str:
    """A period end moved by ``months``, clamped to the target month's last day (30 Jun - 3 -> 31 Mar)."""
    return _shift(end, months)


def _role_period(role: str, end: str) -> tuple[str, str]:
    """``(period_end, period_type)`` a column role covers."""
    if role == "current":
        return end, "quarter"
    if role == "preceding":
        return _shift(end, -3), "quarter"
    if role == "year_ago":
        return _shift(end, -12), "quarter"
    if role == "ytd":
        return end, "fy" if end[5:7] == "03" else "ytd"
    if role == "prior_ytd":
        return _shift(end, -12), "fy" if end[5:7] == "03" else "ytd"
    if role == "last_fy":
        return _last_fy_end(end), "fy"
    return end, "quarter"


def _last_fy_end(end: str) -> str:
    y, m = int(end[:4]), int(end[5:7])
    return f"{y - 1}-03-31" if m == 3 else f"{y}-03-31"


# ------------------------------------------------------------------ consumers (ratios.py) -----------------------------------------------
def printed_quarters(conn: sqlite3.Connection, symbol: str) -> dict:
    """``{(basis, period_end): {item: (value, known_at, fiscal_period, period_start)}}`` from checked printed rows.

    The EARLIEST filing that printed a quarter is kept: its ``known_at`` is the day a past question may see."""
    out: dict = defaultdict(dict)
    marks = ",".join("?" * len(CHECK_OK))
    for basis, start, end, fiscal, item, value, known in conn.execute(
            "SELECT basis, period_start, period_end, fiscal_period, line_item, value, known_at FROM fin_quarter_printed "
            f"WHERE symbol=? AND period_type='quarter' AND check_status IN ({marks}) "
            "AND basis IN ('standalone','consolidated') ORDER BY known_at", (symbol, *CHECK_OK)):
        if not _is_quarter_end(end):
            continue
        out[(basis, end)].setdefault(item, (value, known, fiscal, start))
    return out


def _is_quarter_end(end: str | None) -> bool:
    """A printed period end must be a real quarter end (30 Jun / 30 Sep / 31 Dec / 31 Mar)."""
    try:
        return bool(end) and len(end) >= 10 and end[5:7] in ("03", "06", "09", "12") and \
            end[:10] == _month_end(int(end[:4]), int(end[5:7]))
    except (TypeError, ValueError):
        return False


def ttm_filings(conn: sqlite3.Connection, symbol: str, basis: str) -> list[dict]:
    """One TTM set per filing that printed it: ``{known_at, doc_key, period_end, items}``.

    ``TTM = last_fy + ytd - prior_ytd`` (a Q2/Q3 table), ``last_fy + current - year_ago`` (Q1, only when the
    table prints no ytd at all) or the printed year (Q4, the ``ytd`` column with ``period_type='fy'``).  Only
    checked cells are used; a missing cell never falls through to the other quarter's formula."""
    rows = conn.execute(
        "SELECT doc_key, known_at, period_end, period_type, column_role, line_item, value FROM fin_quarter_printed "
        f"WHERE symbol=? AND basis=? AND check_status IN ({','.join('?' * len(CHECK_OK))}) ORDER BY known_at",
        (symbol, basis, *CHECK_OK)).fetchall()
    by_doc: dict = {}
    for doc_key, known, end, ptype, role, item, value in rows:
        by_doc.setdefault((doc_key, known), {})[(role, item)] = (value, end, ptype)
    out = []
    for (doc_key, known), cells in by_doc.items():
        items = {}
        for item in {key[1] for key in cells}:
            ttm = _ttm_one(cells, item)
            if ttm is not None:
                items[item] = ttm
        if "pat" in items or "eps_basic" in items:
            comps = [items.get(k) for k in ("pbt_before_exceptional", "finance_cost", "depreciation", "other_income")]
            if "ebitda" not in items and comps[0] is not None and comps[1] is not None and comps[2] is not None \
                    and not profile.is_lender(symbol):
                items["ebitda"] = comps[0] + comps[1] + comps[2] - (comps[3] or 0.0)
            out.append({"known_at": known, "doc_key": doc_key, "items": items,
                        "period_end": max(end for _v, end, _p in cells.values())})
    return out


def _ttm_one(cells: dict, item: str) -> float | None:
    """The table's own shape decides the formula: a Q2/Q3 table prints a ytd column and uses
    ``last_fy + ytd - prior_ytd``; only a table with no ytd at all is a Q1 table
    (``last_fy + current - year_ago``).  A Q4 table prints the year itself.  A missing or unchecked cell returns
    None -- never the other quarter's formula."""
    def at(role):
        cell = cells.get((role, item))
        return None if cell is None else cell[0]

    has, cur, ago, ytd, prior = at("last_fy"), at("current"), at("year_ago"), at("ytd"), at("prior_ytd")
    has_ytd_column = any(role == "ytd" for role, _item in cells)
    if has_ytd_column:
        ytd_cell = cells.get(("ytd", item))
        if ytd_cell is not None and ytd_cell[2] == "fy":
            return ytd_cell[0]                              # the Q4 table prints the year itself
        if has is not None and ytd is not None and prior is not None:
            return has + ytd - prior                        # Q2 / Q3 table
        return None
    if has is not None and cur is not None and ago is not None:
        return has + cur - ago                                # Q1 table
    return None
