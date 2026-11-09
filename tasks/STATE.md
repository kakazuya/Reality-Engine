# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-09 19:20 IST (Wolf)
History `docs/state_history/`; method `docs/PILOT3_BLUEPRINT.md`; v2 contract `docs/V2_SCHEMA_CONTRACT.md`.

## Now
- Stores (DELETE journal mode): `D:/RealityEngine/{u8/u8.db, q12/q12.db, p20/p20new.db}`, prices/valuation 2019 -> 9 Nov 2026; pilot set `pilot10/pilot10.db`. Go key 1 only.
- Pilot20, STRICT point in time (T-156): baseline 126 graded right but only 97 strict; now **211 right / 19 partly of 230** (`p20/answers/t154/current_strict_230.json`); counting verified 'not disclosed after a documented search' as right (contract s1 rule): **229 / 230** (`current_contract_230.json`). Call questions dated at transcript filing (`questions_P/Q.json` keep `as_of_original`).
- T-154 semantic stays (Shivam), alongside the table store; index `p20/embed/` (~$0.48 spent).
- Merged today: T-134 period engine, T-155 prices from 2019, T-139 rating rationales (41 texts, `D:/RealityEngine/outside_doc/ratings_p20`), T-132 round 1 (cells store `D:/RealityEngine/v2/p20_r1`, ~8/30 right), T-156 sql as_of guard, T-157 transcripts (p20 135 -> 151).
- Waiting Shivam: T-116, T-118, T-121, T-122, T-125, T-126.

## Running
- none

## Next action
1. Grade round 5; then one consolidated 230-answer report (`answer_run_report`).
2. T-157 follow-up: Coal India 9, Havells 3, Titan 1 calls not found (widen BSE subject filter); run the fetcher on u8 and q12.
3. T-132 round 2 merged 19:25: Opus unseen sample ~60% fully right (contract s10 lists remaining classes) -> round 3; then T-133 label map (stock/flow; 436 mixed keys), T-150 units at write.
4. T-139: load rationales into `outside_doc` + a read tool; India Ratings detail JSON.
5. Standard answer brief: carry the strict-PIT and 'not disclosed' rules from `<Wolf scratch>/T-156_round4_hp.md`.
6. raw_to_drive sweep (u8 + p20 raw, SHP, transcripts_raw, raw_market masters copied back today).

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy (else workers fail "unable to open database file").

## Merge recipe
Review row first; merge --no-ff --no-commit; drop PROGRESS_NOTES.md; tests per file; docs; commit `By:`; remove worktree.
