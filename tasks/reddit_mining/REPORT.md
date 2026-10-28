# Reddit mining — how real investors ask about Indian stocks, sectors and policy

Read-only mining of the Arctic Shift archive on `D:\RealityEngine\raw\reddit` (posts from 2024-04-01 for Indian subreddits, last year for international and trading subreddits). Raw text never leaves D: only counts, original paraphrases under 15 words, and pattern names appear below.

## 0. Drift from the context pack and logs

- `fetch.log` / `fetch_intl.log` print `+0` for many subreddits, but the JSONL files on disk are populated (the log is a stale earlier run). Files win: 28 subreddits have rows, 4 are empty and skipped (`IPOIndia`, `ShareMarketIndia`, `Trading_India`, `chartpatterns`).
- The context pack says `equity_intelligence.shareholding` has 40 rows; the reality-data `holding`/`shp_index` path is the one that carries quarterly pledge history for our coverage. The bank marks pledge questions `partial`, not `yes`.
- `DSH_WORKER_PROGRESS_NOTES` is unset in this worker; progress is logged in `tasks/reddit_mining/PROGRESS_NOTES.md`.

## 1. Question-post filter and counts

Deterministic rules, then a read of samples per pattern:

1. **Keep** when the title asks something: a `?`, or an interrogative stem (`why/what/when/how/should/is/are/can/will/worth/best/kaun/kyun/kya/kab/kaise/kitna`) and the post names a market subject (`MARKET` regex over stock/share/nifty/IPO/results/valuation/FII/SEBI/budget... or a known alias).
2. **Drop** personal-finance-only and broker-process posts (tax filing, 80C, insurance, loans, credit score, KYC, broker app bug) when no market subject follows.
3. **Drop** memes/shitposts and bare portfolio-rating requests.
4. Body is read only after the title passes; this keeps the scan at ~30 s/file and the filter auditable.

| | posts |
|---|---:|
| Rows read across 28 non-empty subreddits | 778,501 |
| Kept as question posts | **116,822** (15.0%) |
| Dropped: no_question_marker | 486,253 |
| Dropped: no_market_subject | 152,099 |
| Dropped: meme_or_portfolio_rating | 12,176 |
| Dropped: personal_finance_or_broker | 11,151 |

### 1.1 Per subreddit

| subreddit | group | rows | kept | keep % |
|---|---|---:|---:|---:|
| IndianStockMarket | indian | 108,599 | 23,475 | 21.6% |
| StockMarketIndia | indian | 63,550 | 12,228 | 19.2% |
| Daytrading | technical | 55,496 | 4,573 | 8.2% |
| personalfinanceindia | indian | 55,491 | 7,557 | 13.6% |
| IndianStreetBets | indian | 54,481 | 8,693 | 16.0% |
| NSEbets | indian | 48,686 | 7,173 | 14.7% |
| mutualfunds | indian | 39,669 | 8,268 | 20.8% |
| IndiaTax | indian | 37,879 | 2,682 | 7.1% |
| IndiaBusiness | indian | 35,453 | 2,657 | 7.5% |
| stocks | international | 34,639 | 6,661 | 19.2% |
| IndiaInvestments | indian | 30,704 | 3,480 | 11.3% |
| economy | international | 28,750 | 1,193 | 4.1% |
| trading | technical | 25,887 | 2,532 | 9.8% |
| investing | international | 22,046 | 4,750 | 21.5% |
| ValueInvesting | international | 19,563 | 4,418 | 22.6% |
| indianstocks | indian | 15,872 | 3,752 | 23.6% |
| Bogleheads | international | 14,592 | 3,411 | 23.4% |
| Economics | international | 11,980 | 219 | 1.8% |
| dividends | international | 10,391 | 2,489 | 24.0% |
| options | technical | 9,358 | 789 | 8.4% |
| smallcapstocks | international | 8,139 | 379 | 4.7% |
| swingtrading | technical | 7,580 | 753 | 9.9% |
| StockMarket | international | 7,075 | 736 | 10.4% |
| CanadianInvestor | international | 6,295 | 1,007 | 16.0% |
| algotrading | technical | 5,846 | 547 | 9.4% |
| DalalStreetTalks | indian | 5,389 | 1,000 | 18.6% |
| technicalanalysis | technical | 4,275 | 449 | 10.5% |
| FluentInFinance | international | 3,521 | 120 | 3.4% |
| IndianEconomy | indian | 2,409 | 223 | 9.3% |
| FIREIndia | indian | 1,949 | 182 | 9.3% |
| UKInvesting | international | 1,028 | 134 | 13.0% |
| StockMarketChat | technical | 847 | 120 | 14.2% |
| ausstocks | international | 529 | 125 | 23.6% |
| SecurityAnalysis | international | 385 | 20 | 5.2% |
| EuropeanStocks | international | 145 | 27 | 18.6% |
| IndianOptionTraders | technical | 3 | 0 | 0.0% |

