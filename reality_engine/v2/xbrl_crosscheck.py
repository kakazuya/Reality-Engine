"""Cross-check hy4 results rows against the exchange's filed XBRL (T-242, Shivam 26 Nov 2026, Wolf).

The store's ``fin_quarter_xbrl`` holds the filed quarterly P&L lines (value in rupees, period_start/period_end,
basis).  A results row (``record_type='number'``, a quarter period, the company's own scope) whose measure maps to an
XBRL line is compared at the same period end and basis:

* within tolerance -> verdict ``xbrl_match``: the loader serves it ``verified`` even when its doc type is capped;
* off by an exact power of ten (missing or wrong unit) -> ``xbrl_unit_fix`` with the filed scale in ``fix_scale``;
* a sign-only difference on a line whose sign convention varies (exceptional items, changes in inventories) ->
  ``xbrl_match`` (``sign_convention``);
* outside tolerance otherwise -> verdict ``xbrl_contradicts``: the loader serves it ``unverified`` with the filed value in
  ``check_fields`` (the read is never overwritten; a mapping or period mistake must not destroy a right row).

Tolerance: 1%, or the printed rounding (half a unit of the last printed digit), whichever is larger.  Rows with no
basis are compared with both bases and match only when exactly one basis matches.

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
_M_D_Y = re.compile(r"\b" + _MON + r"\s*(\d{1,2})(?:st|nd|rd|th)?[\s,]*(\d{2,4})\b", re.I)
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


def _tolerance(value_text: str, scale: float, filed: float) -> float:
    """1% of the filed value, or half a unit of the last printed digit, whichever is larger."""
    t = (value_text or "").replace(",", "")
    dec = re.search(r"\.(\d+)", t)
    unit = 10 ** -(len(dec.group(1))) if dec else 1.0
    return max(abs(filed) * TOLERANCE, 0.5 * unit * (scale or 1.0))


def store_xbrl() -> dict[str, dict[tuple, float]]:
    """symbol -> {(line_item, period_end, basis): value in rupees} from every store's fin_quarter_xbrl."""
    out: dict[str, dict[tuple, float]] = defaultdict(dict)
    for pattern in STORE_GLOBS:
        for db in glob.glob(pattern):
            if os.path.basename(os.path.dirname(db)) + ".db" != os.path.basename(db):
                continue
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
                rows = con.execute("SELECT symbol, line_item, period_start, period_end, basis, value, scale "
                                   "FROM fin_quarter_xbrl WHERE value IS NOT NULL").fetchall()
                con.close()
            except sqlite3.Error:
                continue
            for sym, li, ps, pe, basis, val, scale in rows:
                try:
                    start, end = dt.date.fromisoformat(ps), dt.date.fromisoformat(pe)
                except (TypeError, ValueError):
                    continue
                if not 80 <= (end - start).days <= 100:        # a quarter only
                    continue
                out[sym][(li, end, (basis or "").lower())] = float(val) * float(scale or 1.0)
    return out


def check_db(db: str | Path, xbrl: dict[str, dict[tuple, float]] | None = None) -> tuple[list[dict], Counter]:
    xbrl = store_xbrl() if xbrl is None else xbrl
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    verdicts: list[dict] = []
    stats: Counter = Counter()
    for r in con.execute("SELECT observation_id, symbol, measure, value, value_text, scale, period, basis, "
                         "entity_scope, status, segment, geography, product FROM observation WHERE record_type='number' AND value IS NOT NULL "
                         "AND status != 'quarantined'"):
        li = MEASURE_TO_XBRL.get(r["measure"] or "")
        if not li or r["symbol"] not in xbrl:
            continue
        if (r["entity_scope"] or "company") not in ("company", ""):
            stats["skip_scope"] += 1
            continue
        if r["segment"] or r["geography"] or r["product"]:
            stats["skip_segment"] += 1          # a segment/geography/product row is never the company's total
            continue
        end = quarter_end(r["period"] or "")
        if end is None:
            stats["skip_period"] += 1
            continue
        val = float(r["value"]) * float(r["scale"] or 1.0)
        bases = [(r["basis"] or "").lower()] if r["basis"] else ["standalone", "consolidated"]
        filed = {b: xbrl[r["symbol"]][(li, end, b)] for b in bases if (li, end, b) in xbrl[r["symbol"]]}
        if not filed:
            stats["no_xbrl_period"] += 1
            continue
        hits = [b for b, f in filed.items() if abs(val - f) <= _tolerance(r["value_text"], r["scale"] or 1.0, f)]
        base = {"id": r["observation_id"], "symbol": r["symbol"], "measure": r["measure"], "line_item": li,
                "period_end": end.isoformat(), "stored": val, "status_before": r["status"],
                "checker": "xbrl_crosscheck", "checked_at": dt.datetime.now().isoformat(timespec="seconds")}
        if len(hits) == 1 or (r["basis"] and hits):
            b = hits[0]
            verdicts.append(base | {"verdict": "xbrl_match", "basis": b, "filed": filed[b],
                                    "evidence": f"XBRL {li} {end} {b} = {filed[b]:,.0f}"})
            stats["match"] += 1
        elif hits:
            stats["ambiguous_basis"] += 1
        else:
            b, f = next(iter(filed.items()))
            tol = _tolerance(r["value_text"], r["scale"] or 1.0, f)
            if li in SIGN_FREE and abs(val + f) <= tol:
                verdicts.append(base | {"verdict": "xbrl_match", "basis": b, "filed": f,
                                        "evidence": f"XBRL {li} {end} {b} = {f:,.0f} (sign_convention)"})
                stats["match_sign_convention"] += 1
                continue
            fix = _power_of_ten(val, f, tol)
            if fix is not None and (r["basis"] or len(filed) == 1):
                verdicts.append(base | {"verdict": "xbrl_unit_fix", "basis": b, "filed": f,
                                        "fix_scale": float(r["scale"] or 1.0) * fix,
                                        "evidence": f"XBRL {li} {end} {b} = {f:,.0f}; stored x{fix:g} off"})
                stats["unit_fix"] += 1
                continue
            if not r["basis"]:
                stats["no_basis_mismatch"] += 1   # an unlabelled basis is never called wrong
                continue
            verdicts.append(base | {"verdict": "xbrl_contradicts", "basis": b, "filed": f,
                                    "evidence": f"XBRL {li} {end} {b} = {f:,.0f}; stored {val:,.0f}"})
            stats["contradicts"] += 1
    con.close()
    for v in verdicts:
        stats[f"{v['verdict']}|{v['status_before']}"] += 1
    return verdicts, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
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
