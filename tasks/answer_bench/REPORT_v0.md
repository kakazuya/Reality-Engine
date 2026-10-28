# Query layer v0 — bench report

- sample: `SAMPLE.jsonl` (150 cases; 30 regressions)
- executor: `reality_engine/query/` router + planners (resolve, FACTS, SERIES, SCREEN,
  EVENT, EVIDENCE, COMPARE, RIPPLE) with `compute.py` arithmetic and `answer.py` assembly
- grading: identical to the bench — `run_bench.finish` (all hops ok -> ANSWERED,
  some ok -> PARTIAL, none ok -> BLOCKED_*/NOT_IN_DATA; PIT evidence check;
  list/ranking rule; rubric ground-truth verdict), plus `recheck.py`'s hand-audit
  downgrades applied to any ANSWERED row it lists
- before: `RESULTS.jsonl` (measured with the old ad-hoc probes)
- data: held databases only, read-only; no migration was run

## 1. Before / after

| grade | before | after |
|---|---|---|
| BLOCKED_TOOL | 17 | 9 |
| PARTIAL | 88 | 106 |
| NOT_IN_DATA | 13 | 1 |
| BLOCKED_SCHEMA | 25 | 17 |
| ANSWERED | 7 | 17 |

**Regressions (30):** ANSWERED 4 -> 7; PARTIAL 15 -> 19; BLOCKED_SCHEMA 6 -> 3; BLOCKED_TOOL 5 -> 0; NOT_IN_DATA 0 -> 1.

Hand-audit downgrades applied to v0: ['MB0883']. Hand-audit downgrades **not** applied because v0 closed the named gap: ['MB0008', 'MB0310'].

### By family (first family in the case)

| family | cases | ANSWERED before | ANSWERED after | PARTIAL before | PARTIAL after |
|---|---|---|---|---|---|
| family 1 | 21 | 0 | 5 | 5 | 12 |
| family 11 | 6 | 0 | 0 | 0 | 6 |
| family 12 | 4 | 0 | 0 | 1 | 4 |
| family 13 | 4 | 0 | 0 | 4 | 0 |
| family 14 | 8 | 0 | 2 | 6 | 3 |
| family 15 | 6 | 2 | 1 | 4 | 4 |
| family 16 | 17 | 0 | 0 | 12 | 15 |
| family 17 | 6 | 0 | 0 | 2 | 6 |
| family 18 | 3 | 0 | 0 | 2 | 3 |
| family 19 | 4 | 0 | 0 | 1 | 3 |
| family 2 | 20 | 5 | 8 | 12 | 9 |
| family 20 | 5 | 0 | 0 | 2 | 3 |
| family 3 | 3 | 0 | 0 | 2 | 3 |
| family 4 | 3 | 0 | 0 | 1 | 2 |
| family 6 | 20 | 0 | 0 | 16 | 18 |
| family 9 | 3 | 0 | 0 | 2 | 2 |
| family None | 17 | 0 | 1 | 16 | 13 |

### By entity level

| level | cases | ANSWERED before | ANSWERED after | PARTIAL before | PARTIAL after |
|---|---|---|---|---|---|
| level index | 5 | 0 | 0 | 3 | 3 |
| level industry | 21 | 0 | 0 | 13 | 18 |
| level macro | 6 | 0 | 0 | 0 | 6 |
| level market-cap bucket | 6 | 0 | 1 | 4 | 4 |
| level market-wide | 12 | 2 | 1 | 8 | 4 |
| level policy | 9 | 0 | 0 | 8 | 9 |
| level price band | 1 | 0 | 0 | 1 | 1 |
| level sector | 5 | 0 | 0 | 2 | 4 |
| level stock | 78 | 5 | 15 | 45 | 50 |
| level theme | 7 | 0 | 0 | 4 | 7 |

### By source bank

| bank | cases | ANSWERED before | ANSWERED after | PARTIAL before | PARTIAL after |
|---|---|---|---|---|---|
| bank open300 | 38 | 2 | 1 | 24 | 27 |
| bank reddit200 | 30 | 0 | 4 | 23 | 21 |
| bank ripple200 | 23 | 0 | 0 | 10 | 21 |
| bank shivam30 | 30 | 4 | 7 | 15 | 19 |
| bank variations300 | 29 | 1 | 5 | 16 | 18 |

## 2. The 30 regressions

