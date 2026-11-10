# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-10 11:20 IST (Wolf, session close)
History `docs/state_history/` (previous: `STATE_2026-11-10_1120.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 contract `docs/V2_SCHEMA_CONTRACT.md`.

## Now
- Stores (DELETE journal mode): `D:/RealityEngine/{u8/u8.db, q12/q12.db, p20/p20new.db}`, pilot set `pilot10/pilot10.db`, n10 being built (T-160). Go key 1 only.
- Pilot20 FINAL 9 Nov: 229/230 right (`reports/2026-11-09_p20_final_230.xlsx`).
- Routine (10 Nov rulings): no headless Opus unless Shivam says so; a separate read-only dsh worker grades every branch; max 2 code workers; no dsh starts 11:30-15:30 and 06:30-09:30 Mon-Fri; peak-hour work on Beam (`beam-free`).
- Merged 10 Nov: T-161/T-159 (first pages type/date docs), T-162 (SHP known_at from file stamp), T-132 r9 (cells; store `D:/RealityEngine/v2/p20_r9`), T-133 v8 (label map; live KPI +253 right / 0 lost), T-165 (holding every category, GoI/FPI/MF, KPI investor words).
- Waiting Shivam: T-116, T-118, T-121, T-122, T-125, T-126.

## Running (owner: this Wolf session until they finish)
- T-133 v8.1 20261110T052550Z-491c3466 (`tasks/handoff/T-133_v81_brief.md`): MUST merge before any KPI rebuild (~30 junk dividend_income/total_income cells).
- T-166 guidance source check 20261110T054026Z-90ecbbdb.
- T-132 r10 review (read-only) 20261110T054010Z-90366162 of branch dsh/20261110T041508Z-c1d00b5c (90 tests pass; store `D:/RealityEngine/v2/p20_r10`; samples `D:/RealityEngine/v2/review/samples`).

## Next action
1. Read each finished job (worker_result), review: v8.1 and T-166 each get a read-only dsh review (briefs like `tasks/handoff/T-165_review_brief.md`); merge r10 if its review passes (zero right rows lost).
2. Then rebuild p20/u8/q12 (docs_collect --profile, build --part stores/transcripts/guidance; KPI only after v8.1) so T-161 (15 retypes) and T-162 (88 SHP filings earlier) go live; restart reality-data MCP (also serves T-165). Re-ask SHP questions at past dates to close T-162.
3. Start queued T-164 (statements) and T-163 (segments) after 15:30 (briefs in `tasks/handoff/`).
4. Store defects to fix: CHOLAFIN nim_pct Q4FY26 0.68 wrong scale; credit_cost_bps Q1FY27 extra rows 180/470; p20 kpi_series 1,466 OFCF rows as capex (fixed on main, needs KPI rebuild).
5. Unmerged old branches to decide: dsh/20261106T143135Z-7b2b2cce (WIP guidance, lease expired), dsh/20261107T221506Z-daa1d0c7 (T-113 A row checks), Wolf-agy-20261109T034102Z-5e770d54, Wolf-agy-20261109T182713Z-4d398312 (T-160 harvest).
6. Bake-off Beam vs LongCat: task r2 scored 0/2 for both models: check the task or scorer (`D:/RealityEngine/night_loop/bakeoff_lc_beam`).
7. T-157 follow-up: Coal India 9, Havells 3, Titan 1 calls not found; run the fetcher on u8 and q12. T-139 next: India Ratings detail JSON. raw_to_drive sweep.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy (else workers fail "unable to open database file").

## Merge recipe
Review row first; merge --no-ff --no-commit; drop PROGRESS_NOTES.md (root only); tests per file; docs; commit `By:`; remove worktree.
