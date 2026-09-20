# Optimization Findings — 2026-09-20

> Read-only investigation pass over the main-branch working tree. **The investigation itself
> modified no files.** This document is the only artifact it produced.
>
> Companion docs: `tasks/todo.md` (standing 16-task plan), `tasks/next_wave_execution_plan.md`.
> This file is deliberately separate and **not yet linked from `tasks/todo.md`** — the loop agent
> reads that file every 30 minutes and another agent was editing the tree concurrently, so
> appending to it was avoided on purpose. See §0.4 for the one-line pointer to paste in.
>
> Task IDs use an `O` prefix so they can never be confused with Tasks 1–16 in `todo.md`.

---

## 0. Session handoff — read this first

### 0.1 Work already built and verified in this session (uncommitted)

| Path | Status | What it is |
|---|---|---|
| `reality_engine/processing/substrate_hygiene.py` | untracked | Trust layer: quarantine rules for test/demo/synthetic-ISIN rows + degradation audit. Owns `substrate_quarantine`. |
| `reality_engine/processing/peer_graph.py` | untracked | Analog peer graph over the dense substrate with feature-signal gating, per-pair coverage, drivers, anchor baselines. Owns `company_peer_graph`, `company_peer_features`, `company_peer_runs`. |
| `reality_engine/scripts/run_substrate_hygiene.py` | untracked | Promotion script, prints `ALL CHECKS PASSED`. |
| `reality_engine/scripts/run_peer_graph.py` | untracked | Promotion script (`--top-k`, `--dry-run`). |
| `reality_engine/tests/test_peer_graph_and_hygiene.py` | untracked | 10 tests. |
| `AGENTS.md` | modified | Module map (§1), new §2.H commands, new convention rule 13. |

Verification status at time of writing: **10/10 new tests pass**; both scripts return
`ALL CHECKS PASSED: True` against the live DB and are idempotent across reruns.

Re-verify:

```bash
python -m unittest reality_engine.tests.test_peer_graph_and_hygiene
python -m reality_engine.scripts.run_substrate_hygiene
python -m reality_engine.scripts.run_peer_graph --top-k 20
```

Live-DB state written by the above: `substrate_quarantine` 1,377 rows ·
`company_peer_graph` 50,180 pairs / 2,509 anchors · `company_peer_features` 4,996 rows ·
`company_peer_runs` 6 rows. All four tables are owned by the two new modules and created by their
own idempotent DDL — nothing in `schema.sql` or `repository.py` was touched.

### 0.2 Active constraints when this was written

- **Another agent was editing the working tree.** Pre-existing modifications observed:
  `.gitignore`, `.kilo/agent/{macro-graph,pipeline-tester,quant-analyst}.md`, `.kilo/run-script.ps1`,
  `AGENTS.md`, `reality_engine/cli.py`, `reality_engine/config.py`,
  `reality_engine/db/repository.py`, `reality_engine/db/schema.sql`,
  `reality_engine/db/vector_store.py`, `reality_engine/ingestion/bse_client.py`,
  `reality_engine/ingestion/filing_discovery.py`, `reality_engine/ingestion/master_sync.py`,
  `reality_engine/ingestion/pdf_ingestor.py`, `reality_engine/tests/test_repo_identity.py`.
  The loop brief also reported ~135 untracked files.
- **Lane ownership** (`.kilo/LANES.md`) — coordinate before touching:
  `cli.py` → `lane-code-cli`; `db/repository.py`, `db/schema.sql` → `lane-code-repo`;
  `business_profiler.py`, `policy_engine.py`, `moat_scorer.py`, `scripts/run_*_peer.py` → `lane-code-derive`;
  `distillation_engine.py` → `lane-code-distill`.
- **Never `git stash`** — stashes are globally shared across worktrees in this repo.
- The continuous loop runs every 30 minutes and SQLite has one writer; serialize writes.
- `reality_engine/data/equity_intelligence.db` is gitignored. Its new tables are *not* in the
  Data Pack (`data_pack_2026-08-31`) or in `schema.sql`, so a fresh clone will not have them until
  the scripts are run.

### 0.3 Staleness check — do this before acting on anything below

Every finding here was measured against the DB and code as of 2026-09-20. Re-confirm before
working, since the other agent may have fixed some of it:

