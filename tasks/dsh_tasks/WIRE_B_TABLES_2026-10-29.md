# Task — wire the newly built class-(b) tables into the query planners

## Goal
`tasks/pilot_b/REPORT.md`: four tables are built from held data in `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot\pilot60\market_state_b.db` (SSD, 3.3 GB, final-schema DDL):

| table | rows |
|---|---:|
| `commodity_price_daily` / `series_observation` (+ `series_meta`) | 7,062 |
| `company_membership_pit` | 10,895 |
| `fno_oi_daily` | 16.2 M |
| `mkt_nse_full_daily` | 4.29 M |

The design (`tasks/pilot_b/cases_pilot_b.jsonl`) now classes 65 more cases as answerable from them. But the planners in `reality_engine/query/` don't read the store yet, so those cases still fail the gate. Wire it in, then prove the cases answer.

## Do
1. `reality_engine/query/ctx.py`:
   - add the store as a T1 alias (`market_state_b`, env `REALITY_MARKET_STATE_B`, default = the SSD path above when present);
   - open every T1 pilot DB read-only with `immutable=True`, so a read-only sandbox can't fail on the WAL `-shm`.
2. Planners:
   - SERIES / COMPARE read commodity series (`series_observation` + `series_meta`) for commodity asks, and the F&O open interest / futures basis (`fno_oi_daily`) for OI, PCR and rollover asks;
   - SCREEN reads `company_membership_pit` for an index-as-of universe, and `mkt_nse_full_daily` for delivery or turnover screens when the live tables lack the window.

   Rows carry the asked entity, period and concept, so the existing gate can judge them.
3. Tests: one per table/planner route, plus a PIT test (`known_at` ≤ as_of).
4. Run the 65 moved cases (their case ids are in `tasks/pilot_b/reclass.json`). Use `tasks/pilot60/gate_run.py` or `tasks/answer_bench/run_v1.py` limited to those ids; one bench process at a time. Report strict ANSWERED before/after and hand-check 10 of them against the source rows.

## Rules
- All pilot stores are on the SSD path above; never read DBs from D:. Live DBs are read-only.
- Don't change `gate.py` checks. Use no paid models and no LLM in the query path, and make no commits.

## Acceptance checks
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` and `python -m unittest reality_engine.tests.test_pilot_b_tables` pass.
- On the 65 cases: strict ANSWERED rises, with 0 PIT breaches and hand precision ≥80% on the 10 checked.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the routes wired;
- the before/after on the 65 cases;
- the hand-check results;
- what's still missing;
- your tool-call count.
