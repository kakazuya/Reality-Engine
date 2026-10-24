# Task: safe read-only SQL, a subagent time cap, and two data fixes

Owner: Shivam (2026-10-24). Reviewer: Claude. You run in the main checkout and may write
`reality_engine/data/equity_intelligence.db` (no other writer is running; never start a second writer).

## Why (from today's subagent fan-out test, job 20261024T133203Z-0eb45906)

- A subagent hung >14 min inside one SQL query on the 53.7 GB `equity_intelligence.db` (correlated subquery /
  unindexed GROUP BY). There is no query timeout and no time cap per subagent; a steering message cannot reach a
  child stuck inside a tool call.
- Read-only SQLite connections intermittently fail with `unable to open database file` on queries needing temp
  space; `PRAGMA temp_store=MEMORY` fixes it. Do NOT use `immutable=1` (it ignores the 371 MB live `-wal`).
- `insider_trades_v2` (built today by `reality_engine/scripts/build_insider_trades.py`) carries NSE's own typo
  dates: trade_from as early as 1922 and as late as 3034, intimation_date up to 2036 (~10 rows, kept "as published").
- `raw_documents` has no symbol/isin column and annual-report `title` is literally 'ANNUAL_REPORT', so a document's
  company is only recoverable from `local_file_path` (`...\pdfs\<SYMBOL>\ANNUAL_REPORT\...`), `document_chunks.isin`
  / `.symbol`, or `corporate_documents`.

## Do

1. **Read-only SQL helper.** Add `reality_engine/db/readonly.py` with `connect_ro(path, timeout_s=30)`:
   `file:...?mode=ro` URI, `PRAGMA temp_store=MEMORY`, `PRAGMA query_only=1`, a sensible `cache_size`, and a
   `set_progress_handler` that aborts any statement running past `timeout_s` with a clear error (`QueryTimeout`).
   Use it in the read paths that agents hit: `plugins/reality-data/server/core.py` (its `connect_sqlite`; keep its
   existing 5 s `sql` tool timeout and add temp_store=MEMORY) and any shared read helper workers use. Add one line to
   AGENTS.md (§3 or a "Querying" note): agents query the big DB via `connect_ro` or the reality-data tools, never a
   bare connection, and avoid correlated subqueries over `document_chunks`.
2. **Subagent per-child time cap.** In the dsh packages (`C:\Users\warri\.bun\install\cache\@deepseek-ai\`,
   start with `dsh-tool-subagent`, `dsh-subagent`, `dsh-subagent-spawn-in-process`, the tool-call timeout settings in
   the base bundle `dsh-base@*/cordis.patch.yml`) find whether a per-child wall-clock limit and/or a per-tool-call
   timeout (bash/pwsh) exists. If yes, stage profile changes in `tasks/dsh_profiles/headless.cordis.patch.yml` and
   `.../web.cordis.patch.yml` (copy from `C:\Users\warri\.dsh\profiles\*\cordis.patch.yml`; you cannot write
   `~/.dsh` — Claude installs after review). Note: a patch replaces a row's whole `config`, so restate base values;
   validate with `dsh --dump-config` against a staged DSH_HOME as the previous worker did (job 20261024T132140Z-d16588e0).
   Aim: child cap 15 min, shell tool-call cap 10 min. If no such setting exists, say so and propose the smallest
   alternative (e.g. parent-side `interrupt_agent` rule in the agent instructions).
3. **insider_trades_v2 bad dates.** In `build_insider_trades.py`: add a `date_flag` column; a trade/intimation date is
   implausible if it is before 2000-01-01 or after the row's `known_at` date + 1 day (or after today when known_at is
   NULL). Set those dates to NULL, keep the raw text in `trade_from_raw`/`intimation_date_raw`, flag the row
   (`implausible_trade_date` etc.). Do not guess corrections. Update tests. Rebuild the live table and report how
   many rows were flagged, with 5 examples.
4. **raw_documents symbol gap.** Add nullable `symbol` and `isin` columns to `raw_documents` (ALTER TABLE ADD COLUMN,
   additive only; check `reality_engine/db/schema.sql` and keep it in sync). Backfill: first from `corporate_documents`
   (match on local_file_path or source_url), then the most common `document_chunks.isin`/`symbol` per doc_id, then the
   `pdfs\<SYMBOL>\` path segment; record which method in a `symbol_source` column. Make the ingestors
   (`pdf_ingestor.ingest_pdf` and `_persist_chunks`) fill them for new documents (they already receive symbol/isin).
   Report coverage by source_type before/after, and how many AR documents still have no symbol.
5. Tests (unittest, in-memory/temp fixtures, no network): connect_ro timeout fires and temp_store works; date flag
   rules; raw_documents backfill precedence. Run them plus `test_insider_trades` and the quick suite.

## Rules

- Back up nothing big; changes are additive. Before ALTER TABLE, check free disk and that no other process holds a
  write on the DB. Commit code changes on a branch-free basis is not needed: leave them uncommitted for Claude's review.
- Final answer: what changed per item, the dsh time-cap finding, test output, the flagged-date count + examples, the
  raw_documents coverage table, and anything not done.
