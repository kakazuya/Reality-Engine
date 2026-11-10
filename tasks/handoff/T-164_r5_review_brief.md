Ticket: T-164
Goal: independent read-only review of the T-164 call-statements branch Eagle-T164-statements (head 340a981f, rounds 1-5 by Beam; you did not write it). Grade strictly; do NOT edit any code. Merge rule (Shivam): zero earlier-right rows lost. Controller already ran tests: transcripts 7, speakers 8, kpi 114, no_company_literals 7, lookups_pilot3 34: all pass.
Evidence: worktree R = C:/Users/warri/Downloads/IDM-worktrees/Eagle-T164-statements (read-only for you). Rebuilt stores R/.tmp/t164/u8.db, q12.db; main-code baseline R/.tmp/t164/main_u8.db, main_q12.db. Round 3's grader found 64.5% entity precision and 5,295 changed speaker/role/section rows; round 4 matched the baseline; round 5 tightened entities (persons out, longest span, single-word rules) but reported NO precision number. The controller's own sample of 20 round-5 rows: ~15 right; wrong ones include "Balraj Menon" (an inline speaker label "Balraj Menon:" at the start of a statement), "RM", "AC", "JV", "US". Ticket text: R/tasks/handoff/T-164_statements_brief.md.
Steps:
1. Baseline: per symbol, compare transcript_statement in R/.tmp/t164/{u8,q12}.db vs main_{u8,q12}.db on (count, speaker, role, section, statement text). Must be identical; list any difference.
2. Entity precision on your own sample (seed 9164): 50 statements with entities per store; grade every entity right (programme, project, brand, place, counterparty, regulator, product) or wrong (person, generic word, fragment, metric abbreviation). Report precision per store with the table.
3. Recall: 25 statements per store with empty entities that name a capitalised product/place/counterparty; count misses.
4. Topics: 40 statements per store with a non-'other' topic; precision per store; 'other' share per store.
5. Lookups: run plugins/reality-data/server/lookups_pilot3.py statements() against R/.tmp/t164 stores for BEL entities=NGC, DLF entities=Dahlias, IDEA entities=BSNL, SAIL terms=safeguard whole_turn=True, analyst_questions for ANANDRATHI over 4 calls; paste 2 rows each.
6. Diff check: git diff main...HEAD for company or person names in code.
Files: none written by you (read-only; scripts via python - on stdin; open sqlite with file:...?mode=ro).
Accept: final answer holds the baseline verdict, entity precision per store with graded table, recall misses, topic precision and 'other' share, lookup rows, diff findings, and MERGE (baseline identical AND entity precision >= 85% per store AND topic precision >= 85%) or SEND BACK with top 3 fixes.
Stop if: you would need to change code to judge something; say so.
Budget: <=100 tool calls. Do not edit tasks/STATE.md. Do not write D:/.
