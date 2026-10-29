# Task — ask_match round 2B: market, holding and narrative concepts must reach the rows

## Goal
Gate run on main (`3489a87`, strict 5.1%): the second group of ask_match failures:

**Market data:**

| concept | cases |
|---|---:|
| range (high/low) | 96 |
| volume | 76 |
| delivery | 53 |
| valuation | 56 |
| band (price band) | 24 |

**Holdings:**

| concept | cases |
|---|---:|
| promoter | 66 |
| pledge | 27 |
| public_holding | 23 |

**Narrative/event:**

| concept | cases |
|---|---:|
| acquisition | 58 |
| products | 32 |
| facilities | 32 |
| audit | 31 |
| lag | 31 |
| listing | 27 |

Plus **307** cases where no concept was identified ("?": too few key terms).

Market and holding data is held:
- prices, delivery and bands in the live DBs plus `mkt_nse_full_daily` (`reality_engine/data/pilot/pilot60/market_state_b.db`);
- the shareholding index `shp_index` and SAST/pledge tables in `equity_intelligence.db`;
- P/E, P/B and market cap from `company_state_daily`.

Narrative concepts live in the chunk store (`reality_engine/data/pilot/pilot60/chunks_v3_pilot.db`: 2,488 docs and 108 k chunks, now uncapped) and in announcements.

## Do
1. For each concept, take 5 failing cases and find why the returned rows lack the concept:
   - an empty window after the period fix;
   - the wrong planner;
   - the row doesn't name the field;
   - EVIDENCE ranks an unrelated passage.

   Fix the route, so SERIES/SCREEN return the field labelled, holding asks read `shp_index` for the asked quarter, and narrative asks rank chunks_v3 passages that actually contain the concept (with the doc type/section matched to it: acquisitions → announcements/AR, facilities → AR/deck, auditor → AR/announcements).
2. The 307 "?" cases: improve the decomposer, so the ask's key concept is recognised. Use the master-bank `template`/`family` fields as a hint. Report how many now map to a concept.
3. Tests for each family, and a wrong-concept row still failing.
4. Re-run the full bank in 100-case chunks, one bench process at a time (`gate_run.py bank --resume --chunk 100`, then `hand60`, `grade`, `report`). Report the before/after per concept, the strict total, and a 20-row hand-check precision.

## File scope
Allowed: `planners/series.py` (field labelling only, not the period code), `planners/screen.py`, `planners/evidence.py` (ranking only), the decomposer and concept detection in `router.py`, and tests.

Do NOT touch:
- `planners/facts.py`, `metrics.py`, `compute.py` (the financials worker owns those);
- `event.py`, `ripple.py`;
- the checks in `gate.py`.

## Rules
- Pilot DBs come from the SSD paths only; never read D:. Live DBs are read-only. Use no paid models and no LLM in the query path, and make no commits.

## Acceptance checks
- `python -m unittest discover -s reality_engine/tests -p "test_query_*.py"` passes.
- The ask_match failures on these concepts fall by ≥50%, hand precision is ≥80%, and there are 0 PIT breaches.

## Test command(s)
```bash
python -m unittest discover -s reality_engine/tests -p "test_query_*.py"
```

## Report
Give:
- the per-concept before/after;
- the "?" mapping rate;
- the strict total;
- the precision;
- what's left;
- your tool-call count.
