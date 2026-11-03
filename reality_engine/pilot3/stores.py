"""Structured stores into the pilot3 tables: share_capital, fin_quarter_xbrl, fin_annual_line,
price_delivery, shp_category.  Rows are read through the gap loop's own copy specs
(``gap_loop.prepare.store_copies``) widened to every ISIN the symbol has had; ``known_at`` always comes from
the filing record the store carries.  No model, no network."""
from __future__ import annotations

import dataclasses
import gzip
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date, datetime

from reality_engine.gap_loop import prepare
from reality_engine.pilot3 import SHP_XBRL, profile, schema
from reality_engine.pilot3.registry import all_isins, isin_history

CR = 1e7  # rupees per crore

# The history window a profile keeps (T-056): every store table and its date column.  No profile -> no filter.
WINDOW_COLUMNS = {"fin_quarter_xbrl": "period_end", "fin_annual_line": "period_end", "shp_category": "quarter_end",
                  "price_delivery": "date", "valuation_daily": "date"}


def apply_window(conn: sqlite3.Connection) -> dict:
    """Delete a profile's rows dated before ``window_start``; returns ``{table: rows deleted}``."""
    start = profile.window_start()
    if not start:
        return {}
    return {table: conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (start,)).rowcount
            for table, column in WINDOW_COLUMNS.items()
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone()}


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
QUARTER_TAGS = {  # XBRL element -> (canonical line item, statement, unit)
    "RevenueFromOperations": ("revenue_from_operations", "P&L", "inr"),
    "OtherIncome": ("other_income", "P&L", "inr"),
    "Income": ("total_income", "P&L", "inr"),
    "CostOfMaterialsConsumed": ("cost_of_materials", "P&L", "inr"),
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


EXTRA_QUARTER_TAGS = {  # facts the `quarterly` view lacks (NBFC / lender P&L), read from results_xbrl.facts
    "InterestEarned": ("interest_income", "P&L", "inr"),
    "ImpairmentOnFinancialInstruments": ("impairment_financial_instruments", "P&L", "inr"),
    "FeesAndCommissionIncome": ("fee_commission_income", "P&L", "inr"),
    "FeesAndCommissionExpense": ("fee_commission_expense", "P&L", "inr"),
    "NetGainOnFairValueChanges": ("net_gain_fair_value", "P&L", "inr"),
}


def _quarter_extras(symbol: str, meta: dict[str, tuple]) -> list[tuple]:
    """NBFC fields per quarter (``meta``: file -> the filing's columns) plus net interest income =
    interest earned - finance costs, a derived row (``is_reported`` 0) wherever both were filed."""
    if not meta:
        return []
    tags = tuple(EXTRA_QUARTER_TAGS) + ("FinanceCosts",)
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
    for (file, tag), (value, rowid) in got.items():
        if tag not in EXTRA_QUARTER_TAGS:
            continue
        isin, start, end, period, basis, audited, known = meta[file]
        item, statement, unit = EXTRA_QUARTER_TAGS[tag]
        out.append((symbol, isin, start, end, period, basis, audited, statement, item, tag, value, unit, 1.0, file,
                    "results_xbrl.db", "facts", f"{file}#{rowid}", known,
                    "results_xbrl.quarterly.dissem_ts|broadcast_ts", 1))
    for file, (isin, start, end, period, basis, audited, known) in meta.items():
        earned, fin = got.get((file, "InterestEarned")), got.get((file, "FinanceCosts"))
        if earned and fin:
            out.append((symbol, isin, start, end, period, basis, audited, "P&L", "net_interest_income",
                        "InterestEarned-FinanceCosts", earned[0] - fin[0], "inr", 1.0, file, "results_xbrl.db", "facts",
                        f"{file}#{earned[1]}-{fin[1]}", known, "results_xbrl.quarterly.dissem_ts|broadcast_ts", 0))
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
                           "quarterly", r["file"], r["known_at"], "results_xbrl.quarterly.dissem_ts|broadcast_ts", 1))
            paid, face = r.get("PaidUpValueOfEquityShareCapital"), r.get("FaceValueOfEquityShareCapital")
            if paid and face:
                sc.append((symbol, r["isin"], r["period_end"], basis, None, None, paid / face, paid, face, "shares",
                           1.0, r["known_at"], "results_xbrl.quarterly.dissem_ts|broadcast_ts", "results_xbrl.db",
                           "quarterly", r["file"], None, None))
        fq += _quarter_extras(symbol, meta)
        conn.executemany("INSERT INTO fin_quarter_xbrl VALUES (" + ",".join("?" * 20) + ")", fq)
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


