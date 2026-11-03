"""Question-set writer for the night loop (Phase 1, written by Claude, loop 1, 4 Nov 2026).

common.py holds the need helpers, the form generator and the questions every company gets (library U*/T* rewritten
for the last four quarters). Each co_*.py holds one company's sector and company questions. build.py writes
questions/<SYMBOL>.jsonl. Needs use the table's stored name when the pilot3 schema already has it, else the
sector_vocab id; `new_table` marks a table Phase 2 must add.
"""
from __future__ import annotations

from dataclasses import dataclass, field

AS_OF = "2026-11-04"
LAST_DAY = "2026-11-03"  # last session before as_of
NEW = "company fact from its own filings"


@dataclass
class Co:
    sym: str
    name: str
    short: str
    bse: str
    sector: str
    cls: str  # ind | bank | nbfc | ins
    quarters: list  # oldest to newest, e.g. ["Q3FY26", "Q4FY26", "Q1FY27", "Q2FY27"]
    call: str  # label of the latest call filed by as_of, e.g. "Q2 FY27"
    basis: str = "consolidated"
    promoter: str = ""  # promoter name; empty when the company has none
    rating_note: str = ""
    ytd: str = "H1FY27"
    peers_note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def lq(self):
        return self.quarters[-1]

    @property
    def pq(self):
        return self.quarters[-2]

    @property
    def lq_txt(self):
        return lab(self.lq)

    @property
    def pq_txt(self):
        return lab(self.pq)

    @property
    def ytd_txt(self):
        return lab(self.ytd)


def pretty(d: str) -> str:
    months = "January February March April May June July August September October November December".split()
    y, m, day = d.split("-")
    return f"{int(day)} {months[int(m) - 1]} {y}"


def lab(p: str) -> str:
    """Q2FY27 -> Q2 FY27."""
    return p[:-4] + " " + p[-4:] if len(p) > 4 and p[-4:-2] == "FY" else p


# --- needs -------------------------------------------------------------------------------------------------------
def K(metric, period, basis=None):
    return {"kind": "row", "table": "kpi_series", "metric": metric, "period": period, "basis": basis}


def F(line, period, basis="consolidated"):
    return {"kind": "row", "table": "fin_quarter_xbrl", "metric": line, "period": period, "basis": basis}


def A(line, year="FY26", basis="consolidated"):
    return {"kind": "row", "table": "fin_annual_line", "metric": line, "period": year, "basis": basis}


def R(metric, period, basis="consolidated"):
    return {"kind": "row", "table": "ratio_panel", "metric": metric, "period": period, "basis": basis}


def G(metric, period):
    return {"kind": "row", "table": "guidance", "metric": metric, "period": period, "basis": None}


def S(category, date):
    return {"kind": "row", "table": "shp_category", "metric": category, "period": date, "basis": None}


def P(column, date=LAST_DAY):
    return {"kind": "row", "table": "price_delivery", "metric": column, "period": date, "basis": None}


def V(metric, date=LAST_DAY):
    return {"kind": "row", "table": "valuation_daily", "metric": metric, "period": date, "basis": None}


def C(date="2026-09-30"):
    return {"kind": "row", "table": "share_capital", "metric": None, "period": date, "basis": None}


def Dv(year="FY26"):
    return {"kind": "row", "table": "dividend_event", "metric": None, "period": year, "basis": None}


def D(doc_type, *terms, period=None):
    need = {"kind": "text", "doc_type": doc_type, "terms": list(terms)}
    if period:
        need["period"] = period
    return need


def N(table, metric, period):
    return {"kind": "row", "table": table, "metric": metric, "period": period, "basis": None, "new_table": True}


def many(fn, metric, quarters, *args):
    return [fn(metric, q, *args) for q in quarters]


# --- one question ------------------------------------------------------------------------------------------------
def forms(co: Co, text: str) -> list:
    """Three other forms of a first-order question: ticker, BSE code and terse, relative period."""
    out = [text.replace(co.name, co.sym).replace(co.short, co.sym)]
    terse = text.replace(co.name, f"BSE {co.bse}").replace(co.short, f"BSE {co.bse}")
    out.append(terse[0].upper() + terse[1:])
    rel = text
    for old, new in ((co.lq_txt, "the latest quarter"), (co.pq_txt, "the quarter before last"),
                     ("FY26", "the last financial year"), (co.ytd_txt, "this financial year so far")):
        rel = rel.replace(old, new)
    if rel == text:
        rel = "As of today, " + text[0].lower() + text[1:]
    out.append(rel)
    seen, uniq = {text}, []
    for form in out:
        if form not in seen:
            seen.add(form)
            uniq.append(form)
    while len(uniq) < 3:
        uniq.append(f"{co.sym}: {text}" if len(uniq) == 0 else f"{text} ({co.sym}, as filed)" if len(uniq) == 1
                    else f"For {co.sym} (BSE {co.bse}): {text}")
    return uniq


