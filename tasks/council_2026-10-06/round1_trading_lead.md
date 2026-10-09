# Council round 1: Trading & Execution Lead (2026-10-06)

**Lens:** can it actually be traded in India, at what size, after what costs and taxes, entered when?

**Headline:** right now nothing the project has found survives costs. The price-side study's follow-on drift is **55–75 bp per side over days 2–20** (`tasks/PRICE_SIDE_DIFFUSION_STUDY_2026-10-03.md` §3). The project's own assumed round trip is about **80 bp before tax**: STT 10 bp per side, 5 bp per side of other charges, and a 50 bp impact prior (`desk_forensic_2026-09-25.md` §10, `desk_backtest_2026-09-25.md` §1.8). The negative side of that drift also needs a short, which a cash-equity book cannot hold overnight. So the framework should make "survives costs at a stated size, entered at a time you could really have traded" a gate from the first test onward, not a final check.

Tax and regulatory numbers below are from memory unless a project file is cited. **They must be checked against current primary sources before they go into `FRAMEWORK.md`.** The Union Budget of Feb 2026 and SEBI's F&O changes from 2024–25 may have moved some of them.

---

## A. North star and scope

### Q1
**Position:** The north star is right but incomplete. It should say "survives costs **at a stated capital size, with an entry time you could really have traded, and within a drawdown limit**".
**Why:**
- "Survives costs" is meaningless without a size. A 60 bp edge can be real at ₹25 lakh and gone at ₹10 cr because market impact (the price moving against you as you trade) grows with order size.
- The entry time has to be one you could have used: the next tradable price after the news was public, not the close before it (see Q7 and Q14).
- A drawdown cap belongs here. The 09-25 desk set a simulated worst drawdown below 25% (`desk_meeting_2026-09-25.md` §2). Keep it.
- Keep paper-only. Add one line: "paper results cannot measure slippage", so going live needs a small real-money pilot step (Q20).
**Confidence:** high

### Q2
**Position:** Run two separate books with separate scoreboards: an **event book** (holds of 1–20 trading days) and a **fundamental book** (holds of 3–12+ months). Research the event book first, but expect the fundamental book to be the one that is easier to trade.
**Why:**
- The event book has high turnover (how often the portfolio is replaced). With about 15-day holds you do roughly 15 round trips a year per slot. At about 80 bp each that is **about 12% a year of cost drag on the capital deployed**, before tax. The edge per trade has to beat that.
- Every winning event trade is a short-term gain: 20% STCG (short-term capital gains tax) after Finance (No.2) Act 2024 (`desk_forensic` §9.1). Holds over 12 months pay 12.5% LTCG (long-term capital gains tax) above ₹1.25 lakh. At the same gross alpha, that tax gap alone favours the long book.
- Frequent trading may also get the income treated as **business income at slab rates** instead of capital gains. This is from memory and depends on the facts, so ask a CA (chartered accountant).
- The two books need different benchmarks, bars and cost models, so one blended scoreboard would hide the cost problem.
**Confidence:** high

