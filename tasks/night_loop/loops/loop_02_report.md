# Loop 2 report (session 02, Eagle, 4 Nov 2026; times are this machine's clock)

## Status: in progress

## Baseline A1 on dev (`pilot10\scores\a1_loop02_base.json`, before any fix): 571/898 = 64%
| Company | All | Some | None | Of | Rate |
|---|---|---|---|---|---|
| BAJFINANCE | 67 | 17 | 4 | 88 | 76% |
| HINDALCO | 63 | 15 | 6 | 84 | 75% |
| ETERNAL | 58 | 25 | 5 | 88 | 66% |
| HINDUNILVR | 61 | 26 | 9 | 96 | 64% |
| SUNPHARMA | 56 | 20 | 12 | 88 | 64% |
| INFY | 57 | 20 | 14 | 91 | 63% |
| KEC | 49 | 22 | 8 | 79 | 62% |
| SBILIFE | 53 | 19 | 20 | 92 | 58% |
| HDFCBANK | 57 | 28 | 16 | 101 | 56% |
| MARUTI | 50 | 31 | 10 | 91 | 55% |

A1 only says the row or page exists, not that the answer is right. Guards not run yet: `guards` needs `--base` and `--branch`, so they run with the first candidate.

Unmet needs (603 over 133 keys; "only blocker" = questions this alone holds back): `kpi_series` 292 needs, of which `segment_ebit` 54 and `segment_revenue` 50 (18 only blocker); text in transcripts 52 (35 only blocker; KEC 21, MARUTI 19); `ratio_panel` 69; `guidance` 42; `valuation_daily` 39 (`pe` 29, 17 only blocker); `fin_quarter_xbrl` 34 (`pat`: HDFCBANK 12, SBILIFE 9); `index_price` 13, `bulk_block_deal` 6, `insider_trade` 6 (all new tables).

## Findings behind the first fixes (13:30 IST)
- **Segments were lost at parse time.** `results_xbrl.db.facts` keeps only the undimensioned total; the raw XBRL holds every segment by axis and member (KEC Q2 FY27: EPC revenue 49,414,400,000, Others 6,133,000,000). Multi-segment: KEC, HINDALCO, HDFCBANK, INFY, HINDUNILVR, ETERNAL, SBILIFE (own life-insurer axes). BAJFINANCE, SUNPHARMA and MARUTI file "Single segment".
- **Bank and insurer P&L lines are not mapped:** `stores.QUARTER_TAGS` is the Ind AS set, so HDFCBANK and SBILIFE have no `pat`.
- **The window filter runs before the ratios,** so TTM values cannot see older quarters: `pe` exists only from 19 Oct 2026, and FY26 `roe`, `roce` and the days ratios are absent.
- **Transcripts:** KEC's real PDFs were already held in `raw\kec_transcripts` but the profile build reads only the manifest. MARUTI's are only on its JavaScript site.
- **22 needs name metric `guidance`,** which no row can carry (rows carry the real metric, such as `order_intake`). They stay unmet however good the table is. For the wrapper: A1 could read this as "any guidance row in that period", but that is a grader change, so I have not touched it.
- **A few A1 needs cannot be met truthfully:** a company with no bulk or block deal has no row, and "none" is the correct answer. Hindalco Q2 FY27 is not filed yet. Workers are told not to add placeholder rows.

## Decisions (logged for the wrapper to overrule)
1. **Compute-only margin, a possible deviation from "nothing older".** A TTM value on a day inside the window needs quarters before it. Rows from already-held XBRL stores back to 2024-10-01 are used as inputs only and never appear in answer tables; no document is read and nothing is fetched. It is off unless the profile sets `compute_start`, and I have not set it in the real profile. To reject it, leave the key out.
2. **Single-segment filers** get one `single_segment` row equal to company revenue and EBIT, `is_reported` 0: a true answer, marked as derived.
3. **KEC transcripts added to the raw set from held files,** no download: 4 rows appended to `pilot10aw\manifest.csv` (backup `manifest_before_kec_transcripts_2026-11-04.csv`, script `scratchdd_kec_transcripts.py`), known_at from the filed cover letter. Pilot10 baseline not rebuilt; candidate on copies `scratch\c_kec*.db`.
4. **MARUTI transcripts not fetched this loop.** Time-boxed: the site renders by JavaScript, the pages tried give no link, and Playwright is not installed. 19 needs stay unmet. Next attempt: a browser session or a headless fetch for `marutisuzuki.com/corporate/investors/company-updates`.

## Workers (Sonnet, DeepSeek peak; started 13:35 IST)
| Name | Branch | Brief | Target | Status |
|---|---|---|---|---|
| l2segments | `Eagle-sonnet-l2segments` | `loop_02_worker_segments.md` | `kpi_series.segment_*`, 104 needs | running |
| l2structured | `Eagle-sonnet-l2structured` | `loop_02_worker_structured.md` | bank and insurer lines, valuation, FY ratios, share capital, 3 new tables, 200 needs | running |

## Build of pilot10 (done, 13:15-13:23 IST, rc 0 on every part)
- Done by the wrapper before this restart: `docs_collect` 512 s, `build_truth_snapshot` 1,249 s.
- Seconds per part: registry 5, pages 52, stores 156, ratios 4, kpi 230, transcripts 4, guidance 5; total 456 s. Runner `pilot10\scratch\build_parts.sh`; log `pilot10\logs\timings.tsv`.
- Weak spots seen in row counts: SBILIFE 8 XBRL quarter rows and no ratio, valuation or share-capital rows; HDFCBANK 48 XBRL rows, 16 ratio rows and no `pe`; HINDALCO no `pe`; `pe` filled on only 2-11 of 269 days elsewhere. No `transcript_statement` rows for ETERNAL, INFY, KEC, MARUTI.
- Pages needing OCR, not run this loop: 865 of 20,865, listed in `pilot10\logs\needs_ocr_pages.csv`. Largest: INFY announcements 200, SBILIFE results 68, HDFCBANK results 50, ETERNAL annual report 53.
- Seen in the document counts: KEC has 4 "transcripts" of 4 pages in total and MARUTI 5 of 5 pages, so these are cover letters and not transcripts (MARUTI already reported by the wrapper; KEC is new). HDFCBANK has one 1-page deck; INFY and ETERNAL have no deck.

## Store gaps (done except snapshot)
- Fetched 19 Oct-4 Nov into normal places with existing fetchers (`D:\RealityEngine\pilot10\scratch\store_gaps.sh`, log `pilot10\logs\store_gaps.log`): NSE/BSE bhavcopy, delivery, bulk/block, insider, corp actions, indices; loaded; `build_bulk_block_deals` 1,748 rows upserted.
- `shp_index` now has Sep 2026 for all 10. SHP XBRL for the window: 51 files, 28 new, in `D:\RealityEngine\raw\nse_shp_xbrl_pilot` (`scratch\fetch_shp10.py`).
- **Finding:** shareholding filings carry old ISINs for 5 of 10 companies (BAJFINANCE INE296A01016, HINDALCO IN9038A01010, HDFCBANK INE040A01018, INFY IN9009A01011, SUNPHARMA INE044A01010), absent from `symbol_isin_history`. An ISIN filter returned nothing. Added to `pilot10_profile.json`.
- **Finding:** `build_truth_snapshot` failed: `raw_market/masters` absent on this laptop (raw_market archived as 7z on `gdrive:InfoDiffusion_archive/raw_market`). Restored masters and corpact folders from the archive with skip-existing. The failed attempt's 12 KB `.building` file was removed.
