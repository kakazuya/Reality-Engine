# CONTINUE: the earlier run was killed mid-task on 31 Oct at about 05:17 IST (supervisor and worker both gone, most likely when the session that owned it closed)

This worktree already holds YOUR partial work from that run, uncommitted. Before anything else:
1. Read `.tmp/PROGRESS_NOTES.md` (or root `PROGRESS_NOTES.md`) if present, then `git status` and `git diff --stat`.
2. Keep what is correct. Re-run only the steps that did not finish. Resume long jobs from existing outputs and `.tmp` DBs instead of starting over.
3. Check for leftovers of the killed run before starting anything long: stray python processes on the MSI, and any HP processes this task started (the HP is `zen7s@192.168.1.42`; another worker's job `hp-20261031T051124-3e6065` is running there, never touch it).
4. Finish the original brief below and give its full report. Do not commit: the reviewer commits this worktree after review.
5. RAM is tight on the MSI: at most one heavy process at a time. If `REALITY_DATA_ROOT` is unset, read data from `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data`, read-only.

---
# Task — v4 integration and the first real gate number

## Goal
Connect the merged v4 pieces end to end and run the whole bank, so we get the first real v4 gate number under the strict grader. First read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`. Target at this checkpoint: at least 30% strict. Report the true number whatever it is; never loosen a check.

## Pieces
- `reality_engine/query/v4/decompose.py`, `parts.py`; `execute.py`, `render.py`; `tasks/answer_bench/grade_v2.py`.
- Stores, read-only, in `reality_engine/data/pilot/v4/`: `fact_v4_pilot.db` (`fact`, `membership`), `v4.db` (`claim`, `own_estimate`, `own_estimate_band`, edge tables), `v4_vocab.db`.
- Bank: `tasks/master_bank/MASTER_BANK.jsonl`, the instances, and hand60, as in `tasks/pilot60/gate_run.py`.

## Work
1. `reality_engine/query/v4/run.py`: question → `decompose` → `execute` per part → `render`, with `as_of` PIT. Fix interface mismatches between pieces; list each. WP4 assumed `fact.atom_id`; WP2a built `fact.atom`.
2. Merge `claim.claim` and `own.estimate` access so the executor reads them. Apply the registry corrections WP2a found: `fin.ebitda`, `fin.order_book`, `fin.order_intake`, the units of `price.traded_value` and `price.mcap`, and macro `entity_key`.
3. Add v4 mode to `tasks/pilot60/gate_run.py` including `--regress` and `--blocker`; do not change the old engine's mode.
4. Run the 61 regression cases first (old answers vs v4): report kept and lost. Then the whole bank, 2,741 cases, chunked so a crash resumes.
5. Report: strict count and % overall and by bucket × sector × family; `real_answered` vs `proxy_answered`; top 15 failure classes with counts, each naming the owning piece (decomposer, store, executor, grader) and an example; latency p50, p95, max.
6. **Hand-check precision:** random 40 strict-ANSWERED rows, each judged against the question and sources, listed in `tasks/arch_v4/GATE_V4_SAMPLE40.md` with a one-line verdict. A high score with low precision is a failure; say so.

## Known limits, do not hide them
Decomposer blind recall 77.6%, precision 84.8%; 3 of 14 judgement rules built; 15:30 event rule not wired; passages read claims only; 29.9% of estimates mix YTD and quarterly XBRL; sector rows empty.

## Acceptance checks
- Whole bank graded by `grade_v2`; `tasks/arch_v4/GATE_V4_2026-10-31.md` written.
- No PIT violation in any answered row.
- Tests below pass.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_run.py reality_engine/tests/test_v4_execute.py reality_engine/tests/test_v4_decompose.py -q
```

