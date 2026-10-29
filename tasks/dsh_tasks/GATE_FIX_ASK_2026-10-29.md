# Task — gate blocker #1: route each asked concept to the planner and field that holds it (~1,060 cases fail ask_match)

## Goal
The first honest gate run (`tasks/answer_bench/GATE_RUN_2026-10-29.md`, §4) failed these cases:
- **880** on GATE ask_match: no returned row carries the asked concept;
- **127** with too few key terms of the ask;
- **54** where no planner produced evidence for the ask.

The 40-row precision sample shows the patterns:
- technical-study asks (drawdown recovery, RSI divergence, share of days near the high) answered with generic 1-year price stats;
- two-part asks that omit one part (an equity share count, the exchange on a YTD high);
- narrative asks answered with an unrelated passage.

Do not loosen the gate. Make the answers carry the asked concept.

## Do
1. From `tasks/answer_bench/GATE_RESULTS_*_strict.jsonl`, cluster the ask_match failures by the asked concept, using the decomposer's slots and the master-bank family/template fields. Rank the clusters by case count.
2. For each top cluster (work down until ~80% of the 1,060 are covered), do one of:
   - (a) the concept is held. Map it to its table/field: the T1 tables in `reality_engine/data/pilot/pilot60/{market_state_pilot,facts_pilot}.db` (`company_state_daily`, `company_metric_series`, `company_segment_pnl`, `event_day0`, `company_membership_pit`, `company_sector_pit`), `xbrl_concept_map`, the live stores, the chunk store. Add the routing so the planner returns that field.
   - (b) the concept needs a computation over held data (RSI, drawdown recovery, days near the high, CAGR, multi-part asks). Add a deterministic compute in the planner, or in `reality_engine/query/metrics.py` if it exists, else `compute.py`.
   - (c) the concept is genuinely not held. Return an explicit NOT IN DATA with the reason, which the gate accepts only when the data truly doesn't exist.
3. Multi-part asks: every part must be answered or explicitly marked missing. Never drop one silently.
4. Extend `ASK_CONCEPTS`/aliases in `gate.py` only for real synonyms; never to make a wrong row pass. Add tests: a right-concept row passes, a wrong-concept row still fails.
5. Re-run the bank in 100-case chunks, one bench process at a time: `python tasks/pilot60/gate_run.py bank --resume --chunk 100`, then `grade`, then `report`. Report the before/after for each cluster and the new strict ANSWERED total. Then hand-check 20 newly ANSWERED rows against their source rows and report precision.

## File scope
Allowed: `gate.py` (aliases only), the concept-routing/decompose parts of `router.py`, a new `reality_engine/query/concepts.py`, compute helpers, the field-selection code in planners, and tests.

Do NOT touch the period-filter code in `router.py` or the planners; another worker owns those.

## Rules
- Pilot stores: SSD paths only (`C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot\...`). Never read DBs from D:.
- Live DBs are read-only. Use no paid models and no LLM in the query path, and make no commits.

## Acceptance checks
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` passes.
- The ask_match failures fall by ≥50%.
- Hand precision on the 20 newly answered rows is ≥80%.
- 0 PIT breaches.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the clusters with counts and how each was handled (a/b/c);
- the before/after;
- the new strict ANSWERED total;
- the 20-row precision;
- what's left;
- your tool-call count.
