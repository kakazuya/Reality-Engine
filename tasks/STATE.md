# STATE: the one live state. Overwrite in place; keep it short. Last updated 2026-10-31 15:20 IST (HP analyst-test worker)

Old logs: `tasks/archive/`. If a doc disagrees with this file, check the repo or the stores, then fix the wrong one.

## Authority
- Order of work and the documentation rule: top of `AGENTS.md`. Trading and risk rules: `tasks/FRAMEWORK.md`.
- Work queue, with what runs next and what waits for Shivam: `tasks/handoff/QUEUE_2026-10-31.md`.
- Decision log: `D:\RealityEngine\plans\DECISION_LOG.md`, synced to Drive.
- v4 design: `tasks/arch_v4/QUERY_V4_DESIGN.md`. Review of how to reach 95%: `tasks/arch_v4/GATE95_REVIEW_2026-10-31.md`.

## Where the gate stands
Golden rule step 5, 60-name pilot, 2,681 rows. Gate is not passed; the 30% checkpoint is missed.

| Measure | Value | Source |
|---|---:|---|
| Contract strict | 361/2681 = 13.5% | gate on main, 31 Oct 13:00; before shareholding XBRL and near_high |
| Contract + shape checks | 246/2681 = 9.2% | same run |
| Rule grade, not reliable | 0.42% [0.17, 1.05] | `tasks/arch_v4/TRUTH_GRADE_2026-10-31.md` |
| **Read grade: the number to trust** | **0/127 answered rows RIGHT, 0.00% [0.00, 0.40] of the bank; 42/127 ill-posed** | `tasks/arch_v4/TRUTH_READ_GRADE_2026-10-31.md` |

The contract count measures answer shape, not truth. Largest cause: 66 of 127 answered rows return a nearby measure, not the one asked. Any earlier number (8.2%, 10.2%, 1.0%) is out of date.

## Stores, `reality_engine/data/pilot/v4/`
- `fact_v4_pilot.db`: core facts. `hold.pct` has promoter and public (57 of 60 names) plus FII, DII, MF and insurance (56); `hold.pledge_pct` has 57. No adjusted price atom, and no point-in-time corporate action atom.
- `fact_v4_pilot_oi.db`: `macro.oi`. `v4.db`: claims and own estimates. `shp_xbrl_pilot.db`: parsed shareholding XBRL, copied into the core store by `build_membership --shp-xbrl-only`.
- Blank `as_of` defaults to 2026-10-19, the last date all 60 names have a close (`run.py` `DEFAULT_AS_OF`). Shivam has not ruled on this yet.
- Raw shareholding XBRL: `D:\RealityEngine\raw\nse_shp_xbrl_pilot`.

## Findings that change what to do
- **Analyst agent test (free Beam + typed PIT tools): KILL.** 7/24 RIGHT (29.2%, Wilson 14.9–49.2) of rows not ILL_POSED and not CORRECT_NOT_IN_DATA; 7 PARTIAL, 10 WRONG, 11 ILL_POSED, 5 CORRECT_NOT_IN_DATA. All 40 answered (native tool calls) at 8.2 s and 19.7k input tokens per question; 0 PIT breaches. Main gaps: premise substitution (11), data gaps (10), no sort/aggregate/chart tools (6). `tasks/arch_v4/ANALYST_AGENT_TEST_2026-10-31.md`.
- Reader test: 13/40 RIGHT (32.5%), killed by its fixed rule; 13 more correctly said not stated, mostly missing documents, and 4 were WRONG. `tasks/arch_v4/READER_TEST_2026-10-31.md`.
- Rubric scoring is not usable (8 of 40 agreement). Premise audit: 219 of 2,098 instances provably false. `tasks/pilot60/PREMISE_AUDIT_2026-10-31.jsonl`.
- near_high operator: 4 right, 1 partial, 1 wrong of 6. `tasks/arch_v4/STUDY_OPERATOR_TEST_2026-10-31.md`.
- Scope: 945 of 1,073 parents name a stock outside the pilot, 450 names. `tasks/arch_v4/SCOPE_OPTIONS_2026-10-31.md`. Shivam has said no re-scope.
- OCR: Windows.Media.Ocr on the HP CPU, 186.7 pages/min, number recall 0.964. Running the 1,073 files is Shivam's call.

## Machines
- MSI: Claude, dsh workers (Go account 2), merges, source data. 2-3 workers, at least 2.5 GB free. Closing the owning session can kill its workers.
- HP: `python -m reality_engine.scripts.hp_worker start <brief> --dbs a,b --timeout N --test-cmd ...`, Go account 1, up to 5, at least 3 GB free. Hard stop is 1800 s unless `--timeout` is passed. **Since 31 Oct 13:30 the LAN address 192.168.1.42 times out: set `HP_RUN_HOST=zen7s@100.78.87.112`;** copying DBs does not fall back on its own.
- Merged worktrees are removed. Nothing is pushed without Shivam's OK.
