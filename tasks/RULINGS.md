# Shivam's rulings: loaded into every session, also after compaction. Under 40 lines.
When Shivam rules or corrects something, write it here before the next action. `[check]` means code enforces it; the rest rely on this file.

## Order and scope
- Golden order: raw data, banks, schema, pilot, re-run at 95% answered plus checklist, and only then the full run. No full run before that.
- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK).
- Scope is query AND compute. A number the filings do not state is a formula to define. Empty store means not extracted: never report it as a gap or "not held" without checking `tasks/DATA_INVENTORY.md` and raw text.
- Bank rulings bind; diff any bank rebuild against the frozen 1,901-question bank. Do not change bank, labels or scope without his ruling. Questions use pilot stocks only.
- Pilot tests: a question with no date uses `as_of` 2026-10-19; live answers use the latest data. Report only the hand-read score, never the format score. The free-model reader is dropped for now: return retrieved passages with exact quotes (Shivam, 2 Nov).
- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score.

## How we work
- Claude reviews, workers build. DeepSeek on `dsh` at max effort; read the clock for off-peak yourself (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST). Do not give pilot bank reasoning to a worker.
- Lean: nothing gets added unless it stops a failure we have already had. At most 2 code workers at once; data and research jobs use idle machines. Finished branches merged or deleted within 24 hours.
- No docs, no merge; doc sweep and data inventory at session close, for Wolf, Eagle and every worker. [check: doc_gate]
- Start files stay short: `STATE.md` 40 lines, `AGENTS.md` 150, this file 40. [check: doc_gate]
- Every worker start names `permission`; the supervisor renews MSI leases. [check: start gate]
- Sessions run to 450k context. At 400k Claude writes the wrap-up: commit, next action in `tasks/STATE.md`, doc sweep. Replaces the older 150k, 100k and 40-45% session limits (Shivam, 1 Nov).
- HP work runs headless: nothing on its screen, no focus loss. [check: test_hp_headless]
- Page-reading subagents: batches of 8 pages, never past 100k context, medium effort for Haiku.
- Three tiers (Shivam, 2 Nov): Haiku 5.5 does the work in fresh sessions under 100k context; after repeated failure it goes to a DeepSeek worker; only if that fails does it reach Opus. dsh workers are the fallback for headless Claude loops when the Claude limit is spent (Shivam, 3 Nov). Opus reviews and manages, and does not write the code. Approved Haiku runs: T-045 docs, T-048 one-company loop.
- Session titles, standing (T-047, never closed): keep the `sv-`/`neo-` prefix and let each session choose the rest (Shivam, 2 Nov).
- Bring ranked ideas from measurements unprompted. Do not idle machines: RAM under 90% or CPU under 70% used means start useful work. Report compute waste.
- A new task from Shivam becomes a ticket in `tasks/TASKS.md` before work starts. Commits on `main` name a real ticket or give a reason. [check: commit-msg]
- While any worker or job runs, keep a live watch that fires on finish, stall or errors, and check real status and progress before saying anything about it; a run with no check of its first minutes is a failure (Shivam, 2 Nov, after the fourth miss).
- Do not stop to ask what you can decide. Do not argue a ruling: figure out how to do it.
- Log every dsh worker and Claude session in `tasks/efficiency/WORKER_REVIEW_LOG.xlsx`: tool calls, tokens on thinking and output, job type, time, what Claude would have done itself, and how to improve the prompt, permissions and scope. Analyse it continuously and apply it to the next brief (Shivam, 2 Nov).

## Never
- Print or copy keys. Read `D:\Shivam_Private\Manual Dumps` or send it to the HP or a model; it stays outside the workspace, or put amounts in the repo or decision log.
- Push without his OK. Use any model except free ones and DeepSeek without his OK, which covers DeepInfra and Haiku beyond an approved run.

## Telling Shivam
- Lists go in Excel, PDF, DOCX or RTF, never markdown. Explain with real questions and examples, never internal codes.
- State failures plainly, with full sample sizes; no scores from small samples without saying so.

## Agreed direction, not yet built
- Split `fact.value` and test `metric_citations` on the prototype (T-036). Typed write contracts are built: `reality_engine/contracts.py`.
- Merge gate with hidden evaluation and rulings diff; tool-call budgets enforced in code; read limit if the median stays above 10 calls before first edit.
- OCR: Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers. No PostgreSQL for now; revisit with measurements after the gate.
