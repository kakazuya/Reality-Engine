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

from reality_engine.pilot3 import profile, schema

# formula_id, metric, expression, inputs, unit, note
FORMULAS = [
    ("F_EBITDA", "ebitda", "pbt_before_exceptional + finance_cost + depreciation - other_income",
     "pbt_before_exceptional,finance_cost,depreciation,other_income", "inr",
     "Operating EBITDA excluding other income; matches KEC's reported Q1 FY27 EBITDA (291 crore)"),
    ("F_EBIT", "ebit", "pbt_before_exceptional + finance_cost", "pbt_before_exceptional,finance_cost", "inr", ""),
    ("F_EBITDA_M", "ebitda_margin_pct", "100 * ebitda / revenue_from_operations", "ebitda,revenue_from_operations", "pct", ""),
    ("F_EBIT_M", "ebit_margin_pct", "100 * ebit / revenue_from_operations", "ebit,revenue_from_operations", "pct", ""),
    ("F_PAT_M", "pat_margin_pct", "100 * pat / revenue_from_operations", "pat,revenue_from_operations", "pct", ""),
    ("F_GROSS_M", "gross_margin_pct",
     "100 * (revenue_from_operations - cost_of_materials - purchases_of_stock_in_trade - changes_in_inventories) "
     "/ revenue_from_operations",
     "revenue_from_operations,cost_of_materials,purchases_of_stock_in_trade,changes_in_inventories", "pct",
     "T-073: a trading / FMCG statement books bought-in goods and its finished-goods inventory movement on their own "
     "lines (a negative inventory change is a cost). Non-lenders only."),
    ("F_INT_COV", "interest_coverage", "ebitda / finance_cost", "ebitda,finance_cost", "x", ""),
    ("F_REV_YOY", "revenue_growth_yoy_pct", "100 * (revenue / revenue_prior_year - 1)", "revenue_from_operations", "pct", ""),
    ("F_PAT_YOY", "pat_growth_yoy_pct", "100 * (pat / pat_prior_year - 1)", "pat", "pct", ""),
    ("F_REV_QOQ", "revenue_growth_qoq_pct", "100 * (revenue / revenue_preceding_quarter - 1)", "revenue_from_operations", "pct",
     "T-057: the preceding quarter is the printed 'preceding' column of the same results table, else the XBRL quarter"),
    ("F_PAT_QOQ", "pat_growth_qoq_pct", "100 * (pat / pat_preceding_quarter - 1)", "pat", "pct",
     "T-057: same as revenue_growth_qoq_pct"),
    ("F_TTM_PRINTED", "ttm_printed", "last_fy + ytd - prior_ytd (Q2/Q3 table) | last_fy + current - year_ago (Q1) | printed year (Q4)",
     "fin_quarter_printed checked rows", "inr",
     "Trailing twelve months from one filing's own printed columns when fin_quarter_xbrl holds fewer than four quarters"),
    ("F_FY_PRINTED", "fy_printed", "the year's flow lines as the latest quarterly table printed them",
     "fin_quarter_printed period_type='fy' checked rows", "inr",
     "A fiscal year whose four quarters are not all held; the earliest filing that printed the year wins"),
    ("F_FY_SUM", "fy_sum", "sum of the four quarters Q1..Q4 of the fiscal year", "quarterly line items", "inr",
     "FY revenue, pat, ebitda, finance cost, depreciation, other income; needs all four quarters filed"),
    ("F_EPS_FY", "eps_basic_fy", "sum of the four quarterly basic EPS", "eps_basic", "inr_per_share",
     "Approximation: quarterly EPS summed (the annual EPS is a weighted average), each quarter restated to the share "
     "basis of the day the last quarter was filed by the cumulative split / bonus factor"),
    ("F_EPS_TTM", "eps_ttm", "sum of the last four quarterly basic EPS", "eps_basic", "inr_per_share", ""),
    ("F_PAT_TTM", "pat_ttm", "sum of pat over the last four quarters", "pat", "inr",
     "Trailing twelve months of PAT from four consecutive quarters; input_refs names each quarter (T-088)"),
    ("F_PAT_BE_TTM", "pat_before_exceptional_ttm",
     "sum over the last four quarters of (pat - exceptional_items)", "pat,exceptional_items", "inr",
     "Trailing twelve months of PAT before exceptional items; input_refs names the four quarters and every quarter "
     "whose exceptional_items is not zero (T-088)"),
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
    ("F_ROE", "roe", "100 * ltm_pat / net_worth", "pat,net_worth", "pct", "average owners' equity (opening + closing)/2 when the opening net worth is held; closing net worth (basis=closing_equity) otherwise"),
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
    ("F_COST_INCOME", "cost_to_income", "100 * operating_expenses / (net_interest_income + other_income)",
     "operating_expenses,net_interest_income,other_income", "pct",
     "Bank cost-to-income of a quarter from the filed lines: OperatingExpenses over (interest earned - interest expended + "
     "other income)"),
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
OPEX_ITEMS = ("employee_cost", "fee_commission_expense", "other_expenses", "depreciation")
OPEX_NTI_INPUTS = (*OPEX_ITEMS, "total_income", "finance_cost")
FLOW_ITEMS = ("revenue_from_operations", "pat", "ebitda", "ebit", "finance_cost", "depreciation", "other_income",
              "interest_income", "net_interest_income", "impairment_financial_instruments")


def _quarters(conn: sqlite3.Connection, symbol: str) -> dict:
    """``{(basis, period_end): {item: (value, known_at, period, period_start)}}`` plus helpers.

    XBRL keeps its value for any (basis, period_end, item) it holds.  Otherwise the printed comparative column
    (``fin_quarter_printed``, ``period_type='quarter'``, checked) fills the quarter from the EARLIEST filing that
    printed it -- that row's ``known_at`` is what a past date may see (T-057)."""
    from reality_engine.pilot3 import comparatives

    out: dict = defaultdict(dict)
    if comparatives.has_table(conn):
        for (basis, end), items in comparatives.printed_quarters(conn, symbol).items():
            for item, cell in items.items():
                out[(basis, end)][item] = cell
    for basis, start, end, period, item, value, known in conn.execute(
            "SELECT basis, period_start, period_end, fiscal_period, line_item, value, known_at FROM fin_quarter_xbrl "
            "WHERE symbol=? ORDER BY known_at", (symbol,)):
        out[(basis, end)][item] = (value, known, period, start)
    for (basis, end), items in out.items():
        pbt, fin, dep, oth = (items.get(k) for k in ("pbt_before_exceptional", "finance_cost", "depreciation", "other_income"))
        if pbt and fin and not profile.is_lender(symbol):
            ks = [x[1] for x in (pbt, fin, dep, oth) if x]
            if any(k is None for k in ks):  # an undated input: the derived line could not be placed in time
                continue
            period = pbt[2]
            start = pbt[3]
            items["ebit"] = (pbt[0] + fin[0], max(ks), period, start)
            if dep:
                items["ebitda"] = (pbt[0] + fin[0] + dep[0] - (oth[0] if oth else 0.0), max(ks), period, start)
    return out


def _put(out: list, symbol, isin, period, ptype, start, end, basis, metric, value, unit, formula, refs, known):
    if value is None:
        return
    out.append((symbol, isin, period, ptype, start, end, basis, metric, float(value), unit, 1.0, formula,
                json.dumps(refs), known, "max(known_at of inputs)", 1))


def _fy_of(end: str) -> str:
    y, m = int(end[:4]), int(end[5:7])
    return f"FY{str(y + 1 if m >= 4 else y)[2:]}"


_FQ = {3: 4, 6: 1, 9: 2, 12: 3}


def _fiscal_q(end: str) -> str:
    """Q2FY26 for a quarter ending 2025-09-30 (Indian fiscal year: April to March)."""
    y, m = int(end[:4]), int(end[5:7])
    return f"Q{_FQ[m]}FY{str(y + 1 if m >= 4 else y)[2:]}"


def _last_fy_end(end: str) -> str:
    y, m = int(end[:4]), int(end[5:7])
    return f"{y - 1}-03-31" if m == 3 else f"{y}-03-31"


def _prev_quarter(end: str) -> str:
    from reality_engine.pilot3.comparatives import shift_period

    return shift_period(end, -3)


def _gross_margin(out: list, symbol, isin, period, ptype, start, end, basis, items: dict, refs_for) -> None:
    """(revenue - materials - stock-in-trade purchases - inventory change) / revenue, non-lenders only (T-073).

    A trading or FMCG statement books its bought-in goods and its finished-goods inventory movement on their own
    lines; with them the cost lines add up to total expenses, without them the margin is overstated."""
    rev = items.get("revenue_from_operations")
    parts = [items.get(k) for k in ("cost_of_materials", "purchases_of_stock_in_trade", "changes_in_inventories")]
    if not rev or not rev[0] or profile.is_lender(symbol) or not any(parts):
        return
    cogs = sum(p[0] for p in parts if p)
    known = max(x[1] for x in (rev, *parts) if x)
    refs = refs_for("revenue_from_operations")
    for key in ("cost_of_materials", "purchases_of_stock_in_trade", "changes_in_inventories"):
        refs += refs_for(key)
    _put(out, symbol, isin, period, ptype, start, end, basis, "gross_margin_pct",
         100.0 * (rev[0] - cogs) / rev[0], "pct", "F_GROSS_M", refs, known)


def _share_count(conn: sqlite3.Connection, symbol: str, basis: str, day: str, as_of: str | None = None):
    """``(shares, known_at, source_table)`` of the latest count known by ``day``.

    The exact total of a filed shareholding pattern wins over the paid-up / face-value division, which is rounded
    (and net of an ESOP trust for some companies; T-073).  Paid-up capital stays the fallback for a day before the
    pattern's own filing.  A store built before ``count_basis`` exists still answers: its shareholding-pattern rows
    are the exact ones by their own ``source_table`` (T-192), so no live store needs a migration to be read."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(share_capital)")}
    basis_expr = ("COALESCE(count_basis, CASE WHEN source_table='shp_category' THEN 'filed_exact' END)"
                  if "count_basis" in have else
                  "CASE WHEN source_table='shp_category' THEN 'filed_exact' END")
    rows = conn.execute(
        f"SELECT as_of_date, shares_outstanding, known_at, source_table, {basis_expr} AS count_basis "
        "FROM share_capital WHERE symbol=? AND basis=? AND event IS NULL AND shares_outstanding>0 AND as_of_date<=? "
        "ORDER BY as_of_date, known_at", (symbol, basis, as_of or day)).fetchall()
    live = [r for r in rows if (r[2] or "")[:10] <= day]
    if not live:
        return None
    exact = [r for r in live if r[4] == "filed_exact"]
    row = (exact or live)[-1]
    return row[1], row[2], row[3]


def _printed_year_ago(conn: sqlite3.Connection, symbol: str, basis: str, item: str, prior_end: str, known: str,
                      prior_label: str):
    """The ``year_ago`` column of the filing that reported the current quarter (same day).

    ``xbrl_ok``, ``repeat_ok`` and ``sum_ok`` all count: ``sum_ok`` means the year-ago column added up on the page,
    which is exactly the comparative a growth uses (HINDUNILVR's Q2 FY27 filing prints Q2 FY26 revenue 15,919 with
    ``sum_ok``; its first printing 16,241 was pre-restatement, T-088 round 2).  Where one filing printed two cells
    for the line, the better check wins (``xbrl_ok`` then ``repeat_ok`` then ``sum_ok``), so INFY's cash-flow
    "Total income" ``sum_ok`` cell cannot beat the XBRL-confirmed revenue cell.  The fiscal label must be the
    year-ago quarter too."""
    from reality_engine.pilot3 import comparatives

    if not comparatives.has_table(conn):
        return None
    row = conn.execute(
        "SELECT value, known_at, fiscal_period, period_start FROM fin_quarter_printed WHERE symbol=? AND basis=? "
        "AND line_item=? AND period_end=? AND fiscal_period=? AND column_role='year_ago' AND period_type='quarter' "
        "AND check_status IN ('xbrl_ok','repeat_ok','sum_ok') "
        "AND abs(julianday(substr(known_at,1,10)) - julianday(substr(?,1,10))) <= 1 "
        "ORDER BY CASE check_status WHEN 'xbrl_ok' THEN 0 WHEN 'repeat_ok' THEN 1 ELSE 2 END, known_at LIMIT 1",
        (symbol, basis, item, prior_end, prior_label, known)).fetchone()
    return tuple(row) if row else None


def _printed_fy(conn: sqlite3.Connection, symbol: str, basis: str) -> dict:
    """``{fiscal_period: {item: (value, known_at, period_end, period_start)}}`` from checked printed full years."""
    from reality_engine.pilot3 import comparatives

    out: dict = defaultdict(dict)
    if not comparatives.has_table(conn):
        return out
    for fy, end, item, value, known, start in conn.execute(
            "SELECT fiscal_period, period_end, line_item, value, known_at, period_start FROM fin_quarter_printed "
            "WHERE symbol=? AND basis=? AND period_type='fy' AND check_status IN ('xbrl_ok','sum_ok','repeat_ok') "
            "ORDER BY known_at", (symbol, basis)):
        out[fy].setdefault(item, (value, known, end, start))
    return out


def _split_factor(conn: sqlite3.Connection, symbol: str):
    """``factor_at(day)``: the cumulative split / bonus factor of the NSE price rows on or before ``day`` (1.0 with no
    price rows).  A quarter's EPS filed on ``d`` is restated to the share basis of day ``b`` by ``f(d) / f(b)``."""
    rows = conn.execute("SELECT date, adj_factor FROM price_delivery WHERE symbol=? AND exchange='NSE' AND close IS NOT NULL "
                        "ORDER BY date", (symbol,)).fetchall()
    days, factors = [r[0] for r in rows], [r[1] if r[1] else 1.0 for r in rows]

    def factor_at(day: str) -> float:
        return factors[max(bisect_right(days, day) - 1, 0)] if days else 1.0

    return factor_at


def _panel(conn: sqlite3.Connection, symbol: str, isin: str | None, out: list) -> None:
    q = _quarters(conn, symbol)
    factor_at = _split_factor(conn, symbol)
    by_basis: dict = defaultdict(dict)
    for (basis, end), items in q.items():
        by_basis[basis][end] = items
    for basis, periods in by_basis.items():
        ends = sorted(periods)
        flows: dict = {}
        for end in ends:
            items = periods[end]
            rev = items.get("revenue_from_operations")
            first = rev or next(iter(items.values()))
            period = first[2]
            start = first[3]
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
                _gross_margin(out, symbol, isin, period, "Q", start, end, basis, items,
                              lambda i: [ref(i)] if i in items else [])
            if ebitda and fin and fin[0]:
                _put(out, symbol, isin, period, "Q", start, end, basis, "interest_coverage", ebitda[0] / fin[0], "x",
                     "F_INT_COV", [ref("ebitda"), ref("finance_cost")], max(ebitda[1], fin[1]))
            for item, metric, fid in (("revenue_from_operations", "revenue_growth_yoy_pct", "F_REV_YOY"),
                                      ("pat", "pat_growth_yoy_pct", "F_PAT_YOY")):
                prior_end = f"{int(end[:4]) - 1}{end[4:]}"
                prior_label = _fiscal_q(prior_end)
                cur = items.get(item)
                year_ago = _printed_year_ago(conn, symbol, basis, item, prior_end, cur[1], prior_label) if cur else None
                fallback = periods.get(prior_end, {}).get(item)
                if fallback and fallback[2] != prior_label:
                    fallback = None      # never a different quarter: an unlabelled/wrong cell refuses the growth
                base = year_ago or fallback
                if cur and base and base[0]:
                    # @fallback marks a base that is NOT the current filing's own year_ago column (T-088)
                    base_ref = f"fq:{symbol}:{base[2]}:{basis}:{item}" + ("" if year_ago else "@fallback")
                    _put(out, symbol, isin, period, "Q", start, end, basis, metric, 100.0 * (cur[0] / base[0] - 1.0),
                         "pct", fid, [ref(item), base_ref], max(cur[1], base[1]))
            for item, metric, fid in (("revenue_from_operations", "revenue_growth_qoq_pct", "F_REV_QOQ"),
                                      ("pat", "pat_growth_qoq_pct", "F_PAT_QOQ")):
                prev_end = _prev_quarter(end)
                cur, prev = items.get(item), periods.get(prev_end, {}).get(item)
                if prev and prev[2] != _fiscal_q(prev_end):
                    prev = None          # same guard as YoY: the previous quarter, or no row at all
                if cur and prev and prev[0]:
                    _put(out, symbol, isin, period, "Q", start, end, basis, metric, 100.0 * (cur[0] / prev[0] - 1.0),
                         "pct", fid, [ref(item), f"fq:{symbol}:{prev[2]}:{basis}:{item}"], max(cur[1], prev[1]))
            eps = items.get("eps_basic")
            if eps:
                _put(out, symbol, isin, period, "Q", start, end, basis, "eps_basic", eps[0], "inr_per_share", None,
                     [ref("eps_basic")], eps[1])
            opex, nii, oth = items.get("operating_expenses"), items.get("net_interest_income"), items.get("other_income")
            if opex and nii and oth and (nii[0] + oth[0]):
                _put(out, symbol, isin, period, "Q", start, end, basis, "cost_to_income", 100.0 * opex[0] / (nii[0] + oth[0]),
                     "pct", "F_COST_INCOME", [ref("operating_expenses"), ref("net_interest_income"), ref("other_income")],
                     max(opex[1], nii[1], oth[1]))
            flows[end] = items
        # trailing twelve months (T-088): four consecutive quarters, every input named so no hand sum is needed
        for end in ends:
            qs = [end]
            for _ in range(3):
                qs.insert(0, _prev_quarter(qs[0]))
            cells = [periods.get(q) for q in qs]
            qparts: list[tuple[str, tuple, dict]] = []
            for q, cell in zip(qs, cells):
                if cell is None:
                    qparts = []
                    break
                pat = cell.get("pat")
                if pat is None:
                    qparts = []
                    break
                qparts.append((q, pat, cell))
            if len(qparts) != 4:
                continue
            period = qparts[-1][1][2]
            start = qparts[0][1][3] or qs[0]
            refs = [f"fq:{symbol}:{p[2]}:{basis}:pat" for _q, p, _c in qparts]
            known = max(p[1] for _q, p, _c in qparts)
            _put(out, symbol, isin, period, "TTM", start, end, basis, "pat_ttm",
                 sum(p[0] for _q, p, _c in qparts), "inr", "F_PAT_TTM", refs, known)
            total, exc_refs, exc_known = 0.0, [], []
            for _q, pat, cell in qparts:
                exc = cell.get("exceptional_items")
                total += pat[0] - (exc[0] if exc else 0.0)
                if exc and exc[0]:       # name the quarter that holds the item, with its amount
                    exc_refs.append(f"fq:{symbol}:{exc[2]}:{basis}:exceptional_items={exc[0]:.0f}")
                    exc_known.append(exc[1])
            _put(out, symbol, isin, period, "TTM", start, end, basis, "pat_before_exceptional_ttm", total, "inr",
                 "F_PAT_BE_TTM", refs + exc_refs, max([known, *exc_known]))
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
            fy_refs = lambda i: [f"fq:{symbol}:{periods[e][i][2] if i in periods[e] else '?'}:{basis}:{i}" for e in fy_ends]  # noqa: E731
            for item in FLOW_ITEMS:
                if item in agg:
                    _put(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, item, agg[item][0], "inr", "F_FY_SUM",
                         fy_refs(item), agg[item][1])
            rev = agg.get("revenue_from_operations")
            if rev and rev[0]:
                for metric, item, fid in (("ebitda_margin_pct", "ebitda", "F_EBITDA_M"), ("ebit_margin_pct", "ebit", "F_EBIT_M"),
                                          ("pat_margin_pct", "pat", "F_PAT_M")):
                    if item in agg:
                        _put(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, metric, 100.0 * agg[item][0] / rev[0],
                             "pct", fid, fy_refs(item) + fy_refs("revenue_from_operations"), max(agg[item][1], rev[1]))
                _gross_margin(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, agg,
                              lambda i: fy_refs(i) if i in agg else [])
            if "ebitda" in agg and "finance_cost" in agg and agg["finance_cost"][0]:
                _put(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, "interest_coverage",
                     agg["ebitda"][0] / agg["finance_cost"][0], "x", "F_INT_COV", fy_refs("ebitda") + fy_refs("finance_cost"),
                     max(agg["ebitda"][1], agg["finance_cost"][1]))
            if "eps_basic" in agg:
                # each quarter's EPS is restated to the share basis of the day the year's last quarter was filed (a bonus
                # or split between two of the quarters would otherwise be summed unadjusted)
                parts = [periods[e]["eps_basic"] for e in fy_ends]
                base = factor_at(agg["eps_basic"][1][:10])
                fy_eps = sum(p[0] * factor_at(p[1][:10]) / base for p in parts) if profile.under_profile() else agg["eps_basic"][0]
                _put(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, "eps_basic_fy", fy_eps,
                     "inr_per_share", "F_EPS_FY", fy_refs("eps_basic"), agg["eps_basic"][1])
            prev_fy = f"FY{int(fy[2:]) - 1:02d}"
            prev_ends = fys.get(prev_fy, [])
            for item, metric, fid in (("revenue_from_operations", "revenue_growth_yoy_pct", "F_REV_YOY"),
                                      ("pat", "pat_growth_yoy_pct", "F_PAT_YOY")):
                if len(prev_ends) == 4 and item in agg:
                    parts = [periods[e].get(item) for e in prev_ends]
                    if all(parts) and sum(p[0] for p in parts):
                        _put(out, symbol, isin, fy, "FY", start, fy_ends[-1], basis, metric,
                             100.0 * (agg[item][0] / sum(p[0] for p in parts) - 1.0), "pct", fid, fy_refs(item),
                             max(agg[item][1], max(p[1] for p in parts)))
        # a year whose four quarters are not all held: the printed full-year columns (and their margins) fill it
        for fy, items in _printed_fy(conn, symbol, basis).items():
            if len(fys.get(fy, [])) == 4:
                continue
            start, end = f"20{int(fy[2:]) - 1:02d}-04-01", f"20{int(fy[2:]):02d}-03-31"
            flat = {item: (value, known) for item, (value, known, _end, _start) in items.items()}
            comps = [flat.get(k) for k in ("pbt_before_exceptional", "finance_cost", "depreciation", "other_income")]
            if comps[0] and comps[1] and comps[2] and not profile.is_lender(symbol):
                flat["ebitda"] = (comps[0][0] + comps[1][0] + comps[2][0] - (comps[3][0] if comps[3] else 0.0),
                                  max(c[1] for c in comps if c))
                flat["ebit"] = (comps[0][0] + comps[1][0], max(comps[0][1], comps[1][1]))
            refs = [f"fp:{symbol}:{fy}:{basis}:{item}" for item in flat]
            for item in FLOW_ITEMS:
                if item in flat:
                    _put(out, symbol, isin, fy, "FY", start, end, basis, item, flat[item][0], "inr",
                         "F_FY_PRINTED", [f"fp:{symbol}:{fy}:{basis}:{item}"], flat[item][1])
            rev = flat.get("revenue_from_operations")
            if rev and rev[0]:
                for metric, item, fid in (("ebitda_margin_pct", "ebitda", "F_EBITDA_M"),
                                          ("ebit_margin_pct", "ebit", "F_EBIT_M"),
                                          ("pat_margin_pct", "pat", "F_PAT_M")):
                    if item in flat:
                        _put(out, symbol, isin, fy, "FY", start, end, basis, metric,
                             100.0 * flat[item][0] / rev[0], "pct", fid,
                             [f"fp:{symbol}:{fy}:{basis}:{item}", f"fp:{symbol}:{fy}:{basis}:revenue_from_operations"],
                             max(flat[item][1], rev[1]))
            if "eps_basic" in flat:
                _put(out, symbol, isin, fy, "FY", start, end, basis, "eps_basic_fy", flat["eps_basic"][0],
                     "inr_per_share", "F_FY_PRINTED", [f"fp:{symbol}:{fy}:{basis}:eps_basic"], flat["eps_basic"][1])


def _input_views(conn: sqlite3.Connection) -> list[str]:
    """TEMP views named like the windowed store tables that read ``main.<t>`` plus ``main.<t>_input`` (the rows
    between ``compute_start`` and ``window_start``), so every query below sees the trailing history; the temp name
    shadows the main table for unqualified queries.  ``fin_annual_line`` exposes ``rowid`` (input rows offset by 1e9)."""
    from reality_engine.pilot3.stores import INPUT_TABLES  # late: stores builds statements -> ratios

    made = []
    for table in INPUT_TABLES:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (f"{table}_input",)).fetchone():
            continue
        keys = ("rowid AS rowid, ", "rowid + 1000000000 AS rowid, ") if table == "fin_annual_line" else ("", "")
        conn.execute(f'CREATE TEMP VIEW "{table}" AS SELECT {keys[0]}* FROM main."{table}" '
                     f'UNION ALL SELECT {keys[1]}* FROM main."{table}_input"')
        made.append(table)
    return made


