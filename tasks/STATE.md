# STATE: the one live state. Max 4,000 characters, overwrite in place. Last updated 2026-11-10 22:15 IST (Eagle, session close)
History `docs/state_history/` (previous: `STATE_2026-11-10_2215.md`); method `docs/PILOT3_BLUEPRINT.md`; v2 `docs/V2_SCHEMA_CONTRACT.md`; Fable review brief `docs/FABLE_REVIEW_BRIEF.md` (live table section 7).

## Now
- Stores: `D:/RealityEngine/{p20/p20new.db, u8/u8.db, q12/q12.db, n10/n10.db, pilot10/pilot10.db}`; s10 list `D:/RealityEngine/s10/universe_s10.csv` (filings fetched 10 Nov).
- Routine: code to DeepSeek (precision) or Beam (plumbing, peak hours); a separate read-only grader on every branch; Claude reruns tests + samples; merge only with 0 earlier-right rows lost. Cap 4 code workers. DeepSeek on Go key 1 (key 2 hit its DeepSeek limit 10 Nov; Beam on key 2).
- Merged 10 Nov: T-133 v8.1, T-166 r4, T-171 steps 1-2, ticket-board rework (why/close_when, close --merged, advisory lint), T-164 r8 call statements (7f8497c4; independent review 0 losses, entity 96.9/86.3%, topic 92.6/96.2%; evidence D:/RealityEngine/v2/review/t164_r8), dsh-worker `model='beam-free'`, free_model_check, worker cap 4, pane order.
- Rulings 10 Nov: frozen hold-out scoring (T-172, T-173); factor rewards dynamic (T-176); OCR only for textless/jumbled pages (T-175); PIB other languages only without English; policy-to-company impact (T-174).

## Running (owner: Eagle session; claim_worker in the new session)
- T-179: 240 answers done (`D:/RealityEngine/t179/<run>/`; median 34-56 s, 6-9 lookups per answer; B runs 0 served SQL). Grading: 5 read-only DeepSeek graders (key 1), 68 items each (240 test + 100 Opus-graded, shuffled): 20261110T205725Z-b9641902, 205726Z-bbcd45a6, 205727Z-e3a3608a, 205727Z-085ef518, 205728Z-f8bb81ba. Beam dies near 192k input tokens.
- T-177 r3 (DeepSeek, after two Beam rounds died at the same wall) 20261110T205743Z-f0e6dae5, base dsh/20261110T204856Z-6ab8a1e5 (r2 WIP); brief `tasks/handoff/T-177_r2_brief.md`.
- T-163 r7 (dsh/20261110T162525Z-3ef5482a, 71cbca9a) HELD with T-132 until T-180 decides: q12 one seed 85%, zero-loss gate failed, self-graded.

## Next action
1. Fable tests (`tasks/FABLE_TESTS_2026-11-10.md`; free models first, DeepSeek only as the answering model or after a free model fails): when the T-179 runs end, check each call log (arm B must show 0 served sql calls), calibrate a Beam grader on 100 Opus-graded answers, grade blind, report with `answer_run_report --call-log` (time and calls per answer). Review T-177, run the 60 pages, then T-178 (Eagle writes the script), then T-180.
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
