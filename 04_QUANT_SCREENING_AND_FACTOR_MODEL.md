# Module 04: Quantitative Screening & Factor Model

---

## 1. Quantitative Core Philosophy

In the Indian equity markets, price movement is fundamentally driven by **Institutional Accumulation (Delivery Footprints)** coupled with **Fundamental Earnings Acceleration (Operating Leverage)**.

The Quantitative Screener operates as a high-speed pre-filter at EOD ($18:30\text{ IST}$) across all ~2,500 listed equities, pruning the universe down to the **Top 20 high-potential candidates** before passing them to the Cloud AI Agent for deep synthesis.

---

## 2. Factor Definitions & Mathematical Formulas

### Factor 1: Technical Flow & Institutional Delivery Momentum ($\mathcal{S}_{\text{TechFlow}}$)

1. **20-Day SMA of Deliverable Volume**:
   $$\text{SMA}_{20}(\text{DelivVolume}_t) = \frac{1}{20} \sum_{i=0}^{19} \text{DelivVolume}_{t-i}$$

2. **Delivery Spike Ratio ($\text{DSR}$)**:
   $$\text{DSR}_t = \frac{\text{DelivVolume}_t}{\text{SMA}_{20}(\text{DelivVolume}_t)}$$

3. **Delivery Conviction Score ($\text{DCS}$)**:
   $$\text{DCS}_t = \text{DSR}_t \times \text{DelivPercentage}_t$$
   *Interpretation*: If a stock trades with $65\%$ delivery percentage and $3.0\times$ its 20-day average delivery volume, $\text{DCS} = 3.0 \times 65 = 195.0$ (Strong institutional buying).

4. **Breakout & Trend Alignment**:
   - $\text{Distance to 52W High } (\%) = \frac{\text{52W High} - \text{Close}}{\text{52W High}} \times 100$
   - $\text{Trend Filter} = (\text{Close} > \text{SMA}_{20}) \land (\text{SMA}_{20} > \text{SMA}_{50}) \land (\text{SMA}_{50} > \text{SMA}_{200})$
   - $\text{RSI Momentum} = 1 \text{ if } 55 \le \text{RSI}_{14} \le 72 \text{ else } 0$

$$\mathcal{S}_{\text{TechFlow}} = \min\left(100, \; (\text{DCS} \times 0.35) + \left(\max(0, 15 - \text{Dist52W}) \times 2.5\right) + (\text{Trend Filter} \times 15) + (\text{RSI Momentum} \times 15)\right)$$

---

### Factor 2: Fundamental Acceleration ($\mathcal{S}_{\text{Funda}}$)

1. **YoY Revenue Growth**:
   $$g_{\text{Rev}} = \frac{\text{Rev}_{t} - \text{Rev}_{t-4}}{\text{Rev}_{t-4}} \times 100$$

2. **YoY PAT Growth**:
   $$g_{\text{PAT}} = \frac{\text{PAT}_{t} - \text{PAT}_{t-4}}{\text{PAT}_{t-4}} \times 100$$

3. **Operating Margin Expansion ($\Delta\text{OPM}$)**:
   $$\Delta\text{OPM} = \text{EBITDA Margin}_t - \text{EBITDA Margin}_{t-4} \quad (\text{in basis points})$$

$$\mathcal{S}_{\text{Funda}} = \min\left(100, \; \left(\max(0, g_{\text{Rev}}) \times 0.4\right) + \left(\max(0, g_{\text{PAT}}) \times 0.4\right) + \left(\max(0, \Delta\text{OPM} / 50) \times 20\right)\right)$$

---

### Factor 3: Alternative Sentiment & Breadth Concurrence ($\mathcal{S}_{\text{Alt}}$)

1. **Telegram Discussion & OCR Intensity**:
   - Number of distinct bullish chart markups/mentions for the ticker in the last 72 hours.
