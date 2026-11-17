"""T-223 (2, 3): two-column notes of the annual report -> ``fin_annual_line`` rows (statement ``NOTE``).

Borrowings (non-current and current), the revenue break-up ('Revenue from operations': sale of products, sale of
services, other operating revenue) and finance costs are printed as a note with two year columns and a total.  The
stores held them only as page text.  No model; the frame is the cash-flow reader's (``ar_statements``):

1. Notes: on every annual-report page, a short, title-like heading line (<= 70 characters, no ':' followed by more words
   after the note number, no sentence words such as 'includes', 'amount of', 'ratio', 'details of', and never a
   statement line carrying figures like 'Revenue from Operations 31 59,461.09 49,433.28') that names the note
   ('16 Long term borrowings', 'Note 11(b) - Financial Liabilities - Borrowings (Current)', '25 Revenue from
   operations', '28 Finance costs') opens it.  On a two-up page (two blocks printed side by side), headings are matched
   strictly per chunk (never across a horizontal column gap except a bare note-number prefix beside its title), and
   each note region is cropped horizontally to its heading chunk before reading columns, units or lines.  Inside the
   cropped note, the note runs until the next numbered heading or a second table printed inside it (disaggregation,
   reconciliation, break-up of revenue/interest, transacted price adjustments, 'comprises', 'products-wise', 'details
   of sales': ``_SUBTABLE``); if an outer lettered/roman section ('B) OTHER OPERATING INCOME') resumes after an
   internal sub-table, the sub-table is skipped and the note continues to its true grand total.  A date line ('31st
   March 2026', '31-Mar-2025', '31-Mar-25', 'Mar-25') is never a heading; a '(Contd.)' heading opens nothing.
2. Columns: the first pair of period-end dates in the note, newer on the left (``_columns``, reading '31-Mar-2025' /
   '31-Mar-25' / 'Mar-25' and en-dash variants alongside full dates), else the nearest header printed above the heading
   in the same horizontal span; a note printed with more than two figure columns is not read.
3. Lines: ``ar_statements._read_lines`` (words right of the prior column dropped, wrapped labels joined, page
   furniture and footnotes dropped), dropping wrapped date/header/unit/footnote-prose lines, flushing separately
   around empty-label total lines and bare roman/letter marker captions so neither merges into an adjacent item
   label, and re-keeping empty-label lines that print both figure columns as totals.
4. Gate, per block and column: the item lines since the block opened (a 'Less:' line printed without a bracket
   is subtracted, as is a single 'Current portion of Non-current borrowings...' deduction line closing a block total
   into a net total) add up to the next total line ('Total', 'Sub total', or a line that prints figures and no words,
   '(A)'), within the printed rounding.  A total that adds up ALL block totals and loose items since the (sub-)note
   opened is the grand total (demoting an earlier intermediate grand if a subsequent outer section adds into a larger
   all-items grand total); a second section total that does not add up everything since the (sub-)note opened is a
   block total.  An unlettered trailing block whose total equals the sole preceding unlettered block total with no ~2x
   grand total later is an alternative break-up and is stopped.  A grand total whose label combines block markers
   ('(A)+(B)+(C)', 'Total (a+b)') stays ``<note>_total`` whatever follows.  Two-column item lines with figures always
   set ``followed`` regardless of label length; only single-column stray numbers inside prose never mark a block total
   as ``followed``.  A block that does not add up writes
   nothing; a column where two rows would share a line_item writes nothing; a region where a (sub-)note's items do
   not sum to its ``_total`` writes nothing.
5. Tie-out gate (face statements): every emitted ``_total`` row (``revenue_from_operations_total``,
   ``finance_costs_total``, ``borrowings_noncurrent_total``, ``borrowings_current_total``) is compared in rupees against
   the held face-statement candidates for ``(fiscal_year, basis)`` from ``fin_annual_line`` (statement 'P&L'/'BS',
   ``period_type='FY'``, preferring the year's own filing then ``facts`` -> ``ar_facts`` -> others, verifying revenue
   quote/caption is revenue from operations and not 'Total Revenue' / 'Total Income') and ``fin_quarter_printed``
   full-year columns (``lower(period_type)='fy'`` and ``column_role IN ('ytd', 'prior_ytd', 'last_fy')``, dropping
   malformed raw tokens and ``unchecked`` 0.0/``last_fy`` rows).  Candidates are ranked by own filing (Q4 ``ytd`` /
   own-year AR), checked status (``sum_ok`` / ``xbrl_ok`` / ``repeat_ok``), then earlier ``known_at``; when several
   face candidates disagree, the note ties if it matches any CHECKED one (never an unchecked non-primary candidate
   alone).  Tolerance is the printed rounding of the larger unit (e.g. 0.5 lakh or 0.01 crore) + 0.1%.  When items add
   up, the gap is <= 1% of the face, the total is not captioned 'Sub-total', and the total is the last figure line of the
   note with no '(Contd.)' continuation on the next page, an XBRL candidate of another filing is marked ``'face figure
   differs: <value> <source>'``; otherwise a disagreeing column writes nothing (``'total does not tie to the
   statement'``); a note with no face figure held appends ``'; not tied to a statement figure'``.
6. Unit & rows: unit is read only from unit-phrase lines ('(Rs in lakhs)', 'All amounts are in ...', '` in Crores'),
   never from prose sentences containing an amount ('Pledge of FDR of Rs. 3.70 Crores'), falling back to the unit
   declared at the start of the same-basis notes section when the page prints no other unit.  One row per item and one
   per total; slugs trim on word boundaries (up to 96 chars); sub-totals fall back to the caption above instead of
   ``subtotal:subtotal``.  Generic 'Borrowings' notes are classified by the nearest Balance-Sheet section heading above
   ('NON-CURRENT LIABILITIES' / 'CURRENT LIABILITIES'), else split by 'Non-current' / 'Current' sub-blocks, and
   ``borrowings_unclassified`` never displaces a classified note for the same ``(fiscal_year, basis)``.  Ranking: tied
   first, then own column, latest report, and lower page number within a document.

    python -m reality_engine.pilot3.ar_notes run --root D:/RealityEngine/tg_build/measure10 [--stores c18] [--dry --out <dir>]
"""
from __future__ import annotations

import argparse
import calendar
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
_PROSE_HEADING = re.compile(r"\b(includes?|amount\s+of|ratios?|details\s+of|maturity\s+(?:profile|analysis))\b", re.I)
_ORDINAL = re.compile(r"^\s*\d{1,2}\s*(st|nd|rd|th)\b", re.I)
_TOTAL = re.compile(r"^\W*(sub[- ]?)?total\b", re.I)
_LESS = re.compile(r"^\W*less\b", re.I)
_DEDUCT_LINE = re.compile(r"^\W*(?:less\b|current\s+(?:portion|maturit)|deduct|transferred\s+to\b)", re.I)
# a column-header or unit line inside the note: never a group caption
_HEADERISH = re.compile(r"particulars|year\s+ended|as\s+at|for\s+the\b|\b(in\s+lakhs?|in\s+crores?|in\s+millions?|amount)\b|"
                        r"\b(march|april|june|september|december)\b|\b20\d\d\b|overview|statutory|reports?\b", re.I)
_CONT = re.compile(r"^\W*(in|from|on|of|by|for|to|with|under|-|–)\s", re.I)
_CONTD = re.compile(r"\(?\s*cont(d|inued)?\b\.*\s*\)?", re.I)
# a second table printed inside the note (disaggregation, reconciliation, terms of repayment, break-up, comprises):
# skipped if an outer lettered/roman section (e.g. 'B) OTHER OPERATING INCOME') resumes after it, else ends the note
_SUBTABLE = re.compile(r"disaggregat|reconcil|contract\s+(balances|price|assets|liabilit)|timing\s+of|sales\s+channel|"
                       r"geograph|performance\s+obligation|unsatisfied|by\s+(nature|type|market|region|customer)|"
                       r"terms\s+(and|of)\s+(conditions|repayment)|repayment\s+(schedule|terms)|maturity\s+(profile|analysis)|"
                       r"rate\s+of\s+interest|nature\s+of\s+security|reportable\s+segment|"
                       r"break[- ]?up\s+of\b|transacted\s+price|(?:contract|transacted|price)\s+adjustments?|"
                       r"\bcomprises?\b|products?[- ]?wise|details\s+of\s+(?:sales|revenue|borrowings|finance\s+costs?)", re.I)
