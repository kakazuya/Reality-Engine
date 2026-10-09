# Council round 2: Quant Lead

## 1. Answers to questions put to me

**Data Steward: will I re-run the results-day puzzle with split, bonus and ex-dividend days removed, and how much survives?**
Yes, and it should come before any other analysis. The cheapest version is to drop every event whose window [−5, +20] contains a split, bonus or ex-dividend date. For 2021–22, where we have no action data, either drop those years or flag days whose price ratio sits near a split ratio with no news that day. My guess at the outcome, which is uncertain: the day-0/1 reaction gap (−85 bp, t −8) mostly survives, because ex-dates rarely fall on results days. The **drift numbers are more exposed**. A board meeting declares a dividend or bonus, and the ex-date usually lands 2–4 weeks later, which is inside the CAR(2,20) window. That puts a mechanical drop into exactly the "Outcome of Board Meeting" family, which shows the largest drift estimate (A ≈ 210 bp). Until the re-run is done, I would not quote any diffusion-study drift number.

**Trading Lead: what replaces "≥30 weekly cohorts" when results cluster into about 4 seasons a year?**
The unit that counts is the independent date cluster, not the trade. Results days in the same week share market shocks, so they behave like one observation. Replace the rule with: **at least 30 independent date clusters, spread over at least 4 results seasons in at least 2 calendar years.** Rough power arithmetic, my own estimate: one season gives about 6–8 heavy weeks. Two forward seasons (about 15 clusters) can only detect large effects of roughly 100 bp or more. Detecting a 50 bp effect needs something like 4–6 seasons. So the forward test has to be long, and that number should go on every card.