2. **FinanciallyFree Sector Strength**:
   - Sector Advance/Decline Ratio $> 1.5$ for the scrip's parent sector.

$$\mathcal{S}_{\text{Alt}} = \min\left(100, \; (\text{Mention Count} \times 15) + (\text{Sector Breadth Score} \times 25)\right)$$

---

## 3. Composite Multi-Factor Ranking Algorithm

Every evening at $18:30\text{ IST}$, calculate the composite weighted rank:

$$\text{Composite Score} = (0.45 \times \mathcal{S}_{\text{TechFlow}}) + (0.35 \times \mathcal{S}_{\text{Funda}}) + (0.20 \times \mathcal{S}_{\text{Alt}})$$

```python
import sqlite3
import pandas as pd
import numpy as np

def compute_daily_screener(date_str: str, db_path: str = "./data/equity_intelligence.db") -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    
    # 1. Fetch Technical and Delivery metrics
    tech_query = """
    SELECT 
        p.symbol, p.isin, p.close, p.change_pct, p.delivery_pct, 
        p.delivery_spike_ratio, p.delivery_conviction_score,
        p.distance_from_52w_high_pct, p.rsi_14,
        p.close > p.sma_20 AND p.sma_20 > p.sma_50 AS is_trending,
        c.industry, c.market_cap_tier
    FROM daily_price_delivery p
    JOIN master_companies c ON p.isin = c.isin
    WHERE p.date = ? AND p.series = 'EQ' AND p.delivery_spike_ratio > 1.5 AND p.delivery_pct >= 40.0
    """
    df_tech = pd.read_sql(tech_query, conn, params=[date_str])
    
    if df_tech.empty:
        conn.close()
        return pd.DataFrame()
        
    # 2. Fetch Latest Quarterly Fundamentals
    funda_query = """
    SELECT 
        isin, yoy_revenue_growth_pct, yoy_pat_growth_pct, ebitda_margin_pct
    FROM quarterly_financials
    WHERE id IN (SELECT MAX(id) FROM quarterly_financials GROUP BY isin)
    """
    df_funda = pd.read_sql(funda_query, conn)
    
    # 3. Merge Datasets
    df_merged = pd.merge(df_tech, df_funda, on='isin', how='left').fillna(0)
    
    # 4. Compute Scores
    # Technical Score
    df_merged['tech_score'] = np.clip(
        (df_merged['delivery_conviction_score'] * 0.35) +
        (np.clip(15 - df_merged['distance_from_52w_high_pct'], 0, 15) * 2.5) +
        (df_merged['is_trending'] * 15) +
        ((df_merged['rsi_14'].between(55, 75)) * 15),
        0, 100
    )
    
    # Fundamental Score
    df_merged['funda_score'] = np.clip(
        (np.maximum(0, df_merged['yoy_revenue_growth_pct']) * 0.4) +
        (np.maximum(0, df_merged['yoy_pat_growth_pct']) * 0.4),
        0, 100
    )
    
    # Composite Score
    df_merged['composite_score'] = (df_merged['tech_score'] * 0.55) + (df_merged['funda_score'] * 0.45)
    
    # Sort and return Top 20 Candidates
    top_candidates = df_merged.sort_values(by='composite_score', ascending=False).head(20)
    conn.close()
    return top_candidates
```

---

## 4. Screening Filters & Safety Constraints

The screener strictly rejects scrips that fail liquidity and corporate governance checks:
1. **Minimum Daily Turnover**: Turnover must exceed $\ge \text{INR } 5\text{ Crore}$ to avoid illiquid micro-caps.
2. **Circuit Check**: Exclude stocks locked in Upper Circuit or Lower Circuit ($|\text{Change } \%| = 5.0\%, 10.0\%, \text{or } 20.0\%$ with zero traded volume divergence).
3. **ASM / GSM Surveillance**: Exclude scrips placed under Stage 2+ Additional Surveillance Measure (ASM) or Graded Surveillance Measure (GSM) by SEBI.
