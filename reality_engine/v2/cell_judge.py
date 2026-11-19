"""T-225 XBRL line-item judge for page cells.

A page cell the checker calls ``verified`` is judged against the store's own XBRL quarter facts
(``fin_quarter_xbrl``) on its LINE ITEM, quarter and basis, not on its value alone.  The earlier judge
(``.tmp/t225/resettle_c09.py``) looked a cell's value up across every XBRL fact and then compared quarters, so a
value that happened to equal some other line raised a false alarm (c88, c61) and a right value under a wrong
row label passed.

For one cell:

1. the row label's leaf (then its last two levels) is mapped to the canonical line item with the printed-results
   lexicon ``pilot3/lexicon/results_lines.yaml`` through ``comparatives.match_line``, the same names XBRL rows use;
2. the column header must name a quarter (a nine-month, half-year or year column has no XBRL quarter fact) and a
   period end date (``31.12.2025``, ``31st December, 2025``, ``Dec 31, 2025``, ``Dec-25``);
3. the basis comes from the table title (consolidated / standalone); none printed = either basis;
4. the unit from the cell's unit text, then the table title (lakh, crore, million, thousand, rupees); per-share
   lines are rupees; an unknown unit tries every scale;
5. the printed figure agrees when it is within half its last printed digit (scaled) plus 0.1% of any XBRL row for
   that (period end, basis, line item); restated rows all count.  A figure that agrees only in absolute value
   agrees with ``sign_flip`` set (XBRL sign conventions for inventory changes and tax credits vary).

Verdicts: ``agree``, ``disagree`` (XBRL holds the line for that quarter and basis, and no row matches; reason
``near_miss`` within 2%; ``elsewhere``
names the XBRL lines the value does match, which separates a wrong label from a wrong figure) and ``no_xbrl_line``
(``reason`` says why: unmapped label, not a quarter column, no date, not a number, no XBRL row).

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

from reality_engine.pilot3.comparatives import match_line

AGREE, DISAGREE, NO_LINE = "agree", "disagree", "no_xbrl_line"
PER_SHARE = {"eps_basic", "eps_diluted", "face_value"}
REL_TOL = 0.001
CELL_ALARM_AGREE = 2
NEAR_TOL = 0.02   # a disagreement within 2%: a restated filing or EPS rounding more often than a misread
COLUMN_ALARM_DISAGREE = 3

_UNITS = (
    (re.compile(r"\b(lakhs?|lacs?|lakh)\b", re.I), 1e5),
    (re.compile(r"\b(crores?|crs?)\b", re.I), 1e7),
    (re.compile(r"\b(millions?|mn|mio)\b", re.I), 1e6),
    (re.compile(r"\bthousands?\b|['’`]\s*000\b", re.I), 1e3),
    (re.compile(r"\b(rupees|rs|inr)\b|₹", re.I), 1.0),
)
_NOT_QUARTER = re.compile(r"nine|\b9\s*months?|half|six|\b6\s*months?|year|twelve|\b12\s*months?|annual|ytd|"
                          r"cumulative|period\s+ended\s+.*\bto\b", re.I)
_SEGMENT = re.compile(r"\bsegment", re.I)   # a segment result is not the company's P&L line
_QUARTER = re.compile(r"quarter|\bq[1-4]\b|three\s+months|\b3\s*months", re.I)
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), start=1)}
_D_M_Y = re.compile(r"\b(\d{1,2})\s*[./\-]\s*(\d{1,2})\s*[./\-]\s*(\d{2,4})\b")
_D_MON_Y = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-./,]*([a-z]{3,9})[\s\-./,']*(\d{2,4})\b", re.I)
_MON_D_Y = re.compile(r"\b([a-z]{3,9})[\s\-./]*(\d{1,2})(?:st|nd|rd|th)?[\s,.\-/']+(\d{4})\b", re.I)
_MON_Y = re.compile(r"\b([a-z]{3,9})[\s\-./,']*(\d{4}|\d{2})\b", re.I)
_DASH = {"", "-", "–", "—", "--", "nil", "na", "n.a.", "n/a"}


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


def column_kind(col_header: str | None) -> str:
    """``quarter`` when the header names a quarter or three months ("Corresponding quarter of the previous year"
    is a quarter), ``longer`` when it names nine months, a half or a year, ``unprinted`` when it names neither:
    a reader often drops the "Half year ended" header level, leaving "30.09.2025 (Unaudited)" over an H1 figure."""
    text = col_header or ""
    if _QUARTER.search(text):
        return "quarter"
    return "longer" if _NOT_QUARTER.search(text) else "unprinted"


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


def line_of(row_label: str | None) -> str | None:
    parts = [p.strip() for p in (row_label or "").split(">") if p.strip()]
    if not parts:
        return None
    return match_line(parts[-1]) or (match_line(" ".join(parts[-2:])) if len(parts) > 1 else None)


class XbrlIndex:
    """``fin_quarter_xbrl`` of one store: (period_end, basis, line_item) -> rupee values."""

    def __init__(self, rows):
        self.by_key: dict[tuple[str, str, str], list[float]] = collections.defaultdict(list)
        self.by_period: dict[str, list[tuple[str, str, float]]] = collections.defaultdict(list)
        for end, basis, item, value, scale in rows:
            if value is None or not end:
                continue
            v = float(value) * float(scale or 1)
            self.by_key[(end, basis, item)].append(v)
            self.by_period[end].append((basis, item, v))

    @classmethod
    def from_store(cls, store_db: str | Path) -> XbrlIndex:
        con = sqlite3.connect(f"file:{Path(store_db).as_posix()}?mode=ro", uri=True)
        try:
            return cls(con.execute("SELECT period_end, basis, line_item, value, scale FROM fin_quarter_xbrl"))
        finally:
            con.close()


def _close(printed: float, decimals: int, scale: float, x: float) -> tuple[bool, bool]:
    """(agrees, sign_flip)."""
    tol = 0.5 * 10 ** -decimals * scale + REL_TOL * abs(x) + 1e-9
    if abs(printed - x) <= tol:
        return True, False
    return abs(abs(printed) - abs(x)) <= tol, True


def judge(cell: dict, xbrl: XbrlIndex) -> Verdict:
    """Judge one page cell (keys ``row_label``, ``col_header``, ``value_text``, ``unit_text``, ``table_title``)."""
    if _SEGMENT.search(cell.get("table_title") or "") or _SEGMENT.search(cell.get("row_label") or ""):
        return Verdict(NO_LINE, "segment_table")
    item = line_of(cell.get("row_label"))
    if item is None:
        return Verdict(NO_LINE, "label_unmapped")
    col = cell.get("col_header") or ""
    kind = column_kind(col)
    if kind == "longer":
        return Verdict(NO_LINE, "not_quarter_column", item)
    end = period_end(col)
    if end is None:
        return Verdict(NO_LINE, "no_period_date", item)
    num = number(cell.get("value_text"))
    if num is None:
        return Verdict(NO_LINE, "not_a_number", item, end)
    value, decimals = num
    basis = basis_of(cell.get("table_title"))
    bases = (basis,) if basis else ("consolidated", "standalone")
    candidates = [x for b in bases for x in xbrl.by_key.get((end, b, item), [])]
    if not candidates:
        return Verdict(NO_LINE, "no_xbrl_row", item, end, basis)
    if item in PER_SHARE:
        scales = [1.0]
    else:
        s = scale_of(cell.get("unit_text"), cell.get("table_title"))
        scales = [s] if s else [1e5, 1e7, 1e6, 1e3, 1.0]
    flip_seen = False
    for scale in scales:
        for x in candidates:
            ok, flip = _close(value * scale, decimals, scale, x)
            if ok and not flip:
                return Verdict(AGREE, "", item, end, basis, value * scale, candidates)
            flip_seen = flip_seen or ok
    if flip_seen:
        return Verdict(AGREE, "sign_flip", item, end, basis, value * scales[0], candidates, sign_flip=True)
    if kind == "unprinted":
        # a quarter figure would have agreed; an unprinted period type may be a half or nine-month column
        return Verdict(NO_LINE, "period_type_unprinted", item, end, basis, value * scales[0], candidates)
    elsewhere = sorted({f"{b}:{i}" for scale in scales for b, i, x in xbrl.by_period.get(end, [])
                        if b in bases and i != item and _close(value * scale, decimals, scale, x)[0]})
    near = any(abs(abs(value * sc) - abs(x)) <= NEAR_TOL * max(abs(x), 1e-9) for sc in scales for x in candidates)
    return Verdict(DISAGREE, "near_miss" if near else "value_differs", item, end, basis, value * scales[0], candidates,
                   elsewhere=elsewhere)


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
    period was read wrong, or the store's XBRL quarter is not this filing's), not evidence against each cell."""
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
    return {"cells": len(records), AGREE: c[AGREE], DISAGREE: c[DISAGREE], NO_LINE: c[NO_LINE],
            "sign_flip": sum(1 for r in records if r["sign_flip"]),
            "disagree_value_elsewhere": sum(1 for r in records if r["verdict"] == DISAGREE and r["elsewhere"]),
            "near_miss": sum(1 for r in records if r.get("alarm") == "near"),
            "cell_alarms": sum(1 for r in records if r.get("alarm") == "cell"),
            "column_alarms": sum(1 for r in records if r.get("alarm") == "column"),
            "no_line_reasons": dict(reasons)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0] if __doc__ else None)
    ap.add_argument("--read", required=True, help="reader output db with a page_cell table")
    ap.add_argument("--store", required=True, help="store db with fin_quarter_xbrl")
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
