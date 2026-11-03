# Hand-off between loop sessions (each loop overwrites "Current state" and "Next", appends "Learnings")

## Current state (wrapper, 4 Nov 2026 05:35 IST)
- Phase 1 library: `questions/LIBRARY_universal_technical.jsonl` (48 universal + 16 technical),
  `questions/LIBRARY_sectors.jsonl` (134 over 29 sectors), `questions/sector_vocab.json`, bank sort
  `questions/BANK_IDEAS_2026-11-04.xlsx`. Research report `D:\RealityEngine\reports\2026-11-04_question_research.html`.
- Pilot 10 chosen (`PILOT10.md`); no pilot10 data fetched yet; no pilot10 database yet.
- Launcher: `tasks/night_loop/run_loop.py NN` (wrapper only). dsh `20261103T224355Z-ef762679` (started 05:43 IST) builds the check scripts T-055
  (`reality_engine/night_eval/`: qset checks Q1-Q3, answerability A1, guards, decide, audit). It counts as one of
  loop 1's two worker slots.
- pilot3 code (`reality_engine/pilot3/`) builds one database for KEC, BAJFINANCE, HINDALCO; `SYMBOLS` and paths are
  fixed in it, so pilot10 needs it generalised (symbol list, data root, output path). Fast checks exist:
  `build --part <p> --symbols <S>` (extractors only), `python -m reality_engine.pilot3.checkpages run`.

## Next
Loop 1: Phase 1 company question sets for the 10 companies + raw data for the 7 new ones (see loop_01_brief.md).

## Learnings (append one line each; newest last)
- 3-4 Nov: full rebuilds (8 min) were the slow loop; per-company parts and fixed check pages are the fast loop.
- 3-4 Nov: workers spent 30-50 calls rediscovering facts when briefs lacked evidence; with evidence, 8-15.
- 4 Nov: hand-read grade of 185 pilot3 answers: 154 right, 30 partly, 1 wrong; the misses were guidance rows,
  period labels a quarter off, and numbers only in deck tables or annual-report prose.
