# T-132 round 3 progress

- Done: all six round-2 defect classes fixed in `reality_engine/v2/table_cells.py` (point/bare date
  headers, no-label/no-header cells dropped, per-share/count/ratio/own-unit rows, garbled header
  dates, `;delta` difference columns, wrapped-label row joins), header phrases assigned in column
  order / nearest group heading, `build_cells.py` passes the doc type and stores `method`,
  `cell_sample.py` adds the `method` column.
- Tests: 27 in `test_v2_table_cells.py` (one per class + two real-PDF smoke tests), 38 across the
  three v2 test files, all pass.
- Final rebuild: `.tmp/v2r6` - 75,394 cells, period 95.0%, scale 78.4%, no header 0.0%
  (deck 13,902 / 82.8%, results 61,492 / 97.7%).
- Seed-11 samples: `.tmp/f_results.csv`, `.tmp/f_deck.csv`. Self-grade of the first 30 of each:
  results 27/30, deck 21/30. Deck misses: Coal India label/value off-by-one row, six-column
  value/% deck tables, garbled labels.
- Docs: contract section 10 (rules a-h + round-3 numbers + remaining families), GUIDE O22.
