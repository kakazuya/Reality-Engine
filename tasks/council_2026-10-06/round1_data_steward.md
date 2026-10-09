# Round 1 — Data Steward (data truth / point-in-time)

Lens: is each number what the market could actually have known at that moment, and has that been checked or only claimed?

## New evidence from today (2026-10-06, live DB opened read-only `file:...?mode=ro`, only indexed lookups)

Queries run: (1) list tables/views and look for history tables; (2) `substrate_quarantine` counts grouped by table and rule; (3) column lists of `financial_metrics`, `quarterly_financials`, `daily_price_delivery`, `corporate_actions`, `v_document_pit`; (4) `corporate_actions` counts by type; (5) price rows around 4 known split/bonus ex-dates (VBL, IONEXCHANG, BLUESTARCO, GULPOLY, June 2023); (6) `v_document_pit` counts by `pit_basis`; (7) per-ISIN first/last price date (index-only, 6.6 s); (8) split/bonus actions with no price row on the ex-date for the same ISIN.

Three findings that matter for everything below:

1. **Prices are NOT adjusted for splits or bonuses.** "Adjusted" here means past prices rescaled so a split doesn't look like a crash. On the ex-date `prev_close` is the old unadjusted price: BLUESTARCO 1:1 bonus shows −48.2%, VBL split −48.8%, IONEXCHANG 10:1 split −90.5%, GULPOLY 1:5 bonus **−11.9%** (true return was about +5.7%). The diffusion study computes returns as `close/prev_close − 1` and blanks anything beyond ±30% (`02_event_engine.py:23`). That catches big splits but **lets smaller bonuses (1:5, 1:10, 2:5 etc.) through as fake −9% to −17% days**. Dividends are not adjusted either. The 2026-09-29 audit called `prev_close` "the only split adjustment"; that is wrong.
2. **ISINs in the price table are rewritten to today's ISIN.** In India a face-value split issues a new ISIN. VBL's 2023 rows carry the post-split ISIN `INE200M01039`; `corporate_actions` stores the pre-split `INE200M01013`. 289 of 386 split/bonus actions have no price row on the ex-date under the same ISIN. So joins by ISIN across tables silently fail around exactly the events that break returns. The "ISINs never change" rule in AGENTS.md is not true for Indian equities.
3. **Corporate actions start only on 2023-01-02**, while prices start 2021-10-27. So 2021–22 has no action data to fix returns with.

Also confirmed: `v_document_pit` has 71,937 rows dated from the BSE feed (exact dissemination time), 434 from annual-report filenames, 45 from transcript bodies, **31,215 `unknown`** (30%). `quarterly_financials` has no filing-date column (`created_at` is the fetch time). No `index_membership_history`, `company_industry_history`, delisting or feature-snapshot table exists. `substrate_quarantine` is materialized: 1,356 synthetic-ISIN companies, 6+6 graph fixtures, 3+3+3 demo/unresolvable macro/ripple rows. The live DB file was last modified today 12:40 (scheduled writer active).

---

### Q1
**Position:** Right, but add "built on data the market actually had" as an explicit fourth leg, plus drawdown and capacity.
**Why:**
- An edge found on look-ahead data is not repeatable; it is a bug. That belongs in the north star, not only in a layer.
- Drawdown and capacity are other members' turf; I support adding them.
**Confidence:** high

### Q2
**Position:** Both, as separate books, but only the event-driven book is testable today.
**Why:**
- Event timing is solid: 72k documents have exchange dissemination timestamps (BSE `DissemDT`).
- Fundamental book needs dated financials (when results were *published*, not quarter-end). We have none: no filing date, 18 quarters with holes, YoY growth 0.0 on 43%/87% of rows (PIT audit). Multi-month fundamental tests today would be look-ahead.
**Confidence:** high

### Q3
**Position:** Start with names continuously traded and liquid; include small caps only after delisting and ISIN-change handling exist.
**Why:**
- Small caps are where bonuses/splits are most frequent and where unadjusted prices hurt most.
- `is_nifty200` is today's flag with no history; "Nifty 200 only" applied backwards is survivorship bias (you pick today's winners). Use a rule-based universe instead (e.g. top N by trailing 60-day turnover as of each date), which can be rebuilt from our price table without index history.
- Capacity size: outside my lens.
**Confidence:** med

