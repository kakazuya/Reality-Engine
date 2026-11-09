"""T-133 label dictionary: one metric per printed row label, per sector family.

A printed row label is normalised (:func:`normalise_label`), then mapped in this order: an exact seed from the
existing ``kpi_series`` rows, a lexicon phrase for the company's sector family, or a common financial line
shared by every family (``sector_family='*'``).  Everything written is ``status='queue'``: only Opus approves.

Every proposed metric gets a ``metric_def`` row (``flow`` / ``stock`` / ``ratio`` / ``per_share`` / ``count`` /
``price``), so the period engine sums only flows: a P&L line is additive, a balance-sheet line or an AUM is not.

CLI::

    python -m reality_engine.v2.label_map --cells-dir <v2 store dir> \\
        --kpi-db <pilot3 db> [--kpi-db <pilot3 db> ...] --out <dir>

writes ``<out>/label_map.db`` (``label_map`` + ``metric_def``, the v2 DDL), ``<out>/review_<family>.csv``
(one per family, sorted by frequency) and ``<out>/coverage.txt`` (mapped share of the numeric ``table_cell``
rows per family and overall, then the 50 most frequent unmapped labels).
"""
from __future__ import annotations

import argparse
import csv
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

# A child label this generic carries no metric by itself: keep its parent ('Segment Revenue > Others').
GENERIC = {"others", "other", "total", "revenue", "sales", "income", "expenses", "expenditure",
           "sub total", "subtotal", "total revenue", "total income", "total expenses", "total expenditure"}

# Words inside a bracket that make the bracket a unit, not part of the metric ("(Rs crore)", "(as a % of revenue)").
UNIT_TOKENS = {"in", "amount", "figure", "figures", "rs", "inr", "usd", "us", "eur", "euro", "gbp", "crore",
               "crores", "cr", "lakh", "lakhs", "million", "millions", "mn", "billion", "billions", "bn",
               "thousand", "thousands", "000", "000s", "%", "per", "cent", "and", "of", "as", "a", "revenue",
               "sales", "income", "turnover"}

NUMBERING = (
    re.compile(r"^\s*(?:\(\s*\d{1,3}\s*\)|\d{1,3}[.)])\s+", re.I),
    re.compile(r"^\s*(?:\(\s*[a-z]\s*\)|[a-z][.)])\s+", re.I),
    re.compile(r"^\s*(?:\(\s*(?:i{1,3}|iv|v|vi{0,3}|ix|x{1,3})\s*\)|"
               r"(?:i{1,3}|iv|v|vi{0,3}|ix|x{1,3})[.)])\s+", re.I),
)
BRACKET = re.compile(r"\(([^()]*)\)|\[([^\[\]]*)\]")

UNIT_ALIASES = {"inr_cr": "inr", "inr_bn": "inr", "inr_mn": "inr", "inr": "inr", "usd_mn": "usd",
                "usd": "usd", "usd_per_tonne": "usd_per_tonne", "pct": "pct", "percent": "pct", "bps": "bps",
                "x": "x", "num": "x", "days": "days", "count": "count", "count_mn": "count",
                "count_cr": "count", "kt": "tonnes", "tonnes": "tonnes", "ton": "tonnes",
                "inr_per_share": "inr_per_share"}

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
    "debenture_redemption_reserve", "network_towers", "population_covered",
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
}

RATIO_METRICS = {
    "monthly_churn", "current_ratio", "current_liability_ratio", "debt_to_assets_ratio", "lt_debt_to_wc_ratio",
    "dscr", "iscr", "debtors_turnover", "bad_debts_to_receivables", "pct_of_net_revenue", "pct_of_customer_base",
    "coverage_pct",
}

PRICE_METRICS = {"arpu", "price", "realisation", "realization"}

