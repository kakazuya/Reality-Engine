# Module 09: Adversarial Audit, Subagent Critiques & Critical Refinements

---

## 1. The Adversarial Council: Execution-Level Stress Tests

To transform this system from a conceptual model into an industrial-grade, failure-proof engine, a council of specialized subagents was assembled to aggressively critique the architecture from execution, alpha generation, and operational reliability perspectives.

```
+--------------------------------------------------------------------------------------------------------+
|                                  ADVERSARIAL COUNCIL STRESS TESTS                                      |
+--------------------------+------------------------------------+----------------------------------------+
| Subagent Role            | Critical Vulnerability Identified  | Architecture Resolution & Action       |
+--------------------------+------------------------------------+----------------------------------------+
| 1. Data Integrity & Scraping | Brittle OAuth on 3rd-party site    | SUBTRACT 3rd-party web scraping.       |
|    Auditor               | (financiallyfree.in) causes breaks.| ADD official NSE Indices & Breadth feed|
+--------------------------+------------------------------------+----------------------------------------+
| 2. Market Microstructure & | Missing real-world crash alpha:  | ADD SEBI Insider Trading (PIT) &       |
|    Forensic Quant        | Delivery alone misses promoter buy | Bulk/Block deals + Promoter Pledge gate|
+--------------------------+------------------------------------+----------------------------------------+
| 3. Knowledge Graph & NLP  | Entity resolution explosion in     | ADD Strict Canonical Entity Registry & |
|    Architect             | unstructured LLM graph extraction  | Predefined Relation Ontologies         |
+--------------------------+------------------------------------+----------------------------------------+
| 4. Value Trap & Solvency  | Buying leveraged cyclicals during  | ADD Forensic Solvency Filter           |
|    Auditor               | market crashes leads to ruin       | (Interest Coverage & Debt/EBITDA gate) |
+--------------------------+------------------------------------+----------------------------------------+
| 5. Concurrency & Compute  | Embedding full 60-page PDF concalls| SUBTRACT full-doc embedding.           |
|    Optimizer             | wastes VRAM on compliance noise    | ADD Smart Section Splitter (Remarks/Q&A|
+--------------------------+------------------------------------+----------------------------------------+
```

---

## 2. What to SUBTRACT (Pruning Overkill & Brittle Dependencies)

### ❌ Subtraction 1: 3rd-Party Authenticated Scraping (`financiallyfree.in`)
* **Critique**: Running a persistent Chromium browser via Playwright behind Google Gmail OAuth creates extreme fragility: Google session tokens expire every 14–30 days, headless Chromium consumes 500MB–1GB RAM, and DOM changes break parsers.
* **Resolution**: The underlying data (Sector Advance/Decline, Nifty 500 breadth, index momentum) is generated natively by the exchange. We **eliminate** the third-party web dependency and ingest the authoritative ground-truth feeds directly:
  - **NSE Sector & Index Bhavcopy**: `https://nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv`
  - **NSE Advance/Decline Feed**: `https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500`

### ❌ Subtraction 2: Monolithic Whole-PDF Concall Vectorization
* **Critique**: 60-page concall transcripts contain 40% legal disclaimers, repetitive operator instructions, safe harbor statements, and courtesy remarks. Ingesting this verbatim pollutes the vector index with low-signal chunks and wastes GPU VRAM.
* **Resolution**: Implement a deterministic **Regex Section Pruner**:
  1. Retain Section A: *Management Opening Remarks & Strategic Overview* (High signal for capex, guidance, order book).
  2. Retain Section B: *Analyst Q&A on Margins, Demand Trends, and Sourcing*.
  3. Discard: Safe harbor statements, operator greetings, and attendance rolls.

---

## 3. What to ADD (Crucial Real-World Alpha & Forensic Filters)

```
                                  +-------------------------------------------------------------+
                                  |         NEW ESSENTIAL ALPHA & SAFETY FEEDS (ADDED)          |
                                  +------------------------------+------------------------------+
                                                                 |
               +-------------------------------------------------+------------------------------------------------+
               |                                                 |                                                |
+--------------+--------------+                   +--------------+--------------+                  +--------------+--------------+
| 1. SEBI INSIDER TRADING     |                   | 2. BULK & BLOCK DEALS        |                  | 3. FORENSIC SOLVENCY GATE   |
| - Daily PIT Reg 7(2) feed   |                   | - Institutional trades >0.5% |                  | - Promoter Pledge < 15%     |
| - Tracks Promoter & KMP open|                   | - Matches FII/DII aggressive |                  | - Interest Coverage >= 2.5x |
|   market buys during panics |                   |   accumulation during drops  |                  | - Eliminates value traps    |
+-----------------------------+                   +-----------------------------+                  +-----------------------------+
```

