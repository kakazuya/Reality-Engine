"""T-230 stage A: one ``observation`` row per printed quantity on a deck / annual-report visual.

The flat ``page_cell`` (row_label, col_header, value_text) loses the slide's groups, the chart a
number belongs to, and whether a figure is the company's or the industry's.  This writer asks
hy4-flash-free once per visual page (page image + its text layer) for observations in the T-230
shape, then checks them independently of the model:

* ``value_text`` must occur as a token in the stored page text when the page has one (a value whose
  digits are nowhere on the page is quarantined); a page with no text layer is unverified.
* ``printed_label`` / ``printed_axis`` / ``group_path`` must be substrings of the page text.
* the unit must map to a unit family, and that family must agree with the measure dictionary.
* a series whose printed total is accompanied by its parts must sum to it within 0.5% (passed parts
  become verified; a mismatch is unverified, never repaired).
* ``known_at`` is copied from the store's ``doc`` row, never from the model; ``value`` is parsed by
  the script from ``value_text``, never taken from the model; ``region`` comes from the text-layer
  word boxes when the value is found there.
* (stage F) ``--skip-statements`` drops an annual report's financial-statement and notes pages from
  the stored text layer before any model call; a notes page printing a segment table (or a BRSR page
  with the plant-location table) is kept.  The run reports kept/dropped counts by reason.

Output is a separate SQLite file (``--out``, default ``.tmp/t230/obs.db``); a store is only ever
read.  Tables: ``observation``, ``measure_dict``, ``dim_vocab``.

Usage:
    python -m reality_engine.v2.observations --stores-root D:/RealityEngine/tg_build/measure10 \
        --sample 5 --ensure c08,c26 --seed 11 --limit 150 --workers 10
    python -m reality_engine.v2.observations --stores c08,c26 --limit 20 --workers 10
    python -m reality_engine.v2.observations --stores-root D:/RealityEngine/tg_build/measure10 \
        --sample 91 --doc-types annual_report --skip-statements --workers 20 --resume \
        --out .tmp/t230ar/obs_ar_91.db
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

from reality_engine.db.readonly import connect_ro
from reality_engine.scripts.extract_deck_figures import parse_number
from reality_engine.v2 import page_layout, page_reader, page_words
from reality_engine.v2 import reference_pages as rp

READER = "hy4-flash-free"
OBS_READER = "hy4-flash-free@obs"      # same model, more room for a page of JSONL observations
TEXT_LAYER_CHARS = 6000
PARSE_STOP = 0.20                      # brief: stop when >20% of pilot pages give empty / non-JSON
QUARANTINE_STOP = 0.10                 # brief: stop when >10% of observations are quarantined

if OBS_READER not in rp.MODELS:        # do not mutate another job's reader: this is our own entry
    rp.MODELS[OBS_READER] = {**rp.MODELS["hy4-flash-free"], "id": "hy4-flash-free",
                             "body": {**rp.MODELS["hy4-flash-free"]["body"], "max_tokens": 16000}}

# --------------------------------------------------------------------------- schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS observation (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    doc_key TEXT NOT NULL,
    page INTEGER NOT NULL,
    region TEXT NOT NULL DEFAULT '',
    known_at TEXT NOT NULL,
    measure TEXT NOT NULL DEFAULT '',
    printed_label TEXT NOT NULL DEFAULT '',
    printed_axis TEXT NOT NULL DEFAULT '',
    value REAL,
    value_text TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    unit_family TEXT NOT NULL DEFAULT '',
    scale REAL NOT NULL DEFAULT 1,
    adjusted INTEGER NOT NULL DEFAULT 0,
    period TEXT NOT NULL DEFAULT '',
    period_kind TEXT NOT NULL DEFAULT '',
    period_source TEXT NOT NULL DEFAULT '',
    basis TEXT NOT NULL DEFAULT '',
    series_kind TEXT NOT NULL DEFAULT '',
    segment TEXT NOT NULL DEFAULT '',
    product TEXT NOT NULL DEFAULT '',
    geography TEXT NOT NULL DEFAULT '',
    plant TEXT NOT NULL DEFAULT '',
    customer TEXT NOT NULL DEFAULT '',
    group_path TEXT NOT NULL DEFAULT '',
    group_source TEXT NOT NULL DEFAULT '',
    group_check TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT '',
    series_id TEXT NOT NULL DEFAULT '',
    series_title TEXT NOT NULL DEFAULT '',
    entity_scope TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('verified', 'unverified', 'quarantined')),
    status_reason TEXT NOT NULL DEFAULT '',
    reader TEXT NOT NULL DEFAULT '',
    read_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS observation_page ON observation (doc_key, page);
CREATE INDEX IF NOT EXISTS observation_symbol ON observation (symbol, measure);
CREATE INDEX IF NOT EXISTS observation_status ON observation (status);

CREATE TABLE IF NOT EXISTS measure_dict (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit_family TEXT NOT NULL DEFAULT '',
    driver_node TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS dim_vocab (
    kind TEXT NOT NULL,
    canonical TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (kind, canonical)
);

CREATE TABLE IF NOT EXISTS measure_proposal (
    printed_label TEXT PRIMARY KEY,
    measure TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'hy4',
    proposed_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS http_429 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at_ist TEXT NOT NULL,
    doc_key TEXT NOT NULL DEFAULT '',
    page INTEGER,
    message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS measure_alias (
    alias TEXT PRIMARY KEY,
    canonical TEXT NOT NULL
);
"""

MIGRATIONS = (("group_source", "TEXT NOT NULL DEFAULT ''"), ("group_check", "TEXT NOT NULL DEFAULT ''"),
              ("adjusted", "INTEGER NOT NULL DEFAULT 0"), ("period_source", "TEXT NOT NULL DEFAULT ''"),
              ("basis", "TEXT NOT NULL DEFAULT ''"), ("series_kind", "TEXT NOT NULL DEFAULT ''"))

# id, name, unit family, node in the T-228 driver tree
MEASURES: tuple[tuple[str, str, str, str], ...] = (
    ("capacity.total", "Total / operating capacity", "capacity", "capacity.total"),
    ("capacity.add", "Capacity added or planned", "capacity", "capacity.add"),
    ("capacity.utilisation", "Capacity utilisation", "percent", "capacity.utilisation"),
    ("capacity.growth_multiple", "Growth multiple (x) of capacity", "ratio", "capacity.add"),
    ("volume.sales", "Units or volume sold / handled", "count", "revenue.volume"),
    ("volume.production", "Units or volume produced", "count", "cost.volume"),
    ("revenue.value", "Revenue", "money", "revenue.value"),
    ("revenue.price", "Realisation or price per unit", "money_per_unit", "revenue.price"),
    ("revenue.mix", "Revenue or volume split by segment / geography", "money", "revenue.mix"),
    ("mix.share", "Share of a mix (percent of revenue / volume)", "percent", "revenue.mix"),
    ("revenue_from_operations", "Revenue from operations", "money", "revenue.value"),
    ("total_income", "Total income", "money", "revenue.value"),
    ("total_expenses", "Total expenses", "money", "cost.total"),
    ("finance_cost", "Finance cost", "money", "cost.finance"),
    ("ebitda", "EBITDA", "money", "profit.ebitda"),
    ("profit_before_tax", "Profit before tax", "money", "profit.pbt"),
    ("pat", "Profit after tax", "money", "profit.pat"),
    ("total_assets", "Total assets", "money", "balance.assets"),
    ("total_equity", "Total equity", "money", "balance.equity"),
    ("borrowings", "Borrowings", "money", "balance.debt"),
    ("cash_and_cash_equivalents", "Cash and cash equivalents", "money", "balance.cash"),
    ("eps", "Earnings per share", "money_per_unit", "profit.eps"),
    ("ebitda_margin", "EBITDA margin", "percent", "profit.ebitda"),
    ("pat_margin", "PAT margin", "percent", "profit.pat"),
    ("revenue_growth_yoy", "Revenue growth (YoY)", "percent", "revenue.value"),
    ("ebitda_per_kg", "EBITDA per kg", "money_per_unit", "profit.ebitda"),
    ("market.value", "Industry or market size (money)", "money", "market.size"),
    ("capex", "Capex", "money", "capex.value"),
    ("capex.estimated", "Estimated capex", "money", "capex.value"),
    ("inventories", "Inventories", "money", "balance.working_capital"),
    ("trade_receivables", "Trade receivables", "money", "balance.working_capital"),
    ("trade_payables", "Trade payables", "money", "balance.working_capital"),
    ("provisions", "Provisions", "money", "balance.provisions"),
    ("other_income", "Other income", "money", "revenue.other"),
    ("total_tax_expense", "Tax expense", "money", "profit.tax"),
    ("ebit", "EBIT", "money", "profit.ebitda"),
    ("lease_liabilities", "Lease liabilities", "money", "balance.lease"),
    ("employee_benefits_expense", "Employee benefits expense", "money", "cost.employee"),
    ("depreciation_and_amortisation_expense", "Depreciation and amortisation", "money", "cost.depreciation"),
    ("other_expenses", "Other expenses", "money", "cost.other"),
    ("other_equity", "Other equity", "money", "balance.equity"),
    ("equity_share_capital", "Equity share capital", "money", "balance.equity"),
    ("other_financial_liabilities", "Other financial liabilities", "money", "balance.other_liabilities"),
    ("other_current_liabilities", "Other current liabilities", "money", "balance.other_liabilities"),
    ("other_non_current_assets", "Other non-current assets", "money", "balance.other_assets"),
    ("other_current_assets", "Other current assets", "money", "balance.other_assets"),
    ("total_current_assets", "Total current assets", "money", "balance.assets"),
    ("total_non_current_assets", "Total non-current assets", "money", "balance.assets"),
    ("total_current_liabilities", "Total current liabilities", "money", "balance.liabilities"),
    ("total_non_current_liabilities", "Total non-current liabilities", "money", "balance.liabilities"),
    ("total_equity_and_liabilities", "Total equity and liabilities", "money", "balance.total"),
    ("property_plant_and_equipment", "Property, plant and equipment", "money", "balance.fixed_assets"),
    ("capital_work_in_progress", "Capital work in progress", "money", "balance.fixed_assets"),
    ("right_to_use", "Right-of-use assets", "money", "balance.fixed_assets"),
    ("other_intangible_assets", "Other intangible assets", "money", "balance.fixed_assets"),
    ("non_current_assets", "Non-current assets", "money", "balance.assets"),
    ("current_assets", "Current assets", "money", "balance.assets"),
    ("non_current_liabilities", "Non-current liabilities", "money", "balance.liabilities"),
    ("current_liabilities", "Current liabilities", "money", "balance.liabilities"),
    ("gross_profit", "Gross profit", "money", "profit.gross"),
    ("count.rakes", "Number of rakes", "count", "revenue.volume"),
    ("pipeline.length", "Pipeline length", "length", "capacity.add"),
    ("order.intake", "Order intake / new orders", "money", "order.intake"),
    ("order.book", "Order book", "money", "order.book"),
    ("market.size", "Industry or market size", "count", "market.size"),
    ("market.share", "Market share", "percent", "market.share"),
    ("count.plants", "Number of plants / facilities / terminals", "count", "capex.site_count"),
    ("count.customers", "Number of customers / subscribers", "count", "revenue.customer_count"),
    ("logistics.throughput", "Port / logistics throughput", "count", "logistics.throughput"),
    ("cash_flow.operating", "Net cash from operating activities", "money", "cash.operating"),
    ("cash_flow.investing", "Net cash from investing activities", "money", "cash.investing"),
    ("cash_flow.financing", "Net cash from financing activities", "money", "cash.financing"),
    ("cash_flow.net_change", "Net change in cash", "money", "cash.net"),
    ("cash_generated_from_operations", "Cash generated from operations", "money", "cash.operating"),
    ("changes_in_working_capital", "Changes in working capital", "money", "cash.working_capital"),
    ("adjustment_for_non_operating_items", "Adjustment for non-operating items", "money", "cash.operating"),
    ("direct_taxes_paid", "Direct taxes paid", "money", "cash.tax"),
    ("deferred_tax", "Deferred tax", "money", "profit.tax"),
    ("current_tax", "Current tax", "money", "profit.tax"),
    ("deferred_tax_liabilities_net", "Deferred tax liabilities (net)", "money", "balance.tax"),
    ("current_tax_liabilities_net", "Current tax liabilities (net)", "money", "balance.tax"),
    ("current_tax_assets_net", "Current tax assets (net)", "money", "balance.tax"),
    ("other_bank_balances", "Other bank balances", "money", "balance.cash"),
    ("other_financial_assets", "Other financial assets", "money", "balance.other_assets"),
    ("loans", "Loans", "money", "balance.other_assets"),
    ("cost_of_goods_sold", "Cost of goods sold", "money", "cost.total"),
    ("cost_of_services", "Cost of services", "money", "cost.total"),
    ("raw_material_cost", "Raw material cost", "money", "cost.total"),
    ("exceptional_items", "Exceptional items", "money", "profit.other"),
    ("gp_percent", "Gross profit margin", "percent", "profit.gross"),
    ("gross_profit_margin", "Gross profit margin", "percent", "profit.gross"),
    ("pbt_margin", "PBT margin", "percent", "profit.pbt"),
    ("ebitda_growth_yoy", "EBITDA growth (YoY)", "percent", "profit.ebitda"),
    ("profit_growth_yoy", "Profit growth (YoY)", "percent", "profit.pat"),
    ("pat_growth_yoy", "PAT growth (YoY)", "percent", "profit.pat"),
    ("goodwill", "Goodwill", "money", "balance.fixed_assets"),
    ("product_weight_range", "Product weight range", "count", "revenue.volume"),
    ("distance_from_chennai", "Distance from Chennai", "length", "logistics.distance"),
    ("count.beneficiaries", "Beneficiaries", "count", "other.people"),
    ("health_consultations", "Health consultations", "count", "other.people"),
    ("iso_certification", "ISO certification", "count", "other.compliance"),
    ("freight_rebate", "Freight rebate", "percent", "cost.freight"),
    ("freight_rebate_duration", "Freight rebate duration", "time", "cost.freight"),
    ("launch_year", "Launch year", "count", "other.year"),
    ("market.growth", "Market growth", "percent", "market.size"),
    ("incremental_demand", "Incremental demand", "count", "market.size"),
    ("count.states", "Number of states", "count", "other.geography"),
    ("tree_plantations", "Trees planted", "count", "other.esg"),
    ("water_managed", "Water managed", "count", "other.esg"),
    ("gender_ratio", "Gender ratio", "ratio", "other.esg"),
    ("capex.investment", "Capex investment", "money", "capex.value"),
    ("count.manufacturing_sections", "Manufacturing sections", "count", "capex.site_count"),
    ("loans.disbursement", "Loan disbursements (flow)", "money", "loans.disbursement"),
    ("loans.disbursement_mix", "Disbursements by segment / geography", "money", "loans.disbursement"),
    ("loans.disbursement_share", "Share of disbursements (percent)", "percent", "loans.disbursement"),
    ("capacity.spindles", "Spindles installed / planned", "count", "capacity.add"),
    ("order.book_growth_yoy", "Order book growth (YoY)", "percent", "order.book"),
    ("order.intake_growth_yoy", "Order intake growth (YoY)", "percent", "order.intake"),
    ("aum.value", "Assets under management", "money", "aum.value"),
    ("aum.growth_yoy", "AUM growth (YoY)", "percent", "aum.value"),
    ("ebitda.delta", "EBITDA bridge step", "money", "profit.ebitda"),
    ("ebitda_margin.delta", "EBITDA margin bridge step", "percent", "profit.ebitda"),
    ("revenue.delta", "Revenue bridge step", "money", "revenue.value"),
    ("pat.delta", "PAT bridge step", "money", "profit.pat"),
    ("revenue_growth_cagr", "Revenue CAGR over a span", "percent", "revenue.value"),
    ("ebitda_growth_cagr", "EBITDA CAGR over a span", "percent", "profit.ebitda"),
    ("pat_growth_cagr", "PAT CAGR over a span", "percent", "profit.pat"),
    ("profit_growth_cagr", "Profit CAGR over a span", "percent", "profit.pat"),
)

