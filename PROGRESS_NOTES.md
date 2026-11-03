# Progress — T-049 F answer check (worker 20261103T120512Z-b23f455b)

- Read the context pack, the pilot3 lookups, gap_loop checks/loop/oracle and the three sandbox dbs.
- Sandbox `answers` table: `round, qid, status, answer_json, gap_type, tier`; status `answered` = 251 newest-per-qid
  rows = the loop-passing test set (KEC 89, BAJFINANCE 83, HINDALCO 79). Answer JSON carries `numbers[]` with
  measure/value/unit/period/table/rowid/known_at, so the oracle says which table produced each number.
- `reality_engine/pilot3/answer_check.py` written: oracle loader, per-symbol measure vocabulary, rule mapper
  (docs/price/valuation/statement/announcement/holding/measure/word-measure/text/hint), one lookup call per
  question against the real lookups module via REALITY_PILOT3_DB, comparison reusing `gap_loop.checks`
  numbers + `pilot3.oracle` periods, xlsx (answers + summary) and self-contained html.
- `reality_engine/tests/test_pilot3_answer_check.py`: fixture pilot3 db + fixture sandbox, 12 tests pass.
- First `.tmp` run (300 questions): match 72, partial 34, mismatch 110, empty 36, answered_no_oracle 47, no_tool 1.
- Next: rerun after the derived-question mapping fix, then update guide O5 + STATE.md, run the accept command.
- Final `.tmp` run: match 72 (KEC 29, BAJFINANCE 24, HINDALCO 19), partial 33, mismatch 111, empty 36,
  answered_no_oracle 47, no_tool 1 of 300. KPI store is the hole (2 match / 62): Bajaj AUM/CoF/new loans and
  Hindalco shipments/EBITDA-per-tonne stop ~FY24; KEC order book 36,267 is labelled FY25. Guide O5 rewritten
  (command, classes, rules, caveat), STATE.md Running updated. Accept: 23 passed, 1 known sandbox MCP-stdio
  failure. Done.