def possessive(name: str) -> str:
    return name + ("'" if name.endswith("s") and name != "Infosys" else "'s")


def make(co: Co, n: int, spec: dict) -> dict:
    text = spec["text"].replace("{co}'s", possessive(co.name)).replace("{co}", co.name).replace("{short}", co.short).replace("{lq}", co.lq_txt) \
        .replace("{pq}", co.pq_txt).replace("{ytd}", co.ytd_txt).replace("{call}", co.call)
    order = spec["order"]
    variations = forms(co, text) if order == 1 else [text.replace(co.name, co.sym).replace(co.short, co.sym)]
    tid = spec.get("tid")
    row = {"qid": f"{co.sym}-{n:03d}", "symbol": co.sym, "sector": co.sector, "text": text, "variations": variations,
           "order": order, "lens": spec["lens"], "sector_fit": spec.get("fit", []),
           "from_mids": [tid] if tid else "new", "as_of": spec.get("as_of", AS_OF),
           "answer_kind": spec.get("kind", "text" if not spec.get("needs") else "number"),
           "needs": spec.get("needs", [])}
    if not tid:
        row["new_reason"] = spec.get("why", NEW)
    return row


def q(lens, order, text, needs=(), fit=(), tid=None, kind=None, as_of=None, why=None):
    spec = {"lens": lens, "order": order, "text": text, "needs": list(needs), "fit": list(fit)}
    if tid:
        spec["tid"] = tid
    if kind:
        spec["kind"] = kind
    if as_of:
        spec["as_of"] = as_of
    if why:
        spec["why"] = why
    return spec


