# Test Findings — 2026-09-24 (Nifty-50 ground + 10-stock panel + P0/P1)

Objective: cause→effect attribution — explain WHY price moved, residual = mispricing → cash BUY/SELL/HOLD for return on capital.

## 1. Signal audit (live DB, read-only via db_manager)

- move_attribution: 136,642 rows. Material (is_material=1): 43,789, mean explained **0.110**, mean residual **0.890**; 22,423 material rows (51%) with explained_total = 0; **0 rows** with explained > 0.5 (histogram: 0.0→22,526 · 0.1→4,293 · 0.2→6,061 · 0.3→10,899 · 0.4→10).
- Direction emission on material rows: factor **42,346** / quality **0** / policy **0** / supply **0** (n=43,789).
- Mean weights on material rows: factor 0.226 / quality 0.271 / policy 0.145 / supply **0.358** — 63% of weight parked on mute lenses.
- regime_tag: single value `'*'` — no conditional reasoning exists. investor_majority spread exists (promoter 89.6k / all 33.8k / retail 10.6k / FII 2.6k).
- Arithmetic meaning: share = weight × 1{predicted == sign(realized)} — a weight of agreement, not a fraction of the move. Carries no magnitude.

**Verdict: the residual is structurally constant. All three red flags fire. Strategy results scored against it are uninformative, not wrong.**

## 2. Root cause (dated evidence, not code)

- Quality/policy/supply predictors return neutral because their inputs are **levels without history** (moat score, ENI snapshot, ripple edge with no time axis). A constant cannot explain a move; returning 0 is correct behavior.
- Fix = storage cadence/versioning (moat/ENI/ripple history columns), not predictor rewrites. Factor votes only because its input is a genuine flow (prior-day change).

## 3. Downstream symptoms (same root cause)

- Calibration `applied: false` every run — starved (one voting member), not healthy.
- model_explainer_rankings vs ledger disagree about best explainer — learning path and attribution path disagree; don't average.
- Peer neighbours match on survivors (often size/moat_rating) — TITAGARH→ULTRACEMCO/POLYCAB/DLF; 13/29 features dropped as near-constant.

## 4. 10-stock panel attribution (2026-09-18, 7yr annuals + 1yr concalls/PPTs)

Mean explained **0.09**, residual **0.91**. 6/10 rows exactly 0.0. Only factor ever fires (4/10 agree). See §1: panel is one more sample of the same constant.

## 5. P0 book (done, verified)

- record_action invariant on write (SELL ⇒ target<entry<stop; BUY mirrored; HOLD levels None). Backup: equity_intelligence.pre_p0_20260924_142645.bak.db.
- 52 stale long-framed SELLs DELETEd (BUY-framed, 46 already scored sign-inverted); backfill rejected (would rewrite scored history).
- Book now 820 rows (165 BUY / 9 SELL / 646 HOLD); 0 bad SELLs; BUY widths 11.87–22.93% (61 distinct); SELL 2.31–4.79% mirrored 3:1; 571 quarantined + 563 non-N50 skipped on reseed.
- Blocker noted: max EOD was 2026-09-18 at reseed → backfilled 09-19→09-23 (14,484 rows, local cache) so forward windows resolve.

## 6. P1 grid + placebo (done, reject/reject)

- Artifact: reality_engine/data/reports/p1_grid_nifty50_2026-09-24.json (book 820, EOD max 09-23).
- BUY n=5/3 cohorts, clustered −328bps, hit CI lower 0.000 → REJECT. SELL n=7/3 cohorts, clustered +285bps, hit CI lower 0.116 → REJECT. Placebos ≈0 (honest gate, strategies fail it: need +500bps, ≥30 cohorts, CI>0.5).
- All 4 horizons identical (realized-window min(closed,entry+h) — T9 diagnostic).

## 7. Substrate state + degradation (report alongside every answer)

- Chunk index 1,398,908 rows dim 384 (fresh 04:19); business map 1,031 anchors/20,620 pairs; company peers 2,577 anchors/51,540 pairs; quality peer moat 2,653/profiles 2,652.
- Quarantine 1,377 rows. Unconditional rankings 69,500/69,500; single-country geo 3,437/3,474; template-less policy 3,239/5,470.
- Screen degenerate: identical 0.3/0.25/0.25/0.2 weights on all top-20 rows. Dossiers: SMA20/50/200 identical + RSI 50.0 (no technical depth on inspection date).
- Index gap: 1.64M source chunks vs 1.4M rows — NULL/empty embeddings incl. intentional boilerplate NULLs (complete-by-design, not corruption).

## 8. Strategies backlog (test only past the bar)

NEXT (P2-gated): momentum-vs-reversal by horizon → Beneish/Altman/Piotroski veto + substrate versioning → GARCH/VIX/investor-majority → OU/Kelly/EVT. Promotion bar: cohort-clustered ≥+500bps net, ≥30 weekly cohorts, 2 regimes, hit CI lower >0.5, placebo ≈0.

## 9. P2 intent (in progress, agent P2Version)

- Additive history tables beside live levels (never migrate in place):
  moat_history / policy_eni_history / ripple_history with asof_date.
  Template: ripple_effects revision_count + last_revised_at pattern.
