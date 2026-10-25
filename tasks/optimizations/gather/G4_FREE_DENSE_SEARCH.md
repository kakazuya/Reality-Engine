# Task G4 — dense search on the vectors we already have, at no cost

## Goal
`search_docs` uses the stored embedding indexes without any paid query-embedding call, and returns the same results
for the same query every time.

## Why
- The stored indexes are paid for already: Nemotron-8B (340,887 chunks: transcripts, decks, announcements, macro),
  Qwen3-8B AR (1.37M) and the old bge-small (1.7M).
- Only embedding a new query text into the Nemotron/Qwen space costs (DeepInfra, gated by
  `REALITY_DATA_ALLOW_PAID_EMBED`). So today the workers get FTS only.
- Shivam (2026-10-25): search on the existing embeddings now.

## Design
1. **Seed-vector expansion (Nemotron, Qwen):**
   - Run FTS5 first. Take the top 3–5 hits that exist in the index (`chunk_ids.npy`).
   - Average their stored vectors into the query.
   - Run cosine top-k over `chunk_vectors.npy` (memory-mapped).
   - Merge with FTS through reciprocal-rank fusion.
   - Keep the same symbol, doc-type and date filters.
2. **Local query embedding for the bge-small index:** use `reality_engine/ingestion/onnx_embedder.py` (ONNX,
   DirectML GPU if present, else CPU). It is free, and serves as the fallback when FTS finds no seed.
3. A paid Nemotron query embed runs only when `REALITY_DATA_ALLOW_PAID_EMBED=1` is already set (unchanged).
4. Results:
   - Every result says which path produced it: `fts`, `seed_dense`, `local_dense` or `paid_dense`.
   - Query vectors are cached on disk under `.tmp/qcache/`, keyed by (model, query text).
   - Ties are broken by chunk id, so rankings are reproducible.
5. **Point-in-time filter:** add `as_of`. Chunks whose document's known/published time is after it are dropped, and
   the result counts them in `hidden_after_as_of`.

## Files to touch
- `plugins/reality-data/server/search_docs.py` and a new helper module `plugins/reality-data/server/dense_free.py`.
- New tests: `plugins/reality-data/tests/test_dense_free.py`, using small synthetic vector folders.
- Do not touch: `core.py`, `server.py` apart from passing `as_of` through `search_docs`'s existing registration,
  `query_embed.py`, any index or database file.

## Steps
1. Read `search_docs.py` (`_dense_rows` ~line 731), `query_embed.py`, `onnx_embedder.py` and the index folder layout
   (`chunk_index_meta.json`, `state.json`).
2. Implement and test.
3. Live check, read-only, with `REALITY_DATA_ALLOW_PAID_EMBED` unset. Run these 3 queries and print the top 5 for each
   with their paths:
   - "El Nino impact on milk procurement" (symbol PARAGMILK);
   - "coal gasification scheme incentive";
   - "data centre tax holiday".

## Acceptance checks
1. `python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"` passes.
2. The live check shows `seed_dense` or `local_dense` hits that FTS alone missed, and makes no paid call (assert that
   the `query_embed` provider is never called).
3. The same query twice gives identical rankings.
4. Latency: ≤ 3 s per query warm, ≤ 15 s cold; report both.

## Test command(s)
```bash
python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"
```

## Budget
≤ 20 tool calls before the first edit; ≤ 100 total; $0 paid.

## Report format
1. What changed  2. Live results (trimmed) + latencies  3. Open problems  4. Tool calls before first edit / total.
