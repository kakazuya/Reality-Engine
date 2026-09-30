# Tech Pipeline — Sequenced Acceleration — 2026-09-25

> Owner: Main integrates; sections owned per-agent. Order: poison quarantine unblocks retries → DB tuning speeds reads → watchdog protects overnights → hygiene + index + dedup last.
> Writer rule: drain-concall-n200 holds single writer. TechDB/TechPoison PLAN-ONLY until drain exit + lock free + explicit go.

<!-- TechPoison -->
## POISON — e0ba0934_5125990312.pdf triage (PLAN-ONLY, gated post-drain)

**Target:** ADANIENT 2026-08-28 `*e0ba0934_5125990312.pdf` — extracted 314,243 chars (scanned=False) via PyMuPDF, `WARNING No chunks produced` on every attempt, `ingest ... no_chunks`.

**Root cause (suspected, NOT yet proven — verification gated below):** `DocumentParser.chunk_text` (reality_engine/processing/document_parser.py:106-145) returns `[]` via one of two paths: (a) `ConcallSectionPruner.prune()` + whitespace-collapse yields empty `cleaned` (line 108-110 `if not cleaned: return []`) — e.g. every line matching `_noise.fullmatch` or a degenerate `_start` slice; or (b) every window body decodes empty (lines 132-133 `continue`). (a) is the prime suspect for a 314k-char extract yielding zero windows; `_BOILER_SECTION` only flags `is_boilerplate`, it cannot zero output. Needs the gated offline repro to confirm which branch fires.

**Retry waste:** 30+ identical extract→0-chunk attempts in `reality_engine/data/logs/annual_report_ingest.log` (2 on 09-23, 5 on 09-24, 20+ in the 09-25 02:20–03:10 retry storm); each cycle re-extracts the PDF + re-inits the ONNX/DML session (~0.5–1.5s GPU init per attempt) and always fails the same way. Task brief cites ~20x/478s in the tight loop — consistent with the 09-25 storm.

**Contrast — sibling ADANIENT mega-docs that DID ingest (same log, 09-23 05:07–05:17):** `bde7555d...` 989 chunks, `f9c1a820...` 936, `4255f70b...` 973, `e76d493c...` 758, `06b44db1...` 676, `82a2d909...` 542, `ab5e7ab9...` 511 — plus 476/451/437/399/347/272/228-chunk siblings. Poison doc is the lone zero among 15 consecutive ADANIENT successes. Same extractor, same code path → content-specific prune collapse, not infra.


**Proposed quarantine-mark (APPROVAL-GATED, executes post-drain only):**
1. `UPDATE corporate_documents SET is_processed=2 WHERE source_url LIKE '%e0ba0934_5125990312%' OR (symbol='ADANIENT' AND doc_type='ANNUAL_REPORT' AND title LIKE '%2026-08-28%')` — value 2 = quarantined-poison (distinct from 0=pending/1=done; there is NO `ingestion_queue` table — poison state lives in `corporate_documents.is_processed` per `run_annual_report_ingest.py:128-133`).
2. Reader skip-guard: `CANDIDATE_SQL` (`run_annual_report_ingest.py:44-58`) filters `(local_file_path IS NULL OR = '')` with NO `is_processed` predicate — so marking `is_processed=2` alone will NOT exclude the poison doc. The skip-guard diff MUST add `AND COALESCE(cd.is_processed,0) <> 2` (quarantined rows never reselect) alongside the path filter, plus TechDB composite `(doc_type,is_processed,local_file_path)` so the exclusion is indexed, not a full rescan.
3. Unquarantine path: after chunker fix lands, reset to 0 for a single supervised retry; if it still yields 0 chunks, back to 2 + file a chunker bug.
**Gated execution plan (all gates REQUIRED, in order):**
- G1 drain-concall-n200 exited AND queue lock free AND explicit owner go (single-writer rule).
- G2 offline repro on a COPY (temp dir, CPU-only, no live DB): extract the PDF, run `prune()` alone, report len-before/len-after + which branch returns [] — confirms (a) vs (b) before any fix is designed.
- G3 owner approves the SQL text + skip-guard diff; TechPoison writes NOTHING — Main or owner applies.

