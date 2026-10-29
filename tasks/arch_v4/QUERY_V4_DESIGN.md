# Query layer v4 — factored concept registry, one executor, a discovery layer

Status: design (30 Oct 2026). Supersedes the planner-patch line of work described in
`tasks/arch_v3/QUERY_LAYER.md`. Every number marked *(measured)* was produced by the two
programs in this directory: `build_concept_registry.py` (registry + coverage over the 1,073
master-bank cases) and `bench_screen.py` (timings + RAM on the pilot stores). Numbers taken
from other documents say so.

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

The pilot gate is **27/2,681 strict = 1.0%**, and the failure reasons are almost all
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
count a typed NID as answered: each of the 150 is a triage ticket — fetch it free within a
day, answer it from a labelled proxy, or close it as true NOT IN DATA with what was tried
(§H.5; the triage worker's list is `tasks/arch_v4/NID_TRIAGE.md`). Consensus is no longer an
absent class: the estimates are ours, built from our own series, guidance and the opinions
store (§A.8).

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

**Read the third column correctly (v4.1 decision 3).** 97.6% says the registry can *write
down* the ask; it is not the gate's expected answer rate. A typed NID is a to-do: every one
of the 150 is triaged into (a) a free fetch that closes it within a day, (b) a labelled proxy
answer (the proxy, its assumption, its confidence), or (c) a true NOT IN DATA that lists what
was tried. The triage output is `tasks/arch_v4/NID_TRIAGE.md`; until it lands, the honest
answer rate is **83.6%** and the plan to raise it is the triage list, not a bigger registry.

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

**Beat/miss.** `realised(atom, period) - own_estimate` with its sign and relative size
(`/ |estimate|`), reported as `beat | miss | in-line` (in-line = |diff| ≤ 2% or ≤ the
estimate's own confidence band) **and**, when an opinions report exists, the same arithmetic
against that report's number. Both readings are printed; they can disagree, and the answer
says which store each came from. A miss is never upgraded to a beat by a later re-estimate:
`known_at` fixes what we could have known at the time, and re-estimates are new rows with a
new `as_of`.

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

The finding is in the numbers: 60–80 labels is the right operating size (60 topics cover
62.4%, and the marginal topic after ~120 adds ~0), but **token matching saturates at ~65%**.
The 95% must therefore be reached by a **semantic** mapping over the 64,948 head surfaces
(§H.8), with the tail as `other:<raw>` by construction. The release check is in
`VOCAB_PASS1.md` §4: 100% of surfaces mapped (label or `other:<raw>`), ≥95% exact precision
on a 100-mapping hand sample, head surfaces mapped, label growth only by promotion.

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
**person-days for one build worker**, measured against what the repo already holds; the
number is an estimate and is labelled as one.

**Step 1 — PIT classification and index membership from NSE archives.**
Sources: `D:\RealityEngine\raw\index_constituents` (archive already downloaded),
`company_membership_pit` (10,895 rows, 124 index codes, 1,888 ISINs), NSE's archived
classification sheets. Build `membership` with only factual windows: `valid_from` = the date
the file was published or first archived, `known_at` = that date, `removed_on` when a later
file drops the name. Where an earlier state is unknown, the row starts at the first archived
snapshot and carries `pit_known=0` — it is never backcast to 2019. **3–4 days** (1 day crawl
and parse, 1 day join/validate, 1–2 days on the classification history: NSE does not publish
a dated classification series, so the history is only as good as the archive; if the archive
starts in 2021, the store starts in 2021).
*Exit check:* zero rows whose `known_at` precedes their source file; per-index membership
counts on 5 sampled dates equal the archived file.

**Step 2 — revenue-weighted multi-sector exposure from segment data.**
`metric_state.company_segment_pnl` gives segment revenue; the missing piece is a
segment-name → sector map (~28 sectors; ~400 segment strings in the pilot, hand-mapped once,
stored as `segment_sector_map`). Weight = segment revenue / total revenue for the period, with
the unallocated remainder as `unallocated`. A company is then multi-sector
(`membership.set_kind='exposure'`, `weight`), and sector screens can weight by exposure
instead of a single label. **4–5 days** (2 days mapping + review, 1 day build, 1–2 days QA:
weights sum to 1, periods align, unallocated share reported).

**Step 3 — value-chain position: inputs and outputs (feeds `edge`).**
*Inputs* from the annual report raw-material cost shares (`ar_facts`: category/item + value,
e.g. "cost of materials consumed", with the item text as the input), *outputs* and customer
industries from segment/customer-concentration notes and the company's own product text.
Writes `edge(origin='text', driver=commodity|sector, target=isin, mechanism='input share',
strength=share, known_at=filing date)`. This is the only step whose data is sparse: cost
shares are disclosed by a minority of companies (mostly manufacturers), so coverage will be
uneven and is reported, not imputed. **5–7 days** (2 days extraction rules over `ar_facts`, 1
day linking input names to commodity series, 1 day customer/output industries, 1–3 days QA —
the honest risk is precision, which is why every edge carries the quote that produced it).

**Step 4 — statistical peers from clustering factor-residual returns.**
Residualise every company's daily returns on the declared common factors (the existing
`factor_spine` + the `bench_screen.py` residualisation, measured 59 ms), then cluster the
residual-return correlation matrix per rolling window (12-month, 1-month step), storing peer
sets with `valid_from`/`known_at`. Peers are a *measured* store, never a label guess.
**2–3 days** (the maths exists; the work is the rolling store, the stability check and the
"refuse when too few active features" rule that `peer_graph.py` already applies).

**Step 5 — themes (thematic indices + product tags).**
Theme membership from the held index codes (thematic indices in `index_list`) plus product
tags extracted from the company's own documents; `theme_map` already has
`source='curated'|'opinion'` and the rule that an opinion theme never silently becomes
curated (architecture doc Q2). **2 days.**

**Step 6 — the checks that decide whether any of it ships.**
(a) **PIT validation**: every date used by a query must be ≥ the source's `known_at`; a
leakage test (query the store as of 2019-06-30 and fail if any label was first published
later) blocks the load. (b) **30-company hand sample**: one page per company showing the
label, the filing it came from, the exposure weights and the peer set; a human marks
right/wrong; ≥28/30 must pass. (c) **Coverage**: per year and per sector, the share of the
universe with a PIT label, with exposure weights, and with a peer set; the gaps are printed,
never filled. **3 days.**

**Total: 19–24 person-days** (≈4–5 weeks for one worker; the steps are independent after
step 1, so 3 workers cut it to about 2 weeks, with step 1 as the gate for steps 2 and 5).

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
typed NOT IN DATA is **not** an answered part; the gate counts only the first three types as
answered (`estimate` and `proxy` are labelled, never dressed as measured).

| type | when | block fields |
|---|---|---|
| `measured` | the fact is held and PIT-filtered | value, unit, period, entity/ISIN, source table, `known_at` |
| `estimate` | `own.estimate` (§A.8) | value, unit, period, entity, **method** (`trend`/`trend_guidance`/`trend_guidance_opinion`), the inputs (series refs, guidance refs, opinions-doc refs), confidence, `known_at` |
| `proxy` | the datum is not held, but a workaround from other held sources answers the ask (decision 3b) | the **proxy** (what is being used in its place), the **assumption** (the stated bridge from proxy to answer, with the arithmetic), the **confidence**, and the sources used |
| `not_in_data` | only after triage (decision 3c) | `NOT IN DATA: <the fact> — Tried: <fetches attempted, with dates> — Checked: <stores, rows after PIT> — Why: <the registry's reason> — To close: <the exact table/fetch>` |

`proxy` is a first-class answer type, not a hedge: the block must state the proxy, the
assumption that makes the proxy informative, and a confidence in [0,1]. A proxy whose
assumption cannot be written down is not an answer — it is a ticket.

**NID triage** (the process behind the fourth type; the per-case list is
`tasks/arch_v4/NID_TRIAGE.md`):

1. **Fetch** — can the data be fetched free within one day (NSE/BSE archive, a filed PDF, an
   index constituent file)? Then it is a fetch job; the part stays open with the job's id.
2. **Proxy** — the datum is genuinely hard to get (paid, private, never published). Answer
   from a proxy or workaround drawn from held sources, labelled `proxy` with its assumption
   and confidence (e.g. "investor-wise holding" → the FCRA/EPT-2 footpath is not held; proxy =
   the shareholding pattern's institution totals, assumption = the institution total bounds
   the name-level position, confidence 0.4).
3. **NID** — only when 1 and 2 are exhausted: list what was tried. The list is the evidence
   the gate needs; "we don't have it" alone is not.

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

- **FDR correction** across all tests at once (Benjamini–Hochberg), not per look.
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

## E.5 Pilot discovery backtest (v4.1 decision 5) — the gate before the full database

**Order of work, binding:** pilot backtest → Shivam approves the full schema → only then the
full database. Nothing in §E/§F is built at full scale before the pilot backtest has run and
been reviewed. The pilot backtest is a *machinery test* (does a hindsight-free discovery
process produce stable, measurable links on 60 names?), not a claim that an edge exists.

**Inputs (all held, read-only):** `market_state_pilot.company_state_daily` (492 sessions ×
the pilot ISINs), the pilot `company_membership_pit`/`company_sector_pit` (§B.6), the pilot
claims (§A.9), and the per-edge statistics from `bench_screen.py`'s residualisation. No
network, no paid call.

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
| 5 | economic | top-decile minus bottom-decile residual spread ≥ 1.5 × round-trip cost (30 bp debit + a stated slippage assumption), before tax; after-tax version reported alongside |
| 6 | decay | no edge whose OOS IC falls > 50% versus its in-sample IC |

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

Residualise every company series on ~10–20 declared common factors (market, sector groups,
rates, INR, commodity groups) **before** testing any link. Correlated "n factors" collapse into
a few latent ones, which is why the measured residualisation is `O(T·N·F)` and cheap
(§F.4).

## F.2 Mechanism gate + hierarchy

Expensive tests run only on pairs connected by a typed link (cost share, segment mix,
supplier/customer named in text, policy target, membership). Test sector aggregates first and
drill into companies only where the sector link holds — that is the hierarchy the measured
costs allow: a company test costs ~10³ more than a sector test, and most sector tests fail.

## F.3 Shock-first walk

When a driver moves >2σ, beam-search outward from it, top-k per hop, ≤3 hops. Measured at
**6.7 ms for 3 hops, top-10** on a 2,000×500 edge matrix *(measured)*, so the walk can be part
of the query path, not a nightly batch.

## F.4 Incremental, never recompute

Per-edge running statistics (counts, sums, cross-products per lag) updated by new rows only:
measured **2.1 ms per new day for 10 lags** across 4,042 companies *(measured)*. Dirty
propagation works like a build system: a new filing marks only the dependent features, edges
and paths stale; a data-quality check must pass before anything is marked stale (§G).

## F.5 Three tiers, with the budgets the measurements actually support

| tier | when | what | budget (measured basis) |
|---|---|---|---|
| **hot** | query time | fact-view lookups, stored edges, 3-hop beam walk | <2 s (measured: lookups 0.01–9.6 ms; walk 6.7 ms) |
| **warm** | nightly incremental | features, stale edges, attention, reaction lags | minutes (measured: residualise + 10 lags = 0.21 s; +1 day = 2.1 ms/edge-set) |
| **cold** | weekly, off-peak **and only after the §E.5 pilot gate (H.0)** | full re-tests, FDR pass, new candidates, link proposals, regime scan | hours, capped, ordered by expected value (impact × low attention ÷ test cost) |

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
(2,296,201 rows); drivers: **33** from held series (22 World Bank commodities forward-filled,
equal-weight market, 10 index-membership groups). numpy only, read-only.

| step | measured (last run) |
|---|---:|
| one lag, full screen (N×D, one BLAS gemm) | 13.2 ms |
| ten lags | 145 ms |
| factor residualisation (20 given factors, OLS) | 59 ms |
| **residualise + ten lags** | **170 ms** |
| A² on 2,000×500 bipartite (20,000 typed edges, fp32) | 19.0 ms |
| A³ | 36.3 ms |
| prune below threshold after a multiply | 13.8 ms |
| shock walk, 3 hops top-10 | 6.3 ms |
| one new day, ten lags (incremental) | 1.9 ms |
| RAM peak (process RSS) | 588 MB (**the row loader**, not the maths: the panel is 7.6 MB) |

Run-to-run variance on this box is 10–30% (the residualisation solve swings 20–59 ms); the
exact last run is in `bench_screen.md`, which the program rewrites each time. Extrapolation to
the design size (arithmetic on the measured rate, not a second measurement): 2,000 entities ×
500 drivers × 492 days → **0.10 s per screen, 1.0 s for ten lags**; at 4,042 entities →
0.20 s / 2.0 s.

**Acceptance targets: confirmed, but the first two are far too loose.** The full daily screen
is ~170 ms (~1,700× under the 5-minute target) and the incremental update is ~2 ms (300,000×
under 10 minutes). The 5-minute budget is really spent in panel assembly and feature build, not in
linear algebra, so §F.5 re-states the budgets as **hot < 2 s, warm = feature build + stale-edge
refresh, cold = weekly batch** — and the engineering effort belongs in the fact view's
partitions and the dirty-propagation graph, not in a faster gemm.

## F.8 GPU vs CPU — a thesis and the test that decides it (v4.1 decision 6)

**Nothing here is measured. Do not cite a speed-up from this section.** The CPU numbers in
§F.7 are measured on this box; the GPU side is a **hypothesis** with a named experiment. A
separate worker runs the benchmark and writes `tasks/arch_v4/bench_gpu.md`; until that file
exists with a result table, the design stays CPU-only and no cold-tier step is specified
against a GPU.

**Thesis (to be tested, not assumed).**

- *H1 — the cold tier is GPU-shaped.* The weekly batch is many independent windows × lags ×
  drivers, i.e. tall-skinny matrix work with no Python object churn. If any step is GPU-shaped,
  it is this one: the CPU path is a loop over windows, and a batched GEMM on the card should
  cut wall-clock once the batch is large enough.
- *H2 — the hot and warm tiers are not GPU-shaped.* Query-time lookups (0.01–9.6 ms), the
  3-hop beam walk (6.7 ms) and the incremental update (2.1 ms/day) are latency-bound; a CUDA
  context, a host→device copy and a synchronise cost more than the work. Predicted: GPU loses
  or ties there.
- *H3 — the bottleneck is not the gemm.* §F.7 measured that panel assembly (57 s per 2.3 M
  rows from SQLite) dominates the arithmetic (~170 ms for residualise + ten lags). If H3
  holds, a 200× GPU gemm changes nothing and the engineering belongs in partitions and the
  dirty-propagation graph. **This is the thesis's real risk: the cheap thing to accelerate is
  not the expensive thing.**

**The test that decides it (pre-registered; the benchmark worker runs exactly this).**

| # | experiment | measure | decides |
|---|---|---|---|
| T1 | full cold-tier workload (all folds in §E.5 × 10 lags × 33–60 drivers) on CPU (numpy, `bench_screen.py`) and on the card (cuPy or torch CUDA), same inputs, fp32 | wall-clock, peak RAM/VRAM, 3 repeats, median ± spread | H1: GPU ≥ 3× faster on the *end-to-end* job (not one gemm) |
| T2 | hot path: 1,000 stored-edge lookups + 100 three-hop walks | p50/p95 latency | H2: GPU not slower at p95 |
| T3 | one new day, ten lags, incremental | per-day time | H2: GPU is not needed (it should lose) |
| T4 | panel assembly alone, CPU only, cold cache | seconds | H3: if assembly ≥ 10× the arithmetic, a GPU result cannot move the budget |

**Decision rule, fixed in advance.** Adopt a GPU path **only if** T1 shows ≥ 3× end-to-end
and T2 shows no p95 regression; otherwise stay CPU and put the effort into panel assembly and
the dirty graph. T4 is reported first, because if it dominates, T1's 3× is unreachable no
matter what the card can do. The CPU path stays the reference: any GPU result must pass an
`np.allclose` (1e-5) check on one window before it is timed.

**What does not change either way.** The CPU path in `bench_screen.py` is the reference
implementation; the hot path remains SQL + stored edges; there are no GPU-only features in the
query contract. The install candidate (named only, not installed): `cupy-cuda12x` or the
CUDA-12 `torch` wheel, on the GTX 1050 Ti (4 GB) — and 4 GB is a stated ceiling, so tiling is
part of the test, not an optimisation after it.

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

**The nightly scoring (after close, ~21:00 IST, after the 19:35 price job).**
1. Load holdings read-only: the **official Kite MCP** for Zerodha and the **Angel One export**
   file. No order endpoints, no write scopes; a missing/stale export marks the account
   `as_of` stale and the run refuses to recommend a switch it cannot size.
2. For each asset (held and candidate), compute the expected 1-year return from the held
   atoms (the same fact view the query layer reads), then convert to **post-tax** return using
   the tax-rules table built from the enacted Gazette texts (never a hardcoded rate — the
   2026-10-19 decision) and the holding period.
3. Cost to switch = exit cost (STT/brokerage + the actual tax on the realised gain + slippage
   in bp by liquidity bucket) + entry cost + the tracking/expense drag of the alternative.
   Slippage is a stated assumption per liquidity bucket, stored in the row, not a constant in
   code.
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
5. The GPU decision (§F.8) and the evening layer (§F.9) are design-only until 2–3 finish; the
   evening layer additionally waits for the portfolio-level out-of-sample test.

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
reproduces today's 1.0% on the old answers (a sanity anchor). Attacks: `ask_match` by
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

| work | cases | effort |
|---|---:|---|
| `corp.amount_per_share` → build `corporate_action_class` (the live DB has `corporate_actions`; the pilot store has no table) | 40 | 3–5 days |
| banking concept keys (`loans` 23, `net_npa` 22, `nim` 13, `credit_cost` 6) → mapping rows over the XBRL concepts already held in `results_xbrl.facts` | 64 | 2–3 days |
| `cwip` 2, `investments` 8, `cfo` 5 → same mapping rows | 15 | 1–2 days |
| `deposits` 7, `unit_volume` 13, `price.free_float` 8 → one atom row + reader/weight coverage each | 28 | 2–4 days |

**(c) Free fetch within one day → a fetch job.** This is mostly *per-entity document
coverage*: the 211-case stream. A company that never filed a concall, or whose deck is not in
the store, cannot answer a claim part however good the registry is. The fetch list is built
from one query per case — `claim(entity, topic)` and `chunks_v3.chunk(isin, doc_type)` row
counts after `known_at <= as_of`; every (entity, doc_type) with zero rows that is *filed and
free* (NSE/BSE archive) is a fetch job, not a NID. **Effort is in the stream, not in this
design.**

**(d) Genuinely hard → proxy with its assumption, or NID with what was tried.**
`absent.intraday` 14 (no free retro intraday bars → proxy: daily high-low range / close as an
amplitude proxy, assumption stated, confidence low), `absent.forecast` 4 (no forecast is a
fact → proxy is a scenario, and a scenario is labelled), `absent.refurb_sales` 2,
`absent.investor_holdings` and `absent.private_terms` (rare in the bank). Each is answered as
a `proxy` block (proxy, assumption, confidence, sources) or, when no bridge can be stated, as
NID listing the fetches tried. **Never a bare "not in data".**

**(e) The decision the triage produces.** For each case: `fetch(job_id)`, `proxy(result,
assumption, confidence)` or `nid(tried[])`. The gate counts the first two; the third is
visible debt with an owner and an attempted-fetch log. The triage worker's output is the input
to the next fetch wave — not a reason to grow the registry.

## H.6 WP6 — sector, exposure and peer build (§B.6)

Six steps, 19–24 person-days; step 1 (PIT classification + membership) is the gate for steps
2 and 5. Acceptance: the leakage test fails the load if any label was first published after
the date it is used for; the 30-company hand sample passes ≥28/30; coverage is printed per
sector per year. The 2019-01-01 backcast in `company_sector_pit` is replaced, not migrated.

## H.7 WP7 — `own_estimate` build (§A.8)

Trend leg first (it needs nothing new), then the guidance adjustment from `claim` rows, then
the opinions join where a report exists. **3–4 days** (1 day trend + backtest, 1–2 days
guidance claims and caps, 1 day opinions join and the beat/miss report). Acceptance: an
`own_estimate` row for every (pilot ISIN, beat/miss atom, quarter) where the series exists;
the estimate's own out-of-sample error is measured (MAPE by cap bucket) and printed; a
re-estimate never rewrites history (new `as_of` rows only).

## H.8 WP8 — vocabulary semantic mapping + label release (§A.9, `VOCAB_PASS1.md`)

Map the 64,948 head surfaces (95% of occurrences) to the ~60–80 labels with a semantic mapper
(the local embedding index; no paid model), keep the tail as `other:<raw>`, run the 100-mapping
hand check, and promote `other` clusters that pass the promotion rule. **5–8 days** (2 days
mapper, 2 days review of the head, 1–2 days promotion queue, 1–2 days re-measure as
`VOCAB_PASS2.md`). Acceptance: 100% of surfaces mapped; ≥95% exact on the 100-mapping sample;
every `other` cluster with ≥20 occurrences / ≥3 companies / ≥2 doc types is in the promotion
queue with its evidence.

## H.9 WP9 — evening portfolio layer (§F.9) — design-only until the gate

When built: the four tables, the nightly scorecard, the recommendation log and its grader.
**5–7 days** (2 days tables + holdings readers — Kite MCP read-only and the Angel One export,
2 days scoring after tax/cost/slippage, 1–2 days grading, 1 day calibration report).
Acceptance: a recommendation carries evidence, confidence and its falsifier; the log is graded
at 1/3/6/12 months; the layer emits signals only (no order path exists); a static allocation
is the benchmark it must beat before it is called useful.

## H.10 WP10 — pilot discovery backtest (§E.5)

Machinery + four folds + the report `tasks/arch_v4/PILOT_BACKTEST.md`. **10–15 days** (the
machinery exists in `bench_screen.py`; the work is the fold loop, the `known_at` replay check,
the FDR pass and the write-up). Acceptance: the replay check is byte-identical; every fold's
edge set is produced with `known_at <= t` in SQL; the report states edge / no edge /
inconclusive per candidate with the test count. This report is what Shivam reviews before the
full schema (H.0).

---

# Open questions for Shivam

The six decisions of 30 Oct 2026 are closed and written into the body. What remains is the
small set of numbers the decisions still need from you; none of them blocks WP1–WP4.

1. **The label gate's wording.** `VOCAB_PASS1.md` measured that a 60–80-topic vocabulary with
   token matching covers 64.8% of phrase occurrences; 95% is reached only over the *head*
   surfaces (64,948 surfaces carry 95% of occurrences), and only with a semantic mapper. Do
   you want the gate as **(a)** "≥95% of occurrences are labelled *or* explicitly
   `other:<raw>`" (100% by construction, honest but weaker) or **(b)** "≥95% of the head
   surfaces carry an exact label, hand-checked at ≥95% precision" (the one this design
   recommends)? (a) and (b) differ in what a failing case is blamed on.
