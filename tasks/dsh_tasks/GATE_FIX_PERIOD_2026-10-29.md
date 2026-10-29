# Task — gate blocker #2: wire the asked period into every planner (~1,000 cases fail period_match)

## Goal
The first honest gate run (`tasks/answer_bench/GATE_RUN_2026-10-29.md`, §4 top blockers) failed **941 cases on GATE period_match**:

| planner | cases |
|---|---:|
| SERIES | 345 |
| EVIDENCE | 257 |
| FACTS | 236 |
| SCREEN | 89 |
| COMPARE | 14 |

In each case the rows returned lie outside the asked period. Another 18 fail entity_match: SERIES returns GOLD rows instead of the asked entity.

The gate itself (`reality_engine/query/gate.py`) is correct; do not loosen it. The planners must fetch rows for the asked period/entity in the first place.

## Do
1. From `tasks/answer_bench/GATE_RESULTS_*_strict.jsonl`, take the period_match failures and group them by planner and by period form: named quarter/FY, month, "last quarter", YTD, as_of, a range, "since X", a named document's date. For each group, find the code path that drops or ignores the period.
2. Fix it in the planners (`reality_engine/query/planners/{series,evidence,facts,screen,compare}.py`) and in the period resolution of `reality_engine/query/router.py`. The router must resolve the period once into a window `(start, end, as_of)` that every planner honours, with point-in-time rules unchanged (known_at ≤ as_of).
3. Entity scope: SERIES must return only the asked ISIN or index. Fix the GOLD leak (MB0131/133/134).
4. Add tests for each fixed period form and for the entity leak.
5. Re-run the bank in 100-case chunks, one bench process at a time: `python tasks/pilot60/gate_run.py bank --resume --chunk 100`, then `grade`, then `report`. Report the before/after for each blocker and the new strict ANSWERED total.

## File scope (other workers are editing nearby; stay inside this)
Allowed: `planners/series.py`, `compare.py`, the period-filter code in `planners/facts.py`, `evidence.py` and `screen.py`, the period parsing in `router.py`, and new tests.

Do NOT edit:
- `gate.py` or its `ASK_CONCEPTS` (the ask worker owns those);
- the concept routing in the router;
- `reality_engine/pilot/*`.

## Rules
- Pilot stores: always use the SSD paths (`C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot\...`; `gate_run.py` already points there). Never read DBs from D:.
- Live DBs are read-only. Use no paid models and no LLM in the query path, and make no commits.

## Acceptance checks
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` passes.
- The period_match failures fall by ≥70%, with 0 PIT breaches and no new WRONG in the 60 hand rows (`gate_run.py hand60`).

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the period forms fixed, with counts;
- the before/after per planner;
- the new strict ANSWERED total;
- what's left;
- your tool-call count.