# Balance-Sheet section headers above an unclassified Borrowings note ('NON-CURRENT LIABILITIES', 'CURRENT LIABILITIES')
_BS_SECTION = re.compile(r"^\s*(?:[ivx0-9a-z]{1,3}[.)]\s+)?(non\s*[-–]?\s*current\s+liabilities|current\s+liabilities)\b", re.I)
_BS_RESET = re.compile(r"^\s*(?:[ivx0-9a-z]{1,3}[.)]\s+)?(?:(?:non\s*[-–]?\s*current\s+|current\s+)?assets|equity|shareholders'?\s+funds)\s*$", re.I)
_BARE_NOTE_NUM = re.compile(r"^(?:note\s*[-:]?\s*)?\(?\d{1,2}(?:\.\d{1,2})?(?:\([a-z]\)|[a-z])?\)?[-:.)]*$", re.I)
# the basis is read from a title line only ('Notes to the Consolidated Financial Statements', 'Standalone Balance
# Sheet'), never from prose ('tracked at consolidated level')
_BASIS_TITLE = re.compile(r"notes?\s+(forming\s+part\s+)?(of\s+|to\s+)?(the\s+)?(audited\s+)?(consolidated|stand[- ]?alone)|"
                          r"(consolidated|stand[- ]?alone)\s+(balance\s+sheet|statement\s+of|financial\s+statements|cash\s+flow)",
                          re.I)
_SENTENCE = re.compile(r"\.\s*$|\b(is|are|was|were|has|have|had|being|which|includes?)\b", re.I)
_PROSE_LINE = re.compile(r"\b(is|are|was|were|has|have|had|being|which|includes?|shall|will|carries|repayable)\b", re.I)


def title_basis(text: str) -> str | None:
    """'consolidated' / 'standalone' named by a title phrase in ``text``; None when none, or both."""
    found = {("consolidated" if m.group(0).lower().find("consolidated") >= 0 else "standalone")
             for m in _BASIS_TITLE.finditer(text or "")}
    return found.pop() if len(found) == 1 else None
_SUBBLOCK = re.compile(r"^\W*(?:\(?[a-z0-9]{1,3}[.):]\s*)?(non\s*[-–]?\s*current|current)\b(?!\s+(maturit|portion|tax|liabilit|assets))", re.I)
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


# Period-end dates including abbreviated forms ('31-Mar-2025', '31–Mar–2025', '31-Mar-25', 'Mar-25').
_DASH_SEP = r"[-–—./]"
_DATE_RES = (
    re.compile(
        rf"(?<!\d)(?<![A-Za-z][-.–—/])(\d{{1,2}})\s*(?:st|nd|rd|th)?(?:\s*{_DASH_SEP}\s*|\s+)"
        rf"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
        rf"(?:[,.]\s*|\s*{_DASH_SEP}\s*|\s+)(20\d\d|[1-3]\d)(?!\d)",
        re.I,
    ),
    re.compile(
        rf"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
        rf"(?:\s*{_DASH_SEP}\s*|\s+)(\d{{1,2}})\s*(?:st|nd|rd|th)?"
        rf"(?:[,.]\s*|\s*{_DASH_SEP}\s*|\s+)(20\d\d|[1-3]\d)(?!\d)",
        re.I,
    ),
    re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d\d)(?!\d)"),
)
_MONTH_YEAR_RE = re.compile(
    rf"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    rf"(?:\s*{_DASH_SEP}\s*(20\d\d|[1-3]\d)|\s+(20\d\d))(?![\w%])",
    re.I,
)
_DATE_FILLER = re.compile(r"\b(as\s+at|for\s+the|year\s+ended|period\s+ended|particulars|notes?(?:\s+no\.?)?|description|sr\.?\s*no\.?)\b|[-–—.,:/()]", re.I)


def _date_of(text: str) -> list[tuple[int, int, str]]:
    """(start, end, ISO date) of every period-end date printed in ``text``."""
    out: list[tuple[int, int, str]] = []
    for n, rx in enumerate(_DATE_RES):
        for m in rx.finditer(text):
            if any(not (m.end() <= s or m.start() >= e) for s, e, _ in out):
                continue
            g = m.groups()
            try:
                if n == 0:
                    d, mo, y = int(g[0]), A._MONTHS[g[1][:3].lower()], (int(g[2]) if len(g[2]) == 4 else 2000 + int(g[2]))
                elif n == 1:
                    mo, d, y = A._MONTHS[g[0][:3].lower()], int(g[1]), (int(g[2]) if len(g[2]) == 4 else 2000 + int(g[2]))
                else:
                    d, mo, y = int(g[0]), int(g[1]), int(g[2])
                if 1 <= d <= 31 and 1 <= mo <= 12:
                    out.append((m.start(), m.end(), f"{y:04d}-{mo:02d}-{d:02d}"))
            except (KeyError, ValueError):
                continue
    for m in _MONTH_YEAR_RE.finditer(text):
        if any(not (m.end() <= s or m.start() >= e) for s, e, _ in out):
            continue
        mo_s, y_dash, y_space = m.groups()
        mo = A._MONTHS[mo_s[:3].lower()]
        ys = y_dash or y_space
        y = int(ys) if len(ys) == 4 else 2000 + int(ys)
        d = calendar.monthrange(y, mo)[1]
        out.append((m.start(), m.end(), f"{y:04d}-{mo:02d}-{d:02d}"))
    return sorted(out)


def _is_date_chunk(text: str) -> bool:
    dates = _date_of(text)
    if not dates:
        return False
    pos, rest = 0, []
    for s, e, _ in dates:
        rest.append(text[pos:s])
        pos = e
    rest.append(text[pos:])
    return not _DATE_FILLER.sub("", "".join(rest)).strip()


def is_heading(text: str, max_len: int = 70) -> bool:
    """A short, title-like numbered note heading ('27 Finance costs', 'Note 11(b) - Borrowings'); a date line
    ('31st March 2026  31st March 2025', '31-Mar-2025  31-Mar-2024'), a numbered prose sentence
    ('2. Debt-Equity Ratio: Debt (includes ...)'), or a statement line carrying figures
    ('Revenue from Operations 31 59,461.09 49,433.28') is not one."""
    t = text.strip()
    if len(t) > max_len or not _HEADING.search(t) or _ORDINAL.match(t) or _date_of(t):
        return False
    rest = _HEADING_PREFIX.sub("", t, count=1)
    if re.search(r":\s*[A-Za-z0-9]", rest) or _PROSE_HEADING.search(t):
        return False
    clean_rest = re.sub(r"\((?:refer|note|see|schedule|annexure)[^)]*\)", "", rest, flags=re.I)
    fig_toks = [tok for tok in clean_rest.split() if any(ch.isdigit() for ch in tok) and A.number(tok) is not None]
    if len(fig_toks) >= 2 or any(re.search(r"\d\.\d{2}\b|,\d{3}\b", tok) for tok in fig_toks):
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


def _slug(label: str, limit: int = 96) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if len(s) <= limit:
        return s
    cut = s[:limit + 1].rfind("_")
    return s[:cut] if cut >= limit // 2 else s[:limit]


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


def _heading_segs(words, line: list[int]) -> list[list[int]]:
    """Horizontal chunks of ``line`` for heading detection: merge a bare note number ('24.') only with the title
    chunk immediately beside it, never merging two side-by-side blocks, and drop trailing unit/date chunks."""
    chunks = _split_chunks(words, line)
    if len(chunks) >= 2 and _BARE_NOTE_NUM.fullmatch(" ".join(words[i][4] for i in chunks[0]).strip()):
        chunks = [chunks[0] + chunks[1]] + chunks[2:]
    while len(chunks) >= 2:
        tail = " ".join(words[i][4] for i in chunks[-1])
        if (len(chunks[-1]) <= 4 and A._unit(tail)) or _is_date_chunk(tail):
            chunks = chunks[:-1]
        else:
            break
    return chunks