# Near-duplicate model ids -> one dictionary id (T-230 stage C3). Applied before the dictionary check.
MEASURE_ALIASES: dict[str, str] = {
    "order_book_growth_yoy": "order.book_growth_yoy",
    "order_book_growth": "order.book_growth_yoy",
    "orderbook_growth_yoy": "order.book_growth_yoy",
    "order_intake_growth_yoy": "order.intake_growth_yoy",
    "order_intake_growth": "order.intake_growth_yoy",
    "order_book": "order.book",
    "orderbook": "order.book",
    "order_intake": "order.intake",
    "aum": "aum.value",
    "aum_growth_yoy": "aum.growth_yoy",
    "loan_book": "loans",
    "loan_disbursement": "loans.disbursement",
    "disbursement": "loans.disbursement",
    "disbursements": "loans.disbursement",
    "disbursement_mix": "loans.disbursement_mix",
    "spindles": "capacity.spindles",
    "number_of_spindles": "capacity.spindles",
    "installed_spindles": "capacity.spindles",
}

# Curated printed label -> measure id (T-230 stage B, Wolf): applied by the script before the dictionary check.
# Exact match after lower-casing, whitespace collapsing and dropping a leading list mark ("(ii)", "a)", "3.").
_SCRIPT_LABEL_MARK = re.compile(r"^\s*(?:\(?[ivxlcdm]+\)?|[a-zA-Z]\)|\d+[.)])\s*", re.I)
SCRIPT_LABELS: dict[str, str] = {
    "revenue from operations": "revenue_from_operations",
    "total revenue": "revenue.value",
    "revenue": "revenue.value",
    "total income": "total_income",
    "other income": "other_income",
    "total expenses": "total_expenses",
    "total expense": "total_expenses",
    "cost of goods sold": "cost_of_goods_sold",
    "cost of services": "cost_of_services",
    "raw material cost": "raw_material_cost",
    "employee benefits expense": "employee_benefits_expense",
    "other expenses": "other_expenses",
    "ebitda": "ebitda",
    "ebit": "ebit",
    "finance cost": "finance_cost",
    "finance costs": "finance_cost",
    "depreciation and amortisation expense": "depreciation_and_amortisation_expense",
    "depreciation and amortization expense": "depreciation_and_amortisation_expense",
    "pbt": "profit_before_tax",
    "profit before tax": "profit_before_tax",
    "pat": "pat",
    "profit after tax": "pat",
    "profit for the period": "pat",
    "profit for the year": "pat",
    "profit for the year (pat)": "pat",
    "total tax expense": "total_tax_expense",
    "total tax expenses": "total_tax_expense",
    "tax expense": "total_tax_expense",
    "eps": "eps",
    "basic eps": "eps",
    "diluted eps": "eps",
    "earnings per share": "eps",
    "equity": "total_equity",
    "total equity": "total_equity",
    "equity share capital": "equity_share_capital",
    "other equity": "other_equity",
    "borrowings": "borrowings",
    "long-term borrowings": "borrowings",
    "short-term borrowings": "borrowings",
    "inventories": "inventories",
    "trade receivable": "trade_receivables",
    "trade receivables": "trade_receivables",
    "trade payables": "trade_payables",
    "provisions": "provisions",
    "total assets": "total_assets",
    "total current assets": "total_current_assets",
    "total non-current assets": "total_non_current_assets",
    "total current liabilities": "total_current_liabilities",
    "total non-current liabilities": "total_non_current_liabilities",
    "total equity and liabilities": "total_equity_and_liabilities",
    "total equities & liabilities": "total_equity_and_liabilities",
    "cash and cash equivalents": "cash_and_cash_equivalents",
    "cash & cash equivalents": "cash_and_cash_equivalents",
    "net cash from operating activities": "cash_flow.operating",
    "net cash from investing activities": "cash_flow.investing",
    "net cash from financing activities": "cash_flow.financing",
    "cash generated from operations": "cash_generated_from_operations",
    "changes in working capital": "changes_in_working_capital",
    "adjustment for non-operating items": "adjustment_for_non_operating_items",
    "direct taxes paid": "direct_taxes_paid",
    "less: direct taxes paid": "direct_taxes_paid",
    "deferred tax liabilities (net)": "deferred_tax_liabilities_net",
    "current tax liabilities (net)": "current_tax_liabilities_net",
    "gross profit": "gross_profit",
    "gp %": "gp_percent",
    "gross profit margin": "gross_profit_margin",
    "pbt margin": "pbt_margin",
    "pat margin": "pat_margin",
    "ebitda margin": "ebitda_margin",
    "ebitda %": "ebitda_margin",
    "ebitda margin %": "ebitda_margin",
    "pat margin %": "pat_margin",
}


def norm_label(label: str) -> str:
    return _SCRIPT_LABEL_MARK.sub("", norm_space(label).lower()).strip()


def script_measure(label: str) -> str:
    return SCRIPT_LABELS.get(norm_label(label), "")

# kind, canonical, aliases ("|" separated) -- printed words become the canonical token
DIM_VOCAB: tuple[tuple[str, str, str], ...] = (
    ("stage", "operating", "operating|in operation|operational"),
    ("stage", "under_construction", "under construction|construction|being built"),
    ("stage", "approved", "approved|approval received|cleared"),
    ("stage", "under_review", "under review|review|awaiting approval"),
    ("stage", "potential", "potential|pipeline|proposed|planned"),
    ("geography", "India", "india|domestic|bharat"),
    ("geography", "USA", "usa|us|united states|america"),
    ("geography", "Odisha", "odisha|orissa"),
    ("geography", "Karnataka", "karnataka"),
    ("geography", "Maharashtra", "maharashtra"),
    ("geography", "Goa", "goa"),
    ("geography", "Tamil Nadu", "tamil nadu|tuticorin"),
    ("product", "LPG", "lpg|liquefied petroleum gas"),
    ("product", "container", "container|containers|teu"),
    ("product", "bulk", "bulk|dry bulk"),
    ("product", "liquid", "liquid|liquids"),
    ("product", "slurry", "slurry"),
)

SCOPES = ("company", "subsidiary", "parent", "industry", "country", "customer", "peer")
PERIOD_KINDS = ("actual", "estimate", "target", "span")
STAGES = ("operating", "under_construction", "approved", "under_review", "potential")
DIMS = ("segment", "product", "geography", "plant", "customer")

# unit text -> family, first match wins
UNIT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("percent", r"%|percent\b|pct\b|bps\b|basis points"),
    ("money_per_unit", r"(?:rs|inr|\u20b9|\$|usd|us\$)[^a-z]*(?:per\b|/)|/ ?(?:tonne|ton|unit|km|kg|mt|share)\b|"
                       r"(?:^|\s)per (?:share|unit|tonne|ton|kg|km|mt)\b|arpu|arr\b|revpar|realis|realiz"),
    ("count", r"\bunits?\b|\bnos\b|\bnumbers?\b|\bthousands?\b|\bteus?\b|\bvehicles?\b|\btractors?\b|"
              r"\bcustomers?\b|\bsubscribers?\b|\bplants?\b|\bterminals?\b|\binstances?\b|"
              r"\blitres?\b|\bliters?\b|\bltrs?\b"),
    ("capacity", r"\bmtpa\b|\bmmtpa\b|\btpa\b|\btpd\b|\btonnes?\b|\btons?\b|\bmt\b|\bmw\b|\bgw\b|\bkw\b"),
    ("money", r"rs\b|inr\b|\u20b9|rupees?\b|crores?\b|\bcrs?\b|\bcr\b|lakhs?\b|lacs?\b|millions?\b|\bmn\b|"
              r"billions?\b|\bbn\b|usd\b|us\$|\$|euros?\b|eur\b"),
    ("length", r"\bkm\b|kilomet(?:er|re)s?\b|\bmiles?\b"),
    ("area", r"\bsft\b|sq\.? ?ft|square feet|\bsqm\b|\bhectares?\b|\bacres?\b"),
    ("time", r"\bdays?\b|\bmonths?\b|\byears?\b"),
    ("ratio", r"^x$|\btimes\b|\bmultiple\b"),
)
CONVERT_FAMILY = {"capacity": {"count"}, "count": {"capacity"}, "money_per_unit": {"money"}}

FOOTNOTE_LABEL = re.compile(r"^\s*(?:\*|#|note\b|source\b|footnote\b)", re.I)
JUNK_MEASURE = re.compile(
    r"^(?:page|phone|telephone|mobile|fax|postal|pin|address|street|floor|tower|sector|plot|registration|"
    r"regulation|cin|din|scrip|signature|date|award|certification|website|email|gst|pan|reporting)"
    r"(?:[._][a-z0-9]+)*$", re.I)
SCALE_WORDS = ((r"thousands?", 1e3), (r"'000|000s", 1e3), (r"\blakhs?\b|\blacs?\b", 1e5),
               (r"\bcrores?\b|\bcrs?\b|\bcr\.", 1e7), (r"\bmillions?\b|\bmn\b|\bmm\b", 1e6),
               (r"\bbillions?\b|\bbn\b", 1e9))

# columns that go into the observation row from one model reply object
ROW_TEXT_KEYS = ("measure", "printed_label", "printed_axis", "unit", "period", "segment", "product",
                 "geography", "plant", "customer", "group_path", "series_id", "series_title", "entity_scope")


def norm_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def text_has(text: str, needle: str) -> bool:
    """``needle`` occurs in ``text`` as a printed token, not inside a longer number ('30' is not in '2030')."""
    n = norm_space(needle)
    if not n:
        return False
    return re.search(r"(?<![\d.,])" + re.escape(n) + r"(?![\d.,])", norm_space(text)) is not None


def infer_unit_family(unit: str) -> str:
    """The unit family of a printed unit; empty when no unit was printed or it is not one we know."""
    low = norm_space(unit).lower()
    if not low:
        return ""
    for family, pattern in UNIT_PATTERNS:
        if re.search(pattern, low):
            return family
    return ""


def family_ok(measure_family: str, unit_family: str) -> bool:
    if not measure_family or not unit_family:
        return True
    return unit_family == measure_family or unit_family in CONVERT_FAMILY.get(measure_family, set())


def parse_reply(text: str) -> tuple[list[dict[str, Any]], int]:
    """Model reply -> (observation objects, lines that looked like content but did not parse)."""
    raw = str(text or "").strip()
    if not raw:
        return [], 0
    raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw).strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, list):
            return [r for r in obj if isinstance(r, dict)], 0
        if isinstance(obj, dict):
            for key in ("observations", "rows", "data"):
                if isinstance(obj.get(key), list):
                    return [r for r in obj[key] if isinstance(r, dict)], 0
            return [obj], 0
    except json.JSONDecodeError:
        pass
    rows: list[dict[str, Any]] = []
    bad = 0
    for line in raw.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            if line.startswith("{"):
                bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows, bad


def measure_index(measures: Iterable[tuple[str, str, str, str]] = MEASURES) -> dict[str, dict[str, str]]:
    return {mid: {"name": name, "unit_family": fam, "driver_node": node} for mid, name, fam, node in measures}


def vocab_index(rows: Iterable[tuple[str, str, str]] = DIM_VOCAB) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for kind, canonical, aliases in rows:
        for alias in str(aliases).split("|"):
            alias = norm_space(alias).lower()
            if alias:
                out[(kind, alias)] = canonical
    return out


def canonical_dim(vocab: dict[tuple[str, str], str], kind: str, raw: str) -> str:
    value = norm_space(raw)
    if not value:
        return ""
    return vocab.get((kind, value.lower()), value)


def canonical_stage(vocab: dict[tuple[str, str], str], raw: str) -> str:
    """A printed stage word or group heading -> stage token ('Projects Approved' -> approved)."""
    low = norm_space(raw).lower()
    if not low:
        return ""
    exact = vocab.get(("stage", low))
    if exact in STAGES:
        return exact
    aliases = sorted(((alias, canonical) for (kind, alias), canonical in vocab.items()
                      if kind == "stage" and alias in low), key=lambda item: -len(item[0]))
    return aliases[0][1] if aliases and aliases[0][1] in STAGES else ""


def stage_from_group(vocab: dict[tuple[str, str], str], group_path: str) -> str:
    for part in reversed(str(group_path or "").split(" > ")):
        stage = canonical_stage(vocab, part)
        if stage:
            return stage
    return ""


def canonical_scope(raw: str) -> str:
    low = norm_space(raw).lower().replace("-", "_")
    synonyms = {"group": "company", "own": "company", "company_total": "company",
                "industry_total": "industry", "economy": "country", "competitor": "peer",
                "portfolio_company": "subsidiary"}
    low = synonyms.get(low, low)
    return low if low in SCOPES else ""


def canonical_group_source(raw: str) -> str:
    low = norm_space(raw).lower().replace("-", "_")
    if low in ("printed", "legend_inferred"):
        return low
    if low in ("legend", "colour", "color", "visual", "inferred"):
        return "legend_inferred"
    return ""


def period_kind_for(raw: str, period: str) -> str:
    low = norm_space(raw).lower()
    synonyms = {"estimated": "estimate", "est": "estimate", "forecast": "estimate",
                "projected": "estimate", "projection": "estimate", "guidance": "target"}
    low = synonyms.get(low, low)
    if low in PERIOD_KINDS:
        return low
    if re.search(r"\dE\b|\bE\b|\best\.?\b", period):
        return "estimate"
    return ""