KIND_OVERRIDE = {
    "revenue": "flow", "borrowings": "stock", "total_borrowings": "stock", "ebitda_margin_pct": "ratio",
    "eps_basic": "per_share", "ebitda_per_tonne": "price", "cost_of_production": "price",
    "segment_assets": "stock", "segment_liabilities": "stock", "net_income": "flow",
}

# Common financial lines every family prints (the third tier, sector_family='*').  The lexicon files carry the
# sector phrases; these are the statement and note lines that are the same for every industry.
EXTRA_COMMON: dict[str, tuple[str, ...]] = {
    "ebit": ("ebit",),
    "ebitdaal": ("ebitdaal", "ebitda al"),
    "operating_ebitda": ("operating ebitda",),
    "revenue": ("net revenues", "net revenue", "total revenues", "total revenue", "net sales",
                "sale of products services", "sales of products services", "business income", "net revenue nr"),
    "other_income": ("other operating revenue", "other operating income", "non operating revenue",
                     "non operating income", "unallocable income"),
    "pat": ("net profit", "net income after exceptional items", "profit after tax after exceptional items"),
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
    "a_and_p_spend": ("advertising", "advertisement and sales promotion", "less advertising and sales promotion",
                      "a and sp"),
    "contribution": ("contribution",),
    "amortization": ("amortization", "amortisation"),
    "finance_cost": ("interest and bank charges",),
    "interest_income": ("interest received", "dividend income", "dividend received"),
    "cumulative_investments": ("cumulative investments",),
    "borrowings": ("borrowings", "borrowing"),
    "equity": ("equity",),
    "total_expenses": ("expenses", "expenditure"),
    "fees_and_commission_expense": ("fees and commission expenses", "fees and commission expense"),
    "airtel_money_revenue": ("airtel money revenue mn", "airtel money revenue"),
    "non_controlling_interest": ("non controlling interest", "non controlling interests",
                                 "non controlling interest nci"),
    "owners_equity": ("owners of the parent", "owners of the company", "owners of the group",
                      "owners of the parent company", "equity holders of the parent", "shareholders of the company"),
    "profit_attributable": ("profit for the period attributable to",),
    "total_comprehensive_income_attributable": ("total comprehensive income for the period attributable to",),
    "total_assets": ("total assets",),
    "total_liabilities": ("total liabilities",),
    "total_equity": ("total equity", "total equity and liabilities"),
    "total_financial_assets": ("financial assets",),
    "total_financial_liabilities": ("financial liabilities",),
    "investments": ("investments", "investment"),
    "investments_in_jvs": ("jvs",),
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
    "ebit_margin": ("ebit margin", "business ebit"),
    "operating_margin": ("operating margin",),
    "net_profit_margin": ("net profit margin",),
    "pat_margin_pct": ("pat margin",),
    "ebitda_margin_pct": ("ebitda margin", "ebitda total revenues", "ebitda per total revenues"),
    "ebitdaal_margin": ("ebitdaal margin",),
    "roce": ("return on capital employed", "return on capital employed annualised"),
    "roe_pct": ("return on shareholder s equity post tax", "return on shareholder s equity pre tax",
                "return on shareholders equity post tax", "return on shareholders equity pre tax"),
    "monthly_churn": ("monthly churn",),
    "current_ratio": ("current ratio",),
    "current_liability_ratio": ("current liability ratio",),
    "debt_to_assets_ratio": ("total debts to total assets ratio",),
    "lt_debt_to_wc_ratio": ("long term debt to working capital ratio",),
    "dscr": ("debt service coverage ratio",),
    "iscr": ("interest service coverage ratio",),
    "debtors_turnover": ("debtors turnover ratio annualised",),
    "bad_debts_to_receivables": ("bad debts to account receivable ratio",),
    "pct_of_net_revenue": ("as a of nr",),
    "pct_of_customer_base": ("as of customer base",),
    "total_minutes_on_network": ("total minutes on network mn", "minutes on the network mn"),
    "total_gbs_on_network": ("total gbs on the network mn",),
    "arpu": ("average revenue per user arpu", "arpu"),
    "net_additions": ("net additions 000 s", "net additions"),
    "network_towers": ("network towers nos", "network towers"),
    "employees": ("total employees nos", "total employees"),
    "price": ("price in rs te", "price in rs per te", "overall average realization", "realisation", "realization"),
    "volume": ("qty in mill te", "quantity in mill te"),
    "population_covered": ("population covered bn", "population coverage"),
    "coverage_pct": ("coverage",),
    "voice_revenue": ("voice revenue mn", "voice revenue"),
    "data_revenue": ("data revenue mn", "data revenue"),
    "passive_infrastructure_services": ("passive infrastructure services",),
    "network_operations_cost": ("network operations costs",),
    "basic_eps": ("basic eps", "basic earnings per share"),
    "diluted_eps": ("diluted eps", "diluted earnings per share"),
}