# --- questions every company gets --------------------------------------------------------------------------------
def results(c: Co) -> list:
    b, L, Qs = c.basis, c.lq, c.quarters
    if c.cls == "ind":
        out = [
            q("results", 1, "What were {co}'s revenue, EBITDA and PAT in {lq}, and the YoY and QoQ growth the filing shows?",
              [F("revenue_from_operations", L, b), F("pat", L, b), R("ebitda", L, b), R("revenue_growth_yoy_pct", L, b)],
              ["revenue", "ebitda", "pat"], "U04"),
            q("results", 2, "How did {co}'s EBITDA margin and PAT margin move across the last four quarters, and what reasons did management give?",
              many(R, "ebitda_margin_pct", Qs, b) + many(R, "pat_margin_pct", Qs, b) + [D("transcript", "margin")],
              ["ebitda_margin", "pat_margin"], "U06", "number_series"),
            q("results", 2, "How much of {co}'s profit before tax in {lq} came from other income and exceptional items?",
              [F("other_income", L, b), F("exceptional_items", L, b), F("pbt", L, b)],
              ["other_income", "exceptional_items"], "U07", "computed"),
            q("results", 1, "What was {co}'s FY26 revenue, EBITDA, PAT and basic EPS?",
              [A("revenue_from_operations", "FY26", b), A("ebitda", "FY26", b), A("pat", "FY26", b), A("eps_basic", "FY26", b)],
              ["revenue", "ebitda", "pat", "eps"], "U04"),
            q("results", 2, "What are {co}'s trailing-twelve-month revenue and PAT, summing the last four quarters, and how do they compare with FY26?",
              many(F, "revenue_from_operations", Qs, b) + many(F, "pat", Qs, b) + [A("revenue_from_operations", "FY26", b)],
              ["revenue", "pat"], "U05", "computed"),
            q("results", 2, "How have {co}'s employee cost and other expenses moved as a share of revenue over the last four quarters?",
              many(F, "employee_cost", Qs, b) + many(F, "other_expenses", Qs, b) + many(F, "revenue_from_operations", Qs, b),
              ["revenue"], "U06", "computed"),
        ]
    elif c.cls in ("bank", "nbfc"):
        fin = "net_interest_income"
        out = [
            q("results", 1, "What were {co}'s net interest income, total income and PAT in {lq}, and the YoY growth the filing shows?",
              [F(fin, L, b), F("total_income", L, b), F("pat", L, b), R("pat_growth_yoy_pct", L, b)],
              ["nii", "pat"], "U04"),
            q("results", 2, "How did {co}'s PAT and net interest income move across the last four quarters?",
              many(F, "pat", Qs, b) + many(F, fin, Qs, b), ["nii", "pat"], "U06", "number_series"),
            q("results", 2, "How much of {co}'s profit before tax in {lq} came from other income, treasury gains or exceptional items?",
              [F("other_income", L, b), F("exceptional_items", L, b), F("pbt", L, b), D("press_release", "profit")],
              ["other_income", "exceptional_items"], "U07", "computed"),
            q("results", 1, "What was {co}'s FY26 total income, net interest income, PAT and basic EPS?",
              [A("total_income", "FY26", b), A(fin, "FY26", b), A("pat", "FY26", b), A("eps_basic", "FY26", b)],
              ["nii", "pat", "eps"], "U04"),
            q("results", 2, "What is {co}'s trailing-twelve-month PAT, summing the last four quarters, and how does it compare with FY26?",
              many(F, "pat", Qs, b) + [A("pat", "FY26", b)], ["pat"], "U05", "computed"),
            q("results", 2, "How have {co}'s employee cost and other operating expenses moved over the last four quarters?",
              many(F, "employee_cost", Qs, b) + many(F, "other_expenses", Qs, b), ["pat"], "U06", "number_series"),
        ]
    else:
        out = [
            q("results", 1, "What were {co}'s net premium income and PAT in {lq}, and the YoY growth the filing shows?",
              [K("gwp", L), F("pat", L, b), R("pat_growth_yoy_pct", L, b)], ["gwp", "pat"], "U04"),
            q("results", 2, "How did {co}'s PAT move across the last four quarters, and what does a life insurer's accounting profit leave out?",
              many(F, "pat", Qs, b) + [D("transcript", "profit")], ["pat"], "U06", "number_series"),
            q("results", 1, "What was {co}'s FY26 gross written premium, PAT and basic EPS?",
              [K("gwp", "FY26"), A("pat", "FY26", b), A("eps_basic", "FY26", b)], ["gwp", "pat", "eps"], "U04"),
            q("results", 2, "What is {co}'s trailing-twelve-month PAT, summing the last four quarters, and how does it compare with FY26?",
              many(F, "pat", Qs, b) + [A("pat", "FY26", b)], ["pat"], "U05", "computed"),
            q("results", 2, "How much investment income did {co} report in {ytd} on the policyholder and shareholder accounts?",
              [D("results", "income from investments")], ["pat"], "U07", "computed"),
        ]
    out += [
        q("results", 1, "When exactly (date and time) did {co} disclose its {lq} results, and was the disclosure before or after market close?",
          [D("results", "results", period=L)], ["pat"], "U32", "date"),
        q("results", 1, "Were {co}'s {lq} results audited or limited-review, and who signed the report?",
          [D("results", "review", period=L)], ["pat"], "U32", "text"),
        q("results", 2, "Do the figures in {co}'s {lq} presentation or press release match its filed results?",
          [D("deck" if c.sym not in ("ETERNAL", "INFY") else "results", "profit", period=L), F("pat", L, b)], ["pat"], "U36", "comparison"),
    ]
    return out


def segments_g(c: Co) -> list:
    b = c.basis
    return [
        q("segments", 1, "What does {co} sell, to whom, and how did revenue split across its reported segments in {lq}?",
          [K("segment_revenue", c.lq, b), D("results", "segment", period=c.lq)], ["segment_revenue"], "U01", "list"),
        q("segments", 2, "How has {co}'s segment mix shifted over the last four quarters, and which segment drives profit growth?",
          many(K, "segment_revenue", c.quarters, b) + many(K, "segment_ebit", c.quarters, b), ["segment_revenue", "segment_ebit"], "U02", "number_series"),
        q("segments", 1, "What was {co}'s segment profit by segment in {lq}?", [K("segment_ebit", c.lq, b)], ["segment_ebit"], "U01"),
        q("segments", 1, "How concentrated is {co} in its top customers, suppliers or geographies, as the FY26 annual report states it?",
          [D("annual_report", "customer")], ["segment_revenue"], "U03", "text"),
    ]


