# Task — v4 WP4: executor, answer contract, renderer, grader alignment

## Goal
Build `reality_engine/query/v4/execute.py`, `render.py` and `tasks/answer_bench/grade_v2.py` (§H.4). First read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Coordination
Parallel workers own `decompose.py` plus `parts.py`, and `fact_view.sql` plus membership. Do not edit those. Code against the part format in §H.3/§H.4 through a thin adapter in `execute.py`, and use small fixtures until they merge; the controller will integrate. State every assumption about their interfaces in your report.

## Binding decisions
- Answer types: measured, estimate, proxy, not_in_data (§D.4). Only measured, estimate and approved proxy count as answered; `real_answered` and `proxy_answered` are separate numbers.
- A proxy needs `search_log` and `approved_by`, or it is not answered. A typed NOT IN DATA is never answered.
- No part means no row: unrelated rows cannot appear.

## Acceptance checks
- One result per part for every mapped case, each with its `answer_type`.
- The renderer prints value, unit, period, ISIN, source and `known_at`; or the estimate's method and inputs; or proxy, assumption and confidence; or the NID wording with what was tried.
- `grade_v2` reproduces the 1.0% anchor on the old answers from commit `4199be2` (27/2,681; §H.4). If it does not reproduce, stop and report why rather than adjusting it.
- `grade_v2` is at least as strict as the hardened grader: multi-part asks need every part.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_execute.py -q
```
Add that test file with small fixtures.
