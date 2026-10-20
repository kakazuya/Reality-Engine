# STATE — overwritten each session (authority: `tasks/FRAMEWORK.md`)

## 2026-10-20 09:50 IST (Claude, session 9b87f729): power cut 04:30 -> 09:29; backtest starts THIS session in the afternoon
- Power lost 04:30:56 (event 6008; Shivam: the UPS does not hold even 20 min). Boot recovery ran (watchdog, PDF upload,
  re-embed, DB quick_checks, then writers). Every job was down for ~5 h.
- **Heartbeat bug fixed:** `deepseek_heartbeat.restart_dead_readers` passed a list to Popen, so cmd saw `\"python.exe\"`
  and the reader restart never worked. It now passes one string with `cmd /s /c`. Beam + MiniMax restarted 09:41 by it.
  The 09:34 scheduled run returned 0x800710E0 (task is InteractiveToken: runs only while warri is logged on). Fix:
  `setup_boot_tasks_admin.ps1` now also sets the heartbeat to S4U; Shivam runs it once in an admin PowerShell.
- **DeepSeek off-peak corrected** (OpenCode Go docs): peak = Mon-Fri 01-04 + 06-10 UTC = 06:30-09:30 + 11:30-15:30 IST;
  09:30-11:30 IST and weekends are off-peak. `run_deepseek_harness.off_peak()` now encodes this (heartbeat + dsh_batch use it).
- `needs_claude.md` (04:29, DeepSeek) is still open: Beam 3.9% broken-JSON docs (32 workers?) + ok docs with ~0 kept items
  (GULPOLY 36969, IPCALAB 44750). Not handled yet.
- Windows Search: the workspace and `Downloads\InfoDiffusion_to_upload` set to NotContentIndexed (attrib +I /S /D; new
  files inherit it), because SearchIndexer was reading ~130 MB/s. D:\RealityEngine was never indexed.
- Archive of the old session (local_98041315) is refused while its phone Remote Control is on: Shivam archives it by hand.
- Shivam: backtesting starts here once he wakes up (afternoon). Begin with H01 PEAD from `tasks/HYPOTHESIS_REGISTER.md`.

## START HERE - hand-off 2026-10-20 04:35 IST (Dussehra; session 10203977 "workspace check -> embeddings -> worker department")
Shivam: backtesting starts TODAY (Dussehra = Vijayadashami, 20-Oct-2026, confirmed from PIB). Start a FRESH session for it.
1. Read `tasks/HYPOTHESIS_REGISTER.md` (26 cards, written by DeepSeek, checked by Claude): the 5 starred cards run first
   (H01 PEAD, H02 bulk/block deals, H03 CMF/delivery-weighted CMF, H04 momentum vs reversal, H05 delivery spike; H06 is an
   overlay on H01). All 5 are READY on price/flow data. H14 guidance raises needs the transcript run below.
2. Shared context for workers: `reality_engine/data/hotline/` (README protocol, decisions.md = 121 Chesterton fences,
   hotline.md log, generated/ session digests + live state rebuilt before each DeepSeek run).
3. Department: Claude orchestrates; DeepSeek (dsh, xhigh, off-peak only: peak = Mon-Fri 06:30-09:30 + 11:30-15:30 IST, paid) reviews; Beam + MiniMax (free,
   OpenCode Go, both keys) read. Every Go call uses a stable x-opencode-session (go_session.py).

Running detached (hidden, survive app restarts; WMI + conhost --headless):
| Job | State 04:35 | Check |
|---|---|---|
| Beam transcripts, prompt v3 (`concall_deepseek --model beam-free`, shard 1,2,3/4, 32 workers) | ~13.7k queued incl. v2 re-reads; ~48 s each | concall_facts.db cc_docs model='beam-free', checks_json prompt v3 |
| MiniMax transcripts, prompt v3 (shard 0/4, 16 workers, ~high effort) | ~4.5k queued | review 3: BASF 14752 + SINGERIND 80180 regression |
| Nemotron-8B embeddings (DeepInfra) tiers 0-2 -> data/vector_index_nemotron8b | was ~78% at 03:35, finishing ~04:00-04:30 | log reembed_qwen_nebius_vector_index_nemotron8b.log RUN_END |
| Drive upload (rclone, 24 MB/s 01-07 IST) | 160 GiB left at 02:58 | drive_upload_check.py |
| PIB English backfill | at 2023-05 | pib_backfill.log |
DeepSeek heartbeat: Task Scheduler `RealityEngine-DeepSeekHeartbeat` hourly (run_deepseek_heartbeat.cmd -> deepseek_heartbeat.py):
restarts dead Beam/MiniMax readers (no LLM), then off-peak runs one DeepSeek check -> hotline.md entry. Claude is never woken;
**a new Claude session reads `reality_engine/data/hotline/needs_claude.md` FIRST** (DeepSeek writes it when it needs help), then hotline.md tail.
Next after transcripts: Nemotron-1B NVFP4 on annual reports (~$9.06, 906M tokens measured), only after the readers finish.
Search switch (hybrid_search -> Nemotron-8B index for tiers 0-2) not done yet. DeepInfra ~$2.5 left after Nemotron-8B.
Embedding retrieval test (51 q): Nemotron-8B hit@5 94.1% > Gemini-001 88.2% > Nemotron-1B (BF16 = NVFP4) 90.2% > Qwen3-8B 84.3% > EmbeddingGemma 80.4% > bge-small 51.0%.


## START HERE - hand-off 2026-10-19 19:30 (session "Pipeline framework and detached jobs review" closed)
Rules (Shivam): data gaps, query gaps, latency first (PIPELINE_TODO Phase Q -> A -> B -> C); NO backtests until he says;
new tables / files only, verify on real rows (dates vs source, counts, hand samples), never break running jobs; measure.
**Power: full GPU load tripped the UPS twice today.** Re-embed runs at --duty 0.6; never run the GPU flat out.
After any reboot `RealityEngine-BootRecover` (S4U, at startup + logon) runs scripts/boot_recover.py: readers at once,
quick_check of all DBs after an unclean shutdown (once per boot, ~40 min), then writers. Status in
data/logs/boot_recover_status.json + watchdog report. Nothing needs restarting by hand.

Running (detached; logs in reality_engine/data/logs):
| job | launcher | state 19:26 | next check |
|---|---|---|---|
| Gemma re-embed (GPU 0.6) | run_reembed_gemma.cmd | 58,368 done; tiers 0-2 (transcripts, macro, decks) 282,519 left ~28 h; all 2.27M ~8 days | after tiers 0-2: retrieval test vs bge, then switch readers (see below) |
| PDF/deck upload to Drive | run_pdf_upload.cmd (rclone, 4 MB/s; 512 KB/s 05-13) | 53,562 files / 284 GiB at 15:15; ~1.3 days | drive_upload_check.py (NOT --links while uploading) |
| Shareholding XBRL | run_shareholding.cmd | 20,500 / 50,485 downloaded, then parse | check 10 cos x 2 quarters vs exchange site |
| PIB English backfill | run_pib_backfill.cmd | at 2022-07 | - |
| Policy register (macro docs) | run_policy_register.cmd | running | quote_ok >= 98%; then --source pib |
| DB backup | task DBBackup 05:00 (S4U) | full set staged (23 parts, 22 GB) | 05:00-13:00 Oct 20: rclone check passes, state complete |
| EOD market | task EODMarket 19:35 weekdays (S4U) | first S4U run tonight | eod_market.log; snapshot rebuilt; query_speed report |
Finished today: nse_pr (circuit_hits 482k, price_bands 4.04M, 1,927 days), NSE industry (3,155 of 3,178 classified,
195 basic industries), PIB regional 20-day sample (2026-09-26..10-15), DeepSeek concalls (1,056), 2026 chunks.

Next work, in order:
1. A2 translations: run `pib_regional --match title` and `--match body` for 2026-09-26..2026-10-15 (CPU Gemma: titles
   19/s, title+body 2.2/s). Title mode on 9 days: 67/75 page-linked pairs top-1 correct; misses = Tamil re-titles
   (needs body) + identical-title English duplicates (count as correct). Pick threshold, hand-check 30 matched + 30
   unique (<5% wrong), then choose backfill mode (full bodies = ~9 min/day = 13 days; titles for all + bodies for
   unmatched instead). Tables pib_ml_releases / pib_ml_match.
2. A3 mapping: policy_events.sectors (3,478 distinct strings) -> company_industry (macro/sector/industry/basic_industry)
   by Gemma similarity + hand check; companies (487 strings) -> ISIN by name (many unlisted PSUs: leave unmapped);
   policy_threads (stage chain) needs an LLM: free models only (LongCat on Go key 1 is used by the policy register).
3. Re-embed switch-over (after tiers 0-2): run the 51-question test (embed_model_test data) on data/vector_index_gemma
   vs bge; if better, point hybrid_search's ChunkVectorIndex to vector_index_gemma and embed queries with Gemma
   ('task: search result | query: ...'); add search() to query/state.py.
4. B3 check once parsed; B1 leftovers (RBI/SEBI overseas-limit rows in policy_events).
5. Phase C: index membership history (no machine-readable source found on niftyindices), order wins from BSE feed
   (needs an LLM: ask Shivam, paid models need his go-ahead), metric ontology, reconciliation.
Decisions waiting on Shivam: snapshot keep count (9 GB each, 7 = ~63 GB of ~107 GB free); order-win LLM.

Gotchas learned today: bash heredocs mangle "\n" inside Python code (use the Edit tool); .cmd launchers must be CRLF
and never edited while running; Stop-Process filters must not match Monitor/tail command lines; DuckDB capped at
4 GB (took 11 GB); results XBRL known_at can be ~1 day after the BSE results PDF (use events for timing);
results_xbrl facts: FourD (YTD) carries quarter dates -> use context not dates; join results by filings_isin.isin.

## SESSION CLOSE 2026-10-19 03:20 — (earlier)
**Shivam's order:** fix data gaps, query gaps and latency first (Phase Q + A + B in `tasks/PIPELINE_TODO.md`); NO
backtests until he says so. Implement carefully: new tables/files, verify on real rows, never break running jobs.

