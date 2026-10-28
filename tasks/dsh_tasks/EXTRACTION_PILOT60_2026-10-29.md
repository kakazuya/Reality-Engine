# Task — targeted fact extraction (build time) for the pilot-60 universe: operating metrics, segment P&L, cost structure, order book, capacity/capex, price revisions, debt mix, rating actions, supplier/customer links

## Goal
Most remaining partial answers lack these facts as tables. Extract them **once, at build time**, so queries stay plain SQL and under 10 s. DeepSeek reads **only the targeted passages**, never whole documents:
- passages are chosen by keyword + chunks_v3 section/tag;
- no embeddings yet; Shivam's ruling is embeddings later, once, after the gate.

## Inputs
- The pilot-60 universe: `tasks/pilot60/UNIVERSE.csv` (from worker b384c636 once merged; otherwise `reality_engine/pilot/universe60.py`).
- Chunks: `D:\RealityEngine\pilot\chunks_v3_pilot.db`, plus the pilot-60 chunk store if merged.
- The target DDL from `tasks/arch_v3/SCHEMA_V3.sql`: `company_operating_metric`, `company_segment_pnl`, `company_cost_structure`, `order_intake`/`order_contract`, `capacity_util`/`capex_project`, `price_revision`, `debt_mix`, `rating_action`, `supply_link`. Add any that are missing, additively.

## Do
1. **Targeting:** for each table, a deterministic passage selector (section tags, headings, keyword sets, number patterns). Report the passages selected per doc and the tokens to be read.
2. **Extraction:** DeepSeek through the repo's existing free reader path, the one the AR/deck pipelines already use, so there is no new paid path.
   - Strict JSON schema per table; every value carries doc_id, page, a quote of ≤25 words and known_at.
   - Deterministic validation: units, magnitudes, and the period vs the doc date. Reject anything that doesn't validate.
   - If no free model path is available inside the sandbox, build the selectors, the schema and the validator, and run the regex-extractable subset (order wins, rating actions and price revisions from announcement headlines and text). Write the exact command for the controller to run the model pass.
3. **Hand check:** 15 rows per table against the source page, for precision. Recall: for 20 doc×table pairs, does the selector find the passage holding the fact?
4. Write into `.tmp/pilot60/extract_pilot60.db`. Then re-run the master-bank cases that the CASE_MAP says need these tables, through the query layer, and report before/after.

## Rules
- Read-only on live DBs and D:. Write only in this worktree. No network except the free model path. No paid models. No commits.

## Acceptance checks
`tasks/pilot60/EXTRACTION_REPORT.md` with, per table:
- the rows;
- precision (≥0.90 target) and recall;
- the tokens read vs the whole-doc tokens;
- the before/after on the dependent cases.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_extraction_pilot60
```

## Report
Give:
- the per-table results;
- the token savings;
- the case lift;
- the controller command for the model pass, if it wasn't runnable;
- your tool-call count.
