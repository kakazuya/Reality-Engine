"""Structured stores into the pilot3 tables: share_capital, fin_quarter_xbrl, fin_annual_line,
price_delivery, shp_category.  Rows are read through the gap loop's own copy specs
(``gap_loop.prepare.store_copies``) widened to every ISIN the symbol has had; ``known_at`` always comes from
the filing record the store carries.  No model, no network."""
from __future__ import annotations

import dataclasses
import gzip
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from bisect import bisect_right
from datetime import date, datetime, timedelta
from pathlib import Path

from reality_engine.gap_loop import prepare
from reality_engine.pilot3 import SHP_XBRL, profile, schema
from reality_engine.pilot3.registry import all_isins, isin_history

CR = 1e7  # rupees per crore

# The history window a profile keeps (T-056): every store table and its date column.  No profile -> no filter.
WINDOW_COLUMNS = {"fin_quarter_xbrl": "period_end", "fin_annual_line": "period_end", "shp_category": "quarter_end",
                  "shp_holder": "quarter_end", "shp_pledge": "quarter_end",
                  "price_delivery": "date", "valuation_daily": "date", "bulk_block_deal": "deal_date",
                  "insider_trade": "intimation_date", "index_price": "date"}
# Tables whose rows dated from ``compute_start`` up to ``window_start`` are kept apart as ``<table>_input``: inputs
# of a trailing four quarters or a prior-year comparison, never part of an answer table (ratios.py reads them).
INPUT_TABLES = ("fin_quarter_xbrl", "fin_annual_line", "price_delivery")
# The shareholding tables keep their whole history from ``compute_start`` instead (T-088): a quarter of the pattern
# is a few hundred rows, and the pledge history and the September-2025 base are answers, not inputs.
HISTORY_TABLES = ("shp_category", "shp_holder", "shp_pledge")


def apply_window(conn: sqlite3.Connection) -> dict:
    """Delete a profile's rows dated before ``window_start``; returns ``{table: rows deleted}``.  With a
    ``compute_start`` the rows of ``INPUT_TABLES`` from that date on are first copied to ``<table>_input``, and the
    ``HISTORY_TABLES`` keep their rows from ``compute_start`` on."""
    start = profile.window_start()
    if not start:
        return {}
    compute = profile.compute_start()
    history = compute or start
    out = {}
    for table, column in WINDOW_COLUMNS.items():
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            continue
        if table in INPUT_TABLES:
            conn.execute(f'DROP TABLE IF EXISTS "{table}_input"')
            if compute:
                conn.execute(f'CREATE TABLE "{table}_input" AS SELECT * FROM "{table}" WHERE {column} >= ? AND {column} < ?',
                             (compute, start))
        out[table] = conn.execute(f"DELETE FROM {table} WHERE {column} < ?",
                                  (history if table in HISTORY_TABLES else start,)).rowcount
    return out


def trim_derived(conn: sqlite3.Connection) -> dict:
    """After the ratios are computed over the inputs: drop derived rows dated before ``window_start``."""
    start = profile.window_start()
    if not start:
        return {}
    out = {"valuation_daily": conn.execute("DELETE FROM valuation_daily WHERE date < ?", (start,)).rowcount}
    if profile.compute_start():
        out["ratio_panel"] = conn.execute("DELETE FROM ratio_panel WHERE period_end < ?", (start,)).rowcount
    return out


def _spec(symbol: str, table: str) -> dict:
    company = dataclasses.replace(profile.company(symbol), isins=all_isins(symbol))
    for spec in prepare.store_copies(company):
        if spec["table"] == table:
            return spec
    raise KeyError(table)


def fetch(symbol: str, table: str, sql: str | None = None) -> list[dict]:
    """The company's rows of a gap-loop store table as dicts (``sql`` overrides the spec's SELECT)."""
    spec = _spec(symbol, table)
    rows, types = prepare._read_sqlite(spec["db"], spec["source"], sql or spec["sql"], spec["params"])
    cols = list(types)
    return [dict(zip(cols, row)) for row in rows]


def _duck(sql: str, params: tuple = ()) -> tuple[list, list[str]]:
    rows, types = prepare._read_duckdb(sql, params)
    return rows, list(types)


def _isin_marks(symbol: str) -> tuple[str, tuple]:
    isins = all_isins(symbol)
    return ",".join("?" * len(isins)), isins


def fiscal_period(period_end: str) -> str | None:
    """Q1FY27 for a quarter ending 2026-06-30 (Indian FY: April to March)."""
    try:
        y, m = int(period_end[:4]), int(period_end[5:7])
    except (TypeError, ValueError):
        return None
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(m)
    if q is None:
        return None
    fy = y + 1 if m >= 4 else y
    return f"Q{q}FY{str(fy)[2:]}"


def _days(a: str, b: str) -> int | None:
    try:
        return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    except (TypeError, ValueError):
        return None


# --- fin_quarter_xbrl + share_capital -------------------------------------------------------------
# A trading / FMCG statement books bought-in goods and its own finished-goods inventory movement on their own
# lines (T-073).  The ``quarterly`` view does not expose them, so ``_quarter_extras`` reads them from
# ``results_xbrl.facts``; keeping them in both maps writes them once, and picks them up for free if the view widens.
STOCK_COST_TAGS = {
    "PurchasesOfStockInTrade": ("purchases_of_stock_in_trade", "P&L", "inr"),
    "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade": ("changes_in_inventories", "P&L", "inr"),
}
QUARTER_TAGS = {  # XBRL element -> (canonical line item, statement, unit)
    "RevenueFromOperations": ("revenue_from_operations", "P&L", "inr"),
    "OtherIncome": ("other_income", "P&L", "inr"),
    "Income": ("total_income", "P&L", "inr"),
    "CostOfMaterialsConsumed": ("cost_of_materials", "P&L", "inr"),
    **STOCK_COST_TAGS,
    "EmployeeBenefitExpense": ("employee_cost", "P&L", "inr"),
    "FinanceCosts": ("finance_cost", "P&L", "inr"),
    "DepreciationDepletionAndAmortisationExpense": ("depreciation", "P&L", "inr"),
    "OtherExpenses": ("other_expenses", "P&L", "inr"),
    "Expenses": ("total_expenses", "P&L", "inr"),
    "ProfitBeforeExceptionalItemsAndTax": ("pbt_before_exceptional", "P&L", "inr"),
    "ExceptionalItemsBeforeTax": ("exceptional_items", "P&L", "inr"),
    "ProfitBeforeTax": ("pbt", "P&L", "inr"),
    "TaxExpense": ("tax", "P&L", "inr"),
    "ProfitLossForPeriodFromContinuingOperations": ("pat_continuing", "P&L", "inr"),
    "ProfitLossForPeriod": ("pat", "P&L", "inr"),
    "ProfitOrLossAttributableToOwnersOfParent": ("pat_owners", "P&L", "inr"),
    "ComprehensiveIncomeForThePeriod": ("total_comprehensive_income", "P&L", "inr"),
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": ("eps_basic", "P&L", "inr_per_share"),
    "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations": ("eps_diluted", "P&L", "inr_per_share"),
    "PaidUpValueOfEquityShareCapital": ("paid_up_capital", "capital", "inr"),
    "FaceValueOfEquityShareCapital": ("face_value", "capital", "inr_per_share"),
}


