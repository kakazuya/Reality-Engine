# Gap roll-up - every named gap, deduplicated and ranked

Built by `tasks/master_bank/build_master_bank.py` from the three registries: G0-G12 (`BACKWARD_REQUIREMENTS_AUDIT_2026-10-27_REPORT.md` §10), NG01-NG29 (`QUESTION_BANK_OPEN_2026-10-27.jsonl` + the open-bank builder) and the 41 schema proposals (`tasks/ripple_bank/_lib.py`). Identity clusters are listed per gap; overlap that is only a dependency (for example G11's XBRL concept map feeding several derived tables) is not treated as a duplicate.

Ranking: unique master cases blocked per build day. `closable from held data` is **yes** (only parsing/mapping of held rows), **partial** (some held, some missing) or **no**; the `path` column then says `new fetch` or `NOT IN DATA`. Effort is the larger of the proposal-table sum and the audit estimate, so a cluster of four series tables is not ranked as one.

A ripple proposal whose source is held filing/text (AR, concall, deck, XBRL, PIB, insider/deal tape) counts as partial / build-from-held even when its derived table was never fetched; external-only series (LME, IMD, customs, Vahan, agency releases, paid consensus) stay `new fetch`.

## 1. Summary

- named gaps in the registries: **83** (13 G + 29 NG + 41 proposals)
- identity clusters after the merge: **58**
- cases blocked by at least one gap: **592** of 830; cases with no gap named: **238**

## 2. Held-data probes (read-only, bounded)

| probe | result |
| --- | --- |
| annual_fy26 | annual_financials FY26: 3,245 rows / 840 with null interest_coverage |
| commodity | mkt_commodity_daily: 25,255 rows / 13 commodity series / 2019-01-01..2026-10-06, known_at column: no |
| concall_docs | corporate_documents: 20,151 processed concall docs |
| delivery_tape | daily_price_delivery max date: 2026-10-23 |
| etf_master | etf_master: 432 rows |
| etf_px | etf_px: 315,259 rows |
| fii_dii | mkt_fii_dii_cash: 1,935 rows / 2019-01-01..2026-10-23 |
| geographic | geographic_exposure: 3,568 rows (undated, company_id-keyed) |
| index_membership | index_membership: 300 rows / 1 distinct as_of |
| insider | insider_trades_v2: 333,712 rows |
| macro | macro_events: 30 rows / 24 with doc_id |
| non_ine | master_companies: 397 non-INE rows (ETFs/other) |
| policy_events | policy_events: 21,552 rows / 20,970 quote_ok |
| price_bands | price_bands: 1,054,354 rows / 538 distinct dates / 2019-12-30..2026-09-22 |
| shareholding | shareholding: 40 rows / 12 quarter-ends (stub) |
| taxonomies | results_xbrl.filings taxonomies: INDAS=69,520, INTEGRATED=30,227, NBFC=3,903, NONINDAS=1,576 |

## 3. Ranked gaps

| # | gap | cases | effort d | cases/day | closable | path | members |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | G11 | 43 | 1.0 | 43.0 | yes | build from held data | G11 |
| 2 | metric_series | 62 | 2.0 | 31.0 | partial | build from held data | metric_series |
| 3 | NG27 | 24 | 1.0 | 24.0 | no | new fetch | NG27, day0_session |
| 4 | segment_pnl | 41 | 2.5 | 16.4 | partial | build from held data | segment_pnl |
| 5 | NG28 | 23 | 1.5 | 15.3 | partial | build from held data | NG28, leakage_window |
| 6 | G10 | 63 | 5.0 | 12.6 | partial | build from held data | G10, policy_target |
| 7 | working_capital | 25 | 2.0 | 12.5 | partial | build from held data | working_capital |
| 8 | price_revision | 33 | 3.0 | 11.0 | partial | build from held data | price_revision |
| 9 | G2 | 15 | 1.5 | 10.0 | no | new fetch | G2 |
| 10 | G4 | 4 | 0.5 | 8.0 | partial | new fetch | G4 |
| 11 | NG12 | 55 | 8.0 | 6.9 | partial | build from held data | NG12, capacity_util, capex_project |
| 12 | G6 | 54 | 8.0 | 6.8 | partial | new fetch | G6, NG29 |
| 13 | debt_mix | 20 | 3.0 | 6.7 | partial | build from held data | debt_mix |
| 14 | NG15 | 25 | 4.0 | 6.2 | partial | build from held data | NG15, order_intake |
| 15 | G12 | 79 | 13.0 | 6.1 | no | new fetch | G12, NG11, commodity_series, freight_series, rainfall (+1) |
| 16 | NG10 | 67 | 12.0 | 5.6 | partial | build from held data | NG10, cost_structure, import_content, fx_exposure, cost_geo |
| 17 | G1 | 16 | 3.0 | 5.3 | partial | build from held data | G1, mcap_state |
| 18 | NG21 | 9 | 2.0 | 4.5 | partial | build from held data | NG21, event_calendar |
| 19 | NG25 | 22 | 5.0 | 4.4 | partial | build from held data | NG25, order_contract |
| 20 | NG08 | 13 | 3.0 | 4.3 | no | new fetch | NG08, rating_action |
| 21 | G0 | 8 | 2.0 | 4.0 | yes | build from held data | G0 |
| 22 | revenue_geo_period | 6 | 1.5 | 4.0 | partial | build from held data | revenue_geo_period |
| 23 | NG14 | 15 | 4.0 | 3.8 | no | new fetch | NG14, capacity_pipeline |
| 24 | share_shift | 12 | 4.0 | 3.0 | no | new fetch | share_shift |
| 25 | NG18 | 8 | 3.0 | 2.7 | partial | build from held data | NG18, sector_flow |
| 26 | NG07 | 5 | 2.0 | 2.5 | partial | build from held data | NG07, pledge_event |
| 27 | NG22 | 12 | 5.0 | 2.4 | no | new fetch | NG22, supply_link |
| 28 | NG09 | 13 | 6.0 | 2.2 | no | new fetch | NG09, fund_raise, fund_use |
| 29 | tariff_exposure | 10 | 5.0 | 2.0 | no | new fetch | tariff_exposure |
| 30 | G8 | 1 | 0.5 | 2.0 | no | new fetch | G8 |
| 31 | deposit_rate | 5 | 3.0 | 1.7 | partial | build from held data | deposit_rate |
| 32 | duty_structure | 5 | 3.0 | 1.7 | no | new fetch | duty_structure |
| 33 | loan_repricing | 6 | 4.0 | 1.5 | partial | build from held data | loan_repricing |
| 34 | interest_cover | 2 | 1.5 | 1.3 | partial | build from held data | interest_cover |
| 35 | NG26 | 4 | 4.0 | 1.0 | partial | build from held data | NG26, subsidy_register |
| 36 | competitor_action | 3 | 3.0 | 1.0 | partial | build from held data | competitor_action |
| 37 | transit_days | 3 | 3.0 | 1.0 | no | new fetch | transit_days |
| 38 | G5 | 1 | 1.0 | 1.0 | yes | build from held data | G5, NG20 |
| 39 | NG24 | 3 | 4.0 | 0.8 | partial | build from held data | NG24, guidance_actual |
| 40 | pass_through | 2 | 3.0 | 0.7 | partial | build from held data | pass_through |
| 41 | G3 | 0 | 1.0 | - | no | new fetch | G3 |
| 42 | G7 | 0 | 3.0 | - | partial | build from held data | G7 |
| 43 | U-DOC | 38 | - | - | no | NOT IN DATA | U-DOC |
| 44 | NG13 | 15 | - | - | partial | build from held data | NG13 |
| 45 | NG02 | 10 | - | - | partial | build from held data | NG02 |
| 46 | G9 | 8 | - | - | no | new fetch | G9 |
| 47 | NG01 | 8 | - | - | partial | build from held data | NG01 |
| 48 | U-REFURB | 8 | - | - | no | new fetch | U-REFURB |
| 49 | U-STORE | 8 | - | - | no | new fetch | U-STORE |
| 50 | NG05 | 5 | - | - | no | new fetch | NG05 |
| 51 | U-OTHER | 5 | - | - | no | new fetch | U-OTHER |
| 52 | NG03 | 3 | - | - | no | new fetch | NG03 |
| 53 | NG04 | 3 | - | - | partial | build from held data | NG04 |
| 54 | NG16 | 3 | - | - | no | new fetch | NG16 |
| 55 | NG06 | 2 | - | - | yes | build from held data | NG06 |
| 56 | NG23 | 2 | - | - | partial | build from held data | NG23 |
| 57 | NG17 | 1 | - | - | no | new fetch | NG17 |
| 58 | NG19 | 1 | - | - | no | NOT IN DATA | NG19 |

## 4. Every gap: the cases it blocks and what would close it

### 1. G11 - XBRL concept map per taxonomy (Ind AS / banking / NBFC / insurance) + segment contexts

- members: G11
- cases blocked: **43** - MB0006, MB0007, MB0052, MB0054, MB0056, MB0060, MB0083, MB0085, MB0088, MB0090, MB0100, MB0365, MB0371, MB0372, MB0407, MB0408, MB0411, MB0412, MB0413, MB0447, MB0453, MB0472, MB0476, MB0477, MB0479, MB0483, MB0488, MB0490, MB0526, MB0527, MB0532, MB0533, MB0540, MB0553, MB0557, MB0559, MB0560, MB0562, MB0564, MB0566, MB0567, MB0568, MB0570
- closable from held data: **yes**; path: build from held data
- held evidence: local: `results_xbrl.facts`
- effort: 1.0 days
- probe: results_xbrl.filings taxonomies: INDAS=69,520, INTEGRATED=30,227, NBFC=3,903, NONINDAS=1,576

### 2. metric_series - quarterly_financials holds 15,173 rows against 45,517 FY25+ XBRL filings and stops at 2026-06-30; a hop on a...

- members: metric_series
- cases blocked: **62** - MB0632, MB0636, MB0637, MB0640, MB0651, MB0655, MB0656, MB0662, MB0666, MB0670, MB0672, MB0679, MB0681, MB0682, MB0685, MB0687, MB0689, MB0690, MB0692, MB0694, MB0703, MB0707, MB0710, MB0715, MB0725, MB0726, MB0734, MB0736, MB0739, MB0740, MB0746, MB0751, MB0752, MB0755, MB0756, MB0757, MB0758, MB0759, MB0761, MB0762, MB0763, MB0766, MB0767, MB0768, MB0770, MB0772, MB0773, MB0778, MB0779, MB0782, MB0786, MB0787, MB0793, MB0796, MB0797, MB0800, MB0801, MB0803, MB0805, MB0808, MB0809, MB0810
- closable from held data: **partial**; path: build from held data
- held evidence: XBRL + results notes, full universe -> company_metric_series
- effort: 2.0 days

### 3. NG27 - no intraday bars, so intraday-filing event windows cannot be measured

- members: NG27, day0_session
- cases blocked: **24** - MB0444, MB0589, MB0594, MB0743, MB0811, MB0812, MB0813, MB0814, MB0815, MB0816, MB0817, MB0818, MB0819, MB0820, MB0821, MB0822, MB0823, MB0824, MB0825, MB0826, MB0827, MB0828, MB0829, MB0830
- closable from held data: **no**; path: new fetch
- held evidence: no intraday bars are held; intraday-filing windows cannot be measured; known_at from every store, mapped to the trading calendar -> event_day0
- effort: 1.0 days

### 4. segment_pnl - Segment contexts in XBRL are unmapped, which is why a segment number cannot be read for most filings.

- members: segment_pnl
- cases blocked: **41** - MB0640, MB0648, MB0652, MB0658, MB0662, MB0665, MB0671, MB0672, MB0677, MB0678, MB0681, MB0690, MB0705, MB0712, MB0714, MB0719, MB0720, MB0724, MB0729, MB0753, MB0754, MB0765, MB0772, MB0774, MB0775, MB0776, MB0777, MB0778, MB0779, MB0780, MB0783, MB0784, MB0785, MB0786, MB0788, MB0789, MB0790, MB0799, MB0804, MB0805, MB0809
- closable from held data: **partial**; path: build from held data
- held evidence: XBRL segment contexts + AR segment note -> company_segment_pnl
- effort: 2.5 days

### 5. NG28 - no event-study harness (price x delivery x filing) with a volatility normaliser

- members: NG28, leakage_window
- cases blocked: **23** - MB0432, MB0583, MB0600, MB0811, MB0812, MB0813, MB0814, MB0815, MB0816, MB0817, MB0818, MB0819, MB0820, MB0821, MB0822, MB0823, MB0824, MB0825, MB0826, MB0827, MB0828, MB0829, MB0830
- closable from held data: **partial**; path: build from held data
- held evidence: prices, delivery and filing timestamps are all held; only the event-study harness is missing; daily_price_delivery + insider_trades_v2 + bulk_block_deals -> event_leakage_window
- effort: 1.5 days
- probe: daily_price_delivery max date: 2026-10-23

### 6. G10 - macro claim targets

- members: G10, policy_target
- cases blocked: **63** - MB0016, MB0017, MB0131, MB0132, MB0133, MB0134, MB0135, MB0136, MB0137, MB0138, MB0182, MB0189, MB0192, MB0209, MB0221, MB0222, MB0223, MB0224, MB0225, MB0226, MB0227, MB0228, MB0229, MB0230, MB0428, MB0463, MB0470, MB0473, MB0496, MB0498, MB0500, MB0503, MB0504, MB0507, MB0508, MB0510, MB0513, MB0525, MB0603, MB0607, MB0608, MB0609, MB0614, MB0620, MB0630, MB0650, MB0651, MB0658, MB0661, MB0662, MB0663, MB0664, MB0665, MB0668, MB0669, MB0670, MB0679, MB0680, MB0698, MB0720, MB0758, MB0774, MB0785
- closable from held data: **partial**; path: build from held data
- held evidence: local text (`pib_releases.body`); PIB/budget/RBI text + the company's own disclosure of the scheme -> policy_company_exposure
- effort: 5.0 days
- probe: policy_events: 21,552 rows / 20,970 quote_ok | macro_events: 30 rows / 24 with doc_id

### 7. working_capital - The XBRL facts exist and are unmapped; annual_financials holds only OCF, never days.

- members: working_capital
- cases blocked: **25** - MB0636, MB0638, MB0640, MB0654, MB0659, MB0664, MB0665, MB0668, MB0669, MB0679, MB0684, MB0686, MB0689, MB0691, MB0707, MB0714, MB0759, MB0760, MB0764, MB0768, MB0773, MB0792, MB0798, MB0799, MB0807
- closable from held data: **partial**; path: build from held data
- held evidence: XBRL trade receivables/inventory/payables + AR schedule -> company_working_capital
- effort: 2.0 days

### 8. price_revision - A price hike is announced in several calls in several words; without this you cannot date the hike or size it.

- members: price_revision
- cases blocked: **33** - MB0631, MB0635, MB0636, MB0637, MB0639, MB0641, MB0643, MB0644, MB0646, MB0649, MB0656, MB0682, MB0687, MB0703, MB0706, MB0708, MB0712, MB0713, MB0715, MB0717, MB0718, MB0719, MB0725, MB0727, MB0728, MB0730, MB0752, MB0767, MB0773, MB0777, MB0778, MB0787, MB0791
- closable from held data: **partial**; path: build from held data
- held evidence: concall/deck/AR price-hike statements -> company_price_revision
- effort: 3.0 days

### 9. G2 - index membership history

- members: G2
- cases blocked: **15** - MB0038, MB0048, MB0078, MB0098, MB0158, MB0188, MB0208, MB0238, MB0258, MB0268, MB0288, MB0308, MB0318, MB0580, MB0619
- closable from held data: **no**; path: new fetch
- held evidence: NSE circulars
- effort: 1.5 days
- probe: index_membership: 300 rows / 1 distinct as_of

### 10. G4 - sector/industry PIT

- members: G4
- cases blocked: **4** - MB0012, MB0019, MB0424, MB0581
- closable from held data: **partial**; path: new fetch
- held evidence: local + BSE scrip master
- effort: 0.5 days

### 11. NG12 - no capacity / utilisation / production time series

- members: NG12, capacity_util, capex_project
- cases blocked: **55** - MB0337, MB0344, MB0345, MB0350, MB0355, MB0374, MB0415, MB0462, MB0487, MB0493, MB0501, MB0502, MB0535, MB0538, MB0633, MB0639, MB0642, MB0645, MB0646, MB0649, MB0651, MB0652, MB0653, MB0654, MB0657, MB0659, MB0663, MB0669, MB0691, MB0693, MB0694, MB0695, MB0697, MB0698, MB0699, MB0700, MB0701, MB0704, MB0711, MB0713, MB0718, MB0721, MB0722, MB0724, MB0725, MB0728, MB0735, MB0737, MB0739, MB0749, MB0750, MB0761, MB0763, MB0789, MB0805
- closable from held data: **partial**; path: build from held data
- held evidence: capacity/utilisation statements sit in concall, deck and AR text; AR capacity note + concall utilisation statements -> company_capacity_utilisation; concall capacity statements + deck + AR MD&A -> capex_project
- effort: 8.0 days

### 12. G6 - layer-1 v3 chunk tags (`known_at`, `section`, `speaker_role`, `content_tags`, `forward_looking`,...

- members: G6, NG29
- cases blocked: **54** - MB0005, MB0029, MB0080, MB0216, MB0219, MB0300, MB0330, MB0349, MB0361, MB0362, MB0363, MB0364, MB0366, MB0367, MB0368, MB0373, MB0375, MB0385, MB0388, MB0414, MB0430, MB0452, MB0465, MB0486, MB0511, MB0512, MB0514, MB0515, MB0516, MB0517, MB0518, MB0519, MB0523, MB0524, MB0534, MB0541, MB0542, MB0543, MB0544, MB0545, MB0546, MB0548, MB0549, MB0550, MB0551, MB0552, MB0554, MB0555, MB0561, MB0612, MB0618, MB0624, MB0625, MB0628
- closable from held data: **partial**; path: new fetch
- held evidence: local chunker_v2 + free models; demand commentary sits in concall/deck text; the cause tag does not
- effort: 8.0 days
- probe: corporate_documents: 20,151 processed concall docs

### 13. debt_mix - annual_financials gives total debt and one blended cover; it cannot say how much reprices next quarter.

- members: debt_mix
- cases blocked: **20** - MB0647, MB0655, MB0659, MB0666, MB0672, MB0676, MB0678, MB0680, MB0681, MB0683, MB0684, MB0686, MB0688, MB0736, MB0750, MB0754, MB0762, MB0764, MB0765, MB0769
- closable from held data: **partial**; path: build from held data
- held evidence: AR borrowing schedule, rating rationale -> company_debt_mix
- effort: 3.0 days

### 14. NG15 - no tender/award pipeline table

- members: NG15, order_intake
- cases blocked: **25** - MB0358, MB0547, MB0631, MB0634, MB0635, MB0648, MB0650, MB0652, MB0657, MB0659, MB0666, MB0667, MB0668, MB0680, MB0688, MB0722, MB0750, MB0759, MB0760, MB0766, MB0783, MB0794, MB0796, MB0808, MB0810
- closable from held data: **partial**; path: build from held data
- held evidence: tender/award pipeline sits in announcements and order-book commentary; concall order-book statement + deck -> order_intake
- effort: 4.0 days

### 15. G12 - dated macro/commodity series (crude, coal, tariff, FX, El Niño) with end dates

- members: G12, NG11, commodity_series, freight_series, rainfall, rural_wage
- cases blocked: **79** - MB0013, MB0015, MB0018, MB0160, MB0161, MB0163, MB0167, MB0171, MB0172, MB0173, MB0174, MB0176, MB0179, MB0202, MB0210, MB0359, MB0369, MB0431, MB0457, MB0458, MB0459, MB0601, MB0606, MB0613, MB0615, MB0632, MB0633, MB0634, MB0635, MB0636, MB0637, MB0638, MB0639, MB0640, MB0641, MB0642, MB0643, MB0644, MB0645, MB0647, MB0648, MB0649, MB0650, MB0670, MB0684, MB0687, MB0691, MB0692, MB0696, MB0697, MB0698, MB0702, MB0703, MB0705, MB0706, MB0707, MB0709, MB0716, MB0751, MB0752, MB0756, MB0757, MB0758, MB0768, MB0774, MB0776, MB0782, MB0787, MB0788, MB0791, MB0792, MB0794, MB0795, MB0797, MB0798, MB0800, MB0801, MB0806, MB0807
- closable from held data: **no**; path: new fetch
- held evidence: external series; mkt_commodity_daily holds 13 series to 2026-10-06 (no known_at); freight, rainfall and rural wage are not held; external: LME/MCX/crude/coal/rubber/cotton/steel HRC series -> commodity_price_daily; external: container/Baltic/WCI indices -> freight_rate_daily; external: IMD district rainfall -> rainfall_daily; MGNREGA MIS + labour bureau -> rural_wage_series
- effort: 13.0 days
- probe: mkt_commodity_daily: 25,255 rows / 13 commodity series / 2019-01-01..2026-10-06, known_at column: no

### 16. NG10 - no cost-share / geography / end-market / import-content table

- members: NG10, cost_structure, import_content, fx_exposure, cost_geo
- cases blocked: **67** - MB0451, MB0454, MB0455, MB0456, MB0461, MB0464, MB0466, MB0467, MB0468, MB0474, MB0475, MB0478, MB0480, MB0494, MB0497, MB0499, MB0505, MB0520, MB0602, MB0604, MB0605, MB0610, MB0611, MB0626, MB0631, MB0632, MB0641, MB0642, MB0643, MB0644, MB0645, MB0646, MB0649, MB0651, MB0661, MB0663, MB0667, MB0670, MB0673, MB0674, MB0675, MB0676, MB0685, MB0686, MB0690, MB0692, MB0696, MB0699, MB0702, MB0703, MB0705, MB0709, MB0710, MB0723, MB0727, MB0730, MB0755, MB0771, MB0776, MB0777, MB0779, MB0781, MB0782, MB0783, MB0784, MB0803, MB0806
- closable from held data: **partial**; path: build from held data
- held evidence: ar_facts raw-material notes + geographic_exposure (3,568 rows, undated) hold the inputs; no cost-share table; AR note on raw material consumption + segment note -> company_cost_structure; AR note (imported vs indigenous raw material), concall FX hedging comment -> company_import_content; AR FX note / hedging disclosure, concall hedging comment -> company_fx_exposure; AR note on manufacturing locat
- effort: 12.0 days

### 17. G1 - shares outstanding + daily market cap

- members: G1, mcap_state
- cases blocked: **16** - MB0004, MB0025, MB0660, MB0713, MB0730, MB0732, MB0733, MB0737, MB0738, MB0741, MB0742, MB0746, MB0747, MB0748, MB0749, MB0802
- closable from held data: **partial**; path: build from held data
- held evidence: local: `results_xbrl.facts`, `adj_factor_cum`, `px_daily`; XBRL paid-up/face x adj_factor_cum + index circulars -> company_state_daily
- effort: 3.0 days
- probe: results_xbrl.filings taxonomies: INDAS=69,520, INTEGRATED=30,227, NBFC=3,903, NONINDAS=1,576

### 18. NG21 - no macro-event calendar for elections, verdicts, geopolitical shocks

- members: NG21, event_calendar
- cases blocked: **9** - MB0421, MB0429, MB0440, MB0700, MB0726, MB0748, MB0793, MB0799, MB0810
- closable from held data: **partial**; path: build from held data
- held evidence: macro_events holds 30 rows (23 with doc_id); policy_events holds 21,552 rows (20,970 quote_ok); policy_events + PIB + exchange + external geopolitical record -> event_calendar
- effort: 2.0 days
- probe: macro_events: 30 rows / 24 with doc_id

### 19. NG25 - no contract / customer / order-to-revenue linkage

- members: NG25, order_contract
- cases blocked: **22** - MB0352, MB0353, MB0418, MB0631, MB0633, MB0634, MB0635, MB0642, MB0644, MB0650, MB0661, MB0667, MB0675, MB0683, MB0699, MB0702, MB0717, MB0721, MB0726, MB0756, MB0760, MB0788
- closable from held data: **partial**; path: build from held data
- held evidence: contract/customer/order-to-revenue linkage sits in announcement and call text; concall order-book tables, deck annexures, exchange order-win filings -> order_book_contract
- effort: 5.0 days

### 20. NG08 - enforcement / tax / rating events are not structured with amounts

- members: NG08, rating_action
- cases blocked: **13** - MB0398, MB0399, MB0409, MB0410, MB0688, MB0689, MB0732, MB0736, MB0739, MB0745, MB0747, MB0765, MB0769
- closable from held data: **no**; path: new fetch
- held evidence: enforcement / tax / rating items sit in bse_announcements headlines; no structured event table with amounts; exchange filings + agency press releases -> rating_action
- effort: 3.0 days

### 21. G0 - ISIN anchor is defective (83 false changes, 1,370 synthetic ISINs, 1,665 FY25+ ISINs absent from master,...

- members: G0
- cases blocked: **8** - MB0014, MB0162, MB0164, MB0165, MB0166, MB0168, MB0169, MB0170
- closable from held data: **yes**; path: build from held data
- held evidence: local: `px_bse`, `security_master`, `entity`, `corporate_actions`, `symbol_isin_history`
- effort: 2.0 days
- probe: etf_master: 432 rows | etf_px: 315,259 rows | master_companies: 397 non-INE rows (ETFs/other)

### 22. revenue_geo_period - geographic_exposure exists (3,568 rows, revenue_share_pct filled) but is company_id-keyed, undated and...

- members: revenue_geo_period
- cases blocked: **6** - MB0673, MB0674, MB0685, MB0755, MB0771, MB0781
- closable from held data: **partial**; path: build from held data
- held evidence: segment note (geographical) + deck -> company_revenue_geography
- effort: 1.5 days
- probe: geographic_exposure: 3,568 rows (undated, company_id-keyed)

### 23. NG14 - no licence / commissioning / JV-execution event register

- members: NG14, capacity_pipeline
- cases blocked: **15** - MB0336, MB0528, MB0529, MB0536, MB0537, MB0565, MB0641, MB0711, MB0712, MB0715, MB0716, MB0717, MB0727, MB0731, MB0735
- closable from held data: **no**; path: new fetch
- held evidence: licence/commissioning/JV events sit in announcements and call text; concall/deck capex announcements + PIB/state single-window approvals -> industry_capacity_pipeline
- effort: 4.0 days

### 24. share_shift - Share shift needs two companies' volumes on one product line; segment P&L and volume series are both missing.

- members: share_shift
- cases blocked: **12** - MB0639, MB0653, MB0654, MB0658, MB0678, MB0693, MB0695, MB0697, MB0700, MB0701, MB0708, MB0728
- closable from held data: **no**; path: new fetch
- held evidence: both companies' disclosed volumes + industry body data -> market_share_shift
- effort: 4.0 days

### 25. NG18 - no sector-level FII/DII flow split

- members: NG18, sector_flow
- cases blocked: **8** - MB0579, MB0660, MB0704, MB0733, MB0738, MB0740, MB0802, MB0808
- closable from held data: **partial**; path: build from held data
- held evidence: mkt_fii_dii_cash is market-wide only; the deal tape exists, the sector split does not; derived from FII/DII daily + holdings; sector attribution from the deal tape -> sector_flow_daily
- effort: 3.0 days
- probe: mkt_fii_dii_cash: 1,935 rows / 2019-01-01..2026-10-23

### 26. NG07 - pledge events carry no quantity or percentage

- members: NG07, pledge_event
- cases blocked: **5** - MB0406, MB0622, MB0732, MB0744, MB0745
- closable from held data: **partial**; path: build from held data
- held evidence: shareholding carries pledged % per quarter; the event-level quantity/percentage sits in announcement text; shareholding pattern (Reg-31) + exchange pledge disclosures -> promoter_pledge_event
- effort: 2.0 days
- probe: shareholding: 40 rows / 12 quarter-ends (stub)

### 27. NG22 - no map from unlisted / private layers to listed suppliers

- members: NG22, supply_link
- cases blocked: **12** - MB0506, MB0509, MB0521, MB0522, MB0633, MB0638, MB0653, MB0663, MB0683, MB0721, MB0722, MB0723
- closable from held data: **no**; path: new fetch
- held evidence: no map from unlisted/private layers to listed suppliers; DRHP and announcement text would have to be curated; AR related-party note + concall named suppliers -> supply_link
- effort: 5.0 days

### 28. NG09 - no QIP/IPO objects-versus-utilisation table

- members: NG09, fund_raise, fund_use
- cases blocked: **13** - MB0556, MB0569, MB0704, MB0708, MB0718, MB0731, MB0733, MB0737, MB0741, MB0748, MB0749, MB0763, MB0770
- closable from held data: **no**; path: new fetch
- held evidence: QIP/IPO objects and utilisation are in announcements and AR notes, not structured; board outcome + EGM notice + placement document -> fund_raise; quarterly monitoring report / annual-progress annexure -> fund_utilisation
- effort: 6.0 days

### 29. tariff_exposure - policy_events carries the rate as text ('50% since August 2025'); nothing maps a tariff to a company's...

- members: tariff_exposure
- cases blocked: **10** - MB0653, MB0654, MB0692, MB0694, MB0695, MB0701, MB0710, MB0766, MB0775, MB0789
- closable from held data: **no**; path: new fetch
- held evidence: US/EU customs schedules + company export disclosure -> tariff_exposure
- effort: 5.0 days

### 30. G8 - price band 2022-02-19→2026-09-14

- members: G8
- cases blocked: **1** - MB0416
- closable from held data: **no**; path: new fetch
- held evidence: NSE
- effort: 0.5 days
- probe: price_bands: 1,054,354 rows / 538 distinct dates / 2019-12-30..2026-09-22

### 31. deposit_rate - Term-deposit card rates are published but not harvested per bank per quarter.

- members: deposit_rate
- cases blocked: **5** - MB0655, MB0671, MB0677, MB0753, MB0793
- closable from held data: **partial**; path: build from held data
- held evidence: AR deposit schedule, quarterly deck -> bank_deposit_rate
- effort: 3.0 days

### 32. duty_structure - Duty changes sit in CBIC notifications as text; policy_events has the headline, not the HS line.

- members: duty_structure
- cases blocked: **5** - MB0652, MB0693, MB0716, MB0784, MB0798
- closable from held data: **no**; path: new fetch
- held evidence: customs notifications / CBIC -> import_duty_structure
- effort: 3.0 days

### 33. loan_repricing - Deposit-vs-loan repricing asymmetry is the whole NIM question; no table carries the loan-book repricing split.

- members: loan_repricing
- cases blocked: **6** - MB0655, MB0656, MB0657, MB0671, MB0753, MB0772
- closable from held data: **partial**; path: build from held data
- held evidence: AR Basel/Pillar 3 disclosures, concall NIM walk -> bank_loan_book_repricing
- effort: 4.0 days

### 34. interest_cover - annual_financials.interest_coverage has 0 rows below 2.5x across 3,245 FY26 rows, so the stored ratio cannot...

- members: interest_cover
- cases blocked: **2** - MB0647, MB0676
- closable from held data: **partial**; path: build from held data
- held evidence: XBRL finance cost + P&L, computed not copied -> company_interest_cover
- effort: 1.5 days
- probe: annual_financials FY26: 3,245 rows / 840 with null interest_coverage

### 35. NG26 - no policy-incentive expiry event tag

- members: NG26, subsidy_register
- cases blocked: **4** - MB0347, MB0723, MB0762, MB0780
- closable from held data: **partial**; path: build from held data
- held evidence: policy_events holds dates/amounts as text; incentive expiry is not a tagged event; PLI/scheme disbursement releases, company AR other income note -> subsidy_register
- effort: 4.0 days

### 36. competitor_action - A competitor's price cut is only ever described in prose; nothing dates it or links actor to target.

- members: competitor_action
- cases blocked: **3** - MB0711, MB0714, MB0780
- closable from held data: **partial**; path: build from held data
- held evidence: concall price-cut statements, deck, exchange filing -> competitor_action
- effort: 3.0 days

### 37. transit_days - Transit time is the hop that turns a route shock into inventory days; it is not held.

- members: transit_days
- cases blocked: **3** - MB0647, MB0764, MB0795
- closable from held data: **no**; path: new fetch
- held evidence: external: carrier schedules / port authority -> shipment_transit
- effort: 3.0 days

### 38. G5 - theme map

- members: G5, NG20
- cases blocked: **1** - MB0011
- closable from held data: **yes**; path: build from held data
- held evidence: local + curation; theme membership can be curated from master_companies + company_industry (sector/basic industry held)
- effort: 1.0 days

### 39. NG24 - guidance is not linked to the actual quarterly series

- members: NG24, guidance_actual
- cases blocked: **3** - MB0360, MB0531, MB0740
- closable from held data: **partial**; path: build from held data
- held evidence: concall_facts.cc_items guidance and results_xbrl actuals are both held; the link is missing; concall guidance + the later reported number -> guidance_vs_actual
- effort: 4.0 days

### 40. pass_through - The measured lag: regress the margin trough on the input shock across past cycles.

- members: pass_through
- cases blocked: **2** - MB0632, MB0751
- closable from held data: **partial**; path: build from held data
- held evidence: derived from quarterly results + the dated input series -> pass_through_history
- effort: 3.0 days

### 41. G3 - F&O history

- members: G3
- cases blocked: **0** (none in the banks yet)
- closable from held data: **no**; path: new fetch
- held evidence: NSE
- effort: 1.0 days

### 42. G7 - opinions DB

- members: G7
- cases blocked: **0** (none in the banks yet)
- closable from held data: **partial**; path: build from held data
- held evidence: local Drive/D: + Telegram
- effort: 3.0 days

### 43. U-DOC - no document exists for that entity/period in any held store

- members: U-DOC
- cases blocked: **38** - MB0044, MB0051, MB0053, MB0055, MB0057, MB0058, MB0061, MB0062, MB0063, MB0064, MB0065, MB0066, MB0067, MB0068, MB0069, MB0070, MB0072, MB0073, MB0074, MB0075, MB0076, MB0142, MB0143, MB0144, MB0145, MB0148, MB0150, MB0175, MB0177, MB0178, MB0243, MB0247, MB0257, MB0264, MB0292, MB0325, MB0326, MB0328
- closable from held data: **no**; path: NOT IN DATA
- held evidence: no document exists for that entity/period in any held store
- effort: not estimated

### 44. NG13 - no operating-metrics series (stores, orders, volumes, LTV)

- members: NG13
- cases blocked: **15** - MB0354, MB0356, MB0427, MB0460, MB0469, MB0471, MB0481, MB0482, MB0484, MB0485, MB0489, MB0491, MB0492, MB0495, MB0539
- closable from held data: **partial**; path: build from held data
- held evidence: stores/orders/volumes/LTV statements sit in concall and deck text
- effort: not estimated

### 45. NG02 - audit opinion detail (type / EOM / going-concern / KAM) is not extracted

- members: NG02
- cases blocked: **10** - MB0376, MB0377, MB0378, MB0383, MB0384, MB0386, MB0387, MB0389, MB0390, MB0417
- closable from held data: **partial**; path: build from held data
- held evidence: results_xbrl.filings.opinion carries the NSE declaration only; opinion type / EOM / KAM need a reader over held AR + results text
- effort: not estimated

### 46. G9 - results-notes backfill

- members: G9
- cases blocked: **8** - MB0009, MB0111, MB0112, MB0114, MB0115, MB0116, MB0118, MB0119
- closable from held data: **no**; path: new fetch
- held evidence: BSE
- effort: not estimated

### 47. NG01 - announcement attachments are not text-extracted

- members: NG01
- cases blocked: **8** - MB0381, MB0391, MB0405, MB0437, MB0438, MB0439, MB0598, MB0623
- closable from held data: **partial**; path: build from held data
- held evidence: bse_announcements.ann (1.9M rows) holds attachment names; announcement PDFs are not text-extracted into document_chunks
- effort: not estimated

### 48. U-REFURB - no refurbished / second-hand electronics sales series is held

- members: U-REFURB
- cases blocked: **8** - MB0191, MB0193, MB0194, MB0195, MB0196, MB0197, MB0198, MB0200
- closable from held data: **no**; path: new fetch
- held evidence: no refurbished / second-hand electronics sales series is held
- effort: not estimated

### 49. U-STORE - the entity has no rows in the store the template needs

- members: U-STORE
- cases blocked: **8** - MB0077, MB0128, MB0218, MB0248, MB0277, MB0278, MB0298, MB0327
- closable from held data: **no**; path: new fetch
- held evidence: the entity has no rows in the store the template needs
- effort: not estimated

### 50. NG05 - shareholding store is a 40-row stub (pledge/holder % unusable)

- members: NG05
- cases blocked: **5** - MB0395, MB0401, MB0577, MB0578, MB0621
- closable from held data: **no**; path: new fetch
- held evidence: equity_intelligence.shareholding is a 40-row stub; shp_index is the live PIT store
- effort: not estimated
- probe: shareholding: 40 rows / 12 quarter-ends (stub)

### 51. U-OTHER - unclassified coverage gap

- members: U-OTHER
- cases blocked: **5** - MB0120, MB0140, MB0190, MB0220, MB0240
- closable from held data: **no**; path: new fetch
- held evidence: unclassified coverage gap
- effort: not estimated

### 52. NG03 - no auditor-firm or parent-subsidiary entity resolution

- members: NG03
- cases blocked: **3** - MB0396, MB0404, MB0419
- closable from held data: **no**; path: new fetch
- held evidence: no entity table for audit firms or parent/subsidiary layers; names sit in ar_facts quotes and announcements
- effort: not estimated

### 53. NG04 - no KMP/board person-role-date table

- members: NG04
- cases blocked: **3** - MB0393, MB0394, MB0400
- closable from held data: **partial**; path: build from held data
- held evidence: board/KMP names sit in AR text and announcements; no person table
- effort: not estimated

### 54. NG16 - no consensus or target-price store

- members: NG16
- cases blocked: **3** - MB0445, MB0616, MB0627
- closable from held data: **no**; path: new fetch
- held evidence: no analyst consensus or target-price store; the source is paid
- effort: not estimated

### 55. NG06 - insider/SAST transaction store is empty

- members: NG06
- cases blocked: **2** - MB0402, MB0420
- closable from held data: **yes**; path: build from held data
- held evidence: insider_trades_v2 holds the NSE/BSE/SAST trade tape (333k rows per STATE 2026-10-24); the 'empty store' claim is stale
- effort: not estimated
- probe: insider_trades_v2: 333,712 rows

### 56. NG23 - dividend/buyback rows are not classified ordinary vs special

- members: NG23
- cases blocked: **2** - MB0370, MB0563
- closable from held data: **partial**; path: build from held data
- held evidence: dividend/buyback rows sit in corporate_actions and announcements; ordinary vs special is not tagged
- effort: not estimated

### 57. NG17 - no Vahan / EV-registration feed

- members: NG17
- cases blocked: **1** - MB0617
- closable from held data: **no**; path: new fetch
- held evidence: no Vahan / EV-registration feed is held
- effort: not estimated

### 58. NG19 - no investor-level holdings data

- members: NG19
- cases blocked: **1** - MB0629
- closable from held data: **no**; path: NOT IN DATA
- held evidence: investor-level holdings are not published for Indian listed stocks
- effort: not estimated

## 5. Cases with no gap named

MB0001, MB0002, MB0003, MB0008, MB0010, MB0020, MB0021, MB0022, MB0023, MB0024, MB0026, MB0027, MB0028, MB0030, MB0031, MB0032, MB0033, MB0034, MB0035, MB0036, MB0037, MB0039, MB0040, MB0041, MB0042, MB0043, MB0045, MB0046, MB0047, MB0049, MB0050, MB0059, MB0071, MB0079, MB0081, MB0082, MB0084, MB0086, MB0087, MB0089, MB0091, MB0092, MB0093, MB0094, MB0095, MB0096, MB0097, MB0099, MB0101, MB0102, MB0103, MB0104, MB0105, MB0106, MB0107, MB0108, MB0109, MB0110, MB0113, MB0117, MB0121, MB0122, MB0123, MB0124, MB0125, MB0126, MB0127, MB0129, MB0130, MB0139, MB0141, MB0146, MB0147, MB0149, MB0151, MB0152, MB0153, MB0154, MB0155, MB0156, MB0157, MB0159, MB0180, MB0181, MB0183, MB0184, MB0185, MB0186, MB0187, MB0199, MB0201, MB0203, MB0204, MB0205, MB0206, MB0207, MB0211, MB0212, MB0213, MB0214, MB0215, MB0217, MB0231, MB0232, MB0233, MB0234, MB0235, MB0236, MB0237, MB0239, MB0241, MB0242, MB0244, MB0245, MB0246, MB0249, MB0250, MB0251, MB0252, MB0253, MB0254, MB0255, MB0256, MB0259, MB0260, MB0261, MB0262, MB0263, MB0265, MB0266, MB0267, MB0269, MB0270, MB0271, MB0272, MB0273, MB0274, MB0275, MB0276, MB0279, MB0280, MB0281, MB0282, MB0283, MB0284, MB0285, MB0286, MB0287, MB0289, MB0290, MB0291, MB0293, MB0294, MB0295, MB0296, MB0297, MB0299, MB0301, MB0302, MB0303, MB0304, MB0305, MB0306, MB0307, MB0309, MB0310, MB0311, MB0312, MB0313, MB0314, MB0315, MB0316, MB0317, MB0319, MB0320, MB0321, MB0322, MB0323, MB0324, MB0329, MB0331, MB0332, MB0333, MB0334, MB0335, MB0338, MB0339, MB0340, MB0341, MB0342, MB0343, MB0346, MB0348, MB0351, MB0357, MB0379, MB0380, MB0382, MB0392, MB0397, MB0403, MB0422, MB0423, MB0425, MB0426, MB0433, MB0434, MB0435, MB0436, MB0441, MB0442, MB0443, MB0446, MB0448, MB0449, MB0450, MB0530, MB0558, MB0571, MB0572, MB0573, MB0574, MB0575, MB0576, MB0582, MB0584, MB0585, MB0586, MB0587, MB0588, MB0590, MB0591, MB0592, MB0593, MB0595, MB0596, MB0597, MB0599