def _scale_factor(text: str) -> float | None:
    factors = {value for pattern, value in SCALE_WORDS if re.search(pattern, str(text or ""), re.I)}
    return factors.pop() if len(factors) == 1 else None


def printed_scale(raw_scale: Any, row: dict[str, Any], page_text: str) -> tuple[float, list[str]]:
    """The scale the printed unit / axis / label names; a model scale is kept only when the page prints it.

    The unit wins: a "Rs in Crs" unit is crore even when the reply says scale 1, and a "thousand units" unit is
    1000.  The axis/label is never used because a table's money header also rules its percent and per-kg rows.  No
    printed scale word in the unit means the reply's scale if the page prints it, else 1, never a guessed one."""
    factor = _scale_factor(row.get("unit", ""))
    if factor:
        return float(factor), []
    if infer_unit_family(row.get("unit", "")) in ("percent", "ratio", "time"):
        return 1.0, []               # a percentage / multiple / duration is never crore or thousand
    try:
        scale = float(raw_scale)
    except (TypeError, ValueError):
        scale = 1.0
    if scale == 1.0 or scale <= 0:
        return 1.0, []
    hay = " ".join([row.get("unit", ""), row.get("printed_axis", ""), row.get("printed_label", ""), page_text])
    for pattern, value in SCALE_WORDS:
        if abs(value - scale) <= scale * 1e-6 and re.search(pattern, hay, re.I):
            return scale, []
    return 1.0, [f"scale {raw_scale} is not printed on the page; stored as 1"]


def bbox(words: list[tuple[float, float, float, float, str]]) -> str:
    x0 = min(w[0] for w in words)
    y0 = min(w[1] for w in words)
    x1 = max(w[2] for w in words)
    y1 = max(w[3] for w in words)
    return f"{x0:.1f},{y0:.1f},{x1:.1f},{y1:.1f}"


def region_for(words: list[tuple[float, float, float, float, str]], value_text: str) -> str:
    """The text-layer box of the printed value when the words carry it, else empty (never the model's guess)."""
    target = norm_space(value_text)
    if not words or not target:
        return ""
    direct = [w for w in words if norm_space(w[4]) == target]
    if len(direct) == 1:
        return bbox(direct)
    if len(direct) > 1:          # the same number is printed more than once: without the label no box is the right one
        return ""
    for start in range(len(words)):
        for length in (2, 3, 4):
            seq = words[start:start + length]
            if len(seq) < length:
                break
            if norm_space(" ".join(w[4] for w in seq)) == target or norm_space("".join(w[4] for w in seq)) == target:
                return bbox(seq)
    return ""


def phrase_bbox(words: Iterable[tuple[float, float, float, float, str]], phrase: str) -> tuple[float, float, float, float] | None:
    """The box of a printed phrase (its words in order), or None when the page's words do not carry it."""
    wanted = norm_space(phrase).split()
    if not wanted:
        return None
    word_list = list(words)
    for start in range(len(word_list)):
        seq = word_list[start:start + len(wanted)]
        if len(seq) == len(wanted) and [norm_space(w[4]) for w in seq] == wanted:
            return (min(w[0] for w in seq), min(w[1] for w in seq),
                    max(w[2] for w in seq), max(w[3] for w in seq))
    return None


def detect_legend(words: Iterable[tuple[float, float, float, float, str]],
                  names: Iterable[str]) -> set[str]:
    """Group names printed as a vertical legend list (colour key), not as a heading beside their values.

    T-230 stage B: on c08 p14 the three groups are a legend at the left; a value's group is known only from colour.
    Two or more group names left-aligned, stacked with small gaps and a short vertical span are a legend; any row
    using one of those names is ``legend_inferred`` even when the model says ``printed``.
    """
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for name in names:
        box = phrase_bbox(words, name)
        if box:
            boxes[name] = box
    if len(boxes) < 2:
        return set()
    ordered = sorted(boxes.items(), key=lambda item: item[1][1])
    lefts = [box[0] for _name, box in ordered]
    tops = [box[1] for _name, box in ordered]
    bottoms = [box[3] for _name, box in ordered]
    gaps = [tops[i + 1] - bottoms[i] for i in range(len(ordered) - 1)]
    if max(lefts) - min(lefts) > 40:
        return set()
    if any(gap > 45 or gap < -2 for gap in gaps):
        return set()
    if tops[-1] - tops[0] > 140:
        return set()
    return set(boxes)


# --------------------------------------------------------------------------- stage C script rules

DISBURSEMENT_RE = re.compile(r"disburs", re.I)
ADJUSTED_RE = re.compile(r"would have been|would be|but for|excluding one[- ]offs?|excluding exceptional|"
                         r"pro[- ]forma|hypothetical|normalis(?:ed|ing)|normaliz(?:ed|ing)|like[- ]for[- ]like|"
                         r"\badjusted\b", re.I)
SPINDLE_RE = re.compile(r"spindle", re.I)

MONEY_UNIT_RE = re.compile(
    r"(?:₹|Rs\.?|INR|USD|US\$|\$)\s*(?:in\s*)?(crore|crores|cr|crs|lakh|lakhs|lac|lacs|million|mn|billion|bn)\b",
    re.I)
IN_UNIT_RE = re.compile(
    r"\b(?:in|amount in|fig(?:ure)?s? in)\s+(?:₹|Rs\.?|INR|USD|US\$|\$)?\s*"
    r"(crore|crores|cr|crs|lakh|lakhs|lac|lacs|million|mn|billion|bn)\b", re.I)
CAPACITY_UNIT_RE = re.compile(r"\b(mtpa|mmtpa|mt|tonnes?|tons?|tpa|tpd|mw|gw|kw)\b", re.I)
COUNT_UNIT_RE = re.compile(r"\b(units?|nos|numbers?|cases?|pieces?|stations?|outlets?|spindles?|machines?|teus?|"
                           r"vehicles?|tractors?|customers?|subscribers?|litres?|liters?|ltrs?)\b", re.I)
UNIT_SCALE = {"crore": 1e7, "crores": 1e7, "cr": 1e7, "crs": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5,
              "lacs": 1e5, "million": 1e6, "mn": 1e6, "billion": 1e9, "bn": 1e9}
PERIOD_PATTERNS = (
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b", re.I),
    re.compile(r"\b(?:Q[1-4]|H[12]|9M|FY)\s?-?\d{2,4}[A-Z]?\b", re.I),
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s-]?\d{2,4}\b", re.I),
    re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"),
    re.compile(r"\b(?:19|20)\d{2}-\d{2}\b"),
)


def _money_unit(text: str, match: re.Match[str]) -> tuple[str, str, float]:
    scale_word = match.group(1).lower()
    token = match.group(0)
    currency = "Rs"
    if re.search(r"USD|US\$|\$", token, re.I):
        currency = "USD"
    elif "INR" in token.upper():
        currency = "INR"
    return f"{currency} {scale_word}", "money", UNIT_SCALE.get(scale_word, 1.0)


def infer_unit(texts: Iterable[str], measure_family: str = "") -> tuple[str, str, float] | None:
    """A printed unit for a row with no unit: money / capacity / count / percent, only when the page prints one."""
    wanted = (measure_family,) if measure_family else ("money", "capacity", "count", "percent")
    for text in texts:
        line = norm_space(text)
        if not line:
            continue
        if "percent" in wanted and re.search(r"%|percent\b|pct\b", line, re.I):
            return "%", "percent", 1.0
        if "money" in wanted or "money_per_unit" in wanted:
            match = MONEY_UNIT_RE.search(line) or IN_UNIT_RE.search(line)
            if match:
                return _money_unit(line, match)
        if "capacity" in wanted:
            match = CAPACITY_UNIT_RE.search(line)
            if match:
                return match.group(1), "capacity", 1.0
        if "count" in wanted:
            match = COUNT_UNIT_RE.search(line)
            if match:
                return match.group(1), "count", 1.0
    return None


def infer_period(texts: Iterable[str]) -> str:
    """A printed period for a row with no period: a fiscal label, month-year, date or year range from its headers."""
    for text in texts:
        line = norm_space(text)
        if not line:
            continue
        for pattern in PERIOD_PATTERNS:
            match = pattern.search(line)
            if match:
                return norm_space(match.group(0))
    return ""


def canonical_measure(measure: str, label: str, axis: str, series_title: str, unit: str,
                      page_text: str) -> str:
    """Stage C3: near-duplicate ids, disbursement vs loans stock, spindle counts under capex."""
    measure = MEASURE_ALIASES.get(norm_space(measure), norm_space(measure))
    scripted = script_measure(label)
    if scripted:
        measure = scripted
    context = " ".join([label, axis, series_title])
    if DISBURSEMENT_RE.search(context):
        if "%" in (unit or "") or "share" in context.lower():
            measure = "loans.disbursement_share"
        else:
            measure = "loans.disbursement_mix" if "mix" in context.lower() else "loans.disbursement"
    if measure_root(measure) == "capex" and not unit and SPINDLE_RE.search(page_text or ""):
        measure = "capacity.spindles"
    return measure


def normalize_name(name: str) -> str:
    low = norm_space(name).lower()
    low = re.sub(r"\b(?:limited|ltd|corporation|corp|company|co|private|pvt|&|and)\b", " ", low)
    return re.sub(r"[^a-z0-9 ]+", " ", low).strip()


def company_index(store_dbs: Iterable[str | Path]) -> dict[str, tuple[str, str]]:
    """normalized company name -> (symbol, full name), built from the stores' own ``company`` tables."""
    index: dict[str, tuple[str, str]] = {}
    for store_db in store_dbs:
        try:
            con = connect_ro(store_db, timeout_s=60)
            _cur = con.execute("SELECT symbol, name FROM company")
            rows: list[Any] = []
            if _cur is not None:
                rows = [(row[0], row[1]) for row in _cur if row is not None]
            con.close()
        except Exception:
            continue
        for symbol, name in rows:
            if not symbol or not name:
                continue
            full = norm_space(name)
            index.setdefault(normalize_name(full), (str(symbol), full))
            index.setdefault(normalize_name(str(symbol)), (str(symbol), full))
    return index


PARENT_RE = re.compile(r"(?:ultimate\s+)?holding\s+company\s+of\s+[^.]{0,120}?i\.?e\.?\s+"
                       r"([A-Z][A-Za-z0-9&.'\- ]{2,60}?(?:Limited|Ltd))", re.I)
PRESENTATION_RE = re.compile(r"investor presentation|investor deck|corporate presentation|corporate deck|"
                             r"investor update|analyst presentation", re.I)
TITLE_STOP = {"institutional", "the", "copy", "please", "we", "this", "enclosed", "pursuant", "kindly",
              "subject", "sub", "sub.", "ref", "schedule", "intimation", "announcement", "company", "corporate",
              "investor", "update", "annual", "quarterly", "financial", "earnings", "results", "of", "for",
              "and", "a", "an", "our", "herewith", "attached", "latest", "presentation", "deck", "enclosing",
              "find", "is", "board", "meeting", "outcome", "under", "regulation", "sebi", "lodr", "listing",
              "obligations", "disclosure", "requirements", "regulations", "general", "information", "dated",
              "as", "per", "investors", "analysts", "call", "transcript", "press", "release", "bse", "nse",
              "limited", "ltd", "regd", "registered", "office", "exchange", "plaza", "notice", "proceedings"}
PERIOD_CANDIDATE = re.compile(r"^(?:Q[1-4]|H[12]|FY|9M|Q\d|H\d|FY\d|revised$|\d)", re.I)


def cover_title(cover: str) -> str:
    """A company name on the deck's cover: the line '<Company> Investor Presentation ...' at line start."""
    for line in (ln.strip() for ln in cover.splitlines()):
        match = PRESENTATION_RE.search(line)
        if not match:
            continue
        prefix = line[:match.start()].strip(" -:|,")
        words = re.findall(r"[A-Za-z0-9&.\-]+", prefix)
        if not words or len(words) > 5:
            continue
        if not all(w[0].isupper() for w in words if w[0].isalpha()):
            continue
        if any(w.lower().strip(".") in TITLE_STOP for w in words):
            continue
        if not any(len(w) > 2 for w in words):
            continue
        candidate = " ".join(words)
        if PERIOD_CANDIDATE.search(candidate):
            continue
        return candidate
    return ""


def doc_owner(store_db: str | Path, doc_key: str, index: dict[str, tuple[str, str]],
              store_symbol: str) -> str:
    """The listed company whose deck this is, when its cover names one other than the store's company.

    T-230 stage C1: a subsidiary files the parent's deck under its own store (NAVKARCORP holds JSW Infrastructure's
    port deck). Three printed sources, high confidence first: the filing letter's "Ultimate Holding Company of X i.e.
    Y", the deck cover line "<Company> Investor Presentation", and a company name known from the stores' company
    tables. When only the store's own company is named the document stays company."""
    con = connect_ro(store_db, timeout_s=60)
    try:
        _cur = con.execute("SELECT title FROM doc WHERE doc_key=?", (doc_key,))
        row = _cur.fetchone() if _cur is not None else None
        title = str(row[0] or "") if row else ""
        _cur = con.execute("SELECT text FROM doc_page WHERE doc_key=? AND page<=3 ORDER BY page", (doc_key,))
        pages: list[str] = []
        if _cur is not None:
            pages = [str(row[0] or "") for row in _cur if row is not None]
    finally:
        con.close()
    raw_cover = "\n".join([title] + pages)
    parent_match = PARENT_RE.search(raw_cover)
    if parent_match:
        return norm_space(parent_match.group(1))
    cover = normalize_name(raw_cover)
    own_names = {normalize_name(store_symbol)}
    own_names |= {name for name, (symbol, _full) in index.items()
                  if symbol.upper() == str(store_symbol).upper()}
    if any(name and re.search(r"\b" + re.escape(name) + r"\b", cover) for name in own_names):
        return ""
    for name, (symbol, _full) in sorted(index.items(), key=lambda item: -len(item[0])):
        if len(name) < 4 or symbol.upper() == str(store_symbol).upper():
            continue
        if re.search(r"\b" + re.escape(name) + r"\b", cover):
            return _full
    return cover_title(raw_cover)


# --------------------------------------------------------------------------- stage D script rules

MONEY_SCALE_RE = re.compile(
    r"(?:₹|Rs\.?|INR|USD|US\$|\$)\s*(?:in\s*)?"
    r"(M|Mn|Mio|Million|MM|Cr|Crore|Crores|Crs|Lakh|Lakhs|Lac|Lacs|Bn|Billion|'000|Thousand)\b", re.I)
IN_SCALE_RE = re.compile(
    r"\b(?:in|amount in|fig(?:ure)?s? in)\s+(?:₹|Rs\.?|INR|USD|US\$|\$)?\s*"
    r"(M|Mn|Mio|Million|MM|Cr|Crore|Crores|Crs|Lakh|Lakhs|Lac|Lacs|Bn|Billion|'000|Thousand)\b", re.I)
