"""Cross-check hy4 results/AR rows against the exchange's filed XBRL (T-242, Shivam 26 Nov 2026, Wolf).

Two filed sources:

* ``fin_quarter_xbrl`` holds the filed quarterly P&L lines (value in rupees, period_start/period_end, basis) -- a
  quarter-period row whose measure maps to an XBRL line is compared at the same quarter end and basis;
* ``fin_annual_line`` holds the filed balance-sheet, cash-flow and P&L lines, mostly half-years (``period_type``
  ``H1``/``FY``/``Q`` plus ``statement`` ``BS``/``P&L``/``CF``) -- a BS row is compared on its as-at date
  (``kind='stock'``), a P&L/CF row only when its period names the same duration (half year -> ``H1``,
  year -> ``FY``, quarter -> ``Q``) and end date.

A row checked by both sources keeps one verdict: a match in either wins, a contradiction only when no source matches.
Verdicts and rules (same for both sources):

* within tolerance -> verdict ``xbrl_match``: the loader serves it ``verified`` even when its doc type is capped;
* off by an exact power of ten (missing or wrong unit) -> ``xbrl_unit_fix`` with the filed scale in ``fix_scale``;
* a sign-only difference on a line whose sign convention varies (exceptional items, changes in inventories, and CF
  outflows such as purchase of fixed assets, dividends paid, repayment, taxes paid) -> ``xbrl_match``
  (``sign_convention``);
* outside tolerance otherwise -> verdict ``xbrl_contradicts``: the loader serves it ``unverified`` with the filed value in
  ``check_fields`` (the read is never overwritten; a mapping or period mistake must not destroy a right row).

Tolerance: 1%, or the printed rounding (half a unit of the last printed digit), whichever is larger.  Rows with no
basis are compared with both bases and match only when exactly one basis matches; an empty basis is never called
wrong.  A mismatch on a store line the store itself derived (``is_reported=0``) never contradicts: only a filed,
reported line may demote a read.

This is a CHECK layer: verdicts are written to ``<out>/<db stem>.jsonl`` (one JSON per checked row, keyed by the
source DB's ``observation_id``) and the source DB is opened read-only.  Re-running it after new reads or new XBRL is
always safe; the verdict file is rewritten whole.

CLI: ``python -m reality_engine.v2.xbrl_crosscheck --db D:/RealityEngine/hy4_out/obs_results_fy27.db``
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

STORE_GLOBS = ("C:/RealityEngine/tg_build/universe_fy27/c*/c*.db", "C:/RealityEngine/tg_build/full394/c*/c*.db")
OUT_DIR = Path("D:/RealityEngine/checks/xbrl")
TOLERANCE = 0.01

# hy4 measure -> fin_quarter_xbrl line_item (only lines the filed XBRL carries)
MEASURE_TO_XBRL = {
    "revenue_from_operations": "revenue_from_operations", "other_income": "other_income",
    "total_income": "total_income", "total_expenses": "total_expenses", "other_expenses": "other_expenses",
    "finance_cost": "finance_cost", "finance_costs": "finance_cost",
    "employee_benefits_expense": "employee_cost", "employee_cost": "employee_cost",
    "depreciation_and_amortisation_expense": "depreciation", "depreciation": "depreciation",
    "raw_material_cost": "cost_of_materials", "cost_of_materials_consumed": "cost_of_materials",
    "purchase_of_finished_goods": "purchases_of_stock_in_trade",
    "purchases_of_stock_in_trade": "purchases_of_stock_in_trade",
    "changes_in_inventories": "changes_in_inventories", "exceptional_items": "exceptional_items",
    "profit_before_exceptional_items_and_tax": "pbt_before_exceptional", "profit_before_tax": "pbt",
    "total_tax_expense": "tax", "pat": "pat", "total_comprehensive_income": "total_comprehensive_income",
    "interest_income": "interest_income", "net_interest_income": "net_interest_income",
}

SIGN_FREE = {"exceptional_items", "changes_in_inventories"}

# hy4 measure -> (fin_annual_line.statement, line_items) for the balance-sheet / cash-flow / half-year check.
# A tuple of line_items means either filed line may confirm the read (a cash-flow closing balance is a valid
# "cash and cash equivalents" figure for the as-at date).
ANNUAL_MEASURE_TO_LINES = {
    "cash_and_cash_equivalents": ("BS", ("cash_and_equivalents", "cash_flow_statement_cash")),
    "trade_receivables": ("BS", ("trade_receivables",)),
    "total_assets": ("BS", ("total_assets",)),
    "equity_share_capital": ("BS", ("equity_share_capital",)),
    "total_equity": ("BS", ("total_equity",)),
    "investments": ("BS", ("investments",)),
    "employee_benefits_expense": ("P&L", ("employee_cost",)), "employee_cost": ("P&L", ("employee_cost",)),
    "other_income": ("P&L", ("other_income",)), "other_expenses": ("P&L", ("other_expenses",)),
    "total_income": ("P&L", ("total_income",)), "revenue_from_operations": ("P&L", ("revenue_from_operations",)),
    "pat": ("P&L", ("pat",)), "total_tax_expense": ("P&L", ("tax",)),
    "finance_cost": ("P&L", ("finance_cost",)), "finance_costs": ("P&L", ("finance_cost",)),
    "depreciation_and_amortisation_expense": ("P&L", ("depreciation",)),
    "depreciation": ("P&L", ("depreciation",)),
    "eps_basic": ("P&L", ("eps_basic",)), "eps_diluted": ("P&L", ("eps_diluted",)),
    "cash_flow.operating": ("CF", ("cash_flow_from_operations",)),
    "cash_flow.investing": ("CF", ("cash_flow_from_investing",)),
    "cash_flow.financing": ("CF", ("cash_flow_from_financing",)),
    "capex": ("CF", ("capex",)),
    "dividends_paid": ("CF", ("dividends_paid",)), "income_tax_paid": ("CF", ("income_tax_paid",)),
    "proceeds_from_borrowings": ("CF", ("proceeds_from_borrowings",)),
    "repayment_of_borrowings": ("CF", ("repayment_of_borrowings",)),
    "purchase_of_ppe": ("CF", ("purchase_of_ppe",)),
}

# Cash-flow lines whose printed sign convention varies: |stored| == |filed| is a match
CF_SIGN_FREE = {"capex", "purchase_of_ppe", "purchase_of_intangibles", "dividends_paid", "income_tax_paid",
                "repayment_of_borrowings", "lease_payments"}

_TENS = (1e-7, 1e-6, 1e-5, 1e-3, 1e-2, 1e2, 1e3, 1e5, 1e6, 1e7)


def _power_of_ten(stored: float, filed: float, tol: float) -> float | None:
    """The factor k (a unit step) with stored * k == filed within tolerance, else None."""
    for k in _TENS:
        if stored and abs(stored * k - filed) <= max(tol, abs(filed) * TOLERANCE):
            return k
    return None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_D_M_Y = re.compile(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?[\s.\-/,]*" + _MON + r"[\s.\-/,']*(\d{2,4})\b", re.I)
_M_D_Y = re.compile(r"\b" + _MON + r"\s*(\d{1,2})(?!\d)(?:st|nd|rd|th)?[\s,]+(\d{2,4})\b", re.I)
_NUM = re.compile(r"\b(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{2,4})\b")
_QFY = re.compile(r"\bQ([1-4])\s*[\-']?\s*FY\s*'?(\d{2,4})\b", re.I)
_QUARTER_WORD = re.compile(r"\bquarter\b|\b3\s*months?\b|\bthree\s+months?\b", re.I)
_OTHER_DURATION = re.compile(r"\b(half|six\s+months?|6\s+months?|nine\s+months?|9\s+months?|year|annual|"
                             r"period\s+ended|ytd|year\s+to\s+date|as\s+at|as\s+on)\b", re.I)
_QEND = {1: (6, 30), 2: (9, 30), 3: (12, 31), 4: (3, 31)}


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if n < 100 else n


def _month_end(y: int, m: int) -> dt.date:
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def quarter_end(period: str) -> dt.date | None:
    """The quarter-end date of a period that names a quarter, else None (a half year, year or as-at never is)."""
    p = period or ""
    q = _QFY.search(p)
    if q:
        n, fy = int(q.group(1)), _year(q.group(2))
        m, d = _QEND[n]
        return dt.date(fy if n == 4 else fy - 1, m, d)
    if not _QUARTER_WORD.search(p) or _OTHER_DURATION.search(_QUARTER_WORD.sub("", p)):
        return None
    for rx, order in ((_D_M_Y, "dmy"), (_M_D_Y, "mdy")):
        m = rx.search(p)
        if m:
            if order == "dmy":
                day, mon, yr = int(m.group(1)), _MONTHS[m.group(2)[:3].lower()], _year(m.group(3))
            else:
                mon, day, yr = _MONTHS[m.group(1)[:3].lower()], int(m.group(2)), _year(m.group(3))
            try:
                return dt.date(yr, mon, day)
            except ValueError:
                return None
    m = _NUM.search(p)
    if m:
        day, mon, yr = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        if 1 <= mon <= 12:
            try:
                return dt.date(yr, mon, day)
            except ValueError:
                return _month_end(yr, mon)
    return None


_HALF_WORD = re.compile(r"\b(half[\s-]*year|h1|six\s+months?|6\s+months?)\b", re.I)
_YEAR_WORD = re.compile(r"\b(year|annual|fy|12\s+months?)\b", re.I)
_NINE_WORD = re.compile(r"\b(nine\s+months?|9\s+months?|9m|ytd|year\s+to\s+date)\b", re.I)
_FY_RANGE = re.compile(r"\b(20\d{2})\s*[-/]\s*(\d{2,4})\b")
_FY_ONLY = re.compile(r"\bFY\s*'?\s*(\d{2,4})\b", re.I)
_H_FY = re.compile(r"\bH([12])\s*[-']?\s*FY\s*'?(\d{2,4})\b", re.I)
_SPAN = {"Q": (70, 110), "H1": (140, 230), "FY": (300, 430)}


def _dates(period: str) -> list[dt.date]:
    """Every valid calendar date the text prints, in text order, deduplicated."""
    found: list[tuple[int, dt.date]] = []
    for rx, order in ((_D_M_Y, "dmy"), (_M_D_Y, "mdy")):
        for m in rx.finditer(period):
            try:
                if order == "dmy":
                    d = dt.date(_year(m.group(3)), _MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
                else:
                    d = dt.date(_year(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
            except ValueError:
                continue
            found.append((m.start(), d))
    for m in _NUM.finditer(period):
        day, mon, yr = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        if 1 <= mon <= 12 and 1900 <= yr <= 2100:
            try:
                found.append((m.start(), dt.date(yr, mon, day)))
            except ValueError:
                continue
    out: list[dt.date] = []
    for _, d in sorted(found):
        if d not in out:
            out.append(d)
    return out


def _fiscal_year_end(period: str) -> dt.date | None:
    """The 31 March an Indian fiscal-year label names (``2024-25``, ``2025-2026``, ``FY26``)."""
    m = _FY_RANGE.search(period)
    if m:
        y1, y2 = int(m.group(1)), _year(m.group(2))
        if y2 < y1:
            y2 += 100
        return dt.date(y2, 3, 31)
    m = _FY_ONLY.search(period)
    return dt.date(_year(m.group(1)), 3, 31) if m else None


def as_at_date(period: str) -> dt.date | None:
    """The as-at date a balance-sheet period names, else None (a duration or an ambiguous bare year never is)."""
    p = period or ""
    if not p or _NINE_WORD.search(p) or _HALF_WORD.search(p) or _QUARTER_WORD.search(p) or _QFY.search(p) \
            or _H_FY.search(p) or re.search(r"\b[QH][1-4]\b", p, re.I) or re.search(
            r"\b(year|annual|12\s+months?|months?|ytd|period\s+ended|year\s+to\s+date)\b", p, re.I):
        return None
    dates = _dates(p)
    if len(dates) == 1:
        return dates[0]
    return _fiscal_year_end(p) if not dates else None


def duration_end(period: str) -> tuple[str, dt.date] | None:
    """(period_type, end date) for a P&L/CF period that names its duration, else None.

    ``H1`` is a six-month duration (the store labels both halves ``H1``), ``FY`` a year, ``Q`` a quarter; a fiscal-year
    label (``2024-25``, ``FY26``) names ``FY``.  When two dates are printed the span must agree with the named
    duration, so a half-year sentence can never be compared with a quarter line.
    """
    p = period or ""
    if not p or _NINE_WORD.search(p):
        return None
    dates = _dates(p)
    h = _H_FY.search(p)
    q = _QFY.search(p)
    kind = None
    end = None
    if q:
        kind, end = "Q", quarter_end(p)
    elif h:
        kind = "H1"
        fy = _year(h.group(2))
        end = dt.date(fy - 1, 9, 30) if h.group(1) == "1" else dt.date(fy, 3, 31)
    elif _HALF_WORD.search(p):
        kind = "H1"
    elif _YEAR_WORD.search(p):
        kind = "FY"
    elif _QUARTER_WORD.search(p):
        kind = "Q"
    elif len(dates) == 2:
        span = (dates[-1] - dates[0]).days
        kind = next((k for k, (lo, hi) in _SPAN.items() if lo <= span <= hi), None)
    if kind is None or end is None:
        if dates:
            end = dates[-1]
        else:
            end = _fiscal_year_end(p)
        if kind is None and end is not None and (_FY_RANGE.search(p) or _FY_ONLY.search(p)):
            kind = "FY"
        if kind is None or end is None:
            return None
    if len(dates) == 2:
        lo, hi = _SPAN[kind]
        if not lo <= (dates[-1] - dates[0]).days <= hi:
            return None
    return kind, end


def half_year_end(period: str) -> dt.date | None:
    """The end date of a period that names a half year, else None."""
    d = duration_end(period)
    return d[1] if d and d[0] == "H1" else None


def _printed_tol(value_text: str, scale: float) -> float:
    """Half a unit of the last printed digit (Eagle 26 Nov: only this proves a read; 1% hides a misread digit)."""
    t = (value_text or "").replace(",", "")
    dec = re.search(r"\.(\d+)", t)
    unit = 10 ** -(len(dec.group(1))) if dec else 1.0
    return 0.5 * unit * (scale or 1.0) * 1.000001 + 1e-6


def _printed_agrees(val: float, filed: float, value_text: str, scale: float) -> bool:
    """The stored figure is the filed one at the printed precision: rounded (half a unit) or cut short
    (a press release's "Rs 330 crore" for 330.53) - never a different digit."""
    half = _printed_tol(value_text, scale)
    if abs(val - filed) <= half:
        return True
    same_sign = (val >= 0) == (filed >= 0)
    return same_sign and abs(val) < abs(filed) < abs(val) + 2 * half


def _tolerance(value_text: str, scale: float, filed: float) -> float:
    """1% of the filed value, or half a unit of the last printed digit, whichever is larger."""
    t = (value_text or "").replace(",", "")
    dec = re.search(r"\.(\d+)", t)
    unit = 10 ** -(len(dec.group(1))) if dec else 1.0
    return max(abs(filed) * TOLERANCE, 0.5 * unit * (scale or 1.0))


def store_filed() -> tuple[dict[str, dict[tuple, float]],
                           dict[str, dict[tuple, list[tuple[float, bool]]]]]:
    """Load both filed sources from every store in one pass.

    quarter: symbol -> {(line_item, period_end, basis): value in rupees} from ``fin_quarter_xbrl``;
    annual:  symbol -> {(line_item, period_end, basis, kind): [(value in rupees, is_reported)]} from
    ``fin_annual_line``, where kind is ``'stock'`` for a BS line (an as-at date) and the ``period_type``
    (``H1``/``FY``/``Q``) for a P&L/CF duration.
    """
    quarters: dict[str, dict[tuple, float]] = defaultdict(dict)
    annual: dict[str, dict[tuple, list[tuple[float, bool]]]] = defaultdict(dict)
    for pattern in STORE_GLOBS:
        for db in sorted(glob.glob(pattern)):
            if os.path.basename(os.path.dirname(db)) + ".db" != os.path.basename(db):
                continue
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
            except sqlite3.Error:
                continue
            try:
                rows = con.execute("SELECT symbol, line_item, period_start, period_end, basis, value, scale "
                                   "FROM fin_quarter_xbrl WHERE value IS NOT NULL").fetchall()
            except sqlite3.Error:
                rows = []
            for sym, li, ps, pe, basis, val, scale in rows:
                try:
                    start, end = dt.date.fromisoformat(ps), dt.date.fromisoformat(pe)
                except (TypeError, ValueError):
                    continue
                if not 80 <= (end - start).days <= 100:        # a quarter only
                    continue
                quarters[sym][(li, end, (basis or "").lower())] = float(val) * float(scale or 1.0)
            try:
                arows = con.execute("SELECT symbol, statement, line_item, period_end, basis, value, scale, "
                                    "period_type, is_reported FROM fin_annual_line WHERE value IS NOT NULL").fetchall()
            except sqlite3.Error:
                arows = []
            for sym, stmt, li, pe, basis, val, scale, ptype, reported in arows:
                try:
                    end = dt.date.fromisoformat(pe)
                except (TypeError, ValueError):
                    continue
                if stmt == "BS":
                    kind = "stock"
                elif stmt in ("P&L", "CF") and ptype in ("H1", "FY", "Q"):
                    kind = ptype
                else:
                    continue
                b = (basis or "").lower()
                b = "" if b == "not_stated" else b
                key = (li, end, b, kind)
                value = float(val) * float(scale or 1.0)
                slot = annual[sym].setdefault(key, [])
                for i, (v0, r0) in enumerate(slot):
                    if abs(v0 - value) <= max(1e-6, abs(value) * 1e-9):
                        slot[i] = (v0, r0 or bool(reported))
                        break
                else:
                    slot.append((value, bool(reported)))
            con.close()
    for per_symbol in annual.values():
        for slot in per_symbol.values():
            slot.sort()
    return quarters, annual


def _compare(val: float, value_text: str, scale: float, li: str, stmt: str, filed: dict[str, list[tuple[float, bool]]],
             basis: str, source: str, end: dt.date, kind: str) -> tuple[dict | None, str | None]:
    """One source's verdict for one row: (verdict dict or None, stat name or None)."""
    if not filed:
        return None, "no_filed"
    base = {"line_item": li, "statement": stmt, "source": source, "period_end": end.isoformat(), "kind": kind}
    sign_free = li in SIGN_FREE or (stmt == "CF" and li in CF_SIGN_FREE)
    hits: dict[str, list[float]] = {}
    for b, vals in filed.items():
        matched = [v for v, _ in vals if abs(val - v) <= _tolerance(value_text, scale, v)]
        if matched:
            hits[b] = matched
    hit_bases = sorted(hits)
    if len(hit_bases) == 1 or (basis and hit_bases):
        b = hit_bases[0]
        f = min(hits[b], key=lambda v: abs(val - v))
        if not _printed_agrees(val, f, value_text, scale):    # within 1% but not the printed figure: a misread?
            return (base | {"verdict": "xbrl_near", "basis": b, "filed": f, "_stat": "near",
                            "evidence": f"XBRL {li} {end} {b} {kind} = {f:,.0f}; stored {val:,.0f} (within 1%, "
                                        f"not to the printed digit)"}), "near"
        return (base | {"verdict": "xbrl_match", "basis": b, "filed": f, "_stat": "match",
                        "evidence": f"XBRL {li} {end} {b} {kind} = {f:,.0f}"}), "match"
    if hit_bases:
        return None, "ambiguous_basis"
    if sign_free:
        flips = {b: [v for v, _ in vals if abs(val + v) <= _tolerance(value_text, scale, v)]
                 for b, vals in filed.items()}
        flip_bases = sorted(b for b, vs in flips.items() if vs)
        if len(flip_bases) == 1 or (basis and flip_bases):
            b = flip_bases[0]
            f = min(flips[b], key=lambda v: abs(val + v))
            if not _printed_agrees(val, -f, value_text, scale):
                return (base | {"verdict": "xbrl_near", "basis": b, "filed": f, "_stat": "near",
                                "evidence": f"XBRL {li} {end} {b} {kind} = {f:,.0f}; stored {val:,.0f} "
                                            f"(sign convention, within 1%, not to the printed digit)"}), "near"
            return (base | {"verdict": "xbrl_match", "basis": b, "filed": f, "_stat": "match_sign_convention",
                            "evidence": f"XBRL {li} {end} {b} {kind} = {f:,.0f} (sign_convention)"}), "match_sign_convention"
    if not basis:
        return None, "no_basis_mismatch"
    reported = [(b, v) for b, vals in filed.items() for v, rep in vals if rep]
    if not reported:
        return None, "derived_only"
    if sign_free:
        b, f = min(reported, key=lambda bv: abs(abs(val) - abs(bv[1])))
    else:
        b, f = min(reported, key=lambda bv: abs(val - bv[1]))
    tol = _tolerance(value_text, scale, f)
    to_u, from_u = (abs(val), abs(f)) if sign_free else (val, f)
    fix = _power_of_ten(to_u, from_u, tol)
    if fix is not None and (basis or len(filed) == 1):
        return (base | {"verdict": "xbrl_unit_fix", "basis": b, "filed": f, "_stat": "unit_fix",
                        "fix_scale": float(scale or 1.0) * fix,
                        "evidence": f"XBRL {li} {end} {b} {kind} = {f:,.0f}; stored x{fix:g} off"}), "unit_fix"
    return (base | {"verdict": "xbrl_contradicts", "basis": b, "filed": f, "_stat": "contradicts",
                    "evidence": f"XBRL {li} {end} {b} {kind} = {f:,.0f}; stored {val:,.0f}"}), "contradicts"


_VERDICT_RANK = {"xbrl_match": 0, "xbrl_near": 1, "xbrl_unit_fix": 2, "xbrl_contradicts": 3}


def check_db(db: str | Path, xbrl: dict[str, dict[tuple, float]] | None = None,
             annual: dict[str, dict[tuple, list[tuple[float, bool]]]] | None = None) -> tuple[list[dict], Counter]:
    """Verdicts for one hy4 DB, merged across both filed sources (a match in either wins)."""
    if xbrl is None and annual is None:
        xbrl, annual = store_filed()
    xbrl = xbrl or {}
    annual = annual or {}
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    verdicts: list[dict] = []
    stats: Counter = Counter()
    checked_at = dt.datetime.now().isoformat(timespec="seconds")
    for r in con.execute("SELECT observation_id, symbol, measure, value, value_text, scale, period, basis, "
                         "entity_scope, status, segment, geography, product FROM observation "
                         "WHERE record_type='number' AND value IS NOT NULL AND status != 'quarantined'"):
        measure = r["measure"] or ""
        li_q = MEASURE_TO_XBRL.get(measure)
        mapped = ANNUAL_MEASURE_TO_LINES.get(measure)
        if not li_q and not mapped:
            continue
        if (r["entity_scope"] or "company") not in ("company", ""):
            stats["skip_scope"] += 1
            continue
        if r["segment"] or r["geography"] or r["product"]:
            stats["skip_segment"] += 1          # a segment/geography/product row is never the company's total
            continue
        period = r["period"] or ""
        basis = (r["basis"] or "").lower()
        bases = [basis] if basis else ["standalone", "consolidated", ""]
        val = float(r["value"]) * float(r["scale"] or 1.0)
        scale = r["scale"] or 1.0
        q_end = quarter_end(period) if li_q else None
        a_hit = None
        if annual and mapped:
            stmt, line_items = mapped
            if stmt == "BS":
                a_end = as_at_date(period)
                a_hit = (stmt, line_items, a_end, "stock") if a_end else None
            else:
                d = duration_end(period)
                a_hit = (stmt, line_items, d[1], d[0]) if d else None
        if q_end is None and a_hit is None:
            stats["skip_period"] += 1
            continue
        parts: list[dict] = []
        notes: list[str] = []
        filed_any = False
        if q_end is not None and li_q:
            per_symbol = xbrl.get(r["symbol"]) or {}
            filed_q = {b: [(per_symbol[(li_q, q_end, b)], True)] for b in bases
                       if (li_q, q_end, b) in per_symbol}
            filed_any |= bool(filed_q)
            verdict, note = _compare(val, r["value_text"], scale, li_q, "P&L", filed_q, basis, "quarter", q_end,
                                     "quarter")
            if verdict:
                parts.append(verdict)
            elif note:
                notes.append(note)
        if a_hit is not None:
            stmt, line_items, a_end, a_kind = a_hit
            per_symbol = annual.get(r["symbol"]) or {}
            filed_a = {b: [entry for li in line_items
                           for entry in per_symbol.get((li, a_end, b, a_kind), [])]
                       for b in bases if any((li, a_end, b, a_kind) in per_symbol for li in line_items)}
            filed_any |= bool(filed_a)
            verdict, note = _compare(val, r["value_text"], scale, "+".join(line_items), stmt, filed_a, basis,
                                     "annual", a_end, a_kind)
            if verdict:
                parts.append(verdict)
            elif note:
                notes.append(note)
        if not parts:
            if filed_any:
                for note in notes:
                    if note != "no_filed":
                        stats[note] += 1
            else:
                stats["no_xbrl_period"] += 1
            continue
        parts.sort(key=lambda p: _VERDICT_RANK[p["verdict"]])
        win = dict(parts[0])
        if len(parts) > 1:
            win["also"] = [{"source": p["source"], "verdict": p["verdict"]} for p in parts[1:]]
            stats["two_sources"] += 1
        stat = win.pop("_stat")
        v = {"id": r["observation_id"], "symbol": r["symbol"], "measure": r["measure"], "stored": val,
             "status_before": r["status"], "checker": "xbrl_crosscheck", "checked_at": checked_at} | win
        verdicts.append(v)
        stats[stat] += 1
        stats[f"{v['verdict']}|{v['statement']}"] += 1
    con.close()
    for v in verdicts:
        stats[f"{v['verdict']}|{v['status_before']}"] += 1
    return verdicts, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--db", required=True, help="hy4 observation DB (opened read-only)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args(argv)
    verdicts, stats = check_db(args.db)
    out = Path(args.out_dir) / f"{Path(args.db).stem}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for v in verdicts:
            fh.write(json.dumps(v, ensure_ascii=False) + "\n")
    tmp.replace(out)
    print(json.dumps(dict(stats), indent=1))
    print(f"verdicts: {out} ({len(verdicts)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
