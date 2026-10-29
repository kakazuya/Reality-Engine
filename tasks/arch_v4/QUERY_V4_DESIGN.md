# Query layer v4 — factored concept registry, one executor, a discovery layer

Status: design (30 Oct 2026). Supersedes the planner-patch line of work described in
`tasks/arch_v3/QUERY_LAYER.md`. Every number marked *(measured)* was produced by the two
programs in this directory: `build_concept_registry.py` (registry + coverage over the 1,073
master-bank cases) and `bench_screen.py` (timings + RAM on the pilot stores). Numbers taken
from other documents say so.

## 0. Why v4, in one paragraph

The pilot gate is **27/2,681 strict = 1.0%**, and the failure reasons are almost all
*composition* failures: `GATE ask_match` 2,884, "sub-question N not addressed" 2,708,
"unrelated rows" ~1,500, and only 383 blocked + 132 NOT IN DATA (`tasks/answer_bench/
GATE_RESULTS_*_strict.jsonl`). The data is mostly there; what is missing is (a) one map from
the words a question uses to the measures the database holds, (b) a typed decomposition so
that "promoter **and** public", "NSE **and** BSE **and** the sum", "raw **and** adjusted"
become three parts that must each come back, and (c) an executor that returns exactly one
result per part. v4 makes those three things data instead of code: a registry of **61 atoms,
18 dims, 13 formulas, 26 operators and a mined lexicon**, one executor over one long-format
fact view, and a decomposer that never sees a bank field. Measured on the whole bank: **897
cases map (83.6%), 150 resolve to NOT IN DATA with the registry's stated reason (14.0%), 26
stay unmapped (2.4%)** — i.e. the registry can express **97.6%** of the bank's asks before any
data question is asked at all *(measured, §A.6)*.

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

## A.1 atoms — 61 rows *(measured)*

One row per **raw measure**: `atom_id, label, kind, store, table, column, source, unit,
grain, entity_key, pit, coverage, coverage_note, synonyms`. The generated table is
`concept_registry.json["atoms"]`; the declarations are the `_ATOMS` list in
`build_concept_registry.py` (hand-checked, 61 rows).

| kind | atoms | examples |
|---|---:|---|
| `market` | 14 | `price.close`, `price.high`, `price.delivery_qty`, `price.delivery_pct`, `price.volume`, `price.traded_value`, `price.mcap`, `price.shares_out`, `price.band`, `price.rsi`, `price.sma` |
| `fundamental` | 22 | `fin.revenue`, `fin.ebitda`, `fin.pat`, `fin.eps`, `fin.book_equity`, `fin.total_debt`, `fin.cwip`, `fin.nim`, `fin.npa`, `fin.order_book`, `fin.segment_value` |
| `ownership` | 6 | `hold.pct` (holder class is a dim), `hold.pledge_pct`, `hold.fpi_limit_utilised`, `flows.net_inr`, `corp.amount_per_share` |
| `narrative` | 2 | `claim.claim` (**topic is a dim**), `text.passage` (page is a dim) |
| `macro` | 8 | `macro.policy`, `macro.claim`, `macro.commodity_close`, `macro.index_close`, `macro.flow`, `macro.oi`, `macro.etf_premium`, `macro.series` |
| `absent` | 7 | `absent.consensus`, `absent.price_target`, `absent.intraday`, `absent.investor_holdings`, `absent.refurb_sales`, `absent.forecast`, `absent.private_terms` |

