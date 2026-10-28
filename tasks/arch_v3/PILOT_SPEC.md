# Pilot spec — the smallest build that can honestly measure the 1,030-case bank

Scope: build the tables the query layer needs for a **30-company, all-doc-type** pilot, run the
whole master bank through the router, and grade it. No full chunking, no re-embedding, no loading of
any production dataset beyond the pilot universe (golden rule step 4–5).

---

## 1. Pilot universe — exact ISINs

Selection rule (deterministic, reproducible with `.tmp/pick_pilot.py`): score every ISIN named in the
bank by `2 × cases + 3 if ARs held + 2 if concalls held + 1 if XBRL held + 1 if prices held + 2 if
>20 docs`, take the top 20, then one company per open-bank archetype not yet represented until 30.
These 30 ISINs are named in **362 of the 1,030 cases (35%)** — the pilot measures a third of the bank
end to end, and the remaining 668 are entity-level (industry/policy/market-wide) cases graded on the
T2 tables or by their declared status.

| # | ISIN | symbol | cases | AR | concall | XBRL | docs | px rows |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | INE040A01034 | HDFCBANK | 26 | 8 | 5 | 14 | 57 | 1,290 |
| 2 | INE455K01017 | POLYCAB | 23 | 6 | 24 | 61 | 90 | 1,290 |
| 3 | INE878B01027 | KEI | 22 | 8 | 7 | 62 | 82 | 1,290 |
| 4 | INE935N01020 | DIXON | 19 | 7 | 18 | 14 | 62 | 1,290 |
| 5 | INE263A01024 | BEL | 18 | 7 | 9 | 12 | 63 | 1,290 |
| 6 | INE930H01031 | KPRMILL | 18 | 7 | 3 | 12 | 82 | 1,290 |
| 7 | INE002A01018 | RELIANCE | 17 | 7 | 6 | 61 | 91 | 1,290 |
| 8 | INE415G01027 | RVNL | 16 | 10 | 6 | 59 | 44 | 1,290 |
| 9 | INE021A01026 | ASIANPAINT | 14 | 6 | 2 | 16 | 79 | 1,290 |
| 10 | INE040H01021 | SUZLON | 14 | 9 | 8 | 61 | 66 | 1,290 |
| 11 | INE615H01020 | TITAGARH | 14 | 9 | 6 | 51 | 73 | 1,332 |
| 12 | INE009A01021 | INFY | 13 | 9 | 9 | 62 | 73 | 1,290 |
| 13 | INE702C01027 | APLAPOLLO | 12 | 8 | 6 | 12 | 85 | 1,290 |
| 14 | INE733E01010 | NTPC | 12 | 9 | 6 | 59 | 60 | 1,290 |
| 15 | INE849A01020 | TRENT | 12 | 8 | 0 | 12 | 31 | 1,290 |
| 16 | INE019A01038 | JSWSTEEL | 11 | 8 | 5 | 12 | 90 | 1,290 |
| 17 | INE066F01020 | HAL | 10 | 6 | 3 | 12 | 42 | 1,290 |
| 18 | INE067A01029 | CGPOWER | 10 | 8 | 4 | 70 | 66 | 1,290 |
| 19 | INE775A01035 | MOTHERSON | 10 | 9 | 19 | 67 | 101 | 1,290 |
| 20 | INE114A01011 | SAIL | 9 | 8 | 6 | 58 | 51 | 1,290 |
| 21 | INE192R01011 | DMART | 9 | 8 | 1 | 63 | 52 | 1,290 |
| 22 | INE918Z01012 | KAYNES | 9 | 3 | 6 | 34 | 54 | 1,013 |
| 23 | INE481G01011 | ULTRACEMCO | 8 | 9 | 5 | 61 | 113 | 1,290 |
| 24 | INE646L01027 | INDIGO | 7 | 8 | 2 | 60 | 79 | 1,290 |
| 25 | INE081A01020 | TATASTEEL | 6 | 8 | 7 | 12 | 113 | 1,290 |
| 26 | INE467B01029 | TCS | 6 | 8 | 5 | 64 | 52 | 1,290 |
| 27 | INE0MWH01014 | TRUALT | 5 | 1 | 0 | 14 | 23 | 276 |
| 28 | INE417T01026 | POLICYBZR | 5 | 6 | 5 | 37 | 48 | 1,277 |
| 29 | INE634S01028 | MANKIND | 4 | 4 | 1 | 28 | 56 | 893 |
| 30 | INE020B01018 | RECLTD | 3 | 10 | 3 | 58 | 49 | 1,290 |

