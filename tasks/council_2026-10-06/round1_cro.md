# Round 1 — CRO / Independent Skeptic (2026-10-06)

**Lens:** risk, governance, self-deception. Read-only review; no DB queries.

**Headline.** The proposed framework (scoreboard → truth → evaluation → registry → decision) is the right *shape*. The risk is not the framework. It is the habits around it:
- **Architecture before signal.** 25 commits, 41 processing modules, 81 test files and 40 task files exist. Not one signal has passed the bar.
- **Results that were not real.** The one "pass" was a bug: `strategy_tracker.md` T4/T5, "46/46 wins" and +527 bps, which came out at −20 bps on actual market closes.
- **Agent claims that were not checked.** Fabricated citations (`SESSION_CLOSEOUT_2026-09-29b.md` §5).
- **Plans that pile up.** Each new plan file supersedes the last one.

The framework needs three things it does not have yet: a **project-level kill switch**, a **test ledger** that also records failed and discarded tests, and **forward time as the only true holdout**. All price history from 2021-10 to 2026-09 has already been looked at.

---

### Q1
**Position:** Mostly right. Add four things: a drawdown/ruin limit, capacity, a project-level stop rule, and the passive index fund as the alternative the whole project must beat.
**Why:**
- "Has a reason" is dangerous if the reason is written *after* the result. The reason must be on the hypothesis card before the test runs.
- The desk meeting set a 40% drawdown tolerance and a <25% simulated worst-drawdown cap (`desk_meeting_2026-09-25.md` §2). Neither appears in the north star.
- The real competitor is a Nifty index fund plus Shivam's time. If nothing is promoted within a fixed budget, the honest outcome is "buy the index", and the north star should say so.
- "Survives costs" should read "survives costs **on data not used to find it**".
**Confidence:** high

### Q2
**Position:** Event-driven only (days to weeks), one book. Shelve multi-month fundamental investing until point-in-time fundamentals exist.
**Why:**
- `PIT_LABEL_AUDIT_2026-09-29.md`: quarterly and annual financials have no "known as of" date, 2023 is missing entirely, and moat/policy scores are dated Aug–Sep 2026. Any fundamental backtest today would be look-ahead (using information the market did not have yet).
- The only clean data is prices plus exchange dissemination timestamps, so only event-driven work can be tested honestly.
- Two books mean two scoreboards and double the threads. That is the over-commitment this project keeps doing.
**Confidence:** high

### Q3
**Position:** A liquid universe defined point in time by turnover, not by today's Nifty 200 flag. Cap each position at about 1–2% of average daily turnover. Use a *stated, realistic* capital number, not ₹10 cr by default.
**Why:**
- The `is_nifty200` flag has no history (PIT audit). Using today's index membership as the past universe is survivorship bias: the backtest only sees the companies that survived.
- The diffusion study used a ₹50 lakh/day turnover floor. At 1% participation that is ₹50k per trade, which is not a ₹10 cr book. Capacity and universe must be set together.
- The ₹10 cr "Oct-2021 lump sum" in the desk meeting looks like a hypothetical (uncertain). The scoreboard should assume what Shivam would actually deploy.
- Small caps: excluded at first. Circuit limits, impact costs and data holes there are a trap for event trades.
**Confidence:** med

### Q4
**Position:** Long-only. "Avoid lists" are allowed only if they are scored as a separate book (underweight against the benchmark), never as fake shorts.
**Why:**
- The only "win" so far was a SELL result produced by a long/short framing bug (T4: every SELL row had `target > entry`). Short-side mechanics are where this project has already hurt itself.
- Overnight cash shorts are not possible in India. F&O or SLB (stock lending) adds borrow cost and restricts the universe; nobody has measured either.
- An avoid list only earns money if you would otherwise hold the name. Its value has to be shown, not assumed.
**Confidence:** high

### Q5
**Position:** Keep the bar's structure but fix three defects:
1. "+500 bps" with no horizon is undefined.
2. A hit-rate test is wrong for skewed payoffs.
3. There is no forward-paper requirement.

