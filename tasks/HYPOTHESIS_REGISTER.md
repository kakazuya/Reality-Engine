# Hypothesis Register — backtest-ready cards (v1)

**Written:** 2026-10-20 04:10 IST, for the Dussehra start Shivam named in his 2026-10-20 03:56 message
("we will have to create a lot of these hypotheses and test them").
**Authority:** `tasks/FRAMEWORK.md`. Where this file and FRAMEWORK disagree, FRAMEWORK wins.
**Inputs read in full:** `tasks/FRAMEWORK.md`, `tasks/STRATEGY_TEST_PLAN_2026-10-06.md`,
`tasks/strategy_tracker.md`, `tasks/modeling_bucket_list.md`, `tasks/PIPELINE_TODO.md`, `tasks/STATE.md`,
`tasks/PRICE_SIDE_DIFFUSION_STUDY_2026-10-03.md`, `reality_engine/data/hotline/README.md`,
`reality_engine/data/hotline/decisions.md`, `reality_engine/data/hotline/hotline.md`.
**Data checks:** read-only `python sqlite3` / `duckdb` against `equity_intelligence.db`, `concall_facts.db`,
`results_xbrl.db` and `truth_2026-10-19.duckdb` on 2026-10-20. No database or running job was touched.
Every count below names the table it comes from; anything I could not find says **not found**.
**Status:** 26 cards — 10 ready now, 13 partial, 3 blocked — plus a parked/buried list.
None has been run. Readiness is a schema-and-coverage check, not a result.

---

## 0. What this register is, and what it is not

This is the single list of hypotheses the shared harness will test, in the order it will test them.
It is built from what exists, not from what would be nice: the three older files keep their names and IDs,
duplicates are merged, and the new cards use the data that landed tonight (concall facts, the unified `events`
table, board meetings, results XBRL with `filings_isin`, shareholding, circuit hits, ETF premium,
`index_tri`, `policy_events`, PIB).

It is **not** a claim that any card makes money. The edge and cheapness scores are priors for ordering the work.
A card earns a place in the book only by passing FRAMEWORK §5 — and the first day's job is to run the cheap,
data-ready cards and log every variant, including the failures.

**The one rule that matters most:** every trigger is a `known_at` / `filed_at` / `posted_at` /
`disseminated_at` / `broadcast_at` / `intimated_at` time, never a period date (`period_end`, `quarter_end`,
`fiscal_year`, `effective_date`). A feature must be readable "as of date t" (FRAMEWORK §6, layer 2).

---

## 1. Fixed rules every card inherits

### 1.1 Trading, cost and risk (FRAMEWORK §2 and §4)

| Rule | Value used by every card |
|---|---|
| Instruments | Cash equities only, long only; no F&O, no overnight shorts. ETFs need a separate ruling (see H10). |
| Universe | All NSE and BSE cash equities, SME included; a position never exceeds 10% of the stock's 20-day average daily traded value. |
| Penny stocks | Raw close under ₹10 on the signal date excluded by default; eligible only with a structural fundamental shift **and** technical confirmation, flagged in the truth report. |
| Costs | **0.30% per round trip (30 bp)**, not the 80 bp prior in the 2026-10-06 plan. |
| Tax | After tax using `tax_rule(rule, sell_date)` from `tax_rules` (20 rows); STCG 20% / LTCG 12.5% from 23-Jul-2024. |
| New strategy allocation | 10% of capital. |
| Strategy kill | Drawdown > 8% on its allocation. |
| Portfolio drawdown | 5%, widened to 8% only when the benchmark is also falling. |

### 1.2 Benchmark — B5 (FRAMEWORK §3)

Each period is compared with **one** index chosen before the period starts: the best performer over the
trailing window among **Nifty Smallcap 250, BSE 250 SmallCap, Nifty Midcap 150, BSE Sensex and BSE IPO**.
Default: trailing 12-month total return, re-chosen monthly; the harness logs which window it used.
`index_tri` has all five (and Nifty 50 / Nifty 500) for 2019-01-01 → 2026-10-19, 1,934 rows each.
BSE total-return series are derived from price + published dividend yield × 0.8 (decisions.md, 2026-10-19);
record the `method` column with every result.

In the cards below, **Benchmark: B5** means exactly this, with the window and chosen index logged per run.

### 1.3 Evidence window (FRAMEWORK §5)

- Build and prove on **2021-01-01 → 2025-12-31**.
- **2026 is live**: run the chosen strategy through 2026 day by day at 10% allocation, with drawdown kills
  and self-correction. That run is the live record.
- 2019–2020 is warm-up only for lookbacks and features.
- No holdout period, no forward paper trading.

**Data-completeness gate (the unresolved tension).** Shivam's 2026-10-10 rule — all data for every traded stock
since 2019, verified by `coverage_report`, before any strategy test — is **not met** on annual reports, concalls or
decks (the 2026-10-11 report shows AR 33–61%, concalls 0–16%, decks 0–19% by year). His 2026-10-20 instruction
starts backtesting anyway. Resolution used here: prices, delivery and filing times are complete; results XBRL
covers ~1,800–2,800 ISINs a year, **not every traded stock**, so H01 is a subset test. AR/deck-dependent cards
(H16, H22, H23) stay partial. Every result prints the `coverage_report` table and is labelled provisional where
the rule is unmet.

### 1.4 Proof rules — the codes used in every card

| Code | What it means | FRAMEWORK |
|---|---|---|
| **F1** | History-only and point-in-time: built and proven on 2021–2025; every feature as-of t; 2026 live. | §5 bullet 1, §6 layer 2 |
| **F2** | Fluke control: one ledger for every test (pass and fail); BH-FDR across the **full** variant grid; deflated / reality check across variants; placebo or shuffled-date test ≈ 0; same sign across periods and regimes. | §5 bullet 2 |
| **F3** | Promotion bar: risk-adjusted, **after tax**, net of 30 bp round trip, against B5; 2026 live record included. The old +500 bp bar is reference only. | §5 bullets 3–4, §2 costs, §3 |
| **F4** | Risk limits: 10% allocation, 8% strategy kill, 5%/8% portfolio drawdown, position ≤ 10% of daily traded value. | §4 |

A card's "Proof rule" line names the decisive test; F1 and F4 apply to all cards whether or not repeated.
For avoid-only cards, F3 is scored as a **cohort** (what not owning would have saved), never as a trade.

### 1.5 Universe shorthands

- **U1 — liquid all-exchange:** all NSE/BSE cash equities including SME; raw close ≥ ₹10; 20-day median
  `px_daily.value_inr` ≥ ₹50 lakh; exclude `substrate_quarantine`; position ≤ 10% of 20-day ADTV.
  The ₹50 lakh floor is the diffusion study's convention (PRICE_SIDE_DIFFUSION_STUDY §3), not a FRAMEWORK rule;
  tune it in the harness and log the choice.
- **U2 — delivery-valid:** U1 restricted to segments where delivery is variable: NSE EQ/SM/ST and
  BSE X/M/B. Exclude NSE BE/BZ (`delivery_pct` is NULL on 366,183 / 58,217 rows) and BSE XT/MT
  (compulsory delivery prints ~100%, so a delivery signal cannot discriminate).
- **U3 — data-conditional:** U1 ∩ companies with the named facts (concall, shareholding, policy map, etc.).

### 1.6 Readiness legend

- **READY** — every named field exists, the PIT timestamp exists, and coverage spans 2021–2025 with enough
  names/events to test now.
- **PARTIAL** — the fields exist but a named gap must close first: coverage, a parser, a PIT column, or a
  snapshot omission. The gap is stated in the card.
