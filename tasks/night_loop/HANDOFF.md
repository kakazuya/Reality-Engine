# Hand-off between loop sessions (each loop overwrites "Current state" and "Next", appends "Learnings")

## Current state (loop 1, 4 Nov 2026 04:45 IST by this machine's clock; full detail `loops/loop_01_report.md`)
- Phase 1 sets written: `questions/<SYMBOL>.jsonl`, 1,305 questions over 10 companies, generator `questions/gen/build.py`.
  My own checks pass; the official `qset check` has not passed them yet (defects below). Q5 and Shivam's approval are open.
- Library inputs unchanged except `questions/sector_vocab.json` (stored table names added; needs the wrapper's OK).
  Bank diff: `questions/BANK_DIFF_2026-11-04.xlsx`.
- Raw: `D:\RealityEngine\pilot10\raw\`, 873 of about 1,160 at wrap-up, 279 announcements pending. Resume, safe to repeat:
  from the repo root with `PYTHONPATH` = repo and `REALITY_DATA_ROOT` = `reality_engine\data`, run
  `python D:\RealityEngine\pilot10\runners\run_fetch.py --fetch`; table: `python D:\RealityEngine\pilot10\runners\coverage.py`.
- `tasks/night_loop/pilot10_profile.json`: the 10 companies, paths, `window_start`, lender flags.
- Stores: XBRL Q2 FY27 held for 9 of 10 (Hindalco has not filed). Sep 2026 shareholding missing for HINDUNILVR, INFY,
  MARUTI, HINDALCO. Prices and deals end 23 Oct, truth snapshot 19 Oct.
- Workers: `20261103T225130Z-b1c96638` REJECT, do not merge (built a second `night_eval`, no pilot3 change).
  `20261103T231018Z-fa830b2b` (`qset` fixes) running, not reviewed.
- Wrapper note 06:00 IST (Shivam): in DeepSeek peak hours use a Sonnet 5.5 medium worker instead of waiting:
  `python tasks/night_loop/sonnet_worker.py start <name> <brief.md>` / `wait <name>` (see LOOP_BRIEF.md).
- Wrapper note 06:20 IST: T-055 merged to main (c17b5a4): `python -m reality_engine.night_eval.qset check
  tasks/night_loop/questions` runs from the main checkout; README `reality_engine/night_eval/README.md`.

## Next
1. Wrapper: review `fa830b2b` (check it did the `qset` fixes, not T-055 again), merge, then run `qset check` on the ten files
   and fix any question-side failures; finish the raw fetch; rerun the coverage table.
2. Add a new ticket for pilot3 generalisation, then restart it from `loops/loop_01_worker_generalise.md` with that ticket.
   Loop 2 cannot build pilot10 without it.
3. Close the store gaps: Sep 2026 shareholding for 3 companies (Hindalco when filed), prices and deals to date, a truth
   snapshot, and SHP XBRL for all 10 (`stores.SHP_XBRL` holds the pilot folder only).
4. Rule on: the `orders` reading outside EPC, the no-rating template, the vocabulary extension, size above 120 per company.

## Learnings (append one line each; newest last)
- 3-4 Nov: full rebuilds (8 min) were the slow loop; per-company parts and fixed check pages are the fast loop.
- 3-4 Nov: workers spent 30-50 calls rediscovering facts when briefs lacked evidence; with evidence, 8-15.
- 4 Nov: hand-read grade of 185 pilot3 answers: 154 right, 30 partly, 1 wrong; the misses were guidance rows,
  period labels a quarter off, and numbers only in deck tables or annual-report prose.
- 4 Nov: `fetch_pilot60_history` fetches any universe and window unchanged: a 10-line runner repoints ROOT, the manifest
  and the cache (`pilot10\runners\run_fetch.py`). Rate seen about 40 documents a minute, many hard-linked from held stores.
- 4 Nov: NSE `integrated-filing-results?index=equities&symbol=<S>` returns one company's XBRL list; the unfiltered index
  returns only about the last 1,000 rows.
- 4 Nov: a worker started with an existing ticket built that ticket's old task instead of the brief. Give new work its own ticket, and read the branch's file list before believing a report.
- 4 Nov: `.tmp` is under a permission deny rule for this session; helper scripts go to `D:\RealityEngine\pilot10\scratch`.
- 4 Nov: page dumps of decks burn context fast; loop 1 reached 400k before its work ended. Search for terms and print short hits instead.
