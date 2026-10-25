# Task C1 + C2 — structure-aware chunker v2 and a retrieval quality set

## Goal
1. **C1:** a deterministic chunker (`chunks_v2`) that follows each document's own structure. Header lines come from
   metadata and need no model calls.
2. **C2:** a labelled set of 200 query→passage pairs, plus a harness that scores any chunking × retrieval setup on
   recall@10 / MRR.

Together they answer one question before any money is spent: do v2 chunks retrieve better than today's
length-cut chunks?

## Read first
- `tasks/optimizations/LEARNING_ARCHITECTURE.md` section 2: the chunking rules, re-chunk backfill, topic-change
  splitting.
- `tasks/optimizations/measure/EVAL25.md`: question style, 25 questions.
- The current chunker is in `reality_engine/processing/document_parser.py`. `document_chunks` in
  `equity_intelligence.db` currently holds 340,887 Nemotron-embedded chunks:
  - 83.5% concall transcripts (15,618 docs, average 2,386 chars);
  - 7.0% PIB releases;
  - 2.7% annual reports (81 docs);
  - 2.4% Economic Survey;
  - 2.2% investor decks (1,701 docs).
- The 2026-10-19 embedding test, `reality_engine/scripts/embed_model_test.py` (51 concall questions), is prior art
  for the harness.

## C1 — chunker v2 (new module `reality_engine/processing/chunker_v2.py`)
**Split rules by document type:**

| Type | Chunk unit |
|---|---|
| Concall transcripts | One speaker turn per chunk; each analyst question is kept with management's full answer as one Q&A chunk; the opening remarks are split by speaker. |
| Investor decks | One slide (page) per chunk. |
| Annual reports and results PDFs | One chunk per note, table or schedule, kept whole. Headings come from PyMuPDF font sizes and bold spans; tables from `page.find_tables()` where it works. |
| PIB / RBI / circulars | One clause or numbered paragraph per chunk (1., 1.1, (a), (i)), keeping the scheme names and the ₹/crore amounts in the chunk. |

**Size limits:**
- A unit over ~6,000 chars is split at the next structural boundary (sub-heading, paragraph, table row group),
  never mid-sentence.
- A unit under ~300 chars is merged with its neighbour inside the same section.

**Header and output:**
- Each chunk gets a header line built from metadata only:
  `<SYMBOL> · <doc type> · <fiscal period> · <section/speaker> · filed <date>`.
  The header is stored separately from the body.
- The output is a new SQLite file under the worktree `.tmp/c1/chunks_v2_pilot.db` (`chunks_v2` + FTS5), with
  columns: chunk_id, doc_id, symbol, isin, doc_type, section, speaker, unit_kind, header, body, char_len,
  published_date, page_from, page_to.
- Do not touch `document_chunks`.

**Text sources:**
- Use the stored text where it exists (`document_chunks` content re-joined per doc in `chunk_index` order, or the
  PDF via `config.resolve_stored_path()`).
- Raw PDFs are on `D:\RealityEngine\pdfs` / `D:\RealityEngine\raw` (read-only).

**Pilot:** 50 documents per type (concall, deck, annual report, PIB/RBI). Report per type:
- docs and chunks, old vs new;
- the chunk length distribution (p10/p50/p90);
- the share of chunks that cut a table or a Q&A pair, against the old chunks, measured by a simple detector you
  describe.

## C2 — quality set + harness
**The 200 pairs:**
- 60 concall, 40 deck, 40 AR/results, 30 PIB/RBI/circular, 30 EVAL25-style cross-document.
- Build each pair from a known passage: pick a passage, write a natural analyst question it answers without
  copying its wording, and record the answer as `(doc_id, character span of the answer)`.
- Gold is the span, not a chunk id, so both old and new chunkings can be scored: a hit is any retrieved chunk that
  overlaps the span.
- Hard negatives: add 20 questions whose answer sits in a table or a Q&A pair that the old chunking splits.
- Write to `tasks/optimizations/learn/quality_set_v1.jsonl`. Fields: qid, question, doc_type, doc_id, span_start,
  span_end, answer_text, as_of, difficulty, why.

**The harness, `reality_engine/scripts/eval_retrieval.py`:**
- Inputs: `--chunks old|v2`, `--retriever fts|seed_dense|local:<model-dir>`.
- Outputs: recall@1/5/10, MRR, and per-type breakdowns as JSON.
- `seed_dense` is the free G4 path (`plugins/reality-data/server/dense_free.py`) and only applies to old chunks,
  which have vectors.
- For v2 chunks, run FTS now. The dense comparison on v2 needs new vectors (paid), so only print the token count and
  the cost formula: tokens × $/M as a parameter. Do not call any paid API.

**Run and report:**
- FTS old vs FTS v2 on all 200;
- seed_dense on old;
- per-type tables, plus the 20 hard negatives separately.

## Rules
- Local data only: no internet, no paid APIs, no live DB writes. Use `connect_ro`.
- All outputs go under `.tmp/c1/` except the two tracked files: the quality set jsonl and the harness.
- Don't let the quality set leak into the chunker. The chunker must not read the questions.

## Acceptance checks
1. `python -m unittest reality_engine.tests.test_chunker_v2` passes. Its fixtures cover:
   - a 3-turn concall with Q&A pairing;
   - a 3-slide deck;
   - an AR note with a table that must stay whole;
   - a circular with numbered clauses;
   - oversize splitting and undersize merging.
2. Pilot stats per type, as above.
3. `quality_set_v1.jsonl` has 200 rows. Spot-check 10 yourself, re-reading the passage: the question must be
   answerable from that span alone.
4. The harness results table: FTS old vs FTS v2, and seed_dense old, overall and per type.
5. Token count of the full corpus re-chunked with v2, per type, using the same tokenizer estimate as
   `state.json` (206M tokens for the current 340,887 chunks). This is the C0 cost input.
6. `git diff --stat`: only the new files listed, plus at most a test registration.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_chunker_v2
```

## Budget
≤ 15 tool calls before the first edit; ≤ 150 total; $0 paid.

## Report
1. Files  2. Pilot stats  3. Quality-set summary + 10 spot checks  4. Harness results
5. Corpus token counts  6. Open problems  7. Tool calls.
