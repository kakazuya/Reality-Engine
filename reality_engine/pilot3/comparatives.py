"""Printed comparative columns of the quarterly results tables (T-057), part ``comparatives``.

A quarterly results PDF prints, beside the current quarter, the preceding and year-ago quarters, the
year-to-date and the last full year.  ``fin_quarter_xbrl`` holds only the window's quarters, so YoY, QoQ and
TTM cannot be computed from XBRL alone.  For a June period end, ``ytd``/``prior_ytd`` are never emitted (``_quarter``
refuses them with ``None``): wide (>=7-col) June pages are read only when ``_side_by_side_ok`` confirms mirrored
S/C halves, and a June ``last_fy`` column is stored only when its previous-March year is matched in the header
(``_date_match(..., require_year=True)``) or its values match XBRL, annual XBRL facts, or prior store FY rows (never by default position;
see ``_role_set`` and ``_roles``).  This part rebuilds every P&L column from the page's **word boxes**
(``page.get_text("words")``, rows by y-centre, columns by x) -- the stored page text scatters a table --
maps each printed label to the canonical line item the XBRL store uses (``lexicon/results_lines.yaml``),
and stores a cell only when a check confirms it: the XBRL value of that quarter (``xbrl_ok``) or one of the
table's own identities (``sum_ok``).  Everything else is ``unchecked`` (stored, never used by ratios) or
dropped to ``<out>_comparatives_review.csv``.  A repaired token (an OCR letter read as a digit) enters only
when a check confirms exactly that value.

Jumbled-layer / OCR pages (R-013, 18 Nov 2026): when ``_ocr_page_rows`` returns OCR word boxes (text layer scored
under the label dictionary), OCR and the text layer are resolved independently on their own column sets:
(1) both agree -> keep; (2) they differ -> keep the candidate higher on ``xbrl_ok (3) > repeat_ok (2) >
sum_ok (1) > unchecked (0)`` (OCR leads on ties, unconfirmed dropped) and log ``ocr_text_disagree``;
(3) layer-only (or OCR table unreadable) -> kept only if in ``CHECK_OK`` (``xbrl_ok``, ``sum_ok``,
``repeat_ok``), else dropped and logged as ``layer_unconfirmed``.  Clean pages keep existing behaviour.

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
from functools import lru_cache
from pathlib import Path

from reality_engine import raw_store
from reality_engine.pilot3 import profile, schema

TABLE = "fin_quarter_printed"
# What ratios.py and pilot3_fin may use.  ``repeat_ok`` (T-057 round 2): the same symbol, basis,
# period_end, period_type and line item, printed by a DIFFERENT filing (a different date) at the same
# value within tolerance -- two independent readings of two PDFs agree.
CHECK_OK = ("xbrl_ok", "sum_ok", "repeat_ok")
CONFIRMED = ("xbrl_ok", "sum_ok")   # what one page's own checks can confirm while it is read
_LADDER = {"xbrl_ok": 3, "repeat_ok": 2, "sum_ok": 1, "unchecked": 0}
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
# A ratio or margin row is never a rupee line; a discontinued-only row is never the continuing/total line.
_PCT_LABEL = re.compile(r"%|\bmargin")
_DISCONTINUED_LABEL = re.compile(r"\bdiscontinu(?:ed|ing)\b|\bdiscounting\s+operations\b|[-–]ounting\s+operations\b")
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
_DAY_MON_YR = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[-./'\s]?([A-Za-z]{3,9})[-./',]*(\d{2,4})[.,]?$")
_MON_DAY_YR = re.compile(r"^([A-Za-z]{3,9})[-./'\s]?(\d{1,2})(?:st|nd|rd|th)?[,.'\-/]+(\d{2,4})[.,]?$")
_DAY_YR = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[,.'\-/]+(\d{2,4})[.,]?$")
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


@lru_cache(maxsize=500_000)
def _ratio(a: str, b: str) -> float:
    """``SequenceMatcher(None, a, b).ratio()``, cached: a results page compares the same lexicon tokens with the
    same label words thousands of times (3.3 million calls, ~95 % of the comparatives part on a 4,700-page store)."""
    return SequenceMatcher(None, a, b).ratio()


def _ratio_cap(a: str, b: str) -> float:
    """The highest ratio two strings of these lengths can reach (``2 * shorter / (a + b)``), checked before
    ``_ratio`` so a pair that cannot beat the current best is never compared; the result is unchanged."""
    total = len(a) + len(b)
    return 2.0 * min(len(a), len(b)) / total if total else 1.0


def _fuzzy_score(pattern: str, label: str) -> tuple[float, int]:
    """Every token of the pattern matched by a distinct label token in the same order (``tot il`` -> ``total``).

    Returns ``(score, first matched label token)`` so a wrapped label can require the match to start in its own
    first line (T-208 round 3).  A long word skipped between two matched words makes the label a different line:
    ``Other comprehensive income`` is not ``other income``, while an OCR split (``bef ore``) still matches."""
    want, have = pattern.split(), label.split()
    if len(want) < 2:
        return 0.0, 0
    total, last, first, used = 0.0, -1, None, []
    for token in want:
        best, at = 0.0, None
        for i in range(last + 1, len(have)):
            if _ratio_cap(token, have[i]) <= max(best, 0.7399):
                continue                        # cannot pass 0.74 nor beat the best: same answer, no compare
            score = _ratio(token, have[i])
            if score > best:
                best, at = score, i
        if at is None or best < 0.74:
            return 0.0, 0
        last = at
        first = at if first is None else first
        used.append(at)
        total += best
    if first is not None and (last - first + 1) > len(want) + 1:   # a couple of words apart at most
        return 0.0, 0
    skipped = [have[i] for i in range(first or 0, last + 1) if i not in used]
    if skipped and len(want) < 3 and any(len(word) > 3 and word.isalpha() for word in skipped):
        return 0.0, 0                  # a word inside a two-token phrase is a different line: "other comprehensive
    return total / len(want), (first or 0)   # income" is not "other income"; "tol 11 expenses" is OCR noise


def _prefix_score(pattern: str, label: str) -> float:
    """An OCR-truncated label that prints only the start of a pattern: ``Revenue fro`` -> ``revenue from operations``.

    Only the printed tokens are scored, one small penalty per pattern token the scan lost, so the full phrase always
    beats a truncation of it.  The value it carries is still stored only when the page's arithmetic confirms it."""
    want, have = pattern.split(), label.split()
    if len(have) < 2 or len(have) > len(want) or len(want) - len(have) > 2:
        return 0.0
    total = 0.0
    for token, printed in zip(want, have):
        score = _ratio(token, printed)
        if score < 0.74:
            return 0.0
        total += score
    return total / len(have) * (1.0 - 0.1 * (len(want) - len(have)))


def match_line(label: str, anchor: int | None = None, prefix_ok: bool = False) -> str | None:
    """Canonical line item for a printed label, or None.  The most specific pattern wins: more matched tokens
    first (``total revenue from operalions`` -> ``revenue_from_operations``, not ``total_income``), then an
    exact phrase, then OCR-tolerant token similarity.  A percentage or margin row never maps (KEC's
    ``Operating Margin excluding exceptional item (%)`` is not the exceptional-items rupee line).

    ``anchor`` (T-208 round 3): the deepest label token a match may start at.  A wrapped label is matched with
    ``anchor=2`` so its continuation line alone ("... exceptional items and tax" under "Profit before share in net
    profit of joint venture,") cannot name the row.  ``prefix_ok`` lets an OCR-truncated label match the start of a
    pattern; its figure is kept only when the page's arithmetic confirms it."""
    low = (label or "").lower()
    if _PCT_LABEL.search(low):
        return None
    if _DISCONTINUED_LABEL.search(low) and "continuing" not in low:
        return None
    text = _norm(label)
    if not text:
        return None
    words = text.split()
    best, found = 0.0, None
    for pattern, item in lexicon():
        tokens = pattern.split()
        start = 0
        if len(tokens) == 1:
            if pattern in words:
                score = 1.0
                start = words.index(pattern)
            elif len(pattern) >= 4:      # an OCR-mangled single word still matches ("Baic" -> basic)
                ratio, at = 0.0, 0
                for i, word in enumerate(words):
                    if len(word) >= 4:
                        got = _ratio(pattern, word)
                        if got > ratio:
                            ratio, at = got, i
                score = ratio if ratio >= 0.78 else 0.0
                start = at
            else:
                score = 0.0
        elif pattern in text:
            score = 1.02
            start = len(text[: text.find(pattern)].split())
        else:
            score, start = _fuzzy_score(pattern, text)
            if score < 0.8 and prefix_ok:
                score, start = _prefix_score(pattern, text), 0
            if score < 0.8:
                continue
        if anchor is not None and start > anchor:
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
        m = re.search(r"[.,](\d+)$", (text or "").strip().strip("()"))
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
    if text.startswith(","):
        return None                     # leading comma is OCR-truncated digits (',036.28' for '7,036.28')
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


def _quarter(period_end: str, ptype: str) -> tuple[str, str, str] | None:
    """``(fiscal_period, period_start, period_type)`` for a printed column, or None when invalid."""
    y, m = int(period_end[:4]), int(period_end[5:7])
    fy = y + 1 if m >= 4 else y
    if ptype == "fy":
        return f"FY{str(fy)[2:]}", f"{fy - 1}-04-01", "fy"
    if ptype == "ytd":
        if m not in (9, 12):
            return None
        label = "H1" if m == 9 else "9M"
        return f"{label}FY{str(fy)[2:]}", f"{fy - 1}-04-01", "ytd"
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(m)
    start = {6: f"{y}-04-01", 9: f"{y}-07-01", 12: f"{y}-10-01", 3: f"{y}-01-01"}.get(m, f"{y}-01-01")
    return f"Q{q or '?'}FY{str(fy)[2:]}", start, "quarter"


def _role_set(end: str, count: int) -> list[str | None]:
    """Positions a results table of this quarter and column count prints them in.

    The pool has to contain the roles the layout can print: a Q1 (June-end) table has no March-FY year-to-date
    columns (``current, preceding, year_ago, last_fy``; five- or six-column June layouts -- including a
    December-year six-month pair or a five-column Q1 + two-year table -- leave non-March year-to-date slots as
    ``None`` so no June-end YTD row is ever stored, and an eight-column side-by-side Q1 table reads its first
    four columns only); a Q2/Q3 table carries a quarter pair, a half/nine-month pair and (with five or six
    columns) the last full year; a Q4 table carries the quarter pair and the two full years.  Without ``last_fy``
    in the pool no TTM can ever be formed from that filing (T-073)."""
    m = int(end[5:7])
    if m == 6:
        if count <= 3:
            return list(ROLE_ORDER[:count])
        if count == 4 or count >= 7:
            return ["current", "preceding", "year_ago", "last_fy"]
        if count == 5:
            return ["current", "preceding", "year_ago", None, "last_fy"]
        return ["current", "preceding", "year_ago", None, None, "last_fy"]
    if count == 6:
        return ["current", "preceding", "year_ago", "ytd", "prior_ytd", "last_fy"]
    if count == 5:
        if m == 3:
            return ["current", "preceding", "year_ago", "ytd", "prior_ytd"]
        if m in (9, 12):
            return ["current", "year_ago", "ytd", "prior_ytd", "last_fy"]
        return list(ROLE_ORDER[:5])
    if count == 4:
        if m == 3:
            return ["current", "preceding", "ytd", "prior_ytd"]
        if m in (9, 12):
            return ["current", "year_ago", "ytd", "prior_ytd"]
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


