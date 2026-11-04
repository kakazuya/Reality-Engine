# Loop 3 worker: comparatives fix round: wrong TTM, false EPS checks, wrong tables, unread filings

Goal: on top of branch `dsh/20261104T124718Z-f826eabb` (A1 680/898, not accepted as is), trailing values are computed by the right formula, `xbrl_ok` is true only when the value truly equals XBRL, no row comes from a segment, ratio or reconciliation table, the rotated and noisy filings are read, and checked coverage rises by a cross-filing check. A1 may fall from 680 where a wrong value goes: state it.

Ticket: T-057

Evidence (controller's audit of `D:\RealityEngine\pilot10\scratch\w_cmp.db`; line numbers are in that branch's `reality_engine/pilot3/comparatives.py`). The reader itself is good: 22 of 22 random checked rows matched their row and column by my reading, and your 12 cells stand. These are the defects:

1. **Every printed TTM on a Q2 or Q3 table is wrong.** `_ttm_one` (line 1047-1051) tests the Q1 branch first, so a Q2/Q3 table, which has `last_fy`, `current` and `year_ago` too, gives `last_fy + current - year_ago`. Measured:
   | Company, date | stored trailing_eps | = wrong formula | right, last_fy + ytd - prior_ytd |
   |---|---|---|---|
   | HINDALCO 2025-11-07 | 75.81 | 72.05 + 21.35 - 17.59 | 72.05 + 39.38 - 31.43 = 80.00 |
   | HINDUNILVR 2026-02-12 | 41.53 | 45.36 + 9.03 - 12.86 | 45.36 + 32.49 - 34.77 = 43.08 |
   | BAJFINANCE 2025-11-10 | 28.27 | 26.89 + 7.85 - 6.47 | 26.89 + 15.41 - 12.79 = 29.51 |
   | SUNPHARMA 2025-11-06 | 45.90 | 45.6 + 13.0 - 12.7 | 45.6 + 22.5 - 24.5 = 43.60 |
   Fix: decide by what the table is. A table with a `ytd` (period_type ytd) uses `last_fy + ytd - prior_ytd`, and only if both are present; Q1 only when the table has no `ytd` at all. Never fall through to the other formula when a cell is missing or unchecked. Add a test per quarter layout with these four cases' numbers.
