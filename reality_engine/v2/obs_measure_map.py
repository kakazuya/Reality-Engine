"""T-241: canonical measure map and junk quarantine for hy4 observations.

Reads a finished ``observations.py`` SQLite database, copies it via SQLite's
backup API to ``--out`` (never modifying ``--obs``), quarantines deterministic
junk ``NEW:*`` rows (page counts, years, call/filing dates, clock times,
registration/ID codes, contact/address numbers, Q&A question counts), maps
normalised and synonym-matched names to ``measure_dict`` / ``measure_alias``,
and clusters remaining ``NEW:*`` names occurring in >= 3 companies within
matching unit families.

Junk rules (all require BOTH a bare-name pattern AND a value/unit check)
------------------------------------------------------------------------
1. ``page_count``:
   Name matches ``total_pages``, ``total_page_count``, ``page_count``,
   ``page_number``, ``pages``, ``slide_number``, ``slide_count``,
   ``page_reference``, ``pdf_page_count``, ``pdf_page_number`` (token-bounded).
   Value check: ``record_type != 'statement'``, unit is empty or in
   ``{'page', 'pages', 'page(s)', 'number', 'numbers', 'slide', 'slides',
   'pdf', '#'}``, and ``value_text`` carries digits.
2. ``year_or_period_label``:
   Name matches ``launch_year``, ``fiscal_year*``, ``calendar_year``,
   ``financial_year``, ``reporting_year``, ``listing_regulation_year``,
   ``incorporation_year``, ``established_year``, ``founding_year``,
   ``half_year_identifier``, ``quarter_identifier``, ``*_call_quarter``,
   ``results_period``, or bare ``year`` / ``fy`` / ``q[1-4]``.
   Value check: ``record_type != 'statement'``, effective unit family is not a
   financial/duration/physical metric (and unit is not ``years``/``months``/
   ``days``/``quarters``/``weeks``), AND either ``value`` is a year integer
   ``1900..2050`` with unit in ``{'', 'year', 'number', 'fiscal year', 'fy'}``
   or ``value_text``/``unit`` is a fiscal/quarter/date/timestamp/floor label.
3. ``call_or_filing_date``:
   Name matches ``conference_call_date``, ``earnings_call_date``, ``call_date``,
   ``intimation_date``, ``communication_date``, ``board_meeting_date``,
   ``filing_date``, ``letter_date``, ``meeting_date``, ``transcript_date``,
   ``release_date``, ``publication_date``, ``record_date``, ``cutoff_date``,
   ``signature_date``, ``circular_date``, ``notice_date``, ``disclosure_date``,
   ``event_date``, ``announcement_date``, or bare ``date``.
   Value check: ``record_type != 'statement'``, unit is empty or date/time
   label (not duration/currency/percent), and ``value_text`` contains a month,
   date separator, 4-digit year, ordinal, or day/year integer.
4. ``call_time``:
   Name matches ``conference_call_time``, ``earnings_call_time``,
   ``call_time``, ``meeting_time``, ``start_time``, ``end_time``, ``ist_time``.
   Value check: ``record_type != 'statement'``, effective unit family is not a
   financial/percent metric, and ``unit + value_text`` contains ``hh:mm``,
   ``am``/``pm``, ``ist``, ``hrs``, or ``+05'30``.
5. ``identifier_or_reg``:
   Name matches ``cin``, ``din``, ``isin``, ``pan``, ``gstin``, ``tan``,
   ``lei``, ``scrip_code``, ``script_code``, ``security_code``,
   ``company_code``, ``*_identification_number``, ``registration_number``,
   ``*membership_number``, ``reference_number``, ``ref_number``, ``ref_no``,
   ``serial_number``, ``survey_number``, ``*regulation_number``,
   ``annual_general_meeting_number``, ``agm_number``, ``block_identifier``,
   ``snake_case_id``.
   Value check: ``record_type != 'statement'``, effective unit family is not
   ``money``/``percent``/``bps``/``capacity``/``money_per_unit``, and
   ``value_text`` is non-empty.
6. ``contact_or_address``:
   Name matches ``phone``, ``telephone``, ``mobile``, ``fax``, ``pin_code``,
   ``pincode``, ``postal_code``, ``zip_code``, ``building_number``,
   ``*address_number``, ``floor_number``, ``*plot_number``, ``street_number``.
   Value check: ``record_type != 'statement'``, effective unit family is not
   ``money``/``percent``/``bps``/``capacity``/``money_per_unit``, and
   ``value_text`` is non-empty.
7. ``qa_question_count``:
   Name matches ``question_count`` or ``number_of_questions``.
   Value check: ``record_type != 'statement'``, unit is empty or question
   label, and ``value`` is a small count ``1..30``.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from reality_engine.db.readonly import connect_ro
from reality_engine.v2 import observations as obs_mod

NEW_PREFIX = obs_mod.NEW_PREFIX

# Clean unit-family patterns: fixes ``observations.py``'s ``rs\b`` without leading
# word boundary (which tagged ``years`` and ``quarters`` as ``money``), and adds
# full-word power/time/count units found in transcript observations.
_CLEAN_UNIT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("bps", r"\bbps\b|\bbasis points?\b"),
    ("percent", r"%|percent\b|\bpct\b"),
    (
        "money_per_unit",
        r"(?:\brs\.?|\binr\b|₹|\$|usd|us\$)[^a-z]*(?:per\b|/)"
        r"|/\s*(?:tonne|ton|unit|km|kg|mt|share|litre|liter|barrel|kwh|mwh)\b"
        r"|(?:^|\s)per\s+(?:tonne|ton|kg|km|mt|share|unit|litre|liter|barrel|employee|customer|store|branch|bed|room)\b"
        r"|\barpu\b|\barr\b|\brevpar\b",
    ),
    (
        "energy",
        r"\bmus?\b|\bmwh\b|\bgwh\b|\bkwh\b|\bbu\b|\bmu\b"
        r"|\b(?:mn|million|bn|billion)\s+units?\b",
    ),
    (
        "capacity",
        r"\bmtpa\b|\bmmtpa\b|\btpa\b|\btpd\b|\btonnes?\b|\btons?\b|\bmt\b"
        r"|\bmegawatts?\b|\bgigawatts?\b|\bkilowatts?\b|\bmw\b|\bgw\b|\bkw\b",
    ),
    (
        "area",
        r"\bsft\b|sq\.?\s*ft|square\s+feet|\bsqm\b|sq\.?\s*m(?:et(?:er|re)s?)?\b"
        r"|square\s+met(?:er|re)s?\b|\bhectares?\b|\bacres?\b",
    ),
    ("length", r"\bkm\b|\bkilomet(?:er|re)s?\b|\bmiles?\b|\bmet(?:er|re)s?\b|\bmillimet(?:er|re)s?\b"),
    ("time", r"\bdays?\b|\bweeks?\b|\bmonths?\b|\bquarters?\b|\byears?\b|\bhours?\b|\bhrs\b"),
    (
        "money",
        r"\brs\.?\b|\binr\b|₹|\brupees?\b|\bcrores?\b|\bcrs?\b|\bcr\.?\b"
        r"|\blakhs?\b|\blacs?\b|\bmillions?\b|\bmn\b|\bbillions?\b|\bbn\b"
        r"|\busd\b|us\$|\$|\beuros?\b|\beur\b",
    ),
    (
        "count",
        r"\bunits?\b|\bnos\.?\b|\bnumbers?\b|\bthousands?\b|\bteus?\b|\bvehicles?\b"
        r"|\btractors?\b|\bcustomers?\b|\bsubscribers?\b|\bplants?\b|\bterminals?\b"
        r"|\binstances?\b|\blit(?:er|re)s?\b|\bltrs?\b|\bpeople\b|\bpersons\b"
        r"|\bemployees?\b|\bstores?\b|\bbranches\b|\brooms?\b|\bbeds?\b|\btowers?\b|\bsites?\b",
    ),
    ("ratio", r"^x$|\btimes\b|\bmultiple\b"),
)
_CURRENCY_HINT_RE = re.compile(
    r"\brs\.?\b|\binr\b|₹|\brupees?\b|\bcrores?\b|\bcrs?\b|\bcr\.?\b"
    r"|\blakhs?\b|\blacs?\b|\bmillions?\b|\bmn\b|\bbillions?\b|\bbn\b"
    r"|\busd\b|us\$|\$|\beuros?\b|\beur\b",
    re.I,
)

# --------------------------------------------------------------------------- Step 3: Junk rules

_JUNK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "page_count",
        re.compile(
            r"(?:^|_)(?:total_pages|total_page_count|page_count|page_number|pages|"
            r"slide_number|slide_count|page_reference|pdf_page_count|pdf_page_number)(?:_|$)"
        ),
    ),
    (
        "year_or_period_label",
        re.compile(
            r"(?:^|_)(?:launch_year|fiscal_year|calendar_year|financial_year|reporting_year|"
            r"listing_regulation_year|incorporation_year|established_year|founding_year|"
            r"fiscal_year_identifier|fiscal_year_reference|fiscal_year_label|"
            r"half_year_identifier|quarter_identifier|earnings_call_quarter|"
            r"conference_call_quarter|results_period)(?:_|$)|^(?:year|fy|q[1-4])$"
        ),
    ),
    (
        "call_or_filing_date",
        re.compile(
            r"^(?:date)$|(?:^|_)(?:conference_call_date|earnings_call_date|call_date|intimation_date|"
            r"communication_date|board_meeting_date|filing_date|prior_letter_date|letter_date|"
            r"meeting_date|transcript_date|release_date|publication_date|record_date|"
            r"cutoff_date|signature_date|signing_date|digital_signature_date|circular_date|"
            r"notice_date|disclosure_date|event_date|announcement_date)(?:_|$)"
        ),
    ),
    (
        "call_time",
        re.compile(
            r"(?:^|_)(?:conference_call_time|earnings_call_time|call_time|"
            r"meeting_time|start_time|end_time|ist_time)(?:_|$)"
        ),
    ),
    (
        "identifier_or_reg",
        re.compile(
            r"(?:^|_)(?:cin|din|isin|pan|gstin|tan|lei|scrip_code|script_code|security_code|"
            r"company_code|company_identification_number|corporate_identification_number|"
            r"director_identification_number|permanent_account_number|registration_number|"
            r"company_secretary_membership_number|membership_number|reference_number|"
            r"ref_number|ref_no|serial_number|survey_number|listing_regulation_number|"
            r"sebi_regulation_number|regulation_number|annual_general_meeting_number|"
            r"agm_number|block_identifier|snake_case_id|pseudonym|digital_signature)(?:_|$)"
        ),
    ),
    (
        "contact_or_address",
        re.compile(
            r"(?:^|_)(?:phone|telephone|mobile|fax|pin_code|pincode|postal_code|zip_code|"
            r"building_number|exchange_address_number|listing_address_number|"
            r"office_address_number|head_office_address_number|head_office_building_number|"
            r"address_number|floor_number|plot_number|exchange_plot_number|street_number)(?:_|$)"
        ),
    ),
    (
        "qa_question_count",
        re.compile(r"(?:^|_)(?:question_count|number_of_questions)(?:_|$)"),
    ),
)

_PAGE_UNITS = {"", "page", "pages", "page(s)", "number", "numbers", "slide", "slides", "pdf", "#"}
_DURATION_UNITS = {"years", "months", "days", "quarters", "weeks"}
_YEAR_LABEL_UNITS = {
    "", "year", "number", "fiscal year", "fy", "q", "quarter", "p.m.", "pm",
    "a.m.", "am", "ist", "pm ist", "p.m. (ist)", "am (ist)", "+05'30'",
    "floor", "unit", "date", "time",
}
_DATE_UNITS = {"", "date", "day", "time", "a.m.", "p.m.", "am", "pm", "a.m. (ist)", "p.m. (ist)", "ist"}
_NON_JUNK_FAMILIES = {"money", "percent", "bps", "capacity", "money_per_unit", "ratio", "area", "length", "energy"}
_MONTH_OR_DATE_RE = re.compile(
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
    r"\d{4}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\b(?:19|20)\d{2}\b|"
    r"\b\d{1,2}(?:st|nd|rd|th)\b)",
    re.I,
)
_FY_Q_TOKEN_RE = re.compile(
    r"(?:fy\s*'?\d{2,4}|q[1-4]|h[12]|'\d{2}\b|\b\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b)",
    re.I,
)
_CLOCK_RE = re.compile(r"\d{1,2}[:.]\d{2}|a\.?m\.?|p\.?m\.?|\bist\b|\bhrs\b|\+05'?30", re.I)
_CODE_OR_ADDR_LABEL_RE = re.compile(r"\b(?:scrip|script|security|pin|code|unit|floor|plot|reg|regulation)\b", re.I)


def strip_new_prefix(measure: str) -> str:
    """Return lowercased bare id with ``NEW:`` and ``<...>`` removed."""
    s = obs_mod.norm_space(measure)
    if s.lower().startswith(NEW_PREFIX.lower()):
        s = s[len(NEW_PREFIX):].strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    return s.lower()


def effective_unit_family(unit: str, stored_family: str = "") -> str:
    """Infer unit family cleanly from ``unit``, fixing ``observations.py``'s ``rs`` plural bug."""
    low = obs_mod.norm_space(unit).lower()
    if low:
        for family, pattern in _CLEAN_UNIT_PATTERNS:
            if re.search(pattern, low):
                return family
    sf = obs_mod.norm_space(stored_family).lower()
    if sf == "money" and low and not _CURRENCY_HINT_RE.search(low):
        return ""
    return sf