def _date_match(got: tuple | None, want: tuple, *, require_year: bool = False) -> bool:
    if not got:
        return False
    gm, gy = got
    wm, wy = want
    if gm is not None and gm != wm:
        return False
    if gy is not None and gy != wy:
        return False
    if require_year and gy is None:
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
                          "year": year, "x": word[0]})
            pending = None
            continue
        dmy = _DAY_MON_YR.match(text)
        if dmy:
            day, mon, yr = int(dmy[1]), _month(dmy[2]), int(dmy[3])
            if mon and 1 <= day <= 31 and (len(dmy[3]) == 2 or 1900 <= yr <= 2099):
                cells.append({"month": mon, "day": day, "year": yr + 2000 if yr < 100 else yr, "x": word[0]})
                pending = None
                continue
        mdy = _MON_DAY_YR.match(text)
        if mdy:
            mon, day, yr = _month(mdy[1]), int(mdy[2]), int(mdy[3])
            if mon and 1 <= day <= 31 and (len(mdy[3]) == 2 or 1900 <= yr <= 2099):
                cells.append({"month": mon, "day": day, "year": yr + 2000 if yr < 100 else yr, "x": word[0]})
                pending = None
                continue
        if pending is not None and pending["day"] is None and pending["year"] is None:
            dy = _DAY_YR.match(text)
            if dy:
                day, yr = int(dy[1]), int(dy[2])
                if 1 <= day <= 31 and (len(dy[2]) == 2 or 1900 <= yr <= 2099):
                    pending["day"] = day
                    pending["year"] = yr + 2000 if yr < 100 else yr
                    continue
        joined = re.match(r"^([A-Za-z]{3,9})(\d{1,2})[.,]?$", text)
        month = _month(joined[1] if joined else re.sub(r"[^a-z]", "", low))
        if joined and month:
            day = int(joined[2])
            cells.append({"month": month, "day": day if 1 <= day <= 31 else None, "year": None, "x": word[0]})
            pending = None
            continue
        if month:
            pending = {"month": month, "day": None, "year": None, "x": word[0]}
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
                cells.append({"month": None, "day": None, "year": int(text), "x": word[0]})
    return cells


def _pair_header_years(cells: list[dict], header_rows, at: int, count: int) -> list[tuple]:
    for other in header_rows[at + 1:at + 3] + header_rows[max(0, at - 2):at]:
        years = [int(w[4].strip()) for w in other if _YEAR.match(w[4].strip())]
        if len(years) == count:
            for cell, year in zip(cells, years):
                if cell["year"] is None:
                    cell["year"] = year
            break
        missing = [cell for cell in cells if cell["year"] is None]
        if missing and len(years) == len(missing):
            for cell, year in zip(missing, years):
                cell["year"] = year
            break
    return [(c["month"], c["year"]) for c in cells]


def _header_dates(header_rows, count: int) -> list[tuple] | None:
    """One ``(month, year)`` per column: the row with ``count`` date cells, then the year row beside it."""
    for i, row in enumerate(header_rows):
        cells = _header_cells(row)
        if len(cells) != count:
            continue
        if any(c["month"] is not None or c["year"] is not None for c in cells):
            return _pair_header_years(cells, header_rows, i, count)
    if count >= 4:
        for i, row in enumerate(header_rows):
            cells = _header_cells(row)
            if len(cells) != count - 1 or not any(c["month"] is not None or c["year"] is not None for c in cells):
                continue
            adj = header_rows[max(0, i - 1):i] + header_rows[i + 1:i + 2]
            extra = [c for r in adj for c in _header_cells(r) if c["month"] is not None]
            if len(extra) == 1:
                merged = sorted(cells + extra, key=lambda c: c["x"])
                return _pair_header_years(merged, header_rows, i, count)
    return None


# ------------------------------------------------------------------ page reading ----------------------------------------------------------
def _unit(text: str) -> float | None:
    """Rupee scale from the page's unit words (crore/lakh/million/thousand), None when the page prints none.

    Tolerant to OCR and spacing: ``Rs. inCrore``, ``(tin crore)``, ``(f in Million)`` and ``llNR crore`` all read."""
    match = _UNIT_DECLARED.search(text.lower())
    return _UNIT_SCALES[(match[1] or match[2])[:4]] if match else None


# A page DECLARES its unit as "in <unit>" or as the currency followed at once by the unit ("Rs. Crore").  A unit word
# after a figure is a sentence of the notes ("a provision of Rs. 20 crore"), not the table's unit: store-repair note
# R-006, where such a note on a lakh page had every figure of three results filings stored 100 times too large.
_UNIT_DECLARED = re.compile(r"in\s*(crore|lakh|lac|million|thousand|billion)"
                            # a scan prints "in" as "on" / "rn": up to three letters, never a digit, before the unit
                            r"|(?:rs\.?|inr|nr|₹|`)\s*\(?\s*[a-z]{0,3}\s*(crore|lakh|lac|million|thousand|billion)")