**Status:** NO code written, NO DB touched (zero connections from this agent), NO ingests launched, NO files deleted.
_Pending TechWatch append._

<!-- TechTest-HYGIENE -->
## TEST HYGIENE — (TechTest lane) <!-- TechTest -->

_Fix landed (only code change): `reality_engine/tests/test_horizon_excess.py:663` — `back = _json.loads(open(dest, encoding="utf-8").read())` → `with open(dest, encoding="utf-8") as _fh:` + `back = _json.loads(_fh.read())`. Same bytes, handle now closed deterministically. No other `open(...).read()` remains in the file (grep-verified). Existing gettempdir()+pid + unlink pattern left untouched (one-line scope)._

### Fastest 5-file gate — promotion math (serial, wall stamped post-drain)

| # | File | Why gate-relevant |
|---|------|-------------------|
| 1 | `test_horizon_excess.py` | realized-window + horizon excess math — **measured 37 tests OK in 4.6s** |
| 2 | `test_sip_backtest.py` | tax/FIFO/cost schedule shared by 10cr book |
| 3 | `test_portfolio_ledger.py` | ledger framing/bracket math |
| 4 | `test_event_version.py` | event-date/version migration contract |
| 5 | `test_desk_backtest.py` | 10cr engine (temp DB) |

```powershell
python -m unittest reality_engine.tests.test_horizon_excess reality_engine.tests.test_sip_backtest reality_engine.tests.test_portfolio_ledger reality_engine.tests.test_event_version reality_engine.tests.test_desk_backtest
```
Gate passes iff 0 failures AND serial wall <15s. Wall unstamped — first post-drain run stamps real durations here. Files 2-5 timings unverified until then.

### Shard A/B plan (from test-infra evidence)

- Full-discovery `pytest` exit-5 is environmental (process accumulation on 16GB) — never a defect signal; shard-by-half is the supported runner (`tasks/SESSION_CLOSEOUT_2026-09-23.md`, `tasks/test_perf_baseline_2026-09-22.md`).
- Shard A: `test_action_thesis.py` → `test_news_explainer` (first-half alphabetical, 36 modules per baseline BEFORE: 386 passed in 136.78s serial).
- Shard B: remainder of `reality_engine/tests` (middle + tail per closeout: 178 + 172).
- `-n 12` xdist is ~1.3x only (DirectML sequential contention inflates 3-30x) — default to serial shards; xdist is never the fast path on this box.
- Full suite stays post-drain only (never beside the writer); pre-commit = 5-file gate above.

### Collection-hygiene rules (all new/edited tests)

