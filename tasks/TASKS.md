# Tickets

One row per line, kept in its section: `- T-014 | DOING Wolf | P1 | title | accept: <command or Shivam> | from: <source> | opened 2026-11-01`
Statuses: `OPEN`, `LOOKING`, `DOING <owner>`, `WAITING <who>`; priorities `P1`-`P3`. No `|` inside a field.
Closed rows move to `tasks/TASKS_DONE.md`: `python -m reality_engine.scripts.task_board done T-014`.
Card and full list: `python -m reality_engine.scripts.task_board card` / `list`.

## Workspace
- T-001 | OPEN | P1 | Enforce worker tool-call budgets in code; a worker used 266+ against 120, and another 181 against 150 | accept: python -m pytest reality_engine/tests/test_worker_budget.py -q | from: STATE 1 Nov | opened 2026-11-02
- T-002 | OPEN | P1 | Block by hook: git push, private folder reads, printed keys, --no-verify, gate edits, git stash, full suite on the MSI | accept: python -m pytest reality_engine/tests/test_enforcement_hooks.py -q | from: enforcement plan | opened 2026-11-02
- T-003 | OPEN | P1 | Merge gate: tests, doc gate, accept check, Docs updated line, hidden evaluation, rulings diff (workspace step 3) | accept: python -m pytest reality_engine/tests/test_merge_gate.py -q | from: workspace plan step 3 | opened 2026-11-02
- T-005 | OPEN | P2 | Cap code workers at 2 and refuse new ones while a branch is over 24 hours old | accept: python -m pytest reality_engine/tests/test_worker_limits.py -q | from: enforcement plan | opened 2026-11-02
- T-006 | OPEN | P2 | Find why the full test suite reaches 7.5 GB; run it on the HP, not the MSI | accept: Shivam | from: STATE 1 Nov | opened 2026-11-02
- T-007 | OPEN | P2 | Fix test_commit_replays_the_identity, which fails when the launcher sets GIT_AUTHOR_NAME | accept: python -m pytest reality_engine/tests/test_dsh_worker_sandbox.py reality_engine/tests/test_dsh_worker_stress.py -k test_commit_replays -q | from: STATE 1 Nov | opened 2026-11-02
- T-008 | OPEN | P2 | Versioned git hooks with an install command and a session start warning when they differ | accept: python -m pytest reality_engine/tests/test_hooks_installed.py -q | from: enforcement plan | opened 2026-11-02
- T-009 | OPEN | P2 | SessionEnd hook runs the doc sweep; next session start prints any failure | accept: python -m pytest reality_engine/tests/test_session_end_sweep.py -q | from: enforcement plan | opened 2026-11-02
- T-010 | OPEN | P2 | One model-call function with an allowlist: free models and DeepSeek only | accept: python -m pytest reality_engine/tests/test_model_allowlist.py -q | from: Shivam ruling 1 Nov | opened 2026-11-02
- T-011 | OPEN | P3 | Remove AGENTS conflicts: FRAMEWORK first against read nothing else first; rule 1 says ISINs never change | accept: Shivam | from: enforcement plan | opened 2026-11-02
- T-042 | OPEN | P1 | Rule and chain-of-command ledger: log every gate block, budget overrun, bypass and who did the work; daily report by rule of enforced, sidelined and unmeasured | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
- T-044 | OPEN | P1 | Catch finished, stalled and failed jobs in code, at any effort level: list_workers shows the newest and running first, and a status command feeds a hook on every prompt | accept: python -m pytest reality_engine/tests/test_job_watch.py -q | from: Shivam 2 Nov | opened 2026-11-02
- T-053 | OPEN | P1 | Stress-test and harden job_watch wait and the Stop hook: race before baseline, corrupt status, many jobs, killed or duplicate waiters, pid reuse, registered stalls | accept: python -m pytest reality_engine/tests/test_job_watch_stress.py reality_engine/tests/test_job_watch.py reality_engine/tests/test_session_hooks.py -q | from: Shivam, 3 Nov | opened 2026-11-03
- T-071 | OPEN | P2 | dsh worker sandbox and stress tests fail on the T-054 Evidence field and the launcher identity; refresh their shared brief fixture | accept: python -m pytest reality_engine/tests/test_dsh_worker_sandbox.py -q | from: T-069 review | opened 2026-11-05
- T-075 | OPEN | P1 | Prototype next-round in the same worker session: Opus reviews finished output, then guides it in that session. --followup-wait keeps a worker waiting only up to 3600 s and HP has no channel; find or build resume after that, and measure tokens and hand-read score | accept: Shivam | from: Paper pointer 2, Shivam 5 Nov | opened 2026-11-05
- T-076 | OPEN | P2 | Trial: two KPI fix rounds run strictly one at a time, answer and data jobs in parallel; compare rows lost between rounds | accept: Shivam | from: Paper pointer 3, Shivam 5 Nov | opened 2026-11-05
- T-077 | OPEN | P2 | Prototype a shared defect-type list that parallel workers read and append (Beam KPI batches, answer runs); measure repeat slips such as ten-times units | accept: Shivam | from: Paper pointer 4, Shivam 5 Nov | opened 2026-11-05
- T-078 | OPEN | P2 | Audit each hook and gate against the last failure it stopped; propose removals for Shivam; test one versioned worker pipeline file | accept: Shivam | from: Paper pointer 5, Shivam 5 Nov | opened 2026-11-05
- T-082 | OPEN | P2 | dsh workers pane: show stable session id, cached tokens, total tokens and median tokens per second on the band above the prompt and on the detail card | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
- T-096 | OPEN | P1 | job_watch wakes Claude at once when a worker with a follow-up wait ends its turn, and shows live tool counts: awaiting_input now reads as RUNNING until the 10-minute stall | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06