### 1.2 Per month (kept)

| month | kept | month | kept |
|---|---:|---|---:|
| 2024-04 | 1,808 | 2025-08 | 2,349 |
| 2024-05 | 2,006 | 2025-09 | 2,362 |
| 2024-06 | 2,888 | 2025-10 | 3,124 |
| 2024-07 | 3,520 | 2025-11 | 5,816 |
| 2024-08 | 3,691 | 2025-12 | 5,790 |
| 2024-09 | 3,554 | 2026-01 | 7,203 |
| 2024-10 | 3,242 | 2026-02 | 5,990 |
| 2024-11 | 2,768 | 2026-03 | 6,659 |
| 2024-12 | 2,659 | 2026-04 | 5,734 |
| 2025-01 | 2,988 | 2026-05 | 5,828 |
| 2025-02 | 2,436 | 2026-06 | 5,615 |
| 2025-03 | 2,233 | 2026-07 | 4,585 |
| 2025-04 | 2,367 | 2026-08 | 4,366 |
| 2025-05 | 2,291 | 2026-09 | 4,072 |
| 2025-06 | 2,596 | 2026-10 | 3,656 |
| 2025-07 | 2,626 |  |  |

The full subreddit x month matrix is `work/subreddit_month.csv` (31 months x 36 subreddits).

## 2. Family and entity-level frequency

Families 1–20 are `tasks/QUERY_TEMPLATES_2026-10-27.md`. `NEW:*` means no template family fits; the name is the gap we would have to add.

| family | description | posts | share |
|---|---|---:|---:|
| NEW:uncategorised | NEW gap: uncategorised | 54,269 | 46.5% |
| 3 | Change over time | 9,667 | 8.3% |
| NEW:position_decision | NEW gap: position decision | 7,389 | 6.3% |
| NEW:technical_setup | NEW gap: technical setup | 5,789 | 5.0% |
| 15 | Market move -> why | 4,155 | 3.6% |
| 10 | Opinion vs truth | 3,906 | 3.3% |
| 16 | Input-cost / commodity transmission | 3,714 | 3.2% |
| 8 | Peers | 3,676 | 3.1% |
| 1 | Lookup (what did the entity say/report) | 3,182 | 2.7% |
| NEW:ipo_grey_market | NEW gap: ipo grey market | 2,902 | 2.5% |
| NEW:macro_event | NEW gap: macro event | 2,811 | 2.4% |
| 2 | Number (metric for entity/period) | 2,523 | 2.2% |
| NEW:entry_timing | NEW gap: entry timing | 2,342 | 2.0% |
| NEW:group_basket | NEW gap: group basket | 1,704 | 1.5% |
| 4 | Screen (which stocks meet condition) | 1,489 | 1.3% |
| NEW:corporate_action | NEW gap: corporate action | 1,434 | 1.2% |
| 12 | When / timeline | 969 | 0.8% |
| 13 | Inverse screen (topic -> companies) | 917 | 0.8% |
| 11 | Point in time | 810 | 0.7% |
| NEW:sebi_rule | NEW gap: sebi rule | 609 | 0.5% |
| 14 | Governance and audit | 558 | 0.5% |
| 18 | Forward policy impact | 515 | 0.4% |
| 9 | Event window | 415 | 0.4% |
| 17 | Business economics | 341 | 0.3% |
| NEW:flows | NEW gap: flows | 296 | 0.3% |
| 19 | Second-order / supply chain | 181 | 0.2% |
| 6 | Policy -> companies | 173 | 0.1% |
| 5 | Cross-document agreement | 86 | 0.1% |

