"""T-133 label dictionary (v3): one metric per printed row label, per sector family.

A printed row label is normalised (:func:`normalise_label`) and then must match a lexicon phrase **whole**: a label
that carries a metric phrase plus other words is not that metric.  v1 matched any substring, so
"Operating Free Cash Flow (EBITDA - Capex)" became ``capex`` (2,062 rows), "Sales and marketing expenses" became
``revenue`` and every "non financial assets" line became ``total_financial_assets``.  The rules, in order:

1. whole-label match against a lexicon phrase (``phrases``) or a ``labels`` regex that must consume the entire
   label; unit tails (``rs``, ``us``, ``mn``, ``nos``, ``000 s``) and footnote digits are stripped first.  OCR
   spellings already seen are repaired before matching (``OCR_FIXES``: liabi6ties/liabiities -> liabilities,
   seoment -> segment, lncome -> income, ...), and a garbled label (digit/letter swap, or no dictionary hit for
   >=40% of its tokens) is ``status='rejected'`` with ``rule='garbled'``, never proposed;
2. a ``kpi_series`` seed is used only when its own label passes rule 1 and the lexicon does not disagree;
3. qualifiers (pre/post tax, including/excluding lease obligations or acceptances, ``(EBITDA - Capex)`` basis,
   ``adjusted``) leave the matched phrase and become ``dimension`` entries.  A member row is ``from_header``
   only with cell evidence (its own ``measure=`` headers, a segment/container parent, or a known entity name);
   a statement line is never a member;
4. ``unit_kind`` comes from ``metric_def`` when set, otherwise from the majority unit of the label's cells
   (``%`` -> ``pct``, ``count`` -> ``count``, ``kt``/``tonne`` -> ``tonnes``, ``x``/``days``, currency -> ``money``);
   a money figure's currency comes from the cell, never this map, and an unknown unit is NULL;
5. statement context (the cell's ``section > label`` parent) separates the rows that exist in two statements:
   "interest received" in the cash flow is ``interest_received``, on the P&L it is ``interest_income``; "owners of
   the parent" under an attributable heading is the attribution line, not ``owners_equity``.  A parent's metric is
   only applied to a child that names no metric of its own: a leaf that carries a metric phrase of a different
   kind keeps its own line, and a generated ``_pct`` name comes from the leaf's mapped base metric, never from a
   slug of the raw text;
6. junk labels (digits/period tokens only, a digit glued to a word, a value token) are ``status='rejected'``.

``from_header`` (a member row whose measure sits in the column header) is proposed only with cell evidence: its
own column headers carry ``measure=``, it sits under a ``segment``/container parent, or it is a known entity name
(``entity``/``entity_alias``).  A statement line is never a member: a leaf that names a line item, a measure, a
heading, or a label used as a section parent in its own table goes to the review queue with no proposal.

Everything written is ``status='queue'`` (or ``'rejected'``): only Opus approves.

Every proposed metric gets a ``metric_def`` row (``flow`` / ``stock`` / ``ratio`` / ``per_share`` / ``count`` /
``price``), so the period engine sums only flows: a P&L line is additive, a balance-sheet line or an AUM is not.
``from_header`` is deliberately not a ``metric_def``: its kind comes from the column header's measure.

CLI::

    python -m reality_engine.v2.label_map --cells-dir <v2 store dir> \\
        --kpi-db <pilot3 db> [--kpi-db <pilot3 db> ...] --out <dir>

writes ``<out>/label_map.db`` (``label_map`` + ``metric_def``, the v2 DDL), ``<out>/review_<family>.csv``
(one per family, sorted by frequency, with ``rule`` / ``confidence`` / ``status``), ``<out>/coverage.txt``
(mapped share of the numeric ``table_cell`` rows per family and overall, then the 50 most frequent unmapped
labels), ``<out>/rejected_seeds.csv`` (kpi seeds a failing rule 1 throws out), ``<out>/seed_changes.csv``
(the kpi_series dry run: rows whose metric the new rule changes, by pair) and ``<out>/sample_seed37.csv``
(200 proposed rows, seed 37, for Opus).
"""
from __future__ import annotations

import argparse
import csv
import random
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence, cast

import yaml

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot3.make_profile import family_of, label_of, main_store, sector_map
from reality_engine.v2 import schema

LEXICON_DIR = Path(__file__).resolve().parents[1] / "pilot3" / "lexicon"
RESULTS_LINES = "results_lines.yaml"
UNKNOWN = "unknown"
ALL_FAMILIES = "*"
QUEUE = "queue"
REJECTED = "rejected"
FROM_HEADER = "from_header"
SAMPLE_SIZE = 200
SAMPLE_SEED = 37
SAMPLE_FILE = "sample_seed37.csv"

# A child label this generic carries no metric by itself: keep its parent ('Segment Revenue > Others').
GENERIC = {"others", "other", "total", "revenue", "sales", "income", "expenses", "expenditure",
           "sub total", "subtotal", "total revenue", "total income", "total expenses", "total expenditure"}
# ... but only these stay ambiguous once printed alone; "Total expenses" under "Expenses" is still total expenses.
KEEP_PARENT = {"others", "other", "total", "sub total", "subtotal"}

# Words inside a bracket that make the bracket a unit, not part of the metric ("(Rs crore)", "(as a % of revenue)").
UNIT_TOKENS = {"in", "amount", "figure", "figures", "rs", "inr", "usd", "us", "eur", "euro", "gbp", "crore",
               "crores", "cr", "lakh", "lakhs", "million", "millions", "mn", "billion", "billions", "bn",
               "thousand", "thousands", "000", "000s", "%", "per", "cent", "and", "of", "as", "a", "revenue",
               "sales", "income", "turnover"}

# Rule 1: the unit/footnote tail a printed label carries after its own words is not part of the metric.
LABEL_UNITS = {"rs", "inr", "us", "usd", "eur", "euro", "gbp", "mn", "million", "millions", "bn", "billion",
               "billions", "cr", "crore", "crores", "lakh", "lakhs", "thousand", "000", "000s", "nos", "no",
               "num", "x", "times", "pct", "percent", "bps", "s", "days", "kt", "mt", "ton", "tonne", "tonnes",
               "kg", "mw", "gw", "units", "sq", "ft", "acre"}

# A bracketed definition only restates how a metric is built ("(EBITDA - Capex)", "(EBITDAaL - Capex)"): it is not
# part of the metric's name, and its basis becomes a `basis=` dimension (rule 3).
DEFINITION_WORDS = {"ebitda", "ebitdaal", "ebitdal", "ebit", "capex", "pat", "pbt", "revenue", "sales", "income",
                    "expenses", "expense", "cost", "profit", "loss"}

# Rule 5: labels whose meaning depends on the statement section they sit under.
CONTEXT_LABELS = {"interest received", "interest paid", "owners of the parent", "owners of the parent company",
                  "non controlling interest", "profit for the period", "total comprehensive income"}

# Rule 3: a parent that names a measure owns the metric of children that name no metric of their own
# ("Segment Assets > Unallocable assets" is segment_assets[unallocable assets], never "assets").
SECTION_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("segment assets", "segment_assets"),
    ("segment liabilities", "segment_liabilities"),
    ("segment results", "segment_results"),
    ("segment revenue", "segment_revenue"),
    ("segment ebitda", "segment_ebitda"),
    ("items that will not be reclassified", "other_comprehensive_income"),
    ("items that will be reclassified", "other_comprehensive_income"),
    ("other comprehensive income oci", "other_comprehensive_income"),
    ("profit for the period attributable to", "profit_attributable"),
    ("total comprehensive income for the period attributable to", "total_comprehensive_income_attributable"),
)

# A parent that is a container of entities, not a measure: its children are members, so the metric is in the
# column header ("JVs > AICTPL (CT-3), JV with MSC" prints that JV's revenue/EBITDA/PAT under a measure header).
CONTAINER_PARENTS = ("jvs", "joint venture", "joint ventures", "subsidiaries", "subsidiary", "associates",
                     "ports", "segments", "business segments", "entities", "subsidiary companies")

# A parent that states the value is a percentage of another line: the metric is the child's metric with `_pct`.
PERCENT_PARENTS = ("as a of total revenues", "as a of revenue", "as a of total income", "as a of sales")

PCT_SPECIAL = {"ebitda": "ebitda_margin_pct", "ebit": "ebit_margin", "pat": "pat_margin_pct", "pbt": "pbt_margin"}

# Rule 6: a row label that states a value or only a period is not a metric.
PERIOD_TOKEN = re.compile(r"^(?:ytd)?(?:9m|6m)?f?y?\d{2,4}$|^[qh][1-4]?(?:fy\d{2,4})?$|^\d{2,4}$")

# Rule 6: a heading row carries a subtotal, not a metric; the leaf lines under it carry the metrics.
HEADINGS = {"financial assets", "financial liabilities", "non financial assets", "non financial liabilities",
            "assets", "liabilities", "equity and liabilities", "consolidated", "standalone"}

# Words that make a label look like a measure of its own, so a table of rows without an exact match is not read
# as a table of member names (rule 3's member rule).
METRIC_HINTS = {"total", "net", "gross", "average", "per", "number", "no", "of", "count", "nos", "customer",
                "customers", "store", "stores", "employee", "employees", "headcount", "countries", "subscriber",
                "subscribers", "users", "volume", "volumes", "production", "capacity", "share", "growth",
                "margin", "ratio", "cost", "revenue", "income", "ebitda", "pat", "profit", "loss", "capex",
                "debt", "cash", "asset", "assets", "liability", "liabilities", "equity", "expense", "expenses",
                "spend", "order", "book", "intake", "backlog", "aum", "loan", "loans", "deposit", "deposits",
                "advance", "advances", "days", "turnover", "utilisation", "utilization", "yield", "churn",
                "arpu", "realisation", "realization", "price", "sales", "ebit", "pbt", "dividend", "tax",
                "interest", "financing", "investing", "other", "bank", "banks", "balance", "balances",
                "derivative", "derivatives", "instrument", "instruments", "held", "sale", "provision",
                "provisions", "borrowings", "lease", "reserves", "surplus", "goodwill", "intangible",
                "intangibles", "investment", "investments", "maturity", "expenditure", "charges", "payable",
                "receivable", "expenditure", "duties"}

