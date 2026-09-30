# SESSION_CLOSEOUT — 2026-09-29 (token cost + information-diffusion method)

Zero-context handoff. Read this plus the two files it points to; assume no other memory.

---

## 1. Objective

Two asks, in priority order.

1. **Reduce token cost.** User reported rising token cost. Investigate plugins,
   LSP usage, and cache reads. Headroom was flagged by the user as promising;
   user explicitly deferred it ("leave headroom for later").
2. **Prepare data for a Thursday 2026-10-02 deadline** to run information-diffusion
   studies across: annual reports, concalls, investor presentations, quarterly
   financials, order-book reports, bank monthly business updates, Vahan 2W/3W
   chassis sales, AMC flows, NSDL FII sector-level flows, daily FII/DII cash and
   index-futures flows. User wants it "neatly chunked and vector dimension so I can
   query it like a rack system." Secondary ask: the tested statistical/probabilistic
   literature for answering *which news, which stock, at what time, at what
   percentage*, and how to apply it.

---

## 2. Live processes

| Process | State at close |
|---|---|
| `bse_announcement_harvest.py` | **EXITED, not finished.** Reaped by 19:53. |
| Harvest log last write | 2026-09-29 19:53:25 |
| Progress reached | 380 / 4,915 symbols, 305,890 rows, 1,174s |
| No `python*` processes alive at close | confirmed via Get-Process |

**This process is NOT persistent and was NOT restarted.** Do not assume the harvest
is progressing. Restarting is a user decision — it was a background data-collection
job, not a supervised one. Full-history PIT timestamps depend on it completing;
at the observed ~3.1s/symbol rate the remaining 4,535 symbols is roughly 3.9 hours.

---

## 3. Settings — orders executed AND orders that FAILED

Config namespace is `cfg://`, writes require interactive approval, global persist
via the `/save` suffix.

**Successfully applied and saved to global config:**

| Key | Was | Now | Effect |
|---|---|---|---|
| `compaction.thresholdTokens` | `-1` (unlimited) | `160000` | Caps context; see caveat below |
| `defaultThinkingLevel` | `max` (32k budget) | `high` (16k) | Thinking billed as output |

**Caveat on the compaction change, unresolved:** the user selected the option
labelled "Cap at 160k only", described as "Keeps extendedContext, just compacts
earlier." `extendedContext` was left at its prior value. Whether a 160k threshold
combined with extended context actually behaves as that option described was NOT
verified. If the user reports context still ballooning past 160k, this pair is the
first suspect.

**Requested by user TWICE, and FAILED BOTH TIMES. Still at original values:**

| Key | Current value | What the user wanted |
|---|---|---|
| `advisor.enabled` | `true` | `false` (off globally) |
| `autolearn.autoContinue` | `true` | `false` (off globally) |

Attempt 1 timed out with no approval response. Attempt 2 (re-issued after the
timeout) was **explicitly DECLINED by the user**. Both were also offered as a
multi-select in `ask` and the user selected *neither* option there. So the
instruction is genuinely ambiguous across three signals. **Do not retry a third
time.** Ask once, in plain text, and let the user set these manually if they
still want them off. Note `advisor.enabled` default is `false`, so the user (or a
prior session) explicitly turned it on; that may be deliberate.

---

## 4. Token cost — measured, and what the levers are

Read from the session's own main log (52 requests, `$4.17` total):

| Cost line | Amount | Share |
|---|---|---|
| Cache writes | $2.28 | **55%** |
| Cache reads | $1.24 | 30% |
| Output (incl. thinking) | $0.65 | 16% |
| Uncached input | $0.00 | ~0% |

Cache writes dominated. Six requests wrote >20k tokens; the largest were 152k,
103k and 85k. A session reading 208k tokens of context means the prefix is
re-sent whenever compaction fires or a cache entry expires.

**Correct framing of the caching question:** the user asked about "increasing cache
reads." Reads are already the cheap line. The goal is to reduce large cache
*writes*, which means keeping the context smaller and avoiding mid-session edits
to the prompt prefix. Lowering the context ceiling attacks both.

**Headroom — NOT adopted, per user decision.** What it is, and the caveats, so the
next session does not re-litigate from scratch:

- An open-source context-compression layer: library, zero-code-change HTTP proxy
  (`headroom proxy --port 8787`), or MCP server. Sits between app and LLM,
  compresses tool output / logs / files / RAG chunks before the model sees them.
  Compression is reversible (originals cached locally) and it dedups across agents.
  Repo: `github.com/headroomlabs-ai/headroom`
- Headline claims: **~20% fewer tokens for coding agents**, 60–95% for JSON. The
  60–95% figure is JSON-shaped workloads and does **not** transfer to this case.
- Unverified risk: a proxy that rewrites the prompt can *break* prefix caching and
  *increase* the cache writes that already dominate this bill. Headroom claims it
  stabilises content for caching; that claim is unverified.
- Unverified: whether omp can be routed through a proxy at all (base-URL override).
- If revisited: trial on a throwaway session, compare cost-per-request against
  this log's baseline. Do not adopt on faith.

