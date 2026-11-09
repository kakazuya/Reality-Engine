# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-09 17:30 IST (Wolf)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`; v2 contract `docs/V2_SCHEMA_CONTRACT.md`.

## Now
- Stores (DELETE journal mode): `D:/RealityEngine/{u8/u8.db, q12/q12.db, p20/p20new.db}`; live pilot set `pilot10/pilot10.db`. Go key 1 only.
- v2 baseline pilot20: 126 right of 230 (`reports/2026-11-09_t143_p20_baseline.*`). q12: 72 right/70 partly/1 wrong/13 scope_out of 156 (`reports/2026-11-09_t124_q12.xlsx`).
- T-154 semantic: `pilot3_semantic` (MCP + `p3ask semantic`), index `p20/embed/` 14,376 pages (~$0.48). Re-ask 120 q (`reports/2026-11-09_t154_p20_semantic_reask.xlsx`): 58 of 90 partly/wrong now right, 28 of 30 right held; est. pilot20 ~182/230 (79%). Shivam: semantic stays, alongside the table store.
- T-131 OK (9 Nov 16:50). T-134 period engine merged (`reality_engine/v2/periods.py`; pilot10 report: 1,604 derived, 436 keys with mixed definitions -> T-133). T-155 merged (prices from 2019 in new builds). SHP re-ask 7/7 right.
- Waiting Shivam: T-116, T-118, T-121, T-122, T-125, T-126.

## Running (17:25)
- T-132 table store: dsh 20261109T115250Z-31023d3d, pilot20 decks+results -> `table_cell` in worktree `.tmp/v2p20`.
- T-139 rating rationales: dsh 20261109T115408Z-99df0bb0, text only, `.tmp/ratings_p20`.

## Next action
1. Review + merge T-132 and T-139 when they finish (Opus samples 100 cells per doc type for T-132).
2. DONE 17:45: u8/q12/p20 D: stores now hold prices, index and valuation from 2019 (prices+index rebuilt, `price_delivery_input` emptied, ratios rerun; every pre-existing valuation/ratio row identical). Profiles live in old Wolf scratch dirs (p20/u8: 82841833.../scratchpad, q12: bea35aad.../scratchpad).
3. T-133 label map (metric kind stock/flow column; fixes the 436 mixed keys), then T-135 calc catalog check, T-150 units at write (number_check missed INDHOTEL-016 10x revenue).
4. Checked: PERSISTENT Mar-26 MF 22.12% (34,887,586 sh) and FPI 22.12% (34,887,919 sh) are both as filed, a coincidence, not a parse bug.
5. Standard answer brief: carry the D2 brief lines (each quarter's deck; source known by as_of; no cross-company figures; TTM by ex-date; scale-check AUM).
6. raw_to_drive sweep for u8 + p20 raw + new SHP files.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy (else workers fail "unable to open database file").

## Merge recipe
Review row first; merge --no-ff --no-commit; drop PROGRESS_NOTES.md; tests per file; docs; commit `By:`; remove worktree.