# A parent section that names the measure: the child is a segment/product, so the label alone would be unmapped
# (or, worse, matched to the same words on a company-level line).  These win over the child-only proposal.
SECTION_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("segment assets", "segment_assets"),
    ("segment liabilities", "segment_liabilities"),
    ("segment results", "segment_results"),
    ("segment revenue", "segment_revenue"),
    ("segment ebitda", "segment_ebitda"),
    ("jvs", "investments_in_jvs"),
    ("items that will not be reclassified", "other_comprehensive_income"),
    ("items that will be reclassified", "other_comprehensive_income"),
    ("other comprehensive income oci", "other_comprehensive_income"),
    ("profit for the period attributable to", "profit_attributable"),
    ("total comprehensive income for the period attributable to", "total_comprehensive_income_attributable"),
)

# A parent that states the value is a percentage of another line: the metric is the child's metric with `_pct`.
PERCENT_PARENTS = ("as a of total revenues", "as a of revenue", "as a of total income", "as a of sales")

PCT_SPECIAL = {"ebitda": "ebitda_margin_pct", "ebit": "ebit_margin", "pat": "pat_margin_pct", "pbt": "pbt_margin"}


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


def normalise_label(raw: str | None, parent: str | None = None) -> str:
    """Normalise one printed row label; keep the parent only when the child alone is generic.

    >>> normalise_label("1. Revenue from operations") == normalise_label("Revenue from Operations (Rs crore)")
    True
    >>> normalise_label("Others", "Segment Revenue")
    'segment revenue > others'
    """
    text = _clean(raw)
    if not text:
        return ""
    if parent and text in GENERIC:
        head = " > ".join(part for part in (_clean(piece) for piece in parent.split(" > ")) if part)
        return f"{head} > {text}" if head else text
    return text


def normalise_cell_label(raw: str | None) -> str:
    """Normalise a ``table_cell.row_label`` that already carries ``section > label`` from the cell builder."""
    parts = [part for part in str(raw or "").split(" > ") if part.strip()]
    if not parts:
        return ""
    return normalise_label(parts[-1], " > ".join(parts[:-1]) or None)


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


@dataclass(frozen=True)
class Proposal:
    metric: str
    reason: str
    family: str
    entry: Entry | None = None


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
    best = 0
    for phrase in entry.phrases:
        if not phrase:
            continue
        found = re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text)
        if found:
            best = max(best, found.end() - found.start())
    for pattern in entry.patterns:
        try:
            found = re.search(pattern, text, re.IGNORECASE)
        except re.error:
            continue
        if found:
            best = max(best, found.end() - found.start())
    if not best:
        return 0
    for neg in entry.neg:
        if neg and re.search(neg, text, re.IGNORECASE):
            return 0
    return best


def _best(entries: Sequence[Entry], text: str) -> Entry | None:
    best, best_length = None, 0
    for entry in entries:
        length = _match_entry(entry, text)
        if length > best_length:
            best, best_length = entry, length
    return best


