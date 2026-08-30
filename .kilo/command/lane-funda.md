---
description: Fundamentals fetch shard lane
---

# lane-funda - Fundamentals fetch shard lane ($1 = shard "i/n" e.g. 0/2)

> Worktree DB is EMPTY (production DB gitignored, setup-script.ps1 only makes empty dirs). Env vars: `WORKTREE_PATH` (your checkout), `REPO_PATH` (main repo). Read `.kilo/LANES.md` first. You own DB TABLES (local DB only) `master_companies`, `quarterly_financials`, `annual_financials`, `company_forensic_health`. **never edit files you do not own; never write DB tables you do not own; worktree-local helper scripts must be deleted before merge or listed in the lane report**

## 0. Parse shard arg

`$1` is shard "i/n" e.g. `0/2`, `1/4`. Also accept `$ARGUMENTS` as same. Parse:
```powershell
$shard = "$1"  # e.g. 0/2
$i, $n = $shard.Split('/')
```
Validate 0 <= i < n, n >=1. Default if missing: 0/1.

## 1. Build master_companies locally

Worktree DB is EMPTY. First:
```powershell
python reality_engine/cli.py sync-master
```
This builds `master_companies` from NSE/BSE in YOUR local DB. Verify `SELECT COUNT(*) FROM master_companies` >1800 before proceeding. If sync-master fails (network), retry once after 10s.

## 2. Create worktree-LOCAL driver

Create `reality_engine/scripts/_lane_shard_driver.py` – WORKTREE-LOCAL only, must be deleted before merge or listed in REPORT. This driver:

- Queries master symbols for this shard:
  ```sql
  SELECT isin, nse_symbol, bse_code FROM master_companies
  WHERE (rowid % :n) = :i
  ORDER BY rowid
  ```
- For each symbol in batches, calls fundamentals ingestion client reused from existing code:
  - Read `reality_engine/ingestion/fundamentals_client.py` and `reality_engine/cli.py` `cmd_fetch_fundamentals` to reuse `fundamentals_client.fetch_company_fundamentals` or `fetch_all_fundamentals` batch helper.
  - Rate-limit 0.5-1.0s between requests, workers 4, retry with exponential backoff on HTTP 429 (sleep 2s, 4s, 8s).
  - RESUMABLE: before fetching a symbol, check if symbol already has rows in `quarterly_financials` AND `annual_financials` (SELECT COUNT(*) >0) – skip if both present.
  - On success, collect rows for `quarterly_financials`, `annual_financials`, `company_forensic_health` (is_solvency_approved etc.).
  - On failure, record in failed list with error.

- Writes to YOUR local DB only (`master_companies` already there, plus 3 fundamentals tables). Single-writer discipline: parent serializes all DB writes – sub-agents return parsed rows only, never write DB directly (SQLite single writer).

- Checkpoint: print progress every 25 symbols: `Fetched 25/320 ... quarterly=100 annual=80 forensic=25 failed=2`.

- Long-running: it is fine to run for hours; keep process alive, handle KeyboardInterrupt gracefully.

- Optionally reuse `cli.py` discover-filings/fetch-filings semantics only if trivial – do NOT duplicate filings lane logic.

## 3. Sub-agent fan-out

Split your shard into 4-8 symbol batches (e.g. shard 0/2 has ~900 symbols -> 8 batches of ~112). One Task sub-agent per batch:

- Sub-agent reads fundamentals_client.py segment, fetches its batch (workers 4 internally), returns dict `{quarterly:[], annual:[], forensic:[], failed:[]}`.
- Parent collects results, writes to DB serially via `repo.upsert_quarterly_financials` etc., updates progress.

## 4. Execution

```powershell
python reality_engine/scripts/_lane_shard_driver.py $1
# or if driver takes --shard flag: python reality_engine/scripts/_lane_shard_driver.py --shard 0/2
```

If driver is implemented as inline python block, ensure it logs to stdout.

## 5. Do NOT git commit/merge

Do NOT run `git commit`, `git merge`, `git stash`. Local session integrates; Agent Manager merges. Delete `_lane_shard_driver.py` before merge or list it in REPORT.

## 6. REPORT

```
REPORT lane-funda shard=$1
- Files changed: reality_engine/scripts/_lane_shard_driver.py (worktree-local, deleted/listed)
- Tests: sync-master OK/FAIL (master_companies count=N), driver fetch OK/FAIL
- Artifacts: quarterly rows=N, annual rows=N, forensic rows=N, failures=[symbol:error,...] (first 20), failures total=F
- Disk: local DB size MB=N
- Shard progress: i/n = fetched X / total Y (Z% estimated completion), resumable skip count=S
- Worktree-local helpers deleted or listed: deleted / [_lane_shard_driver.py listed]
```

Include per-table counts from `SELECT COUNT(*) FROM quarterly_financials` etc. after run.

Args: `$1` = shard "i/n", `$ARGUMENTS` forwarded.
