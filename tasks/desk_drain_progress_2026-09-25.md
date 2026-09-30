# Desk Drain Progress — 2026-09-25 (RunDrain, read-only)

> Ownership: RunDrain owns ONLY this file. No code/schema edits. Single-writer rule enforced throughout.
> Serialization (parent directive): BuildEventVer owns `scripts/migrate_event_version.py`; migration runs on live DB only after temp-COPY proof; drain stages pause while migration holds writer; BuildDeskBook never touches live DB.

## 1. Gate checks (before each stage)

| Check | 2026-09-25 ~02:1x UTC | Evidence |
|---|---|---|
| embed-server :8099 TCP | REACHABLE | `socket.connect(127.0.0.1:8099)` ok; `/health` → `{"status":"ok"}` |
| embed-server process | ready pid=24008, uptime ~19m, restarts=0, detached+persist | `hub ps` |
| Queue lock file | exists, 6 B (idle marker, no holder) | `reality_engine/data/ingestion_queue.lock` |
| Live writer | NONE running | `hub ps`: all ingest-* exited/failed; only embed-server live |
| DB WAL/SHM | `equity_intelligence.db` 27.4 GB; `-wal` 41,232 B; `-shm` 32,768 B (quiescent, no active writer) | stat |
| GPU/env for stages | `GPU_DUTY 0.90 / VULKAN_BATCH 96 / EMBED_BACKEND vulkan / EMBED_SERVER http://127.0.0.1:8099` | stage log line |
| Hourly watchdog | `RealityEngine-AnnualDrain` Ready; queue lock makes ticks skip when writer busy | handover §2 (unchanged) |

## 2. Baseline pending trajectory (live DB, query-only)

Timestamp: 2026-09-25 ~02:20 UTC. Source: `SELECT doc_type,is_processed,COUNT(*) FROM corporate_documents GROUP BY 1,2`.

| doc_type | pending (is_processed=0) | done (is_processed=1) |
|---|---|---|
| ANNOUNCEMENT | 16,085 | — |
| ANNUAL_REPORT | 26,263 | 351 |
| CONCALL_TRANSCRIPT | 10,456 | 8,060 |
| FINANCIAL_RESULT | 2,707 | 40 |
| INVESTOR_PRESENTATION | 585 | 1,030 |
| OFFER_DOCUMENT | — | 904 |
| OTHER_FILING | 37,150 | — |
| **Total pending** | **93,246** | — |

- `document_chunks`: **1,653,367** rows.
- `fiscal_period IS NOT NULL`: **292,246** (fiscal-labeled; column is `fiscal_period`, not `fiscal_year`).
- `corporate_documents` cols: **14**; `document_chunks` cols: **15**; event-date/version cols: **absent** (`has_event_col = 0`). Confirms handover live state.
- HELD gate: bulk **26,263 ANNUAL_REPORT** (+ 10,456 concalls) stay HELD until BuildEventVer lands event-date/version columns. BuildEventVer confirmed 2026-09-25: "NOT landed yet … do NOT start any writer smoke until I clear you."

## 3. Per-stage exits (sequential, one writer at a time)

Stage order (from `run_ingestion_queue._stages`): drhp → annual_n200 → concall_n200 → annual_all → concall_all → refresh → business_map.

### 3a. History (from `reality_engine/data/logs/ingestion_queue.log`, pre-existing)

- `drhp`: 2026-09-22 attempt 3 exit=0 (301 s) after two `3221225477` crashes. Stage finished.
- `annual_n200`: 2026-09-22 attempt 1 exit=0 (591 s) → `QUEUE_COMPLETE`. 2026-09-24 full N200: attempt 1 exit=0 (5,166 s, backend=vulkan) → `QUEUE_COMPLETE`. Matches handover `ingest-annual-resume-v2` 233/234.
- `concall_n50`: exited 0 (~38 min, 377/378) per handover; `chunk-index-rebuild` exited 0 (1,398,908 rows dim 384) per handover.

### 3b. Today — smoke `annual_n200 --n200-limit 25` (two runs: first stop-induced exit 1, second clean wrapper exit 0, both 0 rows)

