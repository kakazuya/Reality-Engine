# CONTINUE — this run was killed mid-task by a laptop restart (29 Oct, ~02:51 IST)

This worktree already holds YOUR partial work from that run (uncommitted). Before anything else:
1. Read `PROGRESS_NOTES.md` (root) and/or `.tmp/PROGRESS_NOTES.md`, then `git status` and `git diff`.
2. Keep what is correct; re-run only the steps that did not finish. Resume long jobs from their resume points
   (manifests, --resume flags, existing .tmp DBs) instead of starting over.
3. Then finish the original brief below and give its full report. RAM is tight on this laptop: run at most
   one heavy process (bench runner, fetch, build) at a time.

---

# Task — make ANSWERED mean answered: an entity + ask relevance gate, then the first real gate run

## Goal
Pilot-60 (`tasks/pilot60/REPORT.md`, `HAND_CHECK_60.json`/`.md`) graded 491 of 1,608 instances ANSWERED, but a hand check of 60 of them found only **3 actually right (5%)**. PARTIAL 2, WRONG 55. The query layer returns price moves, deck lines or another metric, every hop "succeeds", and the grader counts rows, not relevance.

The golden rule needs ≥95% answered. That number is meaningless until ANSWERED requires the answer to be about the right entity, the right metric/ask, and the right period, point-in-time.

## Do
1. **Read the 55 WRONG and 2 PARTIAL hand verdicts.** Classify the failure modes (wrong entity, wrong metric, wrong period, generic text, the ask unaddressed, …) with counts.
2. **Gate in the answer contract.** In `reality_engine/query/answer.py` and the planners, every hop result carries:
   - `entity_match`: the ISIN/sector/index of the rows equals the asked entity;
   - `ask_match`: the metric/concept or text evidence matches the ask's slots, via the decomposer's slots, an alias table and a deterministic lexical/concept check. No LLM in the loop;
   - `period_match`: the period/as_of is respected.

   A question is ANSWERED only if every required hop passes all three. Otherwise it is PARTIAL or BLOCKED, with the failing check named.
3. **Grader:** make `tasks/answer_bench/grade_v1.py` (strict) enforce the same checks independently. It must not trust the planner's flags; it recomputes them from the returned rows.
4. **Calibrate on the 60 hand-checked rows.** The gate must reject ≥50 of the 55 WRONG and keep the 3 OK. Report a confusion matrix. Then draw 40 new rows the new gate calls ANSWERED (seed 20261029, stratified by bucket and family), hand-check them yourself against the source rows, and report precision with a Wilson lower bound.
5. **First real gate run:** run the whole bank (1,073 originals + the pilot-60 instances in `tasks/pilot60/INSTANCES.jsonl`) with the env pointing at all the pilot stores:
   - `REALITY_PILOT_T1=D:\RealityEngine\pilot\pilot60`;
   - `REALITY_CHUNKS_V3=D:\RealityEngine\pilot\pilot60\chunks_v3_pilot.db`;
   - `REALITY_MACRO_PILOT_DB=D:\RealityEngine\pilot\macro_all.db`.

   Report answered % by bucket × sector × family, with latency (p50/p95/max) and PIT breaches. Then list the top 15 blockers, ranked by cases unblocked, each with its fix: a table, a planner wiring, or a fetch.

## Rules
- Live DBs and the D: pilot stores are read-only. Write only in this worktree. Use no paid models and no LLM in the query path, and make no commits.
- RAM: the bench runner peaks at about 1.8 GB. Run one bench process at a time, never parallel copies.

## Acceptance checks
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` passes, plus new tests for each check (a wrong-entity row, a wrong-metric row and a wrong-period row each fail).
- `tasks/answer_bench/GATE_RUN_2026-10-29.md` holds the confusion matrix, the 40-row precision, and the full-bank table and blockers.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the failure-mode counts;
- the confusion matrix on the 60;
- the 40-row precision with its lower bound;
- answered % overall and by bucket/family;
- latency;
- the top blockers;
- your tool-call count.
