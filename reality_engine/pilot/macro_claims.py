"""macro_claim_target pilot (G10 / policy_target) — deterministic claim -> target map.

Every claim is one row of the held ``policy_events`` table (``claim_id`` = its id, so
a reviewer can always diff the pilot back to the source row).  Targets are derived
from three deterministic maps only — no reader, no model, no network:

  * sector / basic-industry aliases keyed on the claim's own ``sectors`` list;
  * a tariff / HS-chapter -> industry map plus product-name aliases (tariff and tax
    claims only, so a budget allocation cannot accidentally hit a product map);
  * named listed companies from the claim's ``companies`` list, resolved to ISIN by
    exact symbol, exact normalised name or a company-name prefix — never a loose
    substring (a substring match turns "Air India" into Tenneco Clean Air India).

Tables are created from ``tasks/arch_v3/SCHEMA_V3.sql`` itself (via
``build_t1.create_schema``) so the pilot cannot drift from the design DDL.  Two
pilot-only columns are added to ``macro_claim`` because the brief asks for them
and SCHEMA_V3 §macro_claim does not carry them yet: ``paraphrase`` (<= 30 words)
and ``known_at`` (copied from ``macro_doc``; the planner still joins the doc).

    python -m reality_engine.pilot.macro_claims --out .tmp/pilot
    python -m reality_engine.pilot.macro_claims --out .tmp/pilot --quota 60

Output: ``<out>/macro_pilot.db`` and ``<out>/macro_pilot_meta.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot.build_t1 import create_schema

REPO = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO / "tasks" / "arch_v3" / "SCHEMA_V3.sql"
DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT", REPO / "reality_engine" / "data"))
EI = DATA_ROOT / "equity_intelligence.db"
DB_NAME = "macro_pilot.db"
KEEP = {"macro_doc", "macro_claim", "macro_claim_target", "policy_target",
        "ix_mclaim_doc", "ix_mclaim_type", "ix_mct_target"}

# The pilot strata: (stratum, quota).  Union Budget is 30 per published year (2024-26),
# RBI splits into policy statements and MPC minutes, PIB is round-robin by ministry,
# tariff notices are 25 per year.  Quotas sum to 300.
QUOTA = {"budget": 90, "rbi": 75, "pib": 60, "tariff": 75}

POLICY_TYPE = {
    "customs_duty": "tariff", "tariff_trade": "tariff", "tender": "tender",
    "subsidy": "subsidy", "pli_incentive": "pli", "capex_sanction": "capex",
    "capex": "capex", "procurement": "capex", "auction_allocation": "capex",
    "monetary": "rate", "regulation": "regulation", "licensing": "regulation",
    "price_control": "regulation", "tax": "tax", "msp": "tax",
}
TARGET_DIRECTION = {"positive": "positive", "negative": "negative",
                    "neutral": "neutral", "mixed": "neutral"}

# --- claim -> sector / basic industry -------------------------------------------------
# Only terms whose own definition names the industry are listed.  A term that is not
# here yields no target: precision first (the brief's bar is 0.90, not coverage).
SECTOR_TERMS: dict[str, tuple[tuple[str, str], ...]] = {
    "banking": (("basic_industry", "Private Sector Bank"),
                ("basic_industry", "Public Sector Bank"),
                ("basic_industry", "Other Bank")),
    "banking and financial services": (("sector", "Financial Services"),),
    "banks": (("basic_industry", "Private Sector Bank"),
              ("basic_industry", "Public Sector Bank")),
    "bank credit and lending rates": (("basic_industry", "Private Sector Bank"),
                                      ("basic_industry", "Public Sector Bank")),
    "financial services": (("sector", "Financial Services"),),
    "financials": (("sector", "Financial Services"),),
    "nbfc": (("basic_industry", "Non Banking Financial Company (NBFC)"),),
    "nbfcs": (("basic_industry", "Non Banking Financial Company (NBFC)"),),
    "housing finance": (("basic_industry", "Housing Finance Company"),),
    "microfinance": (("basic_industry", "Microfinance Institutions"),),
    "fintech": (("basic_industry", "Financial Technology (Fintech)"),),
    "digital payments": (("basic_industry", "Financial Technology (Fintech)"),),
    "payments": (("basic_industry", "Financial Technology (Fintech)"),),
    "insurance": (("basic_industry", "Life Insurance"),
                  ("basic_industry", "General Insurance")),
    "health insurance": (("basic_industry", "General Insurance"),),
    "asset management": (("basic_industry", "Asset Management Company"),),
    "capital markets": (("basic_industry", "Stockbroking & Allied"),
                        ("basic_industry", "Asset Management Company"),
                        ("basic_industry", "Exchange and Data Platform")),
    "financial markets": (("basic_industry", "Stockbroking & Allied"),
                          ("basic_industry", "Exchange and Data Platform")),
    "mutual funds": (("basic_industry", "Asset Management Company"),),
    "stock exchanges": (("basic_industry", "Exchange and Data Platform"),),
    "construction": (("sector", "Construction"),),
    "infrastructure": (("sector", "Construction"),),
    "urban infrastructure": (("sector", "Construction"),),
    "rural infrastructure": (("sector", "Construction"),),
    "industrial infrastructure": (("sector", "Construction"),),
    "roads": (("basic_industry", "Civil Construction"),
              ("basic_industry", "Road Assets - Toll Annuity Hybrid-Annuity")),
    "highways": (("basic_industry", "Civil Construction"),
                 ("basic_industry", "Road Assets - Toll Annuity Hybrid-Annuity")),
    "rural roads": (("basic_industry", "Civil Construction"),),
    "metro rail": (("basic_industry", "Civil Construction"),),
    "railways": (("basic_industry", "Railway Wagons"),),
    "cement": (("basic_industry", "Cement & Cement Products"),),
    "steel": (("basic_industry", "Iron & Steel Products"),
              ("basic_industry", "Sponge Iron"), ("basic_industry", "Pig Iron")),
    "metals": (("sector", "Metals & Mining"),),
    "mining": (("sector", "Metals & Mining"),),
    "aluminium": (("basic_industry", "Aluminium"),
                  ("basic_industry", "Aluminium Copper & Zinc Products")),
    "aluminum": (("basic_industry", "Aluminium"),
                 ("basic_industry", "Aluminium Copper & Zinc Products")),
    "copper": (("basic_industry", "Copper"),
               ("basic_industry", "Aluminium Copper & Zinc Products")),
    "critical minerals": (("sector", "Metals & Mining"),),
    "power": (("sector", "Power"),),
    "electricity": (("sector", "Power"),),
    "electricity distribution": (("basic_industry", "Power Distribution"),),
    "power distribution": (("basic_industry", "Power Distribution"),),
    "renewable energy": (("sector", "Power"),),
    "solar": (("sector", "Power"),),
    "solar energy": (("sector", "Power"),),
    "nuclear energy": (("sector", "Power"),),
    "energy storage": (("basic_industry", "Other Electrical Equipment"),),
    "oil & gas": (("sector", "Oil Gas & Consumable Fuels"),),
    "oil and gas": (("sector", "Oil Gas & Consumable Fuels"),),
    "petroleum": (("sector", "Oil Gas & Consumable Fuels"),),
    "natural gas": (("sector", "Oil Gas & Consumable Fuels"),),
    "coal": (("basic_industry", "Coal"),),
    "water": (("basic_industry", "Water Supply & Management"),),
    "water supply": (("basic_industry", "Water Supply & Management"),),
    "sanitation": (("basic_industry", "Waste Management"),
                   ("basic_industry", "Water Supply & Management")),
    "waste management": (("basic_industry", "Waste Management"),),
    "healthcare": (("sector", "Healthcare"),),
    "health": (("sector", "Healthcare"),),
    "hospitals": (("basic_industry", "Hospital"),),
    "pharmaceuticals": (("basic_industry", "Pharmaceuticals"),),
    "medical devices": (("basic_industry", "Medical Equipment & Supplies"),),
    "education": (("basic_industry", "Education"),),
    "school education": (("basic_industry", "Education"),),
    "higher education": (("basic_industry", "Education"),),
    "skill development": (("basic_industry", "Education"),),
    "skilling": (("basic_industry", "Education"),),
    "vocational training": (("basic_industry", "Education"),),
    "edtech": (("basic_industry", "E-Learning"),),
    "education technology": (("basic_industry", "E-Learning"),),
    "agriculture": (("basic_industry", "Other Agricultural Products"),),
    "agri-inputs": (("basic_industry", "Pesticides & Agrochemicals"),),
    "seeds": (("basic_industry", "Other Agricultural Products"),),
    "fertilizers": (("basic_industry", "Fertilizers"),),
    "fertilisers": (("basic_industry", "Fertilizers"),),
    "food processing": (("basic_industry", "Packaged Foods"),
                        ("basic_industry", "Other Food Products")),
    "dairy": (("basic_industry", "Dairy Products"),),
    "sugar": (("basic_industry", "Sugar"),),
    "edible oils": (("basic_industry", "Edible Oil"),),
    "edible oil": (("basic_industry", "Edible Oil"),),
    "textiles": (("sector", "Textiles"),),
    "textile": (("sector", "Textiles"),),
    "garments": (("basic_industry", "Garments & Apparels"),),
    "apparel": (("basic_industry", "Garments & Apparels"),),
    "technical textiles": (("basic_industry", "Other Textile Products"),),
    "leather": (("basic_industry", "Leather And Leather Products"),),
    "footwear": (("basic_industry", "Footwear"),),
    "gems and jewellery": (("basic_industry", "Gems Jewellery And Watches"),),
    "gems & jewellery": (("basic_industry", "Gems Jewellery And Watches"),),
    "gems jewellery and watches": (("basic_industry", "Gems Jewellery And Watches"),),
    "tourism": (("basic_industry", "Hotels & Resorts"),
                ("basic_industry", "Tour Travel Related Services")),
    "hospitality": (("basic_industry", "Hotels & Resorts"),),
    "hotels": (("basic_industry", "Hotels & Resorts"),),
    "retail": (("basic_industry", "Speciality Retail"),
               ("basic_industry", "Diversified Retail")),
    "e-commerce": (("basic_industry", "E-Retail/ E-Commerce"),
                   ("basic_industry", "Internet & Catalogue Retail")),
    "automobile": (("sector", "Automobile and Auto Components"),),
    "automobiles": (("sector", "Automobile and Auto Components"),),
    "automotive": (("sector", "Automobile and Auto Components"),),
    "electric vehicles": (("sector", "Automobile and Auto Components"),),
    "tyres": (("basic_industry", "Tyres & Rubber Products"),),
    "aviation": (("basic_industry", "Airline"),),
    "airlines": (("basic_industry", "Airline"),),
    "airports": (("basic_industry", "Airport & Airport services"),),
    "shipping": (("basic_industry", "Shipping"),),
    "ports": (("basic_industry", "Port & Port services"),),
    "shipbuilding": (("basic_industry", "Ship Building & Allied Services"),),
    "logistics": (("basic_industry", "Logistics Solution Provider"),),
    "warehousing": (("basic_industry", "Logistics Solution Provider"),),
    "telecom": (("sector", "Telecommunication"),),
    "information technology": (("sector", "Information Technology"),),
    "it services": (("sector", "Information Technology"),),
    "it": (("sector", "Information Technology"),),
    "technology": (("sector", "Information Technology"),),
    "software": (("sector", "Information Technology"),),
    "artificial intelligence": (("sector", "Information Technology"),),
    "semiconductors": (("basic_industry", "Consumer Electronics"),
                       ("basic_industry", "Other Electrical Equipment")),
    "batteries": (("basic_industry", "Auto Components & Equipments"),
                  ("basic_industry", "Other Electrical Equipment")),
    "ev": (("sector", "Automobile and Auto Components"),),
    "finance": (("sector", "Financial Services"),),
    "skills": (("basic_industry", "Education"),),
    "skills training": (("basic_industry", "Education"),),
    "heavy engineering": (("sector", "Capital Goods"),),
    "biotechnology": (("basic_industry", "Biotechnology"),),
    "roadways": (("basic_industry", "Civil Construction"),),
    "defence": (("basic_industry", "Aerospace & Defense"),),
    "defense": (("basic_industry", "Aerospace & Defense"),),
    "space": (("basic_industry", "Aerospace & Defense"),),
    "chemicals": (("sector", "Chemicals"),),
    "capital goods": (("sector", "Capital Goods"),),
    "services": (("sector", "Services"),),
    "electronics": (("basic_industry", "Consumer Electronics"),
                    ("basic_industry", "Other Electrical Equipment")),
    "electronics manufacturing": (("basic_industry", "Consumer Electronics"),
                                 ("basic_industry", "Other Electrical Equipment")),
    "agriculture and allied": (("basic_industry", "Other Agricultural Products"),),
    "consumer durables": (("sector", "Consumer Durables"),),
    "depositories": (("basic_industry", "Depositories Clearing Houses and Other Intermediaries"),),
    "depository": (("basic_industry", "Depositories Clearing Houses and Other Intermediaries"),),
    "agri-allied": (("basic_industry", "Other Agricultural Products"),),
    "agri allied": (("basic_industry", "Other Agricultural Products"),),
    "real estate": (("sector", "Realty"),),
    "housing": (("sector", "Realty"),
                ("basic_industry", "Residential Commercial Projects")),
    "affordable housing": (("sector", "Realty"),
                           ("basic_industry", "Residential Commercial Projects")),
    "rural housing": (("basic_industry", "Residential Commercial Projects"),),
}

# --- tariff / HS code -> industry ----------------------------------------------------
# Only strings that are unambiguously in the customs schedule.  Applied to tariff/tax
# claims only (the product field of a budget allocation is not a customs line).
PRODUCT_TERMS: dict[str, tuple[tuple[str, str], ...]] = {
    "gold": (("basic_industry", "Gems Jewellery And Watches"),
             ("basic_industry", "Precious Metals")),
    "silver": (("basic_industry", "Gems Jewellery And Watches"),
               ("basic_industry", "Precious Metals")),
    "platinum": (("basic_industry", "Precious Metals"),),
    "jewellery": (("basic_industry", "Gems Jewellery And Watches"),),
    "mobile phone": (("basic_industry", "Consumer Electronics"),),
    "cellular mobile": (("basic_industry", "Consumer Electronics"),),
    "medical implant": (("basic_industry", "Medical Equipment & Supplies"),),
    "medical device": (("basic_industry", "Medical Equipment & Supplies"),),
    "x-ray": (("basic_industry", "Medical Equipment & Supplies"),),
    "cancer medicine": (("basic_industry", "Pharmaceuticals"),),
    "generic drug": (("basic_industry", "Pharmaceuticals"),),
    "medicines": (("basic_industry", "Pharmaceuticals"),),
    "steel": (("basic_industry", "Iron & Steel Products"),),
    "iron": (("basic_industry", "Iron & Steel Products"),),
    "aluminium": (("basic_industry", "Aluminium"),),
    "aluminum": (("basic_industry", "Aluminium"),),
    "copper": (("basic_industry", "Copper"),),
    "solar cell": (("sector", "Power"), ("basic_industry", "Other Electrical Equipment")),
    "solar module": (("sector", "Power"), ("basic_industry", "Other Electrical Equipment")),
    "solar glass": (("basic_industry", "Glass - Industrial"),
                    ("sector", "Power")),
    "lithium": (("basic_industry", "Other Electrical Equipment"),),
    "critical mineral": (("sector", "Metals & Mining"),),
    "soyabean": (("basic_industry", "Edible Oil"),),
    "sunflower": (("basic_industry", "Edible Oil"),),
    "palm oil": (("basic_industry", "Edible Oil"),),
    "edible oil": (("basic_industry", "Edible Oil"),),
    "fertiliser": (("basic_industry", "Fertilizers"),),
    "fertilizer": (("basic_industry", "Fertilizers"),),
    "urea": (("basic_industry", "Fertilizers"),),
    "petrochemical": (("basic_industry", "Petrochemicals"),),
    "polymer": (("basic_industry", "Petrochemicals"),
                ("basic_industry", "Plastic Products - Industrial")),
    "spandex": (("basic_industry", "Other Textile Products"),),
    "yarn": (("sector", "Textiles"),),
    "cotton": (("sector", "Textiles"),),
    "fabric": (("sector", "Textiles"),),
    "garment": (("basic_industry", "Garments & Apparels"),),
    "shrimp": (("basic_industry", "Seafood"),),
    "seafood": (("basic_industry", "Seafood"),),
    "paper": (("basic_industry", "Paper & Paper Products"),),
    "pulp": (("basic_industry", "Paper & Paper Products"),),
    "tyre": (("basic_industry", "Tyres & Rubber Products"),),
    "rubber": (("basic_industry", "Tyres & Rubber Products"),),
    "aircraft": (("basic_industry", "Aerospace & Defense"),),
    "nuclear": (("sector", "Power"),),
    "cement": (("basic_industry", "Cement & Cement Products"),),
    "coal": (("basic_industry", "Coal"),),
    "natural gas": (("basic_industry", "LPG/CNG/PNG/LNG Supplier"),),
    "ferro-nickel": (("basic_industry", "Iron & Steel Products"),),
    "micro oven": (("basic_industry", "Household Appliances"),),
    "microwave oven": (("basic_industry", "Household Appliances"),),
    "battery": (("basic_industry", "Auto Components & Equipments"),
                ("basic_industry", "Other Electrical Equipment")),
    "granite": (("basic_industry", "Granites & Marbles"),),
    "marble": (("basic_industry", "Granites & Marbles"),),
    "footwear": (("basic_industry", "Footwear"),
                 ("basic_industry", "Leather And Leather Products")),
}

HS_CHAPTERS: dict[str, tuple[tuple[str, str], ...]] = {
    "27": (("sector", "Oil Gas & Consumable Fuels"),),
    "28": (("basic_industry", "Commodity Chemicals"),),
    "29": (("basic_industry", "Commodity Chemicals"),),
    "30": (("basic_industry", "Pharmaceuticals"),),
    "31": (("basic_industry", "Fertilizers"),),
    "32": (("basic_industry", "Dyes And Pigments"), ("basic_industry", "Paints")),
    "39": (("basic_industry", "Plastic Products - Industrial"),
           ("basic_industry", "Petrochemicals")),
    "40": (("basic_industry", "Tyres & Rubber Products"),),
    "48": (("basic_industry", "Paper & Paper Products"),),
    "50": (("sector", "Textiles"),), "51": (("sector", "Textiles"),),
    "52": (("sector", "Textiles"),), "53": (("sector", "Textiles"),),
    "54": (("sector", "Textiles"),), "55": (("sector", "Textiles"),),
    "56": (("sector", "Textiles"),), "57": (("sector", "Textiles"),),
    "58": (("sector", "Textiles"),), "59": (("sector", "Textiles"),),
    "60": (("sector", "Textiles"),),
    "61": (("basic_industry", "Garments & Apparels"),),
    "62": (("basic_industry", "Garments & Apparels"),),
    "63": (("basic_industry", "Other Textile Products"),),
    "64": (("basic_industry", "Footwear"),),
    "69": (("basic_industry", "Ceramics"),),
    "70": (("basic_industry", "Glass - Industrial"),),
    "71": (("basic_industry", "Gems Jewellery And Watches"),
           ("basic_industry", "Precious Metals")),
    "72": (("basic_industry", "Iron & Steel Products"),),
    "73": (("basic_industry", "Iron & Steel Products"),),
    "74": (("basic_industry", "Copper"),),
    "76": (("basic_industry", "Aluminium"),),
    "79": (("basic_industry", "Zinc"),),
    "84": (("basic_industry", "Industrial Products"),),
    "85": (("basic_industry", "Other Electrical Equipment"),),
    "87": (("sector", "Automobile and Auto Components"),),
    "94": (("basic_industry", "Furniture Home Furnishing"),),
}
HS_RE = re.compile(r"\b(?:hs|heading|chapter)\s*(?:no\.?\s*)?(\d{2})\d{0,6}\b", re.I)

# Themes are only emitted where a curated universe exists (universe_membership is not
# built in the live DB yet; the planner reports that instead of inventing members).
THEME_TERMS = {
    "data centres": "data_centres", "data centre": "data_centres",
    "data center": "data_centres", "data centers": "data_centres",
    "semiconductor": "semiconductors", "semiconductors": "semiconductors",
    "defence": "defence", "defense": "defence",
    "specialty chemicals": "specialty_chemicals",
    "speciality chemicals": "specialty_chemicals",
    "gold jewellery": "gold_jewellery_finance",
    "housing finance": "housing_finance", "dairy": "dairy",
    "oil marketing": "omc_refining", "textile export": "textiles_exporters",
}

STATE_NAMES = {"up": "Uttar Pradesh", "tn": "Tamil Nadu", "ap": "Andhra Pradesh",
               "mp": "Madhya Pradesh", "wb": "West Bengal", "hp": "Himachal Pradesh"}

_SUFFIX_RE = re.compile(r"\b(?:limited|ltd|corporation|corp|company|co|inc|plc|pvt|"
                        r"private)\b\.?\s*$", re.I)
_NAME_STOP = {"ltd", "limited", "india", "the", "and", "of", "bank", "finance",
              "company", "corporation", "services", "industries", "enterprises"}


def _clean(value: object) -> str:
    return " ".join(str(value or "").lower().replace("&", " and ").split())


def parse_list(raw: object) -> list[str]:
    """The JSON-ish list fields of policy_events -> list[str] (deterministic order)."""
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        text = str(raw or "").strip()
        if not text or text == "[]":
            return []
        try:
            items = json.loads(text)
        except (ValueError, TypeError):
            items = re.split(r"[,;|]", text)
        if not isinstance(items, list):
            items = [items]
    out = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned.lower() not in {"none", "null", "[]"} and cleaned not in out:
            out.append(cleaned)
    return out


def policy_type(row: dict) -> str:
    return POLICY_TYPE.get(_clean(row.get("instrument")), "other")


def claim_direction(row: dict) -> str:
    return TARGET_DIRECTION.get(_clean(row.get("direction_for_industry")), "neutral")


def iso_effective(raw: object) -> str | None:
    """Effective date as ISO (fiscal-year text -> the FY start, e.g. 2024-25 -> 2024-04-01)."""
    text = str(raw or "").strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4})-(\d{2})$", text)
    if m and int(m.group(2)) <= 12:
        return f"{m.group(1)}-{m.group(2)}-01"
    m = re.match(r"^(\d{4})\s*[-–]\s*(\d{2,4})$", text)
    if m:
        start, end = int(m.group(1)), m.group(2)
        end_num = int(end) % 100
        if (start % 100) + 1 == end_num:
            return f"{start}-04-01"  # Indian fiscal year -> its start
        return None
    return None


def magnitude(row: dict) -> tuple[float | None, str | None, str | None]:
    """(value, unit, raw) with the DDL's unit vocabulary; bps normalised to percent."""
    unit = _clean(row.get("unit"))
    amount = row.get("amount_inr_crore")
    raw_value = row.get("new_value")
    unit_map = {"": "INR_CRORE", "null": "INR_CRORE", "inr crore": "INR_CRORE",
                "inr crore per year": "INR_CRORE", "inr": "INR_CRORE",
                "inr lakh": "INR_LAKH", "%": "PERCENT", "percent": "PERCENT",
                "per cent": "PERCENT", "% of gsdp": "PERCENT",
                "% of gdp": "PERCENT", "basis points": "PERCENT", "bps": "PERCENT",
                "mw": "MW"}
    if amount is not None:
        value = float(amount)
        if unit in ("basis points", "bps"):
            value /= 100.0
        mapped = unit_map.get(unit)
        if mapped is None and "crore" in unit:
            mapped = "INR_CRORE"
        if mapped is None:  # a unit the DDL does not carry (INR/litre, years ...)
            return None, None, str(raw_value or amount)
        return value, mapped, str(raw_value or amount)
    text = f"{raw_value or ''} {row.get('quote') or ''}"
    # The extractor inserts spaces around decimal points ("6. 50 per cent"): rejoin them or
    # a level of 6.50 is read as a 50 per cent change.
    text = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", text)
    # bps first: a rate claim often prints "25 bps to 5.50 per cent" and the target
    # magnitude is the 25 bps the claim changes, not the level it lands on.
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:bps|basis\s+points?)", text, re.I)
    if m:
        return float(m.group(1)) / 100.0, "PERCENT", m.group(0).strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent)", text, re.I)
    if m:
        return float(m.group(1)), "PERCENT", m.group(0).strip()
    return None, None, None


