# Task — RIPPLE round 2: the sector table, non-company targets and trigger matching (35 blocked + many partial)

## Goal
After the EVENT/RIPPLE fix (merge `f7bdff3`; strict 174/2,681 = 6.5%), RIPPLE still has **35** first-blocker failures and **268** raw hop failures. The worker report found three causes:

1. The SSD pilot store `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot\pilot60\market_state_pilot.db` has an **empty `company_sector_pit`** and an empty `event_leakage_window`. The older HDD copy `D:\RealityEngine\pilot\market_state_pilot.db` has 449 pilot rows. Other benches read the SSD file with `immutable=1`, so do NOT modify it.
2. Claim targets of kind `state`, `commodity` and `theme` map to no held ISIN.
3. "No policy event matching the ask": Hinglish or paraphrased trigger wording.

## Do
1. Build a small sector store, `.tmp/sector_pit.db`, containing `company_sector_pit` (+ `event_leakage_window` if useful) for the full pilot universe (`tasks/pilot60/T2_ISINS.txt`). Source: either
   - read the HDD original once, sequentially, and copy the rows; or
   - rebuild with `reality_engine/pilot/build_t1.py --universe pilot`, writing into `.tmp`.

   Validate the rows: as-of semantics and `pit_conf`. In `reality_engine/query/ctx.py`, add an alias `sector_pit` (env `REALITY_SECTOR_PIT`, default `REALITY_DATA_ROOT/pilot/pilot60/sector_pit.db`, opened immutable). RIPPLE reads `company_sector_pit` from it first. The controller will copy the file to the SSD path.
2. Map the non-company targets:
   - `state` → companies with plants or revenue there (from the AR/deck facilities facts in `extract_pilot60.db` / `ar_facts`) where held, otherwise NOT IN DATA with a reason;
   - `commodity` → users/producers via `company_cost_structure` / the segment and industry maps;
   - `theme` → `company_membership_pit` (thematic indices) in `market_state_b.db`.
3. Trigger matching: normalise Hinglish/paraphrase in `reality_engine/query/planners/ripple.py`. Use a deterministic synonym list plus the issuer/date/topic score that already exists. Report the match rate on the RIPPLE cases before and after.
4. Tests for each, then re-run only the cases whose RIPPLE hop changes (keep the other rows unchanged), then `grade` + `report`. Report the before/after and the strict total. Hand-check 10 RIPPLE answers.

## File scope
Allowed: `planners/ripple.py`, `reality_engine/pilot/macro_claims.py`, the `sector_pit` alias in `ctx.py`, a new sector-store builder, and tests.

Do NOT touch:
- `facts.py`, `series.py`, `screen.py`, `evidence.py`, `metrics.py` (other workers own those);
- `gate.py`, `grade_v1.py`.

## Rules
- Read DBs from the SSD paths. The single exception is one sequential read of the HDD original, for the copy in step 1. Live DBs are read-only. Use no paid models and no LLM in the query path, and make no commits.

## Acceptance checks
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` and `python -m unittest reality_engine.tests.test_macro_claim_target` pass.
- RIPPLE first-blocker failures fall by ≥50%, with 0 PIT breaches and no new WRONG in hand-60.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the sector-store rows;
- the target-kind mapping counts;
- the trigger match rate;
- the before/after;
- the strict total;
- the hand-check results;
- your tool-call count.