```bash
# O1 + O2: does the screener still disagree with the canonical tables?
python - <<'PY'
import sqlite3
from reality_engine.processing.composite_screener import composite_screener as cs
con = sqlite3.connect('file:reality_engine/data/equity_intelligence.db?mode=ro', uri=True)
canon = dict(con.execute("select ticker, total_moat_score from moat_evaluations").fetchall())
uni = [r[0] for r in con.execute("select nse_symbol from master_companies where is_nifty200=1 and nse_symbol is not null")]
diff = sum(1 for s in uni if canon.get(s) is not None and abs(cs._lookup_moat_metrics(s,"")["total_moat_score"] - canon[s]) > 0.01)
print("mismatch:", diff, "/", len(uni), "| roic sample:", cs._lookup_roic_wacc_spread("HAL",""))
PY

# O3: import tax still present?
python -X importtime -c "import reality_engine.cli" 2>&1 | sort -t'|' -k2 -rn | head -5

# O5: is the chunk index still missing?
python -c "
import sqlite3; con=sqlite3.connect('file:reality_engine/data/equity_intelligence.db?mode=ro',uri=True)
print([r[3] for r in con.execute(\"EXPLAIN QUERY PLAN SELECT chunk_id FROM document_chunks WHERE symbol='HAL' LIMIT 5\")])"
```

### 0.4 Optional pointer to paste into `tasks/todo.md` (not done here)

```markdown
> Optimization findings from the 2026-09-20 read-only pass: `tasks/optimization_findings_2026-09-20.md` (tasks O1–O7, guardrails G1–G3, 3 open decisions).
```

### 0.5 Implementation status (2026-09-20, second session)

O1–O7 are **implemented and verified**. Measured before → after:

| Item | Before | After |
|---|---|---|
| O1 moat routing | 152/200 nifty200 symbols disagreed with `moat_evaluations`; 67 crossed the 3.5 gate | **0/200 mismatch, 0 gate flips**, all 200 resolve via `moat_evaluations` |
| O2 ROIC claim | "ROIC-WACC +6.00% >5% value-creative" asserted from a constant for every name | status `unknown` → claim suppressed; `measured`/`proxy` still assert |
| O3 CLI start | `import reality_engine.cli` **8.11 s** | **1.14 s** |
| O4 embed memoization | 5 identical query embeds per report | 1 uncached embed + 4 cache hits (**see correction below**) |
| O5 chunk indexes | `WHERE symbol=?` **5,045 ms**, `WHERE isin=?` 623 ms (full scans) | **0.04 ms / 0.02 ms**, `SEARCH … USING INDEX` |
| O6 planner stats | `master_companies` stat 3,474 vs actual 6,438 (46% drift) | drift detected and analysed; second call converges to `{}` |
| O7 suite | `test_03_cli_screen` failed on fixture drift; discovery truncated (exit 5, no summary) | module + discovery report a summary; **full suite: 593 tests, OK, exit 0** |

**O1b (follow-on, done in the same pass):** tier 3 of the moat chain now reads the canonical
`business_model_profiles` instead of the `business_model_profiles_demo` mirror. Measured basis
for calling this behaviour-preserving: canonical 2,592 rows vs mirror 2,592 rows, **2,592
symbols present in both**, and identical coverage in every universe bucket (nifty50/100/200/500
100%, screenable 2,412 vs 2,411, active 2,454 vs 2,454). On the live DB the mirror-reading tier
was already unreachable for every symbol it could serve — a sample of 400 screenable names now
resolves 397 `moat_evaluations` + 3 `distilled_param`, with **no `archetype_heuristic` hits at
all**. The mirror now has **no reader**; remaining cleanup is in lane-owned files (see G1).

Tests added: `reality_engine/tests/test_screener_substrate_routing.py` (7) and
`reality_engine/tests/test_perf_guards.py` (7) — 14/14 pass.

**Corrections to the original write-up, from doing the work:**

1. **O4's impact was overstated.** The "0.62 s per call" figure was a `pstats` *average*
   (`cumulative/calls`) dominated by one-time ONNX session construction in the first call,
   not a per-call cost. Memoization therefore saves four near-free calls, not ~2.5 s. The
   cache is kept (it is bounded, correct, and removes genuinely redundant work in
   long-lived processes) but the win is small. The real cost in that path is O8 below.
