# Query layer v3 — planner contracts, router, hybrid search, NOT IN DATA

Design for the query layer that sits on `SCHEMA_V3.sql`. Every rule here is checkable against
`tasks/arch_v3/CASE_MAP.jsonl`: each of the 1,030 cases names its planner chain, the exact
`table.column`s each hop reads, its PIT key and its status. Numbers cited as measured come from
`SPEED_PLAN.md` (same directory) and from the read-only probes summarised in `COVERAGE.md §2`.

---

## 0. Where this design disagrees with the reviewer's draft

`tasks/QUERY_ARCHITECTURE_PILOT_PLAN_2026-10-28.md` (Eagle) is the draft. Six things are wrong or thin:

| # | Draft says | Problem, measured | This design |
|---|---|---|---|
| 1 | "route by `answer_kind` (one planner per shape)" | 200 of 1,030 cases have `answer_kind = null` (the whole ripple bank) and 85 have no `family` at all (all reddit cases carry `family: []`). Routing on `answer_kind` mis-routes 285 cases before a single query runs. | Route on `(source_bank, archetype/template, family set, entity_level, answer_kind)` in that order; `answer_kind` is a tiebreaker, never the key. `CASE_MAP.jsonl` rows show the resulting chain per case. |
| 2 | Schema additions ranked by "cases unblocked" from GAP_ROLLUP | GAP_ROLLUP counts every gap a case touches, so its totals double-count (a case blocked by 3 gaps appears 3×). The marginal order differs: `chunks_v3` 64 cases, `commodity_price_daily` 62, `macro_claim_target` 58, `exchange_originals` 46, `company_metric_series` 42 (greedy set-cover over `CASE_MAP.blocking`, `COVERAGE.md §3`). | Rank by **marginal** cases closed, and report both raw and marginal. |
| 3 | NG27 "new fetch" (intraday bars) — 24 cases | The 24 cases do not need intraday bars: they need the **15:30 session rule**. A filing at 19:56 is day+1; that is a table, not a fetch. Only *intraday amplitude* is genuinely not in data (and NSE does not publish free retro intraday). | `event_day0` closes 21 of 24; the remaining 3 that ask for intraday amplitude are answered with a stated degradation ("daily window only"). Design: `event_day0.session_0`. |
| 4 | Hybrid search = "FTS5 + dense filtered by …" with no size model | The 4096-d corpus is 3.4M × 16 KB = **56 GB**; the live Nemotron index holds 2.79 GB = ~170k vectors (measured today), the AR Qwen index ~684k, bge ~1.7M. Brute-force dense over the full corpus cannot fit a 2 s budget on this machine, and 95% of chunks have no 4096-d vector at all. | Filter first, then lexical, then dense **rerank of ≤2,000 candidates** (measured 1.6 ms). Corpus-wide dense is an ANN upgrade, not a pretence. Chunks without vectors are marked lexical-only in the degradation note. |
| 5 | Pilot universe = "every company named in the master bank + 20 random" | The bank names **489 distinct ISINs / 502 symbols** (measured). "Every FY25+ document" for 489 companies is 9.4k concalls + 13k decks + 14.4k ARs + ~41k result PDFs ≈ 78k docs — that is not a pilot, it is the full run with a different name. | Two-tier pilot: **T1 = 30 ISINs** chosen for case coverage (one per archetype, all doc types) and **T2 = the full 489** for the cheap deterministic tables only (`company_state_daily`, `metric_series`, `event_day0`). See `PILOT_SPEC.md §1`. |
| 6 | Gate "search p95 < 2 s" with no plan to measure it | No query set, no corpus scale, no distinction between entity-scoped and corpus-wide search. | 20 timed queries, 5 of them search, measured at live scale (2.3M-row FTS) plus a 10k-row prototype of the new tables; p95 computed and shown in `SPEED_PLAN.md §1`. |

Two things the draft gets right and this design keeps: one function per planner in `reality-data`
(the master bank becomes the regression suite), and the PIT cutoff applied **in SQL at every hop**.

One correction to `ARCHITECTURE_OVERHAUL_2026-10-27.md` that matters for queries: its
`company_membership_pit` uses `index_code`, but the held table is `index_membership.index_name`
(300 rows, one `as_of`); `SCHEMA_V3.sql` keeps `index_code` as the canonical key and maps the
snapshot in the build, so the drift is recorded rather than silently joined.

---

## 1. The eight planners

Every planner is a pure function `(slots, as_of) -> rows + provenance`. All of them return the same
envelope so the assembler can treat a hop uniformly:

```json
{"hop": "FACTS", "rows": [...], "provenance": [{"ref": "results_xbrl.filings.file=INDAS_..._WEB.xml",
  "known_at": "2026-07-10T04:51:00"}, ...], "pit": "dissem_ts <= 2026-10-19",
 "checked": ["results_xbrl.filings", "results_xbrl.facts"], "degraded": []}
```

| planner | input slots | output | SQL shape (index used) | PIT clause | measured |
|---|---|---|---|---|---|
| **RESOLVE** | symbol / ISIN / BSE code / name at `as_of` | `isin`, `symbol_at_time`, `bse_code`, `status` | point lookups on `master_companies.isin`, `symbol_isin_history(symbol, first_date<=d, last_date>=d)`, then `isin_rekey_map` if the ISIN is stale | the symbol window containing `as_of`, never today's symbol | 0.022 ms (Q01) |
| **FACTS** | `isin`, `metric_key`, `period`, `basis` | rows with `value`, `unit`, `doc_id`, filing id | `company_metric_series` PK `(isin, metric_key, period_end, period_kind, basis)`; fallback `results_xbrl.facts(file,concept)`, `ar_facts(isin,category)`, `deck_facts` via `pages.isin`, `cc_items(isin,list_name)` | `known_at <= as_of` on the row's own filing timestamp (`dissem_ts`, `filed_at`, `deck.known_at`) | 0.1–9.6 ms (Q05–Q10) |
| **SERIES** | `isin`/`symbol`, `date_from`, `date_to`, metric | ordered rows; derived stats (CAGR, drawdown, z-score) | `daily_price_delivery` PK-ish `(isin,date)` range; `px_nse_adj(symbol,date)`; `commodity_price_daily(series_code,date)`; `company_state_daily(isin,date)` | `date <= as_of`; for indices/commodities, publish date (release lag) | 0.01–0.9 ms (Q03,Q04,Q19) |
| **SCREEN** | universe predicate (`mcap_bucket`, `index_code`, `sector`, `theme`, `band`, `fno`), ranking metric, date | ranked list + membership provenance | `company_state_daily(date, mcap_bucket)` / `(date, price_band)` / PK `(isin,date)`; membership interval `(index_code, added_on)` with `removed_on` test; sector/theme intervals | interval `valid_from <= d < valid_to`; daily row `date <= as_of` | 0.09–3.99 ms (Q17,Q28; P1,P2,P3) |
| **EVENT** | `isin`, event kind, window `[-k,+n]` | `session_0`, offset, abnormal return, delivery z, insider/deal net | `event_day0(isin, session_0)` then `event_leakage_window(isin, date)`; raw window from `daily_price_delivery` | news known at `T` can only move `session_0 >= session(T)` (15:30 rule); windows backwards only | 0.01–5.4 ms (D1,P6,P7) |
| **RIPPLE** | claim/policy id **or** a trigger (`commodity+move`, `policy+date`), hop budget | hop chain: trigger → targets → company exposures → market response | `macro_claim_target(target_kind,target_id)` → `company_sector_pit` → `company_cost_structure` / `company_segment_pnl` / metric series → `EVENT` per company | claim `known_at` at hop 1; every downstream row must be knowable at the same `as_of` (no look-ahead from a later quarter) | 0.06 ms hop 1 (P8), 0.15 ms policy (Q11) |
| **COMPARE** | `isin` set or `basic_industry` + metric + period | table of peers with the same metric | same as FACTS/SCREEN but over a peer set; `company_peer_graph` for analog peers when no sector map | identical clause to the underlying hop — a peer's later filing must not leak in | 0.02–1.5 ms (per peer) |
| **EVIDENCE** | free text + filters (`isin`, `doc_type`, `known_at<=T`, `tag`, `fiscal_period`) | up to 6 passages with doc/page/known_at | §5 hybrid: structured prefilter → FTS5 `MATCH` → dense rerank of ≤2,000 → deterministic boost rerank | `chunk.known_at <= as_of` inside the SQL, never after ranking | 238 ms (Q15) + 1.6 ms rerank |

**Order inside a chain** is `SCREEN → EVENT → RIPPLE → COMPARE → FACTS → SERIES → EVIDENCE`:
narrowing first (it shrinks every later hop), text last (it is 100× more expensive per row). The
`CASE_MAP.jsonl` chains obey this order; 393 of 1,030 have 4 hops, 290 have 3.