### ✅ Addition 1: SEBI Insider Trading (PIT) & Promoter Open Market Buys
* **Why It Matters**: When a stock crashes 15–20% during a macro panic, the ultimate signal of intrinsic resilience is **Promoters buying their own shares from the open market**.
* **Data Source**: Official NSE Insider Trading daily feed (`https://www.nseindia.com/api/corporates-pit`).
* **Implementation**: Stored in `insider_trades` table. If Promoter acquisition $> ₹1\text{ Crore}$ occurs during a 10-day price drop, trigger `PROMOTER_ACCUMULATION_SIGNAL` (+30% boost to conviction score).

### ✅ Addition 2: Bulk & Block Deals Ingestion
* **Why It Matters**: Marquee domestic mutual funds and foreign institutional investors accumulate high-conviction scrips via block windows or bulk market purchases during market corrections.
* **Data Source**: NSE Daily Bulk/Block archives (`bulk_deals_DDMMYYYY.csv` and `block_deals_DDMMYYYY.csv`).
* **Implementation**: Match institutional buyer identities against marquee fund lists (e.g., HDFC MF, SBI MF, Kotak MF, Government Pension Funds).

### ✅ Addition 3: Forensic Solvency & Value Trap Gate
* **Why It Matters**: Buying optically cheap cyclical stocks during a crisis is fatal if the company is over-leveraged and cannot service its debt during an extended downturn.
* **Hard Constraints (Must Pass Before Any Buy Recommendation)**:
  1. **Promoter Pledge Constraint**: $\text{Promoter Pledge} \le 15.0\%$ of total promoter holding.
  2. **Interest Coverage Ratio**: $\text{EBIT} / \text{Interest Expense} \ge 2.5\times$.
  3. **Debt-to-Equity Trajectory**: Net Debt / Equity $\le 1.2\times$ (or non-increasing for capital-intensive cyclicals).
  4. **Auditor Integrity Check**: Discard companies with qualified auditor opinions, frequent CFO/Auditor resignations, or high related-party transactions ($>25\%$ of revenue).

### ✅ Addition 4: Order Book-to-Bill & Visibility Metric
* **Why It Matters**: For Capital Goods, Defence, Railways, Power Transmission, and EMS/Electronic Manufacturing companies, revenue growth for the next 2–3 years is locked inside the **Order Book**.
* **Formula**:
  $$\text{Order Book-to-Bill Ratio} = \frac{\text{Current Executable Order Book (INR Cr)}}{\text{TTM Revenue (INR Cr)}}$$
* **Threshold**: Ratios $> 2.5\times$ with multi-year execution visibility provide an asymmetric safety buffer during broader market contractions.

### ✅ Addition 5: Automated Market Drawdown Event Trigger ("The Panic Protocol")
* **Why It Matters**: The system shouldn't only run at a fixed clock time. It should actively wake up when the market experiences severe intraday or multi-day drawdowns.
* **Trigger Conditions**:
  - Nifty 50 or Nifty Midcap 100 falls $\ge 1.5\%$ in a single session, OR
  - Sector Index falls $\ge 3.0\%$ due to a geopolitical/macro headline.
* **Automated Action**:
  - Automatically activates the **Crisis Opportunism Engine**.
  - Runs graph traversal to simulate the shock and cross-references with stocks experiencing **Delivery Volume Spikes** while prices are falling (Institutions soaking retail panic).

---

## 4. Refined Database Schema Additions

