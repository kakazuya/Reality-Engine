# Task — fix the master bank's family and entity-level mapping (the coverage matrix is wrong)

## Goal
The reviewer (Claude) found three mapping defects in `tasks/master_bank/build_master_bank.py`, merged to main at `b2a43e6` in its worktree branch. Because of them, the coverage matrix and the "empty cells" finding cannot be trusted:
1. **Multi-family rows keep only the first family.** The variations bank stores families as strings such as `"2,11"`, `"6,7"`, `"1,5"`, `"1,9"`, `"1,3"`. That is why families 5, 7, 8 and 10 show zero cases, and family 11 (point in time) is undercounted.
2. **The open bank has no `entity_level`.** All 300 rows are `None` and were defaulted to `stock`. Derive the level from each row's `entities[].type` (stock / industry / index / policy / market-wide) and from the question scope: "all listed PSU banks" is sector, "Nifty Smallcap 250 members" is index, "mid-caps" is the market-cap bucket, "market fell on 4 June 2024" is market-wide, an RBI or Budget action is policy or macro.
3. **The ripple bank has no family** (200 rows `None`). Map the archetype to families:
   - R01 → 16, R02 → 18, R03 → 16, R04 → 16 and 19, R05 → 19, R06 → 3, R07 → 12, R08 → 16, R09 → 11, R10 → 9.
   - Also set the entity level from the entities and the question.

The variations bank's V7 (scope up to industry/sector) and V8 (theme/index/market-cap screen) rows must land at those levels, not at stock. Use the `variation` field, not only the text.

## Do
1. Change `family` to a **list** everywhere: in the schema, the coverage matrix (a row counts in every family it lists) and the md tables (list it under its primary family and cross-reference it).
2. Add a deterministic `derive_entity_level(row)`:
   - from the entities' type and the scope keywords;
   - for the variations bank, from the variation slot;
   - record `entity_level_source` (given / entities / variation / keywords) so it can be audited.
3. Rebuild. Print the before/after counts of family × level. Re-list the thin and empty cells and the top 10.
4. **Hand-check 30 rows** across the banks against their question text, and give the accuracy of the derived level.
5. Keep everything else unchanged: the dedupe, the gap roll-up, the regressions, the `--check`, and support for the Reddit file.

## Rules
- Work in this worktree. No network, no commits. Read-only databases.

## Acceptance checks
1. No row has a `None` family. Families 5, 7, 8 and 10 are non-zero if the sources contain them; if one is truly zero, show the evidence.
2. Open-bank and ripple rows have a derived level, with fewer than 10% falling back to stock. The 30-row hand check is at least 90% correct.
3. `--check` passes. MASTER_BANK.md and GAP_ROLLUP.md are regenerated.

## Test command(s)
```bash
python tasks/master_bank/build_master_bank.py --check
```

## Report
Give:
- the before/after family × level table;
- the 30-row hand-check result;
- the new top-10 thin or empty cells;
- your tool-call count.