- **BLOCKED** — the signal cannot be computed from the database today. The missing table/history is named.

---

## 2. Ranked index — ready first, then expected edge × cheapness

Read this as a work queue, not a return forecast. **★ = one of the first five to run on Dussehra.**
H06 (Card A) is an **overlay** on H01, not a sixth slot: it changes when H01 enters, it does not add a position.

| # | ID | Card | Ready | Edge | Cheap | Hold | Dir | Why here |
|---:|---|---|---|---|---|---|---|---|
| 1 | **H01** | **Card B — Earnings-surprise conditioning (PEAD)** ★ | READY | H | M | 20/60 td | + | Uses tonight's results + timing data; the headline test. |
| 2 | **H02** | **Card F — Bulk/block deal accumulation** ★ | READY | M | M | 20/60 td | + | Deal history now 2019→2026; independent flow signal. |
| 3 | **H03** | **Card F — CMF / delivery-weighted CMF** ★ | READY | M | H | 20 td | + | One query over `px_daily`; tests the accumulation mechanism. |
| 4 | **H04** | **P1 — Momentum vs reversal by horizon** ★ | READY | M | H | 30/90/180/365 td | +/− | Cheapest baseline; every other card must beat it. |
| 5 | **H05** | **Delivery spike** ★ | READY | M | H | 5/20 td | + | India-specific, one query, same family as H03. |
| 6 | H06 | Card A — Pre-results timing overlay | READY | M | H | 5 pre / 1 post | avoid | Cheap risk overlay; runs with H01. |
| 7 | H07 | Circuit-hit follow-through | READY | L–M | H | 3/5/20 td | +/− | Cheap, but the liquidity trap caps the edge. |
| 8 | H08 | FII/DII cash-flow regime | READY | M | H | 20 td | + | 1,932 days; low power, but tests the macro gate. |
| 9 | H09 | Card E — GSM stage moves | READY | M | H | 20/60 td | − | Avoid-only; ASM is not in the data (not found). |
| 10 | H10 | ETF premium / discount | READY data, **GATED** | H | H | 3/10/20 td | + | Highest raw score, but FRAMEWORK §2 says cash equities only. |
| 11 | H11 | P4 — VIX regime conditioning | PARTIAL | M | H | host card | + | VIX is live only, not in the snapshot. |
| 12 | H12 | Board-meeting purpose events | PARTIAL | M | H | 5/20 td | +/− | Text regex + 50 hand checks; no parsed type. |
| 13 | H13 | Card C / P6 — Promoter open-market buying | PARTIAL | M | M | 20/60 td | + | Date cleaning + post-May-2026 trades missing. |
| 14 | H14 | Card D — Guidance raises in concalls | PARTIAL | H | M | 20/60 td | + | 2025-05→2026-10 only; 2021-24 unstructured. |
| 15 | H15 | Order surprise (concall + Telegram) | PARTIAL | M | M | 20/60 td | + | Values are free text; BSE order-win parser missing. |
| 16 | H16 | Capex / capacity expansion | PARTIAL | M | M | 60/120 td | +/− | 2025-26 only; capex actuals missing. |
| 17 | H17 | Analyst pushback / Q&A evasiveness | PARTIAL | M | M | 20 td | − | Counts exist; a validated score does not. |
| 18 | H18 | Promoter pledge change | PARTIAL | M | M | 60 td | − | Pledge parsed for only 5.5% of filings. |
| 19 | H19 | FII/DII ownership change | PARTIAL | M | M | 60 td | + | 13.5k / 50.3k rows; snapshot detail missing. |
| 20 | H20 | Auditor / rating action avoid | PARTIAL | M | H | 60 td | − | Headline regex only; small n. |
| 21 | H21 | Policy stage drift | PARTIAL | H | L | 20/60 td | +/− | 21.5k events, but sector→company map missing. |
| 22 | H22 | P3 — LM sentiment on concall text | PARTIAL | M | L | 20 td | − | Chunks exist; lexicon/score does not. |
| 23 | H23 | Card G / P2 — Forensic & solvency avoid | PARTIAL | M | M | 12 m | − | Ratios exist, but not as-filed/PIT. |
| 24 | H24 | Card E — Index inclusion/exclusion | BLOCKED | H | L | 20 td | +/− | One membership snapshot only. |
| 25 | H25 | IPO / OFS listing | BLOCKED | M | L | 5/20 td | ? | No issue price/allotment data. |
| 26 | H26 | P7 — Hierarchical sector→stock shrinkage | BLOCKED | L | L | n/a | + | Small/micro cells n = 0. |

---

## 3. The cards

## Part A — Ready now

### H01 · Card B — Earnings-surprise conditioning (PEAD) ★

- **Claim:** A positive year-on-year PAT surprise, scaled by the company's own eight-quarter variability,
  earns positive excess over 20/60 sessions in liquid stocks; the first-two-day reaction is a conditioner,
  not the signal.
- **Signal (exact):** `results_key.ProfitLossForPeriod` (quarter, OneD context) for `period_end` q and the same
  quarter a year earlier; `surprise = (PAT_q − PAT_q−4) / std(8 quarterly YoY changes)`. Use
  `results_key.consolidated='Consolidated'`; fall back to `'Standalone'` or `'Non-Consolidated'` only when no
  consolidated row exists and record the basis. Revenue variant: `results_key.RevenueFromOperations`; banks use `InterestEarned`
  because `RevenueFromOperations` is null for them. Exclude `period_end IS NULL` (1,171 rows) and duplicate
  filings. Join `results_key.file = results_filings.file`; `results_filings.trading_isin` in the snapshot is
  the `filings_isin` resolution from the live `results_xbrl.db`. Use it and never `filings.isin`, which carries
  stale pre-split ISINs on about 15% of filings (STATE.md, 2026-10-19 05:20).
- **PIT trigger:** earliest `bse_ann.DissemDT` with `SUBCATNAME='Financial Results'` whose `NEWSSUB` parses
  to the same period end ("... ended 31st December 2024"), joined `bse_ann.SCRIP_CD →
  security_master.bse_code → security_master.isin`; fallback = earliest Financial Results announcement within
  100 days after `period_end`. **`bse_ann.QUARTER_ID` is NULL on all 140,627 Financial Results rows (checked),
  so do not use it.** Enter at t+1 open. **Never `period_end`.**
- **Universe:** U1; require a prior-year quarter and non-null PAT.
- **Holding:** 20 and 60 trading days; report both and FDR over both.
- **Benchmark:** B5.
- **Readiness:** **READY.** `results_key` 2021–2025: 1,793 → 2,384 ISINs with non-null PAT; 2,120 companies
  with ≥ 12 quarters; `bse_ann` Financial Results 140,627 filings (2020-01-01 → 2026-10-19); `px_daily`
  2019-01-01 → 2026-10-19. Revenue leg is partial: 1,797 → 2,813 ISINs with revenue.
- **Direction:** + (long positive surprise; negative surprise is an avoid, not a short).
- **Proof rule:** **F2** over 2 horizons × 2 surprise measures (PAT, revenue) × surprise sign; BH-FDR;
  placebo = shuffled filing dates within the same month. Then **F3** after tax at 30 bp.
- **Main fooling risk:** **look-ahead** — `results_filings.known_at_utc` is NSE XBRL dissemination and can be
  a day after the BSE results PDF (TITAGARH Q3 FY25: BSE 13-Feb-2025 20:32 IST, XBRL 14-Feb 15:10 IST;
  STATE.md). Survivorship: build the universe from `security_master`, including delisted names. **Coverage bias:**
  only XBRL filers with PAT (~2,120 companies with ≥12 quarters) are in the test, not the ~5,000–7,800 traded
  stocks; state the covered share with every result. Overlap: the results cluster and the H06 timing overlay.