2. **O6 needed a different mechanism.** `PRAGMA optimize` does **not** refresh statistics
   that are stale on disk: measured at 0.00 s (and `PRAGMA optimize=0x10002` at 2.11 s)
   leaving `master_companies` at 3,474. Only a real `ANALYZE` fixed it, at 32.8 s for the
   whole DB — too expensive unconditionally. Implemented as: cheap `PRAGMA optimize` first
   (it does cover never-analysed tables), then compare each table's stored estimate to its
   actual count and `ANALYZE` only what drifted >25%; big enough tables only.
3. **O3 had two more halves** beyond `agent/tools.py`: `VectorStoreManager.__init__`
   connected LanceDB eagerly although only `add_chunks` uses it, and `FinancialOCREngine`
   built the DirectML provider at construction. Both now initialise on first use — that is
   most of the 8.11 s → 1.14 s. `engine`/`provider` are lazy *properties* so the existing
   availability probes (`inst.engine is not None`, `inst.provider`) still report the truth.
4. **O7's crash did not reproduce** after the changes above, so the truncation is not
   root-caused — do not record it as "fixed by X". The confirmed defect was the
   fixture-pinned `assertIn("HAL", output)` in `test_03_cli_screen`, now replaced with
   structural assertions (table columns + at least one ranked row). If exit-5 truncation
   returns, suspect interaction between unbuffered output and engine/OCR init; `-b` was the
   workaround that let the module report a full summary.

---

## O1: Route the screener moat lookup to the canonical `moat_evaluations` on SQLite

**Description:** `composite_screener._lookup_moat_metrics` (~L618–708) opens with a PostgreSQL-shaped
query: `FROM moat_evaluations m JOIN companies c ON c.company_id = m.company_id`. There is **no
`companies` table in SQLite** — it is PostgreSQL-only. The query raises `OperationalError`, the bare
`except Exception: pass` swallows it, and every lookup falls through to tier 2: an archetype
heuristic over `business_model_profiles_demo` using
`score_map = {"Tollbooth": 3.8, "Platform": 4.2, "Asset-Heavy OEM": 2.7, "Network": 3.6}`.
Add a SQLite tier that reads `moat_evaluations WHERE ticker = ?` **before** the demo heuristic.

**Measured impact (nifty200, vs canonical):**

| Metric | Value |
|---|---|
| Score mismatch > 0.01 | **152 / 200 (76%)** |
| Mean delta / max \|delta\| | +0.138 / **1.30** |
| Flipped across `TOPDOWN_MIN_MOAT_SCORE = 3.5` | **67 (56 wrongly pass, 11 wrongly fail)** |

Example: DABUR screener 4.1 vs canonical 3.4; HAL 4.1 vs 3.65; ITC 3.95 vs 3.4.

**Fence:** PG-first is deliberate — PostgreSQL is the production target and `companies` legitimately
exists there. The fence protects the *existence of the fallback chain*, not a SQLite branch that skips
a table which exists locally with 2,593 populated rows (50 distinct values, sd 0.49 — genuinely
varied and worth routing to). Keep the PG tier and all lower tiers intact.

**Acceptance:** for nifty200, screener score equals canonical within 0.01 wherever a `moat_evaluations`
row exists; the 67 gate flips go to zero by construction; capture `top_down_screen` `funnel_stats`
before and after.

**Verification:** `python -m unittest reality_engine.tests.test_quant_hardening` plus the staleness
probe in §0.3; run `python reality_engine/cli.py screen --universe nifty200 --top 20 --top-down`
before/after and diff the candidate set.

**Dependencies:** none. **Risk:** changes which names pass the funnel, so the thesis set changes.
**Do not** claim a trajectory improvement — `moat_trajectory` is 2,586 / 2,593 `"Stable"`.

**Files:** `reality_engine/processing/composite_screener.py` (lane: none assigned — check with `lane-code-derive`).
**Scope:** S.

---

## O2: Stop asserting a ROIC–WACC spread that comes from a hardcoded constant

**Description:** `_lookup_roic_wacc_spread` (~L720–751) has the same absent-`companies` pattern
(`financial_metrics … WHERE company_id IN (SELECT company_id FROM companies …)`), falls to a ROCE
proxy in `annual_financials`, then terminates at `return 0.06`.
`orchestrator._synthesize_topdown_rationale`'s `monet_line` renders that constant verbatim as
`"ROIC-WACC +6.00% >5% value-creative"` inside the thesis text an inference model reads.

