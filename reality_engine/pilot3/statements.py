"""Balance-sheet, cash-flow and annual P&L lines out of the XBRL result filings (T-049 part D), plus
dividend events from NSE corporate actions.  Everything lands in ``fin_annual_line`` (``fiscal_year`` FYyy or
H1FYyy, ``period_type`` FY / H1) with a ``definition``:

* ``xbrl_reported``  a tag the company filed, value as filed (rupees, scale 1);
* ``xbrl_derived``   a sum or difference of filed tags (total borrowings, net debt, capex, capital employed);
* ``company_stated`` the company's own measure (``company.py`` / the ar_facts lexicon), kept beside the derived one.

Source of every row: the XBRL file name (``doc_key``), ``results_xbrl.db`` table ``facts`` row id, and the
filing's dissemination time as ``known_at``.  No model, no network."""
from __future__ import annotations

import re
import sqlite3
from datetime import date

from reality_engine.gap_loop import prepare
from reality_engine.pilot3 import profile, schema
from reality_engine.pilot3.registry import all_isins
from reality_engine.pilot3.stores import EXTRA_QUARTER_TAGS, QUARTER_TAGS, SECTOR_TAGS, _basis, _duck, fetch

COLS = 23
# Balance-sheet instants: XBRL element -> (canonical line item)
BS_TAGS = {
    "Assets": "total_assets", "Liabilities": "total_liabilities", "Equity": "total_equity",
    "EquityAttributableToOwnersOfParent": "equity_owners", "EquityShareCapital": "equity_share_capital",
    "OtherEquity": "other_equity", "NonControllingInterest": "non_controlling_interest",
    "CurrentAssets": "current_assets", "CurrentLiabilities": "current_liabilities",
    "NoncurrentAssets": "noncurrent_assets", "NoncurrentLiabilities": "noncurrent_liabilities",
    "BorrowingsCurrent": "borrowings_current", "BorrowingsNoncurrent": "borrowings_noncurrent",
    "Borrowings": "borrowings_other_than_debt_securities", "DebtSecurities": "debt_securities",
    "SubordinatedLiabilities": "subordinated_liabilities", "Deposits": "deposits", "Loans": "loans",
    "Investments": "investments", "CashAndCashEquivalents": "cash_and_equivalents",
    "BankBalanceOtherThanCashAndCashEquivalents": "bank_balances", "CurrentInvestments": "current_investments",
    "NoncurrentInvestments": "noncurrent_investments", "TradeReceivablesCurrent": "trade_receivables_current",
    "TradeReceivablesNoncurrent": "trade_receivables_noncurrent", "TradeReceivables": "trade_receivables",
    "Inventories": "inventories", "TradePayablesCurrent": "trade_payables_current",
    "TradePayablesNoncurrent": "trade_payables_noncurrent", "LoansCurrent": "loans_current",
    "LoansNoncurrent": "loans_noncurrent", "CapitalWorkInProgress": "capital_work_in_progress",
    # bank and life-insurer balance sheets (T-056 loop 2): capital and reserves, shareholders' funds, and the closing
    # cash of the cash-flow statement (their balance sheet has no cash-and-equivalents line of the industrial kind)
    "Capital": "equity_share_capital", "ShareCapital": "equity_share_capital",
    "ReservesAndSurplus": "reserves_and_surplus", "ShareholdersFunds": "shareholders_funds",
    "CashAndCashEquivalentsCashFlowStatement": "cash_flow_statement_cash",
}
# Cash-flow durations (year to date)
CF_TAGS = {
    "CashFlowsFromUsedInOperatingActivities": "cash_flow_from_operations",
    "CashFlowsFromUsedInInvestingActivities": "cash_flow_from_investing",
    "CashFlowsFromUsedInFinancingActivities": "cash_flow_from_financing",
    "CashFlowsFromUsedInOperations": "cash_generated_from_operations",
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": "purchase_of_ppe",
    "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities": "purchase_of_intangibles",
    "ProceedsFromSalesOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": "sale_of_ppe",
    "DividendsPaidClassifiedAsFinancingActivities": "dividends_paid",
    "InterestPaidClassifiedAsFinancingActivities": "interest_paid_financing",
    "InterestPaidClassifiedAsOperatingActivities": "interest_paid_operating",
    "IncomeTaxesPaidRefundClassifiedAsOperatingActivities": "income_tax_paid",
    "PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities": "lease_payments",
    "ProceedsFromBorrowingsClassifiedAsFinancingActivities": "proceeds_from_borrowings",
    "RepaymentsOfBorrowingsClassifiedAsFinancingActivities": "repayment_of_borrowings",
}
PL_TAGS = {tag: v for tag, v in {**QUARTER_TAGS, **EXTRA_QUARTER_TAGS, **SECTOR_TAGS}.items()
           if v[1] == "P&L" and v[2] == "inr" or tag.startswith(("Basic", "Diluted"))}
FY_QUARTERS = ("Yearly", "Fourth quarter")
H1_QUARTERS = ("Half yearly", "Second quarter")


def _fy(period_end: str) -> str:
    y, m = int(period_end[:4]), int(period_end[5:7])
    return f"FY{str(y + 1 if m >= 4 else y)[2:]}"


