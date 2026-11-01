# Query layer v4 — factored concept registry, one executor, a discovery layer

## v4.2 changes (30 Oct 2026, evening) — the answers, the re-triage and the GPU result

This revision is binding and supersedes v4.1 where the two disagree. Every row names the
decision, the sections it changed, and the artifact that carries the measurement.

| # | decision (Shivam, 30 Oct 2026 evening) | where this document changed | evidence |
|---|---|---|---|
| 1 | **Label gate = option (b).** ≥95% of the *head* surfaces carry an exact label, hand-checked at ≥95% precision. Option (a) is removed, not ranked second | §A.9 (gate restated, (a) struck), §H.8; the question is deleted from "Open questions" | `VOCAB_PASS1.md` §4 |
| 2 | **"In-line" is a band per atom, not one number.** Each atom's band is derived at build time from the measured historical error of the `trend` estimate for that atom, stored per atom × mcap bucket in a small table and read by a lookup at query time. The fixed 2% is gone | **§A.8 (`own_estimate_band`, build + lookup)**, §H.7 | the table itself, re-measured on each rebuild |
| 3 | **A proxy is the last resort, not a route.** Order is: search everything held (structured + raw documents) → fetch if free within a day → proxy → NOT IN DATA listing what was tried. A proxy answer must carry its `search_log` ref or it does not count as answered; the gate reports `real_answered` and `proxy_answered` separately and **only an approved proxy counts towards 95%** | **§A.6**, **§D.4 (proxy row + the four-step triage)**, **§H.5**, §E.5; the 74 proxy tickets were re-triaged | `nid_retriage.py`, `nid_search_logs/` (74 files), `nid_retriage_summary.json` |
| 4 | **Sector labels are ours, dated, and may lead NSE.** The v4.1 premise of an on-disk index-constituent archive is **false** and is corrected (3 current CSVs, no history). New step 1: an own PIT label per company from what its filings said at the time, `known_at` = filing date, with a confidence, never backcast before its first supporting filing; scored against the NSE label when one later exists (agreement + lead time). Company documents are held only from 2024-04-01, so a **pilot-only** AR backfill for FY2019–FY2024 is specified (design + size estimate, **not fetched**) | §B.2, **§B.6 (step 1 rewritten, backfill spec added)**, §H.6 | this document §B.6; §B.6 verification note |
| 5 | **The §E.5 verdict rule is PENDING** and is **not approved**. Four amendments are recorded as proposals, not merged | **§E.5** (PENDING banner, `492 → 1,927 sessions`, metrics 5 & 6 in the verdict, the t < 2 bucket, fold availability, F1–F3 status) | `bench_screen.md`; the pilot store |
| 6 | **Evening-layer costs come from a dated table, never a constant.** `broker_charges(broker, segment, charge, rate, unit, cap, min, side, effective_from, source_url, checked_on)` seeded with the rate cards checked 2026-10-30. Round trip on ₹1 lakh via NSE: **Zerodha 23.8 bp, Angel One 29.3 bp**, replacing the fixed 30 bp. Slippage measured per liquidity bucket from held daily OHLC (a high-low spread estimator, labelled an estimate; no intraday data). Switch margin: after-tax improvement ≥ 1.5 × total switch cost | **§F.9.1 (new: the table, the seed rows, the seeded values)**, §F.9, **§E.5 metric 5**, §H.9 | `zerodha.com/charges`, `angelone.in/pricing` (checked 2026-10-30) |

**Also folded in.**

| item | where | what changed |
|---|---|---|
| `NID_TRIAGE.md` → work packages | **§H.5**, §H.0 | the 31 classes, their 121 build-hours and the execution order are the WP backlog; the proxy half is now governed by decision 3 and was re-searched (`nid_search_logs/`) |
| `bench_gpu.md` | **§F.5, §F.8 (rewritten from thesis to measured result)**, §F.7 | CPU for the hot path, GPU for nightly and cold, with the measured crossovers; `CUPY_CACHE_IN_MEMORY=1` in sandboxes. Open question 7 is deleted |
| False-discovery null | **§E.3, §F.1, §F.7** | the null was mis-specified (self-membership pairs left in, commodity columns used as "factors"). Three nulls measured; block permutation on the pair set with the mechanical pairs dropped is adopted |
| `bench_screen.py` | **§F.7**, `bench_screen.md` | drivers are standardised, so the screen is a **correlation** and asserts \|r\| ≤ 1; the GPU guess ("wins past ~10k entities") is replaced by the measured crossings |
| Effort in **worker-hours** | **§H.11 (new)**, every WP estimate in §H | person-days are gone. Calibrated on the 202 finished dsh workers in `plugins/dsh-worker/runtime/jobs/*/status.json` |
| The opinions store | **§A.8** | 529 raw files covering **1 of the 60 pilot ISINs**: the design now states exactly what `own.estimate` does without it instead of listing it as a method leg it will use |
| `bench_screen.py`'s defect | §F.7 | it multiplied standardised returns by raw driver levels (abs max 55,385) and called the output a correlation |

Numbers re-measured for this revision: **60 atoms, 19 dims, 13 formulas, 26 operators, 2,242
lexicon rows**, coverage **897 mapped / 150 NID / 26 unmapped** unchanged, `--check`
deterministic **PASS**. The screen benchmark was re-run after the standardisation fix.

Status: design (30 Oct 2026, v4.2). Supersedes the planner-patch line of work described in
`tasks/arch_v3/QUERY_LAYER.md`. Every number marked *(measured)* was produced by a program in
this directory: `build_concept_registry.py` (registry + coverage over the 1,073 master-bank
cases), `bench_screen.py` (timings, RAM and the false-discovery null on the pilot stores),
`vocab_pass1.py` (the document vocabulary), `nid_retriage.py` (the proxy-ticket search logs) or
`bench_gpu.py` (the CPU/GPU comparison). Numbers taken from other documents say so.

## v4.1 changes (30 Oct 2026) — Shivam's six decisions + the evening layer

This revision is binding. Each row names the decision, what changed here, and the generator
output that was re-measured.

