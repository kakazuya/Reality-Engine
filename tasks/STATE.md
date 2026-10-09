# STATE — overwritten each session (authority: `tasks/FRAMEWORK.md`)

_Last updated: 2026-10-09_

## Done
- 2026-10-06/07: all NSE + BSE cash-segment data, NSE/BSE disclosures, NSDL FPI reports, derivatives participant data and commodities fetched from 2019-01-01 and loaded into `mkt_*` tables (~22M rows). Scripts: `reality_engine/scripts/fetch_market_raw.py`, `fetch_nse_api_raw.py`, `fetch_bse_api_raw.py`, `fetch_nsdl_raw.py`, `load_market_raw.py`. Raw copies in `reality_engine/data/raw_market/`.
- 2026-10-08: framework settled (`tasks/FRAMEWORK.md`).

## Cleanup
2026-10-08: Shivam removed 33 superseded task files with `git rm` (staged, not yet committed) and the untracked 2026-10-05 closeout.
Kept on purpose: FRAMEWORK*, STATE, council_2026-10-06/, PRICE_SIDE_DIFFUSION_STUDY, PIT_LABEL_AUDIT, FACTOR_SPINE_DESIGN, STRATEGY_TEST_PLAN, strategy_tracker (killed-strategy history), modeling_bucket_list (idea backlog).

## Settled 2026-10-08
- Proof window 2021-01 → 2025-12; 2026 is simulated as live (see FRAMEWORK §5).

## In progress
- Done 2026-10-08: BSE index history loaded, `mkt_bse_index_daily` 142,160 rows, 138 indices with data, 2019-01-01 → 2026-10-07 (all four BSE benchmark indices present; BSE Select IPO only from 2024-11).
- Done 2026-10-08: FII/DII daily cash flows from Moneycontrol's API (`fetch_fiidii_moneycontrol.py`, protobuf decoded), `mkt_fii_dii_cash` 1,924 days 2019-01-01 → 2026-10-07. Check: FII net 2022 ≈ −₹2.78 lakh cr, matching public figures.

## Truth layer (2026-10-08)
- Snapshot `reality_engine/data/snapshots/truth_2026-10-08.duckdb` (2.2 GB) built by `reality_engine/scripts/build_truth_snapshot.py`. Research reads this, not the live DB.
- Company = ISIN issuer code (`INE117A`), equity ISINs only (ETFs/INF, IN9, INE_AUTO excluded). 6,228 companies; 3,453 traded on NSE, 4,950 on BSE.
- `px_daily`: 7.21M rows (NSE when traded that day, else BSE), raw + split/bonus/rights-adjusted (`adj_*`) + total-return (`tr_close`) prices, delivery (BSE 100%, NSE 89% of rows).
- Corporate actions from NSE main, NSE SME (new fetch) and BSE (new fetch): 656 splits, 845 bonuses, 281 rights, 20 consolidations parsed; 14.5k dividends → total-return factors; 721 unrecorded splits/bonuses inferred from clean-ratio price jumps (flagged `kind='inferred'`).
- Validated: only 3 capital actions disagree with the ex-date price move; spot checks (Nestlé, Reliance, Bajaj Finance, HDFC Bank) match.
- Open flags: 457 large jumps with no clean ratio (mostly < ₹2 penny stocks and BSE-only relistings); 966 moves beyond −40%/+70% remain after adjustment (754 of them on stocks < ₹10). Rule set 2026-10-08 (FRAMEWORK §2): stocks < ₹10 excluded unless a structural fundamental shift AND technical confirmation.

## Running jobs (detached; they keep running after the Claude app closes)
| Job | Start / restart | Log | State at 2026-10-09 13:45 |
|---|---|---|---|
| Deck-figure extraction | `reality_engine\scripts\run_deck_extract.cmd` (repeats passes until nothing new is left; restarts after a crash) | `reality_engine/data/logs/extract_deck_figures.log` (+ `.passes.log`) | 2026-10-09 19:35: 116,306 pages done (112,137 read, 4,169 skipped by the page gate), 1.68M final figures, 20 pages in error (retried next pass); est. ~776k pages total (~15%). Speed 0.7-4.8 pages/s depending on LongCat/Dots throttling |
| NSE results XBRL download | `reality_engine\scripts\run_results_xbrl_fetch.cmd` | `reality_engine/data/logs/fetch_nse_results_xbrl.log` | 76,387 files on disk; last log line 52,500/52,500 ok, 0 errors (looks complete) |

To stop the extractor, end the `cmd.exe` running `run_deck_extract.cmd` and the `python.exe` running `extract_deck_figures`. Resumable: finished pages are never re-read.

