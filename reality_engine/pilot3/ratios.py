"""ratio_panel (formula registry + materialised table) and valuation_daily, from the stores built by
``stores.py``.  Pure Python arithmetic over the pilot3 tables: no model, no network.

Point in time: a derived row's ``known_at`` is the latest ``known_at`` of its inputs, so a ratio never quotes
a quarter it could not yet know.  ``input_refs`` lists the input rows as ``fq:<sym>:<period>:<basis>:<item>``
(fin_quarter_xbrl) or ``fa:<sym>:<FYxx>:<basis>:<item>`` (fin_annual_line) or ``px:<sym>:<date>``."""
from __future__ import annotations

import json
import sqlite3
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta

from reality_engine.pilot3 import SYMBOLS, schema

# formula_id, metric, expression, inputs, unit, note
FORMULAS = [
    ("F_EBITDA", "ebitda", "pbt_before_exceptional + finance_cost + depreciation - other_income",
     "pbt_before_exceptional,finance_cost,depreciation,other_income", "inr",
     "Operating EBITDA excluding other income; matches KEC's reported Q1 FY27 EBITDA (291 crore)"),
    ("F_EBIT", "ebit", "pbt_before_exceptional + finance_cost", "pbt_before_exceptional,finance_cost", "inr", ""),
    ("F_EBITDA_M", "ebitda_margin_pct", "100 * ebitda / revenue_from_operations", "ebitda,revenue_from_operations", "pct", ""),
    ("F_EBIT_M", "ebit_margin_pct", "100 * ebit / revenue_from_operations", "ebit,revenue_from_operations", "pct", ""),
    ("F_PAT_M", "pat_margin_pct", "100 * pat / revenue_from_operations", "pat,revenue_from_operations", "pct", ""),
    ("F_INT_COV", "interest_coverage", "ebitda / finance_cost", "ebitda,finance_cost", "x", ""),
    ("F_REV_YOY", "revenue_growth_yoy_pct", "100 * (revenue / revenue_prior_year - 1)", "revenue_from_operations", "pct", ""),
    ("F_PAT_YOY", "pat_growth_yoy_pct", "100 * (pat / pat_prior_year - 1)", "pat", "pct", ""),
    ("F_FY_SUM", "fy_sum", "sum of the four quarters Q1..Q4 of the fiscal year", "quarterly line items", "inr",
     "FY revenue, pat, ebitda, finance cost, depreciation, other income; needs all four quarters filed"),
    ("F_EPS_FY", "eps_basic_fy", "sum of the four quarterly basic EPS", "eps_basic", "inr_per_share",
     "Approximation: quarterly EPS summed (the annual EPS is a weighted average)"),
    ("F_EPS_TTM", "eps_ttm", "sum of the last four quarterly basic EPS", "eps_basic", "inr_per_share", ""),
    ("F_PAYOUT", "dividend_payout_pct", "100 * dividend_per_share / eps_basic_fy", "dividend_per_share,eps_basic_fy", "pct",
     "Needs dividend_per_share in fin_annual_line"),
    ("F_BVPS", "book_value_per_share", "net_worth / shares_outstanding", "net_worth,shares_outstanding", "inr_per_share",
     "Needs net_worth in fin_annual_line"),
    ("F_MCAP", "market_cap", "close * shares_outstanding", "close,shares_outstanding", "inr", "raw close, shares as filed"),
    ("F_ND_EBITDA", "net_debt_to_ebitda", "net_debt / ltm_ebitda", "net_debt,ebitda", "x",
     "XBRL-derived net debt = borrowings - cash - other bank balances - current investments; EBITDA of the 4 quarters to the date"),
    ("F_DE", "debt_to_equity", "total_borrowings / net_worth", "total_borrowings,net_worth", "x", "borrowings incl. deposits for a lender"),
    ("F_NIM", "nim_pct", "100 * annualised_net_interest_income / average(opening_book, closing_book)",
     "net_interest_income,loans", "pct",
     "Lender NIM (T-051, Bajaj Finance): the period's quarterly net interest income summed and annualised "
     "(x4/n quarters) over the average of the balance-sheet loan book at the period start and end. A NIM the "
     "company states itself stays in kpi_series.nim_pct as its own row, never merged into this one"),
    ("F_ROCE", "roce", "100 * ltm_ebit / capital_employed", "ebit,capital_employed", "pct",
     "capital employed = total assets - current liabilities at the period end (closing, not average)"),
    ("F_ROE", "roe", "100 * ltm_pat / net_worth", "pat,net_worth", "pct", "closing net worth (equity attributable to owners)"),
    ("F_ROA", "roa", "100 * ltm_pat / total_assets", "pat,total_assets", "pct", "closing total assets"),
    ("F_OPEX_NTI", "opex_to_net_total_income_pct",
     "100 * (employee_cost + fee_commission_expense + other_expenses + depreciation) / (total_income - finance_cost)",
     "employee_cost,fee_commission_expense,other_expenses,depreciation,total_income,finance_cost", "pct",
     "Lender operating cost over net total income, both from the filed XBRL annual lines (T-049, 4 Nov 2026: "
     "Bajaj Finance had quarterly rows only). NTI = total income - finance cost = the reported net total income "
     "(FY26: 8,19,895 - 2,86,659.5 = 5,33,235.5 mn = 53,324 crore); the cost components reconcile with the "
     "company's pre-impairment operating profit (53,324 - 17,776 = 35,548 crore)"),
    ("F_REC_DAYS", "receivable_days", "365 * trade_receivables / ltm_revenue", "trade_receivables,revenue_from_operations", "days",
     "closing trade receivables (current + non-current) over trailing-4-quarter revenue"),
    ("F_INV_DAYS", "inventory_days", "365 * inventories / ltm_revenue", "inventories,revenue_from_operations", "days", "revenue basis"),
    ("F_PAY_DAYS", "payable_days", "365 * trade_payables / ltm_revenue", "trade_payables,revenue_from_operations", "days", "revenue basis"),
    ("F_NWC_DAYS", "nwc_days", "365 * (receivables + inventories - payables) / ltm_revenue", "receivables,inventories,payables",
     "days", "trade working capital only; the company's own NWC-days figure is stored beside it as company_stated"),
    ("F_CUR", "current_ratio", "current_assets / current_liabilities", "current_assets,current_liabilities", "x", ""),
    ("F_PE", "pe", "close / trailing_eps", "close,eps_basic", "x",
     "EPS of each quarter restated to the valuation date's share basis by the cumulative split factor"),
    ("F_PB", "pb", "market_cap / net_worth", "market_cap,net_worth", "x", "Needs net_worth"),
    ("F_EV_EBITDA", "ev_ebitda", "(market_cap + net_debt) / trailing_ebitda", "market_cap,net_debt,ebitda", "x", "Needs net_debt"),
    # growth, share, mix and order-book ratios over stored rows: evaluated on demand by queries.py (kpi_growth, kpi_share,
    # kpi_mix, book_to_bill, coverage_years), never stored as extracted values (T-049 E)
    ("F_KPI_YOY", "kpi_growth_yoy_pct", "100 * (kpi[t] / kpi[t - 1 year] - 1)", "kpi_series.metric", "pct",
     "same metric, dimension and basis, period one year earlier (Q1FY27 vs Q1FY26, FY26 vs FY25); both rows at the best confidence"),
    ("F_KPI_QOQ", "kpi_growth_qoq_pct", "100 * (kpi[t] / kpi[t - 1 quarter] - 1)", "kpi_series.metric", "pct",
     "quarters only (Q1FY27 vs Q4FY26)"),
    ("F_SHARE", "kpi_share_pct", "100 * kpi[segment] / kpi[total]", "kpi_series.metric", "pct",
     "denominator = the 'total' row of the same period when stored, else the sum of the segment rows"),
    ("F_MIX", "kpi_mix_pct", "100 * kpi[segment] / sum over segments of kpi[segment]", "kpi_series.metric", "pct",
     "every segment of one metric and period; the shares add to 100"),
    ("F_B2B", "book_to_bill", "order_intake / revenue_from_operations", "kpi_series.order_intake,ratio_panel.revenue_from_operations", "x",
     "same period; revenue from the filed results (ratio_panel), intake from the company's own statement"),
    ("F_COVER", "order_book_coverage_years", "order_book / trailing_twelve_month_revenue", "kpi_series.order_book,ratio_panel.revenue_from_operations", "x",
     "years of revenue the order book covers; FY and quarter-end books use the revenue of the year or the last four quarters"),
]
LENDERS = ("BAJFINANCE",)  # finance cost is the cost of goods for a lender: no EBITDA / EBIT metrics
OPEX_ITEMS = ("employee_cost", "fee_commission_expense", "other_expenses", "depreciation")
OPEX_NTI_INPUTS = (*OPEX_ITEMS, "total_income", "finance_cost")
FLOW_ITEMS = ("revenue_from_operations", "pat", "ebitda", "ebit", "finance_cost", "depreciation", "other_income",
              "interest_income", "net_interest_income", "impairment_financial_instruments")


