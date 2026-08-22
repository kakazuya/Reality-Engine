# Module 08: Macro Policy, Economic Surveys & Causal Knowledge Graph

---

## 1. System Vision: The Living Causal Reality Graph

The system is not an isolated stock screener. It is an **omnivorous, living and breathing Causal Knowledge Graph** that models the objective reality of the economic and industrial ecosystem.

It continuously ingests and cross-correlates macro policy drivers with ground-level corporate disclosures:

```
+--------------------------------------------------------------------------------------------------------------------+
|                                      MACROECONOMIC & GOVERNMENT POLICY FEEDS                                       |
|  - Union Finance Budget Speeches (Ministry Capex: Railways, Defence, Infra, Energy, Semiconductor PLI)             |
|  - RBI Economic Surveys, MPC Resolutions, Liquidity Reports & Credit Growth Bulletins                              |
|  - Institutional Research Reports (Brokerage Sector Models, Channel Checks, Global Commodity Outlooks)            |
|  - Government Gazettes & Notifications (Anti-Dumping Duties, Custom Tariffs, Export Quotas, Subsidy Schemes)       |
+---------------------------------------------------------+----------------------------------------------------------+
                                                          |
                                                          ▼
+--------------------------------------------------------------------------------------------------------------------+
|                                    CAUSAL GRAPH EXTRACTION & ONTOLOGY ENGINE                                       |
|  Maps Directional Causal Edges: [Policy / Shock / Macro Shift] ---> [Transmission Mechanism] ---> [Stock Impact]  |
+---------------------------------------------------------+----------------------------------------------------------+
                                                          |
                                                          ▼
+--------------------------------------------------------------------------------------------------------------------+
|                                   BOTTOM-UP CORPORATE DISCLOSURES & FOOTPRINTS                                     |
|  - Earnings Concall Transcripts, Investor Presentations, Annual Reports, Management Guidance                       |
|  - Daily Full Bhavcopy Deliverable Footprints (Institutional Accumulation / Distribution)                          |
+---------------------------------------------------------+----------------------------------------------------------+
                                                          |
                                                          ▼
+--------------------------------------------------------------------------------------------------------------------+
|                                       OBJECTIVE REALITY MODEL IN SQLITE & VECTORS                                  |
|                               (Graph Nodes + Directed Causal Edges + Dynamic JSON Metrics)                         |
+--------------------------------------------------------------------------------------------------------------------+
```

---

## 2. Ingestion Feeds: Macro, Policy & Research Reports

```
+-------------------+--------------------------------------------+----------------------------------------------------+
| Source Category   | Target Documents & Feeds                   | Ingestion Frequency & Mechanism                    |
+-------------------+--------------------------------------------+----------------------------------------------------+
| Union Budget      | Budget Speech PDF, Ministry Demand for     | Annual / Ad-hoc Supplementary Demands              |
|                   | Grants, Fiscal Deficit Statements          | (PyMuPDF + Markdown Structured Parsing)            |
+-------------------+--------------------------------------------+----------------------------------------------------+
| RBI Disclosures   | RBI Annual Report, Economic Survey, MPC    | Bi-Monthly / Annual                                |
|                   | Minutes, State of Economy Reports          | (RBI Bulletin RSS / Automated PDF Downloader)      |
+-------------------+--------------------------------------------+----------------------------------------------------+
| Institutional     | Top Institutional Brokerage Reports        | Daily / Weekly                                     |
| Research          | (Motilal, Kotak, ICICI Sec, Jefferies, etc.)| (Telegram Research Threads + PDF Storage)          |
+-------------------+--------------------------------------------+----------------------------------------------------+
| Ministry Circulars| Ministry of Commerce (Anti-Dumping),       | Weekly automated scraping of                       |
| & Gazettes        | Ministry of Power, Defence DAP Gazettes    | PIB (Press Information Bureau) & Ministry portals  |
+-------------------+--------------------------------------------+----------------------------------------------------+
```

---

## 3. Causal Graph Schema & Graph Modeling in SQLite