def _is_int_in_range(value: Any, lo: int, hi: int) -> bool:
    if value is None:
        return False
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return f.is_integer() and lo <= int(f) <= hi


def classify_junk(
    bare_name: str,
    record_type: str,
    value: Any,
    value_text: str,
    unit: str,
    stored_unit_family: str = "",
    printed_label: str = "",
) -> str | None:
    """Return junk pattern name if both name pattern and value/unit check fire, else ``None``."""
    if (record_type or "").lower() == "statement":
        return None
    vt = obs_mod.norm_space(value_text)
    u_low = obs_mod.norm_space(unit).lower()
    eff_uf = effective_unit_family(unit, stored_unit_family)
    if bare_name == "launch_year" and u_low == "unit":
        eff_uf = ""

    for pname, pat in _JUNK_PATTERNS:
        if not pat.search(bare_name):
            continue
        if pname == "page_count":
            if u_low in _PAGE_UNITS and re.search(r"\d", vt):
                return pname
        elif pname == "year_or_period_label":
            if eff_uf in _NON_JUNK_FAMILIES or u_low in _DURATION_UNITS:
                continue
            unit_ok = u_low in _YEAR_LABEL_UNITS or bool(re.match(r"^fy\d+$", u_low))
            if not unit_ok:
                continue
            if (
                _is_int_in_range(value, 1900, 2050)
                or _FY_Q_TOKEN_RE.search(vt)
                or _MONTH_OR_DATE_RE.search(vt)
                or u_low != ""
                or _CODE_OR_ADDR_LABEL_RE.search(printed_label or "")
            ):
                return pname
        elif pname == "call_or_filing_date":
            if eff_uf in ("", "time") and u_low in _DATE_UNITS:
                if _MONTH_OR_DATE_RE.search(vt) or _is_int_in_range(value, 1, 31) or _is_int_in_range(value, 1900, 2050):
                    return pname
        elif pname == "call_time":
            if eff_uf in ("", "time") and _CLOCK_RE.search(f"{u_low} {vt}"):
                return pname
        elif pname in ("identifier_or_reg", "contact_or_address"):
            if eff_uf not in {"money", "percent", "bps", "capacity", "money_per_unit"} and vt:
                return pname
        elif pname == "qa_question_count":
            if u_low in {"", "question", "questions", "forward question", "sub questions"} and _is_int_in_range(value, 1, 30):
                return pname
    return None


