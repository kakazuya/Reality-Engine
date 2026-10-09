# Round 1 — Macro & Behavioural PM (independent position)

Lens: where edge in Indian equities comes from. For every idea I ask: **who is on the other side of the trade, and why are they slow or forced?** If nobody can answer that, the pattern is probably luck or a data artefact.

Evidence base used: `tasks/PRICE_SIDE_DIFFUSION_STUDY_2026-10-03.md` (§3, §7, §8), `tasks/PIT_LABEL_AUDIT_2026-09-29.md`, `tasks/FACTOR_SPINE_DESIGN_2026-09-29.md` §0, `tasks/strategy_tracker.md`, `tasks/desk_macro_psych_2026-09-25.md`, `tasks/tariff_event_card_2026-09-29.md`, `tasks/SESSION_CLOSEOUT_2026-10-05.md`, `FUNDAMENTAL_REALITY_ENGINE_OBJECTIVES.md`.

---

## A. North star and scope

### Q1
**Position:** Right, but add a fourth test: **"we can name who loses to us and why they keep losing."** Also add drawdown and capacity to the scoreboard.
**Why:**
- "Has a reason" is too loose. Any story can be written after the fact. "The other side is slow or forced" can be checked: index funds must buy on inclusion, ASM-listed stocks force margin calls, retail under-reads late-evening filings.
- Edges with no named loser decay fastest. The project's own results-drift estimate already shows decay by year: +96 bp (2023), +22/+24 (2022/2024), −11 (2025), −41 (2026) (`SESSION_CLOSEOUT_2026-10-05.md` §3).
- A drawdown limit belongs in the north star, not only in sizing. The desk's 40% cash/gold buffer (`desk_macro_psych` header) already shows the user thinks this way.
**Confidence:** high

### Q2
**Position:** Two separate books with separate scoreboards. The event-driven book (days to weeks) starts **now**. The multi-month fundamental book waits until fundamentals have real point-in-time dates.
**Why:**
- The only data that is truly point-in-time today is prices plus the BSE announcement feed with exact IST timestamps. Quarterly and annual fundamentals have **no filing date**, and quarters are missing (no 2023 at all) (`PIT_LABEL_AUDIT` table). Any multi-month fundamental backtest run today has look-ahead (it uses data the market did not have yet).
- The diffusion study puts attention half-life at about 1 day and drift over days 2–20. That is event-book territory.
- The two books have different costs, turnover, tax treatment (short- vs long-term capital gains) and failure modes. Combining them hides which one is working.
**Confidence:** high

### Q3
**Position:** Use a liquidity-floor universe, not "Nifty 200". Primary floor: about ₹2 cr median daily turnover. Run the existing ₹50 lakh floor as a sensitivity check. Keep ₹10 cr as the assumed capital.
**Why:**
- The edge mechanisms (thin analyst coverage, retail-heavy shareholder registers, slow reading of filings) are strongest **below** the Nifty 200. Cutting the universe to large caps removes the place where diffusion is slowest.
- Rough arithmetic (my own estimate, not fitted): ₹10 cr across 20 names is ₹50 lakh per position. To stay under about 10% of a day's volume over 2–3 days, a stock needs roughly ₹2 cr or more of daily turnover.
- "Nifty 200" today means *today's* members, with no membership history (`PIT_LABEL_AUDIT`: survivorship). A turnover floor computed as of each date avoids that bias.
**Confidence:** med

### Q4
**Position:** Long-only. Run "avoid lists" as their own scored cohort: the avoid basket's return minus the benchmark is reported, even though it is never traded.
**Why:**
- In the cash market you cannot short overnight. Stock lending (SLB) is thin, and F&O covers only about 180–220 large names. Most negative-information edges sit in names you cannot short.
- Negative information is still valuable. The strongest finding so far is negative: late-evening results filings show −53 to −84 bp relative to matched controls (`DIFFUSION_STUDY` §8). Scoring the avoid list keeps that knowledge honest without pretending we can short it.
- Optional later step: hedge market beta with Nifty futures. That is a risk overlay, not alpha.
**Confidence:** high

## B. Scoreboard

### Q5
**Position:** The bar is directionally right but is written in the wrong units. "+500 bps" with no horizon is meaningless for a 20-day event trade. Restate it **per book** as an annualised net information ratio (excess return divided by tracking error) plus a maximum-drawdown cap. Add a **per-year stability** test.
**Why:**
- Results drift is about 55–75 bp per trade (`DIFFUSION_STUDY` §3). It can never clear "+500 bps" per trade, yet it could still be a good book if repeated many times a year. On the other side, a 12-month fundamental trade clears +500 bps through market beta alone.
- "2 regimes same sign" is too weak with 5 years of data. The drift *changed sign* in 2025–26. I would require no more than one losing year out of five, and the most recent year must not be the worst.
**Confidence:** med