def guidance_g(c: Co) -> list:
    return [
        q("guidance", 1, "What numeric targets did {co}'s management give on the {call} call, and for which periods?",
          [D("transcript", "expect", period=c.call.replace(" ", "")), G("guidance", "FY27")], ["guidance"], "U21", "list"),
        q("guidance", 2, "Did {co} deliver on what it guided a year ago, and how did the guidance change across the last four calls?",
          [G("guidance", "FY26"), G("guidance", "FY27"), D("transcript", "guidance")], ["guidance"], "U22", "comparison"),
        q("guidance", 2, "What risks or headwinds did {co}'s management flag on the {call} call, and were they already flagged on the call before?",
          [D("transcript", "risk", period=c.call.replace(" ", "")), D("transcript", "headwind")], ["guidance"], "U23", "text"),
        q("guidance", 2, "What is the main bull case for {co} that management argues, and which figures in its filings over the next year would prove or disprove it?",
          [D("transcript", "growth"), D("annual_report", "strategy")], ["guidance"], "U44", "text"),
    ]


def balance_g(c: Co) -> list:
    b = c.basis
    if c.cls == "ind":
        out = [
            q("balance_sheet", 1, "What are {co}'s total borrowings, cash and investments, and net debt at the latest balance sheet date, and its net debt to EBITDA?",
              [A("total_borrowings", "FY26", b), A("cash_and_equivalents", "FY26", b), A("net_debt", "FY26", b), R("net_debt_to_ebitda", c.lq, b)],
              ["net_debt", "net_debt_to_ebitda"], "U13"),
            q("balance_sheet", 2, "What is {co}'s interest coverage, and how has its finance cost moved over the last four quarters?",
              many(F, "finance_cost", c.quarters, b) + [R("interest_coverage", c.lq, b)], ["interest_coverage", "finance_cost"], "U14", "number_series"),
            q("balance_sheet", 2, "What was {co}'s operating cash flow against PAT and EBITDA in FY26 (cash conversion)?",
              [A("cash_flow_from_operations", "FY26", b), A("pat", "FY26", b), A("ebitda", "FY26", b)], ["ocf", "pat", "ebitda"], "U09", "computed"),
            q("balance_sheet", 2, "What was {co}'s free cash flow after capex in FY26, and how was it used?",
              [A("cash_flow_from_operations", "FY26", b), A("capex", "FY26", b), A("dividends_paid", "FY26", b)], ["fcf", "capex"], "U10", "computed"),
            q("balance_sheet", 2, "How have {co}'s receivable, inventory and payable days moved between FY26 and the latest half-year balance sheet?",
              [R("receivable_days", "FY26", b), R("inventory_days", "FY26", b), R("payable_days", "FY26", b), D("results", "trade receivables")],
              ["receivable_days", "inventory_days", "payable_days"], "U11", "computed"),
            q("balance_sheet", 2, "Are {co}'s receivables or inventory growing faster than revenue?",
              [A("trade_receivables", "FY26", b), A("inventories", "FY26", b), D("results", "inventories")], ["receivable_days", "inventory_days"], "U12", "comparison"),
        ]
    elif c.cls in ("bank", "nbfc"):
        out = [
            q("balance_sheet", 1, "What are {co}'s total assets, net worth and total borrowings at the end of FY26?",
              [A("total_assets", "FY26", b), A("net_worth", "FY26", b), A("total_borrowings", "FY26", b)], ["net_debt"], "U13"),
            q("balance_sheet", 2, "How has {co}'s finance cost moved over the last four quarters against its interest income?",
              many(F, "finance_cost", c.quarters, b) + many(F, "interest_income", c.quarters, b), ["finance_cost"], "U14", "number_series"),
            q("balance_sheet", 2, "What was {co}'s operating cash flow in FY26, and what drove the sign of it for a lender?",
              [A("cash_flow_from_operations", "FY26", b)], ["ocf"], "U09", "number"),
        ]
    else:
        out = [
            q("balance_sheet", 1, "What are {co}'s total assets and shareholders' funds at the end of FY26?",
              [A("total_assets", "FY26", b), A("net_worth", "FY26", b)], ["ocf"], "U13"),
            q("balance_sheet", 2, "What was {co}'s operating cash flow in FY26, and how much came from renewal premium collections?",
              [A("cash_flow_from_operations", "FY26", b), D("annual_report", "cash flow")], ["ocf"], "U09", "number"),
        ]
    out += [
        q("balance_sheet", 1, "Did {co}'s auditor flag a qualified opinion, going-concern uncertainty or emphasis of matter in FY26?",
          [D("annual_report", "emphasis of matter")], ["contingent_liabilities"], "U16", "yes_no"),
        q("balance_sheet", 1, "What contingent liabilities does {co} disclose at the end of FY26, relative to its net worth?",
          [D("annual_report", "contingent liabilities"), A("net_worth", "FY26", b)], ["contingent_liabilities"], "U17"),
    ]
    return out