**CRO: what exactly is my holdout, and what does "+500 bps" mean for a 2-day versus a 20-day hold?**
You are right that I have no historical holdout; see change (a) below. On "+500 bps": drop it. The per-trade bar should come from costs, not from the holding period. Gross edge per trade must be at least **2× the round-trip cost** (Trading's rule, about 160 bp at our assumed 80 bp), whether the hold is 2 days or 20. On top of that, the book must reach an annualised net information ratio of at least 0.5 (excess return divided by its volatility) and in-sample t ≥ 3. Holding period then affects only turnover, and so total cost drag.

**Macro PM: can the drift survive the decay from +96 to −41 bp, should recent years count for more, and is surprise better measured by YoY growth or by the price reaction?**
- **Decay:** no, not as a trade. A drift whose year estimates go +96, +22, +24, −11, −41 bp is consistent with an effect that has gone. The honest forward expectation is about zero.
- **Recent years:** don't weight them; test them. Add a formal **trend-in-year-effects test** to every card. If the trend is significant, the forward estimate is the recent level, not the pooled mean.
- **Surprise measure:** use YoY growth, scaled by the company's own past variability. Literature calls this SUE (standardised unexpected earnings, the seasonal random-walk version). The price reaction is an outcome, not an independent sign, so it can only be a secondary condition. Caveat: today YoY PAT is 0.0 on 87% of rows, so the surprise has to be rebuilt from exchange XBRL filings stamped with the filing date.

## 2. Where I change my position

- **(a) Holdout (Q8/Q15/Q17).** I move from "seal 2025-10 → 2026-09 as a historical holdout" to **CRO's view: confirmation is forward-only**. Every year has been examined year by year, and the decay pattern is now common knowledge that would shape any new card. 2025–26 can still be used as a pre-declared **stability check**, but it must never be called out-of-sample.
- **(b) Diffusion evidence (Q9/Q14).** I move from "provisional" to **not quotable until re-run on corporate-action-clean data**, given Data Steward's finding that prices are unadjusted (the GULPOLY −11.9% fake day gets through the ±30% guard). I adopt "result unchanged after data correction" as a promotion requirement.
- **(c) First hypothesis (Q14).** I move from "post-results drift as the first test" to **earnings-surprise conditioning as a research question, with the late-filer time-of-day gradient as its first diagnostic** (Macro PM's framing). Drift as a stand-alone trade is dead: 55–75 bp per side, half of it on the short side, against about 80 bp of cost. Second card: a long-only "avoid new buys before results" overlay, frozen now and tested forward only.
- **(d) Universe (Q3).** I move from a ₹1 cr floor to **a ₹2 cr floor for trading tests, with Trading's ₹5 cr as a sensitivity run**. ₹50 lakh stays as a research-only sensitivity run.
- **(e) Scope (Q2).** I move from "two books" to **one active event book**. The fundamental book is defined on paper only, until dated fundamentals exist.
- **(f) Review date (Q21).** I accept CRO's **2026-12-31** in place of my 2027-01-31.

## 3. Where I still disagree

- **Macro PM (Q17): calling 2025-01 → 2026-09 "pre-declared out-of-sample".** Data we have already looked at, labelled out-of-sample, is worse than having no holdout, because it lends false confidence. The strongest argument is concrete: we already know drift turned negative in 2025–26. Any card written now is shaped by that knowledge.
- **Macro PM (Q5): "at most one losing year in five".** The per-year estimates are too noisy for this. The 2022 and 2024 CIs include zero at +22 and +24 bp. A real 50 bp edge would fail a year-sign rule quite often, and a lucky fake could pass it. A formal heterogeneity/trend test across years is better, because it uses the size of each estimate's noise and not just its sign.
- **CRO (Q5/Q20): "6 months forward, same sign" as the promotion test.** Under no edge, the sign is a coin flip, so this passes 50% of null signals. The forward test should be: **the forward mean is not significantly below zero, falls inside the backtest's confidence band, and the cluster count meets the power target stated on the card.** Six months can be enough for a tiny cost-measuring pilot. It is not enough for promotion.
- **CRO (Q16): "leave the cross-sectional test for later".** The top hypothesis, surprise deciles, is a cross-sectional sort. So is the check that an effect is not just momentum or size. Keep the cross-sectional test in the minimum harness, as a thin version. I agree with CRO's known-answer tests (inject a fake edge and recover it; feed no edge and get about zero).
- **Trading (Q14): the overlay "costs nothing".** It does cost something: forgone returns on the days out of the market. It was also found by exploration, and most of the reaction may sit in the overnight gap. It needs a frozen card and forward scoring like everything else.

## 4. Final stance per question

- **Q1:** Keep the north star; add "stable across years, on data not used to find it, within a stated drawdown and capacity".
- **Q2:** Run one event book now. The fundamental book exists on paper only until dated fundamentals exist.
- **Q3:** Universe set point-in-time by turnover. ₹2 cr/day floor for trading tests, ₹5 cr and ₹50 lakh as sensitivity runs. Score at ₹10 cr and report capacity.
- **Q4:** Long-only. Avoid lists are scored as an underweight book, never as shorts.
- **Q5:** Gross edge ≥ 2× cost, annualised net IR ≥ 0.5, in-sample t ≥ 3, drawdown cap, a year-trend test, placebo ≈ 0, and the result unchanged after data fixes. Hit-rate rule dropped.
- **Q6:** Primary benchmark is matched peers. Always also report against the index. Factor model as a robustness check.
- **Q7:** Fixed, tiered, pessimistic costs, and the edge must survive 2× costs. Pre-tax for promotion, post-tax for go-live.
- **Q8:** Append-only test ledger counting every variant, with snapshot and data version. FDR control across the whole ledger, and a t-hurdle that rises with the count.
- **Q9:** Data Steward's six checks. Corporate-action adjustment and an ISIN-history map come first. Nothing is quotable before they pass.
- **Q10:** Research on dated, frozen snapshots. Ingestion continues.
- **Q11:** Yes. First the results filing date plus XBRL surprise values, then index membership history.
- **Q12:** Set them aside, excluded from all scoring. They return only through a card.
- **Q13:** Card needs mechanism, counterparty, signal, timing, cost tier, a power target (number of clusters), pass and kill bars, snapshot ID. Shivam freezes it by git commit. Any edit means a new card.
- **Q14:** First, earnings-surprise conditioning with the late-filer gradient as its first diagnostic. Second, a forward-only pre-results avoid overlay. Guidance raises go after these.
- **Q15:** Exploration is free but labelled. Confirmation is forward-only, on a frozen card.
- **Q16:** Build from the diffusion code: event study, a thin cross-sectional test, a long-only cost/capacity backtest, known-answer tests, ledger hook.
- **Q17:** All history is in-sample. Report every year. The holdout is forward time.
- **Q18:** No ensemble before 3 promoted, low-correlation signals with forward records. Equal weight until then.
- **Q19:** LLM for extraction (with measured accuracy) and for generating hypotheses that go into the ledger. Never for decisions.
- **Q20:** Pre-registered demotion based on a test plus a drawdown limit. Tiny pilot after 2 seasons to measure costs. Scale up only after the power target is met (about 4–6 seasons).
- **Q21:** Freeze until the first promotion or 2026-12-31, whichever comes first. Truth-layer repairs are exempt.
- **Q22:** FRAMEWORK.md, plus a one-page STATE that is overwritten each session, plus the append-only ledger and registry.
