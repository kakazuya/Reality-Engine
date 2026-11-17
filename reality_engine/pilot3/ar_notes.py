"""T-223 (2, 3): two-column notes of the annual report -> ``fin_annual_line`` rows (statement ``NOTE``).

Borrowings (non-current and current), the revenue break-up ('Revenue from operations': sale of products, sale of
services, other operating revenue) and finance costs are printed as a note with two year columns and a total.  The
stores held them only as page text.  No model; the frame is the cash-flow reader's (``ar_statements``):

1. Notes: on every annual-report page, a short, title-like heading line (<= 70 characters, no ':' followed by more words
   after the note number, no sentence words such as 'includes', 'amount of', 'ratio', 'details of') that names the
   note ('16 Long term borrowings', 'Note 11(b) - Financial Liabilities - Borrowings (Current)', '25 Revenue from
   operations', '28 Finance costs') opens it; the note runs until the next numbered heading, a second table printed inside
   it (disaggregation, reconciliation with contract price, geography, terms of repayment, ...: ``_SUBTABLE``) or the
   page end.  A date line ('31st March 2026') is never a heading; a '(Contd.)' heading opens nothing.  On a two-up page
   (two blocks printed side by side), each note region is restricted horizontally to its own block (heading left edge
   minus a small margin up to the next side-by-side block's left edge) before reading columns, units or lines.
2. Columns: the first pair of period-end dates in the note, newer on the left (``ar_statements._columns``), else
   the nearest header printed above the heading in the same horizontal span; a note printed with more than two figure
   columns is not read.
3. Lines: ``ar_statements._read_lines`` (words right of the prior column dropped, wrapped labels joined, page
   furniture and footnotes dropped).
4. Gate, per block and column: the item lines since the block opened (a 'Less:' line printed without a bracket
   is subtracted) add up to the next total line ('Total', 'Sub total', or a line that prints figures and no words,
   '(A)'), within the printed rounding.  A total that adds up the block totals above it plus any loose items printed
   after them is the grand total.  A grand total whose label is a combination of the block markers printed above it
   ('(A)+(B)+(C)', 'Total (a+b)', 'Total (A+B)') stays ``<note>_total`` whatever follows in the note.  A block that
   does not add up writes nothing; a column where two rows would share a line_item writes nothing.
5. Rows: one per item and one per total.  ``line_item`` = ``<note>[:sub]:<item slug>``; the note total
   ``<note>_total[:sub]`` is a marker-combination grand total, another grand total with no figures after it, or a lone
   block with no figures after it in the (sub-)note; every other block total is
   ``<note>[:sub]_subtotal:<caption>_<printed label>``.  A generic 'Borrowings' note split by 'Non-current' /
   'Current' writes ``borrowings_noncurrent`` / ``borrowings_current``; unsplit it is ``borrowings_unclassified`` (never
   read as total debt).  A note printing current and non-current columns side by side (four columns) is refused.  A
   'Total (ii) Current' line closes the block and opens the current sub-note.  An item under a 'Less:' caption line is
   subtracted; an all-zero column never passes the gate.  The unit comes from the lines strictly above the first figure
   line of the note (never from footnotes below the figures), else the nearest unit line above its heading, else the
   page's only unit.  An item is named by its own label; the bare caption above it (never a sentence) is prefixed only
   when the label is a caption's tail ('In rupees') or two items would share a name.  A 'Less:' item is stored negative,
   so a block's items sum to its total.  Unit from the note or page, ``fiscal_year`` from the column date.  Basis from a
   title phrase in the page head ('Notes to the Consolidated Financial Statements', 'Standalone Balance Sheet'), else the
   last such title on an earlier page of the report, never from prose; a report with no consolidated statement is
   standalone outright.  ``known_at`` = the report's filing time, ``source_table='ar_note'``.  One page and column per
   (year, basis, note), items, sub-totals and total together: the year's own report first, else the latest report's
   prior column.

    python -m reality_engine.pilot3.ar_notes run --root D:/RealityEngine/tg_build/measure10 [--stores c18] [--dry --out <dir>]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from reality_engine.pilot3 import ar_statements as A
from reality_engine.pilot3.segments_printed import readable
from reality_engine.v2.page_words import words_for
from reality_engine.v2.reference_geom import lines_of

SOURCE_TABLE = "ar_note"

# note -> heading pattern (searched in the heading line only), checked in this order
NOTES = (
    ("borrowings_noncurrent", re.compile(r"(non\s*[-–]?\s*current|long[- ]term)\s+(financial\s+liabilities\W*)?borrowings|borrowings\W*\(?\s*non\s*[-–]?\s*current", re.I)),
    ("borrowings_current", re.compile(r"(?<!non[- ])(?<!non)\b(current|short[- ]term)\s+(financial\s+liabilities\W*)?borrowings|borrowings\W*\(?\s*current", re.I)),
    ("borrowings_unclassified", re.compile(r"\bborrowings\b", re.I)),   # heading names neither current nor non-current
    ("revenue_from_operations", re.compile(r"revenue\s+from\s+operations", re.I)),
    ("finance_costs", re.compile(r"finance\s+costs?", re.I)),
)
_HEADING = re.compile(r"^\s*(note\s*[-:]?\s*)?\(?\d{1,2}(\.\d{1,2})?\s*(\([a-z]\)|[a-z])?\)?\s*[-:.)]*\s*[A-Za-z]", re.I)
_HEADING_PREFIX = re.compile(r"^\s*(?:note\s*[-:]?\s*)?\(?\d{1,2}(?:\.\d{1,2})?\s*(?:\([a-z]\)|[a-z])?\)?\s*[-:.)]*\s*", re.I)
_PROSE_HEADING = re.compile(r"\b(includes?|amount\s+of|ratios?|details\s+of)\b", re.I)
_ORDINAL = re.compile(r"^\s*\d{1,2}\s*(st|nd|rd|th)\b", re.I)
_TOTAL = re.compile(r"^\W*(sub[- ]?)?total\b", re.I)
_LESS = re.compile(r"^\W*less\b", re.I)
# a column-header or unit line inside the note: never a group caption
_HEADERISH = re.compile(r"particulars|year\s+ended|as\s+at|for\s+the\b|\b(in\s+lakhs?|in\s+crores?|in\s+millions?|amount)\b|"
                        r"\b(march|april|june|september|december)\b|\b20\d\d\b|overview|statutory|reports?\b", re.I)
_CONT = re.compile(r"^\W*(in|from|on|of|by|for|to|with|under|-|–)\s", re.I)
_CONTD = re.compile(r"\(?\s*cont(d|inued)?\b\.*\s*\)?", re.I)
# a second table printed inside the note (disaggregation, reconciliation, terms of repayment): the note ends there
_SUBTABLE = re.compile(r"disaggregat|reconcil|contract\s+(balances|price|assets|liabilit)|timing\s+of|sales\s+channel|"
                       r"geograph|performance\s+obligation|unsatisfied|by\s+(nature|type|market|region|customer)|"
                       r"terms\s+(and|of)\s+(conditions|repayment)|repayment\s+(schedule|terms)|maturity\s+profile|"
                       r"rate\s+of\s+interest|nature\s+of\s+security|reportable\s+segment", re.I)
# the basis is read from a title line only ('Notes to the Consolidated Financial Statements', 'Standalone Balance
# Sheet'), never from prose ('tracked at consolidated level')
_BASIS_TITLE = re.compile(r"notes?\s+(forming\s+part\s+)?(of\s+|to\s+)?(the\s+)?(audited\s+)?(consolidated|stand[- ]?alone)|"
                          r"(consolidated|stand[- ]?alone)\s+(balance\s+sheet|statement\s+of|financial\s+statements|cash\s+flow)",
                          re.I)
_SENTENCE = re.compile(r"\.\s*$|\b(is|are|was|were|has|have|had|being|which|includes?)\b", re.I)


def title_basis(text: str) -> str | None:
    """'consolidated' / 'standalone' named by a title phrase in ``text``; None when none, or both."""
    found = {("consolidated" if m.group(0).lower().find("consolidated") >= 0 else "standalone")
             for m in _BASIS_TITLE.finditer(text or "")}
    return found.pop() if len(found) == 1 else None
_SUBBLOCK = re.compile(r"^\W*(\(?[a-z0-9]{1,3}\)\s*)?(non\s*[-–]?\s*current|current)\b(?!\s+(maturit|portion|tax|liabilit|assets))", re.I)
# a header printing current and non-current columns side by side ('Current   Non-Current'): a four-column note


def four_columns(text: str) -> bool:
    """A short header line naming both 'Non-current' and a separate 'Current' (a four-column note)."""
    nc = len(re.findall(r"non\s*[-–]?\s*current", text, re.I))
    return len(text) < 90 and nc >= 1 and len(re.findall(r"\bcurrent\b", text, re.I)) > nc


# 'Total (ii) Current': a total line printed on the same line as the next sub-block's caption
_SUB_AFTER_TOTAL = re.compile(r"(non\s*[-–]?\s*current|current)\s*$", re.I)


@dataclass
class NoteLine:
    label: str
    values: list
    decimals: int
    quote: str
    page: int


def is_heading(text: str, max_len: int = 70) -> bool:
    """A short, title-like numbered note heading ('27 Finance costs', 'Note 11(b) - Borrowings'); a date line
    ('31st March 2026  31st March 2025') or a numbered prose sentence ('2. Debt-Equity Ratio: Debt (includes ...)')
    is not one."""
    t = text.strip()
    if len(t) > max_len or not _HEADING.search(t) or _ORDINAL.match(t) or A._date_of(t):
        return False
    rest = _HEADING_PREFIX.sub("", t, count=1)
    if re.search(r":\s*[A-Za-z0-9]", rest) or _PROSE_HEADING.search(t):
        return False
    return True


def note_of(text: str) -> str | None:
    """The note a heading line opens, or None.  A '(Contd.)' heading opens nothing: the note's first page holds its
    items and total (a continued half never adds up on its own, and must never stand in for the note)."""
    if not is_heading(text) or _CONTD.search(text):
        return None
    for name, rx in NOTES:
        if rx.search(text):
            return name
    return None


def note_of_row(line_item: str) -> str:
    """The note a row belongs to: 'borrowings_current_subtotal:secured_a' / 'finance_costs_total' /
    'borrowings_total:noncurrent' -> 'borrowings_current' / 'finance_costs' / 'borrowings'."""
    return re.sub(r"_(sub)?total$", "", line_item.split(":")[0])


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:60]


def _split_chunks(words, line: list[int], gap_min: float = 40.0) -> list[list[int]]:
    """Split a printed line into horizontal chunks separated by a gap >= ``gap_min``."""
    if not line:
        return []
    chunks = [[line[0]]]
    for idx in line[1:]:
        if words[idx][0] - words[chunks[-1][-1]][2] >= gap_min:
            chunks.append([idx])
        else:
            chunks[-1].append(idx)
    return chunks


def _line_heading_text(words, line: list[int]) -> str:
    """Line text for heading checks, dropping a far-right unit tag ('(H in lakhs)') separated by a large gap."""
    chunks = _split_chunks(words, line)
    if len(chunks) >= 2 and len(chunks[-1]) <= 4 and A._unit(" ".join(words[i][4] for i in chunks[-1])):
        chunks = chunks[:-1]
    return " ".join(words[i][4] for c in chunks for i in c)


def note_regions(words, lines) -> list[tuple[str, int, int]]:
    """(note, first line index, end line index) for every note heading on the page."""
    texts = [" ".join(words[i][4] for i in ln) for ln in lines]
    heads = []
    for n, (ln, t) in enumerate(zip(lines, texts)):
        ht = _line_heading_text(words, ln)
        name = note_of(ht)
        if name:
            heads.append((n, name))
        elif is_heading(ht, max_len=90) and n > 0:
            heads.append((n, None))         # another note's heading closes the previous one
        else:
            # two-up page: a target heading may start in a right-hand chunk on the same y-line
            for seg in _split_chunks(words, ln)[1:]:
                if (seg_name := note_of(" ".join(words[i][4] for i in seg))):
                    heads.append((n, seg_name))
                    break
    out = []
    for k, (n, name) in enumerate(heads):
        if not name:
            continue
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        end = next((j for j in range(n + 1, end) if _SUBTABLE.search(texts[j])), end)
        out.append((name, n, end))
    return out


def _adds(parts: list[A.Line], total: A.Line, k: int, signed: bool = True) -> bool:
    s = sum(-abs(i.values[k]) if signed and _LESS.search(i.label) else i.values[k] for i in parts)
    tol = 0.5 * 10 ** (-max(i.decimals for i in parts + [total])) * (len(parts) + 1) + 1e-9
    return abs(s - total.values[k]) <= tol


def _block_markers(label: str) -> set[str]:
    found = re.findall(r"\(([a-z0-9]{1,3})\)", label, re.I)
    if found:
        return {m.lower() for m in found}
    m = re.fullmatch(r"(?:(?:sub[- ]?)?total\s*[-:]?\s*)?([a-z]|[ivx]{1,3})", label.strip(), re.I)
    return {m.group(1).lower()} if m else set()


def _combo_markers(label: str) -> list[str]:
    out: list[str] = []
    for m in re.findall(r"\(([a-z0-9]{1,3}(?:\s*\+\s*[a-z0-9]{1,3})+)\)", label, re.I):
        out.extend(p.strip().lower() for p in m.split("+"))
    for m in re.findall(r"\([a-z0-9]{1,3}\)(?:\s*\+\s*\([a-z0-9]{1,3}\))+", label, re.I):
        out.extend(p.lower() for p in re.findall(r"\(([a-z0-9]{1,3})\)", m, re.I))
    if not out:
        for m in re.findall(r"\b([a-z]{1,3}(?:\s*\+\s*[a-z]{1,3})+)\b", label, re.I):
            out.extend(p.strip().lower() for p in m.split("+"))
    return out


def _is_marker_grand(label: str, done: list[A.Line]) -> bool:
    """True when ``label`` combines the block markers printed on ``done`` ('(A)+(B)+(C)', 'Total (a+b)')."""
    combo = _combo_markers(label)
    if len(combo) < 2:
        return False
    above = {m for d in done for m in _block_markers(d.label)}
    return set(combo).issubset(above)


def blocks(lines: list[A.Line], k: int) -> list[tuple[str, list[tuple[str, A.Line]], A.Line, str, str, bool]]:
    """(sub-block, [(group, item)], total, kind, caption, followed) for each total line of one column whose items add
    up to it; ``followed``: figures (or a total that adds up nothing) come after it in the same (sub-)note.
    ``group`` is the bare caption the item is printed under ('Secured', 'Term loans from banks'); kind is 'block',
    or 'grand' for a total that adds up the block totals printed above it since the last grand total; caption is the
    first bare caption of the block ('Secured', 'Unsecured')."""
    out = []
    locked: set[int] = set()          # marker-combination grand totals stay <note>_total whatever follows
    items: list[tuple[str, A.Line]] = []
    done: list[A.Line] = []           # block totals since the last grand total
    sub, group, head = "", "", ""
    for ln in lines:
        label = ln.label.strip()
        v = ln.values[k] if ln.values else None
        if v is None and _SUBBLOCK.search(label) and len(label) < 40:
            sub = "noncurrent" if re.search(r"non", label, re.I) else "current"
            items, group, head = [], "", ""
            continue
        if v is None:
            # a 'Less: Current maturities of long-term debt (refer note 21)' caption counts at any length
            if ((len(label) < 50 or _LESS.search(label)) and readable(label) and not is_heading(label)
                    and not _HEADERISH.search(label) and not _SENTENCE.search(label)):
                group = label.rstrip(":").strip()
                head = head or group
            continue
        if _TOTAL.search(label) or not re.search(r"[A-Za-z]{2}", label):
            parts = [i for _, i in items]
            # a grand total: the block totals above it (and any loose items printed after the last of them) add up
            if ln.values[k] == 0 and all(i.values[k] == 0 for i in parts + done):
                pass                                    # an all-zero column adds up by itself: proves nothing
            elif done and _adds(done + parts, ln, k) and all(readable(i.label) for i in parts):
                if _is_marker_grand(ln.label, done):
                    locked.add(len(out))
                out.append((sub, list(items), ln, "grand", "", False))
                done = []
            elif parts and _adds(parts, ln, k) and all(readable(i.label) for i in parts):
                out.append((sub, list(items), ln, "block", head, False))
                done.append(ln)
            elif parts or done:
                # a total that closes nothing: what came before it is not the whole note
                out = [b[:5] + (True,) if b[0] == sub and idx not in locked else b for idx, b in enumerate(out)]
            items, group, head = [], "", ""
            m = _SUB_AFTER_TOTAL.search(label)
            if m and _TOTAL.search(label):
                sub = "noncurrent" if re.search(r"non", m.group(1), re.I) else "current"
                done = []
            continue
        # figures printed after a block's total, in the same (sub-)note: that block is not the whole note
        out = [b[:5] + (True,) if b[0] == sub and idx not in locked else b for idx, b in enumerate(out)]
        if _LESS.search(group) and not _LESS.search(ln.label):
            # an item under a 'Less:' caption line is subtracted like a 'Less:' item
            ln = A.Line(f"Less: {ln.label}", ln.values, ln.decimals, ln.quote, ln.page, ln.section)
        items.append((group, ln))
    return out


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
    own: bool
    source: str


_NON_LABEL_WORDS = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*$|"
    r"^(as|at|for|the|year|ended|ending|on|in|of|to|current|non|particulars|total|sub|rs|inr|lakhs?|lacs?|crores?|millions?|thousands?|mn|crs?)$",
    re.I,
)


def _columns_above(words, lines, first: int, x_left: float = float("-inf"), x_right: float = float("inf")):
    """The nearest column header printed above the note's heading in its horizontal span."""
    span_lines = [[i for i in ln if x_left <= words[i][0] < x_right] for ln in lines[:first]]
    for j in range(first - 1, -1, -1):
        window = [ln for ln in span_lines[max(j - 1, 0): j + 1] if ln]
        if window:
            cols = A._columns(words, window)
            if cols:
                return cols
    return None


