# STATE for any AI picking this up — 29 Oct 2026, 12:30 IST (written by Eagle/Claude before a weekly-quota throttle)

Read in this order:
1. `AGENTS.md`: the GOLDEN RULE (the order of work).
2. This file.
3. `tasks/HANDOFF_2026-10-29.md` §8–10: the detailed log of the night.
4. `D:\RealityEngine\plans\DECISION_LOG.md`: the last 40 lines.

## 1. Where we are on the golden rule
| step | status |
|---|---|
| 1. Raw data | DONE (fetches may continue) |
| 2. Master bank (1,073 cases) | APPROVED; 8 period fixes applied 29 Oct (`2ea66b1`, see `tasks/master_bank/BANK_DEFECTS_2026-10-29.md` §4) |
| 3. Schema (DB design) | **DONE**: `tasks/SCHEMA_FINAL_2026-10-29.md` + `.sql` (149 tables, runs clean) + `tasks/SCHEMA_FINAL_CASES_2026-10-29.jsonl` (per-case class a/b/c + tables). After the b-tables build: **a 694 / b 370 / c 9** (`tasks/pilot_b/cases_pilot_b.jsonl`) |
| 4. Pilot | built (stores below) |
| 5. Gate ≥95% | **NOT met. Honest strict score = 27/2,681 (1.0%)** with the hardened grader (precision on ANSWERED 19/20) |
| 6. Full chunking/embedding | FORBIDDEN until step 5 passes |

## 2. Gate history (2,681 cases = 1,073 originals + 1,608 pilot-60 instances)
- Old grader: 2.1% → 3.6% (period fix) → 5.1% (ask v1, extraction, uncapped chunks) → 6.5% (EVENT/RIPPLE fix).
- Hardened grader (every asked part must be present; unrelated rows penalised; a judgement ask needs its metric): **1.0%**. This is the true number.
- What's left among the not-answered:
  - PARTIAL 2,271 (of those, 1,771 fail `ask_match`: the concept is not in the rows);
  - BLOCKED_SCHEMA 195;
  - NOT_IN_DATA 132;
  - BLOCKED_TOOL 56.

## 3. Root cause and next plan: v4 query design (Shivam agreed the direction)
The planner patches plateaued. Four design gaps:
1. **No CONCEPT REGISTRY.** There is no single map concept → table.field → planner. Shivam asked for this from day one; it was overlooked. Generate it from `tasks/SCHEMA_FINAL_CASES_2026-10-29.jsonl` (the tables listed per case) + `tasks/SCHEMA_FINAL_2026-10-29.sql` (fields) + `facts_pilot.xbrl_concept_map`.
2. **No ASK CONTRACT.** The question must be decomposed into typed parts, each of which must be answered (e.g. "promoter AND public", "NSE AND BSE plus the combined total", "raw AND adjusted").
3. **The router uses master-bank metadata** (`template`/`family`), which real user questions won't have. The decomposer must work from the QUESTION TEXT ONLY; bank fields are for grading only.
4. **No ANSWER CONTRACT.** Each part must be printed with its value, period and source, or NOT IN DATA with a reason.

The brief to run: `tasks/dsh_tasks/V4_QUERY_DESIGN_2026-10-29.md` (a design doc; one worker; a reviewer checks it). Then 3–4 build workers with disjoint file scopes, then one full gate run.

Rough cost: ~1–1.3 M output tokens in total. The limits are laptop RAM (~5 workers) and the DeepSeek peak windows, not quota.

## 4. Running right now (dsh workers, DeepSeek V4.1 Flash, Go account 2)
| job | task | worktree branch |
|---|---|---|
| `20261029T040413Z-5d203544` | ask round 2B: market/holding/narrative concepts | `dsh/20261029T040413Z-5d203544` |
| `20261029T053108Z-34562ae1` | RIPPLE round 2: sector store `sector_pit.db`, state/commodity/theme targets, Hinglish triggers | `dsh/20261029T053108Z-34562ae1` |

Both leases run to 14:01 IST. `renew_worker_lease(job_id, 7200)` keeps them alive; if a lease isn't renewed the worker stops.

Merge recipe:
- `git merge --no-ff --no-commit dsh/<id>`;
- for conflicts in `tasks/answer_bench/GATE_RESULTS_*` and `tasks/pilot60/RESULTS_HAND60*`, keep main's copy (`git checkout --ours`);
- `git rm --cached PROGRESS_NOTES.md`;
- run `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"`;
- commit with `By: Eagle`.

RIPPLE2 builds `.tmp/sector_pit.db` in its worktree. Copy it to `reality_engine/data/pilot/pilot60/sector_pit.db`.

