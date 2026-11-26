# Full ledger of `tasks/RULINGS.md` (never trimmed)

`tasks/RULINGS.md` is the short copy every session loads; it is condensed to fit its size cap. This file keeps every line ever added (`+`) or removed (`-`) there, with date, branch and author, oldest first (Shivam, 26 Nov 2026). Earlier full wording of the rulings: `docs/rulings/RULINGS_full_2026-11-08.md`.

## 2026-11-01T18:32:46+05:30 | kakazuya (Wolf) | 0635b046 Carry Shivam's rulings into every session: RULINGS.md and a session start hook
```diff
+# Shivam's rulings: loaded into every session, also after compaction. Under 40 lines.
+When Shivam rules or corrects something, write it here before the next action. `[check]` means code enforces it; the rest rely on this file.
+## Order and scope
+- Golden order: raw data, banks, schema, pilot, re-run at 95% answered plus checklist, and only then the full run. No full run before that.
+- Workspace fix comes before database design: `tasks/WORKSPACE_FIX_2026-11-01.md`. Prototype on 2-3 companies before any wider run.
+- Scope is query AND compute. A number the filings do not state is a formula to define. Empty store means not extracted: never report it as a gap or "not held" without checking `tasks/DATA_INVENTORY.md` and raw text.
+- Bank rulings bind; diff any bank rebuild against the frozen 1,901-question bank. Do not change bank, labels or scope without his ruling. Questions use pilot stocks only.
+- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score.
+## How we work
+- Claude reviews, workers build. DeepSeek on `dsh` at max effort; read the clock for off-peak yourself (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST). Do not give pilot bank reasoning to a worker.
+- Lean: nothing gets added unless it stops a failure we have already had. At most 2 code workers at once; data and research jobs use idle machines. Finished branches merged or deleted within 24 hours.
+- No docs, no merge; doc sweep and data inventory at session close, for Wolf, Eagle and every worker. [check: doc_gate]
+- Start files stay short: `STATE.md` 40 lines, `AGENTS.md` 150, this file 40. [check: doc_gate]
+- Set `permission` on every worker start and read it back. Renew MSI leases. [check coming: start gate]
+- HP work runs headless: nothing on its screen, no focus loss. [check: test_hp_headless]
+- Page-reading subagents: batches of 8 pages, never past 100k context, medium effort for Haiku.
+- Bring ranked ideas from measurements unprompted. Do not idle machines: RAM under 90% or CPU under 70% used means start useful work. Report compute waste.
+- Do not stop to ask what you can decide. Do not argue a ruling: figure out how to do it.
+## Never
+- Print or copy keys. Send `Manual Dumps/` to the HP or a model, or put amounts in the repo or decision log.
+- Push without his OK. Use paid models or DeepInfra without his OK, including Haiku beyond an approved run.
+## Telling Shivam
+- Lists go in Excel, PDF, DOCX or RTF, never markdown. Explain with real questions and examples, never internal codes.
+- State failures plainly, with full sample sizes; no scores from small samples without saying so.
+## Agreed direction, not yet built
+- Typed write contracts at write time (unit, range, label), splitting `fact.value`; test `metric_citations` on the prototype.
+- Merge gate with hidden evaluation and rulings diff; tool-call budgets enforced in code; read limit if the median stays above 10 calls before first edit.
+- OCR: Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers. No PostgreSQL for now; revisit with measurements after the gate.
```

## 2026-11-01T23:42:49+05:30 | kakazuya (Wolf) | 0b62ba5f Record 1 Nov rulings: 450k sessions, private folder moved out, model list
```diff
-- Set `permission` on every worker start and read it back. Renew MSI leases. [check coming: start gate]
+- Every worker start names `permission`; the supervisor renews MSI leases. [check: start gate]
+- Sessions run to 450k context. At 400k Claude writes the wrap-up: commit, next action in `tasks/STATE.md`, doc sweep. Replaces the older 150k, 100k and 40-45% session limits (Shivam, 1 Nov).
-- Print or copy keys. Send `Manual Dumps/` to the HP or a model, or put amounts in the repo or decision log.
-- Push without his OK. Use paid models or DeepInfra without his OK, including Haiku beyond an approved run.
+- Print or copy keys. Read `D:\Shivam_Private\Manual Dumps` or send it to the HP or a model; it stays outside the workspace, or put amounts in the repo or decision log.
+- Push without his OK. Use any model except free ones and DeepSeek without his OK, which covers DeepInfra and Haiku beyond an approved run.
```

## 2026-11-02T00:20:34+05:30 | kakazuya (Wolf) | 2597585a merge: dsh/20261101T181317Z-dd908113 ticket tracker and 400k wrap-up hook (reviewed)
```diff
++- A new task from Shivam becomes a ticket in `tasks/TASKS.md` before work starts. Commits on `main` name a real ticket or give a reason. [check: commit-msg]
```

## 2026-11-02T01:42:04+05:30 | kakazuya (Wolf) | 22954e51 Close T-015 and T-026 on Shivam's rulings of 2 Nov
```diff
+- Pilot tests: a question with no date uses `as_of` 2026-10-19; live answers use the latest data. Report only the hand-read score, never the format score. The free-model reader is dropped for now: return retrieved passages with exact quotes (Shivam, 2 Nov).
```

## 2026-11-02T01:51:22+05:30 | kakazuya (Wolf) | 7e07e144 Resume the pilot test on the 3 prototype companies, by Shivam's order of 2 Nov (T-035)
```diff
-- Workspace fix comes before database design: `tasks/WORKSPACE_FIX_2026-11-01.md`. Prototype on 2-3 companies before any wider run.
+- Pilot test resumes (Shivam, 2 Nov): the workspace issues are settled, and open workspace tickets no longer block it. Prototype on 2-3 companies before any wider run.
```

## 2026-11-02T03:34:10+05:30 | kakazuya (Wolf) | 8052ce0e merge: dsh/20261101T215253Z-6f5a0601 rule and chain-of-command ledger (T-042, T-043, reviewed)
```diff
++- Log every dsh worker and Claude session in `tasks/efficiency/WORKER_REVIEW_LOG.xlsx`: tool calls, tokens on thinking and output, job type, time, what Claude would have done itself, and how to improve the prompt, permissions and scope. Analyse it continuously and apply it to the next brief (Shivam, 2 Nov).
```

## 2026-11-02T03:57:02+05:30 | kakazuya (Wolf) | 3d503f25 T-035 reader call limit raised to 300 s and errors shown in progress; live-watch ruling added
```diff
+- While any worker or job runs, keep a live watch that fires on finish, stall or errors, and check real status and progress before saying anything about it; a run with no check of its first minutes is a failure (Shivam, 2 Nov, after the fourth miss).
```

## 2026-11-02T04:22:35+05:30 | kakazuya (Wolf) | 0bf94539 T-045 core docs read line by line: AGENTS, RULINGS, guide, raw families, machines
```diff
-- Typed write contracts at write time (unit, range, label), splitting `fact.value`; test `metric_citations` on the prototype.
+- Split `fact.value` and test `metric_citations` on the prototype (T-036). Typed write contracts are built: `reality_engine/contracts.py`.
```

## 2026-11-02T05:16:56+05:30 | kakazuya (Wolf) | aea88f09 T-045 Haiku doc loop, Stop and PreCompact hooks, Shivam's reader ruling
```diff
+- T-045 docs are read by Haiku 5.5 in fresh `claude -p` sessions under 100k context, not by Opus; this is an approved Haiku run (Shivam, 2 Nov). [check: test_doc_review_loop]
```

## 2026-11-02T13:01:00+05:30 | kakazuya (Wolf) | 12965e99 T-047 session titles made a standing rule: row committed, never closed, ruling recorded
```diff
+- Session titles, standing (T-047, never closed): keep the `sv-`/`neo-` prefix and let each session choose the rest (Shivam, 2 Nov).
```

## 2026-11-02T14:32:24+05:30 | kakazuya (Wolf) | 2ecfa4b5 T-048 one-company gap loop: three-tier ruling recorded, DeepSeek brief to build the loop
```diff
-- T-045 docs are read by Haiku 5.5 in fresh `claude -p` sessions under 100k context, not by Opus; this is an approved Haiku run (Shivam, 2 Nov). [check: test_doc_review_loop]
+- Three tiers (Shivam, 2 Nov): Haiku 5.5 does the work in fresh sessions under 100k context; after repeated failure it goes to a DeepSeek worker; only if that fails does it reach Opus. Opus reviews and manages, and does not write the code. Approved Haiku runs: T-045 docs, T-048 one-company loop.
```

## 2026-11-03T02:35:02+05:30 | kakazuya (Wolf) | 1715a17d T-049 opened: script extraction into one database for the 3 pilot companies (Shivam, 3 Nov); ruling 
```diff
-- Pilot test resumes (Shivam, 2 Nov): the workspace issues are settled, and open workspace tickets no longer block it. Prototype on 2-3 companies before any wider run.
+- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK).
```

## 2026-11-03T13:40:31+05:30 | kakazuya (Eagle) | aebd41db T-049 merge: pilot3 in one database served by eight reality-data MCP tools (Sonnet session F, unfini
```diff
++- Three tiers (Shivam, 2 Nov): Haiku 5.5 does the work in fresh sessions under 100k context; after repeated failure it goes to a DeepSeek worker; only if that fails does it reach Opus. dsh workers are the fallback for headless Claude loops when the Claude limit is spent (Shivam, 3 Nov). Opus reviews and manages, and does not write the code. Approved Haiku runs: T-045 docs, T-048 one-company loop.
```

## 2026-11-03T16:27:34+05:30 | kakazuya (Eagle) | f7437d04 T-052 rulings of 3 Nov, tickets T-050..T-052, delete finished AR-study text extracts, worker briefs
```diff
-- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK).
+- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. Golden benchmark for the pilot (3 Nov): every model call goes through the `reality-data` MCP, a direct db or raw read only when absolutely necessary; every extraction script's design is written up (guide section O) for the full run. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK).
-- Three tiers (Shivam, 2 Nov): Haiku 5.5 does the work in fresh sessions under 100k context; after repeated failure it goes to a DeepSeek worker; only if that fails does it reach Opus. dsh workers are the fallback for headless Claude loops when the Claude limit is spent (Shivam, 3 Nov). Opus reviews and manages, and does not write the code. Approved Haiku runs: T-045 docs, T-048 one-company loop.
+- Chain of command until Fri 6 Nov 23:30 IST (Shivam, 3 Nov): Opus manages, dsh workers do all the work, every headless session included; no Haiku runs, except a Haiku subagent Opus sends to check a dsh report it suspects is bogus. Opus does not write the code.
-- While any worker or job runs, keep a live watch that fires on finish, stall or errors, and check real status and progress before saying anything about it; a run with no check of its first minutes is a failure (Shivam, 2 Nov, after the fourth miss).
+- While any worker or job runs, keep a live watch that fires on finish, stall or errors, and check real status and progress before saying anything about it; a run with no check of its first minutes is a failure (Shivam, 2 Nov, after the fourth miss). A worker that finishes is reviewed at once, never left waiting (3 Nov). [check: T-050 stop hook]
-- Push without his OK. Use any model except free ones and DeepSeek without his OK, which covers DeepInfra and Haiku beyond an approved run.
+- Push without his OK (given 3 Nov for merged main). Use any model except free ones and DeepSeek without his OK, which covers DeepInfra and Haiku beyond an approved run.
-- Lists go in Excel, PDF, DOCX or RTF, never markdown. Explain with real questions and examples, never internal codes.
+- Reports are HTML or Mermaid diagrams, never markdown text walls (3 Nov); lists in Excel, PDF, DOCX or RTF. No spend reports needed: work until he says stop. Explain with real questions and examples, never internal codes.
```

## 2026-11-03T18:24:20+05:30 | kakazuya (Eagle) | b4587e33 No-ticket: record Shivam's ruling that all OCR runs on the HP laptop
```diff
-- OCR: Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers. No PostgreSQL for now; revisit with measurements after the gate.
+- OCR runs on the HP laptop only, headless (Shivam, 3 Nov): Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers; no OCR on the MSI. No PostgreSQL for now; revisit with measurements after the gate.
```

## 2026-11-03T18:43:29+05:30 | kakazuya (Eagle) | 0fc1bc49 No-ticket: Shivam's ruling that every report goes in D:/RealityEngine/reports
```diff
-- Reports are HTML or Mermaid diagrams, never markdown text walls (3 Nov); lists in Excel, PDF, DOCX or RTF. No spend reports needed: work until he says stop. Explain with real questions and examples, never internal codes.
+- Reports are HTML or Mermaid diagrams, never markdown text walls, and every report for Shivam goes in ONE folder, `D:\RealityEngine\reports\`, named `YYYY-MM-DD_<topic>.<ext>` (3 Nov); lists in Excel, PDF, DOCX or RTF. No spend reports needed: work until he says stop. Explain with real questions and examples, never internal codes.
```

## 2026-11-04T02:53:09+05:30 | kakazuya (Eagle) | 226b920b No-ticket: project rule, briefs carry evidence before a dsh start; blueprint build timings
```diff
-- Claude reviews, workers build. DeepSeek on `dsh` at max effort; read the clock for off-peak yourself (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST). Do not give pilot bank reasoning to a worker.
+- Claude reviews, workers build. DeepSeek on `dsh` at max effort; read the clock for off-peak yourself (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST). Do not give pilot bank reasoning to a worker. Brief a worker only after Claude has gathered its evidence (Shivam, 4 Nov, this project only): the defect rows and ids, the exact file/function/line to edit, the table columns, and a fast check command (`--part`, one company, fixed check pages), so it does not rediscover them.
```

