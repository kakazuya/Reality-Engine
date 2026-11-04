# Hand-off between loop sessions (each loop overwrites "Current state" and "Next", appends "Learnings")

## Current state (loop 1, 4 Nov 2026 04:45 IST by this machine's clock; full detail `loops/loop_01_report.md`)
- Phase 1 sets written: `questions/<SYMBOL>.jsonl`, 1,305 questions over 10 companies, generator `questions/gen/build.py`.
  `qset check` Q1-Q3 passes on the fix branch. Q5 and Shivam's approval are open.
- Library inputs unchanged except `questions/sector_vocab.json` (stored table names added; needs the wrapper's OK).
  Bank diff: `questions/BANK_DIFF_2026-11-04.xlsx`.
- Raw: `D:\RealityEngine\pilot10\raw\`, 873 of about 1,160 at wrap-up, 279 announcements pending. Resume, safe to repeat:
  from the repo root with `PYTHONPATH` = repo and `REALITY_DATA_ROOT` = `reality_engine\data`, run
  `python D:\RealityEngine\pilot10\runners\run_fetch.py --fetch`; table: `python D:\RealityEngine\pilot10\runners\coverage.py`.
- `tasks/night_loop/pilot10_profile.json`: the 10 companies, paths, `window_start`, lender flags.
- Stores: XBRL Q2 FY27 held for 9 of 10 (Hindalco has not filed). Sep 2026 shareholding missing for HINDUNILVR, INFY,
  MARUTI, HINDALCO. Prices and deals end 23 Oct, truth snapshot 19 Oct.
- Workers: `20261103T225130Z-b1c96638` REJECT, do not merge (built a second `night_eval`, no pilot3 change).
  `20261103T231018Z-fa830b2b` (`qset` fixes) reviewed: ACCEPT, ready to merge.
- Wrapper note 06:00 IST (Shivam): in DeepSeek peak hours use a Sonnet 5.5 medium worker instead of waiting:
  `python tasks/night_loop/sonnet_worker.py start <name> <brief.md>` / `wait <name>` (see LOOP_BRIEF.md).
- Wrapper note 06:20 IST: T-055 merged to main (c17b5a4): `python -m reality_engine.night_eval.qset check
  tasks/night_loop/questions` runs from the main checkout; README `reality_engine/night_eval/README.md`.

## Wrapper between loops 1 and 2 (05:00 IST)
- Merged the qset fix worker (030725d): `qset check` on all 10 files: 1,305 questions, Q1 0 violations, Q2 every company
  11 lenses, orders about 46/42/12%, Q3 0 short variations, 0 duplicates. Wrapper hand-read 24 random: 23 fine, one
  typo fixed (Eternal "of NOV" -> "as a share of GOV").
- **Split and frozen (9b5de23):** use only `tasks/night_loop/questions/dev.jsonl` (898 questions). The 407 hidden ones
  and the full company files moved to `D:\RealityEngine\pilot10\eval_hidden\`: never read them, never `git show` the
  old company files from history (audited). `qset check` expects per-company files; for the dev set use
  `answerable.py --qset tasks/night_loop/questions/dev.jsonl`.
- Rulings on loop 1's four questions (wrapper, by Shivam's "decide, don't ask"): (1) "orders" questions stay only for
  companies that report orders or deals (EPC order book, IT deal TCV); elsewhere they are reworded or dropped later;
  (2) the no-rating template stays: "no rated instrument found" is a valid answer only with the search shown;
  (3) the vocabulary extension with stored table names is accepted; (4) 120-136 per company is fine.
- Rejected worker b1c96638 removed. **Generalisation running:** dsh `20261103T232215Z-375ffabf` (T-056, brief
  `loops/loop_01_worker_generalise.md`), started 04:52 IST on DeepSeek; it is loop 2's first worker slot.

## Next
Loop 2 (see `loops/loop_02_brief.md`): review the generalisation worker, build pilot10.db from its branch, baseline
A1 on the dev set, close the store gaps, and brief the first gap fixes.

## Learnings (append one line each; newest last)
- 3-4 Nov: full rebuilds (8 min) were the slow loop; per-company parts and fixed check pages are the fast loop.
- 3-4 Nov: workers spent 30-50 calls rediscovering facts when briefs lacked evidence; with evidence, 8-15.
- 4 Nov: hand-read grade of 185 pilot3 answers: 154 right, 30 partly, 1 wrong; the misses were guidance rows,
  period labels a quarter off, and numbers only in deck tables or annual-report prose.
- 4 Nov: `fetch_pilot60_history` fetches any universe and window unchanged: a 10-line runner repoints ROOT, the manifest
  and the cache (`pilot10\runners\run_fetch.py`). Rate seen about 30 documents a minute, many hard-linked from held stores.
- 4 Nov: NSE `integrated-filing-results?index=equities&symbol=<S>` returns one company's XBRL list; the unfiltered index
  returns only about the last 1,000 rows.
- 4 Nov: a worker started with an existing ticket built that ticket's old task instead of the brief. Give new work its own ticket, and read the branch's file list before believing a report.
- 4 Nov: `.tmp` is under a permission deny rule for this session; helper scripts go to `D:\RealityEngine\pilot10\scratch`.
- 4 Nov: page dumps of decks burn context fast; loop 1 reached 400k before its work ended. Search for terms and print short hits instead.
- 4 Nov 04:50 IST, supersedes the raw figures above: fetch finished, 1,149 ok, 2 errors, 11 no attachment, 2 pending; table `D:\RealityEngine\pilot10\logs\coverage_final.txt`.
- Wrapper 05:10 IST: loop 2 was killed at 05:03 by Claude Code's low-memory reaper about 8 minutes in (its transcript ends at 261 lines); nothing to resume from it. Restart only on Shivam's word: `python tasks/night_loop/run_loop.py 2`. The generalisation worker 375ffabf kept running.
- Wrapper 05:25 IST: T-056 generalisation merged (2b152da): `--profile tasks/night_loop/pilot10_profile.json` on docs_collect and build; build from main now, not a worktree. MARUTI test build: 147 docs, 1,170 pages, stores 15 s, kpi 12 s. Accept 3 of its brief was missing `--part pages` (guidance needs doc_page). Finding: MARUTI's five fetched "concall transcripts" are 1-page cover letters, so transcripts/guidance are empty: the real transcripts must be fetched (company website or the attachment behind the cover letter). Loop 2 partial work (old ISINs on shareholding filings, store gaps fetched) is committed (d19b756); `build_truth_snapshot` is heavy: run it alone, check RAM first.
- Wrapper 13:00 IST: loop 2 restart was reaped again for low memory (Opera ~4 GB + `build_truth_snapshot` ~1 GB+). The snapshot run the loop started (`pilot10/scratch/run_timed.sh snapshot`) was left to finish; do not start it again. Loops now start detached (`tasks/night_loop/start_loop.ps1 NN`). Never run two heavy jobs at once; check free RAM first.