def build_ratios(conn: sqlite3.Connection) -> dict:
    # T-202: the one migration entry point (a store built before ``count_basis`` gains it before any query reads
    # it, T-192), and a part run straight from a script still arrives on a current schema.
    schema.migrate(conn)
    schema.create(conn, ("formula", "ratio_panel", "valuation_daily"))
    conn.executemany("INSERT INTO formula VALUES (?,?,?,?,?,1,?)", FORMULAS)
    counts = {}
    views = _input_views(conn)
    try:
        for symbol in profile.symbols():
            isin = conn.execute("SELECT isin FROM company WHERE symbol=? ORDER BY isin_from DESC LIMIT 1", (symbol,)).fetchone()
            isin = isin[0] if isin else None
            out: list = []
            _panel(conn, symbol, isin, out)
            _payout_bvps(conn, symbol, isin, out)
            _balance_ratios(conn, symbol, isin, out)
            _lender_opex(conn, symbol, isin, out)
            conn.executemany("INSERT INTO ratio_panel VALUES (" + ",".join("?" * 16) + ")", out)
            counts[symbol] = {"ratio_panel": len(out), "valuation_daily": _valuation(conn, symbol, isin)}
    finally:
        for view in views:
            conn.execute(f"DROP VIEW IF EXISTS temp.{view}")
    from reality_engine.pilot3.stores import trim_derived  # late: stores builds statements -> ratios

    counts["window"] = trim_derived(conn)
    conn.commit()
    return counts