def _days(a: str, b: str) -> int | None:
    try:
        return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    except (TypeError, ValueError):
        return None


def _row(symbol, f, fy, end, basis, statement, item, caption, value, unit, quote, rowid, derived, definition,
         ptype, scale=1.0):
    return (symbol, f["isin"], fy, end, basis, statement, item, caption, float(value), unit, scale, f["file"], None,
            quote, "results_xbrl.db", "facts", rowid, f["known_at"], "results_xbrl.filings.dissem_ts|broadcast_ts",
            0 if derived else 1, 1 if derived else 0, definition, ptype)


def _filing_lines(symbol: str, f: dict, ptype: str, facts: list) -> list[tuple]:
    end = f["period_end"]
    basis = _basis(f["consolidated"])
    fy = _fy(end) if ptype == "FY" else "H1" + _fy(end)
    window = (355, 372) if ptype == "FY" else (176, 188)
    got: dict[str, tuple] = {}  # tag -> (value, rowid, context)
    for concept, context, start, stop, instant, value, unit, rowid in facts:
        if value is None or unit not in ("INR", "INRPerShare", None):
            continue
        if instant is not None or (start is None and context == "OneI"):
            if context == "OneI" and concept in BS_TAGS and (instant in (None, end)):
                got.setdefault(concept, (float(value), rowid, context))
        elif stop == end and start is not None:
            span = _days(start, stop)
            if span is not None and window[0] <= span <= window[1] and (concept in CF_TAGS or concept in PL_TAGS):
                if concept not in got or context == "FourD":
                    got[concept] = (float(value), rowid, context)
    out: list[tuple] = []
    refs: dict[str, tuple] = {}
    for tag, (value, rowid, _ctx) in got.items():
        if tag in BS_TAGS:
            item, statement = BS_TAGS[tag], "BS"
        elif tag in CF_TAGS:
            item, statement = CF_TAGS[tag], "CF"
        else:
            item, statement = PL_TAGS[tag][0], "P&L"
        unit_out = "inr_per_share" if "PerShare" in tag else "inr"
        out.append(_row(symbol, f, fy, end, basis, statement, item, f"{tag} (XBRL)", value, unit_out,
                        f"{tag} = {value:g}", f"{f['file']}#{rowid}", False, "xbrl_reported", ptype))
        refs[item] = (value, f"{f['file']}#{rowid}", tag)
    # net worth: equity attributable to owners (total equity when that tag is absent)
    nw = refs.get("equity_owners") or refs.get("total_equity")
    if nw:
        out.append(_row(symbol, f, fy, end, basis, "BS", "net_worth",
                        "net worth = EquityAttributableToOwnersOfParent" if "equity_owners" in refs else "net worth = Equity",
                        nw[0], "inr", f"{nw[2]} = {nw[0]:g}", nw[1], True, "xbrl_derived", ptype))
    elif "shareholders_funds" in refs and profile.under_profile():  # life insurer
        sf = refs["shareholders_funds"]
        out.append(_row(symbol, f, fy, end, basis, "BS", "net_worth", "net worth = ShareholdersFunds", sf[0], "inr",
                        f"{sf[2]} = {sf[0]:g}", sf[1], True, "xbrl_derived", ptype))
    elif "equity_share_capital" in refs and "reserves_and_surplus" in refs and profile.under_profile():  # bank
        parts = [refs["equity_share_capital"], refs["reserves_and_surplus"]]
        out.append(_row(symbol, f, fy, end, basis, "BS", "net_worth", "net worth = capital + reserves and surplus",
                        sum(p[0] for p in parts), "inr", "; ".join(f"{p[2]} {p[0]:g}" for p in parts),
                        ";".join(p[1] for p in parts), True, "xbrl_derived", ptype))
    extra = profile.under_profile()  # the three-company pilot3 build keeps the lines it always had
    if extra and "cash_and_equivalents" not in refs and "cash_flow_statement_cash" in refs and profile.is_lender(symbol):
        c = refs["cash_flow_statement_cash"]
        out.append(_row(symbol, f, fy, end, basis, "BS", "cash_and_equivalents",
                        "cash and cash equivalents = closing cash of the cash-flow statement (no balance-sheet line)", c[0],
                        "inr", f"{c[2]} = {c[0]:g}", c[1], True, "xbrl_derived", ptype))
    if extra and "investments" not in refs and ("current_investments" in refs or "noncurrent_investments" in refs):
        parts = [refs[i] for i in ("current_investments", "noncurrent_investments") if i in refs]
        out.append(_row(symbol, f, fy, end, basis, "BS", "investments", "investments = current + non-current investments",
                        sum(p[0] for p in parts), "inr", "; ".join(f"{p[2]} {p[0]:g}" for p in parts),
                        ";".join(p[1] for p in parts), True, "xbrl_derived", ptype))
    if extra and not profile.is_lender(symbol) and all(i in refs for i in ("pbt_before_exceptional", "finance_cost", "depreciation")):
        parts = [refs[i] for i in ("pbt_before_exceptional", "finance_cost", "depreciation")]
        oth = refs.get("other_income")
        out.append(_row(symbol, f, fy, end, basis, "P&L", "ebitda",
                        "EBITDA = profit before exceptional items and tax + finance cost + depreciation - other income "
                        "(formula F_EBITDA, applied to the period's filed lines)",
                        sum(p[0] for p in parts) - (oth[0] if oth else 0.0), "inr",
                        "; ".join(f"{p[2]} {p[0]:g}" for p in parts) + (f"; less {oth[2]} {oth[0]:g}" if oth else ""),
                        ";".join(p[1] for p in parts + ([oth] if oth else [])), True, "xbrl_derived", ptype))

    def total(items, label, name, minus=()):
        parts = [refs[i] for i in items if i in refs]
        if not parts:
            return None
        value = sum(p[0] for p in parts) - sum(refs[i][0] for i in minus if i in refs)
        used = [p[2] for p in parts] + [f"-{refs[i][2]}" for i in minus if i in refs]
        out.append(_row(symbol, f, fy, end, basis, "BS", name, f"{label} = " + " ".join(used), value, "inr",
                        f"{name} = " + "; ".join(f"{p[2]} {p[0]:g}" for p in parts), ";".join(p[1] for p in parts),
                        True, "xbrl_derived", ptype))
        return value

    if profile.is_lender(symbol):
        debt = total(("borrowings_other_than_debt_securities", "debt_securities", "subordinated_liabilities", "deposits"),
                     "total borrowings (incl. deposits)", "total_borrowings")
    else:
        debt = total(("borrowings_current", "borrowings_noncurrent"), "total borrowings", "total_borrowings")
        if debt is not None:
            total(("borrowings_current", "borrowings_noncurrent"),
                        "net debt = borrowings - cash - other bank balances - current investments", "net_debt",
                        minus=("cash_and_equivalents", "bank_balances", "current_investments"))
        if "total_assets" in refs and "current_liabilities" in refs:
            ce = refs["total_assets"][0] - refs["current_liabilities"][0]
            out.append(_row(symbol, f, fy, end, basis, "BS", "capital_employed",
                            "capital employed = Assets - CurrentLiabilities", ce, "inr",
                            f"Assets {refs['total_assets'][0]:g} - CurrentLiabilities {refs['current_liabilities'][0]:g}",
                            refs["total_assets"][1] + ";" + refs["current_liabilities"][1], True, "xbrl_derived", ptype))
    tr = [refs[i] for i in ("trade_receivables_current", "trade_receivables_noncurrent", "trade_receivables") if i in refs]
    if tr and not profile.is_lender(symbol):
        out.append(_row(symbol, f, fy, end, basis, "BS", "trade_receivables", "trade receivables (current + non-current)",
                        sum(t[0] for t in tr), "inr", "; ".join(f"{t[2]} {t[0]:g}" for t in tr),
                        ";".join(t[1] for t in tr), True, "xbrl_derived", ptype))
    capex = [refs[i] for i in ("purchase_of_ppe", "purchase_of_intangibles") if i in refs]
    if capex:
        out.append(_row(symbol, f, fy, end, basis, "CF", "capex",
                        "capex = -(purchase of PPE + purchase of intangibles), cash-flow sign (outflow negative)",
                        -sum(c[0] for c in capex), "inr", "; ".join(f"{c[2]} {c[0]:g}" for c in capex),
                        ";".join(c[1] for c in capex), True, "xbrl_derived", ptype))
    return out


