# T-242 brief: extend the filed-figure cross-check to balance sheet, cash flow and half-year lines (dsh DeepSeek, off-peak, 26 Nov, Wolf)

Ticket: T-242
permission: workspace-write (worktree)

Goal: `reality_engine/v2/xbrl_crosscheck.py` (read it first; skill `.claude/skills/store-accuracy-review`) checks hy4
results rows against the store's `fin_quarter_xbrl` (P&L, quarters only): 863 match, 28 unit fixes, 65 contradict.
Extend it to the store's `fin_annual_line` table, which holds filed balance-sheet, cash-flow and P&L lines mostly for
HALF-YEARS (period_type 'H1': BS 3,269 / P&L 2,391 / CF 1,659 rows in 150 stores; a few 'FY' and 'Q'). Check both
`D:/RealityEngine/hy4_out/obs_results_fy27.db` and `obs_ar_fy27.db` rows (an AR's 31 March balance sheet matches a
filed 'FY'/'BS' line when present).

Evidence: `fin_annual_line` columns: symbol, fiscal_year, period_end, basis, statement ('BS'/'P&L'/'CF'), line_item,
caption, value, unit, scale, period_type ('H1'/'FY'/'Q'). Common line_items: trade_receivables, total_assets,
cash_and_equivalents, cash_flow_from_operations/investing/financing, equity_share_capital, net_worth, investments,
capex, employee_cost, other_income, other_expenses, total_income, eps_basic/diluted, dividends_paid,
proceeds_from_borrowings, repayment_of_borrowings, income_tax_paid. hy4 measures for these include
cash_and_cash_equivalents, trade_receivables, total_assets, equity_share_capital, cash_flow.operating,
cash_flow.investing, cash_flow.financing, total_equity, employee_benefits_expense, other_income, other_expenses.
Stores: C:/RealityEngine/tg_build/universe_fy27/c*/c*.db and full394 (read-only, `mode=ro`, timeout=300).

## Steps
1. Add a second filed source in xbrl_crosscheck.py (or a sibling module sharing its helpers): load `fin_annual_line`
   per symbol keyed by (line_item, period_end, basis, kind) where kind = 'stock' for BS (an as-at date) and
   'H1'/'FY'/'Q' duration for P&L/CF. Map hy4 measures -> line_items in a dict like MEASURE_TO_XBRL.
2. Period matching: a BS row matches on its as-at date ("As at 30.09.2026", "31st March 2026"); a P&L/CF row matches
   only when its period names the same duration (half year / six months -> H1; year -> FY; quarter -> Q) and end date.
   Reuse the date parsing; add `as_at_date()` and `half_year_end()` beside `quarter_end()`.
3. Same verdicts and rules as the quarter check: `xbrl_match` / `xbrl_unit_fix` / `xbrl_contradicts`; tolerance 1% or
   half the last printed digit; skip segment/geography/product rows and non-company scope; an empty basis is never
   called wrong; sign-convention lines (cash outflows printed in brackets vs filed negative) -> match on |value| for
   CF lines whose sign convention varies (purchase of fixed assets, dividends paid, repayment, taxes paid).
4. Verdicts: one file per hy4 DB in --out-dir (default D:/RealityEngine/checks/xbrl; YOU run with --out-dir
   .tmp/checks_xbrl, Wolf copies). Merge with the quarter verdicts so one file per DB still holds every xbrl verdict
   (a row checked by both sources: a match in either wins; contradictions only when no source matches).
5. Tests in reality_engine/tests/test_xbrl_crosscheck.py: BS as-at match, H1 cash-flow match, sign-convention CF
   match, half-year row never compared with a quarter line, contradiction, unit fix. Keep the existing 6 tests passing.
6. Run on both DBs; report counts per verdict and statement, and 20 seeded (seed 7) contradictions with page text read
   (judge: real read error vs matcher error). Precision of contradictions >= 80% or report the rule, not ship it.
7. Docs: extend the XBRL cross-check bullet in docs/DEVELOPER_GUIDE.md; update the check table in
   .claude/skills/store-accuracy-review/SKILL.md.

Files: reality_engine/v2/xbrl_crosscheck.py, reality_engine/tests/test_xbrl_crosscheck.py, docs/DEVELOPER_GUIDE.md,
.claude/skills/store-accuracy-review/SKILL.md. Do NOT edit load_observations.py (verdict names are unchanged).
Accept: python -m pytest -q reality_engine/tests/test_xbrl_crosscheck.py passes; counts per DB; contradiction sample
judged.
Stop if: contradictions exceed 25% of compared rows (matcher problem): report the top 3 causes and stop.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine; no model calls; hy4 DBs are
live (read-only, timeout); never kill processes by name.
Budget: ~2 hours, ~150 tool calls.
