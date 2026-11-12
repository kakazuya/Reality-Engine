# Idea box

Rulings (Shivam, 12 Nov 2026): ideas still to be tested are not tickets. Tickets (`tasks/TASKS.md`) hold only in-scope
work (a fix, a removal, a test with an accept command); rules live in `tasks/RULINGS.md`; ideas live here. Backtest-ready
hypotheses live in `tasks/HYPOTHESIS_REGISTER.md`.

Each idea records WHY it exists, not just what it is: the context that caused it (the failure, measurement or
question, with evidence), its purpose (the decision or question it serves), when and by whom it was created, and a
**review trigger**: the stage of work at which it must be re-read, plus a review date. When a trigger is reached
(a stage begins, or the date passes), Claude re-reads the idea and proposes to Shivam: promote to a ticket now, keep
parked with a new trigger, or drop, with the reason. `reality_engine/scripts/load_context.py` lists ideas whose review
date has passed at every session start, so none sits forgotten.

Stages used for triggers (the order of work in AGENTS.md): `extraction-design` (atom design, readers, checker),
`unseen-company-test` (BLUESTARCO and later names), `pilot-95-pass` (the 95% bar and checklist passed),
`full-run` (chunking, re-embedding, universe build), `prediction` (6m-2y price prediction work), `maintenance`
(repo and tooling health, reviewed every two weeks).

Template:

```
## I-NNN: <title>
- Created: YYYY-MM-DD HH:MM IST, by <Shivam|Eagle|Wolf>, during <task/ticket/session>
- Context (what caused it): <the failure, measurement or question, with numbers and where it is recorded>
- Purpose (what it is for): <the decision, question or goal it serves>
- Idea: <what to build or test, in 1-3 sentences>
- Data: <held / needed>
- Review trigger: stage `<stage>`; review by YYYY-MM-DD
- Status: parked | next | promoted to T-NNN (date) | promoted to H-NN (date) | dropped: <reason> (date)
- History: <date: what changed>
```

---

## I-001: Own forward estimates vs what the price implies
- Created: 2026-11-08, by Shivam (as ticket T-119), moved here 2026-11-12 by the housekeeping pass
- Context (what caused it): P/E and P/S lag when the market pays a premium; the market prices 6 months to 2 years ahead,
  so a static multiple misses what the price expects.
- Purpose (what it is for): the ultimate goal, predicting a stock 6m/1y/2y ahead; tests whether the gap between our
  estimate and the price-implied growth predicts returns.
- Idea: our own 1-2 year revenue and earnings estimate per company from held facts (trend, guidance, order book,
  margins) against the growth the current price implies (reverse DCF at a sector discount rate); test whether the
  gap predicts 6m-2y returns, point in time.
- Data: held: financials, guidance, KPI rows, prices (valuation_daily). Needs: a discount-rate rule; I-002's result first.
- Review trigger: stage `prediction`; review by 2026-12-15
- Status: parked
- History: 2026-11-12 moved from ticket T-119.

## I-002: Recurring factor-reward engine
- Created: 2026-11-10, by Shivam (as ticket T-176, replacing T-118), moved here 2026-11-12 by the housekeeping pass
- Context (what caused it): T-118 (8 Nov) measured one pooled 2019-2026 cross-section; Shivam ruled 10 Nov that factor
  rewards are not fixed laws and must be recomputed per stock, sector and regime at every point in time.
- Purpose (what it is for): choose the few heavyweight factors for 6m-2y prediction and know when the rewarded set shifts.
- Idea: at every rebalance date, per stock/sector/regime, measure which held factors were rewarded over the next
  6m/12m/24m (point in time); report the statistical mode of rewarded factors and its shifts. Still unmeasured: ROE/ROCE,
  pledge, FPI/MF changes, guidance revisions.
- Data: held: prices 2019+, ratio_panel, shp_category, guidance, flows. Neighbours: H04, H14, H18, H19, H23 in
  `tasks/HYPOTHESIS_REGISTER.md`.
- Review trigger: stage `prediction`; review by 2026-12-15
- Status: parked
- History: 2026-11-12 moved from ticket T-176.

## I-003: Main-vs-branch store diff tool
- Created: 2026-11-12 22:00 IST, by Eagle, during the T-192 reviews
- Context (what caused it): T-192 needed three hand rebuilds of pilot10 to catch what the worker's report missed: a
  ratios crash, 6 then 4 group guidance targets hidden, 113 KPI period relabels.
- Purpose (what it is for): safe, fair rebuilds before the atom-design test; merge only with zero right rows lost.
- Idea: copy a store, build with main and with the branch from the same copy, keyed diff of every table, gate on loss.
- Data: store copies and build profiles (held).
- Review trigger: stage `extraction-design`; review by 2026-11-13
- Status: promoted to T-201 (2026-11-12)
- History: 2026-11-12 promoted by Shivam.

