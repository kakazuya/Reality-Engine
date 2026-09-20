# Environment / Resource-Efficiency Handoff — 2026-09-21

> Written by a library-installation + transcriber-fix session. Companion to
> `tasks/optimization_findings_2026-09-20.md` (read §0.5 and the Guardrails section there
> before executing anything below — its fences G1–G3 and the O2 fence still apply).
>
> **Scope of this handoff:** tooling/library availability, one functional fix shipped and
> verified, and a prioritized list of *not yet executed* resource-efficiency changes with
> measurements an executing agent can reuse without re-benchmarking everything.

---

## 0. What this session already changed (do NOT redo)

| Change | Files | Verified by |
|---|---|---|
| `faster-whisper` wired in as the FIRST transcription backend, before the `openai-whisper` fallback | `reality_engine/ingestion/youtube_transcriber.py` (new `import os`; new rung in `transcribe()` at ~L274; lazy `WhisperModel(device="cpu", compute_type="int8", cpu_threads=os.cpu_count()-2)`, stored as `self._fw_model_obj`) | Real-TTS smoke test: 3 timestamped segments from speech in **2.1 s**. Tone-only wav returned 0 speech segments and fell through to the unchanged final mock — expected. |
| Installed `faster-whisper` 1.2.1 (+ctranslate2 4.8.2, av) | global Python 3.14.6 | `pip install` clean; `WhisperModel("tiny.en")` loads in ~8 s cold incl. HF download |
| Installed `numexpr` 2.14.2, `bottleneck` 1.6.0 | global Python | pandas 3.0.3 auto-detects bottleneck (`pd.core.nanops._USE_BOTTLENECK == True`); 200k-row groupby ×5 = 0.084 s |
| Registered both in manifests | `requirements.txt` (numexpr/bottleneck under core), `requirements-optional.txt` (faster-whisper section, commented rationale) | — |
| Regression check | — | `reality_engine.tests.test_perf_guards` + `test_agent_and_reporting`: 13/13 OK |
| CLI import regression | none | warm `import reality_engine.cli` = **1.34 s** — O3's fix still holds. A one-off 8.5 s cold figure is bytecode recompilation after the edit, not a regression. |

**Environment observed this session:** Python 3.14.6 / pip 26.2.1 (all candidate wheels exist for cp314 — dry-run verified); SQLite module 3.50.4 with FTS5 + RTree, WAL; DB 2.43 GB (`document_chunks` 71,375 · `daily_price_delivery` 3,121,803 · `master_companies` 6,438); i5-12400F 12 threads; RX 6700 XT 12 GB (DirectML + Vulkan both live); **16 GB RAM, 67.8% in use** — RAM is the binding constraint, not CPU.

---

## 1. Pending item A (highest value): vectors.json → npy + sidecar (O8 option a)

`reality_engine/data/lancedb/vectors.json` is **585.2 MB**, 73,615 rows × 384-dim. Every
first search in a process:

- `json.loads()` of 585 MB = **5.9 s** (measured 2026-09-20, O8 §, unchanged — code at
  `reality_engine/db/vector_store.py:54-63` still `_load()`s the whole file into `self._rows`);
- inflates to **≈2–3 GB RSS** as Python dict/float-list objects, on a machine with 16 GB where
  a 7.6 GB llama.cpp model also wants to live;
- scores candidates with a **pure-Python dot product** (`sum(a*b for a, b in zip(...))`,
  `vector_store.py:140`) over 384 dims per candidate.

**Spec (already given in O8; restated for execution):**

1. One-time migration script (idempotent, e.g. `reality_engine/scripts/migrate_vector_store.py`):
   parse `vectors.json` once, write `reality_engine/data/lancedb/vectors.npy` (73,615×384 f32,
   113 MB) + a metadata sidecar (`vectors_meta.json`, without the vector payloads, ~360 MB
   textual reduced to no more than a bare `json` of id/symbol/text fields). Keep `vectors.json`
   on disk as audit source; only stop reading it.
2. `VectorStoreManager._load()`: `np.load(..., mmap_mode="r")` for vectors + `json` sidecar for
   rows. `search()`: numpy-ize the dot product (`metas @ q` on the symbol-filtered index) —
   pure-Python zip scoring must not survive the migration.
3. **Interlock with O4's embed cache and the O3 lazy properties** — `_rows` is still required
   (fence in O8: do NOT delete `_rows`/the symbol filter); the fence "LanceDB is the ANN tier
   and the JSON is the dependency-free fallback" is satisfied by the npy format, not by
   deleting the tier.
4. **Acceptance (from O8):** `_load()` ≤ ~0.5 s on this corpus; search results unchanged for a
   golden sample of `(symbol, query, top_k)` triples captured BEFORE the migration (see
   O8 risk note: run `add_chunks` path + `test_onnx_embedder` / `test_intel_search` after).
5. Expected side effects to record honestly: ~2–3 GB RSS freed when a search process runs
   alongside the local LLM; first-search latency 5.9 s → sub-second. Do NOT claim these are a
   wall-clock win for cold processes only — the RSS reduction is the headline.

