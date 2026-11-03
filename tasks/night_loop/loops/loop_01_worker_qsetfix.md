Goal: `python -m reality_engine.night_eval.qset check tasks/night_loop/questions` judges the ten real company files correctly, and `answerable.py` scores them, by fixing five mismatches between `reality_engine/night_eval` and the real question files.

Evidence (gathered by the controller, 4 Nov 2026; do not re-derive). Current output of the check on main: `questions: 1469 ok: False`, with these causes:
1. `qset.py:23` `VOCAB = ROOT / "tasks" / "night_loop" / "sector_vocab.json"`: the file is `tasks/night_loop/questions/sector_vocab.json`.
2. `qset.py:137-142` `load_vocab` and `q1_sector_fit` (line 144 on) assume `{sector: {metric: [synonyms]}}`. The real file is `{"_note": str, "universal": [ids], "technical": [ids], "<sector>": [ids]}`. Allowed metrics for a question = its sector's list + universal + technical. Keep accepting the dict form so existing fixtures pass.
3. `qset.py:128` `qdir.glob("*.jsonl")` also reads `LIBRARY_universal_technical.jsonl` and `LIBRARY_sectors.jsonl` (198 library lines, hence 1469 instead of 1271). Skip files whose name starts with `LIBRARY_` and any file not holding `qid` questions.
4. The near-duplicate check compares across companies (output has `DUP SBILIFE-051 ~ SUNPHARMA-058 (0.818)` by the thousand: the same universal question for two companies is not a duplicate). Compare only within one symbol.
5. `validate` (`qset.py`, the `need.get("table") not in ROW_TABLES` line) rejects two valid cases, e.g. `SCHEMA BAJFINANCE.jsonl:72 needs[0].table: 'valuation_daily' is not a typed table` and `'insider_trade' is not a typed table`:
   - `valuation_daily` is a real pilot3 table (columns symbol, isin, date, basis, close, shares_outstanding, market_cap, trailing_eps, trailing_pat, net_worth, net_debt, trailing_ebitda, pe, pb, ev_ebitda, dividend_yield_pct, known_at): add it to `qset.ROW_TABLES` and to `answerable.py:29-39` `ROW_TABLES` as `(None, "date", "date")`, with the metric checked as a non-null column the same way `price_delivery` is at `answerable.py:147`.
   - A need with `"new_table": true` names a table Phase 2 must add (`insider_trade`, `index_price`, `bulk_block_deal`). It is valid in `validate`; in `answerable.py` it is met only if that table exists in the db with a row for the symbol, otherwise unmet with work-list key `table.metric`. It must not raise when the table is absent.
Gotchas: pytest `tmp_path` is denied in the dsh sandbox (use a temp dir under `.tmp`); read the question files only, do not change them; never read `D:\RealityEngine\pilot10\eval_hidden`.

Files: `reality_engine/night_eval/qset.py`, `reality_engine/night_eval/answerable.py`, `reality_engine/night_eval/README.md`, `reality_engine/tests/test_night_eval.py` (add new tests; change no existing assertion), `docs/DEVELOPER_GUIDE.md` only if it states the old vocabulary path. Do not touch: `tasks/night_loop/**`, `reality_engine/pilot3/**`, `plugins/**`, `guards.py`, `decide.py`.

Accept:
1. `python -m pytest reality_engine/tests/test_night_eval.py -q` passes, with new tests: list-form vocabulary with universal and technical lists; LIBRARY file skipped; same text under two symbols is not flagged; the same text twice under one symbol is flagged; a `new_table` need validates and scores unmet when the table is absent and met when a fixture table holds a row; a `valuation_daily` need scores met on a fixture row.
2. `python -m reality_engine.night_eval.qset check tasks/night_loop/questions` prints `questions: 1271` or the current sum of the ten files, with no SCHEMA lines; paste its full output in your report (the controller fixes any question-side failures).
3. `python -m reality_engine.night_eval.answerable --db reality_engine/data/pilot3/pilot3.db --qset tasks/night_loop/questions/KEC.jsonl --out .tmp/kec_a1.json` runs under 60 s; paste the printed summary and the top 15 of the work list.
4. code-tools `typecheck` clean on changed files.

Stop if: an existing test assertion would have to change; a fix needs files outside the list.
Budget: 8 tool calls before the first edit, 80 total, 45 minutes. No paid calls.
Ticket: T-055
Report: per file what changed; accept outputs; tool calls before first edit and any Evidence item wrong; `Docs updated:` line.
