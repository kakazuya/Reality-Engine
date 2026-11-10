# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-10 12:35 IST (Eagle took over from Wolf)
History `docs/state_history/` (previous: `STATE_2026-11-10_1235.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 contract `docs/V2_SCHEMA_CONTRACT.md`.

## Now
- Stores (DELETE journal mode): `D:/RealityEngine/{u8/u8.db, q12/q12.db, p20/p20new.db}`, pilot set `pilot10/pilot10.db`, n10 being built (T-160). Go key 1 only.
- Pilot20 FINAL 9 Nov: 229/230 right (`reports/2026-11-09_p20_final_230.xlsx`).
- Routine (10 Nov rulings): no headless Opus unless Shivam says so; a separate read-only dsh worker grades every branch; max 4 code workers (10 Nov: MSI is dedicated to this work); no dsh starts 11:30-15:30 and 06:30-09:30 Mon-Fri; peak-hour work on Beam (`beam-free`).
- Merged 10 Nov: T-161/T-159 (first pages type/date docs), T-162 (SHP known_at from file stamp), T-132 r9 (cells; store `D:/RealityEngine/v2/p20_r9`), T-133 v8 (label map; live KPI +253 right / 0 lost), T-165 (holding every category, GoI/FPI/MF, KPI investor words), T-133 v8.1 (leaf-anchored live KPI labels, EBIDTA, net_revenue; Beam grader: 199/200, 0 stored right rows lost, ~470 junk cells removed; artifacts `D:/RealityEngine/v2/review/label_map_v81`).
- Waiting Shivam: T-116, T-118, T-121, T-122, T-125, T-126. Bake-off rescored (scorer fix): Beam 105/108, LongCat 98/108.

## Running (owner: Eagle)
- Beam code: T-163 r2 (worktree Eagle-T163-segments), T-164 r5 (Eagle-T164-statements, entity precision only). dsh-worker MCP now takes model='beam-free' (live after /mcp).
- DeepSeek: T-166 r4 20261110T100247Z-f72d7dc0 (base 8e9dbc8). Next free slot: T-163 r3 on DeepSeek (Beam r2 precision u8 67.5%, q12 45%).
- Shivam 10 Nov: after T-166, T-164, T-163 merge, Eagle writes a report for Fable 5.2 (measured / not measured / bottleneck / evals / fixes); due tonight. Older-filings fetch deferred until 95% answered.

## Next action
1. T-166: r4 on DeepSeek (brief above); merge only with 0 targets lost vs main, <=3 junk.
2. Rebuild p20/u8/q12 now possible (nothing reads p20new.db; guidance part waits for T-166 r2) (docs_collect --profile, build --part stores/transcripts/guidance, KPI now allowed: v8.1 merged) so T-161/T-162 go live; restart reality-data MCP (T-165). Re-ask SHP questions at past dates to close T-162.
3. T-132 r10 SENT BACK (review 44/60 strict, 0 lost; Bharti p34/p61 51,798 Year Ended Mar-26 stored as Q4, r9 had FY; junk parents; YoY column identity; bullet cell; Titan 871 unit). r11 to the same worker when a code slot is free, after 15:30.
4. After 15:30: T-164 (statements), T-163 (segments); briefs in `tasks/handoff/`. Max 2 code workers.
5. T-133 follow-ups (5/40 real labels still rejected, OCR EPS label, 4 revenue cells): `tasks/efficiency/worker_reviews.jsonl`.
6. Store defects (u8, Beam diagnosis checked by Eagle): CHOLAFIN kpi_series id 5544 nim_pct 0.68 is an impact ratio '(0.68% on Avg. Assets)'; 6042 credit_cost 180 is last year's 1.8%; 6050 470 is CSEL segment, stored as total. Root cause kpi.py sentence_rows: no guard for parenthetical impact ratio / prior-year comparison; entity attribution profile-gated, csel missing in page_entities.yaml. Fix in a code slot with tests. p20 1,466 OFCF-as-capex rows: fixed by v8.1, needs KPI rebuild.
7. Unmerged old branches to decide: dsh/20261106T143135Z-7b2b2cce, dsh/20261107T221506Z-daa1d0c7 (T-113 A), Wolf-agy-20261109T034102Z-5e770d54, Wolf-agy-20261109T182713Z-4d398312 (T-160).
8. T-157 follow-up: Coal India 9, Havells 3, Titan 1 calls not found; run fetcher on u8/q12. T-139; raw_to_drive.

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy (else workers fail "unable to open database file").

## Merge recipe
Review row first; merge --no-ff --no-commit; drop PROGRESS_NOTES.md (root only); tests per file; docs; commit `By:`; remove worktree.
