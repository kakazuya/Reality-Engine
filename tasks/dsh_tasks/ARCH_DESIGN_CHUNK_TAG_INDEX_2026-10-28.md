# Task — chunking, tagging and search-index spec v3, prototyped on a small sample of real originals

## Objective
This is the companion to the query/schema design worker. That worker writes `tasks/arch_v3/` in another worktree, so don't duplicate its work: it owns the case map, schema, query layer and pilot spec.

You own **how documents become searchable chunks**, so that the EVIDENCE planner returns the right passage quickly and point-in-time. Your outputs feed the pilot build directly.

## Inputs
- `tasks/ARCHITECTURE_OVERHAUL_2026-10-27.md` §2.2 (chunks_v3 DDL), §3 (per-source specs), §4 (label rules) and §5 (PIT). Its "Manager review" section overrides the rest: never derive chunks from `document_chunks` text, because it is lowercased.
- `tasks/QUERY_ARCHITECTURE_PILOT_PLAN_2026-10-28.md` §3: the reviewer's draft chunk units.
- `tasks/master_bank/MASTER_BANK.jsonl`: the EVIDENCE-type cases, i.e. what passages must be findable.
- Originals on D: (read-only):
  - concall PDFs under `D:\RealityEngine\raw\concall_pdfs` (or the concall_refetch root; find it);
  - decks under `D:\RealityEngine\raw\decks*`;
  - ARs under `D:\RealityEngine\pdfs`;
  - results notes under `D:\RealityEngine\raw\results_pdfs`;
  - NSE announcement attachments under `D:\RealityEngine\raw\nse_announcements\pilot_2026-10-28\attachments`.
- The existing search: `plugins/reality-data/server/search_docs.py`, with its NumPy dense index plus FTS5.

## Do
1. **Pick a prototype sample:** 10 concalls, 5 decks, 3 ARs, 10 results notes, 20 announcements. Mix sectors and sizes; include scanned and badly formatted ones.
2. **Write the chunker:** `reality_engine/processing/chunker_v3.py`, with one function per doc type, following the spec. You may improve the spec, but say why.
   - Concall: speaker-turn segmentation, Q&A pairing, management vs analyst roles, the opening vs Q&A section.
   - Deck: one chunk per slide.
   - AR: section-aware (MD&A, segment, notes, related party).
   - Results notes: note blocks.
   - Announcement: the whole doc, or split by headings.

   Every chunk header carries isin, symbol_at_time, doc_type, period, known_at (from the filing record, never the crawl date), page/slide and section. **Keep the original case.**
3. **Deterministic tags:** doc type, section, speaker role, has_number, guidance verbs (expect, target, guide), forward_looking, units/currency, and entity mentions resolved to ISIN. Use a tag vocabulary list.
4. **Index design**, written as `tasks/arch_v3_chunks/INDEX_SPEC.md`:
   - FTS5 tokenizer choice (porter vs unicode61; tokens like "FY25", "Rs", "crore");
   - the filter columns and composite indexes (isin, doc_type, known_at, tag);
   - the dense index layout (per doc type or global, the dimension, IVF or flat at our scale);
   - how pre-filters are applied before ranking;
   - the rerank step;
   - the expected index size for the full corpus, from chunk counts × the sample average.
5. **Prototype and measure** in `.tmp/chunks_proto.db` (SQLite + FTS5), using the sample only:
   - chunk stats per doc type (count, token mean/p95, % with tables);
   - 15 EVIDENCE questions taken from the master bank whose companies are in your sample: does the right chunk come back in the top 5 with FTS + filters? Measure the latency;
   - a hand check of 50 chunks for boundary quality (cut mid-sentence or mid-table?) and tag precision.
6. **Projection:** the full-run time and size for all doc types, using the real counts from the catalog and the raw stores.

## Rules
- Read-only on D: and on every DB. Write only in this worktree (`reality_engine/processing/chunker_v3.py`, tests, `tasks/arch_v3_chunks/`, `.tmp/`).
- No network, no paid embeddings (no dense vectors needed; design the dense side but don't compute it), no commits. No full chunking.

## Acceptance checks
1. chunker_v3 runs on the whole sample with no crash. Offline tests pass in `reality_engine/tests/test_chunker_v3.py`.
2. INDEX_SPEC.md is written, with the measured top-5 hit rate and latency on the 15 questions.
3. The boundary/tag hand check reports precision.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_chunker_v3
```

## Report
Give:
- the chunk stats;
- the top-5 hit rate and latency;
- the hand-check precision;
- the full-run projection;
- where you changed the reviewer's spec and why;
- your tool-call count.
