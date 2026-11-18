"""T-177/T-185: settle reference cells by where the value is printed, not only by how many readers agree.

A text-only reader gets the page in reading order.  On a results page that order is column-major (every row label,
then a column of numbers), so a blank cell shifts every later number one row down and two readers can make the
same shift ("Exceptional items 45271" on a page where that cell is blank).  A vote cannot see that; the PDF can:
each printed word has a box.  Here every reader cell (row label, column header, value) is placed on the page:

* **row**: the value's word sits on a line whose text to its left spells the row label (also a wrapped label of up
  to three number-less lines above and one below, at the label's x-position); a chart value with no labelled line
  takes the nearest number-less title above it in the same x-band as its row;
* **column**: per table block, the header band (the lines above the first data line that hold period/date/unit
  words) is attached to the number columns below it.  A header phrase stays over the columns its box spans, so a
  date printed once above a quarter column and a nine-month column belongs to both, while "Nine months ended"
  belongs only to the nine-month ones.  The cell's column holds when the reader's header matches the stack of the
  column the value sits in, fails when it matches another column's stack, and falls back to the old presence rule
  only where no header band is found.  A chart value takes the nearest axis label below it as its column.

A cell is settled when its row is confirmed by position and no check contradicts it:

    script+position   two or more readers gave it and the row is confirmed
    position          one reader gave it, row and column both confirmed
    script            two or more readers gave it, the label or value could not be located (a chart, a scan)
    (empty)           not settled: ``conflict`` names why (row_elsewhere, column_elsewhere, lone_unlocated ...)

Every output cell also carries a ``verdict`` that separates what the reader got wrong from what the checker could
not confirm: ``confirmed`` (row and column placed), ``reader_error_row`` (the value sits on a line a confirmed cell
or another reader names as a different row), ``reader_error_column`` (it sits under a different column's header
stack), ``checker_miss`` (label and value are on the page, nothing contradicts them, but the rules could not
confirm) and ``unplaced`` (value or label not on the page).  ``how`` says whether the row came from the value's
own line, a wrapped label, or a chart panel (``line`` / ``wrap`` / ``chart``).

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
from reality_engine.v2.reference_vote import cells_of, col_key, label_key, same_label, unify_labels

COLS = ["page_id", "split", "row_label", "col_header", "value_text", "unit_text", "table", "readers", "agree_n", "row_ok",
        "col_ok", "settled_by", "conflict", "how", "verdict", "label_aliases", "col_aliases", "line_text", "x0", "y0",
        "x1", "y1", "section", "label_repeated"]
VERDICTS = ("confirmed", "reader_error_row", "reader_error_column", "checker_miss", "unplaced")
_NUM = re.compile(r"^[-(]?[\d,]*\d(?:\.\d+)?\)?[%x]?$")
_STRIP = "*†‡#^~`₹$€£:;|"

_MONTHS = {"jan", "january", "feb", "february", "mar", "march", "apr", "april", "may", "jun", "june", "jul", "july",
           "aug", "august", "sep", "sept", "september", "oct", "october", "nov", "november", "dec", "december"}
_HEADER_WORDS = {"quarter", "quarters", "month", "months", "year", "years", "ended", "ending", "audited", "unaudited",
                 "reviewed", "restated", "particulars", "description", "yearended", "quarterended", "halfyear"}
_UNIT_WORDS = {"rs", "inr", "usd", "eur", "crore", "crores", "lakh", "lakhs", "million", "millions", "billion", "mn",
               "bn", "%", "unit", "units", "share", "per"}
_QTR = re.compile(r"^q[1-4](?:fy)?\d{0,4}$")
_PERIOD = re.compile(r"^(?:fy|h[12](?:fy)?)\d{1,4}$")
_DATE = re.compile(r"^(?:\d{1,2}[-./]\d{1,2}[-./]\d{2,4}|\d{1,2}(?:st|nd|rd|th)?[-./]?[a-z]{3,9}[-./]?\d{0,4}"
                   r"|(?:19|20)\d{2}|\d{1,2}[-./][a-z]{3,9})$")
# A date printed with odd separators ("31.03.2022", "31,03,22").  The last group is 2 or 4 digits: an Indian-grouped
# number ("1,03,086") ends in a 3-digit group and is a value, not a date (T-225).
_DATE_TYPO = re.compile(r"^(?:0?[1-9]|[12]\d|3[01])[.\-/](?:0?[1-9]|1[0-2])[.\-/](?:\d{2}|(?:19|20)\d{2})$"
                        r"|^(?:0?[1-9]|[12]\d|3[01]),(?:0?[1-9]|1[0-2]),(?:19|20)\d{2}$"
                        r"|^(?:0?[1-9]|1[0-2])[.\-/](?:0?[1-9]|[12]\d|3[01])[.\-/](?:19|20)\d{2}$")
# A month and year in one word: "Dec22", "Mar-23", "March2023", "Dec'22" (T-225).
_MONTH_YEAR = re.compile(r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]{0,6}[-'.’/]?(?:\d{2}|(?:19|20)\d{2})$")


def word_value(text: str) -> str:
    """A printed word as a value key: braces read as brackets ("{367)"), marks and currency signs dropped."""
    t = str(text or "").strip().strip(_STRIP).replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    return _norm_value(t)


_BLANK = {"-", "--", "–", "—", "nil", "na", "n.a.", "n/a", "nm"}


# A well-formed printed figure (T-225): western 1,234,567 or Indian 1,23,45,678 grouping or plain digits, optional
# decimals, sign, brackets, %, x or a footnote star.  "206,61", "4,7t186", "1.24.285.61" are scan misreads.
_WELL_FORMED = re.compile(r"^\(?[-+]?(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3}|\d+)(?:\.\d+)?[%x]?\)?[%x]?$")
GARBLED_MIN_FIGURES = 20        # figure tokens a page must print before its layer can be judged (5 flagged a clean
                                # page on one odd token)
GARBLED_SHARE = 0.15            # malformed share at or above which the layer is a scan misread (dev pages: 0.04 vs 0.44)


_GLUED_UNIT = re.compile(r"(?:crores?|cr|lakhs?|lacs?|mn|bn|millions?|billions?)\)?[.,;:]?$", re.I)


def well_formed(value: str) -> bool:
    """A printed figure in a valid grouping.  A unit glued to it ("₹2.40crore", "(₹0.00crore).") and closing
    punctuation are dropped first."""
    t = str(value or "").strip().replace(" ", "").casefold()
    t = t.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    t = re.sub(r"[–—−]", "-", t)                          # en/em dash and unicode minus print a negative
    t = re.sub(r"[*†‡#^~]+", "", t)                       # footnote marks
    t = re.sub(r"₹|\$|€|£|rs\.?|inr", "", t)              # currency anywhere ("-₹1,234", "(€1,234)", "Rs.1,234")
    t = _GLUED_UNIT.sub(lambda m: ")" if ")" in m.group(0) else "", t).rstrip(".,;:")
    return bool(_WELL_FORMED.match(t))


_SECTION_NO = re.compile(r"^\d+(?:\.\d+){2,}$|^(?:19|20)\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}$")   # 2.1.1, 2022.01.31
_RANGE = re.compile(r"^[\d,.]+[-–][\d,.]+[*+]?$")                                          # 10.5-12.3


def _figure_token(t: str) -> bool:
    """A printed word that should be a table figure: a separator, 3+ digits, not a date/period/time/code/clause
    number/range.  A misread first digit ("l,234.56", "O,456.78") still counts, so that it counts as malformed."""
    t = t.strip()
    if not re.search(r"[.,]", t) or len(re.sub(r"\D", "", t)) < 3 or ":" in t or re.search(r"\d[.,]$", t):
        return False
    if _SECTION_NO.match(t) or _RANGE.match(t) or _is_header_word(t):
        return False
    return not re.match(r"^[A-Za-z]", t) or bool(re.match(r"^[lIOSBZ][.,\d]", t))


def layer_garbled(words: list[tuple[float, float, float, float, str]] | None) -> bool:
    """A text layer whose figures are scan misreads ("18,527,91J", "6rn.18"): confirming a reader's value against
    it would confirm the misread, so such a page confirms nothing until OCR words replace the layer (T-175, T-225)."""
    figs = [w[4] for w in words or [] if _figure_token(w[4])]
    return len(figs) >= GARBLED_MIN_FIGURES and sum(1 for t in figs if not well_formed(t)) / len(figs) >= GARBLED_SHARE


def _is_num(text: str) -> bool:
    """A number, or the mark a table prints in an empty cell."""
    t = str(text or "").strip().casefold()
    return t in _BLANK or bool(_NUM.match(word_value(text).replace("-", "", 1) or "x"))


def _tok(text: str) -> str:
    """One printed word reduced to a comparison token."""
    return re.sub(r"^[^a-z0-9%]+|[^a-z0-9%]+$", "", str(text or "").casefold())


def _is_header_word(text: str) -> bool:
    """A word that belongs to a column header band: a period/date token or a unit word."""
    t = _tok(text)
    if not t:
        return False
    if t in _HEADER_WORDS or t in _UNIT_WORDS or t in _MONTHS:
        return True
    return bool(_QTR.match(t) or _PERIOD.match(t) or _DATE.match(t) or _DATE_TYPO.match(t)
                or _MONTH_YEAR.match(t))


def _header_tokens(text: str) -> list[str]:
    """Comparison tokens: "Q4FY21" and "Q4 FY21" are both ("q4", "fy21")."""
    out: list[str] = []
    for t in re.findall(r"[a-z0-9]+%?", str(text or "").casefold()):
        m = re.match(r"^(q[1-4]|h[12])(fy)?(\d{2,4})$", t)
        if m:
            out.append(m.group(1))
            out.append((m.group(2) or "") + m.group(3))
        else:
            out.append(t)
    return out


_GENERIC = {"particulars", "description", "unit", "units", "amount", "note", "notes", "no", "sr", "srno", "in", "of",
            "the", "as", "at", "per", "and", "to", "for", "reviewed", "audited", "unaudited", "restated"}


def _strong_header(words: list[tuple[float, float, float, float, str]]) -> bool:
    """Two or more period/date/unit words, or a third of the line: a real header, not prose with a year in it."""
    toks = [_tok(w[4]) for w in words if _tok(w[4])]
    if not toks:
        return False
    hits = sum(1 for w in words if _is_header_word(w[4]))
    return hits >= 2 or (hits >= 1 and hits / len(toks) >= 0.34)


# word headers ("No. of shares | Amount"): only function words are ignored; "amount", "no", "units" name columns
_WORD_STOP = {"the", "of", "in", "as", "at", "and", "to", "for", "per", "on", "rs", "inr", "crore", "crores", "lakh",
              "lakhs", "million", "mn"}


_PERIOD_WORDS = {"quarter", "quarters", "month", "months", "year", "years", "ended", "ending", "yearended",
                 "quarterended", "halfyear"}


def _is_period_word(text: str) -> bool:
    t = _tok(text)
    return bool(t) and bool(t in _PERIOD_WORDS or t in _MONTHS or _QTR.match(t) or _PERIOD.match(t)
                        or _DATE.match(t) or _DATE_TYPO.match(t) or _MONTH_YEAR.match(t))


def _is_sub_period(text: str) -> bool:
    return bool(re.fullmatch(r"q[1-4]|h[12]|\d{1,2}m", _tok(text)))


def _is_year_part(text: str) -> bool:
    t = str(text or "").strip().casefold().strip(".,;:()^*")
    return bool(re.fullmatch(r"fy'?\d{2,4}[a-z]?|'\d{2}|(?:19|20)\d{2}|(?:19|20)\d{2}-\d{2,4}", t))


def _is_period_part(text: str) -> bool:
    return _is_sub_period(text) or _is_year_part(text)


def _period_kind(text: str) -> str:
    """What kind of period a header phrase names: a bare year, a month/day date, a quarter or something else."""
    toks = _header_tokens(text)
    if any(t in _MONTHS for t in toks) or any(_DATE_TYPO.match(t) or _MONTH_YEAR.match(t) for t in toks) \
            or sum(1 for t in toks if t.isdigit()) >= 2:
        return "date"
    if any(_QTR.match(t) or t in {"quarter", "quarters"} for t in toks):
        return "quarter"
    if any(re.fullmatch(r"(?:19|20)\d{2}", t) for t in toks) \
            or any(_PERIOD.match(t) or t in {"year", "years", "yearended"} for t in toks):
        return "year"
    if any(_DATE.match(t) for t in toks):
        return "date"
    return "other"


def _header_match(header: str, stack: str) -> bool:
    """Does a reader's column header name this printed header stack?  Matches on the col_key, else on every word
    of the reader's header being printed in the stack (a period token must be among them)."""
    rk, sk = col_key(header), col_key(stack)
    if not rk or not sk:
        return False
    if rk == sk or rk in sk or sk in rk:
        return True
    reader_tokens = _header_tokens(header)
    stack_tokens = set(_header_tokens(stack))
    if not reader_tokens or not all(t in stack_tokens for t in reader_tokens):
        return False
    return any(any(ch.isdigit() for ch in t) for t in reader_tokens)


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
        heights = sorted(max(w[3] - w[1], 3.0) for w in words)
        self.h = heights[len(heights) // 2] if heights else 8.0
        self.by_value: dict[str, list[int]] = defaultdict(list)
        for i, w in enumerate(words):
            key = word_value(w[4])
            if key:
                self.by_value[key].append(i)
                if key.endswith("%"):
                    self.by_value[key[:-1]].append(i)
        self._bands: dict[int, list[int]] = {}
        self._blocks: dict[int, list[int]] = {}
        self._cols: dict[int, list[dict[str, Any]]] = {}
        self._phrases: dict[Any, list[tuple[float, float, str]]] = {}
        self._whole_key: str | None = None

    # -- labels -------------------------------------------------------------------------------------------------
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

    def line_letters(self, line: int) -> list[int]:
        return [i for i in self.lines[line] if re.search(r"[A-Za-z]", self.words[i][4])]

    def first_letter_x0(self, line: int) -> float | None:
        idx = self.line_letters(line)
        return self.words[idx[0]][0] if idx else None

    def line_has_value(self, line: int) -> bool:
        """A value the table prints: a number that is not a header's date/period/unit word.  A day number beside
        a month ("31 March 2023") belongs to the header, not to a data cell."""
        line_words = self.lines[line]
        for i in line_words:
            w = self.words[i]
            if not _is_num(w[4]) or _tok(w[4]) in _BLANK or _is_header_word(w[4]):
                continue
            beside = any(abs(self.words[j][0] - w[2]) <= max(6.0, 0.8 * self.h)
                         or abs(w[0] - self.words[j][2]) <= max(6.0, 0.8 * self.h)
                         for j in line_words if j != i and _is_header_word(self.words[j][4]))
            if not beside:
                return True
        return False

    def title_line(self, line: int) -> bool:
        """A page or table title or a registration line, whose words must never head a column (T-225: a title's
        "30th SEPTEMBER, 2026" put a 30.09.2025 column under 30.09.2026 on a real results page).  Only two shapes:
        a CIN / registered-office line, or a line whose longest phrase has five or more words and spans 85% or more
        of the table's width (a logo word beside it does not matter).  A line split into several phrases ("Standalone Results | Consolidated Results", "For the quarter
        ended | For the year ended") is a group row and stays: it is what tells repeated date columns apart."""
        idx = self.lines[line]
        words = [self.words[j][4] for j in idx]
        if any(re.fullmatch(r"(?:cin|regd\.?|registered)", w.strip(",.:;()").casefold()) for w in words):
            return True
        if words and re.fullmatch(r"(?:particulars|s\.?\s*no\.?|s[il1]\.?|sr\.?|no\.?)", words[0].strip(",.:;()").casefold()):
            return False
        period_hits = Counter(t for t in (_tok(w) for w in words) if t in ("quarter", "month", "months", "year", "ended"))
        if any(n >= 2 for n in period_hits.values()):
            return False                              # two column headers run together ("Quarter ... Quarter ...")
        gap = max(14.0, 1.5 * self.h)
        runs: list[list[int]] = [[idx[0]]] if idx else []
        for a, b in zip(idx, idx[1:]):
            if self.words[b][0] - self.words[a][2] > gap:
                runs.append([b])
            else:
                runs[-1].append(b)
        longest = max(runs, key=lambda r: sum(1 for j in r if re.search(r"[A-Za-z]{2}", self.words[j][4])), default=[])
        if sum(1 for j in longest if re.search(r"[A-Za-z]{2}", self.words[j][4])) < 5:
            return False
        figs = []                                  # table figures: right of each line's row label (no serial nos.)
        for m in range(line + 1, min(len(self.lines), line + 12)):
            lab = max((self.words[j][2] for j in self.lines[m] if re.search(r"[A-Za-z]{2}", self.words[j][4])),
                      default=None)
            if lab is not None:
                figs += [j for j in self.lines[m] if self._digit_figure(j) and self.words[j][0] > lab]
        if not figs:
            return True
        x0, x1 = min(self.words[j][0] for j in figs), max(self.words[j][2] for j in figs)
        span = min(self.words[longest[-1]][2], x1) - max(self.words[longest[0]][0], x0)
        # one phrase over (nearly) every column decides no column; a phrase running in from the label area over
        # half the columns or more is a title too (a group row sits over the columns only)
        from_labels = self.words[longest[0]][0] < x0 - 3.0 * self.h
        return span >= 0.85 * (x1 - x0) or (from_labels and span >= 0.5 * (x1 - x0))

    def is_header_line(self, line: int) -> bool:
        return any(_is_header_word(self.words[i][4]) for i in self.lines[line])

    def strong_header_line(self, line: int) -> bool:
        return _strong_header([self.words[i] for i in self.lines[line]])

    def _wrapped(self, i: int) -> tuple[str, str]:
        """The number-less lines joined onto the value's label, at the label's x-position (up to 3 above, 1 below)."""
        n, x = self.line_of[i], self.words[i][0]
        tol = max(18.0, 3.0 * self.h)
        above: list[str] = []
        anchor = self.first_letter_x0(n)
        if anchor is not None and anchor > x:
            anchor = None
        if anchor is None:
            last = None
            for m in range(n - 1, max(-1, n - 4), -1):
                if self.line_has_value(m) or self.strong_header_line(m):
                    break
                text = self.text_left(m, None)
                x0 = self.first_letter_x0(m)
                if not re.search(r"[A-Za-z]", text) or x0 is None or x0 >= x - tol:
                    break
                if last is not None and abs(x0 - last) > tol:
                    break
                above.append(text)
                last = x0
            above.reverse()
        else:
            for m in range(n - 1, max(-1, n - 4), -1):
                if self.line_has_value(m) or self.strong_header_line(m):
                    break
                x0 = self.first_letter_x0(m)
                if x0 is None or abs(x0 - anchor) > tol:
                    break
                text = self.text_left(m, x)
                if not re.search(r"[A-Za-z]", text):
                    break
                above.append(text)
            above.reverse()
        below = ""
        if anchor is not None and n + 1 < len(self.lines) and not self.line_has_value(n + 1) \
                and not self.strong_header_line(n + 1):
            x0 = self.first_letter_x0(n + 1)
            if x0 is not None and abs(x0 - anchor) <= tol:
                text = self.text_left(n + 1, x)
                if re.search(r"[A-Za-z]", text):
                    below = text
        return " ".join(above), below

    def row_texts(self, i: int) -> list[str]:
        """Label text candidates for the value word ``i``: its own line, then the same joined with wrapped lines."""
        n, x = self.line_of[i], self.words[i][0]
        own = self.text_left(n, x)
        whole = " ".join(self.words[j][4] for j in self.lines[n]
                         if self.words[j][2] <= x + 1 and re.search(r"[A-Za-z]", self.words[j][4]))
        out = [own] + ([whole] if whole and whole != own else [])
        above, below = self._wrapped(i)
        if above:
            out.append(f"{above} {own}")
        if below:
            out.append(f"{own} {below}")
        if above and below:
            out.append(f"{above} {own} {below}")
        return out

    def row_own(self, i: int, keys: set[str]) -> bool:
        """Does the row label fit the value's own printed line?"""
        n, x = self.line_of[i], self.words[i][0]
        own = self.text_left(n, x)
        whole = " ".join(self.words[j][4] for j in self.lines[n]
                         if self.words[j][2] <= x + 1 and re.search(r"[A-Za-z]", self.words[j][4]))
        return any(_label_fits(k, [own, whole]) for k in keys if k)

    def row_wrap(self, i: int, keys: set[str]) -> bool:
        """Does the row label fit the value's line joined with its wrapped label lines?"""
        n, x = self.line_of[i], self.words[i][0]
        own = self.text_left(n, x)
        above, below = self._wrapped(i)
        own_key = label_key(own)
        if re.search(r"[A-Za-z]{3}", own) and own_key and not any(
                k and (own_key in k or k in own_key) for k in keys):
            return False                                 # the own line names a different row (T-225 review r4)
        texts = []
        if above:
            texts.append(f"{above} {own}")
        if below:
            texts.append(f"{own} {below}")
        if above and below:
            texts.append(f"{above} {own} {below}")
        return any(_label_fits(k, texts) for k in keys if k)

    def occurrences(self, value: str) -> list[int]:
        key = _norm_value(value)
        return self.by_value.get(key) or self.by_value.get(key.rstrip("%")) or []

    def label_on_page(self, key: str) -> bool:
        if self._whole_key is None:
            self._whole_key = label_key(" ".join(w[4] for w in self.words))
        return bool(key) and key in self._whole_key

    # -- chart --------------------------------------------------------------------------------------------------
    def chart_title(self, i: int) -> str:
        """The nearest number-less line above the value in the value's x-band: a chart panel's title."""
        n = self.line_of[i]
        x0, x1 = self.words[i][0], self.words[i][2]
        pad = max(20.0, 4.0 * self.h)
        for m in range(n - 1, max(-1, n - 20), -1):
            if self.line_has_value(m):
                continue
            line = self.lines[m]
            lx0, lx1 = self.words[line[0]][0], max(self.words[j][2] for j in line)
            if lx1 < x0 - pad or lx0 > x1 + pad:
                continue
            text = " ".join(self.words[j][4] for j in line)
            if re.search(r"[A-Za-z]", text):
                return text
        return ""

    def axis_text(self, i: int) -> str:
        """The nearest axis label below the value, over the value's x position (a chart's column)."""
        n = self.line_of[i]
        xc = (self.words[i][0] + self.words[i][2]) / 2
        pad = max(12.0, 2.0 * self.h)
        for m in range(n + 1, min(len(self.lines), n + 9)):
            near = [j for j in self.lines[m]
                    if self.words[j][0] - pad <= xc <= self.words[j][2] + pad and re.search(r"[A-Za-z0-9]", self.words[j][4])]
            text = " ".join(self.words[j][4] for j in near)
            if near and (re.search(r"[A-Za-z]", text) or self.is_header_line(m)):
                return text
        return ""

    def axis_state(self, i: int, header: str) -> bool | None:
        """Does the reader's header name the axis label under the value?  None: no label could be tested."""
        if not _header_tokens(header):
            return None
        label = self.axis_text(i)
        if not label:
            return self.header_above(i, header, below=True)
        return _header_match(header, label)

    # -- header band and column model ---------------------------------------------------------------------------
    def _blank_cell(self, j: int) -> bool:
        """An empty-cell mark ("-", "nil") printed right of its line's row label (not the dash opening "- Owner")."""
        if str(self.words[j][4]).strip().casefold() not in _BLANK:
            return False
        n = self.line_of[j]
        letters = [k for k in self.lines[n] if re.search(r"[A-Za-z]{2}", self.words[k][4])]
        return not letters or self.words[j][0] > max(self.words[k][2] for k in letters)

    def _value_x_band(self, n: int) -> tuple[float, float]:
        nums = [j for j in self.lines[n]                # a digit is required: "- Owner" opens with a dash (T-225)
                if _is_num(self.words[j][4]) and _tok(self.words[j][4]) not in _BLANK
                and re.search(r"\d", self.words[j][4])]
        if nums:                                         # empty-cell marks right of the label widen the band
            nums += [j for j in self.lines[n] if self._blank_cell(j)]
        if not nums:
            nums = self.lines[n]
        return min(self.words[j][0] for j in nums), max(self.words[j][2] for j in nums)

    def header_band(self, n: int) -> list[int]:
        """The header lines of the value's table block, ordered top to bottom.  The nearest strong header line
        above the value (over earlier rows of the same table) starts the band; it runs down to the first data line
        over the value's number columns, so a lower header row that holds no date/unit word ("Increase",
        "Decrease", "Audited") stays in its stack.  Empty when no header is found (prose, a chart)."""
        if n in self._bands:
            return self._bands[n]
        if len(self.line_letters(n)) > 14:            # prose, not a printed table row
            self._bands[n] = []
            return []
        m = n - 1
        vx0, vx1 = self._value_x_band(n)
        pad = max(40.0, 3.0 * self.h)
        while m >= 0 and n - m <= 120:
            if m < n - 1 and min(self.words[j][1] for j in self.lines[m + 1]) \
                    - max(self.words[j][3] for j in self.lines[m]) > max(30.0, 5.0 * self.h):
                m = -1
                break
            # a period word over the value columns: "year" ending a wrapped row label at the left is not a header
            if self.is_header_line(m) and _strong_header([self.words[j] for j in self.lines[m]]) \
                    and any(_is_period_word(self.words[j][4]) and self.words[j][2] >= vx0 - pad
                            and self.words[j][0] <= vx1 + pad for j in self.lines[m]):
                break
            m -= 1
        if m < 0:
            self._bands[n] = []
            return []
        start = m
        while start - 1 >= 0 and self.is_header_line(start - 1) and m - start < 5:
            start -= 1
        # a group row with no period word ("Consolidated | Standalone") right above, over the value columns and
        # printing no figure, belongs to the band: a reader's group name must be checked against it (T-225)
        groups = 0
        while start - 1 >= 0 and groups < 2:
            g = start - 1
            gap = min(self.words[j][1] for j in self.lines[start]) - max(self.words[j][3] for j in self.lines[g])
            over = [j for j in self.lines[g] if self.words[j][2] >= vx0 - pad and self.words[j][0] <= vx1 + pad]
            if gap > 2.5 * self.h or not over or any(self._digit_figure(j) for j in self.lines[g]) \
                    or len(self.line_letters(g)) > 8:
                break
            start, groups = g, groups + 1
        band = list(range(start, m + 1))
        x0, x1 = self._value_x_band(n)
        for h in range(m + 1, n):
            if self.line_has_value(h):
                break
            over = any(self.words[j][0] <= x1 and self.words[j][2] >= x0 for j in self.line_letters(h))
            if self.is_header_line(h) or over:
                band.append(h)
                continue
            break
        band.sort()
        self._bands[n] = band
        return band

    def _block(self, n: int, band: list[int]) -> list[int]:
        """The data lines under a header band, to the next header line or a blank gap."""
        if n in self._blocks:
            return self._blocks[n]
        start, out = band[-1] + 1, []
        prev_y1 = max(self.words[j][3] for j in self.lines[band[-1]])
        for m in range(start, min(len(self.lines), max(n, start) + 40)):
            if self.is_header_line(m) and _strong_header([self.words[j] for j in self.lines[m]]) \
                    and any(_is_period_word(self.words[j][4]) for j in self.lines[m]):
                break
            y0 = min(self.words[j][1] for j in self.lines[m])
            if out and y0 - prev_y1 > max(24.0, 3.0 * self.h):
                break
            out.append(m)
            prev_y1 = max(self.words[j][3] for j in self.lines[m])
        self._blocks[n] = out
        return out

    def _column_centres(self, cols: list[dict[str, Any]]) -> list[float]:
        return [(col["x0"] + col["x1"]) / 2 for col in cols]

    def _header_phrases(self, m: int, cols: list[dict[str, Any]]) -> list[tuple[float, float, str]]:
        """Header phrases on one band line: split on a wide gap or where the next word sits over another column."""
        key = (m, tuple((round(col["x0"], 1), round(col["x1"], 1)) for col in cols))
        if key in self._phrases:
            return self._phrases[key]  # type: ignore[index]
        gap = max(14.0, 1.5 * self.h)
        centres = self._column_centres(cols)
        out: list[tuple[float, float, str]] = []
        cur: list[int] = []
        last_col: int | None = None
        for j in self.lines[m]:
            w = self.words[j]
            centre = (w[0] + w[2]) / 2
            col = min(range(len(cols)), key=lambda k: abs(centres[k] - centre)) if cols else None
            moved = col is not None and last_col is not None and col != last_col
            period = bool(re.search(r"\d", w[4])) or _tok(w[4]) in _MONTHS
            # a period prefix ("Q3", "9M", "H1") after a phrase that already names a year starts a new column's
            # phrase: "Q3 FY21  Q3 FY20^" is two headers, not one (T-225)
            restart = not str(w[4]).strip().startswith("(") and _is_period_part(w[4]) \
                and any(_is_sub_period(self.words[k][4]) for k in cur) \
                and any(_is_year_part(self.words[k][4]) for k in cur)
            # two labels printed touching across a column change ("Standalone|Consolidated") are two phrases:
            # words of one phrase are at least a space apart (T-225 review r3)
            touching = moved and w[0] - self.words[cur[-1]][2] <= 0.15 * self.h if cur else False
            if cur and (w[0] - self.words[cur[-1]][2] > gap or (moved and period) or restart or touching):
                out.append(self._phrase(cur))
                cur = []
            cur.append(j)
            last_col = col
        if cur:
            out.append(self._phrase(cur))
        self._phrases[key] = [p for p in out if re.search(r"[A-Za-z0-9]", p[2])]  # type: ignore[index]
        return self._phrases[key]  # type: ignore[index]

    def _phrase(self, idx: list[int]) -> tuple[float, float, str]:
        return (min(self.words[j][0] for j in idx), max(self.words[j][2] for j in idx),
                " ".join(self.words[j][4] for j in idx))

    def columns_for(self, n: int) -> list[dict[str, Any]]:
        """Number columns under the header band over the value's line, each with the header stack printed over it.
        A header line with fewer phrases than columns is a grouping row: a phrase spans the nearest run of columns
        (a lower row splits the groups)."""
        if n in self._cols:
            return self._cols[n]
        band = self.header_band(n)
        cols: list[dict[str, Any]] = []
        if band:
            nums = [j for m in self._block(n, band) for j in self.lines[m]
                    if _is_num(self.words[j][4]) and _tok(self.words[j][4]) not in _BLANK
                    and re.search(r"\d", self.words[j][4]) and not _is_header_word(self.words[j][4])]
            blanks = [j for m in self._block(n, band) for j in self.lines[m] if self._blank_cell(j)]
            cols = _cluster_columns(nums, self.words, max(8.0, 1.2 * self.h))
            for j in blanks:                      # a dash counts toward the figure column it sits in, never widens it
                bc = (self.words[j][0] + self.words[j][2]) / 2
                for col in cols:
                    if col["x0"] - 0.5 * self.h <= bc <= col["x1"] + 0.5 * self.h:
                        col["n"] += 1
                        break
            counted = [col for col in cols if col["n"] >= 2]
            if counted:
                cols = counted
            centres = self._column_centres(cols)
            for col in cols:
                col["stack"] = []
            low = self._header_phrases(band[-1], cols)
            kinds = [""] * len(cols)
            if low:
                lp = [(p[0] + p[1]) / 2 for p in low]
                for ci, centre in enumerate(centres):
                    kinds[ci] = _period_kind(low[min(range(len(low)), key=lambda k: abs(lp[k] - centre))][2])
            left = min((col["x0"] for col in cols), default=0.0) - self.h
            for m in [m for m in band if not self.title_line(m)]:
                # a phrase wholly left of the number columns ("₹ Crores" over the labels) heads no column (T-225)
                phrases = [p for p in self._header_phrases(m, cols) if p[1] >= left]
                if not phrases:
                    continue
                assign = self._assign_phrases(phrases, centres, kinds)
                for ci, k in enumerate(assign):
                    cols[ci]["stack"].append(phrases[k][2])
        self._cols[n] = cols
        return cols

    @staticmethod
    def _assign_phrases(phrases: list[tuple[float, float, str]], centres: list[float],
                        kinds: list[str]) -> list[int]:
        """Which header phrase belongs to each column.  A grouping row (fewer phrases than columns) splits where
        the lower header row's period kind changes; otherwise each column takes its nearest phrase."""
        pc = [(p[0] + p[1]) / 2 for p in phrases]
        near = [min(range(len(phrases)), key=lambda k: abs(pc[k] - c)) for c in centres]
        if len(phrases) >= len(centres):
            return near
        bounds = [0]
        for k in range(1, len(phrases)):
            mid = (pc[k - 1] + pc[k]) / 2
            default = sum(1 for c in centres if c < mid)
            lo, hi = bounds[-1] + 1, len(centres) - (len(phrases) - k)
            best = min(max(default, lo), hi)
            changes = [b for b in range(lo, hi + 1) if 0 < b < len(kinds) and kinds[b] != kinds[b - 1]]
            if changes and len(centres) > 1:
                # snap only to a kind change lying near the midpoint between the two group phrases (T-225 review
                # r2: a far change moved "Consolidated > Q4FY24" under "Standalone")
                # snap only to the ONE kind change of the range (years then dates); with two or more ("FY24 |
                # Q4FY24 | Q3FY24 | FY23") the midpoint decides (T-225 review r2-r3)
                # snap to the range's ONE kind change, unless a group phrase is printed over a column the snap
                # would give to the other group ("Standalone" over Q4FY23 keeps Q4FY23 Standalone; review r4)
                def contradicts(b: int) -> bool:
                    a0, a1 = phrases[k - 1][0], phrases[k - 1][1]
                    b0, b1 = phrases[k][0], phrases[k][1]
                    tol = 0.25 * min(centres[q + 1] - centres[q] for q in range(len(centres) - 1))
                    return any(b0 - tol <= centres[q] <= b1 + tol for q in range(b)) or                         any(a0 - tol <= centres[q] <= a1 + tol for q in range(b, len(centres)))
                near_mid = [b for b in changes if len(changes) == 1 and not contradicts(b)]
                if near_mid:
                    best = min(near_mid, key=lambda b: abs(b - best))
            bounds.append(best)
        bounds.append(len(centres))
        assign: list[int] = []
        for k in range(len(phrases)):
            assign.extend([k] * (bounds[k + 1] - bounds[k]))
        return assign

    def _near_columns(self, i: int, cols: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The columns in the value's table: within half a page of the value, so a two-page spread's other table
        is not mistaken for a column of this one."""
        xc = (self.words[i][0] + self.words[i][2]) / 2
        return [col for col in cols if abs((col["x0"] + col["x1"]) / 2 - xc) <= 340.0]

    def _column_of(self, i: int, cols: list[dict[str, Any]]) -> int | None:
        x0, x1 = self.words[i][0], self.words[i][2]
        best: tuple[float, int] | None = None
        for ci, col in enumerate(cols):
            overlap = min(x1, col["x1"]) - max(x0, col["x0"])
            if overlap >= -0.5 * self.h and (best is None or overlap > best[0]):
                best = (overlap, ci)
        return best[1] if best else None

    def column_state(self, i: int, header: str) -> bool | None:
        """The band test; where it cannot decide, the word-header test may confirm.  A band test that refuses (a
        reader header naming a number the band never prints) confirms nothing by any rule (T-225 review defect 1)."""
        state = self._band_state(i, header)
        if state == "blocked":
            return None
        if state is not None:
            return bool(state)
        # the band cannot decide (a merged or split column model): the stricter word-header test may confirm, but
        # never calls the cell a reader error there
        if self.word_header_state(i, header) is not True:
            return None
        band = self.header_band(self.line_of[i])
        band_tokens = set(_header_tokens(" ".join(self.words[j][4] for m in band if not self.title_line(m)
                                                  for j in self.lines[m])))
        cols, ci = self._word_columns(i)
        own = set(_header_tokens(" ".join(cols[ci]["stack"]))) if ci is not None else set()
        needed = [t for t in _header_tokens(header) if t in band_tokens and t not in _WORD_STOP]
        return True if all(t in own for t in needed) else None

    def _band_state(self, i: int, header: str) -> bool | str | None:
        """Does the reader's column header name the stack over the value's column?  Every reader word that is
        printed in the band must sit in the value's own stack ("Nine months ended" is printed over the nine-month
        columns only, so it is not part of a quarter column); a reader word printed nowhere in the band (an
        annotation the reader added) is ignored.  None: no header band, or nothing in the band to test against;
        "blocked": the reader header names a number the band does not print."""
        reader = _header_tokens(header)
        if not reader:
            return None
        band = self.header_band(self.line_of[i])
        if not band:
            word = self.word_header_state(i, header)
            if word is not None:
                return word
            cols, _ci = self._word_columns(i)
            if any(col["stack"] for col in cols):
                return None          # the table prints word headers and they do not decide: no looser rule may
            return self.header_above(i, header)
        cols = self._near_columns(i, self.columns_for(self.line_of[i]))
        ci = self._column_of(i, cols) if cols else None
        if ci is None:
            return None
        stacks = [" ".join(col["stack"]) for col in cols]
        vocab = set(_header_tokens(" ".join(stacks)))
        band_tokens = set(_header_tokens(" ".join(self.words[j][4] for m in band if not self.title_line(m)
                                                  for j in self.lines[m])))
        # a reader header naming a number printed nowhere in the band ("Mat 37,2020" copied from a misread layer,
        # where only "2020" is printed) is not the printed header: confirm nothing, by any rule (T-225)
        if any(t.isdigit() and t not in vocab and t not in band_tokens for t in reader):
            return "blocked"
        required = [t for t in reader if t in vocab and t not in _GENERIC]
        if not required:
            return None
        own = set(_header_tokens(stacks[ci]))
        if all(t in own for t in required):
            return True
        for k, other in enumerate(stacks):
            if k != ci and all(t in set(_header_tokens(other)) for t in required):
                return False
        return None

    # -- word headers (T-225): "No. of shares | Amount", no period word, so no header band ----------------------
    def _digit_num(self, j: int) -> bool:
        return _is_num(self.words[j][4]) and bool(re.search(r"\d", self.words[j][4]))

    def _digit_figure(self, j: int) -> bool:
        """A printed figure: a number with a digit that is not a header date/period word."""
        return self._digit_num(j) and not _is_header_word(self.words[j][4])

    def _num_column(self, i: int) -> tuple[float, float, int]:
        """The printed number column holding word ``i``: its x-extent over the numbers of nearby lines that overlap
        it, and the first line of the column (its top data row).  Lines where the column is blank but the table
        prints other numbers do not end the column; two lines with no number at all do."""
        x0, x1, n = self.words[i][0], self.words[i][2], self.line_of[i]
        top = n
        for step in (-1, 1):
            m, misses = n + step, 0
            prev = n
            while 0 <= m < len(self.lines) and misses < 4 and abs(m - n) <= 60:
                a, b = (m, prev) if step < 0 else (prev, m)
                if min(self.words[j][1] for j in self.lines[b]) - max(self.words[j][3] for j in self.lines[a]) \
                        > max(24.0, 3.0 * self.h):
                    break                                # a blank gap: another table
                prev = m
                nums = [j for j in self.lines[m] if self._digit_num(j) and not _is_header_word(self.words[j][4])]
                hit = [j for j in nums if self.words[j][0] <= x1 and self.words[j][2] >= x0]
                if not nums and any(self.words[j][0] <= x1 and self.words[j][2] >= x0 for j in self.lines[m]):
                    near = range(max(0, n - 6), min(len(self.lines), n + 7))
                    spans = [(c["x0"], c["x1"]) for c in _cluster_columns(
                        [j for q in near for j in self.lines[q] if self._digit_figure(j)], self.words,
                        max(8.0, 1.2 * self.h))]
                    covered = sum(1 for a0, a1 in spans if any(self.words[j][0] <= a1 + self.h
                                                              and self.words[j][2] >= a0 - self.h
                                                              for j in self.lines[m]))
                    first = min(sp[0] for sp in spans) if spans else x0
                    labelled = any(self.words[j][2] < first - 3.0 * self.h for j in self.lines[m])
                    if covered >= 2 or not labelled:
                        break                            # words over the columns on a figure-less line: a header
                    misses += 1                          # a labelled sub-row inside the table
                    m += step
                    continue
                if hit:
                    misses = 0
                    x0 = min(x0, *(self.words[j][0] for j in hit))
                    x1 = max(x1, *(self.words[j][2] for j in hit))
                    if step < 0:
                        top = m
                elif not nums:
                    misses += 1
                m += step
        return x0, x1, top

    def _word_columns(self, i: int) -> tuple[list[dict[str, Any]], int | None]:
        """The number columns of the value's table block, each with the words printed over it.  A header word
        belongs to the ONE column whose centre is nearest (never to two), and only header lines above the block's
        top data row count (up to four, stopping at another table's data row)."""
        n = self.line_of[i]
        _x0, _x1, top = self._num_column(i)
        lo, hi = top, n
        while hi + 1 < len(self.lines) and hi - n < 8 and any(self._digit_num(j) for j in self.lines[hi + 1]):
            hi += 1
        nums = [j for m in range(lo, hi + 1) for j in self.lines[m]
                if self._digit_num(j) and not _is_header_word(self.words[j][4])]
        label_end = max((self.words[j][2] for j in self.lines[n] if re.search(r"[A-Za-z]{2}", self.words[j][4])
                         and self.words[j][2] <= self.words[i][0]), default=-1e9)
        nums = [j for j in nums if self.words[j][0] > label_end - 1]       # a number inside a row label is no column
        cols = _cluster_columns(nums, self.words, max(8.0, 1.2 * self.h))
        for col in cols:
            col["stack"] = []
        self._hdr_tokens: set[str] = set()
        self._sibling_tokens: set[str] = set()
        self._left_tokens: set[str] = set()
        if not cols:
            return [], None
        centres = self._column_centres(cols)
        left, right = cols[0]["x0"] - 3.0 * self.h, cols[-1]["x1"] + 3.0 * self.h
        own_x0, own_x1, _top = self._num_column(i)
        prev_y0 = min(self.words[j][1] for j in self.lines[top])
        for m in range(top - 1, max(-1, top - 11), -1):
            line = self.lines[m]
            if prev_y0 - max(self.words[j][3] for j in line) > max(24.0, 3.0 * self.h):
                break                                    # a blank gap ends the header
            prev_y0 = min(self.words[j][1] for j in line)
            if any(self._digit_figure(j) and self.words[j][0] <= own_x1 and self.words[j][2] >= own_x0
                   for j in line):
                break                                    # another table's data row over this column
            line = [j for j in line if not self._digit_figure(j)]   # side prose figures head no column
            self._hdr_tokens |= {t for j in line for t in _header_tokens(self.words[j][4])}
            # whole phrases (words split at a wide gap) go to the nearest column, so a wrapped "Digital Health &
            # Pharmacy Distribution" is not shared word by word with its neighbour
            phrases: list[list[int]] = []
            def nearest(j: int) -> int:
                c = (self.words[j][0] + self.words[j][2]) / 2
                return min(range(len(cols)), key=lambda q: abs(centres[q] - c))
            for j in line:
                gap = self.words[j][0] - self.words[phrases[-1][-1]][2] if phrases else 1e9
                if phrases and (gap < 0 or gap <= max(6.0, 1.2 * self.h)
                                and nearest(j) == nearest(phrases[-1][-1])):
                    phrases[-1].append(j)
                else:
                    phrases.append([j])
            for ph in phrases:
                x0p, x1p = min(self.words[j][0] for j in ph), max(self.words[j][2] for j in ph)
                c = (x0p + x1p) / 2
                if not left <= c <= right:
                    if len(phrases) > 1:                 # a shifted group label beside in-range phrases
                        self._left_tokens |= set(_header_tokens(" ".join(self.words[j][4] for j in ph)))
                    continue
                text = " ".join(self.words[j][4] for j in ph)
                pad = 0.5 * self.h
                over = [q for q in range(len(cols)) if x0p <= cols[q]["x1"] + pad and x1p >= cols[q]["x0"] - pad]
                if not over:                         # between columns: a spanning group over its two neighbours
                    rightq = [q for q in range(len(cols)) if centres[q] >= c]
                    leftq = [q for q in range(len(cols)) if centres[q] < c]
                    over = ([leftq[-1]] if leftq else []) + ([rightq[0]] if rightq else [])
                    sibling = any(ph2 is not ph for ph2 in phrases)
                    if sibling or not over:      # a shifted sibling header ("Standalone  Consolidated"): no one's
                        self._sibling_tokens |= set(_header_tokens(text))
                        continue
                for q in over:
                    cols[q]["stack"].insert(0, text)
        ci = self._column_of(i, cols)
        return cols, ci

    def word_header_state(self, i: int, header: str) -> bool | None:
        """Does the reader's lowest header level ("No. of shares") name the words printed over this value's own
        column and over no other column of the table?  Single letters and digits count ("Segment A", "Tier 2").
        None when the level has no word to test, a number the reader names is not printed over the column, or an
        upper level the reader names sits over another column and not this one."""
        levels = [lv for lv in header.split(">") if lv.strip()]
        if not levels:
            return None
        want = [t for t in _header_tokens(levels[-1]) if t not in _WORD_STOP]
        if not want or not any(len(t) > 1 and not t.isdigit() for t in want):
            return None
        cols, ci = self._word_columns(i)
        if ci is None:
            return None
        stacks = [set(_header_tokens(" ".join(col["stack"]))) for col in cols]
        own = stacks[ci]
        if not own:
            return None
        printed = set().union(*stacks) | getattr(self, "_hdr_tokens", set())   # a group heading no column too
        upper = {t for lv in levels[:-1] for t in _header_tokens(lv) if t not in _WORD_STOP and t in printed}
        rival_tokens = set().union(*(st for k, st in enumerate(stacks) if k != ci)) | getattr(self, "_sibling_tokens", set())
        if any(t not in own and t in rival_tokens for t in upper):
            return None                                  # the reader's group heads another column, not this one
        own_groups = [ph for ph in cols[ci]["stack"] if not set(_header_tokens(ph)) & set(want)]
        if own_groups and any(t not in own and t in getattr(self, "_left_tokens", set()) for t in upper):
            return None      # a group label left of the columns, while this column prints a group of its own
        if any(t.isdigit() and t not in own for t in _header_tokens(header)):
            return None                                  # a number the reader names is not over this column
        rival = any(k != ci and all(t in st for t in want) for k, st in enumerate(stacks))
        if all(t in own for t in want):
            return None if rival else True
        return False if rival else None

    # -- old presence rule (fallback where no header band is found) ---------------------------------------------
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


def _cluster_columns(nums: list[int], words: list[tuple[float, float, float, float, str]],
                     tol: float) -> list[dict[str, Any]]:
    """Group number words into printed columns by their horizontal boxes, left to right."""
    cols: list[dict[str, Any]] = []
    for j in sorted(nums, key=lambda i: (words[i][0] + words[i][2]) / 2):
        x0, x1 = words[j][0], words[j][2]
        if cols and x0 - cols[-1]["x1"] <= tol:
            cols[-1]["x0"] = min(cols[-1]["x0"], x0)
            cols[-1]["x1"] = max(cols[-1]["x1"], x1)
            cols[-1]["n"] += 1
            cols[-1].setdefault("members", []).append(j)
        else:
            cols.append({"x0": x0, "x1": x1, "n": 1, "members": [j]})
    return cols


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


def place(page: Page, cell: dict[str, Any],
          taken: dict[int, tuple[str, str]] | None = None) -> tuple[bool | None, bool | None, int | None, str]:
    """(row_ok, col_ok, word index, how).  ``how`` is ``line`` / ``wrap`` / ``chart``.  None = could not locate.

    ``taken`` maps a word index already claimed by a settled row to that cell's (label key, column key).  A cell of
    the SAME row printed under a DIFFERENT column takes the next occurrence of its value instead of the claimed word
    (T-199): a row that prints 1.23 in two columns must keep both cells."""
    keys = {cell["lk"], label_key(cell["label"])}
    occ = [i for i in page.occurrences(cell["value"])
           if not (taken and i in taken and taken[i][0] == cell["lk"] and taken[i][1] != cell.get("ck", ""))]
    if not occ:
        return None, None, None, ""
    on_row: list[tuple[int, str]] = [(i, "line") for i in occ if page.row_own(i, keys)]
    if not on_row:
        for i in occ:                                 # a chart: the panel title above is the row, the axis label below
            own = page.text_left(page.line_of[i], page.words[i][0])
            if re.search(r"[A-Za-z]{3}", own):       # the value's own line names a row: not a chart value (grader)
                continue
            title = page.chart_title(i)              # the column
            if title and any(_label_fits(k, [title]) for k in keys if k):
                return True, page.axis_state(i, cell["col"]), i, "chart"
        on_row = [(i, "wrap") for i in occ if page.row_wrap(i, keys)]
    if not on_row:
        located = any(page.label_on_page(k) for k in keys)
        return (False if located else None), None, None, ""
    cols = [(page.column_state(i, cell["col"]), i, how) for i, how in on_row]
    for want in (True, None, False):
        hit = [(ok, i, how) for ok, i, how in cols if ok is want]
        if hit:
            return True, want, hit[0][1], hit[0][2]
    return True, None, on_row[0][0], on_row[0][1]


def settle_page(readers: list[list[dict[str, str]]], words: list[tuple[float, float, float, float, str]] | None,
                text: str = "", alt_words: list[tuple[float, float, float, float, str]] | None = None
                ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``alt_words``: OCR word boxes of the same page.  A cell whose value the layer does not print (a scan layer's
    "(359,72)" for 359.72) is placed again on them and confirmed only when they place both its row and column
    (T-225); ``how`` is then ``ocr``."""
    per_reader = [cells_of(r) for r in readers]
    canon = unify_labels(per_reader)
    answering = sum(1 for c in per_reader if c)
    page = Page(words) if words else None
    text_norm = _norm_space(text or " ".join(w[4] for w in words or [])).casefold()
    text_nocomma = text_norm.replace(",", "")
    records: list[dict[str, Any]] = []
    taken: dict[int, tuple[str, str]] = {}
    for ri, cells in enumerate(per_reader):
        for c in cells:
            if c["value"].strip().casefold() in _BLANK:
                continue                                   # an empty cell, not a figure
            c["lk"] = str(canon.get(c["lk"], c["lk"]))
            row_ok, col_ok, at, how = place(page, c, taken) if page else (None, None, None, "")
            if at is not None:                             # the word is claimed: a second column cannot take it
                taken.setdefault(at, (c["lk"], c.get("ck", "")))
            records.append({"ri": ri, "cell": c, "row_ok": row_ok, "col_ok": col_ok, "at": at, "how": how})
    placed: dict[int, list[dict[str, Any]]] = defaultdict(list)
    loose: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        if rec["at"] is not None:
            placed[rec["at"]].append(rec)
        else:
            loose[(rec["cell"]["lk"], rec["cell"]["norm"])].append(rec)
    line_names: dict[int, set[str]] = defaultdict(set)
    line_confirmed: dict[int, set[str]] = defaultdict(set)
    label_lines: dict[str, set[int]] = defaultdict(set)     # a label printed on two lines is two rows (T-199)
    if page:
        for rec in records:
            if rec["at"] is None:
                continue
            n = page.line_of[rec["at"]]
            line_names[n].add(rec["cell"]["lk"])
            label_lines[rec["cell"]["lk"]].add(n)
            if rec["col_ok"] is True:
                line_confirmed[n].add(rec["cell"]["lk"])
    out: list[dict[str, Any]] = []
    for at, given in sorted(placed.items(), key=lambda kv: (page.words[kv[0]][1], page.words[kv[0]][0])):  # type: ignore[union-attr]
        w = page.words[at]  # type: ignore[union-attr]
        by_label = Counter(rec["cell"]["lk"] for rec in given)
        lk = by_label.most_common(1)[0][0]
        mine = [rec for rec in given if rec["cell"]["lk"] == lk]
        agree = len({rec["ri"] for rec in mine})
        names = Counter(rec["cell"]["label"] for rec in mine)
        heads = Counter(rec["cell"]["col"] for rec in mine)
        col_votes = [rec["col_ok"] for rec in mine]
        col_ok = True if any(v is True for v in col_votes) else (False if all(v is False for v in col_votes) else None)
        pick = max(mine, key=lambda rec: (rec["col_ok"] is True, names[rec["cell"]["label"]],
                                          heads[rec["cell"]["col"]]))
        conflict = ""
        if len(by_label) > 1:
            conflict = "two_labels_fit_line"
        elif col_ok is False:
            conflict = "column_elsewhere"
        elif agree < 2 and col_ok is None:
            conflict = "lone_column_unlocated"
        settled = "" if conflict else ("script+position" if agree >= 2 else "position")
        if col_ok is False:
            verdict = "reader_error_column"
        elif conflict == "two_labels_fit_line":
            verdict = "checker_miss"
        elif col_ok is True:
            verdict = "confirmed"
        else:
            verdict = "checker_miss"
        out.append({"row_label": pick["cell"]["label"], "col_header": pick["cell"]["col"],
                    "value_text": pick["cell"]["value"], "unit_text": pick["cell"]["unit"],
                    "table": pick["cell"].get("table", ""), "readers": answering, "agree_n": agree,
                    "row_ok": True, "col_ok": "" if col_ok is None else col_ok, "settled_by": settled,
                    "conflict": conflict, "how": pick["how"], "verdict": verdict,
                    "label_aliases": " || ".join(n for n in names if n != pick["cell"]["label"]),
                    "col_aliases": " || ".join(h for h in heads if h != pick["cell"]["col"]),
                    "line_text": page.row_texts(at)[0], "x0": round(w[0], 1), "y0": round(w[1], 1),  # type: ignore[union-attr]
                    "x1": round(w[2], 1), "y1": round(w[3], 1), "section": pick["cell"].get("section", ""),
                    "label_repeated": len(label_lines.get(lk, ())) > 1})
    for (_lk, _norm), given in loose.items():
        agree = len({rec["ri"] for rec in given})
        names = Counter(rec["cell"]["label"] for rec in given)
        pick = max(given, key=lambda rec: names[rec["cell"]["label"]])
        row_ok = False if any(rec["row_ok"] is False for rec in given) else None
        v = _norm_space(pick["cell"]["value"]).casefold()
        verbatim = bool(v) and (v in text_norm or v.replace(",", "") in text_nocomma)
        if row_ok is False:
            settled, conflict = "", "row_elsewhere"
        elif agree >= 2 and verbatim:
            settled, conflict = "script", ""
        else:
            settled, conflict = "", ("lone_unlocated" if verbatim else "value_not_printed")
        verdict = _loose_verdict(page, pick["cell"], text_norm, text_nocomma, line_names, line_confirmed)
        out.append({"row_label": pick["cell"]["label"], "col_header": pick["cell"]["col"],
                    "value_text": pick["cell"]["value"], "unit_text": pick["cell"]["unit"],
                    "table": pick["cell"].get("table", ""), "readers": answering, "agree_n": agree,
                    "row_ok": "" if row_ok is None else row_ok, "col_ok": "", "settled_by": settled,
                    "conflict": conflict, "how": "", "verdict": verdict,
                    "label_aliases": " || ".join(n for n in names if n != pick["cell"]["label"]),
                    "col_aliases": "", "line_text": "", "x0": "", "y0": "", "x1": "", "y1": "",
                    "section": pick["cell"].get("section", ""),
                    "label_repeated": len(label_lines.get(pick["cell"]["lk"], ())) > 1})
    garbled = layer_garbled(words)
    for rec in out:                                   # T-225: never confirm a misread layer or a malformed value
        if rec["settled_by"] in ("position", "script+position", "script"):
            if garbled:
                rec["settled_by"], rec["conflict"], rec["verdict"] = "", "garbled_layer", "unplaced"
            elif not well_formed(rec["value_text"]):
                rec["settled_by"], rec["conflict"], rec["verdict"] = "", "malformed_value", "unplaced"
    if alt_words and words and not garbled:
        held = {(label_key(r["row_label"]), _norm_value(r["value_text"])) for r in out if r["settled_by"]}
        redo = [rec for rec in out if not rec["settled_by"] and rec["conflict"] in ("value_not_printed",
                                                                                  "lone_unlocated")
                and (label_key(rec["row_label"]), _norm_value(rec["value_text"])) not in held]
        if redo:
            again, _ = settle_page([[{"table": r["table"], "row_label": r["row_label"], "col_header": r["col_header"],
                                      "value": r["value_text"], "unit": r["unit_text"]} for r in redo]], alt_words)
            ok = {(c["row_label"], c["col_header"], c["value_text"]) for c in again if c["settled_by"] == "position"}
            for rec in redo:
                if (rec["row_label"], rec["col_header"], rec["value_text"]) in ok and well_formed(rec["value_text"]):
                    rec.update(settled_by="position", conflict="", verdict="confirmed", how="ocr", row_ok=True,
                               col_ok=True)
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


def _loose_verdict(page: Page | None, cell: dict[str, Any], text_norm: str, text_nocomma: str,
                   line_names: dict[int, set[str]], line_confirmed: dict[int, set[str]]) -> str:
    """Why a cell that could not be placed is an error or a checker miss."""
    keys = [cell["lk"], label_key(cell["label"])]
    keys = [k for k in keys if k]
    v = _norm_space(cell["value"]).casefold()
    verbatim = bool(v) and (v in text_norm or v.replace(",", "") in text_nocomma)
    if page is None:
        return "unplaced" if not (verbatim and any(k in label_key(text_norm) for k in keys)) else "checker_miss"
    occ = page.occurrences(cell["value"])
    if not occ or not any(page.label_on_page(k) for k in keys):
        return "unplaced"
    for j in occ:
        n = page.line_of[j]
        others = {k for k in (line_names.get(n, set()) | line_confirmed.get(n, set()))
                  if k and k != cell["lk"] and not same_label(k, cell["lk"])}
        if others:
            return "reader_error_row"
    return "checker_miss"


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
                         "confirmed": sum(1 for c in cells if c["verdict"] == "confirmed"),
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
            "by_verdict": Counter(r["verdict"] for r in rows), "unread": len(unread_rows), "pages": per_page}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="T-177/T-185: settle reference cells by printed position")
    ap.add_argument("--pages", required=True, type=Path)
    ap.add_argument("--pdf-pages", required=True, type=Path)
    ap.add_argument("--runs", nargs="+", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    s = run(args.pages, args.pdf_pages, args.runs, args.out)
    print(f"cells {s['cells']}, numbers on table lines no reader gave {s['unread']}")
    for status, n in sorted(s["by_status"].items(), key=lambda kv: -kv[1]):
        print(f"  {status}: {n}")
    print("verdicts:")
    for verdict, n in sorted(s["by_verdict"].items(), key=lambda kv: -kv[1]):
        print(f"  {verdict}: {n}")
    for p in s["pages"]:
        print(f"  {p['page_id']} {p['split']:6} {p['doc_type']:13} {p['stratum']:16} cells {p['cells']:4} "
              f"settled {p['settled']:4} confirmed {p['confirmed']:4} open {p['open']:4} unread {p['unread']:4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
