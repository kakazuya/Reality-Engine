# Full ledger of `tasks/TASKS.md` (never trimmed)

`tasks/TASKS.md` is the short copy every session loads; it is condensed to fit its size cap. This file keeps every line ever added (`+`) or removed (`-`) there, with date, branch and author, oldest first (Shivam, 26 Nov 2026). Earlier full wording of the rulings: `docs/rulings/RULINGS_full_2026-11-08.md`.

## 2026-11-02T00:12:30+05:30 | kakazuya (Wolf) | 7c8e3ffe Goal: Build a small ticket tracker that every session sees cheaply and that commits and worker start
```diff
+# Tickets
+One row per line, kept in its section: `- T-014 | DOING Wolf | P1 | title | accept: <command or Shivam> | from: <source> | opened 2026-11-01`
+Statuses: `OPEN`, `LOOKING`, `DOING <owner>`, `WAITING <who>`; priorities `P1`-`P3`. No `|` inside a field.
+Closed rows move to `tasks/TASKS_DONE.md`: `python -m reality_engine.scripts.task_board done T-014`.
+Card and full list: `python -m reality_engine.scripts.task_board card` / `list`.
+## Workspace
+## Data
+## OCR and extraction
+## Schema and question map
+## Bank
+## Research
+## Machines
```

## 2026-11-02T00:20:34+05:30 | kakazuya (Wolf) | 2597585a merge: dsh/20261101T181317Z-dd908113 ticket tracker and 400k wrap-up hook (reviewed)
```diff
+ # Tickets
+ One row per line, kept in its section: `- T-014 | DOING Wolf | P1 | title | accept: <command or Shivam> | from: <source> | opened 2026-11-01`
+ Statuses: `OPEN`, `LOOKING`, `DOING <owner>`, `WAITING <who>`; priorities `P1`-`P3`. No `|` inside a field.
+ Closed rows move to `tasks/TASKS_DONE.md`: `python -m reality_engine.scripts.task_board done T-014`.
+ Card and full list: `python -m reality_engine.scripts.task_board card` / `list`.
+ ## Workspace
++- T-001 | OPEN | P1 | Enforce worker tool-call budgets in code; a worker used 266+ against 120, and another 181 against 150 | accept: python -m pytest reality_engine/tests/test_worker_budget.py -q | from: STATE 1 Nov | opened 2026-11-02
++- T-002 | OPEN | P1 | Block by hook: git push, private folder reads, printed keys, --no-verify, gate edits, git stash, full suite on the MSI | accept: python -m pytest reality_engine/tests/test_enforcement_hooks.py -q | from: enforcement plan | opened 2026-11-02
++- T-003 | OPEN | P1 | Merge gate: tests, doc gate, accept check, Docs updated line, hidden evaluation, rulings diff (workspace step 3) | accept: python -m pytest reality_engine/tests/test_merge_gate.py -q | from: workspace plan step 3 | opened 2026-11-02
++- T-004 | OPEN | P1 | Final count and verdict on the 9 efficiency fixes, due the night of 1 Nov | accept: Shivam | from: tasks/efficiency/FIX_TRACKER_2026-10-31.md | opened 2026-11-02
++- T-005 | OPEN | P2 | Cap code workers at 2 and refuse new ones while a branch is over 24 hours old | accept: python -m pytest reality_engine/tests/test_worker_limits.py -q | from: enforcement plan | opened 2026-11-02
++- T-006 | OPEN | P2 | Find why the full test suite reaches 7.5 GB; run it on the HP, not the MSI | accept: Shivam | from: STATE 1 Nov | opened 2026-11-02
++- T-007 | OPEN | P2 | Fix test_commit_replays_the_identity, which fails when the launcher sets GIT_AUTHOR_NAME | accept: python -m pytest reality_engine/tests/test_dsh_worker_sandbox.py reality_engine/tests/test_dsh_worker_stress.py -k test_commit_replays -q | from: STATE 1 Nov | opened 2026-11-02
++- T-008 | OPEN | P2 | Versioned git hooks with an install command and a session start warning when they differ | accept: python -m pytest reality_engine/tests/test_hooks_installed.py -q | from: enforcement plan | opened 2026-11-02
++- T-009 | OPEN | P2 | SessionEnd hook runs the doc sweep; next session start prints any failure | accept: python -m pytest reality_engine/tests/test_session_end_sweep.py -q | from: enforcement plan | opened 2026-11-02
++- T-010 | OPEN | P2 | One model-call function with an allowlist: free models and DeepSeek only | accept: python -m pytest reality_engine/tests/test_model_allowlist.py -q | from: Shivam ruling 1 Nov | opened 2026-11-02
++- T-011 | OPEN | P3 | Remove AGENTS conflicts: FRAMEWORK first against read nothing else first; rule 1 says ISINs never change | accept: Shivam | from: enforcement plan | opened 2026-11-02
++- T-012 | WAITING Shivam | P2 | Quiz a fresh session on the rulings, to test tasks/RULINGS.md | accept: Shivam | from: STATE 1 Nov | opened 2026-11-02
+ ## Data
++- T-021 | LOOKING | P3 | Check if still open: PIB phase 2, Hindi, Urdu and regional offices | accept: Shivam | from: tasks/PIPELINE_TODO.md A2 | opened 2026-11-02
++- T-022 | LOOKING | P3 | Check if still open: policy register at scale, with stage threads and company mapping | accept: Shivam | from: tasks/PIPELINE_TODO.md A3 | opened 2026-11-02
++- T-023 | LOOKING | P3 | Check if finished: shareholding and pledge backfill, marked running on 19 Oct | accept: Shivam | from: tasks/PIPELINE_TODO.md B3 | opened 2026-11-02
++- T-024 | LOOKING | P3 | Check if still open: index membership history | accept: Shivam | from: tasks/PIPELINE_TODO.md Phase C | opened 2026-11-02
++- T-025 | LOOKING | P3 | Check if still open: parse value, customer and execution period from exchange order-win filings | accept: Shivam | from: tasks/PIPELINE_TODO.md Phase C | opened 2026-11-02
+ ## OCR and extraction
++- T-019 | WAITING Shivam | P1 | Approve Haiku on about 100 fresh OCR pages, batches of 8: tasks/ocr/OCR_ON_HP_FINDINGS_2026-11-01.md | accept: Shivam | from: STATE 1 Nov | opened 2026-11-02
++- T-020 | OPEN | P2 | OCR after workspace step 4: TextRecognizer first pass, stronger reader for low-confidence numbers; last accuracy pilot failed its gate | accept: Shivam | from: RULINGS, GATE_STATE | opened 2026-11-02
+ ## Schema and question map
++- T-014 | OPEN | P1 | Question map for the 3 prototype companies: every bank question naming them has a row (workspace step 4) | accept: python -m pytest reality_engine/tests/test_question_map.py -q | from: workspace plan step 4 | opened 2026-11-02
++- T-015 | WAITING Shivam | P1 | Decide blank as_of default, truth panel and reader kill: tasks/arch_v4/GATE_STATE_2026-11-01.md | accept: Shivam | from: STATE 1 Nov | opened 2026-11-02
++- T-016 | OPEN | P2 | Typed write contracts: unit, range, label, known_at; split fact.value; test metric_citations on the prototype | accept: python -m pytest reality_engine/tests/test_write_contracts.py -q | from: RULINGS agreed direction | opened 2026-11-02
++- T-017 | OPEN | P2 | Full-run guard: chunk, embed and load scripts refuse a full run with no pilot pass file | accept: python -m pytest reality_engine/tests/test_full_run_guard.py -q | from: enforcement plan | opened 2026-11-02
+ ## Bank
++- T-018 | OPEN | P2 | Refuse a bank rebuild that changes the frozen 1,901 questions or ruled rows, or names a non-pilot stock | accept: python -m pytest reality_engine/tests/test_bank_guard.py -q | from: enforcement plan | opened 2026-11-02
+ ## Research
++- T-026 | WAITING Shivam | P3 | Research library: delete OK for 256 duplicate copies (3.76 GB) and a bucket scheme; memory dated 27 Oct, recheck first | accept: Shivam | from: memory project_research_folder_import | opened 2026-11-02
++- T-027 | OPEN | P3 | Trading limits module the test harness cannot run without, when backtests resume | accept: python -m pytest reality_engine/tests/test_trading_limits.py -q | from: tasks/FRAMEWORK.md | opened 2026-11-02
+ ## Machines
++- T-013 | WAITING Shivam | P2 | Decide use of the Claude cloud credit that memory says expires 5 Nov; only Shivam can start that session | accept: Shivam | from: memory, not rechecked | opened 2026-11-02
```

## 2026-11-02T00:21:26+05:30 | kakazuya (Wolf) | 88619045 Open T-028 for the doc sweep findings
```diff
+- T-028 | OPEN | P2 | Clear the doc sweep: 26 references in old docs point at files that no longer exist | accept: python reality_engine/scripts/doc_gate.py --sweep | from: sweep 2 Nov | opened 2026-11-02
```

## 2026-11-02T01:02:58+05:30 | kakazuya (Wolf) | 708be5bf Reword T-013 and T-019 after Shivam's replies; open T-029 and T-030
```diff
-- T-019 | WAITING Shivam | P1 | Approve Haiku on about 100 fresh OCR pages, batches of 8: tasks/ocr/OCR_ON_HP_FINDINGS_2026-11-01.md | accept: Shivam | from: STATE 1 Nov | opened 2026-11-02
+- T-029 | OPEN | P3 | When OCR resumes after workspace step 4: decide a second Haiku baseline on about 100 fresh pages, batches of 8; first run: 100 pages, 995,856 tokens | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
-- T-013 | WAITING Shivam | P2 | Decide use of the Claude cloud credit that memory says expires 5 Nov; only Shivam can start that session | accept: Shivam | from: memory, not rechecked | opened 2026-11-02
+- T-030 | WAITING Shivam | P2 | Shivam uses the Claude cloud credit himself on the Eagle account, Tuesday 3 Nov | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
```

## 2026-11-02T01:42:04+05:30 | kakazuya (Wolf) | 22954e51 Close T-015 and T-026 on Shivam's rulings of 2 Nov
```diff
-- T-015 | WAITING Shivam | P1 | Decide blank as_of default, truth panel and reader kill: tasks/arch_v4/GATE_STATE_2026-11-01.md | accept: Shivam | from: STATE 1 Nov | opened 2026-11-02
+- T-032 | OPEN | P2 | Gate reports show only the hand-read score: tasks/pilot60/gate_run.py still prints the format score | accept: Shivam | from: Shivam ruling 2 Nov | opened 2026-11-02
-- T-026 | WAITING Shivam | P3 | Research library: delete OK for 256 duplicate copies (3.76 GB) and a bucket scheme; memory dated 27 Oct, recheck first | accept: Shivam | from: memory project_research_folder_import | opened 2026-11-02
+- T-031 | OPEN | P3 | Research library bucket scheme; duplicates deleted 2 Nov, list in _dupes_deleted_2026-11-02.csv | accept: Shivam | from: T-026 | opened 2026-11-02
```

## 2026-11-02T01:43:25+05:30 | kakazuya (Wolf) | e62ad87e Drop T-012: Shivam dropped the rulings quiz
```diff
-- T-012 | WAITING Shivam | P2 | Quiz a fresh session on the rulings, to test tasks/RULINGS.md | accept: Shivam | from: STATE 1 Nov | opened 2026-11-02
```

## 2026-11-02T01:51:22+05:30 | kakazuya (Wolf) | 7e07e144 Resume the pilot test on the 3 prototype companies, by Shivam's order of 2 Nov (T-035)
```diff
+- T-034 | DOING Wolf | P1 | Pilot: page text for the thin BAJFINANCE, HINDALCO and KEC documents, by HP TextRecognizer | accept: Shivam | from: PROTOTYPE3 grade change 2 | opened 2026-11-02
-- T-014 | OPEN | P1 | Question map for the 3 prototype companies: every bank question naming them has a row (workspace step 4) | accept: python -m pytest reality_engine/tests/test_question_map.py -q | from: workspace plan step 4 | opened 2026-11-02
-- T-016 | OPEN | P2 | Typed write contracts: unit, range, label, known_at; split fact.value; test metric_citations on the prototype | accept: python -m pytest reality_engine/tests/test_write_contracts.py -q | from: RULINGS agreed direction | opened 2026-11-02
+- T-014 | DOING Wolf | P1 | Question map for the 3 prototype companies: every bank question naming them has a row (workspace step 4) | accept: python -m pytest reality_engine/tests/test_question_map.py -q | from: workspace plan step 4 | opened 2026-11-02
+- T-016 | DOING Wolf | P2 | Typed write contracts: unit, range, label, known_at; split fact.value; test metric_citations on the prototype | accept: python -m pytest reality_engine/tests/test_write_contracts.py -q | from: RULINGS agreed direction | opened 2026-11-02
+- T-033 | DOING Wolf | P1 | Pilot: engine routes each measure to its store and refuses a nearby measure, on a 3-company fact store | accept: python -m pytest reality_engine/tests/test_proto3_engine.py -q | from: PROTOTYPE3 grade change 4 | opened 2026-11-02
+- T-035 | OPEN | P1 | Pilot: rerun extraction on the 3 companies, answer the same questions, grade by reading | accept: Shivam | from: PROTOTYPE3 grade change 5 | opened 2026-11-02
```

## 2026-11-02T01:57:30+05:30 | kakazuya (Wolf) | f11bc3db T-014 question map for the 3 prototype companies: 286 rows
```diff
-- T-014 | DOING Wolf | P1 | Question map for the 3 prototype companies: every bank question naming them has a row (workspace step 4) | accept: python -m pytest reality_engine/tests/test_question_map.py -q | from: workspace plan step 4 | opened 2026-11-02
```

## 2026-11-02T02:12:15+05:30 | kakazuya (Wolf) | cb9d43fe merge: dsh/20261101T202143Z-aaa5ff41 write contracts and whole-page reads (T-016, reviewed)
```diff
++- T-036 | OPEN | P2 | Split fact.value into numeric and text, and test metric_citations on the prototype | accept: Shivam | from: T-016 | opened 2026-11-02
```

## 2026-11-02T02:17:50+05:30 | kakazuya (Wolf) | d0480ffa T-034 wrap-up at 400k: next actions in STATE, HP and KEC helpers kept, tickets opened
```diff
+- T-037 | OPEN | P1 | Fetch KEC's call transcripts from kecrpg.com; its 10 filed concalls are cover letters | accept: Shivam | from: Pilot 2 Nov | opened 2026-11-02
+- T-038 | OPEN | P1 | Wire contract-passing extract rows into the fact view; answer narrative questions with retrieved quoted passages, no model | accept: Shivam | from: Pilot 2 Nov | opened 2026-11-02
+- T-039 | WAITING Shivam | P2 | Rule on 21 NOT IN DATA labels with inputs held: 12 grouped with peers, 9 single-company, 13 carry evidence | accept: Shivam | from: Question map 2 Nov | opened 2026-11-02
```

## 2026-11-02T02:52:18+05:30 | kakazuya (Wolf) | 0a2c34d9 merge: dsh/20261101T210210Z-521b20a9 extract rows reach the fact store, narrative questions get quot
```diff
++- T-041 | OPEN | P2 | All 74 results_notes docs in chunks_v3_pilot point at a deleted worktree; raw PDFs are gone. 3 pilot ones refetched to D but their hash differs from the stored one, so check pages and fix raw_path | accept: Shivam | from: T-040 2 Nov | opened 2026-11-02
++- T-040 | OPEN | P1 | Pilot: OCR every page of the 3 companies and mark each extracted number confirmed or disputed against the text layer | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
```

## 2026-11-02T03:22:37+05:30 | kakazuya (Wolf) | b7851afa merge: dsh/20261101T211651Z-042ff303 each extracted number marked confirmed, disputed or unchecked a
```diff
++- T-042 | OPEN | P1 | Rule and chain-of-command ledger: log every gate block, budget overrun, bypass and who did the work; daily report by rule of enforced, sidelined and unmeasured | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
```

## 2026-11-02T03:34:10+05:30 | kakazuya (Wolf) | 8052ce0e merge: dsh/20261101T215253Z-6f5a0601 rule and chain-of-command ledger (T-042, T-043, reviewed)
```diff
++- T-043 | OPEN | P1 | Worker review log: tool calls, thinking and output tokens, job type, time, and Claude's review of prompt, permissions and scope, for every dsh worker and Claude session | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
```

## 2026-11-02T04:13:39+05:30 | kakazuya (Wolf) | 570f01e1 T-045 first task for the new session: Claude reads every doc line by line
```diff
+- T-044 | OPEN | P1 | Catch finished, stalled and failed jobs in code, at any effort level: list_workers shows the newest and running first, and a status command feeds a hook on every prompt | accept: python -m pytest reality_engine/tests/test_job_watch.py -q | from: Shivam 2 Nov | opened 2026-11-02
+- T-045 | OPEN | P1 | Claude personally reads every doc line by line, deletes stale entries and corrects the rest to the current code; no worker or subagent reads for it | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
```

## 2026-11-02T04:25:20+05:30 | kakazuya (Wolf) | 7593ce87 T-045 arch_v4 read: 5 stale docs deleted, reports corrected, old queue replaced by a ticket
```diff
+- T-046 | OPEN | P2 | List the 10 documents the 31 Oct reader test found absent and check whether they exist at the source; moved from the old work queue | accept: Shivam | from: manual | opened 2026-11-02
```

## 2026-11-02T13:01:00+05:30 | kakazuya (Wolf) | 12965e99 T-047 session titles made a standing rule: row committed, never closed, ruling recorded
```diff
+- T-047 | OPEN | P3 | Session titles: keep the sv/neo prefix, let each session choose the rest | accept: A new session started by claude-neo or claude-sv with no task shows <prefix>-<title chosen by that session> | from: Shivam, 2 Nov | opened 2026-11-02
```

## 2026-11-02T13:14:46+05:30 | kakazuya (Wolf) | bd4a718c T-045 closed as done on Shivam's word, 2 Nov
```diff
-- T-045 | OPEN | P1 | Claude personally reads every doc line by line, deletes stale entries and corrects the rest to the current code; no worker or subagent reads for it | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
```

## 2026-11-02T14:32:24+05:30 | kakazuya (Wolf) | 2ecfa4b5 T-048 one-company gap loop: three-tier ruling recorded, DeepSeek brief to build the loop
```diff
+- T-048 | OPEN | P1 | One-company gap loop: 100 sector-fit questions for KEC, Haiku sessions under 100k fill gaps by extraction or computation in a sandbox, Opus manages; replicate to 3, then 60 | accept: Shivam | from: Shivam, 2 Nov | opened 2026-11-02
```

## 2026-11-03T02:35:02+05:30 | kakazuya (Wolf) | 1715a17d T-049 opened: script extraction into one database for the 3 pilot companies (Shivam, 3 Nov); ruling 
```diff
+- T-049 | OPEN | P1 | Script extraction for the 3 pilot companies: rule-based scripts (no LLM; AI OCR only for image pages within budget) read all raw documents of KEC, BAJFINANCE, HINDALCO into the schema of tasks/arch_v4/T048_FINDINGS_AND_SCHEMA_2026-11-03.md in SQLite/DuckDB; answers only via MCP over that db; target the pilot's AI answer quality | accept: Shivam | from: Shivam, 3 Nov | opened 2026-11-03
```

## 2026-11-03T16:27:34+05:30 | kakazuya (Eagle) | f7437d04 T-052 rulings of 3 Nov, tickets T-050..T-052, delete finished AR-study text extracts, worker briefs
```diff
+- T-050 | OPEN | P1 | Claude must act on every worker or job end: job_watch wait blocks until a watched job finishes, fails or stalls (run in background so Claude is woken); Stop hook refuses to end a turn while a job runs with no wait armed; stale entries can be cleared | accept: python -m pytest reality_engine/tests/test_job_watch.py -q | from: Shivam, 3 Nov | opened 2026-11-03
+- T-052 | OPEN | P1 | pilot3 OCR run to completion over every needs_ocr page (sandbox and pages.db), then rebuild pilot3.db with the OCR pages | accept: Shivam | from: Shivam, 3 Nov | opened 2026-11-03
+- T-051 | OPEN | P1 | AI-loop defects: accept rejects qids not in the bank and the stray HINDALCO029b row is removed; promoter, MF and FPI holding, Bajaj FY26 NIM, book value per share and ROCE answered from pilot3.db, not absent | accept: python -m pytest reality_engine/tests/test_gap_loop.py reality_engine/tests/test_pilot3_core.py -q | from: Shivam, 3 Nov | opened 2026-11-03
```

## 2026-11-03T17:16:16+05:30 | kakazuya (Eagle) | 20b8cba8 T-052 merge: OCR reads the 958 pages.db needs_ocr pages; build --ocr-db fills doc_page and kpi from 
```diff
++- T-053 | OPEN | P1 | Stress-test and harden job_watch wait and the Stop hook: race before baseline, corrupt status, many jobs, killed or duplicate waiters, pid reuse, registered stalls | accept: python -m pytest reality_engine/tests/test_job_watch_stress.py reality_engine/tests/test_job_watch.py reality_engine/tests/test_session_hooks.py -q | from: Shivam, 3 Nov | opened 2026-11-03
```

## 2026-11-04T03:18:41+05:30 | kakazuya (Eagle) | e605a15e T-054: brief to retire code-intel for run-and-exit code-tools; brief template gains a required Evide
```diff
+- T-054 | OPEN | P1 | Retire code-intel (800 MB LSP per worker, 1.5% of calls); code-tools outline + typecheck run-and-exit MCP; Evidence: required brief field | accept: python -m pytest plugins/code-tools/tests reality_engine/tests/test_dsh_worker_plugin.py reality_engine/tests/test_hp_worker.py -q | from: Shivam, 4 Nov | opened 2026-11-04
```

## 2026-11-04T03:40:58+05:30 | kakazuya (Eagle) | 44cabd2e T-055: night loop goal, frozen evals and boundaries (draft for Shivam's approval); eval-harness brie
```diff
+- T-055 | OPEN | P1 | Night loop frozen evals (reality_engine/night_eval: gold freeze dev/hidden, score M1-M9, guards, replay, decide, run_loop); brief tasks/dsh_tasks/T055_NIGHT_EVAL_2026-11-04.md; goal tasks/night_loop/GOAL.md | accept: python -m pytest reality_engine/tests/test_night_eval.py -q | from: Shivam 4 Nov | opened 2026-11-04
```

## 2026-11-04T04:52:11+05:30 | kakazuya (Eagle) | 9b5de23e T-056: question set frozen and split (dev 898 in repo; hidden 407 and full sets moved to D:/RealityE
```diff
+- T-056 | OPEN | P1 | Generalise reality_engine/pilot3 to any company list via a profile (pilot10: 10 companies, last 4 quarters); brief tasks/night_loop/loops/loop_01_worker_generalise.md | accept: python -m pytest reality_engine/tests/test_pilot3_core.py -q -m 'not slow' | from: Shivam 4 Nov | opened 2026-11-04
```

## 2026-11-04T18:10:35+05:30 | kakazuya (Eagle) | 9dffd01f T-056: merge bank and insurer lines, compute-only history, deals, insider and index tables (l2struct
```diff
++- T-057 | OPEN | P1 | Printed QoQ and YoY comparatives from quarterly results tables into pilot10, feeding TTM, YoY and QoQ (Shivam 4 Nov) | accept: python -m pytest reality_engine/tests/test_pilot3_comparatives.py -q | from: Shivam 4 Nov | opened 2026-11-04
```

## 2026-11-04T21:30:57+05:30 | kakazuya (Eagle) | 5653a17c T-058: guidance recall brief; combined A1 694 of 898 in STATE
```diff
+- T-058 | OPEN | P1 | Guidance recall: real guidance sentences missed for SUNPHARMA, ETERNAL, HINDUNILVR, SBILIFE, HDFCBANK, including ranges and worded targets | accept: python -m pytest reality_engine/tests/test_pilot3_guidance.py -q | from: Loop 3 next step | opened 2026-11-04
```

## 2026-11-04T22:01:13+05:30 | kakazuya (Eagle) | a5774f56 T-058: merge guidance recall (worded targets, ranges); guidance 26, core 29, lookups 23 tests pass, 
```diff
++- T-059 | OPEN | P1 | MARUTI real call transcripts from the company site replace 1-page cover letters in the pilot10 raw set (Shivam 4 Nov) | accept: python -m reality_engine.pilot3.checkpages run | from: Shivam 4 Nov | opened 2026-11-04
```

## 2026-11-04T22:04:11+05:30 | kakazuya (Eagle) | e07b4cf3 T-060: brief to fetch real documents behind cover letters; T-059 MARUTI transcripts recorded
```diff
+- T-060 | OPEN | P1 | Real results decks for HDFCBANK, INFY, ETERNAL in the pilot10 raw set: find every other held cover letter and fetch what it points at | accept: python -m reality_engine.pilot3.checkpages run | from: Shivam 4 Nov | opened 2026-11-04
```

## 2026-11-04T22:19:38+05:30 | kakazuya (Eagle) | b9c15034 T-061: KPI round 3 brief from round 2's hand read
```diff
+- T-061 | OPEN | P1 | KPI precision round 3: period, subject and unit rules to 18 of 20 per company on pilot10 | accept: python -m pytest reality_engine/tests/test_pilot3_kpi.py -q | from: KPI round 2 review | opened 2026-11-04
```

## 2026-11-04T22:31:27+05:30 | kakazuya (Eagle) | a10a0529 T-062: guidance fix brief; T-059 and T-060 closed; A1 709 of 898 on the copy
```diff
-- T-059 | OPEN | P1 | MARUTI real call transcripts from the company site replace 1-page cover letters in the pilot10 raw set (Shivam 4 Nov) | accept: python -m reality_engine.pilot3.checkpages run | from: Shivam 4 Nov | opened 2026-11-04
-- T-060 | OPEN | P1 | Real results decks for HDFCBANK, INFY, ETERNAL in the pilot10 raw set: find every other held cover letter and fetch what it points at | accept: python -m reality_engine.pilot3.checkpages run | from: Shivam 4 Nov | opened 2026-11-04
+- T-062 | OPEN | P1 | Guidance wrong rows: SBILIFE growth labelled margin, MARUTI customer mix, KEC slice, new documents hand read | accept: python -m pytest reality_engine/tests/test_pilot3_guidance.py -q | from: T-058 review | opened 2026-11-04
```