```sql
-- 1. SEBI Insider Trading (PIT) & Promoter Buys
CREATE TABLE IF NOT EXISTS insider_trades (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    isin TEXT NOT NULL,
    acquirer_name TEXT NOT NULL,
    category_of_person TEXT NOT NULL, -- 'PROMOTER', 'PROMOTER_GROUP', 'DIRECTOR', 'KMP'
    transaction_type TEXT NOT NULL,   -- 'BUY', 'SELL', 'PLEDGE', 'REVOCATION'
    num_shares INTEGER NOT NULL,
    value_inr_lacs REAL NOT NULL,
    mode_of_acquisition TEXT,        -- 'OPEN_MARKET', 'OFF_MARKET', 'PREFERENTIAL'
    acquisition_date DATE NOT NULL,
    intimation_date DATE NOT NULL,
    FOREIGN KEY (isin) REFERENCES master_companies(isin)
);

-- 2. Daily Bulk & Block Deals
CREATE TABLE IF NOT EXISTS bulk_block_deals (
    id TEXT PRIMARY KEY,
    deal_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    client_name TEXT NOT NULL,
    deal_type TEXT CHECK(deal_type IN ('BULK', 'BLOCK')),
    buy_sell TEXT CHECK(buy_sell IN ('BUY', 'SELL')),
    quantity INTEGER NOT NULL,
    trade_price REAL NOT NULL,
    is_marquee_institution BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Forensic Solvency & Governance Metrics
CREATE TABLE IF NOT EXISTS company_forensic_health (
    isin TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    fiscal_year TEXT NOT NULL,
    promoter_holding_pct REAL NOT NULL,
    promoter_pledge_pct REAL NOT NULL,
    interest_coverage_ratio REAL NOT NULL,
    debt_to_equity_ratio REAL NOT NULL,
    altman_z_score REAL,
    auditor_name TEXT,
    has_qualified_audit_opinion BOOLEAN DEFAULT 0,
    related_party_tx_pct_revenue REAL,
    is_solvency_approved BOOLEAN DEFAULT 1,
    last_evaluated_date DATE NOT NULL,
    FOREIGN KEY (isin) REFERENCES master_companies(isin)
);

-- 4. Official NSE Sector & Index Breadth
CREATE TABLE IF NOT EXISTS nse_index_breadth (
    date DATE NOT NULL,
    index_name TEXT NOT NULL,          -- 'NIFTY 50', 'NIFTY MIDCAP 100', 'NIFTY INFRA'
    open REAL, high REAL, low REAL, close REAL,
    change_pct REAL NOT NULL,
    advances_count INTEGER NOT NULL,
    declines_count INTEGER NOT NULL,
    advance_decline_ratio REAL NOT NULL,
    pe_ratio REAL,
    pb_ratio REAL,
    dividend_yield REAL,
    PRIMARY KEY(date, index_name)
);

CREATE INDEX IF NOT EXISTS idx_insider_sym_date ON insider_trades(symbol, acquisition_date DESC);
CREATE INDEX IF NOT EXISTS idx_deals_sym_date ON bulk_block_deals(symbol, deal_date DESC);
CREATE INDEX IF NOT EXISTS idx_forensic_solvency ON company_forensic_health(is_solvency_approved);
```

---

## 5. Refined Asymmetric Crisis Synthesis Algorithm

With these additions, the EOD and Crisis Opportunism engine computes the **Asymmetric Conviction Rank**:

$$\text{Crisis Conviction Score} = \left(\mathcal{S}_{\text{TechFlow}} \times 0.25\right) + \left(\mathcal{S}_{\text{Funda}} \times 0.25\right) + \left(\mathcal{S}_{\text{CausalResilience}} \times 0.30\right) + \left(\mathcal{S}_{\text{SmartMoney}} \times 0.20\right)$$

Where:
1. **$\mathcal{S}_{\text{SmartMoney}}$**:
   $$\mathcal{S}_{\text{SmartMoney}} = (\text{Promoter Open Market Buy} \times 40) + (\text{Marquee Bulk Deal} \times 30) + (\text{Delivery Spike Ratio} \ge 2.5 \times 30)$$
2. **$\mathcal{S}_{\text{CausalResilience}}$**:
   - Verified via `trace_macro_causal_chain`: Direct transmission confirms zero operational impairment from the active headline/shock, while order book-to-bill $\ge 2.5\times$ guarantees multi-year cash flows.
3. **Forensic Gate Enforcement**:
   - If `is_solvency_approved == 0` (Promoter pledge $>15\%$ or Interest coverage $<2.5\times$), the stock is **strictly disqualified** regardless of technicals or valuation.