# --------------------------------------------------------------------------- Step 4: Normalisation & Synonyms

_PLURAL_EXEMPT = {
    "sales", "assets", "liabilities", "expenses", "earnings", "receivables", "payables",
    "inventories", "provisions", "investments", "borrowings", "deposits", "advances",
    "operations", "activities", "reserves", "surplus", "goods", "services", "funds",
    "days", "months", "years", "quarters", "bps", "eps", "ops", "sms", "gas", "loss",
    "gross", "less", "excess", "progress", "business", "process", "status", "basis",
    "bonus", "focus", "versus", "plus", "class", "glass", "mass", "pass", "cross",
    "brass", "news", "series", "presales", "pre_sales", "slippages", "ebitda",
    "gnpa", "nnpa", "roa", "roe", "roce", "crar", "nim", "pcr", "dscr", "plf",
    "gdv", "lcr", "ltv", "aum", "tcv", "anda", "sssg", "capex", "opex", "cogs",
}
_BRITISH_US = {
    "utilisation": "utilization",
    "amortisation": "amortization",
    "realisation": "realization",
    "optimisation": "optimization",
    "localisation": "localization",
    "customisation": "customization",
    "monetisation": "monetization",
    "annualised": "annualized",
    "stabilisation": "stabilization",
    "normalised": "normalized",
    "capitalisation": "capitalization",
    "decarbonisation": "decarbonization",
    "modernisation": "modernization",
    "rationalisation": "rationalization",
    "blending": "blend",
    "positioning": "position",
    "competition": "competitive",
}
_TOKEN_SYNONYMS = {
    "percentage": "pct",
    "percent": "pct",
    "per_cent": "pct",
    "year_on_year": "yoy",
    "year_over_year": "yoy",
    "quarter_on_quarter": "qoq",
    "quarter_over_quarter": "qoq",
    "ton": "tonne",
    "tons": "tonne",
    "tonnes": "tonne",
}

