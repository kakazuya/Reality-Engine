# T-242: strict milestone grade of 60 annual-report rows after the statement gate (DeepSeek, read-only, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: grade 60 VERIFIED annual-report number rows strictly against the page text. They come from the 200-page AR
pilot, re-parsed after the statement gate: lines that XBRL holds are now unverified, while segment, contingent,
related-party and operating figures stay verified. None of these 60 was in the earlier graded sample. The grade
checks whether the gate fixed the failure on rows it was not tuned on (bar: at least 70% right and at most 5%
wrong + junk).

Files:
- Rows: C:/RealityEngine/t242/ar_grade_fresh/pack.jsonl, one JSON object per line. Its fields are id,
  observation_id, symbol, doc_key, page, record_type, measure, printed_label, printed_axis, value_text, value,
  value_high, unit, scale, period, basis, segment, geography, product, entity_scope, series_title, statement,
  status and status_reason.
- Page text: find the store holding doc_key under C:/RealityEngine/tg_build/universe_fy27/cNN/cNN.db, table
  doc_page(doc_key, page, text). Open it read-only (`file:...?mode=ro`).
- You are read-only: write no files. Your FINAL ANSWER carries the results.

Evidence: the earlier strict grade of this pilot was 42/8/10/0. Its 6 W were subset lines stored as headline
statement measures, for example one bank balance stored as cash and cash equivalents.

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