Entity level:

| level | posts | share |
|---|---:|---:|
| market-wide | 37,162 | 31.8% |
| sector | 29,354 | 25.1% |
| stock | 15,506 | 13.3% |
| index | 10,526 | 9.0% |
| policy | 8,283 | 7.1% |
| theme | 6,216 | 5.3% |
| ipo | 4,969 | 4.3% |
| macro | 4,806 | 4.1% |

How the entity is named (multi-label, title only):

| naming style | posts | share |
|---|---:|---:|
| ticker | 22,604 | 19.3% |
| index | 4,626 | 4.0% |
| abbreviation | 1,904 | 1.6% |
| old_name | 1,347 | 1.2% |
| nickname | 1,283 | 1.1% |
| hinglish | 856 | 0.7% |
| broker | 853 | 0.7% |
| misspelling | 633 | 0.5% |
| group | 335 | 0.3% |

Hop depth (1 = direct fact; 2 = one driver/peer/macro link; 3 = a chain or two or more drivers; heuristic documented in `mine.py::hop_depth`):

| hops | posts | share |
|---|---:|---:|
| 1 | 88,426 | 75.7% |
| 2 | 25,504 | 21.8% |
| 3 | 2,892 | 2.5% |

## 3. Data the asker connects

| data point | posts |
|---|---:|
| price | 22,370 |
| index | 11,387 |
| results | 7,077 |
| technical | 6,735 |
| policy | 6,125 |
| valuation | 5,587 |
| dividend | 5,358 |
| macro | 5,330 |
| ipo | 4,947 |
| holding | 3,989 |
| guidance | 2,350 |
| flows | 2,341 |
| volume | 1,969 |
| oi | 1,521 |
| delivery | 728 |

Top co-occurring pairs (both named in the same post):

| pair | posts |
|---|---:|
| index + price | 2,717 |
| price + technical | 2,457 |
| price + results | 2,143 |
| price + valuation | 2,024 |
| macro + price | 1,744 |
| dividend + price | 1,221 |
| results + valuation | 1,167 |
| index + technical | 1,165 |
| holding + price | 1,163 |
| policy + price | 1,020 |
| price + volume | 963 |
| ipo + price | 888 |
| dividend + macro | 666 |
| flows + price | 651 |
| guidance + price | 570 |

## 4. The top 30 question patterns we are missing

Frequency is the number of kept posts whose title/opening mentions the pattern (rules in `mine.py::MISSING_PATTERNS`; patterns overlap, so counts are upper bounds on distinct asks). Answerability and schema are repeated per row in `patterns.csv`.

### 1. `mf_etf_vs_stock` — 14,945 posts (12.8% of kept)

- Entity focus: fund; answerable today: **no**.
- e.g. “Should I hold an index fund instead of picking stocks?”
- e.g. “SIP in a Nifty ETF or buy the same names directly?”
- e.g. “Which is cheaper over ten years: fund or direct equity?”
- Schema: `fund_master(amfi_code, name, category, benchmark); fund_nav(amfi_code, date, nav); fund_holding(amfi_code, isin, weight, as_of); not held today`

### 2. `fundamental_health_check` — 13,276 posts (11.4% of kept)

- Entity focus: stock; answerable today: **partial**.
- e.g. “Is the balance sheet strong enough to survive a bad year?”
- e.g. “How do debt, ROE and cash flow look together?”
- e.g. “Is the reported profit real cash or accounting?”
- Schema: `annual_financials + quarterly_financials + ar_facts cover most; missing derived_quality(isin, period, roic, wacc, accrual_ratio, debt_equity, interest_coverage, formula_version)`

### 3. `hold_or_sell_position` — 12,649 posts (10.8% of kept)