### H02 · Card F — Bulk/block deal accumulation ★

- **Claim:** Net buying by identifiable institutions in NSE/BSE bulk or block deals predicts +20-day excess,
  and the effect is stronger in less-followed stocks.
- **Signal (exact):** `nse_deals(date, deal_type, symbol, client_name, buy_sell, quantity, price)` and
  `bse_deals(date, deal_type, sc_code, client_name, buy_sell, quantity, price)`; net = Σ buy − Σ sell per
  (isin, date); keep |net value| ≥ ₹1 crore. There is **no `is_marquee` column**: fix a marquee whitelist
  before the run and log it. Join `symbol → symbol_isin_history` on the deal date; BSE `sc_code →
  security_master.bse_code`.
- **PIT trigger:** `known_at_utc` (date-only = end of day IST) → t+1 open. Never the deal-date close.
- **Universe:** U1; exclude clients who are promoters/insiders (dedupe with H13).
- **Holding:** 20 and 60 trading days.
- **Benchmark:** B5.
- **Readiness:** **READY.** 138,572 NSE + 135,509 BSE deal rows, 2019 → 2026-10; `deal_type` includes BULK
  and BLOCK. No ISIN and no marquee flag: both are build steps, not missing data.
- **Direction:** +.
- **Proof rule:** **F2** across 2 marquee definitions (broad institution list vs top-20 repeat clients) ×
  2 horizons; placebo = shuffled deal dates. Then **F3**.
- **Main fooling risk:** **liquidity/price** — a block prints at a negotiated price, not the close you can buy
  at, and the next-open gap can eat the edge. Look-ahead if the deal date is used. Client-name entity
  resolution. Overlap with results and momentum.

### H03 · Card F (sub-check) — CMF / delivery-weighted CMF ★

- **Claim:** A high or rising 20-day Chaikin Money Flow, especially the delivery-weighted version, precedes
  positive 20-day excess.
- **Signal (exact):** `px_daily.high/low/close` (use `adj_high/adj_low/adj_close`) and `adj_volume`;
  `CMF = Σ(((close−low) − (high−close))/(high−low) × volume) / Σ volume` over 20 days. Delivery variant uses
  `deliverable_qty` in place of volume. Restrict to U2; exclude BSE XT/MT (compulsory ~100% delivery).
- **PIT trigger:** close of t (known 18:00 IST, STATE) → t+1 open.
- **Universe:** U2.
- **Holding:** 20 trading days.
- **Benchmark:** B5.
- **Readiness:** **READY.** `px_daily` 7,258,000 rows, 2019-01-01 → 2026-10-19; delivery is non-null on NSE
  EQ 3,174,516 rows and BSE X 1,812,021 rows (mean 53.6% / 83.0%). NSE BE has 366,183 rows with delivery
  NULL — exclude, do not read as zero.
- **Direction:** +.
- **Proof rule:** **F2** over level vs 20-day change × total vs delivery volume (4 variants) + shuffled dates.
  Then **F3**.
- **Main fooling risk:** split/bonus volume jumps (use `adj_volume`, drop `corporate_actions.ex_date` days);
  compulsory-delivery segments; **overlap** with H05 delivery spike and H04 momentum — test as one family in
  the FDR, not as independent discoveries.

### H04 · P1 — Momentum vs reversal by horizon ★

- **Claim:** 90/180-day momentum has positive excess and 30-day reversal is negative; the long leg survives
  liquidity and survivorship controls.
- **Signal (exact):** `px_daily.adj_close` (robustness `tr_close`); return over 30/90/180/365 trading days,
  skipping the last 5 days; cross-sectional rank within 20-day ADTV buckets. Benchmark-relative variant
  subtracts `index_tri.tri` for B5.
- **PIT trigger:** last trading session of the month (close) → next open.
- **Universe:** U1; delisted names kept via `security_master.first_trade/last_trade`.
- **Holding:** 30 / 90 / 180 / 365 trading days; the horizon is the treatment, not a choice.
- **Benchmark:** B5.
- **Readiness:** **READY.** `px_daily` 2019 → 2026-10-19 with `adj_close` non-null on all 7,258,000 rows;
  `index_tri` 7 indices × 1,934 days. Adjusted prices verified on a split: BANSALWIRE 2026-10-16 raw
  −80.5%, adjusted −2.3%.
- **Direction:** + for 90/180/365; − for 30 (avoid only; no short).
- **Proof rule:** **F2** across 4 horizons × 2 formation windows × 2 universes (FDR). Then **F3**.
- **Main fooling risk:** **survivorship** (use `security_master`, not today's index members); penny stocks;
  look-ahead in index membership; overlap with H01/H03/H05; factor-zoo multiplicity.

### H05 · Delivery spike ★

- **Claim:** A delivery-spike ratio above 3 with a positive price move predicts +5/20-day excess in
  delivery-valid segments (U2).
- **Signal (exact):** `px_daily.deliverable_qty`; `spike = deliverable_qty(t) / SMA20(deliverable_qty)`;
  require `close(t) > close(t−1)` and `delivery_pct(t)` above its own 60-day median. Restrict to U2.
  Do **not** use `daily_price_delivery.delivery_spike_ratio` — that table ends 2026-09-24.
- **PIT trigger:** EOD t → t+1 open.
- **Universe:** U2.
- **Holding:** 5 and 20 trading days.
- **Benchmark:** B5.
- **Readiness:** **READY.** Compute from `px_daily`; delivery fields are populated on NSE EQ/SM/ST and
  BSE X/M/B (see H03 counts).
- **Direction:** +.
- **Proof rule:** **F2** over thresholds 2/3/5 × 5/20 days + shuffled dates. Then **F3**.
- **Main fooling risk:** BE/BSE delivery NULLs (exclude); split/bonus volume; **overlap** with H03 CMF —
  the two are one family and must share an FDR.

### H06 · Card A — Pre-results timing overlay

- **Claim:** Buying in the sessions before a pre-announced results board meeting, especially when the
  company's own history predicts a late filing, gives up return; delay the entry until after the filing.
- **Signal (exact):** `board_meetings.purpose ILIKE '%Financial Results%'` and `meeting_date`; late-filer
  score = share of the company's last 8 `bse_ann` Financial Results `DissemDT` after 15:30 IST (and after
  21:00 IST), using only filings **before `intimated_at`**. Never the actual filing time.
- **PIT trigger:** `board_meetings.intimated_at` (`known_at_utc`); earliest intimation if revised.
- **Universe:** U1, applied to every long candidate.
- **Holding:** overlay: 5 sessions before `meeting_date` to 1 session after the actual filing; scored as the
  delta versus the same trade without the overlay.
- **Benchmark:** B5.
- **Readiness:** **READY.** 120,600 board meetings 2019-01-01 → 2026-11-14; `purpose` has 40,783
  "Financial Results" plus 9,919 "/Other business matters" variants; `intimated_at` is on average 12 days
  before the meeting and never after (STATE.md).
- **Direction:** avoid/delay; the timing benefit should be positive.
- **Proof rule:** **F2** with placebo = random meeting dates matched by month; stability by year. Then
  **F3** as an overlay delta.
- **Main fooling risk:** meetings are revised and `meeting_date` ≠ filing date; using the actual `DissemDT`
  leaks the future; **overlap** with H01 — condition on surprise so the overlay is not just PEAD.

### H07 · Circuit-hit follow-through

