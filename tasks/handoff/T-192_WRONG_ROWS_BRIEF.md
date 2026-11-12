Ticket: T-192

Goal: fix, as general rules (never per company), five kinds of wrong stored rows that four independent Opus graders
found in the T-189 AUROPHARMA store (`D:/RealityEngine/aurobindo/aurobindo.db`). Every model that answered was caught
by them. A fix is right only when it is a rule any listed company gets through the same code.

Evidence (grader findings, 12 Nov; key `D:/RealityEngine/aurobindo/report/key_round1.csv`, grades `report/grades*.csv`):
1. ROE (question A25): `ratio_panel` roe FY26 = 9.24% = PAT 3,502.97 / CLOSING equity 37,883. The annual report
   (FY26 AR p113) states 9.9%; on AVERAGE owners' equity (32,653 + 37,891)/2 it is 9.93%. The row is labelled or read as
   return on average equity. Rule: ROE on average owners' equity when the opening figure is held; closing-equity
   ROE only when it is not, and then labelled `basis=closing_equity`.
2. EBITDA (A55): derived FY25 EBITDA = 6,582.79 cr includes the Rs 23 cr forex loss; the company reports EBITDA
   "before forex and other income" = 6,605 cr, 20.8% (FY25 deck p16, AR p47). A second `ratio_panel` row holds
   EBITDA 6,555.61 with margin 20.66%: two derivations that disagree. And `ebitda_margin_pct` FY25 = 21.4 is the
   Q4 FY25 quarter's margin filed under the annual period. Rules: one EBITDA definition (state it in the formula
   row; exclude forex gain/loss and other income when the statement prints them separately); a margin's numerator
   and denominator come from the same period and the same EBITDA row; an annual period is never filled from a
   quarter.
3. KPI (A03): a stored KPI row carries Q1 FY27 operating EBITDA margin 20.4%; deck p13 and p7 state 21.0%. Find where
   20.4 came from (likely the Q1 FY26 comparative column read as the current quarter) and fix the column rule.
4. Guidance (B04): guidance row `ebitda_margin` FY31 = 15 is Lannett's (a US subsidiary) margin from an analyst
   question (transcript c19eed01 p18), stored as group guidance; the transcript doc is also labelled with the wrong
   call period (Q1FY31). Rules: a target stated for a subsidiary/segment carries that entity and is never served as
   the group's; the call period comes from the filing record, not from a year mentioned in the text.
5. Share count (A39): `share_capital` held 575,400,000 = paid-up capital Rs 57.54 cr / face value, a rounded number
   served as exact. The exact 575,377,895 is in the SHP XBRL (fetched 12 Nov; the store now prefers it). Rule: a
   count derived from rounded capital is marked `derived_from_capital` and never preferred over a filed exact count.

Files: find the writers yourself first (`code-tools outline`, then grep): `reality_engine/pilot3/ratios.py`,
`reality_engine/pilot3/preferred.py`, `reality_engine/pilot3/stores.py`, `reality_engine/pilot3/kpi*.py`,
`reality_engine/pilot3/guidance*.py`, `reality_engine/pilot3/transcripts*.py`, their tests under
`reality_engine/tests/test_pilot3_*.py`. Docs: `docs/PILOT3_BLUEPRINT.md` (methods) and `docs/DEVELOPER_GUIDE.md`.

Steps:
1. For each defect, reproduce it on a COPY of the store in your `.tmp` (`python -m reality_engine.scripts.p3ask --db
   <copy> sql query=...`), find the writing function and line, and write the failing test first (fixture rows, no
   real DB in tests).
2. Fix as a rule. No symbol, company name or ISIN literal in code (`test_pilot3_no_company_literals.py` must pass).
3. Rebuild only the affected parts on copies of the six stores (`D:/RealityEngine/{p20/p20new.db, u8/u8.db,
   q12/q12.db, n10/n10.db, pilot10/pilot10.db, aurobindo/aurobindo.db}`; copy recipe: checkpoint, copy,
   `PRAGMA journal_mode=DELETE`) with `python -m reality_engine.pilot3.build --profile <profile> --out <copy> --part
   <part>`, and diff old vs new rows of the touched tables.
4. Write `.tmp/T-192_DIFF.md`: per store and defect, rows changed / added / removed, and 10 sampled changed rows with
   their source page, so an independent grader can check them.

Accept: `python -m pytest reality_engine/tests/test_pilot3_ratios.py reality_engine/tests/test_pilot3_preferred.py
reality_engine/tests/test_pilot3_no_company_literals.py -q` plus every new test, run one file at a time; the five
AUROPHARMA rows above come out right on the rebuilt copy; `.tmp/T-192_DIFF.md` exists; docs updated in the same
branch.

