# Current Plan — 2026-09-27 evening (SUPERSEDES all tasks/*.md task docs for execution)

> Prior task files (`plan.md`, `todo.md`, `SESSION_HANDOVER_*`, `desk_*`,
> `tech_pipeline_*`, `wave_*`, `verification_*`, `next_wave_*`,
> `strategy_tracker.md`, closeouts) are HISTORICAL RECORD. Strategy verdicts
> (F1/F2 KILL, REVOKED list, promotion bar) still stand as truth; every
> execution plan, stage order, and ETA in them is STALE. This file is the
> only execution authority until replaced.

## 1. Ingest state (parked 2026-09-27 ~17:40 IST, batch edge 190-200)

- Writer STOPPED at clean edge (`batch 190-200 done: ok=186`), pid 22348
  terminated, no python writers live, WAL static 160KB, queue lock FREE.
- Position: concalls 196 flipped this run (8,864 pending / 9,652 done);
  PPT bulk 520 flipped + 65 genuinely-fresh tail pending;
  chunks 2,031,900. Resumption = next candidate row, zero duplicates.
- Schedules: News/Forecast/Continuous Disabled; annualdrain hourly Ready
  (7s no-op, lock-skips); CapacityLoop/sebi-weekly/PowerGrid need elevated
  disable (Access denied from harness). Embed-server DOWN, DirectML fallback.
- Staged fixes in /tmp (post-drain): txn-close-before-add_chunks +
  incremental _known_ids (PROVEN 62-1638x); trigger AFTER→BEFORE demoted to
  hygiene, BuildEventVer-owned. Runners: /tmp/run_ppt_downloaded.py,
  /tmp/concall_bulk_m2.py, /tmp/concall_shootout.py, /tmp/ppt_batch_flip2.py.

## 2. Next session: QUERIES, not ingest (user order — DB full-of-crap check)

1. Quarterly-table audit: 4+ quarters × 200 N200 symbols?
2. N200 concall chunk-level gate (chunk doc_ids DIRECTLY, never corp ids):
   event trio + fiscal ≥0.5 + guidance text + FTS/embed on 2,927 rows.
3. Industry coverage on N200 chunks (101/101 NULL seen on small-cap R3 rows;
   N200 masters 0/200 null — confirm on chunk rows).
4. Distillation gaps (NOT ingest): daily market-cap series, revenue segments,
   suppliers/vendors, event-study abnormal returns, growth expectations.
   Tables exist as skeleton (ripple 76 rows, moat/bmp ~2.6k deterministic
   seed); market-response unbuilt; provenance (event/fiscal/symbol/date)
   verified present.

## 3. Rules carried forward

- Single SQLite writer + queue lock; loops stay parked till user says so.
- No `reality_engine/` edits mid-drain; /tmp scripts only.
- Quarantine predicate on every inference read; honest-NULL triggers;
  fiscal ≥0.5 + event_date discipline (never one for the other).
- Capital PARKED, paper only (F1/F2 KILL, REVOKED never re-quoted).