**Hop stop rule.** A planner that returns 0 rows does not fail the case: it returns
`{"empty": true, "checked": [...]}` and the assembler decides between a NID answer and a partial
answer. This is what makes 127 of 200 ripple cases answerable as a partial chain with an explicit
unanswered hop.

---

## 2. Router: master-bank fields → planner chain

Deterministic, no model. Implemented in `.tmp/build_case_map.py` (kept in the worktree so the
1,030-row map can be regenerated) and specified here.

```
1. entity resolution slot:
   entity_level in (stock,index,market-cap bucket,price band) or any entity has symbol/isin
       -> "resolve" is hop 0 (1,030/1,030 cases)
2. evidence slots: parse rubric.required_evidence (and, for the ripple bank, chain[i].evidence_needed)
   into canonical refs (px, xf, af, ar_facts, cc_items, deck_facts, xbrl_filings, policy, shp, ...).
   Each ref maps to one planner family (table above).
3. body planners:
   ripple200                     -> RIPPLE + EVENT if any hop is day0/leakage + SERIES if any hop is a
                                    series gap + FACTS + EVIDENCE   (the chain is the question)
   entity_level in index/theme/market-cap bucket/sector/price band -> SCREEN
   family ∩ {9,15} or "event window" in question                    -> EVENT
   family ∩ {6,7,18,19}                                              -> RIPPLE
   family ∩ {8,13} and level in industry/sector/theme                -> COMPARE
   family ∩ {1,2,3,5,11,14,17}                                       -> FACTS
   family ∩ {3,12} or answer_kind=date with family 12                -> SERIES
   answer_kind in {text+quote,explanation,list} or family ∩ {5,15}   -> EVIDENCE
4. dedupe, keep resolve first, then the canonical order above.
5. status = worst blocker named by coverage.gap (+ chain gap_keys + "not held" evidence markers):
   NOT_IN_DATA > needs_new_fetch > needs_new_table > answerable_now.
```

Why `answer_kind` is only a tiebreaker (measured on the bank):

| answer_kind | cases | what actually determines the hops |
|---|---:|---|
| `null` | 200 | ripple chain (`chain[i].gap_key`) |
| `explanation` | 223 | evidence text (concall/deck/AR) + a number to compare |
| `fact` / `text+quote` | 255 | the named store (`required_evidence`) |
| `ranking` | 109 | SCREEN (universe + metric) |
| `number` | 97 | FACTS (metric + period) |
| `NOT IN DATA` | 71 | the conversion is the answer; the chain decides whether it is justified |
| `list` / `date` | 75 | SCREEN / SERIES |

The **question text is never used to route**, only to fill slots (dates, period, entity hints).
A model that invents a hop is a defect: the chain comes from the master-bank row, which the
reviewer can diff against `CASE_MAP.jsonl`.

---

## 3. Multi-hop ripple execution

The 655 ripple hops in the bank reduce to five stages. Each stage returns a **set** that the next
stage consumes; the answer reports the chain, not just the endpoint.

```
stage 1  TRIGGER     macro_claim_target | commodity_price_daily | policy_events
         in:  claim_id or (series_code, move_pct, window) or policy_id
         out: target_kind, target_id, direction, magnitude, effective_date, known_at
stage 2  EXPOSURE    company_sector_pit × company_cost_structure / company_segment_pnl /
                     company_revenue_geography / company_import_content / company_fx_exposure
         in:  target set
         out: isin list with the *share* (of COGS, of revenue, of segment) + source doc
stage 3  TRANSMISSION  company_price_revision | order_book_contract | pass_through_history
         in:  isin list + trigger date
         out: dated mechanism rows (when the price moved, what contract basis)
stage 4  MARKET       EVENT window per isin (event_leakage_window / daily_price_delivery)
         out: abnormal return, delivery z, volume — measured, not assumed
stage 5  VERDICT      compare stage 3/4; if a hop is missing -> say which hop and stop there
```

Execution rules:

1. **A hop is a row, not a sentence.** Every stage must return a row with `known_at` and a source
   doc id. If the only evidence is prose in a chunk, the hop returns the chunk id and page and is
   labelled `text_only` (precision caveat).
2. **The direction is inherited, the magnitude is re-measured.** `macro_claim_target.direction`
   says "negative for cables"; the 20% copper move is recomputed from `commodity_price_daily`
   between the two dates the question names. Never take the magnitude from the claim text.
3. **Hop budget = 5.** Longer chains are declared unsupported rather than chained blindly; the
   bank's longest chain is 5.
4. **Partial answers are the norm, and must be worded as such.** 127/200 ripple cases are
   "partial" by construction; the answer lists hops answered (with evidence) and hops not in data.
