# Pilot (b) — the (b) tables whose source is already held (2026-10-29)

Built by `python -m reality_engine.pilot.build_b` into `.tmp/pilot_b/market_state_b.db` with the DDL of `tasks/SCHEMA_FINAL_2026-10-29.sql` (schema prefix stripped: one file per domain). No network, no live-DB write; every raw file on D: is streamed once.

## 1. Tables

| table | rows | coverage | hand check | cases moved b → a |
|---|---:|---|---|---:|
| `series_meta` | 22 | 22 World Bank Pink Sheet series, monthly | 10/10 against the raw file | 0 |
| `series_observation` | 7,062 | 2000-01-31..2026-09-30 monthly; known_at 2026-10-02 | 10/10 against the raw file | 0 |
| `commodity_price_daily` | 7,062 | 2000-01-31..2026-09-30 view over 22 commodities | 10/10 against the raw file | 36 |
| `index_list` | 133 | changes_only 124, snapshot 6, derived 3 | 6/6 against the raw file | 0 |
| `company_membership_pit` | 10,895 | 2019-01-01..2026-10-30, 1888 ISINs; pit_conf 0.6: 6815, pit_conf 0.8: 2022, pit_conf 1.0: 2058 | 10/10 against the raw file | 3 |
| `fno_oi_daily` | 16,242,454 | 2019-01-01..2026-10-28, 1930 sessions, 362 underlyings; PE: 7585532, CE: 7577740, FUT: 1079182 | 10/10 against the raw file | 7 |
| `mkt_nse_full_daily` | 4,290,443 | 2019-01-01..2026-10-19, 1926 sessions, 4467 symbols, 5 series | 10/10 against the raw file | 19 |

Case re-classification: **a 694 / b 370 / c 9** (from a 629 / b 435 / c 9): 65 moved b → a, 40 still b, written to `tasks/pilot_b/cases_pilot_b.jsonl`.

## 2. Cases moved b → a

- `MB0013` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-06-30 for the case window (period end 2026-06-30)
- `MB0015` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-19)
- `MB0077` — mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19
- `MB0102` — mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19
- `MB0104` — mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19
- `MB0128` — mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19
- `MB0160` — wb_coal_aus covers 2000-01-31..2026-06-30 for the case window (period end 2026-06-30)
- `MB0162` — mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19
- `MB0164` — mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19
- `MB0165` — mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19
- `MB0166` — mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19
- `MB0168` — mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19
- `MB0169` — mkt_nse_full_daily has 1/1 entity symbols <= 2026-09-17
- `MB0170` — mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19
- `MB0218` — mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19
- `MB0220` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-19)
- `MB0235` — mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19
- `MB0240` — mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19
- `MB0248` — mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19
- `MB0258` — NIFTY MIDSMALLCAP 400: 883 dated intervals <= 2026-10-19 (coverage derived)
- `MB0277` — mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19
- `MB0278` — mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19
- `MB0288` — NIFTY SMALLCAP 250: 752 dated intervals <= 2026-10-19 (coverage snapshot)
- `MB0298` — mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19
- `MB0308` — NIFTY 200: 342 dated intervals <= 2026-10-19 (coverage snapshot)
- `MB0327` — mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19
- `MB0369` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-06-30 for the case window (period end 2026-06-30)
- `MB0459` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-09-30)
- `MB0632` — wb_crude_brent covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0633` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0635` — wb_coal_aus covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0636` — wb_crude_brent covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0637` — wb_crude_brent covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0638` — wb_urea covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0640` — wb_gold covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0641` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0643` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0644` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0648` — wb_rubber covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0649` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0650` — wb_copper covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0687` — wb_gold covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0696` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0697` — wb_cotton_a covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0698` — wb_crude_brent covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0703` — wb_copper covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0706` — wb_rubber covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0716` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0788` — wb_coal_aus covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-29)
- `MB0791` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-23)
- `MB0794` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-23)
- `MB0798` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-23)
- `MB0800` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-23)
- `MB0806` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-23)
- `MB0880` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-03-31 for the case window (period end 2026-03-31)
- `MB0943` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-03-31 for the case window (period end 2026-03-31)
- `MB0945` — a held series (22 of the 40 asked for) covers 2000-01-31..2025-12-31 for the case window (period end 2025-12-31)
- `MB0980` — a held series (22 of the 40 asked for) covers 2000-01-31..2026-03-31 for the case window (period end 2026-03-31)
- `MB1017` — fno_oi_daily has rows for AMBER <= 2026-10-19
- `MB1018` — fno_oi_daily has rows for SONACOMS <= 2026-10-19
- `MB1019` — fno_oi_daily has rows for ASIANPAINT <= 2026-10-19
- `MB1020` — fno_oi_daily has rows for DMART <= 2026-10-19
- `MB1021` — fno_oi_daily has rows for ETERNAL <= 2026-10-19
- `MB1022` — fno_oi_daily has rows for POLYCAB <= 2026-10-19
- `MB1025` — fno_oi_daily has rows for HDFCBANK <= 2026-09-24