def _heading_span(words, line: list[int], note: str) -> tuple[float, float]:
    """(x_left, x_right) from the heading line: left edge minus margin, and right heading's left edge if two-up."""
    chunks = _split_chunks(words, line)
    h_idx = 0
    if len(chunks) > 1:
        for idx, seg in enumerate(chunks):
            if note_of(" ".join(words[i][4] for i in seg)) == note:
                h_idx = idx
                break
    x_left = words[chunks[h_idx][0]][0] - 20.0
    x_right = float("inf")
    for seg in chunks[h_idx + 1:]:
        if is_heading(" ".join(words[i][4] for i in seg)):
            x_right = words[seg[0]][0] - 6.0
            break
    return x_left, x_right


def _right_block_edge(sub_words, sl: list[list[int]], centres: list[float]) -> float:
    """When a second block sits beside this note to the right of its two columns, return that block's left edge."""
    right_edge = centres[1] + 0.7 * abs(centres[1] - centres[0])
    heading_xs: list[float] = []
    label_xs: list[float] = []
    for ln in sl[1:]:
        for seg in _split_chunks(sub_words, ln, gap_min=30.0)[1:]:
            x0 = sub_words[seg[0]][0]
            if x0 <= right_edge:
                continue
            txt = " ".join(sub_words[i][4] for i in seg)
            if is_heading(txt):
                heading_xs.append(x0)
                break
            alpha = [sub_words[i][4].strip(".,:;-–()[]") for i in seg if re.search(r"[A-Za-z]{2}", sub_words[i][4])]
            if any(not _NON_LABEL_WORDS.match(tok) for tok in alpha):
                label_xs.append(x0)
                break
    if heading_xs:
        return min(heading_xs) - 6.0
    if len(label_xs) >= 3:
        return min(label_xs) - 6.0
    return float("inf")