| # | decision (30 Oct 2026) | where this document changed |
|---|---|---|
| 1 | **Consensus = our own estimates, no paid feed.** `own_estimate` per company, per atom, per period; inputs = own quarterly trend + guidance adjustment + analyst numbers from the opinions store where they exist; each estimate stores method, inputs and `known_at`; beat/miss is measured against it, and against the opinions report when one exists | §A.1 (atom table), §A.2 (`est_atom` dim), **§A.8 (new spec)**, §B.5 (migration order), §C.1 (Ask), §D.4 (answer types), §H.5 (the old `absent.consensus`/`absent.price_target` class is gone), §H.7 (build) |
| 2 | **Extraction vocabulary: exhaustive surface, few labels.** Every phrase verbatim and unbounded; ~60–80 topics in two levels sharing ids with registry atoms; facets instead of more labels; cluster the phrases, keep the smallest topic set covering ≥95%, remainder `other:<raw>`, promote a growing `other` cluster | §A.5 (two lexicons), **§A.9 (new pipeline/tables/check)**, §B.1/§B.3 (claim joins the label), §H.8, **`VOCAB_PASS1.md`** (first measured pass on the pilot: phrases, clusters, topics, 20 sample mappings) |
| 3 | **NOT IN DATA is not an answer by itself.** A typed NID is not counted as answered; triage (a) free fetch within one day → fetch job, (b) genuinely hard → labelled proxy estimate with its assumption, (c) only then NID listing what was tried. New `proxy` answer type (proxy, assumption, confidence) | §A.6 (ceiling restated), §D.4 (answer contract), **§H.5 (triage; `NID_TRIAGE.md` is the triage worker's output)**, §H.0 |
| 4 | **Sector store is not empty.** `sector_pit.db.company_sector_pit` has **482 rows**; the defect is that `valid_from` is a 2019-01-01 backcast of *today's* classification (hindsight). Specify the six-step sector build with honest effort | §B.2 (correction + the real defect), **§B.6 (new six-step build, effort per step)**, §H.6, open questions |
| 5 | **Discovery backtest is hindsight-free and runs on the pilot first.** Order: pilot backtest → Shivam approves the full schema → only then the full database | **§E.5 (new: pilot universe/window/`edge.known_at` enforcement/edge-or-no-edge metrics)**, §H.0 (order of work) |
| 6 | **GPU vs CPU is unmeasured.** Rewrite the GPU section as a thesis plus the test that decides it; assert no result | **§F.8 (rewritten)**, §H.0; the GPU benchmark worker writes `tasks/arch_v4/bench_gpu.md` |
| E | **Evening portfolio decision layer** (design-only): `portfolio_positions`, `asset_universe`, `daily_scorecard`, `recommendation_log`; nightly scoring of holdings against alternatives after tax, costs and slippage; hold/trim/switch/exit with evidence, confidence and what would change the call; the log graded on later outcomes; signals only until the strategy tests pass out of sample; holdings read-only from the brokers (official Kite MCP for Zerodha; Angel One by its export) | **§F.9 (new)**, §E.2 (link 8: the recommendation log is graded like `say_vs_do`), §H.9 |

Numbers re-measured for this revision: **60 atoms, 19 dims, 13 formulas, 26 operators, 2,242
lexicon rows** (was 61/18: the two paid-consensus atoms became one `own.estimate` atom with an
`est_atom` dim), coverage **897 mapped / 150 NID / 26 unmapped** unchanged, `--check`
deterministic **PASS**. The 150 NID are now *tickets*, not answers (§H.5).

## 0. Why v4, in one paragraph

The pilot gate when v4 was designed was **27/2,681 strict = 1.0%**; the current gate is **361/2,681 = 13.5% contract strict, 0.00% read** (`GATE_V4_2026-10-31.md`, `TRUTH_READ_GRADE_2026-10-31.md`). The failure reasons for that design-time run are almost all
*composition* failures: `GATE ask_match` 2,884, "sub-question N not addressed" 2,708,
"unrelated rows" ~1,500, and only 383 blocked + 132 NOT IN DATA (`tasks/answer_bench/
GATE_RESULTS_*_strict.jsonl`). The data is mostly there; what is missing is (a) one map from
the words a question uses to the measures the database holds, (b) a typed decomposition so
that "promoter **and** public", "NSE **and** BSE **and** the sum", "raw **and** adjusted"
become three parts that must each come back, and (c) an executor that returns exactly one
result per part. v4 makes those three things data instead of code: a registry of **60 atoms,
19 dims, 13 formulas, 26 operators and a mined lexicon**, one executor over one long-format
fact view, and a decomposer that never sees a bank field. Measured on the whole bank: **897
cases map (83.6%), 150 resolve to NOT IN DATA with the registry's stated reason (14.0%), 26
stay unmapped (2.4%)** — i.e. the registry can express **97.6%** of the bank's asks before any
data question is asked at all *(measured, §A.6)*.

That 97.6% is an **expressiveness** ceiling, not an answer rate. v4.1 (decision 3) does not
count a typed NID as answered, and v4.2 (decision 3) fixes the order in which a ticket is
worked: **search everything held** (structured stores and raw document text) → **fetch** if the
fetch is free within a day → **proxy** only after that search has failed and the controller has
reviewed the log → **NOT IN DATA** listing what was tried (§D.4, §H.5; the triage worker's list
is `tasks/arch_v4/NID_TRIAGE.md`, and the search evidence for its 74 proxy tickets is
`tasks/arch_v4/nid_search_logs/`). The re-triage found held evidence for 32 of those 74, which
is the clearest sign the proxy was sitting one step too early.

The rest of this document specifies each piece, the shapes that remove planner code, the
discovery layer that finds the 2nd/3rd-order links, the engine and the measured budget, and
the work packages with the gate gain each is expected to buy.

---

# A. Factored registry: atoms, never composed concepts

A question is `operator(atom | formula, dims, window, entity_set)`. The task's own example:
"SBICARD's YTD high in 2026, with the date, on which exchange" is **one atom**
(`price.high`), **one operator** (`max_with_date`), **one window** (`YTD 2026`) and **one
dim** (`exchange = each`). It is *not* a "yearly-high-with-date-and-exchange" concept. Bank
case MB0305 decomposes exactly that way *(measured)*:

```
Lakshmi Mills (NSE: LAKSHMIMIL) ka 2026 ka YTD high price kya tha, aur kis date ko? NSE ya BSE, exchange bhi batao.
  (1) metric=price.high  atoms=price.high,price.close  dims=exchange=NSE, lag=ytd  op=value_at
  (2) (date qualifier)                                     -> max_with_date supplies period_end
  (3) metric=price.high  dims=exchange=NSE, exchange=BSE   -> two readings of ONE atom
  (4) metric=price.high  scope=sector                      -> "which exchange" is the dim, not a concept
window: 2026-01-01..2026-10-19 ("year to date", by the existing `period_bounds`)
```

## A.1 atoms — 60 rows *(measured)*

One row per **raw measure**: `atom_id, label, kind, store, table, column, source, unit,
grain, entity_key, pit, coverage, coverage_note, synonyms`. The generated table is
`concept_registry.json["atoms"]`; the declarations are the `_ATOMS` list in
`build_concept_registry.py` (hand-checked, 60 rows).

| kind | atoms | examples |
|---|---:|---|
| `market` | 14 | `price.close`, `price.high`, `price.delivery_qty`, `price.delivery_pct`, `price.volume`, `price.traded_value`, `price.mcap`, `price.shares_out`, `price.band`, `price.rsi`, `price.sma` |
| `fundamental` | 22 | `fin.revenue`, `fin.ebitda`, `fin.pat`, `fin.eps`, `fin.book_equity`, `fin.total_debt`, `fin.cwip`, `fin.nim`, `fin.npa`, `fin.order_book`, `fin.segment_value` |
| `ownership` | 6 | `hold.pct` (holder class is a dim), `hold.pledge_pct`, `hold.fpi_limit_utilised`, `flows.net_inr`, `corp.amount_per_share` |
| `narrative` | 2 | `claim.claim` (**topic is a dim**), `text.passage` (page is a dim) |
| `macro` | 8 | `macro.policy`, `macro.claim`, `macro.commodity_close`, `macro.index_close`, `macro.flow`, `macro.oi`, `macro.etf_premium`, `macro.series` |
| `own` | 1 | `own.estimate` (**estimated atom and method are dims**, §A.8 — replaces `absent.consensus` / `absent.price_target`) |
| `absent` | 5 | `absent.intraday`, `absent.investor_holdings`, `absent.refurb_sales`, `absent.forecast`, `absent.private_terms` |

Coverage status per atom *(measured)*: **43 held**, **12 gap** (the registry knows the
measure, the pilot store does not carry it yet — listed in §H.4), **5 absent** (nothing
publishes it; the atom exists so the NOT IN DATA wording has a reason, not an apology).

Two design decisions carry most of the minimality:

1. **The narrative measures are one atom, not thirty.** `claim.claim` is
   `(topic, direction, magnitude, horizon, known_at, page_ref)` and the **topic is a dim
   value** drawn from the extraction vocabulary that already exists (`concall_facts.cc_items.
   metric`, `deck_figures.facts.metric`, `ar_facts` category). "What did management say about
   demand and margins", "key products", "control change", "auditor remuneration" are four
   topic values on one atom.
2. **Nothing derived is an atom.** Margin, growth, ratios, D/E, working-capital cycle, per-
   rupee revenue, book value per share are formulas (§A.3); ranking, change, max-with-date, a
   ripple walk are operators (§A.4). That is why 60 rows cover a 1,073-case bank. The one
   estimate-shaped row, `own.estimate`, is a *measured object* (we produce it and store its
   method, inputs and `known_at`), not a formula: it is the consensus that no free feed sells
   us (§A.8).

## A.2 dims — 19 rows *(measured)*

A dim is a qualifier that lives **on** an atom. Each row: `dim_id, values, source, default,
note`. The five the brief names plus the ones the bank actually needs:

| dim | values | why it is a dim and not a concept |
|---|---|---|
| `exchange` | NSE, BSE, each, sum | three readings of one price/delivery atom (MB0021 asks all three) |
| `basis` | raw, adjusted | adjusted = split/bonus/dividend adjusted; the same atom |
| `consolidation` | consolidated, standalone | a filing carries both; the dim picks one |
| `holder_class` | promoter, public, FII, DII, MF, insurance, retail, pledge, fpi_limit | one `hold.pct` atom, nine columns (MB0125 asks promoter **and** public) |
| `segment` | open set | from the segment note; the mix comes from `f.share_of` |
| `topic` | open set — **label ids from §A.9** (surface phrases stay verbatim in the document lexicon) | the narrative topic on `claim.claim` |
| `scope` | stock, sector, industry, index, theme, mcap_bucket, price_band, fno, market_wide | the entity_set; "which sugar companies" is a membership join |
| `doctype` | announcement, concall, deck, ar, results, pib, rbi, budget | the source class of a passage/claim |
| `flow_kind` | insider, deal, bulk, block | sign of `flows.net_inr` |
| `event_kind` | 15 values already held in `event_day0.event_kind` | the event taxonomy is data, not an atom family |
| `lag` | yoy, qoq, ytd, 1d…1y | the lag of a change/growth operator |
| `margin_kind` | ebitda, pat, operating, net | which margin `f.margin` reads |
| `npa_kind` | gross, net | one NPA atom, two columns |
| `ratio_kind` | de, pb, pe, ev_ebitda, roic, roce, roe, icr | one `f.ratio` formula, eight readings |
| `direction` | up, down, neutral | the sign a claim or a move asks about |
| `period_kind` | day, quarter, FY, event, span | the window grain, from `period_bounds` |
| `page` | numeric | "page 41 of the deck" is a dim on `text.passage` |
| `lookback` | 20, 50, 200 | the SMA length |
| `est_atom` | open set of registry atom ids | **v4.1:** the measure an `own.estimate` is for; "beat consensus revenue" is one atom plus `est_atom=fin.revenue`, never a per-measure atom family |

## A.3 formulas — 13 rows *(measured)*

Derived measures as expressions **over atoms**; never stored as data.

| id | expression | over |
|---|---|---|
| `f.margin` | `ebitda(pat) / revenue` | fin.ebitda, fin.pat, fin.revenue |
| `f.ratio` | `num/den` for de, pb, pe, ev_ebitda, roic, roce, roe, icr | debt, book equity, mcap, pat, ebitda |
| `f.dso` | `receivables / revenue * 365` | fin.receivables, fin.revenue |
| `f.working_capital_cycle` | `dso + inventory_days - payable_days` | receivables, inventory, payables, revenue |
| `f.share_of` | `part / total * 100` | segment value, revenue, holding |
| `f.net` | `a + b`, signs preserved (the NIM-gain vs treasury-loss netting in MB0772) | claim, nim, price |
| `f.per_rupee_revenue` | `Δcapex / Δrevenue` | capex, revenue |
| `f.book_value_per_share` | `book_equity / shares_out` | book equity, shares |
| `f.gap_pct` | `(open - prev_close)/prev_close` | open, close |
| `f.drawdown` | `close / max(close) - 1` | close |
| `f.cagr` | `(end/start)^(1/years) - 1` | close, revenue, pat |
| `f.excess_return` | `return(company) - return(benchmark)` | close, index |
| `f.spread` | `output price - input cost` | commodity, revenue |

## A.4 operators — 26 rows *(measured)*, one closed set

Each row: `op_id, label, params, shape, template, default_atom` (+ `rules` for `rule`). The
`default_atom` is what makes "how much did it move" or "has control changed" resolvable when
the question names the *operation* but not the measure: the operator declares the input it
reads (`pct_change -> price.close`, `control_change -> hold.pct`, …).

`value_at`, `series`, `max_with_date`, `min_with_date`, `change`, `pct_change`, `growth`,
`rank`, `screen`, `compare`, `lag_between`, `event_window_return`, `first_visible`,
`last_visible`, `zscore`, `count`, `correlate`, `aggregate`, `walk`, `rule`, `exists`,
`join_entity_set`, `threshold_cross`, `span_days`, `list_distinct`, `describe_series`.

Every template is one line and reads the fact view only:

```
value_at   SELECT value, unit, period_end, known_at FROM fact
           WHERE atom=:atom AND {dims} AND {window} AND known_at<=:as_of
rank       SELECT entity_id, value FROM fact WHERE atom=:atom AND {dims} AND {window}
           ORDER BY value DESC LIMIT :n
walk       bounded BFS over edge(driver,target), known_at<=:as_of, max_hops<=5
rule       the named rule below, returning the verdict plus the numbers it used
```

The 14 **named deterministic judgement rules** each carry their stated rule in the registry
(so a verdict is auditable, and a new judgement is one row):

| rule | stated rule |
|---|---|
| `gap_type` | gap up if `open > prev_close*1.01`; gap down if `< *0.99`; else flat |
| `breakout` | `close >= max(close, lookback)` **and** `volume >= 1.5 * mean(volume, lookback)` |
| `distribution_absorption` | absorption if `delivery_pct z > 2` and `return >= 0`; distribution if `z > 2` and `return < 0` |
| `margin_bottom` | "bottomed" if the claim direction is up after ≥2 consecutive periods of falling margin |
| `control_change` | any holder class moves ≥5pp in one quarter, or promoter falls ≥5pp |
| `solvency` | fail if pledge > 15% or interest cover < 2.5x or D/E > 1.5x (AGENTS.md §3.11) |
| `valuation_premium` | premium if `pb > 1.2 * median(peer pb)` |
| `receivables_quality` | deteriorating if `dso` rises while revenue growth ≤ 0, or `dso` +20% with falling cfo/revenue |
| `say_vs_do` | credible if the guided direction held in ≥70% of tested periods; score = hit rate with n |
| `regime_break` | broken if the out-of-sample coefficient sign flips or `|t| < 2` in the later window |
| `analog_cycle` | top-5 by standardised distance over the shared window; no hindsight on the target window |
| `dilution` | dilutive if share-count growth > pat growth + 5pp over the window |
| `golden_cross` | `sma_50` crosses above `sma_200` in the window; death cross if below |
| `support_resistance` | support = highest low of the last 60 sessions below the close; resistance = lowest high above; a "real" level needs ≥2 touches within 1% |

## A.5 lexicon — 2,242 rows *(measured)*: surface → atom | formula | dim | operator | scope | period

One surface maps to one entry. Counts by target kind *(measured)*: atom 1,056, operator 381,
claim_topic 223, formula 150, rule 134, dim 120, entity_set 104, period 74. 1,109 of the
rows are English plural/singular variants of another row (`fii`/`fiis`,
`borrowings`/`borrowing`), so the **distinct surfaces** are ~1,133; the report states both.

**Mining, as specified, and what it found.** The generator mines 1–3-grams from the 1,073
questions, normalises them, and admits a surface only when it matches a FINAL-schema column
name, a held metric key (`facts_pilot.xbrl_concept_map`, `company_metric_series`,
`company_segment_pnl`, `concall_facts.cc_items`), or a declared dim value. Result *(measured)*:
**5 mined surfaces admitted**, out of 730 that matched something. The finding is worth
stating plainly: the bank's vocabulary is financial English ("promoter", "delivery", "yield
on advances", "premium to book"), while column names are snake_case schema nouns; they barely
overlap. The registry's coverage therefore comes from the hand-declared atom synonyms and the
declared topics, and the *mining* deliverable is the opposite list — §A.7's residue and the
60 `mined_candidates` in the JSON: phrases the bank uses that the registry still lacks.

**Two lexicons, not one (v4.1 decision 2).** The table above is the **query lexicon**: the
words a *question* uses, mapped to atoms/formulas/dims/operators (2,242 rows). The words a
*document* uses are a separate, much larger object — the **surface layer** of §A.9: every
extracted phrase kept verbatim with no cap (148,652 distinct phrases for the 60 pilot
companies, measured in `VOCAB_PASS1.md`), mapped to ~60–80 **label** ids that share ids with
the registry atoms, with `other:<raw>` for the tail. Neither lexicon is mined into the other;
a bank phrase and a company's phrase are different evidence.

**Minimality rule, enforced in code:** a new entry is admitted only if a case cannot be
written with the existing ones, and an operator/formula is preferred over an atom. The
generator prints the size-vs-coverage curve that makes the rule checkable (§A.6).

## A.6 Measured coverage and the size-vs-coverage curve

From `python tasks/arch_v4/build_concept_registry.py --check` *(measured)*:

| status | cases | share | meaning |
|---|---:|---:|---|
| mapped | 897 | 83.6% | every clause resolves to an atom/formula/rule; slots filled |
| not_in_data | 150 | 14.0% | resolves, but a required atom is `absent`/`gap` → a **ticket** (§H.5), not an answer |
| unmapped | 26 | 2.4% | a clause names a measure the registry cannot express |
| **mapped + NID** | **1,047** | **97.6%** | the *expressiveness* ceiling |

**Read the third column correctly (v4.1 decision 3, tightened by v4.2 decision 3).** 97.6% says
the registry can *write down* the ask; it is not the gate's expected answer rate. A typed NID is
a to-do, and the order of work on it is fixed: **search everything held** (structured stores and
the raw document text) → **fetch** if the fetch is free within one day → **proxy** only when
both fail → **NOT IN DATA** listing what was tried. The triage output is
`tasks/arch_v4/NID_TRIAGE.md`; the search evidence behind it is `nid_search_logs/`, one file per
proxy ticket (§H.5). Until those tickets close, the honest answer rate is **83.6%** and the plan
to raise it is the ticket list, not a bigger registry.

By source bank *(measured)*: variations300 281/18/1, open300 268/18/14, reddit200
208/22/13, ripple200 171/26/3, shivam30 28/2/0 (mapped / NID / unmapped). By entity level:
stock 526/38/20, industry 163/16/2, policy 73/17/3, market-wide 85/6/4.

**Size vs coverage** — greedy set cover over clause requirements, starting from an **empty**
lexicon, each admitted entry having to match a schema column / held metric / declared surface:

| lexicon rows chosen | cases covered | coverage |
|---:|---:|---:|
| 0 | 2 | 0.2% |
| 32 | 382 | 35.6% |
| 64 | 578 | 53.9% |
| 96 | 701 | 65.3% |
| 128 | 792 | 73.8% |
| 160 | 862 | 80.3% |
| 192 | 919 | 85.6% |
| 224 | 953 | 88.8% |
| 256 | 991 | 92.4% |
| 288 | 1,029 | 95.9% |
| 320 | 1,062 | 99.0% |

**80% at 159 rows, 90% at 235, 95% at 280** *(measured)*; the curve's ceiling is 98.97%.
So *the registry size at which coverage reaches 95% is ~280 lexicon rows* — eight rows in ten
of the current 2,242 are redundant synonyms. The build phase should ship the 280-row core and
grow it only when a case fails, which is the minimality rule with a number attached.

What this measure is **not**: it is coverage of the *bank*, not of unseen wording, and it
says the registry can *express* an ask — not that the entity has the data. Per-entity coverage
is the executor's job (§D.3): a topic the company never discussed is NOT IN DATA at that
entity, with the same reason vocabulary.

## A.7 What does not map (26 cases, 2.4%) — the honest residue

| residue term | clauses | what it needs |
|---|---:|---|
| `order` (as in "in what order", "order timing") | 4 | the rank operator on the preceding parts (a decomposer fix, not an atom) |
| `capital` (capital raise / capitalised interest) | 2 | topic value on `claim.claim` |
| `market` ("what did the market do") | 2 | `pct_change` with `price.close` default |
| `issue` (objects of the issue) | 1 | topic value on `claim.claim` |
| no measure at all (judgement-only asks) | 17 | a named rule that is not declared yet — one registry row each |

Every case id is listed in `registry_coverage.md` §4.4. These 26 are **not** a data problem and
not a reason to grow atoms: 9 are decomposer refinements and 17 are named rules.

## A.8 `own.estimate` — consensus is ours (v4.1 decision 1)

No paid consensus feed. An **own estimate** is a first-class measured object with an
auditable method, stored per **(company, estimated atom, period)**; the estimated atom is the
`est_atom` dim, so "beat consensus revenue" and "target price" are the same atom read twice.

```sql
CREATE TABLE own_estimate(
  isin TEXT NOT NULL,
  est_atom TEXT NOT NULL,             -- fin.revenue | fin.pat | fin.eps | price.close | …
  period_end TEXT NOT NULL,           -- the period being estimated
  value REAL, unit TEXT,              -- one number, one unit
  method TEXT NOT NULL,               -- trend | trend_guidance | trend_guidance_opinion
  inputs_json TEXT NOT NULL,          -- the exact rows used: series refs, claim/guidance refs,
                                      -- opinions-doc refs, and the arithmetic
  n_obs INT, confidence REAL,         -- 0-1; small caps are thin, say so
  known_at TEXT NOT NULL,             -- when WE could first have computed it (PIT)
  as_of TEXT NOT NULL,                -- the information cut of the inputs
  PRIMARY KEY (isin, est_atom, period_end, as_of));
```

**Method ladder** (each step is stored, never hidden):

1. `trend` — the company's own quarterly series: a seasonal-naive plus a damped-trend
   extrapolation (last 8–12 quarters; robust to the one-off quarter by using the median of
   the last four YoY growth rates). This is the base and it always exists where the series
   does.
2. `trend_guidance` — adjustment by the company's own claims (concall/deck): a guidance claim
   is a `claim` row (§B.3) with topic = the estimated atom, `direction`, `magnitude`,
   `horizon`. The adjustment is the guided delta applied at the stated horizon, capped at
   ±1.5× the trend's own standard error; the claim refs go into `inputs_json`.
3. `trend_guidance_opinion` — where the opinions store has an analyst number for (isin,
   est_atom, period), the estimate is the analyst number, stored as-is with the report ref;
   otherwise the trend+guidance estimate stands. **The opinions store today**: no
   `opinions.db` exists; the Drive research-report inventory is
   `D:\RealityEngine\raw\user_research_drive` (529 files: 268 docx, 170 xlsx, 63 pdf, 16 mp4;
   139 company folders, 281 company files) and it covers **1 of the 60 pilot ISINs** (Tejas
   Networks). `equity_intelligence.telegram_posts` (4,527 rows, exact timestamps) is the only
   opinion-shaped store in a database. So path 3 applies to almost nothing today — which is
   exactly why the ladder is trend-first and why "thin coverage in small caps" is stated, not
   papered over.

**What `own.estimate` does with no opinions store (v4.2).** The third leg is inoperative for
59 of the 60 pilot names, so the design says what runs in its place rather than implying
coverage it does not have:

1. Every pilot estimate is `trend` or `trend_guidance`; the `method` column says which. No row
   is ever stamped `trend_guidance_opinion` for a name whose report we do not hold.
2. Beat/miss is measured against **our own** estimate. The second reading (against the
   report's number) is printed only where the store covers the name — one pilot ISIN (Tejas
   Networks) — and the answer says so in one line when it cannot be printed.
3. Consensus-shaped asks are still answered: `own.estimate` plus its method, `n_obs` and the
   §A.8 band. What cannot be claimed is the **dispersion** of the street's view, and the answer
   states that limit instead of implying a survey.
4. The gate does not treat a consensus question as better answered than a trend estimate
   deserves: the block carries `method=trend`, `n_obs` and `band_pct`, so a reader can see the
   difference between "we modelled it" and "an analyst wrote it".
5. The 529-file Drive inventory is a roadmap item, not a leg. Adding a name is one report
   parsed, linked to (isin, est_atom, period) and stamped with its `known_at`; the ladder
   already takes it where it exists, so coverage grows without a schema change.

**Beat/miss, and the in-line band per atom (v4.2 decision 2).**
`realised(atom, period) - own_estimate`, with its sign and relative size (`/ |estimate|`),
reported as `beat | miss | in-line`. **"In-line" is not one number and it is not picked by
hand.** It is `|diff| ≤ band(est_atom, mcap_bucket)`, where the band is the measured
out-of-sample error of the `trend` leg for that atom in that market-cap bucket — stored in one
small table and read by a lookup at query time. The fixed 2% this section used to carry is
gone.

```sql
CREATE TABLE own_estimate_band(
  est_atom TEXT NOT NULL,               -- fin.revenue | fin.pat | fin.eps | …
  mcap_bucket TEXT NOT NULL,            -- large | mid | small | micro (master_companies.market_cap_tier)
  n_obs INT NOT NULL,                   -- walk-forward estimates scored
  mape REAL NOT NULL,                   -- median |diff| / |realised| of the trend leg, OOS
  p75_abs_pct REAL NOT NULL,            -- the 75th percentile of that absolute error
  band_pct REAL NOT NULL,               -- what the lookup returns: p75, floored at 0.5
  fallback TEXT,                        -- 'pooled_atom' | 'pooled_all' | NULL
  measured_from TEXT NOT NULL,          -- the series, window and as_of the error was measured on
  as_of TEXT NOT NULL,
  PRIMARY KEY (est_atom, mcap_bucket, as_of));
```

The band is written by the same job that writes `own_estimate` (§H.7), from the same
walk-forward errors: for every (atom, bucket) the `trend` leg is re-run on history and scored
against what was later reported. **The band is therefore a measurement of our own estimator,
not a tolerance we hoped for.** Rule: `band_pct = p75_abs_pct`, floored at 0.5% (below that a
rounding difference is not a miss). Where `n_obs < 8` the row takes the pooled band for that
atom across buckets; where that is missing too it takes `pooled_all` and records `fallback`.
No path returns a constant — a missing band is a build defect and is printed as one.

The lookup is part of the answer, never a footnote, so a reader can check the claim:

```
in-line = |diff| <= {band_pct}%  — the p75 walk-forward error of the trend estimate for
                                   {est_atom} in the {mcap_bucket} bucket
                                   (n = {n_obs}, measured to {as_of})
```

When an opinions report exists for the name, the same arithmetic is run against that report's
number as well. Both readings are printed; they can disagree, and the answer says which store
each came from. A miss is never upgraded to a beat by a later re-estimate: `known_at` fixes
what we could have known at the time, and re-estimates are new rows with a new `as_of`.

**Coverage rule.** An `own.estimate` exists wherever the quarterly series exists (the trend
leg never needs a feed). Where it does not exist, the part is a triage ticket (§H.5), not a
silent NID: the build job is the `own_estimate` table, not a purchase.

## A.9 Document vocabulary: exhaustive surface, few labels (v4.1 decision 2)

The extraction we run ourselves keeps **every phrase**, and assigns a small number of
**labels**. Two layers, two tables, one join:

- **Surface layer (unlimited, automatic).** Every extracted phrase is stored verbatim with
  its provenance: `vocab.surface(surface_id, surface_verbatim, norm_key, source_kind, doc_id,
  isin, page_ref, known_at, occurrences)`. Nothing is dropped, nothing is normalised away:
  the phrase the company printed stays the audit trail (`Asepto total capacity target`,
  `↑ 16% on account of higher shipments`).
- **Label layer (~60–80 topics, two levels).** `vocab.label(label_id, parent_id, level,
  label, definition, registry_atoms, created_at)`; level 1 is 8 families
  (`financial_performance`, `costs_balance_sheet`, `segments_business`, `demand_orders`,
  `guidance_risk`, `people_governance`, `ownership_market`, `policy_macro`) plus
  `operations_other`; level 2 is the topic. **Ids are shared with the registry atoms**
  (`label.registry_atoms`), so a claim and the number it is about join on one id.
- **Facets, not more labels.** `direction` (`up|down|neutral`), `magnitude` (value+unit),
  `horizon` (`Q1FY27|FY27|3 years`), `certainty` (`stated|expected|aspirational`),
  `guidance_vs_fact` (`guidance|fact`) are columns on the claim row, never label values.
  The label says *what it is about*; the facets say *what was said about it*.
- **`other:<raw>` and promotion.** A surface with no label is stored as `other:<raw>` (the
  raw phrase itself), never guessed. `other` surfaces are clustered; a cluster with
  ≥20 occurrences, ≥3 companies and ≥2 document types queues for promotion, and promotion is
  one hand-edited label row with its date and evidence. A growing `other` cluster therefore
  becomes a topic; it never stays a bucket.

**How the label count is chosen (the rule, and the measured pass).** Cluster the phrases,
then pick the smallest topic set covering ≥95% of them with hand-checkable precision.
`VOCAB_PASS1.md` ran the first measured pass on the pilot's three existing extractions
(cc_items, deck metrics, AR categories; 60 ISINs, read-only):

| measured | value |
|---|---:|
| verbatim surface distinct / occurrences | 148,652 / 1,691,352 |
| surfaces carrying 95% of occurrences (the mapping workload) | 64,948 |
| topics needed for 95% with a declared vocabulary (method A) | 137 used, **64.8%** of occurrences |
| coverage at 60 / 80 topics | 62.4% / 64.1% |
| lexical clustering (no declared vocabulary) for 95% | 11,467 clusters |
| hand check on 20 sample mappings | 13/14 exact, 3 alias gaps found |

**The finding is in the numbers:** 60–80 labels is the right operating size (60 topics cover
62.4%, and the marginal topic after ~120 adds ~0), but **token matching saturates at ~65%**.
The 95% must therefore be reached by a **semantic** mapping over the 64,948 head surfaces
(§H.8), with the tail as `other:<raw>` by construction.

**The release gate (v4.2 decision 1 — option (b), the only option).** The gate is:

> **≥95% of the head surfaces carry an exact label** — one of the ~60–80 label ids, not
> `other:<raw>` — **and a 100-mapping hand sample scores ≥95% exact precision.**

The earlier alternative ("≥95% of *occurrences* are labelled **or** explicitly `other:<raw>`")
is **removed**, not ranked second: it is satisfied by construction the moment the tail is
written as `other:<raw>`, so it grades the writer rather than the mapper. Saying what was
*not* labelled, and how much of the corpus that is, are reporting duties of `VOCAB_PASS2.md`;
they are not the gate.

The full release check is in `VOCAB_PASS1.md` §4, restated under this gate: head surfaces
mapped at ≥95%; ≥95% exact precision on the 100-mapping hand sample; the `other:<raw>` share
printed per document type; label growth only by promotion (§A.9 above).

---

# B. Database shape that removes most planner code

## B.1 One long-format fact view

```sql
CREATE VIEW fact AS
  SELECT isin AS entity_id, 'price.close' AS atom_id, NULL AS dims,
         date AS period_start, date AS period_end, close AS value, 'INR' AS unit,
         known_at, 'daily_price_delivery' AS source_ref
  FROM equity_intelligence.daily_price_delivery
UNION ALL
  SELECT isin, 'fin.'||metric_key, NULL, period_end, period_end, value, unit,
         known_at, source
  FROM metric_state.company_metric_series
UNION ALL
  SELECT isin, 'hold.pct', 'holder_class=promoter', quarter_end, quarter_end,
         promoter_pct, '%', broadcast_at, 'shp_index'
  FROM equity_intelligence.shareholding
  /* … one branch per atom; 60 branches, no data copy … */
;
```

The view is the *only* read path the executor knows. `dims` is a small text map
(`'exchange=BSE;basis=adjusted'`) parsed into the WHERE clause; a dim may also be a column
(`basis`) where the source table has one. **PIT is one filter everywhere:**
`known_at <= :as_of`, inside the view's WHERE, never in Python after the fact.

Which existing tables become views, and which need columns:

| source | becomes | new columns needed |
|---|---|---|
| `daily_price_delivery`, `px_nse_adj`/`px_bse_adj` | `fact` branches (`price.*`, `basis`) | none (adjustment factors already exist) |
| `metric_state.company_metric_series` (1.06 M rows, already long) | `fact` branch (`fin.*`) | none — **but the concept map needs 11 more keys** (§H.4) |
| `company_segment_pnl` | `fact` branch + `dims.segment` | none |
| `shareholding` / `company_ownership_pit` | `fact` branch + `holder_class` | none |
| `policy_events`, `macro_claim_target`, `series_observation`, `mkt_commodity_daily`, `mkt_fii_dii_cash`, `fno_oi_daily` | `fact` branches (`macro.*`) | none |
| `event_day0` + `event_leakage_window` | **not** the fact view: the event-study engine reads them directly | none |
| `cc_items`, `deck_facts`, `ar_facts`, `chunks_v3.chunk` | new `claim` table (§B.3) + `vocab.surface`/`vocab.label` (§A.9) + `text` branch | `claim.topic` = label id; `claim.direction/magnitude/horizon/certainty` |
| `metric_state.own_estimate` (v4.1, build job §H.7) | `fact` branch (`own.estimate` + `dims.est_atom`) | the table itself |
| `index_membership`, `company_sector_pit`, `theme_map`, `company_state_daily.mcap_bucket` | new `membership` table with validity (§B.2) | `removed_on` (present), `weight` |
| `corporate_actions` / `corporate_action_class` | `fact` branch (`corp.amount_per_share`) | **build it for the pilot** (§H.4) |

No data is copied where a view will do. The one place a materialised table is right is the
fact view itself at scale (§F: partitions by atom and month), because the benchmark shows the
*panel assembly* is the real cost, not the algebra (§F.4).

## B.2 Entity-set membership, with validity dates

```sql
CREATE TABLE membership(
  entity_id TEXT, set_kind TEXT,          -- index | sector | basic_industry | theme | mcap_bucket | price_band | fno
  set_value TEXT, valid_from TEXT, valid_to TEXT,
  weight REAL, source TEXT, known_at TEXT,
  PRIMARY KEY (set_kind, set_value, entity_id, valid_from));
```

"Which sugar companies…" becomes `membership(set_kind='sector', set_value='sugar',
valid_from <= d < valid_to)` joined to the fact view. `company_membership_pit` in the pilot
already has 10,895 rows over 124 index codes and 1,888 ISINs *(measured)*.

**Correction (v4.1, decision 4).** An earlier draft of this document said the sector store is
empty. That is wrong. Re-read on 30 Oct 2026: `reality_engine/data/pilot/pilot60/sector_pit.db`
→ `company_sector_pit` has **482 rows / 482 ISINs / 28 sectors**, all
`source='nse_classification'` (the earlier "0 rows" came from reading the wrong pilot file —
the T1 build writes `company_sector_pit` into *both* `market_state_pilot.db` and
`sector_pit.db`; the file named in the old sentence was not the one the T1 build filled).

The real defect is not emptiness, it is **hindsight**: all 482 rows carry
`valid_from='2019-01-01'` and `valid_to IS NULL`, i.e. today's NSE classification is backcast
over seven years. A 2019 question answered with a 2026 label is a look-ahead leak.

**The sector build replaces the backcast with a point-in-time store — six steps, honest
effort.** Full spec and per-step estimates in §B.6.

## B.3 Typed claim table for narrative sources

```sql
CREATE TABLE claim(
  entity_id TEXT, topic TEXT,            -- a vocab.label id (level 2), never a raw phrase
  direction TEXT,                        -- up | down | neutral
  magnitude REAL, unit TEXT, horizon TEXT,
  certainty TEXT,                        -- stated | expected | aspirational
  guidance_vs_fact TEXT,                 -- guidance | fact
  quote TEXT, page_no INT, doc_id TEXT, doctype TEXT,
  surface_id INT,                        -- the verbatim phrase (§A.9), for the audit trail
  known_at TEXT, pit_conf REAL,
  FOREIGN KEY (surface_id) REFERENCES surface(surface_id));
```

Filled **at ingest** by the extraction that already runs, so a query is a lookup. The raw
phrase stays in `surface`; `topic` is the label; the facets say what was said about it:

| existing extraction | feeds `claim` | rows held |
|---|---|---:|
| `concall_facts.cc_items` (metric, direction, firmness, statement, quote) | topic = the `vocab.label` the surface maps to; direction from `direction` | 645 k |
| `deck_figures.facts` (metric, period, value) | topic = label; the deck phrase is the `surface` (§A.9) | 13.6 M |
| `ar_facts.ar_facts` (category, item, quote) | topic = label over `category`+`item` | 32.4 M |
| `policy_events` / `macro_claim_target` | policy claims and their targets | 21.6 k / 44.7 k |

This is the single biggest coverage lever in the bank: the label layer resolves "products",
"business model", "control change", "auditor", "order book", "guidance" without a new atom each
(maximum 80 labels, measured pass in `VOCAB_PASS1.md`) — and the executor's per-entity check
turns "this company never said it" into a precise triage ticket instead of a wrong number.

## B.4 Exposure edges

`edge(driver, target, origin, strength, lag, n, fdr_q, stability_by_window, label, known_at,
last_tested)` — shared by the discovery layer (§E) and the ripple `walk` operator. One table,
one quality vocabulary (`verified | measured_weak | plausible_untested | contradicted`).

## B.5 Migration order (each step independently shippable, in this order)

1. `fact` view over the tables that need no new column (market, metric series, ownership,
   macro). Everything in §D already runs on it.
2. `vocab.surface` + `vocab.label` + `vocab.map` (§A.9) over the three extractions; the head
   64,948 surfaces labelled, the tail `other:<raw>`. `claim` follows immediately, topic =
   label id.
3. `membership` from `company_membership_pit` + the **PIT sector build** (§B.6) — the
   2019-01-01 backcast is replaced, not reused.
4. `own_estimate` (§A.8) from the held quarterly series first, then guidance claims, then the
   opinions store where a report exists.
5. `claim` table backfill from `cc_items` (highest value first), then decks, then ARs.
6. `edge` table (§E) — empty at first; `walk` answers "no typed edge" until it fills.
7. `corporate_action_class` build (closes 4 of the 26 unmapped and ~10 of the NID cases).

## B.6 Sector, exposure and peer build (v4.1 decision 4)

The store today: 482 rows / 482 ISINs / 28 sectors in
`pilot/pilot60/sector_pit.db.company_sector_pit`, every row `valid_from='2019-01-01'`,
`valid_to=NULL`, `source='nse_classification'`. That is one snapshot of *today's*
classification backcast over seven years. The build below replaces it. Effort is in
**worker-hours** (§H.11), one worker-hour being one wall-clock hour of a finished dsh worker;
the numbers are estimates anchored on measured workers and are labelled as estimates.

**Step 1 — our own PIT classification from the filings, scored against NSE when NSE exists
(v4.2 decision 4).**

*The archive claim was false, and it is corrected here.* v4.1 stated that
`D:\RealityEngine\raw\index_constituents` held an on-disk archive of index constituents. That is
not true, and it is corrected here. Verified
2026-10-30: that directory holds **exactly three files, all `*_current.csv`** —
`nifty50_current.csv`, `nifty100_current.csv`, `niftymidcap150_current.csv`, written
2026-10-20. There is no dated history and no archive. Three current snapshots are the only
factual index membership we hold from that path; `company_membership_pit` (10,895 rows, 124
index codes, 1,888 ISINs) is the rest. So the build cannot be "parse the archive": the labels
have to be **ours**, derived from what each company's filings said at the time.

1a. **Own PIT label per company.** Source of truth is the company's own disclosure:
    `metric_state.company_segment_pnl` segment revenue (the dominant segment by revenue at the
    filing date) and the annual report's business description (`ar_facts` category/item at
    `dr_filed_at`). Each label row carries `valid_from = known_at = the filing date`,
    `source_ref` (doc id + page), `method` (`segment_revenue` | `ar_business_description`) and
    a **confidence** (segment share at the filing date, capped at 1.0; a two-way split scores
    lower than a dominant one). **Rule: no label may precede its first supporting filing.**
    A 2019 question gets 2019's label or `no_label` — never today's.