## 2026-11-04T04:20:39+05:30 | kakazuya (Eagle) | f1b75787 No-ticket: Sonnet 5.5 medium code workers in DeepSeek peak hours (Shivam ruling 4 Nov); launcher tas
```diff
-- Chain of command until Fri 6 Nov 23:30 IST (Shivam, 3 Nov): Opus manages, dsh workers do all the work, every headless session included; no Haiku runs, except a Haiku subagent Opus sends to check a dsh report it suspects is bogus. Opus does not write the code.
+- Chain of command until Fri 6 Nov 23:30 IST (Shivam, 3 Nov): Opus manages, dsh workers do all the work, every headless session included; no Haiku runs, except a Haiku subagent Opus sends to check a dsh report it suspects is bogus. Opus does not write the code. In DeepSeek peak hours the code workers are Sonnet 5.5 at medium effort (`tasks/night_loop/sonnet_worker.py`; Shivam, 4 Nov), same 2-worker limit.
```

## 2026-11-04T18:08:30+05:30 | kakazuya (Eagle) | 99957f9d T-056: merge reportable segments from raw results XBRL into kpi_series (l2segments); xbrl_segments 9
```diff
++- Scope is query AND compute. A number the filings do not state is a formula to define. Empty store means not extracted: never report it as a gap or "not held" without checking `tasks/DATA_INVENTORY.md` and raw text. A results filing's table prints QoQ and YoY comparative columns: read them before calling any quarter missing or asking for a download (Shivam, 4 Nov).
```

## 2026-11-04T19:21:21+05:30 | kakazuya (Eagle) | 30050656 T-056: loop 3 is the last loop session; after it the main session runs 2 dsh workers at once
```diff
-- Chain of command until Fri 6 Nov 23:30 IST (Shivam, 3 Nov): Opus manages, dsh workers do all the work, every headless session included; no Haiku runs, except a Haiku subagent Opus sends to check a dsh report it suspects is bogus. Opus does not write the code. In DeepSeek peak hours the code workers are Sonnet 5.5 at medium effort (`tasks/night_loop/sonnet_worker.py`; Shivam, 4 Nov), same 2-worker limit.
+- Chain of command until Fri 6 Nov 23:30 IST (Shivam, 3 Nov): Opus manages, dsh workers do all the work, every headless session included; no Haiku runs, except a Haiku subagent Opus sends to check a dsh report it suspects is bogus. Opus does not write the code. In DeepSeek peak hours the code workers are Sonnet 5.5 at medium effort (`tasks/night_loop/sonnet_worker.py`; Shivam, 4 Nov), same 2-worker limit. After loop 3, no more Opus loop sessions: the main session runs 2 dsh workers at once directly (Shivam, 4 Nov).
```

## 2026-11-05T00:51:16+05:30 | kakazuya (Eagle) | cacd8f8d T-067: Shivam approves the question set and free Beam for unsettled KPI rows; answer test brief
```diff
-- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score.
+- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov).
```

## 2026-11-05T03:27:24+05:30 | kakazuya (Eagle) | 0d4dbaa4 T-072: move standing rules out of tickets, add paper and goal-brief tickets, record 5 Nov rulings
```diff
-- Session titles, standing (T-047, never closed): keep the `sv-`/`neo-` prefix and let each session choose the rest (Shivam, 2 Nov).
+- Session titles, standing: keep the `sv-`/`neo-` prefix and let each session choose the rest (Shivam, 2 Nov).
-- Do not stop to ask what you can decide. Do not argue a ruling: figure out how to do it.
+- Tickets hold tests and prototypes, never standing rules; rules live here and in memory. One task stays in one worker session: Opus reviews its finished output and guides it in the next round, a new worker only when its context reaches 1M or the task changes; no live adviser calls to Claude, they eat the weekly limit (Shivam, 5 Nov). Do not stop to ask what you can decide. Do not argue a ruling: figure out how to do it.
```

## 2026-11-06T13:36:27+05:30 | kakazuya (Eagle) | 7adcd888 T-088, T-089: open store fixes and holiday rows; record the goal ruling
```diff
-- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. Golden benchmark for the pilot (3 Nov): every model call goes through the `reality-data` MCP, a direct db or raw read only when absolutely necessary; every extraction script's design is written up (guide section O) for the full run. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK).
+- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. Goal (6 Nov): store the facts so a cheap model gets Opus-quality answers, not brute-force digging by a strong model. Golden benchmark for the pilot (3 Nov): every model call goes through the `reality-data` MCP, a direct db or raw read only when absolutely necessary; every extraction script's design is written up (guide section O) for the full run. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK).
```

## 2026-11-06T18:20:31+05:30 | kakazuya (Eagle) | 68191e62 T-090: open the universe-scale round, Shivam's ruling and six tickets
```diff
-- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. Goal (6 Nov): store the facts so a cheap model gets Opus-quality answers, not brute-force digging by a strong model. Golden benchmark for the pilot (3 Nov): every model call goes through the `reality-data` MCP, a direct db or raw read only when absolutely necessary; every extraction script's design is written up (guide section O) for the full run. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK).
+- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. Goal (6 Nov): store the facts so a cheap model gets Opus-quality answers, not brute-force digging by a strong model. Tables, extractors, chunks, tools and the MCP server must scale unchanged to the whole NSE+BSE universe; the ten companies only teach how to build it (6 Nov). Golden benchmark for the pilot (3 Nov): every model call goes through the `reality-data` MCP, a direct db or raw read only when absolutely necessary; every extraction script's design is written up (guide section O) for the full run. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK).
```

## 2026-11-06T18:42:46+05:30 | kakazuya (Eagle) | ab1885e9 T-092: packets tested on real data, ruling on Opus scaffolds
```diff
-- Chain of command until Fri 6 Nov 23:30 IST (Shivam, 3 Nov): Opus manages, dsh workers do all the work, every headless session included; no Haiku runs, except a Haiku subagent Opus sends to check a dsh report it suspects is bogus. Opus does not write the code. In DeepSeek peak hours the code workers are Sonnet 5.5 at medium effort (`tasks/night_loop/sonnet_worker.py`; Shivam, 4 Nov), same 2-worker limit. After loop 3, no more Opus loop sessions: the main session runs 2 dsh workers at once directly (Shivam, 4 Nov).
+- Chain of command until Fri 6 Nov 23:30 IST (Shivam, 3 Nov): Opus manages, dsh workers do all the work, every headless session included; no Haiku runs, except a Haiku subagent Opus sends to check a dsh report it suspects is bogus. Opus scouts and writes code for design, tests, review and scaffolds (one working example), about 20-25%; workers write the rest (Shivam 6 Nov, standing, replaces "does not write the code"). In DeepSeek peak hours the code workers are Sonnet 5.5 at medium effort (`tasks/night_loop/sonnet_worker.py`; Shivam, 4 Nov), same 2-worker limit. After loop 3, no more Opus loop sessions: the main session runs 2 dsh workers at once directly (Shivam, 4 Nov).
```

## 2026-11-06T22:09:57+05:30 | kakazuya (Eagle) | 33b83e79 T-096: Shivam's order, Opus fixes the watcher first next session
```diff
-- Tickets hold tests and prototypes, never standing rules; rules live here and in memory. One task stays in one worker session: Opus reviews its finished output and guides it in the next round, a new worker only when its context reaches 1M or the task changes; no live adviser calls to Claude, they eat the weekly limit (Shivam, 5 Nov). Do not stop to ask what you can decide. Do not argue a ruling: figure out how to do it.
+- Tickets hold tests and prototypes, never standing rules; rules live here and in memory. One task stays in one worker session: Opus reviews its finished output and guides it in the next round, a new worker only when its context reaches 1M or the task changes; no live adviser calls to Claude, they eat the weekly limit (Shivam, 5 Nov). Do not stop to ask what you can decide. Do not argue a ruling: figure out how to do it. Opus fixes the job watcher itself (T-096) as absolute priority, before returning to the reality-data server, schema and query methods (Shivam, 6 Nov).
```

## 2026-11-06T22:55:36+05:30 | kakazuya (Eagle) | 3a6be690 T-096: job_watch shows WAITING at once, live tool counts, acks that clear a stall
```diff
-- Tickets hold tests and prototypes, never standing rules; rules live here and in memory. One task stays in one worker session: Opus reviews its finished output and guides it in the next round, a new worker only when its context reaches 1M or the task changes; no live adviser calls to Claude, they eat the weekly limit (Shivam, 5 Nov). Do not stop to ask what you can decide. Do not argue a ruling: figure out how to do it. Opus fixes the job watcher itself (T-096) as absolute priority, before returning to the reality-data server, schema and query methods (Shivam, 6 Nov).
+- Tickets hold tests and prototypes, never standing rules; rules live here and in memory. One task stays in one worker session: Opus reviews its finished output and guides it in the next round, a new worker only when its context reaches 1M or the task changes; no live adviser calls to Claude, they eat the weekly limit (Shivam, 5 Nov). Do not stop to ask what you can decide. Do not argue a ruling: figure out how to do it. Opus fixes the job watcher itself (T-096) as absolute priority, before returning to the reality-data server, schema and query methods (Shivam, 6 Nov; fix committed, awaits his accept).
```

## 2026-11-06T23:24:00+05:30 | kakazuya (Eagle) | 092a37d5 T-092: Shivam approves Beam for guidance sentences, state of the read
```diff
-- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov).
+- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov).
```

## 2026-11-06T23:47:38+05:30 | kakazuya (Wolf) | 1ac5a247 T-097: Go key 2 for all paid calls (HP default too), board cleanup on Shivam's 6 Nov ruling
```diff
-- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov).
+- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go key 1 is at 99% of its limit (6 Nov): every paid call, dsh workers on MSI and HP included, uses key 2; key 1 only to test the dsh server; free Beam and other free models still use both keys. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
```

## 2026-11-07T00:13:48+05:30 | kakazuya (Wolf) | 7ddccb0d T-100: Shivam's document scope ruling (decks and calls first, annual reports by selected sections, r
```diff
-- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go key 1 is at 99% of its limit (6 Nov): every paid call, dsh workers on MSI and HP included, uses key 2; key 1 only to test the dsh server; free Beam and other free models still use both keys. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
+- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go key 1 is at 99% of its limit (6 Nov): every paid call, dsh workers on MSI and HP included, uses key 2; key 1 only to test the dsh server; free Beam and other free models still use both keys. Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
```

## 2026-11-07T01:11:58+05:30 | kakazuya (Wolf) | 14bb8b16 T-099: holiday copies removed from daily_price_delivery, Muhurat 2021-11-04 restored, bhavcopy write
```diff
-- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go key 1 is at 99% of its limit (6 Nov): every paid call, dsh workers on MSI and HP included, uses key 2; key 1 only to test the dsh server; free Beam and other free models still use both keys. Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
+- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go key 1 is at 99% of its limit (6 Nov): every paid call, dsh workers on MSI and HP included, uses key 2; key 1 only to test the dsh server; free Beam and other free models still use both keys. Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Announcement types (Shivam, 7 Nov): never trust the exchange's category or headline, companies file under wrong ones; read the first page, and further pages until the document's type is clear, and build our own type dictionary from that, applied to every new filing as it arrives; the keep or skip choice is made on our own types. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
```

## 2026-11-07T02:16:07+05:30 | kakazuya (Wolf) | 50501014 T-102: raw files only on Drive (Shivam's ruling); raw_to_drive.py; doc_locations reads the second ar
```diff
-- OCR runs on the HP laptop only, headless (Shivam, 3 Nov): Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers; no OCR on the MSI. No PostgreSQL for now; revisit with measurements after the gate.
+- OCR runs on the HP laptop only, headless (Shivam, 3 Nov): Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers; no OCR on the MSI. No PostgreSQL for now; revisit with measurements after the gate. Raw files live only on Google Drive (Shivam, 7 Nov): no raw file stays on the MSI or the HP; a job downloads what it needs, writes the database, then deletes the copy; only databases stay local; every local raw file is checked on Drive (size and hash) before its local copy is deleted.
```

## 2026-11-07T02:39:18+05:30 | kakazuya (Wolf) | 9764419b T-102: research library stays local (--keep), Telegram Desktop untouched; Shivam 7 Nov
```diff
-- OCR runs on the HP laptop only, headless (Shivam, 3 Nov): Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers; no OCR on the MSI. No PostgreSQL for now; revisit with measurements after the gate. Raw files live only on Google Drive (Shivam, 7 Nov): no raw file stays on the MSI or the HP; a job downloads what it needs, writes the database, then deletes the copy; only databases stay local; every local raw file is checked on Drive (size and hash) before its local copy is deleted.
+- OCR runs on the HP laptop only, headless (Shivam, 3 Nov): Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers; no OCR on the MSI. No PostgreSQL for now; revisit with measurements after the gate. Raw files live only on Google Drive (Shivam, 7 Nov): no raw file stays on the MSI or the HP; a job downloads what it needs, writes the database, then deletes the copy; only databases stay local; every local raw file is checked on Drive (size and hash) before its local copy is deleted. Kept local: the research library `D:\RealityEngine\raw\user_research` (about 33 GB, from the shared Drive). `Downloads\Telegram Desktop` is his brother's: never touch it.
```

## 2026-11-07T03:57:54+05:30 | kakazuya (Wolf) | 0fbda89d Rulings: prescriptive step-list briefs, prototype before briefing an unknown method, own review befo
```diff
-- Claude reviews, workers build. DeepSeek on `dsh` at max effort; read the clock for off-peak yourself (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST). Do not give pilot bank reasoning to a worker. Brief a worker only after Claude has gathered its evidence (Shivam, 4 Nov, this project only): the defect rows and ids, the exact file/function/line to edit, the table columns, and a fast check command (`--part`, one company, fixed check pages), so it does not rediscover them.
+- Claude reviews, workers build. DeepSeek on `dsh` at max effort; read the clock for off-peak yourself (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST). Do not give pilot bank reasoning to a worker. Brief a worker only after Claude has gathered its evidence (Shivam, 4 Nov, this project only): the defect rows and ids, the exact file/function/line to edit, the table columns, and a fast check command (`--part`, one company, fixed check pages), so it does not rediscover them. The brief is prescriptive, a numbered step list with limits, pitfalls, tools, budget and a stop rule; if the method is unknown, Opus prototypes it before briefing; a finished worker is checked against Opus's own tests and sample and logged before merge (Shivam, 7 Nov).
```