def build_xbrl_statements(conn: sqlite3.Connection) -> dict:
    """Year-end and half-year balance sheets, cash flows and annual P&L lines of every XBRL filing held."""
    counts = {}
    for symbol in profile.symbols():
        filings = [f for f in fetch(symbol, "results_filings") if f.get("status") == "ok"]
        rows: list[tuple] = []
        for f in filings:
            end, quarter = str(f["period_end"] or ""), f["reporting_quarter"]
            if end[5:] == "03-31" and quarter in FY_QUARTERS:
                ptype = "FY"
            elif end[5:] == "09-30" and quarter in H1_QUARTERS:
                ptype = "H1"
            else:
                continue
            facts, _ = prepare._read_sqlite(
                "results_xbrl.db", "facts",
                "SELECT concept, context, period_start, period_end, instant, value, unit, rowid FROM facts WHERE file=?",
                (f["file"],))
            rows += _filing_lines(symbol, f, ptype, facts)
        conn.executemany("INSERT INTO fin_annual_line VALUES (" + ",".join("?" * COLS) + ")", rows)
        counts[symbol] = len(rows)
    conn.commit()
    return counts


# --- dividends --------------------------------------------------------------------------------------
_AMOUNT = re.compile(r"(?:rs\.?|re\.?|inr|₹)\s*([\d]+(?:\.\d+)?)", re.I)


def _dividend_fy(ex: date, kind: str) -> str:
    """Final and special dividends (ex-date April to September) belong to the year that closed in March
    before; interim ones (October to March) to the year that closes in the next March."""
    if kind == "interim":
        return f"FY{str(ex.year + 1 if ex.month >= 4 else ex.year)[2:]}"
    return f"FY{str(ex.year if ex.month <= 9 else ex.year + 1)[2:]}"