- **Claim:** An upper-circuit hit continues for 3–5 sessions when delivery is high, then reverses by 20 days;
  lower-circuit hits bounce.
- **Signal (exact):** `circuit_hits.date`, `symbol`, `series`, `high_low` ('H'/'L'); join
  `symbol_isin_history` on the date; `delivery_pct` from `px_daily`.
- **PIT trigger:** `circuit_hits.known_at_utc` is date-only (23:59 IST) → t+1 open; never intraday.
- **Universe:** U1; drop stocks with `price_bands.band='5'` (5% band) on the day — a hit there is usually locked.
- **Holding:** 3, 5 and 20 trading days.
- **Benchmark:** B5.
- **Readiness:** **READY.** 482,308 rows 2019-01-01 → 2026-10-19; H 237,364 / L 244,944; 4,502 symbols.
  No ISIN in the table — join.
- **Direction:** + short, − medium; the sign is the test.
- **Proof rule:** **F2** over 3 horizons × H/L + placebo on matched non-circuit days. Then **F3**.
- **Main fooling risk:** **liquidity** — you cannot buy at the circuit price, and the next-open gap is the
  real entry; price-band changes; overlap with momentum.

### H08 · FII/DII cash-flow regime

- **Claim:** Aggregate FII net buying over 20 sessions predicts positive next-month smallcap excess; DII
  buying cushions but does not lead.
- **Signal (exact):** `fii_dii_cash.fii_net_cr`, `dii_net_cr`; 20-day sum; interaction with `index_tri`
  (`index_name='NIFTY SMALLCAP 250'`) returns. Both tables are in the snapshot.
- **PIT trigger:** EOD t (flows published after close) → t+1.
- **Universe:** broad smallcap basket (U1 equal-weight or Nifty Smallcap 250 members).
- **Holding:** 20 trading days.
- **Benchmark:** B5.
- **Readiness:** **READY.** 1,932 days 2019-01-01 → 2026-10-19; ~92 monthly observations — low power, state it.
- **Direction:** +.
- **Proof rule:** **F2** over FII/DII/both × 5/20/60-day windows + shuffled flow blocks. Then **F3**.
- **Main fooling risk:** small n; flow data timing; flows are endogenous to returns; overlap with market
  beta and H04.

### H09 · Card E (surveillance) — GSM stage moves

- **Claim:** Stocks entering GSM Stage I/II underperform over 20–60 days; exits outperform. Long-only use is
  avoid/delay, not a short.
- **Signal (exact):** `price_bands.remarks` regex `GSM.*Stage.*(0|I|II|III|IV)` normalized across the
  case/format variants ("GSM STAGE - 0", "GSM Stage - 0", "GSM - Stage I"); `price_bands.band`; sequence by
  symbol.
- **PIT trigger:** `price_bands.known_at_utc` (date-only EOD) → t+1.
- **Universe:** U1.
- **Holding:** 20 and 60 trading days.
- **Benchmark:** B5.
- **Readiness:** **READY (with a caveat).** 4,044,248 band rows 2021 → 2026; GSM stages are present.
  **ASM is not in the table** — 0 rows with "ASM"; do not claim ASM coverage.
- **Direction:** − on entry, + on exit.
- **Proof rule:** **F2** over stages I–IV + entry/exit + placebo matched non-GSM stocks. Then **F3** as an
  avoid overlay.
- **Main fooling risk:** label variants; GSM co-moves with circuit hits and price-band changes; end-of-day
  timing; survivorship.

### H10 · ETF premium / discount (GATED)

- **Claim:** Buying an ETF at a deep discount to same-day iNAV, and avoiding >10% premiums, earns positive
  excess as the premium mean-reverts; MONQ50 in September 2026 is the stress case.
- **Signal (exact):** `etf_inav.inav`, `premium_vs_inav_pct` (5 international ETFs); `etf_premium.premium_pct`
  = 100 × (close/nav − 1) (366 ETFs); `etf_px.value_inr` for liquidity.
- **PIT trigger:** `etf_inav` is same-day index × FX (known at close) → t+1 open. `etf_premium` uses the AMFI
  NAV published after t close → t+1; never t close.
- **Universe:** ETFs only (`etf_px`), not equities; `value_inr` floor.
- **Holding:** 3, 10 and 20 trading days.
- **Benchmark:** B5 for comparability; also report vs NAV and vs a near-identical ETF.
- **Readiness:** **READY data, GATED scope.** `etf_px` 314,199 rows / 432 ISINs to 2026-10-19;
  `etf_premium` 267,587 rows / 366 ETFs to 2026-10-16; `etf_inav` 6,785 rows / 5 ETFs to 2026-10-19.
  Both `etf_inav` and `etf_premium` are live-DB only (not in the 2026-10-19 snapshot).
  **Gate 1:** FRAMEWORK §2 says "cash equities only"; ETFs are not equities — Shivam must rule them in.
  **Gate 2:** `tax_rules` carries equity STCG/LTCG; ETF-specific tax is **not found** — verify before F3.
- **Direction:** + (buy discount), avoid premium.
- **Proof rule:** **F2** over 5 ETFs × 3 horizons + placebo (premium shifted 5 days). Then **F3/F4** only if
  in scope.
- **Main fooling risk:** **look-ahead via NAV publication lag** (the big one); stale NAV for international
  ETFs; circuit/creation suspension (MONQ50 +235% premium on 18-Sep-2026, then −49% in three sessions);
  thin liquidity; instrument scope.

---

## Part B — Partial: close the named gap first

### H11 · P4 — VIX regime conditioning

- **Claim:** The same long signals earn more when India VIX is in its top quintile; VIX should gate
  aggression, not be a standalone signal.
- **Signal (exact):** `mkt_nse_index_daily.index_name='India VIX'.close` and `nse_index_breadth` same; 20-day
  change and quintile vs trailing 3 years; interaction with H01/H04.
- **PIT trigger:** VIX close t (EOD) → t+1.
- **Universe:** all cards, as a conditioning layer.
- **Holding:** same as the host card.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** VIX exists 2019 → 2026 in the live DB but is **not in `truth_2026-10-19`**;
  add it to the snapshot before the harness reads it.
- **Direction:** + for panic-conditioned longs (if the crisis thesis holds).
- **Proof rule:** **F2** over quintiles + placebo shuffled VIX blocks. Then **F3**.
- **Main fooling risk:** few independent regimes (2020, 2022, 2025); look-ahead if VIX is used intraday;
  small n.

### H12 · Board-meeting purpose events

- **Claim:** Board-meeting intimations for bonus/buyback/fund-raising produce positive 20-day excess; plain
  results meetings do not.
- **Signal (exact):** `bse_ann.SUBCATNAME='Board Meeting'` + regex on `NEWSSUB`/`HEADLINE` for
  `Bonus|Buyback|Buy-back|Fund Raising|Fundraising|Preferential|Rights`; `board_meetings.purpose` as the
  cross-check. There is **no parsed event-type field** — build the regex and hand-check 50.
- **PIT trigger:** `bse_ann.DissemDT` / `known_at_utc` (intimation), not `meeting_date`.
- **Universe:** U1.
- **Holding:** 5 and 20 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** 203,644 Board Meeting announcements + 120,600 `board_meetings` rows; text is
  free-form; the regex and hand checks are cheap but not done.
- **Direction:** + for bonus/buyback/fund-raise; unclear for results-only.
- **Proof rule:** **F2** over 4 purpose classes + placebo ("Other business"). Then **F3**.
- **Main fooling risk:** vague or repeated intimations; rescheduling; priced-in information; look-ahead if
  `meeting_date` is the trigger.