def _payout_bvps(conn: sqlite3.Connection, symbol: str, isin: str | None, out: list) -> None:
    """Dividend payout (DPS / FY EPS), when the annual lines carry the inputs.  One row per fiscal year and basis:
    the year's declared dividends summed from the NSE corporate actions (``source_table`` corporate_actions) win over
    a figure read from an annual report, and a figure not tied to a fiscal year is never used."""
    for basis in ("consolidated", "standalone"):
        fy_eps = {}
        for row in out:
            if row[7] == "eps_basic_fy" and row[6] == basis:
                fy_eps[row[2]] = (row[8], row[13])
        found = conn.execute(
            "SELECT fiscal_year, value, known_at, rowid, source_table FROM fin_annual_line WHERE symbol=? "
            "AND basis IN (?, 'not_stated') AND line_item='dividend_per_share' AND unit IN ('inr','inr_per_share') "
            "AND definition='reported' AND period_type='FY' ORDER BY fiscal_year, known_at", (symbol, basis)).fetchall()
        if profile.under_profile():  # one figure per year; without a profile every row is used, as it always was
            chosen: dict = {}
            for fy, value, known, quote_id, source in found:
                if fy not in chosen or (source == "corporate_actions") > (chosen[fy][3] == "corporate_actions"):
                    chosen[fy] = (value, known, quote_id, source)
            found = [(fy, *rest) for fy, rest in chosen.items()]
        for fy, value, known, quote_id, _source in found:
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


