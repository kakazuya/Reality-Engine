# Task — extend pilot index membership to every index in the notices, plus pre-FY23 share counts

## Goal
The merged pilot T1 build (`reality_engine/pilot/build_t1.py`; DBs at `D:\RealityEngine\pilot\`) has two gaps:
- **`company_membership_pit` holds only 3 indices** (nifty50, nifty100, niftymidcap150). The master bank asks about Nifty 500, Smallcap 250, Midcap 100, Next 50, Bank, IT, PSU Bank, sector and thematic indices. The 446 notices in `D:\RealityEngine\raw\index_history` cover many more.
- **mcap is NULL before FY23**, because XBRL paid-up capital is the only share-count source in use.

## Do
1. Parse every index named in the 446 notices: additions, exclusions and effective dates. Rebuild intervals backwards from the latest constituent snapshot for each index.
   - If no snapshot is held for an index, check `D:\RealityEngine\raw\index_history` for the constituent CSVs (`ind_<slug>list.csv`).
   - If neither exists, record the index as `changes_only`, with pit_conf < 1.
2. Count members per index on 3 dates and check them against the official size (50, 100, 150, 250, 500 and so on). Write the table to `tasks/pilot_t1/INDEX_COVERAGE.md`.
3. Find a held source for share counts before FY23. Candidates:
   - shareholding pattern totals (`shp_index` or equivalent);
   - the bhavcopy market cap;
   - corporate actions (splits/bonus) applied backwards from the first XBRL count.

   Use the best one. Fill mcap for 2019–2022, with `shares_source` and pit_conf. Hand-check 10.
4. Rebuild into `.tmp/pilot/` with `build_t1.py --universe pilot`. Keep it idempotent, and keep the tests passing. Add tests for multi-index parsing.

## Rules
- Read-only on live DBs and D:. Write only in this worktree. No network. No commits.

## Acceptance checks
1. Membership covers at least 15 indices, with size checks within ±1 of the official size where a snapshot exists.
2. mcap fill before FY23 ≥ 80% for the pilot universe, or a written reason.
3. `python -m unittest reality_engine.tests.test_pilot_t1` passes.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_pilot_t1
```

## Report
Give:
- the indices covered, with their size checks;
- the mcap fill before and after;
- your tool-call count.
