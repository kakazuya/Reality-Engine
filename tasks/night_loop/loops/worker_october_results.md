# Worker: three more October results filings

Goal: the pilot10 raw set holds Q2 FY26 results filings of HINDUNILVR, MARUTI and SBILIFE, and the fetch runner's window agrees with the profile.

Ticket: T-065

Evidence: T-063 listed these BSE records:
- HINDUNILVR: NEWSID `cb8dcf99-6ddb-4d7f-8c0d-4d683f357905`, attachment begins `c1326928-`, 2025-10-23T11:11:45.
- MARUTI: NEWSID `3fcaa94c-bc0d-4bae-a67a-552ad3b2a3b2`, attachment begins `95ad289a-`, 2025-10-31T14:24:26.
- SBILIFE: NEWSID `93c5a180-4f94-4fc8-8bc4-ab5675ff3e3a`, attachment begins `4257e2dd-`, 2025-10-24T15:31:16.
- Method: `D:\RealityEngine\pilot10\scratch\w_results_fix.py`, the same script pattern, safe to repeat. It downloaded `https://www.bseindia.com/xml-data/corpfiling/AttachHis/<attachment>.pdf`. Find the full attachment names in the same BSE data that script used.
- `D:\RealityEngine\pilot10\runners\run_fetch.py` has `--window-start 2025-11-01`, and `tasks/night_loop/pilot10_profile.json` has `window_start` 2025-10-01. Change the runner to 2025-10-01.
- New manifest rows are CSV-only, and a later `run_fetch --fetch` rewrites the CSV from `raw_manifest.db`, which would drop them and the rows from `add_maruti_transcripts.py`, `w_add_cover_letters.py` and `w_results_fix.py`. Add them to `D:\RealityEngine\pilot10\raw_manifest.db` as well, or report exactly why that is not safe, after reading how `Manifest` in `reality_engine/scripts/fetch_pilot60_history.py` writes.

Files: scripts and data only under `D:\RealityEngine\pilot10`. No product code. Do not write `pilot10.db`, `pages.db` or `combined*.db`.

Accept:
1. A table: company, quarter, source URL, pages, first-page heading, `dissem_ts`.
2. `python -m reality_engine.pilot3.docs_collect --profile tasks/night_loop/pilot10_profile.json --symbols HINDUNILVR,MARUTI,SBILIFE --out D:\RealityEngine\pilot10\scratch\w_results2_pages.db` on a sqlite3 `backup` copy of `D:\RealityEngine\pilot10\scratch\w_results_pages.db`: rc 0, the new documents typed `results`.
3. Row counts of `manifest.csv` and `raw_manifest.db` before and after, and all site rows present in both.

Stop if: an exchange blocks you after two polite tries. Report what you tried; do not work around a block. Free RAM under 2.5 GB for 10 minutes also stops the job.

Budget: 40 tool calls. End with `Docs updated:` naming nothing in the repo, because the wrapper records the result.