# Rule 1 (v3): OCR spellings already seen in the p20_r4 cells.  Applied one token at a time before matching, so
# "financial liabiities > borrow ings" is the financial liabilities section and "seoment" is a segment heading.
OCR_FIXES = {
    "liabi6ties": "liabilities", "liabiities": "liabilities", "fiabilities": "liabilities",
    "liabifities": "liabilities", "riabi6ties": "liabilities", "riabiities": "liabilities",
    "seoment": "segment", "lncome": "income", "mobife": "mobile", "selfvices": "services",
    "rnfrastrnctme": "infrastructure", "rmancial": "financial", "borrov": "borrowings", "ings": "",
    "adiustment": "adjustment", "adjusune": "adjustment", "redassified": "reclassified",
    "relatmg": "relating", "wdl": "will", "tlirouuh": "through", "orofit": "profit", "ocl": "oci",
}

# Rule 1 (v3): phrase-level OCR repairs, applied after the token fixes ("pro fit" is the printed "profit").
OCR_PHRASES = (("pro fit", "profit"), ("un allocable", "unallocable"), ("un allocated", "unallocated"))

# Rule 1 (v3): a token whose letters are swapped with a digit is OCR damage ("0ther", "expe1"), never a label.
DIGIT_SWAP = re.compile(r"^(?:\d+[a-z]{2,}|[a-z]{2,}\d+[a-z]{2,})$")

# Rule 3 (v3): a statement line is never a member row.  A leaf carrying one of these words names a line item or a
# measure, not a segment/port/subsidiary; it goes to the queue with no proposal.
LINE_WORDS = frozenset("""
    account accounting accumulated adjustment adjustments allowance allowances amortisation amortization amount
    assets attributable audit audited average bad balance balances bank borrowings capital cash charge charges
    cogs consolidated cost costs creditors current debenture debts debt deferred depreciation discount dividend
    dividends dues earning earnings ebitda ebitdaal ebit eps equity exceptional expense expenses expenditure
    fee fees finance goodwill grant gross impairment income insurance interest inventories inventory investment
    investments item items lease leases liabilities liability loan loans loss margin margins material materials
    eliminations elimination enterprises enterprise medium micro net non note notes operating paid payable
    payables premium profit profits provision provisions
    ratio ratios receivable receivables redemption refer reserves reserve revenue revenues sale sales securities
    share shares small statutory stock stores surplus tax taxes total turnover value waiver worth written
""".split())

# ... and these words state a measure, so the label is a KPI row, not a member name.
MEASURE_WORDS = frozenset("""
    arpu average base branches capacity churn cities count countries coverage covered customers dealers gbs
    growth headcount margin minutes number operations population rank share size subscribers stores towers
    utilisation utilization users volume volumes
""".split())

# Rule 1 (v3): the dictionary the garbled check reads.  Filler and domain words seen in printed labels; it is not
# the lexicon (matching still uses whole phrases only).
LABEL_WORDS = frozenset("""
    a about above access add according across activities activity actual added addition additional after again
    against air airtel africa al allocable also alternative amount and annual annualised annualized another any
    applicable applied
    approx as asia at attributable available bazaar based basic before below benefits between both brought business
    businesses by cable cables capitalised caratlane carried case cash catering certain change changes claridges
    closed closing clubbed collection compared comprising consolidated continued continuing contracts contractual
    core corporate cost crore crores cumulative customer customers dahej damas date day days declared decrease
    defined delivered denoted denominated derived digital domestic during each earlier earned effect effective
    ended ending
    enhanced equivalent established estimated europe excluding exclusive expenditure expense expenses extra
    facility fair fees
    figure figures financial financed fixed following for foreign from full further gain gains generated ginger
    giving goods gross group half held higher highest holding homes hotels however including inclusive increase
    increased incurred independent indicated individually industry india initial institution insurance interest
    interim internal inventory invested investment investments ipo issue issued item items jewellery joint lakh
    lakhs last later lease less liabilities limited ltd made main major making management margin market marine
    materials maximum measurement measured medium million millions minimum mobile month months more most namely
    net no non controlling not number of on one only operating operations operator oriental or order other
    others our outstanding over overall paid parent
    particular partly payment pension per period periods place plan plus portion ports post previous prior pro
    profit profits proportion provided provision provisions quarter quarterly range rate rates ratio reached
    received receivable receivables recurring relating relevant remaining reported reporting respective restated
    result results resulted retail revenue revenues revised right sale sales same schedule second segment segments
    senior services share shares shorter significant similar since sold standard standalone stated statement
    subsidiary substantial substantially such support surplus switchgears tax taxes than that the their thereof
    these third this those through to total totaling totalised towards turnover tv un under underlying unallocated
    up upon us used value various versus via volume was were whereas which while will with within without year
    years
""".split()) | {"benefit", "plans", "remeasurement", "remeasurements"}

NUMBERING = (
    re.compile(r"^\s*(?:\(\s*\d{1,3}\s*\)|\d{1,3}[.)])\s+", re.I),
    re.compile(r"^\s*(?:\(\s*[a-z]\s*\)|[a-z][.)])\s+", re.I),
    re.compile(r"^\s*(?:\(\s*(?:i{1,3}|iv|v|vi{0,3}|ix|x{1,3})\s*\)|"
               r"(?:i{1,3}|iv|v|vi{0,3}|ix|x{1,3})[.)])\s+", re.I),
)
BRACKET = re.compile(r"\(([^()]*)\)|\[([^\[\]]*)\]")

UNIT_ALIASES = {"inr_cr": "money", "inr_bn": "money", "inr_mn": "money", "inr": "money", "usd_mn": "money",
                "usd": "money", "usd_per_tonne": "money", "pct": "pct", "percent": "pct", "bps": "bps",
                "x": "x", "num": "x", "days": "days", "count": "count", "count_mn": "count",
                "count_cr": "count", "kt": "tonnes", "tonnes": "tonnes", "ton": "tonnes",
                "inr_per_share": "money", "money": "money"}

PER_SHARE = {"eps_basic", "eps_diluted", "dividend_per_share", "dps", "book_value_per_share", "bvps", "face_value"}

STOCK_METRICS = {
    "net_debt", "gross_debt", "borrowings", "total_borrowings", "debt", "aum", "order_book", "order_book_l1",
    "order_backlog", "deposits", "advances", "casa", "cash_balance", "inventory", "receivables", "payables",
    "net_worth", "equity", "total_assets", "total_liabilities", "paid_up_capital", "embedded_value", "abv",
    "customer_franchise", "employees", "headcount", "dark_stores", "monthly_transacting_users", "direct_reach",
    "capacity", "stores", "branches", "dealers", "segment_assets", "segment_liabilities", "pending_andas",
    "non_controlling_interest", "owners_equity", "total_equity", "total_financial_assets",
    "total_financial_liabilities", "investments", "investments_in_jvs", "lease_liabilities", "provisions",
    "trade_receivables", "trade_payables", "other_financial_assets", "other_financial_liabilities",
    "other_current_assets", "other_non_current_assets", "other_current_liabilities", "other_non_current_liabilities",
    "total_current_assets", "total_current_liabilities", "total_non_current_assets", "total_non_current_liabilities",
    "cash_and_equivalents", "equity_share_capital", "other_equity", "property_plant_equipment", "goodwill",
    "right_of_use_assets", "capital_work_in_progress", "intangible_assets", "intangible_assets_under_development",
    "loans", "liquid_investments", "income_tax_assets", "preference_shares_outstanding", "paid_up_debt_capital",
    "debenture_redemption_reserve", "network_towers", "population_covered", "total_equity_and_liabilities",
    "deferred_tax_liabilities",
}

FLOW_METRICS = {
    "revenue", "revenue_from_operations", "segment_revenue", "segment_ebit", "segment_ebitda", "pat", "pbt", "ebitda",
    "net_income", "order_intake", "order_intake_l1", "gov", "volumes", "export_volumes", "domestic_volumes",
    "ev_volumes", "shipments_kt", "production_kt", "new_loans", "customers_added", "net_adds", "net_additions",
    "anda_filed", "anda_approved", "capex", "cash_flow_from_operations", "operating_cash_flow", "free_cash_flow",
    "loan_loss_provisions", "ebit", "ebitdaal", "operating_ebitda", "pat_before_exceptional", "pbt_before_exceptional",
    "share_of_jv_profit", "access_charges", "licence_fee", "cost_of_goods_sold", "sg_and_a_expense", "a_and_p_spend",
    "contribution", "amortization", "interest_income", "profit_attributable", "total_comprehensive_income_attributable",
    "other_comprehensive_income", "tax_effect_oci", "operating_free_cash_flow", "cash_profit_from_operations",
    "cash_generated_from_operations", "cash_flow_from_financing", "cash_flow_from_investing",
    "proceeds_from_asset_sale", "contractual_expense", "stripping_activity_adjustment", "eliminations",
    "inter_segment_revenue", "segment_results", "total_minutes_on_network", "total_gbs_on_network", "voice_revenue",
    "data_revenue", "passive_infrastructure_services", "network_operations_cost", "volume",
    "fees_and_commission_expense", "airtel_money_revenue",
    "other_income", "total_income", "total_expenses", "cost_of_materials", "purchases_of_stock_in_trade",
    "changes_in_inventories", "employee_cost", "finance_cost", "depreciation", "other_expenses",
    "exceptional_items", "tax", "current_tax", "deferred_tax", "total_comprehensive_income",
    "interest_expended", "operating_expenses", "expenditure_excl_provisions", "operating_profit",
    "provisions_and_contingencies", "impairment_financial_instruments", "net_gain_fair_value", "gross_premium",
    "net_premium", "investment_income", "expenses_of_management", "net_commission", "net_surplus",
    "interest_received", "unallocable_income", "unallocable_expenses", "sales_and_marketing_expense",
    "free_cash_flow_before_capex",
}

RATIO_METRICS = {
    "monthly_churn", "current_ratio", "current_liability_ratio", "debt_to_assets_ratio", "lt_debt_to_wc_ratio",
    "dscr", "iscr", "debtors_turnover", "bad_debts_to_receivables", "pct_of_net_revenue", "pct_of_customer_base",
    "coverage_pct", "interest_coverage", "roe_pct", "ebitda_margin_pct", "operating_margin", "ebit_margin",
    "ebitdaal_margin", "net_profit_margin", "pat_margin_pct", "net_debt_to_equity",
}

PRICE_METRICS = {"arpu", "price", "realisation", "realization", "revenue_per_tower_per_month"}

