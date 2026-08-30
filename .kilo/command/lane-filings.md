---
description: Filings download shard lane
---

# lane-filings - Filings download shard lane ($1 = shard "i/n" e.g. 0/2)

> Read `.kilo/LANES.md` first. You own LOCAL DB columns/tables `corporate_documents` (download-state cols for your id shard only), `raw_documents`, `document_chunks`. **never edit files you do not own; never write DB tables you do not own; worktree-local helper scripts must be deleted before merge or listed in the lane report**

## 0. Parse shard arg and ensure base DB

`$1` is shard "i/n" (e.g. 0/2). Also accept `$ARGUMENTS`. Validate 0 <= i < n.

**Copy base DB if missing:**
```powershell
if (-not (Test-Path -LiteralPath "$env:WORKTREE_PATH\reality_engine\data\equity_intelligence.db")) {
  Copy-Item "$env:REPO_PATH\reality_engine\data\equity_intelligence.db" "$env:WORKTREE_PATH\reality_engine\data\equity_intelligence.db"
}
```
This is ~1.6 GB – only if missing (do NOT overwrite existing). Verify `SELECT COUNT(*) FROM corporate_documents` >0 after copy.

If REPO_PATH not set, ask user or default to parent dir assumption; log path used.

## 1. Filter shard rows

Work ONLY on rows where:
```sql
doc_type IN ('CONCALL_TRANSCRIPT','INVESTOR_PRESENTATION')
AND (id % :n) = :i
AND is_processed = 0
AND (local_file_path IS NULL OR local_file_path='')
```
Order by `id`. Count total for shard. Resumable: skip rows where `is_processed=1` or `local_file_path` present (already downloaded).

## 2. Reuse existing fetch semantics

Read to reuse:

- `reality_engine/cli.py` `cmd_fetch_filings` --from-db --doc-type semantics
- `reality_engine/ingestion/official_filing_client.py` client functions (`official_filing_client.archive_many` or `archive_link`, `_download`)

Reuse those client functions with:

- rate-limit ~0.8s
- workers 3-4
- retry/backoff on 429/500
- On success: update `corporate_documents` columns `local_file_path`, `sha256_hash`, `file_size_bytes`, `is_processed=1` WHERE id=?
- Create `raw_documents` + `document_chunks` rows per existing pipeline path if the ingestion does it automatically (check `pdf_ingestor.py` / `process-inbox` path – if auto then verify rows appear, else insert placeholder with `doc_id` linked to corporate_documents id).

Single-writer discipline: sub-agents download only and return file metadata `{id, local_file_path, sha256_hash, file_size_bytes, is_processed, error}`; parent serializes all DB writes (UPDATE corporate_documents + INSERT raw_documents/document_chunks) in one transaction per batch.

## 3. Sub-agent fan-out

Split shard into 4-6 parallel batch downloaders (e.g. shard 0/3 has ~400 docs -> 4 batches of 100). One Task sub-agent per batch:

- Sub-agent reads `official_filing_client.py` segment, downloads its batch (workers 3-4), returns metadata list.
- Parent collects, writes DB serially, updates counts.

## 4. Execution and resumable checkpoints

Checkpoint print every 25 downloads: `Downloaded 25/100 ... success 20 failed 5 skipped 0 disk_used MB=45`.

Long-running hours OK. Handle 403/404 as failed (do not retry indefinitely).

Hours-long OK – keep alive. If interrupted, re-run will skip is_processed=1.

## 5. Do NOT git commit/merge

Do NOT run `git commit`, `git merge`, `git stash`. Delete `reality_engine/scripts/_lane_shard_driver.py` if you created one, or list in REPORT. Local session integrates.

## 6. REPORT

```
REPORT lane-filings shard=$1
- Files changed: reality_engine/scripts/_lane_shard_driver.py (if used, deleted/listed)
- Tests: base DB copy OK/SKIPPED (size MB=N), shard filter count=N (doc_type CONCALL/INVESTOR only)
- Artifacts: downloaded=N, failed=N, skipped (is_processed=1 already)=S, disk_used MB=N, pdf_dir files=N
- Per-table: corporate_documents updated=N, raw_documents inserted=N, document_chunks inserted=N
- Failures (first 20): [id:symbol:error]
- Worktree-local helpers deleted or listed: deleted / [list]
```

Args: `$1` = shard "i/n", `$ARGUMENTS` forwarded.

Example:
```
Copy-Item "$env:REPO_PATH\reality_engine\data\equity_intelligence.db" "$env:WORKTREE_PATH\reality_engine\data\equity_intelligence.db"
python reality_engine/scripts/_lane_shard_driver.py 0/2
```
