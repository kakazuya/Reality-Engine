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
* (stage I) a per-unit measure (EPS, Rs/kWh) never takes a crore/lakh scale and "tn" reads 1e12; a
  statement/table page's bare cells are never an axis tick; "Y-O-Y"/"QoQ"/"growth" is not a period;
  "lakh sq ft" is area and "billion units" is energy; a Unicode dash matches an ASCII hyphen; "crossed /
  more than / exceeds" prints a lower bound (``value_kind``), never the actual figure; a footnote that
  names one period's basis overrides the page basis for that period.
* (stage J) an axis ladder needs five evenly spaced values, a table page (three or more label-then-column
  rows) is never a chart ladder, and a printed text line beside the value is its data label; the printed
  total flag is stored (``is_total``) and re-derived from the label ("Total", "Overall", "Consolidated
  total") or the arithmetic, so a recheck keeps the parts-sum proof.
* (stage K) the top-500 annual-report invented measure names are reviewed once: only a same-meaning name is
  aliased, a handful of driver measures (DPS, gross block, accumulated depreciation, share count, DSCR,
  turnover ratios) join the dictionary, and governance/compliance/BRSR names stay unmapped.  Basis and period
  also come from the printed column header nearest above the value ("Standalone"/"Consolidated", the year a
  column is headed with) when the page title, series or label names none; no header above the value is no
  basis/period, never a guess.
* (stage L) a parts-sum proof needs two non-zero parts with two distinct values and a total that is not itself
  a part; a generic category label ("Male", "Other", "Total", "Wages", "Interest Cost") verifies only when
  the printed group heading names the measure (``generic_label``), and a gratuity/defined-benefit interest
  cost is never finance cost; a page/section heading names the basis ("Notes to Consolidated", "the Group",
  "Standalone"); a date inside an inline comparative bracket is not the row's period, and a printed
  "as at/as on <date>" on a closing balance is a point-in-time period (``period_kind='instant'``), not the
  year's flow.
* (stage M) the measure is a dictionary id or a DECLARED ``NEW:<snake_case>`` with its definition and driver node; a
  bare non-dictionary id is ``undeclared_new`` and never verifies, and every NEW id is indexed in ``measure_new``
  (counts, pages, definitions) with model-free merge proposals in a review CSV.  ``--doc-types transcript`` reads
  call pages text-only through the transcript prompt and stores ``statement`` (verbatim sentence, speaker,
  direction) and ``guidance`` (period, low/high, unit, direction) records beside the numbers; a statement verifies
  when its sentence is in the page text, a guidance row when its value tokens and period words are in the sentence.
* (stage O) a statement is one management speaker's whole passage on one topic, never a sentence cut at a PDF line
  break: one without terminal punctuation or ending on and/the/of/to/in is quarantined (``statement_cut``), and a
  pronoun-only passage with no measure is unverified ``no_subject``; a guidance row whose value no statement row on
  its page carries is flagged ``guidance_without_statement``; the question a short answer needs is kept in
  ``question_context`` beside the verbatim answer.

Output is a separate SQLite file (``--out``, default ``.tmp/t230/obs.db``); a store is only ever
read.  Tables: ``observation``, ``measure_dict``, ``measure_new``, ``dim_vocab``.

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
import contextlib
import csv
import json
import os
import random
import re
import sqlite3
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import lru_cache
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

# T-238 stage M: the output contract.  A fact's measure is a dictionary id or, when nothing in the dictionary means
# the same thing, a DECLARED new one: "NEW:<snake_case id>" plus its definition and driver node.  A bare id that is
# neither is rejected as ``undeclared_new`` and never verifies.
NEW_PREFIX = "NEW:"
NEW_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
NEW_NODES = ("revenue", "cost", "margin", "capex", "capacity", "debt", "equity", "working_capital", "none")
RECORD_TYPES = ("number", "statement", "guidance")


def reader_entry(name: str) -> str:
    """T-234: the ``@obs`` MODELS entry for reader ``name``; KeyError when the registry has no such model."""
    if name not in rp.MODELS:
        raise KeyError(name)
    entry = f"{name}@obs"
    if entry not in rp.MODELS:         # do not mutate another job's reader: this is our own entry
        base = rp.MODELS[name]
        rp.MODELS[entry] = {**base, "id": base.get("id", name),
                            "body": {**base.get("body", {}), "max_tokens": 16000}}
    return entry


def set_reader(name: str) -> None:
    """T-234 ``--reader``: read with another MODELS entry; the default (hy4-flash-free) is unchanged."""
    global READER, OBS_READER
    READER, OBS_READER = name, reader_entry(name)


set_reader(READER)

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
    value_kind TEXT NOT NULL DEFAULT '',
    is_total INTEGER NOT NULL DEFAULT 0,
    period TEXT NOT NULL DEFAULT '',
    period_kind TEXT NOT NULL DEFAULT '',
    period_source TEXT NOT NULL DEFAULT '',
    basis TEXT NOT NULL DEFAULT '',
    basis_source TEXT NOT NULL DEFAULT '',
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
    text_source TEXT NOT NULL DEFAULT '',
    record_type TEXT NOT NULL DEFAULT 'number',
    statement TEXT NOT NULL DEFAULT '',
    speaker TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT '',
    question_context TEXT NOT NULL DEFAULT '',
    value_high REAL,
    new_definition TEXT NOT NULL DEFAULT '',
    new_driver_node TEXT NOT NULL DEFAULT '',
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

CREATE TABLE IF NOT EXISTS page_reply (
    doc_key TEXT NOT NULL,
    page INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    raw TEXT NOT NULL,
    read_at TEXT NOT NULL,
    PRIMARY KEY (doc_key, page)
);

CREATE TABLE IF NOT EXISTS page_read (
    doc_key TEXT NOT NULL,
    page INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    rows INTEGER NOT NULL DEFAULT 0,
    read_at TEXT NOT NULL,
    PRIMARY KEY (doc_key, page)
);

CREATE TABLE IF NOT EXISTS page_ocr (
    doc_key TEXT NOT NULL,
    page INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    reader TEXT NOT NULL DEFAULT '',
    read_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (doc_key, page)
);

CREATE TABLE IF NOT EXISTS measure_new (
    new_id TEXT PRIMARY KEY,
    definition TEXT NOT NULL DEFAULT '',
    driver_node TEXT NOT NULL DEFAULT '',
    observations INTEGER NOT NULL DEFAULT 0,
    pages INTEGER NOT NULL DEFAULT 0,
    examples TEXT NOT NULL DEFAULT '',
    first_known_at TEXT NOT NULL DEFAULT ''
);
"""

MIGRATIONS = (("group_source", "TEXT NOT NULL DEFAULT ''"), ("group_check", "TEXT NOT NULL DEFAULT ''"),
              ("adjusted", "INTEGER NOT NULL DEFAULT 0"), ("period_source", "TEXT NOT NULL DEFAULT ''"),
              ("basis", "TEXT NOT NULL DEFAULT ''"), ("basis_source", "TEXT NOT NULL DEFAULT ''"),
              ("series_kind", "TEXT NOT NULL DEFAULT ''"),
              ("text_source", "TEXT NOT NULL DEFAULT ''"), ("value_kind", "TEXT NOT NULL DEFAULT ''"),
              ("is_total", "INTEGER NOT NULL DEFAULT 0"),
              # T-238 stage M: record types, declared new measures and the transcript fields
              ("record_type", "TEXT NOT NULL DEFAULT 'number'"), ("statement", "TEXT NOT NULL DEFAULT ''"),
              ("speaker", "TEXT NOT NULL DEFAULT ''"), ("direction", "TEXT NOT NULL DEFAULT ''"),
              # T-238 stage O: the question a short answer needs (the answer stays verbatim)
              ("question_context", "TEXT NOT NULL DEFAULT ''"),
              ("value_high", "REAL"), ("new_definition", "TEXT NOT NULL DEFAULT ''"),
              ("new_driver_node", "TEXT NOT NULL DEFAULT ''"))

# id, name, unit family, node in the T-228 driver tree
MEASURES: tuple[tuple[str, str, str, str], ...] = (
    ("capacity.total", "Total / operating capacity", "capacity", "capacity.add"),
    ("capacity.add", "Capacity added or planned", "capacity", "capacity.add"),
    ("capacity.utilisation", "Capacity utilisation", "percent", "revenue.volume"),
    ("capacity.growth_multiple", "Growth multiple (x) of capacity", "ratio", "capacity.add"),
    ("volume.sales", "Units or volume sold / handled", "count", "revenue.volume"),
    ("volume.production", "Units or volume produced", "count", "revenue.volume"),
    ("revenue.value", "Revenue", "money", "revenue.total"),
    ("revenue.price", "Realisation or price per unit", "money_per_unit", "revenue.price"),
    ("revenue.mix", "Revenue or volume split by segment / geography", "money", "revenue.mix"),
    ("mix.share", "Share of a mix (percent of revenue / volume)", "percent", "revenue.mix"),
    ("revenue_from_operations", "Revenue from operations", "money", "revenue.total"),
    ("total_income", "Total income", "money", "revenue.total"),
    ("total_expenses", "Total expenses", "money", "cost.other"),
    ("finance_cost", "Finance cost", "money", "debt.cost"),
    ("ebitda", "EBITDA", "money", "margin.ebitda"),
    ("profit_before_tax", "Profit before tax", "money", "none: below-EBITDA profit line"),
    ("pat", "Profit after tax", "money", "none: accounting result"),
    ("total_assets", "Total assets", "money", "none: balance-sheet line"),
    ("total_equity", "Total equity", "money", "none: balance-sheet line"),
    ("borrowings", "Borrowings", "money", "debt.level"),
    ("cash_and_cash_equivalents", "Cash and cash equivalents", "money", "none: balance-sheet line"),
    ("eps", "Earnings per share", "money_per_unit", "equity.shares"),
    ("ebitda_margin", "EBITDA margin", "percent", "margin.ebitda"),
    ("pat_margin", "PAT margin", "percent", "none: accounting result"),
    ("revenue_growth_yoy", "Revenue growth (YoY)", "percent", "revenue.total"),
    ("ebitda_per_kg", "EBITDA per kg", "money_per_unit", "margin.ebitda"),
    ("market.value", "Industry or market size (money)", "money", "none: market-level metric"),
    ("capex", "Capex", "money", "capex.amount"),
    ("capex.estimated", "Estimated capex", "money", "capex.amount"),
    ("inventories", "Inventories", "money", "working_capital.days"),
    ("trade_receivables", "Trade receivables", "money", "working_capital.days"),
    ("trade_payables", "Trade payables", "money", "working_capital.days"),
    ("provisions", "Provisions", "money", "none: balance-sheet line"),
    ("other_income", "Other income", "money", "revenue.total"),
    ("total_tax_expense", "Tax expense", "money", "none: tax line"),
    ("ebit", "EBIT", "money", "margin.ebitda"),
    ("lease_liabilities", "Lease liabilities", "money", "debt.level"),
    ("employee_benefits_expense", "Employee benefits expense", "money", "cost.employee"),
    ("depreciation_and_amortisation_expense", "Depreciation and amortisation", "money", "cost.other"),
    ("other_expenses", "Other expenses", "money", "cost.other"),
    ("other_equity", "Other equity", "money", "none: balance-sheet line"),
    ("equity_share_capital", "Equity share capital", "money", "none: balance-sheet line"),
    ("other_financial_liabilities", "Other financial liabilities", "money", "none: balance-sheet line"),
    ("other_current_liabilities", "Other current liabilities", "money", "none: balance-sheet line"),
    ("other_non_current_assets", "Other non-current assets", "money", "none: balance-sheet line"),
    ("other_current_assets", "Other current assets", "money", "none: balance-sheet line"),
    ("total_current_assets", "Total current assets", "money", "none: balance-sheet line"),
    ("total_non_current_assets", "Total non-current assets", "money", "none: balance-sheet line"),
    ("total_current_liabilities", "Total current liabilities", "money", "none: balance-sheet line"),
    ("total_non_current_liabilities", "Total non-current liabilities", "money", "none: balance-sheet line"),
    ("total_equity_and_liabilities", "Total equity and liabilities", "money", "none: balance-sheet total"),
    ("property_plant_and_equipment", "Property, plant and equipment", "money", "capex.amount"),
    ("capital_work_in_progress", "Capital work in progress", "money", "capex.amount"),
    ("right_to_use", "Right-of-use assets", "money", "capex.amount"),
    ("other_intangible_assets", "Other intangible assets", "money", "capex.amount"),
    ("non_current_assets", "Non-current assets", "money", "none: balance-sheet line"),
    ("current_assets", "Current assets", "money", "none: balance-sheet line"),
    ("non_current_liabilities", "Non-current liabilities", "money", "none: balance-sheet line"),
    ("current_liabilities", "Current liabilities", "money", "none: balance-sheet line"),
    ("gross_profit", "Gross profit", "money", "margin.gross"),
    ("count.rakes", "Number of rakes", "count", "revenue.volume"),
    ("pipeline.length", "Pipeline length", "length", "capacity.add"),
    ("order.intake", "Order intake / new orders", "money", "revenue.order_book"),
    ("order.quantity", "Order quantity (units ordered)", "count", "revenue.order_book"),
    ("order.book", "Order book", "money", "revenue.order_book"),
    ("market.size", "Industry or market size", "count", "none: market-level metric"),
    ("market.share", "Market share", "percent", "none: market-level metric"),
    ("count.plants", "Number of plants / facilities / terminals", "count", "capacity.add"),
    ("count.customers", "Number of customers / subscribers", "count", "revenue.volume"),
    ("logistics.throughput", "Port / logistics throughput", "count", "revenue.volume"),
    ("cash_flow.operating", "Net cash from operating activities", "money", "none: cash-flow line"),
    ("cash_flow.investing", "Net cash from investing activities", "money", "none: cash-flow line"),
    ("cash_flow.financing", "Net cash from financing activities", "money", "none: cash-flow line"),
    ("cash_flow.net_change", "Net change in cash", "money", "none: cash-flow line"),
    ("cash_generated_from_operations", "Cash generated from operations", "money", "none: cash-flow line"),
    ("changes_in_working_capital", "Changes in working capital", "money", "working_capital.days"),
    ("adjustment_for_non_operating_items", "Adjustment for non-operating items", "money", "none: cash-flow line"),
    ("direct_taxes_paid", "Direct taxes paid", "money", "none: cash-flow line"),
    ("deferred_tax", "Deferred tax", "money", "none: tax line"),
    ("current_tax", "Current tax", "money", "none: tax line"),
    ("deferred_tax_liabilities_net", "Deferred tax liabilities (net)", "money", "none: balance-sheet line"),
    ("current_tax_liabilities_net", "Current tax liabilities (net)", "money", "none: balance-sheet line"),
    ("current_tax_assets_net", "Current tax assets (net)", "money", "none: balance-sheet line"),
    ("other_bank_balances", "Other bank balances", "money", "none: balance-sheet line"),
    ("other_financial_assets", "Other financial assets", "money", "none: balance-sheet line"),
    ("loans", "Loans", "money", "none: balance-sheet line"),
    ("cost_of_goods_sold", "Cost of goods sold", "money", "cost.other"),
    ("cost_of_services", "Cost of services", "money", "cost.other"),
    ("raw_material_cost", "Raw material cost", "money", "cost.other"),
    ("exceptional_items", "Exceptional items", "money", "none: below-EBITDA profit line"),
    ("gp_percent", "Gross profit margin", "percent", "margin.gross"),
    ("gross_profit_margin", "Gross profit margin", "percent", "margin.gross"),
    ("pbt_margin", "PBT margin", "percent", "none: below-EBITDA profit line"),
    ("ebitda_growth_yoy", "EBITDA growth (YoY)", "percent", "margin.ebitda"),
    ("profit_growth_yoy", "Profit growth (YoY)", "percent", "none: accounting result"),
    ("pat_growth_yoy", "PAT growth (YoY)", "percent", "none: accounting result"),
    ("goodwill", "Goodwill", "money", "capex.amount"),
    ("product_weight_range", "Product weight range", "count", "revenue.volume"),
    ("distance_from_chennai", "Distance from Chennai", "length", "none: geography"),
    ("count.beneficiaries", "Beneficiaries", "count", "none: non-financial metric"),
    ("health_consultations", "Health consultations", "count", "none: non-financial metric"),
    ("iso_certification", "ISO certification", "count", "none: non-financial metric"),
    ("freight_rebate", "Freight rebate", "percent", "cost.other"),
    ("freight_rebate_duration", "Freight rebate duration", "time", "cost.other"),
    ("launch_year", "Launch year", "count", "none: non-financial metric"),
    ("market.growth", "Market growth", "percent", "none: market-level metric"),
    ("incremental_demand", "Incremental demand", "count", "none: market-level metric"),
    ("count.states", "Number of states", "count", "none: geographic footprint"),
    ("tree_plantations", "Trees planted", "count", "none: non-financial metric"),
    ("water_managed", "Water managed", "count", "none: non-financial metric"),
    ("gender_ratio", "Gender ratio", "ratio", "none: non-financial metric"),
    ("capex.investment", "Capex investment", "money", "capex.amount"),
    ("count.manufacturing_sections", "Manufacturing sections", "count", "capacity.add"),
    ("loans.disbursement", "Loan disbursements (flow)", "money", "none: lending flow"),
    ("loans.disbursement_mix", "Disbursements by segment / geography", "money", "none: lending flow"),
    ("loans.disbursement_share", "Share of disbursements (percent)", "percent", "none: lending flow"),
    ("capacity.spindles", "Spindles installed / planned", "count", "capacity.add"),
    ("order.book_growth_yoy", "Order book growth (YoY)", "percent", "revenue.order_book"),
    ("order.intake_growth_yoy", "Order intake growth (YoY)", "percent", "revenue.order_book"),
    ("aum.value", "Assets under management", "money", "none: asset stock, no tree node"),
    ("aum.growth_yoy", "AUM growth (YoY)", "percent", "none: asset stock, no tree node"),
    ("ebitda.delta", "EBITDA bridge step", "money", "margin.ebitda"),
    ("ebitda_margin.delta", "EBITDA margin bridge step", "percent", "margin.ebitda"),
    ("revenue.delta", "Revenue bridge step", "money", "revenue.total"),
    ("pat.delta", "PAT bridge step", "money", "none: accounting result"),
    ("revenue_growth_cagr", "Revenue CAGR over a span", "percent", "revenue.total"),
    ("ebitda_growth_cagr", "EBITDA CAGR over a span", "percent", "margin.ebitda"),
    ("pat_growth_cagr", "PAT CAGR over a span", "percent", "none: accounting result"),
    ("profit_growth_cagr", "Profit CAGR over a span", "percent", "none: accounting result"),
    ("gnpa_pct", "Gross NPA ratio", "percent", "cost.other"),
    ("gnpa.value", "Gross non-performing assets (amount)", "money", "cost.other"),
    ("nnpa_pct", "Net NPA ratio", "percent", "cost.other"),
    ("nnpa.value", "Net non-performing assets (amount)", "money", "cost.other"),
    ("pcr", "Provision coverage ratio", "percent", "cost.other"),
    ("casa", "CASA deposits", "money", "debt.level"),
    ("deposits", "Deposits", "money", "debt.level"),
    ("nim", "Net interest margin", "percent", "revenue.price"),
    ("cost_of_funds", "Cost of funds", "percent", "debt.cost"),
    ("yield_on_advances", "Yield on advances", "percent", "revenue.price"),
    ("net_interest_income", "Net interest income", "money", "revenue.total"),
    ("interest_income", "Interest income", "money", "revenue.total"),
    ("finance_income", "Finance income", "money", "revenue.total"),
    ("net_total_income", "Net total income", "money", "revenue.total"),
    ("average_ticket_size", "Average ticket size", "money", "none: loan ticket size, no tree node"),
    ("pre_provision_operating_profit", "Pre-provision operating profit", "money", "margin.ebitda"),
    ("cash_profit_margin", "Cash profit margin", "percent", "margin.ebitda"),
    ("cash_profit", "Cash profit", "money", "margin.ebitda"),
    ("collection_efficiency", "Collection efficiency", "percent", "none: collection recovery ratio"),
    ("credit_cost", "Credit cost", "percent", "cost.other"),
    ("crar", "Capital adequacy ratio (CRAR)", "percent", "none: regulatory capital ratio"),
    ("count.outlets", "Number of branches / outlets / touchpoints", "count", "capacity.add"),
    ("count.atms", "Number of ATMs", "count", "capacity.add"),
    ("sma_0", "SMA-0 book", "money", "cost.other"),
    ("sma_1", "SMA-1 book", "money", "cost.other"),
    ("sma_2", "SMA-2 book", "money", "cost.other"),
    ("npa_additions", "NPA additions in the period", "money", "cost.other"),
    ("opening_gross_npa_balance", "Opening gross NPA balance", "money", "cost.other"),
    ("order.bid_pipeline", "Bid pipeline / pipeline of potential projects", "money", "revenue.order_book"),
    ("order.executed", "Orders executed", "money", "revenue.order_book"),
    ("count.projects", "Number of projects", "count", "capacity.add"),
    ("count.projects_completed", "Projects completed (track record)", "count", "capacity.add"),
    ("capacity.under_construction", "Capacity under construction / planned", "capacity", "capacity.add"),
    ("ebitda_per_tonne", "EBITDA per tonne", "money_per_unit", "margin.ebitda"),
    ("value_addition_per_kg", "Value addition per kg", "money_per_unit", "revenue.price"),
    ("volume_growth_yoy", "Sales volume growth (YoY)", "percent", "revenue.volume"),
    ("import_dependency", "Import dependency", "percent", "cost.raw_material"),
    ("power_cost", "Power and fuel cost", "money", "cost.power_fuel"),
    ("land_area", "Land area", "area", "capacity.add"),
    ("crude_oil_price", "Crude oil price", "money_per_unit", "cost.raw_material"),
    ("count.stores", "Number of stores", "count", "capacity.add"),
    ("area.retail", "Retail / store area", "area", "capacity.add"),
    ("same_store_sales_growth", "Same-store sales growth", "percent", "revenue.total"),
    ("count.distributors", "Distributors / dealers / channel reach", "count", "capacity.add"),
    ("occupancy", "Occupancy", "percent", "revenue.volume"),
    ("deal.tcv", "Deal total contract value", "money", "revenue.order_book"),
    ("count.employees", "Employees / headcount", "count", "cost.employee"),
    ("attrition", "Attrition rate", "percent", "cost.employee"),
    ("anda.filed", "ANDAs filed", "count", "none: regulatory filing pipeline"),
    ("anda.approved", "ANDAs approved", "count", "none: regulatory approvals"),
    ("product.launches", "Product launches", "count", "revenue.volume"),
    ("rnd.expense", "R&D expense", "money", "cost.other"),
    ("rnd.share", "R&D as a share of revenue", "percent", "cost.other"),
    ("product.registrations", "Product registrations (MAs)", "count", "none: regulatory registrations"),
    ("plf", "Plant load factor", "percent", "revenue.volume"),
    ("generation.volume", "Power generation", "energy", "revenue.volume"),
    ("realestate.presales", "Pre-sales / sales value", "money", "revenue.total"),
    ("realestate.collections", "Collections", "money", "none: cash collection, no tree node"),
    ("area.sold", "Area sold / booked", "area", "revenue.volume"),
    ("area.unsold", "Area unsold", "area", "none: unsold inventory stock"),
    ("area.carpet", "Carpet area", "area", "capacity.add"),
    ("area.delivered", "Area delivered / handed over", "area", "revenue.volume"),
    ("area.under_construction", "Area under construction", "area", "capacity.add"),
    ("demand.peak", "Peak demand (power)", "capacity", "none: country/industry demand, no tree node"),
    ("water_intensity", "Water intensity", "ratio", "none: ESG intensity metric"),
    ("water_intensity_reduction", "Water intensity reduction", "percent", "none: ESG intensity metric"),
    ("energy_intensity", "Energy intensity", "ratio", "none: ESG intensity metric"),
    ("energy_intensity_reduction", "Energy intensity reduction", "percent", "none: ESG intensity metric"),
    ("investments", "Investments", "money", "none: balance-sheet line"),
    ("non_current_investments", "Non-current investments", "money", "none: balance-sheet line"),
    ("current_investments", "Current investments", "money", "none: balance-sheet line"),
    ("non_controlling_interest", "Non-controlling interest", "money", "none: accounting line"),
    ("total_comprehensive_income", "Total comprehensive income", "money", "none: accounting total"),
    ("other_comprehensive_income", "Other comprehensive income", "money", "none: accounting total"),
    ("other_non_current_liabilities", "Other non-current liabilities", "money", "none: balance-sheet line"),
    ("other_non_current_financial_assets", "Other non-current financial assets", "money", "none: balance-sheet line"),
    ("other_liabilities_and_provisions", "Other liabilities and provisions", "money", "none: balance-sheet line"),
    ("other_assets", "Other assets", "money", "none: balance-sheet line"),
    ("total_liabilities", "Total liabilities", "money", "none: balance-sheet total"),
    ("deferred_tax_assets_net", "Deferred tax assets (net)", "money", "none: balance-sheet line"),
    ("long_term_provisions", "Long-term provisions", "money", "none: balance-sheet line"),
    ("reserves_and_surplus", "Reserves and surplus", "money", "none: balance-sheet line"),
    ("intangible_assets_under_development", "Intangible assets under development", "money", "capex.amount"),
    ("long_term_loans_and_advances", "Long-term loans and advances", "money", "none: balance-sheet line"),
    ("short_term_loans_and_advances", "Short-term loans and advances", "money", "none: balance-sheet line"),
    ("changes_in_inventories", "Changes in inventories", "money", "cost.raw_material"),
    ("purchase_of_finished_goods", "Purchases of stock-in-trade", "money", "cost.raw_material"),
    ("excise_duty", "Excise duty", "money", "cost.other"),
    ("share_of_profit_of_jv_and_associates", "Share of profit of JV / associates", "money", "none: share of associates, below EBITDA"),
    ("employee_stock_option_outstanding", "Employee stock option outstanding", "money", "equity.shares"),
    ("operating_profit_before_working_capital_changes", "Operating profit before working-capital changes", "money", "margin.ebitda"),
    ("operating_expenses", "Operating expenses", "money", "cost.other"),
    ("cost_of_revenue", "Cost of revenues", "money", "cost.raw_material"),
    ("assets_held_for_sale", "Assets held for sale", "money", "none: balance-sheet line"),
    ("liabilities_classified_as_held_for_sale", "Liabilities classified as held for sale", "money", "none: balance-sheet line"),
    ("tax_provisions", "Tax provisions", "money", "none: tax liability"),
    ("investment_in_property", "Investment in property", "money", "none: balance-sheet line"),
    ("financial_asset", "Financial assets", "money", "none: balance-sheet line"),
    ("contract_assets_unbilled_wip", "Contract assets (unbilled WIP)", "money", "none: working-capital stock"),
    ("opening_cash_and_cash_equivalents", "Opening cash and cash equivalents", "money", "none: cash-flow line"),
    ("profit_before_exceptional_items_and_tax", "Profit before exceptional items and tax", "money", "none: below-EBITDA profit line"),
    ("tangible_net_worth", "Tangible net worth", "money", "none: balance-sheet total"),
    ("capital_employed", "Capital employed", "money", "none: balance-sheet total"),
    ("roe", "Return on equity", "percent", "none: return ratio"),
    ("roce", "Return on capital employed", "percent", "none: return ratio"),
    ("core_roce", "Core ROCE (company definition)", "percent", "none: return ratio"),
    ("net_debt", "Net debt", "money", "debt.level"),
    ("net_debt_equity", "Net debt to equity", "ratio", "debt.level"),
    ("net_debt_to_ebitda", "Net debt to EBITDA", "ratio", "debt.level"),
    ("debt_to_ebitda", "Debt to EBITDA (gross)", "ratio", "debt.level"),
    ("debt_equity", "Debt to equity", "ratio", "debt.level"),
    ("long_term_debt_equity", "Long-term debt to equity", "ratio", "debt.level"),
    ("interest_coverage_ratio", "Interest coverage ratio", "ratio", "debt.cost"),
    ("total_outside_liabilities_equity", "Total outside liabilities to total equity", "ratio", "debt.level"),
    ("current_ratio", "Current ratio", "ratio", "working_capital.days"),
    ("quick_ratio", "Quick ratio", "ratio", "working_capital.days"),
    ("working_capital_days", "Working capital days", "time", "working_capital.days"),
    ("inventory_days", "Inventory days", "time", "working_capital.days"),
    ("debtor_days", "Debtor days", "time", "working_capital.days"),
    ("payable_days", "Payable days", "time", "working_capital.days"),
    ("cash_conversion_cycle", "Cash conversion cycle", "time", "working_capital.days"),
    ("asset_turnover", "Asset turnover", "ratio", "none: efficiency ratio"),
    ("fixed_asset_turnover", "Fixed-asset turnover", "ratio", "none: efficiency ratio"),
    ("book_value_per_share", "Book value per share", "money_per_unit", "equity.shares"),
    ("cash_eps", "Cash EPS", "money_per_unit", "equity.shares"),
    ("ebit_margin", "EBIT margin", "percent", "margin.ebitda"),
    ("ebit_growth_yoy", "EBIT growth (YoY)", "percent", "margin.ebitda"),
    ("ebitda_margin_change_bps", "EBITDA margin change (bps)", "bps", "margin.ebitda"),
    ("pat_margin_change_bps", "PAT margin change (bps)", "bps", "none: PAT margin, below the EBITDA margin node"),
    ("eps_growth_yoy", "EPS growth (YoY)", "percent", "equity.shares"),
    ("tax_growth_yoy", "Tax expense growth (YoY)", "percent", "none: tax line"),
    ("depreciation_growth_yoy", "Depreciation growth (YoY)", "percent", "cost.other"),
    ("employee_cost_growth_yoy", "Employee cost growth (YoY)", "percent", "cost.employee"),
    ("finance_cost_growth_yoy", "Finance cost growth (YoY)", "percent", "debt.cost"),
    ("total_expenses_growth_yoy", "Total expenses growth (YoY)", "percent", "cost.other"),
    ("revenue_growth_qoq", "Revenue growth (QoQ)", "percent", "revenue.total"),
    ("total_comprehensive_income_growth_yoy", "Total comprehensive income growth (YoY)", "percent", "none: accounting total"),
    ("count.countries", "Number of countries", "count", "none: geographic footprint"),
    # T-230 stage K: driver measures the annual-report read named and the dictionary lacked (top-500 review:
    # D:/RealityEngine/t230/stageK_aliases.csv).  Governance / compliance / BRSR / actuarial names stay unmapped.
    ("other_operating_revenue", "Other operating revenue", "money", "revenue.total"),
    ("gross_block", "Gross block", "money", "capex.amount"),
    ("accumulated_depreciation", "Accumulated depreciation", "money", "capex.amount"),
    ("dividend_per_share", "Dividend per share", "money_per_unit", "equity.shares"),
    ("count.shares", "Equity shares outstanding", "count", "equity.shares"),
    ("dscr", "Debt service coverage ratio", "ratio", "debt.cost"),
    ("inventory_turnover", "Inventory turnover (x)", "ratio", "working_capital.days"),
    ("receivable_turnover", "Receivables turnover (x)", "ratio", "working_capital.days"),
    ("payable_turnover", "Payables turnover (x)", "ratio", "working_capital.days"),
    ("net_capital_turnover", "Net capital turnover (x)", "ratio", "none: efficiency ratio"),
    # T-238 stage N: the deck read's coined ids that name a real quantity, clustered by normalised name and kept
    # apart by the review guards (a level never merges with a change, a percent with money, a stock with a flow, a
    # value with a volume, yoy with qoq; different entities and share bases stay apart).  Governance / metadata names
    # (experience, rank, reference numbers, dates, ESG scores) stay unmapped -- see .tmp/t238n/stageN_aliases.csv.
    ("roa", "Return on assets", "percent", "none: return ratio"),
    ("other_income_growth_yoy", "Other income growth (YoY)", "percent", "revenue.total"),
    ("other_expenses_growth_yoy", "Other expenses growth (YoY)", "percent", "cost.other"),
    ("total_income_growth_yoy", "Total income growth (YoY)", "percent", "revenue.total"),
    ("gross_profit_growth_yoy", "Gross profit growth (YoY)", "percent", "margin.gross"),
    ("profit_before_tax_growth_yoy", "Profit before tax growth (YoY)", "percent", "none: below-EBITDA profit line"),
    ("pat_growth_qoq", "PAT growth (QoQ)", "percent", "none: accounting result"),
    ("ebitda_growth_qoq", "EBITDA growth (QoQ)", "percent", "margin.ebitda"),
    ("profit_before_tax_growth_qoq", "Profit before tax growth (QoQ)", "percent", "none: below-EBITDA profit line"),
    ("volume_growth_qoq", "Sales volume growth (QoQ)", "percent", "revenue.volume"),
    ("other_income_growth_qoq", "Other income growth (QoQ)", "percent", "revenue.total"),
    ("total_income_growth_qoq", "Total income growth (QoQ)", "percent", "revenue.total"),
    ("finance_cost_growth_qoq", "Finance cost growth (QoQ)", "percent", "debt.cost"),
    ("gross_margin_change_bps", "Gross margin change (bps)", "bps", "margin.gross"),
    ("shareholding_pct", "Shareholding pattern (share of equity capital)", "percent", "equity.shares"),
    ("ownership_stake_pct", "Ownership stake in a JV / associate / subsidiary", "percent", "none: investments"),
    ("dividend_payout_ratio", "Dividend payout ratio", "percent", "equity.shares"),
    ("dividend_paid", "Dividend paid", "money", "equity.shares"),
    ("face_value_per_share", "Face value per share", "money_per_unit", "equity.shares"),
    ("share_price", "Share price", "money_per_unit", "equity.shares"),
    ("count.cities", "Number of cities", "count", "none: geographic footprint"),
    ("count.districts", "Number of districts", "count", "none: geographic footprint"),
    ("count.villages", "Number of villages", "count", "none: geographic footprint"),
    ("count.schools", "Number of schools", "count", "none: geographic footprint"),
    ("count.products", "Number of products / SKUs", "count", "revenue.volume"),
    ("changes_in_receivables", "Changes in trade receivables (cash-flow change)", "money", "working_capital.days"),
    ("changes_in_payables", "Changes in trade payables (cash-flow change)", "money", "working_capital.days"),
    ("contract_duration", "Contract duration", "time", "revenue.order_book"),
    ("growth_multiple", "Growth over a printed span (x)", "ratio", "none: growth"),
)

# id -> unit family (stage G: the label-map unit guard reads this)
_MEASURE_FAMILY: dict[str, str] = {m[0]: m[2] for m in MEASURES}

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
    "order_size": "order.quantity",
    "order_quantity": "order.quantity",
    "units_ordered": "order.quantity",
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
    "advances": "loans",
    "area.carpet_total": "area.carpet",
    "area_sold": "area.sold",
    "area_unsold": "area.unsold",
    "area.carpet_delivered": "area.delivered",
    "area.construction_scope": "area.under_construction",
    "area.developed": "area.delivered",
    "area.development": "area.delivered",
    "area_construction_delivered": "area.delivered",
    "area_construction_total": "area.under_construction",
    "area_delivered": "area.delivered",
    "area_delivered_recognized_for_revenue": "area.delivered",
    "area_developed": "area.delivered",
    "carpet_area_delivered": "area.delivered",
    "construction_area": "area.under_construction",
    "construction_area_delivered": "area.delivered",
    "asset_turnover_ratio": "asset_turnover",
    "assets_classified_as_held_for_sale": "assets_held_for_sale",
    "book_value_per_share_ratio": "book_value_per_share",
    "cash_and_cash_equivalents_opening": "opening_cash_and_cash_equivalents",
    "change_in_inventories": "changes_in_inventories",
    "change_in_inventories_of_finished_goods_and_work_in_progress": "changes_in_inventories",
    "core_capital_employed": "capital_employed",
    "cost_of_deposits": "cost_of_funds",
    "cost_of_material_consumed": "raw_material_cost",
    "count.asset_focused_outlets": "count.outlets",
    "count.banking_outlets": "count.outlets",
    "count.banking_outlets_by_location": "count.outlets",
    "count.banking_outlets_by_state": "count.outlets",
    "count.branches": "count.outlets",
    "count.csc": "count.outlets",
    "count.liability_focused_outlets": "count.outlets",
    "count.rural_centers": "count.outlets",
    "creditors_days": "payable_days",
    "crude_oil_price_per_barrel": "crude_oil_price",
    "debt_equity_ratio": "debt_equity",
    "debt_to_equity": "debt_equity",
    "debtors_days_excluding_retention": "debtor_days",
    "debtors_days_including_retention": "debtor_days",
    "deferred_tax_assets": "deferred_tax_assets_net",
    "deposits.casa": "casa",
    "deposits.total": "deposits",
    "depreciation_and_amortisation_expense_growth_yoy": "depreciation_growth_yoy",
    "ebitda_margin_change_yoy": "ebitda_margin_change_bps",
    "ebitda_margin_change_yoy_bps": "ebitda_margin_change_bps",
    "employee_benefits_expense_growth_yoy": "employee_cost_growth_yoy",
    "employee_count": "count.employees",
    "employee_headcount": "count.employees",
    "energy_consumption_intensity_reduction": "energy_intensity_reduction",
    "energy_consumption_intensity_reduction_target": "energy_intensity_reduction",
    "eps_growth": "eps_growth_yoy",
    "fixed_asset_turnover_ratio": "fixed_asset_turnover",
    "fixed_assets": "property_plant_and_equipment",
    "gnpa": "gnpa.value",
    "gnpa_percent": "gnpa_pct",
    "gross_advances": "loans",
    "gross_non_performing_assets": "gnpa.value",
    "gross_npa": "gnpa.value",
    "gross_npa_percent": "gnpa_pct",
    "increase_decrease_in_stocks": "changes_in_inventories",
    "interest_coverage": "interest_coverage_ratio",
    "interest_expense": "finance_cost",
    "investment": "investments",
    "investments_accounted_for_using_the_equity_method": "investments",
    "long_term_debt_equity_ratio": "long_term_debt_equity",
    "minority_interest": "non_controlling_interest",
    "net_debt_ebitda": "net_debt_to_ebitda",
    "net_debt_to_equity": "net_debt_equity",
    "net_non_performing_assets": "nnpa.value",
    "net_profit": "pat",
    "net_worth": "total_equity",
    "nnpa": "nnpa.value",
    "nnpa_percent": "nnpa_pct",
    "non_controlling_interests": "non_controlling_interest",
    "operating_expense": "operating_expenses",
    "orders_executed": "order.executed",
    "other_borrowings": "borrowings",
    "other_current_financial_assets": "other_financial_assets",
    "outside_liab_equity": "total_outside_liabilities_equity",
    "pat_after_non_controlling_interest": "pat",
    "peak_demand": "demand.peak",
    "pat_margin_change_yoy": "pat_margin_change_bps",
    "pat_margin_change_yoy_bps": "pat_margin_change_bps",
    "pbit": "ebit",
    "product_registrations": "product.registrations",
    "profit_before_extraordinary_items_and_tax": "profit_before_exceptional_items_and_tax",
    "provision_coverage_ratio": "pcr",
    "purchases_of_stock_in_trade": "purchase_of_finished_goods",
    "return_on_capital_employed": "roce",
    "return_on_equity": "roe",
    "secured_borrowings": "borrowings",
    "share_of_profit_loss_from_jv": "share_of_profit_of_jv_and_associates",
    "share_of_profit_loss_from_jv_associates": "share_of_profit_of_jv_and_associates",
    "share_of_profit_loss_of_associate": "share_of_profit_of_jv_and_associates",
    "share_of_profit_loss_of_jce_net_of_tax": "share_of_profit_of_jv_and_associates",
    "share_of_profit_loss_of_jv": "share_of_profit_of_jv_and_associates",
    "share_of_profit_of_joint_venture": "share_of_profit_of_jv_and_associates",
    "short_term_borrowings": "borrowings",
    "tax_expense_growth_yoy": "tax_growth_yoy",
    "total_asset_turnover": "asset_turnover",
    "total_asset_turnover_ratio": "asset_turnover",
    "total_carpet_area": "area.carpet",
    "total_outside_liabilities_to_total_equity": "total_outside_liabilities_equity",
    "valuation_rate": "revenue.price",
    "volume.sales_growth_yoy": "volume_growth_yoy",
    "water_consumption_intensity_reduction": "water_intensity_reduction",
    "water_consumption_intensity_reduction_target": "water_intensity_reduction",
    "water_intensity_limit": "water_intensity",
    "water_intensity_vs_statutory_limit": "water_intensity",
    "statutory_water_intensity_limit": "water_intensity",
    # T-230 stage K: annual-report invented ids that mean a dictionary measure.  Only same-meaning maps; the
    # governance / compliance / BRSR / actuarial names of the top-500 review are deliberately absent.
    "interest_cost": "finance_cost",
    "purchases": "purchase_of_finished_goods",
    "net_profit_ratio": "pat_margin",
    "operating_profit_margin": "ebit_margin",
    "property_plant_and_equipment_additions": "capex",
    "net_block": "property_plant_and_equipment",
    "employee_turnover_rate": "attrition",
    "return_on_net_worth": "roe",
    "inventory_turnover_ratio": "inventory_turnover",
    "trade_receivables_turnover_ratio": "receivable_turnover",
    "debtors_turnover": "receivable_turnover",
    "trade_payables_turnover_ratio": "payable_turnover",
    "net_capital_turnover_ratio": "net_capital_turnover",
    "debt_service_coverage_ratio": "dscr",
    "equity_shares_outstanding": "count.shares",
    "count_of_shares": "count.shares",
    "count.permanent_employees": "count.employees",
    # T-238 stage N: the deck read's coined ids that name a dictionary measure (guards: a percent id is never
    # mapped into a money measure and vice versa; a change id never into its stock; the base of a share is kept).
    "equity_shares": "count.shares",
    "equity.shares": "count.shares",
    "equity.shares_outstanding": "count.shares",
    "equity.shares.outstanding": "count.shares",
    "shares_outstanding": "count.shares",
    "count_of_equity_shares": "count.shares",
    "revenue_mix": "revenue.mix",
    "revenue.mix_share": "revenue.mix",
    "roa_pct": "roa",
    "return_on_assets": "roa",
    "return_on_assets_pct": "roa",
    "pbt_growth_yoy": "profit_before_tax_growth_yoy",
    "profit_before_tax_growth": "profit_before_tax_growth_yoy",
    "pbt_growth_qoq": "profit_before_tax_growth_qoq",
    "profit_growth_qoq": "profit_before_tax_growth_qoq",
    "pat_growth_qoq_pct": "pat_growth_qoq",
    "ebitda_growth_qoq_pct": "ebitda_growth_qoq",
    "volume_growth_qoq_pct": "volume_growth_qoq",
    "other_income_growth": "other_income_growth_yoy",
    "other_expenses_growth": "other_expenses_growth_yoy",
    "total_income_growth": "total_income_growth_yoy",
    "gross_profit_growth": "gross_profit_growth_yoy",
    "gross_profit_margin_change_bps": "gross_margin_change_bps",
    "shareholding_percentage": "shareholding_pct",
    "shareholding_share": "shareholding_pct",
    "shareholding.share": "shareholding_pct",
    "shareholding": "shareholding_pct",
    "ownership_stake": "ownership_stake_pct",
    "ownership_share": "ownership_stake_pct",
    "ownership.share": "ownership_stake_pct",
    "dividend.payout_ratio": "dividend_payout_ratio",
    "dividend_payout_pct": "dividend_payout_ratio",
    "equity_share_face_value": "face_value_per_share",
    "face_value": "face_value_per_share",
    "contract.duration": "contract_duration",
}

# Curated printed label -> measure id (T-230 stage B, Wolf): applied by the script before the dictionary check.
# Exact match after lower-casing, whitespace collapsing and dropping a leading list mark ("(ii)", "a)", "3.").
_SCRIPT_LABEL_MARK = re.compile(r"^\s*(?:\([ivxlcdm]+\)|\([a-zA-Z]\)|[ivxlcdm]+\)|[a-zA-Z]\)|\d+[.)])\s+", re.I)
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
    "aum": "aum.value",
    "branches": "count.outlets",
    "capital work in progress": "capital_work_in_progress",
    "capital work-in-progress": "capital_work_in_progress",
    "area delivered": "area.delivered",
    "area under construction": "area.under_construction",
    "carpet area": "area.carpet",
    "china va over index rm (on 12 mic) - $/kg": "value_addition_per_kg",
    "cogs": "cost_of_goods_sold",
    "cost of revenues": "cost_of_revenue",
    "crar": "crar",
    "credit cost": "credit_cost",
    "crude oil - $/barrel": "crude_oil_price",
    "debt to equity": "debt_equity",
    "debt to equity ratio": "debt_equity",
    "debt-to-equity ratio": "debt_equity",
    "deferred tax assets": "deferred_tax_assets_net",
    "deferred tax assets (net)": "deferred_tax_assets_net",
    "depreciation": "depreciation_and_amortisation_expense",
    "depreciation & amortization": "depreciation_and_amortisation_expense",
    "depreciation and amortization": "depreciation_and_amortisation_expense",
    "disbursement": "loans.disbursement",
    "disbursements": "loans.disbursement",
    "employee cost": "employee_benefits_expense",
    "employee expenses": "employee_benefits_expense",
    "employees": "count.employees",
    "fixed assets": "property_plant_and_equipment",
    "fixed assets(net)": "property_plant_and_equipment",
    "gnpa": "gnpa_pct",
    "gross debt": "borrowings",
    "gross npa": "gnpa_pct",
    "gross npas at the end of period/year": "gnpa_pct",
    "gross revenue": "revenue.value",
    "income from operations": "revenue_from_operations",
    "inventory": "inventories",
    "net debt equity ratio": "net_debt_equity",
    "net debt/equity ratio (x)": "net_debt_equity",
    "net npa": "nnpa_pct",
    "net npas at the end of period/year": "nnpa_pct",
    "net profit": "pat",
    "net sales": "revenue.value",
    "net worth": "total_equity",
    "networth": "total_equity",
    "nnpa": "nnpa_pct",
    "occupancy": "occupancy",
    "operating revenue": "revenue_from_operations",
    "operational revenue": "revenue_from_operations",
    "peak demand": "demand.peak",
    "peak demand (gw)": "demand.peak",
    "peak demand (mw)": "demand.peak",
    "pcl va* (consol-all films) - $/kg": "value_addition_per_kg",
    "production": "volume.production",
    "reserves & surplus": "other_equity",
    "reserves and surplus": "other_equity",
    "revenues": "revenue.value",
    "sales revenue": "revenue.value",
    "share capital": "equity_share_capital",
    "staff cost": "employee_benefits_expense",
    "tax": "total_tax_expense",
    "team strength": "count.employees",
    "total expenditure": "total_expenses",
    "water intensity": "water_intensity",
    "energy intensity": "energy_intensity",
    "with a carpet area of": "area.carpet",
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
PERIOD_KINDS = ("actual", "estimate", "target", "span", "instant")
STAGES = ("operating", "under_construction", "approved", "under_review", "potential")
DIMS = ("segment", "product", "geography", "plant", "customer")

# unit text -> family, first match wins
UNIT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("bps", r"\bbps\b|\bbasis points?\b"),
    ("percent", r"%|percent\b|pct\b"),
    ("money_per_unit", r"(?:rs|inr|\u20b9|\$|usd|us\$)[^a-z]*(?:per\b|/)|/ ?(?:tonne|ton|unit|km|kg|mt|share)\b|"
                       r"(?:^|\s)per (?:share|unit|tonne|ton|kg|km|mt)\b|arpu|arr\b|revpar|realis|realiz"),
    ("energy", r"\bmus?\b|\bmwh\b|\bgwh\b|\bkwh\b|\bbu\b|\bmu\b|\bmn units?\b|\bmillion units?\b|"
               r"\bbn units?\b|\bbillion units?\b"),
    ("count", r"\bunits?\b|\bnos\b|\bnumbers?\b|\bthousands?\b|\bteus?\b|\bvehicles?\b|\btractors?\b|"
              r"\bcustomers?\b|\bsubscribers?\b|\bplants?\b|\bterminals?\b|\binstances?\b|"
              r"\blitres?\b|\bliters?\b|\bltrs?\b"),
    ("capacity", r"\bmtpa\b|\bmmtpa\b|\btpa\b|\btpd\b|\btonnes?\b|\btons?\b|\bmt\b|\bmw\b|\bgw\b|\bkw\b"),
    ("length", r"\bkm\b|kilomet(?:er|re)s?\b|\bmiles?\b"),
    ("area", r"\bsft\b|sq\.? ?ft|square feet|\bsqm\b|\bhectares?\b|\bacres?\b"),
    ("money", r"rs\b|inr\b|\u20b9|rupees?\b|crores?\b|\bcrs?\b|\bcr\b|lakhs?\b|lacs?\b|millions?\b|\bmn\b|"
              r"billions?\b|\bbn\b|usd\b|us\$|\$|euros?\b|eur\b"),
    ("time", r"\bdays?\b|\bmonths?\b|\byears?\b"),
    ("ratio", r"^x$|\btimes\b|\bmultiple\b"),
)
CONVERT_FAMILY = {"capacity": {"count"}, "count": {"capacity"}, "money_per_unit": {"money"},
                  "percent": {"bps"}}

FOOTNOTE_LABEL = re.compile(r"^\s*(?:\*|#|note\b|source\b|footnote\b)", re.I)
JUNK_MEASURE = re.compile(
    r"^(?:page|phone|telephone|mobile|fax|postal|pin|address|street|floor|tower|sector|plot|registration|"
    r"regulation|cin|din|scrip|signature|date|award|certification|website|email|gst|pan|reporting|"
    # T-238 stage M: the letterhead/date span the transcript reader coins as NEW ids
    r"digital|letter|call|meeting|document|calendar|time|period|quarter|year|financial|fy|q[1-4]|ref|"
    r"registered|corporate|membership|stock)"
    r"(?:[._][a-z0-9]+)*$", re.I)
LAKH_CRORE_RE = re.compile(r"\b(?:lakhs?|lacs?)\s*(?:crores?|crs?|cr)\b", re.I)
SCALE_WORDS = ((r"thousands?", 1e3), (r"'000|000s", 1e3), (r"\blakhs?\b|\blacs?\b", 1e5),
               (r"\bcrores?\b|\bcrs?\b|\bcr\.", 1e7), (r"\bmillions?\b|\bmn\b|\bmm\b", 1e6),
               (r"\bbillions?\b|\bbn\b", 1e9),
               (r"\btrillions?\b|(?:rs\.?|inr|\u20b9|\$|usd|us\$)\s*(?:in\s*)?\btn\b", 1e12))

# columns that go into the observation row from one model reply object
ROW_TEXT_KEYS = ("measure", "printed_label", "printed_axis", "unit", "period", "segment", "product",
                 "geography", "plant", "customer", "group_path", "series_id", "series_title", "entity_scope")


def norm_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


UNICODE_DASH_RE = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")


def norm_match(text: Any) -> str:
    """Whitespace-collapsed text with every Unicode dash/hyphen read as '-', for printed-label matching.

    Stage I: a PDF prints "Total Non‐Current Liabilities" with U+2010 while the model writes an ASCII hyphen
    (id 527), so the verbatim-label gate never matched.  NBSP is already covered by ``\\s``.
    """
    return norm_space(UNICODE_DASH_RE.sub("-", str(text or "")))


def text_has(text: str, needle: str) -> bool:
    """``needle`` occurs in ``text`` as a printed token, not inside a longer number ('30' is not in '2030')."""
    n = norm_match(needle)
    if not n:
        return False
    return re.search(r"(?<![\d.,])" + re.escape(n) + r"(?![\d.,])", norm_match(text)) is not None


def canonical_new_measure(measure: str) -> str:
    """``NEW:<id>`` / ``NEW: <ID>`` -> ``NEW:id``: the reader often copies the prompt's placeholder brackets."""
    measure = norm_space(measure)
    if not measure.lower().startswith(NEW_PREFIX.lower()):
        return measure
    new_id = measure[len(NEW_PREFIX):].strip().strip("<>").strip().lower()
    new_id = re.sub(r"[^a-z0-9_.]+", "_", new_id).strip("_.")
    return NEW_PREFIX + new_id


def junk_measure(measure: str) -> bool:
    """True for a letterhead/contact/date id (a NEW id is judged on its bare name, never on the NEW: prefix)."""
    bare = canonical_new_measure(measure)
    if bare.startswith(NEW_PREFIX):
        bare = bare[len(NEW_PREFIX):]
    return JUNK_MEASURE.match(bare) is not None


VALUE_HEAD_RE = re.compile(r"^(?:₹|rs\.?|inr|usd|us\$|\$|€)\s*", re.I)
VALUE_TAIL_RE = re.compile(r"\s*(?:%|\+|plus|-plus|bps)$", re.I)


def value_forms(value_text: str) -> list[str]:
    """The forms of a printed value a page may carry: as written, and without its currency / % / '+' marker."""
    text = norm_space(value_text)
    forms = [text]
    bare = VALUE_TAIL_RE.sub("", VALUE_HEAD_RE.sub("", text)).strip()
    if bare and bare != text:
        forms.append(bare)
    return forms


def value_printed(text: str, value_text: str) -> bool:
    return any(text_has(text, form) for form in value_forms(value_text))


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
    if LAKH_CRORE_RE.search(str(text or "")):
        return 1e12                  # T-241: "lakh crore" is one scale, not lakh and crore at once
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
    if infer_unit_family(row.get("unit", "")) in ("percent", "ratio", "time", "money_per_unit"):
        return 1.0, []               # a percentage / multiple / duration / per-unit price is never crore or thousand
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
              "lacs": 1e5, "million": 1e6, "mn": 1e6, "billion": 1e9, "bn": 1e9, "tn": 1e12,
              "trillion": 1e12}
