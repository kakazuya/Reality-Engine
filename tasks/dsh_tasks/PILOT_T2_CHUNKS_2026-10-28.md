# Task — fix chunker v3, then build the pilot chunk store (T2) for the 30-ISIN pilot universe

## Goal
This is step 4 of the golden rule (pilot), the T2 half. `tasks/arch_v3/PILOT_SPEC.md` names 30 ISINs for the reader/chunk tier. `reality_engine/processing/chunker_v3.py` (merged) was prototyped on 48 docs, with these measured results:
- top-5 hit rate 0.80;
- boundary quality 0.82, and every AR failure is a mid-sentence cut in `_split_long`;
- tag precision 0.88, below the 0.90 gate;
- `forward_looking` fires on 85% of concall chunks, so it doesn't discriminate.

The query layer v0 (merged, `reality_engine/query/`) says its biggest remaining blocker is precise passage retrieval with chunks_v3: 40 + 7 cases.

## Do
1. **Fix the chunker:**
   - `_split_long` extends to the next sentence end within +15% of MAX_CHARS, and marks continuation chunks `note_cont`.
   - Tighten `forward_looking`: it needs a forward verb plus a future time/target anchor.
   - Fix the tag rules from the hand-check failures in `tasks/arch_v3_chunks/INDEX_SPEC.md`.
   - Re-run the 50-chunk hand check. The target is boundary ≥ 0.95 and tag precision ≥ 0.90 (Wilson LB reported).
2. **Build** `.tmp/pilot/chunks_v3_pilot.db` (the chunks_v3 DDL from `tasks/arch_v3/SCHEMA_V3.sql`, FTS5 unicode61, plus `chunk_entity` and `chunk_tag`):
   - every FY25+ (known_at ≥ 2024-04-01) original for the 30 PILOT_SPEC ISINs: concalls, decks, ARs, results notes and announcements, from D: (`concall_pdfs`, `deck`/`decks*`, `annual_report` + `pdfs`, `results_pdfs`, `material_announcement`, `nse_announcements/*/attachments`). The raw downloads finished today;
   - the known_at comes from the filing record (BSE DissemDT / NSE exchdisstime / corporate_documents), **never** the file date. Check the first 20 rows against the filing records;
   - scanned PDFs: record `grade=C` and `needs_ocr` (no OCR in this task).
3. **Wire it in:** let the EVIDENCE planner in `reality_engine/query/planners/evidence.py` read `chunks_v3_pilot.db` when it is present, via an env var `REALITY_CHUNKS_V3` with filter push-down (isin, doc_type, known_at ≤ as_of, section/speaker/tag). FTS + filters only; no dense vectors.
4. **Measure:**
   - re-run `tasks/answer_bench/run_v0.py` on the benchmark cases whose ISIN is in the pilot 30, with and without chunks_v3; report before/after;
   - EVIDENCE p50/p95 latency, target < 2 s;
   - coverage: docs found vs expected per ISIN × doc_type, with every missing original listed.

## Rules
- Read-only on D: and all DBs. Write only in this worktree (code, tests, `.tmp/pilot/`, `tasks/pilot_t2/`).
- No network, no paid embeddings, no commits.
- This is the pilot only. No chunking beyond the 30 ISINs.

## Acceptance checks
1. `python -m unittest reality_engine.tests.test_chunker_v3` passes, with new tests for the split and forward-looking fixes.
2. `tasks/pilot_t2/REPORT.md`:
   - the hand check (boundary, tags);
   - chunks per doc type;
   - coverage per ISIN;
   - the known_at check;
   - the before/after benchmark on the pilot ISINs;
   - EVIDENCE latency.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_chunker_v3
```

## Report
Give:
- boundary and tag precision, before → after;
- the chunk counts;
- coverage gaps;
- the before/after benchmark, with EVIDENCE latency;
- your tool-call count.