# Exact normalised bare-name -> measure_dict.id true synonyms (checked before clustering).
# Note: ``operating_margin`` is deliberately NOT mapped to ``ebitda_margin`` because in
# transcripts it often denotes EBIT margin; ``operating_profit_margin`` maps to ``ebit_margin``
# via ``measure_alias``.
DICT_SYNONYMS: dict[str, str] = {
    "revenue": "revenue.value",
    "sales": "revenue.value",
    "turnover": "revenue.value",
    "total_revenue": "revenue.value",
    "total_sales": "revenue.value",
    "total_turnover": "revenue.value",
    "net_sales": "revenue.value",
    "gross_sales": "revenue.value",
    "sales_revenue": "revenue.value",
    "sales_turnover": "revenue.value",
    "business_turnover": "revenue.value",
    "topline": "revenue.value",
    "top_line": "revenue.value",
    "revenue_growth": "revenue_growth_yoy",
    "sales_growth": "revenue_growth_yoy",
    "turnover_growth": "revenue_growth_yoy",
    "revenue_growth_rate": "revenue_growth_yoy",
    "operating_profit": "ebit",
    "operating_income": "ebit",
    "pbit": "ebit",
    "net_profit": "pat",
    "profit_after_tax": "pat",
    "net_earnings": "pat",
    "bottomline": "pat",
    "bottom_line": "pat",
    "net_margin": "pat_margin",
    "net_profit_margin": "pat_margin",
    "gross_margin": "gross_profit_margin",
    "gross_debt": "borrowings",
    "total_debt": "borrowings",
    "debt": "borrowings",
    "net_worth": "total_equity",
    "networth": "total_equity",
    "shareholder_equity": "total_equity",
    "shareholders_equity": "total_equity",
    "shareholder_fund": "total_equity",
    "shareholders_fund": "total_equity",
    "capital_expenditure": "capex",
    "capex_spend": "capex",
    "capex_outlay": "capex",
    "interest_expense": "finance_cost",
    "interest_cost": "finance_cost",
    "borrowing_cost": "finance_cost",
    "employee_cost": "employee_benefits_expense",
    "staff_cost": "employee_benefits_expense",
    "manpower_cost": "employee_benefits_expense",
    "personnel_cost": "employee_benefits_expense",
    "headcount": "count.employees",
    "employee_count": "count.employees",
    "employee_headcount": "count.employees",
    "workforce": "count.employees",
    "staff_strength": "count.employees",
    "team_strength": "count.employees",
    "count_employee": "count.employees",
    "raw_material_expense": "raw_material_cost",
    "material_cost": "raw_material_cost",
    "rm_cost": "raw_material_cost",
    "power_and_fuel_cost": "power_cost",
    "power_fuel_cost": "power_cost",
    "capacity_utilization": "capacity.utilisation",
    "plant_utilization": "capacity.utilisation",
    "utilization_rate": "capacity.utilisation",
    "capacity_utilization_rate": "capacity.utilisation",
    "ebitda_per_ton": "ebitda_per_tonne",
    "ebitda_per_mt": "ebitda_per_tonne",
    "dso": "debtor_days",
    "dso_day": "debtor_days",
    "days_sales_outstanding": "debtor_days",
    "debtor_day": "debtor_days",
    "receivable_day": "debtor_days",
    "inventory_day": "inventory_days",
    "payable_day": "payable_days",
    "creditor_day": "payable_days",
    "working_capital_day": "working_capital_days",
    "working_capital_cycle": "cash_conversion_cycle",
    "cost_of_borrowing": "cost_of_funds",
    "average_cost_of_borrowing": "cost_of_funds",
    "borrowing_rate": "cost_of_funds",
    "loan_book": "loans",
    "gross_advance": "loans",
    "gnpa_ratio": "gnpa_pct",
    "gross_npa_ratio": "gnpa_pct",
    "gross_npa_pct": "gnpa_pct",
    "nnpa_ratio": "nnpa_pct",
    "net_npa_ratio": "nnpa_pct",
    "net_npa_pct": "nnpa_pct",
    "provision_coverage_ratio": "pcr",
    "net_interest_margin": "nim",
    "capital_adequacy_ratio": "crar",
    "pre_sale": "realestate.presales",
    "presale": "realestate.presales",
    "order_backlog": "order.book",
    "pending_order_book": "order.book",
    "unexecuted_order_book": "order.book",
    "order_inflow": "order.intake",
    "order_win": "order.intake",
    "new_order": "order.intake",
    "total_contract_value": "deal.tcv",
    "deal_tcv": "deal.tcv",
    "debt_to_equity_ratio": "debt_equity",
    "debt_equity_ratio": "debt_equity",
    "debt_to_equity": "debt_equity",
    "net_debt_to_equity_ratio": "net_debt_equity",
    "net_debt_equity_ratio": "net_debt_equity",
    "net_debt_to_equity": "net_debt_equity",
    "net_debt_to_ebitda_ratio": "net_debt_to_ebitda",
    "net_debt_ebitda_ratio": "net_debt_to_ebitda",
    "net_debt_ebitda": "net_debt_to_ebitda",
    "debt_to_ebitda_ratio": "debt_to_ebitda",
    "debt_ebitda_ratio": "debt_to_ebitda",
    "interest_coverage": "interest_coverage_ratio",
    "debt_service_coverage_ratio": "dscr",
    "return_on_equity": "roe",
    "return_on_capital_employed": "roce",
    "return_on_asset": "roa",
    "return_on_net_worth": "roe",
    "dividend_payout_pct": "dividend_payout_ratio",
    "book_value_per_share_ratio": "book_value_per_share",
    "sssg": "same_store_sales_growth",
    "cash_and_cash_equivalent": "cash_and_cash_equivalents",
}