EXTRA_QUARTER_TAGS = {  # facts the `quarterly` view lacks (NBFC / lender P&L + the stock-cost lines), read from results_xbrl.facts
    **STOCK_COST_TAGS,
    "InterestEarned": ("interest_income", "P&L", "inr"),
    "ImpairmentOnFinancialInstruments": ("impairment_financial_instruments", "P&L", "inr"),
    "FeesAndCommissionIncome": ("fee_commission_income", "P&L", "inr"),
    "FeesAndCommissionExpense": ("fee_commission_expense", "P&L", "inr"),
    "NetGainOnFairValueChanges": ("net_gain_fair_value", "P&L", "inr"),
}
# Bank and life-insurer taxonomies (T-056 loop 2): their own element names for the same lines.  A taxonomy is
# recognised by one marker element in the filing, so a company needs no entry; a line the `quarterly` view already
# gave for that filing is never written twice.
BANK_MARKER, LIFE_MARKER = "InterestExpended", "GrossPremiumIncome"
BANK_TAGS = {
    "InterestExpended": ("interest_expended", "P&L", "inr"),
    "EmployeesCost": ("employee_cost", "P&L", "inr"),
    "OtherOperatingExpenses": ("other_expenses", "P&L", "inr"),
    "OperatingExpenses": ("operating_expenses", "P&L", "inr"),
    "ExpenditureExcludingProvisionsAndContingencies": ("expenditure_excl_provisions", "P&L", "inr"),
    "OperatingProfitBeforeProvisionAndContingencies": ("operating_profit", "P&L", "inr"),
    "ProvisionsOtherThanTaxAndContingencies": ("provisions_and_contingencies", "P&L", "inr"),
    "ProfitLossFromOrdinaryActivitiesBeforeTax": ("pbt", "P&L", "inr"),
    "ProfitLossForThePeriod": ("pat", "P&L", "inr"),
    "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates": ("pat_owners", "P&L", "inr"),
    "BasicEarningsPerShareAfterExtraordinaryItems": ("eps_basic", "P&L", "inr_per_share"),
    "DilutedEarningsPerShareAfterExtraordinaryItems": ("eps_diluted", "P&L", "inr_per_share"),
}
LIFE_TAGS = {
    "GrossPremiumIncome": ("gross_premium", "P&L", "inr"),
    "NetPremiumIncome": ("net_premium", "P&L", "inr"),
    "IncomeFromInvestmentsNet": ("investment_income", "P&L", "inr"),
    "ExpensesOfManagement": ("expenses_of_management", "P&L", "inr"),
    "NetCommission": ("net_commission", "P&L", "inr"),
    "NetSurplusDeficit": ("net_surplus", "P&L", "inr"),
    "ProfitLossBeforeTax": ("pbt", "P&L", "inr"),
    "ProfitLossAfterTaxAndExtraordinaryItems": ("pat", "P&L", "inr"),
}
# one element carries both EPS lines of a life insurer
LIFE_EPS = "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized"
SECTOR_TAGS = {**BANK_TAGS, **LIFE_TAGS}


def _quarter_extras(symbol: str, meta: dict[str, tuple], have: set | None = None) -> list[tuple]:
    """NBFC, bank and life-insurer fields per quarter (``meta``: file -> the filing's columns) plus net interest
    income, a derived row (``is_reported`` 0) wherever both inputs were filed: interest earned - interest expended for
    a bank, else interest earned - finance costs.  ``have`` holds the ``(file, line item)`` pairs already written."""
    if not meta:
        return []
    have = set(have or ())
    tags = tuple(EXTRA_QUARTER_TAGS) + tuple(SECTOR_TAGS) + ("FinanceCosts", LIFE_EPS)
    out, got = [], {}
    files = list(meta)
    for i in range(0, len(files), 200):
        chunk = files[i:i + 200]
        marks = ",".join("?" * len(chunk))
        rows, _ = prepare._read_sqlite(
            "results_xbrl.db", "facts",
            f"SELECT file, concept, value, rowid FROM facts WHERE file IN ({marks}) AND context='OneD' "
            f"AND concept IN ({','.join('?' * len(tags))})", tuple(chunk) + tags)
        for file, tag, value, rowid in rows:
            if value is None:
                continue
            got[(file, tag)] = (float(value), rowid)

    def add(file, tag, item, statement, unit, value, rowid, reported=1, src=None):
        if (file, item) in have:
            return
        have.add((file, item))
        isin, start, end, period, basis, audited, known = meta[file]
        out.append((symbol, isin, start, end, period, basis, audited, statement, item, tag, value, unit, 1.0, file,
                    "results_xbrl.db", "facts", src or f"{file}#{rowid}", known,
                    "results_xbrl.quarterly.dissem_ts|broadcast_ts|filings.filing_ts|file name stamp", reported))

    bank = {file for (file, tag) in got if tag == BANK_MARKER}
    life = {file for (file, tag) in got if tag == LIFE_MARKER}
    for (file, tag), (value, rowid) in got.items():
        if tag in EXTRA_QUARTER_TAGS:
            item, statement, unit = EXTRA_QUARTER_TAGS[tag]
            add(file, tag, item, statement, unit, value, rowid)
        elif tag in BANK_TAGS and file in bank:
            item, statement, unit = BANK_TAGS[tag]
            add(file, tag, item, statement, unit, value, rowid)
        elif tag in LIFE_TAGS and file in life:
            item, statement, unit = LIFE_TAGS[tag]
            add(file, tag, item, statement, unit, value, rowid)
        elif tag == LIFE_EPS and file in life:
            for item in ("eps_basic", "eps_diluted"):
                add(file, tag, item, "P&L", "inr_per_share", value, rowid)
    for file in meta:
        earned = got.get((file, "InterestEarned"))
        expended = got.get((file, "InterestExpended")) if file in bank else None
        fin = got.get((file, "FinanceCosts"))
        cost, name = (expended, "InterestEarned-InterestExpended") if expended else (fin, "InterestEarned-FinanceCosts")
        if earned and cost:
            add(file, name, "net_interest_income", "P&L", "inr", earned[0] - cost[0], None, 0,
                f"{file}#{earned[1]}-{cost[1]}")
    return out


def _basis(value: object) -> str:
    return "consolidated" if str(value or "").strip().lower() == "consolidated" else "standalone"