## 2026-11-04T22:53:00+05:30 | kakazuya (Eagle) | 872fa4f6 T-063: brief for missing window results filings
```diff
+- T-063 | OPEN | P1 | Missing window results filings: HDFCBANK Q2FY26, INFY Q2FY26 and Q4FY26, in the pilot10 raw set | accept: python -m reality_engine.pilot3.checkpages run | from: T-060 report | opened 2026-11-04
```

## 2026-11-04T23:17:50+05:30 | kakazuya (Eagle) | f21ca6b5 T-064: briefs for KPI three faults and October filings; reviews of KPI rounds 2 and 3 and T-063
```diff
-- T-063 | OPEN | P1 | Missing window results filings: HDFCBANK Q2FY26, INFY Q2FY26 and Q4FY26, in the pilot10 raw set | accept: python -m reality_engine.pilot3.checkpages run | from: T-060 report | opened 2026-11-04
+- T-065 | OPEN | P2 | HINDUNILVR, MARUTI, SBILIFE Q2 FY26 results filings; fetch window matches the profile; site rows in the raw manifest db | accept: python -m reality_engine.pilot3.checkpages run | from: T-063 report | opened 2026-11-04
+- T-064 | OPEN | P1 | KPI three faults: segment revenue as total, debt as a ratio, segment margin as company | accept: python -m pytest reality_engine/tests/test_pilot3_kpi.py -q | from: T-061 review | opened 2026-11-04
```

## 2026-11-04T23:21:40+05:30 | kakazuya (Eagle) | 6ab680f8 T-064: wrap-up at 400k context: next action in STATE, hand-off; T-061 dropped, T-062 closed
```diff
-- T-061 | OPEN | P1 | KPI precision round 3: period, subject and unit rules to 18 of 20 per company on pilot10 | accept: python -m pytest reality_engine/tests/test_pilot3_kpi.py -q | from: KPI round 2 review | opened 2026-11-04
-- T-062 | OPEN | P1 | Guidance wrong rows: SBILIFE growth labelled margin, MARUTI customer mix, KEC slice, new documents hand read | accept: python -m pytest reality_engine/tests/test_pilot3_guidance.py -q | from: T-058 review | opened 2026-11-04
```

## 2026-11-04T23:25:44+05:30 | kakazuya (Eagle) | ef642cd6 T-065: October filings accepted and closed
```diff
-- T-065 | OPEN | P2 | HINDUNILVR, MARUTI, SBILIFE Q2 FY26 results filings; fetch window matches the profile; site rows in the raw manifest db | accept: python -m reality_engine.pilot3.checkpages run | from: T-063 report | opened 2026-11-04
```

## 2026-11-05T00:37:44+05:30 | kakazuya (Eagle) | 926a077c T-066: tickets for the lost KPI numbers and the real answer test; fix brief
```diff
+- T-066 | OPEN | P1 | KPI branch line: restore the six numbers round 3 lost (KEC order intake and order book, HINDALCO EBITDA per tonne) so the branch can merge | accept: python -m reality_engine.pilot3.checkpages run | from: Shivam 5 Nov | opened 2026-11-05
+- T-067 | OPEN | P1 | The real test: 60 fixed random dev questions per company answered by DeepSeek through the MCP only, hand-read graded by Opus; first true baseline against 95% | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
```

## 2026-11-05T00:51:16+05:30 | kakazuya (Eagle) | cacd8f8d T-067: Shivam approves the question set and free Beam for unsettled KPI rows; answer test brief
```diff
+- T-068 | OPEN | P1 | Settle doubtful KPI rows with free beam-free on both Go keys, as a step after the build with saved verdicts; gate its accuracy on hand-read rows before use | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
```

## 2026-11-05T01:40:22+05:30 | kakazuya (Eagle) | 08133794 T-069 T-070: tickets and briefs for per-worker session ids and the HP profile database
```diff
+- T-069 | OPEN | P1 | One x-opencode-session per dsh worker: all jobs on an account share one id today, against OpenCode's docs and our rule | accept: python -m pytest reality_engine/tests/test_dsh_worker_plugin.py -q | from: Shivam 5 Nov | opened 2026-11-05
+- T-070 | OPEN | P1 | HP workers can serve a profile database: hp_worker start --pilot-db sets REALITY_PILOT3_DB for the job | accept: python -m pytest reality_engine/tests/test_hp_worker.py -q | from: Shivam 5 Nov | opened 2026-11-05
```

## 2026-11-05T01:43:45+05:30 | kakazuya (Eagle) | 8b797c86 T-069: merge one x-opencode-session per dsh worker
```diff
++- T-071 | OPEN | P2 | dsh worker sandbox and stress tests fail on the T-054 Evidence field and the launcher identity; refresh their shared brief fixture | accept: python -m pytest reality_engine/tests/test_dsh_worker_sandbox.py -q | from: T-069 review | opened 2026-11-05
```

## 2026-11-05T02:54:24+05:30 | kakazuya (Eagle) | 107606cb T-067: all 600 answers hand-read, 480 right 116 partly 4 wrong; tickets T-072 to T-074
```diff
+- T-074 | OPEN | P2 | Trial from the software-factory paper: send review findings back to the same worker session, A/B on two KPI fix rounds against fresh workers (tokens, tool calls, hand-read score) | accept: Shivam | from: Shivam 5 Nov, paper review | opened 2026-11-05
+- T-072 | OPEN | P1 | Stop worker sum and unit slips: a calculator tool with crore and lakh formatting, and a script that recomputes each answer's numbers list (31 of 120 misses in the 600-answer test) | accept: Shivam | from: T-067 hand read | opened 2026-11-05
+- T-073 | OPEN | P1 | Store defects from the 600-answer test: share count from the shareholding pattern not paid-up capital (ETERNAL 4.5% low, HUL and Hindalco rounded); PE history before four quarters of filings; quarterly stock-in-trade and inventory change lines; KEC year-to-date labelled H1 | accept: Shivam | from: T-067 hand read | opened 2026-11-05
```

## 2026-11-05T03:27:24+05:30 | kakazuya (Eagle) | 0d4dbaa4 T-072: move standing rules out of tickets, add paper and goal-brief tickets, record 5 Nov rulings
```diff
+- T-075 | OPEN | P1 | Prototype next-round in the same worker session: Opus reviews finished output, then guides it in that session. --followup-wait keeps a worker waiting only up to 3600 s and HP has no channel; find or build resume after that, and measure tokens and hand-read score | accept: Shivam | from: Paper pointer 2, Shivam 5 Nov | opened 2026-11-05
+- T-076 | OPEN | P2 | Trial: two KPI fix rounds run strictly one at a time, answer and data jobs in parallel; compare rows lost between rounds | accept: Shivam | from: Paper pointer 3, Shivam 5 Nov | opened 2026-11-05
+- T-077 | OPEN | P2 | Prototype a shared defect-type list that parallel workers read and append (Beam KPI batches, answer runs); measure repeat slips such as ten-times units | accept: Shivam | from: Paper pointer 4, Shivam 5 Nov | opened 2026-11-05
+- T-078 | OPEN | P2 | Audit each hook and gate against the last failure it stopped; propose removals for Shivam; test one versioned worker pipeline file | accept: Shivam | from: Paper pointer 5, Shivam 5 Nov | opened 2026-11-05
+- T-079 | OPEN | P1 | Trial one KPI round on a goal brief: keep evidence and fast check, drop edit-this-line steps; goal hand-read 18 of 20 on INFY and HINDALCO, checkpages at least 145 | accept: Shivam | from: Shivam 5 Nov, go given | opened 2026-11-05
```

## 2026-11-05T03:27:35+05:30 | kakazuya (Eagle) | 9c1fc26a T-075: drop T-043 and T-047 (standing rules) and T-074 (replaced)
```diff
-- T-043 | OPEN | P1 | Worker review log: tool calls, thinking and output tokens, job type, time, and Claude's review of prompt, permissions and scope, for every dsh worker and Claude session | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
-- T-047 | OPEN | P3 | Session titles: keep the sv/neo prefix, let each session choose the rest | accept: A new session started by claude-neo or claude-sv with no task shows <prefix>-<title chosen by that session> | from: Shivam, 2 Nov | opened 2026-11-02
-- T-074 | OPEN | P2 | Trial from the software-factory paper: send review findings back to the same worker session, A/B on two KPI fix rounds against fresh workers (tokens, tool calls, hand-read score) | accept: Shivam | from: Shivam 5 Nov, paper review | opened 2026-11-05
```

## 2026-11-05T05:48:51+05:30 | kakazuya (Eagle) | 1f90ea9b T-080: ticket for the answer re-run
```diff
+- T-080 | OPEN | P1 | Re-run the same 60 questions per company on the build with T-072 and T-073 merged, through the MCP only with `pilot3_calc` and `answer_record`; Opus hand-reads and compares with 480/116/4 | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
```

## 2026-11-05T16:44:56+05:30 | kakazuya (Eagle) | 357df895 T-079: review held the merge; fix worker and HINDALCO re-run started; T-030 dropped
```diff
-- T-030 | WAITING Shivam | P2 | Shivam uses the Claude cloud credit himself on the Eagle account, Tuesday 3 Nov | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
```

## 2026-11-05T17:35:28+05:30 | kakazuya (Eagle) | 040a93a3 T-081: KPI round 4 ticket and worker started; three worker reviews logged
```diff
+- T-081 | OPEN | P1 | KPI round 4: the wrong classes Opus found after T-079 (a loss stored positive, subsidiary figures as total, quarter dated to the year, non-revenue lines as revenue, question text as a value) | accept: Opus hand read on an unused seed | from: T-079 review 5 Nov | opened 2026-11-05
```

## 2026-11-05T17:54:45+05:30 | kakazuya (Eagle) | 2e3fd545 T-082: pane ticket and worker started; wrap-up at 400k context with grading next action
```diff
+- T-082 | OPEN | P2 | dsh workers pane: show stable session id, cached tokens, total tokens and median tokens per second on the band above the prompt and on the detail card | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
```

## 2026-11-05T22:30:22+05:30 | kakazuya (Eagle) | 371b8afc T-083: open the second reading step on Shivam's go; T-080 closed; STATE paths repaired
```diff
+- T-083 | DOING Eagle | P1 | Second reading step: a free model reads each answer against the question and the answer's own numbers and flags contradictions, unsourced causes and question misfit; test on graded answers before any use | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
```

## 2026-11-06T00:42:34+05:30 | kakazuya (Eagle) | 1098e7cc T-084: open the model or store test as first next session; T-085 number check gap; T-083 fix test re
```diff
+- T-084 | OPEN | P1 | HIGHEST, take first next session. Model or store test: Opus 5.5 at medium effort answers the same 180 questions DeepSeek answered for INFY, ETERNAL and BAJFINANCE (worst three in T-080: 41, 42, 44 right of 60), same questions and as_of from `D:\RealityEngine\pilot10\answer_a3\<SYMBOL>_questions.json`, same tools only (pilot3_* with pilot3_calc, recorded through answer_record), server pointed at `D:\RealityEngine\pilot10\pilot10.db` by `REALITY_PILOT3_DB`. Opus hand-reads both sets blind under shuffled labels, redoing sums. Result: a right-answer gain above 15 points means a model problem; 15 or less means look at the store | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
+- T-085 | OPEN | P1 | Number check passes invented or wrong figures: MARUTI-102 in `answer_a3\second_read\fix_test\arm_plain` writes Rs 5,33,555 crore for 5.33555e+11 rupees (53,355.5 crore); INFY-005 in `arm_flags` has inputs 43,278, 46,347, 49,012, 50,699 that sum to the right total but are not the filed quarters (Q2 49,244). Catch both with no new false alarm on the 600 answers | accept: python -m pytest reality_engine/tests/test_pilot3_number_check.py -q | from: Eagle 6 Nov, T-083 read | opened 2026-11-06
```

## 2026-11-06T00:47:02+05:30 | kakazuya (Eagle) | f5c123d0 T-084: no bar in advance, keep every attribute per answer (Shivam)
```diff
-- T-084 | OPEN | P1 | HIGHEST, take first next session. Model or store test: Opus 5.5 at medium effort answers the same 180 questions DeepSeek answered for INFY, ETERNAL and BAJFINANCE (worst three in T-080: 41, 42, 44 right of 60), same questions and as_of from `D:\RealityEngine\pilot10\answer_a3\<SYMBOL>_questions.json`, same tools only (pilot3_* with pilot3_calc, recorded through answer_record), server pointed at `D:\RealityEngine\pilot10\pilot10.db` by `REALITY_PILOT3_DB`. Opus hand-reads both sets blind under shuffled labels, redoing sums. Result: a right-answer gain above 15 points means a model problem; 15 or less means look at the store | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
+- T-084 | OPEN | P1 | HIGHEST, take first next session. Model or store test: Opus 5.5 at medium effort answers the same 180 questions DeepSeek answered for INFY, ETERNAL and BAJFINANCE (worst three in T-080: 41, 42, 44 right of 60), same questions and as_of from `D:\RealityEngine\pilot10\answer_a3\<SYMBOL>_questions.json`, same tools only (pilot3_* with pilot3_calc, recorded through answer_record), server pointed at `D:\RealityEngine\pilot10\pilot10.db` by `REALITY_PILOT3_DB`. Opus hand-reads both sets blind under shuffled labels, redoing sums. Keep per answer: qid, company, question type, model and effort, grade and fault class, tool calls by tool, tokens, minutes, number-check result, plus DeepSeek old grade and new blind grade. Shivam reads the results himself and sets no bar in advance | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
```

## 2026-11-06T03:47:29+05:30 | kakazuya (Eagle) | 074637f9 T-084: grading plan changed by Shivam: DeepSeek all 82 pairs, Opus samples
```diff
-- T-084 | OPEN | P1 | HIGHEST, take first next session. Model or store test: Opus 5.5 at medium effort answers the same 180 questions DeepSeek answered for INFY, ETERNAL and BAJFINANCE (worst three in T-080: 41, 42, 44 right of 60), same questions and as_of from `D:\RealityEngine\pilot10\answer_a3\<SYMBOL>_questions.json`, same tools only (pilot3_* with pilot3_calc, recorded through answer_record), server pointed at `D:\RealityEngine\pilot10\pilot10.db` by `REALITY_PILOT3_DB`. Opus hand-reads both sets blind under shuffled labels, redoing sums. Keep per answer: qid, company, question type, model and effort, grade and fault class, tool calls by tool, tokens, minutes, number-check result, plus DeepSeek old grade and new blind grade. Shivam reads the results himself and sets no bar in advance | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
+- T-084 | OPEN | P1 | HIGHEST, take first next session. Model or store test: Opus 5.5 at medium effort answers the same 180 questions DeepSeek answered for INFY, ETERNAL and BAJFINANCE (worst three in T-080: 41, 42, 44 right of 60), same questions and as_of from `D:\RealityEngine\pilot10\answer_a3\<SYMBOL>_questions.json`, same tools only (pilot3_* with pilot3_calc, recorded through answer_record), server pointed at `D:\RealityEngine\pilot10\pilot10.db` by `REALITY_PILOT3_DB`. Opus hand-reads both sets blind under shuffled labels, redoing sums. Keep per answer: qid, company, question type, model and effort, grade and fault class, tool calls by tool, tokens, minutes, number-check result, plus DeepSeek old grade and new blind grade. Shivam reads the results himself and sets no bar in advance. Changed by Shivam 6 Nov: stopped at 82 of 180 answered and only those graded; DeepSeek grades all 82 pairs blind, Opus reads 20 random pairs (`answer_t084\grading\opus_random_20.txt`, drawn before grades) plus every pair DeepSeek grades differently | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
```

## 2026-11-06T04:14:06+05:30 | kakazuya (Eagle) | d2408465 T-084: graded on 82 of 180; open T-086 wrong-base growth rows
```diff
+- T-086 | OPEN | P1 | Wrong-base growth rows in `ratio_panel`: INFY Q2FY27 consolidated `revenue_growth_yoy_pct` is 8.28 (49,244 over Q3 FY26 45,479); the filing gives 10.7 (over 44,490). Check all companies and fix the build | accept: Shivam | from: Eagle 6 Nov, T-084 read | opened 2026-11-06
```

## 2026-11-06T04:40:01+05:30 | kakazuya (Eagle) | 8ad174e8 T-087: open DeepSeek dig test on 20 graded misses
```diff
+- T-087 | OPEN | P1 | DeepSeek digs on 20 of its own graded misses from the T-084 read: no tool-call limit, schema card, MSI, raw source files allowed; for each gap report why the data is not in the database and how to store it. Opus reads the results blind | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
```

## 2026-11-06T13:36:27+05:30 | kakazuya (Eagle) | 7adcd888 T-088, T-089: open store fixes and holiday rows; record the goal ruling
```diff
+- T-088 | OPEN | P1 | Store fixes 1 and 2 from the T-087 report: shareholding (named holders, pledge, denominator, September 2025 backfill) and financial lines (one preferred comparative, stated and derived ROE, exceptional items and TTM, entity apart from basis). Same 20 questions re-asked on DeepSeek afterwards. Start after 15:30 IST 6 Nov | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
+- T-089 | OPEN | P2 | Main store `daily_price_delivery` holds copies of the prior day on holidays (INFY 2026-03-03 repeats 2026-03-02, 2,229 rows that date, also 2025-12-25, 2026-01-26); remove them or mark them, and check what reads them | accept: Shivam | from: Eagle 6 Nov, T-087 read | opened 2026-11-06
```

## 2026-11-06T18:20:31+05:30 | kakazuya (Eagle) | 68191e62 T-090: open the universe-scale round, Shivam's ruling and six tickets
```diff
+- T-090 | OPEN | P1 | One preferred figure in the data: point-in-time preferred columns on the financial tables, the election shared with pilot3_fin, and tool text that reads coverage from the database instead of naming three companies | accept: python -m pytest reality_engine/tests/test_pilot3_preferred_data.py -q | from: Shivam 6 Nov, T-088 re-test | opened 2026-11-06
+- T-091 | OPEN | P1 | Universal annual-report note tables: credit ratings and rating triggers, concentration, related-party transactions, with no company-specific rules | accept: python -m pytest reality_engine/tests/test_pilot3_note_tables.py -q | from: Shivam 6 Nov, T-088 re-test | opened 2026-11-06
+- T-092 | OPEN | P1 | Complete, named guidance from letters and calls, with the store count and growth targets the ETERNAL answers had to dig for; universal rules | accept: Shivam | from: Shivam 6 Nov, T-088 re-test | opened 2026-11-06
+- T-093 | OPEN | P1 | Document identity check before the full run: company, fiscal year, type against BSE category and text, date from a filing record; failures set aside, not deleted | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
+- T-094 | OPEN | P1 | Universe readiness: no hand lists of companies in build or tools (LENDERS in ratios.py, kpi.COMPANIES, gap_loop COMPANIES, docs_collect KEC manifest), sector from data, per-company time and size measured and projected to 6,940 companies, and an unchanged build on companies never seen | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
+- T-095 | OPEN | P1 | Re-ask the same 20 questions with the T-088 brief after T-090, T-091 and T-092, Opus read blind | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
```

## 2026-11-06T19:59:07+05:30 | kakazuya (Eagle) | 4dda2050 T-090, T-091: closed, accept commands pass
```diff
-- T-090 | OPEN | P1 | One preferred figure in the data: point-in-time preferred columns on the financial tables, the election shared with pilot3_fin, and tool text that reads coverage from the database instead of naming three companies | accept: python -m pytest reality_engine/tests/test_pilot3_preferred_data.py -q | from: Shivam 6 Nov, T-088 re-test | opened 2026-11-06
-- T-091 | OPEN | P1 | Universal annual-report note tables: credit ratings and rating triggers, concentration, related-party transactions, with no company-specific rules | accept: python -m pytest reality_engine/tests/test_pilot3_note_tables.py -q | from: Shivam 6 Nov, T-088 re-test | opened 2026-11-06
```

## 2026-11-06T21:54:30+05:30 | kakazuya (Eagle) | 6731d1ca No-ticket: logs the job_watch wake-up fault as a new ticket row
```diff
+- T-096 | OPEN | P1 | job_watch wakes Claude at once when a worker with a follow-up wait ends its turn, and shows live tool counts: awaiting_input now reads as RUNNING until the 10-minute stall | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
```

## 2026-11-06T23:47:38+05:30 | kakazuya (Wolf) | 1ac5a247 T-097: Go key 2 for all paid calls (HP default too), board cleanup on Shivam's 6 Nov ruling
```diff
-- T-004 | OPEN | P1 | Final count and verdict on the 9 efficiency fixes, due the night of 1 Nov | accept: Shivam | from: tasks/efficiency/FIX_TRACKER_2026-10-31.md | opened 2026-11-02
-- T-054 | OPEN | P1 | Retire code-intel (800 MB LSP per worker, 1.5% of calls); code-tools outline + typecheck run-and-exit MCP; Evidence: required brief field | accept: python -m pytest plugins/code-tools/tests reality_engine/tests/test_dsh_worker_plugin.py reality_engine/tests/test_hp_worker.py -q | from: Shivam, 4 Nov | opened 2026-11-04
-- T-069 | OPEN | P1 | One x-opencode-session per dsh worker: all jobs on an account share one id today, against OpenCode's docs and our rule | accept: python -m pytest reality_engine/tests/test_dsh_worker_plugin.py -q | from: Shivam 5 Nov | opened 2026-11-05
+- T-097 | DOING Wolf | P1 | Go key 1 is at 99% of its limit: every paid call (dsh workers, HP default included) uses key 2; key 1 only for a dsh server test; free Beam stays on both keys | accept: python -m pytest reality_engine/tests/test_hp_worker.py -q | from: Shivam 6 Nov | opened 2026-11-06
-- T-057 | OPEN | P1 | Printed QoQ and YoY comparatives from quarterly results tables into pilot10, feeding TTM, YoY and QoQ (Shivam 4 Nov) | accept: python -m pytest reality_engine/tests/test_pilot3_comparatives.py -q | from: Shivam 4 Nov | opened 2026-11-04
-- T-058 | OPEN | P1 | Guidance recall: real guidance sentences missed for SUNPHARMA, ETERNAL, HINDUNILVR, SBILIFE, HDFCBANK, including ranges and worded targets | accept: python -m pytest reality_engine/tests/test_pilot3_guidance.py -q | from: Loop 3 next step | opened 2026-11-04
-- T-064 | OPEN | P1 | KPI three faults: segment revenue as total, debt as a ratio, segment margin as company | accept: python -m pytest reality_engine/tests/test_pilot3_kpi.py -q | from: T-061 review | opened 2026-11-04
-- T-066 | OPEN | P1 | KPI branch line: restore the six numbers round 3 lost (KEC order intake and order book, HINDALCO EBITDA per tonne) so the branch can merge | accept: python -m reality_engine.pilot3.checkpages run | from: Shivam 5 Nov | opened 2026-11-05
-- T-055 | OPEN | P1 | Night loop frozen evals (reality_engine/night_eval: gold freeze dev/hidden, score M1-M9, guards, replay, decide, run_loop); brief tasks/dsh_tasks/T055_NIGHT_EVAL_2026-11-04.md; goal tasks/night_loop/GOAL.md | accept: python -m pytest reality_engine/tests/test_night_eval.py -q | from: Shivam 4 Nov | opened 2026-11-04
-- T-056 | OPEN | P1 | Generalise reality_engine/pilot3 to any company list via a profile (pilot10: 10 companies, last 4 quarters); brief tasks/night_loop/loops/loop_01_worker_generalise.md | accept: python -m pytest reality_engine/tests/test_pilot3_core.py -q -m 'not slow' | from: Shivam 4 Nov | opened 2026-11-04
-- T-067 | OPEN | P1 | The real test: 60 fixed random dev questions per company answered by DeepSeek through the MCP only, hand-read graded by Opus; first true baseline against 95% | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
-- T-072 | OPEN | P1 | Stop worker sum and unit slips: a calculator tool with crore and lakh formatting, and a script that recomputes each answer's numbers list (31 of 120 misses in the 600-answer test) | accept: Shivam | from: T-067 hand read | opened 2026-11-05
-- T-073 | OPEN | P1 | Store defects from the 600-answer test: share count from the shareholding pattern not paid-up capital (ETERNAL 4.5% low, HUL and Hindalco rounded); PE history before four quarters of filings; quarterly stock-in-trade and inventory change lines; KEC year-to-date labelled H1 | accept: Shivam | from: T-067 hand read | opened 2026-11-05
-- T-084 | OPEN | P1 | HIGHEST, take first next session. Model or store test: Opus 5.5 at medium effort answers the same 180 questions DeepSeek answered for INFY, ETERNAL and BAJFINANCE (worst three in T-080: 41, 42, 44 right of 60), same questions and as_of from `D:\RealityEngine\pilot10\answer_a3\<SYMBOL>_questions.json`, same tools only (pilot3_* with pilot3_calc, recorded through answer_record), server pointed at `D:\RealityEngine\pilot10\pilot10.db` by `REALITY_PILOT3_DB`. Opus hand-reads both sets blind under shuffled labels, redoing sums. Keep per answer: qid, company, question type, model and effort, grade and fault class, tool calls by tool, tokens, minutes, number-check result, plus DeepSeek old grade and new blind grade. Shivam reads the results himself and sets no bar in advance. Changed by Shivam 6 Nov: stopped at 82 of 180 answered and only those graded; DeepSeek grades all 82 pairs blind, Opus reads 20 random pairs (`answer_t084\grading\opus_random_20.txt`, drawn before grades) plus every pair DeepSeek grades differently | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
-- T-087 | OPEN | P1 | DeepSeek digs on 20 of its own graded misses from the T-084 read: no tool-call limit, schema card, MSI, raw source files allowed; for each gap report why the data is not in the database and how to store it. Opus reads the results blind | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
-- T-088 | OPEN | P1 | Store fixes 1 and 2 from the T-087 report: shareholding (named holders, pledge, denominator, September 2025 backfill) and financial lines (one preferred comparative, stated and derived ROE, exceptional items and TTM, entity apart from basis). Same 20 questions re-asked on DeepSeek afterwards. Start after 15:30 IST 6 Nov | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
-- T-093 | OPEN | P1 | Document identity check before the full run: company, fiscal year, type against BSE category and text, date from a filing record; failures set aside, not deleted | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
-- T-086 | OPEN | P1 | Wrong-base growth rows in `ratio_panel`: INFY Q2FY27 consolidated `revenue_growth_yoy_pct` is 8.28 (49,244 over Q3 FY26 45,479); the filing gives 10.7 (over 44,490). Check all companies and fix the build | accept: Shivam | from: Eagle 6 Nov, T-084 read | opened 2026-11-06
-- T-080 | OPEN | P1 | Re-run the same 60 questions per company on the build with T-072 and T-073 merged, through the MCP only with `pilot3_calc` and `answer_record`; Opus hand-reads and compares with 480/116/4 | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
-- T-070 | OPEN | P1 | HP workers can serve a profile database: hp_worker start --pilot-db sets REALITY_PILOT3_DB for the job | accept: python -m pytest reality_engine/tests/test_hp_worker.py -q | from: Shivam 5 Nov | opened 2026-11-05
```

