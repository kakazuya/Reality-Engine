# F1 Forensic-Avoidance Paper Screen — 2026-09-25 (evening wave, Slice B)

**Verdict: KILL — do not promote.** The forensic veto fails all five promotion-bar criteria (§8).
Direction is adverse: vetoed names *outperformed* XS-matched peers after veto dates on all 16
horizon×universe cells (avoided-loss excess negative everywhere). Read-only screen; no code edits,
no live writes. Owner file: this file only.

## 1. Method (frozen conventions)

- **Gate 0** (AGENTS.md §11, unchanged): reject iff `promoter_pledge_pct > 15 OR
  interest_coverage_ratio < 2.5 OR debt_to_equity_ratio > 1.5`. Live bite is DE-driven only:
  182 current-snapshot DE>1.5 rejects (quarantine-excluded); IC<2.5 fires on 811 placeholder-zero
  rows (no information); pledge never fires (all-zero). Gate 0 kept as-is; overlap reported, never
  double-counted.
- **Gate 1** (`tasks/desk_forensic_2026-09-25.md` §§3–7): F1 loss-maker (NI<0) VETO; F2
  growth-without-margin (SGI>1.5 AND Δopm<−2pp) VETO; F3 margin collapse (Δopm<−2pp AND Δnpm<0,
  sane |.|≤100 both years incl. npm leg) FLAG; F4 leverage jump (ΔDE>+0.3 with DE>1.0) FLAG;
  F5 F-5≤1 (NI>0, ΔNI>0, ΔEBITDA>0, ΔDE<0, Δopm>0; missing input ⇒ criterion 0 AND partial=1,
  fail-closed veto-only) VETO; F6 F-5=2 FLAG; F7 loss persistence (NI<0 two FYs) upgrades
  (single corroborating FLAG suffices). Resolution: any VETO ⇒ BUY-blocked; two independent
  FLAGs on different axes ⇒ VETO. SUPPORT feeds the SELL leg only (never standalone SELL).
- **PIT lags** (§3.3): FY label usable only at action_date ≥ Jun-01 (FY23→2023-06-01 …
  FY26→2026-06-01). FY22 dropped as an entry vintage (only 14 consecutive pairs; FY21 nearly
  empty — 16 rows, 1,564/1,627 FY22 snapshots NI-NULL). Forensic table is a current snapshot
  (stamped, not PIT). Quarterly corroboration (2,944 names at 45d lag) supports the F-5 margin
  leg per spec; no quarterly input was used as a veto trigger in this screen.
- **Quarantine on every read**: `NOT EXISTS (substrate_quarantine WHERE table_name=
  'master_companies' AND row_key=isin)` on all financials reads; sibling
  `quarantined_master_symbols` (INE_AUTO_* + quarantine keys) on price reads: **760 symbols
  excluded**, incl. 2 veto-entry overlaps. 25 vetoed symbols with no universe (LARGE non-nifty
  masters outside the 4-index map: ABB, SIEMENS, ADANIGREEN, ADANIPOWER, TATACAP, HYUNDAI, …)
  are listed unmapped and excluded from the grid (never force-mapped).
- **Scoring**: SELL-form veto entries (avoided-loss-vs-holding, both legs sign-flipped;
  `excess = peer_ret − stock_ret − cost`); XS-matched primary (equal-weight same-universe peers
  over the same realized window, entry symbol excluded); breadth-index secondary where
  resolvable, else documented surrogate (below). Net of 50bps ASSUMED impact prior + STT
  0.1%/side + 5bps other (assumed) + FIFO taxes per forensic §§9–10; risk-free 0. Realized window
  `min(entry+h)` on market closes via sibling `realized_window` (never fwd-filled); all entries
  open (`closed_date=None`) so the horizon axis is informative (no T9 flattening). SELL invariant
  `target < entry < stop` untouched (no SELL terms framed here). REVOKED artifacts never quoted.
- **Engine fidelity**: grid math is a validated replica of sibling `excess_for_entry` /
  `realized_window` / `_p1_cell_stats` / `_p1_placebo_stats` (500-sample validation vs live
  siblings: **0 mismatches**, max diff 6.7e-16; float64 grids; next-bar peer semantics preserved).
  Placebo: 50 draws/(entry,horizon) (10 for Microcap, documented), seed 20260925, same realized
  holding, shuffled entry date.

## 2. Veto rates (quarantine-excluded; vetoed + passed = scanned, reconciled per vintage)