def _quarters(conn: sqlite3.Connection, symbol: str) -> dict:
    """``{(basis, period_end): {item: (value, known_at, period)}}`` (latest filed value per key) plus helpers."""
    rows = conn.execute(
        "SELECT basis, period_end, fiscal_period, line_item, value, known_at FROM fin_quarter_xbrl "
        "WHERE symbol=? ORDER BY known_at", (symbol,)).fetchall()
    out: dict = defaultdict(dict)
    for basis, end, period, item, value, known in rows:
        out[(basis, end)][item] = (value, known, period)
    for (basis, end), items in out.items():
        pbt, fin, dep, oth = (items.get(k) for k in ("pbt_before_exceptional", "finance_cost", "depreciation", "other_income"))
        if pbt and fin and symbol not in LENDERS:
            ks = [x[1] for x in (pbt, fin, dep, oth) if x]
            period = pbt[2]
            items["ebit"] = (pbt[0] + fin[0], max(ks), period)
            if dep:
                items["ebitda"] = (pbt[0] + fin[0] + dep[0] - (oth[0] if oth else 0.0), max(ks), period)
    return out


def _put(out: list, symbol, isin, period, ptype, start, end, basis, metric, value, unit, formula, refs, known):
    if value is None:
        return
    out.append((symbol, isin, period, ptype, start, end, basis, metric, float(value), unit, 1.0, formula,
                json.dumps(refs), known, "max(known_at of inputs)", 1))