- CORRECTED 2026-09-24: one backfill row per key is NOT enough — live
  audit shows moat 1 row/symbol (2021 singletons) and policy 6 rows/key
  all same-date (cross-sectional, no time series). Deltas need two
  DATES per key. Writers (quality/policy peer re-runs, event revisions)
  must append genuinely new dated rows on revision; same-day upserts
  collapse by day-key by design.
- Predictors vote on dated deltas (downgrade/drop = -1, upgrade = +1);
  levels keep gating, asof_date=None keeps legacy behavior
  (eod_corrector.py:34-51 contract preserved).
- Gate: signal-audit re-run shows quality/policy/supply direction counts
  > 0 on material rows (baseline 0/0/0). No new strategies benchmarked
  against the residual until the gate flips.

## 10. Versioning ledger evidence (2026-09-24, recompute)

- N50 recompute: 1,250 rows, 389 material via --universe nifty50
  (branch added: _resolve_symbols nifty50 → 50 members; was falling
  through to literal ['NIFTY50'], 0 rows).
- Supply dirs 0 → 24 on-ledger (JSWSTEEL/NTPC/TATASTEEL, +1 on real
  revision deltas). Quality probe SBIN = -1 (3.75→2.75) but SBIN
  attributions predate 09-24, so quality dirs still 0 on-ledger —
  correct no-future-leakage, not broken wiring.
- Policy 0: live matches canon (2,231 rows, 0 mismatches) — no genuine
  revision exists; forcing one would fabricate.
- Status: mechanism proven (one lens votes on-ledger), foresight not
  claimed. Audit gate needs multi-lens dirs at breadth.

## 11. Fiscal-period extraction spec (FYAudit, 5k-sample verified)

- Header FY empty 99.94%; naive content-regex = 100% noise (literal
  `FY:` in every header). Body-only genuine rates: financial/fiscal
  year 12.2%, `FY 20xx` 6.07%, `FY20xx` 1.98%, year-range 1.6%,
  Q-FY 1.0%. Mentioned years flat FY23-26 (~1% each).
- Preprocessing mandatory: body = content after first newline; all
  patterns on body only, never raw content.
- Priority: P1 Q-FY quarter > P2 FY-range > P3/P4 FY short/year >
  P5 anchored YY-range > P6 quarter-end date (corroboration only).
  Tie-breaks: specificity > rightmost > multi-conflict → NULL+flag.
- Confidence: 1.0 P1 / 0.9 P2-P4 / 0.7 P3-anchored / 0.5 P5 /
  0.3 P6 / 0.2 multi → NULL. Backtest threshold >= 0.5.
- Output: fiscal_period (FY24 / Q2FY25) + fiscal_confidence +
  fiscal_source. Additive columns + index; 5k-row batches, ~280
  batches over 1.4M rows, idempotent/resumable, content untouched.
- Discovery-vs-fiscal lag proven: 60-72% of FY24/25 mentions sit on
  2026-08 discovery dates (1-2yr lag) — published_date unusable as
  fiscal proxy.

## 12. Fiscal backfill complete + audit wait (2026-09-24)

- Backfill: 1.4M scanned, 290,959 labeled (20.8%), checkpointed,
  resumable; live count 292,246 with insert-stamping active.
- Votes unchanged: quality 0 / policy 0 / supply 24. No post-09-24
  EOD exists (max 2026-09-23), so no new attributions can form.
- Audit gate waits on market calendar: new trading EOD + recompute
  → quality joins supply on-ledger → close.

## 13. Audit gate flipped (2026-09-24, fresh EOD 09-24)

- Backfill: 8,695 rows, EOD max 09-23 → 09-24. Recompute: 1,250 rows,
  406 material.
- Quality dirs 0 → 1 on-ledger: SBIN 2026-09-24 = -1, share 0.25,
  explained 0.25 (downgrade 3.75→2.75 voting live, no leakage —
  second moat row dated 09-24, attribution 09-24).
- Supply 24 → 25. Factor 42,381 → 42,408. Policy 0 (correctly idle).
- Gate: quality now votes on-ledger alongside supply. Multi-lens
  breadth still thin (1 quality row) — mechanism proven at ledger
  level, foresight still unproven at scale.

## 14. Drain verdict: conditional hold (firm panel, live-verified)

- Verdict: enrich DEPTH (lens history), hold BREADTH (no bulk annuals
  until event-date/version columns land). Unanimous across roles.
- Live: 1,653,367 chunks, 292,246 fiscal-labeled, 24,185 annuals
  pending (agent said 26,263 — broader pending set; corrected live).
- Release condition: fiscal YES (columns + index + insert-stamping
  live). Event-date/version NO (columns absent on chunks/corporate
  docs — verified PRAGMA). Bulk HELD until those land; fiscal-only
  batches may flow. Order: annual_n200 → concall_n → annual_all →
  concall_all → refresh.
- Top extraction upgrade: guidance-change diff on concalls
  (raised/lowered/maintained + magnitude) — feeds dated-delta
  contract directly, the only mechanism proven on-ledger (SBIN -1).
