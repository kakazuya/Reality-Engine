# Task — v4 price basis: stop returns running silently across splits and bonuses

## Goal
Lookup repair now answers 24 `f.cagr` rows from raw closes, and the answer does not say so. A bonus or split inside the window makes a raw return false: a 1:1 bonus reads as about -50%. Many questions ask for an adjusted CAGR, and the store has no adjusted price atom. Fix this honestly. Read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`; the code is `reality_engine/query/v4/execute.py` and `decompose.py`.

## Work
1. Measure: of the 60 pilot names, which have a split, bonus or similar action inside 2019 onward, and which of the 24 CAGR rows span one. Use the store's corporate action atom and `reality-data` as a cross-check; list each case, including any where a large close-to-close jump has no recorded action.
2. Every return that uses closes (`f.cagr`, change over a window) states its basis: "raw close".
3. If a corporate action falls inside the window, the answer must not present the raw figure as the return. Adjust only if the action's ratio and ex-date are held and known by `as_of`, and say "adjusted for <action> on <date>, ratio <r>". Otherwise return a typed NID that names the action. Never guess a ratio.
4. Where the question asks for adjusted and there is no action in the window, raw equals adjusted for splits and bonuses: say that. Dividends are not adjusted; say so where the question says total return.
5. Report before and after for those 24 rows, values recomputed independently of the code.

## Limits
- Do not change any grader, the bank, or the store. No new atom unless it is computed at query time from held rows.
- PIT: an action counts only from its own `known_at`.

## Acceptance checks
- Test: a window with a held 1:1 bonus gives the adjusted figure and names it.
- Test: a window with a jump and no held ratio gives a typed NID.
- Test: a clean window says raw close.
- Hand table for every CAGR row that spans an action.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_execute.py reality_engine/tests/test_v4_run.py -q
```
