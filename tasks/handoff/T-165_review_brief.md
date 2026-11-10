Ticket: T-165
Goal: independent review of the T-165 answer-routing branch (another worker wrote it; you did not). Grade strictly and do NOT edit code. Branch dsh/20261110T050415Z-01031c79, worktree R = C:/Users/warri/Downloads/IDM-worktrees/20261110T050415Z-01031c79 (read it; its re-ask is R/.tmp/t165/reask.md and reask.py).
Evidence and steps:
1. Read the brief tasks/handoff/T-165_routing_brief.md and the audit rows (D:/RealityEngine/reports/2026-11-10_held_not_queryable_audit.csv, miss_reason tool_routing). The worker claims 12/12 right (u8 rows 14,21,22,23,24,26,27,35; q12 rows 45,65,66,89).
2. Re-run each question yourself through R/plugins/reality-data/server/lookups_pilot3.py (python with sys.path set to R, read-only stores D:/RealityEngine/u8/u8.db, q12/q12.db, as_of from the audit row) and compare with the audit value and the page quote. Do not trust reask.md.
3. Check the holding change for regressions: for 5 companies across p20/u8/q12 call holding(symbol, as_of) at two past dates; confirm promoter/public values equal what main's holding() returned (run main's lookups_pilot3.py from C:/Users/warri/Downloads/Info_Diffusion_Model the same way), that no category is duplicated, that "anchors on the latest quarter with an XBRL filing" never returns a quarter filed after as_of, and that GoI/FPI/MF words route right.
4. KPI words: net interest margin, credit cost, cost of funds/borrowings resolve to the right metric for CHOLAFIN and one other lender; held_quarantined never returns a quarantined value as the answer.
Files: you are read-only; put everything in your final answer.
Accept: final answer: per question right/wrong with value and source; regression table (company, date, main vs branch); verdict merge / send back with exact fixes.
Stop if: you would need to change code to judge; say so.
Budget: 1 hour, <=60 tool calls. Do not edit tasks/STATE.md. Do not write D:/.
