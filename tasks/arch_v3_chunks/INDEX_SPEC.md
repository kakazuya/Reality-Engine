# INDEX_SPEC — chunks_v3: chunking, tags and the search index (2026-10-28)

Companion to `tasks/arch_v3/` (case map, schema, query layer). This file owns **how a document
becomes a searchable chunk** and **how those chunks are indexed**, measured on a 48-document
sample of real originals. Implementation: `reality_engine/processing/chunker_v3.py`
(reuses `chunker_v2` structure detection), prototype DB `.tmp/chunks_proto.db`, tests
`reality_engine/tests/test_chunker_v3.py` (17 tests, offline).

Read-only on D: and on every DB. No network, no embeddings computed, no commits.

---

## 1. Chunk contract

Every chunk is a **verbatim slice of the parsed original** (`body` case-preserved, `span_start/end`
exact). The header carries every field the planner filters on, so a header hit alone pins the
company and the point in time:

```
SYMBOL · ISIN · <doc label> · <fiscal period> · <section/speaker> · p<page> · known <ISO ts>
TITAN · INE280A01028 · Concall transcript · FY26Q3 · Q&A · p8 · known 2025-11-08T16:47:31
```

Fields on `chunk` (denormalised from `doc`): `isin`, `symbol_at_time`, `doc_type`, `source_class`,
`known_at`, `event_date`, `fiscal_period`, `section`, `speaker`, `speaker_role`, `unit_kind`,
`page_from/page_to`, `span_start/span_end`, `n_numbers`, `forward_looking`, `quality_grade`,
`pit_confidence`, `content_tags`.

`known_at` comes **only** from the filing record (`bse_dissem`/`nse_dissem` = 1.0,
`filing_date` = 0.9, `body_letterhead` = 0.8, `folder_name` = 0.6, `drive_btime` = 0.5).
`upload`/`crawl` raise `ValueError` — a crawl date can never become a chunk timestamp.
`doc_date` (crawl) is never read by the chunker.

### Units per doc type

| doc type | unit | measured chunks/doc | mean chars | notes |
|---|---|---|---|---|
| concall | speaker turn; **one Q&A pair** = question + all answers; opening remarks per speaker | 31.6 | 1,707 | Q&A cap 2,200 chars (~550 tokens), split at turns then sentences; continuation repeats the question in `section` |
| deck | **one slide** per chunk | 25.4 | 964 | a slide <250 chars merges forward inside its section; divider slides set the section |
| annual_report | **one note/schedule** per chunk, heading path in `section` (`MD&A > Segment > Note 5`) | 340 (sample); 247 (corpus average) | 3,159 | tables protected from cuts |
| results_notes | **one note block** from the notes section onward | 24.0 | 2,329 | cut starts at the `Notes to the financial results` marker; P&L/cover pages are not retrieval units; no marker → whole filing, grade B |
| announcement | whole doc when ≤6,000 chars (~1,500 tokens), else heading split | 1.2 | 2,200 | category string also feeds tags |

Speaker roles: management / analyst / moderator. The role on a Q&A chunk is the **speaker carrying
most characters** (normally the management answer), not the first speaker. Measured on the sample:
167 management, 120 analyst, 27 moderator chunks.

---

## 2. Deterministic tags

Closed vocabulary in `chunker_v3.TAG_VOCAB` (content, event, numeric axes), written to
`tag_vocab`; a tag outside it cannot be written. Rules are regex on the chunk body alone — no
model, no inference from the doc type. Model tagging stays off until the §4.6 precision gate
passes.

Structural tags (free): `section:opening_remarks`, `section:qa`, `section:mda`, `section:notes`,
`section:related_party`, `section:segment`, `speaker_role:*`, `has_number`, `forward_looking`,
`unit:inr_crore`, `unit:inr_lakh`, `unit:percent`, `unit:bps`, `unit:usd`.
Content tags: the 16 spec tags (`guidance`, `order_book`, `capacity`, `capex`, `margin`, `pricing`,
`demand`, `debt`, `working_capital`, `m_and_a`, `regulatory`, `management_change`,
`dividend_buyback`, `risk`, `accounting_note`, `analyst_view` — the last only for opinions).

**Measured precision (50 chunks, one per 10 chunks of each doc type):**