def _fy_of(end: str) -> str:
    y, m = int(end[:4]), int(end[5:7])
    return f"FY{str(y + 1 if m >= 4 else y)[2:]}"


def _panel(conn: sqlite3.Connection, symbol: str, isin: str, out: list) -> None:
    q = _quarters(conn, symbol)
    by_basis: dict = defaultdict(dict)
    for (basis, end), items in q.items():
        by_basis[basis][end] = items
    for basis, periods in by_basis.items():
        ends = sorted(periods)
        flows: dict = {}
        for end in ends:
            items = periods[end]
            rev = items.get("revenue_from_operations")
            period = (rev or next(iter(items.values())))[2]
            start = conn.execute("SELECT period_start FROM fin_quarter_xbrl WHERE symbol=? AND period_end=? LIMIT 1",
                                 (symbol, end)).fetchone()[0]
            ref = lambda i: f"fq:{symbol}:{period}:{basis}:{i}"  # noqa: E731
            for item in FLOW_ITEMS:
                if item in items:
                    _put(out, symbol, isin, period, "Q", start, end, basis, item, items[item][0], "inr",
                         {"ebitda": "F_EBITDA", "ebit": "F_EBIT"}.get(item), [ref(item)], items[item][1])
            ebitda, ebit, pat, fin = items.get("ebitda"), items.get("ebit"), items.get("pat"), items.get("finance_cost")
            if rev and rev[0]:
                for metric, num, fid in (("ebitda_margin_pct", ebitda, "F_EBITDA_M"), ("ebit_margin_pct", ebit, "F_EBIT_M"),
                                         ("pat_margin_pct", pat, "F_PAT_M")):
                    if num:
                        _put(out, symbol, isin, period, "Q", start, end, basis, metric, 100.0 * num[0] / rev[0], "pct",
                             fid, [ref(metric.split("_margin")[0]), ref("revenue_from_operations")],
                             max(num[1], rev[1]))
            if ebitda and fin and fin[0]:
                _put(out, symbol, isin, period, "Q", start, end, basis, "interest_coverage", ebitda[0] / fin[0], "x",
                     "F_INT_COV", [ref("ebitda"), ref("finance_cost")], max(ebitda[1], fin[1]))
            for item, metric, fid in (("revenue_from_operations", "revenue_growth_yoy_pct", "F_REV_YOY"),
                                      ("pat", "pat_growth_yoy_pct", "F_PAT_YOY")):
                prior_end = f"{int(end[:4]) - 1}{end[4:]}"
                cur, prev = items.get(item), periods.get(prior_end, {}).get(item)
                if cur and prev and prev[0]:
                    _put(out, symbol, isin, period, "Q", start, end, basis, metric, 100.0 * (cur[0] / prev[0] - 1.0),
                         "pct", fid, [ref(item), f"fq:{symbol}:{prev[2]}:{basis}:{item}"], max(cur[1], prev[1]))
            eps = items.get("eps_basic")
            if eps:
                _put(out, symbol, isin, period, "Q", start, end, basis, "eps_basic", eps[0], "inr_per_share", None,
                     [ref("eps_basic")], eps[1])
            flows[end] = items
        # fiscal years: all four quarters (Jun, Sep, Dec, Mar) filed
        fys = defaultdict(list)
        for end in ends:
            fys[_fy_of(end)].append(end)
        for fy, fy_ends in fys.items():
            if len(fy_ends) != 4:
                continue
            start = f"{int(fy_ends[-1][:4]) - 1}-04-01"
            agg = {}
            for item in FLOW_ITEMS + ("eps_basic",):
                parts = [periods[e].get(item) for e in fy_ends]
                if all(parts):
                    agg[item] = (sum(p[0] for p in parts), max(p[1] for p in parts))
            refs = lambda i: [f"fq:{symbol}:{periods[e][i][2] if i in periods[e] else '?'}:{basis}:{i}" for e in fy_ends]  # noqa: E731
            for item in FLOW_ITEMS:
                if item in agg:
                    _put(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, item, agg[item][0], "inr", "F_FY_SUM",
                         refs(item), agg[item][1])
            rev = agg.get("revenue_from_operations")
            if rev and rev[0]:
                for metric, item, fid in (("ebitda_margin_pct", "ebitda", "F_EBITDA_M"), ("ebit_margin_pct", "ebit", "F_EBIT_M"),
                                          ("pat_margin_pct", "pat", "F_PAT_M")):
                    if item in agg:
                        _put(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, metric, 100.0 * agg[item][0] / rev[0],
                             "pct", fid, refs(item) + refs("revenue_from_operations"), max(agg[item][1], rev[1]))
            if "ebitda" in agg and "finance_cost" in agg and agg["finance_cost"][0]:
                _put(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, "interest_coverage",
                     agg["ebitda"][0] / agg["finance_cost"][0], "x", "F_INT_COV", refs("ebitda") + refs("finance_cost"),
                     max(agg["ebitda"][1], agg["finance_cost"][1]))
            if "eps_basic" in agg:
                _put(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, "eps_basic_fy", agg["eps_basic"][0],
                     "inr_per_share", "F_EPS_FY", refs("eps_basic"), agg["eps_basic"][1])
            prev_fy = f"FY{int(fy[2:]) - 1:02d}"
            prev_ends = fys.get(prev_fy, [])
            for item, metric, fid in (("revenue_from_operations", "revenue_growth_yoy_pct", "F_REV_YOY"),
                                      ("pat", "pat_growth_yoy_pct", "F_PAT_YOY")):
                if len(prev_ends) == 4 and item in agg:
                    parts = [periods[e].get(item) for e in prev_ends]
                    if all(parts) and sum(p[0] for p in parts):
                        _put(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, metric,
                             100.0 * (agg[item][0] / sum(p[0] for p in parts) - 1.0), "pct", fid, refs(item),
                             max(agg[item][1], max(p[1] for p in parts)))


