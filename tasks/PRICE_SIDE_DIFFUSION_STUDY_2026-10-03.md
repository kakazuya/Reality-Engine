# Price-side information-diffusion study — first pass (2026-10-03)

Code: `analysis/diffusion_study/` (`01_build_events.py` → `02_event_engine.py` → `03_estimate.py`, shared `common.py`).
Outputs (git-ignored, regenerate in about a minute): `analysis/diffusion_study/out/`. Everything is read-only on the databases and
numpy/pandas only (no scipy/statsmodels needed), so it runs unchanged on the laptop. Run order is the file order; each stage prints its sample counts.

## 1. What was joined

| Piece | Source | Size |
|---|---|---|
| Events | `analysis/bse_announcements.db` (BSE feed, exact `DissemDT` in IST, 2020–2026) | 1,940,081 announcements |
| Prices | `reality_engine/data/parquet/daily_price_delivery.parquet`, series EQ | 3,120 stocks, 1,269 sessions, 2021-10-27 → 2026-09-24 |
| Join | feed `symbol` → price-table ISIN; 59.5% of announcements map to an EQ stock with prices (the rest are SME/BE/delisted/renamed symbols) | 552,796 event-days |
| PIT documents | `corporate_documents` rows carry `bse_newsid`, so PDFs (transcripts, presentations) are the same events as the feed; the feed is used as the event source because it is complete and timestamped | 71,937 documents joined |

An **event-day** is (stock, first session whose close-to-close return can contain the news). Timing rule from the IST timestamp:
before 09:15 or non-trading day → next open session (`pre_open`, `non_trading`); 09:15–15:30 → same session, partial exposure (`intraday`);
after 15:30 → next session (`after_close`). 'full' timing in the tables = news arrived outside the session.

## 2. Method

1. **Benchmark.** For each stock, abnormal return `AR = r − β·m_b`, where `m_b` is the equal-weighted return of all stocks in the same
   *liquidity bucket* on the same day (6 buckets on lagged 60-day median turnover) and β is estimated through the origin on sessions
   [t0−250, t0−31]. Why not a plain market model: with an equal-weighted market proxy, large caps drifted −8 bp/day and small caps +8 bp/day
   against it; a fitted intercept extrapolated out of sample added a spurious drift for stocks selected on past performance. Matched
   benchmarks and intercept-free models are standard (Brown & Warner 1985; Barber & Lyon 1997 — cited from memory, see §6).
2. **Volume and delivery.** Log turnover and delivery % are measured against the same-day mean of the stock's liquidity bucket, then against
   the stock's own estimation-window baseline, so market-wide volume seasonality (month-end, expiry, results season) is removed.
3. **Isolation.** A stratum keeps only event-days with no *other-cluster* material announcement in sessions [t0−2, t0+10]. The results
   cluster (Financial Results, Outcome of Board Meeting, Investor Presentation, Press Release, Earnings Call Transcript, Analyst Meet,
   Board Meeting, Integrated Filing) is treated as one information event. The material list in `common.py` was fixed a priori.
4. **Statistics per stratum (family × timing).**
   - `car01`: mean CAR(0,+1) (reaction). BMP standardised z (Boehmer, Musumeci & Poulsen 1991) as a robustness check for event-induced variance.
   - `drift_sc`: **mean-shift-proof drift** = ½·(E[CAR(2,20) | reaction above stratum median] − E[CAR(2,20) | below]).
     >0 means under-reaction (prices keep moving the way they first moved), <0 reversal. A first version (sign × CAR(2,20)) was
     rejected because results days have a negative average CAR(2,20), which inflated it mechanically.
   - `lv01`, `vr01`, `dp01`: excess log turnover, excess variance ratio `mean(AR²/σ²)−1`, delivery-% shift, all over τ=0,1.
   - Two-way (stock × date) clustered standard errors (Cameron, Gelbach & Miller 2011), because announcements cluster on accounting-calendar dates.
   - Benjamini–Hochberg FDR across all primary strata per statistic (Benjamini & Hochberg 1995).
   - Attention half-life: fit `LV(τ)=B·e^(−λτ)` on τ=0..20; half-life = ln2/λ. Drift saturation: fit `S(e)=A·(1−e^(−k·e))` on the
     centred sign-conditioned CAR(2,τ) path, t50 = ln2/k. Both with firm-cluster bootstrap CIs (300 draws).
