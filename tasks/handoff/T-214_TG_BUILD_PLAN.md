# T-214 Telegram build: plan and the fixes that come first (Wolf, 15 Nov 2026)

Ticket: T-214 (with T-178, T-215, T-216, T-213, T-113, T-025, T-141, T-111)

## Shivam's rulings behind it (14-15 Nov)
- A universe-wide model-read build is unaffordable in tokens. Build stores **on demand per company** from raw already
  held; tune answers across many companies, never one (one-company tuning overfits).
- Priority list = companies posted in the paid Telegram community in the last 60 days (topic 683 PEAD "Great
  Results", topic 7 Big Orders). Fundamentals from FY2024-25 onward; prices and technicals may use longer history.
- Ranking: PEAD score from the cards (read by Haiku subagents, under 100k context each) first, market cap second.
  Tiers: 1) PEAD + order win + mcap 800-20,000 cr; 2) PEAD + order win + mcap below the list median (2,990 cr);
  3) PEAD, no order win, mcap 800 cr to median, PEAD score >= 45. Within a tier: score high to low, then smaller mcap.
- agy model order: `gemini-4-argon-high` until its weekly limit is used, then `gemini-4-hydrogen-high`; high only.
  Haiku for image reading (cheaper than Argon).
- Pre-build fixes: whatever known issue can be fixed in 1-2 days is fixed before the batch build starts.

## Files (D:/RealityEngine/tg_build/, private: paid-community content never goes to GitHub)
- `companies_60d.csv` (653 companies, 15 Sep-14 Nov), `companies_60d_mcap.csv`, `build_list_800_20000cr.csv` (368).
- `pead_images/` (507 cards), `pead_sheets/` (43 stitched header sheets), `pead_reads/batch_*.jsonl` (Haiku reads),
  `pead_scores.json` (507 reads, 506 resolved to ISIN; PENINSLAND unresolved; 24/24 spot-checked right).
- `priority_list.csv` (all tiers), **`build_queue.csv` (93: tier 1 = 11, tier 2 = 6, tier 3 = 76)**.
- Refresh: `python reality_engine/scripts/tg_backfill.py --topics 7,683`, then
  `python reality_engine/scripts/tag_telegram_posts.py`, then
  `python -m reality_engine.scripts.tg_company_mentions --topics 7,683 --no-download`.
  PEAD cards are downloaded by the session helper used on 14 Nov (date-bounded `iter_messages`, topic 683, photos
  only); market cap = 3 Nov close x latest SHP promoter+public shares, fallback `company_forensic_health` FY26.

## Pre-build fixes, in order (target: done within 1-2 days, then the batch)
1. **T-178 salvage test** (P1, first): can the first-build facts (`ar_facts.db` 33M, `deck_figures.db` 11.8M,
   `concall_facts.db` 720k items) be verified against page text, re-keyed with the label map + period engine, and
   re-dated (fiscal year from the report text, known_at from the filing record)? Decides how much of the build needs
   no model call. Plan: `tasks/FABLE_TESTS_2026-11-10.md` section 2. Script work, DeepSeek or Argon worker.
   **Result 15 Nov: audit-only** — verified+re-keyed facts recall 47.4% vs the r10 script's 26.9%, but frozen
   precision 78.3% (bar 95%), so no first-build facts enter the build as a candidate layer; every page the build
   needs is read. Script `reality_engine/scripts/t178_salvage.py`, numbers in the Fable-tests section 2 result.
2. **T-215 raw_to_drive delete scope** (P1): delete must touch only the given roots; one call would have removed
   603 GB. Small, test-first.
3. **Build pipeline measure on 10 queue companies** (T-214 step 1): the pilot3 build steps (`pilot3/build_all`
   chain as used for Blue Star / s10) restricted to FY2024-25+, script layers only; record per company: wall time,
   peak RAM, disk, pages by route (`no_figures` / `text_ok` / `needs_ocr` / `table_or_chart`), and how many table
   pages the XBRL already covers. Output `D:/RealityEngine/tg_build/pilot10_measure.csv`.
   **Result 15 Nov:** all ten built and measured, 0 failed steps; command, columns, totals and medians are in the
   Developer Guide's "T-214 step 3" bullet (`reality_engine/scripts/tg_measure_build.py`).
4. **On-demand table-page reading** (T-214 step 2): a model reads a `table_or_chart` page only when an answer needs
   it; rows pass the independent row checks (T-113) before storage and are cached. Free readers first, DeepSeek on a
   failed check (ruling 10 Nov).