# Ratios of a balance-sheet date (closing balances, trailing four quarters): the half-year sheet of 30 September
# is also the Q2 point in time, so those rows are written a second time under the quarter label.  A period measure
# (the NIM of the half year) is not.
POINT_IN_TIME = ("book_value_per_share", "debt_to_equity", "roe", "roa", "net_debt_to_ebitda", "roce", "receivable_days",
                 "inventory_days", "payable_days", "nwc_days", "current_ratio")


def _quarter_labelled(out: list, first: int) -> None:
    """Copy the H1 point-in-time rows added since ``first`` under their quarter label (Q2FYyy)."""
    from reality_engine.pilot3.stores import fiscal_period  # late: stores builds statements -> ratios

    for row in list(out[first:]):
        if row[3] != "H1" or row[7] not in POINT_IN_TIME:
            continue
        label = fiscal_period(row[5])
        if label:
            quarter_start = f"{row[5][:5]}{int(row[5][5:7]) - 2:02d}-01"
            out.append((row[0], row[1], label, "Q", quarter_start, row[5], *row[6:]))


def _balance_ratios(conn: sqlite3.Connection, symbol: str, isin: str | None, out: list) -> None:
    first = len(out)
    _balance_ratios_rows(conn, symbol, isin, out)
    if profile.under_profile():  # the three-company pilot3 build keeps its present rows
        _quarter_labelled(out, first)


