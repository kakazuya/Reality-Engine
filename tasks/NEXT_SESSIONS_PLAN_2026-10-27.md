# Next sessions plan (written 2026-10-27 evening, for new Claude Code CLI sessions)

Read this first in every new session. Then read `tasks/FRAMEWORK.md` (the authority), `AGENTS.md` and the memory index.
Each block below is **one session**: give a fresh CLI session the block's title plus "read tasks/NEXT_SESSIONS_PLAN_2026-10-27.md, do session S<n>".

## Standing rules (apply to every session)
1. **CORE RULE: checklist before full runs.**
   - No full chunking, tagging, embedding or loading of any dataset until the DB schema is ready **and** the dataset's pilot passes the shared checklist script.
   - The checklist covers:
     - required tags with fill rates;
     - point-in-time rules: `known_at` comes from the filing record, nothing is dated after its filing, and the symbol is the one in use at that time;
     - search: indexes plus timed templated queries;
     - hand-checked tag precision;
     - the question bank.
   - Raw fetches of originals may continue.
   - Spec: `tasks/QUERY_TEMPLATES_2026-10-27.md` (11 families, variations, §5 = Shivam's 30 questions).
2. **Claude manages and reviews; DeepSeek workers (dsh-worker MCP) do the work.**
   - DeepSeek runs at max effort.
   - Peak is Mon–Fri 06:30–09:30 and 11:30–15:30 IST. During peak, start no worker and renew no lease past the start of peak.
   - Leases are at most 2 h, so renew them hourly.
3. **Scope:** company data from FY2024-25 (known_at ≥ 2024-04-01, BSE dissemination date); macro and government data, all of it held; prices, flows and insider data from 2019.
4. **Storage and safety:**
   - Raw data goes on `D:\RealityEngine`. Read live DBs with `connect_ro`.
   - Never delete permanently; use the Recycle Bin.
   - No push without Shivam's go-ahead.
   - No paid spend (DeepInfra, paid models) without his OK.
   - Telegram and Drive research content stays out of GitHub.

## State at hand-off (2026-10-27 ~19:30 IST)

| Item | State | Where |
|---|---|---|
| Results notes fetch (FY25+, newest to oldest, gate per quarter, PDFs to Drive) | Q2FY27 → Q1FY26 done and passed; Q4FY25 running; Q3FY25, Q2FY25, Q1FY25 and Q4FY24 left (ETA ~01:00–01:30 28 Oct) | `reality_engine/scripts/results_notes.py` (parser `notes-v2`), `reality_engine/data/results_notes.db`; logs `D:\RealityEngine\raw\results_notes_run.log`; restart with `python -m reality_engine.scripts.results_notes all --workers 8 --start <next quarter end>` (resumes, skipping docs already done) |
| Re-parse of old quarters with notes-v2 | **done** (22:39): Q2FY27, Q1FY27, Q4FY26, Q3FY26 all re-parsed and gates passed; PDFs back on Drive. Q4FY25 fetched under notes-v2 and passed (notes_company 0.843); Q3FY25 fetch at 1,900/3,898 at 52/min | `reparse --quarter <q>`; log `D:\RealityEngine\raw\results_notes_reparse.log`; DB backup `D:\RealityEngine\backups\results_notes.db.bak-20261027-prev2` |
| 300-question bank | worker `20261027T130242Z-84259659` writing it (draft has 300 rows) | worktree `C:\Users\warri\Downloads\IDM-worktrees\20261027T130242Z-84259659\tasks\QUESTION_BANK_300_2026-10-27.{md,jsonl}` |
| Backward requirements audit | done and reviewed (3 numbers spot-checked against the DB) | `tasks/BACKWARD_REQUIREMENTS_AUDIT_2026-10-27_REPORT.md`, scripts in `tasks/audit_2026-10-27/` |
| Concall re-fetch pilot | done: 200/200 OK, 91% real transcripts, ~8.2–8.5k unique FY25+ to fetch (6–8 h at ≤25/min) | worktree `IDM-worktrees/20261027T002757Z-52ef59af` (`concall_refetch.py`, `tasks/concall_refetch/report_pilot.md`); PDFs `D:\RealityEngine\raw\concall_pdfs\` |
| Video OCR pilot | done: 30/30 labels correct by hand; full run ≈35–40 h CPU | worktree `IDM-worktrees/20261027T002613Z-06cac05a` (`video_screen_ocr.py`, `.tmp/LABEL_AUDIT.md`) |
| Raw originals inventory | done | worktree `IDM-worktrees/20261027T002828Z-095da489/tasks/RAW_ORIGINALS_INVENTORY_2026-10-27_REPORT.md` |

Known small items:
- 1 Q2FY27 PDF is blocked by Drive as "abusive"; refetch it from BSE.
- Q2FY27's PDFs are still on D (copy-back flag bug, fixed in `585ce48`); move them to Drive.
- 13 notes carry quarter labels from 2021 or 2023 (`detect_quarter` picks up old dates printed in notes).
- `auditor_report` sections sometimes capture cover-letter text.
- The band under the CLI prompt shows the 3 lost jobs from 26 Oct as "stalled". That's a dsh-workers plugin display bug; ignore it.

## Shivam's rulings on the audit §11 decisions (2026-10-27, these replace the suggestions below)
1. **Timing rule (the 3:30 cutoff plus 4 days).**
   - A filing disseminated **before 15:30 IST** on session T has day 0 = T.
   - A filing **at or after 15:30** has day 0 = the next session (T+1). That is the one-day gap.
   - Information is treated as gradually reaching the public over a **4-session window** tied to day 0.
   - The document's text still becomes usable only at its `known_at`; the window is for attributing price moves, never for using text early.
   - (Claude's reading; confirm the exact direction of the window with Shivam if the build needs it.)
2. **Storage:** as suggested. Daily rows for close and price band; valid_from/valid_to ranges for shares outstanding and the market-cap bucket.
3. **Partly-paid, DVR and ETF lines:** as suggested. Their own state rows, linked to the parent, excluded from market-cap ranks and buckets.
4. **The 1,665 missing ISINs:** rebuild the master from `security_master`, flagging delisted names. Nothing is dropped out of scope.
5. **Price bands:** OPEN. Shivam asked what price bands are; they were explained as the exchange's daily circuit limits. Awaiting his call.
6. **Index history:** fetch back to 2019 if the fetch takes under 3 hours; otherwise from FY2024-25 only. Time a pilot first.
7. **Opinion dates:**
   - Pull the video links from Telegram posts and read each video's publish date from its metadata (yt-dlp, no download).
   - Use those dates to back-date where a document first appeared, where that's possible.
   - Elsewhere, folder dates at confidence ≤ 0.5; claims below 0.6 are shown but not graded.
8. **Sector classification:** OPEN. First, a pilot on about 200 small caps comparing the NSE and BSE industry labels against what each company actually does (AR business description and segments). The decision follows the pilot.

## Decisions waiting on Shivam (from audit §11; Claude's suggested answers, superseded by the rulings above)
1. When a filing counts: it counts for the **next** session, so a filing at 19:50 doesn't change that day's market cap.
2. Company-state storage: daily rows for close and band; change-date intervals for shares and market-cap bucket.
3. Partly-paid, DVR and ETF lines: their own state rows, excluded from market-cap ranks.
4. The 1,665 missing FY25+ ISINs: rebuild the master from `security_master` (8,434 rows), flagging delisted names.
5. Price bands: backfill to 2019.
6. Index history: from 2019.
7. Opinion dates: folder dates allowed at low confidence; claims below 0.6 confidence are reported but not graded.
8. BSE industry classification: stored as a separate classification, never mixed into NSE's sectors.

Also waiting:
- **Approval of the 300-question bank.** It becomes the pass/fail threshold only once approved.
- **Concall candidate list:** BSE "Earnings Call Transcript" only, or widened to about 1,800 "Analyst / Investor Meet" calls plus about 1,500 NSE-only companies.
- **Push approval:** many local commits since `35c40ff`.

## Sessions, in dependency order
Gap IDs (G0–G12) are from audit §10. A session ends when its acceptance checks pass and Claude has reviewed the worker's result.

### S1 — Review and approve the 300-question bank (Shivam + Claude, no worker)
- Run the bank's test command.
- Hand-check 20 random rows: entities resolve, each variation slot follows its rule, coverage values are right. Fix or flag problems.
- Show Shivam the `.md` file; record his approval or edits.
- Merge the bank into `tasks/`.
- Output: the approved bank = the checklist's pass/fail threshold.

### S2 — G0: rebuild the ISIN anchor (worker, no fetch, ~2 days)
- Build `security(isin, valid_from, valid_to, source, confidence)`:
  - from BSE scrip-code windows, `px_daily.entity_id` and `corporate_actions`;
  - validate check digits;
  - remove the 83 false 2021-10-27 changes;
  - repair the stale `shp_index.isin` values;
  - quarantine the 1,370 `INE_AUTO*` ISINs;
  - decide the 1,665 missing ISINs (decision 4).
- Acceptance: the 10 real ISIN-change cases from audit §3.3 join across the change; 0 false changes; tests.
- Blocks everything below.

### S3 — G4 sector/industry history + G11 XBRL concept maps (worker, ~1.5 days; small BSE fetch)
- Repair the 1,556 placeholders from `company_industry`.
- Fetch BSE's scrip-master industry for the rest and store it as a separate tree (decision 8).
- Store everything as `valid_from` intervals.
- G11: concept and context maps for Ind AS, banking, NBFC and insurance taxonomies. Validate against AR totals; the MGL case is off by 9.5%.

### S4 — G1 shares outstanding + `company_state_daily` (worker, ~2 days; after S2)
- Build shares outstanding from XBRL paid-up capital ÷ face value, stepped by `adj_factor_cum`.
- Market cap and bucket as of each date (SEBI-style ranks), using decisions 1–3.
- Tests that nothing can see future data, plus spot checks on known dates.

### S5 — G8 price bands, G3 F&O history, G2 index history (worker, fetches; can run alongside S4)
- NSE bhavcopy/surveillance price-band fields for 2022-02 → 2026-09 (decision 5).
- Monthly F&O lists.
- Index-change notices from 2019 (decision 6) into `company_membership_pit`.
- Fetch politely, raw files to D.

### S6 — G5 theme map (worker, ~1 day)
- Curated `theme_map` built from basic industry plus keywords. It must cover the themes your 30 questions need: gold stocks, HFCs, dairy, defence, rail, EMS, data centres.

### S7 — Build the checklist script (worker; after S1–S6)
- A single command that scores any dataset:
  - tags and fill rates per doc type;
  - point-in-time checks;
  - index and FTS presence;
  - the approved 300 + 30 questions, with time limits per family;
  - precision on the hand-checked sample.
- Output a scorecard with failing instances listed.

### S8 — G6 v3 re-chunk pilot with full layer-1 tags (worker; needs originals)
- Chunker v3 plus the deterministic tagger on a pilot per doc type: results notes, concalls (after S9 fetch), decks, ARs, PIB.
- 300-chunk hand check, with precision ≥ 0.90.
- Run the pilot through S7.
- The full run happens only after it passes (core rule).

### S9 — Raw fetches that may run any time off-peak (keep total BSE load under 76 requests/min)
- **Concalls:** `python -m reality_engine.scripts.concall_refetch --n 9390 --report tasks/concall_refetch/report_full.md` from the concall worktree, ≤25 requests/min. Settle the candidate-list scope first.
- **From the inventory report:** 1,417 missing decks (re-run the harvester first; 979 are from 2026), 1,794 ARs, 108 RBI documents, and the filtered material announcements (~8,540).
- **NSE-only companies (322):** need an NSE announcement source.

### S10 — G10 macro-link reader, G7 opinions DB pilot, G12 macro series (later)
- G10: macro-link reader over PIB, budgets and RBI with a fixed vocabulary.
- G7: opinions pilot (10 videos, 10 reports, 200 Telegram posts). Video OCR is ready, but the full run waits for S7. ASR is a paid endpoint and needs Shivam's OK.
- G12: measure the end dates of the commodity, tariff and FX series.

### S11 — Re-embed (paid, needs Shivam's OK)
- Only after S7 and S8 pass, so the embeddings carry the final headers.
