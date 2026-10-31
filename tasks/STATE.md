# STATE: the one live state. Overwrite in place; keep it short. Last updated 2026-10-31 15:20 IST (Wolf)

Old logs: `tasks/archive/`. If a doc disagrees with this file, check the repo or the stores, then fix the wrong one.

## Authority
- Order of work and the documentation rule: top of `AGENTS.md`. Trading and risk rules: `tasks/FRAMEWORK.md`.
- Work queue, with what runs next and what waits for Shivam: `tasks/handoff/QUEUE_2026-10-31.md`.
- Decision log: `D:\RealityEngine\plans\DECISION_LOG.md`, synced to Drive.
- v4 design: `tasks/arch_v4/QUERY_V4_DESIGN.md`. Review of how to reach 95%: `tasks/arch_v4/GATE95_REVIEW_2026-10-31.md`.
- Docs: stale hand-offs, state snapshots and merged briefs moved to `tasks/archive/` on 31 Oct; the move list is `tasks/archive/README.md`. Old gate numbers (8.2%, 10.2%, 1.0%) are out of date.

## Where the gate stands
Golden rule step 5, 60-name pilot, 2,681 rows. Gate is not passed; the 30% checkpoint is missed.

| Measure | Value | Source |
|---|---:|---|
| Contract strict | 341/2681 = 12.7% | main gate regenerated 31 Oct 14:36; label-fix branch 327/2681 = 12.2% (`tasks/arch_v4/GATE_V4_LABELS_2026-10-31.md`) |
| Contract + shape checks | 246/2681 = 9.2% | same run |
| Rule grade, not reliable | 0.42% [0.17, 1.05] | `tasks/arch_v4/TRUTH_GRADE_2026-10-31.md` |
| **Read grade: the number to trust** | **0/127 answered rows RIGHT, 0.00% [0.00, 0.40] of the bank; 42/127 ill-posed** | `tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md` |

The contract count measures answer shape, not truth. Largest cause: 66 of 127 answered rows return a nearby measure, not the one asked. Any earlier number (8.2%, 10.2%, 1.0%) is out of date.

## Stores, `reality_engine/data/pilot/v4/`
- `fact_v4_pilot.db`: core facts. `hold.pct` has promoter and public (57 of 60 names) plus FII, DII, MF and insurance (56); `hold.pledge_pct` has 57. **The built store's `price.close` is still split/bonus-adjusted (`adj_close`, using later actions) while `price.open`, `price.high` and `price.low` are raw: POWERGRID 2023-09-11 stores 198.375, traded 264.50.** `fact_view.sql` now loads `company_state_daily.raw_close` and states `basis=raw`; `build_t1.py` now persists that column. Until the controller rebuilds T1 and the fact view (steps in `tasks/arch_v4/GATE_V4_LABELS_2026-10-31.md`; 103,313 `price.close` rows), every close level says it is adjusted, never raw. Returns are computed over the adjusted series at query time (`price_basis`). No point-in-time corporate action atom.
- `fact_v4_pilot_oi.db`: `macro.oi`. `v4.db`: claims and own estimates. `shp_xbrl_pilot.db`: parsed shareholding XBRL, copied into the core store by `build_membership --shp-xbrl-only`.
- Blank `as_of` defaults to 2026-10-19, the last date all 60 names have a close (`run.py` `DEFAULT_AS_OF`). Shivam has not ruled on this yet.
- Raw shareholding XBRL: `D:\RealityEngine\raw\nse_shp_xbrl_pilot`.

## Findings that change what to do
- Reader test: 13/40 RIGHT (32.5%), killed by its fixed rule; 13 more correctly said not stated, mostly missing documents, and 4 were WRONG. `tasks/arch_v4/READER_TEST_2026-10-31.md`.
- "Latest" now means the most recent period known by `as_of`, within limits in `execute.py` `LATEST_LIMIT_DAYS` (hold 200, fin 400, price 10, flows 100, macro and text 400 days). Named periods are strict, with no older fallback. Lifts pledge questions and removes years-old values given as latest; the run that introduced it fell 369 to 352.
- Answer labels (31 Oct): a difference prints as `<atom> change: value (from X on d1 to Y on d2)`, never as a level; `f.ratio` names its kind and only the inputs used (`derived:f.ratio(pb):price.mcap+fin.book_equity`); a share over 100%, a list over 50 distinct values, an empty value and a change across several entities are typed NIDs. Gate rerun: 937 changed rows, contract 341 to 327 (correct: 64 false/unstatable parts no longer count), PIT 0. `tasks/arch_v4/GATE_V4_LABELS_2026-10-31.md`.
- Returns over closes state their basis and name a held split or bonus (`execute.py` `price_basis`). An unexplained single-session fall of 30% or more is a typed NID. A close level names its basis; an old store's adjusted close is never called raw, and `near_high` uses one basis for the high and the close.
- Rubric scoring is not usable (8 of 40 agreement). Premise audit: 219 of 2,098 instances provably false. `tasks/pilot60/PREMISE_AUDIT_2026-10-31.jsonl`.
- near_high operator: 4 right, 1 partial, 1 wrong of 6. `tasks/arch_v4/STUDY_OPERATOR_TEST_2026-10-31.md`.
- Scope: 945 of 1,073 parents name a stock outside the pilot, 450 names. `tasks/arch_v4/SCOPE_OPTIONS_2026-10-31.md`. Shivam has said no re-scope.
- OCR: Windows.Media.Ocr on the HP CPU, 186.7 pages/min, number recall 0.964. Running the 1,073 files is Shivam's call.

## Never
Copy keys into files or print them. Send `Manual Dumps/` to the HP or any model, or put amounts in the repo or decision log. Loosen a grader to raise a score. Push without Shivam's OK. Spend DeepInfra or use paid models without his OK. Change the bank's instances, labels or scope without his ruling.

## Merge recipe (Claude)
Review by meaning; a report without `Docs updated:` is not merged. `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, keep ours on `query/v4/__init__.py`, run the tests, update this file and each affected doc, commit ending `By: Wolf` and the co-author line. Copy `.tmp` DBs first, then remove the worktree and branch. Log to the decision log and `rclone copy D:\RealityEngine\plans gdrive:InfoDiffusion_archive/plans`. HP: `hp_worker fetch-patch <job>` gives branch `dsh-hp/<job>`.

## Machines
- MSI: Claude, dsh workers (Go account 2), merges, source data. 2-3 workers, at least 2.5 GB free. Closing the owning session can kill its workers.
- HP: `python -m reality_engine.scripts.hp_worker start <brief> --dbs a,b --timeout N --test-cmd ...`, Go account 1, up to 5, at least 3 GB free. Hard stop is 1800 s unless `--timeout` is passed. **Since 31 Oct 13:30 the LAN address 192.168.1.42 times out: set `HP_RUN_HOST=zen7s@100.78.87.112`;** copying DBs does not fall back on its own.
- Merged worktrees are removed. Nothing is pushed without Shivam's OK.