### H13 · Card C / P6 — Promoter open-market buying

- **Claim:** Open-market purchases by promoters/promoter group, disclosed under SEBI PIT, predict +20/60-day
  excess; intra-group transfers, ESOPs and pledges do not.
- **Signal (exact):** `mkt_nse_insider.person_category IN ('Promoters','Promoter Group')`,
  `transaction_type='Buy'`, `acquisition_mode='Market Purchase'`, `buy_qty > 0`, `buy_value`; add
  `mkt_nse_sast.sale_or_acq='Acquisition'` + `acquisition_mode IN ('Open Market','Open market')` — SAST uses
  "Open Market", not the PIT table's "Market Purchase". Exclude 'Inter-se transfer', 'Inter-se-Transfer',
  'ESOP', 'Pledge Creation', 'Revokation of Pledge', 'Gift', 'Off Market'.
- **PIT trigger:** `mkt_nse_insider.disseminated_at` (disclosure) → t+1; not `acq_from`.
- **Universe:** U1.
- **Holding:** 20 and 60 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** 176,089 PIT rows / 2,198 symbols, 2019 → 2026-05-02; 574 rows have
  unparseable `acq_from` (years 1922 and 3034); `insider_trades` is **0 rows**; SAST has no ISIN, quantity or
  value; post-2026-05-02 trades exist only in `nse_pit_filings` + `nse_pit_xbrl_facts` and are not parsed
  into transaction rows. Missing: cleaned dates and post-May-2026 trades.
- **Direction:** +.
- **Proof rule:** **F2** (promoter vs promoter group; with/without director buys; placebo shuffled
  disclosure dates). Then **F3**.
- **Main fooling risk:** **look-ahead via acquisition date vs disclosure date**; inter-se transfers miscoded
  as market buys; token buys; survivorship; overlap with H02 deals.

### H14 · Card D — Guidance raises in concalls

- **Claim:** A computed guidance raise versus the prior comparable call predicts +20/60-day excess beyond
  the earnings surprise, and is stronger when the company's prior guidance was met. Direction variants:
  `raised` (+), `new` first-time quantified (+ if credible), `lowered` (−, avoid), `maintained` (placebo).
- **Signal (exact):** `cc_items` (list_name='guidance') joined `cc_item_checks` on (doc_id, list_name, idx)
  where `computed_direction IN ('raised','lowered','new','maintained')`, `value_in_quote=1`,
  `direction_supported=1`, same `metric_key` / `item_fy`, `prev_doc_id` not null. Numeric value =
  `cc_item_checks.value_low` / `value_high` with the `value_is_pct` flag, and the comparable prior =
  `cc_item_checks.prev_doc_id` / `prev_value_mid`; do not parse the raw `cc_items.value` string. Credibility =
  prior guidance midpoint vs later `results_key` actual for the same fiscal year/quarter. Use
  `computed_direction`, never the LLM `direction` alone.
- **PIT trigger:** `cc_docs.filed_at` (transcript filing) or `events.kind='concall'.known_at_utc`; never the
  call date or period. Verify on 10 docs that `filed_at` is the public filing time (the call date is not in
  this table).
- **Universe:** U3 ∩ companies with a prior comparable call.
- **Holding:** 20 and 60 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** 1,718 ok docs / 152,080 items, 2025-05 → 2026-10 (662 docs / 287 ISINs in
  2025; 1,056 / 404 in 2026); only 280 computed comparisons (90 raised / 65 docs) at the 2026-10-20 check;
  2021–2024 has no structured facts (chunks only); the v3 prompt re-read is pending; `cc_items.value` is
  free text.
- **Direction:** + for raised/new; − for lowered (avoid, no short); maintained is the placebo.
- **Proof rule:** **F2** over direction × raise size × credibility × metric (revenue/margin/PAT), FDR;
  placebo = a random non-call date for the same company. Then **F3**.
- **Main fooling risk:** LLM label/period error (`period_in_quote` 55%, direction backed 24%); the call comes
  after results (**overlap** with H01 — test incremental IC); coverage bias (Telegram/PEAD companies in
  2026); small n.

### H15 · Order surprise (concall + Telegram)

- **Claim:** A large order win or order-book increase disclosed in a concall or a Telegram order alert
  predicts +20/60-day excess when the order is ≥ 10% of trailing revenue.
- **Signal (exact):** `cc_items` list_name='order_book' (`value`, `unit`, `period`, `quote`) — values are
  free text and must be parsed; `tg_orders` (`value_cr`, `annual_cr`, `duration_months`, `revenue_cr`,
  `revenue_fy`, `pct_of_revenue`, `customer`); `tg_order_schedule.amount_cr` by fy/q. `bse_ann` order-win
  announcements exist but are unparsed.
- **PIT trigger:** `cc_docs.filed_at` or `tg_orders.known_at_utc` (Telegram post) or `bse_ann.DissemDT` for
  order wins; never the order date.
- **Universe:** U3.
- **Holding:** 20 and 60 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** 2,615 order_book items / 276 ISINs / 783 docs (2025–26) plus 219 `tg_orders` /
  121 ISINs (2025-07 → 2026-10); values are not numeric; the BSE order-win parser is missing; no order-book
  level history (only disclosed snapshots).
- **Direction:** +.
- **Proof rule:** **F2** over source (concall/Telegram/BSE) × order/revenue bucket + placebo (no-value
  announcements). Then **F3**.
- **Main fooling risk:** order value ≠ revenue (execution period, JV/parent scope); repeat/recap alerts;
  OCR/name mismatch; coverage bias; overlap with results.

### H16 · Capex / capacity expansion

- **Claim:** Announced capex/capacity expansion predicts +60/120-day excess only when it is funded and
  demand-backed; unfunded or JV/parent capex predicts nothing or negative.
- **Signal (exact):** `cc_items` list_name='capex' and list_name='capacity_and_projects'; parse
  `value`/`unit`/`period`; scope (JV/parent/subsidiary) and funding (internal vs debt) from the quote plus
  `cc_items` list_name='balance_sheet_and_cash'. There is no actual capex/PPE line in `results_key` to verify
  completion.
- **PIT trigger:** `cc_docs.filed_at`.
- **Universe:** U3.
- **Holding:** 60 and 120 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** 3,317 capex items / 372 ISINs / 1,203 docs + 7,281 capacity items, 2025–26
  only; no capex actuals; capacity/utilisation is **not found**.
- **Direction:** + (conditional); unclear overall.
- **Proof rule:** **F2** across funded/unfunded, JV/own, size buckets + placebo (maintenance vs growth).
  Then **F3**.
- **Main fooling risk:** **scope mislabel** — the Ester case stored ₹1,600 crore of JV capex as Ester's own
  (actual share ₹250–270 crore); capex ≠ spend; no completion dates; look-ahead via decks.

### H17 · Analyst pushback / Q&A evasiveness

- **Claim:** Concalls with high analyst pushback density predict negative 20-day excess; low pushback with a
  raise predicts positive.
- **Signal (exact):** `cc_items` list_name='analyst_pushback' (`metric`, `statement`, `quote`, `doc_id`);
  count per doc divided by total items; topic concentration; `cc_item_checks.speaker_role` for analyst vs
  management.
- **PIT trigger:** `cc_docs.filed_at`.
- **Universe:** U3.
- **Holding:** 20 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** 14,642 items / 415 ISINs / 1,705 docs, 2025–26; no validated evasiveness
  score; the counts are mechanical, the label is not.
- **Direction:** − (pushback); + (no pushback + raise).
- **Proof rule:** **F2** over density quintiles × topic + placebo (shuffled item labels within the doc).
  Then **F3**.
