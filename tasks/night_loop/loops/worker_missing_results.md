# Worker: missing results filings on pilot10

Goal: the pilot10 raw set holds the quarterly results filing of HDFCBANK for Q2 FY26 and of INFY for Q2 FY26 and Q4 FY26, as real multi-page results documents.

Ticket: T-063

Evidence, from `D:\RealityEngine\pilot10\raw\manifest.csv` (columns include symbol_at_time, bucket, headline, dissem_ts, url, source, local_path, sha256, status), rows with `result` in `bucket`:
- HDFCBANK: 2026-01-17, 2026-04-18, 2026-07-18, 2026-10-17. Missing Q2 FY26, filed about 18 Oct 2025.
- INFY: 2026-01-14, 2026-07-23, 2026-10-23. Missing Q4 FY26, filed about April 2026, and Q2 FY26, filed about October 2025.
- Likely cause for the October filings: `D:\RealityEngine\pilot10\runners\run_fetch.py` runs `reality_engine.scripts.fetch_pilot60_history` with `--window-start 2025-11-01`, while these two companies report in mid-October. The April INFY filing is inside that window, so its cause is different: find it (bucket, headline match, or a held document typed `announcement`; two INFY filings of 379 pages are typed that way).
- First look in held stores before downloading: `D:\RealityEngine\pilot10\raw`, `results_xbrl.db.filings`, and the raw BSE and NSE folders. Check the page count and first-page heading of whatever you use.
- `infosys.com` refuses this PC, so use exchange filings.
- To add a file: the method in `D:\RealityEngine\pilot10\scratch\add_maruti_transcripts.py`: back up the manifest, append once, safe to repeat, `dissem_ts` from the exchange record. Or re-type an existing row if that is the fault, and say so.

Files: scripts and data only under `D:\RealityEngine\pilot10\scratch`, `D:\RealityEngine\pilot10\raw`, `D:\RealityEngine\raw`. No product code; do not change `run_fetch.py` for other companies. Do not write `pilot10.db`, `pages.db` or `combined*.db`.

Accept:
1. A table: company, quarter, source URL or held path, pages, first-page heading, `dissem_ts`.
2. `python -m reality_engine.pilot3.docs_collect --profile tasks/night_loop/pilot10_profile.json --symbols <S> --out D:\RealityEngine\pilot10\scratch\w_results_pages.db` on a copy of `D:\RealityEngine\pilot10\pages.db`: rc 0, the new documents typed `results`.
3. The same check for all 10 companies: list any other window quarter with no results filing. Fetch nothing more than the three named; list the rest.

Stop if: an exchange blocks you after two polite tries. Report what you tried; do not work around a block. Free RAM under 2.5 GB for 10 minutes also stops the job.

Budget: 50 tool calls. End with `Docs updated:` naming nothing in the repo, because the wrapper records the result.