## Data
- T-021 | LOOKING | P3 | Check if still open: PIB phase 2, Hindi, Urdu and regional offices | accept: Shivam | from: tasks/PIPELINE_TODO.md A2 | opened 2026-11-02
- T-022 | LOOKING | P3 | Check if still open: policy register at scale, with stage threads and company mapping | accept: Shivam | from: tasks/PIPELINE_TODO.md A3 | opened 2026-11-02
- T-023 | LOOKING | P3 | Check if finished: shareholding and pledge backfill, marked running on 19 Oct | accept: Shivam | from: tasks/PIPELINE_TODO.md B3 | opened 2026-11-02
- T-024 | LOOKING | P3 | Check if still open: index membership history | accept: Shivam | from: tasks/PIPELINE_TODO.md Phase C | opened 2026-11-02
- T-025 | LOOKING | P3 | Check if still open: parse value, customer and execution period from exchange order-win filings | accept: Shivam | from: tasks/PIPELINE_TODO.md Phase C | opened 2026-11-02
- T-037 | OPEN | P1 | Fetch KEC's call transcripts from kecrpg.com; its 10 filed concalls are cover letters | accept: Shivam | from: Pilot 2 Nov | opened 2026-11-02
- T-041 | OPEN | P2 | All 74 results_notes docs in chunks_v3_pilot point at a deleted worktree; raw PDFs are gone. 3 pilot ones refetched to D but their hash differs from the stored one, so check pages and fix raw_path | accept: Shivam | from: T-040 2 Nov | opened 2026-11-02
- T-046 | OPEN | P2 | List the 10 documents the 31 Oct reader test found absent and check whether they exist at the source; moved from the old work queue | accept: Shivam | from: manual | opened 2026-11-02
- T-099 | WAITING Shivam | P1 | Holiday copies in daily_price_delivery: fix nse_client.fetch_bhavcopy date check, delete 111,535 rows by the T-089 plan, replace 2021-11-04 Muhurat session, rebuild indicators | accept: Shivam | from: T-089 report 7 Nov | opened 2026-11-07

## OCR and extraction
- T-020 | OPEN | P2 | OCR after workspace step 4: TextRecognizer first pass, stronger reader for low-confidence numbers; last accuracy pilot failed its gate | accept: Shivam | from: RULINGS, GATE_STATE | opened 2026-11-02
- T-029 | OPEN | P3 | When OCR resumes after workspace step 4: decide a second Haiku baseline on about 100 fresh pages, batches of 8; first run: 100 pages, 995,856 tokens | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
- T-034 | DOING Wolf | P1 | Pilot: page text for the thin BAJFINANCE, HINDALCO and KEC documents, by HP TextRecognizer | accept: Shivam | from: PROTOTYPE3 grade change 2 | opened 2026-11-02
- T-040 | OPEN | P1 | Pilot: OCR every page of the 3 companies and mark each extracted number confirmed or disputed against the text layer | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
- T-052 | OPEN | P1 | pilot3 OCR run to completion over every needs_ocr page (sandbox and pages.db), then rebuild pilot3.db with the OCR pages | accept: Shivam | from: Shivam, 3 Nov | opened 2026-11-03
- T-068 | OPEN | P1 | Settle doubtful KPI rows with free beam-free on both Go keys, as a step after the build with saved verdicts; gate its accuracy on hand-read rows before use | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
- T-079 | OPEN | P1 | Trial one KPI round on a goal brief: keep evidence and fast check, drop edit-this-line steps; goal hand-read 18 of 20 on INFY and HINDALCO, checkpages at least 145 | accept: Shivam | from: Shivam 5 Nov, go given | opened 2026-11-05
- T-081 | OPEN | P1 | KPI round 4: the wrong classes Opus found after T-079 (a loss stored positive, subsidiary figures as total, quarter dated to the year, non-revenue lines as revenue, question text as a value) | accept: Opus hand read on an unused seed | from: T-079 review 5 Nov | opened 2026-11-05