def _line_heading_text(words, line: list[int]) -> str:
    """Line text for single-column heading checks, dropping far-right unit or date header chunks."""
    chunks = _split_chunks(words, line)
    while len(chunks) >= 2:
        tail = " ".join(words[i][4] for i in chunks[-1])
        if (len(chunks[-1]) <= 4 and A._unit(tail)) or _is_date_chunk(tail):
            chunks = chunks[:-1]
        else:
            break
    return " ".join(words[i][4] for c in chunks for i in c)


def note_regions(words, lines) -> list[tuple[str, int, int]]:
    """(note, first line index, end line index) for every note heading on the page, matched per chunk."""
    heads: list[tuple[int, str | None, int, int]] = []  # (line_idx, name_or_None, chunk_idx, n_chunks)
    for n, ln in enumerate(lines):
        segs = _heading_segs(words, ln)
        matched = False
        for idx, seg in enumerate(segs):
            seg_txt = " ".join(words[i][4] for i in seg)
            if (seg_name := note_of(seg_txt)):
                heads.append((n, seg_name, idx, len(segs)))
                matched = True
                break
        if not matched and n > 0:
            for idx, seg in enumerate(segs):
                seg_txt = " ".join(words[i][4] for i in seg)
                if is_heading(seg_txt, max_len=90):
                    heads.append((n, None, idx, len(segs)))
                    break
    out = []
    for k, (n, name, idx, n_segs) in enumerate(heads):
        if not name:
            continue
        x0 = words[_heading_segs(words, lines[n])[idx][0]][0]
        end = len(lines)
        for m_n, _m_name, m_idx, m_n_segs in heads[k + 1:]:
            m_x0 = words[_heading_segs(words, lines[m_n])[m_idx][0]][0]
            # on a two-up line, a heading in a different horizontal column does not close this note
            if (n_segs > 1 or m_n_segs > 1) and abs(m_x0 - x0) > 150.0:
                continue
            end = m_n
            break
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
    up to it; ``followed``: non-prose figures (or a total that adds up nothing) come after it in the same (sub-)note.
    ``group`` is the bare caption the item is printed under ('Secured', 'Term loans from banks'); kind is 'block',
    or 'grand' for the note's single grand total that adds up ALL block totals and loose items since the (sub-)note
    opened; caption is the first bare caption of the block ('Secured', 'Unsecured')."""
    out = []
    locked: set[int] = set()          # marker-combination grand totals stay <note>_total whatever follows
    items: list[tuple[str, A.Line]] = []
    all_items: list[A.Line] = []      # every item in the current (sub-)note since it opened
    done: list[A.Line] = []           # block totals since the last grand total
    sub, group, head = "", "", ""
    in_note_foot = False
    for ln_i, ln in enumerate(lines):
        label = ln.label.strip()
        v = ln.values[k] if ln.values else None
        if v is None and _SUBBLOCK.search(label) and len(label) < 40:
            sub = "noncurrent" if re.search(r"non", label, re.I) else "current"
            items, all_items, group, head = [], [], "", ""
            in_note_foot = False
            continue
        if v is None:
            if out and _FOOTNOTE_HEAD.match(label):
                in_note_foot = True
                continue
            # a 'Less: Current maturities of long-term debt (refer note 21)' caption counts at any length
            if ((len(label) < 50 or _LESS.search(label)) and readable(label) and not is_heading(label)
                    and not _HEADERISH.search(label) and not _SENTENCE.search(label) and not _date_of(label)):
                group = label.rstrip(":").strip()
                head = head or group
            continue
        if _TOTAL.search(label) or not re.search(r"[A-Za-z]{2}", label):
            parts = [i for _, i in items]
            # a grand total: the block totals above it (and any loose items printed after the last of them) add up,
            # AND it accounts for every item since the (sub-)note opened (a second section total without that is a block)
            if ln.values[k] == 0 and all(i.values[k] == 0 for i in parts + done):
                pass                                    # an all-zero column adds up by itself: proves nothing
            elif done and _adds(done + parts, ln, k) and all(readable(i.label) for i in parts):
                whole_note = _adds(all_items, ln, k) and not any(
                    b[0] == sub and b[3] == "grand" for b in out
                )
                if whole_note:
                    if _is_marker_grand(ln.label, done):
                        locked.add(len(out))
                    out.append((sub, list(items), ln, "grand", "", False))
                    done = []
                else:
                    out.append((sub, list(items), ln, "block", head, False))
                    done = [ln]
            elif (any(b[0] == sub and b[3] == "grand" for b in out)
                  and _adds(all_items, ln, k) and all(readable(i.label) for i in parts)
                  and _adds([next(b[2] for b in reversed(out) if b[0] == sub and b[3] == "grand")] + done + parts, ln, k)):
                # an earlier block total matched all items seen up to that point, before another section (e.g. 'B)')
                # arrived and summed into the true note grand total: demote the earlier one to 'block'
                g_idx = max(idx for idx, b in enumerate(out) if b[0] == sub and b[3] == "grand")
                gb = out[g_idx]
                fallback_cap = gb[4] or (gb[1][0][0] if gb[1] else "") or (gb[1][0][1].label if gb[1] else "")
                out[g_idx] = (gb[0], gb[1], gb[2], "block", fallback_cap, True)
                locked.discard(g_idx)
                if _is_marker_grand(ln.label, [gb[2]] + done):
                    locked.add(len(out))
                out.append((sub, list(items), ln, "grand", head, False))
                done = []
            elif parts and _adds(parts, ln, k) and all(readable(i.label) for i in parts):
                # an unlettered trailing block whose total equals the sole preceding unlettered block total (with no
                # grand total ~2x later in the column) is an alternative break-up of the same note total: stop here
                if (len(done) == 1 and len(out) == 1 and out[0][0] == sub and out[0][3] == "block"
                        and _adds([done[0]], ln, k) and not _block_markers(done[0].label) and not _block_markers(ln.label)):
                    later_grand = any(
                        _TOTAL.search(rem.label) and rem.values and rem.values[k] is not None
                        and abs(rem.values[k]) > 1.5 * abs(ln.values[k])
                        for rem in lines[ln_i + 1:]
                    )
                    if not later_grand:
                        out = [b[:5] + (False,) if idx not in locked else b for idx, b in enumerate(out)]
                        break
                out.append((sub, list(items), ln, "block", head, False))
                done.append(ln)
            elif (done and len(parts) == 1 and _DEDUCT_LINE.search(parts[0].label) and readable(parts[0].label)
                  and abs((sum(d.values[k] for d in done) - abs(parts[0].values[k])) - ln.values[k])
                  <= 0.5 * 10 ** (-max(i.decimals for i in done + parts + [ln])) * (len(done) + 2) + 1e-9):
                # a single deduction line ('Current portion of Non-current borrowings...') after a block total
                # subtracted to reach the net total (c85 p188): store it negative so items sum cleanly to total
                neg = A.Line(parts[0].label if _LESS.search(parts[0].label) else f"Less: {parts[0].label}",
                             parts[0].values, parts[0].decimals, parts[0].quote, parts[0].page, parts[0].section)
                items = [(items[0][0], neg)]
                all_items[-1] = neg
                whole_note = _adds(all_items, ln, k) and not any(b[0] == sub and b[3] == "grand" for b in out)
                if whole_note:
                    out.append((sub, list(items), ln, "grand", head, False))
                    done = []
                else:
                    out.append((sub, list(items), ln, "block", head, False))
                    done = [ln]
            elif not label:
                # an unnamed figures-only line that does not close the open block is a partial sub-total (e.g. for
                # one caption inside a larger block): leave items intact so the block's Total still sums them
                continue
            elif parts or done:
                # a total that closes nothing: what came before it is not the whole note
                out = [b[:5] + (True,) if b[0] == sub and idx not in locked else b for idx, b in enumerate(out)]
            items, group, head = [], "", ""
            m = _SUB_AFTER_TOTAL.search(label)
            if m and _TOTAL.search(label):
                sub = "noncurrent" if re.search(r"non", m.group(1), re.I) else "current"
                all_items, done = [], []
            continue
        # figures printed after a block's total, in the same (sub-)note: that block is not the whole note
        # a two-column item line with >8 words still sets followed; prose/footnotes and single-column prose do not
        both_cols = len(ln.values) >= 2 and ln.values[0] is not None and ln.values[1] is not None
        if (not in_note_foot and not _PROSE_LINE.search(label) and not _FOOTNOTE_START.match(label)
                and (both_cols or len(label.split()) <= 8)):
            out = [b[:5] + (True,) if b[0] == sub and idx not in locked else b for idx, b in enumerate(out)]
        if _LESS.search(group) and not _LESS.search(ln.label):
            # an item under a 'Less:' caption line is subtracted like a 'Less:' item
            ln = A.Line(f"Less: {ln.label}", ln.values, ln.decimals, ln.quote, ln.page, ln.section)
        items.append((group, ln))
        all_items.append(ln)
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
    tie_status: str = "no_face"


_NON_LABEL_WORDS = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*$|"
    r"^(as|at|for|the|year|ended|ending|on|in|of|to|current|non|particulars|total|sub|rs|inr|lakhs?|lacs?|crores?|millions?|thousands?|mn|crs?)$",
    re.I,
)


def _columns(words, lines: list[list[int]]) -> tuple[list[float], list[str]] | None:
    """Centres (x) of the current and prior columns and their period ends, using ``_date_of``."""
    for n, line in enumerate(lines[:30]):
        text, spans = A._spans(words, line)
        dates = _date_of(text)
        dates = [d for n_, d in enumerate(dates)
                 if not (n_ + 1 < len(dates) and re.fullmatch(r"\s*(to|-|–|—)\s*", text[d[1]:dates[n_ + 1][0]], re.I))]
        if dates and re.fullmatch(r"\s*(to|-|–|—)\s*", text[dates[-1][1]:], re.I) and n + 1 < len(lines):
            below, _ = A._spans(words, lines[n + 1])
            bd = _date_of(below)
            if bd:
                dates[-1] = (dates[-1][0], dates[-1][1], bd[0][2])
        for (a0, b0, e0), (a1, b1, e1) in zip(dates, dates[1:]):
            c0, c1 = A._centre(words, spans, a0, b0), A._centre(words, spans, a1, b1)
            if c0 is not None and c1 is not None and c1 > c0 and e0 > e1:
                return [c0, c1], [e0, e1]
        fys = [(i, int(m.group(1))) for i in line
               if (m := re.fullmatch(r"(?:FY\s*)?(20\d\d)\s*-\s*\d{2,4}", words[i][4].strip(" ,.)")))]
        if len(fys) == 2 and fys[0][1] == fys[1][1] + 1:
            centres = [(words[i][0] + words[i][2]) / 2 for i, _ in fys]
            return centres, [f"{fys[0][1] + 1:04d}-03-31", f"{fys[1][1] + 1:04d}-03-31"]
        years = [(i, int(words[i][4].strip(" ,.)")[-4:])) for i in line
                 if re.fullmatch(r"20\d\d", words[i][4].strip(" ,.)"))]
        if len(years) == 2 and years[0][1] == years[1][1] + 1 and n > 0:
            above, _ = A._spans(words, lines[n - 1])
            mo = next((v for k, v in A._MONTHS.items() if re.search(rf"\b{k}", above, re.I)), 3)
            text_days = re.findall(r"(\d{1,2})\s*,", text)
            day = int(text_days[0]) if text_days else (31 if mo in (1, 3, 5, 7, 8, 10, 12) else 30)
            centres = []
            for i, _ in years:
                j = line.index(i)
                left = words[line[j - 1]][0] if j > 0 and re.fullmatch(r"\d{1,2}(st|nd|rd|th)?,?", words[line[j - 1]][4]) else words[i][0]
                centres.append((left + words[i][2]) / 2)
            return centres, [f"{years[0][1]:04d}-{mo:02d}-{day:02d}", f"{years[1][1]:04d}-{mo:02d}-{day:02d}"]
    return None


def _columns_above(words, lines, first: int, x_left: float = float("-inf"), x_right: float = float("inf")):
    """The nearest column header printed above the note's heading in its horizontal span."""
    span_lines = [[i for i in ln if x_left <= words[i][0] < x_right] for ln in lines[:first]]
    for j in range(first - 1, -1, -1):
        window = [ln for ln in span_lines[max(j - 1, 0): j + 1] if ln]
        if window:
            cols = _columns(words, window)
            if cols:
                return cols
    return None