Why these 30 are representative: 11 industries (banks, cables, consumer durables, defence, textiles,
retail, power, rail, IT, metals, insurance); large/mid/small tiers; banks (HDFCBANK, RECLTD) so the
NBFC taxonomy and the loan-repricing tables are exercised; TRUALT and KAYNES are the thin-data names
that test the NID path; the cables cohort (POLYCAB, KEI, APLAPOLLO) is the ripple bank's core chain.

---

## 2. Documents and counts (measured for these 30 ISINs)

`corporate_documents` for the 30 ISINs: **2,027 rows** — 837 OTHER_FILING, 529 CONCALL_TRANSCRIPT,
381 ANNUAL_REPORT, 220 ANNOUNCEMENT, 36 INVESTOR_PRESENTATION, 15 FINANCIAL_RESULT, 9
OFFER_DOCUMENT.

| doc type | held (30 ISINs) | FY25+ | already on disk | must fetch before chunking |
|---|---:|---:|---|---|
| Annual reports (`ar_docs`) | 222 | **64** | 146 of 300 sampled ARs are on D: (overhaul §Manager review) | the rest, from `corporate_documents.source_url` / BSE |
| Concall transcripts (`cc_docs`) | 187 | 39 in 2026 | 0 on D:; Drive holds 2,289 all-years | BSE "Earnings Call Transcript" filings (subcategory-keyed) |
| Investor decks (`deck_sources` / `pages`) | 460 / **12,935 pages** | ~ | `D:/RealityEngine/raw/decks_full` | none (re-chunk only) |
| XBRL results (`filings`) | 1,218 | **399** | local XML not archived; facts are loaded | none for numbers; XML only if segment contexts are re-parsed |
| Results notes (PDF) | **0** | 0 | none | BSE "Result" filings (G9) — the largest fetch, dedupe per company-quarter first |
| Announcements | 220 rows; attachments 0 text-extracted | — | none | BSE attachments (NG01); or rely on the 220 titles for a title-only pilot |

Expected v3 volume for the pilot: **~1,000 documents → ~78,000 chunks** (AR 222 × 248 ≈ 55k,
concalls 529 × 18 ≈ 9.5k, decks 12,935 slides, announcements 660), i.e. 2.3% of the 3.4M full corpus.
Parse time ≈ 23 min single-threaded, 3–4 min at 8 workers; FTS add ~1 min.

---

## 3. Tables built for the pilot

Two tiers, because the deterministic tables are cheap enough to build for the whole bank universe
while the reader tables are not.

**T1 — reader/chunk tier, the 30 ISINs only (pilot DBs):**

| table / store | rows (pilot) | why it must be in the pilot |
|---|---:|---|
| `chunks_v3.db` doc/chunk/chunk_fts/chunk_tag/tag_vocab/coverage_scorecard | ~1,000 docs / ~78k chunks | the EVIDENCE planner and the tag-precision gate |
| `result_note` | ~120 (30 × 4 quarters, after the fetch) | G9, the "note 5 of the results" cases |
| `company_segment_pnl` | ~600 (30 × 6 years × 3 segments) | 41 cases; validates the AR segment-note parser |
| `company_cost_structure`, `company_import_content`, `company_fx_exposure` | ~1,500 | R01/R07/R08 chains on the cables cohort |
| `company_price_revision`, `order_intake`, `order_book_contract` | ~2,000 | the reader path + the fixed-price contract question |
| `company_capacity_utilisation`, `capex_project` | ~1,200 | A01/A02/A14 (commissioning slip, ramp, guidance) |
| `company_working_capital`, `company_interest_cover`, `company_debt_mix` | ~2,000 | reddit balance-sheet / earnings-quality / ROIC cases |

**T2 — deterministic tier, the full 489-ISIN bank universe:**

| table | rows | why full universe |
|---|---:|---|
| `company_state_daily` (+ `price_band_daily`, `mcap_bucket_interval` views) | ≤13.4M (pilot can start 2019+ for all 489: ~2.2M) | every SCREEN case, valuation, index flow |
| `company_membership_pit`, `company_sector_pit`, `company_theme_pit` | ~3k | ranking by index/industry/theme |
| `company_metric_series` + `xbrl_concept_map` | ~120k for 489 ISINs | 62 metric-series cases, all peer compares |
| `company_result_pit`, `company_ownership_pit` | ~40k | results-day and promoter cases |
| `event_day0`, `event_leakage_window` | ~150k for 489 ISINs | 24 + 23 event cases |
| `macro_claim`, `macro_claim_target`, `macro_doc`, `event_calendar` | ~60k | 63 policy→company cases |
| `commodity_price_daily`, `freight_rate_daily`, `rainfall_daily`, `rural_wage_series` | fetched | 62 ripple triggers |