- Entity focus: stock; answerable today: **partial**.
- e.g. “I am down 30%. Hold, average, or sell?”
- e.g. “Should I book profit after this run-up?”
- e.g. “Is waiting another year for a recovery worth it?”
- Schema: `needs a position-aware layer: position(user_id, isin, qty, avg_price, opened_at) is out of scope; answerable only generically from price/valuation`

### 4. `broker_platform_process` — 8,445 posts (7.2% of kept)

- Entity focus: process; answerable today: **no**.
- e.g. “Which broker charges less for delivery trades?”
- e.g. “Why did my order get rejected on the app?”
- e.g. “How do I move shares between demat accounts?”
- Schema: `out of scope for market data; answer from a help/FAQ corpus only`

### 5. `fno_vs_cash_flow` — 6,711 posts (5.7% of kept)

- Entity focus: stock/derivative; answerable today: **yes**.
- e.g. “Does futures OI tell me where the cash market goes?”
- e.g. “Is the futures premium worth rolling before expiry?”
- e.g. “Do delivery volumes matter when options expire?”
- Schema: `fno_contract(isin, trade_date, expiry, strike, option_type, oi, volume, iv, settle); fno_rollover(isin, expiry_from, expiry_to, roll_pct); futures_basis(isin, date, futures_close, spot_close)`

### 6. `index_inclusion_rebalance` — 6,014 posts (5.1% of kept)

- Entity focus: index; answerable today: **partial**.
- e.g. “How much passive buying comes when a stock enters Nifty?”
- e.g. “Will exclusion force selling at the next review?”
- e.g. “Which ETF flow hits my stock on rebalance day?”
- Schema: `index_membership(index_code, isin, valid_from, valid_to); index_rebalance_event(index_code, announce_date, effective_date, add_isin, del_isin, est_flow_inr)`

### 7. `ipo_grey_listing_day` — 4,574 posts (3.9% of kept)

- Entity focus: ipo; answerable today: **partial**.
- e.g. “How did the grey premium compare with the listing price?”
- e.g. “Is the IPO worth applying for a listing-day gain?”
- e.g. “Why did it list below the grey-market talk?”
- Schema: `ipo_issue(isin, issue_open, issue_close, price_band_low, price_band_high, lot, issue_size_cr, subscription_json); ipo_grey_market(isin, date, gmp_inr, source); ipo_listing(isin, listing_date, open, high, low, close, first_day_return)`

### 8. `ta_support_resistance` — 4,451 posts (3.8% of kept)

- Entity focus: stock/technical; answerable today: **partial**.
- e.g. “Is this support level still valid after the bounce?”
- e.g. “Where do I put a stop below yesterday's low?”
- e.g. “Has resistance been tested enough to break?”
- Schema: `px_nse/px_bse daily OHLCV + delivery held daily_price_delivery; needed technical_level(isin, date, kind, price_low, price_high, touches, method, valid_from, valid_to)`

### 9. `group_basket_entity` — 4,297 posts (3.7% of kept)

- Entity focus: group/basket; answerable today: **partial**.
- e.g. “Which Adani stock is the safest of the group?”
- e.g. “Best PSU bank to buy for the cycle?”
- e.g. “Which Tata company benefits most from the capex?”
- Schema: `entity_group(group_id, name, kind, parent_isin NULL, valid_from, valid_to); entity_group_member(group_id, isin, weight, valid_from, valid_to)`

### 10. `entry_timing_good_time` — 4,080 posts (3.5% of kept)

- Entity focus: stock; answerable today: **partial**.
- e.g. “Is now a good time to enter after the fall?”
- e.g. “Should I wait for a retest before buying?”
- e.g. “Too late to buy after this rally?”
- Schema: `valuation_asof(isin, date, pe, pb, ev_ebitda, percentile_5y); technical_state(isin, date, sma50, sma200, rsi14, pct_from_52w_high, atr)`

### 11. `valuation_vs_peers` — 4,013 posts (3.4% of kept)