| mid | before | after | question | blocker |
|---|---|---|---|---|
| MB0001 | PARTIAL | PARTIAL | AEROFLEX products + close on a date | hop failed: EVIDENCE (no passage matching 'products' in the available documents known by 2 |
| MB0002 | BLOCKED_TOOL | ANSWERED | 532627 latest AR: control change |  |
| MB0003 | BLOCKED_SCHEMA | PARTIAL | 544161 business + segments | hop failed: FACTS (segment facts exist but the segment member names are not mapped; a segm |
| MB0004 | PARTIAL | PARTIAL | P/B now vs stored | hop failed: COMPARE (no comparable metric for two peers filed by 2026-10-19) |
| MB0005 | BLOCKED_TOOL | PARTIAL | DEEDEV Aug-2026 concall remark | hop failed: EVIDENCE (no passage matching 'concall remark' in the transcript documents kno |
| MB0006 | PARTIAL | PARTIAL | KRISHNADEF segment revenue, latest quarter | hop failed: RIPPLE (policy State_Budget_Tamil_Nadu: Tamil Nadu Budget Analysis FY2026-27 ( |
| MB0007 | PARTIAL | PARTIAL | Bank of Maharashtra net NPA % | hop failed: FACTS (facts exist for MAHABANK but none carries the asked metric (net_npa)) |
| MB0008 | PARTIAL | ANSWERED | ZENTEC 3-yr price CAGR |  |
| MB0009 | BLOCKED_TOOL | PARTIAL | VISHNU Note 5 of latest results + geo split | hop failed: EVENT (no event row around 2026-06-30; price moved +0.49% on 2026-07-01) |
| MB0010 | ANSWERED | ANSWERED | VINCOFE public shareholding Sep 2026 |  |
| MB0011 | PARTIAL | PARTIAL | Why gold stocks fell Jun–Jul 2026 | hop failed: SCREEN (screen needs company_theme_pit; that table is not held yet) |
| MB0012 | BLOCKED_SCHEMA | BLOCKED_SCHEMA | HFC securitisation leader, QoQ/YoY with NPA guard | screen needs company_theme_pit; that table is not held yet |
| MB0013 | PARTIAL | PARTIAL | OMCs: record Q4 then loss Q1; earliest PIT signal | hop failed: RIPPLE (policy RBI_Monetary_Policy: RBI Full Document (2026-10-07) matched, bu |
| MB0014 | PARTIAL | BLOCKED_SCHEMA | MONQ50 ETF jump/fall + tracking error | isin_rekey_map not held: no event row around 2026-09-18; price moved -20.00% on 2026-09-21 |
| MB0015 | PARTIAL | PARTIAL | Garware: tariff hit, then negative correlation | hop failed: RIPPLE (policy RBI_MPC_Minutes: RBI Minutes of the Monetary Policy Committee M |
| MB0016 | PARTIAL | PARTIAL | RBI repo hike causes; PIB or RBI only | hop failed: RIPPLE (policy RBI_Monetary_Policy: RBI Governor’s Statement: October 7, 2026  |
| MB0017 | BLOCKED_SCHEMA | PARTIAL | Second-hand electronics boom CY2026: who benefits | hop failed: RIPPLE (policy Secretary, Department of Urban Development, MoHUA chairs 10th m |
| MB0018 | PARTIAL | PARTIAL | Coal gasification drafts vs the earlier scheme | hop failed: RIPPLE (policy State_Budget_West_Bengal: West Bengal Budget Analysis FY2026-27 |
| MB0019 | PARTIAL | PARTIAL | PARAGMILK on El Niño; dairy peers | hop failed: RIPPLE (policy State_Budget_Himachal_Pradesh: Himachal Pradesh Budget Analysis |
| MB0020 | PARTIAL | PARTIAL | Data-centre tax holiday outcome so far | hop failed: RIPPLE (policy Ministry of Youth Affairs and Sports issues operational guideli |
| MB0021 | ANSWERED | PARTIAL | What was the delivery volume (delivered quantity, not total traded qua | hop failed: EVENT (no event row around 2026-04-14; price moved -4.05% on 2026-04-15) |
| MB0022 | ANSWERED | ANSWERED | What is the promoter holding of NSE: BLACKBUCK as of September 2026? |  |
| MB0023 | BLOCKED_SCHEMA | ANSWERED | How many manufacturing facilities does Ganesha Ecosphere have, per its |  |
| MB0024 | BLOCKED_SCHEMA | PARTIAL | What are the key products of Chemcon Speciality Chemicals per its inve | hop failed: EVIDENCE (no passage matching 'products speciality' in the deck documents know |
| MB0025 | PARTIAL | BLOCKED_SCHEMA | How many equity shares does Lumax Auto Technologies have, and what is  | CASE_MAP blocker needs_new_table:xbrl_concept_map: v0 measured only an adjacent held-data  |
| MB0026 | PARTIAL | NOT_IN_DATA | What did BSE: 540879 show on page 21 (of 79) of its investor presentat | 2026-10-24 is after as_of 2026-10-19; a document first known after the as_of day cannot an |
| MB0027 | BLOCKED_TOOL | PARTIAL | What did ISIN INE864I01014 say about its fuel-cell capacity expansion  | hop failed: EVIDENCE (no passage matching 'isin fuel' in the transcript documents known by |
| MB0028 | ANSWERED | ANSWERED | What was the YTD high price of BSE: 532810 in 2026 (value and date)? |  |
| MB0029 | BLOCKED_SCHEMA | PARTIAL | What did NSE: SAILIFE say about its newly commissioned facilities, as  | hop failed: EVIDENCE (no passage matching 'newly commissioned' in the available documents  |
| MB0030 | BLOCKED_TOOL | ANSWERED | Per the transcript of 18 September 2026 of 540678 / COCHINSHIP: what d |  |

## 3. CASE_MAP accuracy: status x v0 grade

| CASE_MAP status | cases | ANSWERED | PARTIAL | BLOCKED_SCHEMA | BLOCKED_TOOL | NOT_IN_DATA |
|---|---|---|---|---|---|---|
| NOT_IN_DATA:consensus | 1 | 0 | 1 | 0 | 0 | 0 |
| NOT_IN_DATA:refurb_sales | 1 | 0 | 1 | 0 | 0 | 0 |
| answerable_now | 61 | 17 | 40 | 3 | 0 | 1 |
| needs_new_fetch:bhavcopy_backfill | 2 | 0 | 0 | 0 | 2 | 0 |
| needs_new_fetch:bse_results_notes | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_fetch:bse_scrip_master_history | 2 | 0 | 1 | 0 | 1 | 0 |
| needs_new_fetch:carrier_schedules | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_fetch:commodity_price_daily | 12 | 0 | 10 | 1 | 1 | 0 |
| needs_new_fetch:customs_schedules | 2 | 0 | 2 | 0 | 0 | 0 |
| needs_new_fetch:exchange_originals | 7 | 0 | 4 | 0 | 3 | 0 |
| needs_new_fetch:freight_rate_daily | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_fetch:industry_volume_data | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_fetch:nse_fno_bhavcopy | 2 | 0 | 1 | 0 | 1 | 0 |
| needs_new_fetch:nse_index_circulars | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_fetch:supply_chain_map | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_fetch:vahan | 1 | 0 | 0 | 0 | 1 | 0 |
| needs_new_table:audit_opinion_detail | 3 | 0 | 1 | 2 | 0 | 0 |
| needs_new_table:bank_deposit_rate | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_table:capex_project | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_table:chunks_v3 | 7 | 0 | 4 | 3 | 0 | 0 |
| needs_new_table:company_cost_structure | 5 | 0 | 4 | 1 | 0 | 0 |
| needs_new_table:company_debt_mix | 2 | 0 | 2 | 0 | 0 | 0 |
| needs_new_table:company_metric_series | 4 | 0 | 4 | 0 | 0 | 0 |
| needs_new_table:company_operating_metrics | 2 | 0 | 2 | 0 | 0 | 0 |
| needs_new_table:company_price_revision | 1 | 0 | 0 | 1 | 0 | 0 |
| needs_new_table:company_segment_pnl | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_table:company_state_daily | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_table:company_theme_pit | 2 | 0 | 1 | 1 | 0 | 0 |
| needs_new_table:event_calendar | 2 | 0 | 2 | 0 | 0 | 0 |
| needs_new_table:event_day0 | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_table:guidance_vs_actual | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_table:industry_capacity_pipeline | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_table:isin_rekey_map | 1 | 0 | 0 | 1 | 0 | 0 |
| needs_new_table:macro_claim_target | 5 | 0 | 4 | 1 | 0 | 0 |
| needs_new_table:price_band_daily | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_table:sector_flow_daily | 1 | 0 | 1 | 0 | 0 | 0 |
| needs_new_table:xbrl_concept_map | 10 | 0 | 7 | 3 | 0 | 0 |

### answerable_now that v0 could not answer

| mid | v0 grade | failed hops | blocker | exact missing piece |
|---|---|---|---|---|
| MB0001 | PARTIAL | EVIDENCE | hop failed: EVIDENCE (no passage matching 'products' in the available documents known by 2026-10-19) | chunks_v3 (known_at/section/speaker_role tags) for precise passage retrieval |
| MB0003 | PARTIAL | FACTS | hop failed: FACTS (segment facts exist but the segment member names are not mapped; a segment P&L by name need | xbrl_concept_map + company_metric_series (held concept names are unmapped) |
| MB0017 | PARTIAL | RIPPLE | hop failed: RIPPLE (policy Secretary, Department of Urban Development, MoHUA chairs 10th meeting of CSMC under | company_cost_structure + company_segment_pnl + macro_claim_target |
| MB0020 | PARTIAL | RIPPLE | hop failed: RIPPLE (policy Ministry of Youth Affairs and Sports issues operational guidelines for revised Sche | company_cost_structure + company_segment_pnl + macro_claim_target |
| MB0021 | PARTIAL | EVENT+SERIES | hop failed: EVENT (no event row around 2026-04-14; price moved -4.05% on 2026-04-15) | event_day0 (15:30 session rule) and announcement dissemination index |
| MB0024 | PARTIAL | EVIDENCE | hop failed: EVIDENCE (no passage matching 'products speciality' in the deck documents known by 2026-10-19) | chunks_v3 (known_at/section/speaker_role tags) for precise passage retrieval |
| MB0026 | NOT_IN_DATA | EVIDENCE | 2026-10-24 is after as_of 2026-10-19; a document first known after the as_of day cannot answer a point-in-time | chunks_v3 (known_at/section/speaker_role tags) for precise passage retrieval |
| MB0027 | PARTIAL | EVIDENCE | hop failed: EVIDENCE (no passage matching 'isin fuel' in the transcript documents known by 2026-10-19) | chunks_v3 (known_at/section/speaker_role tags) for precise passage retrieval |
| MB0831 | PARTIAL | EXPECTATIONS | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB0832 | PARTIAL | EXPECTATIONS+EVIDENCE | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB0839 | PARTIAL | EXPECTATIONS | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB0840 | PARTIAL | EXPECTATIONS | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB0842 | BLOCKED_SCHEMA | EXPECTATIONS+SERIES | the held numbers may answer the factual part, but no consensus / target-price / valuation-advice store exists, | not identified |
| MB0867 | PARTIAL | EXPECTATIONS | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB0883 | PARTIAL | - | one quarter's promoter % plus the price; whether the promoter group RAISED its stake needs two quarters compar | not identified |
| MB0886 | BLOCKED_SCHEMA | EXPECTATIONS | the held numbers may answer the factual part, but no consensus / target-price / valuation-advice store exists, | not identified |
| MB0890 | PARTIAL | FACTS | hop failed: FACTS (segment facts exist but the segment member names are not mapped; a segment P&L by name need | xbrl_concept_map + company_metric_series (held concept names are unmapped) |
| MB0898 | PARTIAL | EXPECTATIONS | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB0935 | PARTIAL | EXPECTATIONS | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB0948 | PARTIAL | RIPPLE+SERIES+EVIDENCE | hop failed: RIPPLE (policy CAQM expands PTZ Camera-based Remote Monitoring to all Industries covered under Dir | company_cost_structure + company_segment_pnl + macro_claim_target |
| MB0969 | PARTIAL | SERIES | hop failed: SERIES (no price rows for HINDZINC between 2024-03-31 and 2024-03-31) | px adjusted series is held; intraday bars / event_day0 for session-level asks |
| MB0973 | PARTIAL | RIPPLE+FACTS | hop failed: RIPPLE (policy State_Budget_Tamil_Nadu: Tamil Nadu Budget Analysis FY2026-27 (PRS) matched, but it | company_cost_structure + company_segment_pnl + macro_claim_target |
| MB0979 | PARTIAL | EXPECTATIONS | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB0983 | BLOCKED_SCHEMA | EXPECTATIONS+SERIES | the held numbers may answer the factual part, but no consensus / target-price / valuation-advice store exists, | not identified |
| MB0989 | PARTIAL | EXPECTATIONS+COMPARE+EVIDENCE | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB1006 | PARTIAL | EXPECTATIONS+EVENT | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB1007 | PARTIAL | EXPECTATIONS+EVENT+EVIDENCE | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB1010 | PARTIAL | EXPECTATIONS+EVENT | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB1011 | PARTIAL | EXPECTATIONS | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB1015 | PARTIAL | EXPECTATIONS | hop failed: EXPECTATIONS (the held numbers may answer the factual part, but no consensus / target-price / valu | not identified |
| MB1026 | PARTIAL | EVENT+EVIDENCE | hop failed: EVENT (no event row around 2025-09-24; price moved -1.50% on 2025-09-25) | event_day0 (15:30 session rule) and announcement dissemination index |
| MB0332 | PARTIAL | FACTS+SERIES | hop failed: FACTS (facts exist for DIXON but none carries the asked metric (revenue)) | xbrl_concept_map + company_metric_series (held concept names are unmapped) |
| MB0436 | PARTIAL | EVENT+EVIDENCE | hop failed: EVENT (no event row around 2025-04-07; price moved -1.74% on 2025-04-08) | event_day0 (15:30 session rule) and announcement dissemination index |
| MB0449 | PARTIAL | EVENT+EVIDENCE | hop failed: EVENT (no event row around 2026-08-12; price moved +2.06% on 2026-08-13) | event_day0 (15:30 session rule) and announcement dissemination index |
| MB0584 | PARTIAL | EVIDENCE | hop failed: EVIDENCE (no passage matching 'delivery june' in the available documents known by 2024-06-11) | chunks_v3 (known_at/section/speaker_role tags) for precise passage retrieval |
| MB0040 | PARTIAL | EVENT | hop failed: EVENT (no event row around 2026-10-16; price moved -1.11% on 2026-10-19) | event_day0 (15:30 session rule) and announcement dissemination index |
| MB0113 | PARTIAL | EVENT+EVIDENCE | hop failed: EVENT (no event row around 2026-06-30; price moved +0.33% on 2026-07-01) | event_day0 (15:30 session rule) and announcement dissemination index |
| MB0151 | PARTIAL | RIPPLE | hop failed: RIPPLE (policy RBI_Monetary_Policy: RBI Full Document (2026-04-08) matched, but its sector/company | company_cost_structure + company_segment_pnl + macro_claim_target |
| MB0152 | PARTIAL | RIPPLE | hop failed: RIPPLE (policy State_Budget_Assam: Assam Budget Analysis FY2026-27 (PRS) matched, but its sector/c | company_cost_structure + company_segment_pnl + macro_claim_target |
| MB0154 | PARTIAL | RIPPLE | hop failed: RIPPLE (policy RBI_Monetary_Policy: RBI Full Document (2026-04-08) matched, but its sector/company | company_cost_structure + company_segment_pnl + macro_claim_target |
| MB0159 | PARTIAL | RIPPLE+EVIDENCE | hop failed: RIPPLE (policy RBI_MPC_Minutes: RBI Minutes of the Monetary Policy Committee Meeting, June 3 to 5, | company_cost_structure + company_segment_pnl + macro_claim_target |
| MB0199 | PARTIAL | RIPPLE+EVIDENCE | hop failed: RIPPLE (policy RBI_MPC_Minutes: RBI Minutes of the Monetary Policy Committee Meeting, June 3 to 5, | company_cost_structure + company_segment_pnl + macro_claim_target |
| MB0201 | PARTIAL | RIPPLE+EVIDENCE | hop failed: RIPPLE (policy Union Minister Shri Hardeep Singh Puri Addresses Valedictory Session of SRCC’s Cent | company_cost_structure + company_segment_pnl + macro_claim_target |
| MB0314 | PARTIAL | EVIDENCE | hop failed: EVIDENCE (no passage matching 'newly commissioned' in the available documents known by 2026-10-19) | chunks_v3 (known_at/section/speaker_role tags) for precise passage retrieval |

## 4. Remaining blockers (top 10)

| blocker / table | worst grade | cases | examples | what fixes it |
|---|---|---|---|---|
| answerable_now | PARTIAL | 40 | MB0001, MB0003, MB0017, MB0020, MB0021 | chunks_v3 (known_at/section/speaker_role tags) for precise passage retrieval |
| commodity_price_daily | PARTIAL | 10 | MB0013, MB0015, MB0018, MB0601, MB0140 | commodity_price_daily (new fetch; mkt_commodity_daily is partial) |
| xbrl_concept_map | PARTIAL | 7 | MB0007, MB0472, MB0477, MB0490, MB0527 | xbrl_concept_map (new table from results_xbrl concepts) |
| company_metric_series | PARTIAL | 4 | MB0004, MB0767, MB0786, MB0808 | company_metric_series (normalized metric time series) |
| chunks_v3 | PARTIAL | 4 | MB0005, MB0016, MB0029, MB0430 | chunks_v3 (new table: known_at, section, speaker_role, tags) |
| company_cost_structure | PARTIAL | 4 | MB0464, MB0466, MB0494, MB0602 | company_cost_structure (AR cost note extraction) |
| macro_claim_target | PARTIAL | 4 | MB0496, MB0609, MB0138, MB0224 | macro_claim_target (claim -> sector/company exposure map) |
| exchange_originals | PARTIAL | 4 | MB0144, MB0148, MB0320, MB0328 | exchange_originals (new fetch: BSE/NSE original filing files) |
| xbrl_concept_map | BLOCKED_SCHEMA | 3 | MB0025, MB0365, MB0411 | xbrl_concept_map (new table from results_xbrl concepts) |
| answerable_now | BLOCKED_SCHEMA | 3 | MB0842, MB0886, MB0983 | see CASE_MAP blocking |

## 5. Speed and PIT

| planner | calls | p50 s | p95 s | max s | over 2 s |
|---|---|---|---|---|---|
| COMPARE | 27 | 0.00 | 0.12 | 0.15 | 0 |
| EVENT | 43 | 0.00 | 0.00 | 0.02 | 0 |
| EVIDENCE | 94 | 1.71 | 5.63 | 14.30 | 41 |
| EXPECTATIONS | 19 | 0.00 | 0.00 | 0.00 | 0 |
| FACTS | 130 | 0.07 | 0.67 | 1.12 | 0 |
| RIPPLE | 55 | 0.02 | 0.07 | 0.32 | 0 |
| SCREEN | 66 | 0.03 | 0.81 | 1.62 | 0 |
| SERIES | 104 | 0.01 | 0.13 | 1.29 | 0 |
| resolve | 150 | 0.01 | 0.03 | 0.04 | 0 |
| case metric | value |
|---|---|
| cases | 150 |
| wall time | 245.5 s |
| per-case p50 | 0.86 s |
| per-case p95 | 5.11 s |
| per-case max | 14.38 s |
| cases over 2 s | 46 |
| PIT violations | 0 |

Slowest cases: MB0001 4.1s, MB0011 14.4s, MB0029 2.8s, MB0030 2.4s, MB0831 3.8s, MB0832 3.3s, MB0840 2.9s, MB0867 4.3s

Speed fixes in code (no migration run):
- `_facts_ar` symbol fallback now resolves doc ids through `ar_docs` and the `ar_facts_doc(doc_id, piece)` index instead of an `upper(symbol) IN (...)` scan of 32.4M rows: the bench's 15.5 s `facts(..., 'ar', 'FY27')` miss is 0.4-3.2 s cold and ~0.4 s warm.
- `snapshot_path()` is cached (it globbed the snapshots dir on every `provenance()` call): ~0.24 s per `doc_find` not-found path.
- `doc_find`/`docs`/`doc_page`/`facts` push `as_of` into SQL and no longer return later documents.
- corpus EVIDENCE reuses `search_docs.warm()` (the MCP server warms at start); cold index load is the 24-34 s peak, warm company search is ~1.9 s.
- candidate indexes (not run): `tasks/arch_v3/INDEX_MIGRATION_V0.sql` — `document_chunks(symbol, published_date DESC)`, `document_chunks(isin, published_date DESC)`, `ar_facts(isin, filed_at DESC)`, `ar_docs(symbol)`, `policy_events(policy_name)`.

PIT: every planner pushes its own timestamp column into the SQL; the harness re-checks every evidence date against `as_of` (0 violations required).

MB0026 (the leak the bench found): v0 grades it **NOT_IN_DATA** — 2026-10-24 is after as_of 2026-10-19; a document first known after the as_of day cannot answer a point-in-time question
