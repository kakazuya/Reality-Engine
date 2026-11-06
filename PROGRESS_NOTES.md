# T-088 progress notes

- 2026-11-06: read context pack + the named files; verified both INFY claims in ar_facts/pages.db
  (917,626,822,725 is a glued "9,176 (FY26); 8,227 (FY25)"; page 225 is the Company/standalone note 3,749,
  page 339 the Group/consolidated 9,176). Code edits done: fin() preferred comparative + restated + alternatives,
  growth YoY/QoQ same-quarter guard (trusted statuses only), ratio() stated+derived, kpi() entity column +
  company-first + exact-duplicate collapse, TTM pat / pat-before-exceptional rows, stores guards.
  `test_pilot3_preferred.py` 9 passed. Next: rebuild the copy DB (stores/comparatives/ratios/kpi), run the accept
  checks, pilot3 regression tests, checkpages, docs. Blocker: none yet; two pytest temp-dir ACL denials worked
  around by writing scratch files under `.tmp/` instead of a fresh directory.
- First copy rebuild was scoped to INFY,BAJFINANCE for `stores`, and its `schema.create` dropped the other eight
  companies' store rows (the blueprint's known trap) — ratios for those companies lost their input, so the first
  growth diff was invalid. Rebuilt from a fresh copy with `--part stores` for all ten companies.
- Accept values seen on the first (invalid-for-other-companies, valid for INFY/BAJFINANCE) build: fin preferred
  19,992.38 cr with 20,180.76 alternative (as_of Jan: 20,180.76); INFY YoY 10.6855%; ROE Q2FY27 stated 20.6 /
  derived 17.914; FY26 stated 18.1 / derived 16.958; TTM PAT 22,066.48 cr; INFY lease liabilities only the
  consolidated 9,176. Bug found in the entity rule (dimension 'total' accepted as an entity) and fixed; kpi rebuilt.
  checkpages 146 (KEC 29 / BAJFINANCE 59 / HINDALCO 58). `test_pilot3_preferred.py` 9 passed.
- Round 2 (review): the round-1 growth rule was too strict — it refused every `sum_ok` year_ago cell, so HINDUNILVR
  fell back to a pre-restatement first printing. `_printed_year_ago` now takes `xbrl_ok`/`repeat_ok`/`sum_ok` of the
  same fiscal quarter and the better check wins when one filing printed two cells (INFY still picks the xbrl_ok
  44,490 over the sum_ok 45,480); a fallback base is labelled `@fallback`. Rebuilt `--part ratios` on the copy:
  HINDUNILVR Q2FY27 14.4921 / Q1FY27 10.0527 and Q3/Q4 back on live values, INFY 10.6855; only 1 growth value
  differs from live. New tests pin the HINDUNILVR sum_ok case and the @fallback label (11 passed); docs (blueprint
  9d, guide O14, STATE) and the growth-report script updated; commit requested.