def build_quarterly(conn: sqlite3.Connection) -> dict:
    """fin_quarter_xbrl (long form, every reported quarter) and share_capital (paid-up / face value)."""
    schema.create(conn, ("fin_quarter_xbrl", "share_capital"))
    counts = {"fin_quarter_xbrl": {}, "share_capital": {}, "skipped_non_quarter": {}}
    for symbol in profile.symbols():
        rows = fetch(symbol, "results_quarterly")
        fq, sc, skipped, meta = [], [], 0, {}
        for r in rows:
            span = _days(r["period_start"], r["period_end"])
            if span is None or not 80 <= span <= 100:
                skipped += 1
                continue
            period, basis = fiscal_period(r["period_end"]), _basis(r["consolidated"])
            meta[r["file"]] = (r["isin"], r["period_start"], r["period_end"], period, basis, r["audited"], r["known_at"])
            for tag, (item, statement, unit) in QUARTER_TAGS.items():
                value = r.get(tag)
                if value is None:
                    continue
                fq.append((symbol, r["isin"], r["period_start"], r["period_end"], period, basis, r["audited"],
                           statement, item, tag, float(value), unit, 1.0, r["file"], "results_xbrl.db",
                           "quarterly", r["file"], r["known_at"], "results_xbrl.quarterly.dissem_ts|broadcast_ts|filings.filing_ts|file name stamp", 1))
            paid, face = r.get("PaidUpValueOfEquityShareCapital"), r.get("FaceValueOfEquityShareCapital")
            if paid and face:
                sc.append((symbol, r["isin"], r["period_end"], basis, None, None, paid / face, paid, face, "shares",
                           1.0, r["known_at"], "results_xbrl.quarterly.dissem_ts|broadcast_ts|filings.filing_ts|file name stamp", "results_xbrl.db",
                           "quarterly", r["file"], None, None))
        fq += _quarter_extras(symbol, meta, {(r[13], r[8]) for r in fq})
        conn.executemany("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, "
                         "audited, statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, "
                         "source_table, source_rowid, known_at, known_at_source, is_reported) VALUES ("
                         + ",".join("?" * 20) + ")", fq)
        conn.executemany("INSERT INTO share_capital VALUES (" + ",".join("?" * 18) + ")", sc)
        counts["fin_quarter_xbrl"][symbol] = len(fq)
        counts["share_capital"][symbol] = len(sc)
        counts["skipped_non_quarter"][symbol] = skipped
    conn.commit()
    return counts


def _ratio(subject: str) -> str | None:
    m = re.search(r"from\s+r[se]\.?\s*([\d.]+)\s*/?-?.*?to\s+r[se]\.?\s*([\d.]+)", subject, re.I)
    if m:
        return f"{float(m.group(1)) / float(m.group(2)):g}:1"
    m = re.search(r"(\d+)\s*:\s*(\d+)", subject)
    return f"{m.group(1)}:{m.group(2)}" if m else None


def build_corporate_events(conn: sqlite3.Connection) -> dict:
    """Split / bonus / buyback events into share_capital (rows with ``event`` set); ISIN windows into
    ``isin_effective_*`` for every share_capital row."""
    counts = {}
    for symbol in profile.symbols():
        rows, _cols = _duck(
            "SELECT id, isin, subject, action_type, ex_date, broadcast_date, known_at_src FROM corporate_actions "
            "WHERE symbol=? AND action_type IN ('SPLIT','BONUS','BUYBACK') ORDER BY ex_date", (symbol,))
        out = []
        for id_, isin, subject, kind, ex, bdate, kat in rows:
            known = kat or bdate or str(ex)
            out.append((symbol, isin, str(ex), None, str(kind).lower(), _ratio(subject or ""), None, None, None,
                        None, None, str(known), "corporate_actions.known_at_src|broadcast_date|ex_date",
                        "truth snapshot", "corporate_actions", str(id_), None, None))
        conn.executemany("INSERT INTO share_capital VALUES (" + ",".join("?" * 18) + ")", out)
        counts[symbol] = len(out)
        for isin, start, end, _src in isin_history(symbol):
            conn.execute("UPDATE share_capital SET isin_effective_from=?, isin_effective_to=? "
                         "WHERE symbol=? AND isin=?", (start, end, symbol, isin))
    conn.commit()
    return counts


# --- fin_annual_line --------------------------------------------------------------------------------
_PFX = r"(?:consolidated |standalone |total |net )?"
LEXICON = [  # (line_item, statement, anchored regex over the lower-cased caption); first match wins
    ("net_debt_incl_acceptances", "BS", r"net debt including acceptances(?: at year[- ]end)?"),
    ("net_working_capital_days", "BS", r"net working capital days"),
    ("receivable_days", "BS", r"(?:trade )?(?:receivables|debtors)(?: turnover)?(?: in)? days|debtor days|receivable days|"
                                       r"(?:debtors|trade receivables?) turnover ratio \((?:no\. of )?days\)(?: - [a-z ]+)?"),
    ("inventory_days", "BS", r"inventory (?:turnover )?days"),
    ("total_debt_incl_leases", "BS", r"total debt \(.*lease.*\)|total debt incl\w* lease liabilities"),
    ("net_debt_to_ebitda", "BS", r"(?:consolidated )?net debt(?: to |/)ebitda(?: ratio)?"),
    ("net_debt_to_equity", "BS", r"net debt(?: to |/)equity(?: ratio)?"),
    ("roce", "P&L", r"return on capital employed(?: \(roce\))?|roce"),
    ("roe", "P&L", r"return on equity(?: \(roe\))?|return on net worth"),
    ("lease_liabilities", "BS", r"(?:total )?lease liabilities"),
    ("revenue_from_operations", "P&L", rf"{_PFX}(?:revenue from operations|revenue)(?: \(net\))?"),
    ("total_income", "P&L", r"total income"),
    ("other_income", "P&L", r"other income"),
    ("net_interest_income", "P&L", r"net interest income(?: \(nii\))?"),
    ("net_total_income", "P&L", r"net total income(?: \(nti\))?"),
    ("ebitda", "P&L", r"(?:consolidated )?ebitda"),
    ("ebitda_margin_pct", "P&L", r"(?:consolidated )?ebitda margin"),
    ("finance_cost", "P&L", r"finance costs?"),
    ("depreciation", "P&L", r"depreciation and amortisation(?: expenses?)?"),
    ("pbt", "P&L", r"profit before tax(?: \(pbt\))?"),
    ("pat", "P&L", r"profit after tax(?: \(pat\))?|profit for the (?:year|period)|net profit"),
    ("impairment_financial_instruments", "P&L", r"impairment on financial instruments"),
    ("operating_profit_pre_impairment", "P&L", r"pre-impairment operating profit"),
    ("eps_basic", "P&L", r"basic eps|basic earnings per share"),
    ("eps_diluted", "P&L", r"diluted eps|diluted earnings per share"),
    ("dividend_per_share", "P&L", r"(?:final |total |proposed )?dividend per (?:equity )?share"),
    ("cash_flow_from_operations", "CF", r"net cash (?:flow )?(?:from|generated from) operating activities"),
    ("capex", "CF", r"capital expenditure|capex"),
    ("net_debt", "BS", r"net debt"),
    ("net_worth", "BS", r"net worth|total equity"),
    ("total_assets", "BS", r"total assets"),
    ("total_borrowings", "BS", r"total borrowings|borrowings"),
]
# Measures the company defines itself (ratio notes, decks): stored with definition 'company_stated' next to the
# XBRL-derived ones, never merged with them.
COMPANY_STATED = {"net_debt_incl_acceptances", "net_working_capital_days", "receivable_days", "inventory_days",
                  "total_debt_incl_leases", "net_debt_to_ebitda", "net_debt_to_equity", "roce", "roe", "net_debt",
                  "ebitda", "ebitda_margin_pct"}
_LEX = [(item, stmt, re.compile(rf"^(?:{rx})$")) for item, stmt, rx in LEXICON]


def lexicon_item(caption: str) -> tuple[str, str] | None:
    text = re.sub(r"\s+", " ", str(caption or "").strip().lower())
    if len(text) > 110:
        return None
    for item, stmt, rx in _LEX:
        if rx.match(text):
            return item, stmt
    # a company-stated caption may carry its year ("Net Working Capital days FY26"): the row's period column decides
    bare = re.sub(r"\s+(?:fy\s?'?\d{2,4}(?:-\d{2})?|q[1-4]\s?fy\s?\d{2})$", "", text)
    if bare != text:
        for item, stmt, rx in _LEX:
            if item in COMPANY_STATED and rx.match(bare):
                return item, stmt
    return None