def _cut_subtable(sub_words, sl: list[list[int]]) -> tuple[list, list[list[int]]]:
    """Stop at the first subsequent heading or sub-table header inside the cropped block."""
    for j in range(1, len(sl)):
        t = " ".join(sub_words[i][4] for i in sl[j])
        ht = _line_heading_text(sub_words, sl[j])
        if is_heading(ht, max_len=90) or _SUBTABLE.search(t):
            sl = sl[:j]
            sub_words = [sub_words[i] for ln in sl for i in ln]
            return sub_words, lines_of(sub_words)
    return sub_words, sl


def _first_figure_line(sub_words, sl: list[list[int]], centres: list[float]) -> int:
    """Index in ``sl`` of the first line holding a column figure (not a date/year column header)."""
    gap = abs(centres[1] - centres[0])
    for j, ln in enumerate(sl):
        vals = []
        for i in ln:
            w = sub_words[i]
            if w[0] > centres[1] + 0.7 * gap or w[0] <= centres[0] - 1.6 * gap:
                continue
            tok = w[4]
            parsed = A.number(tok) if (any(ch.isdigit() for ch in tok) or tok.strip() in A._DASH) else None
            if parsed is None:
                continue
            xc = (w[0] + w[2]) / 2
            d = min(abs(xc - centres[0]), abs(xc - centres[1]))
            if d <= 0.6 * gap:
                vals.append(parsed[0])
        if not vals:
            continue
        txt = " ".join(sub_words[i][4] for i in ln)
        if A._date_of(txt) or (A._HEADER_LINE.search(txt) and all(v == int(v) and 1990 <= abs(v) <= 2100 for v in vals)):
            continue
        return j
    return len(sl)


