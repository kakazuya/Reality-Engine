# Task — v4 "latest quarter" misses filings that are held

## Goal
Held data is being lost. `python -m reality_engine.query.v4.run --mid MB0401#L` asks for POWERGRID's promoter pledge "in the latest quarter" as of 2026-10-07. It returns NOT IN DATA for `hold.pledge_pct`, with window 2026-07-08..2026-10-07. The store holds the 2026-06-30 row, known 2026-07-14. The latest known filing has a `period_end` just before the window, because "latest" was turned into the last 91 days of `period_end`. Quarterly data arrives weeks after its period ends, so this may hit many rows and atoms. Read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Work
1. Measure first: on the gate results, count the rows and atoms where a part returns NOT IN DATA with a window, but a row for that entity and atom with `known_at <= as_of` exists in an earlier period. Split by atom and by the phrase that caused the window. Report the count before any change.
2. Fix in `reality_engine/query/v4/` so that "latest", "latest quarter", "current" and a bare measure with no named period take the most recent period known by `as_of`. The answer states the period it used and when it was filed.
3. Set a staleness limit per atom class, stated in the answer, so a years-old row is not offered as "latest". Propose the limits from measured filing lags, and name them in one place.
4. An explicitly named period or window stays strict: "Q1FY27" with no row is still NOT IN DATA.
5. MB0401 also emits a nonsense `f.share_of` part over `fin.segment_value` and a duplicate pledge part. Fix them if the cause is small and shared with other rows; otherwise report the cause and count.
6. Re-run the gate on a copy of your code with `python tasks/pilot60/gate_run.py v4 --fresh`, one heavy process at a time, and report before and after per atom. Hand-grade 20 newly answered rows by a committed seed, reading each value back from the store separately.

## Limits
- Do not change the bank, any grader, or the stores.
- PIT: a row with `known_at` after `as_of` must never enter. Prove it with a test where a later filing exists.

## Acceptance checks
- Test: MB0401-shaped ask returns the 2026-06-30 row as of 2026-10-07, not the 2026-09-30 row known 2026-10-15.
- Test: a named period with no row stays typed NID.
- Test: a row past the staleness limit is not offered as latest.
- PIT breaches stay 0. No row that was answered before is lost, or each loss is listed with a reason.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_execute.py reality_engine/tests/test_v4_decompose.py reality_engine/tests/test_v4_run.py -q
```