# The rupee scale a unit text names (T-115): annual-report fonts print the rupee sign as '`' or '₹', so the word is
# what counts.  A text naming two scales ("rs lakh crore") or none keeps its raw text and scale 1 - never a guess.
_UNIT_SCALE = {"cr": ("inr_crore", CR), "crore": ("inr_crore", CR), "crores": ("inr_crore", CR),
               "mn": ("inr_million", 1e6), "million": ("inr_million", 1e6), "millions": ("inr_million", 1e6),
               "bn": ("inr_billion", 1e9), "billion": ("inr_billion", 1e9), "billions": ("inr_billion", 1e9),
               "lakh": ("inr_lakh", 1e5), "lakhs": ("inr_lakh", 1e5), "lac": ("inr_lakh", 1e5),
               "lacs": ("inr_lakh", 1e5), "thousand": ("inr_thousand", 1e3), "thousands": ("inr_thousand", 1e3),
               "paise": ("inr", 0.01), "paisa": ("inr", 0.01)}


def _unit(unit: object) -> tuple[str, float]:
    """(canonical unit, rupees per printed unit) of a stored annual-report unit text (T-115)."""
    text = str(unit or "").strip().lower()
    scales: set[tuple[str, float]] = {_UNIT_SCALE[t] for t in re.findall(r"[a-z]+", text) if t in _UNIT_SCALE}
    if re.search(r"'000", text):
        scales.add(_UNIT_SCALE["thousand"])
    if len(scales) > 1:
        return "unknown", 1.0
    if scales:
        return scales.pop()
    if text in ("%", "pct", "percent", "percentage"):
        return "pct", 1.0
    if text in ("ratio", "times", "x"):
        return "ratio", 1.0
    if "per share" in text or "per_share" in text:
        return "inr_per_share", 1.0
    if text in ("rs", "inr", "rupees", "rs."):
        return "inr", 1.0
    return text or "unknown", 1.0


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _concatenated_value(value: float, value_raw: str | None, value_check: str | None) -> bool:
    """True for an unverified fact whose number is two printed numbers glued together (T-088).

    ``value_raw`` "9,176 (FY26); 8,227 (FY25)" produced 917,626,822,725 in ar_facts; the value matches neither
    printed number, so it is a concatenation, not a figure.  Only ``value_check='not_found'`` rows are judged:
    a row whose value was found on its page is kept as filed."""
    if (value_check or "") != "not_found":
        return False
    printed = [float(re.sub(r"[,]", "", m)) for m in _NUMBER.findall(str(value_raw or ""))]
    return len(printed) >= 2 and not any(abs(float(value) - v) <= max(1e-6, 1e-6 * abs(v)) for v in printed)


def _statement_basis(text: str) -> str | None:
    """Consolidated or standalone from a financial-statement page's own wording ("the Company" / "the Group")."""
    company = len(re.findall(r"\bthe Company\b", text, re.I))
    group = len(re.findall(r"\bthe Group\b", text, re.I))
    if group and group > company:
        return "consolidated"
    if company and company > group:
        return "standalone"
    return None


def _ar_page_bases(spec: dict, symbol: str):
    """``(basis_of(doc_id, page), close)`` reading pages.db: the page's statement wording decides the basis.

    ``ar_facts.basis`` says consolidated for both the standalone and the consolidated lease-liability note of the
    same annual report (T-088: INFY 3,749 stored as consolidated beside the consolidated 9,176).  The page text
    holds the evidence ("The Company ..." / "The Group ..."), so it overrides the stored basis when it speaks."""
    try:
        rows, _ = prepare._read_sqlite(spec["db"], "ar_docs", "SELECT doc_id, sha256 FROM ar_docs WHERE symbol=?",
                                       (symbol,))
    except Exception:
        return (lambda _doc, _page: None), (lambda: None)
    path = profile.pages_db()
    if not path or not Path(path).is_file():
        return (lambda _doc, _page: None), (lambda: None)
    pg = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=30)
    sha_key = {sha: key for key, sha in pg.execute("SELECT doc_key, sha256 FROM doc WHERE symbol=?", (symbol,))}
    doc_key = {str(doc_id): sha_key.get(sha) for doc_id, sha in rows}
    cache: dict[tuple[str, int], str | None] = {}

    def basis_of(doc_id, page) -> str | None:
        key = doc_key.get(str(doc_id))
        if not key or not page:
            return None
        if (key, int(page)) not in cache:
            row = pg.execute("SELECT text FROM doc_page WHERE doc_key=? AND page=?", (key, int(page))).fetchone()
            cache[(key, int(page))] = _statement_basis(row[0]) if row and row[0] else None
        return cache[(key, int(page))]

    return basis_of, pg.close


def _fy_label(period: object, fiscal_year: object) -> str | None:
    """The FY label an ar_facts row is stored under: its period column, else the March year-end it files."""
    fy = str(period or "")
    m = re.fullmatch(r"FY(?:20)?(\d\d)", fy)
    if m:
        return "FY" + m.group(1)
    m = re.match(r"(\d{4})-03-31", str(fiscal_year or ""))
    return "FY" + m.group(1)[2:] if m else None


# The forms an annual report prints a column's own year in (T-115).  The range is read before the label so
# "FY 2021-22" ends in 2022; the dash may be U+2010..U+2015 or U+2212 in the text layer, and "FY'20" has an
# apostrophe instead of a space.
_FY_RANGE = re.compile(r"(?<!\d)(\d{4})\s?[-\u2010-\u2015\u2212]\s?(\d{2}|\d{4})(?!\d)")
_FY_LABEL = re.compile(r"\bfy\s?'?(\d{4}|\d{2})(?!\d)", re.I)


def _quote_fy(quote: object, value: float | None) -> str | None:
    """The fiscal year a quote prints for this row's own value, or None (T-115).

    A history table prints the year of its column ("FY 2021-22 106,342", "1,26,676 FY2024") while
    ``ar_facts.period`` holds the report's own year: exactly one year in the quote beside this row's printed number
    is that column's year.  Two or more years (a comparative sentence), no year, or a quote that does not print this
    value cannot tell the column, so the stored period is kept."""
    text = str(quote or "")
    years: set[int] = set()
    for m in _FY_RANGE.finditer(text):
        start, end = int(m.group(1)), m.group(2)
        if len(end) == 4:
            if int(end) == start + 1:
                years.add(int(end) % 100)
        elif end == f"{(start + 1) % 100:02d}":
            years.add((start + 1) % 100)
    spans = _FY_RANGE.sub(" ", text)
    for m in _FY_LABEL.finditer(spans):
        years.add(int(m.group(1)) % 100)
    if len(years) != 1 or value is None:
        return None
    printed = _FY_LABEL.sub(" ", spans)
    for m in _NUMBER.finditer(printed):
        raw = m.group(0).replace(",", "")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if abs(float(raw) - abs(value)) <= 0.5 * 10 ** -decimals + 1e-9 * abs(value):
            return f"FY{years.pop():02d}"
    return None


def _amount_key(value: float, scale: float) -> float:
    """The rupee amount at 0.1 % precision: two printings of one figure ("rs mn" and "inr_million") collapse."""
    amount = value * scale
    return float(f"{amount:.3g}") if amount else 0.0


