"""T-225 XBRL line-item judge for page cells.

A page cell the checker calls ``verified`` is judged against the store's own XBRL facts on its LINE ITEM, period
and basis, not on its value alone.  The earlier judge (``.tmp/t225/resettle_c09.py``) looked a cell's value up
across every XBRL fact and then compared quarters, so a value that happened to equal some other line raised a
false alarm (c88, c61) and a right value under a wrong row label passed.

XBRL sources: quarter columns -> ``fin_quarter_xbrl``; year and half-year columns of a P&L or cash-flow table and
balance-sheet date columns -> ``fin_annual_line`` rows with ``source_table='facts'`` (``P&L`` / ``CF`` by
``period_type`` FY or H1; ``BS`` by date).

For one cell:

1. a segment table or segment row, and a table of other entities (Form AOC-1 subsidiaries, associates, joint
   ventures), is never judged: neither is the company's own line;
2. the column header gives the period end date (``31.12.2025``, ``31st December, 2025``, ``Dec 31, 2025``,
   ``Dec-25``) and the period kind (:func:`column_kind`): quarter, nine months (never judged: XBRL holds no
   nine-month facts), half, year, a balance-sheet date, or unprinted;
3. the table decides the statement: a balance-sheet title ("Balance Sheet", "Statement of Assets & Liabilities")
   or an "As at" column -> :func:`bs_lines`; a cash-flow title -> :func:`cf_line` (the R-025 dictionary
   ``ar_statements.LINES`` plus borrowing, lease and cash-generated lines); otherwise the P&L lexicon
   ``pilot3/lexicon/results_lines.yaml`` through ``comparatives.match_line``.  A balance-sheet label whose block
   (current / non-current) is not printed is judged against both lines;
4. the basis comes from the table title (consolidated / standalone); none printed = either basis;
5. the unit from the cell's unit text, then the table title (lakh, crore, million, thousand, rupees); per-share
   lines are rupees; an unknown unit tries every scale;
6. the printed figure agrees when it is within half its last printed digit (scaled) plus 0.1% of any XBRL row for
   that (period, basis, line); restated rows all count.  A figure that agrees only in absolute value agrees with
   ``sign_flip`` set (XBRL sign conventions for inventory changes, tax credits and payments vary).

Verdicts: ``agree``, ``disagree`` (XBRL holds the line for that period and basis, and no row matches; reason
``near_miss`` within 2%, ``decimal_lost`` when the figure agrees once a lost decimal point is put back -- a
reader defect seen on HY4 OCR pages, "14277" for 1,427.7; ``other_period`` when the figure is the same line of
another period (a misplaced column: c19 BODALCHEM's Q 30.06.2024 revenue verified under 30.06.2025); ``elsewhere``
names the XBRL lines the value does match: ``basis:line`` in the same period, then
``KEY:period_end:basis:line`` in other periods (up to ``ELSEWHERE_MAX``), which separates a wrong label, a wrong
figure and a misplaced column) and ``no_xbrl_line`` (``reason`` says why).  A P&L or cash-flow
column whose period type is unprinted is tried against the quarter, half and year facts and may only agree.

CLI::

    python -m reality_engine.v2.cell_judge --read <read_*.db> --store <store.db> [--status verified] [--out x.csv]
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from reality_engine.pilot3.ar_statements import _SECTION_OF_LINE as CF_SECTION_OF_LINE
from reality_engine.pilot3.ar_statements import LINES as CF_LINES
from reality_engine.pilot3.comparatives import match_line

AGREE, DISAGREE, NO_LINE = "agree", "disagree", "no_xbrl_line"
PER_SHARE = {"eps_basic", "eps_diluted", "face_value"}
REL_TOL = 0.001
CELL_ALARM_AGREE = 2
NEAR_TOL = 0.02   # a disagreement within 2%: a restated filing or EPS rounding more often than a misread
COLUMN_ALARM_DISAGREE = 3
ELSEWHERE_MAX = 5   # other-period matches listed per disagreeing cell
# XBRL period keys: quarter, half year, full year, balance-sheet date
Q, H1, FY, BS = "Q", "H1", "FY", "BS"

_UNITS = (
    (re.compile(r"\b(lakhs?|lacs?|lakh)\b", re.I), 1e5),
    (re.compile(r"\b(crores?|crs?)\b", re.I), 1e7),
    (re.compile(r"\b(millions?|mn|mio)\b", re.I), 1e6),
    (re.compile(r"\bthousands?\b|['’`]\s*000\b", re.I), 1e3),
    (re.compile(r"\b(rupees|rs|inr)\b|₹", re.I), 1.0),
)
_SEGMENT = re.compile(r"\bsegment", re.I)
_QUARTER = re.compile(r"quarter|\bq[1-4]\b|three\s+months|\b3\s*months", re.I)
_KINDS = (  # checked in this order once "quarter" is ruled out
    ("nine", re.compile(r"nine|\b9\s*months?", re.I)),
    ("half", re.compile(r"half|six|\b6\s*months?", re.I)),
    ("year", re.compile(r"year|twelve|\b12\s*months?|annual", re.I)),
    ("as_at", re.compile(r"\bas\s+(at|on)\b", re.I)),
)
_BS_TITLE = re.compile(r"balance\s+sheet|financial\s+position|assets\s*(&|and)\s*liabilities", re.I)
_CF_TITLE = re.compile(r"cash\s*-?\s*flow", re.I)
_YEAR_TITLE = re.compile(r"year\s+ended|for\s+the\s+year|annual", re.I)
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), start=1)}
_D_M_Y = re.compile(r"\b(\d{1,2})\s*[./\-]\s*(\d{1,2})\s*[./\-]\s*(\d{2,4})\b")
_D_MON_Y = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-./,]*([a-z]{3,9})[\s\-./,']*(\d{2,4})\b", re.I)
_MON_D_Y = re.compile(r"\b([a-z]{3,9})[\s\-./]*(\d{1,2})(?:st|nd|rd|th)?[\s,.\-/']+(\d{4})\b", re.I)
_MON_Y = re.compile(r"\b([a-z]{3,9})[\s\-./,']*(\d{4}|\d{2})\b", re.I)
_DASH = {"", "-", "–", "—", "--", "nil", "na", "n.a.", "n/a"}

# balance-sheet labels, matched WHOLE after normalising (enumerators, punctuation and a trailing "net" dropped).
# A value names its line, or (current line, non-current line) when the printed block decides.
_BsItem = str | tuple[str, ...]   # one line, or the (current, non-current[, undivided]) lines a block picks from
_BS_LABELS: tuple[tuple[re.Pattern[str], _BsItem], ...] = tuple((re.compile(rf"^(?:{rx})$"), item) for rx, item in (
    (r"total assets", "total_assets"),
    (r"total equity and liabilities|equity and liabilities total|total liabilities and equity", "total_assets"),
    (r"total equity", "total_equity"),
    (r"shareholders? funds|total shareholders? funds", ("total_equity", "shareholders_funds")),
    (r"total liabilities", "total_liabilities"),
    (r"total current assets|current assets", "current_assets"),
    (r"total non current assets|non current assets", "noncurrent_assets"),
    (r"total current liabilities|current liabilities", "current_liabilities"),
    (r"total non current liabilities|non current liabilities", "noncurrent_liabilities"),
    (r"(equity )?share capital", "equity_share_capital"),
    (r"other equity", "other_equity"),
    (r"reserves? and surplus", ("other_equity", "reserves_and_surplus")),
    (r"non controlling interests?|minority interests?", "non_controlling_interest"),
    (r"inventories|inventory", "inventories"),
    (r"cash and cash equivalents?", "cash_and_equivalents"),
    (r"bank balances? other than .*|other bank balances?", "bank_balances"),
    (r"capital work in progress|capital wip", "capital_work_in_progress"),
    (r"trade receivables?", ("trade_receivables_current", "trade_receivables_noncurrent", "trade_receivables")),
    (r"trade payables?", ("trade_payables_current", "trade_payables_noncurrent")),
    (r"borrowings?", ("borrowings_current", "borrowings_noncurrent")),
    (r"short term borrowings?", "borrowings_current"),
    (r"long term borrowings?", "borrowings_noncurrent"),
    (r"investments?", ("current_investments", "noncurrent_investments")),
    (r"current investments?", "current_investments"),
    (r"non current investments?", "noncurrent_investments"),
    (r"loans?", ("loans_current", "loans_noncurrent")),
))
_NONCURRENT = re.compile(r"non\s*-?\s*current|long\s*-?\s*term", re.I)
_CURRENT = re.compile(r"\bcurrent|short\s*-?\s*term", re.I)
# cash-flow lines the R-025 dictionary does not carry; checked first
_CF_EXTRA = (
    ("cash_generated_from_operations", re.compile(r"^(?!.*\bnet\b).*cash\s+(generated|flows?)\s+(from|used\s+in)\s+"
                                                  r"operations\b", re.I)),
    ("proceeds_from_borrowings", re.compile(r"^(proceeds|receipts?)\b.*borrowings?|^(availment|taking)\b.*(loans?|"
                                            r"borrowings?)", re.I)),
    ("repayment_of_borrowings", re.compile(r"^repayments?\b(?!.*lease).*(borrowings?|loans?)", re.I)),
    ("lease_payments", re.compile(r"(payment|repayment)s?\s+(of|towards)\s+lease", re.I)),
)
_CF_SECTION = re.compile(r"operating|investing|financing", re.I)
# an operating adjustment ("(Profit)/loss on sale of PPE", "Impairment of asset held for sale") is not the
# investing or financing cash line it names
_CF_ADJUSTMENT = re.compile(r"\b(profit|loss|gain|impairment|write|provision|fair\s+value)", re.I)
# a table of other entities (Form AOC-1 subsidiaries, associates, joint ventures) is not the company's statement
_OTHER_ENTITY = re.compile(r"subsidiar|associate|joint\s+venture|\baoc\b", re.I)


@dataclass
class Verdict:
    verdict: str
    reason: str = ""
    line_item: str | None = None
    period_end: str | None = None
    basis: str | None = None
    printed: float | None = None
    xbrl: list = field(default_factory=list)
    sign_flip: bool = False
    elsewhere: list = field(default_factory=list)
    period_key: str | None = None


def _year(text: str) -> int:
    y = int(text)
    return y + 2000 if y < 100 else y


def _month_end(year: int, month: int) -> str | None:
    if not 1 <= month <= 12 or not 1990 <= year <= 2100:
        return None
    days = (31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31,
            30, 31)
    return f"{year:04d}-{month:02d}-{days[month - 1]:02d}"


def _mon(word: str) -> int | None:
    return _MONTHS.get(word[:3].lower())


def period_end(col_header: str | None) -> str | None:
    """The period end date a column header prints, as an ISO month end; None when none is printed."""
    text = col_header or ""
    m = _D_M_Y.search(text)
    if m:
        return _month_end(_year(m.group(3)), int(m.group(2)))
    for rx, mi, yi in ((_D_MON_Y, 2, 3), (_MON_D_Y, 1, 3), (_MON_Y, 1, 2)):
        for m in rx.finditer(text):
            month = _mon(m.group(mi))
            if month:
                return _month_end(_year(m.group(yi)), month)
    return None


def column_kind(col_header: str | None, table_title: str | None = None) -> str:
    """The period a column covers: ``quarter`` (it names a quarter or three months; "Corresponding quarter of the
    previous year" is a quarter), ``nine``, ``half``, ``year``, ``as_at`` (a balance-sheet date) or ``unprinted``.
    A header that names no period type takes it from a title that names only one kind ("Statement of Profit and
    Loss for the year ended 31 March 2025", "Balance Sheet"); otherwise it stays ``unprinted``: a reader often
    drops the "Half year ended" level, leaving "30.09.2025 (Unaudited)" over an H1 figure."""
    text = col_header or ""
    if _QUARTER.search(text):
        return "quarter"
    for kind, rx in _KINDS:
        if rx.search(text):
            return kind
    title = table_title or ""
    if _BS_TITLE.search(title):
        return "as_at"
    if _YEAR_TITLE.search(title) and not _QUARTER.search(title) and not any(
            rx.search(title) for kind, rx in _KINDS if kind in ("nine", "half")):
        return "year"
    return "unprinted"


def scale_of(*texts: str | None) -> float | None:
    for text in texts:
        for rx, scale in _UNITS:
            if text and rx.search(text):
                return scale
    return None


def basis_of(table_title: str | None) -> str | None:
    t = (table_title or "").lower()
    cons, stand = "consolidated" in t, "standalone" in t or "stand alone" in t or "stand-alone" in t
    if cons == stand:
        return None
    return "consolidated" if cons else "standalone"


def number(text: str | None) -> tuple[float, int] | None:
    """``(value, decimals)`` of a printed figure; brackets or a leading minus are negative."""
    t = (text or "").strip()
    if t.lower() in _DASH:
        return None
    neg = t.startswith("(") or t.startswith("-") or t.startswith("−")
    digits = re.sub(r"[^\d.]", "", t)
    if not re.fullmatch(r"\d+(\.\d+)?", digits):
        return None
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    return (-1 if neg else 1) * float(digits), decimals


def _parts(row_label: str | None) -> list[str]:
    return [p.strip() for p in (row_label or "").split(">") if p.strip()]


def line_of(row_label: str | None) -> str | None:
    """P&L line of a results row: the leaf, then its last two levels, through the printed-results lexicon."""
    parts = _parts(row_label)
    if not parts:
        return None
    return match_line(parts[-1]) or (match_line(" ".join(parts[-2:])) if len(parts) > 1 else None)


def _bs_norm(text: str) -> str:
    t = text.lower().replace("&", " and ")
    t = re.sub(r"^\s*(?:(?:\(?[0-9]{1,2}[a-z]?\)?|\(?[ivx]{1,4}\)|\(?[a-h]\)|[a-h]\.|[ivx]{1,4}\.)\s*)+", " ", t)
    t = re.sub(r"\bnote\s*\d+\b", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return re.sub(r"\s+net$", "", t)


def bs_lines(row_label: str | None) -> tuple[str, ...]:
    """Balance-sheet line(s) a row label names, matched whole; the printed block (a parent naming current or
    non-current, or the label itself) picks one of a (current, non-current) pair."""
    parts = _parts(row_label)
    if not parts:
        return ()
    leaf = _bs_norm(parts[-1])
    for rx, item in _BS_LABELS:
        if not rx.match(leaf):
            continue
        if isinstance(item, str):
            return (item,)
        parent = " ".join(parts[:-1])
        pair = [i for i in item if i.endswith(("_current", "_noncurrent")) or i.startswith(("current_", "noncurrent_"))]
        if len(pair) == 2 and parent:
            if _NONCURRENT.search(parent):
                return tuple(i for i in item if "noncurrent" in i)
            if _CURRENT.search(parent):
                return tuple(i for i in item if "noncurrent" not in i)
        return tuple(item)
    return ()


def cf_line(row_label: str | None) -> str | None:
    """Cash-flow line of a cash-flow-statement row: the extra rules, then the R-025 dictionary (first match wins).
    A line that counts only inside its own activity block is refused when the printed parent names another one."""
    parts = _parts(row_label)
    if not parts:
        return None
    leaf = re.sub(r"\s+", " ", parts[-1]).strip()
    for item, rx in _CF_EXTRA:
        if rx.search(leaf):
            return item
    parent = " ".join(parts[:-1])
    block = _CF_SECTION.search(parent)
    for item, rx, _total in CF_LINES:
        if rx.search(leaf):
            need = CF_SECTION_OF_LINE.get(item)
            if need and (block and block.group(0).lower() != need or _CF_ADJUSTMENT.search(leaf)):
                return None
            return item
    return None


class XbrlIndex:
    """One store's XBRL facts: (period key, period_end, basis, line_item) -> rupee values.

    ``rows``: ``fin_quarter_xbrl`` (period_end, basis, line_item, value, scale), keyed ``Q``.  ``annual_rows``:
    ``fin_annual_line`` facts (statement, period_type, period_end, basis, line_item, value, scale): ``BS`` rows keyed
    by date, ``P&L`` / ``CF`` rows keyed ``FY`` or ``H1``."""

    def __init__(self, rows, annual_rows=()):
        self.by_key: dict[tuple[str, str, str, str], list[float]] = collections.defaultdict(list)
        self.by_period: dict[tuple[str, str], list[tuple[str, str, float]]] = collections.defaultdict(list)
        for end, basis, item, value, scale in rows:
            self._add(Q, end, basis, item, value, scale)
        for statement, ptype, end, basis, item, value, scale in annual_rows:
            key = BS if statement == "BS" else ptype if ptype in (FY, H1) else None
            if key:
                self._add(key, end, basis, item, value, scale)

    def _add(self, key, end, basis, item, value, scale):
        if value is None or not end:
            return
        v = float(value) * float(scale or 1)
        self.by_key[(key, end, basis, item)].append(v)
        self.by_period[(key, end)].append((basis, item, v))

    @classmethod
    def from_store(cls, store_db: str | Path) -> XbrlIndex:
        con = sqlite3.connect(f"file:{Path(store_db).as_posix()}?mode=ro", uri=True)
        try:
            quarter = con.execute("SELECT period_end, basis, line_item, value, scale FROM fin_quarter_xbrl").fetchall()
            annual = con.execute("SELECT statement, period_type, period_end, basis, line_item, value, scale "
                                 "FROM fin_annual_line WHERE source_table='facts'").fetchall()
            return cls(quarter, annual)
        finally:
            con.close()


def _close(printed: float, decimals: int, scale: float, x: float) -> tuple[bool, bool]:
    """(agrees, sign_flip)."""
    tol = 0.5 * 10 ** -decimals * scale + REL_TOL * abs(x) + 1e-9
    if abs(printed - x) <= tol:
        return True, False
    return abs(abs(printed) - abs(x)) <= tol, True


_KIND_KEY = {"quarter": Q, "half": H1, "year": FY}


def judge(cell: dict, xbrl: XbrlIndex) -> Verdict:
    """Judge one page cell (keys ``row_label``, ``col_header``, ``value_text``, ``unit_text``, ``table_title``)."""
    title = cell.get("table_title") or ""
    if _SEGMENT.search(title) or _SEGMENT.search(cell.get("row_label") or ""):
        return Verdict(NO_LINE, "segment_table")
    if _OTHER_ENTITY.search(title):
        return Verdict(NO_LINE, "other_entity_table")
    col = cell.get("col_header") or ""
    kind = column_kind(col, title)
    if _BS_TITLE.search(title) or kind == "as_at":
        items, keys = bs_lines(cell.get("row_label")), (BS,)
    else:
        if _CF_TITLE.search(title):
            one = cf_line(cell.get("row_label"))
            allowed = (FY, H1)
        else:
            one = line_of(cell.get("row_label"))
            allowed = (Q, FY, H1)
        items = (one,) if one else ()
        if kind in _KIND_KEY:
            keys = (_KIND_KEY[kind],) if _KIND_KEY[kind] in allowed else ()
        else:   # unprinted: tried against every allowed period, may only agree
            keys = allowed if kind == "unprinted" else ()
    if not items:
        return Verdict(NO_LINE, "label_unmapped")
    item = items[0] if len(items) == 1 else "|".join(items)
    if kind == "nine":
        return Verdict(NO_LINE, "nine_month_column", item)
    if not keys:
        return Verdict(NO_LINE, "period_not_held", item)
    end = period_end(col)
    if end is None:
        return Verdict(NO_LINE, "no_period_date", item)
    num = number(cell.get("value_text"))
    if num is None:
        return Verdict(NO_LINE, "not_a_number", item, end)
    value, decimals = num
    basis = basis_of(title)
    bases = (basis,) if basis else ("consolidated", "standalone")
    found = {k: [x for b in bases for i in items for x in xbrl.by_key.get((k, end, b, i), [])] for k in keys}
    candidates = [x for k in keys for x in found[k]]
    if not candidates:
        return Verdict(NO_LINE, "no_xbrl_row", item, end, basis)
    if any(i in PER_SHARE for i in items):
        scales = [1.0]
    else:
        s = scale_of(cell.get("unit_text"), title)
        scales = [s] if s else [1e5, 1e7, 1e6, 1e3, 1.0]
    flip_key = None
    for k in keys:
        for scale in scales:
            for x in found[k]:
                ok, flip = _close(value * scale, decimals, scale, x)
                if ok and not flip:
                    return Verdict(AGREE, "", item, end, basis, value * scale, found[k], period_key=k)
                if ok and flip_key is None:
                    flip_key = k
    if flip_key:
        return Verdict(AGREE, "sign_flip", item, end, basis, value * scales[0], found[flip_key], sign_flip=True,
                       period_key=flip_key)
    if kind == "unprinted":
        # the period type is not printed: a half or nine-month figure under a bare date is not a wrong cell
        return Verdict(NO_LINE, "period_type_unprinted", item, end, basis, value * scales[0], candidates)
    key = keys[0]
    per_share = any(i in PER_SHARE for i in items)
    same, other, scale_hit = set(), set(), None
    for (k, e), facts in xbrl.by_period.items():
        for b, i, x in facts:
            if b not in bases or (i in PER_SHARE) != per_share or (k, e) == (key, end) and i in items:
                continue
            for scale in scales:
                if _close(value * scale, decimals, scale, x)[0]:
                    scale_hit = scale_hit or scale
                    if (k, e) == (key, end):
                        same.add(f"{b}:{i}")
                    else:
                        other.add((i in items, f"{k}:{e}:{b}:{i}"))
    # same-period lines first ("basis:line"), then other periods ("KEY:period_end:basis:line"), the cell's own line
    # first among those; a value that is the same line of another period means the column was misplaced
    elsewhere = sorted(same) + [s for _own, s in sorted(other, key=lambda t: (not t[0], t[1]))][:ELSEWHERE_MAX]
    own_other = any(own for own, _s in other)
    near = any(abs(abs(value * sc) - abs(x)) <= NEAR_TOL * max(abs(x), 1e-9) for sc in scales for x in candidates)
    # the printed figure with its decimal point lost ("14277" for 1,427.7, "016" for 0.16): a reader defect
    lost = decimals == 0 and any(_close(value * sc / 10 ** k, k, sc, x)[0] for k in (1, 2, 3) for sc in scales
                                 for x in candidates)
    reason = ("decimal_lost" if lost else "other_period" if own_other else "near_miss" if near
              else "value_differs")
    shown = scale_hit or min(scales, key=lambda sc: min(abs(abs(value * sc) - abs(x)) / max(abs(x), 1e-9)
                                                        for x in candidates))
    return Verdict(DISAGREE, reason, item, end, basis, value * shown, candidates, elsewhere=elsewhere,
                   period_key=key)


def judge_read(read_db: str | Path, store_db: str | Path, status: str | None = "verified") -> list[dict]:
    xbrl = XbrlIndex.from_store(store_db)
    con = sqlite3.connect(f"file:{Path(read_db).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sql = ("SELECT doc_key, page, status, table_title, row_label, col_header, value_text, unit_text FROM page_cell"
           + (" WHERE status=?" if status else ""))
    out = []
    try:
        for row in con.execute(sql, (status,) if status else ()):
            cell = dict(row)
            v = judge(cell, xbrl)
            rec = {**cell, **asdict(v)}
            rec["xbrl"] = ";".join(f"{x:g}" for x in v.xbrl)
            rec["elsewhere"] = ";".join(v.elsewhere)
            out.append(rec)
    finally:
        con.close()
    return mark_alarms(out)


def mark_alarms(records: list[dict]) -> list[dict]:
    """Per printed column (doc, page, table, column header): a disagreeing cell in a column where at least
    ``CELL_ALARM_AGREE`` other cells agree is a ``cell`` alarm (wrong label or figure on that row); a column with
    no agreeing cell and at least ``COLUMN_ALARM_DISAGREE`` disagreeing ones is a ``column`` alarm (the column's
    period was read wrong, or the store's XBRL period is not this filing's), not evidence against each cell."""
    cols: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    key = lambda r: (r.get("doc_key"), r.get("page"), r.get("table_title"), r.get("col_header"))  # noqa: E731
    for r in records:
        cols[key(r)][r["verdict"]] += 1
    for r in records:
        c = cols[key(r)]
        r["column_agree"], r["column_disagree"] = c[AGREE], c[DISAGREE]
        r["alarm"] = ""
        if r["verdict"] == DISAGREE:
            if r["reason"] == "near_miss":
                r["alarm"] = "near"
            elif c[AGREE] >= CELL_ALARM_AGREE:
                r["alarm"] = "cell"
            elif c[AGREE] == 0 and c[DISAGREE] >= COLUMN_ALARM_DISAGREE:
                r["alarm"] = "column"
    return records


def summary(records: list[dict]) -> dict:
    c = collections.Counter(r["verdict"] for r in records)
    reasons = collections.Counter(r["reason"] for r in records if r["verdict"] == NO_LINE)
    by_key = collections.Counter(f"{r.get('period_key')}:{r['verdict']}" for r in records
                                 if r["verdict"] in (AGREE, DISAGREE))
    return {"cells": len(records), AGREE: c[AGREE], DISAGREE: c[DISAGREE], NO_LINE: c[NO_LINE],
            "sign_flip": sum(1 for r in records if r["sign_flip"]),
            "disagree_value_elsewhere": sum(1 for r in records if r["verdict"] == DISAGREE and r["elsewhere"]),
            "near_miss": sum(1 for r in records if r.get("alarm") == "near"),
            "decimal_lost": sum(1 for r in records if r["reason"] == "decimal_lost"),
            "other_period": sum(1 for r in records if r["reason"] == "other_period"),
            "cell_alarms": sum(1 for r in records if r.get("alarm") == "cell"),
            "column_alarms": sum(1 for r in records if r.get("alarm") == "column"),
            "by_period": dict(by_key), "no_line_reasons": dict(reasons)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0] if __doc__ else None)
    ap.add_argument("--read", required=True, help="reader output db with a page_cell table")
    ap.add_argument("--store", required=True, help="store db with fin_quarter_xbrl and fin_annual_line")
    ap.add_argument("--status", default="verified", help="page_cell status to judge; 'all' for every cell")
    ap.add_argument("--out", help="CSV of every judged cell")
    a = ap.parse_args(argv)
    recs = judge_read(a.read, a.store, None if a.status == "all" else a.status)
    if a.out:
        with open(a.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(recs[0]) if recs else ["verdict"])
            w.writeheader()
            w.writerows(recs)
    print(summary(recs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