- **Main fooling risk:** LLM classification / speaker attribution; doc-length confound; coverage bias;
  overlap with H14.

### H18 · Promoter pledge change

- **Claim:** A quarter-on-quarter increase in pledged promoter shares predicts negative 60-day excess; a
  release predicts positive.
- **Signal (exact):** `shareholding.promoter_pledged_pct` (from `shp_facts` context
  `ShareholdingOfPromoterAndPromoterGroup_ContextI`, concept
  `EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares`), `quarter_end`, `broadcast_at`; QoQ delta;
  also `promoter_encumbered_pct`.
- **PIT trigger:** `shp_index.broadcast_at` / `known_at_utc`, not `quarter_end`.
- **Universe:** U3.
- **Holding:** 60 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** The `shareholding` view has 50,329 rows but `promoter_pledged_pct` is non-null
  for only 2,757 (5.5%); FII 13,478, DII 13,333, MF 9,471. Snapshot carries `shp_index.promoter_pct` only;
  the pledge/FII detail is live-DB only. Fix the parse before testing.
- **Direction:** − on increase; + on release.
- **Proof rule:** **F2** (increase/release/no change) + placebo shuffled quarters. Then **F3**.
- **Main fooling risk:** 5.5% coverage → **selection bias**; context labels; revised filings; quarter_end vs
  broadcast look-ahead; pledge ≠ distress.

### H19 · FII/DII ownership change

- **Claim:** QoQ FII increase predicts +60-day excess; DII/MF increase is weaker or contrarian.
- **Signal (exact):** `shareholding.fii_pct`, `dii_pct`, `mf_pct`, `quarter_end`, `broadcast_at`; QoQ delta
  and level.
- **PIT trigger:** `broadcast_at`.
- **Universe:** U3.
- **Holding:** 60 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** 13,478 FII / 13,333 DII / 9,471 MF rows out of 50,329; 2021+ only (NSE SHP XBRL
  starts mid-2021); the snapshot carries `shp_index` only.
- **Direction:** + FII; unclear DII.
- **Proof rule:** **F2** (FII/DII/MF × level/change) + placebo. Then **F3**.
- **Main fooling risk:** coverage; quarter_end vs broadcast; overlap with H08 flows and H04 momentum;
  revisions.

### H20 · Auditor / rating action avoid

- **Claim:** Auditor resignation/qualification or a rating downgrade announcement predicts negative 60-day
  excess; avoid-only.
- **Signal (exact):** `bse_ann.HEADLINE` / `NEWSSUB` regex ("resignation" + "auditor", "qualified opinion",
  "rating" + "downgrade"); no structured action field; hand-check 50.
- **PIT trigger:** `bse_ann.DissemDT` / `known_at_utc`.
- **Universe:** U1; avoid cohort only.
- **Holding:** 60 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** 1.95M announcements; text regex only; no parsed event type; counts are small.
- **Direction:** −.
- **Proof rule:** **F2** (auditor vs rating vs both; placebo "auditor reappointment"). Then **F3** as an
  avoid overlay.
- **Main fooling risk:** keyword false positives; small n; clustering; look-ahead if the PDF body (not the
  headline) is used.

### H21 · Policy stage drift

- **Claim:** A policy event at stage 'signal'/'draft' for a sector produces positive excess in that sector's
  mapped companies before the 'effective' date; the market prices the announcement, not the implementation.
- **Signal (exact):** `policy_events.stage`, `sectors`, `companies`, `direction_for_industry`,
  `published_at`, `known_at_utc`, `effective_date`, `quote_ok`; `pib_releases.posted_at`, `ministry`,
  `title`, `relevant`; join `company_industry` on macro/sector/industry/basic_industry via a hand-built
  sector map (A3 is not done: 3,478 distinct sector strings).
- **PIT trigger:** `policy_events.known_at_utc` / `pib_releases.posted_at` (minute precision); never
  `effective_date`.
- **Universe:** U3 ∩ mapped sector.
- **Holding:** 20 and 60 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** 21,552 events 2019 → 2026-10 (announced 12,609, effective 3,333, signal 2,370,
  draft 125, consultation 76); PIB 28,853 releases 2021 → 2026; sector→company map missing; companies are
  free text; PIB register backfill is in progress; require `quote_ok ≥ 98%`.
- **Direction:** +/− per `direction_for_industry`.
- **Proof rule:** **F2** across stages × map versions, FDR; placebo = non-policy PIB releases matched by
  ministry. Then **F3**.
- **Main fooling risk:** **sector string mapping**; **`company_industry` is a current NSE label, not PIT** — using
  it for 2019 events is look-ahead, so restrict to companies whose sector did not change or build a dated map;
  look-ahead via `effective_date`; reverse causality (policy follows the sector); overlapping events; small n
  per sector.

### H22 · P3 — Loughran-McDonald sentiment on concall text

- **Claim:** Negative Loughran-McDonald sentiment in concall Q&A predicts negative 20-day excess, incremental
  to guidance and surprise.
- **Signal (exact):** `document_chunks.content` for transcript docs, joined to `corporate_documents` /
  `v_document_pit.pit_ts`; LM finance lexicon (not in the DB — install it); score =
  (negative − positive)/(positive + negative); Q&A only if speaker tags exist.
- **PIT trigger:** `v_document_pit.pit_ts` → t+1.
- **Universe:** U3 with 2021–25 transcript chunks.
- **Holding:** 20 trading days.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** Chunks exist for 2021–25, but there is no LM lexicon/score; 2026 facts are
  structured (H14) and can substitute; PIT dates were repaired.
- **Direction:** −.
- **Proof rule:** **F2** (LM vs finance-specific lexicon; Q&A vs prepared remarks) + placebo shuffled dates.
  Then **F3**.
- **Main fooling risk:** lexicon mismatch; boilerplate; chunk/PIT dates; coverage; overlap with H14/H17.

### H23 · Card G / P2 — Forensic & solvency avoid list

- **Claim:** Stocks failing the solvency gate (promoter pledge > 15%, interest cover < 2.5×, D/E > 1.5×) or
  showing high accruals underperform; avoid-only, never traded.
- **Signal (exact):** `annual_financials.debt_to_equity`, `interest_coverage`, `net_profit_inr_cr`,
  `revenue_inr_cr`; `shareholding.promoter_pledged_pct`; compute Altman Z / Beneish M / Piotroski F from
  as-filed data. Accruals need as-filed cash-flow/working-capital facts (`ar_facts`, `results_facts`), **not**
  `annual_financials.operating_cash_flow_inr_cr` (mostly 0/null). `company_forensic_health` is current-only,
  one row per ISIN — **not PIT**.
- **PIT trigger:** `events.kind='annual_report'.known_at_utc` for the fiscal year, or the results filing for
  the quarter; never `fiscal_year` end.
- **Universe:** U1; avoid cohort.
- **Holding:** 12 months / until the next annual report.
- **Benchmark:** B5.
- **Readiness:** **PARTIAL.** `annual_financials` 12,933 rows / 3,361 ISINs, FY20–FY26, but no `filed_at`
  and it is live-DB only (the snapshot carries `results_key`/`ar_facts`); `company_forensic_health` 4,065
  current rows (no history); pledge 5.5%. The accrual leg is especially weak:
  `annual_financials.operating_cash_flow_inr_cr` was 0 or null on 12,432 of 13,015 rows in the 2026-10-10 check
  (STATE.md; the table now has 12,933 rows), so accrual screens need as-filed XBRL/AR cash-flow facts, not this
  column or yfinance restatements.