- Entity focus: stock/peers; answerable today: **partial**.
- e.g. “Is this stock expensive compared with its peers?”
- e.g. “Why does it trade at a higher PE than the sector?”
- e.g. “Which of the two is cheaper on EV/EBITDA?”
- Schema: `valuation_asof(isin, date, mcap, pe, pb, ev_ebitda, dividend_yield); peer_set(isin, peer_isin, basis, valid_from, valid_to)`

### 12. `global_cue_overnight` — 3,538 posts (3.0% of kept)

- Entity focus: macro/market-wide; answerable today: **partial**.
- e.g. “US markets fell overnight. How will Nifty open?”
- e.g. “Does a Fed decision move my Indian stock next day?”
- e.g. “Crude spiked overnight. Which sectors get hit at open?”
- Schema: `global_cue(date_ist, series, value, pct_change, source); market_open_gap(index_code, date, prev_close, open, gap_pct)`

### 13. `dividend_record_date` — 3,186 posts (2.7% of kept)

- Entity focus: stock; answerable today: **yes**.
- e.g. “Do I get the dividend if I buy before the record date?”
- e.g. “What happens to my shares on the ex-dividend date?”
- e.g. “Is the dividend yield worth holding for?”
- Schema: `corporate_action covers ex/record dates; missing dividend_detail(isin, announce_date, ex_date, amount_per_share, type, fy)`

### 14. `penny_low_price_stock` — 2,946 posts (2.5% of kept)

- Entity focus: stock; answerable today: **partial**.
- e.g. “Which low-price stocks can double from here?”
- e.g. “Is a ten-rupee stock cheaper than a thousand-rupee stock?”
- e.g. “Are micro-caps with no earnings worth the risk?”
- Schema: `price + master_companies market_cap_tier cover the universe; missing liquidity_floor(isin, date, median_turnover_20d, impact_cost_bps)`

### 15. `corporate_action_aftermath` — 2,846 posts (2.4% of kept)

- Entity focus: stock; answerable today: **yes**.
- e.g. “What happens to my shares after the demerger?”
- e.g. “How does the buyback affect my cost basis?”
- e.g. “Should I tender in the OFS or sell in the market?”
- Schema: `corporate_action(isin, ex_date, record_date, kind, ratio_num, ratio_den, price_inr, size_cr, source_ref); corporate_action_effect(isin, action_id, pre_price, post_price, adjustment_factor)`

### 16. `ta_breakout_volume` — 2,169 posts (1.9% of kept)

- Entity focus: stock/technical; answerable today: **yes**.
- e.g. “Was the breakout confirmed by volume and delivery?”
- e.g. “Is a low-volume breakout likely to fail?”
- e.g. “How much delivery should a real breakout show?”
- Schema: `price, volume and delivery are held; needed breakout_event(isin, date, level, close_vs_level_pct, volume_ratio_20d, delivery_ratio_20d)`

### 17. `ta_rsi_momentum` — 1,917 posts (1.6% of kept)

- Entity focus: stock/technical; answerable today: **yes**.
- e.g. “RSI is oversold. Is this a buy in an uptrend?”
- e.g. “Can a stock stay overbought for weeks?”
- e.g. “Does RSI divergence actually predict a reversal?”
- Schema: `RSI14 derived today; needed indicator_state(isin, date, rsi14, rsi_zone, divergence_kind) with the exact formula/version`

### 18. `guidance_vs_delivery` — 1,830 posts (1.6% of kept)

- Entity focus: stock; answerable today: **partial**.
- e.g. “Management promised this last year. Did they deliver?”
- e.g. “Which guidance has been cut twice already?”
- e.g. “Is the current guidance credible after the miss?”
- Schema: `guidance_item(isin, doc_id, metric, period, value_low, value_high, unit, statement_date); guidance_delivery(guidance_id, actual_fact_id, surprise_pct)`

### 19. `sebi_rule_question` — 1,457 posts (1.2% of kept)

- Entity focus: policy; answerable today: **partial**.
- e.g. “Which SEBI rule applies to this preferential issue?”
- e.g. “Was this disclosure late under LODR?”
- e.g. “What does the regulator's order actually ban?”
- Schema: `sebi_rule(rule_id, title, instrument, stage, effective_date, summary, url); sebi_rule_company(rule_id, isin, direction, materiality)`

