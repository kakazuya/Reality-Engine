Goal: a named calc catalog the answering model calls instead of doing arithmetic: `plugins/reality-data/server/calc_catalog.py` with the 14 formulas below, each returning value, unit, the formula text and the inputs echoed back; served by `p3ask catalog` and listed by `p3ask catalog name=list`. Every compute-class failure listed under Evidence is reproduced right by one catalog call in a test.

Evidence:
- Why: pilot10 re-asks (8-9 Nov) still lost marks on hand arithmetic: BAJFINANCE-005 TTM PAT 22,067 vs FY26 19,332 written 14.12% (right 14.15%); KEC-081 compares TTM with FY26 although they overlap two quarters; MARUTI-023 sets a six-month receivables change against year-on-year revenue growth; ETERNAL-020 operating cash flow 632 crore against PAT 366 and EBITDA 1,208 (earlier run wrote it ten times too large); HINDUNILVR-031 gave ROCE levels, not incremental ROCE (change in EBIT over change in capital employed); BAJFINANCE-123 PE 30.9 in a 26.1-37.9 range called 'upper half' (it is 41% up the range); HDFCBANK-120 fair P/B by Gordon done backwards (at ROE 14.5%, COE 12%, g 7% fair P/B is 1.5); SBILIFE-081 Q3/Q4 FY26 APE not derived from 9M and FY; SBILIFE-105 18.8% operating RoEV called the half-year return (it is annualised); ETERNAL-113 added EBITDA margin points to match a PAT target, ignoring tax and depreciation.
- Existing code to reuse, not duplicate: `plugins/reality-data/server/calc.py` (`evaluate(expression, inputs)`, `parse_input(spec)` parses '5 crore', '12.5%', unit-aware Fractions; raise `CalcError` on unit clashes). Price-side maths (Wilder RSI, gaps, volume spikes, range, moving averages) already lives in `lookups_tech.py`; do NOT re-implement it, list those names in the catalog listing as `see tech kind=...`.
- CLI: `reality_engine/scripts/p3ask.py`, `TOOLS` tuple line 20 and `run()` line 33: add `catalog` -> `calc_catalog.run(args)`.
- The 14 formulas (id: inputs -> output):
  1. GROWTH: now, before -> pct (100*(now/before-1)); refuses before<=0 with a reason.
  2. TTM_SUM: q1..q4 (four quarter values, with period labels) -> sum; refuses if the labels are not four consecutive quarters.
  3. TTM_GROWTH: ttm_now, ttm_year_ago -> pct. Also accepts period labels and REFUSES comparing a TTM with a fiscal year it overlaps (KEC-081): message names the overlapping quarters.
  4. Q_FROM_CUMULATIVE: longer (FY or 9M or H1 value + label), shorter (9M/H1/Q1 value + label) -> the residual period value and its label (FY-9M = Q4, 9M-H1 = Q3, H1-Q1 = Q2).
  5. SHARE: part, total -> pct.
  6. CONTRIBUTION_TO_INCREASE: part_now, part_before, total_now, total_before -> pct of the total's change that the part explains.
  7. CASH_CONVERSION: ocf, pat, ebitda -> ocf/pat and ocf/ebitda (x); all three must carry the same unit after parsing.
  8. INCREMENTAL_ROCE: ebit_now, ebit_before, capital_employed_now, capital_employed_before -> pct.
  9. RANGE_POSITION: x, low, high -> pct ((x-low)/(high-low)) plus the words 'lower third'/'middle third'/'upper third'.
  10. FAIR_PB: roe, cost_of_equity, growth -> x ((roe-g)/(coe-g)); IMPLIED_ROE: pb, cost_of_equity, growth -> pct (roe = pb*(coe-g)+g).
  11. IMPLIED_GROWTH_PE: pe, payout, cost_of_equity -> pct (from PE = payout*(1+g)/(r-g): g = (PE*r - payout)/(PE + payout)).
  12. ANNUALISE: rate, months, method ('simple'|'compound') -> pct, and the label 'annualised' always in the reply.
  13. SAME_SPAN_GROWTH: balance_now, balance_before, flow_now, flow_before, plus the four period labels -> both growths; refuses when the balance span and the flow span differ (MARUTI-023).
  14. PROFIT_BRIDGE_MARGIN: target_pat, revenue, tax_rate, depreciation, finance_cost, other_income -> the EBITDA margin needed (ETERNAL-113): ebitda = target_pat/(1-tax) + depreciation + finance_cost - other_income; margin = ebitda/revenue.
- Reply shape (every formula): {"formula_id", "value", "unit", "formula": "<text with the numbers substituted>", "inputs": {...as parsed...}, "notes": [..]} or {"error": "<reason>", "formula_id"}.
- Data: none read; pure functions. No database access in this module.
- Checks: `python -m pytest -q reality_engine/tests/test_calc_catalog.py` (new) and `python -m pytest -q reality_engine/tests/test_p3ask.py` if it exists (run each test file in its own process). Pytest `tmp_path` is denied in the sandbox; you need no temp files.
- Gotchas: inputs come as strings like '22,067 crore' or numbers; use `calc.parse_input`. Percent inputs ('14.5%') parse to fractions: keep pct outputs as percent points (14.15 not 0.1415). Round only in the `formula` text, never in `value`.

Files: new `plugins/reality-data/server/calc_catalog.py`; new `reality_engine/tests/test_calc_catalog.py`; edit `reality_engine/scripts/p3ask.py` (catalog tool); edit `docs/PILOT3_BLUEPRINT.md` (one short section 'Calc catalog (T-135)' listing the ids) and the docstring of p3ask. Do not touch: `calc.py` logic (import it), `lookups_tech.py`, `lookups_pilot3.py`, `server.py` (the controller wires the MCP tool after review), anything under `reality_engine/pilot3/`.

Accept:
1. `python -m pytest -q reality_engine/tests/test_calc_catalog.py` passes, with at least one test per formula, including these exact cases: GROWTH('22,067 crore','19,332 crore') = 14.147..% (round 2 -> 14.15); TTM_GROWTH refuses TTM to Q2FY27 vs FY26; Q_FROM_CUMULATIVE(FY26=100, 9MFY26=72) -> Q4FY26 = 28; CASH_CONVERSION('632 crore','366 crore','1,208 crore') -> 1.727x and 0.523x; RANGE_POSITION(30.9, 26.1, 37.9) -> 40.68% 'middle third'; FAIR_PB(14.5%,12%,7%) -> 1.5; IMPLIED_ROE(1.85,12%,7%) -> 16.25%; ANNUALISE(9.4%, 6, simple) -> 18.8% labelled annualised; SAME_SPAN_GROWTH refuses H1 balance change vs YoY revenue; CASH_CONVERSION refuses '632 crore' with '366 lakh units'.
2. `python -m reality_engine.scripts.p3ask --db D:/RealityEngine/pilot10/pilot10.db catalog name=GROWTH 'inputs={"now": "22,067 crore", "before": "19,332 crore"}'` prints value 14.147...
3. `python -m reality_engine.scripts.p3ask --db D:/RealityEngine/pilot10/pilot10.db catalog name=list` prints all 14 ids plus the tech kinds.
4. basedpyright (code-tools typecheck) clean on the two new files.

Stop if: a formula needs data from a database (report which), or the change needs files outside the list.

Budget: first edit within 10 tool calls; 80 tool calls total; 2 hours; no paid calls.

Ticket: T-135
