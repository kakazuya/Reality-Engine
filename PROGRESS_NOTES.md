# T-132 round 4 — progress notes

- 2026-11-09 21:40 IST: Read contract 10 and the three files. Baseline rebuild `.tmp/v2r4a` reproduces round 3 exactly
  (189 docs, 75,394 cells, period 95.0%, scale 78.4%). Six round-4 classes reproduced in
  `reality_engine/tests/test_v2_table_cells.py` (5 of 6 failed on the old code; class 1 failed on the header text).
- Fixes in `reality_engine/v2/table_cells.py`: x-position header assignment (`_phrase_columns`), `Vear`/`twelve months`
  spans, POINT rows for segment/balance items, per-unit label units (realization/ARPU/RevPAR/per tonne, `in ₹`),
  `measure=` group header carried into `col_header`, garbled-label rejection. `PARSE_VERSION` -> t132-cells-4.
- Verified on the real pages: Asian Paints p7 (single date per header), HDFC AMC p13 (`Vear Ended` -> FY25),
  Havells p4 (segment assets/liabilities -> POINT), Coal India p17 (realization -> Rs scale 1),
  Indian Hotels deck p28 (`measure=EBITDA`), Coal India p19 (`St` rows gone).
- Next: rebuild `.tmp/v2r4b`, sample seed 13 (100/type), grade the first 30 of each, update contract 10 + guide O22.
- 2026-11-09 23:05 IST: final build `.tmp/v2r4d` (189 docs, 74,486 cells, period 94.9%, scale 81.9%, no header 0.0%,
  88.4 s).  Samples `.tmp/f4_results.csv` / `.tmp/f4_deck.csv` (seed 13, 100 per type).  Own grade of the first 30
  rows of each: results 27/30, deck 27/30.  Six round-4 classes have tests; 45 pass in the three v2 test files.
  Contract s10 and guide O22 updated; STATE.md left alone per the ticket.  Committing.
