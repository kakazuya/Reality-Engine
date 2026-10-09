# Reality Engine — Framework Open Questions (2026-10-06)

**Purpose:** settle the high-level framework (objectives, layers, what gets fixed first) one question at a time before any further execution. No implementation detail here.

**How this file works:**
1. Questions below come from the framework discussion of 2026-10-06.
2. A council of advisors (Claude subagents, each playing a prop-desk role) debates them in rounds. Their working notes live in `tasks/council_2026-10-06/`.
3. The council chair writes a **Claude Council Verdict** under each question.
4. Shivam reads the verdicts and marks each one in **Shivam's call**: `OK` / `LOOK MORE` / `DIDN'T UNDERSTAND` (+ notes).
5. A question is settled only when Shivam marks it `OK`. Settled answers then go into `tasks/FRAMEWORK.md`, which becomes the single authority file.

## The proposed framework (for reference)

**North star:** find edges in Indian equities that repeat, have a clear reason behind them, and survive trading costs; then combine them into paper-traded decisions that correct themselves as new data arrives.

| # | Layer | Question it answers |
|---|---|---|
| 0 | Scoreboard | What counts as a win? |
| 1 | Truth layer (data) | Is the data what the market knew at that moment? |
| 2 | Signal layer (substrate) | What did we know about stock X on date t? |
| 3 | Hypothesis registry | What are we testing, and why? |
| 4 | Evaluation engine | Did it work? |
| 5 | Decision layer | What do we do tomorrow? |
| 6 | Learning loop | Is it still working? |

Research loop (layers 1→4) is kept separate from the production loop (layers 5→6).
Proposed order of fixing: scoreboard → truth audit → evaluation engine → hypothesis registry → feature versioning. Frozen until a first signal is promoted: new harnesses/routers, new lenses, MoE temperature, event graphs, new ingestion feeds.

---

## A. North star and scope

### Q1. Is the north star right?
"Repeatable, has a reason, survives costs" + paper-only until a signal is promoted. Is anything missing (e.g. risk, drawdown, capacity) or wrong?
A1. Consider jim simons medallion fund, it's not right all the time but it makes up for that with position sizing, drawdown risk managements, upside riding and all. What I mean to say, the north star is the one where I keep winning and cut losses, that's it. Rest is Desh, kaal & Sthiti which can remain dynamic. Because anyways the opportunities come in pockets and get taken away by competitors quickly like a school of fish scooping up thrown grains in the water. Whoever notices the opportunity and acts first gets fed for the day.

### Q2. Horizon and style
Event-driven (days to weeks, where the diffusion study points), multi-month fundamental investing, or both as separate books with separate scoreboards?
A2. PEAD plays out in days, so I want a mix of both technical and fundamental, they will have their own scoreboards but not distinct books, any trade during backtesting as well will be taken in mind by keeping both fundamental and technical thesis.

### Q3. Universe and capacity
Nifty 200 only, or small caps too? What liquidity floor? What capital size should the scoreboard assume (the 2026-09-25 desk meeting assumed ₹10 cr)?
A3. 10 cr is my hypothetical capital, but in actuality I have ₹1 cr so universe isn't a problem at this point as impact cost won't be a drag on me at current scale.  

### Q4. Long-only or long-short?
Given Indian shorting constraints (F&O stocks / SLB only), should the framework be long-only, with "avoid lists" in place of shorts?
A4. Ideally I would have wanted long short both but since we can't do overnight short, we will figure out correlations among sectors and stocks that have high negative correlation to achieve the same results but remember, desh kaal and sthiti of every situation to understand why did the negative correlation appear, how long did it last and why did it break if it did during the period for which we have the data.

## B. Scoreboard (layer 0)

### Q5. Promotion bar
Is the current bar (≥ +500 bps net excess, ≥ 30 weekly cohorts, 2 regimes same sign, hit-rate CI lower bound > 0.5, placebo ≈ 0) right? Should it differ by horizon, or use risk-adjusted measures (information ratio, drawdown)?
A5. You can create your own risk adjusted return measures. What I gave was just for reference.

### Q6. Benchmark
Excess against what: the index, matched peer stocks, or a factor model (e.g. market + size + value + momentum)?
A6. Your benchmark would be whichever is doing the best for any period among Nifty Smallcap 250, BSE 250 Smallcap, Nifty Midcap 150, BSE Sensex, BSE IPO Index.

### Q7. Costs and taxes
Use measured costs (from real fills/slippage) or a fixed assumed cost stack until real fills exist? Pre-tax or post-tax scoring?
A7. Don't worry about slippage, assume a fix cost at this point. It won't impact me that much at current stage.

### Q8. Multiple-testing budget
Over months we will test many ideas, and some will pass by luck. How do we account for that across the whole registry (false-discovery control, a sealed holdout period, a count of all tests tried)?
A8. We must have some statistical models to figure whether any strategy is a fluke or not. We won't have a holdout period anyway, it's a strict deploy pass. We will test against real cash and use position sizing and drawdown stoploss to protect ourselves.

## C. Truth layer (layer 1)

### Q9. Minimum data-truth checks
Which checks must pass before any test is trusted (point-in-time dates, corporate-action adjustment, survivorship/delisted names, quarantine)? Which of these are still unverified today?
A9. Figure out yourself. 

### Q10. Live writers vs research
The scheduled drains still write the live DB. Do we freeze ingestion, or research on dated snapshots while ingestion continues?
A10. Research on dated snapshots, keep the ingestion continuous, infact figure out the ways such that the ingestion quality keeps increasing in terms of testing, knowledge percent retention, labels, retrieval speed and efficiency, how to leverage my system the best for the same, etc.

## D. Signal layer (layer 2)

### Q11. Feature versioning
Every feature must be readable "as of date t". At a high level, is that the right requirement, and which features need it first?
A11. That's your job to keep testing and improving upon.

### Q12. The existing substrate
Moat scores, ENI, ripple effects and business profiles are mostly deterministic seeds. Keep them as unvalidated candidates, or set them aside until tested?
A12. Set them aside and try to create your strategies that are able to beat the same after refinements that are continuous.

## E. Hypothesis registry (layer 3)

### Q13. Hypothesis card
What must every card contain (mechanism, signal, universe, horizon, pass bar, placebo, ...)? Who freezes it, and what happens if it is changed after seeing returns?
A13. I trust you on this, from my end I can only say that the hypothesis is clear, concise such that two hypothesis don't test the same things just by reframing the problem statement itself.

### Q14. First hypotheses in the backlog
What goes first: the negative reaction to results (earnings-surprise conditioning), post-results drift, guidance raises in concalls (the 100-hour study), or something else? On what ranking rule?
A14. I won't interfere here, your job to rank them and promote/demote.

### Q15. Exploration vs confirmation
How much open-ended exploration is allowed, and how is it kept apart from confirmatory tests (e.g. a sealed final period nobody looks at)?
A15. Again use the best practices available, I won't suggest.

## F. Evaluation engine (layer 4)

### Q16. One shared harness
Build the shared harness out of the diffusion-study code? What must it cover at minimum (event study, cross-sectional test, portfolio backtest with costs)?
A16. I didn't understand the question.

### Q17. Time split
Which period is in-sample, which is held out, and how many regimes must the data span?
A17. You can do multiple tests and in-samples, it's not like that i have just one stock to test against. I have a lot of data.

## G. Decision and learning layers (layers 5–6)

### Q18. When does the ensemble get built?
After how many promoted signals is the all-peers ensemble / MoE worth building? Until then, is a simple equal-weight combination of promoted signals enough?
A18. It's a hard question to answer properly because for every scrip the ensemble will have differnt explainig powers from each factor so we have to store them on different layers like stock, industry, indices the stock is part of and eventually for the whole free float market. But I would say after atleast 4 trial, if the emsemble is at peak, it's worth promoting.

### Q19. Role of the LLM
Where does the LLM belong: extraction only (turning documents into dated features), hypothesis generation, or decisions too?
A19. At every stage, you are the backbone, your job is to start synthesising the data from raw formats to create engine that run consistently and start producing decisions independently so in a way you are creating algorithms that would start assisting you at every level starting from the bottom and eventually you become the CEO and only chime in when big decisions are to be taken and not day to day decisions.

### Q20. Demotion and go-live
How does a promoted signal get demoted? How long must it paper-trade forward before any real capital, and what does going live require?
A20. We won't paper trade on forward data, you have to create, test, confirm and deploy all on the past data itself. On live data the testing will just keep happening on your decisions and fine tune itself. Self recursice learning engine is the final objective.

## H. Operating model

### Q21. What stays frozen, and for how long?
New tools, harnesses, routers, feeds, lenses: frozen until the first promotion, or until a date?
I won't add any extra tools unless you recommend going forward except maybe some plugins and skills that would be helpful. The ensemble once tested and deployed will stay frozen until any other challenger comes up with more predictive power since we are going to keep creating hypotheses, testing them, killing or promoting them 24 by 7. Think it like we will keep the local maxima unless we spot a higher local maxima, global maxima is 100% predicitve power with < 5 bps of error margin which isn't going to happen anyway so yeah.

### Q22. Authority and handoff
One authority file (`tasks/FRAMEWORK.md`) replaces `CURRENT_PLAN_2026-09-27.md`? How do sessions hand off without piling up closeout files?
A22. This framework file is the authority going forward unless i explicitally say otherwise, execution handoff files can be there but delete all others which don't align with curent framework.

---

# Claude Council Verdicts

_Written by the council chair on 2026-10-06, after two debate rounds. Sources: `tasks/council_2026-10-06/round1_*.md` and `round2_*.md`. Where a member changed position in round 2, the round-2 position is the one counted. Members: **Quant** (Quant Lead), **Data** (Data Steward), **Trading** (Trading & Execution Lead), **CRO** (CRO / Independent Skeptic), **Macro** (Macro & Behavioural PM)._

## Read this first

- **The framework's shape is right, but the habits around it need fixing first.** No signal has passed the bar yet. The one "pass" on file (+527 bps, "46/46 wins") was a bug. The council's priority is therefore guardrails (a test ledger, frozen hypothesis cards, a truth-checked data loader), not new machinery.
- **Confirmed data finding: prices are not adjusted for splits, bonuses or dividends.** On a 2026-10-06 read-only check, Data found that `prev_close` is the raw old price. Examples: GULPOLY's 1:5 bonus shows as a −11.9% day when the true return was about +5.7%, and that slips through the diffusion study's ±30% filter. Past price rows also carry *today's* ISIN, so 289 of 386 split/bonus actions do not join to prices. Corporate-action data starts only on 2023-01-02. **Every diffusion-study number is provisional.** The drift numbers are the most exposed, because dividend and bonus ex-dates usually fall 2–4 weeks after a board meeting, inside the drift window. No cumulative-return (CAR) level should be quoted until it has been re-run on adjusted prices.
- **All of 2021-10 → 2026-09 has already been looked at year by year. The only clean test is forward time.** A sealed historical period (2025-10 → 2026-09) can still be used, but only for idea families nobody has examined (for example promoter buying or guidance raises), and only if the data loader enforces it.
- **Post-results drift as a stand-alone trade is dead.** It is about 55–75 bp gross per side, against about 80 bp of round-trip cost. Half of it is on the short side, which a cash book cannot hold, and the yearly estimates went +96 → +22/+24 → −11 → −41 bp. It stays a research question only.
- **First work item: earnings-surprise conditioning of the results reaction, with the "late filer" time-of-day pattern as its first diagnostic.** In parallel, a long-only "don't buy before results / trim before results" timing overlay runs as a frozen card, tested on forward data only.
- **TIME-SENSITIVE (decide this week):** the Q2 FY27 results season starts in about two weeks (mid-October to mid-November 2026). If a late-filer / pre-results overlay card is frozen by git commit **before** that season starts, then that season and the Jan–Feb 2027 season count as genuine forward evidence. If the card is not frozen in time, a quarter of forward evidence is lost. (CRO, round 2, supported by Trading and Macro.)
- **One active book only: the event book (days to weeks).** The multi-month fundamental book stays reserved with zero hours until results carry their real publication dates.
- **Freeze new tools, feeds, lenses, the mixture-of-experts router and event graphs.** Data-truth repairs are exempt, as a closed, named list with an hour budget. **2026-12-31 is a hard review date.** The council splits on whether that date means "stop" or "check progress" (see Q21 and Q23).
- **Only Shivam freezes cards, opens the holdout, and promotes.** No agent, council role included, may do any of these. "AGENTS.md" currently steers every new session toward the frozen architecture, and its "ISINs never change" rule has been shown false. It needs a header that defers to `FRAMEWORK.md` (see Q24).
- **Two numbers only Shivam can supply:** the capital Shivam would really deploy (the ₹10 cr figure looks hypothetical), and the size of a first real-money pilot. The liquidity floor, capacity and the go-live ladder all depend on them.

---

### Q1. Is the north star right?
**Verdict:** Keep it, with five additions. Every edge must be: (1) found on data the market actually had at that moment; (2) stable across years, not just significant when all years are pooled; (3) positive after costs at a stated capital size, with an entry time Shivam could really have traded; (4) within a stated maximum drawdown; and (5) backed by a named counterparty, meaning someone identifiable who is slow or forced and keeps losing to it. The default alternative is a Nifty index fund. If nothing beats it after costs, the honest answer is "buy the index".
**Why:**
- Quant: "repeatable" must be testable. The drift is significant when pooled (q ≤ 0.003) but swings by year from +96 to −41 bp (`SESSION_CLOSEOUT_2026-10-05.md` §3).
- Trading: "survives costs" means nothing without a size. A 60 bp edge can be real at ₹25 lakh and gone at ₹10 cr.
- Data: an edge found on look-ahead data is a bug, not an edge. Look-ahead means using information the market did not yet have.
- Macro: "has a reason" is too easy to write after the fact. "Who is on the other side and why are they slow?" can be checked. CRO adopted this in round 2, and added the index fund as the bar the whole project must beat.
**Vote:** 5–0.
**Confidence:** high.
**Shivam decides:** nothing. Confirm or reject the five additions.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q2. Horizon and style
**Verdict:** Two books, never scored together, but only the **event book** (holds of 1–20 trading days) gets any hours now. The **fundamental book** (holds of 3–12+ months) stays reserved, with no design and no hours, until quarterly results carry the date they were actually published.
**Why:**
- Quant: five years of data give about 250 non-overlapping weekly windows but only about 20 non-overlapping 90-day windows and 5 one-year windows. Multi-month claims can be explored on this history but not confirmed.
- Data, CRO, Macro: quarterly financials have no filing date (`created_at` is the date the project fetched them), 2023 quarters are missing, and YoY profit growth is 0.0 on 87% of rows (`PIT_LABEL_AUDIT_2026-09-29.md`). Any fundamental backtest today would have look-ahead.
- Trading: the books differ in costs, tax and turnover. An event book replacing positions about every 15 days pays about 12% a year in cost drag at 80 bp a round trip. Blending the two hides which book works.
- CRO began at "one book only" and moved to "two books, zero hours for the fundamental one". The remaining four had already moved to "one active book".
**Vote:** 5–0.
**Confidence:** high.
**Shivam decides:** nothing. Confirm or reject.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q3. Universe and capacity
**Verdict:** Do not use "Nifty 200". Define the universe **as of each date** by median daily traded value. Today's index list contains only the survivors, and the project holds no membership history. The **trading floor follows from capital:** floor = position size ÷ (participation cap × days allowed to fill). Use a 5% participation cap as the base case and 2% as a stress test. Until Shivam gives a real capital figure, score at a ₹5 cr/day floor and run ₹1–2 cr and ₹50 lakh as research-only sensitivity tiers, always reported by size tier. Treat ₹10 cr as one point on a capacity curve, not as the default.
**Why:**
- All five members agree that today's `is_nifty200` flag used backwards is survivorship bias (`PIT_LABEL_AUDIT`).
- Trading: ₹10 cr across 20 names is ₹50 lakh per position. That equals a whole day's trading in a stock at the diffusion study's ₹50 lakh floor. In a ₹1 cr/day name, round-trip cost is about 60–110 bp (Trading's estimate, unmeasured).
- CRO backs ₹5 cr for scoring. Quant moved from ₹1 cr to ₹2 cr, with ₹5 cr as a sensitivity run. Macro moved to ₹5 cr as tradable but warns that under-reaction is strongest in low-attention small names. An effect that lives only below ₹5 cr is a capacity limit, not a fake.
- Participation: Trading proposes 5% base and 2% stress. CRO proposed 1–2% in round 1 and did not restate it in round 2. Data: small caps only after price adjustment and delisting fixes, because bonuses cluster there.
**Vote:** 5–0 on a point-in-time liquidity universe tied to real capital. On the base floor, 4–1: Quant prefers ₹2 cr for trading tests.
**Confidence:** medium. The exact floor and cap are judgement calls until a spread estimate exists.
**Shivam decides:** (a) the capital Shivam would actually deploy; the floor follows from it (see Q28). (b) Whether small caps get a separate research cell now or after the data fixes.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q4. Long-only or long-short?
**Verdict:** **Long-only.** "Avoid lists" are scored as their own cohort and never booked as shorts. They are scored either as an underweight against the benchmark or as a "timing benefit on trades already planned". A futures-based short cell may be considered only after a long signal is promoted.
**Why:**
- Trading, Macro: cash shares cannot be shorted overnight in India. Stock lending (SLB) is thin, and stock futures cover only about 180–220 names with large lot sizes (from memory, unchecked).
- CRO: the only "win" on file was a SELL-side framing bug (T4: every SELL row had target > entry). Short-side mechanics are where the project has already hurt itself.
- Quant: the diffusion drift is measured on both sides together, so the long half must be reported on its own.
- Data: a short leg would need a dated F&O eligibility list, which the project does not hold.
**Vote:** 5–0.
**Confidence:** high.
**Shivam decides:** nothing. Confirm or reject.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

## B. Scoreboard

### Q5. Promotion bar
**Verdict:** Replace the bar. Drop "+500 bps" and the hit-rate rule. A signal is promoted only if **all** of these hold:
- gross edge per trade at least **2× the assumed round-trip cost** (about 160 bp at today's 80 bp assumption);
- an annualised net **information ratio ≥ 0.5** (yearly excess return divided by how much that excess return varies; roughly, return per unit of risk taken versus the benchmark);
- **t ≥ 3** on the historical data (t measures how many "noise widths" the effect sits away from zero);
- at least **30 independent date clusters spread over at least 4 results seasons** in at least 2 calendar years;
- placebo ≈ 0;
- a stated maximum drawdown;
- every year reported, plus a formal test that the yearly results are not trending toward zero;
- the result still holds after the data fixes, on a pinned snapshot;
- forward confirmation (see Q20).

Freeze this bar now.
**Why:**
- All five members: "+500 bps" without a horizon means nothing. It is extraordinary over 10 days and modest over 12 months.
- Quant, Trading, CRO, Macro: a hit-rate test is wrong for event trades, which often win less than half the time but win big. It becomes a diagnostic only.
- Quant: results in the same week share market shocks, so the unit that counts is the independent date cluster, not the trade. By Quant's rough power arithmetic, two seasons can detect only effects of about 100 bp or more, while a 50 bp effect needs 4–6 seasons.
- Data (with CRO and Quant agreeing): the bar must include "unchanged after data correction". CRO: the bar has already been revised once after an embarrassment (2026-09-23), so freeze it.
**Vote:** 5–0 on everything except the per-year rule, where it is 2–2 with 1 not stating a view. CRO and Macro want a hard rule: no more than one losing year in five, and the latest year must not be the worst. Quant objects that yearly estimates are too noisy. The 2022 and 2024 figures already have confidence intervals that include zero, so a real 50 bp edge would often fail a sign rule. Quant wants a formal test of whether yearly effects differ or trend. Trading asks only for "stability by year". **Chair's recommendation:** make the formal trend/heterogeneity test the gate, and show the losing-year count beside it as a red flag.
**Confidence:** medium-high.
**Shivam decides:** the per-year rule: a statistical trend test (Quant), a hard sign-count rule (CRO, Macro), or both.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q6. Benchmark
**Verdict:** For research, use **matched peers**: stocks in the same liquidity and size bucket, on the same days. For the book, **always also report excess return against an investable index after costs** (Macro suggests Nifty 500 total return), because that is what the money actually competes with. A factor model (market, size, value, momentum) is only a robustness check until the factor spine has been validated. Every benchmark must be built from the same adjusted, survivorship-aware price data as the signal.
**Why:**
- Quant, Macro: an equal-weighted market benchmark created fake drifts of −8 bp/day for large caps and +8 bp/day for small caps. Bucket matching fixed this (diffusion study §2.1, §7).
- CRO, Trading: the money question is whether the strategy beat an index ETF held in the same capital slot, after costs. Report that number even when it looks bad.
- Data: if peer stocks contain fake bonus-day crashes, both sides of the comparison are wrong. The −4 bp/day placebo drift (study §4.3) may partly be this.
**Vote:** 5–0.
**Confidence:** high.
**Shivam decides:** which index is the book's yardstick (for example Nifty 500 TR, or a midcap index if the universe is mid/small).
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q7. Costs and taxes
**Verdict:** Use a **fixed, deliberately pessimistic, dated cost stack, tiered by liquidity**, and require the signal to survive at both 1× and 2× cost. Trading's illustrative impact tiers are 20/40/80/150 bp round trip, labelled as assumptions. Change the current bar's wording from "measured costs" to **"modelled costs"**: paper trading never touches the order book, so the current wording can never be met. "Measured" is reserved for fills from a real pilot. Score **pre-tax to promote a signal and post-tax to approve a book for going live.**
**Why:**
- Trading, CRO: the current bar is unpassable by construction while capital is parked. That contradiction invites quiet loosening later.
- Trading: until fills exist, estimate bid-ask spreads from daily high/low prices (Corwin–Schultz) plus an impact term that grows with order size. Data: this works only on *adjusted* prices with ex-dates excluded, otherwise split days create huge fake spreads.
- Quant, Macro (who moved in round 2), CRO: tax depends on holding period and law, so it is noise for a statistical test but decisive for go-live. Trading's figures: STCG (short-term capital gains tax) 20%, LTCG (long-term) 12.5% above ₹1.25 lakh, STT 0.1% per side, stamp duty about 0.015% on buys. **All are from memory and unchecked** (see caveats).
- Data: date the cost stack, because STT and stamp-duty rates change with each budget.
**Vote:** 5–0.
**Confidence:** high on the structure, low on the exact basis-point tiers.
**Shivam decides:** nothing. Confirm or reject. Shivam is best placed to sanity-check the tax figures, or to ask a CA.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q8. Multiple-testing budget
**Verdict:** Keep one **append-only test ledger**. Every test, variant, discarded design and failed run gets a row, including cost, fill-price and entry-timing variants. Each row records the data snapshot ID and data version. Apply **false-discovery-rate (FDR) control across the whole ledger**, not just within one study. FDR control limits the share of "passes" that are really luck; the Benjamini–Hochberg method is fine. Require t ≥ 3. When tuned variants compete, also report a "best of N" luck test (deflated Sharpe ratio, or Hansen's SPA test). Once the ledger passes about 50 entries, forward confirmation is mandatory for any pass.
**Why:**
- Quant: with 20 tries at the 5% level, one false pass is expected. Without a count, a pass cannot be interpreted.
- CRO: the project already has about 20+ strategy-level tries with zero real passes (T1–T12, F1/F2, the P1 grid, the diffusion families). Discarded designs are vanishing into prose; the first matching design in study §7 is one example.
- Data: a re-run after a data fix is a new test, so the ledger must record which data version each test used.
- Trading: choosing "open vs close" fills after seeing results is also snooping, so those choices count too.
**Vote:** 5–0.
**Confidence:** high.
**Shivam decides:** nothing. Confirm or reject.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

## C. Truth layer

### Q9. Minimum data-truth checks
**Verdict:** Nothing is trusted until these checks pass on the snapshot being used. Today **one passes, two partly pass, and four fail**. Fix in this order: price adjustment and an ISIN-history map, then delisted names, then results filing dates.

| Check | Status today | Evidence (Data's read-only DB checks unless noted) |
|---|---|---|
| Event time = public release time ("point-in-time") | Partly verified | 71,937 documents carry BSE dissemination timestamps. 31,215 (30%) are undated and must be excluded, not filled in. BSE publishes within about a minute of upload (median 1 s, 99th percentile 61 s, across 139,802 results filings). No NSE cross-check has been done yet. |
| Prices adjusted for splits, bonuses and dividends | **Fails** | BLUESTARCO −48.2%, VBL −48.8%, IONEXCHANG −90.5%, GULPOLY −11.9% on ex-dates. Actions data starts 2023-01-02. |
| Stable identity across ISIN changes | **Fails** | Old price rows carry today's ISIN. 289 of 386 split/bonus actions do not join. |
| Delisted names included (no survivorship bias) | Fails / unmeasured | 574 of 5,710 ISINs stop before 2026-06, but real delistings cannot yet be told apart from ISIN changes. There is no delisting table. |
| Fundamentals dated by publication | **Fails** | No filing-date column in `quarterly_financials` or `financial_metrics`. |
| Quarantine applied | Passes | `substrate_quarantine` is materialized (1,356 synthetic-ISIN companies, etc.). |
| Pinned, checksummed snapshot | Not yet a rule | The live DB was modified today at 12:40. |
| Tradable at entry (Trading) | Unverified, no data | No price-band, suspension, ASM/GSM surveillance-list or F&O history table exists. |

**Why:**
- Data's finding overturns the 2026-09-29 audit's claim that `prev_close` adjusts for splits. Quant, CRO and Macro accept that it is a failure, not "partly done".
- An unadjusted SWANDEF jump already voided one earlier result (100-hour study).
- Survivorship bias pushes long-only results upward: failed companies drop out of the data, and they are also the ones most likely to file late.
**Vote:** 5–0.
**Confidence:** high on status; medium on how much fixing these will move the results.
**Shivam decides:** whether results computed on unadjusted prices are labelled "provisional" (the council's view) or "void".
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q10. Live writers vs research
**Verdict:** Research runs **only on dated, checksummed snapshots**. Each result cites the snapshot date, row counts and the code's git commit. Ingestion continues on the live DB, especially the end-of-day price update that forward paper trading depends on. Writers must be quiet while a snapshot is being cut, and no *new* feed types may be added.
**Why:**
- All five: a result read from a live, changing file cannot be reproduced. The live file changed today, and the Oct 2 upload broke mid-write.
- Data: pausing a writer does not make a result reproducible, because a paused task can be re-enabled. Only a dated copy plus the code commit can be re-run.
- Trading, CRO: freezing ingestion would kill the forward test, and forward time is now the main holdout.
**Vote:** 5–0 on snapshots. On whether to also **pause the annual-report drain**, the council is split. CRO and Macro would pause it because no current test needs it. Data and Trading say it is Shivam's scope call. Quant says let ingestion continue.
**Confidence:** high.
**Shivam decides:** whether to pause the annual-report drain (and `CapacityLoop`) until a hypothesis card needs that data. This needs Shivam's elevated PowerShell.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

## D. Signal layer

### Q11. Feature versioning
**Verdict:** Yes, the requirement is right. Every feature row carries two dates: the period it describes, and when it first became public (`first_public_at`). A read "as of date t" only sees rows public by t. Revisions are added as new rows, never overwrites. Version **only what the queued hypotheses need**, in this order:
1. adjusted prices plus the ISIN-history map;
2. results filing dates (days of work), then the reported figures from exchange XBRL filings (weeks of work), which also fill the missing 2023 quarters;
3. the NSE insider-trading feed, index membership, and F&O and surveillance-list history;
4. sector labels;
5. LLM-extracted features, stamped with the source document's time, the model and the prompt version.
**Why:**
- Data: nothing beyond prices and document timestamps meets this requirement today. The 139,802 results filings already have exact BSE timestamps and only need mapping to a quarter. The time estimates are Data's own and uncertain.
- Quant, Macro: the top hypothesis (earnings surprise) is blocked until results carry their publication date.
- CRO: versioning everything at once is another architecture project, so do only what the critical path needs.
- Trading: tradability fields (traded value, surveillance status, F&O eligibility) decide whether a trade could have happened at all.
**Vote:** 5–0.
**Confidence:** high.
**Shivam decides:** nothing. Confirm or reject.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q12. The existing substrate
**Verdict:** **Set aside.** Moat scores, ENI, ripple effects and business profiles are labelled "untested, undated priors" and excluded from all scoring, dossiers and theses. Do not delete them. Each idea can come back only by being rebuilt from dated documents and passing its own hypothesis card.
**Why:**
- Data, Quant: they were generated in Aug–Sep 2026 (moat history has 2 dates, policy has 1), so any backtest using them has look-ahead by construction.
- CRO: across 43,789 material moves, the quality, policy and supply lenses cast **0** directional votes (`test_findings_2026-09-24.md` §1).
- Macro: ripple `transmission_elasticity` is a constant 1.0 on 61 of 61 rows, and `regime_tag='*'` is set on 100% of rankings. Macro defends the *ideas* (business quality and supply-chain transmission are real economics) and suggests the tariff event card as the cheapest honest way to revive the supply-chain idea. Its run-1 results were never written up.
- CRO: calling them "candidates" lets them leak back into theses as if they meant something.
**Vote:** 5–0.
**Confidence:** high.
**Shivam decides:** nothing. Confirm or reject.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

## E. Hypothesis registry

### Q13. Hypothesis card
**Verdict:** Every card contains:

- **Mechanism:** why it should work, and why it has not been arbitraged away.
- **Counterparty:** who is on the other side, and why they are slow or forced to trade.
- **Expected decay:** how fast the edge is expected to fade.
- **A falsifiable prediction:** the sign and rough size of the effect.
- **Signal definition and data inputs:** the exact signal, the timing field used, the exclusion rules, the price-adjustment version and the snapshot ID.
- **Universe:** the universe, with the floor formula.
- **Execution:** entry and exit rules (the first tradable price after release), the participation cap, the instrument, the cost tier, the break-even cost, and the expected short-term vs long-term tax mix.
- **Testing:** benchmark, primary statistic, pass bar and kill bar.
- **Controls and power:** placebo and negative controls, plus a **power target**, i.e. how many independent date clusters are needed to detect the claimed effect.
- **History and ledger:** which years this idea family has already seen, the ledger ID, and an outcome section.

**Shivam freezes the card with a git commit before the confirmatory run.** Any change after seeing returns creates a new card. The old card is logged as failed and is never edited.
**Why:**
- Quant: pre-registration is what makes a significance test mean anything. The power target stops tests that cannot succeed.
- CRO: no agent may freeze or amend a card, because agents produced the 46/46 promotion. A git timestamp is cheap, tamper-evident proof. Quant and Macro both moved from "CRO freezes" to "Shivam freezes".
- Macro: `tariff_event_card_2026-09-29.md` is already the right template, but it lacks an outcome section.
- Data: changing the data after seeing returns is as much p-hacking (tweaking until something looks significant) as changing the parameters.
**Vote:** 5–0.
**Confidence:** high.
**Shivam decides:** nothing. Confirm that Shivam personally does the freezing.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q14. First hypotheses in the backlog
**Verdict:**
- **Step 0 (prerequisite):** adjust prices, then re-run the results-day puzzle (diffusion study §7/§8) with split, bonus and ex-dividend windows removed.
- **Card A (freeze this week, forward only):** a long-only **pre-results timing overlay**. Delay planned buys until after results, and move planned sells or trims to before them. Score it as a timing benefit on planned trades, not as a strategy. Base it on a *predicted* late-filer flag, built from each company's past filing times and its pre-announced board-meeting date. Report how much of the reaction sits in the overnight gap that nobody can trade.
- **Card B (main research study):** **earnings-surprise conditioning** of the results reaction and drift. Its first diagnostic is the late-filer time-of-day gradient: does that gradient disappear once surprise is controlled for?
- **Then, one at a time:** promoter open-market buying, but only after the NSE insider-trading feed is loaded. After that, guidance raises from concalls, tested only for what they add beyond earnings surprise. Forced-flow events (index changes, surveillance-list moves) are first in line for a new feed after the freeze.
- **Ranking rule:** mechanism × data readiness × statistical power × long-only tradability, divided by the hours needed to test it.
**Why:**
- The −85 bp results-day gap against matched non-announcers (t −8.1, negative every year 2023–26) is the strongest number in the project. It worsens from about −15 bp for filings before 13:00 to −84 bp for filings after 21:00 (study §7, §8). CRO notes that it was found by exploration, so it must be confirmed on forward data.
- Trading: drift as a trade is gone. The long half of the drift (55–75 bp) is below costs of about 60–110 bp. Card B must state its break-even before the run: gross edge of at least about 160 bp.
- Macro (round 2) registered three explanations for the drift's decay *before* testing them. D1: a data artefact from unadjusted bonus days, tested first. D2: a regime explanation, with drift sign following whether small caps have been beating large caps. D3: faster retail reading of results, so decay concentrated in high-attention names. Macro leans about 65/35 toward "bad quarters get filed late" (a selection effect).
- Data: the live `insider_trades` table has **0 rows**, and BSE takeover-code (SAST) headlines carry no buy/sell direction. Promoter buying therefore cannot start yet. CRO: one study at a time, not in parallel.
- Quant: the overlay is not free. It gives up the return on the days spent out of the market, which is why it gets a card and forward scoring like everything else.
**Vote:** 5–0 on the content. On the order there is a minor split: Macro puts the overlay (A) as #1 and surprise (B) as #2, while the other four put B first with A in parallel. In practice both start now, because A only needs freezing and forward tracking.
**Confidence:** medium.
**Shivam decides:** (a) whether to freeze Card A this week (time-sensitive). (b) The exact kill bar on Card A. CRO's proposal: filers after 15:30 trail matched non-announcers by at least 30 bp on CAR(0,1) at t < −2, on adjusted prices, scored over the Oct–Nov 2026 and Jan–Feb 2027 seasons. CAR(0,1) is the cumulative abnormal return on the results day and the day after. (c) Card B must pre-state "conditioned drift ≤ 0 in 2025–26 means killed", with no "the regime changed" excuse allowed afterwards (CRO).
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q15. Exploration vs confirmation
**Verdict:** Exploration is allowed but **logged in the ledger and labelled "exploratory — not evidence"**. It can never promote anything or be quoted as a result. Confirmation happens only on a frozen card, in one of two ways:
- for the **results family** (reaction, drift, late filers), **on forward data only**, because every year has already been looked at;
- for **untouched families**, on a **sealed 2025-10 → 2026-09 holdout**. The shared data loader must physically cut those dates off unless a ledger entry, approved by Shivam and naming the frozen card, unseals them.

A **holdout** is a stretch of data nobody looks at until a single final test.
**Why:**
- CRO, Quant, Data, Macro all moved to "forward is the main holdout". A historical period that has already been examined, if labelled out-of-sample, gives false confidence (Quant).
- Data: "a promise is not a seal". The parquet files and Shivam's Drive copy already contain 2025–26, and agents read them freely, so only loader enforcement works.
- CRO: no agent can hold the key, because agents can read any file.
**Vote:** 5–0 on the confirmation rules. On **how much exploration**, 2–2 with 1 abstaining. CRO and Macro (round 2) want it **time-boxed to about 30% of hours**, because Shivam's time is the binding constraint and "unlimited exploration is how 40 task files appeared in two weeks". Quant and Data say it is free as long as it is logged and labelled. Trading did not take a position.
**Confidence:** high on the rules, medium on the cap.
**Shivam decides:** whether exploration gets a 30%-of-hours cap.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

## F. Evaluation engine

### Q16. One shared harness
**Verdict:** Yes. Build a **thin** harness under `analysis/`, extending the diffusion-study code rather than rebuilding it inside `reality_engine/`. The minimum:
- one shared **data loader** that enforces the Q9 checks (adjusted returns, ISIN map, point-in-time dates, quarantine, holdout cut-off), replacing the per-script ±30% patches;
- an event study with matched benchmark, clustered errors and negative controls;
- a thin cross-sectional test;
- a long-only portfolio simulation with tiered costs, the participation cap, no fill on price-band-hit days, exits for delisted names, a capacity curve (₹25 lakh → ₹50 cr) and a tax ledger reused from `sip_backtest`;
- automatic per-year and size-tier output at 1×/2× cost;
- **known-answer tests**: inject a fake edge and it must be recovered; feed zero edge and it must report about zero;
- **bug-class invariants**: exit prices equal market prices, and trade direction matches stop/target sides;
- a hook that writes every run to the ledger.
**Why:**
- Quant, Macro: the diffusion code already has matched benchmarks, two-way clustered errors, FDR control and negative controls. It is the only code that produced a result surviving its own controls (0 of 20 control strata rejected).
- Trading: an event-study return is not a P&L. Overlapping positions, cash limits and costs can erase it.
- CRO: the known-answer tests and invariants catch the class of bug behind the 46/46 result.
- Data: if the ±30% guard stays as a local patch, the next study will copy it and inherit the bonus bug.
**Vote:** 5–0 on building from the diffusion code. On including the cross-sectional test now, 4–1. In round 1, CRO wanted to defer it and did not restate this in round 2. Quant's counter: the surprise-decile study and the "is it just momentum?" check are both cross-sectional.
**Confidence:** high.
**Shivam decides:** nothing. Confirm or reject.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q17. Time split
**Verdict:** **All of 2021-10 → 2026-09 is in-sample.** Every result reports each calendar year separately, plus the year-trend test from Q5. The **holdout is forward time**, starting from each card's freeze date. The only exception is the per-family sealed 2025-10 → 2026-09 period for untouched families (Q15). Be candid that the data span **one market cycle with three phases**: the 2022 rate-hike drawdown, the 2023–24 small-cap boom, and the late-2024–25 correction plus the tariff shock. There was no recession, no credit event and no 2020 crash, so "two regimes, same sign" is a weak test. Define regimes in advance from prices alone (index drawdown, India VIX, small vs large relative strength), not from macro documents.
**Why:**
- All five moved to this view in round 2. Quant dropped the 2025-10 seal for the results family. Macro dropped the "pre-declared out-of-sample 2025–26" idea. Data dropped its 2022–24 / 2025–26 split.
- Quant: walk-forward testing (fit on past data, test the next block, roll forward) for anything with tuned parameters.
- Data: 2021–22 needs a corporate-action backfill before it is usable. Trading: the span must include a high-volatility stretch, because that is when spreads widen.
**Vote:** 5–0.
**Confidence:** high on the rule, medium on the regime labels.
**Shivam decides:** nothing. Confirm or reject.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

## G. Decision and learning layers

### Q18. When does the ensemble get built?
**Verdict:** No ensemble, no mixture-of-experts router (a model that switches between sub-models), and no "temperature" until there are **at least 3 promoted, weakly correlated signals, each with a forward paper record**. Until then, use **equal weight**, capped by liquidity, and **net overlapping trades**: two signals agreeing on one stock means one trade, not two. Any router must later beat equal weight on forward data to exist at all.
**Why:**
- Quant, CRO: fitted weights are themselves a many-parameter test, and simple equal weighting is hard to beat out of sample (DeMiguel et al. 2009; cited from memory by both members, not re-verified).
- Quant, Macro: the calibration loop already refused every fold ("no out-of-sample improvement", `strategy_tracker.md` T8). There is nothing to weight yet.
- Macro: the all-peers vision is kept but sequenced. The hypothesis registry *is* the honest peer competition. Macro also wants the 3 signals drawn from at least 2 different lens families.
- Trading: netting trades is a cost saving that no mixture-of-experts layer provides.
**Vote:** 5–0 on the principle. On how long the forward record must be, members differ: CRO and Trading say at least 6 months each, Quant about 1 year, Macro a year before regime-varying weights.
**Confidence:** high.
**Shivam decides:** the forward-record length: 6 months or 12 months.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q19. Role of the LLM
**Verdict:** The LLM does **extraction**, turning documents into dated features. Each extracted feature is measured for accuracy on a hand-checked sample before use, and stamped with the source document's time, the model name and the prompt version. The LLM may also **suggest hypotheses**, which go into the ledger and count as tests. **It never makes decisions, promotions or card freezes.** Orders come from a deterministic rule that can be replayed.
**Why:**
- Quant, Data, Macro: an LLM decision cannot be backtested honestly, because the model's training data already contains what happened after 2023. Even extraction must ask only what the document itself says.
- CRO: the track record includes fabricated citations, the 46/46 promotion, and a "100% F1" commit claim (`10fb07e`) that nobody has independently re-checked.
- Trading: slippage cannot be audited against a non-repeatable decision, and SEBI's algo rules expect explainable logic (current rules unchecked).
- Macro: extraction is where a one-person desk gains a real edge, by reading about 100k filings on thinly covered names.
**Vote:** 4–1. Data's round-2 stance is "extraction only" and does not mention hypothesis generation. Everyone agrees on "never decisions".
**Confidence:** high.
**Shivam decides:** nothing. Confirm or reject, including whether LLM-suggested hypotheses are allowed.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q20. Demotion and go-live
**Verdict:** A staged ladder:
1. **Paper forward** for at least 2 results seasons **and** at least 30 independent events. The paper fill is the next tradable price after the decision is time-stamped, and each decision logs the input snapshot it saw.
2. A **small real pilot**, suggested at ₹10–20 lakh (1–5% of capital). Its job is to *measure fills*, not to make money.
3. **Scale in steps** of 10% → 25% → 50% → 100%, only while realised costs stay within 1.5× of the model and live returns track paper within the confidence band. **Do not scale past 25% before 12 months forward and the card's power target are met.**

**Demotion is automatic and fixed in advance, with no retuning.** It triggers on any of:
- rolling forward net excess below zero together with a pre-stated test showing it is significantly below the backtest;
- realised costs above 2× the model;
- a live-vs-paper tracking gap beyond the band;
- a drawdown beyond the book limit (CRO suggests 1.5× the backtest maximum).
**Why:**
- Trading: this ladder is the only way "measured costs" can ever be met. The F2 kill rule ("kill fast, no tuning", desk meeting §2) is the pattern to follow.
- Quant: "6 months forward, same sign" passes half of all signals that have no edge, because under no edge the sign is a coin flip. Use a test against the backtest's confidence band and a power target instead. Expect live results smaller than backtest (published anomalies lose about a third to a half; McLean & Pontiff 2016, from memory).
- Macro: event edges run on the results calendar, so 6 months may contain almost no events unless it spans two seasons.
- Data: forward paper trading is the only test that cannot leak future data.
**Vote:** 5–0 on the ladder's structure. On the exact demotion trigger, members' wording differs. Macro proposes "below half the backtest estimate, or a sign flip over two consecutive seasons". The chair has merged these into the list above.
**Confidence:** medium. The structure is solid; the numbers are judgement.
**Shivam decides:** (a) the pilot size; (b) the book's maximum drawdown limit (the 2026-09-25 desk set a simulated worst drawdown below 25%); (c) Shivam's explicit sign-off at each scaling step.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

## H. Operating model

### Q21. What stays frozen, and for how long?
**Verdict:** **Freeze** new tools, harnesses (other than the Q16 harness), routers, lenses, the mixture-of-experts temperature, event graphs, video transcription, new feeds, new councils and settings tinkering. The freeze lasts until the first promotion. It lifts *only* on a promotion, never because "the harness now exists". **Exempt:** a **closed, named list of truth-layer repairs with an hour budget**:
- corporate-action adjustment;
- the ISIN-history map;
- the 2021–22 corporate-action backfill;
- delisted names;
- results filing dates and XBRL figures;
- the NSE insider-trading feed;
- an NSE timestamp cross-check on 200 sample filings;
- spread proxies.

**2026-12-31 is a hard review date.**
**Why:**
- Quant: every new lens is a new set of untested hypotheses. It raises the test count without adding statistical power. Truth repairs, by contrast, raise the power of *every* test.
- Macro, Data: without the carve-out, the freeze blocks the top hypothesis on a technicality.
- CRO: an open-ended carve-out is how threads multiply, so it must be a closed list with an hour budget. Index-membership history is pre-approved as the first new feed after the freeze (Macro).
**Vote:** 5–0 on the freeze and the carve-out. **3–2 on what 2026-12-31 means.** CRO: missing promotion by then triggers a *stop or rescope* decision. Trading and Macro: it is a **process review** ("is a frozen card running forward on adjusted data, and are the harness and ledger live?"). Their reason is that only one results season falls before that date, so a promotion is impossible in time and the rule would be a guaranteed kill. They put the real promote-or-kill date after the second forward season: about **2027-03-31** (Trading) or **2027-06-30** (Macro). Quant accepted the date without saying which meaning; Data did not address it. **Chair's recommendation:** treat 2026-12-31 as a pass/fail *process* review, and set the project-level kill-or-rescope decision for 2027-03-31, shortly after the Jan–Feb 2027 season closes.
**Confidence:** medium.
**Shivam decides:** (a) the meaning of 2026-12-31; (b) the kill-or-rescope date (see Q23); (c) the hour budget for the truth-repair list.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

### Q22. Authority and handoff
**Verdict:** Yes. `tasks/FRAMEWORK.md` becomes the single authority and replaces `CURRENT_PLAN_2026-09-27.md`. The full file set is:
- `FRAMEWORK.md`: the rules, changed rarely.
- One-page **`STATE.md`**: overwritten each session, including a "data state" table (what is verified, the current snapshot ID, open data defects).
- **Append-only test ledger.**
- **Hypothesis registry.**
- **Paper-book log**, added once forward trading starts.

Sessions hand off by overwriting STATE and appending to the ledger, not by writing new closeout files. Older plans and closeouts move to `tasks/archive/`, and git keeps the history.
**Why:**
- CRO: each closeout says "read me first" and supersedes the last one. That is drift, not handoff.
- Data: stale claims survive in closeouts. The 2026-09-29 audit says `prev_close` adjusts for splits, which was false as of today. One maintained table fixes that.
- Macro: the tracker still lists momentum-vs-reversal as "NEXT", which contradicts other files.
- Quant: the ledger *is* the handoff (what was tried, on which snapshot, with what result).
**Vote:** 5–0.
**Confidence:** high.
**Shivam decides:** nothing. Confirm or reject.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

---

### Q23+. Missing questions raised by the council

#### Q23. Project kill switch and opportunity cost
**Council recommendation:** Write down now when the project stops if nothing is promoted, and what happens then. The default answer is "Shivam's money sits in an index fund", which also means waiting costs little. CRO wanted the stop at 2026-12-31. Trading proposed about 2027-03-31 and Macro about 2027-06-30, both after the second forward season. All agree that "beat the index after costs" is the bar, and that a missed date means *stop or rescope*, never "reset the clock and build more".
**Shivam decides:** the kill-or-rescope date, and what "rescope" would be allowed to mean.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

#### Q24. `AGENTS.md` conflicts with the freeze
**Council recommendation:** `AGENTS.md` tells every new session that the mission is an all-peers ensemble, MoE temperature, event graphs and continuous self-correction, which steers agents back toward the frozen architecture. Its rule that "ISINs are immutable" is also false for Indian equities (a face-value split issues a new ISIN). Add a few lines at the top saying that `tasks/FRAMEWORK.md` overrides it, and correct the ISIN rule (CRO, Data, Macro). Not edited by the council.
**Shivam decides:** approve the `AGENTS.md` header change.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

#### Q25. Independent re-runs before numbers enter a tracker
**Council recommendation:** No number enters a tracker, STATE or FRAMEWORK unless a script re-run on a pinned snapshot reproduces it, and the ledger row names the script, commit and snapshot (CRO, with Quant and Data agreeing). The background is agent-reported numbers and citations that turned out to be wrong. Five citations in the diffusion report are still unchecked.
**Shivam decides:** nothing. Confirm or reject.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

#### Q26. Bury or card the old threads
**Council recommendation:** Formally close each of these with one line in the ledger, or turn it into a card:
- the T4 "+790 bps" SELL re-test;
- F3 regime-carry;
- the T6 open BUYs;
- the video backlog;
- the 100-hour guidance study;
- the tariff card, whose run-1 results were never written up.

Otherwise they come back (CRO). Macro asks that guidance raises be **kept as a queued card, not buried**, because LLM reading of concalls on thinly covered names is the desk's most distinctive possible edge. The tariff results should be written up as a calibration of the supply-chain idea.
**Shivam decides:** for each thread, bury or card.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

#### Q27. Concentration limits, even on paper
**Council recommendation:** Results events cluster in about 6–8 heavy weeks per season, so 30 "independent" trades can really be one bet on one week. Set a maximum exposure per results week and per stock for the paper book, and count date clusters, not trades (CRO, Quant).
**Shivam decides:** the per-week exposure cap.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

#### Q28. The capital Shivam would actually deploy
**Council recommendation:** The ₹10 cr in the 2026-09-25 desk meeting looks like a hypothetical "Oct-2021 lump sum". Nobody has asked Shivam for the real figure. It sets the liquidity floor (Q3), the capacity curve's main point, and the pilot size (Q20). Trading, CRO and Macro all asked for it.
**Shivam decides:** the realistic deployable capital, and the pilot amount (Trading suggested ₹10–20 lakh).
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

#### Q29. Tax status of a frequent-trading book
**Council recommendation:** A high-turnover event book may be taxed as business income at slab rates rather than as capital gains (Trading, from memory). This depends on the facts. Ask a chartered accountant before go-live, not now. Do not let tax modelling become a build project (CRO).
**Shivam decides:** whether and when to consult a CA.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

#### Q30. Limits of this council
**Council recommendation:** The five members are the same underlying model playing roles, so their agreement is weak evidence, much weaker than five independent people agreeing. Cap the debate at these two rounds, with no further councils during the freeze. Shivam's marks are the only authority (CRO, all agreeing).
**Shivam decides:** nothing. Confirm or reject.
**Shivam's call:** ☐ OK  ☐ LOOK MORE  ☐ DIDN'T UNDERSTAND — notes:

---

## Proposed order of work (if the verdicts are accepted)

1. **This week:** Shivam marks the verdicts, gives the capital figure, and freezes **Card A** (the pre-results overlay and late-filer forward card) by git commit before the Q2 FY27 season starts.
2. Write `FRAMEWORK.md`, `STATE.md`, the test ledger and the hypothesis registry. Add the override header to `AGENTS.md`. Archive the old plans and closeouts. Record buried and carded threads.
3. Truth repairs from the closed list: corporate-action adjustment plus the ISIN-history map, then the 2021–22 action backfill and delisted names, then mapping results filing dates. Cut the first dated, checksummed snapshot.
4. Build the thin harness: truth-checked loader, known-answer tests, invariants, costed long-only simulation, ledger hook.
5. Re-run the results-day puzzle (study §7/§8) and Macro's D1 check on adjusted data, as ledger entries. Re-label every diffusion number accordingly.
6. Load the XBRL results figures and freeze **Card B** (earnings-surprise conditioning) with its break-even and kill bar stated. Run it.
7. Paper book runs forward through Oct–Nov 2026 and Jan–Feb 2027. Process review on 2026-12-31; kill-or-rescope decision on the date Shivam sets.
8. Only after that: the NSE insider feed and promoter-buying card, then guidance raises, then forced-flow feeds.

## Council caveats

- **Not independent.** All five members and the chair are the same underlying model. Unanimous votes here are much weaker evidence than five independent experts agreeing. Treat 5–0 as "no obvious objection found", not as proof.
- **Verified by read-only DB checks (Data only, 2026-10-06):**
  - unadjusted prices on ex-dates (BLUESTARCO −48.2%, VBL −48.8%, IONEXCHANG −90.5%, GULPOLY −11.9%);
  - ISIN restamping (289 of 386 split/bonus actions not joining);
  - `corporate_actions` starting 2023-01-02;
  - `v_document_pit` counts (71,937 BSE-dated, 31,215 unknown);
  - no filing-date column in `quarterly_financials`, and no membership, sector-history, delisting, band, ASM/GSM or F&O history tables;
  - `substrate_quarantine` counts;
  - 574 of 5,710 ISINs ending before 2026-06;
  - the live DB modified at 12:40 today;
  - BSE upload-to-publish lag (median 1 s, 99th percentile 61 s, 139,802 results filings; 6,311 after 21:00), from `analysis/bse_announcements.db`;
  - the `insider_trades` table having 0 rows, and SAST headlines carrying no direction.

  No other member queried the DB. The chair re-checked none of these.
- **Stated from memory and unchecked:**
  - tax and regulatory figures: STCG 20%, LTCG 12.5% above ₹1.25 lakh, STT 0.1% per side, stamp duty about 0.015%, F&O coverage of about 180–220 names, lot sizes of about ₹15–20 lakh, SEBI's 2024–25 F&O and retail curbs, the SEBI retail-algo rules, and the business-income tax risk;
  - literature: DeMiguel et al. 2009, McLean & Pontiff 2016, and the "managers delay bad news" literature.

  Check all of these against primary sources before they go into `FRAMEWORK.md`.
- **Judgement, not measurement:** the cost tiers (20/40/80/150 bp), the 60–110 bp and 100–200 bp round-trip estimates, the ₹2 cr/₹5 cr floors, the 5% participation cap, Quant's power arithmetic (2 seasons detect about 100 bp, 50 bp needs 4–6), Data's "days" and "weeks" repair estimates, and Macro's 65/35 selection-vs-behaviour lean.
- **Diffusion-study figures** (−85 bp, t −8.1, the yearly drift path, 55–75 bp, 19,216 event-days) come from project files as cited by members. All are provisional on unadjusted, survivor-only prices. Other task-file citations (strategy tracker, desk meetings, PIT audit) were taken from members' summaries, not re-read by the chair.
