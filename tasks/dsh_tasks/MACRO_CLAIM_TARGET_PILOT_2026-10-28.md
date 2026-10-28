# Task — macro_claim_target pilot: map policy/budget/RBI/PIB claims to the sectors/industries/companies they hit

## Goal
`macro_claim_target` (G10 / policy_target) blocks about 58 master-bank ripple cases: policy → sector → company. The DDL is in `tasks/arch_v3/SCHEMA_V3.sql`, and the RIPPLE planner contract is in `tasks/arch_v3/QUERY_LAYER.md`. Held sources:
- `policy_events` (21,552 rows; 20,970 quote_ok);
- PIB and budget documents;
- RBI policy;
- `macro_events` + `ripple_effects`.

## Do
1. **Deterministic extraction:** map each policy claim to its targets (sector, basic industry, theme, or ISIN) using keyword → sector maps, a tariff/HS-code → industry map, and named companies. Fields:
   - a paraphrase of ≤ 30 words;
   - direction (+/−/mixed);
   - magnitude if stated (%, ₹ cr);
   - effective date;
   - conditions/exceptions;
   - known_at (the publication time);
   - source doc id.
2. **Pilot on 300 claims:** stratify across Budgets 2024–26, RBI MPC, PIB ministries and tariff notices. Build into `.tmp/pilot/macro_pilot.db`.
3. **Hand-check 60 claim→target mappings** and report precision/recall. The target precision is ≥ 0.90.
4. Run the RIPPLE planner of `reality_engine/query/` on the ripple200 master-bank cases with policy roots, using the pilot table. Report before/after answerability.

## Rules
- Read-only on live DBs. Write only in this worktree. No network, no paid models, no commits.

## Acceptance checks
`tasks/macro_pilot/REPORT.md` with the precision table and the before/after on ripple cases. `python -m unittest reality_engine.tests.test_macro_claim_target` passes.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_macro_claim_target
```

## Report
Give:
- the claims by source;
- precision;
- the ripple cases unblocked;
- your tool-call count.