def _balance_ratios_rows(conn: sqlite3.Connection, symbol: str, isin: str | None, out: list) -> None:
    """Ratios on the XBRL balance sheets (year ends and half years): book value per share, leverage, ROCE, ROE and
    working-capital days.  Flows are the four quarters to the balance-sheet date, same basis as the sheet."""
    quarters = _quarters(conn, symbol)
    sheets: dict = defaultdict(dict)  # (basis, fiscal_year, period_end, period_type) -> item -> (value, known, rowid)
    for basis, fy, end, ptype, item, value, known, rowid in conn.execute(
            "SELECT basis, fiscal_year, period_end, period_type, line_item, value*scale, known_at, rowid FROM fin_annual_line "
            "WHERE symbol=? AND definition IN ('xbrl_reported','xbrl_derived') AND period_type IN ('FY','H1') "
            "AND statement IN ('BS','P&L') ORDER BY known_at", (symbol,)):
        sheets[(basis, fy, end, ptype)][item] = (value, known, rowid)
    # opening net worth by (basis, period_end) for the ROE average: (value, fy, rowid, known_at), so the average's
    # own input is named in the row and a grader can rebuild the number from the references.
    equity_by_end = {}
    for (basis, fy, end, _ptype), bs in sheets.items():
        if "net_worth" in bs:
            equity_by_end.setdefault((basis, end), (bs["net_worth"][0], fy, bs["net_worth"][2], bs["net_worth"][1]))
    sheets = defaultdict(dict)
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
        sh = _share_count(conn, symbol, basis, nw[1], end) if nw else None
        if nw and sh and sh[0]:
            _put(out, symbol, isin, fy, ptype, start, end, basis, "book_value_per_share", nw[0] / sh[0], "inr_per_share",
                 "F_BVPS", [ref("net_worth"), f"sc:{symbol}:{end}"], max(nw[1], sh[1] or ""))
        if nw and nw[0] and debt:
            put("debt_to_equity", debt[0] / nw[0], "x", "F_DE", ("total_borrowings", "net_worth"))
        # ROE on average owners' equity when the opening net worth is held; closing equity only otherwise.
        opening_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        opening = equity_by_end.get((basis, opening_end))
        if nw and nw[0] and "pat" in ltm:
            if opening and opening[0]:
                opening_ref = f"fa:{symbol}:{opening[1]}:{basis}:net_worth#{opening[2]}"
                _put(out, symbol, isin, fy, ptype, start, end, basis, "roe",
                     100.0 * ltm["pat"][0] / ((opening[0] + nw[0]) / 2.0), "pct", "F_ROE",
                     [ref("net_worth"), opening_ref, f"fq:{symbol}:ltm:{basis}:pat@{end}"],
                     max(nw[1], opening[3], ltm["pat"][1]))
            else:
                _put(out, symbol, isin, fy, ptype, start, end, "closing_equity", "roe",
                     100.0 * ltm["pat"][0] / nw[0], "pct", "F_ROE", [ref("net_worth")] +
                     [f"fq:{symbol}:ltm:{basis}:pat@{end}"], max(nw[1], ltm["pat"][1]))
        if "total_assets" in bs and "pat" in ltm:
            put("roa", 100.0 * ltm["pat"][0] / bs["total_assets"][0], "pct", "F_ROA", ("total_assets",), ("pat",))
        if profile.is_lender(symbol) and "loans" in bs:
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
        if profile.is_lender(symbol):
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