## 2026-11-07T04:15:39+05:30 | kakazuya (Wolf) | 4b91965b T-102: Downloads personal folders stay as they are (Shivam, 7 Nov)
```diff
-- OCR runs on the HP laptop only, headless (Shivam, 3 Nov): Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers; no OCR on the MSI. No PostgreSQL for now; revisit with measurements after the gate. Raw files live only on Google Drive (Shivam, 7 Nov): no raw file stays on the MSI or the HP; a job downloads what it needs, writes the database, then deletes the copy; only databases stay local; every local raw file is checked on Drive (size and hash) before its local copy is deleted. Kept local: the research library `D:\RealityEngine\raw\user_research` (about 33 GB, from the shared Drive). `Downloads\Telegram Desktop` is his brother's: never touch it.
+- OCR runs on the HP laptop only, headless (Shivam, 3 Nov): Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers; no OCR on the MSI. No PostgreSQL for now; revisit with measurements after the gate. Raw files live only on Google Drive (Shivam, 7 Nov): no raw file stays on the MSI or the HP; a job downloads what it needs, writes the database, then deletes the copy; only databases stay local; every local raw file is checked on Drive (size and hash) before its local copy is deleted. Kept local: the research library `D:\RealityEngine\raw\user_research` (about 33 GB, from the shared Drive). `Downloads\Telegram Desktop` is his brother's: never touch it. The personal folders in Downloads (Allen tests, neet registration, Wallpapers, photo folder, stockfish zip) stay as they are.
```

## 2026-11-07T15:30:29+05:30 | kakazuya (Wolf) | 5b5fa782 T-102: MSI dsh workers honour account (key 2 at Go limit, Shivam: use key 1)
```diff
-- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go key 1 is at 99% of its limit (6 Nov): every paid call, dsh workers on MSI and HP included, uses key 2; key 1 only to test the dsh server; free Beam and other free models still use both keys. Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Announcement types (Shivam, 7 Nov): never trust the exchange's category or headline, companies file under wrong ones; read the first page, and further pages until the document's type is clear, and build our own type dictionary from that, applied to every new filing as it arrives; the keep or skip choice is made on our own types. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
+- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go keys (7 Nov): key 2 hit its limit (429) and Shivam said use the other key, which works: dsh workers pass `account='1'` until key 2 resets; free Beam and other free models still use both keys. Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Announcement types (Shivam, 7 Nov): never trust the exchange's category or headline, companies file under wrong ones; read the first page, and further pages until the document's type is clear, and build our own type dictionary from that, applied to every new filing as it arrives; the keep or skip choice is made on our own types. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
```

## 2026-11-07T20:08:23+05:30 | kakazuya (Wolf) | 4fdf4ad3 T-102: RawStore maps the sandbox root; ruling: new raw fetches may stay local during testing
```diff
-- OCR runs on the HP laptop only, headless (Shivam, 3 Nov): Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers; no OCR on the MSI. No PostgreSQL for now; revisit with measurements after the gate. Raw files live only on Google Drive (Shivam, 7 Nov): no raw file stays on the MSI or the HP; a job downloads what it needs, writes the database, then deletes the copy; only databases stay local; every local raw file is checked on Drive (size and hash) before its local copy is deleted. Kept local: the research library `D:\RealityEngine\raw\user_research` (about 33 GB, from the shared Drive). `Downloads\Telegram Desktop` is his brother's: never touch it. The personal folders in Downloads (Allen tests, neet registration, Wallpapers, photo folder, stockfish zip) stay as they are.
+- OCR runs on the HP laptop only, headless (Shivam, 3 Nov): Microsoft TextRecognizer first pass at 300 DPI grayscale, a stronger reader for low-confidence numbers; no OCR on the MSI. No PostgreSQL for now; revisit with measurements after the gate. Raw files live only on Google Drive (Shivam, 7 Nov): no raw file stays on the MSI or the HP; a job downloads what it needs, writes the database, then deletes the copy; only databases stay local; every local raw file is checked on Drive (size and hash) before its local copy is deleted. During the testing phase newly fetched raw files may pile up locally again; sweep them to Drive later with `raw_to_drive` (Shivam, 7 Nov evening). Kept local: the research library `D:\RealityEngine\raw\user_research` (about 33 GB, from the shared Drive). `Downloads\Telegram Desktop` is his brother's: never touch it. The personal folders in Downloads (Allen tests, neet registration, Wallpapers, photo folder, stockfish zip) stay as they are.
```

## 2026-11-07T23:44:40+05:30 | kakazuya (Wolf) | fb88d426 T-104: Antigravity CLI worker ticket; ruling: agy runs only gemini-3.8-flash-medium
```diff
-- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go keys (7 Nov): key 2 hit its limit (429) and Shivam said use the other key, which works: dsh workers pass `account='1'` until key 2 resets; free Beam and other free models still use both keys. Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Announcement types (Shivam, 7 Nov): never trust the exchange's category or headline, companies file under wrong ones; read the first page, and further pages until the document's type is clear, and build our own type dictionary from that, applied to every new filing as it arrives; the keep or skip choice is made on our own types. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
+- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go keys (7 Nov): key 2 hit its limit (429) and Shivam said use the other key, which works: dsh workers pass `account='1'` until key 2 resets; free Beam and other free models still use both keys. Antigravity CLI (`agy`, Google AI Pro; Shivam, 7 Nov): run only `--model gemini-3.8-flash-medium`, never another model through it. Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Announcement types (Shivam, 7 Nov): never trust the exchange's category or headline, companies file under wrong ones; read the first page, and further pages until the document's type is clear, and build our own type dictionary from that, applied to every new filing as it arrives; the keep or skip choice is made on our own types. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
```

## 2026-11-08T02:39:26+05:30 | kakazuya (Wolf) | f5ff1336 T-112: agy-worker runs with --dangerously-skip-permissions by default (Shivam's ruling, 8 Nov)
```diff
-- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go keys (7 Nov): key 2 hit its limit (429) and Shivam said use the other key, which works: dsh workers pass `account='1'` until key 2 resets; free Beam and other free models still use both keys. Antigravity CLI (`agy`, Google AI Pro; Shivam, 7 Nov): run only `--model gemini-3.8-flash-medium`, never another model through it. Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Announcement types (Shivam, 7 Nov): never trust the exchange's category or headline, companies file under wrong ones; read the first page, and further pages until the document's type is clear, and build our own type dictionary from that, applied to every new filing as it arrives; the keep or skip choice is made on our own types. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
+- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go keys (7 Nov): key 2 hit its limit (429) and Shivam said use the other key, which works: dsh workers pass `account='1'` until key 2 resets; free Beam and other free models still use both keys. Antigravity CLI (`agy`, Google AI Pro; Shivam, 7 Nov): run only `--model gemini-3.8-flash-medium`, never another model through it. agy workers run headless with `--dangerously-skip-permissions` (Shivam, 8 Nov). Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Announcement types (Shivam, 7 Nov): never trust the exchange's category or headline, companies file under wrong ones; read the first page, and further pages until the document's type is clear, and build our own type dictionary from that, applied to every new filing as it arrives; the keep or skip choice is made on our own types. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
```

## 2026-11-08T03:43:44+05:30 | kakazuya (Wolf) | b07c30a8 T-113: standing rule (worker never checks own code) and row check layer prototype for guidance and k
```diff
+- Architecture, standing (Shivam, 8 Nov): the worker that wrote code never checks it, and correctness must not depend on Opus reading rows. Every row an extractor writes passes an independent script check layer (`reality_engine/pilot3/row_checks.py`, T-113) written by someone other than the extractor's author: quote anchor on the cited page, metric fits the company's sector and is the company's own figure, reconciliation with statements and other documents, plausibility and scale. Rows are `verified`, `unverified` (served labelled) or `quarantined` (never served); when unsure, write no row. Each extractor release is gated on a fresh hidden hold-out of companies its worker never saw, plus rulings diff and tool-call budgets in code; Opus reads only a fixed random sample per release (about 60 rows per sector or document stratum), never every row; full runs watch quarantine rate per metric, sector and document type.
-- Merge gate with hidden evaluation and rulings diff; tool-call budgets enforced in code; read limit if the median stays above 10 calls before first edit.
```

## 2026-11-08T13:32:39+05:30 | kakazuya (Wolf) | af29a663 Rulings: investor-question scope (peers later by model, brokerage facts only, regulator fetcher T-11
```diff
-- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go keys (7 Nov): key 2 hit its limit (429) and Shivam said use the other key, which works: dsh workers pass `account='1'` until key 2 resets; free Beam and other free models still use both keys. Antigravity CLI (`agy`, Google AI Pro; Shivam, 7 Nov): run only `--model gemini-3.8-flash-medium`, never another model through it. agy workers run headless with `--dangerously-skip-permissions` (Shivam, 8 Nov). Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Announcement types (Shivam, 7 Nov): never trust the exchange's category or headline, companies file under wrong ones; read the first page, and further pages until the document's type is clear, and build our own type dictionary from that, applied to every new filing as it arrives; the keep or skip choice is made on our own types. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale.
+- Proxy is the last resort, reported apart from real answers. Do not loosen a grader to raise a score. The 1,305-question pilot10 set is approved: "solid for practical life queries" (Shivam, 5 Nov). KPI rows the scripts cannot settle may go to free `beam-free` on both OpenCode Go keys, at zero cost, as a step apart from the script build (5 Nov). Guidance sentences too, with Opus writing that code, not a dsh worker (6 Nov). Go keys (7 Nov): key 2 hit its limit (429) and Shivam said use the other key, which works: dsh workers pass `account='1'` until key 2 resets; free Beam and other free models still use both keys. Antigravity CLI (`agy`, Google AI Pro; Shivam, 7 Nov): run only `--model gemini-3.8-flash-medium`, never another model through it. agy workers run headless with `--dangerously-skip-permissions` (Shivam, 8 Nov). Document scope (Shivam, 7 Nov): the bulk is decks and call transcripts; annual reports by script, only selected sections, no heavy reading; read an annual report in full only for a company that publishes no calls or decks; keep credit rating and borrowing documents. Announcement types (Shivam, 7 Nov): never trust the exchange's category or headline, companies file under wrong ones; read the first page, and further pages until the document's type is clear, and build our own type dictionary from that, applied to every new filing as it arrives; the keep or skip choice is made on our own types. Settled 6 Nov: DeepSeek answers need Opus's help (model-vs-store test closed); the 600-answer tests are past, testing is now at universal scale. Investor-question scope (Shivam, 8 Nov): peer comparison comes later and needs no special table, a model compares two or more companies' rows once each is in the database; brokerage reports count only for the facts they state, never targets or ratings; PIB does not cover RBI, IRDAI, SEBI and other regulators, so their circulars, notices and bulletins need their own fetcher (T-117, later).
```

## 2026-11-08T13:50:46+05:30 | kakazuya (Wolf) | 14f3cddd Rulings: ultimate objective is 6m-2y price prediction from the least reliable data; T-118 factor wei
```diff
-- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. Goal (6 Nov): store the facts so a cheap model gets Opus-quality answers, not brute-force digging by a strong model. Tables, extractors, chunks, tools and the MCP server must scale unchanged to the whole NSE+BSE universe; the ten companies only teach how to build it (6 Nov). Golden benchmark for the pilot (3 Nov): every model call goes through the `reality-data` MCP, a direct db or raw read only when absolutely necessary; every extraction script's design is written up (guide section O) for the full run. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK).
+- Next objective (Shivam, 3 Nov): replicate the pilot's AI answer quality with our own scripts on CPU/GPU/NPU, universal across KEC, BAJFINANCE and HINDALCO documents, writing facts into SQLite/DuckDB; every answer comes from that database via MCP, raw records only when absolutely necessary; a question the database cannot answer is a gap to fill in the database. Goal (6 Nov): store the facts so a cheap model gets Opus-quality answers, not brute-force digging by a strong model. Tables, extractors, chunks, tools and the MCP server must scale unchanged to the whole NSE+BSE universe; the ten companies only teach how to build it (6 Nov). Golden benchmark for the pilot (3 Nov): every model call goes through the `reality-data` MCP, a direct db or raw read only when absolutely necessary; every extraction script's design is written up (guide section O) for the full run. AI OCR or model calls only to cut what scripts cannot do, within a budget that burns at most 1-2 months of subscription (OpenCode Go, DeepInfra or similar, with his OK). Ultimate objective (Shivam, 8 Nov): predict any stock's price 6 months, 1 year and 2 years ahead from data we hold reliably, with the least information that does it; gathering data is not the goal and more data does not always help. Focus on the few heavyweight factors that move prices beyond the short term (sentiment swings within 6 months); other data points only add angles.
```

## 2026-11-08T14:15:43+05:30 | kakazuya (Wolf) | 2856c400 T-120: rulings (verbatim statements first, compute judges at scale; pilot companies may hold pre-FY2
```diff
-- Scope is query AND compute. A number the filings do not state is a formula to define. Empty store means not extracted: never report it as a gap or "not held" without checking `tasks/DATA_INVENTORY.md` and raw text. A results filing's table prints QoQ and YoY comparative columns: read them before calling any quarter missing or asking for a download (Shivam, 4 Nov).
+- Scope is query AND compute. A number the filings do not state is a formula to define. Empty store means not extracted: never report it as a gap or "not held" without checking `tasks/DATA_INVENTORY.md` and raw text. A results filing's table prints QoQ and YoY comparative columns: read them before calling any quarter missing or asking for a download (Shivam, 4 Nov). Verbatim first (Shivam, 8 Nov): language reads many ways in context, so store what management, government officials and regulators (RBI, IRDAI, SEBI, PIB ...) said verbatim with its source, date and speaker; the model judges meaning at query time. Structured numbers (XBRL) stay as they are. This is a pilot method: at scale, judgment and second/third-order links (macro, statements, news, sentiment) must come from our own compute (ML or mathematical models), not Opus reading everything. Pilot companies may hold documents before the FY24 window so text factors can be tested over 2-year horizons.
```