| run | tag instances | correct | precision |
|---|---:|---:|---:|
| first rules (spec text almost verbatim) | 91 | 48 | **0.53** |
| after tightening (this code) | 55 | 43 (+6 unverifiable) | **0.88 over 49 verifiable / 0.78 over all 55** |

First-run defect classes, now fixed or bounded: `regulatory` fired on the **SEBI LODR boilerplate**
("In terms of the SEBI (Listing Obligations…)"; "Regulation 30 of the SEBI"); `risk` fired on
"provisions for employees" and "provisions of Sections"; `forward_looking` fired on document titles
containing `FY25` and on politeness ("would like to inform", "will also be available"); `capacity`
fired on "utilisation of funds" and "commission income"; `debt` fired on "operating leverage" and
"leverage our strength"; `management_change` fired on role titles in a cover letter; `pricing`
fired on "lease rental discounting".

Still failing the gate: point estimate 0.88 < 0.90 and the Wilson 95% lower bound on n=49 is
≈0.76 < 0.85. **Deterministic tags are not rolled out as fact** — they are candidate tags until a
larger hand-check or the model pass clears §4.6. `forward_looking` is 85% of concall chunks
(it matches ordinary "will/expect/should" prose) and is not discriminative; use the tag only as a
soft filter.

Entity mentions: `EntityResolver` (built from `master_companies`, 6,172 names / 5,936 symbols)
resolves exact normalised name and symbol mentions to ISIN in a separate table
`chunk_entity(isin, symbol, chunk_id)`. A 6.8k-ISIN tag cannot live in `tag_vocab`; this is an
additive change to §2.2. The document's own ISIN is excluded from mentions.

---

## 3. FTS5 tokenizer — measured choice: `unicode61 remove_diacritics 2`

Both tokenizers were built over the same 1,727 chunks and queried with the same 15 questions.

| tokenizer | top-5 hit | MRR | median | p95 |
|---|---:|---:|---:|---:|
| **unicode61 remove_diacritics 2** | **12/15 (0.80)** | **0.589** | **10.3 ms** | **56.9 ms** |
| porter unicode61 remove_diacritics 2 | 10/15 (0.67) | 0.572 | 8.3 ms | 67.2 ms |

Porter loses two questions and adds nothing on the rest. On financial text it over-stems
(`guidance`→`guidanc`, `securities`→`secur`) and merges terms that must stay distinct. Missing
plural forms (`product` vs `products`) are cheaper to fix on the **query** side: the query builder
adds a de-pluralised form and the tag-vocabulary synonyms below. That is what takes the query from
10/15 to 12/15 (measured: `unicode_idf` 10/15 → `unicode_best` 12/15).

Tokenisation of the tokens the spec names (SQLite FTS5, verified by inserting a probe row):

| text | tokens |
|---|---|
| `FY25` | `fy25` (one token; `Q2FY25` → `q2fy25`) |
| `Rs. 1,234 crore` | `rs`, `1`, `234`, `crore` |
| `₹1,234 crore` | `1`, `234`, `crore` (`₹` is a separator) |
| `crores` | `crores` (≠ `crore`; query expansion adds `crore`) |
| `EBITDA margin 21.24%` | `ebitda`, `margin`, `21`, `24` (the `%` is a separator) |

Consequence for design: **numeric equality is not FTS's job.** `1,234` and `1234` do not match
each other. Exact numbers come from `facts`/`xbrl`/`ar_facts`; the EVIDENCE planner must send the
passage query, not a number comparison. A query-side number normaliser (insert Indian comma
grouping, then OR the ungrouped form) is a cheap follow-up if numeric passages are ever ranked.

---

## 4. Filter columns, composite indexes, pre-filtering

```sql
CREATE INDEX ix_chunk_isin_known ON chunk(isin, known_at);
CREATE INDEX ix_chunk_type_known ON chunk(doc_type, known_at);
CREATE INDEX ix_chunk_known      ON chunk(known_at);
CREATE INDEX ix_chunk_fiscal     ON chunk(fiscal_period);
CREATE INDEX ix_chunk_tag_chunk  ON chunk_tag(chunk_id);
-- chunk_tag PK (tag, chunk_id): "all chunks with tag X" is a PK range scan
CREATE TABLE chunk_entity(isin TEXT, symbol TEXT, chunk_id INTEGER,
                          PRIMARY KEY (isin, symbol, chunk_id)) WITHOUT ROWID;
```

