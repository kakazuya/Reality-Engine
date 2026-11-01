# Task — fetch the full 2019-2024 document history for the 60 pilot companies

## Goal
Shivam approved (30 Oct 2026) fetching ALL company documents for the 60 pilot names only: annual reports, investor presentations, concall transcripts, quarterly results, and other material filings. Window: `DissemDT` from 2019-01-01 to 2024-03-31 (2024-04-01 onward is already held). Raw fetch only: no extraction, chunking, embedding or LLM.

**Why:** backtest folds F1–F3 and our own dated sector labels need what each company had filed at the time.

## Inputs
- Universe: `tasks/pilot60/UNIVERSE.csv` (60 rows: `isin, symbol, ...`). Use the symbol and scrip code valid at the time; check ISIN and symbol history, since names change.
- Metadata: `reality_engine/data/bse_announcements.db`, table `ann` (`NEWSID, SCRIP_CD, ATTACHMENTNAME, HEADLINE, CATEGORYNAME, SUBCATNAME, DissemDT, symbol`). First measure its coverage for these 60 names before 2024-04. If it is incomplete, fill it from the BSE API with the existing fetchers.
- Code to reuse, not rewrite: `reality_engine/scripts/fetch_originals.py` (`OriginalFetcher`, list CSV → resumable, paced downloader), `fetch_bse_api_raw.py`, `fetch_bse_announcements_daily.py`, `fetch_decks.py`, `concall_refetch.py`, `fetch_results_notes_text.py`, `fetch_bse_annual_report_dates.py`, `fetch_missed_ar_files.py`.
- Also use NSE corporate filings as a second source where BSE lacks a file.
- Check what is already held under `D:\RealityEngine\raw` by hash or by NEWSID before downloading.

## What to fetch
Every attachment for these 60 names in the window, in these buckets: `annual_report, investor_presentation, concall_transcript, concall_audio_link, quarterly_results, results_press_release, material_filing`. `material_filing` covers acquisitions, orders, capacity, capex, fund raising, rating actions, management changes, litigation, schemes, buybacks, dividends, and any other business update.

Skip the attachment, but keep the metadata row with a `skip_reason`, for purely routine items: trading-window closure, newspaper advertisement copies, loss of share certificates, routine compliance certificates (Reg 74(5), Reg 7(3)/40(9)). Print the full skip list with counts per `SUBCATNAME` in the report.

## Storage
- Files: `D:\RealityEngine\raw\pilot60_history\<symbol>\<bucket>\` (HDD, sequential writes only, no DBs read from D:).
- Manifest: `D:\RealityEngine\raw\pilot60_history\manifest.csv`, plus `manifest.db` in `reality_engine/data/pilot/pilot60_history_manifest.db` with: `isin, symbol_at_time, scrip_code, newsid, bucket, headline, category, subcat, dissem_ts, url, source, local_path, bytes, sha256, http_status, attempts, is_pdf, is_scanned_guess, skip_reason, fetched_at`.
- `known_at` = the filing record's `dissem_ts`, never the crawl date. Verify this on the first rows you write.

## Rate limits
No arbitrary caps. Measured: NSE took 400/min bursts and BSE +199/min with no block (28 Oct). Run BSE and NSE in parallel at those measured rates with back-off on 403/429/5xx. Keep it resumable: re-running must skip finished rows.

## Long runs
Launch the fetch detached via `Start-Process` with a log under `D:\RealityEngine\raw\pilot60_history\logs\`. Poll sparingly; do not sleep in short loops. Stay alive until it finishes, then do the checks.

## Rules
- Write only: this repo's workspace, `D:\RealityEngine\raw\pilot60_history\`, and the manifest DB named above. Do not modify any other DB.
- No paid services. No LLM.
- Use LSP for Python navigation, read/grep tools rather than pwsh for files, and `mcp__reality-data__sql` for DB queries.
- Disk: stop and report if D: falls below 50 GB free.

## Acceptance checks
- Coverage matrix: per company × fiscal year × bucket, count held; written to `tasks/pilot60/HISTORY_COVERAGE_2026-10-30.md`. Explain every empty annual-report or quarterly-results cell (listed later, not filed, fetch failed). Transcripts are expected to be sparse before about 2021; say so rather than treating it as failure.
- 40 random files: open and confirm the content matches the headline and the company, and that `dissem_ts` matches the BSE record. Report any mismatch.
- `SELECT COUNT(*)` of manifest rows with a `local_path` that does not exist = 0.
- No file with `dissem_ts` outside the window.
- Failures listed with reason and a retry count; retried at least twice.
- Non-PDF responses (HTML error pages) are not counted as fetched.

## Test command(s)
```bash
python -m pytest reality_engine/tests -q -k "fetch_originals or pilot60_history"
```
Add a small test for any new code.

## Report
Totals per bucket (files, GB); coverage matrix summary; gaps and reasons; measured rates and any blocks; skip list counts; how many scanned PDFs need OCR later; the 40-file check; elapsed time; code-intel calls vs grep/read/pwsh; calls before first edit.