PERIOD_PATTERNS = (
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b", re.I),
    re.compile(r"\b(?:Q[1-4]|H[12]|9M|FY)\s?-?\d{2,4}[A-Z]?\b", re.I),
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s-]?\d{2,4}\b", re.I),
    re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"),
    re.compile(r"\b(?:19|20)\d{2}-\d{2}\b"),
)
# Stage I: words a column can be headed with that name a comparison, never a period (Wolf read 394, ids 12734).
# Stage M: a transcript's prose ("currently", "this quarter", "corresponding quarter last year") is not a period either.
NOT_A_PERIOD_RE = re.compile(
    r"^(?:y[- ]?o[- ]?y|q[- ]?o[- ]?q|y[- ]?t[- ]?d|yoy|qoq|ytd|cagr|growth|growth\s*%?|%|vs\.?|versus|"
    r"present|current|currently|previous|prior|absolute|change|total|this|next|last|sequential|today|now|"
    r"later|early|recently|year[- ]on[- ]year|quarter[- ]on[- ]quarter|"
    r"(?:this|last|next|previous|current|corresponding|prior|same)\s+(?:year|quarter|month|period)\b.*)$", re.I)


def period_is_printed(period: str) -> bool:
    """False for a comparison word stored as a period ("Y-O-Y", "QoQ", "growth"); empty is no period at all."""
    return NOT_A_PERIOD_RE.match(norm_space(period).strip(" .:;,")) is None


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


def _label_unit_fits(measure: str, unit: str) -> bool:
    """Stage G: a printed-label map applies only when the printed unit's family fits the measure."""
    family = _MEASURE_FAMILY.get(measure, "")
    unit_family = infer_unit_family(unit)
    return not unit_family or family_ok(family, unit_family)


EXCEPTIONAL_RE = re.compile(r"\b(?:exceptional|extraordinary|one[- ]?off)\b", re.I)
CASHFLOW_CHANGE_RE = re.compile(r"\b(?:change[sd]?|increase|decrease|movement|addition|additions)\b", re.I)
RECEIVABLE_WORD_RE = re.compile(r"receivable|debtors?\b", re.I)
PAYABLE_WORD_RE = re.compile(r"payable|creditors?\b", re.I)
# T-238 stage N2: the size of an order won is a quantity ordered, never the company's sales volume (JWL).
ORDER_QTY_RE = re.compile(
    r"\b(?:wagons?|units? ordered|ordered|order (?:for|of)|manufacturing and supply of|supply of)\b", re.I)
