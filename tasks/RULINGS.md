# Shivam's rulings: loaded into every session, also after compaction. Max 8,000 characters.
New rulings via `ruling add`. `[check]` = code enforces it. Full wording: `docs/rulings/RULINGS_full_2026-11-08.md`; by topic: `project_rules(topic)` tool.
## Goal and scope
- Ultimate goal (8 Nov): predict any stock 6m/1y/2y ahead from reliably held data, least information that does it; few heavyweight factors; more data is not the goal.
- Store facts so a cheap model gets Opus-quality answers through the `reality-data` MCP (direct db/raw reads only when necessary); tables, extractors, tools must scale unchanged to all NSE+BSE; pilot companies only teach the build. Scripts first; AI/OCR only where scripts fail, within 1-2 months of subscription, with his OK.
- Golden order: raw data, banks, schema, pilot, re-run to 95% answered plus checklist, only then the full run.
- Scope is query AND compute: an unstated number is a formula. Empty store = not extracted, never "not held" before checking `tasks/DATA_INVENTORY.md` and raw text; read results tables' QoQ/YoY columns before calling a quarter missing.
- Verbatim first (8 Nov): store what management, officials and regulators said verbatim with source, date, speaker; the model judges at query time; XBRL stays as filed. At scale, judgment and 2nd/3rd-order links come from our own compute, not Opus. Pilot companies may hold pre-FY24 documents.
- Documents (7 Nov): bulk is decks and call transcripts; annual reports by script, selected sections only (in full only for a company with no calls or decks); keep credit-rating and borrowing documents. Never trust the exchange's category or headline: read pages until the type is clear, keep/skip on our own type dictionary.
- Investor questions (8 Nov): peers later, a model compares stored rows; brokerage reports only for stated facts, never targets or ratings; regulator circulars (RBI, SEBI, IRDAI) need their own fetcher (T-117).
- Banks and tests: bank rulings bind (diff rebuilds vs the frozen 1,901 bank); undated question = `as_of` 2026-10-19; report hand-read scores only; the 1,305-question pilot10 set is approved. Proxy is the last resort, reported apart. Never loosen a grader.
- Unpublished data (9 Nov): the answer says 'data not found' with what was searched, plus the nearest supporting point labelled as such; graded right when the search holds up.

## Models and keys
- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`, both Go keys; dsh-worker `model='beam-free'` or `run_deepseek_harness`) writes plumbing code (tables, tools, build parts, tests, scripts) in any hour and grades branches read-only in peak; extraction rules judged by row precision go to DeepSeek. Every branch: a separate read-only grader, then Claude's own tests + sample, merge only with 0 earlier-right rows lost. Beam only while OpenCode lists it free: `free_model_check` flag, harness refuses beam-free once it charges [check: free_model_check]. No headless Opus unless Shivam says so. dsh workers use Go `account='1'` until key 2 resets (7 Nov). Beam may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
- `agy` runs only `gemini-3.8-flash-medium`, headless with `--dangerously-skip-permissions`. Settled: DeepSeek answers need Opus's help; testing is at universal scale.

## How we work
- Claude reviews, workers build; Opus writes ~20-25% (design, tests, review, one working example). Brief only after gathering evidence: defect rows, exact file/function/line, columns, a fast check command; numbered steps with limits, pitfalls, tools, budget, stop rule; unknown method -> Opus prototypes first. Check a finished worker against Opus's own tests and sample, log it, then merge [check: worker_review] [check: merge_tests]. No pilot bank reasoning to workers. Page-reading subagents: batches of 8 pages, under 100k context, Haiku medium.
- Lean: add nothing that does not stop a failure we have had. Max 4 code workers at once on the MSI (10 Nov; was 2 while the browser shared it) [check: code_worker_limit]; data/research jobs on idle machines. Branches merged or deleted within 24 h.
- One task stays in one worker session; Opus reviews and guides the next round; new worker only at 1M context or a new task. No live adviser calls to Claude. Tickets hold tests, never rules.
- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer (quote anchor, sector fit, own figure, reconciliation, scale): `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Releases gate on a hidden hold-out, rulings diff, tool budgets; a fixed random sample is hand-read (~60/stratum). Score only on frozen sets (10 Nov): half of each new set's questions never drive fixes; an exam set (s20: micro/BSE-only/new sectors) gives the reported number. Merge only with zero right rows lost, zero wrong rows verified; structural rules, not per-company.
- No docs, no merge; doc sweep + data inventory at session close, for Wolf, Eagle and every worker. [check: doc_gate]
- Start files: `STATE.md` 4,000 characters, this file 8,000, `AGENTS.md` 150 lines. [check: doc_gate]
- Every worker start names `permission`. [check: start gate] HP work is headless. [check: test_hp_headless] No session-length limit (9 Nov); keep notes as you go: what is done and what is pending, in `tasks/STATE.md`.
- Keep a live watch on every running job (finish, stall, errors); check real progress before reporting; review a finished worker at once. [check: T-050 stop hook]
- A new task from Shivam becomes a ticket first (`task_board add`); commits on `main` name a ticket. [check: commit-msg]
- Log every worker (`tasks/efficiency/worker_reviews.jsonl` -> `WORKER_REVIEW_LOG.xlsx`) and apply lessons to the next brief. [check: worker_review] Bring ranked ideas from measurements unprompted. RAM <90% or CPU <70% used = start useful work. Report compute waste. Decide what you can; never argue a ruling. Session titles keep the `sv-`/`neo-` prefix.

## Data and machines
- Raw files live only on Drive (7 Nov): jobs download, write the database, delete the copy; check size and hash on Drive before deleting a local copy; new fetches may pile up locally during testing, sweep with `raw_to_drive`. Kept local: `D:\RealityEngine\raw\user_research`.
- OCR on the HP only, headless (TextRecognizer 300 DPI first, stronger reader for low-confidence numbers). Until 15 Nov: work never stops for MSI RAM; copy the job's data to an HP worktree folder, run there (x64 Python `C:\RE\py313x64`), bring results back, delete the HP copy (10 Nov). No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.

## Never
- Print or copy keys; read `D:\Shivam_Private\Manual Dumps` or send it anywhere; put amounts in the repo or decision log. Push without his OK (given for merged main, 3 Nov). Use paid models (DeepInfra, Haiku beyond an approved run) without his OK.

## Telling Shivam
- Replies always in proper Indian English, whatever language he writes in; never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. His source of truth for tickets is `D:\RealityEngine
eports	icket_board.xlsx` (+ `.html`), kept in sync with the tracker on every change (8 Nov). [check: task_board + post-commit hook] After every question/answer run: an Excel + CSV in the reports folder with questions, answers, grades, errors, documents and root causes (`answer_run_report.py`; 8 Nov). Rules and how each is enforced: `D:\RealityEngine
eports\standing_rules.xlsx` (+ `.html`), rewritten when this file changes. No spend reports: work until he says stop.