def _annual_rows(symbol: str, rows: list[dict], basis_of, source_db: str) -> list[tuple]:
    """The fin_annual_line rows of one company's ar_facts rows (T-115).

    Only a closed caption lexicon's lines are kept; the quote's own year and the unit's own scale are applied, and
    one row per (isin, year, basis, line, rupee amount, document) survives."""
    out, seen = [], set()
    for r in rows:
        hit = lexicon_item(r["item"])
        if not hit or r["value"] is None:
            continue
        basis = str(r["basis"] or "").lower()
        if basis not in ("consolidated", "standalone"):
            basis = "not_stated"
        if _concatenated_value(float(r["value"]), r.get("value_raw"), r.get("value_check")):
            continue             # a value glued from two printed numbers is not a figure (T-088)
        page_basis = basis_of(r["doc_id"], r["page"])
        if page_basis:
            basis = page_basis
        fy = _fy_label(r["period"], r["fiscal_year"])
        if fy is None:
            continue
        fy = _quote_fy(r["quote"], float(r["value"])) or fy
        unit, scale = _unit(r["unit"])
        key = (r["isin"], fy, basis, hit[0], _amount_key(float(r["value"]), scale), str(r["doc_id"]))
        if key in seen:
            continue             # the same figure printed twice in one document (a table and its summary)
        seen.add(key)
        definition = "company_stated" if hit[0] in COMPANY_STATED else "reported"
        out.append((symbol, r["isin"], fy, f"20{fy[2:]}-03-31", basis, hit[1], hit[0], r["item"],
                    float(r["value"]), unit, scale, str(r["doc_id"]), r["page"], r["quote"], source_db,
                    "ar_facts", str(r["src_rowid"]), r["known_at"], "ar_facts.filed_at", 1, 0, definition, "FY"))
    return out


def build_annual(conn: sqlite3.Connection) -> dict:
    """fin_annual_line: statement-caption rows picked out of ar_facts by a closed lexicon (no PDF reading)."""
    schema.create(conn, ("fin_annual_line",))
    counts = {}
    for symbol in profile.symbols():
        spec = _spec(symbol, "ar_facts")
        sql = spec["sql"].replace("SELECT *,", "SELECT rowid AS src_rowid, *,", 1)
        rows, types = prepare._read_sqlite(spec["db"], spec["source"], sql, spec["params"])
        cols = list(types)
        basis_of, close_pages = _ar_page_bases(spec, symbol)
        try:
            out = _annual_rows(symbol, [dict(zip(cols, raw)) for raw in rows], basis_of, spec["db"])
        finally:
            close_pages()
        conn.executemany("INSERT INTO fin_annual_line VALUES (" + ",".join("?" * 23) + ")", out)
        counts[symbol] = len(out)
    conn.commit()
    return counts


# --- price_delivery ---------------------------------------------------------------------------------
def build_prices(conn: sqlite3.Connection) -> dict:
    """Daily OHLC, volume, delivery and split-adjusted close on both exchanges (truth snapshot)."""
    schema.create(conn, ("price_delivery",))
    counts = {}
    for symbol in profile.symbols():
        marks, isins = _isin_marks(symbol)
        n = 0
        for exch, table in (("NSE", "px_nse_adj"), ("BSE", "px_bse_adj")):
            rows, _ = _duck(
                f"SELECT isin, CAST(date AS VARCHAR), open, high, low, close, prev_close, volume, value_inr, "
                f"num_trades, deliverable_qty, delivery_pct, cum_price_factor, adj_close FROM {table} "
                f"WHERE isin IN ({marks}) ORDER BY date", isins)
            conn.executemany("INSERT INTO price_delivery VALUES (" + ",".join("?" * 21) + ")",
                             [(symbol, r[0], exch, r[1], *r[2:14], r[1], "bhavcopy date (end of day)",
                               "truth snapshot", table, f"{r[0]}|{r[1]}") for r in rows])
            n += len(rows)
        counts[symbol] = n
    conn.commit()
    return counts


# --- shp_category -----------------------------------------------------------------------------------
MEMBERS = {
    "ShareholdingOfPromoterAndPromoterGroup": "promoter", "PublicShareholding": "public",
    "MutualFundsOrUti": "mutual_funds", "InsuranceCompanies": "insurance", "Banks": "banks",
    "AlternativeInvestmentFunds": "aif", "ForeignPortfolioInvestor": "fpi",
    "InstitutionsForeignPortfolioInvestorCatergoryOne": "fpi_category_1",
    "InstitutionsForeignPortfolioInvestorCatergoryTwo": "fpi_category_2",
    "ProvidentFundsOrPensionFunds": "pension_funds", "NBFCsRegisteredWithRbi": "nbfc",
    "InstitutionsDomestic": "institutions_domestic", "InstitutionsForeign": "institutions_foreign",
    "NonInstitutions": "non_institutions", "BodiesCorporate": "bodies_corporate",
    "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh": "retail_up_to_2_lakh",
    "ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh": "retail_above_2_lakh",
    "NonResidentIndians": "nri", "IndividualsOrHinduUndividedFamily": "promoter_individuals",
    "SharesHeldByNonPromoterNonPublicShareholders": "non_promoter_non_public",
    "ForeignInstitutions": "foreign_institutions", "ForeignCompanies": "foreign_companies",
    # 2025-05 taxonomy spellings
    "MutualFundsOrUTI": "mutual_funds", "NBFCsRegisteredWithRBI": "nbfc",
    "InstitutionsForeignPortfolioInvestorCategoryOne": "fpi_category_1",
    "InstitutionsForeignPortfolioInvestorCategoryTwo": "fpi_category_2",
}


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
# Every tag of one category context the build keeps: the holding itself and the encumbrance block beside it.
CATEGORY_TAGS = ("NumberOfShares", PCT, "NumberOfShareholders",
                 "PledgedOrEncumberedNumberOfShares", "PledgedOrEncumberedSharesHeldAsPercentageOfTotalNumberOfShares",
                 "NumberOfSharesEncumberedUnderPledged", "EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares",
                 "NumberOfSharesEncumbered", "EncumberedSharesHeldAsPercentageOfTotalNumberOfShares",
                 "NumberOfSharesEncumberedUnderOtherEncumbrances",
                 "EncumberedShareUnderOtherEncumbrancesAsPercentageOfTotalNumberOfShares")
PCT_TAGS = frozenset((PCT, "PledgedOrEncumberedSharesHeldAsPercentageOfTotalNumberOfShares",
                      "EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares",
                      "EncumberedSharesHeldAsPercentageOfTotalNumberOfShares",
                      "EncumberedShareUnderOtherEncumbrancesAsPercentageOfTotalNumberOfShares",
                      "PercentageOfShareholdingByPAC"))
HOLDER_TAGS = ("NameOfTheShareholder", "NameOfThePAC", "NumberOfShares", PCT, "NumberOfShareholders",
               "PercentageOfShareholdingByPAC", "NumberOfSharesEncumberedUnderPledged",
               "PledgedOrEncumberedNumberOfShares")
# The detail axes carry the member name of the category ("DetailsOfSharesHeldByBodiesCorporateAxis"); a few
# spellings differ from the CategoryOfShareholdersAxis member of the same category, so map those to its name.
DETAIL_MEMBERS = {"IndividualsOrHUF": "promoter_individuals",
                  "IndividualsOrHinduUndividedFamily": "promoter_individuals",
                  "InstitutionsForeignPortfolioInvestorOne": "fpi_category_1",
                  "InstitutionsForeignPortfolioInvestorTwo": "fpi_category_2"}