D_SCALE = {"m": 1e6, "mn": 1e6, "mio": 1e6, "million": 1e6, "mm": 1e6, "cr": 1e7, "crore": 1e7,
           "crores": 1e7, "crs": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "bn": 1e9,
           "billion": 1e9, "'000": 1e3, "thousand": 1e3}
STANDALONE_RE = re.compile(r"\bstandalone\b|\bstand-alone\b|\bstand alone\b", re.I)
CONSOLIDATED_RE = re.compile(r"\bconsolidated\b|\bconsole\b|\bcons\b", re.I)
SUBSIDIARY_RE = re.compile(r"([A-Z][A-Za-z0-9&.\-]{1,15})[’']s\s+standalone", re.I)
STOCK_MEASURE_RE = re.compile(
    r"^(?:capacity\.|aum\.)|^(?:gnpa|nnpa|loans|order\.book)$|"
    r"^count\.(?:.*(?:outlet|plant|branch|terminal|station))", re.I)
NOT_A_MEASURE_RE = re.compile(r"years? of (?:professional )?experience|professional experience|"
                              r"total experience|^age$|\bDIN\b|qualification", re.I)
BRIDGE_TEXT_RE = re.compile(r"\breported ebitda\b|\bebitda bridge\b|\bmargin bridge\b|\bbridge\b|\bwalk\b", re.I)
DELTA_OF = {"ebitda": "ebitda.delta", "ebitda_margin": "ebitda_margin.delta",
            "revenue.value": "revenue.delta", "revenue_from_operations": "revenue.delta", "pat": "pat.delta"}
TICK_LINE_RE = re.compile(r"^(?:\s*[-\d.,()%]+\s*)+$")
CAPACITY_NEGATIVE_RE = re.compile(
    r"can be (?:further )?enhanced|further enhanced|being set up|is establishing|establishing|planned|proposed|"
    r"under construction|under progress|under-progress|under execution|in progress|approved|pipeline|potential|"
    r"will be|to be set up|to be setup|coming up|announced|"
    r"\bEPC\b|track record|projects? completed|executed for|commissioned for|built for|qualification|moat", re.I)
CAPACITY_POSITIVE_RE = re.compile(
    r"\binstalled\b|\bexisting\b|\bcurrent\b|\boperating\b|in operation|\bcommissioned\b|\bcreated\b", re.I)
MT_UNITS = {"MT", "MT.", "MTON", "METRIC TON", "METRIC TONS"}
MT_MILLION_RE = re.compile(r"million (?:metric )?tonnes?|million tons?|\bMMT\b|\bMTPA\b", re.I)
MT_TONNE_RE = re.compile(r"(?<!million )(?<!million metric )\btonnes?\b|\btons?\b|metric tonnes?", re.I)
CAGR_RE = re.compile(r"\bCAGR\b", re.I)
FY_LABEL_RE = re.compile(r"\bFY\s?-?(\d{2,4})\b", re.I)
GROWTH_YOY_RE = re.compile(r"growth_yoy$", re.I)
FILING_LETTER_RE = re.compile(r"\bBSE Limited\b|\bDear Sir\b|\bSub\s*:|\bRegulation 30\b|^\s*To,", re.I | re.M)


def money_scale(texts: Iterable[str]) -> float | None:
    """A scale named in a money unit/header: 'in M', 'Mn', 'Mio', 'Million' -> 1e6, 'Cr' -> 1e7, etc."""
    for text in texts:
        line = norm_space(text)
        match = MONEY_SCALE_RE.search(line) or IN_SCALE_RE.search(line)
        if match:
            return D_SCALE.get(match.group(1).lower())
    return None


def page_head(page_text: str, lines: int = 3) -> str:
    return "\n".join([line for line in str(page_text or "").splitlines() if line.strip()][:lines])


def page_tail(page_text: str, lines: int = 3) -> str:
    return "\n".join([line for line in str(page_text or "").splitlines() if line.strip()][-lines:])


def detect_basis(axis: str, series: str, head: str,
                 words: Iterable[tuple[float, float, float, float, str]] = (),
                 region: str = "", group_path: str = "", page_text: str = "") -> str:
    """Standalone / consolidated from the column header, series title, page title or a heading/footer line."""
    text = " ".join([group_path, axis, series, head, page_head(page_text, 3), page_tail(page_text, 3)])
    stand = bool(STANDALONE_RE.search(text))
    cons = bool(CONSOLIDATED_RE.search(text))
    if stand and not cons:
        return "standalone"
    if cons and not stand:
        return "consolidated"
    headers = [(norm_space(w[4]).lower(), (w[0] + w[2]) / 2) for w in words
               if norm_space(w[4]).lower() in ("standalone", "stand-alone", "consolidated")]
    if len(headers) >= 2 and region:
        parts = [float(p) for p in region.split(",") if p.strip()]
        if len(parts) == 4:
            centre = (parts[0] + parts[2]) / 2
            headers.sort(key=lambda item: item[1])
            boundary = headers[0][1] + (headers[-1][1] - headers[0][1]) / 2
            return "standalone" if centre < boundary else "consolidated"
    return ""


def detect_subsidiary(texts: Iterable[str], companies: dict[str, tuple[str, str]], store_symbol: str) -> bool:
    """A page/series that names a subsidiary: "<ABBR>'s Standalone P&L" or another known company name."""
    text = " ".join(str(t or "") for t in texts)
    match = SUBSIDIARY_RE.search(text)
    if match:
        abbr = match.group(1).strip().upper()
        if abbr and abbr != str(store_symbol).upper():
            return True
    normalized = norm_space(text).lower()
    for name, (symbol, _full) in companies.items():
        if len(name) < 4 or symbol.upper() == str(store_symbol).upper():
            continue
        if re.search(r"\b" + re.escape(name) + r"\b", normalized):
            return True
    return False


def is_stock_measure(measure: str) -> bool:
    """A true stock a deck's as-of date can belong to (E1): not a rate, an addition or a plan."""
    return re.search(r"^capacity\.(?:total|add)$|^count\.(?:.*(?:outlets?|branches?|plants?))$|"
                     r"^(?:gnpa|nnpa|loans|order\.book)$|^aum\.", measure or "", re.I) is not None


def capacity_deck_period_ok(row: dict[str, Any], page_text: str) -> bool:
    """E1: capacity takes the deck period only for an operating/installed stock, never a plan, a rate or EPC work."""
    measure = row.get("measure") or ""
    if not measure.startswith("capacity."):
        return True
    if measure in ("capacity.utilisation", "capacity.growth_multiple"):
        return False
    if row.get("stage") in ("potential", "approved", "under_construction", "under_review"):
        return False
    text = " ".join([row.get("printed_label") or "", row.get("series_title") or "", row.get("group_path") or "",
                     page_head(page_text, 4), page_tail(page_text, 3)])
    if CAPACITY_NEGATIVE_RE.search(text):
        return False
    if row.get("stage") == "operating":
        return True
    if measure == "capacity.add" and not re.search(r"commissioned|installed|created", text, re.I):
        return False
    return CAPACITY_POSITIVE_RE.search(text) is not None


def cagr_measure(measure: str, label: str, axis: str, series: str,
                 page_text: str) -> tuple[str, str] | None:
    """E4: a CAGR / two-point span on a growth row becomes *_growth_cagr with period_kind span, never *_yoy."""
    if not GROWTH_YOY_RE.search(measure or ""):
        return None
    text = " ".join([label, axis, series])
    cue = CAGR_RE.search(text) is not None or CAGR_RE.search(page_head(page_text, 6)) is not None
    years = sorted({int(m.group(1)) for m in FY_LABEL_RE.finditer(page_text or "")})
    two_point = len(years) == 2 and (years[1] - years[0]) >= 2
    if not cue and not (two_point and not norm_space(label)):
        return None
    new_measure = GROWTH_YOY_RE.sub("growth_cagr", measure)
    span = f"FY{years[0]}-FY{years[1]}" if two_point else ""
    return new_measure, span


def resolve_mt_scale(page_text: str) -> float | None:
    """E5: a bare 'MT' is tonnes or million tonnes; only a printed tonne/million-tonne word resolves it."""
    if MT_MILLION_RE.search(page_text or ""):
        return 1e6
    if MT_TONNE_RE.search(page_text or ""):
        return 1.0
    return None


def _period_token(text: str) -> str:
    match = re.search(r"(?:as\s+on|as\s+at|as\s+of)\s+([A-Za-z0-9 ,.'/-]{4,40})", text or "", re.I)
    if match:
        period = infer_period([match.group(1)])
        if period:
            return period
    return infer_period([text])


def deck_period(store_db: str | Path, doc_key: str, page_text: str) -> str:
    """E2: the period printed on the presentation's own cover/title page or page header, never the filing letter."""
    candidates: list[str] = []
    try:
        con = connect_ro(store_db, timeout_s=60)
        _cur = con.execute("SELECT title FROM doc WHERE doc_key=?", (doc_key,))
        row = _cur.fetchone() if _cur is not None else None
        title = str(row[0] or "") if row else ""
        _cur = con.execute("SELECT page, text FROM doc_page WHERE doc_key=? AND page BETWEEN 2 AND 6 ORDER BY page",
                           (doc_key,))
        pages: list[Any] = []
        if _cur is not None:
            pages = [(r[0], r[1]) for r in _cur if r is not None]
        con.close()
        for _page, text in pages:
            text = str(text or "")
            if FILING_LETTER_RE.search(text):
                continue
            candidates.append(text)
    except Exception:
        title = ""
    head = page_head(page_text, 4)
    if head and not FILING_LETTER_RE.search(head):
        candidates.append(head)
    if title and not FILING_LETTER_RE.search(title):
        candidates.append(title)
    for text in candidates:
        period = _period_token(text)
        if period:
            return period
    return ""


def apply_series_kind(rows: list[dict[str, Any]], page_text: str) -> None:
    """D3: a bridge/waterfall's middle bars are steps of the walked measure, never a segment's level."""
    by_series: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_series.setdefault(row.get("series_id") or "s1", []).append(row)
    for series, group in by_series.items():
        for row in group:
            row["series_kind"] = row.get("series_kind") or "level"
        if len(group) < 3:
            continue
        first = group[0]
        bridge = BRIDGE_TEXT_RE.search(page_text or "") is not None or \
            re.search(r"\breported\b", first.get("printed_label") or "", re.I) is not None
        if not bridge:
            continue
        base = first.get("measure") or ""
        delta = DELTA_OF.get(base) or (base + ".delta" if base else "")
        for row in group:
            row["series_kind"] = "bridge"
        for row in group[1:]:
            if delta and delta in measure_index():
                row["measure"] = delta
            row["status"] = "unverified"
            row["status_reason"] = (row["status_reason"] + "; " if row["status_reason"] else "") + \
                f"bridge step of {base or 'the walked measure'}, not a level"


def apply_basis_conflicts(rows: list[dict[str, Any]]) -> int:
    """D2: two verified rows with the same measure/label/period/series but different values need distinct bases."""
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("value") is None:
            continue
        key = (row.get("series_id"), row.get("measure"), row.get("printed_label"), row.get("period"),
               row.get("unit"), float(row.get("scale") or 1))
        groups.setdefault(key, []).append(row)
    conflicts = 0
    for group in groups.values():
        values = {round(float(r["value"]), 6) for r in group}
        if len(values) < 2:
            continue
        by_value: dict[float, list[dict[str, Any]]] = {}
        for row in group:
            by_value.setdefault(round(float(row["value"]), 6), []).append(row)
        bases = {value: {r.get("basis") for r in rows} for value, rows in by_value.items()}
        clean = all(len(b) == 1 and "" not in b for b in bases.values()) and \
            len({next(iter(b)) for b in bases.values()}) == len(bases)
        if clean:
            continue
        conflicts += 1
        for row in group:
            row["status"] = "unverified"
            row["status_reason"] = (row["status_reason"] + "; " if row["status_reason"] else "") + \
                "basis_conflict: same measure/label/period with different values and no distinct basis"
    return conflicts


def is_axis_tick(text: str, row: dict[str, Any]) -> bool:
    """D5: a value that only appears on an axis-tick line (several bare numbers) has no data label."""
    label = norm_space(row.get("printed_label"))
    if label and label != norm_space(row.get("series_title")):
        return False
    needle = norm_space(row.get("value_text"))
    if not needle:
        return False
    for line in str(text or "").splitlines():
        line = norm_space(line)
        if needle not in line:
            continue
        raw_numbers = re.findall(r"(?<![\w.])\(?\d[\d,]*\.?\d*\)?%?", line)
        numbers: list[float] = []
        for token in raw_numbers:
            try:
                numbers.append(float(token.replace(",", "").strip("()%").rstrip(".")))
            except ValueError:
                continue
        if len(numbers) >= 3 and all(n % 1000 == 0 for n in numbers):
            return True
    return False


def is_not_a_measure(row: dict[str, Any]) -> bool:
    text = " ".join([row.get("printed_label") or "", row.get("measure") or "", row.get("printed_axis") or ""])
    return NOT_A_MEASURE_RE.search(text) is not None