Not built: `fno_oi_daily` (needs the F&O bhavcopy fetch — the 8 OI/PCR cases stay `needs_new_fetch`),
`opinion_calls` (0 cases), `consensus_target` (never), `tariff_exposure`/`import_duty_structure`
(fetch), `supply_link` (curation), `market_share_shift` (industry volumes), the four NID-only areas.

---

## 4. Build order (dependencies, one writer per DB)

```
0. FIXES (30 min)                                   [no dependency]
   idx on corporate_documents(isin, publication_date), ann(symbol, DissemDT)

1. market_state.db — deterministic T2                [0]
   1a security_alias/isin_rekey_map  (G0)
   1b company_state_daily + views        <- px_daily, XBRL paid-up, price_bands, circuit_hits
   1c membership/sector/theme intervals  <- index_membership snapshot, company_industry
   1d company_ownership_pit              <- shp_index
   1e company_result_pit                 <- xbrl filings
   GATE: SCREEN/T2 cases answerable; 0 rows with known_at > as_of; 3 timed queries < 300 ms

2. metric_state.db — deterministic T2                [1e]
   2a xbrl_concept_map (60 metrics)      <- xbrl facts 554 concepts (hand map)
   2b company_metric_series              <- 2a + filings
   2c company_working_capital / interest_cover   <- 2a
   2d company_revenue_geography          <- ar_facts segment (geographical)
   2e company_debt_mix                   <- ar_facts borrowings_maturity
   2f company_segment_pnl                <- ar_facts category='segment'
   GATE: FACTS hop answers 80% of the metric cases on the 30 ISINs; spot-check 20 numbers vs filing

3. event layer                                        [1b, 1e]
   3a event_day0 (15:30 rule)            <- truth.events + prices
   3b event_leakage_window               <- 3a + prices/delivery/insider/deals
   GATE: A18-style session attribution correct on 20 hand-checked filings (0 off-by-one)

4. chunks_v3.db — T1                                  [0, 1b, 2b]  (needs originals; stream B runs in parallel)
   4a doc registry (known_at resolution chain)
   4b parse + chunk (chunker_v2 per doc type) + FTS
   4c deterministic tags + chunk_tag; model tags only after the 300-chunk check
   GATE: 78k chunks, header fields 100%, tag precision >= 0.90 on 300 hand-checked chunks

5. reader tables — T1                                 [4]
   5a cost structure / import content / FX      5b price revision / order intake / contracts
   5c capacity / capex projects                 5d working capital reader corrections
   GATE: each table's 10 sample rows trace to a doc_id+page+quote (no unsourced numbers)

6. macro_claim layer                                  [4]
   6a macro_doc (PIB/budget/RBI known_at)         6b macro_claim + claim_target
   GATE: 30 claims hand-checked vs the PIB paragraph (precision >= 0.90)

7. the 1,030-case re-run (§5)                         [1-6]
```

Dependencies in words: nothing needs chunks except EVIDENCE and the reader tables; nothing needs the
event layer except EVENT; `macro_claim_target` needs `chunks_v3.doc` ids but not chunk text (the claim
extractor reads the original). That is why streams 1–3 can run while the raw originals download.

---

## 5. Re-run harness — how 1,030 cases execute and are graded automatically

One runner, no per-case hand work:

```
python -m reality_engine.toolbelt.run_master_bank \
  --case-map tasks/arch_v3/CASE_MAP.jsonl --bank tasks/master_bank/MASTER_BANK.jsonl \
  --as-of-from-case --out tasks/arch_v3/rerun/<run_id>/ [--only T1|T2|all] [--seed 0]
```

**Execution.** For each case, in `CASE_MAP` order: take `planner_chain`, fill slots from the case
(`entities` → ISINs via RESOLVE, `period`/`as_of` → cutoff), call each planner in order, pass the
previous hop's row set, and assemble. Every planner call is logged with: SQL text, params, plan,
rows, ms, and the PIT clause it applied. No model is in the loop for routing; a model (local, free)
is used only to compose prose from the assembled rows, and the prose is checked against the rows
(numbers must appear verbatim in the row set).

**Grading labels** (one per case, plus a reason string):

