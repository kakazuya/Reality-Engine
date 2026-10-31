# Task — v4 answers print false labels, and stale values pass as current

## Goal
The read grade's rows show answers that state something untrue about themselves. A reader takes these as facts. Read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`, then trace each one in `reality_engine/query/v4/` (`execute.py`, `render.py`).

Observed in `tasks/answer_bench/GATE_RESULTS_v4_strict.jsonl`:
1. **A change printed as a level.** `MB1033#L` prints `price.close: 359.1 INR` for GRASIM on 2026-09-24; the close is 3,166.50. `MB1070#MI` prints `price.close: -155.1721 INR`. `MB0435` prints `price.close: -954.65 INR`. `MB1073#MI` prints `price.close: 53.96` where the close is 172.81, and `price.delivery_pct: 7.67 %` where delivery is 40.57%. These look like changes over a window printed under the level's label.
2. **Wrong source on a ratio.** `MB0064#L` and `MB0004#L` give a P/B with source `derived:facts_pilot.company_metric_series:borrowings_current+borrowings_noncurrent`, which is the source of a debt ratio. Any derived value must name the inputs it really used. `f.ratio` must also say which ratio it is.
3. **A stale value offered with no warning.** `MB0997#MS` answers capex as of 2026-10-19 with FY21 (period 2021-03-31). The answer must show its age plainly, or say the value is too old to use.
4. **Impossible values.** `MB0974#MI` prints `f.share_of: 4,357.91 %`. `MB0525` prints `—` as a value on a 4,357-row series. A value that cannot be stated is not `measured`.

## Work
1. For each class, find the cause and count the affected rows on the gate results before fixing.
2. Fix so that every result prints what it really is: operator, label, window and inputs. A change says it is a change, with its start and end values.
3. A value that fails a basic sanity check (a share over 100% where the parts are of a whole, or an empty value) becomes a typed failure, not `measured`.
4. Run the gate on your code and report which rows changed. The contract count may fall; that is correct and must be stated.

## Limits
- Do not change any grader, the bank or the stores. Never loosen a check.
- Do not change which rows are fetched, only how results are labelled and accepted.

## Acceptance checks
- A test for each of the four classes, using the rows above.
- 20 changed rows by a committed seed, read back against the store with separate SQL.
- PIT breaches stay 0.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_execute.py reality_engine/tests/test_v4_run.py -q
```
