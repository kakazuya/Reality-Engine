# Hand-off between loop sessions (each loop overwrites "Current state" and "Next", appends "Learnings")

## Current state (loop 3, 4 Nov 2026 18:20 IST)
- Baseline on a copy, `pilot10\scratch\l3_base.db`: A1 dev 651/898 = 72% (`pilot10\scores\a1_loop03_base.json`). `pilot10.db` itself is untouched and stale: promote only through the wrapper.
- Running: DeepSeek workers f826eabb (comparatives, T-057, `dsh/20261104T124718Z-f826eabb`) and 2e947e47 (KPI lexicons, `dsh/20261104T124734Z-2e947e47`).
- Brief ready, not started: `loops/loop_03_worker_speech.md` (speakers for ETERNAL, INFY, KEC; guidance precision).
- 865 pages need OCR: `pilot10\logs\needs_ocr_pages.csv`. Not run.

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
Loop 3 continues: review both workers, then start the speech worker. See `loops/loop_03_report.md`.

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
- Wrapper 13:15 IST: done before loop 2 restart: `docs_collect --profile` 512 s rc 0 (pages.db), `build_truth_snapshot` 1,249 s rc 0 -> `reality_engine/data/snapshots/truth_2026-11-04.duckdb`. Do not rerun either; continue with the build parts.
- 4 Nov loop 2: `results_xbrl.db.facts` drops XBRL dimensions (segments, expense details); anything per-member must be read from the raw XML in `raw_market\nse_results_xbrl`.
- 4 Nov loop 2: `--part stores|registry|pages --symbols X` runs `schema.create`, which drops the table for every company. Those parts must run on all 10 (under 4 minutes together); only kpi, transcripts and guidance are per company.
- 4 Nov loop 2: a raw document can be added without code: append a manifest row with `local_path`, `bucket`, `dissem_ts`, then `docs_collect --symbols X`.
- Wrapper 14:00 IST: loop 2 stopped at the Claude 5-hour limit (resets 17:40 IST), peak context 299k. Ready to merge: Eagle-sonnet-l2segments (ACCEPT). Sonnet workers l2structured and l2kpi share the same limit and stop with it; check `sonnet_worker.py status <name>` before restarting. Restart loop 2 after the reset: `powershell -NoProfile -ExecutionPolicy Bypass -File tasks/night_loop/start_loop.ps1 2`.
- Wrapper 18:40 IST: the 13:54 stop came from 5 parallel Claude sessions on one account: Sonnet workers 58% of usage, the loop manager 23%, an open wrapper near 400k context 16%. `run_loop.py` and `sonnet_worker.py` now load only the MCP servers they need and no skills, which moved startup context only from about 48k to 44.8k. Shivam rejected a 150k context cap.
- Wrapper 18:40 IST (Shivam): results tables print QoQ and YoY columns; XBRL does not. Check `doc_page` before calling a quarter missing. TTM = last full year + current year-to-date - prior year-to-date, from one filing.
- Loop 3: results tables must be read from PDF word boxes (`page.get_text('words')`, sort by y-centre, 3.5 pt rows), not `doc_page.text`, which scatters labels and columns on most layouts. Script `pilot10\scratch\l3\geo.py`.
- Loop 3: `start_worker` `writes` wants bare db file names (`w_cmp.db`), not paths. `job_watch wait --help` does not print help: it starts waiting.
- Loop 3: A1 counts wrong guidance rows as answered: about 58 of 136 rows were wrong on a hand read. Read rows, not only the score.