Freeze the bar now. It has already been revised once after an embarrassment (2026-09-23).
**Why:**
- +500 bps over 2 days and over 365 days are completely different claims. State it per horizon, annualised, net of costs.
- Hit rate above 0.5 can pass a strategy that loses money (many small wins, a few large losses). Use a cohort-clustered mean t-stat plus information ratio (excess return per unit of tracking risk) plus max drawdown.
- Overlapping weekly cohorts are not 30 independent observations. Count independent periods.
- Add: a pass in backtest = "candidate". Promotion = candidate plus at least 6 months of forward paper results with the same sign.
**Confidence:** high

### Q6
**Position:** Primary benchmark is size- and liquidity-matched peer stocks, which the study already does. Always also report against the investable index. Use a factor model as a robustness check only.
**Why:**
- The matched-peer method is already built and tested (`PRICE_SIDE_DIFFUSION_STUDY` §7: raw returns and matched controls tell the same story).
- The factor spine is unvalidated. Making it the judge adds another untested component.
- For a long-only book, the money question is always "did I beat the index fund after costs?" Report that number even when it is ugly.
**Confidence:** med

### Q7
**Position:** Use a fixed, deliberately pessimistic cost stack until real fills exist, and pass the stress test at 2× costs. Pre-tax for the research gate, post-tax for the go-live decision.
**Why:**
- The current bar says "net of **measured** cost", but there are no fills, so the bar cannot currently be met. That contradiction invites quiet relaxation later. Fix the wording now.
- Event trades of 1–2 days in mid-liquidity names are where impact cost (the price moving against you as you trade) dominates. A 50 bps prior is not obviously conservative.
- Taxes (STCG 20%) matter only once there is something worth taxing. Do not let tax modelling become another build project.
**Confidence:** med

### Q8
**Position:** One append-only **test ledger**. Every test, variant, discarded design and failed run gets a row. Use the ledger count to set a stricter t-hurdle (about 3 rather than 2). Confirmation only on forward data.
**Why:**
- Discarded designs are already vanishing into prose. Example: §7 of the study "discarded" a first matching design that dropped high run-up events. That was the right call, but it is still a test that was tried.
- False-discovery correction (BH) is applied *within* the diffusion study but not *across* the project (F1, F2, T1–T12, grid P1, the diffusion families …).
- **No sealed historical period exists.** Every year 2021–2026 has been examined by year. Pretending otherwise is self-deception. The holdout is the future, starting from the freeze date.
**Confidence:** high

### Q9
**Position:** Six checks must pass before any test is trusted:
1. Point-in-time timestamps for every input.
2. Corporate-action-adjusted prices.
3. Survivorship (delisted names present).
4. Quarantine applied.
5. Dissemination time equals the real public release time.
6. A pinned data snapshot.

Most of these are still unverified today.
**Why:**
- Survivorship is **unverified/failing**: the sample is stocks present in the 2026 price table and delistings are missing (study §4.4). Only 59.5% of announcements map to a stock.
- Corporate actions are **partial**: `corporate_actions` starts 2023-01. A SWANDEF unadjusted jump already voided one result.
- Dissemination timing (`DissemDT`) is **unverified**. It is the leading suspect in the open −85 bp puzzle: the after-21:00 gradient could come from late or misdated stamps.
- Fundamentals point-in-time: **fails** (PIT audit). The concall date repair was applied, but its accuracy has not been re-sampled since.
- Five citations in the study report are still unchecked (closeout 2026-10-05 §3).
**Confidence:** high

### Q10
**Position:** Research only on dated, checksummed snapshots. Pause the two scheduled writers (`annualdrain`, `CapacityLoop`) unless a written hypothesis needs what they ingest. Keep only the EOD price update needed for forward paper trading.
**Why:**
- Annual-report ingestion feeds no current test. It is momentum, not purpose.
- Live writes have already broken one upload (Oct 2). They make any result impossible to reproduce unless it is tied to a snapshot.
- This needs Shivam's elevated PowerShell. It is his call, but the risk is real.
**Confidence:** high

### Q11
**Position:** The requirement is right. Define it as "first public at", not "computed at". Version only what the first hypothesis needs: the results filing date and point-in-time quarterly revenue/PAT.
**Why:**
- Versioning everything is another architecture project.
- `test_findings_2026-09-24.md` §2 shows why it matters: lenses fed by values with no history can never vote.
- Only one feature family is on the critical path right now.
**Confidence:** high

