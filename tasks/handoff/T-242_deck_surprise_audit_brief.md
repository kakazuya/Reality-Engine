# T-242 surprise audit: strict grade of 60 verified deck numbers outside every checkpoint (DeepSeek, read-only, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: the deck checkpoints passed (55/4/0/1, 54/6/0/0, 57/1/2/0), but they sample near each checkpoint. This audit
grades 60 verified deck numbers drawn from the WHOLE live deck run, excluding every checkpoint row, to find defects
the checkpoints miss (Shivam: surprise audits once fixes are done).

Files:
- Rows: C:/RealityEngine/t242/audit_deck1/pack.jsonl, one JSON per line (49 companies, at most 2 per company).
  Fields: id, observation_id, symbol, doc_key, page, measure, printed_label, value, value_high, unit, period,
  basis, segment, entity_scope, value_text, store_db.
- Page text: the row's store_db (a SQLite file), table doc_page(doc_key, page, text). Open it read-only
  (`file:<path>?mode=ro`, uri=True). Read the row's page; read the page before it when a heading or unit note sits
  there.
- You write NO files. Your final answer carries the results.

Evidence: the last deck checkpoint's W were an order-book aircraft count stored as fleet size, and a single site's
facility count stored as the company's plant count. Its P was a subsidiary's figure with an empty segment.

Steps:
1. Grade each row strictly R / P / W / J against the page:
   - value (and value_high for a range) as printed, with unit and scale (crore, lakh, million, %, bps);
   - period: the column or label the figure sits under;
   - measure fits the printed label: not a broader or different line;
   - entity: a subsidiary's, segment's, industry's or peer's figure must say so (entity_scope or segment);
   - basis: standalone/consolidated where the page states it.
   Grade W for a wrong value, wrong period, wrong measure, or an outside entity's figure stored as the company's.
   Grade P for a right value with a missing or wrong unit, scale, basis or segment. Grade J for a non-figure (page
   number, year, footnote marker, date) or a duplicate of another pack row.
2. Final answer, part 1: a CSV block with columns id,grade,reason (reason: one short line naming the printed words
   checked), 60 lines.
3. Final answer, part 2: counts R/P/W/J, and the 3 commonest failure kinds with their row ids.

Accept: 60 CSV lines with grades in {R,P,W,J}, plus the counts.
Stop if: a page cannot be found (grade it J "page not found" and go on).
Budget: about 90 minutes; read-only.