def _heading_span(words, line: list[int], note: str) -> tuple[float, float]:
    """(x_left, x_right) from the heading line: left edge minus margin, and right heading's left edge if two-up."""
    chunks = _heading_segs(words, line)
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


_OUTER_A = re.compile(r"^\s*(?:\([AI1]\)|[AI][.)])\s+[A-Za-z]")
_OUTER_CAPS_CONT = re.compile(r"^\s*(?:\([B-Z]\)|[B-Z]\)|(?:II|III|IV|V)[.)])\s+[A-Z]{2,}")
_OUTER_TITLE_CONT = re.compile(r"^\s*(?:\([B-Z]\)|[B-Z]\)|(?:II|III|IV|V)[.)])\s+[A-Z]")


def _cut_subtable(sub_words, sl: list[list[int]]) -> tuple[list, list[list[int]]]:
    """Stop at the first subsequent heading; skip an internal sub-table if an outer section (e.g. 'B) OTHER...')
    resumes after it, otherwise stop at the sub-table."""
    for j in range(1, len(sl)):
        segs0 = _heading_segs(sub_words, sl[j])[0]
        if is_heading(" ".join(sub_words[i][4] for i in segs0), max_len=90):
            sl = sl[:j]
            sub_words = [sub_words[i] for ln in sl for i in ln]
            return sub_words, lines_of(sub_words)
    texts = [" ".join(sub_words[i][4] for i in ln) for ln in sl]
    kept: list[list[int]] = []
    outer_a_before = False
    j = 0
    while j < len(sl):
        t = texts[j]
        fig_count = sum(1 for tok in t.split() if re.search(r"\d\.\d|,\d{3}", tok))
        if j > 0 and _SUBTABLE.search(t) and not _TOTAL.search(t) and fig_count < 2:
            resume = None
            for k in range(j + 1, len(sl)):
                kt = texts[k]
                if _SUBTABLE.search(kt) or _TOTAL.search(kt):
                    continue
                if _OUTER_CAPS_CONT.match(kt) or (outer_a_before and _OUTER_TITLE_CONT.match(kt)):
                    resume = k
                    break
            if resume is not None:
                j = resume
                continue
            break
        if j > 0 and _OUTER_A.match(t):
            outer_a_before = True
        kept.append(sl[j])
        j += 1
    if len(kept) != len(sl):
        sub_words = [sub_words[i] for ln in kept for i in ln]
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
        if _date_of(txt) or (A._HEADER_LINE.search(txt) and all(v == int(v) and 1990 <= abs(v) <= 2100 for v in vals)):
            continue
        return j
    return len(sl)