### Q6
**Position:** For research, use **matched peers** (same liquidity/size bucket, same day). For the decision book, use a **broad index** (Nifty 500 total return). Add a factor model (market, size, value, momentum) as a robustness check once the factor spine exists.
**Why:**
- The diffusion study showed that an equal-weight market proxy created spurious ±8 bp/day drifts between large and small caps. Liquidity-bucket matching fixed this (`DIFFUSION_STUDY` §2.1).
- The book's investor ultimately compares against an index fund, so the scoreboard should too.
**Confidence:** med

### Q7
**Position:** Use a fixed, deliberately pessimistic cost stack until real fills exist. Score **post-tax** in the decision book and pre-tax in research.
**Why:** A short-hold event book pays short-term capital gains tax (20% after the July 2024 change — from memory, unchecked) plus securities transaction tax (STT). The tax gap between a 15-day book and a 13-month book can decide which book is worth running. Mostly the Trading Lead's question.
**Confidence:** med

### Q8
**Position:** Keep a single append-only registry that counts **every** test, including abandoned ones. Use false-discovery-rate control (a method that limits the share of false positives among the "passes") across the registry. Use forward paper trading as the true holdout.
**Why:**
- All 2021–2026 history has already been looked at by the diffusion study. No historical period is truly "sealed" anymore. Only the future is clean.
- Detailed design is the Quant Lead's call.
**Confidence:** med

## C. Truth layer

### Q9
**Position:** These must pass before trusting a test: (1) point-in-time event timestamps — done for announcements; (2) **filing dates for fundamentals — not done, and this is the biggest gap**; (3) delisted/renamed names — not done (only 59.5% of announcements map to a priced stock); (4) quarantine — done; (5) corporate-action adjustment — partly done (`prev_close` only; corporate_actions starts 2023).
**Why:**
- From my lens, (2) blocks the strongest hypothesis (earnings surprise). (3) biases every result toward survivors, and failed companies are exactly the ones that file late and badly.
- Sector is unusable for 92% of the master list (`FACTOR_SPINE` §0). Any sector-relative or supply-chain claim is blocked until that is fixed.
**Confidence:** high

### Q10
**Position:** Do research on **dated read-only snapshots** and let ingestion continue. Do not freeze ingestion.
**Why:** The drains are adding the annual-report text that later hypotheses need. Freezing them costs data. Snapshots cost only disk space. Data Steward's call.
**Confidence:** med

## D. Signal layer

### Q11
**Position:** Yes. "Readable as of date t" is the right requirement. Priority order: (1) quarterly results with exchange filing timestamp, (2) insider/promoter (PIT and SAST) disclosures with timestamp, (3) index membership history, (4) sector/industry history, (5) LLM-extracted concall features (guidance direction), stamped with the transcript's publication time.
**Why:** This order follows the hypothesis ranking in Q14. Each item unblocks a named test. Moat, ENI and ripple features come last because no hypothesis needs them yet.
**Confidence:** high

### Q12
**Position:** Set them aside as decision inputs. Keep the tables and the vision. Revive each one only through a hypothesis card that tests it.
**Why:**
- They cannot vote. Moat has 2 dates of history, policy has 1, and ripple `transmission_elasticity` is a constant 1.0 on 61/61 rows (`FACTOR_SPINE` §0; `PIT_LABEL_AUDIT`). `model_explainer_rankings` has `regime_tag='*'` on 100% of rows. The weights parked on these mute lenses (supply 0.358 + quality 0.271 = 63%) were noise (`desk_macro_psych` §0).
- I defend the *ideas* — business quality and supply-chain transmission are real economics. But today's numbers are LLM-generated snapshots dated Aug–Sep 2026. Treating them as signals is look-ahead.
- Best revival route: the tariff event card. It is a cheap, honest test of whether exposure-based reasoning predicts ordering of reactions at all.
**Confidence:** high

## E. Hypothesis registry

### Q13
**Position:** The card must contain: mechanism; **who is on the other side and why they are slow or forced**; why it has not been arbitraged away, and the expected decay; signal definition and its point-in-time source; universe and liquidity floor; horizon; benchmark; primary test and pass bar; placebo and negative controls; minimum sample size; kill criteria; and an attempt ledger. The CRO freezes the card. Any change after seeing returns creates a new run that counts against the test budget.
**Why:**
- `tasks/tariff_event_card_2026-09-29.md` is already the right template. It was frozen before any returns were computed, has one primary hypothesis, a placebo, and an attempt ledger. Its weakness: the results were never written up in a task file (they exist only in script output). The card needs an "outcome" section.
- The "other side" field is my main addition. It is the cheapest filter against stories invented after the fact.
**Confidence:** high

