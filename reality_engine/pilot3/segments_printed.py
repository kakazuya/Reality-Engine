"""T-223 (1): segment tables printed in quarterly results -> ``kpi_series`` rows, one per segment, metric and period.

Only 10 of the 91 Telegram stores held segment rows (from XBRL); small companies rarely tag segments, but their
results print the Ind AS 108 / Reg. 33 segment table every quarter.  No model:

1. Pages: every ``results`` page that ``doc_map.yaml`` labels ``segment_table``.
2. Rows: PDF word boxes (``v2.page_words.words_for``) rebuilt into printed rows (``comparatives.rows_from_words``);
   number tokens, column anchors, monotone token-to-column assignment, decimals and the printed unit all come from
   ``comparatives`` (the reader of the P&L table on the same filings), so OCR-split numbers and blank cells are
   handled the same way.
3. Columns -> periods: the header dates (``comparatives._header_dates``) and the current period end
   (``_period_end``: the latest quarter end printed on or before the filing) give each column its role (current
   quarter, preceding, year-ago, year-to-date, prior year-to-date, last full year).  A table printing standalone
   and consolidated side by side (twice the columns) is split in two halves, each with its own basis.
4. Blocks: 'Segment Revenue', 'Segment Results', 'Segment Assets', 'Segment Liabilities', 'Capital Employed'
   (OCR tolerant).  Inside a block, the lines between the heading and its 'Total' are the segments;
   reconciliation lines (inter-segment, unallocable, interest, profit before tax) are not segments.
5. Gate, per block and column: the segments add up to the printed total (within the printed rounding).  A block
   with no total, one segment only, or a sum that fails writes nothing for that column.  The revenue line printed
   under the revenue total ('Net sales / Income from operations') is used to name the basis and fix the columns
   (below); the inter-segment line is not checked.
   Column roles: when the header prints its dates, those roles only, and every printed date must match its role
   (else the page writes nothing); without dates, the layout's default.  Each candidate order must agree with the
   company's P&L revenue in every column that has one (no mismatch at all) and match at least one; two columns
   naming one period, or a year-to-date column at a June end (a quarter, or a non-March year), write nothing.  The
   page's period end must equal the filing's own P&L current period end when the P&L was read.
6. Rows: metric ``segment_revenue`` / ``segment_ebit`` / ``segment_assets`` / ``segment_liabilities`` /
   ``segment_capital_employed``, ``dimension`` = the segment name (one spelling per company, as
   ``xbrl_segments._canonical`` does), value in rupees (``unit='inr'``, ``scale=1``; ``raw_value`` keeps the printed
   token), ``fiscal_period`` Q/H1/9M/FY, ``known_at`` = the filing's.  One row per (metric, segment, period, basis):
   the filing whose current or year-to-date column is that period first, else the latest filing.  A basis taken
   from the filing's only P&L basis (no word on the page) needs the header dates read.  Where XBRL segment rows exist for
   that metric, period and basis, XBRL is kept and the printed figure is only compared.

    python -m reality_engine.pilot3.segments_printed run --root D:/RealityEngine/tg_build/measure10 [--stores c70] [--dry --out <dir>]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from reality_engine.pilot3 import comparatives as C
from reality_engine.pilot3 import doc_map, kpi
from reality_engine.pilot3.xbrl_segments import _canonical, normalise
from reality_engine.v2.page_words import words_for

SOURCE_TYPE = "printed_segment"
RULE = "printed_segment_v1"

BLOCKS = (
    ("segment_ebit", ("result", "results")),
    ("segment_revenue", ("revenue", "income", "sales", "turnover")),
    ("segment_ebit", ("profit", "ebit", "ebitda")),
    ("segment_assets", ("assets", "asset")),
    ("segment_liabilities", ("liabilities", "liability")),
)
_CAPITAL = re.compile(r"capital\s+employed", re.I)
_TOTAL = re.compile(r"^\W*(\d+\W*)?(sub[- ]?total|total|segment\s+total)\b|^total\s+segment", re.I)
# a column that prints its own start ('For the period 11 February 2024 to 31 March 2025'): not a standard period
_PERIOD_FROM = re.compile(r"period\s+(from\s+)?\d{1,2}(st|nd|rd|th)?\b(?![.,/-]?\d)(?!\s*months)|"
                          r"\bfrom\s+\d{1,2}(st|nd|rd|th)?[\s./-]*[a-z]*[\s./-]*\d{2,4}\s+to\b", re.I)
_NOT_SEGMENT = re.compile(
    r"inter[- ]?segment|unallocable|un-?allocated|unallocated|less\s*:|add\s*:|interest|finance\s+cost|"
    r"profit\s*(\(|/)?.*before\s+tax|before\s+tax|exceptional|net\s+sales|income\s+from\s+operations|"
    r"revenue\s+from\s+operations|other\s+income|share\s+of\s+profit|tax\s+expense|total\s+income|eliminat|"
    r"capital\s*(&|and)\s*reserves?|\breserves?\b|share\s+capital|\bequity\b|discontinu", re.I)
_REVENUE_LINE = re.compile(r"net\s+sales|income\s+from\s+operations|revenue\s+from\s+operations", re.I)
# a column-header line repeated inside the table ('Particulars March December March ...', 'Audited Unaudited')
_HEADERISH = re.compile(r"particulars|\b(jan|feb|march|mar|june|jun|sept?|september|dec|december)\b|audited|unaudited|"
                        r"quarter|months?\s+ended|year\s+ended|half\s+year", re.I)
_PREFIX = re.compile(r"^\W*(\(?[a-hivx]{1,4}[).:]|\d{1,2}[).:]|[-•])\s*", re.I)


def _similar(word: str, target: str) -> bool:
    return word == target or (len(word) >= 5 and SequenceMatcher(None, word, target).ratio() >= 0.7)


def block_of(label: str) -> str | None:
    """The block a heading line opens ('Segment Revenue', OCR 'Seen,ent Assets'), or None."""
    if _CAPITAL.search(label):
        return "segment_capital_employed"
    if re.search(r"inter[- ]?segment|^\W*less\b", label, re.I):
        return None
    words = re.findall(r"[a-z]+", label.lower().replace(",", "").replace("!", "l"))
    if not any(_similar(w, "segment") or _similar(w, "segmental") for w in words):
        return None
    for metric, keys in BLOCKS:
        if any(any(_similar(w, k) for k in keys) for w in words):
            return metric
    return None


def segment_name(label: str) -> str:
    """'a) Yarn' -> 'Yarn'; '(b) Retail Banking' -> 'Retail Banking'; OCR 'al Yarn' / '(al Domestic' -> 'Yarn' /
    'Domestic'; a word carrying digits (an unread number left in the label, '275_76') is dropped."""
    name = _PREFIX.sub("", label.strip())
    name = _PREFIX.sub("", name)
    name = re.sub(r"^(?:[l1|I!]?\s*[(\[{/!|]|[!|/\[]\s*)[a-h][l1|j}\])]*\s+(?=[A-Z])", "", name)
    name = re.sub(r"^[a-h][l1|j}\])]\s+(?=[A-Z])", "", name)
    name = re.sub(r"^segment\s*[-:–]\s*", "", name, flags=re.I)
    name = _STAMP.sub("", name)
    name = " ".join(_ocr_word(w) for w in name.split() if not re.search(r"\d", w) or ocr_damaged(w))
    return re.sub(r"\s+", " ", name).strip(" -:.=")


_OCR_DIGITS = str.maketrans({"8": "b", "0": "o", "1": "l", "5": "s", "6": "g", "4": "a"})


def ocr_damaged(word: str) -> bool:
    """A word the scan damaged: three or more letters with one or two digits in it ('8rokerage'), or an apostrophe
    after its first letter ("l'oundit")."""
    letters, digits = len(re.findall(r"[A-Za-z]", word)), len(re.findall(r"\d", word))
    return (letters >= 3 and 1 <= digits <= 2) or bool(re.match(r"^[A-Za-z][\'\u2019`][a-z]{3,}", word))


def _ocr_word(word: str) -> str:
    if not ocr_damaged(word):
        return word
    w = re.sub(r"^([A-Za-z])[\'\u2019`]", "", word) if not re.search(r"\d", word) else word.translate(_OCR_DIGITS)
    return w[:1].upper() + w[1:] if word[:1].isdigit() else w


def name_damaged(label: str) -> bool:
    """The printed segment name carried a scan-damaged word (its repaired spelling needs a clean twin)."""
    return any(ocr_damaged(w) for w in _PREFIX.sub("", label.strip()).split())


# an auditor's stamp printed over the table ('For identification purposes only')
_STAMP = re.compile(r"\b(for\s+)?identification(\s+purposes?(\s+only)?)?|\bpurposes?\s+on\S*|"
                    r"[\(\[]?\s*\(?refer\s*note.*$", re.I)


def readable(name: str) -> bool:
    """A segment name made of words, so OCR debris ('l ll j l fr l f fr w f h iil') is never stored as a segment:
    at least half its words have three or more letters, and every such word carries a vowel.  Company words
    ('Distillery', 'Petcare', 'foundit') need not be in any dictionary."""
    words = re.findall(r"[a-z]+", name.lower())
    long_words = [w for w in words if len(w) >= 3]
    if not long_words or len(long_words) < len(words) / 2:
        return False
    return all(re.search(r"[aeiouy]", w) for w in long_words)


_UNALLOC = re.compile(r"^un\W*al+\W*o\W*c", re.I)


def is_unallocated(name: str) -> bool:
    """'Unallocated', 'Un-allocated', OCR 'Unalloca1ed', 'Unallocable': a reconciling member, kept as one dimension."""
    letters = re.sub(r"[^a-z]", "", name.lower())
    return bool(_UNALLOC.search(name)) or any(SequenceMatcher(None, letters[:11], t).ratio() >= 0.8
                                              for t in ("unallocated", "unallocable"))


@dataclass
class Cell:
    metric: str
    name: str            # printed segment name ('' for the block total)
    column: int
    value: float          # printed number, unscaled
    raw: str
    quote: str
    repaired: bool
    name_ocr: bool = False   # the name carried a scan-damaged word


def _halves(header_rows, anchors: list[float], text: str) -> list[tuple[list[int], str | None]]:
    """Column index groups and their basis: one group, or two when standalone and consolidated print side by side."""
    n = len(anchors)
    head = " ".join(w[4] for row in header_rows for w in row).lower()
    low = text.lower()
    if n <= 6:
        return [(list(range(n)), C._page_basis("", head))]       # the title rows only, never a note lower down
    # more columns than one results layout prints: standalone and consolidated side by side, or nothing we can read
    if n % 2 or n // 2 > 6:
        return []
    half = n // 2
    # each half is named by the basis word printed ABOVE its columns (never by the order of words in a title)
    split = (anchors[half - 1] + anchors[half]) / 2
    left = anchors[0] - 2 * (anchors[1] - anchors[0])
    found: dict[str, set[str]] = {"left": set(), "right": set()}
    for row in header_rows:
        for w in row:
            word = re.sub(r"[^a-z]", "", w[4].lower())
            basis = next((b for b in ("standalone", "consolidated")
                          if word == b or (len(word) >= 7 and SequenceMatcher(None, word, b).ratio() >= 0.8)), None)
            if basis is None or w[2] < left:
                continue
            found["left" if (w[0] + w[2]) / 2 < split else "right"].add(basis)
    if len(found["left"]) == 1 and len(found["right"]) == 1 and found["left"] != found["right"]:
        return [(list(range(half)), found["left"].pop()), (list(range(half, n)), found["right"].pop())]
    # no basis word above the columns: the halves are named later from the revenue line (``resolve_bases``)
    return [(list(range(half)), None), (list(range(half, n)), None)]


def read_table(rows, known_at: str) -> dict | None:
    """The segment blocks of one page: ``{cells, anchors, groups, decimals, scale, end, header_dates}``."""
    if not rows:
        return None
    text = " ".join(w[4] for row in rows for w in row)
    first = next((i for i, row in enumerate(rows) if block_of(C._label(row)) is not None), None)
    if first is None:
        return None
    data = rows[first:]
    anchors = C._columns(data)
    if len(anchors) < 2:
        return None
    header_rows = rows[:first]
    # the column header may print below the line that opens the first block: read the page's first 25 rows
    if _PERIOD_FROM.search(" ".join(w[4] for row in rows[:max(first, 25)] for w in row)):
        return None             # a non-standard period column: its roles cannot be named (lost rows only)
    cells: list[Cell] = []
    block = None
    seen_total: set[str] = set()
    tokens_text = []
    pending = ""            # a bare label line waiting for the figures on the next line ('Medical and other' / 'appliances 662.71')
    last: list[int] = []    # indexes in ``cells`` of the previous segment line (a lower-case line after it continues its name)
    for row in data:
        label = C._label(row)
        opened = block_of(label)
        tokens = C._assign_tokens(row, anchors)
        quote = " ".join(w[4] for w in row)
        if opened is not None and opened not in seen_total:
            block, pending, last = opened, "", []
            if tokens:
                # the heading line itself carries figures: a single-segment company prints its totals here
                for at, tok in tokens.items():
                    cells.append(Cell(block, "", at, 0.0, tok["text"], quote, False))
                    tokens_text.append(tok["text"])
                seen_total.add(block)
            continue
        if block is None:
            continue
        if not tokens:
            bare = label.strip()
            if not bare or block in seen_total or _NOT_SEGMENT.search(bare) or _HEADERISH.search(bare):
                pending = ""
                continue
            if bare[:1].islower() and last:
                for i in last:          # the second line of the name printed beside the figures above
                    cells[i] = Cell(cells[i].metric, f"{cells[i].name} {segment_name(bare)}".strip(), cells[i].column,
                                    cells[i].value, cells[i].raw, cells[i].quote, cells[i].repaired)
                last = []
            else:
                pending = bare
            continue
        if _TOTAL.search(label.strip()) or label.strip().lower() in ("total", ""):
            pending, last = "", []
            if block in seen_total or label.strip() == "":
                continue
            for at, tok in tokens.items():
                cells.append(Cell(block, "", at, 0.0, tok["text"], quote, False))
                tokens_text.append(tok["text"])
            seen_total.add(block)
            continue
        if block in seen_total:
            if block == "segment_revenue" and _REVENUE_LINE.search(label):
                # 'Net sales / Income from operations' under the revenue total: names the basis of its columns
                for at, tok in tokens.items():
                    cells.append(Cell("_revenue_line", "", at, 0.0, tok["text"], quote, False))
                    tokens_text.append(tok["text"])
            continue
        name = segment_name(label)
        if pending and (name[:1].islower() or re.search(r"(\band|&|,|-|/|\bof)\s*$", pending, re.I)):
            name = f"{segment_name(pending)} {name}".strip()
        pending = ""
        if is_unallocated(name) and not re.search(r"less|add|expend|income|inter", label, re.I):
            name = "Unallocated"        # a reconciling member of the total (segment assets / liabilities)
        elif _NOT_SEGMENT.search(label) or _HEADERISH.search(label):
            last = []
            continue
        if not re.search(r"[A-Za-z]{2}", name):
            continue
        last = []
        damaged = name_damaged(label)
        for at, tok in tokens.items():
            last.append(len(cells))
            cells.append(Cell(block, name, at, 0.0, tok["text"], quote, False, damaged))
            tokens_text.append(tok["text"])
    if not cells:
        return None
    decimals = C._decimals(tokens_text)
    parsed = []
    for c in cells:
        got = C.read_number(c.raw, decimals)
        if got is None:
            continue
        parsed.append(Cell(c.metric, c.name, c.column, got[0], c.raw, c.quote, got[1], c.name_ocr))
    dates = C._header_dates(header_rows, len(anchors))
    end = C._period_end(dates, known_at, " ".join(w[4] for row in header_rows for w in row) + " " + text[:2000])
    return {"cells": parsed, "anchors": anchors, "groups": _halves(header_rows + [rows[first]], anchors, text), "decimals": decimals,
            "scale": C._unit(text), "end": end, "dates": dates, "text": text}


def role_candidates(table: dict, group: list[int]) -> list[list[str]]:
    """Column-role orders to try.  Header dates printed: the order they support, and only when every printed date
    matches its role's expected month and year (a calendar-year company's '31.12.2023' year-ago quarter is never
    taken for nine months); a contradiction gives no order (the page writes nothing).  No dates: the layout's
    default for that quarter."""
    end, count = table["end"], len(group)
    default = C._role_set(end, count)
    dates = table["dates"]
    sub = [dates[i] for i in group] if dates and len(dates) == len(table["anchors"]) else None
    if not sub or not any(d[0] is not None or d[1] is not None for d in sub):
        return [default]
    roles = C._roles_from_dates(sub, end, default, count)[0]
    for d, role in zip(sub, roles):
        if role and (d[0] is not None or d[1] is not None) and not C._date_match(d, C._expected_date(role, end)):
            return []
    return [roles]


def _coarse(ptype: str) -> str:
    return "quarter" if ptype == "Q" else ("fy" if ptype == "FY" else "ytd")


def choose_columns(conn, symbol: str, table: dict, group: list[int], basis: str, page_scale: float | None,
                   doc_key: str | None = None, page: int | None = None):
    """``(periods, scale, how)`` for one basis group, or ``(None, None, why)``.

    The table's revenue line ('Net sales / Income from operations', else the segment revenue total) in each column
    must equal the revenue the same company's P&L table printed for the period that column's role names
    (``fin_quarter_printed``, read by ``comparatives`` with XBRL checks): that fixes the role order and the unit
    together.  A table with no revenue line, or a company with no P&L rows for those periods, keeps the header's
    roles and the printed unit, and its year-to-date revenue total may not be below its quarter's.  P&L rows read
    from this same page (``doc_key``, ``page``) are left out: a page never confirms itself."""
    pl: dict[tuple, list[float]] = defaultdict(list)
    pl_ti: dict[tuple, list[float]] = defaultdict(list)
    for end, ptype, item, value in conn.execute(
            "SELECT period_end, period_type, line_item, value * coalesce(scale, 1) FROM fin_quarter_printed "
            "WHERE symbol=? AND basis=? AND line_item IN ('revenue_from_operations','total_income') "
            "AND NOT (doc_key IS ? AND page IS ?)",
            (symbol, basis, doc_key, page)):
        key = (end, "fy" if ptype == "fy" else ("quarter" if ptype == "quarter" else "ytd"))
        (pl if item == "revenue_from_operations" else pl_ti)[key].append(value)
    cells = [c for c in table["cells"] if c.column in group]
    rev = {c.column: c.value for c in cells if c.metric == "_revenue_line"}
    strong = bool(rev)
    if not rev:
        rev = {c.column: c.value for c in cells if c.metric == "segment_revenue" and not c.name}
    unit = 10 ** (-table["decimals"])
    cands = role_candidates(table, group)
    if not cands:
        return None, None, "header dates contradict the column roles"
    best, bounded, near, any_miss = None, None, None, False
    for k, roles in enumerate(cands):
        periods = periods_for(roles, group, table["end"])
        if periods is None:
            continue
        for j, sc in enumerate(([page_scale] if page_scale else []) + [s for s in (1e5, 1e7, 1e6, 1e3) if s != page_scale]):
            hits = misses = b_hits = b_misses = near_misses = 0
            own_ok = True
            for col, v in rev.items():
                p = periods.get(col)
                if p is None:
                    continue
                k_pl = (p[0], _coarse(p[2]))
                want = pl.get(k_pl)
                if not want:
                    continue
                if any(abs(v * sc - x) <= 0.5 * unit * sc + 0.002 * abs(x) for x in want):
                    hits += 1
                    b_hits += 1
                else:
                    misses += 1
                    tis = pl_ti.get(k_pl) or want
                    tol = 0.5 * unit * sc + 0.002 * max(abs(x) for x in want + tis)
                    lo, hi = min(want) - tol, max(want + tis) + tol
                    if lo <= v * sc <= hi:
                        b_hits += 1
                    else:
                        b_misses += 1
                        if p[4]:
                            own_ok = False
                        if hi > 0 and abs(v * sc - hi) <= 0.05 * hi:
                            near_misses += 1
                        else:
                            near_misses += 10
            # every column with a P&L figure must agree (strong revenue line or the segment total alike): one
            # coincidental match never outweighs a shifted order
            if not misses:
                rank = (hits, -k, -j)
                if hits and (best is None or rank > best[0]):
                    best = (rank, periods, sc)
                continue
            any_miss = any_miss or hits > 0 or strong
            if not b_misses and b_hits and (bounded is None or (b_hits, -k, -j) > bounded[0]):
                bounded = ((b_hits, -k, -j), periods, sc)
            elif k == 0 and sc == page_scale and own_ok and b_hits >= 3 and b_misses == 1 and near_misses == 1:
                near = (periods, sc)
    if best:
        return best[1], best[2], "revenue line = P&L revenue"
    if bounded:
        return bounded[1], bounded[2], "revenue line within P&L [revenue, total_income]"
    if near:
        return near[0], near[1], "revenue line matches P&L (one prior column restated)"
    if any_miss:
        return None, None, "revenue line disagrees with the P&L under every column order"
    if not page_scale:
        return None, None, "no unit and no P&L revenue to fix it"
    periods = periods_for(cands[0], group, table["end"])
    if periods is None:
        return None, None, "two columns name one period, or a year-to-date column at a June end"
    cur = next((v for c, v in rev.items() if periods.get(c) and periods[c][4] and periods[c][2] == "Q"), None)
    for c, v in rev.items():
        p = periods.get(c)
        if cur and p and p[2] != "Q" and p[0] == table["end"] and v < cur:
            return None, None, "year-to-date revenue below its quarter: column roles unsure"
    return periods, page_scale, "header roles, printed unit (no P&L revenue to check)"


def periods_for(roles: list[str], group: list[int], end: str) -> dict[int, tuple[str, str, str, str, bool]] | None:
    """column -> (period_end, fiscal_period, period_type, period_start, own).  ``own``: the filing's current quarter
    or its year to date (H1 in September, 9M in December, FY in March).  None when two columns name one period, or
    a year-to-date column falls at a June end (that is the quarter itself, or a year that does not end in March)."""
    out = {}
    for col, role in zip(group, roles):
        if not role:
            continue
        period_end, ptype = C._role_period(role, end)
        if ptype == "ytd" and period_end[5:7] not in ("09", "12"):
            return None
        fiscal, start, ptype2 = C._quarter(period_end, ptype)
        out[col] = (period_end, fiscal, {"quarter": "Q", "fy": "FY"}.get(ptype2, fiscal[:2] if fiscal.startswith("H") else "9M"),
                    start, role in ("current", "ytd"))
    if len({(p[1], p[2]) for p in out.values()}) != len(out):
        return None
    return out


def column_periods(table: dict, group: list[int]) -> dict[int, tuple[str, str, str, str, bool]]:
    """column -> periods under the header's roles ({} when none can be named)."""
    if not table["end"]:
        return {}
    cands = role_candidates(table, group)
    return (periods_for(cands[0], group, table["end"]) or {}) if cands else {}