Coverage status per atom *(measured)*: **43 held**, **11 gap** (the registry knows the
measure, the pilot store does not carry it yet — listed in §H.4), **7 absent** (nothing
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
   ripple walk are operators (§A.4). That is why 61 rows cover a 1,073-case bank.

## A.2 dims — 18 rows *(measured)*

A dim is a qualifier that lives **on** an atom. Each row: `dim_id, values, source, default,
note`. The five the brief names plus the ones the bank actually needs:

| dim | values | why it is a dim and not a concept |
|---|---|---|
| `exchange` | NSE, BSE, each, sum | three readings of one price/delivery atom (MB0021 asks all three) |
| `basis` | raw, adjusted | adjusted = split/bonus/dividend adjusted; the same atom |
| `consolidation` | consolidated, standalone | a filing carries both; the dim picks one |
| `holder_class` | promoter, public, FII, DII, MF, insurance, retail, pledge, fpi_limit | one `hold.pct` atom, nine columns (MB0125 asks promoter **and** public) |
| `segment` | open set | from the segment note; the mix comes from `f.share_of` |
| `topic` | open set (223 values in the lexicon, mined) | the narrative topic on `claim.claim` |
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

**Minimality rule, enforced in code:** a new entry is admitted only if a case cannot be
written with the existing ones, and an operator/formula is preferred over an atom. The
generator prints the size-vs-coverage curve that makes the rule checkable (§A.6).

## A.6 Measured coverage and the size-vs-coverage curve

From `python tasks/arch_v4/build_concept_registry.py --check` *(measured)*:

| status | cases | share | meaning |
|---|---:|---:|---|
| mapped | 897 | 83.6% | every clause resolves to an atom/formula/rule; slots filled |
| not_in_data | 150 | 14.0% | resolves, but a required atom is `absent`/`gap` → NID with the registry's reason |
| unmapped | 26 | 2.4% | a clause names a measure the registry cannot express |
| **mapped + NID** | **1,047** | **97.6%** | the ceiling for the 95% gate |

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
  /* … one branch per atom; 61 branches, no data copy … */
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
| `cc_items`, `deck_facts`, `ar_facts`, `chunks_v3.chunk` | new `claim` table (§B.3) + `text` branch | `claim.topic`, `claim.direction/magnitude/horizon` |
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
already has 10,895 rows over 124 index codes and 1,888 ISINs *(measured)*; the sector store is
empty in the pilot (`sector_pit.db.company_sector_pit` has 0 rows) and must be built before
sector screens can answer — that is a one-day curation job, not a schema change.

## B.3 Typed claim table for narrative sources

```sql
CREATE TABLE claim(
  entity_id TEXT, topic TEXT,            -- a topic atom from the dim table
  direction TEXT,                        -- up | down | neutral
  magnitude REAL, unit TEXT, horizon TEXT,
  quote TEXT, page_no INT, doc_id TEXT, doctype TEXT,
  known_at TEXT, pit_conf REAL);
```

Filled **at ingest** by the extraction that already runs, so a query is a lookup:

| existing extraction | feeds `claim` | rows held |
|---|---|---:|
| `concall_facts.cc_items` (metric, direction, firmness, statement, quote) | topic = `metric`; direction from `direction` | 645 k |
| `deck_figures.facts` (metric, period, value) | topic = `metric` (numeric claims) | 13.6 M |
| `ar_facts.ar_facts` (category, item, quote) | topic = `category`+`item` | 32.4 M |
| `policy_events` / `macro_claim_target` | policy claims and their targets | 21.6 k / 44.7 k |

This is the single biggest coverage lever in the bank: the 223-topic lexicon resolves
"products", "business model", "control change", "auditor", "order book", "guidance" without a
new atom each — and the executor's per-entity check turns "this company never said it" into a
precise NID instead of a wrong number.

## B.4 Exposure edges

`edge(driver, target, origin, strength, lag, n, fdr_q, stability_by_window, label, known_at,
last_tested)` — shared by the discovery layer (§E) and the ripple `walk` operator. One table,
one quality vocabulary (`verified | measured_weak | plausible_untested | contradicted`).

## B.5 Migration order (each step independently shippable)

1. `fact` view over the tables that need no new column (market, metric series, ownership,
   macro). Everything in §D already runs on it.
2. `membership` from `company_membership_pit` + `company_sector_pit` (sector curation).
3. `claim` table from `cc_items` (the highest-value source first), then decks, then ARs.
4. `edge` table (§E) — empty at first; `walk` answers "no typed edge" until it fills.
5. `corporate_action_class` build (closes 4 of the 26 unmapped and ~10 of the NID cases).

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
Fix: the third part is a *typed NID*: `corp.amount_per_share` is a declared `gap`, so the
executor prints "post-action count not held: market_state.corporate_action_class is not built
for the pilot" instead of a wrong number.

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
            source_ref, known_at, shape, rule_used?, verdict?, nid_reason?}
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