5. **Negative controls.** 17 administrative families (loss-of-certificate notices, trading-window closures, newspaper publications, AGM/postal-ballot
   notices, secretarial certificates, …) go through the identical machinery. They should show nothing.

## 3. Results (primary sample: isolated, turnover ≥ ₹50 lakh/day)

| Family (timing) | n | CAR(0,1) bp | Drift bp (t) | Turnover (log) | Variance ratio | Attention half-life, days (95% CI) | Drift A, bp (95% CI); t50 days |
|---|---|---|---|---|---|---|---|
| Financial Results (full) | 4,469 | −82 | +54 (3.5) | +0.65 | +2.3 | 0.89 (0.83–0.96) | 77 (23–236); 11.6 (1.9–open) |
| Financial Results (intraday) | 6,139 | −53 | +68 (5.3) | +0.93 | +2.8 | 1.20 (1.12–1.28) | 88 (47–244); 8.7 (3.0–open) |
| Outcome of Board Meeting (full) | 3,534 | −85 | +73 (4.1) | +0.65 | +2.4 | 0.87 (0.79–0.94) | 210 (40–298); 34.7 (3.5–open) |
| Investor Presentation (full) | 3,355 | −31 | +72 (4.4) | +0.56 | +2.0 | 0.83 (0.75–0.94) | 58 (29–160); 3.5 (0.6–23.5) |
| Press Release (full) | 5,152 | +1 | +29 (2.1) | +0.40 | +1.35 | 0.77 (0.71–0.87) | not identified |

"open" = upper bound at the edge of the search grid (t50 ≥ 34.7 days), i.e. the data cannot rule out very slow drift.

**What the data support**
- **Which news:** results-cluster filings (Financial Results, Outcome of Board Meeting, Investor Presentation) are the only non-trivial families that pass FDR on drift (q ≤ 0.003); 6 strata pass, all in that cluster. Press releases and clarifications move volume and variance strongly but show no reliable drift.
- **At what time:** attention (volume, variance) is front-loaded: excess turnover halves in about 1 day for results (0.8–1.2 days). Price drift is slower; the point estimate of t50 is 4–12 days but its CI runs from 1–3 days to unbounded, so the speed of drift is **not** pinned down.
- **At what percentage:** per side of the reaction distribution, follow-on drift over days 2–20 is about 55–75 bp for results-cluster filings (the saturation level A is 60–90 bp with wide CIs, except where noted). Exposure the first two sessions is much larger than that in absolute terms (the mean reaction is −30 to −85 bp, with standard deviation far greater).
- **Intraday vs outside-session:** results released during the session show a bigger volume spike (+0.93 vs +0.65 log) and a slightly larger drift estimate (68 vs 54 bp), but the difference is not tested formally.

## 4. Things that look wrong or odd — read before quoting any number