def checked_blocks(table: dict, group: list[int], tol_units: float = 3.0) -> list[tuple[str, int, list[Cell]]]:
    """(metric, column, segment cells) for every block and column whose segments add up to the printed total."""
    unit = 10 ** (-table["decimals"])
    out = []
    by = defaultdict(list)
    for c in table["cells"]:
        if c.column in group:
            by[(c.metric, c.column)].append(c)
    for (metric, col), cs in by.items():
        segs = [c for c in cs if c.name and c.name != "Unallocated"]
        if not all(readable(c.name) for c in segs):
            continue        # a segment name the scan garbled: the column writes nothing
        extra = [c for c in cs if c.name == "Unallocated"]
        total = [c for c in cs if not c.name]
        names = {c.name for c in segs}
        if len(names) < 2 or len(total) != 1 or len(names) != len(segs) or len(extra) > 1:
            continue
        want = total[0].value
        # each printed figure is rounded to half its last unit: the sum may drift by (segments + 1) half-units;
        # the segments alone, or the segments and the unallocated line, must make the printed total
        for members in (segs, segs + extra):
            s = sum(c.value for c in members)
            if abs(s - want) <= 0.5 * unit * (len(members) + 1) + 1e-9:
                out.append((metric, col, members))
                break
    return out


def resolve_bases(conn, doc_key: str, table: dict, scale: float, page: int | None = None) -> list[tuple[list[int], str | None]]:
    """Each column group's basis: the word printed above it; else the group whose current-column revenue line
    equals the same filing's P&L revenue of one basis takes that basis (and the other half the other one); else the
    filing's only P&L basis for a single group.  A group still unnamed stays None (no rows).  P&L rows read from this
    same page are left out (a garbled title read once must not name the page twice)."""
    groups = [list(g) for g in table["groups"]]
    if not groups or all(b for _g, b in groups):
        return [(g, b) for g, b in groups]
    pl = {b: v for b, v in conn.execute(
        "SELECT basis, value * coalesce(scale, 1) FROM fin_quarter_printed WHERE doc_key=? AND column_role='current' "
        "AND line_item='revenue_from_operations' AND period_end=? AND page IS NOT ?", (doc_key, table["end"], page))}
    scales = [scale] if scale else [1e5, 1e7, 1e6, 1e3]
    named: list[str | None] = [b for _g, b in groups]
    for i, (cols, b) in enumerate(groups):
        if b:
            continue
        periods = column_periods(table, cols)
        cur = next((c for c, p in periods.items() if p[4] and p[2] == "Q"), None)
        line = next((c for c in table["cells"] if c.metric == "_revenue_line" and c.column == cur), None)
        if line is None:
            continue
        hits = [basis for basis, v in pl.items()
                if any(abs(line.value * sc - v) <= 0.5 * 10 ** (-table["decimals"]) * sc + 1e-6 for sc in scales)]
        if len(hits) == 1:
            named[i] = hits[0]
    if len(groups) == 2 and sum(1 for n in named if n) == 1:
        known = next(n for n in named if n)
        named = [n or ("consolidated" if known == "standalone" else "standalone") for n in named]
    if len(groups) == 1 and not named[0] and table["dates"]:
        named[0] = _fallback_basis(conn, doc_key, page)  # never on a page whose header dates were not read
    if len(groups) == 2 and named[0] == named[1]:
        named = [None, None]
    return [(g[0], n) for g, n in zip(groups, named)]