KIND_OVERRIDE = {
    "revenue": "flow", "borrowings": "stock", "total_borrowings": "stock", "ebitda_margin_pct": "ratio",
    "eps_basic": "per_share", "ebitda_per_tonne": "price", "cost_of_production": "price",
    "segment_assets": "stock", "segment_liabilities": "stock", "net_income": "flow",
    "total_equity_and_liabilities": "stock", "deferred_tax_liabilities": "stock", "roe_pct": "ratio",
    "interest_coverage": "ratio", "revenue_per_tower_per_month": "price", "from_header": "flow",
    "sales_and_marketing_expense": "flow", "unallocable_income": "flow", "unallocable_expenses": "flow",
    "interest_received": "flow", "free_cash_flow_before_capex": "flow",
}

# Common financial lines every family prints (the third tier, sector_family='*').  The lexicon files carry the
# sector phrases; these are the statement and note lines that are the same for every industry.  Every phrase is
# matched whole: "financial assets" is a heading (rule 6), so only "total financial assets" is a metric here.
EXTRA_COMMON: dict[str, tuple[str, ...]] = {
    "ebit": ("ebit",),
    "ebitdaal": ("ebitdaal", "ebitda al"),
    "operating_ebitda": ("operating ebitda",),
    "revenue": ("net revenues", "net revenue", "total revenues", "total revenue", "net sales",
                "sale of products services", "sales of products services", "business income", "net revenue nr",
                "revenue from operations", "revenue from operation", "revenue from contracts with customers",
                "revenue from contract with customers"),
    "other_income": ("other operating revenue", "other operating income", "non operating revenue",
                     "non operating income"),
    "total_income": ("total income",),
    "pat": ("net profit", "net income after exceptional items", "profit after tax after exceptional items",
            "profit after tax", "profit after taxation"),
    "pat_before_exceptional": ("net income before exceptional items", "profit after tax before exceptional items",
                               "net profit before exceptional items"),
    "pbt": ("profit before tax", "pbt"),
    "pbt_before_exceptional": ("profit before exceptional item and tax", "profit before exceptional items and tax",
                               "profit before exceptional item and tax after exceptional"),
    "tax": ("tax", "total tax"),
    "share_of_jv_profit": ("share of results of joint ventures associates", "share of profit in associates",
                           "share of profit in associate joint venture", "share of jv profit",
                           "share of profit loss of associates and joint ventures"),
    "access_charges": ("access charges",),
    "licence_fee": ("licence fee", "license fee", "licence fees revenue share and spectrum charges"),
    "cost_of_goods_sold": ("cost of goods sold", "cost of goods sold and services"),
    "cost_of_materials": ("raw material", "material costs", "cost of raw materials and components consumed"),
    "employee_cost": ("staff cost", "staff costs"),
    "other_expenses": ("other costs",),
    "sg_and_a_expense": ("selling general and adminstration expense", "selling general and administration expense",
                         "less other sg and a"),
    "sales_and_marketing_expense": ("sales and marketing expenses", "sales and marketing expense",
                                    "selling and marketing expenses"),
    "a_and_p_spend": ("advertising", "advertisement and sales promotion", "less advertising and sales promotion",
                      "a and sp"),
    "contribution": ("contribution",),
    "amortization": ("amortization", "amortisation"),
    "finance_cost": ("interest and bank charges", "finance costs", "finance cost"),
    "interest_income": ("interest income",),
    "interest_received": ("interest received",),
    "cumulative_investments": ("cumulative investments",),
    "borrowings": ("borrowings", "borrowing"),
    "equity": ("equity",),
    "total_expenses": ("expenses", "expenditure", "total expenses"),
    "fees_and_commission_expense": ("fees and commission expenses", "fees and commission expense"),
    "airtel_money_revenue": ("airtel money revenue mn", "airtel money revenue"),
    "non_controlling_interest": ("non controlling interest", "non controlling interests",
                                 "non controlling interest nci"),
    "owners_equity": ("equity attributable to owners of the parent",
                      "equity attributable to owners of the parent company"),
    "profit_attributable": ("profit for the period attributable to",),
    "total_comprehensive_income_attributable": ("total comprehensive income for the period attributable to",),
    "total_assets": ("total assets",),
    "total_liabilities": ("total liabilities",),
    "total_equity": ("total equity",),
    "total_equity_and_liabilities": ("total equity and liabilities", "total equity liabilities"),
    "total_financial_assets": ("total financial assets",),
    "total_financial_liabilities": ("total financial liabilities",),
    "investments": ("investments", "investment"),
    "investments_in_jvs": ("total investments in jvs", "investment in joint ventures"),
    "lease_liabilities": ("lease liabilities", "lease liability"),
    "provisions": ("provisions", "provision"),
    "trade_receivables": ("trade receivables", "trade receivable"),
    "trade_payables": ("trade payables", "trade payable"),
    "other_financial_assets": ("other financial assets",),
    "other_financial_liabilities": ("other financial liabilities",),
    "other_current_assets": ("other current assets",),
    "other_non_current_assets": ("other non current assets",),
    "other_current_liabilities": ("other current liabilities",),
    "other_non_current_liabilities": ("other non current liabilities",),
    "total_current_assets": ("total current assets", "current assets"),
    "total_current_liabilities": ("total current liabilities", "current liabilities"),
    "total_non_current_assets": ("total non current assets",),
    "total_non_current_liabilities": ("total non current liabilities",),
    "cash_and_equivalents": ("cash and cash equivalents", "cash and equivalents"),
    "equity_share_capital": ("equity share capital", "share capital"),
    "other_equity": ("other equity",),
    "property_plant_equipment": ("property plant and equipment", "property plant equipment"),
    "goodwill": ("goodwill",),
    "right_of_use_assets": ("right of use assets", "right of use asset"),
    "capital_work_in_progress": ("capital work in progress",),
    "intangible_assets": ("intangible assets", "other intangible assets"),
    "intangible_assets_under_development": ("intangible assets under development",),
    "loans": ("loans", "loan"),
    "liquid_investments": ("liquid",),
    "income_tax_assets": ("income tax assets net",),
    "preference_shares_outstanding": ("outstanding redeemable preference shares quantity no",),
    "paid_up_debt_capital": ("paid up debt capital",),
    "debenture_redemption_reserve": ("debenture redemption reserve",),
    "net_worth": ("net worth",),
    "other_comprehensive_income": ("items that will not be reclassified to profit or loss",
                                   "items that will be reclassified to profit or loss",
                                   "other comprehensive income oci",
                                   "other comprehensive income loss for the period"),
    "tax_effect_oci": ("income tax effect", "ii income tax effect",
                       "income tax relating to items that will be reclassified to profit or loss"),
    "operating_free_cash_flow": ("operating free cash flow",),
    "free_cash_flow_before_capex": ("free cash flow before capex", "adjusted free cash flow before capex"),
    "cash_profit_from_operations": ("cash profit from operations",),
    "cash_generated_from_operations": ("cash generated from operations", "net cash generated from operating activities"),
    "cash_flow_from_financing": ("net cash used in financing activities",
                                 "cash flows from financing activities"),
    "cash_flow_from_investing": ("net cash used in investing activities", "cash flow from investing activities"),
    "proceeds_from_asset_sale": ("proceeds from sale of property plant and equipment",),
    "contractual_expense": ("contractual expense",),
    "stripping_activity_adjustment": ("stripping activity adjustment",),
    "eliminations": ("eliminations others", "eliminations per others"),
    "inter_segment_revenue": ("less inter segment revenue",),
    "segment_results": ("segment results", "total segment results"),
    "segment_assets": ("segment assets", "total segment assets"),
    "segment_liabilities": ("segment liabilities", "total segment liabilities"),
    "unallocable_income": ("unallocable income",),
    "unallocable_expenses": ("unallocable expenses", "unallocable expenditure"),
    "ebit_margin": ("ebit margin", "business ebit"),
    "operating_margin": ("operating margin",),
    "net_profit_margin": ("net profit margin",),
    "pat_margin_pct": ("pat margin",),
    "ebitda_margin_pct": ("ebitda margin", "ebitda total revenues", "ebitda per total revenues"),
    "ebitdaal_margin": ("ebitdaal margin",),
    "roce": ("return on capital employed", "return on capital employed annualised"),
    "roe_pct": ("return on shareholder s equity", "return on shareholders equity"),
    "monthly_churn": ("monthly churn",),
    "current_ratio": ("current ratio",),
    "current_liability_ratio": ("current liability ratio",),
    "debt_to_assets_ratio": ("total debts to total assets ratio",),
    "lt_debt_to_wc_ratio": ("long term debt to working capital ratio",),
    "dscr": ("debt service coverage ratio",),
    "iscr": ("interest service coverage ratio",),
    "interest_coverage": ("interest coverage ratio",),
    "debtors_turnover": ("debtors turnover ratio annualised",),
    "bad_debts_to_receivables": ("bad debts to account receivable ratio",),
    "pct_of_net_revenue": ("as a of nr",),
    "pct_of_customer_base": ("as of customer base",),
    "total_minutes_on_network": ("total minutes on network mn", "minutes on the network mn"),
    "total_gbs_on_network": ("total gbs on the network mn",),
    "arpu": ("average revenue per user arpu", "arpu"),
    "revenue_per_tower_per_month": ("revenue per tower per month", "revenue per towers per month",
                                    "revenue per tow ers per month"),
    "net_additions": ("net additions 000 s", "net additions"),
    "network_towers": ("network towers nos", "network towers"),
    "employees": ("total employees nos", "total employees"),
    "price": ("price in rs te", "price in rs per te", "overall average realization", "realisation", "realization"),
    "population_covered": ("population covered bn", "population coverage"),
    "coverage_pct": ("coverage",),
    "voice_revenue": ("voice revenue mn", "voice revenue"),
    "data_revenue": ("data revenue mn", "data revenue"),
    "passive_infrastructure_services": ("passive infrastructure services",),
    "network_operations_cost": ("network operations costs",),
    "deferred_tax": ("deferred tax", "deferred tax expense", "deferred tax charge", "deferred tax credit"),
    "deferred_tax_liabilities": ("deferred tax liabilities net", "deferred tax liabilities"),
    "basic_eps": ("basic eps", "basic earnings per share"),
    "diluted_eps": ("diluted eps", "diluted earnings per share"),
}