## Schema and question map
- T-017 | OPEN | P2 | Full-run guard: chunk, embed and load scripts refuse a full run with no pilot pass file | accept: python -m pytest reality_engine/tests/test_full_run_guard.py -q | from: enforcement plan | opened 2026-11-02
- T-032 | OPEN | P2 | Gate reports show only the hand-read score: tasks/pilot60/gate_run.py still prints the format score | accept: Shivam | from: Shivam ruling 2 Nov | opened 2026-11-02
- T-035 | OPEN | P1 | Pilot: rerun extraction on the 3 companies, answer the same questions, grade by reading | accept: Shivam | from: PROTOTYPE3 grade change 5 | opened 2026-11-02
- T-036 | OPEN | P2 | Split fact.value into numeric and text, and test metric_citations on the prototype | accept: Shivam | from: T-016 | opened 2026-11-02
- T-038 | OPEN | P1 | Wire contract-passing extract rows into the fact view; answer narrative questions with retrieved quoted passages, no model | accept: Shivam | from: Pilot 2 Nov | opened 2026-11-02
- T-048 | OPEN | P1 | One-company gap loop: 100 sector-fit questions for KEC, Haiku sessions under 100k fill gaps by extraction or computation in a sandbox, Opus manages; replicate to 3, then 60 | accept: Shivam | from: Shivam, 2 Nov | opened 2026-11-02
- T-049 | OPEN | P1 | Script extraction for the 3 pilot companies: rule-based scripts (no LLM; AI OCR only for image pages within budget) read all raw documents of KEC, BAJFINANCE, HINDALCO into the schema of tasks/arch_v4/T048_FINDINGS_AND_SCHEMA_2026-11-03.md in SQLite/DuckDB; answers only via MCP over that db; target the pilot's AI answer quality | accept: Shivam | from: Shivam, 3 Nov | opened 2026-11-03
- T-092 | OPEN | P1 | Complete, named guidance from letters and calls, with the store count and growth targets the ETERNAL answers had to dig for; universal rules | accept: Shivam | from: Shivam 6 Nov, T-088 re-test | opened 2026-11-06
- T-094 | OPEN | P1 | Universe readiness: no hand lists of companies in build or tools (LENDERS in ratios.py, kpi.COMPANIES, gap_loop COMPANIES, docs_collect KEC manifest), sector from data, per-company time and size measured and projected to 6,940 companies, and an unchanged build on companies never seen | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
- T-095 | OPEN | P1 | Re-ask the same 20 questions with the T-088 brief after T-090, T-091 and T-092, Opus read blind | accept: Shivam | from: Shivam 6 Nov | opened 2026-11-06
- T-085 | OPEN | P1 | Number check passes invented or wrong figures: MARUTI-102 in `answer_a3\second_read\fix_test\arm_plain` writes Rs 5,33,555 crore for 5.33555e+11 rupees (53,355.5 crore); INFY-005 in `arm_flags` has inputs 43,278, 46,347, 49,012, 50,699 that sum to the right total but are not the filed quarters (Q2 49,244). Catch both with no new false alarm on the 600 answers | accept: python -m pytest reality_engine/tests/test_pilot3_number_check.py -q | from: Eagle 6 Nov, T-083 read | opened 2026-11-06
- T-083 | DOING Eagle | P1 | Second reading step: a free model reads each answer against the question and the answer's own numbers and flags contradictions, unsourced causes and question misfit; test on graded answers before any use | accept: Shivam | from: Shivam 5 Nov | opened 2026-11-05
- T-098 | OPEN | P1 | Build applies window_start to documents, not only stores: scratch builds from the pilot60_history manifest held 2019+ documents (hold6 531 of 611 guidance targets before 2024-04-01); re-measure T-094's 501 GB and 52 h projection on windowed documents | accept: Shivam | from: Wolf 6 Nov, T-092 hold-out read | opened 2026-11-06
- T-100 | OPEN | P1 | Prototype an announcement category allow-list (Shivam approves the list first) and re-measure per-company size on 2024-04+ documents with it; project to 6,940 | accept: Shivam | from: Shivam 7 Nov | opened 2026-11-07

## Bank
- T-018 | OPEN | P2 | Refuse a bank rebuild that changes the frozen 1,901 questions or ruled rows, or names a non-pilot stock | accept: python -m pytest reality_engine/tests/test_bank_guard.py -q | from: enforcement plan | opened 2026-11-02

## Research
- T-027 | OPEN | P3 | Trading limits module the test harness cannot run without, when backtests resume | accept: python -m pytest reality_engine/tests/test_trading_limits.py -q | from: tasks/FRAMEWORK.md | opened 2026-11-02
- T-031 | OPEN | P3 | Research library bucket scheme; duplicates deleted 2 Nov, list in _dupes_deleted_2026-11-02.csv | accept: Shivam | from: T-026 | opened 2026-11-02

## Machines