The planner's normal query shape is `isin + doc_type + known_at <= as_of (+ tag / fiscal_period /
page)`. All of it is applied **in SQL before ranking**; FTS5 is joined to the already-filtered row
set, so the `MATCH` never runs over the 5M-chunk corpus:

1. filter `chunk` on `isin`, `doc_type`, `known_at <= as_of`, optionally `fiscal_period`, optional
   `page_from <= N AND page_to >= N`, and `chunk_tag` for a tag filter;
2. `JOIN chunk_fts ON chunk_fts.rowid = chunk.chunk_id WHERE chunk_fts MATCH ?`;
3. `ORDER BY bm25(chunk_fts, 0.2, 1.0)` (header weight 0.2, body 1.0);
4. take top-50 → rerank → top-k with provenance.

Measured filter selectivity on the 15 questions: **13–39 candidate chunks** (median 33), one
outlier at 294 (RELIANCE AR on 187 pages). Latency with this order: median **10.3 ms**, p95
**56.9 ms** on 1,727 chunks — the whole EVIDENCE hop is well inside the pilot's 2 s p95 gate.

Query construction (measured best of five): content words only; drop question/date/entity words;
drop terms with corpus DF > 10%; add tag-vocabulary synonyms (`profitability → profit, ebitda,
breakeven`; `margin → ebitda`; `products → product`; `tariff → duty, customs`; `capacity →
commissioned, plant`; `guidance → expect, target`); de-pluralise; extract `page N` into the page
filter; OR the rest. An OR-of-everything query scores 9/15, the filtered-rare-term query 10/15,
the full builder **12/15**.

### Measured 15 EVIDENCE questions (master bank → sample)

| mid | company | doc | top-5 rank | missed because |
|---|---|---|---:|---|
| MB0464 | SIEMENS | concall FY27Q1 | miss | question is a two-company copper/margin comparison; the call's margin sentence (`commodity prices`, p7) loses to pages mentioning Siemens in the header |
| MB0930 | PAYTM | concall FY25Q3 | 2 | — |
| MB0931 | ETERNAL | concall FY25Q4 | 4 | — |
| MB0898 | ETERNAL | concall FY25Q4 | 3 | — |
| MB0909 | TITAN | concall FY26Q3 | 1 | — |
| MB0460 | TITAN | concall FY26Q3 | 1 | — |
| MB0497 | LUPIN | concall FY25Q4 | 1 | — |
| MB0329 | ECOSMOBLTY | concall FY26Q4 | 1 | MOU absent from this call; margin guidance found |
| MB0900 | PAYTM | concall FY25Q3 | miss | "which metric should the valuation be judged on" shares no vocabulary with the passage |
| MB0024 | CHEMCON | deck 2026-05-22 | 1 | — |
| MB0262 | FLUOROCHEM | deck 2026-08-12 | 4 | — |
| MB0266 | BIKAJI | deck 2026-05-21 | miss | product-mix slide says `PRODUCT MIX` (singular); plural expansion on the query did not reach top-5 |
| MB0284 | REFEX | deck 2026-07-29 | 1 | page-31 filter collapses 34 chunks to 1 |
| MB0286 | DCMSHRIRAM | deck 2026-05-13 | 1 | page-18 filter likewise |
| MB0034 | RELIANCE | AR FY26 | 2 | — |

**Top-5 hit rate 12/15 = 0.80, MRR 0.589, median 10.3 ms, p95 56.9 ms.** The three misses are
lexical-gap cases, not chunk-boundary cases: the gold passage exists and is correctly chunked, but
the question's words do not occur in it. That is exactly the work the dense half + rerank must do;
it is not a reason to change chunk boundaries.

Per doc type: concall 7/9, deck 4/5, annual report 1/1.

---

## 5. Dense index layout (designed, not computed)

No vectors are computed here. Layout constraints from the real corpus and the existing stores:

- **Per doc type, not one global index.** Each type already has its own model and its own filter
  population: `vector_index_nemotron8b` (4096-d) for concalls, decks and announcements;
  `vector_index_qwen8b_ar` (4096-d) for annual reports. A global index would force one model on all
  types and defeat the isin/doc-type pre-filter.
- **Filtered path = exact scan, no ANN.** The planner's shape returns 13–300 candidates. Store each
  shard as an int8 memory-mapped array indexed by `chunk_id`; gather the candidate ids from SQL and
  dot products on 300 × 4096 int8 is negligible (<1 ms). Ann-indexing a filtered query would only
  add recall loss.
- **Global path (no isin filter) = IVF-PQ.** For market-wide search use IVF-PQ on the doc-type
  shard: `nlist=4096, m=64, nbits=8`, `nprobe=16`. Full precision is not needed for a first pass
  because a cross-encoder reranks the top-50.
- **Dimension 4096**, matching the models already paid for. Do not introduce a new dimension.

Sizes for ~4.97M chunks (projection in §6):

| representation | per vector | total |
|---|---:|---:|
| float32, 4096-d | 16 KB | 79.6 GB |
| float16, 4096-d (storage) | 8 KB | 40.7 GB |
| int8, 4096-d (filtered scan, mmap) | 4 KB | 20.4 GB |
| IVF-PQ, m=64, 8-bit (global) | 64 B | 0.32 GB |

The AR shard is 3.55M of the 4.97M chunks (71%), so AR decides the budget: 29 GB float16 or
14.5 GB int8. On the 12 GB target GPU only the IVF-PQ index plus the queried shard's pages fit;
the filtered path must stay mmap/CPU.

RRF fusion: FTS top-50 and dense top-50 → `score = Σ 1/(60 + rank)`, take top-50.

Rerank: one cross-encoder pass on the fused top-50 (Nemotron-3.5-Rerank-8B, already the candidate
for AR) → top-10 with `(doc_id, page, section, known_at)` provenance. Budget ~0.0007 USD/search
per the state hand-off; not measured here.

---

## 6. Expected size and time for the full corpus

Counts from the architecture doc's FY25+ scope (concalls 9,390 · decks 12,954 · ARs 14,377 ·
results notes ~30,000 with notes after dedupe · material announcements ~65,000). Per-doc averages
are the sample's, except AR where the corpus average (247 chunks/doc, measured on the 8,265
already-chunked ARs) is used instead of the sample's 340 — the sample is three large integrated
reports.

| source | docs | chunks/doc | chunks | text (GB) | parse+chunk s/doc | single-process hours |
|---|---:|---:|---:|---:|---:|---:|
| concall | 9,390 | 31.6 | 296,724 | 0.50 | 0.57 | 1.5 |
| deck | 12,954 | 25.4 | 329,032 | 0.32 | 0.43 | 1.5 |
| annual report | 14,377 | 247 | 3,551,119 | 11.2 | 7.22 | 28.8 |
| results notes | 30,000 | 24.0 | 720,000 | 1.68 | 0.83 | 6.9 |
| announcement (material) | 65,000 | 1.2 | 78,000 | 0.17 | 0.09 | 1.6 |
| **total** | **131,721** | | **4,974,875** | **13.9** | | **40.3 h** |

- **chunks_v3.db with one FTS index:** the prototype is 12.9 MB for 4.50 MB of chunk text with
  *two* FTS indexes (2.88×); removing the porter index gives ≈2.16× text, so **≈30 GB** for the
  full corpus (range 25–35 GB). Text alone is 13.9 GB; the FTS index is the other half.
- **Dense side:** 40.7 GB float16, 20.4 GB int8, 0.32 GB IVF-PQ (§5).
- **Run time:** 40.3 h single process, dominated by AR parsing (28.8 h, PyMuPDF). With 8
  processes ≈ 5–6 h wall clock, I/O-bound on D:; run ARs first and cap workers at 6–8 so the
  spinning disk is not thrashed.
- Sample measured build (48 docs, 1,432 pages, 1,727 chunks): **41 s**, 12.9 MB DB, 0 failures.

Macro sources (PIB 84k, budgets ~400, RBI ~250, news ~30k) are outside this sample and their
spec targets (~420k + 30k + 8k + 150k chunks) would add ≈0.6M chunks and ≈2 GB text.

---

## 7. Where this changes the reviewer's spec, and why

1. **Results-notes unit.** Reviewer: "one note block". Implemented as: cut the filing at the
   `Notes to the financial results` marker, then one note per chunk; no marker → whole filing and
   grade B. Reason: the P&L/cover pages were becoming 25% of chunks and never answer a "note N"
   question.
2. **Announcement threshold** = 6,000 chars ≈ 1,500 tokens at 4 chars/token. Same intent, but the
   chunker must not depend on a tokenizer at parse time.
3. **Q&A cap 2,200 chars (~550 tokens)** instead of 900 tokens. Reason: v2's cap already fits every
   8k-context embedder and the existing rerank window; 900 tokens would split answers that the
   bank's questions quote whole.
4. **Speaker role = dominant speaker of the chunk**, not the first speaker. Reason: a Q&A pair is
   one chunk; tagging it `analyst` hides management guidance from role filters. `speaker` keeps the
   asker, `speaker_role` now names the majority voice.
5. **`chunk_entity` table added** (not in §2.2). Reason: entity mentions are multi-valued and keyed
   by 6.8k ISINs; they cannot be rows in `tag_vocab`. `PRIMARY KEY(isin, symbol, chunk_id)` makes
   "chunks mentioning ISIN X" a range scan.
6. **`page_from/page_to` are filters, not decoration.** A deterministic `page N` extractor took
   REFEX and DCM Shriram from miss to rank 1; the planner should always use it when the question
   names a page.
7. **Tokenizer: unicode61, not porter** (measured 12/15 vs 10/15), plus query-side plural/synonym
   expansion. The inverse choice (porter at index time) was the obvious default and it loses.
8. **Tag rules tightened against boilerplate** (see §2). The spec's regex examples fire on SEBI
   LODR citations and safe-harbour text; that is a recall/precision trade that the 0.90 gate cannot
   absorb.
9. **Explicit AR projection at 247 chunks/doc**, not the sample's 340. The sample over-represents
   300-page integrated reports; the corpus average is measured.

---

## 8. Boundary and tag hand check (50 chunks, 10 per doc type)

Boundary rule: a chunk passes when it starts and ends at a structural boundary (speaker, slide,
heading, page/table break) and does not cut a sentence or a table row.

| doc type | boundary OK | failures |
|---|---:|---|
| concall | 8/10 | 2 oversize opening remarks cut mid-sentence |
| deck | 10/10 | — (one slide per chunk, page boundaries are the unit) |
| annual report | 5/10 | 5 oversize notes cut mid-sentence (`note_cont` starts/ends lowercase) |
| results notes | 8/10 | 1 cover letter cut mid-sentence, 1 dot-leader/table header |
| announcement | 10/10 | — (whole-doc or heading split) |
| **total** | **41/50 = 0.82** | |

The AR failures are all the same root cause: `chunker_v2._split_long` takes the last line boundary
inside `MAX_CHARS`, and PyMuPDF text has few line breaks inside a note. Fix before the full run:
extend the cut forward to the next sentence end within +15% of `MAX_CHARS` and mark the piece
`note_cont` with `(cont.)` in `section`. That is a small change in v2's splitter, not in the unit
detection, so it can be done without re-opening the 2.05M-chunk AR store.

Tag precision and its gate are in §2.

---

## 9. Open problems

- **Tag gate:** 0.88 verifiable / 0.78 all, below 0.90 + Wilson 0.85. Do not treat content tags as
  facts yet; a 300-chunk per-type stratified check (spec §4.6) is still owed.
- **`forward_looking` is not discriminative** (85% of concall chunks). Either model-gate it or
  drop it to a soft hint.
- **Lexical gap on 3/15 questions** (SIEMENS commodity/margin, PAYTM valuation metric, BIKAJI
  product mix). The dense + rerank path must close these; if it does not, the chunk unit is not the
  problem.
- **Scanned documents:** RAILTEL (93% image-only) yields 1 chunk and no retrievable text. The
  quality grade is C, but the OCR route is not part of this chunker; the pilot must gate on
  `quality_grade` and count C docs as NOT IN DATA rather than as chunking failures.
- **Results-notes sample:** the 158 held PDFs are 10 large banks; the master bank's note-5 cases
  (DNAMEDIA, GTL, ATGL, RACE, BALMLAWRIE, GLOSTERLTD) are not among them, so note-5 retrieval
  cannot be measured until those filings are fetched. The chunker path is exercised (240 chunks,
  55% with tables) but the question set does not include it.
- **No dense vectors computed** (task rule): dense numbers in §5–§6 are arithmetic from chunk
  counts and dimension, not measured retrieval quality.
