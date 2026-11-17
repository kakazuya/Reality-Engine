# Store-repair notes (generated from notes.jsonl by `store_repair note`; do not edit by hand)

One entry per store defect or patch, five points each (Shivam 16 Nov): why it had to be done, what the problem was, what was missing, how it was fixed, what can come next; then the code and store tables it touches, its tags and scope, the stores repaired. Stores are named by their build folder, never by company. Grid of stores x parts: `reports/store_repair_grid.xlsx` (`store_repair note grid`).

| id | status | part | scope | tags | stores repaired |
|---|---|---|---|---|---|
| R-001 | open | guidance | general | guidance, worded-guidance, transcript, speaker |  |
| R-002 | fix_written | docs_collect | general | transcript, fetch, nse, bse, no-call-filed | c08 |
| R-003 | fixed | events | general | events, order-win, regulation-30, announcement | c01, c02, c03, c04, c05, c06, c07, c08, c09, c10 |
| R-004 | fixed | stores | general | shareholding, xbrl, fpi, mutual-funds, drive | c01, c02, c03, c04, c05, c06, c07, c08, c09 |
| R-005 | fixed | kpi | general | kpi, unit, lakh, scale, row-check | c01, c02, c03, c04, c05, c06, c07, c08, c09, c10 |
| R-006 | fixed | comparatives | general | results, unit, lakh, scale, xbrl, scan | c01, c02, c03, c04, c05, c06, c07, c08, c09, c10 |
| R-007 | open | kpi | general | kpi, revenue-definition, deck, annual-report, derived |  |
| R-008 | fixed | stores | general | share-capital, results, scale | c01, c02, c03, c04, c05, c06, c07, c08, c09, c10 |
| R-009 | fixed | raw_fetch | general | fetch, nse, bse, fallback, raw |  |
| R-010 | fix_written | pages | general | ocr, hp | c01, c03, c04, c10, c15, c16, c19, c22, c24, c25, c26, c28, c30, c50, c51, c60, c72, c80, c82, c83, c84, c85, c89, c91 |
| R-011 | fix_written | transcripts | general | transcripts, ocr |  |
| R-012 | open | docs_collect | general | transcripts, raw_fetch |  |
| R-013 | open | comparatives | general | ocr, R-010 |  |
| R-014 | open | docs_collect | general | trial1, raw_missing |  |
| R-015 | open | comparatives | general | trial1, not_extracted |  |
| R-016 | open | kpi | general | trial1, not_extracted |  |
| R-017 | open | kpi | general | trial1, wrong_row |  |
| R-018 | open | holding | general | trial1, raw_missing |  |

## R-001 (open, part `guidance`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, pilot10, n10): What guidance did management give on margins for the year, and did it change between calls?
2. **What the problem was:** Worded guidance (no number) is missed, and widening the sentence patterns loses right rows on unseen stores **Root cause:** pilot3/guidance.py worded path: four worker rounds (T-214 fix B) each failed on fresh stores; tag-question ban ignores who speaks; accounting-policy pages are in scope
3. **What was missing:** a guidance reader that knows the document type and who is speaking (management vs analyst); a test set of worded-guidance sentences from unseen stores
4. **How it was fixed:** not written; Claude to redesign per document type and speaker; evidence D:/RealityEngine/tg_build/fixB_evidence
5. **What can come next:** Claude redesigns the worded path per document type and speaker, measured on unseen stores with zero right rows lost before it enters the build
- **Code:** reality_engine/pilot3/guidance.py::worded path
- **Store tables touched:** guidance
- **Tags:** guidance, worded-guidance, transcript, speaker; **scope:** general
- **Stores repaired:** -; runs: -