| Vintage (entry) | Names | F1 loss | F2 | F3 | F4 | F5 ≤1 | F6 =2 | F7 | VETO | Veto rate | Passed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| FY23 (2023-06-01) | 2,090 (1,567 pairs) | 297 | 3 | 72 | 225 | 238 | 782 | 2 | 499 | 23.9% | 1,591 |
| FY24 (2024-06-01) | 2,104 (1,978 pairs) | 256 | 39 | 378 | 128 | 327 | 248 | 130 | 597 | 28.4% | 1,507 |
| FY25 (2025-06-01) | 2,121 (1,999 pairs) | 241 | 53 | 439 | 95 | 357 | 316 | 119 | 633 | 29.8% | 1,488 |
| FY26 (2026-06-01) | 2,961 (2,030 pairs) | 534 | 52 | 508 | 97 | 413 | 315 | 123 | 986 | 33.3% | 1,975 |

- Spot checks (FY26): F2 veto LEAPIND / BNAGROCHEM / SONAMLTD satisfy SGI>1.5 + Δopm<−2;
  corroborated-FLAG vetoes SJVN (F3+F4+F6), SIEMENS (F3+F6), AVANTEL (F3+F6) satisfy the
  two-independent-FLAGs rule with no direct veto — resolution logic confirmed on live rows.
- Gate-0 overlap (current-snapshot DE>1.5, stamped not PIT): FY23 58 / FY24 68 / FY25 67 /
  FY26 63 veto symbols overlap — reported alongside, not counted as Gate-1 wins.
- FY26 bite is inflated by current-year partials (534 F1 vs ~250 prior vintages); §3.3 gates
  usability but cannot create filing timestamps (forensic §14.2).

## 3. Avoided-loss excess — 4 horizons × 4 universes (XS primary, net, bps)

Positive = veto correct (vetoed names underperformed peers → avoidance saved money).
`n` = legs; `G` = weekly cohorts; CI = cohort-clustered t(G−1) 95%; `cohhitlo` = cohort-robust
hit lower (the gate); placebo = shuffle-entry mean [95% CI], n draws.

| Universe | h | n | G | XS mean | Clustered CI | hit | cohhitlo | Placebo mean [CI] (n) | Index-rel mean |
|---|---|---|---|---|---|---|---|---|---|
| Nifty 50 | 30 | 32 | 4 | −346.8 | [−1081.5, +153.8] | 0.219 | −0.023 | −183.3 [−225.4, −141.2] (1,600) | −514.8 |
| Nifty 50 | 90 | 32 | 4 | −534.7 | [−1327.6, +367.0] | 0.344 | +0.109 | −311.1 [−395.0, −227.2] (1,600) | −843.6 |
| Nifty 50 | 180 | 22 | 3 | −1,068.0 | [−1,470.1, −755.3] | 0.273 | +0.046 | −859.1 [−987.0, −731.2] (1,100) | −1,540.6 |
| Nifty 50 | 365 | 22 | 3 | −4,133.7 | [−9,106.0, +3,135.6] | 0.182 | −0.236 | −3,162.7 [−3,470.9, −2,854.6] (1,100) | −4,449.9 |
| Midcap 150 | 30 | 81 | 4 | −305.5 | [−921.0, +288.0] | 0.296 | +0.095 | −244.1 [−304.5, −183.8] (4,050) | −501.4 |
| Midcap 150 | 90 | 81 | 4 | −352.1 | [−1,420.5, +650.6] | 0.457 | +0.284 | −500.1 [−593.7, −406.5] (4,050) | −804.5 |
| Midcap 150 | 180 | 59 | 3 | −1,318.0 | [−3,879.5, +1,232.1] | 0.339 | −0.119 | −693.8 [−841.5, −546.1] (2,950) | −1,781.1 |
| Midcap 150 | 365 | 59 | 3 | −2,814.6 | [−12,340.6, +6,600.6] | 0.424 | +0.292 | −1,551.6 [−1,809.8, −1,293.5] (2,950) | −3,874.7 |
| Smallcap 250 | 30 | 269 | 4 | −129.1 | [−347.1, +111.1] | 0.428 | +0.255 | −309.5 [−337.0, −282.1] (13,450) | −306.5 |
| Smallcap 250 | 90 | 269 | 4 | −329.0 | [−968.7, +282.0] | 0.450 | +0.137 | −536.8 [−578.1, −495.6] (13,450) | −623.3 |
| Smallcap 250 | 180 | 183 | 3 | −786.5 | [−3,395.6, +1,799.8] | 0.372 | −0.139 | −870.8 [−951.6, −790.0] (9,150) | −1,329.6 |
| Smallcap 250 | 365 | 183 | 3 | −1,301.1 | [−4,557.5, +1,929.6] | 0.410 | −0.085 | −650.3 [−772.1, −528.6] (9,150) | −2,223.6 |
| Microcap 250 | 30 | 2,267 | 4 | −223.8 | [−678.3, +151.6] | 0.419 | +0.160 | −7,249.8 [−10,989.2, −3,510.4] (22,670) | −294.6 |
| Microcap 250 | 90 | 2,263 | 4 | −267.9 | [−1,227.0, +496.1] | 0.487 | +0.201 | −7,598.8 (22,630) | −352.2 |
| Microcap 250 | 180 | 1,435 | 3 | −695.8 | [−2,864.6, +1,366.9] | 0.471 | +0.218 | −11,101.9 (14,350) | −1,470.8 |
| Microcap 250 | 365 | 1,435 | 3 | −11,559.1 | [−73,173.7, +45,299.4] | 0.528 | +0.194 | −26,701.9 (14,350) | −12,195.0 |