def build_ratios(conn: sqlite3.Connection) -> dict:
    schema.create(conn, ("formula", "ratio_panel", "valuation_daily"))
    conn.executemany("INSERT INTO formula VALUES (?,?,?,?,?,1,?)", FORMULAS)
    counts = {}
    for symbol in SYMBOLS:
        isin = conn.execute("SELECT isin FROM company WHERE symbol=? ORDER BY isin_from DESC LIMIT 1", (symbol,)).fetchone()
        isin = isin[0] if isin else None
        out: list = []
        _panel(conn, symbol, isin, out)
        _payout_bvps(conn, symbol, isin, out)
        _balance_ratios(conn, symbol, isin, out)
        _lender_opex(conn, symbol, isin, out)
        conn.executemany("INSERT INTO ratio_panel VALUES (" + ",".join("?" * 16) + ")", out)
        counts[symbol] = {"ratio_panel": len(out), "valuation_daily": _valuation(conn, symbol, isin)}
    conn.commit()
    return counts


def _payout_bvps(conn: sqlite3.Connection, symbol: str, isin: str, out: list) -> None:
    """Dividend payout (DPS / FY EPS) and book value per share, when the annual lines carry the inputs."""
    for basis in ("consolidated", "standalone"):
        fy_eps = {}
        for row in out:
            if row[7] == "eps_basic_fy" and row[6] == basis:
                fy_eps[row[2]] = (row[8], row[13])
        for fy, value, known, quote_id in conn.execute(
                "SELECT fiscal_year, value, known_at, rowid FROM fin_annual_line WHERE symbol=? AND basis IN (?, 'not_stated') "
                "AND line_item='dividend_per_share' AND unit IN ('inr','inr_per_share') AND definition='reported' "
                "AND period_type='FY' ORDER BY fiscal_year, known_at",
                (symbol, basis)).fetchall():
            if fy in fy_eps and fy_eps[fy][0]:
                _put(out, symbol, isin, fy, "FY", f"20{int(fy[2:]) - 1}-04-01", f"20{fy[2:]}-03-31", basis,
                     "dividend_payout_pct", 100.0 * value / fy_eps[fy][0], "pct", "F_PAYOUT",
                     [f"fa:{symbol}:{fy}:{basis}:dividend_per_share#{quote_id}", f"ratio:{symbol}:{fy}:{basis}:eps_basic_fy"],
                     max(known or "", fy_eps[fy][1] or ""))