### Q3
**Position:** Use a liquidity-defined universe, not an index name. Require a **60-day median traded value of at least ₹5 cr a day** at the date of each trade, and cap each order at **10% of that day's expected traded value**. Score at ₹10 cr, and also report capacity: the largest size at which the edge stays positive.
**Why:**
- At ₹10 cr spread over 20 names, each position is ₹50 lakh. The diffusion study's floor is ₹50 lakh a day (`common.py` `LIQ_MIN_TURNOVER_LACS = 50`), which means one position would equal a whole day's trading in the thinnest names. That is research-grade, not tradable.
- At ₹5 cr a day and 10% participation, a ₹50 lakh order fills in one day. Below that floor, entry takes several days and the event edge drains away while you are still buying.
- Historical index membership has no history (the `is_nifty*` flags, closeout §5). A point-in-time liquidity rule avoids that survivorship trap. "Nifty 200" today is a list of survivors.
- Small caps carry extra friction: price bands of 5–20% (no fill on days the band is hit) and ASM/GSM surveillance lists (the exchanges' additional and graded surveillance measures, which bring higher margins and trade-for-trade settlement). Exclude names on those lists as of each date, and treat band-hit days as no-fill.
- Run small caps as a separate research cell with smaller sizes, not inside the main book.
**Confidence:** med (the ₹5 cr floor and 10% cap are my judgement; calibrate them once a spread proxy exists)

### Q4
**Position:** **Long-only**, with an "avoid / exit-before" list in place of shorts. Short legs are allowed only as a separate research cell restricted to F&O stocks (stocks with exchange-traded futures).
**Why:**
- Indian cash equities cannot be shorted overnight. SLB (securities lending and borrowing) exists, but liquidity is thin and patchy. Stock futures cover only about 180–220 names (from memory), have large minimum contract sizes after SEBI's 2024–25 changes (from memory, about ₹15–20 lakh), and carry rollover cost and basis risk (the gap between the futures and cash price).
- About half the measured drift (the negative side) is therefore unreachable for most of the universe.
- An avoid list is still valuable and cheap: it costs nothing extra when it changes **when** you trade something you were trading anyway (see Q14).
- Score SELL/avoid calls as "loss avoided against holding", as the 09-25 desk already decided (`desk_backtest` §1.3 item 11). Keep that.
**Confidence:** high

## B. Scoreboard (layer 0)

### Q5
**Position:** The bar is right in spirit but wrong in units. "+500 bp per trade" is far too hard for a 10-day hold and too easy for a 365-day hold. Make the bar depend on the horizon and add two execution tests.
**Why:**
- +500 bp net on a 10-day trade would be an extraordinary edge. On a 12-month hold it is modest. Express the bar as annualised net excess plus an **information ratio ≥ 0.5** (excess return divided by its volatility), measured on the book's actual turnover.
- Add a **cost break-even multiple ≥ 2**: the gross edge must be at least twice the assumed round-trip cost, so a cost model that is wrong by 2x still leaves the signal alive.
- Add a **capacity test**: still positive at the ₹10 cr sizing under the Q3 participation cap.
- Keep the 30 weekly cohorts, the two regimes with the same sign, and the placebo. Results events cluster in about 8 weeks a quarter, so "30 cohorts" for the event book should mean about 4 results seasons, not 30 calendar weeks.
- Add a maximum-drawdown limit for the book.
**Confidence:** med

### Q6
**Position:** The primary benchmark is **matched peers** (same liquidity bucket and size, same dates). Also report index-relative excess, because that is what money actually earns against.
**Why:**
- Matched peers isolate the signal. The study's bucket-matched benchmark already works (§2.1 and §7 of the study).
- The money question is whether it beats a Nifty or Midcap ETF held in the same capital slot, net of costs. A peer-relative edge that lives in micro-caps can still lose to the index after impact.
- Add factor-model alpha later, once the factor spine is validated. Do not make it the gate yet.
**Confidence:** med

### Q7
**Position:** Use a **fixed, tiered, assumed cost stack** now, with impact tiered by liquidity bucket (for example 20 / 40 / 80 / 150 bp round trip, labelled as assumptions) instead of a flat 50 bp. Score **pre-tax** to promote a signal and **post-tax** to judge a book. Replace the assumptions with fills from a small real pilot (Q20).
**Why:**
- Paper trading cannot produce measured slippage: no order ever hits the book. "Measured costs" in the current bar (`desk_meeting` §2) is therefore unreachable while capital is parked, and the bar is unpassable by construction. Fix that wording.
- Until real fills exist, estimate the bid-ask spread from daily high/low/close (Corwin–Schultz or Abdi–Ranaldo estimators) per stock and date, and add an impact term that grows with the square root of order size divided by traded value. All of this comes from data the project already holds.
- Statutory costs from memory, to verify: delivery STT 0.1% on each side (consistent with `desk_forensic` §9.2), stamp duty about 0.015% on buys, exchange and SEBI fees of a few basis points, and 18% GST on brokerage and exchange fees.
- Signal promotion should not depend on tax-lot timing. A book's verdict should be after tax, because the STCG versus LTCG gap is large.
**Confidence:** high on structure; low on the exact bp tiers

### Q8
**Position:** Outside my lens mostly. Count every variant tried, including **cost and entry-timing variants**: picking the "open versus close" fill after seeing results is snooping too.
**Confidence:** med

## C. Truth layer (layer 1)

### Q9
**Position:** Add three execution-truth checks to the data-truth list: (a) **a tradable price exists at the assumed entry time** (no band-hit, not suspended, not on the ASM/GSM lists); (b) **corporate-action-adjusted** open and close prices; (c) **delisted names included**, with an exit at the last traded price.
**Why:**
- The diffusion study's sample is "stocks present in the 2026 price table", so delistings are missing (study §4.4). Survivors make every long-only backtest look better than reality.
- The SWANDEF unadjusted jump already voided one result (`100-hour` study plan §15).
- I have not seen the band-hit, ASM/GSM or suspension history checked anywhere. Treat it as unverified.
**Confidence:** high

### Q10
**Position:** Research on **dated, frozen snapshots**, and let ingestion continue on the live DB.
**Why:**
- A paper-trading book needs fresh daily data, so freezing ingestion kills the forward test.
- Every paper decision should record the snapshot or as-of time it used, so the trade can be replayed.
**Confidence:** high

## D. Signal layer (layer 2)

### Q11
**Position:** Yes. From my side, the first things that must be readable "as of date t" are the **exchange dissemination timestamp**, the **liquidity bucket or traded value**, **surveillance and F&O eligibility**, and **index membership**, because they decide whether a trade could have happened at all.
**Confidence:** med

### Q12
**Position:** Set them aside. Nothing that cannot be dated may gate or vote in a paper trade.
**Why:** Levels with no dated history already produced the T1/T2 failures (`strategy_tracker.md`).
**Confidence:** med

## E. Hypothesis registry (layer 3)

### Q13
**Position:** Each card must include a block of execution fields alongside mechanism, signal, universe, horizon, bar and placebo:
**Why:**
- **Entry rule:** the first tradable price after public release (next open or next close, chosen in advance), and for after-15:30 filings that is never the same day's close.
- **Exit rule and holding period;** expected turnover a year.
- **Liquidity floor and participation cap; capacity at ₹10 cr.**
- **Instrument:** long cash only, or F&O short.
- **Cost tier assumed;** break-even cost; tax treatment (STCG or LTCG share of exits).
- Any change to these after seeing returns makes the run exploratory, as for any other field.
**Confidence:** high

### Q14
**Position:** First: **results-day timing as an overlay on trades you were going to make anyway**. Second: earnings-surprise conditioning. Ranking rule: **expected net edge per rupee of cost and per hour of work, at the ₹10 cr size, long-only.**
**Why:**
- The negative reaction is the strongest and steadiest effect found so far. It is −85 bp against matched non-announcers (t −8.1) and is negative in 2023–2026 every year (study §7). It is worst for releases after market hours: −53 bp for 15:30–18:00 up to −84 bp after 21:00 (study §8).
- As a standalone trade it does not survive: you would need a short, and the reaction to an after-hours release is mostly in the next open's gap, before anyone can act.
- As an overlay it costs nothing: **do not start new buys in the 5 sessions before a known board-meeting date, and put planned sells or trims before it.** The board-meeting date is announced in advance. The release time is not, so lean on how late the company has filed in past quarters.
- Before trusting any next-day number, check open-to-close against close-to-close for the event day, to see how much of the −85 bp happens in the overnight gap that nobody can trade.
- Post-results drift as a standalone strategy is weak: 55–75 bp per side against about 80 bp round trip, with yearly signs of +96, +22, +24, −11 and −41 bp (closeout §3). Kill it as a trade; keep it as a research question.
- Guidance raises from concalls (the 100-hour plan) fit the fundamental book's 90-day horizon and long-only rule. Good third choice.
**Confidence:** med

### Q15
**Position:** Mostly outside my lens. Exploration may use any cost model. Confirmation must use the cost tier and entry rule frozen on the card.
**Confidence:** med

## F. Evaluation engine (layer 4)

### Q16
**Position:** Yes, build the harness from the diffusion-study code. The portfolio backtest with costs is **mandatory**, not optional.
**Why:**
- The harness must cover: the event study; the cross-sectional test; a **portfolio simulation** with position limits, the participation cap, tiered costs, no-fill on band-hit days, delisting exits, an STCG/LTCG tax ledger, and cash drag; and a **capacity curve** (net return against capital, ₹25 lakh to ₹50 cr).
- Reuse the existing tax and FIFO code in `sip_backtest` (33 tests green per `desk_forensic` §9). Do not rebuild it.
- An event-study CAR (cumulative abnormal return) is not a P&L: overlapping positions, cash limits and costs can erase it.
**Confidence:** high

### Q17
**Position:** Outside my lens mostly. Require the span to include at least one **stress or high-volatility period**, because impact and spreads widen exactly then. Also note the price history only starts 2021-10-27 (`desk_backtest` §1), so there is no 2020 crash in sample.
**Confidence:** med

## G. Decision and learning layers (layers 5–6)

### Q18
**Position:** Use equal weight, capped by liquidity, until there are **at least 3 promoted, low-correlation signals with 6+ months of forward paper record each**.
**Why:** Signals that trade the same names share turnover. Combining them should first **net trades against each other** (signals agreeing on one name means one trade, not two), and that is a cost gain no MoE (mixture-of-experts gating) layer provides.
**Confidence:** med

### Q19
**Position:** Use the LLM for extraction and hypothesis generation only. **Never for order decisions.** Orders must come from a deterministic rule that can be replayed.
**Why:** You cannot audit slippage or replay a fill against a non-deterministic decision. Regulators and brokers also expect explainable rules if this ever becomes algorithmic trading (SEBI's retail algo framework; check the current rules).
**Confidence:** high

### Q20
**Position:** The go-live ladder:
1. **Paper forward** for at least 2 results seasons (about 6 months) or 30 independent event cohorts, whichever is longer. The paper fill is the next tradable price after the decision is time-stamped.
2. **Real pilot** at about 1–2% of target capital (₹10–20 lakh, Shivam's call). Its job is to **measure fills, not to make money**.
3. **Scale in steps** (10% → 25% → 50% → 100%) only while realised costs stay within 1.5x of the model and live net tracks paper within its confidence band.

Demote on any of: rolling net excess below zero over the last 2 seasons; realised costs above 2x the model; live versus paper tracking gap beyond the band; or a drawdown beyond the book limit.
**Why:**
- This ladder is the only way the "measured costs" requirement can ever be met.
- Demotion rules must be frozen at promotion, the same way F2's kill rule was (`desk_meeting` §2).
**Confidence:** high on structure; med on the exact numbers

## H. Operating model

### Q21
**Position:** Freeze new tools until the first promotion **or** until the harness with costs and capacity (Q16) exists, whichever comes first. The single exception is cost and liquidity data (spread proxies, surveillance and F&O eligibility history), which is part of the truth layer.
**Confidence:** med

### Q22
**Position:** Yes: one authority file, `FRAMEWORK.md`. Add a short **paper-book log** as the only other living file once forward trading starts.
**Confidence:** med

---

## Questions I'd push other council members on

- **Quant Lead:** If per-trade bars become horizon-specific (Q5), what replaces "≥30 weekly cohorts" when results events cluster in about 4 seasons a year? How many seasons buy real power?
- **Data Steward:** Do we hold the **open** price, price-band and suspension flags, ASM/GSM history and F&O eligibility history by date? Without them no entry rule or short leg can be validated. And can delisted names be added back?
- **CRO / Independent Skeptic:** Will you accept a cost model built from high/low spread estimators until pilot fills exist? Or do you insist "measured" means real fills, which means the bar cannot be met while capital is parked?
- **Macro & Behavioural PM:** Is the after-hours negative reaction "bad news filed late" (a selection effect) or "sell the news" (a behaviour effect)? Only the second survives earnings-surprise conditioning as a timing overlay worth keeping.
