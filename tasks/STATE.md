# STATE: the one live state. Keep it under 40 lines, overwrite in place. Last updated 2026-11-02 (Wolf)

## Now
**Pilot test on BAJFINANCE, HINDALCO and KEC, by Shivam's order of 2 Nov.** Workspace tickets no longer block it. The last prototype failed: 0 of 40 sampled answers right, 78% of numbers missed: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`.

**T-048 gap loop on KEC is running** (started 2 Nov about 16:15 IST; log `D:\RealityEngine\sandbox\kec_loop\logs\loop.log`, reports in `reports\`; Opus usage counted from 14:20 IST in this session's transcript). `reality_engine/gap_loop/` (checks, store, tiers, ledger, loop, keeper) plus the shared `reality_engine/scripts/session_runner.py`; Claude's review is fixed: a number that fails a check leaves its row `unverified` instead of failing the unit, a number may cite a re-runnable `reality-data` call (`tool`+`args`) instead of a `doc_text` page, fix units cap at 10 questions (25 of one gap type = 3 units), tier 2 starts with `approved_by` recorded, and an escalation writes one line per question. 19 gap-loop tests pass and `--dry-run` on `D:\RealityEngine\sandbox\kec_loop` prints 10 answer units of 10 (tier 1 Haiku, then DeepSeek, then `escalations.jsonl`) with no model call. Claude starts the real run after review. Method: `docs/DEVELOPER_GUIDE.md` section N.

## Next action
**T-045 doc review is done and closed** (Shivam, 2 Nov), archive included: 22 finished archive briefs deleted. Open with Shivam: delete `tasks/ar_study/text/` (32 FY24 annual-report extracts of the finished October AR study; no test or code reads them). Method: `docs/DEVELOPER_GUIDE.md` section M.

Pilot session, next, in order:
1. T-035 extraction finished 04:2x IST: `.tmp/proto3/extract_t035.db`, 830 calls, 0 errors, 1,476 checked or unchecked numbers, est. $2.09, DeepSeek at low effort. Number check: 783 confirmed, 222 disputed, 471 unchecked (456 are XBRL rows with no page). In a sample of 12 disputes the number was on neither reading of the cited page, so suspect a wrong page from multi-page chunks before suspecting misreads: test that first. Then `proto3 recheck` on it; `load_fact --extract` it into a copy of the fact store (`.tmp/proto3/v4`); `run_proto3_bank.py`; Claude grades by reading. `order_book_contract`, `supply_link` and `company_debt_mix` returned almost no rows: check why.
2. Drop the Workers sheet from `reality_engine/scripts/rule_ledger.py`: `reality_engine/scripts/worker_review.py` covers it. On every worker finish add its row to `tasks/efficiency/worker_reviews.jsonl`, then `worker_review build`.
3. Ask Shivam for the Console Usage screenshot to compare with `tasks/ledgers/spend.jsonl`, and for acceptance of T-042, T-043; T-034, T-037, T-038, T-040 after the grade.

T-044 is merged: `job_watch status` runs on every prompt through `.claude/settings.json`. Truth rule v2 is merged as a tool (1 false RIGHT on 94 read rows, `tasks/arch_v4/TRUTH_RULE_V2_2026-10-31.md`); the hand-read grade stays the reported score.

## Running
No pilot job or worker.

## Where the project stands
Golden rule step 3, schema design, with the question bank accepted (1,901 questions, frozen). Gate on the old pilot: 12.7% contract strict, but 0 of 127 answered rows right on hand reading. Prototype on 3 companies failed its grade: `tasks/pilot60/PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`. Full record: `tasks/arch_v4/GATE_STATE_2026-11-01.md`. Decisions: `D:\RealityEngine\plans\DECISION_LOG.md`, last 5 entries.

## Never
Copy keys into files or print them. Read `D:\Shivam_Private\Manual Dumps` or send it to the HP or any model, or put amounts in the repo or decision log. Loosen a grader to raise a score. Push without Shivam's OK. Spend DeepInfra or use paid models without his OK. Change the question bank, labels or scope without his ruling. Assign pilot bank reasoning to a worker: Claude owns it, DeepSeek only reads.

## Merge recipe
Review by meaning; a report without `Docs updated:` is not merged. `git merge --no-ff --no-commit <branch>`, drop `PROGRESS_NOTES.md`, keep ours on `query/v4/__init__.py`, run the tests, update this file and each affected doc, commit ending `By: Wolf` and the co-author line. Copy `.tmp` DBs first, then remove the worktree and branch. Log to the decision log and `rclone copy D:\RealityEngine\plans gdrive:InfoDiffusion_archive/plans`. HP: `hp_worker fetch-patch <job>` gives branch `dsh-hp/<job>`.

## Machines
How to operate each computer: `machines/README.md`. All HP work runs headless. Nothing is pushed without Shivam's OK.
