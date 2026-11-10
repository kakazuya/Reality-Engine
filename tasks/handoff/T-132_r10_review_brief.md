Ticket: T-132
Goal: independent review of T-132 round 10 of the v2 table-cell builder (another worker wrote it; you did not). Grade strictly, do NOT edit code. Branch dsh/20261110T041508Z-c1d00b5c; its store is copied to D:/RealityEngine/v2/p20_r10 (company/<ISIN>.db table table_cell), samples and replay script in D:/RealityEngine/v2/review/samples (f10_results.csv, f10_deck.csv, replay_r10.py, replay_r10.csv).
Evidence and steps:
1. Standard: read D:/RealityEngine/night_loop/opus/briefs/t132_r8_grade.md (grading standard and classes) and the r9 grades D:/RealityEngine/v2/review/T-132_r9_opus_grades.csv + T-132_r9_replay_check.md.
2. Part A: grade rows 50-79 (0-based, iloc[50:80]) of f10_results.csv and f10_deck.csv (60 rows) against page text in D:/RealityEngine/p20/p20new.db doc_page (window ~800 chars around the label; never a whole page). RIGHT only when leaf label (no wrong parent), measure, period (column and kind: quarter/half/year/point), value, unit and scale are all right; 'label_parent' when only the parent is wrong. r9 scored results 21/30 strict, deck 22/30.
3. Part B: the worker claims 179/179 earlier right rows kept (r5-r9) including parents. Do not trust replay_r10.csv: independently check every r9 replay-check problem row (r6 deck 73 parent, r5 results 64 "As a % of Total revenues", Bharti "Africa"/"India" parents) and 25 random right rows from the r5-r9 grade files against p20_r10.
4. Part C: Adani deck p49 (balance rows as points), p33/p42/p43 (Total cells unit MMT, no dash cells), Bharti results p3/p34 (no invented years), Titan results p19 year column. Sample 10 cells.
Files: you are read-only; put everything in your final answer.
Accept: final answer: Part A table (sample,row,grade,class,note) with strict/lenient counts, lost rows list, Part C verdict, merge / send back with top 3 fixes.
Stop if: judging needs code changes; say so.
Budget: 1.5 hours, <=80 tool calls. Do not edit tasks/STATE.md. Do not write D:/.