2. **The estimate method's caps.** §A.8 caps a guidance adjustment at ±1.5× the trend's
   standard error and calls |diff| ≤ 2% "in-line". Revenue and EPS have very different
   natural error; do you want the band per atom (e.g. 2% revenue, 5% EPS), or one number for
   all?
3. **Proxy acceptability.** What confidence floor counts as an *answered* proxy part in the
   gate (this design says: any stated proxy counts, because the assumption is inspectable;
   the alternative is to require ≥0.5 confidence, which would re-open ~10 of the 150 tickets)?
   And are the named bridges acceptable — intraday amplitude → daily high-low/close, and
   investor-level holdings → institutional totals?
4. **Sector-build effort.** §B.6 prices it at 19–24 person-days (≈2 weeks with three workers),
   gated on step 1. If the NSE classification archive starts in 2021, the PIT store starts in
   2021 and everything before it is `pit_known=0` — is that an acceptable history, or should
   the build stop and wait for an archive?
5. **Pilot backtest power.** 60 names, 28 sectors, four folds (2022–2025) and 2026 untouched.
   Approve the verdict rule of §E.5 — including that most edges are expected to be
   *inconclusive* and that an inconclusive edge does not enter the hot tier.
6. **Evening layer inputs.** Confirm the brokers (Zerodha via the official Kite MCP, Angel One
   via its export only), the slippage assumptions per liquidity bucket, the switch margin
   (this design requires the after-tax improvement to exceed the switch cost by a margin
   before a switch is recommended), and that a static allocation is the benchmark the layer
   must beat.