### Q12
**Position:** Set them aside. Label them "unvalidated, excluded from all scoring". Do not delete them. They come back only through a hypothesis card.
**Why:**
- On 43,789 material moves, the quality, policy and supply lenses emitted **0** directional votes (`test_findings_2026-09-24.md` §1).
- Moat history has 2 dates and policy history has 1. Geographic exposure has 37 USA rows out of 3,568. These are seeds, not measurements.
- Keeping them as "candidates" lets them leak back into dossiers and theses as if they meant something.
**Confidence:** high

### Q13
**Position:** The card contains:
- the mechanism;
- a falsifiable prediction (sign plus rough size);
- the exact signal definition;
- universe and liquidity floor;
- entry/exit timing rules;
- benchmark, cost stack, horizon;
- pass bar and kill bar;
- placebo;
- data snapshot ID and ledger ID.

Shivam freezes it by git commit *before* the confirmatory run. Any change after seeing returns creates a new card. The old card is logged as a failed test and is never edited.
**Why:**
- An agent must not be able to freeze or amend a card. Agents produced the 46/46 promotion.
- A git timestamp is cheap, tamper-evident proof of pre-registration.
- "Change after seeing" is fine as long as it costs a ledger entry. That makes the cost of p-hacking (tweaking until something looks significant) visible.
**Confidence:** high

### Q14
**Position:** First: earnings-surprise conditioning of the results reaction. It is the open puzzle, and it forces building the point-in-time quarterly data everything else needs. Second: a long-only "exit or avoid before results" card, frozen now and tested *forward only*. Drop further post-results drift work. Put guidance raises last.
**Why:**
- The ranking rule: (clean data available now) × (prior evidence) × (test cost) × (long-only tradability).
- Sign-free drift has decayed: +96 bp in 2023, then −11 in 2025 and −41 in 2026. More slicing of it is data mining.
- The −85 bp results-day gap (t −8) is the strongest number in the project. That is exactly why it is dangerous: it was found by exploration, its cause is unknown, and the timestamp lag is not ruled out. Freeze a card for it, then let forward data decide.
- Guidance raises need text extraction plus corrected concall dates (99% were wrong before the repair). That makes them the most expensive and the least verified.
**Confidence:** med

### Q15
**Position:** Exploration is allowed but time-boxed, about 30% of hours. Its outputs are labelled "exploratory — not evidence" and never quoted as results. Confirmation happens only on forward data from the card's freeze date.
**Why:**
- With no unseen history left (Q8), the only clean separation is time.
- Without a hard label, an exploratory t-stat quietly becomes a quoted "result". Compare the +790 bps "suggestive" number in T4, which is still sitting in the tracker.
**Confidence:** high

### Q16
**Position:** Yes, extend the diffusion-study code under `analysis/`, and keep it thin. Minimum scope:
- an event study;
- a long-only portfolio backtest with costs;
- automatic year-by-year output;
- a placebo;
- writing to the test ledger;
- a check that the data snapshot is pinned.

Leave the cross-sectional test for later.
**Why:**
- The code already has clustered standard errors, BH correction and negative controls. Do not rebuild it inside `reality_engine/`. That is the architecture trap again.
- **Mandatory known-answer tests:** inject a fake edge and the harness must recover it; feed zero edge and it must report about zero.
- **Mandatory invariant checks:** exit prices are market prices, and stop/target sides match the trade direction. These catch the 46/46 bug class.
**Confidence:** high

### Q17
**Position:** Treat all of 2021-10 → 2026-09 as in-sample, because it is already seen. The held-out period is forward paper from each card's freeze date. Require the same sign in at least 2 distinct market states *and* report every year.
**Why:**
- Five years, about 1,269 sessions, mostly one long bull phase with corrections. "2 regimes" is a low bar here.
- Signs flipping by year (drift: +96 → −41) is the most important regime warning already on file.
- A held-out set of stocks is a weak substitute because same-day returns are correlated across stocks. Use it only as a supplement.
**Confidence:** med

### Q18
**Position:** Do not build the ensemble or the mixture-of-experts router (MoE: a model that switches between sub-models) until there are at least 3 promoted, weakly correlated signals, each with at least 6 months of forward record. Until then, use equal weight. The router must beat equal weight *forward* to exist at all.
**Why:**
- Simple 1/N (equal weighting) is notoriously hard to beat out of sample (DeMiguel, Garlappi & Uppal 2009, RFS). This citation is well known but I did not re-verify it this session.
- The MoE "temperature" and lens-ranking machinery already exists in the schema and has never had a real signal to combine.
**Confidence:** high