DETAIL_AXIS = re.compile(r"^Details(?:Of)?SharesHeldBy(.+)Axis$")
PAC_AXIS = re.compile(r"^Details(?:Of)?TheShareholdersActingAsPersonsInConcertFor(.+)Axis$")
PAC_MEMBERS = {"Public": "public", "PromoterAndPromoterGroup": "promoter",
               "NonPromoterNonPublic": "non_promoter_non_public"}


def _holder_category(axis: str) -> str | None:
    """The shp_category name a named-holder axis belongs to (``pac_*`` for a persons-in-concert disclosure), or
    None for an axis that names no holder (significant beneficial owners, unclaimed shares ...)."""
    m = DETAIL_AXIS.match(axis)
    if m:
        member = m.group(1)
        return DETAIL_MEMBERS.get(member) or MEMBERS.get(member) or _snake(member)
    m = PAC_AXIS.match(axis)
    if m:
        bucket = m.group(1)
        return "pac_" + PAC_MEMBERS.get(bucket, _snake(bucket))
    return None


def _num(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_shp_xbrl(blob: bytes) -> dict:
    """Header, per-category facts, named holders and the promoter-encumbrance block of one SHP XBRL file, stdlib
    only.  ``facts`` is keyed ``(member, instant)``; ``holders`` is keyed by the holder axis and the filing's own
    holder id, because ``NameOfTheShareholder`` sits in a ``D_`` context while its counts sit in the bare one, both
    carrying the same typed member."""
    root = ET.fromstring(blob)
    ctx: dict[str, tuple] = {}
    head: dict[str, str] = {}
    for el in root:
        tag = _local(el.tag)
        if tag == "context":
            dims, inst = [], None
            for sub in el.iter():
                t = _local(sub.tag)
                if t == "explicitMember":
                    dims.append((sub.get("dimension", "").split(":")[-1], (sub.text or "").split(":")[-1]))
                elif t == "typedMember":
                    dims.append((sub.get("dimension", "").split(":")[-1], "".join(sub.itertext()).strip()))
                elif t == "instant":
                    inst = sub.text
                elif t == "endDate" and inst is None:
                    inst = sub.text
            if el.get("id"):
                ctx[el.get("id") or ""] = (tuple(dims), inst)
        elif tag in ("ISIN", "Symbol", "DateOfReport") and el.text:
            head[tag] = el.text.strip()
    facts: dict[tuple, dict] = {}
    holders: dict[tuple, dict] = {}
    pledge: dict[str, str] = {}
    for el in root:
        tag, ref = _local(el.tag), el.get("contextRef")
        if not ref or ref not in ctx:
            continue
        dims, inst = ctx[ref]
        value = (el.text or "").strip()
        if tag.startswith("WhetherAnySharesHeldByPromotersAre"):
            if not dims:
                pledge[tag] = value
        elif tag in CATEGORY_TAGS and len(dims) == 1 and dims[0][0] == "CategoryOfShareholdersAxis":
            number = _num(value)
            if number is not None:
                facts.setdefault((dims[0][1].removesuffix("Member"), inst), {})[tag] = number
        elif tag in HOLDER_TAGS and len(dims) == 1 and _holder_category(dims[0][0]):
            holder = holders.setdefault(dims[0], {})
            number = _num(value)
            if number is not None:
                holder[tag] = number
            elif tag in ("NameOfTheShareholder", "NameOfThePAC"):
                holder[tag] = value
    # The 2025-05 taxonomy files give percentages as fractions (0.5467), older ones as percent (54.67):
    # promoter + public always total 100%, so a total near 1 marks a fractional file.
    fractional = any(0 < sum(facts.get((m, inst), {}).get(PCT, 0.0)
                             for m in ("ShareholdingOfPromoterAndPromoterGroup", "PublicShareholding")) <= 1.5
                     for inst in {i for (_m, i) in facts})
    if fractional:
        for f in (*facts.values(), *holders.values()):
            for k in PCT_TAGS.intersection(f):
                f[k] = round(f[k] * 100.0, 6)
    return {"head": head, "facts": facts, "holders": holders, "pledge": pledge}


def _quarter(parsed: dict) -> str | None:
    """The quarter end a parsed file reports: its instant (every fact of one file shares it), else the head date."""
    instants = {i for (_m, i) in parsed["facts"] if i}
    return max(instants) if instants else parsed["head"].get("DateOfReport")


def _flag(value: str | None) -> int | None:
    return None if value is None else int(value.strip().lower() in ("true", "1", "yes"))


def _pct_base(parsed: dict) -> tuple[float | None, str | None]:
    """``(shares, label)`` the file's printed percentages are on.

    The base is the total shareholding pattern less the shares a depository holds against depository receipts
    (``CustodianOrDRHolder``): INFY at 2026-09-30 prints promoter 13.90% for 516,677,914 shares, which is 13.90% of
    3,716,041,606 (4,058,276,578 less 342,234,972 under ADRs) and 12.73% of the total.  The choice is checked
    against every category the file prints a percentage for; no file of the 591-file corpus fails both checks."""
    quarter = _quarter(parsed)
    total = (parsed["facts"].get(("ShareholdingPattern", quarter)) or {}).get("NumberOfShares")
    if not total:
        return None, None
    custodian = (parsed["facts"].get(("CustodianOrDRHolder", quarter)) or {}).get("NumberOfShares") or 0.0
    candidates = [("total_shares", total)]
    if 0 < custodian < total:
        candidates.insert(0, ("total_excluding_dr_custody", total - custodian))
    for label, base in candidates:
        bad = 0
        for (member, inst), f in parsed["facts"].items():
            pct, shares = f.get(PCT), f.get("NumberOfShares")
            if inst != quarter or member == "ShareholdingPattern" or not pct or not shares or shares <= 0:
                continue
            if abs(pct - shares / base * 100.0) > 0.011:
                bad += 1
        if not bad:
            return base, label
    return candidates[0][1], candidates[0][0]


def build_shp(conn: sqlite3.Connection) -> dict:
    """shp_category (shp_index promoter / public per quarter + the holder categories of every SHP XBRL file),
    shp_holder (the named holders, one row per category and name per quarter) and shp_pledge (the promoter
    encumbrance block), each carrying the file's own ``known_at`` and the percentage base it prints on."""
    schema.create(conn, ("shp_category", "shp_holder", "shp_pledge"))
    counts, xbrl_files = {}, {}
    if SHP_XBRL.is_dir():
        for path in sorted(SHP_XBRL.glob("*.xml.gz")):
            xbrl_files[path.name[:-3]] = path
    if not xbrl_files:   # 8 Nov: raw moved to Drive, the folder was empty and pledge/holder tables came out empty
        print(f"WARNING build_shp: no SHP XBRL files in {SHP_XBRL}; shp_holder and shp_pledge will be empty "
              "(fetch gdrive:InfoDiffusion_archive/msi_raw/raw/nse_shp_xbrl_pilot first)", file=sys.stderr)
    parsed_files ={name: parse_shp_xbrl(gzip.open(path).read()) for name, path in xbrl_files.items()}
    bases = {}
    for parsed in parsed_files.values():
        if _quarter(parsed):
            bases[(parsed["head"].get("ISIN"), _quarter(parsed))] = _pct_base(parsed)
    for symbol in profile.symbols():
        index = fetch(symbol, "shp_index")
        by_file = {r["file"]: r for r in index}
        out = []
        for r in index:
            known = r["broadcast_at"] or r["submission_date"]
            for cat, pct in (("promoter", r["promoter_pct"]), ("public", r["public_pct"])):
                if pct is None:
                    continue
                out.append((symbol, r["isin"], r["quarter_end"], cat, cat, None, pct, None, "pct", "index",
                            r["file"], "equity_intelligence.db", "shp_index", r["record_id"],
                            r["revised"], known, "shp_index.broadcast_at", 1,
                            *bases.get((r["isin"], r["quarter_end"]), (None, None))))
        holders: dict[tuple, tuple] = {}
        pledges: dict[tuple, tuple] = {}
        isins = set(all_isins(symbol))
        for name, parsed in parsed_files.items():
            if parsed["head"].get("ISIN") not in isins:
                continue
            idx = by_file.get(name)
            if idx is not None:
                known, src, revised = idx["broadcast_at"] or idx["submission_date"], "shp_index.broadcast_at", idx["revised"]
            else:
                stamp = re.search(r"_(\d{14})_WEB", name)
                known = datetime.strptime(stamp.group(1), "%d%m%Y%H%M%S").isoformat() if stamp else None
                src, revised = "file name timestamp", None
            isin, quarter = parsed["head"]["ISIN"], _quarter(parsed)
            base, base_label = bases.get((isin, quarter), (None, None))
            fpi, ifor = {}, {}
            for (member, inst), f in parsed["facts"].items():
                if member == "InstitutionsForeign":
                    ifor[inst] = f
                cat = MEMBERS.get(member, _snake(member))
                out.append((symbol, isin, inst, cat, member, f.get("NumberOfShares"),
                            f.get(PCT), f.get("NumberOfShareholders"),
                            "pct", "xbrl", name, "nse_shp_xbrl_pilot", "xml.gz", name, revised, known, src, 1,
                            base, base_label))
                if cat.startswith("fpi"):
                    fpi[(cat, inst)] = f
            for inst, f in ifor.items():  # new taxonomy: the pattern's own FII / FPI line (all foreign institutions)
                if ("fpi", inst) in fpi:
                    continue
                out.append((symbol, isin, inst, "fpi_total", "InstitutionsForeign (FII/FPI line)",
                            f.get("NumberOfShares"), f.get(PCT), None,
                            "pct", "xbrl", name, "nse_shp_xbrl_pilot", "xml.gz", name, revised, known, src, 1,
                            base, base_label))
            for inst in {i for (_c, i) in fpi} - {i for i in ifor if ("fpi", i) not in fpi}:
                pick = [fpi[k] for k in fpi if k[1] == inst and k[0] == "fpi"] or \
                       [fpi[k] for k in fpi if k[1] == inst and k[0] in ("fpi_category_1", "fpi_category_2")]
                if pick:
                    out.append((symbol, isin, inst, "fpi_total", "FPI (derived: sum of FPI members)",
                                sum(p.get("NumberOfShares") or 0 for p in pick),
                                sum(p.get(PCT) or 0 for p in pick),
                                None, "pct", "xbrl", name, "nse_shp_xbrl_pilot", "xml.gz", name, revised, known, src, 0,
                                base, base_label))
            for (axis, _domain), f in parsed["holders"].items():
                cat, holder = _holder_category(axis), f.get("NameOfTheShareholder")
                if not cat or not holder:
                    continue
                pac_pct = f.get("PercentageOfShareholdingByPAC")
                row = (symbol, isin, quarter, cat, holder, f.get("NumberOfShares"),
                       f.get(PCT, pac_pct), f.get("NumberOfShareholders"), f.get("NameOfThePAC"), pac_pct,
                       f.get("NumberOfSharesEncumberedUnderPledged", f.get("PledgedOrEncumberedNumberOfShares")),
                       name, "nse_shp_xbrl_pilot", "xml.gz", known, src)
                key = (isin, quarter, cat, holder)
                if key not in holders or (holders[key][14] or "") <= (known or ""):
                    holders[key] = row
            flags = parsed["pledge"]
            promoter = parsed["facts"].get(("ShareholdingOfPromoterAndPromoterGroup", quarter)) or {}
            pledge_flag = _flag(flags.get("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged")
                                if "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged" in flags else
                                flags.get("WhetherAnySharesHeldByPromotersArePledgeOrOtherwiseEncumbered"))
            pledged = promoter.get("NumberOfSharesEncumberedUnderPledged")
            if pledged is None:
                pledged = promoter.get("PledgedOrEncumberedNumberOfShares")
            if pledged is None and pledge_flag == 0:
                pledged = promoter.get("NumberOfSharesEncumbered")
            pledged_pct = promoter.get("EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares")
            if pledged_pct is None:
                pledged_pct = promoter.get("PledgedOrEncumberedSharesHeldAsPercentageOfTotalNumberOfShares")
            row = (symbol, isin, quarter, pledge_flag,
                   _flag(flags.get("WhetherAnySharesHeldByPromotersAreEncumberedUnderNonDisposalUndertaking")),
                   _flag(flags.get("WhetherAnySharesHeldByPromotersAreEncumberedOtherThanByWayOfPledgeOrNDU")),
                   promoter.get("NumberOfShares"), pledged, pledged_pct,
                   promoter.get("NumberOfSharesEncumberedUnderOtherEncumbrances"),
                   promoter.get("NumberOfSharesEncumbered"), name, known, src)
            key = (isin, quarter)
            if key not in pledges or (pledges[key][12] or "") <= (known or ""):
                pledges[key] = row
        conn.executemany("INSERT INTO shp_category VALUES (" + ",".join("?" * 20) + ")", out)
        conn.executemany("INSERT INTO shp_holder VALUES (" + ",".join("?" * 16) + ")", list(holders.values()))
        conn.executemany("INSERT INTO shp_pledge VALUES (" + ",".join("?" * 14) + ")", list(pledges.values()))
        counts[symbol] = len(out)
    conn.commit()
    return counts


# --- share count from the shareholding pattern ---------------------------------------------------------
def build_share_fallback(conn: sqlite3.Connection) -> dict:
    """The exact share count of every quarter end, from the total of its shareholding pattern: the
    ``shareholding_pattern`` row of ``shp_category`` with the SHP's own ``known_at``.  One row per basis the company
    reports, written even where the results filing also gave paid-up capital (T-073): the pattern count is exact,
    the paid-up/face-value division is rounded, so the ratio that needs a share count prefers the pattern row and
    keeps the paid-up one only as a fallback."""
    counts = {}
    for symbol in profile.symbols():
        bases = [r[0] for r in conn.execute("SELECT DISTINCT basis FROM fin_quarter_xbrl WHERE symbol=?", (symbol,))]
        have = {(r[0], r[1]) for r in conn.execute(
            "SELECT as_of_date, basis FROM share_capital WHERE symbol=? AND event IS NULL "
            "AND source_table='shp_category'", (symbol,))}
        n = 0
        for isin, quarter_end, shares, known, name, rowid in conn.execute(
                "SELECT isin, quarter_end, shares, known_at, source_file, rowid FROM shp_category WHERE symbol=? "
                "AND category='shareholding_pattern' AND source_kind='xbrl' AND shares IS NOT NULL AND shares > 0 "
                "AND known_at IS NOT NULL ORDER BY quarter_end, known_at", (symbol,)).fetchall():
            for basis in bases:
                if (quarter_end, basis) in have:
                    continue
                conn.execute("INSERT INTO share_capital VALUES (" + ",".join("?" * 18) + ")",
                             (symbol, isin, quarter_end, basis, None, None, shares, None, None, "shares", 1.0, known,
                              "shp_category.known_at (shareholding pattern total)", "pilot3.db", "shp_category",
                              f"{name}#{rowid}", None, None))
                have.add((quarter_end, basis))
                n += 1
        counts[symbol] = n
    conn.commit()
    return counts


# --- deals, insider trades, index prices -----------------------------------------------------------------
EQUITY_DB = "equity_intelligence.db"


def build_deals(conn: sqlite3.Connection) -> dict:
    """bulk_block_deal from ``equity_intelligence.db.bulk_block_deals``, read by ISIN (every ISIN the company has had).
    A company with no deals has no rows; ``known_at`` is the deal date."""
    schema.create(conn, ("bulk_block_deal",))
    start, counts = profile.window_start() or "0000-00-00", {}
    for symbol in profile.symbols():
        marks, isins = _isin_marks(symbol)
        rows, _ = prepare._read_sqlite(
            EQUITY_DB, "bulk_block_deals",
            f"SELECT id, isin, CAST(deal_date AS TEXT), client_name, deal_type, buy_sell, quantity, trade_price, exchange, "
            f"is_marquee_institution FROM bulk_block_deals WHERE isin IN ({marks}) AND deal_date >= ? ORDER BY deal_date, id",
            (*isins, start))
        conn.executemany("INSERT INTO bulk_block_deal VALUES (" + ",".join("?" * 15) + ")",
                         [(symbol, r[1], r[2][:10], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[2][:10],
                           "deal_date (end of day)", EQUITY_DB, "bulk_block_deals", r[0]) for r in rows])
        counts[symbol] = len(rows)
    conn.commit()
    return counts


def build_insiders(conn: sqlite3.Connection) -> dict:
    """insider_trade from ``equity_intelligence.db.insider_trades_v2`` by ISIN, superseded rows dropped."""
    schema.create(conn, ("insider_trade",))
    start, counts = profile.window_start() or "0000-00-00", {}
    for symbol in profile.symbols():
        marks, isins = _isin_marks(symbol)
        rows, _ = prepare._read_sqlite(
            EQUITY_DB, "insider_trades_v2",
            f"SELECT source, source_key, isin, person_name, person_category, transaction_type, mode, security_type, qty, "
            f"value_inr, before_pct, after_pct, trade_from, trade_to, intimation_date, known_at FROM insider_trades_v2 "
            f"WHERE isin IN ({marks}) AND coalesce(is_superseded, 0) = 0 AND intimation_date >= ? "
            f"ORDER BY intimation_date, source_key", (*isins, start))
        conn.executemany("INSERT INTO insider_trade VALUES (" + ",".join("?" * 21) + ")",
                         [(symbol, r[2], r[0], r[1], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12], r[13],
                           r[14], r[15] or r[14], "insider_trades_v2.known_at|intimation_date", EQUITY_DB,
                           "insider_trades_v2", f"{r[0]}:{r[1]}") for r in rows])
        counts[symbol] = len(rows)
    conn.commit()
    return counts