# Rule 3: qualifier phrases leave the matched phrase and become the row's dimension.  Only the qualifiers the
# brief names; "adjusted ebitda" is a metric of its own in the metals lexicon, not ebitda with a note.
QUALIFIERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpre tax\b|\bbefore tax\b"), "pre_tax"),
    (re.compile(r"\bpost tax\b|\bafter tax\b"), "post_tax"),
    (re.compile(r"\bexcluding lease (?:obligations|liabilities)\b"), "excl_lease"),
    (re.compile(r"\bincluding lease (?:obligations|liabilities)\b"), "incl_lease"),
    (re.compile(r"\bexcluding acceptances\b"), "excl_acceptances"),
    (re.compile(r"\bincluding acceptances\b"), "incl_acceptances"),
)


# ------------------------------------------------------------------------------------------------ normalisation
def _is_unit(inner: str) -> bool:
    """True when a bracketed phrase is only a currency, scale or percent (so it can be dropped)."""
    tokens = re.findall(r"[a-z]+|[$₹%]|'?\d+", inner.lower())
    return bool(tokens) and all(token in UNIT_TOKENS or token.isdigit() for token in tokens)


def _strip_numbering(text: str) -> str:
    for pattern in NUMBERING:
        while True:
            stripped = pattern.sub("", text, count=1)
            if stripped == text:
                break
            text = stripped
    return text


def _clean(text: str | None) -> str:
    value = str(text or "")
    value = BRACKET.sub(lambda m: "" if _is_unit(m.group(1) or m.group(2) or "") else m.group(0), value)
    value = value.lower()
    value = _strip_numbering(value)
    value = value.replace("%", " ")
    value = value.replace("/", " ")
    value = value.replace("&", " and ")
    value = re.sub(r"[₹$`]", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def strip_units(text: str) -> str:
    """Drop the unit/footnote tail a printed label carries ("capex 1 us", "net debt us mn", "customer base 000 s")."""
    tokens = text.split()
    while tokens and (tokens[-1] in LABEL_UNITS or tokens[-1].isdigit()):
        tokens.pop()
    return " ".join(tokens)


def _normalise_piece(raw: str | None) -> str:
    """One normalised label piece: OCR spellings repaired, unit tails and numbering dropped."""
    text = strip_units(_clean(raw))
    text = " ".join(fixed for fixed in
                    (OCR_FIXES.get(token, token) for token in text.split()) if fixed)
    for phrase, repaired in OCR_PHRASES:
        text = text.replace(phrase, repaired)
    return text


def normalise_label(raw: str | None, parent: str | None = None) -> str:
    """Normalise one printed row label; keep the parent only when the child alone is generic.

    >>> normalise_label("1. Revenue from operations") == normalise_label("Revenue from Operations (Rs crore)")
    True
    >>> normalise_label("Others", "Segment Revenue")
    'segment revenue > others'
    >>> normalise_label("Net Debt US$ mn")
    'net debt'
    """
    text = _normalise_piece(raw)
    if not text:
        return ""
    if parent and text in KEEP_PARENT:
        head = " > ".join(part for part in (_normalise_piece(piece) for piece in parent.split(" > ")) if part)
        return f"{head} > {text}" if head else text
    return text


def _split_label(raw: str | None) -> tuple[str | None, str]:
    """``(parent, child)`` of a ``section > label`` cell label, both as printed (not yet normalised)."""
    parts = [part for part in str(raw or "").split(" > ") if part.strip()]
    if not parts:
        return None, ""
    return (" > ".join(parts[:-1]) or None), parts[-1]


def _definition_parts(raw: str) -> tuple[str, list[str]]:
    """``(raw without its definition brackets, dimension parts)`` for "(EBITDA - Capex)"-style brackets.

    A unit bracket is dropped by :func:`_clean`; a qualifier bracket ("(excluding lease obligations)") is kept for
    the qualifier rule; a definition bracket only restates how the metric is built, so it leaves the label and,
    when it names a basis, sets ``basis=``.  "Operating Free Cash Flow (EBITDA - Capex)" is therefore the
    operating free cash flow on an EBITDA basis, never the capex line.
    """
    parts: list[str] = []

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1) or match.group(2) or ""
        tokens = set(_clean(inner).split())
        if not tokens or _is_unit(inner) or not (tokens & DEFINITION_WORDS):
            return match.group(0)
        if "ebitdaal" in tokens:
            parts.append("basis=ebitdaal")
        elif "ebitda" in tokens:
            parts.append("basis=ebitda")
        elif "ebit" in tokens:
            parts.append("basis=ebit")
        return ""

    return BRACKET.sub(repl, str(raw or "")), parts


def split_qualifiers(text: str) -> tuple[str, list[str]]:
    """``(phrase, dimensions)`` with the qualifier phrases removed ("net debt excluding lease obligations")."""
    found: list[str] = []
    for pattern, dimension in QUALIFIERS:
        if pattern.search(text):
            found.append(dimension)
            text = pattern.sub(" ", text)
    return " ".join(text.split()), found


def junk_reason(label_norm: str) -> str:
    """Rule 6: why a normalised label cannot be a metric, or ``''``."""
    tokens = label_norm.split()
    words = [token for token in tokens if re.search(r"[a-z]", token)]
    if not words:
        return "digits only"
    if all(PERIOD_TOKEN.match(token) for token in words):
        return "period tokens only"
    if any(re.search(r"[a-z]\d", token) for token in words):
        return "digit glued to a word"
    if any(token.isdigit() and len(token) >= 3 for token in tokens):
        return "a value token in the label"
    return ""


GARBLED_SHARE = 0.4
_VOCAB: frozenset[str] | None = None


def _vocabulary() -> frozenset[str]:
    """The dictionary the garbled check reads: label filler, measure/line words and the lexicon's common lines."""
    global _VOCAB
    if _VOCAB is None:
        words: set[str] = set(LABEL_WORDS) | set(LINE_WORDS) | set(MEASURE_WORDS)
        for group in (GENERIC, HEADINGS, METRIC_HINTS, LABEL_UNITS, UNIT_TOKENS):
            for phrase in group:
                words.update(str(phrase).split())
        for phrases in EXTRA_COMMON.values():
            for phrase in phrases:
                words.update(normalise_label(phrase).split())
        _VOCAB = frozenset(word for word in words if word)
    return _VOCAB


def garbled_reason(label_norm: str, raw: str | None = None) -> str:
    """Rule 1 (v3): ``'garbled'`` for an OCR-damaged label, or ``''``.

    A digit/letter swap ("0ther") is damage anywhere.  Otherwise a label of two or more words is garbled when the
    dictionary misses 40% or more of its tokens ("gpwis mmt", "mobife ... rnfrastrnctme servi ces"), and a single
    lower-case word of six or more letters the dictionary does not hold is damage too ("sorrowtngs").  Entity
    names and acronyms are short or title-case, so they pass.
    """
    words = label_norm.split()
    if any(DIGIT_SWAP.match(word) for word in words):
        return "garbled"
    vocabulary = _vocabulary()
    unknown = [word for word in words
               if word not in vocabulary and not (len(word) == 1 and word.isalpha())]
    if len(words) >= 2:
        if unknown and len(unknown) / len(words) >= GARBLED_SHARE:
            return "garbled"
    elif unknown and ((len(words[0]) >= 6 and str(raw or "").strip()[:1].islower())
                      or len(words[0]) >= 12):
        return "garbled"
    return ""


def statement_of(parent: str) -> str:
    """Rule 5: which statement the parent section names, or ``''``."""
    text = f" {parent.lower()} "
    if any(word in text for word in ("cash flow", "cash flows", "operating activities", "investing activities",
                                     "financing activities")):
        return "cash_flow"
    if any(word in text for word in ("profit and loss", "statement of profit", "income statement")):
        return "pnl"
    if any(word in text for word in (" balance sheet ", " assets ", " liabilities ", " equity ")):
        return "balance_sheet"
    return ""


@dataclass(frozen=True)
class ParsedLabel:
    label_norm: str
    candidates: tuple[tuple[str, str], ...] = ()   # (whole-label text, dimension) in rule order
    junk: str = ""


def parse_label(raw: str | None, parent: str | None = None) -> ParsedLabel:
    """Split a printed label into its normalised key and the phrases rule 1 may match whole.

    Candidate 1 is the label as printed; candidate 2 drops a definition bracket ("Operating Free Cash Flow
    (EBITDA - Capex)"); candidate 3 also drops its qualifiers.  The first candidate that matches a lexicon phrase
    whole is the proposal, and the qualifiers that were dropped become its ``dimension`` (T-133 rules 1 and 3).
    """
    without_definitions, definition_dims = _definition_parts(str(raw or ""))
    label_norm = normalise_label(raw, parent)
    if not label_norm:
        return ParsedLabel("", (), "")
    base_norm = label_norm if not definition_dims else normalise_label(without_definitions, parent)
    base_dimension = "; ".join(definition_dims)
    candidates: list[tuple[str, str]] = []
    for text in dict.fromkeys((label_norm, base_norm)):
        if text:
            candidates.append((text, base_dimension))
    stripped, qualifier_dims = split_qualifiers(base_norm)
    if stripped and stripped != base_norm:
        dimension = "; ".join(part for part in [base_dimension, "; ".join(qualifier_dims)] if part)
        candidates.append((stripped, dimension))
    return ParsedLabel(label_norm, tuple(candidates), junk_reason(label_norm))


# ---------------------------------------------------------------------------------------------------- lexicons
@dataclass(frozen=True)
class Entry:
    metric: str
    patterns: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    neg: tuple[str, ...] = ()
    source: str = ""
    kind: str = ""
    unit: str = ""
    phrases_norm: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.phrases_norm and self.phrases:
            object.__setattr__(self, "phrases_norm",
                               tuple(dict.fromkeys(p for p in (normalise_label(phrase) for phrase in self.phrases)
                                                   if p)))


@dataclass(frozen=True)
class Proposal:
    metric: str
    reason: str
    family: str
    entry: Entry | None = None
    dimension: str = ""
    rule: str = ""
    confidence: str = ""
    status: str = QUEUE