def _fallback_scale(conn, doc_key: str) -> float | None:
    row = conn.execute("SELECT scale FROM fin_quarter_printed WHERE doc_key=? AND scale IS NOT NULL "
                       "GROUP BY scale ORDER BY COUNT(*) DESC LIMIT 1", (doc_key,)).fetchone()
    return row[0] if row else None


def _fallback_basis(conn, doc_key: str, page: int | None) -> str | None:
    rows = conn.execute("SELECT basis, COUNT(*) FROM fin_quarter_printed WHERE doc_key=? AND basis IN "
                        "('standalone','consolidated') AND page IS NOT ? GROUP BY basis", (doc_key, page)).fetchall()
    return rows[0][0] if len(rows) == 1 else None


_OTHERS_DIMS = frozenset({"others", "other", "other_segments", "all_other_segments"})


def _ocr_sim(a: str, b: str) -> float:
    norm = lambda s: s.replace("rn", "m").replace("vv", "w")
    return max(SequenceMatcher(None, a, b).ratio(), SequenceMatcher(None, norm(a), norm(b)).ratio())


def _swap_ocr(by_block: dict, mapping: dict[str, str], ratio: float = 0.5) -> dict[str, str]:
    """A scan letter swap ('Yam' for Yarn, 'specrnltty polym is', 'oornesllc' for domestic): a name in a block whose
    other names are a set the company prints in two or more other blocks (any filing) with exactly one name missing,
    and that is printed in fewer blocks than the missing name, takes the missing name when the two spellings are alike
    (ratio >= 0.5, allowing rn<->m / vv<->w OCR merges).  When multiple candidate sets match, a uniquely dominant target
    (>= 2x the next candidate's block count) still resolves."""
    canon = lambda n: mapping.get(n, n)
    sets = [(k, frozenset(canon(n) for n in v)) for k, v in by_block.items()]
    blocks_of: dict[str, int] = defaultdict(int)
    support: dict[frozenset, set] = defaultdict(set)
    for key, names in sets:
        support[names].add(key)
        for n in names:
            blocks_of[n] += 1
    out = dict(mapping)
    for key, names in sets:
        for r in names:
            rest = names - {r}
            fits = {next(iter(t - rest)) for t, ks in support.items()
                    if len(ks - {key}) >= 2 and len(t) == len(names) and rest < t}
            fits = {f for f in fits if f not in names and blocks_of[f] > blocks_of[r]
                    and not any(r in s and f in s for _k, s in sets)
                    and _ocr_sim(r, f) >= ratio}
            chosen_target = None
            if len(fits) == 1:
                chosen_target = fits.pop()
            elif len(fits) > 1:
                ranked = sorted(fits, key=lambda x: blocks_of[x], reverse=True)
                if blocks_of[ranked[0]] >= 2 * blocks_of[ranked[1]]:
                    chosen_target = ranked[0]
            if chosen_target is not None:
                for n, c in list(out.items()):
                    if c == r:
                        out[n] = chosen_target
    for n, c in list(out.items()):
        seen = {n}
        while c in out and out[c] != c and out[c] not in seen:
            seen.add(c)
            c = out[c]
        out[n] = c
    return out