- `cli` / `pandas` / `fitz` imports are function-local inside the test method — never module top-level (keeps collection light, no import-time side effects).
- New tests use `tempfile.TemporaryDirectory` (self-cleaning) — never `gettempdir()+pid` + manual `unlink` (legacy pattern grandfathered where it stands; this task's one-line fix did not migrate it).
- Temp-DB or no-DB proof only; zero live DB connections beyond read-only dry-run/SELECT; zero live writes.
- No new packages; no bootstrap changes; no full-suite runs beside the writer.

### Proof (this task)

- `python -m unittest reality_engine.tests.test_horizon_excess -v` → **37 tests OK in 4.645s** (full module, temp-only, post-fix).
- Grep `open\(.*\)\.read\(\)` over the file → zero remaining sites (fix is complete, not partial).

<!-- TechDB-TUNING -->
## DB TUNING — staged SQL text (TechDB lane, PLAN-ONLY, gated post-drain)

**Status: NOT applied live. Awaits post-drain window (drain-concall-n200 exit + queue lock free + explicit go). Zero live UPDATE/ALTER/DROP/CREATE by TechDB; zero live DB connections (read-only schema.sql reads + :memory: temp-DB proof only). No edits to reality_engine/db/database.py or reality_engine/config.py in this window.**

**Column verification (schema.sql read-back, 2026-09-25):**
- `document_chunks(symbol TEXT :638, chunk_id PK :628, industry_id INTEGER :637)` — supports `idx_docchunks_symbol_chunk` + partial `idx_docchunks_noindustry`.
- `corporate_documents(doc_type TEXT NOT NULL :241, is_processed BOOLEAN DEFAULT 0 :250, local_file_path TEXT :247)` — supports `idx_corpdocs_pending`.
- `portfolio_actions(status TEXT NOT NULL DEFAULT 'open' :85, symbol TEXT NOT NULL :78, action_date TEXT NOT NULL :80)` — DDL lives in `reality_engine/processing/portfolio_ledger.py:76-91` (not schema.sql); supports `idx_portfolio_open_sym`. Complements existing `idx_portfolio_status_date(status, action_date)` at portfolio_ledger.py:93-96.
- `raw_documents(source_type TEXT NOT NULL :450, published_date TEXT NOT NULL :451)` — supports `idx_rawdoc_type_pub`. Complements existing `idx_rawdoc_source_type(source_type)` + `idx_rawdoc_published(published_date DESC)` at schema.sql:462-463.

**Staged migration block — append at end of `DatabaseManager._apply_runtime_migrations` in `reality_engine/db/database.py` (after regpol block ~:343, following existing symbol/fiscal-index try/except pattern):**
```python
        # Post-drain read-speed indexes (TechDB 2026-09-25) — ADDITIVE ONLY.
        # Follows the existing idx_docchunks_symbol / idx_chunks_fiscal pattern:
        # one try/except per CREATE INDEX IF NOT EXISTS, never crash init_db.
        for _idx_sql in (
            "CREATE INDEX IF NOT EXISTS idx_docchunks_symbol_chunk "
            "ON document_chunks(symbol, chunk_id)",
            "CREATE INDEX IF NOT EXISTS idx_docchunks_noindustry "
            "ON document_chunks(symbol) WHERE industry_id IS NULL",
            "CREATE INDEX IF NOT EXISTS idx_corpdocs_pending "
            "ON corporate_documents(doc_type, is_processed, local_file_path)",
            "CREATE INDEX IF NOT EXISTS idx_portfolio_open_sym "
            "ON portfolio_actions(status, symbol, action_date)",
            "CREATE INDEX IF NOT EXISTS idx_rawdoc_type_pub "
            "ON raw_documents(source_type, published_date DESC)",
        ):
            try:
                conn.execute(_idx_sql)
            except Exception:
                # Table absent on a minimal bootstrap; never crash init_db.
                pass
```

**Staged config patch — `reality_engine/config.py` ONLY (2 constants, nothing else):**
```diff
-    "PRAGMA cache_size = -64000;",      # 64 MB page cache
+    "PRAGMA cache_size = -256000;",     # 256 MB page cache (post-drain read burst)
     "PRAGMA temp_store = MEMORY;",
     "PRAGMA foreign_keys = ON;",
     "PRAGMA busy_timeout = 180000;",      # 3 min: a large PDF ingest holds one write txn ~50s
```
- `SQLITE_PRAGMAS` busy_timeout is already 180000 (3 min) — NO change needed there.
- Backfill `PRAGMA busy_timeout=60000` (60s) lives in `reality_engine/scripts/backfill_fiscal_periods.py:39` + `reality_engine/scripts/migrate_event_version.py:83` — OUTSIDE TechDB file ownership, so staged here as text-only proposal for Main/owner post-drain: `60000` → `180000` in both scripts. TechDB writes NEITHER file.

**Temp-DB proof (fresh `:memory:` sqlite, never live DB — run 2026-09-25, GREEN):**
- Created minimal tables with the verified columns, ran all 5 CREATE INDEX statements, re-ran for idempotency.
- `sqlite_master` returned exactly the 5 indexes with expected DDL (partial WHERE + DESC preserved):
  - `idx_corpdocs_pending`, `idx_docchunks_noindustry`, `idx_docchunks_symbol_chunk`, `idx_portfolio_open_sym`, `idx_rawdoc_type_pub`
- Result: `TEMP-DB PROOF GREEN: 5 indexes, idempotent`.

**Gates (all REQUIRED, in order):** G1 drain-concall-n200 exited + queue lock free + explicit owner go → G2 owner approves SQL text + config diff above → G3 Main/owner applies (TechDB applies nothing).
<!-- TechWatch -->
## OPS — watchdog queue hardening (TechWatch)

### 1. ONSTART task plan (ELEVATED, plan only — NOT registered this session)
# Embed server first (Vulkan-only :8099), then drain. /delay staggers boot I/O; /ru SYSTEM survives user logoff.
# schtasks /create /tn RealityEngine-EmbedServer /sc ONSTART /delay 0001:00 /ru SYSTEM (tr: wscript run_hidden.vbs run_embed_server.cmd) /f
# schtasks /create /tn RealityEngine-AnnualDrain /sc ONSTART /delay 0003:00 /ru SYSTEM (tr: wscript run_hidden.vbs run_annual_drain.cmd) /f
# Keep existing HOURLY RealityEngine-AnnualDrain as-is (no schtasks changes made; VBS already restored single-line; no .cmd edits).
# Facts: run_embed_server.cmd binds 127.0.0.1:8099, bge-small-en-v1.5-q8_0, hub owns restart (detached+persist, no respawn loop); run_annual_drain.cmd sets GPU_DUTY=0.90/VULKAN_BATCH=96, runs queue --only annual_n200 --batch 10, exit /b %ERRORLEVEL%.

### 2. Fail-fast semantics (env REALITY_ENGINE_FAIL_FAST_DOC, default OFF)
# - Off by default: wrapper keeps --retries 20 for transient 0xC0000005 (drhp precedent: exit 0 on attempt 3 after two 3221225477 crashes).
# - When enabled: a stage failing 3x consecutively (no_chunks poison-doc class, e.g. ADANIENT e0ba0934 looping exit=1) logs POISON_GUARD + breaks that stage's retry loop — stops burning 20 retries on a deterministic poison doc.
# - Queue sees subprocess exit codes, not per-doc status; 3-consecutive is the stage-level proxy. Per-doc quarantine is TechPoison's lane; this only stops the retry burn. Breaking the loop still records FAILED (nonzero wrapper) — never masks failure as success.

### 3. Nonzero-wrapper contract
# - Every selected stage exits 0 at least once → QUEUE_COMPLETE, return 0.
# - ANY selected stage never exits 0 → QUEUE_INCOMPLETE stages=<csv>, return 1. Fixes masking where drain-smoke-n200-25b logged QUEUE_COMPLETE with wrapper exit 0 despite stage exit=1.
# - Lock held by another writer → skip message, return 0 (hourly tick overlapping live writer is expected).
# - Unknown --only → error, return 2.

### 4. Reboot checklist
# 1. Embed :8099 reachable (Vulkan) before any drain tick. 2. Queue lock free; hourly ticks skip while writer busy — never co-run GPU/DB jobs. 3. Env echo shows GPU_DUTY=0.90 VULKAN_BATCH=96 EMBED_BACKEND=vulkan. 4. Poison doc quarantined before annual_n200 retries resume; consider REALITY_ENGINE_FAIL_FAST_DOC=1 until drain green. 5. After reboot: verify ONSTART tasks Ran Successfully, then confirm QUEUE_COMPLETE (not QUEUE_INCOMPLETE) in ingestion_queue.log.

Code change (shipped, py_compile clean): `reality_engine/scripts/run_ingestion_queue.py` ONLY — FAIL_FAST_THRESHOLD=3 + env gate + consecutive-failure tracking + failed_stages[] + QUEUE_INCOMPLETE nonzero. Default-off path preserves retry-20; enabled path breaks poison loop at 3. No stage-order/schtasks/lock changes.