def capital_g(c: Co) -> list:
    b = c.basis
    out = [
        q("capital_allocation", 1, "What dividends did {co} pay for FY26, with record dates, and what payout ratio does that make?",
          [Dv("FY26"), R("dividend_payout_pct", "FY26", b)], ["dividend_per_share", "payout_ratio"], "U19"),
        q("capital_allocation", 1, "Has {co} raised equity (QIP, rights, preferential, ESOP allotments) or issued shares in the last year, and at what price?",
          [D("announcement", "allotment"), C()], ["dividend_per_share"], "U20", "list"),
        q("capital_allocation", 1, "What acquisitions, stake purchases or disposals has {co} announced since November 2025, and at what value?",
          [D("announcement", "acquisition")], ["capex"], "U20", "list"),
        q("capital_allocation", 2, "What share of {co}'s FY26 profit went to dividends and buybacks, and what share stayed in the business?",
          [Dv("FY26"), A("pat", "FY26", b), A("dividends_paid", "FY26", b)], ["payout_ratio", "pat"], "U19", "computed"),
    ]
    if c.cls == "ind":
        out += [
            q("capital_allocation", 1, "What capex did {co} spend in FY26 and {ytd}, and on what?",
              [A("capex", "FY26", b), D("results", "purchase"), D("transcript", "capex")], ["capex"], "U18"),
            q("capital_allocation", 2, "Is the return on {co}'s recent capex (incremental ROCE) above what it earned before?",
              [R("roce", "FY26", b), A("capex", "FY26", b), D("transcript", "capex")], ["roce", "capex"], "U43", "computed"),
            q("capital_allocation", 2, "What are {co}'s ROE and ROCE for FY26, and are they rising or falling on the latest half?",
              [R("roe", "FY26", b), R("roce", "FY26", b)], ["roe", "roce"], "U08", "computed"),
        ]
    else:
        out += [
            q("capital_allocation", 2, "What is {co}'s ROE for FY26, and is it rising or falling on the latest quarter?",
              [R("roe", "FY26", b), R("roe", c.lq, b)], ["roe"], "U08", "computed"),
        ]
    return out


def ownership_g(c: Co) -> list:
    d, pd = "2026-09-30", "2026-06-30"
    if c.sym == "HINDALCO":
        d, pd = "2026-06-30", "2026-03-31"
    hold = [("mar", "2025-12-31"), ("mar", "2026-03-31"), ("jun", "2026-06-30"), ("sep", "2026-09-30")]
    dates = [h[1] for h in hold if h[1] <= d]
    prom = c.promoter
    dt, pdt = pretty(d), pretty(pd)
    out = []
    if prom:
        out += [
            q("ownership", 1, f"What is {{co}}'s promoter holding ({prom}) at {dt}, and how did it change over the last four quarters?",
              many(S, "promoter", dates), ["promoter_holding"], "U24", "number_series"),
            q("ownership", 1, "What share of {co}'s promoter holding is pledged or encumbered at the latest quarter, and has it changed?",
              [S("pledge_pct", d)], ["pledge_pct"], "U25"),
        ]
    else:
        out += [
            q("ownership", 1, f"{{co}} has no promoter group: what is the public shareholding at {dt}, and who holds the largest disclosed blocks?",
              [S("public", d)], ["fii_holding"], "U24", "list"),
            q("ownership", 1, "Do any shareholders of {co} hold above 5% according to the latest shareholding pattern, and did the list change over the year?",
              [D("announcement", "shareholding")], ["fii_holding"], "U24", "list"),
        ]
    out += [
        q("ownership", 1, f"What share of {{co}} did foreign portfolio investors hold at {dt}, against the quarter before?",
          [S("fpi_total", d), S("fpi_total", pd)], ["fii_holding"], "U26"),
        q("ownership", 1, f"What share of {{co}} did mutual funds hold at {dt}, against the quarter before?",
          [S("mutual_funds", d), S("mutual_funds", pd)], ["mf_holding"], "U26"),
        q("ownership", 1, f"What share of {{co}} did insurance companies hold at {dt}?", [S("insurance", d)], ["dii_holding"], "U26"),
        q("ownership", 1, f"What share of {{co}} did small retail holders (up to Rs 2 lakh) hold at {dt}, and how many of them were there?",
          [S("retail_up_to_2_lakh", d)], ["retail_holding"], "U26"),
        q("ownership", 2, "Who has been buying and who selling {co} over the last four quarters: FPIs, mutual funds, insurers or retail?",
          many(S, "fpi_total", dates) + many(S, "mutual_funds", dates) + many(S, "retail_up_to_2_lakh", dates),
          ["fii_holding", "mf_holding", "retail_holding"], "U26", "number_series"),
        q("ownership", 1, "Which insiders or promoter entities of {co} bought or sold shares since November 2025 (SAST and insider-trading disclosures)?",
          [D("announcement", "SAST"), N("insider_trade", "insider_trade", "FY27")], ["promoter_holding"], "U27", "list"),
        q("ownership", 1, "How many shares of {co} were outstanding at the latest date, and how did the count change over the year?",
          [C()], ["market_cap"], "U20"),
        q("ownership", 2, "Did institutional holding in {co} rise in the same quarters that its delivery percentage rose?",
          many(S, "fpi_total", dates) + [P("delivery_pct")], ["fii_holding", "delivery_pct"], "T06", "comparison"),
    ]
    return out


