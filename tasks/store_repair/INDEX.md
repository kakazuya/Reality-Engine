# Store-repair notes (generated from notes.jsonl by `store_repair note`; do not edit by hand)

One entry per store defect, like one notebook cell: the question that exposed it, what was wrong and why, the fix, the code and store tables it touches, its tags and scope, the stores repaired. Stores are named by their build folder, never by company. Grid of stores x parts: `reports/store_repair_grid.xlsx` (`store_repair note grid`).

| id | status | part | scope | tags | stores repaired |
|---|---|---|---|---|---|
| R-001 | open | guidance | general | guidance, worded-guidance, transcript, speaker |  |
| R-002 | fix_written | docs_collect | general | transcript, fetch, nse, bse, no-call-filed | c08 |
| R-003 | fixed | events | general | events, order-win, regulation-30, announcement | c01, c02, c03, c04, c05, c06, c07, c08, c09, c10 |
| R-004 | fixed | stores | general | shareholding, xbrl, fpi, mutual-funds, drive | c01, c02, c03, c04, c05, c06, c07, c08, c09 |
| R-005 | fixed | kpi | general | kpi, unit, lakh, scale, row-check | c01, c03, c04, c05, c06, c07, c08, c09, c10 |
| R-006 | fixed | comparatives | general | results, unit, lakh, scale, xbrl, scan | c01, c02, c03, c04, c05, c06, c07, c08, c09, c10 |
| R-007 | open | kpi | general | kpi, revenue-definition, deck, annual-report, derived |  |
| R-008 | open | stores | general | share-capital, results, scale |  |

## R-001 (open, part `guidance`, opened 2026-11-16)

- **Question that exposed it** (pilot10, n10): What guidance did management give on margins for the year, and did it change between calls?
- **What was wrong:** Worded guidance (no number) is missed, and widening the sentence patterns loses right rows on unseen stores
- **Why:** pilot3/guidance.py worded path: four worker rounds (T-214 fix B) each failed on fresh stores; tag-question ban ignores who speaks; accounting-policy pages are in scope
- **Fix:** not written; Claude to redesign per document type and speaker; evidence D:/RealityEngine/tg_build/fixB_evidence
- **Code:** reality_engine/pilot3/guidance.py::worded path
- **Store tables touched:** guidance
- **Tags:** guidance, worded-guidance, transcript, speaker; **scope:** general
- **Stores repaired:** -; runs: -

## R-002 (fix_written, part `docs_collect`, opened 2026-11-16)

- **Question that exposed it** (c01): What did management say on the last call about order inflow and margins?
- **What was wrong:** Store holds no call transcript: 0 transcript_statement and 0 guidance rows (38 of 93 queue companies)
- **Why:** most of these companies file no call transcript on either exchange: of 37 queue companies with none in the store, BSE (feed to 19 Oct) and NSE (listing to 16 Nov) show transcripts for 3 (no BSE code, NSE only); 34 file none since 2024-04; the held BSE feed also stopped on 19 Oct, before the Q2 FY27 calls
- **Fix:** fetch family approved 16 Nov: nse_announcements listing for the queue + --attachments-only transcript (600 files, 52 companies, 610 MB, on Drive) and fetch_bse_announcements_daily 19 Oct-16 Nov (35,336 rows copied into reality_engine/data/bse_announcements.db; 34 queue companies filed a Q2 FY27 transcript, none of the 34 with no transcript). Next: rebuild docs_collect + transcripts + guidance store by store; a company with none on either exchange is recorded as no call filed, not a gap
- **Code:** reality_engine/scripts/nse_announcements.py::AnnouncementFetcher.download_kind, reality_engine/scripts/fetch_bse_announcements_daily.py::main, reality_engine/pilot3/docs_collect.py::discover
- **Store tables touched:** doc, doc_page, transcript_statement, guidance
- **Tags:** transcript, fetch, nse, bse, no-call-filed; **scope:** general
- **Stores repaired:** c08; runs: 20261116T160339

