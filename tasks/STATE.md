# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-09 19:20 IST (Wolf)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`; v2 contract `docs/V2_SCHEMA_CONTRACT.md`.

## Now
- Stores (DELETE journal mode): `D:/RealityEngine/{u8/u8.db, q12/q12.db, p20/p20new.db}`, prices/valuation 2019 -> 9 Nov 2026; pilot set `pilot10/pilot10.db`. Go key 1 only.
- Pilot20 FINAL 9 Nov (strict dates + Shivam's ruling: unpublished = 'data not found' + nearest supporting point): **229 / 230 right** (`reports/2026-11-09_p20_final_230.xlsx`); without the ruling 211. Only ADANIPORTS-005 left (figure only on a later transcript). Call questions dated at transcript filing (`questions_P/Q.json` keep `as_of_original`).
- T-154 semantic stays (Shivam), alongside the table store; index `p20/embed/` (~$0.48 spent).
- Merged today: T-134 period engine, T-155 prices from 2019, T-139 rating rationales (41 texts, `D:/RealityEngine/outside_doc/ratings_p20`), T-132 round 1 (cells store `D:/RealityEngine/v2/p20_r1`, ~8/30 right), T-156 sql as_of guard, T-157 transcripts (p20 135 -> 151).
- Waiting Shivam: T-116, T-118, T-121, T-122, T-125, T-126.

## Running
- T-132 round 5 dsh 20261109T160601Z-c6c3bb38; T-139 ratings loader + pilot3_ratings tool dsh 20261109T160635Z-eb95b8da.

## Next action
1. Carry into every answer brief: strict as_of on all tools incl. sql; search-before-'not found' with the searched list; nearest supporting point labelled (ruling 9 Nov, T-158 gate).
2. T-157 follow-up: Coal India 9, Havells 3, Titan 1 calls not found (widen BSE subject filter); run the fetcher on u8 and q12.
3. T-132 round 4 merged 22:00 (store `D:/RealityEngine/v2/p20_r4`, 74,486 cells): Opus unseen results ~25/30, deck ~27/30; leftovers in contract s10. T-133 v1 merged 21:25: 27 sector families (0 unknown of 40 pilot cos), `metric_def` stock/flow, review queue `D:/RealityEngine/v2/label_map` (98.3% rows mapped/queued) -> Opus approves per family. Then T-150 units at write.
4. T-139: load rationales into `outside_doc` + a read tool; India Ratings detail JSON.
5. Standard answer brief: carry the strict-PIT and 'not disclosed' rules from `<Wolf scratch>/T-156_round4_hp.md`.
6. raw_to_drive sweep (u8 + p20 raw, SHP, transcripts_raw, raw_market masters copied back today).

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy (else workers fail "unable to open database file").

## Merge recipe
Review row first; merge --no-ff --no-commit; drop PROGRESS_NOTES.md; tests per file; docs; commit `By:`; remove worktree.
