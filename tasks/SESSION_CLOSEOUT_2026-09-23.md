# Session Closeout — 2026-09-23 (self-contained; new session starts here)

> Written because the prior session carried 262k+ tokens of context that will NOT
> transfer. Everything below is verified against the live tree/DB/processes at
> closeout time. Trust this doc + the four brief docs in §1; distrust any memory
> of conversation not written here.

## 0. Objective (unchanged, user-stated)

Build a **cause→effect model** that figures out **why prices moved** and whether the
move is **explained by available information** — residual = mispricing → **BUY / SELL /
HOLD equities in the cash segment on model predictions only**, maximizing **return on
capital deployed**.

## 1. Read these four docs first (in order)

1. `tasks/next_wave_plan_2026-09-23.md` — the plan. Dirty truth: warehouse/substrate/
   ledger/ensemble/nightly all exist, but every measuring layer measures something
   else (SELL sign-inverted, fixed 18%/6% bracket, constant residual ≈0.89, no time
   axis on levels, 84% of universe mapped to Microcap). P0→P4 phase order + tightened
   promotion bar (§5) + 6 open decisions (drain scope, bracket rule, fill convention,
   SELL scoring, substrate versioning, universe mapping).
2. `tasks/strategy_tracker.md` — T1–T12 tested/pending/promotion-log. **SELL +527bps
   REVOKED** (long-framed accounting artifact, T4/T5). T12: KEEP bge-small (substance
   0.50/0.69 vs base 0.00/0.00). Promotion bar: cohort-clustered ≥+500bps net of
   measured cost, ≥30 weekly cohorts, 2 regimes, hit CI lower >0.5, placebo ≈0.
3. `tasks/session_flowchart.md` — mermaid WHY-chain for the whole session (living doc).
4. `tasks/modeling_bucket_list.md` — 6 idea families; NEXT = momentum-vs-reversal by
   horizon (blocked on drain freeing the DB writer).

Supporting: `tasks/next_wave_attribution.md` (3-slice contract), `tasks/test_perf_baseline_2026-09-22.md`
(suite speed: 738 passed, 199s under xdist — contention-bound, serial-profile next),
`tasks/local_only_preliminary_findings_2026-09-22.md` (7 local fixes, verified 11/11).

## 2. Live processes (verified via hub ps at closeout)

| Process | PID | State | Notes |
|---|---|---|---|
| `embed-server` | 15852 | ready, 44m uptime | `:8099` verified (health ok, 384-dim norm 1.0). Died once cleanly after 1.75M tasks/13h; restarted |
| `ingest-annual-resume` | 22376 | ready, detached+persistent | annual_n200 drain, GPU 100% (duty 1.0 + Vulkan 128 + ONNX batch 64 + queue batch 20), backend=vulkan |
| `RealityEngine-AnnualDrain` | — | Scheduled Task, hourly, Ready (next 14:40) | Survival loop: reboot/power/session/internet-proof. Files: `reality_engine/scripts/run_annual_drain.cmd` + `install_annual_drain_task.py` |

Older `ingest-annual-*` rows (90/90b/100/full/n200) are **exited history, not casualties** —
only the two `ready` rows above matter. Restart policy: `restart=no` everywhere; queue
self-retries stages (20×); single SQLite writer — NEVER co-run a second GPU/DB job.

## 3. GPU 100% order (user order, executed + verified in logs)

- `REALITY_ENGINE_GPU_DUTY=1.0` (sleep disabled) + `REALITY_ENGINE_VULKAN_BATCH=128`
- Code defaults raised: ONNX `batch_size` 32→64 (`onnx_embedder.py:66`), queue `--batch`
  5→20 (`run_ingestion_queue.py:70`). `ingest-workers=1` kept (single-writer + DML lock).
- `run_ingestion_queue.py` logs `GPU_DUTY/VULKAN_BATCH/EMBED_BACKEND/EMBED_SERVER` at
  every stage start (env-echo patch). `backend=vulkan` confirmed on log lines.
- Caveat: duty gates the **embedder only** — RapidOCR DirectML has no duty concept.
  If display flickers when user returns: drop to 0.9 (or `REALITY_ENGINE_OCR_GPU=0`).
- Measured pace: ~12–20s/doc small docs, ~85s/doc on 400–850-chunk annuals; gaps in
  Task Manager GPU graph are pipeline bubbles (download/extract/commit stages use no
  GPU), not throttling. Compute-1 at 0% is normal (all submits on queue 0).

