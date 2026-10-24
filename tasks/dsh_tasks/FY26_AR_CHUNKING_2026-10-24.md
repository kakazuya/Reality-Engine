# Task: get every FY26 annual report chunked into the search layer

Owner: Shivam (2026-10-24: "At least we should have the chunks for FY 2026 annual reports"). Worker: you (DeepSeek). Reviewer: Claude (only if you are blocked or need a reasoning call).

## Facts already established (2026-10-24, read-only checks)

- Chunker: `python -m reality_engine.scripts.run_annual_report_ingest --local-only` (PyMuPDF parse -> chunk -> `raw_documents` + `document_chunks` + FTS in `reality_engine/data/equity_intelligence.db`; no embedding, no API). It reads `corporate_documents.local_file_path`, newest unprocessed first, skips missing files with a `missing file` warning (row stays unprocessed), sets `is_processed=1` on success. Resumable.
- FY26 annual reports (fiscal year ending 2026-03-31): `ar_facts.db` `ar_docs` has 4,978 with status `done` (5,117 rows total). Only ~294 annual reports filed in 2026 are in the search layer; 3,520 annual reports are chunked in total out of 33,705 downloaded.
- Why it stopped: the ingestion queue only ran its Nifty-200 stage (last 2026-09-25); on 2026-10-20 the PC's local PDFs were deleted after an MD5-verified upload to Google Drive; this laptop's 2026-10-21 restore deliberately excluded source PDFs; scheduled tasks are disabled since 2026-10-21.
- PDFs: 4,295 of the 4,978 FY26 files are on Drive (`gdrive:InfoDiffusion_archive/pdfs/...` -> `reality_engine/data/pdfs/...`, 468 files; `gdrive:InfoDiffusion_archive/D_pdfs/...` -> `D:\RealityEngine\pdfs\...`, 3,827 files). File lists: `%TMP%\fy26_c.txt` and `%TMP%\fy26_d.txt` (paths relative to those roots); full FY26 list `%TMP%\fy26_rel.txt`, the Drive-present subset `%TMP%\fy26_hit.txt`.
- A background `rclone copy` of those 4,295 files started 2026-10-24 ~15:30 IST, logging to `reality_engine/data/logs/fy26_ar_restore_2026-10-24.log`; it prints `RESTORE_DONE rc=N` at the end (~30 GB at ~5 MB/s, about 1.7 h). Do not start a second copy of the same files; if it ended with rc != 0, re-run the same `rclone copy ... --files-from` command (it skips files already present).
- `D:` is Shivam's personal data disk: write only inside `D:\RealityEngine\pdfs`.

## What to do

1. Wait for `RESTORE_DONE` (check the log every few minutes; do not busy-loop). Then verify counts on disk against the two lists.
2. Run the chunker with `--local-only` until every FY26 row whose file is on disk is processed. It will also walk older rows whose files are missing; that is fine (they only warn). Run it in batches (e.g. `--limit 1000`) so you can report progress, and never run two chunkers at once (one writer on equity_intelligence.db).
3. The 683 FY26 reports not on Drive: fetch them from BSE using their `corporate_documents.source_url` (the ingest script's normal download path, or `--download-only` restricted to those rows via `--since 2026-04-01`), into the same `local_file_path`, then chunk them. Be polite to bseindia.com (the script's existing worker/rate settings).
4. Verify: for FY26, count reports with chunks in `document_chunks` (join through `raw_documents`), total new chunks, chunks per report (median), reports that failed and why (no text layer, unreadable, missing). Spot-check 3 reports: a chunk's text matches the PDF page.
5. Write the result to `tasks/FY26_AR_CHUNKING_2026-10-24.md` (counts, failures, timing, chunk total and token estimate at ~620 tokens/chunk so Shivam can price embedding).

## Rules

- No paid APIs, no embedding runs, no GPU. No git commits except the result note. Do not touch other databases.
- If a step fails in a way you cannot resolve, stop and say exactly what blocked you.
