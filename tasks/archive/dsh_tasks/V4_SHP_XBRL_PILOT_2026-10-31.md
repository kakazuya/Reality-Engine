# Task — shareholding XBRL for the 60 pilot names: FII, DII, MF and pledge

## Goal
The v4 store holds `hold.pct` for promoter and public only, because `equity_intelligence.shp_index` has only those two columns. Questions on DII, MF, pledge and FPI return NOT IN DATA. `shp_index` has `xbrl` and `file` columns. Fetch and parse the filings for the 60 pilot names so those classes can be answered. Read `tasks/dsh_tasks/V4_COMMON_2026-10-31.md`.

## Work
1. Look first for an existing shareholding fetcher or parser in the repo (`mcp__code-intel__symbols`, grep for `shp_index`). Reuse it if there is one. Measure what `xbrl` and `file` hold for the 60 names, and which quarters from 2024-04-01 on have a link. Names in `tasks/pilot60/UNIVERSE.csv`; match through `symbol_isin_history` because many filings carry an older ISIN.
2. Fetch those filings at a measured polite rate. Raw files go to `.tmp/shp_xbrl_raw/` in your workspace; report the folder so the controller can move it to `D:\RealityEngine\raw`. A rerun must skip what it has.
3. Parse into `.tmp/shp_xbrl_pilot.db`, one row per ISIN, quarter and holder class, with atoms in the same form as the `fact` table: `hold.pct` with `holder_class=fii|dii|mf`, plus a pledge atom named after the design's list. Keep promoter and public as a cross-check, not as new facts.
4. `known_at` is the filing's `broadcast_at`, falling back to `submission_date`. Never a crawl date, and never `quarter_end`. A revised filing is its own row with its own `known_at`, so the original stays usable before the revision.
5. Tell apart a class the filing reports as zero from one it does not report. Never turn a missing value into 0.

## Limits
- 60 pilot names only. No full-market fetch.
- Do not write to `reality_engine/data/` or install anything. Do not change the `fact` store, `fact_view*.sql` or `shp_index`.
- No paid models. If the network or a source blocks you, report the exact error and stop that part; do not switch to another source without saying so.

## Acceptance checks
- Coverage table: for each of the 60 names, quarters expected, fetched, parsed; each gap has a reason.
- Promoter and public from XBRL match `shp_index` on every row where both exist; list each mismatch.
- 20 rows by a committed seed checked against the raw file by re-reading it with separate code from the parser, with the classes shown.
- Tests pass on a small committed fixture, including revised filings, a zero and a missing class.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_shp_xbrl.py -q
```
Create that test file.