## 2b. Five dependent bank cases per table (the field is present for the case's entity and period)

| table | case | entity + period evidence | verdict |
|---|---|---|---|
| `commodity_price_daily` | `MB0013` | a held series (22 of the 40 asked for) covers 2000-01-31..2026-06-30 for the case window (period end 2026-06-30) | moved b → a |
| `commodity_price_daily` | `MB0015` | a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-19) | moved b → a |
| `commodity_price_daily` | `MB0160` | wb_coal_aus covers 2000-01-31..2026-06-30 for the case window (period end 2026-06-30) | moved b → a |
| `commodity_price_daily` | `MB0220` | a held series (22 of the 40 asked for) covers 2000-01-31..2026-09-30 for the case window (period end 2026-10-19) | moved b → a |
| `commodity_price_daily` | `MB0369` | a held series (22 of the 40 asked for) covers 2000-01-31..2026-06-30 for the case window (period end 2026-06-30) | moved b → a |
| `company_membership_pit` | `MB0258` | NIFTY MIDSMALLCAP 400: 883 dated intervals <= 2026-10-19 (coverage derived) | moved b → a |
| `company_membership_pit` | `MB0288` | NIFTY SMALLCAP 250: 752 dated intervals <= 2026-10-19 (coverage snapshot) | moved b → a |
| `company_membership_pit` | `MB0308` | NIFTY 200: 342 dated intervals <= 2026-10-19 (coverage snapshot) | moved b → a |
| `company_membership_pit` | `MB0038` | NIFTY TOTAL MARKET: only 1020 notice-dated changes held (coverage changes_only); the full constituent list is not held | kept b for another reason |
| `company_membership_pit` | `MB0098` | NIFTY HOUSING: only 34 notice-dated changes held (coverage changes_only); the full constituent list is not held | kept b for another reason |
| `fno_oi_daily` | `MB1017` | fno_oi_daily has rows for AMBER <= 2026-10-19 | moved b → a |
| `fno_oi_daily` | `MB1018` | fno_oi_daily has rows for SONACOMS <= 2026-10-19 | moved b → a |
| `fno_oi_daily` | `MB1019` | fno_oi_daily has rows for ASIANPAINT <= 2026-10-19 | moved b → a |
| `fno_oi_daily` | `MB1020` | fno_oi_daily has rows for DMART <= 2026-10-19 | moved b → a |
| `fno_oi_daily` | `MB1021` | fno_oi_daily has rows for ETERNAL <= 2026-10-19 | moved b → a |
| `mkt_nse_full_daily` | `MB0077` | mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19 | moved b → a |
| `mkt_nse_full_daily` | `MB0102` | mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19 | moved b → a |
| `mkt_nse_full_daily` | `MB0104` | mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19 | moved b → a |
| `mkt_nse_full_daily` | `MB0128` | mkt_nse_full_daily has 3/3 entity symbols <= 2026-10-19 | moved b → a |
| `mkt_nse_full_daily` | `MB0162` | mkt_nse_full_daily has 1/1 entity symbols <= 2026-10-19 | moved b → a |

