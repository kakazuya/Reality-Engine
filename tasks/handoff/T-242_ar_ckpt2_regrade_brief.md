# T-242: re-grade of AR ckpt_0002 after the AR row gates (recheck copy), DeepSeek read-only, 25 Nov 2026, Eagle

Ticket: T-242

Goal: grade 60 annual-report rows strictly against the page text: rows read by the live hy4 loop (prompt fp 48d75aa69de7,
author Wolf), with 16 from audit checkpoint 2, from a copy re-checked with the merged row gates (35449f64: printed periods, report-year periods, dates never values, prose basis, consolidated scope). First grade 53/3/3/1 failed. Bar: at least 70% right and at most 5% wrong + junk.

Files:
- Rows: C:/RealityEngine/t242/regrade_ar_ckpt2/pack.jsonl, one JSON object per line. Each carries page_text: use it, and open
  the store (C:/RealityEngine/tg_build/universe_fy27/cNN/cNN.db, doc_page, read-only `file:...?mode=ro`) only for a
  neighbouring page. Row ids are the line numbers 1-60.
- You are read-only: write and commit no files. Your FINAL ANSWER carries the results.

Evidence: first grade C:/RealityEngine/t242/ar_grade_ckpt2/grades.csv (53/3/3/1: invented periods, date as value, subsidiary tag on a consolidated table); the fix is in docs/DEVELOPER_GUIDE.md (AR row gates, 25 Nov).

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