## I-004: Golden rows per store
- Created: 2026-11-12 22:00 IST, by Eagle, during the T-192 reviews
- Context (what caused it): right rows were lost silently in rebuilds; the checks live in reviewer memory and grader notes.
- Purpose (what it is for): a fixed regression set that every rebuild and merge must keep.
- Idea: 5-10 hand-verified rows per company kept as a CSV, asserted after every rebuild (T-201's `--golden`).
- Data: grader-verified rows (held in grade notes).
- Review trigger: stage `unseen-company-test` (after T-201 merges); review by 2026-11-20
- Status: parked

## I-005: Versioned store schema
- Created: 2026-11-12 22:00 IST, by Eagle, during the T-192 round-3 review
- Context (what caused it): `count_basis` added by one build part crashed `--part ratios` on pilot10 and would have broken
  `pilot3_holding` on all six live stores.
- Purpose (what it is for): add the atom table and future columns without breaking older stores.
- Idea: `schema_meta` version, numbered additive migrations, one migrate call per build, version checks on read.
- Data: schema.py (held).
- Review trigger: stage `extraction-design`; review by 2026-11-13
- Status: promoted to T-202 (2026-11-12)

## I-006: One typed reply contract for every tool
- Created: 2026-11-12 22:00 IST, by Eagle, after T-196
- Context (what caused it): 8 of 21 held answers were missed because tool replies looked complete (tag counts, cut lists).
- Purpose (what it is for): keep replies honest after T-197 as tools change.
- Idea: one schema for the coverage block, one test that runs every tool against it.
- Data: T-197's coverage block.
- Review trigger: stage `extraction-design` (after T-197 merges); review by 2026-11-16
- Status: parked

## I-007: Split the giant modules
- Created: 2026-11-12 22:00 IST, by Eagle
- Context (what caused it): kpi.py ~3,300 lines, lookups_pilot3.py and guidance.py 1,500-2,300; workers spend 26-41 calls
  before their first edit; typecheck times out on kpi.py, which carries pre-existing type errors.
- Purpose (what it is for): faster, cheaper, safer worker edits.
- Idea: split by job (period parsing, tables, sentences; one lookup module per tool), no behaviour change, existing tests.
- Data: code (held).
- Review trigger: stage `maintenance`; review by 2026-11-26
- Status: parked

## I-008: Test tiers
- Created: 2026-11-12 22:00 IST, by Eagle
- Context (what caused it): a one-process pilot3 pytest hit 7.9 GB (4 Nov); a test file hung 20+ minutes (12 Nov); sandbox
  `tmp_path` failures make workers add their own fixtures.
- Purpose (what it is for): every commit gets a quick check; the full suite runs nightly.
- Idea: mark slow tests, ~60 s smoke set per commit, full suite per file nightly; fix the sandbox tmp_path problem.
- Data: tests (held).
- Review trigger: stage `maintenance`; review by 2026-11-26
- Status: parked

## I-009: Route each symbol to its store
- Created: 2026-11-12 22:00 IST, by Eagle, during T-195
- Context (what caused it): answering Aurobindo through the MCP needed a committed `.mcp.json` edit that also switched
  Wolf's sessions and turned the default store off.
- Purpose (what it is for): test BLUESTARCO in its own store without config edits.
- Idea: a store registry; each call resolves its symbol to the store that holds it; an env var can still pin one store.
- Data: every store's `company` table (held).
- Review trigger: stage `unseen-company-test`; review by 2026-11-13
- Status: promoted to T-203 (2026-11-12)

## I-010: Machine-check worker claims
- Created: 2026-11-12 22:00 IST, by Eagle
- Context (what caused it): worker self-reports overstated ("0 group targets lost", "found=true" on partial answers).
- Purpose (what it is for): reviews start from verified numbers.
- Idea: every countable claim in a worker report (counts, tests passed, files) is re-run by script before review.
- Data: worker results, store copies.
- Review trigger: stage `maintenance`; review by 2026-11-26
- Status: parked

## I-011: Secret scan and lint before every commit
- Created: 2026-11-12 22:00 IST, by Eagle
- Context (what caused it): keys for DeepInfra, Go and Kite are in use on this machine; a leaked key is costly.
- Purpose (what it is for): stop a key or obvious defect reaching a commit or a push.
- Idea: a secret scanner and ruff in the pre-commit hook.
- Data: none.
- Review trigger: stage `maintenance`; review by 2026-11-26
- Status: parked

## I-012: Store backup retention
- Created: 2026-11-12 22:00 IST, by Eagle
- Context (what caused it): `*_before_*.db` backups pile up, 3-5 per store at ~150 MB each.
- Purpose (what it is for): disk stays clean; old backups stay recoverable on Drive.
- Idea: keep the last two locally, older ones to Drive via raw_to_drive; the data inventory flags excess.
- Data: raw_to_drive (held).
- Review trigger: stage `maintenance`; review by 2026-11-26
- Status: parked