LOOKBACK_MONTHS = (("1m", 1), ("3m", 3), ("6m", 6), ("12m", 12))


def _months_before(day: str, months: int) -> str:
    y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
    m -= months
    while m <= 0:
        m, y = m + 12, y - 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return f"{y:04d}-{m:02d}-{min(d, last):02d}"


def build_index_prices(conn: sqlite3.Connection) -> dict:
    """index_price: the stock against each index per trading day, from ``mkt_nse_index_daily`` and the NSE
    ``price_delivery`` rows.  Returns use the split-adjusted close of the stock (``adj_close``) and the index close;
    the lookback day is the last trading day on or before the date N calendar months back, and a return is null
    when that day falls before the earliest day the build keeps (``compute_start``, else ``window_start``).
    ``relative_return_*`` = stock return - index return, in percentage points.  Indices: ``Nifty 50`` plus the
    profile's ``extra_indices``."""
    schema.create(conn, ("index_price",))
    start = profile.window_start() or "0000-00-00"
    earliest = profile.compute_start() or start
    names = ("Nifty 50", *[n for n in profile.extra_indices() if n != "Nifty 50"])
    series = {}
    for name in names:
        rows, _ = prepare._read_sqlite(EQUITY_DB, "mkt_nse_index_daily",
                                       "SELECT date, close FROM mkt_nse_index_daily WHERE index_name=? AND close IS NOT NULL "
                                       "ORDER BY date", (name,))
        series[name] = ([r[0] for r in rows], [r[1] for r in rows])

    def at(days: list, values: list, day: str):
        i = bisect_right(days, day) - 1
        return values[i] if i >= 0 else None

    counts = {}
    for symbol in profile.symbols():
        px = conn.execute("SELECT date, close, adj_close, isin, rowid FROM price_delivery WHERE symbol=? AND exchange='NSE' "
                          "AND adj_close IS NOT NULL ORDER BY date", (symbol,)).fetchall()
        pdays, padj = [r[0] for r in px], [r[2] for r in px]
        out = []
        for name, (idays, icl) in series.items():
            for day, close, adj, isin, rowid in px:
                if day < start:
                    continue
                index_close = at(idays, icl, day)
                if index_close is None or idays[bisect_right(idays, day) - 1] != day:
                    continue  # no index print that day
                stock_ret, index_ret, rel = [], [], []
                for _tag, months in LOOKBACK_MONTHS:
                    target = _months_before(day, months)
                    base_s, base_i = at(pdays, padj, target), at(idays, icl, target)
                    if target < earliest or not base_s or not base_i:
                        stock_ret.append(None), index_ret.append(None), rel.append(None)
                        continue
                    s_r, i_r = 100.0 * (adj / base_s - 1.0), 100.0 * (index_close / base_i - 1.0)
                    stock_ret.append(s_r), index_ret.append(i_r), rel.append(s_r - i_r)
                out.append((symbol, isin, name, day, index_close, close, adj, *stock_ret, *index_ret, *rel, day,
                            "price date (end of day)", f"{EQUITY_DB}+truth snapshot", "mkt_nse_index_daily+px_nse_adj",
                            f"{name}|{day}|pd#{rowid}"))
        conn.executemany("INSERT INTO index_price VALUES (" + ",".join("?" * 24) + ")", out)
        counts[symbol] = len(out)
    conn.commit()
    return counts


def build_stores(conn: sqlite3.Connection) -> dict:
    result = {"quarterly": build_quarterly(conn)}
    result["corporate_events"] = build_corporate_events(conn)
    result["fin_annual_line"] = build_annual(conn)
    from reality_engine.pilot3 import statements  # after build_annual: it appends rows to fin_annual_line

    result["statements"] = statements.build_statements(conn)
    result["price_delivery"] = build_prices(conn)
    result["shp_category"] = build_shp(conn)
    if profile.under_profile():  # without a profile the three-company build stays exactly as it was
        result["share_capital_from_shp"] = build_share_fallback(conn)
        result["bulk_block_deal"] = build_deals(conn)
        result["insider_trade"] = build_insiders(conn)
        result["index_price"] = build_index_prices(conn)
    result["window"] = apply_window(conn)
    conn.commit()
    return result
