"""Structured, queryable company-parameter distillation store."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field
except ImportError:  # Keep the local-first engine usable in minimal deployments.
    class BaseModel:
        def __init__(self, **values):
            annotations = getattr(self.__class__, "__annotations__", {})
            for key in annotations:
                default = getattr(self.__class__, key, None)
                if callable(default):
                    default = default()
                setattr(self, key, values.get(key, default))

        def model_dump(self):
            return dict(self.__dict__)

        def dict(self):
            return self.model_dump()

    def Field(default_factory=None, default=None, **_kwargs):
        return default_factory if default_factory is not None else default

from reality_engine.db.database import db_manager


class CyclicalityProfile(BaseModel):
    is_cyclical: bool = False
    cyclicality_type: Optional[str] = None
    cycle_duration_years: Optional[float] = None
    cycle_current_stage: Optional[str] = None
    key_revenue_drivers: List[str] = Field(default_factory=list)
    margin_sensitivities: Dict[str, float] = Field(default_factory=dict)
    stage_conviction: Optional[float] = None
    stage_rationale: Optional[str] = None


class BusinessSensitivities(BaseModel):
    key_revenue_drivers: List[str] = Field(default_factory=list)
    raw_material_sensitivities: Dict[str, float] = Field(default_factory=dict)
    pricing_power_assessment: Optional[str] = None
    moat_rating: Optional[float] = None


class GeopoliticalSupplyChain(BaseModel):
    geographic_revenue_split: Dict[str, float] = Field(default_factory=dict)
    supply_chain_dependencies: List[str] = Field(default_factory=list)
    macro_geopolitical_sensitivities: List[str] = Field(default_factory=list)
    transit_route_risks: List[str] = Field(default_factory=list)


class CapitalAllocation(BaseModel):
    in_progress_capex_inr_cr: Optional[float] = None
    expected_commercialization_quarter: Optional[str] = None
    deleveraging_trend: Optional[str] = None


class OrderBookMetrics(BaseModel):
    executable_order_book_inr_cr: Optional[float] = None
    ttm_revenue_inr_cr: Optional[float] = None
    order_book_to_bill_ratio: Optional[float] = None
    execution_visibility_years: Optional[float] = None


class DistillationEngine:
    DEFINITIONS = [
        ("cyclicality_profile", "Cyclicality Profile", "JSON", "Revenue and margin cycle profile.", "CYCLICALITY"),
        ("business_sensitivities", "Business Sensitivities", "JSON", "Revenue drivers, raw materials, pricing power, and moat.", "BUSINESS_MODEL"),
        ("geopolitical_supply_chain", "Geopolitical Supply Chain", "JSON", "Geographic exposure and supply-chain risks.", "MACRO"),
        ("capital_allocation", "Capital Allocation", "JSON", "Capex and deleveraging trajectory.", "CAPITAL_ALLOCATION"),
        ("order_book_metrics", "Order Book Metrics", "JSON", "Executable order book and visibility metrics.", "BUSINESS_MODEL"),
    ]

    def __init__(self, manager=None):
        self.db = manager or db_manager

    def seed_ontology_definitions(self) -> int:
        with self.db.session() as conn:
            conn.executemany(
                """INSERT INTO dynamic_parameter_definitions
                   (parameter_key, display_name, data_type, description, category)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(parameter_key) DO UPDATE SET display_name=excluded.display_name,
                   data_type=excluded.data_type, description=excluded.description, category=excluded.category""",
                self.DEFINITIONS,
            )
            return len(self.DEFINITIONS)

    def upsert_parameter(self, isin: str, symbol: str, parameter_key: str,
                         value: Any, confidence_score: float = 1.0,
                         source_document_ref: Optional[str] = None,
                         last_updated_date: Optional[str] = None) -> int:
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        elif hasattr(value, "dict"):
            value = value.dict()
        payload = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        with self.db.session() as conn:
            return conn.execute(
                """INSERT INTO company_distilled_parameters
                   (isin, symbol, parameter_key, value_json, confidence_score,
                    source_document_ref, last_updated_date) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(isin, parameter_key) DO UPDATE SET symbol=excluded.symbol,
                   value_json=excluded.value_json, confidence_score=excluded.confidence_score,
                   source_document_ref=excluded.source_document_ref,
                   last_updated_date=excluded.last_updated_date""",
                (isin, symbol, parameter_key, payload, confidence_score,
                 source_document_ref, last_updated_date or date.today().isoformat()),
            ).rowcount

    def query_parameters(self, symbol: str, parameter_key: Optional[str] = None,
                          json_path: Optional[str] = None, expected: Any = None) -> List[Dict[str, Any]]:
        sql = "SELECT *, json_extract(value_json, ?) AS extracted_value FROM company_distilled_parameters WHERE symbol = ?"
        params: List[Any] = [json_path or '$', symbol]
        if parameter_key:
            sql += " AND parameter_key = ?"
            params.append(parameter_key)
        if json_path and expected is not None:
            sql += " AND json_extract(value_json, ?) = ?"
            params.extend([json_path, expected])
        sql += " ORDER BY parameter_key"
        with self.db.session() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def get_distilled_parameters(self, symbol: str, parameter_key: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self.query_parameters(symbol, parameter_key)
        for row in rows:
            try:
                row["value"] = json.loads(row["value_json"])
            except (TypeError, json.JSONDecodeError):
                row["value"] = row["value_json"]
        return rows

    def seed_canonical_company_parameters(self) -> Dict[str, int]:
        """Seeds canonical distilled parameters and concall transcript snippets."""
        self.seed_ontology_definitions()
        
        canonical_data = [
            {
                "symbol": "HAL",
                "isin": "INE066F01020",
                "parameters": {
                    "cyclicality_profile": {
                        "is_cyclical": False,
                        "cyclicality_type": "Structural Defence Capex / Monopolistic",
                        "cycle_duration_years": 10.0,
                        "cycle_current_stage": "Accelerated Execution Phase",
                        "key_revenue_drivers": ["LCA Tejas Mk1A / Mk2 deliveries", "Su-30MKI upgrade programme", "Helicopters (ALH / LCH / LUH)", "MRO & Engine Overhaul"],
                        "margin_sensitivities": {"Raw Materials (Titanium/Alloys)": 0.15, "Avionics Import Duties": 0.10},
                        "stage_conviction": 0.95,
                        "stage_rationale": "Strong multi-year order book of Rs 1.24 Lakh Cr driven by MoD indigenization policy."
                    },
                    "business_sensitivities": {
                        "key_revenue_drivers": ["Defence Indigenization DAP 2020", "Export orders to friendly nations", "Private aerospace supplier integration"],
                        "raw_material_sensitivities": {"Titanium aero-structures": 0.12, "Advanced avionics sensors": 0.22, "Gas turbine raw components": 0.18},
                        "pricing_power_assessment": "Monopolistic cost-plus pricing with guaranteed operating margins on sovereign contracts",
                        "moat_rating": 9.5
                    },
                    "order_book_metrics": {
                        "executable_order_book_inr_cr": 124000.0,
                        "ttm_revenue_inr_cr": 29810.0,
                        "order_book_to_bill_ratio": 4.16,
                        "execution_visibility_years": 4.2
                    },
                    "capital_allocation": {
                        "in_progress_capex_inr_cr": 3500.0,
                        "expected_commercialization_quarter": "FY27Q1",
                        "deleveraging_trend": "Zero Debt / Net Cash Surplus (>Rs 20,000 Cr)"
                    },
                    "geopolitical_supply_chain": {
                        "geographic_revenue_split": {"Indian Armed Forces (MoD)": 98.2, "Friendly Foreign Exports": 1.8},
                        "supply_chain_dependencies": ["GE F404/F414 Turbofan Engines (USA)", "Russian RD-33 / AL-31FP spares"],
                        "macro_geopolitical_sensitivities": ["US-India Defence Trade initiative", "Indigenization DAP timeline enforcement"],
                        "transit_route_risks": ["Low ocean freight dependency, strategic airlift for critical parts"]
                    }
                },
                "concall_snippets": [
                    "Management Q1 FY27 Guidance: Defence Acquisition Council has cleared additional procurement worth INR 45,000 Cr for Su-30 MKI upgrades and LCA Tejas Mk1A. Operating margin expected to stay resilient at 28-30% on expanding indigenization and robust MRO revenue mix.",
                    "Order book stands at all-time high of INR 1,24,000 Cr providing revenue visibility for next 4+ years. Nashik and Bengaluru manufacturing lines operating at maximum capacity utilization."
                ]
            },
            {
                "symbol": "TITAGARH",
                "isin": "INE615H01020",
                "parameters": {
                    "cyclicality_profile": {
                        "is_cyclical": True,
                        "cyclicality_type": "Capex-Linked / Rail Infrastructure Modernization Cycle",
                        "cycle_duration_years": 7.0,
                        "cycle_current_stage": "Early-to-Mid Capex Expansion",
                        "key_revenue_drivers": ["Vande Bharat sleeper trainsets", "Wagon procurement tenders", "Metro coach rolling stock", "Propulsion systems"],
                        "margin_sensitivities": {"Special Grade Steel": 0.40, "Forged Wheelsets": 0.20},
                        "stage_conviction": 0.90,
                        "stage_rationale": "Massive Indian Railways wagon modernization & Vande Bharat contract pipeline."
                    },
                    "business_sensitivities": {
                        "key_revenue_drivers": ["Union Budget Rail Capex", "BHEL-Titagarh consortium execution", "Metro rail expansion"],
                        "raw_material_sensitivities": {"Heavy structural steel": 0.35, "Wheelsets & Axles": 0.18, "Electrical propulsion kits": 0.15},
                        "pricing_power_assessment": "Moderate-to-Strong via technical consortium barrier and pre-qualification criteria",
                        "moat_rating": 8.0
                    },
                    "order_book_metrics": {
                        "executable_order_book_inr_cr": 28000.0,
                        "ttm_revenue_inr_cr": 3850.0,
                        "order_book_to_bill_ratio": 7.27,
                        "execution_visibility_years": 5.0
                    },
                    "capital_allocation": {
                        "in_progress_capex_inr_cr": 1000.0,
                        "expected_commercialization_quarter": "FY26Q4",
                        "deleveraging_trend": "Working capital optimized, low debt-to-equity ratio"
                    },
                    "geopolitical_supply_chain": {
                        "geographic_revenue_split": {"Indian Railways & Metro Rail": 92.0, "European / Global Rail": 8.0},
                        "supply_chain_dependencies": ["Titagarh Firema Italian engineering technology transfer", "Wheelset imports"],
                        "macro_geopolitical_sensitivities": ["Domestic content mandate under Make in India"],
                        "transit_route_risks": ["Domestic rail freight corridors minimize sea freight disruption"]
                    }
                },
                "concall_snippets": [
                    "Management Concall: Titagarh Rail Systems confirmed delivery ramp-up of Vande Bharat sleeper trainsets starting Q4. Wagon delivery run-rate has reached 1,000+ units per month.",
                    "Joint venture with Ramkrishna Forgings for wheelset manufacturing will completely de-risk import reliance from Europe and expand consolidated EBITDA margins by 150-200 bps."
                ]
            },
            {
                "symbol": "KAYNES",
                "isin": "INE918Z01012",
                "parameters": {
                    "cyclicality_profile": {
                        "is_cyclical": False,
                        "cyclicality_type": "Secular Electronics Manufacturing Services (EMS) Supercycle",
                        "cycle_duration_years": 8.0,
                        "cycle_current_stage": "High Growth Acceleration",
                        "key_revenue_drivers": ["Railway signalling & safety EMS", "Automotive & EV electronics", "Industrial IoT & Aerospace", "OSAT Semiconductor packaging"],
                        "margin_sensitivities": {"Semiconductor components": 0.45, "PCB substrates": 0.20},
                        "stage_conviction": 0.92,
                        "stage_rationale": "High-margin box-build mix expansion and OSAT facility commissioning."
                    },
                    "business_sensitivities": {
                        "key_revenue_drivers": ["India Semiconductor Mission PLI", "Rail Kavach anti-collision deployment", "Smart meter rollout"],
                        "raw_material_sensitivities": {"Active semiconductor components": 0.40, "Passive electronic components": 0.20, "Printed circuit boards": 0.15},
                        "pricing_power_assessment": "High value-added ODM and box-build engineering contracts with client stickiness",
                        "moat_rating": 8.5
                    },
                    "order_book_metrics": {
                        "executable_order_book_inr_cr": 5050.0,
                        "ttm_revenue_inr_cr": 1805.0,
                        "order_book_to_bill_ratio": 2.80,
                        "execution_visibility_years": 2.8
                    },
                    "capital_allocation": {
                        "in_progress_capex_inr_cr": 2800.0,
                        "expected_commercialization_quarter": "FY27Q2",
                        "deleveraging_trend": "Zero Debt / Net Cash Surplus following QIP capital raise"
                    },
                    "geopolitical_supply_chain": {
                        "geographic_revenue_split": {"India Domestic": 82.0, "Export (North America & Europe)": 18.0},
                        "supply_chain_dependencies": ["Taiwan & Korea semiconductor fab supply", "Japan passive components"],
                        "macro_geopolitical_sensitivities": ["Global semiconductor supply chain stability", "PLI incentive disbursements"],
                        "transit_route_risks": ["Air cargo reliance for microchip imports"]
                    }
                },
                "concall_snippets": [
                    "Q1 Management Remarks: Order book crossed INR 5,000 Cr mark led by robust inflows from Indian Railways Kavach deployment and industrial IoT clients. Target 40%+ YoY revenue growth in FY27.",
                    "OSAT semiconductor packaging plant in Sanand, Gujarat is on track for trial production by early FY27, which will significantly expand gross margins to above 32%."
                ]
            },
            {
                "symbol": "PIDILITIND",
                "isin": "INE318A01026",
                "parameters": {
                    "cyclicality_profile": {
                        "is_cyclical": False,
                        "cyclicality_type": "Defensive / Structural Consumer & Specialty Chemical",
                        "cycle_duration_years": 12.0,
                        "cycle_current_stage": "Steady Compounding Expansion",
                        "key_revenue_drivers": ["Fevicol retail adhesives", "Dr. Fixit waterproofing", "Fevikwik instant bonding", "Industrial resins"],
                        "margin_sensitivities": {"Vinyl Acetate Monomer (VAM)": 0.35, "Packaging crude derivatives": 0.15},
                        "stage_conviction": 0.95,
                        "stage_rationale": "Dominant retail distribution network with unassailable 70%+ brand market share."
                    },
                    "business_sensitivities": {
                        "key_revenue_drivers": ["Home improvement & renovation demand", "Real estate construction cycle", "Tier-2/4 rural penetration"],
                        "raw_material_sensitivities": {"Vinyl Acetate Monomer (VAM) global spot prices": 0.35, "Polymer emulsions": 0.18},
                        "pricing_power_assessment": "Extreme pricing power; able to pass through input cost hikes without volume destruction",
                        "moat_rating": 9.5
                    },
                    "order_book_metrics": {
                        "executable_order_book_inr_cr": None,
                        "ttm_revenue_inr_cr": 12450.0,
                        "order_book_to_bill_ratio": None,
                        "execution_visibility_years": None
                    },
                    "capital_allocation": {
                        "in_progress_capex_inr_cr": 850.0,
                        "expected_commercialization_quarter": "FY26Q3",
                        "deleveraging_trend": "Virtually Debt Free / Return on Capital Employed > 28%"
                    },
                    "geopolitical_supply_chain": {
                        "geographic_revenue_split": {"India Domestic": 88.0, "International Subsidiaries": 12.0},
                        "supply_chain_dependencies": ["Global VAM producers (US, China, Saudi Arabia)"],
                        "macro_geopolitical_sensitivities": ["Crude oil pricing & chemical feedstock freight"],
                        "transit_route_risks": ["Container freight rates for raw monomer imports"]
                    }
                },
                "concall_snippets": [
                    "Earnings Concall: Pidilite delivered strong double-digit volume growth in consumer and bazaar segment. VAM prices remained benign in $800-900/MT range, supporting 22%+ EBITDA margins.",
                    "Expansion into decorative paints and tile adhesives under Roff and Puma brands continues to gain market share in Tier-2 and Tier-3 cities."
                ]
            },
            {
                "symbol": "RELIANCE",
                "isin": "INE002A01018",
                "parameters": {
                    "cyclicality_profile": {
                        "is_cyclical": True,
                        "cyclicality_type": "Diversified Conglomerate (O2C Cyclical + Retail & Telecom Secular)",
                        "cycle_duration_years": 8.0,
                        "cycle_current_stage": "New Energy & Retail Capex Monetization",
                        "key_revenue_drivers": ["Jio 5G telecom ARPU growth", "Reliance Retail footprint expansion", "O2C refining & petrochemicals", "Solar & Green Hydrogen gigafactories"],
                        "margin_sensitivities": {"Singapore Gross Refining Margin (GRM)": 0.30, "Petchem polymer deltas": 0.20},
                        "stage_conviction": 0.88,
                        "stage_rationale": "Digital & consumer retail cash flows cushioning global refining margin fluctuations."
                    },
                    "business_sensitivities": {
                        "key_revenue_drivers": ["Telecom subscriber addition & tariff hikes", "Consumer retail grocery & apparel expansion", "Global crude refining spreads"],
                        "raw_material_sensitivities": {"Crude Oil spot benchmarks (Brent/Dubai)": 0.50, "Telecom spectrum & network capex": 0.20},
                        "pricing_power_assessment": "High pricing power in digital telecom duopoly and offline retail leadership",
                        "moat_rating": 9.0
                    },
                    "order_book_metrics": {
                        "executable_order_book_inr_cr": None,
                        "ttm_revenue_inr_cr": 925000.0,
                        "order_book_to_bill_ratio": None,
                        "execution_visibility_years": None
                    },
                    "capital_allocation": {
                        "in_progress_capex_inr_cr": 75000.0,
                        "expected_commercialization_quarter": "FY26Q4",
                        "deleveraging_trend": "Targeting Net Debt zero across group entities via strong operating cash flows"
                    },
                    "geopolitical_supply_chain": {
                        "geographic_revenue_split": {"India Domestic": 68.0, "Global Refining & Petchem Exports": 32.0},
                        "supply_chain_dependencies": ["Middle East & Russian crude imports", "Global solar cell equipment suppliers"],
                        "macro_geopolitical_sensitivities": ["OPEC+ crude quotas", "Red Sea shipping lane security", "US Dollar exchange rate"],
                        "transit_route_risks": ["Supertanker VLCC routes across Strait of Hormuz and Arabian Sea"]
                    }
                },
                "concall_snippets": [
                    "Reliance Investor Presentation: Jio 5G monetisation on track with monthly ARPU rising past INR 195. Retail segment footfalls and square footage expanded by 18% YoY.",
                    "Jamnagar New Energy gigafactory for solar PV modules is entering phase-1 commissioning with captive clean power integration."
                ]
            },
            {
                "symbol": "ASIANPAINT",
                "isin": "INE021A01026",
                "parameters": {
                    "cyclicality_profile": {
                        "is_cyclical": False,
                        "cyclicality_type": "Consumer Decorative & Architectural Coatings",
                        "cycle_duration_years": 10.0,
                        "cycle_current_stage": "Competitive Resurgence & Margin Consolidation",
                        "key_revenue_drivers": ["Decorative paint volume growth", "Home decor & bath fittings", "Industrial coatings", "Waterproofing segment"],
                        "margin_sensitivities": {"Crude oil derivatives & Titanium Dioxide (TiO2)": 0.40, "Solvents & Phthalic Anhydride": 0.20},
                        "stage_conviction": 0.85,
                        "stage_rationale": "Unrivaled tinting machine network in 150,000+ retail dealerships across India."
                    },
                    "business_sensitivities": {
                        "key_revenue_drivers": ["Urbanization & repainting cycles", "Monsoon recovery & festive demand", "Industrial coatings uptake"],
                        "raw_material_sensitivities": {"Crude oil & petroleum derivatives": 0.35, "Titanium Dioxide (TiO2)": 0.20},
                        "pricing_power_assessment": "High historical pricing power with disciplined dealer network",
                        "moat_rating": 9.0
                    },
                    "order_book_metrics": {
                        "executable_order_book_inr_cr": None,
                        "ttm_revenue_inr_cr": 35400.0,
                        "order_book_to_bill_ratio": None,
                        "execution_visibility_years": None
                    },
                    "capital_allocation": {
                        "in_progress_capex_inr_cr": 2000.0,
                        "expected_commercialization_quarter": "FY26Q4",
                        "deleveraging_trend": "Zero Debt / ROCE > 32%"
                    },
                    "geopolitical_supply_chain": {
                        "geographic_revenue_split": {"India Domestic": 90.0, "International (Middle East, Asia)": 10.0},
                        "supply_chain_dependencies": ["Imported TiO2 suppliers", "Petrochemical solvent refineries"],
                        "macro_geopolitical_sensitivities": ["Crude oil fluctuations and Red Sea freight surcharges"],
                        "transit_route_risks": ["Raw chemical container shipping routes"]
                    }
                },
                "concall_snippets": [
                    "Q1 Earnings Call: Asian Paints reported 10% volume growth in decorative paints. Backward integration in VAE and White Spirits will structurally lower cost of goods sold.",
                    "Targeting double-digit EBITDA margin resilience even in volatile crude oil and TiO2 pricing environments."
                ]
            },
            {
                "symbol": "SCI",
                "isin": "INE109A01011",
                "parameters": {
                    "cyclicality_profile": {
                        "is_cyclical": True,
                        "cyclicality_type": "Global Freight & Tanker Shipping Cycle",
                        "cycle_duration_years": 5.0,
                        "cycle_current_stage": "Freight Rate Upcycle",
                        "key_revenue_drivers": ["Crude tanker charter rates", "Product tanker dayrates", "Dry bulk vessel chartering", "Offshore supply vessels"],
                        "margin_sensitivities": {"Bunker fuel oil": 0.35, "Global tanker charter rates": 0.50},
                        "stage_conviction": 0.86,
                        "stage_rationale": "Red Sea rerouting and longer ton-mile demand elevating global tanker dayrates."
                    },
                    "business_sensitivities": {
                        "key_revenue_drivers": ["Global crude shipping ton-mile demand", "Geopolitical rerouting around Cape of Good Hope", "PSU strategic cargo carriage"],
                        "raw_material_sensitivities": {"Very Low Sulfur Fuel Oil (VLSFO) bunker fuel": 0.35, "Vessel dry-docking and maintenance": 0.15},
                        "pricing_power_assessment": "Market rate taker indexed to Baltic Tanker and Dirty Tanker indices",
                        "moat_rating": 7.0
                    },
                    "order_book_metrics": {
                        "executable_order_book_inr_cr": None,
                        "ttm_revenue_inr_cr": 5400.0,
                        "order_book_to_bill_ratio": None,
                        "execution_visibility_years": None
                    },
                    "capital_allocation": {
                        "in_progress_capex_inr_cr": 1200.0,
                        "expected_commercialization_quarter": "FY26Q4",
                        "deleveraging_trend": "Substantial debt reduction, strong cash flow from tanker operations"
                    },
                    "geopolitical_supply_chain": {
                        "geographic_revenue_split": {"Global International Shipping": 75.0, "Domestic Coastal Trade": 25.0},
                        "supply_chain_dependencies": ["Global bunkering ports (Singapore, Fujairah)", "International maritime classification societies"],
                        "macro_geopolitical_sensitivities": ["Red Sea security", "Strait of Hormuz transit security", "IMO environmental emission standards"],
                        "transit_route_risks": ["Geopolitical chokepoint blockades directly expand sailing distances and increase revenue"]
                    }
                },
                "concall_snippets": [
                    "SCI Management Review: Tanker dayrates surged by 45% YoY as VLCC and Suezmax vessels reroute via Cape of Good Hope avoiding the Red Sea corridor.",
                    "Fleet modernization programme underway with acquisition of next-gen fuel-efficient LR2 product tankers."
                ]
            },
            {
                "symbol": "HAVELLS",
                "isin": "INE176B01034",
                "parameters": {
                    "cyclicality_profile": {
                        "is_cyclical": False,
                        "cyclicality_type": "Consumer Electricals & Housing Modernization",
                        "cycle_duration_years": 8.0,
                        "cycle_current_stage": "Solar & Consumer Electricals Expansion",
                        "key_revenue_drivers": ["Lloyd air conditioning & appliances", "Industrial cables & wires", "Switchgears & domestic lighting", "PM Surya Ghar residential solar equipment"],
                        "margin_sensitivities": {"Copper & Aluminium": 0.35, "Polymer packaging": 0.10},
                        "stage_conviction": 0.90,
                        "stage_rationale": "Rapid adoption of rooftop solar under PM Surya Ghar and housing electrification."
                    },
                    "business_sensitivities": {
                        "key_revenue_drivers": ["PM Surya Ghar Muft Bijli Yojana rooftop solar rollout", "Real estate construction & rewiring demand", "Summer cooling appliance sales"],
                        "raw_material_sensitivities": {"LME Copper spot prices": 0.35, "Aluminium ingots": 0.15, "Sheet metal & refrigerants": 0.12},
                        "pricing_power_assessment": "Strong brand recall and nationwide dealer network supporting regular price pass-throughs",
                        "moat_rating": 8.8
                    },
                    "order_book_metrics": {
                        "executable_order_book_inr_cr": None,
                        "ttm_revenue_inr_cr": 19800.0,
                        "order_book_to_bill_ratio": None,
                        "execution_visibility_years": None
                    },
                    "capital_allocation": {
                        "in_progress_capex_inr_cr": 600.0,
                        "expected_commercialization_quarter": "FY26Q3",
                        "deleveraging_trend": "Virtually Zero Debt, High Return on Equity (>18%)"
                    },
                    "geopolitical_supply_chain": {
                        "geographic_revenue_split": {"India Domestic": 97.0, "Exports": 3.0},
                        "supply_chain_dependencies": ["Domestic copper and aluminium smelters", "AC compressor manufacturers"],
                        "macro_geopolitical_sensitivities": ["Government solar rooftop subsidies", "LME base metal price volatility"],
                        "transit_route_risks": ["Domestic road logistics across Indian states"]
                    }
                },
                "concall_snippets": [
                    "Concall Highlights: Havells saw 25% YoY growth in industrial cables and solar distribution equipment under PM Surya Ghar Muft Bijli Yojana scheme.",
                    "Lloyd segment turned EBIT positive driven by supply chain localization and strong summer demand across tier-1 and tier-2 metros."
                ]
            }
        ]

        from reality_engine.db.vector_store import VectorStoreManager
        vector_store = VectorStoreManager()
        
        param_count = 0
        concall_chunks = []
        fts_rows = []

        for item in canonical_data:
            sym = item["symbol"]
            isin = item["isin"]
            for p_key, p_val in item["parameters"].items():
                self.upsert_parameter(isin, sym, p_key, p_val, confidence_score=0.95, source_document_ref="Canonical_Intelligence_FY26")
                param_count += 1
            
            for idx, text in enumerate(item.get("concall_snippets", [])):
                chunk_id = f"CANONICAL_{sym}_CHUNK_{idx+1}"
                concall_chunks.append({
                    "id": chunk_id,
                    "symbol": sym,
                    "isin": isin,
                    "text": text,
                    "document_date": "2026-08-14",
                    "source_type": "CONCALL_TRANSCRIPT"
                })
                fts_rows.append((chunk_id, sym, isin, "CONCALL_TRANSCRIPT", "2026-08-14", text))

        if concall_chunks:
            vector_store.add_chunks(concall_chunks)
            with self.db.session() as conn:
                for row in fts_rows:
                    conn.execute(
                        "INSERT INTO intelligence_fts(chunk_id, symbol, isin, source_type, document_date, document_text) VALUES (?, ?, ?, ?, ?, ?)",
                        row
                    )

        return {"parameters_seeded": param_count, "concall_chunks_seeded": len(concall_chunks)}


distillation_engine = DistillationEngine()
seed_ontology_definitions = distillation_engine.seed_ontology_definitions
