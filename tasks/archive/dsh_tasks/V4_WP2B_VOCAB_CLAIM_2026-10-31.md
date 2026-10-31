# Task — v4 WP2b: vocabulary, claims and own estimates

## Goal
Build the rest of WP2 (§H.2): `reality_engine/query/v4/build_vocab.py`, `build_claim.py`, `build_own_estimate.py`, `build_edge_schema.py`. First read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`. A separate worker owns `fact_view.sql` and `build_membership.py`.

## Design sections
§H.2, §A.8 (`own_estimate`, `own_estimate_band`), §A.9 and `tasks/arch_v4/VOCAB_PASS1.md`, §B.3 (`claim`), §E.1 (edge tables, schema only).

## Binding decisions
- Label gate: at least 95% of the head surfaces carry an exact label, hand-checked at 95% precision or better. The tail is stored as `other:<raw>`.
- The in-line band is per atom × mcap bucket, derived from the walk-forward error of the `trend` estimate. Never a constant.
- No LLM calls in this task. If labelling needs a model, stop at the deterministic pass and report how many surfaces remain; that goes to free Beam in a later job.

## Acceptance checks
- `vocab.surface` holds the measured 148,652 pilot surfaces, 100% mapped to a label or `other:<raw>`.
- `claim` holds at least 600k rows from `cc_items` with label ids and facets; 50 random claims spot-checked against their quote.
- `own_estimate` covers the pilot's held quarterly series for the beat/miss atoms, with `method`, `inputs_json` and `known_at`; replay check: an estimate at `as_of=t` reads nothing with `known_at > t`.
- Edge DDL runs clean.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_vocab_claim.py -q
```
Add that test file with small fixtures.
