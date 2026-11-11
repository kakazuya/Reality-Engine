# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-10 22:15 IST (Eagle, session close)
History `docs/state_history/` (previous: `STATE_2026-11-10_2215.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md`; Fable review brief `docs/FABLE_REVIEW_BRIEF.md` (live table section 7).

## Now
- Stores: `D:/RealityEngine/{p20/p20new.db, u8/u8.db, q12/q12.db, n10/n10.db, pilot10/pilot10.db}`; s10 list `D:/RealityEngine/s10/universe_s10.csv` (filings fetched 10 Nov).
- Routine: code to DeepSeek (precision) or Beam (plumbing, peak hours); a separate read-only grader on every branch; Claude reruns tests + samples; merge only with 0 earlier-right rows lost. Cap 4 code workers. DeepSeek on Go key 1 (key 2 hit its DeepSeek limit 10 Nov; Beam on key 2).
- Merged 10 Nov: T-133 v8.1, T-166 r4, T-171 steps 1-2, ticket-board rework (why/close_when, close --merged, advisory lint), T-164 r8 call statements (7f8497c4; independent review 0 losses, entity 96.9/86.3%, topic 92.6/96.2%; evidence D:/RealityEngine/v2/review/t164_r8), dsh-worker `model='beam-free'`, free_model_check, worker cap 4, pane order.

## Running (owner: Eagle session; claim_worker in the new session)
- T-179 DONE (first look): no effect of removing raw SQL (SQL 96/120 right, no SQL 94/120; same-arm runs disagree on 14-16 of 60). Grader lenient vs Opus (28 of 50 Opus-not-right called right). Median 34-56 s and 6-9 lookups per answer; tools take 1-2 s of that. Result in `tasks/FABLE_TESTS_2026-11-10.md`; data `D:/RealityEngine/t179/`.
- T-177: reference pages in `D:/RealityEngine/v2/reference_pages/` (3 free Kilo readers, 60 pages). `reference_vote.py` settles 2,063 of 4,143 candidate cells; 98.8% of values are printed on the page but 1,048 are label disputes (readers disagree on the row). Next: arbitrate rows by word positions, then hand-read the rest.
- Running (DeepSeek key 1, started 10:44 IST 11 Nov): T-177 completeness report 20261111T051419Z-0a0553b9; T-181 document-integrity gate 20261111T051441Z-8e5c9538.
- T-163 r7 (dsh/20261110T162525Z-3ef5482a, 71cbca9a) HELD with T-132 until T-180 decides: q12 one seed 85%, zero-loss gate failed, self-graded.

## Next action
1. Fable tests: the ordered pending list is the first section of `tasks/FABLE_TESTS_2026-11-10.md` (10 items; start with item 1, reconcile by value and column, then hand-settle disputes, then T-178 and T-180).
2. Then rebuild p20/u8/q12 (docs_collect --profile, build --part stores/transcripts/guidance/kpi/segments, one at a time) and restart reality-data MCP so T-161, T-162, T-164, T-165, T-166, v8.1 go live.
3. CHOLAFIN KPI branch dsh/20261110T104212Z-67ceeb28: run `.tmp/cholafin_kpi/build.py --tree main|branch --stores <one>` in its worktree for q12, p20, pilot10, n10 one at a time when <= 1 worker builds (RAM reaped it once), then grader, then merge.
4. s10: T-169 website crawler (Beam), build s10 stores, T-172 frozen split, then T-170 baseline with timed answers.
5. T-132 paused after r12 pending Fable's review (`docs/FABLE_REVIEW_BRIEF.md`).
6. Board: backfill why/close_when for the 76 open tickets from the 10 Nov triage (job 20261110T154548Z-13965dd0 output); move Wolf's DOING rows (T-113, T-120, T-130, T-132, T-133, T-134, T-139) to their real owner.
7. T-166 follow-ups: 3 wrong speakers, APLAPOLLO volume as revenue_growth, ADANIPORTS p52 11-16% missed, BHARTIARTL analyst capex row.
8. Raw folders `raw_market/masters` and `transcripts_raw` documented in `docs/RAW_DATA_FAMILIES.md` but not in a main doc (data_inventory reports 2 undocumented).

## Store copy recipe
checkpoint -> copy to D:/RealityEngine/<set>/ -> `PRAGMA journal_mode=DELETE` on the copy.

## Merge recipe
Grader row first; merge_worker; drop root PROGRESS_NOTES.md; tests per file; docs; remove worktree; log in worker_reviews.jsonl.
