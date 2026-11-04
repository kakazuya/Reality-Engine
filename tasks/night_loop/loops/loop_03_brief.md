# Loop 3 brief: printed comparatives first, then the KPI worker (Phase 2)

Started by the wrapper on Wed 4 Nov evening. All code workers are DeepSeek (`dsh`) until 06:30 IST on Thu 5 Nov. There is no 150k context cap: the limits in `LOOP_BRIEF.md` stand.

## State on main
`l2segments` and `l2structured` are merged. `compute_start` is not set in `pilot10_profile.json`, and it stays unset. `pilot10.db` predates both merges, so rebuild `stores`, `registry`, `pages`, `ratios` and `segments` once on all 10 companies, then run A1 on the dev set and record that as this loop's baseline.

## 1. Printed comparatives (T-057, Shivam's ruling, top priority)
A quarterly results table prints comparative columns. Earlier reports called these quarters gaps or asked for downloads, and that was wrong.

Evidence, measured by the wrapper on `pilot10.db`:
- **Columns in the PDF:** current quarter, preceding quarter, year-ago quarter, current year-to-date, prior year-to-date, and last full year. Q4 tables print fewer year-to-date columns.
  - HDFCBANK filing of 2026-10-17, page 2, Interest earned: 83426.60, 79362.78, 76690.70, 162789.38, 154160.90, 307522.08.
  - MARUTI filing of 2026-10-27, page 2: the same six-column layout.
- **Not in XBRL:** the raw results XBRL carries only contexts `OneD` (quarter) and `FourD` (year to date), with no comparative columns. `results_xbrl.db` cannot supply them; `doc_page.text` for `doc.doc_type='results'` can.
- **Coverage:** the four window filings print eight distinct quarters (Q3 FY25 to Q2 FY27).
- **TTM from one filing:** last full year + current year-to-date - prior year-to-date, with no older document.
- **Text noise:** the text layer prints one number per line and misreads characters. HDFCBANK has `39.09.2026` in a date header and `79362,78` in a value; MARUTI has `I,005,746` and `s43.294`. Do not trust a digit that has not been checked.
- **Arithmetic is the check:**
  - HDFCBANK 83426.60 + 79362.78 = 162789.38, as printed.
  - MARUTI's sale of products 506,155 + 499,591 = 1,005,746, as printed.
  - MARUTI's total revenue line reads 533,402 and 524,551 against a half-year of 1,057,959 (itself misread as `1,057.959`). Its components 499,591 + 17,364 + 7,602 give 524,557, so the misread digit is detectable.
- **Hard cases:**
  - SBILIFE's results pages did not match my simple P&L search in the first 12 pages, so check its Ind AS-free insurer format by hand.
  - Pages listed in `pilot10\logs\needs_ocr_pages.csv` have no usable text. Report them; do not run OCR here.

Requirements for the worker brief. Add the file, function and line evidence the template asks for:
1. A new table, proposed name `fin_quarter_printed`: symbol, isin, period_end, period_type (quarter, ytd, fy), column_role (current, preceding, year_ago, ytd, prior_ytd, last_fy), basis, line_item (the canonical names `stores.QUARTER_TAGS` and `SECTOR_TAGS` already use), value, unit, scale, doc_key, page, known_at, check_status.
2. Unit and scale come from the table header of that filing (crore, lakh, million), and values are stored in rupees like the XBRL rows.
3. `known_at` is the filing date of the document that printed the number, never earlier. A printed comparative is never back-dated.
4. Every row carries `check_status`: `sum_ok` (quarter and year-to-date or component arithmetic holds), `xbrl_ok` (equals the XBRL value), or `unchecked`. A failed check stores nothing as fact: log it for review. Never guess a repaired digit into an answer table.
5. When the same period is printed twice with different values, keep both rows and report it as a restatement.
6. Ratios: YoY, QoQ and TTM read XBRL for the quarter it holds and the printed table otherwise. `known_at` rules still decide what a date can see. Do not use `compute_start`.
7. Universal parser: it works from the printed header and line labels, with no per-company code. Fast check: `--part comparatives --symbols HDFCBANK,MARUTI,KEC`, plus a test file `reality_engine/tests/test_pilot3_comparatives.py` (the T-057 accept command).
8. Docs named in the brief: `docs/PILOT3_BLUEPRINT.md` and guide section O10.

Accept by: rows per company per quarter, share `sum_ok` or `xbrl_ok`, 20 rows hand-checked against the page, A1 before and after, guards. Revisit the questions earlier reports held back for older quarters, such as SBILIFE and SUNPHARMA `pe`. Where a date is earlier than any held filing's `known_at`, say exactly that; do not call it missing data.

## 2. KPI worker
`Eagle-sonnet-l2kpi` (2690518) stopped at the usage limit with no report, and its work is unreviewed. Give a DeepSeek worker `loops/loop_02_worker_kpi.md`, tell it to start by `git cherry-pick 2690518`, and have it finish and report. Review the result by reading the code and the rows.

## 3. Then, by size of the unmet list
Guidance precision (wrong rows such as "Cables ... maybe 6%" and a questioner's "8% to 8.5%" stored as company guidance), `transcript_statement` for ETERNAL and INFY, then the KEC transcript candidate (`scratch\c_kec*.db`, manifest already has the 4 rows).

MARUTI transcripts stay last: they need a browser fetch.

## Report
A1 before and after per company, build timings, worker verdicts, the unmet list. Update `HANDOFF.md`. The wrapper merges.