## R-003 (fixed, part `events`, opened 2026-11-16)

- **Question that exposed it** (c01): How large are the recent order wins against annual revenue, and over what period are they executed?
- **What was wrong:** 0 event rows although 19 held announcements are order wins ('secured a new work order of Rs. 300 Crores')
- **Why:** pilot3/events.py had no order-win kind and event has no value column
- **Fix:** pilot3/order_wins.py (prescribed Regulation 30 table by label, headline fallback) writes order_win in the events part; c01: 19 rows, Rs 6,361 crore, 2.5 s repair
- **Code:** reality_engine/pilot3/order_wins.py, reality_engine/pilot3/events.py
- **Store tables touched:** order_win
- **Tags:** events, order-win, regulation-30, announcement; **scope:** general
- **Stores repaired:** c01, c02, c03, c04, c05, c06, c07, c08, c09, c10; runs: 20261116T054008, 20261116T054133, 20261116T054138, 20261116T054142, 20261116T054146, 20261116T054151, 20261116T054155, 20261116T054159, 20261116T054203, 20261116T054207

## R-004 (fixed, part `stores`, opened 2026-11-16)

- **Question that exposed it** (c01): How have FPI and mutual fund holdings moved over the last four quarters?
- **What was wrong:** shp_category holds promoter and public only (2 rows per quarter, source shp_index); no FPI, MF, insurance or pledge rows
- **Why:** pilot3/stores.py build_shp read only the local pilot folder raw/nse_shp_xbrl_pilot (none of these companies' files); their filings since 2024-04 are on Drive under nse_shp_xbrl_universe (T-209), never looked up
- **Fix:** stores._shp_parsed looks up each file shp_index names in the pilot then universe folder, on disk or on Drive via raw_store (temp copy deleted). Applied c01-c09 (16 Nov), each refused by the gate and accepted after a check: no shareholding percentage changed, 358-757 category rows and 15-468 named holders added per store, KPI verdicts unchanged. Share counts now also come from intra-quarter shareholding filings, so allotments show earlier (c09: 187.2 m -> 464.3 m shares from 1 May 2026 instead of 14 May; c07 book value per share H1FY27 16,329 -> 133.57, the old figure used a bad 694,000-share quarterly row). c10 has no shareholding index (fetch gap). Quarters before 2024-04 are held nowhere
- **Code:** reality_engine/pilot3/stores.py::_shp_parsed, reality_engine/pilot3/stores.py::build_shp
- **Store tables touched:** shp_category, shp_holder, shp_pledge, share_capital, valuation_daily
- **Tags:** shareholding, xbrl, fpi, mutual-funds, drive; **scope:** general
- **Stores repaired:** c01, c02, c03, c04, c05, c06, c07, c08, c09; runs: -

## R-005 (fixed, part `kpi`, opened 2026-11-16)

- **Question that exposed it** (c01): What is the order book and how many years of revenue does it cover?
- **What was wrong:** 117 of 182 kpi_series rows quarantined, 13 verified
- **Why:** kpi.page_money_unit read only billion/million page declarations, so bare table figures on a page printed 'Rs. in Lakhs' were stored as crore (100x); the row checker's page_unit then quarantined them, and also quarantined a correctly rescaled row because it compared units only
- **Fix:** kpi: lakh/crore page declarations (declared only; two different declarations = unsure); row_checks.check_page_unit passes a row whose value is exactly the printed number moved from the declared scale. Applied 16 Nov to c01 c03-c10 after a hand-read of each diff: every re-valued row divided by exactly 100; rows dropped without a twin were wrong crore figures (quarantined or unverified), no verified row lost; c01 quarantined 85 -> 49, c08 111 -> 86 (verified 23 -> 39), c10 42 -> 34. c02 HELD: 4 verified Q4 rows derived as FY - 9M from the deck would be lost because the annual report's revenue (now read right) disagrees with the deck's (R-007)
- **Code:** reality_engine/pilot3/kpi.py::page_money_unit, reality_engine/pilot3/kpi.py::_page_unit_canon, reality_engine/pilot3/row_checks.py::check_page_unit, reality_engine/pilot3/row_checks.py::_rescaled_exactly
- **Store tables touched:** kpi_series, row_check, row_check_fail
- **Tags:** kpi, unit, lakh, scale, row-check; **scope:** general
- **Stores repaired:** c01, c03, c04, c05, c06, c07, c08, c09, c10; runs: 20261116T145556, 20261116T145711

## R-006 (fixed, part `comparatives`, opened 2026-11-16)

- **Question that exposed it** (c01): What was the full-year profit after tax, and does the order book cover three years of revenue?
- **What was wrong:** Printed results rows of three filings stored 100 times too large (full-year PAT 1,857.67 crore for 18.58); the row checker then quarantined right KPI rows as 'part, not total'
- **Why:** pilot3/comparatives.py _unit took 'crore' from a note sentence on a page printed in lakhs whose unit line is missing from the text layer; a declared scale was never tested against XBRL
- **Fix:** _unit reads only a declared unit ('in lakhs', 'Rs. Crore'); _roles lets an XBRL-confirmed scale beat a declared one. Unseen ten-company store (copy diff, 16 Nov): 0 values changed, 0 rows lost; 698 rows on 6 pages only gained the label 'scale from XBRL'
- **Code:** reality_engine/pilot3/comparatives.py::_unit, reality_engine/pilot3/comparatives.py::_roles
- **Store tables touched:** fin_quarter_printed, fin_quarter_current, kpi_series, row_check
- **Tags:** results, unit, lakh, scale, xbrl, scan; **scope:** general
- **Stores repaired:** c01, c02, c03, c04, c05, c06, c07, c08, c09, c10; runs: 20261116T054404, 20261116T092917, 20261116T092943, 20261116T093035, 20261116T093154, 20261116T093301, 20261116T093353, 20261116T093447, 20261116T093514, 20261116T093845

## R-007 (open, part `kpi`, opened 2026-11-16)

- **Question that exposed it** (c02): What was the Q4 revenue, and how did it move from the year before?
- **What was wrong:** After R-005 the annual report's revenue rows (lakh pages) are read correctly and disagree with the deck's 'Revenue': FY24 standalone 665.57 crore (AR, revenue from operations 66,556.67 lakh) against 706.7 (deck); the cumulative derivation then refuses Q4 = FY - 9M, so 6 derived Q4 rows (4 verified) are no longer written
- **Why:** not diagnosed: the deck's 'Revenue' line probably includes other income (706.7 - 665.57 = 41.1); kpi maps both captions to one metric 'revenue'
- **Fix:** -
- **Code:** reality_engine/pilot3/kpi.py::derive_quarters, reality_engine/pilot3/kpi.py (revenue captions)
- **Store tables touched:** kpi_series
- **Tags:** kpi, revenue-definition, deck, annual-report, derived; **scope:** general
- **Stores repaired:** -; runs: -

## R-008 (open, part `stores`, opened 2026-11-16)

- **Question that exposed it** (c07): What is the book value per share now?
- **What was wrong:** share_capital holds 694,000 shares for 2026-09-30 from the quarterly results (source 'quarterly'), against 84.8 million in the shareholding pattern of the same date
- **Why:** not diagnosed: the quarterly results reader took a share-count figure about 120 times too small (perhaps a face-value or lakh column)
- **Fix:** -
- **Code:** reality_engine/pilot3/stores.py (share_capital from quarterly results)
- **Store tables touched:** share_capital, ratio_panel, valuation_daily
- **Tags:** share-capital, results, scale; **scope:** general
- **Stores repaired:** -; runs: -