1. **Mean reaction to results is negative (−53 to −85 bp) with a +60 bp run-up over τ=−5..−1, in each of 2022–2026.** Only 36% of results days have a positive CAR(0,1). A zero-mean benchmark should not give that. Possible causes (unresolved): announcers underperform same-bucket non-announcers, a pre-results positioning effect, benchmark contamination by other reporters on the same day, or a flaw in timing or isolation I have not found. The sign-free drift and attention statistics do not depend on it, but **do not read car01 as "the market reaction to results"** until it is explained.
2. **Controls are not fully clean.** Drift is calibrated (0 of 20 control strata reject, |t| ≤ 1.6), but car01, volume, variance and delivery reject in 20–60% of controls (BH q < 0.05), at small effect sizes (max |CAR| 24 bp, max |log turnover| 0.11, max |variance ratio| 0.23). Calendar clustering of administrative filings is the likely cause. Treat effects smaller than those maxima as indistinguishable from nothing; the results-cluster effects (0.4–0.9 log turnover, +2 to +2.8 variance ratio) are 4–10× larger.
3. **Placebo days are not neutral.** Random no-news windows average about −4 bp/day against the benchmark, so quiet stocks underperform announcing ones (an announcement effect, or a selection effect). It cancels in `drift_sc` but affects any raw CAR.
4. **Survivorship and coverage.** Only 59.5% of announcements map to an EQ stock; the sample is stocks present in the 2026 price table, so delistings are missing (the corporate-actions feed has none either).
5. **No sign for the news.** Without a surprise or sentiment measure the study cannot say whether a given filing was good or bad; it only conditions on the realised first-two-day reaction. Results of this type are **predictive, not causal**.
6. **Ties to the PIT work.** The timing rule assumes `DissemDT` is IST and exchange-side dissemination; a 15:30 cutoff ignores the post-close session and Muhurat/special sessions.
7. **Coarse family labels.** Families are BSE sub-categories. "Financial Results" mixes good and bad quarters; "General" and "Press Release" mix everything.

## 5. Not done yet (in order of value)

1. Explain the negative mean reaction (§4.1): split by results-season vs off-season, compare against a size-and-liquidity-matched individual-firm benchmark, check the first-day price-limit/circuit behaviour.
2. Add a surprise signal for results (YoY PAT/revenue growth from `financial_metrics` once point-in-time) so the sign is exogenous; then the saturation fit becomes a clean PEAD-style estimate (Bernard & Thomas 1989).
3. Per-stock information share (Hasbrouck 1995 does not apply to single-venue; use a Beveridge–Nelson/VECM split) and eligibility by liquidity.
4. Text-side study (concall content) once the video/concall backlog is loaded.
5. Order-flow mechanism check: restrict to the most liquid tercile and see if effects persist (Chordia, Roll & Subrahmanyam 2002).
6. Robustness: year-by-year drift, alternative isolation windows, alternative benchmark (Fama–French-style factors once the factor spine is wired).

## 6. Citations

Verified earlier in this project (see `tasks/SESSION_CLOSEOUT_2026-09-29b.md`): Ball & Brown (1968); Bernard & Thomas (1989); Kothari & Warner (2007); Tetlock (2007, JF 62); Da, Engelberg & Gao (2011); Chordia, Roll & Subrahmanyam (2002, JFE 65); Hasbrouck (1995).
**Cited from memory in this report and not yet checked against the source — verify before relying on them:** Brown & Warner (1985, JFE); Barber & Lyon (1997, JFE); Boehmer, Musumeci & Poulsen (1991, JFE); Cameron, Gelbach & Miller (2011, JBES); Benjamini & Hochberg (1995, JRSS-B).

## 7. Update 2026-10-05 — negative-reaction puzzle, test 1 (matched non-announcers)

Code: `analysis/diffusion_study/04_negative_reaction_matched.py` (about 10 s, read-only, reads only `out/units.parquet`, `out/calendar.txt` and the price parquet).
Design: each Financial Results event-day (turnover ≥ ₹50 lakh/day) is matched to its 20 nearest non-announcers by prior-5-day run-up (excess vs the same-day liquidity-bucket mean),
within liquidity bucket and calendar year, caliper 50 bp, date-clustered SEs. Control A = no results-cluster filing within ±5 sessions; control B = no material filing in [t−2, t+10].
A first attempt that required same-date controls kept only 1,387 of 4,096 events and silently dropped the high run-up ones (matched run-up −50 bp vs +72 bp overall); it was discarded.

| Sample (isolated FR, control A) | n | Run-up, events / controls (bp) | CAR(0,1) events / controls (bp) | Difference (bp, t) | Raw return(0,1) events / controls (bp) |
|---|---|---|---|---|---|
| All timing | 4,068 | +64 / +64 | −89 / −5 | −85 (−8.1) | −108 / +16 |
| Outside session | 2,133 | +62 / +61 | −99 / −2 | −97 (−7.0) | −116 / +15 |
| Intraday | 1,935 | +67 / +67 | −79 / −7 | −72 (−4.7) | −99 / +16 |
| All FR events, not isolated | 19,216 | +78 / +78 | −50 / −4 | −47 (−9.2) | −59 / +16 |

