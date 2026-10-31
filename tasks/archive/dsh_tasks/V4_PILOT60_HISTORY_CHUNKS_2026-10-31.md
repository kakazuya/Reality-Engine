# Task — chunk the pilot-60 document history (2019-01-01 to 2024-03-31) on the HP

## Goal
The history fetch (`064fc13`) gave 19,942 files, now in `C:\RE\raw\pilot60_history` on this machine. None of it is searchable. Build a separate chunk store from it so history questions, and later the WP6 annual-report backfill (`tasks/arch_v4/QUERY_V4_DESIGN.md` §B.6 step 1d), can use it. Read `tasks/pilot60/HISTORY_COVERAGE_2026-10-30.md` first.

## Inputs
- PDFs: `C:\RE\raw\pilot60_history`. On the MSI the same tree is `D:\RealityEngine\raw\pilot60_history`; take the root from an env var or argument and never hard-code either.
- Filing records: `pilot/pilot60_history_manifest.db`, already copied under `REALITY_DATA_ROOT` for this job.
- Builder: `tasks/pilot60/build_chunks60_all.py` and `build_chunks60.py`, `reality_engine/processing/chunker_v3.py`. Reuse them. Do not write a second chunker.

## Work
1. Add a history mode: documents come from the manifest, not the D: tree walk and not `equity_intelligence.db`.
2. Output `.tmp/pilot60/chunks_v3_history.db`, same schema as `chunks_v3_pilot.db`. Do not touch or merge into the live pilot store.
3. `known_at` and every date come from the manifest's filing record, never file dates. Print the first 20 rows beside their manifest rows and check them before the full run. Stop if any differs.
4. Pilot first: 200 files stratified by document type and year. Report seconds per file, peak RAM, and share with no text layer.
5. Scanned PDFs: record `grade=C` and `needs_ocr`. No OCR in this task.
6. Then the full run, resumable, at most 4 shards. Other jobs share this machine; check free RAM and drop to 2 shards if under 3 GB free.
7. Skip duplicates by content hash, and count them.

## Acceptance checks
- Every manifest row ends as chunked, `needs_ocr`, duplicate or failed, with a count for each. The four counts sum to the manifest total.
- Coverage table by company, document type and fiscal year.
- 30 random chunks hand-checked against their PDF pages: text, page number, `known_at`. Report the failures as found.
- FTS query for 10 terms returns results, with timings.
- Report the final DB path and size so the reviewer can copy it back.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_pilot60_history_chunks.py -q
```
Create that test file: known_at comes from the manifest, duplicates are skipped, resume does not double-write.