def build_dividends(conn: sqlite3.Connection) -> dict:
    """dividend_event (one row per NSE corporate action) and the per-year sums in fin_annual_line."""
    schema.create(conn, ("dividend_event",))
    counts = {}
    for symbol in profile.symbols():
        rows, _ = _duck(
            "SELECT id, isin, subject, ex_date, rec_date, face_value, broadcast_date FROM corporate_actions "
            "WHERE symbol=? AND action_type='DIVIDEND' ORDER BY ex_date", (symbol,))
        events, per_year = [], {}
        for id_, isin, subject, ex, rec, face, bdate in rows:
            m = _AMOUNT.search(subject or "")
            if not m or ex is None:
                continue
            amount = float(m.group(1))
            low = (subject or "").lower()
            kind = "special" if "special" in low else "interim" if "interim" in low else \
                "final" if ex.month in (4, 5, 6, 7, 8, 9) else "interim"
            fy = _dividend_fy(ex, kind)
            known = f"{bdate or ex}"
            src = "corporate_actions.broadcast_date" if bdate else "ex_date (declaration was earlier)"
            events.append((symbol, isin, str(ex), str(rec) if rec else None, fy, kind, amount, face, subject, known, src,
                           "truth snapshot", "corporate_actions", str(id_)))
            per_year.setdefault((fy, kind == "special"), []).append((ex, amount, id_, subject, isin, known))
        conn.executemany("INSERT INTO dividend_event VALUES (" + ",".join("?" * 14) + ")", events)
        lines = []
        for (fy, special), evs in sorted(per_year.items()):
            total = sum(e[1] for e in evs)
            item = "special_dividend_per_share" if special else "dividend_per_share"
            lines.append((symbol, evs[-1][4], fy, f"20{fy[2:]}-03-31", "not_stated", "P&L", item,
                          f"{item.replace('_', ' ')}, sum of NSE corporate actions: " + "; ".join(e[3] for e in evs),
                          total, "inr_per_share", 1.0, "truth snapshot/corporate_actions", None,
                          "; ".join(e[3] for e in evs), "truth snapshot", "corporate_actions",
                          ",".join(str(e[2]) for e in evs), max(e[5] for e in evs),
                          "corporate_actions.broadcast_date|ex_date", 1, 1 if len(evs) > 1 else 0, "reported", "FY"))
        conn.executemany("INSERT INTO fin_annual_line VALUES (" + ",".join("?" * COLS) + ")", lines)
        counts[symbol] = len(events)
    conn.commit()
    return counts


# --- company-stated measures, read by script from deck / transcript / press-release pages -------------
STATED_DOC_TYPES = ("deck", "press_release", "results", "transcript")
_MON = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_QEND = {1: "06-30", 2: "09-30", 3: "12-31", 4: "03-31"}
_PERIOD = re.compile(
    r"(?<![A-Za-z0-9])(?:(Q[1-4])\s*FY\s*['’]?(?:20)?(\d{2})|(H[12])\s*FY\s*['’]?(?:20)?(\d{2})|"
    r"FY\s*['’]?(?:20)?(\d{2})|(\d{1,2})(?:st|nd|rd|th)?[-\s]([A-Za-z]{3})[a-z]*[-\s']*(\d{2,4}))(?![0-9])", re.I)
_NUM = re.compile(r"^\(?-?\d[\d,]*(?:\.\d+)?\)?(%|x)?$")
_SKIP = {"", "yoy", "qoq", "change", "yoy %", "qoq change %", "change yoy %", "change %", "%", "particulars",
         "y-o-y", "q-o-q", "yoy change", "qoq change", "yoy change %", "change qoq %"}
MEASURE_ROWS = [  # (line_item, anchored regex over the lower-cased row label)
    ("net_debt_incl_acceptances", r"net debt \(?incl\w*\.? acceptances\)?"),
    ("net_debt_to_ebitda", r"(?:consolidated )?net debt(?: to |/ ?)(?:ttm )?(?:adjusted )?ebitda(?: ratio)?"),
    ("net_debt", r"(?:consolidated )?net debt"),
    ("ebitda_margin_pct", r"(?:consolidated )?ebitda margin(?: \(%\))?"),
    ("ebitda", r"(?:consolidated )?ebitda"),
]
_ROW_RX = [(item, re.compile(rf"^(?:{rx})$")) for item, rx in MEASURE_ROWS]
_NUMBER = r"([\d,]+(?:\.\d+)?)"
SENTENCES = [  # (line_item, unit, regex); group 1 = number
    ("ebitda_margin_pct", "pct", re.compile(r"ebitda margins?[^%]{0,100}?\b(?:to|at|of|was|stood at|is)\s+(\d+(?:\.\d+)?)\s*%", re.I)),
    ("net_debt_incl_acceptances", "inr_crore",
     re.compile(r"net debt,? \(?including acceptances\)?\s*(?:is|was|stood)?\s*(?:at|of)?\s*(?:inr|rs\.?|₹)\s*" + _NUMBER +
                r"\s*(?:crores?|cr)\b", re.I)),
    ("net_debt", "inr_crore",
     re.compile(r"\bnet debt(?!,? \(?incl)(?! to)(?!/)[^\d%]{0,60}?(?:inr|rs\.?|₹)\s*" + _NUMBER + r"\s*(?:crores?|cr)\b", re.I)),
    ("net_debt_to_ebitda", "x", re.compile(r"net debt(?: to |/ ?)ebitda[^\d]{0,60}?(\d+(?:\.\d+)?)\s*x", re.I)),
    # the company's own "cash flow from operations" (Q4 FY26 deck net-debt bridge: "Healthy Cash flow from
    # operations at ₹21,858 crore"): a different measure from the audited XBRL operating cash flow, so it is stored
    # as its own company_stated row beside it and neither replaces the other (T-049: the conflict had no definition).
    ("cash_flow_from_operations", "inr_crore",
     re.compile(r"cash flows? (?:from operations|amounting to)[^\d%]{0,40}(?:inr|rs\.?|₹)\s*" + _NUMBER +
                r"\s*(?:crores?|cr)\b", re.I)),
]