| Pending docs | 92,092 (`local_file_path IS NULL`) |
| Chunk index | built 2026-09-21, 241k rows (stale vs corpus — rebuild after drain) |
| Drain progress | ~91/1,231 on resume run (doc_id ~7,673), ~20–85s/doc by size |

### Verify commands (run from project root)
```bash
python reality_engine/cli.py portfolio-ledger --horizons 30,90,180,365 --universes nifty50,midcap150,smallcap250,microcap250
python reality_engine/cli.py run-calibration
python -m unittest reality_engine.tests.test_action_thesis reality_engine.tests.test_move_attribution reality_engine.tests.test_eod_corrector
```

## 5. Test state

- Suite **714 green by shard** (middle 178 + tail 172 + first 364). Full-discovery
  exit-5 kill is process accumulation on 16GB, not a defect — shard-by-half is the
  supported runner. pytest 9.1.1 + xdist 3.8.0 installed dev-only (manifest untouched).
- 58/58 on predictor/action/attribution modules; 25/25 action-thesis; 13/13 nightly;
  40/40 horizon+ledger; 19/19 embed prototype; 3/3 index backfill.
- Hermeticity fix landed: fixture `AgentOrchestrator` screener now bound to hermetic
  repo (was leaking live ENI −1.38 for symbol "X").

## 6. What is TRUE vs what is REVOKED (do not regress)

- ❌ REVOKED: SELL +527bps / 46-46 wins — long-framed terms (`target > entry` on all 52
  SELL rows), `mark_to_market` mirrored stop booked as gain. Honest 20d read: +790bps,
  n=16, 12 symbols, 5 weekly clusters, one index-down regime (plan §2A).
- ❌ REVOKED: blended book "+29.8 first profit" — artifact sum, not edge.
- ❌ REJECTED (do not revisit): confirmation filter (1W/29L), trend-continuation entry.
- ✅ HOLDS: predictor honesty (levels GATE, flows VOTE), dislocation gate (2σ),
  factor-agreement BUY gate, quality_broken widening (as *selection*, not P&L),
  calibration gate behavior (`applied: false`), embed KEEP-small verdict.
- ✅ HOLDS: 401-row wave acceptance, 90 evaluated horizon cells, nightly `track_record`
  stage (13/13), index 4-leg backfill, floor-units fix, single-embed search.

## 7. Next actions (in order, from plan §4)

1. **P0 honest book** (needs drain checkpoint first — single writer): SELL framing
   invariant (`target < entry < stop`) + `record_action` regression test; per-scrip
   vol-scaled brackets (trailing-σ, clamped — GARCH later); quarantine join in seed +
   every book/ledger read (4,770 ledger rows join quarantined `INE_AUTO_*` masters);
   re-seed; excess rebuilt on market closes with cohort clustering.
2. **09-21/09-22 EOD backfill** (CSVs on disk in `data/bhavcopy/`): behind a drain
   checkpoint, never concurrent. Resolves forward windows for 121 open BUYs + 6 SELLs.
3. **P1 measurement grid** (read-only): horizon × regime × universe + shuffle placebo.
4. **P2 selection**: Beneish/Altman/Piotroski veto + substrate versioning (history
   columns — prerequisite for honest delta voting).
5. Then P3 (VIX/GARCH/investor-majority) → P4 (OU/Kelly/EVT, only past the bar).

## 8. Open decisions — RULED 2026-09-23 (P0 unblocked on 1–4, 5–6 as stated)

1. Drain scope: **slice-first** — finish running `annual_n200`, then concall_n200; full 93k trail behind, never gate P0.
2. Bracket rule: **trailing-σ percentile, clamped** (GARCH later as P3 refinement).
3. Fill convention: **close-through-the-level default**, touch-fill as sensitivity.
4. SELL scoring: **avoided-loss-vs-holding** (cash segment can't short).
5. Substrate versioning: **side table now**, merge into live DB after drain.
6. Universe mapping: **keep 4 + printed per-universe n and unmapped list**.

## 9. Standing rules (from this session's scars)

- NEVER `git stash`; no `repository.py`/`schema.sql` edits; no live-row deletes.
- Single SQLite writer: drain owns GPU+DB — no second compute task until it frees.
- Tests hermetic on temp DBs; bind fixture screeners to hermetic repos (live leak proven).
- 384-dim lock-in: vectors/index/fusion assume it; any model change = migration project.
- Chart + tracker update rule: after every task action, update nodes + timestamp.
- Suite runner: shard-by-half (`test_action_thesis`→`test_news_explainer`, then rest);
  full discovery exit-5 is environmental.