### 20. `macro_event_what_if` — 1,121 posts (1.0% of kept)

- Entity focus: macro/policy; answerable today: **partial**.
- e.g. “If the RBI cuts rates, which stocks benefit first?”
- e.g. “What does a tariff change do to my sector?”
- e.g. “Budget day: buy before or after the speech?”
- Schema: `macro_event + ripple_effects exist; missing scenario table(scenario_id, assumption_json, asof, affected_isin, delta_revenue_pct, delta_margin_bps)`

### 21. `cycle_peak_trough` — 1,098 posts (0.9% of kept)

- Entity focus: sector/stock; answerable today: **no**.
- e.g. “Where are we in the steel cycle right now?”
- e.g. “Is the cement downcycle over?”
- e.g. “How much of the margin is cycle versus company?”
- Schema: `needs cycle_state(sector_id, month, phase, spread_pct, inventory_days, capacity_utilisation) derived from prices + filings`

### 22. `ta_52week_extreme` — 914 posts (0.8% of kept)

- Entity focus: stock/technical; answerable today: **yes**.
- e.g. “It is near its 52-week high. Buy or wait?”
- e.g. “How often does a 52-week-high breakout hold?”
- e.g. “How long does a 15% drawdown take to recover?”
- Schema: `daily_price_delivery has 52w high/low; needed pct_from_52w_high, days_since_52w_extreme, and index-relative version`

### 23. `ta_gap_event` — 886 posts (0.8% of kept)

- Entity focus: stock/technical; answerable today: **yes**.
- e.g. “Did the result gap fill, and how long did it take?”
- e.g. “Is an opening gap up a trap?”
- e.g. “Does a gap down act as resistance later?”
- Schema: `needs gap_event(isin, date, prev_close, open, gap_pct, filled, fill_date)`

### 24. `why_stock_moved` — 869 posts (0.7% of kept)

- Entity focus: stock/index; answerable today: **partial**.
- e.g. “Why did this stock fall 8% today?”
- e.g. “The result beat. Why did the stock still fall?”
- e.g. “Was the move company-specific or the whole sector?”
- Schema: `move_attributor exists in processing; no served table. Needed: move_attribution(isin, date, return_pct, attributed_kind, evidence_id, known_at, confidence)`

### 25. `fii_dii_flow_link` — 740 posts (0.6% of kept)

- Entity focus: market-wide/stock; answerable today: **partial**.
- e.g. “Did FII selling cause this stock's fall?”
- e.g. “Are DIIs absorbing the FII selling?”
- e.g. “How do I see FII flow for one stock?”
- Schema: `fii_dii_cash exists daily; missing fii_dii_stock(isin, date, fii_net_inr, dii_net_inr) and flow_attribution(isin, date, flow_inr, price_effect)`

### 26. `ta_delivery_spike` — 728 posts (0.6% of kept)

- Entity focus: stock/technical; answerable today: **yes**.
- e.g. “Was the delivery spike accumulation or a block deal?”
- e.g. “Why is delivery 60% today?”
- e.g. “Does high delivery at a high mean more upside?”
- Schema: `delivery_qty/delivery_pct held per exchange; needed delivery_spike(isin, date, delivery_pct, zscore_60d, value_inr) and a cash-vs-F&O split`

### 27. `promoter_pledge_sale` — 600 posts (0.5% of kept)

- Entity focus: stock; answerable today: **partial**.
- e.g. “Is promoter pledge rising with the debt?”
- e.g. “Did the promoter sell before the bad quarter?”
- e.g. “How much of the float did the block deal absorb?”
- Schema: `shareholding exists; missing pledge_history(isin, quarter_end, pledged_pct, encumbered_pct) and deal_print(isin, date, side, qty, price, client_type)`

### 28. `circuit_band_behaviour` — 535 posts (0.5% of kept)

- Entity focus: stock; answerable today: **yes**.
- e.g. “Why is it stuck in the upper circuit?”
- e.g. “When will the circuit open so I can sell?”
- e.g. “Did the band change after the base-price reset?”
- Schema: `price_bands exists daily (date, symbol, series, band_pct); missing circuit_event(isin, date, direction, band_pct, open, close, volume_multiple)`