def _period_of(m: re.Match) -> tuple[str, str] | None:
    """('Q','Q4FY26') | ('H','H1FY26') | ('FY','FY26'); a month-end date token gives its quarter."""
    if m.group(1):
        return "Q", f"{m.group(1).upper()}FY{m.group(2)}"
    if m.group(3):
        return "H", f"{m.group(3).upper()}FY{m.group(4)}"
    if m.group(5):
        return "FY", f"FY{m.group(5)}"
    mon = _MON.get(m.group(7).lower())
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(mon)
    if q is None:
        return None
    year = int(m.group(8)) + (2000 if len(m.group(8)) == 2 else 0)
    return "Q", f"Q{q}FY{str(year + 1 if mon >= 4 else year)[2:]}"


def _number(token: str) -> float | None:
    t = token.strip().rstrip("%x").replace(",", "")
    neg = t.startswith("(") or t.startswith("-")
    try:
        v = float(t.strip("()-"))
    except ValueError:
        return None
    return -v if neg else v


def _item_for(label: str) -> str | None:
    text = re.sub(r"\s+", " ", label.strip().lower()).rstrip("*#^ ")
    for item, rx in _ROW_RX:
        if rx.match(text):
            return item
    return None


def table_rows(text: str) -> list[tuple]:
    """Rows whose label line is followed by numeric lines and whose column header (period tokens just above)
    has as many columns: (line_item, period kind, period label, value, unit, quote)."""
    lines = [ln.strip() for ln in text.split("\n")]
    out, group, after_text = [], [], True
    crore = bool(re.search(r"(?:₹|rs\.?|inr)\s*(?:in\s*)?crores?|crores?\)", text, re.I))
    for i, ln in enumerate(lines):
        pm = _PERIOD.fullmatch(ln) if ln else None
        if pm and _period_of(pm):
            if after_text:
                group, after_text = [], False
            group.append(_period_of(pm))
            continue
        item = _item_for(ln) if ln else None
        if item and group:
            vals, j = [], i + 1
            while j < len(lines) and (lines[j].lower() in _SKIP or _NUM.match(lines[j])):
                if lines[j].lower() not in _SKIP:
                    vals.append(lines[j])
                j += 1
            keep = [v for v in vals if (v.endswith("%") if item == "ebitda_margin_pct" else not v.endswith("%"))]
            money = item in ("ebitda", "net_debt", "net_debt_incl_acceptances")
            if len(keep) == len(group) and keep and not (money and not crore):
                unit = "pct" if item == "ebitda_margin_pct" else "x" if item == "net_debt_to_ebitda" else "inr_crore"
                for (kind, label), v in zip(group, keep):
                    value = _number(v)
                    if value is not None:
                        out.append((item, kind, label, value, unit, f"{ln} " + " ".join(vals)[:120]))
            continue
        if ln and ln.lower() not in _SKIP:
            after_text = True
    return out


def sentence_rows(text: str, doc_period: tuple[str, str] | None) -> list[tuple]:
    flat = re.sub(r"\s+", " ", text)
    out = []
    for item, unit, rx in SENTENCES:
        for m in rx.finditer(flat):
            value = _number(m.group(1))
            seg_periods = [p for p in (_period_of(x) for x in _PERIOD.finditer(m.group(0))) if p]
            period = seg_periods[-1] if seg_periods else doc_period
            if value is None or period is None:
                continue
            out.append((item, period[0], period[1], value, unit, flat[max(0, m.start() - 20):m.end() + 20]))
    return out


def _other_pages() -> sqlite3.Connection | None:
    """The collector's pages.db of this build (the profile's, else the pilot3 one): read-only, optional."""
    path = profile.pages_db()
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30) if path.is_file() else None


def _stated_pages(conn: sqlite3.Connection, symbol: str):
    """(doc_key, page, text, known_at, doc_type, title, source) for candidate pages: this database first, then
    pages.db for documents this database does not hold yet."""
    sql = ("SELECT p.doc_key, p.page, p.text, COALESCE(p.known_at, d.known_at), d.doc_type, d.title FROM doc_page p "
           "JOIN doc d ON d.doc_key=p.doc_key WHERE d.symbol=? AND d.doc_type IN (?,?,?,?) AND COALESCE(p.known_at, d.known_at) IS NOT NULL AND "
           "(lower(p.text) LIKE '%ebitda%' OR lower(p.text) LIKE '%net debt%')")
    have = set()
    for dk, pg, text, known, dtype, title in conn.execute(sql, (symbol, *STATED_DOC_TYPES)):
        have.add(dk)
        yield dk, pg, text, known, dtype, title, "pilot3"
    other = _other_pages()
    if other is None:
        return
    try:
        rows = other.execute(sql, (symbol, *STATED_DOC_TYPES)).fetchall()
    except sqlite3.Error:
        return
    finally:
        other.close()
    for dk, pg, text, known, dtype, title in rows:
        if dk not in have:
            yield dk, pg, text, known, dtype, title, "pages.db"