ORDER_SALES_RE = re.compile(r"\b(?:sold|sales|dispatched|delivered|billed|shipped|supplied)\b", re.I)


def force_fit_veto(measure: str, label: str, axis: str, series_title: str) -> str:
    """T-238 stage N: a pre-exceptional profit is never plain PBT; a cash-flow change is never the balance.

    Wolf's hand grade (D:/RealityEngine/t237/measure_grade) caught hy4 force-fitting "Profit before exceptional
    items" into ``profit_before_tax`` (4 rows) and a cash-flow "change in trade receivables/payables" into the
    balance-sheet stock (3 rows, receivables/payables swapped).  The printed words say which line it is, so the
    script rewrites the id; the dictionary carries both the level and the change.

    N2: "manufacturing and supply of 697 ... Wagons" under a secured contract is an order quantity, and a volume
    row that also prints sold/dispatched/shipped is a real sales volume and keeps ``volume.sales``.
    """
    text = " ".join([label, axis, series_title])
    if measure == "profit_before_tax" and EXCEPTIONAL_RE.search(text):
        return "profit_before_exceptional_items_and_tax"
    if measure in ("trade_receivables", "trade_payables") and CASHFLOW_CHANGE_RE.search(text):
        if RECEIVABLE_WORD_RE.search(text):
            return "changes_in_receivables"
        if PAYABLE_WORD_RE.search(text):
            return "changes_in_payables"
    if measure_root(measure) == "volume" and ORDER_QTY_RE.search(text) and not ORDER_SALES_RE.search(text):
        return "order.quantity"
    return measure


def canonical_measure(measure: str, label: str, axis: str, series_title: str, unit: str,
                      page_text: str) -> str:
    """Stage C3: near-duplicate ids, disbursement vs loans stock, spindle counts under capex."""
    measure = canonical_new_measure(norm_space(measure))       # T-238: NEW:<id> -> NEW:id
    measure = MEASURE_ALIASES.get(measure, measure)
    scripted = script_measure(label)
    if scripted and _label_unit_fits(scripted, unit):
        measure = scripted
    context = " ".join([label, axis, series_title])
    if DISBURSEMENT_RE.search(context):
        if "%" in (unit or "") or "share" in context.lower():
            measure = "loans.disbursement_share"
        else:
            measure = "loans.disbursement_mix" if "mix" in context.lower() else "loans.disbursement"
    if measure_root(measure) == "capex" and not unit and SPINDLE_RE.search(page_text or ""):
        measure = "capacity.spindles"
    return force_fit_veto(measure, label, axis, series_title)


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
    r"(M|Mn|Mio|Million|MM|Cr|Crore|Crores|Crs|Lakh|Lakhs|Lac|Lacs|Bn|Billion|Tn|Trillion|'000|Thousand)\b", re.I)
IN_SCALE_RE = re.compile(
    r"\b(?:in|amount in|fig(?:ure)?s? in)\s+(?:₹|Rs\.?|INR|USD|US\$|\$)?\s*"
    r"(M|Mn|Mio|Million|MM|Cr|Crore|Crores|Crs|Lakh|Lakhs|Lac|Lacs|Bn|Billion|Tn|Trillion|'000|Thousand)\b", re.I)
D_SCALE = {"m": 1e6, "mn": 1e6, "mio": 1e6, "million": 1e6, "mm": 1e6, "cr": 1e7, "crore": 1e7,
           "crores": 1e7, "crs": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "bn": 1e9,
           "billion": 1e9, "tn": 1e12, "trillion": 1e12, "'000": 1e3, "thousand": 1e3}
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

# --------------------------------------------------------------------------- stage H script rules
#
# Wolf's visual audit (D:/RealityEngine/t230/wolf_visual_audit.md) graded 24 deck pages by picture type: recall is
# 93-98% on every type, precision is not.  The rules below are the script half of the fix; the prompt carries the
# other half (never estimate an unprinted bar, one series per map panel, a stack segment is a part, a rank is not a %).

DELTA_TO_LEVEL = {"ebitda.delta": "ebitda", "ebitda_margin.delta": "ebitda_margin",
                  "revenue.delta": "revenue.value", "pat.delta": "pat"}
MAP_MIN_PLACES = 5              # rows with >=5 distinct geographies on one page are a map call-out list
MAP_CALLOUT_GAP = 14.0          # points; reference_geom's label gap: max(14.0, 1.5 * word height)
BY_PLACE_RE = re.compile(r"by_(?:state|states|location|locations|geography|region|district)$", re.I)
TOP_N_RE = re.compile(r"\btop\s+(\d+)\b", re.I)
PERCENT_MEASURE_RE = re.compile(r"(?:^|\.)(?:share|mix)|_share$|_pct$|_margin$|margin$", re.I)
CAGR_AFTER_VALUE_RE = r"[^\n]{0,4}\bCAGR\b"

# --------------------------------------------------------------------------- stage I script rules
#
# Wolf's first read of the new-company decks (D:/RealityEngine/t232/wolf_read_decks394_a.md) graded 50 rows: the
# stage-H rules do not all generalise.  A per-unit figure took the table's crore scale (974, 20613), the axis-tick
# rule fired on statement tables (27274), a comparison word ("Y-O-Y") was stored as a period (12734), "lakh sq ft"
# read as money and "billion units" as a count (18095, 7916), a Unicode hyphen broke the label gate (527), and a
# threshold ("crossed Rs 35 Cr") verified as the reported figure (18288).

STATEMENT_SERIES_RE = re.compile(
    r"balance\s*-?\s*sheet|profit\s*(?:&|and)\s*loss|statement\s+of\s+(?:profit|cash|changes)|"
    r"cash\s*-?\s*flow|financial\s+statements?|particulars", re.I)
LOWER_BOUND_RE = re.compile(r"\bcrossed\b", re.I)
LOWER_BOUND_TAIL_RE = re.compile(
    r"(?:\bmore than|\bexceeds?|\bexceeding|\bin excess of|\bover|\babove)\s+"
    r"(?:(?:rs\.?|inr|\u20b9|\$|usd|us\$)\s*)?[\d.,]+\s*(?:%|pp|cr|crores?|crs?|lakhs?|mn|bn|million|"
    r"billion|gw|mw|mt|units?)?\s*$", re.I)
FOOTNOTE_BASIS_RE = re.compile(
    r"\b(?:figures?|numbers?|financials?|results?)\b[^.\n]{0,40}?\b(?:are|is|were|have\s+been)?\s*"
    r"(?:on\s+)?(?:a\s+)?(standalone|consolidated)\b", re.I)
MARKET_CAP_RE = re.compile(r"market\s*cap", re.I)


def is_statement_table(row: dict[str, Any], text: str) -> bool:
    """Stage I: a statement/table page or one of its rows is a printed label-and-columns table, not a chart axis."""
    return bool(statement_page_reason(text)) or \
        STATEMENT_SERIES_RE.search(" ".join([row.get("series_title") or "",
                                             row.get("printed_axis") or ""])) is not None


def lower_bound_kind(row: dict[str, Any]) -> str:
    """Stage I: "crossed Rs X", "over Rs X", "more than", "exceeds" print a threshold, never the actual level.

    The cue must be on the row's own label and bind to the value: "crossed ..." names a threshold, and
    "more than / over / exceeds <number>" only when the value ends the label ("over Rs. 40,000 Cr"); a cue
    inside a longer sentence ("bank balances other than above", "more than doubled to 816.89") is not a
    bound on this figure.  The deck's "Crossed revenue milestone of ..." is the class Wolf flagged (id 18288).
    """
    label = row.get("printed_label") or ""
    if LOWER_BOUND_RE.search(label) or LOWER_BOUND_TAIL_RE.search(label):
        return "lower_bound"
    return ""


def footnote_basis(page_text: str, period: str) -> str:
    """Stage I: a footnote naming one period's basis overrides the page basis for that period (id 20120).

    "FY23 & FY24 financial numbers are on Standalone basis" applies to the FY24 column and not to FY25's
    consolidated one, which a page-wide ``detect_basis`` cannot tell apart.
    """
    match = FY_LABEL_RE.search(period or "")
    years = {int(match.group(1)) % 100} if match else set()
    if not years:
        month_year = re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s-]?(\d{2,4})\b",
                               period or "", re.I)
        if month_year:
            years = {int(month_year.group(1)) % 100}
    if not years:
        return ""
    for line in str(page_text or "").splitlines():
        found = FOOTNOTE_BASIS_RE.search(line)
        if not found:
            continue
        line_years = {int(year) % 100 for year in FY_LABEL_RE.findall(line)}
        line_years |= {int(year) % 100 for year in re.findall(r"\b(20\d{2})\b", line)}
        if line_years & years:
            return found.group(1).lower()
    return ""


# T-238 stage N2 scope cues.  A figure whose heading names a country / industry / market, or a named client,
# customer or project, is never the company's own measure.
MARKET_SCOPE_RE = re.compile(r"\b(?:peak demand|market size|industry (?:size|demand|volume)|tam)\b", re.I)
COUNTRY_SCOPE_RE = re.compile(r"\bIndia\b|\bdomestic\b|\bBharat\b", re.I)
CLIENT_CUE_RE = re.compile(
    r"(?:[Cc]lient\s*:\s*|[Cc]ustomer\s*:\s*|[Oo]rders?\s+from\s+|[Cc]ontract\s+(?:[Ww]ith|[Ff]rom)\s+|"
    r"[Aa]warded\s+[Bb]y\s+)"
    r"((?:[A-Z][\w&.'-]*)(?:\s+(?:[A-Z][\w&.'-]*|of|and|&)){0,5})")
CLIENT_AWARDS_RE = re.compile(
    r"^\s*((?:[A-Z][\w&.'-]*)(?:\s+(?:[A-Z][\w&.'-]*|of|and|&)){0,4})\s+awards?\b")
PROJECT_CUE_RE = re.compile(r"\b(?:projects?|schemes?|missions?|yojana|kshetra|development)\b", re.I)
ORDERBOOK_PAGE_RE = re.compile(r"\border\s*book\b", re.I)


def client_name(text: str) -> str:
    """The client/customer a printed heading names ("2 Orders from Nesco Limited" -> 'Nesco Limited')."""
    match = CLIENT_CUE_RE.search(str(text or "")) or CLIENT_AWARDS_RE.search(str(text or ""))
    if not match:
        return ""
    name = norm_space(match.group(1)).strip(" .,;:-")
    return name if len(name) >= 3 else ""


def scope_cue(row: dict[str, Any], page_text: str = "") -> str:
    """Stage I/N2: a market, country or client figure is never the company's own measure.

    A market-size / peak-demand figure is country scope when the page names India, else industry.  A heading that
    names a client or customer is customer scope, and a project named on an order-book case-study page is the
    client's project, not the company's own asset (REPL's 1023 acres).
    """
    hay = " ".join([row.get("printed_label") or "", row.get("printed_axis") or "",
                    row.get("series_title") or "", row.get("group_path") or ""])
    root = measure_root(row.get("measure", ""))
    if root in ("market", "demand") or MARKET_SCOPE_RE.search(hay):
        if MARKET_CAP_RE.search(row.get("printed_label") or ""):
            return ""
        current = canonical_scope(row.get("entity_scope") or "")
        if COUNTRY_SCOPE_RE.search(hay):
            return "" if current == "country" else "country"   # the row's own heading names the country
        if current in ("country", "industry"):
            return ""          # the reader/page already scoped it at market level: keep that scope
        return "industry"
    client_hay = " | ".join([row.get("series_title") or "", row.get("printed_label") or "",
                             row.get("printed_axis") or "", row.get("group_path") or ""])
    if client_name(client_hay):          # the series/heading names the client, so read it first
        return "customer"
    if PROJECT_CUE_RE.search(hay) and ORDERBOOK_PAGE_RE.search(str(page_text or "")):
        return "customer"           # an order-book case study describes the client's project, not company land
    return ""


def apply_per_unit_scale(row: dict[str, Any], measure_family: str) -> bool:
    """Stage I: EPS, Rs/kWh, Rs/unit ... never take a crore/lakh/million scale (ids 974, 20613)."""
    if measure_family != "money_per_unit":
        return False
    try:
        scale = float(row.get("scale") or 1)
    except (TypeError, ValueError):
        scale = 1.0
    if scale == 1:
        return False
    row["scale"] = 1.0
    return True


def labels_match(row: dict[str, Any], text: str, ocr_text: str = "") -> bool:
    """The row's printed label/axis/group is in the page text once Unicode dashes read as '-' (stage I, id 527)."""
    hay = norm_match(str(text or "") + "\n" + str(ocr_text or ""))
    for field in ("printed_label", "printed_axis", "group_path"):
        value = str(row.get(field) or "")
        if not value:
            continue
        parts = value.split(" > ") if field == "group_path" else [value]
        if any(part and norm_match(part) not in hay for part in parts):
            return False
    return True


TOTAL_LABEL_RE = re.compile(r"^(?:(?:grand|overall|consolidated)\s+)?total\b|\btotal\s*$|^overall\b", re.I)


def derive_is_total(row: dict[str, Any]) -> bool:
    """Stage J: the stored total flag, else a printed "Total"/"Overall"/"Consolidated total" label.

    ``apply_parts_sum`` can only prove a printed total it is told about; a recheck used to lose that proof
    because the flag lived only in the model reply (144 rows).  The label derivation also re-marks the
    totals of rows read before the column existed.
    """
    if row.get("is_total"):
        return True
    label = norm_space(row.get("printed_label"))
    return bool(label) and TOTAL_LABEL_RE.search(label) is not None


def _numbers_in(line: str) -> list[float]:
    numbers: list[float] = []
    for token in re.findall(r"(?<![\w.])\(?\d[\d,]*\.?\d*\)?%?", line):
        try:
            numbers.append(float(token.replace(",", "").strip("()%").rstrip(".")))
        except ValueError:
            continue
    return numbers


TICK_LADDER_MIN = 5            # stage J: four adjacent data values can be a coincidence (0.20/0.21/0.22/0.23)


def _tick_ladder(numbers: list[float]) -> bool:
    """An evenly spaced axis ladder: >=5 numbers with a constant step (0, 1,000, 2,000, 3,000 ...)."""
    if len(numbers) < TICK_LADDER_MIN:
        return False
    ordered = sorted(numbers)
    steps = [b - a for a, b in zip(ordered, ordered[1:])]
    if not steps or steps[0] <= 0:
        return False
    return all(abs(step - steps[0]) <= max(1e-9, abs(steps[0]) * 0.01) for step in steps)


def _box_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Distance between two printed boxes in points: 0 when they touch, else the largest axis gap."""
    dx = max(0.0, b[0] - a[2], a[0] - b[2])
    dy = max(0.0, b[1] - a[3], a[1] - b[3])
    return max(dx, dy)


def region_box(region: str) -> tuple[float, float, float, float] | None:
    parts = [p for p in str(region or "").split(",") if p.strip()]
    if len(parts) != 4:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
    except ValueError:
        return None


def nearest_geography(words: Iterable[tuple[float, float, float, float, str]], region: str,
                      names: Iterable[str], gap: float = MAP_CALLOUT_GAP) -> str:
    """The printed place name closest to the value's box, when that name sits within the call-out gap.

    The map's own call-outs are the only evidence a number belongs to a state: a name printed far away (the deck
    title, a neighbouring panel) never binds it, and a value the text layer does not carry binds to nothing.
    """
    value_box = region_box(region)
    if value_box is None:
        return ""
    best: tuple[float, str] | None = None
    for name in dict.fromkeys(norm_space(n) for n in names if norm_space(n)):
        box = phrase_bbox(words, name)
        if box is None:
            continue
        distance = _box_gap(value_box, box)
        if distance <= gap and (best is None or distance < best[0]):
            best = (distance, name)
    return best[1] if best else ""


def is_map_pin(row: dict[str, Any]) -> bool:
    """A count of places (outlets, dealers, customers, plants) placed on a map; a volume/price table is not one."""
    return str(row.get("measure") or "").startswith("count.")


def apply_geography(rows: list[dict[str, Any]], words: Iterable[tuple[float, float, float, float, str]]) -> int:
    """Stage H: a map call-out's geography must be printed next to its value; else the geography is cleared.

    A page whose count rows name MAP_MIN_PLACES or more distinct places is a map page.  On it the place of every
    count row is re-read from the text-layer word boxes: the nearest printed place name within the call-out gap wins
    (this also un-swaps neighbouring call-outs), and a value whose state name is not printed next to it carries no
    geography.  A page with fewer places is left alone, and a volume/price table that happens to name its rows by
    plant is never treated as a map: its geography is the row's printed label, not a call-out.
    """
    word_list = list(words)
    pinned = [r for r in rows if is_map_pin(r)]
    places = {norm_space(r.get("geography")) for r in pinned if norm_space(r.get("geography"))}
    if len(places) < MAP_MIN_PLACES or not word_list:
        return 0
    cleared = 0
    for row in pinned:
        if not norm_space(row.get("geography")):
            continue
        found = nearest_geography(word_list, row.get("region") or "", places)
        if found:
            row["geography"] = found
            continue
        row["geography"] = ""
        cleared += 1
        row["status"] = "unverified"
        row["status_reason"] = (row["status_reason"] + "; " if row.get("status_reason") else "") + \
            "geography_not_printed: no place name printed next to the value (map call-out unbound)"
    return cleared


def split_panels(rows: list[dict[str, Any]]) -> int:
    """Stage H: one series per map panel.  Rows of a map series carrying different printed panel titles are split.

    The three maps of CONFIPET's dealer slide are one series with no segment in obs_91.db, so Punjab returns 12, 07
    and 41 with nothing to tell them apart.  The model now prints each panel's title; the script makes each title its
    own series and, where a place is printed, its own segment.  Only a map-like series (>=MAP_MIN_PLACES distinct
    geographies) is split, so a normal chart whose title the model paraphrases per row is never broken up.
    """
    by_series: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_series.setdefault(row.get("series_id") or "s1", []).append(row)
    split = 0
    for series_id, group in by_series.items():
        places = {norm_space(r.get("geography")) for r in group if is_map_pin(r) and norm_space(r.get("geography"))}
        if len(places) < MAP_MIN_PLACES:
            continue
        titles: list[str] = []
        for row in group:
            title = norm_space(row.get("series_title"))
            if title and title not in titles:
                titles.append(title)
        if len(titles) < 2:
            continue
        for row in group:
            title = norm_space(row.get("series_title"))
            if not title:
                continue
            row["series_id"] = f"{series_id}#{titles.index(title) + 1}"
            if not norm_space(row.get("segment")) and norm_space(row.get("geography")):
                row["segment"] = title
            split += 1
    return split


def apply_map_orphans(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stage H: a value with no printed label, axis or place that sits in a bare list is not an observation.

    ESAF's 25 map pins carry only their number (no state name printed anywhere in the text layer), so the row can
    never be attributed to a state; Wolf graded all 25 wrong ("nothing says which state each belongs to").  The same
    shape is an unlabelled bar list (POLYPLEX's estimated capacity heights): a count/capacity value with none of its
    own printed context is dropped, never stored as an unattributable row.
    """
    by_series: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_series.setdefault(row.get("series_id") or "s1", []).append(row)

    def bare(row: dict[str, Any]) -> bool:
        return not (norm_space(row.get("printed_label")) or norm_space(row.get("printed_axis"))
                    or norm_space(row.get("geography")))

    kept: list[dict[str, Any]] = []
    for row in rows:
        measure = row.get("measure") or ""
        group = by_series.get(row.get("series_id") or "s1", [])
        listing = sum(1 for other in group if other.get("measure") == measure and bare(other))
        orphan = bare(row) and (BY_PLACE_RE.search(measure) is not None
                                or (measure.startswith(("count.", "capacity.")) and listing >= MAP_MIN_PLACES))
        if not orphan:
            kept.append(row)
    return kept


def apply_stacked_parts(rows: list[dict[str, Any]]) -> int:
    """Stage H: a segment inside a stacked bar is a part, never the total, and keeps its own label.

    Same series, period, unit and scale: the one row whose value equals the sum of the others (within rounding) is
    the printed total; every other row is a part.  A part with no label takes its segment name as the label, and a
    part carrying the total's own measure is unverified: it cannot be read as a second total for the year.
    """
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("value") is None:
            continue
        key = (row.get("series_id") or "s1", row.get("period") or "", row.get("unit") or "",
               float(row.get("scale") or 1))
        groups.setdefault(key, []).append(row)
    marked = 0
    for group in groups.values():
        if not 2 <= len(group) <= 12:
            continue
        values = [float(r["value"]) for r in group if r.get("value") is not None]
        if len(values) != len(group):
            continue
        for index, total in enumerate(group):
            rest = values[:index] + values[index + 1:]
            if min(rest) < 0:
                continue
            tolerance = max(0.51, abs(values[index]) * 0.005)
            if abs(sum(rest) - values[index]) > tolerance:
                continue
            for row in group:
                if row is total:
                    row["_is_total"] = True       # stage J: the arithmetic prints the total even when its label does not
                    continue
                row["_part"] = True
                marked += 1
                if not norm_space(row.get("printed_label")) and norm_space(row.get("segment")):
                    row["printed_label"] = norm_space(row.get("segment"))
                if row.get("measure") and row.get("measure") == total.get("measure") \
                        and str(row.get("measure")).endswith(".total"):
                    row["status"] = "unverified"
                    row["status_reason"] = (row["status_reason"] + "; " if row.get("status_reason") else "") + \
                        "stacked_part: a segment of the stack, not the year's total"
            break
    return marked


def apply_rank_count(rows: list[dict[str, Any]]) -> int:
    """Stage H: a rank is a count, not a share.  "top 10 film customers ... 26%" prints a count of 10 and a 26% share.

    A percent measure whose label says "top N" and whose value is that N (no % printed) is the rank count: it becomes
    a customer count and never verifies as a percentage.
    """
    fixed = 0
    for row in rows:
        measure = row.get("measure") or ""
        label = row.get("printed_label") or ""
        match = TOP_N_RE.search(label)
        if not match or not PERCENT_MEASURE_RE.search(measure):
            continue
        value_text = norm_space(row.get("value_text"))
        if "%" in value_text:
            continue                 # the share itself is printed with a % sign; only the bare rank is remapped
        value = row.get("value")
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if abs(number - float(match.group(1))) > 1e-6:
            continue
        row["measure"] = "count.customers"
        row["unit"] = "customers"
        row["unit_family"] = "count"
        row["status"] = "unverified"
        row["status_reason"] = (row["status_reason"] + "; " if row.get("status_reason") else "") + \
            f"rank_count: 'top {match.group(1)}' prints a count, not a share"
        fixed += 1
    return fixed


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


# --------------------------------------------------------------------------- stage K: printed column headers

# Standalone / consolidated as a printed header word (trailing punctuation stripped).
BASIS_TOKENS: dict[str, str] = {"standalone": "standalone", "stand-alone": "standalone",
                                "consolidated": "consolidated"}
HEADER_LINE_MAX_CHARS = 60
HEADER_LINE_MAX_WORDS = 8
HEADER_X_SLACK = 150.0
YEAR_SPAN_RE = re.compile(r"\b(?:19|20)\d{2}\s?-\s?\d{2}\b")


def _line_words(words: Iterable[tuple[float, float, float, float, str]]) -> list[list[tuple[float, float, float, float, str]]]:
    """The page's words grouped into printed lines (same baseline), top to bottom (T-230 stage K)."""
    ordered = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list[tuple[float, float, float, float, str]]] = []
    centre = 0.0
    for word in ordered:
        yc = (word[1] + word[3]) / 2
        if lines and abs(yc - centre) <= max(2.5, (word[3] - word[1]) * 0.6):
            lines[-1].append(word)
            continue
        lines.append([word])
        centre = yc
    for line in lines:
        line.sort(key=lambda w: w[0])
    return lines


def _value_box(region: str) -> tuple[float, float, float, float] | None:
    parts = [float(p) for p in str(region or "").split(",") if p.strip()]
    return (parts[0], parts[1], parts[2], parts[3]) if len(parts) == 4 else None


def _over_value(line: Iterable[tuple[float, float, float, float, str]],
                box: tuple[float, float, float, float]) -> bool:
    """The line's printed text sits over the value's column (overlaps in x, or a heading near its centre)."""
    line = list(line)
    x0 = min(w[0] for w in line)
    x1 = max(w[2] for w in line)
    if x0 <= box[2] and box[0] <= x1:
        return True
    return abs((x0 + x1) / 2 - (box[0] + box[2]) / 2) <= HEADER_X_SLACK


def basis_token(word: str) -> str:
    """'Standalone' / 'Consolidated' (any case, trailing punctuation) -> its token, else ''."""
    return BASIS_TOKENS.get(norm_space(word).lower().strip(".,;:()[]"), "")


def column_basis(words: Iterable[tuple[float, float, float, float, str]], region: str) -> str:
    """T-230 stage K: the basis printed in the column/page header nearest above the value, never guessed.

    A page that prints both words takes the header over the value's own column; a page that prints one of them as
    a section heading applies it to every row beneath that heading.  Empty region (the value's box is unknown), or
    no basis word above the value, leaves the basis empty and the basis conflict stands.
    """
    box = _value_box(region)
    if box is None:
        return ""
    heading: list[tuple[float, str]] = []
    hits: list[tuple[float, float, str]] = []
    for line in _line_words(words):
        gap = box[1] - max(w[3] for w in line)
        if gap < -2.0:
            continue
        bases = {b for b in (basis_token(w[4]) for w in line) if b}
        if len(bases) == 1 and len(line) <= HEADER_LINE_MAX_WORDS and basis_token(line[0][4]):
            text = norm_space(" ".join(w[4] for w in line))
            if len(text) <= HEADER_LINE_MAX_CHARS:
                heading.append((gap, next(iter(bases))))
        for word in line:
            token = basis_token(word[4])
            if token:
                hits.append((gap, abs((word[0] + word[2]) / 2 - (box[0] + box[2]) / 2), token))
    if len({b for _gap, b in heading}) == 1:
        # ponytail: one printed basis heading covers every row beneath it on the page; a side-by-side table whose
        # own header is image-only would inherit it. Add a per-table header when a Wolf read shows that mixture.
        return heading[0][1]                  # one section heading above the value: it names this part of the page
    if len({b for _gap, _x, b in hits}) < 2:
        return ""                             # one stray header token that is not a heading is not a proof
    for line in reversed(_line_words(words)):
        if box[1] - max(w[3] for w in line) < -2.0 or not _over_value(line, box):
            continue
        tokens: list[tuple[float, float, str]] = []
        for word in line:
            token = basis_token(word[4])
            if token:
                tokens.append((box[1] - word[3], abs((word[0] + word[2]) / 2 - (box[0] + box[2]) / 2), token))
        if tokens:
            return min(tokens, key=lambda item: (item[0], item[1]))[2]
    return ""


def period_header(text: str) -> str:
    """The period a printed column header names, when the header is essentially the period ('31 March 2025')."""
    line = norm_space(text).strip(" .|,;:")
    if not line or len(line) > HEADER_LINE_MAX_CHARS:
        return ""
    best = ""
    for pattern in (YEAR_SPAN_RE,) + PERIOD_PATTERNS:
        match = pattern.search(line)
        if match and len(norm_space(match.group(0))) > len(best):
            best = norm_space(match.group(0))
    return best if len(best) * 2 >= len(line) else ""


def column_period(words: Iterable[tuple[float, float, float, float, str]], region: str) -> str:
    """T-230 stage K: the period a printed column header above the value puts over it; '' when there is none.

    Only a short header line over the value's own column counts (a paragraph that mentions a year is not a column
    header), and the value's text-layer box must be known: the period is never guessed.
    """
    box = _value_box(region)
    if box is None:
        return ""
    for line in reversed(_line_words(words)):
        if box[1] - max(w[3] for w in line) < -2.0 or not _over_value(line, box):
            continue
        period = period_header(" ".join(w[4] for w in line))
        if period:
            return period
    return ""


# --------------------------------------------------------------------------- stage L: proof and label gates

# A printed label that is only a category word ("Male", "Other", "Total", "Wages", "Interest Cost"): the row is
# a part or a column qualifier of a table, never the measure itself.  Stage K's AR upgrades verified these on a
# trivially marshalled parts sum (Wolf's read D:/RealityEngine/t230/stageK_read/grade{1,2,3}.md).
GENERIC_LABEL_RE = re.compile(
    r"^(?:total(?:\s*\([a-z]\))?|employees?|workers?|staff|males?|females?|"
    r"other(?:\s+than\s+permanent)?|transgender|permanent|contractual|wages?|interest\s+cost)"
    r"(?:\s+(?:employees?|workers?))?$", re.I)