## Deck figures (built 2026-10-09)
- **Sources** (`reality_engine/scripts/fetch_decks.py`; files in `reality_engine/data/decks/`; manifest table `deck_sources` in `reality_engine/data/deck_figures.db`): BSE "Investor Presentation" filings 2021-01 → 2026-09 (24,674 PDFs, 107 GB, 4 failed); for the 707 NSE-only companies, decks found in their NSE announcement history by keyword and size (1,713 PDFs, 15 GB; raw announcement JSON in `raw_market/nse_announcements/`); plus the 1,152 `corporate_documents` decks (463 meeting-intimation letters excluded). Every deck carries the exchange dissemination time (point-in-time).
- **Extraction** (`reality_engine/scripts/extract_deck_figures.py` → `deck_figures.db`: `pages`, `outputs`, `facts`, `spend`, `bad_docs`, `doc_pages`): each PDF rendered in an isolated child process (a malformed PDF can no longer kill the run). **Page gate**: pages with ≥3 text-layer numbers go to a reader; text pages with ≤2 are skipped; image-heavy pages with ≤2 go only if RapidOCR (DirectML on the RX 6700 XT, ~0.4 s/page) finds ≥2 numbers (skips ~37% of pages, est. <0.2% of figures lost). **Readers** (all free): LongCat 2.5 Preview primary + Dots 3 Note via Kilo (`KILO_API_KEY`) as second primary; Step 5 Preview second reader on weak pages. Since 2026-10-09 21:45 the primaries take turns (LongCat, Dots, LongCat...; whichever has a free slot), and second readings go through a persistent `second_queue` table read by their own pool, so a throttled Step no longer holds primary workers (before: Step at its floor of 10 left ~90 of 110 workers waiting, 0.5 pages/s). A page is saved with its primary reading first and updated when the second reading lands; above 5,000 queued pages workers wait inline again. Paid OpenCode models (MiMo, Muse) are opt-in only (`--also-primary/--also-second`). Ornith (local GPU) dropped: 0.11 pages/s; GPU kept for RapidOCR. Tests: `reality_engine/tests/test_extract_deck_figures.py` (12).
- **Quality test** (40 pages, hand-checked slides; share of figures identifiable = unique label+period+unit): Haiku 5.5 100%, Step 96.3%, Muse 93.5%, Dots 90.4%, Ornith 85.6%, LongCat 85.2%, MiMo 82.7%; none misread a number. Local models on Vulkan failed (Qwen3-VL-4B 31.7% identifiable, MiniCPM-V 4.6 27% recall, GLM-OCR ignores the format); Vulkan reads images ~20x slower than ROCm on this card. Finding: PDF text layers can be wrong (VENKEYS: 204.33 in text vs 254.33 printed; totals confirm the image), so text-layer recall is a guide, not ground truth.
- **Value check** (20-deck pilot): 77% of figures are operating KPIs the DB does not hold (volumes, capacity, beds/ARPOB, inventory, order book, segment revenue). Overlapping headline figures match `quarterly_financials` (SOBHA Q1 FY27 EBITDA and PAT exact, revenue within 4%). Note `quarterly_financials` is mostly yfinance (13,552 of 15,261 rows, no filing dates).
- **Limits**: the OpenCode Go caps (rolling 5 h / weekly / monthly) are ONE budget for the whole account, shared with Shivam's own coding; the 2026-10-09 run used 99% of the weekly and 93% of the monthly allowance, which is why paid models are now opt-in. OpenCode refuses MiMo/Muse with HTTP 402 before the pipeline's own spend estimate reaches the plan cap (MiMo was cut off at ~$7.6 of the $12 / 5 h estimate); a 402 now benches that model for 30 min and its pages go to the free reader. Free models are "limited time": when the free list at https://opencode.ai/v2/docs/console/go changes, re-run the 40-page quality test before switching. Muse Contributor prompts are used for Meta training (public filings only).
- **Claude Haiku 5.5 queue** (`reality_engine/scripts/claude_page_queue.py`): `export` claims unread pages oldest-decks-first (extractor goes newest-first) into `reality_engine/data/claude_queue/run_*/bNNN/`, Haiku 5.5 helper agents (15 pages each, max 20 at once) write `NNNNN.txt`, `import` loads them as model `claude-haiku-5-5`; unanswered claims fall back to the extractor after 24 h. 5,699 pages done in 19 waves (as of 2026-10-10 03:55; wave cap now 80% of the 5-hour limit per Shivam; always verify an export wrote manifest.json and 300 pages before launching agents, one silent export failure on 2026-10-10) (waves 6-13 on 2026-10-09 evening, 300 pages each, ~9% of the Pro 5-hour limit per wave); label junk 1.2% (waves 1-5). Agent instructions live in `reality_engine/data/claude_queue/AGENT_INSTRUCTIONS.md` (includes the down-arrow-as-negative rule from wave 6 on). Agent instruction: image wins on different digits, keep text-layer decimals when the number is the same, skip product/model/certification codes and axis ticks; down-arrow/decline figures are written as negative (rule added for wave 6+; wave 5 lost the sign on ▼ figures).
- Approved and queued, not started: extend the BSE announcement feed back to 2019. Pending Shivam: annual-report dating via AGM notices.

## Next (in order)
1. Parse the NSE results XBRL into a dated quarterly-figures table linked to filing timestamps (input for the earnings-surprise card).
2. Normalise deck figures into a point-in-time KPI table (company-specific metric names, periods, units) once extraction completes.
3. Shared test harness (data loader on snapshots, 0.30% cost, after-tax P&L, benchmark selection, risk limits, fluke statistics, test ledger).
4. Hypothesis registry seeded from `tasks/STRATEGY_TEST_PLAN_2026-10-06.md` and `tasks/modeling_bucket_list.md`; re-run the results-day puzzle on adjusted prices.
5. Scheduled jobs: end-of-day update, correction run, overnight research run.

## Known data gaps
BSE insider 2023+ (paged API); MCX blocked; NSDL company-level limits need a form post; NSE FII derivative stats file ends Oct 2024 (participant OI covers after).
