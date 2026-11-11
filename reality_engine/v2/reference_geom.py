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
        "x1", "y1"]
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
_DATE_TYPO = re.compile(r"^\d{1,2}[.,\-/]\d{1,2}[.,\-/]\d{2,4}$")


def word_value(text: str) -> str:
    """A printed word as a value key: braces read as brackets ("{367)"), marks and currency signs dropped."""
    t = str(text or "").strip().strip(_STRIP).replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    return _norm_value(t)


_BLANK = {"-", "--", "–", "—", "nil", "na", "n.a.", "n/a", "nm"}


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
    return bool(_QTR.match(t) or _PERIOD.match(t) or _DATE.match(t) or _DATE_TYPO.match(t))


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


_PERIOD_WORDS = {"quarter", "quarters", "month", "months", "year", "years", "ended", "ending", "yearended",
                 "quarterended", "halfyear"}


def _is_period_word(text: str) -> bool:
    t = _tok(text)
    return bool(t) and bool(t in _PERIOD_WORDS or t in _MONTHS or _QTR.match(t) or _PERIOD.match(t)
                        or _DATE.match(t) or _DATE_TYPO.match(t))


def _period_kind(text: str) -> str:
    """What kind of period a header phrase names: a bare year, a month/day date, a quarter or something else."""
    toks = _header_tokens(text)
    if any(t in _MONTHS for t in toks) or any(_DATE_TYPO.match(t) for t in toks) \
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
    def _value_x_band(self, n: int) -> tuple[float, float]:
        nums = [j for j in self.lines[n]
                if _is_num(self.words[j][4]) and _tok(self.words[j][4]) not in _BLANK]
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
        while m >= 0 and n - m <= 120:
            if m < n - 1 and min(self.words[j][1] for j in self.lines[m + 1]) \
                    - max(self.words[j][3] for j in self.lines[m]) > max(30.0, 5.0 * self.h):
                m = -1
                break
            if self.is_header_line(m) and _strong_header([self.words[j] for j in self.lines[m]]) \
                    and any(_is_period_word(self.words[j][4]) for j in self.lines[m]):
                break
            m -= 1
        if m < 0:
            self._bands[n] = []
            return []
        start = m
        while start - 1 >= 0 and self.is_header_line(start - 1) and m - start < 5:
            start -= 1
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
            if cur and (w[0] - self.words[cur[-1]][2] > gap or (moved and period)):
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
                    and not _is_header_word(self.words[j][4])]
            cols = _cluster_columns(nums, self.words, max(8.0, 1.2 * self.h))
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
            for m in band:
                phrases = self._header_phrases(m, cols)
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
            if changes:
                best = min(changes, key=lambda b: abs(b - best))
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
        """Does the reader's column header name the stack over the value's column?  Every reader word that is
        printed in the band must sit in the value's own stack ("Nine months ended" is printed over the nine-month
        columns only, so it is not part of a quarter column); a reader word printed nowhere in the band (an
        annotation the reader added) is ignored.  None: no header band, or nothing in the band to test against."""
        reader = _header_tokens(header)
        if not reader:
            return None
        band = self.header_band(self.line_of[i])
        if not band:
            return self.header_above(i, header)
        cols = self._near_columns(i, self.columns_for(self.line_of[i]))
        ci = self._column_of(i, cols) if cols else None
        if ci is None:
            return None
        stacks = [" ".join(col["stack"]) for col in cols]
        vocab = set(_header_tokens(" ".join(stacks)))
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
        else:
            cols.append({"x0": x0, "x1": x1, "n": 1})
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


def place(page: Page, cell: dict[str, Any]) -> tuple[bool | None, bool | None, int | None, str]:
    """(row_ok, col_ok, word index, how).  ``how`` is ``line`` / ``wrap`` / ``chart``.  None = could not locate."""
    keys = {cell["lk"], label_key(cell["label"])}
    occ = page.occurrences(cell["value"])
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
                text: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    per_reader = [cells_of(r) for r in readers]
    canon = unify_labels(per_reader)
    answering = sum(1 for c in per_reader if c)
    page = Page(words) if words else None
    text_norm = _norm_space(text or " ".join(w[4] for w in words or [])).casefold()
    text_nocomma = text_norm.replace(",", "")
    records: list[dict[str, Any]] = []
    for ri, cells in enumerate(per_reader):
        for c in cells:
            if c["value"].strip().casefold() in _BLANK:
                continue                                   # an empty cell, not a figure
            c["lk"] = str(canon.get(c["lk"], c["lk"]))
            row_ok, col_ok, at, how = place(page, c) if page else (None, None, None, "")
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
    if page:
        for rec in records:
            if rec["at"] is None:
                continue
            n = page.line_of[rec["at"]]
            line_names[n].add(rec["cell"]["lk"])
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
                    "x1": round(w[2], 1), "y1": round(w[3], 1)})
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