def _qends(end: str) -> list[str]:
    """The four quarter-end dates up to and including `end`."""
    y, m = int(end[:4]), int(end[5:7])
    out = []
    for _ in range(4):
        out.append(f"{y}-{m:02d}-{30 if m in (6, 9) else 31}")
        m -= 3
        if m <= 0:
            m, y = m + 12, y - 1
    return out


def _balance_ratios(conn: sqlite3.Connection, symbol: str, isin: str, out: list) -> None:
    """Ratios on the XBRL balance sheets (year ends and half years): book value per share, leverage, ROCE, ROE and
    working-capital days.  Flows are the four quarters to the balance-sheet date, same basis as the sheet."""
    quarters = _quarters(conn, symbol)
    sheets: dict = defaultdict(dict)  # (basis, fiscal_year, period_end, period_type) -> item -> (value, known, rowid)
    for basis, fy, end, ptype, item, value, known, rowid in conn.execute(
            "SELECT basis, fiscal_year, period_end, period_type, line_item, value*scale, known_at, rowid FROM fin_annual_line "
            "WHERE symbol=? AND definition IN ('xbrl_reported','xbrl_derived') AND period_type IN ('FY','H1') "
            "AND statement IN ('BS','P&L') ORDER BY known_at", (symbol,)):
        sheets[(basis, fy, end, ptype)][item] = (value, known, rowid)
    # the lender's book at each sheet date, so a NIM can average the period's opening and closing loan book
    books = {(basis, end): (bs["loans"][0], bs["loans"][1], bs["loans"][2], fy)
             for (basis, fy, end, ptype), bs in sheets.items() if "loans" in bs}
    for (basis, fy, end, ptype), bs in sorted(sheets.items()):
        qends = _qends(end)
        ltm: dict = {}
        for item in ("revenue_from_operations", "pat", "ebit", "ebitda"):
            parts = [quarters.get((basis, e), {}).get(item) for e in qends]
            if all(parts):
                ltm[item] = (sum(p[0] for p in parts), max(p[1] for p in parts))
        start = f"{int(end[:4]) - 1}-04-01" if end[5:7] == "03" else f"{end[:4]}-04-01"

        def ref(item: str) -> str:
            return f"fa:{symbol}:{fy}:{basis}:{item}#{bs[item][2]}"

        def put(metric, value, unit, fid, items, flows=()):
            known = [bs[i][1] for i in items if i in bs] + [ltm[f][1] for f in flows if f in ltm]
            refs = [ref(i) for i in items if i in bs] + [f"fq:{symbol}:ltm:{basis}:{f}@{end}" for f in flows if f in ltm]
            _put(out, symbol, isin, fy, ptype, start, end, basis, metric, value, unit, fid, refs, max(known))

        nw, debt = bs.get("net_worth"), bs.get("total_borrowings")
        sh = conn.execute("SELECT shares_outstanding, known_at FROM share_capital WHERE symbol=? AND event IS NULL AND basis=? "
                          "AND as_of_date<=? ORDER BY as_of_date DESC, known_at DESC LIMIT 1", (symbol, basis, end)).fetchone()
        if nw and sh and sh[0]:
            _put(out, symbol, isin, fy, ptype, start, end, basis, "book_value_per_share", nw[0] / sh[0], "inr_per_share",
                 "F_BVPS", [ref("net_worth"), f"sc:{symbol}:{end}"], max(nw[1], sh[1] or ""))
        if nw and nw[0] and debt:
            put("debt_to_equity", debt[0] / nw[0], "x", "F_DE", ("total_borrowings", "net_worth"))
        if nw and nw[0] and "pat" in ltm:
            put("roe", 100.0 * ltm["pat"][0] / nw[0], "pct", "F_ROE", ("net_worth",), ("pat",))
        if "total_assets" in bs and "pat" in ltm:
            put("roa", 100.0 * ltm["pat"][0] / bs["total_assets"][0], "pct", "F_ROA", ("total_assets",), ("pat",))
        if symbol in LENDERS and "loans" in bs:
            # NIM: the period's NII annualised over the average of the opening and closing loan book.
            opening = books.get((basis, (date.fromisoformat(start) - timedelta(days=1)).isoformat()))
            qtrs = [e for e in qends if start < e <= end]
            nii = [quarters.get((basis, e), {}).get("net_interest_income") for e in qtrs]
            if opening and nii and all(nii) and opening[0] and opening[0] + bs["loans"][0] > 0:
                nim = (100.0 * (4.0 / len(nii)) * sum(n[0] for n in nii)
                       / ((opening[0] + bs["loans"][0]) / 2.0))
                refs = ([f"fq:{symbol}:{n[2]}:{basis}:net_interest_income" for n in nii]
                        + [f"fa:{symbol}:{opening[3]}:{basis}:loans#{opening[2]}", ref("loans")])
                _put(out, symbol, isin, fy, ptype, start, end, basis, "nim_pct", nim, "pct", "F_NIM", refs,
                     max([n[1] for n in nii] + [opening[1], bs["loans"][1]]))
        if symbol in LENDERS:
            continue
        if "net_debt" in bs and "ebitda" in ltm and ltm["ebitda"][0] > 0:
            put("net_debt_to_ebitda", bs["net_debt"][0] / ltm["ebitda"][0], "x", "F_ND_EBITDA", ("net_debt",), ("ebitda",))
        if "capital_employed" in bs and "ebit" in ltm and bs["capital_employed"][0] > 0:
            put("roce", 100.0 * ltm["ebit"][0] / bs["capital_employed"][0], "pct", "F_ROCE", ("capital_employed",), ("ebit",))
        rev = ltm.get("revenue_from_operations")
        if rev and rev[0]:
            rec, inv = bs.get("trade_receivables"), bs.get("inventories")
            pay_items = [i for i in ("trade_payables_current", "trade_payables_noncurrent") if i in bs]
            if rec:
                put("receivable_days", 365.0 * rec[0] / rev[0], "days", "F_REC_DAYS", ("trade_receivables",), ("revenue_from_operations",))
            if inv:
                put("inventory_days", 365.0 * inv[0] / rev[0], "days", "F_INV_DAYS", ("inventories",), ("revenue_from_operations",))
            if pay_items:
                put("payable_days", 365.0 * sum(bs[i][0] for i in pay_items) / rev[0], "days", "F_PAY_DAYS",
                    pay_items, ("revenue_from_operations",))
            if rec and inv and pay_items:
                put("nwc_days", 365.0 * (rec[0] + inv[0] - sum(bs[i][0] for i in pay_items)) / rev[0], "days", "F_NWC_DAYS",
                    ["trade_receivables", "inventories", *pay_items], ("revenue_from_operations",))
        if "current_assets" in bs and "current_liabilities" in bs and bs["current_liabilities"][0]:
            put("current_ratio", bs["current_assets"][0] / bs["current_liabilities"][0], "x", "F_CUR",
                ("current_assets", "current_liabilities"))


