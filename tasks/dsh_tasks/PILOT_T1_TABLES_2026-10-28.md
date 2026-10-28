# Task — build the pilot's deterministic (T1) tables from held data, per tasks/arch_v3/PILOT_SPEC.md

## Goal
This is step 4 of the golden rule: the pilot, built to the v3 schema. `tasks/arch_v3/PILOT_SPEC.md` splits it into:
- **T1:** deterministic tables built from held data, for its 489-ISIN universe (or wider where it's cheap);
- **T2:** reader/chunk tables for 30 ISINs.

This task is **T1 only**, into a separate pilot DB. Nothing touches the live DBs.

## Do
1. Create `.tmp/pilot/market_state_pilot.db` and `.tmp/pilot/facts_pilot.db` in this worktree, with the DDL from `tasks/arch_v3/SCHEMA_V3.sql` for these T1 tables:
   - `company_state_daily`: close, band, mcap from prices + shares; daily rows; the price_band_daily and mcap_bucket views on top;
   - `index_membership_interval`: rebuilt from the 2026-09-30 snapshot backwards, using the dated changes in `D:\RealityEngine\raw\index_history` (446 notices). Parse with `reality_engine/scripts/fetch_index_history.py`;
   - `price_band`: from `D:\RealityEngine\raw\price_bands` (1,683 daily sec_list files). Parse with `fetch_price_bands.parse_band_csv`;
   - `event_day0`: the 15:30 rule from each filing's known_at, using the trading calendar;
   - `event_leakage_window`: day0-4 … day0-1 delivery/price stats;
   - `xbrl_concept_map` (G11) + `company_metric_series`: from results_xbrl.db;
   - `company_segment_pnl`: from ar_facts segment notes, as PILOT_SPEC/SCHEMA_V3 say;
   - any other T1 table PILOT_SPEC lists that is buildable from held data.
2. Every row carries its source key and its PIT key (known_at / valid_from). **Verify dates against the filing record on the first rows** (memory rule: doc_date is crawl date, never use it).
3. **Checks** in `tasks/pilot_t1/CHECKS.md`:
   - row counts, and fill rate per column;
   - 10 hand-checked rows per table against the source;
   - index-membership spot checks: Nifty 50 members on 3 dates vs the notices;
   - band spot checks vs the raw files;
   - day0: 10 filings before and after 15:30;
   - query timings for the SCHEMA_V3 indexes.
4. **Build script:** `reality_engine/pilot/build_t1.py`. Idempotent, with `--universe pilot|all` and `--out DIR`, so the full build later is the same code.

## Rules
- Read-only on all live DBs (`connect_ro`) and on D: raw. Write only in this worktree (`.tmp/pilot/`, code, tests, `tasks/pilot_t1/`).
- No network. No commits. No chunking (that is T2, another worker).

## Acceptance checks
1. Both pilot DBs exist, with every listed table non-empty, or a written reason if a table can't be built.
2. CHECKS.md has the hand checks, with ≥95% agreement per table.
3. `python -m unittest reality_engine.tests.test_pilot_t1` passes (offline fixtures).

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_pilot_t1
```

## Report
Give:
- the per-table rows, fill and hand-check accuracy;
- the timings;
- the tables that couldn't be built and why;
- the full-universe build time estimate;
- your tool-call count.