**Why this is the top item on a 16 GB machine:** it is the only change that lets
`bonsai-27b-v1` (7.6 GB GGUF) and a search-heavy session coexist without swapping.

---

## 2. Pending item B: SQLite `mmap_size` pragma (one line)

`reality_engine/config.py` `SQLITE_PRAGMAS` (L302) currently sets WAL / synchronous NORMAL /
cache_size −64000 / temp_store MEMORY / FK / busy_timeout — **no `mmap_size` (0 default)** on a
2.43 GB read-heavy DB.

**Change:** append `"PRAGMA mmap_size = 1073741824;"` (1 GB). mmap pages are file-backed and
OS-evictable, so this does NOT pin RAM the way a bigger `cache_size` would; safer than raising
the page cache on a 16 GB box.

**Verify:** `EXPLAIN QUERY PLAN` unchanged (planner-neutral); time the Appendix A.4 probe
queries before/after; confirm `pragma mmap_size` reports 1073741824 on a fresh connection.
**Risk:** file-config only, lane-neutral (config.py is NOT in LANES.md's assignment list,
but it WAS dirty on 2026-09-20 — coordinate with `lane-code-cli`/`lane-code-repo` holders
if you touch anything beyond this one line). Optional follow-up when RAM is free: raise
`cache_size` −64000 → −262144 (256 MB) ONLY for ingest-heavy phases, not as a default.

---

## 3. Pending item C: adopt polars (already installed, zero callers)

`polars` 1.42.1 + `pyarrow` 24 are installed. Measured THIS session on the live 3.12M-row
`daily_price_delivery`:

| Operation | pandas 3.0.3 | polars |
|---|---|---|
| build DF from rows + groupby mean/std/count | 0.26 s | 0.08 s |
| per-symbol rolling SMA(20) over 3.12M rows | 2.76 s (`transform`) | 1.31 s (`rolling_mean(20).over('symbol')`) |

**Targets (batch/high-volume paths only, NOT the per-scrip live request path):**
`technical_engine.py` (rolling SMA/RSI recomputes), any screener/QoQ batch that fans over the
whole price history. Keep the DataFrame-exchange shape at module boundaries or convert at the
edge — do not let polars types leak into `repository.py` row persistence.

**Order:** do A first; C's wins partially overlap the RAM relief A provides and C touches more
surface, so A is the lower-risk start.

---

## 4. Dead ANN tier: lancedb not installed

`lancedb` IS absent from the env. That alone is NOT a reason to install it:

- `VectorStoreManager._table_handle()` (`vector_store.py:40-50`) creates the lance table
  lazily on first WRITE only; read paths use in-memory rows (`vector_store.py:139-142`).
- The `lancedb/` directory contains ONLY `vectors.json` — no populated lance table — so
  installing lancedb today changes nothing for read performance.

After A (npy migration), installing `lancedb` becomes a viable follow-up (version
`0.38.0` dry-run-verified installable with `lance-namespace-*` deps). Not part of A; do not
couple them.

---

## 5. Confirmed-sound toolchain — no action

- `rapidocr` 3.9.2 + `onnxruntime-directml` 1.24.4: DirectML provider is live on the RX 6700 XT
  (providers list: `['DmlExecutionProvider', 'CPUExecutionProvider']`). Leave alone.
- ffmpeg 2026-02-02 build present; yt-dlp 2026.8.19 present.
- aria2c 1.37.0 present — use it (multi-connection) for re-fetching the 10.1 GB
  `data_pack_2026-08-31` / `data_pack_split` zips if they are ever re-transferred.
- SQLite CLI binary absent (only the Python `sqlite3` module). Minor; Python module is
  sufficient for all repo scripts.
- Python 3.14 is fine there is no wheel gap left: everything this repo needs installed or
  dry-ran cleanly on cp314.

---

## 6. Staleness checks before executing

All state re-confirmed 2026-09-21, but another agent may touch the tree:

```bash
# Is the vector store still JSON-parse-everything?  (A pre-check)
grep -n "vectors.json" reality_engine/db/vector_store.py
python -c "import pathlib; p=pathlib.Path('reality_engine/data/lancedb/vectors.json'); print(p.exists(), f'{p.stat().st_size/1e6:.1f} MB')"

# Is mmap still unset? (B pre-check)
python -c "from reality_engine.config import SQLITE_PRAGMAS; print(SQLITE_PRAGMAS)"

# Polars still installed, still zero callers? (C pre-check)
pip show polars | head -2 && python reality_engine/cli.py --help > /dev/null && echo "cli ok"
grep -rn "import polars" reality_engine/ || echo "polars: no callers"

# Transcriber faster-whisper tier still first in line? (shipped this session)
grep -n "faster_whisper" reality_engine/ingestion/youtube_transcriber.py
```

## 7. Open decisions carried over (unchanged by this session)

D1 substrate-dossier wiring into the loop brief / agent tools (context budget: serve config
`-c 4096`) · D2 re-distill the 8 degenerate parameter families · D3 supply-chain edge
extraction sizing ($5.22–$86.98 batch) — full sizing in
`tasks/optimization_findings_2026-09-20.md` §"Open decisions".