NO_RATED_DEBT = ("ETERNAL", "INFY", "HINDUNILVR", "SBILIFE")


def ratings_none(c: Co) -> list:
    """Companies with no rating filing in the window: what an investor asks instead is whether debt and ratings matter."""
    b = c.basis
    lease = "lease liabilities" if c.cls == "ind" else "subordinated debt"
    return [
        q("credit_ratings", 1, c.rating_note, [D("annual_report", "credit rating")], ["credit_rating"], "U15", "text"),
        q("credit_ratings", 1, "Did {co} file any credit rating action with the exchanges since November 2025?", [D("announcement", "rating")], ["credit_rating"], "U15", "yes_no"),
        q("credit_ratings", 1, "What ESG ratings has {co} disclosed to the exchanges since November 2025, and from whom?", [D("announcement", "ESG")], ["credit_rating"], "U15", "list"),
        q("credit_ratings", 1, "How much rated or unrated debt does {co} have outstanding at the end of FY26, by instrument?", [A("total_borrowings", "FY26", b), D("annual_report", "borrowings")], ["credit_rating", "net_debt"], "U15", "number"),
        q("credit_ratings", 1, "What bank limits, commercial paper or non-convertible debentures does {co}'s FY26 annual report show?", [D("annual_report", "debentures")], ["credit_rating"], "U15", "list"),
        q("credit_ratings", 1, f"What {lease} does {{co}} carry at the end of FY26, which a rating agency would count as debt?", [D("annual_report", lease)], ["credit_rating"], "U15", "number"),
        q("credit_ratings", 1, "Has {co} given corporate guarantees for subsidiaries or others, and for how much, at the end of FY26?", [D("annual_report", "guarantee")], ["credit_rating", "contingent_liabilities"], "U17", "number"),
        q("credit_ratings", 2, "Does {co}'s cash cover its total debt, so that a credit rating has little bearing on it?", [A("cash_and_equivalents", "FY26", b), A("total_borrowings", "FY26", b)], ["credit_rating", "net_debt"], "U13", "computed"),
        q("credit_ratings", 2, "Do any of {co}'s subsidiaries hold ratings of their own, and do they rely on a parent guarantee?", [D("annual_report", "subsidiar", "rating")], ["credit_rating"], "U15", "text"),
        q("credit_ratings", 3, "If {co} borrowed to fund a large acquisition, how much debt could it take before reaching a leverage that normally costs a top rating?", [A("net_worth", "FY26", b), F("pat", c.lq, b)], ["credit_rating", "net_debt"], "U38", "computed"),
    ]