1b. **Score our label against NSE's, when NSE's arrives.** Where an NSE classification or
    index-constituent snapshot exists for a later date, compare our label at that date with
    NSE's and write `(agreement, lead_days)` to a `sector_label_score` row: `agreement` = exact
    sector match / the coarser NSE bucket, `lead_days` = how many days before NSE our label
    said it. That is how "our label may lead NSE" becomes a **measured** claim instead of an
    assertion, and it is the same discipline as `say_vs_do`: a classifier that is never scored
    is a guess with a schema.

1c. **Membership from factual windows only.** `valid_from` = the date the snapshot was
    published or first archived, `known_at` = that date, `removed_on` when a later file drops
    the name. Where an earlier state is unknown the row starts at the first snapshot and
    carries `pit_known=0` — never backcast to 2019.

**Step 1d — pilot-only annual-report backfill, FY2019–FY2024 (design + size only; NOT
fetched).** Without it, folds F1–F3 of §E.5 have no PIT labels: company documents are held
only from **2024-04-01**, so a decision date in 2022 can read no label and no business
description, and every filing-based edge test in those folds is unpowered.

| item | estimate (labelled: a size estimate, not a measurement) |
|---|---|
| universe | the 60 pilot ISINs, `tasks/pilot60/UNIVERSE.csv` |
| documents | 60 × 6 fiscal years ≈ **360 AR filings**, fewer where a name listed after FY19; FY24 partially held already |
| pages / bytes | ~250 pages and ~10 MB per report → ~90,000 pages, ~3.6 GB |
| extraction | text layer with PyMuPDF (~40 pages/s) for the digital majority; the scanned minority (~20%, ~72 docs) through the existing OCR path at ~1.5 s/page → ~7–8 hours of unattended CPU |
| chunks / facts | ~135,000 chunks into `document_chunks`/FTS; ~360,000 `ar_facts` rows at the current ~1,000 facts/report |
| effort | **10–14 worker-hours** (§H.11): fetch 2, parse+OCR 3 (unattended), extraction queue 4–6, QA 2 |
| scope guard | **pilot only.** The full-universe backfill is a separate decision after the pilot gate (§H.0); nothing here authorises it |

