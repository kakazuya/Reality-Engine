# T-242: fund_raise round 7b - restore the 9 broken R rows (DeepSeek, same session as 749d4e61; Eagle, 25 Nov 2026)

Ticket: T-242

Goal: restore 9 graded R rows broken by round 7 without losing its fresh5 fixes.

Files: reality_engine/research/filing_events.py (fund_raise paths only), reality_engine/tests/test_filing_events.py, docs/research/T-231_filing_events.md, docs/DEVELOPER_GUIDE.md. Your worktree starts from round 7 (branch dsh/20261125T052722Z-749d4e61). FIRST run `git merge main` (order_win round 7 is merged on main; on a conflict keep main's order_win code and round 7's fund_raise code) and run the tests before any change.

Evidence: round 7 (branch dsh/20261125T052722Z-749d4e61) fixes 22/22 W and 6/6 P on fresh5, but on the ROUND-5 grade set
(C:/RealityEngine/t242/events_grade_fundraise/pack.jsonl + grades.csv, stores fresh4/fresh3) it breaks 9 rows that
were graded R. Your stop rule (>25% of fund_raise rows moved on fresh4) also fired, and you carried on: next time
stop and report.

Broken R rows (id: graded reason -> round 7):
- #3 MINDACORP "Board approved NCDs aggregating up to Rs 500 crore on private placement" -> GONE
- #18 AURIONPRO "Board approved 48,134 shares at Rs 1454.30 = Rs 7,00,01,276.2 preferential" -> GONE
- #50 AURIONPRO "allotted 48,134 shares at Rs 1454.30" -> GONE
- #24 EFCIL "Board approved 19,99,996 shares at Rs 270 = Rs 53,99,98,920 to Ultrafresh sellers" -> GONE
  (a share swap is the company issuing its OWN shares: an issuance, not an acquisition veto)
- #47 KPIGREEN "allotted 1,01,00,000 warrants at Rs 470.30 = Rs 475,00,30,000" -> GONE
- #17, #22, #41, #45 (RATNAVEER, MANAKCOAT) "conversion allotment ...; 75% balance printed Rs X" -> scaled x4/3.
  The graded rule: a warrant conversion stores the 75% balance PRINTED in the filing, never a computed 100%.

Steps:
1. Find which new rule drops or rescales each row: `_RAISE_FOREIGN_ISSUE_VETO`, `_raise_family_ok`,
   `_raise_count_size` or `_RAISE_BALANCE_CLAUSE`. Narrow it structurally:
   - the issuer veto fires only when the security's issuer is ANOTHER named entity;
   - "of the Company", or allotment to sellers or investors as consideration, is the company's own issue;
   - a printed balance amount wins over count x price.
2. Re-measure all three sets into new .tmp files. Report:
   - (a) the 9 rows above;
   - (b) every round-5-graded row (60) and every fresh5-graded row (60) whose amount, stage or presence changed;
   - (c) fund_raise rows moved vs r6 on fresh4/fresh3.
3. Update the round-7 docs section with the corrected numbers.

Accept: all 9 rows back to their graded value; fresh5 still at least 18/22 W fixed and 0 R broken; order_win
rows identical to C:/RealityEngine/t242/orderwin_r7d/events_r7d_fresh{5,4,3}.db; test_filing_events.py passes.
Stop if: a fix for one of these rows re-breaks a fresh5 fix twice. Report it, don't trade.
Budget: about 2 hours; worktree only.