- **Direction:** −.
- **Proof rule:** **F2** (each screen alone and combined, FDR) + placebo matched non-flagged. Then **F3** as
  an avoid overlay.
- **Main fooling risk:** **look-ahead** (using FY data before the annual report); restatements; current-only
  holdings; coverage; small n in extreme buckets.

---

## Part C — Blocked

### H24 · Card E (index) — Index inclusion/exclusion

- **Claim:** Index inclusion (Nifty 50/100/Midcap 150) forces buying and predicts +20-day excess; exclusion
  predicts negative.
- **Signal (exact):** `index_membership.index_name`, `symbol`, `isin`, `as_of` — one snapshot only; no
  inclusion/exclusion event table.
- **PIT trigger:** index-change announcement — **not in the DB**.
- **Universe:** index members.
- **Holding:** 20 trading days.
- **Benchmark:** B5.
- **Readiness:** **BLOCKED.** `index_membership` has three indices (nifty50, nifty100, niftymidcap150) as of
  2026-09-30; no history and no change dates. Missing: index membership history / announcement feed.
- **Direction:** + inclusion; − exclusion.
- **Proof rule:** **F2** across indices and horizons; then **F3**.
- **Main fooling risk:** **survivorship** (using today's members for history); look-ahead; overlap with flows.

### H25 · IPO / OFS listing

- **Claim:** IPO listing pops / OFS discounts predict short-term excess.
- **Signal (exact):** `bse_ann` 'New Listing' (1,085 rows); no issue price, allotment, subscription or OFS
  data. `index_tri` 'BSE IPO' is an index, not a listing event.
- **PIT trigger:** listing-date announcement.
- **Universe:** new listings.
- **Holding:** 5 and 20 trading days.
- **Benchmark:** B5.
- **Readiness:** **BLOCKED.** No IPO issue/allotment/OFS table **found**.
- **Direction:** unclear; listing pops are usually positive, but a long-only entry after the pop may have no edge.
- **Proof rule:** **F2** (listing-day return vs a matched non-listing control; no promotion without issue-price
  data), then **F3** only if a tradeable long exists after the pop.
- **Main fooling risk:** survivorship (failed listings absent); look-ahead; tiny sample.

### H26 · P7 — Hierarchical sector→stock shrinkage

- **Claim:** Small/micro cells borrow sector strength, improving stability.
- **Signal (exact):** `model_explainer_rankings` / `eod_scrip_calls` by sector; small/micro cells n = 0.
- **PIT trigger:** as-of date.
- **Universe:** small/micro.
- **Holding:** n/a (stability study).
- **Benchmark:** B5.
- **Readiness:** **BLOCKED.** No small/micro call rows; coverage is needed first.
- **Direction:** + (stability), not a standalone long signal.
- **Proof rule:** **F2** (stability across cells and periods), then **F3** as a shrinkage overlay on an existing card.
- **Main fooling risk:** sparse cells; over-shrinkage.

---

## Part D — Parked, buried and method gates

### P5 — Sizing and model stack (parked)

Kelly sizing, OU exits, EVT stops, BSTS counterfactuals, BMA, bandits, conformals, GBM/LightGBM, survival
analysis, transfer entropy, Hawkes cascades, copulas, spectral cyclicality. `tasks/strategy_tracker.md`
P5 says "book must stabilize first". None is a hypothesis card yet; they are sizing/model layers that need a
working signal to size. Keep them out of the first wave.

### Buried — do not re-test without new evidence

| ID | Name | Evidence and status |
|---|---|---|
| T1 | BUY unexplained weakness + intact quality + solvent | 44 closed BUY, 1 win, mean −5.00; horizon excess −338 bp vs Nifty, −299 bp vs Midcap. Killed; baseline only. |
| T4 | SELL widened broken-thesis | 46/46 "wins" were a framing artifact: all rows long-framed (`target > entry`), `stop_hit` fired on bar 1 and `pnl` equalled the stop percentage. Revoked. |
| T5 | SELL realized-window excess | +527 bp reproduces only with the artifact exit price; on market closes −20 bp, hit 0.50. Revoked. |
| T10 | Next-day confirmation filter | Stabilized 1W/29L, skipped 0W/14L; hit 0.03. Dead. |
| T11 | Trend-continuation entry | Only 6/34 continuations; 28/34 sudden drops. Dead. |
| T12 | Embedding model (bge-small vs bge-base) | Keep bge-small; method verdict, not a return hypothesis. |

Do not re-test T1/T4/T5/T10/T11 as-is. T4/T5 may return only after the terms-layer framing fix
(`SELL ⇒ target < entry < stop`) and a rebuilt excess table on market closes.

### Method gates — keep, but they are not cards

T2 (predictor honesty: levels gate, flows vote), T3 (\|move\| ≥ 2σ floor), T6 (momentum agreement gate),
T7 (HOLD baseline hit-rate), T8 (calibration / `apply_if_improved`), T9 (horizon exit scoring) are harness
checks. They stay in the shared test harness; they do not compete for a hypothesis slot.

---

## 4. Source coverage — every named idea from the three files

| Source | Name(s) | Where it lives |
|---|---|---|
| `STRATEGY_TEST_PLAN_2026-10-06.md` | Step 0 | **P0** pre-flight gate (below) |
| | Card A | **H06** |
| | Card B | **H01** |
| | Card C | **H13** |
| | Card D | **H14** |
| | Card E | **H24** (index, blocked) + **H09** (surveillance) |
| | Card F | **H02** (deals) + **H03** (CMF sub-check) |
| | Card G | **H23** |
| `strategy_tracker.md` | T1, T4, T5, T10, T11 | Buried table |
| | T2, T3, T6, T7, T8, T9 | Method gates (kept) |
| | T12 | Method verdict (kept) |
| | P1 | **H04** |
| | P2 | **H23** |
| | P3 | **H22** (LM); GARCH floors → F4 sizing, not a card |
| | P4 | **H11** |
| | P5 | Parked |
| | P6 | **H13** |
| | P7 | **H26** |
| `modeling_bucket_list.md` | Momentum, factor zoo, event-study AR | **H04**, **F2**, method |
| | Beneish/Altman/Piotroski, accruals, receivables/CCC, auditor, pledge | **H23**, **H18** |
| | Hawkes, OU, Kelly, transfer entropy, EVT, spectral | Parked P5 |
| | GBM, tone, guidance-change, isolation forest, survival, bandits, conformal | **H14**, **H17**, **H22**, **H23**, P5 |
| | Beta-binomial, hierarchical, BSTS, BMA, structural priors, always-valid p | P5, **H26**, **F2** |
| | Promoter signaling, FII/DII herding, IPO/OFS, execution | **H13**, **H08**/**H19**, **H25**, F4 |
| | Anchoring, LM sentiment, attention, VIX, narrative | **H04** variant, **H22**, **H05**/**H17**, **H11**, parked |

**Merges that prevent reframing:** results reaction + surprise → H01 (reaction is a conditioner);
guidance raise + new guidance + credibility → H14 (variants, one FDR); Card G + P2 → H23; Card C + P6 → H13;
Telegram + concall + BSE order wins → H15 (source variants); ETF switch + premium → H10; benchmark-relative
momentum → H04 variant.

---

## 5. Pre-flight gates (run before the first card)

### P0 — Step 0: re-run the results-day puzzle on adjusted prices

- **Question:** do the −85 bp results-day gap and the late-filer gradient (−15 bp before 13:00 → −84 bp after
  21:00) survive once split, bonus and ex-dividend days are adjusted or removed?
- **Signal:** `events.kind='results'` or `bse_ann.SUBCATNAME='Financial Results'`; CAR(0,1) from
  `px_daily.adj_close`; drop `corporate_actions.ex_date` split/bonus days in [t0−5, t0+20]; timing buckets
  pre-open / intraday / after-close from `bse_ann.DissemDT`.
- **Trigger:** BSE `DissemDT`.
- **Universe:** U1.
- **Holding:** event window 0,+1; drift 2,+20.
- **Benchmark:** the study's liquidity-bucket abnormal return first; re-report vs B5.
- **Readiness:** **READY.** `corporate_actions` 18,220 rows; `px_daily.adj_close` non-null on all rows;
  adjusted prices verified on BANSALWIRE (split 2026-10-16: raw −80.5%, adjusted −2.3%).
- **Direction:** n/a (re-check, no promotion).
- **Proof rule:** gates F2; no card may quote a diffusion number until P0 relabels it holds/changed/gone.
- **Main fooling risk:** ex-dates inside the drift window; bonus/split volume; ISIN changes.

### H1 — Harness constants (set once)

1. Read the newest `truth_<date>.duckdb`; record the snapshot date with every result. Run
   `coverage_report` and print its per-year table with every result: H01–H05 depend on prices and results, not on
   the AR/deck coverage (which is 14–61% by year in the 2026-10-11 report), but the gap must be stated, not hidden.
2. Costs: 30 bp per round trip. Tax: `tax_rule(rule, sell_date)`. Benchmark: B5, chosen before the period.
3. Universe: U1 by default; U2 for delivery cards; delisted names via `security_master`.
4. Cluster standard errors by date (and stock for cross-sectional tests); report n, hit rate, mean, median,
   t-stat, and per-year results for every card.
5. One ledger: every variant, pass or fail. BH-FDR across the **whole** grid of that card. Placebo ≈ 0.
6. No card is promoted on one period, one regime or one variant.

### H2 — First-day sequence (Dussehra)

1. **P0** on adjusted prices; hand-check 20 events against the exchange.
2. Build the results-event table from the earliest BSE `DissemDT`; hand-check 20 vs the exchange.
3. Build U1 with delisted names and the liquidity floor; print names per year.
4. Run **H01, H02, H03, H04, H05** in that order; H06 runs as an overlay on H01.
5. Stop and report. No promotion from day one; the ledger and the per-year tables are the deliverable.

**Stop rule:** if a card cannot clear its PIT check on 20 hand samples, it does not run that day; log why.

---

## 6. What the data does not show (checked, not guessed)

| Missing thing | What was checked | Consequence |
|---|---|---|
| Index membership history | `index_membership` has 3 indices, one `as_of` 2026-09-30 | H24 blocked; any historical index test would be survivorship-biased. |
| ASM history | `price_bands.remarks` has 0 rows containing "ASM"; only GSM stages | H09 covers GSM only; do not claim ASM. |
| Analyst consensus / forward estimates | No consensus table; decisions.md records the choice to use own guidance/trend | H01/H14 use own-history expectations, not "surprise vs street". |
| Capacity / utilisation | No table; `cc_items.capacity_and_projects` is qualitative | H16 cannot test capex→capacity→utilisation; only announcement returns. |
| BSE order-win parse | `bse_ann` has order announcements, no parsed value/customer/period | H15 is partial until the parser exists. |
| IPO issue price / allotment / OFS | No table found; `bse_ann` has 'New Listing' only | H25 blocked. |
| Post-2026-05-02 insider trades | Only `nse_pit_filings` + `nse_pit_xbrl_facts`, unparsed | H13 partial. |
| `insider_trades` transaction rows | Table exists, **0 rows** | H13 must use `mkt_nse_insider` + `mkt_nse_sast`. |
| Pledge detail | `shareholding.promoter_pledged_pct` non-null on 2,757 of 50,329 | H18 partial; 5.5% coverage is a selection problem, not just a small sample. |
| VIX in the snapshot | `truth_2026-10-19` has no `mkt_nse_index_daily` / `nse_index_breadth` | H11 partial; add VIX to the snapshot. |
| ETF iNAV / premium in the snapshot | `etf_inav` / `etf_premium` live only | H10 needs the live DB or a snapshot extension. |
| Shareholding detail in the snapshot | Only `shp_index` (promoter/public) is in the snapshot | H18/H19 need the live DB or a snapshot extension. |
| PIB bodies in the snapshot | Snapshot `pib_releases` carries metadata only | H21 text checks need the live `pib_releases.body`. |
| Policy sector→company map | `policy_events.sectors` has 3,478 distinct strings; A3 not built | H21 partial; a sector-level version can start before a stock-level one. |
| 2021–2024 concall facts | `cc_docs` ok docs start 2025-05; older years are chunks only | H14–H17 cannot cover the full 2021–2025 window yet. |
| NSE BE/BZ delivery | 366,183 BE + 58,217 BZ rows with `delivery_pct` NULL | Any delivery card must exclude BE/BZ; do not treat NULL as 0. |

**What the files also do not show:** whether any of these cards makes money after 30 bp and tax. The
edge × cheapness ordering is a prior, not evidence. The first honest result will be the ledger after the
first five run.

---

## 7. Open decisions for Shivam

1. **ETFs (H10):** FRAMEWORK §2 says cash equities only. Are ETFs in scope for the book, research only, or out?
   If in scope, the ETF tax treatment must be added to `tax_rules` (not found).
2. **Marquee whitelist (H02):** no `is_marquee` column exists. Approve a fixed list (or let the harness use
   "top-20 repeat clients" as a pre-registered proxy).
3. **Order-win parser (H15):** the BSE feed is complete but unparsed; parsing it needs an LLM (paid) or a
   rule-based parser. Which?
4. **Index history (H24):** no machine-readable source found on niftyindices; buy/parse an archive, or drop H24?
5. **Pledge parse (H18):** fix the `shareholding` view (5.5% coverage) before any pledge test; is that a
   priority over the first five? My view: no — the first five do not need it.
6. **Snapshot extensions:** add India VIX, `etf_inav`, `etf_premium`, shareholding detail and PIB bodies to
   the nightly snapshot, or let the harness read the live DB for those cards? The cleaner path is the snapshot.

---

## 8. Sources for the numbers in this file

- FRAMEWORK rules: `tasks/FRAMEWORK.md` §2–§6.
- Evidence window, live 2026, proof rules: `tasks/FRAMEWORK.md` §5.
- Results timing lag and the TITAGARH example: `tasks/STATE.md` (2026-10-19 05:50 entry).
- Board-meeting count and intimation lead: `tasks/STATE.md` (2026-10-19 05:40 entry).
- Deal/insider/ETF/TRI/shareholding/circuit/band coverage: `tasks/STATE.md` 2026-10-19 entries and the
  read-only checks above.
- Diffusion-study numbers (−85 bp, late-filer gradient, 55–75 bp drift): `tasks/PRICE_SIDE_DIFFUSION_STUDY_2026-10-03.md` §3–§8.
- Old bar, old universe assumptions and buried strategies: `tasks/STRATEGY_TEST_PLAN_2026-10-06.md`,
  `tasks/strategy_tracker.md`, `tasks/modeling_bucket_list.md`.
- Snapshot table counts and dates: `truth_2026-10-19.duckdb` (`duckdb_tables()`, `describe`, counts above).
- Concall coverage and label quality: `concall_facts.db` (`cc_docs`, `cc_items`, `cc_item_checks`) and
  `tasks/STATE.md` 2026-10-19 03:20 entry.
- Tax rates: `tax_rules` (20 rows) and `tasks/STATE.md` 2026-10-19 04:45 entry.