- Skips (honest-NULL, counted): 1,904 missing-stock-exit (FY26 180/365d windows run past EOD
  2026-09-24) + 24 missing-stock-entry. No silent drops.
- Microcap 365d cells are outlier-dominated (CI ±60,000bps; single-name 1,300×-scale moves in
  the equal-weight XS pool) — reported as-measured, not trimmed, not tuned.
- Index-relative leg: breadth history starts 2025-09-01, so FY23–FY25 entries resolve the index
  leg against a documented surrogate (equal-weight universe-mean close history); the XS primary
  (the bar leg) uses no surrogate. Microcap index-relative means additionally carry the
  outlier pool above.

## 4. Cohorts, regimes, placebo

- **Weekly cohorts**: 4 (one per entry vintage: 2023-05-29, 2024-05-27, 2025-05-26, 2026-06-01;
  3 for 180/365d after exit-censoring). Bar needs ≥30. **FAIL** (4 ≪ 30 — structural: annual
  PIT dates admit at most ~4 cohorts; the design cannot pass this criterion without a
  quarterly/monthly cadence change, which is out of scope tonight).
- **Regimes** (sibling trailing-50 Nifty rule): drawdown 1,896 legs (FY26) + unknown 6,796 legs
  (FY23–25, breadth starts 2025-09); **uptrend 0 legs** — the 2-regimes-same-sign criterion is
  untestable here. **FAIL**.
- **Placebo**: means −183 to −26,702bps, every 95% CI excludes 0 (-microcap magnitudes are
  outlier-driven, same pool as above). Nowhere near ≈0 (±100bps). **FAIL**. Note the sign:
  even on shuffled dates vetoed names beat peers — the veto loads on names with positive XS
  drift in this window, so entry skill cannot be isolated; delta-vs-placebo is negative on
  15/16 cells.

## 5. Entries composition

2,655 veto-only entries scored (quarantine/unmapped/price-missing excluded):
Nifty 50: 32; Midcap 150: 81; Smallcap 250: 269; Microcap 250: 2,273; by vintage FY23 488 /
FY24 591 / FY25 620 / FY26 956; 8,692 ok legs.

## 6. Live state (read-only probes this session)

EOD max 2026-09-24 (verified); book 841 actions (BUY 165 / HOLD 667 / SELL 9 — matches
681 closed + 160 open); chunks ~1.70M and moving (writer Slice A active during reads:
NULL embeddings 247,794 mid-drain, not 0); corporate_documents 103,630 live
(ANNUAL_REPORT 26,614; 1 quarantined, is_processed=2); contract dispatch state
(NULLs 0 / pending ~91,929 / ANNUAL 26,262) is the pre-drain baseline, superseded mid-flight.
All inference reads carried the quarantine predicate; queue lock never taken.

## 7. Promotion-bar mapping → KILL

| Criterion | Bar | F1 result | Pass? |
|---|---|---|---|
| Cohort-clustered net excess | ≥ +500bps | All 16 cells negative (−129 to −11,559bps) | NO |
| Weekly cohorts | ≥ 30 | 4 (3 for 180/365d) | NO |
| Hit CI lower (cohort-robust) | > 0.5 | max 0.292 | NO |
| 2 regimes, same sign | both | uptrend 0 legs; only drawdown + unknown | NO |
| Shuffle placebo | ≈ 0 | −183 to −26,702bps, CIs exclude 0 | NO |

**KILL.** 0/5 criteria met, and the sign is adverse — vetoed names outperformed XS peers after
veto dates on every cell, so promotion would pay to avoid winners. No threshold re-tuning
(F-5 ≥4, F2 SGI 1.5 stay frozen priors per forensic §14.4). Pre-registered follow-ups if the
desk ever revisits: (a) quarterly-cadence screen for cohort count; (b) T-F2 BUY-overlay test
(does the veto remove losers from the BUY leg — the one framing where adverse SELL-direction
does not kill the idea); (c) outlier-robust (median/trimmed) estimator pre-registered before
seeing results. None of these change tonight's call.
