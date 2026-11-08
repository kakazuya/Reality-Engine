# T-113 A round 8: net cash sign, year-to-date words, same-document conflicts, analyst text (CONTINUE)

Ticket: T-113

CONTINUE: you are the checker's author for rounds 1-7 (commits 332acc8 .. 94b854f, last 94b854f). That session ended,
so this is a fresh session on the same task. Read `docs/DB_BUILD_GUIDELINES.md` section 13 and `git log -8 --stat` for
`reality_engine/pilot3/row_checks.py` before editing. Same rules as before: you are not the extractor's author; never
edit `kpi.py`, `guidance.py`, `lexicon/` or any extractor; no shared word lists; no company or metric literals in code.

Goal: no wrong row stays `verified` for the four defects below, with no new false quarantine on the dev dbs.

Files (only these): `reality_engine/pilot3/row_checks.py`, `reality_engine/pilot3/row_checks_vocab.yaml`,
`reality_engine/tests/test_row_checks.py`, `docs/DB_BUILD_GUIDELINES.md` section 13 (checks list, counts).

Evidence (read-only; never write to these):
- unseen6 dev db with stores built: `C:/Users/warri/AppData/Local/Temp/claude/12b5f02fd3b7ce95/fa93aa0b-0c04-408d-a8f4-f7630af29fed/scratchpad/ho/u6_eval.db`,
  profile `.../scratchpad/ho/unseen6_profile.json` (same folder). Opus's read after round 7 (seed 111108, 35 verified):
  33 right, 1 partly, 1 wrong. Rows (kpi_series ids in u6_eval.db):
  1. id 24 ALKEM net_debt 9MFY23 value +19 inr_bn, quote "strengthen our balance sheet with strong net cash position of
     ₹ 19". Net cash stored as positive net debt: wrong sign. Verified today. Must be quarantined (hard `net_cash_sign`):
     a net_debt row whose label or the words between label and number say "net cash" / "cash surplus" / "net cash
     positive" with value > 0 (and the mirror: "net debt" wording with a negative value is fine only when the quote has
     a minus or brackets). Row 245 below shows the right sign: net cash 200 stored as -200.
  2. id 985 ASHOKA capex Q2FY24 79 inr_cr, quote "capex for up-to-date was around INR79 crores and maybe the pending capex
     would be approximately INR15-odd crores for March '24". A year-to-date figure stored as one quarter. Extend
     `period_word` (or a new hard check) so cumulative words in the number's sentence ("up-to-date", "till date",
     "to date", "so far", "year-to-date", "YTD", "cumulative", "since April", "during the year so far") conflict with
     period_type 'Q'. Measure on both dev dbs how many Q rows it hits and read 10 of them.
  3. id 245 TEJASNET net_debt Q3FY24 -200, quote "net cash balance has also come down to INR200-odd crores. So that's why
     I was just trying to understand how": an analyst speaking; the question phrase is in the NEXT sentence. Still
     verified. The transcript speaker structure from round 6 (`not_company_speaker`) should already catch the speaker;
     find why it misses here (open doc_page for that doc_key / page 10 in u6_eval.db) and fix it generally. If the speaker
     cannot be found, a question phrase ("trying to understand", "could you", "can you", "?") in the sentence right
     after the number makes the row at most `unverified` (soft `question_next`).
  4. Same-document conflicts: two kpi rows with the same symbol, metric, dimension, fiscal_period and basis from the SAME
     doc_key that disagree by more than 1.5% (after scale) must not be `verified` (soft `same_doc_conflict`), unless one
     is clearly a different variant (already flagged soft `variant`). Count them on both dev dbs.
- pilot10 dev db: `D:/RealityEngine/pilot10/scratch/t113_p10_v2.db`, profile `tasks/night_loop/pilot10_profile.json`.
- Current runs: `python -m reality_engine.pilot3.row_checks --db <db> --out .tmp/rc.db --profile <profile>
  --tables kpi_series,guidance --report .tmp/rep --sample 30 --seed 5 --status verified`.

Steps:
1. Tests first in `test_row_checks.py`, tiny tmp_path fixtures with the three quotes above verbatim plus a right row each:
   "net debt of ₹ 1,200 crore" stored +1200 (verified or unverified, never quarantined); "net cash of INR 200 crore"
   stored -200 by a management speaker (not quarantined); "capex for the quarter was INR 79 crores" Q row (not
   flagged); two same-doc rows 100 and 100.5 (no conflict) and 100 and 140 (conflict).
2. Implement the four checks with general rules.
3. Run on both dev dbs; give before/after status counts per table and per new check, plus 5 random hits per new check
   (id, quote cut to 160 chars, verdict). Every quarantine a new check adds that you think is a right row: list it.
4. Update guide section 13. Final answer must start with `Docs updated:`.

Accept: `python -m pytest reality_engine/tests/test_row_checks.py -q` passes (44 tests today, more after); rows 24, 985
and 245 in u6_eval.db are not `verified` (24 quarantined); the pilot10 dev run finishes under 15 s.

Limits and pitfalls:
- Read-only on every database; outputs to `.tmp/` only. Do not open any other database in `scratchpad/ho/` (there is a
  hidden hold-out there; reading it voids the score).
- `PYTHONIOENCODING=utf-8` for any run that prints quotes. Write regexes with the editor, never in shell heredocs;
  never `\b` in a non-raw Python string.
- Run the test file alone, one process. No model calls, no new dependencies.

Budget: 120 tool calls, 2 hours.
Stop if: a rule needs a company or metric literal, or a known-wrong row cannot fail without quarantining a known-right
one: report the pair with both quotes and stop.
