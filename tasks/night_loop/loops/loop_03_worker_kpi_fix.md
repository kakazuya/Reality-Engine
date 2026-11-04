# Loop 3 worker: KPI fix round: restore lost metrics, and bring every sector family to 18 of 20 right

Goal: on top of branch `dsh/20261104T124734Z-2e947e47` (A1 676/898, controller's verdict: not accepted), company EBITDA and the other metrics the sector gate wiped are back, the wrong-row families below are gone, and a fresh hand read gives at least 18 of 20 right in every family with new rows. Precision outranks A1 here: A1 may fall from 676 when wrong rows go, but it must stay above the 651 baseline with no company below its baseline, and each true need lost must be named.

Ticket: T-056

Evidence (controller, by querying `D:\RealityEngine\pilot10\scratch\w_kpi3.db` against `D:\RealityEngine\pilot10\scratch\l3_base.db`):

1. **The sector gate deleted true rows.** `sectors:` on `metals.yaml` and `lenders.yaml` also gates entries that are universal. Metric gone entirely, rows in base -> 0: KEC `ebitda` 64 (`EBITDA / 430 / 374 / 15% / 1,211 / 989`), SUNPHARMA `ebitda` 70 (`EBITDA / 44,177`), MARUTI `ebitda` 16, HINDUNILVR `ebitda` 5; INFY `ebitda_margin_pct` 44, SBILIFE 35, MARUTI 16, HDFCBANK 16 (the last two you judge); SBILIFE `aum` 49 (`assets under management stands at INR5.2`) ; `roe_pct` SUNPHARMA 25, SBILIFE 14, HINDUNILVR 8, INFY 5 and others. Your A1 check did not catch it, because the questions in dev happen not to need those rows; hidden questions may. Wanted: `ebitda` (metals.yaml:10) and `roe_pct` move to `common.yaml`; `aum` goes also in `insurance_life.yaml`; `metals.yaml:12` `ebitda_margin_pct` has the bare label `margin`, which stays metals-only and common keeps its anchored entry; `utilisation`, `capacity`: keep under sectors that print them (metals, auto_oem, it_services). Truly sector-wrong removals stay removed: `deposits`, `crar_pct`, `nim_pct`, `nnpa_pct`, `cost_of_production` outside their sectors. After the fix, list every (symbol, metric) still at 0 with a reason.
2. **`table_v1` (622 new rows) reads a text stream with no period check.** Rows and causes:
   - Column read as the wrong period: BAJFINANCE `revenue` H1FY26 17,002.86 and `revenue` H1FY25 14,987.02 (`Total revenue from operations / 20,890.66 / 19,802.43 / 17,002.86`: third column is the year-ago QUARTER, labelled half-year), SUNPHARMA `domestic_formulations` FY25 169,230.0 (`48,358.9 / 49,985.8 / 42,129.6 / 192,903.6 / 169,230.0`: fifth column of a Q3 table is prior nine months), MARUTI `export_volumes` H1FY27 (deck column read one off), SBILIFE `vnb` 9MFY25 42.9 `inr_cr` (the unit is bn).
   - Fragments of a number: BAJFINANCE `pat` H1FY25 791.0 from `... 9,574.97 / 7,791...`. HDFCBANK `gnpa_pct` H1FY27 37.0 from a list `(c) % of Gross NPAs to Gross Advances / 1.11% / 1.17% ...`; `gnpa_pct` 11,447 and `roa_pct` 507,536 (your own report).
   - Impossible values: SUNPHARMA `r_and_d_pct` FY23 23,676 with unit pct (the row is rupees, label `R&D expenditure`), KEC `working_capital_days` 0.19 from `Long term debt to working capital Ratio`, MARUTI `domestic_volumes` -9, -20, +118.4 (the delta column of a table), SBILIFE `banca_share` 63 from `62/27/11 / 63`.
   - Wrong metric: BAJFINANCE `net_debt` 15,832.25 (`Net cash generated from financing activities (C)`), 94.441 (`investing activities`).
   Wanted, in `kpi.py`, for **all** table rows under a profile (no profile: pilot3 unchanged, `checkpages` proves it):
   a. Period only from the column's own header. A row with a count of values different from the header's period columns is dropped, not mapped by position (`st["column_mismatch"]`). On a results table, column meaning follows the rule in `reality_engine/pilot3/comparatives.py` when that merges; in this round, a results table with more than one quarter column may give only its first (current) column, and year-to-date only from a column whose own header says half year or nine months.
   b. A value must be a whole printed token: its characters bounded by the column's separators in the row (`791.0` out of `7,791.xx` is refused).
   c. `kind: pct` above 100 is refused unless the entry says otherwise; a signed token (`+118.4`, `-9`) or a token in a column headed change, growth, `%`, `YoY`, `QoQ` is not a `count` or `money` level; a `days` value below 1 is refused.
   d. `net_debt` `neg` adds `cash (generated|used|flow)|financing|investing|operating activities`; `working_capital_days` `neg` adds `ratio|to working capital`.
   e. `r_and_d_pct` needs `%` in the label or token.
   f. Pages whose text says `in crore` in the header but value parses as bn or lakh keep the table's unit (`vnb` above: read `page_money_unit`, the deck says ₹ bn).
3. **`sentence_default_v1` (478 new rows) and `sentence_v1` (191).** Wrong rows:
   - INFY `deal_tcv` FY26 50 usd_mn from `Our $50 mn plus clients increased`; INFY `cc_growth` Q3FY25 57 from `Large Deal TCV / (57`, `cc_growth` Q4FY26 20.3 from `CC Growth# / 20.3% FY Reported`, `cc_growth` FY14 21.1 from `CC Growth# / 21.1% / Operating / Margin / 14`: a fact-sheet block with labels detached from values; refuse a sentence row whose label and value are on different lines with another label between.
   - The old value of a change: INFY `dso` 69 (`was 67 days ... compared to 69 days`) under the current period, `dso` Q4FY25 67 (`as of March 31, 2026 and March 31, 2025 was 67 days`), SUNPHARMA `market_share` Q4FY26 8.1 (`increased from 8.1% to 8.4%`): in `from X to Y` the current value is Y, in `X compared to Y` it is X.
   - A change read as the level: ETERNAL `cash_balance` 316 (`increased by INR 316 crore QoQ to INR 18,288 crore`: wanted 18,288). A `by N` number is not the level.
   - Another subject: HINDALCO `ebitda_adjusted_usd` 104 (`impacted by an estimated negative $104 million`), SUNPHARMA `api_revenue` 520 bn from a mix chart list `API & Others / 4% / ...`, `api_revenue` chart rows 4, 5, 146, 582 with unit `inr_cr` while the quote says `bn`: unit wrong, and for 4, 5 the number is a percentage.
   - Period from the deck default where the sentence says another period: SBILIFE `gwp` FY26 1,012.9 `inr_cr` from an annual-report chart (`₹1,012.9 / 15% / CAGR`): check it.
4. **Periods too old.** 278 new rows carry periods ending before the window (FY23, FY24, FY25, 9MFY25, Q3FY25, Q4FY25): decks print history. Under a profile keep a row only if its period ends on or after `window_start` minus one year (a YoY base), for new sector families as well as existing ones, except a row whose metric is needed by the dev question set at that exact period (there are none expected: if you find any, list them).
5. **Branch hygiene.** The branch committed `PROGRESS_NOTES.md` and edited `tasks/STATE.md`: remove both from the branch's diff (`git rm --cached PROGRESS_NOTES.md`; restore STATE.md to the base). The wrapper writes `tasks/STATE.md`.

Where: `reality_engine/pilot3/kpi.py`: `value_unit` line 273, `find_values` 322, `sentence_rows` 615, `table_and_chart_rows` 1052 (these line numbers are main's; add the branch's shift); `keep_period` 161. `lexicon/metals.yaml:10-12`, `lexicon/lenders.yaml:6`, `lexicon/common.yaml`.

Data: read `w_kpi3.db` as your before-state; write copy `D:\RealityEngine\pilot10\scratch\w_kpi4.db` from `l3_base.db` by sqlite3 `backup`. Scratch `D:\RealityEngine\pilot10\scratch\kpi4\`. Your earlier scripts in `scratch\kpi3\` (`sample.py`, `why.py`) are there to reuse.

Checks: `build --profile tasks/night_loop/pilot10_profile.json --part kpi --symbols <SYM> --out <copy>`, one company at a time, 191 s for all ten. `pytest reality_engine/tests/test_pilot3_kpi.py -q` (45 pass today). `python -m reality_engine.pilot3.checkpages run` about 6 s (145: KEC 29, BAJFINANCE 59, HINDALCO 57), must not move. `python -m reality_engine.night_eval.answerable --db <copy> --qset <main checkout>\tasks\night_loop\questions\dev.jsonl --out D:\RealityEngine\pilot10\scratch\w_kpi4_a1.json` about 8 s.

Gotchas: env `PYTHONPATH=<your worktree>`, `REALITY_DATA_ROOT=C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data`, `PYTHONIOENCODING=utf-8`. Hand read means reading the row's quote against the page, with a seed you print before you see any row; do not adjust labels and then re-read the same seed. No company names in code or lexicons. Never read `D:\RealityEngine\pilot10\eval_hidden\` or `D:\RealityEngine\pilot3\answer_run*`. Other workers own `ratios.py`, `build.py`, `schema.py`, `comparatives.py`, `guidance.py`, `transcripts.py`, `lexicon/results_lines.yaml`, `lexicon/topics.yaml`.

Files:
- Change: `reality_engine/pilot3/kpi.py`, `reality_engine/pilot3/lexicon/*.yaml` except the two named above, `reality_engine/tests/test_pilot3_kpi.py` (new tests only: each rule 2a-2f and each sentence defect in 3).
- Docs: your paragraphs in `docs/PILOT3_BLUEPRINT.md` and `docs/DEVELOPER_GUIDE.md` O2: state the rules and the new numbers.
- Do not touch: everything else, including `tasks/`.

Accept:
1. All ten built, rc 0, seconds per company.
2. Every (symbol, metric) from Evidence 1 is back, or listed with a reason. KEC `ebitda` Q2FY27 present, with quote.
3. Each row named in Evidence 2 and 3: print what is there now (right value, or none).
4. Fresh hand read at seed 20261105, 20 random new rows (new against `l3_base.db`) per family: at least 18/20 in every family with 20 or more rows; every wrong row with its cause. Under 18: fix once more, new seed.
5. The value read-backs of `loop_02_worker_kpi.md` Accept 2 still hold, except MARUTI `export_volumes`, which you report again.
6. A1 per company: above baseline 651/898 in total, none under its baseline (BAJFINANCE 71, ETERNAL 65, HDFCBANK 71, HINDALCO 69, HINDUNILVR 71, INFY 65, KEC 51, MARUTI 59, SBILIFE 67, SUNPHARMA 62). Each need met on `w_kpi3.db` but unmet now: list with a reason (row was wrong, or true row lost).
7. `python -m reality_engine.night_eval.guards --db <copy> --base-db D:\RealityEngine\pilot10\scratch\l3_base.db --base main --branch HEAD --parts '' --a6 ok --out D:\RealityEngine\pilot10\scratch\w_kpi4_guards.json`: A3 >= 98%, `xbrl_disagreements` not above base 335, A5 pass.
8. `pytest test_pilot3_kpi.py`, `test_pilot3_core.py -m "not slow"`, `checkpages run` as above. `git diff <base> --stat` shows no `PROGRESS_NOTES.md`, no `tasks/`.

Stop if: a label would need a company name; pilot3's checkpages moves and you cannot find why; free RAM under 2.5 GB (pause).

Budget: first edit within 10 tool calls (the rows above are the evidence); 120 total; 2 hours; no paid calls, no network, no model call in the build.

Out of scope: a new reader for label-after-values tables (report remaining pages); OCR; guidance; comparatives.

Report as in `tasks/worker_context/BRIEF_TEMPLATE.md`, with a `Docs updated:` line.
