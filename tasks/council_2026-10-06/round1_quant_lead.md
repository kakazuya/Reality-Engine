# Council round 1 — Quant Lead (statistics, research design)

**My one-paragraph view.** The framework is right in shape. The biggest statistical risk is not a bad model. It is **too little independent history being used up by too many looks**. Price data runs 2021-10 → 2026-09 (about 5 years, 1,269 sessions). Dated fundamentals do not exist yet (`PIT_LABEL_AUDIT_2026-09-29.md`). The diffusion study already shows the classic warning sign: pooled drift is significant (q ≤ 0.003), but by year it is +96 bp (2023), +22/+24 (2022/2024, CIs include 0), −11 (2025), −41 (2026) (`SESSION_CLOSEOUT_2026-10-05.md` §3). One good year can carry a pooled t-stat. So my answers focus on three things: seal a holdout now, count every test, and judge signals by stability across years, not by pooled significance.

Terms used below: **holdout** = a stretch of data nobody looks at until a final, one-shot test. **FDR (false discovery rate)** = the share of "passed" ideas that are really luck. **Power** = the chance a test detects a real effect of a given size. **t-stat** = effect divided by its noise; |t| ≈ 2 is a 5% coin-flip bar, |t| ≈ 3 is the bar the finance literature now asks of new factors.

---

## A. North star and scope

### Q1
**Position:** Keep it, but add two words: "**stable** and **risk-adjusted**". An edge must survive costs *and* show the same sign in most years, with a stated worst drawdown.
**Why:**
- "Repeatable" is vague. Make it testable: same sign in at least 3 of 4 calendar years (or both halves of the sample), not just a significant pooled average. The diffusion drift fails this today.
- "Has a reason" is useful as a prior, not as evidence. A good story lowers the bar slightly; it never replaces the holdout.
- Capacity matters more to the Trading Lead; from my side, an edge that only exists in stocks below ₹50 lakh/day turnover is not measured reliably (wide spreads, stale prices).
**Confidence:** high.

### Q2
**Position:** Both, as **separate books with separate scoreboards and separate test budgets**. Start with event-driven (days–weeks) because it is the only horizon the data can test now.
**Why:**
- Statistical power depends on the number of *independent* bets. Five years gives about 250 non-overlapping weekly windows but only ~20 non-overlapping 90-day windows and 5 one-year windows. Multi-month fundamental claims cannot be confirmed on this history; they can only be explored.
- Multi-month fundamental investing also needs dated fundamentals, which do not exist yet (PIT audit: quarterly financials have no filing date; 87% of YoY PAT growth rows are 0.0).
- Mixing horizons in one score lets a short-horizon fluke subsidise a long-horizon story, or vice versa.
**Confidence:** high.

