# Progress notes — T-049 KPI defect fix

- Read the context pack, `kpi.py`, `build.py`, `stores.py`, `statements.py`, the test file and the 3 Nov grade report.
- Baseline on a `.tmp` copy of `pilot3.db`: answer_check **131 match / 48 partial / 69 mismatch / 3 empty** (same as STATE).
- Causes: (1) HINDALCO segment words came from the page title row and from value rows used as block headings; KEC
  23,000/36,267 took a segment from a previous sentence; (2) no segment-mix / donut / business-revenue rule; (3) prose
  under a distant table header read as a table row (GNPA Q4FY20 for a 31-Mar-2021 line) and a date printed between
  label and value ignored; (4) AUM entity (BFL / BHFL / consolidated) never tagged; (5) 21,858 is the company's
  net-debt-bridge inflow, 10,250 the audited consolidated XBRL CFO (context FourD, FY26, consolidated — matches the
  filing's statement of consolidated cash flows).
- Code: dimension rules, sentence-scoped dimension with share-clause lookback, prose guard, whole-token values,
  `mix_v1` table rule, donut + business-revenue rules, `page_basis` entity from the deck heading, period between
  label and value, statement-period for a restated quarter; `statements.py` company-stated CFO sentence.
- Tests: 10 new tests; 32 pass in `test_pilot3_kpi.py` (the 6 pre-existing `tmp_path` tests error at fixture setup in
  this DSH sandbox: PermissionError on pytest's temp root).
- Rebuilt KPI + stores on the copy; remaining: answer_check on the copy, docs/STATE, report.

## Done (4 Nov 2026)
- Rebuilt --part kpi (with the four OCR DBs + ocr_textrec) and --part stores on .tmp/pilot3.db.
- Printed examples: HINDALCO Q4FY26 EBITDA 10,812 / 11,197 -> dimension total (both decks p35); KEC FY26 order book
  36,267 total (5 rows) / 23,000 T&D (3 rows); BAJFINANCE FY26 AUM mix mortgage 1,62,077, consumer 1,04,485, rural
  25,234, rural_sales 10,559, sme 51,570, commercial 33,839, auto 15,011, gold 17,831, urban_sales 37,430, las
  33,247, 2w3w 4,288+8,325, cv_tractor 3,881, mfi 2,198, total 5,09,975; KEC order book mix 63/27/7/2/1 and revenue
  T&D 15,883 / civil 3,823 / renewables 516 / cables 2,217 / transportation 1,555 / oil_gas 258; GNPA Q4FY25/Q4FY26
  rows exist; AUM entity basis consolidated 5,09,975 / standalone 3,72,986 / bhfl 1,40,706; HINDALCO FY26 CFO
  10,250 (xbrl_reported, audited) + 21,858 (company_stated).
- answer_check on the copy: 134 match / 48 partial / 67 mismatch / 2 empty (baseline 131 / 48 / 69 / 3); two swaps
  (BAJFINANCE045, KEC028) are pilot3_kpi reply-cap artefacts, the store holds the right numbers.
- Tests 32 pass (6 sandbox tmp_path errors); lookups 15 pass (1 named-pipe error).
- Docs: DEVELOPER_GUIDE O2/O5 + 4 Nov state, tasks/STATE.md.