### Q4
**Position:** Long-only with avoid lists. Data note: F&O eligibility also changes over time and we hold no history of it.
**Why:** any short-leg test needs a dated F&O list, which we don't have.
**Confidence:** med

### Q5
**Position:** Add a hard data gate to the promotion bar: a signal cannot be promoted unless the Q9 checks passed on the exact snapshot it was tested on.
**Why:**
- Statistical bar is Quant Lead's call; I'd add "result unchanged after corporate-action fix and after dropping `unknown`-dated events".
- A robustness re-run on a corrected price series is cheap and catches the GULPOLY-type error.
**Confidence:** med

### Q6
**Position:** Whatever benchmark is chosen, build it from the same adjusted, survivorship-aware price panel and the same as-of universe.
**Why:** if the benchmark contains fake bonus crashes from other stocks the excess return is wrong in both legs; placebo days at −4 bp/day (diffusion study §4.3) could partly be this.
**Confidence:** med

### Q7
**Position:** Fixed assumed cost stack, versioned and dated (STT/stamp-duty rates change by budget). Outside lens otherwise.
**Confidence:** med

### Q8
**Position:** Keep a test log that records the **snapshot ID and data version** for each test, not only the count.
**Why:** a re-run after a data fix is a new test; without the version you can't tell whether a result changed because of the idea or the data.
**Confidence:** med

### Q9 — minimum data-truth checks
**Position:** Six checks must pass before any result is trusted. Today **one passes, two partly, three fail**.

| Check | Status | Evidence |
|---|---|---|
| 1. Event timestamps = public dissemination time | **Partly verified** | 71,937 docs via BSE feed join (`v_document_pit`); concall body dates applied (7,019 rows). 31,215 (30%) still `unknown` and must be excluded, not filled with crawl dates. Unverified: that `DissemDT` is IST, post-15:30 and special sessions (study §4.6). |
| 2. Prices adjusted for splits/bonuses/dividends | **Fails** | Today's spot checks above. GULPOLY −11.9% passes the ±30% guard. |
| 3. Stable identity across ISIN changes | **Fails** | Price table restamped to current ISIN; 289/386 actions don't join. Need an ISIN-history map (old ISIN → new ISIN, date). |
| 4. Survivorship: delisted/merged names present | **Partly** | 574 of 5,710 ISINs stop before 2026-06, so some dead names exist, but study §4.4 says the sample is stocks present in 2026; no delisting table; actions feed has no delistings. Unverified how many real delistings 2021–26 are missing. |
| 5. Fundamentals dated by publication | **Fails** | No filing date in `quarterly_financials`/`financial_metrics`; `created_at` = fetch time. |
| 6. Quarantine applied before reading substrate | **Verified (exists)** | `substrate_quarantine` materialized (counts above). Unverified that every research script reads through it; the diffusion study doesn't touch substrate, so fine for now. |

Fixing 2 and 3 is cheap: we already have `corporate_actions` 2023+ (need NSE/BSE action history for 2021–22) and can derive split factors from the action subject text, then cross-check against price jumps. Until then, **any CAR (cumulative abnormal return) number from the diffusion study is provisional**, and the negative results-day puzzle should be re-run with bonus/split/ex-dividend days removed as test (5) already planned.
**Confidence:** high on status, med on how much it moves results.

### Q10
**Position:** Research only on dated, frozen snapshots; let ingestion continue on the live DB.
**Why:**
- The live file changed today at 12:40; any result read off it can't be reproduced tomorrow.
- The diffusion study already reads a Parquet export, which is the right pattern. Name every export with its date and record it in the result.
- Freezing ingestion stalls the PIT backlog for no gain. But writers must be stopped (or a copy taken while quiet) when cutting a snapshot — the Oct 2 upload already showed the risk.
- Each research result should cite: snapshot date, row counts, and git commit of the code.
**Confidence:** high

### Q11 — feature versioning
**Position:** Yes, the requirement is right. Every feature row needs two dates: the period it describes and the moment it became public (`first_public_at`); a read "as of t" takes rows with `first_public_at <= t`, and revisions are new rows, never overwrites.
**Why:**
- Today nothing beyond prices and document timestamps meets this (PIT audit: business models, moats, policy exposure all stamped Aug–Sep 2026).
- Order to version first: (1) adjusted prices + ISIN map (feeds everything); (2) quarterly results with result-announcement date (needed for earnings surprise, the top backlog item); (3) universe/index membership and F&O eligibility; (4) sector/industry labels; (5) document-derived (LLM) features stamped with the source document's dissemination time **and** the extractor version, since re-running an LLM changes values.
**Confidence:** high

