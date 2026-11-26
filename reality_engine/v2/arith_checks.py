"""Arithmetic check layer for hy4 stored number rows (T-242, 26 Nov 2026, Wolf).

The hy4 stores hold one row per printed number.  A number can be read, scaled or stored wrongly and still look
plausible alone; several of them on the same page make the mistake visible.  This module checks four kinds of
impossible arithmetic entirely in script (no model calls):

* ``arith_sum_mismatch`` -- a row flagged ``is_total=1`` in a ``group_path`` whose printed children (the rows of
  that group in the same document page, period and basis, at the deepest ``group_path`` level) do not sum to it
  beyond 1% or printed rounding.  The total AND each child are flagged: the page's arithmetic cannot hold.
  When exactly one child explains the gap by a power of ten (AVI employee benefits 350 stored for 3.50), only
  that child is flagged ``arith_unit_suspect`` with ``fix_scale`` and ``fixed_value``.
* ``arith_subset_as_total`` -- a row stored under a canonical TOTAL measure (``total_*``, raw material cost,
  capital work-in-progress, borrowings, revenue from operations) while a larger ``is_total`` row with the same
  measure, page, period and basis sits beside it and the row is one of its components (ARCHIDPLY 'Chemicals in
  Kgs' 5,499.65 against the 19,070.11 total; ABB 'Nelamangala' 17.07 against the 94.77 CWIP total).
* ``arith_sign`` -- the label says loss while the row is stored positive under a profit measure ('total net loss
  after tax' stored +1,207.22).
* ``arith_jump`` -- the same symbol, measure, basis and period kind jumps 90x-110x (or 1/90-1/110x) between
  adjacent periods and the outlier disagrees with the rest of the series (a unit error, not growth).

This is a CHECK layer, like ``reality_engine/v2/xbrl_crosscheck.py``: verdicts are written to
``<out>/<db stem>.jsonl`` (one JSON per flagged row, keyed by the source DB's ``observation_id``) and the source
DB is opened read-only.  The loader applies the verdicts later; the stored row is never changed here.  An empty
verdict file is the right answer when nothing is wrong; every rule skips the ambiguous cases (duplicate printed
labels from a two-column table, nested totals, mixed units) rather than guess.

CLI: ``python -m reality_engine.v2.arith_checks --db D:/RealityEngine/hy4_out/obs_results_fy27.db
--out-dir .tmp/checks_arith``
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from reality_engine.v2.xbrl_crosscheck import _power_of_ten, quarter_end

OUT_DIR = Path("D:/RealityEngine/checks/arith")
TOLERANCE = 0.01
TOTAL_MEASURES = frozenset({
    "raw_material_cost", "capital_work_in_progress", "borrowings", "revenue_from_operations",
})
PROFIT_MEASURES = frozenset({
    "pat", "profit", "profit_after_tax", "profit_before_tax", "pbt", "net_profit", "profit_for_the_period",
    "profit_before_exceptional_items_and_tax", "total_comprehensive_income", "ebitda", "ebit",
})
TOTAL_LABEL = re.compile(r"\b(total|sub[\s-]?total|grand\s+total)\b", re.I)
LOSS_LABEL = re.compile(r"^\W*(?:\d+\s*[.)]?\s*)?(?:total\s+)?(?:net\s+)?(?:other\s+)?(?:comprehensive\s+)?loss\b",
                        re.I)
LINE_WORDS = re.compile(r"total|revenue|income|expense|tax|profit|loss|equity|liabilit|asset|borrow|worth|capital|"
                        r"sales|share|cash|balance|depreciation|finance|dues", re.I)
CASH_FLOW_GROUPS = ("cash flow", "cash flows", "working capital", "operating activities", "investing activities",
                    "financing activities")
# Only a primary-statement section is a partition of its total; notes, disclosures, segment and exposure tables are not.
STATEMENT_GROUPS = frozenset({
    "expenses", "expense", "operating expenses", "other expenses", "income", "tax expense", "tax expenses",
    "other comprehensive income", "revenue from operations", "assets", "equity and liabilities", "equity",
    "liabilities", "current assets", "non-current assets", "current liabilities", "non-current liabilities",
    "shareholders funds", "capital work-in-progress", "capital work in progress",
})
SUBSET_RATIO = 1.5
SUBSET_MAX_ROWS = 25
JUMP_LOW, JUMP_HIGH = 90.0, 110.0
MIN_JUMP_RUPEES = 100_000.0
_SPACING = {"q": (60, 100), "h": (150, 210), "y": (330, 400), "i": (330, 400), "d": (330, 400)}
_DIMENSIONS = ("segment", "customer")

_COLS = (
    "observation_id", "symbol", "doc_key", "page", "series_id", "measure", "printed_label", "value",
    "value_text", "unit", "unit_family", "scale", "is_total", "period", "basis", "entity_scope",
    "segment", "product", "geography", "plant", "customer", "group_path", "status",
)


# --------------------------------------------------------------------------- small helpers

def _text(row: dict, key: str) -> str:
    return str(row.get(key) or "")


def _rupees(row: dict) -> float:
    """The stored value in rupees (value is in the row's printed unit; scale converts it)."""
    return float(row["value"]) * float(row.get("scale") or 1.0)


def _rounding(row: dict) -> float:
    """Half a unit of the last printed digit, in rupees (the smallest change the page could print)."""
    dec = re.search(r"\.(\d+)", _text(row, "value_text").replace(",", ""))
    unit = 10.0 ** -(len(dec.group(1))) if dec else 1.0
    return 0.5 * unit * float(row.get("scale") or 1.0)


def _key(row: dict) -> tuple:
    return (_text(row, "doc_key"), row.get("page"), _text(row, "series_id"), _text(row, "period"),
            _text(row, "basis").lower(), _text(row, "entity_scope"))


def _page_key(row: dict) -> tuple:
    """The ticket's subset key: one printed page, period and basis (a page may hold several table blocks)."""
    return (_text(row, "doc_key"), row.get("page"), _text(row, "period"), _text(row, "basis").lower(),
            _text(row, "entity_scope"))


def _path(row: dict) -> str:
    return _text(row, "group_path").strip()


def _in_group(child_path: str, group: str) -> bool:
    return child_path == group or child_path.startswith(group + " > ")


def _is_total_measure(measure: str) -> bool:
    return measure in TOTAL_MEASURES or measure.startswith("total_")


def _dimensioned(row: dict) -> bool:
    return any(_text(row, dim) for dim in _DIMENSIONS)


def _fmt(value: float) -> str:
    return f"{value:,.2f}"


def _verdict(row: dict, verdict: str, rule: str, evidence: str, **extra: object) -> dict:
    out = {
        "id": row["observation_id"], "verdict": verdict, "rule": rule, "evidence": evidence,
        "checker": "arith_checks", "symbol": row.get("symbol"), "measure": row.get("measure"),
        "printed_label": row.get("printed_label"), "period": row.get("period"), "basis": row.get("basis"),
        "page": row.get("page"), "doc_key": row.get("doc_key"), "stored": _rupees(row),
    }
    out.update(extra)
    return out


# --------------------------------------------------------------------------- rule: sum_mismatch

def _child_ok(child: dict, total: dict) -> bool:
    """Only a number that can plausibly be one component of the total's group is summed."""
    measure = _text(child, "measure")
    total_measure = _text(total, "measure")
    if measure.startswith("cash_flow."):
        return False                    # a cash-flow subtotal never belongs in a P&L/balance-sheet group
    if measure in PROFIT_MEASURES and total_measure not in PROFIT_MEASURES:
        return False                    # a profit line is not a component of expenses/assets/income
    low_measure, low_total = measure.lower(), total_measure.lower()
    if ("expense" in low_total or "cost" in low_total) and ("income" in low_measure or "revenue" in low_measure):
        return False
    if ("income" in low_total or "revenue" in low_total) and ("expense" in low_measure or "cost" in low_measure):
        return False
    return True


def _collect(prefix: str, candidates: list[dict]) -> list[dict] | None:
    """Walk one group branch: a single printed subtotal stands for its branch; plain rows sum; mixed trees skip."""
    here = [c for c in candidates if _path(c) == prefix]
    totals_here = [c for c in here if c["is_total"]]
    if len(totals_here) == 1:
        return totals_here                 # this level's printed subtotal covers its branch whole
    if len(totals_here) > 1:
        if len(here) == len(totals_here):
            return totals_here             # sibling subtotals (e.g. non-current + current) add up
        return None
    deeper = [c for c in candidates if _path(c).startswith(prefix + " > ")]
    if here and deeper:
        return None                        # plain rows beside a deeper breakdown: cannot tell what to sum
    if not deeper:
        return here
    segments = sorted({_path(c)[len(prefix) + 3:].split(" > ")[0] for c in deeper})
    out: list[dict] = []
    for segment in segments:
        got = _collect(prefix + " > " + segment, candidates)
        if got is None:
            return None
        out.extend(got)
    return out


def _section_conflict(total: dict, children: list[dict]) -> bool:
    """A total of one statement section must not be checked against rows of another section."""
    measure = _text(total, "measure").lower()
    if "equity_and_liabilities" in measure:
        return False
    group = _path(total)
    relative = [_path(c)[len(group) + 3:] if _path(c).startswith(group + " > ") else _path(c) for c in children]
    joined = " ".join(relative).lower()
    if "total_assets" in measure or measure == "assets":
        return "liabilit" in joined or "equity" in joined
    if "liabilit" in measure:
        return "asset" in joined or "shareholders" in joined or "equity" in joined
    if "equity" in measure:
        return "liabilit" in joined or "asset" in joined
    low_relative = [item.lower() for item in relative]
    if "non_financial" in measure and any("financial" in item and "non-financial" not in item
                                          for item in low_relative):
        return True
    if "financial" in measure and "non_financial" not in measure and any("non-financial" in item
                                                                        for item in low_relative):
        return True
    return False


def _statement_group(group: str) -> bool:
    """True for a primary-statement section (Expenses, Income, Assets ...); a note/disclosure group is not summed."""
    leaf = group.split(" > ")[-1].lower()
    leaf = re.sub(r"^[0-9ivx.\s()\-]+", "", leaf)
    leaf = re.sub(r"\s+", " ", leaf).strip(" .:-")
    return leaf in STATEMENT_GROUPS


def _leaves(total: dict, candidates: list[dict]) -> list[dict] | None:
    """The rows a printed total should equal (subtotals whole, plain components summed); None when ambiguous."""
    group = _path(total)
    low_group = group.lower()
    if not _statement_group(group):
        return None                     # notes, disclosures and segment/exposure tables are not partitions
    if _text(total, "measure").startswith("cash_flow.") or _text(total, "measure") == "changes_in_working_capital":
        return None                     # a cash-flow statement is a sequence of steps, not a partition of a total
    if any(word in low_group for word in CASH_FLOW_GROUPS):
        return None
    candidates = [c for c in candidates if _child_ok(c, total)]
    leaves = _collect(group, candidates)
    if leaves is None or len(leaves) < 2:
        return None
    if any("cash flow" in _path(c).lower() for c in leaves):
        return None
    if _section_conflict(total, leaves):
        return None
    labels = [_text(c, "printed_label").lower().strip() for c in leaves]
    if len(set(labels)) != len(labels):
        return None                     # one label twice: a two-column table read as one column
    if any(_text(c, "unit_family") not in ("money", "") for c in leaves):
        return None
    return leaves


def sum_verdicts(rows: list[dict], stats: Counter) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[_key(row)].append(row)
    out: list[dict] = []
    for page_rows in groups.values():
        totals: dict[str, list[dict]] = defaultdict(list)
        for row in page_rows:
            if row["is_total"] and _path(row):
                totals[_path(row)].append(row)
        for group, same in totals.items():
            if len(same) != 1:           # two totals in one group (two columns) tell us nothing
                stats["sum_skip_multi_total"] += 1
                continue
            total = same[0]
            candidates = [r for r in page_rows if r is not total and _path(r) and _in_group(_path(r), group)]
            children = _leaves(total, candidates)
            if children is None:
                stats["sum_skip_ambiguous"] += 1
                continue
            before = [c for c in children if c["observation_id"] < total["observation_id"]]
            after = [c for c in children if c["observation_id"] > total["observation_id"]]
            if before and after:
                stats["sum_skip_two_sides"] += 1
                continue                # rows above and below the total: a sequence, not one column's parts
            children = before or after
            if len(children) < 2:
                stats["sum_skip_ambiguous"] += 1
                continue
            total_v = _rupees(total)
            values = [_rupees(c) for c in children]
            summed = sum(values)
            tol = max(abs(total_v) * TOLERANCE, _rounding(total) + sum(_rounding(c) for c in children))
            if abs(summed - total_v) <= tol:
                stats["sum_ok"] += 1
                continue
            fixes = []
            sign_fixes = []
            for child, value in zip(children, values):
                need = total_v - (summed - value)
                fix = _power_of_ten(value, need, _rounding(total) + _rounding(child) + 1e-9)
                if fix is not None:
                    fixes.append((child, value, fix))
                child_text = _text(child, "value_text").strip()
                child_negative = child_text.startswith("-") or (child_text[:1] in "({" and child_text[-1:] in ")}")
                if value > 0 and child_negative and abs(total_v - (summed - 2 * value)) <= tol:
                    sign_fixes.append((child, value))
            if len(fixes) == 1:
                child, value, fix = fixes[0]
                fixed = value * fix
                if total_v and abs(fixed) < abs(total_v) * 5e-4:
                    stats["sum_skip_vanishing_fix"] += 1
                    continue                # a fix that makes the line 0.00% of the total is a duplicated subtotal
                evidence = (f"only {child.get('printed_label') or child.get('measure')} explains the gap: "
                            f"stored {_fmt(value)} should be {_fmt(fixed)} (x{fix:g}) to make the group sum to "
                            f"{_fmt(total_v)} {total.get('measure')} {_text(total, 'period')}")
                stats["unit_suspect"] += 1
                out.append(_verdict(child, "arith_unit_suspect", "sum_mismatch", evidence,
                                    fix_scale=float(child.get("scale") or 1.0) * fix, fixed_value=fixed,
                                    total_id=total["observation_id"]))
                continue
            if len(sign_fixes) == 1:
                child, value = sign_fixes[0]
                stats["sign_fix"] += 1
                out.append(_verdict(child, "arith_sign", "sum_mismatch",
                                    f"only {child.get('printed_label') or child.get('measure')} explains the gap: "
                                    f"stored {_fmt(value)} is the sign of {-value:,.2f} in the group that sums to "
                                    f"{_fmt(total_v)} {total.get('measure')} {_text(total, 'period')}",
                                    total_id=total["observation_id"]))
                continue
            shown = ", ".join(f"{_text(c, 'printed_label') or _text(c, 'measure')}={_fmt(v)}"
                              for c, v in zip(children, values))
            evidence = (f"{_fmt(total_v)} {total.get('measure')} {_text(total, 'period')} != children sum "
                        f"{_fmt(summed)}: {shown}")
            stats["sum_mismatch_total"] += 1
            out.append(_verdict(total, "arith_sum_mismatch", "sum_mismatch", evidence,
                                children=[c["observation_id"] for c in children], children_sum=summed))
            for child, value in zip(children, values):
                stats["sum_mismatch_child"] += 1
                out.append(_verdict(child, "arith_sum_mismatch", "sum_mismatch",
                                    f"component of {_fmt(total_v)} total that sums to {_fmt(summed)}: "
                                    f"{_text(child, 'printed_label')}={_fmt(value)}",
                                    total_id=total["observation_id"]))
    return out


# --------------------------------------------------------------------------- rule: subset_as_total

def subset_verdicts(rows: list[dict], stats: Counter) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if _is_total_measure(_text(row, "measure")) and not _dimensioned(row) and float(row["value"] or 0):
            groups[_page_key(row)].append(row)
    out: list[dict] = []
    for same_page in groups.values():
        by_measure: dict[str, list[dict]] = defaultdict(list)
        for row in same_page:
            by_measure[_text(row, "measure")].append(row)
        for measure, series in by_measure.items():
            if len(series) < 2:
                continue
            series.sort(key=lambda r: r["observation_id"])
            for i, row in enumerate(series):
                label = _text(row, "printed_label").strip()
                if not label or re.match(r"\s*\(?\s*tot", label, re.I) or TOTAL_LABEL.search(label) \
                        or LINE_WORDS.search(label) or re.search(r"\b(limited|ltd|pvt|private)\b", label, re.I):
                    continue                # a row named like a statement line or a company is a line of its own table
                row_v = abs(_rupees(row))
                best: tuple[int, dict] | None = None
                for j, other in enumerate(series):
                    if i == j or not other["is_total"]:
                        continue
                    if abs(_rupees(other)) <= row_v * SUBSET_RATIO:
                        continue
                    if _text(other, "printed_label").strip().lower() == label.lower():
                        continue            # two rows of one label are two columns, not a total and its part
                    other_path, row_path = _path(other), _path(row)
                    if other_path and not _in_group(row_path, other_path):
                        continue
                    if not other_path and row_path:
                        continue
                    distance = abs(j - i)
                    if distance > SUBSET_MAX_ROWS:
                        continue
                    if best is None or distance < best[0]:
                        best = (distance, other)
                if best is None:
                    continue
                total = best[1]
                total_v = abs(_rupees(total))
                evidence = (f"{_text(row, 'printed_label') or measure} {_fmt(row_v)} is a component of the "
                            f"{_fmt(total_v)} {measure} total on the same page/period ({_text(row, 'period')})")
                stats["subset_as_total"] += 1
                out.append(_verdict(row, "arith_subset_as_total", "subset_as_total", evidence,
                                    total_id=total["observation_id"], total_value=total_v))
    return out


# --------------------------------------------------------------------------- rule: sign

def sign_verdicts(rows: list[dict], stats: Counter) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        value = float(row["value"] or 0)
        text = _text(row, "value_text").strip()
        printed_negative = text.startswith("-") or (text[:1] in "({" and text[-1:] in ")}")
        if printed_negative and value > 0 and _text(row, "unit_family") in ("money", ""):
            stats["sign"] += 1
            out.append(_verdict(row, "arith_sign", "sign",
                                f"value_text {text!r} prints a negative but value stored positive {_fmt(value)}"))
            continue
        label = _text(row, "printed_label") or _text(row, "measure")
        if _text(row, "measure") not in PROFIT_MEASURES or _text(row, "unit_family") not in ("money", ""):
            continue
        if "profit" in label.lower() or re.search(r"loss\s*\)?\s*[/&]\s*\(?\s*(profit|income|gain)", label, re.I):
            continue                    # "(loss)/profit" or "loss/income" is a two-way label, not a loss label
        if not LOSS_LABEL.search(label):
            continue
        if value <= 0:
            continue
        stats["sign"] += 1
        out.append(_verdict(row, "arith_sign", "sign",
                            f"label says loss while {_text(row, 'measure')} is stored positive {_fmt(_rupees(row))}"))
    return out


# --------------------------------------------------------------------------- rule: jump

_DATE_NUM = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
_DAY_MON_YEAR = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?[\s.\-/]+" + _MON + r"[a-z]*[\s.\-/,'()]+(\d{2,4})", re.I)
_MON_DAY_YEAR = re.compile(_MON + r"[a-z]*\.?[\s.\-/]+(\d{1,2})(?:st|nd|rd|th)?[,\s]+(\d{2,4})", re.I)
_MON_YEAR = re.compile(_MON + r"[a-z]*[\s.\-/,'()]+(\d{2,4})", re.I)


def _year(text: str) -> int:
    n = int(text)
    return n + 2000 if n < 100 else n


def _fallback_date(period: str) -> tuple[int, int, int] | None:
    """A period end from common date spellings ("31-Mar-26", "March 31, 2026", "31.03.2026", "March 2026")."""
    m = _DATE_NUM.search(period)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), _year(m.group(3))
    else:
        m = _DAY_MON_YEAR.search(period)
        if m:
            day, month, year = int(m.group(1)), _MONTHS[m.group(2)[:3].lower()], _year(m.group(3))
        else:
            m = _MON_DAY_YEAR.search(period)
            if m:
                month, day, year = _MONTHS[m.group(1)[:3].lower()], int(m.group(2)), _year(m.group(3))
            else:
                m = _MON_YEAR.search(period)
                if not m:
                    return None
                month, year = _MONTHS[m.group(1)[:3].lower()], _year(m.group(2))
                if not 1 <= month <= 12:
                    return None
                return year, month, calendar.monthrange(year, month)[1]
    if 1 <= month <= 12 and 1 <= day <= 31:
        return year, month, day
    return None


def period_kind(period: str) -> str | None:
    """q (quarter), h (half), y (year), i (instant), d (a bare date: compared as an annual column only)."""
    p = period or ""
    if quarter_end(p) is not None:
        return "q"
    low = p.lower()
    if "half" in low or "six months" in low:
        return "h"
    if "year" in low or "annual" in low:
        return "y"
    if "as at" in low or "as on" in low:
        return "i"
    return "d" if _fallback_date(p) is not None else None


def _period_end(period: str) -> tuple[int, int, int] | None:
    q = quarter_end(period or "")
    return (q.year, q.month, q.day) if q else _fallback_date(period or "")


def jump_verdicts(rows: list[dict], stats: Counter) -> list[dict]:
    series_map: dict[tuple, dict[tuple[int, int, int], list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if _text(row, "unit_family") not in ("money", ""):
            continue
        kind = period_kind(_text(row, "period"))
        end = _period_end(_text(row, "period"))
        if kind is None or end is None:
            stats["jump_skip_period"] += 1
            continue
        key = (_text(row, "symbol"), _text(row, "measure"), _text(row, "basis").lower(),
               _text(row, "entity_scope"), _text(row, "unit_family"), kind)
        series_map[key][end].append(row)
    out: list[dict] = []
    for key, by_end in series_map.items():
        points: list[tuple[tuple[int, int, int], float, dict]] = []
        for end, same_end in by_end.items():
            values = {round(_rupees(r), 2) for r in same_end}
            if len(values) != 1:          # a restatement or two columns: the period has no single value
                continue
            points.append((end, values.pop(), same_end[0]))
        points.sort()
        if len(points) < 3:
            stats["jump_skip_short_series"] += 1
            continue
        low, high = _SPACING[key[5]]
        for (end_a, value_a, row_a), (end_b, value_b, row_b) in zip(points, points[1:]):
            days = (dt.date(*end_b) - dt.date(*end_a)).days
            if not low <= days <= high:
                continue
            size_a, size_b = abs(value_a), abs(value_b)
            if min(size_a, size_b) == 0:
                continue
            ratio = max(size_a, size_b) / min(size_a, size_b)
            if not JUMP_LOW <= ratio <= JUMP_HIGH:
                continue
            others = [abs(v) for end, v, _ in points if end not in (end_a, end_b)]
            if not others:
                stats["jump_skip_ambiguous_pair"] += 1
                continue
            median = statistics.median(others)
            if median == 0:
                continue

            def distance(value: float) -> float:
                return max(abs(value), median) / min(abs(value), median)

            distance_a, distance_b = distance(value_a), distance(value_b)
            if distance_a == distance_b:
                stats["jump_skip_ambiguous_pair"] += 1
                continue
            if distance_a > distance_b:
                outlier, outlier_ratio, row = value_a, distance_a, row_a
            else:
                outlier, outlier_ratio, row = value_b, distance_b, row_b
            if outlier_ratio < JUMP_LOW or abs(outlier) < MIN_JUMP_RUPEES or median < MIN_JUMP_RUPEES:
                continue
            stats["jump"] += 1
            out.append(_verdict(row, "arith_jump", "jump",
                                f"{key[1]} jumps x{ratio:g} against the adjacent period and x{outlier_ratio:g} "
                                f"against the series median {_fmt(median)}; stored {_fmt(abs(outlier))}"))
    return out


# --------------------------------------------------------------------------- entry points

def check_rows(rows: list[dict]) -> tuple[list[dict], Counter]:
    """Run every rule over rows already loaded from an observation table (the unit-testable entry point)."""
    stats: Counter = Counter()
    stats["rows"] = len(rows)
    verdicts = sum_verdicts(rows, stats) + subset_verdicts(rows, stats) + sign_verdicts(rows, stats) \
        + jump_verdicts(rows, stats)
    return verdicts, stats


def check_db(db: str | Path) -> tuple[list[dict], Counter]:
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True, timeout=300)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        f"SELECT {', '.join(_COLS)} FROM observation "
        "WHERE record_type='number' AND value IS NOT NULL AND status != 'quarantined'")]
    con.close()
    return check_rows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "arithmetic checks").split("\n")[0])
    ap.add_argument("--db", required=True, help="hy4 observation DB (opened read-only)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args(argv)
    verdicts, stats = check_db(args.db)
    out = Path(args.out_dir) / f"{Path(args.db).stem}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for verdict in verdicts:
            fh.write(json.dumps(verdict, ensure_ascii=False) + "\n")
    tmp.replace(out)
    print(json.dumps({k: v for k, v in sorted(stats.items())}, indent=1))
    print(f"verdicts: {out} ({len(verdicts)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