2. **EPS `xbrl_ok` is false: the tolerance is in rupees of the table's scale.** `tol = 2.0 / 10**decimals * scale` (line 742) reaches `_xbrl_ok` (line 782, 836) for EPS too, so with scale 1e6 any EPS within 2,000,000 passes. Proof: MARUTI 2026-07-31 consolidated `current` `eps_basic` = **10,953.0**, `xbrl_ok`, `repaired`, raw `t0953`, quote `Basic (lNR) t0953 l r6.38 t20.62 466.90`; XBRL says 109.63. So that repair went through on a false check and stored a wrong value. Same tolerance goes to `_check_column`. Fix: EPS and any `inr_per_share` item use tolerance 2 units of its own printed decimals (about 0.02), never scaled. Recount statuses after this: every EPS `xbrl_ok` is suspect today.
3. **Rows from tables that are not the P&L.** `read_page` (line 415) and `_continuation` (line 652) accept them:
   - Segment reconciliation: HINDALCO 2025-11-07 p16 `Depreciation and amortisation expense - (2,155) (2,080) (1,932) (4,235) (3,824) (7,881)`, 2026-02-12 p14 likewise: stored `depreciation` -19,320,000,000 and so on; negative `finance_cost` 35 rows, `depreciation` 17 rows, of which 6 are `sum_ok`. A cost line is never negative in the P&L.
   - HINDUNILVR 2026-07-28 p7, a continuation after the Q1 table: `(75) (122) Finance costs (76) (410)` gives `finance_cost` FY26 -760,000,000 with role `ytd`, and `(75) (125) Exceptional items [net (charge) / credit] 247 (235)`. Its columns are not those of p6: a Q1 filing has no `ytd`.
   - Ratio page: KEC 2026-08-10 p7 `Operating Margin excluding exceptional item (%) 5.79 7.01 6.97 7.06` stored as `exceptional_items` 69,700,000. A label with `%` or `margin` never maps to a rupee line.
   - Component as total: HINDALCO 2026-02-12 `Current tax expense (refer note 3) 1,617 ...` stored as `tax` 16,170,000,000 (XBRL `tax` 7,800,000,000). Where only components print, either store no `tax` or a derived sum of current and deferred with `is_reported` 0.
   Fix: the page must carry a P&L shape (a revenue or income line and a profit line, or a continuation with the previous page's x-bins, column count and a matching period in the same statement). A page whose first table heading says segment, or `Less:` lines before a profit line, is skipped. A cost line (`finance_cost`, `depreciation`, `employee_cost`, `total_expenses`, `other_expenses`, `cost_of_materials`) printed in brackets in a table means the table is not the P&L, except a page where every cost prints in brackets by convention and the identity still holds.
4. **Filings not read, and not reported** (your Accept 4 asked for it). `doc` rows with 0 rows stored, per `doc_key` suffix:
   - MARUTI 2026-01-28 and 2026-04-28: **pages are rotated** (`page.rotation` 270 on pages 2-10 and 2-15), so y-sorted words are garbage (`6 5 4 3 2 I`, `: the The are The The b) a) the On in December`). Use the page's `rotation_matrix` on word boxes before sorting, in `rows_from_words`'s caller. Same on INFY 2026-01-14 (pages 8-19, 43, 44 rotated, some empty: those need OCR, list them).
   - MARUTI 2026-10-27 consolidated: `Notes to the Statement of Consolidated...` is p9, so the table is about p7 or p8, and nothing was stored. MARUTI's valuation reads consolidated, so this is why its `pe` days did not move. Find why it was refused.
   - ETERNAL 2026-01-21 p13: clean rows, header `Detember31, September 30, December 31, December 31, December 31, March 31,` and title `Dctember 31, 2025`. `_period_end` (line 841) found no date. Add a last fallback: the latest quarter end at most 60 days before `known_at`, kept only if the XBRL or the arithmetic agrees; log that it was used.
   - SUNPHARMA 2026-01-31 p11, consolidated, title `Statement of Unaudited ca"nsolidated Financial Results`: fuzzy basis match in `_page_basis` (line 485). `31 .1 2.2025` in the header also needs joining.
   - ETERNAL 2026-04-28 consolidated: 10 rows only; INFY 2026-01-14: no rows: say which page holds the crore table and why it was skipped.
   Report every results filing per company with rows per basis, or the reason for none. Scanned filings (HDFCBANK 2026-04-18, 2026-07-18) are listed once with their empty pages.
5. **Identity failures drop true values.** BAJFINANCE 2025-11-10 p4, `total_income` `14,491.79` in the review file with `total_income=144917900000.0 not 129397...`: the identity took the wrong row as `revenue_from_operations` (a component like interest income), and the true total was deleted. 169 cells are in the review file, BAJFINANCE 40, HINDALCO 33, HINDUNILVR 24. Fix `_choose_rows` to prefer a `Total ...` row for totals, and in `_check_column` when an identity fails with more than one possible input row, do not delete. Give counts per company after.
6. **Cross-filing check (new status, controller's decision).** 2,136 of 5,587 rows are `unchecked` today, largely because XBRL covers only 4 quarters. New `check_status='repeat_ok'`: the same symbol, basis, period_end, period_type and line_item printed by a **different filing** (different date) with the same value within tolerance. Two independent readings of two PDFs agree. Ratios, `ttm_filings`, `printed_quarters`, `_printed_year_ago`, `_printed_fy` and `lookups_pilot3.fin` accept `repeat_ok`. Keep each row's own `known_at`: a row's filing date stays what a past date may see, even though its agreement came from a later filing. KEC's FY25 EPS 21.8 (`unchecked` in 2025-11-10 and 2026-01-30, printed again 2026-05-16) is the test case: KEC `pe` must then start at its first filing with the formula of item 1 (today it starts 2026-05-18). INFY `year_ago` and `prior_ytd` have only one filing each: they stay unchecked; EPS can pass by `eps ~ pat / shares` if the share count is held: check `_shares` (line 575) finds one, since INFY reports none today.
7. **Hygiene.** Remove `PROGRESS_NOTES.md` from the branch and restore `tasks/STATE.md` to main's. The wrapper writes STATE.

Checks: work copy `D:\RealityEngine\pilot10\scratch\w_cmp2.db` from `D:\RealityEngine\pilot10\scratch\l3_base.db` by sqlite3 `backup`. `--part comparatives --symbols X` about 15-30 s a company; `--part ratios` about 4 s; A1 about 8 s, as in your first brief (`loops/loop_03_worker_comparatives.md`, whose decisions, Gotchas and do-not-touch list all stand). `reality_engine/night_eval/` may not change. The controller's audit scripts, which print what is listed above: `D:\RealityEngine\pilot10\scratch\l3\cmp_rev.py`, `cmp_rev2.py`, `cmp_rev3.py`, reading `w_cmp.db`: copy them to your scratch and repoint. Scratch folder `D:\RealityEngine\pilot10\scratch\cmp2\`.

Files: as in the first brief, on your branch. Do not touch: `kpi.py` and its lexicons, `guidance.py`, `transcripts.py`, `stores.py`, `xbrl_segments.py`, `reality_engine/night_eval/`, `tasks/`, any question file. Docs: update your blueprint 9b and O10 text to the fixed behaviour, with `repeat_ok`.

Accept:
1. The four rows in the table of item 1 read the right value; print each with `input_refs`. Add MARUTI, INFY, KEC, HDFCBANK, SBILIFE, ETERNAL first-`pe` day with the computed sum written out, and hand-check it against the row values.
2. `SELECT count(*)` of `eps_basic` or `eps_diluted` rows with `xbrl_ok` where abs(value - XBRL) > 0.03: 0. MARUTI's 10,953 row gone or 109.63.
3. Each row named in item 3: print what is there now. Rows with a negative cost line: 0 unless explained one by one.
4. Per filing table from item 4. MARUTI at least 4 quarters more than today; ETERNAL's and SUNPHARMA's named tables read.
5. Status counts per company before and after; share of quarter rows checked per company (target 90% for 8 of 10; say why each that falls short does).
6. Fresh hand read at seed 20261105, 30 rows, weighted to rows new in this round; every wrong row with cause. At least 29 right.
7. A1 per company against baseline 651/898 (BAJFINANCE 71, ETERNAL 65, HDFCBANK 71, HINDALCO 69, HINDUNILVR 71, INFY 65, KEC 51, MARUTI 59, SBILIFE 67, SUNPHARMA 62): no company below it; list needs met in `w_cmp.db` that are unmet now, with why. `pe` days per company.
8. PIT: no ratio or valuation row uses an input with a later `known_at`. No row in `ratio_panel` uses `unchecked`.
9. `test_pilot3_comparatives.py`, `test_pilot3_ratios.py`, `test_pilot3_profile.py`, `test_pilot3_core.py -m "not slow"`, plugin `test_lookups_pilot3.py`: one process each, pass. `checkpages run` >= 145 with the same split. Guards as before.

Stop if: a change is needed outside the named files; a label would need a company name; free RAM under 2.5 GB (pause).

Budget: first edit within 8 tool calls; 130 total; 2 hours; no paid calls, no network, no model call in the build.

Out of scope: OCR, older documents, a wider `fin_quarter_xbrl` window, the A1 scorer.

Report as in `tasks/worker_context/BRIEF_TEMPLATE.md`, with a `Docs updated:` line.