### Q12 — the existing substrate
**Position:** Set aside. Label them "untested, undated priors"; no test may use them as historical inputs.
**Why:**
- Verified: they were generated in Aug–Sep 2026 from current documents (moat history 2 dates, policy 1). Feeding them into a 2022–2025 backtest is look-ahead by construction.
- They are also partly placeholder: 1,356 synthetic-ISIN companies quarantined; YoY growth zero on most rows; entity edge "shared terms" are stopwords.
- They can come back only if rebuilt from dated documents, as-of each date, and then tested like any hypothesis.
**Confidence:** high

### Q13
**Position:** Card must also carry: data snapshot ID, the date-field used for timing (e.g. `pit_ts` from BSE feed only), exclusion rules (`unknown` dates, quarantined rows), and the adjustment version of prices.
**Why:** changing the data after seeing returns is as much p-hacking as changing the parameters; freeze both.
**Confidence:** med

### Q14
**Position:** First: earnings-surprise conditioning on results days — but only after the results-filing date is attached to each quarter and prices are adjusted. Concall guidance (100-hour study) last.
**Why:**
- Results announcements have the best timestamps we own (BSE feed).
- Concall transcripts: 2026-only crawl dates were repaired, but text-derived features have no extractor versioning yet and 30% of docs lack a date.
- Ranking rule from my lens: data readiness × expected value.
**Confidence:** med

### Q15
**Position:** Seal the most recent period by snapshot, not by promise: hold back a dated copy that research code cannot read (separate file not on the default path).
**Confidence:** med

### Q16
**Position:** Yes, build from the diffusion-study code, with a shared data-loading module that enforces the Q9 checks (adjusted returns, ISIN map, PIT dates, quarantine) so no study re-implements them.
**Why:** the ±30% guard is a local patch in two scripts; the next study will copy it and inherit the bonus bug.
**Confidence:** high

### Q17
**Position:** Data constraint: clean prices run 2021-10 → 2026-09, actions only 2023+. That's one full rate cycle and one sharp small-cap run-up/correction at best. In-sample 2022–2024, holdout 2025–2026 is the only split that gives both enough events and a recent period; but 2021–22 needs action backfill first.
**Confidence:** med

### Q18
**Position:** Outside lens; from data side, an ensemble on unversioned features is meaningless, so not before Q11 items (1)–(3) exist. Equal-weight is enough.
**Confidence:** med

### Q19
**Position:** Extraction only for now, and every LLM output stamped with source doc's dissemination time, model name and prompt version.
**Why:** LLM reading a 2023 document today may use knowledge of what happened after 2023 (its training data). That is look-ahead you can't see. Keep it to quoting facts from the document.
**Confidence:** high

### Q20
**Position:** Paper trading forward is also the only truly clean PIT test we have — it can't leak future data. Log decisions with the inputs they saw at decision time (input snapshot), so demotion reviews compare like with like.
**Confidence:** med

### Q21
**Position:** Freeze new feeds/lenses until first promotion, **except** truth-layer repair: corporate-action adjustment, ISIN map, delisting list, results-filing dates. Those are not new features; they are fixes.
**Confidence:** high

### Q22
**Position:** Yes, one authority file. Add a short "data state" section to it (what is verified, current snapshot ID, open truth defects) replacing the PIT memory + closeout trail.
**Why:** the 2026-09-29 audit says `prev_close` adjusts splits; today it doesn't — stale claims survive in closeouts. One maintained table avoids that.
**Confidence:** high

---

## Questions I'd push other council members on

- **Quant Lead:** Will you re-run the results-day CAR puzzle with split/bonus/ex-dividend days excluded before anything else? How much of the −50 to −85 bp and the −4 bp/day placebo drift survives?
- **CRO / Independent Skeptic:** Should "unchanged after data correction" be a formal promotion requirement, and should any result computed on the unadjusted panel be marked void rather than provisional?
- **Trading & Execution Lead:** Your cost and capacity assumptions — are they built on the same unadjusted turnover and price series? Turnover in lakhs is fine, but price-based liquidity filters jump on split days.
- **Macro & Behavioural PM:** Your regime calls need dated macro data; we hold about 30 macro/policy docs. Is a "2 regimes same sign" test even possible with 2021–2026 data?
