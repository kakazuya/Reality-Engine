# Task — build the class-(b) pilot tables whose source data is ALREADY HELD (no fetch)

## Goal
`tasks/SCHEMA_FINAL_2026-10-29.md` (§2, §5) and `tasks/SCHEMA_FINAL_CASES_2026-10-29.jsonl` list 435 class-(b) cases: answerable once a designed table is built. The top tables by cases unblocked include:

| table | cases |
|---|---:|
| `commodity_price_daily` | 62 |
| `mkt_nse_full_daily` (bhavcopy) | 19 |
| `fno_oi_daily` | 19 |
| `company_membership_pit` | 15 |
| `industry_capacity_pipeline` | 13 |

Several have their raw source already on disk:
- the F&O bhavcopy 2019+ is fetched: `D:\RealityEngine\raw\fo_bhavcopy\`, 1,930 days;
- the commodity series: `D:\RealityEngine\raw\commodity_series\commodity_series.csv`, 22 World Bank series;
- the NSE full bhavcopy raw files: `D:\RealityEngine\raw\bhavcopy` / `raw_market`;
- the index constituents and history: `D:\RealityEngine\raw\index_constituents`, `index_history`.

Build, for the pilot scope (the 60 pilot ISINs + 30 regression ISINs in `tasks/pilot60/T2_ISINS.txt`, plus whatever market-wide rows the bank cases need), every (b) table whose source is fully held. Use the exact DDL in `tasks/SCHEMA_FINAL_2026-10-29.sql`.

## Do
1. From the cases JSONL, list the (b) tables, and for each one check whether its source is held: a raw path on D:, or a live store. Skip anything that needs a fetch or an LLM reader; just list those.
2. Build each held-source table into `.tmp/pilot_b/market_state_b.db` (market tables) or `.tmp/pilot_b/metric_state_b.db` (company metric tables), using the final DDL. Rules:
   - PIT: `known_at` comes from the source's publication or dissemination time, with the 15:30 IST day-0 rule. Never use the crawl date.
   - Every raw file on D: is read ONCE and sequentially. Never run random-access queries against D:.
3. Validate each table:
   - row counts;
   - date coverage;
   - 10 random rows hand-checked against the raw file;
   - for 5 dependent bank cases per table, show that the needed field is now present for the case's entity and period.
4. Re-classify those cases in a copy of the cases JSONL (b → a only when verified) and report the new a/b/c counts.

## Rules
- Live DBs are read-only; D: is read-only and read sequentially only. Write only inside this worktree. Use no paid models and make no commits.
- RAM is tight. Stream files; never load a whole year of F&O into memory at once.

## Acceptance checks
- `python -m unittest reality_engine.tests.test_pilot_t1` passes, plus a new `test_pilot_b_tables.py` with a schema-match test and a PIT test per table.
- `tasks/pilot_b/REPORT.md` lists per table: rows, coverage, hand check, cases moved b → a.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_pilot_t1 reality_engine.tests.test_pilot_b_tables
```

## Report
Give:
- the tables built, with rows, coverage and hand-check results;
- the cases moved b → a;
- the tables skipped because they need a fetch or a reader (with case counts);
- your tool-call count.
