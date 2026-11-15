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
2. **T-215 raw_to_drive delete scope** (P1): delete must touch only the given roots; one call would have removed
   603 GB. Small, test-first.
3. **Build pipeline measure on 10 queue companies** (T-214 step 1): the pilot3 build steps (`pilot3/build_all`
   chain as used for Blue Star / s10) restricted to FY2024-25+, script layers only; record per company: wall time,
   peak RAM, disk, pages by route (`no_figures` / `text_ok` / `needs_ocr` / `table_or_chart`), and how many table
   pages the XBRL already covers. Output `D:/RealityEngine/tg_build/pilot10_measure.csv`.
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