def _quarter_end(label: str) -> str:
    q, fy = int(label[1]), 2000 + int(label[4:6])
    return f"{fy if q == 4 else fy - 1}-{_QEND[q]}"


def _derived_flow(conn: sqlite3.Connection, symbol: str, label: str) -> tuple[float, float] | None:
    """(EBITDA, revenue) in rupees from the XBRL quarters of a QnFYyy or FYyy label, consolidated; None if any
    quarter is missing.  Used only as a plausibility gate for scripted deck reads."""
    if label.startswith("Q"):
        ends = [_quarter_end(label)]
    else:
        y = 2000 + int(label[2:4])
        ends = [f"{y - 1}-06-30", f"{y - 1}-09-30", f"{y - 1}-12-31", f"{y}-03-31"]
    total_e = total_r = 0.0
    for end in ends:
        got = dict(conn.execute(
            "SELECT line_item, value FROM fin_quarter_xbrl WHERE symbol=? AND basis='consolidated' AND period_end=? "
            "AND line_item IN ('pbt_before_exceptional','finance_cost','depreciation','other_income','revenue_from_operations') "
            "ORDER BY known_at", (symbol, end)).fetchall())
        if not all(k in got for k in ("pbt_before_exceptional", "finance_cost", "depreciation", "revenue_from_operations")):
            return None
        total_e += got["pbt_before_exceptional"] + got["finance_cost"] + got["depreciation"] - got.get("other_income", 0.0)
        total_r += got["revenue_from_operations"]
    return total_e, total_r


def _plausible(conn: sqlite3.Connection, symbol: str, item: str, label: str, value: float, unit: str) -> bool:
    """Gate against mis-mapped table columns and segment rows: a company EBITDA must sit within 25% of the XBRL-derived
    one (margin within 3 points); net debt within 40% of the XBRL-derived net debt; leverage between 0 and 15 times.
    No XBRL figure for the period (lender, future quarter) means no gate beyond the range check."""
    if item == "net_debt_to_ebitda":
        return 0 <= value <= 15
    if item in ("ebitda", "ebitda_margin_pct"):
        if profile.is_lender(symbol):
            return False
        d = _derived_flow(conn, symbol, label)
        if d is None or not d[1]:
            return item == "ebitda" or value < 30
        if item == "ebitda":
            return abs(value * 1e7 - d[0]) <= 0.25 * abs(d[0])
        return abs(value - 100.0 * d[0] / d[1]) <= 3.0
    if item == "net_debt" and label.startswith("FY"):
        row = conn.execute("SELECT value FROM fin_annual_line WHERE symbol=? AND basis='consolidated' AND fiscal_year=? "
                           "AND line_item='net_debt' AND definition='xbrl_derived' LIMIT 1", (symbol, label)).fetchone()
        return row is None or abs(value * 1e7 - row[0]) <= 0.4 * abs(row[0])
    return True


def _first_period(text: str, limit: int = 2000):
    """First match of _PERIOD that names a fiscal period (a bare "22nd May 2026" is a filing date, not a period)."""
    for m in _PERIOD.finditer(text[:limit]):
        p = _period_of(m)
        if p:
            return p
    return None


def _stated_periods(kind: str, label: str, item: str) -> list[tuple[str, str]]:
    """Periods one company-stated figure belongs to: an annual flow stated in a Q4 document (net debt, operating
    cash flow) is also the fiscal year, so a FY26 question finds the deck's Q4 FY26 slide."""
    periods = [(kind, label)]
    if kind == "Q" and label[1] == "4" and item in ("net_debt", "net_debt_incl_acceptances", "net_debt_to_ebitda",
                                                    "cash_flow_from_operations"):
        periods.append(("FY", f"FY{label[4:6]}"))
    return periods