## 3. Cases kept b (the built table did not verify them)

- `MB0018` — no held commodity observation covers period end 2026-12-31 as known by 2026-10-19
- `MB0038` — NIFTY TOTAL MARKET: only 1020 notice-dated changes held (coverage changes_only); the full constituent list is not held
- `MB0098` — NIFTY HOUSING: only 34 notice-dated changes held (coverage changes_only); the full constituent list is not held
- `MB0108` — NIFTY INDIA FPI 150: only 32 notice-dated changes held (coverage changes_only); the full constituent list is not held
- `MB0140` — no held commodity observation covers period end 2026-10-19 as known by 2026-10-19
- `MB0158` — NIFTY OIL & GAS: only 8 notice-dated changes held (coverage changes_only); the full constituent list is not held
- `MB0167` — case names no Nifty index
- `MB0188` — NIFTY TOTAL MARKET: only 1020 notice-dated changes held (coverage changes_only); the full constituent list is not held
- `MB0202` — no held commodity observation covers period end 2026-12-31 as known by 2026-10-19
- `MB0208` — NIFTY TOTAL MARKET: only 1020 notice-dated changes held (coverage changes_only); the full constituent list is not held
- `MB0210` — no held commodity observation covers period end 2026-12-31 as known by 2026-10-19
- `MB0238` — NIFTY SMALLCAP 500: only 237 notice-dated changes held (coverage changes_only); the full constituent list is not held
- `MB0359` — judgement/prediction ask: no held store answers it (EXPECTATIONS gate)
- `MB0431` — no held commodity observation covers period end 2025-04-07 as known by 2025-04-07
- `MB0457` — no held commodity observation covers period end 2027-03-31 as known by 2026-10-07
- `MB0458` — no held commodity observation covers period end 2026-12-31 as known by 2026-10-07
- `MB0580` — case names no Nifty index
- `MB0601` — no held commodity observation covers period end 2027-03-31 as known by 2026-10-07
- `MB0606` — no held commodity observation covers period end 2027-03-31 as known by 2026-10-07
- `MB0613` — no held commodity observation covers period end 2027-03-31 as known by 2026-10-07
- `MB0615` — no held commodity observation covers period end 2027-03-31 as known by 2026-10-07
- `MB0619` — judgement/prediction ask: no held store answers it (EXPECTATIONS gate)
- `MB0634` — commodity wb_aluminium is not among the 22 held World Bank series
- `MB0639` — no held commodity observation covers period end 2026-08-19 as known by 2026-08-19
- `MB0642` — commodity wb_aluminium is not among the 22 held World Bank series
- `MB0645` — judgement/prediction ask: no held store answers it (EXPECTATIONS gate)
- `MB0692` — commodity wb_aluminium is not among the 22 held World Bank series
- `MB0702` — commodity wb_aluminium is not among the 22 held World Bank series
- `MB0707` — judgement/prediction ask: no held store answers it (EXPECTATIONS gate)
- `MB0742` — no F&O contract for APARINDS, KEI, RRKABEL (not F&O eligible)
- `MB0751` — no held commodity observation covers period end 2026-06-30 as known by 2026-06-30
- `MB0752` — no held commodity observation covers period end 2026-06-30 as known by 2026-06-30
- `MB0756` — no held commodity observation covers period end 2026-06-30 as known by 2026-06-30
- `MB0768` — no held commodity observation covers period end 2026-06-30 as known by 2026-06-30
- `MB0774` — no held commodity observation covers period end 2026-06-30 as known by 2026-06-30
- `MB0787` — no held commodity observation covers period end 2026-06-30 as known by 2026-06-30
- `MB0797` — commodity wb_aluminium is not among the 22 held World Bank series
- `MB0903` — case names no Nifty index
- `MB0905` — case names no Nifty index
- `MB1016` — no F&O contract for SYRMA (not F&O eligible)

## 4. Skipped: needs a fetch or a document reader

