# Progress — T-033 (v4 engine routes each measure to its store)

- 2026-11-02: read the context pack, GATE_STATE, the Claude grade, the 8 acceptance bank rows
  and the v4 executor/run/decompose. Probed the live stores: `price.close` has no basis dim and
  no `raw_close` column exists in the live T1 store (the brief's premise is stale); the printed
  panel `equity_intelligence.daily_price_delivery` + `mkt_bse_*` holds the traded close and BSE
  delivery the fact view lacks.
- Implemented: `execute.measure_mismatch` (negated measure, split-of-a-total), `traded_close`,
  `panel_delivery`, `exchange=sum` completeness, named-dates -> series, summed source naming;
  `run.Stores.market` (third read-only connection, `mode=ro`). New test 8 rows pass; 224 v4 tests
  pass. Bank run written: 153 rows, 29 answered, 124 refused (reason counts in the answer file).
- Docs: QUERY_V4_DESIGN.md §D.1.1/§D.1.2, GATE_STATE and GATE_V4_LABELS corrected. tasks/STATE.md
  left alone: the brief forbids touching it (controller adds the fact).
- Next: controller merges; the narrative-ask-with-no-topic residue and the judgement/forecast
  typed-unmapped half of queue item 3 remain open.
