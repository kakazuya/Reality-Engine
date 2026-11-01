# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-02 (Wolf)

## Now
**Pilot test on BAJFINANCE, HINDALCO and KEC, by Shivam's order of 2 Nov.** Workspace tickets no longer block it. The last prototype failed: 0 of 40 sampled answers right, 78% of numbers missed: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`.

## Next action
1. Overlay worker `20261101T204312Z-47a63343` (T-034): review and merge. If it died with the old session, restart it from the same goal: OCR text for thin pages, with its source recorded.
2. HP OCR: `tasks/pilot60/proto3_text/thin_pages.py` cuts 352 thin deck pages plus 100 check pages; the copy to the HP failed (`tar` returned 1 on the `C:/` path, 0 files arrived). Fix that, then start an HP job writing `ocr_pages.jsonl.gz` for them. The 100 pages measure how wrong hidden text layers are.
3. KEC transcripts (T-037): `tasks/pilot60/proto3_text/kec_fetch.py` found no links because the page's hrefs do not end in .pdf; listing saved at `D:\RealityEngine\raw\kec_transcripts\_listing.html`. Fix the pattern and fetch. known_at comes from the cover letter's filing, not the fetch.
4. T-038: wire `extract_proto3.db` rows that pass contracts into the fact view, and answer narrative questions with retrieved passages and exact quotes, no model. Of 153 rows, 29 answered and 124 refused: 115 reasons were no row in the store, 47 narrative with no topic.
5. T-035: rerun extraction, hard stop $8, DeepSeek; answer the same questions; grade by reading.

## Running
Overlay worker only. The dsh-worker server still has the old start gate until restarted.

## Where the project stands
Golden rule step 3, schema design, with the question bank accepted (1,901 questions, frozen). Gate on the old pilot: 12.7% contract strict, but 0 of 127 answered rows right on hand reading. Prototype on 3 companies failed its grade: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`. Full record: `tasks/arch_v4/GATE_STATE_2026-11-01.md`. Decisions: `D:\RealityEngine\plans\DECISION_LOG.md`, last 5 entries.

## Never
Copy keys into files or print them. Read `D:\Shivam_Private\Manual Dumps` or send it to the HP or any model, or put amounts in the repo or decision log. Loosen a grader to raise a score. Push without Shivam's OK. Spend DeepInfra or use paid models without his OK. Change the question bank, labels or scope without his ruling. Assign pilot bank reasoning to a worker: Claude owns it, DeepSeek only reads.

## Merge recipe
Review by meaning; a report without `Docs updated:` is not merged. `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, keep ours on `query/v4/__init__.py`, run the tests, update this file and each affected doc, commit ending `By: Wolf` and the co-author line. Copy `.tmp` DBs first, then remove the worktree and branch. Log to the decision log and `rclone copy D:\RealityEngine\plans gdrive:InfoDiffusion_archive/plans`. HP: `hp_worker fetch-patch <job>` gives branch `dsh-hp/<job>`.

## Machines
How to operate each computer: `machines/README.md`. All HP work runs headless. Nothing is pushed without Shivam's OK.