GENERIC_MEASURE_WORDS = {"count", "value"}
JOB_WORDS = {"employees", "employee", "workers", "worker", "staff", "headcount"}
BENEFIT_OBLIGATION_RE = re.compile(
    r"gratuity|defined[\s-]*benefit|present\s+value\s+of\s+(?:the\s+)?obligation|employee\s+benefit|"
    r"leave\s+encashment|provident\s+fund|superannuation", re.I)

# A page/section heading that names the basis of the rows beneath it.  The word alone is not enough when the
# page prints both bases (a side-by-side statement); then neither is proven.
CONSOLIDATED_PAGE_RE = re.compile(
    r"notes?\s+to\s+(?:the\s+)?consolidated|consolidated\s+(?:financial\s+)?"
    r"(?:statements?|balance\s+sheet|profit|cash\s*flow)|on\s+a\s+consolidated|"
    r"consolidated\s+basis|\bthe\s+group\b", re.I)
STANDALONE_PAGE_RE = re.compile(
    r"standalone\s+(?:financial\s+)?(?:statements?|balance\s+sheet|profit|cash\s*flow)|"
    r"on\s+a\s+standalone|standalone\s+basis|\bstandalone\b", re.I)

# "(31 March 2024 : NIL)" is an inline comparative: the date inside it is the other column, never this row's
# period (ESTER p196).  A bracketed column header has no comparison mark and is not matched.
COMPARATIVE_SPAN_RE = re.compile(r"\(([^()]{1,120})\)")
COMPARATIVE_MARK_RE = re.compile(r":\s*(?:nil|n\.?a\.?|[-–—]|\d)|compared|\bvs\.?\b|previous", re.I)
AS_AT_DATE_RE = re.compile(
    r"\b(?:as\s+(?:at|on|of)|closing\s+as\s+(?:at|on)|balance\s+as\s+(?:at|on))\s+"
    r"((?:\d{1,2}(?:st|nd|rd|th)?\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4}"
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{4})", re.I)
FLOW_PERIOD_RE = re.compile(
    r"\d{1,2}[./-]\d{1,2}[./-]\d{4}\s*(?:-|to|–)\s*\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    r"\bFY\s?\d|financial\s+year|year\s+ended|year\s+end", re.I)


def _word_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", norm_space(text).lower()))


def measure_keywords(measure: str) -> set[str]:
    """The words of a measure id that must be printed in a group heading before a generic label can verify."""
    return _word_set(re.sub(r"[._]", " ", str(measure or ""))) - GENERIC_MEASURE_WORDS


def _label_names_measure(label_words: set[str], measure_words: set[str]) -> bool:
    """Every category word of the label must be one the measure names ('Total Workers' fits count.employees)."""
    for word in label_words:
        if word in measure_words:
            continue
        if word in JOB_WORDS and measure_words & JOB_WORDS:
            continue
        return False
    return True


def generic_label_reason(row: dict[str, Any]) -> str:
    """Stage L: a generic category label proves nothing unless its printed group heading names the measure.

    "Female" under Employees is a sub-count, "Wages" is one complaints category, "Interest Cost" under a
    benefit-obligation note is the unwinding of a gratuity obligation, and a bare "Total" names no measure.
    The row verifies only when the label's own category word is in the measure and every measure word is in
    the printed group path; otherwise it reads as a total the page does not print.
    """
    label = norm_space(row.get("printed_label")).lower().strip(" .:;")
    measure = str(row.get("measure") or "")
    if not label or not measure or GENERIC_LABEL_RE.match(label) is None:
        return ""
    context = " ".join([row.get("printed_label") or "", row.get("printed_axis") or "",
                        row.get("series_title") or "", row.get("group_path") or ""])
    if BENEFIT_OBLIGATION_RE.search(context) and measure_root(measure) == "finance_cost":
        return f"generic_label: defined-benefit interest cost {row.get('printed_label')!r} is not finance_cost"
    label_words = _word_set(label) - {"total", "grand", "overall", "all"}
    measure_words = measure_keywords(measure)
    if not _label_names_measure(label_words, measure_words):
        return f"generic_label: {row.get('printed_label')!r} is a part/category, not the measure {measure!r}"
    if not label_words and (row.get("_is_total") or row.get("is_total")):
        return ""                          # a bare printed "Total" is the total of its parts: the sum is its proof
    group = " ".join([row.get("group_path") or "", row.get("printed_axis") or ""])
    if not measure_words or not measure_words <= _word_set(group):
        return f"generic_label: no printed heading names {measure!r}"
    return ""


COMPARED_BASIS_RE = re.compile(r"\b(?:than|versus|vs\.?|against|compared\s+(?:to|with))\s+(?:the\s+|our\s+)?$", re.I)
SECTION_BASIS_RE = re.compile(r"\b(standalone|stand-alone|consolidated)\b", re.I)


def section_basis(page_text: str, label: str, value_text: str) -> str:
    """T-241: the basis a transcript number sits under: the last standalone / consolidated word before it.

    A CFO reads "Starting with the standalone numbers ..." then "Coming to the consolidated results ..." on one
    page, so the page-level rule (both words -> no basis) and the first heading are both wrong for half the rows."""
    text = norm_space(page_text)
    pos = -1
    for probe in (f"{label} {value_text}".strip(), value_text, label):
        if probe:
            pos = text.find(probe)
            if pos >= 0:
                break
    if pos < 0:
        return ""
    last = ""
    for m in SECTION_BASIS_RE.finditer(text, 0, pos):
        if COMPARED_BASIS_RE.search(text[max(0, m.start() - 25):m.start()]):
            continue                 # "better than standalone performance" compares, it does not switch the section
        last = m.group(1).lower()
    return "standalone" if last in ("standalone", "stand-alone") else last


def page_basis(page_text: str) -> str:
    """Stage L: the page's own section heading names the basis when no column header does.

    "Notes to Consolidated Financial Statements" (KRYSTAL p185) and "the Group" (COSMOFIRST) are the printed
    basis of the rows beneath them.  A page that prints both bases proves neither (never guessed).
    """
    text = str(page_text or "")
    stand = bool(STANDALONE_PAGE_RE.search(text))
    cons = bool(CONSOLIDATED_PAGE_RE.search(text))
    if stand and not cons:
        return "standalone"
    if cons and not stand:
        return "consolidated"
    return ""


def strip_comparatives(text: str) -> str:
    """The text with its inline comparative brackets removed (a comparative date is not a header)."""
    return COMPARATIVE_SPAN_RE.sub(
        lambda match: " " if COMPARATIVE_MARK_RE.search(match.group(1)) else match.group(0), str(text or ""))


def comparative_period(period: str, page_text: str, row_text: str = "") -> bool:
    """Stage L: True when ``period`` is printed only inside an inline comparative bracket.

    "(31 March 2024 : NIL)" says the previous column was nil; the row's own period is the unqualified header
    (ESTER p196).  The row's own label/axis is read first: a period named only inside a bracket there is the
    comparative even when the page prints the same month elsewhere.  A bracketed column header has no comparison
    mark, so it is not a comparative.
    """
    target = norm_space(period).lower()
    if not target:
        return False

    def in_comparative(text: str) -> bool:
        for match in COMPARATIVE_SPAN_RE.finditer(text):
            span = match.group(1)
            if COMPARATIVE_MARK_RE.search(span) and target in norm_space(span).lower():
                return True
        return False

    row = str(row_text or "")
    if row and in_comparative(row):
        return target not in norm_space(strip_comparatives(row)).lower()
    text = str(page_text or "")
    return in_comparative(text) and target not in norm_space(strip_comparatives(text)).lower()


def apply_instant_period(row: dict[str, Any]) -> bool:
    """Stage L: "Closing as on 31st March 2024" is a point-in-time period, not the year's flow.

    Only a row whose stored period is a fiscal range/flow and whose own label names the as-at date moves;
    a P&L row already headed "As on March 31, 2024" keeps its period and its kind.
    """
    label = " ".join([row.get("printed_label") or "", row.get("printed_axis") or ""])
    match = AS_AT_DATE_RE.search(label)
    period = str(row.get("period") or "")
    if not match or not period:
        return False
    date = infer_period([match.group(1)]) or norm_space(match.group(1))
    if not date or date.lower() in period.lower() or not FLOW_PERIOD_RE.search(period):
        return False
    row["period"] = date
    row["period_kind"] = "instant"
    row["period_source"] = "label_instant"
    return True


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


# T-238 stage N2: the closed list of snapshot measures a deck's as-of date can belong to.  A count of customers,
# countries, employees or orders is not a stock the deck date measures, and neither is a ratio or a growth.
DECK_ASOF_MEASURES = re.compile(
    r"^capacity\.(?!utilisation|growth_multiple)|^shareholding_pct$|^count\.shares$|"
    r"^count\.(?:.*(?:outlets?|branches?|atms?|stores?|plants?|locations?))$|"
    r"^order\.book$|^aum\.value$|^loans$|^deposits$|^borrowings$|^net_worth$|^total_equity$", re.I)


def is_stock_measure(measure: str) -> bool:
    """A true stock a deck's as-of date can belong to (E1, closed list in stage N2): not a rate, an addition or a plan."""
    return DECK_ASOF_MEASURES.search(measure or "") is not None

DECK_ASOF_TARGET_RE = re.compile(
    r"\b(?:to\s+(?:reach|touch|be)\b|target(?:s|ed|ing)?\b|aspir(?:e|es|ed|ing|ation)\b|guidance\b|"
    r"expected\s+to\b|\bby\s+FY(?:\s?-?\d{2,4})?\b)"
    r"|\bto\s+(?:(?:reach|touch|be)\s+)?(?:rs\.?\s*|inr\s*|\u20b9\s*|\$\s*|usd\s*)?\d", re.I)
PAST_PROGRAMME_RE = re.compile(r"\bCOVID\b|\bResolution Framework\b", re.I)

def deck_asof_allowed(row: dict[str, Any], page_text: str) -> bool:
    """T-238 N3: a stock measure may take the deck's as-of date only when its label is a real snapshot,
    not a target/forward figure, and the page is not a past programme/period page."""
    if not is_stock_measure(str(row.get("measure")) if isinstance(row, dict) else str(row)):
        return False
    if not capacity_deck_period_ok(row, page_text):
        return False
    label_text = " ".join([str(row.get("printed_label") or ""), str(row.get("series_title") or ""),
                           str(row.get("group_path") or "")])
    if DECK_ASOF_TARGET_RE.search(label_text):
        return False
    if PAST_PROGRAMME_RE.search(page_head(page_text, 6)):
        return False
    return True


def capacity_deck_period_ok(row: dict[str, Any], page_text: str) -> bool:
    """E1: capacity takes the deck period only for an operating/installed stock, never a plan, a rate or EPC work."""
    measure = row.get("measure") or ""
    if measure == "count.plants" and len(norm_space(row.get("printed_label")).split()) >= 4:
        return False        # stage H: "All 3 plants are within 15-110KM ..." is a sentence, not a dated stock row
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
                 page_text: str, value_text: str = "") -> tuple[str, str] | None:
    """E4: a CAGR / two-point span on a growth row becomes *_growth_cagr with period_kind span, never *_yoy."""
    if not GROWTH_YOY_RE.search(measure or ""):
        return None
    text = " ".join([label, axis, series])
    cue = CAGR_RE.search(text) is not None or CAGR_RE.search(page_head(page_text, 6)) is not None
    if not cue and value_text:          # stage H: the value's own printed phrase says CAGR ("27.8% CAGR")
        cue = re.search(re.escape(norm_space(value_text)) + CAGR_AFTER_VALUE_RE, page_text or "", re.I) is not None
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
    periods = fiscal_periods(text)          # T-238 stage N: keep the printed quarter ("Q2 FY26", not "FY26")
    if periods:
        return periods[0]
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


# T-238 stage N: a fiscal label as a deck title prints it ("Q2 FY26", "H1FY26", "9M 2025-26", "FY25").
# N2: the label keeps the fiscal-year suffix the page prints, so a page printing "9M 2025-26" is never stored
# as the truncated "9M 2025".
FISCAL_PERIOD_RE = re.compile(
    r"\b(?:Q[1-4]|H[12]|9M)\s*-?\s*(?:FY)?\s*-?\s*\d{2,4}(?:\s*-\s*\d{2,4})?[A-Z]?\b|"
    r"\bFY\s?-?\d{2,4}(?:\s*-\s*\d{2,4})?[A-Z]?\b", re.I)
BASIS_WORD_RE = re.compile(r"\b(standalone|consolidated)\b", re.I)
BASIS_NEGATED_RE = re.compile(r"\b(?:not|non|ex)[- ](?:standalone|consolidated)\b", re.I)
# N2: page furniture that carries a date but is not the slide's title (REPL's "Investor's Highlights Q4/12 M FY 24"
# footer and its "Page 3 of 12" strip, an app-screenshot's nav text, a bare page number).
TITLE_FURNITURE_RE = re.compile(
    r"^(?:page\s+\d+\s*(?:of|/)\s*\d+|p\.?\s*\d+|\d{1,3}|home\s+outline|hamburger\b.*|"
    r"investor(?:'s|\u2019s)?\s+highlights\b.*)$|^(?:\(\d+\)|note\b|source\b|[*#]\s*)", re.I)
TITLE_MAX_WORDS = 12
TITLE_MAX_CHARS = 90


def fiscal_periods(text: str) -> list[str]:
    """Every fiscal period label printed in the text, in order and as written ('Q2 FY26', 'H1FY26', 'FY25')."""
    return [norm_space(match.group(0)) for match in FISCAL_PERIOD_RE.finditer(str(text or ""))]


def _period_key(period: str) -> str:
    return re.sub(r"[^a-z0-9]", "", norm_space(period).lower())


def _title_like(line: str, periods: list[str]) -> bool:
    """A slide title, not body text or a table/column label: short, and the fiscal label is only part of its words."""
    line = norm_space(line)
    words = line.split()
    if not words or len(words) > TITLE_MAX_WORDS or len(line) > TITLE_MAX_CHARS:
        return False
    rest = line
    for period in periods:
        rest = rest.replace(period, " ")
    return re.search(r"[A-Za-z]{2,}", rest) is not None


def slide_period(page_text: str) -> str:
    """Stage N/N2: the fiscal period printed in the page's own title line, never in its footer/header furniture.

    A value with no period printed beside it takes the period the slide's title names ("Q2 FY26 Investor
    Update", "H1FY26 Performance") -- but only when the page prints that one fiscal label and no second one:
    a multi-period chart has no single period any number on it belongs to, so its flow rows stay no_period.
    N2 (Wolf's hand grade): the label must sit in the title line itself, not in the first three lines.  A first
    line that is a bare label ("9M 2025-26" over one column) or a footnote tile is not the slide's title, and a
    line that prints only the period plus a page number is furniture; both refuse the fill (KPIL, REPL).
    N3 (Wolf's recheck): a bare fiscal title stays a title even when the line under it is a bare number --
    AJMERA p17 prints "H1 FY26" over its project table ("Marina" 1,49,229 area.sold) and the page took no
    period.  The only vetoes are the multi-period table (a line or a page printing two fiscal labels).
    """
    lines = [norm_space(line) for line in str(page_text or "").splitlines() if norm_space(line)]
    if not lines:
        return ""
    if any(len(fiscal_periods(line)) >= 2 for line in lines):
        return ""
    labels = {_period_key(period) for line in lines for period in fiscal_periods(line)}
    if len(labels) != 1:
        return ""
    for i, line in enumerate(lines[:5]):
        if TITLE_FURNITURE_RE.match(line):
            continue                       # page number / nav strip / footer highlight strip, not the title
        periods = fiscal_periods(line)
        bare_title = (len(periods) == 1 and norm_space(line) == norm_space(periods[0]))
        if not bare_title and not _title_like(line, periods):
            return ""                      # body text or a table label: the title block ends here
        if periods:
            return periods[0]
    return ""


GROWTH_CHANGE_RE = re.compile(r"_growth_(?:yoy|qoq)(?:_|$)|_change_(?:pct|pp)(?:_|$)", re.I)
FISCAL_YEAR_LABEL_RE = re.compile(r"\bFY\s?-?(\d{2,4})\b", re.I)
_PERIOD_KIND_RE = re.compile(r"^(Q[1-4]|H[12]|9M|FY)", re.I)


def _fiscal_year(label: str) -> int | None:
    text = label or ""
    match = FISCAL_YEAR_LABEL_RE.search(text)
    if not match:
        return None
    year = int(match.group(1))
    range_match = re.search(r"\d{2,4}\s*-\s*(\d{2,4})", text)
    if range_match:
        end = int(range_match.group(1))
        year = end if end >= 1000 else 2000 + end
    return year if year >= 1000 else 2000 + year


def _period_rank(label: str) -> tuple[int, int] | None:
    """(fiscal year, ordinal) so a printed pair sorts: FY24 > FY23, Q2 FY26 > Q1 FY26, Q2 FY26 > Q2 FY25."""
    match = _PERIOD_KIND_RE.match(norm_space(label))
    year = _fiscal_year(label)
    if not match or year is None:
        return None
    kind = match.group(1).upper()
    index = {"FY": 0, "H1": 1, "H2": 2, "9M": 3}.get(kind)
    if index is None:                        # Q1..Q4
        index = int(kind[1])
    return year, index


def growth_change_period(period: str, measure: str, page_text: str) -> str:
    """N2: a printed YoY/change row takes the later label of the printed pair, never the earlier one.

    IRCON p20 prints "Y-o-Y (%) FY23 FY24" beside Other Income 437.45 vs 340.43 (+28.50%): the growth belongs to
    FY24 and the fill had stored FY23.  The pair must be the page's only two labels of its kind; a three-year trend
    prints no single pair, so the row's own period is left alone.
    """
    if not period or not GROWTH_CHANGE_RE.search(measure or ""):
        return period
    labels = [label for line in str(page_text or "").splitlines() for label in fiscal_periods(line)]
    distinct: list[str] = []
    for label in labels:
        if _period_key(label) not in {_period_key(seen) for seen in distinct}:
            distinct.append(label)
    if len(distinct) != 2:
        return period
    first, second = distinct
    kinds = []
    for label in (first, second):
        match = _PERIOD_KIND_RE.match(norm_space(label))
        kinds.append(match.group(1).upper()[:1] if match else "")
    if kinds[0] != kinds[1]:
        return period                          # a year beside a quarter is no printed pair
    ranks = [_period_rank(first), _period_rank(second)]
    if ranks[0] is None or ranks[1] is None:
        return period
    ya, ia = ranks[0]
    yb, ib = ranks[1]
    adjacent = (ya == yb and abs(ia - ib) == 1) or (abs(ya - yb) == 1 and ia == ib)
    if not adjacent:
        return period
    earlier, later = sorted([(ranks[0], first), (ranks[1], second)])
    return later[1] if _period_key(period) == _period_key(earlier[1]) else period


@lru_cache(maxsize=512)
def deck_basis(store_db: str | Path, doc_key: str) -> str:
    """Stage N: the one basis every basis word printed in the deck names; '' when it prints none or both.

    A deck whose every "Standalone"/"Consolidated" word says the same basis dates all its unlabelled financial
    rows to that basis; a deck printing both leaves an unlabelled row unbased (a conflict, never a guess).
    """
    try:
        con = connect_ro(store_db, timeout_s=60)
        try:
            _cur = con.execute("SELECT text FROM doc_page WHERE doc_key=?", (doc_key,))
            texts = [str(row[0] or "") for row in _cur if row is not None] if _cur is not None else []
        finally:
            con.close()
    except Exception:
        return ""
    found = {match.group(1).lower() for text in texts
             for match in BASIS_WORD_RE.finditer(BASIS_NEGATED_RE.sub("", text))}
    return next(iter(found)) if len(found) == 1 else ""


def apply_series_kind(rows: list[dict[str, Any]], page_text: str) -> None:
    """D3/H4: a waterfall's first and last bars are levels of the walked measure; only the middle bars are steps.

    The bridge must be printed on THIS series (its title or first label), not anywhere on the page: RSYSTEMS p7 has
    an "Adj. EBITDA Bridge" panel beside its revenue trend, and the page-wide word turned every multi-row series into
    a bridge (row 118618, a level, became ebitda.delta).  Where the series no longer qualifies, a step stored by the
    old rule goes back to its level measure.
    """
    by_series: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row["_series_kind_before"] = row.get("series_kind") or ""
        by_series.setdefault(row.get("series_id") or "s1", []).append(row)
    for series, group in by_series.items():
        for row in group:
            row["series_kind"] = "level"
        if len(group) < 3:
            for row in group:
                row.pop("_series_kind_before", None)
            continue
        first = group[0]
        title = " ".join(sorted({norm_space(r.get("series_title")) for r in group
                                 if norm_space(r.get("series_title"))}))
        bridge = BRIDGE_TEXT_RE.search(title) is not None or \
            re.search(r"\breported\b", first.get("printed_label") or "", re.I) is not None
        if not bridge:
            for row in group:
                old_kind = row.pop("_series_kind_before", "")
                if old_kind == "bridge":
                    row["_proof"] = True   # the page-wide bridge rule demoted a level; a recheck may verify it
                    if row.get("measure") in DELTA_TO_LEVEL:
                        row["measure"] = DELTA_TO_LEVEL[row["measure"]]
            continue
        base = DELTA_TO_LEVEL.get(first.get("measure") or "", first.get("measure") or "")
        delta = DELTA_OF.get(base) or (base + ".delta" if base else "")
        for row in group:
            row["series_kind"] = "bridge"
            row.pop("_series_kind_before", None)
        for row in group[1:-1]:                 # only the middle bars are steps
            if delta and delta in measure_index():
                row["measure"] = delta
            row["status"] = "unverified"
            row["status_reason"] = (row["status_reason"] + "; " if row["status_reason"] else "") + \
                f"bridge step of {base or 'the walked measure'}, not a level"
        for row in (group[0], group[-1]):       # the opening and closing bars are levels of the walked measure
            if row.get("measure") in DELTA_TO_LEVEL:
                row["measure"] = DELTA_TO_LEVEL[row["measure"]]
                row["_proof"] = True


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


def _is_bare_number(line: str) -> bool:
    """A text-layer line that is only a number ('5,000', '(1.5)', '81%'): a tick, a data label or a lone value."""
    return re.fullmatch(r"\(?[-+]?\d[\d,]*(?:\.\d+)?\)?%?", norm_space(line)) is not None


def page_tick_values(text: str) -> set[float]:
    """The axis-tick numbers a page prints, read from its bare-number lines.

    A PDF often extracts each axis tick as its own word/line ("0", "1,000", "2,000" ...), so the ladder is only
    visible across the page: the longest run of bare numbers whose step is constant (>=5 numbers) is the axis.
    """
    values = sorted({_numbers_in(line)[0] for line in str(text or "").splitlines()
                     if _is_bare_number(line) and len(_numbers_in(line)) == 1})
    ticks: set[float] = set()
    index = 0
    while index + TICK_LADDER_MIN - 1 < len(values):
        step = values[index + 1] - values[index]
        end = index + 1
        while end + 1 < len(values) and abs((values[end + 1] - values[end]) - step) <= max(1e-9, abs(step) * 0.01):
            end += 1
        if end - index + 1 >= TICK_LADDER_MIN:
            ticks.update(values[index:end + 1])
            index = end + 1
        else:
            index += 1
    return ticks


def _label_beside_value(text: str, needle: str) -> bool:
    """Stage J: a printed text line directly above/below the value is its data label, not an axis tick.

    FAZE3Q p13 prints ROE rows as "11%" then "ROE^": the value belongs to the label beside it even though a
    ladder elsewhere on the page also contains 11.  An axis title can sit beside the top or bottom tick, so
    only the value's immediate neighbours are read.
    """
    lines = [norm_space(line) for line in str(text or "").splitlines()]
    for index, line in enumerate(lines):
        if not text_has(line, needle):
            continue
        neighbours = []
        if index:
            neighbours.append(lines[index - 1])
        if index + 1 < len(lines):
            neighbours.append(lines[index + 1])
        for neighbour in neighbours:
            if neighbour and not _is_bare_number(neighbour) and not _numbers_in(neighbour) \
                    and re.search(r"[A-Za-z]{2,}", neighbour):
                return True
    return False


def _is_table_rows(text: str) -> bool:
    """Stage J: a page of label-then-column-values rows is a table, never a chart's axis ladder.

    FAZE3Q p13's "Key Ratios Summary" prints each row as a label followed by nine bare cells (7%, 8%, 11% ...),
    so its 11% sits in a five-or-more run of evenly spaced bare numbers.  Three such runs on one page are a
    table; a chart extracts at most the one ladder of its axis.
    """
    lines = [norm_space(line) for line in str(text or "").splitlines()]
    runs = 0
    run = 0
    for line in lines:
        if _is_bare_number(line):
            run += 1
            continue
        if run >= TICK_LADDER_MIN:
            runs += 1
        run = 0
    if run >= TICK_LADDER_MIN:
        runs += 1
    return runs >= 3


def is_axis_tick(text: str, row: dict[str, Any]) -> bool:
    """D5/H2: a value whose only text-layer match is a tick ladder (0, 1,000, 2,000 ...) has no data label.

    A bar's height estimated against the gridlines can land on an axis-tick number by chance (POLYPLEX 5,000/7,000/
    9,000, MANINFRA 2,500/1,000); the old rule only caught a bare tick line and a row with no label.  Now every line
    carrying the value must be a ladder line, or a bare number that belongs to the page's own tick ladder: one
    printed data label anywhere on the page settles it as a value.  Stage I: a statement/table page is never a chart
    -- its bare cells (ASTRAMICRO's balance-sheet "3") are a table row, not an axis ladder (27274).
    """
    needle = norm_space(row.get("value_text"))
    if not needle or is_statement_table(row, text) or _is_table_rows(text):
        return False
    hits = [norm_space(line) for line in str(text or "").splitlines() if text_has(line, needle)]
    if not hits:
        return False
    if _label_beside_value(text, needle):
        return False                   # stage J: the value's own data label sits next to it, not an axis tick
    if all(_tick_ladder(_numbers_in(line)) for line in hits):
        return True
    if not all(_is_bare_number(line) for line in hits):
        return False                   # the value sits inside a printed label or sentence: a data value, not a tick
    try:
        raw_value = row.get("value")
        number = float(raw_value) if raw_value is not None else _numbers_in(needle)[0]
    except (TypeError, ValueError, IndexError):
        return False
    return any(abs(number - tick) <= max(1e-9, abs(tick) * 1e-6) for tick in page_tick_values(text))


def declared_measure(measure: str, definition: str, node: str,
                     measures: dict[str, dict[str, str]]) -> tuple[str, str]:
    """(stored measure, verdict) -- '' verdict when the measure is usable (T-238 stage M).

    A dictionary id is usable.  So is ``NEW:<snake_case>`` WITH a one-line definition and one of the driver nodes; it
    is stored as-is (the row may verify, the id is indexed in ``measure_new``).  A bare id that is neither is
    ``undeclared_new`` and never verifies: the reader may not invent measure names silently.
    """
    measure = canonical_new_measure(measure)
    if not measure:
        return "", "measure_missing: no dictionary id and no NEW:<id>"
    if measure in measures:
        return measure, ""
    if not measure.startswith(NEW_PREFIX):
        return measure, f"undeclared_new: {measure!r} is neither a dictionary id nor NEW:<id>"
    if junk_measure(measure):
        return measure, f"junk_measure: {measure} is letterhead/date data, not a business quantity"
    new_id = measure[len(NEW_PREFIX):]
    if not NEW_ID_RE.match(new_id):
        return measure, f"new_id_bad: {new_id!r} is not a lower-case snake_case id"
    if not norm_space(definition):
        return measure, "new_definition_missing: a NEW:<id> needs one line saying what the printed quantity is"
    if norm_space(node).lower() not in NEW_NODES:
        return measure, (f"new_driver_node_missing: {norm_space(node)!r} is not one of "
                         f"{'/'.join(NEW_NODES)}")
    return measure, ""


