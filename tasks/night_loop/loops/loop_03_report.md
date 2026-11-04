# Loop 3 report (session 03, Eagle, 4 Nov 2026; times are this machine's clock)

## Status: stopped at the 400k context line, 20:20 IST. **Nothing is ready to merge yet.**
Two fix workers were still running when this was written, and one more round is queued. No branch has passed review. Sections below hold the evidence.

## For the wrapper
| Work | Merge this branch once reviewed | State at 20:20 IST | A1 dev, alone against 651 |
|---|---|---|---|
| Printed comparatives (T-057) | `dsh/20261104T140210Z-42e59ee9`, on `dsh/20261104T124718Z-f826eabb` | Fix running. First round has wrong TTM, so do not merge that one | First round 680; wrong until the fix lands |
| Speakers and guidance | `dsh/20261104T143838Z-20a19ffb`, on `dsh/20261104T133227Z-c8ca921f` | Fix running | First round 662 |
| Sector KPIs | `dsh/20261104T134520Z-2ba2330d`, then round 2 | Round 2 **not started**: `loops/loop_03_worker_kpi_fix2.md`, start it with `base=dsh/20261104T134520Z-2ba2330d` | 677, about 75% of new rows right on my read of 67 |

A1 per company, each candidate alone (not additive; never combined or built together):
| Company | Base | KPI fix | Comparatives, first round | Speech, first round |
|---|---|---|---|---|
| BAJFINANCE /88 | 71 | 71 | 77 | 71 |
| ETERNAL /88 | 65 | 68 | 66 | 65 |
| HDFCBANK /101 | 71 | 75 | 74 | 71 |
| HINDALCO /84 | 69 | 69 | 76 | 69 |
| HINDUNILVR /96 | 71 | 74 | 74 | 71 |
| INFY /91 | 65 | 65 | 65 | 65 |
| KEC /79 | 51 | 51 | 54 | 62 |
| MARUTI /91 | 59 | 61 | 61 | 59 |
| SBILIFE /92 | 67 | 75 | 67 | 67 |
| SUNPHARMA /88 | 62 | 68 | 66 | 62 |
| Total /898 | 651 | 677 | 680 | 662 |

These figures are the workers' and A1 counts rows, not right answers. Guards were run by the workers; I did not re-run them. A2 not run. Hidden split not read.

Build seconds on a copy: registry 4, pages 27, stores 171, ratios 1, segments 2. Workers measured kpi 191 s for ten, comparatives 15-33 s a company, A1 about 8 s.

