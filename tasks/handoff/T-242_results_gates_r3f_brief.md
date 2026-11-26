# T-242 brief: results gates r3f - OCR signs/splits, garbled values, measure from section, change vs balance (dsh DeepSeek, 27 Nov, Wolf)

Ticket: T-242
permission: workspace-write (worktree)
Base: main at/after 41ea0dae (r3d + r3e + r3d2 merged).

Goal: results ckpt_0003 (49/3/8/0) and ckpt_0004 (48/4/8/0) failed on kinds r3d/r3e do not cover. Fix notes (read first):
D:/RealityEngine/hy4_out/obs_results_fy27.db.audit/ckpt_0003.fix.md and ckpt_0004.fix.md. Packs with page_text:
C:/RealityEngine/t242/results_ckpt3/pack.jsonl and results_ckpt4/pack.jsonl (id = line number). Structural rules only, in the
results row gates of reality_engine/v2/observations.py; rows end unverified/quarantined or right, never deleted.

Evidence: ckpt_0003.fix.md and ckpt_0004.fix.md (paths above); packs results_ckpt3 / results_ckpt4 with page_text.

## Kinds (one test each from the pack row's page_text, plus a counter-test)
1. OCR brackets and split digits: '{171.56)' / '(171.56}' are brackets -> negative (ALOKINDS ckpt3); '(2 69)' / '3, 221 59' -
   digits split by one space inside a number rejoin with the decimal at the printed position (ATGL -2.69), else unverified;
   never keep the leading fragment (-2.0).
2. Garbled OCR value: a value_text with non-digit junk inside the number ('-2,1::!.J.:?.9', ARSSINFRA) -> quarantined.
3. Measure from the section: a cash-flow statement line never maps to a P&L or BS measure (AZADIND 'Extraordinary items' in
   CF -> not exceptional_items; APTUS CF 'Issue of equity shares' -> not equity_share_capital); a line under 'Non-current'
   takes the non-current measure (AAYUSH '(b) Provisions' -> long_term_provisions); a P&L charge never maps to a balance
   (BANDHANBNK provisions charge 4,131 cr).
4. Change, not balance: 'increased by / decreased by / rose by / declined by <amount>' is a movement, never the balance
   measure (HDFCAMC 'DTL ... had increased by 69.75 Crore'; also AAYUSH, BANDHANBNK) -> unverified with
   value_kind 'change' (or the existing change field if present).
5. Share-count tables: a value printed '(in Lacs)' under a share-count table keeps scale 1e5 and a count measure, never
   a rupee measure (ATMAIND preference shares 2.50).
6. Segment column + geography subset: the r3d column-position rule also applies to segment tables (AEQUS 'Aerospace'
   3,039.54 is the Q4 column, not 'Year ended'); a geography row ('India') stored as a total measure with empty segment
   -> segment/geography set, unverified (ARTEMISMED).
7. Own statement scope: a page headed with the company's own name / STANDALONE is entity_scope company (ASTRONMULT #40).

## Measure
Recheck a COPY of C:/RealityEngine/t242/results_r3d/base.db (copy into your .tmp with the sqlite backup API) with
`python -m reality_engine.v2.observations --recheck --baseline <copy> --out <out> --stores-root
C:/RealityEngine/tg_build/universe_fy27 --doc-types results` (REALITY_RAW_FETCH=0). If it cannot finish by 05:00, measure
on the pages of the ckpt3/ckpt4 packs plus 200 seeded pages only (re-run apply_results_row_gates on them). Report rows
per new rule, 0 status change on graded-R rows of results_ckpt1, results_grade_r2, results_grade_r3c, results_ckpt2,
results_ckpt3, results_ckpt4 (R = rows not named in their fix notes), 20 seeded (seed 7) rows per rule judged.

Files: reality_engine/v2/observations.py, reality_engine/tests/test_results_gates.py, docs/DEVELOPER_GUIDE.md,
tasks/t242_results_measure.md.
Accept: python -m pytest -q reality_engine/tests/test_results_gates.py ; test_observations.py ; test_ar_sections.py ;
test_deck_guards.py - each separately, pass; 0 graded-R change; per-rule precision >= 80%.
Stop if: a rule changes > 3% of verified rows or any graded-R row after 2 tries. Hard stop 05:30 IST (Shivam: operations
stop by 08:00) - commit what passes.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine; no model calls; never kill
processes by name.
Budget: ~3.5 hours, ~180 tool calls.