def _lender_opex(conn: sqlite3.Connection, symbol: str, isin: str | None, out: list) -> None:
    """Opex / net total income per fiscal year from the XBRL annual lines (no other input needed).

    Both sides come from the same filing: NTI = total income - finance cost, opex = employee cost + fee and
    commission expense + other expenses + depreciation.  A company without those lines gets no row.
    """
    rows: dict = defaultdict(dict)
    marks = ",".join("?" * len(OPEX_NTI_INPUTS))
    for basis, fy, end, item, value, known, rowid in conn.execute(
            "SELECT basis, fiscal_year, period_end, line_item, value*scale, known_at, rowid FROM fin_annual_line "
            f"WHERE symbol=? AND period_type='FY' AND definition='xbrl_reported' AND unit='inr' "
            f"AND line_item IN ({marks}) ORDER BY known_at",
            (symbol, *OPEX_NTI_INPUTS)).fetchall():
        rows[(basis, fy, end)][item] = (value, known, rowid)
    for (basis, fy, end), items in sorted(rows.items()):
        opex = [items[i] for i in OPEX_ITEMS if i in items]
        income, finance = items.get("total_income"), items.get("finance_cost")
        if len(opex) != len(OPEX_ITEMS) or not income or not finance:
            continue
        nti = income[0] - finance[0]
        if not nti:
            continue
        _put(out, symbol, isin, fy, "FY", f"{int(end[:4]) - 1}-04-01", end, basis, "opex_to_net_total_income_pct",
             100.0 * sum(part[0] for part in opex) / nti, "pct", "F_OPEX_NTI",
             [f"fa:{symbol}:{fy}:{basis}:{item}#{items[item][2]}" for item in OPEX_NTI_INPUTS],
             max(part[1] for part in [*opex, income, finance]))