def _unit(unit: object) -> tuple[str, float]:
    text = str(unit or "").strip().lower()
    if "crore" in text:
        return "inr_crore", CR
    if "million" in text or text in ("mn", "rs million"):
        return "inr_million", 1e6
    if text in ("%", "pct", "percent"):
        return "pct", 1.0
    if text in ("rs", "inr", "rupees", "rs."):
        return "inr", 1.0
    if "per share" in text:
        return "inr_per_share", 1.0
    return text or "unknown", 1.0


def build_annual(conn: sqlite3.Connection) -> dict:
    """fin_annual_line: statement-caption rows picked out of ar_facts by a closed lexicon (no PDF reading)."""
    schema.create(conn, ("fin_annual_line",))
    counts = {}
    for symbol in profile.symbols():
        spec = _spec(symbol, "ar_facts")
        sql = spec["sql"].replace("SELECT *,", "SELECT rowid AS src_rowid, *,", 1)
        rows, types = prepare._read_sqlite(spec["db"], spec["source"], sql, spec["params"])
        cols = list(types)
        seen, out = set(), []
        for raw in rows:
            r = dict(zip(cols, raw))
            hit = lexicon_item(r["item"])
            basis = str(r["basis"] or "").lower()
            if basis not in ("consolidated", "standalone"):
                basis = "not_stated"
            if not hit or r["value"] is None:
                continue
            fy = str(r["period"] or "")
            m = re.fullmatch(r"FY(?:20)?(\d\d)", fy)
            if m:
                fy = "FY" + m.group(1)
            else:
                m = re.match(r"(\d{4})-03-31", str(r["fiscal_year"] or ""))
                if not m:
                    continue
                fy = "FY" + m.group(1)[2:]
            unit, scale = _unit(r["unit"])
            key = (r["isin"], fy, basis, hit[0], round(float(r["value"]), 4), r["page"], r["doc_id"])
            if key in seen:
                continue
            seen.add(key)
            definition = "company_stated" if hit[0] in COMPANY_STATED else "reported"
            out.append((symbol, r["isin"], fy, f"20{fy[2:]}-03-31", basis, hit[1], hit[0], r["item"],
                        float(r["value"]), unit, scale, str(r["doc_id"]), r["page"], r["quote"],
                        spec["db"], "ar_facts", str(r["src_rowid"]), r["known_at"], "ar_facts.filed_at", 1, 0,
                        definition, "FY"))
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


