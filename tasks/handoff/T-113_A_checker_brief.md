# T-113 A: harden the independent row check layer (checker worker)

Ticket: T-113

Goal: make `reality_engine/pilot3/row_checks.py` a tested, universe-ready check layer for `guidance` and
`kpi_series` rows. It must never let a wrong row be `verified`, and must quarantine only rows that are wrong.
You are the checker's author, NOT the extractor's: never edit `kpi.py`, `guidance.py`, `lexicon/`, or any extractor.
Do not reuse extractor functions or word lists (standing rule, `tasks/RULINGS.md`: the checker must not share the
extractor's mistakes). Read `docs/DB_BUILD_GUIDELINES.md` section 13 first, then all of `row_checks.py` and
`row_checks_vocab.yaml` (Opus's prototype, commit b07c30a).

Files (only these): `reality_engine/pilot3/row_checks.py`, `reality_engine/pilot3/row_checks_vocab.yaml`,
new `reality_engine/tests/test_row_checks.py`, `docs/DB_BUILD_GUIDELINES.md` section 13 (update numbers and checks).

Evidence (dev databases, read-only; never write to them):
- `D:/RealityEngine/pilot10/scratch/t113_p10_v2.db`: pilot10 with guidance v2 rebuilt (106 guidance rows incl. the 6
  known-wrong rows: HDFCBANK aum_growth 12-13 'system growth', 9-9.5 'nominal GDP', 12 'that is why we grew at 12%';
  SBILIFE aum_growth 14 'agency + banca' and 14-15 'guided for a growth'; SBILIFE opex_to_nti None) and 6,043 kpi rows.
  Profile: `tasks/night_loop/pilot10_profile.json`.
- `D:/RealityEngine/pilot10/scratch/t105_agy.db` (guidance only): Gemini's rejected rows. Known wrong (must NOT be
  verified; should be quarantined): "Return on assets ... 4.4%-4.6%" and "ROE metric ... 19%-20%" stored as
  credit_cost; "non-interest income to grow by 16-18%" as aum_growth; "COF is expected ..." 7.55-7.65 as leverage;
  "120 million franchise" as new_customers; "Onsite mix ... 1%" as revenue_growth; ETERNAL ebitda_margin with no number.
- Current run (`python -m reality_engine.pilot3.row_checks --db <db> --out .tmp/rc.db --profile tasks/night_loop/pilot10_profile.json`,
  4 s): guidance 46 verified / 26 unverified / 34 quarantined; kpi 4,249 / 1,422 / 372.
- Opus read of 60 random verified kpi rows (seed 81108, before the list/delta/independence checks): 5 wrong, 4
  partly. Still verified today and wrong: row 45653 INFY revenue_usd 'total' Q1FY27 246 = "Revenue from products and
  platforms 246" (a part stored as the total). Partly: 41782 / 41732 dimension names one subsidiary, entity another;
  46024 "3 to 4 days" stored as 4.
- Known false quarantines to fix: MARUTI dealer_inventory_days Q1FY27 13 "dealer inventory closing of around 13 days"
  (list_order fires on volumes / dealer_inventory_days); KEC order_intake 'protection' FY26 1,550 "order intake during
  the year stood at over 1,550 Crore" (list_order revenue / order_intake); BAJFINANCE credit_cost_bps bhfl Q2FY26 18
  "credit cost of 0.18%" (bps row should match 0.18% first; it matches a later number).

Steps:
1. Tests first (`test_row_checks.py`): build tiny sqlite fixtures in `tmp_path` (tables doc, doc_page, guidance,
   kpi_series, company; copy the column lists from the dev db) holding the quoted sentences above verbatim, one test
   per case: each known-wrong row is quarantined, each known-right row listed below is verified or unverified, never
   quarantined. Known right: INFY "Our operating margin guidance for financial year '27 is 20% to 22%." (verified);
   BAJFINANCE "The Company expects to disburse 60-62 MM new loans in FY27." (verified); BAJFINANCE "I would say probably
   between 26%, 27% growth we should deliver now on a full year basis." as aum_growth (unverified, not quarantined:
   a lender's unqualified growth); "Gross NPA and Net NPA as of 31 March 2026 stood at 1.27% and 0.52% respectively,
   as against 1.18% and 0.56% as of 31 March 2025" -> gnpa 1.27 / 1.18 and nnpa 0.52 / 0.56 pass, nnpa 1.18 fails
   list_order. Unit tests for `numbers_in` ("20%-22%" gives 20 and 22, not -22; "Rs.33,688 million"; "1,40,647.0";
   "(12.3)"), `period_end`, `_DELTA`, `_DENOM`.
2. Fix the three false quarantines above with general rules (no company or metric literals in code).
3. New hard checks, each with a test and a measured count on the dev db:
   a. `part_not_total`: an amount row with dimension 'total' whose value is under 15% of the same company's filed
      revenue for that period (fin_quarter_current / fin_annual_line, any basis; same currency only) for metrics in
      the revenue / pat / ebitda / order families. Revenue-in-USD rows: compare to the company's other revenue_usd rows
      of the same period (a part is far below the median).
   b. `period_word`: the quote names a different period than the row: '9m' / 'nine months' / 'ytd' / 'h1' / 'half
      year' / 'q1'-'q4' + fiscal year in the number's sentence against the row's fiscal_period and period_type.
   c. `variant_word`: a pat / ebitda / revenue row whose label in the quote carries 'before exceptional', 'before
      one-time', 'adjusted', 'excluding', 'per ' (per franchise, per share, per tonne) -> soft `variant` unless the
      metric name says so (adjusted_*, *_per_*); measure how many.
   d. `entity_mismatch` (soft): dimension names a subsidiary-like token and entity names another non-symbol entity.
4. Report: `--report <dir>` writes `row_checks_summary.csv` (status counts by metric x sector x doc_type x rule) and
   `--sample N --seed S --status verified` writes a TSV of N random rows (id, symbol, metric, dimension, period,
   value, unit, quote, fails) for a human read. Keep the run under 15 s on the dev db.
5. Run on both dev dbs; put the before/after counts per check and 10 random rows per new check (quote + verdict) in
   your final answer. Do not tune to make numbers look good: a rule that needs a company name is wrong.
6. Update guide section 13 (checks list, counts, commands). Final answer must start with `Docs updated:`.

Accept: `python -m pytest reality_engine/tests/test_row_checks.py -q` passes; the run on the dev db finishes;
none of the Gemini known-wrong rows and none of the 6 v2 rows is `verified`. Opus then scores the checker on a hidden
hold-out of companies you have not seen; your dev numbers are not the score.

Limits and pitfalls:
- Read-only on every database; outputs to `.tmp/` only.
- Tool output on Windows: set `PYTHONIOENCODING=utf-8`; quotes hold the rupee sign and bullets.
- In heredocs a double backslash collapses; write regexes in files with the editor, never through shell heredocs.
- Never `\b` inside a non-raw Python string (it becomes a backspace byte; this already broke the prototype twice).
- Run the test file alone, one process; no full test suite.
- No model calls. No new dependencies.

Budget: 160 tool calls, 3 hours.
Stop if: a needed rule would require a company or segment literal; or you cannot make a known-wrong row fail without
quarantining a known-right one: stop and report the pair with both quotes.
