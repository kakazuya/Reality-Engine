Goal: close the two defects the T-048 AI loop left, in code.
1. `reality_engine/gap_loop/loop.py` `accept_answers` (line ~186) stored an answer for qid `HINDALCO029b`, which is not in the bank. Accept must reject any qid that is not one of the unit's question ids (and not in the company's bank), recording the rejection reason the same way other rejections are recorded. Add a test in `reality_engine/tests/test_gap_loop.py`.
2. Several loop answers said "absent" for numbers pilot3.db holds or can compute. In `reality_engine/data/pilot3/pilot3.db` (read-only for you; build into `.tmp/pilot3.db` with `python -m reality_engine.pilot3.build --out .tmp/pilot3.db --part all` if you need a writable copy) check that these are answerable by one query each, and add what is missing:
   - promoter, mutual fund and FPI holding % by quarter for KEC, BAJFINANCE, HINDALCO (`shp_category`; confirm the category mapping covers promoter / MF / FPI and that rows under older ISINs were copied via `symbol_isin_history`);
   - book value per share and ROCE (`ratio_panel`, metrics `book_value_per_share`, `roce`): confirm FY25 and FY26 rows exist per company where inputs exist;
   - Bajaj Finance net interest margin: not in `ratio_panel`. Add metric `nim_pct` in `reality_engine/pilot3/ratios.py` as a formula row in `formula`: annualised net interest income / average of opening and closing AUM (or loan book), inputs from `fin_quarter_xbrl` / `ratio_panel.net_interest_income` and `kpi_series` (AUM). Keep `is_derived=1` and `input_refs` filled. If the company states NIM itself in kpi_series, keep that as a separate company_stated row, never merged (same rule as section O of the guide).
   Add tests in `reality_engine/tests/test_pilot3_core.py` (fixture level, not the 90 s integration build).
3. Docs: section N (gap loop) and section O (pilot3, the formula list) of `docs/DEVELOPER_GUIDE.md` say what the code now does.
Files: reality_engine/gap_loop/loop.py, reality_engine/pilot3/ratios.py, reality_engine/pilot3/stores.py (only if the holding copy needs a fix), reality_engine/tests/test_gap_loop.py, reality_engine/tests/test_pilot3_core.py, docs/DEVELOPER_GUIDE.md
Accept: python -m pytest reality_engine/tests/test_gap_loop.py reality_engine/tests/test_pilot3_core.py -q
Stop if: AUM or loan book is not extractable for Bajaj from any pilot3 table; report the tables you checked with row counts instead of inventing an input. Do not write to reality_engine/data or D:\RealityEngine.
Budget: 150 tool calls.
Ticket: T-051
Report: changed files, test output, the one query per item in 2 with the value it returns for FY26 (or latest), and `Docs updated: <files>`.
