# Module 07: Dynamic Financial Distillation & Parameter Engine

---

## 1. Architectural Objective: The Frontier Distilled Knowledge Layer

Rather than treating company financials and disclosures as static rows of numbers, the system operates an **Automated Knowledge Distillation Layer**. 

This layer transforms verbose, unstructured qualitative data (annual reports, concalls, credit rating reports, sector notes) into **structured, queryable quantitative parameters** that dynamically influence the decision and ranking engine.

```
+----------------------------------------------------------------------------------------------------+
|                               UNSTRUCTURED VERBOSE DISCLOSURES                                     |
|           (Concalls, Annual Reports, Investor Presentations, Industry Notes, Reg Filings)          |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                               FRONTIER LLM DISTILLATION WORKER                                     |
|           - Sector Cyclicality Classifier & Cycle Duration Estimator                               |
|           - Key Revenue & Margin Sensitivity Driver Identification (Raw Materials, FX, Capex)      |
|           - Moat, Pricing Power & Management Capital Allocation Track Record                       |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                         DYNAMIC HYBRID KNOWLEDGE STORE (SQLITE + JSON)                             |
|  +----------------------------------------------------------------------------------------------+  |
|  | Base Relational Table: master_companies (ISIN, Symbol, Sector, MarketCap)                    |  |
|  | Dynamic Attribute Registry: company_distilled_parameters (JSONB / EAV Pattern)                |  |
|  |   - is_cyclical: true/false | cycle_duration_years: 4-6 | cycle_current_stage: "EARLY_EXPANSION"|  |
|  |   - primary_revenue_drivers: ["CRUDE_OIL_SPREADS", "ETHANOL_BLENDING_MANDATE"]              |  |
|  |   - raw_material_sensitivity: [{"material": "Natural Gas", "margin_impact_bps": 220}]       |  |
|  +----------------------------------------------------------------------------------------------+  |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                           DYNAMIC FACTOR INJECTION INTO EOD RANKING                                |
|  - EOD Engine queries dynamic parameters on-the-fly without database migrations                     |
|  - User can introduce custom heuristics (e.g. "Penalize Cyclicals at Late Peak Stage")             |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Dynamic Schema Architecture: Zero-Migration Parameter Store

To ensure that **new parameters can be introduced at any time without schema migrations or breaking code**, the storage layer utilizes a **Hybrid Relational-Document Entity-Attribute-Value (EAV) + JSON1** architecture in SQLite.

```sql
-- 1. Parameter Definitions Registry
-- Allows defining new metrics and their types dynamically (e.g., 'cyclicality_type', 'moat_rating')
CREATE TABLE IF NOT EXISTS dynamic_parameter_definitions (
    parameter_key TEXT PRIMARY KEY,       -- e.g., 'cyclicality_profile', 'raw_material_driver'
    display_name TEXT NOT NULL,
    data_type TEXT NOT NULL,              -- 'JSON', 'FLOAT', 'STRING', 'BOOLEAN'
    description TEXT,
    category TEXT NOT NULL,               -- 'CYCLICALITY', 'BUSINESS_MODEL', 'GOVERNANCE', 'MACRO'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Distilled Company Parameters Table (Dynamic Key-Value Store)
CREATE TABLE IF NOT EXISTS company_distilled_parameters (
    isin TEXT NOT NULL,
    symbol TEXT NOT NULL,
    parameter_key TEXT NOT NULL,
    value_json TEXT NOT NULL,             -- JSON string containing structured parameter payload
    confidence_score REAL DEFAULT 1.0,    -- LLM distillation confidence (0.0 to 1.0)
    source_document_ref TEXT,             -- e.g., "Concall_FY26Q1_P14", "AnnualReport_FY25"
    last_updated_date DATE NOT NULL,
    PRIMARY KEY (isin, parameter_key),
    FOREIGN KEY (isin) REFERENCES master_companies(isin),
    FOREIGN KEY (parameter_key) REFERENCES dynamic_parameter_definitions(parameter_key)
);

-- Indexing for instantaneous JSON path queries
CREATE INDEX IF NOT EXISTS idx_distilled_sym_key ON company_distilled_parameters(symbol, parameter_key);
```

### SQLite JSON1 Dynamic Query Example
Because SQLite natively supports `json_extract()` and JSON path operators (`->`), any custom metric can be extracted in standard SQL queries:

```sql
-- Query all companies in Early/Mid Upcycle with high sensitivity to raw material price cuts
SELECT 
    symbol,
    json_extract(value_json, '$.is_cyclical') AS is_cyclical,
    json_extract(value_json, '$.cycle_stage') AS cycle_stage,
    json_extract(value_json, '$.cycle_duration_years') AS cycle_duration_years,
    json_extract(value_json, '$.key_revenue_drivers') AS key_drivers
FROM company_distilled_parameters
WHERE parameter_key = 'cyclicality_profile'
  AND json_extract(value_json, '$.cycle_stage') IN ('EARLY_RECOVERY', 'MID_EXPANSION');
```

---

## 3. Core Distillation Ontologies & Parameter Schemas

### A. Cyclicality & Sector Cycle Ontology (`cyclicality_profile`)

```json
{
  "is_cyclical": true,
  "cyclicality_type": "COMMODITY_SPREAD_DRIVEN", 
  "typical_cycle_duration_years": {
    "min_years": 4.0,
    "max_years": 6.5,
    "average_years": 5.0
  },
  "cycle_current_stage": "EARLY_EXPANSION",
  "stage_conviction": 0.88,
  "key_stage_indicators": [
    "EBITDA margins bottomed in Q3 FY25 at 8.2% and expanded to 13.5% in Q1 FY27",
    "Sector capacity utilization reached 86%, triggering greenfield capex"
  ],
  "cycle_inflection_triggers": [
    "Global steel export tariffs by China",
    "Domestic infrastructure spending allocation increase in union budget"
  ]
}
```

### B. Revenue & Margin Sensitivities (`business_sensitivities`)

```json
{
  "key_revenue_drivers": [
    {
      "driver_name": "Government Ethanol Blending Mandate (20% Target)",
      "impact_direction": "POSITIVE",
      "revenue_share_impact_pct": 28.0,
      "transmission_mechanism": "Distillery capacity expansion directly converts B-heavy molasses into ethanol at guaranteed OCM pricing"
    },
    {
      "driver_name": "Domestic Sugar MSP Revision",
      "impact_direction": "POSITIVE",
      "revenue_share_impact_pct": 55.0,
      "transmission_mechanism": "Each ₹1/kg hike in Sugar MSP expands annual EBITDA by ₹85 Cr"
    }
  ],
  "raw_material_sensitivities": [
    {
      "input_commodity": "Imported Coal / Power & Fuel",
      "cost_share_pct": 18.5,
      "hedging_policy": "70% hedged on 6-month forward contracts"
    }
  ],
  "pricing_power_assessment": {
    "moat_rating": "MODERATE",
    "ability_to_pass_cost_inflation": "HIGH_WITH_1_QUARTER_LAG",
    "customer_concentration_risk": "LOW (Top 5 customers < 15% revenue)"
  }
}
```

### C. Geopolitical, Military, Geographic & Supply Chain Exposure (`geopolitical_supply_chain`)

```json
{
  "geographic_revenue_split": {
    "domestic_india_pct": 58.0,
    "north_america_pct": 22.0,
    "europe_pct": 12.0,
    "middle_east_pct": 8.0
  },
  "supply_chain_dependencies": [
    {
      "component_category": "Semiconductor ICs & Bare PCBs",
      "sourcing_geography": "Taiwan & South Korea",
      "transit_route_risk": "Vulnerable to South China Sea logistics disruption",
      "inventory_buffer_days": 75,
      "alternative_sourcing_viability": "MODERATE (Domestic supplier qualified in FY26)"
    },
    {
      "component_category": "Specialty Active Pharmaceutical Ingredients (APIs)",
      "sourcing_geography": "China (Hubei province)",
      "transit_route_risk": "Subject to Chinese export duty changes",
      "inventory_buffer_days": 90,
      "alternative_sourcing_viability": "HIGH (In-house synthesis commissioned in FY27)"
    }
  ],
  "macro_geopolitical_sensitivities": [
    {
      "shock_scenario": "Red Sea Shipping / Suez Canal Disruption",
      "direct_impact": "Ocean freight cost increases by $1,800/FEU with 14-day transit delay to European export clients",
      "pnl_impact_severity": "LOW (Contracts are FOB with freight pass-through clauses)"
    },
    {
      "shock_scenario": "Middle East Military Escalation & Crude Surge > $95/bbl",
      "direct_impact": "Raw material monomers increase by 8-12%; electricity and heat costs rise",
      "pnl_impact_severity": "HIGH (EBITDA margins contract by ~180 bps if sustained > 2 quarters)"
    },
    {
      "shock_scenario": "Indian Defence Indigenization (Positive Mandate)",
      "direct_impact": "Eligible for negative import list tenders with domestic manufacturing preference",
      "pnl_impact_severity": "VERY_HIGH_POSITIVE (Order book multi-year CAGR accelerates to >35%)"
    }
  ]
}
```

---

## 4. Capital Allocation & Balance Sheet Trajectory (`capital_allocation`)

```json
{
  "current_capex_cycle": {
    "in_progress_capex_inr_cr": 450.0,
    "capex_as_pct_of_gross_block": 22.5,
    "expected_commercialization_quarter": "FY27-Q3",
    "projected_peak_revenue_addition_inr_cr": 750.0
  },
  "deleveraging_trend": {
    "peak_debt_to_equity": 1.45,
    "current_debt_to_equity": 0.38,
    "projected_net_cash_status_date": "FY28-Q1"
  }
}
```

---

## 5. Distillation Worker & Update Cycle

The Distillation Engine runs as an asynchronous background worker when new disclosures land or on a weekly schedule.

```python
from pydantic import BaseModel, Field
from typing import List, Optional
import json

class CyclicalityProfile(BaseModel):
    is_cyclical: bool = Field(..., description="Whether business is cyclical or secular growth")
    cyclicality_type: str = Field(..., description="e.g. COMMODITY_PRICE, CAPEX_CYCLE, REGULATORY, MONSOON")
    average_cycle_duration_years: float = Field(..., description="Average span of complete peak-to-trough cycle")
    cycle_current_stage: str = Field(..., description="TROUGH, EARLY_RECOVERY, MID_EXPANSION, PEAK, LATE_DOWNTURN")
    key_revenue_drivers: List[str] = Field(..., description="Core macroeconomic or regulatory drivers")
    margin_sensitivities: List[str] = Field(..., description="Inputs that drastically shift EBITDA margins")
    stage_rationale: str = Field(..., description="Reasoning for current cycle stage assignment")

def distill_company_profile(symbol: str, concall_text: str, annual_report_text: str, client) -> CyclicalityProfile:
    prompt = f"""
    You are an Expert Frontier Financial Analyst & Accounting Forensic Specialist.
    Analyze the following disclosures for {symbol}. 
    Quantify and distill the business cyclicality, key revenue drivers, margin sensitivities, and current cycle position.
    
    [Concall & Disclosures Excerpts]:
    {concall_text[:80000]}
    
    [Annual Report Highlights]:
    {annual_report_text[:40000]}
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": CyclicalityProfile
        }
    )
    
    return CyclicalityProfile.model_validate_json(response.text)
```

---

## 6. How Distilled Parameters Feed into Decision Making & Crisis Opportunism

When the EOD Ranking Engine, Crisis Screener, and Cloud AI Agent evaluate candidates, they query the dynamic parameters to apply **context-aware valuation, causal shock analysis, and timing rules**:

1. **Cycle Stage Awareness**:
   - If a stock is flagged as `is_cyclical: true` and `cycle_current_stage: "EARLY_RECOVERY"`, high P/E ratio is ignored (classic cyclical bottom where earnings are depressed but valuation looks optically expensive).
   - If `cycle_current_stage: "PEAK"`, technical breakouts are penalized for distribution risk.
2. **Crisis & Shock Simulation Engine (The Asymmetric Fall Edge)**:
   - When a macro panic happens (e.g., Geopolitical tension in Taiwan, Red Sea freight spike, RBI interest rate surprises):
     - The Agent runs `simulate_macro_shock(shock_name="RED_SEA_FREIGHT_SURGE")`.
     - Queries `company_distilled_parameters` across all companies for `geopolitical_supply_chain`.
     - Separates companies with genuine earnings impairment from those with zero operational impact whose stock price fell purely due to market-wide beta dumping.
     - Emits the **Crisis Bargain List** (Resilient companies trading at steep panic discounts).
3. **Commodity & Input Alignment**:
   - If crude oil prices fall by 8%, the screener instantly boosts the composite scores of scrips whose `raw_material_sensitivities` list crude derivatives (e.g., Paints, Specialty Chemicals, Adhesives).
4. **Capex Commercialization Catalyst**:
   - Scrips whose `expected_commercialization_quarter` is within the next 1–2 quarters receive priority weighting in the final Top 5 selection.