- Supervised process `drain-smoke-n200-25` (full path `Python314\python.exe -m reality_engine.scripts.run_ingestion_queue --only annual_n200 --n200-limit 25`, env GPU_DUTY=0.90/VULKAN_BATCH=96/backend=vulkan).
- First launch with bare `python` failed to spawn (Win32 error 193) — no process, no DB touch. Relaunched with full interpreter path: running pid=14512.
- While starting, BuildEventVer issued serialization hold: **no writer smoke (including annual_n200) until migration clears**. RunDrain stopped the process immediately: `drain-smoke-n200-25` → **exited exit=1, uptime 36.7 s** (stop-induced, not a natural completion).
- Its single stage attempt before stop: `stage annual_n200 attempt 1 exit=1 (27 s)`; ingest log: `pending ANNUAL_REPORT: 1 (nifty200: 1)`; `batch 0-1 done: ok=0 failed=1 (21 s)`; `RUN_COMPLETE ingested=0 failed=1 seconds=23`; `ADANIENT 2026-08-28: no_chunks` (PDF extracted 314,243 chars via PyMuPDF, `No chunks produced`). **Rows written: 0.**
- Writer after first stop: FREE (hub `ps`: only embed-server live). No overlapping writers at any point (first smoke was the sole writer; stopped before any other stage started).
- Clean retry `drain-smoke-n200-25b` (same cmd + `--retries 1`, pid=10432, after BuildEventVer "holding all live-DB work, proceed with smoke"): **exited exit=0, uptime 2m07s**, `QUEUE_COMPLETE in 128s (embed backend=vulkan)`. Stage attempt: `attempt 1 exit=1 (113 s)` (nonzero stage exit, queue wrapper still exits 0 with `--retries 1`); ingest: `pending ANNUAL_REPORT: 1 (nifty200: 1)`; `batch 0-1 done: ok=0 failed=1 (108 s)`; `RUN_COMPLETE ingested=0 failed=1 seconds=109`; same `ADANIENT 2026-08-28: no_chunks` (PDF 314,243 chars via PyMuPDF, `No chunks produced`). **Rows written: 0.** Post-smoke recount: ANNUAL pending 26,263 / CONCALL 10,456 / chunks 1,653,367 — unchanged, no silent writes.
- Writer after retry: FREE (hub `ps`: only embed-server live; `drain-smoke-n200-25b exited 0`). Each smoke ran as the sole writer, sequential, never concurrent — zero overlap. Remaining stages **NOT started** — `concall_n200`, `annual_all`, `concall_all`, `refresh`, `business_map` all HELD pending BuildEventVer live-run-complete. Writer now HANDED to BuildEventVer for migration (COPY-proof → live ALTER); RunDrain starts no further writers until its clear.

## 4. Chunk index freshness (marker check, read-only)

- Marker: `reality_engine/data/vector_index/chunk_index_meta.json` + `build_chunk_vector_index --stats`:
  - `rows 1,398,908`, `dim 384`, `dtype float32`, `built_at 2026-09-24T04:19:39`, `build_seconds 999.3`, `source_chunks_at_build 1,642,865`.
- Live `document_chunks` count: **1,653,367**.
- Freshness: **STALE by ~10,502 chunks** (1,653,367 − 1,642,865). Rebuild (`refresh` stage) deferred until drain writes resume + migration clears, to avoid indexing mid-write. No rebuild launched today (would take the writer/index path).

## 5. Writer-overlap audit

- 02:19–02:20 UTC: one writer (`drain-smoke-n200-25`, pid 14512) alive; embed-server is not a DB writer. No second GPU/DB job co-ran. 02:22–02:24 UTC: one writer (`drain-smoke-n200-25b`, pid 10432) alive; same — sole writer, never concurrent with any other GPU/DB job.
- Post-retry `hub ps`: `embed-server ready`; `drain-smoke-n200-25 exited 1`; `drain-smoke-n200-25b exited 0`; all other ingest processes exited/failed (historical). **Zero overlapping writers at every instant.**
- Queue lock: lock file present as idle marker; no process holds it now (both smokes exited; writer HANDED to BuildEventVer for migration — RunDrain starts nothing further until its clear).

## 6. Pending trajectory toward 0

| Time | Pending ANNUAL | Pending CONCALL | Chunks | Index source_at_build | Note |
|---|---|---|---|---|---|
| Handover (09-24) | 26,263 | 10,456 | 1,653,367 | 1,642,865 (stale ~10.5k) | corp_docs 103,631; pending 93,246 |
| 2026-09-25 ~02:20 UTC | 26,263 | 10,456 | 1,653,367 | 1,642,865 (stale ~10,502) | First smoke stop-induced exit 1, 0 rows, then HELD |
| 2026-09-25 ~02:24 UTC | 26,263 | 10,456 | 1,653,367 | 1,642,865 (stale ~10,502) | Clean retry wrapper exit 0, stage exit 1 (ADANIENT no_chunks), 0 rows; writer handed to EventVer |

