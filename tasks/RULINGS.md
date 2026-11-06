# Shivam's rulings: loaded into every session, also after compaction. Under 40 lines.
When Shivam rules or corrects something, write it here before the next action. `[check]` means code enforces it; the rest rely on this file.

## Order and scope
- Golden order: raw data, banks, schema, pilot, re-run at 95% answered plus checklist, and only then the full run. No full run before that.
- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. Goal (6 Nov): store the facts so a cheap model gets Opus-quality answers, not brute-force digging by a strong model. Golden benchmark for the pilot (3 Nov): every model call goes through the `reality-data` MCP, a direct db or raw read only when absolutely necessary; every extraction script's design is written up (guide section O) for the full run. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK).
- Scope is query AND compute. A number the filings do not state is a formula to define. Empty store means not extracted: never report it as a gap or "not held" without checking `tasks/DATA_INVENTORY.md` and raw text. A results filing's table prints QoQ and YoY comparative columns: read them before calling any quarter missing or asking for a download (Shivam, 4 Nov).
- Bank rulings bind; diff any bank rebuild against the frozen 1,901-question bank. Do not change bank, labels or scope without his ruling. Questions use pilot stocks only.
- Pilot tests: a question with no date uses `as_of` 2026-10-19; live answers use the latest data. Report only the hand-read score, never the format score. The free-model reader is dropped for now: return retrieved passages with exact quotes (Shivam, 2 Nov).
- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov).

## How we work
- Claude reviews, workers build. DeepSeek on `dsh` at max effort; read the clock for off-peak yourself (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST). Do not give pilot bank reasoning to a worker. Brief a worker only after Claude has gathered its evidence (Shivam, 4 Nov, this project only): the defect rows and ids, the exact file/function/line to edit, the table columns, and a fast check command (`--part`, one company, fixed check pages), so it does not rediscover them.
- Lean: nothing gets added unless it stops a failure we have already had. At most 2 code workers at once; data and research jobs use idle machines. Finished branches merged or deleted within 24 hours.
- No docs, no merge; doc sweep and data inventory at session close, for Wolf, Eagle and every worker. [check: doc_gate]
- Start files stay short: `STATE.md` 40 lines, `AGENTS.md` 150, this file 40. [check: doc_gate]
- Every worker start names `permission`; the supervisor renews MSI leases. [check: start gate]
- Sessions run to 450k context. At 400k Claude writes the wrap-up: commit, next action in `tasks/STATE.md`, doc sweep. Replaces the older 150k, 100k and 40-45% session limits (Shivam, 1 Nov).
- HP work runs headless: nothing on its screen, no focus loss. [check: test_hp_headless]
- Page-reading subagents: batches of 8 pages, never past 100k context, medium effort for Haiku.
- Chain of command until Fri 6 Nov 23:30 IST (Shivam, 3 Nov): Opus manages, dsh workers do all the work, every headless session included; no Haiku runs, except a Haiku subagent Opus sends to check a dsh report it suspects is bogus. Opus does not write the code. In DeepSeek peak hours the code workers are Sonnet 5.5 at medium effort (`tasks/night_loop/sonnet_worker.py`; Shivam, 4 Nov), same 2-worker limit. After loop 3, no more Opus loop sessions: the main session runs 2 dsh workers at once directly (Shivam, 4 Nov).
- Session titles, standing: keep the `sv-`/`neo-` prefix and let each session choose the rest (Shivam, 2 Nov).
- Bring ranked ideas from measurements unprompted. Do not idle machines: RAM under 90% or CPU under 70% used means start useful work. Report compute waste.
- A new task from Shivam becomes a ticket in `tasks/TASKS.md` before work starts. Commits on `main` name a real ticket or give a reason. [check: commit-msg]
- While any worker or job runs, keep a live watch that fires on finish, stall or errors, and check real status and progress before saying anything about it; a run with no check of its first minutes is a failure (Shivam, 2 Nov, after the fourth miss). A worker that finishes is reviewed at once, never left waiting (3 Nov). [check: T-050 stop hook]
- Tickets hold tests and prototypes, never standing rules; rules live here and in memory. One task stays in one worker session: Opus reviews its finished output and guides it in the next round, a new worker only when its context reaches 1M or the task changes; no live adviser calls to Claude, they eat the weekly limit (Shivam, 5 Nov). Do not stop to ask what you can decide. Do not argue a ruling: figure out how to do it.
- Log every dsh worker and Claude session in `tasks/efficiency/WORKER_REVIEW_LOG.xlsx`: tool calls, tokens on thinking and output, job type, time, what Claude would have done itself, and how to improve the prompt, permissions and scope. Analyse it continuously and apply it to the next brief (Shivam, 2 Nov).

## Never
- Print or copy keys. Read `D:\Shivam_Private\Manual Dumps` or send it to the HP or a model; it stays outside the workspace, or put amounts in the repo or decision log.
- Push without his OK (given 3 Nov for merged main). Use any model except free ones and DeepSeek without his OK, which covers DeepInfra and Haiku beyond an approved run.

## Telling Shivam
- Reports are HTML or Mermaid diagrams, never markdown text walls, and every report for Shivam goes in ONE folder, `D:\RealityEngine\reports\`, named `YYYY-MM-DD_<topic>.<ext>` (3 Nov); lists in Excel, PDF, DOCX or RTF. No spend reports needed: work until he says stop. Explain with real questions and examples, never internal codes.
- State failures plainly, with full sample sizes; no scores from small samples without saying so.

## Agreed direction, not yet built
- Split `fact.value` and test `metric_citations` on the prototype (T-036). Typed write contracts are built: `reality_engine/contracts.py`.
- Merge gate with hidden evaluation and rulings diff; tool-call budgets enforced in code; read limit if the median stays above 10 calls before first edit.
- OCR runs on the HP laptop only, headless (Shivam, 3 Nov): Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers; no OCR on the MSI. No PostgreSQL for now; revisit with measurements after the gate.
