# T-107: a ratio row carries the period it was printed for (quarter, half, nine months, year)

Ticket: T-107

Goal: `kpi_series` ratio rows (roe_pct, roa_pct, nim_pct, credit_cost, cost_to_income, margins ...) are stored under
the period the document prints for that number, and `pilot3_ratio` / `pilot3_kpi` answer "FY26 ROE" with the full-year
figure (BAJFINANCE consolidated FY26 ROE 18.1%), never a quarter's annualised figure (Q4 FY26 20.0%).

Files (only these): `reality_engine/pilot3/kpi.py` (the code that sets `fiscal_period` / `period_type` for a row; find
it with `outline`), `plugins/reality-data/server/lookups_pilot3.py` (`_stated_ratios` ~line 540, only if step 4 needs
it), tests in a new `reality_engine/tests/test_pilot3_kpi_ratio_period.py`, `docs/PILOT3_BLUEPRINT.md` (kpi period
paragraph), `docs/DB_BUILD_GUIDELINES.md` (kpi section).

Evidence (Opus, 8 Nov; live `D:/RealityEngine/pilot10/pilot10.db`, read-only):
- Question BAJFINANCE-027 "What is Bajaj Finance's ROE for FY26, and is it rising or falling on the latest quarter?"
  A model answered 20.0% (graded wrong: "20.0% is Q4, not FY26 ROE"). Right: 18.1% (FY26 consolidated).
- kpi_series rows stored as FY26 / period_type FY that are NOT full-year figures (ids, quote):
  42385/42487/42585/42684 'ROE \n20.0%' and 42386/... 'ROE \n19.7%' (quarter tiles of a deck); 42856 'Annualised ROE\n19.2';
  42961 'Annualised Return on Average Equity \n20.03%\n18.74%\n19.22' (quarter columns; 20.03 is Q4FY26, row 42959);
  42993 standalone same table; 43650 'Annualised Return on Average Equity \n20.4%\n19.0%\n18.1' (check the page header:
  which columns are quarters and which the year); 43048 'Return on equity came in at 20% in the current quarter' is Q
  (correct). 43087/43088 'Return on Average Equity (ROE) of 19.22%' / '18.05%' - read the page: one may be FY, one 9M or
  H1. Also BHFL (subsidiary) ROE 12.1 / 12.01 rows stored with basis not_stated and no entity: out of scope here
  (T-106), but do not make them worse.
- Correct full-year evidence: 42898/43579 deck history table 'Return on equity ... 17.4/18.1' (multi-column; the FY26
  column), 43183 "return on average equity ('ROAE') for FY2026 was 4.3%" (that one is a different entity's figure:
  check, likely Bajaj Finserv or an insurance subsidiary).
- Use `doc_page` in the same db for the page text of each row (`SELECT text FROM doc_page WHERE doc_key=? AND page=?`).
- Fast check: build the kpi part for BAJFINANCE only on a COPY: copy `D:/RealityEngine/pilot10/scratch/t113_p10_v2.db`
  to `.tmp/p10_t107.db`, then `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json
  --out .tmp/p10_t107.db --part kpi --symbols BAJFINANCE` (check `--help` for the symbol flag; if none, build all).

Steps:
1. Read the 12 rows above with their page text; write in your answer, per row, the period the page prints and why.
2. Tests first: fixture pages for (a) a deck tile 'ROE 20.0%' on a quarter results deck -> Q of that deck's quarter,
   never FY; (b) 'Annualised Return on Average Equity 20.03% 18.74% 19.22' under a header 'Q4FY26 Q4FY25 FY26' -> three
   rows with those periods; (c) 'ROE ... for FY2026 was X%' -> FY; (d) 'in the current quarter' -> Q;
   (e) 'Annualised' with no year word on a quarterly document -> Q, never FY.
3. Fix the period assignment in kpi.py with general rules (no company literals): a ratio's default period is the
   document's own quarter unless the sentence or column header says the year (FY, 'for the year', 'full year',
   'FY2026'); a column header decides each column.
4. Rebuild the copy; report before/after for BAJFINANCE roe_pct FY26 and Q4FY26 rows, and the counts of FY ratio rows
   that moved to Q per metric across all ten companies. Check `pilot3_ratio` / `pilot3_kpi` for BAJFINANCE roe FY26
   against the copy (`REALITY_PILOT3_DB=.tmp/p10_t107.db`) answers 18.1 first.
5. Docs as listed. Final answer starts with `Docs updated:`.

Accept: new test file passes; `python -m pytest reality_engine/tests/test_pilot3_kpi.py -q` still passes (run alone);
BAJFINANCE FY26 consolidated ROE served first = 18.1 on the copy.
Limits: never write to `D:/RealityEngine/pilot10/pilot10.db` or any db outside `.tmp/`; do not edit `row_checks.py`
(another author's checker); no company literals; `PYTHONIOENCODING=utf-8`; one test file per process.
Budget: 130 tool calls, 2.5 hours.
Stop if: the period cannot be told from the page for most of the 12 rows: report them with page text and stop.