def is_declared_new(row: dict[str, Any]) -> bool:
    return bool(norm_space(row.get("measure")).startswith(NEW_PREFIX)
                and norm_space(row.get("new_definition")) and norm_space(row.get("new_driver_node")))


def period_in_text(period: str, sentence: str) -> bool:
    """True when the guidance period's own words are printed in the sentence ('FY27' also reads '2027')."""
    period_s = norm_space(period)
    if not period_s:
        return False
    flat_period = re.sub(r"[^a-z0-9]", "", period_s.lower())
    flat_sentence = re.sub(r"[^a-z0-9]", "", norm_space(sentence).lower())
    if flat_period and flat_period in flat_sentence:
        return True
    for year in re.findall(r"(?:19|20)\d{2}", period_s):
        if year in sentence:
            return True
    for short in re.findall(r"\bFY\s?-?(\d{2})\b", period_s, re.I):
        for year in ("20" + short, "20" + str(int(short) + 1)):
            if year in sentence:
                return True
    return False


# --------------------------------------------------------------------------- stage O: statements as whole passages
STATEMENT_END_RE = re.compile("[.!?][\"')\\]\u2019\u201d]?$")
STATEMENT_END_WORDS = {"and", "the", "of", "to", "in"}
STATEMENT_PRONOUNS = {"it", "it's", "its", "this", "that", "these", "those", "they", "them", "their", "there",
                      "we", "our", "us", "i", "you", "your", "he", "she", "him", "his", "her"}
STATEMENT_NON_NOUN = STATEMENT_PRONOUNS | {
    "the", "a", "an", "some", "any", "all", "no", "not", "every", "each", "both", "much", "more", "most", "less",
    "few", "several", "such", "another", "same", "other", "own", "only", "just", "also", "very", "really", "quite",
    "too", "still", "even", "now", "then", "so", "but", "and", "or", "well", "okay", "yes", "yeah", "obviously",
    "basically", "actually", "probably", "maybe", "perhaps", "again", "because", "if", "when", "as", "for", "of",
    "to", "in", "on", "at", "with", "by", "from", "about", "over", "under", "than", "which", "who", "what", "how",
    "why", "where"}
STATEMENT_VERBS = {"is", "are", "was", "were", "am", "be", "been", "being", "has", "have", "had", "do", "does",
                   "did", "will", "would", "shall", "should", "can", "could", "may", "might", "must", "go", "goes",
                   "going", "went", "get", "gets", "getting", "got", "expect", "expects", "think", "believe",
                   "see", "sees", "look", "looks", "seem", "seems", "need", "needs", "want", "wants", "hope",
                   "hopes", "say", "says", "said", "feel", "feels", "know", "knows", "come", "comes", "came",
                   "become", "becomes", "became", "remain", "remains", "remained", "continue", "continues",
                   "hold", "holds", "held", "maintain", "maintains", "maintained", "grow", "grows", "growing",
                   "grew", "improve", "improves", "improved", "increase", "increases", "decrease", "decreases",
                   "take", "takes", "took", "make", "makes", "made", "keep", "keeps", "kept", "show", "shows",
                   "anticipate", "assume", "tell", "told", "give", "gives", "given", "let", "put", "move", "moving",
                   "work", "works", "stay", "stays", "stand", "stands", "reach", "reaches", "deliver", "delivers"}


def statement_cut_reason(sentence: str) -> str:
    """T-238 stage O: '' when a statement ends at its last full stop, else why it was cut (quarantined).

    The reader cut passages at PDF line breaks in stage M ("... under pressure in terms of pricing and"), so a
    passage with no terminal punctuation or ending on and/the/of/to/in is a print artefact, not a statement.
    """
    text = norm_space(sentence).rstrip()
    if not text:
        return ""
    if not STATEMENT_END_RE.search(text):
        return "statement_cut: no terminal punctuation (cut at a PDF line break?)"
    tail = re.sub(r"[^a-z']", "", text.rstrip("\"')\u201d\u2019").rsplit(None, 1)[-1].lower())
    if tail in STATEMENT_END_WORDS:
        return f"statement_cut: ends on the function word {tail!r}"
    return ""


def statement_no_subject(sentence: str) -> bool:
    """T-238 stage O: True for a bare pronoun passage that names nothing and carries no measure.

    From the diagnosis: "It's going to be about the same." has no noun anywhere, so neither the row nor its measure
    says what it is about.  A whole passage that names anything ("I would go through the market dynamics ...", "We
    hold our prices") and a passage carrying a measure ("It is about 2.5%.") are not flagged; the opening subject may
    still be a pronoun.
    """
    if re.search(r"\d", sentence):
        return False
    tokens = [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z'\-]*", sentence)]
    return bool(tokens) and all(word in STATEMENT_NON_NOUN or word in STATEMENT_VERBS for word in tokens)


def evaluate_statement(row: dict[str, Any], hay_match: str,
                       measures: dict[str, dict[str, str]]) -> tuple[str, list[str]]:
    """T-238 stage M: a statement verifies when its verbatim sentence is in the page text and its measure is usable.

    Stage O: a statement is a whole passage, so one cut at a PDF line break (no terminal punctuation, or ending on
    and/the/of/to/in) is quarantined rather than kept as a half sentence; a passage that names nothing beyond
    pronouns/function words and carries no measure is unverified ``no_subject`` ("It's going to be about the same.").
    """
    reasons: list[str] = []
    _measure, why = declared_measure(row.get("measure", ""), row.get("new_definition", ""),
                                     row.get("new_driver_node", ""), measures)
    if why:
        reasons.append(why)
    sentence = norm_space(row.get("statement"))
    if not sentence:
        reasons.append("statement_missing: no verbatim sentence")
    else:
        cut = statement_cut_reason(sentence)
        if cut:
            reasons.append(cut)
            return "quarantined", reasons
        if norm_match(sentence) not in hay_match:
            reasons.append("statement_not_printed: the sentence is not in the page text")
        if statement_no_subject(sentence):
            reasons.append("no_subject: the passage has no noun subject beyond pronouns and no measure")
    return ("unverified" if reasons else "verified"), reasons


def _apply_scale(row: dict[str, Any], raw: dict[str, Any], text: str, page_text: str,
                 head: str, measure: dict[str, str] | None) -> list[str]:
    """Apply the printed-scale / money-scale / per-unit scale rules to one observation row."""
    row["scale"], scale_notes = printed_scale(raw.get("scale", 1), row, text)
    row["unit_family"] = infer_unit_family(row["unit"]) or row.get("unit_family", "")
    if row["unit_family"] == "money" and float(row["scale"] or 1) == 1:
        factor = money_scale([row["unit"], row["printed_axis"], row["series_title"], head])
        if factor:
            row["scale"] = factor
    if (row["unit"] or "").strip().upper() in MT_UNITS and float(row["scale"] or 1) == 1:
        resolved = resolve_mt_scale(page_text)
        if resolved:
            row["scale"] = resolved
    measure_family = measure["unit_family"] if measure else row["unit_family"]
    if apply_per_unit_scale(row, measure_family):
        scale_notes = []           # a crore scale on a per-unit price is never a printed scale
    return scale_notes


def evaluate_guidance(row: dict[str, Any], hay_match: str,
                      measures: dict[str, dict[str, str]]) -> tuple[str, list[str]]:
    """T-238 stage M: guidance verifies when its sentence is printed and its value and period words are in it."""
    reasons: list[str] = list(row.pop("_scale_notes", []))
    _measure, why = declared_measure(row.get("measure", ""), row.get("new_definition", ""),
                                     row.get("new_driver_node", ""), measures)
    if why:
        reasons.append(why)
    sentence = norm_space(row.get("statement"))
    if not sentence:
        reasons.append("statement_missing: no verbatim sentence")
    elif norm_match(sentence) not in hay_match:
        reasons.append("statement_not_printed: the sentence is not in the page text")
    tokens = re.findall(r"\d[\d,.]*", norm_space(row.get("value_text")))
    if not tokens:
        reasons.append("guidance_value_missing: no printed low/high value")
    missing = [token for token in tokens if not text_has(sentence, token)]
    if missing:
        reasons.append(f"guidance_value_not_in_sentence: {', '.join(missing)}")
    if not row.get("period"):
        reasons.append("no_period: guidance needs its target period as printed")
    elif not period_in_text(row.get("period", ""), sentence):
        reasons.append(f"guidance_period_not_in_sentence: {row.get('period')!r}")
    return ("unverified" if reasons else "verified"), reasons


def _record_row(*, symbol: str, doc_key: str, page: int, known_at: str, record_type: str,
                raw: dict[str, Any]) -> dict[str, Any]:
    """Every OBS_COLUMNS key for a statement / guidance record (the number path builds its own row)."""
    direction = norm_space(raw.get("direction")).lower()
    return {
        "symbol": symbol, "doc_key": doc_key, "page": int(page), "region": "", "known_at": known_at,
        "measure": norm_space(raw.get("measure")), "printed_label": "", "printed_axis": "", "value": None,
        "value_text": "", "unit": norm_space(raw.get("unit")), "unit_family": "", "scale": 1.0,
        "adjusted": 0, "value_kind": "", "is_total": 0, "period": norm_space(raw.get("period")),
        "period_kind": "", "period_source": "", "basis": "", "basis_source": "", "series_kind": "", "segment": "",
        "product": "", "geography": "", "plant": "", "customer": "", "group_path": "", "group_source": "",
        "group_check": "", "stage": "", "series_id": "", "series_title": "",
        "entity_scope": canonical_scope(norm_space(raw.get("entity_scope"))), "text_source": "",
        "record_type": record_type, "statement": norm_space(raw.get("text") or raw.get("statement")),
        "speaker": norm_space(raw.get("speaker"))[:200],
        "direction": direction if direction in ("up", "down", "flat") else "",
        "question_context": norm_space(raw.get("question_context"))[:500],
        "value_high": None, "new_definition": norm_space(raw.get("new_definition")),
        "new_driver_node": norm_space(raw.get("new_driver_node")).lower(),
        "status": "unverified", "status_reason": "",
        "reader": READER, "read_at": datetime.now().isoformat(timespec="seconds"),
    }


def statement_observation(*, symbol: str, doc_key: str, page: int, known_at: str, raw: dict[str, Any],
                          hay_match: str, measures: dict[str, dict[str, str]]) -> dict[str, Any] | None:
    if len(norm_space(raw.get("text") or raw.get("statement")).split()) < 3:
        return None                      # a greeting, a speaker tag or a heading is not a statement
    row = _record_row(symbol=symbol, doc_key=doc_key, page=page, known_at=known_at,
                      record_type="statement", raw=raw)
    row["status"], reasons = evaluate_statement(row, hay_match, measures)
    row["status_reason"] = "; ".join(reasons)
    return row


def guidance_observation(*, symbol: str, doc_key: str, page: int, known_at: str, raw: dict[str, Any],
                         hay_match: str, measures: dict[str, dict[str, str]],
                         page_text: str = "") -> dict[str, Any] | None:
    low_text = norm_space(raw.get("low") or raw.get("value_text"))
    high_text = norm_space(raw.get("high"))
    low, high = parse_number(low_text), parse_number(high_text)
    if low is None and high is None:
        return None                      # worded guidance without a number stays a statement
    row = _record_row(symbol=symbol, doc_key=doc_key, page=page, known_at=known_at,
                      record_type="guidance", raw=raw)
    row["value"] = low if low is not None else high
    row["value_high"] = high
    if not row["unit"] and low_text.rstrip().endswith("%"):
        row["unit"] = "%"                # T-241: a printed "60%" target keeps its percent unit
    row["value_text"] = low_text if high_text in ("", low_text) else f"{low_text}-{high_text}"
    row["period_kind"] = period_kind_for(raw.get("period_kind", ""), row["period"]) or "target"
    row["statement"] = norm_space(raw.get("text") or raw.get("statement"))
    row["_scale_notes"] = _apply_scale(row, raw, norm_space(page_text), page_text, page_head(page_text),
                                       measures.get(row["measure"]))
    row["status"], reasons = evaluate_guidance(row, hay_match, measures)
    row["status_reason"] = "; ".join(reasons)
    return row


def apply_guidance_statements(prose: list[dict[str, Any]]) -> int:
    """T-238 stage O: a guidance row's value must also appear as a statement row on its page.

    A guidance row keeps the number; the statement row keeps the sentence that carries the correction ("not
    adhesive, building solutions") and its attribution.  A page where no statement row carries the value is flagged
    ``guidance_without_statement`` in its reason, so the page is read again; the guidance row's own check (sentence,
    value and period printed) still decides its status.
    """
    statements: dict[tuple[str, int], list[str]] = {}
    for row in prose:
        if row.get("record_type") == "statement":
            statements.setdefault((str(row.get("doc_key")), int(row.get("page") or 0)), []).append(
                str(row.get("statement") or ""))
    flagged = 0
    for row in prose:
        if row.get("record_type") != "guidance":
            continue
        values = re.findall(r"\d[\d,.]*", norm_space(row.get("value_text")))
        page_statements = statements.get((str(row.get("doc_key")), int(row.get("page") or 0)), [])
        if any(all(text_has(sentence, value) for value in values) for sentence in page_statements):
            continue
        flagged += 1
        reason = "guidance_without_statement: no statement row on this page carries its value"
        row["status_reason"] = "; ".join(part for part in (str(row.get("status_reason") or ""), reason) if part)
    return flagged


def is_not_a_measure(row: dict[str, Any]) -> bool:
    text = " ".join([row.get("printed_label") or "", row.get("measure") or "", row.get("printed_axis") or ""])
    return NOT_A_MEASURE_RE.search(text) is not None


def evaluate_status(row: dict[str, Any], text: str, measures: dict[str, dict[str, str]],
                    raw_text: str = "", ocr_text: str = "", ocr_page: bool = False) -> tuple[str, list[str]]:
    """Re-apply every script check to one row (used by the reader and by --recheck).

    Stage H: the text layer is the first check and the OCR of the page image the second, so a value printed only
    inside a chart image verifies with ``text_source='ocr'``; a value neither source carries is unverified
    (``image_text``), never quarantined -- Wolf's audit had 37 correct image-only rows sitting in quarantine.
    T-238: ``ocr_page`` marks a page whose reading input IS the stored OCR words (the text layer was unusable):
    every printed check has run against those words and the row carries ``text_source='ocr'``.
    """
    reasons = list(row.pop("_scale_notes", []))
    row["text_source"] = ""
    if is_not_a_measure(row):
        return "quarantined", reasons + ["not_a_measure: director/tenure row, not a business quantity"]
    if row.get("adjusted"):
        reasons.append("adjusted/hypothetical figure, not the reported measure")
    layer = str(text or "")
    ocr = str(ocr_text or "")
    hay = norm_space(layer + "\n" + ocr)
    hay_match = norm_match(hay)
    if not hay:
        return "unverified", reasons + ["no text layer on this page; value not checkable"]
    in_layer = value_printed(layer, row.get("value_text", ""))
    in_ocr = value_printed(ocr, row.get("value_text", ""))
    if not in_layer and not in_ocr:
        return "unverified", reasons + [
            "image_text: the value is printed in the page image, not in its text layer or OCR"]
    row["text_source"] = "ocr" if (ocr_page or not in_layer) else "text_layer"
    status = "unverified" if reasons else "verified"
    for field in ("printed_label", "printed_axis", "group_path"):
        if not row.get(field):
            continue
        parts = row[field].split(" > ") if field == "group_path" else [row[field]]
        missing = [part for part in parts if part and norm_match(part) not in hay_match]
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
    _stored, measure_verdict = declared_measure(row.get("measure", ""), row.get("new_definition", ""),
                                                row.get("new_driver_node", ""), measures)
    if measure_verdict:
        status = "unverified"
        reasons.append(measure_verdict)
    elif measure is None:
        row["new_measure"] = 1            # a DECLARED NEW id: allowed, indexed in measure_new
    elif row.get("unit_family") and not family_ok(measure["unit_family"], row["unit_family"]):
        status = "unverified"
        reasons.append(f"unit family {row['unit_family']!r} does not match measure {row['measure']!r} "
                       f"({measure['unit_family']!r})")
    generic = generic_label_reason(row)          # stage L: a category word is not the measure's name
    if generic:
        status = "unverified"
        reasons.append(generic)
    if measure is not None and measure["unit_family"] == "money":
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
        "money", "money_per_unit", "capacity", "count", "length", "area", "time", "energy")
    if required_unit and not row.get("unit") and not str(row.get("measure") or "").startswith("count."):
        status = "unverified"           # stage H: a count.* row is its own unit ("14 outlets"); the count is the unit
        reasons.append("no_unit: no unit printed for this money/quantity row")
    if not row.get("period") or not period_is_printed(row.get("period", "")):
        status = "unverified"
        reasons.append("no_period: no period printed for this row")
    if (row.get("value_kind") or "") == "lower_bound":
        status = "unverified"
        reasons.append("lower_bound: the page prints a threshold ('more than' / 'crossed'), not the actual figure")
    return status, reasons


MIX_MEASURE_RE = re.compile(
    r"^(?:revenue\.mix|mix\.share|volume\.mix)$|_(?:mix|(?<!per_)share)$",   # a total order book needs no part
    re.I,
)
_MIX_PREFIX_RE = re.compile(
    r"^(?:out\s+of\s+(?:which|that|the)|share\s+of|mix\s+of|portion\s+of|part\s+of|"
    r"contribution\s+(?:of|from)|came\s+from|comes\s+from|coming\s+from|"
    r"contributed\s+by|accounted\s+for\s+by|close\s+to|at\s+around|right\s+now|"
    r"and|or|while|whereas|which|that|this|these|those|it|we|our|its|their|"
    r"the|an?|of|for|from|in|at|to|by|on|with|only|around|about|nearly|"
    r"approximately|approx\.?|roughly|almost|is|are|was|were|has|have|had|been|be|become|"
    r"giving|give|kept|keep|currently|today)"
    r"(?:$|\s+|[,;:]\s*)",
    re.I,
)
_MIX_SUFFIX_RE = re.compile(
    r"(?:^|\s+|[,;:]\s*)"
    r"(?:contributed\s+to|contributed|contribute|contributes|contributing|"
    r"accounts\s+for|accounted\s+for|account\s+for|"
    r"stood\s+at|stands\s+at|stand\s+at|"
    r"constitutes|constitute|constituted|"
    r"comprises\s+of|comprises|comprise|comprised|"
    r"has\s+become|became|become|"
    r"(?:is|are|was|were)\s+at|which\s+(?:is|was)|that\s+(?:is|was)|close\s+to|right\s+now|"
    r"is|are|was|were|will\s+be|would\s+be|be|has|have|had|"
    r"to|of|at|by|for|from|in|around|about|nearly|approximately|approx\.?|"
    r"roughly|almost|only|which|that|and|or|while|\d+(?:\.\d+)?%)$",
    re.I,
)
_MIX_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "while", "whereas", "which", "that", "this", "these", "those",
    "it", "its", "we", "our", "us", "they", "their", "them", "i", "you", "your",
    "of", "at", "in", "on", "to", "for", "from", "by", "with", "out", "into", "as",
    "is", "are", "was", "were", "be", "been", "being", "will", "would", "has", "have", "had", "become", "became",
    "around", "about", "nearly", "approximately", "approx", "roughly", "almost", "only", "close",
    "share", "mix", "part", "portion", "total", "contributed", "contribute", "contributes", "contributing",
    "accounts", "accounted", "account", "stood", "stands", "stand", "constitutes", "constitute", "constituted",
    "comprises", "comprise", "comprised", "came", "comes", "coming",
    "giving", "give", "kept", "keep", "right", "now", "currently", "today",
})


def mix_part(label: str) -> str:
    """Extract the named part (segment/product/geo/customer) from a mix printed_label, else ''."""
    s = norm_space(label).strip(" ,;:-.()[]\"'")
    while s:
        nxt = _MIX_PREFIX_RE.sub("", s)
        nxt = _MIX_SUFFIX_RE.sub("", nxt).strip(" ,;:-.()[]\"'")
        if nxt == s:
            break
        s = nxt
    if not s or not re.search(r"[a-zA-Z]", s):
        return ""
    words = s.split()
    if len(words) > 6:
        return ""
    if all((not re.search(r"[a-z]", w.lower()) or re.sub(r"[^a-z0-9]", "", w.lower()) in _MIX_STOP_WORDS)
           for w in words):
        return ""
    return s