def parse_shp_xbrl(blob: bytes) -> dict:
    """Header (isin, symbol) and per-category facts of one SHP XBRL file, stdlib only."""
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
                    dims.append(("typed", ""))
                elif t == "instant":
                    inst = sub.text
            ctx[el.get("id")] = (tuple(dims), inst)
        elif tag in ("ISIN", "Symbol", "DateOfReport") and el.text:
            head[tag] = el.text.strip()
    facts: dict[tuple, dict] = {}
    for el in root:
        tag, ref = _local(el.tag), el.get("contextRef")
        if ref not in ctx or tag not in ("NumberOfShares", "ShareholdingAsAPercentageOfTotalNumberOfShares",
                                         "NumberOfShareholders"):
            continue
        dims, inst = ctx[ref]
        if len(dims) != 1 or dims[0][0] != "CategoryOfShareholdersAxis":
            continue
        member = dims[0][1].removesuffix("Member")
        try:
            value = float(el.text)
        except (TypeError, ValueError):
            continue
        facts.setdefault((member, inst), {})[tag] = value
    # The 2025-05 taxonomy files give percentages as fractions (0.5467), older ones as percent (54.67):
    # promoter + public always total 100%, so a total near 1 marks a fractional file.
    pct = "ShareholdingAsAPercentageOfTotalNumberOfShares"
    for inst in {i for (_m, i) in facts}:
        total = sum(facts.get((m, inst), {}).get(pct, 0.0)
                    for m in ("ShareholdingOfPromoterAndPromoterGroup", "PublicShareholding"))
        if 0 < total <= 1.5:
            for (member, i), f in facts.items():
                if i == inst and pct in f:
                    f[pct] = round(f[pct] * 100.0, 6)
    return {"head": head, "facts": facts}


def build_shp(conn: sqlite3.Connection) -> dict:
    """shp_category: shp_index (promoter / public per quarter) + holder categories from the SHP XBRL files."""
    schema.create(conn, ("shp_category",))
    counts, xbrl_files = {}, {}
    if SHP_XBRL.is_dir():
        for path in sorted(SHP_XBRL.glob("*.xml.gz")):
            xbrl_files[path.name[:-3]] = path
    parsed_files = {name: parse_shp_xbrl(gzip.open(path).read()) for name, path in xbrl_files.items()}
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
                            r["revised"], known, "shp_index.broadcast_at", 1))
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
            fpi, ifor = {}, {}
            for (member, inst), f in parsed["facts"].items():
                if member == "InstitutionsForeign":
                    ifor[inst] = f
                cat = MEMBERS.get(member, _snake(member))
                out.append((symbol, parsed["head"]["ISIN"], inst, cat, member, f.get("NumberOfShares"),
                            f.get("ShareholdingAsAPercentageOfTotalNumberOfShares"), f.get("NumberOfShareholders"),
                            "pct", "xbrl", name, "nse_shp_xbrl_pilot", "xml.gz", name, revised, known, src, 1))
                if cat.startswith("fpi"):
                    fpi[(cat, inst)] = f
            for inst, f in ifor.items():  # new taxonomy: the pattern's own FII / FPI line (all foreign institutions)
                if ("fpi", inst) in fpi:
                    continue
                out.append((symbol, parsed["head"]["ISIN"], inst, "fpi_total", "InstitutionsForeign (FII/FPI line)",
                            f.get("NumberOfShares"), f.get("ShareholdingAsAPercentageOfTotalNumberOfShares"), None,
                            "pct", "xbrl", name, "nse_shp_xbrl_pilot", "xml.gz", name, revised, known, src, 1))
            for inst in {i for (_c, i) in fpi} - {i for i in ifor if ("fpi", i) not in fpi}:
                pick = [fpi[k] for k in fpi if k[1] == inst and k[0] == "fpi"] or \
                       [fpi[k] for k in fpi if k[1] == inst and k[0] in ("fpi_category_1", "fpi_category_2")]
                if pick:
                    out.append((symbol, parsed["head"]["ISIN"], inst, "fpi_total", "FPI (derived: sum of FPI members)",
                                sum(p.get("NumberOfShares") or 0 for p in pick),
                                sum(p.get("ShareholdingAsAPercentageOfTotalNumberOfShares") or 0 for p in pick),
                                None, "pct", "xbrl", name, "nse_shp_xbrl_pilot", "xml.gz", name, revised, known, src, 0))
        conn.executemany("INSERT INTO shp_category VALUES (" + ",".join("?" * 18) + ")", out)
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
    result["window"] = apply_window(conn)
    conn.commit()
    return result