Trajectory is flat-in-HELD by design: drain to zero resumes after event-version migration clears. Fiscal-only batches may flow per handover drain verdict once BuildEventVer scopes them; RunDrain awaits that signal.

## 7. Next (blocked, explicit)

1. Await BuildEventVer `live-run-complete` message (event-date/version columns on live DB) — writer is THEIRS now; RunDrain launches nothing.
2. On clear: re-verify gate (TCP :8099 + `hub ps` writer-free + WAL/SHM) before each stage.
3. Sequential queue via `hub start` (one at a time): expand N200 → `concall_n200` → `annual_all` → `concall_all` → `refresh` (rebuild index, expect `source_chunks_at_build == COUNT(document_chunks)`) → `business_map`. Smoke already done (wrapper exit 0, 0 rows — single N200 pending doc fails chunking, needs triage, not retry-loop). Log each exit + recount here.
4. Respect hourly watchdog (lock makes ticks skip); env `GPU_DUTY 0.90 / VULKAN_BATCH 96` every stage.

## 8. Evening writer session — 2026-09-26 ~00:32–00:44 UTC (WriterSequence, single writer)

> Slice A owns the queue lock. No other slice writes live DB. All counts below are live-DB reads unless noted.

### 8a. Pre-flight gate

| Check | Result | Evidence |
|---|---|---|
| embed-server :8099 TCP + `/health` | REACHABLE | `socket.connect(127.0.0.1:8099)` ok; `/health` → `{"status":"ok"}` |
| Live writers | NONE (writer-free) | `tasklist`: only harness python (pid 12520, omp runner) + self; `BEGIN IMMEDIATE` + `ROLLBACK` probe ok (no mutation); `-wal` 5,220,072 B static over 20 s obs; queue/ingest logs static since 2026-09-25 12:40 UTC |
| Queue log tail | last run 2026-09-25 12:40 UTC: `stage annual_n200 attempt 1 exit=0 (7s)` → `QUEUE_COMPLETE in 7s` | `ingestion_queue.log:297-301` |
| Ingest log tail | 12:40:08 `pending ANNUAL_REPORT: 0 (nifty200: 0)` — N200 slice drained | `annual_report_ingest.log:17211` |

### 8b. Baseline recount (live DB, read-only, ~00:33 UTC)

| doc_type | pending (is_processed=0) | done (1) | quarantined (2) |
|---|---|---|---|
| ANNOUNCEMENT | 16,085 | — | — |
| ANNUAL_REPORT | 26,262 | 351 | 1 (ADANIENT id=5880, `.../512599/5125990312.pdf` — PUA poison doc, excluded from candidates) |
| CONCALL_TRANSCRIPT | 9,140 | 9,376 | — |
| FINANCIAL_RESULT | 2,707 | 40 | — |
| INVESTOR_PRESENTATION | 585 | 1,030 | — |
| OFFER_DOCUMENT | — | 904 | — |
| OTHER_FILING | 37,150 | — | — |
| **Total pending** | **91,929** | — | — |

- `document_chunks`: **1,685,464** (handover live state 1,685,464 confirmed; drift +32,097 vs §2 focused on N200/concall deltas since).
- EOD/book recheck landed in §8faudit row (below) post-migration.
- Chunk index marker: `rows 1,398,908 / source_chunks_at_build 1,642,865 / built_at 2026-09-24T04:19:39` — **STALE by ~42,599 chunks**; rebuild deferred to `refresh` stage.
- Candidate guard verified in code: `CANDIDATE_SQL` already carries `AND COALESCE(cd.is_processed,0) <> 2`, so the quarantined poison row never reselects (matches TechPoison plan).

### 8c. migrate_event_version — exit 0 holding the lock (DROPs + honest-NULL CREATEs)