## D.4 Renderer and the LLM's role

One block per part: value, unit, period, entity/ISIN, source, `known_at`; or
`NOT IN DATA: <the fact> — Checked: <stores, rows after PIT> — Why: <the registry's reason> —
To close: <table or fetch>`.

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

## E.2 The seven mechanisms

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
| **cold** | weekly, off-peak | full re-tests, FDR pass, new candidates, LLM link proposals, regime scan | hours, capped, ordered by expected value (impact × low attention ÷ test cost) |

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

## F.8 GPU (GTX 1050 Ti, 4 GB) — specified, not installed

- **Which steps are dense/sparse matrix work**: the screen (lagged cross-correlation, `N×D`),
  factor residualisation (`T×N×F`), A²/A³ (`N×D×N`), and the FDR batch (vectorised p-values).
  The hot path (lookups, stored edges, beam walk) is **not** GPU work.
- **Where it wins**: measured CPU throughput is 4.3 G multiply-adds/s; the card is ~2 TFLOP/s
  fp32 peak ≈ 230× before bus and launch overhead. So it wins on the weekly cold tier (many
  windows × many lags × many drivers) and on A^k at full universe — not on a 15 ms gemm where a
  CUDA context costs more than the answer. Same lesson as this card's OCR run: measure first.
- **VRAM tiling** (~3 GB of the 4): the panel is `T×N` fp32 (500×4,000 = 8 MB), the driver
  matrix 1 MB, the `N×N` covariance at 4,000 entities 64 MB. Tile over rows:
  `rows_per_tile = 0.75 GB / (N·4 B)` = 50,331 days at N=4,000 — the whole window fits in one
  tile; only `N×N` products above ~8,000 entities need splitting. Accumulate fp32, never fp64.
- **Install (named only, nothing installed here)**: `cupy-cuda12x` (CUDA 12 driver) or `torch`
  with the CUDA 12 wheel. CPU fallback = the numpy path in `bench_screen.py`, kept as the
  reference the GPU result is checked against (`np.allclose`, 1e-5, one window, before every
  cold run).

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

Four packages, disjoint files, each with its acceptance test. The gate-gain estimates below
are shares of the *failure-reason findings* (2,681-case run: `ask_match` 2,884, sub-question
2,708, unrelated ~1,500, blocked 383, NID 132) — they overlap, so **they do not add**.

## H.1 WP1 — registry generator + lexicon (this deliverable, shipped as the baseline)

Files: `tasks/arch_v4/build_concept_registry.py`, `concept_registry.json`,
`registry_coverage.md`. Acceptance: `--check` prints coverage, sizes and the curve; deterministic
rebuild (`PASS`); 897 mapped / 150 NID / 26 unmapped.
Attacks: the *vocabulary* half of `ask_match` (a concept the answer never carried). Estimated
share: **15–25% of ask_match** (the concepts a registry row now names).

## H.2 WP2 — fact view + entity sets + claim/edge tables

Files: `reality_engine/query/v4/fact_view.sql`, `build_membership.py`, `build_claim.py`,
`build_edge_schema.py`. Acceptance: the view returns one row per (entity, atom, period) for all
43 held atoms on the pilot; `membership` covers 1,888 ISINs / 124 index sets; `claim` holds
≥600 k rows from `cc_items` with topics; a spot-check of 50 random claims against their quote.
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
Acceptance: one result per part for every mapped case; the renderer prints value/unit/period/
ISIN/source/`known_at` or the four-gate NID wording; `grade_v2` scores coverage against the Ask
and reproduces today's 1.0% on the old answers (a sanity anchor). Attacks: `ask_match` by
construction (every part carries its concept) and "unrelated rows" (no part → no row).
Estimated share: **~35–45% of `ask_match` and most of the ~1,500 unrelated-row findings**.

Then a fifth package, **discovery/engine (§E/§F)**, only after the gate passes.

## H.5 Data gaps — the cases that still fail because the data is absent

