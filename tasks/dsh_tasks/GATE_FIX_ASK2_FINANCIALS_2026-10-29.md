# Task — ask_match round 2A: company-financial concepts must reach the FACTS rows

## Goal
Gate run on main (`3489a87`, strict 5.1%): **1,324** cases fail "no row carries the asked concept" and **310** fail "too few key terms". Clustering by concept, the company-financial ones lead:

| concept | cases |
|---|---:|
| revenue | 141 |
| margin | 114 |
| order_book | 82 |
| working_capital | 68 |
| capex | 65 |
| guidance | 63 |
| capacity | 61 |
| segment | 51 |
| roic | 35 |
| net_npa | 30 |
| loan_growth | 29 |
| ebitda | 27 |
| cfo | 25 |
| dividend | 53 |

These fields are largely **held**:
- `results_xbrl.db` facts with `xbrl_concept_map` (110 concepts) in `reality_engine/data/pilot/pilot60/facts_pilot.db`;
- `company_metric_series` (1.06 M rows);
- `company_segment_pnl`;
- the extraction store `reality_engine/data/pilot/pilot60/extract_pilot60.db`: order book, capacity, capex, debt mix, cost structure, operating metrics;
- `ar_facts.db`, which now has the `ar_facts_isin_filed` index;
- concall guidance in `concall_facts.db`;
- deck figures.

So the failure is routing and row-labelling in `planners/facts.py` and `reality_engine/query/metrics.py`, not missing data.

## Do
1. For each concept above, take 5 failing cases from `tasks/answer_bench/GATE_RESULTS_*_strict.jsonl`. Find where the held value lives for that ISIN and period. Then make FACTS fetch it and return a row whose `item`/`concept` names the concept, with the period, ISIN and source.
   - Derived ratios are computed deterministically from held components: margin = EBITDA or PAT ÷ revenue; ROIC; working capital = inventory + receivables − payables; CFO; dividend per share. Add these to `compute.py`.
   - Banks: net NPA and loan growth from the XBRL bank schedules.
2. When the concept is truly absent for that ISIN and period, return an explicit NOT IN DATA with a reason. Never return an unrelated row.
3. Tests: one right-concept row passing per concept family, and a wrong-concept row still failing.
4. Re-run the full bank in 100-case chunks, one bench process at a time (`gate_run.py bank --resume --chunk 100`, then `hand60`, `grade`, `report`). Report the before/after per concept and the strict total. Hand-check 20 newly ANSWERED rows against their source rows.

## File scope
Allowed: `planners/facts.py`, `reality_engine/query/metrics.py`, `compute.py`, and their tests.

Do NOT touch:
- `gate.py` checks;
- the period code, `series.py`, `screen.py`, `event.py`, `ripple.py` (other workers own those).

## Rules
- Pilot DBs come from the SSD paths only; never read D:. Live DBs are read-only. Use no paid models and no LLM in the query path, and make no commits.

## Acceptance checks
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` passes.
- The ask_match failures on these concepts fall by ≥50%, hand precision is ≥80% on the 20, and there are 0 PIT breaches.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the per-concept before/after;
- the strict total;
- the precision;
- what's left, and why;
- your tool-call count.