def _valuation(conn: sqlite3.Connection, symbol: str, isin: str | None) -> int:
    """valuation_daily: one row per NSE trading day from ``price_start`` (only the day loop's floor; every input is
    still read point in time), consolidated basis, every input filed by that day.  A day whose PE/PB/EV inputs are
    not yet known keeps its close and market cap with NULL ratios (T-155)."""
    from reality_engine.pilot3 import comparatives

    def _complete(b: str) -> bool:
        """A basis valuation can use: a share count AND a quarterly statement on it."""
        if not conn.execute("SELECT 1 FROM share_capital WHERE symbol=? AND basis=? AND event IS NULL LIMIT 1",
                            (symbol, b)).fetchone():
            return False
        if conn.execute("SELECT 1 FROM fin_quarter_xbrl WHERE symbol=? AND basis=? LIMIT 1", (symbol, b)).fetchone():
            return True
        return bool(comparatives.has_table(conn) and conn.execute(
            "SELECT 1 FROM fin_quarter_printed WHERE symbol=? AND basis=? AND period_type='quarter' "
            "AND check_status IN ('xbrl_ok','sum_ok','repeat_ok') LIMIT 1", (symbol, b)).fetchone())

    # A stray consolidated printed page must not push a standalone filer onto a basis with no share count and no
    # quarters (T-073, SBILIFE): the basis is the one that has both sides.
    basis = "consolidated" if _complete("consolidated") else "standalone"
    window = profile.price_start()   # T-155: valuation history starts with the prices, not with the documents
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
    # T-057: when fewer than four quarters are held, one filing's own printed columns give the TTM
    ttm_sets = comparatives.ttm_filings(conn, symbol, basis) if comparatives.has_table(conn) else []
    shares = conn.execute("SELECT as_of_date, known_at, shares_outstanding, source_table FROM share_capital "
                          "WHERE symbol=? AND event IS NULL AND basis=? AND shares_outstanding>0 "
                          "ORDER BY as_of_date, known_at", (symbol, basis)).fetchall()

    def shares_asof(day: str):
        """The latest count known on ``day``; the pattern's exact total wins over the rounded paid-up row."""
        live = [r for r in shares if r[1] and r[1][:10] <= day and (r[0] or "")[:10] <= day]   # undated row: never
        exact = [r for r in live if r[3] == "shp_category"]
        return (exact or live)[-1] if live else None

    # The last full year's EPS / PAT / EBITDA, known by its own filing.  A Q2/Q3 results table prints the half
    # (ytd) and prior-half columns but not last year's, so the TTM is last_fy(annual) + ytd - prior_ytd (T-073).
    annual_fy: dict = defaultdict(list)
    for item, end, value, scale, unit, known in conn.execute(
            "SELECT line_item, period_end, value, scale, unit, known_at FROM fin_annual_line WHERE symbol=? AND basis=? "
            "AND line_item IN ('eps_basic','pat','ebitda') AND period_type='FY' AND definition IN "
            "('xbrl_reported','xbrl_derived') ORDER BY known_at", (symbol, basis)):
        if unit in ("inr", "inr_per_share"):
            annual_fy[item].append((end, known, value * scale))

    def fy_value(item: str, end: str, day: str):
        vals = [v for e, k, v in annual_fy.get(item, []) if e == end and (k or "")[:10] <= day]
        return vals[-1] if vals else None

    def ttm_fill(filing: dict, item: str, day: str):
        """last FY (annual line) + the filing's own ytd - prior_ytd, when the filing printed no last-FY column."""
        cells = filing.get("cells") or {}
        ytd, prior = cells.get(("ytd", item)), cells.get(("prior_ytd", item))
        if not ytd or not prior or ytd[2] != "ytd":
            return None
        last = fy_value(item, _last_fy_end(ytd[1]), day)
        return None if last is None else last + ytd[0] - prior[0]

    annual = defaultdict(list)
    for item, end, ptype, value, scale, unit, known in conn.execute(
            "SELECT line_item, period_end, period_type, value, scale, unit, known_at FROM fin_annual_line "
            "WHERE symbol=? AND basis=? AND line_item IN ('net_worth','net_debt') AND definition='xbrl_derived' "
            "ORDER BY known_at", (symbol, basis)):
        if unit in ("inr_crore", "inr", "inr_per_share"):
            annual[item].append((known, end, ptype, value * scale))
    # trailing-12-month dividends per share (ex-date window), restated to the day's share basis by the split factor
    dividends = [(ex, amount * 1.0, known or ex) for ex, amount, known in conn.execute(
        "SELECT ex_date, amount_per_share, known_at FROM dividend_event WHERE symbol=? ORDER BY ex_date", (symbol,))]

    paid_zero = [(known, value) for known, value in conn.execute(
        "SELECT known_at, value FROM fin_annual_line WHERE symbol=? AND basis=? AND line_item='dividends_paid' "
        "AND definition='xbrl_reported' AND period_type='FY' ORDER BY known_at", (symbol, basis))]

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
        if day < window:  # earlier days only feed the split factor
            continue
        sh = shares_asof(day)
        if sh is None:
            continue
        shares_now = sh[2]
        eps4 = last4(eps_rows, day)
        pat4 = last4(pat_rows, day)
        ebitda4 = last4(ebitda_rows, day)
        f_day = factor_at(day)
        trailing_eps = sum(v * factor_at(k[:10]) / f_day for k, _e, v in eps4) if eps4 else None
        trailing_pat = sum(v for _k, _e, v in pat4) if pat4 else None
        trailing_ebitda = sum(v for _k, _e, v in ebitda4) if ebitda4 else None
        ttm_printed = None
        ttm_fy_used = False
        if (eps4 is None or pat4 is None or ebitda4 is None) and ttm_sets:
            ttm = None
            for filing in ttm_sets:
                if filing["known_at"][:10] <= day:
                    ttm = filing
                else:
                    break
            if ttm:
                filling = {}
                for item in ("eps_basic", "pat", "ebitda"):
                    if item in ttm["items"]:
                        filling[item] = ttm["items"][item]
                    else:
                        v = ttm_fill(ttm, item, day)
                        if v is not None:
                            filling[item] = v
                            ttm_fy_used = True
                ttm_printed = ttm if filling else None      # never claim a TTM this filing could not form
                if eps4 is None and "eps_basic" in filling:
                    trailing_eps = filling["eps_basic"] * factor_at(ttm["known_at"][:10]) / f_day
                if pat4 is None and "pat" in filling:
                    trailing_pat = filling["pat"]
                if ebitda4 is None and "ebitda" in filling:
                    trailing_ebitda = filling["ebitda"]
        mcap = close * shares_now
        known = [day, sh[1][:10]] + ([max(k for k, _e, _v in eps4)[:10]] if eps4 else [])
        # the latest FILED balance sheet, annual or half-year (T-073): a half-year sheet filed in October gives
        # net worth / net debt from that filing, not only from the spring year end.
        nw = [a for a in annual["net_worth"] if a[0][:10] <= day]
        nd = [a for a in annual["net_debt"] if a[0][:10] <= day]
        if nw:
            known.append(nw[-1][0][:10])
        if nd:
            known.append(nd[-1][0][:10])
        since = date.fromisoformat(day) - timedelta(days=365)
        dps = [(ex, amt, k) for ex, amt, k in dividends if since.isoformat() < ex <= day and k[:10] <= day]
        net_worth = nw[-1][3] if nw else None
        net_debt = nd[-1][3] if nd else None
        pe = close / trailing_eps if trailing_eps and trailing_eps > 0 else None
        pb = mcap / net_worth if net_worth and net_worth > 0 else None
        ev = (mcap + net_debt) / trailing_ebitda if net_debt is not None and trailing_ebitda and trailing_ebitda > 0 else None
        ttm_dps = sum(amt * factor_at(ex) / f_day for ex, amt, _k in dps) if dps else None
        dy = 100.0 * ttm_dps / close if ttm_dps and close else None
        if dy is None and not dps and close and profile.under_profile():
            paid = [a for a in paid_zero if a[0][:10] <= day]  # no declared dividend and the filed cash flow shows none
            if paid and paid[-1][1] == 0:
                dy = 0.0
        refs = {"px": f"px:{symbol}:{day}", "shares": sh[1], "quarters": [r[1] for r in (eps4 or [])]}
        if nd:
            refs["net_debt"] = f"bs {nd[-1][1]} {nd[-1][2]} known {nd[-1][0][:10]}"
        if nw:
            refs["net_worth"] = f"bs {nw[-1][1]} {nw[-1][2]} known {nw[-1][0][:10]}"
        if eps4 and pat4:
            refs["ttm"] = "4_quarters"
        if ttm_printed:
            refs["ttm_printed"] = ttm_printed["doc_key"]
            refs["ttm"] = "last_fy(annual)+ytd-prior_ytd" if ttm_fy_used else "printed: last_fy+ytd-prior_ytd"
            known.append(ttm_printed["known_at"][:10])
        out.append((symbol, isin, day, basis, close, shares_now, mcap, trailing_eps, trailing_pat, net_worth, net_debt,
                    trailing_ebitda, pe, pb, ev, dy, max(known), "max(price date, share count, EPS filing dates)",
                    json.dumps(refs)))
        n += 1
    conn.executemany("INSERT INTO valuation_daily VALUES (" + ",".join("?" * 19) + ")", out)
    return n