**LSP is already available** as `xd://lsp` and saves tokens by replacing
grep-then-read loops with direct definition/reference/hover lookups. It was left
on. Its savings depend on actually being used consistently.

---

## 5. REVOCATIONS — do not let these resurrect

The first answer in this session contained **fabricated or misattributed
citations**. A later turn caught them; each was re-verified against sources before
the corrected versions above were published. The corrections are the canonical
ones. **If a prior artifact or a future draft reintroduces any item below, it is
wrong.**

| Bad claim | Corrected to |
|---|---|
| "I-share" attributed to "Ding, Froot & Schipper (2010)" | **Hasbrouck (1995)**, "One security, many markets" — information share (IS), the most widely used price-discovery contribution measure. The paper does not exist. |
| State-space eq. `R=μ+ε`, `μ=μ₋₁+θR₋₁+η` claimed to yield `Var(μ)/Var(R)` as I-share | Discard the derivation. For single-venue stocks use a **Beveridge–Nelson or Hasbrouck VECM** permanent/transitory split. |
| "Media-Optimus" as Tetlock's dictionary | **Tetlock (2007, JF 62)** built a pessimism factor from Harvard GI-IV word categories. "Media-Optimus" is not the name. |
| Engelberg & Parsons (2011) used TV broadcast tone | It used **local newspaper coverage** (San Francisco). Design logic still the right idea: news reaching otherwise-disadvantaged investors identifies an information-arrival effect. |
| "Biais, Fukuyama & Hillion (1997)" and "Aktas et al. (2007)" for order imbalance | **Chordia, Roll & Subrahmanyam (2002, JFE 65)** "Order imbalance, liquidity, and market returns"; and **Chordia & Subrahmanyam (2004)** on order imbalance and individual stock returns. Both fabricated. |
| Sloan (1996) cited for post-earnings-announcement drift | Sloan (1996) is about **accruals**. Drop it from the PEAD chain. |
| "Indian mid-caps have t50 in the 3–20 day range" | **Unsourced guess. Withdrawn.** Fit it; do not assume it. |

Confirmed-good citations, safe to use: **Ball & Brown (1968)**, **Bernard & Thomas
(1989)** for PEAD/drift; **Kothari & Warner (2007)** for event-study econometrics;
**Tetlock (2007)**; **Da, Engelberg & Gao (2011)** (Google search volume as
attention proxy); **Chordia/Roll/Subrahmanyam (2002)**.

---

## 6. Method — how to use the literature

The user's question is four estimable quantities. Standard methods exist for each;
together they reduce to one panel regression once the event timestamp is fixed.

**(a) At what time → lag profile.** Cross-sectional regression of next-day return
on *lagged* news score, not contemporaneous. Tetlock (2007): high media pessimism
predicts downward price pressure followed by reversion to fundamentals, with the
predictive power **concentrated in after-hours and opening-hour returns**. That
argues for hourly/intraday bars and for modelling the after-hours window
separately — a direct design instruction, not a footnote.

**(b) At what percentage → information share.** Hasbrouck (1995) IS for
multi-venue price discovery; for single-venue NSE/BSE names use Beveridge–Nelson or
Hasbrouck VECM to split trend vs noise, then measure the news-driven share of
variance. One number per stock per month tells you which names are even *eligible*
for a diffusion study. Note the data gap in §7 (sector coverage) that this
cross-sectional work depends on.

**(c) Fraction incorporated by a deadline.** Fit cumulative abnormal return to a
saturation curve:

    CAR(τ) = A · (1 − e^(−kτ))     ⇒    A = total information content
                                      t50 = ln(2) / k

`A` = how much of the news was in the price at all. `t50` = diffusion half-life in
days. The fraction of `A` not incorporated by day +1 is the post-earnings
announcement drift, and it is the most tradeable number in the set. Method
reference: Kothari & Warner (2007). Event-study skeleton per firm:
`AR(i,τ) = R(i,τ) − (α̂_i + β̂_i·R_m,τ)`, `CAR_i(T) = Σ_{τ=0}^{T} AR(i,τ)`.

**(d) Causal vs correlational.** Contemporaneous news/return correlation is mostly
noise and reverse causality. Engelberg & Parsons (2011) and Da/Engelberg/Gao
(2011) use exogenous variation in news exposure. **Without an instrument, label
results predictive, not causal.** Do not overclaim.

**Mechanism check.** News moves prices through order-book imbalance, not directly.
Chordia, Roll & Subrahmanyam (2002). If news variables only work in liquid names,
the study is measuring impact via the order book, not information content.

**Two failure modes that invalidate results regardless of model choice:**

1. **Point-in-time timestamps.** If a "2026-09-28" filing hit the wire at 18:40
   after close, its return belongs to the next day. Misassignment smears the whole
   diffusion curve. This is the binding constraint on everything above — more
   important than any estimator choice.
