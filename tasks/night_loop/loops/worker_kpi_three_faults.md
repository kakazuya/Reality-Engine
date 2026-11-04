# Worker: three KPI faults

Goal: on branch `dsh/20261104T164945Z-90879780`, the three largest KPI faults are fixed by general rules, so INFY, HINDALCO and HINDUNILVR each read at least 18 of 20 right and no other company gets worse.

Ticket: T-064

Evidence: round 3's hand read, seed 20261111, gave INFY 5, HINDALCO 12, HINDUNILVR 12 of 20. These three faults are 29 of all 59 wrong rows:
- INFY, 14 rows: segment lines "Revenue 13,463 / 1,419 / 2,858 ..." stored as total company revenue. A table whose columns or headings are business segments must not give a company total. Also "DSO is down 2 days" stored as DSO 2 days.
- HINDALCO, 8 rows: Gross Debt 63,696, 61,932, 63,330, 72,670, 85,639 and Net Debt 34,257, 35,332, 41,415 stored as `net_debt_to_ebitda`, a ratio. Debt-table cells are matched through the `leverage` label: an amount in crore is not a ratio. Round 3 says this is in the table reader, not the lexicon.
- HINDUNILVR, 7 rows: "EBITDA as a % of TO 4%" (4 rows) stored as company margin; it is a segment. ROE 22.4% is FY26 data dated Q4FY26 (3 rows).
- Also seen on the same pattern, fix only if the same rule covers them: ETERNAL restaurant-business margin stored as total; HDFCBANK and ETERNAL subsidiary PAT or revenue stored as the company's.
- Code: `reality_engine/pilot3/kpi.py`: `_assign_columns`, `_kept_columns`, `_quote_owns_value`, `_neg_context`, `table_and_chart_rows`, `sentence_rows`, `value_unit`. Use `outline`: about 2,000 lines, do not read it whole.

Data: `D:\RealityEngine\pilot10\scratch\w_kpi7.db`, copied from `D:\RealityEngine\pilot10\scratch\w_guid2.db` by sqlite3 `backup`. Check free RAM first; wait above 2.5 GB. Fast check, foreground: `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part kpi --symbols INFY --out D:\RealityEngine\pilot10\scratch\w_kpi7.db`. Build the other companies last, once.

Accept:
1. Hand read with fresh seed 20261113, against each quote: INFY, HINDALCO and HINDUNILVR at least 18 of 20, every company printed first in the report. Compare round 3's numbers for the rest: KEC 18, BAJFINANCE 17, HDFCBANK 16, SBILIFE 16, SUNPHARMA 14, MARUTI 15, ETERNAL 16.
2. A1: `python -m reality_engine.night_eval.answerable --db D:\RealityEngine\pilot10\scratch\w_kpi7.db --qset tasks/night_loop/questions/dev.jsonl --out D:\RealityEngine\pilot10\scratch\a1_kpi7.json`, per company, against `D:\RealityEngine\pilot10\scores\a1_combined3.json`: BAJFINANCE 77, ETERNAL 67, HDFCBANK 75, HINDALCO 76, HINDUNILVR 74, INFY 66, KEC 66, MARUTI 75, SBILIFE 67, SUNPHARMA 66. List any company below and the rows behind it. Do not change the grader.
3. `python -m pytest reality_engine/tests/test_pilot3_kpi.py -q`, new tests from these rows. `python -m reality_engine.pilot3.checkpages run`, print its totals: 145 found.

Rules: general wording, no company names in code, not tuned to a seed. Do not run `guards`.

Files: `reality_engine/pilot3/kpi.py`, `reality_engine/pilot3/lexicon/*.yaml` except `results_lines.yaml` and `topics.yaml`, `reality_engine/tests/test_pilot3_kpi.py`, your lines in `docs/PILOT3_BLUEPRINT.md` and guide O2 in `docs/DEVELOPER_GUIDE.md`. Do not touch `tasks/`.

Stop if: free RAM stays under 2.5 GB for 10 minutes, or INFY, HINDALCO and HINDUNILVR stay under 18 of 20 after two rule rounds. Report the rows either way.

Budget: 70 tool calls. End with rows per company, the hand read, A1 per company and a `Docs updated:` line.
