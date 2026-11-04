# Loop 3 report (session 03, Eagle, 4 Nov 2026; times are this machine's clock)

## Status: in progress

## Baseline A1 on dev, 651/898 = 72% (`pilot10\scores\a1_loop03_base.json`)
Built from main (18:12-18:16 IST) on a copy, `pilot10\scratch\l3_base.db`, not on `pilot10.db`: GOAL section 5 bars a loop from writing the live database, and the wrapper promotes. Parts and seconds: registry 4, pages 27, stores 171, ratios 1, segments 2. Script `scratch\l3_base.sh`.

| Company | All | Some | None | Of | Rate | Loop 2 base |
|---|---|---|---|---|---|---|
| BAJFINANCE | 71 | 16 | 1 | 88 | 81% | 67 |
| ETERNAL | 65 | 20 | 3 | 88 | 74% | 58 |
| HDFCBANK | 71 | 25 | 5 | 101 | 70% | 57 |
| HINDALCO | 69 | 12 | 3 | 84 | 82% | 63 |
| HINDUNILVR | 71 | 20 | 5 | 96 | 74% | 61 |
| INFY | 65 | 17 | 9 | 91 | 71% | 57 |
| KEC | 51 | 21 | 7 | 79 | 65% | 49 |
| MARUTI | 59 | 24 | 8 | 91 | 65% | 50 |
| SBILIFE | 67 | 14 | 11 | 92 | 73% | 53 |
| SUNPHARMA | 62 | 17 | 9 | 88 | 70% | 56 |

Largest unmet needs: text in transcripts 52, `guidance.guidance` 22, `valuation_daily.pe` 22, `ratio_panel.roce` 11, `ratio_panel.dividend_payout_pct` 10, text in press releases 10, text in announcements 9, `ratio_panel.roe` 9. A1 counts a row or a page as met; it does not say the answer is right.

## Finding: read the PDF's word boxes, not the stored page text
Measured on 7 result-table layouts. `doc_page.text` scatters tables: KEC, ETERNAL and SUNPHARMA's last-FY column sits at the end of the page without labels, SBILIFE's labels are at the end of the page, HINDUNILVR's values split around the label. Sorting PyMuPDF words by y-centre and x rebuilds every one as clean rows (`scratch\l3\geo.py`, 12 lines). The worker brief requires this method.

Other findings for the brief:
- MARUTI's unit is not in the text layer: scale comes from matching the current column to XBRL.
- HINDUNILVR's column order is current, year_ago, preceding, unlike the others, so roles are tested by arithmetic.
- HDFCBANK's 2026-04-18 and 2026-07-18 filings are mostly scans (29 of 32 and 21 of 22 pages empty), and SBILIFE has about half its pages empty. They stay unread, since no OCR runs here.
- `ratios.py:153` would crash on a printed-only quarter, and `guards.py` does not score the new table in A3 (the worker adds its own check; the gate itself may not be edited by a loop).

## Decisions (for the wrapper to overrule)
1. Baseline on a copy, as above. The loop brief says "rebuild", GOAL says a loop may not write the live database; GOAL wins.
2. The brief's table grew: `period_start`, `fiscal_period`, `quote`, `raw_token`, `check_detail`, `is_reported`, because provenance (A3) and period lookups need them.
3. `pilot3_fin` falls back to checked printed rows: otherwise an investor's "Q2 FY26 revenue" has a row no tool reads. A1 is not changed: a need naming `fin_quarter_xbrl` stays a need for that table, so A1 rises only through ratios and valuation.
4. A repaired OCR digit enters only when an arithmetic or XBRL check confirms exactly that value; otherwise the cell is logged and stores nothing.

## Findings for the next worker (brief ready: `loop_03_worker_speech.md`, waits for a free slot)
- **ETERNAL and INFY transcripts give 0 statements although text is present.** ETERNAL's management are `unknown` (no titles, no lexicon list). INFY's speakers are name-only lines with no colon. KEC's real transcripts are only in the candidate `c_kec_pages.db`.
- **Hand read of all 136 guidance rows (107 on `l3_base.db` + 29 KEC candidate): about 58 wrong plus about 20 duplicates.** Judged on quotes cut at 135 characters, so the count is approximate. The families: backward-looking "Q2 performance" read as the target period; "next year" read as this year; results "at 22.6%, within the guided range" stored as targets; capex spent to date read as a range low; project total as a year's capex; sub-segment numbers under company metrics; questions; duplicates. A1 cannot see any of this: it counts them as answered.
- One correction to the loop brief: "8% to 8.5%" (row 118) is management confirming the range (Vimal Kejriwal: "I think you're right, we have been talking about 8% to 8.5%"). It is a true row, not a questioner's number.

## Workers
Both on DeepSeek, off-peak, started 18:17 IST.
| Name | Job | Branch | Brief | Status |
|---|---|---|---|---|
| comparatives | 20261104T124718Z-f826eabb | `dsh/20261104T124718Z-f826eabb` | `loop_03_worker_comparatives.md` | running |
| kpi | 20261104T124734Z-2e947e47 | `dsh/20261104T124734Z-2e947e47` | `loop_03_worker_kpi.md` (cherry-picks 2690518) | **NOT ACCEPTED, do not merge alone**; fix round queued (`loop_03_worker_kpi_fix.md`) |
| speech | 20261104T133227Z-c8ca921f | `dsh/20261104T133227Z-c8ca921f` | `loop_03_worker_speech.md` | running, started 19:02 IST |

### Review of the KPI worker (19:05 IST)
Its numbers: A1 651 to 676, A3 99.85%, tests and checkpages green. Its own hand read fails its accept: fmcg 20/20, insurance 16, pharma 14, it_services 12, consumer_internet 11, bank 10, auto 9, lenders 9, against a rule of 18/20; the brief said fix before reporting. My read of the rows confirms this and adds a defect the report did not name:
- **The sector gate wiped true rows.** `ebitda` lives in `metals.yaml` and `aum` in `lenders.yaml`, so KEC `ebitda` went 64 to 0, SUNPHARMA 70 to 0, SBILIFE `aum` 49 to 0, `roe_pct` too. A1 did not notice, because dev happens not to need them. Hidden questions may.
- **Wrong rows that raise A1:** a year-ago quarter labelled as a half year (BAJFINANCE `revenue` H1FY26 17,002.86), number fragments (`pat` 791.0), a rupee row with unit pct (`r_and_d_pct` 23,676), cash-flow lines as `net_debt`, old values of a change (`dso` 69, `market_share` 8.1), 278 rows dated before the window.
- It committed `PROGRESS_NOTES.md` and edited `tasks/STATE.md`.
Part of the 25-question A1 gain may rest on these wrong rows, which is what the fix round will show.