def propose_metric(label_norm: str, family: str, seeds: Mapping[tuple[str, str], str],
                   family_entries: Mapping[str, Sequence[Entry]],
                   common: Sequence[Entry]) -> Proposal | None:
    """Seed first, then the family's lexicon, then the common lines (``sector_family='*'``)."""
    if not label_norm:
        return None
    seeded = seeds.get((label_norm, family))
    if seeded:
        return Proposal(seeded, "seed", family)
    entry = _best(family_entries.get(family, ()), label_norm)
    if entry is not None:
        return Proposal(entry.metric, f"lexicon:{entry.source}", family, entry)
    entry = _best(common, label_norm)
    if entry is not None:
        return Proposal(entry.metric, f"common:{entry.source}", ALL_FAMILIES, entry)
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


def resolve_unit_kind(metric: str, meta: MetricMeta | None) -> str:
    if meta is not None and meta.units:
        counts: Counter[str] = Counter()
        for unit, count in meta.units.items():
            counts[normalise_unit(unit)] += count
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    if meta is not None and meta.entry_unit:
        return normalise_unit(meta.entry_unit)
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


def read_kpis(taxonomy: sqlite3.Connection, table: dict, db_paths: Sequence[Path],
              observations: dict[tuple[str, str], Observation],
              seeds: dict[tuple[str, str], Counter[str]],
              meta: dict[str, MetricMeta], isin_by_symbol: dict[str, str],
              family_cache: dict[tuple[str | None, str | None], str]) -> int:
    """Seed mappings and label observations from ``kpi_series``; returns the rows read."""
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
                label_norm = normalise_label(raw_label)
                if not label_norm:
                    continue
                seeds.setdefault((label_norm, family), Counter())[metric] += 1
                metric_meta = meta.setdefault(metric, MetricMeta())
                if unit:
                    metric_meta.units[str(unit)] += 1
                metric_meta.sources.add("seed")
                _observe(observations, (label_norm, family), raw_label, symbol)
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
    return Entry(metric, source="label_map:section", kind="money", unit="inr")


def read_cells(cells_dir: Path, taxonomy: sqlite3.Connection, table: dict, isin_symbol: Mapping[str, str],
               observations: dict[tuple[str, str], Observation], numeric: Counter[tuple[str, str]],
               blank_numeric: Counter[str], seeds: Mapping[tuple[str, str], str],
               family_entries: Mapping[str, Sequence[Entry]], common: Sequence[Entry],
               forced: dict[tuple[str, str], Proposal]) -> dict[str, int]:
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
            for raw_label, value in _rows(con, "SELECT row_label, value FROM table_cell"):
                cells += 1
                plain = normalise_cell_label(raw_label)
                if not plain:
                    if value is not None:
                        blank_numeric[family] += 1
                    continue
                parent, full = _parent_label(raw_label, plain)
                key_label, proposal = plain, None
                if parent:
                    metric = _section_metric(parent)
                    if metric:
                        key_label = full
                        proposal = Proposal(metric, "section", family, _section_entry(metric, "section"))
                    elif any(needle in parent for needle in PERCENT_PARENTS):
                        base = propose_metric(plain, family, seeds, family_entries, common)
                        metric = _pct_metric(base.metric if base else plain.replace(" ", "_"))
                        key_label = full
                        proposal = Proposal(metric, "section:pct", family, _section_entry(metric, "section:pct"))
                if proposal is None and propose_metric(plain, family, seeds, family_entries, common) is None \
                        and parent and propose_metric(full, family, seeds, family_entries, common) is not None:
                    key_label = full
                if proposal is not None:
                    forced[(key_label, family)] = proposal
                _observe(observations, (key_label, family), str(raw_label or ""), symbol)
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
        sources[proposal.metric].add(proposal.reason)
        metrics.setdefault(proposal.metric, MetricMeta())
        if proposal.entry is not None:
            entry = proposal.entry
            if entry.unit:
                metrics[proposal.metric].units[entry.unit] += 1
            if entry.kind and not metrics[proposal.metric].entry_kind:
                metrics[proposal.metric].entry_kind = entry.kind
    for metric, metric_meta in meta.items():  # seed units are observed facts, so they rank above lexicon wording
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


