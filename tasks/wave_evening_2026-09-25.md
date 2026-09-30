# Evening Wave Contract — 2026-09-25 (frozen; all slices read first)

## Shared goal
Mumbai prop-desk edge + 10cr book. CEO verdict stands: paper only until a leg clears the bar
(cohort-clustered ≥+500bps net measured, ≥30 weekly cohorts, 2 regimes same sign, hit CI lower>0.5, placebo≈0).
Tonight: unblock the writer pipeline (triggers → indexes → drain → refresh), run F1/F2 paper screens,
re-verify ledger+calibration+gate, and fix the PUA poison class at its root.

## Global constraints (all slices)
- Denylist: NEVER edit `reality_engine/db/repository.py` or `reality_engine/db/schema.sql`; no live-row deletes;
  no `git stash`; no destructive ops; no new packages without need.
- REVOKED stays revoked: SELL +527bps, blended +29.8, T10 confirmation, T11 trend. Never re-quote as edge.
- Single SQLite writer + queue lock (`reality_engine/data/ingestion_queue.lock`); NEVER co-run GPU/DB jobs.
  ONLY slice A holds the writer. All other slices: read-only live DB (`mode=ro`/dry-run/SELECT) or temp DBs.
- GPU_DUTY 0.90 / VULKAN_BATCH 96 / EMBED_BACKEND vulkan / :8099. No full suites beside the writer;
  verification is the <15s 5-file gate only, serial.
- SELL invariant at write: SELL ⇒ `target < entry < stop` (assert, abort on violation). SELL scored
  avoided-loss-vs-holding, never short-notional P&L.
- No formatters/linters/project-wide suites; no edits outside owned files; call sibling logic, never copy it.

## Frozen interfaces
- `BOOTSTRAP {factor 0.30, quality 0.25, policy 0.25, supply 0.20}` frozen; levels GATE, flows VOTE.
- Price convention: close usable iff finite>0 from `daily_price_delivery`; trades at closes; no fwd-fill for
  trading; valuation carries last close; FIFO; FY LTCG exemption; no cross-year carry; risk-free 0.
- Cost stack: 50bps impact prior + STT 0.1%/side + 5bps other (flagged priors) + FIFO STCG 20% / LTCG 12.5%
  above ₹1.25L/FY post Finance (No.2) Act 2024 + intra-FY harvest. SIP_START 2021-10-27, BREADTH_START 2025-09-01.
- Quarantine predicate on EVERY inference read: exclude `INE_AUTO_*` / `substrate_quarantine` keys.
  Poison sentinel: `corporate_documents.is_processed=2` + `AND COALESCE(cd.is_processed,0)<>2` in candidate scans.
- Event-date contract (honest-NULL): `event_date = COALESCE(explicit, fallback_date)` else NULL with
  `event_source='unknown'`; NEVER `date('now')`. Content/embeddings never rewritten.
- Horizons 30/90/180/365 × Nifty50/Midcap150/Smallcap250/Microcap250; ISO-week cohorts; XS-matched primary,
  index-relative secondary; shuffle-entry placebo ≈0 required.
- Live state at dispatch: chunks 1,685,464 / NULLs 0; corp pending ~91,929 (ANNUAL 26,262 incl. 1 quarantined);
  EOD max 2026-09-24; book 681 closed/160 open (BUY 58/SELL 8/HOLD 615 closed); ledger N50 −20bps / Midcap −335bps.

## Slice A — WriterSequence (owns the queue lock + drain execution; NO other slice writes live DB)
Target: triggers honest-NULL → 5 indexes → drain annual_n200 → annual_all → concall_all → refresh → business_map.
Files owned: `tasks/desk_drain_progress_2026-09-25.md` (append). Runs (never edits): `scripts/migrate_event_version.py`,
`scripts/run_ingestion_queue.py`, `scripts/build_chunk_vector_index.py`, peer-graph runner.
Steps: 1) probe :8099 reachable else abort slice and report; 2) migrate script holding lock (DROP+CREATE triggers,
verify `sqlite_master` has no `date('now')`); 3) apply staged DB-tuning block from `tasks/tech_pipeline_2026-09-25.md`
DB section via a one-shot python holding the lock; 4) sequential queue stages one at a time
(`--only annual_n200` → `annual_all` → `concall_all` → `refresh` → `business_map`), per-stage exit + recount;
5) expect `source_chunks_at_build == COUNT(document_chunks)` after refresh.
Acceptance: progress file shows per-stage exits + pending trajectory + index freshness; zero overlapping writers.

## Slice B — ForensicF1 (read-only; owns `tasks/desk_f1_screen_2026-09-25.md` only)
Target: F1 forensic-avoidance paper screen over live financials (Gate0 AGENTS §11 + Gate1 F1–F7 per
`tasks/desk_forensic_2026-09-25.md`), PIT lags (FY usable ≥ Jun-01; quarterly +45d), quarantine predicate.
No code edits, no live writes. Report: veto rates, avoided-loss excess per 30/90/180/365 XS-controlled,
weekly cohorts, placebo; kill verdict if bar unmet.
Acceptance: report file exists with rates + 4-horizon cells + explicit promote/kill call.

## Slice C — MomentumF2 (read-only; owns `tasks/desk_f2_grid_2026-09-25.md` only)
Target: F2 vol-scaled continuation-momentum paper grid, price-only PIT (trailing-20σ floor clamped [0.5,8.0],
≥2σ + factor agreement, k_target 3/k_stop 1, SELL mirrored), XS-matched primary, 30/90/180/365, weekly cohorts,
placebo. Pre-registered kill: 30D net clustered <+500bps after measured costs → kill, no k-tuning.
No code edits, no live writes.
Acceptance: report file exists with 4×4 cells + placebo + explicit promote/kill call.

## Slice D — VerifyGate (owns `tasks/verification_evening_2026-09-25.md` only)
Target: read-only + scoped proofs: `portfolio-ledger --horizons 30,90,180,365 --universes
nifty50,midcap150,smallcap250,microcap250`; `run-calibration`; 5-file gate serially
(`test_horizon_excess test_sip_backtest test_portfolio_ledger test_event_version test_desk_backtest`,
stamp wall time); live counts (EOD max, actions splits, chunks, pending by type, PRAGMA event cols).
Yield immediately if writer contention appears. No code edits.
Acceptance: report file exists with verbatim outputs + met/unmet mapping to the 5 goal criteria.

## Slice E — PuaFallback (owns `reality_engine/processing/document_parser.py` helper +
`reality_engine/ingestion/pdf_ingestor.py` call-site guard + `reality_engine/tests/test_pua_fallback.py` only)
Target: kill the poison CLASS at its root. Proven root cause: 314k chars are U+F0xx PUA (299,549 PUA, 0 ASCII)
from unembedded custom font; prune() passes through; BPE collapses to 2 ids with empty decode → 0 chunks.
Change: PUA-rate detector (fraction of chars in U+E000–U+F8FF; threshold 0.5 pre-registered) in document_parser;
pdf_ingestor call-site: when PUA-rate exceeds threshold, route the page/PDF to the scanned-image OCR path
(RapidOCR pixmap) instead of trusting the text layer; if OCR also yields nothing, return status
`no_text_layer` (distinct from `no_chunks`) so the queue can quarantine without conflating causes.
No live DB writes; proof on temp files + synthetic PUA fixtures only (never the live ADANIENT PDF path writes).
Acceptance: `test_pua_fallback.py` green (`python -m unittest reality_engine.tests.test_pua_fallback`;
synthetic PUA text triggers OCR route; normal text unaffected; `no_text_layer` status asserted).