## R-002 (fix_written, part `docs_collect`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, c01): What did management say on the last call about order inflow and margins?
2. **What the problem was:** Store holds no call transcript: 0 transcript_statement and 0 guidance rows (38 of 93 queue companies) **Root cause:** most of these companies file no call transcript on either exchange: of 37 queue companies with none in the store, BSE (feed to 19 Oct) and NSE (listing to 16 Nov) show transcripts for 3 (no BSE code, NSE only); 34 file none since 2024-04; the held BSE feed also stopped on 19 Oct, before the Q2 FY27 calls
3. **What was missing:** a transcript fetch beyond the BSE API (NSE listing), the BSE feed after 19 Oct, and a 'no call filed' record so an empty store is not taken for an extraction gap
4. **How it was fixed:** fetch family approved 16 Nov: nse_announcements listing for the queue + --attachments-only transcript (600 files, 52 companies, 610 MB, on Drive) and fetch_bse_announcements_daily 19 Oct-16 Nov (35,336 rows copied into reality_engine/data/bse_announcements.db; 34 queue companies filed a Q2 FY27 transcript, none of the 34 with no transcript). Next: rebuild docs_collect + transcripts + guidance store by store; a company with none on either exchange is recorded as no call filed, not a gap
5. **What can come next:** rebuild docs_collect, transcripts and guidance store by store on the 91 build; record no-call-filed companies; keep the daily BSE feed running
- **Code:** reality_engine/scripts/nse_announcements.py::AnnouncementFetcher.download_kind, reality_engine/scripts/fetch_bse_announcements_daily.py::main, reality_engine/pilot3/docs_collect.py::discover
- **Store tables touched:** doc, doc_page, transcript_statement, guidance
- **Tags:** transcript, fetch, nse, bse, no-call-filed; **scope:** general
- **Stores repaired:** c08; runs: 20261116T160339

## R-003 (fixed, part `events`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, c01): How large are the recent order wins against annual revenue, and over what period are they executed?
2. **What the problem was:** 0 event rows although 19 held announcements are order wins ('secured a new work order of Rs. 300 Crores') **Root cause:** pilot3/events.py had no order-win kind and event has no value column
3. **What was missing:** an order-win event kind and a value column on events
4. **How it was fixed:** pilot3/order_wins.py (prescribed Regulation 30 table by label, headline fallback) writes order_win in the events part; c01: 19 rows, Rs 6,361 crore, 2.5 s repair
5. **What can come next:** T-025: execution period and customer per order, order book vs revenue cover in the backtest timing
- **Code:** reality_engine/pilot3/order_wins.py, reality_engine/pilot3/events.py
- **Store tables touched:** order_win
- **Tags:** events, order-win, regulation-30, announcement; **scope:** general
- **Stores repaired:** c01, c02, c03, c04, c05, c06, c07, c08, c09, c10; runs: 20261116T054008, 20261116T054133, 20261116T054138, 20261116T054142, 20261116T054146, 20261116T054151, 20261116T054155, 20261116T054159, 20261116T054203, 20261116T054207