Control B gives the same picture (difference −81 bp, t −7.7). Non-announcers show a mild reversal after a run-up (decile table in the script output: −4 to −9 bp over days 0–1 for the top
run-up deciles), which accounts for 5–8 bp of the −89 bp, not the bulk.

**Conclusion:** the negative mean reaction is not short-term reversal and not a benchmark artifact. Raw returns show the same gap (events −108 bp, matched controls +16 bp), so the choice of benchmark does not drive it.
It is specific to the announcing stock-days, so the abnormal-return panel does **not** need rebuilding on this account. By year the gap is −29 (2022, CI includes 0), −99, −94, −87 and −83 bp (2023–2026);
2022 intraday is about zero (+6 ± 34 bp). Still open: why announcers fall after a +64 bp run-up (candidates: buy-the-rumour/sell-the-news, DissemDT lagging the real release time, results-day selling by
stocks that run up into results). Remaining planned tests: 3 (reaction vs run-up size, season vs off-season, time of day), 4 (cap tier), 5 (board-meeting intimation and ex-dividend timing).
Caveat: control A/B non-announcers are stocks that do not report in the window, a selected group; the control mean (−5 to −8 bp) is therefore a comparison group, not a neutral zero.

## 8. Update 2026-10-05 — negative-reaction puzzle, test 3 (run-up size, season, time of day)

Code: `analysis/diffusion_study/05_negative_reaction_splits.py` (reads the matched pairs saved by `04_…`, which now also writes `out/neg_reaction_matched_A_allFR.parquet`).
Outcome = announcer CAR(0,1) minus the mean of its 20 matched non-announcers (bp), date-clustered SEs, all 19,216 Financial Results event-days (4,068 isolated in brackets where it matters).

- **Run-up size: weak.** The gap is −31 bp in the lowest run-up quintile (mean run-up −510 bp) and −62 bp in the highest (+766 bp); slope −2.3 bp per +100 bp of run-up (t −1.7; isolated −2.6, t −1.0). It is negative even when the run-up was negative, so it is not just a pre-results run-up unwinding.
- **Time of day: strong gradient.** Gap by Financial Results dissemination time (IST): before 13:00 about −14 to −26 (t ≈ −0.4 to −0.7, n ≈ 1,500); 13:00–15:30 −34 (t −3.9); 15:30–18:00 −53 (t −6.0); 18:00–21:00 −57 (t −6.1); after 21:00 −84 (t −4.2). Isolated sample shows the same ordering (−29 → −67 → −88 → −106 → −118). Results released early in the session show no reliable negative reaction.
- **Season: not a clean season effect.** Gap by market-wide density of results that day: low-density days −31 bp, mid −51, peak −60 (isolated −70 / −85 / −100). By month it varies from −18 (Apr) to −112 (Jun, n=182) and is largest in Feb and Aug, smallest in Apr, May, Oct and Nov; SEs are 11–40 bp, so month-level ranking is noisy.
- **Joint regression** (diff on time-of-day dummies, density z, run-up/100 bp; base <13:00): 15:30–18:00 −35 (t −1.8), 18:00–21:00 −39 (t −1.9), 21:00+ −66 (t −2.4), density −13 per SD (t −2.2), run-up −2.4 (t −1.8). Time of day and density both survive separately but neither is sharp once together; cells are small for early-day filings.

**Reading (hypothesis, not tested):** later and more crowded releases carry worse news — firms with bad quarters tend to file late and on deadline days, and the study has no sign for the news (§4.5), so the lateness gradient may just proxy for surprise sign.
This is the case for the earnings-surprise step (§5.2): condition on point-in-time YoY PAT/revenue growth and check whether the time-of-day gradient disappears. It does not explain the +64 bp run-up.
Remaining from the closeout list: test 4 (cap tier, rerun without isolation rule) and test 5 (board-meeting intimation and ex-dividend timing).