| blocker | (b) cases | why skipped |
|---|---:|---|
| `needs_new_fetch:commodity_price_daily` | 62 | 22 monthly World Bank series built; daily LME/MCX/domestic series not held |
| `needs_new_fetch:exchange_originals` | 46 | not held; needs the fetch queue |
| `needs_new_fetch:bhavcopy_backfill` | 19 | NSE history built from the snapshot; SME/BSE-only archive not held |
| `needs_new_fetch:nse_index_circulars` | 15 | held and built (444/446 notice PDFs) |
| `needs_new_fetch:supply_chain_map` | 9 | not held; needs the fetch queue |
| `needs_new_fetch:customs_schedules` | 9 | not held; needs the fetch queue |
| `needs_new_fetch:nse_fno_bhavcopy` | 8 | held and built (futures market-wide, options pilot symbols) |
| `needs_new_fetch:freight_rate_daily` | 7 | not held; needs the fetch queue |
| `needs_new_fetch:industry_volume_data` | 6 | not held; needs the fetch queue |
| `needs_new_fetch:rural_wage_series` | 4 | not held; needs the fetch queue |
| `needs_new_fetch:bse_scrip_master_history` | 3 | not held; needs the fetch queue |
| `needs_new_fetch:rainfall_daily` | 3 | not held; needs the fetch queue |
| `needs_new_fetch:bse_results_notes` | 2 | not held; needs the fetch queue |
| `needs_new_fetch:cbic_notifications` | 2 | not held; needs the fetch queue |
| `needs_new_fetch:vahan` | 1 | not held; needs the fetch queue |
| `needs_new_fetch:nse_fno_history` | 1 | held and built |
| `needs_new_fetch:unspecified_source` | 1 | not held; needs the fetch queue |
| `needs_new_fetch:carrier_schedules` | 1 | not held; needs the fetch queue |
| `needs_new_fetch:ipo_grey_market` | 1 | not held; needs the fetch queue |
| `needs_new_fetch:india_10y_gsec` | 1 | not held; needs the fetch queue |
| `needs_new_table:company_cost_structure` | 31 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:chunks_v3` | 29 | already built by the chunks_v3 pilot — not rebuilt here |
| `needs_new_table:company_capacity_utilisation` | 19 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:company_operating_metrics` | 15 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:industry_capacity_pipeline` | 13 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:company_debt_mix` | 13 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:capex_project` | 12 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:company_segment_pnl` | 11 | already built by the T1 pilot (`build_t1`) — not rebuilt here |
| `needs_new_table:audit_opinion_detail` | 10 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:company_revenue_geography` | 7 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:company_fx_exposure` | 7 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:event_calendar` | 6 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:fund_raise` | 5 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:order_book_contract` | 4 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:rating_action` | 4 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:promoter_pledge_event` | 4 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:bank_deposit_rate` | 4 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:order_intake` | 3 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:guidance_vs_actual` | 3 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:company_kmp` | 3 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:entity_relations` | 3 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:event_leakage_window` | 3 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:company_theme_pit` | 2 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:corporate_action_class` | 2 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:bank_loan_book_repricing` | 2 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:company_cost_geography` | 2 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:competitor_action` | 2 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:isin_rekey_map` | 1 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:subsidy_register` | 1 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:price_band_daily` | 1 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:sector_flow_daily` | 1 | designed table: source held, but the deterministic/reader build is not part of this pilot |
| `needs_new_table:company_price_revision` | 1 | designed table: source held, but the deterministic/reader build is not part of this pilot |

## 6. How to reproduce

```bash
python -m reality_engine.pilot.build_b            # build (~43 min, streamed)
python -m reality_engine.pilot.build_b --verify   # stats + hand checks + reclassify
python -m unittest reality_engine.tests.test_pilot_t1 reality_engine.tests.test_pilot_b_tables
```

No network, no paid model, no commit. The build reads only D: raw files and the read-only live stores; it writes only `.tmp/pilot_b/` and `tasks/pilot_b/`.