### 29. `ta_oi_pcr_maxpain` — 533 posts (0.5% of kept)

- Entity focus: stock/derivative; answerable today: **no**.
- e.g. “What is the PCR, and does it mark a bottom?”
- e.g. “Where is max pain into expiry?”
- e.g. “Is the OI build-up longs or shorts?”
- Schema: `no daily OI/PCR table; needed fno_oi(isin, date, expiry, strike, option_type, oi, oi_change, volume, iv); pcr_daily(index_code, date, pcr_oi, pcr_volume); max_pain(index_code, expiry, date, strike)`

### 30. `moat_competitive_advantage` — 532 posts (0.5% of kept)

- Entity focus: stock; answerable today: **partial**.
- e.g. “What protects this business from competition?”
- e.g. “Is the pricing power real or cyclical?”
- e.g. “Would a new entrant take share in five years?”
- Schema: `moat_evaluations(substrate) exists; no served per-company moat table with evidence. Needed: moat_score(isin, asof, width, trajectory, sc, ne, ca, ia, es, evidence_ids)`

## 5. Technical patterns: data needed and point-in-time status

| pattern | price / volume / delivery / OI / band needed | held PIT? |
|---|---|---|
| support / resistance | daily OHLCV + swing pivots + volume | yes (dated rows); levels derived, not stored |
| breakout with volume | close vs level, volume/20d median, delivery % | yes |
| moving average / cross | SMA20/50/200 from dated rows | yes |
| RSI setup | RSI14 per dated row | yes |
| 52-week high/low | 52w columns per dated row | yes |
| gap up/down | prev close, open, low, next sessions | yes |
| relative strength vs index | stock return vs Nifty close | partial: Nifty only, no sector indices |
| F&O OI build-up | daily OI by strike/expiry, rollover, basis | no table |
| PCR / max pain | option chain OI, expiry closes | no table |
| delivery spike | delivery qty/%, volume, band state | yes |
| circuit / band behaviour | price_bands + OHLCV + delivery | yes |
| chart patterns | labelled windows (flag, triangle, H&S) | no table |

Raw OHLCV, volume, delivery, 52-week and band rows are dated and PIT-safe. Derived columns (SMA/RSI) are stored per dated row, so an as-of question must read the row for that date, never today's column. OI, PCR, max pain, rollover and chart patterns are NOT IN DATA; those questions are in the bank with `coverage.verdict = no`.

## 6. International value patterns, translated

| pattern from value/fundamentals subs | Indian translation used in the bank |
|---|---|
| moat durability | margin stability through a crude cycle; volume vs price |
| ROIC vs WACC | segment capital employed; through-cycle spread |
| capital allocation | cash returned vs retained; incremental return |
| accounting red flags | receivables/inventory days, CFO/PAT, notes |
| management credibility | dated guidance vs delivered number |
| unit economics | per-order or per-store contribution margin |
| cycle position | margin vs last peak; cost-curve claim |
| second-order macro | rate/crude/FX -> margin with a stated lag |
| reinvestment runway | capex per rupee of new revenue; project dates |
| balance-sheet stress | maturity wall, coverage, funding gap |
| earnings quality | accruals, DSO, capitalised cost |
| sum of parts / holdco | listed stakes at market, net debt, discount |
| dividend sustainability | FCF cover after maintenance capex |
| customer concentration | top-client share and revenue at risk |
| thesis break | explicit falsifier instead of a price target |

## 7. Aliases

`aliases.csv` lists every alias with frequency >= 20, the resolved symbol/ISIN, and whether `reality-data.resolve` returns an active equity today (48 rows).

