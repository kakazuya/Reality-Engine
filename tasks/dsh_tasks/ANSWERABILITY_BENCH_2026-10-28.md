# Task — answerability benchmark: how many master-bank questions can we answer today, and what blocks the rest

## Goal
Shivam (2026-10-28): before the schema and pilot, measure how many questions the data we already hold answers comfortably, through today's tools. The blockers become the schema requirements. This is a read-only benchmark: no chunking, no DB writes, no network.

## Do
1. **Sample 150 cases** from `tasks/master_bank/MASTER_BANK.jsonl`, with seed 20261028:
   - all 30 `regression: true`;
   - 30 from `source_bank` reddit200;
   - the other 90 stratified across family × entity_level, so every family that exists is covered at least 3 times and every entity level at least 5 times.

   Write `tasks/answer_bench/SAMPLE.jsonl`.
2. **Answer each case** with the `reality-data` MCP tools only:
   - `resolve`, `price`, `price_extreme`, `delivery`, `holding`, `facts`, `docs`, `doc_find`, `doc_page`, `search_docs` (FTS fallback is fine; **no paid embedding**), `universe`, `catalog`, and a bounded `sql`.
   - Respect `as_of` / `period` point-in-time: use nothing published after the question's as_of.
   - Budget at most 8 tool calls per case. If you hit it, grade PARTIAL or BLOCKED.
3. **Grade each case** as exactly one of:
   - `ANSWERED`: the full answer with provenance (db / table / doc id + date). Check it against the rubric `ground_truth` if present.
   - `PARTIAL`: some hops answered; name which hop failed.
   - `BLOCKED_SCHEMA`: the data exists in raw or held form but there is no table or field to query it. Name the missing table/field and map it to a gap id from `tasks/master_bank/GAP_ROLLUP.md` (G*, NG*, or a proposal name), or propose a new one.
   - `BLOCKED_TOOL`: the data is in a table, but the tool can't reach it or is too slow (over 20 s).
   - `NOT_IN_DATA`: we truly don't hold it. Say what source would.
   - `WRONG`: an answer was produced but it contradicts the ground truth, or PIT is violated.

   Record per case: the grade, the answer (≤60 words), the evidence ids, tools used, seconds, blocker, and gap id.
4. **Roll-up** in `tasks/answer_bench/REPORT.md`:
   - the overall answered %;
   - answered % by family, by entity level, by bank, and for the 30 regressions;
   - the blocker frequency table: gap id → cases blocked → closable from held data (yes/partial/no);
   - the top 15 schema additions ranked by cases unblocked;
   - the PIT violations found;
   - a slow-tool list (tool, args shape, seconds).

## Rules
- Read-only everywhere. Use `connect_ro` for any direct DB read. No network. No paid embeddings (`REALITY_DATA_ALLOW_PAID_EMBED` stays unset). No commits.
- Don't fake answers. If unsure, grade PARTIAL and say why.
- Don't stop to ask; if a tool errors, record it and move on.

## Acceptance checks
1. `tasks/answer_bench/RESULTS.jsonl` has 150 rows, each with exactly one grade from the list above.
2. The roll-up has the per-family, per-level and per-bank rates and the blocker table.

## Test command(s)
```bash
python -c "import json;r=[json.loads(l) for l in open('tasks/answer_bench/RESULTS.jsonl',encoding='utf-8')];G={'ANSWERED','PARTIAL','BLOCKED_SCHEMA','BLOCKED_TOOL','NOT_IN_DATA','WRONG'};assert len(r)==150 and all(x['grade'] in G for x in r);print('ok')"
```

## Report
Give:
- the overall %, and the % for the 30 regressions;
- the top 15 schema additions;
- the PIT violations;
- your tool-call count.