def build_company_stated(conn: sqlite3.Connection) -> dict:
    """EBITDA, margin, net debt and leverage as the company prints them (deck tables, deck / call sentences):
    fin_annual_line rows with definition 'company_stated'; quarter rows have fiscal_year QnFYyy, period_type Q."""
    counts = {}
    for symbol in profile.symbols():
        isin = conn.execute("SELECT isin FROM company WHERE symbol=? ORDER BY isin_from DESC LIMIT 1", (symbol,)).fetchone()
        isin = isin[0] if isin else None
        found: dict[tuple, tuple] = {}
        doc_period: dict[str, tuple | None] = {}
        for dk, pg, text, known, dtype, title, src in _stated_pages(conn, symbol):
            if dk not in doc_period:
                if pg <= 3:
                    head = _PERIOD.search(text[:400])
                    doc_period[dk] = _period_of(head) if head else None
                else:   # only a chart page of this document matched the filter: date it from its title pages
                    first = conn.execute("SELECT text FROM doc_page WHERE doc_key=? AND page<=3 ORDER BY page",
                                         (dk,)).fetchall()
                    doc_period[dk] = _first_period(" ".join(t for (t,) in first)) if first else None
            first = _PERIOD.search(text[:300])
            page_period = _period_of(first) if first else None
            if page_period and page_period[0] != "Q":
                page_period = None
            consolidated = "consolidated" if re.search(r"consolidated", text, re.I) else "not_stated"
            for item, kind, label, value, unit, quote in table_rows(text) + sentence_rows(text, page_period or doc_period.get(dk)):
                if item == "cash_flow_from_operations":
                    flat = re.sub(r"\s+", " ", text)
                    pos = flat.find(quote) if quote else -1
                    local = [_period_of(m) for m in _PERIOD.finditer(flat[max(0, pos - 160):pos + 80])] if pos >= 0 else []
                    local = [p for p in local if p]
                    if local:
                        kind, label = local[-1]            # "In FY26, our businesses ... cash flows amounting to ..."
                    elif doc_period.get(dk):
                        kind, label = doc_period[dk]       # an annual flow belongs to the document's period
                for pk, pl in _stated_periods(kind, label, item):
                    key = (consolidated, pl, item, round(value, 4))
                    if key not in found or (known or "") < (found[key][0] or ""):
                        found[key] = (known, dk, pg, quote, unit, pk, src)
        rows_out, dropped = [], 0
        for (basis, pl, item, value), (known, dk, pg, quote, unit, pk, src) in sorted(found.items()):
            end = _quarter_end(pl) if pl.startswith("Q") else f"20{pl[2:]}-03-31" if pl.startswith("FY") else None
            if end is None or not _plausible(conn, symbol, item, pl, value, unit):
                dropped += 1
                continue
            rows_out.append((symbol, isin, pl, end, basis,
                             "CF" if item == "cash_flow_from_operations" else "P&L" if item.startswith("ebitda") else "BS",
                             item, f"{item.replace('_', ' ')} as printed by the company", value, unit,
                             1e7 if unit == "inr_crore" else 1.0, dk, pg, quote, src, "doc_page", f"{dk}#{pg}", known,
                             "doc_page.known_at (filing record of the document)", 1, 0, "company_stated", pk))
        # pages taken from pages.db are copied into this database so every quote can be checked here
        _import_pages(conn, symbol, {(r[11], r[12]) for r in rows_out if r[14] == "pages.db"})
        conn.executemany("INSERT INTO fin_annual_line VALUES (" + ",".join("?" * COLS) + ")", rows_out)
        counts[symbol] = {"rows": len(rows_out), "dropped_by_plausibility_gate": dropped}
    conn.commit()
    return counts


def _import_pages(conn: sqlite3.Connection, symbol: str, pages: set) -> None:
    if not pages:
        return
    other = _other_pages()
    if other is None:
        return
    for dk in {dk for dk, _pg in pages}:
        row = other.execute("SELECT doc_key, symbol, isin, doc_type, title, filing_date, known_at, pages, sha256, "
                            "source_record FROM doc WHERE doc_key=?", (dk,)).fetchone()
        if row and not conn.execute("SELECT 1 FROM doc WHERE doc_key=?", (dk,)).fetchone():
            conn.execute("INSERT INTO doc (doc_key, symbol, isin, doc_type, doc_family, title, filing_date, known_at, "
                         "pages, sha256, source, source_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (row[0], row[1], row[2], row[3], row[3], row[4], row[5], row[6], row[7], row[8],
                          "pilot3/pages.db", row[9]))
    for dk, pg in pages:
        row = other.execute("SELECT text, method, known_at FROM doc_page WHERE doc_key=? AND page=?", (dk, pg)).fetchone()
        if row and not conn.execute("SELECT 1 FROM doc_page WHERE doc_key=? AND page=?", (dk, pg)).fetchone():
            conn.execute("INSERT INTO doc_page (doc_key, symbol, page, text, method, chars, known_at) "
                         "VALUES (?,?,?,?,?,?,?)", (dk, symbol, pg, row[0], row[1], len(row[0]), row[2]))
            conn.execute("INSERT INTO doc_page_fts(rowid, text) VALUES (last_insert_rowid(), ?)", (row[0],))
    other.close()


# --- annual-report statement pages (annual reports that pages.db holds and this database does not) -------
AR_LABELS = [  # (line_item, statement, anchored regex over the lower-cased, space-joined label)
    ("cash_flow_from_operations", "CF", r"net cash .*operating activities"),
    ("cash_flow_from_investing", "CF", r"net cash .*investing activities"),
    ("cash_flow_from_financing", "CF", r"net cash .*financing activities"),
    ("capex_payments", "CF", r"payments? (?:to acquire|for) property,? plant and equipment.*"),
    ("dividends_paid", "CF", r"dividends? paid.*"),
    ("total_assets", "BS", r"total assets"),
    ("total_equity", "BS", r"total equity"),
]
_AR_RX = [(i, s, re.compile(rf"^(?:{rx})$")) for i, s, rx in AR_LABELS]
_AR_NUM = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$|^-$")
_AR_NOTE = re.compile(r"^\d{1,2}[A-Z]?(?: ?\([a-z]\))?$")