def read_page(store_db: str, doc_key: str, page: int, known_at: str, doc_basis: str | None) -> tuple[list[Row], list[dict]]:
    pw = words_for(store_db, doc_key, page)
    if not pw.words:
        return [], []
    words = A._norm(pw.words)
    lines = lines_of(words)
    rows, log = [], []
    for note, first, end in note_regions(words, lines):
        x_left, x_right = _heading_span(words, lines[first], note)
        region = [i for ln in lines[first:end] for i in ln]
        sub_words = [words[i] for i in region if x_left <= words[i][0] < x_right]
        sl = lines_of(sub_words)
        sub_words, sl = _cut_subtable(sub_words, sl)
        cols = A._columns(sub_words, sl[:8]) or _columns_above(words, lines, first, x_left, x_right)
        if not cols:
            log.append({"page": page, "note": note, "ok": 0, "why": "no two period-end columns"})
            continue
        if x_right == float("inf"):
            rx = _right_block_edge(sub_words, sl, cols[0])
            if rx < float("inf"):
                x_right = rx
                sub_words = [w for w in sub_words if w[0] < x_right]
                sl = lines_of(sub_words)
                sub_words, sl = _cut_subtable(sub_words, sl)
                cols = A._columns(sub_words, sl[:8]) or _columns_above(words, lines, first, x_left, x_right)
                if not cols:
                    log.append({"page": page, "note": note, "ok": 0, "why": "no two period-end columns"})
                    continue
        # four printed columns (current / non-current per year): not this reader
        nums = [w for w in sub_words if A.number(w[4]) and any(ch.isdigit() for ch in w[4])]
        right_edge = cols[0][1] + 0.7 * abs(cols[0][1] - cols[0][0])
        if sum(1 for w in nums if w[0] > right_edge) >= 3:
            log.append({"page": page, "note": note, "ok": 0, "why": "more than two columns"})
            continue
        if any(four_columns(" ".join(sub_words[i][4] for i in ln)) for ln in sl[:10]):
            log.append({"page": page, "note": note, "ok": 0, "why": "current and non-current columns (four columns)"})
            continue
        # the unit printed above the first figure line of the note (never footnotes below), else the nearest unit
        # line above its heading; the page's first unit only when every unit printed on the page agrees
        fig_idx = _first_figure_line(sub_words, sl, cols[0])
        unit = next((u for j in range(fig_idx - 1, -1, -1)
                     if (u := A._unit(" ".join(sub_words[i][4] for i in sl[j])))), None)
        if not unit:
            unit = next((u for j in range(first - 1, -1, -1)
                         if (u := A._unit(" ".join(words[i][4] for i in lines[j] if x_left <= words[i][0] < x_right)))),
                        None)
        if not unit:
            found = {A._unit(" ".join(words[i][4] for i in ln)) for ln in lines} - {None}
            unit = found.pop() if len(found) == 1 else None
        if not unit:
            log.append({"page": page, "note": note, "ok": 0, "why": "no unit printed"})
            continue
        body = A._read_lines(sub_words, cols[0], page)
        basis = title_basis(" ".join(" ".join(words[i][4] for i in ln) for ln in lines[:12])) or doc_basis
        if basis not in ("standalone", "consolidated"):
            log.append({"page": page, "note": note, "ok": 0, "why": "basis not printed"})
            continue
        ends = cols[1]
        n_ok = 0
        for k in (0, 1):
            fy = A.fiscal_label(ends[k])
            own = ends[k] == max(ends)
            col_rows = []
            found = blocks(body, k)
            # an item is named by its own label; the caption it is printed under is added only where two items of
            # the column would otherwise share a name (the indent that shows where a caption ends is not read)
            base = [_slug(i.label) for b in found for _g, i in b[1]]
            clash = {n for n in base if base.count(n) > 1}
            for sub, items, total, kind, caption, followed in found:
                n_ok += 1
                # a generic 'Borrowings' note split into non-current / current is those two notes
                nm, tag = (f"borrowings_{sub}", "") if note == "borrowings_unclassified" and sub else (note, f":{sub}" if sub else "")
                for group, i in items:
                    own_label = _slug(i.label)
                    tail = bool(_CONT.match(i.label))      # 'In rupees', 'From banks', '- Term loans': a caption's tail
                    slug = _slug(f"{group} {i.label}") if group and (tail or own_label in clash) else own_label
                    # a 'Less:' line is stored negative, so the items of a block sum to its total
                    val = -abs(i.values[k]) if _LESS.search(i.label) else i.values[k]
                    col_rows.append(Row(fy, ends[k], basis, f"{nm}{tag}:{slug}", i.label[:200],
                                    val, unit[0], unit[1], doc_key, page, i.quote[:300], known_at,
                                    f"ar_note_reader: {nm}{tag}, items add up to the printed total", own,
                                    f"{doc_key}#p{page}#{k}"))
                # the note total is the grand total, or the one block of its (sub-)note; every other block total is
                # a sub-total named by its caption and printed label
                same = [b for b in found if b[0] == sub]
                is_total = (kind == "grand" or len(same) == 1) and not followed
                name = (f"{nm}_total{tag}" if is_total
                        else f"{nm}{tag}_subtotal:{_slug(f'{caption} {total.label}') or 'block'}")
                col_rows.append(Row(fy, ends[k], basis, name, total.label[:200] or "Total",
                                    total.values[k], unit[0], unit[1], doc_key, page, total.quote[:300], known_at,
                                    f"ar_note_reader: {nm}{tag} {kind} total", own, f"{doc_key}#p{page}#{k}"))
            # a line item named twice in one column is ambiguous: the column writes nothing
            names = [r.line_item for r in col_rows]
            if len(names) != len(set(names)):
                log.append({"page": page, "note": note, "ok": 0, "why": f"column {k}: a line item named twice"})
                n_ok -= len(found)
                continue
            rows += col_rows
        log.append({"page": page, "note": note, "ok": n_ok, "why": "" if n_ok else "no block adds up"})
    return rows, log


