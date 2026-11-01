# Task: patch the concall reader + 25-doc pilot (no full run yet)

Owner: Shivam (2026-10-24). Reviewer: Claude. Builds on `tasks/CONCALL_READER_READINESS_2026-10-24.md` (read it fully).

## Do

1. **Patch `reality_engine/scripts/concall_deepseek.py`** (in this worktree):
   - `--from-chunks`: read transcript text from `document_chunks` (ordered, overlap-aware join) when no PDF is on disk.
   - `--strict-date`: queue strictly newest → oldest by real call/filing date.
   - Fix the done-set bug: a missing PDF / unreadable text must be `skip_unreadable_text` (retryable), never a terminal
     done status; existing `skip_unreadable` rows caused by missing PDFs must be re-queued, not trusted.
   - **Undated transcripts (1,499):** Shivam: "in transcripts, dates are written on the first page itself". Add a
     date resolver: parse the call date from the first ~3,000 characters of the text (PDF page 1 or first chunks):
     patterns like "Q1 FY27 Earnings Conference Call ... August 11, 2026", "11th August 2026", "11-08-2026",
     "dated ...". Prefer the explicit call date; sanity-check against filing timestamps (call date ≤ filing date,
     within ~60 days) and record `date_source`. Report how many of the 1,499 get a confident date; include them in the
     newest→oldest queue.
   - Lanes: Go key 2 `beam-free`, Kilo key 1 and Kilo key 2 `reflection/beam-free` (Shivam has two Kilo keys) — three
     lanes, interleaved, each with its own 429 backoff; stable `x-opencode-session` per lane.
   - **LongCat:** Shivam's screenshot of https://opencode.ai/v2/docs/console/go (2026-10-24) still lists
     "LongCat 2.5 Preview Free — Free, Unlimited, limited time" and "Beam Free". Today's probe got 403 (Go 1) / 429
     "endpoint unavailable" (Go 2). Re-check: exact model id from that docs page / `opencode models` / the Go models
     API, retry 3× over ~10 min with backoff, and say whether it is capacity (429, temporary) or removed. If it works,
     add it as a lane only if its historical 25/25 gate still holds on a 5-doc spot check.
2. Unit tests for the patch (from-chunks text assembly, date resolver patterns + sanity rules, retryable skip,
   ordering). Run them.
3. **Pilot:** 25 newest transcripts across the three lanes into `concall_facts.db` (the real DB — this is the
   approved pilot), verbatim/QA checks as in production. Report: per-lane success, seconds/transcript, items per
   transcript, QA failures, 429s, and 3 spot checks (fact vs transcript text).

Final answer: diff summary, test output, date-resolver coverage, LongCat finding, pilot table, and the exact command
for the full newest→oldest run (Claude/Shivam approve it separately).