## 2026-11-08T16:04:40+05:30 | kakazuya (Wolf) | 290e1fc0 T-122: ruling, no backsliding across companies; structural rules over heuristics
```diff
-- Architecture, standing (Shivam, 8 Nov): the worker that wrote code never checks it, and correctness must not depend on Opus reading rows. Every row an extractor writes passes an independent script check layer (`reality_engine/pilot3/row_checks.py`, T-113) written by someone other than the extractor's author: quote anchor on the cited page, metric fits the company's sector and is the company's own figure, reconciliation with statements and other documents, plausibility and scale. Rows are `verified`, `unverified` (served labelled) or `quarantined` (never served); when unsure, write no row. Each extractor release is gated on a fresh hidden hold-out of companies its worker never saw, plus rulings diff and tool-call budgets in code; Opus reads only a fixed random sample per release (about 60 rows per sector or document stratum), never every row; full runs watch quarantine rate per metric, sector and document type.
+- Architecture, standing (Shivam, 8 Nov): the worker that wrote code never checks it, and correctness must not depend on Opus reading rows. Every row an extractor writes passes an independent script check layer (`reality_engine/pilot3/row_checks.py`, T-113) written by someone other than the extractor's author: quote anchor on the cited page, metric fits the company's sector and is the company's own figure, reconciliation with statements and other documents, plausibility and scale. Rows are `verified`, `unverified` (served labelled) or `quarantined` (never served); when unsure, write no row. Each extractor release is gated on a fresh hidden hold-out of companies its worker never saw, plus rulings diff and tool-call budgets in code; Opus reads only a fixed random sample per release (about 60 rows per sector or document stratum), never every row; full runs watch quarantine rate per metric, sector and document type. No backsliding (Shivam, 8 Nov): every extractor or checker change is re-scored on every row ever hand-read across all companies (T-122 regression set) and merges only with zero right rows lost or quarantined and zero wrong rows verified; prefer structural rules (second source, filed-statement reconciliation, verbatim storage) over per-company heuristics.
```

## 2026-11-08T17:26:21+05:30 | kakazuya (Wolf) | cec49dbd T-125: merge dsh 20261108T114201Z-41e0aa80 (project_rules/project_state tools, never-cut rulings hoo
```diff
--# Shivam's rulings: loaded into every session, also after compaction. Under 40 lines.
--When Shivam rules or corrects something, write it here before the next action. `[check]` means code enforces it; the rest rely on this file.
++# Shivam's rulings: loaded into every session, also after compaction. Max 8,000 characters.
++Write a new ruling here before the next action. `[check]` = code enforces it. Full wording: `docs/rulings/RULINGS_full_2026-11-08.md`; by topic: `project_rules(topic)` tool.
--## Order and scope
++## Goal and scope
++- Ultimate goal (8 Nov): predict any stock 6m/1y/2y ahead from reliably held data, least information that does it; few heavyweight factors; more data is not the goal.
++- Store facts so a cheap model gets Opus-quality answers through the `reality-data` MCP (direct db/raw reads only when necessary); tables, extractors, tools must scale unchanged to all NSE+BSE; pilot companies only teach the build. Scripts first; AI/OCR only where scripts fail, within 1-2 months of subscription, with his OK.
++- Golden order: raw data, banks, schema, pilot, re-run to 95% answered plus checklist, only then the full run.
++- Scope is query AND compute: an unstated number is a formula. Empty store = not extracted, never "not held" before checking `tasks/DATA_INVENTORY.md` and raw text; read results tables' QoQ/YoY columns before calling a quarter missing.
++- Verbatim first (8 Nov): store what management, officials and regulators said verbatim with source, date, speaker; the model judges at query time; XBRL stays as filed. At scale, judgment and 2nd/3rd-order links come from our own compute, not Opus. Pilot companies may hold pre-FY24 documents.
++- Documents (7 Nov): bulk is decks and call transcripts; annual reports by script, selected sections only (in full only for a company with no calls or decks); keep credit-rating and borrowing documents. Never trust the exchange's category or headline: read pages until the type is clear, keep/skip on our own type dictionary.
++- Investor questions (8 Nov): peers later, a model compares stored rows; brokerage reports only for stated facts, never targets or ratings; regulator circulars (RBI, SEBI, IRDAI) need their own fetcher (T-117).
++- Banks and tests: bank rulings bind (diff rebuilds against the frozen 1,901 bank); questions use pilot stocks; undated question = `as_of` 2026-10-19; report hand-read scores only; the 1,305-question pilot10 set is approved. Proxy is the last resort, reported apart. Never loosen a grader.
++
++## Models and keys
++- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself); in peak hours code workers are Sonnet 5.5 medium (`tasks/night_loop/sonnet_worker.py`). dsh workers use Go `account='1'` until key 2 resets (7 Nov). Free `beam-free` (both Go keys) may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
++- `agy` runs only `gemini-3.8-flash-medium`, headless with `--dangerously-skip-permissions`. Settled: DeepSeek answers need Opus's help; testing is at universal scale.
++- Claude reviews, workers build; Opus writes ~20-25% (design, tests, review, one working example). Brief only after gathering evidence: defect rows, exact file/function/line, columns, a fast check command; numbered steps with limits, pitfalls, tools, budget, stop rule; unknown method -> Opus prototypes first. Check a finished worker against Opus's own tests and sample, log it, then merge. No pilot bank reasoning to workers.
++- Lean: add nothing that does not stop a failure we have had. Max 2 code workers at once; data/research jobs on idle machines. Branches merged or deleted within 24 h.
++- One task stays in one worker session; Opus reviews and guides the next round; new worker only at 1M context or a new task. No live adviser calls to Claude. Tickets hold tests, never rules.
++- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer (quote anchor, sector fit, own figure, reconciliation, scale): `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Each release is gated on a fresh hidden hold-out, the rulings diff and tool budgets in code; Opus reads a fixed random sample (~60 rows per stratum). No backsliding: re-score every hand-read row (T-122 set); merge only with zero right rows lost and zero wrong rows verified; prefer structural rules over per-company ones.
++- No docs, no merge; doc sweep + data inventory at session close, for Wolf, Eagle and every worker. [check: doc_gate]
++- Start files: `STATE.md` 4,000 characters, this file 8,000, `AGENTS.md` 150 lines. [check: doc_gate]
++- Every worker start names `permission`. [check: start gate] HP work is headless. [check: test_hp_headless] Sessions run to 450k context; at 400k write the wrap-up (commit, next action in `tasks/STATE.md`, doc sweep).
++- Page-reading subagents: batches of 8 pages, under 100k context, Haiku at medium effort.
++- Keep a live watch on every running job (finish, stall, errors); check real progress before reporting; review a finished worker at once. [check: T-050 stop hook]
++- A new task from Shivam becomes a ticket first (`task_board add`); commits on `main` name a ticket. [check: commit-msg]
++- Log every worker and session in `tasks/efficiency/WORKER_REVIEW_LOG.xlsx` and apply lessons to the next brief. Bring ranked ideas from measurements unprompted. RAM <90% or CPU <70% used = start useful work. Report compute waste. Decide what you can; do not argue a ruling, find how to do it. Session titles keep the `sv-`/`neo-` prefix.
++
++## Data and machines
++- Raw files live only on Drive (7 Nov): jobs download, write the database, delete the copy; check size and hash on Drive before deleting a local copy; new fetches may pile up locally during testing, sweep with `raw_to_drive`. Kept local: `D:\RealityEngine\raw\user_research`.
++- OCR on the HP only, headless (TextRecognizer 300 DPI first, stronger reader for low-confidence numbers). No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
++- Print or copy keys; read `D:\Shivam_Private\Manual Dumps` or send it anywhere; put amounts in the repo or decision log.
++- Push without his OK (given for merged main, 3 Nov). Use paid models (DeepInfra, Haiku beyond an approved run) without his OK.
--
--## Agreed direction, not yet built
++- Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. No spend reports: work until he says stop.
```

## 2026-11-08T17:34:42+05:30 | kakazuya (Wolf) | 84f42068 T-125: Shivam's Excel ticket board (reports/ticket_board.xlsx + html) synced on every task_board cha
```diff
-- Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. No spend reports: work until he says stop.
+- Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. His source of truth for tickets is `D:\RealityEngine
```

## 2026-11-08T18:03:55+05:30 | kakazuya (Wolf) | 51390ba7 T-124: per-run answer report (xlsx + csv: questions, answers, grades, errors, documents, root causes
```diff
-- Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. His source of truth for tickets is `D:\RealityEngine
+- Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. His source of truth for tickets is `D:\RealityEngine
+eports	icket_board.xlsx` (+ `.html`), kept in sync with the tracker on every change (8 Nov). [check: task_board + post-commit hook] After every question/answer run: an Excel + CSV in the reports folder with questions, answers, grades, errors, documents and root causes (`answer_run_report.py`; 8 Nov). No spend reports: work until he says stop.
```

## 2026-11-08T18:05:57+05:30 | kakazuya (Wolf) | e933e14d T-125: standing-rules sheet (reports/standing_rules.xlsx + html): every ruling and how it is enforce
```diff
-- Print or copy keys; read `D:\Shivam_Private\Manual Dumps` or send it anywhere; put amounts in the repo or decision log.
-- Push without his OK (given for merged main, 3 Nov). Use paid models (DeepInfra, Haiku beyond an approved run) without his OK.
+- Print or copy keys; read `D:\Shivam_Private\Manual Dumps` or send it anywhere; put amounts in the repo or decision log. Push without his OK (given for merged main, 3 Nov). Use paid models (DeepInfra, Haiku beyond an approved run) without his OK.
-eports	icket_board.xlsx` (+ `.html`), kept in sync with the tracker on every change (8 Nov). [check: task_board + post-commit hook] After every question/answer run: an Excel + CSV in the reports folder with questions, answers, grades, errors, documents and root causes (`answer_run_report.py`; 8 Nov). No spend reports: work until he says stop.
+eports	icket_board.xlsx` (+ `.html`), kept in sync with the tracker on every change (8 Nov). [check: task_board + post-commit hook] After every question/answer run: an Excel + CSV in the reports folder with questions, answers, grades, errors, documents and root causes (`answer_run_report.py`; 8 Nov). Rules and how each is enforced: `D:\RealityEngine
+eports\standing_rules.xlsx` (+ `.html`), rewritten when this file changes. No spend reports: work until he says stop.
```

## 2026-11-08T18:46:44+05:30 | kakazuya (Wolf) | c011609c T-127: merge dsh 20261108T124200Z-67ccd079 (worker_review and merge_tests merge gates, code_worker_l
```diff
--Write a new ruling here before the next action. `[check]` = code enforces it. Full wording: `docs/rulings/RULINGS_full_2026-11-08.md`; by topic: `project_rules(topic)` tool.
++New rulings via `ruling add`. `[check]` = code enforces it. Full wording: `docs/rulings/RULINGS_full_2026-11-08.md`; by topic: `project_rules(topic)` tool.
++- Banks and tests: bank rulings bind (diff rebuilds vs the frozen 1,901 bank); undated question = `as_of` 2026-10-19; report hand-read scores only; the 1,305-question pilot10 set is approved. Proxy is the last resort, reported apart. Never loosen a grader.
++- Claude reviews, workers build; Opus writes ~20-25% (design, tests, review, one working example). Brief only after gathering evidence: defect rows, exact file/function/line, columns, a fast check command; numbered steps with limits, pitfalls, tools, budget, stop rule; unknown method -> Opus prototypes first. Check a finished worker against Opus's own tests and sample, log it, then merge [check: worker_review] [check: merge_tests]. No pilot bank reasoning to workers. Page-reading subagents: batches of 8 pages, under 100k context, Haiku medium.
++- Lean: add nothing that does not stop a failure we have had. Max 2 code workers at once [check: code_worker_limit]; data/research jobs on idle machines. Branches merged or deleted within 24 h.
++- Log every worker (`tasks/efficiency/worker_reviews.jsonl` -> `WORKER_REVIEW_LOG.xlsx`) and apply lessons to the next brief. [check: worker_review] Bring ranked ideas from measurements unprompted. RAM <90% or CPU <70% used = start useful work. Report compute waste. Decide what you can; never argue a ruling. Session titles keep the `sv-`/`neo-` prefix.
```

## 2026-11-09T15:52:32+05:30 | kakazuya (Wolf) | 12bf3e26 T-154: no session-length limit (Shivam 9 Nov; context_guard unregistered, STATE done/pending notes s
```diff
-- Every worker start names `permission`. [check: start gate] HP work is headless. [check: test_hp_headless] Sessions run to 450k context; at 400k write the wrap-up (commit, next action in `tasks/STATE.md`, doc sweep).
+- Every worker start names `permission`. [check: start gate] HP work is headless. [check: test_hp_headless] No session-length limit (9 Nov); keep notes as you go: what is done and what is pending, in `tasks/STATE.md`.
```

## 2026-11-09T20:08:07+05:30 | kakazuya (Wolf) | 03a7ec78 T-156: ruling 'data not found + nearest supporting point'; pilot20 final 229/230; consolidated repor
```diff
+- Unpublished data (9 Nov): the answer says 'data not found' with what was searched, plus the nearest supporting point labelled as such; graded right when the search holds up.
```

## 2026-11-10T00:10:47+05:30 | kakazuya (Wolf) | a9f052b0 T-160: ruling 10 Nov: LongCat 2.5 (longcat-2.5-free, effort high, both Go keys) is the peak-hours de
```diff
-- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself); in peak hours code workers are Sonnet 5.5 medium (`tasks/night_loop/sonnet_worker.py`). dsh workers use Go `account='1'` until key 2 resets (7 Nov). Free `beam-free` (both Go keys) may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
+- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself); in peak hours workers default to LongCat 2.5 at effort high (`longcat-2.5-free`, free on Go both keys 10-24 Nov; `run_deepseek_harness --model longcat-2.5-free`), also off-peak for cheap tasks (10 Nov). dsh workers use Go `account='1'` until key 2 resets (7 Nov). Free `beam-free` (both Go keys) may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
```

## 2026-11-10T00:15:51+05:30 | kakazuya (Wolf) | 386cf6ff T-160: ruling 10 Nov (until 15 Nov): offload to the HP when MSI RAM is short; HP x64 Python with PyM
```diff
-- OCR on the HP only, headless (TextRecognizer 300 DPI first, stronger reader for low-confidence numbers). No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
+- OCR on the HP only, headless (TextRecognizer 300 DPI first, stronger reader for low-confidence numbers). Until 15 Nov: work never stops for MSI RAM; copy the job's data to an HP worktree folder, run there (x64 Python `C:\RE\py313x64`), bring results back, delete the HP copy (10 Nov). No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
```

## 2026-11-10T00:22:18+05:30 | kakazuya (Wolf) | 530b9267 Ruling 10 Nov: replies always in proper Indian English, whatever language Shivam writes in
```diff
-- Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. His source of truth for tickets is `D:\RealityEngine
+- Replies always in proper Indian English, whatever language he writes in; never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. His source of truth for tickets is `D:\RealityEngine
```

## 2026-11-10T10:45:30+05:30 | kakazuya (Wolf) | 3669c4f0 Ruling 10 Nov: Beam (beam-free) replaces LongCat 2.5 as the peak-hours default worker after the bake
```diff
-- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself); in peak hours workers default to LongCat 2.5 at effort high (`longcat-2.5-free`, free on Go both keys 10-24 Nov; `run_deepseek_harness --model longcat-2.5-free`), also off-peak for cheap tasks (10 Nov). dsh workers use Go `account='1'` until key 2 resets (7 Nov). Free `beam-free` (both Go keys) may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
+- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself); in peak hours workers default to Beam (`beam-free`, free on Go both keys; `run_deepseek_harness --model beam-free`), also off-peak for cheap tasks (10 Nov: Beam beat LongCat 2.5 in the bake-off, 101 vs 94 of 108 checks and ~5x faster; LongCat no longer the default). dsh workers use Go `account='1'` until key 2 resets (7 Nov). Free `beam-free` (both Go keys) may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
```

## 2026-11-10T11:15:03+05:30 | kakazuya (Wolf) | 2febb583 Session close sweep: no-headless-Opus ruling, site_documents folders documented, inventory regenerat
```diff
-- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself); in peak hours workers default to Beam (`beam-free`, free on Go both keys; `run_deepseek_harness --model beam-free`), also off-peak for cheap tasks (10 Nov: Beam beat LongCat 2.5 in the bake-off, 101 vs 94 of 108 checks and ~5x faster; LongCat no longer the default). dsh workers use Go `account='1'` until key 2 resets (7 Nov). Free `beam-free` (both Go keys) may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
+- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself); in peak hours workers default to Beam (`beam-free`, free on Go both keys; `run_deepseek_harness --model beam-free`), also off-peak for cheap tasks (10 Nov: Beam beat LongCat 2.5 in the bake-off, 101 vs 94 of 108 checks and ~5x faster; LongCat no longer the default). No headless Opus runs unless Shivam says so (10 Nov): a separate read-only dsh worker grades a branch it did not write. dsh workers use Go `account='1'` until key 2 resets (7 Nov). Free `beam-free` (both Go keys) may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
```

## 2026-11-10T15:18:04+05:30 | kakazuya (Eagle) | f1238110 Beam only while free on OpenCode: free_model_check flag + harness refusal; routing ruling (Shivam 10
```diff
-- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself); in peak hours workers default to Beam (`beam-free`, free on Go both keys; `run_deepseek_harness --model beam-free`), also off-peak for cheap tasks (10 Nov: Beam beat LongCat 2.5 in the bake-off, 101 vs 94 of 108 checks and ~5x faster; LongCat no longer the default). No headless Opus runs unless Shivam says so (10 Nov): a separate read-only dsh worker grades a branch it did not write. dsh workers use Go `account='1'` until key 2 resets (7 Nov). Free `beam-free` (both Go keys) may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
+- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`, both Go keys; dsh-worker `model='beam-free'` or `run_deepseek_harness`) writes plumbing code (tables, tools, build parts, tests, scripts) in any hour and grades branches read-only in peak; extraction rules judged by row precision go to DeepSeek. Every branch: a separate read-only grader, then Claude's own tests + sample, merge only with 0 earlier-right rows lost. Beam only while OpenCode lists it free: `free_model_check` flag, harness refuses beam-free once it charges [check: free_model_check]. No headless Opus unless Shivam says so. dsh workers use Go `account='1'` until key 2 resets (7 Nov). Beam may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
```