def _parse_line_cols(words, line: list[int], centres: list[float], gap: float) -> tuple[str, list, int, str, int]:
    """Extract label, two-column values, max decimals, quote and column-number count for one printed line."""
    label_words, vals, decs, kept = [], [None, None], [0, 0], []
    n_nums = 0
    for i in line:
        tok = words[i][4]
        if words[i][0] > centres[1] + 0.7 * gap:
            continue
        kept.append(i)
        xc = (words[i][0] + words[i][2]) / 2
        d = [abs(xc - c) for c in centres]
        k = 0 if d[0] <= d[1] else 1
        parsed = A.number(tok) if (any(ch.isdigit() for ch in tok) or tok.strip() in A._DASH) else None
        if parsed is not None and d[k] <= 0.6 * gap and words[i][0] > centres[0] - 1.6 * gap:
            n_nums += 1
            if vals[k] is None:
                vals[k], decs[k] = parsed
            continue
        if parsed is not None and words[i][0] > centres[0] - 0.9 * gap:
            n_nums += 1
            continue
        label_words.append(tok)
    label = " ".join(label_words).strip()
    quote = " ".join(words[i][4] for i in kept) if vals != [None, None] else label
    return label, vals, max(decs), quote, n_nums


_MONTH_WORD = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.I,
)


_MARKER_START = re.compile(r"^\W*(?:\(?[ivx]{1,4}\)?[.):]\s+|\(?[a-z]\)[.):]?\s+|[a-z][.)]\s+)", re.I)
_FOOTNOTE_START = re.compile(r"^\W*(?:\*+|#|@|notes?\s*[-:])", re.I)
_FOOTNOTE_HEAD = re.compile(r"^\W*(?:\*+\s*(?:includes?|represents?|consists?)|notes?\s*[:\-]\s*$)", re.I)
_PROSE_SENT_END = re.compile(r"(?<!ltd)(?<!pvt)(?<!no)(?<!co)(?<!rs)(?<!cr)(?<!mn)(?<!st)(?<!a/c)\.\s*$", re.I)


def _flush_seg(seg_words: list, centres: list[float], gap: float, page: int, out: list[A.Line]) -> bool:
    """Run ``A._read_lines`` on one chunk, returning True if a signature line stopped the page."""
    if not seg_words:
        return False
    body = A._read_lines(seg_words, centres, page)
    b = 0
    for line in lines_of(seg_words):
        label, vals, dec, quote, n_nums = _parse_line_cols(seg_words, line, centres, gap)
        if A._SIGNATURE.search(label):
            return True
        if b < len(body) and body[b].quote == quote:
            out.append(body[b])
            b += 1
        elif (not label and vals[0] is not None and vals[1] is not None and n_nums == 2
              and not (A._HEADER_LINE.search(quote)
                       and all(v == int(v) and 1990 <= abs(v) <= 2100 for v in vals))):
            out.append(A.Line("", vals, dec, quote, page))
    if b < len(body):
        out.extend(body[b:])
    return False


def _read_lines(words, centres: list[float], page: int) -> list[A.Line]:
    """Drop date/unit/footnote-prose lines before ``A._read_lines``, flush separately around empty-label total
    lines and bare roman/letter marker captions so neither merges into an adjacent item label."""
    gap = abs(centres[1] - centres[0])
    out: list[A.Line] = []
    seg_words: list = []
    in_footnote = False
    dropped_open_prose = False
    for ln in lines_of(words):
        label, vals, dec, quote, n_nums = _parse_line_cols(words, ln, centres, gap)
        line_text = " ".join(words[i][4] for i in ln)
        header_vals = (
            vals != [None, None]
            and dec == 0
            and (
                (all(v is None or (v == int(v) and (1 <= abs(v) <= 31 or 1990 <= abs(v) <= 2100)) for v in vals)
                 and bool(_HEADERISH.search(label) or _MONTH_WORD.search(label)))
                or (not label and vals[0] is not None and vals[1] is not None
                    and 1990 <= vals[0] <= 2100 and 1990 <= vals[1] <= 2100 and abs(vals[0] - vals[1]) <= 2)
            )
        )
        if _is_date_chunk(line_text) or header_vals or (vals == [None, None] and (
            _HEADERISH.search(label) or is_heading(label)
            or _line_unit(label) is not None or _line_unit(line_text) is not None
        )):
            continue
        if vals == [None, None]:
            if A._SIGNATURE.search(label):
                _flush_seg(seg_words, centres, gap, page, out)
                return out
            if _FOOTNOTE_HEAD.match(label):
                if _flush_seg(seg_words, centres, gap, page, out):
                    return out
                seg_words = []
                out.append(A.Line(label, [None, None], 0, quote, page))
                in_footnote = True
                dropped_open_prose = False
                continue
            is_prose = bool(
                _FOOTNOTE_START.match(label)
                or _UNIT_AMOUNT.search(label)
                or _PROSE_LINE.search(label)
                or (_PROSE_SENT_END.search(label) and len(label.split()) >= 5)
            )
            if in_footnote:
                if _MARKER_START.match(label) and not is_prose and len(label.split()) <= 8:
                    in_footnote = False
                    dropped_open_prose = False
                else:
                    if is_prose and not _PROSE_SENT_END.search(label):
                        dropped_open_prose = True
                    continue
            elif is_prose:
                in_footnote = True
                dropped_open_prose = not _PROSE_SENT_END.search(label)
                continue
            if _MARKER_START.match(label):
                if _flush_seg(seg_words, centres, gap, page, out):
                    return out
                seg_words = [words[i] for i in ln]
                continue
        else:
            if dropped_open_prose and ((vals[0] is None) != (vals[1] is None)) and label[:1].islower():
                continue
            in_footnote = False
            dropped_open_prose = False
            if not label and vals[0] is not None and vals[1] is not None and n_nums == 2:
                if _flush_seg(seg_words, centres, gap, page, out):
                    return out
                seg_words = []
                out.append(A.Line("", vals, dec, quote, page))
                continue
        seg_words.extend(words[i] for i in ln)
    _flush_seg(seg_words, centres, gap, page, out)
    return out


_TIED_NOTES = {
    "revenue_from_operations": ("P&L", ("revenue_from_operations",)),
    "finance_costs": ("P&L", ("finance_cost", "finance_costs")),
    "borrowings_noncurrent": ("BS", ("borrowings_noncurrent",)),
    "borrowings_current": ("BS", ("borrowings_current",)),
}
_FACE_LINE_TO_NOTE = {
    ("P&L", "revenue_from_operations"): "revenue_from_operations",
    ("P&L", "finance_cost"): "finance_costs",
    ("P&L", "finance_costs"): "finance_costs",
    ("BS", "borrowings_noncurrent"): "borrowings_noncurrent",
    ("BS", "borrowings_current"): "borrowings_current",
}
_CURRENCY_UNITS = {"inr", "inr_lakh", "inr_crore", "inr_million", "inr_thousand", "₹"}


@dataclass
class FaceCand:
    inr: float
    scale: float
    unit: str
    checked: bool
    own_filing: bool
    src_tier: int
    known_at: str
    source: str
    doc_key: str
    is_xbrl: bool = False


_BAD_REV_FACE = re.compile(r"\btotal\s+income\b|\btotal\s+revenue(?!\s+from\s+operations)\b", re.I)
_GOOD_REV_AR = re.compile(r"revenue\s+from\s+operations|income\s+from\s+operations|operating\s+revenue|sale\s+of", re.I)
_PRIOR_QUOTE = re.compile(r"\b(?:previous|prior)\s+year\b|\bcomparative\b", re.I)
_UNIT_AMOUNT = re.compile(
    r"\d+(?:\.\d+)?\s*(?:lakhs?|lacs?|crores?|millions?|crs?|mns?)\b|(?:rs\.?|inr|₹|`)\s*\d[\d,.]*",
    re.I,
)
_UNIT_DECL = re.compile(
    r"\ball\s+amounts?\b|\bamount\s+in\b|(?:rs\.?|inr|rupees|h|`|₹)\s*in\s+(?:lakh|lac|crore|cr|million|mn|thousand)|"
    r"\(\s*(?:rs\.?|inr|rupees|h|`|₹)?\s*(?:in\s+)?(?:lakhs?|lacs?|crores?|millions?|thousands?|crs?|mns?)\s*\)",
    re.I,
)


