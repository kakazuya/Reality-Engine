# T-115: annual-report lines keep their printed scale and their own year (fin_annual_line from ar_facts)

Ticket: T-115

Goal: every `fin_annual_line` row built from `ar_facts` carries the rupee scale its unit text names, and the fiscal year
the quote prints, so filed figures can witness KPI rows and answer questions at the right size and year.

Files (only these): `reality_engine/pilot3/stores.py` (`_unit` line 382, `build_annual` line 454), new tests in
`reality_engine/tests/test_pilot3_stores_annual_units.py`, `docs/DB_BUILD_GUIDELINES.md` (the fin_annual_line
paragraph: search "fin_annual_line"), `docs/PILOT3_BLUEPRINT.md` (one line where fin_annual_line is described).

Evidence (Opus, 8 Nov; databases read-only):
- `_unit()` knows only 'crore', 'million'/'mn'/'rs million', '%', 'rs'/'inr', 'per share'; anything else keeps the raw text
  with scale 1. Distinct units now stored in fin_annual_line on the unseen6 build: 'ratio', 'inr_million', 'inr_crore',
  'pct', '₹ in mn', 'inr', 'rs mn', 'unknown', 'times', 'percentage', 'inr_per_share', 'rs lakh', 'rs lacs',
  'rs.in lacs', '` mn', 'rs. in lacs', '₹ mn', 'rs. lacs', 'paise', 'h'. The '`' is the rupee glyph in some AR fonts.
  104 rows on unseen6 + pilot10 carry such a unit with scale 1 (ALKEM, ASHOKA, UFLEX, KALYANKJIL, SBILIFE 'rs billion',
  SUNPHARMA '₹ billion'), e.g. ALKEM FY24 revenue 126676.0 '₹ in mn' scale 1, ASHOKA FY24 revenue 979846.22 'rs lakh'.
- Wrong year: ALKEM's 5-year table on one AR page is stored five times under FY26 (`ar_facts.period` = the report's year):
  ('FY26','Revenue from operations',106342.0,'₹ in mn', page 15, quote 'FY 2021-22 106,342'), same for
  'FY 2022-23 1,15,993', 'FY 2023-24 1,26,676', 'FY 2024-25 1,29,645', 'FY 2025-26 1,47,123'. The quote prints the
  column's own year. Another form seen: 'Revenue From Operations (₹ in Mn) 1,26,676 FY2024' stored correctly as FY24.
- Check db: `C:/Users/warri/AppData/Local/Temp/claude/12b5f02fd3b7ce95/fa93aa0b-0c04-408d-a8f4-f7630af29fed/scratchpad/ho/u6_eval.db`
  with profile `.../scratchpad/ho/unseen6_profile.json` (same folder). Copy the db to `.tmp/u6_t115.db` and build only
  there: `python -m reality_engine.pilot3.build --profile <profile> --out .tmp/u6_t115.db --part stores` (~1-2 min).
  Pilot10 profile `tasks/night_loop/pilot10_profile.json`; for pilot10 copy `D:/RealityEngine/pilot10/scratch/t113_p10_v2.db`
  to `.tmp/p10_t115.db` the same way. Never build into any other path.
- Query to see the defect: `SELECT symbol, fiscal_year, line_item, value, unit, scale, quote FROM fin_annual_line
  WHERE source_table='ar_facts' AND scale=1 AND unit NOT IN ('inr','pct','ratio','times','percentage','inr_per_share','unknown')`.

Steps:
1. Tests first (tmp fixtures calling `_unit` and a tiny `build_annual` path or a helper you extract from it):
   every unit text above maps to (canonical unit, scale): mn / million / '₹ in mn' / '` mn' / 'rs mn' -> inr_million 1e6;
   lakh / lacs / 'rs. in lacs' / 'rs.in lacs' -> inr_lakh 1e5; crore / cr -> inr_crore 1e7; billion / bn -> inr_billion 1e9;
   thousand / '000 -> inr_thousand 1e3; paise -> inr 0.01; '%','percentage' -> pct; 'times','x','ratio' -> ratio 1.
   'h' and other unknown text stay unknown with scale 1 (do not guess). A unit text naming two scales is unknown.
2. Year from the quote: when the quote prints exactly ONE fiscal year ('FY 2021-22', 'FY2024', 'FY24', 'FY 2025-26',
   '2023-24', 'FY 25') and it differs from the stored period, store the quote's year (and period_end) instead. When the
   quote prints two or more years, keep the stored period but only if the value's own column cannot be told; record the
   choice in a short comment. Write the year parser yourself in stores.py (no shared lexicon edits).
3. After both fixes, dedupe: identical (symbol, fiscal_year, basis, line_item, value*scale rounded to 0.1%, doc_key)
   rows keep one.
4. Build both copies; report before/after: rows per unit/scale, rows whose year changed (read 10, with quotes), and for
   ALKEM, ASHOKA, UFLEX, KIMS-like cases: revenue per year after the fix. Then run the row checker on both copies:
   `python -m reality_engine.pilot3.row_checks --db .tmp/u6_t115.db --out .tmp/rc_u6.db --profile <profile>
   --tables kpi_series` and give fin_conflict / part_not_total / verified counts before (u6: 93 verified / 711 / 172
   quarantined; p10: 3,527 / 2,079 / 437) and after.
5. Docs as listed. Final answer starts with `Docs updated:`.

Accept: `python -m pytest reality_engine/tests/test_pilot3_stores_annual_units.py -q` passes; the defect query above
returns only unit 'h'/unknown rows; ALKEM has one revenue value per year and basis; existing
`python -m pytest reality_engine/tests/test_pilot3_stores.py -q` (if present) still passes, run per file.

Limits and pitfalls:
- Never write to `D:/RealityEngine/pilot10/pilot10.db` or any db outside `.tmp/`. `PYTHONIOENCODING=utf-8` for prints.
- Do not touch `row_checks.py` (another author's checker) or `lexicon/`. No company or year literals in code.
- Write regexes with the editor, never through shell heredocs; never `\b` in a non-raw string.
- Run one test file per process.
Budget: 120 tool calls, 2 hours.
Stop if: the year in the quote disagrees with the page's own column header in a way you cannot resolve generally:
report 5 examples with quotes and stop.