def ratings_g(c: Co) -> list:
    if c.sym in NO_RATED_DEBT:
        return ratings_none(c)
    note = c.rating_note
    return [
        q("credit_ratings", 1, "What is {co}'s current long-term credit rating and outlook, and from which agency?",
          [D("announcement", "credit rating")], ["credit_rating"], "U15", "text"),
        q("credit_ratings", 1, "What short-term or commercial-paper rating does {co} hold?", [D("announcement", "rating", "short")], ["credit_rating"], "U15", "text"),
        q("credit_ratings", 1, "What rating actions on {co} happened since November 2025 (upgrade, downgrade, reaffirmed, withdrawn), with dates?",
          [D("announcement", "rating")], ["credit_rating"], "U15", "list"),
        q("credit_ratings", 1, "Which instruments of {co} are rated, and for what amounts?", [D("announcement", "rating", "crore")], ["credit_rating"], "U15", "list"),
        q("credit_ratings", 1, "Does {co}'s annual report name its credit ratings, and do they agree with the latest exchange filing?",
          [D("annual_report", "credit rating"), D("announcement", "rating")], ["credit_rating"], "U15", "comparison"),
        q("credit_ratings", 1, f"{note or 'Does {co} hold any international credit rating as well as a domestic one?'}",
          [D("announcement", "rating")], ["credit_rating"], "U15", "text"),
        q("credit_ratings", 2, "Did {co}'s stock move on the days its rating actions were disclosed since November 2025?",
          [D("announcement", "rating"), P("close")], ["credit_rating", "close"], "T08", "comparison"),
        q("credit_ratings", 2, "Is {co}'s rating consistent with how its leverage or capital has moved over the last four quarters?",
          [D("announcement", "rating"), R("debt_to_equity", "FY26", c.basis)], ["credit_rating"], "U15", "comparison"),
        q("credit_ratings", 2, "What reasons did the rating agency give for {co}'s rating, and what would trigger a change?",
          [D("announcement", "rating", "outlook")], ["credit_rating"], "U15", "text"),
        q("credit_ratings", 3, "If {co}'s rating were cut by one notch, what would that do to its funding cost or business, given what it has disclosed?",
          [D("announcement", "rating"), D("annual_report", "credit rating")], ["credit_rating", "finance_cost"], "U38", "text"),
    ]


def governance_g(c: Co) -> list:
    return [
        q("governance", 1, "What related-party transactions does {co} report for FY26, and how large are they against revenue or net worth?",
          [D("annual_report", "related party")], ["related_party_transactions"], "U28", "text"),
        q("governance", 1, "Which directors, the CEO, CFO, auditor or company secretary of {co} changed since November 2025, and why?",
          [D("announcement", "appointment")], ["related_party_transactions"], "U29", "list"),
        q("governance", 1, "How much were {co}'s top executives paid in FY26, relative to profit, and how did pay change?",
          [D("annual_report", "remuneration")], ["pat"], "U30", "number"),
        q("governance", 1, "Who are {co}'s statutory auditors and what were they paid in FY26?", [D("annual_report", "auditor")], ["related_party_transactions"], "U29", "text"),
        q("governance", 1, "Did {co} receive tax demands, penalties or regulatory orders since November 2025, and are they material relative to profit?",
          [D("announcement", "order"), D("announcement", "penalty")], ["contingent_liabilities"], "U48", "list"),
        q("governance", 1, "What material announcements did {co} make in {lq}?", [D("announcement", "intimation", period=c.lq)], ["related_party_transactions"], "U31", "list"),
        q("governance", 1, "What did {co}'s shareholders vote on at the 2026 AGM, and did any resolution fail or pass narrowly?",
          [D("announcement", "resolution")], ["related_party_transactions"], "U31", "list"),
        q("governance", 2, "How much do {co}'s employee stock options dilute shareholders, from the FY26 annual report and allotments since?",
          [D("annual_report", "stock option"), D("announcement", "allotment"), C()], ["market_cap"], "U20", "computed"),
    ]