Limits and pitfalls: never write to the live stores under D:/RealityEngine (copies in `.tmp` only). Never loosen a
row check to make a test pass. Run tests per file (a one-process pilot3 pytest hit 7.9 GB on 4 Nov). Do not commit
PROGRESS_NOTES.md. Do not open `D:/RealityEngine/aurobindo/questions/` or any answers file.

Stop if: a fix would change more than 2% of a table's rows in any store other than aurobindo (report the count and
stop for review); or a defect needs a judgement about what the company meant (write it up, skip it).

Budget: 3 hours; one session.

## Round 2 (12 Nov 14:25, Opus review of dsh/20261112T075239Z-35e1d0fc; you start from that branch)
Keep: the ROE average-equity rule in `ratios.py` and the call period from `doc_period` in `guidance.py`.
Fix, verbatim review findings:
- R1. `ratios.py` / `statements.py` forex: the keys `forex_gain_loss`, `exchange_gain_loss`,
  `foreign_exchange_gain_loss` exist in NO store (checked: `SELECT DISTINCT line_item FROM fin_annual_line` and
  `fin_quarter_xbrl` on aurobindo.db), so EBITDA did not change. Find how the filed XBRL actually carries forex (grep
  the results_xbrl parser and the AUROPHARMA FY25 quarterly lines); if forex is not a separate filed line, do not
  derive it. Instead: when the company prints its own EBITDA (deck / press release KPI row, `kpi_series`), serve that
  as the preferred EBITDA and margin, with the derived one kept as a second, labelled row. And fix `ebitda_margin_pct`
  FY25 = 21.4, which is the Q4 FY25 quarter margin under the annual period: an annual row is never filled from a
  quarter.
- R2. `stores.py` line 287: you replaced the `known_at_source` text with "derived_from_capital". That destroys the
  provenance. Revert it; mark the derived count in its own field (or the `unit`/`definition` column the table has),
  and make the share-count preference (`lookups_pilot3` holding / `preferred`) pick a filed exact count (SHP
  `shp_category` total) over a capital-derived one for the same date.
- R3. Defect 3 (KPI Q1 FY27 operating EBITDA margin 20.4 vs 21.0 printed, deck p7/p13) and defect 4 (Lannett margin
  stored as group guidance) were not touched. Do them.
- R4. No tests were written. For every defect add a test that FAILS on main and passes on your branch (fixture rows).
  The 9 `test_pilot3_ratios.py` errors are a tmpdir problem: set `--basetemp=.tmp/pt` and make them run.
- R5. Steps 3-4 are required: rebuild the touched parts on store COPIES and write `.tmp/T-192_DIFF.md`.
Accept (round 2): the tests above pass one file at a time; `.tmp/T-192_DIFF.md` shows the five AUROPHARMA rows right
and per-store changed-row counts. Budget 3 hours.