### Q3
**Position:** Research universe = all EQ stocks above a liquidity floor of about **₹1 crore median daily turnover** (lagged 60-day), reported in at least two size tiers. Scoreboard capital: keep ₹10 cr as the base assumption, but **report the capacity number** (how much capital before costs eat half the edge).
**Why:**
- Restricting to Nifty 200 throws away most event observations and uses today's index membership, which is survivorship bias (`is_nifty200` has no history, PIT audit).
- The diffusion study used ₹50 lakh/day; I'd tighten for trading tests and keep ₹50 lakh for research, so we can see whether an effect lives only in illiquid names (a red flag).
- Always report results by size tier. An edge that is all in the bottom tier is usually costs and stale prices, not information.
**Confidence:** medium (the exact floor is the Trading Lead's call).

### Q4
**Position:** Long-only scoring, with "avoid lists" scored as **long-only underweights vs the benchmark**, not as shorts.
**Why:**
- The diffusion drift is symmetric ("per side"); the down-side half is not tradable for most names, so we must report the **long half on its own**. A symmetric statistic overstates what a long-only book can earn.
- An avoid list is testable cheaply: does excluding these names raise the benchmark's return? That is a clean, low-variance test.
- Shorts via F&O can be a later, separate book once there is a promoted long signal.
**Confidence:** high.

## B. Scoreboard

### Q5
**Position:** The current bar is the right *kind* of bar but has the wrong units. Replace the fixed "+500 bps" with a **horizon-scaled, risk-adjusted** bar, and drop the hit-rate rule.
**Why:**
- +500 bps means very different things over 5 days and 365 days. Use annualised net excess return *and* an information ratio (excess return ÷ its volatility); suggest IR ≥ 0.5 net of costs on the holdout, plus a positive-and-significant estimate in-sample.
- Hit-rate CI > 0.5 is a poor rule for skewed returns: event strategies often win less than half the time but win big. It can reject real edges and pass fake ones. Keep it as a diagnostic only.
- Keep: ≥ 30 independent cohorts, same sign across regimes, placebo ≈ 0. These are the parts that already did their job (the P1 grid placebos ≈ 0 caught nothing false; `desk_quant_2026-09-25.md` T-2).
- Add: **t ≥ 3 in-sample** (not 2) because we will run many tests (see Q8), and a stated maximum drawdown.
- Same bar shape for every horizon; only the cohort definition changes (weekly for event book, monthly for fundamental book).
**Confidence:** medium-high.

### Q6
**Position:** Primary benchmark = **matched peers** (same liquidity/size bucket, same day). Secondary = factor model (market + size + value + momentum) once the factor spine exists. Index return is reported for the investor's view only.
**Why:**
- The diffusion study already showed the index-style benchmark is biased here: against an equal-weighted market, large caps drifted −8 bp/day and small caps +8 bp/day (report §2.1). Matched liquidity buckets fixed that.
- The matched non-announcer test (report §7) is the right template: it removed the benchmark as an explanation for the negative results-day reaction.
- A factor model answers a different question ("is this just momentum in disguise?"). Every promoted signal must pass both: beat peers, and survive after removing known factors.
**Confidence:** high.

### Q7
**Position:** Use a **fixed, deliberately pessimistic** cost stack until there are real fills, then switch to measured costs. Score **pre-tax** for promotion; report post-tax alongside.
**Why:**
- Promotion is about whether the signal is real and tradable; tax depends on holding period and the investor's situation, and changes with law (the Finance Act 2024 change is cited in `desk_meeting_2026-09-25.md`). Mixing tax into the research test adds noise and policy risk to a statistical question.
- Post-tax matters for the go-live decision (Q20), so compute it there.
- Run every test at 1× and 2× the assumed cost. An edge that dies at 2× is fragile.
**Confidence:** medium (cost levels are the Trading Lead's area).

### Q8
**Position:** Three controls together: (1) a **test ledger** that logs every test ever run, including failures and parameter variants; (2) FDR control across the whole ledger (Benjamini–Hochberg is fine), with the significance bar rising as the count rises; (3) a **sealed holdout** that is used once per hypothesis.
**Why:**
- With 20 independent tries at the 5% level, you expect one false pass. Over months the registry will reach dozens. Without a count, any pass is uninterpretable.
- The ledger must count *variants* too (different windows, thresholds, universes). The diffusion study already ran families × timings × statistics; that is dozens of tests, which it correctly FDR-corrected within the study. The ledger extends that across studies.
- For tuned strategy variants, also report a "deflated" Sharpe or White's Reality Check / Hansen's SPA test (the closeout already plans SPA from the `arch` package). These ask: is the best of N variants better than you'd expect from luck?
- The holdout is the only control that does not depend on honest counting. It is the strongest protection.
**Confidence:** high.

## C. Truth layer

### Q9
**Position:** Before any test is trusted: point-in-time dates on every input, corporate-action-adjusted prices, delisted names included, quarantine applied, and a **negative-control pass**. Unverified today: delisted names, corporate-action adjustment before 2023, fundamentals' filing dates.
**Why:**
- Survivorship: the diffusion sample is "stocks present in the 2026 price table"; delistings are missing (report §4.4). This biases toward stocks that survived, i.e. upward.
- Corporate actions: `corporate_actions` starts 2023-01-02; `prev_close` is the only adjustment (PIT audit). One unadjusted split already voided a result (SWANDEF, 100-hour study).
- Fundamentals have no "known as of" date, so any fundamental feature in a past test is look-ahead.
- Negative controls should be a standing check, not a one-off: the diffusion controls showed car01/volume reject in 20–60% of administrative families (report §4.2). That tells us effects below ~25 bp CAR are indistinguishable from noise in this setup. Every new test should report its control rejection rate.
**Confidence:** high.

### Q10
**Position:** **Research on dated, frozen snapshots**; let ingestion continue on the live DB. Each test records the snapshot ID it ran on.
**Why:**
- Reproducibility: a test that cannot be re-run on the same data cannot be audited. The live DB changed mid-upload on Oct 2.
- Freezing ingestion has a real cost (the holdout period keeps growing only if new data keeps arriving).
- The diffusion study already does this in spirit (Parquet exports + a separate announcements DB). Make it the rule.
**Confidence:** high.

## D. Signal layer

### Q11
**Position:** Yes, it is the right requirement, and it is the precondition for any fundamental test. First priorities: **results filing date per quarter**, then quarterly financials as filed, then index membership history, then sector history.
**Why:**
- The single most valuable next hypothesis (earnings surprise, Q14) needs YoY PAT/revenue as known on the filing date. That is blocked today.
- Index membership history fixes survivorship in universe selection.
- Moat/ENI versioning is lower priority: those are not yet tested signals (Q12).
**Confidence:** high.

### Q12
**Position:** **Set them aside** from all decision paths. Keep them as candidates in the registry; each needs its own card and test before use.
**Why:**
- They are snapshots generated in Aug–Sep 2026 with 1–2 history dates (PIT audit), so any backtest using them is look-ahead by construction.
- The signal audit found the substrate explains 11% of moves on average and 0 rows explain more than half; quality/policy/supply voted almost nothing (`desk_quant` T-6). Evidence of usefulness is currently zero.
- Leaving untested features in the decision path silently adds untracked tests and noise.
**Confidence:** high.

## E. Hypothesis registry

### Q13
**Position:** Card contains: mechanism (why it should work, and why it hasn't been arbitraged away), exact signal definition, universe, entry/exit timing, horizon, benchmark, primary statistic, pass bar, placebo/negative control, expected effect size and **power calculation**, data snapshot, and the holdout period. **Frozen by someone other than the author** (for us: CRO role, then Shivam signs). Any change after seeing returns = a **new card**, the old one is logged as failed/abandoned, and both count in the test ledger.
**Why:**
- Pre-registration is what makes a p-value mean anything.
- The power calculation stops us running tests that cannot succeed: e.g. "a 50 bp effect with this many events and this noise gives 30% power" → don't bother.
- One primary statistic per card. Secondary analyses are labelled exploratory.
**Confidence:** high.

### Q14
**Position:** First: **earnings-surprise-conditioned post-results drift** (it merges the negative-reaction puzzle and post-results drift into one test). Second: guidance raises in concalls. Ranking rule: (expected effect × data readiness × statistical power) ÷ hours to test.
**Why:**
- Post-results drift (PEAD) is the most replicated anomaly in the literature (Bernard & Thomas 1989, verified in this project), so the prior is strong.
- Our own data say the sign of the news is the missing piece: the time-of-day gradient (−14 bp before 13:00 to −84 bp after 21:00, report §8) is plausibly late filers having worse quarters. A surprise measure tests that and makes the drift tradable on a price-independent signal.
- Blocker: needs dated quarterly results (Q11). Until then, the price-only reaction-conditioned drift can be studied **only on the in-sample period**.
- Guidance raises: second, because concall dates were repaired only recently and the text extraction for guidance is not yet built or validated. Event count will be smaller → lower power.
**Confidence:** medium-high.

### Q15
**Position:** Exploration is unlimited **on the in-sample period only**. Confirmation happens once, on the sealed holdout, against a frozen card. Seal the most recent ~12 months (2025-10 → 2026-09) **now**, before anyone looks further.
**Why:**
- Exploration is how ideas are found; the danger is only when exploration results are reported as confirmations.
- Caveat I must flag: the diffusion study has already looked at 2025 and 2026 (the by-year drift). Those years are partly "burned" for the drift idea specifically. For that hypothesis, the honest holdout is **forward data from today** (paper-trade period). For hypotheses nobody has touched (e.g. guidance raises), 2025-10 → 2026-09 can still serve as a holdout.
- Keep a short list of which hypothesis has seen which years.
**Confidence:** high on principle, medium on the exact dates.

## F. Evaluation engine

### Q16
**Position:** Yes, build it from the diffusion-study code; it is the best-designed code in the project. Minimum: event study (with matched benchmark, clustered errors, negative controls), cross-sectional test (monthly/weekly sorts or regressions), portfolio backtest with costs and capacity, and the **test ledger hook** that logs every run.
**Why:**
- The diffusion code already has matched benchmarks, two-way clustered standard errors, BH FDR, negative controls, bootstrap CIs, and an intercept-free benchmark that avoids a known bias (report §2). That is more rigour than the old portfolio-ledger path, which produced the revoked +527 bps artifact (`strategy_tracker.md` T4/T5).
- One harness means every idea faces the same tests; most past false positives came from ad-hoc scripts.
- Add by default: per-year results, size-tier split, 1×/2× cost, and placebo shuffle.
**Confidence:** high.

### Q17
**Position:** In-sample: 2021-10 → 2025-09 (4 years). Holdout: 2025-10 → 2026-09 (sealed; see Q15 caveat). After that, live forward paper trading is the real holdout. Require results in at least two regimes inside the in-sample period.
**Why:**
- Regimes available: 2022 drawdown/rate hikes, 2023–24 broad rally (especially small caps), late-2024–25 correction. That is roughly three, which is thin but usable.
- Prefer **walk-forward** (fit on past, test next block, roll) over a single split for anything with tuned parameters.
- Five years is short. We should state this openly in every result: "one market cycle at most."
**Confidence:** medium.

## G. Decision and learning

### Q18
**Position:** No ensemble until there are **at least 3 promoted, low-correlation signals** with ~1 year of forward paper record each. Until then, equal weight (or inverse-volatility) is enough.
**Why:**
- Fitted combination weights are themselves a test with many free parameters; with few signals and short history they overfit badly. Equal-weight portfolios routinely beat optimised ones out of sample when estimates are noisy (DeMiguel et al. 2009 — cited from memory, unverified).
- The calibration loop already refused every fold for lack of out-of-sample improvement (`strategy_tracker.md` T8). That is the data telling us there is nothing yet to weight.
- MoE gating and "temperature" add more tuning knobs; each is an untracked test.
**Confidence:** high.

### Q19
**Position:** LLM for **extraction** (documents → dated, checked features) and for **hypothesis generation** (logged as exploration). Not for decisions.
**Why:**
- An LLM decision is not reproducible and not testable in a backtest (the model has seen the future in its training data; it knows how 2023 went). That is look-ahead we cannot remove.
- Extraction is testable: measure accuracy on a hand-labelled sample before any extracted feature enters a test.
- LLM-generated hypotheses must enter the test ledger like any other; generating 50 ideas means 50 tests counted.
**Confidence:** high.

### Q20
**Position:** Demote when the forward record's rolling 12-month excess is below zero **and** a pre-stated statistical test says the live mean is significantly below the backtest mean, or on a hard drawdown stop. Go-live requires ≥ 12 months of forward paper trading with ≥ 30 independent cohorts, results consistent with the backtest (inside its confidence band), and measured costs.
**Why:**
- Expect live results to be smaller than backtest; published anomalies lose roughly a third to a half after publication (McLean & Pontiff 2016 — from memory, unverified). Plan for it in the bar.
- A demotion rule based only on "recent returns are bad" will demote real signals in normal drawdowns. Pair it with a test and a drawdown limit set *before* going live.
- Start capital small and scale with the forward record.
**Confidence:** medium.

## H. Operating model

### Q21
**Position:** Frozen until the first promotion **or** a review date (suggest 2027-01-31), whichever comes first. At the review, if nothing is promoted, ask whether the data can support any test, not whether we need more tools.
**Why:**
- Every new lens or feed is a new untested hypothesis set; it raises the multiple-testing count without adding power.
- Exceptions should be data-truth work only (dated fundamentals, delisted names), because those raise the power of every test.
**Confidence:** medium.

### Q22
**Position:** Yes: one `tasks/FRAMEWORK.md` plus two living files: the **hypothesis registry** and the **test ledger**. Session handoff = append a dated entry to the ledger/registry, not a new closeout file.
**Why:** From my lens, the test ledger *is* the handoff: what was tried, on what snapshot, with what result. Separate closeout files fragment the count of tests.
**Confidence:** medium.

---

## Questions I'd push other council members on

- **Data Steward:** How many delisted/suspended stocks are missing from the price parquet, and can we get them for 2021–2026? Can quarterly results be stamped with an exchange filing date within weeks, or is it months? (Q14 depends on it.)
- **Trading & Execution Lead:** For the post-results drift, what is the realistic round-trip cost for a 2–20 day hold at ₹1 cr/day turnover? If it is above ~60 bp, the long-side drift (about 55–75 bp per side, before costs) is gone before we start.
- **CRO / Independent Skeptic:** Will you hold the key to the holdout, and do you agree the drift hypothesis has already "seen" 2025–26 and must use forward data instead? What count of tests makes you distrust any pass?
- **Macro & Behavioural PM:** The drift has decayed from +96 bp (2023) to −41 bp (2026). Is there a regime or behavioural reason (more retail flow, faster dissemination, algo adoption) we can write down *before* testing, so "regime" is not chosen after the fact?