| alias | target | resolves | frequency |
|---|---|---|---:|
| Nifty | NIFTY50_INDEX | wrong_kind | 6,120 |
| HDFC | HDFCBANK | delisted_only | 2,383 |
| Nifty 50 | NIFTY50_INDEX | wrong_kind | 2,171 |
| ICICI | ICICIBANK | yes | 1,677 |
| SBI | SBIN | yes | 1,473 |
| Groww | GROWW | yes | 1,445 |
| Zerodha | ZERODHA | wrong_kind | 1,352 |
| Sensex | SENSEX_INDEX | wrong_kind | 834 |
| Reliance | RELIANCE | yes | 802 |
| Kotak | KOTAKBANK | yes | 676 |
| Axis | AXISBANK | yes | 608 |
| Tata Motors | TATAMOTORS | yes | 570 |
| Zomato | ETERNAL | yes | 556 |
| TCS | TCS | yes | 433 |
| HDFC Bank | HDFCBANK | yes | 420 |

Failures today (the trader's word does not land on a live ISIN):

| alias | target | resolves | note | frequency |
|---|---|---|---|---:|
| Nifty | NIFTY50_INDEX | wrong_kind | index, not a company | 6,120 |
| HDFC | HDFCBANK | delisted_only | Housing Development Finance Corp.Lt; last trade 2023-07-12 | 2,383 |
| Nifty 50 | NIFTY50_INDEX | wrong_kind | index, not a company | 2,171 |
| Zerodha | ZERODHA | wrong_kind | unlisted broker | 1,352 |
| Sensex | SENSEX_INDEX | wrong_kind | index, not a company | 834 |
| Bank Nifty | BANKNIFTY_INDEX | no | index, not a company | 305 |
| defence stocks | DEFENCE_THEME | no | theme basket, no ISIN | 148 |
| Adani stocks | ADANI_GROUP | no | group basket, no single ISIN | 115 |
| railway stocks | RAILWAY_THEME | no | theme basket, no ISIN | 79 |
| PSU stocks | PSU_BASKET | no | theme basket, no ISIN | 76 |

## 8. Time-phrase dictionary

Phrases are stored verbatim in the raw posts (not reproduced here); this is the canonical form the miner matches and its frequency.

| canonical | surface forms | posts |
|---|---|---:|
| long term | long term / 5-10 years / decade | 10,512 |
| today | today / aaj / intraday | 8,016 |
| tomorrow | tomorrow / kal / next session | 1,822 |
| this year | this year / current year | 1,416 |
| last year | last / past year | 1,371 |
| yesterday | yesterday / kal | 1,087 |
| expiry | expiry / expiration | 849 |
| this week | this week | 622 |
| last week | last week | 460 |
| this month | this month | 451 |
| 52-week | 52-week | 320 |
| next week | next week | 298 |
| YTD | YTD / year to date | 200 |
| QnFYxx | Q1FY26 … Q4FY27 | 188 |
| after results | after / post results | 165 |
| after budget | post-budget / after the budget | 125 |
| at open | at / on market open | 105 |
| this quarter | this quarter / current quarter | 101 |
| after election | after / since / post election | 78 |
| before budget | pre-budget | 77 |
| since listing | since IPO / listing | 59 |
| since 2024 | since 2024 | 32 |
| next quarter | next quarter / next Qn | 27 |
| after rate cut | after rate cut / RBI decision / Fed | 15 |

## 9. The bank

- `QUESTION_BANK_REDDIT_2026-10-28.jsonl`: 200 rows (indian 75, international 75, technical 50); unique qids; every entity resolves to an active ISIN in `master_companies`.
- Coverage verdicts: no 10, partial 154, yes 36.
- Each row carries the open-bank fields (`family`, `rubric`, `coverage`, `why`) plus `reddit_pattern` and `group`.
- New patterns covered by the bank: group/basket, grey-market IPO and listing day, entry timing, corporate-action aftermath (demerger/buyback/OFS), SEBI rules, F&O vs cash, overnight global cues, position decisions, plus the 15 translated value patterns and 10 technical setups.

## 10. Reproduce

```bash
python tasks/reddit_mining/mine.py --samples   # aggregates -> work/, patterns.csv
python tasks/reddit_mining/aliases.py          # resolve check -> aliases.csv
python tasks/reddit_mining/build_bank.py       # validate -> jsonl + md
python tasks/reddit_mining/check_leak.py       # 10-word overlap check
python tasks/reddit_mining/write_report.py     # this report
```

