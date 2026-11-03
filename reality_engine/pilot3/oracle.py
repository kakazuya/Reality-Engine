"""Acceptance test for the pilot3 core tables: re-answer the gap loop's passing answers by fixed SQL.

Oracle = the newest ``answers`` row per qid with status ``answered`` in the three sandbox databases; its
``answer_json.numbers`` carry value / unit / period.  Every question that
``tasks/arch_v4/T048_QUESTION_COVERAGE_2026-11-03.xlsx`` maps to one of our tables has each of its numbers
turned into a fixed query shape from ``queries.py`` and compared (0.5% relative tolerance; money across
crore / million / rupee scales).  A number whose inputs live in a table outside part A (AUM, order book,
segment EBITDA ...) is counted apart, not as a failure.

``python -m reality_engine.pilot3.oracle --db .tmp/pilot3.db --tables core``
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from reality_engine.pilot3 import SANDBOX_DB, SYMBOLS, queries

COVERAGE = Path(__file__).resolve().parents[2] / "tasks" / "arch_v4" / "T048_QUESTION_COVERAGE_2026-11-03.xlsx"
CORE = ("ratio_panel", "price_delivery", "fin_quarter_xbrl", "fin_annual_line", "shp_category", "valuation_daily")
TOL = 0.005
MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
QEND = {1: "06-30", 2: "09-30", 3: "12-31", 4: "03-31"}


# --- oracle -----------------------------------------------------------------------------------------
def load_oracle() -> dict[str, dict]:
    """``{qid: {status, numbers, as_of}}`` from the newest answered row of each sandbox."""
    out = {}
    for symbol in SYMBOLS:
        path = SANDBOX_DB[symbol]
        if not Path(path).is_file():
            raise SystemExit(f"STOPPED: sandbox database missing: {path}")
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for qid, status, blob in con.execute(
                "SELECT qid, status, answer_json FROM answers WHERE status='answered' ORDER BY round, rowid"):
            try:
                numbers = json.loads(blob).get("numbers") or []
            except (TypeError, ValueError):
                numbers = []
            out[qid] = {"symbol": symbol, "status": status, "numbers": numbers}
        con.close()
    return out


def load_coverage() -> dict[str, dict]:
    import openpyxl

    wb = openpyxl.load_workbook(COVERAGE, read_only=True)
    rows = list(wb["questions_300"].iter_rows(values_only=True))
    head = rows[0]
    col = {name: i for i, name in enumerate(head)}
    out = {}
    for r in rows[1:]:
        if r[0]:
            out[r[col["qid"]]] = {"symbol": r[col["company"]], "question": r[col["question"]],
                                  "table": str(r[col["table(s) that would serve it"]]).split(" ")[0],
                                  "as_of": str(r[col["as of"]] or "2026-10-19")[:10]}
    return out


# --- parsing ----------------------------------------------------------------------------------------
def parse_period(text: object) -> tuple[str, str] | None:
    """('Q','Q1FY26') | ('FY','FY26') | ('D','2026-10-16') for the period string of an oracle number."""
    t = str(text or "")
    m = re.search(r"Q([1-4])\s*FY\s?(?:20)?(\d\d)\b", t, re.I)
    if m:
        return "Q", f"Q{m.group(1)}FY{m.group(2)}"
    m = re.search(r"\bFY\s?(?:20)?(\d\d)\b", t, re.I)
    if m:
        return "FY", f"FY{m.group(1)}"
    m = re.search(r"(\d{4})-(\d\d)-(\d\d)", t)
    if m:
        return "D", m.group(0)
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", t)
    if m and m.group(2).lower() in MONTHS:
        return "D", f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(Mar|Jun|Sep|Dec)[a-z]*\.?\s+(\d{4})", t)
    if m:
        return "D", f"{m.group(2)}-{QEND[{'Jun': 1, 'Sep': 2, 'Dec': 3, 'Mar': 4}[m.group(1)]]}"
    return None


def fiscal_of(day: str) -> tuple[str, str] | None:
    """The quarter and year a quarter-end date closes: ('Q4FY26','FY26') for 2026-03-31."""
    y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
    if (m, d) not in ((6, 30), (9, 30), (12, 31), (3, 31)):
        return None
    q = {6: 1, 9: 2, 12: 3, 3: 4}[m]
    fy = str(y + 1 if m >= 4 else y)[2:]
    return f"Q{q}FY{fy}", f"FY{fy}"


def to_date(period: tuple[str, str]) -> str:
    """The quarter-end / year-end date of a period (a plain date stays as it is)."""
    kind, value = period
    if kind == "D":
        return value
    if kind == "FY":
        return f"20{value[2:]}-03-31"
    q, fy = int(value[1]), 2000 + int(value[4:])
    return f"{fy if q == 4 else fy - 1}-{QEND[q]}"


# --- measure -> shape ---------------------------------------------------------------------------------
OTHER = re.compile(r"\b(aum|aun|auf|customer|order|book|bhfl|bfsl|novelis|copper|segment|aluminium|tonne|"
                   r"cost of funds|credit cost|deposit|npa|nim|opex|operating expenses|net total income|per customer|"
                   r"capacity|franchise|share of|prudent|management overlay|to equity|rate)\b", re.I)
PX_RULES = [(r"deliver\w* (percentage|%)|delivery pct", "delivery_pct"), (r"deliver\w* quantity|delivery qty", "deliverable_qty"),
            (r"low", "low"), (r"high", "high"), (r"\bopen", "open"), (r"clos", "close"), (r"price", "close")]
FIN_RULES = [  # regex, (annual/quarter items), ratio metric (for derived ones); first match wins
    (r"net debt incl\w* acceptances", ["net_debt_incl_acceptances"], None),
    (r"net debt to ebitda", ["net_debt_to_ebitda"], "net_debt_to_ebitda"),
    (r"net working capital days", ["net_working_capital_days"], "nwc_days"),
    (r"receivables? in days|debtors? (?:turnover|days)|receivable days", ["receivable_days"], "receivable_days"),
    (r"\broce\b|return on capital employed", ["roce"], "roce"),
    (r"total debt", ["total_debt_incl_leases", "total_borrowings"], None),
    (r"total liabilities", ["total_liabilities"], None),
    (r"book value per share", [], "book_value_per_share"),
    (r"ebitda margin", ["ebitda_margin_pct"], "ebitda_margin_pct"), (r"ebitda", ["ebitda"], "ebitda"),
    (r"net interest income", ["net_interest_income"], "net_interest_income"),
    (r"profit before tax", ["pbt", "pbt_before_exceptional"], None),
    (r"profit after tax|\bpat\b|profit for (the )?(period|year)|profit \(loss\)", ["pat", "pat_owners"], "pat"),
    (r"finance cost", ["finance_cost"], "finance_cost"), (r"depreciation", ["depreciation"], "depreciation"),
    (r"diluted eps", ["eps_diluted"], None), (r"eps|earnings per share", ["eps_basic"], "eps_basic_fy"),
    (r"impairment|loan loss", ["impairment_financial_instruments"], "impairment_financial_instruments"),
    (r"dividend per share", ["dividend_per_share"], None), (r"capital expenditure|capex", ["capex"], None),
    (r"cash flow from operations|operating activities", ["cash_flow_from_operations"], None),
    (r"net worth", ["net_worth"], None), (r"net debt", ["net_debt"], None), (r"borrowings", ["total_borrowings"], None),
    (r"total assets", ["total_assets"], None), (r"other income", ["other_income"], "other_income"),
    (r"total income", ["total_income"], None), (r"revenue", ["revenue_from_operations"], "revenue_from_operations"),
]


def classify(measure: str, unit: str) -> tuple[str, object]:
    m, u = measure.lower(), (unit or "").lower()
    if "52-week" in m or "52 week" in m:
        return "px52", "low" if "low" in m else "high"
    if re.search(r"promoter", m):
        return "shp", ("promoter", "shares" if u in ("number", "shares") else "pct")
    if re.search(r"mutual fund", m):
        return "shp", ("mutual_funds", "pct")
    if re.search(r"fii|fpi|foreign portfolio", m):
        return "shp", ("fpi_total", "pct")
    if re.search(r"shares outstanding|paid-up equity shares|number of shares", m) or \
            ("shares" in m and u in ("number", "shares")):
        return "sc", "shares_outstanding"
    if re.search(r"paid[- ]up (equity )?(share )?capital|paid-up value", m):
        return "sc", "paid_up_capital"
    if "face value" in m:
        return "sc", "face_value"
    if re.search(r"to ebitda|days|receivable|working capital|\broce\b|return on|coverage", m):
        for rx, items, metric in FIN_RULES[:8]:  # measures part D stores (company-stated and balance-sheet based)
            if re.search(rx, m):
                return "fin", (items, metric)
        return "ratio_missing", None  # a derived ratio that part A does not compute (needs balance-sheet inputs)
    if OTHER.search(m):
        return "other", None
    if re.search(r"price|clos|deliver|intraday|\bhigh|\blow", m):
        for rx, field in PX_RULES:
            if re.search(rx, m):
                return "px", field
    for rx, items, metric in FIN_RULES:
        if re.search(rx, m):
            return "fin", (items, metric)
    return "unknown", None


def scale_of(unit: str) -> float:
    u = (unit or "").lower()
    if "cr" in u:
        return 1e7
    if "million" in u or u in ("mn", "m"):
        return 1e6
    if "billion" in u or u == "bn":
        return 1e9
    if "lakh" in u:
        return 1e5
    return 1.0


# --- evaluation -------------------------------------------------------------------------------------
def candidates(conn: sqlite3.Connection, symbol: str, num: dict, question: str, as_of: str) -> tuple[str, list]:
    """(kind, candidate list) for one oracle number; kind 'other' / 'unknown' means outside part A."""
    kind, spec = classify(str(num.get("measure", "")), str(num.get("unit", "")))
    period = parse_period(num.get("period")) or parse_period(num.get("measure"))
    if kind in ("other", "unknown"):
        return kind, []
    if kind == "ratio_missing":
        return "ratio_panel", []
    if kind == "px52":
        start = (date.fromisoformat(as_of) - timedelta(days=365)).isoformat()
        return "price_delivery", queries.px_extreme(conn, symbol, spec, "MIN" if spec == "low" else "MAX", start, as_of)
    if kind == "px":
        if not period:
            return "price_delivery", []
        return "price_delivery", queries.px_on(conn, symbol, to_date(period), spec)
    if kind == "shp":
        if not period:
            return "shp_category", []
        category, what = spec
        return "shp_category", queries.shp(conn, symbol, to_date(period), category, as_of, what)
    if kind == "sc":
        if not period:
            return "share_capital", []
        return "share_capital", queries.shares(conn, symbol, to_date(period), spec)
    items, metric = spec
    if not period:
        return "fin", []
    bases = ["standalone", "not_stated"] if "standalone" in question.lower() else \
        ["consolidated", "not_stated"] if "consolidated" in question.lower() else \
        ["consolidated", "standalone", "not_stated"]
    cands: list = []
    quarter = fy = None
    if period[0] == "Q":
        quarter = period[1]
    elif period[0] == "FY":
        fy = period[1]
    else:  # a date: a quarter end is both that quarter and (for March) the year
        closes = fiscal_of(period[1])
        if not closes:
            return "fin", []
        quarter, fy = closes[0], (closes[1] if period[1][5:7] == "03" else None)
    for basis in bases:
        if quarter:
            for item in items:
                cands += queries.fin_quarter(conn, symbol, quarter, item, basis, as_of)
                cands += queries.fin_annual(conn, symbol, quarter, item, basis, as_of)  # company-stated quarter lines
            if metric:
                cands += queries.ratio(conn, symbol, quarter, metric, basis, as_of)
        if fy:
            for item in items:
                cands += queries.fin_annual(conn, symbol, fy, item, basis, as_of)
            if metric:
                cands += queries.ratio(conn, symbol, fy, metric, basis, as_of)
    return "fin", cands


def _half_unit(value: float) -> float:
    """Half a unit of the last printed decimal of the oracle value (6.5 -> 0.05): stored answers are rounded."""
    text = repr(float(value))
    decimals = len(text.split(".")[1]) if "." in text and not text.endswith(".0") else 0
    return 0.5 * 10 ** -decimals


def judge(value: float, unit: str, cands: list) -> tuple[str, float | None, str]:
    """('reproduced'|'mismatch'|'missing', db value in the oracle's unit, source)"""
    if not cands:
        return "missing", None, ""
    best = None
    for v, native, src in cands:
        conv = v / scale_of(unit) if native == "inr" else v
        err = abs(conv - value) / max(abs(value), 1e-9)
        if abs(conv - value) <= _half_unit(value) + 1e-9 or err <= TOL:
            return "reproduced", conv, src
        if best is None or err < best[0]:
            best = (err, conv, src)
    return "mismatch", best[1], best[2]


def run(db: Path, tables=CORE) -> dict:
    conn = sqlite3.connect(db)
    oracle, coverage = load_oracle(), load_coverage()
    report: dict = {t: {"questions": 0, "reproduced": 0, "mismatched": 0, "not_reachable": 0,
                        "numbers": Counter(), "mismatches": [], "reasons": Counter()} for t in tables}
    for qid, info in sorted(coverage.items()):
        table = info["table"]
        if table not in report:
            continue
        rep = report[table]
        rep["questions"] += 1
        answered = oracle.get(qid)
        if not answered:
            rep["not_reachable"] += 1
            rep["reasons"]["oracle has no check-passing answer"] += 1
            continue
        symbol = info["symbol"]
        verdicts = []
        for num in answered["numbers"]:
            try:
                value = float(num.get("value"))
            except (TypeError, ValueError):
                continue
            kind, cands = candidates(conn, symbol, num, info["question"], info["as_of"])
            if kind in ("other", "unknown"):
                rep["numbers"]["outside part A"] += 1
                continue
            verdict, got, src = judge(value, str(num.get("unit", "")), cands)
            rep["numbers"][verdict] += 1
            verdicts.append((verdict, num, got, src, kind))
        if not verdicts:
            rep["not_reachable"] += 1
            rep["reasons"]["inputs are outside part A tables (or no numbers)"] += 1
        elif any(v[0] == "mismatch" for v in verdicts):
            rep["mismatched"] += 1
            for verdict, num, got, src, _k in verdicts:
                if verdict == "mismatch":
                    rep["mismatches"].append((qid, str(num.get("measure"))[:38], str(num.get("period"))[:14],
                                              num.get("value"), num.get("unit"), round(got, 4), src[:60]))
        elif all(v[0] == "reproduced" for v in verdicts):
            rep["reproduced"] += 1
        else:
            rep["not_reachable"] += 1
            for verdict, num, _g, _s, kind in verdicts:
                if verdict == "missing":
                    rep["reasons"][f"no {kind} row for {str(num.get('measure'))[:30]} / {str(num.get('period'))[:14]}"] += 1
                    break
    conn.close()
    return report


def render(report: dict, detail: bool = False) -> str:
    lines = [f"{'table':<18}{'questions':>10}{'reproduced':>11}{'mismatched':>11}{'not reachable':>14}   numbers"]
    for table, r in report.items():
        nums = ", ".join(f"{k} {v}" for k, v in sorted(r["numbers"].items()))
        lines.append(f"{table:<18}{r['questions']:>10}{r['reproduced']:>11}{r['mismatched']:>11}{r['not_reachable']:>14}   {nums}")
    for table, r in report.items():
        if r["mismatches"]:
            lines.append(f"\nmismatches in {table} (qid, measure, period, oracle value+unit, db value in that unit, source):")
            lines += [f"  {m}" for m in r["mismatches"][: 200 if detail else 12]]
        if detail and r["reasons"]:
            lines.append(f"\nnot reachable in {table}:")
            lines += [f"  {n} x {k}" for k, n in r["reasons"].most_common(12)]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--tables", default="core", help="'core' or a comma list of table names")
    ap.add_argument("--detail", action="store_true")
    args = ap.parse_args(argv)
    tables = CORE if args.tables == "core" else tuple(args.tables.split(","))
    print(render(run(Path(args.db), tables), args.detail))


if __name__ == "__main__":
    main()
