# Worker: guidance wrong rows

Goal: the known wrong guidance rows are gone or correctly labelled by general rules, and every company's new rows read at least 18 of 20 right (all rows if fewer than 20).

Ticket: T-062

Evidence, on `D:\RealityEngine\pilot10\scratch\combined3.db`, table `guidance` (metric, target_period, low, high, unit, direction, said_on, doc_key, page, quote, speaker, extractor_rule):
- SBILIFE `ebitda_margin` FY27 14-15 pct up, quote p8 "we'll be growing for the year at around 14% to 15%". This is individual APE growth; the question naming APE is on the previous page, outside the 300-character question window, and the visible question is about margins. Same idea: a growth sentence must not take a margin metric from a question.
- MARUTI `other` FY27 34 pct flat, "salaried is about 40%, business would be about 34%, self-employed about 20%, very broad profiling for customers". A customer mix, not a target. It came in with the real transcripts now in the raw set.
- KEC `order_intake` FY27 20000, "out of INR30,000 crores ... roughly it would be INR20,000 crores". A slice of the target; the 30,000 row is right.
- HINDALCO `cost_of_production` FY26 3-4 up, "the cost of production in the Q2 level, I was expecting ... 3% to 4% higher than Q1". Period is Q2, not FY26. Graded `checkpages` entries read this row: report if a right fix changes the 145.
- HDFCBANK, ETERNAL and INFY rows from documents added today have never been hand read: ETERNAL 12, HDFCBANK 2, INFY 16.
- `other` currently takes anything with a number and a forward word. It should need a real target wording.
- Code: `reality_engine/pilot3/guidance.py`, including `worded_row`, `CUE`, `OTHER_CUE`, `PAST_ONLY`, `METRICS`, `NO_GUIDANCE`, `EXAMPLE_LIST`, `NON_REVENUE_CAGR`. Use `outline` first. A sector word goes in a lexicon; adding a metric such as an insurer's APE growth is allowed. No company names in code.

Data: copy `combined3.db` to `D:\RealityEngine\pilot10\scratch\w_guid2.db` by sqlite3 `backup`. Never write `combined3.db`, `pilot10.db` or `pages.db`.

Fast check, foreground: `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part guidance --out D:\RealityEngine\pilot10\scratch\w_guid2.db` (about 10 s).

Accept:
1. Each row above is gone or right, shown with its quote. Sentences that must stay: SBILIFE "guidance of 26% to 28% range", SUNPHARMA "high single-digit consolidated top line growth for FY27", ETERNAL "60% CAGR", HDFCBANK "provision coverage will be in the 70s".
2. Hand read with seed 20261112: at least 18 of 20 per company, printed first in the report.
3. `python -m reality_engine.night_eval.answerable --db D:\RealityEngine\pilot10\scratch\w_guid2.db --qset tasks/night_loop/questions/dev.jsonl --out D:\RealityEngine\pilot10\scratch\a1_guid2.json`: no company below `D:\RealityEngine\pilot10\scores\a1_combined3.json`. Do not change the grader.
4. `python -m pytest reality_engine/tests/test_pilot3_guidance.py -q` with new tests from these sentences, and `python -m reality_engine.pilot3.checkpages run` at 145, or the exact change explained.

Files: `reality_engine/pilot3/guidance.py`, `reality_engine/pilot3/lexicon/*.yaml`, `reality_engine/tests/test_pilot3_guidance.py`, your lines in `docs/PILOT3_BLUEPRINT.md` and guide O6 in `docs/DEVELOPER_GUIDE.md`. Do not touch `tasks/`.

Stop if: free RAM stays under 2.5 GB for 10 minutes, or a company stays under 18 of 20 after two tries. Report the rows either way.

Budget: 70 tool calls. End with rows per company before and after, the hand read, A1 per company and a `Docs updated:` line.
