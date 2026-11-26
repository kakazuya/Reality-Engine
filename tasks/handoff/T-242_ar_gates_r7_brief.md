# T-242 brief: AR gates r7 - sub-table items never stored as the bare canonical measure; other-entity statement pages; units from the page before

Ticket: T-242
permission: workspace-write (your worktree only)
Author: Eagle (26 Nov 23:55 IST, from a hand read of AR ckpt_0004 W rows). Reviewer/recorder: Wolf (non-author). Start after the 08:00 27 Nov stop is lifted.
Base: main at or after c67d2a76 (AR gates r5+r6 merged). Same agy Hydrogen session as r5/r6 if it is still open.

Goal: the AR ckpt_0004 W kinds (43R/1P/16W/0J, fix note D:/RealityEngine/hy4_out/obs_ar_fy27.db.audit/ckpt_0004.fix.md) are handled by structural
rules, without undoing r6 (company-scope RPT rows stay verified; other_entity only on that entity's own statement pages).

Files: reality_engine/v2/observations.py (AR row gates: apply_ar_row_gates, ar_subset_as_total, ar_other_entity, unit/scale fill),
reality_engine/tests/test_ar_row_guards.py, docs/DEVELOPER_GUIDE.md (AR gates bullet).

Accept:
- python -m pytest -q reality_engine/tests/test_ar_row_guards.py ; then test_ar_sections.py, test_observations.py, test_results_gates.py, test_deck_guards.py
  (one file per call; all pass).
- On the 60 ckpt_0004 pack rows (C:/RealityEngine/t242/ar_grade_ckpt4/pack.jsonl, row text + page_text in each line): each of the W rows below ends
  unverified with a reason naming its kind (or corrected as described), and 0 of the 43 R rows change status.
- Measured on the rows these rules flag in a fresh copy (sqlite backup API, never a plain file copy: the hy4 DBs are WAL now) of
  D:/RealityEngine/hy4_out/obs_ar_fy27.db: verified downgrades <= 5% of verified; 20 random downgrades (seed 7) with page text, <= 2 of them right rows.

## Evidence (pack id, symbol, page, stored -> what the page prints)
Kind A - item under a geography / segment / currency / person / exposure sub-table stored as the bare canonical measure, segment empty:
- #19 ADVENZYMES p138 'USA' 2,192.35 -> revenue.value; page: 'Segment revenue (based upon location of customers) | India 3,718.88 | Europe | USA 2,192.35
  | Asia | Others | 7,449.50'. Fix: geography = 'USA', measure revenue.geography (or segment), never the company total.
- #39 BBOX p205 'America' 800.99 -> non_current_assets; page block '(b) Geographical segment ... Non-current assets'. Same fix.
- #49 AMBOAGRI p55 'Oil' 3,071.23 -> revenue.mix; page: 'Details of Manufactured Goods Sold | Biscuits | Oil 1,830.58 | 3,071.23' and later
  'Details of Traded Goods Sold | Oil 6,235.54 | 3,733.89'. Fix: product = 'Oil', segment = the sub-heading ('Manufactured Goods Sold').
- #57 ALPA p135 'Advances from Customers' 24,85,324 under '( In Foreign currency) | Particulars | USD' -> NEW:advances_from_customers, unit
  'In Foreign currency'. #25 ALLTIME p151 'Advance from customer' 8.79 in the unhedged foreign-currency exposure table -> NEW:advance_from_customer.
  Fix: a row inside a foreign-currency exposure / sensitivity table carries the currency (USD) and series 'fx_exposure'; never the balance-sheet measure.
- #28 AHASOLAR p94 'Jaydeep Parekh' 1.50 -> employee_benefits_expense (a KMP remuneration line in the RPT note). Fix: a person's name as the row label
  under KMP / related-party transactions -> customer/person = name, measure NEW:kmp_remuneration, never the company expense.
- #24 ACSTECH p70 'Total Unquoted Equity Instruments' 20,050.530 -> NEW:equity_instrument_count_total, scale 1: the value column is the carrying amount
  (the count column is 'No. of shares'). Fix: a 'Total ... Instruments' row whose number sits in the amount column is an amount with the note's unit.
Kind B - other-entity statement pages and scope:
- #26 AHLEAST p130 'Retained earnings' (46,540.70) kept as company by r6's own-equity guard; the page is GJS Hotels Limited's own notes
  ('Asian Hotels (East) Limited and its Nominees | 100% | 4,918,116' above '8. OTHER EQUITY'). Fix: a page that lists the company itself as a 100%
  shareholder is the subsidiary's statement page: entity_scope subsidiary, segment = that entity; the own-equity guard must not fire on it.
- #34 ASHOKLEY p337 '45.81 crores ... of losses before taxation to the Group' contributed by TECOSIM Group since acquisition -> scope company.
  Fix: 'X has contributed ... to the Group' -> entity_scope subsidiary, segment X, period as printed ('since the date of acquisition' stays unverified).
- #15 ADSL p238 'Soft Shell System (I) Private Limited' 40.68% -> scope subsidiary, but the RPT list prints 'Associate'. Fix: the printed relationship
  column decides (Associate -> associate).
- #13 ABANSENT p43 key-ratio table (Debt-Equity change -41.24%) -> basis standalone although the section heading is consolidated. Fix: basis from the
  nearest section heading on the page or the page before.
Kind C - unit / scale / measure:
- #27 BCG p140 'For Other Audit related Services' 2.00, unit 'Rupees' scale 1; the page before prints 'INR in Lakhs' for the note. Fix: an empty
  or bare-currency unit takes the note's scale from the page before (as the results gates already do).
- #37 AMAL p19 ten-year trend table 'EBTDA' 1,182 -> NEW:ebt. Fix: EBTDA / EBDTA labels map to a NEW:ebtda code, never ebt.
- #52 A2ZINFRA p49 '14.92% increase in turnover' (FY 2025-26 vs FY 2024-25) stored period 'FY 2025'. Fix: a growth figure over 'FY X compared with
  FY X-1' takes the later year.
Keep (r6 must hold): ACC / AGL / A2ZINFRA / ADVENTHTL / AFSL company-scope RPT rows stay verified; LT 'Subsidiaries, including:'; AMBALALSA /
PERSISTENT / AIAENG / ASIANTILES / 7NR own pages not other_entity.

## Steps
1. Reproduce each W above on the pack rows (row + page_text); write one failing test per kind with the printed text as fixture.
2. Kind A: detect the sub-table heading (Geographical segment / location of customers / Details of ... Goods Sold / foreign currency / USD / KMP)
   within the page lines above the row; set geography / product / segment / customer and the series; unverified with reason
   `ar_subtable_item: '<label>' under '<heading>'` when the measure would be the bare canonical one.
3. Kind B and C as above, each with its own reason prefix.
4. Run the accept tests; measure on a fresh backup copy (flagged rows only is enough); 20 random downgrades seed 7 with page text in your answer.
5. Docs: DEVELOPER_GUIDE AR gates bullet -> r7, with the measured numbers.

## Limits
Never write D:/RealityEngine or C:/RealityEngine files except your own scratch under the worktree .tmp; no model calls; pytest per file;
never kill processes by name. Structural rules only - never a per-company list.
Stop if: a rule would downgrade any of the 43 R rows and cannot be narrowed in 2 tries; or verified downgrades pass 5%.
Budget: ~120 tool calls.