CLUSTER_SYNONYMS: dict[str, str] = {
    "lcr": "liquidity_coverage_ratio",
    "ltv": "loan_to_value_ratio",
    "loan_to_value": "loan_to_value_ratio",
    "cd_ratio": "credit_deposit_ratio",
    "fcf": "free_cash_flow",
    "gdv": "gross_development_value",
    "cost_income_ratio": "cost_to_income_ratio",
    "net_cash_position": "net_cash",
    "net_cash_balance": "net_cash",
    "net_cash_surplus": "net_cash",
}

_TURNOVER_RATIO_CONTEXT = {"asset", "inventory", "receivable", "debtor", "payable", "creditor", "capital", "employee", "staff"}
_INERT_ORDER_TOKENS = {"of", "the", "in", "for", "and", "a", "an"}


def _singularize_token(tok: str) -> str:
    if len(tok) <= 3 or tok in _PLURAL_EXEMPT:
        return tok
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith(("ches", "shes", "xes", "zes", "sses")) and len(tok) > 5:
        return tok[:-2]
    if tok.endswith("s") and not tok.endswith(("ss", "us", "is", "as", "os")):
        return tok[:-1]
    return tok


def normalise_name(raw: str) -> str:
    """Normalise a measure name: lower, strip NEW:/<>, snake_case, word-order, singular/plural."""
    s = strip_new_prefix(raw)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if not s:
        return ""
    # Word order: ratio_of_x_to_y / ratio_of_x_and_y / ratio_of_x_y -> x_to_y_ratio / x_y_ratio
    m = re.match(r"^ratio_of_(.+?)_(?:to|and)_(.+)$", s)
    if m:
        s = f"{m.group(1)}_to_{m.group(2)}_ratio"
    else:
        m2 = re.match(r"^ratio_of_(.+)$", s)
        if m2 and not m2.group(1).endswith("_ratio"):
            s = f"{m2.group(1)}_ratio"
    # Word order: (total_)number_of_X / count_of_X -> count_X
    m3 = re.match(r"^(?:total_)?(?:number|count)_of_(.+)$", s)
    if m3:
        s = f"count_{m3.group(1)}"
    # Phrase-level replacements
    s = s.replace("year_on_year", "yoy").replace("year_over_year", "yoy")
    s = s.replace("quarter_on_quarter", "qoq").replace("quarter_over_quarter", "qoq")
    s = s.replace("per_cent", "pct")

    tokens = []
    for tok in s.split("_"):
        if not tok:
            continue
        tok = _BRITISH_US.get(tok, tok)
        tok = _TOKEN_SYNONYMS.get(tok, tok)
        tok = _singularize_token(tok)
        tok = _BRITISH_US.get(tok, tok)
        tok = _TOKEN_SYNONYMS.get(tok, tok)
        tokens.append(tok)
    return "_".join(tokens)


def _cluster_normalise(raw: str) -> str:
    norm = normalise_name(raw)
    if not norm:
        return ""
    norm = CLUSTER_SYNONYMS.get(norm, norm)
    tokens = norm.split("_")
    # Safe revenue/sales/turnover canonicalization in multi-word non-ratio metrics
    # (e.g. turnover_target / sales_target -> revenue_target), excluding efficiency ratios.
    if not any(t in _TURNOVER_RATIO_CONTEXT for t in tokens):
        tokens = [
            "revenue" if t in {"turnover", "sales"} and "presale" not in norm and "same_store" not in norm else t
            for t in tokens
        ]
    norm = "_".join(tokens)
    return CLUSTER_SYNONYMS.get(norm, norm)


def _order_signature(norm: str) -> tuple[str, ...]:
    toks = [t for t in norm.split("_") if t and t not in _INERT_ORDER_TOKENS]
    return tuple(sorted(toks))


def _dict_lookup_variants(norm: str) -> list[str]:
    variants = [norm]
    if "_to_" in norm and norm.endswith("_ratio"):
        variants.append(norm.replace("_to_", "_"))
    if norm.endswith("_ratio"):
        variants.append(norm[:-6])
    return variants


