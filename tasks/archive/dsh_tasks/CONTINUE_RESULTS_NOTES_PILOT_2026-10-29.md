# CONTINUE — this run was killed mid-task by a laptop restart (29 Oct, ~02:51 IST)

This worktree already holds YOUR partial work from that run (uncommitted). Before anything else:
1. Read `PROGRESS_NOTES.md` (root) and/or `.tmp/PROGRESS_NOTES.md`, then `git status` and `git diff`.
2. Keep what is correct; re-run only the steps that did not finish. Resume long jobs from their resume points
   (manifests, --resume flags, existing .tmp DBs) instead of starting over.
3. Then finish the original brief below and give its full report. RAM is tight on this laptop: run at most
   one heavy process (bench runner, fetch, build) at a time.

---

# Task — results-notes text for the pilot (0 / 78 today), then add it to the pilot chunk store

## Goal
The pilot-60 T2 chunk build found **0 of the 78** expected results notes (`tasks/pilot60/coverage.json`, `results_notes`). The causes:
- `tasks/pilot_t2/build_chunks_v3.py:load_results_notes` finds a file only by `corporate_documents.sha256_hash`. All 78 rows have a NULL hash and a NULL `local_file_path`. The `source_url`s are BSE `AnnPdfOpen.aspx?Pname=<uuid>.pdf`.
- `D:\RealityEngine\raw\results_pdfs\<quarter>\` is empty, because the PDFs were moved to `gdrive:InfoDiffusion_archive` (see `D:\RealityEngine\raw\results_notes_run.log`, "drive move ok").
- `reality_engine/scripts/fetch_results_notes_text.py`, which builds `results_xbrl.db:results_notes`, has never been run. That table does not exist.

Results notes carry the segment notes, exceptional items and auditor qualifications that many bank questions need.

## Do
1. Add `--isins-file` and `--out-db` to `fetch_results_notes_text.py`:
   - read `filings` from the live `results_xbrl.db` read-only, through `connect_ro`;
   - write `results_notes` + FTS into `--out-db`, never into the live DB;
   - keep the PDFs under `--raw-root` = this worktree's `.tmp/results_notes_raw/`.
2. Run it for the 90 pilot ISINs (`tasks/pilot60/T2_ISINS.txt` plus the 30 regression ISINs the T2 build uses), with `--since 2024-03-31`.
   - Before downloading a PDF, look for it in the Drive copy: `rclone lsf gdrive:InfoDiffusion_archive/` (find the results-PDF folder). Copy only the files you need from there; download from BSE only what is missing, at 1 request/s, stopping on 403/429.
   - `known_at` must be the BSE announcement time (`ann` broadcast ts), never the crawl date. Check the first 20 rows against the filing record.
3. Change `load_results_notes` in the pilot builder so it resolves a document by:
   - the stored `results_notes` pages, keyed by ISIN + period + newsid; else
   - the `Pname` uuid filename under the raw root.
   Then build only the results-notes chunks into a separate pilot store (`.tmp/pilot60/results_notes_chunks.db`) with the same chunk schema, so the controller can merge it.
4. Report coverage per ISIN as expected vs found (target ≥ 90% of the 78 plus the regression ISINs). List every miss with its reason.

## Rules
- Live DBs are read-only. Write only inside this worktree. Use no paid models and make no commits.
- Disk: avoid duplicate copies. A PDF is stored once, under the raw root.

## Acceptance checks
- `python -m unittest reality_engine.tests.test_chunker_v3 reality_engine.tests.test_pilot60` passes, plus a new test for the resolver and the ISIN filter.
- The coverage report shows ≥ 90% found, and `known_at` matches the filing record for the first 20 rows.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_chunker_v3 reality_engine.tests.test_pilot60
```

## Report
Give:
- the found/expected count per bucket;
- the number of files from Drive and the number downloaded;
- the result of the known_at check;
- the output DB path and size;
- your tool-call count.