def technical_g(c: Co) -> list:
    L = c.lq
    return [
        q("technical", 2, "Is {co} trading above or below its 50-day and 200-day moving averages, and when did it last cross them?", [P("close")], ["close", "dma_50", "dma_200"], "T01", "computed"),
        q("technical", 2, "How far is {co} from its 52-week high and low, and on which days were they made?", [P("high"), P("low"), P("high", "2025-11-03")], ["high_52w", "low_52w"], "T02", "computed"),
        q("technical", 2, "How has {co} performed over 1, 3, 6 and 12 months against the Nifty 50?", [P("close"), P("close", "2025-11-03"), N("index_price", "relative_return", LAST_DAY)], ["return_1m", "return_12m", "relative_return"], "T03", "computed"),
        q("technical", 2, "On which days in the last year was {co}'s volume more than 3 times its 20-day average, and what did the price do?", [P("volume"), P("close")], ["volume", "volume_ratio_20d"], "T04", "list"),
        q("technical", 2, "What is {co}'s delivery percentage trend over the last quarter, and on which days did it jump well above its own average?", [P("delivery_pct")], ["delivery_pct"], "T05", "list"),
        q("technical", 2, "How did {co}'s price and volume react in the 5 sessions after each of its last 4 results announcements?", [P("close"), D("results", "results", period=L)], ["close", "volume"], "T07", "number_series"),
        q("technical", 2, "How did {co}'s stock react on day 0 to day 3 after its largest announcements since November 2025?", [P("close"), D("announcement", "intimation")], ["close"], "T08", "comparison"),
        q("technical", 2, "What are {co}'s maximum drawdown and daily volatility over the last year?", [P("close")], ["drawdown", "volatility"], "T09", "computed"),
        q("technical", 2, "Where are {co}'s recent swing highs and lows, and has the price broken any of them?", [P("high"), P("low")], ["close"], "T10", "list"),
        q("technical", 2, "When did {co} last gap up or down by more than 3%, and was the gap filled?", [P("open"), P("close")], ["gap"], "T11", "date"),
        q("technical", 1, "What is {co}'s average daily traded value over the last 3 months?", [P("value_inr")], ["traded_value"], "T12", "number"),
        q("technical", 1, "Were there bulk or block deals in {co} since November 2025, who were the buyers and sellers, and at what price?", [N("bulk_block_deal", "block_deal", "FY27")], ["bulk_deal", "block_deal"], "T13", "list"),
        q("technical", 2, "What is {co}'s 14-day RSI today, and has momentum diverged from price in the last month?", [P("close")], ["rsi_14"], "T14", "computed"),
        q("technical", 1, "What was {co}'s closing price, volume and delivery percentage on the last trading day?", [P("close"), P("volume"), P("delivery_pct")], ["close", "volume", "delivery_pct"], "T05", "number"),
        q("technical", 1, "What was {co}'s closing price and delivery quantity on 30 September 2026?", [P("close", "2026-09-30"), P("deliverable_qty", "2026-09-30")], ["close", "delivery_qty"], "T05", "number", "2026-11-04"),
        q("technical", 2, "How did {co}'s price behave around its last ex-dividend date?", [Dv("FY26"), P("close")], ["close", "dividend_per_share"], "T16", "comparison"),
    ]


def valuation_g(c: Co) -> list:
    out = [
        q("valuation", 1, "What are {co}'s market capitalisation, shares outstanding and dividend yield today?", [V("market_cap"), V("dividend_yield_pct"), C()], ["market_cap", "dividend_yield"], "U35"),
        q("valuation", 1, "What was {co}'s market capitalisation on 30 September 2026?", [V("market_cap", "2026-09-30")], ["market_cap"], "U35"),
        q("valuation", 1, "What is {co}'s trailing PE and price to book today?", [V("pe"), V("pb")], ["pe", "pb"], "U33"),
        q("valuation", 2, "How does {co}'s trailing PE today compare with its range over the last year?", [V("pe"), V("pe", "2025-11-03")], ["pe"], "U33", "comparison"),
        q("valuation", 2, "At {co}'s current valuation, what profit growth does the price imply, and has it delivered that in the last four quarters?",
          [V("pe"), R("pat_growth_yoy_pct", c.lq, c.basis)], ["pe", "pat"], "U45", "computed"),
        q("valuation", 2, "How much has {co}'s valuation changed from before its last results to today, and how much of the price move was earnings?",
          [V("pe"), V("pe", "2026-09-30"), F("pat", c.lq, c.basis)], ["pe", "pat"], "U33", "computed"),
    ]
    if c.cls == "ind":
        out += [q("valuation", 1, "What is {co}'s EV to EBITDA today?", [V("ev_ebitda")], ["ev_ebitda"], "U33"),
                q("valuation", 2, "How does {co}'s EV to EBITDA today compare with its level a year ago?", [V("ev_ebitda"), V("ev_ebitda", "2025-11-03")], ["ev_ebitda"], "U33", "comparison")]
    return out


def ripple_g(c: Co) -> list:
    """Generic third-order questions that make sense for every company in the pilot."""
    return [
        q("results", 3, "Which government policy, budget item or regulation since November 2025 affected {co}, and how did management describe the impact?",
          [D("transcript", "regulation"), D("annual_report", "regulatory")], ["pat"], "U41", "text"),
        q("guidance", 3, "Trace one chain for {co}: a named policy or price change since November 2025, its effect on the industry, then on {co}'s revenue or cost, with the lag its own numbers show.",
          [D("transcript", "impact"), F("pat", c.lq, c.basis)], ["pat"], "U47", "text"),
    ]


def universal(c: Co) -> list:
    return (results(c) + segments_g(c) + guidance_g(c) + balance_g(c) + capital_g(c) + ownership_g(c) + ratings_g(c)
            + governance_g(c) + technical_g(c) + valuation_g(c) + ripple_g(c))
