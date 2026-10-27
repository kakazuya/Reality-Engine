# Task — widen the BSE concall candidate set beyond "Earnings Call Transcript" (code + dry-run only)

## Goal
Shivam's ruling (2026-10-28): fetch every concall transcript.

`reality_engine/scripts/concall_refetch.py` (merged to main) only picks BSE announcements in the "Earnings Call Transcript" subcategory: 9,390 candidates. **That full fetch is already running separately; don't run it or touch its output.**

The old corpus also holds 1,771 transcripts filed under other BSE subcategories: "Analyst / Investor Meet" 1,437, General 236, and a few others. See `tasks/concall_refetch/report_pilot.md` §1.

## Do
1. **Add a `--widen` mode to `concall_refetch.py`.** It selects FY25+ announcements from `bse_announcements.db` in the subcategories "Analyst / Investor Meet", "General", "Investor Presentation" and "Press Release / Media Release". Pick those whose headline, or the attachment name, signals a transcript, for example:
   - transcript, conference call, earnings call, concall, con call;
   - investor call, analyst meet transcript;
   - Regulation 30 + 46(2)(oa).

   Exclude plain "schedule of analyst meet" intimations and audio/video-link-only notices.
2. **Dedupe** against the 9,390 Earnings Call candidates by (ISIN, fiscal quarter) and by attachment name. Report the overlap.
3. **`--dry-run`:** produce the widened candidate list and its counts by subcategory and fiscal quarter, with no network. Also measure recall against the 1,771 old-corpus rows the pilot listed: how many does the widened filter catch? List 20 misses with headlines.
4. **Classifier precision:** sample 40 widened candidates whose attachments already exist on disk, in `D:\RealityEngine\raw\concall_pdfs_probe` or `concall_pdfs`. If fewer than 40 exist, use the headline only and say so. Apply the pilot's real-transcript test and report precision.
5. **Tests:** extend `reality_engine/tests/test_concall_refetch.py` with offline cases for the headline filter (positive and negative) and the dedupe.

## Rules
- **No network** in this task. The widened fetch runs later, after the 9,390 finish, to keep BSE at ≤76 requests/min in total.
- Write only in this worktree. All databases are read-only (`connect_ro`). No commits.

## Acceptance checks
1. `--widen --dry-run` gives counts, overlap and recall against the 1,771.
2. The precision sample is reported.
3. The tests pass.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_concall_refetch
```

## Report
Give:
- the widened candidate count, by subcategory;
- the overlap with the 9,390;
- recall on the 1,771, with the misses;
- precision;
- the expected fetch time at ≤25 requests/min;
- the exact command to run the widened fetch later;
- your tool-call count.
