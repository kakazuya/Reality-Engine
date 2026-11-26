# T-242 brief: results gates r3e - five structural fixes from results ckpt_0002 (dsh DeepSeek, off-peak, 26 Nov, Wolf)

Ticket: T-242
permission: workspace-write (worktree)
Base: branch Wolf-agy-20261126T110515Z-55c573aa (results r3d, under review); keep every r3d/r3c test passing.

Goal: results ckpt_0002 graded 50 R / 4 P / 5 W / 1 J (W+J 10%). Eagle's fix note
D:/RealityEngine/hy4_out/obs_results_fy27.db.audit/ckpt_0002.fix.md (read first) names five structural causes. Fix each in
the results row gates of reality_engine/v2/observations.py (`apply_results_row_gates` and helpers) - structural rules
only, never per company. Rows end unverified (or right), never deleted.

Evidence (pack C:/RealityEngine/t242/results_ckpt2/pack.jsonl, page_text inside each row):
1. APMIN p5 '- on Current/Cash Credit Accounts' stored 10 (group total 2+8) instead of 8; ASTRONMULT p4 'Bank Balance :
   Current Account' under 'Cash And Cash Equivalents Comprise' stored as other_bank_balances. -> a component line under a
   printed 'comprise / consists of / includes' heading keeps the heading's measure family; a component row whose value
   equals the group's printed total is unverified `results_component_is_total`.
2. ARCHIDPLY p7 cash flow 'Interest Received' 10.16 stored as finance_income: the CF title is on the previous page ->
   the r3 cash-flow remap also runs when the cash-flow statement title is in the previous page's tail (head context).
3. AMIC p14 'Minority Interest' 29.76 'Half year ended 31.03.2026': a stock (balance-sheet family) measure never takes a
   duration fill - 'As at <date>' only.
4. ALANKIT p7 Note 4 face value Rs 10 of a subsidiary stored as the company's (company's FV Re 1 on p6): a note paragraph
   that names another entity ('<Name> Private Limited / Limited, a subsidiary') sets entity_scope 'subsidiary', unverified
   when not resolvable.
5. BLUECOAST p1 '33rd' Board's Report stored as 33 lakh: a number glued to st/nd/rd/th is never a value (junk).

## Steps
1. Reproduce each case from the pack row's page_text as a failing unit test in
   reality_engine/tests/test_results_gates.py; add a counter-test for each (a real component, a CF line already on a CF
   page, a stock row 'As at', the company's own note, '3rd quarter' text that is not a value).
2. Implement the five rules; run every results test file.
3. Measure on a recheck of a COPY of C:/RealityEngine/t242/results_r3d/base.db (Wolf's r3d baseline copy; copy it into
   your worktree .tmp; `python -m reality_engine.v2.observations --recheck --baseline <copy> --out <out>
   --stores-root C:/RealityEngine/tg_build/universe_fy27 --doc-types results` with REALITY_RAW_FETCH=0): count rows per
   new rule; 0 status change on the graded-R rows of C:/RealityEngine/t242/results_ckpt1, results_grade_r2,
   results_grade_r3c and results_ckpt2 (R = rows not named W/P/J in their fix notes); 20 seeded (seed 7) rows per new
   rule judged right/wrong from page_text.
4. Docs: DEVELOPER_GUIDE.md r3e bullet; tasks/t242_results_measure.md r3e section.

Files: reality_engine/v2/observations.py, reality_engine/tests/test_results_gates.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_results_measure.md.
Accept: python -m pytest -q reality_engine/tests/test_results_gates.py ; test_observations.py ; test_ar_sections.py ;
test_deck_guards.py - each separately, pass; 0 graded-R status change; per-rule precision >= 80% on the 20-row samples.
Stop if: a rule changes > 3% of verified rows or any graded-R row and 2 tries do not fix it: report and stop.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine (copies in .tmp); no model calls;
never kill processes by name; hard stop by 06:00 IST Fri 27 Nov (Shivam: operations stop by 08:00) - commit what passes.
Budget: ~2.5 hours, ~150 tool calls.
