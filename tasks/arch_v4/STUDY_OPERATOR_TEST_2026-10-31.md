# v4 study operator cheap test — near-high count and forward return

Task: `tasks/archive/dsh_tasks/V4_STUDY_OPERATOR_TEST_2026-10-31.md` (moved after the job merged; idea 5 in
`tasks/arch_v4/GATE95_REVIEW_2026-10-31.md`). Run: MB1044 and MB1047, every instance,
hand-graded against an independent SQL recompute.

## What was built

One typed operator, `near_high`, reached through the ordinary decomposer path (§A.4), not
by mid:

- `reality_engine/query/v4/parts.py` — `near_high` in the closed `OPERATORS` tuple (27
  now); `tasks/arch_v4/concept_registry.json` — its registry row (declared shape,
  params, default atom `price.high`).
- `reality_engine/query/v4/decompose.py` — `_near_high_study()`: the phrase
  "within N% of [the then-current] 52-week high" becomes one `near_high` part over one
  window. `this year` -> YTD window, otherwise trailing 364 days. `how many` -> count;
  `share/proportion/fraction` -> share. `prior` -> exclude the as_of session. `what
  followed` -> forward 10 sessions, declared as a default in the answer. A comparative
  version ("versus/which/compare") stays on the ordinary path.
- `reality_engine/query/v4/execute.py` — `_execute_near_high()`: per session, the
  then-current 52-week high is the max of the basis series over the rows dated
  `d - 364d .. d` only (bisect over the date-sorted series); SQL cuts `known_at <= as_of`
  and never fetches a row after `as_of`; the count or share, every qualifying session,
  and forward returns whose endpoint must be on or before `as_of`. Forward windows that
  do not exist are counted separately and named, never dropped. `price.high` prefers the
  NSE row (BSE fallback). Raw basis is stated; a share-count change inside the trail is
  named; no 52-week trail returns a typed NID.
- `reality_engine/query/v4/render.py` — the answer block prints the count/share, window,
  threshold, basis, exchange, the full forward distribution (winners/losers/flat,
  mean/median/min/max, complete/incomplete) and every qualifying session with its close,
  then-current high, distance and forward return.
- Prior run's uncommitted work kept; fixes added: `forward_default` in dims, prior
  sessions are strictly before `as_of` (not "all but the last row"), NSE row preference
  for a two-exchange `price.high`, lookback-sized NID message, "52-week trail" wording,
  share-count formatting, `shape="scalar"`, the renderer block, and the last `tmp_path`
  test moved to the checkout `.tmp` (the worker sandbox denies directories created with
  mode 0o700, so the plain test command could not run).

## Results — 6 instances, hand-graded

The independent value comes from `.tmp/recompute_near_high.py`: SQL reads the pilot
`fact` table directly, then a naive per-session scan with its own arithmetic (no import
of the decomposer, executor, renderer or operator). All six operator values, counts,
sessions, basis and forward statistics matched it exactly (printed `ALL MATCH`).

| Instance | as_of / window | Operator answer | Independent SQL | Verdict |
|---|---|---|---|---|
| MB1044#L HINDALCO (`INE038A01020`) | 2026-09-24; 2026-01-01..2026-09-24, prior sessions | 22 of 179 sessions (12.2905%); high basis; 10 fwd sessions complete, winners 10 / losers 12, mean -0.566%, median -0.1472%, min -10.9072%, max 7.1382% | 22 / 179; same winners/losers/mean/periods | **RIGHT** |
| MB1044#MS APLAPOLLO (`INE702C01027`) | same | 14 of 179 (7.8212%); high basis; 13 complete + 1 incomplete (2026-09-18, named), winners 5 / losers 8, mean +1.1572%, median -1.4873%, min -4.9479%, max 11.2348% | 14 / 179; same, incomplete 2026-09-18 | **RIGHT** |
| MB1044#MI HEGAM (`INE545A01024`) | same | 31 of 179 (17.3184%); **close** basis (the store's `price.high` starts 2026-09-22); reverse split 2025-02-11 named; 31 complete, winners 13 / losers 18, mean -10.3073%, min -70.5371% | 31 / 179; same numbers | **WRONG** — the 2026-09-07 demerger is an unadjusted 63% price break the operator did not name; its forward returns (e.g. 2026-09-01 -> 2026-09-16, -70.5%) are demerger artifacts, not "what followed" |
| MB1047#L PIDILITIND (`INE318A01026`) | 2026-09-24; 2025-09-25..2026-09-24 | 0 of 246 sessions (0%); high basis; 1:1 bonus 2025-09-23 named as inside the trail | 0 / 246; same | **PARTIAL** — arithmetically right on the declared raw basis and the bonus is named, but a 0% share contradicts the question's "at a new high": the raw comparison across the 2x bonus is not an economic answer |
| MB1047#MS INDHOTEL (`INE053A01029`) | same | 4 of 246 (1.626%); high basis; sessions 2026-09-21 (4.1122%), 09-22 (4.674%), 09-23 (1.8088%), 09-24 (3.7761%); no action | 4 / 246; same periods | **RIGHT** |
| MB1047#MI RAJESHEXPO (`INE343B01030`) | same | 0 of 246 (0%); high basis; no action | 0 / 246; same | **RIGHT** |

