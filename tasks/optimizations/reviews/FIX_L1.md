# Task — fix the L1 market-lookup review defects

## Goal
Fix every defect the independent reviewer found in `lookups_market.py` and its tests, in this worktree; tests green.

## Why
Review of L1 returned PASS-WITH-NOTES with one failed check (GPIL share count stale FY25 instead of FY26).

## Files to touch
- `plugins/reality-data/server/lookups_market.py`, `plugins/reality-data/tests/test_lookups_market.py`,
  `plugins/reality-data/tests/test_reality_data.py` (line ~176 only), `plugins/reality-data/catalog_descriptions.yaml`
  (add one entry for `equity_intelligence.insider_trades_v2`: one-line description of what the table holds — read 3 rows first).
- Delete the stray `PROGRESS_NOTES.md` at the worktree root (`git rm`).
- Do not touch: `core.py`, `server.py`, any database.

## Reviewer defects (verbatim)
DEFECTS:
1. `plugins/reality-data/server/lookups_market.py:398-405` — `_ar_candidates` does not exclude `core.quarantined_doc_ids()`; add `AND doc_id NOT IN (<quarantined>)` (quarantined VENUSREM doc 92565 can otherwise contribute a share count).
2. `plugins/reality-data/server/lookups_market.py:26-27` — `_SHARE_TOTAL` misses "Number of equity shares" / "Paid-up equity share capital (number of shares)"; add those phrases so GPIL returns the FY26 673,097,430 instead of FY25.
3. `plugins/reality-data/server/lookups_market.py:536-538` — "trust the AR figure" is date-blind; only emit it when the exact candidate is not older than the XBRL period, else warn of a likely buyback/split.
4. `plugins/reality-data/server/lookups_market.py:438-443` — XBRL filing query has no standalone preference/tie-break; GPIL consolidated paid-up is 617,000,000 vs standalone 650,600,000; order `Standalone` first.
5. `plugins/reality-data/server/lookups_market.py:501-504` — `as_of` only bounds `shp_index`; `holding("LUMAXTECH", as_of="2020-01-01")` returns 2026 AR/XBRL counts; filter candidates by date/known_at ≤ `as_of`.
6. `plugins/reality-data/server/lookups_market.py:28-34` — `_SHARE_TOTAL_BAD` misses range-style buckets and promoter labels; add `above|below|range|president|other banks|turnover` (PFC shows "Total Shares (100001& Above shares)" and "President of India total shares").
7. `plugins/reality-data/server/lookups_market.py:15` — unused `Iterable` import; remove it.
8. `plugins/reality-data/tests/test_reality_data.py:176` — superset assert omits `delivery`, `price_extreme`, `holding`; add them so MCP registration is actually tested.
9. `plugins/reality-data/tests/test_lookups_market.py:307-352` — LiveChecks pin 2026-10-19 values while `snapshot_path()` picks the newest `truth_*.duckdb`; skip unless the snapshot is 2026-10-19 (or pin via env).

## Manager decisions
- D3: when the exact (filing-text) count is older than the XBRL period, still return it as `best_share_count` only if
  no newer exact count exists, and set `warning: "AR count older than latest XBRL; possible buyback/split/issue"`.
- D5: every candidate carries its date; `as_of` filters all candidates (AR by fiscal year end / filing date, XBRL by period_end).
- D9: skip the live checks unless the chosen snapshot file name is `truth_2026-10-19.duckdb`.
- Add a regression test per defect where a fixture can express it (D1, D2, D4, D5, D6).

## Acceptance checks
1. `python -m unittest plugins.reality-data.tests.test_lookups_market` style run: `python -m unittest discover -s plugins/reality-data/tests -p "test_lookups_market.py"` → all pass.
2. Live: `python -m reality_engine.toolbelt.lookup_market holding GPIL` → best 673,097,430 (FY26 AR doc 120077 p182);
   `holding LUMAXTECH` still 68,157,705; `holding PFC` has no bucket/"President of India" candidates chosen.
3. `git diff --stat` touches only the files above.

## Test command(s)
```bash
python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"
```

## Budget
≤ 10 tool calls before the first edit; ≤ 50 total; ≤ 40 min; $0 paid.

## Report format
1. What changed per defect  2. Verified (counts + live answers)  3. Outside-sandbox steps  4. Open problems  5. Tool calls before first edit / total.
