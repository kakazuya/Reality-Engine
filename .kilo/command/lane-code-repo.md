---
description: Repository ISIN resolver and schema fixes
---

# lane-code-repo - ISIN resolver, industries schema, funnel fix, merge helper

> Worktree: `WORKTREE_PATH` / `REPO_PATH`. Read `.kilo/LANES.md` first. You own ONLY `reality_engine/db/repository.py`, `reality_engine/pipeline/data_audit.py`, `reality_engine/scripts/merge_lane_db.py`, `reality_engine/tests/test_merge_lane_db.py`. **never edit files you do not own; never write DB tables you do not own; worktree-local helper scripts must be deleted before merge or listed in the lane report**

## 1. Read contract + existing code

- Read `.kilo/LANES.md`.
- Read `reality_engine/db/postgres_schema.sql` line 31 (industries DDL: industry_id PK AUTOINCREMENT, sector_name, industry_name UNIQUE, secular_growth_score, lifecycle_stage, tam_growth_cagr).
- Read `reality_engine/db/seed_fundamental.py` and `reality_engine/data/seed/fundamental_seed.json`.
- Read `reality_engine/pipeline/data_audit.py` line ~353 (FUNNEL_TABLES) and `reality_engine/db/repository.py` upsert methods.

## 2. repository.py - _resolve_isin + ensure_industries_schema

**Private helper:**
```python
_resolve_isin_cache = {}
def _resolve_isin(conn, company_id, symbol):
    # cache by (company_id, symbol)
    # if company_id: SELECT isin FROM master_companies WHERE rowid=?
    # elif symbol: SELECT isin FROM master_companies WHERE nse_symbol=? OR bse_code=?
    # return isin or None
```

Wire into:
- `upsert_regulatory_political_risk(symbol, ..., isin=None)` : if not isin or isin=="" call `_resolve_isin(conn, company_id, symbol)` and use resolved value, never overwriting a provided isin.
- `upsert_moat_evaluation(...)` same.
- `upsert_business_model_profile(...)` same.
Use `company_id` if supplied, else `symbol` lookup.

**Industries schema:**
- `ensure_industries_schema()` - SQLite DDL mirroring `postgres_schema.sql` line 31:
  ```sql
  CREATE TABLE IF NOT EXISTS industries (
    industry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sector_name TEXT NOT NULL,
    industry_name TEXT NOT NULL UNIQUE,
    secular_growth_score REAL CHECK (secular_growth_score BETWEEN 1 AND 5),
    lifecycle_stage TEXT CHECK (lifecycle_stage IN ('Early Adoption','Growth','Mature','Consolidating','Declining')),
    tam_growth_cagr REAL
  );
  ```
- `seed_industries_from_seed_file()` - load `reality_engine/data/seed/fundamental_seed.json` (mirror `db/seed_fundamental.py` logic onto canonical `industries` table, idempotent `INSERT OR IGNORE` / `INSERT OR REPLACE`). Must seed 12 industries.

Call `ensure_industries_schema()` inside each upsert where needed or expose for callers.

## 3. data_audit.py - phantom removal

In `reality_engine/pipeline/data_audit.py` remove the single phantom list entry `"peer_financial_metrics"` from `FUNNEL_TABLES` (~line 353). Keep the other 7 entries. This table never existed.

## 4. reality_engine/scripts/merge_lane_db.py (you also own it)

Write per TASK 3 (see also `.kilo/LANES.md` DB partition rules). Argparse `--main <db> --lane <db> [--mode funda|filings] [--dry-run]`, ATTACH, PRAGMA column lists, transactional, per-table counts. See `lane-code-repo` TASK 3 details.

## 5. Tests

```powershell
python -m unittest reality_engine.tests.test_bootstrap reality_engine.tests.test_moat_backfill reality_engine.tests.test_policy_eni reality_engine.tests.test_supply_chain reality_engine.tests.test_merge_lane_db
```

All must be GREEN. `test_merge_lane_db` is your own file - ensure it passes, including idempotent re-run.

## 6. Sub-agents

No mandatory fan-out, but you may use Task agents for: (a) helper implementation, (b) data_audit fix verification, each isolated.

## 7. Do NOT git commit/merge

Do NOT run `git commit`, `git merge`, `git stash`. Local session integrates.

## 8. REPORT

```
REPORT lane-code-repo
- Files changed: repository.py, data_audit.py, merge_lane_db.py, test_merge_lane_db.py
- Tests: test_bootstrap GREEN/RED, test_moat_backfill ..., test_policy_eni ..., test_supply_chain ..., test_merge_lane_db GREEN (counts)
- Artifacts: _resolve_isin wired: YES, industries seeded: 12 rows, FUNNEL_TABLES phantom removed: YES, merge_lane_db.py modes: funda/filings/dry-run
- Worktree-local helpers deleted or listed: none / [list]
```

Args: `$ARGUMENTS` ignored (no shard). Forward extra flags if needed.
