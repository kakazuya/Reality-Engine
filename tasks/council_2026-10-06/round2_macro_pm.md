# Round 2 — Macro & Behavioural PM (debate)

All the numbers I cite from the diffusion study are provisional until prices are adjusted for bonuses and splits (Data Steward found 1:5 bonuses showing up as fake falls of −9% to −17%).

## 1. Answers to questions put to me

**Quant Lead — why did drift decay from +96 bp (2023) to −41 bp (2026)? Written down before any test.** I register three explanations, to be tested in this order. Each one makes a prediction that could prove it wrong.
- **D1 — data artefact (test first).** Bonus issues and splits peaked in the 2023–24 small-cap boom. Unadjusted bonus days look like crashes, and they enter the "reaction" sort and the drift window. *Prediction:* if the by-year pattern changes materially once prices are adjusted, D1 explains it.
- **D2 — trend regime.** 2023 to mid-2024 was a retail-led, one-way small-cap rally (record new demat accounts and SIP inflows). In that kind of market, any stock that moves keeps moving. From late 2024 to 2025 came record FII selling, a small-cap correction and SEBI's curbs on retail F&O trading (from memory, unchecked), and moves started to reverse. *Prediction:* drift has the same sign as a regime label computed beforehand from prices: whether small caps beat large caps over the trailing 6 months. If drift does not line up with that label, D2 is wrong.
- **D3 — faster reading of results.** By 2025, results summaries from apps, AI tools, X and Telegram reach retail investors within hours, so under-reaction shrinks. *Prediction:* the decay is concentrated in high-attention names (large turnover spike on the event day), and drift survives in low-attention names. If drift decayed equally across attention levels, D3 is wrong.

If none of the three fits, I accept that the 2023 drift was luck.

**Data Steward — can we test "2 regimes" with only about 30 macro documents?** Yes, because the regimes can be defined from prices alone: index drawdown state, India VIX, and small-cap vs large-cap relative strength. No macro documents are needed. But the honest count is about one cycle with three phases: the 2022 rate-hike drawdown, the 2023–24 small-cap boom, and the 2024–25 correction plus the tariff shock. There was no recession and no credit event. So a "2 regimes" test is weak. Report every year instead.