def write_csv(path: Path, rows: Iterable[dict]) -> None:
    columns = ("label_norm", "raw_labels", "frequency", "companies", "proposed_metric", "dimension",
               "unit_kind", "reason")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(out_dir: Path, proposals: Mapping[tuple[str, str], Proposal],
                  observations: Mapping[tuple[str, str], Observation], numeric: Counter[tuple[str, str]],
                  blank_numeric: Counter[str], metric_meta: dict[str, MetricMeta]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    metric_defs = _metric_defs(proposals.values(), metric_meta)
    unit_by_metric = {row["metric"]: row["unit_kind"] for row in metric_defs}

    database = out_dir / "label_map.db"
    conn = sqlite3.connect(database)
    try:
        schema.create(conn)
        conn.execute("DELETE FROM label_map")
        conn.execute("DELETE FROM metric_def")
        conn.executemany(
            "INSERT INTO label_map (label_norm, sector_family, metric, dimension, unit_kind, status) "
            "VALUES (?,?,?,?,?,'queue')",
            [(label_norm, family, proposal.metric, "", unit_by_metric.get(proposal.metric, ""))
             for (label_norm, family), proposal in sorted(proposals.items())])
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
    for family in sorted(by_family):
        rows = []
        for label_norm, obs in sorted(by_family[family], key=lambda item: (-item[1].count, item[0])):
            proposal = proposals.get((label_norm, family))
            if proposal is None:
                proposal = next((p for (norm, fam), p in proposals.items()
                                 if fam == ALL_FAMILIES and norm == label_norm), None)
            metric = proposal.metric if proposal else ""
            rows.append({"label_norm": label_norm,
                         "raw_labels": "; ".join(raw for raw, _ in obs.raws.most_common(3)),
                         "frequency": obs.count,
                         "companies": ";".join(sorted(obs.companies)),
                         "proposed_metric": metric, "dimension": "",
                         "unit_kind": unit_by_metric.get(metric, "") if metric else "",
                         "reason": proposal.reason if proposal else ""})
        write_csv(out_dir / f"review_{family}.csv", rows)

    # The '*' queue, one row per shared label, with the observations it covers.
    common_totals: Counter[str] = Counter()
    common_companies: dict[str, set[str]] = defaultdict(set)
    common_raws: dict[str, Counter[str]] = defaultdict(Counter)
    for (label_norm, _family), obs in observations.items():
        if (label_norm, ALL_FAMILIES) in proposals:
            common_totals[label_norm] += obs.count
            common_companies[label_norm] |= obs.companies
            common_raws[label_norm].update(obs.raws)
    write_csv(out_dir / "review_common.csv", [
        {"label_norm": label_norm, "raw_labels": "; ".join(raw for raw, _ in common_raws[label_norm].most_common(3)),
         "frequency": common_totals[label_norm], "companies": ";".join(sorted(common_companies[label_norm])),
         "proposed_metric": proposals[(label_norm, ALL_FAMILIES)].metric, "dimension": "",
         "unit_kind": unit_by_metric.get(proposals[(label_norm, ALL_FAMILIES)].metric, ""),
         "reason": proposals[(label_norm, ALL_FAMILIES)].reason}
        for label_norm in sorted(common_totals, key=lambda name: (-common_totals[name], name))])

    # Coverage over numeric table rows (value IS NOT NULL), per family and overall.
    families = sorted({family for _, family in numeric} | set(blank_numeric))
    total_numeric = sum(numeric.values()) + sum(blank_numeric.values())
    total_mapped = sum(count for (label_norm, family), count in numeric.items()
                       if (label_norm, family) in proposals or (label_norm, ALL_FAMILIES) in proposals)
    unmapped: Counter[str] = Counter()
    for (label_norm, family), count in numeric.items():
        if (label_norm, family) not in proposals and (label_norm, ALL_FAMILIES) not in proposals:
            unmapped[label_norm] += count
    family_counts: dict[str, tuple[int, int]] = {}
    for family in families:
        rows = sum(count for (norm, fam), count in numeric.items() if fam == family) + blank_numeric[family]
        mapped = sum(count for (norm, fam), count in numeric.items() if fam == family
                     and ((norm, fam) in proposals or (norm, ALL_FAMILIES) in proposals))
        family_counts[family] = (rows, mapped)
    labeled_rows = total_numeric - sum(blank_numeric.values())
    lines = [
        "label map coverage (T-133)",
        f"numeric table_cell rows: {total_numeric}",
        f"mapped to a proposed metric: {total_mapped} ({100 * total_mapped / total_numeric:.1f}%)"
        if total_numeric else "mapped to a proposed metric: 0",
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
            "mapped_rows": total_mapped, "total": total_numeric}


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
    try:
        kpi_rows = read_kpis(taxonomy, table, kpi_dbs, observations, seed_counts, metric_meta, isin_symbol,
                             family_cache)
        seeds = {key: sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]
                 for key, counter in seed_counts.items()}
        cell_stats = read_cells(cells_dir, taxonomy, table, isin_symbol, observations, numeric, blank_numeric,
                                seeds, family_entries, common, forced)
    finally:
        taxonomy.close()

    proposals: dict[tuple[str, str], Proposal] = {}
    for label_norm, family in sorted(observations):
        if (label_norm, family) in forced:
            continue
        proposal = propose_metric(label_norm, family, seeds, family_entries, common)
        if proposal is None:
            continue
        key = (label_norm, proposal.family)
        proposals.setdefault(key, proposal)
        metric_meta.setdefault(proposal.metric, MetricMeta()).sources.add(proposal.reason)
    for key, proposal in forced.items():  # a section override wins over the child-only proposal
        proposals[key] = proposal
        metric_meta.setdefault(proposal.metric, MetricMeta()).sources.add(proposal.reason)

    stats = write_outputs(out_dir, proposals, observations, numeric, blank_numeric, metric_meta)
    stats.update({"kpi_rows": kpi_rows, **cell_stats, "observations": len(observations)})
    reasons = Counter(proposal.reason.split(":")[0] for proposal in proposals.values())
    kinds = Counter(row["kind"] for row in _metric_defs(proposals.values(), metric_meta))
    families = sorted({family for _, family in observations})
    unknown_companies = sorted({company for (_, family), obs in observations.items() if family == UNKNOWN
                                for company in obs.companies})
    print(f"label map: {len(proposals)} rows from {len(observations)} (label, family) observations; "
          f"seed {reasons['seed']}, lexicon {reasons['lexicon']}, common {reasons['common']}, "
          f"section {reasons['section']}")
    print(f"sources: kpi_series {kpi_rows} rows from {len(kpi_dbs)} db(s); table_cell {cell_stats['cells']} cells "
          f"from {cell_stats['files']} company file(s)")
    print(f"metric_def: {stats['metrics']} metrics; kinds " +
          ", ".join(f"{kind} {count}" for kind, count in sorted(kinds.items())))
    print(f"families: {', '.join(families)}")
    if unknown_companies:
        print(f"unknown family companies ({len(unknown_companies)}): {', '.join(unknown_companies)}")
    print(f"coverage: {stats['mapped_rows']}/{stats['numeric_rows']} numeric rows "
          f"({100 * stats['mapped_rows'] / stats['numeric_rows']:.1f}%)" if stats["numeric_rows"] else
          "coverage: no numeric rows")
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