5. **T-113 row checks** for model-read rows (quote anchor, own-company figure, reconciliation, plausibility).
6. **T-025 order-win parsing** from exchange filings (value, customer, execution period): tier 1-2 companies'
   order books feed the backtest timing (ruling 18 Oct: capture durations). `tg_orders` already holds 219 Telegram
   order cards with `duration_months`.
7. **T-213 answer checks** that generalise (no per-company rule): theme-calls check (calls whose statements match
   the question's theme words must be read) and C4 comparing the stated figure with the printed segment figure.
   Measured on the built Telegram stores, with half of each company's questions frozen (T-172 method).
8. **T-216 agy retry** on transport errors (P2).
9. Known data gaps on the queue: 26 PEAD companies without a market cap, PENINSLAND unresolved, master sector labels
   useless (321 of 368 "General Diversified"): take the sector from each company's own filings during the build.

## Measured this session (for planning)
- Haiku subagent image reading: ~43k fixed + ~7k per 12-card sheet; 5-6 sheets per session (69-86k tokens).
- Blue Star store: 263 docs, 5,749 pages, 2,134 table/chart pages (~20M tokens if all read by a model up front);
  stores are 25-80 MB per company; D: has ~536 GB free.
- Answer path: run B (DeepSeek agent, p3ask, unlimited lookups) 54/64 -> 57/64 with the round-15 checker + repair
  (not blind). Grades and report: `D:/RealityEngine/reports/2026-11-14_r13_grading.html` s5b.

## Gap diagnosis on the 10 measured stores (15 Nov, read-only DeepSeek job 20261115T153222Z-4400ca40; Wolf re-checked 4 counts)
All four gaps are silent empties (rc=0). Share of the 93-company queue in brackets.
1. **No XBRL quarters (10/93):** `results_xbrl.db` holds NSE XBRL only; BSE-only companies get nothing (`pilot3/prepare.py` results query by ISIN). Fix: BSE results-XBRL fetch family keyed by scrip code. Size M.
2. **No shareholding rows (11/93):** 9 have no `shp_index` rows (index is NSE-only); 2 are dropped because `shp_index.isin` is NULL (1,654 rows / 78 symbols) and the build filters on ISIN. Fix: symbol fallback DONE 15 Nov (T-214 fix A: `gap_loop.prepare.store_copies` reads `isin IN (...) OR (isin IS NULL AND symbol=?)`; on a c07 copy `shp_category` went 0 -> 74 rows / 36 quarters, and a c01 `store_diff --parts stores` showed 0 rows removed, added or changed) + ISIN backfill (data job, not done; `shp_index` itself is untouched); BSE shareholding fetch (M).
3. **No guidance rows:** 38/93 have no call transcript in `corporate_documents`; the fetch manifest is BSE-API only, and one company's 10 transcripts held in `corporate_documents` never reached its manifest. Fix: transcript fetch family + reconcile `corporate_documents` into the manifest (M). Where transcripts exist, `guidance.py` drops cue-but-no-number sentences that fail `WORDED_MOVE` without counting them (23 and 155 sentences in two stores), and numeric answers whose metric is only in the analyst's question. Fix: widen the worded path, read the metric from the question turn, count every drop (S).
4. **Sector `unknown` (38/93):** 20 have no `company_industry` row, 18 carry an industry `sector_map.yaml` does not map. `unknown` switches off the sector KPI lexicon (62-132 KPI rows vs 357-1,417), sector topic tags and sector-fit row checks. Fix: taxonomy ingest for missing ISINs, BSE industry fetch, map the unmapped industries (S-M).
   **Fix C DONE 15 Nov (no fetch):** 38 -> 31 unknown on the 93 (55 -> 62 mapped; 3 by four new `basic_industry` mappings, 4 by the BSE industry on `board_meetings` as the last fallback). Still unknown: 13 carry an industry that no family fits (Packaging, Sugar, Gas, Paper, Lubricants, Oil Equipment, Diversified Commercial Services), 1 only a BSE value no family fits (Ceramics And Sanitaryware), 17 have no usable industry (8 "General Diversified", 2 "Other" = the 2 demo-ISIN rows, 7 nothing), so 15 real companies need a taxonomy fetch. Across the universe the family share 1,638 (30.6%) -> 1,784 (33.3%); the 63 pilot10/p20/u8/q12 company rows keep their sector (0 changed).
Also: 2 queue rows are demo ISINs (`INE_AUTO_*`, tiers 2 and 3) and must be taken out of the queue.
