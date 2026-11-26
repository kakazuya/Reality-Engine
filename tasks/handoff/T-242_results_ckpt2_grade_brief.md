# T-242: grade of results audit ckpt_0002 (live loop, r3c gates), agy Hydrogen high read-only, 26 Nov 2026 (Wolf runs, Eagle records: Wolf authored the results gates)

permission: read-only

Ticket: T-242

Goal: grade 60 quarterly-results rows (60 companies, verified rows only, seed 3127) strictly against the page text,
from the copy C:/RealityEngine/t242/results_r3c/after.db rechecked with results gates r3c. ckpt_0001 failed 40/20/0/0
(flow periods without a duration); r2 copy failed 28/23/8/1. Bar: at least 70% right and at most 5% wrong + junk.
Periods: a flow line (P&L, cash flow, OCI) must carry the duration its column header prints (Quarter / Half year /
Nine months / Year ended <date>); a bare date on a flow line = P; a wrong duration (quarter label on the year column,
'Year ended' on a half-year date) = W.

Files:
- Rows: C:/RealityEngine/t242/results_ckpt2/pack.jsonl, one JSON object per line. Each carries page_text: use it, and open
  the store (C:/RealityEngine/tg_build/universe_fy27/cNN/cNN.db, doc_page, read-only `file:...?mode=ro`) only for a
  neighbouring page. Row ids are the line numbers 1-60.
- You are read-only: write and commit no files. Your FINAL ANSWER carries the results.

Evidence: past failure kinds: C:/RealityEngine/t242/results_grade_r2/fix.md (subsidiary scope on own statement, cash-flow
adjustments as P&L lines, non-current as current, consolidated on a standalone-only filer, statute numbers).

Steps:
1. Grade each row R / P / W / J strictly. Name the row label and the column header the value sits under.
   - The value is printed in that row, under that column. The column's period matches `period`.
   - The measure is exactly the printed line, not a broader or narrower one: a subset line stored as the total = W.
   - The unit and scale are right (lakh, crore, million); check them against the page's "(in ...)" note.
   - basis (standalone / consolidated) matches the page heading.
   - entity: the company's own figure, not a subsidiary's or an associate's unless segment or entity says so.
   - Grades: a wrong value, column, period, measure or entity = W. A missing unit or basis when one is printed = P.
     A page number, note number or year stored as a value = J.
   - Watch for a layout where the value is printed BEFORE its label; use the arithmetic (totals, growth %) to
     confirm the column.
2. Final answer, part 1: a CSV block with columns id,grade,reason (reason: the row label and column header checked),
   60 lines.
3. Final answer, part 2: counts R/P/W/J, and the 3 commonest failure kinds.

Accept: the final answer holds 60 CSV lines with grades in {R,P,W,J} and the counts.
Stop if: a page cannot be found (grade it J "page not found" and go on). Never write a file.
Budget: about 90 minutes; read-only.