def evaluate_status(row: dict[str, Any], text: str, measures: dict[str, dict[str, str]],
                    raw_text: str = "") -> tuple[str, list[str]]:
    """Re-apply every script check to one row (used by the reader and by --recheck)."""
    reasons = list(row.pop("_scale_notes", []))
    if is_not_a_measure(row):
        return "quarantined", reasons + ["not_a_measure: director/tenure row, not a business quantity"]
    if row.get("adjusted"):
        reasons.append("adjusted/hypothetical figure, not the reported measure")
    if not text:
        return "unverified", reasons + ["no text layer on this page; value not checkable"]
    if not text_has(text, row.get("value_text", "")):
        return "quarantined", reasons + ["value_text is not in the page text layer"]
    status = "unverified" if reasons else "verified"
    for field in ("printed_label", "printed_axis", "group_path"):
        if not row.get(field):
            continue
        parts = row[field].split(" > ") if field == "group_path" else [row[field]]
        missing = [part for part in parts if part and norm_space(part) not in text]
        if missing:
            status = "unverified"
            reasons.append(f"{field} is not in the page text layer: {' > '.join(missing)!r}")
    if not (row.get("printed_label") or row.get("printed_axis") or row.get("series_title")):
        status = "unverified"
        reasons.append("no printed label, axis or series title")
    if row.get("group_path"):
        if row.get("group_source") == "legend_inferred":
            status = "unverified"
            reasons.append("group inferred from colour/legend, not a printed heading")
        elif row.get("group_source") != "printed":
            status = "unverified"
            reasons.append("group source not stated (printed or legend_inferred)")
    measure = measures.get(row.get("measure", ""))
    if measure is None:
        status = "unverified"
        reasons.append(f"measure is not in the dictionary: {row.get('measure')!r}")
    elif row.get("unit_family") and not family_ok(measure["unit_family"], row["unit_family"]):
        status = "unverified"
        reasons.append(f"unit family {row['unit_family']!r} does not match measure {row['measure']!r} "
                       f"({measure['unit_family']!r})")
    if measure is not None and measure["unit_family"] in ("money", "money_per_unit"):
        hint = money_scale([row.get("unit", ""), row.get("printed_axis", ""), row.get("series_title", "")])
        if hint is not None and float(row.get("scale") or 1) == 1:
            status = "unverified"
            reasons.append("scale_unread: the unit names a scale but the stored scale is 1")
    if (row.get("unit") or "").strip().upper() in MT_UNITS and float(row.get("scale") or 1) == 1 \
            and resolve_mt_scale(raw_text or text) is None:
        status = "unverified"
        reasons.append("scale_ambiguous: 'MT' could be tonnes or million tonnes and the page does not resolve it")
    if is_axis_tick(raw_text or text, row):
        status = "unverified"
        reasons.append("axis_tick: the value only appears on an axis-tick line, not as a data label")
    if not row.get("entity_scope"):
        status = "unverified"
        reasons.append("entity_scope not stated: the figure cannot be attributed")
    required_unit = measure is not None and measure["unit_family"] in (
        "money", "money_per_unit", "capacity", "count", "length", "area", "time")
    if required_unit and not row.get("unit"):
        status = "unverified"
        reasons.append("no_unit: no unit printed for this money/quantity row")
    if not row.get("period"):
        status = "unverified"
        reasons.append("no_period: no period printed for this row")
    return status, reasons


def build_observations(*, symbol: str, doc_key: str, page: int, known_at: str, page_text: str,
                       words: Iterable[tuple[float, float, float, float, str]] = (),
                       reply_rows: Iterable[dict[str, Any]] = (),
                       measures: dict[str, dict[str, str]] | None = None,
                       vocab: dict[tuple[str, str], str] | None = None,
                       doc_owner_symbol: str = "",
                       companies: dict[str, tuple[str, str]] | None = None,
                       deck_asof: str = "") -> list[dict[str, Any]]:
    """Model reply objects -> checked observation rows (status and status_reason set here)."""
    measures = measures if measures is not None else measure_index()
    vocab = vocab if vocab is not None else vocab_index()
    word_list = list(words)
    reply_rows = list(reply_rows)
    text = norm_space(page_text)
    page_groups = {part for raw in reply_rows if isinstance(raw, dict)
                   for part in norm_space(raw.get("group_path")).split(" > ") if part}
    legend_groups = detect_legend(word_list, page_groups)
    out: list[dict[str, Any]] = []
    for raw in reply_rows:
        if not isinstance(raw, dict):
            continue
        value_text = norm_space(raw.get("value_text"))
        if not value_text or not re.search(r"\d", value_text):
            continue
        label = norm_space(raw.get("printed_label"))
        if FOOTNOTE_LABEL.match(label) and label.endswith("."):
            continue                 # a footnote echoing the value ("* Further approval of 4 MTPA is under process.")
        if label.endswith(".") and len(label.split()) >= 4:
            continue                 # a printed sentence, not a label
        value = parse_number(value_text)
        if value is None:            # the model's own "value" is never trusted, and value_text is not a number
            continue
        row: dict[str, Any] = {key: norm_space(raw.get(key)) for key in ROW_TEXT_KEYS}
        if JUNK_MEASURE.match(row["measure"]):
            continue                 # page number, phone, address, PIN, CIN/DIN, signature date: not a quantity
        row.update({
            "symbol": symbol, "doc_key": doc_key, "page": int(page), "known_at": known_at,
            "value_text": value_text, "value": value,
            "period_kind": period_kind_for(raw.get("period_kind", ""), row["period"]),
            "period_source": "",
            "basis": "",
            "series_kind": "level",
            "series_id": row["series_id"] or "s1",
            "region": region_for(word_list, value_text),
            "group_source": canonical_group_source(raw.get("group_source", "")),
            "group_check": "",
            "adjusted": 0,
            "reader": READER, "read_at": datetime.now().isoformat(timespec="seconds"),
            "_is_total": raw.get("is_total") is True or str(raw.get("is_total", "")).lower() in ("true", "yes", "1"),
        })
        for dim in DIMS:
            row[dim] = canonical_dim(vocab, dim, row.get(dim, ""))
        row["stage"] = canonical_stage(vocab, row.get("stage", "")) or stage_from_group(vocab, row["group_path"])
        if not row["group_path"]:
            row["group_source"] = ""
        elif any(part in legend_groups for part in row["group_path"].split(" > ")):
            row["group_source"] = "legend_inferred"
        row["entity_scope"] = canonical_scope(row["entity_scope"])
        head = page_head(text)
        if detect_subsidiary([row["printed_axis"], row["series_title"], head], companies or {}, symbol):
            if row["entity_scope"] in ("company", "parent", ""):
                row["entity_scope"] = "subsidiary"
        row["basis"] = detect_basis(row["printed_axis"], row["series_title"], head, word_list, row["region"],
                                    row["group_path"], page_text)
        row["measure"] = canonical_measure(row["measure"], row["printed_label"], row["printed_axis"],
                                           row["series_title"], row["unit"], text)
        cagr = cagr_measure(row["measure"], row["printed_label"], row["printed_axis"], row["series_title"], page_text)
        if cagr:
            row["measure"], span = cagr
            if span:
                row["period"] = span
                row["period_source"] = ""
                row["period_kind"] = "span"
        measure = measures.get(row["measure"])
        if not row["unit"]:
            inferred = infer_unit([row["printed_axis"], row["series_title"], row["printed_label"]],
                                  measure["unit_family"] if measure else "")
            if inferred:
                row["unit"], row["unit_family"], row["scale"] = inferred
        row["scale"], scale_notes = printed_scale(raw.get("scale", 1), row, text)
        row["unit_family"] = infer_unit_family(row["unit"]) or row.get("unit_family", "")
        if row["unit_family"] in ("money", "money_per_unit") and float(row["scale"] or 1) == 1:
            factor = money_scale([row["unit"], row["printed_axis"], row["series_title"], head])
            if factor:
                row["scale"] = factor
        if (row["unit"] or "").strip().upper() in MT_UNITS and float(row["scale"] or 1) == 1:
            resolved = resolve_mt_scale(page_text)
            if resolved:
                row["scale"] = resolved
        if not row["period"]:
            row["period"] = infer_period([row["printed_axis"], row["series_title"], row["group_path"],
                                          row["printed_label"]])
            row["period_kind"] = period_kind_for(raw.get("period_kind", ""), row["period"])
        if not row["period"] and deck_asof and is_stock_measure(row["measure"]) \
                and capacity_deck_period_ok(row, page_text):
            row["period"] = deck_asof
            row["period_source"] = "deck_period"
            row["period_kind"] = period_kind_for("", deck_asof)
        row["adjusted"] = 1 if ADJUSTED_RE.search(" ".join(
            [row["printed_label"], row["printed_axis"], row["series_title"]])) else 0
        if doc_owner_symbol and row["entity_scope"] in ("company", "subsidiary", ""):
            row["entity_scope"] = "parent"
        row["_scale_notes"] = scale_notes
        row["status"], reasons = evaluate_status(row, text, measures, page_text)
        row["status_reason"] = "; ".join(reasons)
        out.append(row)
    apply_parts_sum(out)
    apply_path_sum(out)
    apply_series_kind(out, text)
    apply_basis_conflicts(out)
    return out


def measure_root(measure_id: str) -> str:
    return norm_space(measure_id).split(".", 1)[0]


def apply_parts_sum(rows: list[dict[str, Any]]) -> None:
    """The rows a model marks as a printed total must equal the parts it printed in the same series and group.

    Membership is the reply's structure (series_id, group_path, is_total); the arithmetic is the script's.  Only a
    one-total group of 2-10 labelled rows whose measure shares the total's root (capacity.total with capacity.add,
    revenue.value with revenue.mix) is checked: a financial-highlights chart with revenue, EBITDA and PAT in one
    series never fires.
    """
    groups: dict[tuple[str, str, str, str, float], list[dict[str, Any]]] = {}
    for row in rows:
        if row["status"] == "quarantined":
            continue
        key = (row["series_id"], row["group_path"], row["period"], row["unit"], float(row["scale"]))
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        totals = [r for r in group if r.get("_is_total")]
        if len(totals) != 1:
            continue
        total = totals[0]
        parts = [r for r in group if not r.get("_is_total")
                 and measure_root(r["measure"]) == measure_root(total["measure"])]
        if not 2 <= len(parts) <= 10:
            continue
        if any(r["value"] is None or not r["printed_label"] for r in parts + [total]):
            continue
        total_value = float(total["value"])
        part_sum = sum(float(r["value"]) for r in parts)
        tolerance = max(0.51, abs(total_value) * 0.005)
        if abs(part_sum - total_value) <= tolerance:
            for row in parts + totals:
                if "no_unit:" in row["status_reason"] or "no_period:" in row["status_reason"] or \
                        "adjusted/hypothetical" in row["status_reason"]:
                    continue         # a parts sum never overrides a hard gate
                row["status"] = "verified"
                row["status_reason"] = (row["status_reason"] + "; " if row["status_reason"] else "") + \
                    f"parts sum to the printed total {total['value_text']}"
                row["_part"] = row is not total
                if row is total:
                    row["_printed_total"] = True
        else:
            for row in parts + totals:
                row["status"] = "unverified"
                row["status_reason"] = (row["status_reason"] + "; " if row["status_reason"] else "") + \
                    f"parts sum to {part_sum:g} but the printed total is {total['value_text']}"