5. **No circular look-ahead:** a stage-3 statement dated after `as_of` cannot justify a stage-2
   exposure. The PIT clause is on each stage's own table, not on the chain object.

Measured cost of the chain today (tables that exist): hop 1 policy 0.15 ms, hop 2 sector membership
0.015 ms, hop 3 price series 0.26 ms per company, hop 4 event window 0.01–0.07 ms. A 20-company
chain is ~15 ms of SQL; the 2 s budget is a search problem, not a ripple problem.

---

## 4. NOT IN DATA: decided by four gates, worded with what was checked

NID is a **result**, not an error. The assembler emits it only after all four gates:

| gate | test | example |
|---|---|---|
| G1 entity | `resolve` returns no ISIN valid at `as_of` | "the symbol did not exist on that date" |
| G2 emptiness | every hop returned 0 rows after its PIT filter, and each hop's `checked` list is non-empty | "no concall filed by that date" |
| G3 source declared absent | the case's blocker is `never` in `GAP` (paid, unpublished, out of scope) | consensus targets (paid), investor-level holdings (never published), refurb sales (no series) |
| G4 question kind | forecast or opinion-without-store | "what will the price be on Diwali 2027" |

Wording contract (the reviewer will sample these):

```
NOT IN DATA: <the exact fact asked>
Checked: <hop1> (<rows after PIT filter>), <hop2> (...), as_of <date>.
Nearest held: <doc_id/title, date> — it does not contain <the fact>.
Why: <one of: not filed by then | not published by any source | paid-only | forecast>.
To close: <table or fetch, e.g. company_segment_pnl from the AR segment note — 41 cases>.
```

Rules:

- Never say "no data" without the `Checked:` list; the list is what makes it verifiable.
- Never convert "we did not fetch it" into "it does not exist". The `status` field in
  `CASE_MAP.jsonl` separates `needs_new_fetch` (it exists, we have not fetched it) from
  `NOT_IN_DATA` (nobody publishes it, or it is a forecast).
- A partial answer is not a NID: name the missing hop inside the answer, keep the answered part.
- 14 cases are NID *by design* (9 `never`, 5 whose rubric asks for a NID statement). They count as
  answered only when the wording above is produced. The 77 `expected_nd` cases are different: they
  ask "if X is not held, say so" but the data path exists, so they are `needs_new_*`, not NID.

---

## 5. Hybrid search over chunks_v3

### 5.1 Why not "dense then filter"

Measured on this machine today: the Nemotron 4096-d index is 2.79 GB for ~170k vectors
(`vector_index_nemotron8b/chunk_vectors.npy`), the AR Qwen index 11.2 GB for ~684k, bge 2.6 GB for
~1.7M. The proposed corpus is ~3.4M chunks = **56 GB at 4096-d float32**. A brute-force scan is
dominated by disk bandwidth: at ~2 GB/s it is ~28 s, and it cannot be cached. Dense retrieval
therefore runs only on a **filtered candidate set**, and the system states when a chunk has no
vector (lexical-only degradation).

### 5.2 The pipeline (five stages, filter first)

```
S0  FILTER PUSHDOWN (SQL, indexed)                       measured
    isin = ? (+ doc_type, fiscal_period, known_at<=T, tag)  
      -> chunk ix_chunk_isin_known             0.08 ms  (Q25, live 2.9M-row table)
    corpus-wide: doc_type + known_at window    -> ix_chunk_type_known
    tag-scoped: chunk_tag(tag, chunk_id) PK    -> tag ids, join chunk   0.04 ms (P10)
    cap candidate set at 8,000 chunk_ids; if larger, add a filter (latest quarter, section)

S1  LEXICAL (FTS5 BM25) on the candidates
    SELECT rowid, bm25(chunk_fts) FROM chunk_fts
     WHERE chunk_fts MATCH :q AND rowid IN (candidates)  238 ms at 2.3M rows (Q15)
    corpus-wide path: MATCH first, LIMIT 2000 by rank, then apply the structured filter;
    if <20 survive, widen once (drop one filter) and record the widening in `degraded`.

S2  DENSE RERANK of the top 200 lexical candidates
    vectors from <model>.npy via chunk_vec_ref, cosine            1.62 ms for 2,000×4096
    chunks with no vector keep their lexical rank (degradation note: "lexical only")

S3  DETERMINISTIC BOOST RERANK (no model, no paid call)
    +0.15 exact isin match in header        +0.10 doc_type == asked type
    +0.10 section match (segment/notes/KAM) +0.08 speaker_role == management (guidance asks)
    +0.08 recency within the fiscal period  -0.20 doc_type == announcement and question asks numbers
    +0.10 tag match from chunk_tag          +0.05 number present (n_numbers > 0) for number asks

S4  ASSEMBLY: 6 passages max, ≤450 tokens each (≈2,700 tokens of text), 2 per document max,
    header + doc_id + page + known_at on every passage, plus a numbers table (≤20 rows) and
    the degradation notes. Total answer context budget: 6,000 tokens.
```