**Trading Lead and CRO — is the after-hours negative reaction bad news filed late (selection) or sell-the-news (behaviour)?** I lean about 65/35 toward **selection**, with low confidence. Evidence: the gap stays negative even when the run-up before results was negative (§8), which argues against pure sell-the-news. The gap also gets steadily worse the later in the day the filing comes, which is what selection predicts. **The key point for Trading:** the overlay does not need behaviour to be the cause. If *which companies file late* can be predicted in advance (from a company's past filing times and its pre-announced board-meeting date), then "don't buy ahead of results from habitual late filers" is a usable signal before the event. That holds even if earnings surprise absorbs the effect once results are out. So test the overlay on the **predicted** late-filer flag, not the actual filing time.

**CRO — does 2021–26 contain two genuinely different regimes?** It is one bull market with two real interruptions (2022, and late 2024–25), not two independent regimes. I agree with you.

## 2. Where I change my position

- **Q14:** PEAD (post-earnings drift) as a standalone trade **moves from #1 to research only.** Trading is right that 55–75 bp gross per side is less than about 80 bp of round-trip cost, and that half of the drift needs a short we cannot hold. Revised ranking:
  0. *Prerequisite:* adjust prices for corporate actions, then rerun §7/§8 and D1.
  1. **Results-timing avoid/trim overlay** using the *predicted* late-filer flag. Freeze the card now and confirm on forward data only. It is cheap, long-only, and the board-meeting dates are known in advance.
  2. **Earnings-surprise conditioning** as research. It needs filing-dated quarterly results, and it decides whether #1 is a selection effect.
  3. **Promoter open-market buying** from insider/SAST takeover-code disclosures. No one has touched this data yet, so a recent historical holdout is still clean for it.
  4. **Concall guidance raises**: only as an increment on top of #2.
  5. **Forced-flow events** (index changes, surveillance-list moves): first in line for a new feed after the freeze.
- **Q2:** Two books becomes **one event book now** (CRO). The fundamental book is shelved, not designed.
- **Q3:** The tradable floor rises to **₹5 cr per day** (Trading). Research continues at ₹1 cr, reported by tier.
- **Q5:** Drop the hit-rate rule (Quant/CRO). Add Trading's rule that the gross edge must be at least 2× the assumed cost.
- **Q7:** Score **pre-tax for promotion, post-tax for going live** (Quant/CRO). I previously wanted post-tax in the book.
- **Q17:** I drop my 2025–26 "pre-declared out-of-sample" split. Every year has already been looked at, so the **forward period is the holdout** (CRO). Exception: untouched hypotheses such as promoter buying may still seal 2025-10 → 2026-09 (Quant).
- **Q10:** I accept pausing the annual-report drain. No current test needs it.

## 3. Where I still disagree

- **CRO, on the 2026-12-31 kill switch.** A deadline is good. But your own rule requires 6 months of forward paper trading before promotion, and only one results season (Oct–Nov 2026) falls before Dec 31. So "nothing promoted by Dec 31 means buy the index" is a **guaranteed kill**, decided before anything is tested. The Dec 31 test should be: *is at least one frozen card running forward on adjusted, point-in-time data?* The real promote-or-kill date should come after two results seasons, around **2027-06-30**. In the meantime Shivam's money sits in the index anyway, so waiting costs nothing.
- **Trading Lead, on the ₹5 cr floor as the only universe.** Under-reaction comes from low attention, so a high floor filters out exactly the stocks where the mechanism lives. CRO also notes that ₹10 cr may be a hypothetical figure. Set the floor from **Shivam's real deployable capital**. If an effect exists only below ₹5 cr, that is a capacity limit, not a fake result.
- **CRO, on "guidance raises last, drop further work".** I agree it should not go first. But LLM extraction from concalls is the one edge source a one-person desk has that larger players do not use cheaply on thinly covered names. Keep it as a frozen card in the queue, not a burial.

## 4. Final one-line stance, Q1–Q22

- **Q1** Keep the north star, plus: name the counterparty, data the market actually had, drawdown and capacity limits, and the index fund as the default.
- **Q2** One event book now. Fundamental book shelved until dated fundamentals exist.
- **Q3** Turnover floor measured at each date: research at ₹1 cr, tradable at ₹5 cr or set from real capital. Report capacity.
- **Q4** Long-only. The avoid list is a separate scored book.
- **Q5** Horizon-scaled net information ratio, t ≥ 3, every year reported, gross edge ≥ 2× cost, drawdown cap, forward confirmation. No hit-rate rule.
- **Q6** Matched peers primary, index always reported, factor model as robustness only.
- **Q7** Pessimistic tiered cost stack at 1× and 2× cost. Pre-tax to promote, post-tax to go live.
- **Q8** One append-only test ledger with false-discovery control, versioned by data snapshot.
- **Q9** Corporate-action adjustment and ISIN map first, then delisted names, results filing dates, `DissemDT` check.
- **Q10** Research on frozen snapshots. Pause the annual-report drain. Keep the EOD price feed.
- **Q11** Version first: adjusted prices, then results filing dates, then insider disclosures, then index/surveillance history.
- **Q12** Set aside entirely. Revive only through a card.
- **Q13** Card must state who is on the other side and why they are slow or forced, plus a written decay explanation, execution fields and the snapshot ID. Shivam freezes it with a git commit.
- **Q14** Revised ranking in §2 above: timing overlay forward, surprise research, promoter buying, guidance, forced flows.
- **Q15** Exploration time-boxed and labelled. Confirmation forward only.
- **Q16** A thin harness built from the diffusion code, with known-answer tests, a shared adjusted-price loader and a cost-aware long-only backtest.
- **Q17** All history counts as in-sample. Forward is the holdout. Report by year.
- **Q18** Ensemble after 3 promoted low-correlation signals with forward records. Equal weight until then.
- **Q19** LLM for extraction (audited against the source) and for suggesting hypotheses (logged). Never decisions.
- **Q20** Pre-registered demotion, at least 2 results seasons of paper trading, a small real-money pilot to measure costs, then staged scale-up.
- **Q21** Freeze, with exceptions for data-truth repairs. Dec 31 checks progress. Promote-or-kill around 2027-06-30.
- **Q22** One FRAMEWORK file, an overwritten STATE file, an append-only ledger. AGENTS.md is overridden.