def apply_path_sum(rows: list[dict[str, Any]]) -> None:
    """A printed running path (177 -> 292 -> 400) must be reproduced by the stage-group rows (T-230 stage B).

    One group is one series/unit/scale/measure root. The path is the non-part rows with distinct periods, strictly
    increasing; the other rows are the components. Pass 1: every component sums to end - start. Pass 2 (a printed box
    total beside its parts, e.g. "85" over seven projects adding to 85.3): the row whose value equals the excess and
    the subset of rows summing to it are the double-counted pair; drop the subset and pass. Passing rows get
    ``group_check='path_sum'``; the status is never changed here (a legend-inferred group stays unverified).
    """
    groups: dict[tuple[str, str, float, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row["status"] == "quarantined" or row["value"] is None:
            continue
        key = (row["series_id"], row["unit"], float(row["scale"]), measure_root(row["measure"]))
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        path: dict[str, dict[str, Any]] = {}
        for row in group:
            if row["period"] and not row.get("_part"):
                path.setdefault(row["period"], row)
        path_rows = sorted(path.values(), key=lambda r: r["period"])
        if len(path_rows) < 2:
            continue
        values = [float(r["value"]) for r in path_rows]
        if any(b <= a for a, b in zip(values, values[1:])):
            continue
        delta = values[-1] - values[0]
        if delta <= 0:
            continue
        components = [r for r in group if all(r is not p for p in path_rows) and not r.get("_part")
                      and r["value"] is not None]
        if len(components) < 2:
            continue
        tolerance = max(0.51, abs(delta) * 0.005)
        provided_total = sum(float(r["value"]) for r in components)
        chosen: list[dict[str, Any]] | None = None
        if abs(provided_total - delta) <= tolerance:
            chosen = components
        else:
            excess = provided_total - delta
            rounding = 0.51
            box = [r for r in components if float(r["value"]) > 0
                   and abs(float(r["value"]) - excess) <= rounding]
            for candidate in box:
                subset = subset_for([r for r in components if r is not candidate],
                                    float(candidate["value"]), rounding)
                if not subset:
                    continue
                collapsed = [r for r in components if r is not candidate
                             and all(r is not s for s in subset)] + [candidate]
                if abs(sum(float(r["value"]) for r in collapsed) - delta) <= tolerance:
                    chosen = collapsed
                    break
        if chosen:
            for row in chosen + path_rows:
                row["group_check"] = "path_sum"


def subset_for(rows: list[dict[str, Any]], target: float, tolerance: float) -> list[dict[str, Any]] | None:
    """A subset of rows whose values sum to ``target`` within ``tolerance`` (bounded DP; None when too large)."""
    items = [(r, int(round(float(r["value"]) * 100))) for r in rows if float(r["value"]) > 0]
    target_c = int(round(target * 100))
    tol_c = int(round(tolerance * 100)) + 1
    if not items or target_c <= 0 or len(items) > 20 or target_c + tol_c > 5_000_000:
        return None
    reachable: dict[int, list[int]] = {0: []}
    for index, (_row, value) in enumerate(items):
        if value > target_c + tol_c:
            continue
        for current, picked in list(reachable.items()):
            new_sum = current + value
            if new_sum <= target_c + tol_c and new_sum not in reachable:
                reachable[new_sum] = picked + [index]
    best = max((s for s in reachable if abs(s - target_c) <= tol_c), default=None)
    if best is None:
        return None
    return [items[i][0] for i in reachable[best]]


def create_db(path: str | Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    columns = {row[1] for row in con.execute("PRAGMA table_info(observation)")}
    for name, ddl in MIGRATIONS:                 # an output DB written before stage B keeps its rows
        if name not in columns:
            con.execute(f"ALTER TABLE observation ADD COLUMN {name} {ddl}")
    con.executemany("INSERT OR IGNORE INTO measure_dict VALUES (?,?,?,?)", MEASURES)
    con.executemany("INSERT OR IGNORE INTO dim_vocab VALUES (?,?,?)", DIM_VOCAB)
    con.executemany("INSERT OR IGNORE INTO measure_alias VALUES (?,?)", sorted(MEASURE_ALIASES.items()))
    con.commit()
    return con


OBS_COLUMNS = ("symbol", "doc_key", "page", "region", "known_at", "measure", "printed_label", "printed_axis",
               "value", "value_text", "unit", "unit_family", "scale", "adjusted", "period", "period_kind",
               "period_source", "basis", "series_kind", "segment", "product", "geography", "plant", "customer",
               "group_path", "group_source", "group_check", "stage", "series_id", "series_title", "entity_scope",
               "status", "status_reason", "reader", "read_at")


def write_rows(con: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    con.execute("DELETE FROM observation WHERE doc_key=? AND page=?", (rows[0]["doc_key"], int(rows[0]["page"])))
    con.executemany(f"INSERT INTO observation ({', '.join(OBS_COLUMNS)}) "
                    f"VALUES ({', '.join('?' for _ in OBS_COLUMNS)})",
                    [[row.get(col) for col in OBS_COLUMNS] for row in rows])
    con.commit()
    return len(rows)


# --------------------------------------------------------------------------- store reading

PROMPT = """Read one printed page of an investor presentation or annual report (image + its text layer) and return
every printed quantity with its meaning. Output ONE JSON object per line (JSON Lines): no array, no markdown, no
prose. Every object has exactly these keys:
{{"series_id": "s1", "series_title": "chart or panel title as printed",
 "measure": "one id from the dictionary below", "printed_label": "words printed against the value, verbatim",
 "printed_axis": "axis / column header / unit line the value sits under, verbatim",
 "value_text": "the number exactly as printed", "unit": "unit as printed", "scale": 1,
 "period": "the year/period the value is for, as printed", "period_kind": "actual|estimate|target",
 "segment": "", "product": "", "geography": "", "plant": "", "customer": "",
 "group_path": "heading(s) that group the value, joined with ' > '", "group_source": "printed|legend_inferred",
 "stage": "",
 "entity_scope": "company|subsidiary|industry|country|customer|peer", "is_total": false}}

Rules:
- One object per quantity actually printed (bar, pie slice, table cell, map label, call-out). Never compute, sum,
  average, convert or share out a number: value_text must contain a digit string that is printed on the page.
  Skip page numbers, footnote markers, phone numbers, addresses, postal codes, CIN/DIN, registration numbers,
  signature dates and other letterhead or contact data.
- value_text: copy the number exactly as printed, with its sign, % or prefix (e.g. "177", "4.5", "36.0", "~2.3x",
  "3,50,000"). Never move digits between values.
- printed_label: the words printed against the value (row label, bar label, slice label, plant/port name), verbatim;
  empty if the chart prints none.
- printed_axis: ONE printed line copied exactly -- the column header, axis label or unit line closest to the value
  (e.g. "Particulars (INR Mn)", "FY28E", "Sale units (in Thousands)"). Never join two printed lines with "|", ">",
  "/" or a newline; a period or year on its own line goes in period, not here. Empty if none.
- unit: the unit as printed (e.g. "mtpa", "%", "Rs crore", "lakh units"); empty if none. scale: the number the
  unit multiplies by (1, 1000, 100000, 10000000) only when the page prints the scale word ("in Thousands",
  "lakh", "crore", "Mn"); otherwise 1.
- period: as printed (FY25, FY28E, FY20, Q2FY26, 2024); empty if none. Only a period printed against this value (its
  axis tick, column header, caption or year label) is its period; a year printed elsewhere on the page is not.
  period_kind: "actual" for a printed past or current period, "estimate" for an E suffix / forecast / projected,
  "target" for a management target or guidance; empty if no period.
- measure: pick the closest id from the dictionary; if none fits, write a snake_case id naming what the printed
  label says. Never guess a different number to fit a measure.
- group_path: only the grouping heading(s) printed directly above or around the value, joined with " > " (e.g.
  "Projects Under Review"); never the slide title or the chart title (series_title carries those); empty when no
  group is printed.
- group_source: "printed" when the grouping heading is printed as text directly above or beside the value;
  "legend_inferred" when you had to use a bar/box colour, a colour legend or another visual key to know which group
  the value belongs to -- even when the group names are printed elsewhere on the slide (a legend at the bottom);
  empty when there is no group.
- stage: operating, under_construction, approved, under_review or potential, only from printed stage words
  ("operating", "under construction", "approved", "under review", "pipeline", "potential"). A printed group heading
  can state it ("Projects Approved" -> approved, "Under Review" -> under_review, "Pipeline of Potential Projects" ->
  potential); else empty.
- dims: segment, product, geography, plant, customer copied from the page (place names, facility names, business
  segment, product); empty when not printed. Never infer a dimension from outside knowledge.
- series_id: which chart/table/panel on the page, s1, s2 ... left to right and top to bottom; one id for all values
  of the same chart. series_title: that chart/panel title as printed.
- entity_scope: "industry" for an industry total (a chart titled industry, source SIAM / TMA / CMIE), "country"
  for a country figure, "company" for this company's own figure, "subsidiary" for a named group company, "customer"
  for a customer figure, "peer" for a competitor. Industry and country figures must never be labelled company.
- is_total: true only when this printed value is the total of the other printed values in the same series and group
  (a "Total" bar, row or slice label); its measure is the parts' measure. Otherwise false.
- Do not invent a value, a group, a stage or a unit the page does not print. A wrong row is worse than a missing row.

Measure dictionary (id -- name -- unit family -- driver node):
{dictionary}

Example of one line:
{{"series_id": "s1", "series_title": "Indian Tractor Industry", "measure": "volume.sales",
 "printed_label": "Indian Tractor Industry", "printed_axis": "FY20", "value_text": "705",
 "unit": "thousand units", "scale": 1000, "period": "FY20", "period_kind": "actual", "segment": "",
 "product": "tractor", "geography": "India", "plant": "", "customer": "", "group_path": "",
 "group_source": "", "stage": "", "entity_scope": "industry", "is_total": false}}
Example of a value in a printed group:
{{"series_id": "s2", "series_title": "2030 Road Map for Growth", "measure": "capacity.add",
 "printed_label": "Jatadhar Port, Odisha", "printed_axis": "All fig. in mtpa", "value_text": "30",
 "unit": "mtpa", "scale": 1, "period": "", "period_kind": "", "segment": "", "product": "",
 "geography": "Odisha", "plant": "Jatadhar Port", "customer": "", "group_path": "Projects Approved",
 "group_source": "printed", "stage": "approved", "entity_scope": "company", "is_total": false}}

Page text layer (verbatim, may be empty):
<<<
{text}
>>>"""


def dictionary_text(measures: dict[str, dict[str, str]]) -> str:
    return "\n".join(f"{mid} -- {m['name']} -- {m['unit_family']} -- {m['driver_node']}"
                     for mid, m in measures.items())


def page_meta(store_db: str | Path, doc_key: str) -> dict[str, str]:
    con = connect_ro(store_db, timeout_s=60)
    try:
        _cur = con.execute("SELECT symbol, doc_type, known_at FROM doc WHERE doc_key=?", (doc_key,))
        row = _cur.fetchone() if _cur is not None else None
    finally:
        con.close()
    if not row:
        return {}
    return {"symbol": row[0] or "", "doc_type": rp._doc_type_norm(row[1] or ""), "known_at": row[2] or ""}


def page_text_of(store_db: str | Path, doc_key: str, page: int) -> str:
    con = connect_ro(store_db, timeout_s=60)
    try:
        _cur = con.execute("SELECT text FROM doc_page WHERE doc_key=? AND page=?", (doc_key, page))
        row = _cur.fetchone() if _cur is not None else None
    finally:
        con.close()
    return str(row[0] or "") if row else ""


# --------------------------------------------------------------------------- reader call and 429 handling

RETRYABLE = re.compile(r"\b(?:429|500|502|503|504)\b")
MAX_RETRIES = 6
QUOTA_STOP_SECONDS = 300.0              # a Retry-After this long is the shared Go quota window, not a burst
_RETRY_EVENTS: list[dict[str, Any]] = []
_RETRY_LOCK = threading.Lock()
_QUOTA: dict[str, float] = {"seconds": 0.0}
_QUOTA_LOCK = threading.Lock()


def ist_now() -> str:
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat(timespec="seconds")


def retry_after_seconds(value: Any) -> float | None:
    """The Retry-After header in seconds (an integer or a delay-seconds string); None when absent/unparsable."""
    if value is None:
        return None
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def quota_seconds() -> float:
    with _QUOTA_LOCK:
        return float(_QUOTA["seconds"])


def set_quota(seconds: float) -> None:
    with _QUOTA_LOCK:
        if seconds > _QUOTA["seconds"]:
            _QUOTA["seconds"] = float(seconds)


def post_once(prompt: str, image_b64: str | None) -> dict[str, Any]:
    """One chat request to the configured reader, keeping the Retry-After header the shared client drops."""
    cfg = rp.MODELS[OBS_READER]
    key = os.environ.get(cfg.get("key_env", "OPENCODE_GO_API_KEY"), "")
    base = cfg.get("base", "https://opencode.ai/zen/go/v1")
    if image_b64:
        content: Any = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}},
                        {"type": "text", "text": prompt}]
    else:
        content = prompt
    body = {"model": cfg.get("id", OBS_READER), **cfg.get("body", {}),
            "messages": [{"role": "user", "content": content}]}
    t0 = time.time()
    try:
        response = requests.post(
            base.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "x-opencode-session": rp._session_id("observations", OBS_READER, "", 0),
                     "User-Agent": "reality-engine/1.0"},
            json=body, timeout=300)
    except Exception as exc:
        return {"output": "", "error": f"{type(exc).__name__}: {exc}", "retry_after": None,
                "seconds": time.time() - t0, "in_tok": 0, "out_tok": 0}
    if response.status_code != 200:
        return {"output": "", "error": f"HTTP {response.status_code}: {response.text[:300]}",
                "retry_after": retry_after_seconds(response.headers.get("Retry-After")),
                "seconds": time.time() - t0, "in_tok": 0, "out_tok": 0}
    payload = response.json()
    if not payload.get("choices"):
        return {"output": "", "error": f"no choices: {response.text[:300]}", "retry_after": None,
                "seconds": time.time() - t0, "in_tok": 0, "out_tok": 0}
    usage = payload.get("usage", {})
    return {"output": payload["choices"][0]["message"].get("content") or "", "error": None, "retry_after": None,
            "seconds": time.time() - t0, "in_tok": usage.get("prompt_tokens", 0),
            "out_tok": usage.get("completion_tokens", 0)}


def call_reader(prompt: str, image_b64: str | None, doc_key: str = "", page: int = 0) -> dict[str, Any]:
    """One reader call; retry short 429/5xx bursts, stop on the shared quota window (large Retry-After)."""
    stop = quota_seconds()
    if stop > 0:
        return {"output": "", "error": "quota window", "quota": stop, "retries": 0, "seconds": 0.0,
                "in_tok": 0, "out_tok": 0}
    attempt = 0
    while True:
        result = post_once(prompt, image_b64)
        error = str(result.get("error") or "")
        retry_after = result.get("retry_after")
        if not error:
            result["retries"] = attempt
            return result
        if "429" in error:
            event = {"at_ist": ist_now(), "doc_key": doc_key, "page": page,
                     "retry_after": retry_after,
                     "message": f"retry_after={retry_after} {error[:280]}"}
            with _RETRY_LOCK:
                _RETRY_EVENTS.append(event)
            print(f"429 {event['at_ist']} {doc_key} p{page} retry_after={retry_after!r} retry {attempt}",
                  file=sys.stderr)
            if retry_after is not None and retry_after > QUOTA_STOP_SECONDS:
                set_quota(retry_after)
                result["quota"] = retry_after
                result["retries"] = attempt
                return result
        if not RETRYABLE.search(error) or attempt >= MAX_RETRIES:
            result["retries"] = attempt
            return result
        attempt += 1
        if retry_after is not None and retry_after <= QUOTA_STOP_SECONDS:
            delay = max(1.0, retry_after) + random.random()
        else:
            delay = min(60.0, 4.0 * (2 ** attempt)) + random.random() * 2.0
        time.sleep(delay)


PROPOSAL_PROMPT = """Map one printed financial label from an Indian company's deck to one measure id in the
dictionary. Reply with ONE JSON object and nothing else:
{{"measure": "<exact dictionary id, or empty when none fits>", "reason": "<one sentence>"}}
Never invent a value or a unit. If the label names something the dictionary does not cover, return an empty measure.

Printed label: {label}
Unit: {unit}
One printed value: {value}

Dictionary (id -- name -- unit family -- driver node):
{dictionary}"""


def propose_one(dictionary: str, label: str, unit: str, value: str, doc_key: str, page: int) -> tuple[str, str] | None:
    if quota_seconds() > 0:
        return None
    prompt = PROPOSAL_PROMPT.format(dictionary=dictionary, label=label[:300], unit=unit, value=value)
    result = call_reader(prompt, None, doc_key, page)
    if result.get("quota"):
        return None
    if result.get("error"):
        return "", f"reader error: {str(result['error'])[:200]}"
    rows, _bad = parse_reply(result.get("output") or "")
    if rows and isinstance(rows[0], dict):
        return norm_space(rows[0].get("measure")), norm_space(rows[0].get("reason"))[:300]
    return "", "unparsable reply"


def propose_measures(con: sqlite3.Connection, limit: int = 300, workers: int = 20) -> dict[str, int]:
    """One hy4 proposal per distinct unmapped label, stored with its reason; never applied to a row."""
    if limit <= 0:
        return {"labels": 0, "proposed": 0, "quota": False}
    measures = measure_index()
    counts: dict[str, int] = {}
    samples: dict[str, tuple[str, str, str, int]] = {}
    for label, measure, unit, value, doc_key, page in con.execute(
            "SELECT printed_label, measure, unit, value_text, doc_key, page FROM observation"):
        label = str(label or "")
        if not label or measure in measures or script_measure(label):
            continue
        counts[label] = counts.get(label, 0) + 1
        samples.setdefault(label, (str(unit or ""), str(value or ""), str(doc_key or ""), int(page or 0)))
    existing = {row[0] for row in con.execute("SELECT printed_label FROM measure_proposal")}
    todo = [(label, n) for label, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            if label not in existing][:limit]
    dictionary = dictionary_text(measures)
    written = 0
    quota_hit = False
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(propose_one, dictionary, label, *samples[label]): label for label, _n in todo}
        for future in as_completed(futures):
            label = futures[future]
            try:
                answer = future.result()
            except Exception as exc:
                answer = ("", f"{type(exc).__name__}: {exc}")
            if answer is None:
                quota_hit = True
                continue
            measure, reason = answer
            con.execute("INSERT OR REPLACE INTO measure_proposal VALUES (?,?,?,?,?)",
                        (label, measure, reason[:500], "hy4", ist_now()))
            written += 1
    con.commit()
    return {"labels": len(todo), "proposed": written, "quota": quota_hit}


