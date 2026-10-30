# PROGRESS_NOTES — v4 WP4 (executor, answer contract, renderer, grader)

Note: `DSH_WORKER_PROGRESS_NOTES` is not set in this session's shell, so this file
sits at the workspace root.

## 2026-10-31 — first pass

Done:
- `reality_engine/query/v4/execute.py`: one `execute(part, as_of, conn)` returning
  exactly one `Result` with `answer_type` measured | estimate | proxy | not_in_data;
  thin part adapter; fact-view reader (PIT `known_at <= as_of` in SQL); dims
  filtering plus `each`/`sum` readings; the closed 26-operator set; 13 formulas;
  own.estimate / claim / walk / 3 judgement rules; typed NID with what was tried;
  proxy only after the held stores fail (search -> proxy -> NID order); counters
  `real_answered` / `proxy_answered` / `not_answered`.
- `reality_engine/query/v4/render.py`: one block per part (value/unit/period/ISIN/
  source/known_at; estimate method+inputs; proxy+assumption+confidence+search_log+
  approval; four-gate NID wording) and `render_run` with the gate counters.
- `tasks/answer_bench/grade_v2.py`: v4 strict grader (every part, every contract
  field, unrelated result fails the case, NID never answered, approved proxy kept
  separate) + the 4199be2 anchor path (27/2,681, exits 3 and lists changed cases
  when it does not reproduce; never tunes the number).
- `reality_engine/tests/test_v4_execute.py`: 18 fixture tests, all passing.

Next:
- Wait for `grade_v2 --anchor` (running in the background; the DuckDB doc index
  makes the regrade the long part).
- Run code-intel diagnostics again on the final files, then write the report with
  the interface assumptions (WP3 part shape, WP2a fact columns, WP2b tables).

## 2026-10-31 — second pass (while the anchor runs)

- Tests: 19 passing (`python -m pytest reality_engine/tests/test_v4_execute.py -q`).
- `execute` now: JSON-safe `Result.to_dict`, `each` dims never silently pick one
  reading (returns the series), typed `_Missing` NIDs for store/dim gaps, price
  formulas guard a one-point series.
- `grade_v2`: a well-formed NID is reported as the reason a case is not covered;
  measured blocks must carry source/known_at (test added).
- Anchor job running since 03:19; it prints only after each result file completes.

## 2026-10-31 — anchor result (job finished)

- `grade_v2 --anchor`: originals 1,073 rows / 8 ANSWERED, instances 1,608 rows /
  19 ANSWERED, **27/2,681 = 1.0%, reproduced, 0 rows changed vs the anchor's own
  grades**, doc index = snapshot, exit 0.
- Final tests: 19 passed. Nothing blocked; report written.