def run_store(db: Path, store: str, dry: bool = False) -> dict:
    conn = sqlite3.connect(db if not dry else f"file:{db.as_posix()}?mode=ro", uri=dry)
    sym, isin = conn.execute("SELECT symbol, isin FROM company LIMIT 1").fetchone()
    docs = conn.execute("SELECT doc_key, known_at, filing_date FROM doc WHERE doc_type='annual_report'").fetchall()
    cand, log = [], []
    heads = re.compile(r"borrowings|revenue\s+from\s+operations|finance\s+costs?", re.I)
    for doc_key, known_at, filing_date in docs:
        pages = conn.execute("SELECT page, text FROM doc_page WHERE doc_key=? ORDER BY page", (doc_key,)).fetchall()
        # a notes page that names no basis takes the basis of the nearest page before it that names one (the
        # standalone and consolidated sections are contiguous); a report with no consolidated statement is standalone
        any_cons = any(re.search(r"consolidated\s+(balance\s+sheet|statement\s+of\s+profit|financial\s+statements)",
                                 t or "", re.I) for _, t in pages)
        last = None if any_cons else "standalone"
        for page, text in pages:
            if any_cons:
                # only a title phrase in the page head moves the running basis, never prose
                last = title_basis((text or "")[:400]) or last
            if not text or not heads.search(text):
                continue
            rows, lg = read_page(str(db), doc_key, page, known_at or filing_date or "", last)
            if not any_cons:
                for r in rows:
                    r.basis = "standalone"        # a report with no consolidated statement is standalone outright
            cand += rows
            for x in lg:
                log.append({"doc_key": doc_key, **x})
    # one report per (year, basis, note): own column first, then the latest report
    # one source per (year, basis, note): items, sub-totals and the total of a note always come from one page and column
    best = {}
    for r in cand:
        key = (r.fiscal_year, r.basis, note_of_row(r.line_item))
        rank = (r.own, r.known_at, r.doc_key, r.page)
        if key not in best or rank > best[key]:
            best[key] = rank
    rows = [r for r in cand if (r.own, r.known_at, r.doc_key, r.page) == best[(r.fiscal_year, r.basis, note_of_row(r.line_item))]]
    if not dry:
        conn.execute("DELETE FROM fin_annual_line WHERE source_table=? AND symbol=?", (SOURCE_TABLE, sym))
        conn.executemany(
            "INSERT INTO fin_annual_line (symbol, isin, fiscal_year, period_end, basis, statement, line_item, caption, "
            "value, unit, scale, doc_key, page, quote, source_db, source_table, source_rowid, known_at, "
            "known_at_source, is_reported, is_derived, definition, period_type) "
            "VALUES (?,?,?,?,?,'NOTE',?,?,?,?,?,?,?,?,'doc_page',?,?,?,'doc.known_at',1,0,?,'FY')",
            [(sym, isin, r.fiscal_year, r.period_end, r.basis, r.line_item, r.caption, r.value, r.unit, r.scale,
              r.doc_key, r.page, r.quote, SOURCE_TABLE, f"{r.doc_key}#p{r.page}", r.known_at, r.definition)
             for r in rows])
        conn.commit()
    conn.close()
    notes = defaultdict(set)
    for r in rows:
        notes[note_of_row(r.line_item)].add(r.fiscal_year)
    return {"store": store, "symbol": sym, "notes_seen": len(log), "notes_ok": sum(1 for x in log if x["ok"]),
            "rows": len(rows), "notes": {k: sorted(v) for k, v in notes.items()}, "log": log, "row_list": rows}