def process_page(store_db: str | Path, doc_key: str, page: int,
                 companies: dict[str, tuple[str, str]] | None = None) -> dict[str, Any]:
    """One page: image + text layer -> model reply -> checked observation rows."""
    stop = quota_seconds()
    if stop > 0:                     # the shared key is in its quota window: leave the page for the resume run
        return {"store": str(store_db), "doc_key": doc_key, "page": page, "quota": stop}
    meta = page_meta(store_db, doc_key)
    if not meta:
        return {"store": str(store_db), "doc_key": doc_key, "page": page, "skip": "no doc row"}
    owner = ""
    if companies:
        try:
            owner = doc_owner(store_db, doc_key, companies, meta["symbol"])
        except Exception:
            owner = ""
    text = page_text_of(store_db, doc_key, page)
    try:
        words = page_words.words_for(store_db, doc_key, page).words
    except Exception:
        words = []
    layout = page_layout.layout_text(words) if words else norm_space(text)
    image_b64 = None
    try:
        data, _scale = page_reader._page_image(store_db, doc_key, page)
        image_b64 = base64.b64encode(data).decode("ascii")
    except Exception as exc:
        image_note = f"no page image: {type(exc).__name__}: {exc}"[:200]
    else:
        image_note = ""
    result: dict[str, Any] = {"store": str(store_db), "doc_key": doc_key, "page": page, "symbol": meta["symbol"],
                              "owner": owner, "raw": "", "error": "", "rows": [], "bad_lines": 0,
                              "parsed": 0, "seconds": 0.0, "image_note": image_note}
    if not image_b64 and not layout.strip():
        result["skip"] = "no image and no text"
        return result
    prompt = PROMPT.format(dictionary=dictionary_text(measure_index()), text=layout[:TEXT_LAYER_CHARS])
    call = call_reader(prompt, image_b64, doc_key, page)
    if call.get("quota"):
        result["quota"] = call["quota"]
        return result
    result["seconds"] = float(call.get("seconds") or 0.0)
    result["raw"] = str(call.get("output") or "")
    if call.get("error"):
        result["error"] = str(call.get("error") or "")
        return result
    reply_rows, bad = parse_reply(result["raw"])
    result["bad_lines"] = bad
    result["parsed"] = len(reply_rows)
    result["rows"] = build_observations(symbol=meta["symbol"], doc_key=doc_key, page=page,
                                        known_at=meta["known_at"], page_text=text, words=words,
                                        reply_rows=reply_rows, doc_owner_symbol=owner,
                                        companies=companies, deck_asof=deck_period(store_db, doc_key, text))
    return result


# --------------------------------------------------------------------------- stage F annual-report page filter
#
# An annual report's routed table/chart pages are mostly financial statements and notes, whose lines the
# stores already hold from XBRL: of 1,837 verified pilot rows only 47 were operating measures.  The filter
# below drops those pages before any model call, on the stored text layer only.

HEADING_WORDS = 14                     # a printed heading is short; a sentence that mentions a statement is not

STATEMENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("balance_sheet", re.compile(r"^(?:consolidated\s+|standalone\s+)?balance\s+sheet\b", re.I)),
    ("profit_and_loss", re.compile(r"^(?:consolidated\s+|standalone\s+)?(?:statement\s+of\s+)?"
                                   r"profit\s*(?:and|&)\s*loss\b", re.I)),
    ("cash_flow", re.compile(r"^(?:consolidated\s+|standalone\s+)?(?:statement\s+of\s+)?"
                             r"cash\s*-?\s*flows?\s+statement\b|^statement\s+of\s+cash\s*-?\s*flows?\b", re.I)),
    ("changes_in_equity", re.compile(r"^(?:consolidated\s+|standalone\s+)?statement\s+of\s+changes\s+"
                                     r"in\s+equity\b", re.I)),
    ("notes", re.compile(r"^(?:notes?|schedules?)\s+(?:forming\s+part\s+of\s+|to\s+)?(?:the\s+)?"
                         r"(?:standalone\s+|consolidated\s+)?financial\s+statements?\b|"
                         r"^notes?\s+on\s+accounts\b", re.I)),
    ("note_no", re.compile(r"^note\s*(?:no\.|number\b)(?!\s*\d*\s*of\s+the\b)|^note\s+\d{1,2}\s*[:(.]", re.I)),
    ("audit_report", re.compile(r"^(?:independent\s+)?auditor['\u2019]?s?\s+report\b|"
                                r"^annexure\b.{0,80}?\bto\s+the\s+(?:independent\s+)?auditor['\u2019]?s?\s+"
                                r"report\b", re.I)),
    ("aoc1", re.compile(r"^form\s+(?:no\.?\s*)?aoc-?\s*1\b", re.I)),
    ("mgt9", re.compile(r"^mgt-?\s*9\b|^extract\s+of\s+the\s+annual\s+return\b", re.I)),
    ("remuneration", re.compile(r"^(?:details\s+(?:pertaining\s+to\s+)?)?(?:remuneration\s+"
                                r"(?:to|of|paid\s+to)\s+(?:the\s+)?(?:directors?|key\s+managerial|managing)|"
                                r"(?:details\s+)?(?:as\s+)?required\s+under\s+section\s+197\b)|"
                                r"^particulars\s+of\s+(?:directors|employees)\b", re.I)),
    ("csr_spend", re.compile(r"^(?:csr\s+(?:amount\s+spent|spend|spending|expenditure|expenses|projects?)|"
                             r"annual\s+report\s+on\s+csr|annexure\b.{0,40}?\bcsr\b)", re.I)),
    ("shareholding", re.compile(r"^shareholding\s+pattern\b", re.I)),
    ("share_price", re.compile(r"^share\s+price\s+(?:data|movement|performance)\b|"
                               r"^performance\s+comparison\b", re.I)),
    ("notice", re.compile(r"^(?:notice\s+(?:to\s+)?(?:the\s+)?(?:shareholders|members)\b|"
                          r"explanatory\s+statement\b|postal\s+ballot\b|remote\s+e-?voting\b|"
                          r"instructions\s+for\s+.{0,20}voting\b|"
                          r"details\s+of\s+directors\s+seeking\s+appointment|"
                          r"annexure\s+to\s+the\s+notice)", re.I)),
    ("secretarial_audit", re.compile(r"^secretarial\s+audit\s+report\b|^form\s+no\.?\s*mr-?3\b", re.I)),
    ("governance", re.compile(r"^(?:report\s+on\s+corporate\s+governance\b|corporate\s+governance\s+report\b|"
                              r"code\s+of\s+(?:conduct|ethics)\b)(?!\s*,\s*(?:which|that|and)\b)", re.I)),
    ("related_party", re.compile(r"^related\s+party\s+(?:transactions?|disclosures?)\b", re.I)),
    ("brsr", re.compile(r"^business\s+responsibility\s*(?:&|and)\s*sustainab", re.I)),
)

# A page with one of these headings can still carry the operating figures stage F exists for: keep it.
STATEMENT_CARVE_OUT: dict[str, re.Pattern[str]] = {
    "notes": re.compile(r"segment\s+(?:reporting|information)\b|geograph\w*\s+segment|"
                        r"revenue\s+by\s+(?:location|customer)|"
                        r"customers?\s+(?:represents?|account\s+for)\s+(?:10|ten)\s*%|"
                        r"customer\s+\d\b|by\s+location\s+of\s+customers|"
                        r"sale\s+of\s+(?:goods|services|products?)\b", re.I),
    "brsr": re.compile(r"number\s+of\s+locations\s+where\s+plants|"
                       r"plants\s+and\s*/\s*or\s+operations(?:\s*/\s*offices)?\s+of\s+the|"
                       r"number\s+of\s+plants", re.I),
}


def statement_page_reason(text: str) -> str:
    """Stage F: why a page is a financial-statement / notes page ('' when it is not).

    Checked against the text layer's own lines: a printed heading starts its line and is short, so an MD&A
    sentence that mentions the balance sheet is kept.  A page with no text layer has no headings and is kept.
    A notes page printing a segment-reporting table (or a BRSR page printing the plant-location table) carries
    the capacity/plant/segment figures stage F is after and is kept.
    """
    flat = norm_space(text)
    for raw in text.splitlines():
        line = norm_space(raw)
        if not line or len(line.split()) > HEADING_WORDS:
            continue
        if line[0].islower() or line.endswith("."):
            continue               # a sentence fragment that mentions a statement, not a printed heading
        for name, pattern in STATEMENT_RULES:
            if pattern.match(line):
                carve = STATEMENT_CARVE_OUT.get(name)
                if carve is not None and carve.search(flat):
                    return ""
                return name
    return ""


def page_texts(store_db: str | Path, pages: Iterable[dict[str, Any]]) -> dict[tuple[str, int], str]:
    """The stored text layer of the given pages, one read per document (stage F filter input)."""
    by_doc: dict[str, list[int]] = {}
    for p in pages:
        by_doc.setdefault(str(p["doc_key"]), []).append(int(p["page"]))
    out: dict[tuple[str, int], str] = {}
    con = connect_ro(store_db, timeout_s=60)
    try:
        for doc_key, numbers in by_doc.items():
            marks = ",".join("?" * len(numbers))
            _cur = con.execute(f"SELECT page, text FROM doc_page WHERE doc_key=? AND page IN ({marks})",
                               (doc_key, *numbers))
            if _cur is None:
                continue
            for row in (_cur.fetchall() or []):
                out[(doc_key, int(row[0]))] = str(row[1] or "")
    finally:
        con.close()
    return out