def build_observations(*, symbol: str, doc_key: str, page: int, known_at: str, page_text: str,
                       words: Iterable[tuple[float, float, float, float, str]] = (),
                       reply_rows: Iterable[dict[str, Any]] = (),
                       measures: dict[str, dict[str, str]] | None = None,
                       vocab: dict[tuple[str, str], str] | None = None,
                       doc_owner_symbol: str = "",
                       companies: dict[str, tuple[str, str]] | None = None,
                       deck_asof: str = "", deck_basis: str = "",
                       ocr_text: str = "", ocr_page: bool = False,
                       transcript_v2: bool = False, deck_guards: bool = False) -> list[dict[str, Any]]:
    """Model reply objects -> checked observation rows (status and status_reason set here).

    ``deck_guards`` (T-242, deck pages only): a growth/change row printed after a decrease word is negative, and a
    page-1/2 filing cover letter gives no rows.
    """
    measures = measures if measures is not None else measure_index()
    vocab = vocab if vocab is not None else vocab_index()
    word_list = list(words)
    reply_rows = list(reply_rows)
    text = norm_space(page_text)
    page_groups = {part for raw in reply_rows if isinstance(raw, dict)
                   for part in norm_space(raw.get("group_path")).split(" > ") if part}
    legend_groups = detect_legend(word_list, page_groups)
    if (transcript_v2 or deck_guards) and is_cover_letter(page_text, page):
        return []                              # T-241 guard 3: a filing cover letter is not part of the call
    out: list[dict[str, Any]] = []
    prose: list[dict[str, Any]] = []          # stage M: statement / guidance records, never number-checked
    hay_match = norm_match(norm_space(text + "\n" + ocr_text))
    for raw in reply_rows:
        if not isinstance(raw, dict):
            continue
        record_type = norm_space(raw.get("type") or "number").lower()
        if record_type not in RECORD_TYPES:
            record_type = "number"
        if record_type == "guidance" and norm_space(raw.get("claim_type")).lower() not in ("", "company_target"):
            continue                 # T-241 v2: a government / industry target or an ask is not company guidance
        if (record_type == "guidance" and (transcript_v2 or "claim_type" in raw)
                and PERIOD_VALUE_RE.match(norm_space(raw.get("low") or raw.get("value_text")))):
            continue                 # T-241 guard 2: "H1FY28" read as a target of 1 is a period, not a value
        if record_type in ("statement", "guidance"):
            if record_type == "statement":
                record = statement_observation(symbol=symbol, doc_key=doc_key, page=page, known_at=known_at,
                                               raw=raw, hay_match=hay_match, measures=measures)
            else:
                record = guidance_observation(symbol=symbol, doc_key=doc_key, page=page, known_at=known_at,
                                              raw=raw, hay_match=hay_match, measures=measures, page_text=page_text)
            if record is not None and record["record_type"] == "guidance" and (transcript_v2 or "claim_type" in raw):
                if record["value_high"] is not None and record["value"] is not None \
                        and record["value_high"] < record["value"]:
                    record["value_high"] = None      # T-241 guard 4: "20% or 10%" is no range
                if record["value_high"] is None:      # T-241 guard 5: the printed upper end
                    low_text = norm_space(raw.get("low") or raw.get("value_text"))
                    record["value_high"] = (printed_range_high(record["statement"], low_text, record["value"])
                                            or printed_range_high(page_text, low_text, record["value"]))
            if record is not None:
                prose.append(record)
            continue
        claim = norm_space(raw.get("claim_type")).lower()
        if claim in NOT_A_COMPANY_FIGURE:
            continue                 # T-241 v2: a hypothetical, an expectation or an ask stays in its statement
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
        if (claim or transcript_v2) and PERIOD_VALUE_RE.match(value_text):
            continue                 # T-241 guard 2: a period label ("Q2", "FY27", "H1FY28") is not a value
        if ((claim or transcript_v2) and label.strip().lower().rstrip(".:") in BARE_LABEL
                and RANGE_START_RE.search(_before(page_text, value_text, 40))):
            continue                 # T-242 guard 7: "310 to INR320" -- the 320 row repeats the range's upper end
        row: dict[str, Any] = {key: norm_space(raw.get(key)) for key in ROW_TEXT_KEYS}
        if junk_measure(row["measure"]):
            continue                 # page number, phone, address, PIN, CIN/DIN, signature date: not a quantity
        row.update({
            "symbol": symbol, "doc_key": doc_key, "page": int(page), "known_at": known_at,
            "value_text": value_text, "value": value,
            "period_kind": period_kind_for(raw.get("period_kind", ""), row["period"]),
            "period_source": "",
            "basis": "",
            "basis_source": "",
            "series_kind": "level",
            "series_id": row["series_id"] or "s1",
            "region": region_for(word_list, value_text),
            "group_source": canonical_group_source(raw.get("group_source", "")),
            "group_check": "",
            "adjusted": 0,
            "value_kind": "",
            "text_source": "",
            "reader": READER, "read_at": datetime.now().isoformat(timespec="seconds"),
            "is_total": 0,
            "_is_total": raw.get("is_total") is True or str(raw.get("is_total", "")).lower() in ("true", "yes", "1"),
            "record_type": "number", "statement": "", "speaker": "", "direction": "", "value_high": None,
            "question_context": "",
            "new_definition": norm_space(raw.get("new_definition")),
            "new_driver_node": norm_space(raw.get("new_driver_node")).lower(),
        })
        row["is_total"] = 1 if row["_is_total"] else 0
        # T-241 v2 transcript prompt: the range's upper end, the sign of a fall, the speaker and the printed period
        # words; a v1 reply carries none of these keys, so its rows are unchanged
        high_text = norm_space(raw.get("high_text"))
        if high_text:
            row["value_high"] = parse_number(high_text)
        if (claim or transcript_v2) and BY_CHANGE_RE.search(label) and not SIGNED_MEASURE.search(row["measure"]):
            # T-241 v2e: "inventory days have decreased by 8" is a change, never the level (Wolf v2d #40)
            root = canonical_new_measure(row["measure"]).removeprefix(NEW_PREFIX)
            row["measure"] = f"{NEW_PREFIX}{root}_change"
            row["new_definition"] = row["new_definition"] or f"change in {root} over the period, as stated ('by X')"
            if re.search(r"decreas|reduc|declin|fell|drop|down", label, re.I) and row["value"] is not None:
                row["value"] = -abs(row["value"])
                row["direction"] = "down"
        if (norm_space(raw.get("sign")) == "-" and row["value"] is not None and row["value"] > 0
                and SIGNED_MEASURE.search(row["measure"] + " " + row["unit"])):
            low, high = row["value"], row["value_high"]      # T-242: a range flips as a whole
            row["value"], row["value_high"] = (-high, -low) if high is not None and high > 0 else (-low, high)
            row["direction"] = "down"
        if raw.get("speaker"):
            row["speaker"] = norm_space(raw.get("speaker"))[:200]
        printed = norm_space(raw.get("period_printed"))
        if printed and printed != row["period"]:
            row["period_source"] = printed[:120]
        if claim or transcript_v2:
            if row["value_high"] is None and not high_text:
                both = inner_range(value_text)          # T-242 guard 6: "40%-45%" is one printed range
                if both:
                    row["value"], row["value_high"] = both
            frac = FRACTION_RE.match(value_text)
            if frac and int(frac.group(2)) > int(frac.group(1)) > 0:
                row["value"] = round(100.0 * int(frac.group(1)) / int(frac.group(2)), 2)   # T-242 guard 8: 1/3
                row["unit"], row["scale"] = "%", 1.0
            if row["measure"] == "nim" and (COST_OF_FUNDS_RE.search(label)
                                            or COST_OF_FUNDS_RE.search(_before(page_text, value_text, 60))):
                row["measure"] = "cost_of_funds"     # T-242 guard 9: "borrowing at 6.3%" is a cost, not a margin
            extra = word_fraction(value_text)
            if extra and row["value"] is not None and float(row["value"]).is_integer():
                row["value"] = row["value"] + extra     # T-242 guard 10: "14 and a half percent" is 14.5
            if row["value_high"] is not None and row["value"] is not None and row["value_high"] < row["value"]:
                row["value_high"] = None       # T-241 guard 4: a high below the low is no range
            if row["value_high"] is None and not high_text and row["value"] is not None:
                high = printed_range_high(page_text, value_text, abs(row["value"]))   # T-241 guard 5
                if high is not None and row["value"] < 0:
                    row["value"], high = -high, row["value"]     # "-25 ... to 30 bps reduction" is -30..-25
                row["value_high"] = high
            if (row["value"] is not None and row["value"] > 0 and not SIGNED_MEASURE.search(row["measure"])
                    and "loss" not in row["measure"].lower() and negative_printed(label, page_text, value_text)):
                # T-241 guard 1: "stood at negative Rs27 crore" is -27; T-242: a range flips as a whole,
                # so "25 to 30 bps reduction" is -30..-25, never -25..+30
                low, high = row["value"], row["value_high"]
                row["value"], row["value_high"] = (-high, -low) if high is not None else (-low, None)
        elif (deck_guards and row["value"] is not None and row["value"] > 0 and SIGNED_MEASURE.search(row["measure"])
              and (DECREASE_RE.search(label) or DECREASE_RE.search(_clause_before(page_text, value_text, 40)))):
            row["value"] = -row["value"]   # T-242 deck guard: "EBITDA decreased 79%", "negative growth 1.9%"
            row["direction"] = "down"
        if not row["unit"] and value_text.rstrip().endswith("%"):
            row["unit"] = "%"            # T-241: a printed "12%" keeps its percent unit
        if claim == "third_party" and row["entity_scope"] in ("", "company", "parent"):
            row["entity_scope"] = "industry"
        for dim in DIMS:
            row[dim] = canonical_dim(vocab, dim, row.get(dim, ""))
        row["stage"] = canonical_stage(vocab, row.get("stage", "")) or stage_from_group(vocab, row["group_path"])
        if not row["group_path"]:
            row["group_source"] = ""
        elif any(part in legend_groups for part in row["group_path"].split(" > ")):
            row["group_source"] = "legend_inferred"
        row["entity_scope"] = canonical_scope(row["entity_scope"])
        head = page_head(page_text)          # the printed page head, not the collapsed whole page (recheck parity)
        if detect_subsidiary([row["printed_axis"], row["series_title"], head], companies or {}, symbol):
            if row["entity_scope"] in ("company", "parent", ""):
                row["entity_scope"] = "subsidiary"
        row["basis"] = detect_basis(row["printed_axis"], row["series_title"], head, word_list, row["region"],
                                    row["group_path"], page_text)
        if not row["basis"]:                      # stage K: the printed standalone/consolidated header over the value
            row["basis"] = column_basis(word_list, row["region"])
        if not row["basis"]:                      # stage L: the page/section heading names the basis
            row["basis"] = page_basis(page_text)
        if claim or transcript_v2:                # T-241 v2 (transcript): the latest standalone/consolidated
            row["basis"] = (section_basis(page_text, row["printed_label"], value_text)   # words before it
                            or (norm_space(raw.get("basis")).lower()
                                if norm_space(raw.get("basis")).lower() in ("standalone", "consolidated") else ""))
        row["measure"] = canonical_measure(row["measure"], row["printed_label"], row["printed_axis"],
                                           row["series_title"], row["unit"], text)
        cagr = cagr_measure(row["measure"], row["printed_label"], row["printed_axis"], row["series_title"], page_text,
                            value_text)
        if cagr:
            row["measure"], span = cagr
            if span:
                row["period"] = span
                row["period_source"] = ""
                row["period_kind"] = "span"
        measure = measures.get(row["measure"])
        if not row["basis"] and deck_basis and measure and measure["unit_family"] == "money":
            row["basis"] = deck_basis              # stage N: the deck prints one basis only
            row["basis_source"] = "deck"
        if not row["unit"]:
            inferred = infer_unit([row["printed_axis"], row["series_title"], row["printed_label"]],
                                  measure["unit_family"] if measure else "")
            if inferred:
                row["unit"], row["unit_family"], row["scale"] = inferred
        scale_notes = _apply_scale(row, raw, text, page_text, head, measure)
        if ((claim or transcript_v2) and measure and measure["unit_family"] == "percent" and not row["unit"]
                and not UNIT_IN_TEXT_RE.search(value_text)
                and not UNIT_IN_TEXT_RE.search(page_text_after(page_text, value_text, 14))):
            scale_notes.append("no_unit: a ratio printed without its %, bps or x")   # T-242 guard 11
        if row["period"] and comparative_period(
                row["period"], page_text, " ".join([row["printed_label"], row["printed_axis"]])):
            row["period"] = ""         # stage L: a date inside "(31 March 2024 : NIL)" is not this row's period
            row["period_source"] = ""
            row["period_kind"] = ""
        if not row["period"]:
            row["period"] = infer_period([strip_comparatives(t) for t in
                                          [row["printed_axis"], row["series_title"], row["group_path"],
                                           row["printed_label"]]])
            row["period_kind"] = period_kind_for(raw.get("period_kind", ""), row["period"])
        if not row["period"]:                     # stage K: the printed column header year over the value
            header_period = column_period(word_list, row["region"])
            if header_period:
                row["period"] = header_period
                row["period_source"] = "column_header"
                row["period_kind"] = period_kind_for(raw.get("period_kind", ""), row["period"])
        if not row["period"]:                     # stage N: the period the slide's own title names
            title_period = slide_period(page_text)
            stock_ok = (not is_stock_measure(row["measure"])) or capacity_deck_period_ok(row, page_text)
            if title_period and stock_ok:
                row["period"] = title_period
                row["period_source"] = "slide_title"
                row["period_kind"] = period_kind_for(raw.get("period_kind", ""), title_period)
        if not row["period"] and deck_asof and deck_asof_allowed(row, page_text):
            row["period"] = deck_asof
            row["period_source"] = "deck_asof"
            row["period_kind"] = period_kind_for("", deck_asof)
        if row["period"] and not period_is_printed(row["period"]):
            row["period"] = ""
            row["period_source"] = ""
            row["period"] = infer_period([strip_comparatives(t) for t in
                                          [row["printed_axis"], row["series_title"], row["group_path"],
                                           row["printed_label"], head]])
            row["period_kind"] = period_kind_for(raw.get("period_kind", ""), row["period"])
        row["period"] = growth_change_period(row["period"], row["measure"], page_text)  # stage N2: the later of a pair
        apply_instant_period(row)                  # stage L: "Closing as on <date>" is a point in time
        foot = footnote_basis(page_text, row["period"]) if row["period"] else ""
        if foot:
            row["basis"] = foot
            row["basis_source"] = ""
        cue = scope_cue(row, page_text)
        if cue:
            row["entity_scope"] = cue
            if cue == "customer" and not row["customer"]:
                heading = " | ".join([row["series_title"], row["printed_label"], row["printed_axis"]])
                row["customer"] = client_name(heading) or norm_space(row["series_title"]) or \
                    norm_space(row["printed_label"])
        row["value_kind"] = lower_bound_kind(row)
        row["adjusted"] = 1 if ADJUSTED_RE.search(" ".join(
            [row["printed_label"], row["printed_axis"], row["series_title"]])) else 0
        if doc_owner_symbol and row["entity_scope"] in ("company", "subsidiary", ""):
            row["entity_scope"] = "parent"
        # T-241: a share/mix/order-book row must name which part it covers (segment, product, geography or customer)
        if MIX_MEASURE_RE.search(row["measure"]) and not any(
                row[dim] for dim in ("segment", "product", "geography", "customer")):
            part = mix_part(row["printed_label"])
            if part:
                row["segment"] = canonical_dim(vocab, "segment", part)
            else:
                scale_notes.append("mix_without_segment: a share row must name its part")
        if (deck_guards or transcript_v2) and row["measure"].startswith("NEW:") and not row["unit"]:
            scale_notes.append("no_unit: a new measure with no unit printed")   # T-242 deck grade: "Regulation 30"
        row["_scale_notes"] = scale_notes
        row["status"], reasons = evaluate_status(row, text, measures, page_text, ocr_text, ocr_page)
        row["status_reason"] = "; ".join(reasons)
        out.append(row)
    out = apply_map_orphans(out)
    split_panels(out)
    apply_geography(out, word_list)
    apply_stacked_parts(out)
    apply_rank_count(out)
    apply_parts_sum(out)
    apply_path_sum(out)
    apply_series_kind(out, text)
    apply_basis_conflicts(out)
    apply_guidance_statements(prose)          # stage O: a guidance value also needs its statement row
    return out + prose


def measure_root(measure_id: str) -> str:
    return norm_space(measure_id).split(".", 1)[0]


def apply_parts_sum(rows: list[dict[str, Any]], stats: dict[str, Any] | None = None) -> None:
    """The rows a model marks as a printed total must equal the parts it printed in the same series and group.

    Membership is the reply's structure (series_id, group_path, is_total); the arithmetic is the script's.  Only a
    one-total group of 2-10 labelled rows whose measure shares the total's root (capacity.total with capacity.add,
    revenue.value with revenue.mix) is checked: a financial-highlights chart with revenue, EBITDA and PAT in one
    series never fires.

    Stage L: a proof needs two non-zero parts with two distinct values and a total that is not itself one of the
    parts.  An all-zero or all-equal group, or a "total" that is just one of its own rows, proves nothing (the
    rows keep their other reasons); an all-zero group verified 2,000+ stage-K annual-report rows.
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
        values = [float(r["value"]) for r in parts]
        if sum(1 for value in values if value != 0) < 2 or len({round(value, 9) for value in values}) < 2 \
                or any(abs(total_value - value) <= max(1e-9, abs(total_value) * 1e-9) for value in values):
            if stats is not None:
                stats["parts_degenerate"] = int(stats.get("parts_degenerate", 0)) + 1
            continue                 # stage L: a degenerate group is no proof
        part_sum = sum(values)
        tolerance = max(0.51, abs(total_value) * 0.005)
        if abs(part_sum - total_value) <= tolerance:
            for row in parts + totals:
                if "no_unit:" in row["status_reason"] or "no_period:" in row["status_reason"] or \
                        "adjusted/hypothetical" in row["status_reason"] or "image_text" in row["status_reason"] or \
                        "geography_not_printed" in row["status_reason"] or "stacked_part" in row["status_reason"] or \
                        "generic_label" in row["status_reason"] or "mix_without_segment" in row["status_reason"]:
                    continue         # a parts sum never overrides a hard gate (stage L adds generic_label)
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
    # T-241 (24 Nov): a reader of the output DB (a quality check, a row count) held a shared lock past sqlite's
    # default 5 s and the run died at commit with "database is locked"; wait instead.
    con = sqlite3.connect(str(path), timeout=120)
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
               "value", "value_text", "unit", "unit_family", "scale", "adjusted", "value_kind", "is_total",
               "period", "period_kind", "period_source", "basis", "basis_source", "series_kind", "segment", "product",
               "geography",
               "plant", "customer", "group_path", "group_source", "group_check", "stage", "series_id",
               "series_title", "entity_scope", "text_source", "record_type", "statement", "speaker", "direction",
               "question_context", "value_high", "new_definition", "new_driver_node", "status", "status_reason",
               "reader", "read_at")


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


# --------------------------------------------------------------------------- stage M: NEW measures and their merges

NEW_NAME_STOP = {"the", "and", "of", "for", "per", "from", "with", "total", "value", "amount", "count",
                 "number", "in", "on", "to", "a", "is", "as", "by", "its", "this", "that", "company",
                 "other", "net", "gross", "including", "incl", "current", "non", "year", "period",
                 "financial", "statement", "standalone", "consolidated"}


def _merge_tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", norm_space(text).lower())
            if len(word) >= 3 and word not in NEW_NAME_STOP}


def new_measure_index(con: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Every declared ``NEW:<id>`` in the DB with its definitions, driver nodes, units, pages and counts."""
    index: dict[str, dict[str, Any]] = {}
    for measure, definition, node, doc_key, page, known_at, family in con.execute(
            "SELECT measure, new_definition, new_driver_node, doc_key, page, known_at, unit_family "
            "FROM observation WHERE measure LIKE ? ORDER BY observation_id", (NEW_PREFIX + "%",)):
        new_id = str(measure)[len(NEW_PREFIX):]
        item = index.setdefault(new_id, {"definitions": [], "nodes": {}, "units": {}, "pages": set(),
                                         "observations": 0, "first_known_at": str(known_at or ""),
                                         "examples": []})
        item["observations"] += 1
        key = (str(doc_key), int(page))
        if key not in item["pages"]:
            item["pages"].add(key)
            if len(item["examples"]) < 3:
                item["examples"].append(f"{Path(str(doc_key)).stem[:20]}:{int(page)}")
        definition = norm_space(definition)
        if definition and definition not in item["definitions"] and len(item["definitions"]) < 5:
            item["definitions"].append(definition)
        if node:
            item["nodes"][str(node)] = item["nodes"].get(str(node), 0) + 1
        if family:
            item["units"][str(family)] = item["units"].get(str(family), 0) + 1
    return index


def index_new_measures(con: sqlite3.Connection) -> int:
    """Write the ``measure_new`` summary: one row per declared id with its definition, counts and pages."""
    index = new_measure_index(con)
    con.execute("DELETE FROM measure_new")
    for new_id, item in index.items():
        definition = max(item["definitions"], key=len) if item["definitions"] else ""
        node = max(item["nodes"], key=lambda k: item["nodes"][k]) if item["nodes"] else ""
        con.execute("INSERT OR REPLACE INTO measure_new VALUES (?,?,?,?,?,?,?)",
                    (new_id, definition, node, item["observations"], len(item["pages"]),
                     ", ".join(item["examples"]), item["first_known_at"]))
    con.commit()
    return len(index)


def new_measure_clusters(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Model-free proposals that several ``NEW:<id>``s name one quantity (T-238 stage M, review only).

    Two ids merge when their normalised names are equal, when their definition tokens overlap by 0.6 (Jaccard), or
    when they share a name token AND their definitions overlap by 0.4 AND they print the same unit family.  Nothing is
    applied: the run writes the proposals to a CSV for Wolf.
    """
    index = new_measure_index(con)
    ids = sorted(index)
    parent = {new_id: new_id for new_id in ids}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    names = {new_id: _merge_tokens(new_id.replace(".", " ")) for new_id in ids}
    definitions = {new_id: _merge_tokens(" ".join(index[new_id]["definitions"])) for new_id in ids}
    families = {new_id: (max(index[new_id]["units"], key=lambda k: index[new_id]["units"][k])
                         if index[new_id]["units"] else "") for new_id in ids}
    postings: dict[str, list[str]] = {}
    for new_id in ids:
        for token in names[new_id] | definitions[new_id]:
            bucket = postings.setdefault(token, [])
            if len(bucket) < 40:              # ponytail: cap postings; a token shared by 40+ ids is generic
                bucket.append(new_id)
    reasons: dict[frozenset[str], str] = {}

    def ratio(left: set[str], right: set[str]) -> float:
        return len(left & right) / len(left | right) if left | right else 0.0

    for bucket in postings.values():
        for i, left in enumerate(bucket):
            for right in bucket[i + 1:]:
                if left == right:
                    continue
                pair = frozenset((left, right))
                if pair in reasons:
                    continue
                def_jaccard = ratio(definitions[left], definitions[right])
                name_overlap = names[left] & names[right]
                if names[left] == names[right] and names[left]:
                    reasons[pair] = "same_name"
                elif def_jaccard >= 0.6:
                    reasons[pair] = "definition_overlap"
                elif name_overlap and def_jaccard >= 0.4 and families[left] == families[right]:
                    reasons[pair] = "name_and_definition"
                else:
                    continue
                union(left, right)
    groups: dict[str, list[str]] = {}
    for new_id in ids:
        groups.setdefault(find(new_id), []).append(new_id)
    clusters: list[dict[str, Any]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda m: (-index[m]["observations"], m))
        cluster_reasons = sorted({reason for pair, reason in reasons.items() if set(members) >= pair})
        clusters.append({
            "proposed": members[0], "ids": members,
            "unit_family": families[members[0]],
            "observations": sum(index[m]["observations"] for m in members),
            "pages": sum(len(index[m]["pages"]) for m in members),
            "reasons": cluster_reasons,
            "definitions": " | ".join(next((d for d in index[m]["definitions"] if d), m) for m in members)[:800],
        })
    clusters.sort(key=lambda cluster: (-cluster["observations"], cluster["proposed"]))
    return clusters


def write_new_merges(con: sqlite3.Connection, path: str | Path) -> dict[str, int | str]:
    """Write the proposed NEW-id merges to a review CSV; nothing is applied to any row."""
    clusters = new_measure_clusters(con)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["cluster", "proposed_merge_into", "new_ids", "unit_family", "observations", "pages",
                         "reasons", "definitions"])
        for number, cluster in enumerate(clusters, start=1):
            writer.writerow([number, cluster["proposed"], "|".join(cluster["ids"]), cluster["unit_family"],
                             cluster["observations"], cluster["pages"], "+".join(cluster["reasons"]),
                             cluster["definitions"]])
    return {"clusters": len(clusters), "ids": sum(len(cluster["ids"]) for cluster in clusters), "csv": str(path)}


# --------------------------------------------------------------------------- store reading

PROMPT = """Read one printed page of an investor presentation or annual report (image + its text layer) and return
every printed quantity with its meaning. Output ONE JSON object per line (JSON Lines): no array, no markdown, no
prose. Every object has exactly these keys:
{{"series_id": "s1", "series_title": "chart or panel title as printed",
 "measure": "one id from the dictionary below", "printed_label": "words printed against the value, verbatim",
 "printed_axis": "axis / column header / unit line the value sits under, verbatim",
 "value_text": "the number exactly as printed", "unit": "unit as printed", "scale": 1,
 "period": "the year/period the value is for, as printed", "period_kind": "actual|instant|estimate|target",
 "segment": "", "product": "", "geography": "", "plant": "", "customer": "",
 "group_path": "heading(s) that group the value, joined with ' > '", "group_source": "printed|legend_inferred",
 "stage": "",
 "entity_scope": "company|subsidiary|industry|country|customer|peer", "is_total": false,
 "new_definition": "", "new_driver_node": ""}}

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
  period_kind: "actual" for a printed past or current period, "instant" for a point-in-time closing balance
  ("as at 31 March 2025"), "estimate" for an E suffix / forecast / projected,
  "target" for a management target or guidance; empty if no period.
- measure: EXACTLY the printed quantity. Pick a dictionary id only when the meaning is the same: a segment slice of
  revenue is revenue.mix, not revenue.value (the total); a printed "Total Liabilities" that includes equity is
  total_equity_and_liabilities, not total_assets; a pre-exceptional "Profit Before Tax" row is
  profit_before_exceptional_items_and_tax, not profit_before_tax; a cash-flow "change in trade payables" is not the
  trade_payables stock; a combined "Loans & Investments" line is neither loans nor investments; an industry's export
  growth in % is not a sold volume; "cash profit" is cash_profit, not cash_generated_from_operations; a JV's PBT is not
  the company's profit_before_tax; "PAT - Controlling Interest" is not pat. Never force-fit a broader, narrower or
  different-entity id. When no dictionary id means exactly this quantity, write "NEW:<snake_case_id>" with
  "new_definition" (one line: what the printed quantity is, with its entity and scope) and "new_driver_node"
  (revenue|cost|margin|capex|capacity|debt|equity|working_capital|none). A bare non-dictionary id is rejected.
  Never guess a different number to fit a measure.
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
- Never estimate a value that is not printed. A bar, line point or slice with no printed number has NO value: leave it
  out (never read it off the gridlines). Axis ticks (0, 1,000 ... 9,000), legend years and a scale line's numbers are
  not data. A chart labelled "E"/"F"/"Guidance"/"Target"/"Est.", or drawn shaded/hatched, is a forecast or a guidance
  case: keep its printed number only, with period_kind "estimate" (E/F/forecast) or "target" (guidance), never "actual".
- A map: one series_id per map panel, with that panel's printed title as series_title (three maps = s1, s2, s3), even
  when the slide gives one overall title. A value on a map gets geography only when the place name is printed next to
  that value in that panel; a pin with no printed place name has empty geography and an empty label. Never move a
  value to a neighbouring state, and never guess a call-out's place from its position on the slide.
- A stacked bar: each segment's printed label is that part's printed_label (and its segment when it names a business
  segment); a segment is never the total. is_total is true only for a bar/row/slice printed with "Total" or the
  printed total's own label.
- A waterfall / bridge: the first and last bars are levels of the walked measure; only the middle bars are steps.
- A count or a rank is not a percentage: "top 10 customers", "10 countries", "3 plants" are counts; a share row's
  value must be printed with a % sign.
- Chart text may sit inside the image: copy what you can read and leave the rest out; never fill a gap by estimation.

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

PROMPT_TRANSCRIPT = """Read one page of an Indian company's earnings-call transcript (its text layer only, no image)
and return every printed number, every management statement and every guidance target. Output ONE JSON object per
line (JSON Lines): no array, no markdown, no prose. Every object names its "type" and holds these keys:

Number: {{"type": "number", "measure": "one id from the dictionary below", "printed_label": "the words printed
immediately before the number, verbatim", "value_text": "the number exactly as printed", "unit": "unit as printed",
"period": "the period printed against it", "period_kind": "actual|estimate|target",
"basis": "standalone|consolidated|", "entity_scope": "company|subsidiary|industry|country|customer|peer",
"segment": "", "product": "", "geography": "", "new_definition": "", "new_driver_node": ""}}
Statement: {{"type": "statement", "measure": "one id from the dictionary below", "text": "one management speaker's
whole passage on one topic, verbatim from its first word to its last full stop", "speaker": "the speaker name
printed for it", "question_context": "when the passage only makes sense with the question, that question's topic
in one line; else empty", "direction": "up|down|flat|", "new_definition": "", "new_driver_node": ""}}
Guidance: {{"type": "guidance", "measure": "one id from the dictionary below", "period": "the future period as
printed", "low": "the lower or only printed number", "high": "the upper printed number, or empty",
"unit": "unit as printed", "direction": "up|down|flat|", "text": "the sentence that states the target, verbatim",
"new_definition": "", "new_driver_node": ""}}

Rules:
- The page text is the only source. Copy every number and every sentence exactly as printed; never compute, round,
  convert, paraphrase or complete a sentence the page does not print. Skip greetings, vote of thanks, safe-harbour
  text, operator notes, analyst small talk and page headers.
- measure: EXACTLY the printed quantity. Pick a dictionary id only when the meaning is the same (a call's "cash profit"
  is cash_profit, not cash_generated_from_operations; a segment's revenue is revenue.mix, not revenue.value; a
  pre-exceptional "profit before tax" row is profit_before_exceptional_items_and_tax; a flow "change in trade
  payables" is not the trade_payables stock; a JV's result is not the company's). Never force-fit a broader, narrower
  or different-entity id. When nothing in the dictionary means exactly this quantity, write
  "NEW:<snake_case_id>" with "new_definition" (one line: what it is) and "new_driver_node"
  (revenue|cost|margin|capex|capacity|debt|equity|working_capital|none). A bare non-dictionary id is rejected.
- statement: one management speaker's continuous passage on ONE topic, copied verbatim from its first word to its
  last full stop -- normally 2-5 sentences. Never split a passage into single sentences and never cut it at a PDF
  line break or mid-sentence: it ends only at its last full stop, even when it is long. A passage that runs onto the
  next page is stored whole on the page where it starts; when this page itself ends mid-sentence, stop the statement
  at its last complete sentence and never emit one without its final full stop. Management speakers only: never
  include the analyst's question, the operator, or another speaker's words; when the speaker changes, start a new
  statement. When the answer alone does not make sense ("Yes. 2.5%", "It's going to be about the same."), keep it
  verbatim and put the question's topic in "question_context". Never store a bare pronoun opening with neither a
  noun subject nor a measure. A reported actual is a number, not a statement.
- direction: "up" when the statement says the item rises or improves, "down" when it falls or worsens, "flat" when it
  stays unchanged; empty when it says none of the three.
- guidance: only a forward target management gives ("we expect 10-12% revenue growth in FY27"). low/high are the range
  printed in the sentence (high empty for a single number), unit and period as printed, and the sentence itself goes
  in "text". A reported actual, a hypothetical ("if gas prices fall") or an outside forecast is never guidance.
- Every guidance row, and every number row whose sentence says what will happen or why (will, should, expect,
  guidance, target, because, due to, continue, next N months/quarters), MUST also emit that same sentence as a
  statement row with the same measure and speaker.
- A number with no printed period stays a number without a period; never give it the call's quarter.

Measure dictionary (id -- name -- unit family -- driver node):
{dictionary}

Transcript page text (verbatim):
<<<
{text}
>>>"""


# T-241 (24 Nov, Eagle audit of 110 hy4 transcript rows): v1 left period free text ('the quarter', a call date) on
# ~140k of 158k number/guidance rows, kept one end of a printed range, lost the sign of declines, stored no speaker on
# any number and kept list numbers / years / postcodes as values. v2 resolves the period against the call's own
# quarter and returns the range's upper end, the sign and the speaker. Chosen with --transcript-prompt v2.
TRANSCRIPT_PROMPT = "v1"
# a sign is kept only on a movement (growth / change / bps); a level (days, margin, amount) is never negated
BY_CHANGE_RE = re.compile(r"\b(?:increas|decreas|reduc|improv|grew|grown|fell|declin|rose|risen|went\s+(?:up|down)|"
                          r"expand|contract|dropp?)\w*\s+by$", re.I)
# T-241 (Wolf's fy27_v2 ckpt_0001 grade, 24 Nov): five number guards for v2 transcript rows
PERIOD_VALUE_RE = re.compile(r"^(?:(?:Q[1-4]|H[12]|9M)\s*(?:FY\s*'?\d{2,4})?|FY\s*'?\d{2,4}(?:\s*[-\u2013]\s*'?\d{2,4})?)$",
                             re.I)
DECREASE_RE = re.compile(r"\b(?:decreas\w*|declin\w*|de-?growth|negative\s+growth|fell|fall(?:en|ing)?|dropped|"
                         r"lower\s+by|down\s+by|contract(?:ed|ion))\b", re.I)
NEGATIVE_WORD_RE = re.compile(r"\bnegative\b|\bloss\s+of\b|\bminus\b|\bnet\s+loss\b", re.I)
COVER_LETTER_RES = (re.compile(r"\b(?:scrip|security)\s+code\b", re.I),
                    re.compile(r"\bsub(?:ject)?\s*[:\-]", re.I),
                    re.compile(r"\bdear\s+(?:sir|sirs|madam)\b", re.I))
CURRENCY_RE = re.compile(r"INR|Rs\.?|USD|US\$|\$|\u20b9|rupees", re.I)
RANGE_TAIL_RE = re.compile(r"\s*(?:to|-|\u2013|\u2014)\s*(?:INR|Rs\.?|USD|US\$|\$|\u20b9)?\s*(\d[\d,]*(?:\.\d+)?)", re.I)


INNER_RANGE_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*%?\s*(?:-|\u2013|\u2014|to)\s*(?:INR|Rs\.?|USD|US\$|\$|\u20b9)?\s*"
                            r"(\d[\d,]*(?:\.\d+)?)", re.I)
FRACTION_RE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})\s*(?:rd|th|ds)?\s*$", re.I)
BARE_LABEL = frozenset({"to", "rs", "rs.", "inr", "-", "upto", "up to"})
RANGE_START_RE = re.compile(r"\d[\d,.]*\s*%?\s*(?:crores?|cr|lakhs?|bn|billion|mn|million)?\s*"
                            r"(?:to|-|\u2013|\u2014)\s*(?:INR|Rs\.?|USD|US\$|\$|\u20b9)?\s*$", re.I)
COST_OF_FUNDS_RE = re.compile(r"\bcost\s+of\s+(?:funds|borrowings?|deposits)\b|\bborrowing\s+(?:at|cost)\b|"
                              r"\bborrow(?:ed|s)?\s+at\b", re.I)


WORD_FRACTION_RE = re.compile(r"\band\s+(?:a\s+)?(half|quarter|three[\s-]quarters?)\b", re.I)
WORD_FRACTION = {"half": 0.5, "quarter": 0.25}
UNIT_IN_TEXT_RE = re.compile(r"%|percent|per\s*cent|bps|basis\s+points?|\btimes\b|\d\s*x\b", re.I)