def run(root: Path, stores, dry: bool, out_dir: Path | None) -> list[dict]:
    res = []
    for d in sorted(root.glob("c[0-9][0-9]")):
        db = d / f"{d.name}.db"
        if db.is_file() and (not stores or d.name in stores):
            r = run_store(db, d.name, dry)
            res.append(r)
            print(json.dumps({k: v for k, v in r.items() if k not in ("log", "row_list")}), flush=True)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "note_pages.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["store", "symbol", "doc_key", "page", "note", "blocks_ok", "why"])
            for r in res:
                for x in r["log"]:
                    w.writerow([r["store"], r["symbol"], x["doc_key"], x["page"], x["note"], x["ok"], x["why"]])
        with open(out_dir / "note_rows.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["store", "symbol", "fiscal_year", "basis", "line_item", "caption", "value", "unit", "doc_key",
                        "page", "quote", "known_at", "definition"])
            for r in res:
                for x in r["row_list"]:
                    w.writerow([r["store"], r["symbol"], x.fiscal_year, x.basis, x.line_item, x.caption, x.value, x.unit,
                                x.doc_key, x.page, x.quote, x.known_at, x.definition])
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--root", required=True)
    r.add_argument("--stores", default=None)
    r.add_argument("--dry", action="store_true")
    r.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    res = run(Path(a.root), a.stores.split(",") if a.stores else None, a.dry, Path(a.out) if a.out else None)
    print(json.dumps({k: sum(r[k] for r in res) for k in ("notes_seen", "notes_ok", "rows")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
