# T-230 stage F brief: annual-report pages for the observation reader (operating pages only)

Ticket: T-230 (Shivam 21 Nov 2026). Reviewer: Wolf (Opus). T-230 stages A-E are merged (bd5bd9c2):
`reality_engine/v2/observations.py`, tests `reality_engine/tests/test_observations.py` (68),
`docs/V2_SCHEMA_CONTRACT.md` section 17.

Goal: Shivam wants spare hy4-flash-free quota spent productively (unused quota is lost at reset). Annual-report
visual pages hold capacity, plant, segment, volume and order figures, but a 300-page pilot showed the routed
table_or_chart pages are mostly financial statements and notes: of 1,837 verified rows only 47 were operating
measures (capacity/order/mix/count/volume); the rest were lines like other_expenses, trade_payables, borrowings that
the stores already hold from XBRL. Read only the operating pages.

Evidence: pilot DB `.tmp/t230ar/obs_ar_pilot.db` in the main checkout (copy it; 300 pages, 55 companies, 7,158 rows,
verified 1,837; command: `python -m reality_engine.v2.observations --stores-root D:/RealityEngine/tg_build/measure10
--sample 91 --doc-types annual_report --limit 300 --workers 15 --out ...`). Stores read-only.

Steps:
1. Page filter (script, before any model call) in `pages_from_store` behind a new flag `--skip-statements`: drop a
   page whose text layer carries financial-statement or notes headings (Balance Sheet, Statement of Profit and Loss,
   Cash Flow Statement, Statement of Changes in Equity, Notes to (the) (Standalone|Consolidated) Financial
   Statements, Note No., Independent Auditor's Report tables, Form AOC-1, MGT-9/remuneration tables, CSR spend
   tables, shareholding pattern tables, share price data tables). Log kept/dropped counts by reason.
2. Measure the filter on the pilot pages: of the 290 pilot pages, how many it keeps, and the share of verified
   operating rows (capacity.*, order.*, *mix*, count.*, volume*, production*, revenue segment rows) on kept vs
   dropped pages. Target: keep >= 90% of the pages that gave verified operating rows while dropping >= 70% of all.
3. Tests (synthetic page texts per reason, and a kept MD&A page).
4. Run all 91 stores, annual_report, `--skip-statements --workers 20 --resume --out .tmp/t230ar/obs_ar_91.db`.
   hy4 quota window cap exists (hit twice on 21 Nov): the reader honours Retry-After and stops cleanly on a long
   one; then re-run the same command with --resume after the window (sleep and retry up to 3 times in-session).
5. Report under 20 lines: page counts kept/dropped, status counts, verified operating rows by measure, 30 random
   verified operating rows (seed 51) with page excerpt in `.tmp/t230ar/report_f.md`.

Files: `reality_engine/v2/observations.py`, `reality_engine/tests/test_observations.py`,
`docs/V2_SCHEMA_CONTRACT.md` (section 17 new stage F note). No other file; do not edit tasks/STATE.md.

Accept: `python -m pytest -q reality_engine/tests/test_observations.py` passes; typecheck clean; report.

Limits: read-only on stores; hy4-flash-free only; another worker (T-231) makes a few hy4 calls on the same key.
Run pytest per file.

Stop if: the filter keeps < 90% of pilot pages with verified operating rows (report and stop before the full run);
quarantine > 10% or empty replies > 20% in the full run.

Budget: about 1 hour of coding; the run is long and resumable.
