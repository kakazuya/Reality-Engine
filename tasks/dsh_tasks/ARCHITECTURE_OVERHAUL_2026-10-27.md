# Task — architecture plan: extract everything, with correct labels (design doc only)

## Goal
Shivam approved the direction in `tasks/LABELS_TAGGING_PLAN_2026-10-27.md` (read it first, fully). Turn it into
a buildable **architecture plan**: how every source we hold or will fetch becomes labelled, graded, point-in-time
chunks and facts that any query can filter fast. Output one document, `tasks/ARCHITECTURE_OVERHAUL_2026-10-27.md`.
No code changes and no data writes.

## Read before writing (real state, not assumptions)
- `tasks/FRAMEWORK.md` (authority), `tasks/STATE.md`, `tasks/optimizations/HANDOFF_2026-10-26.md`,
  `tasks/optimizations/learn/C1C2_RESULTS_2026-10-26.md`.
  - Wide test verdict: chunker_v2 + headers wins on decks and concalls.
  - LLM facts are not a search corpus.
- Code:
  - `reality_engine/processing/chunker_v2.py`, `reality_engine/scripts/load_deck_chunks.py`;
  - `reality_engine/db/schema.sql`, `reality_engine/db/readonly.py`;
  - `plugins/reality-data/server/` (search_docs, facts, price tools);
  - `reality_engine/scripts/tg_backfill.py` and the `tg_*` scripts;
  - `reality_engine/scripts/coverage_report.py`, `market_session_coverage.py`.
- Live data, **read-only via `reality_engine.db.readonly.connect_ro`**. Bounded queries only; no correlated
  subqueries or unindexed GROUP BY on `document_chunks` (2.9M rows); sample by rowid if needed.
  - Stores: `equity_intelligence.db`, `chunks_v2.db`, `concall_facts.db`, `deck_figures.db`, `ar_facts.db`,
    `results_xbrl.db`, `bse_announcements.db` under `reality_engine/data/`.
  - Tables to profile: `master_companies`, `company_industry`, `index_membership`, `price_bands`, `shp_index`,
    `mkt_nse_pit_xbrl_facts`, `raw_documents`, `corporate_documents`, `telegram_posts`, `tg_orders`.

## Known facts to build on (verified 2026-10-27)
- **Chunk-level labels:**
  - symbol/ISIN: 99–100% on company docs;
  - `sector_id` / `industry_id`: 0%;
  - fiscal_period: sparse;
  - master sector: 61%;
  - market-cap tier and Nifty flags: current-only;
  - `index_membership`: one snapshot (2026-09-30).
- **Production concall chunks are stored lowercased.** Proper nouns are lost; the v2 re-chunk must keep case.
- **Deck store:** `chunks_v2.db` holds 23,321 real decks chunked with the old chunker (re-chunk with v2).
- **Concalls:** 6,086 known but not fetched.
- **PIB:** 61k ingested but not chunked.
- **Results PDFs:** notes pages not fetched. Only 27% of XBRL files carry the notes text, so link PDF notes to XBRL
  by company + quarter + standalone/consolidated + "note N".
- **Opinions (subscribed analysts):**
  - Drive research: ~252 reports, 107 member videos + 62 DailyBytes, 126 h of audio (Hinglish), 2,066 chart PNGs.
  - Telegram: 17 topics, 4,504 posts.
  - Drive dates: btime is unreliable for older items; 331 of 529 docs were edited after upload.
- **ASR (hosted DeepInfra):** Qwen3-ASR-0.6B/1.7B is best (timestamps, digits) and writes Devanagari for Hindi.
  It mishears proper terms as near-sounding words; correct against a per-video glossary (screen OCR + filings
  terms + folder title). Laptop GPU is too slow for ASR and OCR; OCR runs on CPU at ~5.5 s per dense frame.
- **Memories:**
  - raw data on D:\RealityEngine;
  - no paid spend without Shivam's OK;
  - free models only on subscriptions;
  - private paid-community content never goes to GitHub.

## What the document must contain
1. **Target architecture diagram (text)**:
   - sources → raw store → parse → chunk (v2) → layer-1 tags → stores → search / facts tools;
   - layer-2 `company_state` and layer-3 macro links joined at query time;
   - `opinions.db` kept separate.
2. **Store layout**: which DB file holds what (keep SQLite + NumPy vector folders; no Postgres), and DDL for every
   new or changed table. At minimum:
   - unified v2 chunk table(s) with all layer-1 tags;
   - `company_state_daily` (or interval form: pick one and justify);
   - macro-link tables;
   - `opinions.db`: `opinion_sources`, `opinion_docs`, `opinion_calls`, `opinion_claims`, `opinion_outcomes`;
   - per-tag coverage scorecard table.
3. **Per-source pipeline spec**, one section each:
   - concalls, decks, annual reports, results notes PDFs, material announcements / order wins;
   - PIB, Union and state budgets, RBI policy, economic news;
   - analyst videos (ASR + frames + glossary), analyst Drive docs, Telegram.

   For each: inputs, parser, chunking rule, every label and how it is derived, `known_at` rule, quality grade,
   failure modes, and current volume vs target volume.
4. **Label derivation rules**: deterministic first, model second.
   - For every model-derived tag: which free model, the prompt contract, and how precision is measured (hand-checked
     sample size) before roll-out.
5. **Point-in-time rules and look-ahead tests**.
6. **Query examples**: show the SQL / tool call for each of the 5 example queries in the plan's §1, against the
   proposed schema, with expected index use.
7. **Build order with estimates** (wall time, CPU/GPU, $ only where paid). Mark what can run in parallel and which
   DB each step writes (one writer per DB).
8. **Gaps and decisions for Shivam**, short.

## Rules
- Read-only everywhere. Write only `tasks/ARCHITECTURE_OVERHAUL_2026-10-27.md` and `.tmp/` in your worktree.
  No network, no paid APIs. Do not commit; the manager does.
- Every number you state about current data must come from a query you ran or a file you read; cite it inline
  (table + count). Mark anything not verified as "unverified".
- Plain words, short sentences, tables where they help. No marketing language.

## Acceptance checks
1. All 8 sections present; DDL parses (`sqlite3` in-memory `executescript` on each DDL block, show the result).
2. Every current-volume number is cited to a query or file.
3. The 5 example queries are written against the proposed schema.
4. Open questions from the plan's §9 each get a recommendation.

## Test command(s)
```bash
python -c "print('doc-only task')"
```

## Report
A summary of the plan, the DDL check output, the list of queries you ran, unverified items, and the tool calls you
used.
