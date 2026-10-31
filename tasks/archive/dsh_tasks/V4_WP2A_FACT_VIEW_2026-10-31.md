# Task — v4 WP2a: fact view and entity sets

## Goal
Build the part of WP2 (§H.2) that makes every held fact reachable: `reality_engine/query/v4/fact_view.sql` and `build_membership.py`. First read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`. A separate worker owns vocab, claim and `own_estimate`; a separate one owns the PIT sector labels. Do not build those.

## Design sections
§H.2, §B (schema and entity sets), the atoms in `tasks/arch_v4/concept_registry.json`.

## Acceptance checks
- The view returns one row per (entity, atom, period) for all 43 held atoms on the pilot; list any atom that cannot and why.
- `membership` covers 1,888 ISINs and 124 index sets with factual windows and `known_at`. Where the earlier state is unknown, `pit_known=0`; never backcast. Sector rows may stay empty until the §B.6 build arrives; say so.
- 30 hand-checked rows across atoms match their source table and `known_at`.
- Median lookup under 50 ms on the pilot, with timings printed.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_fact_view.py -q
```
Add that test file with small fixtures.