## 2026-11-06T23:47:46+05:30 | kakazuya (Wolf) | bf6fecaa T-097: done, key 1 dsh smoke test passed on HP (hp-20261106T234436-1c843f)
```diff
-- T-097 | DOING Wolf | P1 | Go key 1 is at 99% of its limit: every paid call (dsh workers, HP default included) uses key 2; key 1 only for a dsh server test; free Beam stays on both keys | accept: python -m pytest reality_engine/tests/test_hp_worker.py -q | from: Shivam 6 Nov | opened 2026-11-06
```

## 2026-11-07T00:04:30+05:30 | kakazuya (Wolf) | 77ec526e Merge T-089: read-only holiday-copy scan of daily_price_delivery (57 dates, 113,195 rows); T-039 dro
```diff
++- T-099 | WAITING Shivam | P1 | Holiday copies in daily_price_delivery: fix nse_client.fetch_bhavcopy date check, delete 111,535 rows by the T-089 plan, replace 2021-11-04 Muhurat session, rebuild indicators | accept: Shivam | from: T-089 report 7 Nov | opened 2026-11-07
++- T-098 | OPEN | P1 | Build applies window_start to documents, not only stores: scratch builds from the pilot60_history manifest held 2019+ documents (hold6 531 of 611 guidance targets before 2024-04-01); re-measure T-094's 501 GB and 52 h projection on windowed documents | accept: Shivam | from: Wolf 6 Nov, T-092 hold-out read | opened 2026-11-06
```

## 2026-11-07T00:13:48+05:30 | kakazuya (Wolf) | 7ddccb0d T-100: Shivam's document scope ruling (decks and calls first, annual reports by selected sections, r
```diff
+- T-100 | OPEN | P1 | Document scope per Shivam 7 Nov: annual reports by script to selected sections (full read only where a company has no calls or decks), announcements cut to material categories, rating and borrowing documents kept; measure size per company on 2024-04+ documents and project to 6,940 | accept: Shivam | from: Shivam 7 Nov | opened 2026-11-07
```

## 2026-11-07T00:17:28+05:30 | kakazuya (Wolf) | d5ac437a T-100, T-097: rows reworded as test and change only; the rulings stay in tasks/RULINGS.md
```diff
-- T-100 | OPEN | P1 | Document scope per Shivam 7 Nov: annual reports by script to selected sections (full read only where a company has no calls or decks), announcements cut to material categories, rating and borrowing documents kept; measure size per company on 2024-04+ documents and project to 6,940 | accept: Shivam | from: Shivam 7 Nov | opened 2026-11-07
+- T-100 | OPEN | P1 | Prototype an announcement category allow-list (Shivam approves the list first) and re-measure per-company size on 2024-04+ documents with it; project to 6,940 | accept: Shivam | from: Shivam 7 Nov | opened 2026-11-07
```

## 2026-11-07T01:11:58+05:30 | kakazuya (Wolf) | 14bb8b16 T-099: holiday copies removed from daily_price_delivery, Muhurat 2021-11-04 restored, bhavcopy write
```diff
-- T-096 | OPEN | P1 | job_watch wakes Claude at once when a worker with a follow-up wait ends its turn, and shows live tool counts: awaiting_input now reads as RUNNING until the 10-minute stall | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
-- T-099 | WAITING Shivam | P1 | Holiday copies in daily_price_delivery: fix nse_client.fetch_bhavcopy date check, delete 111,535 rows by the T-089 plan, replace 2021-11-04 Muhurat session, rebuild indicators | accept: Shivam | from: T-089 report 7 Nov | opened 2026-11-07
-- T-100 | OPEN | P1 | Prototype an announcement category allow-list (Shivam approves the list first) and re-measure per-company size on 2024-04+ documents with it; project to 6,940 | accept: Shivam | from: Shivam 7 Nov | opened 2026-11-07
+- T-100 | OPEN | P1 | Prototype the announcement type reader: classify each 2024-04+ announcement from its own text (first page, more pages until clear), not the exchange category; measure agreement with a hand read and how often the exchange label is wrong; re-measure per-company size on the kept types; project to 6,940 | accept: Shivam | from: Shivam 7 Nov | opened 2026-11-07
+- T-099 | OPEN | P1 | Holiday copies in daily_price_delivery: fix nse_client.fetch_bhavcopy date check, delete 111,535 rows by the T-089 plan, replace 2021-11-04 Muhurat session, rebuild indicators | accept: Shivam | from: T-089 report 7 Nov | opened 2026-11-07
```

## 2026-11-07T01:11:59+05:30 | kakazuya (Wolf) | 28ec6eb5 T-099: closed, done in 14bb8b1
```diff
-- T-099 | OPEN | P1 | Holiday copies in daily_price_delivery: fix nse_client.fetch_bhavcopy date check, delete 111,535 rows by the T-089 plan, replace 2021-11-04 Muhurat session, rebuild indicators | accept: Shivam | from: T-089 report 7 Nov | opened 2026-11-07
```

## 2026-11-07T01:41:03+05:30 | kakazuya (Wolf) | a8cc6df5 T-101: doc_locations.py maps every catalogued document to disk and the Drive archive
```diff
+- T-101 | OPEN | P1 | One document inventory: every held document file on C, D and the Drive archive linked to its catalog row (corporate_documents, raw_documents) or listed as unlinked; Drive part done by doc_locations.py (70,617 Drive files, 398 GB, no row points to: all 23,596 decks, 40,405 results PDFs) | accept: python -m pytest reality_engine/tests/test_doc_locations.py -q | from: Shivam 7 Nov | opened 2026-11-07
```

## 2026-11-07T02:16:07+05:30 | kakazuya (Wolf) | 50501014 T-102: raw files only on Drive (Shivam's ruling); raw_to_drive.py; doc_locations reads the second ar
```diff
+- T-102 | OPEN | P1 | Raw files only on Google Drive: upload every MSI and HP raw file not yet on Drive (verified by size and hash), delete local copies, jobs fetch on demand and delete after; search the rest of Drive for files the 44,601 not-found catalog rows point to | accept: python -m pytest reality_engine/tests/test_doc_locations.py -q | from: Shivam 7 Nov | opened 2026-11-07
```

## 2026-11-07T03:46:30+05:30 | kakazuya (Wolf) | 5f95c765 T-103 opened: model-read rows out of default answers (Shivam 7 Nov)
```diff
+- T-103 | OPEN | P1 | Model-read rows out of default answers: facts() ranks filed XBRL first, labels every row by extraction (filed_xbrl or model_read, unverified), returns model-read rows (ar_facts, deck_figures, concall_facts) only on include_model_read=true or an explicit kind; search_docs drops annual-report model quotes unless asked | accept: python -m pytest plugins/reality-data/tests/test_reality_data.py plugins/reality-data/tests/test_search_docs.py -q | from: Shivam 7 Nov | opened 2026-11-07
```

## 2026-11-07T04:12:28+05:30 | kakazuya (Wolf) | fd542212 T-103 closed, T-102 next steps: wrap-up at 400k (STATE next action, doc sweep clean, worker review l
```diff
-- T-103 | OPEN | P1 | Model-read rows out of default answers: facts() ranks filed XBRL first, labels every row by extraction (filed_xbrl or model_read, unverified), returns model-read rows (ar_facts, deck_figures, concall_facts) only on include_model_read=true or an explicit kind; search_docs drops annual-report model quotes unless asked | accept: python -m pytest plugins/reality-data/tests/test_reality_data.py plugins/reality-data/tests/test_search_docs.py -q | from: Shivam 7 Nov | opened 2026-11-07
```

## 2026-11-07T23:44:40+05:30 | kakazuya (Wolf) | fb88d426 T-104: Antigravity CLI worker ticket; ruling: agy runs only gemini-3.8-flash-medium
```diff
+- T-104 | OPEN | P2 | Antigravity CLI as a worker backend: confirm a headless run (prompt in, edits in a worktree, answer out, exit), its login persistence, models and daily quota on Google AI Pro; one small test task; if it passes, add an adapter to dsh-worker beside OpenCode; model only gemini-3.8-flash-medium (Shivam) | accept: Shivam | from: Shivam 7 Nov | opened 2026-11-07
```

## 2026-11-08T02:00:45+05:30 | kakazuya (Wolf) | 8d868e52 T-105..T-112: store fixes from the Gemini vs Opus vs DeepSeek test; agy-worker tool ticket
```diff
+- T-105 | OPEN | P1 | Latest guidance: each `guidance` row links the row it supersedes and `pilot3_guidance` returns the current target per company+metric+period by default (history on request); load the Q2 FY27 call targets missing for BAJFINANCE (60-62 mn loans, 18-20 mn customers, 25-40 bps opex, AUM 26-27%). Fails now: BAJFINANCE-014, -017 | accept: those two re-asked by DeepSeek come back right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
+- T-106 | OPEN | P1 | Scope on every guidance and KPI row: group, segment or subsidiary (Blinkit, District, BHFL), so a segment target is never served as the company's. Fails now: ETERNAL-015, -017 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
+- T-107 | OPEN | P1 | Period type on every ratio row (quarter, half, year) and the full-year ratio stored directly (BAJFINANCE FY26 ROE 18.1%, not Q4 20.0%). Fails now: BAJFINANCE-027 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
+- T-108 | OPEN | P1 | Nil is a fact: a shareholding filing that states nil promoter pledge stores pledge 0 with its filing, and `pilot3_holding` says nil, filed on date. Fails now: BAJFINANCE-029, INFY-034 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
+- T-109 | OPEN | P2 | `pilot3_calc` returns a change between two percentages in percentage points (unit pp) beside the relative change. Fails now: INFY-035, INFY-032, INFY-065 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
+- T-110 | OPEN | P2 | Extract the facts found missing: named holders each quarter (shp_holder), standalone related-party transactions, parent guarantees, restated prior-period figures. Fails now: ETERNAL-033, ETERNAL-053, INFY-051, BAJFINANCE-001 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
+- T-111 | OPEN | P2 | Ready-made answer views for common question shapes (results summary, debt, ratings, holders, auditor, 52-week range) so an answer takes 1-3 calls, not 10-16 | accept: DeepSeek median calls per question under 5 on the 82, score not lower | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
+- T-112 | OPEN | P1 | agy-worker MCP: start, status (tool calls by tool, tokens, quota left), result and cancel for Antigravity CLI coding jobs in a Wolf- worktree, like dsh-worker; then the same prescriptive T-105 brief to Gemini 3.8 Flash medium and to dsh, compared | accept: Shivam | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
```

## 2026-11-08T03:43:44+05:30 | kakazuya (Wolf) | b07c30a8 T-113: standing rule (worker never checks own code) and row check layer prototype for guidance and k
```diff
+- T-113 | DOING Wolf | P1 | Independent row check layer `reality_engine/pilot3/row_checks.py` for `guidance` and `kpi_series` (quote anchor, sector-metric fit, own-company figure, reconciliation, plausibility) giving each row verified / unverified / quarantined; run over live pilot10.db read-only and report counts per metric, sector and document type | accept: catches the 6 T-105 rows deleted 8 Nov (backup guidance_before_t105.db) and most of the 15 Gemini T-105 wrong rows without being told about them; Opus sample of quarantined and verified rows; Shivam | from: Shivam 8 Nov (standing rule: worker never checks its own code) | opened 2026-11-08
```

## 2026-11-08T12:53:13+05:30 | kakazuya (Wolf) | 2186604d T-114, T-115, T-116 opened (pre-existing test failures, ar_facts scale bug, investor question harves
```diff
+- T-114 | OPEN | P3 | Fix three pilot3 test files that fail on main before T-113: `test_pilot3_ocr` (`registry.PAGES_DB` missing), `test_pilot3_no_company_literals` (`_company_manifest` signature), `test_pilot3_profile` (1 test) | accept: each file passes run alone | from: Wolf 8 Nov, found running T-113 neighbour tests | opened 2026-11-08
+- T-115 | OPEN | P1 | `fin_annual_line` rows from `ar_facts` keep the unit text ('rs mn', 'rs lakh', 'rs. in lacs') but scale 1 (104 rows on unseen6 + pilot10: ALKEM, ASHOKA, UFLEX, KALYANKJIL, SBILIFE, SUNPHARMA), and several history columns land under one year (ALKEM FY26 revenue holds 5 values) | accept: no fin_annual_line row whose unit names a scale has scale 1; one value per symbol/year/line/basis/caption; row_checks fin_conflict counts unchanged or lower | from: T-113 round 9 worker list, 8 Nov | opened 2026-11-08
+- T-116 | DOING Wolf | P2 | Investor question harvest: agy (Gemini 3.8 Flash medium) searches Google and YouTube for questions investors ask about each test company; Opus reframes them inside our data's bounds, marks blind spots (questions our bank does not ask) | accept: Shivam reviews the reframed list | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T12:58:47+05:30 | kakazuya (Wolf) | 83d4677c T-114, T-115: briefs for DeepSeek workers (test drift; ar_facts unit scale and quote year)
```diff
-- T-114 | OPEN | P3 | Fix three pilot3 test files that fail on main before T-113: `test_pilot3_ocr` (`registry.PAGES_DB` missing), `test_pilot3_no_company_literals` (`_company_manifest` signature), `test_pilot3_profile` (1 test) | accept: each file passes run alone | from: Wolf 8 Nov, found running T-113 neighbour tests | opened 2026-11-08
-- T-115 | OPEN | P1 | `fin_annual_line` rows from `ar_facts` keep the unit text ('rs mn', 'rs lakh', 'rs. in lacs') but scale 1 (104 rows on unseen6 + pilot10: ALKEM, ASHOKA, UFLEX, KALYANKJIL, SBILIFE, SUNPHARMA), and several history columns land under one year (ALKEM FY26 revenue holds 5 values) | accept: no fin_annual_line row whose unit names a scale has scale 1; one value per symbol/year/line/basis/caption; row_checks fin_conflict counts unchanged or lower | from: T-113 round 9 worker list, 8 Nov | opened 2026-11-08
+- T-114 | DOING Wolf | P3 | Fix three pilot3 test files that fail on main before T-113: `test_pilot3_ocr` (`registry.PAGES_DB` missing), `test_pilot3_no_company_literals` (`_company_manifest` signature), `test_pilot3_profile` (1 test) | accept: each file passes run alone | from: Wolf 8 Nov, found running T-113 neighbour tests | opened 2026-11-08
+- T-115 | DOING Wolf | P1 | `fin_annual_line` rows from `ar_facts` keep the unit text ('rs mn', 'rs lakh', 'rs. in lacs') but scale 1 (104 rows on unseen6 + pilot10: ALKEM, ASHOKA, UFLEX, KALYANKJIL, SBILIFE, SUNPHARMA), and several history columns land under one year (ALKEM FY26 revenue holds 5 values) | accept: no fin_annual_line row whose unit names a scale has scale 1; one value per symbol/year/line/basis/caption; row_checks fin_conflict counts unchanged or lower | from: T-113 round 9 worker list, 8 Nov | opened 2026-11-08
```

## 2026-11-08T13:11:33+05:30 | kakazuya (Wolf) | 20d48836 T-107: started (dsh 20261108T074113Z-e99f5aff)
```diff
-- T-107 | OPEN | P1 | Period type on every ratio row (quarter, half, year) and the full-year ratio stored directly (BAJFINANCE FY26 ROE 18.1%, not Q4 20.0%). Fails now: BAJFINANCE-027 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
+- T-107 | DOING Wolf | P1 | Period type on every ratio row (quarter, half, year) and the full-year ratio stored directly (BAJFINANCE FY26 ROE 18.1%, not Q4 20.0%). Fails now: BAJFINANCE-027 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
```

## 2026-11-08T13:28:15+05:30 | kakazuya (Wolf) | b094f0d5 T-116: investor question harvest reframed (95 questions, 14 blind spots); agy links found invented; 
```diff
-- T-116 | DOING Wolf | P2 | Investor question harvest: agy (Gemini 3.8 Flash medium) searches Google and YouTube for questions investors ask about each test company; Opus reframes them inside our data's bounds, marks blind spots (questions our bank does not ask) | accept: Shivam reviews the reframed list | from: Shivam 8 Nov | opened 2026-11-08
+- T-116 | WAITING Shivam | P2 | Investor question harvest: agy (Gemini 3.8 Flash medium) searches Google and YouTube for questions investors ask about each test company; Opus reframes them inside our data's bounds, marks blind spots (questions our bank does not ask) | accept: Shivam reviews the reframed list | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T13:32:39+05:30 | kakazuya (Wolf) | af29a663 Rulings: investor-question scope (peers later by model, brokerage facts only, regulator fetcher T-11
```diff
+- T-117 | OPEN | P3 | Regulator notice fetcher: RBI, IRDAI, SEBI and other authorities' circulars, notices and bulletins (PIB does not carry them), dated and mapped to the companies they touch; design later | accept: Shivam | from: Shivam 8 Nov (T-116 review) | opened 2026-11-08
```

## 2026-11-08T13:50:46+05:30 | kakazuya (Wolf) | 14f3cddd Rulings: ultimate objective is 6m-2y price prediction from the least reliable data; T-118 factor wei
```diff
+- T-118 | OPEN | P1 | Factor weight study: which held, reliable facts explain 6-month, 1-year and 2-year forward returns across the universe (earnings and PAT growth, guidance raised or cut, margin trend, ROE/ROCE, valuation, net debt change, promoter/FPI/MF holding change, pledges, insider buys), measured as rank correlation per period with sector and size controls; the result ranks which extractions to finish first and which to drop | accept: Shivam | from: Shivam 8 Nov (objective: predict 6m-2y from the least reliable data; heavyweight factors only) | opened 2026-11-08
```

## 2026-11-08T13:53:04+05:30 | kakazuya (Wolf) | 251d7670 T-118: factor weight study brief (PIT monthly panel 2019-2026, rank IC and Fama-MacBeth at 6/12/24 m
```diff
-- T-118 | OPEN | P1 | Factor weight study: which held, reliable facts explain 6-month, 1-year and 2-year forward returns across the universe (earnings and PAT growth, guidance raised or cut, margin trend, ROE/ROCE, valuation, net debt change, promoter/FPI/MF holding change, pledges, insider buys), measured as rank correlation per period with sector and size controls; the result ranks which extractions to finish first and which to drop | accept: Shivam | from: Shivam 8 Nov (objective: predict 6m-2y from the least reliable data; heavyweight factors only) | opened 2026-11-08
+- T-118 | DOING Wolf | P1 | Factor weight study: which held, reliable facts explain 6-month, 1-year and 2-year forward returns across the universe (earnings and PAT growth, guidance raised or cut, margin trend, ROE/ROCE, valuation, net debt change, promoter/FPI/MF holding change, pledges, insider buys), measured as rank correlation per period with sector and size controls; the result ranks which extractions to finish first and which to drop | accept: Shivam | from: Shivam 8 Nov (objective: predict 6m-2y from the least reliable data; heavyweight factors only) | opened 2026-11-08
```

## 2026-11-08T14:08:14+05:30 | kakazuya (Wolf) | 27441e1f T-119 opened: own forward estimates vs market-implied growth (Shivam 8 Nov)
```diff
+- T-119 | OPEN | P1 | Our own forward estimates vs the market's: per company, our 1-2 year revenue and earnings estimate from held facts (trend, guidance, order book, margins), and the growth the current price implies (reverse DCF / implied growth at a sector discount rate); the gap says whether the market sees the company through the same lens. Measure the gap's power on 6m-2y forward returns after T-118, PIT | accept: Shivam | from: Shivam 8 Nov (P/E and P/S are lagging when the market pays a premium; the market looks 6 months to 2 years ahead) | opened 2026-11-08
```