### Q14 — First hypotheses (my priority question)

**Ranking rule.** Score 1–3 on each of: **Mechanism** (named, slow or forced counterparty), **Data readiness** (point-in-time today), **Power** (number of independent events), **Long-only tradability**. Rank by the product. Break ties by cheapness. A hypothesis with Data = 1 cannot go first, however good the story.

| Rank | Hypothesis | Mech | Data | Power | Trade | Note |
|---|---|---|---|---|---|---|
| 1 | **Earnings-surprise-conditioned post-results drift** (PEAD: prices keep drifting in the direction of an earnings surprise) | 3 | 2 | 3 | 2 | The flagship. Counterparty: retail and thinly covered mid-cap holders who under-read the numbers. Literature: Bernard & Thomas 1989, verified in project. Data fix needed: the results filing timestamp is **already in the BSE feed**. Only the surprise *value* is missing. Pull YoY revenue/PAT from BSE results XBRL keyed to the announcement. Count this as a truth-layer repair, not a new feed. |
| 2 | **Filing-time / "late filer" signal** (the negative reaction to results) | 2 | 3 | 3 | 2 (as avoid / underweight) | Ready **today**. The gap runs from about −15 bp for filings before 13:00 to −84 bp after 21:00 (`DIFFUSION_STUDY` §8). Mechanism: managers delay bad news (classic accounting literature, from memory, unchecked). Run it **as the first diagnostic inside #1**: if the time-of-day gradient disappears once surprise is controlled for, it is a proxy for surprise, not a separate edge. Either outcome is informative. |
| 3 | **Promoter open-market buying** (insider-trading and SAST takeover-code disclosures) | 3 | 2 | 2 | 3 | Strongest counterparty logic in India: promoters own about half of a typical company and know it best, and buying with their own cash is a costly signal. These disclosures probably sit inside the 1.94M-row BSE feed with timestamps. To confirm: whether direction and size can be parsed. Long-only by nature. It was already flagged "cheap — promote early" (`strategy_tracker` P6). |
| 4 | **Guidance raises in concalls** (the 100-hour study) | 3 | 1→2 | 2 | 3 | Good mechanism (analysts anchor on the old guidance). But concalls arrive within days of results, so this is **heavily confounded with #1**. Only valid as an *incremental* test: does guidance add anything after earnings surprise is controlled for? Needs LLM extraction plus pairs of comparable prior calls. Concall dates were repaired (7,019 rows), but extraction does not exist yet. |
| 5 | **Forced-flow events**: index inclusion/exclusion, ASM/GSM surveillance moves, F&O ban, pledge invocation, OFS/QIP supply | 3 | 1 | 2 | 2 | The purest "forced counterparty" class. Index funds and margin calls must trade regardless of price. The blocker is data: there is no index-membership history, and surveillance-list history must be collected. Put this first in the line for **new feeds after the freeze**. |
| 6 | **Macro/tariff transmission** (the tariff card, budget capex) | 2 | 2 | 1 | 2 | Five to seven events is too few to build a book. Use it as **calibration** for the supply-chain lens (does exposure predict the *ordering* of reactions?), not as a signal. Write up the run-1 results first. |
| 7 | VIX-fear displacement (B2), FII/DII regime conditioning (M3) | 2 | 1 | 1 | 2 | These are conditioning layers on an edge that already works. Out of order until something is promoted. FII-majority rows are only 1.8%. |

**Bottom line:** start with **#1 with #2 run as its first diagnostic**, which is one study. Run #3 in parallel only if the feed parse is cheap (about a day). Move #4 to second place once #1 gives a surprise control to test against. One warning to put on #1's card now: the year-by-year drift trend is decaying, so the expected-decay field must cover the possibility that 2025–26 is the new normal (crowding, or faster retail access to filings through apps).
**Confidence:** med on the order of #1–#3, high that #4 must not go before #1.

### Q15
**Position:** Allow unlimited exploration, but it is labelled "exploratory", cannot promote anything, and every look is logged. Confirmation happens only on a frozen card, scored on forward paper trading plus a pre-declared historical split.
**Why:** Exploration is how the late-filer pattern was found (§8 was exploratory). That is fine, as long as the pattern becomes a card before it becomes a claim.
**Confidence:** med

## F. Evaluation engine