## 2026-11-10T16:09:46+05:30 | kakazuya (Eagle) | cb5c06e3 Code-worker cap 2 -> 4 on the MSI (Shivam 10 Nov: laptop dedicated); DSH_WORKER_MAX_CODE_WORKERS ove
```diff
-- Lean: add nothing that does not stop a failure we have had. Max 2 code workers at once [check: code_worker_limit]; data/research jobs on idle machines. Branches merged or deleted within 24 h.
+- Lean: add nothing that does not stop a failure we have had. Max 4 code workers at once on the MSI (10 Nov; was 2 while the browser shared it) [check: code_worker_limit]; data/research jobs on idle machines. Branches merged or deleted within 24 h.
```

## 2026-11-10T20:36:13+05:30 | kakazuya (Eagle) | 4a7ef0b9 Ruling (Shivam 10 Nov): score only on frozen sets; T-172 s10 frozen half, T-173 s20 exam set; Fable 
```diff
-- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer (quote anchor, sector fit, own figure, reconciliation, scale): `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Each release is gated on a fresh hidden hold-out, the rulings diff and tool budgets in code; Opus reads a fixed random sample (~60 rows per stratum). No backsliding: re-score every hand-read row (T-122 set); merge only with zero right rows lost and zero wrong rows verified; prefer structural rules over per-company ones.
+- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer (quote anchor, sector fit, own figure, reconciliation, scale): `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Releases gate on a hidden hold-out, rulings diff, tool budgets; a fixed random sample is hand-read (~60/stratum). Score only on frozen sets (10 Nov): half of each new set's questions never drive fixes; an exam set (s20: micro/BSE-only/new sectors) gives the reported number. Merge only with zero right rows lost, zero wrong rows verified; structural rules, not per-company.
```

## 2026-11-10T21:54:54+05:30 | kakazuya (Eagle) | 888843fb Shivam 10 Nov board decisions: close T-023, T-116, T-122, T-125, T-126; T-021/T-022 become rulings (
```diff
-- Investor questions (8 Nov): peers later, a model compares stored rows; brokerage reports only for stated facts, never targets or ratings; regulator circulars (RBI, SEBI, IRDAI) need their own fetcher (T-117).
+- Investor questions (8 Nov): peers later, a model compares stored rows; brokerage reports only for stated facts, never targets or ratings; regulator circulars (RBI, SEBI, IRDAI) need their own fetcher (T-117). Policy (10 Nov): other-language PIB/official text only when no English version exists; each policy maps to companies touched: advantageous, disadvantageous or neutral, with why and a figure where possible.
-- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`, both Go keys; dsh-worker `model='beam-free'` or `run_deepseek_harness`) writes plumbing code (tables, tools, build parts, tests, scripts) in any hour and grades branches read-only in peak; extraction rules judged by row precision go to DeepSeek. Every branch: a separate read-only grader, then Claude's own tests + sample, merge only with 0 earlier-right rows lost. Beam only while OpenCode lists it free: `free_model_check` flag, harness refuses beam-free once it charges [check: free_model_check]. No headless Opus unless Shivam says so. dsh workers use Go `account='1'` until key 2 resets (7 Nov). Beam may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
+- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`, both keys) writes plumbing code any hour and grades read-only in peak; extraction judged by row precision goes to DeepSeek. Every branch: separate read-only grader, then Claude's tests + sample; merge with 0 earlier-right rows lost. Beam only while free [check: free_model_check]. No headless Opus unless Shivam says so. dsh workers use Go `account='1'` until key 2 resets (7 Nov). Beam may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
-- Lean: add nothing that does not stop a failure we have had. Max 4 code workers at once on the MSI (10 Nov; was 2 while the browser shared it) [check: code_worker_limit]; data/research jobs on idle machines. Branches merged or deleted within 24 h.
+- Lean: add nothing that does not stop a failure we have had. Max 4 code workers on the MSI (10 Nov) [check: code_worker_limit]; data/research jobs on idle machines. Branches merged or deleted within 24 h.
-- OCR on the HP only, headless (TextRecognizer 300 DPI first, stronger reader for low-confidence numbers). Until 15 Nov: work never stops for MSI RAM; copy the job's data to an HP worktree folder, run there (x64 Python `C:\RE\py313x64`), bring results back, delete the HP copy (10 Nov). No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
+- OCR on the HP only, headless, only for pages with no or a jumbled text layer (10 Nov) (TextRecognizer 300 DPI first, stronger reader for low-confidence numbers). Until 15 Nov: work never stops for MSI RAM; copy the job's data to an HP worktree folder, run there (x64 Python `C:\RE\py313x64`), bring results back, delete the HP copy (10 Nov). No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
-- Replies always in proper Indian English, whatever language he writes in; never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. His source of truth for tickets is `D:\RealityEngine
-eports	icket_board.xlsx` (+ `.html`), kept in sync with the tracker on every change (8 Nov). [check: task_board + post-commit hook] After every question/answer run: an Excel + CSV in the reports folder with questions, answers, grades, errors, documents and root causes (`answer_run_report.py`; 8 Nov). Rules and how each is enforced: `D:\RealityEngine
-eports\standing_rules.xlsx` (+ `.html`), rewritten when this file changes. No spend reports: work until he says stop.
+- Replies always in proper Indian English, whatever language he writes in; never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. His source of truth for tickets is `D:\RealityEngine\reports\ticket_board.xlsx` (+ `.html`), kept in sync with the tracker on every change (8 Nov). [check: task_board + post-commit hook] After every question/answer run: an Excel + CSV in the reports folder with questions, answers, grades, errors, documents and root causes (`answer_run_report.py`; 8 Nov). Rules and how each is enforced: `D:\RealityEngine\reports\standing_rules.xlsx` (+ `.html`), rewritten when this file changes. No spend reports: work until he says stop.
```

## 2026-11-10T22:00:58+05:30 | kakazuya (Eagle) | 6b6323a9 Ruling (Shivam 10 Nov): factor rewards are time-varying, recomputed per stock/sector/regime with the
```diff
-- Ultimate goal (8 Nov): predict any stock 6m/1y/2y ahead from reliably held data, least information that does it; few heavyweight factors; more data is not the goal.
-- Store facts so a cheap model gets Opus-quality answers through the `reality-data` MCP (direct db/raw reads only when necessary); tables, extractors, tools must scale unchanged to all NSE+BSE; pilot companies only teach the build. Scripts first; AI/OCR only where scripts fail, within 1-2 months of subscription, with his OK.
+- Ultimate goal (8 Nov): predict any stock 6m/1y/2y ahead from reliably held data, least information that does it; few heavyweight factors; more data is not the goal. Factor rewards aren't fixed laws (10 Nov): recompute at every point in time per stock, sector and regime; report the statistical mode of rewarded factors and shifts.
+- Store facts so a cheap model gets Opus-quality answers through the `reality-data` MCP (raw reads only when needed); tables, extractors, tools must scale unchanged to all NSE+BSE; pilot companies teach the build. Scripts first; AI/OCR only where scripts fail, within 1-2 months of subscription, with his OK.
-- Banks and tests: bank rulings bind (diff rebuilds vs the frozen 1,901 bank); undated question = `as_of` 2026-10-19; report hand-read scores only; the 1,305-question pilot10 set is approved. Proxy is the last resort, reported apart. Never loosen a grader.
+- Banks and tests: bank rulings bind (diff rebuilds vs the frozen 1,901 bank); undated question = `as_of` 2026-10-19; report hand-read scores only; pilot10's 1,305 questions are approved. Proxy is the last resort, reported apart. Never loosen a grader.
-- Claude reviews, workers build; Opus writes ~20-25% (design, tests, review, one working example). Brief only after gathering evidence: defect rows, exact file/function/line, columns, a fast check command; numbered steps with limits, pitfalls, tools, budget, stop rule; unknown method -> Opus prototypes first. Check a finished worker against Opus's own tests and sample, log it, then merge [check: worker_review] [check: merge_tests]. No pilot bank reasoning to workers. Page-reading subagents: batches of 8 pages, under 100k context, Haiku medium.
+- Claude reviews, workers build; Opus writes ~20-25% (design, tests, review, one working example). Briefs carry evidence (defect rows, file/function/line, a fast check), numbered steps, limits, pitfalls, budget and a stop rule; unknown method -> Opus prototypes first. Check a finished worker against Opus's own tests and sample, log it, then merge [check: worker_review] [check: merge_tests]. No pilot bank reasoning to workers. Page-reading subagents: batches of 8 pages, under 100k context, Haiku medium.
-- Log every worker (`tasks/efficiency/worker_reviews.jsonl` -> `WORKER_REVIEW_LOG.xlsx`) and apply lessons to the next brief. [check: worker_review] Bring ranked ideas from measurements unprompted. RAM <90% or CPU <70% used = start useful work. Report compute waste. Decide what you can; never argue a ruling. Session titles keep the `sv-`/`neo-` prefix.
+- Log every worker (`tasks/efficiency/worker_reviews.jsonl` -> `WORKER_REVIEW_LOG.xlsx`) and apply lessons to the next brief. [check: worker_review] Bring ranked ideas from measurements unprompted. RAM <90% or CPU <70% used = start useful work. Report compute waste. Decide what you can; never argue rulings. Titles keep `sv-`/`neo-` prefixes.
-- Replies always in proper Indian English, whatever language he writes in; never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. His source of truth for tickets is `D:\RealityEngine\reports\ticket_board.xlsx` (+ `.html`), kept in sync with the tracker on every change (8 Nov). [check: task_board + post-commit hook] After every question/answer run: an Excel + CSV in the reports folder with questions, answers, grades, errors, documents and root causes (`answer_run_report.py`; 8 Nov). Rules and how each is enforced: `D:\RealityEngine\reports\standing_rules.xlsx` (+ `.html`), rewritten when this file changes. No spend reports: work until he says stop.
+- Replies always in proper Indian English, whatever language he writes in; never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. Ticket truth: `reports\ticket_board.xlsx` (+ `.html`), synced on every change (8 Nov). [check: task_board + post-commit hook] After every question/answer run: an Excel + CSV in the reports folder with questions, answers, grades, errors, documents and root causes (`answer_run_report.py`; 8 Nov). Rules and their enforcement: `reports\standing_rules.xlsx` (+ `.html`), rewritten when this file changes. No spend reports: work until he says stop.
```

