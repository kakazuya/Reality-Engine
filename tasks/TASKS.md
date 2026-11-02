# Tickets

One row per line, kept in its section: `- T-014 | DOING Wolf | P1 | title | accept: <command or Shivam> | from: <source> | opened 2026-11-01`
Statuses: `OPEN`, `LOOKING`, `DOING <owner>`, `WAITING <who>`; priorities `P1`-`P3`. No `|` inside a field.
Closed rows move to `tasks/TASKS_DONE.md`: `python -m reality_engine.scripts.task_board done T-014`.
Card and full list: `python -m reality_engine.scripts.task_board card` / `list`.

## Workspace
- T-001 | OPEN | P1 | Enforce worker tool-call budgets in code; a worker used 266+ against 120, and another 181 against 150 | accept: python -m pytest reality_engine/tests/test_worker_budget.py -q | from: STATE 1 Nov | opened 2026-11-02
- T-002 | OPEN | P1 | Block by hook: git push, private folder reads, printed keys, --no-verify, gate edits, git stash, full suite on the MSI | accept: python -m pytest reality_engine/tests/test_enforcement_hooks.py -q | from: enforcement plan | opened 2026-11-02
- T-003 | OPEN | P1 | Merge gate: tests, doc gate, accept check, Docs updated line, hidden evaluation, rulings diff (workspace step 3) | accept: python -m pytest reality_engine/tests/test_merge_gate.py -q | from: workspace plan step 3 | opened 2026-11-02
- T-004 | OPEN | P1 | Final count and verdict on the 9 efficiency fixes, due the night of 1 Nov | accept: Shivam | from: tasks/efficiency/FIX_TRACKER_2026-10-31.md | opened 2026-11-02
- T-005 | OPEN | P2 | Cap code workers at 2 and refuse new ones while a branch is over 24 hours old | accept: python -m pytest reality_engine/tests/test_worker_limits.py -q | from: enforcement plan | opened 2026-11-02
- T-006 | OPEN | P2 | Find why the full test suite reaches 7.5 GB; run it on the HP, not the MSI | accept: Shivam | from: STATE 1 Nov | opened 2026-11-02
- T-007 | OPEN | P2 | Fix test_commit_replays_the_identity, which fails when the launcher sets GIT_AUTHOR_NAME | accept: python -m pytest reality_engine/tests/test_dsh_worker_sandbox.py reality_engine/tests/test_dsh_worker_stress.py -k test_commit_replays -q | from: STATE 1 Nov | opened 2026-11-02
- T-008 | OPEN | P2 | Versioned git hooks with an install command and a session start warning when they differ | accept: python -m pytest reality_engine/tests/test_hooks_installed.py -q | from: enforcement plan | opened 2026-11-02
- T-009 | OPEN | P2 | SessionEnd hook runs the doc sweep; next session start prints any failure | accept: python -m pytest reality_engine/tests/test_session_end_sweep.py -q | from: enforcement plan | opened 2026-11-02
- T-010 | OPEN | P2 | One model-call function with an allowlist: free models and DeepSeek only | accept: python -m pytest reality_engine/tests/test_model_allowlist.py -q | from: Shivam ruling 1 Nov | opened 2026-11-02
- T-011 | OPEN | P3 | Remove AGENTS conflicts: FRAMEWORK first against read nothing else first; rule 1 says ISINs never change | accept: Shivam | from: enforcement plan | opened 2026-11-02
- T-028 | OPEN | P2 | Clear the doc sweep: 26 references in old docs point at files that no longer exist | accept: python reality_engine/scripts/doc_gate.py --sweep | from: sweep 2 Nov | opened 2026-11-02
- T-042 | OPEN | P1 | Rule and chain-of-command ledger: log every gate block, budget overrun, bypass and who did the work; daily report by rule of enforced, sidelined and unmeasured | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
- T-043 | OPEN | P1 | Worker review log: tool calls, thinking and output tokens, job type, time, and Claude's review of prompt, permissions and scope, for every dsh worker and Claude session | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
- T-044 | OPEN | P1 | Catch finished, stalled and failed jobs in code, at any effort level: list_workers shows the newest and running first, and a status command feeds a hook on every prompt | accept: python -m pytest reality_engine/tests/test_job_watch.py -q | from: Shivam 2 Nov | opened 2026-11-02
- T-047 | OPEN | P3 | Session titles: keep the sv/neo prefix, let each session choose the rest | accept: A new session started by claude-neo or claude-sv with no task shows <prefix>-<title chosen by that session> | from: Shivam, 2 Nov | opened 2026-11-02