_CONDITION_RE = re.compile(
    r"\b(provided that|except|unless|only if|subject to|eligib\w*|applicable to|"
    r"for those|shall not|in respect of|notwithstanding)\b", re.I)


def conditions(row: dict) -> str | None:
    """The quote's conditional clauses (the DDL has no conditions column; pilot-only)."""
    text = str(row.get("quote") or "")
    if not text:
        return None
    clauses = [part.strip() for part in re.split(r"(?<=[.;])\s+", text)
               if _CONDITION_RE.search(part)]
    return " ".join(clauses)[:400] or None


def paraphrase(row: dict, sectors: list[str]) -> str:
    """<= 30 words: name, instrument, direction, the sectors it names, magnitude if any."""
    value, unit, _ = magnitude(row)
    words = [str(row.get("policy_name") or row.get("title") or "policy claim").strip()]
    instrument = str(row.get("instrument") or "").replace("_", " ").strip()
    if instrument:
        words.append(f"({instrument}; {_clean(row.get('direction_for_industry')) or 'neutral'})")
    if sectors:
        words.append("hits " + ", ".join(sectors[:4]))
    if value is not None:
        shown = f"{value:,.2f}".rstrip("0").rstrip(".")
        label = {"INR_CRORE": "crore", "INR_LAKH": "lakh", "PERCENT": "%",
                 "MW": "MW"}.get(str(unit), str(unit or "").lower())
        words.append(f"at Rs {shown} {label}")
    return " ".join(" ".join(words).split()[:30])