def word_fraction(value_text: str) -> float:
    """'14 and a half percent' -> 0.5 (added to the 14 the number parser reads); 0 when none is printed."""
    m = WORD_FRACTION_RE.search(value_text or "")
    if not m:
        return 0.0
    word = m.group(1).lower()
    return 0.75 if word.startswith("three") else WORD_FRACTION[word]


def inner_range(value_text: str) -> tuple[float, float] | None:
    """'40%-45%', '40-45%', 'INR310 to INR320' printed inside one value_text -> (low, high), else None."""
    m = INNER_RANGE_RE.search(value_text or "")
    if not m:
        return None
    low, high = parse_number(m.group(1)), parse_number(m.group(2))
    if low is None or high is None or not (low < high <= max(abs(low), 1) * 20):
        return None
    return low, high


def is_cover_letter(page_text: str, page: int) -> bool:
    """A filing cover letter (Scrip Code + Sub: + Dear Sir on page 1-2) carries no investor figure."""
    text = str(page_text or "")
    return int(page) <= 2 and all(rx.search(text) for rx in COVER_LETTER_RES)


def printed_range_high(page_text: str, value_text: str, value: float | None) -> float | None:
    """The upper end printed right after ``value_text`` ("$23 billion to $25 billion", "60% to 65%"), else None."""
    if value is None or not value_text:
        return None
    text = norm_space(page_text)
    idx = text.find(value_text)
    if idx < 0:
        return None
    tail = text[idx + len(value_text): idx + len(value_text) + 40]
    m = RANGE_TAIL_RE.match(tail)
    if not m:
        return None
    # the two ends share a unit: "rose by 11% to INR34.5 crores" is a growth and a new level, never a range
    low_pct, high_pct = value_text.rstrip().endswith("%"), tail[m.end():].lstrip().startswith("%")
    if low_pct != high_pct and not (not low_pct and high_pct and re.fullmatch(r"[\d.,\s]+", value_text)):
        return None
    if CURRENCY_RE.search(tail[:m.start(1)]) and not CURRENCY_RE.search(value_text):
        return None
    high = parse_number(m.group(1))
    if high is None or high <= value or high > abs(value) * 20:
        return None
    return high


def page_text_after(page_text: str, value_text: str, width: int) -> str:
    """The ``width`` characters printed right after ``value_text`` on the page ('' when it is not found)."""
    text = norm_space(page_text)
    idx = text.find(value_text) if value_text else -1
    return text[idx + len(value_text): idx + len(value_text) + width] if idx >= 0 else ""


def _clause_before(page_text: str, value_text: str, width: int) -> str:
    """``_before`` cut at the last '.', ';' or ',' so another clause's word ("costs declined; revenue grew 12%") is out."""
    return re.split(r"[.;,]", _before(page_text, value_text, width))[-1]


def _before(page_text: str, value_text: str, width: int) -> str:
    """The ``width`` characters printed before ``value_text`` on the page ('' when it is not found)."""
    text = norm_space(page_text)
    idx = text.find(value_text) if value_text else -1
    return text[max(0, idx - width):idx] if idx > 0 else ""


def negative_printed(label: str, page_text: str, value_text: str) -> bool:
    """'stood at negative Rs27 crore', 'a loss of 12 crore': the sign is printed in words, not with a minus."""
    if NEGATIVE_WORD_RE.search(label or ""):
        return True
    text = norm_space(page_text)
    idx = text.find(value_text) if value_text else -1
    return idx > 0 and bool(NEGATIVE_WORD_RE.search(text[max(0, idx - 25):idx]))


# T-241 v2c (Wolf's grade, 7 of 7 wrongs): a number that is not the company's own actual or target
NOT_A_COMPANY_FIGURE = frozenset({"hypothetical", "expectation", "ask"})
SIGNED_MEASURE = re.compile(r"growth|change|_yoy|_qoq|delta|\bbps\b|basis points", re.I)

PROMPT_TRANSCRIPT_V2 = """Read one page of an Indian company's earnings-call transcript (its text layer only, no image)
and return every number management states, every management statement and every guidance target. Output ONE JSON
object per line (JSON Lines): no array, no markdown, no prose. Every object names its "type" and holds these keys:

Number: {{"type": "number", "measure": "one id from the dictionary below", "printed_label": "the words printed
immediately before the number, verbatim", "value_text": "the number exactly as printed (the lower end of a range)",
"high_text": "the upper end of a printed range exactly as printed, else empty", "sign": "- when the sentence says
the quantity fell / declined / dropped / degrew / was negative / was a loss, else empty", "unit": "unit as printed,
WITH its scale word (crore, lakh, million, billion, bps) and its noun (tonnes, MW, stores)", "period": "fiscal label
(rules below)", "period_printed": "the period words exactly as printed, empty when none",
"period_kind": "actual|estimate|target", "basis": "standalone|consolidated|",
"entity_scope": "company|subsidiary|industry|country|customer|peer", "segment": "", "product": "", "geography": "",
"customer": "", "speaker": "the name of the person who said the sentence holding this number (an analyst's name
when an analyst said it and management confirmed it)",
"claim_type": "company_actual|company_target|third_party|hypothetical|expectation|ask", "new_definition": "",
"new_driver_node": ""}}
Statement: {{"type": "statement", "measure": "one id from the dictionary below", "text": "one management speaker's
whole passage on one topic, verbatim from its first word to its last full stop", "speaker": "the speaker name
printed for it", "question_context": "when the passage only makes sense with the question, that question's topic
in one line; else empty", "direction": "up|down|flat|", "new_definition": "", "new_driver_node": ""}}
Guidance: {{"type": "guidance", "measure": "one id from the dictionary below", "period": "fiscal label (rules below)",
"low": "the lower or only printed number", "high": "the upper printed number, or empty", "unit": "unit as printed
with its scale word", "direction": "up|down|flat|", "speaker": "the speaker name",
"claim_type": "company_target|third_party|ask", "text": "the sentence that states
the target, verbatim", "new_definition": "", "new_driver_node": ""}}

This call: filed {known_at}; it discusses {call_quarter} (Indian fiscal year April-March: Q1 = Apr-Jun, Q2 = Jul-Sep,
Q3 = Oct-Dec, Q4 = Jan-Mar; FY26 ends 31 March 2026).

Rules:
- The page text is the only source. Copy every number and every sentence exactly as printed; never compute, round,
  convert, paraphrase or complete a sentence the page does not print. Skip greetings, vote of thanks, safe-harbour
  text, operator notes, analyst small talk and page headers.
- Speakers: a page may open mid-answer; the speaker is then the last "Name:" label before the text, or the
  management speaker whose answer this page continues. Emit numbers and guidance ONLY when management states them.
  An analyst's figure, an analyst's arithmetic ("so that comes to 1,100 crores?") or a number management merely
  repeats back from the question is never a number row; emit it only when management states it as its own figure.
- claim_type says whose figure it is. company_actual: the company's (or its subsidiary's) own reported figure;
  company_target: the company's own plan, guidance or expectation for itself; third_party: a figure about the
  government, a ministry, NHAI, a regulator, the industry, the economy, a competitor or a customer's own plans
  ("NHAI targets 40,000 crores of awards", "the government plans 17,000 km of expressways");
  hypothetical: "even if you assume 80%", "let's say", "suppose", "if prices fall to"; expectation: what the market,
  analysts or "everyone" expected ("INR 20 was what everyone was expecting"); ask: what the company or its industry
  asks the government or a regulator for ("450 crore should be allotted to the sugar sector"). Guidance is only
  company_target. A duration ("11-12 months"), a share of the order book or a split of a pipeline is never capex,
  revenue or revenue.mix: name the quantity it is (NEW:<id> when the dictionary has none).
- unit: a printed "%" is the unit "%" (growth, margin, share, ratio rows); never drop it. "crore litres", "lakh
  tonnes", "million units" keep their noun: a quantity is never rupees.
- from / to / by: "decreased by 8 days to 69 days" is TWO rows: the level 69 (inventory_days, this period) and the
  change 8 (a *_change measure, NEW:<id> if needed, sign "-"); never store the change under the level's measure.
  "climbed from around 12% to 20.4%": 20.4% is this period's level, 12% is the EARLIER period's level (its period is
  that earlier period: last year's same quarter, the earlier date printed), or skip it when that period is unclear.
- measure kind: a growth or change % is a *_growth_yoy / *_growth_qoq / *_change measure, never a level or a mix;
  a company-wide amount is its level measure (revenue_from_operations, ebitda, pat), never revenue.mix; revenue.mix
  and mix.share only for ONE named segment, product, geography or customer (fill that field), never for the whole
  company, never for an order-book or pipeline split.
- Business metrics only. Never a value: counts of agendas, fronts, points, things, questions, steps or initiatives;
  technical specifications of a product, a standard or a project (speeds "160 km/h", voltages "2x25kV",
  dimensions, model numbers); vague durations ("more than 6 months", "for some time") unless the company states it
  as its own lead time, payback, execution or breakeven period.
- A forward target management gives is a guidance row, not a number row (then also its statement row).
- basis: the LATEST "standalone" / "consolidated" words before the number on this page ("Coming to the consolidated
  results" switches every number after it); empty when the page names neither.
- Never a value: page numbers, years or dates ("2024", "FY25" -> 25, "Q2" -> 2), list markers ("number one",
  "first", "2 things"), postcodes, phone numbers, times, ratings ("4-star"), counts of questions or speakers,
  the age of an anecdote ("2 months back"), or a hypothetical ("let's say 100", "suppose", "for example", "if").
- period: a fiscal label, one of "Q1 FY25", "H1 FY25", "9M FY25", "FY25", or "FY26-FY28" for a span. Resolve
  relative words against this call: "this quarter", "the quarter", "during the quarter" -> {call_quarter};
  "last quarter" / "sequentially" -> the quarter before; "same quarter last year" -> that quarter a year earlier;
  "this year", "current year", "full year" -> the fiscal year of {call_quarter}; "next year" -> the fiscal year after;
  "H2" / "second half" -> that half of the current fiscal year; "first half" / "H1" -> H1 of it. A stock (order book,
  cash, debt, headcount, stores, capacity) stated "as on date" or "currently" -> {call_quarter}.
  A comparison figure carries ITS OWN period: in "INR 749 crores in H1 FY '25 as against INR 857 crores in H1 FY '24"
  the 857 row is "H1 FY24", and "as against INR 64 crores in Q1" is the earlier quarter, never the call's quarter.
  A year printed in calendar form ("by 2030", "December 2025") keeps that wording. Put the printed words in
  "period_printed". When no period is printed or implied, leave "period" empty.
- range: "12% to 15%", "600-700 crores", "50%-60%" -> value_text "12%" and high_text "15%". "Minimum 60%" or
  "500+ crores" is a single number with "minimum" / "+" kept in the printed_label.
- A date or a deadline ("by 30th November", "from 1st April") is never a number row; it stays in the statement.
- sign: only on a growth, change or movement row (never on a level such as days, a margin or an amount); stated as falling ("declined 19.2%", "degrowth of 5%", "down 120 bps")
  sets "sign": "-"; value_text stays exactly as printed.
- measure: EXACTLY the printed quantity. Pick a dictionary id only when the meaning is the same (a call's "cash profit"
  is cash_profit, not cash_generated_from_operations; a segment's or one customer's revenue or growth is revenue.mix
  with that segment / customer named, never the company's revenue; an order-book split is not a revenue mix; a JV's
  result is not the company's). Never force-fit a broader, narrower or different-entity id. When nothing in the
  dictionary means exactly this quantity, write "NEW:<snake_case_id>" with "new_definition" (one line: what it is)
  and "new_driver_node" (revenue|cost|margin|capex|capacity|debt|equity|working_capital|none).
- statement: one management speaker's continuous passage on ONE topic, copied verbatim from its first word to its
  last full stop -- normally 2-5 sentences. Never split a passage into single sentences and never cut it at a PDF
  line break or mid-sentence. A passage that runs onto the next page is stored whole on the page where it starts;
  when this page itself ends mid-sentence, stop at its last complete sentence. Management speakers only; when the
  speaker changes, start a new statement. When the answer alone does not make sense ("Yes. 2.5%"), keep it verbatim
  and put the question's topic in "question_context". Keep the sentence that holds a number together with the
  sentence that qualifies it. A reported actual is a number, not a statement.
- direction: "up" when the statement says the item rises or improves, "down" when it falls or worsens, "flat" when it
  stays unchanged; empty when it says none of the three.
- guidance: only a forward target management gives ("we expect 10-12% revenue growth in FY27"). A reported actual, a
  hypothetical, an analyst's estimate or an outside forecast is never guidance.
- Every guidance row, and every number row whose sentence says what will happen or why (will, should, expect,
  guidance, target, because, due to, continue, next N months/quarters), MUST also emit that same sentence as a
  statement row with the same measure and speaker.

Measure dictionary (id -- name -- unit family -- driver node):
{dictionary}

Transcript page text (verbatim):
<<<
{text}
>>>"""


def call_quarter(known_at: str) -> str:
    """The fiscal quarter a call discusses: the last quarter that ended before its filing month ("Q1 FY25")."""
    m = re.match(r"(\d{4})-(\d{2})", known_at or "")
    if not m:
        return "the quarter just reported"
    year, month = int(m.group(1)), int(m.group(2))
    if month <= 3:
        q, fy = 3, year            # filed Jan-Mar: Oct-Dec just ended -> Q3 FY(year)
    elif month <= 6:
        q, fy = 4, year            # filed Apr-Jun: Jan-Mar -> Q4 FY(year)
    elif month <= 9:
        q, fy = 1, year + 1        # filed Jul-Sep: Apr-Jun -> Q1 FY(year+1)
    else:
        q, fy = 2, year + 1        # filed Oct-Dec: Jul-Sep -> Q2 FY(year+1)
    return f"Q{q} FY{fy % 100:02d}"


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


# --------------------------------------------------------------------------- stage H image-only text (OCR)

OCR_READER = os.environ.get("T230_OCR_READER", "")   # T-238: the Kilo Dots default is gone (404); the env hook stays
OCR_PROMPT = (
    "Transcribe ONLY the numbers printed as data labels on this page image. One line per number: the number exactly "
    "as printed, then the words printed next to it. Never estimate a value from a bar's height or from the gridlines, "
    "never compute, sum or convert, and never transcribe axis ticks, chart years or page numbers. If the page prints "
    "no data label, output nothing."
)
_OCR_LOCK = threading.Lock()
_OCR_CACHE: dict[tuple[str, str, int], str] = {}


def ocr_page_text(store_db: str | Path, doc_key: str, page: int, image_b64: str | None) -> str:
    """The page image's printed data labels, read from the stored OCR words; '' when no OCR words exist.

    Stage H: a chart whose numbers sit inside the image has an empty text layer at exactly those values (CONFIPET
    p34: 37 correct rows were quarantined).  This gives the check a second printed source; the value's status then
    verifies with ``text_source='ocr'``.  The store's own OCR database (``<store>_ocr.db``, the RapidOCR/TextRecognizer
    pass) is used first: it is already on disk and costs no call.  T-238: Kilo Dots is gone (404), so no OCR model is
    called by default; ``T230_OCR_READER`` names another reader and a failed or quota-blocked call returns '' (the
    row stays unverified ``image_text``, never quarantined).
    """
    key = (str(store_db), str(doc_key), int(page))
    with _OCR_LOCK:
        if key in _OCR_CACHE:
            return _OCR_CACHE[key]
    text = ""
    stored = Path(str(store_db)).with_name(Path(str(store_db)).stem + "_ocr.db")
    if stored.is_file():
        try:
            text = norm_space(" ".join(w[4] for w in page_words.ocr_words([stored], doc_key, int(page))))
        except Exception:
            text = ""
    if not text and image_b64 and OCR_READER and quota_seconds() <= 0:
        try:
            result = rp._model_call(OCR_READER, OCR_PROMPT, image_b64)
        except Exception as exc:
            result = {"output": "", "error": f"{type(exc).__name__}: {exc}"}
        if result.get("error"):
            print(f"OCR unavailable for {doc_key} p{page}: {str(result['error'])[:160]}", file=sys.stderr)
        else:
            text = str(result.get("output") or "")
    if text:
        with _OCR_LOCK:
            _OCR_CACHE[key] = text
    return text



# --------------------------------------------------------------------------- reader call and 429 handling

RETRYABLE = re.compile(r"\b(?:429|500|502|503|504)\b")
MAX_RETRIES = 6
QUOTA_STOP_SECONDS = 300.0              # a Retry-After this long is the shared Go quota window, not a burst
_RETRY_EVENTS: list[dict[str, Any]] = []
_RETRY_LOCK = threading.Lock()
_QUOTA: dict[str, float] = {"seconds": 0.0}
_QUOTA_LOCK = threading.Lock()


def reparse_db(con: sqlite3.Connection, store_dbs: Iterable[str | Path], only: Any = None) -> dict[str, Any]:
    """T-241: rebuild transcript rows from the stored raw replies (``page_reply``) with today's parsing and guards.

    No model call.  Every selected page's rows are deleted and rebuilt from its reply; the ``page_read`` outcome is
    updated.  A reply written by the v2 transcript prompt (its fingerprint in ``page_reply.fingerprint``) gets the
    v2 guards.  Only transcript pages are re-parsed (a deck page also needs its words / OCR text); others are counted.
    """
    import hashlib
    v2_fp = hashlib.sha256(f"{OBS_READER}\n{PROMPT_TRANSCRIPT_V2}".encode("utf-8")).hexdigest()[:12]
    store_dbs = list(store_dbs)
    companies = company_index(store_dbs)
    doc_store: dict[str, str] = {}
    for store_db in store_dbs:
        try:
            store_con = connect_ro(store_db, timeout_s=60)
            try:
                for (key,) in store_con.execute("SELECT doc_key FROM doc"):
                    doc_store.setdefault(str(key), str(store_db))
            finally:
                store_con.close()
        except sqlite3.Error:
            continue
    stats: dict[str, Any] = {"pages": 0, "no_store": 0, "not_transcript": 0, "unselected": 0,
                             "rows_before": 0, "rows_after": 0, "v2_pages": 0}
    replies = con.execute("SELECT doc_key, page, fingerprint, raw FROM page_reply ORDER BY doc_key, page").fetchall()
    for doc_key, page, fingerprint, raw in replies:
        store_db = doc_store.get(str(doc_key))
        if store_db is None:
            stats["no_store"] += 1
            continue
        if only is not None and not only.page(store_db, doc_key, page):
            stats["unselected"] += 1
            continue
        meta = page_meta(store_db, doc_key)
        if not meta or meta["doc_type"] != "transcript":
            stats["not_transcript"] += 1
            continue
        owner = ""
        try:
            owner = doc_owner(store_db, doc_key, companies, meta["symbol"])
        except Exception:
            owner = ""
        text = page_text_of(store_db, doc_key, page)
        reply_rows, _bad = parse_reply(str(raw or ""))
        v2 = f"transcript:{v2_fp}" in str(fingerprint or "")
        rows = build_observations(symbol=meta["symbol"], doc_key=doc_key, page=int(page), known_at=meta["known_at"],
                                  page_text=text, reply_rows=reply_rows, doc_owner_symbol=owner,
                                  companies=companies, transcript_v2=v2)
        stats["rows_before"] += int(con.execute("SELECT COUNT(*) FROM observation WHERE doc_key=? AND page=?",
                                                (doc_key, int(page))).fetchone()[0])
        con.execute("DELETE FROM observation WHERE doc_key=? AND page=?", (doc_key, int(page)))
        write_rows(con, rows)
        con.execute("INSERT OR REPLACE INTO page_read VALUES (?,?,?,?,?)",
                    (doc_key, int(page), "rows" if rows else "empty", len(rows), ist_now()))
        con.commit()
        stats["pages"] += 1
        stats["v2_pages"] += int(v2)
        stats["rows_after"] += len(rows)
    return stats


def apply_prompt_choice(transcript_prompt: str) -> None:
    """Set the transcript prompt (and the reader set_reader chose) here AND on the imported module.

    Run as ``python -m`` this file is ``__main__``; read_gate imports ``reality_engine.v2.observations``, a second
    module object, so a choice made only here left the gate fingerprinting v1 while v2 read (24 Nov bug).
    """
    import importlib
    globals()["TRANSCRIPT_PROMPT"] = transcript_prompt     # T-241: v1 unless the A/B picks v2
    imported = importlib.import_module("reality_engine.v2.observations")
    if imported.__dict__ is not globals():
        imported.TRANSCRIPT_PROMPT = transcript_prompt
        imported.OBS_READER = OBS_READER
        imported.READER = READER


def template_for(doc_type: str) -> str:
    """The prompt template a page of ``doc_type`` is read with; read_gate fingerprints exactly this (T-241)."""
    if "transcript" in str(doc_type):
        return PROMPT_TRANSCRIPT_V2 if TRANSCRIPT_PROMPT == "v2" else PROMPT_TRANSCRIPT
    return PROMPT


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
            json=body, timeout=float(cfg.get("timeout", 300)))
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
    """One reader proposal per distinct unmapped label, stored with its reason; never applied to a row."""
    if limit <= 0:
        return {"labels": 0, "proposed": 0, "quota": False}
    measures = measure_index()
    counts: dict[str, int] = {}
    samples: dict[str, tuple[str, str, str, int]] = {}
    for label, measure, unit, value, doc_key, page in con.execute(
            "SELECT printed_label, measure, unit, value_text, doc_key, page FROM observation"):
        label = str(label or "")
        if not label or measure in measures or script_measure(label) or str(measure or "").startswith(NEW_PREFIX):
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
                        (label, measure, reason[:500], READER, ist_now()))
            written += 1
    con.commit()
    return {"labels": len(todo), "proposed": written, "quota": quota_hit}


def process_page(store_db: str | Path, doc_key: str, page: int,
                 companies: dict[str, tuple[str, str]] | None = None,
                 text_only: bool = False) -> dict[str, Any]:
    """One page: image + text layer -> model reply -> checked observation rows.

    ``text_only`` (T-234) sends the stored text layer without the page image, for a text-only reader.
    """
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
    transcript = meta["doc_type"] == "transcript"
    pw = None
    try:
        pw = page_words.words_for(store_db, doc_key, page)
    except Exception:
        pw = None
    # T-238: the page's own OCR words are the reading input when the text layer is unusable (the route sends such
    # a page here only when its <stem>_ocr.db holds words).  The prompt gets their layout as the text layer and
    # every printed check (label/axis/period/basis) runs on those words; the rows carry text_source='ocr'.
    ocr_read = bool(pw and pw.words and pw.source.startswith("ocr"))
    words = pw.words if pw else []
    layout = page_layout.layout_text(words) if words else norm_space(text)
    check_text = layout if ocr_read else text
    image_b64 = None
    if text_only or transcript:              # T-238: a transcript page is text; no image is read for it
        image_note = ""
    else:
        try:
            data, _scale = page_reader._page_image(store_db, doc_key, page)
            image_b64 = base64.b64encode(data).decode("ascii")
        except Exception as exc:
            image_note = f"no page image: {type(exc).__name__}: {exc}"[:200]
        else:
            image_note = ""
    result: dict[str, Any] = {"store": str(store_db), "doc_key": doc_key, "page": page, "symbol": meta["symbol"],
                              "owner": owner, "raw": "", "error": "", "rows": [], "bad_lines": 0,
                              "parsed": 0, "seconds": 0.0, "in_tok": 0, "out_tok": 0, "image_note": image_note,
                              "doc_type": meta["doc_type"]}
    if not image_b64 and not layout.strip():
        result["skip"] = "no image and no text"
        return result
    template = template_for(meta["doc_type"])
    prompt = template.format(dictionary=dictionary_text(measure_index()), text=layout[:TEXT_LAYER_CHARS],
                             known_at=meta["known_at"][:10], call_quarter=call_quarter(meta["known_at"]))
    call = call_reader(prompt, image_b64, doc_key, page)
    if call.get("quota"):
        result["quota"] = call["quota"]
        return result
    result["seconds"] = float(call.get("seconds") or 0.0)
    result["in_tok"] = int(call.get("in_tok") or 0)
    result["out_tok"] = int(call.get("out_tok") or 0)
    result["raw"] = str(call.get("output") or "")
    if call.get("error"):
        result["error"] = str(call.get("error") or "")
        return result
    reply_rows, bad = parse_reply(result["raw"])
    result["bad_lines"] = bad
    result["parsed"] = len(reply_rows)
    text_flat = norm_space(check_text)
    image_values = [norm_space(r.get("value_text")) for r in reply_rows if isinstance(r, dict)]
    result["ocr_text"] = ""
    result["ocr_read"] = ocr_read
    if not ocr_read and not transcript and any(v and re.search(r"\d", v) and not text_has(text_flat, v)
                                               for v in image_values):
        result["ocr_text"] = ocr_page_text(store_db, doc_key, page, image_b64)
    result["rows"] = build_observations(symbol=meta["symbol"], doc_key=doc_key, page=page,
                                        known_at=meta["known_at"], page_text=check_text, words=words,
                                        reply_rows=reply_rows, doc_owner_symbol=owner,
                                        companies=companies,
                                        deck_asof="" if transcript else deck_period(store_db, doc_key, check_text),
                                        deck_basis="" if transcript else deck_basis(str(store_db), str(doc_key)),
                                        ocr_text=result["ocr_text"], ocr_page=ocr_read,
                                        transcript_v2=transcript and TRANSCRIPT_PROMPT == "v2",
                                        deck_guards=meta.get("doc_type") == "deck")
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


@lru_cache(maxsize=512)
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
        if p.get("doc_type") == "transcript":
            kept.append(p)               # T-238: a call transcript page is speech, never a statement table
            continue
        reason = statement_page_reason(texts.get((str(p["doc_key"]), int(p["page"])), ""))
        if not reason:
            kept.append(p)
        elif dropped is not None:
            dropped[reason] = dropped.get(reason, 0) + 1
    return kept


def transcript_pages(store_db: str | Path) -> list[dict[str, Any]]:
    """T-238 stage M: every routed or unrouted page of the store's call transcripts that prints text."""
    try:
        con = connect_ro(store_db, timeout_s=60)
    except Exception:
        return []
    rows: list[Any] = []
    try:
        _cur = con.execute(
            "SELECT p.doc_key, p.page FROM doc_page p JOIN doc d ON d.doc_key = p.doc_key "
            "WHERE LOWER(d.doc_type) = 'transcript' AND COALESCE(p.text, '') <> '' "
            "ORDER BY p.doc_key, p.page")
        fetched = _cur.fetchall() if _cur is not None else None
        rows = [row for row in (fetched or [])]
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [{"store": str(store_db), "doc_key": str(row[0]), "page": int(row[1]), "doc_type": "transcript"}
            for row in rows]


@lru_cache(maxsize=256)
def _ocr_pages(store_db: str) -> frozenset[tuple[str, int]]:
    """The (doc_key, page) pairs the store's own ``<stem>_ocr.db`` holds words for (T-238)."""
    path = page_words.sibling_ocr_db(store_db)
    if not path.is_file():
        return frozenset()
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            return frozenset((str(row[0]), int(row[1])) for row in con.execute("SELECT doc_key, page FROM ocr_page"))
        finally:
            con.close()
    except sqlite3.Error:
        return frozenset()