After both merge, run the full gate on main **detached**: `python .tmp/run_gate_full.py` (it runs bank in 100-case chunks, then hand60, grade and report, ~2 h, all local CPU). Read the result from `tasks/answer_bench/GATE_RUN_2026-10-29.md` and `GATE_RESULTS_*_strict.jsonl`.

## 5. Data stores (all query DBs on the C: SSD; never read DBs from D:, which is an HDD)
`reality_engine/data/pilot/` (gitignored):
- `pilot60/chunks_v3_pilot.db`: 2,488 docs / 108 k chunks, uncapped, with 74 results notes; the capped one is kept as `chunks_v3_pilot_capped.db`.
- `pilot60/market_state_pilot.db`: T1 store; `company_sector_pit` is EMPTY here (the HDD copy `D:\RealityEngine\pilot\market_state_pilot.db` has 449 rows).
- `pilot60/facts_pilot.db`: `company_metric_series` 1.06 M, `company_segment_pnl`, `xbrl_concept_map`.
- `pilot60/extract_pilot60.db`: 11 extraction tables, 577 rows.
- `pilot60/market_state_b.db`: F&O OI 16.2 M, commodity 7 k, index membership 10.9 k, bhavcopy 4.29 M.
- `pilot60/results_notes_chunks.db`, `results_notes.db`, `macro_all.db` (21,552 claims → 44,742 targets).

Live stores are in `reality_engine/data/*.db`. The 5 speed indexes are built.

Backup of the irreplaceable core is on Drive: `gdrive:InfoDiffusion_archive/db_backups/2026-10-29_core` (zstd, sha256 in its MANIFEST.json); the script is `D:\RealityEngine\backups\backup_core.py`.

## 6. Pipeline execution issues and lessons (do not repeat them)
1. **Never read a DB from the D: HDD.** Random reads pin it at 100% busy. Twice tonight: the integrity check and the bench reading the pilot DBs.
2. **Never build or write a DB on the HDD.** The backup build thrashed D: until it was staged on the SSD. Only sequential writes of finished files go to D:.
3. **Background jobs get killed by Claude Code's memory guard** unless Claude is started with `CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1`. Run long jobs detached with PowerShell `Start-Process -WindowStyle Hidden`, never as a Claude background shell. A Monitor expiring after 30 min also kills processes it started.
4. **RAM:** 16 GB laptop. About 5 dsh workers fit after the reality-data fix (`ac2901e`: search index mmap-shared, preload opt-in). The bench runner peaks at ~1.8 GB. Run local CPU jobs under `.tmp/ram_guard.ps1`, which pauses and never kills.
5. **Peak windows (no new dsh starts):** Mon–Fri 06:30–09:30 and 11:30–15:30 IST. Running workers continue.
6. **Driver stop condition bug:** "100 in this chunk" contains the text "0 in this chunk", so match the whole phrase `already done, 0 in this chunk` (fixed in `.tmp/run_gate_full.py`).
7. **Worker class-(b) promotion was coverage-based, not ask-based.** Hand-check the precision of every "answered" increase. ALWAYS hand-check 10+ rows before believing a gate number.
8. **The watchdog** (`reality_engine/scripts/resource_watchdog.py`, `d11e562`) now reports per-disk busy %, GPU and RAM %, and runs hidden. Read it with `python -m reality_engine.scripts.resource_watchdog --report`.

## 7. Test fixtures / commands
- Query tests: `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` (138 OK at `987d70f`).
- Pilot tests: `python -m unittest reality_engine.tests.test_pilot60 reality_engine.tests.test_pilot_t1 reality_engine.tests.test_pilot_b_tables reality_engine.tests.test_extraction_pilot60 reality_engine.tests.test_macro_claim_target`.
- Series fetchers: `python -m unittest reality_engine.tests.test_extra_series reality_engine.tests.test_missing_series_fetchers` (fixtures in `reality_engine/tests/fixtures/extra_series/`).
- Gate runner: `tasks/pilot60/gate_run.py {hand60|bank --resume --chunk 100|grade|sample40|report}`. The strict grader is `tasks/answer_bench/grade_v1.py`, and the gate checks are in `reality_engine/query/gate.py`.
- Hand-check calibration set: `tasks/pilot60/HAND_CHECK_60.json` and `GATE_SAMPLE40_verdicts*.json`.

## 8. Decisions waiting for Shivam
- SCHEMA_FINAL §6:
  - the embedding dimension;
  - approve the 211-case fetch stream (the 95% gate needs it);
  - whether to merge `market_state` and `metric_state`.
- Keep iterating toward 95% via v4, or re-scope the gate.
- Push: main is many commits ahead of origin, NOT pushed; a push needs Shivam's OK.