This is the one place in §B.6 where a fetch is the right answer rather than a proxy: the
documents are public, free, and the fold labels cannot be built without them.

**Step 2 — revenue-weighted multi-sector exposure from segment data.**
`metric_state.company_segment_pnl` gives segment revenue; the missing piece is a
segment-name → sector map (~28 sectors; ~400 segment strings in the pilot, hand-mapped once,
stored as `segment_sector_map`). Weight = segment revenue / total revenue for the period, with
the unallocated remainder as `unallocated`. A company is then multi-sector
(`membership.set_kind='exposure'`, `weight`), and sector screens can weight by exposure
instead of a single label. **2 worker-hours** (the segment-name → sector map is ~400 strings in the pilot, hand-mapped
once; the build and the QA are one script and one report).

**Step 3 — value-chain position: inputs and outputs (feeds `edge`).**
*Inputs* from the annual report raw-material cost shares (`ar_facts`: category/item + value,
e.g. "cost of materials consumed", with the item text as the input), *outputs* and customer
industries from segment/customer-concentration notes and the company's own product text.
Writes `edge(origin='text', driver=commodity|sector, target=isin, mechanism='input share',
strength=share, known_at=filing date)`. This is the only step whose data is sparse: cost
shares are disclosed by a minority of companies (mostly manufacturers), so coverage will be
uneven and is reported, not imputed. **3 worker-hours** (extraction rules over `ar_facts`, input names linked to commodity series,
output/customer industries, and QA — the honest risk is precision, which is why every edge
carries the quote that produced it).