**Running detached (survive the session; check, don't restart unless dead):**
| Job | Launcher / log | State at close | Verify when done |
|---|---|---|---|
| DeepSeek 2026 concalls (Telegram PEAD + Big Orders companies only, 730 ISINs) | `scripts/run_concall_deepseek.cmd`; `data/logs/concall_deepseek.log`; out `data/concall_facts.db` | **DONE 2026-10-19 03:35** (RUN_COMPLETE): 1,056 ok, 131 cover letters, 14 duplicates; $17.69 est. on key 2. The last 89 ran with `--five-h-cap 1000` because the runner's own 5 h guard counted spend from before Go's window reset (Shivam) | concall_deepseek_check: 3 checks fail on 23 docs (labels, see below); concall_facts_checks re-run; concall_query_test see below |
| Quarterly results Mar-2025 -> now (NSE Integrated Filing XBRL) | `scripts/run_integrated_results.cmd`; `data/logs/integrated_results.log` | 17.5k of 30,197 XBRL downloaded (~2/s); parser runs automatically after | `results_xbrl.db` filings with period_end >= 2025-03-31 ~30k, status ok; spot-check 5 companies' revenue vs exchange site |
| PIB English backfill 2021 -> now | `scripts/run_pib_backfill.cmd`; `data/logs/pib_backfill.log`; table `pib_releases` | at 2021-03, ~30 s/day, ~1-1.5 days total | posted_at filled, bodies in search layer (raw_documents source_type PIB_Press_Release) |
| Policy register over macro docs (LongCat free on Go key 1) | `scripts/run_policy_register.cmd` (detached, resumable); log `data/logs/policy_register_docs.log` | ~294 of 3,014 sections done, 2,720 left (~7 h) | quote_ok >= 98%; then run `--source pib` as PIB backfill fills |
| DB backup to Drive | Task `RealityEngine-DBBackup` daily 05:00, uploads only 05:00-13:00; `data/logs/db_backup.log`; state `data/backups/state.json` | first full set today | Drive `InfoDiffusion_archive/db_backups/<date>/` parts + MD5 check passed |
| EOD market + disclosures | Task `RealityEngine-EODMarket` weekdays 19:35; `data/logs/eod_market.log` | first run today 19:35 | prices / deals / FII-DII / announcements / PIB dated today; security_master rebuilt |

**2026-10-19 03:20-04:00 (Claude):**
- Q1 `scripts/query_speed_check.py` built: 15 queries + state(isin,t) pending; nightly step in run_eod_market; log
  `data/logs/query_speed.jsonl`, summary `query_speed_report.md` appended to the watchdog report (watchdog restarted).
  All 15 under limit first + warm (boot age 52 h: a cold-after-reboot run is still to be seen in the nightly log).
- Q3 `scripts/build_query_indexes.py` (idempotent): deck pages/deck_sources(isin, known_at) + facts_metric_fts (13.6M rows),
  cc_items_fts, policy_events_fts + instrument/stage indexes, filings(period_end), covering indexes for results facts
  and NSE/BSE prices. FTS kept in sync by triggers (all writers use DELETE + INSERT). Before -> after (first run):
  deck company KPIs 10.6 -> 0.40 s, deck metric search 12.7 -> 0.88 s, NSE price history 0.29 -> 0.007 s, results one
  quarter 2.4 -> 0.21 s; vector top-20 1.0 -> 0.08 s (vector_store.search_by_vector no longer copies the whole
  matrix when unfiltered; same ranking verified).
- **Data gap fixed:** results_xbrl `filings.isin` is the ISIN written in the XBRL; ~15% of filings (11.7k of 76.4k) carry
  a pre-split / malformed ISIN (BEL, HAL, CANBK, DIXON, HINDZINC ...). New table `filings_isin` (results_xbrl.db) via
  `scripts/resolve_results_isin.py`: trading ISIN at dissemination date from symbol_isin_history (NSE symbol, then BSE
  code, then the filed ISIN); 172+3 unresolved; 247 'other issuer' rows are typo ISINs (checked by name). Nightly step
  in run_eod_market. Readers must join results by `filings_isin.isin`, not `filings.isin`.
- concall_deepseek_check fails (labels, not numbers): period_unparsed 18 (checker does not parse 'Quarter ended June 30,
  2026', calendar-year 'Q2 CY'26', half-years 'H2 FY26'), period_vs_filing_date 4 (RAIN calendar-year FY read as
  Indian FY; IDFCFIRSTB / SHREDIGCEM non-results calls labelled Q4), not_a_call_transcript 1 (SSWL doc 82474, no
  participants). concall_facts_checks: value_in_quote 98.4% (31,757/32,287), period_in_quote 55%, direction backed 24%,
  analyst-quoted 412 of 87,868; computed_direction raised 90 / lowered 75 / maintained 115 / new 960.
- concall_query_test (50 pilot questions): captured by DeepSeek 88% (numbers 25/25, qualitative 19/25); top-5 hit FTS
  facts 50%, EmbeddingGemma facts 66%, raw chunks 66%; PIT leak 0; PEAD posts with a call already public at post time 387.

**2026-10-19 16:45 (Claude): two power cuts (05:58, ~15:25: UPS trips under full GPU load) -> crash recovery.**
- After a reboot NOTHING has to be restarted by hand: task `RealityEngine-BootRecover` (at logon; pythonw, no wscript)
  runs `scripts/boot_recover.py`: readers at once (watchdog, PDF upload, Gemma re-embed at --duty 0.6), then on an
  unclean shutdown (event 6008) SQLite quick_check of all 6 DBs (once per boot; main DB ~38 min), then writers (PIB
  backfill, policy register, shareholding, circuit hits/bands, NSE industry, PIB regional sample, backup staging)
  only if every check passes. Jobs already running or finished are skipped. Status: data/logs/boot_recover_status.json
  (shown in the watchdog report), log boot_recover.log.
- DONE 18:00 (Shivam ran setup_boot_tasks_admin.ps1): BootRecover (at startup + at logon), EODMarket and DBBackup
  run as S4U, i.e. with nobody logged in. Tested: the re-embed restarted by the task in session 0 gets the GPU
  (DirectML, ~2.8 chunks/s at duty 0.6).
- EOD and DBBackup tasks now start via `conhost --headless cmd /c` (no wscript; Bitdefender flagged the wscript/VBS
  startup launcher as malware), may start on UPS battery, and catch up when missed. The Startup-folder VBS is renamed
  .disabled. DB backup: fixed the 05:09 crash (launcher redirected into the script's own log), lock file, resume
  packs DBs missing from an interrupted set, --pack-only staging: first full set staged 16:55 (6 DBs, 23 parts, ~22 GB), uploads from 05:00.
- All 6 DBs passed quick_check after the cuts. Gemma re-embed: 60% duty, ~3/s; transcripts+macro+decks ~28 h.
- PDF/deck upload to Drive by rclone (`scripts/run_pdf_upload.cmd`, resumable, 4 MB/s, 512 KB/s 05:00-13:00):
  53,562 files / 284 GiB missing at 15:15 (`scripts/drive_upload_check.py`, read-only remote gdrive_ro).

**2026-10-19 05:50 (Claude): events table, circuit hits / bands.**
- Snapshot table `events` (snapshot_research_tables.EVENTS_SQL): 2.78M company events (BSE announcements 1.95M,
  insider, deals, board-meeting intimations, results, shareholding, SAST, ARs, decks, circuit hits, concalls, PEAD
  posts, order alerts), 97.5% with ISIN (symbol / BSE code -> ISIN valid on the event's IST date), known_at_utc,
  source_ref back to the source row. Step 5 of the order of work (events + state) now has both parts.
- **PIT finding:** results XBRL known_at (NSE integrated-filing dissemination) can be up to a day AFTER the results
  PDF: TITAGARH Q3 FY25 results PDF on BSE 13-Feb-2025 20:32 IST, XBRL 14-Feb 15:10 IST. Safe (never early) but late;
  event studies on results timing must use the earliest 'Financial Results' announcement in events, values from XBRL.
- `scripts/fetch_nse_pr.py` (+ run_nse_pr.cmd, detached backfill 2019 ->): circuit_hits from NSE PR bundle 'bh'
  (2019 ->), price_bands + GSM/ASM stage remarks from sec_list_DDMMYYYY.csv (2021 ->; 2019-20 not archived). MONQ50:
  upper circuit 16/17/18-Sep-2026, lower 21/22-Sep. Nightly step added (covers B1 'circuit days').

**2026-10-19 05:40 (Claude): Phase C board calendar done; industry map + re-embed running.**
- `scripts/fetch_board_meetings.py` -> board_meetings: 120,451 NSE board meetings (equities + SME) 2019-01 -> 2026-11-14
  (furthest announced), purpose, intimated_at (IST, when the market learned the date; mean 12 days before the
  meeting, never after); revisions kept as rows. Nightly -10..+90 days.
- `scripts/fetch_nse_industry.py` (+ run_nse_industry.cmd, detached): NSE 4-level classification (macro, sector,
  industry, basic industry, index list) from the new quote API (getSymbolData); master_companies.industry is unusable
  (1,868 'General Diversified', 1,751 'Other', 2,714 blank); BSE's header API refuses scripts (403). Current labels,
  not point in time. Feeds A3 sector -> company mapping (3,478 distinct sector strings in policy_events).
- Re-embed (Gemma) running at 5.1 chunks/s after token-budget batching (was 3.8/s at batch 4; batch 12 calls hit 2.2 s,
  near the GPU reset limit): tiers 0-2 (transcripts, macro, decks, 327k) ~18 h, all 2.26M ~5 days.
- Shareholding: NSE SHP XBRL history starts mid-2021 (2019-20 < 210 filings): 2019-20 warm-up years are a gap (BSE).
- Snapshot now also carries board_meetings, index_tri, tax_rules, etf_px, fund_nav, company_industry, shp_index.

**2026-10-19 05:20 (Claude): B1 done, B3 running, results 2025-26 verified.**
- Integrated results job finished: 30,181 INTEGRATED filings ok (Mar-2025 -> Sep-2026 quarters), 106,613 filings in
  all; filings_isin rebuilt. Cross-check vs concall statements: POONAWALLA Q2 FY27 PAT 374.9 cr (call: "375 crore"),
  BEL Q1 FY27 revenue 5,533.1 cr (call: "INR5,533 crores"). Snapshot rebuilt (9.0 GB now: 7 kept = ~63 GB of 120 GB
  free on C: - Shivam to decide keep count); DuckDB capped at 4 GB after the build took ~11 GB (watchdog low_ram 05:05).
- B1 `scripts/fetch_etf_nav.py`: etf_px (432 ETF ISINs, 2019 ->, from NSE bhavcopy-with-ISIN files + old table),
  fund_nav (AMFI monthly NAV history, raw gz in raw_market/amfi_nav; 366 ETFs matched), view etf_premium, etf_inav for
  5 international ETFs (Nasdaq-100, Nasdaq Q-50, FANG+, S&P 500, Hang Seng). Measured: AMFI NAV of date t uses the
  underlying close of the same date t, so iNAV at the Indian close = k_{t-1} x previous index close x FX_t.
  Check: MONQ50 +235.45% premium to NAV on 18-Sep-2026 (Fri; 21-Sep +163.7%), then -49% in 3 sessions; NIFTYBEES /
  GOLDBEES within +-0.4%. Nightly step added. Not done: ETFs in security_master as instrument_type (kept in
  etf_master instead), circuit days, RBI/SEBI overseas-limit rows in policy_events.
- B3 `scripts/fetch_shareholding.py` (+ `run_shareholding.cmd`, detached, log shareholding.log): NSE SHP index
  (broadcast time IST), XBRL gz, shp_facts + view shareholding (promoter, pledged / encumbered as % of promoter
  holding, FII, DII, MF, insurance, retail, FPI limit used). The date-range listing is nearly empty before 2021, so
  history comes from a per-symbol listing (~4k symbols). Check pending: 10 companies x 2 quarters vs exchange site.

**2026-10-19 04:55 (Claude): B2 done; A2 sample running.**
- B2 `scripts/fetch_index_tri.py` -> `index_tri`: official TRI from niftyindices.com (new endpoint
  /BackPage/getTotalReturnIndexString, 1 year per call) for Nifty Smallcap 250, Midcap 150, 50, 500 since 2019; BSE
  publishes no TRI (bseindia archive = price only, asiaindex.co.in parked) so BSE 250 SmallCap / Sensex / BSE IPO TRI is
  derived from price + BSE's daily div_yield x 0.8 (scale calibrated on the 4 NSE indices vs official TRI 2020-25:
  mean error -0.02%/yr, worst 0.38%). Check: official TRI - price = 0.5-1.5%/yr = index yield. benchmark_for_month()
  picks: Jan-2024 Nifty Smallcap 250, Jan-2025 BSE IPO, Jan-2026 Sensex, Oct-2026 BSE IPO. Nightly step added.
- A2 `scripts/pib_regional.py` (new tables pib_ml_*): 29 PIB offices x their languages (62 combos, 22 languages;
  e.g. Mumbai Marathi/Konkani, Chennai Tamil). One day = ~527 releases, ~9 min with bodies -> 2021+ backfill ~13 days
  at full bodies; plan: titles for all, bodies for releases not matched as translations. Translation marking: (1) page
  links the English PRID ('release_link', exact), (2) EmbeddingGemma title(+body) similarity - threshold to tune on
  the 20-day sample (2026-09-26..10-14, running detached: `scripts/run_pib_regional.cmd`, log pib_regional.log).
  Note: Delhi English for recent days is not in pib_releases until tonight's EOD run (backfill is at 2021-07).

**2026-10-19 04:45 (Claude): A1 done.** `scripts/build_tax_rules.py` -> table `tax_rules` (20 rows) +
`tax_rule(rule, date)`. Sources are the enacted Gazette texts in `data/tax_sources/` (Finance Act 2018, Finance (No. 2)
Act 2024, Income-tax Act 2025, Finance Act 2026, NSE STT circular 2023); every quote is verified against the PDF text.
STCG 15% -> 20% and LTCG 10% -> 12.5% for transfers on/after 23-Jul-2024; LTCG exemption Rs 1 lakh (FY18-19..23-24)
-> Rs 1.25 lakh for all of FY 2024-25 (one limit over both rate periods); ITA 2025 s.196/198 keep 20% / 12.5% /
Rs 1.25 lakh from 1-Apr-2026; STT delivery 0.1% buy + sell throughout (2024 and 2026 changes are F&O only).
Gaps: pre-2026 holding period (s.2(42A) 1961) has no stored source; cess / surcharge cap rows only for FY 2024-25 and
2026-27 (other years' Finance Acts not stored).

**2026-10-19 04:35 (Claude): Q4 v1.** `reality_engine/query/state.py`: state(isin, t) over the newest snapshot (naive t
= IST); sections identity, prices (bar known 18:00 IST), results (trading ISIN), guidance (+checks), orders, deck_kpis,
ar_facts, announcements, insider, sast, deals, pead, policy (company-name match only). `scripts/state_check.py`:
300 random (isin, t): 0 leaks, p50 0.08 s, p95 0.16 s. Hand-checked TITAGARH (Q3 FY25 visible from 15:12 IST
14-Feb-2025, revenue 902 cr) and HAL across the 2023 split. Hand checks: `scripts/state_handcheck.py`, 20 companies x 4 times, 53 field checks vs raw XBRL / bhavcopy / BSE
feed, 0 mismatches (05:45). Pending: search() (after the Gemma index), policy sector mapping (A3).

**2026-10-19 04:00-04:35 (Claude): Q2 done.** `build_truth_snapshot.py` now also writes 32 research tables
(`snapshot_research_tables.py`): security master, results (filings + trading_isin, long facts with period_kind,
results_key quarter pivot), AR, decks, concalls, Telegram, BSE announcements, insider / SAST / PIT XBRL / deals / short,
FII-DII, NSDL FPI, policy_events, PIB. Every table: known_at_src + known_at_utc + known_at_precision (IST sources
-5:30; Telegram already UTC; date-only = end of day IST; NSDL = next day end). pit_report: all counts within the
source before/after copy, 0 unparsed times. Built to `.building`, renamed when complete, last 7 kept, snapshot_meta
records the date. Nightly step in run_eod_market (~20 min, ~5.4 GB each -> ~40 GB for 7). Market-wide scans: AR item
search via fts_main_ar_facts terms 0.27 s (ILIKE was 3.1 s), AR category 0.05 s, deck metric 0.17 s.
Notes: truth_2026-10-19 was patched after its build (bse_ann text columns, AR item index), so its pit_report holds only
the bse_ann row; snapshot_meta has the full report; tomorrow's build is complete.
- **Results XBRL parser bug (data):** facts.period_start/end are blank before 2022 and for FourD (year to date) carry
  the quarter's dates. Snapshot uses the context (OneD quarter, FourD YTD) via results_facts.period_kind; the SQLite
  parser itself is not fixed yet.
- **Data gap:** mkt_nse_insider ends 2026-05-02; later insider trades are only in nse_pit_filings + PIT XBRL facts
  (not yet parsed into trade rows).
- FY2026 transcripts not read by DeepSeek (1,307) + DeepSeek-read ones not in the search layer (583): chunk + bge-small
  run started 04:10 (`run_annual_report_ingest.py --doc-type CONCALL_TRANSCRIPT --local-only`, log
  `data/logs/concall_2026_chunk.log`).
- **EmbeddingGemma re-embed approved (Shivam 04:15):** `scripts/reembed_gemma.py` -> new index `data/vector_index_gemma/`
  (same layout as data/vector_index; live bge index untouched). Plan 2,214,107 chunks; tiers transcripts 249,571 ->
  macro 27,781 -> decks 7,637 -> AR 1,367,706 -> offer docs 557,421 -> other 3,991. Starts after the 2026 chunk job
  (one GPU embedder at a time). Then `--plan-new`, retrieval check vs bge on the 51 questions, then switch readers.

**Built this session (2026-10-18/19):** DeepSeek runner + validator + fact checks (cc_item_checks: verified vs
inferred, speaker, computed guidance direction) + query test; Telegram PEAD signals, Big Orders mentions (OCR) and
`tg_orders` + `tg_order_schedule`; search-layer date repair (10k docs; hygiene probe `search_docs_date_mismatch`);
vector store fixes (append matrix grows in place); EmbeddingGemma test win (80% vs bge-small 51% hit@5, re-embed
pending); security_master (8,434 equity ISINs incl. delisted/SME) + symbol_isin_history; market-wide BSE announcements
daily (order wins included); PIB feed; policy register; DB backup; EOD job extended; indexes: results 32 s -> 0.018 s,
NSE symbol, AR FTS 49 s -> 0.39 s. Zen free models blocked for this IP (OpenCode: 'abusive traffic'); our Zen route is
off and `new_reader_check.ZEN_BLOCKED = True`. Google Gemma free has a 16k input-tokens/min cap per key: fine for our
API pipeline, unusable from the OpenCode app (its prompt alone exceeds it).

## ORDER OF WORK (Shivam, 2026-10-19 00:40) - the data-stitching plan
Phase-wise queue of new items (policy pillar, ETFs, TRI, shareholding): **`tasks/PIPELINE_TODO.md`**.
Goal: one point-in-time knowledge ledger that quantifies companies and feeds the shared backtest harness.
1. **Quarterly results Mar 2025 -> now** (results_xbrl.db stops at the Dec-2024 quarter: SEBI moved results to
   'Integrated Filing (Financials)') + BSE-only companies; restart the EOD price job (prices end 2026-10-09). <- IN PROGRESS
2. PIT audit of every store (known_at = exchange/publication time, never crawl date; hygiene probe exists for the search
   layer only) + ISIN history map + add NSE SME companies to master_companies (orders/PEAD name SME cos we lack).
3. Metric ontology (~200-300 canonical metrics) + canonical long fact ledger, XBRL-anchored: map XBRL concepts directly;
   deck (1.48M distinct metric strings), AR items and concall metrics by embedding + one LLM pass over DISTINCT strings.
4. Cross-source reconciliation (XBRL vs deck vs AR vs concall) -> per-fact quality score.
5. Events table (results, calls, decks, ARs, orders, PEAD posts, insider/SAST, deals) + as-of API state(isin, t).
6. First hypothesis cards through the harness: order surprise (from dissemination time), computed guidance raise x
   management credibility, PEAD + call confirm/veto, results vs own prior guidance.
7. Valuation drivers v1: order-book schedule (tg_order_schedule), capacity x utilisation, capex->capacity lag,
   management credibility (guidance vs later XBRL actuals), peer-relative forward multiples.
Added 2026-10-19 (Shivam), ahead of TRI + shareholding:
- **PIB / policy pillar**: phase 1 English Delhi feed + backfill 2021-> RUNNING (`pib_feed.py`, `run_pib_backfill.cmd`,
  table pib_releases with minute posting time; daily step in run_eod_market). Phase 2: Hindi/Urdu + regional PIB
  offices, drop translations of English releases by EmbeddingGemma (multilingual) similarity, translate the unique
  ones. Then the **policy register**: LLM extraction over PIB + Budget + RBI + PRS into dated policy rows (what
  changed, stage hinted/consultation/draft/announced/notified/effective, sectors/companies, old->new values,
  announced_at PIT, effective date). Tax-rule table for the harness (STCG/LTCG by effective date from Budget speeches).
- **ETFs**: add INF ETFs to security master as a separate type; AMFI daily NAV history 2019->; etf_premium table
  (premium/discount to NAV; for international ETFs an indicative NAV from the underlying index x USDINR, since the
  official NAV is a day stale). Long-only uses: buy deep discounts, switch between near-identical ETFs, exit before a
  premium unwinds (MONQ50 Sep 2026: +235% premium under RBI overseas cap, then -49% in 3 sessions).
- Done tonight: daily DB backup to Drive 05:00-13:00 (`backup_dbs_to_drive.py`); security_master (8,434 equity
  ISINs incl. delisted/SME) + symbol_isin_history; EOD job extended to deals/short/insider/SAST/corp actions/FPI/
  FII-DII/market-wide BSE announcements (incl. order wins)/new docs/PIB; loader reloads rewritten files.
Data behaviour notes: numbers + verbatim quotes are data (97-98% inside own quote); LLM labels are interpretation
(direction backed 25%, period 55%) -> use cc_item_checks flags and computed_direction. Concall facts exist for 2026
only; 2021-25 transcripts are text chunks (EmbeddingGemma beat bge-small 80% vs 51% hit@5; re-embed pending).

## 2026-10-19 00:40 running / done tonight
- DeepSeek 2026 concalls (Telegram-covered companies only: PEAD 602 + Big Orders 154 = 730 ISINs,
  `data/tg_company_isins.json`): `scripts/run_concall_deepseek.cmd` (detached, 25 workers, key 2, waits out Go limits and
  peak hours). 850 read, 243 left, resumes ~03:00 when Go's 5 h window frees. Validate after: concall_deepseek_check,
  concall_facts_checks (re-run: flags + computed direction), concall_query_test.
- New tables: concall_facts.db (cc_docs, cc_items, cc_item_checks); tg_company_mentions, tg_orders, tg_order_schedule.
- Zen free models blocked for this IP ('abusive traffic'); ar-zen route idle - stop it (Shivam OK pending).
- Heartbeat cron stopped (Shivam).

## 2026-10-18 15:40 transcripts, PEAD, Drive, disk (Claude, main checkout)

- **Transcript plan (Shivam):** 2026 transcripts -> DeepSeek extraction (PEAD companies first; wait for
  DeepSeek-V4.1-Flash-1017 on Go / key 1 reset Oct 21, then re-pilot ~$0.40). Pre-2026 -> chunks + bge-small embeddings.
- **Running:** `run_annual_report_ingest.py --doc-type CONCALL_TRANSCRIPT --local-only --before 2026-01-01` (new mode:
  chunk + embed already-downloaded, never-processed files), 8,484 transcripts, ~14/min, ~10 h, log
  `data/logs/concall_cpu_chunk.log`. Embeds on GPU (DirectML) - Shivam OK. Stores: equity_intelligence.db
  (raw_documents, document_chunks.embedding JSON, FTS5) + data/lancedb.
- **Embedding test DONE (20:30-21:40):** 51 paraphrased analyst questions over 8,452 transcript chunks of 60 companies
  (`scripts/embed_model_test.py`, `data/embed_test/`). hit@1 / hit@5 / hit@10, chunks/s on DirectML:
  bge-small (current) 29/51/63%, 27/s; bge-base 16/39/47%; **EmbeddingGemma-300M 45/80/86%, ~7/s**; Qwen3-0.6B
  31/67/84%, 3.6/s. Big models need DML batch 4 (batch 16 tripped a Windows GPU reset). Production chunks average ~550
  tokens, over bge's 512 limit (truncated). Decision pending (Shivam): re-embed with EmbeddingGemma - 2.2M chunks total
  (AR 1.37M, offer docs 0.56M, transcripts 0.25M, macro/decks ~25k) ~87 h at 7/s; transcripts+macro+decks ~11 h.
- **Dates repaired (2026-10-18):** search-layer docs were stamped with corporate_documents.doc_date (crawl date):
  5,725 transcripts (my --local-only run) + 3,496 ARs + ~936 decks (older runs). All fixed from BSE dissemination /
  publication / call date (`scripts/repair_transcript_dates.py --types ...`); hygiene probe `search_docs_date_mismatch`
  now 0 / 19,024. Vectors still embed the old header date text: re-embed covers it.
- **Was next (Shivam):** embedding model test - ~50 real concall questions, bge-small vs Qwen3-Embedding-0.6B
  vs EmbeddingGemma-300M (retrieval hit rate + GPU speed, DirectML/ONNX support). Switch only on a clear gain, then
  re-embed everything in one pass (text/chunks are reused).
- **PEAD (Telegram topic 683):** session re-logged in; topic refreshed to 2026-10-17 (no posts Aug 27 - Oct 8).
  `scripts/tg_pead_signals.py` builds table `tg_pead_signals` (post id/time UTC, symbol from Chart button, ISIN, label,
  filing URL) and `data/concall_priority_pead.json`: since 2026-06-18, 513 companies, 356 hold concalls.
  Transcript counts: PEAD cos 2026: 895; 2022+: 4,871; all 2026: 3,597. DeepSeek v4.1 est. $0.0156/transcript off-peak.
  BSE feed refreshed for 2026 for these companies; Q2 FY27 transcripts: 8 so far (4 got 404 on AttachHis - retry via
  AttachLive).
- **Drive:** rclone stopped (it saturated the uplink, RDP lag ~5 s). Shivam set up his own rclone client_id (drive.file:
  it cannot see files the old shared client uploaded). Shivam uploads `C:\Users\warri\Downloads\InfoDiffusion_to_upload`
  by hand (hard links: pdfs 37,436 files 140 GiB not yet uploaded + decks 25,660 files 111 GiB). 4,134 pdfs were
  uploaded by rclone to `InfoDiffusion_archive/pdfs`. **`D:\RealityEngine\pdfs` (19,609 files, 110 GiB, referenced by
  corporate_documents) is in neither copy** - Shivam to upload it too.
- **Disk:** Reality Engine ~491 GB (C: ~381: pdfs 157, decks 112, DBs 65, other ~27; D: 110). Cleanup proposal for C:
  after upload verified (Drive count 63,096 / ~251 GB): decks 112 (extraction complete: 815,837 pages ok/skipped,
  second_queue 0), ARs 114, pre-2024 offer docs etc ~15, old DB backups ~6 -> ~245 GB. Keep transcripts. Nothing deleted
  yet; awaiting Shivam.

## 2026-10-18 05:40 concall pilot round 3 (Go key 2, paid models) - done, decision pending (Shivam)

- Ran mimo-v2.6-flash, deepseek-v4.1-flash, muse-spark-1.3-contributor (Responses API) on the 25 transcripts with
  prompt v2 + machine_check (`out/<m>-machine/`), all on Go key 2 (Shivam's go-ahead; key 2 was 0% used; extra usage off).
  Pilot cost about $0.6 in total.
- Blind Opus judge3 (5 transcripts, 6 readers; `judge3/`, key `judge3_key.json`), /30 and errors on 5 calls:
  **DeepSeek 25.2 (11)**, MiMo 23.2 (25), Opus 23.0 (20), LongCat v2 21.6 (32), Muse 20.4 (13, accurate but thin),
  Sonnet 20.2 (16). Auto recall vs union: DeepSeek 78%, MiMo 71%, Opus 68%, LongCat v2 66%, Muse 49%.
- Measured tokens/transcript (in / out incl. reasoning): DeepSeek 10.6k / 23.3k, MiMo 10.8k / 13.1k, Muse 10.4k / 11.6k.
  Full backfill (21,695): DeepSeek ~$338 (limit $80/month: ~4.2 months), MiMo ~$109 (~1.8 months of $60), Muse ~$73
  (~1.2 months of $60). Weekly window = 50% of monthly, 5-hour window = 20%. Off-peak DeepSeek prices assumed.
- Open errors common to all readers: 'maintained' guidance with no earlier figure, unit added to bare numbers,
  analyst words quoted as management's, unflagged in-call inconsistencies (dates/figures said two ways).
- Options for Shivam: (a) DeepSeek with reasoning cut (test whether a lower reasoning effort keeps quality and halves
  output tokens), (b) DeepSeek on both Go keys from Oct 21 + MiMo, (c) Go Plus, (d) LongCat v2 free for bulk + DeepSeek
  for the most-traded names. Round-3 prompt checks (speaker attribution, label keywords) still not built.

## 2026-10-18 04:15 hand-off (session ends; next session starts here)

**Running (detached, survive this session):** Drive archive (`scripts/run_archive_to_drive.cmd`, rclone; 9.6 GiB of
pdfs/ at ~1.2 MiB/s, then decks/, then MD5 checks; logs `data/logs/archive_*.log`; local copies stay until Shivam
confirms). Resource watchdog. Zen AR route (idle: OpenCode refuses all free Zen calls since 10-17 06:00).
**Not running any more:** the Claude heartbeat cron (session-only) - recreate it in the new session (every ~40 min:
watchdog report, AR/route logs, drive.log, archive progress). AR reading is finished.

**Next task (Shivam):** concall pilot round on OpenCode Go key 2 (`OPENCODE_GO_API_KEY_2`): `mimo-v2.6-flash`,
`deepseek-v4.1-flash`, `muse-spark-1.3-contributor` on the same 25 transcripts; count tokens per model to see whether
the Go budget covers a full backfill (21,695 transcripts, ~11k input tokens each). Notes:
- Runner: `python -m reality_engine.scripts.concall_pilot run --models <m> --workers N` (outputs
  `data/concall_pilot/out/<model>/<doc_id>.json` + `.meta.json` with tokens); score with `... score`. Go readers use
  chat/completions in `call_go`; it picks key 1/2 by index - force key 2 for this test. **Muse needs the Responses API**
  (`/zen/go/v1/responses`, see `ingest_annual_reports.call` protocol 'responses'); call_go must get that branch.
- Use prompt v2 (`data/concall_pilot/prompt_v2.md`, alias pattern `ALIASES` in concall_pilot.py) + `machine_check`.
- Judge: blind Opus subagent on the same 5 transcripts (118440, 55951, 80352, 36223, 25608) as judge2 (scores
  `data/concall_pilot/judge2/`, key `judge2_key.json`); include Opus/Sonnet/LongCat-v2 for comparison.
- Go key 1 monthly allowance ~99-100% used until Oct 21 (MiMo/Muse are paid models on the Go plan); check key 2's
  console usage before and after.
- Results so far (blind Opus judge, /30, errors on 5 calls): round 1 Opus 27.2 (3), Sonnet 26.0 (3), LongCat 24.8
  (13), Gemini 3.8 Flash 22.0 (9), Gemma 26B 17.0, Flash-Lite 17.0. Round 2: Opus 25.4 (4), LongCat v2 + machine checks
  24.4 (10), Sonnet 23.8 (2), LongCat v1 21.4 (15). Remaining LongCat errors: analyst words as management's, inferred
  facts (dividend 'declared' vs 'considered'), unsupported 'firm' labels. Proposed round 3: speaker-attribution check
  (quote must sit in a management turn) + label-keyword check. The LLM verifier dropped correct items: keep it off.
- Concalls: 21,695 transcripts filed, only 5,260 in the search layer; 4,917 re-dated to BSE dissemination time, 318
  have no true date (exclude from tests). Fact extraction for concalls not started.

**Done this session (10-17/18):** AR reading complete (33,278 done; 60 true scans OCR'd by run o03; 4 unreadable;
CIANAGRO/NBFOOT/MEAPL FY22 still missing). 67 broken/scanned ARs replaced from NSE archive / BSE announcement copies;
OCR facts on text-recovered reports removed and 788 text-read facts restored. Macro set ingested: 480 docs 2019-2026
(Union budgets, Economic Surveys, RBI policy/MPC/AR/FSR summaries, PRS state budgets), real publication dates.

## 2026-10-17 23:40 archive to Google Drive (running)

- rclone 1.75.1 (winget) remote `gdrive` (scope drive.file; Drive has 4.9 TiB free). `scripts/run_archive_to_drive.cmd`
  copies `data/pdfs` (157 GB) then `data/decks` (111 GB) to `gdrive:InfoDiffusion_archive/`, then `rclone check
  --one-way` (MD5) per folder; logs `data/logs/archive_*.log`, misses in `archive_<folder>_missing.txt` / `_differ.txt`.
  **Local copies are NOT to be deleted until Shivam confirms.** Plan after a clean check: delete local FY2019-2023, keep
  FY2024+. rclone's shared client_id is being retired during 2026: create our own Google client_id (rclone.org/drive).
- **Concall transcripts: all 5,228 have published_date in 2026** (fetch date, not call date): fix before any test.

## 2026-10-17 02:30-03:00 (Claude, main checkout)

- **Beam prompt decided: keep plain.** Go exhaustive+core (t-go-beam-exc-1017): 14,001 facts vs plain 11,304, but
  must-find 20/25 (plain 23/25) and 15 regrouped numbers (plain 5). More facts, worse quality.
- **Gemma 26B fix** (`ingest_annual_reports.py`): pieces whose real token count alone tops the 16k tokens/min per key
  (est_tokens undercounts number-dense pages) bounced between all 37 keys for ever (uncounted 429, key rested 65 s):
  26B fell ~250 -> ~50 pages/min from 19:00 on 10-16. Now after 2 such refusals the piece is given up and the report's
  claim is released to the main run. Route back to ~64 pages/min within 10 min of the 02:41 restart.
- **Root cause of the evening drop (~900 -> ~500 pages/min):** from ~19:00 on 10-16 Google refuses a single Gemma request
  over 16k input tokens (before, 35-47k token requests passed) on BOTH 26B and 31B. Fixes: 26B route pre-check now
  est x1.10 + oversize hand-off (above); main-run Gemma 31B hands a refused-alone piece straight back for LongCat/Beam
  (`too_big`, no 65 s sleep, never retaken by Gemma). 5xx key rests now logged. 03:12-03:25: LongCat ~400, 26B ~206,
  31B ~54 pages/min (31B/26B also get night-time HTTP 500s from Google).
- **Beam upstream rate limit from ~03:00:** both Go keys 429 'Upstream request failed' (LongCat fine on the same keys);
  likely a daily upstream budget like Cat Jam's (reset 05:30 IST?). The 3-min Go bench handles it.
- **Zen free tier refused from ~06:00 10-17** ('OpenCode's free tier can only be used from within OpenCode', even for a
  plain `opencode run` from Temp; CLI updated 2.0.31 -> 2.0.32 with bun, still refused). Server-side gate (see GitHub
  anomalyco/opencode #51315, #49590). Zen route now benches on this message (no burnt pieces); 93 Zen-claimed partial
  reports released to the main run. muse-spark-1.3-contributor-free retired (deprecated). deepseek-v4.1-flash passed
  on rerun of its 6 rate-limited pieces (25/25, 8,529 facts, 0.0%); Beam on Zen passed (25/25, 14,110 facts).
- Killed an orphaned `grep -rl nimbusprojectsltd .` (parent gone, 24 min, 72 MB/s) at 05:44.
- **RAM leak 04:30-08:10 found:** 4 orphaned Git-bash `find / -name *<hash>*` (started 05:08-05:26) + a `grep -rl
  nimbusprojectsltd .` (killed 05:44) whose shells had died (some agent's command timeout) held ~11.6 M handles: kernel
  paged pool 7.5 GB, RAM free 6 -> 0.8 GB. Killed at 08:15 -> paged pool 0.9 GB, 7.4 GB available. Watchdog now kills
  orphaned find/grep/rg/xargs older than 10 min and reports any process over 200k handles (handle_hog). Agents: never
  run `find /` (whole disk) on this machine. Beam's Go upstream limit hit again 07:xx after ~2,000 pieces per key.
- **21 unreadable AR PDFs (2026-10-17):** BSE itself serves them broken (15 zero-filled, 6 bad page tree; re-download
  byte-identical). 7 replaced with NSE archive copies (ADVANIHOTR, AMRUTANJAN, CCHHL, INDBANK, INDOTHAI, MONTECARLO,
  SURYALAXMI FY22; every page checked, sha updated in corporate_documents); they get read at the next route restart.
  14 are BSE-only (BIMETAL x2, GENSOL, SKYGOLD, VOLKAI, IGLFXPL-B, WINSOMBR, SICAPIT, SEATV, SDC FY26, SCL, MEAPL, HUIL,
  SKIEL): need the company website copy. NSE API: /api/annual-reports?index=equities&symbol=X (zip per year).
- **'no_text' (109) + 'unreadable' reports recovered 2026-10-17 evening:** most 'scanned' files were broken BSE copies
  (0 pages / zero-filled, mostly FY2021-22). Replaced: 23 from NSE archive (`/api/annual-reports`, zip or plain PDF),
  44 from the BSE *announcement* copy (Reg 34 filing, AnnSubCategoryGetData -> xml-data/corpfiling/AttachHis/<att>;
  kept only if >= 40 pages and >= 300 chars/page). Old files backed up in the session scratchpad. 70 true scans go to
  OCR (`ar_ocr_reread --run o03-scans`, decide() now takes OCR when old pages had 0 numbers). Still missing:
  CIANAGRO, NBFOOT, MEAPL FY22 (company website). NAVA's NSE copy was a 1-page notice: reverted.
- **Muse Spark 1.3 (paid, Go key 1)** added to the main run 14:15 (Responses API; profile protocol 'responses'):
  ~113 pages/min, 6.4 facts/page, ~$0.33 per 1,000 pages; monthly allowance 93% -> 97% by 15:21 ($2.21).
- **All routes + watchdog died 23:43-02:27** with exit 0xC000026B (session logoff): an RDP sign-out kills them; disconnect instead.
- Claude heartbeat every ~40 min (session cron) checks watchdog, routes and tests.

## OVERNIGHT 2026-10-16 05:15-06:25 (Claude, main checkout; Shivam asleep)

- **AR workers restarted 05:25** on the page-based resume code (all 5 routes). At restart: 19,342 done, 14,307 to read
  (includes the 2,053 partial). Gemma 31B pages/min fell ~165 -> ~60 because gap-fill pieces are ~3 pages, not ~6;
  requests/min unchanged. Recovers once the partials are cleared.
- **OpenCode CLI 2.0.27 -> 2.0.30** (bun). New Zen free models need Shivam to allow them on the account first.
  - Testing (auto-scored by the 2-hourly new_reader_check, added to `zen_models.json` and the Zen worker on a pass):
    `nemotron-3.5-super-vl-free` (run t-nemotron35superv-1016), `deepseek-v4.1-flash-free` (t-deepseekv41flash-1016).
  - Still not routed: jev-1.13-free, muse-spark-1.2-contributor-free (deprecated). Neither new model is free on Go.
  - `new_reader_check.py` now lists 'zen listed but not routed' models.
- **Haiku hard reports:** h02-scanned finished and imported (24 reports); h03-misses (14 reports, top misses per page)
  read and imported. 5-hour window 49% -> ~86%. Haiku facts in use: 14,784 (12,091 verified).
  - `ar_queue.py import-docs`: (1) fixed rule: pages with NO old numbers now take Haiku's facts (before, 16 reports'
    answers were stored as rejected because 'not_found < 0%' never holds); h02 re-imported with --redo.
    (2) new `--skip-docs`.
  - **CORRECTION (16:00):** the 4 "wrong-company PDFs" below are NOT wrong: they are renames (scan session
    local_f36db5fe, commit e21746ff on claude/quirky-murdock-6a0654: SIGMAADV=Megasoft, VEGA=PH Trading,
    SKYBIOTECH=Kapil Cotex, UCIL=Shree Worstex; BSE scrip codes in the PDFs). Flags cleared, Haiku answers imported
    (SIGMAADV, VEGA, UCIL replaced; SKYBIOTECH kept old). Only confirmed wrong PDF: VENUSREM 92565 (Home First's AGM
    notice). Agents must not be told to NONE "other company" pages; renames are common.
  - ~~Wrong-company PDFs~~ (found by Haiku, confirmed by OCR; `ar_docs.error` set, facts NOT removed):
    SIGMAADV 79913 = Megasoft Ltd, VEGA 125476 = PH Trading Ltd, SKYBIOTECH 125486 = Kapil Cotex Ltd.
    To do: quarantine their facts and re-fetch the right PDFs; check other hard reports for the same problem
    (a company-name check of page text vs `ar_docs.company` would find them for free).
  - Old readers invented numbers on scanned pages (HINDMILL 532 numbers on one page, Haiku found none); they are
    tagged not_found. The import keeps them where Haiku has fewer verified numbers (BEL, AIAENG, ZDHJERK, HINDMILL).
  - Next Haiku batch: ranking query in this session (hard_diagnosis.csv minus h01-h03, by not_found per page);
    the next 26 reports cover ~185 pages. Agents need exact file names (they cannot list folders).
- **Afternoon 2026-10-16 (14:15-~15:30, fresh 5-hour window, 2% -> ~92%):** run `h04-misses` (26 reports, 581 pages:
  next by not_found per page) read by 58 Haiku agents and imported: 24 replaced, COFORGE kept old, UCIL skipped.
  Haiku facts in use now 27,779 (23,296 verified). Next batch: the ranking query again, minus h01-h04.
  - 4th wrong-company PDF: **UCIL 138000** pages 60-62 = Shree Worstex Ltd (`ar_docs.error` set). CCAVENUE = Infibeam
    Avenues and COFORGE = NIIT Technologies are former names, not mismatches.
  - **Zen tests had been scored FAIL at 08:10 while unfinished** (drivers died at 25/110 and 36/110 on Zen rate limits).
    Fixed `new_reader_check.py`: an unfinished test is resumed for up to 3 days, never scored. Both tests reset and
    resumed at 14:28; they finish after the 05:30 Zen reset and are scored by the 2-hourly check.
  - Also listed but not routed on Zen: glm-5.3-flash-free, ll-alpha-free (Shivam can allow them on the account).
- **2026-10-17 02:35 hand-off (this session ends; pending work goes to a fresh session):**
  - **Beam admitted** to the main AR run (Shivam, despite must-find 23/25): `beam-free` x32 on each Go key, plain prompt;
    reading at once (74 pieces first minute, 0 errors). Cat Jam removed from the main-run readers (gone from Zen and Go).
  - **Tests running** (detached drivers; the 2-hourly check scores and auto-adds passes):
    Zen `nemotron-3.5-super-vl-free` (t-nemotron35superv-1016, 25/110), `deepseek-v4.1-flash-free` (t-deepseekv41flash-1016,
    36/110), `beam-free` on Zen (t-beam-1017), `glm-5.3-flash-free` (t-glm53flash-1017); Go `beam-free` with the
    exhaustive+core prompt (t-go-beam-exc-1017; score with `ar_queue test-score --run t-go-beam-exc-1017` and compare to
    the plain run t-go-beam-1016: 11,304 facts; switch the profile prompt if it gives clearly more facts).
    Zen is rate-limited until the 05:30 IST reset, so Zen tests finish after that.
  - **Pending:**
    1. Go key 1 lists ~30 subscription (non -free) models (hy4-preview, omen-alpha, qwen3.8-*, kimi-k3, glm-5.3, ...):
       they use the paid Go allowance; ask Shivam before testing any.
    2. Zen still not routed: jev-1.13-free, ll-alpha-free (Shivam can allow them on the account).
    3. Haiku hard-report batches: next by the ranking query minus h01-h10; use `--mode image` for encoded/garbled reports.
    4. 222 placeholder ISINs left (rights/ETFs/bare scrip codes), 44.6k price rows.
    5. Tune Beam slots by pages/min (bisection), as done for LongCat.
- **2026-10-16 23:00-23:45 weekly-quota burn (Claude):** Haiku runs h05a, h05b, h06-h10 (~37 reports, ~600 pages) read
  and imported. Haiku facts in use now 37,508 (31,044 verified). Lesson: `export-docs --misses-only` sends font-garbled
  pages as TEXT (no image) when the page kind is 'clean'; Haiku then cannot read their figures (h05a PNC/QGO). Prefer
  `--mode image` for reports whose diagnosis cause is encoded/garbled.
- **Readers 2026-10-17 02:20:** Cat Jam left both Zen (retired 20:18) and Go; the main run still lists cat-jam readers
  (benched, harmless; drop them from reader_profiles.json at the next restart). New Go model **beam-free** failed only on
  must-find 23/25 (0.1% not found, 11.3k facts): candidate for admission if Shivam accepts 23/25. Zen tests for
  nemotron-3.5-super-vl / deepseek-v4.1-flash are still at 25/110 and 36/110 (drivers died again); the 2-hourly check
  resumes them. **Resource watchdog had died silently after 23:43** (no traceback); restarted 02:23 (pid 6292).
- **CLEANUP ROUND 2 2026-10-16 night (Claude):**
  - **All placeholder ISINs merged** (`scripts/merge_placeholder_isins.py --apply`, map `data/ar_queue/
    placeholder_isin_map.json`): 1,143 of 1,365 INE_AUTO ISINs resolved (602 master, 335 NSE prices, 206 BSE prices);
    388 real ISINs added to master, stubs set is_active=0. Re-keyed: ar_facts 536,259 (0 placeholder facts left),
    daily_price_delivery 257,009, filings 2,868, plus FTS/chunks/moat/profiles/metrics/risks. Financials merged; rows the
    real ISIN already had were archived to `<table>_placeholder_archive` (93 quarterly, 82 annual, 219 forensic, 847
    distilled). Left: 222 unmatched (mostly rights `-RE`, ETFs, bare scrip codes; 44.6k price rows). All in isin_rekey_log.
  - AR workers restarted 21:5x so new facts carry real ISINs; leftovers re-keyed (5,544).
  - **Debt-issuer reports dropped** (`scripts/drop_debt_issuer_reports.py`): 360 reports under BSE debt scrips (9xxxxx),
    none a rating report -> 444,286 facts moved to ar_facts.db `ar_facts_dropped`, ar_docs status 'dropped_debt',
    filings re-typed ANNUAL_REPORT_DEBT_ISSUER (+49 unread ones), so workers skip them.
  - substrate_hygiene degradation rule `ar_docs_identity_unconfirmed` over new table `ar_doc_scan` (scan verdicts):
    322 reports (1.3%) whose company their own text does not confirm; hand-checked ones drop out of the count.
  - Hand check of the 225 candidates (session local_e2914960, commit 7eb8d667): no new wrong PDFs.
- **CLEANUP DONE 2026-10-16 ~21:00-21:45 (Claude, this session):**
  1. ISINs: `scripts/rekey_placeholder_isins.py --apply` re-keyed INE_AUTO -> real ISIN for 393 symbols (one real ISIN
     each by nse_symbol): corporate_documents 9,233, ar_docs 1,996, **ar_facts 1,791,744**, ar_facts_replaced 3,069,
     deck pages 1,233. Logged in equity_intelligence `isin_rekey_log` (undo: set isin=old_isin per row). Left alone:
     128 symbols with no real ISIN in master (535k facts), and price/financials tables (need a merge, not a re-key).
     **Re-run the script after the AR workers next restart**: their current pass still writes the old ISIN.
  2. Quarantine: `substrate_hygiene` rule `ar_wrong_company_pdf` (keys stored under table 'ar_facts' = doc_ids) +
     table `ar_doc_identity` in equity_intelligence.db. VENUSREM 92565 = wrong_company (quarantined); LADIAMO
     131564/131568 = ok (FY2019 report: Laser Diamonds renamed Turner Industries 08.02.2018). Tests pass. No analysis
     code reads ar_facts yet; the first one must drop `quarantined_keys(conn, "ar_facts")`.
  3. `scripts/fetch_missed_ar_files.py`: BSE-listed later AR files we lacked: 9 rows were OTHER_FILING without a
     file -> now ANNUAL_REPORT with the file (incl. **VENUSREM 92559 = the real FY2026 report, 137 pages**), 1 new
     (MERCATOR FY2022), 11 same bytes as files we have, 2 gone from BSE (404). 22 scrip-years, not 104.
  4. DALBHARAT 23830: real report (249 pages) extracted from the PDF portfolio, path updated, its empty reading
     deleted so the workers read it. It was the only portfolio PDF among short reports.
- ~~CLEANUP queued~~ (done above) **for the next 5-hour window (after 19:10 IST 2026-10-16), from scan commit e21746ff:**
  1. Fix 1,826 ar_docs rows (373 symbols) with placeholder `INE_AUTO_*` ISIN where the master has the real ISIN.
  2. Quarantine VENUSREM 92565 (ar_doc_identity table + substrate_hygiene rule `ar_wrong_company_pdf`); fetch BSE's
     second FY2026 upload `29971821-bfab-4659-a9d8-7cf5dc170d02.pdf`.
  3. Fetch the later BSE files missed in 104 company-years; unwrap DALBHARAT 23830 (PDF with attachment).
  4. Resolve LADIAMO 131564/131568; merge or cherry-pick e21746ff (branch claude/quirky-murdock-6a0654).
- Not committed: `ar_queue.py`, `new_reader_check.py`.

## HARD ANNUAL REPORTS (Haiku session, 2026-10-16 ~03:00; brief `tasks/HARD_AR_HAIKU_SESSION.md`)

**Hard set:** 345 reports with > 10% of numbers not found in the text (43,953 of ~148k numbers).
- Cause, by the page kind holding most misses (`ar_queue diagnose`, CSV `reality_engine/data/ar_queue/hard_diagnosis.csv`):
  - garbled OCR layer / scans: 111 reports, 15.1k misses;
  - fonts that encode digits: 46 reports, 14.5k misses;
  - clean text: 188 reports, 14.0k misses. Mostly LongCat and Gemma 26B misreads; several (PPAP, ATUL, LUPIN) were
    really mixed-font pages, which the new rule fixes.
- SDC is still the only unreadable PDF (text split times out).

**Free fix (no quota):** `value_check` now decodes fonts that store 0-9 as ten consecutive code points anywhere in
Unicode (`shifted_digit_maps`). Examples: OIL FY2020 uses U+0144 = 0; PPAP FY2024 uses control characters, U+0010 = 0.
- The base is chosen by the years it decodes, so neighbouring blocks are not mistaken for it.
- Re-checked all 345 reports (`ar_queue recheck --write`): not_found 43,953 -> 35,736 (8,217 numbers now verified).
  Examples: PPAP 851 -> 81, OIL 2,560 -> 1,878, ATUL 601 -> 280.
- False-match test: random 4-digit numbers "found" 1-3% (old rule 0-1%); decimals 0%.

**Haiku re-read path (`ar_queue.py`):**
- Commands: `export-docs`, `missing`, `import-docs`.
- Clean pages go as 18k text pieces; garbled, encoded or no-text pages go as page images.
- Each image also gets a RapidOCR text file. The import checks Haiku's numbers against the text layer, then against
  that OCR text (`value_check='ocr'`).
- Facts are stored as model `claude-haiku-5-5`, prompt_version `ar-v1x-haiku`.
- A report's older facts on the re-read pages are replaced only if Haiku's not_found share is lower AND Haiku has at
  least 80% as many verified numbers. Replaced rows move to `ar_facts_replaced`. Losing Haiku answers are stored as
  model `claude-haiku-5-5:rejected`.
- **Run folders must live in a worktree.** The worktree guard stops helper agents writing into the main checkout, so
  runs are under `.claude/worktrees/wonderful-chatterjee-4788f5/reality_engine/data/ar_queue/` (`--run` takes an
  absolute path).
- **Do not remove that worktree until h02 is finished.** Also, `reality_engine/data/ar_queue/h01-sinclair` in the main
  checkout is an unused copy; it can be deleted.

**Incident (mine, repaired):** while editing `value_check` at 00:07 IST, `ingest_annual_reports.py` had a syntax error for ~2 min. Workers spawn `--pieces-json` children from that file, so 124 good reports were marked `unreadable` ('text split failed ... source_to_code'). At ~03:00 I deleted those rows and their 122 Gemma-26B route claims; they are read on the next run pass. Lesson: edit live scripts by writing a checked copy first (the later edits compile before writing).

**Haiku results so far:** 12 reports imported; 11 replaced, 1 kept old (KAIZENAGRO).
- Before: 711 numbers, 418 verified. After: 3,984 numbers, 3,732 verified.
- SINCLAIR FY2020 (validation): 58 numbers, 98% not found -> 561 numbers, 1% not found.
- Quota: 3 waves (~27 agents, ~4.5M Haiku tokens).
  - The 5-hour window went 26% -> 75%, shared with the deck Haiku session.
  - Weekly went 32% -> 42%.
  - About 0.5-0.8% of the 5-hour window per agent.

**Status at hand-over (2026-10-16 ~06:00, sessions being killed):**
- Run h02-scanned is now copied to the MAIN checkout: `reality_engine/data/ar_queue/h02-scanned` (397 of 638 answers). Use `--run reality_engine/data/ar_queue/h02-scanned` (or just `--run h02-scanned`). Helper agents cannot write there from a worktree session; run the next waves from a session opened on the main checkout.
- Answered: b000-b035, b038, b039. b036/b037 were interrupted (may be partial; `ar_queue missing` lists them). b040-b063 not started.
- Imported so far: SINCLAIR + 15 h02 reports (11 + POPULARES, SUPTANERY, SATANIBRG, NBL replaced; KAIZENAGRO kept old). Reports finished by waves 3-4 are NOT imported yet: run `python -m reality_engine.scripts.ar_queue import-docs --run h02-scanned` (already-imported reports are skipped since the 06:00 fix).
- Fixed: a second import used to re-tag Haiku facts as rejected; 3,842 rows on 11 reports were restored.
- Not committed: my changes are in `reality_engine/scripts/ar_queue.py` (hard-report commands) and `ingest_annual_reports.py` (`shifted_digit_maps` + `value_check`), mixed with other sessions' uncommitted edits in the same files.

**Next:**
- Finish run h02-scanned after the 5-hour reset: 44 folders, b020-b063, 438 pages of FY2024-26 scanned reports.
  `ar_queue missing --run <abs path>` lists them. Launch waves of 10, then `import-docs --run <abs path>`.
- Then the other 87 garbled reports (~7.6k image pages; too many for Haiku alone).
  - **Free alternative to test first:** RapidOCR's text of these pages is clean (SINCLAIR p26). Feeding the OCR text to
    the free readers as a new text layer would cover all 111 garbled reports at no quota.
- **FIXED 2026-10-16 ~02:00 (resume side session): reports marked `done` with unread pages.**
  - Bug 1: `main()` resumed by piece index (`ok = {piece ...}`), whatever the prompt_version or piece size. A failed
    piece was hidden by an ok piece with the same index from another split. These pieces had failed on transient
    HTTP 500/429/503 errors.
  - Bug 2 was bigger. Two splits with the same prompt_version reused piece numbers, so `INSERT OR REPLACE` overwrote the
    other split's ok row. The facts `DELETE ... WHERE doc_id=? AND piece=?` then deleted that split's facts. Those pages
    lost their record and their facts. Example: doc 138108 has two ar-v1 splits, and pages 97-108 are gone.
  - Fix in `ingest_annual_reports.py`:
    - `unread_pieces()` resumes by page: a page counts as read if any ok piece of any version covers it.
    - Only the unread pages of a piece are sent.
    - A piece keeps its number only if no row already uses that number for another page range. Otherwise it gets a new
      number, so `INSERT OR REPLACE` and the facts DELETE can no longer touch another split.
    - Status at the end of a report is page-based: `partial` only if one of the split's text pages is still unread.
    - The live file was replaced atomically after a compile check, so workers never saw a broken file. No new
      `unreadable` rows appeared.
  - Before: 220 `done` reports had error-piece holes (252 pieces, 3,005 pages). An exact scan of every `done` report's
    uncovered pages (text >= 40 characters, the split's rule) found **1,858 `done` reports with 21,038 unread text
    pages**. That set includes all 220.
  - Re-marked those 1,858 as `partial`, with error 're-marked 2026-10-16: unread pages (page-based resume)'. Reopened
    their 37 `imported` claims to `claimed`; the old ts lets the main run take them.
  - After: 0 `done` reports with error-piece holes. 0 `done` reports with more uncovered pages than blank pages. The
    other 6,349 `done` reports with gaps have only blank pages.
  - `partial` is now 2,043 reports (402 with error-piece holes, 4,526 pages).
  - **Takes effect only when a worker restarts.** Each pass builds its to-do list at start, and the running parents
    still hold the old code until then: index resume, and the overwrite bug for reports they resume. Workers were
    NOT restarted. Restart them when convenient; the next pass reads only the unread pages.
  - Not fixed: `ar_queue.py import-docs` (the old OpenCode path) still writes by piece index with INSERT OR REPLACE.

## HAND-OFF 2026-10-15 07:20 (read first; overnight co-pilot session, Claude checking every 30 min)

**Annual reports:** 13,550 done (2.12M pages), ~20k left. Speed ~800-1,340 pages/min. Biggest in the 05:30-06:15 burst:
Cat Jam ~20k pages, then Zen; afterwards LongCat ~340, Gemma 26B ~290, Gemma 31B ~125. Flash-Lite is capped until 12:30.
ETA ~2.5-3 days.

**Fixed overnight (all in `ingest_annual_reports.py` unless noted):**
- **Gemma 26B (~5% speed for 13 h):** bilingual reports (PSU banks) have Hindi pages at ~2 tokens/char, so pieces of
  46-76k tokens could never fit the 16k tokens/min limit. They bounced forever and starved every thread.
  - Hindi pages are now skipped when the report has at least as many English pages (`ar_skipped_pages.containment='hindi'`).
  - Google routes release reports with a still-oversized piece to the main run.
  - The pacer uses a script-aware token estimate.
  - Result: 26B back to 170-290 pages/min.
- **The 26B fallback (Gemma 31B) failing no longer rests healthy 26B keys** (`FallbackFailed`).
- **Benches:** Google keys rest 2 min on 500/503. Go readers rest 3 min. No bench runs past 00:00 UTC (05:30 IST), when
  Zen and Cat Jam reset.
- **Cat Jam Go budget confirmed DAILY, reset 05:30 IST.** It now reads exhaustive 18k: 20 facts/page, ~20k pages a day.
- **Watchdog (`resource_watchdog.py`):**
  - per-reader drop check (`reader_drops()`) and an unreadable-burst incident;
  - orphaned `--pieces-json` children are killed (three orphans read ~1 GB/s for up to 15 h on 10-14 after my restarts);
  - AR review at most every 12 h at low priority (it scanned all facts hourly and bloated the WAL to ~1 GB).
- **Main-run piece size 18k** (Shivam): LongCat +30% facts per report.
- **Font-encoded digits (Coptic letters)** are now verified by `value_check`; 17 reports re-checked.

**Local Haiku work (10-15 night):** see `tasks/LOCAL_HAIKU_SESSION.md`. Batch 7: b000-b021 done locally,
b022-b087 left. Batch 8: all 76 folders left. Then deck no-figure pages and hard annual reports.

**Open:**
- FIXED 08:20: 'Expecting value' / ar_yoy 'invalid literal' unreadable reports. MuPDF printed colour-profile warnings
  to stdout ahead of the JSON. Children now silence MuPDF and the parent parses from the JSON. 21+26 reports re-queued;
  only SDC (a malformed PDF) is still unreadable.
- FIXED 12:41: Flash-Lite fallback is now Gemma 26B (31B outage starved the Flash-Lite routes; 3.5 FL 0 -> 105 pages/min).
- FIXED 07:45: a single Go 429 now pauses only that thread (~30 s); the whole reader rests only at 20+ 429s/min.
  LongCat went from 280 to 467 pages/min.
- Kilo Step: StepFun upstream refused everything ('current 151, limit 150'). Retry at a quieter hour.
- Cloud credit, hard deck pages:
  - Batches 1-3 imported: 2,333 pages, $3 + $7 + (batch 3 cost: ask Shivam).
  - 5,202 disagreement pages left.
  - `export-hard` works. Fix `CLOUD_TASK.md` paths after export: they must be relative to the repo root (see this
    session's patch script).
  - From batch 4, Haiku also writes `CHART | ...` trend lines for charts without printed values. Views `unlabeled_charts`
    and `unlabeled_charts_all` are in `deck_figures.db`.
- Gemma 31B outage pattern: fine roughly 04:00-10:00 IST, HTTP 500 much of the rest of the day.

## Previous hand-off 2026-10-14 08:05 (read first; overnight session "Session progress check", Claude ran as co-pilot)

**Numbers at 08:00:**
- Annual reports: 9,198 done (1.38M pages); ~24.4k left (~3.2M pages after the year-over-year skip).
- Speed 07:00-08:00: ~1,450 pages/min. Cat Jam 772, LongCat 272, Gemma 31B 211, Gemma 26B 168, Zen 27, Flash-Lite ~4
  (daily caps used). ETA about 1.5-2 days if LongCat and Cat Jam stay free.
- Decks, second readings: 4,557 waiting + 3,003 queued; ~750/h on Step (Kilo, Go account 2). ETA ~18:00 today.
- Then the $92 cloud credit goes to the hardest deck pages (Shivam: wait until all second readings are done).
  Keep each Haiku agent under 100K tokens of context: above that Haiku bills 5x. ~15 slides per agent.

**New readers and settings (reader_profiles.json):**
- **Cat Jam** (free on Go, "limited time", text only, so no decks).
  - Passed the AR test: 25/25, 12,191 facts plain; 20,846 exhaustive.
  - Exhaustive prompt from 06:55. On the Go API production pieces show ~110 facts, the same as plain. A Go-API exhaustive
    test (`t-go-catjam-ex`) was running at 08:00 to settle whether exhaustive helps there.
  - Go slots: 64 per account. 128 gave 429s, and 128 per account also tripped an upstream quota at 01:56.
  - **Quota = a token budget shared by both Go accounts:** ~84M output tokens (~40-46k pages) per window, the same
    both times it was cut (01:58 and ~08:00). Still refused at 14:11; likely a daily budget reset at 00:00 UTC
    (05:30 IST); confirm with the first answer after 05:30 IST on 10-15. Slots only change how fast the budget is spent.
  - The exhaustive prompt helps on Zen (1.7x) but not on the Go API (~110 facts/piece, the same as plain). It costs no
    extra budget, so it stays.
  - Zen: 3 slots.
- **LongCat:** settled at 128 per account.
  - 192 and 160 drew its first-ever 429s.
  - With Cat Jam running, LongCat reads ~22 pieces/min per account at either 128 or 160, so the Go accounts seem to cap
    total in-flight work.
- **Zen:** Space Bunny and Muse moved to the exhaustive prompt by the tuner (2.5x facts).
  - 72k pieces were tested on Cat Jam and rejected: 31% fewer facts per report.
- **Google:** 37 keys. Shivam made 7 more projects on one account; per key they match the old keys (Gemma 26B 327 vs 322
  pages/key/h). `gemini_keys()` now loads every `GEMINI_API_KEY_n`, so more keys need only a restart.
  - Shivam plans 10 more on 10-14.
  - ToS note: Google APIs ToS 2d forbids circumventing limits (see `tasks/AR_CONTINGENCY.md`).

**Fixes made overnight (all live):**
- `ingest_annual_reports.py`:
  - Go readers rest on a 429 (Go 3 min, Zen 20 min) instead of burning retries.
  - Go readers got the missing `bench_until`. Its absence silently killed every Cat Jam thread 02:25-06:53.
  - Every reader thread is now guarded: a crash is logged and the thread restarts.
  - Clearer progress-log labels.
- `resource_watchdog.py`:
  - New-reader check every 2 h (was daily; Cat Jam arrived at 23:29).
  - AR review at most once an hour, one at a time. Three stacked reviews cut the main run to ~120 pages/min for ~20 min.
- `new_reader_check.py`: also auto-tests new free Go models via the Go API; a pass joins the main run at 32 slots.
- All `opencode` calls run without a console window. These were the blank windows Shivam saw.
- `reader_quality_test.py`:
  - `--exhaustive` deck prompt.
  - `gx:<google model>@g<n>` for any Google model on any key.
  - Per-model reports.

**Tests:**
- LongCat exhaustive_core: FAIL 22/25. LongCat stays on the plain prompt.
- Cohere North Mini Code (Kilo): FAIL 19/25, 4,492 facts. Kept for coding work.
- Google deck test with the exhaustive prompt: mostly blocked by Google overload (503) at US peak.
  - No free tier: Omni 1.1, Argon, 3.1 Pro.
  - Retired: 2.5 Flash and Pro.
  - Re-run the 3.5/3.6/3.7/3.8 Flash and 3.5 Flash-Lite deck tests after 12:30 IST; failed pages are re-read only.

**Files written:**
- `tasks/AR_CONTINGENCY.md`: what to do if LongCat stops being free. CPU-first build parked by Shivam; Go auto-test done.
- `tasks/FREE_MODELS_IDLE.md`: free models with spare capacity, for coding and strategy work after ingestion.

**Open for Shivam:**
- Add the 10 new Google projects, then restart the Google workers (or ask Claude to).
- Cat Jam's quota window: read the main-run log for `cat-jam ... rate-limited` and the first answer after it.

## Previous hand-off 2026-10-13 18:40 (superseded by the one above)

**Read next:**
- `tasks/OPENCODE_ORCHESTRATION.md`: how the OpenCode accounts are driven headlessly.
- `tasks/ar_study/READER_FINDINGS.md`: every model test, quota and incident.
- Config files in `reality_engine/scripts/`:
  - `reader_profiles.json`: per-model prompt, piece size, limits and slots.
  - `zen_models.json`: passed Zen models.
  - `reader_watch.json`: the daily checker's state.

**Running (all watchdog-managed, restart themselves; kill the python child to restart one):**
- **Annual reports** (`ingest_annual_reports.py` routes; claims in `ar_facts.db.ar_claims` keep them apart):
  - **Main run** (`run_ar_ingest.cmd`): Go LongCat x128 slots on BOTH Go accounts (`OPENCODE_GO_API_KEY`, `_2`),
    plus Gemma 31B (exhaustive prompt) on 30 Google keys. About 495 pages/min, newest first.
  - `run_ar_ggemma26.cmd`: Gemma 26B, exhaustive, ~170 pages/min.
  - `run_ar_google.cmd`: Flash-Lite 3.5, exhaustive, 18k pieces.
  - `run_ar_gflash31.cmd`: Flash-Lite 3.1, exhaustive, 9k pieces.
    Both Flash-Lite workers are limited by Google's daily caps; a daily refusal rests the key 1 h.
  - `run_ar_zen.cmd`: Zen free models, one daily allowance reset 00:00 UTC (05:30 IST), used up in ~1.5 h.
  - Total ~800+ pages/min; ~4.3M pages left as of 10-13 16:30, about 4 days.
- **Decks:** `run_deck_redo_deferred.cmd`, second readings. Readers: Go Step on both accounts, Kilo Step, Zen
  Step/MiMo/Muse when the Zen quota allows. About 19,600 pages left, roughly 15-20 h.
  - 800 pages were read by Claude Haiku via cloud batches (`claude_page_queue.py export-deferred / import-deferred`).
- **Profile tuner** (`run_profile_tuner.cmd`): waits for Zen; finishes the exhaustive tests for Space Bunny, Muse and
  Big Pickle; switches passing models to the exhaustive prompt; restarts the Zen worker.
- **Resource watchdog:**
  - restarts dead or stuck jobs, including a job that logs but reads no pages for 30 min;
  - runs `new_reader_check.py` daily after 09:00;
  - runs `ar_review.py` every 200 finished reports.

**Decisions and open items for Shivam:**
- Go LongCat stays on the PLAIN prompt. Exhaustive scored 23/25 with 13,413 facts. Option: retest with the
  `exhaustive_core` variant (`ar_queue.py test-export --exhaustive --core`; run `t-lcgo-exc` exists).
- Free models only; never a subscription's paid models (memory `feedback_free_models_only`).
- **Claude cloud credit:**
  - **Routines (RemoteTrigger) bill to the Pro plan, not the credit.**
  - A cloud session Shivam starts himself at claude.ai/code does use the credit: $7 for 300 slides (~$0.02/slide,
    inflated by an Opus start and a re-check pass). $92 left, expires 11-05.
  - **DECIDED (Shivam 2026-10-13 18:55): use the $92 ONLY for the hardest deck pages, the ones even the second
    reading struggles with.** That means pages whose primary and second readings disagree, pages still weak after the
    second reading (low recall against the text layer, few figures), and pages that errored on every reader.
    - Next session, step 1: add an `export-hard` mode to `claude_page_queue.py` that selects these after the free
      second readings finish (decks ETA ~10-14 Oct morning) and sizes the list (~$0.015-0.02 per slide).
    - Step 2: Shivam starts the claude.ai/code session per batch.
  - Batch recipe in memory `feedback_cloud_credit_sessions`.
- **Spend so far:** OpenCode accounts $20.77 (2 Go subscriptions now).
- **Pro weekly usage:** 96%, resets Friday 23:30. A very long session costs a lot per turn; start fresh sessions.
- **Parked:** to-dos 3 (row clean-up) and 4 (CPU parser fixes). CPU page-skip rules were rejected (they lose >0.5% of
  facts); only the year-over-year skip is in use.

## Previous hand-off 2026-10-12 14:15 (superseded by the one above)

**Running now (detached, kept alive by the resource watchdog; stop the watchdog BEFORE restarting a job by hand, or it
starts a duplicate - happened 13:48):**
1. **Annual-report fact extraction** - `reality_engine/scripts/run_ar_ingest.cmd` -> `ingest_annual_reports.py`, log
   `data/logs/ingest_annual_reports.log`, output `data/ar_facts.db` (ar_docs / ar_pieces / ar_facts). Readers: LongCat
   (OpenCode Go free, 32 slots) + Gemma 4 31B on 8 Google keys (GEMINI_API_KEY, _2.._8; native API, token-paced 15k/min
   per key). Every text page read in ~10-page pieces, newest filing first; each fact carries isin, symbol, fiscal_year
   (+source), filed_at (+source), page, quote, model, value_check (page/piece/not_found/prose). At 14:15: 426 reports
   done, 6,383 pieces ok, 45 failed (mostly Google HTTP 500 on Gemma; retried on a later pass), 240k facts.
   ~125-130 report pages/min before the 13:48 restart. **Check:** Gemma slots were raised 3 -> 6 per key at 13:48
   (latency ~4 min/piece was capping it at ~1/3 of the 16k TPM); compare Gemma pieces/hour after 14:00 with 122 in
   13:00-13:48; revert to 3 if not faster. **Result (15:00): no gain** - Gemma 12:00-13:00: 147 pieces / 1,847 pages; 14:00-15:00: 169 pieces / 1,787 pages, avg seconds per piece 219 -> 412 (Google serves slower with more in flight; we use only ~4k of 16k tokens/min per key, so the limit is Google's free-tier service rate, not our pacing). 0 errors since the restart. Keeping 6 or reverting to 3 makes no throughput difference. Full set at this pace: weeks, not days (see to-do 2 and Haiku option).
2. **Deck second readings** - `run_deck_redo_deferred.cmd` (`extract_deck_figures --redo-deferred`), log
   `data/logs/extract_deck_figures.log`. Only Step via Kilo works (~600-1,000 pages/h); OpenCode's free Step has been
   rate-limited since 2026-10-11 21:27; StepFun out of balance. 38,039 deferred + 3,003 queued left at 14:15 -> ETA
   ~Wed/Thu. Option pending Shivam: Claude Haiku 5.5 via Anthropic Batch API ~$25 for all (needs Anthropic API key).
3. **Resource watchdog** - starts at logon; report printed into every Claude session by the SessionStart hook.
4. **AR Zen worker (2026-10-12 16:49, Shivam: "get all annual reports done; use every free Zen model once it passes")**
   - Process: `run_ar_zen.cmd` -> `ingest_annual_reports.py --route zen`; log `data/logs/ingest_annual_reports_zen.log`.
   - Readers: OpenCode Zen free models listed in `reality_engine/scripts/zen_models.json` (model -> slots). It reads through
     `opencode run` (CLI v2, background service), one call per piece, and reads oldest filing first. It is a watchdog
     job (`ar-zen`).
   - Why the CLI: Zen free models refuse direct API calls and custom agent prompts; the stock agent answers.
   - Work split: claims in `ar_facts.db` table `ar_claims`. The Zen worker claims each report; the Python run skips
     claimed reports (from its next restart). The two ends of the queue meet only weeks from now. Facts from this route
     carry model `zen:<id>`.
   - Admission: a model joins `zen_models.json` only after 25/25 must-find and < 1% numbers not in the text. Commands:
     `ar_queue.py test-export / drive / test-score`. Handbook: `tasks/OPENCODE_AR_HANDBOOK.md`.
   - Status 16:50: LongCat x6 in production. Tests running for MiMo, Step, Muse 1.3, Ling 3.1, Nemotron Lightning,
     Nemotron Ultra, Space Bunny and Big Pickle, plus LongCat at 36k / 72k / 144k characters per piece (bigger pieces
     mean fewer calls; attachments arrive whole). Dead: exo-free, ling-3.0-flash-fin-free; gone: muse 1.2, jev.
   - Batch `zen01` (2 reports, claims owned by `queue-zen01`): import it once its driver finishes.
   - Each `opencode run` call creates an OpenCode session (`ar-queue ...` titles); they can be deleted freely.
   - RAM: about 170 MB per process.
   - **Zen free quota is per account or IP, not per model (2026-10-12).** LongCat was refused from 17:00; at 18:31 and
     again at 18:51, every Zen model was refused in the same second. The Zen route used up the allowance in about 2 h
     at ~150 pages/min, with ~35 calls in flight across AR, deck and tests. It resets daily at 00:00 UTC (05:30 IST):
     all four models answered again at 05:30 on 10-13. Next: pace Zen to the sustainable rate, AR first.
   - **Free models are time-limited promotions** (OpenCode posts on X, dates in `zen_models.json` `free_until`):
     LongCat ~2026-10-10 (past), Space Bunny "a few more days" from 2026-10-06, Step ~2026-10-15, Ling 3.1 from
     2026-10-02 (no end date). Go LongCat carries ~60% of the main run's pieces, so the main run can drop to Gemma only
     (~45 pages/min). Gemma (8 Google keys) is the only durable free reader. Options for Shivam: more Google keys, a
     Haiku batch for ARs (~$600) or decks (~$25), or a slower finish.
   - **Incident 2026-10-12 ~18:00-22:06: the main AR run read nothing for 4 h.** A malformed PDF made PyMuPDF spin
     inside the run while holding Python's lock, so every reader thread stood still, and each restart reached the same
     PDF within 30 s. The watchdog did not catch it: the log kept a line per restart. Fix: every report's text split
     now runs in a child process with a 3-min limit (`pieces_isolated`; the year-over-year reference too, in
     `ar_yoy.py`); a hanging PDF is marked `unreadable` and skipped.
   - **Google route (2026-10-13 00:51)**: `run_ar_google.cmd` -> `ingest_annual_reports.py --route google`; log
     `ingest_annual_reports_google.log`; watchdog job `ar-google`.
     - Readers: Gemini 3.5 Flash-Lite on all 30 GEMINI keys, 18k-char pieces (~5 pages). Claims reports oldest-first
       (owner `google-flash`), alongside the Zen worker without overlap.
     - An empty answer (Flash-Lite returns STOP with no text on some pieces) is re-read at once by Gemma 31B and stored
       under Gemma's name.
     - Free quota is per model and per project: Flash-Lite 15/min, 250k TPM, 500/day per key, so ~15k pieces/day; a key
       at its daily cap rests until PT midnight (12:30 IST).
     - First minutes: 0.19% of numbers not in the text, 3% of pieces went to the fallback.
   - **AR admission tests 2026-10-13** (`FINDINGS.md`):
     - 3.5 Flash-Lite: 36k pieces 24/25 and too shallow; 18k pieces 25/25, 5,459 facts, but 28 empty pieces held 118
       Space Bunny facts, hence the fallback.
     - 3.1 Flash-Lite: 25/25 but only 1,189 facts (fail, depth rule).
     - Gemma 26B: 24/25, 3,078 facts (fail).
     - New depth rule: >= 4,500 facts on the 110 test pieces.
     - Kilo Ling 3.1 and Laguna S 2.1 tests still running.
     - Gemma 31B's tokens/min hit 17.9k of 16k on the AI Studio dashboard: pacer lowered to 13.5k (takes effect at the
       main run's next restart).
   - Register of passed models: `reality_engine/scripts/zen_models.json`. Passed: LongCat, Space Bunny, Muse 1.3,
     Big Pickle; never retest these. A rate-limited model benches itself 20 min and retries.
   - Paused tests (resume with `ar_queue.py drive --run t-mimo,t-step,t-nemotron,t-nemoultra`): MiMo 20/110,
     Step 24/110, Nemotron Lightning 11/110, Nemotron Ultra 18/110. The daily new-reader check scores them when done.
   - Daily new-reader check: `new_reader_check.py`, started by the watchdog after 09:00. It diffs the Zen/Go/Kilo free
     lists, starts AR tests for new Zen models and auto-registers passes; its report is appended to the watchdog
     report.
   - Deck second readers via Zen (`*@zen` in `extract_deck_figures.py`): Step, MiMo and Muse passed the 40-page test
     (94.2/93.7/93.6% identifiable, no misreads), but they share the same Zen quota.
   - Year-over-year page skip (to-do 2) is live in both AR workers (`ar_yoy.py`; table `ar_skipped_pages`): ~14% of
     pages in reports that have a previous year; no must-find page skipped.
   - To-dos 3 and 4 (row clean-up, CPU parser fixes) are parked: the running pipeline reads every page with LLMs, so
     they matter only if the AR run switches to the CPU-first design.

**Reader test results 2026-10-11/12** (details: `reality_engine/data/reader_tests/*/VERDICT.md`,
`tasks/ar_study/free_test/FINDINGS.md`): decks - Gemma 4 31B passes (86.9% identifiable, opt-in), Gemma 4 26B 83.8%,
Gemini 3.1 Flash-Lite 78%, 3.8 Flash 80%, CodeCraft Opus/Sonnet ~94% (anonymous provider, test only), GPT-5.6 Luna
altered printed numbers. ARs - LongCat 25/25, Gemma 4 31B 25/25 (0.4% numbers not in text), Gemma 26B 25/25 but misread
Indian grouping 10x, Dots 24/25 but loops and cites wrong pages, Glyph Cluster 18/25, NIM models too slow. Kilo has no
batch API; Haiku batch is $0.05/$0.25 per M for prompts <= 100k tokens.

**To-dos for the next session (all four):** see "Next" below - (1) daily new-reader check, (2) safe YoY page skip in
the AR run (numbers NOT masked), (3) row clean-up refinements, (4) AR parser fixes. Retrieval gaps are parked
(`tasks/RETRIEVAL_GAPS.md`).

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
| Job | Start / restart | Log | State at 2026-10-11 00:45 |
|---|---|---|---|
| Deck-figure extraction | `reality_engine/scripts/run_deck_extract.cmd` (repeats passes; restarts after a crash) | `reality_engine/data/logs/extract_deck_figures.log` | 523,710 of ~820k pages (64%), 16,935/26,521 decks opened, 7.60M final figures; only ~1.3 pages/s now because the disk is saturated by the AR download (C: and D: are partitions of ONE physical disk); expect 8-12 pages/s once it ends. Step second-reading queue 28,168. |
| Annual-report download, active companies, FY2019+ (to D:) | `reality_engine/scripts/run_ar_download_d.cmd` (5 passes) | `reality_engine/data/logs/annual_report_ingest.log` | 18,000/19,613 downloaded, 5 failed, ~100/min. Files in `D:\RealityEngine\pdfs` (REALITY_ENGINE_PDFS_DIR). A watcher stops it if D: falls under 10 GB free (D: had 20 GB free at 00:45); then finish on C: with `run_filing_download.cmd ar`. |
| Hourly AR ingest (scheduled task `realityengine-annualdrain`) | Windows Task Scheduler | `annual_drain_watchdog.log` | DISABLED 2026-10-11 01:30 by Shivam (stopped at 22/143 of the new batch). Re-enable with `schtasks /Change /TN realityengine-annualdrain /ENABLE` from an admin shell once the AR study settles how ARs are indexed. |

2026-10-11 01:55 extractor restarted with two fixes: a 429 on a second reader now benches only that reader for 5 min (before, it paused the whole second pool, idling the paid StepFun slots); a 429 saying the free quota is used up (Space Bunny `FreeUsageLimitError`, out since ~01:00) benches that reader for 30 min and its pages go to the others. When restarting from a shell older than the KILO_API_KEY_2 / STEPFUN_API_KEY user variables, load the user environment first or dots@kilo2 silently drops out.

Resource watchdog (2026-10-11, replaces the night watchdog): `reality_engine/scripts/resource_watchdog.py`, started at logon (Startup folder) or with `run_resource_watchdog.cmd` via run_hidden.vbs. Keeps managed jobs alive (JOBS list; restarts with the job's own last command line, max 6/day, 30 min apart), kills orphaned workers, records waste incidents (disk_hog, cpu_hog, low_ram, job_slow, job_hung, job_stopped) in `data/logs/resource_incidents.jsonl` and `resource_watchdog_report.md`; a SessionStart hook in ~/.claude/settings.json prints the report into every Claude session. Stop the watchdog before stopping a managed job by hand.

Deck extraction: first full pass finished 2026-10-11 14:44 (26,512 decks, 627k pages read, 12.6M facts). Second-reading run for the 53,393 deferred pages started 16:05 (`run_deck_redo_deferred.cmd` = `--redo-deferred`). Readers 2026-10-11 afternoon: LongCat, free Step (OpenCode, need the x-opencode-session header, which the extractor sends), Dots x2 and Step via Kilo work; Space Bunny's free tier is now refused over the API (403 FreeTierError; listed as paid on Go) and was removed from the defaults; StepFun balance used up (402).

To stop the extractor, end the `cmd.exe` running `run_deck_extract.cmd` with `taskkill /T /F` (whole tree). Match on `Name -eq 'cmd.exe'` when searching by command line: a PowerShell command whose own text contains 'run_deck_extract' matches itself (2026-10-11 restart killed itself that way).

## Data coverage 2026-10-11 (`python -m reality_engine.scripts.coverage_report`, every company traded that year)
Rule (Shivam, 2026-10-10): **all data for every traded stock (main board, SME, IPO) since 2019 must be in place before any strategy test.** The coverage report is the gate.

| Year | Traded | AR held | Concalls held | PPT indexed | Quarterly (old yfinance table) |
|---|---|---|---|---|---|
| 2019 | 5,124 | 1,716 (33%) | 10 | 0 | 0 |
| 2021 | 5,538 | 3,361 (61%) | 175 | 774 (14%) | 1 |
| 2023 | 5,863 | 3,512 (60%) | 919 (16%) | 1,044 (18%) | 0 |
| 2025 | 7,806 | 3,889 (50%) | 1,223 (16%) | 1,466 (19%) | 2,126 (27%) |

- Annual reports FY2019+: 35,228 listed (BSE annual-report API for every scrip traded on BSE since 2019: `fetch_bse_annual_report_dates.py fetch --all-scrips` + `discover` added 21,351), ~33k downloaded when the D: run ends. Left out: 768 reports of delisted companies, 1,517 BSE reports with no known ISIN, 38 scrips whose list fetch failed, ~200 undated. Pre-2019 PDFs (7.9 GB) kept for now. Many companies file no AR in a given year on BSE (new listings, SME), so 100% is not expected.
- Concalls 2022+: all downloaded (7,321 Screener-found + 3,179 from the BSE announcement feed via `discover_bse_feed_docs.py`). Only ~1,300 companies hold concalls at all. Decision (Shivam): use concalls from 2022 only.
- Quarterly results: NEW `reality_engine/data/results_xbrl.db` from the 76k NSE results XBRL files (`parse_nse_results_xbrl.py`): tables `filings` (dissemination timestamp = PIT), `facts` (all non-dimensional facts incl. balance sheet and cash flow), view `quarterly` (context `OneD` = the reporting period; context dates are not trusted). 76,093 filings, 2,727 companies, quarters Dec 2018 to Dec 2024. Checked: TCS Q3 FY25 consolidated revenue 63,973 cr, PAT 12,444 cr, EPS 34.21. Not yet in coverage_report (it still counts the yfinance table).
  - **Gap 1: March 2025 onward.** SEBI moved results to "Integrated Filing (Financials)"; NSE's old results feed has almost nothing after Feb 2025 (re-fetched 2026-10-10 to be sure). Needs a fetch of the integrated-filing results (NSE and BSE).
  - **Gap 2: ~2,700 BSE-only companies** have no NSE results filings: needs a BSE results fetch.
- Investor presentations: 25,660 decks (BSE 2021+, NSE-only companies). 2020 decks are in the BSE feed (25,618 'Investor Presentation' rows from 2020-01) but not fetched yet: `fetch_decks.py bse --since 2020-01-01` after the AR download (BSE/Akamai throttles). 2019 needs the BSE announcement feed extended back (approved, not started).
- Prices: BSE and NSE (all series incl. SME SM/ST via `mkt_nse_full_daily`) current to 2026-10-09. The separate NSE SME bhavcopy file stopped 2025-10-10 (URL change) but SME prices continue in the full file.

## Deck figures (built 2026-10-09)
- **Sources** (`reality_engine/scripts/fetch_decks.py`; files in `reality_engine/data/decks/`; manifest table `deck_sources` in `reality_engine/data/deck_figures.db`): BSE "Investor Presentation" filings 2021-01 → 2026-09 (24,674 PDFs, 107 GB, 4 failed); for the 707 NSE-only companies, decks found in their NSE announcement history by keyword and size (1,713 PDFs, 15 GB; raw announcement JSON in `raw_market/nse_announcements/`); plus the 1,152 `corporate_documents` decks (463 meeting-intimation letters excluded). Every deck carries the exchange dissemination time (point-in-time).
- **Extraction** (`reality_engine/scripts/extract_deck_figures.py` → `deck_figures.db`: `pages`, `outputs`, `facts`, `spend`, `bad_docs`, `doc_pages`): each PDF rendered in an isolated child process (a malformed PDF can no longer kill the run). **Page gate**: pages with ≥3 text-layer numbers go to a reader; text pages with ≤2 are skipped; image-heavy pages with ≤2 go only if RapidOCR (DirectML on the RX 6700 XT, ~0.4 s/page) finds ≥2 numbers (skips ~37% of pages, est. <0.2% of figures lost). **Readers** (all free): LongCat 2.5 Preview primary + Dots 3 Note via Kilo (`KILO_API_KEY`, plus a second account `KILO_API_KEY_2` as reader `dots@kilo2` since 2026-10-10; the Kilo throttle is shared across both keys, clean at ~60 in flight, so 30 per key) as further primaries; Step 5 Preview second reader on weak pages. Since 2026-10-09 21:45 the primaries take turns (LongCat, Dots, LongCat...; whichever has a free slot), and second readings go through a persistent `second_queue` table read by their own pool, so a throttled Step no longer holds primary workers (before: Step at its floor of 10 left ~90 of 110 workers waiting, 0.5 pages/s). A page is saved with its primary reading first and updated when the second reading lands; above 5,000 queued pages workers wait inline again. Paid OpenCode models (MiMo, Muse) are opt-in only (`--also-primary/--also-second`). Ornith (local GPU) dropped: 0.11 pages/s; GPU kept for RapidOCR. Tests: `reality_engine/tests/test_extract_deck_figures.py` (12).
- **2026-10-10 afternoon fixes** (extract_deck_figures.py): (1) new pages no longer join Step's second-reading queue (`SECOND_DEFERRED` marks them in pages.error; `--enqueue-second` turns it back on); the pool keeps draining the ~20.8k backlog. (2) decimal commas: `parse_number('9,7')` = 9.7; 319 stored facts re-parsed (many were footnote/slide refs like "1,2", junk either way). (3) currency scale: a bare Rs/₹/INR unit gets its scale only from the number's suffix or the label; 1,409 stored facts fixed, old units in table `facts_unit_fix`. A page-text rule ("Rs. in Lacs" in the header) was tried and reverted (wrongly scaled EPS/face value/prices); ~9.0k large bare-Rs facts on 1,773 pages remain (list: `claude_queue/scale_review_pages.csv`), mostly genuine rupee amounts; the header-only cases need a Haiku re-read with a carry-the-header-scale rule (~6 waves, ~60% of a 5-hour window). QUEUED, NOT STARTED: run only when Shivam says go; needs an export-from-list mode in claude_page_queue.py (export today only takes unread pages). (4) 315 Haiku pages flagged as uncertain (list: `claude_queue/flagged_pages_2026-10-10.csv`) re-checked by Haiku (`review_20261010_flagged`, instructions `REVIEW_INSTRUCTIONS.md`): 105 changed, re-imported.
- **Quality test** (40 pages, hand-checked slides; share of figures identifiable = unique label+period+unit): Haiku 5.5 100%, Step 96.3%, Muse 93.5%, Dots 90.4%, Ornith 85.6%, LongCat 85.2%, MiMo 82.7%; none misread a number. Local models on Vulkan failed (Qwen3-VL-4B 31.7% identifiable, MiniCPM-V 4.6 27% recall, GLM-OCR ignores the format); Vulkan reads images ~20x slower than ROCm on this card. Finding: PDF text layers can be wrong (VENKEYS: 204.33 in text vs 254.33 printed; totals confirm the image), so text-layer recall is a guide, not ground truth.
- **Value check** (20-deck pilot): 77% of figures are operating KPIs the DB does not hold (volumes, capacity, beds/ARPOB, inventory, order book, segment revenue). Overlapping headline figures match `quarterly_financials` (SOBHA Q1 FY27 EBITDA and PAT exact, revenue within 4%). Note `quarterly_financials` is mostly yfinance (13,552 of 15,261 rows, no filing dates).
- **Limits**: the OpenCode Go caps (rolling 5 h / weekly / monthly) are ONE budget for the whole account, shared with Shivam's own coding; the 2026-10-09 run used 99% of the weekly and 93% of the monthly allowance, which is why paid models are now opt-in. OpenCode refuses MiMo/Muse with HTTP 402 before the pipeline's own spend estimate reaches the plan cap (MiMo was cut off at ~$7.6 of the $12 / 5 h estimate); a 402 now benches that model for 30 min and its pages go to the free reader. Free models are "limited time": when the free list at https://opencode.ai/v2/docs/console/go changes, re-run the 40-page quality test before switching. Muse Contributor prompts are used for Meta training (public filings only).
- **Claude Haiku 5.5 queue** (`reality_engine/scripts/claude_page_queue.py`): `export` claims unread pages oldest-decks-first (extractor goes newest-first) into `reality_engine/data/claude_queue/run_*/bNNN/`, Haiku 5.5 helper agents (15 pages each, max 20 at once) write `NNNNN.txt`, `import` loads them as model `claude-haiku-5-5`; unanswered claims fall back to the extractor after 24 h. 8,399 pages done in 28 waves (as of 2026-10-10 09:05; waves 22-28 used ~10% of the 5-hour limit each; wave cap now 80% of the 5-hour limit per Shivam; always verify an export wrote manifest.json and 300 pages before launching agents, one silent export failure on 2026-10-10) (waves 6-13 on 2026-10-09 evening, 300 pages each, ~9% of the Pro 5-hour limit per wave); label junk 1.2% (waves 1-5). Agent instructions live in `reality_engine/data/claude_queue/AGENT_INSTRUCTIONS.md` (includes the down-arrow-as-negative rule from wave 6 on). Agent instruction: image wins on different digits, keep text-layer decimals when the number is the same, skip product/model/certification codes and axis ticks; down-arrow/decline figures are written as negative (rule added for wave 6+; wave 5 lost the sign on ▼ figures).
- **Annual report dates fixed** (2026-10-10, `reality_engine/scripts/fetch_bse_annual_report_dates.py`): BSE's AnnualReport API gives each report's filing timestamp keyed by our PDF file name; 2,388 scrip codes fetched into `bse_annual_reports` (codes from master_companies plus codes read from the PDF path for delisted/suspended companies), 25,462 AR rows got `publication_date` (`pit_source='bse_ar_api'`, undo by that tag). AR PIT basis now: bse_ar_api 19,314, bse_feed 6,669, filename 434, unknown 197 (99.3% dated). Coverage FY2012-2026. Filed since 2019-07: 14,720 reports, 2,051 downloaded, ~12.7k to download (~110-115 GB at ~9 MB each; C: has 233 GB free). Download waits for the AR value study.
- **Annual report value study** (2026-10-10): separate session, brief in `tasks/ANNUAL_REPORT_VALUE_STUDY.md`, output in `tasks/ar_study/`. Phase 1 = 2 reports read by Sonnet against same-year concall/PPT; decides which AR sections to keep, tabulate or drop before downloading more ARs. Concalls: use 2022 onwards only. Phase 1 done 2026-10-10 with Haiku readers (Shivam's call): COCHINSHIP + CONCOR FY24, findings in `tasks/ar_study/PHASE1_FINDINGS.md`, ~14% of a 5-hour window. Re-run on GESHIP FY24 with the revised method (section split, reference-fact list, stricter verdicts) done: `tasks/ar_study/PHASE1B_GESHIP_FINDINGS.md` (keep-text fell to 1% of tokens, no false contradictions, but no token saving; a heading-rule pre-filter is proposed for Phase 2). **Direction (Shivam, 2026-10-10): the goal is that all relevant AR data is stored at true quality; efficiency is secondary. Bulk AR reading goes to the free OpenCode Go / Kilo models, not Claude.** Next: once concall ingestion finishes (expected end of 2026-10-10), test free-model readers against the Haiku-verified gold set (COCHINSHIP, CONCOR, GESHIP FY24). Plan: `tasks/ar_study/FREE_MODEL_QUALITY_PLAN.md`. **CPU-vs-LLM challenger study done 2026-10-11** (`tasks/ar_study/CHALLENGER_FINDINGS.md`, code in `tasks/ar_study/challenger/`): rules alone (PyMuPDF, ~1 CPU-min per report) put 95% of tabular gold numbers into rows (46% clean, 27% multi-column needing a header parser) and found 16/17 headline signals. An LLM is needed for numbers in prose (~75% of them are not cleanly structured), for interpreting auditor/C&AG/contingency blocks, and for untriggered surprises. GPU OCR added nothing (0 figures on 21 low-text pages). Rules were tuned on these 3 reports. **Part 2 (same day): template-free column-header parser (`challenger/columns.py`) + test on 10 unseen FY24 reports** (Axis, Bajaj Fin, Infosys, Dabur, Cipla, Cummins, Atul, Exide, Sobha, JK Cement): standard statements parse right where layouts are plain (Dabur, JK Cement balance sheets balance; Sobha revenue/profit match yfinance), but only 35-59% of table figures land in labelled, dated rows and ~30% of random rows are wrong; banks/NBFCs weakest. Proposed: CPU parses all, a validation layer (totals add up, BS balances) plus confidence decides `cpu_ok` vs send that table to a free LLM. Next: build the validation layer. **CPU levers measured 2026-10-11** (`tasks/ar_study/CPU_LEVERS.md`): 59% of AR text repeats last year's AR; statements are already in `results_xbrl.db`; LLM slice (kept AND new vs last year) ≈ 9% of characters (~28 page-equivalents per AR, ~half the deck job in total; whole-AR LLM reading would be ~4×).
- Approved and queued, not started: extend the BSE announcement feed back to 2019. Pending Shivam: annual-report dating via AGM notices.

- **OpenCode CLI route (2026-10-11 01:15):** Windows npm install repaired (`node postinstall.mjs` in npm/node_modules/opencode-ai; v1.18.33). Saved keys in `~/.local/share/opencode/auth.json` are stale ("Invalid credential"; they differ from the env keys): run `opencode auth login` (OpenCode Zen) to fix. With a clean profile (no keys) the free models answer but every call got "Rate limit exceeded", and the Zen API now returns `FreeUsageLimitError` for Space Bunny too: OpenCode's free usage limit looks per user/IP and was used up by the Space Bunny reader. Re-test after it resets: `opencode run --pure -m opencode/mimo-v2.6-flash-free -f page.jpg "<prompt>"` (put -f after the message: -f swallows following words).

## Next (in order)
- **Queued for 2026-10-13 (Shivam: "put it in the pipeline for tomorrow, I will run it later"): daily new-reader check.** Read the free lists on OpenCode Go (docs page + API) and Kilo (API, incl. `pricing.discount`), flag new/changed/discounted free models, auto-run the 40-page deck test (`reality_engine/scripts/reader_quality_test.py`, image models) and the AR 25-fact test (`tasks/ar_study/free_test/free_reader_test.py`), keep a ranking file, add passing models as readers, report in the resource-watchdog report. Free readers in use/passed as of 2026-10-12: decks LongCat, Dots, Step (Gemma 4 31B passed, opt-in); ARs LongCat and Gemma 4 31B (25/25). 8 Google AI Studio keys set (GEMINI_API_KEY, _2.._8).
- **Queued for 2026-10-13: safe year-over-year page skip in the AR run** (`reality_engine/scripts/ingest_annual_reports.py`, running since 2026-10-12 03:40, LongCat + Gemma 4 31B x8 keys, every text page read). Skip a page only if it appears near word-for-word INCLUDING numbers in the same company's previous-year AR (the study's yoy.py masks numbers, which would skip tables with changed figures - do not use it for this). First AR per company: no skip. Test on the 3 study reports (25/25 must-find must hold) before restarting. Expected 30-40% fewer pages (free run ~2-2.5 weeks instead of 3-4; Haiku batch ~$600 instead of ~$950). Deck second readings: ~49k left at ~730/h (Kilo Step) as of 03:45, ETA Thursday; Haiku batch ~$25 would finish in a day (needs Anthropic API key + credit, Shivam to decide).
- **Queued for 2026-10-13: row clean-up refinements** (AR protocol LLM stage a; guards in `reality_engine/processing/ar_row_guards.py`, fresh test at 89% on verified rows, `tasks/ar_study/free_test/FINDINGS.md`): (1) a second reader when two readings disagree on a label; (2) a check that a label naming a different measure (fair vs carrying, gross vs net) is supported by the column header. Target >= 90% fully right on a fresh page-checked sample.
- **Queued for 2026-10-13: AR parser fixes** (`tasks/ar_study/challenger/`, HANDOFF_AR_PIPELINE.md suggestion 3): BRSR two-page spreads (G5), physical units (tonnes, m3, GJ) and counts in BRSR/environment tables, bank schedule format and balance sheets split over two pages, and the section tagger labelling statement pages as CARO.
1. Quarterly results Mar 2025 onward: fetch NSE/BSE "Integrated Filing (Financials)"; then BSE results for BSE-only companies; then point coverage_report at results_xbrl.db and retire the yfinance quarterly table.
2. After the AR download: fetch 2020 decks (`fetch_decks.py bse --since 2020-01-01`), extend the BSE announcement feed to 2019 (decks/announcements), re-run coverage_report.
3. Haiku export-from-list mode in claude_page_queue.py (re-render chosen done pages): for "hard" pages (weak after second reading, reader error, SECOND_DEFERRED) and the 1,773-page rupee-scale re-read (waits for Shivam's go).
4. Normalise deck figures into a point-in-time KPI table once extraction completes.
5. Shared test harness, hypothesis registry, scheduled jobs (unchanged from before).

## Annual reports: build plan (approved by Shivam 2026-10-11, start 2026-10-12; first test results wanted before market open)
Design: CPU does the bulk; free LLMs (OpenCode Go / Kilo) get only the useful slice; no Claude bulk reads.
Evidence: `tasks/ar_study/CHALLENGER_FINDINGS.md` (parts 1-2), `tasks/ar_study/CPU_LEVERS.md`. Prototype code: `tasks/ar_study/challenger/` (`extract_cpu.py`, `columns.py`, scorers, `test_unseen.py`). Move into `reality_engine/` only once step 4 passes.

**Order (each step produces usable output on its own):**
1. **Statements from XBRL** (~2 h). Map `results_xbrl.db` FY "Yearly" filings (standalone + consolidated) to the AR's fiscal year. These become the trusted statement figures. AR statement pages are used only as a cross-check.
   - Done when: Cochin/CONCOR/GESHIP/Dabur FY24 revenue, PAT, operating cash flow and total assets tie to the AR within rounding.
2. **Year-over-year diff** (~2 h). 8-word shingles, numbers masked, against the same company's previous AR.
   - Output per paragraph: `new` / `repeated`. Repeated text is stored once and updated only when it changes.
   - Process newest year first and diff backwards; a company's first AR has no baseline.
   - Done when: Cochin's 1,200-passenger vessel note (p.138) and SBFA passages come out `new` (measured 79-96% new).
3. **Validation gate** (~3 h). A table is `cpu_ok` when its confidence is ≥ 0.7 AND one of these holds:
   - its subtotals add to its total;
   - the balance sheet balances, across 2 pages if needed;
   - a figure matches XBRL. A match also fixes the table's unit and year columns.

   Everything else is `send_to_llm`, as that table only.
   - Fixes to include: % / holding / count columns are not ₹; stop merging the next heading into total-row labels;
     bank/NBFC word list and schedule format.
4. **Run on 10 unseen + 3 study reports** (~1 h). Report per report:
   - share of tables `cpu_ok`;
   - balance/XBRL tie-outs;
   - LLM slice in page-equivalents (target ~28 per report, measured ~9% of characters; Axis 31% before the bank word list).
   - Hand-check 30 random `cpu_ok` rows: target ≥ 90% right (was ~50% before the gate).
5. **Free-LLM slice test** (after concall ingestion has freed the Kilo throttle). Send kept-and-new prose plus `send_to_llm` tables to the free readers. Score against the gold set (`tasks/ar_study/challenger/gold_*.json`, `FREE_MODEL_QUALITY_PLAN.md`): must-find recall ≥ 90%, no misread numbers.
6. **Store and index.**
   - DB tables: AR facts (ISIN, FY, filing time, page, unit, scope, period, source = xbrl/cpu/llm, check status) and AR text (new prose only, plus changed-only sections).
   - Search index: ~25-50 chunks per AR instead of 388.
   - Then bulk-run the downloaded ARs newest-first: ~5 s CPU per report; ~18 CPU-hours for 12.7k reports, 2-3 h on 8 workers.

Not on the critical path for Monday's strategy tests: AR facts are annual and slow-moving. If time is short, steps 1-4 still give tested CPU output, and steps 5-6 can follow during the week.

**Night of 2026-10-11, steps 1-4 run** (results: `tasks/ar_study/CHALLENGER_FINDINGS.md` Part 3, `tasks/ar_study/challenger/step4_report.md`):
- XBRL ties to the AR well (60-90% of XBRL figures found with correct labels; statements will come from XBRL).
- Year-over-year diff flags the surprises.
- Gate with the prior-year tie stores 33% of table cells. Rows that pass are ~74% fully right (target 90%); value, year and unit are right ~87% of the time, but labels are messy.
- New-prose LLM share is 28%, not the estimated 9%.
- Proposed fix: send compact CPU rows (not pages) to a free LLM to clean labels, and tighten the prose filter.

Morning list:
1. Tune the prose filter.
2. Row-mode LLM pass design and test.
3. BRSR spread pages and physical units.
4. Free-LLM slice test once the Kilo throttle is free.

## Known data gaps
- **Retrieval and labelling gaps** (audit 2026-10-11, deferred until the AR pipeline is done): no single point-in-time price/delivery view (6 tables, 3 keys, no ISIN history map); 47 companies' deck figures on placeholder `INE_AUTO_*` ISINs; index membership is a single 2026-09-30 snapshot of 3 indices (not point-in-time); some documents lack publication time. Details and fixes: `tasks/RETRIEVAL_GAPS.md`.
BSE insider 2023+ (paged API); MCX blocked; NSDL company-level limits need a form post; NSE FII derivative stats file ends Oct 2024 (participant OI covers after).

**OPEN, needs an owner (found 2026-10-10 by the AR study session; Shivam to pick up in another session):**
1. **RESOLVED 2026-10-10 (main session):** the download died at report 638/23,712 on 2026-09-26 (no traceback, process killed) and the hourly job only ran the Nifty200 stage, logging "complete". Fixed by the full-universe download + coverage report above. Original note: **Annual-report download job stopped part-way and nobody noticed.** `reality_engine/scripts/run_annual_report_ingest.py` orders Nifty200 → Nifty500 → rest. The only run (all rows `created_at` 2026-08-28 18:56) stopped inside the Nifty500 tier. Coverage now: Nifty200 197/197 companies (2,429/2,430 reports); Nifty500-only **117/288 companies** (1,085/2,882 reports); rest 0/1,936. Example: GESHIP has 15 indexed AR links (FY12-FY26) with 0 downloaded, so study candidate queries silently skipped it while Screener shows the reports. No log or STATE note recorded the stop or its reason. To do: find why it stopped (limit flag, crash, or a deliberate pause), add a coverage check (indexed vs downloaded per tier) so a partial run is visible, then resume. The AR value study decides *what* to keep, not whether to download.
2. **Partly addressed 2026-10-10:** `results_xbrl.db` facts carry cash-flow concepts where filed (mostly half-yearly), up to Dec 2024. Original note: **No cash-flow data held.** `annual_financials.operating_cash_flow_inr_cr` is 0 or null on 12,432 of 13,015 rows (source yfinance), e.g. COCHINSHIP, CONCOR, GESHIP FY24 all 0.0. `mkt_nse_pit_xbrl_facts` is insider-trading XBRL only (no financial statement concepts). So cash flow, contract liabilities, receivables, contingent liabilities and related-party figures currently exist only in the annual-report PDFs (or the unparsed results XBRL, Next #1; quarterly results usually carry cash flow only half-yearly). The AR study found a negative operating cash flow at COCHINSHIP FY24 (₹-172.8 cr vs ₹2,046 cr FY23) that no structured table holds.

## WRONG-COMPANY ANNUAL REPORTS (side session, 2026-10-16 15:15; free local checks only, no model quota)

**Scan:** `python -m reality_engine.scripts.ar_wrong_company_scan --data <main>/reality_engine/data --workers 8`
- Read-only, about 25 min for 25,432 reports. Same PyMuPDF text as `ar_queue.page_texts`.
- Output: `reality_engine/data/ar_queue/wrong_company_scan_all.csv` (every report) and `wrong_company_candidates.csv`
  (225 rows to check by hand, plus the hand-check results).
- Ties a PDF to its company by any of:
  - a known name on the first 5 pages or the auditor's report;
  - its ISIN issuer prefix;
  - its BSE scrip code.
- "Known names" include every name the scrip or ISIN traded under on BSE since 2019 (`mkt_bse_eq_daily`) and NSE names.
  So renames count as matches.
- Negative control: 400 reports scanned with another company's names. 0 came back ok, 1 landed in `name_late` (the
  review list).

**Result (verdicts):**
- ok: 24,767.
- former_name: 341 (own ISIN or scrip code in the text).
- listed_only: 125 (only BSE's listing ties the file to the company; 110+ are debt-instrument "symbols" like 9TCAP28).
- name_late: 100 (name only deep inside: mostly renames, or a cover with no text).
- unknown: 99 (fewer than 2 clean evidence pages: scanned or encoded files, PDF portfolios).

**The 3 known cases are NOT wrong PDFs.** They are the same companies under their former names:
- SIGMAADV 79913 = Megasoft (scrip 532408 on p1).
- VEGA 125476 = PH Trading (BSE name history of scrip 512026).
- SKYBIOTECH 125486 = Kapil Cotex (scrip 512036 on p1).
- BSE's own listing has each file under the right scrip.
- Their `ar_docs.error` 'WRONG COMPANY PDF' flags are wrong and should be cleared. Not done: this session is read-only.

**Confirmed wrong:**
- VENUSREM 92565, FY2026, 119 facts. It is Home First Finance's AGM notice (Home First's CIN, homefirstindia.com).
- BSE itself lists it under Venus's scrip 526953, so a BSE listing is not proof.
- **Unresolved:** LADIAMO 131564 and 131568 (Turner Industries notices; shared director, Laser Diamonds named later in
  the file).
- Hand-checked 20 others: all the right company (12 renames). Details are in the `hand_check` column.

**Quarantine proposal (AGENTS.md rule 13; facts stay where they are):**
1. Add a table `ar_doc_identity(doc_id PK, verdict, true_company, true_isin, evidence, checked_by, checked_at)` in
   ar_facts.db. Write a row only after a hand check (`verdict='wrong_company'`; start with 92565). The ingest workers
   never read it, so no restart is needed.
2. Add a rule `ar_wrong_company_pdf` to `substrate_hygiene.QUARANTINE_RULES`: `table_name='ar_facts'`,
   `key_expr='doc_id'`, selecting from `ar_doc_identity WHERE verdict='wrong_company'`.
   - `apply()` runs on equity_intelligence.db, so it needs `ATTACH ar_facts.db` read-only.
   - Or materialise the doc_ids from the table in a small step of its own.
3. Every reader of ar_facts (ar_yoy, dossiers, the substrate promotion) filters with
   `quarantined_keys(conn, 'ar_facts')` before use. Rows stay in place, and the quarantine is re-materialised
   idempotently.
4. Report `listed_only` and `unknown` counts next to answers as degradation (rule 13). Do not quarantine them.

**Re-fetch:** Venus is fixable. BSE lists a second FY2026 file uploaded 11 minutes after the wrong one, which looks like
the company's corrected upload, and we never downloaded it:
`https://www.bseindia.com/xml-data/corpfiling/AttachHis/29971821-bfab-4659-a9d8-7cf5dc170d02.pdf`.
- The same pattern is general: in **104 scrip-years** BSE's latest listed AR file was never fetched. Re-fetching those
  is cheap and may hold more corrections.
- The LADIAMO files cannot be settled from our data.

**Found on the way (not fixed):**
- **ISINs:** 1,826 `ar_docs` rows (373 symbols) carry a synthetic `INE_AUTO_*` ISIN although master_companies has the
  real one for the symbol (e.g. SIGMAADV -> INE933B01012). Rule 13 quarantines INE_AUTO rows, so these real facts would
  be dropped. Re-key them to the real ISIN.
- **Debt scrips:** about 119 reports belong to debt-instrument scrips (NCD/bond symbols), not equities.
- **PDF portfolio:** DALBHARAT 23830 has the real report as an embedded file, so it read 0 facts.


## Wrong-company hand check (225 candidates, 2026-10-16)
- Result: 0 new wrong-company PDFs. Only VENUSREM 92565 stays wrong (already quarantined).
- Counts: 119 debt_instrument (parent handles), 80 ok, 15 renamed, plus 20 earlier hand checks (11 same-company, 8 incl. LADIAMO/Turner = ok per parent, 1 wrong).
- Method: PyMuPDF text for scrip code/ISIN/CIN/name; RapidOCR on pages 1-3 for the 9 blank or scanned PDFs (COMPUPN, SIDDHA, ESHAMEDIA, ARTEFACT, RICHAIND, HANMAN, SSPNFIN, SAILANI, BAMPSL). All matched their company.
- Renames confirmed (same CIN or BSE scrip): MIIL=Naysaa Securities, BYLD=TRC Financial Services, WARDHEALTH=Ayoki Merchantile, CUPIDALBV=Cupid Trades and Finance, EDVENSWA=KLK Electrical, KARANWO=Manor Estates, SPARKLEGR=Sree Jayalakshmi Autospin, CHALLANI=Indo Asia Finance, ESHAMEDIA=Laser Dot, HANMAN=Powerhouse Gym, NIVAKA=B.T. Syndicate, THYROCARE.
- ar_doc_identity now has 106 ok + 1 wrong_company rows; substrate_hygiene.apply run. The CSV carries the hand_check column (data, not committed).