## Round 3 (DeepSeek v4.1 flash, off-peak; starts from dsh/20261112T080310Z-024abcfe)
Review of round 2 (Opus, 12 Nov 14:50). Keep: `kpi._kept_columns(cols, current)`; capital-derived share counts ordered
last in `lookups_pilot3.holding` and `_ref_input`; ROE average equity; call period from `doc_period`.
Fix, verbatim:
- G1. `guidance.py` ~line 1459 tests `speaker == "Swami Iyer"`: a person's name in code is a per-company literal and is
  forbidden. Replace with a rule: a target stated for a named subsidiary/segment/investee (the sentence or the
  question it answers names an entity other than the company: "Lannett", "Eugia", "Aurobindo Pharma USA", a
  subsidiary list from the annual report's subsidiary table if held) carries that entity and is never the group's.
- G2. `stores.py` writes "derived_from_capital" into share_capital's `ratio` column (meant for split ratios). Use or
  add a proper column (`count_basis`: `filed_exact` | `derived_from_capital`), migrate in `schema.py`, and order on it.
- G3. EBITDA: no change was made. Serve the company-printed EBITDA and margin (kpi_series / press-release or deck
  row) as preferred in `pilot3_fact` when one exists for the period and basis; keep the derived one as a second,
  labelled row. Fix `ebitda_margin_pct` FY25 = 21.4 on aurobindo (a quarter's margin under the annual period).
- G4. Delete `reality_engine/tests/conftest_tmp.py` (it is not a conftest and does nothing). Use `--basetemp=.tmp/pt`.
- G5. Tests: one test per defect that FAILS on main and PASSES on the branch; show both runs in your final answer.
- G6. Rebuild on copies is mandatory (your sandbox may read D:/RealityEngine; write the copies under your `.tmp`):
  aurobindo + pilot10 at least, parts `stores kpi guidance preferred ratios`; `.tmp/T-192_DIFF.md` with per-table
  changed-row counts and the five AUROPHARMA rows before/after. Without it the branch is not reviewed.
Stop if: the pilot10 copy loses any row a test or grader marked right (list them). Budget 3 hours.

## Round 4 (DeepSeek, off-peak; starts from dsh/20261112T100117Z-b83f0ffa)
Review of round 3 (Opus, 12 Nov 16:25). Opus rebuilt copies of pilot10 with main code and with your branch (parts
transcripts, kpi, guidance, ratios) and diffed them. Keep: ROE average equity; `_kept_columns(cols, current)`;
`call_period_ok` / `filing_quarter`; `count_basis`; `_ebitda_rank`; the 8 new tests (Opus ran them on main: the KPI and
transcript ones fail there as required). Fix, verbatim:
- H1. BLOCKER. `ratios.py:204` `_share_count` and `lookups_pilot3.py` lines ~927, ~934, ~1732 read
  `share_capital.count_basis`, which only `stores` adds. On the pilot10 copy `--part ratios` crashed
  (`sqlite3.OperationalError: no such column: count_basis`), and after a reality-data restart `pilot3_holding` would fail
  on all six live stores, which have no such column. Lookups open stores read-only: they must tolerate the column being
  absent (PRAGMA table_info once per connection; fall back to `source_table='shp_category'`). `ratios` must call
  `schema.ensure_columns(conn, "share_capital", schema.SHARE_CAPITAL_ADDITIONS)` first. Test: a fixture store with the
  old 18-column share_capital, through `holding()` and `build --part ratios`.
- H2. STOP RULE HIT: the guidance entity rule hides group targets. On pilot10 it tagged 11 rows; at least 6 are the
  group's own: BAJFINANCE `opex_to_nti` FY27 25-40 entity "NTI" (x2; NTI = net total income, a metric), HINDALCO
  `cost_of_production` entity "LME" (a price benchmark), HINDALCO capex FY26 8,000 entity "Bandha Mine" (the company's
  own mine project), SBILIFE `revenue_growth` FY27 14 entity "APE" (a metric), ETERNAL `ebitda_margin` FY27 5-6 entity
  "AOV" (a metric). Right ones: Novelis, Bajaj Housing, (Lannett, Merck on aurobindo). Rule to use instead: an entity
  makes a target non-group only when it is a SUBSIDIARY / associate / JV / acquired company, known from data:
  the annual report's subsidiary list or related-party table if held (`notes` part), the store's `entity` values that
  `kpi_series` already uses for subsidiaries, or a filing/statement naming it "subsidiary", "acquisition", "step-down",
  "associate", "joint venture". An acronym (all caps, <= 4 letters), a metric word, a benchmark, a plant/mine/project
  name is never an entity. Unsure = keep it group (and label `entity_unsure`), never hide. Test with the 6 wrong rows
  as fixtures (must stay group) plus Lannett/Novelis (must be entity rows). Re-diff pilot10: zero group targets lost.
- H3. KPI default period for transcripts (`kpi.py` ~3275): forcing the filing quarter when the document default is not
  a quarter relabelled 78 pilot10 rows; some got better (KEC order book from a Q2 call -> Q2FY26) but some got worse:
  SUNPHARMA `domestic_formulations` 192,904 "India formulation sales for the full year" FY26 -> Q4FY26 (wrong);
  SBILIFE `vnb` 32.7 bn H1FY27 -> Q2FY27 (VNB is reported year-to-date: wrong); 9MFY26 -> Q3FY26 (5 rows) and
  H1 -> Q2 (8 rows) the same kind. Rule: a row whose sentence or table header says full year / for the year / FY /
  nine months / 9M / H1 / half year / YTD / year-to-date keeps that period; the filing quarter is only the default for
  rows with no period cue. Stock figures at a quarter end (order book, AUM, net debt, cash) take the quarter-end
  period. Test with those three quotes.
- H4. `kpi.py` MON_Y still matches a word that merely starts with a month abbreviation followed by an integer. Opus's
  probe on your branch: "EBITDA Margin\n21%" -> "Margin\n21", "Margin 24", "Marketing 22", "Junk 23" all match. Only
  a real month name (Jan, January, Feb, ..., Sep, Sept, September, ...) followed by a non-letter may match. Add these
  four to the test.
- H5. The FY25 `ebitda_margin_pct` 21.4 row on aurobindo (Q1 FY25 transcript p4) is still stored under FY25. Trace it
  and fix the rule (likely the H3 rule covers it); the rebuilt row must be Q-labelled or carry its own sentence period.
- H6. `pilot3_fact` routes ebitda / ebitda_margin to `kpi` whenever `kpi_series` holds any EBITDA row for the company.
  Show with a test that for a period the KPI rows do not cover (e.g. a fixture with KPI EBITDA for FY25 only, asked
  FY24) the reply still returns the derived ratio_panel figure, not an empty or wrong-period KPI answer.
- H7. Non-results calls (SUNPHARMA "Organon Acquisition Investor Call", filed 5 May) now get a quarter (Q4FY26) from
  the filing record. Only a results/earnings call takes a filing quarter; an acquisition/investor-day call keeps
  call_period NULL. Test with the title.
- H8. Rebuild on copies BOTH sides yourself (main code and branch code from the same starting copy, so pre-existing
  drift cancels), for aurobindo and pilot10, parts transcripts kpi guidance ratios, and write `.tmp/T-192_DIFF.md`
  with per-table removed/added/period-changed counts per store and 10 sampled changed rows per store with quotes.
Accept: all round-3 tests plus new tests pass one file at a time (use `--basetemp=.tmp/pt<n>` with a NEW name each run);
pilot10 diff: zero group guidance targets hidden that main served, KPI period changes listed and each class justified.
Stop if: any pilot10 group target is hidden after H2, or the KPI rows changed exceed 2% of pilot10's kpi_series.
Budget: 3 hours.

## Round 5 (DeepSeek; starts from dsh/20261112T105109Z-a810bf31)
Review of round 4 (Opus, 12 Nov 17:40): Opus rebuilt pilot10 from the same live copy with main and with your branch
(transcripts kpi guidance ratios). Good: tests pass per file (ratios 17, preferred 16, kpi_ratio_period 13, guidance 46,
transcripts 22, literals 7, shp_holder 5, price_window 7); ratios no longer crashes; the 6 round-3 false entities are
gone; Organon call stays NULL; MON_Y fixed; BAJFINANCE credit cost "2.09% in FY26" FY25 -> FY26 is a real fix.
Keep all of it. Fix, verbatim:
- J1. STOP RULE HIT AGAIN: 4 HINDALCO group targets are hidden as `entity='Novelis'`; every one is INDIA capex:
  p14 "And the India CAPEX ... around INR 10,000 crores a year"; p20 "our target is about ... INR 8,000 crores ... the
  Bandha Mine"; p11 "In FY27, the India capex will be about INR12,000 crores, and the Novelis capex will be ...";
  p11 "India capex, Pinakin, INR12,000 crores this year, next year ... INR15,000 crores to INR17,000 crores".
  The entity came from the analyst question. Rule: the sentence's own scope wins over the question's: when the
  sentence names the company itself, a home-country/standalone scope ("India", "standalone", "domestic", the
  company's name), or a different entity than the question, the question's entity is not used; when a sentence names
  two scopes, a figure belongs to the scope named nearest before it. Only when the sentence names no scope at all may
  the question's entity apply, and then only if that entity is proven (your known_entity_names). Test with these four
  quotes (group) and the Lannett/Bajaj Housing ones (entity).
- J2. KPI default for a Q4 (results) call: 36 pilot10 rows moved FY26 -> Q4FY26, e.g. SBILIFE `ape` "APE stands at
  INR221.1 billion" and "INR242.7 billion", `market_share` 21.4% — these are the year's figures (a Q4 call reports the
  full year for flows). Rule: in a call whose filing quarter is Q4, a flow figure (APE, VNB, premium, revenue,
  disbursements, order intake, PAT, EBITDA) with no period cue keeps the fiscal year; a stock at the quarter end (AUM,
  order book, net debt, leverage, cash) may take Q4 (same date as the year end). Q1-Q3 calls keep your round-4 rule.
  Test with the two APE quotes (FY26) and SBILIFE AUM "assets under management stands at INR4.9 trillion" (Q4FY26 ok).
- J3. Re-diff pilot10 (main vs branch from the same copy): guidance group rows lost must be 0 (main 104); KPI period
  changes must fall under 2% of keys (main 6,185 keys), each class listed in `.tmp/T-192_DIFF.md` with 3 quotes.
Accept: the round-4 tests plus J1/J2 tests pass, one file at a time; DIFF shows 0 group targets lost and KPI churn < 2%.
Stop if: either number is missed after one honest attempt (report it). Budget: 2 hours.