def filter_statement_pages(pages: list[dict[str, Any]], texts: dict[tuple[str, int], str],
                           dropped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Stage F: drop the financial-statement and notes pages; ``dropped`` counts them by reason."""
    kept: list[dict[str, Any]] = []
    for p in pages:
        reason = statement_page_reason(texts.get((str(p["doc_key"]), int(p["page"])), ""))
        if not reason:
            kept.append(p)
        elif dropped is not None:
            dropped[reason] = dropped.get(reason, 0) + 1
    return kept


def pages_from_store(store_db: str | Path, doc_types: Iterable[str] = ("deck",),
                     routes: Iterable[str] = ("table_or_chart",), skip_statements: bool = False,
                     dropped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    routes_csv = Path(store_db).parent / "routes.csv"
    if not routes_csv.is_file():
        return []
    wanted_types = {rp._doc_type_norm(t) for t in doc_types}
    wanted_routes = set(routes)
    pages: dict[tuple[str, int], dict[str, Any]] = {}
    with routes_csv.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("route") not in wanted_routes:
                continue
            if rp._doc_type_norm(row.get("doc_type", "")) not in wanted_types:
                continue
            try:
                page = int(row["page"])
            except (KeyError, ValueError):
                continue
            pages.setdefault((row["doc_key"], page), {"store": str(store_db), "doc_key": row["doc_key"],
                                                      "page": page})
    selected = list(pages.values())
    if skip_statements:
        selected = filter_statement_pages(selected, page_texts(store_db, selected), dropped)
    return selected


def seed_stores(root: str | Path, sample: int, seed: int, ensure: Iterable[str] = (),
                doc_types: Iterable[str] = ("deck",)) -> list[str]:
    """Stores under ``root`` that hold routed pages of ``doc_types``: required ones plus the rest chosen by ``seed``."""
    root = Path(root)
    dirs = sorted(p for p in root.iterdir() if p.is_dir() and (p / f"{p.name}.db").is_file()
                  and pages_from_store(p / f"{p.name}.db", doc_types=doc_types))
    ensure_names = [name for name in ensure if (root / name / f"{name}.db").is_file()]
    ensure_dirs = [p for p in dirs if p.name in ensure_names]
    ensure_names = [p.name for p in ensure_dirs]
    pool = [p for p in dirs if p not in ensure_dirs]
    extra = random.Random(seed).sample(pool, max(0, min(sample, len(pool)) - len(ensure_names)))
    picked = [root / name / f"{name}.db" for name in ensure_names] + [p / f"{p.name}.db" for p in extra]
    return [str(p) for p in picked]


def select_pages(pages: list[dict[str, Any]], limit: int, seed: int,
                 required: Iterable[tuple[str, int]] = ()) -> list[dict[str, Any]]:
    """The required pages plus a seeded sample of the rest, at most ``limit`` in all."""
    required = list(required)
    pages = sorted(pages, key=lambda p: (p["doc_key"], p["page"]))
    forced = [p for p in pages if any(sub in p["doc_key"] and p["page"] == page for sub, page in required)]
    rest = [p for p in pages if p not in forced]
    random.Random(seed).shuffle(rest)
    return (forced + rest)[:limit]


def missing_pages(con: sqlite3.Connection, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pages with no observation row yet (T-230 stage B resume: skip what a stopped run already wrote)."""
    done = {(str(row[0]), int(row[1])) for row in con.execute("SELECT DISTINCT doc_key, page FROM observation")}
    return [p for p in pages if (str(p["doc_key"]), int(p["page"])) not in done]


def recheck_db(con: sqlite3.Connection, store_dbs: Iterable[str | Path],
               companies: dict[str, tuple[str, str]] | None = None) -> dict[str, Any]:
    """Stage C: re-apply every script check to an existing observation DB with no model call.

    Only checks that need a new printed source may upgrade an unverified row: an inherited unit or period, a
    measure alias/label mapping, or a stage read from a printed group.  Any other upgrade is refused and reported.
    """
    store_dbs = list(store_dbs)
    companies = companies if companies is not None else company_index(store_dbs)
    measures = measure_index()
    vocab = vocab_index()
    doc_store: dict[str, str] = {}
    store_symbol: dict[str, str] = {}
    for store_db in store_dbs:
        try:
            store_con = connect_ro(store_db, timeout_s=60)
            _cur = store_con.execute("SELECT symbol FROM company LIMIT 1")
            symbol_row = _cur.fetchone() if _cur is not None else None
            store_symbol[str(store_db)] = str(symbol_row[0] or "") if symbol_row else ""
            _cur = store_con.execute("SELECT doc_key FROM doc")
            if _cur is not None:
                for row in _cur:
                    if row is not None:
                        doc_store[str(row[0])] = str(store_db)
            store_con.close()
        except Exception:
            continue
    stats: dict[str, Any] = {"pages": 0, "rows": 0, "changed": 0, "upgraded": 0, "downgraded": 0,
                             "unit_inherited": 0, "period_inherited": 0, "measure_mapped": 0, "adjusted": 0,
                             "parent_rows": 0, "stage_set": 0, "unproven_upgrades": 0, "kept_hard_reason": 0,
                             "scale_fixed": 0, "basis_set": 0, "basis_conflicts": 0, "bridge_rows": 0,
                             "subsidiary_rows": 0, "deck_periods": 0, "deck_period_cleared": 0,
                             "deck_period_fixed": 0, "cagr_rows": 0}
    pages = list(con.execute("SELECT DISTINCT doc_key, page FROM observation ORDER BY doc_key, page"))
    con.row_factory = sqlite3.Row
    for doc_key, page in pages:
        store_db = doc_store.get(str(doc_key))
        if not store_db:
            continue
        stats["pages"] += 1
        raw_text = page_text_of(store_db, doc_key, int(page))
        text = norm_space(raw_text)
        head = page_head(raw_text)
        deck_asof = deck_period(store_db, doc_key, raw_text)
        try:
            words = page_words.words_for(store_db, doc_key, int(page)).words
        except Exception:
            words = []
        owner = ""
        try:
            owner = doc_owner(store_db, doc_key, companies, store_symbol.get(store_db, ""))
        except Exception:
            owner = ""
        rows = [dict(r) for r in con.execute("SELECT * FROM observation WHERE doc_key=? AND page=?",
                                             (doc_key, int(page)))]
        updated: list[dict[str, Any]] = []
        for row in rows:
            stats["rows"] += 1
            old_status = str(row["status"])
            old_measure = str(row["measure"])
            old_reason = str(row["status_reason"] or "")
            new_measure = canonical_measure(row["measure"] or "", row["printed_label"] or "",
                                            row["printed_axis"] or "", row["series_title"] or "",
                                            row["unit"] or "", text)
            mapped = new_measure != old_measure
            if mapped:
                row["measure"] = new_measure
                stats["measure_mapped"] += 1
            cagr_set = False
            cagr = cagr_measure(row["measure"], row["printed_label"] or "", row["printed_axis"] or "",
                                row["series_title"] or "", raw_text)
            if cagr:
                row["measure"], span = cagr
                if span:
                    row["period"] = span
                    row["period_source"] = ""
                    row["period_kind"] = "span"
                cagr_set = True
                stats["cagr_rows"] += 1
            measure = measures.get(row["measure"] or "")
            family = measure["unit_family"] if measure else (row["unit_family"] or "")
            unit_inherited = period_inherited = stage_set = scale_fixed = deck_period_used = False
            if not row["unit"]:
                inferred = infer_unit([row["printed_axis"] or "", row["series_title"] or "",
                                       row["printed_label"] or ""], family)
                if inferred:
                    row["unit"], row["unit_family"], row["scale"] = inferred
                    unit_inherited = True
                    stats["unit_inherited"] += 1
            if family in ("money", "money_per_unit") and float(row["scale"] or 1) == 1:
                factor = money_scale([row["unit"] or "", row["printed_axis"] or "",
                                      row["series_title"] or "", head])
                if factor:
                    row["scale"] = factor
                    scale_fixed = True
                    stats["scale_fixed"] += 1
            if (row["unit"] or "").strip().upper() in MT_UNITS and float(row["scale"] or 1) == 1:
                resolved = resolve_mt_scale(raw_text)
                if resolved:
                    row["scale"] = resolved
                    scale_fixed = True
                    stats["scale_fixed"] += 1
            if row["period_source"] == "deck_period":
                if not is_stock_measure(row["measure"] or "") or not capacity_deck_period_ok(row, raw_text) \
                        or not deck_asof:
                    row["period"] = ""
                    row["period_source"] = ""
                    row["period_kind"] = ""
                    stats["deck_period_cleared"] += 1
                elif row["period"] != deck_asof:
                    row["period"] = deck_asof
                    row["period_kind"] = period_kind_for("", deck_asof)
                    stats["deck_period_fixed"] += 1
            if not row["period"]:
                period = infer_period([row["printed_axis"] or "", row["series_title"] or "",
                                       row["group_path"] or "", row["printed_label"] or ""])
                if period:
                    row["period"] = period
                    row["period_kind"] = period_kind_for("", period)
                    period_inherited = True
                    stats["period_inherited"] += 1
                elif deck_asof and is_stock_measure(row["measure"] or "") \
                        and capacity_deck_period_ok(row, raw_text):
                    row["period"] = deck_asof
                    row["period_kind"] = period_kind_for("", deck_asof)
                    row["period_source"] = "deck_period"
                    deck_period_used = True
                    stats["deck_periods"] += 1
            if not row["adjusted"] and ADJUSTED_RE.search(" ".join(
                    [row["printed_label"] or "", row["printed_axis"] or "", row["series_title"] or ""])):
                row["adjusted"] = 1
                stats["adjusted"] += 1
            if not row["stage"]:
                stage = stage_from_group(vocab, row["group_path"] or "")
                if stage:
                    row["stage"] = stage
                    stage_set = True
                    stats["stage_set"] += 1
            if detect_subsidiary([row["printed_axis"] or "", row["series_title"] or "", head],
                                 companies, store_symbol.get(store_db, "")):
                if row["entity_scope"] in ("company", "parent", ""):
                    row["entity_scope"] = "subsidiary"
                    stats["subsidiary_rows"] += 1
            old_basis = str(row["basis"] or "")
            row["basis"] = detect_basis(row["printed_axis"] or "", row["series_title"] or "", head,
                                        words, row["region"] or "", row["group_path"] or "", raw_text)
            basis_changed = bool(row["basis"]) and row["basis"] != old_basis
            if owner and row["entity_scope"] in ("company", "subsidiary", ""):
                row["entity_scope"] = "parent"
                stats["parent_rows"] += 1
            row.pop("_scale_notes", None)
            status, reasons = evaluate_status(dict(row), text, measures, raw_text)
            dictionary_fix = ("measure is not in the dictionary" in old_reason
                              and (row["measure"] or "") in measures)
            row["_old_status"] = old_status
            row["_old_reason"] = old_reason
            row["_proof"] = (unit_inherited or period_inherited or mapped or stage_set or dictionary_fix
                             or scale_fixed or deck_period_used or cagr_set or basis_changed)
            row["status"] = status
            row["status_reason"] = "; ".join(reasons)
            updated.append(row)
        apply_series_kind(updated, raw_text)
        stats["bridge_rows"] += sum(1 for r in updated if r["series_kind"] == "bridge")
        stats["basis_set"] += sum(1 for r in updated if r["basis"])
        stats["basis_conflicts"] += apply_basis_conflicts(updated)
        for row in updated:
            old_status = str(row["_old_status"])
            old_reason = str(row["_old_reason"])
            status = str(row["status"])
            reason = str(row["status_reason"] or "")
            if status == "verified" and old_status != "verified":
                hard_old = "parts sum to" in old_reason or ("scale " in old_reason and not row["_proof"])
                if hard_old:
                    stats["kept_hard_reason"] = int(stats.get("kept_hard_reason", 0)) + 1
                    status, reason = old_status, old_reason
                elif not row["_proof"] and "basis_conflict" not in old_reason:
                    stats["unproven_upgrades"] += 1
                    examples = stats.setdefault("unproven_examples", [])
                    if isinstance(examples, list) and len(examples) < 20:
                        examples.append({"observation_id": row["observation_id"], "symbol": row["symbol"],
                                         "measure": row["measure"], "unit": row["unit"], "period": row["period"],
                                         "old_reason": old_reason[:220]})
                    status, reason = old_status, old_reason
            if status != old_status:
                if status == "verified":
                    stats["upgraded"] += 1
                elif old_status == "verified":
                    stats["downgraded"] += 1
            con.execute("UPDATE observation SET measure=?, unit=?, unit_family=?, scale=?, period=?, period_kind=?, "
                        "period_source=?, basis=?, series_kind=?, adjusted=?, stage=?, entity_scope=?, status=?, "
                        "status_reason=? WHERE observation_id=?",
                        (row["measure"], row["unit"], row["unit_family"], row["scale"], row["period"],
                         row["period_kind"], row["period_source"], row["basis"], row["series_kind"],
                         row["adjusted"], row["stage"], row["entity_scope"], status, reason,
                         row["observation_id"]))
            stats["changed"] += 1
    con.commit()
    if stats["unproven_upgrades"]:
        stats["stopped"] = (f"{stats['unproven_upgrades']} rows would verify without a new printed source; "
                            "their stage B status is kept")
    return stats


def run(store_dbs: list[str], limit: int, workers: int, out: str | Path,
        doc_types: Iterable[str] = ("deck",), seed: int = 11,
        required: Iterable[tuple[str, int]] = (), propose_limit: int = 300,
        resume: bool = False, skip_statements: bool = False) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    dropped_by_reason: dict[str, int] = {}
    for store_db in store_dbs:
        pages.extend(pages_from_store(store_db, doc_types=doc_types, skip_statements=skip_statements,
                                      dropped=dropped_by_reason))
    selected = select_pages(pages, limit, seed, required)
    statement_filter = {"kept": len(pages), "dropped": sum(dropped_by_reason.values()),
                        "by_reason": dict(sorted(dropped_by_reason.items(), key=lambda kv: -kv[1]))}
    if skip_statements:
        print(f"statement filter: kept {statement_filter['kept']} dropped {statement_filter['dropped']} "
              f"{statement_filter['by_reason']}", file=sys.stderr)
    with _RETRY_LOCK:
        _RETRY_EVENTS.clear()
    with _QUOTA_LOCK:
        _QUOTA["seconds"] = 0.0
    con = create_db(out)
    already_done = 0
    if resume:
        before = len(selected)
        selected = missing_pages(con, selected)
        already_done = before - len(selected)
    stats: dict[str, Any] = {"pages": len(selected), "already_done": already_done, "read": 0, "errors": 0,
                             "parse_failures": 0, "dropped_all": 0, "observations": 0, "quarantined": 0,
                             "skipped": 0, "quota_skipped": 0, "parent_rows": 0, "http_429": 0,
                             "statement_filter": statement_filter, "failed_replies": []}
    companies = company_index(store_dbs)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process_page, p["store"], p["doc_key"], p["page"], companies): p for p in selected}
        done = 0
        for future in as_completed(futures):
            done += 1
            try:
                result = future.result()
            except Exception as exc:
                stats["errors"] += 1
                stats["failed_replies"].append({"error": f"{type(exc).__name__}: {exc}"})
                continue
            if result.get("quota"):
                stats["quota_skipped"] += 1
                continue
            if result.get("skip"):
                stats["skipped"] += 1
                continue
            if result.get("error"):
                stats["errors"] += 1
                if "429" in result["error"]:
                    print(f"429: {result['store']} {result['doc_key']} p{result['page']}: {result['error']}",
                          file=sys.stderr)
                stats["failed_replies"].append({"store": result["store"], "doc_key": result["doc_key"],
                                                "page": result["page"], "error": result["error"]})
                continue
            rows = result["rows"]
            stats["read"] += 1
            if not rows:
                if not result["raw"].strip() or result["parsed"] == 0:
                    stats["parse_failures"] += 1
                    if len(stats["failed_replies"]) < 5:
                        stats["failed_replies"].append({"store": result["store"], "doc_key": result["doc_key"],
                                                        "page": result["page"], "raw": result["raw"][:2000]})
                else:
                    stats["dropped_all"] += 1      # a letterhead / cover page whose every row the script dropped
            write_rows(con, rows)
            stats["observations"] += len(rows)
            stats["quarantined"] += sum(1 for r in rows if r["status"] == "quarantined")
            stats["parent_rows"] += sum(1 for r in rows if r["entity_scope"] == "parent")
            if done % 100 == 0:
                print(f"{done}/{len(selected)} pages, {stats['observations']} observations, "
                      f"{time.time() - t0:.0f}s", file=sys.stderr)
    events = list(_RETRY_EVENTS)
    if events:
        con.executemany("INSERT INTO http_429 (at_ist, doc_key, page, message) VALUES (?,?,?,?)",
                        [(e["at_ist"], e["doc_key"], e["page"], e["message"]) for e in events])
        con.commit()
    stats["http_429"] = len(events)
    stats["quota_retry_after"] = quota_seconds()
    if quota_seconds() > 0:
        stats["proposals"] = {"labels": 0, "proposed": 0, "quota": True}
    else:
        stats["proposals"] = propose_measures(con, propose_limit, workers)
    con.close()
    stats["seconds"] = round(time.time() - t0, 1)
    stats["out"] = str(out)
    done_pages = max(1, stats["pages"] - stats["quota_skipped"])
    reply_fail_share = (stats["parse_failures"] + stats["errors"]) / done_pages
    quarantine_share = stats["quarantined"] / max(1, stats["observations"])
    stats["reply_fail_share"] = round(reply_fail_share, 3)
    stats["quarantine_share"] = round(quarantine_share, 3)
    if quota_seconds() > 0:
        stats["stopped"] = (f"hy4 quota window (Retry-After {quota_seconds():.0f} s); "
                            f"{stats['quota_skipped']} pages left for the --resume run")
    elif reply_fail_share > PARSE_STOP:
        stats["stopped"] = "more than 20% of pilot pages gave an empty or non-JSON reply"
    elif quarantine_share > QUARANTINE_STOP:
        stats["stopped"] = "more than 10% of observations are quarantined"
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-230: observation rows from deck/AR visuals")
    parser.add_argument("--stores", default="", help="comma list of store names, dirs or .db paths")
    parser.add_argument("--stores-root", default="", help="root holding cNN/cNN.db store directories")
    parser.add_argument("--sample", type=int, default=5, help="stores to pick from --stores-root")
    parser.add_argument("--ensure", default="", help="comma list of stores always included from --stores-root")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--limit", type=int, default=150, help="pages read at most")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--out", default=".tmp/t230/obs.db")
    parser.add_argument("--doc-types", default="deck")
    parser.add_argument("--propose-limit", type=int, default=300,
                        help="hy4 label->measure proposals at most (0 turns the pass off)")
    parser.add_argument("--require", default="", help="doc_key-substring:page to force into the sample")
    parser.add_argument("--resume", action="store_true",
                        help="skip pages that already have observation rows in --out (after a stopped run)")
    parser.add_argument("--recheck", action="store_true",
                        help="re-apply every script check to --out with no model call (stage C)")
    parser.add_argument("--skip-statements", action="store_true",
                        help="drop financial-statement/notes pages before any model call (stage F)")
    args = parser.parse_args(argv)

    store_dbs: list[str] = []
    doc_types = [t for t in args.doc_types.split(",") if t]
    if args.stores_root:
        store_dbs = seed_stores(args.stores_root, args.sample, args.seed,
                                [s for s in args.ensure.split(",") if s], doc_types=doc_types)
    if args.stores:
        for item in args.stores.split(","):
            item = item.strip()
            if not item:
                continue
            path = Path(item)
            if path.is_dir():
                path = path / f"{path.name}.db"
            elif not path.suffix and (Path(args.stores_root or ".") / item / f"{item}.db").is_file():
                path = Path(args.stores_root or ".") / item / f"{item}.db"
            store_dbs.append(str(path))
    store_dbs = [s for s in dict.fromkeys(store_dbs) if Path(s).is_file()]
    if not store_dbs:
        parser.error("no store found from --stores / --stores-root")
    if args.recheck:
        back = create_db(args.out)
        try:
            recheck_stats = recheck_db(back, store_dbs)
        finally:
            back.close()
        print(json.dumps(recheck_stats, indent=2))
        if recheck_stats.get("stopped"):
            print(f"STOP: {recheck_stats['stopped']}", file=sys.stderr)
            return 2
        return 0
    required: list[tuple[str, int]] = []
    for item in args.require.split(","):
        if ":" in item:
            sub, page = item.rsplit(":", 1)
            required.append((sub.strip(), int(page)))
    stats = run(store_dbs, args.limit, args.workers, args.out,
                doc_types=doc_types, seed=args.seed, required=required,
                propose_limit=args.propose_limit, resume=args.resume, skip_statements=args.skip_statements)
    print(json.dumps(stats, indent=2))
    if stats.get("stopped"):
        print(f"STOP: {stats['stopped']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
