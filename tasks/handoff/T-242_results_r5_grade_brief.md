Goal: strict re-grade of 60 VERIFIED number rows from the quarterly-results pilot after the results-page gates (merge 0bb304f6). The first grade failed 33/12/6/9. These 60 rows are new: none was in the first pack. A pass opens results reading in bulk. T-242.
Evidence: pack C:/RealityEngine/t242/results_pilot/r5_grade/pack.jsonl (60 lines; also pack_part00/01); each line has the row plus page_text and previous_page_text. Rubric: docs/grading/number_rubric.md (read it first; grade by the rubric: one wrong or missing minor field is P; W is a value that is not the printed figure, the wrong period column, the wrong entity, or a scale error that changes the number's size).
Steps:
1. Find each value in page_text (previous page for headers). Results filings print quarter, previous quarter, year-ago quarter, half-year/year-to-date and full-year columns: confirm the stored period by recomputing a total or growth wherever possible.
2. Basis: the stored basis must be the table the value sits in (standalone or consolidated).
3. Unit and scale from the printed unit line.
4. Grade R / P / W / J.
Accept: final answer = one CSV block "n,grade,reason" with 60 lines, then counts R/P/W/J, the W and J kinds with row numbers, and how many periods were checked by arithmetic.
Stop if: a row's page text is empty: grade J "page not found" and go on. Never write a file.
Files: none written (read-only).
Budget: 60 minutes.
Ticket: T-242