## R-004 (fixed, part `stores`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, c01): How have FPI and mutual fund holdings moved over the last four quarters?
2. **What the problem was:** shp_category holds promoter and public only (2 rows per quarter, source shp_index); no FPI, MF, insurance or pledge rows **Root cause:** pilot3/stores.py build_shp read only the local pilot folder raw/nse_shp_xbrl_pilot (none of these companies' files); their filings since 2024-04 are on Drive under nse_shp_xbrl_universe (T-209), never looked up
3. **What was missing:** a lookup of the universe shareholding folder on Drive (T-209); BSE shareholding for BSE-only companies (c10)
4. **How it was fixed:** stores._shp_parsed looks up each file shp_index names in the pilot then universe folder, on disk or on Drive via raw_store (temp copy deleted). Applied c01-c09 (16 Nov), each refused by the gate and accepted after a check: no shareholding percentage changed, 358-757 category rows and 15-468 named holders added per store, KPI verdicts unchanged. Share counts now also come from intra-quarter shareholding filings, so allotments show earlier (c09: 187.2 m -> 464.3 m shares from 1 May 2026 instead of 14 May; c07 book value per share H1FY27 16,329 -> 133.57, the old figure used a bad 694,000-share quarterly row). c10 has no shareholding index (fetch gap). Quarters before 2024-04 are held nowhere
5. **What can come next:** BSE shareholding fetch for BSE-only companies; ISIN backfill on shp_index
- **Code:** reality_engine/pilot3/stores.py::_shp_parsed, reality_engine/pilot3/stores.py::build_shp
- **Store tables touched:** shp_category, shp_holder, shp_pledge, share_capital, valuation_daily
- **Tags:** shareholding, xbrl, fpi, mutual-funds, drive; **scope:** general
- **Stores repaired:** c01, c02, c03, c04, c05, c06, c07, c08, c09; runs: -

## R-005 (fixed, part `kpi`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, c01): What is the order book and how many years of revenue does it cover?
2. **What the problem was:** 117 of 182 kpi_series rows quarantined, 13 verified **Root cause:** kpi.page_money_unit read only billion/million page declarations, so bare table figures on a page printed 'Rs. in Lakhs' were stored as crore (100x); the row checker's page_unit then quarantined them, and also quarantined a correctly rescaled row because it compared units only
3. **What was missing:** lakh and crore page declarations in kpi.page_money_unit; a unit check that accepts a correctly rescaled figure
4. **How it was fixed:** kpi: lakh/crore page declarations (declared only; two different declarations = unsure); row_checks.check_page_unit passes a row whose value is exactly the printed number moved from the declared scale. Applied 16 Nov to all ten stores after a hand-read of each diff: every re-valued row divided by exactly 100; rows dropped without a twin were wrong crore figures. c02 accepted with Shivam's OK although 4 verified Q4 rows derived as FY - 9M from the deck are no longer written (the annual report's revenue now disagrees with the deck's: R-007 restores them once revenue captions are told apart)
5. **What can come next:** R-007 (deck vs annual report revenue captions) restores the 4 derived Q4 rows on c02
- **Code:** reality_engine/pilot3/kpi.py::page_money_unit, reality_engine/pilot3/kpi.py::_page_unit_canon, reality_engine/pilot3/row_checks.py::check_page_unit, reality_engine/pilot3/row_checks.py::_rescaled_exactly
- **Store tables touched:** kpi_series, row_check, row_check_fail
- **Tags:** kpi, unit, lakh, scale, row-check; **scope:** general
- **Stores repaired:** c01, c02, c03, c04, c05, c06, c07, c08, c09, c10; runs: 20261116T145556, 20261116T145711

## R-006 (fixed, part `comparatives`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, c01): What was the full-year profit after tax, and does the order book cover three years of revenue?
2. **What the problem was:** Printed results rows of three filings stored 100 times too large (full-year PAT 1,857.67 crore for 18.58); the row checker then quarantined right KPI rows as 'part, not total' **Root cause:** pilot3/comparatives.py _unit took 'crore' from a note sentence on a page printed in lakhs whose unit line is missing from the text layer; a declared scale was never tested against XBRL
3. **What was missing:** a rule that only a declared unit counts, and a cross-check of the declared scale against XBRL
4. **How it was fixed:** _unit reads only a declared unit ('in lakhs', 'Rs. Crore'); _roles lets an XBRL-confirmed scale beat a declared one. Unseen ten-company store (copy diff, 16 Nov): 0 values changed, 0 rows lost; 698 rows on 6 pages only gained the label 'scale from XBRL'
5. **What can come next:** apply the XBRL scale check to every page-read table, not only printed results
- **Code:** reality_engine/pilot3/comparatives.py::_unit, reality_engine/pilot3/comparatives.py::_roles
- **Store tables touched:** fin_quarter_printed, fin_quarter_current, kpi_series, row_check
- **Tags:** results, unit, lakh, scale, xbrl, scan; **scope:** general
- **Stores repaired:** c01, c02, c03, c04, c05, c06, c07, c08, c09, c10; runs: 20261116T054404, 20261116T092917, 20261116T092943, 20261116T093035, 20261116T093154, 20261116T093301, 20261116T093353, 20261116T093447, 20261116T093514, 20261116T093845

## R-007 (open, part `kpi`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, c02): What was the Q4 revenue, and how did it move from the year before?
2. **What the problem was:** After R-005 the annual report's revenue rows (lakh pages) are read correctly and disagree with the deck's 'Revenue': FY24 standalone 665.57 crore (AR, revenue from operations 66,556.67 lakh) against 706.7 (deck); the cumulative derivation then refuses Q4 = FY - 9M, so 6 derived Q4 rows (4 verified) are no longer written **Root cause:** not diagnosed: the deck's 'Revenue' line probably includes other income (706.7 - 665.57 = 41.1); kpi maps both captions to one metric 'revenue'
3. **What was missing:** separate metrics for 'revenue from operations' and deck 'Revenue' (likely incl. other income)
4. **How it was fixed:** -
5. **What can come next:** diagnose on c02, split the captions in kpi, re-derive Q4 = FY - 9M from like-for-like lines
- **Code:** reality_engine/pilot3/kpi.py::derive_quarters, reality_engine/pilot3/kpi.py (revenue captions)
- **Store tables touched:** kpi_series
- **Tags:** kpi, revenue-definition, deck, annual-report, derived; **scope:** general
- **Stores repaired:** -; runs: -

## R-008 (fixed, part `stores`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, c07): What is the book value per share now?
2. **What the problem was:** share_capital holds 694,000 shares for 2026-09-30 from the quarterly results (source 'quarterly'), against 84.8 million in the shareholding pattern of the same date **Root cause:** SPMLINFRA's Q2FY27 consolidated results XBRL filed paid-up equity capital Rs 13.88 lakh against Rs 17.83 crore in the standalone filing of the same day (a filing slip); share_capital derived 694,000 shares from it
3. **What was missing:** a reconciliation of share counts between the standalone and consolidated results filings of one quarter, judged by the shareholding total
4. **How it was fixed:** Third version (16 Nov evening): when the standalone and consolidated results filings of one quarter end differ by more than 1% in share count, the row further from a reference count is dropped (stores._parent_share_count via stores.reconcile_share_count, after build_shp, before build_share_fallback). Reference: the shareholding-pattern total of that date, else the nearest in date among pattern totals and quarters whose two filings agree, else consolidated is dropped. Version 1 always kept standalone (wrong on c01 BLKASHYAP Q3FY25: standalone 255.44m vs 225.44m consolidated and pattern); version 2 kept standalone when no pattern total that date (wrong on c02 SEAMECLTD Q3FY20: standalone 24.53m vs 25.43m in every neighbouring quarter). c01 applied (v2, same result under v3); c07 applied with v1.
5. **What can come next:** run the same reconciliation on the 81 new stores; flag any quarter where no reference count exists
- **Code:** reality_engine/pilot3/stores.py::_parent_share_count, reality_engine/pilot3/stores.py::reconcile_share_count, reality_engine/pilot3/stores.py::build_stores
- **Store tables touched:** share_capital, ratio_panel, valuation_daily
- **Tags:** share-capital, results, scale; **scope:** general
- **Stores repaired:** c01, c02, c03, c04, c05, c06, c07, c08, c09, c10; runs: 20261116T185056, 20261116T185257, 20261116T185953, 20261116T190126

## R-009 (fixed, part `raw_fetch`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, measure10 (91 build)): Any question on VIVIANA or SAKAR (two of the 91 queue companies): their stores would hold no filing at all
2. **What the problem was:** The 91-company raw fetch logged 'no BSE scrip code' for VIVIANA and SAKAR and would have built two empty stores **Root cause:** fetch_pilot60_history lists filings from BSE only; its NSE fallback existed but was opt-in (--nse-fallback), so a run that forgot the flag silently skipped NSE-only/SME names
3. **What was missing:** an automatic NSE fallback: every company the BSE feed returns nothing for must be listed from NSE without anyone remembering a flag or writing a one-off script
4. **How it was fixed:** --nse-fallback is now on by default (argparse BooleanOptionalAction; --no-nse-fallback turns it off): any company with zero BSE rows (no scrip code, NSE-only, SME, delisted from BSE) is listed from the NSE corporate-announcements API and its attachments fetched in the same run. The 91 fetch is re-run with it before the build
5. **What can come next:** same both-way fallback for the other feeds that are single-exchange today: results XBRL is NSE-only (10 of 93 queue companies get no quarters) and the shareholding index is NSE-only (11 of 93) -> a BSE fallback keyed by scrip code; a per-company coverage line in the build that names which exchange served each part
- **Code:** reality_engine/scripts/fetch_pilot60_history.py::main
- **Store tables touched:** doc, doc_page
- **Tags:** fetch, nse, bse, fallback, raw; **scope:** general
- **Stores repaired:** -; runs: -

## R-010 (fix_written, part `pages`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, c01): Why: scanned results and deck pages carry figures that questions ask for (quarterly revenue, PAT), and the store held no text for them
2. **What the problem was:** c01 (BLKASHYAP): 38 pages routed needs_ocr had empty doc_page text; printed results rows came from a garbled scan layer ('Total Income 0313.90 95,200.40 71363]') and 8 of them were wrong figures **Root cause:** the 91 build runs no OCR part; the HP TextRecognizer output sits in cNN/ocr/ocr_textrec.db, which no part reads
3. **What was missing:** OCR text in doc_page and OCR words for comparatives/kpi on scanned pages
4. **How it was fixed:** copy cNN/ocr/ocr_textrec.db to cNN/cNN_ocr.db (the file build.ocr_inputs already reads), then store_repair --part pages (dependants). c01: 37 pages filled, fin_quarter_printed +280 rows (175 xbrl_ok, 87 sum_ok), 8 garbled rows dropped, 3 tax values corrected to the XBRL figure; 0 served rows lost
5. **What can come next:** a cell layer and OCR both read with different values keeps the layer's value and is listed in the kpi part's stats (ocr_conflicts: doc_key, page, metric, period, both values; first 50): read that list after the re-run and switch to OCR where the page shows the layer wrong (c01's garbled results layer is the known case)
- **Code:** reality_engine/pilot3/build.py, reality_engine/scripts/store_repair.py
- **Store tables touched:** doc_page, fin_quarter_printed, kpi_series
- **Tags:** ocr, hp; **scope:** general
- **Stores repaired:** c01, c03, c04, c10, c15, c16, c19, c22, c24, c25, c26, c28, c30, c50, c51, c60, c72, c80, c82, c83, c84, c85, c89, c91; runs: 20261116T225524, 20261116T230114, 20261117T025927, 20261117T030109, 20261117T031511, 20261117T032238, 20261117T032402, 20261117T032523, 20261117T032641, 20261117T032822, 20261117T033011, 20261117T035447, 20261117T035547, 20261117T040516, 20261117T041758, 20261117T042710, 20261117T042925, 20261117T043024, 20261117T043134, 20261117T043253, 20261117T043802, 20261117T044004, 20261117T044159

## R-011 (fix_written, part `transcripts`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, c06): Why: management statements and guidance are answered from transcript_statement; a call with 0 statements answers nothing
2. **What the problem was:** c06 (SUBEXLTD): 7 of 11 held call transcripts gave 0 statements (3,142 stored); the HP OCR of one cover page then emptied an eighth call (699 statements lost) **Root cause:** cover-letter fields ('Fax:', 'BSE Scrip Code:', 'NSE Symbol:', 'Encl.:') counted as colon speaker marks; 5 or more flip a name-line transcript into colon mode, which finds no speakers. Separately call_date took the letter's own date, not 'held on <date>'
3. **What was missing:** statements of every call whose filing starts with a cover letter
4. **How it was fixed:** transcripts.NOT_SPEAKERS gains Fax, Encl, BSE, NSE; call_date_of uses call_dates.call_date, whose cue now also takes 'conducted on' and a cue ending one line above the date (two dsh reviews: 52ce737f, 5ad73687). A letter that prints its own date and names the call date with no cue still gives the letter date. Tests in test_pilot3_transcripts.py. SUBEX: 0 empty calls, 6,888 statements (was 3,142)
5. **What can come next:** re-run the transcripts part on every store (store_repair --part stale) and read the call_date changes in the diff
- **Code:** reality_engine/pilot3/transcripts.py
- **Store tables touched:** transcript_statement, transcript_question
- **Tags:** transcripts, ocr; **scope:** general
- **Stores repaired:** -; runs: -

## R-012 (open, part `docs_collect`, opened 2026-11-16)

1. **Why it had to be done** (question that exposed it, c26): Why: a company whose transcripts are only links has no call statements or guidance at all
2. **What the problem was:** 15 of 109 transcript filings in the first 36 stores are a one-page letter with a link to the company website (c26 NELCAST 11 of 11, c08 NAVKARCORP 3 of 3, c07 1 of 12) **Root cause:** the exchange filing holds the cover letter only; the transcript PDF sits on the company site
3. **What was missing:** the linked transcript PDFs
4. **How it was fixed:** not written: a general fetcher that reads the URL (or the named pdf) from a 1-3 page transcript letter, downloads it to Drive via raw_store, and adds it as the transcript document
5. **What can come next:** write the fetcher after the build; measure on all 91 stores
- **Code:** -
- **Store tables touched:** doc, doc_page, transcript_statement
- **Tags:** transcripts, raw_fetch; **scope:** general
- **Stores repaired:** -; runs: -

## R-013 (open, part `comparatives`, opened 2026-11-17)

1. **Why it had to be done** (question that exposed it, c05,c07,c08,c09,c20,c21): Why did the OCR merge (R-010) get refused on most stores?
2. **What the problem was:** store_repair refused the R-010 pages repair: fin_quarter_printed rows from scanned pages are removed and some have no same-value row after (c05 12, c07 3, c08 1, c09 12, c20 4, c21 1). Most removed rows are wrong parses of a jumbled text layer (e.g. GAYAPROJ FY25 standalone total income 3,46,572.20 lakh), but a few look right (SPMLINFRA Q3FY25 PBT 126,517 thousand from 'Profi/lloss) before Excaptional ltems'). **Root cause:** Once a page has OCR text the printed-table parser reads only that text; a line the OCR splits or misreads gives no row, and the layer row it replaced is gone.
3. **What was missing:** A rule for printed rows on pages with both a jumbled layer and OCR: which source leads, and whether a layer row the OCR does not reproduce survives when it passes the checks.
4. **How it was fixed:** Proposed: parse both; OCR rows lead on a jumbled page; keep a layer row for a (period, basis, line) the OCR misses only if it passes row_checks (reconciles with its siblings); log every layer/OCR value conflict, as kpi does since R-010.
5. **What can come next:** Write the rule in the comparatives part with a test on c07 p5 and c20 p7; re-run the refused stores and accept only with zero right rows lost. Until then those stores keep their as-built rows.
- **Code:** -
- **Store tables touched:** fin_quarter_printed
- **Tags:** ocr, R-010; **scope:** general
- **Stores repaired:** -; runs: -

## R-014 (open, part `docs_collect`, opened 2026-11-17)

1. **Why it had to be done** (question that exposed it, all): Trial 1: what did the call/deck the question needs say? (e.g. NELCAST backward integration, PANAMAPET drilling-lubricant target, GAYAPROJ arbitration)
2. **What the problem was:** 28 of 182 trial-1 answers graded raw_missing: the filing that states the answer is not in the store. 37 of 91 stores hold no call transcript, 30 no investor deck, 27 neither (e.g. GAYAPROJ, NSIL, NILKAMAL, DHANBANK, HYPERSOFT); NELCAST's 11 and RANEHOLDIN's transcripts are cover letters with a link only (R-012). **Root cause:** R-002 found most no-transcript companies filed none on the exchange, but company websites and BSE/NSE attachments were not searched for decks; link-only transcripts are not followed.
3. **What was missing:** A per-company register of which calls and decks exist anywhere (exchange, company site), so 'not filed' and 'not fetched' are told apart.
4. **How it was fixed:** Proposed: R-012 link follower for transcript cover letters; a deck/transcript finder over the company IR page for the 27 companies with neither; record 'no call held' when none exists.
5. **What can come next:** Measure on the 27: how many have a deck or transcript on their IR page; then fetch and re-run docs/pages/transcripts for those stores; re-ask the 28 raw_missing questions in trial 2.
- **Code:** -
- **Store tables touched:** doc, transcript_statement
- **Tags:** trial1, raw_missing; **scope:** general
- **Stores repaired:** -; runs: -

## R-015 (open, part `comparatives`, opened 2026-11-17)

1. **Why it had to be done** (question that exposed it, all): Trial 1: three-year ROCE/ROE trend, FY24 cash flow, capex commitments, PP&E/CWIP schedule (JYOTISTRUC, VIDHIING, KRYSTAL, BIRLACABLE, POLYPLEX, SAKAR, FAZE3Q, BBL, DBOL)
2. **What the problem was:** 21 trial-1 answers graded not_extracted; 12 of them need an annual-report statement or note the store holds as page text only: cash-flow statement before FY25 (KRYSTAL, BIRLACABLE, POLYPLEX, SAKAR), the Key Financial Ratios note (JYOTISTRUC, VIDHIING), PP&E/CWIP schedule (FAZE3Q), capital commitments (BBL), other operating revenue (DBOL). **Root cause:** fin_annual_line is filled from XBRL (FY25 onward) and printed quarterly results; annual-report statements and notes are read only as page text, so earlier years and note-level lines have no rows.
3. **What was missing:** Rows from the AR cash-flow statement (CFO, capex, both columns), the ratios note (printed ROCE/ROE/margins with year), PP&E/CWIP movement and capital commitments.
4. **How it was fixed:** Proposed: an AR statement/note reader on the page-cell route (table pages already routed table_or_chart) that writes fin_annual_line rows with the printed comparative year, labelled source=annual_report; ratio_panel keeps derived values and gains a printed column.
5. **What can come next:** Prototype on the 9 named companies' ARs, hand-read 20 rows, then run as a repair part on all stores; re-ask the 12 questions in trial 2.
- **Code:** -
- **Store tables touched:** fin_annual_line, ratio_panel, page_cell
- **Tags:** trial1, not_extracted; **scope:** general
- **Stores repaired:** -; runs: -

## R-016 (open, part `kpi`, opened 2026-11-17)

1. **Why it had to be done** (question that exposed it, all): Trial 1: segment results, bank NIM, volumes (NILKAMAL Retail EBIT, DHANBANK yield/NIM, ALICON tonnage, DBOL cane crushed)
2. **What the problem was:** Segment tables in quarterly results (NILKAMAL p4) and KPI tables in decks/calls (DHANBANK NIM, ALICON tonnage, DBOL cane crushed/recovery, MANINFRA cash+investments 697.6 cr) are held as page text with no row; answers said 'not disclosed' and were graded wrong or partly. **Root cause:** kpi extraction keys on known metric labels; segment result tables and sector KPIs outside its dictionary give no row.
3. **What was missing:** segment revenue/result rows from the results' segment note; sector KPI dictionary entries for banks (NIM, yield, cost of deposits) and process industries (tonnage, crushing, recovery).
4. **How it was fixed:** Proposed: segment-note reader for quarterly results (Ind AS 108 table: segment, revenue, result, period columns) and dictionary entries for the named KPIs.
5. **What can come next:** Count how many of the 91 stores print a segment note; prototype on NILKAMAL p4; re-ask in trial 2.
- **Code:** -
- **Store tables touched:** kpi_series, fin_quarter_printed
- **Tags:** trial1, not_extracted; **scope:** general
- **Stores repaired:** -; runs: -

## R-017 (open, part `kpi`, opened 2026-11-17)

1. **Why it had to be done** (question that exposed it, c53,SIMPLEXINF,NSIL): Trial 1: KABRAEXTRU FY26 PAT, SIMPLEXINF FY24 order book, NSIL PE
2. **What the problem was:** 3 wrong stored rows found by the grader and checked: KABRAEXTRU kpi_series FY26 pat 34 inr_cr (AR p37 quote 'PAT\n34' is the FY25 column; FY26 is (2.44)); SIMPLEXINF order book FY24 20000 inr_cr from a quote in mns (10x); KABRAEXTRU order book 1900 inr_cr from 'INR 1,900+ Mn'; NSIL valuation_daily PE off (PAT unit vs share count). **Root cause:** kpi table reader assigns the first value of a two-column row to the current period when the row label line carries only one number; sentence reader takes 'Mn'/'mns' as crore in some phrasings; PE uses a PAT row in a different unit.
3. **What was missing:** A period check (value must sit under its column header) and a unit check for 'Mn/mns' in the kpi readers; a unit-consistent PE input.
4. **How it was fixed:** Proposed: period-column alignment check before a table row is kept; Mn/mns token mapped to inr_mn; PE built from the preferred PAT in rupees.
5. **What can come next:** Find all kpi rows with quote like 'Mn'/'mns' stored as inr_cr across 91 stores and all single-number table rows; fix, repair, accept only with no right rows lost.
- **Code:** -
- **Store tables touched:** kpi_series, valuation_daily
- **Tags:** trial1, wrong_row; **scope:** general
- **Stores repaired:** -; runs: -

## R-018 (open, part `holding`, opened 2026-11-17)

1. **Why it had to be done** (question that exposed it, SHREEREF,PANCHMAHQ,YASHHV,NITTAGELA,UNIFIED,AFCOM,SUDARSHAN,CNCRD,HYPERSOFT): Trial 1: UNIFIED promoter stake cut (4.97%) and who bought
2. **What the problem was:** 9 of 91 stores have no shp_category rows at all (UNIFIED, HYPERSOFT, YASHHV, SUDARSHAN, ...), so pilot3_holding returns nothing; the UNIFIED question was graded not_held. **Root cause:** Not yet traced: the shareholding fetch/load for these companies gave no rows (likely BSE-only or SME listings outside the NSE shareholding feed).
3. **What was missing:** Quarterly shareholding pattern for these 9 companies.
4. **How it was fixed:** Proposed: BSE shareholding fallback (already open as R-009) for every store with zero shp rows.
5. **What can come next:** Confirm the cause per company (exchange, listing type); fetch via BSE; re-run holding part; re-ask in trial 2.
- **Code:** -
- **Store tables touched:** shp_category, shp_holder
- **Tags:** trial1, raw_missing; **scope:** general
- **Stores repaired:** -; runs: -
