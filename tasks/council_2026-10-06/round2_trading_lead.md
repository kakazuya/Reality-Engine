# Council round 2: Trading & Execution Lead (2026-10-06)

Read: all five round-1 files. Tax and regulatory figures are still from memory and need checking against primary sources.

## 1. Direct answers to questions put to me

**Quant Lead: what is a realistic round trip for a 2–20 day hold in a ₹1 cr/day stock?**
- Statutory and fixed costs come to about 25–35 bp: STT 10 bp each side, plus stamp duty, exchange fees and GST.
- On top of that come the spread and impact. In a ₹1 cr/day name I would guess 30–80 bp for a small order. That is an unmeasured judgement.
- So the total is **about 60–110 bp**. It is above your 60 bp line, so the long half of the drift (55–75 bp gross) is gone before tax.
- Capacity is the bigger problem. A ₹50 lakh position, which is ₹10 cr spread over 20 names, would be 50% of a day's trading in that stock. A ₹1 cr/day name is not tradable at ₹10 cr scale at all.

**CRO: what does a 1–2 day trade cost in a ₹50 lakh/day stock? And can "exit before results" make money once the days you are out are counted?**
- For a ₹50 lakh/day name the round trip is likely 100–200 bp for any order bigger than a few lakh. Event trades there are research only.
- On exit-before-results: **no, not as a standalone trade.** Selling and buying back costs about 80 bp or more. The average loss you avoid is about 50–85 bp, before the Data Steward's adjustment fixes. Selling also triggers capital-gains tax on that holding, and for a position held under 12 months it restarts the 12-month clock for the lower long-term rate.
- It only adds value as a **free timing rule on trades already planned**: delay a planned buy until after results, and move a planned sell to before them. That costs nothing extra. So it should be scored as "timing benefit on planned trades", never as a strategy P&L.

**Data Steward: are the cost and capacity numbers built on unadjusted prices?**
- Liquidity is measured as traded **value** in rupees (price × quantity). A split does not change that, so the turnover floors are safe.
- Two things do break: any price-level filter, and the high/low spread estimators on split, bonus and dividend ex-dates. Exclude ex-dates from spread estimation, and compute returns only on the adjusted panel you proposed.
- Every drift number I costed in round 1 is provisional until that adjustment is done.

**Macro PM: how many results events per quarter are tradable at a ₹2 cr floor for a ₹10 cr book?**
- I cannot give a number without querying the data, so I will not make one up.
- What I know: 19,216 Financial Results event-days passed the ₹50 lakh floor over about 19 quarters, roughly 1,000 per quarter.
- The count at ₹2 cr and ₹5 cr floors is a cheap query on the snapshot. **It should be on the first hypothesis card before any returns are looked at**, as the capacity denominator.

**Macro PM: is a 55–75 bp gross drift positive after costs and tax?**
- No. After about 80 bp of costs it is roughly zero or negative.
- Then 20% STCG (short-term capital gains tax) applies to the winners. Losses only offset gains, so a near-zero gross edge turns into a net negative.

## 2. Where I change position