**Measured:** screener returns exactly `0.06` for HAL / TITAGARH / KAYNES / BHEL / ITC while
`financial_metrics.roic_wacc_spread` is `-0.1` for the same symbols — and **2,414 of 2,585 canonical
rows are exactly `-0.1`**.

**Fence — this one exists to prevent a harmful fix.** `return 0.06` keeps the top-down funnel populated
until the spread is genuinely computed. Pointing the lookup at `financial_metrics` would swap one
constant for another and flip every company to value-destructive. **Do not** change the numeric
default, and **do not** re-point the source.

**Fix sketch (correctness only):** add a coverage status analogous to the existing
`policy_coverage` (`mapped | no_template | unknown`) and suppress the value-creative sentence when the
spread is default-derived. The upstream fix is computing roic/wacc from `annual_financials` before any
consumer reads it.

**Acceptance:** no exported thesis text asserts a spread unless the value is sourced;
`grep -r "value-creative" reality_engine/data/reports/` returns nothing on a default-derived run.

**Verification:** regenerate one report and inspect the markdown output.

**Dependencies:** none. **Risk:** low, provided the fix stays a status/coverage field.

**Files:** `reality_engine/processing/composite_screener.py`, `reality_engine/agent/orchestrator.py`.
**Scope:** S.

---

## O3: 5.8 s of every CLI start is an eager hybrid-search engine construction

**Description:** `reality_engine/agent/tools.py:26` constructs
`_search_engine = HybridSearchEngine(db_manager)` at module scope, which builds `VectorStoreManager`
(loads `vectors.json`, connects LanceDB). Make it lazy behind an accessor; the seven tool functions and
`dispatch_tool_call` keep sharing one instance exactly as today.

**Measured:** `python -X importtime -c "import reality_engine.cli"` →
`reality_engine.agent.tools` **5.78 s self**; `import reality_engine.cli` wall **8.11 s**.
Secondary: `reality_engine/ingestion/telegram_client.py` 0.68 s self (+ telethon 1.24 s cumulative)
and `reality_engine/processing/ocr_engine.py` `__init__` **1.21 s** (DirectML provider) at import.