2. **Multiple testing.** 200 news categories × 500 stocks manufactures significance.
   Apply Benjamini–Hochberg FDR, and cluster standard errors by firm (announcement
   dates cluster on accounting-calendar dates and inflate t-stats badly).

---

## 7. Data inventory — the real blocker

Full scout report: `agent://DataInventory` (may expire; the substance is here).

**The problem is not missing sources. It is that the timestamp layer is broken at
the root, and every diffusion study is invalid until it is fixed.** You cannot chunk
your way out of wrong dates: a clean pgvector index over a corpus where 99% of
concall timestamps are wrong answers confidently and is systematically wrong —
worse than no index, because it passes the eyeball test.

| Corpus | Rows | Verdict |
|---|---|---|
| Concall transcripts | 18,516 | **0.9% of dates correct.** Median **858 days** late vs BSE feed. Stored dates are crawl dates. |
| Annual reports | 26,614 | `event_source='doc_date'` on 100%. Dates span two crawl days. |
| Quarterly financials | 15,261 | **No `filing_date` column at all.** `source=yfinance`, fetch-time only. 2023 missing entirely. |
| Investor presentations | 1,615 | Crawl-dated until joined — **but trial showed 10/10 match by PDF filename.** Join is tractable. |

**Repair work already exists and is UNAPPLIED:** `analysis/proposed_changes.csv`,
**7,019 rows** (re-probed at close), columns `corp_id, symbol, field,
current_value, proposed_value, event_source_proposed, date_tier, quarter`.
Snapshot to diff against: `analysis/snapshot_before_dates.jsonl`.

**Present and good:**

| Asset | Coverage |
|---|---|
| Daily OHLCV + delivery | 2021-10-27 → 2026-09-24, **5,706 symbols, 1,269 sessions, ~3.12M rows** (`equity_intelligence.db:daily_price_delivery`, 31.1GB DB) |
| Bhavcopy raw CSVs | ~1,601 files, same span (`reality_engine/data/bhavcopy/`) |
| Master symbols/ISIN | 6,445 rows — but **5,945 have NULL/Other sector**; `is_nifty*` is today's flag with no history |
| Corporate actions | 8,535 rows, 2023-01-02 → 2026-08-28, **no delistings in feed** |

**ABSENT — no table, no schema, no fetcher script, zero repo hits:**

- Order-book / brokerage reports (only derived prose `order_book_metrics`, ~3,474, stamped Aug–Sep 2026)
- Bank monthly business updates
- **Vahan 2W/3W chassis sales** — grep for `vahan|chassis` repo-wide returns nothing
- AMC / MF flows
- NSDL FII sector-level flows (only an `fii_holding_pct` snapshot column)

Five of the user's named sources do not exist in the repo in any form. If any are
in scope for Thursday, that is the item most likely to slip.

**Sector-coverage gap, flagged separately** because it bites the I-share and every
cross-sectional regression: 5,945/6,445 symbols have NULL sector and nifty flags
have no point-in-time history. Sector controls do not exist yet. Fixable, not free.

---

## 8. Open items and next actions

**Blocking on a user answer — the deadline reading.** Two readings of Thursday,
and they imply very different work:

- (A) Deadline is driven by **the testing strategies**, not the full source list.
  → Achievable: the price-side study (I-share, lag profiles, t50) on annual reports
  and presentations, whose join is already proven. Concalls excluded until repaired.
  A real result rather than a thin one.
- (B) Deadline requires **all named sources**.
  → Not achievable. Five sources are greenfield, and the PIT repair is days of work.

**Also open:** whether the five absent sources are in or out of scope.

**Recommended sequence, pending the above answer:**

1. Apply the 7,019-row PIT repair from `analysis/proposed_changes.csv`. Everything
   else queues behind it. *(Prerequisite for all diffusion work.)*
2. Extend the proven presentation join to concalls and annual reports.
3. Then run the price-side study — it needs only PIT timestamps plus the 3.12M-row
   price table already on disk.
4. Text-side study queues behind (1).
5. Greenfield sources last, if in scope at all.

**Unresolved config ambiguity:** the `extendedContext` + 160k interaction (§3), and
the two declined settings (§3). Ask in plain text; do not auto-retry.

---

## 9. Standing rules / scars

- **Never present an unsourced number as an estimate.** The t50 figure is the scar
  from this session. Fit parameters, or label them explicitly as guesses.
- **Cite only what was verified.** Every citation above was checked against
  sources in this session. Fabricated attributions are worse than no citation,
  because the user intends to build tests on them.
- **Audit timestamp provenance before any cross-sectional study.** `doc_date` is
  crawl-date-stamped across the document corpus; the PIT audit in
  `tasks/PIT_LABEL_AUDIT_2026-09-29.md` is the root-cause writeup.
- **Multi-venue knowledge is in skills, not the repo.** Concall-date extraction
  (`reality-engine-concall-date-extraction`), BSE Reg-30 dissemination timestamps
  (`bse-announcement-pit-timestamps`), crawl-date correction
  (`reality-engine-crawl-date-correction`) are managed skills — read them before
  re-deriving any of this.
