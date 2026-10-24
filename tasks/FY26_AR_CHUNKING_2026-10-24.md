# FY26 annual-report chunking — 2026-10-24

Owner: Shivam · Worker: DeepSeek · Status: **in progress** (this note is updated in place; the final
counts land in "Result" at the bottom).

## 1. Worker benchmark (1 vs 2 vs 4) — done 15:1x

`--ingest-workers` in `reality_engine/scripts/run_annual_report_ingest.py` is **inert**: the flag is
only interpolated into the log line (line 197) and never read. `--local-only` is a serial `for` loop
(`_local_only`, lines 83-103). So the CLI cannot run 2/4 workers at all today; the arms below were
measured by a driver that calls the same `PDFIngestor.ingest_pdf` (same DB, same FTS, same vector
store) on **three disjoint report sets** (40 FY26 reports each, round-robin split so page counts are
comparable), one arm after the other, identical env (resource-guard targets relaxed to
mem 96% / cpu 95% / max-wait 1 s — the default guard was sleeping 30 s twice per document because
machine memory sits above the 85% target; that alone was 60 s/report, ~20x the real work).

| arm | workers | reports | pages | wall (s) | reports/min | pages/min | chunks | CPU mean (% of 8) | CPU max core (%) | DB-lock errors | failures |
|-----|---------|---------|-------|----------|-------------|-----------|--------|-------------------|------------------|----------------|----------|
| w1  | 1       | 40      | 6,269 | 62.6     | 38.3        | 6,009     | 5,106  | 16.9              | 24.6             | 0              | 0        |
| w2  | 2       | 40      | 6,216 | 79.4     | 30.2        | 4,697     | 5,041  | 16.8              | 24.0             | 0              | 0        |
| w4  | 4       | 40      | 5,632 | 42.6     | 56.3        | 7,933     | 4,514  | 23.5              | 29.9             | 0              | 0        |

Per-core CPU mean over the arm wall: w1 `[15.1, 10.4, 20.6, 12.2, 16.4, 14.2, 21.4, 24.6]`,
w2 `[21.3, 13.2, 24.0, 13.5, 19.9, 12.4, 16.0, 13.7]`, w4 `[27.1, 21.1, 25.2, 21.7, 25.9, 21.4, 29.9, 15.8]`.
All arms: 0 failed, 0 `database is locked`, 0 duplicates.

### Bottleneck

Measured on the live serial run (`--local-only`, n=818 reports, 15:00-15:55) from the per-document log
timestamps:

- sha256 + PyMuPDF extract + chunk: **median 1.0 s** (p90 2.0 s).
- persist (`document_chunks` insert + FTS5 insert + vector-store append): **median 1.0 s** (p90 2.0 s).
- resource-guard waits after tuning: 42 in the whole window (all ≤1 s).

- **Not CPU-bound.** One core is busy at w1 (16.9% of 8), ~1.9 cores at w4 (23.5%); no core above 30%.
  4 threads bought only 1.47x, and 2 threads were *slower* than 1 (dashboard interference between
  arms; rclone was also running).
- **The wall is the SQLite writer.** Persist is ~1 s/report and serialized (single writer, WAL);
  w4's 56.3 reports/min ≈ the 60/min ceiling implied by 1.0 s of write per report. Parse is fully
  hidden behind the writer at 4 workers, so the DB write path (chunk inserts + FTS5) is the limit.
  Contention shows up as latency, not errors (`busy_timeout` 30 s absorbs it).
- **Disk is not the limit** (guard reports 0% disk busy); the network copy is byte-wise irrelevant to
  chunking because rclone and the chunker touch different files.

### Decision

Serial CLI first (what the task asked for), then **4 workers** once it was clear serial cannot finish
inside the window (the CLI managed 22-37 reports/min under restore+download contention). The parallel
driver (`fy26_parallel.py`, scratch) calls the same `PDFIngestor.ingest_pdf` and sets `is_processed`
exactly like `_local_only`.

Two hazards had to be fixed before 4 workers were safe, both found by running it:

1. **`VectorStoreManager.add_chunks()` has no lock** and computes append offsets from its own in-process
   row count, so N ingestors appending to the same `vectors.f32`/`vectors_meta.jsonl` overwrite each
   other. The driver wraps `add_chunks` in a process-wide lock.
2. **One vector store per worker costs ~1.2 GB each.** With 4 stores the process was 5.2 GB on a 17 GB
   box (0.8 GB free) and the run stalled for 6 min at ~0% CPU — page-file thrash, not a DB lock. Sharing
   one store across the 4 ingestors (behind the lock) dropped it to 2.7 GB and restored ~50 reports/min.

Final throughput ~45-50 reports/min vs 22-37 serial. Follow-ups for `--ingest-workers` to become real:
implement it in `_local_only` with a shared, locked vector store, and pin
`REALITY_ENGINE_EMBED_BACKEND=onnx` for local chunking (the default `auto` backend's HTTP probe/fallback
path was one more source of long stalls when the box is under memory pressure).

## 2. Restore + download state

- rclone restore of 4,295 Drive PDFs: C: branch (468) finished 15:05; D: branch finished 16:53.
  `RESTORE_DONE rc=1`: one refused file (KUWERIN, "abusive/malware", 403 cannotDownloadAbusiveFile) and
  a directory-modtime error. Everything else landed: D: 3,826 files, C: 468.