## 2026-11-11T14:20:46+05:30 | kakazuya (Eagle) | 432afadb T-184: run ledger (every run of every model: tool calls by tool, MCP vs raw SQL vs workaround, secon
```diff
+- Run ledger (11 Nov): log every run of every model (DEVELOPER_GUIDE s7); answers say why raw SQL was used; report overfit at once.
-- Raw files live only on Drive (7 Nov): jobs download, write the database, delete the copy; check size and hash on Drive before deleting a local copy; new fetches may pile up locally during testing, sweep with `raw_to_drive`. Kept local: `D:\RealityEngine\raw\user_research`.
-- OCR on the HP only, headless, only for pages with no or a jumbled text layer (10 Nov) (TextRecognizer 300 DPI first, stronger reader for low-confidence numbers). Until 15 Nov: work never stops for MSI RAM; copy the job's data to an HP worktree folder, run there (x64 Python `C:\RE\py313x64`), bring results back, delete the HP copy (10 Nov). No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
+- Raw files live only on Drive (7 Nov): jobs download, write the database, delete the copy; check size and hash on Drive before deleting a local copy; test fetches may stay local until `raw_to_drive`. Kept local: `D:\RealityEngine\raw\user_research`.
+- OCR on the HP only, headless, only for pages with no or a jumbled text layer (10 Nov) (TextRecognizer 300 DPI first, stronger reader for low-confidence numbers). Until 15 Nov, MSI RAM short: run on the HP (`machines/HP_LAPTOP.md`), bring results back, delete the HP copy (10 Nov). No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
-- Replies always in proper Indian English, whatever language he writes in; never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. Ticket truth: `reports\ticket_board.xlsx` (+ `.html`), synced on every change (8 Nov). [check: task_board + post-commit hook] After every question/answer run: an Excel + CSV in the reports folder with questions, answers, grades, errors, documents and root causes (`answer_run_report.py`; 8 Nov). Rules and their enforcement: `reports\standing_rules.xlsx` (+ `.html`), rewritten when this file changes. No spend reports: work until he says stop.
+- Replies always in proper Indian English, whatever language he writes in; never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. Ticket truth: `reports\ticket_board.xlsx` (+ `.html`), synced on every change (8 Nov). [check: task_board + post-commit hook] After every answer run: Excel + CSV in reports (questions, answers, grades, errors, documents, root causes; `answer_run_report.py`, 8 Nov). Rules sheet: `reports\standing_rules.xlsx` (+ `.html`), rewritten with this file. No spend reports: work until he says stop.
```

## 2026-11-12T21:47:17+05:30 | kakazuya (Eagle) | ac338f22 Ruling 12 Nov: tickets = in-scope work only, rules in RULINGS, ideas in the new tasks/IDEA_BOX.md
```diff
-- `agy` runs only `gemini-3.8-flash-medium`, headless with `--dangerously-skip-permissions`. Settled: DeepSeek answers need Opus's help; testing is at universal scale.
+- `agy` runs only `gemini-3.8-flash-medium`, headless with `--dangerously-skip-permissions`.
-- One task stays in one worker session; Opus reviews and guides the next round; new worker only at 1M context or a new task. No live adviser calls to Claude. Tickets hold tests, never rules.
+- One task stays in one worker session; Opus reviews and guides the next round; new worker only at 1M context or a new task. No live adviser calls to Claude. Tickets = in-scope work only; rules here; ideas to `tasks/IDEA_BOX.md` (12 Nov).
-- Start files: `STATE.md` 4,000 characters, this file 8,000, `AGENTS.md` 150 lines. [check: doc_gate]
+- Start files: STATE 4,000 chars, this 8,000, AGENTS 150 lines. [check: doc_gate]
```

## 2026-11-12T21:58:14+05:30 | kakazuya (Eagle) | 7d7deaec T-201/T-202/T-203: promoted from the idea box with briefs; idea box records context, purpose, origin
```diff
-- Lean: add nothing that does not stop a failure we have had. Max 4 code workers on the MSI (10 Nov) [check: code_worker_limit]; data/research jobs on idle machines. Branches merged or deleted within 24 h.
-- One task stays in one worker session; Opus reviews and guides the next round; new worker only at 1M context or a new task. No live adviser calls to Claude. Tickets = in-scope work only; rules here; ideas to `tasks/IDEA_BOX.md` (12 Nov).
+- Lean: add nothing that does not stop a failure we have had. Max 4 code workers on the MSI (10 Nov) [check: code_worker_limit]; data jobs on idle machines. Branches merged or deleted within 24 h.
+- One task stays in one worker session; Opus reviews and guides the next round; new worker at 1M context or a new task. No live adviser calls to Claude. Tickets = in-scope work only; rules here; ideas to `tasks/IDEA_BOX.md` (why, purpose, review trigger; Claude proposes promotion when due) (12 Nov).
-- Start files: STATE 4,000 chars, this 8,000, AGENTS 150 lines. [check: doc_gate]
+- Start files: STATE 4,000, this 8,000, AGENTS 150 lines. [check: doc_gate]
```

## 2026-11-13T15:11:19+05:30 | kakazuya (Eagle) | a689c703 T-206: workspace journal (tasks/JOURNAL.md), ruling, start hook names the latest entry
```diff
-New rulings via `ruling add`. `[check]` = code enforces it. Full wording: `docs/rulings/RULINGS_full_2026-11-08.md`; by topic: `project_rules(topic)` tool.
+New rulings via `ruling add`; `[check]` = enforced by code. Full wording `docs/rulings/RULINGS_full_2026-11-08.md`; `project_rules(topic)`.
-- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`, both keys) writes plumbing code any hour and grades read-only in peak; extraction judged by row precision goes to DeepSeek. Every branch: separate read-only grader, then Claude's tests + sample; merge with 0 earlier-right rows lost. Beam only while free [check: free_model_check]. No headless Opus unless Shivam says so. dsh workers use Go `account='1'` until key 2 resets (7 Nov). Beam may settle KPI rows and guidance sentences scripts cannot, as a separate step; Opus writes that code.
+- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`, both keys) writes plumbing code any hour and grades read-only in peak; extraction judged by row precision goes to DeepSeek. Every branch: read-only grader, then Claude's tests + sample; merge with 0 right rows lost. Beam only while free [check: free_model_check]. No headless Opus unless Shivam says so. dsh workers use Go `account='1'` until key 2 resets (7 Nov). Beam may settle KPI/guidance rows scripts cannot (separate step; Opus code).
-- Claude reviews, workers build; Opus writes ~20-25% (design, tests, review, one working example). Briefs carry evidence (defect rows, file/function/line, a fast check), numbered steps, limits, pitfalls, budget and a stop rule; unknown method -> Opus prototypes first. Check a finished worker against Opus's own tests and sample, log it, then merge [check: worker_review] [check: merge_tests]. No pilot bank reasoning to workers. Page-reading subagents: batches of 8 pages, under 100k context, Haiku medium.
+- Claude reviews, workers build; Opus writes ~20-25% (design, tests, review, one working example). Briefs carry evidence (defect rows, file/function/line, a fast check), numbered steps, limits, pitfalls, budget and a stop rule; unknown method -> Opus prototypes first. Check a finished worker on Opus's own tests and sample, log, merge [check: worker_review] [check: merge_tests]. No pilot bank reasoning to workers. Page-reading subagents: batches of 8 pages, under 100k context, Haiku medium.
-- One task stays in one worker session; Opus reviews and guides the next round; new worker at 1M context or a new task. No live adviser calls to Claude. Tickets = in-scope work only; rules here; ideas to `tasks/IDEA_BOX.md` (why, purpose, review trigger; Claude proposes promotion when due) (12 Nov).
-- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer (quote anchor, sector fit, own figure, reconciliation, scale): `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Releases gate on a hidden hold-out, rulings diff, tool budgets; a fixed random sample is hand-read (~60/stratum). Score only on frozen sets (10 Nov): half of each new set's questions never drive fixes; an exam set (s20: micro/BSE-only/new sectors) gives the reported number. Merge only with zero right rows lost, zero wrong rows verified; structural rules, not per-company.
+- One task, one worker session (new worker at 1M context or a new task); Opus reviews each round. No live adviser calls to Claude. Tickets = in-scope work; rules here; ideas to `tasks/IDEA_BOX.md` (why, purpose, review trigger; Claude proposes promotion when due) (12 Nov).
+- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer (quote anchor, sector fit, own figure, reconciliation, scale): `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Releases gate on a hidden hold-out, rulings diff, tool budgets; ~60 rows/stratum hand-read. Score only on frozen sets (10 Nov): half of each new set's questions never drive fixes; an exam set (s20: micro/BSE-only/new sectors) gives the reported number. Merge only with zero right rows lost, zero wrong rows verified; structural rules, not per-company.
-- Every worker start names `permission`. [check: start gate] HP work is headless. [check: test_hp_headless] No session-length limit (9 Nov); keep notes as you go: what is done and what is pending, in `tasks/STATE.md`.
-- Keep a live watch on every running job (finish, stall, errors); check real progress before reporting; review a finished worker at once. [check: T-050 stop hook]
+- Every worker start names `permission`. [check: start gate] HP work is headless. [check: test_hp_headless] No session-length limit (9 Nov); done/pending notes in `tasks/STATE.md`.
+- Live watch on every running job (finish, stall, errors); check real progress before reporting; review a finished worker at once. [check: T-050 stop hook]
+- Journal (13 Nov): add a tasks/JOURNAL.md entry (work, what worked, what failed and why, fixes) at 400k context and at wrap-up; read the latest at start.
```

## 2026-11-13T23:56:09+05:30 | kakazuya (Eagle) | 302239ac T-205: r13 brief (Hydrogen answers, Opus medium grades); T-208 unseen stores and T-209 structured la
```diff
-- `agy` runs only `gemini-3.8-flash-medium`, headless with `--dangerously-skip-permissions`.
+- `agy`: coding `gemini-3.8-flash-medium`; answer tests (13 Nov): `gemini-4-hydrogen-high` answers, Opus 5.5 medium grades.
-- Log every worker (`tasks/efficiency/worker_reviews.jsonl` -> `WORKER_REVIEW_LOG.xlsx`) and apply lessons to the next brief. [check: worker_review] Bring ranked ideas from measurements unprompted. RAM <90% or CPU <70% used = start useful work. Report compute waste. Decide what you can; never argue rulings. Titles keep `sv-`/`neo-` prefixes.
+- Log every worker (`tasks/efficiency/worker_reviews.jsonl` -> `WORKER_REVIEW_LOG.xlsx`) and apply lessons to the next brief. [check: worker_review] Bring ranked ideas from measurements unprompted. RAM <90% or CPU <70% used = start useful work. Report compute waste. Decide what you can; never argue rulings.
```

## 2026-11-13T23:58:06+05:30 | kakazuya (Eagle) | 575a5119 No-ticket: ruling update, agy runs only gemini-4-hydrogen-high, Flash 3.8 dropped (Shivam 13 Nov)
```diff
-- `agy`: coding `gemini-3.8-flash-medium`; answer tests (13 Nov): `gemini-4-hydrogen-high` answers, Opus 5.5 medium grades.
+- `agy` (13 Nov): only `gemini-4-hydrogen-high` (answers, question search); Flash 3.8 dropped. Opus 5.5 medium grades.
```

## 2026-11-14T00:18:03+05:30 | kakazuya (Eagle) | 02696234 No-ticket: board closes T-177/182/183/185/186/187/189/190 (merged, accepts pass); rulings: Go key 1 
```diff
-- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`, both keys) writes plumbing code any hour and grades read-only in peak; extraction judged by row precision goes to DeepSeek. Every branch: read-only grader, then Claude's tests + sample; merge with 0 right rows lost. Beam only while free [check: free_model_check]. No headless Opus unless Shivam says so. dsh workers use Go `account='1'` until key 2 resets (7 Nov). Beam may settle KPI/guidance rows scripts cannot (separate step; Opus code).
-- `agy` (13 Nov): only `gemini-4-hydrogen-high` (answers, question search); Flash 3.8 dropped. Opus 5.5 medium grades.
+- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`) writes plumbing code any hour and grades read-only in peak; extraction judged by row precision goes to DeepSeek. Every branch: read-only grader, then Claude's tests + sample; merge with 0 right rows lost. Beam only while free [check: free_model_check]. No headless Opus unless Shivam says so. Go key 1 only; key 2 retired (14 Nov). Beam may settle KPI/guidance rows scripts cannot (separate step; Opus code).
+- `agy` (13 Nov): only `gemini-4-hydrogen-high` (answers, question search, coding on trial); Flash dropped. Opus 5.5 medium grades.
```