### Q16
**Position:** Yes. Build the shared harness from the diffusion-study code. It already has the hard parts: point-in-time event timing, matched benchmark, clustered errors, false-discovery control, negative controls. Add a cost-aware long-only portfolio backtest and a cross-sectional test. Quant Lead's detail.
**Why:** It is the only code in the repo that has produced a result that survived its own controls (drift statistic: 0 of 20 control strata rejected).
**Confidence:** med

### Q17
**Position:** The data runs only from 2021-10 to 2026-09, so the honest holdout is **forward**. Historically, use 2021-10 → 2024-12 as in-sample and 2025-01 → 2026-09 as a pre-declared out-of-sample period, accepting that it has already been seen.
**Why:**
- The window covers several distinct regimes: the 2022 rate-hike drawdown, the 2023–24 retail and small-cap boom, record FII selling from late 2024 to early 2025, and the 2025 tariff shock. Those are enough *regimes* but few *cycles*. No full credit cycle is included.
- Drift sign changed in 2025–26. That is exactly why the recent period must be tested separately and not pooled.
**Confidence:** med

## G. Decision and learning layers

### Q18
**Position:** Build the ensemble only after **3 promoted signals from at least 2 different lens families** with low correlation to each other. Until then, use equal weight or inverse-volatility weight. Mixture-of-experts gating and temperature come only after a year of forward records shows that weights *should* vary by regime.
**Why:**
- The all-peers vision is right in principle. Edges are conditional, and who drives the price matters. But an ensemble of unvalidated lenses just averages noise. The project already learned this: calibration folds refused every run ("no out-of-sample improvement", `strategy_tracker` T8).
- The vision is kept, just sequenced. The registry *is* the peer competition, run honestly.
**Confidence:** high

### Q19
**Position:** Use the LLM for **extraction** (documents → dated, audited features) and for **hypothesis generation**. Never for decisions. Every extracted feature needs a hand-checked accuracy sample before use.
**Why:**
- This is where the original vision has its strongest real edge. A one-person desk cannot read about 100k filings and concalls; the LLM can. In India, mid- and small-caps have thin analyst coverage, so a feature like "guidance direction, as of the transcript's publication time" is information most market participants do not process quickly.
- Decisions made by the LLM cannot be backtested point-in-time, because the model has read the future (training data cutoff). Extraction can be audited against the source text.
- Warning: even extraction carries look-ahead if the model "knows" what happened later. Prompts must ask only for what the document says.
**Confidence:** high

### Q20
**Position:** Demote when, over a rolling 12 months forward, net performance falls below half the backtest estimate, or the sign flips over any two consecutive results seasons. Before real capital: at least 6 months of paper trading **and** at least 2 results seasons. Going live also needs measured slippage and the user's explicit sign-off.
**Why:** Event edges run on the results calendar. Six months without two results seasons can contain almost no events.
**Confidence:** med

## H. Operating model

### Q21
**Position:** Freeze until the first promotion **or** until 2026-12-31, whichever comes first, then review. Two carve-outs: **truth-layer repairs do not count as "new feeds"** (results XBRL with filing dates, insider-disclosure parse from the existing BSE feed, delisted names). Index-membership history is pre-approved as the first new feed after the freeze lifts.
**Why:** Without the carve-out, the freeze blocks the top-ranked hypothesis on a technicality. Event graphs, MoE temperature and new lenses stay frozen. I agree with that.
**Confidence:** med

### Q22
**Position:** Yes. `tasks/FRAMEWORK.md` should be the single authority file, plus one append-only `tasks/LOG.md` (dated entries of 10 lines or fewer) instead of new closeout files. The hypothesis registry should be its own file, because it changes on a different schedule.
**Why:** `CURRENT_PLAN`, many `SESSION_CLOSEOUT_*` files, the tracker and the desk docs already contradict each other in places. For example, the tracker still lists momentum-vs-reversal as "NEXT".
**Confidence:** high

---

## Questions I'd push other council members on

- **Quant Lead:** Can the results-drift estimate survive the year-by-year decay (+96 → −41 bp)? Should the bar weight recent years more? And is "surprise" best measured as YoY growth or as the price reaction itself, given there are no analyst-consensus data?
- **Data Steward:** How many days of work is BSE results XBRL with filing timestamps for 2021–2026? Do insider/SAST disclosures in `bse_announcements.db` carry direction and size, or only a PDF? How many delisted names can be recovered?
- **Trading & Execution Lead:** At a ₹2 cr turnover floor, how many results events per quarter are tradable for a ₹10 cr book? And is a 55–75 bp gross drift even positive after STT, impact and short-term capital gains tax?
- **CRO / Skeptic:** The late-filer gradient was found by exploration on the full history. What exactly would you accept as a confirmatory test, given no historical period is clean? And does the 2025–26 sign flip already kill #1 before we start?
