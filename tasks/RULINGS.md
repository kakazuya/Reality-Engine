# Shivam's rulings: loaded into every session, also after compaction. Max 8,000 characters.
New rulings via `ruling add`; `[check]` = enforced by code. Full wording `docs/rulings/RULINGS_FULL.md`; `project_rules(topic)`.
## Goal and scope
- Ultimate goal (8 Nov): predict any stock 6m/1y/2y ahead from reliably held data, least information that does it; few heavyweight factors; more data is not the goal. Factor rewards aren't fixed laws (10 Nov): re-run every month-end, ongoing (14 Nov), per stock, sector and regime; report the statistical mode of rewarded factors and shifts.
- Store facts so a cheap model gets Opus-quality answers through the `reality-data` MCP (raw reads only when needed); tables, extractors, tools must scale unchanged to all NSE+BSE; pilot companies teach the build. Scripts first; AI/OCR only where scripts fail, within 1-2 months of subscription, with his OK.
- Golden order: raw data, banks, schema, pilot, re-run to 95% answered plus checklist, only then the full run.
- Scope is query AND compute: an unstated number is a formula. Empty store = not extracted, never "not held" before checking `tasks/DATA_INVENTORY.md` and raw text; read results tables' QoQ/YoY columns before calling a quarter missing.
- Verbatim first (8 Nov): store what management, officials and regulators said verbatim with source, date, speaker; the model judges at query time; XBRL stays as filed. At scale, judgment and 2nd/3rd-order links come from our own compute, not Opus. Calls (24 Nov): statements gate; call numbers unverified until a held filing matches within 1%.
- Documents (7 Nov, 17 Nov): a small company's data sits in its annual report, quarterly results, rating documents and ad hoc announcements (order wins, material gain/loss, audit, management change): read those first. Type a document by its pages on our own dictionary, never the exchange's category. Parent calls (18 Nov): a subsidiary's store keeps its parent's call transcripts, labelled.
- Investor questions (8 Nov): peers later, a model compares stored rows; brokerage reports only for stated facts, never targets or ratings; regulator circulars (RBI, SEBI, IRDAI) need their own fetcher (T-117). Policy (10 Nov): other-language PIB/official text only when no English version exists; each policy maps to companies touched (for, against or neutral), with why and a figure where possible.
- Banks and tests: bank rulings bind (diff rebuilds vs the frozen 1,901 bank); undated question = `as_of` 2026-10-19; report hand-read scores only; pilot10's 1,305 questions are approved. Proxy is the last resort, reported apart. Never loosen a grader.
- Unpublished data (9 Nov): the answer says 'data not found' with what was searched, plus the nearest supporting point labelled as such; graded right when the search holds up.

## Models and keys
- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`) writes plumbing code any hour and grades read-only in peak; extraction judged by row precision goes to DeepSeek. Every branch: read-only grader, then Claude's tests + sample. Beam only while free [check: free_model_check]. No headless Opus unless Shivam asks. Go key 1 only (14 Nov). Beam may settle KPI/guidance rows scripts cannot (separate step).
- Reasoning ladder (26 Nov, replaces 17-25 Nov routing): errands -> gemini-worker Gemma 4 31B/26B if quick; harder -> DeepSeek off-peak, `agy` Hydrogen in peak; DeepSeek weak or failing rounds -> Hydrogen high; higher reasoning/review -> Opus medium itself; hardest only -> Neon 4 high/xhigh, sparingly. Company question search: `agy` gemini-3.8-flash-medium while it lasts (no Argon).

## How we work
- Claude reviews, workers build; Opus writes ~20-25% (design, tests, review, one working example). Briefs carry evidence (rows, file:line, a fast check), numbered steps, limits, pitfalls, budget and a stop rule; unknown method -> Opus prototypes first. Check a finished worker on Opus's own tests and sample, log, merge [check: worker_review] [check: merge_tests]. No pilot bank reasoning to workers. Page-reading subagents: batches of 8 pages, under 100k context, Haiku medium.
- Stores (16 Nov): build ALL queue firms, then random trials; general fixes, re-trial; >=90% = next companies. Per-part repairs (no rebuild); repair notes scored by companies hit x wrong/corrupt/missed, fix by priority (17 Nov); Claude codes stores. Lean: only what stops a past failure. Max 4 MSI code workers [check: code_worker_limit]; data jobs on idle machines. Branches merged or deleted in 24 h.
- One task, one worker session (new worker at 1M context or a new task); Opus reviews each round. No live adviser calls to Claude. Tickets = in-scope work; rules here; ideas to `tasks/IDEA_BOX.md` (why, purpose, review trigger) (12 Nov).
- Architecture (8 Nov): authors never check own code. Every extracted row passes the independent `row_checks.py` layer: `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row; score only on frozen sets (10 Nov); s20 exam set gives the reported score. Structural rules only. Never block reading (26 Nov): all doc types read and load; graded sample >10% W+J loads unverified; block only if >10% of the DB is corrupt; Claude fixes. 2 passes = grade every 5th ckpt (27 Nov). [check: read_gate] Rows store read_model/gateway/harness, prompt_fp, read_at.
- No docs, no merge; doc sweep + data inventory at session close, for Wolf, Eagle and every worker. [check: doc_gate]
- Start files: STATE 4,000, this 8,000, AGENTS 150 lines. [check: doc_gate]
- Every worker start names `permission`. [check: start gate] No session limit (9 Nov); done/pending in `tasks/STATE.md`.
- Watch every running job (finish, stall, errors); check real progress before reporting; review a finished worker at once. [check: T-050 stop hook]
- A new task from Shivam becomes a ticket first (`task_board add`); commits on `main` name a ticket. [check: commit-msg]
- Log every worker (`tasks/efficiency/worker_reviews.jsonl` -> `WORKER_REVIEW_LOG.xlsx`) and apply lessons to the next brief. [check: worker_review] Bring ranked ideas from measurements unprompted. RAM <90% or CPU <70% used = start useful work. Report compute waste. Decide what you can; never argue rulings.
- Run ledger (11 Nov): log every run of every model (DEVELOPER_GUIDE s7); answers say why raw SQL was used; report overfit at once.
- Journal (13 Nov): add a tasks/JOURNAL.md entry (work, worked, failed and why, fixes) at 400k context and at wrap-up; read the latest at start.

## Data and machines
- Raw files only on Drive (7 Nov): download, write the database, delete the copy after a Drive hash check; tests local till `raw_to_drive`. `raw\user_research` goes to Drive too (27 Nov). Tools/trackers (16 Nov): local, Drive or GitHub only; no cloud until deployed.
- HP gone (17 Nov): OCR (bad text layer only) by Kilo Dots on the page image, Haiku where Dots fails. No PostgreSQL. Stores on C: SSD (18 Nov). Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.

## Never
- Print or copy keys; read `D:\Shivam_Private\Manual Dumps` or send it anywhere; put amounts in the repo or decision log. Push without his OK (given for merged main, 3 Nov). Use paid models (DeepInfra, Haiku beyond an approved run) without his OK.

## Telling Shivam
- Replies always in proper Indian English, never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, not codes. State failures plainly with sample sizes. Ticket truth: `reports\ticket_board.xlsx` (+ `.html`), synced on every change (8 Nov). [check: task_board + post-commit hook] After every answer run: Excel + CSV in reports (`answer_run_report.py`, 8 Nov). Rules sheet `reports\standing_rules.xlsx` (+ `.html`). No spend reports: work until he says stop.