Tally: **4 RIGHT, 1 PARTIAL, 1 WRONG** — 4/6 RIGHT (66.7%), so the kill rule (fewer than
half RIGHT) is not triggered. Per the brief, no further operators were built here. The
one WRONG is the operator's own requirement, not a new operator: an unrecorded corporate
action (demerger) is invisible because the only pilot signal is `price.shares_out`, which
does not move on a demerger. Evidence from the live store:
`equity_intelligence.corporate_actions` has `INE545A01024` / `HEGAM`, subject `Demerger`,
`ex_date` 2026-09-07 (`broadcast_date` is null, so it cannot enter a PIT answer as-is).

## Acceptance checks

- **Every instance has a verdict and an independently recomputed value.** Table above;
  `.tmp/recompute_near_high.py` prints all six and `ALL MATCH`.
- **A row after `as_of` cannot change the result; the high is then-current, not today's.**
  `test_near_high_never_sees_a_row_after_as_of` adds (a) a trail high published after
  `as_of`, (b) a row dated after `as_of`, (c) a later revision of the last session, and
  asserts the answer is byte-identical to the clean store.
  `test_near_high_is_then_current_not_todays_high_and_counts_losers` uses a last-day
  spike that would reject every early session if "today's high" were used; the operator
  keeps 8 of 10 sessions and its own trail highs.
- **Losers are counted.** Same test: the full forward window is 6 winners / 2 losers,
  both losers are listed with negative `forward_pct`, and the rendered block says
  "losers 2".
- **PIT breaches stay 0.** 0 breaches across the six answers (no `known_at`, session
  period or `forward_end` after 2026-09-24); the fetch applies
  `substr(known_at,1,10) <= as_of` in SQL.
- Test command: `python -m pytest reality_engine/tests/test_v4_execute.py
  reality_engine/tests/test_v4_decompose.py reality_engine/tests/test_v4_run.py -q`
  -> **66 passed** (1 environmental pytest-cache warning).

## Routing / regress count

`routing_before.json` (snapshot taken by the previous run before its edits) versus the
current decomposer over all 2,098 `tasks/pilot60/INSTANCES.jsonl` rows:

- 2,098 in, 2,098 out; **6 changed**, all and only the six MB1044/MB1047 instances
  (each went from a collapsed `value_at` spot part to one `near_high` part).
- **74 regression instances, 0 changed.**
- Status counts identical before and after: 1,785 mapped, 218 not_in_data, 95 unmapped.

## Files changed

- `reality_engine/query/v4/decompose.py` — the study route (one part, one window).
- `reality_engine/query/v4/execute.py` — the operator.
- `reality_engine/query/v4/parts.py` — `near_high` in `OPERATORS`.
- `reality_engine/query/v4/render.py` — the study answer block.
- `tasks/arch_v4/concept_registry.json` — the operator registry row.
- `reality_engine/tests/test_v4_execute.py` — 5 operator tests (then-current high,
  PIT cut, losers, incomplete forward, typed NID, named corporate action).
- `reality_engine/tests/test_v4_decompose.py` — 3 route tests (one part, share window,
  comparative ask not hijacked).
- `reality_engine/tests/test_v4_run.py` — the last `tmp_path` test uses `.tmp` like the
  module's other fixture (sandbox 0o700 denial).

No DB, JSONL or master-bank/instance/grader file was changed or generated.

## Open problems

1. **Corporate actions the store cannot see.** `price.shares_out` catches splits/bonuses
   but not demergers (HEGAM 2026-09-07). A PIT corporate-action atom (known from the
   filing/broadcast timestamp, never `ex_date`) is needed before this operator can
   promise "named, never silent".
2. **The pilot store carries non-trading rows.** `price.close`/`price.high` include
   2026-01-01 and 111 weekend rows across the 60 names. Each MB1044 count therefore
   includes one holiday session (2026-01-01); a trading-day filter would make HINDALCO
   21/178, APLAPOLLO 13/178, HEGAM 30/178. The operator counts store rows as sessions and
   says so only through the window, not as a caveat.
3. **Raw basis and adjustment.** The pilot store has no adjusted series. For PIDILITIND
   the 1:1 bonus is named but the 0% share is not usable as an economic statement; an
   adjusted or ratio-adjusted basis (with the ratio stated) is the honest next step.
4. **`price.high` coverage is uneven.** HEGAM has 19 intraday-high rows (from 2026-09-22),
   so the answer falls back to raw closes; the fallback and the earliest high date are
   stated in the assumption, but "within 2% of the 52-week high" is then a close-high
   proxy.

## Reproduce

```bash
python -m pytest reality_engine/tests/test_v4_execute.py \
  reality_engine/tests/test_v4_decompose.py reality_engine/tests/test_v4_run.py -q
python -m reality_engine.query.v4.run --mid 'MB1044#MI' --json   # and the other five
python .tmp/recompute_near_high.py                               # independent SQL check
```
