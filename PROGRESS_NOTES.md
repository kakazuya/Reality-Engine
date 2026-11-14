# T-205 progress

- 2026-11-13 r13 step 1: `agy_core.MODELS` allowlist (`gemini-3.8-flash-medium` coding default,
  `gemini-4-hydrogen-high` answer arm, `claude-opus-5-5-medium` grader); `start`/`resume` take `model` and refuse
  anything else; `runner.py` passes the job's model; MCP instructions/README updated. Tests in `test_agy_core.py`.
- 2026-11-13 r13 step 2: `reality_engine/answer/agy_call.py` — `run_agy(prompt, model, cwd, timeout, log_path)` using
  the agy-worker's `parse_events` (one parser), one retry on a transport error and never on a model answer, prompts
  over 24k chars moved to a file (Windows 32767-char argv cap) with a read-me pointer, `client_for` for answer_step /
  plan_model, `last_json`. `test_agy_call.py` on a fake agy (never the real one).
- 2026-11-13 r13 step 3: `answer_step --answer-model agy:<id>` and `pack_recall --plan-model agy:<id>` route through
  `agy_call`; round-12 prompts unchanged; each answer file records `model_tools` / `model_data_tool_calls` (arm P
  showed 0 store lookups). Script calc + citation check unchanged.
- 2026-11-13 r13 step 4: `reality_engine/answer/seeded_run.py` (arm S): one agy run per question, prompt = T-199
  rules rewritten for the pilot3_* MCP tools + question/as_of + the pack reading copy as starting evidence; writes
  `answers.jsonl` in the ds_a shape and `calls.jsonl` from the event log; resumable on qid.
- 2026-11-13 r13 step 5: `reality_engine/answer/blind_grade.py` (make/run/decode): N named sets labelled A..,
  seeded shuffle per question, key under `key_private/`, batches of 8, Opus 5.5 medium via agy with the GRADING_1
  rules in MCP spelling, strict per-line parsing with one re-ask, per-set totals + per-question table + pairwise
  agreement.
- 2026-11-13 r13 step 6: smoke on BS-001..003 under `.tmp/r13_smoke/` (agy runs unsandboxed in this worker): arm P
  3/3 answered, 8 figures, 0 data tool calls; arm S 3/3, 47 tool calls; one Opus batch graded 6/6 (both sets 3/3
  right, 3/3 agreement); decode wrote totals + pairwise.
- 2026-11-13 r13 step 7: DEVELOPER_GUIDE answer-path section, agy-worker README, STATE. Tests: 63 passed, 1 skipped;
  typecheck clean. Full 64-question runs are Claude's (commands in the guide).
# T-205 round 5 progress

- 2026-11-13: union gather (round-3 script net at full quota + plan lookups at their own quota), deterministic
  retries (no period, then terms words), cells-for-fin/fact, page-of-hit for search/statements, `price_rows`
  (previous close, adjusted close, first-to-last return, endpoints for a long range), holding share counts per
  quarter end, per-part all/some/none coverage with retries/derived, reading copy plan-first capped at 60k.
  22 tests pass. Both sets re-running from the plan cache after the price/reading fix.
- 2026-11-13 r10: answer_step.py built (one model call, AST-only calcs, figure/number check, one repair,
  unverified list, coverage not_found/abstained rule, 429 waits, resumable, per-question model/tokens/seconds).
  37 tests pass. Beam phase hit 429s and was stopped; DeepSeek (approved paid) ran Blue Star to 46 answers
  (39 ok, 7 unparseable = 15% > 10% stop), then stopped; Aurobindo not run. Beam answers kept apart.
