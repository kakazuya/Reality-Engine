# Worker: KPI precision round 3

Goal: on branch `dsh/20261104T155309Z-1c188316`, new KPI rows reach at least 18 of 20 right in every company, by general rules, without losing true rows. Precision outranks A1.

Ticket: T-061

Evidence: round 2's hand read of new rows (seed 20261107/20261109): KEC 16, BAJFINANCE 14, HINDALCO 15, HDFCBANK 14, SBILIFE 17, INFY 19, SUNPHARMA 20, MARUTI 15, HINDUNILVR 18, ETERNAL 15, of 20. Wrong rows by family:
- **Period:** KEC D/E H1FY27 0.90 read from the older column. BAJFINANCE two different H1FY26 revenues from 4- and 5-value rows. HDFCBANK GNPA 1.15 and 2.44 dated March 2026 stored as FY25 and Q4FY25. MARUTI monthly export sales 31,304, 49,872 and 33,844 given FY or quarter defaults. ETERNAL -3.0% and -4.7% both Q3FY26. INFY `cc_growth` Q2FY27 21.0 and Q3FY25 57 from the fact-sheet block. HINDUNILVR Q1FY27 value growth 10% beside 5% from one page.
- **Subject:** BAJFINANCE AUM 2,198 crore is a subsidiary's; new_loans 1.1 is "loan offers"; customer_franchise "addition 46" twice. HINDALCO segment EBITDA 37,217 stored as total; "utilisation of 70% of approved thresholds" twice. SBILIFE APE 24.7 is profit after tax; `vnb_margin` 13.6 is `Margin / 27.5% / Networth / 13.6%`. ETERNAL -1.4% "as a % of Revenue" under a GOV metric. MARUTI 50,000 cumulative EV exports stored as quarter exports. HDFCBANK `advances` 13,854.09, 14,645.26, 14,724.64 from the Fixed-assets side table (two tables on one vertical band).
- **Unit:** KEC capex "17.15 lakh" stored as 17.15 crore. BAJFINANCE "Lacs". SBILIFE `vnb` 66.7 stored `inr_cr` against the deck's bn; NBP 535.8 mn beside 425.5 bn. HINDUNILVR direct_reach "2 lakh" stored as 2.
- **Forward, threshold or change:** KEC "doing another INR2,000", "new orders of over INR1,000". HINDALCO planned 60 KT capacity; "reduction of 145 KT" stored as shipments. HDFCBANK "gross NPAs is 5 per cent". ETERNAL "close to 6%", "next 6" dark stores.
- **True rows lost or missing:** MARUTI `export_volumes` Q2FY27 108,119 (deck 2026-10-27 p16 `Exports 108,119 -2.1% 15.5% 232,855 12.2% 16.9%`). HDFCBANK `cd_ratio` 0 rows, `deposits` 1 row. Lost from round 1: BAJFINANCE-083, 099; HINDALCO-087, 091, 092; HINDUNILVR-105; INFY-092, 099, 108, 112; KEC-088; SBILIFE-080.
- **Outlier gate:** factor 500 keeps KEC's true 6,722 crore net debt but passes BAJFINANCE `nnpa_pct` 77; non-positive values skip it (HINDALCO `ebitda_adjusted_usd` -150, 53).
- **Code:** `reality_engine/pilot3/kpi.py`: `_review_outliers`, `_label_owns_value`, `_quote_names_label`, `drop_reason`, `_table_value_ok`, `sentence_rows`, `table_and_chart_rows`, `value_unit`. Use `outline`: the file is about 2,000 lines, so do not read it whole.

Rules: general wording only; do not tune to a seed or name a company in code. Do not touch `results_lines.yaml`, `topics.yaml` or `tasks/`.

Data: fresh copy `D:\RealityEngine\pilot10\scratch\w_kpi6.db` from `D:\RealityEngine\pilot10\scratch\combined2.db` by sqlite3 `backup`, which has the real KEC and MARUTI transcripts. Check free RAM first; wait above 2.5 GB. Fast check, foreground, one company at a time: `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part kpi --symbols X --out D:\RealityEngine\pilot10\scratch\w_kpi6.db`.

Accept:
1. Hand read of 20 random new rows per company with a fresh seed (20261111), against each row's quote, at least 18 of 20 each, printed first in the report. A failing company is reported as failing.
2. A1 per company on the dev set is no lower than `D:\RealityEngine\pilot10\scores1_combined2.json`: BAJFINANCE 77, ETERNAL 66, HDFCBANK 74, HINDALCO 76, HINDUNILVR 74, INFY 66, KEC 66, MARUTI 75, SBILIFE 67, SUNPHARMA 66. Do not change the grader.
3. `python -m pytest reality_engine/tests/test_pilot3_kpi.py -q`, new tests from the rows above, and `python -m reality_engine.pilot3.checkpages run` still at 145.

Files: `reality_engine/pilot3/kpi.py`, `reality_engine/pilot3/lexicon/*.yaml`, `reality_engine/tests/test_pilot3_kpi.py`, your paragraphs in `docs/PILOT3_BLUEPRINT.md` and guide O2 in `docs/DEVELOPER_GUIDE.md`.

Do not run `guards`: the wrapper runs them on a checkpointed copy.

Stop if: free RAM stays under 2.5 GB for 10 minutes, or the same companies still fail after two rule rounds. Report the rows either way.

Budget: 120 tool calls. End with rows per company, the hand read, A1 per company and a `Docs updated:` line.
