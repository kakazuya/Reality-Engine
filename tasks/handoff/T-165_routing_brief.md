Ticket: T-165
Goal: 11 audit questions failed although the table already held the answer. Fix the reality-data tools and the answer brief so they answer. Scripts only; no company lists.
Evidence and steps:
1. Read the audit D:/RealityEngine/reports/2026-11-10_held_not_queryable_audit.csv rows with miss_reason tool_routing (15 rows; 11 are this ticket) and D:/RealityEngine/night_loop/opus/held_audit/summary.md section 4.
2. Holding: shp_category holds FPI and mutual-fund rows for u8 and q12 (categories fpi_total, mutual_funds), yet pilot3_holding answered only promoter/public. Make pilot3_holding return every category row for the quarter (promoter, public, mutual_funds, fpi_total, insurance, government ...) with pct and basis, and accept a category filter.
3. Government: Vodafone Idea (IDEA) GoI holds 49% under category central_government_or_president_of_india; pilot3_holding must return it and map "government", "GoI" to that category.
4. Duplicate promoter rows per quarter (index copy + XBRL parse): return one value per category and quarter (XBRL first, as queries.shp already orders).
5. Lender KPIs: Cholamandalam NIM, credit cost and cost of funds are now in kpi_series; check pilot3_kpi finds them by the words investors use (NIM, net interest margin, credit cost, cost of funds) and fix the matching if not. Note the audit's Chola NIM Q4FY26 = 0.68 scale defect: report it (do not fix the store).
6. Answer brief: find the standard answer brief text (grep the repo for "strict as_of" in tasks/ and reality_engine/; the T-156 round-4 brief carries it) and add one routing line per fixed class.
7. Re-ask: run each of the 11 questions through the tools (python calls to the lookup functions, read-only stores, as_of from the audit row) and record the answer and its source row.
Files: plugins/reality-data/server/lookups_pilot3.py, plugins/reality-data/server/server.py (tool descriptions), plugins/reality-data/tests/test_lookups_pilot3.py, reality_engine/pilot3/queries.py if needed, the answer brief file, docs/DEVELOPER_GUIDE.md, docs/PILOT3_BLUEPRINT.md.
Accept: (a) python -m pytest -q -p no:cacheprovider plugins/reality-data/tests/test_lookups_pilot3.py passes with a test per step; (b) .tmp/t165/reask.md: the 11 questions, tool call, answer, source row, right/wrong vs the audit value (target 11/11); (c) docs; (d) exact tool-call count. The controller restarts the MCP server after merge.
Stop if: a fix needs a company list.
Budget: 2 hours, <=90 tool calls, <=20 before first edit. Commit your work. Do not edit tasks/STATE.md. Do not write D:/. Do not commit PROGRESS_NOTES.md.
