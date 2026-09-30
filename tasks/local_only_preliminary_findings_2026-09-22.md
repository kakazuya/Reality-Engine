# Local-Only Preliminary Findings — 2026-09-22

> Companion to `tasks/optimization_findings_2026-09-20.md` (O1–O8, G1–G3) and
> `tasks/resource_efficiency_handoff_2026-09-21.md` (items A/B/C).
> Scope: run whole Reality Engine locally on this box. No cloud, no PG server.

## 0. Environment observed (this session, live)

- CPU: i5-12400F 12 threads; RAM 17.0 GB total / 7.9 GB avail (53.6% used) — RAM binding, not CPU
- Disk: C: 804 GB total / 491 GB free
- GPU: RX 6700 XT, `onnxruntime 1.24.4 providers=[DmlExecutionProvider,CPUExecutionProvider]`
- Python 3.14.6; `faster-whisper present`, `polars 1.42.1`, `rapidocr present`, `huggingface_hub present`, `playwright present`, `telethon 1.44.0`
- Correctly MISSING (do not install): `torch`, `lancedb`, `sentence_transformers` — fallbacks cover them
- DB: `reality_engine/data/equity_intelligence.db` 12.14 GB WAL (`-wal 0`, `-shm 32k`)
  - `document_chunks 662,509` · `daily_price_delivery 3,121,803` · `master_companies 6,438`
  - `company_distilled_parameters 17,667` · `moat_evaluations 2,653` · `raw_documents 6,242`
- Live via `db_manager.get_connection()`: `mmap 1073741824 / cache -64000 / WAL / sync NORMAL(1) / temp MEMORY(2) / busy 180000 / FK ON` — correct. Raw `sqlite3.connect` shows `mmap 0 / cache -2000` — never open DB direct.
- Vectors: `lancedb/vectors.json 556 MB` + `vectors_meta.json 230 MB` + `vectors.npy 113 MB` (mmap path live in `db/vector_store.py:54`); `vector_index/chunk_vectors.npy 370 MB` + `chunk_ids.npy 1.9 MB` (BLAS index live)
- Models: `models/bonsai-27b-v1/Ternary-Bonsai-2-27B-Q2_g64.gguf 7.59 GB` + 5.8 GB `.incomplete` HF cache junk; `models/gguf/bge-small-en-v1.5-q8_0.gguf 36 MB`; `models/bge-small-en-v1.5/onnx/model.onnx 133 MB`
- Env unset: `REALITY_ENGINE_EMBED_BACKEND / EMBED_SERVER / GPU_DUTY / OCR_GPU / LLM_BASE_URL` all None → embed defaults to `onnx`, vulkan path dormant

Already captured, do NOT redo: `mmap 1GB` via manager, npy+mmap vector path, `chunk_vector_index` BLAS, O1–O8 lazy init (cli 8.11s→1.14s), `backfill.rolling_indicators_polars`, faster-whisper first (`cpu_threads=10`), embed memo 256-entry.

## 1. P0: `llm-serve` path broken — fix before any lens work

`cli.py:_llm_paths()` expects `models/bonsai-27b/Ternary-Bonsai-2-27B-PQ2_0.gguf`; disk has `models/bonsai-27b-v1/Ternary-Bonsai-2-27B-Q2_g64.gguf`. Every `llm-serve` misses. `setup-bonsai2-vulkan.ps1` LMStudio path nonexistent. `data/llama-bonsai/llama-server*.exe` present (impl.dll + log, no prism dir).

- Canonicalize one dir (`bonsai-27b-v1`), add glob fallback like cached-line already does; repoint/delete ps1.
- Delete `models/bonsai-27b-v1/.cache/**/​*.incomplete` (4.84+0.95 GB) — dead weight, confuses HF resume.

## 2. Do not run 27B at 32k ctx by default