| label | test | counts toward 95%? |
|---|---|---|
| `ANSWERED` | every hop returned rows; the answer's numbers/quote match the rows; no PIT flag | yes |
| `ANSWERED_PARTIAL` | some hops answered, missing hops named with the NID wording | yes, only if the rubric allows partial (the 77 `expected_nd` + ripple partial cases) |
| `BLOCKED_SCHEMA` | a hop failed because its table is not in the pilot (should equal `needs_new_table` for unbuilt tables) | no |
| `BLOCKED_FETCH` | as above for `needs_new_fetch` | no |
| `NOT_IN_DATA_JUSTIFIED` | NID wording with a complete `Checked:` list, and the case's status is NID-class | yes |
| `NOT_IN_DATA_UNJUSTIFIED` | NID without the checked list, or NID for a case whose status is answerable | **failure** |
| `WRONG` | a number contradicts the stored row, a quote is not verbatim, a date is off, or the answer uses post-`as_of` data | **failure** |

**Automatic checks per case (each is a hard assert in the harness):**

1. **Row fidelity** — every number in the answer appears in the hop's returned rows (string match on
   the formatted value); every quote is a substring of a returned chunk/quote row.
2. **PIT** — every row used has `known_at <= as_of`; the harness re-runs each SQL with `known_at >
   as_of` injected as a filter and asserts 0 rows. Any hit is a PIT violation and fails the run.
3. **Resolve** — the ISIN used equals the case's entity ISIN resolved at `as_of`; a mismatch is
   `WRONG`.
4. **Completeness** — if the answer omits a hop the chain declares, it must say why.
5. **Determinism** — the same case run twice returns the same rows (order-insensitive compare);
   any difference is a defect (the router is deterministic).
6. **Cost** — per-case ms recorded; search calls recorded separately for the p95 gate.

**Artifacts per run:** `results.jsonl` (case → label, hops, rows hash, ms, degradation notes),
`failures.md` (grouped by label and by blocker), `pit_violations.jsonl`, `timings.json`
(p50/p95 by planner), `tag_precision.csv` (300 sampled chunks, hand label vs tagger),
`regressions.md` (the 30 `regression=true` cases).

**Cohorts for reporting:** the 30 regressions; the 30 T1 ISINs (362 cases); per bank; per family;
per status. The gate is computed on **all 1,030**, with `BLOCKED_*` counted against the design, not
excused.

---

## 6. Checklist gates (exact, with the command that proves each)

| gate | pass condition | command / evidence |
|---|---|---|
| **CASE_MAP integrity** | 1,030 rows, unique mids, every row has `planner_chain` + `status`; every held `table.column` exists | `python -c "import json,sqlite3; ..."` (the acceptance check in the brief) and `.tmp/verify_map.py` → `bad columns: 0, unknown tables: 0` |
| **schema parses** | `sqlite3 :memory: < SCHEMA_V3.sql` | `.tmp/check_schema.py` → `parse ok: tables 73 views 3 indexes 41` |
| **answer rate** | ≥95% of 1,030 are `ANSWERED` or `ANSWERED_PARTIAL` (allowed) or `NOT_IN_DATA_JUSTIFIED`; `WRONG` = 0 | `rerun/<id>/results.jsonl` label counts |
| **PIT** | 0 violations: 0 rows with `known_at > as_of` in any hop | `rerun/<id>/pit_violations.jsonl` empty |
| **regressions** | **30/30** `regression=true` cases `ANSWERED` | `rerun/<id>/regressions.md` |
| **search speed** | p95 < 2 s over all EVIDENCE calls; structured p95 < 300 ms | `rerun/<id>/timings.json` |
| **tag precision** | ≥0.90 over 300 hand-checked chunks (Wilson 95% lower bound reported) | `rerun/<id>/tag_precision.csv` + `coverage_scorecard` |
| **answer fidelity** | 100% of numbers/quotations trace to a returned row | harness assert per case |
| **degradation honesty** | every answer using a thin source carries a degradation note (no silent gaps) | harness assert; AGENTS.md §3.13 |

If the answer rate lands below 95%, the run report must name the blocking statuses
(`BLOCKED_SCHEMA` / `BLOCKED_FETCH` / `NOT_IN_DATA_UNJUSTIFIED`) and the cases, not "we ran out of
time". The design's projection is 99.1% with the fetch stream and 79.6% without it, so the pilot can
only pass ≥95% once the commodity/originals/bhavcopy fetches have landed.

---

## 7. What the pilot explicitly does not do

- No full chunking, no tagging/embedding of the full corpus (`chunks_v3.db` stays pilot-sized).
- No re-embedding: the existing Nemotron/Qwen/bge indexes are read-only inputs; the pilot's new
  chunks are lexical-only unless the local ONNX/vLLM embedder is available (free, local), and that
  is recorded as a degradation, not hidden.
- No paid calls: no paid embedding, no paid reader; the model tagger uses the free local readers and
  is gated at 0.90 precision.
- No production writes: all pilot DBs are new files (`*_pilot.db`), `equity_intelligence.db` is
  opened read-only.