_UNIT_SCALES = {"cror": 1e7, "lakh": 1e5, "lac": 1e5, "mill": 1e6, "thou": 1e3, "bill": 1e9}


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
    """Every number token of a row to its own column, keeping the row's left-to-right order.

    The matching is monotone: when a cell in the middle is missing or two words merge into one number, a later
    token must not slide one column left (T-073: INFY's ``19.32 19.19 17.76 38.51 34.47 71.58`` row, with the
    Q1 cell split by OCR, put the half-year EPS under the year-ago quarter).  A token and a column that are too
    far apart never match."""
    gap = min((b - a for a, b in zip(anchors, anchors[1:])), default=40.0)
    tol = max(6.0, 0.45 * gap)
    tokens = _tokens(_strip_row_number(row))
    n, k = len(anchors), len(tokens)
    if not n or not k:
        return {}
    best = [[0.0] * (k + 1) for _ in range(n + 1)]
    back: list[list[tuple | None]] = [[None] * (k + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, k + 1):
            best[i][j], back[i][j] = best[i - 1][j], ("col", i - 1, j)
            d = abs(anchors[i - 1] - tokens[j - 1]["x1"])
            gain = 10.0 - d / max(tol, 1e-9)         # a match always beats leaving the token out; closer is better
            if d <= tol and best[i - 1][j - 1] + gain > best[i][j]:
                best[i][j], back[i][j] = best[i - 1][j - 1] + gain, ("take", i - 1, j - 1)
            if best[i][j - 1] > best[i][j]:                       # a token no column takes
                best[i][j], back[i][j] = best[i][j - 1], ("token", i, j - 1)
    out: dict[int, dict] = {}
    i, j = n, k
    while i > 0 and j > 0:
        step = back[i][j]
        if step is None:
            break
        kind, ni, nj = step
        if kind == "take":
            out[ni] = tokens[nj]
        i, j = ni, nj
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
    """A Q2/Q3 table that prints a quarter pair AND a half-year pair (``Three months ended … Six months
    ended …``) is ``current, year_ago, ytd, prior_ytd`` plus ``last_fy`` when it also prints the year.  The month
    of the current period end decides the other layouts (`_role_set`): a Q1 table's "year ended" column is the
    last full year, a Q4 table's is the year itself, so the hint never overrides those."""
    if len(anchors) not in (4, 5):
        return None
    text = " ".join(w[4] for row in header_rows for w in row).lower().replace("-", " ")
    if "six months" in text or "nine months" in text or "half year" in text:
        return ["current", "year_ago", "ytd", "prior_ytd", "last_fy"][:len(anchors)]
    return None


def _continues(previous: str, label: str) -> bool:
    """Does ``label`` continue the label line ``previous``?  A wrapped label's second line starts mid-phrase: a
    lower-case word (``and tax``, ``exceptional items and tax``) after a line that ends mid-sentence.  A
    capitalised line is a new heading -- "Other comprehensive income/(expense)" is a section, not the first line of
    the row that follows it -- and so is a numbered row printed under a heading ending with a comma."""
    first = (label.split() or [""])[0]
    if not first:
        return False
    if first in ("and", "or", "of"):
        return True
    return first[0].islower() and previous.rstrip().endswith((",", "and", "or", "of", "the"))


def _data_labels(data_rows) -> list[tuple[str, bool]]:
    """The label of every data row, with a wrapped label line joined to the row it belongs to (T-208 round 3).

    A line that prints no number and that the next numbered row continues (``_continues``) is the first line of
    that row's label: p9 of a results PDF prints ``Profit before share in net profit /(loss) of joint venture,``
    and only then ``exceptional items and tax (1-2) 3,511 ...``.  Matching the continuation alone named the row
    ``exceptional_items``; the joined label is matched with ``anchor=2`` so a phrase that lives only in the
    continuation cannot name the row."""
    out: list[tuple[str, bool]] = []
    previous_label, previous_numbered = "", True
    for row in data_rows:
        label = _label(row).strip()
        numbered = bool(_tokens(_strip_row_number(row)))
        if numbered and not previous_numbered and _continues(previous_label, label):
            out.append(((previous_label + " " + label).strip(), True))
        else:
            out.append((label, False))
        previous_label, previous_numbered = label, numbered
    return out


def read_page(rows, ocr: bool = False) -> dict | None:
    """A P&L table page rebuilt from word-box ``rows``, or None when the page is not one.

    The page needs a title with "results" (OCR tolerant), no US-dollar unit, no auditor's report, no segment
    heading, a header of period words and at least 8 rows with 3 or more numeric columns; balance sheet, cash
    flow, ratio and segment pages are never read here.  It must carry a P&L shape -- an income line and a
    profit line -- so a notes page whose few matched rows are costs is refused.

    ``ocr`` (T-208 round 3): the rows are OCR words, so a truncated label may match the start of a pattern; the
    figure it carries is stored only when the page's arithmetic confirms it (``_table_rows``)."""
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
        if match_line(_label(row), prefix_ok=ocr):
            first = i
            break
    if first is None:
        return None
    header_rows, data_rows = rows[:first], rows[first:]
    labels = _data_labels(data_rows)
    rows3 = sum(1 for row in data_rows if len(_tokens(_strip_row_number(row))) >= 3)
    if rows3 < 8:
        return None
    anchors = _columns(data_rows)
    if len(anchors) < 3:
        return None
    if _less_before_profit(data_rows):
        return None
    values: dict = defaultdict(lambda: defaultdict(list))
    captions: dict[str, str] = {}
    for index, row in enumerate(data_rows):
        label, joined = labels[index]
        # A printed label names the row only from its own start (a prefix word such as "Net" or "(b)" is allowed,
        # a phrase buried mid-label is not: "Profit/(Loss) after exceptional item and tax from discontinued
        # operations" is not the exceptional-items line; T-208 round 3).
        item = match_line(label, anchor=2, prefix_ok=ocr)
        if item is None:
            continue
        cells = _assign_tokens(row, anchors)
        if len(cells) < 2:          # a badly scanned table keeps a row whose cells partly print (MARUTI)
            continue
        captions.setdefault(item, label.strip())
        quote = " ".join(w[4] for w in row)
        for at, token in cells.items():
            token["quote"] = quote
            token["row"] = index
            token["label"] = label
            values[at][item].append(token)
    if not values or not _pl_shape(values, rows3):
        return None
    decimals = _decimals([t["text"] for col in values.values() for tokens in col.values() for t in tokens])
    return {"anchors": anchors, "dates": _header_dates(header_rows, len(anchors)), "values": values,
            "labels": captions, "text": text, "head": head, "header_rows": header_rows[:12],
            "decimals": decimals, "scale": _unit(text), "hint": _layout_hint(header_rows, anchors)}


# ------------------------------------------------------------------ XBRL side -------------------------------------------------------------
class _XbrlIndex(defaultdict):
    """``{(basis, period_end): {item: value}}`` tracking keys present ONLY in ``fin_quarter_xbrl_input``."""

    def __init__(self) -> None:
        super().__init__(dict)
        self.input_only: set[tuple[str, str, str]] = set()


def xbrl_index(conn: sqlite3.Connection, symbol: str) -> dict:
    """``{(basis, period_end): {item: value}}`` for the symbol's XBRL quarters.

    With a ``compute_start`` the quarters before the window live in ``fin_quarter_xbrl_input``; they are inputs
    only, but a printed prior-year column is checked against them (T-073).  The main table wins when both hold a
    quarter."""
    values = _XbrlIndex()
    tables = (["fin_quarter_xbrl_input"] if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='fin_quarter_xbrl_input'").fetchone() else []) + ["fin_quarter_xbrl"]
    for table in tables:
        for basis, end, item, value in conn.execute(
                f"SELECT basis, period_end, line_item, value FROM {table} "
                "WHERE symbol=? AND basis IN ('standalone','consolidated')", (symbol,)):
            values[(basis, end)][item] = value
            if table == "fin_quarter_xbrl_input":
                values.input_only.add((basis, end, item))
            else:
                values.input_only.discard((basis, end, item))
    return values


def annual_facts_index(conn: sqlite3.Connection, symbol: str) -> dict[tuple[str, str], dict[str, list[float]]]:
    """``{(basis, period_end): {item: [value, ...]}}`` from ``fin_annual_line`` (``source_table='facts'``)."""
    values: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='fin_annual_line'").fetchone():
        return values
    vocab = {item for _pattern, item in lexicon()}
    for basis, end, item, value in conn.execute(
            "SELECT basis, period_end, line_item, value FROM fin_annual_line "
            "WHERE source_table='facts' AND symbol=? AND value IS NOT NULL", (symbol,)):
        if item in vocab and basis in ("standalone", "consolidated") and end:
            values[(basis, end)][item].append(float(value))
    return values


def _close(got: float, want: float, tol: float) -> bool:
    return abs(got - want) <= tol


_BASIS_SPACE = (
    ("standalone", re.compile(r"\bstand\s*a\s*lon\w*")),
    ("consolidated", re.compile(r"\bcon\s*solidat\w*")),
)
_BASIS_SPLIT = (
    ("standalone", re.compile(r"\bstand\s*[-\s]*a\s*-?\s*lon\w*")),
    ("consolidated", re.compile(r"\bcon\s*[-\s]*solidat\w*")),
)


def _basis_positions(text: str, *, allow_hyphen: bool = False) -> dict[str, int]:
    """First offset of ``standalone`` and ``consolidated`` in ``text``, space-split and OCR tolerant."""
    low = (text or "").lower()
    found: dict[str, int] = {}
    for name, pat in (_BASIS_SPLIT if allow_hyphen else _BASIS_SPACE):
        at = low.find(name)
        if at < 0:
            hit = pat.search(low)
            at = hit.start() if hit else -1
        if at < 0:
            for word in re.findall(r"[a-z]{7,}", low):
                if SequenceMatcher(None, word, name).ratio() >= 0.8:
                    at = low.find(word)
                    break
        if at >= 0:
            found[name] = at
    return found


def _page_basis(text: str, head: str | None = None, *, allow_hyphen: bool = False) -> str | None:
    """Standalone / consolidated from the page title (the head rows), never from a note lower on the page.

    Tolerant to OCR and space-splits: ``Standa lone``, ``ca"nsolidated`` and ``Consolidstcd`` all match."""
    for source in (head, text):
        found = _basis_positions(source or "", allow_hyphen=allow_hyphen)
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
    """Basic and diluted EPS ~ pat / shares within 1.5%, when a share count is known."""
    pat = cells.get("pat")
    if not (pat and shares and shares > 0):
        return
    want = pat["value"] / shares
    tol = max(0.015 * abs(want), 0.02)
    for eps_item in ("eps_basic", "eps_diluted"):
        eps = cells.get(eps_item)
        if eps is not None and abs(eps["value"] - want) <= tol:
            eps["ident"] = "sum_ok"


# ------------------------------------------------------------------ extraction ------------------------------------------------------------
def has_table(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone())


def _pdf_candidates(path: Path | str | None, symbol: str) -> list[Path]:
    """Where a ``source_key`` may sit: the stored path, then the profile's raw copy of the same name."""
    if not path:
        return []
    candidates = [Path(path)]
    current = profile.active() if profile.under_profile() else None
    raw_root = getattr(current, "raw_root", None)
    if raw_root:
        candidates.append(Path(raw_root) / symbol / "quarterly_results" / Path(path).name)
    return candidates


def _open_pdf(path: Path | str | None, symbol: str):
    """The PDF at ``path``, opened from a store temp copy when it lives only on Drive (T-102).

    The run's ``prefetch`` keeps that copy on disk until the run ends, so the caller can read every
    page of the document and close it there."""
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    store = raw_store.default_store()
    for candidate in _pdf_candidates(path, symbol):
        if not store.exists(candidate):
            continue
        try:
            with store.local(candidate) as source:
                return fitz.open(str(source))
        except Exception:
            return None
    return None


def _shares(conn, symbol: str, basis: str, day: str) -> float | None:
    row = conn.execute("SELECT shares_outstanding FROM share_capital WHERE symbol=? AND event IS NULL AND basis=? "
                       "AND as_of_date<=? ORDER BY as_of_date DESC, known_at DESC LIMIT 1",
                       (symbol, basis, day)).fetchone()
    return row[0] if row and row[0] else None


def run(conn: sqlite3.Connection, symbols=None, review_path: Path | str | None = None, store_db=None,
        ocr_dbs=()) -> dict:
    """Read every ``results`` document's P&L pages for ``symbols`` and rewrite their ``fin_quarter_printed`` rows.

    ``store_db`` + ``ocr_dbs`` (T-208 round 3): the store whose ``doc`` table names each page's PDF and the OCR
    databases holding its OCR words.  When given, a page whose text layer the label dictionary scores under 0.75
    is read from its OCR words (see ``page_words.words_for``), and those figures are kept only when the page's
    own arithmetic confirms them."""
    schema.ensure(conn, (TABLE,))       # the part's own table: created when absent, never rebuilt here
    want = [s.strip().upper() for s in (symbols or profile.symbols()) if s and s.strip()]
    review: list[dict] = []
    stats: dict = {}
    for symbol in want:
        conn.execute(f"DELETE FROM {TABLE} WHERE symbol=?", (symbol,))
        stats[symbol] = _extract_symbol(conn, symbol, review, store_db=store_db, ocr_dbs=ocr_dbs)
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


def _ocr_page_rows(store_db, doc_key: str, page_no: int, ocr_dbs) -> list | None:
    """The page's OCR word rows when its text layer scores under the label dictionary, else None (T-208 round 3)."""
    if store_db is None:
        return None
    from reality_engine.v2 import page_words

    try:
        got = page_words.words_for(store_db, doc_key, page_no, ocr_dbs)
    except Exception:                      # a store without doc/doc_page must not stop the part
        return None
    if not got.source.startswith("ocr") or not got.words:
        return None
    return rows_from_words(got.words)


def _extract_symbol(conn: sqlite3.Connection, symbol: str, review: list[dict], store_db=None,
                    ocr_dbs=()) -> dict:
    started = time.time()
    isin = conn.execute("SELECT isin FROM company WHERE symbol=? ORDER BY isin_from DESC LIMIT 1", (symbol,)).fetchone()
    isin = isin[0] if isin else None
    xbrl = xbrl_index(conn, symbol)
    annual_facts = annual_facts_index(conn, symbol)
    docs = conn.execute(
        "SELECT doc_key, known_at, source_key, sha256 FROM doc WHERE symbol=? AND doc_type='results' "
        "AND source_key IS NOT NULL AND known_at IS NOT NULL ORDER BY known_at", (symbol,)).fetchall()
    rows: list[tuple] = []
    store_fy: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    disagreed: dict[tuple[str, int, str, str, str], tuple[float, float]] = {}
    layer_pending: set[tuple[str, int, str, str, str]] = set()
    ocr_pending: set[tuple[str, int, str, str, str]] = set()
    seen: set[str] = set()
    duplicates: list[str] = []
    files: list[dict] = []
    tables = pages = missing = 0
    store = raw_store.default_store()
    # One download and one delete for the company's results decks (T-102): they are read inside this scope.
    with store.prefetch([p for _dk, _ka, source_key, _sha in docs
                         for p in _pdf_candidates(source_key, symbol)]):
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
            prev_layer = None
            for page_no in range(1, pdf.page_count + 1):
                entry["pages"] += 1
                pages += 1
                layer_rows = rows_from_words(_page_words(pdf[page_no - 1]))
                word_rows = layer_rows
                table = None
                fill_table = None
                ocr_all = False
                layer_only = False
                ocr_rows = _ocr_page_rows(store_db, doc_key, page_no, ocr_dbs) if ocr_dbs else None
                base = read_page(layer_rows) if (ocr_rows and layer_rows) else None
                if ocr_rows:
                    ocr_table = read_page(ocr_rows, ocr=True)
                    if ocr_table is not None:
                        word_rows, table, fill_table, ocr_all = ocr_rows, ocr_table, base, True
                    elif base is not None:
                        table, layer_only = base, True
                if table is None and layer_rows:
                    table = base if base is not None else read_page(layer_rows)
                if not layer_rows and not ocr_rows:
                    entry["empty_pages"].append(page_no)          # no text layer and no readable OCR
                    previous = None
                    prev_layer = None
                    continue
                if table is None:
                    if ocr_rows:
                        table = _continuation(ocr_rows, previous)
                        if table is not None:
                            word_rows, ocr_all = ocr_rows, True
                            if layer_rows:
                                fill_table = _continuation(layer_rows, prev_layer or previous)
                    if table is None and layer_rows:
                        table = _continuation(layer_rows, prev_layer or previous)
                        if table is not None and ocr_rows:
                            layer_only = True
                if table is None:
                    previous = None
                    prev_layer = None
                    continue
                tables += 1
                entry["tables"] += 1
                prev = previous
                prev_lay = prev_layer
                previous = table
                prev_layer = fill_table if ocr_all else (base or table)
                page_review: list[dict] = []
                new = _table_rows(conn, symbol, isin, doc_key, page_no, known_at, table, xbrl, page_review,
                                  ocr=ocr_all, fill_table=fill_table, store_fy=store_fy, disagreed=disagreed,
                                  layer_only=layer_only, layer_pending=layer_pending,
                                  ocr_pending=ocr_pending, annual_facts=annual_facts)
                if not new and prev is not None:
                    cont = _continuation(ocr_rows if ocr_all else layer_rows, prev)
                    if cont is not None:
                        cont_fill = (_continuation(layer_rows, prev_lay or prev)
                                     if (ocr_all and layer_rows) else None)
                        cont_review: list[dict] = []
                        cont_rows = _table_rows(conn, symbol, isin, doc_key, page_no, known_at, cont, xbrl,
                                                cont_review, ocr=ocr_all, fill_table=cont_fill, store_fy=store_fy,
                                                disagreed=disagreed, layer_only=layer_only,
                                                layer_pending=layer_pending, ocr_pending=ocr_pending,
                                                annual_facts=annual_facts)
                        if cont_rows:
                            table = cont
                            previous = cont
                            prev_layer = cont_fill if ocr_all else cont
                            new = cont_rows
                            page_review = cont_review
                if not new:
                    previous = None
                    prev_layer = None
                review.extend(page_review)
                entry["rows"] += len(new)
                for row in new:
                    entry["basis"][row[7]] = entry["basis"].get(row[7], 0) + 1
                    if row[5] == "fy" and row[20] in CHECK_OK:
                        store_fy[(row[7], row[3])][row[9]].append(row[11])
                rows.extend(new)
            if not entry["rows"] and not entry["reason"]:
                entry["reason"] = "no_pl_table"
            files.append(entry)
            pdf.close()
    rows = _apply_repeats(rows)
    if disagreed:
        swapped = False
        for idx_r, row in enumerate(rows):
            info = disagreed.get((row[16], row[17], row[6], row[7], row[9]))
            if not isinstance(info, dict) or not info.get("alt_row"):
                continue
            if _LADDER.get(row[20], 0) >= 2:
                continue
            if _has_repeat_match(info["alt_row"], rows):
                rows[idx_r] = info["alt_row"]
                swapped = True
        if swapped:
            rows = _apply_repeats(rows)
    if disagreed or layer_pending or ocr_pending:
        kept: list[tuple] = []
        for row in rows:
            key = (row[16], row[17], row[6], row[7], row[9])
            if key in layer_pending and row[20] not in CHECK_OK:
                review.append({"symbol": symbol, "doc_key": row[16], "page": row[17], "line_item": row[9],
                               "column_role": row[6], "raw_token": row[14], "check": "layer_unconfirmed",
                               "detail": ""})
                continue
            if key in ocr_pending and row[20] not in CHECK_OK:
                review.append({"symbol": symbol, "doc_key": row[16], "page": row[17], "line_item": row[9],
                               "column_role": row[6], "raw_token": row[14], "check": "ocr_unreconciled",
                               "detail": f"value={row[11]}"})
                continue
            if key in disagreed and row[20] not in CHECK_OK:
                continue
            kept.append(row)
        rows = kept
    conn.executemany(
        f"INSERT INTO {TABLE} (symbol, isin, period_start, period_end, fiscal_period, period_type, column_role, "
        "basis, statement, line_item, caption, value, unit, scale, raw_token, quote, doc_key, page, known_at, "
        "known_at_source, check_status, check_detail, is_reported) VALUES ("
        + ",".join("?" * 23) + ")", rows)
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
    for i, row in enumerate(data_rows):
        if i > 0 and re.match(r"^notes?\b\s*[:.\-]", _label(row).strip(), re.I):
            data_rows = data_rows[:i]
            break
    anchors = _columns(data_rows)
    if len(anchors) != len(previous["anchors"]) or any(
            abs(a - b) > 10.0 for a, b in zip(anchors, previous["anchors"])):
        return None
    if _less_before_profit(data_rows):
        return None
    table = dict(previous)
    table["values"] = defaultdict(lambda: defaultdict(list))
    table["labels"] = {}
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
    cont_only = set(_PL_BOTTOM) | {"other_comprehensive_income", "paid_up_capital", "tax", "current_tax", "deferred_tax"}
    if not (set(table["labels"]) & set(previous["labels"])) and not (set(table["labels"]) <= cont_only):
        return None                      # no line item in common and not the bottom-of-P&L continuation
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


class _HalfValues(defaultdict):
    """Column map of one half of a side-by-side S/C table: carries the whole table's EPS decimals, because one
    half may print EPS with its points lost ('213 181') while the other keeps them ('2.15 1.90')."""
    eps_decimals: int | None = None


def _eps_decimals(values: dict) -> int:
    """Decimal places the table prints EPS to (the majority length of its last separator); a dash-printed
    zero keeps that count, so a 0 against an XBRL 0.11 is not inside 2 units of the last printed decimal.
    A side-by-side half (``_HalfValues``) answers with the whole table's count at every call site."""
    fixed = getattr(values, "eps_decimals", None)
    if fixed is not None:
        return fixed
    votes: dict[int, int] = defaultdict(int)
    for col in values.values():
        for item, tokens in col.items():
            if not item.startswith("eps_"):
                continue
            for token in tokens:
                m = re.search(r"[.,](\d{1,2})[.,]?$", token["text"].strip().strip("()"))
                if m:
                    votes[len(m[1])] += 1
    return max(votes, key=lambda key: (votes[key], key)) if votes else 0


def _resolve_eps_decimals(values: dict, roles: list, end: str, xbrl: dict, basis: str, scale: float,
                          decimals: int, annual_facts: dict | None = None) -> int:
    """Use the table's EPS decimal count, falling back to XBRL-confirmed 2 decimals when all EPS points were dropped."""
    eps_dec = _eps_decimals(values)
    if eps_dec or not xbrl or basis not in ("standalone", "consolidated"):
        return eps_dec
    if any(re.search(r"[.,](\d{1,2})[.,]?$", token["text"].strip().strip("()"))
           for col in values.values() for item, tokens in col.items()
           if item.startswith("eps_") for token in tokens):
        return 0

    def _hits(candidate_dec: int) -> int:
        hits = 0
        for at, role in enumerate(roles):
            if not role:
                continue
            period_end, ptype = _role_period(role, end)
            for item, tokens in values.get(at, {}).items():
                if not item.startswith("eps_"):
                    continue
                for token in tokens:
                    parsed = _parse_cell(item, token["text"], decimals, candidate_dec)
                    if parsed is not None and _xbrl_ok(
                        xbrl, basis, period_end, item, parsed[0],
                        _tol(item, decimals, scale, token["text"], candidate_dec),
                        ptype=ptype, annual_facts=annual_facts,
                    ):
                        hits += 1
                        break
        return hits

    return 2 if _hits(2) > _hits(0) else 0


def _tol(item: str, decimals: int, scale: float, text: str | None = None,
         eps_decimals: int | None = None) -> float:
    """2 units of the last printed decimal: rupees of the table's scale for a rupee line, its OWN printed
    decimals for a per-share line (never scaled -- a crore-scaled EPS tolerance would accept any value)."""
    if item.startswith("eps_") or item.endswith("_per_share"):
        digits = eps_decimals
        if digits is None:
            digits = 0
            if text:
                m = re.search(r"[.,](\d{1,2})[.,]?$", text.strip().strip("()"))
                digits = len(m[1]) if m else 0
        return 2.0 / (10.0 ** digits)
    return 2.0 / (10.0 ** decimals) * scale


def _row_label(values: dict, item: str, row: int) -> str:
    for col in values.values():
        for token in col.get(item, []):
            if token["row"] == row:
                return _norm(token.get("label", ""))
    return ""


def _col_item_values(col_values: dict, name: str, decimals: int, eps_decimals: int, scale: float) -> list[float]:
    """Parsed rupee values for ``name`` in one raw column, deriving ``tax = current_tax + deferred_tax`` if absent."""
    tokens = col_values.get(name, [])
    out: list[float] = []
    for t in tokens:
        parsed = _parse_cell(name, t["text"], decimals, eps_decimals)
        if parsed is not None:
            out.append(parsed[0] * (1.0 if name.startswith("eps_") else scale))
    if not out and name == "tax" and "current_tax" in col_values and "deferred_tax" in col_values:
        curs = _col_item_values(col_values, "current_tax", decimals, eps_decimals, scale)
        dfrs = _col_item_values(col_values, "deferred_tax", decimals, eps_decimals, scale)
        if curs and dfrs:
            out.append(curs[0] + dfrs[0])
    return out


def _row_ident_hits(item: str, val_by_col: dict[int, float], values: dict, roles: list,
                    decimals: int, eps_decimals: int, scale: float, tol: float) -> int:
    """Count column arithmetic identities satisfied by placing ``val_by_col[at]`` for ``item``."""
    hits = 0
    for at, val in val_by_col.items():
        col_values = values.get(at, {})
        identities = _BANK_IDENTITIES if ("interest_income" in col_values or "operating_profit" in col_values) else _IDENTITIES
        matched = False
        for target, inputs in identities:
            in_names = [n for n, _s in inputs]
            if item == target:
                choices = [_col_item_values(col_values, n, decimals, eps_decimals, scale) for n in in_names]
                if all(choices):
                    for combo in itertools.product(*choices):
                        if _close(sum(v * s for v, (_n, s) in zip(combo, inputs)), val, tol):
                            matched = True
                            break
            elif item in in_names:
                targets = _col_item_values(col_values, target, decimals, eps_decimals, scale)
                choices = [[val] if n == item else _col_item_values(col_values, n, decimals, eps_decimals, scale)
                           for n in in_names]
                if targets and all(choices):
                    for tv in targets:
                        if any(_close(sum(v * s for v, (_n, s) in zip(combo, inputs)), tv, tol)
                               for combo in itertools.product(*choices)):
                            matched = True
                            break
            if matched:
                hits += 1
                break
    return hits


def _choose_rows(values: dict, roles: list, end: str, xbrl: dict, basis: str, scale: float, decimals: int,
                 tol: float, eps_decimals: int = 0, annual_facts: dict | None = None) -> dict:
    """One printed row per line item: score across all XBRL-backed columns (most XBRL matches, fewest conflicts,
    ``current`` match, smallest diff), then ``Total`` label for totals when no XBRL matches, then column
    arithmetic, readable cells, and earliest row."""
    role_slots = [(at, role, *_role_period(role, end)) for at, role in enumerate(roles) if role]
    chosen: dict = {}
    for item in {name for col in values.values() for name in col}:
        rows_present = sorted({t["row"] for col in values.values() for t in col.get(item, [])})
        if len(rows_present) <= 1:
            chosen[item] = rows_present[0] if rows_present else None
            continue
        best_key = None
        best = rows_present[0]
        for row in rows_present:
            xbrl_matches = 0
            xbrl_conflicts = 0
            cur_match = 0
            total_diff = 0.0
            val_by_col: dict[int, float] = {}
            for at, role, period_end, ptype in role_slots:
                token = next((t for t in values.get(at, {}).get(item, []) if t["row"] == row), None)
                if token is None:
                    continue
                parsed = _parse_cell(item, token["text"], decimals, eps_decimals)
                if parsed is None:
                    continue
                val = parsed[0] * (1.0 if item.startswith("eps_") else scale)
                val_by_col[at] = val
                matched_diff, conflict = _xbrl_conflict(
                    xbrl, basis, period_end, item, val,
                    _tol(item, decimals, scale, token["text"], eps_decimals),
                    ptype=ptype, annual_facts=annual_facts,
                )
                if matched_diff is not None:
                    xbrl_matches += 1
                    total_diff += matched_diff
                    if role == "current":
                        cur_match = 1
                elif conflict is not None:
                    xbrl_conflicts += 1
            total_pref = 1 if (xbrl_matches == 0 and item in _TOTAL_ITEMS
                               and _row_label(values, item, row).startswith("total")) else 0
            ident_hits = _row_ident_hits(item, val_by_col, values, roles, decimals, eps_decimals, scale, tol)
            key = (xbrl_matches, -xbrl_conflicts, cur_match, -round(total_diff, 6),
                   total_pref, ident_hits, len(val_by_col), -row)
            if best_key is None or key > best_key:
                best_key = key
                best = row
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
    text = re.sub(r"\s+", "", raw or "").strip("()")
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
    its own ``known_at``: the filing date is still what a past date may see, even though its agreement came later.
    Rows with ``xbrl_conflict`` in ``check_detail`` never receive ``repeat_ok`` (XBRL outranks repetition)."""
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
            if row[20] != "unchecked" or (row[21] and "xbrl_conflict" in row[21]):
                continue
            tol_i = _printed_tolerance(row[14], row[11])
            for j in idxs:
                if j == i or out[j][18][:10] == row[18][:10]:
                    continue
                if out[j][21] and "xbrl_conflict" in out[j][21]:
                    continue
                tol_j = _printed_tolerance(out[j][14], out[j][11])
                tol = max((t for t in (tol_i, tol_j) if t is not None), default=0.0)
                if abs(row[11] - out[j][11]) <= tol + 1e-9:
                    detail = f"repeat of {out[j][18][:10]}"
                    out[i] = row[:20] + ("repeat_ok", (detail + "; " + row[21]) if row[21] else detail) + row[22:]
                    marked += 1
                    break
    return out


def _has_repeat_match(alt: tuple, rows: list[tuple]) -> bool:
    """True when ``alt`` matches a row from a DIFFERENT filing date on ``(symbol, basis, period_end, period_type, item)``."""
    if alt[21] and "xbrl_conflict" in alt[21]:
        return False
    key = (alt[0], alt[7], alt[3], alt[5], alt[9])
    tol_a = _printed_tolerance(alt[14], alt[11])
    for other in rows:
        if (other[0], other[7], other[3], other[5], other[9]) != key or other[18][:10] == alt[18][:10]:
            continue
        if other[21] and "xbrl_conflict" in other[21]:
            continue
        tol_b = _printed_tolerance(other[14], other[11])
        tol = max((t for t in (tol_a, tol_b) if t is not None), default=0.0)
        if abs(alt[11] - other[11]) <= tol + 1e-9:
            return True
    return False


def _debit_costs(columns: dict) -> bool | None:
    """A cost line printed in brackets means the table is not the P&L (a segment reconciliation); only a table
    where EVERY cost line prints in brackets by convention may stand, with the magnitudes read positive, or a
    mixed table whose ``total_expenses`` is non-negative (e.g. a single negative expense credit/reversal).
    Returns True when all costs were negated, False when no cost is negative (or mixed with non-negative
    total_expenses), None when ``total_expenses`` itself prints negative in a mixed table."""
    cells = [(item, cell) for col in columns.values() for item, cell in col.items() if item in _COST_ITEMS]
    negative = [(item, cell) for item, cell in cells if cell["value"] < 0]
    if not negative:
        return False
    if len(negative) == len(cells):
        for _item, cell in negative:
            cell["value"] = -cell["value"]
            cell["bracketed"] = True
        return True
    if any(item == "total_expenses" for item, _cell in negative):
        return None
    return False


def _derive_tax(columns: dict) -> None:
    """Where only the current and deferred components print, the total is their sum, ``is_reported`` 0."""
    for cells in columns.values():
        if "tax" in cells or "current_tax" not in cells or "deferred_tax" not in cells:
            continue
        cur, dfr = cells["current_tax"], cells["deferred_tax"]
        tax = {"value": cur["value"] + dfr["value"], "raw": f"{cur['raw']} {dfr['raw']}",
               "repaired": False, "caption": f"{cur['caption']} + {dfr['caption']}",
               "quote": f"{cur['quote']} | {dfr['quote']}", "item": "tax", "row": None, "derived": True}
        if cur.get("src") == "layer" or dfr.get("src") == "layer":
            tax["src"] = "layer"
        elif (cur.get("ocr") and not cur.get("agreed")) or (dfr.get("ocr") and not dfr.get("agreed")):
            tax["ocr"] = True
        elif cur.get("agreed") and dfr.get("agreed"):
            tax["agreed"] = True
        cells["tax"] = tax


def _parsed_cells(values, roles, chosen, decimals, eps_dec, scale, captions, review, symbol, doc_key, page_no,
                  ocr: bool = False) -> dict[str, dict]:
    """The parsed cells of one table, one per (column role, line item); ``ocr`` marks a cell read from OCR words."""
    columns: dict[str, dict] = {}
    for at, role in enumerate(roles):
        if role is None:
            continue
        cells: dict = {}
        for item, tokens in values.get(at, {}).items():
            if item == "face_value":
                continue
            best = next((t for t in tokens if t["row"] == chosen.get(item)), tokens[0])
            parsed = _parse_cell(item, best["text"], decimals, eps_dec)
            if parsed is None:
                review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": item,
                               "column_role": role, "raw_token": best["raw"], "check": "unreadable", "detail": ""})
                continue
            cell = {"value": parsed[0] * (1.0 if item.startswith("eps_") else scale),
                    "raw": best["raw"], "repaired": parsed[1], "caption": captions.get(item, ""),
                    "quote": best["quote"], "item": item, "row": best["row"]}
            if ocr:
                cell["ocr"] = True
            cells[item] = cell
        columns[role] = cells
    return columns


def _apply_cell_xbrl_status(cell: dict, xbrl: dict, basis: str, period_end: str, item: str,
                            decimals: int, scale: float, eps_dec: int, ptype: str,
                            annual_facts: dict | None = None) -> None:
    """Resolve one cell's confirmation status against XBRL.

    Pre-window ``fin_quarter_xbrl_input`` entries confirm matching figures (``xbrl_ok``) and block unconfirmed
    ``repeat_ok`` guesses, but never override a self-consistent comparative column whose own page arithmetic
    confirmed ``sum_ok`` when ``fin_quarter_xbrl`` holds no row for that quarter."""
    matched_diff, conflict = _xbrl_conflict(
        xbrl, basis, period_end, item, cell["value"],
        _tol(item, decimals, scale, cell["raw"], eps_dec),
        ptype=ptype, annual_facts=annual_facts)
    if matched_diff is not None:
        cell["status"] = "xbrl_ok"
        cell.pop("xbrl_conflict", None)
    elif conflict is not None and not (
        cell.get("ident") == "sum_ok"
        and ptype == "quarter"
        and (basis, period_end, item) in getattr(xbrl, "input_only", ())
    ):
        cell["status"] = "unchecked"
        cell["xbrl_conflict"] = conflict
    else:
        cell["status"] = cell.get("ident", "unchecked")
        cell.pop("xbrl_conflict", None)


def _assign_status(columns, end: str, xbrl: dict, basis: str, decimals: int, scale: float,
                   eps_dec: int, annual_facts: dict | None = None) -> None:
    """Set every cell's status: XBRL outranks arithmetic and repetition (match -> ``xbrl_ok``; mismatch against a held
    XBRL figure -> ``unchecked`` with ``xbrl_conflict``; otherwise ``sum_ok`` or ``unchecked``)."""
    for role, cells in columns.items():
        period_end, ptype = _role_period(role, end)
        for item, cell in cells.items():
            if item == "_fails":
                continue
            _apply_cell_xbrl_status(cell, xbrl, basis, period_end, item, decimals, scale, eps_dec, ptype, annual_facts)
            cell["period_end"], cell["ptype"] = period_end, ptype


def _derive_revenue(columns) -> None:
    """No row prints revenue, total income - other income does (HINDUNILVR); never for a bank or an insurer, whose
    "revenue" is interest income / net premium and has its own row."""
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


def _cross_column_marks(columns, end: str, rupee_tol: float) -> None:
    """Across columns on a Q2 table: current + preceding = ytd marks every cell of the identity ``sum_ok``."""
    if end[5:7] != "09" or not {"ytd", "current", "preceding"} <= set(columns):
        return
    for item in (set(columns["current"]) & set(columns["preceding"]) & set(columns["ytd"])) - {"_fails"}:
        cur, pre, ytd = columns["current"][item], columns["preceding"][item], columns["ytd"][item]
        ok = abs(cur["value"] + pre["value"] - ytd["value"]) <= (0.02 if item.startswith("eps_") else rupee_tol)
        if ok:
            for cell in (cur, pre, ytd):
                cell.setdefault("ident", "sum_ok")


def _ambiguous_items(values: dict) -> set[str]:
    values_by_item: dict = {}
    for col in values.values():
        for item, tokens in col.items():
            values_by_item.setdefault(item, set()).update(t["row"] for t in tokens)
    return {item for item, rows in values_by_item.items() if len(rows) > 1}


def _resolve_columns(columns: dict[str, dict], end: str, rupee_tol: float, ambiguous: set[str],
                     shares: float | None, xbrl: dict, basis: str, decimals: int, scale: float,
                     eps_dec: int, bracketed: bool, review: list[dict], symbol: str, doc_key: str,
                     page_no: int, *, drop_ocr_unreconciled: bool, log_review: bool,
                     recheck_after_revenue: bool = True, annual_facts: dict | None = None) -> dict[str, dict] | None:
    """Run P&L identities, cross-column marks, XBRL checks, and derived tax/revenue on one column set."""
    _derive_tax(columns)
    for cells in columns.values():
        cells["_fails"] = _check_column(cells, rupee_tol, ambiguous)
        _eps_ok(cells, shares)
    if bracketed and not any(isinstance(cell, dict) and cell.get("ident") == "sum_ok"
                             for cells in columns.values() for cell in cells.values()):
        _assign_status(columns, end, xbrl, basis, decimals, scale, eps_dec, annual_facts=annual_facts)
        kept_xbrl = {
            role: {k: v for k, v in cells.items() if isinstance(v, dict) and v.get("status") == "xbrl_ok"}
            for role, cells in columns.items()
        }
        if any(kept_xbrl.values()):
            return kept_xbrl
        if log_review:
            review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": None,
                           "column_role": None, "raw_token": None, "check": "not_pl_costs",
                           "detail": "every cost in brackets but no identity holds"})
        return None
    _cross_column_marks(columns, end, rupee_tol)
    _assign_status(columns, end, xbrl, basis, decimals, scale, eps_dec, annual_facts=annual_facts)
    has_negative_cost = any(
        isinstance(cell, dict) and item in _COST_ITEMS and cell["value"] < 0
        for cells in columns.values() for item, cell in cells.items()
    )
    if has_negative_cost and not any(
        isinstance(cell, dict) and cell.get("status") in CONFIRMED
        for cells in columns.values() for cell in cells.values()
    ):
        if log_review:
            review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": None,
                           "column_role": None, "raw_token": None, "check": "not_pl_costs",
                           "detail": "a cost line prints in brackets inside an unconfirmed page"})
        return None
    for role, cells in columns.items():
        for item, _names, target, want, unsure in cells.get("_fails", []):
            cell = cells.get(item)
            if cell is None or cell["status"] in CHECK_OK:
                continue
            if log_review:
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
                if not cell.get("drop") and log_review:
                    review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": item,
                                   "column_role": role, "raw_token": cell["raw"], "check": "repair_unconfirmed",
                                   "detail": ""})
                del cells[item]
    if drop_ocr_unreconciled:
        for role, cells in columns.items():
            stale = cells.get("revenue_from_operations")
            if (stale is not None and stale.get("ocr") and not stale.get("agreed")
                    and stale["status"] not in CHECK_OK and "total_income" in cells and "other_income" in cells):
                if log_review:
                    review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no,
                                   "line_item": "revenue_from_operations", "column_role": role,
                                   "raw_token": stale["raw"], "check": "ocr_unreconciled",
                                   "detail": f"value={stale['value']}"})
                del cells["revenue_from_operations"]
    _derive_revenue(columns)
    if recheck_after_revenue:
        for cells in columns.values():
            _check_column(cells, rupee_tol, ambiguous)
            _eps_ok(cells, shares)
        _assign_status(columns, end, xbrl, basis, decimals, scale, eps_dec, annual_facts=annual_facts)
    else:
        for cells in columns.values():
            rev = cells.get("revenue_from_operations")
            if rev is not None and rev.get("derived"):
                _apply_cell_xbrl_status(rev, xbrl, basis, rev["period_end"], "revenue_from_operations",
                                        decimals, scale, eps_dec, rev["ptype"], annual_facts)
    return columns


def _build_row(symbol: str, isin: str | None, role: str, basis: str, item: str, cell: dict,
               doc_key: str, page_no: int, known_at: str, scale_from_xbrl: bool,
               fallback: bool, header_used: bool) -> tuple | None:
    if cell["ptype"] == "ytd" and cell["period_end"][5:7] not in ("09", "12"):
        return None
    q = _quarter(cell["period_end"], cell["ptype"])
    if q is None:
        return None
    fiscal, start, ptype = q
    unit = "inr_per_share" if item.startswith("eps_") else "inr"
    detail = []
    if scale_from_xbrl:
        detail.append("scale from XBRL")
    if cell["repaired"]:
        detail.append("repaired")
    if cell.get("derived"):
        detail.append("derived")
    if cell.get("bracketed"):
        detail.append("bracketed costs")
    if fallback:
        detail.append("period from filing date")
    if header_used:
        detail.append("header_used")
    if cell.get("agreed"):
        detail.append("agreed")
    if cell.get("xbrl_conflict") is not None:
        detail.append(f"xbrl_conflict {cell['xbrl_conflict']}")
    return (symbol, isin, start, cell["period_end"], fiscal, ptype, role, basis, "P&L", item,
            cell["caption"], cell["value"], unit, 1.0, cell["raw"], cell["quote"], doc_key, page_no,
            known_at, "doc.known_at", cell["status"], "; ".join(detail) or None,
            0 if cell.get("derived") else 1)


def _table_rows(conn, symbol, isin, doc_key, page_no, known_at, table, xbrl, review, ocr: bool = False,
                fill_table: dict | None = None, store_fy: dict | None = None,
                disagreed: dict | None = None, layer_only: bool = False,
                layer_pending: set | None = None, ocr_pending: set | None = None,
                annual_facts: dict | None = None) -> list[tuple]:
    """Resolve this table's roles, parse its cells, run the checks, and return the rows to store.

    R-013 (18 Nov 2026): on a jumbled results page with OCR (``ocr=True``), OCR and the text layer (``fill_table``)
    are resolved on their own column sets; agreeing cells keep ``agreed``; disagreeing cells use the confirmation
    ladder (``xbrl_ok > repeat_ok > sum_ok > unchecked``, OCR on ties) and log ``ocr_text_disagree``; layer-only
    cells (or all cells when ``layer_only=True``) are kept only when confirmed in ``CHECK_OK``, else dropped as
    ``layer_unconfirmed``.  A clean text layer (``ocr=False, layer_only=False``) keeps existing behaviour unchanged."""
    halves = _split_side_by_side(table)
    if halves is not None:
        count = len(table["anchors"])
        fill_halves = (_split_side_by_side(fill_table, sides=(halves[0]["basis"], halves[1]["basis"]))
                       if fill_table is not None and len(fill_table["anchors"]) == count else None)
        out_rows: list[tuple] = []
        for i, half_table in enumerate(halves):
            fill_half = fill_halves[i] if fill_halves is not None else None
            out_rows.extend(_table_rows(conn, symbol, isin, doc_key, page_no, known_at, half_table, xbrl,
                                        review, ocr=ocr, fill_table=fill_half, store_fy=store_fy,
                                        disagreed=disagreed, layer_only=layer_only, layer_pending=layer_pending,
                                        ocr_pending=ocr_pending, annual_facts=annual_facts))
        return out_rows
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
    ambiguous = _ambiguous_items(values)
    basis_hint = table.get("basis") or _page_basis(table["text"], table.get("head"), allow_hyphen=(end[5:7] == "06"))
    dates = table.get("dates")
    if end[5:7] == "06" and dates is None and fill_table is not None and fill_table.get("dates") \
            and len(fill_table["dates"]) == count:
        dates = fill_table["dates"]
    choice = _roles(dates, end, count, values, xbrl, basis_hint, table["scale"], decimals,
                    table.get("hint"), header_rows=table.get("header_rows"), store_fy=store_fy,
                    annual_facts=annual_facts)
    if choice is None:
        review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": None,
                       "column_role": None, "raw_token": None, "check": "no_scale_or_roles",
                       "detail": f"unit={table['scale']}"})
        return []
    roles, basis, scale = choice["roles"], choice["basis"], choice["scale"]
    rupee_tol = _tol("total_income", decimals, scale)
    eps_dec = table.get("eps_decimals")
    if eps_dec is None:
        eps_dec = _resolve_eps_decimals(values, roles, end, xbrl, basis, scale, decimals, annual_facts)
    shares = _shares(conn, symbol, basis, known_at)
    chosen = _choose_rows(values, roles, end, xbrl, basis, scale, decimals, rupee_tol, eps_dec,
                          annual_facts=annual_facts)
    columns = _parsed_cells(values, roles, chosen, decimals, eps_dec, scale, table["labels"], review,
                            symbol, doc_key, page_no, ocr=ocr)
    if layer_only:
        for cells in columns.values():
            for cell in cells.values():
                cell["src"] = "layer"
    bracketed = _debit_costs(columns)
    if bracketed is None:
        _assign_status(columns, end, xbrl, basis, decimals, scale, eps_dec, annual_facts=annual_facts)
        xbrl_kept = []
        for role, cells in columns.items():
            for item, cell in cells.items():
                if cell.get("status") == "xbrl_ok":
                    built = _build_row(symbol, isin, role, basis, item, cell, doc_key, page_no, known_at,
                                       table["scale"] is None, fallback, bool(choice.get("header_used")))
                    if built is not None:
                        xbrl_kept.append(built)
        if not xbrl_kept:
            review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": None,
                           "column_role": None, "raw_token": None, "check": "not_pl_costs",
                           "detail": "a cost line prints in brackets inside a mixed page"})
        return xbrl_kept
    fill: dict[str, dict] = {}
    fill_dec = decimals
    fill_eps = eps_dec
    layer_ambiguous: set[str] = set()
    if fill_table is not None:
        fill_scale_in = (fill_table["scale"] or scale) if ocr else fill_table["scale"]
        fill_choice = _roles(fill_table.get("dates"), end, len(fill_table["anchors"]), fill_table["values"],
                             xbrl, basis_hint, fill_scale_in, fill_table["decimals"], fill_table.get("hint"),
                             header_rows=fill_table.get("header_rows"), store_fy=store_fy,
                             annual_facts=annual_facts)
        if fill_choice is not None and fill_choice["basis"] == basis and fill_choice["scale"] == scale \
                and {r for r in fill_choice["roles"] if r} == {r for r in roles if r}:
            fill_dec = fill_table["decimals"]
            fill_eps = fill_table.get("eps_decimals")
            if fill_eps is None:
                fill_eps = _resolve_eps_decimals(fill_table["values"], fill_choice["roles"], end, xbrl, basis,
                                                 scale, fill_dec, annual_facts)
            layer_ambiguous = _ambiguous_items(fill_table["values"])
            fill_chosen = _choose_rows(fill_table["values"], fill_choice["roles"], end, xbrl, basis, scale,
                                       fill_dec, _tol("total_income", fill_dec, scale), fill_eps,
                                       annual_facts=annual_facts)
            fill = _parsed_cells(fill_table["values"], fill_choice["roles"], fill_chosen, fill_dec, fill_eps,
                                 scale, fill_table["labels"], review, symbol, doc_key, page_no, ocr=(not ocr))
    scale_from_xbrl = table["scale"] is None
    header_used = bool(choice.get("header_used"))
    if ocr and fill:
        raw_ocr = {role: {k: dict(v) for k, v in cells.items()} for role, cells in columns.items()}
        raw_layer: dict[str, dict] = {}
        for role in columns:
            rdict: dict[str, dict] = {}
            for item, cell in fill.get(role, {}).items():
                if item == "total_expenses" and cell["value"] < 0:
                    if bracketed:
                        cell = dict(cell, value=-cell["value"], bracketed=True)
                    else:
                        continue
                elif item in _COST_ITEMS and cell["value"] < 0 and bracketed:
                    cell = dict(cell, value=-cell["value"], bracketed=True)
                else:
                    cell = dict(cell)
                cell["src"] = "layer"
                rdict[item] = cell
            raw_layer[role] = rdict

        disagree_pairs: set[tuple[str, str]] = set()
        for role in raw_ocr:
            for item, oc_raw in raw_ocr[role].items():
                lc_raw = raw_layer.get(role, {}).get(item)
                if lc_raw is None:
                    continue
                item_tol = 1e-6 if item.startswith("eps_") else _tol(item, decimals, scale, oc_raw["raw"], eps_dec)
                if _close(oc_raw["value"], lc_raw["value"], item_tol):
                    oc_raw["agreed"] = True
                    lc_raw["agreed"] = True
                else:
                    disagree_pairs.add((role, item))
                    review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no,
                                   "line_item": item, "column_role": role,
                                   "raw_token": oc_raw["raw"], "check": "ocr_text_disagree",
                                   "detail": f"text={lc_raw['value']} ocr={oc_raw['value']}"})

        res_ocr = _resolve_columns(
            {r: {k: dict(v) for k, v in c.items()} for r, c in raw_ocr.items()},
            end, rupee_tol, ambiguous, shares, xbrl, basis, decimals, scale, eps_dec,
            bool(bracketed), review, symbol, doc_key, page_no,
            drop_ocr_unreconciled=True, log_review=True, recheck_after_revenue=True,
            annual_facts=annual_facts,
        )
        if res_ocr is None:
            return []
        fill_rupee_tol = _tol("total_income", fill_dec, scale)
        res_layer = _resolve_columns(
            {r: {k: dict(v) for k, v in c.items()} for r, c in raw_layer.items()},
            end, fill_rupee_tol, layer_ambiguous, shares, xbrl, basis, fill_dec, scale, fill_eps,
            bool(bracketed), review, symbol, doc_key, page_no,
            drop_ocr_unreconciled=False, log_review=False, recheck_after_revenue=True,
            annual_facts=annual_facts,
        ) or {}

        columns = {role: {} for role in raw_ocr}
        recheck_layer: dict[str, dict] = {role: {} for role in raw_ocr}
        for role in raw_ocr:
            ro = res_ocr.get(role, {})
            rl = res_layer.get(role, {})
            raw_o = raw_ocr[role]
            raw_l = raw_layer.get(role, {})
            seen_items = [k for k in ro if k != "_fails"] + [k for k in rl if k != "_fails" and k not in ro]
            for item in seen_items:
                oc = ro.get(item)
                lc = rl.get(item)
                if (role, item) in disagree_pairs:
                    if item == "revenue_from_operations" and oc is not None and oc.get("derived"):
                        if lc is not None and lc["status"] in CHECK_OK:
                            columns[role][item] = lc
                        else:
                            columns[role][item] = oc
                        continue
                    o_score = _LADDER.get(oc["status"], 0) if oc is not None else -1
                    l_score = _LADDER.get(lc["status"], 0) if lc is not None else -1
                    if l_score == o_score == 3 and oc is not None and lc is not None:
                        period_end, ptype = _role_period(role, end)
                        item_tol = _tol(item, decimals, scale, oc["raw"], eps_dec)
                        od = _xbrl_diff(xbrl, basis, period_end, item, oc["value"], item_tol,
                                        ptype=ptype, annual_facts=annual_facts)
                        ld = _xbrl_diff(xbrl, basis, period_end, item, lc["value"], item_tol,
                                        ptype=ptype, annual_facts=annual_facts)
                        winner, loser = (lc, oc) if (ld is not None and (od is None or ld < od)) else (oc, lc)
                    else:
                        winner, loser = (lc, oc) if l_score > o_score else (oc, lc)
                    if winner is None:
                        continue
                    if winner["status"] in CHECK_OK:
                        columns[role][item] = winner
                        if _LADDER[winner["status"]] < 2 and loser is not None and disagreed is not None:
                            alt_row = _build_row(symbol, isin, role, basis, item, loser, doc_key, page_no,
                                                 known_at, scale_from_xbrl, fallback, header_used)
                            if alt_row is not None:
                                disagreed[(doc_key, page_no, role, basis, item)] = {"alt_row": alt_row}
                    elif disagreed is not None:
                        alt_row = (_build_row(symbol, isin, role, basis, item, loser, doc_key, page_no,
                                              known_at, scale_from_xbrl, fallback, header_used)
                                   if loser is not None else None)
                        disagreed[(doc_key, page_no, role, basis, item)] = {"alt_row": alt_row}
                        columns[role][item] = winner
                elif item in raw_o and item in raw_l:
                    winner = lc if (lc is not None and (oc is None or _LADDER.get(lc["status"], 0) > _LADDER.get(oc["status"], 0))) else oc
                    if winner is not None:
                        winner["agreed"] = True
                        columns[role][item] = winner
                elif item in raw_o:
                    if oc is not None:
                        columns[role][item] = oc
                elif item in raw_l:
                    if lc is not None and lc["status"] in CHECK_OK:
                        columns[role][item] = lc
                    else:
                        recheck_layer[role][item] = dict(raw_l[item])
                else:
                    o_score = _LADDER.get(oc["status"], 0) if oc is not None else -1
                    l_score = _LADDER.get(lc["status"], 0) if lc is not None else -1
                    winner = lc if l_score > o_score else oc
                    if winner is not None:
                        columns[role][item] = winner
            for item, cell in raw_l.items():
                if (role, item) not in disagree_pairs and item not in raw_o and item not in columns[role] and item not in recheck_layer[role]:
                    recheck_layer[role][item] = dict(cell)

        disagree_probe: dict[str, dict] = {role: {} for role in raw_ocr}
        for role in raw_ocr:
            for item in raw_ocr[role]:
                cur = columns[role].get(item)
                if cur is not None and cur["status"] in CHECK_OK:
                    continue
                if (role, item) in disagree_pairs and item in raw_layer.get(role, {}):
                    disagree_probe[role][item] = dict(raw_layer[role][item], _disagree_try=True)
                elif item not in columns[role] and item not in recheck_layer[role]:
                    disagree_probe[role][item] = dict(raw_ocr[role][item], _disagree_try=True)

        if any(recheck_layer.values()) or any(disagree_probe.values()) or any(
            cell.get("ocr") and not cell.get("agreed") and cell["status"] not in CHECK_OK
            for cells in columns.values() for cell in cells.values()
        ):
            probe = {r: {k: dict(v) for k, v in c.items()} for r, c in columns.items()}
            for role, pending in recheck_layer.items():
                for item, cell in pending.items():
                    probe[role][item] = dict(cell, _layer_try=True)
            for role, pending in disagree_probe.items():
                for item, cell in pending.items():
                    probe[role][item] = cell
            _derive_tax(probe)
            for cells in probe.values():
                _check_column(cells, rupee_tol, ambiguous)
                _eps_ok(cells, shares)
            _cross_column_marks(probe, end, rupee_tol)
            _assign_status(probe, end, xbrl, basis, decimals, scale, eps_dec, annual_facts=annual_facts)
            _derive_revenue(probe)
            for cells in probe.values():
                _check_column(cells, rupee_tol, ambiguous)
                _eps_ok(cells, shares)
            _assign_status(probe, end, xbrl, basis, decimals, scale, eps_dec, annual_facts=annual_facts)
            for role, pending in recheck_layer.items():
                for item, raw_cell in pending.items():
                    pcell = probe.get(role, {}).get(item)
                    if pcell is not None and pcell["status"] in CHECK_OK:
                        pcell.pop("_layer_try", None)
                        columns[role][item] = pcell
                    elif layer_pending is None:
                        review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no,
                                       "line_item": item, "column_role": role,
                                       "raw_token": raw_cell["raw"], "check": "layer_unconfirmed",
                                       "detail": ""})
                    else:
                        period_end, ptype = _role_period(role, end)
                        raw_cell["status"] = "unchecked"
                        raw_cell["period_end"], raw_cell["ptype"] = period_end, ptype
                        _, conflict = _xbrl_conflict(
                            xbrl, basis, period_end, item, raw_cell["value"],
                            _tol(item, fill_dec, scale, raw_cell["raw"], fill_eps),
                            ptype=ptype, annual_facts=annual_facts)
                        if conflict is not None:
                            raw_cell["xbrl_conflict"] = conflict
                        columns[role][item] = raw_cell
                        layer_pending.add((doc_key, page_no, role, basis, item))
            for role, pending in disagree_probe.items():
                for item, raw_cell in pending.items():
                    pcell = probe.get(role, {}).get(item)
                    if pcell is not None and pcell["status"] in CHECK_OK:
                        pcell.pop("_disagree_try", None)
                        columns[role][item] = pcell
                        if disagreed is not None:
                            disagreed.pop((doc_key, page_no, role, basis, item), None)
            for role in columns:
                ptax = probe.get(role, {}).get("tax")
                if ptax is not None and ptax.get("derived") and "tax" not in columns[role]:
                    if ptax["status"] in CHECK_OK:
                        columns[role]["tax"] = ptax
                    elif ptax.get("src") == "layer" and layer_pending is not None:
                        columns[role]["tax"] = ptax
                        layer_pending.add((doc_key, page_no, role, basis, "tax"))
                    elif ptax.get("ocr") and ocr_pending is not None:
                        columns[role]["tax"] = ptax
                        ocr_pending.add((doc_key, page_no, role, basis, "tax"))
            for role, cells in columns.items():
                for item, cell in list(cells.items()):
                    if item == "_fails" or cell["status"] in CHECK_OK:
                        continue
                    pcell = probe.get(role, {}).get(item)
                    if pcell is not None and pcell["status"] in CHECK_OK and _close(
                        cell["value"], pcell["value"], 1e-9
                    ):
                        cells[item] = pcell
                        continue
                    if cell.get("agreed") or (role, item) in disagree_pairs or cell.get("src") == "layer":
                        continue
                    if cell.get("ocr"):
                        if ocr_pending is not None:
                            ocr_pending.add((doc_key, page_no, role, basis, item))
                        else:
                            review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no,
                                           "line_item": item, "column_role": role,
                                           "raw_token": cell["raw"], "check": "ocr_unreconciled",
                                           "detail": f"value={cell['value']}"})
                            del cells[item]
    else:
        for role in columns:
            for item, cell in fill.get(role, {}).items():
                if item in _COST_ITEMS and cell["value"] < 0:
                    if bracketed:
                        cell["value"] = -cell["value"]
                        cell["bracketed"] = True
                    else:
                        continue
                columns[role].setdefault(item, cell)
        resolved = _resolve_columns(
            columns, end, rupee_tol, ambiguous, shares, xbrl, basis, decimals, scale, eps_dec,
            bool(bracketed), review, symbol, doc_key, page_no,
            drop_ocr_unreconciled=bool(ocr or fill or layer_only), log_review=True,
            recheck_after_revenue=bool(ocr or fill or layer_only), annual_facts=annual_facts,
        )
        if resolved is None:
            return []
        columns = resolved
        if ocr or fill or layer_only:
            for role, cells in columns.items():
                for item, cell in list(cells.items()):
                    if item == "_fails" or cell["status"] in CHECK_OK:
                        continue
                    if cell.get("src") == "layer":
                        if layer_pending is None:
                            review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": item,
                                           "column_role": role, "raw_token": cell["raw"],
                                           "check": "layer_unconfirmed", "detail": ""})
                            del cells[item]
                        else:
                            layer_pending.add((doc_key, page_no, role, basis, item))
                        continue
                    if cell.get("ocr") and not cell.get("agreed"):
                        if ocr_pending is not None:
                            ocr_pending.add((doc_key, page_no, role, basis, item))
                        else:
                            review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no, "line_item": item,
                                           "column_role": role, "raw_token": cell["raw"], "check": "ocr_unreconciled",
                                           "detail": f"value={cell['value']}"})
                            del cells[item]
            if not ocr and not layer_only and end[5:7] == "06" and fill and "last_fy" in columns:
                for item, cell in list(columns["last_fy"].items()):
                    if item == "_fails" or cell["status"] in CHECK_OK:
                        continue
                    ocr_cell = fill.get("last_fy", {}).get(item)
                    if ocr_cell is not None and not _close(cell["value"], ocr_cell["value"], rupee_tol):
                        if disagreed is None:
                            review.append({"symbol": symbol, "doc_key": doc_key, "page": page_no,
                                           "line_item": item, "column_role": "last_fy",
                                           "raw_token": cell["raw"], "check": "ocr_text_disagree",
                                           "detail": f"text={cell['value']} ocr={ocr_cell['value']}"})
                            del columns["last_fy"][item]
                        else:
                            disagreed[(doc_key, page_no, "last_fy", basis, item)] = (cell["value"], ocr_cell["value"])
    out: list[tuple] = []
    for role, cells in columns.items():
        for item, cell in cells.items():
            if item == "_fails":
                continue
            built = _build_row(symbol, isin, role, basis, item, cell, doc_key, page_no, known_at,
                               scale_from_xbrl, fallback, header_used)
            if built is not None:
                out.append(built)
    if fallback and not any(row[20] in CONFIRMED for row in out):
        return []                       # a guess with nothing confirming it stores nothing
    return out


def _xbrl_wants(xbrl: dict, basis: str, period_end: str, item: str, *,
                ptype: str = "quarter", annual_facts: dict | None = None) -> tuple[float, ...]:
    """Period-type-aware XBRL references for ``(basis, period_end, item)``: ``fy`` uses ``fin_annual_line``
    facts, ``quarter`` uses ``fin_quarter_xbrl``, ``ytd`` has no XBRL flow figures, and point-in-time
    ``paid_up_capital`` checks ``fin_quarter_xbrl`` when annual facts hold no row."""
    if ptype == "fy":
        wants = tuple((annual_facts or {}).get((basis, period_end), {}).get(item, ()))
        if wants:
            return wants
        if item != "paid_up_capital":
            return ()
    elif ptype != "quarter" and item != "paid_up_capital":
        return ()
    want = xbrl.get((basis, period_end), {}).get(item)
    return (want,) if want is not None else ()


def _xbrl_conflict(xbrl: dict, basis: str, period_end: str, item: str, value: float, tol: float,
                   ptype: str = "quarter", annual_facts: dict | None = None) -> tuple[float | None, float | None]:
    """Return ``(matched_diff, conflict_want)``: one is populated when XBRL holds a figure for the period."""
    wants = _xbrl_wants(xbrl, basis, period_end, item, ptype=ptype, annual_facts=annual_facts)
    if not wants:
        return None, None
    diffs = [abs(value - want) for want in wants if _close(value, want, tol)]
    if diffs:
        return min(diffs), None
    return None, min(wants, key=lambda want: abs(value - want))


def _xbrl_diff(xbrl: dict, basis: str, period_end: str, item: str, value: float, tol: float,
               ptype: str = "quarter", annual_facts: dict | None = None) -> float | None:
    return _xbrl_conflict(xbrl, basis, period_end, item, value, tol, ptype=ptype, annual_facts=annual_facts)[0]


def _xbrl_ok(xbrl: dict, basis: str, period_end: str, item: str, value: float, tol: float,
             ptype: str = "quarter", annual_facts: dict | None = None) -> bool:
    return _xbrl_diff(xbrl, basis, period_end, item, value, tol, ptype=ptype, annual_facts=annual_facts) is not None


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


def _row_basis_x(row, *, allow_hyphen: bool = False) -> dict[str, float]:
    """Approximate x-centre of ``standalone`` / ``consolidated`` words in one header row."""
    spans: list[tuple[int, int, float]] = []
    parts: list[str] = []
    pos = 0
    for word in row:
        txt = word[4]
        if parts:
            pos += 1
        end = pos + len(txt)
        spans.append((pos, end, (word[0] + word[2]) / 2.0))
        parts.append(txt)
        pos = end
    found = _basis_positions(" ".join(parts), allow_hyphen=allow_hyphen)
    out: dict[str, float] = {}
    for name, offset in found.items():
        for s, e, x in spans:
            if s <= offset < e:
                out[name] = x
                break
    return out


def _basis_header_sides(header_rows, anchors: list[float], *, allow_hyphen: bool = True) -> tuple[str, str] | None:
    """``(left_basis, right_basis)`` for an even ``>= 8`` column table with both S and C headings."""
    count = len(anchors)
    if count < 8 or count % 2:
        return None
    half = count // 2
    mid = (anchors[half - 1] + anchors[half]) / 2.0
    for row in reversed(header_rows or []):
        xs = _row_basis_x(row, allow_hyphen=allow_hyphen)
        if set(xs) != {"standalone", "consolidated"}:
            continue
        sx, cx = xs["standalone"], xs["consolidated"]
        if sx < mid <= cx:
            return ("standalone", "consolidated")
        if cx < mid <= sx:
            return ("consolidated", "standalone")
    flat = " ".join(w[4] for row in (header_rows or []) for w in row)
    pos = _basis_positions(flat, allow_hyphen=allow_hyphen)
    if set(pos) != {"standalone", "consolidated"}:
        return None
    return ("standalone", "consolidated") if pos["standalone"] < pos["consolidated"] else ("consolidated", "standalone")


def _split_side_by_side(table: dict, sides: tuple[str, str] | None = None) -> list[dict] | None:
    """Split a side-by-side Standalone/Consolidated table (8, 10 or 12 columns) into its two halves."""
    anchors = table.get("anchors") or []
    count = len(anchors)
    if count < 8 or count % 2 or table.get("basis") is not None:
        return None
    detected = _basis_header_sides(table.get("header_rows") or [], anchors, allow_hyphen=True)
    used_fallback = detected is None and sides is not None
    sides = detected or sides
    if sides is None:
        return None
    half = count // 2
    dates = table.get("dates")
    if dates and len(dates) == count:
        left_d, right_d = dates[:half], dates[half:]
        if any(lm is not None and rm is not None and lm != rm for (lm, _ly), (rm, _ry) in zip(left_d, right_d)):
            if not used_fallback:
                return None
            half_dates = (None, None)
        else:
            half_dates = (left_d, right_d)
    else:
        half_dates = (None, None)
    halves: list[dict] = []
    eps_dec = table.get("eps_decimals", _eps_decimals(table["values"]))   # one half may print EPS without points
    for i, basis in enumerate(sides):
        offset = i * half
        half_anchors = anchors[offset:offset + half]
        half_table = dict(table)
        half_table["anchors"] = half_anchors
        # keep the build's default-empty columns: a half whose column holds no figure must read as empty
        half_values = _HalfValues(lambda: defaultdict(list),
                                  {at - offset: col for at, col in table["values"].items()
                                   if offset <= at < offset + half})
        half_values.eps_decimals = eps_dec
        half_table["values"] = half_values
        half_table["dates"] = half_dates[i]
        half_table["hint"] = _layout_hint(table.get("header_rows") or [], half_anchors)
        half_table["basis"] = basis
        half_table["eps_decimals"] = eps_dec
        halves.append(half_table)
    return halves


def _side_by_side_ok(header_rows, dates, count: int) -> bool:
    """True only when a wide (>=7-column) June table is two mirrored four-column S/C halves."""
    if count < 8:
        return False
    flat = " ".join(w[4] for row in (header_rows or []) for w in row)
    if set(_basis_positions(flat, allow_hyphen=True)) != {"standalone", "consolidated"}:
        return False
    if dates and len(dates) >= 8:
        left, right = dates[:4], dates[-4:]
        for (lm, _ly), (rm, _ry) in zip(left, right):
            if lm is not None and rm is not None and lm != rm:
                return False
        for (lm, _ly), want_m in zip(left, (6, 3, 6, 3)):
            if lm is not None and lm != want_m:
                return False
    return True


def _fy_refs(basis: str, period_end: str, xbrl: dict, store_fy: dict | None,
             annual_facts: dict | None = None) -> dict[str, list[float]]:
    """Known full-year values for ``period_end`` from XBRL, earlier store FY rows, and annual XBRL facts."""
    refs: dict[str, list[float]] = defaultdict(list)
    if basis in ("standalone", "consolidated"):
        for item, val in xbrl.get((basis, period_end), {}).items():
            refs[item].append(val)
    for extra in (store_fy, annual_facts):
        if not extra:
            continue
        for (b, pe), items in extra.items():
            if pe != period_end:
                continue
            if basis in ("standalone", "consolidated") and b not in (basis, "unchecked"):
                continue
            for item, vals in items.items():
                refs[item].extend(vals)
    return refs


def _june_last_fy_confirmed(at: int, dates, end: str, values: dict, xbrl: dict, store_fy: dict | None,
                             basis: str, scale: float, decimals: int,
                             annual_facts: dict | None = None) -> bool:
    """True when a June table's ``last_fy`` column has its March year matched or matches an FY value."""
    want_year = int(end[:4])
    if dates and at < len(dates) and _date_match(dates[at], (3, want_year), require_year=True):
        return True
    refs = _fy_refs(basis, _last_fy_end(end), xbrl, store_fy, annual_facts)
    if not refs:
        return False
    eps_dec = _eps_decimals(values)
    for item, tokens in values.get(at, {}).items():
        wants = refs.get(item)
        if not wants:
            continue
        for token in tokens:
            parsed = _parse_cell(item, token["text"], decimals, eps_dec)
            if parsed is None or abs(parsed[0]) == 0.0:
                continue
            val = parsed[0] * (1.0 if item.startswith("eps_") else scale)
            tol = _tol(item, decimals, scale, token["text"], eps_dec)
            if any(_close(val, want, tol) for want in wants):
                return True
    return False


def _roles(dates, end: str, count: int, values: dict, xbrl: dict, basis_hint: str | None,
           scale: float | None, decimals: int, hint: list[str] | None = None,
           header_rows=None, store_fy: dict | None = None,
           annual_facts: dict | None = None) -> dict | None:
    """Column roles (header order first, a header layout hint second, layout by quarter last), basis and scale,
    checked against XBRL; the earlier candidate wins a tie."""
    if end[5:7] == "06" and count >= 7 and not _side_by_side_ok(header_rows, dates, count):
        return None
    default = _role_set(end, count)
    chance = None
    if dates and len(dates) == count:
        header, covered = _roles_from_dates(dates, end, default, count)
        if covered and header != default:
            chance = header
    bases = [basis_hint] if basis_hint else (["consolidated", "standalone"] if xbrl else ["unchecked"])
    target = list(hint) if (hint and end[5:7] != "06") else None
    candidates: list[list[str | None]] = []
    for roles in (target, chance, default):
        if roles is not None and roles not in candidates:
            candidates.append(roles)
    if end[5:7] == "06" and count in (5, 6):
        want_year = int(end[:4])
        base = chance or default
        lfy_at = base.index("last_fy") if "last_fy" in base else -1
        has_year = bool(lfy_at >= 0 and dates and lfy_at < len(dates)
                        and _date_match(dates[lfy_at], (3, want_year), require_year=True))
        if has_year:
            candidates = [base]
        else:
            q_part = base[:3]
            tail_n = count - 3
            for pos in range(tail_n):
                tail: list[str | None] = [None] * tail_n
                tail[pos] = "last_fy"
                cand = list(q_part) + tail
                if cand not in candidates:
                    candidates.append(cand)
    best = None
    for roles in candidates:
        for basis in bases:
            # the page's declared scale is tried first and wins a tie; a scale the XBRL figures confirm beats a
            # declared one they do not (R-006: the unit line can be missing from the text layer)
            for sc in ([scale] if scale else []) + [s for s in (1e5, 1e6, 1e7) if s != scale]:
                use_fy = store_fy if (scale is None or sc == scale) else None
                use_annual = annual_facts if (scale is None or sc == scale) else None
                if basis not in ("standalone", "consolidated") and not (end[5:7] == "06" and (use_fy or use_annual)):
                    score = 0
                else:
                    score = _score_roles(roles, end, values, xbrl, basis, sc, decimals,
                                         store_fy=use_fy, annual_facts=use_annual)
                if best is None or score > best[0]:
                    best = (score, roles, basis, sc)
    if best is None or (best[0] == 0 and scale is None):
        return None
    _score, roles, basis, sc = best
    if best[0] == 0 and basis_hint is None:
        basis = "unchecked"          # neither the title nor the XBRL match settles the basis
    roles = list(roles)
    if end[5:7] == "06" and "last_fy" in roles:
        at = roles.index("last_fy")
        if not _june_last_fy_confirmed(at, dates, end, values, xbrl, store_fy, basis, sc, decimals,
                                       annual_facts=annual_facts):
            roles[at] = None
    periods = {role: _role_period(role, end) for role in roles if role}
    return {"roles": roles, "basis": basis, "scale": sc, "periods": periods, "score": best[0],
            "header_used": bool(chance and roles == chance)}


def _roles_from_dates(dates, end: str, default: list[str | None], count: int) -> tuple[list[str | None], bool]:
    """Header order: the day/month/year each column prints, checked against the role's expected date.

    Quarter columns come first and the ytd/year columns after them in every Indian results layout, so each
    group of roles is permuted over its own slots and the permutation the dates support best wins; the layout's
    own order breaks a tie (HDFCBANK's year-ago column is misread 39.09.2026 -- the count and the quarter
    decide).  A company that puts the year-ago before the preceding quarter (HINDUNILVR) is still read right."""
    expected = {role: _expected_date(role, end) for role in default if role}
    quarter = [r for r in default if r in ("current", "preceding", "year_ago")]
    group = [r for r in default if r not in ("current", "preceding", "year_ago")]

    def best_order(roles: list[str | None], start: int) -> list[str | None]:
        best, best_score = list(roles), -1
        for perm in dict.fromkeys(itertools.permutations(roles)):
            score = 0
            for i, role in enumerate(perm):
                at = start + i
                if role and dates and at < len(dates) and _date_match(
                        dates[at], expected[role], require_year=(role == "last_fy")):
                    score += 1
            score = score * 10 + sum(1 for i, role in enumerate(perm) if role == roles[i])
            if score > best_score:
                best, best_score = list(perm), score
        return best

    roles = (best_order(quarter, 0) + best_order(group, len(quarter)))[:count]
    return roles, bool(dates) and len(dates) == count


def _score_roles(roles, end, values, xbrl, basis: str, scale: float, decimals: int,
                 store_fy: dict | None = None, annual_facts: dict | None = None) -> int:
    tol = _tol("total_income", decimals, scale)
    eps_dec = _eps_decimals(values)
    score = 0
    if basis in ("standalone", "consolidated"):
        for at, role in enumerate(roles):
            if not role:
                continue
            period_end, ptype = _role_period(role, end)
            for item, tokens in values.get(at, {}).items():
                for token in tokens:
                    parsed = _parse_cell(item, token["text"], decimals, eps_dec)
                    if parsed is None:
                        continue
                    value = parsed[0] * (1.0 if item.startswith("eps_") else scale)
                    if _xbrl_ok(xbrl, basis, period_end, item, value,
                                _tol(item, decimals, scale, token["text"], eps_dec),
                                ptype=ptype, annual_facts=annual_facts):
                        score += 10 if role == "current" else 5
    if end[5:7] == "06" and "last_fy" in roles and (store_fy or annual_facts):
        at = roles.index("last_fy")
        lfy_end = _last_fy_end(end)
        refs = _fy_refs(basis, lfy_end, {}, store_fy, annual_facts)
        for item, tokens in values.get(at, {}).items():
            wants = refs.get(item)
            if not wants:
                continue
            for token in tokens:
                parsed = _parse_cell(item, token["text"], decimals, eps_dec)
                if parsed is None or abs(parsed[0]) == 0.0:
                    continue
                value = parsed[0] * (1.0 if item.startswith("eps_") else scale)
                item_tol = _tol(item, decimals, scale, token["text"], eps_dec)
                if not _xbrl_ok(xbrl, basis, lfy_end, item, value, item_tol,
                                ptype="fy", annual_facts=annual_facts) and any(
                        _close(value, want, item_tol) for want in wants):
                    score += 5
    if basis in ("standalone", "consolidated") and end[5:7] == "09" and all(
            r in roles for r in ("current", "preceding", "ytd")):
        i, j, k = roles.index("current"), roles.index("preceding"), roles.index("ytd")
        for item in (set(values.get(i, {})) & set(values.get(j, {})) & set(values.get(k, {}))):
            got = []
            for at in (i, j, k):
                parsed = _parse_cell(item, values[at][item][0]["text"], decimals)
                got.append(None if parsed is None else parsed[0])
            if any(g is None for g in got):
                continue
            if item.startswith("eps_"):
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
        if "pat" in items or "eps_basic" in items or any(role in ("ytd", "prior_ytd") for role, _item in cells):
            comps = [items.get(k) for k in ("pbt_before_exceptional", "finance_cost", "depreciation", "other_income")]
            if "ebitda" not in items and comps[0] is not None and comps[1] is not None and comps[2] is not None \
                    and not profile.is_lender(symbol):
                items["ebitda"] = comps[0] + comps[1] + comps[2] - (comps[3] or 0.0)
            out.append({"known_at": known, "doc_key": doc_key, "items": items, "cells": cells,
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