### 5.3 Interface

```
search_chunks(q, *, isin=None, doc_type=None, known_at_to, tag=None, fiscal_period=None,
              k=6, lexical_k=200, dense_k=200) -> {
  passages: [{chunk_id, doc_id, isin, doc_type, known_at, page_from, section, speaker_role,
              body, score, why: ["isin","bm25","dense","tag"]}],
  degraded: [{chunk_id, reason: "no_vector"|"filter_widened"}],
  plan: {filter_index, fts_rows, dense_rows, rerank_rows}
}
```

### 5.4 Failure behaviour (must be explicit, not silent)

- FTS5 unavailable → dense-only on the candidate set; the answer carries `degraded: fts_unavailable`.
- No query embedding (paid embedding disabled by default) → lexical + deterministic rerank only;
  `degraded: no_query_embedding` (this is the normal path for the pilot).
- Candidate set empty → do **not** fall back to corpus-wide search; return empty and let the
  assembler run gate G2. A silent corpus-wide fallback is how a "not in data" becomes a wrong answer.
- A passage whose `known_at > as_of` can never enter the set: the clause is inside S0/S1 SQL. The
  leakage test (`PIT_LABEL_AUDIT` pattern) asserts this on every pilot run.

### 5.5 Token budget per answer type

| answer_kind | passages | tokens text | numbers rows | total budget |
|---|---:|---:|---:|---:|
| `number` / `fact` | 2 | 500 | 20 | 1,500 |
| `text+quote` | 3 | 1,200 | 0 | 1,800 |
| `explanation` | 5 | 2,000 | 10 | 3,000 |
| `ranking` / `list` | 1 methodology | 400 | 50 | 1,800 |
| `date` / timeline | 3 | 1,000 | 0 | 1,400 |
| ripple (multi-hop) | 6 | 2,700 | 20/hop | 6,000 |

Hard cap 6,000 tokens; over budget, drop the lowest-scored passage and record it (never truncate a
quote mid-sentence — a truncated number is a wrong number).

---

## 6. Latency contract

| path | p50 measured | budget | where measured |
|---|---:|---:|---|
| resolve + 3 point lookups | 0.06 ms | 5 ms | Q01,Q02 |
| facts (one ISIN, one metric) | 0.02–9.6 ms | 50 ms | Q05–Q10,Q23,Q24 |
| screen (one date, one bucket) | 2.3–4.0 ms | 100 ms | Q17,Q28,P1,P2 |
| event window | 0.01–5.4 ms | 50 ms | D1,P6,P7 |
| policy/ripple hop 1 | 0.15 ms | 20 ms | Q11,P8 |
| search: filter + FTS + dense rerank | 238 + 1.6 ms | 900 ms | Q15, dense bench |
| assemble (6 passages + numbers) | ~20 ms | 100 ms | estimate, measured in the pilot |
| **worst-case chain (5 hops + search)** | **~270 ms** | **2,000 ms** | sum of the above |

The 2 s gate has ~7× headroom. The one thing that would blow it is a scan over an unindexed column:
`bse_announcements.ann` by symbol measured **2.4 s** (Q20, 1.9M-row scan) — which is why
`event_day0` exists and why the pilot adds `ann(symbol, DissemDT)` before any event query runs.

---

## 7. What the query layer never does

- Never post-filters PIT: `known_at` is in the SQL, not in Python after the fact.
- Never uses a symbol without its window: `symbol_at_time` comes from `symbol_isin_history`.
- Never treats `corporate_documents.doc_date` as a filing date (it is the crawl date).
- Never presents an opinion as evidence: `source_class='opinion'` is excluded unless the question
  explicitly asks for analyst views (0 master-bank cases do).
- Never answers a screen from current membership: `index_membership` is one snapshot (300 rows,
  `as_of=2026-09-30`); as-of screens use `company_membership_pit` or say they cannot.
- Never counts a `needs_new_fetch` case as answered: the status distinction is enforced in the
  re-run harness (`PILOT_SPEC.md §5`).