To maintain maximum performance without heavy graph database daemons (like Neo4j), the causal graph is implemented using an **Adjacency & Property Graph Model** natively in SQLite:

```sql
-- 1. Graph Entity Nodes (Macro Concepts, Policies, Commodities, Sectors, Companies)
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id TEXT PRIMARY KEY,             -- e.g., 'MACRO_UNION_BUDGET_2026_RAILWAY_CAPEX', 'STOCK_TITAGARH'
    node_type TEXT NOT NULL,              -- 'MACRO_POLICY', 'COMMODITY', 'SECTOR', 'GEOGRAPHY', 'COMPANY', 'MILITARY_CONFLICT'
    name TEXT NOT NULL,
    metadata_json TEXT NOT NULL,          -- Full node attributes (e.g., budget allocation INR Cr, baseline price)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Directed Causal Edges (Relationships & Transmission Mechanisms)
CREATE TABLE IF NOT EXISTS graph_causal_edges (
    edge_id TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL,         -- e.g., 'COMMODITY_CRUDE_OIL'
    target_node_id TEXT NOT NULL,         -- e.g., 'COMPANY_ASIAN_PAINTS'
    relationship_type TEXT NOT NULL,      -- 'RAW_MATERIAL_INPUT', 'POLICY_BENEFICIARY', 'SUPPLIER_TO', 'TRANSIT_VULNERABILITY'
    impact_direction TEXT NOT NULL,       -- 'POSITIVE', 'NEGATIVE', 'NEUTRAL', 'ASYMMETRIC'
    elasticity_score REAL,                -- Magnitude multiplier: e.g., -1.8 (% margin shift per 10% commodity shift)
    transmission_mechanism TEXT NOT NULL, -- Detailed explanatory narrative of the transmission chain
    evidence_document_ref TEXT,           -- Document citation: "Budget_2026_Speech_P22", "Concall_FY26Q1"
    confidence_score REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_node_id) REFERENCES graph_nodes(node_id),
    FOREIGN KEY (target_node_id) REFERENCES graph_nodes(node_id)
);

-- 3. Macro Events & Shock Registry
CREATE TABLE IF NOT EXISTS macro_events (
    event_id TEXT PRIMARY KEY,
    event_name TEXT NOT NULL,             -- e.g., 'RED_SEA_CRISIS_FREIGHT_SURGE', 'UNION_BUDGET_CAPEX_EXPANSION'
    category TEXT NOT NULL,               -- 'GEOPOLITICAL', 'BUDGET', 'MONETARY', 'REGULATORY', 'COMMODITY'
    event_date DATE NOT NULL,
    raw_document_path TEXT,
    summary TEXT NOT NULL,
    affected_nodes_json TEXT,             -- JSON Array of root-affected node_ids
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_edge_source ON graph_causal_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_edge_target ON graph_causal_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_edge_type ON graph_causal_edges(relationship_type);
```

---

## 4. Multi-Hop Causal Propagation Engine

When a macro policy shift, Union Budget announcement, or geopolitical crisis occurs, the system executes a **Recursive Common Table Expression (CTE) Graph Walk** in SQLite to trace the full propagation wave down to individual listed stocks:

```sql
-- Recursive Multi-Hop Causal Traversal in SQLite
WITH RECURSIVE causal_path(
    current_node, 
    path, 
    cumulative_impact, 
    depth, 
    mechanisms
) AS (
    -- Anchor: Starting from the Macro Shock Node
    SELECT 
        node_id, 
        node_id, 
        1.0, 
        0, 
        'Origin: ' || name
    FROM graph_nodes
    WHERE node_id = 'MACRO_UNION_BUDGET_RAILWAY_CAPEX_HIKE'
    
    UNION ALL
    
    -- Recursive Step: Follow causal edges to downstream beneficiaries/victims
    SELECT 
        e.target_node_id,
        cp.path || ' -> ' || e.target_node_id,
        cp.cumulative_impact * COALESCE(e.elasticity_score, 1.0),
        cp.depth + 1,
        cp.mechanisms || ' | ' || e.transmission_mechanism
    FROM graph_causal_edges e
    JOIN causal_path cp ON e.source_node_id = cp.current_node
    WHERE cp.depth < 4 -- Up to 4-hop propagation depth
)
SELECT 
    n.name AS beneficiary_or_victim,
    n.node_type,
    cp.cumulative_impact,
    cp.path AS transmission_chain,
    cp.mechanisms
FROM causal_path cp
JOIN graph_nodes n ON cp.current_node = n.node_id
WHERE n.node_type = 'COMPANY'
ORDER BY ABS(cp.cumulative_impact) DESC;
```