## 2026-11-08T14:15:43+05:30 | kakazuya (Wolf) | 2856c400 T-120: rulings (verbatim statements first, compute judges at scale; pilot companies may hold pre-FY2
```diff
+- T-120 | DOING Wolf | P1 | Pilot10 history 2019-2024: fetch BSE documents for HDFCBANK, SBILIFE, INFY, MARUTI, ETERNAL (the other five are already in pilot60_history) and build a pilot10 history database with window_start 2019, so verbatim statements, guidance and KPIs can be tested on 6m-2y horizons (T-118/T-119) | accept: coverage per company per year (decks, calls, results, AR) reported; Shivam | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T15:02:12+05:30 | kakazuya (Wolf) | b058fbcd T-121: document robustness ticket and brief (OCR inside every build; stratified format-drift canary)
```diff
+- T-121 | OPEN | P1 | Document robustness: every page gets text (OCR part inside every profile build; today 6% of pages and 130 of 1,937 documents in a fresh build have no text) and a stratified canary of unseen companies x doc type x year that flags any drop in text coverage or extractor yield when a document format changes | accept: tests + canary table; Shivam | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T15:08:31+05:30 | kakazuya (Wolf) | 9a7984f0 T-118: factor weight study (PIT monthly panel 2019-2026, 35 factors, rank IC + Fama-MacBeth at 6/12/
```diff
-- T-118 | DOING Wolf | P1 | Factor weight study: which held, reliable facts explain 6-month, 1-year and 2-year forward returns across the universe (earnings and PAT growth, guidance raised or cut, margin trend, ROE/ROCE, valuation, net debt change, promoter/FPI/MF holding change, pledges, insider buys), measured as rank correlation per period with sector and size controls; the result ranks which extractions to finish first and which to drop | accept: Shivam | from: Shivam 8 Nov (objective: predict 6m-2y from the least reliable data; heavyweight factors only) | opened 2026-11-08
+- T-118 | WAITING Shivam | P1 | Factor weight study: which held, reliable facts explain 6-month, 1-year and 2-year forward returns across the universe (earnings and PAT growth, guidance raised or cut, margin trend, ROE/ROCE, valuation, net debt change, promoter/FPI/MF holding change, pledges, insider buys), measured as rank correlation per period with sector and size controls; the result ranks which extractions to finish first and which to drop | accept: Shivam | from: Shivam 8 Nov (objective: predict 6m-2y from the least reliable data; heavyweight factors only) | opened 2026-11-08
```

## 2026-11-08T15:09:06+05:30 | kakazuya (Wolf) | 6722d3e9 T-121 started (dsh 20261108T093838Z-9477b891); T-118 worker reviewed
```diff
-- T-121 | OPEN | P1 | Document robustness: every page gets text (OCR part inside every profile build; today 6% of pages and 130 of 1,937 documents in a fresh build have no text) and a stratified canary of unseen companies x doc type x year that flags any drop in text coverage or extractor yield when a document format changes | accept: tests + canary table; Shivam | from: Shivam 8 Nov | opened 2026-11-08
+- T-121 | DOING Wolf | P1 | Document robustness: every page gets text (OCR part inside every profile build; today 6% of pages and 130 of 1,937 documents in a fresh build have no text) and a stratified canary of unseen companies x doc type x year that flags any drop in text coverage or extractor yield when a document format changes | accept: tests + canary table; Shivam | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T16:04:14+05:30 | kakazuya (Wolf) | e80350c4 T-122: frozen hand-labelled regression set across all companies read so far (brief)
```diff
+- T-122 | DOING Wolf | P1 | Frozen hand-labelled regression set across every company read so far (pilot10, unseen6, hold6, fresh6; ~250-300 rows keyed by content): every extractor or checker change must show zero right-rows quarantined and zero wrong-rows verified before merge | accept: score --all baseline table | from: Shivam 8 Nov (a fix for one company must not break another) | opened 2026-11-08
```

## 2026-11-08T16:19:00+05:30 | kakazuya (Wolf) | 03aeec2f T-121: OCR part in every build; stratified document-format canary (dsh 20261108T093838Z-9477b891)
```diff
-- T-121 | DOING Wolf | P1 | Document robustness: every page gets text (OCR part inside every profile build; today 6% of pages and 130 of 1,937 documents in a fresh build have no text) and a stratified canary of unseen companies x doc type x year that flags any drop in text coverage or extractor yield when a document format changes | accept: tests + canary table; Shivam | from: Shivam 8 Nov | opened 2026-11-08
+- T-121 | WAITING Shivam | P1 | Document robustness: every page gets text (OCR part inside every profile build; today 6% of pages and 130 of 1,937 documents in a fresh build have no text) and a stratified canary of unseen companies x doc type x year that flags any drop in text coverage or extractor yield when a document format changes | accept: tests + canary table; Shivam | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T16:24:26+05:30 | kakazuya (Wolf) | fdfa21b9 T-122: frozen hand-labelled regression set and scorer (dsh 20261108T103418Z-46655f94)
```diff
-- T-122 | DOING Wolf | P1 | Frozen hand-labelled regression set across every company read so far (pilot10, unseen6, hold6, fresh6; ~250-300 rows keyed by content): every extractor or checker change must show zero right-rows quarantined and zero wrong-rows verified before merge | accept: score --all baseline table | from: Shivam 8 Nov (a fix for one company must not break another) | opened 2026-11-08
+- T-122 | WAITING Shivam | P1 | Frozen hand-labelled regression set across every company read so far (pilot10, unseen6, hold6, fresh6; ~250-300 rows keyed by content): every extractor or checker change must show zero right-rows quarantined and zero wrong-rows verified before merge | accept: score --all baseline table | from: Shivam 8 Nov (a fix for one company must not break another) | opened 2026-11-08
```

## 2026-11-08T16:43:13+05:30 | kakazuya (Wolf) | 34022928 T-123, T-124 opened: document difficulty report; ask the database the harvested investor questions w
```diff
+- T-123 | OPEN | P1 | Document difficulty report, refreshed with every build: per doc type x company x filing year, text coverage (canary), verdict rates (verified / unverified / quarantined), top hard-failure reasons and hand-read accuracy from the regression labels; names which documents need work and which are clean. First cut 8 Nov: annual reports and transcripts ~30% of rows quarantined (unit_kind/page_unit; future_period/analyst speaker), decks/announcements/results 7-10%, XBRL segments 100% verified; hand reads: decks 53% right, annual reports 65%, results 83% | accept: Shivam | from: Shivam 8 Nov | opened 2026-11-08
+- T-124 | OPEN | P1 | Ask the database the harvested investor questions: for each company set, Opus reframes the Gemini questions (T-116 v2), a model answers them through the reality-data MCP, Opus grades right / partly / not held; every 'not held' gets a usefulness grade (does it touch a T-118 price-moving factor) and the raw source that would answer it; output feeds the source wishlist and the database priorities | accept: Shivam | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T16:56:37+05:30 | kakazuya (Wolf) | 548e63a8 T-125 opened: lock project rules in plugin/skills/MCP tools instead of start-of-session prompts
```diff
+- T-125 | OPEN | P1 | Lock project rules in code, not prompts: a project plugin/skills + MCP tools serve rulings, state and procedures on demand (rules(topic), state()), hooks/gates enforce the hard ones, so the always-loaded start shrinks. Measured 8 Nov: controllable start text ~80k chars (~20k tokens: STATE.md 33.6k chars despite the 40-line cap, MEMORY.md 17k, AGENTS.md 13.1k, RULINGS 12.5k, shared 3.8k) on top of the harness's fixed prompt and tool schemas | accept: Shivam | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T17:09:45+05:30 | kakazuya (Wolf) | 623779b8 T-126: index Drive files other machines uploaded into the T-102 manifest so RawStore and docs_collec
```diff
+- T-126 | DOING Wolf | P1 | Drive files uploaded by other machines enter the T-102 manifest (raw_to_drive.db): drive_index_unlisted list+index writes drive_file (path, md5, sha256) and local_file rows (status on_drive_unlisted) so RawStore/docs_collect find them; 8 Nov: 79,421 added, 282 of 308 FY25-27 docs of the 12 hold-out companies now visible | accept: test_drive_index_unlisted passes; docs_collect on fresh6/hold6 finds FY25-27 transcripts | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T17:34:42+05:30 | kakazuya (Wolf) | 84f42068 T-125: Shivam's Excel ticket board (reports/ticket_board.xlsx + html) synced on every task_board cha
```diff
-- T-126 | DOING Wolf | P1 | Drive files uploaded by other machines enter the T-102 manifest (raw_to_drive.db): drive_index_unlisted list+index writes drive_file (path, md5, sha256) and local_file rows (status on_drive_unlisted) so RawStore/docs_collect find them; 8 Nov: 79,421 added, 282 of 308 FY25-27 docs of the 12 hold-out companies now visible | accept: test_drive_index_unlisted passes; docs_collect on fresh6/hold6 finds FY25-27 transcripts | from: Shivam 8 Nov | opened 2026-11-08
+- T-126 | WAITING Shivam | P1 | Drive files uploaded by other machines enter the T-102 manifest (raw_to_drive.db): drive_index_unlisted list+index writes drive_file (path, md5, sha256) and local_file rows (status on_drive_unlisted) so RawStore/docs_collect find them; 8 Nov: 79,421 added, 282 of 308 FY25-27 docs of the 12 hold-out companies now visible | accept: test_drive_index_unlisted passes; docs_collect on fresh6/hold6 finds FY25-27 transcripts | from: Shivam 8 Nov | opened 2026-11-08
-- T-124 | OPEN | P1 | Ask the database the harvested investor questions: for each company set, Opus reframes the Gemini questions (T-116 v2), a model answers them through the reality-data MCP, Opus grades right / partly / not held; every 'not held' gets a usefulness grade (does it touch a T-118 price-moving factor) and the raw source that would answer it; output feeds the source wishlist and the database priorities | accept: Shivam | from: Shivam 8 Nov | opened 2026-11-08
-- T-125 | OPEN | P1 | Lock project rules in code, not prompts: a project plugin/skills + MCP tools serve rulings, state and procedures on demand (rules(topic), state()), hooks/gates enforce the hard ones, so the always-loaded start shrinks. Measured 8 Nov: controllable start text ~80k chars (~20k tokens: STATE.md 33.6k chars despite the 40-line cap, MEMORY.md 17k, AGENTS.md 13.1k, RULINGS 12.5k, shared 3.8k) on top of the harness's fixed prompt and tool schemas | accept: Shivam | from: Shivam 8 Nov | opened 2026-11-08
+- T-124 | DOING Wolf | P1 | Ask the database the harvested investor questions: for each company set, Opus reframes the Gemini questions (T-116 v2), a model answers them through the reality-data MCP, Opus grades right / partly / not held; every 'not held' gets a usefulness grade (does it touch a T-118 price-moving factor) and the raw source that would answer it; output feeds the source wishlist and the database priorities | accept: Shivam | from: Shivam 8 Nov | opened 2026-11-08
+- T-125 | WAITING Shivam | P1 | Lock project rules in code, not prompts: a project plugin/skills + MCP tools serve rulings, state and procedures on demand (rules(topic), state()), hooks/gates enforce the hard ones, so the always-loaded start shrinks. Measured 8 Nov: controllable start text ~80k chars (~20k tokens: STATE.md 33.6k chars despite the 40-line cap, MEMORY.md 17k, AGENTS.md 13.1k, RULINGS 12.5k, shared 3.8k) on top of the harness's fixed prompt and tool schemas | accept: Shivam | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T18:46:44+05:30 | kakazuya (Wolf) | c011609c T-127: merge dsh 20261108T124200Z-67ccd079 (worker_review and merge_tests merge gates, code_worker_l
```diff
++- T-127 | OPEN | P1 | Shivam's directions enforced by code, not Claude's memory: (1) one intake command records a new direction in RULINGS.md, the standing-rules sheet and memory, and opens a gate ticket when it relies on the model; (2) gates for the model-reliant rules that already failed once: merge refused without a worker_reviews row; start_worker refuses a third code worker; merge refused when a branch's tests are missing; full-run build parts refuse without a passing pilot checklist; raw files left on disk after a DB write flagged by the session-start hook. Measured 8 Nov: 9 of 25 rulings enforced by code | accept: standing_rules.xlsx shows each listed rule with a code gate; tests for each gate pass | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-08T20:53:43+05:30 | kakazuya (Wolf) | 5d336d8e T-128, T-129: tickets and briefs for the re-ask fixes (tech tool; KPI period, derived quarters, scal
```diff
+- T-129 | OPEN | P1 | KPI period and unit fixes from the re-ask: transcript sentence 'for the period ended <date>' gives the YTD period (SBI Life APE 117.5 is H1FY27, stored FY27); derive Q3/Q4 of flow KPIs from cumulative 9M/FY/H1 rows as labelled derived rows; number_check fails a crore figure whose source text states the same digits in million (MARUTI-127) | accept: python -m pytest reality_engine/tests/test_pilot3_kpi.py reality_engine/tests/test_pilot3_number_check.py -q | from: Shivam 8 Nov: fix the 70 partly answers | opened 2026-11-08
+- T-128 | OPEN | P1 | pilot3_tech tool: price reaction and technicals computed in code (day 0 from filing time after 15:30 = next session, gap held/fill vs previous close, Wilder RSI with divergence points, 50/200-day SMA and last crosses, volume spikes vs prior 20 sessions, range position); re-ask misses ETERNAL-066/067/133, KEC-064/070, HDFCBANK-068, SBILIFE-066, BAJFINANCE-056 | accept: python -m pytest reality_engine/tests/test_pilot3_tech.py -q | from: Shivam 8 Nov: fix the 70 partly answers | opened 2026-11-08
```

## 2026-11-08T21:05:34+05:30 | kakazuya (Wolf) | b15337c1 T-128: done (accept passed)
```diff
-- T-128 | OPEN | P1 | pilot3_tech tool: price reaction and technicals computed in code (day 0 from filing time after 15:30 = next session, gap held/fill vs previous close, Wilder RSI with divergence points, 50/200-day SMA and last crosses, volume spikes vs prior 20 sessions, range position); re-ask misses ETERNAL-066/067/133, KEC-064/070, HDFCBANK-068, SBILIFE-066, BAJFINANCE-056 | accept: python -m pytest reality_engine/tests/test_pilot3_tech.py -q | from: Shivam 8 Nov: fix the 70 partly answers | opened 2026-11-08
```

## 2026-11-08T22:06:48+05:30 | kakazuya (Wolf) | 059eb8cc T-129: done; data inventory refreshed at wrap-up
```diff
-- T-129 | OPEN | P1 | KPI period and unit fixes from the re-ask: transcript sentence 'for the period ended <date>' gives the YTD period (SBI Life APE 117.5 is H1FY27, stored FY27); derive Q3/Q4 of flow KPIs from cumulative 9M/FY/H1 rows as labelled derived rows; number_check fails a crore figure whose source text states the same digits in million (MARUTI-127) | accept: python -m pytest reality_engine/tests/test_pilot3_kpi.py reality_engine/tests/test_pilot3_number_check.py -q | from: Shivam 8 Nov: fix the 70 partly answers | opened 2026-11-08
```

## 2026-11-08T23:35:00+05:30 | kakazuya (Wolf) | 9d098b02 T-130: harvest briefs for unseen set u8 (company-specific + standard/conceptual questions)
```diff
+- T-130 | DOING Wolf | P1 | Unseen set u8 (ULTRACEMCO, TRENT, BEL, INDIGO, CIPLA, PERSISTENT, CHOLAFIN, TATACONSUM): agy harvests company-specific questions plus the sector's standard and conceptual analyst questions; Opus reframes; build the u8 store; DeepSeek answers; Opus grades by hand | accept: harvest CSVs verified (pages fetched); reframed set; u8 store built; answer_run_report u8 xlsx+csv with right/partly/wrong and root causes | from: Shivam 8 Nov 23:30 | opened 2026-11-08
```

## 2026-11-09T01:04:22+05:30 | kakazuya (Wolf) | ca7ae6d0 T-131..T-144: v2 store design tickets; pilot20 fetch started; STATE
```diff
+- T-139 | OPEN | P1 | Outside sources: rating-agency rationale notes (CRISIL, ICRA, CARE, India Ratings), official monthly industry data (auto sales, cement output, airline traffic), budget/PIB capex figures; dated, mapped to companies | accept: fetchers + raw on Drive for pilot20 and unseen sets; rating rationale held for >=90% of rated pilot20 companies | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-143 | OPEN | P1 | Pilot20: pick 10 new companies from sectors not in pilot10 (Shivam approves), fetch raw, build on the CURRENT design, harvest + reframe questions, answer and grade = baseline; then rebuild on v2 and re-ask = redesign delta | accept: baseline report and v2 report on the same question set; delta table right/partly/wrong | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-132 | OPEN | P1 | Table store: every printed table cell of decks, results, fact sheets, investor presentations and annual-report notes as a row (doc, page, row label, column header, period, unit, value); text layer first, HP OCR for scans, AI only where scripts fail and labelled | accept: on pilot20: >=95% of hand-sampled printed table cells captured with right header/period/unit (Opus sample 100 cells per doc type) | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-137 | OPEN | P1 | Guidance chain v2: every forward statement verbatim (speaker, call date, metric, period, range), linked to the target it revises; a call and its transcript are one event; delivered-vs-guided computed | accept: pilot20 guidance rows hand-read: >=95% right; Eternal/SBI Life/BEL guidance-history questions answered right | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-138 | OPEN | P1 | Annual-report notes as tables: guarantees, contingent liabilities, related parties (standalone and consolidated apart), FX sensitivity, ratings, segments; section detection per page | accept: Infosys parent guarantee, KEC FX sensitivity, HUL related parties answered from rows; pilot20 notes sample >=95% right | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-131 | OPEN | P1 | Design v2 schema contract (Opus, one owner): table store, label-to-metric map, periods + derived rows, calc catalog outputs, guidance chain, notes, events, disclosure map; every table names the investor questions it answers | accept: schema doc + DDL merged; each table maps to >=5 real failed questions; Shivam OK | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-133 | OPEN | P1 | Label dictionary: cluster row labels across companies into one metric per sector family; Opus approves each family once; review queue for frequent unmapped labels; fix sector map (UltraTech, Trent, IndiGo came out 'unknown') | accept: every pilot20 company has a sector family; >=90% of table rows in numeric tables map to a metric or sit in the queue | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-134 | OPEN | P1 | Period engine: exact start/end on every value; derive quarters from 9M/H1/FY, TTM, year-ago-as-known-at-date pairs as stored rows with formula and inputs; the model never subtracts | accept: SBI Life Q3/Q4 APE, TTM vs FY cases and all pilot cumulative-only series derived and checked against printed QoQ/YoY columns | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-135 | OPEN | P1 | Calc catalog: named formulas run by code (growth, share, contribution to increase, incremental ROCE, cash conversion, range position, fair P/B, implied growth, reactions) served by a tool; answers cite outputs | accept: every compute-class failure of the 600/72 re-asks reproduced right by a catalog call; tests per formula | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-136 | OPEN | P1 | Answer protocol + final checker: plan the facts a question needs, fetch each by tool, compose; checker refuses any figure not tied to a stored/derived row and any conclusion its own figures contradict | accept: replay of the 72 re-ask answers: every wrong/partly reading fault caught or fixed; zero right answers refused | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-140 | OPEN | P1 | Events table: dated policy, tariff, regulation, results, orders, M&A and rating events with effective dates and companies touched, so 'since <date>' chains are queries | accept: Maruti/Hindalco/KEC policy-chain questions answered with in-window events; T-117 circulars feed it | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-141 | OPEN | P1 | Disclosure map: per company, metric and period, whether it was disclosed; 'not disclosed' becomes a stored fact the answer can state | accept: the ~17 not-disclosed partials of the 72 re-ask answered as correct 'not disclosed, searched X' | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-142 | OPEN | P1 | Row checks for v2 rows: parts sum to totals, printed QoQ/YoY columns agree with derived rows, XBRL reconciliation; verified without a second source when they pass | accept: regression set 0 FAIL; hidden hold-out: zero wrong rows verified | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-144 | OPEN | P1 | Iteration loop: build pilot20 -> test on a fresh unseen set -> rebuild -> test on the next fresh unseen set; each unseen set used once, questions harvested by agy and reframed by Opus | accept: per-round answer_run_report xlsx; trend sheet across rounds | from: Shivam 9 Nov 01:10 | opened 2026-11-09
```

## 2026-11-09T01:20:15+05:30 | kakazuya (Wolf) | d536e699 T-145..T-153: v2 storage and build tickets
```diff
+- T-148 | OPEN | P1 | Incremental build by document, keyed by content hash: a new filing touches only its company file; reruns skip documents already done | accept: adding one filing rebuilds one company in minutes; full rerun with no new docs does no extraction | from: Shivam 9 Nov 01:25 | opened 2026-11-09
+- T-152 | OPEN | P1 | Golden tables per type: ~50 hand-checked tables per type (deck KPI, segment note, FX sensitivity, results P&L); every extractor change scored on them before merge | accept: golden sets on Drive; merge gate fails on any lost right cell | from: Shivam 9 Nov 01:25 | opened 2026-11-09
+- T-153 | OPEN | P1 | Warm MCP server for v2: cached file handles and connections so tool start-up does not dominate the 1 s budget | accept: end-to-end tool call p95 <=1 s on pilot20 | from: Shivam 9 Nov 01:25 | opened 2026-11-09
+- T-147 | OPEN | P1 | Parse once, map many: keep each document's parsed output (tables, sections, statements) beside the store so later schema versions re-map without re-reading PDFs from Drive | accept: v2 rebuild of pilot20 from parsed outputs with zero PDF downloads; parse step skipped on rerun | from: Shivam 9 Nov 01:25 | opened 2026-11-09
+- T-145 | OPEN | P1 | v2 storage layout: per-company SQLite files (facts + evidence + full-text), DuckDB over Parquet for market series and cross-company screens, a catalog that routes company/ISIN to its file; atomic per-company swap | accept: lookup p95 <=5 ms, per-company text search p95 <=50 ms, cross-company screen p95 <=1 s on a 500 GB synthetic scale test; swap of one company never touches another | from: Shivam 9 Nov 01:25 | opened 2026-11-09
+- T-146 | OPEN | P1 | One fact, many sources: a figure printed in deck, results and press release is one fact row with several evidence links; agreement count feeds row checks; derived rows store formula + input ids only; preferred figure elected ahead | accept: no duplicate fact keys in pilot20; corroboration count populated; derived rows recompute exactly from inputs | from: Shivam 9 Nov 01:25 | opened 2026-11-09
+- T-149 | OPEN | P1 | Entities for segments and subsidiaries (Blinkit, Novelis, BHFL, Westside/Zudio, SAE Towers) linked to the parent; every fact names its entity | accept: segment-as-total and subsidiary-PAT-as-company errors absent in the pilot20 hand sample | from: Shivam 9 Nov 01:25 | opened 2026-11-09
+- T-150 | OPEN | P1 | Units normalised at write: base-unit value plus the original unit text and scale; read side never converts | accept: zero scale errors in pilot20 sample; ar_facts mn/lakh cases covered by tests | from: Shivam 9 Nov 01:25 | opened 2026-11-09
+- T-151 | OPEN | P1 | Question templates compiled to fact keys: the 1,305 pilot10 questions and harvested sets become templates naming the facts they need; a script reports which templates the store can fill before any answering | accept: coverage report per company set; >=95% of templates fillable or marked not-disclosed before a full run | from: Shivam 9 Nov 01:25 | opened 2026-11-09
```

## 2026-11-09T01:27:29+05:30 | kakazuya (Wolf) | 75f43c9b T-154: embedding bake-off ticket
```diff
+- T-154 | OPEN | P2 | Embedding model bake-off for v2 semantic search: current Nemotron 8B vs finance-trained (Fin-E5 from FinMTEB, voyage-finance-2 only with Shivam's OK for paid) vs Qwen3-Embedding vs a model fine-tuned on our own graded question-to-page pairs; scored on our own Indian filings | accept: eval set of >=300 graded question->correct page/passage pairs from pilot10 runs; recall@5/@20 and latency per model; pick by measurement | from: Shivam 9 Nov 01:35 | opened 2026-11-09
```

## 2026-11-09T01:50:02+05:30 | kakazuya (Wolf) | 53c5c48e T-131: v2 schema contract draft (DDL + question map); T-143 pilot20 answer briefs
```diff
-- T-143 | OPEN | P1 | Pilot20: pick 10 new companies from sectors not in pilot10 (Shivam approves), fetch raw, build on the CURRENT design, harvest + reframe questions, answer and grade = baseline; then rebuild on v2 and re-ask = redesign delta | accept: baseline report and v2 report on the same question set; delta table right/partly/wrong | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-143 | DOING Wolf | P1 | Pilot20: pick 10 new companies from sectors not in pilot10 (Shivam approves), fetch raw, build on the CURRENT design, harvest + reframe questions, answer and grade = baseline; then rebuild on v2 and re-ask = redesign delta | accept: baseline report and v2 report on the same question set; delta table right/partly/wrong | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-131 | OPEN | P1 | Design v2 schema contract (Opus, one owner): table store, label-to-metric map, periods + derived rows, calc catalog outputs, guidance chain, notes, events, disclosure map; every table names the investor questions it answers | accept: schema doc + DDL merged; each table maps to >=5 real failed questions; Shivam OK | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-131 | DOING Wolf | P1 | Design v2 schema contract (Opus, one owner): table store, label-to-metric map, periods + derived rows, calc catalog outputs, guidance chain, notes, events, disclosure map; every table names the investor questions it answers | accept: schema doc + DDL merged; each table maps to >=5 real failed questions; Shivam OK | from: Shivam 9 Nov 01:10 | opened 2026-11-09
```

## 2026-11-09T01:51:26+05:30 | kakazuya (Wolf) | f293072f T-135: calc catalog worker brief
```diff
-- T-135 | OPEN | P1 | Calc catalog: named formulas run by code (growth, share, contribution to increase, incremental ROCE, cash conversion, range position, fair P/B, implied growth, reactions) served by a tool; answers cite outputs | accept: every compute-class failure of the 600/72 re-asks reproduced right by a catalog call; tests per formula | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-135 | DOING Wolf | P1 | Calc catalog: named formulas run by code (growth, share, contribution to increase, incremental ROCE, cash conversion, range position, fair P/B, implied growth, reactions) served by a tool; answers cite outputs | accept: every compute-class failure of the 600/72 re-asks reproduced right by a catalog call; tests per formula | from: Shivam 9 Nov 01:10 | opened 2026-11-09
```

## 2026-11-09T15:31:50+05:30 | kakazuya (Wolf) | d86b66f3 T-154: semantic query cache falls back to ./.tmp in a sandboxed worker; embed client retries read ti
```diff
+- T-155 | OPEN | P1 | Pilot builds keep price history from 2019 (price_start), not from window_start: price_delivery, index_price, valuation_daily | accept: fixture build with window_start 2023-10-01 keeps 2020 price + index rows, drops 2020 fin rows; valuation_daily 2020 has close, NULL ratios without inputs; tests pass | from: STATE next action 3, Shivam OK 9 Nov 15:10 | opened 2026-11-09
```

## 2026-11-09T16:34:41+05:30 | kakazuya (Wolf) | 07fb0808 T-131: Shivam OK on the v2 schema contract (semantic alongside, free outside sources kept lean); T-1
```diff
-- T-155 | OPEN | P1 | Pilot builds keep price history from 2019 (price_start), not from window_start: price_delivery, index_price, valuation_daily | accept: fixture build with window_start 2023-10-01 keeps 2020 price + index rows, drops 2020 fin rows; valuation_daily 2020 has close, NULL ratios without inputs; tests pass | from: STATE next action 3, Shivam OK 9 Nov 15:10 | opened 2026-11-09
+- T-155 | DOING Wolf | P1 | Pilot builds keep price history from 2019 (price_start), not from window_start: price_delivery, index_price, valuation_daily | accept: fixture build with window_start 2023-10-01 keeps 2020 price + index rows, drops 2020 fin rows; valuation_daily 2020 has close, NULL ratios without inputs; tests pass | from: STATE next action 3, Shivam OK 9 Nov 15:10 | opened 2026-11-09
-- T-131 | DOING Wolf | P1 | Design v2 schema contract (Opus, one owner): table store, label-to-metric map, periods + derived rows, calc catalog outputs, guidance chain, notes, events, disclosure map; every table names the investor questions it answers | accept: schema doc + DDL merged; each table maps to >=5 real failed questions; Shivam OK | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-134 | OPEN | P1 | Period engine: exact start/end on every value; derive quarters from 9M/H1/FY, TTM, year-ago-as-known-at-date pairs as stored rows with formula and inputs; the model never subtracts | accept: SBI Life Q3/Q4 APE, TTM vs FY cases and all pilot cumulative-only series derived and checked against printed QoQ/YoY columns | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-134 | DOING Wolf | P1 | Period engine: exact start/end on every value; derive quarters from 9M/H1/FY, TTM, year-ago-as-known-at-date pairs as stored rows with formula and inputs; the model never subtracts | accept: SBI Life Q3/Q4 APE, TTM vs FY cases and all pilot cumulative-only series derived and checked against printed QoQ/YoY columns | from: Shivam 9 Nov 01:10 | opened 2026-11-09
```

## 2026-11-09T17:24:40+05:30 | kakazuya (Wolf) | 055a03e1 T-132, T-139: workers started; STATE trimmed to done/pending
```diff
-- T-139 | OPEN | P1 | Outside sources: rating-agency rationale notes (CRISIL, ICRA, CARE, India Ratings), official monthly industry data (auto sales, cement output, airline traffic), budget/PIB capex figures; dated, mapped to companies | accept: fetchers + raw on Drive for pilot20 and unseen sets; rating rationale held for >=90% of rated pilot20 companies | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-139 | DOING Wolf | P1 | Outside sources: rating-agency rationale notes (CRISIL, ICRA, CARE, India Ratings), official monthly industry data (auto sales, cement output, airline traffic), budget/PIB capex figures; dated, mapped to companies | accept: fetchers + raw on Drive for pilot20 and unseen sets; rating rationale held for >=90% of rated pilot20 companies | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-132 | OPEN | P1 | Table store: every printed table cell of decks, results, fact sheets, investor presentations and annual-report notes as a row (doc, page, row label, column header, period, unit, value); text layer first, HP OCR for scans, AI only where scripts fail and labelled | accept: on pilot20: >=95% of hand-sampled printed table cells captured with right header/period/unit (Opus sample 100 cells per doc type) | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-132 | DOING Wolf | P1 | Table store: every printed table cell of decks, results, fact sheets, investor presentations and annual-report notes as a row (doc, page, row label, column header, period, unit, value); text layer first, HP OCR for scans, AI only where scripts fail and labelled | accept: on pilot20: >=95% of hand-sampled printed table cells captured with right header/period/unit (Opus sample 100 cells per doc type) | from: Shivam 9 Nov 01:10 | opened 2026-11-09
```

## 2026-11-09T17:41:48+05:30 | kakazuya (Wolf) | c2d37c28 T-154: strict grade of 50 re-ask answers; point-in-time leak ticket
```diff
+- T-156 | OPEN | P1 | Point-in-time leak: 14 of 120 re-ask answers quote a call transcript filed 2-3 days after the question date (read via pilot3_sql on doc_page, which has no as_of filter); add an as_of guard to sql/doc_page reads and set call-question as_of to the transcript filing date | accept: re-run strict check: 0 quotes from pages known after as_of on the 120 re-ask answers; sql with as_of drops later doc_page rows; test | from: Opus strict grading 9 Nov | opened 2026-11-09
```

## 2026-11-09T18:43:38+05:30 | kakazuya (Wolf) | d7872009 T-156/T-157: partly-answer fix plan in STATE
```diff
+- T-157 | OPEN | P1 | Missing call transcripts: resolve the links in one-page transcript cover letters (Adani Ports 13, IHCL 2, Havells 1) and fetch calls with no transcript doc (Pidilite Q2 FY27), PIT known_at, into the pilot stores | accept: copy run adds text for >=12 of 16 linked stubs; tests pass; the 19 source-missing pilot20 answers re-asked | from: Shivam 9 Nov 18:40: fix the partly answers | opened 2026-11-09
```

## 2026-11-09T20:08:07+05:30 | kakazuya (Wolf) | 03a7ec78 T-156: ruling 'data not found + nearest supporting point'; pilot20 final 229/230; consolidated repor
```diff
+- T-158 | OPEN | P2 | Gate for ruling: Unpublished data (9 Nov): the answer says 'data not found' with what was searched, plus the nearest supporting point lab | accept: standing_rules.xlsx shows a code gate for it | from: ruling intake | opened 2026-11-09
```

## 2026-11-09T20:27:23+05:30 | kakazuya (Wolf) | d910b8a0 T-155, T-157: closed on their test accepts (work merged and applied 9 Nov)
```diff
-- T-155 | DOING Wolf | P1 | Pilot builds keep price history from 2019 (price_start), not from window_start: price_delivery, index_price, valuation_daily | accept: fixture build with window_start 2023-10-01 keeps 2020 price + index rows, drops 2020 fin rows; valuation_daily 2020 has close, NULL ratios without inputs; tests pass | from: STATE next action 3, Shivam OK 9 Nov 15:10 | opened 2026-11-09
-- T-157 | OPEN | P1 | Missing call transcripts: resolve the links in one-page transcript cover letters (Adani Ports 13, IHCL 2, Havells 1) and fetch calls with no transcript doc (Pidilite Q2 FY27), PIT known_at, into the pilot stores | accept: copy run adds text for >=12 of 16 linked stubs; tests pass; the 19 source-missing pilot20 answers re-asked | from: Shivam 9 Nov 18:40: fix the partly answers | opened 2026-11-09
```

## 2026-11-09T20:47:10+05:30 | kakazuya (Wolf) | d2d4b024 T-133: label map worker started; STATE
```diff
-- T-133 | OPEN | P1 | Label dictionary: cluster row labels across companies into one metric per sector family; Opus approves each family once; review queue for frequent unmapped labels; fix sector map (UltraTech, Trent, IndiGo came out 'unknown') | accept: every pilot20 company has a sector family; >=90% of table rows in numeric tables map to a metric or sit in the queue | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-133 | DOING Wolf | P1 | Label dictionary: cluster row labels across companies into one metric per sector family; Opus approves each family once; review queue for frequent unmapped labels; fix sector map (UltraTech, Trent, IndiGo came out 'unknown') | accept: every pilot20 company has a sector family; >=90% of table rows in numeric tables map to a metric or sit in the queue | from: Shivam 9 Nov 01:10 | opened 2026-11-09
```

## 2026-11-09T23:50:09+05:30 | kakazuya (Wolf) | 5345525a T-157: BSE announcements read every page; meet-outcome PDFs that read as a call count as transcripts
```diff
+- T-159 | OPEN | P1 | Retype held call transcripts filed under announcement/results: doc type from page text (Moderator: on first pages, >=3 pages) beats the BSE category in docs_collect/build; 16 docs across p20 (HAVELLS 6, INDHOTEL 1), u8 (CHOLAFIN 3, CIPLA 1, ULTRACEMCO 1), q12 (KIMS, SAIL, UBL 2); then statements rebuilt for them | accept: the Moderator query returns 0 non-transcript docs on p20, u8, q12; HAVELLS Q1/Q2/Q3 FY25 calls answer through pilot3_statements | from: Wolf 9 Nov (T-157 follow-up evidence) | opened 2026-11-09
```

## 2026-11-10T00:01:40+05:30 | kakazuya (Wolf) | 397f4ccd T-160: Opus headless analysis launcher; n10 unseen set ticket; u8/q12 transcripts applied (docs)
```diff
+- T-160 | OPEN | P1 | Unseen set n10 (AUBANK, BALRAMCHIN, SRF, LT, DMART, TATAPOWER, ICICIGI, DIXON, JUBLFOOD, MCX): agy harvests analyst questions whose answers sit in company filings/decks/calls but need extraction, multi-period structuring or computation (no price/valuation/opinion questions); Opus filters and reframes; build n10 store; ask + grade; every miss names the table/KPI/compute to build | accept: harvest CSV with verified source URLs and data_needed tags; Opus-filtered set; n10 store; answer_run_report xlsx+csv with root causes split held-not-queryable vs not-held | from: Shivam 10 Nov 00:10 | opened 2026-11-09
```

## 2026-11-10T00:16:20+05:30 | kakazuya (Wolf) | 50ae207d T-161..T-166: tickets from the Opus held-not-queryable audit (82/106 answerable from held docs); STA
```diff
+- T-162 | OPEN | P1 | SHP known_at is our reload time, not the exchange filing time: strict as_of drops quarters already public; take known_at from the NSE/BSE filing timestamp | accept: shp_category/shp_holder known_at equals the filing dissemination time for every row on p20/u8/q12; strict as_of re-ask of the SHP questions loses none | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
+- T-161 | OPEN | P1 | Misdated documents: transcripts whose printed call date is years before filing_date (Tata Elxsi 2018 and APL Apollo/Edelweiss 2016 calls stored as Aug 2026; 6 found) give confident wrong answers; doc date from the printed call date, mismatch > 120 days quarantined | accept: 0 transcripts on p20/u8/q12 whose first-page call date differs from filing_date by >120 days stay served; Tata Elxsi 'JLR 24%' no longer answers as of 2026 | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
+- T-166 | OPEN | P2 | Guidance table attributes outside forecasts as company guidance (ICRA 19-21% HFC industry stored as Cholamandalam guidance; management said 22-23%); speaker/source check before a guidance row | accept: 0 guidance rows whose quote names a rating agency/industry forecast instead of management on p20/u8/q12 | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
+- T-163 | OPEN | P1 | Segment and business-line table from AR segment notes and deck slides (segment, vertical, cluster, brand, subsidiary) with an alias map (NourishCo = RTD); 14 audit questions | accept: the 14 segment questions of the held audit answer by one query on u8/q12 | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
+- T-164 | OPEN | P1 | Call statements: tag named programmes/projects/counterparties and real topics (not 'other'), split at speaker turns never mid-answer, view of analyst questions across the last N calls; 18 audit questions | accept: the 18 statement questions of the held audit answer through pilot3_statements on u8/q12 | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
+- T-165 | OPEN | P2 | Answer routing: 11 audit questions failed although the table held the answer (SHP FPI/MF split, Vodafone Idea GoI 49%, Cholamandalam NIM/credit cost/cost of funds); fix tool routing and the answer brief | accept: the 11 routing questions answer on re-ask with the standard brief | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
```

## 2026-11-10T10:25:00+05:30 | kakazuya (Wolf) | 3eac8630 T-162: SHP known_at takes the earlier PM-safe file-name stamp when the index broadcast is a late re-
```diff
-- T-162 | OPEN | P1 | SHP known_at is our reload time, not the exchange filing time: strict as_of drops quarters already public; take known_at from the NSE/BSE filing timestamp | accept: shp_category/shp_holder known_at equals the filing dissemination time for every row on p20/u8/q12; strict as_of re-ask of the SHP questions loses none | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
+- T-162 | DOING Wolf | P1 | SHP known_at is our reload time, not the exchange filing time: strict as_of drops quarters already public; take known_at from the NSE/BSE filing timestamp | accept: shp_category/shp_holder known_at equals the filing dissemination time for every row on p20/u8/q12; strict as_of re-ask of the SHP questions loses none | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
```

## 2026-11-10T11:15:03+05:30 | kakazuya (Wolf) | 2febb583 Session close sweep: no-headless-Opus ruling, site_documents folders documented, inventory regenerat
```diff
-- T-165 | OPEN | P2 | Answer routing: 11 audit questions failed although the table held the answer (SHP FPI/MF split, Vodafone Idea GoI 49%, Cholamandalam NIM/credit cost/cost of funds); fix tool routing and the answer brief | accept: the 11 routing questions answer on re-ask with the standard brief | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
+- T-165 | DOING Wolf | P2 | Answer routing: 11 audit questions failed although the table held the answer (SHP FPI/MF split, Vodafone Idea GoI 49%, Cholamandalam NIM/credit cost/cost of funds); fix tool routing and the answer brief | accept: the 11 routing questions answer on re-ask with the standard brief | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
```

## 2026-11-10T16:05:15+05:30 | kakazuya (Eagle) | b442de99 T-167..T-170: unseen s10 set (sparse-disclosure + mid/small deck companies), raw fetch, website fetc
```diff
+- T-168 | OPEN | P1 | Raw fetch for the s10 set: every exchange filing since FY24 (results, annual reports, announcements, SHP, credit ratings) plus company-website investor pages for the 5 sparse-disclosure companies (press releases, AGM speeches, presentations not filed); raw to Drive via raw_store | accept: coverage_report for s10 shows each doc family per quarter; website pages fetched for the 5 sparse companies with source_url and fetched_at | from: Shivam 10 Nov 16:00 | opened 2026-11-10
+- T-169 | OPEN | P2 | Company-website fetcher: generic investor-relations page crawler (no per-company code) that finds results, presentations, AGM/press material on the company's own site, dates each item from the page or PDF, and dedupes against exchange filings by hash | accept: fetcher tests pass; on the 5 sparse s10 companies it finds every item listed on their IR pages with a date; 0 duplicates of exchange filings | from: Shivam 10 Nov 16:00 | opened 2026-11-10
+- T-170 | OPEN | P1 | s10 answer baseline: build stores for s10 on the current design, harvest verified investor questions per company (Gemini), reframe to our data incl. level-2 peer questions against held peers, answer through the reality-data MCP with calls and seconds timed per answer, grade by hand rules; report accuracy split by disclosure type (sparse vs deck) | accept: answer_run_report xlsx with right/partly/wrong per company and per disclosure type, calls per answer and p50/p95 seconds; root cause per miss | from: Shivam 10 Nov 16:00 | opened 2026-11-10
+- T-167 | OPEN | P1 | Unseen-set selection (s10): 10 new companies chosen from data, not from memory: 5 sparse-disclosure (no call transcripts and no investor decks in the last 8 quarters; annual reports, quarterly results and announcements only), 5 mid/small caps that publish decks (calls optional); sectors not in p20/u8/q12/n10/pilot10, or else direct peers of held companies so level-2 peer questions can be tested; mcap spread across mid and small; Shivam approves the list | accept: reports/ list of 10 with sector, mcap bucket, doc-type counts per quarter from the filings index, peer link where used; Shivam's approval recorded | from: Shivam 10 Nov 16:00 | opened 2026-11-10
```

## 2026-11-10T16:11:17+05:30 | kakazuya (Eagle) | cbcb03ea T-171 per-worker RAM cut (measured 0.8 GB baseline); CHOLAFIN KPI brief
```diff
+- T-171 | OPEN | P1 | Cut per-worker RAM. Measured 10 Nov: each dsh worker holds ~0.8 GB before it runs anything: dsh node 230 MB, sandbox+subprocess node 130 MB, its own reality-data MCP 210 MB, code-tools MCP 77 MB, data-gather MCP 76 MB, harness+supervisor python 70 MB; tests/builds it runs add the 1-2 GB spikes. Fix: (1) code workers start without data-gather (data jobs keep it); (2) one shared reality-data server for all workers (HTTP transport) instead of one per worker, or lazy imports + capped caches; (3) workers run heavy builds/tests through a RAM-capped runner (one heavy job at a time); measure before/after with 4 workers | accept: per-worker baseline RAM measured <=450 MB with 4 workers running; tools unchanged for workers (reality-data, code-tools calls still pass); report before/after in docs/DEVELOPER_GUIDE.md | from: Shivam 10 Nov 16:30 (RAM, not CPU, is the limit) | opened 2026-11-10
```

## 2026-11-10T19:29:41+05:30 | kakazuya (Eagle) | 73ab9e3d T-167 done (Shivam approved s10 list; D:/RealityEngine/s10/universe_s10.csv); T-168 started
```diff
-- T-168 | OPEN | P1 | Raw fetch for the s10 set: every exchange filing since FY24 (results, annual reports, announcements, SHP, credit ratings) plus company-website investor pages for the 5 sparse-disclosure companies (press releases, AGM speeches, presentations not filed); raw to Drive via raw_store | accept: coverage_report for s10 shows each doc family per quarter; website pages fetched for the 5 sparse companies with source_url and fetched_at | from: Shivam 10 Nov 16:00 | opened 2026-11-10
+- T-168 | DOING Eagle | P1 | Raw fetch for the s10 set: every exchange filing since FY24 (results, annual reports, announcements, SHP, credit ratings) plus company-website investor pages for the 5 sparse-disclosure companies (press releases, AGM speeches, presentations not filed); raw to Drive via raw_store | accept: coverage_report for s10 shows each doc family per quarter; website pages fetched for the 5 sparse companies with source_url and fetched_at | from: Shivam 10 Nov 16:00 | opened 2026-11-10
-- T-167 | OPEN | P1 | Unseen-set selection (s10): 10 new companies chosen from data, not from memory: 5 sparse-disclosure (no call transcripts and no investor decks in the last 8 quarters; annual reports, quarterly results and announcements only), 5 mid/small caps that publish decks (calls optional); sectors not in p20/u8/q12/n10/pilot10, or else direct peers of held companies so level-2 peer questions can be tested; mcap spread across mid and small; Shivam approves the list | accept: reports/ list of 10 with sector, mcap bucket, doc-type counts per quarter from the filings index, peer link where used; Shivam's approval recorded | from: Shivam 10 Nov 16:00 | opened 2026-11-10
```

## 2026-11-10T20:36:13+05:30 | kakazuya (Eagle) | 4a7ef0b9 Ruling (Shivam 10 Nov): score only on frozen sets; T-172 s10 frozen half, T-173 s20 exam set; Fable 
```diff
+- T-172 | OPEN | P1 | Frozen hold-out for s10 (before T-170 answers anything): split each s10 company's verified question set at random (seed fixed, recorded) into a dev half that may drive fixes and a frozen half that no worker, brief or fix may read until the final measurement; store the frozen half outside the repo with a hash; the score reported for s10 is the frozen half's | accept: split file + hash recorded; a test fails if any brief or worker log names a frozen question id | from: Shivam 10 Nov 20:40 | opened 2026-11-10
+- T-173 | OPEN | P1 | s20 exam set: 20 companies never used for any fix (micro caps, BSE-only companies without a sector label, sectors not yet held, a few sparse filers), chosen from data like T-167; questions harvested and frozen before any build; its score is the reported any-company number and no fix may be drawn from its questions | accept: s20 list approved by Shivam; questions frozen with hash before the first build; first answer run reported with calls and seconds per answer | from: Shivam 10 Nov 20:40 | opened 2026-11-10
```

## 2026-11-10T20:50:25+05:30 | kakazuya (Eagle) | 9114a81e Close merged tickets T-159, T-161, T-162, T-165, T-166; T-163 r6 brief; review log
```diff
-- T-162 | DOING Wolf | P1 | SHP known_at is our reload time, not the exchange filing time: strict as_of drops quarters already public; take known_at from the NSE/BSE filing timestamp | accept: shp_category/shp_holder known_at equals the filing dissemination time for every row on p20/u8/q12; strict as_of re-ask of the SHP questions loses none | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
-- T-159 | OPEN | P1 | Retype held call transcripts filed under announcement/results: doc type from page text (Moderator: on first pages, >=3 pages) beats the BSE category in docs_collect/build; 16 docs across p20 (HAVELLS 6, INDHOTEL 1), u8 (CHOLAFIN 3, CIPLA 1, ULTRACEMCO 1), q12 (KIMS, SAIL, UBL 2); then statements rebuilt for them | accept: the Moderator query returns 0 non-transcript docs on p20, u8, q12; HAVELLS Q1/Q2/Q3 FY25 calls answer through pilot3_statements | from: Wolf 9 Nov (T-157 follow-up evidence) | opened 2026-11-09
-- T-161 | OPEN | P1 | Misdated documents: transcripts whose printed call date is years before filing_date (Tata Elxsi 2018 and APL Apollo/Edelweiss 2016 calls stored as Aug 2026; 6 found) give confident wrong answers; doc date from the printed call date, mismatch > 120 days quarantined | accept: 0 transcripts on p20/u8/q12 whose first-page call date differs from filing_date by >120 days stay served; Tata Elxsi 'JLR 24%' no longer answers as of 2026 | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
-- T-166 | OPEN | P2 | Guidance table attributes outside forecasts as company guidance (ICRA 19-21% HFC industry stored as Cholamandalam guidance; management said 22-23%); speaker/source check before a guidance row | accept: 0 guidance rows whose quote names a rating agency/industry forecast instead of management on p20/u8/q12 | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
-- T-165 | DOING Wolf | P2 | Answer routing: 11 audit questions failed although the table held the answer (SHP FPI/MF split, Vodafone Idea GoI 49%, Cholamandalam NIM/credit cost/cost of funds); fix tool routing and the answer brief | accept: the 11 routing questions answer on re-ask with the standard brief | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
```

## 2026-11-10T21:54:54+05:30 | kakazuya (Eagle) | 888843fb Shivam 10 Nov board decisions: close T-023, T-116, T-122, T-125, T-126; T-021/T-022 become rulings (
```diff
-One row per line, kept in its section: `- T-014 | DOING Wolf | P1 | title | accept: <command or Shivam> | from: <source> | opened 2026-11-01`
-Statuses: `OPEN`, `LOOKING`, `DOING <owner>`, `WAITING <who>`; priorities `P1`-`P3`. No `|` inside a field.
-Closed rows move to `tasks/TASKS_DONE.md`: `python -m reality_engine.scripts.task_board done T-014`.
-Card and full list: `python -m reality_engine.scripts.task_board card` / `list`.
+One row per line, kept in its section.
-- T-021 | LOOKING | P3 | Check if still open: PIB phase 2, Hindi, Urdu and regional offices | accept: Shivam | from: tasks/PIPELINE_TODO.md A2 | opened 2026-11-02
-- T-022 | LOOKING | P3 | Check if still open: policy register at scale, with stage threads and company mapping | accept: Shivam | from: tasks/PIPELINE_TODO.md A3 | opened 2026-11-02
-- T-023 | LOOKING | P3 | Check if finished: shareholding and pledge backfill, marked running on 19 Oct | accept: Shivam | from: tasks/PIPELINE_TODO.md B3 | opened 2026-11-02
-- T-126 | WAITING Shivam | P1 | Drive files uploaded by other machines enter the T-102 manifest (raw_to_drive.db): drive_index_unlisted list+index writes drive_file (path, md5, sha256) and local_file rows (status on_drive_unlisted) so RawStore/docs_collect find them; 8 Nov: 79,421 added, 282 of 308 FY25-27 docs of the 12 hold-out companies now visible | accept: test_drive_index_unlisted passes; docs_collect on fresh6/hold6 finds FY25-27 transcripts | from: Shivam 8 Nov | opened 2026-11-08
+- T-174 | OPEN | P1 | Policy-to-company impact map: each held policy/regulation row linked to the companies it touches with a verdict (advantageous, disadvantageous, neutral), the reason, and a quantification where the filings or the policy text give one | accept: Shivam: approves the 40-link sample | from: Shivam 10 Nov (T-022) | opened 2026-11-10
+- T-175 | OPEN | P1 | Jumbled text-layer detector: flag pages whose text layer exists but reads as garbage (broken encoding, glued words, reversed or scattered characters) so only those and textless pages go to HP OCR | accept: Shivam: approves the 100-page labelled check | from: Shivam 10 Nov (T-121) | opened 2026-11-10
-- T-116 | WAITING Shivam | P2 | Investor question harvest: agy (Gemini 3.8 Flash medium) searches Google and YouTube for questions investors ask about each test company; Opus reframes them inside our data's bounds, marks blind spots (questions our bank does not ask) | accept: Shivam reviews the reframed list | from: Shivam 8 Nov | opened 2026-11-08
-- T-121 | WAITING Shivam | P1 | Document robustness: every page gets text (OCR part inside every profile build; today 6% of pages and 130 of 1,937 documents in a fresh build have no text) and a stratified canary of unseen companies x doc type x year that flags any drop in text coverage or extractor yield when a document format changes | accept: tests + canary table; Shivam | from: Shivam 8 Nov | opened 2026-11-08
-- T-122 | WAITING Shivam | P1 | Frozen hand-labelled regression set across every company read so far (pilot10, unseen6, hold6, fresh6; ~250-300 rows keyed by content): every extractor or checker change must show zero right-rows quarantined and zero wrong-rows verified before merge | accept: score --all baseline table | from: Shivam 8 Nov (a fix for one company must not break another) | opened 2026-11-08
-- T-125 | WAITING Shivam | P1 | Lock project rules in code, not prompts: a project plugin/skills + MCP tools serve rulings, state and procedures on demand (rules(topic), state()), hooks/gates enforce the hard ones, so the always-loaded start shrinks. Measured 8 Nov: controllable start text ~80k chars (~20k tokens: STATE.md 33.6k chars despite the 40-line cap, MEMORY.md 17k, AGENTS.md 13.1k, RULINGS 12.5k, shared 3.8k) on top of the harness's fixed prompt and tool schemas | accept: Shivam | from: Shivam 8 Nov | opened 2026-11-08
```

## 2026-11-10T22:00:58+05:30 | kakazuya (Eagle) | 6b6323a9 Ruling (Shivam 10 Nov): factor rewards are time-varying, recomputed per stock/sector/regime with the
```diff
-- T-118 | WAITING Shivam | P1 | Factor weight study: which held, reliable facts explain 6-month, 1-year and 2-year forward returns across the universe (earnings and PAT growth, guidance raised or cut, margin trend, ROE/ROCE, valuation, net debt change, promoter/FPI/MF holding change, pledges, insider buys), measured as rank correlation per period with sector and size controls; the result ranks which extractions to finish first and which to drop | accept: Shivam | from: Shivam 8 Nov (objective: predict 6m-2y from the least reliable data; heavyweight factors only) | opened 2026-11-08
+- T-176 | OPEN | P1 | Recurring factor-reward engine: at every rebalance date and for every stock, sector and regime, measure which held factors were rewarded over the following 6m/12m/24m (point in time), store the per-date results, and report the statistical mode of the rewarded factors per stock/sector/regime and how that mode shifts over time | accept: Shivam: reviews the mode report | from: Shivam 10 Nov (T-118 follow-up) | opened 2026-11-10
```

## 2026-11-10T22:01:54+05:30 | kakazuya (Eagle) | 29a70759 Close 31 triaged tickets approved by Shivam 10 Nov (17 done, 12 superseded, T-095 duplicate, T-075 r
```diff
-- T-005 | OPEN | P2 | Cap code workers at 2 and refuse new ones while a branch is over 24 hours old | accept: python -m pytest reality_engine/tests/test_worker_limits.py -q | from: enforcement plan | opened 2026-11-02
-- T-006 | OPEN | P2 | Find why the full test suite reaches 7.5 GB; run it on the HP, not the MSI | accept: Shivam | from: STATE 1 Nov | opened 2026-11-02
-- T-042 | OPEN | P1 | Rule and chain-of-command ledger: log every gate block, budget overrun, bypass and who did the work; daily report by rule of enforced, sidelined and unmeasured | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
-- T-044 | OPEN | P1 | Catch finished, stalled and failed jobs in code, at any effort level: list_workers shows the newest and running first, and a status command feeds a hook on every prompt | accept: python -m pytest reality_engine/tests/test_job_watch.py -q | from: Shivam 2 Nov | opened 2026-11-02
-- T-075 | OPEN | P1 | Prototype next-round in the same worker session: Opus reviews finished output, then guides it in that session. --followup-wait keeps a worker waiting only up to 3600 s and HP has no channel; find or build resume after that, and measure tokens and hand-read score | accept: Shivam | from: Paper pointer 2, Shivam 5 Nov | opened 2026-11-05
-- T-076 | OPEN | P2 | Trial: two KPI fix rounds run strictly one at a time, answer and data jobs in parallel; compare rows lost between rounds | accept: Shivam | from: Paper pointer 3, Shivam 5 Nov | opened 2026-11-05
-- T-082 | OPEN | P2 | dsh workers pane: show stable session id, cached tokens, total tokens and median tokens per second on the band above the prompt and on the detail card | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
-- T-037 | OPEN | P1 | Fetch KEC's call transcripts from kecrpg.com; its 10 filed concalls are cover letters | accept: Shivam | from: Pilot 2 Nov | opened 2026-11-02
-- T-101 | OPEN | P1 | One document inventory: every held document file on C, D and the Drive archive linked to its catalog row (corporate_documents, raw_documents) or listed as unlinked; Drive part done by doc_locations.py (70,617 Drive files, 398 GB, no row points to: all 23,596 decks, 40,405 results PDFs) | accept: python -m pytest reality_engine/tests/test_doc_locations.py -q | from: Shivam 7 Nov | opened 2026-11-07
-- T-143 | DOING Wolf | P1 | Pilot20: pick 10 new companies from sectors not in pilot10 (Shivam approves), fetch raw, build on the CURRENT design, harvest + reframe questions, answer and grade = baseline; then rebuild on v2 and re-ask = redesign delta | accept: baseline report and v2 report on the same question set; delta table right/partly/wrong | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-034 | DOING Wolf | P1 | Pilot: page text for the thin BAJFINANCE, HINDALCO and KEC documents, by HP TextRecognizer | accept: Shivam | from: PROTOTYPE3 grade change 2 | opened 2026-11-02
-- T-040 | OPEN | P1 | Pilot: OCR every page of the 3 companies and mark each extracted number confirmed or disputed against the text layer | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
-- T-079 | OPEN | P1 | Trial one KPI round on a goal brief: keep evidence and fast check, drop edit-this-line steps; goal hand-read 18 of 20 on INFY and HINDALCO, checkpages at least 145 | accept: Shivam | from: Shivam 5 Nov, go given | opened 2026-11-05
-- T-081 | OPEN | P1 | KPI round 4: the wrong classes Opus found after T-079 (a loss stored positive, subsidiary figures as total, quarter dated to the year, non-revenue lines as revenue, question text as a value) | accept: Opus hand read on an unused seed | from: T-079 review 5 Nov | opened 2026-11-05
-- T-105 | OPEN | P1 | Latest guidance: each `guidance` row links the row it supersedes and `pilot3_guidance` returns the current target per company+metric+period by default (history on request); load the Q2 FY27 call targets missing for BAJFINANCE (60-62 mn loans, 18-20 mn customers, 25-40 bps opex, AUM 26-27%). Fails now: BAJFINANCE-014, -017 | accept: those two re-asked by DeepSeek come back right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
-- T-107 | DOING Wolf | P1 | Period type on every ratio row (quarter, half, year) and the full-year ratio stored directly (BAJFINANCE FY26 ROE 18.1%, not Q4 20.0%). Fails now: BAJFINANCE-027 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
-- T-108 | OPEN | P1 | Nil is a fact: a shareholding filing that states nil promoter pledge stores pledge 0 with its filing, and `pilot3_holding` says nil, filed on date. Fails now: BAJFINANCE-029, INFY-034 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
-- T-109 | OPEN | P2 | `pilot3_calc` returns a change between two percentages in percentage points (unit pp) beside the relative change. Fails now: INFY-035, INFY-032, INFY-065 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
-- T-115 | DOING Wolf | P1 | `fin_annual_line` rows from `ar_facts` keep the unit text ('rs mn', 'rs lakh', 'rs. in lacs') but scale 1 (104 rows on unseen6 + pilot10: ALKEM, ASHOKA, UFLEX, KALYANKJIL, SBILIFE, SUNPHARMA), and several history columns land under one year (ALKEM FY26 revenue holds 5 values) | accept: no fin_annual_line row whose unit names a scale has scale 1; one value per symbol/year/line/basis/caption; row_checks fin_conflict counts unchanged or lower | from: T-113 round 9 worker list, 8 Nov | opened 2026-11-08
-- T-124 | DOING Wolf | P1 | Ask the database the harvested investor questions: for each company set, Opus reframes the Gemini questions (T-116 v2), a model answers them through the reality-data MCP, Opus grades right / partly / not held; every 'not held' gets a usefulness grade (does it touch a T-118 price-moving factor) and the raw source that would answer it; output feeds the source wishlist and the database priorities | accept: Shivam | from: Shivam 8 Nov | opened 2026-11-08
-- T-035 | OPEN | P1 | Pilot: rerun extraction on the 3 companies, answer the same questions, grade by reading | accept: Shivam | from: PROTOTYPE3 grade change 5 | opened 2026-11-02
-- T-038 | OPEN | P1 | Wire contract-passing extract rows into the fact view; answer narrative questions with retrieved quoted passages, no model | accept: Shivam | from: Pilot 2 Nov | opened 2026-11-02
-- T-048 | OPEN | P1 | One-company gap loop: 100 sector-fit questions for KEC, Haiku sessions under 100k fill gaps by extraction or computation in a sandbox, Opus manages; replicate to 3, then 60 | accept: Shivam | from: Shivam, 2 Nov | opened 2026-11-02
-- T-049 | OPEN | P1 | Script extraction for the 3 pilot companies: rule-based scripts (no LLM; AI OCR only for image pages within budget) read all raw documents of KEC, BAJFINANCE, HINDALCO into the schema of tasks/arch_v4/T048_FINDINGS_AND_SCHEMA_2026-11-03.md in SQLite/DuckDB; answers only via MCP over that db; target the pilot's AI answer quality | accept: Shivam | from: Shivam, 3 Nov | opened 2026-11-03
-- T-095 | OPEN | P1 | Re-ask the same 20 questions with the T-088 brief after T-090, T-091 and T-092, Opus read blind | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
-- T-083 | DOING Eagle | P1 | Second reading step: a free model reads each answer against the question and the answer's own numbers and flags contradictions, unsourced causes and question misfit; test on graded answers before any use | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
-- T-135 | DOING Wolf | P1 | Calc catalog: named formulas run by code (growth, share, contribution to increase, incremental ROCE, cash conversion, range position, fair P/B, implied growth, reactions) served by a tool; answers cite outputs | accept: every compute-class failure of the 600/72 re-asks reproduced right by a catalog call; tests per formula | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-156 | OPEN | P1 | Point-in-time leak: 14 of 120 re-ask answers quote a call transcript filed 2-3 days after the question date (read via pilot3_sql on doc_page, which has no as_of filter); add an as_of guard to sql/doc_page reads and set call-question as_of to the transcript filing date | accept: re-run strict check: 0 quotes from pages known after as_of on the 120 re-ask answers; sql with as_of drops later doc_page rows; test | from: Opus strict grading 9 Nov | opened 2026-11-09
-- T-031 | OPEN | P3 | Research library bucket scheme; duplicates deleted 2 Nov, list in _dupes_deleted_2026-11-02.csv | accept: Shivam | from: T-026 | opened 2026-11-02
-- T-104 | OPEN | P2 | Antigravity CLI as a worker backend: confirm a headless run (prompt in, edits in a worktree, answer out, exit), its login persistence, models and daily quota on Google AI Pro; one small test task; if it passes, add an adapter to dsh-worker beside OpenCode; model only gemini-3.8-flash-medium (Shivam) | accept: Shivam | from: Shivam 7 Nov | opened 2026-11-07
```

## 2026-11-10T22:06:04+05:30 | kakazuya (Eagle) | 63a24b9e T-164 merged (7f8497c4) after independent review; evidence on D:, docs repointed, worktrees removed;
```diff
-- T-164 | OPEN | P1 | Call statements: tag named programmes/projects/counterparties and real topics (not 'other'), split at speaker turns never mid-answer, view of analyst questions across the last N calls; 18 audit questions | accept: the 18 statement questions of the held audit answer through pilot3_statements on u8/q12 | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
```

## 2026-11-10T23:16:53+05:30 | kakazuya (Eagle) | fe775325 T-177 T-178 T-179 T-180 opened: Fable review written into the brief (section 10) and test designs in
```diff
+- T-177 | OPEN Eagle | P1 | Reference pages (60, half frozen) and per-page completeness report with a build gate | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/v2/reference_pages/reference_cells.csv').exists() else 1)" | from: Fable review 10 Nov | opened 2026-11-10
+- T-178 | OPEN Eagle | P1 | First-build re-key test: ar_facts/deck_figures facts verified + label map + period engine vs script cells on reference pages | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/reports/2026-11-11_t178_first_build_rekey.xlsx').exists() else 1)" | from: Fable review 10 Nov | opened 2026-11-10
+- T-180 | OPEN Eagle | P1 | Free-model table transcription bake-off (Beam, LongCat 2.5, Kilo free models) with script verification vs r10 script | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/reports/2026-11-12_t180_reader_bakeoff.xlsx').exists() else 1)" | from: Fable review 10 Nov | opened 2026-11-10
+- T-179 | OPEN Eagle | P1 | Raw SQL A/B: 120 questions x 2 arms x 2 runs with and without pilot3_sql, calls and seconds logged, grader calibrated | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/reports/2026-11-11_t179_sql_ab.xlsx').exists() else 1)" | from: Fable review 10 Nov | opened 2026-11-10
```

## 2026-11-11T10:44:11+05:30 | kakazuya (Eagle) | b7d98dff T-181 opened (document-integrity gate); briefs for T-181 and the T-177 completeness report
```diff
+- T-181 | OPEN Eagle | P1 | Document-integrity gate before extraction: link-notice transcripts, duplicates, misdated, mistyped, truncated documents; per-store report and build gate | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/pilot3/doc_integrity.py').exists() else 1)" | from: Fable review 10 Nov | opened 2026-11-11
```

## 2026-11-11T11:02:07+05:30 | kakazuya (Eagle) | 67cd12dd T-181 done: review row, reports on D:, ticket closed
```diff
-- T-181 | OPEN Eagle | P1 | Document-integrity gate before extraction: link-notice transcripts, duplicates, misdated, mistyped, truncated documents; per-store report and build gate | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/pilot3/doc_integrity.py').exists() else 1)" | from: Fable review 10 Nov | opened 2026-11-11
```

## 2026-11-11T14:08:19+05:30 | kakazuya (Eagle) | 8b8e07b8 T-182: ticket opened (word boxes for every page, text layer or OCR)
```diff
+- T-182 | OPEN Eagle | P1 | Word boxes for every page: one source (PDF text layer turned upright, else OCR word boxes from ocr_page), with a text-quality verdict (ok / none / jumbled), feeding layout text and the position check | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/v2/page_words.py').exists() else 1)" | from: Shivam 11 Nov 13:45 (settle extraction for every page, text or image; free models code in peak) | opened 2026-11-11
```

## 2026-11-11T14:10:19+05:30 | kakazuya (Eagle) | c44603e5 T-183: ticket opened (page reader)
```diff
+- T-183 | OPEN Eagle | P1 | Page reader: every table page of a store (text layer or OCR) read by a free model in grid format from layout text, each cell position-checked (verified/unverified), unread numbers counted per page and re-asked once; resumable, written to page_read/page_cell | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/v2/page_reader.py').exists() else 1)" | from: Shivam 11 Nov 13:45 (settle extraction for every page) | opened 2026-11-11
```

## 2026-11-11T14:20:46+05:30 | kakazuya (Eagle) | 432afadb T-184: run ledger (every run of every model: tool calls by tool, MCP vs raw SQL vs workaround, secon
```diff
+- T-184 | OPEN | P2 | Gate for ruling: Run ledger (11 Nov): log every run of every model (DEVELOPER_GUIDE s7); answers say why raw SQL was used; report overfit | accept: Shivam: standing_rules.xlsx shows a code gate for it | from: ruling intake | opened 2026-11-11
```

## 2026-11-11T14:42:27+05:30 | kakazuya (Eagle) | b2f52365 T-180: bake-off scored on a fresh frozen set (Dots grid+image recall 84% vs r10 36%, first build 41%
```diff
-- T-180 | OPEN Eagle | P1 | Free-model table transcription bake-off (Beam, LongCat 2.5, Kilo free models) with script verification vs r10 script | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/reports/2026-11-12_t180_reader_bakeoff.xlsx').exists() else 1)" | from: Fable review 10 Nov | opened 2026-11-10
```

## 2026-11-11T15:36:25+05:30 | kakazuya (Eagle) | 8d143caf T-185, T-186: tickets opened
```diff
+- T-185 | OPEN Eagle | P1 | Position check v2: columns from header x-ranges (not header-word presence), wrapped row labels, chart panels; and a per-cell verdict that separates reader error from checker miss | accept: python -m pytest -q reality_engine/tests/test_v2_reference_geom.py | from: T-180 result 11 Nov | opened 2026-11-11
+- T-186 | OPEN Eagle | P1 | Answer-ready fact lookup: one tool call returns the preferred figure with period, basis, unit, source document and page, known_at, and the formula inputs when computed, for any (company, metric, period, basis) | accept: python -m pytest -q plugins/reality-data/tests/test_lookups_pilot3.py | from: Fable review item 7, 11 Nov | opened 2026-11-11
```

## 2026-11-11T15:39:13+05:30 | kakazuya (Eagle) | e1ec6316 T-187: ticket opened (guidance round 5)
```diff
+- T-187 | OPEN Eagle | P1 | Guidance round 5: restore 4 management targets the 11 Nov rebuild lost (BEL FY27 margin 25-31%, CIPLA FY24 margin 23-24%, INDHOTEL FY26 capex ~1,100 Cr, APOLLOTYRE FY27 capex 1,200-1,300 Cr); stop keying gross margin as ebitda_margin | accept: python -m pytest -q reality_engine/tests/test_pilot3_guidance.py | from: Eagle rebuild compare 11 Nov | opened 2026-11-11
```

## 2026-11-11T21:14:15+05:30 | kakazuya (Eagle) | 271e8682 T-188: ticket + STATE line for the local reader bake-off (truth for all 30 frozen2 pages, hard/norma
```diff
+- T-188 | DOING Eagle | P1 | Local reader bake-off: PaddleOCR-VL-1.6, GLM-OCR, LightOnOCR-3-0.8B on the 1050 Ti and TextRecognizer (HP) against Dots, on all 30 frozen2 pages with Opus hand-read truth; hardest half (Dots worst by truth) vs normal half | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/v2/reference_pages_frozen2/handread/score_local.csv').exists() else 1)" | from: Shivam 11 Nov 19:00 | opened 2026-11-11
```

## 2026-11-11T21:15:39+05:30 | kakazuya (Eagle) | fea087bd T-188: done (accept file score_local.csv written; results in STATE)
```diff
-- T-188 | DOING Eagle | P1 | Local reader bake-off: PaddleOCR-VL-1.6, GLM-OCR, LightOnOCR-3-0.8B on the 1050 Ti and TextRecognizer (HP) against Dots, on all 30 frozen2 pages with Opus hand-read truth; hardest half (Dots worst by truth) vs normal half | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/v2/reference_pages_frozen2/handread/score_local.csv').exists() else 1)" | from: Shivam 11 Nov 19:00 | opened 2026-11-11
```

## 2026-11-11T22:46:07+05:30 | kakazuya (Eagle) | c04ddb81 T-189: plan for the AUROPHARMA unseen-company test (frozen questions, routed page reading, 92% bar);
```diff
+- T-189 | OPEN Eagle | P1 | Unseen-company test: AUROPHARMA built end to end with routed page reading (text layer / HP TextRecognizer / Dots on table+chart pages), frozen first-order question set answered via MCP and hand-graded; pass bar 92% right; compare with pilot honest baselines | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/aurobindo/report/grades.csv').exists() else 1)" | from: Shivam 11 Nov 22:30 | opened 2026-11-11
```

## 2026-11-12T13:18:17+05:30 | kakazuya (Eagle) | cbb896ec T-190: HP TextRecognizer stays installed; helper build fixed; embed --since/--all-types (T-191)
```diff
+- T-193 | OPEN | P1 | AUROPHARMA missing filings: Q2 FY27 call transcript, every SHP category + pledge from exchange XML (script fetch, universe-wide fetcher) | accept: python -m reality_engine.scripts.p3ask --db D:/RealityEngine/aurobindo/aurobindo.db holding symbol=AUROPHARMA as_of=2026-10-19 category=fpi_total | from: T-189 graders | opened 2026-11-12
+- T-192 | OPEN | P1 | Wrong stored rows found by T-189 graders: ROE on average equity, exact share count (not rounded from paid-up capital), one EBITDA definition per line | accept: python -m pytest reality_engine/tests -q -k 'roe or share_count or ebitda' | from: T-189 graders | opened 2026-11-12
+- T-191 | OPEN Eagle | P1 | Semantic search A/B on AUROPHARMA: same model, same store, same 69 questions, arm A without pilot3_semantic, arm B with it (Nemotron 8B page vectors) | accept: python -c "import pathlib;assert pathlib.Path('D:/RealityEngine/aurobindo/ab_semantic/AB_RESULT.md').exists()" | from: Shivam 12 Nov | opened 2026-11-12
+- T-190 | OPEN Eagle | P1 | HP TextRecognizer stays installed: install once, signing key destroyed, cert only in TrustedPeople; hp_ocr cleanup keeps the package | accept: python -m pytest reality_engine/tests/test_hp_headless.py -q | from: Shivam 12 Nov | opened 2026-11-12
```

## 2026-11-12T13:25:18+05:30 | kakazuya (Eagle) | 9ebc3108 T-194: tool-fix brief (waits for Shivam); STATE after four-model grading, SHP fetch, HP install
```diff
+- T-194 | WAITING Shivam | P1 | Tool fixes for early stopping: topic tool across calls, exact-phrase search with counts, sector topic vocabulary, event table, server-enforced as_of | accept: python -m pytest plugins/reality-data/tests/test_lookups_pilot3.py -q | from: T-189 graders | opened 2026-11-12
```

## 2026-11-12T19:24:14+05:30 | kakazuya (Eagle) | 04c4a9f8 T-195: reality-data serves the Aurobindo store (REALITY_PILOT3_DB); re-run brief with the topic tool
```diff
+- T-195 | OPEN Eagle | P1 | Aurobindo 69-question re-run after T-192 row fixes and T-194 tools (DeepSeek x2, Haiku x1), blind graded | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/reports/2026-11-12_aurobindo_rerun.html').exists() else 1)" | from: Shivam 12 Nov 20:40 | opened 2026-11-12
```

## 2026-11-12T19:49:05+05:30 | kakazuya (Eagle) | df645428 T-195: re-run graded and reported (DeepSeek 85.5/84.1, Haiku 76.8)
```diff
-- T-195 | OPEN Eagle | P1 | Aurobindo 69-question re-run after T-192 row fixes and T-194 tools (DeepSeek x2, Haiku x1), blind graded | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/reports/2026-11-12_aurobindo_rerun.html').exists() else 1)" | from: Shivam 12 Nov 20:40 | opened 2026-11-12
```

## 2026-11-12T19:52:16+05:30 | kakazuya (Eagle) | 7cdae468 T-196: ticket for why answerers stop early; retry briefs point at it
```diff
+- T-196 | OPEN Eagle | P1 | Why answerers stop early: DeepSeek retries on T-195 misses (answer is held), why_stopped per question | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/reports/2026-11-12_why_answers_stop.html').exists() else 1)" | from: Shivam 12 Nov 19:50 | opened 2026-11-12
```

## 2026-11-12T20:17:23+05:30 | kakazuya (Eagle) | 2bef1e9e T-196: why answers stop - retries 12/21 right, stop reasons and fixes reported
```diff
-- T-196 | OPEN Eagle | P1 | Why answerers stop early: DeepSeek retries on T-195 misses (answer is held), why_stopped per question | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/reports/2026-11-12_why_answers_stop.html').exists() else 1)" | from: Shivam 12 Nov 19:50 | opened 2026-11-12
```

## 2026-11-12T21:00:47+05:30 | kakazuya (Eagle) | dc9bdfd0 T-197/T-198: briefs for discoverable tool replies and the row-checker label rule (universal, no ques
```diff
+- T-198 | OPEN Eagle | P1 | Row checker: a label's own qualifier is not a conflict; like-for-like cross-doc; pilot3_fact shows a company-stated figure it did not prefer | accept: python -m pytest reality_engine/tests/test_row_checks.py -q | from: Shivam 12 Nov 20:50 | opened 2026-11-12
+- T-197 | OPEN Eagle | P1 | Discoverable tool replies: coverage block, full-text topic/statements, paging, as_of on every tool, event body, cells values (universal, no question tuning) | accept: python -m pytest plugins/reality-data/tests/test_lookups_pilot3.py -q | from: Shivam 12 Nov 20:50 | opened 2026-11-12
```

## 2026-11-12T21:49:24+05:30 | kakazuya (Eagle) | 6c0427f6 Housekeeping 12 Nov: T-053 done; T-119, T-176 moved to idea box (I-001, I-002); I-003..I-012 mainten
```diff
-- T-053 | OPEN | P1 | Stress-test and harden job_watch wait and the Stop hook: race before baseline, corrupt status, many jobs, killed or duplicate waiters, pid reuse, registered stalls | accept: python -m pytest reality_engine/tests/test_job_watch_stress.py reality_engine/tests/test_job_watch.py reality_engine/tests/test_session_hooks.py -q | from: Shivam, 3 Nov | opened 2026-11-03
+- T-200 | OPEN Eagle | P2 | agy job.json stays 'running' after the job ends (exit.json says completed): fix the status writer | accept: python -m pytest plugins/agy-worker/tests -q | from: housekeeping 12 Nov | opened 2026-11-12
-- T-119 | OPEN | P1 | Our own forward estimates vs the market's: per company, our 1-2 year revenue and earnings estimate from held facts (trend, guidance, order book, margins), and the growth the current price implies (reverse DCF / implied growth at a sector discount rate); the gap says whether the market sees the company through the same lens. Measure the gap's power on 6m-2y forward returns after T-118, PIT | accept: Shivam | from: Shivam 8 Nov (P/E and P/S are lagging when the market pays a premium; the market looks 6 months to 2 years ahead) | opened 2026-11-08
+- T-199 | OPEN Eagle | P1 | Atom design + unseen-company test: BLUESTARCO (questions frozen before build; Haiku page reading via subagent sessions; tools after T-197/T-198) | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/bluestar/questions/questions.csv').exists() else 1)" | from: Shivam 12 Nov 21:40 | opened 2026-11-12
-- T-176 | OPEN | P1 | Recurring factor-reward engine: at every rebalance date and for every stock, sector and regime, measure which held factors were rewarded over the following 6m/12m/24m (point in time), store the per-date results, and report the statistical mode of the rewarded factors per stock/sector/regime and how that mode shifts over time | accept: Shivam: reviews the mode report | from: Shivam 10 Nov (T-118 follow-up) | opened 2026-11-10
```

## 2026-11-12T21:50:20+05:30 | kakazuya (Eagle) | 3ca92e7e T-092: dropped as superseded; 12 superseded branches deleted with archive tags (worktrees 9.2 -> 3.8
```diff
-- T-092 | OPEN | P1 | Complete, named guidance from letters and calls, with the store count and growth targets the ETERNAL answers had to dig for; universal rules | accept: Shivam | from: Shivam 6 Nov, T-088 re-test | opened 2026-11-06
```

## 2026-11-12T21:58:14+05:30 | kakazuya (Eagle) | 7d7deaec T-201/T-202/T-203: promoted from the idea box with briefs; idea box records context, purpose, origin
```diff
+- T-201 | OPEN Eagle | P1 | Store diff tool: rebuild a store copy with main code and with a branch, diff every table, refuse a merge that loses a right row (from idea I-003) | accept: python -m pytest reality_engine/tests/test_pilot3_no_company_literals.py -q | from: Shivam 12 Nov 22:20 (promoted from idea box) | opened 2026-11-12
+- T-203 | OPEN Eagle | P1 | reality-data routes each symbol to the store that holds it, no .mcp.json edit per test (from idea I-009) | accept: python -m pytest reality_engine/tests/test_pilot3_no_company_literals.py -q | from: Shivam 12 Nov 22:20 (promoted from idea box) | opened 2026-11-12
+- T-202 | OPEN Eagle | P1 | Versioned store schema: schema_version table, numbered migrations, build parts and lookups check the version (from idea I-005) | accept: python -m pytest reality_engine/tests/test_pilot3_no_company_literals.py -q | from: Shivam 12 Nov 22:20 (promoted from idea box) | opened 2026-11-12
```

## 2026-11-12T22:11:48+05:30 | kakazuya (Eagle) | cdc5e982 T-197, T-201 done; events rebuilt on aurobindo, pilot10, n10
```diff
-- T-201 | OPEN Eagle | P1 | Store diff tool: rebuild a store copy with main code and with a branch, diff every table, refuse a merge that loses a right row (from idea I-003) | accept: python -m pytest reality_engine/tests/test_pilot3_no_company_literals.py -q | from: Shivam 12 Nov 22:20 (promoted from idea box) | opened 2026-11-12
-- T-197 | OPEN Eagle | P1 | Discoverable tool replies: coverage block, full-text topic/statements, paging, as_of on every tool, event body, cells values (universal, no question tuning) | accept: python -m pytest plugins/reality-data/tests/test_lookups_pilot3.py -q | from: Shivam 12 Nov 20:50 | opened 2026-11-12
```

## 2026-11-12T22:27:44+05:30 | kakazuya (Eagle) | 49a0148e T-203 done
```diff
-- T-203 | OPEN Eagle | P1 | reality-data routes each symbol to the store that holds it, no .mcp.json edit per test (from idea I-009) | accept: python -m pytest reality_engine/tests/test_pilot3_no_company_literals.py -q | from: Shivam 12 Nov 22:20 (promoted from idea box) | opened 2026-11-12
```

## 2026-11-12T23:08:27+05:30 | kakazuya (Eagle) | 24a86102 Close merged tickets T-191 (04e75c9c), T-192 (2c3aafd0), T-194, T-198
```diff
-- T-198 | OPEN Eagle | P1 | Row checker: a label's own qualifier is not a conflict; like-for-like cross-doc; pilot3_fact shows a company-stated figure it did not prefer | accept: python -m pytest reality_engine/tests/test_row_checks.py -q | from: Shivam 12 Nov 20:50 | opened 2026-11-12
-- T-192 | OPEN | P1 | Wrong stored rows found by T-189 graders: ROE on average equity, exact share count (not rounded from paid-up capital), one EBITDA definition per line | accept: python -m pytest reality_engine/tests -q -k 'roe or share_count or ebitda' | from: T-189 graders | opened 2026-11-12
-- T-194 | WAITING Shivam | P1 | Tool fixes for early stopping: topic tool across calls, exact-phrase search with counts, sector topic vocabulary, event table, server-enforced as_of | accept: python -m pytest plugins/reality-data/tests/test_lookups_pilot3.py -q | from: T-189 graders | opened 2026-11-12
-- T-191 | OPEN Eagle | P1 | Semantic search A/B on AUROPHARMA: same model, same store, same 69 questions, arm A without pilot3_semantic, arm B with it (Nemotron 8B page vectors) | accept: python -c "import pathlib;assert pathlib.Path('D:/RealityEngine/aurobindo/ab_semantic/AB_RESULT.md').exists()" | from: Shivam 12 Nov | opened 2026-11-12
```

## 2026-11-12T23:18:23+05:30 | kakazuya (Eagle) | ca3e2d41 T-200 done
```diff
-- T-200 | OPEN Eagle | P2 | agy job.json stays 'running' after the job ends (exit.json says completed): fix the status writer | accept: python -m pytest plugins/agy-worker/tests -q | from: housekeeping 12 Nov | opened 2026-11-12
+- T-204 | OPEN Eagle | P1 | Small fixes before the atom build: fetch --out writes the per-company manifest; topic coverage document list shrinks with limit; page_cell not listed as searched on a store without it | accept: python -m pytest plugins/reality-data/tests/test_lookups_pilot3.py -q | from: Eagle 12 Nov 23:35 (Shivam: clear tickets before the atom build) | opened 2026-11-12
```

## 2026-11-12T23:26:39+05:30 | kakazuya (Eagle) | 8e07a309 T-202 done
```diff
-- T-202 | OPEN Eagle | P1 | Versioned store schema: schema_version table, numbered migrations, build parts and lookups check the version (from idea I-005) | accept: python -m pytest reality_engine/tests/test_pilot3_no_company_literals.py -q | from: Shivam 12 Nov 22:20 (promoted from idea box) | opened 2026-11-12
```

## 2026-11-12T23:46:38+05:30 | kakazuya (Eagle) | 98184220 T-204 done
```diff
-- T-204 | OPEN Eagle | P1 | Small fixes before the atom build: fetch --out writes the per-company manifest; topic coverage document list shrinks with limit; page_cell not listed as searched on a store without it | accept: python -m pytest plugins/reality-data/tests/test_lookups_pilot3.py -q | from: Eagle 12 Nov 23:35 (Shivam: clear tickets before the atom build) | opened 2026-11-12
```

## 2026-11-13T14:49:37+05:30 | kakazuya (Eagle) | c06cc937 T-205: open ticket; free-model check and data inventory refresh
```diff
+- T-205 | OPEN Eagle | P1 | Evidence-pack answerer: script gathers every route per question, model writes from the pack; measure pack recall vs grader truths first | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/bluestar/pack/pack_recall.csv').exists() else 1)" | from: Shivam 13 Nov 12:50 | opened 2026-11-13
```

## 2026-11-13T15:11:19+05:30 | kakazuya (Eagle) | a689c703 T-206: workspace journal (tasks/JOURNAL.md), ruling, start hook names the latest entry
```diff
+- T-206 | OPEN | P2 | Gate for ruling: Journal (13 Nov): add a tasks/JOURNAL.md entry (work, what worked, what failed and why, fixes) at 400k context and at wr | accept: Shivam: standing_rules.xlsx shows a code gate for it | from: ruling intake | opened 2026-11-13
```

## 2026-11-13T16:08:51+05:30 | kakazuya (Wolf) | df4f4cd3 T-207: factor-reward ticket and brief; T-205 round-4 brief; board cut to 51 open (I-013..I-015), Shi
```diff
-- T-001 | OPEN | P1 | Enforce worker tool-call budgets in code; a worker used 266+ against 120, and another 181 against 150 | accept: python -m pytest reality_engine/tests/test_worker_budget.py -q | from: STATE 1 Nov | opened 2026-11-02
-- T-002 | OPEN | P1 | Block by hook: git push, private folder reads, printed keys, --no-verify, gate edits, git stash, full suite on the MSI | accept: python -m pytest reality_engine/tests/test_enforcement_hooks.py -q | from: enforcement plan | opened 2026-11-02
-- T-003 | OPEN | P1 | Merge gate: tests, doc gate, accept check, Docs updated line, hidden evaluation, rulings diff (workspace step 3) | accept: python -m pytest reality_engine/tests/test_merge_gate.py -q | from: workspace plan step 3 | opened 2026-11-02
-- T-127 | OPEN | P1 | Shivam's directions enforced by code, not Claude's memory: (1) one intake command records a new direction in RULINGS.md, the standing-rules sheet and memory, and opens a gate ticket when it relies on the model; (2) gates for the model-reliant rules that already failed once: merge refused without a worker_reviews row; start_worker refuses a third code worker; merge refused when a branch's tests are missing; full-run build parts refuse without a passing pilot checklist; raw files left on disk after a DB write flagged by the session-start hook. Measured 8 Nov: 9 of 25 rulings enforced by code | accept: standing_rules.xlsx shows each listed rule with a code gate; tests for each gate pass | from: Shivam 8 Nov | opened 2026-11-08
-- T-148 | OPEN | P1 | Incremental build by document, keyed by content hash: a new filing touches only its company file; reruns skip documents already done | accept: adding one filing rebuilds one company in minutes; full rerun with no new docs does no extraction | from: Shivam 9 Nov 01:25 | opened 2026-11-09
-- T-152 | OPEN | P1 | Golden tables per type: ~50 hand-checked tables per type (deck KPI, segment note, FX sensitivity, results P&L); every extractor change scored on them before merge | accept: golden sets on Drive; merge gate fails on any lost right cell | from: Shivam 9 Nov 01:25 | opened 2026-11-09
-- T-153 | OPEN | P1 | Warm MCP server for v2: cached file handles and connections so tool start-up does not dominate the 1 s budget | accept: end-to-end tool call p95 <=1 s on pilot20 | from: Shivam 9 Nov 01:25 | opened 2026-11-09
-- T-171 | OPEN | P1 | Cut per-worker RAM. Measured 10 Nov: each dsh worker holds ~0.8 GB before it runs anything: dsh node 230 MB, sandbox+subprocess node 130 MB, its own reality-data MCP 210 MB, code-tools MCP 77 MB, data-gather MCP 76 MB, harness+supervisor python 70 MB; tests/builds it runs add the 1-2 GB spikes. Fix: (1) code workers start without data-gather (data jobs keep it); (2) one shared reality-data server for all workers (HTTP transport) instead of one per worker, or lazy imports + capped caches; (3) workers run heavy builds/tests through a RAM-capped runner (one heavy job at a time); measure before/after with 4 workers | accept: per-worker baseline RAM measured <=450 MB with 4 workers running; tools unchanged for workers (reality-data, code-tools calls still pass); report before/after in docs/DEVELOPER_GUIDE.md | from: Shivam 10 Nov 16:30 (RAM, not CPU, is the limit) | opened 2026-11-10
-- T-139 | DOING Wolf | P1 | Outside sources: rating-agency rationale notes (CRISIL, ICRA, CARE, India Ratings), official monthly industry data (auto sales, cement output, airline traffic), budget/PIB capex figures; dated, mapped to companies | accept: fetchers + raw on Drive for pilot20 and unseen sets; rating rationale held for >=90% of rated pilot20 companies | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-174 | OPEN | P1 | Policy-to-company impact map: each held policy/regulation row linked to the companies it touches with a verdict (advantageous, disadvantageous, neutral), the reason, and a quantification where the filings or the policy text give one | accept: Shivam: approves the 40-link sample | from: Shivam 10 Nov (T-022) | opened 2026-11-10
-- T-052 | OPEN | P1 | pilot3 OCR run to completion over every needs_ocr page (sandbox and pages.db), then rebuild pilot3.db with the OCR pages | accept: Shivam | from: Shivam, 3 Nov | opened 2026-11-03
-- T-068 | OPEN | P1 | Settle doubtful KPI rows with free beam-free on both Go keys, as a step after the build with saved verdicts; gate its accuracy on hand-read rows before use | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
-- T-132 | DOING Wolf | P1 | Table store: every printed table cell of decks, results, fact sheets, investor presentations and annual-report notes as a row (doc, page, row label, column header, period, unit, value); text layer first, HP OCR for scans, AI only where scripts fail and labelled | accept: on pilot20: >=95% of hand-sampled printed table cells captured with right header/period/unit (Opus sample 100 cells per doc type) | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-138 | OPEN | P1 | Annual-report notes as tables: guarantees, contingent liabilities, related parties (standalone and consolidated apart), FX sensitivity, ratings, segments; section detection per page | accept: Infosys parent guarantee, KEC FX sensitivity, HUL related parties answered from rows; pilot20 notes sample >=95% right | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-147 | OPEN | P1 | Parse once, map many: keep each document's parsed output (tables, sections, statements) beside the store so later schema versions re-map without re-reading PDFs from Drive | accept: v2 rebuild of pilot20 from parsed outputs with zero PDF downloads; parse step skipped on rerun | from: Shivam 9 Nov 01:25 | opened 2026-11-09
-- T-175 | OPEN | P1 | Jumbled text-layer detector: flag pages whose text layer exists but reads as garbage (broken encoding, glued words, reversed or scattered characters) so only those and textless pages go to HP OCR | accept: Shivam: approves the 100-page labelled check | from: Shivam 10 Nov (T-121) | opened 2026-11-10
-- T-106 | OPEN | P1 | Scope on every guidance and KPI row: group, segment or subsidiary (Blinkit, District, BHFL), so a segment target is never served as the company's. Fails now: ETERNAL-015, -017 | accept: re-asked right | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
-- T-112 | OPEN | P1 | agy-worker MCP: start, status (tool calls by tool, tokens, quota left), result and cancel for Antigravity CLI coding jobs in a Wolf- worktree, like dsh-worker; then the same prescriptive T-105 brief to Gemini 3.8 Flash medium and to dsh, compared | accept: Shivam | from: Shivam 8 Nov (Gemini vs Opus vs DeepSeek test, answer_t084/grading_g) | opened 2026-11-08
-- T-113 | DOING Wolf | P1 | Independent row check layer `reality_engine/pilot3/row_checks.py` for `guidance` and `kpi_series` (quote anchor, sector-metric fit, own-company figure, reconciliation, plausibility) giving each row verified / unverified / quarantined; run over live pilot10.db read-only and report counts per metric, sector and document type | accept: catches the 6 T-105 rows deleted 8 Nov (backup guidance_before_t105.db) and most of the 15 Gemini T-105 wrong rows without being told about them; Opus sample of quarantined and verified rows; Shivam | from: Shivam 8 Nov (standing rule: worker never checks its own code) | opened 2026-11-08
+- T-113 | OPEN | P1 | Independent row check layer `reality_engine/pilot3/row_checks.py` for `guidance` and `kpi_series` (quote anchor, sector-metric fit, own-company figure, reconciliation, plausibility) giving each row verified / unverified / quarantined; run over live pilot10.db read-only and report counts per metric, sector and document type | accept: catches the 6 T-105 rows deleted 8 Nov (backup guidance_before_t105.db) and most of the 15 Gemini T-105 wrong rows without being told about them; Opus sample of quarantined and verified rows; Shivam | from: Shivam 8 Nov (standing rule: worker never checks its own code) | opened 2026-11-08
-- T-120 | DOING Wolf | P1 | Pilot10 history 2019-2024: fetch BSE documents for HDFCBANK, SBILIFE, INFY, MARUTI, ETERNAL (the other five are already in pilot60_history) and build a pilot10 history database with window_start 2019, so verbatim statements, guidance and KPIs can be tested on 6m-2y horizons (T-118/T-119) | accept: coverage per company per year (decks, calls, results, AR) reported; Shivam | from: Shivam 8 Nov | opened 2026-11-08
-- T-123 | OPEN | P1 | Document difficulty report, refreshed with every build: per doc type x company x filing year, text coverage (canary), verdict rates (verified / unverified / quarantined), top hard-failure reasons and hand-read accuracy from the regression labels; names which documents need work and which are clean. First cut 8 Nov: annual reports and transcripts ~30% of rows quarantined (unit_kind/page_unit; future_period/analyst speaker), decks/announcements/results 7-10%, XBRL segments 100% verified; hand reads: decks 53% right, annual reports 65%, results 83% | accept: Shivam | from: Shivam 8 Nov | opened 2026-11-08
-- T-094 | OPEN | P1 | Universe readiness: no hand lists of companies in build or tools (LENDERS in ratios.py, kpi.COMPANIES, gap_loop COMPANIES, docs_collect KEC manifest), sector from data, per-company time and size measured and projected to 6,940 companies, and an unchanged build on companies never seen | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
-- T-085 | OPEN | P1 | Number check passes invented or wrong figures: MARUTI-102 in `answer_a3\second_read\fix_test\arm_plain` writes Rs 5,33,555 crore for 5.33555e+11 rupees (53,355.5 crore); INFY-005 in `arm_flags` has inputs 43,278, 46,347, 49,012, 50,699 that sum to the right total but are not the filed quarters (Q2 49,244). Catch both with no new false alarm on the 600 answers | accept: python -m pytest reality_engine/tests/test_pilot3_number_check.py -q | from: Eagle 6 Nov, T-083 read | opened 2026-11-06
-- T-098 | OPEN | P1 | Build applies window_start to documents, not only stores: scratch builds from the pilot60_history manifest held 2019+ documents (hold6 531 of 611 guidance targets before 2024-04-01); re-measure T-094's 501 GB and 52 h projection on windowed documents | accept: Shivam | from: Wolf 6 Nov, T-092 hold-out read | opened 2026-11-06
-- T-100 | OPEN | P1 | Prototype the announcement type reader: classify each 2024-04+ announcement from its own text (first page, more pages until clear), not the exchange category; measure agreement with a hand read and how often the exchange label is wrong; re-measure per-company size on the kept types; project to 6,940 | accept: Shivam | from: Shivam 7 Nov | opened 2026-11-07
-- T-130 | DOING Wolf | P1 | Unseen set u8 (ULTRACEMCO, TRENT, BEL, INDIGO, CIPLA, PERSISTENT, CHOLAFIN, TATACONSUM): agy harvests company-specific questions plus the sector's standard and conceptual analyst questions; Opus reframes; build the u8 store; DeepSeek answers; Opus grades by hand | accept: harvest CSVs verified (pages fetched); reframed set; u8 store built; answer_run_report u8 xlsx+csv with right/partly/wrong and root causes | from: Shivam 8 Nov 23:30 | opened 2026-11-08
-- T-133 | DOING Wolf | P1 | Label dictionary: cluster row labels across companies into one metric per sector family; Opus approves each family once; review queue for frequent unmapped labels; fix sector map (UltraTech, Trent, IndiGo came out 'unknown') | accept: every pilot20 company has a sector family; >=90% of table rows in numeric tables map to a metric or sit in the queue | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-134 | DOING Wolf | P1 | Period engine: exact start/end on every value; derive quarters from 9M/H1/FY, TTM, year-ago-as-known-at-date pairs as stored rows with formula and inputs; the model never subtracts | accept: SBI Life Q3/Q4 APE, TTM vs FY cases and all pilot cumulative-only series derived and checked against printed QoQ/YoY columns | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-136 | OPEN | P1 | Answer protocol + final checker: plan the facts a question needs, fetch each by tool, compose; checker refuses any figure not tied to a stored/derived row and any conclusion its own figures contradict | accept: replay of the 72 re-ask answers: every wrong/partly reading fault caught or fixed; zero right answers refused | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-140 | OPEN | P1 | Events table: dated policy, tariff, regulation, results, orders, M&A and rating events with effective dates and companies touched, so 'since <date>' chains are queries | accept: Maruti/Hindalco/KEC policy-chain questions answered with in-window events; T-117 circulars feed it | from: Shivam 9 Nov 01:10 | opened 2026-11-09
+- T-130 | OPEN | P1 | Unseen set u8 (ULTRACEMCO, TRENT, BEL, INDIGO, CIPLA, PERSISTENT, CHOLAFIN, TATACONSUM): agy harvests company-specific questions plus the sector's standard and conceptual analyst questions; Opus reframes; build the u8 store; DeepSeek answers; Opus grades by hand | accept: harvest CSVs verified (pages fetched); reframed set; u8 store built; answer_run_report u8 xlsx+csv with right/partly/wrong and root causes | from: Shivam 8 Nov 23:30 | opened 2026-11-08
-- T-142 | OPEN | P1 | Row checks for v2 rows: parts sum to totals, printed QoQ/YoY columns agree with derived rows, XBRL reconciliation; verified without a second source when they pass | accept: regression set 0 FAIL; hidden hold-out: zero wrong rows verified | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-144 | OPEN | P1 | Iteration loop: build pilot20 -> test on a fresh unseen set -> rebuild -> test on the next fresh unseen set; each unseen set used once, questions harvested by agy and reframed by Opus | accept: per-round answer_run_report xlsx; trend sheet across rounds | from: Shivam 9 Nov 01:10 | opened 2026-11-09
-- T-145 | OPEN | P1 | v2 storage layout: per-company SQLite files (facts + evidence + full-text), DuckDB over Parquet for market series and cross-company screens, a catalog that routes company/ISIN to its file; atomic per-company swap | accept: lookup p95 <=5 ms, per-company text search p95 <=50 ms, cross-company screen p95 <=1 s on a 500 GB synthetic scale test; swap of one company never touches another | from: Shivam 9 Nov 01:25 | opened 2026-11-09
-- T-146 | OPEN | P1 | One fact, many sources: a figure printed in deck, results and press release is one fact row with several evidence links; agreement count feeds row checks; derived rows store formula + input ids only; preferred figure elected ahead | accept: no duplicate fact keys in pilot20; corroboration count populated; derived rows recompute exactly from inputs | from: Shivam 9 Nov 01:25 | opened 2026-11-09
-- T-149 | OPEN | P1 | Entities for segments and subsidiaries (Blinkit, Novelis, BHFL, Westside/Zudio, SAE Towers) linked to the parent; every fact names its entity | accept: segment-as-total and subsidiary-PAT-as-company errors absent in the pilot20 hand sample | from: Shivam 9 Nov 01:25 | opened 2026-11-09
-- T-150 | OPEN | P1 | Units normalised at write: base-unit value plus the original unit text and scale; read side never converts | accept: zero scale errors in pilot20 sample; ar_facts mn/lakh cases covered by tests | from: Shivam 9 Nov 01:25 | opened 2026-11-09
-- T-151 | OPEN | P1 | Question templates compiled to fact keys: the 1,305 pilot10 questions and harvested sets become templates naming the facts they need; a script reports which templates the store can fill before any answering | accept: coverage report per company set; >=95% of templates fillable or marked not-disclosed before a full run | from: Shivam 9 Nov 01:25 | opened 2026-11-09
-- T-163 | OPEN | P1 | Segment and business-line table from AR segment notes and deck slides (segment, vertical, cluster, brand, subsidiary) with an alias map (NourishCo = RTD); 14 audit questions | accept: the 14 segment questions of the held audit answer by one query on u8/q12 | from: Opus held audit 10 Nov (reports/2026-11-10_held_not_queryable_audit.xlsx) | opened 2026-11-10
+- T-207 | OPEN | P1 | Factor-reward engine, round 1: at every month-end, which held factors were rewarded over the next 6/12/24 months, measured only from returns already realised (trailing window), per sector group and market regime; report the mode of rewarded factors, the dates it shifts, and a walk-forward test of dynamic against static factor choice | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('docs/research/T-207_factor_rewards.md').exists() else 1)" | from: Shivam 13 Nov (idea I-002 promoted) | opened 2026-11-13
```

## 2026-11-13T17:24:08+05:30 | kakazuya (Wolf) | 2a561319 T-207: STATE and ticket board after the merge (ticket waits for Shivam)
```diff
-- T-207 | OPEN | P1 | Factor-reward engine, round 1: at every month-end, which held factors were rewarded over the next 6/12/24 months, measured only from returns already realised (trailing window), per sector group and market regime; report the mode of rewarded factors, the dates it shifts, and a walk-forward test of dynamic against static factor choice | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('docs/research/T-207_factor_rewards.md').exists() else 1)" | from: Shivam 13 Nov (idea I-002 promoted) | opened 2026-11-13
+- T-207 | WAITING Shivam | P1 | Factor-reward engine, round 1: at every month-end, which held factors were rewarded over the next 6/12/24 months, measured only from returns already realised (trailing window), per sector group and market regime; report the mode of rewarded factors, the dates it shifts, and a walk-forward test of dynamic against static factor choice | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('docs/research/T-207_factor_rewards.md').exists() else 1)" | from: Shivam 13 Nov (idea I-002 promoted) | opened 2026-11-13
```

## 2026-11-13T23:56:09+05:30 | kakazuya (Eagle) | 302239ac T-205: r13 brief (Hydrogen answers, Opus medium grades); T-208 unseen stores and T-209 structured la
```diff
+- T-209 | DOING Eagle | P1 | Structured layer at universe scale, script only: every NSE shareholding XBRL since FY24 -> category holdings (promoter, FPI total, MF, insurance, DII, public) and promoter pledge; balance-sheet lines (equity, borrowings, cash, capital employed) from filed results XBRL; one universe store with known_at; feeds the T-207 unmeasured factors (pledge, FPI/MF change, ROE/ROCE) | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/structured/structured_universe.db').exists() else 1)" | from: Shivam 13 Nov | opened 2026-11-13
-- T-205 | OPEN Eagle | P1 | Evidence-pack answerer: script gathers every route per question, model writes from the pack; measure pack recall vs grader truths first | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/bluestar/pack/pack_recall.csv').exists() else 1)" | from: Shivam 13 Nov 12:50 | opened 2026-11-13
+- T-205 | DOING Eagle | P1 | Evidence-pack answerer: script gathers every route per question, model writes from the pack; measure pack recall vs grader truths first | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/bluestar/pack/pack_recall.csv').exists() else 1)" | from: Shivam 13 Nov 12:50 | opened 2026-11-13
+- T-208 | DOING Eagle | P1 | Three unseen test companies (KEI, MEDANTA, PVRINOX from s10): build each pilot3 store from the fetched s10 raw with the Blue Star build parts, register them, coverage report per doc family; feeds the T-205 verdict and the T-172 frozen split | accept: python -c "import pathlib,sys;sys.exit(0 if all(pathlib.Path(f'D:/RealityEngine/s10/{s}/{s}.db').exists() for s in ('kei','medanta','pvrinox')) else 1)" | from: Shivam 13 Nov | opened 2026-11-13
```

## 2026-11-14T00:07:36+05:30 | kakazuya (Eagle) | d630be2f T-210: factor deep study ticket and brief (sectors, companies, combinations, opposites; Shivam 14 No
```diff
+- T-210 | DOING Eagle | P1 | Factor-reward deep study (T-207 round 3): per sector and per company (shrunk to its sector), factor correlations (which move together, which are opposite), redundancy pruning, pairwise interactions and sparse combinations at 6/12/24m, walk-forward with placebo; sector-KPI arm on the 52 companies with KPI series as a labelled method pilot | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('docs/research/T-210_factor_deep_study.md').exists() else 1)" | from: Shivam 14 Nov | opened 2026-11-14
```

## 2026-11-14T00:18:03+05:30 | kakazuya (Eagle) | 02696234 No-ticket: board closes T-177/182/183/185/186/187/189/190 (merged, accepts pass); rulings: Go key 1 
```diff
-- T-177 | OPEN Eagle | P1 | Reference pages (60, half frozen) and per-page completeness report with a build gate | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/v2/reference_pages/reference_cells.csv').exists() else 1)" | from: Fable review 10 Nov | opened 2026-11-10
-- T-182 | OPEN Eagle | P1 | Word boxes for every page: one source (PDF text layer turned upright, else OCR word boxes from ocr_page), with a text-quality verdict (ok / none / jumbled), feeding layout text and the position check | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/v2/page_words.py').exists() else 1)" | from: Shivam 11 Nov 13:45 (settle extraction for every page, text or image; free models code in peak) | opened 2026-11-11
-- T-183 | OPEN Eagle | P1 | Page reader: every table page of a store (text layer or OCR) read by a free model in grid format from layout text, each cell position-checked (verified/unverified), unread numbers counted per page and re-asked once; resumable, written to page_read/page_cell | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/v2/page_reader.py').exists() else 1)" | from: Shivam 11 Nov 13:45 (settle extraction for every page) | opened 2026-11-11
-- T-185 | OPEN Eagle | P1 | Position check v2: columns from header x-ranges (not header-word presence), wrapped row labels, chart panels; and a per-cell verdict that separates reader error from checker miss | accept: python -m pytest -q reality_engine/tests/test_v2_reference_geom.py | from: T-180 result 11 Nov | opened 2026-11-11
-- T-187 | OPEN Eagle | P1 | Guidance round 5: restore 4 management targets the 11 Nov rebuild lost (BEL FY27 margin 25-31%, CIPLA FY24 margin 23-24%, INDHOTEL FY26 capex ~1,100 Cr, APOLLOTYRE FY27 capex 1,200-1,300 Cr); stop keying gross margin as ebitda_margin | accept: python -m pytest -q reality_engine/tests/test_pilot3_guidance.py | from: Eagle rebuild compare 11 Nov | opened 2026-11-11
-- T-189 | OPEN Eagle | P1 | Unseen-company test: AUROPHARMA built end to end with routed page reading (text layer / HP TextRecognizer / Dots on table+chart pages), frozen first-order question set answered via MCP and hand-graded; pass bar 92% right; compare with pilot honest baselines | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/aurobindo/report/grades.csv').exists() else 1)" | from: Shivam 11 Nov 22:30 | opened 2026-11-11
-- T-186 | OPEN Eagle | P1 | Answer-ready fact lookup: one tool call returns the preferred figure with period, basis, unit, source document and page, known_at, and the formula inputs when computed, for any (company, metric, period, basis) | accept: python -m pytest -q plugins/reality-data/tests/test_lookups_pilot3.py | from: Fable review item 7, 11 Nov | opened 2026-11-11
-- T-190 | OPEN Eagle | P1 | HP TextRecognizer stays installed: install once, signing key destroyed, cert only in TrustedPeople; hp_ocr cleanup keeps the package | accept: python -m pytest reality_engine/tests/test_hp_headless.py -q | from: Shivam 12 Nov | opened 2026-11-12
```

## 2026-11-14T01:09:44+05:30 | kakazuya (Eagle) | 8bb77c12 T-209: done on the board
```diff
-- T-209 | DOING Eagle | P1 | Structured layer at universe scale, script only: every NSE shareholding XBRL since FY24 -> category holdings (promoter, FPI total, MF, insurance, DII, public) and promoter pledge; balance-sheet lines (equity, borrowings, cash, capital employed) from filed results XBRL; one universe store with known_at; feeds the T-207 unmeasured factors (pledge, FPI/MF change, ROE/ROCE) | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/structured/structured_universe.db').exists() else 1)" | from: Shivam 13 Nov | opened 2026-11-13
```

## 2026-11-14T02:28:45+05:30 | kakazuya (Wolf) | 51aec310 T-211: T-207 accepted by Shivam as a continuous process; ruling amended (re-run every month-end), T-
```diff
-- T-207 | WAITING Shivam | P1 | Factor-reward engine, round 1: at every month-end, which held factors were rewarded over the next 6/12/24 months, measured only from returns already realised (trailing window), per sector group and market regime; report the mode of rewarded factors, the dates it shifts, and a walk-forward test of dynamic against static factor choice | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('docs/research/T-207_factor_rewards.md').exists() else 1)" | from: Shivam 13 Nov (idea I-002 promoted) | opened 2026-11-13
+- T-211 | OPEN Wolf | P1 | Factor rewards as a standing monthly run (T-207 accepted 14 Nov as a continuous process): after every month-end, refresh the truth snapshot, re-run factor_rewards (and factor_deep once T-210's panel run passes), append the new month's rewarded set, mode and shifts, and report any factor entering, leaving or flipping sign | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('docs/research/FACTOR_REWARDS_MONTHLY.md').exists() else 1)" | from: Shivam 14 Nov 02:30 | opened 2026-11-14
```

## 2026-11-14T02:53:45+05:30 | kakazuya (Wolf) | 12c444e2 T-212: ticket opened (Q2 FY27 results XBRL refresh, universe)
```diff
+- T-212 | DOING Wolf | P1 | Q2 FY27 results XBRL refresh, universe: results_xbrl.db holds 566 filings (307 companies) for 2026-09-30 against ~2,400 for Q1, because the integrated index was last fetched ~2 Nov; refetch the index, download only files not yet parsed, parse, move raw to Drive; repeat after the 14 Nov filing deadline | accept: python -c "import sqlite3,sys;c=sqlite3.connect('reality_engine/data/results_xbrl.db');n=c.execute(\"select count(distinct symbol) from filings where period_end='2026-09-30'\").fetchone()[0];sys.exit(0 if n>=2000 else 1)" | from: Wolf 14 Nov (T-208 evidence) | opened 2026-11-14
```

## 2026-11-14T03:19:12+05:30 | kakazuya (Wolf) | f0e1007c T-213: round 14 brief (planned lookups, code checks, code-written follow-ups; no pack) and ticket
```diff
+- T-213 | DOING Wolf | P1 | Round 14 answer loop: model names exact facts, code fetches only those rows, code checks coverage/numbers/quotes+speaker/not-found probe/kind rules and sends code-written follow-ups (max 2); no pack; DeepSeek (Go) and Hydrogen (agy) adapters | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/tests/test_checked_lookups.py').exists() else 1)" | from: Shivam 14 Nov 03:20 | opened 2026-11-14
```

## 2026-11-14T06:04:26+05:30 | kakazuya (Wolf) | b1392ea5 T-213: waiting on Shivam's design choice
```diff
-- T-213 | DOING Wolf | P1 | Round 14 answer loop: model names exact facts, code fetches only those rows, code checks coverage/numbers/quotes+speaker/not-found probe/kind rules and sends code-written follow-ups (max 2); no pack; DeepSeek (Go) and Hydrogen (agy) adapters | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/tests/test_checked_lookups.py').exists() else 1)" | from: Shivam 14 Nov 03:20 | opened 2026-11-14
+- T-213 | WAITING Shivam | P1 | Round 14 answer loop: model names exact facts, code fetches only those rows, code checks coverage/numbers/quotes+speaker/not-found probe/kind rules and sends code-written follow-ups (max 2); no pack; DeepSeek (Go) and Hydrogen (agy) adapters | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/tests/test_checked_lookups.py').exists() else 1)" | from: Shivam 14 Nov 03:20 | opened 2026-11-14
```

## 2026-11-14T12:55:18+05:30 | kakazuya (Wolf) | b6657c0e T-213: round 15 brief (code checker around the run-B agent answers)
```diff
-- T-213 | WAITING Shivam | P1 | Round 14 answer loop: model names exact facts, code fetches only those rows, code checks coverage/numbers/quotes+speaker/not-found probe/kind rules and sends code-written follow-ups (max 2); no pack; DeepSeek (Go) and Hydrogen (agy) adapters | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/tests/test_checked_lookups.py').exists() else 1)" | from: Shivam 14 Nov 03:20 | opened 2026-11-14
+- T-213 | DOING Wolf | P1 | Round 14 answer loop: model names exact facts, code fetches only those rows, code checks coverage/numbers/quotes+speaker/not-found probe/kind rules and sends code-written follow-ups (max 2); no pack; DeepSeek (Go) and Hydrogen (agy) adapters | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('reality_engine/tests/test_checked_lookups.py').exists() else 1)" | from: Shivam 14 Nov 03:20 | opened 2026-11-14
```

## 2026-11-14T13:00:04+05:30 | kakazuya (Wolf) | 3649588f T-210: low-RAM panel brief for Hydrogen (agy)
```diff
-- T-210 | DOING Eagle | P1 | Factor-reward deep study (T-207 round 3): per sector and per company (shrunk to its sector), factor correlations (which move together, which are opposite), redundancy pruning, pairwise interactions and sparse combinations at 6/12/24m, walk-forward with placebo; sector-KPI arm on the 52 companies with KPI series as a labelled method pilot | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('docs/research/T-210_factor_deep_study.md').exists() else 1)" | from: Shivam 14 Nov | opened 2026-11-14
+- T-210 | DOING Wolf | P1 | Factor-reward deep study (T-207 round 3): per sector and per company (shrunk to its sector), factor correlations (which move together, which are opposite), redundancy pruning, pairwise interactions and sparse combinations at 6/12/24m, walk-forward with placebo; sector-KPI arm on the 52 companies with KPI series as a labelled method pilot | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('docs/research/T-210_factor_deep_study.md').exists() else 1)" | from: Shivam 14 Nov | opened 2026-11-14
```

## 2026-11-15T14:46:02+05:30 | kakazuya (Wolf) | c0bc6621 T-210: review row, ticket done; ignore private Telegram ISIN list
```diff
-- T-210 | DOING Wolf | P1 | Factor-reward deep study (T-207 round 3): per sector and per company (shrunk to its sector), factor correlations (which move together, which are opposite), redundancy pruning, pairwise interactions and sparse combinations at 6/12/24m, walk-forward with placebo; sector-KPI arm on the 52 companies with KPI series as a labelled method pilot | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('docs/research/T-210_factor_deep_study.md').exists() else 1)" | from: Shivam 14 Nov | opened 2026-11-14
```

## 2026-11-15T15:09:01+05:30 | kakazuya (Wolf) | 749eceb8 T-212: post-deadline re-run 5,242 filings / 2,904 symbols; raw swept to Drive; delete-scope caution 
```diff
-- T-212 | DOING Wolf | P1 | Q2 FY27 results XBRL refresh, universe: results_xbrl.db holds 566 filings (307 companies) for 2026-09-30 against ~2,400 for Q1, because the integrated index was last fetched ~2 Nov; refetch the index, download only files not yet parsed, parse, move raw to Drive; repeat after the 14 Nov filing deadline | accept: python -c "import sqlite3,sys;c=sqlite3.connect('reality_engine/data/results_xbrl.db');n=c.execute(\"select count(distinct symbol) from filings where period_end='2026-09-30'\").fetchone()[0];sys.exit(0 if n>=2000 else 1)" | from: Wolf 14 Nov (T-208 evidence) | opened 2026-11-14
```

## 2026-11-15T15:36:05+05:30 | kakazuya (Wolf) | 74dfa004 T-214: Telegram build plan and pre-build fix order; tickets T-214/215/216, T-178 to Wolf, T-205 drop
```diff
+- T-215 | OPEN Wolf | P1 | raw_to_drive delete acts on every on_drive manifest row, not only the --root given (dry run 15 Nov: 127,598 files, 603 GB); limit delete to the given roots, re-check md5 before each delete, test it | accept: python -m pytest reality_engine/tests/test_raw_to_drive.py -q | from: Wolf 15 Nov (T-212 sweep) | opened 2026-11-15
+- T-216 | OPEN Wolf | P2 | agy-worker runner: retry a run once on a transport/DNS error by resuming the same conversation; log the retry | accept: python -m pytest plugins/agy-worker/tests/test_agy_core.py -q | from: Wolf 15 Nov (T-210) | opened 2026-11-15
+- T-214 | OPEN Wolf | P1 | Telegram build: on-demand pilot3 stores for the 93-company queue (D:/RealityEngine/tg_build/build_queue.csv: PEAD score + order win + market cap tiers), fundamentals FY2024-25 onward, script layers first, model reads of table pages only on demand; 10-company measured pilot (time, disk, tokens per company) before the batch | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/tg_build/pilot10_measure.csv').exists() else 1)" | from: Shivam 14-15 Nov | opened 2026-11-15
-- T-178 | OPEN Eagle | P1 | First-build re-key test: ar_facts/deck_figures facts verified + label map + period engine vs script cells on reference pages | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/reports/2026-11-11_t178_first_build_rekey.xlsx').exists() else 1)" | from: Fable review 10 Nov | opened 2026-11-10
+- T-178 | DOING Wolf | P1 | First-build re-key test: ar_facts/deck_figures facts verified + label map + period engine vs script cells on reference pages | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/reports/2026-11-11_t178_first_build_rekey.xlsx').exists() else 1)" | from: Fable review 10 Nov | opened 2026-11-10
-- T-205 | DOING Eagle | P1 | Evidence-pack answerer: script gathers every route per question, model writes from the pack; measure pack recall vs grader truths first | accept: python -c "import pathlib,sys;sys.exit(0 if pathlib.Path('D:/RealityEngine/bluestar/pack/pack_recall.csv').exists() else 1)" | from: Shivam 13 Nov 12:50 | opened 2026-11-13
-- T-208 | DOING Eagle | P1 | Three unseen test companies (KEI, MEDANTA, PVRINOX from s10): build each pilot3 store from the fetched s10 raw with the Blue Star build parts, register them, coverage report per doc family; feeds the T-205 verdict and the T-172 frozen split | accept: python -c "import pathlib,sys;sys.exit(0 if all(pathlib.Path(f'D:/RealityEngine/s10/{s}/{s}.db').exists() for s in ('kei','medanta','pvrinox')) else 1)" | from: Shivam 13 Nov | opened 2026-11-13
```

## 2026-11-15T16:15:35+05:30 | kakazuya (Wolf) | 6f32b35e T-215: raw_to_drive delete only under the call's --root folders (folder-boundary match, refuses with
```diff
-- T-215 | OPEN Wolf | P1 | raw_to_drive delete acts on every on_drive manifest row, not only the --root given (dry run 15 Nov: 127,598 files, 603 GB); limit delete to the given roots, re-check md5 before each delete, test it | accept: python -m pytest reality_engine/tests/test_raw_to_drive.py -q | from: Wolf 15 Nov (T-212 sweep) | opened 2026-11-15
```

## 2026-11-16T00:52:40+05:30 | kakazuya (Wolf) | 3424d670 T-217, T-218: tickets and hand-off for the question bank and modular store repair; STATE, journal, i
```diff
+- T-218 | OPEN Wolf | P1 | Modular store repair: part stamps, store_repair runner (re-run one part across stores with a before/after diff gate) and the store-repair notes system; written by Claude | accept: python -m reality_engine.scripts.store_repair --stale --root D:/RealityEngine/tg_build | from: Shivam 16 Nov | opened 2026-11-16
+- T-217 | OPEN Wolf | P1 | Question bank for the Telegram companies: Gemini 3.8 Flash medium (agy) harvests real investor questions from the web and YouTube per company, then writes grounded variants; questions.db + Excel | accept: python -m reality_engine.scripts.tg_questions check --db D:/RealityEngine/tg_build/questions.db --min-companies 93 | from: Shivam 16 Nov | opened 2026-11-16
```

## 2026-11-16T16:06:07+05:30 | kakazuya (Wolf) | aadb7198 T-219: ruling on local/Drive/GitHub-only tools, unified-items ticket; journal entry for the 16 Nov w
```diff
+- T-219 | OPEN Wolf | P1 | Unified items: tickets, ideas, rulings, store defects in one file-per-item format with generated views; GitHub Issues mirror | accept: python -m pytest -q reality_engine/tests/test_task_board.py | from: Shivam 16 Nov | opened 2026-11-16
```

## 2026-11-16T19:41:04+05:30 | kakazuya (Wolf) | 24700646 T-219 done; T-218: five-point patch write-up (why, problem, missing, fix, next) on every store-repai
```diff
-- T-219 | OPEN Wolf | P1 | Unified items: tickets, ideas, rulings, store defects in one file-per-item format with generated views; GitHub Issues mirror | accept: python -m pytest -q reality_engine/tests/test_task_board.py | from: Shivam 16 Nov | opened 2026-11-16
```

## 2026-11-16T21:18:20+05:30 | kakazuya (Wolf) | 188f5ea4 T-221: ticket for the page_route fetch-on-first-need follow-up
```diff
+- T-221 | DOING Wolf | P2 | T-220 follow-up: page_route downloads a Drive PDF on first need per document (RawStore.keep); prefetch-all was 2x slower | accept: python -m pytest -q reality_engine/tests/test_raw_store.py reality_engine/tests/test_v2_page_route.py | from: Shivam 16 Nov | opened 2026-11-16
```

## 2026-11-16T21:26:21+05:30 | kakazuya (Wolf) | e7cd3157 T-221 done; STATE notes the 91 build and the speed-ups
```diff
-- T-221 | DOING Wolf | P2 | T-220 follow-up: page_route downloads a Drive PDF on first need per document (RawStore.keep); prefetch-all was 2x slower | accept: python -m pytest -q reality_engine/tests/test_raw_store.py reality_engine/tests/test_v2_page_route.py | from: Shivam 16 Nov | opened 2026-11-16
```

## 2026-11-17T15:25:57+05:30 | kakazuya (Eagle) | 9ec7e62b T-222 R-015: annual-report cash-flow reader (pilot3/ar_statements.py, part ar_statements) in all 91 
```diff
+- T-223 | OPEN Eagle | P1 | Small-company core documents (Shivam 17 Nov): (1) segment note and results segment tables into rows; (2) borrowings/debt note; (3) revenue break-up and PP&E/CWIP notes; (4) small companies: annual report, quarterly results, credit-rating documents and ad hoc announcements (order wins, material gain/loss, audit, management change) held and read for every store | accept: python -m pytest -q reality_engine/tests/test_ar_statements.py | from: Shivam 17 Nov | opened 2026-11-17
```

## 2026-11-18T01:26:34+05:30 | kakazuya (Eagle) | 3afe02e4 T-223: STATE under 4,000 characters (dropped the 11 Nov merged list, in docs/state_history)
```diff
+- T-224 | OPEN Eagle | P1 | Model router: read OpenCode Go account-1 usage % (rolling 24 h) and send coding to agy Hydrogen high when DeepSeek is in peak hours or usage >10%; dsh start_worker reports the route | accept: Shivam: router reads the Go usage % with no manual step | from: Shivam 17 Nov | opened 2026-11-17
```

## 2026-11-18T21:04:44+05:30 | kakazuya (Eagle) | 0e8a626a T-225 session close: blend ticket, NAVKAR parent-transcript ruling, raw folder docs, journal
```diff
+- T-225 | OPEN Eagle | P1 | Model + script blend for page figures: rebuild the figure checker first, then Dots reads pages and the checker settles rows; first test on held stores c09 c31 c61 c87 c88 | accept: Shivam: on a frozen hand-read page set the checker keeps >=95% of right cells and verifies zero wrong cells; 5 held stores repaired with zero right rows lost | from: Shivam 18 Nov | opened 2026-11-18
```

## 2026-11-19T20:01:19+05:30 | kakazuya (Eagle) | ef47f777 T-226: open ticket; STATE - script-first reader on branch, review running; 18 Nov repair detail to s
```diff
+- T-226 | DOING Eagle | P1 | Script-first page reading: model-free table reader + cross-filing gate (two filings 45+ days apart print the same value for the same line and period), measured against model-verified cells | accept: python -m pytest reality_engine/tests/test_v2_script_reader.py -q | from: Shivam 2026-11-19 | opened 2026-11-19
```

## 2026-11-20T12:26:38+05:30 | kakazuya (Eagle) | 73af932b T-227: script_cell store writer and pilot3_cells script_rows (option 1); 10 measured stores written,
```diff
+- T-227 | DOING Eagle | P1 | Store writer for script-read cells: script_cell table in each company store, served by pilot3_cells beside existing rows (option 1); precedence over printed rows only after a frozen-set answer test (option 2) | accept: python -m pytest reality_engine/tests/test_v2_script_cells.py reality_engine/tests/test_v2_script_reader.py -q | from: Shivam 2026-11-20 | opened 2026-11-20
```

## 2026-11-20T22:51:39+05:30 | kakazuya (Wolf) | 6bf821e3 T-228: ticket and stage 1a brief (driver-tree claims from management text, hy4-flash-free)
```diff
+- T-228 | DOING Wolf | P1 | Driver-tree claims: turn verbatim management text (call statements, guidance) into quantified claims on revenue (volume x price), operating cost, capex/capacity, debt and equity, read by hy4-flash-free on Go (free, run unleashed to measure its real quota); then our forward estimate (B) and management credibility (C), and test whether B+C add prediction over the hard-number factors (T-210 panel) | accept: Shivam | from: Shivam 20 Nov | opened 2026-11-20
```

## 2026-11-21T00:04:29+05:30 | kakazuya (Wolf) | c5fde66f T-229: ticket and stage A brief (factor study on the 91 stores)
```diff
+- T-229 | DOING Wolf | P1 | Factor study on the 91 Telegram stores: store-derived point-in-time factors (financial lines, margins, valuation, debt, holdings, guidance, order book) against 3/6/12-month forward excess returns, with a store-vs-XBRL-panel check and a matched random control set to measure the selection bias of the 91 | accept: Shivam | from: Shivam 21 Nov | opened 2026-11-21
```

## 2026-11-21T00:24:34+05:30 | kakazuya (Wolf) | 93a222d7 T-230: deck/visual observation schema ticket (promotes I-016, Shivam 21 Nov)
```diff
+- T-230 | OPEN Wolf | P1 | Observation schema for deck and note visuals (maps, bars, pies, plant lists): one row per printed quantity with measure, value, unit, period, dims (segment, product, geography, plant, customer), group path and project stage (operating / approved / under review / potential), series identity (which chart), entity scope (company / subsidiary / industry / country / customer), verbatim label and axis, source page + region, known_at, status; measure dictionary and dimension vocabularies; script-derived breakups (capacity or revenue by region/plant) with parts-sum-to-total and cross-document checks | accept: Shivam | from: Shivam 21 Nov (promotes I-016) | opened 2026-11-21
```

## 2026-11-21T13:26:41+05:30 | kakazuya (Wolf) | 6e8085df T-231: filing-level event table brief
```diff
+- T-231 | OPEN Wolf | P1 | Filing-level event table: order wins, capex approvals, fund raises (one row per filing) for the factor study | accept: Shivam | from: Wolf 21 Nov (plan step 2) | opened 2026-11-21
```

## 2026-11-21T15:29:06+05:30 | kakazuya (Wolf) | 8db0a480 T-232: deck stores brief; T-230 stage G dictionary brief
```diff
+- T-232 | OPEN Wolf | P1 | Minimal deck stores (doc, doc_page, routes) for the 403 non-91 Telegram companies with decks since FY25 | accept: Shivam | from: Shivam 21 Nov | opened 2026-11-21
```

## 2026-11-21T15:42:21+05:30 | kakazuya (Wolf) | 6c3cc0be T-233: fast fix loop brief (golden sets + scoped re-runs)
```diff
+- T-233 | OPEN Wolf | P1 | Fast fix loop: golden regression sets from every hand read + selector-scoped re-runs for observations, filing events and claims | accept: Shivam | from: Shivam 21 Nov | opened 2026-11-21
```

## 2026-11-22T00:20:39+05:30 | kakazuya (Wolf) | 8a6380ed T-234: free-model reader bake-off brief
```diff
+- T-234 | OPEN Wolf | P1 | Free-model reader bake-off: Gemma 4 31B, Nemotron VL, Ling, Particle (image pages); ERNIE 5.5, Nemotron Ultra (text pages) vs hy4 on quality, precision, accuracy, speed, tokens | accept: Shivam | from: Shivam 22 Nov | opened 2026-11-22
```

## 2026-11-22T14:53:10+05:30 | kakazuya (Wolf) | 08f19e7a T-235: capital-flow early-warning stage 1 brief; T-236 backfill ticket
```diff
+- T-236 | OPEN Wolf | P1 | Market data backfill 2010-2018: NSE/BSE prices + delivery, bulk/block, insider/SAST, corporate actions, FII/DII, NSDL FPI, indices | accept: Shivam | from: Shivam 22 Nov | opened 2026-11-22
+- T-235 | OPEN Wolf | P1 | Capital-flow early warning: daily per-stock flow signals (delivery, insider/promoter, bulk/block, ownership, earnings, red flags) + event study (after-signal returns, before-big-move look-back, combinations), back-test 2010+ | accept: Shivam | from: Shivam 22 Nov | opened 2026-11-22
```

## 2026-11-22T20:24:19+05:30 | kakazuya (Wolf) | 58288837 T-230: stage L review logged
```diff
+- T-237 | OPEN Wolf | P1 | Opus deep-read case study: 2 companies (SOMANYCERA, RSWM) - ARs, transcripts, decks, ratings into dictionary facts (NEW ids allowed), then query with technicals: are fundamental factors recoverable? | accept: Shivam | from: Shivam 22 Nov | opened 2026-11-22
```

## 2026-11-22T22:56:08+05:30 | kakazuya (Wolf) | 80cacbfb T-238: briefs for OCR-routed pages and the transcript reader
```diff
+- T-238 | OPEN Wolf | P1 | Close hy4 coverage gaps found in T-237: OCR-routed deck pages, call transcripts, measure disagreements | accept: Shivam | from: Shivam 22 Nov | opened 2026-11-22
```

## 2026-11-23T10:44:14+05:30 | kakazuya (Wolf) | 31497832 T-239: ticket and wiring brief
```diff
+- T-239 | DOING Wolf | P1 | Serve hy4 observations (decks, AR, transcripts) and T-231 events from the 91 stores via MCP, then a 200 frozen-question answer trial (DeepSeek answers, Opus grades) vs trial 1 | accept: Shivam | from: Shivam 23 Nov | opened 2026-11-23
```

## 2026-11-23T10:53:40+05:30 | kakazuya (Wolf) | cdf1c465 T-240: fetcher retries BSE non-JSON 200 pages, splits, skips a refused window
```diff
+- T-240 | DOING Wolf | P1 | Full store build for the 394 Telegram companies outside the 91: raw fetch (BSE+NSE since FY25), T-214 recipe stores in shards, then hy4 reads (transcripts, results, OCR'd decks; ARs after) | accept: Shivam | from: Shivam 23 Nov | opened 2026-11-23
```

## 2026-11-23T17:02:21+05:30 | kakazuya (Wolf) | 6b0cefc9 T-241: tg_measure_build --window-start (universe FY27 build)
```diff
+- T-241 | DOING Wolf | P1 | Universe store build for FY2026-27: every company that filed on BSE/NSE since 2026-04-01 (~5,170), raw fetch + script stores in shards + observations where hy4 quota allows, uploaded to gdrive by 27 Nov | accept: Shivam | from: Shivam 23 Nov | opened 2026-11-23
```

## 2026-11-24T14:13:35+05:30 | kakazuya (Wolf) | 11d75d61 T-242: ticket - hy4 free window, verified reading of decks, transcripts, AR sections, order filings
```diff
+- T-242 | OPEN Wolf+Eagle | P1 | hy4 free window: read decks, transcripts, useful AR sections and order filings, verified, into objective rows | accept: python -m reality_engine.v2.read_gate status | from: Shivam 24 Nov ~14:00 | opened 2026-11-24
```

## 2026-11-25T21:29:32+05:30 | kakazuya (Wolf) | 30c065b6 T-243: ticket + guide heading
```diff
+- T-243 | DOING Wolf | P1 | Skills catalog + rule hooks: repeatable workflows as project skills; standing rules enforced by a PreToolUse hook | accept: python -m pytest -q reality_engine/tests/test_rule_guard.py | from: Shivam 25 Nov 21:20 | opened 2026-11-25
```

## 2026-11-26T01:32:32+05:30 | kakazuya (Wolf) | 454d0b7b T-244: ticket - dsh launcher control-bind flake
```diff
+- T-244 | OPEN | P2 | dsh launcher: heartbeat control channel fails to bind at start (exit 126) | accept: python -m pytest plugins/dsh-worker/tests -q -k control_bind | from: manual | opened 2026-11-26
```

## 2026-11-26T17:04:41 | kakazuya (Wolf) | branch main
```diff
+- T-245 | OPEN Wolf | P1 | Lean MSI by Fri 27 Nov 10:00 IST: data-heavy files to Drive, laptop stays a cloud box over RDP | accept: python reality_engine/scripts/drive_upload_check.py reports every moved folder present on gdrive:InfoDiffusion_archive with matching hashes and the post-move disk inventory shows no data-heavy folder left local | from: manual | opened 2026-11-26
```