**(a) Absent by nature (7 atoms) — no fetch closes these.** `absent.consensus`,
`absent.price_target` (paid broker research), `absent.intraday` (no free retro intraday bars),
`absent.investor_holdings` (not published in India), `absent.refurb_sales`,
`absent.forecast`, `absent.private_terms`. Cases: 24 atom-mentions across the 150 NID cases
*(measured)* — intraday alone accounts for 14.
Decision needed (Shivam): buy consensus, or accept NID for those parts.

**(b) Pilot build missing (11 atoms) — a build job, not a fetch.** Counts are atom-mentions across the 150 NID cases (a case can name two missing atoms, so they do not add to 150).
 The concept map carries 21
metric keys; these 11 atoms need a mapping row (and for ratio atoms a formula over mapped
concepts), and one of them needs a table built:

| atom | what is missing | closes |
|---|---|---:|
| `fin.npa`, `fin.nim`, `fin.credit_cost`, `fin.loan_book` | `metric_key` rows for the banking concepts (gross/net NPA, NIM, provisions, advances) — the raw XBRL concepts exist in `results_xbrl.facts` | 64 mentions |
| `fin.cwip`, `fin.investments`, `fin.cfo` | same, for the balance-sheet/cash-flow concepts | 15 mentions |
| `fin.deposits`, `fin.unit_volume`, `price.free_float` | new atom rows + the reader/operating-metrics coverage | 28 mentions |
| `corp.amount_per_share` | **build `market_state.corporate_action_class`** (the live DB already has `equity_intelligence.corporate_actions`, and the pilot store has no corporate-action table at all) | 40 mentions |

**(c) The fetch stream (211 cases).** This is *per-entity document coverage*: a company that
never filed a concall, or whose deck is not in the store, cannot answer a claim part however
good the registry is. The registry measurement deliberately cannot see this, because it
measures expressiveness, not per-entity coverage. The check to run before the fetch stream is
one query per case: `claim(entity, topic)` and `chunks_v3.chunk(isin, doc_type)` row counts
after `known_at <= as_of`. The NID reason then names the store and the document instead of the
concept, and the fetch list is the set of (entity, doc_type) with zero rows — which is what the
211-case stream should be built from, not from a guess.

---

# Open questions for Shivam

1. **Consensus estimates**: buy a feed, or accept NID for the `absent.consensus` /
   `absent.price_target` classes (14 cases, and every "beat/miss vs street" framing)?
2. **`claim` topics at scale**: is the extraction vocabulary (cc_items metrics, deck metrics,
   AR categories) the approved topic space, or do you want a hand-curated 50-topic list that
   the extraction must map into? The first is broader, the second is checkable.
3. **Does the 95% gate count a typed NID as answered?** The design assumes yes when the reason
   is `absent` and the wording lists what was checked. If not, the ceiling moves from 97.6% to
   83.6% and the data-gap section becomes the plan.
4. **Sector store**: `sector_pit.db.company_sector_pit` is empty in the pilot. Is one day of
   curation approved (needed before any sector screen can answer)?
5. **Discovery backtesting**: `edge.known_at` makes a hindsight-free backtest possible — do you
   want the first version scored on the last 12 months before any edge is allowed into the hot
   tier?
6. **GPU**: approve `cupy-cuda12x` when the cold tier is built, or keep CPU-only until a
   measured run beats it? (The measurement says CPU wins on everything except the weekly batch.)

---

# Appendix — files, commands, measured provenance

```
python tasks/arch_v4/build_concept_registry.py --check      # writes concept_registry.json + registry_coverage.md
python tasks/arch_v4/build_concept_registry.py --show MB0305,MB0125
python tasks/arch_v4/bench_screen.py                        # writes bench_screen.md
```

Inputs: `tasks/master_bank/MASTER_BANK.jsonl` (1,073 cases, sha `64d2f46318127f76`),
`tasks/SCHEMA_FINAL_2026-10-29.sql` (137 tables), pilot stores under
`reality_engine/data/pilot/pilot60/` (read-only, `mode=ro&immutable=1`). Gate counts from
`tasks/answer_bench/GATE_RESULTS_*_strict.jsonl`. The generator is deterministic (byte-identical
rebuild verified) and touches no database outside the pilot stores.