def ar_statement_rows(text: str) -> list[tuple]:
    """(line_item, statement, current-year value, prior-year value, quote) for the closed AR_LABELS on one
    consolidated / standalone statement page ('(` Crore)' pages only).  A label may wrap over lines; its numbers are
    the note reference (dropped) followed by the current and prior year."""
    if not re.search(r"`\s*crore|₹\s*crore", text, re.I):
        return []
    lines = [ln.strip() for ln in text.split("\n")]
    out, label, i = [], [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln or ln in ("-",) and not label:
            i += 1
            continue
        if _AR_NUM.match(ln) or (label and _AR_NOTE.match(ln)):
            nums = []
            j = i
            while j < len(lines) and len(nums) < 3 and (not lines[j] or _AR_NUM.match(lines[j]) or _AR_NOTE.match(lines[j])):
                if lines[j]:
                    nums.append(lines[j])
                j += 1
            vals = [n for n in nums if _AR_NUM.match(n)]
            if len(nums) == 3 and _AR_NOTE.match(nums[0]):
                vals = nums[1:]
            done = False
            for k in range(1, len(label) + 1):  # a wrapped label is the last k lines; earlier ones are page furniture
                name = re.sub(r"\s+", " ", " ".join(label[-k:])).strip().lower()
                for item, stmt, rx in _AR_RX:
                    if rx.match(name) and len(vals) >= 2:
                        cur = _number(vals[0]) if vals[0] != "-" else 0.0
                        prev = _number(vals[1]) if vals[1] != "-" else 0.0
                        if cur is not None and prev is not None:
                            out.append((item, stmt, cur, prev, f"{name} {vals[0]} {vals[1]}"))
                        done = True
                        break
                if done:
                    break
            label, i = [], j
            continue
        label = (label + [ln])[-3:] if not re.match(r"^[A-Z]\. ", ln) else [ln]
        i += 1
    return out


def build_ar_statements(conn: sqlite3.Connection) -> dict:
    """fin_annual_line rows (definition 'reported', period_type FY) from annual-report statement pages: only the
    reports pages.db holds that this database does not, so the newest year is not missing for want of ar_facts."""
    counts = {s: 0 for s in profile.symbols()}
    other = _other_pages()
    if other is None:
        return counts
    try:
        for symbol in profile.symbols():
            held = {r[0] for r in conn.execute("SELECT doc_key FROM doc WHERE symbol=? AND doc_type='annual_report'", (symbol,))}
            isin = conn.execute("SELECT isin FROM company WHERE symbol=? ORDER BY isin_from DESC LIMIT 1", (symbol,)).fetchone()
            isin = isin[0] if isin else None
            newest = conn.execute("SELECT MAX(known_at) FROM doc WHERE symbol=? AND doc_type='annual_report'", (symbol,)).fetchone()[0] or ""
            docs = [d for d in other.execute("SELECT doc_key, known_at, pages FROM doc WHERE symbol=? AND doc_type='annual_report' "
                                             "AND pages>50", (symbol,)) if d[0] not in held and (d[1] or "") > newest]
            rows, used = [], set()
            for dk, known, _pages in docs:
                for page, text in other.execute(
                        "SELECT page, text FROM doc_page WHERE doc_key=? AND (lower(text) LIKE '%cash flow%' OR "
                        "lower(text) LIKE '%total assets%')", (dk,)):
                    head = text[:300].upper()
                    basis = "consolidated" if "CONSOLIDATED FINANCIAL STATEMENTS" in head else \
                        "standalone" if "STANDALONE FINANCIAL STATEMENTS" in head else None
                    yr = re.search(r"Annual Report (20\d\d)-(\d\d)", text)
                    if not basis or not yr:
                        continue
                    fy = f"FY{yr.group(2)}"
                    prev = f"FY{int(yr.group(2)) - 1:02d}"
                    for item, stmt, cur, old, quote in ar_statement_rows(text):
                        for fiscal, value in ((fy, cur), (prev, old)):
                            if fiscal == prev and fiscal != fy:
                                continue  # the prior year is already held from its own report
                            rows.append((symbol, isin, fiscal, f"20{fiscal[2:]}-03-31", basis, stmt, item,
                                         f"{item.replace('_', ' ')} as printed in the annual report", value, "inr_crore", 1e7,
                                         dk, page, quote, "pages.db", "doc_page", f"{dk}#{page}", known,
                                         "doc_page.known_at (filing record of the document)", 1, 0, "reported", "FY"))
                        used.add((dk, page))
            conn.executemany("INSERT INTO fin_annual_line VALUES (" + ",".join("?" * COLS) + ")", rows)
            _import_pages(conn, symbol, used)
            counts[symbol] = len(rows)
    finally:
        other.close()
    conn.commit()
    return counts


def build_statements(conn: sqlite3.Connection) -> dict:
    result = {"xbrl_statements": build_xbrl_statements(conn), "dividends": build_dividends(conn)}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='doc_page'").fetchone():
        result["company_stated"] = build_company_stated(conn)
        result["ar_statements"] = build_ar_statements(conn)
    return result
