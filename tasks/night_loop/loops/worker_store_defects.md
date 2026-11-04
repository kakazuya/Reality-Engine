# Worker: store defects from the 600-answer test

Goal: four database defects that gave investors wrong or thin answers are fixed by general rules, in the pilot10 build: share count, valuation history, quarterly cost lines, and year-to-date order intake.

Ticket: T-073

Evidence: measured by Opus on 5 Nov on `D:\RealityEngine\pilot10\pilot10.db`.

Defect 1, share count (5 misses: ETERNAL-079, HINDUNILVR-041, HINDALCO-041, -060, -078).
- `share_capital` for 30 Sep 2026: ETERNAL 9,210,000,000, HINDUNILVR 2,350,000,000: paid-up capital from the results XBRL, rounded and, for ETERNAL, net of the ESOP trust. `source_table='quarterly'`.
- The shareholding pattern holds the exact count as `shp_category` `category='shareholding_pattern'`, `source_kind='xbrl'`. Check: ETERNAL public 9,212,774,343 + non-promoter-non-public 437,576,304 = 9,650,350,647; HINDUNILVR 1,454,412,858 + 895,178,404 = 2,349,591,262; HINDALCO 2,247,226,523.
- `reality_engine/pilot3/stores.py` lines 583-610 use that total only where a quarter has no results row (`have` skips the rest). `reality_engine/pilot3/ratios.py:576` `_valuation` and `:470` book value read `share_capital` with no preference.
- Want: market cap and book value per share use the shareholding-pattern total wherever one is filed by that day, paid-up only as fallback. Keep the paid-up rows; point in time unchanged (each row's own `known_at`). HINDALCO's jump from 2,220,000,000 to 2,247,226,523 must stop being a false rise: the rounded row should no longer drive the series.

Defect 2, valuation history (6 misses: INFY-080 wrong, HDFCBANK-075, SBILIFE-073, ETERNAL-084, HINDUNILVR-084, BAJFINANCE-120).
- `valuation_daily` has 269 sessions from 2025-10-01 per company. Sessions with PE, first PE date: HDFCBANK 11 (2026-10-19), INFY 71 (2026-07-23), ETERNAL 130 (2026-04-28), MARUTI 130 (2026-04-28), KEC 188 (2026-01-30), BAJFINANCE 188 (2025-11-10), HINDALCO 245, SUNPHARMA 246, HINDUNILVR 255. SBILIFE has **no rows at all**, though it has 269 prices and a standalone `share_capital` from the pattern: find out why (`_valuation` picks its basis at `ratios.py:551-558`; test whether printed consolidated rows push it off standalone).
- `ev_ebitda` is far thinner: INFY 8, ETERNAL 10, MARUTI 6, HDFCBANK and BAJFINANCE 0 (lenders are expected to have none; say so in the row or tool, do not fake one).
- `_valuation` `last4` (`ratios.py:592`) needs four consecutive known quarters, then falls to `comparatives.ttm_filings` (`comparatives.py:1391`, formula F_TTM_PRINTED: last FY + YTD - prior YTD). A results table prints the last full year and the YTD columns, so TTM should be available from the first in-window results filing. INFY filed on 2025-10-16 and still has no PE until July: find why the printed route fails.
- `fin_quarter_printed` holds mislabelled cells for INFY consolidated `eps_basic`, `period_type='quarter'`: 2025-03-31 = 71.58 (the full year), 2025-09-30 = 38.51 `sum_ok` (the half year), 2025-12-31 = 16.98 `unchecked` beside XBRL 16.17. `printed_quarters` (`comparatives.py:1366`) must not feed those into a TTM. Fixing the cause is better than a filter.
- Want: PE and, for non-lenders, EV/EBITDA on every session from the company's first in-window results filing that lets a TTM be formed honestly, and never a value from data filed after that day. `pilot3_ratio` or the row states how the TTM was formed.

Defect 3, quarterly cost lines (2 misses: HINDUNILVR-103 wrong, HINDUNILVR-109).
- `stores.py:108` `QUARTER_TAGS` lacks `PurchasesOfStockInTrade` and `ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade`. HUL Q2 FY27 XML (`D:\RealityEngine\raw\raw_market\nse_results_xbrl\INTEGRATED_FILING_INDAS_1748161_28102026072448_WEB.xml`) prints 36,540,000,000 and -5,070,000,000, which is exactly the Rs 3,147 crore gap between its lines and total expenses.
- Want: both lines stored, the same captions read by `comparatives` and `lexicon/results_lines.yaml`, and a derived `gross_margin` formula: (revenue - materials - purchases - inventory change) / revenue, non-lenders only. HUL Q2 FY27 must come out about 47.6%. Also check that no other expense tag is dropped: for each company, reported lines must add to `total_expenses` for the latest quarter; list any gap over 1%.
- HINDUNILVR-109 asked for EBITDA margin in each quarter; Q4 FY26 was not given as a quarter though `fin_quarter_xbrl` holds 2026-03-31 lines. Find whether the row is missing or the tool missed it.

Defect 4, year-to-date intake (1 miss: KEC-088).
- `kpi_series` id 663: KEC order intake 13,500, `fiscal_period='H1FY27'`, from a press release filed 2026-11-02 (`KEC/results_press_release/878bb0f6-b1cf-4f1d-a08e-b62f26394f7f.pdf` p3); the company's "YTD" figure runs past 30 September, so the H1 label overstates H1. `kpi.py:776` `_ytd_period` assumes a Q2 document's YTD is the half year. Also id 668 stores the same 13,500 as `dimension='T&D'` ("~70% from T&D" follows it in the quote), and id 203 is the same pattern for 9MFY26.
- Want: a flow printed as YTD in a document filed after the quarter ended is labelled year-to-date as of the filing date, not as the half or nine months, unless the text ties it to the period end. A total whose quote gives a segment's share stays a total. Read the KEC page and say what H1 intake really was if the filing states it.

Data: `D:\RealityEngine\pilot10\scratch\w_t073.db`, copied from `D:\RealityEngine\pilot10\pilot10.db` by sqlite3 `backup`. Never write `pilot10.db` itself. Check free RAM first; wait above 2.5 GB. One heavy job at a time. Fast check, foreground: `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part stores --symbols HINDUNILVR --out D:\RealityEngine\pilot10\scratch\w_t073.db`, then `--part comparatives` and `--part ratios` the same way, `--part kpi --symbols KEC`. Build the other companies last, once.

Accept: print a before and after table from the copy for each.
1. Latest market cap uses 9,650,350,647 shares for ETERNAL, 2,349,591,262 for HINDUNILVR, 2,247,226,523 for HINDALCO.
2. Sessions with PE per company, before and after; SBILIFE has rows; INFY has at least 200 of 269 and its PE on 2025-11-14 is printed with its inputs. Hand-check one date per company against the filing's printed EPS. No session uses a filing later than itself: write a test that proves it.
3. HUL Q2 FY27 gross margin about 47.6%; expense gap list printed.
4. KEC 13,500 no longer labelled H1FY27 or T&D.
5. A1: `python -m reality_engine.night_eval.answerable --db D:\RealityEngine\pilot10\scratch\w_t073.db --qset tasks/night_loop/questions/dev.jsonl --out D:\RealityEngine\pilot10\scratch\a1_t073.json`, per company; live score is 730 of 898. List any company below its current score and the rows behind it. Do not change the grader.
6. `python -m reality_engine.pilot3.checkpages run`: at least 145 found. `python -m pytest <each changed test file> -q`, one file per process under the RAM watchdog, new tests from these rows. `mcp__code-tools__typecheck` on changed files: no new errors. List any test expectation you changed and why, `_ytd_period`'s above all.

Rules: general wording, no company names in code. Do not touch `reality_engine/pilot3/number_check.py`, `answer_record.py` or `plugins/reality-data/server/server.py`: another worker owns those. Leave the other 7 store misses (pledge column, related-party table, listed-subsidiary prices, text in images) alone, and do not fetch anything.

Files: `reality_engine/pilot3/stores.py`, `ratios.py`, `comparatives.py`, `kpi.py`, `lexicon/results_lines.yaml`, `plugins/reality-data/server/lookups_pilot3.py` only if a row needs surfacing, their tests in `reality_engine/tests/`, your lines in `docs/PILOT3_BLUEPRINT.md` and guide section O in `docs/DEVELOPER_GUIDE.md`. Do not touch `tasks/`.

Stop if: free RAM stays under 2.5 GB for 10 minutes, or the INFY TTM needs a filing the pilot10 raw set does not hold: then report which filing, and carry on with the other defects.

Budget: 90 tool calls. End with the before and after tables, A1, test results and a `Docs updated:` line. Then wait: Opus reviews in this same session and sends the next round.
