# Reality Engine — Lanes Contract (Parallel Worktree Lanes)

> Worktree env vars: `WORKTREE_PATH` (worktree root), `REPO_PATH` (main repo root). Each worktree starts with EMPTY `reality_engine/data` (production DB is gitignored, `setup-script.ps1` only makes empty dirs).

## 1. Lane Table

| Lane | Owned Code Files | Owned DB Tables / Columns (local DB only) | Merge Artifact |
|------|------------------|-------------------------------------------|----------------|
| `lane-code-cli` | `reality_engine/cli.py` + `reality_engine/tests/test_cli_and_dashboard.py` (fix assertions only) | _none_ (read-only queries) | git branch → main |
| `lane-code-repo` | `reality_engine/db/repository.py`, `reality_engine/pipeline/data_audit.py`, `reality_engine/scripts/merge_lane_db.py`, `reality_engine/tests/test_merge_lane_db.py` | _none_ (schema helpers only) | git branch → main |
| `lane-code-derive` | `reality_engine/processing/business_profiler.py`, `reality_engine/processing/policy_engine.py`, `reality_engine/processing/moat_scorer.py`, `reality_engine/scripts/run_supply_peer.py`, `reality_engine/scripts/run_quality_peer.py`, `reality_engine/scripts/run_policy_peer.py`, `reality_engine/tests/test_derived_substrate.py` | _none_ | git branch → main |
| `lane-code-distill` | `reality_engine/processing/distillation_engine.py`, `reality_engine/data/seed/curated_company_parameters.json`, `reality_engine/tests/test_distilled_expansion.py` | _none_ | git branch → main |
| `lane-funda` | `reality_engine/scripts/_lane_shard_driver.py` (worktree-local, delete before merge) | `master_companies`, `quarterly_financials`, `annual_financials`, `company_forensic_health` | lane DB `reality_engine/data/equity_intelligence.db` → `merge_lane_db.py --mode funda` |
| `lane-filings` | `reality_engine/scripts/_lane_shard_driver.py` (worktree-local, delete before merge) | `corporate_documents` (shard cols `local_file_path/sha256_hash/file_size_bytes/is_processed` WHERE `(id % n)=i`), `raw_documents`, `document_chunks` | lane DB → `merge_lane_db.py --mode filings` |

## 2. Invariant (strict)

**never edit files you do not own; never write DB tables you do not own; worktree-local helper scripts must be deleted before merge or listed in the lane report**

- Check `.kilo/LANES.md` before any edit. If a file/table is not in your lane row, do NOT touch it.
- Worktree-local helpers (e.g. `_lane_shard_driver.py`) must be deleted before merge or explicitly listed in the lane REPORT.

## 3. Merge Order

1. `lane-code-repo` (provides `merge_lane_db.py` + schema fixes)
2. `lane-code-cli` → `lane-code-derive` → `lane-code-distill` (code peers, any order after repo)
3. `lane-funda` (fundamentals DB shard)
4. `lane-filings` (filings DB shard, runs after funda to avoid FK churn)

Main repo verifies all lane branches merged/applied via Agent Manager (user-driven) before DB merges.

## 4. DB Partition Rules

- **Code lanes** never write lane DB tables directly; they promote the dense substrate via owned code only (read-only DB queries allowed).
- **lane-funda** sharding: `WHERE (rowid % n) = i` ordered by `rowid` on `master_companies.nse_symbol`; idempotent `INSERT OR IGNORE` merge; SQLite single-writer — parent serializes DB writes.
- **lane-filings** sharding: `WHERE (id % n) = i` on `corporate_documents` where `doc_type IN ('CONCALL_TRANSCRIPT','INVESTOR_PRESENTATION')`; resumable `is_processed=1` skip; merge via UPDATE (only `is_processed=1` rows) + INSERT OR IGNORE for `raw_documents` (`sha256_hash`) and `document_chunks` (`doc_id,chunk_index`).
- **merge_lane_db.py** must inspect `PRAGMA table_info` and build explicit column lists (no `SELECT *`); transactional `BEGIN/COMMIT`; `--dry-run` prints counts without writing.
- Production DB `reality_engine/data/equity_intelligence.db` is gitignored and never copied to worktrees except `lane-filings` one-time `Copy-Item` from `REPO_PATH`.