def load_lexicons(lexicon_dir: Path = LEXICON_DIR) -> tuple[dict[str, list[Entry]], list[Entry]]:
    """``(family -> entries, common entries)`` from the pilot3 lexicon yamls.

    A yaml with ``entries`` and ``sectors`` belongs to those families; ``family: common`` applies to all.
    ``results_lines.yaml`` (a metric -> printed-phrase map) and the common financial lines go to the common tier.
    """
    family_entries: dict[str, list[Entry]] = defaultdict(list)
    common: list[Entry] = []
    for path in sorted(lexicon_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if path.name == RESULTS_LINES:
            for metric, phrases in data.items():
                if isinstance(phrases, list) and phrases:
                    common.append(Entry(str(metric), phrases=tuple(str(p) for p in phrases), source=path.stem))
            continue
        entries = data.get("entries") or []
        if not entries:
            continue
        family = str(data.get("family") or "")
        sectors = [str(s) for s in (data.get("sectors") or [])]
        for raw in entries:
            entry = Entry(str(raw["metric"]), patterns=tuple(str(p) for p in (raw.get("labels") or ())),
                          neg=(str(raw["neg"]) if raw.get("neg") else "",),
                          source=path.stem, kind=str(raw.get("kind") or ""), unit=str(raw.get("unit") or ""))
            if family == "common":
                common.append(entry)
            else:
                for sector in sectors:
                    family_entries[sector].append(entry)
    for metric, phrases in EXTRA_COMMON.items():
        common.append(Entry(metric, phrases=tuple(phrases), source="label_map"))
    return dict(family_entries), common


def _match_entry(entry: Entry, text: str) -> int:
    """Length of a whole-label match (rule 1), or 0 when the entry's phrase is only part of ``text``.

    >>> _match_entry(Entry("ebit", phrases=("ebit",)), "ebit")
    4
    >>> _match_entry(Entry("ebit", phrases=("ebit",)), "ebit margin")
    0
    """
    if not text:
        return 0
    matched = 0
    for phrase in entry.phrases_norm:
        if text == phrase:
            matched = max(matched, len(phrase))
    for pattern in entry.patterns:
        try:
            found = re.fullmatch(pattern, text, re.IGNORECASE)
        except re.error:
            continue
        if found:
            matched = max(matched, len(text))
    if not matched:
        return 0
    for neg in entry.neg:
        if neg and re.search(neg, text, re.IGNORECASE):
            return 0
    return matched


def _best(entries: Sequence[Entry], text: str) -> Entry | None:
    best, best_length = None, 0
    for entry in entries:
        length = _match_entry(entry, text)
        if length > best_length:
            best, best_length = entry, length
    return best


def propose_metric(label_norm: str, family: str, seeds: Mapping[tuple[str, str], str],
                   family_entries: Mapping[str, Sequence[Entry]],
                   common: Sequence[Entry], dimension: str = "") -> Proposal | None:
    """Whole-label match first, then the family's lexicon, then the common lines (``sector_family='*'``)."""
    if not label_norm:
        return None
    family_entry = _best(family_entries.get(family, ()), label_norm)
    common_entry = _best(common, label_norm)
    entry = family_entry if family_entry is not None else common_entry
    seeded = seeds.get((label_norm, family))
    if seeded and (entry is None or entry.metric == seeded):
        return Proposal(seeded, "seed", family, dimension=dimension, rule="2-seed",
                        confidence="exact" if not dimension else "synonym")
    if family_entry is not None:
        return Proposal(family_entry.metric, f"lexicon:{family_entry.source}", family, family_entry, dimension,
                        "1-match" if not dimension else "3-qualifier",
                        "exact" if not dimension else "synonym")
    if common_entry is not None:
        return Proposal(common_entry.metric, f"common:{common_entry.source}", ALL_FAMILIES, common_entry, dimension,
                        "1-match" if not dimension else "3-qualifier",
                        "exact" if not dimension else "synonym")
    return None


# ---------------------------------------------------------------------------------------------------- metric kind
def normalise_unit(unit: str | None) -> str:
    value = str(unit or "").strip().lower()
    return UNIT_ALIASES.get(value, value)


def metric_kind(metric: str, unit_kind: str | None = None) -> str:
    """``flow`` / ``stock`` / ``ratio`` / ``per_share`` / ``count`` / ``price`` for a metric id."""
    name = metric.strip().lower()
    unit = normalise_unit(unit_kind)
    if name in KIND_OVERRIDE:
        return KIND_OVERRIDE[name]
    if unit == "inr_per_share" or name in PER_SHARE or name.endswith("_per_share"):
        return "per_share"
    if name in STOCK_METRICS or name.endswith(("_debt", "_borrowings", "_aum", "_book", "_balance", "_worth")):
        return "stock"
    if name in PRICE_METRICS:
        return "price"
    if name in RATIO_METRICS:
        return "ratio"
    if unit in {"pct", "bps", "x", "days"}:
        return "ratio"
    if unit == "usd_per_tonne":
        return "price"
    if unit == "tonnes":
        return "flow"
    if unit == "count":
        return "flow"
    if name in FLOW_METRICS:
        return "flow"
    if (name.endswith(("_pct", "_bps", "_days", "_ratio", "_margin", "_growth", "_share", "_mix", "_yield"))
            or "margin" in name or "ratio" in name or "growth" in name or "share" in name
            or "utilisation" in name or "utilization" in name or name.startswith(("roe", "roa", "roce", "roev"))):
        return "ratio"
    if name.endswith(("_revenue", "_income", "_expense", "_expenses", "_cost", "_profit", "_capex", "_flow",
                      "_intake", "_volumes", "_spend")):
        return "flow"
    return "flow"


@dataclass
class MetricMeta:
    units: Counter[str] = field(default_factory=Counter)
    entry_kind: str = ""
    entry_unit: str = ""
    sources: set[str] = field(default_factory=set)


def unit_kind_of(unit: str | None) -> str:
    """Rule 4 (v3): the kind a printed unit names (``%`` -> pct, ``Rs crore`` -> money, ``kt`` -> tonnes), or ``''``."""
    text = str(unit or "").strip().lower()
    if not text:
        return ""
    value = normalise_unit(text)
    if value in {"pct", "bps", "x", "days", "count", "tonnes", "money"}:
        return value
    if "%" in text or "percent" in text or text == "per cent":
        return "pct"
    if text in {"times", "x"}:
        return "x"
    if text in {"nos", "no", "number", "num"}:
        return "count"
    if text in {"kt", "mt", "te", "ton", "tonne", "tonnes"}:
        return "tonnes"
    if any(word in text for word in ("rs", "inr", "usd", "us$", "₹", "crore", "lakh", "million", "billion",
                                     "mn", "bn")):
        return "money"
    return ""


def majority_unit_kind(units: Counter[str]) -> str:
    """Rule 4 (v3): the kind most of these printed units name; a tie or an unknown unit is NULL (``''``)."""
    counts: Counter[str] = Counter()
    for unit, count in units.items():
        kind = unit_kind_of(unit)
        if kind:
            counts[kind] += count
    if not counts:
        return ""
    ranked = counts.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return ""
    return ranked[0][0]


def resolve_unit_kind(metric: str, meta: MetricMeta | None) -> str:
    """Rule 4 (v3): ``metric_def`` unit when set, else the majority unit of the label's cells, else ``''``.

    Only a currency unit gives ``money``; an unknown or tied unit is NULL (``''``).  A money figure's currency
    still comes from the cell, never from this map.
    """
    if meta is not None and meta.entry_unit:
        kind = unit_kind_of(meta.entry_unit)
        if kind:
            return kind
    if meta is not None:
        return majority_unit_kind(meta.units)
    return ""


# ------------------------------------------------------------------------------------------------------ reading
def _rows(con: sqlite3.Connection, sql: str, params: Sequence[object] = ()) -> list[tuple]:
    """``con.execute(...).fetchall()`` with the read-only connection's return type pinned to a cursor."""
    return cast(sqlite3.Cursor, con.execute(sql, params)).fetchall()


def company_family(taxonomy: sqlite3.Connection, table: dict, isin: str | None = None,
                   symbol: str | None = None) -> str:
    """The sector family of a company, by the make_profile path: company_industry, else master_industry."""
    if taxonomy.row_factory is not sqlite3.Row:
        taxonomy.row_factory = sqlite3.Row
    basic, industry = label_of(taxonomy, [isin] if isin else [], symbol)
    family = family_of(basic, industry, table)
    if family == UNKNOWN and basic is None and industry is None:
        row = taxonomy.execute("SELECT industry FROM master_companies WHERE isin=? OR nse_symbol=? LIMIT 1",
                               (isin or "", symbol or "")).fetchone()
        family = (table.get("master_industry") or {}).get(row["industry"] if row else "", UNKNOWN)
    return family


def company_families(store_paths: Sequence[Path], taxonomy_path: Path | None = None) -> list[dict]:
    """One row per company row of each pilot3 store: store, symbol, isin, family. Read-only."""
    taxonomy = connect_ro(taxonomy_path or main_store(), timeout_s=60)
    table = sector_map()
    rows: list[dict] = []
    try:
        for path in store_paths:
            con = connect_ro(path, timeout_s=60)
            try:
                for symbol, isin in _rows(con, "SELECT symbol, isin FROM company ORDER BY symbol, isin"):
                    rows.append({"store": str(path), "symbol": symbol, "isin": isin,
                                 "family": company_family(taxonomy, table, isin, symbol)})
            finally:
                con.close()
    finally:
        taxonomy.close()
    return rows


@dataclass
class Observation:
    count: int = 0
    raws: Counter[str] = field(default_factory=Counter)
    companies: set[str] = field(default_factory=set)
    units: Counter[str] = field(default_factory=Counter)


def _observe(observations: dict[tuple[str, str], Observation], key: tuple[str, str], raw: str,
             company: str) -> None:
    obs = observations.setdefault(key, Observation())
    obs.count += 1
    obs.raws[raw] += 1
    obs.companies.add(company)


def _symbol_by_isin(paths: Sequence[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in paths:
        con = connect_ro(path, timeout_s=60)
        try:
            for symbol, isin in _rows(con, "SELECT symbol, isin FROM company WHERE isin IS NOT NULL "
                                            "ORDER BY (isin_to IS NULL) DESC, isin"):
                out.setdefault(isin, symbol)
        finally:
            con.close()
    return out


def _candidate_proposal(label_norm: str, family: str, seeds: Mapping[tuple[str, str], str],
                        family_entries: Mapping[str, Sequence[Entry]], common: Sequence[Entry],
                        parsed: ParsedLabel) -> Proposal | None:
    """First candidate form (whole label, then definition/qualifier stripped) that matches a phrase whole.

    When the whole label and its qualifier-stripped form give the same metric, the stripped form wins: the
    qualifier belongs in ``dimension`` ("net debt including acceptances" is net_debt[incl_acceptances]).  When
    they give different metrics the whole label wins ("adjusted ebitda" is not plain ebitda).
    """
    chosen: Proposal | None = None
    for index, (text, dimension) in enumerate(parsed.candidates):
        proposal = propose_metric(text, family, seeds, family_entries, common, dimension)
        if proposal is None:
            continue
        if index > 0 and proposal.reason.startswith(("lexicon", "common")):
            proposal = Proposal(proposal.metric, proposal.reason, proposal.family, proposal.entry, dimension,
                                "3-qualifier", "synonym", proposal.status)
        if chosen is None:
            chosen = proposal
            continue
        if dimension and proposal.metric == chosen.metric:
            return proposal
    return chosen


def read_kpis(taxonomy: sqlite3.Connection, table: dict, db_paths: Sequence[Path],
              observations: dict[tuple[str, str], Observation],
              seeds: dict[tuple[str, str], Counter[str]], meta: dict[str, MetricMeta],
              isin_by_symbol: dict[str, str], family_cache: dict[tuple[str | None, str | None], str],
              family_entries: Mapping[str, Sequence[Entry]], common: Sequence[Entry],
              rejected: list[dict], rejected_rows: dict[tuple[str, str], str]) -> int:
    """Seed mappings and label observations from ``kpi_series``; returns the rows read.

    Rule 2: a seed whose raw label does not pass rule 1 is ignored and listed in ``rejected``.  A seed that passes
    but disagrees with the lexicon loses to the lexicon (the lexicon is the reviewed contract, the seed a usage
    witness); the dry run carries the metric the row would get so the change is auditable.
    """
    rows_read = 0
    for path in db_paths:
        con = connect_ro(path, timeout_s=60)
        try:
            curse = _rows(con, "SELECT symbol, raw_label, metric, unit FROM kpi_series "
                                "WHERE raw_label IS NOT NULL AND TRIM(raw_label) <> '' AND metric IS NOT NULL")
            for symbol, raw_label, metric, unit in curse:
                rows_read += 1
                key_cache = (isin_by_symbol.get(symbol), symbol)
                family = family_cache.get(key_cache)
                if family is None:
                    family = company_family(taxonomy, table, *key_cache)
                    family_cache[key_cache] = family
                parsed = parse_label(raw_label)
                if not parsed.label_norm:
                    continue
                proposal = None if parsed.junk else _candidate_proposal(parsed.label_norm, family, {},
                                                                        family_entries, common, parsed)
                _observe(observations, (parsed.label_norm, family), str(raw_label), symbol)
                if parsed.junk:
                    rejected_rows[(parsed.label_norm, family)] = parsed.junk
                if parsed.junk or proposal is None or proposal.metric != metric:
                    rejected.append({"raw_label": str(raw_label), "label_norm": parsed.label_norm,
                                     "family": family, "metric": str(metric),
                                     "new_metric": proposal.metric if proposal is not None else "",
                                     "reason": "junk" if parsed.junk else
                                               ("no whole-label phrase" if proposal is None else "metric conflict")})
                    continue
                seeds.setdefault((parsed.label_norm, family), Counter())[metric] += 1
                metric_meta = meta.setdefault(metric, MetricMeta())
                if unit:
                    metric_meta.units[str(unit)] += 1
                metric_meta.sources.add("seed")
        finally:
            con.close()
    return rows_read


def _parent_label(raw: str | None, plain: str) -> tuple[str, str]:
    """``(normalised parent, parent > label)`` for a ``section > label`` cell; ``("", plain)`` when there is none."""
    parts = [part for part in str(raw or "").split(" > ") if part.strip()]
    if len(parts) < 2:
        return "", plain
    parent = " > ".join(part for part in (normalise_label(piece) for piece in parts[:-1]) if part)
    if not parent:
        return "", plain
    full = plain if plain.startswith(parent + " > ") else f"{parent} > {plain}"
    return parent, full


def _section_metric(parent: str) -> str:
    for needle, metric in SECTION_OVERRIDES:
        if needle in parent:
            return metric
    return ""


def _pct_metric(base: str) -> str:
    base = PCT_SPECIAL.get(base, base)
    if base.endswith(("_pct", "_margin_pct", "_margin")):
        return base
    return f"{base}_pct"


def _section_entry(metric: str, reason: str) -> Entry:
    if reason == "section:pct":
        return Entry(metric, source="label_map:pct", kind="pct", unit="pct")
    return Entry(metric, source="label_map:section", kind="money", unit="money")


def _context_proposal(plain: str, parent: str, family: str) -> Proposal | None:
    """Rule 5: the statement a row sits under decides the metric for the lines printed in two statements."""
    statement = statement_of(parent)
    if plain in {"owners of the parent", "owners of the parent company"}:
        if "profit for the period attributable" in parent:
            metric = "profit_attributable"
        elif "total comprehensive income" in parent and "attributable" in parent:
            metric = "total_comprehensive_income_attributable"
        elif "comprehensive income" in parent or "items that will" in parent:
            metric = "other_comprehensive_income"
        elif "equity" in parent and "liabilities" not in parent:
            return Proposal("owners_equity", "section:context", family, None, "", "5-context", "section")
        else:
            metric = "profit_attributable"     # the attribution line is the P&L's by default
        return Proposal(metric, "section:context", family, None, "attribution=owners_of_parent", "5-context",
                        "section")
    if plain == "non controlling interest" and "attributable" in parent:
        metric = ("profit_attributable" if "profit" in parent else
                  "total_comprehensive_income_attributable" if "total comprehensive income" in parent else
                  "other_comprehensive_income")
        return Proposal(metric, "section:context", family, None, "attribution=non_controlling", "5-context",
                        "section")
    if plain == "interest received":
        if statement == "cash_flow":
            return Proposal("interest_received", "section:context", family, None, "statement=cash_flow",
                            "5-context", "section")
        if statement in {"pnl", "balance_sheet"}:
            return Proposal("interest_income", "section:context", family, None, "statement=pnl", "5-context",
                            "section")
    return None


def _member_like(label: str, has_measure: bool, has_metric_row: bool, peers: int) -> bool:
    """Rule 3 (v3): is this row a member (a segment/port/subsidiary name), not a statement line?

    ``has_measure``: one of this row's own column headers carries ``measure=``; ``has_metric_row``: another row
    of the table maps to a metric; ``peers``: the table's other unmapped labels.  A leaf that carries a line-item,
    measure or heading word is never a member, whatever the table looks like.
    """
    if not label or label in GENERIC or label in HEADINGS:
        return False
    tokens = label.split()
    if len(tokens) > 4 or set(tokens) & (METRIC_HINTS | MEASURE_WORDS | LINE_WORDS):
        return False
    if all(len(token) == 1 for token in tokens):
        return False
    return has_measure or has_metric_row or peers >= 3


def _prefix_proposal(text: str, family: str, family_entries: Mapping[str, Sequence[Entry]],
                     common: Sequence[Entry]) -> Proposal | None:
    """Rule 5 (v3): the longest whole metric phrase that starts ``text`` — the base metric of a percent row."""
    best: Proposal | None = None
    best_length = 0
    for entries in (family_entries.get(family, ()), common):
        for entry in entries:
            for phrase in entry.phrases_norm:
                if len(phrase) <= best_length or len(phrase.split()) < 2 or not text.startswith(phrase + " "):
                    continue
                best = Proposal(entry.metric, f"prefix:{entry.source}", family, entry, "", "5-context", "section")
                best_length = len(phrase)
    return best


def _section_conflict(plain: str, section_metric: str, family: str,
                      family_entries: Mapping[str, Sequence[Entry]], common: Sequence[Entry]) -> bool:
    """Rule 5 (v3): the leaf names a metric of a different kind, so the parent's metric must not replace it."""
    kind = metric_kind(section_metric)
    for entries in (family_entries.get(family, ()), common):
        for entry in entries:
            if metric_kind(entry.metric) == kind:
                continue
            for phrase in entry.phrases_norm:
                if len(phrase.split()) >= 2 and phrase in plain:
                    return True
    return False


def _container_parent(parent: str) -> bool:
    """Rule 3 (v3): the whole parent names a container of entities, not a measure ("JVs", "Subsidiaries")."""
    return bool(parent) and parent in CONTAINER_PARENTS


def decide_label(raw: str, family: str, seeds: Mapping[tuple[str, str], str],
                 family_entries: Mapping[str, Sequence[Entry]], common: Sequence[Entry],
                 has_measure: bool = False, has_metric_row: bool = False, peers: int = 0,
                 is_section_parent: bool = False, entity_name: bool = False
                 ) -> tuple[str, Proposal | None, str]:
    """``(key_label, proposal, rejection)`` for one cell label — rules 1-7 for a row, no database.

    ``has_measure``: one of this row's column headers carries ``measure=``; ``has_metric_row``: another row of the
    table maps to a metric; ``peers``: the table's other unmapped labels (rule 3's member evidence);
    ``is_section_parent``: the label is also a section parent in the same table (a line, not a member);
    ``entity_name``: the label is a name in the file's ``entity``/``entity_alias`` table.
    """
    parent, child = _split_label(raw)
    parsed = parse_label(child, parent)
    plain = parsed.label_norm
    if not plain:
        return "", None, ""
    parent_norm, full = _parent_label(raw, plain)
    container_child = _container_parent(parent_norm) and plain not in GENERIC
    if parsed.junk:
        return plain, None, parsed.junk
    direct = _candidate_proposal(plain, family, seeds, family_entries, common, parsed)
    if not container_child and direct is None:
        garbled = garbled_reason(plain, raw)
        if garbled:
            return plain, None, garbled
    key_label, proposal, rejection = plain, None, ""
    if plain in CONTEXT_LABELS:
        proposal = _context_proposal(plain, parent_norm, family)
        if proposal is not None:
            key_label = full
    if proposal is None and any(needle in parent_norm for needle in PERCENT_PARENTS):
        base = (_candidate_proposal(plain, family, seeds, family_entries, common, parsed)
                or _prefix_proposal(plain, family, family_entries, common))
        if base is not None:
            metric = _pct_metric(base.metric)
            proposal = Proposal(metric, "section:pct", family, _section_entry(metric, "section:pct"), "",
                                "5-context", "section")
            key_label = full
    if proposal is None:
        proposal = direct
    if proposal is None:
        section_metric = _section_metric(parent_norm)
        if section_metric and not _section_conflict(plain, section_metric, family, family_entries, common):
            proposal = Proposal(section_metric, "section", family, _section_entry(section_metric, "section"),
                                "" if plain in GENERIC else plain, "5-context", "section")
            key_label = full
    if proposal is None and not is_section_parent:
        if entity_name or container_child or _member_like(plain, has_measure, has_metric_row, peers):
            proposal = Proposal(FROM_HEADER, "member", family, None, plain, "3-member", "section")
            key_label = full
    if proposal is None and plain in HEADINGS:
        rejection = "heading"
    return key_label, proposal, rejection


def read_cells(cells_dir: Path, taxonomy: sqlite3.Connection, table: dict, isin_symbol: Mapping[str, str],
               observations: dict[tuple[str, str], Observation], numeric: Counter[tuple[str, str]],
               blank_numeric: Counter[str], seeds: Mapping[tuple[str, str], str],
               family_entries: Mapping[str, Sequence[Entry]], common: Sequence[Entry],
               metric_meta: dict[str, MetricMeta],
               forced: dict[tuple[str, str], Proposal],
               rejected: dict[tuple[str, str], str]) -> dict[str, int]:
    """Read every ``table_cell`` row of every company file; returns cells/companies read."""
    company_dir = cells_dir / "company"
    if not company_dir.is_dir():
        raise SystemExit(f"no company/ folder under {cells_dir}")
    files = sorted(company_dir.glob("*.db"))
    cells = 0
    for path in files:
        isin = path.stem
        family = company_family(taxonomy, table, isin=isin)
        symbol = isin_symbol.get(isin, isin)
        con = connect_ro(path, timeout_s=60)
        try:
            entity_names: set[str] = set()
            for sql in ("SELECT name FROM entity", "SELECT alias FROM entity_alias"):
                try:
                    entity_names |= {normalise_label(str(name)) for (name,) in _rows(con, sql) if name}
                except sqlite3.DatabaseError:      # a file built before T-149 has no entity table
                    continue
            tables: dict[tuple[str, object, int], list[tuple[str, str, str | None, object]]] = defaultdict(list)
            for doc_key, page, table_no, raw_label, col_header, unit_text, value in _rows(
                    con, "SELECT doc_key, page, table_no, row_label, col_header, unit_text, value "
                         "FROM table_cell"):
                tables[(str(doc_key), page, int(table_no or 0))].append((raw_label, col_header, unit_text, value))
            for (_doc, _page, _no), rows in tables.items():
                labels = {str(raw or "") for raw, _header, _unit, _value in rows}
                measure_rows = {str(raw or "") for raw, header, _unit, _value in rows
                                if "measure=" in str(header or "").lower()}
                parent_labels = {normalise_label(parent) for parent in
                                 (_split_label(raw)[0] for raw in labels) if parent}
                exact: dict[str, Proposal] = {}
                for raw in labels:
                    item = parse_label(*reversed(_split_label(raw)))
                    if not item.label_norm or item.junk:
                        continue
                    proposal = _candidate_proposal(item.label_norm, family, seeds, family_entries, common, item)
                    if proposal is not None:
                        exact[raw] = proposal
                peers = len([raw for raw in labels if raw not in exact])
                decisions: dict[str, tuple[str, Proposal | None, str]] = {}
                for raw in labels:
                    item = parse_label(*reversed(_split_label(raw)))
                    decisions[raw] = decide_label(
                        raw, family, seeds, family_entries, common, raw in measure_rows, bool(exact), peers,
                        item.label_norm in parent_labels,
                        item.label_norm in entity_names)
                for raw, _header, unit_text, value in rows:
                    cells += 1
                    key_label, proposal, rejection = decisions[raw]
                    if not key_label:
                        if value is not None:
                            blank_numeric[family] += 1
                        continue
                    if rejection:
                        rejected[(key_label, family)] = rejection
                    if proposal is not None:
                        forced[(key_label, proposal.family)] = proposal
                        if unit_text:
                            meta = metric_meta.setdefault(proposal.metric, MetricMeta())
                            meta.units[str(unit_text)] += 1
                            meta.sources.add(proposal.reason)
                    _observe(observations, (key_label, family), raw, symbol)
                    if unit_text:
                        observations[(key_label, family)].units[str(unit_text)] += 1
                    if value is not None:
                        numeric[(key_label, family)] += 1
        finally:
            con.close()
    return {"files": len(files), "cells": cells}


# ------------------------------------------------------------------------------------------------------ output
def _metric_defs(proposals: Iterable[Proposal], meta: dict[str, MetricMeta]) -> list[dict]:
    metrics: dict[str, MetricMeta] = {}
    sources: dict[str, set[str]] = defaultdict(set)
    for proposal in proposals:
        if not proposal.metric or proposal.metric == FROM_HEADER:
            continue
        sources[proposal.metric].add(proposal.reason)
        metrics.setdefault(proposal.metric, MetricMeta())
        if proposal.entry is not None:
            entry = proposal.entry
            if entry.unit:
                metrics[proposal.metric].units[entry.unit] += 1
                if not metrics[proposal.metric].entry_unit:
                    metrics[proposal.metric].entry_unit = entry.unit
            if entry.kind and not metrics[proposal.metric].entry_kind:
                metrics[proposal.metric].entry_kind = entry.kind
    for metric, metric_meta in meta.items():  # seed units are observed facts, so they rank above lexicon wording
        if metric == FROM_HEADER:
            continue
        target = metrics.setdefault(metric, MetricMeta())
        target.units.update(metric_meta.units)
    rows = []
    for metric in sorted(metrics):
        metric_meta = metrics[metric]
        unit_kind = resolve_unit_kind(metric, metric_meta)
        rows.append({"metric": metric, "kind": metric_kind(metric, unit_kind), "unit_kind": unit_kind,
                     "description": "T-133 proposed metric (" + ", ".join(sorted(sources.get(metric) or {"seed"}))
                     + ")."})
    return rows


REVIEW_COLUMNS = ("label_norm", "raw_labels", "frequency", "companies", "proposed_metric", "dimension",
                  "unit_kind", "reason", "rule", "confidence", "status")


def write_csv(path: Path, rows: Iterable[dict], columns: Sequence[str] = REVIEW_COLUMNS) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(rows)


def _queue_row(label_norm: str, obs: Observation, proposal: Proposal | None, unit_by_metric: Mapping[str, str],
               rejection: str = "") -> dict:
    metric = proposal.metric if proposal is not None else ""
    status = proposal.status if proposal is not None else (REJECTED if rejection else "")
    rule = (proposal.rule if proposal is not None else
            ("garbled" if rejection == "garbled" else ("6-reject" if rejection else "")))
    unit_kind = unit_by_metric.get(metric, "") if metric else ""
    if metric and not unit_kind and obs.units:
        unit_kind = majority_unit_kind(obs.units)
    return {"label_norm": label_norm,
            "raw_labels": "; ".join(raw for raw, _ in obs.raws.most_common(3)),
            "frequency": obs.count,
            "companies": ";".join(sorted(obs.companies)),
            "proposed_metric": metric,
            "dimension": proposal.dimension if proposal is not None else "",
            "unit_kind": unit_kind,
            "reason": (proposal.reason if proposal is not None else rejection),
            "rule": rule,
            "confidence": proposal.confidence if proposal is not None else "",
            "status": status}


def write_outputs(out_dir: Path, proposals: Mapping[tuple[str, str], Proposal],
                  observations: Mapping[tuple[str, str], Observation], numeric: Counter[tuple[str, str]],
                  blank_numeric: Counter[str], metric_meta: dict[str, MetricMeta],
                  rejected: Mapping[tuple[str, str], str]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    metric_defs = _metric_defs(proposals.values(), metric_meta)
    unit_by_metric = {row["metric"]: row["unit_kind"] for row in metric_defs}

    def label_unit(label_norm: str, family: str, metric: str) -> str:
        """Rule 4 (v3): the metric's unit when the lexicon states one, else this label's own cell majority."""
        kind = unit_by_metric.get(metric, "")
        if kind:
            return kind
        units: Counter[str] = Counter()
        for (name, observed_family), obs in observations.items():
            if name == label_norm and (family == ALL_FAMILIES or observed_family == family):
                units.update(obs.units)
        return majority_unit_kind(units)

    database = out_dir / "label_map.db"
    conn = sqlite3.connect(database)
    try:
        schema.create(conn)
        conn.execute("DELETE FROM label_map")
        conn.execute("DELETE FROM metric_def")
        rows = [(label_norm, family, proposal.metric, proposal.dimension,
                 label_unit(label_norm, family, proposal.metric), proposal.status)
                for (label_norm, family), proposal in sorted(proposals.items())]
        rows += [(label_norm, family, "", "", "", REJECTED)
                 for (label_norm, family) in sorted(rejected)
                 if (label_norm, family) not in proposals]
        conn.executemany(
            "INSERT INTO label_map (label_norm, sector_family, metric, dimension, unit_kind, status) "
            "VALUES (?,?,?,?,?,?)", rows)
        conn.executemany("INSERT INTO metric_def (metric, kind, unit_kind, description) VALUES (?,?,?,?)",
                         [(row["metric"], row["kind"], row["unit_kind"], row["description"])
                          for row in metric_defs])
        conn.commit()
    finally:
        conn.close()

    # Per-family review queues: every observed label, mapped or not, most frequent first.
    by_family: dict[str, list[tuple[str, Observation]]] = defaultdict(list)
    for (label_norm, family), obs in observations.items():
        by_family[family].append((label_norm, obs))
    proposed_rows: list[dict] = []
    for family in sorted(by_family):
        rows = []
        for label_norm, obs in sorted(by_family[family], key=lambda item: (-item[1].count, item[0])):
            proposal = proposals.get((label_norm, family))
            if proposal is None:
                proposal = next((p for (norm, fam), p in proposals.items()
                                 if fam == ALL_FAMILIES and norm == label_norm), None)
            row = _queue_row(label_norm, obs, proposal, unit_by_metric, rejected.get((label_norm, family), ""))
            rows.append(row)
            if row["proposed_metric"] and row["status"] == QUEUE:
                proposed_rows.append({**row, "family": family})
        write_csv(out_dir / f"review_{family}.csv", rows)

    # The '*' queue, one row per label the common tier proposes.
    common_totals: Counter[str] = Counter()
    common_companies: dict[str, set[str]] = defaultdict(set)
    common_raws: dict[str, Counter[str]] = defaultdict(Counter)
    common_units: dict[str, Counter[str]] = defaultdict(Counter)
    for (label_norm, _family), obs in observations.items():
        if (label_norm, ALL_FAMILIES) in proposals:
            common_totals[label_norm] += obs.count
            common_companies[label_norm] |= obs.companies
            common_raws[label_norm].update(obs.raws)
            common_units[label_norm].update(obs.units)
    write_csv(out_dir / "review_common.csv", [
        _queue_row(label_norm, Observation(common_totals[label_norm], common_raws[label_norm],
                                           common_companies[label_norm], common_units[label_norm]),
                   proposals[(label_norm, ALL_FAMILIES)], unit_by_metric)
        for label_norm in sorted(common_totals, key=lambda name: (-common_totals[name], name))])

    # Output: a seed-37 sample of 200 proposed rows across families for Opus to grade.
    sample_rows = random.Random(SAMPLE_SEED).sample(proposed_rows, min(SAMPLE_SIZE, len(proposed_rows)))
    write_csv(out_dir / SAMPLE_FILE,
              [{key: row.get(key, "") for key in REVIEW_COLUMNS + ("family",)} for row in sample_rows],
              REVIEW_COLUMNS + ("family",))

    # Coverage over numeric table rows (value IS NOT NULL), per family and overall.
    families = sorted({family for _, family in numeric} | set(blank_numeric))
    total_numeric = sum(numeric.values()) + sum(blank_numeric.values())
    mapped_keys = {(label_norm, family) for (label_norm, family), proposal in proposals.items()
                   if proposal.metric}
    mapped_common = {label_norm for (label_norm, family), proposal in proposals.items()
                     if family == ALL_FAMILIES and proposal.metric}
    total_mapped = sum(count for (label_norm, family), count in numeric.items()
                       if (label_norm, family) in mapped_keys or label_norm in mapped_common)
    unmapped: Counter[str] = Counter()
    for (label_norm, family), count in numeric.items():
        if (label_norm, family) not in proposals and (label_norm, ALL_FAMILIES) not in proposals:
            unmapped[label_norm] += count
    family_counts: dict[str, tuple[int, int]] = {}
    for family in families:
        rows = sum(count for (norm, fam), count in numeric.items() if fam == family) + blank_numeric[family]
        mapped = sum(count for (norm, fam), count in numeric.items() if fam == family
                     and ((norm, fam) in mapped_keys or norm in mapped_common))
        family_counts[family] = (rows, mapped)
    labeled_rows = total_numeric - sum(blank_numeric.values())
    rejected_rows = sum(count for (label_norm, family), count in numeric.items()
                        if (label_norm, family) in rejected)
    lines = [
        "label map coverage (T-133 v3)",
        f"numeric table_cell rows: {total_numeric}",
        f"mapped to a proposed metric: {total_mapped} ({100 * total_mapped / total_numeric:.1f}%)"
        if total_numeric else "mapped to a proposed metric: 0",
        f"rejected as junk/heading: {rejected_rows}",
        f"mapped or queued (label collected in review_<family>.csv): {labeled_rows} "
        f"({100 * labeled_rows / total_numeric:.1f}%)" if total_numeric else "mapped or queued: 0",
        f"blank labels (no row_label): {sum(blank_numeric.values())}",
        "",
        "per family:",
    ]
    for family in families:
        rows, mapped = family_counts[family]
        share = f"{100 * mapped / rows:.1f}%" if rows else "n/a"
        lines.append(f"  {family:24} rows {rows:8d}  mapped {mapped:8d}  {share:>6}")
    lines.append("")
    lines.append("50 most frequent unmapped labels:")
    for index, (label_norm, count) in enumerate(sorted(unmapped.items(), key=lambda item: (-item[1], item[0]))[:50],
                                                start=1):
        lines.append(f"  {index:2d}. {count:6d}  {label_norm}")
    (out_dir / "coverage.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"label_map": len(proposals), "metrics": len(metric_defs), "numeric_rows": total_numeric,
            "mapped_rows": total_mapped, "total": total_numeric, "rejected_rows": rejected_rows}


def kpi_seed_changes(kpi_dbs: Sequence[Path], out_dir: Path) -> dict:
    """Rule 2 dry run: how many ``kpi_series`` rows the new whole-label rule changes, by (old, new) pair.

    Read-only against the stores; nothing is written back.  The rule applied is the one :mod:`pilot3.kpi` uses, so
    the table predicts the next extraction, not just this review queue.
    """
    from reality_engine.pilot3 import kpi as kpi_module

    entries, _dims = kpi_module.load_lexicon()
    changes: Counter[tuple[str, str]] = Counter()
    total = 0
    for path in kpi_dbs:
        con = connect_ro(path, timeout_s=60)
        try:
            for symbol, raw_label, metric in _rows(con, "SELECT symbol, raw_label, metric FROM kpi_series "
                                                       "WHERE raw_label IS NOT NULL AND TRIM(raw_label) <> '' "
                                                       "AND extractor_rule='table_v1'"):
                total += 1
                hits = kpi_module.row_label_hits(entries, symbol, str(raw_label))
                new = hits[0][0].metric if hits else ""
                if new != str(metric):
                    changes[(str(metric), new)] += 1
        finally:
            con.close()
    rows = [{"old_metric": old, "new_metric": new, "rows": count}
            for (old, new), count in sorted(changes.items(), key=lambda item: (-item[1], item[0]))]
    write_csv(out_dir / "seed_changes.csv", rows, ("old_metric", "new_metric", "rows"))
    return {"kpi_rows": total, "changed_rows": sum(changes.values()), "pairs": len(changes)}


def run(cells_dir: Path, kpi_dbs: Sequence[Path], out_dir: Path,
        taxonomy_path: Path | None = None) -> dict:
    taxonomy = connect_ro(taxonomy_path or main_store(), timeout_s=60)
    table = sector_map()
    family_entries, common = load_lexicons()
    observations: dict[tuple[str, str], Observation] = {}
    seed_counts: dict[tuple[str, str], Counter[str]] = {}
    metric_meta: dict[str, MetricMeta] = {}
    numeric: Counter[tuple[str, str]] = Counter()
    blank_numeric: Counter[str] = Counter()
    isin_symbol = _symbol_by_isin(kpi_dbs)
    family_cache: dict[tuple[str | None, str | None], str] = {}
    forced: dict[tuple[str, str], Proposal] = {}
    rejected_labels: dict[tuple[str, str], str] = {}
    rejected_seeds: list[dict] = []
    try:
        kpi_rows = read_kpis(taxonomy, table, kpi_dbs, observations, seed_counts, metric_meta, isin_symbol,
                             family_cache, family_entries, common, rejected_seeds, rejected_labels)
        seeds = {key: sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]
                 for key, counter in seed_counts.items()}
        cell_stats = read_cells(cells_dir, taxonomy, table, isin_symbol, observations, numeric, blank_numeric,
                                seeds, family_entries, common, metric_meta, forced, rejected_labels)
    finally:
        taxonomy.close()

    proposals: dict[tuple[str, str], Proposal] = {}
    for label_norm, family in sorted(observations):
        if (label_norm, family) in forced:
            continue
        item = parse_label(label_norm)
        if item.junk:
            rejected_labels.setdefault((label_norm, family), item.junk)
            continue
        proposal = _candidate_proposal(label_norm, family, seeds, family_entries, common, item)
        if proposal is None:
            garbled = garbled_reason(label_norm)
            if garbled:
                rejected_labels.setdefault((label_norm, family), garbled)
                continue
        if " > " in label_norm:
            continue
        if proposal is None:
            continue
        key = (label_norm, proposal.family)
        proposals.setdefault(key, proposal)
        metric_meta.setdefault(proposal.metric, MetricMeta()).sources.add(proposal.reason)
    for key, proposal in forced.items():  # a section/context override wins over the child-only proposal
        proposals[key] = proposal
        metric_meta.setdefault(proposal.metric, MetricMeta()).sources.add(proposal.reason)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "rejected_seeds.csv",
              [{key: row[key] for key in ("raw_label", "label_norm", "family", "metric", "new_metric", "reason")}
               for row in rejected_seeds],
              ("raw_label", "label_norm", "family", "metric", "new_metric", "reason"))
    seed_dry = kpi_seed_changes(kpi_dbs, out_dir)

    stats = write_outputs(out_dir, proposals, observations, numeric, blank_numeric, metric_meta, rejected_labels)
    stats.update({"kpi_rows": kpi_rows, **cell_stats, "observations": len(observations),
                  "rejected_seeds": len(rejected_seeds), **seed_dry})
    reasons = Counter(proposal.rule for proposal in proposals.values())
    kinds = Counter(row["kind"] for row in _metric_defs(proposals.values(), metric_meta))
    families = sorted({family for _, family in observations})
    unknown_companies = sorted({company for (_, family), obs in observations.items() if family == UNKNOWN
                                for company in obs.companies})
    print(f"label map: {len(proposals)} rows from {len(observations)} (label, family) observations; rules "
          + ", ".join(f"{rule} {count}" for rule, count in sorted(reasons.items())))
    print(f"sources: kpi_series {kpi_rows} rows from {len(kpi_dbs)} db(s), {len(rejected_seeds)} seed rows rejected; "
          f"table_cell {cell_stats['cells']} cells from {cell_stats['files']} company file(s)")
    print(f"metric_def: {stats['metrics']} metrics; kinds " +
          ", ".join(f"{kind} {count}" for kind, count in sorted(kinds.items())))
    print(f"seed dry run: {seed_dry['changed_rows']} of {seed_dry['kpi_rows']} kpi_series rows change metric "
          f"({seed_dry['pairs']} pairs) -> seed_changes.csv")
    print(f"families: {', '.join(families)}")
    if unknown_companies:
        print(f"unknown family companies ({len(unknown_companies)}): {', '.join(unknown_companies)}")
    print(f"coverage: {stats['mapped_rows']}/{stats['numeric_rows']} numeric rows "
          f"({100 * stats['mapped_rows'] / stats['numeric_rows']:.1f}%), rejected {stats['rejected_rows']}"
          if stats["numeric_rows"] else "coverage: no numeric rows")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-133 label dictionary (printed label -> metric per family)")
    parser.add_argument("--cells-dir", required=True, type=Path, help="v2 store root (has company/*.db)")
    parser.add_argument("--kpi-db", action="append", default=[], type=Path,
                        help="pilot3 database holding kpi_series (repeatable)")
    parser.add_argument("--out", required=True, type=Path, help="output folder")
    parser.add_argument("--taxonomy-db", type=Path, default=None,
                        help="equity_intelligence.db (default: REALITY_DATA_ROOT)")
    args = parser.parse_args(argv)
    run(args.cells_dir, args.kpi_db, args.out, args.taxonomy_db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