def pages_from_store(store_db: str | Path, doc_types: Iterable[str] = ("deck",),
                     routes: Iterable[str] = ("table_or_chart", "needs_ocr"), skip_statements: bool = False,
                     dropped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """The routed pages a reader may read, from the ``routes.csv`` beside the store.

    T-238: a ``needs_ocr`` row is readable once the store's ``<stem>_ocr.db`` holds words for it -- the reader gets
    the OCR text layer and the checks run on the OCR words (``text_source='ocr'``).  A ``needs_ocr`` row with no
    OCR words yet is still skipped.
    """
    wanted_types = {rp._doc_type_norm(t) for t in doc_types}
    wanted_routes = set(routes)
    have_ocr: frozenset[tuple[str, int]] | None = None
    pages: dict[tuple[str, int], dict[str, Any]] = {}
    if "transcript" in wanted_types:
        pages.update(((p["doc_key"], p["page"]), p) for p in transcript_pages(store_db))
    routes_csv = Path(store_db).parent / "routes.csv"
    if routes_csv.is_file():
        with routes_csv.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("route") not in wanted_routes:
                    continue
                doc_type = rp._doc_type_norm(row.get("doc_type", ""))
                if doc_type not in wanted_types or doc_type == "transcript":
                    continue
                try:
                    page = int(row["page"])
                except (KeyError, ValueError):
                    continue
                if row.get("route") == "needs_ocr":
                    if have_ocr is None:
                        have_ocr = _ocr_pages(str(store_db))
                    if (str(row["doc_key"]), page) not in have_ocr:
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
    # T-241: a page read whose rows were all dropped (cover, disclaimer) or that has nothing to read is in the
    # page_read ledger and is not read again; errors and parse failures are not recorded, so they are retried.
    done |= {(str(row[0]), int(row[1])) for row in con.execute(
        "SELECT doc_key, page FROM page_read WHERE outcome IN ('rows','empty','skip')")}
    return [p for p in pages if (str(p["doc_key"]), int(p["page"])) not in done]


def _kept_pages(pages: Iterable[tuple[str, int]]) -> Any:
    """T-238: one raw-store ``keep()`` per document, so a recheck downloads each deck PDF once, not once per page.

    The pages arrive ordered by (doc_key, page).  A deck whose PDF is Drive-only re-fetches it on every
    ``page_words.words_for`` call outside a keep block, which made the 9,439-page N2 recheck take over 100 minutes
    and get killed mid-run.  Same idiom as ``page_route._kept``; a local PDF is never downloaded.
    """
    from reality_engine import raw_store

    store = raw_store.default_store()
    current: str | None = None
    stack = contextlib.ExitStack()
    with stack:
        for doc_key, page in pages:
            if doc_key != current:
                stack.close()
                current = doc_key
                stack.enter_context(store.keep())
            yield doc_key, page


def recheck_db(con: sqlite3.Connection, store_dbs: Iterable[str | Path],
               companies: dict[str, tuple[str, str]] | None = None,
               only: Any = None) -> dict[str, Any]:
    """Stage C: re-apply every script check to an existing observation DB with no model call.

    Only checks that need a new printed source may upgrade an unverified row: an inherited unit or period, a
    measure alias/label mapping, or a stage read from a printed group.  Any other upgrade is refused and reported.
    ``only`` (a :class:`reality_engine.research.selector.Selector`) restricts the pages and rows re-checked;
    the rest of the DB is left untouched (T-233 scoped fix run).  Each document's PDF is fetched at most once
    (``_kept_pages``), so a scoped pass over thousands of pages is minutes, not hours.
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
                             "subsidiary_rows": 0, "deck_asof": 0, "deck_asof_cleared": 0,
                             "deck_asof_fixed": 0, "deck_asof_renamed": 0, "slide_title_periods": 0,
                             "slide_title_cleared": 0, "growth_periods": 0, "customers_named": 0,
                             "basis_deck": 0, "cagr_rows": 0, "map_orphans": 0, "panels_split": 0,
                             "geography_cleared": 0, "stacked_parts": 0, "rank_counts": 0, "measure_fixed": 0,
                             "text_source_ocr": 0, "per_unit_scales": 0, "period_cleared": 0, "ticks_cleared": 0,
                             "footnote_basis": 0, "scope_cues": 0, "lower_bounds": 0, "dash_labels": 0,
                             "unit_family_fixed": 0, "is_total_rows": 0, "parts_sum_restored": 0,
                             "basis_header": 0, "period_header": 0, "generic_labels": 0,
                             "parts_degenerate": 0, "comparative_periods": 0, "instant_periods": 0,
                             "basis_page": 0}
    pages = list(con.execute("SELECT DISTINCT doc_key, page FROM observation ORDER BY doc_key, page"))
    if only is not None:                      # T-233: a scoped recheck touches only the selected pages
        pages = [p for p in pages if only.page(doc_store.get(str(p[0])), str(p[0]), int(p[1]))]
    row_filter = only.where_sql() if only is not None else "1=1"
    con.row_factory = sqlite3.Row
    for doc_key, page in _kept_pages(pages):
        store_db = doc_store.get(str(doc_key))
        if not store_db:
            continue
        stats["pages"] += 1
        raw_text = page_text_of(store_db, doc_key, int(page))
        try:
            pw = page_words.words_for(store_db, doc_key, int(page))
            words = pw.words
        except Exception:
            pw, words = None, []
        ocr_page = bool(pw and words and pw.source.startswith("ocr"))
        if ocr_page:            # T-238: a recheck re-applies the checks on the OCR words the reader used
            raw_text = page_layout.layout_text(words)
        text = norm_space(raw_text)
        head = page_head(raw_text)
        deck_asof = deck_period(store_db, doc_key, raw_text)
        page_deck_basis = deck_basis(str(store_db), str(doc_key))
        owner = ""
        try:
            owner = doc_owner(store_db, doc_key, companies, store_symbol.get(store_db, ""))
        except Exception:
            owner = ""
        rows = [dict(r) for r in con.execute(f"SELECT * FROM observation WHERE doc_key=? AND page=?"
                                             f" AND ({row_filter})", (doc_key, int(page)))]
        rows = [row for row in rows if str(row.get("record_type") or "number") == "number"]
        if not rows:
            continue                     # T-238 stage M: statement/guidance records are not number-checked
        ocr_text = ""
        if not ocr_page:
            ocr_row = con.execute("SELECT text FROM page_ocr WHERE doc_key=? AND page=?",
                                  (str(doc_key), int(page))).fetchone()
            ocr_text = str(ocr_row[0] or "") if ocr_row else ""
            if not ocr_text and any(norm_space(r["value_text"]) and not text_has(text, r["value_text"])
                                    for r in rows):
                ocr_text = ocr_page_text(store_db, doc_key, int(page), None)   # stored OCR words only, no call
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
                                row["series_title"] or "", raw_text, row["value_text"] or "")
            if cagr:
                row["measure"], span = cagr
                if span:
                    row["period"] = span
                    row["period_source"] = ""
                    row["period_kind"] = "span"
                cagr_set = True
                stats["cagr_rows"] += 1
            measure = measures.get(row["measure"] or "")
            old_unit_family = str(row["unit_family"] or "")
            row["unit_family"] = infer_unit_family(row["unit"] or "") or old_unit_family
            unit_family_fix = row["unit_family"] != old_unit_family
            if unit_family_fix:
                stats["unit_family_fixed"] += 1
            family = measure["unit_family"] if measure else (row["unit_family"] or "")
            unit_inherited = period_inherited = stage_set = scale_fixed = deck_period_used = False
            instant_used = False
            if not row["unit"]:
                inferred = infer_unit([row["printed_axis"] or "", row["series_title"] or "",
                                       row["printed_label"] or ""], family)
                if inferred:
                    row["unit"], row["unit_family"], row["scale"] = inferred
                    unit_inherited = True
                    stats["unit_inherited"] += 1
            if family == "money" and float(row["scale"] or 1) == 1:
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
            per_unit_fix = family == "money_per_unit" and (
                "scale " in old_reason or "scale_unread" in old_reason)
            if apply_per_unit_scale(row, family):
                scale_fixed = True
                stats["per_unit_scales"] += 1
            if row["period_source"] == "deck_asof":
                if not deck_asof_allowed(row, raw_text) or not deck_asof:
                    row["period"] = ""
                    row["period_source"] = ""
                    row["period_kind"] = ""
                    stats["deck_asof_cleared"] += 1
                elif row["period"] != deck_asof:
                    row["period"] = deck_asof
                    row["period_kind"] = period_kind_for("", deck_asof)
                    stats["deck_asof_fixed"] += 1
            if row["period_source"] == "slide_title":        # stage N2: the title line must still print it
                title_period = slide_period(raw_text)
                if not title_period or _period_key(title_period) != _period_key(row["period"] or ""):
                    row["period"] = ""
                    row["period_source"] = ""
                    row["period_kind"] = ""
                    stats["slide_title_cleared"] += 1
            comparative = bool(row["period"]) and comparative_period(
                row["period"], raw_text, " ".join([row["printed_label"] or "", row["printed_axis"] or ""]))
            if comparative:
                row["period"] = ""           # stage L: a date inside an inline comparative bracket is not this row's
                row["period_source"] = ""
                row["period_kind"] = ""
                stats["comparative_periods"] += 1
            fake_period = bool(row["period"]) and not period_is_printed(row["period"])
            if fake_period:
                row["period"] = ""           # stage I: "Y-O-Y" / "QoQ" / "growth" is a comparison, not a period
                row["period_source"] = ""
                row["period_kind"] = ""
                stats["period_cleared"] += 1
            if not row["period"]:
                texts = [row["printed_axis"] or "", row["series_title"] or "",
                         row["group_path"] or "", row["printed_label"] or ""]
                if fake_period or comparative:
                    texts.append(head)       # the column header or page header may carry the real period
                period = infer_period([strip_comparatives(t) for t in texts])
                header_period = "" if period else column_period(words, row["region"] or "")
                if header_period:
                    period = header_period
                    row["period_source"] = "column_header"
                    stats["period_header"] += 1
                if period:
                    row["period"] = period
                    row["period_kind"] = period_kind_for("", period)
                    period_inherited = True
                    stats["period_inherited"] += 1
                elif (title_period := slide_period(raw_text)) and (
                        not is_stock_measure(row["measure"] or "") or capacity_deck_period_ok(row, raw_text)):
                    row["period"] = title_period        # stage N: the period the slide's own title names
                    row["period_kind"] = period_kind_for("", title_period)
                    row["period_source"] = "slide_title"
                    period_inherited = True
                    stats["slide_title_periods"] += 1
                elif deck_asof and deck_asof_allowed(row, raw_text):
                    row["period"] = deck_asof
                    row["period_kind"] = period_kind_for("", deck_asof)
                    row["period_source"] = "deck_asof"
                    deck_period_used = True
                    stats["deck_asof"] += 1
            later_period = growth_change_period(row["period"] or "", row["measure"] or "", raw_text)
            if later_period != (row["period"] or ""):
                row["period"] = later_period          # stage N2: a growth takes the later half of its printed pair
                row["period_kind"] = period_kind_for("", later_period)
                stats["growth_periods"] += 1
            if apply_instant_period(row):        # stage L: "Closing as on <date>" is a point in time
                instant_used = True
                stats["instant_periods"] += 1
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
            row["basis_source"] = ""
            row["basis"] = detect_basis(row["printed_axis"] or "", row["series_title"] or "", head,
                                        words, row["region"] or "", row["group_path"] or "", raw_text)
            if not row["basis"]:                 # stage K: the standalone/consolidated header over the value
                row["basis"] = column_basis(words, row["region"] or "")
                if row["basis"]:
                    stats["basis_header"] += 1
            if not row["basis"]:                 # stage L: the page/section heading names the basis
                row["basis"] = page_basis(raw_text)
                if row["basis"]:
                    stats["basis_page"] += 1
            if not row["basis"] and page_deck_basis and family == "money":
                row["basis"] = page_deck_basis    # stage N: every basis word the deck prints says this one
                row["basis_source"] = "deck"
                stats["basis_deck"] += 1
            foot = footnote_basis(raw_text, row["period"] or "")
            if foot and row["basis"] != foot:
                row["basis"] = foot          # a footnote names this period's basis (id 20120)
                row["basis_source"] = ""
                stats["footnote_basis"] += 1
            basis_changed = bool(row["basis"]) and row["basis"] != old_basis
            cue = scope_cue(row, raw_text)
            if cue:
                if row["entity_scope"] != cue:
                    row["entity_scope"] = cue
                    stats["scope_cues"] += 1
                if cue == "customer" and not (row.get("customer") or ""):
                    heading = " | ".join([row["series_title"] or "", row["printed_label"] or "",
                                          row["printed_axis"] or ""])
                    row["customer"] = client_name(heading) or norm_space(row["series_title"]) or \
                        norm_space(row["printed_label"])
                    stats["customers_named"] += 1
            row["value_kind"] = lower_bound_kind(row)
            if row["value_kind"]:
                stats["lower_bounds"] += 1
            tick_fix = "axis_tick" in old_reason and not is_axis_tick(raw_text, row)
            if tick_fix:
                stats["ticks_cleared"] += 1
            dash_label = "is not in the page text layer" in old_reason and labels_match(row, text, ocr_text)
            if dash_label:
                stats["dash_labels"] += 1
            value_text_fix = "image_text" in old_reason and (
                value_printed(text, row["value_text"] or "") or value_printed(ocr_text, row["value_text"] or ""))
            if owner and row["entity_scope"] in ("company", "subsidiary", ""):
                row["entity_scope"] = "parent"
                stats["parent_rows"] += 1
            row.pop("_scale_notes", None)
            row["_is_total"] = derive_is_total(row)   # stage L: a printed "Total" label is known before the checks
            status, reasons = evaluate_status(dict(row), text, measures, raw_text, ocr_text, ocr_page)
            if any("generic_label" in reason for reason in reasons):
                stats["generic_labels"] += 1
            dictionary_fix = (("measure is not in the dictionary" in old_reason or "undeclared_new" in old_reason)
                              and (row["measure"] or "") in measures)
            count_unit_fix = ("no_unit:" in old_reason and str(row["measure"] or "").startswith("count.")
                              and not row["unit"])      # stage H: a count.* row's count is its unit
            row["_old_status"] = old_status
            row["_old_reason"] = old_reason
            row["_proof"] = (unit_inherited or period_inherited or mapped or stage_set or dictionary_fix
                             or scale_fixed or deck_period_used or cagr_set or basis_changed or count_unit_fix
                             or per_unit_fix or tick_fix or dash_label or value_text_fix or unit_family_fix
                             or instant_used)
            row["status"] = status
            row["status_reason"] = "; ".join(reasons)
            updated.append(row)
        before_measure = {int(r["observation_id"]): str(r["measure"]) for r in updated}
        kept = apply_map_orphans(updated)
        for row in updated:
            if all(row is not k for k in kept):
                con.execute("DELETE FROM observation WHERE observation_id=?", (int(row["observation_id"]),))
                stats["map_orphans"] += 1
        updated = kept
        for row in updated:
            row["_is_total"] = derive_is_total(row)
        stats["panels_split"] += split_panels(updated)
        stats["geography_cleared"] += apply_geography(updated, words)
        stats["stacked_parts"] += apply_stacked_parts(updated)
        stats["rank_counts"] += apply_rank_count(updated)
        stats["is_total_rows"] += sum(1 for r in updated if r["_is_total"])
        before_parts = {int(r["observation_id"]): str(r["status"]) for r in updated}
        apply_parts_sum(updated, stats)
        for row in updated:
            if "parts sum to the printed total" in str(row.get("status_reason") or ""):
                row["_proof"] = True        # the printed total and its parts are a proof (stage J)
                if before_parts.get(int(row["observation_id"])) != "verified" and row["status"] == "verified":
                    stats["parts_sum_restored"] += 1
        apply_series_kind(updated, raw_text)
        for row in updated:
            if str(row["measure"]) != before_measure.get(int(row["observation_id"]), ""):
                stats["measure_fixed"] += 1
        stats["bridge_rows"] += sum(1 for r in updated if r["series_kind"] == "bridge")
        stats["basis_set"] += sum(1 for r in updated if r["basis"])
        stats["basis_conflicts"] += apply_basis_conflicts(updated)
        for row in updated:
            old_status = str(row["_old_status"])
            old_reason = str(row["_old_reason"])
            status = str(row["status"])
            reason = str(row["status_reason"] or "")
            if status == "verified" and old_status != "verified":
                hard_old = "parts sum to" in old_reason or "geography_not_printed" in old_reason or \
                    ("scale " in old_reason and not row["_proof"])
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
            con.execute("UPDATE observation SET measure=?, printed_label=?, geography=?, series_id=?, unit=?, "
                        "unit_family=?, scale=?, value_kind=?, is_total=?, period=?, period_kind=?, period_source=?, "
                        "basis=?, basis_source=?, series_kind=?, adjusted=?, stage=?, entity_scope=?, customer=?, "
                        "text_source=?, status=?, status_reason=? WHERE observation_id=?",
                        (row["measure"], row["printed_label"], row["geography"], row["series_id"], row["unit"],
                         row["unit_family"], row["scale"], row.get("value_kind") or "",
                         1 if row.get("_is_total") else 0, row["period"],
                         row["period_kind"], row["period_source"], row["basis"], row.get("basis_source") or "",
                         row["series_kind"], row["adjusted"], row["stage"], row["entity_scope"],
                         row.get("customer") or "", row.get("text_source") or "", status, reason,
                         row["observation_id"]))
            stats["changed"] += 1
            if (row.get("text_source") or "") == "ocr":
                stats["text_source_ocr"] += 1
    # T-238 stage N: one name for one source -- rows written before the rename carried 'deck_period'.
    stale = con.execute("SELECT COUNT(*) FROM observation WHERE period_source='deck_period'").fetchone()[0]
    if stale:
        con.execute("UPDATE observation SET period_source='deck_asof' WHERE period_source='deck_period'")
        stats["deck_asof_renamed"] = int(stale)
    con.commit()
    if stats["unproven_upgrades"]:
        stats["stopped"] = (f"{stats['unproven_upgrades']} rows would verify without a new printed source; "
                            "their stage B status is kept")
    return stats


def run(store_dbs: list[str], limit: int, workers: int, out: str | Path,
        doc_types: Iterable[str] = ("deck",), seed: int = 11,
        required: Iterable[tuple[str, int]] = (), propose_limit: int = 300,
        resume: bool = False, skip_statements: bool = False,
        only: Any = None, text_only: bool = False) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    dropped_by_reason: dict[str, int] = {}
    for store_db in store_dbs:
        if only is not None and not only.store(store_db):
            continue
        pages.extend(pages_from_store(store_db, doc_types=doc_types, skip_statements=skip_statements,
                                      dropped=dropped_by_reason))
    if only is not None:                      # T-233: a scoped re-read is exactly the selection, not a sample
        pages = [p for p in pages if only.page(p["store"], p["doc_key"], p["page"])]
        selected = pages
    elif resume:
        # T-241 (24 Nov): resume used to sample `limit` pages first and drop the done ones after, so a fixed seed
        # re-picked the same pages every run and the rest of the queue was never read; drop the done pages first.
        con0 = create_db(out)
        todo = missing_pages(con0, pages)
        con0.close()
        selected = select_pages(todo, limit, seed, required)
    else:
        selected = select_pages(pages, limit, seed, required)
    # T-241 maker-checker-verifier: a bulk read needs an independent passing audit of this reader, and every
    # earlier audit checkpoint of this output DB must be graded pass (raises read_gate.GateError otherwise).
    # Scoped (--only) runs are gated too; the pilot allowance counts pages already in the output's ledger.
    from reality_engine.v2 import read_gate
    read_gate.check(list(doc_types), len(selected), out)
    reply_fp = ",".join(f"{d}:{read_gate.fingerprint(d)}" for d in doc_types)   # which prompt wrote page_reply.raw
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
    if only is not None:            # a scoped re-read replaces its pages in the --baseline copy, no duplicates
        con.executemany("DELETE FROM observation WHERE doc_key=? AND page=?",
                        [(str(p["doc_key"]), int(p["page"])) for p in selected])
        con.commit()
    already_done = 0
    if resume:
        before = len(selected)
        selected = missing_pages(con, selected)
        already_done = before - len(selected)
    stats: dict[str, Any] = {"pages": len(selected), "already_done": already_done, "read": 0, "errors": 0,
                             "parse_failures": 0, "dropped_all": 0, "observations": 0, "quarantined": 0,
                             "skipped": 0, "quota_skipped": 0, "parent_rows": 0, "http_429": 0,
                             "ocr_pages": 0, "ocr_rows": 0, "ocr_read_pages": 0, "image_text_rows": 0,
                             "numbers": 0, "statements": 0, "guidance_rows": 0, "undeclared_new": 0,
                             "in_tok": 0, "out_tok": 0, "latencies": [],
                             "statement_filter": statement_filter, "failed_replies": []}
    companies = company_index(store_dbs)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process_page, p["store"], p["doc_key"], p["page"], companies, text_only): p
                   for p in selected}
        done = 0
        for future in as_completed(futures):
            done += 1
            try:
                result = future.result()
            except Exception as exc:
                stats["errors"] += 1
                stats["failed_replies"].append({"error": f"{type(exc).__name__}: {exc}"})
                continue
            stats["in_tok"] += int(result.get("in_tok") or 0)
            stats["out_tok"] += int(result.get("out_tok") or 0)
            if result.get("seconds"):
                stats["latencies"].append(round(float(result["seconds"]), 2))
            if result.get("quota"):
                stats["quota_skipped"] += 1
                continue
            if result.get("skip"):
                stats["skipped"] += 1
                # A skip is permanent only when nothing failed: an image fetch that raised (busy raw store, Drive
                # fetch) on a page with no text layer is retried like an error (Eagle review, T-241).
                if not result.get("image_note"):
                    con.execute("INSERT OR REPLACE INTO page_read VALUES (?,?,?,?,?)",
                                (result["doc_key"], int(result["page"]), "skip", 0, ist_now()))
                    con.commit()
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
            if result.get("raw"):
                # T-241 (24 Nov): keep the reader's raw reply, so a script fix to parsing or row guards is re-applied
                # offline (re-parse) instead of paying for the page again; the checkpoint of 2,000 pages proved
                # the parse-side fixes keep coming.
                con.execute("INSERT OR REPLACE INTO page_reply VALUES (?,?,?,?,?)",
                            (result["doc_key"], int(result["page"]), reply_fp, result["raw"], ist_now()))
            if result.get("ocr_read"):
                stats["ocr_read_pages"] += 1
            if not rows:
                if not result["raw"].strip() or result["parsed"] == 0:
                    stats["parse_failures"] += 1
                    if len(stats["failed_replies"]) < 5:
                        stats["failed_replies"].append({"store": result["store"], "doc_key": result["doc_key"],
                                                        "page": result["page"], "raw": result["raw"][:2000]})
                else:
                    stats["dropped_all"] += 1      # a letterhead / cover page whose every row the script dropped
                    con.execute("INSERT OR REPLACE INTO page_read VALUES (?,?,?,?,?)",
                                (result["doc_key"], int(result["page"]), "empty", 0, ist_now()))
            else:
                con.execute("INSERT OR REPLACE INTO page_read VALUES (?,?,?,?,?)",
                            (result["doc_key"], int(result["page"]), "rows", len(rows), ist_now()))
            write_rows(con, rows)
            con.commit()                    # the page_read row too (write_rows of no rows does not commit)
            ckpt = read_gate.maybe_checkpoint(con, out)
            if ckpt is not None:            # a failed or ungraded audit must stop the reading, not the next run
                stats["stopped"] = f"audit checkpoint {ckpt.name} written: grade it (read_gate grade) to continue"
                for other in futures:
                    other.cancel()
                break
            if result.get("ocr_text"):
                con.execute("INSERT OR REPLACE INTO page_ocr VALUES (?,?,?,?,?)",
                            (result["doc_key"], int(result["page"]), result["ocr_text"], OCR_READER, ist_now()))
                stats["ocr_pages"] += 1
            stats["ocr_rows"] += sum(1 for r in rows if r.get("text_source") == "ocr")
            stats["image_text_rows"] += sum(1 for r in rows if "image_text" in str(r.get("status_reason") or ""))
            stats["numbers"] += sum(1 for r in rows if str(r.get("record_type") or "number") == "number")
            stats["statements"] += sum(1 for r in rows if r.get("record_type") == "statement")
            stats["guidance_rows"] += sum(1 for r in rows if r.get("record_type") == "guidance")
            stats["undeclared_new"] += sum(1 for r in rows if "undeclared_new" in str(r.get("status_reason") or ""))
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
    stats["new_measures"] = index_new_measures(con)      # T-238 stage M: counts, pages, definitions by NEW id
    stats["new_merges"] = write_new_merges(con, Path(str(out)).with_suffix(".new_merges.csv"))
    con.close()
    stats["seconds"] = round(time.time() - t0, 1)
    stats["out"] = str(out)
    latencies = sorted(float(s) for s in stats["latencies"])
    if latencies:
        stats["median_seconds"] = round(statistics.median(latencies), 2)
        stats["p90_seconds"] = round(latencies[int(round(0.9 * (len(latencies) - 1)))], 2)
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
    parser.add_argument("--doc-types", default="deck",
                        help="comma list: deck, annual_report, transcript (a transcript page is always text-only)")
    parser.add_argument("--propose-limit", type=int, default=300,
                        help="hy4 label->measure proposals at most (0 turns the pass off)")
    parser.add_argument("--require", default="", help="doc_key-substring:page to force into the sample")
    parser.add_argument("--resume", action="store_true",
                        help="skip pages that already have observation rows in --out (after a stopped run)")
    parser.add_argument("--recheck", action="store_true",
                        help="re-apply every script check to --out with no model call (stage C)")
    parser.add_argument("--skip-statements", action="store_true",
                        help="drop financial-statement/notes pages before any model call (stage F)")
    parser.add_argument("--only", default="",
                        help="T-233 selector JSON: re-process only these stores/doc_keys/pages")
    parser.add_argument("--baseline", default="",
                        help="with --only: copy this DB to --out first, then patch the copy")
    parser.add_argument("--reader", default=READER,
                        help="MODELS registry entry to read with (default hy4-flash-free; T-234 bake-off)")
    parser.add_argument("--reparse", action="store_true",
                        help="T-241: copy --baseline to --out and rebuild its transcript rows from page_reply (no model)")
    parser.add_argument("--transcript-prompt", choices=("v1", "v2"), default="v1",
                        help="T-241 transcript prompt: v1 (default) or v2 (fiscal periods, ranges, sign, speaker)")
    parser.add_argument("--text-only", action="store_true",
                        help="send the stored text layer only, no page image (T-234 text readers; transcript "
                             "pages are text-only already)")
    args = parser.parse_args(argv)
    try:
        set_reader(args.reader)
    except KeyError:
        parser.error(f"unknown --reader {args.reader!r}; known: {', '.join(sorted(rp.MODELS))}")
    apply_prompt_choice(args.transcript_prompt)

    only = None
    if args.only:
        from reality_engine.research.selector import Selector
        only = Selector.load(args.only)
    if args.baseline and (args.recheck or args.only or args.reparse):
        from reality_engine.research.selector import copy_db
        copy_db(args.baseline, args.out)      # T-238: a recheck reads --out, so the baseline must reach it first

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
    if args.reparse:                          # T-241: rebuild rows from page_reply; no model call, no read gate
        if not args.baseline:
            parser.error("--reparse needs --baseline (the DB with page_reply); --out receives the rebuilt copy")
        back = create_db(args.out)
        try:
            reparse_stats = reparse_db(back, store_dbs, only=only)
        finally:
            back.close()
        print(json.dumps(reparse_stats, indent=2))
        return 0 if reparse_stats.get("pages") else 2
    if args.recheck:
        back = create_db(args.out)
        try:
            recheck_stats = recheck_db(back, store_dbs, only=only)
        finally:
            back.close()
        print(json.dumps(recheck_stats, indent=2))
        if not recheck_stats.get("pages"):    # T-238: a recheck that read no page changed nothing, so it is no pass
            print(f"STOP: --recheck read 0 pages from {args.out}: the DB has no rows on the selected pages, "
                  "or no --stores/--only selection reaches them", file=sys.stderr)
            return 2
        if recheck_stats.get("stopped"):
            print(f"STOP: {recheck_stats['stopped']}", file=sys.stderr)
            return 2
        return 0
    required: list[tuple[str, int]] = []
    for item in args.require.split(","):
        if ":" in item:
            sub, page = item.rsplit(":", 1)
            required.append((sub.strip(), int(page)))
    from reality_engine.v2.read_gate import GateError
    try:
        stats = _run_main(args, store_dbs, doc_types, required, only)
    except GateError as exc:
        print(f"GATE: {exc}", file=sys.stderr)
        return 3
    return _report(stats)


def _run_main(args: argparse.Namespace, store_dbs: list[str], doc_types: list[str],
              required: list[tuple[str, int]], only: Any) -> dict[str, Any]:
    return run(store_dbs, args.limit, args.workers, args.out,
                doc_types=doc_types, seed=args.seed, required=required,
                propose_limit=args.propose_limit, resume=args.resume, skip_statements=args.skip_statements,
                only=only, text_only=args.text_only)


def _report(stats: dict[str, Any]) -> int:
    print(json.dumps(stats, indent=2))
    if stats.get("stopped"):
        print(f"STOP: {stats['stopped']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