def _norm_company(value: object) -> str:
    text = _clean(value)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = _SUFFIX_RE.sub("", " ".join(text.split()))
    return " ".join(text.split())


class CompanyIndex:
    """Exact symbol, exact normalised name, or company-name prefix — no substring match."""

    def __init__(self, rows: list[dict]):
        self.by_symbol: dict[str, str] = {}
        self.by_name: dict[str, str] = {}
        self.names: list[tuple[str, str]] = []
        for row in rows:
            isin = str(row.get("isin") or "")
            if not isin:
                continue
            symbol = str(row.get("nse_symbol") or "").strip().upper()
            if symbol and len(symbol) >= 2:
                self.by_symbol.setdefault(symbol, isin)
            name = _norm_company(row.get("company_name") or "")
            if name and len(name) >= 4:
                self.by_name.setdefault(name, isin)
                self.names.append((name, isin))

    def resolve(self, raw: str) -> str | None:
        text = str(raw or "").strip()
        if not text:
            return None
        symbol = text.upper()
        if len(symbol) >= 3 and symbol in self.by_symbol:
            return self.by_symbol[symbol]
        name = _norm_company(text)
        if not name or name in _NAME_STOP or len(name) < 5:
            return None
        if name in self.by_name:
            return self.by_name[name]
        prefix = name + " "
        hits = {isin for full, isin in self.names
                if full.startswith(prefix) and len(full) > len(prefix)}
        if len(hits) == 1:
            return hits.pop()
        if len(hits) > 1:
            # Several listed names share the prefix: ambiguous, so refuse it.
            return None
        return None


