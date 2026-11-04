# Pilot database blueprint (KEC, BAJFINANCE, HINDALCO; any company list from a profile, section 9)

The one persistent record of how the pilot database was designed, tested and improved, and what the tests found.
Read this before changing the schema, an extractor or the scale-up plan. It keeps the method and the results;
the code's own detail stays in `docs/DEVELOPER_GUIDE.md` sections O to O8, and the live step in `tasks/STATE.md`; the rules derived from it are in `docs/DB_BUILD_GUIDELINES.md`.
Started 4 Nov 2026 (Eagle). Update it in the same commit as any change it describes.

## 1. Goal and rules
- One database where every investor question is a query: facts extracted once from raw filings by scripts (no model
  calls in the build), each row carrying its source document, page, exact quote and `known_at` (point in time).
- A number the filings do not print is a formula over extracted inputs (`ratio_panel`, `formula`), never a gap.
- Golden order (AGENTS.md): pilot must reach 95% answered plus the checklist before any full run; embeddings last.
- Answers go through the `reality-data` MCP `pilot3_*` tools only; raw files only when the database cannot answer,
  and then the gap becomes a table or an extractor fix.

## 2. Schema (one SQLite file, `reality_engine/data/pilot3/pilot3.db`)
| Table | Holds | Built from |
|---|---|---|
| `company` | symbol, ISIN (with history), BSE code | security master |
| `doc`, `doc_alias` | every held document: type, title, filing date, `known_at`, source | `pages.db` (docs_collect) |
| `doc_page` (+ FTS `doc_page_fts`) | page text, method (text layer / OCR), confidence | PDF text layer, OCR dbs |
| `fin_annual_line`, `fin_quarter_xbrl` | reported financial lines, basis (consolidated / standalone), definition | exchange XBRL results |
| `fin_quarter_printed` (T-057) | every P&L cell a results table prints: current, preceding, year-ago, ytd, prior ytd, last full year, with the check that confirmed it (`xbrl_ok`/`sum_ok`/`unchecked`) | the results PDF's word boxes |
| `ratio_panel`, `formula` | derived ratios with formula id and input row ids | computed from fin lines |
| `kpi_series` | company-stated KPIs (order book, AUM, EBITDA/t, NIM, mixes) with period, dimension, entity, quote, page | decks, results, press releases, transcripts |
| `transcript_statement` | call quotes with speaker, role, topic tags | transcripts |
| `guidance` | one row per forward target: metric, period, low/high, unit, revision link | transcripts, decks, results, press releases |
| `shp_category`, `share_capital`, `dividend_event`, `price_delivery`, `valuation_daily` | holdings, share count, dividends, prices, PE/PB/EV | exchange data stores |
| `bulk_block_deal`, `insider_trade`, `index_price` (profile builds, T-056 loop 2) | bulk/block deals and SEBI insider trades per company (none held = no rows); the stock against `Nifty 50` (and a profile's `extra_indices`) per trading day with 1/3/6/12-month relative return in points | `equity_intelligence.db` + price rows |

Tools: `pilot3_fin`, `pilot3_ratio`, `pilot3_kpi`, `pilot3_guidance`, `pilot3_statements`, `pilot3_search` (bm25),
`pilot3_docs`, `pilot3_holding`, `pilot3_sql`; `schema` / `catalog` know the `pilot3` db.

## 3. Extraction methods (what works, what failed)
- **Documents**: collected per company into `D:\RealityEngine\pilot3\pages.db`. Dates: `known_at` = exchange
  dissemination time; a transcript is never known before the call date printed in its first pages (`call_dates.py`).
  Order wins filed as generic press releases are retyped by headline.
- **Page text**: 96% of pages have a text layer (22,589 of 23,558). OCR only the rest (969 pages; HP TextRecognizer
  ~116 pages/min, MSI RapidOCR ~4 pages/min: OCR runs on the HP).
- **Financials**: from XBRL, labelled with basis and definition; tools default to consolidated (a standalone EPS was
  once returned for a consolidated question). Both company-stated and audited figures are kept, each labelled
  (Hindalco FY26 operating cash flow: 10,250 cr XBRL vs 21,858 cr company bridge).
- **KPIs**: rule-based readers for sentences, tables (columns mapped to period headers), charts, segment-mix tables
  (`mix_v1`), entity headings (consolidated / standalone / subsidiary). Lexicon families in `pilot3/lexicon/`
  (common, lenders, metals, orders, dimensions, topics). Period rules: a period can never start after its document's
  date ("June 26, 2019" was once read as June 2026); a later deck restating an earlier quarter keeps that quarter.
- **Guidance**: sentence rules: forward cue, metric must be the target's subject, past actuals / tariff rates / supply
  shares / net-debt sentences rejected. Precision: 18/30 clean (3 Nov) → 28/40 (4 Nov). Remaining errors: two
  quantities in one sentence, restated past figures, vague levels.
- **Segments from the raw results XBRL** (`pilot3/xbrl_segments.py`, `build --part segments`, loop 2, 4 Nov 2026):
  `results_xbrl.db.facts` keeps only the undimensioned totals, so a script reads each window filing's instance and
  writes `segment_revenue`, `segment_ebit`, `segment_assets`, `segment_liabilities` per reportable segment into
  `kpi_series` (`source_type='xbrl_segment'`, `confidence='xbrl'`, page 0, empty quote, file name as `doc_key`).
  Axis, member and period come from the context, never its id; an instant (assets, liabilities) takes its name from
  the sister duration context. Life insurers: revenue = net premium + investment income + other income + transfer from
  shareholders (`is_reported` 0), EBIT = `SurplusDeficit`. A filing that says `Single segment` gets one
  `single_segment` row per metric (revenue from operations or total income; profit before tax + finance costs;
  `is_reported` 0). Segment names are normalised and mapped per company: names that occur together in one filing never merge (Participating / Non Participating Pension are two segments); similar names (difflib >= 0.85) that never occur together merge to the spelling used in the most filings, a tie going to the latest. `raw_label` keeps the name as filed; a single-segment description of 'NA' falls back to "Single segment". The
  `kpi` part keeps these rows when it rewrites a company. Check: segment revenue less inter-segment revenue equals the
  filing's `SegmentRevenueFromOperations` within 1%.
- **Company-specific parts today** (the scale-up cost): segment patterns in `dimensions.yaml` (26 for 3 companies),
  sector lexicons, and a few hard-coded cases (lender has no EBITDA, KEC website transcripts, one KEC name guard).

## 4. Test methodology
- **Question bank**: 300 pilot questions (100 per company) rewritten from the frozen 1,901 bank; undated questions
  use `as_of` 2026-10-19.
- **Automatic check** (`pilot3.answer_check`): maps each question to a tool call and compares with an oracle;
  classes match / partial / mismatch / empty / answered_no_oracle. Good for regressions, not the reported score.
- **Hand-read grade** (the only reported score): DeepSeek workers answer through the MCP only; Opus reads every
  answer: R right, P partly right, W wrong. Files: `D:\RealityEngine\pilot3\answer_run*`.
- **Retrieval test** (`pilot3.embed_test`): gold pages = pages holding an exact quote from a right / partly right
  answer (leans towards pages bm25 already finds); hit@1/5/10/50 and MRR per method.

## 5. Results history
| Date | Test | Result |
|---|---|---|
| 1 Nov | prototype 3, 40 sampled answers | 0 right, 78% of numbers missed |
| 3 Nov | T-048 gap loops (Claude models, per company) | KEC 89, BAJFINANCE 83, HINDALCO 79 of 100 |
| 3 Nov | answer_check, rebuilt db | 114 → 131 match of 300 |
| 3 Nov | MCP-only answers, hand-read 185 | 110 right / 58 partly / 17 wrong |
| 4 Nov | after guidance table + KPI fixes, same 185 | **154 / 30 / 1** (KEC 54/6/1, BAJ 48/13/0, HIN 52/11/0) |
| 4 Nov | answer_check after KPI + dates merges | 134 match, no match lost |
| 4 Nov | embeddings, 112 gold questions, top 10 | bm25 35%, bm25+1B 46%, bm25+8B 52%; images add nothing |

Open from the 4 Nov grade: data not held (RBI repo path, national capex), one part of two-part questions missed,
definitions not reconciled (BHFL share of profit, ROCE), KEC transcripts stored twice (website + exchange copy).

## 6. Findings that set the scale-up plan
- **Sources the 185 graded answers used** (a question can use several): investor presentations 37%, transcripts 30%,
  annual reports 24%, XBRL financials 24%, computed ratios 14%, announcements 12%, market / shareholding 10%,
  press releases 7%. **86% need no annual report**; at most 26 questions (14%) had an annual-report figure found
  nowhere else (`D:\RealityEngine\pilot3\embed_test\question_sources.json`).
- **Annual report sections**: front section (highlights, KPIs, strategy), directors' report and MD&A = ~37% of
  pages and 40 of 46 quotes used; financial statements, notes, auditor report, AGM notice = ~49% of pages and 1 quote
  (XBRL covers them). Corporate governance + BRSR = 15% of pages, 4 quotes (credit ratings, RBI action). Read the
  front section only; notes later for related-party / contingent-liability questions (`ar_sections.json`).
- **Announcements**: 1,425 of 2,004 documents; analyst-meet intimations (422), board-meeting notices (118),
  certificates and trading-window filings are never used by answers; outcomes, management changes, credit ratings,
  acquisitions, AGM/EGM, dividends and order wins are. Keep all, subtype them, skip OCR on the unused kinds.
- **Embeddings** (by document type, top 10): decks 15% bm25 → 40% 8B alone; annual reports 17% → 37% hybrid;
  transcripts 38% → 52% hybrid; press releases 55% bm25, embeddings worse. Blend per type; text only.
  Cost measured: 1B $0.1224, 8B $0.2683 for 4,606 pages + 1,451 images (`by_doc_type.json`, `image_test.json`).

## 7. Scale-up plan (bare bones first, Shivam 4 Nov)
1. Download-time triage: category / headline decides OCR; text-layer check first; OCR page 1 of scans only, then
   decide; exact hash + first-page text fingerprint to drop duplicates.
2. Build without annual reports first (XBRL, decks, transcripts, results, press releases, material announcements);
   then annual-report front sections.
3. Segments from each company's segment note (no hand patterns); one KPI lexicon per sector family (~12).
4. Fast checks: incremental build (`--part`, per company, cached by document hash + extractor version) and fixed
   check pages per extractor; full rebuild only at merge.
5. Run unchanged on 10 pilot-60 companies across sectors, measure fill rate, fixes needed and build time per company.
6. Embeddings, chunking and the rest in the background once a working database exists for every company.

## 7a. Build timings (MSI, 4 Nov 2026, live rebuild)
- `docs_collect` (all 3 companies, 1,999 documents): 528 s, ~3 min per company.
- `build --part all` with 4 OCR dbs: 484 s for 23,558 pages (~2.7 min per company, single process).
- After the dates + guidance merges: guidance 660 -> 329 rows (KEC 218, BAJFINANCE 52, HINDALCO 59): check recall
  on the next re-answer; kpi_series 38,851; zero Q1FY27 rows from documents known before 2026-04-01.

## 8. Where the evidence lives
- Reports: `D:\RealityEngine\reports\2026-11-03_mcp_answer_grade.html`, `2026-11-04_mcp_reanswer_grade.html`,
  `2026-11-04_embedding_test.html`, `2026-11-03_answer_check_final.html`, `2026-11-03_ocr_hp_vs_msi.html`.
- Grades and answers: `D:\RealityEngine\pilot3\answer_run\`, `answer_run2\` (`regrades.tsv`).
- Retrieval evidence: `D:\RealityEngine\pilot3\embed_test\` (gold.json, EVAL.xlsx, split.json, by_doc_type.json,
  image_test.json, question_sources.json, ar_sections.json). Vector caches there are disposable.
- Decisions: `D:\RealityEngine\plans\DECISION_LOG.md`. Briefs: `tasks/dsh_tasks/T049_*`.
- Disposable: `D:\RealityEngine\pilot3\pilot3_before_*.db` backups, `pages_before_*.db`, worker `.tmp` folders.

## 9. Profiles: any company list (T-056, 4 Nov 2026)

A profile is one JSON file naming the companies and the paths a build reads, so the company literals live in the
JSON and never in an extractor: `name`, `pages_db`, `raw_root` (with its `manifest.csv`), `out` (the database),
`window_start`, and `companies` (`symbol`, `name`, `bse_code`, `isins`, `sector`, `lender`). The committed
pilot10 profile is `tasks/night_loop/pilot10_profile.json` (10 companies, window from 2025-10-01);
`reality_engine/pilot3/profile.py` loads it (`Profile`, `ProfileCompany`, `load`) and every pilot3 module reads the
active one. Without a profile every command behaves exactly as before (the three pilot3 companies into `pilot3.db`).

    python -m reality_engine.pilot3.docs_collect --profile tasks/night_loop/pilot10_profile.json --symbols MARUTI --out .tmp/p10/pages.db
    python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --symbols MARUTI --part kpi --out .tmp/p10/p10.db --pages-db .tmp/p10/pages.db

- **Manifest only.** Under a profile `docs_collect` reads the raw `manifest.csv` (`status='ok'` rows), writes the
  same `doc` / `doc_page` / FTS tables, and dates each document `known_at = dissem_ts`; it does not walk the raw
  store and does not query a filing store. A bucket with no document behind it (`concall_audio_link`, `skip`), a
  row whose file is not on disk and a row without `dissem_ts` are counted, not written.
- **No sandbox.** The extractors read documents and pages from `pages_db` only; they never open
  `<sandbox>/<co>_loop`.
- **Window.** The store builders keep rows dated on or after `window_start` (`fin_quarter_xbrl.period_end`,
  `fin_annual_line.period_end`, `shp_category.quarter_end`, `price_delivery.date`, `valuation_daily.date`);
  documents come from the manifest, which is the requested window. No profile: no filter.
- **`--symbols` limits every part** under a profile (a profile database built for one company holds one company);
  without a profile it still limits only the extractors, as before. `--out` and `--pages-db` override the
  profile's paths.
- **MCP.** With `REALITY_PILOT3_DB` set, `plugins/reality-data/server/lookups_pilot3.py` takes the allowed
  companies from that database's `company` table, so the `pilot3_*` tools serve a profile build unchanged.
- **Verified 4 Nov 2026** (this MSI, `.tmp` outputs). Without a profile nothing moved: `checkpages run` 145 found
  (KEC 29/78, BAJFINANCE 59/113, HINDALCO 57/123) and `build --part kpi --symbols KEC` on a copy plus the four
  `--ocr-db` databases reproduces all 6,915 KEC `kpi_series` rows exactly (96 s; without `--ocr-db` the 39 rows
  read from OCR text are missing, as on any build). With the pilot10 profile, MARUTI: `docs_collect` 147 documents
  / 1,170 pages (17 s, 15 `needs_ocr`); `build` parts registry 0.2 s, pages 0.5 s, stores 15.5 s, kpi 11.8 s,
  transcripts 0.3 s, guidance 0.4 s -> `company` 1 row, `doc` 147 with `known_at` on every row, `doc_page` 1,170,
  `fin_quarter_xbrl` 164 rows (min `period_end` 2025-12-31), `fin_annual_line` 260 (min 2026-03-31),
  `price_delivery` 516 (min 2025-10-01), `shp_category` 180, `kpi_series` 161. MARUTI's five `concall_transcript`
  filings are one-page cover letters ("the transcript ... has been uploaded"), so `transcript_statement` and
  `guidance` are 0 for it: the documents, not the code path (the KPI extractor reads the same pages: 161 rows).
- **Tests.** `reality_engine/tests/test_pilot3_profile.py` (6 tests: the committed profile, the no-profile
  defaults, a manifest -> pages -> registry/pages/kpi/transcripts/guidance build with a sandbox root that does not
  exist, the window filter, `--symbols` scoping, and `lookups_pilot3` on a `REALITY_PILOT3_DB` database).

- **Segments part.** `build --part segments` (after `extract` in `all`) runs `pilot3/xbrl_segments.py` for the
  profile's companies from the raw XBRL named in `results_xbrl.db.filings` (about 1 s for 10 companies); it needs no
  pages. First run on the pilot10 copy: A1 571 -> 601 of 898, `kpi_series.segment_revenue` and `segment_ebit` no longer
  unmet. Test: `reality_engine/tests/test_pilot3_xbrl_segments.py`.

### 9a. Compute-only history, bank and insurer lines, three new tables (T-056 loop 2, 4 Nov 2026)

- **Superseded direction (Shivam, 4 Nov, T-057):** the older quarters above are printed in the held results tables as QoQ and YoY comparatives, so they need no download. `compute_start` stays unset in the pilot10 profile until T-057 reports.
- **`compute_start`** (optional profile key, default = `window_start`, so nothing changes): rows of `fin_quarter_xbrl`,
  `fin_annual_line` and `price_delivery` dated from `compute_start` up to `window_start` move to `<table>_input` at the end
  of `--part stores` (`stores.apply_window`). `--part ratios` reads them through TEMP views named like the tables
  (`main.t UNION ALL main.t_input`), computes, drops the views and deletes `ratio_panel` / `valuation_daily` rows dated before
  `window_start` (`stores.trim_derived`). No answer table holds a pre-window row (min dates 2025-10-01 / 2025-12-31); the
  inputs are only already-held XBRL and price rows, nothing is fetched. `--part ratios` re-run gives byte-identical
  `ratio_panel` (1,612 rows) and `valuation_daily` (2,651). Point in time stays exact: a day's TTM uses the last four quarters
  with `known_at` <= that day; HINDALCO's last four known quarters end Q1 FY27 and no Q2 is extrapolated. Use
  `compute_start` 2024-07-01 or earlier: BAJFINANCE's Q2 FY26 XBRL was disseminated 10 Nov 2025, so its TTM on 3 Nov 2025 is
  Q2 FY25 to Q1 FY26 and needs the quarter ended 2024-09-30 (2024-10-01 would drop it).
- **Bank and life-insurer P&L lines** (`stores.BANK_TAGS`, `LIFE_TAGS`, recognised by one marker element per filing, no company
  list): `pat`, `pbt`, `employee_cost`, `other_expenses`, `operating_expenses`, `operating_profit`, `interest_expended`,
  `eps_basic/diluted`; bank `net_interest_income` = InterestEarned - InterestExpended (derived, `is_reported` 0); insurer
  `gross_premium`, `net_premium`, `investment_income`, `expenses_of_management`, `net_commission`, `net_surplus`. A line the
  `quarterly` view already gave is never written twice. Annual lines follow (`statements.PL_TAGS`), plus bank net worth =
  Capital + ReservesAndSurplus, insurer net worth = ShareholdersFunds, `cash_and_equivalents` of a lender from the cash-flow
  statement, `investments` = current + non-current, and an annual `ebitda` (F_EBITDA on the filed annual lines, `xbrl_derived`,
  beside the company-stated one). Checks: HDFC Bank standalone `pat` Q3FY26..Q2FY27 = 186,537.5 / 192,210.5 / 190,597.2 /
  195,099.6 million rupees; SBILIFE Q2FY27 `pat` 5,492,318,000 (as the filing); HDFC standalone cost-to-income Q2FY27 39.1%,
  FY26 `eps_basic_fy` 48.615 (the filed annual EPS is 48.62; the Q1 EPS filed before the 1:1 bonus is restated by the
  cumulative split factor, see F_EPS_FY).
- **Share count**: a quarter end with no results-filing share count takes the `shareholding_pattern` total of `shp_category`
  with the SHP's `known_at` (`share_capital.source_table='shp_category'`): SBILIFE 5 quarters (1,003,405,073 at 30 Sep 2026),
  HINDALCO 30 Sep 2026 (2,247,226,523). `valuation_daily` uses standalone for a company with no consolidated filing (SBILIFE).
- **Ratios**: half-year point-in-time ratios (`book_value_per_share`, `roe`, `roa`, `roce`, `net_debt_to_ebitda`, days, ...) are
  also written under the quarter label (`Q2FY27`, same value and formula; the NIM is a period measure and is not copied);
  `cost_to_income` (F_COST_INCOME, banks); `dividend_payout_pct` uses one DPS per fiscal year (the corporate-action sum wins over
  an annual-report figure); a zero `dividend_yield_pct` is written only when no dividend was declared in 12 months and the last
  filed annual cash flow shows none paid (ETERNAL).
- **New tables**, read by ISIN (every ISIN the company has had), no placeholder rows: `bulk_block_deal` (2 to 14 rows for BAJFINANCE,
  ETERNAL, HDFCBANK, HINDALCO, HINDUNILVR, INFY, SBILIFE, SUNPHARMA; none for KEC and MARUTI, which the store holds nothing for after
  23 Sep and 14 Jul 2025), `insider_trade` (INFY 363, BAJFINANCE 34, HINDUNILVR 7; the store holds no PIT rows after the window start for
  the others), `index_price` (268 days per company against `Nifty 50`). `relative_return_*` = stock return (split-adjusted close) -
  index return, in points, null when the lookback day is before `compute_start` (else `window_start`). INFY 12 months to 3 Nov 2026:
  1,148.1 / 1,485.5 = -22.71%, Nifty 50 23,810.85 / 25,763.35 = -7.58%, relative -15.13 points.
- **Measured** (this MSI, copy of the pilot10 database, 10 companies): `--part stores` 140 s, `--part ratios` 1.4 s. A1 on `dev.jsonl`
  571 -> 679 of 898 questions fully answerable; 137 of the 147 listed structured needs are now met. Still unmet: KEC and MARUTI deals and
  ETERNAL, HDFCBANK, HINDALCO, SUNPHARMA insider trades (nothing held after 2025-10-01), HDFCBANK `nim_pct` Q2FY27 (needs interest-earning
  assets, not in the results XBRL; the loan book is not the bank's NIM base), SBILIFE and SUNPHARMA `pe` and SUNPHARMA `ev_ebitda` on
  2025-11-03 (the XBRL store holds those two from the quarter ended 2025-03-31, so four known quarters exist only from Jan/Feb 2026).
- Without a profile nothing changes (bank/insurer annual rows, restated EPS, payout selection, quarter-labelled copies, zero yield and the
  new tables are built under a profile only); `checkpages run` stays at 145 found.

### 9b. Printed comparative columns (T-057, 4 Nov 2026)

- **`fin_quarter_printed`** (`schema.py`, 23 columns, index `ix_fqp` on `(symbol, basis, line_item, period_end)`): one row per cell
  a quarterly results table prints -- `period_start`, `period_end`, `fiscal_period` (`Q2FY27`; `H1FY27`/`9MFY27` for ytd; `FY26` for a
  year), `period_type` (`quarter`/`ytd`/`fy`), `column_role` (`current`, `preceding`, `year_ago`, `ytd`, `prior_ytd`, `last_fy`),
  `basis`, `statement`, `line_item`, `caption`, `value` (rupees, `unit` `inr` / `inr_per_share`, `scale` 1.0), `raw_token` (the printed
  words), `quote` (the printed row), `doc_key`, `page`, `known_at` (= `doc.known_at`, `known_at_source` `doc.known_at`),
  `check_status` (`xbrl_ok` / `sum_ok` / `unchecked`), `check_detail` (`repaired`, `scale from XBRL`, `derived`, `header_used`), `is_reported`.
- **The part** `reality_engine/pilot3/comparatives.py` (`--part comparatives`, after `stores`, before `ratios`; in `all` only under a
  profile) reads every `results` document of the `--symbols` companies. The table is created with `CREATE TABLE IF NOT EXISTS` (new
  `schema.ensure`) and only the named symbols' rows are deleted -- `schema.create` would drop every company's rows (the HANDOFF 4 Nov trap).
- **Reading.** Page word boxes (`page.get_text("words")`), rows by y-centre within 3.5 pt (as `kpi.py:1538`), column anchors from the x1
  every column's numbers end at, numbers merged only when adjacent fragments belong to one printed token (`20,21 1` -> 20,211; a lone
  dash never merges), every numeric word binned by x. A page must carry a title with "results", no US-dollar unit, no auditor's report or
  cash-flow/equity statement in its head, a header of period words and 8+ rows of 3+ numeric columns; a continuation page with no title
  inherits the previous page when the x-bins match. Labels sit left or in the middle (HINDUNILVR) and are matched by
  `lexicon/results_lines.yaml` (longest pattern wins; OCR-tolerant ordered tokens, no company names -- guard A5).
- **Roles and units.** The current period end is the latest quarter end the header/title prints on or before the filing day, falling back
  on the XBRL quarter the current column equals. Quarter roles are permuted over the first three columns and the ytd/year roles over the
  rest; the permutation the printed month/year supports best wins and the layout order breaks a tie (HDFCBANK's year-ago column misreads
  `39.09.2026`; HINDUNILVR prints the year-ago second). Unit from crore/lakh/million/thousand words; with none, the power of ten in
  {1e5, 1e6, 1e7} that makes the current column equal XBRL (`scale from XBRL`). EPS keeps its own decimals and is never scaled.
- **Checks.** `xbrl_ok` = the value equals `fin_quarter_xbrl` for that basis, quarter and item (tolerance 2 units of the last printed
  decimal); `sum_ok` = an identity holds (`total_income = revenue + other_income`, `pbt_before_exceptional = total_income - total_expenses`,
  `pbt = pbt_before_exceptional + exceptional`, `pat = pbt - tax`, `total_comprehensive_income = pat + other OCI`, the bank set
  `total_income = interest + other`, `expenditure_excl_provisions = interest_expended + operating_expenses`, `operating_profit`,
  `pbt = operating_profit - provisions`, `pat = pbt - tax`, `current + preceding = ytd` on a Q2 table, EPS ~ pat / shares within 1.5%).
  A failed check stores nothing (review CSV beside `--out`); a repaired token enters only behind a confirming check; everything else is
  `unchecked` (stored, never used by ratios). No row prints revenue (HINDUNILVR): `revenue_from_operations = total_income - other_income`,
  `is_reported` 0. Same period printed twice with different values: both rows kept, listed as restatements.
- **Ratios** (`ratios.py`): `_quarters` keeps XBRL where it holds the quarter and otherwise takes the printed quarter from the EARLIEST
  filing that printed it (that row's `known_at`); `period_start` comes from the merged rows (the old XBRL-only lookup crashed on a
  printed-only quarter). YoY uses the same filing's printed `year_ago` column when checked; new `revenue_growth_qoq_pct` /
  `pat_growth_qoq_pct` (`F_REV_QOQ`, `F_PAT_QOQ`). `_valuation` still uses `last4` when four quarters are held and otherwise one filing's
  `TTM = last_fy + ytd - prior_ytd` (Q1: `last_fy + current - year_ago`; Q4: the printed year, `F_TTM_PRINTED`, `refs.ttm_printed`).
  A fiscal year without four quarters takes the printed `fy` rows (`F_FY_PRINTED`): flows, margins, `eps_basic_fy`.
- **MCP**: `pilot3_fin` reads `fin_quarter_printed` after `fin_quarter_xbrl` returns no row for a line item and period, `definition`
  `printed_comparative`, provenance table `fin_quarter_printed`, doc + page, `as_of` honoured; `pilot3_sql` and `catalog` list the table.
- **Measured 4 Nov 2026** on the pilot10 copy (`scratch/w_cmp.db`, built from `scratch/l3_base.db`): 5,587 rows in 2 min 40 s for the
  10 companies (KEC 967, BAJFINANCE 1,156, HINDALCO 705, HDFCBANK 98, SBILIFE 262, INFY 300, SUNPHARMA 870, MARUTI 130, HINDUNILVR
  750, ETERNAL 349; 169 cells to `w_cmp_comparatives_review.csv`). The 12 expected cells read back exactly (KEC preceding/year-ago
  revenue and FY26 pat, HDFCBANK year-ago/ytd interest earned, MARUTI year-ago revenue and preceding EPS 106.62, SBILIFE year-ago net
  premium, HINDUNILVR year-ago/preceding total income, HINDALCO year-ago standalone revenue, INFY FY26 pat). Quarter rows checked:
  ETERNAL 80.4%, HDFCBANK 81.1%, KEC 79.2%, INFY 78.9%, SUNPHARMA 77.4%, MARUTI 73.8%, HINDALCO 65.8%, BAJFINANCE 65.0%,
  HINDUNILVR 63.3%, SBILIFE 42.5% -- short of the 90% target because `fin_quarter_xbrl` holds only four quarters: a filing older than
  that window (every filing before Q3FY26) has no XBRL row for any of its quarter columns, and the insurer's printed total rows
  (`Total (2 to 5)`) carry no canonical line item. `--part ratios` after it: `valuation_daily.pe` days (baseline -> now) BAJFINANCE
  11 -> 244, HINDALCO 0 -> 245, SUNPHARMA 3 -> 246, HINDUNILVR 5 -> 178, KEC 2 -> 117, ETERNAL 10 -> 72, HDFCBANK 11 -> 11,
  INFY 8 -> 8, MARUTI 6 -> 6, SBILIFE 6 -> 6; `ratio_panel` rows up for all 10 (KEC 146 -> 324, HINDALCO 78 -> 211, SUNPHARMA
  146 -> 308) and 95 `pat_growth_qoq_pct` / 94 `revenue_growth_qoq_pct` / 46 `revenue_growth_yoy_pct` / 40 `pat_growth_yoy_pct` rows.
  A1 on `dev.jsonl` 651 -> 680 of 898, no company lower than the baseline (BAJFINANCE 71 -> 77, HINDALCO 69 -> 76, KEC 51 -> 54,
  SUNPHARMA 62 -> 66, HINDUNILVR 71 -> 74, HDFCBANK 71 -> 74, MARUTI 59 -> 61, ETERNAL 65 -> 66, INFY 65, SBILIFE 67).
- **Tests**: `reality_engine/tests/test_pilot3_comparatives.py` (13: word-box rows, the middle-label layout, the HINDUNILVR column
  order, a misread header year, separator and repair rules, unit from text and from XBRL, xbrl_ok/sum_ok, a failed check storing
  nothing, `known_at` = the filing's date, raw token inside its quote, per-symbol rerun scope, TTM from one filing's columns) and one
  new test in `plugins/reality-data/tests/test_lookups_pilot3.py` (printed quarter through `pilot3_fin`, `as_of` filter).