def _build_dict_lookups(
    con: sqlite3.Connection,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """Return (dict_families, exact_dict_norm, exact_alias_norm, alias_map)."""
    dict_families: dict[str, str] = {}
    exact_dict_norm: dict[str, str] = {}
    for mid, _name, uf, _node in con.execute("SELECT id, name, unit_family, driver_node FROM measure_dict"):
        mid_s = str(mid)
        dict_families[mid_s] = str(uf or "")
        exact_dict_norm.setdefault(mid_s.lower(), mid_s)
        n = normalise_name(mid_s)
        if n:
            exact_dict_norm.setdefault(n, mid_s)

    alias_map: dict[str, str] = {}
    exact_alias_norm: dict[str, str] = {}
    for alias, canonical in con.execute("SELECT alias, canonical FROM measure_alias"):
        a_s, c_s = str(alias), str(canonical)
        if c_s not in dict_families:
            continue
        alias_map[a_s.lower()] = c_s
        n = normalise_name(a_s)
        if n:
            exact_alias_norm.setdefault(n, c_s)
    return dict_families, exact_dict_norm, exact_alias_norm, alias_map


# Dictionary ids never auto-mapped from NEW:* because hy4 misused the NEW name as catch-all junk.
_SKIP_DICT_AUTO = {"launch_year"}


def _match_dict_or_alias(
    raw_new: str,
    dict_families: dict[str, str],
    exact_dict_norm: dict[str, str],
    exact_alias_norm: dict[str, str],
    alias_map: dict[str, str],
) -> tuple[str, str]:
    """Return (dict_id, source) where source is 'dict', 'alias', or ''."""
    bare = strip_new_prefix(raw_new)
    if bare in _SKIP_DICT_AUTO:
        return "", ""
    if bare in dict_families:
        return bare, "dict"
    if bare in alias_map:
        return alias_map[bare], "alias"
    norm = normalise_name(raw_new)
    if not norm:
        return "", ""
    if norm in exact_dict_norm:
        return exact_dict_norm[norm], "dict"
    if norm in exact_alias_norm:
        return exact_alias_norm[norm], "alias"
    for cand in _dict_lookup_variants(norm):
        if cand in DICT_SYNONYMS and DICT_SYNONYMS[cand] in dict_families:
            return DICT_SYNONYMS[cand], "alias"
        if cand in exact_alias_norm:
            return exact_alias_norm[cand], "alias"
        if cand in exact_dict_norm:
            return exact_dict_norm[cand], "dict"
    return "", ""


def _copy_db_backup(src_path: Path, dst_path: Path) -> None:
    if src_path.resolve() == dst_path.resolve():
        raise ValueError("--out must be a copy path distinct from --obs")
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    for suf in ("", "-wal", "-shm"):
        p = Path(str(dst_path) + suf)
        if p.exists():
            p.unlink()
    src = connect_ro(src_path, timeout_s=30.0)
    try:
        dst = sqlite3.connect(str(dst_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _dominant_unit_family(uf_counts: Counter[str], total_rows: int) -> str:
    """Return dominant non-empty unit family if unambiguous (>=70% of non-empty and >=2 rows or >=20% of all), else ''."""
    non_empty = {k: v for k, v in uf_counts.items() if k}
    if not non_empty:
        return ""
    ne_total = sum(non_empty.values())
    top_uf, top_cnt = max(non_empty.items(), key=lambda kv: (kv[1], kv[0]))
    if len(non_empty) > 1 and top_cnt / ne_total < 0.70:
        return "__CONFLICT__"
    if top_cnt < 2 and total_rows >= 5:
        return ""
    return top_uf


def run(
    obs_db: Path,
    out_db: Path,
    *,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Copy ``obs_db`` to ``out_db``, quarantine junk, map to dict/alias, and cluster >=3-company NEW measures."""
    t0 = time.perf_counter()
    _copy_db_backup(obs_db, out_db)

    con = sqlite3.connect(str(out_db))
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA journal_mode=WAL")

    dict_families, exact_dict_norm, exact_alias_norm, alias_map = _build_dict_lookups(con)

    new_rows = con.execute(
        """
        SELECT observation_id, symbol, measure, record_type, value, value_text,
               unit, unit_family, status, status_reason, printed_label
        FROM observation
        WHERE measure LIKE 'NEW:%'
        ORDER BY observation_id
        """
    ).fetchall()

    distinct_new_before = len({r[2] for r in new_rows})
    total_new_rows = len(new_rows)

    # Phase 1: Junk quarantine
    junk_by_pattern: Counter[str] = Counter()
    quarantine_updates: list[tuple[str, int]] = []
    remaining_rows: list[tuple[int, str, str, str, str]] = []  # oid, symbol, measure, eff_uf, bare
    all_new_counts: Counter[str] = Counter()

    for oid, sym, measure, rt, val, vt, unit, uf, status, reason, plabel in new_rows:
        all_new_counts[measure] += 1
        bare = strip_new_prefix(measure)
        eff_uf = effective_unit_family(unit or "", uf or "")
        junk_pat = classify_junk(bare, rt or "", val, vt or "", unit or "", uf or "", plabel or "")
        if junk_pat is not None:
            junk_by_pattern[junk_pat] += 1
            reason_s = str(reason or "").strip()
            if "junk_measure" not in reason_s:
                tag = f"junk_measure: {junk_pat}"
                reason_s = f"{reason_s}; {tag}" if reason_s else tag
            quarantine_updates.append((reason_s, oid))
        else:
            remaining_rows.append((oid, str(sym), str(measure), eff_uf, bare))

    if quarantine_updates:
        con.executemany(
            "UPDATE observation SET status = 'quarantined', status_reason = ? WHERE observation_id = ?",
            quarantine_updates,
        )

    # Phase 2: Dict & Alias mapping (unit-family safe per row)
    measure_updates: list[tuple[str, int]] = []
    new_alias_inserts: list[tuple[str, str]] = []
    map_rows: dict[str, tuple[str, str, int]] = {}  # new_name -> (canonical, source, count)

    rows_by_new_name: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for oid, sym, measure, eff_uf, _bare in remaining_rows:
        rows_by_new_name[measure].append((oid, sym, eff_uf))

    unmapped_by_name: dict[str, list[tuple[int, str, str]]] = {}
    rows_mapped_by_source: Counter[str] = Counter()

    for new_name, items in rows_by_new_name.items():
        canon, src = _match_dict_or_alias(new_name, dict_families, exact_dict_norm, exact_alias_norm, alias_map)
        if canon:
            target_uf = dict_families.get(canon, "")
            matched_cnt = 0
            for oid, _sym, eff_uf in items:
                if eff_uf and target_uf and eff_uf != target_uf:
                    continue  # never map across conflicting unit families
                measure_updates.append((canon, oid))
                matched_cnt += 1
            if matched_cnt > 0:
                map_rows[new_name] = (canon, src, matched_cnt)
                rows_mapped_by_source[src] += matched_cnt
                if src == "alias":
                    bare = strip_new_prefix(new_name)
                    if bare and bare not in alias_map and bare not in dict_families:
                        new_alias_inserts.append((bare, canon))
                continue
        unmapped_by_name[new_name] = items

    # Phase 3: Cluster remaining NEW names appearing in >= 3 companies within same unit family
    # Step 3a: Group each unmapped raw new_name by (cluster_norm, dominant_uf)
    name_meta: dict[str, tuple[str, str, set[str], int]] = {}  # new_name -> (cnorm, dom_uf, syms, count)
    for new_name, items in unmapped_by_name.items():
        uf_counts = Counter(eff_uf for _oid, _sym, eff_uf in items)
        dom_uf = _dominant_unit_family(uf_counts, len(items))
        if dom_uf == "__CONFLICT__":
            continue
        cnorm = _cluster_normalise(new_name)
        if not cnorm:
            continue
        syms = {sym for _oid, sym, _uf in items}
        name_meta[new_name] = (cnorm, dom_uf, syms, len(items))

    # Step 3b: Group by (cnorm, dom_uf), then attach statement-only (dom_uf=='') exact cnorm
    # ONLY if cnorm has exactly one non-empty unit_family bucket.
    exact_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    cnorm_nonempty_ufs: dict[str, set[str]] = defaultdict(set)
    for new_name, (cnorm, dom_uf, _syms, _cnt) in name_meta.items():
        exact_groups[(cnorm, dom_uf)].append(new_name)
        if dom_uf:
            cnorm_nonempty_ufs[cnorm].add(dom_uf)

    for cnorm, nonempty_ufs in cnorm_nonempty_ufs.items():
        if len(nonempty_ufs) == 1 and (cnorm, "") in exact_groups:
            target_uf = next(iter(nonempty_ufs))
            exact_groups[(cnorm, target_uf)].extend(exact_groups.pop((cnorm, "")))

    # Step 3c: Merge groups sharing the SAME non-empty unit_family (or both '') and same
    # inert-word-stripped sorted token signature (e.g. turnover_target vs target_turnover).
    sig_buckets: dict[tuple[tuple[str, ...], str], list[tuple[str, str]]] = defaultdict(list)
    for key in list(exact_groups):
        cnorm, uf = key
        sig = _order_signature(cnorm)
        if len(sig) >= 2:
            sig_buckets[(sig, uf)].append(key)

    merged_clusters: list[tuple[str, str, list[str]]] = []  # (rep_cnorm, uf, member_new_names)
    consumed_keys: set[tuple[str, str]] = set()
    for (_sig, uf), keys in sig_buckets.items():
        if len(keys) <= 1:
            continue
        # Pick the cnorm with highest total row count as representative
        keys.sort(key=lambda k: (-sum(name_meta[m][3] for m in exact_groups[k]), k[0]))
        rep_cnorm = keys[0][0]
        members: list[str] = []
        for k in keys:
            consumed_keys.add(k)
            members.extend(exact_groups[k])
        merged_clusters.append((rep_cnorm, uf, members))

    for key, members in exact_groups.items():
        if key not in consumed_keys:
            merged_clusters.append((key[0], key[1], members))

    # Keep only clusters spanning >= 3 distinct companies
    cluster_summaries: list[dict[str, Any]] = []
    for rep_cnorm, uf, members in merged_clusters:
        if not obs_mod.NEW_ID_RE.match(rep_cnorm):
            continue
        cluster_syms: set[str] = set()
        for m in members:
            cluster_syms.update(name_meta[m][2])
        if len(cluster_syms) < 3:
            continue
        canon_measure = f"{NEW_PREFIX}{rep_cnorm}"
        cluster_rows_total = 0
        for m in members:
            matched_cnt = 0
            for oid, _sym, eff_uf in unmapped_by_name[m]:
                if eff_uf and uf and eff_uf != uf:
                    continue
                measure_updates.append((canon_measure, oid))
                matched_cnt += 1
            if matched_cnt > 0:
                map_rows[m] = (canon_measure, "cluster", matched_cnt)
                rows_mapped_by_source["cluster"] += matched_cnt
                cluster_rows_total += matched_cnt
        if cluster_rows_total > 0:
            cluster_summaries.append(
                {
                    "canonical": canon_measure,
                    "unit_family": uf,
                    "companies": len(cluster_syms),
                    "rows": cluster_rows_total,
                    "members": sorted(members, key=lambda m: (-all_new_counts[m], m)),
                }
            )

    cluster_summaries.sort(key=lambda c: (-c["rows"], -c["companies"], c["canonical"]))

    # Any remaining unmapped (or fully quarantined) NEW:* names get source='none' in measure_map
    for new_name, total_cnt in all_new_counts.items():
        if new_name not in map_rows:
            map_rows[new_name] = ("", "none", total_cnt)
            rows_mapped_by_source["none"] += total_cnt

    # Apply observation updates, measure_alias additions, measure_map table, and measure_new refresh
    if measure_updates:
        con.executemany("UPDATE observation SET measure = ? WHERE observation_id = ?", measure_updates)
    if new_alias_inserts:
        con.executemany("INSERT OR IGNORE INTO measure_alias (alias, canonical) VALUES (?, ?)", new_alias_inserts)

    con.execute("DROP TABLE IF EXISTS measure_map")
    con.execute(
        """
        CREATE TABLE measure_map (
            new_name TEXT PRIMARY KEY,
            canonical TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL CHECK (source IN ('dict', 'alias', 'cluster', 'none')),
            rows INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    con.executemany(
        "INSERT INTO measure_map (new_name, canonical, source, rows) VALUES (?, ?, ?, ?)",
        [(k, v[0], v[1], v[2]) for k, v in sorted(map_rows.items())],
    )
    con.commit()

    has_measure_new = bool(
        con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='measure_new'").fetchone()
    )
    if has_measure_new:
        obs_mod.index_new_measures(con)

    distinct_new_after = con.execute(
        "SELECT COUNT(DISTINCT measure) FROM observation WHERE measure LIKE 'NEW:%'"
    ).fetchone()[0]
    distinct_new_after_non_junk = con.execute(
        "SELECT COUNT(DISTINCT measure) FROM observation WHERE measure LIKE 'NEW:%' AND status != 'quarantined'"
    ).fetchone()[0]
    new_rows_after = con.execute(
        "SELECT COUNT(*) FROM observation WHERE measure LIKE 'NEW:%'"
    ).fetchone()[0]

    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("PRAGMA journal_mode=DELETE")
    con.close()

    elapsed_s = round(time.perf_counter() - t0, 2)
    stats: dict[str, Any] = {
        "out_db": str(out_db),
        "elapsed_s": elapsed_s,
        "total_new_rows": total_new_rows,
        "new_rows_after": new_rows_after,
        "distinct_new_before": distinct_new_before,
        "distinct_new_after": distinct_new_after,
        "distinct_new_after_non_junk": distinct_new_after_non_junk,
        "junk_total": sum(junk_by_pattern.values()),
        "junk_by_pattern": dict(junk_by_pattern.most_common()),
        "rows_mapped_by_source": dict(rows_mapped_by_source),
        "clusters_total": len(cluster_summaries),
        "clusters_multi_member": sum(1 for c in cluster_summaries if len(c["members"]) >= 2),
        "top_clusters": cluster_summaries[:30],
    }
    if report_path is not None:
        _write_report(report_path, stats)
    return stats


def _write_report(path: Path, stats: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# T-241 Canonical Measure Map Report",
        "",
        f"- Output DB: `{stats['out_db']}`",
        f"- Runtime: `{stats['elapsed_s']:.2f} s`",
        f"- NEW:* rows before -> after: `{stats['total_new_rows']:,}` -> `{stats['new_rows_after']:,}`",
        f"- Distinct NEW:* names before -> after: `{stats['distinct_new_before']:,}` -> `{stats['distinct_new_after']:,}` (non-quarantined: `{stats['distinct_new_after_non_junk']:,}`)",
        f"- Junk quarantined rows: `{stats['junk_total']:,}`",
        "",
        "## Junk Rows by Pattern",
        "",
        "| Pattern | Rows |",
        "| --- | ---: |",
    ]
    for pat, cnt in stats["junk_by_pattern"].items():
        lines.append(f"| `{pat}` | {cnt:,} |")
    lines += [
        "",
        "## Rows Mapped by Source (`measure_map`)",
        "",
        "| Source | Rows |",
        "| --- | ---: |",
    ]
    for src in ("dict", "alias", "cluster", "none"):
        lines.append(f"| `{src}` | {stats['rows_mapped_by_source'].get(src, 0):,} |")
    lines += [
        "",
        f"## Top 30 Clusters (>= 3 companies; {stats['clusters_total']} total, {stats['clusters_multi_member']} multi-member)",
        "",
        "| # | Canonical | Unit Family | Companies | Rows | Member Names |",
        "| ---: | --- | --- | ---: | ---: | --- |",
    ]
    for i, c in enumerate(stats["top_clusters"], start=1):
        members_s = ", ".join(f"`{m}`" for m in c["members"][:10])
        if len(c["members"]) > 10:
            members_s += f" (+{len(c['members']) - 10} more)"
        lines.append(
            f"| {i} | `{c['canonical']}` | `{c['unit_family'] or '-'}` | {c['companies']} | {c['rows']:,} | {members_s} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-241: canonical measure map & junk quarantine for hy4 observations.")
    ap.add_argument("--obs", required=True, type=Path, help="Input observations SQLite database (read-only)")
    ap.add_argument("--out", required=True, type=Path, help="Output copy SQLite database path")
    ap.add_argument("--report", default=None, type=Path, help="Optional Markdown report output path")
    args = ap.parse_args(argv)

    stats = run(args.obs, args.out, report_path=args.report)
    print(f"obs_measure_map done in {stats['elapsed_s']:.2f}s -> {stats['out_db']}")
    print(
        f"  NEW rows: {stats['total_new_rows']} -> {stats['new_rows_after']} | "
        f"distinct NEW names: {stats['distinct_new_before']} -> {stats['distinct_new_after']} "
        f"(non-quarantined: {stats['distinct_new_after_non_junk']})"
    )
    print(f"  junk quarantined ({stats['junk_total']}): {stats['junk_by_pattern']}")
    print(f"  rows mapped by source: {stats['rows_mapped_by_source']}")
    print(f"  clusters (>=3 companies): {stats['clusters_total']} ({stats['clusters_multi_member']} multi-member)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