---

## 5. Real-World Macro-to-Micro Causal Examples in the Knowledge Graph

### Example 1: Union Budget Railway & Defence Capex Allocation
1. **Root Node**: `UNION_BUDGET_2026_RAIL_CAPEX` (+18% allocation to ₹2.95 Lakh Cr).
2. **Hop 1 (Sub-Sector)**: `WAGON_PROCUREMENT` & `KAVACH_SAFETY_SYSTEM`.
3. **Hop 2 (Component Suppliers)**: `WHEELS_AND_AXLES` & `RAILWAY_ELECTRONICS_EMS`.
4. **Target Stocks**:
   - `TITAGARH` / `JWL` (Direct wagon contract execution).
   - `KAYNES` / `KERNEX` (Kavach collision avoidance electronics).
   - `RAMKRISHNA_FORGINGS` (Forged wheels & bogie components).

### Example 2: Geopolitical Crisis (Red Sea Shipping Disruption)
1. **Root Node**: `GEOPOLITICAL_RED_SEA_ATTACKS`.
2. **Hop 1 (Direct Impact)**: Ocean freight rates spike from $1,200 to $3,800/FEU; transit times around Cape of Good Hope increase by 14–18 days.
3. **Hop 2 (Transmission)**:
   - *Negative Impact*: European export-oriented textiles and auto-ancillaries without price escalation clauses face margin shrinkage.
   - *Positive Asymmetric Beneficiary*: Domestic shipping lines (`SCI`, `GREAT_EASTERN_SHIPPING`) experience multi-quarter charter rate expansion.

---

## 6. Distillation Agent Prompt for Macro Policy Ingestion

```text
You are the Chief Macroeconomic & Industrial Causal Graph Specialist for Indian Equities.

Your task is to ingest the following policy document (Budget Speech / RBI Survey / Research Report) and extract:
1. Root Macro Nodes: Specific fiscal allocations, policy incentives, tariff modifications, or monetary shifts.
2. Direct & Indirect Transmission Chains: How this policy propagates through sectors, commodities, supply chains, and down to listed Indian companies.
3. Exact Transmission Mechanisms: Quantifiable mechanisms (e.g. "₹12,000 Cr allocation under PM Surya Ghar Yojana -> expands rooftop solar inverter demand by 45% -> directly benefits HAVELS, POLYCAB, WAAREE").
4. Causal Direction & Magnitude: POSITIVE / NEGATIVE, and estimated elasticity score.

Output the extracted entities and directed causal edges in strict Pydantic JSON matching the CausalGraphUpdate schema.
```

---

## 7. Cloud Agent Causal Query Tools

The Cloud LLM Agent is equipped with the following tool:

```json
{
  "name": "trace_macro_causal_chain",
  "description": "Trace the multi-hop transmission chain of a macro event, budget policy, commodity shift, or geopolitical shock down to listed Indian companies.",
  "parameters": {
    "type": "object",
    "properties": {
      "macro_event_or_policy": {
        "type": "string",
        "description": "The macro trigger, e.g., 'Union Budget Railway Capex', 'Crude Spike', 'Semiconductor PLI Phase 2'"
      },
      "impact_filter": {
        "type": "string",
        "enum": ["ALL", "BENEFICIARIES_ONLY", "VICTIMS_ONLY"],
        "default": "BENEFICIARIES_ONLY"
      },
      "max_hops": {
        "type": "integer",
        "description": "Propagation depth (1 to 4)",
        "default": 3
      }
    },
    "required": ["macro_event_or_policy"]
  }
}
```