`cmd_llm_serve:979` launches `ctx 32768, -ngl 99, --threads -1, reasoning-budget 512` + 7.6 GB GGUF on 12 GB VRAM alongside 370+113 MB mmap indexes + DirectML OCR in 16 GB RAM → swap.
Lens passes (`llm_lens_client.extract_macro/synthesize`, STRICT JSON) need 4–8k; thesis 16k.

- Lens `4096–8192`, thesis `16384`; `--threads 8` not `-1` (FW already takes 10).
- Per `llm_lens_client.py:18` spec: `Qwen2.5-3B Q4_K_M 1.9 GB` for lens distill, 27B thesis-only.

## 3. Embed backend defaults to 2x-slower path

`ingestion/onnx_embedder.py:80-87` measured Vulkan 65.4 chunks/s vs DirectML 31.8, yet backend unset → `onnx`. DML `Run` serializes under `self._lock:250` — more `--workers` never speeds embed.

- Set `REALITY_ENGINE_EMBED_BACKEND=auto`, `EMBED_SERVER=127.0.0.1:8099`, `VULKAN_BATCH 8→32` when server up (auto-fallback to ONNX preserved).
- Keep `batch_size 32`, `gpu_duty 1.0` batch / `0.8` interactive (`_duty_sleep:339`).
- Split pools: fetch `8–10`, embed/ingest `2–4` (`offer_backfill` resolve-2x/ingest-min(8,2x) pattern). CLI `phase1 --workers 8` right for IO; never 12+ (RAM + single-writer lock).

## 4. Search does double dense work per query

`search/hybrid_search.py:search` runs `vector_store.search` (73k concall subset) + `_chunk_index_search` (662k full corpus, BLAS 50–150 ms) + FTS5, RRF-fused (`min_dense_score 0.35`, `max_per_symbol 3`). `_chunk_index_search` calls `onnx_embedder.embed` direct, bypassing `VectorStoreManager` memo → 2 ONNX calls per search.

- Local-only: chunk index primary, VectorStore secondary. One embed, pass vector to both; keep `0.35` gate (kills cosine-noise lists before RRF).
- Leave `lancedb/sentence_transformers/torch` uninstalled; `lancedb/` has JSON only, no table. `PG_DSN` unset → `_pgvector_search` returns None fast; leave PG branch dormant (zero-pad 384→1536 path is dead).

## 5. SQLite: manager-only, stagger writers

Single writer. Never co-run `continuous_loop (30m)` + `nightly 16:00/23:00` + `capacity 6h` + backfill; `STALE_LOCK 45m` exists — stagger, pause loop during Wave A–D distill.
Keep `cache -64000` default; `-262144` via env for backfill phases only (mmap evictable, cache pinned). Drift-guard `ANALYZE` (O6) before big `screen`; never full `VACUUM` on 12 GB.

## 6. Stale-index + transcription threads

`chunk_index_meta.source_chunks_at_build` rots on every ingest — rebuild `build_chunk_vector_index` in nightly/catchup after ingest or DRHP vectors are write-only.
`youtube_transcriber cpu_threads 10→8` (leave 4 for DML/server/loop). `aria2c` present — use for 10 GB pack re-fetch. Keep `BROWSER_RATE_LIMIT 1s`, SEBI `workers 2` (WAF).

## 7. Reclaim

- `lancedb/vectors.json 556 MB` audit-only after npy golden `(symbol,query,top_k)` check (§1.4 handoff) → `zstd` or delete.
- Root `_tmp_sudeep*/_pack_audit*/poll_*/logs_step*.txt/tests_run.log` → `archive/` (agent context noise).
- `data_pack_split/ ~10 GB` keep only if replay needed.

## Verify

1. `llm-serve` ready + `lens-extract --kind moat` returns JSON
2. `EMBED_BACKEND=auto` chunks/s before/after; one `search-concall` latency + RSS with 27B resident
3. `EXPLAIN QUERY PLAN` unchanged after pragma; `build_chunk_vector_index` rows == `embedding<>''` count