def _add(targets: list[tuple[str, str, str, str]], seen: set, kind: str, ident: str,
         direction: str, evidence: str) -> None:
    ident = str(ident or "").strip()
    if not ident or (kind, ident) in seen:
        return
    seen.add((kind, ident))
    targets.append((kind, ident, direction, evidence))


def _term_targets(term: str) -> tuple[tuple[tuple[str, str], ...], str | None]:
    """A sector term -> (targets, theme); compounds are matched on their parts.

    "Textiles & Apparel" splits on " and "; "rates-sensitive sectors (real estate,
    auto)" is matched on each part inside the parentheses too.
    """
    key = _clean(term)
    hit = SECTOR_TERMS.get(key)
    if hit:
        return hit, THEME_TERMS.get(key)
    parts: list[str] = []
    paren = re.match(r"^(.*?)\(([^)]*)\)\s*$", key)
    if paren:
        parts = [paren.group(1).strip(), *re.split(r"[,;/]", paren.group(2))]
    elif " and " in key:
        parts = key.split(" and ")
    if parts:
        merged: list[tuple[str, str]] = []
        theme = None
        for part in parts:
            sub, sub_theme = _term_targets(part)
            merged.extend(sub)
            theme = theme or sub_theme
        return tuple(merged), theme
    return (), None