def _line_unit(text: str) -> tuple[str, float] | None:
    """Unit only from a genuine unit phrase line ('(Rs in lakhs)', 'All amounts are in ...', '` in Crores'),
    never from a prose sentence carrying a numeric amount ('Pledge of FDR of Rs. 3.70 Crores')."""
    t = text.strip()
    if not t or _UNIT_AMOUNT.search(t):
        return None
    u = A._unit(t)
    if not u:
        return None
    if _UNIT_DECL.search(t):
        return u if len(t.split()) <= 20 else None
    if _PROSE_LINE.search(t) or _SENTENCE.search(t) or len(t.split()) > 10:
        return None
    return u


def _malformed_token(tok: str | None, checked: bool) -> bool:
    """True when ``raw_token`` in ``fin_quarter_printed`` has OCR corruption that makes its parsed scale unsafe."""
    if not tok:
        return False
    s = tok.strip().strip("()")
    if not s:
        return False
    if re.search(r"[A-Za-z]", s):
        return True
    if re.search(r",\d{4,}\.", s):        # e.g. '2,55039.9' parsed 10x wrong
        return True
    if checked:
        return False
    if s.count(".") > 1 or re.search(r"\s", s):
        return True
    if "," in s:
        parts = s.split(".", 1)[0].split(",")
        if len(parts[-1]) != 3 or any(len(p) not in (2, 3) for p in parts[1:-1]):
            return True
    return False


def _rev_quote_ok(note: str, caption: str | None, quote: str | None, src_table: str | None) -> bool:
    if note != "revenue_from_operations":
        return True
    cap, qt = caption or "", quote or ""
    if _BAD_REV_FACE.search(cap) or _BAD_REV_FACE.search(qt):
        return False
    if src_table == "ar_facts" and not _GOOD_REV_AR.search(f"{cap} {qt}"):
        return False
    return True


def _cand_key(c: FaceCand):
    return (-int(c.own_filing), -int(c.checked), -c.src_tier, c.known_at or "9999")