## 2026-11-14T02:28:45+05:30 | kakazuya (Wolf) | 51aec310 T-211: T-207 accepted by Shivam as a continuous process; ruling amended (re-run every month-end), T-
```diff
-- Ultimate goal (8 Nov): predict any stock 6m/1y/2y ahead from reliably held data, least information that does it; few heavyweight factors; more data is not the goal. Factor rewards aren't fixed laws (10 Nov): recompute at every point in time per stock, sector and regime; report the statistical mode of rewarded factors and shifts.
+- Ultimate goal (8 Nov): predict any stock 6m/1y/2y ahead from reliably held data, least information that does it; few heavyweight factors; more data is not the goal. Factor rewards aren't fixed laws (10 Nov): re-run every month-end, ongoing (14 Nov), per stock, sector and regime; report the statistical mode of rewarded factors and shifts.
```

## 2026-11-14T15:52:06+05:30 | kakazuya (Wolf) | 059f7546 T-210: agy default model gemini-4-argon-high (Shivam 14 Nov: Argon first, Hydrogen after, high only)
```diff
-- `agy` (13 Nov): only `gemini-4-hydrogen-high` (answers, question search, coding on trial); Flash dropped. Opus 5.5 medium grades.
+- `agy` (14 Nov): `gemini-4-argon-high` until its weekly limit is used, then `gemini-4-hydrogen-high`; high only. Opus medium grades.
```

## 2026-11-15T19:39:48+05:30 | kakazuya (Wolf) | 7616ee32 T-214: ruling 15 Nov: weekday DeepSeek peak hours, coding goes to agy (Argon, then Hydrogen)
```diff
-- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`) writes plumbing code any hour and grades read-only in peak; extraction judged by row precision goes to DeepSeek. Every branch: read-only grader, then Claude's tests + sample; merge with 0 right rows lost. Beam only while free [check: free_model_check]. No headless Opus unless Shivam says so. Go key 1 only; key 2 retired (14 Nov). Beam may settle KPI/guidance rows scripts cannot (separate step; Opus code).
-- `agy` (14 Nov): `gemini-4-argon-high` until its weekly limit is used, then `gemini-4-hydrogen-high`; high only. Opus medium grades.
+- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`) writes plumbing code any hour and grades read-only in peak; extraction judged by row precision goes to DeepSeek. Every branch: read-only grader, then Claude's tests + sample; merge with 0 right rows lost. Beam only while free [check: free_model_check]. No headless Opus unless Shivam says so. Go key 1 only (14 Nov). Beam may settle KPI/guidance rows scripts cannot (separate step; Opus code).
+- `agy` (14 Nov): `gemini-4-argon-high` until its weekly limit, then `gemini-4-hydrogen-high`; high only; in weekday DeepSeek peak hours coding goes to agy (15 Nov). Opus medium grades.
```

## 2026-11-16T00:46:24+05:30 | kakazuya (Wolf) | 62af1a81 T-214: agy keeps gemini-3.8-flash-medium, runs the model Shivam names (current_model.txt); rulings: 
```diff
-- `agy` (14 Nov): `gemini-4-argon-high` until its weekly limit, then `gemini-4-hydrogen-high`; high only; in weekday DeepSeek peak hours coding goes to agy (15 Nov). Opus medium grades.
+- `agy`: run the model Shivam names (Argon high, Hydrogen high, `gemini-3.8-flash-medium`; none dropped, 16 Nov); default Argon, then Hydrogen; weekday DeepSeek peak hours: coding goes to agy. Opus medium grades.
-- Lean: add nothing that does not stop a failure we have had. Max 4 code workers on the MSI (10 Nov) [check: code_worker_limit]; data jobs on idle machines. Branches merged or deleted within 24 h.
+- Stores (16 Nov): one company at a time; modular: small repair scripts per store part, no whole-store rebuild; defects+fixes in store-repair notes; Claude writes store code, DeepSeek/Flash boilerplate only. Lean: add nothing that does not stop a failure we have had. Max 4 code workers on the MSI (10 Nov) [check: code_worker_limit]; data jobs on idle machines. Branches merged or deleted within 24 h.
-- Every worker start names `permission`. [check: start gate] HP work is headless. [check: test_hp_headless] No session-length limit (9 Nov); done/pending notes in `tasks/STATE.md`.
+- Every worker start names `permission`. [check: start gate] No session-length limit (9 Nov); done/pending notes in `tasks/STATE.md`.
-- OCR on the HP only, headless, only for pages with no or a jumbled text layer (10 Nov) (TextRecognizer 300 DPI first, stronger reader for low-confidence numbers). Until 15 Nov, MSI RAM short: run on the HP (`machines/HP_LAPTOP.md`), bring results back, delete the HP copy (10 Nov). No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
+- HP laptop gone (16 Nov). OCR only for pages with no or a jumbled text layer; MSI route untested No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
```

## 2026-11-16T16:06:07+05:30 | kakazuya (Wolf) | aadb7198 T-219: ruling on local/Drive/GitHub-only tools, unified-items ticket; journal entry for the 16 Nov w
```diff
-- Raw files live only on Drive (7 Nov): jobs download, write the database, delete the copy; check size and hash on Drive before deleting a local copy; test fetches may stay local until `raw_to_drive`. Kept local: `D:\RealityEngine\raw\user_research`.
+- Raw files only on Drive (7 Nov): download, write the database, delete the copy after a Drive hash check; tests local till `raw_to_drive`. Kept local: `raw\user_research`. Tools/trackers (16 Nov): local, Drive or GitHub only; no cloud until deployed.
```

## 2026-11-16T19:36:32+05:30 | kakazuya (Wolf) | da501971 T-214: correct the store ruling: build all queue companies first, then randomised question trials (S
```diff
-- Stores (16 Nov): one company at a time; modular: small repair scripts per store part, no whole-store rebuild; defects+fixes in store-repair notes; Claude writes store code, DeepSeek/Flash boilerplate only. Lean: add nothing that does not stop a failure we have had. Max 4 code workers on the MSI (10 Nov) [check: code_worker_limit]; data jobs on idle machines. Branches merged or deleted within 24 h.
+- Stores (16 Nov): build ALL queue companies, then random question trials; general fixes, re-trial; >=90% = next companies. Per-part repairs, no whole-store rebuild; defects in store-repair notes; Claude codes stores, DeepSeek/Flash boilerplate. Lean: only what stops a past failure. Max 4 MSI code workers [check: code_worker_limit]; data jobs on idle machines. Branches merged or deleted within 24 h.
```

## 2026-11-17T07:48:03+05:30 | kakazuya (Wolf) | 3c279c26 T-219: ruling 17 Nov: OCR after the HP goes to Kilo Dots on the page image, Haiku where Dots fails
```diff
-- HP laptop gone (16 Nov). OCR only for pages with no or a jumbled text layer; MSI route untested No PostgreSQL for now. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
+- HP gone (17 Nov): OCR (bad text layer only) by Kilo Dots on the page image, Haiku where Dots fails. No PostgreSQL. Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
```

## 2026-11-17T08:48:23+05:30 | kakazuya (Wolf) | e1384706 T-219: store-repair notes scored (severity = companies hit, criticality = wrong/corrupt/missed, prio
```diff
-- Stores (16 Nov): build ALL queue companies, then random question trials; general fixes, re-trial; >=90% = next companies. Per-part repairs, no whole-store rebuild; defects in store-repair notes; Claude codes stores, DeepSeek/Flash boilerplate. Lean: only what stops a past failure. Max 4 MSI code workers [check: code_worker_limit]; data jobs on idle machines. Branches merged or deleted within 24 h.
+- Stores (16 Nov): build ALL queue firms, then random trials; general fixes, re-trial; >=90% = next companies. Per-part repairs (no rebuild); repair notes scored by companies hit x wrong/corrupt/missed, fix by priority (17 Nov); Claude codes stores. Lean: only what stops a past failure. Max 4 MSI code workers [check: code_worker_limit]; data jobs on idle machines. Branches merged or deleted in 24 h.
```

## 2026-11-17T15:25:57+05:30 | kakazuya (Eagle) | 9ec7e62b T-222 R-015: annual-report cash-flow reader (pilot3/ar_statements.py, part ar_statements) in all 91 
```diff
-- Documents (7 Nov): bulk is decks and call transcripts; annual reports by script, selected sections only (in full only for a company with no calls or decks); keep credit-rating and borrowing documents. Never trust the exchange's category or headline: read pages until the type is clear, keep/skip on our own type dictionary.
+- Documents (7 Nov, 17 Nov): a small company's data sits in its annual report, quarterly results, rating documents and ad hoc announcements (order wins, material gain/loss, audit, management change): read those first. Never trust the exchange's category or headline: type a document by its pages, on our own dictionary.
```

## 2026-11-18T01:26:27+05:30 | kakazuya (Eagle) | db203d45 T-223: state, repair notes R-015/R-016/R-019/R-020, worker reviews, agy Hydrogen routing ruling (17 
```diff
-- `agy`: run the model Shivam names (Argon high, Hydrogen high, `gemini-3.8-flash-medium`; none dropped, 16 Nov); default Argon, then Hydrogen; weekday DeepSeek peak hours: coding goes to agy. Opus medium grades.
+- `agy` (17 Nov, Hydrogen account neo47verma): coding and reasoning `gemini-4-hydrogen-high`; question search for companies `gemini-4-argon-medium`; Flash kept, none dropped. Coding (17 Nov): Hydrogen high first at any hour until 60% of its Gemini weekly limit is used (`mcp__agy-worker__quota`); after that, agy in DeepSeek peak hours, DeepSeek off-peak unless its OpenCode Go usage rose >10 points in 24 h (`D:/RealityEngine/ledger/go_usage.csv`), then agy. Opus medium grades.
```