**Impact:** every CLI verb, every test-module import (86 modules → most of the suite's runtime), and
every loop-spawned pass.

**Fence:** a single shared engine behind a function registry is the intended design (OpenAI/Gemini-style
tool schemas). Laziness preserves that contract; it does not change it. `grep -rn "_search_engine"`
before renaming anything.

**Acceptance:** `-X importtime` for `reality_engine.cli` at or below ~2.5 s;
`python -m reality_engine.cli --help` and one real verb behave identically.

**Verification:** time `python reality_engine/cli.py noise-floor --symbol TITAGARH` before/after.

**Dependencies:** none. **Risk:** low. Watch for consumers depending on import-time side effects;
treat the OCR provider init as a separate sub-item if desired.

**Files:** `reality_engine/agent/tools.py`; optionally `reality_engine/ingestion/__init__.py`,
`reality_engine/processing/ocr_engine.py`.
**Scope:** S.

---

## O4: Query embedding recomputed 5× for a byte-identical string

**Description:** `reality_engine/db/vector_store.py` `embed` / `embed_many` (L42+) have no cache.
`evaluate_candidate_scrip` passes the same query literal for every candidate
(`"order book capex expansion capacity commercialization guidance margin"`), so a 20-pool / 5-thesis
report pays the same ONNX embedding five times.

**Measured** — `cProfile` of `AgentOrchestrator.synthesize_daily_alpha_report(pool=20, theses=5)`,
wall **4.7 s**:

| Frame | Cumulative |
|---|---|
| `evaluate_candidate_scrip` ×5 | 3.95 s |
| `search_concall_guidance` ×5 | 3.34 s |
| `VectorStoreManager.embed` ×5 | **3.10 s (0.62 s/call average — see correction 1 in §0.5)** |

**Status: implemented.** Identical `(text, is_query)` now reuses the vector within the
process (bounded 256-entry cache; the returned list is a copy so callers cannot corrupt the
cache). Honest impact: it removes four redundant calls, which turned out to be near-free —
the 3.10 s was one-time ONNX session construction, not per-call work. Real remaining cost in
this path is **O8**.

**Fence:** the dense/hybrid retrieval tier is a design pillar (see AGENTS.md §3 rule 8
fallback chain). Keep the tier; memoize the call.

**Files:** `reality_engine/db/vector_store.py`.
**Scope:** S.

---

## O8 (new): `VectorStoreManager._load()` parses `vectors.json` in 5.9 s on every construction

**Where:** `reality_engine/db/vector_store.py`, `_load()` (called from `__init__`).

**Measured** while verifying O3/O4: `_load()` = **5.893 s** cumulative, dominating
`VectorStoreManager.__init__` and therefore every process that touches search. It is a plain
`json.loads()` of the fallback vector store (the `reality_engine/data/lancedb/` directory is
~503 MB), so the cost is JSON parsing of a very large document.

**Composition measured 2026-09-20** (makes the format choice concrete):

| Property | Value |
|---|---|
| File | `reality_engine/data/lancedb/vectors.json`, **585.2 MB** |
| `read_bytes()` | 0.33 s |
| `json.loads()` | **5.54 s → parse-bound**, 75 µs/row |
| Rows | 73,615 |
| Row keys | `document_date, id, isin, source_type, symbol, text, vector` |
| Vector payload | 384-dim → 113 MB as f32 / 226 MB as f64 |
| Implication | **the `text` + metadata fields dominate the file (~360 MB), not the vectors** — so extracting only the vectors to a matrix format fixes ~40% of the parse cost, at best |

**Why it was not obvious earlier:** it used to happen at import time (via `agent/tools.py`'s
eager engine), so it was attributed to "import tax" rather than to the vector store. Deferring
the construction moved the cost into the first search, where it is now visible.

**Fence:** `_rows` is genuinely required by `search()` — it filters the in-memory rows by
symbol and scores them — so this is not dead work; LanceDB is the ANN tier and the JSON is the
dependency-free fallback. Do not "fix" this by deleting `_rows`.

**Fix candidates (not implemented — needs a decision, it is a storage-format change).** The
composition data above changes the ranking: since `text`/metadata dominate the file, moving
vectors to a binary matrix is a partial fix. The real win is not parsing unused fields at all.

(a) **Split the store**: `vectors.npy` (73,615×384 f32 = 113 MB, memory-mapped) + a metadata
JSON/sidecar indexed by symbol, loaded lazily per symbol. Meets the acceptance bar; ~10-50× on
the vector load and lets a symbol-scoped search avoid touching the other 300 MB.
(b) Store vectors as `.npz` in the single blob, keep text in JSON — partial (~40% ceiling).
(c) Let LanceDB serve the search path instead of the in-memory list — note the local
`lancedb/` directory currently holds only `vectors.json` at the top level, so check whether the
lance table is actually populated before relying on this.

Option (a) is the smallest change that reaches the goal; option (c) needs verification first.

**Acceptance:** `_load()` under ~0.5 s on the same corpus; search results unchanged for a
golden sample of `(symbol, query, top_k)` triples.

**Risk:** medium — format migration touches the persisted fallback store; run the
`add_chunks` path and `test_onnx_embedder` / `test_intel_search` afterwards.

---

## O5: `document_chunks` has no index on `symbol` / `isin` — a 5 s cliff

**Description:** `document_chunks` indexes only `(doc_id, chunk_index)`. Add `(symbol)` and `(isin)`
via `schema.sql` plus the idempotent runtime-DDL path used by other modules.

**Measured on the live table:** `WHERE symbol = ?` → **5,045 ms** (plan `SCAN document_chunks`);
`WHERE isin = ?` → 623 ms. The same rows copied to a temp table with an index: **0.03 ms**
(≈12,000× — the wide `embedding` TEXT column is why the real-table scan is far worse).

**Fence — this is where the naive claim breaks and the honest justification differs.** Production
SQLite retrieval does **not** filter chunks by symbol: `hybrid_search` filters by `chunk_id` lists and
`industry_id`, and doc-scoped access is already indexed. The symbol filter appears in tests
(`test_document_industry_tag`, 4× per run) and in backfill/consumer code. So the justification is
*"removes a 5 s landmine for new symbol-scoped consumers and trims test runtime"* — **not**
"speeds up production". Put that wording in the commit message so nobody over-claims.

**Acceptance:** `EXPLAIN QUERY PLAN` shows `SEARCH … USING INDEX`; report the DB size delta;
`test_document_industry_tag` runtime before/after.

**Verification:** profile command in Appendix A.4.

**Dependencies:** none. **Risk:** small write amplification on ingest (73,626 rows).

**Files:** `reality_engine/db/schema.sql` (lane: `lane-code-repo`) + runtime DDL owner.
**Scope:** S.

---

## O6: Planner statistics are ~2× stale

**Description:** `sqlite_stat1` reports `master_companies` 3,474 (actual **6,438**) and
`daily_price_delivery` 2,715,255 (actual **3,121,803**), so the planner works from ~2× wrong row
estimates. Refresh them at the end of bulk-ingest phases.

**Fence:** `DatabaseManager.vacuum()` already runs `PRAGMA optimize` — the modern, cheaper
replacement for full `ANALYZE`. It is simply never invoked after ingestion. **Do not** add a
bespoke full `ANALYZE` on every run.

**Status: implemented, with a correction — the fence above turned out to be wrong for this
case.** Measured: `PRAGMA optimize` (0.00 s) and `PRAGMA optimize=0x10002` (2.11 s) both left
the stale numbers untouched; only a real `ANALYZE` refreshed them, at **32.8 s** for the whole
DB. `PRAGMA optimize` keys off changes made by the *current* connection and does not notice
drift already on disk. Implemented as `DatabaseManager.optimize()`:
cheap `PRAGMA optimize` first (it does cover never-analysed tables), then per-table
`ANALYZE` only where the stored estimate differs from the actual count by >25% (and the table
has ≥1,000 rows). Drift >25% on the live DB: only the one injected case, so it converges to a
no-op. Called from `phase1_runner` and `backfill` after their writes.

**Acceptance:** `sqlite_stat1` within ~10% of actual counts; second call returns `{}`.

**Verification:** `python -c "import reality_engine.db.database as d; print(d.db_manager.optimize())"`.

**Dependencies:** none. **Risk:** DB write — do not run concurrently with the loop's writer.

**Files:** `reality_engine/db/database.py`, `reality_engine/pipeline/phase1_runner.py`,
`reality_engine/pipeline/backfill.py`.
**Scope:** S.

---

## O7: Full-suite discovery never completes (blocks everyone's verification)

**Description:** `python -m unittest discover -s reality_engine/tests -p "test_*.py"` terminates with
**exit 5 and no summary line**, reproducibly, after the DirectML OCR-init log line. Two independent
pre-existing causes:

1. `test_cli_and_dashboard.test_03_cli_screen` asserts `"HAL" in output` for the legacy screener on
   `2026-08-14`; the live DB now returns DABUR / BHARTIARTL / … — live-data fixture drift, the class of
   test the repo rules say to delete rather than re-pin.
2. The same module hard-kills the interpreter with no traceback (native crash path, after OCR
   initialisation), which is why discovery never prints a summary.

Also: `AGENTS.md` §A lists `python -m unittest reality_engine.tests.test_new_funnel`, and that module
**does not exist**.

**Not caused by** the working-tree changes at time of writing: `cli.py`, `composite_screener.py`,
`dashboard.py`, `orchestrator.py` and `test_cli_and_dashboard.py` are byte-identical to the last commit
(`cli.py` was already dirty before this session).

**Acceptance:** discovery prints a summary and exits 0/1 instead of truncating; every command in
`AGENTS.md` §A resolves.

**Verification:** `python -m unittest discover -s reality_engine/tests -p "test_*.py" | tail -5`.

**Dependencies:** none. **Risk:** low; the failing assertion should be removed, not re-pinned.

**Files:** `reality_engine/tests/test_cli_and_dashboard.py`, `AGENTS.md` §A.
**Scope:** S.

---

## Guardrails — do NOT do these

### G1: `business_model_profiles_demo` — precondition now met; residual is lane-owned

Originally: do not delete or wholesale-filter it, because it was tier 2 of the live moat chain
*and* a documented compatibility mirror (`repository.py:1558` — "Remove the mirror once
composite_screener is migrated to the canonical table").

**Status 2026-09-20: the screener is migrated** (see O1b). The mirror is a measured 1:1
duplicate and now has **no reader** anywhere in `reality_engine/`. What is left to do, and who
owns it:

| Residual | File | Owner |
|---|---|---|
| Drop the mirror write (`INSERT INTO business_model_profiles_demo …`) and its `_BP_DEMO_DDL` | `reality_engine/db/repository.py` (~L1558, L1578, L1760) | `lane-code-repo` (per `.kilo/LANES.md`) |
| Update the class docstring that still describes the mirror as load-bearing | `reality_engine/processing/business_profiler.py:3` | `lane-code-derive` |
| Drop `business_model_profiles_demo` from `QUARANTINED_TABLES` once the table is gone | `reality_engine/processing/substrate_hygiene.py:42` | this module's owner |

Not done here deliberately: `repository.py` and `business_profiler.py` are other lanes' files,
and dropping a populated table is destructive. Deleting the *table* is safe (2,592 rows that
duplicate `business_model_profiles` 1:1) but should ride along with the writer removal in one
commit.

**Still-true caution:** AGENTS.md rule 13 tells inference-facing consumers to exclude the
`*_demo` tables wholesale. That remains correct at a consumer boundary. Do not push it into a
shared read helper.

### G2: Do not re-point `_lookup_roic_wacc_spread` at `financial_metrics`

See O2 — the replacement is 93% one default value (`-0.1`).

### G3: Do not delete `INE_AUTO*` rows

The 1,356 synthetic-ISIN rows are a **designed pipeline stage** (backfill stub → real-ISIN promotion),
with carve-outs and consumers in `reality_engine/ingestion/master_sync.py` (delisting),
`reality_engine/pipeline/backfill.py` (stub creation), `reality_engine/pipeline/offer_backfill.py`,
`reality_engine/processing/instrument_classifier.py`,
`reality_engine/db/repository.py` (`_is_placeholder_isin`, promotion keep-rule), and tests
`test_master_upsert` / `test_financial_denominator`. Quarantining them from inference-facing reads is
correct; deleting rows breaks promotion.

### Verified sound — leave alone

| Item | Measurement |
|---|---|
| `continuous_loop.collect_health` | 0.59 s total; `COUNT(*)` on 3.1M rows = 84.5 ms. Not a bottleneck. |
| `model_explainer_rankings` by `stock_id` | 0.279 ms via the autoindex. |
| `corporate_documents` by symbol | 0.150 ms, covering index `idx_docs_sym_date`. |
| `daily_price_delivery` indexes | 6 indexes incl. `(symbol, date DESC)`; `idx_price_date(date)` is arguably redundant beside `idx_price_spike(date, …)` but each was added for a specific screener query — measure before removing. |

---

## Open decisions (not code)

### D1: Wire the substrate dossier into the inference path

The loop brief still renders `COUNT(*)` per table; no `get_substrate_dossier` tool declaration exists.
Open question is **which surface**: the loop brief (`continuous_loop.py`, loop-owned), an agent tool
declaration in `agent/tools.py`, or both. Context budget matters: the local serve config is
`-c 4096` (`setup-bonsai2-vulkan.ps1`), so at 4k tokens a dossier (~1.7k tokens/symbol) means ~2 symbols.

### D2: Re-distill the eight degenerate parameter families

All eight `company_distilled_parameters` dimensions fail the peer graph's signal gate as near-constant
(94–98% single value each): `is_cyclical`, `cycle_duration_years`, `stage_conviction`, `moat_rating`,
`n_revenue_drivers`, `n_raw_material_links`, `max_input_elasticity`, `n_supply_risks`. This is the
upstream ceiling on analogical reasoning — a batch run, not code. Verify the replacement data is not
itself default-filled before swapping (see O2 for the pattern).

### D3: Edge extraction (the transmission layer)

Sizing measured: 73,626 total chunks (217.7M chars ≈ 54.4M tokens); **34,563 chunks** carry ≥1
supply-chain term (104.3M chars ≈ **26.1M input tokens**); 9,541 carry ≥2. Estimated **~31,106 edges**
at ~0.9/chunk, ~2.18M output tokens, **$5.22 (cheap tier) – $86.98 (mid tier)** batch cost — against
**9 production causal edges** today (`graph_causal_edges` minus the 6 `TEST_*` rows).

---

## Appendix A: reproduction commands

### A.1 Test suite blocker (O7)

```bash
python -m unittest discover -s reality_engine/tests -p "test_*.py" 2>&1 | tail -5    # exit 5, no summary
python -m unittest reality_engine.tests.test_cli_and_dashboard -v -f 2>&1 | grep -A20 "^FAIL:"   # first failure
git status --porcelain | grep -E "cli\.py|test_cli_and_dashboard|composite_screener|dashboard\.py|orchestrator\.py"
```

### A.2 Benchmark + profile (O1, O2, O4)

```bash
python - <<'PY'
import cProfile, pstats, io, time
from reality_engine.agent.orchestrator import AgentOrchestrator
o = AgentOrchestrator(); t0 = time.perf_counter()
pr = cProfile.Profile(); pr.enable()
o.synthesize_daily_alpha_report(universe="nifty200", top_n=5, screener_pool_size=20)
pr.disable(); print("wall %.1fs" % (time.perf_counter() - t0))
s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(18)
print("\n".join(l for l in s.getvalue().splitlines() if "vector_store" in l or "hybrid_search" in l or "evaluate_candidate" in l))
PY
```

### A.3 Import tax (O3)

```bash
python -X importtime -c "import reality_engine.cli" 2>&1 | sort -t'|' -k2 -rn | head -12
```

### A.4 Query plans + timings (O5, O6)

```bash
python - <<'PY'
import sqlite3, time
con = sqlite3.connect('file:reality_engine/data/equity_intelligence.db?mode=ro', uri=True)
for name, sql, p in [
  ("chunks by symbol", "SELECT chunk_id, content FROM document_chunks WHERE symbol = ? LIMIT 5", ("HAL",)),
  ("chunks by isin",   "SELECT chunk_id FROM document_chunks WHERE isin = ? LIMIT 5", ("INE066F01020",)),
  ("rankings by stock","SELECT lens_family FROM model_explainer_rankings WHERE stock_id = ? AND investor_majority = ? LIMIT 8", ("HAL","all")),
]:
    t0 = time.perf_counter()
    for _ in range(3): con.execute(sql, p).fetchall()
    print(f"{name:20s} {(time.perf_counter()-t0)/3*1000:9.3f} ms  {[r[3] for r in con.execute('EXPLAIN QUERY PLAN '+sql, p)]}")
PY
```

### A.5 New modules built this session

```bash
python -m unittest reality_engine.tests.test_peer_graph_and_hygiene -v
python -m reality_engine.scripts.run_substrate_hygiene
python -m reality_engine.scripts.run_peer_graph --top-k 20
python -m reality_engine.scripts.run_peer_graph --dry-run --top-k 20   # gate report only, no writes

# read back analogues (drivers + lift are the useful part)
python - <<'PY'
from reality_engine.db.repository import repo as R
from reality_engine.processing import peer_graph as pg
with R.db.session() as conn:
    for r in pg.neighbours(conn, "TITAGARH", top_k=3): print(r)
PY
```

---

## Appendix B: suggested continuation order

1. **O7** first — it is the only item blocking anyone's ability to verify a change end to end.
2. **O1** — highest correctness value; it makes the canonical moat substrate actually used.
3. **O3 + O4** together — both are pure latency, independently verifiable, no semantic risk.
4. **O2** — coverage semantics only; explicitly avoid the source swap (G2).
5. **O5, O6** — cheap hardening; O5 must be described as landmine removal, not a production win.
6. **D2** before **D3** — re-distilling the degenerate parameters is what gives the peer graph real
   dimensions; edge extraction then builds on a substrate worth traversing.

**State of the peer graph as measured 2026-09-20** (so a future reader can tell whether D2 moved the
needle): 4,996 symbols in frame, 753 quarantined symbols excluded, 2,509 anchors, **12 of 29 features
active** (all 8 distilled dims dropped as near-constant), 50,180 pairs, median per-anchor baseline
similarity 0.055, 492 unit-contaminated quarterly values rejected. HAL's nearest structural analogues
were DIVISLAB (0.9683), ITC (0.9652), SUNPHARMA (0.9584) — i.e. large-mature-business financial-shape
twins driven by `log_market_cap` and `revenue_recurrence_pct`, **not** defence analogues. If a future
run still produces that shape, D2 has not landed.