def _disaggregates_others(own_rows: list, other_rows: list, dim_of) -> bool:
    """True when a later comparative source preserves every named segment of the period's own filing at the same
    value and splits its 'others' bucket into newly named segments whose values (plus any remaining 'others') sum to
    the own filing's 'others' figure within printed rounding."""
    a_map: dict[str, float] = defaultdict(float)
    b_map: dict[str, float] = defaultdict(float)
    for r in own_rows:
        a_map[dim_of(r)] += r[6]
    for r in other_rows:
        b_map[dim_of(r)] += r[6]
    a_others = [d for d in a_map if d in _OTHERS_DIMS]
    if len(a_others) != 1:
        return False
    a_other_val = a_map[a_others[0]]
    a_keep = {d: v for d, v in a_map.items() if d not in _OTHERS_DIMS}
    b_keep = {d: v for d, v in b_map.items() if d not in _OTHERS_DIMS}
    if not a_keep:
        return False
    for d, va in a_keep.items():
        if d not in b_keep:
            if d == "unallocated" and abs(va) <= 1e5:
                continue
            return False
        if abs(b_keep[d] - va) > 0.005 * max(abs(va), 1.0) + 2e5:
            return False
    new_dims = set(b_keep) - set(a_keep)
    if not new_dims:
        return False
    b_other_val = sum(v for d, v in b_map.items() if d in _OTHERS_DIMS)
    split_sum = sum(b_keep[d] for d in new_dims) + b_other_val
    return abs(split_sum - a_other_val) <= 0.005 * max(abs(a_other_val), 1.0) + 2e5