def claim_targets(row: dict, companies: CompanyIndex,
                  doc_source: str = "") -> list[tuple[str, str, str, str]]:
    """(target_kind, target_id, direction, evidence) from the claim's own fields."""
    direction = claim_direction(row)
    targets: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    for term in parse_list(row.get("sectors")):
        hit, theme = _term_targets(term)
        for kind, ident in hit:
            _add(targets, seen, kind, ident, direction, f"sector term '{term}'")
        if theme:
            _add(targets, seen, "theme", theme, direction, f"theme term '{term}'")

    if policy_type(row) in {"tariff", "tax"}:
        # Product names come from the claim's own product/policy fields: a comparison in
        # the surrounding quote ("railway MROs to benefit similar to aircraft MROs") is not
        # a product the claim changes.  HS codes are unambiguous wherever they appear.
        text = _clean(" ".join(str(row.get(k) or "") for k in ("products", "policy_name")))
        for term, hit in PRODUCT_TERMS.items():
            if re.search(r"\b" + re.escape(term) + r"\b", text):
                for kind, ident in hit:
                    _add(targets, seen, kind, ident, direction, f"product term '{term}'")
        hs_text = _clean(" ".join(str(row.get(k) or "") for k in
                                  ("products", "policy_name", "quote", "new_value")))
        for chapter in HS_RE.findall(hs_text):
            for kind, ident in HS_CHAPTERS.get(chapter, ()):
                _add(targets, seen, kind, ident, direction, f"HS chapter {chapter}")

    for name in parse_list(row.get("companies")):
        isin = companies.resolve(name)
        if isin:
            _add(targets, seen, "isin", isin, direction, f"named company '{name}'")

    state = _state_of(doc_source)
    if state:
        _add(targets, seen, "state", state, "neutral", f"state budget {state}")
    return targets


