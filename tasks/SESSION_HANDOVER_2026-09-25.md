# Session Handover — 2026-09-25 (self-contained; new session starts here)

> Prior session carried 500k+ tokens that will NOT transfer. Everything below verified against the live tree/DB/processes at handover time. Trust this + `tasks/test_findings_2026-09-24.md` (§§1–14); distrust unwritten memory.

## 0. Objective (user-stated, unchanged)

Cause→effect model: why prices moved, residual = mispricing → cash BUY/SELL/HOLD maximizing return on capital. Current capital frame: ₹1L on 2021-10-27 + ₹50k monthly SIP → ₹30.5L in; benchmark post-tax XIRR **7.06%**, signals trail 13–16bps. Drawdown tolerance 40% (worst observed 11.65%).

## 1. Read first (in order)

1. `tasks/test_findings_2026-09-24.md` — §§1–14: signal audit, P0/P1 verdicts, backtest, versioning, fiscal spec, drain verdict. The evidence base.
2. `tasks/next_wave_plan_2026-09-23.md` — prior plan (P0→P4 order still stands).
3. `tasks/strategy_tracker.md` — T1–T12 + promotion bar (≥+500bps clustered net, ≥30 cohorts, CI lower >0.5, placebo≈0).

## 2. Live processes (hub ps at handover)

| Process | State | Notes |
|---|---|---|
| `embed-server` PID 22792 | ready, detached+persistent | Vulkan-only :8099, bge-small q8_0, verified 200/384/1.0 |
| `ingest-annual-resume-v2` | exited 0 | annual_n200 done (233/234, QUEUE_COMPLETE, backend=vulkan) |
| `ingest-concall-n50` | exited 0 | 377/378 concalls, ~38min |
| `chunk-index-rebuild` | exited 0 | 1,398,908 rows dim 384, fresh |
| Hourly `RealityEngine-AnnualDrain` Scheduled Task | Ready | reboot watchdog; queue lock makes ticks skip when writer busy |

Writer is FREE. No GPU/DB job running. embed-server survives session exit; drains resume via scheduler + lock.

## 3. What is TRUE vs REVOKED

- ✅ P0 honest book: invariant on write, 0 bad SELLs (52 deleted, backup `equity_intelligence.pre_p0_20260924_142645.bak.db`), vol brackets 11.87–22.93%, 820 rows. Backup confirmed on disk.
- ✅ P1 grid + placebo: reject/reject (BUY −328bps, SELL +285bps, placebos ≈0). Rebuild 09-26 with votes: still reject (real leg immobile — votes don't create actions until flow runs; flow now built: book 841, closed 66).
- ✅ Versioning: moat/policy/ripple history tables additive; predictors vote on dated deltas; SBIN −1 live on-ledger 09-24; supply 25 votes; policy correctly idle.
- ✅ Fiscal: extractor + columns + 292,246 labeled (20.8%); spec §11.
- ✅ SIP backtest reconciled: artifact `sip_signal_legs_post_tax_2026-09-24.json`, 33 tests green, tax schedule source-cited.
- ❌ REVOKED (never regress): SELL +527bps artifact, blended +29.8 profit, confirmation filter, trend entry.
- ❌ Drain verdict: CONDITIONAL HOLD — 24,185 annuals pending stay HELD until event-date/version columns land. Fiscal-only batches may flow.

## 4. Open work (in order)

1. **Event-date/version columns** (unblocking 24k release): add + stamp at insert, same pattern as fiscal.
2. **Guidance-change diff** on concalls (panel's top extraction upgrade — feeds delta contract).
3. **Breadth**: peer re-runs for multi-date keys beyond SBIN; policy's first genuine revision.
4. **P2 forensic veto** (Beneish/Altman/Piotroski) + GARCH/VIX/investor-majority (P3) — only past the bar.

## 5. Guardrails

- Single SQLite writer; queue lock; never co-run GPU/DB jobs.
- Additive schema only; quarantine joins on reads, never delete; no `git stash` (globally shared).
- Soft 90% resource targets (not OS-enforced 97%); GPU_DUTY 0.90 / Vulkan batch 96.
- Promotion bar unchanged. Placebo required on every grid. Scope caveats stamped on artifacts.