### Q19
**Position:** The LLM does extraction only, with measured precision on a hand-labelled sample. It may *suggest* hypotheses, which then go through card plus ledger. No decisions, no promotions, no freezes.
**Why:**
- Track record: fabricated citations; the 46/46 promotion; commit messages claiming "100% F1" (commit `10fb07e`). No independent re-check of that claim is on file.
- Every number an agent reports should be re-runnable from a script before it enters a tracker.
**Confidence:** high

### Q20
**Position:** Demotion is automatic and pre-registered. It triggers on forward rolling net excess below zero with t < −1, or drawdown above 1.5× the backtest maximum, with no retuning allowed. Before real money: at least 6 months of forward paper and at least 30 independent events. Go-live starts at ≤5% of capital with a hard loss limit, and scales up in stages only after real fills confirm the cost assumptions.
**Why:**
- The F2 kill rule ("kill fast, no k-tuning", desk meeting §2) is the right pattern. Generalise it.
- Real fills are the only way to resolve the "measured cost" contradiction (Q7).
**Confidence:** med

### Q21
**Position:** Freeze until the first promotion, with a hard **review date** (proposal: 2026-12-31). Missing the date is a *project* kill-or-rescope signal, not a cue to unfreeze and build more. The freeze also covers video transcription, new councils, settings tinkering and new feeds.
**Why:**
- "Until promotion" alone is unbounded, and unbounded effort is how 40 task files appeared in about two weeks.
- The 100-hour study plan had the right instinct: a fixed clock, and "stop early when a gate fails".
**Confidence:** high

### Q22
**Position:** Yes. Use three files only:
- **`FRAMEWORK.md`**: the rules, changed rarely.
- **`STATE.md`**: one page, *overwritten* each session.
- **`TEST_LEDGER`**: append-only.

Move older plans and closeouts into `tasks/archive/`; git keeps the history. Also amend `AGENTS.md` (see below).
**Why:**
- Each closeout says "read me first" and supersedes the last. That is drift, not handoff.
- Overwriting STATE forces the next session to see one truth.
**Confidence:** high

---

## Missing questions

1. **Project kill switch and opportunity cost.** After how many hours or what date, with no promoted signal, does Shivam stop and just buy the index? Nothing in the list asks this.
2. **`AGENTS.md` conflicts with the freeze.** It tells every agent the mission is an all-peers ensemble, MoE temperature, event graphs and continuous self-correction. Every new session gets steered back toward the frozen architecture. `FRAMEWORK.md` must explicitly override it, and `AGENTS.md` must say so in its first lines.
3. **Who verifies agent claims?** Rule: no number enters a tracker unless an independent script re-run reproduces it, from a pinned snapshot.
4. **Bug-class invariants.** These are systematic checks: direction or framing, fills equal market prices, no future timestamps in features. Not just "tests pass".
5. **Old open threads must be explicitly buried or carded:**
   - the T4 "honest +790 bps" SELL re-test;
   - F3 regime-carry;
   - T6 open BUYs;
   - the video backlog;
   - the 100-hour guidance study.

   Otherwise they come back.
6. **Position-sizing and concentration rules, even for paper.** Event books cluster in results season, so 30 "independent" trades can be one bet on one week.
7. **The council itself.** Five subagents running on the same model are not independent advisors; agreement among us is weak evidence. Cap the debate at 2 rounds. Shivam's marks are the only authority.

## Questions I'd push other council members on

- **Quant Lead:** All five years have been examined year by year. What exactly is your holdout? And what does "+500 bps" mean for a 2-day versus a 20-day hold?
- **Data Steward:** Can you show that `DissemDT` equals the real first public release, not an exchange re-stamp? What would it cost to add delisted stocks? Until both are done, should any event-study number be quoted at all?
- **Trading & Execution Lead:** What is a realistic round-trip cost for a 1–2 day trade in a ₹50 lakh/day stock? Can a long-only "exit before results" rule make money once you count the forgone return on days you are out?
- **Macro & Behavioural PM:** Is the −85 bp results-day gap behavioural (sell the news), or just bad quarters filing late? If it is the latter, the earnings-surprise variable absorbs it and there is no separate edge. And does 2021–26 contain two genuinely different regimes, or one bull market with dips?