def _state_of(source_type: str) -> str | None:
    text = str(source_type or "")
    m = re.match(r"^State_Budget_([A-Za-z_]+)$", text)
    if not m:
        return None
    slug = m.group(1)
    return STATE_NAMES.get(slug.lower(), slug.replace("_", " ").title())


# --- source read + strata -----------------------------------------------------------
DOC_TYPE = {
    "Union_Budget": "union_budget", "Economic_Survey": "economic_survey",
    "PIB_Press_Release": "pib",
}


def _doc_type(source_type: str, source_kind: str) -> str:
    text = str(source_type or "")
    if text in DOC_TYPE:
        return DOC_TYPE[text]
    if text.startswith("State_Budget"):
        return "state_budget"
    if text.startswith("RBI_Annual_Report") or text.startswith("RBI_Strategy"):
        return "rbi_report"
    if text.startswith("RBI"):
        return "rbi_policy"
    if text.startswith("PIB") or source_kind == "pib":
        return "pib"
    return "news"


def _stratum(source_type: str, source_kind: str, instrument: str) -> str:
    text = str(source_type or "")
    if text.startswith("Union_Budget"):
        return "budget"
    if text.startswith(("RBI_Monetary_Policy", "RBI_MPC_Minutes")):
        return "rbi"
    # A standalone customs/tariff notice; a budget speech line, a central-bank report or
    # an Economic Survey paragraph that merely mentions a duty stays in its own stratum.
    if _clean(instrument) in {"customs_duty", "tariff_trade"} and not text.startswith(
            ("Economic_Survey", "RBI_", "State_Budget")):
        return "tariff"
    if text.startswith("PIB") or source_kind == "pib":
        return "pib"
    if text.startswith("State_Budget"):
        return "state_budget"
    return "other"


def read_source(ei_path: Path) -> dict[str, list[dict]]:
    con = connect_ro(ei_path, timeout_s=120)
    con.row_factory = sqlite3.Row
    try:
        docs = {int(r["doc_id"]): dict(r) for r in con.execute(
            "SELECT doc_id, title, source_type, creator_or_ministry, published_date "
            "FROM raw_documents")}
        ministries = {}
        try:
            ministries = {int(r["prid"]): str(r["ministry"] or "") for r in con.execute(
                "SELECT prid, ministry FROM pib_releases")}
        except sqlite3.DatabaseError:
            pass
        claims = [dict(r) for r in con.execute(
            "SELECT id, source_kind, source_id, section, published_at, title, policy_name, "
            "instrument, direction_for_industry, sectors, companies, products, "
            "amount_inr_crore, unit, new_value, old_value, effective_date, end_date, quote "
            "FROM policy_events WHERE quote_ok=1 ORDER BY id")]
        companies = [dict(r) for r in con.execute(
            "SELECT isin, nse_symbol, company_name FROM master_companies "
            "WHERE isin IS NOT NULL AND isin <> ''")]
    finally:
        con.close()
    return {"docs": docs, "ministries": ministries, "claims": claims, "companies": companies}


