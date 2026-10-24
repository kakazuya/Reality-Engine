# Morning summary — Sat 2026-10-24 (overnight run, 03:20–07:45 IST)

Claude managed; DeepSeek workers (deepseek-v4.1-flash, max effort, Go account 2, off-peak) did the building. Everything was
reviewed and tested by Claude before committing. Nothing is pushed.

## Landed on main (commits)

| Commit | What |
|---|---|
| 7a36ddd | **reality-data MCP**: catalog / resolve / price / facts / search_docs / sql over all 7 databases, registered for Claude + dsh. A fresh dsh worker answers the PPL question in 2 tool calls / ~20–30 s (was 39 steps / 9.5 min). |
| 13a634c | Paid query embedding (DeepInfra) **off** unless `REALITY_DATA_ALLOW_PAID_EMBED=1`; fleet design plan. |
| a4d0247 | `tasks/DB_QUALITY_TEST_2026-10-24.md`: your 5 questions, all handled correctly (4 answered, Q5 correctly "not in data"), 7m50s, no internet. |
| 7f0a7d6 | `tasks/DATA_JOBS_AUDIT_2026-10-24.md`: every data job, freshness, verdict, priority run list. |
| af24f2c | **dsh fleet phase 1**: any Claude session can steer any worker (DPAPI-encrypted tokens, claim_worker, steering log), worktree writers with auto-commit, 2 h leases. |
| 160d8cf | **dsh fleet phase 2**: merge queue (tests, rollback, conflict reports, push needs confirm) + `jobs.yaml` with all 57 data jobs (all disabled) + list_jobs/start_job/job_log + resource locks. |

## To activate
- **Restart the Claude app** (or reconnect MCP) so the new reality-data server and the upgraded dsh-worker load. dsh picks up
  reality-data on its next run (already in both profiles).

## Decisions for you
1. **DeepInfra query embedding** for search_docs (a few dozen tokens per search). Say yes to set the flag; until then search is keyword-only.
2. **Annual-report embeddings**: the Qwen AR index is only 4.5% done (61,440 / 1,367,706). Re-do on DeepInfra? (Nebius key is dead, HTTP 401.)
3. **Data jobs**: the nightly EOD chain stopped 19 Oct and fakes success; the raw market cache is missing; daily_price_delivery is
   2021-10-27..2026-09-24 only; there's a PIB English hole from Dec 2025 to Sep 2026. Approve the audit's P0 list (section 6), and which jobs to enable in jobs.yaml.
4. **Push** these commits to GitHub?

## Data gaps found by the test
- DEEDEV concall transcripts are marked processed but never chunked (check others too).
- `company_forensic_health` P/B mixes price dates; no quarterly net worth.
- The catalog places 2 tables in the wrong DB (small fix).

## Housekeeping
- Before the gate went in, a handful of DeepInfra query embeddings were spent (tiny tokens).
- Worktrees IDM-rd-search/-catalog removed; branches reality-data/search and reality-data/catalog are kept (merged by file copy).
- Pre-existing uncommitted files left untouched (H01 large outputs, tmp_dbs.py, tmp_q2.py, ledger.duckdb, .mcp.json.bak-20261024).