- Not-on-Drive set: 1,001 FY26 rows (ar_facts counts 683; `corporate_documents` carries 5,294 dated FY26
  rows vs ar_facts' 4,978 done). Stale `local_file_path` cleared, then
  `--download-only --since 2026-04-01 --workers 2` fetched 1,065 of 1,069 (4 hit `database is locked`
  because chunkers were writing; re-run picked them up). KUWERIN fetched from BSE the same way.
- 7 KUWERIN rows in `corporate_documents` point at a D: directory that was never restored (no date in
  the interim-date columns, so they fall outside the `>= 2026-04-01` queue): they need a separate check.

## 3. What actually capped the throughput (measured, in order of impact)

1. **Duplicate re-ingest cost 85 s/report.** `ingest_pdf` detects a duplicate by sha, then counts FTS
   rows with `chunk_id LIKE 'doc-%'` — a LIKE over 2.7M FTS rows, ~85 s each. Several hundred restored
   rows were already ingested by earlier partial runs but still `is_processed=0`, so the queue spent
   hours re-hashing them. Fixed in the driver: hash the file (0.05 s) and short-circuit before
   `ingest_pdf`. Marking the 222 rows whose `corporate_documents.sha256_hash` already resolved took one
   UPDATE. This alone moved the tail from ~6 reports/min to ~45.
2. **Per-page RapidOCR on scanned annual reports.** Text-less PDFs route to RapidOCR page-by-page,
   minutes each, and several SME reports in the restored set are scans. For this pass OCR is disabled
   (text-layer only); those reports are flagged `is_processed=2` and listed in
   `reality_engine/data/logs/fy26_no_text.log` as an OCR backlog.
3. **Pathological PDFs.** `SDC/ANNUAL_REPORT/20261024_98222041_....pdf` spins forever inside
   `page.get_text()` and holds the GIL (kills any in-process worker pool). `is_processed=2` +
   `fy26_stalls.log`. Guarded from now on by a per-child timeout.
4. **Memory.** 4 vector-store copies (bench) or one shared store growing with every chunk's text took
   the box to 96-100% (17 GB) and everything crawled. Fixed by sharing one store, dropping the
   in-memory text copies, and running batched child processes instead of a long-lived pool.

## 4. Result (final, 19:00 IST)

### Coverage

| measure | value |
|---|---|
| FY26 annual-report rows in `corporate_documents` (filing date >= 2026-04-01) | **5,362** |
| with chunks in `document_chunks` (joined via `raw_documents`) | **5,361 (99.98%)** |
| failed (`is_processed=2`) | **1** — `SDC/ANNUAL_REPORT/20261024_98222041_...pdf`, `page.get_text()` never returns |
| pending with a local file | **0** |
| rows with no `local_file_path` | 0 |
| rows whose file is missing | 0 |

Reports ingested today: **4,748** (the rest of the 5,361 already had chunks from earlier partial
runs). New chunks appended today: **678,279**. FY26 chunk corpus total (all 5,361): **908,969**.

### Chunks per report (today's 4,748)

median **116**, mean 143, p10 34, p90 289, max 865, min 1 — 0 zero-chunk documents.

### Token / embedding price estimate

At the requested ~620 tokens/chunk: **420.5M tokens** for today's new chunks, **563.6M tokens** for
the full FY26 corpus (5,361 reports). (Actual chunker config is 512-token chunks / 64-token overlap,
so 620 is a conservative upper bound.)

### Timing

- Chunking window 15:18-19:00 IST (3 h 42 m), 4,748 reports. Average 21 reports/min over the window,
  but the last ~50 minutes ran at 40-50 reports/min (after the duplicate short-circuit fix). Serial
  `--local-only` alone managed 22-37/min on this box.
- rclone restore 14:50-16:53 (4,295 files, ~30 GB): `RESTORE_DONE rc=1` = 1 abusive file (fetched from
  BSE instead) + 3 directory-modtime errors.
- BSE downloads 15:18-16:30: 1,069 FY26 rows requested, 1,069 files fetched (4 rows hit a transient
  `database is locked` write and were re-run successfully).
- `equity_intelligence.db`: 42.6 GB -> 50.1 GB; `document_chunks` 2,261,482 -> 2,939,096;
  `raw_documents` annual reports 8,268.

### Spot check (chunk text vs the PDF page)

| report | chunk | page found |
|---|---|---|
| SANOFI (doc 39674) | #114 | p. 111 / 223 |
| HUHTAMAKI (doc 39673) | #112 | p. 63 / 115 |
| HEXT (doc 39672) | #193 | p. 110 / 206 |

3/3 chunk texts found verbatim on a PDF page.

### Failures / open items

1. **SDC** (`is_processed=2`): PyMuPDF hangs in `page.get_text()` (confirmed by an isolated subprocess,
   >90 s, 3.6 MB file). Retry with pdfplumber/OCR or exclude — 1 report.
2. **KUWERIN**: 7 further `corporate_documents` rows point at a `D:\...\KUWERIN` directory that was
   never restored; their filing-date columns are NULL, so they fall outside the `>= 2026-04-01` queue
   and were not part of the 5,362. Worth a look before declaring KUWERIN fully covered.
3. **Scan/garble quality**: no report ended up `no_text_layer` in this pass, but **70 of today's
   reports carry mis-encoded font layers** (chunks dense in control bytes, e.g. doc 37923). The PUA
   guard in `_extract_with_pymupdf` catches PUA-range poison only; a per-report "garbled rate" check
   would catch the rest (follow-up, not blocking the chunk count).
4. **Legacy vector store**: the tail (~1,300 reports, after 18:14) was chunked with the 384-d hash
   vector store stubbed out (subprocess isolation), and the in-process bench arms appended to
   `vectors.f32`/`vectors_meta.jsonl` from multiple store instances. `document_chunks.embedding` and
   the on-disk `vectors.*` index should be treated as stale for those rows; the authoritative AR
   vectors are the `vector_index_qwen8b_ar` folders built by the separate embedding job. `document_chunks`
   + FTS (the search layer) are complete and unaffected.