7. **GPU benchmark approval.** The test in §F.8 needs one install (`cupy-cuda12x` or the
   CUDA-12 torch wheel) on the GTX 1050 Ti box. Approve that install for the benchmark worker
   only; no GPU dependency enters the query path either way.

---

# Appendix — files, commands, measured provenance

```
python tasks/arch_v4/build_concept_registry.py --check      # writes concept_registry.json + registry_coverage.md
python tasks/arch_v4/build_concept_registry.py --show MB0305,MB0125
python tasks/arch_v4/vocab_pass1.py                         # the measured vocabulary pass (VOCAB_PASS1.md)
python tasks/arch_v4/vocab_pass1.py --json                  # the same numbers as JSON
python tasks/arch_v4/bench_screen.py                        # writes bench_screen.md (CPU baseline)
```

Inputs: `tasks/master_bank/MASTER_BANK.jsonl` (1,073 cases, sha `64d2f46318127f76`),
`tasks/pilot60/UNIVERSE.csv` (the 60 pilot ISINs), `tasks/SCHEMA_FINAL_2026-10-29.sql` (137
tables), pilot stores under `reality_engine/data/pilot/pilot60/` (read-only,
`mode=ro&immutable=1`). Gate counts from `tasks/answer_bench/GATE_RESULTS_*_strict.jsonl`. The
generator is deterministic (byte-identical rebuild verified, `PASS`) and touches no database
outside the pilot stores. `build_concept_registry.py` now emits **60 atoms / 19 dims** (v4.1:
the two paid-consensus atoms became one `own.estimate` atom); coverage is unchanged at 897
mapped / 150 NID / 26 unmapped.

Companion documents, each produced by its own worker, not by this one:
`VOCAB_PASS1.md` (this directory), `NID_TRIAGE.md` (the 150 NID cases, in progress),
`bench_gpu.md` (the GPU test, in progress), `PILOT_BACKTEST.md` (after §E.5 is built).