- Cmd: `python -m reality_engine.scripts.migrate_event_version --db <abs>/equity_intelligence.db` (script's own `_acquire_queue_lock`; lock acquired, no contention — exit would have been 3 otherwise).
- Wall: launched 2026-09-26T00:38:28 UTC, **exit=0**, stderr empty.
- Summary JSON: `tables=[document_chunks, corporate_documents, raw_documents]`, `indexes=[idx_chunks_event_date, idx_corpdocs_event_date, idx_rawdocs_event_date]`, `triggers=[trg_chunks_event_stamp, trg_corpdocs_event_stamp, trg_rawdocs_event_stamp]`, per-table `still_null=0`, `batches=3`, checkpoint cursors `{document_chunks: 1655631, corporate_documents: 116161, raw_documents: 9205}` (scanned=0/dated=0 this run — backfill already complete, DDL+trigger pass only).
- **Pre-migrate finding (ground truth): live triggers VIOLATED the honest-NULL contract.** Each trigger body contained `COALESCE(..., date('now'))` with fallback `event_source='ingest_time'` (read back verbatim from `sqlite_master` before the run). The migrate run's DROP+CREATE replaced all three.
- **Post-migrate verification (read-back from `sqlite_master`):**
  - `SELECT type,name FROM sqlite_master WHERE sql LIKE '%date(%now%)%'` → **NONE** — honest-NULL holds.
  - `sql LIKE '%ingest_time%'` on triggers → NONE; `ELSE 'unknown'` present in all three bodies; `COALESCE(NEW.event_date, NEW.<fallback>)` with no third arg.
  - Remaining `%now%` hits are only the substring inside `'unknown'` + column names (`event_date`/`known` fragments) — confirmed via regex: no time-function call remains in any trigger body.
  - NULL audit: `event_date IS NULL` counts = 0 on all three event tables.

### 8d. Staged DB tuning (TechDB text, one-shot holding the lock)

- First attempt (inline, 00:39:20 UTC): lock acquired, then harness kernel died (exit 130) mid-run — **zero index DDL landed** (verified: all 5 staged indexes MISSING post-kill; trigger honesty unaffected, re-verified NONE).
- Second attempt: `tmp_writer_tuning_oneshot.py` (one-shot script: 5× `CREATE INDEX IF NOT EXISTS` + `busy_timeout=180000 / cache_size=-256000 / temp_store=MEMORY / journal_mode=WAL`, non-blocking msvcrt queue-lock, exit 3 on contention; throwaway, deleted after landing) launched as the sole background writer (pid 12948). A duplicate foreground launch failed immediately with `PermissionError` on the lock file rather than overlap — **zero overlapping writers** (contention yielded, per contract).
- Status at append time: tuning writer RUNNING; index-present verification + per-index timings appended on its exit (next §8e row). No stage started meanwhile.

### 8e. Per-stage exits (sequential, one writer at a time)

| Stage | Exit | Note |
|---|---|---|
| tuning (5 indexes + pragmas) | exit=0 01:01 UTC (1,040.4 s) | 5/5 PRESENT, verbatim DDL; cache -256000 / timeout 180000 |
| annual_n200 | exit=0 01:02 UTC (attempt 1, 5 s, QUEUE_COMPLETE, 0 rows — slice drained) | env note: first launch logged auto(default); rerun path uses cmd-scoped env |
| annual_all | RUNNING since 01:02 UTC (sole writer, lock held; contract env in queue log) | 33/24,184 docs by 01:09 UTC; ~8–16 s/doc; first resource-guard memory wait (85.3% vs 85% target) logged, drain continuing |
| concall_all | QUEUED (starts on annual_all exit) | todo 9,140 |
| refresh (index rebuild) | QUEUED (starts on concall_all exit) | expect `source_chunks_at_build == COUNT(document_chunks)` after |
| business_map (`run_business_peer_graph --top-k 20`) | QUEUED (starts on refresh exit) | runner flags verified |
### 8f. Audit rows

| Time (UTC) | Pending ANNUAL | Pending CONCALL | Chunks | Index source_at_build | Writer |
|---|---|---|---|---|---|
| 2026-09-26 ~00:33 | 26,262 (+1 quarantined) | 9,140 | 1,685,464 | 1,642,865 (stale ~42,599) | NONE (pre-migrate probe) |
| 2026-09-26 ~00:38 | 26,262 | 9,140 | 1,685,464 | 1,642,865 | migrate_event_version exit=0 (lock held, DDL-only) |
| 2026-09-26 ~00:44 | — (recount on tuning exit) | — | — | — | tuning RUNNING pid 12948 (sole writer) |
| 2026-09-26 ~01:08 | 26,234 (+1 quarantined, sentinel id=5880 intact) | 9,140 | 1,695,058 | 1,642,865 (stale ~52,193) | annual_all RUNNING (sole writer, 28/24,184 docs) |
| 2026-09-26 ~01:27 | 26,167 (+1 quarantined, sentinel intact) | 9,140 | 1,719,484 | 1,642,865 (stale ~76,619) | annual_all RUNNING (sole writer, 95/24,184 docs) |
| 2026-09-26 ~03:05 | 25,860 (+1 quarantined, sentinel intact) | 9,140 | 1,813,642 | 1,642,865 (stale ~170,777) | annual_all third pass RUNNING (bg_61, sole writer, 23,782 todo) |

- SELL invariant untouched (no book writes this session).
- EOD max (live, read-only 00:47 UTC): `daily_price_delivery MAX(date)=2026-09-24`, 3,133,449 rows — matches handover EOD.
- Throwaway `tmp_writer_tuning_oneshot.py` removed 01:04 UTC (verified absent, no repo residue).
- 00:49 UTC writer audit: second Series writer sighted — `python -m reality_engine.pipeline.continuous_loop --agent` (pid 3000, spawned 00:48:26 UTC, ppid 5492). Module audit: separate `continuous.lock` in `logs/loop/`, no SQLite DML in module, `--agent` spawns an `omp` subagent tick only (no ingestion stages, no queue-lock path). 28 GB DB mtime 00:42 UTC is the tuner checkpoint (pid 12948, sole DB writer). Hourly `RealityEngine-AnnualDrain` tick coexists per design (skips on lock). Yield-on-contention rule stands: lock-held/busy on any stage → stop and report, never overlap.
- 00:51 UTC tuning progress: tuner pid 12948 alive (CPU 0:01:08, RSS ~309 MB, DB-writer only); index 1/5 PRESENT (`idx_docchunks_symbol_chunk`, DDL verbatim per staged text). Remaining 4 pending — large-table builds on a 28 GB DB, no stall signal (WAL 0 = checkpointed, writer holds lock). Business-map tables pre-existing (graph 20,620 / features 1,031 / runs 4); disk free 463.6 GB. No stage started until tuner exits.
- 00:53 UTC stage workload estimate (live CANDIDATE_SQL read-only): `annual_n200 todo=0` (slice drained — expect fast exit 0), `annual_all todo=24,184`, `concall_all todo=9,140` (informational `concall_n200 todo=6`, not in Slice-A order). Full `annual_all`/`concall_all` are multi-hour GPU drains; Slice-A order runs them sequentially after tuning via `run_ingestion_queue --only <stage>` with `GPU_DUTY=0.90/VULKAN_BATCH=96/EMBED_BACKEND=vulkan/:8099`.
- 01:01 UTC TUNING COMPLETE (tuner pid 12948 exit=0, elapsed 1,040.4 s holding queue lock, sole DB writer throughout): all 5 staged indexes PRESENT with verbatim staged DDL — `idx_docchunks_symbol_chunk` (489.3 s), `idx_docchunks_noindustry` (549.7 s), `idx_corpdocs_pending` (1.0 s), `idx_portfolio_open_sym` (0.0 s), `idx_rawdoc_type_pub` (0.2 s); session `cache_size=-256000 / busy_timeout=180000` confirmed post-run; trigger honesty re-verified (`date(now)` triggers=0); recount unchanged (chunks 1,685,464; ANNUAL pending 26,262 +1 quarantined; CONCALL 9,140). :8099 re-probed REACHABLE (`{"status":"ok"}`) before stages. Next: sequential `run_ingestion_queue --only annual_n200 → annual_all → concall_all → refresh → business_map` with `GPU_DUTY=0.90/VULKAN_BATCH=96/EMBED_BACKEND=vulkan/EMBED_SERVER=http://127.0.0.1:8099`.
- 01:02 UTC STAGE `annual_n200` exit=0 (attempt 1, 5 s, QUEUE_COMPLETE; `pending ANNUAL_REPORT: 0 (nifty200: 0)` — slice drained, 0 rows as estimated). NOTE: runner logged `EMBED_BACKEND=auto(default)` — the `set VAR=&&` chain did not propagate contract env into the stage; corrected to `cmd /c`-scoped inline env for subsequent stages so the queue log records `GPU_DUTY=0.90 VULKAN_BATCH=96 EMBED_BACKEND=vulkan EMBED_SERVER=http://127.0.0.1:8099`.
- 01:02 UTC STAGE `annual_all` RUNNING (sole writer, queue lock held; contract env confirmed in queue log: `GPU_DUTY=0.90 VULKAN_BATCH=96 EMBED_BACKEND=vulkan EMBED_SERVER=http://127.0.0.1:8099`; `pending ANNUAL_REPORT: 24,184 (nifty200: 0)`). Early throughput ~15–16 s/doc: NEULANDLAB 2026-08-29 ×3 docs → 313+520+492 chunks (PyMuPDF+RapidOCR, vulkan embed). Overlap probe: second `annual_all` invocation exited fast with `queue lock held by another run; skipping overlapping invocation` — zero overlapping writers verified live.
- 01:05 UTC `annual_all` throughput: 13/24,184 docs in ~100 s (~8–9 s/doc after warmup; batch 0–10 ok=10 failed=0 in 137 s; NEULANDLAB run ~3,800 chunks so far). Writer holds lock; multi-hour drain — subsequent stages (`concall_all → refresh → business_map`) stay queued behind its exit.
- Parent quarantine note 01:08 UTC cross-checked live: sentinel `id=5880 ADANIENT ANNUAL_REPORT is_processed=2` PRESENT, exactly 1 sentinel row corpus-wide; ANNUAL `is_processed=0` now 26,234 (was 26,262 at 00:33 UTC — delta = `annual_all` drain writes, not reselect); `CANDIDATE_SQL ... COALESCE(cd.is_processed,0) <> 2` confirmed in code. `annual_n200` exit=0 with `pending 0 (nifty200: 0)` and zero `no_chunks` lines — the 20x poison burn did NOT return. `annual_all` continues as sole writer (28/24,184 docs by 01:08 UTC, NH batch now ingesting).
- HANDOFF 01:10 UTC: `annual_all` (bg_22) continues RUNNING as the sole queue-lock writer (~33+/24,184 docs, ~8–16 s/doc, contract env, 0 failures). `concall_all → refresh → business_map` remain QUEUED behind its exit per Slice-A order. Lock discipline live-verified (3× `queue lock held … skipping` on overlap probes). Next writer action on `annual_all` exit: recount pending/chunks, run `concall_all`, then `refresh` (expect `source_chunks_at_build == COUNT(document_chunks)`), then `business_map --top-k 20`, one at a time.
- 01:14 UTC `annual_all` steady: 47/24,184 docs, batches 0–10/10–20/20–30/30–40 all ok=40 failed=0 (109–159 s/batch), ~12–18 s/doc sustained (NEULANDLAB→NEWGEN→NH→NIACL→NIVABUPA→NLCINDIA); resource-guard memory waits appearing (85–86% vs 85% target) but drain continuing, sole lock holder. Trajectory: pending ANNUAL falling (26,262→26,234), chunks rising (1,685,464→1,695,058+).
- 01:17 UTC writer audit: `annual_all` queue wrapper pid 16588 + stage child pid 4216 (`run_annual_report_ingest --batch 10 … ANNUAL_REPORT`, the queue's own subprocess — NOT a second writer). Peers beside it: MomentumF2 `f2_phase2.py` pid 11400 (pure numpy/ledger math on `/tmp/f2_*.npz`, writes only `/tmp/f2_placebo|cells.json`, zero DB handles) + one `mode=ro` COUNT query pid 17700 (read-only URI, `timeout=120`, no writes). Single-DB-writer invariant HOLDS: only the `annual_all` stage writes live DB.
- 01:17 UTC `annual_all` at 59/24,184 docs (NLCINDIA batch, ~10–21 s/doc, batches all ok/failed=0); sole lock holder; peers read-only (F2 numpy + one mode=ro COUNT). Pending trajectory falling, chunks rising; index rebuild (`refresh`) stays queued until drain writes stop.
- 01:18 UTC `annual_all` at 65/24,184 docs (NUVOCO batch, batch 50–60 pacing ~10–20 s/doc); sole lock holder; monitor bg_44/bg_46 set for 25–30 min rechecks; `concall_all → refresh → business_map` stay queued.
- 01:19 UTC recount (live, read-only, writer running): ANNUAL pending 26,195 (67 docs drained since 00:33 baseline 26,262); chunks 1,711,074 (+25,610); sentinel still exactly 1. `annual_all` at 67/24,184 (NUVOCO 1,104-chunk doc just landed); trajectory toward 0 confirmed.
- 01:21 UTC steady state: `annual_all` ingesting continuously (batch 60–70 zone, first CPU-bound resource-guard wait logged — cpu=92.7% vs 90% target — drain self-throttling per design, continuing). Writer = sole queue-lock holder (bg_22: wrapper pid 16588 + stage child pid 4216); monitor jobs bg_37/bg_39/bg_44/bg_46/bg_49 recheck at 20–30 min cadence; `concall_all → refresh → business_map` stay QUEUED per Slice-A order. Handoff condition: next writer turn starts from `annual_all` exit line in `ingestion_queue.log`, recounts pending/chunks, proceeds one stage at a time.
- 01:21:48 UTC monitor (bg_27): `annual_all` at 77/24,184 docs (OLECTRA batch, ~12 s/doc); sole lock holder; 0 failures; monitors bg_37/bg_39/bg_44/bg_46/bg_49/bg_51 queued for cadence rechecks.
- 01:23 UTC monitor: `annual_all` at 83/24,184 docs (PARADEEP batch, ~18 s/doc); sole lock holder; 0 failures; pace ~13–18 s/doc sustained → full slice is multi-day; `concall_all → refresh → business_map` stay QUEUED per Slice-A order behind its exit.
- 01:24 UTC monitor: `annual_all` at 88/24,184 docs (PCBL batch); sole lock holder; throughput steady ~12–22 s/doc with periodic resource-guard waits (memory 85% / cpu 90% targets); monitor bg_52 queued for +25 min recheck.
- 01:26 UTC monitor: `annual_all` at 93/24,184 docs (PCBL batch); drain healthy, ~17 s/doc; monitors bg_52/bg_53 queued for +25 min cadence; remaining stages QUEUED.
- 01:27 UTC recount (live, read-only, writer running): ANNUAL pending 26,167 (95 docs drained since 00:33 baseline 26,262); chunks 1,719,484 (+34,020); sentinel exactly 1. `annual_all` at 95/24,184 (PCBL 343-chunk doc just landed); trajectory toward 0 on track.
- 01:29 UTC monitor: `annual_all` at 102/24,184 docs (PETRONET batch, ~29 s/doc on 795k-char doc); sole lock holder; queue log shows only lock-held skips beside the runner (zero overlap); monitors bg_37/bg_39/bg_44/bg_46/bg_49/bg_51/bg_52/bg_53/bg_54 queued for cadence rechecks.
- 01:30 UTC monitor: `annual_all` at 107/24,184 docs (PETRONET batch 100–110 zone, ~17–23 s/doc); sole lock holder; monitor bg_55 queued for +25 min recheck.
- 01:31 UTC milestone: `annual_all` batch 100–110 done (ok=110 failed=0 cumulative, 190 s for the batch); at 110/24,184 docs, zero failures across all 11 batches. Pace holding ~14–20 s/doc (PETRONET run). Sole lock holder; remaining stages QUEUED.
- 01:31 UTC recount (live, read-only, writer running): ANNUAL pending 26,152 (110 docs drained since 00:33 baseline 26,262); chunks 1,723,457 (+37,993); sentinel exactly 1. Batch 100–110 milestone confirms 1:1 pending↔docs (110 = 110).
- 01:31:24 UTC monitor (bg_37): `annual_all` at 111/24,184 docs (PETRONET 98-chunk doc, 13 s); batch 100–110 closed ok=110 failed=0; sole lock holder; remaining stages QUEUED.
- 01:31:44 UTC monitor: `annual_all` at 112/24,184 docs (PETRONET 82-chunk doc, 12 s); pace ~12–23 s/doc; sole lock holder; remaining stages QUEUED.
- 01:32:45 UTC monitor (bg_39): `annual_all` at 116/24,184 docs (PFIZER batch — 259-chunk then 17-chunk docs, ~12–16 s/doc); sole lock holder; remaining stages QUEUED.
- 01:33 UTC monitor: `annual_all` at 118/24,184 docs (PFIZER 221-chunk doc, 18 s); drain healthy; sole lock holder; remaining stages QUEUED.
- WRAP-UP ~01:33 UTC (run budget reached): writer leaves `annual_all` RUNNING as sole queue-lock holder (118/24,184 docs at last check, batches all ok/failed=0, ~12–29 s/doc, contract env `GPU_DUTY=0.90 VULKAN_BATCH=96 EMBED_BACKEND=vulkan`). Completed this session: migrate exit=0 (honest-NULL verified, date(now)=NONE), tuning exit=0 (5/5 indexes verbatim), `annual_n200` exit=0 (0 rows, no poison re-burn; sentinel id=5880 intact, 1 row). Trajectory: ANNUAL 26,262→26,152, chunks 1,685,464→1,723,457. QUEUED in Slice-A order: `concall_all` (todo 9,140) → `refresh` (expect source_chunks_at_build==COUNT(document_chunks)) → `business_map --top-k 20`. Resumption: read `annual_all` exit line in `ingestion_queue.log`, recount, run next `--only <stage>` with cmd-scoped contract env, one writer at a time; yield on lock contention.
- 02:03 UTC WATCHDOG TIMEOUT on bg_22 (3600 s wall, NOT a stage failure — kill landed mid-`annual_all`, last ingest line 02:01:57 `[212/24,184] PTCIL 426 chunks`; queue-log wrapper never printed its exit line). Post-kill state: queue lock FREE (non-blocking msvcrt acquire+release ok); recount ANNUAL pending 26,061 (201 docs drained since 00:33 baseline), chunks 1,751,385 (+65,921), sentinel exactly 1. Only harness python (pid 17452) alive — no orphan ingest processes. Hourly 01:40 UTC watchdog tick correctly skipped on lock. Resumption: `run_ingestion_queue --only annual_all` re-enters at the next CANDIDATE_SQL row (resumable, skips local_file_path-set rows) with cmd-scoped contract env.
- 02:03 UTC `annual_all` RESUMED as sole lock holder (bg_58, contract env in queue log; `pending ANNUAL_REPORT: 23,983` = 24,184−201 drained, matches recount). First resumed batch hit 10× `download failed PIRAMALFIN 2026-08-29: http_404` (dead BSE source URLs — download-side, not chunking; rows stay pending, no poison loop) then continued into OCR ingest. Resumability confirmed: re-entry continued past the kill point, no duplicate rows.
- 02:05 UTC resumed drain healthy past the 404 batch: 17/23,983 docs (PTCIL 258-chunk doc, 9 s — pace back to normal after the dead-URL batch); sole lock holder (bg_58); batches continue ok; remaining stages QUEUED.
- 03:05 UTC second WATCHDOG TIMEOUT on bg_58 (3600 s wall, NOT a stage failure — kill landed mid-`annual_all` at ~212/23,983 SCI batch, 03:03 UTC; queue wrapper again killed before its exit line; NOTE: orphan ingest output kept flowing ~2 min past kill — stage child drains in-flight batch before dying). Lock verified FREE, :8099 `{"status":"ok"}`, no orphan python beside harness. `annual_all` relaunched third pass (bg_61, contract env): `pending ANNUAL_REPORT: 23,782` = 24,184−402 drained, matching trajectory (201+201 across the two killed passes). PIRAMALFIN 404 batch recurs at re-entry head (dead BSE URLs, rows stay pending).
- 03:08 UTC `annual_all` FOURTH pass (bg_62, max 3600 s window, contract env): `pending ANNUAL_REPORT: 23,781` (one row resolved between passes — PIRAMALFIN 404 set is static at re-entry head, rows stay pending by design). Lock re-acquired by writer; sole-writer invariant holds.
- DB-tuning scalar proof (manager session, post-edit): `cache_size = -256000`, `busy_timeout = 180000`, `journal_mode = wal`, `mmap_size = 1073741824` (bare-sqlite probes showing -2000/5000 are invalid — they never apply `config.SQLITE_PRAGMAS`; manager connections apply staged values at open). Already-open drain connections keep startup pragmas; new connections pick up -256000 immediately. Timing noted mid-drain, no restart forced.
- DEDUP NOTE (corrected with code evidence — NOT a bug): `PDF already ingested … (N chunks, 0 fts)` is the sha256 idempotency path working as designed (`pdf_ingestor.ingest_pdf:729-736` — sha lookup on the DOWNLOADED bytes, skip when chunks>0; log line at :735). Historical hits (OFSS/PFC/MARUTI/RELIANCE 2026-09-22–24 + 02:04/03:07/03:09 UTC re-entry overlaps) resolve in 5–72 s with zero new chunk writes vs 8–32 s full ingests — but they still pay download+extract+embed-session cost. Post-drain optimization (not correctness): order candidates or pre-check sha before download is impossible (sha is of file bytes, unknown pre-download) — real saving would need BSE `Content-Length`/ETag memoization in `official_filing_client.archive_link`, out of Slice-A scope.
- 03:10 UTC fourth pass healthy past the 404 head: 15/23,781 docs (SCI 458-chunk doc, 13 s; dedup skip on re-entry overlap resolved 566 chunks in 56 s with zero new writes); sole lock holder (bg_62); remaining stages QUEUED.
- 03:10 UTC CONTROLLED STOP for run settle: fourth pass (bg_62) cancelled by writer after health confirm (15+/23,781 docs, pace normal); lock verified FREE post-cancel; only harness python alive; ingest tail static at 03:10:26 extract line (in-flight batch drains out, no new writes). Drain is resumable at next CANDIDATE_SQL row — next writer runs `run_ingestion_queue --only annual_all` (cmd-scoped contract env), then `concall_all → refresh → business_map` one at a time; yield on lock contention.
