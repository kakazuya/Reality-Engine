# Task — v4 lookup repair: held data the executor loses

## Goal
A hand trace found 31% of failed pilot rows have the data but lose it in the view or executor. Fix that class. Read `tasks/arch_v4/GATE95_REVIEW_2026-10-31.md` section 1 traces and idea 2, and `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Work, in this order
1. **Blank `as_of`.** Blank means `known_at <= ''` removes every row (262 rows, 0 answered; MB0345). Default a blank `as_of` to one declared snapshot constant, the latest complete market date in the store, in one named place, and state it in the answer as an assumption. Shivam reviews this choice in the morning, so it must be a one-line change.
2. **Exchange and other dims.** Do not filter on a dim that the atom's rows do not carry, and do not read "(NSE: X)" as an exchange ask (MB0032#L). About 80 cases fail only on exchange and 13 only on `basis=adjusted`. An explicit "on BSE" ask that cannot be served must stay a typed NID.
3. **Cheap test, then stop and judge.** Re-run the rows affected by 1 and 2 and hand-grade 20 against stored rows. Under 8 right: finish the current item, report, and do not continue to item 4 onward.
4. **Named date on a non-session day.** Snap to the last session and say so in the answer.
5. **YTD and `max_with_date`.** `lag=ytd` is ignored, so MB0309#L returned 1,610.3 where the true YTD high is 1,620.7. A wrong number passed as answered. The old engine got this class right (MB0304, MB0028 in `tasks/pilot60/GATE_SAMPLE40_verdicts_20261029.json`).
6. **`f.cagr`** must use prices when the ask is about price (MB0102#MS, MB0109#L).
7. **Holdings for 21 of 60 names.** `hold.pct` is missing for Grasim, Pidilite, Hindalco and others; the rows carry the old ISIN (INE318A01018, INE047A01013). Trace the build, since the ISIN cause is only inferred. Join through ISIN history. Another worker is editing `fact_view.sql`: do not edit it. Put the fix in a new SQL file and builder step, tested on a `.tmp` copy, and give the reviewer the install step.

Compare with the `reality-data` functions (`holding`, `price_extreme`, `delivery`): reuse their logic where it honours `as_of`, and check that `known_at` comes from the filing record, not a crawl date.

## Limits
- Point-in-time holds: nothing before its filing-record date. Report PIT breaches, which must stay 0.
- A case that stays unanswerable must stay a typed NID. Never return a value to fill a gap.
- Do not change the grader, `INSTANCES.jsonl` or `MASTER_BANK.jsonl`. Another worker is adding a truth grade.
- No store sanity rule from the Vodafone Idea example: its +34,552 cr matches the filing.
- One heavy process at a time on this machine.

## Acceptance checks
- For each item: rows changed, before and after, and a hand-checked sample with values read back from the store.
- `python tasks/pilot60/gate_run.py v4 --fresh` re-run; report strict count and regressions, and say that contract count rising is not proof of truth.
- Tests pass, with one test per fix.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_run.py reality_engine/tests/test_v4_execute.py reality_engine/tests/test_v4_decompose.py -q
```