**Step 4 — statistical peers from clustering factor-residual returns.**
Residualise every company's daily returns on the declared common factors (the existing
`factor_spine` + the `bench_screen.py` residualisation, measured 59 ms), then cluster the
residual-return correlation matrix per rolling window (12-month, 1-month step), storing peer
sets with `valid_from`/`known_at`. Peers are a *measured* store, never a label guess.
**2 worker-hours** (the maths already exists and is benchmarked — `bench_screen.py` times the
residualisation at 15.8 ms; the work is the rolling store, the stability check and the "refuse
when too few active features" rule `peer_graph.py` already applies).

**Step 5 — themes (thematic indices + product tags).**
Theme membership from the held index codes (thematic indices in `index_list`) plus product
tags extracted from the company's own documents; `theme_map` already has
`source='curated'|'opinion'` and the rule that an opinion theme never silently becomes
curated (architecture doc Q2). **1.5 worker-hours.**

**Step 6 — the checks that decide whether any of it ships.**
(a) **PIT validation**: every date used by a query must be ≥ the source's `known_at`; a
leakage test (query the store as of 2019-06-30 and fail if any label was first published
later) blocks the load. (b) **30-company hand sample**: one page per company showing the
label, the filing it came from, the exposure weights and the peer set; a human marks
right/wrong; ≥28/30 must pass. (c) **Coverage**: per year and per sector, the share of the
universe with a PIT label, with exposure weights, and with a peer set; the gaps are printed,
never filled. **2 worker-hours.**

*Exit checks (§B.6 step 6 runs them):* zero rows whose `known_at` precedes their source
filing; per-index membership counts on 5 sampled dates equal the held snapshot; the leakage
test (query as of 2019-06-30, fail if any label was first published later); the 30-company
hand sample.

**Total: 24–28 worker-hours** (step 1 + 1d 14–16 h, step 2 2, step 3 3, step 4 2, step 5 1.5,
step 6 2). The steps are independent after step 1, so three or four workers run steps 2–6 in
parallel and the build is one working session plus the backfill; step 1 is the gate for steps 2
and 5, and step 1d is the gate for folds F1–F3 of §E.5.

---

# C. Ask contract + text-only decomposer

## C.1 The typed Ask

```python
Ask = {
  "entities": [{"isin": str, "level": "stock|index|sector|theme|mcap_bucket|price_band|fno|market_wide|driver|policy"}],
  "as_of": "YYYY-MM-DD",                       # the PIT cut, from the question or the run date
  "windows": [{"from": date, "to": date, "basis": "named date|month|quarter end|YTD|since|as_of"}],
  "parts": [{
      "atom"|"formula": str,                   # exactly one measure per part
      "dims": {dim: value},                    # exchange, basis, holder_class, topic, scope, …
      "window": int,                           # index into windows
      "operator": str,                         # one of the 26
      "shape": "scalar|series|ranked_list|path|verdict|passage",
      "judgement": bool,                        # True -> the operator is `rule`
  }],
}
```

Ambiguity is **emitted, not guessed**: "NSE **and** BSE **plus** the combined total" is three
parts with the same atom and three dim readings; "raw and adjusted" is two parts; "promoter
and public" is two parts. The strict grader evaluates part coverage against this Ask, so an
Ask that silently picked one reading would be *visible* as a missing part.

An estimated part is explicit, never implicit: `{"atom": "own.estimate", "dims":
{"est_atom": "fin.revenue"}}` and, when the question is a beat/miss, the realised atom is a
second part. The executor returns that part with `shape="estimate"` and the method/inputs it
used (§A.8), so the reader can see whether the number is a trend, a guidance-adjusted trend,
or an analyst report.

## C.2 The decomposer (no model, no bank fields)

```
text -> clauses (split on + ; ? and lower-case "and", commas before a lower-case word)
     -> per clause: surface hits via a two-pass matcher
            pass 1 CONTENT kinds (atom, formula, claim_topic, rule, dim)
            pass 2 MODIFIER kinds (operator, period, entity_set)
          (two passes so a period phrase like "ytd high" cannot shadow the measure "high")
     -> per clause: metric = first atom | formula | topic | operator.default_atom | rule.default_atom
     -> dim-only clause inherits the case metric; an operator-only clause ("in what order")
        is a qualifier that inherits it too
     -> entity: symbol/ISIN/BSE code/company name from `security_master` in the text;
        else a scope word; else a theme stem ("X stocks/makers/players"); else a policy/driver
        entity; else the declared default (the held universe)
     -> window: the existing `period_bounds()` from reality_engine/query/router.py
```

**Bank fields are not inputs.** `template`, `family`, `chain`, `period`, `answer_kind` are read
only by the evaluator. This is the v3 defect that the gate kept punishing: the router read
`template`/`family`, which real user questions do not carry.

Known limits of the splitter, stated rather than hidden: it splits on lower-case "and", so
"CG Power and Industrial Solutions" stays one clause but "demand and margins" splits (which is
what we want); and it mis-reads a bare percentage as a fiscal year in one place (`hits 30%` →
`FY30`), which is `period_bounds`' existing behaviour, not a new defect.

## C.3 Evaluation: per-part precision/recall, no DB

The 95% end-to-end gate needs ≥97% on parts, because a case with four parts fails as a whole
if one is wrong. The evaluator is a table join, not a model:

| target | source | measure |
|---|---|---|
| part recall | `strict_subs[i].concepts` + `rubric.required_evidence` in the bank | fraction of the rubric's concepts that appear in some Ask part's atom/topic/formula |
| part precision | the same | fraction of Ask parts whose concept is in the rubric's evidence set |
| dim completeness | the question's own dim words ("promoter **and** public", "NSE **and** BSE **and** the sum") | fraction of named dim values present in the Ask |
| window correctness | `period` + `as_of` | exact match with `period_bounds`, or a stated "unresolved" |
| unmapped residue | the residue list | must be empty for a mapped case |

Run on all 1,073 cases with no DB and no network. Ship criterion: recall ≥97%, precision ≥97%,
dim completeness 100% on the dim-naming subset. Today's generator already computes the
mapping side of this *(measured: 897 mapped, 150 NID, 26 unmapped)*; the precision side needs
the rubric join, which is Work package 3.

## C.4 Twenty worked examples from failing cases

Each is a real bank case that the pilot answered wrong; the Ask is what the decomposer emits
and the fix column names the composition defect v4 removes. "NID: …" is the registry's own
reason, not an apology.

**1. MB0234 — `ARIHANT delivery 11-12 Aug nse bse`** *(stock, market)*
```
parts: [ price.delivery_pct | dims{exchange=NSE} | value_at | window=11–12 Aug 2026
         price.delivery_pct | dims{exchange=BSE} | value_at | same window ]
```
Fix: two parts, one atom. The pilot returned one exchange's figure and the gate flagged
`ask_match` on the other.

**2. MB0280 — Kotyark share count + promoter holding after a corporate action, "if the
post-action count is not held, answer NOT IN DATA"** *(stock, ownership)*
```
parts: [ price.shares_out | exchange=NSE | value_at | window=as_of
         hold.pct | holder_class=promoter | last_visible | window=as_of
         corp.amount_per_share | dims{event_kind=corporate_action} | first_visible ]   -> NID
```
Fix (v4.1): the third part is a **ticket**, not an answer: `corp.amount_per_share` is a
declared `gap`, so the triage (§H.5) routes it to the `corporate_action_class` build (a
build job, H.5b, 3–5 days) and the part stays open until it lands. Until then the block names
the missing table and the build — it is never silently answered with a wrong number, and the
gate does not count it as answered.

**3. MB0125 — `M & B Engineering (NSE: MBEL) mein public shareholding Sep 2026 tak kitni hai?
Promoter aur public dono ka percentage filing se batao.`** *(Hinglish, ownership)*
```
parts: [ hold.pct | holder_class=public  | last_visible | window=Sep 2026
         hold.pct | holder_class=promoter | last_visible | window=Sep 2026 ]
entity: symbol MBEL in text;  window: 2026-09-01..2026-09-30 (period_bounds)
```
Fix: "dono" (both) is a dim-completeness obligation. The pilot answered one class.

**4. MB0996 — Jaiprakash Power: has the debt fallen, or moved into CWIP and JVs?** *(stock,
judgement)*
```
parts: [ fin.total_debt | change | FY22–FY26
         fin.cwip       | change | FY22–FY26        -> NID (concept map lacks cwip)
         fin.investments| change | FY22–FY26        -> NID (concept map lacks investments) ]
rule:   f.net over the two legs, with `receivables_quality`-style stated arithmetic
```
Fix: this is a *composition* judgement: three parts, then `f.net`. It is NID today for a
one-row reason (the concept map), not because the balance sheet is missing.

**5. MB0003 — `544161 business + segments`** *(stock, lookup)*
```
entity: BSE code 544161 in text
parts: [ claim.claim | topic=business | last_visible
         fin.segment_value | segment=* | value_at | window=Q1FY27 ]
```
Fix: "business" is a claim topic (the AR/MD&A text), "segments" is the segment store — two
different stores, one Ask.

**6. MB0305 — Lakshmi Mills YTD high + date + exchange** — the §A example. Fix:
`max_with_date(price.high, exchange=each)` returns the value, `period_end` and the exchange.

**7. MB0021 — Ather delivery volume 13 & 14 April, "NSE + BSE combined, give NSE, BSE and the
sum per day"** *(stock, market)*
```
parts: 3 exchanges x 2 dates of price.delivery_qty  (each|sum)
```
Fix: `exchange ∈ {NSE, BSE, sum}` for each of two named dates = six results, one per part.
The pilot printed a single "delivery" row and the gate called the rest unrelated.

**8. MB0218 — `For the NIFTY SMALLCAP 100 constituents, how exposed are the members to El Nino
2026, and what did they say about handling it?`** *(index, ripple)*
```
entity_set: membership(index, 'NIFTY_SMALLCAP_100') @ as_of
parts: [ macro.series | series=el_nino | value_at | window=2026
         claim.claim | topic=risk | zscore over the entity then rank                 ]
```
Fix: the entity set is a join (membership), and "exposed" is `correlate`/`zscore`, not a new
concept.

**9. MB0366 — `Which companies announced fresh orders above Rs 1,000 crore in Q1 FY27? Include
the order value and the period of execution.`** *(market-wide, screen)*
```
parts: [ fin.order_intake | screen{value > 10000} | window=Q1FY27 | shape=ranked_list
         fin.order_intake | value_at | same entities
         claim.claim | topic=order execution period | last_visible ]
```
Fix: a screen is `screen(entity_set=market_wide, atom, cmp)`; the pilot's SCREEN planner knew
only `daily_price_delivery` columns.

**10. MB0654 — US 100%/200% tariff on generic drugs; trace through US revenue, front-loading,
capex, the CDMO that gains** *(policy, ripple)*
```
trigger: macro.policy | screen{policy_name ~ generic drug tariff} | first_visible
parts:   [ fin.revenue | dims{geography=US} | share_of | window=FY26
           fin.capex   | change | window=FY26..FY28
           walk(edge, hops<=3, known_at<=as_of) -> the CDMO node ]
```
Fix: `walk` is an operator over the exposure edges; the RIPPLE planner hard-coded five stages
and lost the CDMO leg.

**11. MB0772 — repo +25 bps: net the NIM gain against the treasury loss** *(policy, judgement)*
```
parts: [ fin.nim | change | window=2026-10-07        -> NID (concept map lacks nim)
         claim.claim | topic=bond portfolio | direction=down
         f.net(nim_gain, treasury_loss) ]
rule:  net = Δnim * loan_book - Δprice * bond_book; the rule prints both legs
```
Fix: a judgement ask with a stated rule and its two measured legs; NID is on the leg the
store lacks, and the reason names it.

**12. MB1034 — `Infosys: did the 50-day cross above the 200-day this year, and how has the
stock behaved in the 30 sessions after each cross?`** *(stock, technical)*
```
parts: [ price.sma | lookback=50  | threshold_cross(rule=golden_cross) | YTD
         price.close | event_window_return(-0,+30 sessions per cross) | YTD ]
rule:  golden_cross (stated in §A.4)
```
Fix: the technical asks are `price.sma` + `threshold_cross` + a stated rule, not a planner.

**13. MB0627 — `Which mid-cap will double in 2027?`** *(market-wide, forecast)*
```
entity_set: mcap_bucket(mid)
parts: [ price.mcap | rank | now
         absent.forecast | value_at | window=2027 ]    -> NID
```
Fix: honest NID with the registry's reason ("forecast, not a held fact") instead of an
invented ranking presented as the answer.

**14. MB0433 — FIIs bought, DIIs bought more, who absorbed the supply, did the index fall
anyway?** *(market-wide, judgement)*
```
parts: [ macro.flow | dims{flow_kind=FII} | value_at | 2026-10-23
         macro.flow | dims{flow_kind=DII} | value_at | 2026-10-23
         macro.flow | list_distinct | aggregate{sum} | the same day
         macro.index_close | change | the same day ]
```
Fix: "who absorbed" is the residual of the flow identity (`net = FII + DII + others`), stated
as arithmetic in the part, not as prose.

**15. MB0585 — `September 2026 mein FIIs ne kitna becha aur DIIs ne kitna kharida?`**
*(Hinglish, market-wide)*
```
parts: [ macro.flow | flow_kind=FII | value_at | window=2026-09
         macro.flow | flow_kind=DII | value_at | window=2026-09 ]
```
Fix: Hinglish verbs ("becha" = sold, "kharida" = bought) are lexicon entries with a sign, not
a separate planner.

**16. MB0845 — `Among listed PSU banks, which paid an interim dividend in the September
quarter, and how much per share?`** *(sector, screen)*
```
entity_set: membership(sector, 'PSU banks')
parts: [ corp.amount_per_share | screen{event_kind=dividend, ex_date in Q2FY27} | ranked_list
         corp.amount_per_share | value_at | the matched entities ]  -> NID (pilot build)
```
Fix: the sector set is a join, and the dividend amount is one atom; today the pilot has no
corporate-action store and says nothing.

**17. MB0959 — `ITC: between dividends and FMCG reinvestment, which one has earned the better
return, and what does the last five years say?`** *(stock, judgement)*
```
parts: [ corp.amount_per_share | series | FY22–FY26   (dividend leg)
         fin.capex | series | FY22–FY26               (reinvestment leg)
         f.excess_return | compare(the two legs) | FY22–FY26 ]
```
Fix: two legs plus `f.compare` — a real comparison instead of one number and an adjective.

**18. MB0611 — `If EV penetration hits 30%, which listed auto-component names lose and which
gain?`** *(theme, ripple)*
```
trigger: claim.claim | topic=ev penetration | magnitude=30% | window=hypothetical
entity_set: membership(theme, 'auto components')
parts: [ macro.series | series=ev_share | change | to the scenario level
         fin.revenue | dims{segment=EV} | share_of            -> NID if the segment note lacks it
         walk(edge, hops<=2) -> classified win/lose per entity by f.share_of ]
```
Fix: a hypothetical is a *scenario window*, and win/lose comes from the exposure share —
not from a planner that guesses.

**19. MB0011 — `Why gold stocks fell Jun–Jul 2026`** *(theme, judgement)*
```
entity_set: membership(sector, 'gold jewellery') | as_of 2026-07-31
parts: [ price.close | change | Jun–Jul 2026 | rank
         macro.commodity_close | series=gold | change | Jun–Jul 2026
         macro.policy | screen | Jun–Jul 2026
         correlate(price.close, gold, lag=0..2) over the window ]
rule:  the move is attributed to the driver with the largest measured share, and the answer
       says what was tested, not what is "probably" true
```
Fix: "why" is a bounded attribution over typed drivers with a stated test, not free text.

**20. MB1073 — `RVNL had three delivery spikes in a month with no price progress. Is that
distribution or absorption?`** *(stock, judgement)*
```
parts: [ price.delivery_pct | zscore | last month
         price.close | change | last month ]
rule:  distribution_absorption (stated: absorption if delivery z>2 and return>=0;
       distribution if z>2 and return<0)
```
Fix: the verdict comes from a rule with a stated threshold, so the grader can check the
reasoning and not just the words.

---

# D. Executor + answer contract

## D.1 One executor

```
execute(part, as_of) -> Result            # exactly one per part, always
  Result = {part_index, atom, dims, window, unit, value(s), period, isin,
            source_ref, known_at, shape, answer_type,   # measured | estimate | proxy | not_in_data
            method?, inputs?, confidence?,               # estimate / proxy
            rule_used?, verdict?, nid_reason?, tried?}
```

It is one function: operator template + `WHERE` on `fact`, with `known_at <= as_of` and the
part's dims bound as parameters. It returns **one** result object per part — a value, a list of
ranked entities, a series, a path, or a verdict — never "some rows, let the assembler sort it
out". That single rule is what kills the "unrelated rows" failure class (~1,500 findings): a
row that is not a part's result has nowhere to come from.

## D.2 Special engines (each small, each a stored table)

| engine | what it does | reads |
|---|---|---|
| **text/claim lookup** | topic → the company's own claim rows, PIT-filtered, with quote/page | `claim`, `chunks_v3.chunk` |
| **graph walk** | trigger → exposure → transmission, ≤5 hops, typed edges only | `edge` |
| **event study** | session-0 mapping (15:30 rule), abnormal return over [−k,+n], delivery z | `event_day0`, `event_leakage_window` |
| **discovery** | not a query engine: the §E search runs offline and writes `edge`/`path` | — |

## D.3 The eight planners → what is deleted, what survives

| v3 planner | v4 |
|---|---|
| RESOLVE | survives as the resolve stage: symbol/ISIN/name → canonical, PIT by `symbol_isin_history` |
| FACTS | **deleted as a planner** — `value_at`/`series` over `fact` |
| SERIES | deleted — `series`/`describe_series` over `fact` |
| SCREEN | deleted — `screen`/`rank` + `membership` |
| COMPARE | deleted — `compare` over an entity set |
| EVENT | survives as the event-study engine (it has its own PIT 15:30 rule) |
| RIPPLE | survives as the `walk` operator over `edge` (only the ≤5-hop budget and the stop-at-the-gap rule survive) |
| EVIDENCE | survives as the claim/text lookup |
| router (`template`/`family`/chain) | **deleted**: the decomposer reads the question, the Ask is the contract |
| `gate.asked_concepts` heuristics | **deleted**: the Ask *is* the list of asked concepts |
| answer assembler | becomes the renderer (§D.4); the LLM no longer formats numbers |

## D.4 Renderer and the answer contract (v4.1 decision 3)

Every part returns exactly one block, and the block's **type** is part of the contract. A
typed NOT IN DATA is **not** an answered part, and — v4.2 decision 3 — a proxy is not an
unqualified yes either. The gate keeps **two counters**:

| counter | counts | what it is allowed to claim |
|---|---|---|
| `real_answered` | `measured` + `estimate` | the answer the data supports |
| `proxy_answered` | `proxy` blocks **carrying an approved `search_log` ref** | a bridge, with its assumption on the page |
| (not counted) | `proxy` without a `search_log`, and `not_in_data` | a ticket |

`proxy` blocks never stand in for the headline number: the 95% gate is evaluated on
`real_answered`, and a proxy is reported next to it as a separate figure with its approval
state. Only an **approved** proxy counts towards the 95%; an unapproved one is visible debt.

| type | when | block fields |
|---|---|---|
| `measured` | the fact is held and PIT-filtered | value, unit, period, entity/ISIN, source table, `known_at` |
| `estimate` | `own.estimate` (§A.8) | value, unit, period, entity, **method** (`trend`/`trend_guidance`/`trend_guidance_opinion`), the inputs (series refs, guidance refs, opinions-doc refs), confidence, `known_at` |
| `proxy` | the datum is not held **and** an exhaustive logged search of the raw data has failed **and** the controller (Opus) has reviewed that log | the **proxy**, the **assumption** (the stated bridge from proxy to answer, with the arithmetic), the **confidence** in [0,1], the sources used, **`search_log`** (the ref into `nid_search_logs/` or the run's own log), and **`approved_by`** |
| `not_in_data` | only after triage (decision 3c) | `NOT IN DATA: <the fact> — Tried: <fetches attempted, with dates> — Checked: <stores, rows after PIT> — Why: <the registry's reason> — To close: <the exact table/fetch>` |

`proxy` is a labelled bridge, never a route: the block must state the proxy, the assumption
that makes it informative, a confidence in [0,1], and the `search_log` that proves we looked
first. A proxy whose assumption cannot be written down is a ticket. **A proxy with no
`search_log` ref does not count as answered at all** — in the gate, in the report, or in the
figure quoted to Shivam.

**NID triage — four steps, in this order, binding (v4.2 decision 3).** The per-case list is
`tasks/arch_v4/NID_TRIAGE.md`; the search evidence for the proxy tickets is
`tasks/arch_v4/nid_search_logs/` (one file per ticket, produced by `nid_retriage.py`).

1. **Search everything held.** Every structured store the class needs (`results_xbrl`,
   `ar_facts`, `concall_facts`, `deck_figures`, `metric_state`, the market tables) *and* the
   raw document text (the query layer's own `doc_find`, plus the FTS index it falls back to),
   scoped to the entity when the question names one. The search writes what it looked for,
   where it looked, and its top hits. **This step is not optional and it is not a formality:**
   18 of the 74 proxy tickets returned held structured rows on the first pass, and every one of
   them had already been labelled "not published".
2. **Fetch, if the fetch is free within one day** (NSE/BSE archive, a filed PDF, an index
   constituent file). The part stays open with the fetch job's id. A day's fetch beats a
   lifetime of proxy.
3. **Proxy** — only when 1 and 2 failed. Answer from a bridge over held sources, labelled
   `proxy` with its assumption, confidence and `search_log` ref, and **approved by the
   controller** after reviewing that log (e.g. "investor-wise holding" → the FCRA/EPT-2
   footpath is not held; proxy = the shareholding pattern's institution totals, assumption =
   the institution total bounds the name-level position, confidence 0.4).
4. **NOT IN DATA** — only when 1, 2 and 3 are exhausted: list what was tried. That list is the
   evidence the gate needs; "we don't have it" alone is not.

The order matters because it inverts the default. Before v4.2 the proxy sat at step 2 and
collected half the NID cases; a proxy is now the *last* thing tried, and it costs a logged
search and a review to reach.

The LLM runs **after** the blocks exist and only: (a) writes the prose that connects the
parts, (b) names the connections it sees between parts, (c) suggests what to look at next.
It never sets a number, never promotes a link, never chooses an entity. The strict grader
checks part coverage against the Ask directly, so the renderer cannot lose a part and the LLM
cannot invent one.

---

# E. Discovery layer: 2nd/3rd-order links people miss

The same atoms, run as a **search** instead of a fixed plan.

## E.1 Four tables

```sql
edge(driver, target, origin,            -- measured | text | llm_proposed
     strength, lag, n, fdr_q, stability_by_window,
     label,                             -- verified | measured_weak | plausible_untested | contradicted
     known_at,           -- the day the link became knowable -> discovery can be backtested
     last_tested, mechanism, evidence_ref);
attention(entity|topic, day, mention_count, source_kind, known_at);
hypothesis(proposed_link, proposer, required_test, status, created_at);   -- feeds HYPOTHESIS_REGISTER.md
reaction_lag(event_id, hop, entity, first_price_response_day, days_late, known_at);
```

Nothing is dropped: a link that fails FDR stays visible as `measured_weak` or `contradicted`
with its numbers. The grey area is the product.

## E.2 The eight mechanisms

1. **Measured links** — residualised driver series × company atoms, lagged 0–20 days, in-sample
   fit and out-of-sample check. Writes `edge(origin='measured')`.
2. **Paths** — sparse matrix powers of the weighted, lagged edge matrix (`A²`, `A³`), pruned
   below a threshold after each multiply; a path is kept only if every hop has a mechanism
   (`edge.mechanism` non-null) and a `known_at`.
3. **Attention gap** — `attention` per entity/topic from our own documents; rank a path by
   impact ÷ attention. "High impact, low attention" is the miss list.
4. **Reaction lag per hop** — `reaction_lag`: does hop-2 reprice later than hop-1? This is the
   diffusion study (`tasks/PRICE_SIDE_DIFFUSION_STUDY_2026-10-03.md`) run per hop instead of
   per event.
5. **Say-vs-do** — `claim` vs the later actual atom, giving a management credibility score
   (the `say_vs_do` rule with n and a hit rate).
6. **Edge breaks / regime change** — the later window's coefficient sign or `|t|` against the
   earlier window (`regime_break`); the edge stays with `label='contradicted'`.
7. **Analog search** — nearest past cycle over the shared atoms, no hindsight on the target
   window (`analog_cycle`).
8. **Recommendation grading** (v4.1 evening layer, §F.9) — every recommendation the evening
   layer issues is a claim with a horizon and a measurable outcome; it is graded exactly like
   `say_vs_do` (hit rate with n, on later realised atoms), so the discovery layer and the
   portfolio layer share one credibility vocabulary and one grader.

## E.3 Guards (non-negotiable)

- **FDR correction** across all tests at once (Benjamini–Hochberg), not per look — **and the
  null that sets it is the block-permutation null, not 1/√T** (v4.2). Measured on the pilot
  panel (§F.7, `bench_screen.md` §5): with 492 sessions and 133,386 pairs, max \|corr\| under no
  relationship is **0.393 (median) / 0.499 (max)** by circular-shift block permutation, against
  **0.205** for the textbook per-pair permutation. A forward-filled monthly commodity series is
  autocorrelated, so a shuffle of the whole driver row is the only null that prices the
  accidental lag alignment the screen actually explores; using the per-pair number would
  declare roughly twice as many links as there is evidence for, and using 1/√T would declare
  all of them.
- **Mechanical pairs are not tested.** A company and the index-group mean it belongs to are
  related by arithmetic, not by a discoverable link: 4,206 such pairs on the pilot. They are
  excluded from the test set before FDR, not "controlled for" after. Measured on those pairs
  alone: max \|corr\| **0.501** when the leading commodity columns were used as the factors and
  **0.003** once the market and index-group means are the factors — which is also the fix to
  the residualisation itself (§F.1).
- **Out-of-sample**: the later window is never used to fit the earlier one.
- **A mechanism is required for `verified`**: a typed path (`edge.mechanism`), not correlation.
- **Every edge carries `known_at`**, so a discovery backtest cannot use hindsight.
- **Cost gate**: only pairs connected by a typed link get the expensive test; the cheap screen
  still sees everything, so a strange factor can enter the grey area only through FDR.

## E.4 Proposed discovery questions for the bank (~20, proposal only — Shivam approves)

1. Which hop-2 suppliers repriced more than 5 sessions after a hop-1 customer's order win?
2. For every commodity shock >2σ, which listed buyers moved last?
3. Which companies' own guidance has been right 3+ times in a row (say-vs-do ≥70%)?
4. Which edges worked in FY22–FY24 and broke in FY25–FY26?
5. Which theme's members have the highest impact but the lowest document attention?
6. Which second-order beneficiaries of a PLI scheme have no analyst coverage in our document set?
7. Which supplier-customer pairs are named in the filings but never in a broker note?
8. Which company's capex announcement preceded its supplier's order-book jump by 1–2 quarters?
9. Which banks' NIM moved before the repo change (leakage) and by how many days?
10. Which stocks react to a peer's result before their own?
11. Which import-heavy companies have a tariff exposure that is not in their own disclosure?
12. Which past cycle is the current one closest to, on the six atoms that explain 80% of the
    sector's moves?
13. Which edges are contradicted by the out-of-sample window but still traded on in the notes?
14. Which government policy targets a theme where every listed member's revenue share is <5%?
15. Which hops in the ripple chain have no measurable price response at all?
16. Which companies' pledge events preceded a delivery spike by ≤3 sessions?
17. Which sector aggregates lead their constituents, and which lag them?
18. Which claim topic appears in the AR but never in a concall (forward-looking vs backward)?
19. Which coalitions of drivers explain a stock's last 12 moves better than its sector?
20. Which links are knowable only from a document we hold but never quote?

## E.5 Pilot discovery backtest (v4.1 decision 5) — **PENDING Shivam's answer**

> **STATUS: PENDING — this verdict rule is NOT approved.** It is the only open question left in
> this document. Everything below the banner except the four *proposed amendments* is the v4.1
> rule unchanged and stays binding for the machinery work; the proposals are recorded so the
> build workers can see where the rule is expected to move, and **no worker may apply them as
> if they were approved**. Until Shivam answers, the pilot backtest runs the v4.1 rule as
> written and reports the proposed metrics **alongside** the verdict, clearly labelled.

**Order of work, binding:** pilot backtest → Shivam approves the full schema → only then the
full database. Nothing in §E/§F is built at full scale before the pilot backtest has run and
been reviewed. The pilot backtest is a *machinery test* (does a hindsight-free discovery
process produce stable, measurable links on 60 names?), not a claim that an edge exists.

**Inputs (all held, read-only):** `market_state_pilot.company_state_daily` — the store holds
**1,927 sessions, 2019-01-01..2026-10-19** (v4.1 said "492 sessions": that is only the window
`bench_screen.py --days 730` reads for its timing run, not the store's coverage) — the pilot
`company_membership_pit`/`company_sector_pit` (§B.6), the pilot claims (§A.9), and the per-edge
statistics from `bench_screen.py`'s residualisation. No network, no paid call.

**Universe.** The 60 pilot ISINs (`tasks/pilot60/UNIVERSE.csv`), restricted at each fold to
names with a PIT sector label, ≥200 traded sessions and a non-quarantined price series
(expected ~55 of 60). Membership is evaluated at the fold's decision date, never today's.

**Window (fixed before the first run, no peeking).** Monthly decision dates, one-year
non-overlapping folds:

| fold | fit (edges estimated) | test (edges scored) |
|---|---|---|
| F1 | 2019-01 .. 2021-12 | 2022-01 .. 2022-12 |
| F2 | 2019-01 .. 2022-12 | 2023-01 .. 2023-12 |
| F3 | 2019-01 .. 2023-12 | 2024-01 .. 2024-12 |
| F4 | 2019-01 .. 2024-12 | 2025-01 .. 2025-12 |

2026 is the **holdout**: it is not read by the backtest at all until the machinery passes
(the pilot store's last session is 2026-09/10). Forward returns: 1, 3 and 6 months, computed
with the existing executable-price rule (`harness/execution.py` semantics: no stale quote at
either endpoint).

**How `edge.known_at` is enforced (the mechanism, not a promise).**
1. A fold has one decision date `t` (the last session of the fit window). The edge loader is
   run with `as_of = t`: `WHERE known_at <= t` is in the SQL, the same way the fact view does
   it — not a Python filter afterwards.
2. The edge's feature inputs may not carry a value whose `known_at` > `t`; a value with
   `period_end` after `t` is allowed only if it was published before `t` (a period label is
   not a publication).
3. A **replay check**: running the loader twice, once on the full store and once on a copy
   physically truncated to `known_at <= t`, must produce the same edge set (same rows, same
   strengths) — that is the test that hindsight did not leak in through a join.
4. The test window's returns are never used to fit, normalise or select an edge; only to
   score the edges that existed at `t`.

**Metrics that decide "edge / no edge" (declared before the run).** For each candidate edge
and for the aggregate edge set, at each fold:

| # | metric | passes when |
|---|---|---|
| 1 | out-of-sample rank IC (edge score vs forward residual return), monthly cross-sections | mean IC > 0 and IC t-stat ≥ 2 after BH-FDR across all tests |
| 2 | sign hit rate of the top-decile call, per fold | ≥ 55% over ≥ 36 monthly observations in total |
| 3 | FDR | BH q ≤ 0.10 across every edge test in the fold, not per look |
| 4 | fold stability | sign and \|t\| ≥ 2 retained in ≥ 3 of 4 folds |
| 5 | economic | top-decile minus bottom-decile residual spread ≥ 1.5 × the round-trip cost **read from the dated cost table, `broker_charges` (§F.9.1)** — not a constant: 23.8 bp Zerodha / 29.3 bp Angel One on ₹1 lakh via NSE at the 2026-10-30 rates, plus the slippage of the liquidity bucket — before tax; the after-tax version is reported alongside |
| 6 | decay | no edge whose OOS IC falls > 50% versus its in-sample IC |

**Proposed amendments (30 Oct 2026) — recorded, NOT approved, NOT applied.**

1. **Metrics 5 and 6 join the verdict.** As the rule stands, `economic` and `decay` are
   declared and then ignored by the verdict: an edge can pass on IC, hit rate and fold
   stability while costing more to trade than it earns, or while its out-of-sample IC has
   collapsed against its in-sample IC. Proposal: an edge is `edge` only if 1 **and** 2 **and**
   4 **and** 5 **and** 6 pass; 3 stays the error control. Cost of the change: some current
   passes become `no edge`, which is the point.
2. **An adequately powered candidate with IC > 0 but t < 2 is `no edge`, not silence.** The
   rule has a bucket for "IC ≤ 0 or sign flipped" (`no edge`) and a bucket for "underpowered"
   (`inconclusive`), and nothing for the case that actually dominates a 60-name pilot: enough
   months, positive IC, and not enough t to claim it. Proposal: that case is `no edge` — it
   cannot enter the hot tier and it must not be reported as "inconclusive", which reads as
   "try again later" and is how a null result survives forever.
3. **The window is not 492 sessions.** The store holds **1,927 sessions, 2019-01-01..2026-10-19**
   (§E.5 inputs, corrected above); the fold table already spends 2019-01..2025-12 on fit and
   test and keeps 2026 as holdout. The amendment is to state the coverage once, at the store,
   and let every fold read from it — the 492 figure was a benchmark window that leaked into
   the backtest spec.
4. **Which folds can test filing-based edges, and what happens with fewer than four.**
   Company documents are held only from **2024-04-01**, so a decision date before mid-2024 can
   read no filing-based label or description; §B.6 step 1d (the pilot-only AR backfill for
   FY2019–FY2024, 10–14 worker-hours) is what makes F1–F3 usable at all. Proposal, in this
   order: (a) run F1–F3 on price/membership edges only, and say so per fold; (b) run F4
   (fit 2019-01..2024-12 → test 2025) on filing-based edges, which is the fold the backfill
   actually unlocks; (c) if the backfill is not approved, **metric 4 becomes "≥ 2 of the
   available folds"** with the shortfall named in the report, and a candidate tested in fewer
   than two folds is `inconclusive` by definition — never `edge` on one fold.

**Verdict rule.** An edge is `edge` only if 1 **and** 2 **and** 4 pass (3 is the error control
that makes 1 credible); it is `no edge` if the OOS IC is ≤ 0 or the sign flips, and it is
`inconclusive` if the tests are underpowered (n < 36 months or a fold's universe < 30 names).
Every candidate is reported with its count of tests, so the multiple-testing bill is visible.
A "no edge" result is a result: the pilot is 60 names and 28 sectors, so the honest expected
outcome is that most edges are inconclusive — the purpose is to prove the machinery and to
find the handful that survive, not to force a verdict.

The pilot backtest report is `tasks/arch_v4/PILOT_BACKTEST.md` (built by the backtest worker
on this specification); it is the document Shivam reviews before the full schema is approved
(§H.0).

---

# F. Engine: fast at scale as data keeps arriving

## F.1 Factor stripping first

Residualise every company series on the **declared common factors — the equal-weight market and
the index-group means** — **before** testing any link. (v4.2: `bench_screen.py` used to pass the
leading *commodity* columns as the "20 given factors" because they come first in the matrix.
That is backwards: a commodity level is a driver, and stripping drivers out of the panel before
testing them is how a real link disappears while a definition survives — a company and its own
group mean stayed at max \|corr\| 0.501 under the old choice and fall to 0.003 under this one.)
Correlated "n factors" collapse into a few latent ones, which is why the measured
residualisation is `O(T·N·F)` and cheap (§F.7, 14.3 ms on the pilot panel).

## F.2 Mechanism gate + hierarchy

Expensive tests run only on pairs connected by a typed link (cost share, segment mix,
supplier/customer named in text, policy target, membership). Test sector aggregates first and
drill into companies only where the sector link holds — that is the hierarchy the measured
costs allow: a company test costs ~10³ more than a sector test, and most sector tests fail.

## F.3 Shock-first walk

When a driver moves >2σ, beam-search outward from it, top-k per hop, ≤3 hops. Measured at
**5.5 ms for 3 hops, top-10** on a 2,000×500 edge matrix *(measured)*, so the walk can be part
of the query path, not a nightly batch.

## F.4 Incremental, never recompute

Per-edge running statistics (counts, sums, cross-products per lag) updated by new rows only:
measured **2.1 ms per new day for 10 lags** across 4,042 companies *(measured)*. Dirty
propagation works like a build system: a new filing marks only the dependent features, edges
and paths stale; a data-quality check must pass before anything is marked stale (§G).

## F.5 Three tiers, with the budgets the measurements actually support

| tier | when | what | device (measured, §F.8) | budget (measured basis) |
|---|---|---|---|---|
| **hot** | query time | fact-view lookups, stored edges, 3-hop beam walk | **CPU** — the walk is 5.8 ms; the one-day update is a clean CPU win (0.45× on the card), and a cold CUDA context costs 0.80 s | <2 s (measured: lookups 0.01–9.6 ms; walk 5.8 ms) |
| **warm/nightly** | nightly incremental | features, stale edges, attention, reaction lags, the daily screen and rolling windows | **GPU** — screen 4.32×, rolling 4.63× at the design size; the CPU numbers are the reference (`np.allclose` before timing) | minutes (measured CPU: residualise + 10 lags = 253 ms; +1 day = 1.8 ms/edge-set) |
| **cold** | weekly, off-peak **and only after the §E.5 pilot gate (H.0)** | full re-tests, FDR pass + block-permutation null, new candidates, link proposals, regime scan, A^k, covariance/eigen | **GPU** — permutations 14.51×, A^k 3.95×, cov+eig 5.22× | hours, capped, ordered by expected value (impact × low attention ÷ test cost) |

The tier boundary is **not** a device boundary by design: it falls where it falls because a
per-call workload pays a transfer and a sync (hot), while a pass over a resident panel amortises
them (nightly, cold). §F.8 has the numbers that made that call.

## F.6 Storage

- Fact view and features in **DuckDB/Parquet, partitioned by atom and month, append-only**
  (measured: rebuilding the panel from SQLite costs 57 s per 2.3 M rows, ~20× the whole screen —
  the screen must read one partition plus a cached returns panel, never rebuild).
- Edges, paths, hypotheses and the registry are small and hot: in-RAM sparse arrays, saved to
  disk.
- Everything hot or warm on the **C: SSD**; **D: (HDD) gets finished archives only**, written
  sequentially.

## F.7 Measured CPU benchmark (`bench_screen.py`)

Panel: **492 sessions × 4,042 companies** from `market_state_pilot.company_state_daily`
(2,296,201 rows); drivers: **33** standardised columns from held series (22 World Bank
commodities forward-filled, equal-weight market, 10 index-membership groups). numpy only,
read-only. The 492 is the `--days 730` window this benchmark reads, **not** the store's
coverage (§E.5).

| step | measured (last run) |
|---|---:|
| one lag, full screen (N×D, one BLAS gemm, true correlation) | 18.8 ms |
| ten lags | 183.7 ms |
| factor residualisation (11 declared factors: market + 10 index groups, OLS) | 14.3 ms |
| **residualise + ten lags** | **253 ms** |
| A² on 2,000×500 bipartite (20,000 typed edges, fp32) | 18.4 ms |
| A³ | 36.6 ms |
| prune below threshold after a multiply | 8.9 ms |
| shock walk, 3 hops top-10 | 5.8 ms |
| one new day, ten lags (incremental) | 1.8 ms |
| RAM peak (process RSS) | 592 MB (**the row loader**, not the maths: the panel is 7.6 MB) |

Run-to-run variance on this box is 10–30%; the exact last run is in `bench_screen.md`, which the
program rewrites each time. Extrapolation to the design size (arithmetic on the measured rate,
not a second measurement): 2,000 entities × 500 drivers × 492 days → **0.14 s per screen, 1.41 s
for ten lags**; at 4,042 entities → **0.28 s / 2.84 s**.

**Two defects were fixed in the benchmark itself (v4.2), and they matter more than the
timings.**

1. **It was not computing a correlation.** The driver matrix was built from raw held levels —
   a commodity level reaches **55,385** — and multiplied straight into a gemm against
   standardised returns, so the "screen" value was a cross-product of magnitude ~10⁴. Drivers
   are now standardised once, before the clock starts, and `screen_corr` returns a Pearson
   correlation and **asserts \|r\| ≤ 1** on every call. The timings barely move (the
   standardisation is outside the timed region); the number finally means what the design says
   it means.
2. **The false-discovery null was mis-specified**, and §E.3 carries the decision. Measured on
   this panel: observed max \|corr\| **0.411** over 133,386 pairs; **block permutation**
   (circular shift of every driver row together) gives **0.393 median / 0.465 p90 / 0.499 max**
   over 20 shuffles; **per-pair permutation** gives **0.205** over all pairs (median of 200
   draws from the t(490) null, and 0.209 on 2,000 sampled pairs × 10 real shuffles). The
   4,206 mechanical self-membership pairs are what made the old null look like noise: on those
   pairs alone max \|corr\| was **0.501** when the leading commodity columns were the "factors",
   and falls to **0.003** once the market and index-group means are. Note that the observed
   maximum (0.411) is **below** the block null's p90 — on the pilot panel nothing survives the
   honest null, which is the expected answer at 492 sessions and 60 names and is reported as a
   result rather than tuned away.

**Acceptance targets: confirmed, but the first two are far too loose.** The full daily screen
is ~253 ms (~1,200× under the 5-minute target) and the incremental update is ~1.8 ms
(~340,000× under 10 minutes). The 5-minute budget is really spent in panel assembly and feature
build, not in linear algebra, so §F.5 re-states the budgets as **hot < 2 s, warm = feature build
+ stale-edge refresh, cold = weekly batch** — and the engineering effort belongs in the fact
view's partitions and the dirty-propagation graph, not in a faster gemm.

## F.8 GPU vs CPU — measured (v4.2 decision 7; `bench_gpu.md`)

**This is a result, not a thesis.** `bench_gpu.py` ran seven workloads as **one function
parameterised by the array module**, so both columns execute the same arithmetic: fp32 on both
devices, `np.allclose` checked before any timing, median of 5 runs, GPU synchronised before the
clock stops. Machine: GTX 1050 Ti (sm_61, 4.0 GB, no TF32), CuPy 14.2 on the CUDA 12.9 runtime,
8 logical CPUs, Python 3.14.7, numpy 2.5.4.

One-time CUDA cost per process, measured: `import cupy` 0.32 s, context + first kernel compile +
first launch + sync 0.48 s → **0.80 s before the first byte of work**. One full-size transfer is
**3.29 ms up, 6.81 ms down** (7.6 MB, pageable memory). Every per-call workload has to earn that
back, and most cannot.

| tier | workload | largest measured | CPU fp32 | GPU incl. transfer | GPU/CPU | device |
|---|---|---|---:|---:|---:|---|
| hot | 3-hop shock walk | A 2000×500 | 5.29 ms | 1.93 ms | 2.75× | **tie (unstable)** |
| hot | incremental one day, 10 lags | 4,042 × 33 | 1.47 ms | 3.25 ms | 0.45× | **CPU** |
| nightly | daily screen (residualise + 10 lags) | 4,042 × 1,650 | 514 ms | 119 ms | 4.32× | **GPU** |
| nightly | rolling windows | 20 × 123 d | 546 ms | 118 ms | 4.63× | **GPU** |
| cold | permutation null | 20 shuffles | 2.65 s | 183 ms | 14.51× | **GPU** |
| cold | A^k with pruning | A 8000×8000 | 5.37 s | 1.36 s | 3.95× | **GPU** |
| cold | covariance + top-20 eigen | 4,042 × 4,042 | 7.22 s | 1.38 s | 5.22× | **GPU** |

**Crossovers, with transfer (the pessimistic case):** screen at **N = 1,024** (3.54×, and
already 13.32× at the pilot panel) — v4.1's "wins past ~10k entities" guess is off by an order
of magnitude; A^k at **500 × 125** (12.79×); rolling at **1 window** (4.77×); covariance at
**512** (3.82×); permutations at **1 shuffle** (12.15×). The shock walk crosses at 2,000 × 500
but is inside its own run-to-run spread. **No crossover** for the incremental one-day update at
any measured size.

**Decision, applied to §F.5:**

- **Hot path: CPU.** The incremental update is a clean CPU win (0.45×) and the shock walk
  cannot be awarded to either device — it synchronises three times per call on a card that is
  also driving the desktop, and measured 1.03×, 1.94× and 2.77× on three runs of the same
  script. The design's real hot path is cheaper than that walk, so the tier stays on the CPU.
- **Nightly and cold: GPU.** This contradicts v4.1, and not because of size: the screen wins
  end to end at the pilot panel already, and only a genuinely cold call (process start, upload,
  download) makes the CPU the right answer there.
- **The dividing line is not the tier — it is the unit of work.** One call pays a sync and a
  transfer each way against microseconds of arithmetic and loses; a pass over data that stays
  resident amortises them and wins. Every per-call workload loses and every resident-panel pass
  wins at the sizes that matter, which is why the rule survives a new GPU or a new workload
  without re-deriving it.

**What the fp32 comparison does and does not say.** Five of the seven rows miss the `allclose`
gate, and the attribution is on the record: on the pilot screen row, numpy's own fp32 is 8.8×
from numpy fp64 on the same output while the GPU in fp64 is 7.5e-08× from numpy fp64. The
disagreement is fp32 arithmetic on a near-zero correlation — a sum of 492 O(1) products that
cancel — not the device. The cold tier therefore keeps its permutation accounting in fp64
wherever the statistic is a near-zero value.

**Operation.**
- **Install (named, not required by the query path):** `cupy-cuda12x` on the GTX 1050 Ti. 4 GB
  is a stated ceiling: the heaviest measured workload peaked at 1,953 MB of pool inside a
  2.5 GB budget, so tiling is part of the test and not an optimisation after it.
- **`CUPY_CACHE_IN_MEMORY=1` in every sandboxed or read-only run.** The default kernel cache
  writes to `~/.cupy`; where the home directory is not writable the first kernel compile fails
  *after* the 0.32 s import, which reads as "CuPy is broken". It is not.
- The numpy path stays the reference implementation. Any GPU result passes `np.allclose`
  against it on one window **before** it is timed, and that check is part of the run, not a
  comment.
- No GPU-only feature enters the query contract either way: the hot path is SQL + stored edges
  on the CPU, exactly as §D.1 specifies.

**What `bench_gpu.md` does not measure** (carried into the open, not hidden): batching the 1,000
permutations as one gemm (it would widen the GPU margin, but it is no longer the same algorithm
on both devices); pinned memory and copy streams (would move every crossover down); fp16/tensor
cores (this card has none — this is a Pascal verdict); sustained thermals; and the panel load,
which is 46–57 s from SQLite on **either** device and remains the argument for the cached or
Parquet panel in §F.6.

## F.9 Evening portfolio decision layer (design-only, v4.1)

What it is: **after the close, score what we hold against what we could hold instead**, after
tax, costs and slippage, and emit a graded recommendation per position. It is the consumer of
the query layer, not a second intelligence stack. **Signals only until the strategy tests pass
out of sample**: until then every row says `recommendation`, never `instruction`, and a human
executes anything.

Four tables (SQLite, one writer, additive):

```sql
CREATE TABLE asset_universe(          -- stocks + the non-stock legs, one row per tradable asset
  asset_id TEXT PRIMARY KEY,          -- isin for equities; INV_CASH | LIQ_FUND | GOLD_ETF |
                                      -- SILVER_ETF | GILT_10Y | NIFTYBEES | …
  asset_class TEXT NOT NULL,          -- stock | cash | liquid_fund | gold | silver | gsec | index_etf
  tradable INTEGER NOT NULL, lot_size INT, min_ticket_inr REAL,
  tax_treatment TEXT NOT NULL,        -- equity_stcg_ltcg | debt_slab | commodity_gold | …
  broker_ref TEXT, known_at TEXT, active INTEGER NOT NULL DEFAULT 1);

CREATE TABLE portfolio_positions(     -- read-only from the brokers, never written by us
  account TEXT NOT NULL, broker TEXT NOT NULL,     -- zerodha | angelone
  asset_id TEXT NOT NULL, qty REAL, avg_cost REAL, as_of TEXT NOT NULL,
  source TEXT NOT NULL,               -- kite_mcp | angelone_export
  read_at TEXT NOT NULL,
  PRIMARY KEY (account, asset_id, as_of));

CREATE TABLE daily_scorecard(         -- the nightly scoring, one row per held/candidate asset
  date TEXT NOT NULL, asset_id TEXT NOT NULL,
  exp_return_1y REAL, exp_return_after_tax REAL,   -- the ranking quantity
  switch_cost_inr REAL, slippage_bp REAL, tax_if_sold_inr REAL,
  score REAL, rank INT, evidence_json TEXT NOT NULL, known_at TEXT NOT NULL,
  PRIMARY KEY (date, asset_id));

CREATE TABLE recommendation_log(      -- every call is a graded claim, never an order
  rec_id INTEGER PRIMARY KEY, date TEXT NOT NULL, account TEXT, asset_id TEXT,
  action TEXT NOT NULL,               -- hold | trim | switch | exit
  target_asset_id TEXT, size_pct REAL,
  evidence_json TEXT NOT NULL,        -- the scorecard rows, the atoms, the known_at of each
  confidence REAL NOT NULL,           -- 0-1, calibrated over time
  what_would_change TEXT NOT NULL,    -- the stated falsifier of this call
  status TEXT NOT NULL DEFAULT 'open',-- open | graded | superseded
  graded_at TEXT, horizon_months INT, realised_excess REAL, verdict TEXT);
```

## F.9.1 Costs, slippage and the switch margin (v4.2 decision 6)

**Costs are data, never a constant.** A fixed basis-point number in code is a bug that silently
ages: STT and stamp duty move with the Finance Act, and brokerage is a per-broker contract.
Five of the eight charges below differ between the two brokers, and two of them are capped per
order rather than scaled per rupee — so one 30 bp constant is wrong for every order size and
both brokers. Hence a dated table:

```sql
CREATE TABLE broker_charges(
  broker TEXT NOT NULL,          -- zerodha | angelone
  segment TEXT NOT NULL,         -- equity_delivery | equity_intraday | …
  charge TEXT NOT NULL,          -- brokerage | stt | exchange_txn | sebi | stamp_duty | gst | dp
  rate REAL NOT NULL,            -- 0.000307 for 0.00307%
  unit TEXT NOT NULL,            -- pct_turnover | pct_brokerage | inr_per_order | inr_per_crore | inr_per_scrip
  cap REAL,                      -- ₹20 per executed order, where the card caps
  min REAL,                      -- ₹5 per executed order, where the card floors
  side TEXT NOT NULL,            -- buy | sell | both
  effective_from TEXT NOT NULL,
  source_url TEXT NOT NULL,
  checked_on TEXT NOT NULL,      -- the day a human read the page
  status TEXT NOT NULL,          -- verified | to_confirm_from_contract_note
  PRIMARY KEY (broker, segment, charge, side, effective_from));
```

**Seed — rate cards checked 2026-10-30, equity.**

| charge | Zerodha delivery | Angel One delivery | Zerodha intraday | Angel One intraday |
|---|---|---|---|---|
| brokerage, per executed order | ₹0 | lower of ₹20 / 0.1%, min ₹5 | lower of ₹20 / 0.03% | lower of ₹20 / 0.1%, min ₹5 |
| STT | 0.1% buy + sell | same | 0.025% sell | same |
| NSE transaction | 0.00307% | 0.0030699% | 0.00307% | 0.0030699% |
| BSE transaction (groups A/B) | 0.00375% | 0.00375% | 0.00375% | 0.00375% |
| SEBI | ₹10/crore | same | same | same |
| stamp duty, buy side | 0.015% | same | 0.003% | same |
| GST | 18% on brokerage + transaction + SEBI | same | same | same |
| DP, per scrip per sell | ₹15.34 incl. GST | ₹20 + GST = ₹23.60 | none | none |

Sources: <https://zerodha.com/charges/>, <https://www.angelone.in/pricing>,
<https://www.angelone.in/exchange-transaction-charges>,
<https://www.angelone.in/news/product-updates/pricing-update-nov-2025-b2c>. Angel One's own pages
conflict — the brokerage calculator says ₹0 delivery brokerage, a support page quotes ₹59 DP for
a BSDA account — so **every Angel One row is seeded `status='to_confirm_from_contract_note'`**,
and until a contract note settles it the *higher* reading is used for a cost estimate, because
an under-estimated cost is exactly what makes a switch look good.

**Round trip on ₹1 lakh, NSE cash, delivery, buy + sell** (DP on the sell leg):

| broker | brokerage | STT | NSE txn | SEBI | stamp | GST | DP | total | bp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Zerodha | 0 | 200.00 | 6.14 | 0.20 | 15.00 | 1.14 | 15.34 | ₹237.82 | **23.8** |
| Angel One | 40.00 | 200.00 | 6.14 | 0.20 | 15.00 | 8.34 | 23.60 | ₹293.28 | **29.3** |

The fixed 30 bp is therefore replaced by this lookup wherever it was quoted (§E.5 metric 5 and
the nightly scoring below). The 5.5 bp gap between the brokers is larger than the whole economic
margin of many candidate edges, so **the broker is part of the experiment, not a footnote**.

**Slippage: measured per liquidity bucket from daily OHLC, and labelled an estimate.** No
intraday data (Shivam's earlier ruling), so the estimator is the daily high-low spread:

```
slippage_bp(bucket) = 10,000 * median over the trailing 60 sessions of  0.5 * (high - low) / close
```

The 0.5 is the "you cross half the spread" convention and it is stored in the row, not buried.
This is an **estimate of a cost we cannot observe**: a recommendation that clears its cost by
less than the estimate's own dispersion is not a recommendation. Buckets by median traded value
(> ₹50 cr, ₹10–50 cr, ₹1–10 cr, < ₹1 cr); every `daily_scorecard` row stores its `slippage_bp`
and the bucket it came from, so the number can be re-derived.

**Switch margin: after-tax improvement ≥ 1.5 × total switch cost.** Matches §E.5 metric 5 and is
non-negotiable here:

```
total switch cost = exit cost (brokerage/STT/stamp + the actual tax on the realised gain + slippage)
                  + entry cost + the alternative's own expense drag

switch only if  exp_return_after_tax(alternative) - exp_return_after_tax(held)
                 >= 1.5 * total switch cost
```

The 1.5× exists because every term in that inequality is an estimate; below it the sign of the
answer is not knowable. **A static allocation stays the benchmark**: the layer must beat its own
silence to justify existing (§F.9 guardrails).

**The nightly scoring (after close, ~21:00 IST, after the 19:35 price job).**
1. Load holdings read-only: the **official Kite MCP** for Zerodha and the **Angel One export**
   file. No order endpoints, no write scopes; a missing/stale export marks the account
   `as_of` stale and the run refuses to recommend a switch it cannot size.
2. For each asset (held and candidate), compute the expected 1-year return from the held
   atoms (the same fact view the query layer reads), then convert to **post-tax** return using
   the tax-rules table built from the enacted Gazette texts (never a hardcoded rate — the
   2026-10-19 decision) and the holding period.
3. Cost to switch = exit cost (STT/brokerage/stamp from `broker_charges` + the actual tax on
   the realised gain + slippage in bp for the liquidity bucket) + entry cost + the
   tracking/expense drag of the alternative. Both the charge rows and the slippage estimate are
   stored in the scorecard row (§F.9.1), never constants in code.
4. Rank on `exp_return_after_tax - switching cost amortised over the horizon`; a switch is
   only recommended when the improvement exceeds the cost by a margin and the confidence is
   above the calibrated threshold. Otherwise `hold` is the answer (it defaulted to hold, it
   did not fail to decide).
5. Outputs `hold | trim | switch | exit` **with evidence, confidence and what would change
   the call**. `exit` also requires the "why now" atom (the same `claim`/fact rows the query
   layer would cite), so a call is never a mood.

**The log is graded, so the layer can be believed or discarded.** Each open recommendation is
graded at 1/3/6/12 months on later outcomes: the held asset's excess return vs the benchmark
and the counterfactual (what the alternative would have done), the tax actually saved or
paid, and whether the stated `what_would_change` fired. Verdicts feed the confidence
calibration (a 0.7-confidence call must win ~70% of the time); the scorecard is the evening
twin of the `say_vs_do` rule (§E.2.8).

**Guardrails (non-negotiable).** Signals only until a portfolio-level backtest passes out of
sample (§E.5's gate, cash-only long book per `FRAMEWORK.md`); no auto-trading code path
exists; holdings are read-only; every recommendation carries the evidence ids and its
falsifier; a static allocation is always a valid alternative and the layer must beat its own
silence to justify existing.

---

# G. Maintenance

1. **Ingest is idempotent**: re-running a feed writes the same rows (natural keys + `INSERT OR
   REPLACE` on the fact view's sources); no `known_at` is ever rewritten.
2. **`known_at` is checked against the filing record on arrival** (exchange dissemination time,
   never the crawl date — the 2026-10-18 defect) and data-quality checks pass *before* anything
   is marked stale; a failed check quarantines the rows (`substrate_quarantine`) instead of
   propagating.
3. **A new atom = one registry row + one view branch**, no planner code. That is the test: if
   adding an atom needs a code change anywhere else, the design has regressed.
4. **The registry and the schema are versioned together**: `concept_registry.json` carries the
   bank sha and the schema sha it was generated from (`generated_from`), so a schema change
   that orphans an atom is visible as a diff.
5. **The gate runs the registry, not the reverse**: a case that fails and cannot be expressed
   is a *registry* bug report (one row), not a reason to add a planner branch.

---

# H. Work packages

Packages are disjoint files, each with its acceptance test. The gate-gain estimates below are
shares of the *failure-reason findings* (2,681-case run: `ask_match` 2,884, sub-question
2,708, unrelated ~1,500, blocked 383, NID 132) — they overlap, so **they do not add**.

## H.0 Order of work (v4.1, binding)

1. **Pilot first.** The pilot stores (60 ISINs) already answer the WP1–WP4 acceptance tests;
   nothing in this document is built at full scale before the pilot gate passes.
2. **Discovery pilot backtest** on the pilot universe (§E.5) → report
   `tasks/arch_v4/PILOT_BACKTEST.md`.
3. **Shivam approves the full schema** (the approved artifact is the DDL + the pilot reports:
   `registry_coverage.md`, `VOCAB_PASS1.md`, `PILOT_BACKTEST.md`, `NID_TRIAGE.md`).
4. **Only then the full database**: chunking, tagging, embedding, loading — the golden rule's
   order (AGENTS.md), unchanged.
5. The GPU decision is **made and measured** (§F.8: CPU hot path, GPU nightly and cold), so it
   no longer waits on anything; the evening layer (§F.9) stays design-only until 2–3 finish and
   additionally waits for the portfolio-level out-of-sample test.

The last two words on any disagreement: no full-scale build, and no instruction-style output,
before the pilot gate and the backtest are reviewed.

## H.1 WP1 — registry generator + lexicon (this deliverable, shipped as the baseline)

Files: `tasks/arch_v4/build_concept_registry.py`, `concept_registry.json`,
`registry_coverage.md`. Acceptance: `--check` prints coverage, sizes and the curve; deterministic
rebuild (`PASS`); 897 mapped / 150 NID / 26 unmapped.
Attacks: the *vocabulary* half of `ask_match` (a concept the answer never carried). Estimated
share: **15–25% of ask_match** (the concepts a registry row now names).

## H.2 WP2 — fact view + entity sets + vocabulary/claim/edge tables

Files: `reality_engine/query/v4/fact_view.sql`, `build_membership.py`, `build_vocab.py`,
`build_claim.py`, `build_own_estimate.py`, `build_edge_schema.py`. Acceptance: the view returns
one row per (entity, atom, period) for all 43 held atoms on the pilot; `membership` covers
1,888 ISINs / 124 index sets **from the PIT sector build (§B.6), not the 2019 backcast**;
`vocab.surface` holds the measured 148,652 pilot surfaces with 100% mapped to a label or
`other:<raw>` (`VOCAB_PASS1.md` §4); `claim` holds ≥600 k rows from `cc_items` with label ids
and facets; `own_estimate` covers the pilot's held quarterly series for the beat/miss atoms
(§A.8); a spot-check of 50 random claims against their quote.
Attacks: the "store had it but no view saw it" class — the largest block of sub-question
failures. Estimated share: **~40% of the sub-question class**.

## H.3 WP3 — decomposer + its evaluation

Files: `reality_engine/query/v4/decompose.py`, `tasks/arch_v4/eval_decomposer.py` (+ its
report). Acceptance: per-part recall ≥97%, precision ≥97%, dim completeness 100% on the
dim-naming subset, no DB. Attacks: multi-part asks ("promoter AND public", "NSE AND BSE AND
sum", "raw AND adjusted"). Estimated share: **~30% of the sub-question class** and some
`ask_match` (a part that is named cannot be silently dropped).

## H.4 WP4 — executor + answer contract + renderer + grader alignment

Files: `reality_engine/query/v4/execute.py`, `render.py`, `tasks/answer_bench/grade_v2.py`.
Acceptance: one result per part for every mapped case, each carrying its `answer_type`
(measured / estimate / proxy / not_in_data, §D.4); the renderer prints value/unit/period/
ISIN/source/`known_at`, or the estimate's method+inputs, or the proxy+assumption+confidence,
or the four-gate NID wording with what was tried; `grade_v2` scores coverage against the Ask,
counts only `measured|estimate|proxy` as answered (a typed NID is **not** an answer), and
reproduces the design-time 1.0% anchor (27/2,681; not the current gate) on the old answers (a sanity anchor). Attacks: `ask_match` by
construction (every part carries its concept) and "unrelated rows" (no part → no row).
Estimated share: **~35–45% of `ask_match` and most of the ~1,500 unrelated-row findings**.

Then **discovery/engine (§E/§F)** and the **evening layer (§F.9)**, only after the pilot gate
(H.0).

## H.5 The 150 NID are tickets — triage, not apology (v4.1 decision 3)

A typed NID is **not counted as answered** by the gate. Every one of the 150 cases goes
through `tasks/arch_v4/NID_TRIAGE.md` (a separate worker; that file is the per-case list, this
section is the policy). Measured reasons across the 150 (from `registry_coverage.md` §4.2;
a case can carry two reasons, so they do not add):

**(a) Answered by the estimate layer — no fetch, no ticket.** `own.estimate` (§A.8) covers
consensus and price-target asks: **2 cases** measured (the bank rarely says "consensus"
literally; the beat/miss framings need the estimate *atom*, not the word). Answer type
`estimate`, with method and inputs — never a typed NID.

**(b) Built from data already held — a build job, not a fetch.**

| work | cases | effort (worker-hours, §H.11) |
|---|---:|---|
| `corp.amount_per_share` → build `corporate_action_class` (the live DB has `corporate_actions`; the pilot store has no table) | 40 | 6–10 |
| banking concept keys (`loans` 23, `net_npa` 22, `nim` 13, `credit_cost` 6) → mapping rows over the XBRL concepts already held in `results_xbrl.facts` | 64 | 4–6 |
| `cwip` 2, `investments` 8, `cfo` 5 → same mapping rows | 15 | 2–4 |
| `deposits` 7, `unit_volume` 13, `price.free_float` 8 → one atom row + reader/weight coverage each | 28 | 4–8 |

**(c) Free fetch within one day → a fetch job.** This is mostly *per-entity document
coverage*: the 211-case stream. A company that never filed a concall, or whose deck is not in
the store, cannot answer a claim part however good the registry is. The fetch list is built
from one query per case — `claim(entity, topic)` and `chunks_v3.chunk(isin, doc_type)` row
counts after `known_at <= as_of`; every (entity, doc_type) with zero rows that is *filed and
free* (NSE/BSE archive) is a fetch job, not a NID. **Effort is in the stream, not in this
design.**

**(d) Genuinely hard → search first, then proxy with its assumption, then NID with what was
tried.** `absent.intraday` 14 (no free retro intraday bars → the last resort is a proxy: the
daily high-low range / close as an amplitude proxy, assumption stated, confidence low),
`absent.forecast` 4 (no forecast is a fact → a scenario, and a scenario is labelled),
`absent.refurb_sales` 2, `absent.investor_holdings` and `absent.private_terms` (rare in the
bank). Every one of these now reaches the proxy **only after** step 1 of §D.4's order has run
and its log is attached.

**The re-triage of the 74 proxy tickets (v4.2 decision 3, measured).** `nid_retriage.py` ran
the deterministic search over the held stores and the document text for all 74 cases that
`NID_TRIAGE.md` sent to a proxy, and wrote one log per ticket to `nid_search_logs/` (74 files).
Result:

| evidence found | tickets | what it means |
|---|---:|---|
| **structured rows held** | **30** | a held table already answers the class — these were filed as "not published" while the rows sat on disk |
| **the company's own document passage** | **2** | the fact is in a filing we hold, in prose |
| corpus match only | 42 | the class term exists somewhere in 2.3 M chunks; that is not evidence and is not counted |
| nothing | 0 | — |

So **32 of 74 proxy tickets show candidate real evidence** and go to step 1/2 of the triage
before any proxy is written. The 42 corpus-only tickets are the honest proxy candidates, and
each still needs the controller's review of its log. **No ticket was re-labelled by this run**;
the logs are the review material, and the worst class — `bank_transmission`, 21 tickets, 7 with
held rows — is also the largest, so the "half of the NID goes to proxy" figure was never a data
statement, it was a search that had not been run.

Per class (structured / own-document / corpus): `valuation_judgement` 9/0/2 ·
`bank_transmission` 7/0/14 · `mechanism_lag` 6/0/11 · `free_float_weight` 4/0/2 ·
`hfc_securitisation` 2/0/7 · `second_suppliers` 1/0/3 · `policy_incidence` 1/0/1 ·
`float_income` 0/2/0 · `forecast_scenario` 0/0/1 · `retail_mtm` 0/0/1.

**(e) The decision the triage produces.** For each case: `fetch(job_id)`,
`proxy(result, assumption, confidence, search_log, approved_by)` or `nid(tried[])`. The gate
keeps `real_answered` (`measured`+`estimate`) and `proxy_answered` (approved proxies only) as
**separate** numbers (§D.4); the third bucket is visible debt with an owner and an
attempted-search log. A proxy without its `search_log` counts as debt, not as an answer.

## H.6 WP6 — sector, exposure and peer build (§B.6)

Six steps, **24–28 worker-hours** (§B.6, including the 10–14 h pilot AR backfill of step 1d);
step 1 (PIT classification + membership) is the gate for steps 2 and 5. Acceptance: the leakage test fails the load if any label was first published after
the date it is used for; the 30-company hand sample passes ≥28/30; coverage is printed per
sector per year. The 2019-01-01 backcast in `company_sector_pit` is replaced, not migrated.

## H.7 WP7 — `own_estimate` build (§A.8)

Trend leg first (it needs nothing new), then the guidance adjustment from `claim` rows, then
the opinions join where a report exists. **3–4 worker-hours** (trend leg + the walk-forward
`own_estimate_band` build, guidance claims and caps, the opinions join, the beat/miss report —
one builder and one report). Acceptance: an `own_estimate` row for every (pilot ISIN,
beat/miss atom, quarter) where the series exists; an `own_estimate_band` row for every
(atom, mcap bucket) that the estimates touch, with `n_obs` and the measured `p75_abs_pct`
printed; the estimate's own out-of-sample error is measured and printed; a re-estimate never
rewrites history (new `as_of` rows only).

## H.8 WP8 — vocabulary semantic mapping + label release (§A.9, `VOCAB_PASS1.md`)

Map the 64,948 head surfaces (95% of occurrences) to the ~60–80 labels with a semantic mapper
(the local embedding index; no paid model), keep the tail as `other:<raw>`, run the 100-mapping
hand check, and promote `other` clusters that pass the promotion rule. **6–8 worker-hours**
(mapper, review of the head, the promotion queue, the re-measure as `VOCAB_PASS2.md`; the one
human-shaped step is the 100-mapping hand check, which is why the gate is precision and not
volume). Acceptance: **≥95% of the head surfaces carry an exact label** and the 100-mapping
sample scores **≥95% exact precision** (§A.9's gate, option (b)); the `other:<raw>` share is
printed per document type; every `other` cluster with ≥20 occurrences / ≥3 companies / ≥2 doc
types is in the promotion queue with its evidence.

## H.9 WP9 — evening portfolio layer (§F.9) — design-only until the gate

When built: the four tables, the `broker_charges` seed (§F.9.1), the nightly scorecard, the
recommendation log and its grader. **7–9 worker-hours** (tables + holdings readers — Kite MCP
read-only and the Angel One export; the scoring after tax, cost and slippage; the grading; the
calibration report).
Acceptance: a recommendation carries evidence, confidence and its falsifier; the log is graded
at 1/3/6/12 months; the layer emits signals only (no order path exists); a static allocation
is the benchmark it must beat before it is called useful.

## H.10 WP10 — pilot discovery backtest (§E.5)

Machinery + four folds + the report `tasks/arch_v4/PILOT_BACKTEST.md`. **5–7 worker-hours**
(the machinery exists in `bench_screen.py`, and the GPU worker's 1.58 h for seven
correctness-checked workloads is the measured anchor for "a fold loop plus a null pass"; the
work is the fold loop, the `known_at` replay check, the block-permutation null and the
write-up). Acceptance: the replay check is byte-identical; every fold's
edge set is produced with `known_at <= t` in SQL; the report states edge / no edge /
inconclusive per candidate with the test count. This report is what Shivam reviews before the
full schema (H.0).

---

## H.11 Effort in worker-hours (v4.2) — calibrated on finished workers

v4.1 quoted person-days. A person-day is a human unit and this build is not done by humans: the
work is dsh workers, each handed one brief, so the honest unit is **one wall-clock hour of one
finished worker, orientation and sandbox friction included**. The calibration is measured, not
assumed, from `plugins/dsh-worker/runtime/jobs/*/status.json` (read 2026-10-30):

| measurement | value |
|---|---:|
| jobs with a recorded start and finish | **202** |
| completed / cancelled / control_unavailable / launcher_error / lost / lease_expired | 172 / 12 / 9 / 4 / 3 / 2 |
| elapsed, median | **0.31 h** (19 min) |
| elapsed, p25 / p75 / p90 | 0.13 h / 0.75 h / 1.33 h |
| longest measured job | 5.0 h (a 23,321-deck download + parse + chunk run) |
| total worker-hours across all 202 jobs | **113.9 h** |

The arch_v4 deliverables have their own anchors, matched to their `brief.md`:

| worker | measured elapsed | what it produced |
|---|---:|---|
| the v4 design worker | **0.65 h** | the 60-atom registry generator, `concept_registry.json`, `registry_coverage.md`, the design |
| the v4.1 revision worker | **0.74 h** | this document, with six decisions folded in |
| the NID triage worker | **0.31 h** | 150 cases, 31 classes, 121 human build-hours itemised |
| the GPU benchmark worker | **1.58 h** | 7 workloads on both devices, correctness-checked, 17 KB report |

**Rule: estimate in measured deliverables, not in days.** One finished worker at 0.31–1.58 h is
the unit (p90 of the whole population is 1.33 h), so a task that is one builder plus one report
is quoted at **1.5 worker-hours**, and a multi-step build is that many steps. Where a v4.1
person-day figure survives as a cross-check, the measured ratio is **0.65–1.0 worker-hours per
person-day** — the design worker and the deck worker bracket it — and the table below uses the
conservative end, never dividing by a factor below 1.

| package | what it is | worker-hours |
|---|---|---:|
| WP1 registry + lexicon | shipped | 0.65 (measured) |
| WP2 fact view + membership + vocab/claim/edge builders | 6 builders | 6–9 |
| WP3 decomposer + evaluation | decomposer + eval + report | 3–4 |
| WP4 executor + answer contract + renderer + grader | 4 files | 4–6 |
| WP6 sector, exposure and peer build (§B.6) | 6 steps **+ the pilot AR backfill** | 24–28 |
| WP7 `own_estimate` + `own_estimate_band` (§A.8) | 1 builder + 1 report | 3–4 |
| WP8 vocabulary semantic mapping + label release (§A.9) | mapper + head review + promotion + re-measure | 6–8 |
| WP9 evening portfolio layer (§F.9, §F.9.1) | 4 tables + `broker_charges` + scorecard + grader | 7–9 |
| WP10 pilot discovery backtest (§E.5) | 4 folds + block null + report | 5–7 |
| the NID ticket backlog (§H.5) | 31 classes, 121 human build-hours restated | 18–22 |
| **total** | | **77–98 worker-hours** |

With three or four workers running disjoint briefs in parallel — §H.0 keeps §E/§F behind the
pilot gate, so the concurrency is real — that is **20–25 hours of wall clock**. The total is an
estimate built on measured workers and is labelled as one: if a package overruns its quote by
more than the p90–median spread (about 1 h), the brief was wrong, not the calibration.

---

# Open questions for Shivam

**One question is open, and it is the §E.5 verdict rule — marked PENDING in §E.5 and not
approved.** Everything else the v4.1 draft asked has been answered and written into the body:

| v4.1 question | closed by | where |
|---|---|---|
| 1. label gate, (a) or (b) | v4.2 decision 1: **(b)**, (a) removed | §A.9 |
| 2. one in-line number or per atom | v4.2 decision 2: **per atom, measured, per mcap bucket** | §A.8 |
| 3. proxy acceptability floor | v4.2 decision 3: **no floor — a proxy is the last resort and needs a `search_log` + approval** | §D.4, §H.5 |
| 4. sector-build effort and a 2021-start archive | v4.2 decision 4: **our own dated labels; the archive claim was false; the pilot AR backfill is specified** | §B.6 |
| 6. evening-layer inputs (brokers, slippage, switch margin) | v4.2 decision 6: **the `broker_charges` table, the measured slippage estimator, the 1.5× margin** | §F.9.1 |
| 7. GPU benchmark install | v4.2 decision 7: **measured; `cupy-cuda12x` on the 1050 Ti, no GPU in the query path** | §F.8 |

**The open one.**

1. **§E.5's verdict rule (PENDING).** Do you approve the v4.1 rule — an edge is `edge` only if
   metrics 1 **and** 2 **and** 4 pass, `no edge` on IC ≤ 0 or a sign flip, `inconclusive` when
   underpowered — and do you approve the **four proposed amendments** recorded in §E.5:
   (i) metrics 5 (economic) and 6 (decay) join the verdict; (ii) an adequately powered
   candidate with IC > 0 and t < 2 is `no edge`, not silence; (iii) the window is the store's
   1,927 sessions, not 492; (iv) metric 4 becomes "≥ 2 of the available folds" if the pilot AR
   backfill is not approved, and a candidate tested in fewer than two folds is `inconclusive`
   by definition?
   *Why it matters now:* the pilot backtest runs this rule, and the pilot is 60 names — so
   most candidates will land in whichever bucket the rule puts them in. The difference between
   `no edge` and `inconclusive` is the difference between a decision and a permanent maybe.
   *Default if you say nothing:* the v4.1 rule as written, with the proposed metrics reported
   next to the verdict and clearly labelled "proposal, not part of the rule".

---

# Appendix — files, commands, measured provenance

```
python tasks/arch_v4/build_concept_registry.py --check      # writes concept_registry.json + registry_coverage.md
python tasks/arch_v4/build_concept_registry.py --show MB0305,MB0125
python tasks/arch_v4/vocab_pass1.py                         # the measured vocabulary pass (VOCAB_PASS1.md)
python tasks/arch_v4/vocab_pass1.py --json                  # the same numbers as JSON
python tasks/arch_v4/bench_screen.py                        # writes bench_screen.md (CPU baseline + the FDR null)
python tasks/arch_v4/nid_retriage.py --check                # self-check only, no writes
python tasks/arch_v4/nid_retriage.py                        # writes nid_search_logs/ + nid_retriage_summary.json
python tasks/arch_v4/bench_gpu.py                           # writes bench_gpu.md (§F.8; needs cupy, see §F.8)
```

Inputs: `tasks/master_bank/MASTER_BANK.jsonl` (1,073 cases, sha `64d2f46318127f76`),
`tasks/pilot60/UNIVERSE.csv` (the 60 pilot ISINs), `tasks/SCHEMA_FINAL_2026-10-29.sql` (137
tables), pilot stores under `reality_engine/data/pilot/pilot60/` (read-only,
`mode=ro&immutable=1`). Gate counts from `tasks/answer_bench/GATE_RESULTS_*_strict.jsonl`. The
generator is deterministic (byte-identical rebuild verified, `PASS`) and touches no database
outside the pilot stores. `build_concept_registry.py` now emits **60 atoms / 19 dims** (v4.1:
the two paid-consensus atoms became one `own.estimate` atom); coverage is unchanged at 897
mapped / 150 NID / 26 unmapped.

Companion artifacts in this directory, each produced by its own worker:

| artifact | status |
|---|---|
| `VOCAB_PASS1.md` | done — the document-vocabulary measurement behind §A.9 |
| `NID_TRIAGE.md` + `nid_triage.json` | done — the 150 NID cases, 31 classes, one verdict each |
| `nid_retriage.py` + `nid_search_logs/` (74 files) + `nid_retriage_summary.json` | done (v4.2) — the deterministic search behind every proxy verdict, §H.5 |
| `bench_gpu.py` + `bench_gpu.md` | done (v4.2) — the CPU/GPU comparison behind §F.8 |
| `bench_screen.py` + `bench_screen.md` | done (v4.2) — the CPU timings and the false-discovery null, §F.7 |
| `PILOT_BACKTEST.md` | **not started** — built by the backtest worker on §E.5 once its verdict rule is approved |

# Appendix: files added 29-31 Oct, documented 1 Nov (first doc sweep)

- `reality_engine/pilot/premise_audit.py`: Rule-check the instance premises against the held stores.
- `reality_engine/query/v4/build_quarters.py`: v4 WP2c — true single-quarter XBRL series from the OneD/FourD contexts (§A.8, §B.1).
- `reality_engine/query/v4/fact_oi.sql`: fact_oi.sql - the F&O open-interest side file (QUERY_V4_DESIGN §B.1, §F.6).
- `reality_engine/query/v4/fact_view_extras.sql`: fact_view_extras.sql - the v4 atoms whose source is outside the five pilot files
- `reality_engine/query/v4/fact_view_holdings_isin.sql`: fact_view_holdings_isin.sql - hold.pct for the pilot names whose shareholding
- `reality_engine/scripts/fetch_shp_xbrl_pilot.py`: Pilot-60 shareholding XBRL -> the ownership atoms v4 is missing (§A.1, §A.2).
- `tasks/arch_v4/reader_test/build_report.py`: Render tasks/arch_v4/READER_TEST_2026-10-31.md from the frozen questions, results and grades.
- `tasks/pilot60/install_traded_close.py`: Rebuild the pilot stores so price.close is the traded close, check them, install, re-run the gate.
- `tasks/pilot60/latest_handcheck.py`: Hand-grade 20 newly answered v4 "latest" rows, reading each value back independently.