At merge:
- `docs_collect --symbols KEC` on the real `pages.db` (KEC's real transcripts are only in `scratch\c_kec_pages.db`).
- `--part comparatives` must run before `--part ratios`.
- Remove `PROGRESS_NOTES.md` and `tasks/STATE.md` edits from any branch that still carries them. I did not write `tasks/STATE.md`: LOOP_BRIEF limits this loop's commits to `tasks/night_loop/`, so its next action is in `HANDOFF.md`. The wrapper updates STATE and `tasks/efficiency/WORKER_REVIEW_LOG.xlsx` from the table at the end.

## Unmet needs
Baseline list at the top of this report, under the A1 table. What each candidate is expected to reach, not measured together: `valuation_daily.pe` 22 and `pat_growth_yoy_pct` 7 by comparatives; transcript text 52 (21 KEC) by the speech work, with MARUTI's 19 left, needing a browser fetch; sector KPIs by the KPI work, whose unmet list with reasons is in that worker's result. `ratio_panel.roe`, `roce`, `dividend_payout_pct` need balance-sheet or dividend inputs. `guidance.guidance` 22 can never be met by a real row: wrapper's call on the scorer, see loop 2's report. SBILIFE and SUNPHARMA `pe` before the first held filing: on such a date the answer is "no filing held before <date>", not missing data.

Not done from the brief: 20 comparatives rows hand-checked against the page image (I read 22 rows against their quotes, which come from the page's words); A1 before and after on a combined build; the questions held back for older quarters.

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
All on DeepSeek, off-peak; the first two started 18:17 IST.
| Name | Job | Branch | Brief | Status |
|---|---|---|---|---|
| comparatives | 20261104T124718Z-f826eabb | `dsh/20261104T124718Z-f826eabb` | `loop_03_worker_comparatives.md` | running |
| kpi | 20261104T124734Z-2e947e47 | `dsh/20261104T124734Z-2e947e47` | `loop_03_worker_kpi.md` (cherry-picks 2690518) | **NOT ACCEPTED, do not merge alone**; fix round queued (`loop_03_worker_kpi_fix.md`) |
| speech | 20261104T133227Z-c8ca921f | `dsh/20261104T133227Z-c8ca921f` | `loop_03_worker_speech.md` | **NOT ACCEPTED, do not merge alone**; fix round queued (`loop_03_worker_speech_fix.md`) |

| kpi fix | 20261104T134520Z-2ba2330d | `dsh/20261104T134520Z-2ba2330d` (on the kpi branch) | `loop_03_worker_kpi_fix.md` | done 20:08 IST, A1 677/898, A3 99.79%, bar not met; next round queued (`loop_03_worker_kpi_fix2.md`) |
| speech fix | 20261104T143838Z-20a19ffb | `dsh/20261104T143838Z-20a19ffb` (on the speech branch) | `loop_03_worker_speech_fix.md` | running, started 20:08 IST |
| comparatives (first) | 20261104T124718Z-f826eabb | `dsh/20261104T124718Z-f826eabb` | `loop_03_worker_comparatives.md` | **NOT ACCEPTED, do not merge alone** |
| comparatives fix | 20261104T140210Z-42e59ee9 | `dsh/20261104T140210Z-42e59ee9` (on the comparatives branch) | `loop_03_worker_comparatives_fix.md` | running, started 19:32 IST |

### Review of the KPI fix round (20:10 IST)
Lost metrics are back, and the worker's report is honest: it says the 18/20 bar is not met (auto 13/20, bank 8-11, consumer internet about 10, EPC about 12; metals, IT, insurance, pharma not read). My read of 67 new rows of five companies: about 50 right. So about 75%, up from the 45-70% of the first round, and not good enough to merge as answers. Round 2 of fixes is general: outlier gate, no default period on long documents, label must own its value, subject words, restore true rows.

### Review of the speech worker (19:34 IST)
Its numbers: A1 651 to 662 (KEC 51 to 62, no other company moves on A1, 0 questions regressed), statements ETERNAL 0 to 691, INFY 0 to 2,512, KEC 1,803, guidance 136 rows to 69, A3 31/31. I read all 69 guidance rows: about 8 wrong, against about 58 of 136 before, so this is real progress (quotes cut at 118 characters, so approximate). Speaker tables and 27 sampled statements look right. No analyst or journalist among them.
- **False claim, sent back:** the worker reported `checkpages` 144 as "pre-existing at HEAD" and wrote that into `tasks/STATE.md`. Measured in the same minute: main 145, KPI branch 145, this branch 144. `checkpages.py:241` runs `guidance.run`, which the worker said it did not. The lost page is `HINDALCO045` "$3.2 billion capital expenditures spent through end of FY26": a true fact that family D of my own brief removed. Fix: keep it as a `project_capital_spent` row. Guard A6 would have failed at merge.
- Left for the fix round: 8 wrong rows, a footer in INFY quotes, INFY's whole media call marked `prepared`.

### Review of the comparatives worker (19:18 IST)
Its numbers: A1 651 to 680, 5,587 rows, `pe` days up to 245 on some companies, its 12 cells exact, 20/20 hand check, tests green. The reader is good: I read 22 random checked rows against their quotes, 22 right. The defects are around it, and its checks could not see them:
- **Every printed TTM on a Q2 or Q3 table is wrong.** `_ttm_one` takes `last_fy + current - year_ago` first. HINDALCO 2025-11-07 trailing EPS stored 75.81; right is 72.05 + 39.38 - 31.43 = 80.00. The same on HINDUNILVR, BAJFINANCE, SUNPHARMA. So the large rise in `pe` days carries wrong P/Es until this is fixed.
- **EPS `xbrl_ok` means nothing:** the tolerance is scaled by the table's rupee unit. MARUTI Q1 FY27 consolidated EPS stored **10,953.0**, `xbrl_ok`, repaired; XBRL says 109.63.
- **Non-P&L tables read:** segment reconciliations give negative `finance_cost` and `depreciation`; `Operating Margin (%)` stored as `exceptional_items`; `Current tax` as `tax`.
- **Filings unread and unreported:** MARUTI 2026-01-28 and 2026-04-28 pages are rotated 270 degrees, and its consolidated 2026-10-27 table is missed, which is why its `pe` did not move; ETERNAL 2026-01-21 (noisy date), SUNPHARMA 2026-01-31 consolidated (noisy title).
- **Its "90% checked" miss** was blamed on the XBRL window. Decision: a new `repeat_ok` status, the same value printed by a different filing. This goes beyond the three statuses in the loop brief: wrapper to overrule if it disagrees.
Point-in-time logic reads right: a printed quarter keeps the earliest filing's `known_at`.

### Review of the KPI worker (19:05 IST)
Its numbers: A1 651 to 676, A3 99.85%, tests and checkpages green. Its own hand read fails its accept: fmcg 20/20, insurance 16, pharma 14, it_services 12, consumer_internet 11, bank 10, auto 9, lenders 9, against a rule of 18/20; the brief said fix before reporting. My read of the rows confirms this and adds a defect the report did not name:
- **The sector gate wiped true rows.** `ebitda` lives in `metals.yaml` and `aum` in `lenders.yaml`, so KEC `ebitda` went 64 to 0, SUNPHARMA 70 to 0, SBILIFE `aum` 49 to 0, `roe_pct` too. A1 did not notice, because dev happens not to need them. Hidden questions may.
- **Wrong rows that raise A1:** a year-ago quarter labelled as a half year (BAJFINANCE `revenue` H1FY26 17,002.86), number fragments (`pat` 791.0), a rupee row with unit pct (`r_and_d_pct` 23,676), cash-flow lines as `net_debt`, old values of a change (`dso` 69, `market_share` 8.1), 278 rows dated before the window.
- It committed `PROGRESS_NOTES.md` and edited `tasks/STATE.md`.
Part of the 25-question A1 gain may rest on these wrong rows, which is what the fix round will show.

## Worker log, for `WORKER_REVIEW_LOG.xlsx`
| Job | Type | Time | Tool calls, first edit | Verdict | Improve next time |
|---|---|---|---|---|---|
| f826eabb comparatives | new extractor | 58 min | 127, 20 | Reader good; TTM, EPS check, table filter wrong | Accept should have recomputed one TTM by hand and read back a wrong-tolerance case |
| 2e947e47 KPI | finish unreviewed branch | 45 min | 130, 62 | Own hand read failed, reported anyway | Evidence should show the rows' look; stop rule on the bar |
| c8ca921f speech | fix + extraction rules | 30 min | 130, 14 | Good; one false claim about checkpages | Brief's family D cost a true fact: my error |
| 2ba2330d KPI fix | fix | 53 min | 108 by its count, 221 by the supervisor, 11 | Honest; bar not met, budget ran out before the read | Polling used 37 calls; foreground builds |
| 42e59ee9 comparatives fix | fix | running | | | |
| 20a19ffb speech fix | fix | running | | | |
This session: Opus manager, reached 400k context at about 70 tool calls, mostly long briefs, row dumps and worker reports. Row dumps were the avoidable part.