- **Q14, first hypothesis:** from "results-day timing overlay first" to **"earnings-surprise conditioning first, with the time-of-day gradient as its first diagnostic"** (Macro PM's framing). Why: the Data Steward showed the −85 bp gap may contain fake bonus-day crashes and late timestamps, and the gradient may just stand in for bad news. The overlay does survive as CRO's version: a frozen card, tracked **forward only**, scored as timing benefit. It costs nothing to paper-track.
- **Q3, participation cap:** from 10% to **5% of a day's traded value** for event entries. Event trades must fill within about a day, and 10% is a patient-execution ceiling. I also accept CRO's point: **score at the capital Shivam would actually deploy, and report ₹10 cr as a point on the capacity curve, not as the default.**
- **Q5, hit-rate rule:** I agree with Quant and CRO: **drop it as a gate** and keep it as a diagnostic. Skewed event payoffs make it misleading.
- **Q20, paper period:** from "2 seasons / 6 months" to **2 results seasons and 30 or more independent events before a small real pilot, and 12 months forward before scaling past 25% of capital.** This combines Quant's 12 months with Macro PM's seasons.
- **Q2, books:** I partly concede to CRO. **Run only one active book (event) now.** The fundamental book is not built or staffed until point-in-time fundamentals exist. But its scoreboard is reserved, and the two horizons are never scored together.

## 3. Where I still disagree

- **CRO, 2026-12-31 kill switch.** Keep the date as a **process review**: is a card frozen, is the harness live, has paper trading started? Do not make it the kill decision. My strongest argument: the only clean holdout is forward time, and results events come in seasons. Between now and 31 Dec there is exactly one season (Q2 FY27 results, mid-Oct to mid-Nov) and too few independent events to judge anything. A kill rule that cannot be passed in its window just becomes a rule to beat the benchmark by luck. **Put the kill-or-rescope decision after the second forward season (about 2027-03-31).** If nothing is promoted by then, the index is the answer. I fully agree that "beat the index after costs" is the bar the project must clear.
- **CRO, 1–2% participation.** That is right for the *stress* case. As the base case it shrinks the universe to the top few hundred names and hides the capacity curve. Use 5% as the base, test 2% as a stress, and report both.
- **Macro PM, ₹2 cr floor; Quant, ₹1 cr floor.** Fine for research tiers, but **the floor must scale with the capital assumed.** At ₹50 lakh per position and a 5% cap, the trading floor is about ₹10 cr/day for one-day fills, or about ₹5 cr/day if entry may take 2 days. My one rule: floor = position size ÷ (cap × days allowed to fill). The card states it, and the number follows from it.
- **Quant and Macro PM, ranking post-results drift (PEAD) highly.** I agree it goes first as *research*. But the card must state the **break-even cost before the run**. The long-only, surprise-conditioned edge must clear at least 2 times about 80 bp, so roughly 160 bp gross over the holding period, at the tested liquidity tier. Otherwise a "significant" result just repeats today's position: real, but not tradable.

## 4. Final stance, Q1–Q22

- **Q1:** Add "at a stated size, with a real entry time, within a drawdown limit, beating the index after costs" to "repeatable, has a reason, survives costs".
- **Q2:** One active event book now. The fundamental book is reserved and waits for point-in-time fundamentals. Never one blended score.
- **Q3:** A universe set by traded value as of each date. Floor = position ÷ (5% × days to fill). Score at realistic capital, with ₹10 cr shown on a capacity curve.
- **Q4:** Long-only. Avoid lists scored as underweights or timing benefit. F&O short cell only after a promotion.
- **Q5:** A bar per horizon: annualised net information ratio, gross edge at least 2 times cost, a capacity test, a maximum drawdown, and stability by year. No hit-rate gate.
- **Q6:** Matched peers for research. The investable index, after costs, for the book.
- **Q7:** A fixed, pessimistic cost stack tiered by liquidity, with a 2x stress test. Pre-tax for promotion, post-tax for go-live. Fix the "measured costs" wording.
- **Q8:** Log every variant, including cost, fill-price and entry-timing choices, in the test ledger.
- **Q9:** Data Steward's six checks, plus mine: a tradable price at entry (no band-hit or suspension, not on the ASM/GSM surveillance lists).
- **Q10:** Frozen snapshots for research. Keep the daily price update running for paper trading. Pausing the annual-report drain is Shivam's call.
- **Q11:** Yes. On the trading side, first: dissemination time, traded value, surveillance and F&O eligibility history.
- **Q12:** Set aside. Nothing undated may gate or vote in a paper trade.
- **Q13:** The card carries execution fields: entry and exit rule, the floor formula, the participation cap, the instrument, the cost tier, the break-even cost, the capacity denominator, and the expected long/short-term tax mix.
- **Q14:** Earnings-surprise conditioning first, with the time-of-day gradient as its diagnostic. A forward-only timing overlay card in parallel. Then promoter buying, then guidance.
- **Q15:** History is all seen. Confirmation is forward only, using the frozen cost tier and entry rule.
- **Q16:** Build on the diffusion code. A portfolio simulation with costs, no-fill on band-hit days, delisting exits and a capacity curve is mandatory, plus CRO's known-answer tests.
- **Q17:** All history is in-sample. Report every year. The holdout is forward time.
- **Q18:** Equal weight, netting overlapping trades across signals, until at least 3 promoted, low-correlation signals each have a forward record.
- **Q19:** The LLM does extraction and suggests ideas only. Orders come from a deterministic rule that can be replayed.
- **Q20:** 2 seasons and 30 or more events, then a pilot at 1–5% of capital to measure fills, then scale in steps after 12 months. Demotion is automatic and set in advance: net below zero, costs above 2x the model, or a drawdown breach.
- **Q21:** Freeze, with truth-layer repairs exempt. Process review on 2026-12-31. Kill-or-rescope after the second forward season (about 2027-03-31).
- **Q22:** One `FRAMEWORK.md`, plus a one-page STATE file, an append-only test ledger and the paper-book log.