def _valuation(conn: sqlite3.Connection, symbol: str, isin: str) -> int:
    """valuation_daily: one row per NSE trading day, consolidated basis, every input filed by that day."""
    basis = "consolidated"
    prices = conn.execute("SELECT date, close, adj_factor FROM price_delivery WHERE symbol=? AND exchange='NSE' "
                          "AND close IS NOT NULL ORDER BY date", (symbol,)).fetchall()
    factor = {d: (f if f else 1.0) for d, _c, f in prices}
    fdates = sorted(factor)

    def factor_at(day: str) -> float:
        i = bisect_right(fdates, day) - 1
        return factor[fdates[max(i, 0)]]

    quarters = _quarters(conn, symbol)
    qs = sorted((end, items) for (b, end), items in quarters.items() if b == basis)
    eps_rows = [(items["eps_basic"][1], end, items["eps_basic"][0]) for end, items in qs if "eps_basic" in items]
    pat_rows = [(items["pat"][1], end, items["pat"][0]) for end, items in qs if "pat" in items]
    ebitda_rows = [(items["ebitda"][1], end, items["ebitda"][0]) for end, items in qs if "ebitda" in items]
    shares = conn.execute("SELECT known_at, shares_outstanding FROM share_capital WHERE symbol=? AND event IS NULL "
                          "AND basis=? ORDER BY known_at", (symbol, basis)).fetchall()
    annual = defaultdict(list)
    for item, fy, value, scale, unit, known in conn.execute(
            "SELECT line_item, fiscal_year, value, scale, unit, known_at FROM fin_annual_line WHERE symbol=? AND basis=? "
            "AND line_item IN ('net_worth','net_debt') AND definition='xbrl_derived' ORDER BY known_at", (symbol, basis)):
        if unit in ("inr_crore", "inr", "inr_per_share"):
            annual[item].append((known, fy, value * scale))
    # trailing-12-month dividends per share (ex-date window), restated to the day's share basis by the split factor
    dividends = [(ex, amount * 1.0, known or ex) for ex, amount, known in conn.execute(
        "SELECT ex_date, amount_per_share, known_at FROM dividend_event WHERE symbol=? ORDER BY ex_date", (symbol,))]

    def last4(rows: list, day: str, key_factor: bool = False):
        known = [r for r in rows if r[0][:10] <= day]
        known.sort(key=lambda r: r[1])
        pick = known[-4:]
        if len(pick) < 4:
            return None
        ends = [date.fromisoformat(r[1]) for r in pick]
        if any((b - a) > timedelta(days=110) or (b - a) < timedelta(days=70) for a, b in zip(ends, ends[1:])):
            return None
        return pick

    n = 0
    out = []
    for day, close, _adj in prices:
        sh = [s for s in shares if s[0][:10] <= day]
        if not sh:
            continue
        shares_now = sh[-1][1]
        eps4 = last4(eps_rows, day)
        pat4 = last4(pat_rows, day)
        ebitda4 = last4(ebitda_rows, day)
        f_day = factor_at(day)
        trailing_eps = sum(v * factor_at(k[:10]) / f_day for k, _e, v in eps4) if eps4 else None
        trailing_pat = sum(v for _k, _e, v in pat4) if pat4 else None
        trailing_ebitda = sum(v for _k, _e, v in ebitda4) if ebitda4 else None
        mcap = close * shares_now
        known = [day, sh[-1][0][:10]] + ([max(k for k, _e, _v in eps4)[:10]] if eps4 else [])
        nw = [a for a in annual["net_worth"] if a[0][:10] <= day]
        nd = [a for a in annual["net_debt"] if a[0][:10] <= day]
        window = date.fromisoformat(day) - timedelta(days=365)
        dps = [(ex, amt, k) for ex, amt, k in dividends if window.isoformat() < ex <= day and k[:10] <= day]
        net_worth = nw[-1][2] if nw else None
        net_debt = nd[-1][2] if nd else None
        pe = close / trailing_eps if trailing_eps and trailing_eps > 0 else None
        pb = mcap / net_worth if net_worth and net_worth > 0 else None
        ev = (mcap + net_debt) / trailing_ebitda if net_debt is not None and trailing_ebitda and trailing_ebitda > 0 else None
        ttm_dps = sum(amt * factor_at(ex) / f_day for ex, amt, _k in dps) if dps else None
        dy = 100.0 * ttm_dps / close if ttm_dps and close else None
        refs = {"px": f"px:{symbol}:{day}", "shares": sh[-1][0], "quarters": [r[1] for r in (eps4 or [])]}
        out.append((symbol, isin, day, basis, close, shares_now, mcap, trailing_eps, trailing_pat, net_worth, net_debt,
                    trailing_ebitda, pe, pb, ev, dy, max(known), "max(price date, share count, EPS filing dates)",
                    json.dumps(refs)))
        n += 1
    conn.executemany("INSERT INTO valuation_daily VALUES (" + ",".join("?" * 19) + ")", out)
    return n