def _pick_even(rows: list[dict], k: int) -> list[dict]:
    if k <= 0 or not rows:
        return []
    if k >= len(rows):
        return list(rows)
    if k == 1:
        return [rows[len(rows) // 2]]
    return [rows[round(i * (len(rows) - 1) / (k - 1))] for i in range(k)]


def _round_robin(groups: list[list[dict]], k: int) -> list[dict]:
    out: list[dict] = []
    cursor = [0] * len(groups)
    while len(out) < k:
        progressed = False
        for index, group in enumerate(groups):
            if cursor[index] < len(group) and len(out) < k:
                out.append(group[cursor[index]])
                cursor[index] += 1
                progressed = True
        if not progressed:
            break
    return out


def _year_quota(groups: dict[str, list[dict]], total: int) -> dict[str, int]:
    """Split a stratum's quota across its published years, remainder to the earliest."""
    years = sorted(groups)
    if not years or total <= 0:
        return {year: 0 for year in years}
    base, extra = divmod(total, len(years))
    return {year: base + (1 if index < extra else 0) for index, year in enumerate(years)}


def _stratum_targets(available: dict[str, int], quota: dict[str, int],
                     total: int | None = None) -> dict[str, int]:
    """Per-stratum claim counts: quota clamped to what the source holds, then the
    leftover handed out one at a time so a thin stratum cannot claim a full quota."""
    keys = ("budget", "rbi", "pib", "tariff")
    target = {key: min(int(quota.get(key, 0)), available.get(key, 0)) for key in keys}
    limit = sum(int(value) for value in quota.values()) if total is None else int(total)
    total = min(limit, sum(available.values()))
    order = ("budget", "pib", "rbi", "tariff")
    while sum(target.values()) < total:
        progressed = False
        for key in order:
            if sum(target.values()) >= total:
                break
            if target[key] < available.get(key, 0):
                target[key] += 1
                progressed = True
        if not progressed:
            break
    while sum(target.values()) > total:  # anchors already used up part of the quota
        reduced = False
        for key in reversed(order):
            if sum(target.values()) <= total:
                break
            if target[key] > 0:
                target[key] -= 1
                reduced = True
        if not reduced:
            break
    return target


def anchor_ids() -> set[int]:
    """policy_events ids the ripple200 master bank names in its own templates."""
    path = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
    found: set[int] = set()
    if not path.exists():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("source_bank") != "ripple200":
            continue
        text = str(row.get("template") or "")
        found.update(int(match) for match in re.findall(r"policy_events\.id=(\d+)", text))
    return found


def select_claims(claims: list[dict], docs: dict[int, dict],
                  quota: dict[str, int] | None = None,
                  ministries: dict[int, str] | None = None,
                  anchors: set[int] | None = None) -> tuple[list[dict], dict]:
    """Deterministic stratified pick; returns rows plus the per-stratum count map.

    ``anchors`` are claim ids the ripple bank itself names: they are always kept
    (the pilot exists to unblock those cases) and the quotas fill the rest.
    """
    quota = dict(quota or QUOTA)
    ministries = ministries if ministries is not None else _MINISTRIES
    anchors = set(anchors or ())
    claims = [row for row in claims
              if str(row.get("published_at") or "")[:4] >= "2024"]
    buckets: dict[str, list[dict]] = {}
    anchor_rows: list[dict] = []
    for row in claims:
        source = docs.get(int(row.get("source_id") or 0), {}) if row.get("source_kind") == "doc" \
            else {}
        source_type = str(source.get("source_type") or "")
        row = dict(row)
        row["_source_type"] = source_type
        row["_stratum"] = _stratum(source_type, str(row.get("source_kind") or ""),
                                   str(row.get("instrument") or ""))
        if int(row.get("id") or 0) in anchors:
            anchor_rows.append(row)
        else:
            buckets.setdefault(row["_stratum"], []).append(row)

    picked: list[dict] = []
    counts: dict[str, int] = {}

    budget_by_year: dict[str, list[dict]] = {}
    for row in buckets.get("budget", []):
        year = str(row.get("published_at") or "")[:4]
        if year in {"2024", "2025", "2026"}:
            budget_by_year.setdefault(year, []).append(row)
    rbi_rows = buckets.get("rbi", [])
    minutes = [r for r in rbi_rows if str(r.get("title") or "").startswith("RBI_MPC_Minutes")]
    statements = [r for r in rbi_rows if r not in minutes]
    pib_rows = buckets.get("pib", [])
    tariff_by_year: dict[str, list[dict]] = {}
    for row in buckets.get("tariff", []):
        year = str(row.get("published_at") or "")[:4]
        if year in {"2024", "2025", "2026"}:
            tariff_by_year.setdefault(year, []).append(row)

    available = {"budget": sum(len(rows) for rows in budget_by_year.values()),
                 "rbi": len(statements) + len(minutes),
                 "pib": len(pib_rows),
                 "tariff": sum(len(rows) for rows in tariff_by_year.values())}
    target = _stratum_targets(available, quota,
                              total=sum(int(value) for value in quota.values()) - len(anchor_rows))
    picked += anchor_rows
    counts["anchor"] = len(anchor_rows)

    budget_pick: list[dict] = []
    budget_quota = _year_quota(budget_by_year, target["budget"])
    for year in sorted(budget_by_year):
        budget_pick += _pick_even(budget_by_year[year], budget_quota[year])
    counts["budget"] = len(budget_pick)
    picked += budget_pick

    minutes_target = target["rbi"] * 2 // 5
    rbi_pick = (_pick_even(statements, target["rbi"] - minutes_target)
                + _pick_even(minutes, minutes_target))
    counts["rbi"] = len(rbi_pick)
    picked += rbi_pick

    pib_groups: dict[str, list[dict]] = {}
    for row in pib_rows:
        ministry = ""
        if row.get("source_kind") == "pib":
            ministry = str(ministries.get(int(row.get("source_id") or 0), "") or "")
        pib_groups.setdefault(ministry or "unattributed", []).append(row)
    ordered = [pib_groups[key] for key in
               sorted(pib_groups, key=lambda k: (-len(pib_groups[k]), k))]
    pib_pick = _round_robin(ordered, target["pib"])
    counts["pib"] = len(pib_pick)
    picked += pib_pick

    tariff_pick: list[dict] = []
    tariff_quota = _year_quota(tariff_by_year, target["tariff"])
    for year in sorted(tariff_by_year):
        tariff_pick += _pick_even(tariff_by_year[year], tariff_quota[year])
    counts["tariff"] = len(tariff_pick)
    picked += tariff_pick

    shortfall = sum(target.values()) - len(picked)
    if shortfall > 0:  # a thin stratum: fill from the state-budget/other pools, evenly
        used = {row.get("id") for row in picked}
        rest = [row for row in claims if row.get("id") not in used]
        extra = _pick_even(sorted(rest, key=lambda r: r.get("id")), shortfall)
        for row in extra:
            row = dict(row)
            source = docs.get(int(row.get("source_id") or 0), {}) \
                if row.get("source_kind") == "doc" else {}
            row["_source_type"] = str(source.get("source_type") or "")
            row["_stratum"] = _stratum(row["_source_type"], str(row.get("source_kind") or ""),
                                       str(row.get("instrument") or ""))
            picked.append(row)

    counts = {"anchor": len(anchor_rows)}
    for row in picked:
        if int(row.get("id") or 0) in anchors:
            continue
        stratum = str(row.get("_stratum") or "other")
        counts[stratum] = counts.get(stratum, 0) + 1
    picked.sort(key=lambda r: int(r.get("id") or 0))
    return picked, counts


_MINISTRIES: dict[int, str] = {}


def build(out: Path, ei_path: Path | None = None, quota: dict[str, int] | None = None,
          anchors: set[int] | None = None, write: bool = True) -> dict:
    """Build the pilot from held data. Returns the build summary (also written as JSON)."""
    global _MINISTRIES
    ei_path = Path(ei_path or EI)
    source = read_source(ei_path)
    _MINISTRIES = source["ministries"]
    companies = CompanyIndex(source["companies"])
    docs = source["docs"]
    picked, counts = select_claims(source["claims"], docs, quota, source["ministries"], anchors)

    out = Path(out)
    path = out / DB_NAME
    if path.exists():
        resolved = path.resolve()
        if REPO not in resolved.parents and resolved.parent != REPO:
            raise RuntimeError(f"refusing to overwrite outside the worktree: {resolved}")
        path.unlink()
    out.mkdir(parents=True, exist_ok=True)

    doc_rows: dict[str, tuple] = {}
    claim_rows: list[tuple] = []
    target_rows: list[tuple] = []
    target_kinds: dict[str, int] = {}
    for row in picked:
        source_kind = str(row.get("source_kind") or "")
        doc_id = f"{source_kind}:{row.get('source_id')}" if source_kind == "pib" \
            else f"doc:{row.get('source_id')}"
        meta = docs.get(int(row.get("source_id") or 0), {}) if source_kind == "doc" else {}
        source_type = str(meta.get("source_type") or "")
        known_at = str(row.get("published_at") or meta.get("published_date") or "")
        issuer = str(meta.get("creator_or_ministry") or "") or \
            str(_MINISTRIES.get(int(row.get("source_id") or 0), "") or "")
        title = str(meta.get("title") or "") or str(row.get("title") or "").split(":")[-1].strip()
        doc_rows[doc_id] = (
            doc_id, source_type or ("PIB_Press_Release" if source_kind == "pib" else source_kind),
            _doc_type(source_type, source_kind), issuer or None, title or None,
            str(meta.get("published_date") or known_at)[:10] or None,
            known_at[:19], 1.0, "en")
        sectors = parse_list(row.get("sectors"))
        value, unit, raw = magnitude(row)
        targets = claim_targets(row, companies, source_type)
        claim_rows.append((
            int(row["id"]), doc_id, str(row.get("section") or "") or None,
            policy_type(row), str(row.get("instrument") or "") or None, claim_direction(row),
            value, unit, raw, iso_effective(row.get("effective_date")),
            iso_effective(row.get("end_date")), str(row.get("quote") or "")
            or str(row.get("policy_name") or ""), None, None,
            "deterministic_kw_v1", 1.0 if targets else 0.3, 0,
            paraphrase(row, sectors), known_at[:19],
            str(row.get("_stratum") or "other"), conditions(row)))
        for kind, ident, direction, evidence in targets:
            target_rows.append((int(row["id"]), kind, ident, direction, 1.0, evidence))
            target_kinds[kind] = target_kinds.get(kind, 0) + 1

    if write:
        con = sqlite3.connect(path)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            create_schema(con, KEEP)
            con.execute("ALTER TABLE macro_claim ADD COLUMN paraphrase TEXT")
            con.execute("ALTER TABLE macro_claim ADD COLUMN known_at TEXT")
            con.execute("ALTER TABLE macro_claim ADD COLUMN stratum TEXT")
            con.execute("ALTER TABLE macro_claim ADD COLUMN conditions TEXT")
            con.executemany(
                "INSERT INTO macro_doc (doc_id, source, doc_type, issuer, title, event_date, "
                "known_at, pit_conf, language) VALUES (?,?,?,?,?,?,?,?,?)", doc_rows.values())
            con.executemany(
                "INSERT INTO macro_claim (claim_id, doc_id, clause_no, policy_type, instrument, "
                "direction, magnitude_value, magnitude_unit, magnitude_raw, effective_date, "
                "end_date, quote, char_start, char_end, model, confidence, verified, "
                "paraphrase, known_at, stratum, conditions) VALUES (" + ",".join("?" * 21) + ")",
                claim_rows)
            con.executemany(
                "INSERT INTO macro_claim_target (claim_id, target_kind, target_id, direction, "
                "weight, evidence) VALUES (?,?,?,?,?,?)", target_rows)
            con.commit()
        finally:
            con.close()

    summary = {
        "db": str(path), "claims": len(claim_rows), "docs": len(doc_rows),
        "targets": len(target_rows), "target_kinds": target_kinds,
        "by_stratum": counts,
        "by_source": _count_sources(picked, docs),
        "claims_without_target": sum(1 for r in claim_rows if r[15] == 0.3),
    }
    if write:
        (out / "macro_pilot_meta.json").write_text(
            json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8")
    return summary


def _count_sources(picked: list[dict], docs: dict[int, dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in picked:
        meta = docs.get(int(row.get("source_id") or 0), {}) if row.get("source_kind") == "doc" \
            else {}
        source = str(meta.get("source_type") or row.get("source_kind") or "unknown")
        out[source] = out.get(source, 0) + 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / ".tmp" / "pilot"))
    ap.add_argument("--quota", type=int, default=300,
                    help="total claims (default 300; strata keep their proportions)")
    ap.add_argument("--ei", default=str(EI), help="live equity_intelligence.db (read-only)")
    a = ap.parse_args(argv)
    quota = None
    if a.quota != 300:
        scale = a.quota / sum(QUOTA.values())
        quota = {key: max(1, round(value * scale)) for key, value in QUOTA.items()}
    anchors = anchor_ids() if a.quota == 300 else set()
    summary = build(Path(a.out), Path(a.ei), quota, anchors)
    summary["anchors"] = len(anchors)
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