def load_face_targets(store_db: str) -> dict[tuple[str, str, str], list[FaceCand]]:
    """Load ranked face-statement candidates ``(fiscal_year, basis, note) -> [FaceCand]`` read-only.
    Prefers the year's own filing (Q4 ``ytd`` or own-year AR), then checked status, then earlier ``known_at``;
    includes ``column_role IN ('ytd', 'prior_ytd', 'last_fy')`` from ``fin_quarter_printed``, drops malformed
    raw tokens, and verifies revenue quotes are revenue from operations (not Total Revenue / Total Income)."""
    cands: dict[tuple[str, str, str], list[FaceCand]] = defaultdict(list)
    try:
        dbp = Path(store_db)
        if not dbp.is_file():
            return {}
        conn = sqlite3.connect(f"file:{dbp.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        try:
            q1 = (
                "SELECT fiscal_year, basis, statement, line_item, caption, quote, value, unit, scale, "
                "source_table, doc_key, known_at FROM fin_annual_line WHERE statement IN ('P&L', 'BS') "
                "AND period_type='FY' AND value IS NOT NULL AND line_item IN "
                "('revenue_from_operations', 'finance_cost', 'finance_costs', 'borrowings_noncurrent', 'borrowings_current')"
            )
            for fy, basis, stmt, li, cap, qt, val, unit, scale, src_tbl, dkey, ka in conn.execute(q1):
                note = _FACE_LINE_TO_NOTE.get((stmt, li))
                u = (unit or "").lower()
                if not note or u not in _CURRENCY_UNITS or not scale or float(scale) <= 0:
                    continue
                if not _rev_quote_ok(note, cap, qt, src_tbl):
                    continue
                is_xbrl = src_tbl == "facts"
                own_f = is_xbrl or not _PRIOR_QUOTE.search(qt or "")
                tier = 4 if is_xbrl else (3 if src_tbl == "ar_facts" else 1)
                cands[(fy, basis, note)].append(FaceCand(
                    inr=float(val) * float(scale), scale=float(scale), unit=u,
                    checked=True, own_filing=own_f, src_tier=tier,
                    known_at=ka or "", source=src_tbl or "fin_annual_line",
                    doc_key=dkey or "", is_xbrl=is_xbrl,
                ))
        except sqlite3.Error:
            pass
        try:
            q2 = (
                "SELECT fiscal_period, column_role, basis, statement, line_item, caption, quote, value, "
                "unit, scale, raw_token, check_status, doc_key, known_at "
                "FROM fin_quarter_printed WHERE lower(period_type)='fy' "
                "AND column_role IN ('ytd', 'prior_ytd', 'last_fy') AND value IS NOT NULL "
                "AND line_item IN ('revenue_from_operations', 'finance_cost', 'finance_costs')"
            )
            for fp, role, basis, stmt, li, cap, qt, val, unit, scale, rtok, cs, dkey, ka in conn.execute(q2):
                note = _FACE_LINE_TO_NOTE.get((stmt, li))
                u = (unit or "").lower()
                if not note or u not in _CURRENCY_UNITS or not scale or float(scale) <= 0:
                    continue
                cs_s = (cs or "").lower()
                checked = cs_s in ("sum_ok", "xbrl_ok", "repeat_ok")
                role_s = (role or "").lower()
                if not checked and (float(val) == 0.0 or role_s == "last_fy"):
                    continue
                if _malformed_token(rtok, checked):
                    continue
                if not _rev_quote_ok(note, cap, qt, "fin_quarter_printed"):
                    continue
                own_f = role_s == "ytd"
                tier = 2 if role_s in ("ytd", "prior_ytd") else 1
                src_tag = f"fqp:{role_s}"
                cands[(fp, basis, note)].append(FaceCand(
                    inr=float(val) * float(scale), scale=float(scale), unit=u,
                    checked=checked, own_filing=own_f, src_tier=tier,
                    known_at=ka or "", source=src_tag,
                    doc_key=dkey or "", is_xbrl=False,
                ))
        except sqlite3.Error:
            pass
    finally:
        conn.close()
    for key in cands:
        cands[key].sort(key=_cand_key)
    return dict(cands)


def _unit_round_inr(unit_name: str, scale: float, decimals: int) -> float:
    step = 0.5 * (10 ** (-decimals)) * scale
    if unit_name == "inr_crore":
        return max(step, 0.01 * scale)
    if unit_name == "inr_lakh":
        return max(step, 0.5 * scale)
    if unit_name == "inr_million":
        return max(step, 0.05 * scale)
    return step


def _cand_matches(note_inr: float, tot_dec: int, note_unit: str, note_scale: float, c: FaceCand) -> bool:
    note_round = _unit_round_inr(note_unit, note_scale, tot_dec)
    face_round = _unit_round_inr(c.unit, c.scale, 2 if c.unit == "inr_crore" else 0)
    tol = max(note_round, face_round) + 0.001 * max(abs(note_inr), abs(c.inr)) + 1.0
    return abs(note_inr - c.inr) <= tol


def _tie_out_check(tot_val: float, tot_dec: int, note_unit: str, note_scale: float,
                   face_entry: list[FaceCand] | tuple[float, float, str] | None,
                   doc_key: str = "", allow_differs: bool = True) -> tuple[str, FaceCand | None]:
    """Return ``(status, matched_or_primary_cand)`` where ``status`` is ``'tied'``, ``'differs'``,
    ``'disagree'``, or ``'no_face'``."""
    if not face_entry:
        return "no_face", None
    if isinstance(face_entry, tuple):
        cands = [FaceCand(inr=face_entry[0], scale=face_entry[1], unit=face_entry[2],
                          checked=True, own_filing=True, src_tier=4, known_at="",
                          source="face", doc_key="", is_xbrl=False)]
    else:
        cands = sorted(face_entry, key=_cand_key)
    note_inr = tot_val * note_scale
    c0 = cands[0]
    if _cand_matches(note_inr, tot_dec, note_unit, note_scale, c0):
        return "tied", c0
    for c in cands[1:]:
        if c.checked and _cand_matches(note_inr, tot_dec, note_unit, note_scale, c):
            return "tied", c
    if (allow_differs and c0.is_xbrl and c0.doc_key and c0.doc_key != doc_key and c0.inr > 0
            and abs(note_inr - c0.inr) <= 0.01 * abs(c0.inr)):
        return "differs", c0
    return "disagree", c0


def _bs_section_above(words, lines: list[list[int]], first: int, x_left: float, x_right: float,
                      doc_section: str | None) -> str | None:
    """Nearest Balance Sheet section header ('borrowings_noncurrent' / 'borrowings_current') above line ``first``."""
    for j in range(first - 1, -1, -1):
        txt = " ".join(words[i][4] for i in lines[j] if x_left - 20.0 <= words[i][0] < x_right).strip()
        if not txt:
            continue
        if _BS_RESET.match(txt):
            return None
        if (m := _BS_SECTION.match(txt)):
            return "borrowings_noncurrent" if "non" in m.group(1).lower() else "borrowings_current"
    for j in range(first - 1, -1, -1):
        if len(_split_chunks(words, lines[j])) != 1:
            continue
        txt = " ".join(words[i][4] for i in lines[j]).strip()
        if _BS_RESET.match(txt):
            return None
        if (m := _BS_SECTION.match(txt)):
            return "borrowings_noncurrent" if "non" in m.group(1).lower() else "borrowings_current"
    return doc_section


def read_page(store_db: str, doc_key: str, page: int, known_at: str, doc_basis: str | None,
              doc_section: str | None = None,
              face_targets: dict[tuple[str, str, str], tuple[float, float, str]] | None = None,
              force_standalone: bool = False,
              doc_unit: tuple[str, float] | None = None,
              contd_notes: set[str] | None = None) -> tuple[list[Row], list[dict]]:
    pw = words_for(store_db, doc_key, page)
    if not pw.words:
        return [], []
    if face_targets is None:
        face_targets = load_face_targets(store_db)
    contd_set = contd_notes or set()
    words = A._norm(pw.words)
    lines = lines_of(words)
    rows, log = [], []
    for reg_i, (note, first, end) in enumerate(note_regions(words, lines)):
        x_left, x_right = _heading_span(words, lines[first], note)
        if note == "borrowings_unclassified":
            sec = _bs_section_above(words, lines, first, x_left, x_right, doc_section)
            if sec:
                note = sec
        region = [i for ln in lines[first:end] for i in ln]
        sub_words = [words[i] for i in region if x_left <= words[i][0] < x_right]
        sl = lines_of(sub_words)
        sub_words, sl = _cut_subtable(sub_words, sl)
        cols = _columns(sub_words, sl[:8]) or _columns_above(words, lines, first, x_left, x_right)
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
                cols = _columns(sub_words, sl[:8]) or _columns_above(words, lines, first, x_left, x_right)
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
        # the unit printed above the first figure line of the note (never footnotes or prose amounts below), else
        # the nearest unit-phrase line above its heading; the page's declared unit only when every unit line agrees
        fig_idx = _first_figure_line(sub_words, sl, cols[0])
        unit = next((u for j in range(fig_idx - 1, -1, -1)
                     if (u := _line_unit(" ".join(sub_words[i][4] for i in sl[j])))), None)
        if not unit:
            unit = next((u for j in range(first - 1, -1, -1)
                         if (u := _line_unit(" ".join(words[i][4] for i in lines[j] if x_left <= words[i][0] < x_right)))),
                        None)
        if not unit:
            found = {_line_unit(" ".join(words[i][4] for i in ln)) for ln in lines} - {None}
            unit = found.pop() if len(found) == 1 else (doc_unit if not found else None)
        if not unit:
            log.append({"page": page, "note": note, "ok": 0, "why": "no unit printed"})
            continue
        body = _read_lines(sub_words, cols[0], page)
        basis = "standalone" if force_standalone else (
            title_basis(" ".join(" ".join(words[i][4] for i in ln) for ln in lines[:12])) or doc_basis
        )
        if basis not in ("standalone", "consolidated"):
            log.append({"page": page, "note": note, "ok": 0, "why": "basis not printed"})
            continue
        ends = cols[1]
        n_ok = 0
        reg_rows: list[Row] = []
        reg_bad = False
        tie_fail_logged = False
        for k in (0, 1):
            fy = A.fiscal_label(ends[k])
            own = ends[k] == max(ends)
            col_rows = []
            found = blocks(body, k)
            # a lone unfollowed block whose printed total is a bare section marker ('(A)') is an incomplete half of a
            # multi-page note (part (B) sits on the next page): never stand in for the complete note
            if (len(found) == 1 and not found[0][5] and found[0][3] == "block"
                    and re.fullmatch(r"\W*\([a-z0-9]{1,2}\)\W*", found[0][2].label.strip(), re.I)):
                found = []
            # an item is named by its own label; the caption it is printed under is added only where two items of
            # the column would otherwise share a name (the indent that shows where a caption ends is not read)
            base = [_slug(i.label) for b in found for _g, i in b[1]]
            clash = {n for n in base if base.count(n) > 1}
            decs_by_sub: dict[tuple[str, str], list[int]] = defaultdict(list)
            tot_decs_by_sub: dict[tuple[str, str], int] = {}
            tot_quote_by_sub: dict[tuple[str, str], str] = {}
            split_subs = {b[0] for b in found if b[0]}
            for sub, items, total, kind, caption, followed in found:
                n_ok += 1
                # a Borrowings note split into non-current / current subsections is those two notes
                split_borr = bool(sub) and (
                    note == "borrowings_unclassified"
                    or (note.startswith("borrowings_") and len(split_subs) > 1)
                )
                nm, tag = (f"borrowings_{sub}", "") if split_borr else (note, f":{sub}" if sub else "")
                decs_by_sub[(nm, tag)].append(total.decimals)
                tot_decs_by_sub[(nm, tag)] = total.decimals
                for group, i in items:
                    own_label = _slug(i.label)
                    tail = bool(_CONT.match(i.label))      # 'In rupees', 'From banks', '- Term loans': a caption's tail
                    slug = _slug(f"{group} {i.label}") if group and (tail or own_label in clash) else own_label
                    # a 'Less:' line is stored negative, so the items of a block sum to its total
                    val = -abs(i.values[k]) if _LESS.search(i.label) else i.values[k]
                    decs_by_sub[(nm, tag)].append(i.decimals)
                    col_rows.append(Row(fy, ends[k], basis, f"{nm}{tag}:{slug}", i.label[:200],
                                    val, unit[0], unit[1], doc_key, page, i.quote[:300], known_at,
                                    f"ar_note_reader: {nm}{tag}, items add up to the printed total", own,
                                    f"{doc_key}#p{page}#r{reg_i}#{k}"))
                # the note total is the grand total, or the one block of its (sub-)note; every other block total is
                # a sub-total named by its caption and printed label
                same = [b for b in found if b[0] == sub]
                is_total = (kind == "grand" or len(same) == 1) and not followed
                if is_total:
                    name = f"{nm}_total{tag}"
                    tot_quote_by_sub[(nm, tag)] = total.quote[:300]
                else:
                    cap_txt = caption or (items[0][0] if items else "") or (items[0][1].label if items else "")
                    lbl_txt = total.label
                    if _slug(lbl_txt) in ("subtotal", "sub_total", "total", "") and cap_txt:
                        sub_slug = _slug(cap_txt)
                    else:
                        sub_slug = _slug(f"{caption} {lbl_txt}") or _slug(cap_txt) or "block"
                    name = f"{nm}{tag}_subtotal:{sub_slug}"
                    used = {r.line_item for r in col_rows}
                    if name in used:
                        base_name, idx = name, 2
                        while f"{base_name}_{idx}" in used:
                            idx += 1
                        name = f"{base_name}_{idx}"
                col_rows.append(Row(fy, ends[k], basis, name, total.label[:200] or "Total",
                                    total.values[k], unit[0], unit[1], doc_key, page, total.quote[:300], known_at,
                                    f"ar_note_reader: {nm}{tag} {kind} total", own, f"{doc_key}#p{page}#r{reg_i}#{k}"))
            # a line item named twice in one column is ambiguous: the column writes nothing
            names = [r.line_item for r in col_rows]
            if len(names) != len(set(names)):
                log.append({"page": page, "note": note, "ok": 0, "why": f"column {k}: a line item named twice"})
                n_ok -= len(found)
                continue
            # whole-note invariant: if a column writes a _total row, all items of that (sub-)note must sum to it
            for (nm, tag), decs in decs_by_sub.items():
                tot_key = f"{nm}_total{tag}"
                tot_rows = [r for r in col_rows if r.line_item == tot_key]
                if len(tot_rows) != 1:
                    continue
                item_rows = [r for r in col_rows if note_of_row(r.line_item) == nm
                             and "_subtotal" not in r.line_item and r.line_item != tot_key
                             and (not tag or f"{tag}:" in r.line_item)]
                tol = 0.5 * 10 ** (-max(decs, default=2)) * (len(item_rows) + 1) + 1e-9
                if abs(sum(r.value for r in item_rows) - tot_rows[0].value) > tol:
                    reg_bad = True
                    break
            if reg_bad:
                break
            # last non-prose figure line in the cropped note for column k (D3 iii)
            fig_lines_k = [ln for ln in body if ln.values and ln.values[k] is not None and (
                (len(ln.values) >= 2 and ln.values[0] is not None and ln.values[1] is not None)
                or not (_PROSE_LINE.search(ln.label) or len(ln.label.split()) > 8)
            )]
            last_fig_quote = fig_lines_k[-1].quote[:300] if fig_lines_k else ""
            # tie-out gate against face statement when held; disagreeing note writes nothing
            kept_col: list[Row] = []
            for (nm, tag), _decs in decs_by_sub.items():
                sub_rows = [r for r in col_rows if note_of_row(r.line_item) == nm and (not tag or f"{tag}:" in r.line_item or r.line_item == f"{nm}_total{tag}")]
                tot_key = f"{nm}_total{tag}"
                tot_rows = [r for r in sub_rows if r.line_item == tot_key]
                if len(tot_rows) == 1 and not tag and nm in _TIED_NOTES:
                    t_dec = tot_decs_by_sub.get((nm, tag), 2)
                    allow_diff = (
                        not re.match(r"^\W*sub[- ]?totals?\b", tot_rows[0].caption.strip(), re.I)
                        and tot_quote_by_sub.get((nm, tag), "") == last_fig_quote
                        and nm not in contd_set
                        and note not in contd_set
                    )
                    status, m_cand = _tie_out_check(
                        tot_rows[0].value, t_dec, unit[0], unit[1], face_targets.get((fy, basis, nm)), doc_key,
                        allow_differs=allow_diff,
                    )
                    if status == "disagree":
                        log.append({"page": page, "note": nm, "ok": 0, "why": "total does not tie to the statement"})
                        tie_fail_logged = True
                        n_ok -= sum(1 for b in found if (f"borrowings_{b[0]}" if (bool(b[0]) and (note == "borrowings_unclassified" or (note.startswith("borrowings_") and len(split_subs) > 1))) else note) == nm)
                        continue
                    for r in sub_rows:
                        r.tie_status = status
                        if status == "no_face":
                            r.definition = f"{r.definition}; not tied to a statement figure"
                        elif status == "differs" and m_cand is not None:
                            r.definition = f"{r.definition}; face figure differs: {m_cand.inr / unit[1]:.2f} {m_cand.doc_key or m_cand.source}"
                else:
                    for r in sub_rows:
                        r.tie_status = "no_face"
                        r.definition = f"{r.definition}; not tied to a statement figure"
                kept_col.extend(sub_rows)
            reg_rows += kept_col
        if reg_bad:
            log.append({"page": page, "note": note, "ok": 0, "why": "items do not sum to total"})
            continue
        rows += reg_rows
        if not reg_rows and tie_fail_logged:
            continue
        log.append({"page": page, "note": note, "ok": n_ok, "why": "" if n_ok else "no block adds up"})
    return rows, log


def _update_section(text: str, cur: str | None) -> str | None:
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        if _BS_RESET.match(t):
            cur = None
        elif (m := _BS_SECTION.match(t)):
            cur = "borrowings_noncurrent" if "non" in m.group(1).lower() else "borrowings_current"
    return cur


def _contd_notes_in(text: str) -> set[str]:
    out: set[str] = set()
    for ln in (text or "").splitlines()[:15]:
        t = ln.strip()
        if not t or not _CONTD.search(t):
            continue
        cleaned = _CONTD.sub("", t).strip()
        if is_heading(cleaned):
            for name, rx in NOTES:
                if rx.search(cleaned):
                    out.add(name)
                    break
    return out


def _page_declared_unit(text: str) -> tuple[str, float] | None:
    found = {_line_unit(ln.strip()) for ln in (text or "").splitlines() if ln.strip()} - {None}
    return found.pop() if len(found) == 1 else None


def run_store(db: Path, store: str, dry: bool = False) -> dict:
    conn = sqlite3.connect(db if not dry else f"file:{db.as_posix()}?mode=ro", uri=dry)
    sym, isin = conn.execute("SELECT symbol, isin FROM company LIMIT 1").fetchone()
    docs = conn.execute("SELECT doc_key, known_at, filing_date FROM doc WHERE doc_type='annual_report'").fetchall()
    face_targets = load_face_targets(str(db))
    cand, log = [], []
    heads = re.compile(r"borrowings|revenue\s+from\s+operations|finance\s+costs?", re.I)
    for doc_key, known_at, filing_date in docs:
        pages = conn.execute("SELECT page, text FROM doc_page WHERE doc_key=? ORDER BY page", (doc_key,)).fetchall()
        # a notes page that names no basis takes the basis of the nearest page before it that names one (the
        # standalone and consolidated sections are contiguous); a report with no consolidated statement is standalone
        any_cons = any(re.search(r"consolidated\s+(balance\s+sheet|statement\s+of\s+profit|financial\s+statements)",
                                 t or "", re.I) for _, t in pages)
        last = None if any_cons else "standalone"
        last_sec: str | None = None
        last_unit: tuple[str, float] | None = None
        for idx, (page, text) in enumerate(pages):
            if any_cons:
                # only a title phrase in the page head moves the running basis, never prose
                nxt = title_basis((text or "")[:400])
                if nxt and nxt != last:
                    last = nxt
                    last_sec = None
                    last_unit = None
            last_unit = _page_declared_unit(text or "") or last_unit
            if text and heads.search(text):
                contd_notes = _contd_notes_in(pages[idx + 1][1]) if idx + 1 < len(pages) and pages[idx + 1][0] == page + 1 else set()
                rows, lg = read_page(str(db), doc_key, page, known_at or filing_date or "", last,
                                     doc_section=last_sec, face_targets=face_targets, force_standalone=not any_cons,
                                     doc_unit=last_unit, contd_notes=contd_notes)
                cand += rows
                for x in lg:
                    log.append({"doc_key": doc_key, **x})
            last_sec = _update_section(text or "", last_sec)
    # never let an unclassified borrowings note stand alongside or displace a classified one for the same (year, basis)
    classified = {(r.fiscal_year, r.basis) for r in cand
                  if note_of_row(r.line_item) in ("borrowings_noncurrent", "borrowings_current")}
    cand = [r for r in cand
            if note_of_row(r.line_item) != "borrowings_unclassified" or (r.fiscal_year, r.basis) not in classified]
    # one report per (year, basis, note): tied to face statement first, then own column, latest report, lower page
    # one source per (year, basis, note): items, sub-totals and the total of a note always come from one page and column
    def _rank(r: Row):
        return (r.tie_status == "tied", r.own, r.known_at, r.doc_key, -r.page, r.source)

    best = {}
    for r in cand:
        key = (r.fiscal_year, r.basis, note_of_row(r.line_item))
        rank = _rank(r)
        if key not in best or rank > best[key]:
            best[key] = rank
    rows = [r for r in cand if _rank(r) == best[(r.fiscal_year, r.basis, note_of_row(r.line_item))]]
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