## 2026-11-18T08:40:35+05:30 | kakazuya (Eagle) | 23607cb5 T-223 R-020: merge Wolf-agy-R020-6held (six held stores' fix) plus two side-by-side fixes from an Ea
```diff
++- Investor questions (8 Nov): peers later, a model compares stored rows; brokerage reports only for stated facts, never targets or ratings; regulator circulars (RBI, SEBI, IRDAI) need their own fetcher (T-117). Policy (10 Nov): other-language PIB/official text only when no English version exists; each policy maps to companies touched (for, against or neutral), with why and a figure where possible.
++- DeepSeek on `dsh` at max effort, off-peak only (peak Mon-Fri 06:30-09:30, 11:30-15:30 IST; read the clock yourself). Routing (10 Nov): Beam (`beam-free`) writes plumbing code any hour and grades read-only in peak; extraction judged by row precision goes to DeepSeek. Every branch: read-only grader, then Claude's tests + sample. Beam only while free [check: free_model_check]. No headless Opus unless Shivam asks. Go key 1 only (14 Nov). Beam may settle KPI/guidance rows scripts cannot (separate step).
++- `agy` (17 Nov): coding and reasoning `gemini-4-hydrogen-high`; question search for companies `gemini-4-argon-medium`; Flash kept, none dropped. Coding (17 Nov): Hydrogen high first at any hour until 60% of its Gemini weekly limit is used; after that, in DeepSeek peak hours agy Hydrogen or Claude Sonnet (18 Nov), DeepSeek off-peak unless its OpenCode Go usage rose >10 points in 24 h (`D:/RealityEngine/ledger/go_usage.csv`), then agy. Opus medium grades.
++- Claude reviews, workers build; Opus writes ~20-25% (design, tests, review, one working example). Briefs carry evidence (rows, file:line, a fast check), numbered steps, limits, pitfalls, budget and a stop rule; unknown method -> Opus prototypes first. Check a finished worker on Opus's own tests and sample, log, merge [check: worker_review] [check: merge_tests]. No pilot bank reasoning to workers. Page-reading subagents: batches of 8 pages, under 100k context, Haiku medium.
++- One task, one worker session (new worker at 1M context or a new task); Opus reviews each round. No live adviser calls to Claude. Tickets = in-scope work; rules here; ideas to `tasks/IDEA_BOX.md` (why, purpose, review trigger) (12 Nov).
++- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer: `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Releases gate on a hidden hold-out, rulings diff, tool budgets; ~60 rows/stratum hand-read. Score only on frozen sets (10 Nov): half of each new set's questions never drive fixes; an exam set (s20) gives the reported number. Merge only with zero right rows lost, zero wrong rows verified; structural rules, not per-company.
++- HP gone (17 Nov): OCR (bad text layer only) by Kilo Dots on the page image, Haiku where Dots fails. No PostgreSQL. Stores on C: SSD (18 Nov). Never touch `Downloads\Telegram Desktop` (his brother's) or his personal Downloads folders.
++- Replies always in proper Indian English, whatever language he writes in; never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. Ticket truth: `reports\ticket_board.xlsx` (+ `.html`), synced on every change (8 Nov). [check: task_board + post-commit hook] After every answer run: Excel + CSV in reports (`answer_run_report.py`, 8 Nov). Rules sheet: `reports\standing_rules.xlsx` (+ `.html`), rewritten with this file. No spend reports: work until he says stop.
```

## 2026-11-18T12:56:57+05:30 | kakazuya (Eagle) | 7e9b2a9b No-ticket: ruling 18 Nov: reviews on agy Opus medium first until its Claude limit is used
```diff
-- `agy` (17 Nov): coding and reasoning `gemini-4-hydrogen-high`; question search for companies `gemini-4-argon-medium`; Flash kept, none dropped. Coding (17 Nov): Hydrogen high first at any hour until 60% of its Gemini weekly limit is used; after that, in DeepSeek peak hours agy Hydrogen or Claude Sonnet (18 Nov), DeepSeek off-peak unless its OpenCode Go usage rose >10 points in 24 h (`D:/RealityEngine/ledger/go_usage.csv`), then agy. Opus medium grades.
+- `agy` (17 Nov): coding and reasoning `gemini-4-hydrogen-high`; question search for companies `gemini-4-argon-medium`; Flash kept, none dropped. Coding (17 Nov): Hydrogen high first at any hour until 60% of its Gemini weekly limit is used; after that, in DeepSeek peak hours agy Hydrogen or Claude Sonnet (18 Nov), DeepSeek off-peak unless its OpenCode Go usage rose >10 points in 24 h (`D:/RealityEngine/ledger/go_usage.csv`), then agy. Reviews: agy Opus medium till its limits run out (18 Nov).
-- Replies always in proper Indian English, whatever language he writes in; never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. Ticket truth: `reports\ticket_board.xlsx` (+ `.html`), synced on every change (8 Nov). [check: task_board + post-commit hook] After every answer run: Excel + CSV in reports (`answer_run_report.py`, 8 Nov). Rules sheet: `reports\standing_rules.xlsx` (+ `.html`), rewritten with this file. No spend reports: work until he says stop.
+- Replies always in proper Indian English, never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. Ticket truth: `reports\ticket_board.xlsx` (+ `.html`), synced on every change (8 Nov). [check: task_board + post-commit hook] After every answer run: Excel + CSV in reports (`answer_run_report.py`, 8 Nov). Rules sheet `reports\standing_rules.xlsx` (+ `.html`). No spend reports: work until he says stop.
```

## 2026-11-18T21:04:44+05:30 | kakazuya (Eagle) | 0e8a626a T-225 session close: blend ticket, NAVKAR parent-transcript ruling, raw folder docs, journal
```diff
-- Verbatim first (8 Nov): store what management, officials and regulators said verbatim with source, date, speaker; the model judges at query time; XBRL stays as filed. At scale, judgment and 2nd/3rd-order links come from our own compute, not Opus. Pilot companies may hold pre-FY24 documents.
-- Documents (7 Nov, 17 Nov): a small company's data sits in its annual report, quarterly results, rating documents and ad hoc announcements (order wins, material gain/loss, audit, management change): read those first. Never trust the exchange's category or headline: type a document by its pages, on our own dictionary.
+- Verbatim first (8 Nov): store what management, officials and regulators said verbatim with source, date, speaker; the model judges at query time; XBRL stays as filed. At scale, judgment and 2nd/3rd-order links come from our own compute, not Opus. Pilots may hold pre-FY24 docs.
+- Documents (7 Nov, 17 Nov): a small company's data sits in its annual report, quarterly results, rating documents and ad hoc announcements (order wins, material gain/loss, audit, management change): read those first. Type a document by its pages on our own dictionary, never the exchange's category. Parent calls (18 Nov): a subsidiary's store keeps its parent's call transcripts, labelled.
-- Every worker start names `permission`. [check: start gate] No session-length limit (9 Nov); done/pending notes in `tasks/STATE.md`.
-- Live watch on every running job (finish, stall, errors); check real progress before reporting; review a finished worker at once. [check: T-050 stop hook]
+- Every worker start names `permission`. [check: start gate] No session limit (9 Nov); done/pending in `tasks/STATE.md`.
+- Watch every running job (finish, stall, errors); check real progress before reporting; review a finished worker at once. [check: T-050 stop hook]
-- Journal (13 Nov): add a tasks/JOURNAL.md entry (work, what worked, what failed and why, fixes) at 400k context and at wrap-up; read the latest at start.
+- Journal (13 Nov): add a tasks/JOURNAL.md entry (work, worked, failed and why, fixes) at 400k context and at wrap-up; read the latest at start.
-- Replies always in proper Indian English, never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, never internal codes. State failures plainly with sample sizes. Ticket truth: `reports\ticket_board.xlsx` (+ `.html`), synced on every change (8 Nov). [check: task_board + post-commit hook] After every answer run: Excel + CSV in reports (`answer_run_report.py`, 8 Nov). Rules sheet `reports\standing_rules.xlsx` (+ `.html`). No spend reports: work until he says stop.
+- Replies always in proper Indian English, never Roman Hinglish or Devanagari (10 Nov). Reports as HTML (or Mermaid) in `D:\RealityEngine\reports\YYYY-MM-DD_<topic>.<ext>`; lists in Excel/PDF/DOCX/RTF; explain with real questions, not codes. State failures plainly with sample sizes. Ticket truth: `reports\ticket_board.xlsx` (+ `.html`), synced on every change (8 Nov). [check: task_board + post-commit hook] After every answer run: Excel + CSV in reports (`answer_run_report.py`, 8 Nov). Rules sheet `reports\standing_rules.xlsx` (+ `.html`). No spend reports: work until he says stop.
```

## 2026-11-18T23:44:20+05:30 | kakazuya (Eagle) | ce4d2e7d T-224: ruling 18 Nov - agy under 40% weekly: dsh off-peak only, agy only in peak; 17 Nov Hydrogen-fi
```diff
-- `agy` (17 Nov): coding and reasoning `gemini-4-hydrogen-high`; question search for companies `gemini-4-argon-medium`; Flash kept, none dropped. Coding (17 Nov): Hydrogen high first at any hour until 60% of its Gemini weekly limit is used; after that, in DeepSeek peak hours agy Hydrogen or Claude Sonnet (18 Nov), DeepSeek off-peak unless its OpenCode Go usage rose >10 points in 24 h (`D:/RealityEngine/ledger/go_usage.csv`), then agy. Reviews: agy Opus medium till its limits run out (18 Nov).
+- `agy` (17 Nov): coding and reasoning `gemini-4-hydrogen-high`; question search for companies `gemini-4-argon-medium`; Flash kept, none dropped. Routing (18 Nov, agy weekly under 40% left): dsh (DeepSeek) workers off-peak only, agy only in DeepSeek peak hours (Hydrogen or Claude Sonnet); replaces the 17 Nov Hydrogen-first order. Reviews: agy Opus medium till its limits run out (18 Nov).
```

## 2026-11-24T15:10:47+05:30 | kakazuya (Wolf) | ed3c8097 Merge Wolf-transcript-statements-gate: call numbers unverified until a filing corroborates; statemen
```diff
++- Verbatim first (8 Nov): store what management, officials and regulators said verbatim with source, date, speaker; the model judges at query time; XBRL stays as filed. At scale, judgment and 2nd/3rd-order links come from our own compute, not Opus. Pilots may hold pre-FY24 docs. Calls (24 Nov): statements gate; call numbers unverified until a held filing matches within 1%.
```

## 2026-11-25T10:52:52+05:30 | kakazuya (Wolf) | 968822c5 Ruling 25 Nov: Hydrogen may run off-peak too; ops_gate drops the off-peak agy rule (T-242)
```diff
-- `agy` (17 Nov): coding and reasoning `gemini-4-hydrogen-high`; question search for companies `gemini-4-argon-medium`; Flash kept, none dropped. Routing (18 Nov, agy weekly under 40% left): dsh (DeepSeek) workers off-peak only, agy only in DeepSeek peak hours (Hydrogen or Claude Sonnet); replaces the 17 Nov Hydrogen-first order. Reviews: agy Opus medium till its limits run out (18 Nov).
+- `agy` (17 Nov): coding and reasoning `gemini-4-hydrogen-high`; question search for companies `gemini-4-argon-medium`; Flash kept, none dropped. Routing (18 Nov, agy weekly under 40% left): dsh (DeepSeek) workers off-peak only; agy (Hydrogen/Sonnet) in peak hours, and off-peak too: each job to whoever does it better (25 Nov). Reviews: agy Opus medium till its limits run out (18 Nov).
```

## 2026-11-26T13:03:04+05:30 | kakazuya (Wolf) | 842a026d T-242: ruling - reasoning ladder (Gemma errands -> DeepSeek/Hydrogen -> Hydrogen high -> Opus medium
```diff
-- `agy` (17 Nov): coding and reasoning `gemini-4-hydrogen-high`; question search for companies `gemini-4-argon-medium`; Flash kept, none dropped. Routing (18 Nov, agy weekly under 40% left): dsh (DeepSeek) workers off-peak only; agy (Hydrogen/Sonnet) in peak hours, and off-peak too: each job to whoever does it better (25 Nov). Reviews: agy Opus medium till its limits run out (18 Nov).
+- Reasoning ladder (26 Nov, replaces 17-25 Nov routing): errands -> gemini-worker Gemma 4 31B/26B if quick; harder -> DeepSeek off-peak, `agy` Hydrogen in peak; DeepSeek weak or failing rounds -> Hydrogen high; higher reasoning/review -> Opus medium itself; hardest only -> Neon 4 high/xhigh, sparingly. Company question search: `gemini-4-argon-medium`.
```

## 2026-11-26T13:09:40+05:30 | kakazuya (Wolf) | 4f9a626b T-242: agy allowlist - Neon 4 high/xhigh added, Argon dropped, Flash 3.8 medium for question search 
```diff
-- Reasoning ladder (26 Nov, replaces 17-25 Nov routing): errands -> gemini-worker Gemma 4 31B/26B if quick; harder -> DeepSeek off-peak, `agy` Hydrogen in peak; DeepSeek weak or failing rounds -> Hydrogen high; higher reasoning/review -> Opus medium itself; hardest only -> Neon 4 high/xhigh, sparingly. Company question search: `gemini-4-argon-medium`.
+- Reasoning ladder (26 Nov, replaces 17-25 Nov routing): errands -> gemini-worker Gemma 4 31B/26B if quick; harder -> DeepSeek off-peak, `agy` Hydrogen in peak; DeepSeek weak or failing rounds -> Hydrogen high; higher reasoning/review -> Opus medium itself; hardest only -> Neon 4 high/xhigh, sparingly. Company question search: `agy` gemini-3.8-flash-medium while it lasts (no Argon).
```

## 2026-11-26T15:11:20+05:30 | kakazuya (Wolf) | ff53a499 T-242: Shivam ruling - never block reading; load every read; >10% W+J graded sample loads unverified
```diff
-- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer: `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Releases gate on a hidden hold-out, rulings diff, tool budgets; ~60 rows/stratum hand-read. Score only on frozen sets (10 Nov): half of each new set's questions never drive fixes; an exam set (s20) gives the reported number. Merge only with zero right rows lost, zero wrong rows verified; structural rules, not per-company.
+- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer: `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Score only on frozen sets (10 Nov); s20 exam set gives the reported number. Structural rules, not per-company. Never block reading (26 Nov): all doc types read and load; a graded sample >10% W+J loads unverified; block only if >10% of the database is corrupt; Claude reviews and improves. [check: read_gate]
```

## 2026-11-26T15:43:33+05:30 | kakazuya (Wolf) | 8ca53659 T-242: read provenance in RULINGS.md and the row-contract skill
```diff
-- Verbatim first (8 Nov): store what management, officials and regulators said verbatim with source, date, speaker; the model judges at query time; XBRL stays as filed. At scale, judgment and 2nd/3rd-order links come from our own compute, not Opus. Pilots may hold pre-FY24 docs. Calls (24 Nov): statements gate; call numbers unverified until a held filing matches within 1%.
+- Verbatim first (8 Nov): store what management, officials and regulators said verbatim with source, date, speaker; the model judges at query time; XBRL stays as filed. At scale, judgment and 2nd/3rd-order links come from our own compute, not Opus. Calls (24 Nov): statements gate; call numbers unverified until a held filing matches within 1%.
-- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer: `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Score only on frozen sets (10 Nov); s20 exam set gives the reported number. Structural rules, not per-company. Never block reading (26 Nov): all doc types read and load; a graded sample >10% W+J loads unverified; block only if >10% of the database is corrupt; Claude reviews and improves. [check: read_gate]
+- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer: `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Score only on frozen sets (10 Nov); s20 exam set gives the reported number. Structural rules, not per-company. Never block reading (26 Nov): all doc types read and load; a graded sample >10% W+J loads unverified; block only if >10% of the database is corrupt; Claude reviews and improves. [check: read_gate] Rows store read_model/gateway/harness, prompt_fp, read_at (26 Nov).
```

## 2026-11-26T15:43:47+05:30 | kakazuya (Wolf) | b0a05b19 T-242: RULINGS.md under 8,000 characters
```diff
-- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer: `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Score only on frozen sets (10 Nov); s20 exam set gives the reported number. Structural rules, not per-company. Never block reading (26 Nov): all doc types read and load; a graded sample >10% W+J loads unverified; block only if >10% of the database is corrupt; Claude reviews and improves. [check: read_gate] Rows store read_model/gateway/harness, prompt_fp, read_at (26 Nov).
+- Architecture (8 Nov): the author never checks own code. Every extracted row passes the independent `row_checks.py` layer: `verified` / `unverified` (served labelled) / `quarantined` (never served); unsure = no row. Score only on frozen sets (10 Nov); s20 exam set gives the reported number. Structural rules, not per-company. Never block reading (26 Nov): all doc types read and load; a graded sample >10% W+J loads unverified; block only if >10% of the database is corrupt; Claude reviews and improves. [check: read_gate] Rows store read_model/gateway/harness, prompt_fp, read_at.
```

## 2026-11-26T16:01:52 | kakazuya (Wolf) | branch main
```diff
-New rulings via `ruling add`; `[check]` = enforced by code. Full wording `docs/rulings/RULINGS_full_2026-11-08.md`; `project_rules(topic)`.
+New rulings via `ruling add`; `[check]` = enforced by code. Full wording `docs/rulings/RULINGS_FULL.md`; `project_rules(topic)`.
```

## 2026-11-27T01:57:08 | kakazuya (Wolf) | branch main
```diff
-- Raw files only on Drive (7 Nov): download, write the database, delete the copy after a Drive hash check; tests local till `raw_to_drive`. Kept local: `raw\user_research`. Tools/trackers (16 Nov): local, Drive or GitHub only; no cloud until deployed.
+- Raw files only on Drive (7 Nov): download, write the database, delete the copy after a Drive hash check; tests local till `raw_to_drive`. `raw\user_research` goes to Drive too (27 Nov). Tools/trackers (16 Nov): local, Drive or GitHub only; no cloud until deployed.
```