## Data
- T-021 | LOOKING | P3 | Check if still open: PIB phase 2, Hindi, Urdu and regional offices | accept: Shivam | from: tasks/PIPELINE_TODO.md A2 | opened 2026-11-02
- T-022 | LOOKING | P3 | Check if still open: policy register at scale, with stage threads and company mapping | accept: Shivam | from: tasks/PIPELINE_TODO.md A3 | opened 2026-11-02
- T-023 | LOOKING | P3 | Check if finished: shareholding and pledge backfill, marked running on 19 Oct | accept: Shivam | from: tasks/PIPELINE_TODO.md B3 | opened 2026-11-02
- T-024 | LOOKING | P3 | Check if still open: index membership history | accept: Shivam | from: tasks/PIPELINE_TODO.md Phase C | opened 2026-11-02
- T-025 | LOOKING | P3 | Check if still open: parse value, customer and execution period from exchange order-win filings | accept: Shivam | from: tasks/PIPELINE_TODO.md Phase C | opened 2026-11-02
- T-037 | OPEN | P1 | Fetch KEC's call transcripts from kecrpg.com; its 10 filed concalls are cover letters | accept: Shivam | from: Pilot 2 Nov | opened 2026-11-02
- T-041 | OPEN | P2 | All 74 results_notes docs in chunks_v3_pilot point at a deleted worktree; raw PDFs are gone. 3 pilot ones refetched to D but their hash differs from the stored one, so check pages and fix raw_path | accept: Shivam | from: T-040 2 Nov | opened 2026-11-02
- T-046 | OPEN | P2 | List the 10 documents the 31 Oct reader test found absent and check whether they exist at the source; moved from the old work queue | accept: Shivam | from: manual | opened 2026-11-02

## OCR and extraction
- T-020 | OPEN | P2 | OCR after workspace step 4: TextRecognizer first pass, stronger reader for low-confidence numbers; last accuracy pilot failed its gate | accept: Shivam | from: RULINGS, GATE_STATE | opened 2026-11-02
- T-029 | OPEN | P3 | When OCR resumes after workspace step 4: decide a second Haiku baseline on about 100 fresh pages, batches of 8; first run: 100 pages, 995,856 tokens | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
- T-034 | DOING Wolf | P1 | Pilot: page text for the thin BAJFINANCE, HINDALCO and KEC documents, by HP TextRecognizer | accept: Shivam | from: PROTOTYPE3 grade change 2 | opened 2026-11-02
- T-040 | OPEN | P1 | Pilot: OCR every page of the 3 companies and mark each extracted number confirmed or disputed against the text layer | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02

## Schema and question map
- T-017 | OPEN | P2 | Full-run guard: chunk, embed and load scripts refuse a full run with no pilot pass file | accept: python -m pytest reality_engine/tests/test_full_run_guard.py -q | from: enforcement plan | opened 2026-11-02
- T-032 | OPEN | P2 | Gate reports show only the hand-read score: tasks/pilot60/gate_run.py still prints the format score | accept: Shivam | from: Shivam ruling 2 Nov | opened 2026-11-02
- T-035 | OPEN | P1 | Pilot: rerun extraction on the 3 companies, answer the same questions, grade by reading | accept: Shivam | from: PROTOTYPE3 grade change 5 | opened 2026-11-02
- T-036 | OPEN | P2 | Split fact.value into numeric and text, and test metric_citations on the prototype | accept: Shivam | from: T-016 | opened 2026-11-02
- T-038 | OPEN | P1 | Wire contract-passing extract rows into the fact view; answer narrative questions with retrieved quoted passages, no model | accept: Shivam | from: Pilot 2 Nov | opened 2026-11-02
- T-048 | OPEN | P1 | One-company gap loop: 100 sector-fit questions for KEC, Haiku sessions under 100k fill gaps by extraction or computation in a sandbox, Opus manages; replicate to 3, then 60 | accept: Shivam | from: Shivam, 2 Nov | opened 2026-11-02
- T-049 | OPEN | P1 | Script extraction for the 3 pilot companies: rule-based scripts (no LLM; AI OCR only for image pages within budget) read all raw documents of KEC, BAJFINANCE, HINDALCO into the schema of tasks/arch_v4/T048_FINDINGS_AND_SCHEMA_2026-11-03.md in SQLite/DuckDB; answers only via MCP over that db; target the pilot's AI answer quality | accept: Shivam | from: Shivam, 3 Nov | opened 2026-11-03

## Bank
- T-018 | OPEN | P2 | Refuse a bank rebuild that changes the frozen 1,901 questions or ruled rows, or names a non-pilot stock | accept: python -m pytest reality_engine/tests/test_bank_guard.py -q | from: enforcement plan | opened 2026-11-02
- T-039 | WAITING Shivam | P2 | Rule on 21 NOT IN DATA labels with inputs held: 12 grouped with peers, 9 single-company, 13 carry evidence | accept: Shivam | from: Question map 2 Nov | opened 2026-11-02

## Research
- T-027 | OPEN | P3 | Trading limits module the test harness cannot run without, when backtests resume | accept: python -m pytest reality_engine/tests/test_trading_limits.py -q | from: tasks/FRAMEWORK.md | opened 2026-11-02
- T-031 | OPEN | P3 | Research library bucket scheme; duplicates deleted 2 Nov, list in _dupes_deleted_2026-11-02.csv | accept: Shivam | from: T-026 | opened 2026-11-02

## Machines
- T-030 | WAITING Shivam | P2 | Shivam uses the Claude cloud credit himself on the Eagle account, Tuesday 3 Nov | accept: Shivam | from: Shivam 2 Nov | opened 2026-11-02
