# T-205 round 13: Gemini Hydrogen answers, Opus medium grades; seeded tool run vs the pack path

Ticket: T-205
Base: branch `dsh/20261113T103928Z-0a9aa11d` (c264b5a3, round 12, not merged). You build on it.

Goal: Shivam's ruling 13 Nov: DeepSeek builds, `gemini-4-hydrogen-high` (through the `agy` CLI) answers, Claude Opus 5.5
at medium effort (`claude-opus-5-5-medium`, also through `agy`) grades blind. Order of the test: first the TOOL RUN
SEEDED WITH THE PACK (arm S), then compare it with the round-12 pack path answered by Hydrogen (arm P), all graded
together blind with the earlier sets. Gather rounds on top come in round 14, not now. You build and smoke-test the
harness; Claude launches the full runs.

Facts you need (checked by Claude 13 Nov):
- agy binary: `%LOCALAPPDATA%/agy/bin/agy.exe`, v1.5.8. `agy models` lists `gemini-4-hydrogen-high` and
  `claude-opus-5-5-medium`. Headless form: `agy -p <prompt> --model <id> --output-format stream-json
  --dangerously-skip-permissions` (see `plugins/agy-worker/server/agy_core.py` and `runner.py` for the exact flags
  already in use and the stream-json event parser `parse_events`; reuse it, do not write a second parser).
- agy's MCP config `C:/Users/warri/.gemini/config/mcp_config.json` already loads `reality-data` (the pilot3_* tools)
  and `agy-tools`. agy has NO shell. Whether `pilot3_*` sees `D:/RealityEngine/bluestar/bluestar.db` depends on the
  store registry (`python -m reality_engine.scripts.store_registry`, `REALITY_PILOT3_STORES`): check it, do not assume.
- Questions: `D:/RealityEngine/bluestar/answers/questions_in.json` (64; qid, question, as_of). Round-12 answers:
  `D:/RealityEngine/bluestar/answers_r12/answer_<qid>.json` (`final_answer`); find in them which pack dir they read
  (pack_r9 or pack_r11) and use that same pack. Old tool runs: `answers_ds_a/answers.jsonl`, `answers_ds_b/answers.jsonl`.
- Grading rules to keep word for word: `D:/RealityEngine/bluestar/report_r12/GRADING_1.md`; blinding script
  `report_r12/make_blind.py` (3 sets, X/Y/Z, seed, private key file). The old graders used `p3ask` in a shell; the
  Opus grader in agy has no shell, so its instructions name the equivalent `pilot3_*` MCP tools instead.
- Every spawned process hidden: `creationflags=CREATE_NO_WINDOW`, no `shell=True`, no DETACHED_PROCESS (MSI rule).

Steps:
1. `plugins/agy-worker/server/agy_core.py` + `agy_worker_mcp.py`: `start` and `resume` take `model`, allowlisted to
   {`gemini-3.8-flash-medium` (default, coding), `gemini-4-hydrogen-high`, `claude-opus-5-5-medium`}; anything else
   refused. `quota` unchanged. Tests in `plugins/agy-worker/tests/test_agy_core.py`. Update the docstring and the MCP
   instructions string (they say "pinned to flash-medium").
2. `reality_engine/answer/agy_call.py`: `run_agy(prompt, model, *, cwd, timeout, log_path) -> dict` (final text,
   tool calls by tool, tokens, seconds, error). One stable session per question is not needed (no Go key here).
   Retries: once on a transport error, never on a model answer. Unit-test with a fake agy binary (a small python
   script passed via an env var), never the real one in tests.
3. Arm P: `answer_step.py` and `plan_model.py` accept `--answer-model agy:gemini-4-hydrogen-high` (and
   `--plan-model` likewise if the plan step calls a model) and route through `agy_call`. The prompt text is
   unchanged from round 12. Record in each answer file whether the model called any tool (it should not; the pack is
   its evidence). Keep the script calc + citation check as is.
4. Arm S: `reality_engine/answer/seeded_run.py --set bluestar --packs <pack dir> --out <dir> [--questions ...]
   [--limit N]`: per question, one agy Hydrogen run whose prompt = the answer rules of
   `tasks/handoff/T-199_ANSWER_BRIEF.md` rewritten for MCP tools (pilot3_fact / fin / kpi / guidance / topic /
   statements / search / semantic / docs / sql, always with as_of) + the question + as_of + the pack's reading copy
   for that question as "evidence already gathered: start from it, check it, fill what is missing with tools".
   Output `answers.jsonl` in the ds_a format (qid, question, as_of, answer, tools, sources, confidence) plus
   `calls.jsonl` from the event log. Resumable (skip qids already written).
5. `reality_engine/answer/blind_grade.py`: generalise make_blind to N named sets (labels A..), seeded shuffle per
   question, private key outside the grader's view, batches of 8 questions per grader run, grader = agy
   `claude-opus-5-5-medium` with GRADING_1.md rules (tool names swapped to MCP), one JSON line per (qid, label) with
   grade right/partly/wrong + reason; a decoder that writes per-set totals, a per-question table and pairwise
   agreement. Grades parsed strictly; a batch whose reply does not parse is re-asked once, then reported.
6. Smoke only (you): arm S on BS-001..BS-003, arm P on the same 3, one grader batch on those 3 x 2 sets. Write them
   under your worktree `.tmp/r13_smoke/`. If agy cannot run inside your sandbox, say so in one line and stop at the
   tests: Claude runs the smoke unsandboxed.
7. Write `docs/DEVELOPER_GUIDE.md` (answer path section): the two arms, the commands Claude runs for the full run,
   the grader. One line in `PROGRESS_NOTES.md` per step.

Files: the ones named in steps 1-5 and their tests; `docs/DEVELOPER_GUIDE.md`; `plugins/agy-worker/README*` if one
exists. Read-only: everything under `D:/RealityEngine/`.
Test command(s): python -m pytest plugins/agy-worker/tests reality_engine/tests/test_answer_step.py reality_engine/tests/test_plan_model.py reality_engine/tests/test_agy_call.py reality_engine/tests/test_seeded_run.py reality_engine/tests/test_blind_grade.py -q
Accept: tests pass; typecheck clean on changed files; smoke files exist (or the one-line sandbox note); the commands
for the full 64-question runs printed in your final answer.
Evidence: round 12 lost 17 of 24 questions on evidence the pack never gathered (journal 13 Nov Wolf); the tool loop can
follow up, the fixed pack cannot. Shivam wants the seeded tool run measured first.
Pitfalls: do not change the round-12 prompts beyond the model route; never print or copy keys; never hand-sum
quarter tables; never open the grader key file from a grader prompt; no paid embedding calls.
Stop if: agy refuses the model ids; a smoke answer shows the model cannot see BLUESTARCO in pilot3 tools (report the
registry state, do not edit the live registry); more than 3 hours.
Budget: 3 hours, 400 tool calls.