def run_store(db: Path, store: str, dry: bool = False) -> dict:
    head_chars, sections = doc_map.load()
    conn = sqlite3.connect(db if not dry else f"file:{db.as_posix()}?mode=ro", uri=dry)
    if not dry:
        kpi.ensure_unique_with_basis(conn)
    sym, isin = conn.execute("SELECT symbol, isin FROM company LIMIT 1").fetchone()
    docs = conn.execute("SELECT doc_key, known_at, filing_date FROM doc WHERE doc_type='results' AND known_at IS NOT NULL "
                        "ORDER BY known_at").fetchall()
    pl_bases = {b for (b,) in conn.execute("SELECT DISTINCT basis FROM fin_quarter_printed WHERE symbol=? AND basis IN "
                                           "('standalone','consolidated')", (sym,))}
    cand = []          # (metric, name, fiscal_period, ptype, period_end, basis, value_inr, raw, quote, doc_key, page, known_at, own)
    log = []
    for doc_key, known_at, filing_date in docs:
        pages = conn.execute("SELECT page, text FROM doc_page WHERE doc_key=? ORDER BY page", (doc_key,)).fetchall()
        for page, text in pages:
            if "segment_table" not in doc_map.label(text or "", "results", sections, head_chars):
                continue
            pw = words_for(str(db), doc_key, page)
            table = read_table(C.rows_from_words(pw.words), known_at)
            if table is None:
                log.append({"doc_key": doc_key, "page": page, "basis": "", "ok": 0, "blocks": 0, "why": "no segment block"})
                continue
            # the filing's own P&L table (comparatives) fixed its period end: a garbled header takes it, a
            # different one ('September 30,' with the year on the next line read as June) refuses the page
            row = conn.execute("SELECT max(period_end) FROM fin_quarter_printed WHERE doc_key=? AND "
                               "column_role='current'", (doc_key,)).fetchone()
            pl_end = row[0] if row and row[0] else None
            if table["end"] and pl_end and table["end"] != pl_end:
                log.append({"doc_key": doc_key, "page": page, "basis": "", "ok": 0, "blocks": 0,
                            "why": f"period end {table['end']} differs from the filing's P&L {pl_end}"})
                continue
            table["end"] = table["end"] or pl_end
            if not table["end"]:
                log.append({"doc_key": doc_key, "page": page, "basis": "", "ok": 0, "blocks": 0, "why": "no period end"})
                continue
            groups = resolve_bases(conn, doc_key, table, table["scale"], page)
            if not groups:
                log.append({"doc_key": doc_key, "page": page, "basis": "", "ok": 0, "blocks": 0,
                            "why": "columns not one layout (no standalone/consolidated split)"})
            for group, basis in groups:
                if basis not in ("standalone", "consolidated"):
                    log.append({"doc_key": doc_key, "page": page, "basis": "", "ok": 0, "blocks": 0, "why": "basis unknown"})
                    continue
                if pl_bases and basis not in pl_bases:
                    # the company's results print no P&L on this basis at all: the page's basis word is not trusted
                    log.append({"doc_key": doc_key, "page": page, "basis": basis, "ok": 0, "blocks": 0,
                                "why": f"basis {basis} absent from every P&L of the company"})
                    continue
                periods, scale, how = choose_columns(conn, sym, table, group, basis, table["scale"], doc_key, page)
                if periods is None:
                    log.append({"doc_key": doc_key, "page": page, "basis": basis, "ok": 0, "blocks": 0, "why": how})
                    continue
                good = checked_blocks(table, group)
                total_blocks = len({(c.metric, c.column) for c in table["cells"] if c.column in group
                                    and not c.metric.startswith("_")})
                log.append({"doc_key": doc_key, "page": page, "basis": basis, "ok": len(good), "blocks": total_blocks,
                            "why": how if good else "no block adds up"})
                for metric, col, segs in good:
                    if col not in periods:
                        continue
                    period_end, fiscal, ptype, start, own = periods[col]
                    for c in segs:
                        cand.append((metric, c.name, fiscal, ptype, period_end, basis, c.value * scale, c.raw,
                                     c.quote[:300], doc_key, page, known_at, own, c.name_ocr))
    # one spelling per segment name across filings
    # names printed together in one block column are different segments; OCR spellings of one name never are
    by_block = defaultdict(set)
    for r in cand:
        by_block[(r[9], r[10], r[5], r[0], r[2])].add(normalise(r[1]))
    mapping = _canonical([("|".join(map(str, k)), sorted(v)) for k, v in by_block.items()])
    mapping = _swap_ocr(by_block, mapping)
    # a repaired (scan-damaged) name is kept only when it lands on a name the company also prints cleanly
    clean = {mapping.get(normalise(r[1]), normalise(r[1])) for r in cand if not r[13]}
    cand = [r for r in cand if not r[13] or mapping.get(normalise(r[1]), normalise(r[1])) in clean]
    # one source per (metric, period, basis): own current column first (unless a later comparative strictly
    # disaggregates its 'others' bucket into newly named segments), then the latest filing
    dim_of = lambda r: mapping.get(normalise(r[1]), normalise(r[1]))
    by_key_src: dict[tuple, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
    for r in cand:
        by_key_src[(r[0], r[2], r[5])][(r[12], r[11], r[9], r[10])].append(r)
    chosen = []
    for _key, srcs in by_key_src.items():
        win = max(srcs)
        if win[0]:
            later = [s for s in sorted(srcs, reverse=True) if not s[0] and s[1] > win[1]]
            for alt in later:
                if _disaggregates_others(srcs[win], srcs[alt], dim_of):
                    win = alt
                    break
        chosen.extend(srcs[win])
    xbrl = defaultdict(dict)
    for metric, dim, fp, basis, value in conn.execute(
            "SELECT metric, dimension, fiscal_period, basis, value*coalesce(scale,1) FROM kpi_series "
            "WHERE source_type='xbrl_segment' AND dimension!='single_segment'"):
        xbrl[(metric, fp, basis)][dim] = value
    agree = []
    rows = []
    for r in chosen:
        dim = mapping.get(normalise(r[1]), normalise(r[1]))
        x = xbrl.get((r[0], r[2], r[5]))
        if x:
            hit = x.get(dim)
            if hit is not None:
                agree.append({"metric": r[0], "period": r[2], "basis": r[5], "segment": dim, "printed": r[6],
                              "xbrl": hit, "ok": abs(r[6] - hit) <= 0.01 * max(abs(hit), 1)})
            continue
        rows.append((sym, r[0], dim, r[6], "inr", 1.0, r[3], r[2], r[4], r[5], r[9], r[10], r[8], r[11],
                     "doc.known_at", 1, r[1], r[7], RULE, "printed_sum_checked", 4, "table", None, SOURCE_TYPE, sym))
    if not dry:
        conn.execute("DELETE FROM kpi_series WHERE symbol=? AND source_type=?", (sym, SOURCE_TYPE))
        conn.executemany(f"INSERT INTO kpi_series({','.join(kpi.COLS)}) VALUES({','.join('?' * len(kpi.COLS))})", rows)
        conn.commit()
    conn.close()
    return {"store": store, "symbol": sym, "pages": len(log), "pages_ok": sum(1 for x in log if x["ok"]),
            "rows": len(rows), "segments": len({r[2] for r in rows}), "periods": len({r[7] for r in rows}),
            "xbrl_compared": len(agree), "xbrl_agree": sum(1 for a in agree if a["ok"]),
            "log": log, "agree": agree, "row_list": rows}


def run(root: Path, stores: list[str] | None, dry: bool, out_dir: Path | None) -> list[dict]:
    res = []
    for d in sorted(root.glob("c[0-9][0-9]")):
        db = d / f"{d.name}.db"
        if db.is_file() and (not stores or d.name in stores):
            r = run_store(db, d.name, dry)
            res.append(r)
            print(json.dumps({k: v for k, v in r.items() if k not in ("log", "agree", "row_list")}), flush=True)
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "seg_pages.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["store", "symbol", "doc_key", "page", "basis", "blocks_ok", "blocks", "why"])
            for r in res:
                for x in r["log"]:
                    w.writerow([r["store"], r["symbol"], x["doc_key"], x["page"], x["basis"], x["ok"], x["blocks"], x["why"]])
        with open(out_dir / "seg_xbrl.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["store", "symbol", "metric", "period", "basis", "segment", "printed", "xbrl", "ok"])
            for r in res:
                for a in r["agree"]:
                    w.writerow([r["store"], r["symbol"], a["metric"], a["period"], a["basis"], a["segment"], a["printed"], a["xbrl"], a["ok"]])
        with open(out_dir / "seg_rows.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["store", "symbol", "metric", "segment", "value_inr", "period_type", "fiscal_period", "period_end",
                        "basis", "doc_key", "page", "quote", "known_at", "printed_label", "raw"])
            for r in res:
                for x in r["row_list"]:
                    w.writerow([r["store"], r["symbol"], x[1], x[2], x[3], x[6], x[7], x[8], x[9], x[10], x[11], x[12], x[13], x[16], x[17]])
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
    print(json.dumps({k: sum(r[k] for r in res) for k in ("pages", "pages_ok", "rows", "xbrl_compared", "xbrl_agree")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
