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
| `doc_identity` (T-093) | one identity verdict per `corporate_documents` row before extraction: company, fiscal year, type, date, each with a reason; `verdict` is `ok` / `set_aside` / `unknown` / `on_drive` / `not_held`; `type_reason` starts `cover_letter:` for a web-link/notification row, `linked_url` is the link it prints and `duplicate_of` the lowest id of the same company+sha; `doc_key` = sha256 (else `corp:<id>`) links it to `doc` | first PDF pages + the filing record + the Drive index |
| `doc_page` (+ FTS `doc_page_fts`) | page text, method (text layer / OCR), confidence | PDF text layer, OCR dbs |
| `fin_annual_line`, `fin_quarter_xbrl` | reported financial lines, basis (consolidated / standalone), definition; `fin_annual_line` keeps the unit text's own rupee scale (mn 1e6, lakh 1e5, crore 1e7, bn 1e9) and the fiscal year the quote prints for that value, one row per year / basis / caption / document (T-115) | exchange XBRL results, annual reports |
| `fin_quarter_printed` (T-057) | every P&L cell a results table prints: current, preceding, year-ago, ytd, prior ytd, last full year, with the check that confirmed it (`xbrl_ok`/`sum_ok`/`repeat_ok`/`unchecked`) | the results PDF's word boxes |
| `ratio_panel`, `formula` | derived ratios with formula id and input row ids | computed from fin lines |
| `kpi_series` | company-stated KPIs (order book, AUM, EBITDA/t, NIM, mixes) with period, dimension, `entity` (the company or the named subsidiary, kept apart from `basis`; T-088), quote, page | decks, results, press releases, transcripts |
| `transcript_statement` | call quotes with speaker, role, topic tags, named entities, answer-turn id (T-164) | transcripts |
| `transcript_question` (T-164) | analyst questions per call (analyst, firm, question, topics, entities) + `analyst_question` view | transcripts |
| `guidance` | one row per forward target: metric, period, low/high (NULL for a worded target), unit, revision link | transcripts, decks, results, press releases |
| `shp_category`, `shp_holder`, `shp_pledge`, `share_capital`, `dividend_event`, `price_delivery`, `valuation_daily` | holdings by category with the share count the printed percentage is on, the named holders, the promoter pledge block, share count, dividends, prices, PE/PB/EV | exchange data stores |
| `bulk_block_deal`, `insider_trade`, `index_price` (profile builds, T-056 loop 2) | bulk/block deals and SEBI insider trades per company (none held = no rows); the stock against `Nifty 50` (and a profile's `extra_indices`) per trading day with 1/3/6/12-month relative return in points | `equity_intelligence.db` + price rows |

Tools: `pilot3_fin`, `pilot3_ratio`, `pilot3_kpi`, `pilot3_guidance`, `pilot3_statements`, `pilot3_search` (bm25),
`pilot3_semantic` (dense page search, T-154; paid query gate, vectors in the store's `embed/`), `pilot3_docs`, `pilot3_holding`, `pilot3_tech` (section 9i), `pilot3_sql`; `schema` / `catalog` know the `pilot3` db.

## 3. Extraction methods (what works, what failed)
- **Documents**: collected per company into `D:\RealityEngine\pilot3\pages.db`. Dates: `known_at` = exchange
  dissemination time; a transcript is never known before the call date printed in its first pages (`call_dates.py`),
  and a transcript re-filed years after its call is dated by that printed date in the collector
  (`docs_collect.reconcile_doc`, section 9m).
  Order wins filed as generic press releases are retyped by headline.
- **Identity before extraction (T-093, 6 Nov 2026)**: every document is checked first for company, fiscal year, type
  and date (`reality_engine/pilot3/doc_identity.py`), because the stored BSE label and the file disagree often: 68
  annual-report rows carry the Newspaper Publication category, and 20 of the KEC/MARUTI "transcripts" are one-page
  notices that the transcript is on the website. `resolve_file` finds a file by stored path, then by sha256 across the
  raw store's sha-named folders and the Drive archive index; a row only in `gdrive:InfoDiffusion_archive` is
  `on_drive` and only a capped sample (50 files) is fetched, never bulk. `docs_collect.collect(set_aside=...)` and
  `registry.build_doc` skip a set-aside sha and leave the document in the store, flagged. On all documents of the ten
  companies (831 rows, 6 processes): 107 ok, 25 set_aside, 3 unknown, 78 on_drive, 618 not_held (481 have no hash at
  all), 4.5 s (5.4 s per 1,000); the Drive sample fetched 10 files in 29.5 s (2.95 s/file). A 2,000-row sample
  stratified by type (seed 20261106) projects the table: ok 15,151, set_aside 1,083, unknown 64, on_drive 255,
  not_held 110,699; 13 of its rows are transcript cover letters (828 projected, each a call with no transcript held),
  11 of the 13 print a link; 10 of its 934 hashed rows are truly missing (their folder was listed and has no file) and
  664 (42,318 projected) sit in folders never listed, so `not_indexed` is not `missing`.
- **Page text**: 96% of pages have a text layer (22,589 of 23,558). OCR only the rest (969 pages; HP TextRecognizer
  ~116 pages/min, MSI RapidOCR ~4 pages/min: OCR runs on the HP).
- **Financials**: from XBRL, labelled with basis and definition; tools default to consolidated (a standalone EPS was
  once returned for a consolidated question). Both company-stated and audited figures are kept, each labelled
  (Hindalco FY26 operating cash flow: 10,250 cr XBRL vs 21,858 cr company bridge). Since T-088 one line and period
  has ONE `preferred` figure: the newest filing known at `as_of`, labelled `restated` when it differs from the first
  printing, with the other values in `alternatives` carrying their filing date, role and check status.
- **KPIs**: rule-based readers for sentences, tables (columns mapped to period headers), charts, segment-mix tables
  (`mix_v1`), entity headings (consolidated / standalone / subsidiary). Lexicon families in `pilot3/lexicon/`
  (common, lenders, metals, orders, dimensions, topics; one file per sector since loop 3: `bank`, `insurance_life`,
  `it_services`, `pharma`, `fmcg`, `auto_oem`, `consumer_internet`). A sector file declares `sectors: [...]` and an
  entry applies only to companies of those sectors in a `--profile` build (no profile, the pilot3 three: only the
  families marked `no_profile: true` — lenders, metals, orders — apply, exactly as before). An entry may also carry
  `strict` labels: the sentence reader uses those when given (the value must follow the term, so "deposits ... margin"
  chart fragments yield no row) while table rows keep the plain `labels`. Period rules: a period can never start
  after its document's date ("June 26, 2019" was once read as June 2026); a later deck restating an earlier quarter
  keeps that quarter; a results table's bare dates are relabelled from the group headings above them ("Quarter
  ended | Half Year ended | Year ended"), so a half-year column over 30.09.2026 is `H1FY27`, not `Q2FY27` — the
  group is the contiguous run of columns a heading is centred over and the year-to-date block starts where a column
  repeats the first column's date (Q2FY27 and H1FY27 both end 30.09.2026), so a 31.03.2026 column under "Quarter
  ended" is `Q4FY26`, not `FY26`, and only the first quarter column of a results table is read (the prior quarters
  print in their own results). Under a `--profile` build a row whose period ends before `window_start` minus one
  year is history and is dropped (`period_before_window`), and a table value must be a whole printed token (the
  `791.0` inside `7,791.02`, the `0,37` decimal comma), a percentage at most `max_pct` (100 unless the entry says
  otherwise), a day count at least one, and never a signed or negative count/money level; a row printing more values
  than its table has columns is dropped (`column_mismatch`). The sentence reader refuses a value whose label sits on
  another line with another label in between (a fact-sheet block), reads `from X to Y` as Y and `by N ... to/at M`
  as M, does not treat the token after "compared to" as a second period, and refuses "impacted by", "larger than
  $50 mn" and "$50 mn plus clients". On the pilot10 base (`l3_base.db`, A1 651/898) the loop-3 lexicons took A1 to
  676/898 and the 4 Nov fix round to 677/898; the 5 Nov precision round 2 (outlier gate, long-document defaults,
  table label ownership, sentence guards, trillion/USD units, `debt_to_equity` split) measures 674/898 on
  `D:\RealityEngine\pilot10\scratch\w_kpi5.db` — above the 651 baseline, with BAJFINANCE 70 (baseline 71) and
  HINDALCO 67 (baseline 69) the only companies below it (ETERNAL 68, HDFCBANK 75, HINDUNILVR 74, INFY 65, KEC 51,
  MARUTI 61, SBILIFE 75, SUNPHARMA 68); outlier groups fell 28 -> 10 and the review rows per company and the
  seed-20261109 hand read (KEC 16, BAJFINANCE 14, HINDALCO 15, HDFCBANK 14, SBILIFE 17, INFY 19, SUNPHARMA 20,
  MARUTI 15, HINDUNILVR 18, ETERNAL 15 of 20 right) are in `w_kpi5_kpi_review.csv` and the DEVELOPER_GUIDE O2
  bullet. `test_pilot3_kpi.py` 53 passed, `test_pilot3_core.py -m "not slow"` 29 passed, checkpages 314 checked /
  145 found (KEC 29, BAJFINANCE 59, HINDALCO 57), so pilot3 is unchanged. The 4 Nov precision round 3 (T-061) on `w_kpi6.db` (fresh copy of `combined2.db`) measures A1 727/898 — BAJFINANCE 77, ETERNAL 67, HDFCBANK 80, HINDALCO 75, HINDUNILVR 77, INFY 66, KEC 64, MARUTI 76, SBILIFE 74, SUNPHARMA 71 — with KEC (64 vs 66) and HINDALCO (75 vs 76) below their baseline; the same build's seed-20261111 hand read of 20 rows per company scored KEC 18, BAJFINANCE 17, HINDALCO 12, HDFCBANK 16, SBILIFE 16, INFY 5, SUNPHARMA 14, MARUTI 15, HINDUNILVR 12, ETERNAL 16, so only KEC reaches 18/20 (`test_pilot3_kpi.py` 66 passed, checkpages 145). The T-064 three-fault round (4 Nov 2026) on `w_kpi7.db` (copy of `w_guid2.db`, all ten rebuilt once) fixes the segment-table total, the debt amount read as `net_debt_to_ebitda`, and the Q4 twin of flow ratios: A1 728/898 — BAJFINANCE 77, ETERNAL 68, HDFCBANK 81, HINDALCO 75, HINDUNILVR 77, INFY 66, KEC 64, MARUTI 76, SBILIFE 73, SUNPHARMA 71 — with KEC (64 vs 66) and HINDALCO (75 vs 76) below the combined3 baseline; both losses reproduce on a fresh build of the pre-T-064 `kpi.py` (the combined3 copy held KEC `order_intake` H1FY27/Q2FY27 and HINDALCO `copper_cathode_volume_kt` Q1FY27 rows that a fresh build does not). The seed-20261113 hand read of 20 quoted rows per company scored INFY 12, HINDALCO 7, HINDUNILVR 18 of 20: the 14 INFY segment rows, the HINDALCO debt-as-ratio rows and HINDUNILVR's "EBITDA as a % of TO" / Q4 ROE rows are gone, and the remaining misses are USD tables read as crore, six-month figures dated to the quarter, the year token "2026" read as revenue, capex commitments, and Novelis/business-segment income stored as the company total. `test_pilot3_kpi.py` 71 passed; `checkpages run` measured 139 (KEC 24, BAJFINANCE 59, HINDALCO 56) and also 139 with the pre-T-064 `kpi.py`. The T-066 KPI branch-line round (5 Nov 2026, `kpi.py` only, no lexicon change) restores the six numbers round 3 lost with two general rules: "YTD"/"till date"/"to date" are period qualifiers, not plan words (a first quarter's YTD intake is that quarter's intake), and a YTD flow takes the half-year/nine-month period its document reports (`_ytd_period`: Q2 -> H1FY, Q3 -> 9MFY; a stock such as an order book keeps its date), while "would" hedges a stated level but "will" still commits. `checkpages run` measures 145 again (KEC 29, BAJFINANCE 59, HINDALCO 57); 13 rows are added across the 314 checked pages and none removed (11 KEC, 2 HINDALCO, 0 BAJFINANCE); `test_pilot3_kpi.py` 72 passed. The rebuilt `w_kpi8.db` (copy of `w_kpi7.db`, KEC built once) measures A1 728/898 with KEC 64 and HINDALCO 75, the same totals as `w_kpi7.db`: KEC's `order_intake` now holds H1FY27 (3), H1FY26 (2), 9MFY26 (6) and Q1FY27 (13) rows beside FY26, so the H1FY27/Q2FY27 dev questions stay unmet for other reasons.
- **KPI goal-brief round (T-079, 5 Nov 2026).** The first round run from a goal rather than an edit list: one KPI build of the ten pilot10 companies on a `sqlite3` backup (`D:\RealityEngine\pilot10\scratch\w_t079.db`), every rule general and no company name in code, acceptance by a 20-row hand read per company. It reaches **INFY 18 of 20** (was 7) and **MARUTI 18** (13), lifts KEC 14 (13), HINDALCO 13 (9), SBILIFE 17 (16) and HINDUNILVR 16 (15), and leaves BAJFINANCE 12 (16), HDFCBANK 11 (14), SUNPHARMA 12 (15) and ETERNAL 3 (6) below their before read; HINDALCO does not reach 18. `checkpages run` 145 (KEC 29 / BAJFINANCE 59 / HINDALCO 57, unchanged), A1 759/898 with every company at the live level, `test_pilot3_kpi.py` 79 passed. The rules (USD table caption at the row, commitments and components, investee "Other Matter" and comparative labels, six/nine-month spans, worded quarters and OCR "FV"/"Q", bare-quarter and period-pair dates, group headings on the header row, year tokens and footnote markers, "grew by z" as a change, TTM and segment-EBITDA tables, subsidiary release titles and investee names) and the stopping rows are listed in DEVELOPER_GUIDE O2; the self-inflicted one is a "Statutory Reports" heading read as an entity name ("statutory" basis on 8 sampled rows), fixable with a section-word stoplist. Evidence: `.tmp/kpi_before.tsv` (124/200) and `.tmp/kpi_after.tsv` (134/200).
- **T-079 round 2 (5 Nov 2026).** After round 1's four regressions, one more rule round on the same copy (one 10-company build, 238 s). The report-section/issuer confusion is fixed structurally (a release title must say what was reported, and the entity words moved to `lexicon/page_entities.yaml`), net cash is stored as negative net debt, acquisition cash and "free cash flow before capex" are refused, the mix title needs a mix word, the market-cap caption is not the metric, "quarter ended 31 March" defaults to Q4, a short line of numbers is a table row, and a margin near one segment is that segment's while two or more keep it the group's. `checkpages run` 145, A1 759/898 with every company at live, `test_pilot3_kpi.py` 82 passed. Same-seed read: no company below its before read (KEC 13, BAJFINANCE 18, HINDALCO 10, HDFCBANK 14, SBILIFE 16, INFY 12, SUNPHARMA 16, MARUTI 13, HINDUNILVR 16, ETERNAL 10; 21 wrong and 3 right rows removed). Fresh-seed read (20261111): KEC 17, BAJFINANCE 16, HINDALCO 15, HDFCBANK 15, SBILIFE 14, INFY 17, SUNPHARMA 16, MARUTI 16, HINDUNILVR 19, ETERNAL 15. **Stopping rows for HINDALCO 18:** Novelis-subsidiary rows still stored `total` (adjusted EBITDA 459 and 516, FRP shipments 916), the Oswego fire impact 53 stored as adjusted EBITDA, guided capex 10,000 stored as Q3FY26 capex, and Novelis's Q4 FY26 EBITDA/tonne 544 stored FY26. **MARUTI 17:** the section-heading periods (564,669 as 9MFY26, 538,994 as Q4FY25, 696,654 as H1FY27) and the passenger-CNG share 70% stored as `market_share`. Evidence: `.tmp/kpi_fresh.tsv`, `.tmp/kpi_same_seed_judged.tsv`.
- **T-079 round 3: the eight branch regressions (5 Nov 2026).** One rule round on a fresh copy (`w_t079b.db`, all ten companies rebuilt once), no company name in code; company words stay in `lexicon/`. (1) `_ABBREV` lookbehinds are whole words (`(?<!\bRs)`), so "quarters." / "factors." end a sentence again while "Rs. 1,436 crore." still splits only after crore; `_sentence_bounds` scans for the preceding end over the whole text so the capital that starts the sentence at `pos` is visible to the lookahead. (2) A bullet mark at a line start (`•✓▪►`) bounds a sentence (`_BULLET_MARK`); a bullet sentence with no segment word takes its block's own heading (`_block_heading_dim`: a last bullet's trailing heading, else the heading above the block), while an entity page's overview bullets stay the entity's. KEC's 43,500/40,000 order book + L1 are `total`, 25,000 is `T&D`, the 10,000 block bullets are `civil`, 1,754 order intake is `total`. (3) `_entity_before` takes only a paragraph's subject — a `Limited` name followed by its predicate ("(HSL), in which the Bank holds", "is a non-deposit") or a block-heading quarter, nearest within 600 chars — never an address block or a passing mention. HDFCBANK's p279 fee income 34,875.9 is `total`, page 22 keeps HDFC Life (5.1/4.5), HDFC ERGO (3.8), HDB Financial Services (5.8), HDFC AMC (7.2/7.5/15.9) and HDFC Securities (9.6), 41460 stays `hdbfsl`; BAJFINANCE's p46 BFSL franchise/PAT keep `bajaj_financial_securities`. (4) `page_basis` gives a one-word-quarter title an issuer only when an earnings/results/presentation/call word follows the quarter and the word is not a section word: "Novelis Q3FY26 Earnings" stays `novelis`, "Revenue Q3 FY26" / "Highlights Q2FY26" / "EBITDA Q4 FY26" / "Results Q2 FY26" / "Company Q2 FY27 Earnings Conference Call" are `not_stated`. (5) `VAL_RX` cannot start inside a token (`(?<![A-Za-z0-9])`): "A320 deliveries", "B737 orders" and the insider-table token "A32071" give no number, while 1,200 / INR2,000 / 21,213.89 read whole. (6) `_FRAME`'s `H1` is not followed by a comma or digit, so the OCR rupee sign in "Net Revenues: H1,91,218.60 crore" no longer dates the HDFCBANK p83 rows: NNPA 0.38 and ROA 1.94 are FY26 (were H1FY26). (7) `_PROSE_ROW` counts is/are/has/have, so a prose line with three numbers stays readable: SBILIFE's "APE channel mix for 9M FY 26 is bancassurance channel 62%, agency channel 27% & other channels 11%" is stored again (62 9MFY26, 53 H1FY27, 47 Q1FY27, 60 FY26). (8) ETERNAL's "At a consolidated level, Adjusted Revenue grew ... to INR 16,692 crore" was a `segment_revenue_rows` row whose heading search ran past a blank line into the next section's "QUICK COMMERCE" — the search now stops at a blank line, and `consumer_internet.yaml` gives "adjusted revenue" a strict sentence label, so 16,692 (Q3FY26) and 17,680 (FY26) are `total` and the Q1/Q2 letters add 20,648 and 24,621. Results on `w_t079b.db`: `test_pilot3_kpi.py` **90 passed** (eight new cases from the real page text), `checkpages run` **145** (KEC 29 / BAJFINANCE 59 / HINDALCO 57), A1 **759/898** with every company exactly at live (BAJFINANCE 79, ETERNAL 72, HDFCBANK 84, HINDALCO 77, HINDUNILVR 81, INFY 72, KEC 64, MARUTI 81, SBILIFE 76, SUNPHARMA 73), `typecheck` no new errors. Rows: 2,070→2,065 BAJFINANCE, 189→192 ETERNAL, 671→672 HDFCBANK, 709→710 HINDALCO, 396, 305, 572→566 KEC, 123, 703→707 SBILIFE, 372. **Collateral to re-read:** the BAJFINANCE "21 FINAI strategies" page's MFI/2-Wheeler AUM 2,317/6,220 are `total` (a block heading above a last bullet); nine `mortgage`-tagged BAJ rows (CRAR/PAT of the company page) are `bhfl`/`total`; HDFCBANK's OCR "HOB Financial Services Limited" rows read `hob_financial_services`; eight HINDALCO Novelis rows whose segment word sat in another sentence are `total`. Evidence: `.tmp/build_all4.log`, `.tmp/cp_t079b_final.log`, `D:\RealityEngine\pilot10\scratch\a1_t079b.json`.
- **T-079 Opus read and merge (5 Nov 2026).** Hand read on unused seeds, not the workers' reads: branch before round 3, seed 20261205, 133 of 200 (KEC 17, BAJFINANCE 16, HINDALCO 11, HDFCBANK 9, SBILIFE 10, INFY 18, SUNPHARMA 16, MARUTI 12, HINDUNILVR 15, ETERNAL 9; the worker's 160 of 200 used seed 20261111, already used by T-061). After round 3, seed 20261207 on five companies: HINDALCO 13, HDFCBANK 12, KEC 17, ETERNAL 9, MARUTI 12 (63 of 100); samples differ and are small, so this is no measured gain. The 18 of 20 goal is not met; the branch merged for what it removes (auditor-note and investee figures, capex commitments, subsidiary figures off the company total) and for its eight fixes. Known wrong after merge: correct sentence bounds moved Novelis adjusted EBITDA rows (476, 516) from `novelis` to `total`; a loss stored positive (Novelis net income -160); subsidiary figures named only in nearby prose (HDBFSL NIM, HDFC ERGO PAT) still `total`; segment bullets (BAJFINANCE MFI 2,317, 2-Wheeler 6,220 AUM) as `total`; `hob_financial_services` is an OCR spelling of HDB; a full quarter dated to the year; sales of investments and R&D rows as revenue; question text as `market_share` or `capex`. `pilot10.db` was rebuilt with this code on 5 Nov after the T-080 grades (6,042 `kpi_series` rows, A1 759 of 898), then again with T-081c (6,054 rows, A1 760 of 898), which fixed the BAJFINANCE row.
- **T-081 wrong-class round (5 Nov 2026).** One rule round on the six classes Opus hand-read on `w_t079b.db` (sign, subsidiary figures as the total, quarter dated to the year, non-revenue lines as revenue, question/plan text as a value, auditor notes), all ten companies rebuilt once on a `sqlite3` backup (`D:\RealityEngine\pilot10\scratch\w_t081.db`, 6,044 rows against 6,108), no company name in code. Fixed and verified on `w_t081.db`: Novelis net income `-160` and India net debt `-6,000`; HDBFSL NIM 8.2 and HDFC ERGO PAT 813/500 on the subsidiary dimension, HDFC Securities book value per share 2,012 in `inr`; Novelis adjusted EBITDA 476/516 and net income 15 (including the release's continuation pages, via `doc_basis`), Hindalco (India) Business EBITDA 22,064 as `india`, consolidated EBITDA 38,097/37,217 as `total`; Eternal margins 0.6/0.9 as `hyperpure` and 5.4 as `food_delivery`; HUL PAT 2,711/3,002 and Eternal 17,680 / 0.5 / -3.0 as `Q4FY26`; Maruti volumes 696,654 `Q2FY27` and 871,276 `H1FY26`, exports 447,774 `FY26`; HDFCBANK NIM 3.34 `FY26`; all five named non-revenue lines, both question-text rows, both capex 2.5 rows, both dark-store 2,137 rows, the 50,000 EV milestone and the 20.95 NPA-concentration row are gone; the subsidiary-note PAT 2,456 is gone. Still wrong and left: Maruti's 538,994 domestic volume on the Q4 press release is dated `FY26`, not `Q4FY26`, and BAJFINANCE keeps 78 A1 questions against the live 79 (one `cost_of_funds_pct` question, its transcript row dated FY26 not Q2FY26). `checkpages run` 146 found (KEC 29 / BAJFINANCE 59 / HINDALCO 58), A1 759/898 (the other nine companies at or above their live count), `test_pilot3_kpi.py` 97 passed. Rules and lexicon in DEVELOPER_GUIDE O2; the 821 dropped / 723 added / 486 dimension-moved groups by rule, with three quotes each, are in `.tmp/t081_diff.txt` of the T-081 worktree.
- **T-081 Opus read and merge (5 Nov 2026).** Hand read on unused seed 20261209, 12 rows each on five companies: MARUTI 12, HDFCBANK 11, ETERNAL 11, KEC 11, HINDALCO 10 (55 of 60; the same companies read 63 of 100 before this round, on another seed and sample size, so a real gain but not a precise one). Still wrong in that read: a segment margin as `total` (HINDALCO 46%), an equity payment as Novelis `net_debt`, HDFC Life PAT as `total`, an assumed 12 days as working capital, a Civil order book as `total`. One accept clause failed and was accepted: BAJFINANCE A1 78 against 79, a `cost_of_funds_pct` call row dated FY26 instead of Q2FY26; also MARUTI 538,994 is dated FY26. `pilot10.db` was rebuilt with this code on 5 Nov after the T-080 grades (6,042 `kpi_series` rows, A1 759 of 898), then again with T-081c (6,054 rows, A1 760 of 898), which fixed the BAJFINANCE row.
- **T-081c period round (5 Nov 2026).** One rule round on the two wrong period classes Opus read on `pilot10.db` — a call figure dated to the year because a year phrase in an earlier sentence was read as its span, and a deck row dated to the comparison quarter of a bps change ("an improvement of 27 bps over Q1 FY26" stored Q1FY26). `reality_engine/pilot3/kpi.py` + `reality_engine/tests/test_pilot3_kpi.py`; one build of the ten companies on a `sqlite3` backup (`D:\RealityEngine\pilot10\scratch\w_t081c.db`, 6,054 rows against 6,042), every rule general and no company name in code; no lexicon change. Verified on the named evidence: BAJFINANCE `cost_of_funds_pct` 7.52 Q2FY26 (Q2FY26 call p4), 7.31 Q2FY27 (Q2FY27 call p4), 7.41 Q4FY26 (Q4FY26 call p4, a row the old build dropped), the deck rows 7.52 Q2FY26 / 7.45 Q3FY26 / 7.41 Q4FY26 / 7.40 Q1FY27 with the subsidiary pages 7.38/7.30/7.28 on the same quarters, and KEC `order_intake` 16,000 FY26 (was FYFY26); no `FYFY` label remains. `checkpages run` 146 found (KEC 29 / BAJFINANCE 59 / HINDALCO 58; fixture baseline 145), A1 760/898 with BAJFINANCE 79 (from 78) and every company at or above its `a1_rebuild.json` count, `test_pilot3_kpi.py` 102 passed. Period-level diff: 14 moved, 1 duplicate dropped, 0 added — the other moved rows are call stock/rate figures dated to the call's quarter (GNPA/NNPA 1.01 Q4FY26, provision coverage 60 Q4FY26, franchise 110.64 Q2FY26 and 124.43 Q1FY27), KEC `order_book` 1,200 FY27 -> Q1FY27, KEC EBITDA margin 7.1 FY26 -> Q4FY26, HINDALCO gross debt 12,200 `india` / 75,000 `novelis` FY26 -> Q4FY26 and SUNPHARMA market share 8.5 FY26 -> Q1FY27; the dropped row is KEC p12's "EBITDA Margin at 7.1% against 6.9%" FY25 comparator, whose same figure survives Q4FY25 on p2 and in the p18 table. MARUTI 538,994 domestic volume stays FY26 (no rule moves it, as before). The rules and the trade-off are in DEVELOPER_GUIDE O2; `pilot10.db` itself is not rebuilt from this worktree (read-only data root).
- **Speakers** (`transcripts.py`, loop 3, 4 Nov 2026): management is placed by universal rules, no company name in
  code and the `people` lexicon not extended. A participants block on the first three pages names management with
  titles (`_title_role`: cfo / md / ir / mgmt) and the analysts/journalists under their headings; the moderator's
  "we have with us today A, B and C" sentence names the management team; a bare name line (no colon) is a speaker
  mark only in a document with fewer than five real colon marks, and only for a participant name or a line repeated
  3+ times with speech after it; in the Q&A a name answering after an analyst 3+ times, never introduced as an
  analyst, is management. Analysts and journalists are never stored; an unplaceable speaker is counted in
  `unknown_speakers`. Two more rules close the 4 Nov review: a running footer whose page number changes ("External
  Document © 2026 Infosys Limited 3") is boilerplate, because the repeat count normalises digits before comparing
  lines, so it is masked and never sits in a quote; and a media call has no moderator, so the moderator-keyed Q&A
  marker never fires — when a document has no moderator, the first participant line from the journalists/analysts
  list opens `qa`. Measured on the pilot10 copy: ETERNAL 691 rows (3 management speakers, the analysts 0), INFY
  2,478 (Salil Parekh md, Jayesh Sanghrajka cfo, Rishi Basu and Nandan Nilekani mgmt, the journalists 0; all four
  calls now carry a prepared/qa split), KEC 1,803
  unchanged; HDFCBANK/HINDALCO/SUNPHARMA gained their real participants (Keki Mistry, Kaizad Bharucha, Steve Fisher,
  Dilip Shanghvi, Kirti Ganorkar, Jayashree Satagopan), BAJFINANCE/HINDUNILVR/SBILIFE unchanged, MARUTI 0 (one-page
  cover letters).
- **Guidance**: sentence rules: forward cue, metric must be the target's subject, past actuals / tariff rates / supply
  shares / net-debt sentences rejected. Loop 3 (4 Nov 2026) hand-read all 136 rows and closed nine wrong-row families:
  a bare quarter used as a backward-looking label ("Q1 results", "Q2 performance") is not the target period; "next /
  coming year" moves one year forward; a result quoted against the guided range is dropped; an amount spent to date no
  longer pairs into a range; a project's whole capital cost is `project_capital_cost`, not a year's capex; `nim` and
  `credit_cost` are read only for a lender whose profile sector is nbfc or bank; a segment's number is not the
  company's metric; `other` needs its guidance word in the number's own clause; a question is never a target; and the
  run dedupes on `(symbol, metric, period, low, high, unit, said_on)`, so BSE/NSE copies and several pages of one
  document are one row while a later restatement stays. The spend that family D masks is not lost: it is stored
  beside the total as `project_capital_spent` (low = high = the amount, unit usd_bn/inr_cr, `target_period` = the
  period the sentence names — "end of FY26" → FY26, "end of Q1FY27" → Q1FY27, "end of Q3FY26" → Q3FY26), so the total
  stays `project_capital_cost` and no annual capex answer can pick the spend up.
  A second read of all 69 rows (4 Nov review) found eight more wrong rows; seven general rules close them: an
  "impact of X on <metric>" sentence is an effect, not a level (`IMPACT_OF_ON`); a hedge ("difficult to quantify") is
  no target (`HEDGE`); "have been spending" is past while "have been talking about 12-15%" is still guidance
  (`PAST_ONLY`); a place's share of a split total ("INR1,000 crores in Orissa and INR600 crores would be in MP") and a
  market's growth ("China is a large, growing market … 5-7% growth") are not the company's number (`PLACE_IN`,
  `MARKET_OWNS`); "27% of a combined business" is a share (`SHARE_NOUN`); and "remains at ~$500/t" with no guidance
  word before the number is the actual, while "the AUM growth estimates … remain at 24 to 25%" keeps its row
  (`REMAINS_AT`). The one leftover loop 3 reported was settled by T-062: HINDALCO's "cost of production in the Q2
  level" row now carries `Q2FY26` (the quarter the sentence names), and `checkpages` still holds 145 / 314 because
  it matches the value and the page, not the period. Before loop 3, precision was 28/40
  (4 Nov). **T-058 (4 Nov 2026): a target said in words is a row too, and the metric the sentence does not name.**
  Ten real guidance sentences were held in `transcript_statement` with no `guidance` row; the recall rules now are:
  (a) a worded target — "high single-digit … top line growth for FY27", "the provision coverage will be in the 70s,
  mid-70s or higher", "the margins to remain flattish", "full year '27 will be ahead of full year '26" — gets a row
  with `low` and `high` **NULL** (no number is invented: "high single-digit" is never 7%), `unit='pct'`, the
  direction from the word (ahead of/better than/or higher → up, flattish/in the guided range → flat) and the exact
  quote; the worded path needs the cue, the metric **named in the sentence itself**, a magnitude or comparison word
  and a period, and it refuses a reporting verb, an actual's shape, a hedge, a macro forecast, a sentence that
  declines to guide ("we do not give forward guidance") and any metric not stated in percent; (b) "the guidance of
  60% CAGR" is `revenue_growth` (an `EBITDA CAGR` / `profit CAGR` is not, `NON_REVENUE_CAGR`); (c) "we are saying we
  will get to" is a cue (`CUE`), `full year '27` names its period (`FULL_YEAR`), "guidance" alone cues `other`
  (`OTHER_CUE`, "INR 11 lakh per day per store"), and a list of example values ("some 25 basis points, some 100
  basis points") is not a target (`EXAMPLE_LIST`); (d) a company flagged `lender: true` whose sector is not a bank or
  NBFC (a life insurer) keeps its "margin" as `ebitda_margin` instead of losing it to NIM, which it is not allowed
  to hold. **T-062 (4 Nov 2026): a growth sentence, a customer mix, a slice of a total, the quarter and a delta.**
  Five general rules close the wrong rows the review named: a growth sentence owns its number, so "we'll be growing
  for the year at around 14% to 15%" cannot take a margin metric from the visible question even when the second
  "14% to 15%" sits 200 characters past "growing" (`subject_ok` reads the whole sentence when the metric's own word
  is not in it); a life insurer's IRP/APE is its top line (`revenue_growth`), a list of labelled percentages is a
  customer/business mix and not `other` ("salaried is about 40%, business would be about 34%"), and `other` otherwise
  needs a target wording or a single number; a number taken out of a stated total is a slice ("out of INR30,000
  crores … INR20,000 crores"), so the total stays the row (`SLICE_OF`); "the cost of production in the Q2 level" is
  that quarter of the filing's year (`Q_LEVEL`) and "in the next quarter" is the quarter after the call's own
  (`NEXT_Q`); a change ("Reduction of 0.75% to 1%", "a 1% point margin accretion") is the size of the change, not a
  level (`DELTA_NOUN`, `PCT_CHANGE`), a present-perfect movement ("yield on assets have come down … 30 basis
  points") is a measurement (`PAST_ONLY`), and a worded target's direction comes from its own size words, not from a
  growth elsewhere in the sentence. A product segment goes in `lexicon/dimensions.yaml` (`non_par`, `protection`) so
  "the growth in pure non-par products" is not the company's top line, and "reach 9%, 10%" is read as the pair it is
  (`PAIR_CUE`). State on the pilot10 copy after T-062 (4 Nov 2026): **90 rows** (BAJFINANCE 6, ETERNAL 11, HDFCBANK 1,
  HINDALCO 31, HINDUNILVR 3, INFY 15, KEC 13, SBILIFE 5, SUNPHARMA 5; MARUTI 0 — its transcripts are one-page cover
  letters and its decks state no forward financial target), `checkpages run` still holds **145 / 314** (KEC 29,
  BAJFINANCE 59, HINDALCO 57), A1 **709/898** with every company level, tests **28 passed**, and the hand read with
  seed 20261112 (HINDALCO 20 of 31 sampled, every other company all rows) is all right: the SBILIFE 14-15% row the
  review reported is now `revenue_growth` (or gone), and its 26-28% margin guidance stays.
  **T-166 (10 Nov 2026): whose target it is, and the two noise shapes.** The table held outside forecasts as company
  guidance: Chola's deck prints ICRA's 19-21% housing-finance AUM growth on an "Industry outlook" slide, so
  `pilot3_guidance('CHOLAFIN')` served it as Cholamandalam's AUM guidance while management guided 22-23%, and BEL's
  "variability of 25% to 31% EBITDA margins" band and an "INR120-plus million" export target read as 120 crore were
  stored beside its real 28% and five-figure-crore order intake. The round-1 version rejected a whole sentence that
  named a rating agency; round 4 scopes that to the number's own clause (`_clause`: sentence/bullet separators plus a
  table's own start, "FY26 guidance"/"Parameter"), so the ADANIPORTS release that prints India Ratings and then the
  FY26 table keeps revenue 36,000-38,000 and EBITDA 21,000-22,000, while ICRA's own "19-21%" clause still drops. A
  named agency/research house/industry body in the clause (`EXTERNAL_SOURCE`, `CARE_RATINGS`, `AS_PER_EXTERNAL`) or
  an industry/sector forecast shape anywhere in the sentence (`INDUSTRY_FORECAST`) rejects the number; the bare
  sentence before it counts only when the clause names no company actor and does not itself read as a guidance table.
  A guidance table is read as a table only when it is one (`table_targets`): a Revenue/EBITDA/Capex label sits beside
  its own amount (nothing but punctuation, a currency/unit parenthesis or a footnote digit in between, `TABLE_GAP` /
  `TABLE_AMOUNT`), at least two labels carry such an amount, the block says guidance/guided/target/parameter, and it
  names its fiscal year ("FY26 guidance"); each row then takes its own metric (`revenue`/`ebitda`/`capex`, added to
  `METRIC_UNITS`) and the table's FY. Prose that merely mentions two of the words ("Revenue and EBITDA guidance at
  ₹36,000-38,000 Cr and ₹21,000-22,000 Cr") is not a table, and the OCR "Rs 18.800-18,900" is not a corridor (a
  1000x span is rejected). Past figures stay out number by number (`past_figure`): "improved to Rs. 5,400 from Rs.
  4,200" (the movement and its base), "we have spent Rs. 4,200 crores in H1" (the spend), "had guided"/"had
  targeted"/"used to be around" (the earlier measurement), "achieved 75% of our revised guidance" (the achieved
  share) and the value before "against target of" (the target after it is the row), while a target in another clause
  ("our guidance is 7,500-8,000", "target of 16,500", "corridor of 20-24%") is untouched. A speaker is read only from
  a transcript: a deck's slide title ("International Ports", "Solid future outlook", "Capex") sits on its own line
  with a colon like a speaker label and is now None, and a duplicate statement row fills a speaker the first copy
  could not identify ("Management" kept, not lost). On a transcript page without statements the page's own labels are
  tracked across sentences (`SPEAKER_LABEL`, `INLINE_SPEAKER`), and a speaker the moderator introduced as a
  questioner (`ANALYST_INTRO`, "from the line of Umesh Raut") is never a target; statement rows with role
  analyst/moderator/unknown are skipped too. Two noise shapes go to review, not the table: an EBITDA-margin range
  wider than five points (`wide_margin`) and an order-intake value below 1% of the company's own largest
  `kpi_series` order intake (falling back to annual revenue; `order_intake_scale`). No column was added: an outside
  forecast is dropped, not labelled, because a `source_kind` column would be a schema change for rows the table
  should not hold. Measured dry run on the same copies of p20/u8/q12 (pre-T-166 extractor cf03b356 -> round 4): p20
  175→180, u8 140→133, q12 276→269 rows; 36 removed (15/8/13: the 7 ADANIPORTS table rows re-keyed to their own
  metric, outside/industry forecasts, analyst questions, past figures, wide bands and unit slips) and 27 added
  (20/1/6: the ADANIPORTS FY25/FY26/FY27 guidance tables with revenue/EBITDA/capex on their own labels, BEL's
  4,500-crore component-order expectation, APLAPOLLO's volume statements and SAIL's planned capex). Against the
  ticket's `*_before` baseline: 11 rows removed, 7 of them the same target back under its own metric, 0 management
  targets lost, 0 junk rows (the 2 APLAPOLLO volume rows are management statements), 0 speaker regressions. Tests
  **40 passed** (four new: the per-clause agency check, the real table, the past figures, the slide-title speaker),
  and every difference is listed with its quote and grade in `D:/RealityEngine/v2/review/t166_r4/r4_diff.md`.
  Independent DeepSeek review (job 20261110T104653Z-69e3cace, every row read against its page): 0 management targets
  lost, 1 junk row added (EDELWEISS FY17 product-mix margin), 0 speaker regressions; open: 3 new wrong speaker names on
  previously empty fields, APLAPOLLO FY27 20% volume guidance keyed `revenue_growth`, ADANIPORTS p52 "11%-16% growth
  guidance" missed because a table match ends the sentence, and BHARTIARTL capex 28,000-34,000 is an analyst
  describing past capex (kept in round 4 only because its brief required it).
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
| 4 Nov | loop 3: speakers + guidance precision, A1 on the pilot10 copy | A1 **662/898** (651 before; KEC 51 → 62, every other company level); statements ETERNAL 691 / INFY 2,512 / KEC 1,803; guidance 69 rows |
| 5 Nov | T-067 real answer test: 60 fixed random dev questions for each of 10 companies, MCP only, all 600 hand-read with arithmetic redone | **480 right / 116 partly / 4 wrong (80.0%)**; misses: 44 worker misread, 31 worker sums or units, 24 not held, 21 store defects (T-072, T-073); direct 85%, two-step 77%, ripple 71%; supersedes the lenient first pass of 107/120. Report `D:\RealityEngine\reports\2026-11-05_answer_test_600.html` |
| 5 Nov | T-080 re-run: same 600 questions with `pilot3_calc`, `number_check` and the T-073 store fixes, all hand-read | **464 right / 136 partly / 0 wrong (77.3%)**; misses: 89 worker misread, 19 not held, 18 sums or units, 10 store defects. 58 answers moved to right and 74 to missed, so a 16-answer gap is within run-to-run change (about 1.4 standard errors); of 14 sampled new misses, 11 were really worse answers and 3 a stricter reading. Best case if every misread and sum is fixed: 571 (95.2%). Grades `D:\RealityEngine\pilot10\answer_a3\grades.tsv`; report `D:\RealityEngine\reports\2026-11-05_answer_test_rerun_600.html` |
| 8 Nov | T-124 re-ask of the 136 partly answers on live pilot10.db (two DeepSeek workers, p3ask, blind to old answers), all hand-read | **64 right / 70 partly / 2 wrong**; pilot set now 528 / 600 (88.0%). Misses: 34 misreads (many repeat 5 Nov: after-close day 0, TTM vs FY overlap, annualised RoEV, swapped utilisation labels, standalone vs consolidated), 18 not extracted (pledge and holder tables empty), 8 sums or units (one ten-times crore slip passed the number check), 5 raw missing, 5 not disclosed. Report `D:\RealityEngine\reports\2026-11-08_t124_reask_136_partials.xlsx` |
| 4 Nov | loop 3 fix: `project_capital_spent`, seven review rules, footer/media-call speakers | `checkpages run` **145 / 314** (29 / 59 / 57) — the fixture baseline; statements INFY 2,478; guidance 67 rows (5 of them the project spend); A1 662/898 held |
| 4 Nov | T-058 guidance recall: worded targets (low/high NULL), insurer margin, CAGR, store-day KPI | guidance **67 → 83 rows** (BAJFINANCE 6, ETERNAL 4, HDFCBANK 1, HINDALCO 31, HINDUNILVR 3, INFY 14, KEC 14, SBILIFE 5, SUNPHARMA 5, MARUTI 0); A1 **694/898 held** (every company level); `checkpages run` 145 / 314 held; tests 26 passed; hand read 69 / 72 |

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

### Model against store: T-084 and T-087 (6 Nov 2026)
Same store, 82 of 180 questions on INFY, ETERNAL, BAJFINANCE. Opus read of 20 random pairs: Opus 17 right, DeepSeek 11. DeepSeek grade of all 82: Opus 76, DeepSeek 51. DeepSeek with no call limit on 20 of its misses: 6 right, 12 partly, 2 wrong, against Opus 16, 4, 0; no raw file was needed, and it made more lookups than Opus (about 10.6 against 8.2). So the gap is not call count. Reasons for its 14 misses, sorted by hand and untested: 4 stopped at a table that looked complete, 4 competing or mislabelled rows, 1 bad data outside the pilot, 5 misread an open page. Direction set by Shivam: store the facts so a cheap model matches Opus. Report `D:\RealityEngine\reports\2026-11-06_deepseek_dig_test.html`; data `D:\RealityEngine\pilot10\answer_t084`. Found in the build: `parse_shp_xbrl` drops named holders and pledge flags held in the SHP files; the window deletes quarter end 2025-09-30; the main store copies the prior day onto holidays (T-089).

Re-test after the T-088 fixes on the rebuilt `pilot10.db`, same 20, same read design: DeepSeek 8 right, 12 partly, 0 wrong (before 6, 12, 2); Opus's unchanged answers 13, 7, 0 on this read (16, 4, 0 before), so a move of 2 is within read noise. Brief rewritten, with a line naming the ten-company coverage, so not a clean store test. The named-holder and pledge tables reached the answers. The preferred-figure fix did not on BAJFINANCE-001: `pilot3_fin` returns the right Q2 FY26 base (19,992.38 crore, preferred, restated) but the worker read the competing rows through `pilot3_sql`, and raw SQL was 77 of its 126 pilot tool calls. So a choice made inside a tool does not reach a model writing SQL; put it in the data. A first run without the coverage line used pilot tools on 7 of 49 listed INFY and ETERNAL calls, because the server text still names three companies; discarded ungraded. Report `D:\RealityEngine\reports\2026-11-06_t088_reask.html`; data `answer_t084\dig_t088`.

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
7. Universe readiness (T-094, 6 Nov 2026): the profile is generated from the stores, not written by hand
   (`reality_engine/pilot3/make_profile.py`), so any list of symbols or ISINs builds with no code change. Of the
   universe's 5,358 active companies the exchange taxonomy places 1,638 (30.6%) in a sector family (T-133 remap,
   9 Nov 2026), 3,720 (69.4%) carry no family (3,309 of them with no `company_industry` row at all, mostly BSE-only;
   the BSE scrip master is a 420-byte Access Denied page, so they stay `unknown` and are reported, never guessed).
   Trying the symbol and the historical ISINs rescued 14 labels (2 families); `master_companies.industry` is usable
   for only 495 (9.2%) and clean-maps 135, adding 64 companies. The five companies never used to write a rule
   (DALBHARAT, POWERGRID, TATAELXSI, APOLLOHOSP, DLF) all fall in the unknown group: their sectors have no lexicon
   family yet, which is the next lexicon work, not a code gap. Decision 8's own segment-revenue label stays deferred.

## 7a. Build timings (MSI, 4 Nov 2026, live rebuild)
- `docs_collect` (all 3 companies, 1,999 documents): 528 s, ~3 min per company.
- `build --part all` with 4 OCR dbs: 484 s for 23,558 pages (~2.7 min per company, single process).
- After the dates + guidance merges: guidance 660 -> 329 rows (KEC 218, BAJFINANCE 52, HINDALCO 59): check recall
  on the next re-answer; kpi_series 38,851; zero Q1FY27 rows from documents known before 2026-04-01.
- **T-164 (round 8, 11 Nov 2026).** Rebuilt from the round-7 baselines: u8 24,835 statements (baseline
  24,325), q12 43,007 (39,256). Added rows are management statements only (u8 +1,043, q12 +3,775; no
  ir/moderator/analyst line among the 9 reviewed calls). Speaker rules: an IR or moderator title is never
  promoted; IR lines are no longer stored (481 baseline IR script rows removed, 462 u8 + 19 q12); a DOI block
  whose heading stands alone is read and its names keep the block role ("L Krishnakumar", "Anand Rathi"); an
  initial-led label ("G Vivek:", "S Ranganathan:") starts that speaker's turn (EDELWEISS analyst questions no
  longer run on as the chairman's statements; BEL Manoj questions 0). Management statements lost vs baseline:
  15 rows, every one carried another speaker's label inside it (CIPLA analyst questions, IDEA/EDELWEISS
  sentences reattributed to their real speaker); every one is a question now or is stored under its own
  speaker. Entities: the longest printed span wins (Capital Foods, Tata Copper Plus, SG Mart, Missile Fire
  Control System), a single token inside a longer printed name is a fragment, and generic capability phrases
  (Communication Suite, Navigation Complex System, Electronic Warfare Suite, Youngest Aircraft Fleet) are out;
  GNPA/GMV/TAM/RCC/WHRS and the learned all-caps metric words (a token beside a figure in 2+ calls and in at
  least half its uses) are out; the call's own "<Name> Pvt Limited (X)" expansion makes X that company
  (SBPL). `whole_turn` is keyed on (doc_key, answer_turn) and expands prepared remarks only when selected
  (SAIL safeguard limit=2: 32 rows, 2 turns). Seeds 9264/10264, 50 entity-tagged and 40 topic-tagged statements
  per store: entity precision 93.7% (u8 93.5/93.5, q12 98.4/89.6), topic label precision 97.3% (u8 91.8/98.6,
  q12 100/100). Named-programme recall: NGC 39/41, Virupaksha 2/2, Capital Foods 138/140, Tata Copper Plus
  8/9, SG Mart 3/3, Durgapur Steel Plant 9/13. 'other' 30.9-36.5% u8, 27.8-42.3% q12. Artifacts
  `.tmp/t164/r8_entity_<seed>.csv`, `r8_topic_<seed>.csv` (statement text + right/wrong per item). Tests:
  transcripts 22, speakers 13, kpi 108 passed + 6 errors (the sandbox refuses pytest's tmp_path directory:
  WinError 5), no-company-literals 7, guidance 32, answer_check 25, doc_identity 21, profile 8,
  lookups_pilot3 35 + 1 skipped, lookups_docs 18.
  TATAELXSI, APOLLOHOSP, DLF (window 2023-10-01, compute 2022-07-01; manifest 3,328 rows, 2,111 `ok`):
  `docs_collect` 270 s -> 2,091 docs / 28,566 pages / 218.7 MB; `build --part all` 814.8 s -> 151.2 MB. Parts:
  comparatives 405.6 s, extract 258.3 s, stores 113.8 s (repeat 59.9 s), notes 22.8 s, pages 6.9 s, guidance 5.1 s,
  segments 0.8 s, ratios 0.7 s, registry 0.5 s, preferred 0.3 s. `kpi_series` 1,003 (46-623 per company: all five
  sectors are `unknown`), `transcript_statement` 5,773, `fin_quarter_printed` 11,200, `fin_quarter_xbrl` 2,085,
  `fin_annual_line` 2,775, `shp_*` 0 for APOLLOHOSP (no SHP files held), `concentration` 0 for all five.
  `scale_report --fixed stores=6`: **311.8 h on one process, 52.0 h on 6, 501 GB for 6,940** (74.0 MB/company);
  these are large companies (market cap 46,445-3,39,891 crore; 2,183-11,125 pages), so it is an upper bound.
  Stores fixed cost measured on 1/2/5 companies: 16.4/27.9/59.9 s -> ~5.9 s fixed + ~10.8 s per company; the
  earlier 65.5 s for 2 vs 154 s for 10 was cold-cache I/O, not a whole-store CPU read.

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
`window_start`, `price_start` (optional, default `2019-01-01`), and `companies` (`symbol`, `name`, `bse_code`,
`isins`, `sector`, `lender`). The committed
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
  `fin_annual_line.period_end`, ...); the shareholding tables are the
  exception (T-088): `shp_category`, `shp_holder` and `shp_pledge` keep every quarter from `compute_start`, because
  the percentage base and the pledge history are answers, not inputs. The price tables are the other exception
  (T-155): `price_delivery`, `index_price` and `valuation_daily` keep their rows from `price_start`, which defaults
  to 2019-01-01 and may only be set later, so five-year price and P/E ranges survive a window whose documents start
  at `window_start`; a valuation day whose PE/PB/EV inputs are not known keeps its close and market cap with NULL
  ratios. Documents come from the manifest, which is the requested window. No profile: no filter.
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
  `price_delivery` 516 (min 2025-10-01; T-155 now keeps prices from `price_start`, 2019-01-01 by default), `shp_category` 180, `kpi_series` 161. MARUTI's five `concall_transcript`
  filings are one-page cover letters ("the transcript ... has been uploaded"), so `transcript_statement` and
  `guidance` are 0 for it: the documents, not the code path (the KPI extractor reads the same pages: 161 rows).
- **Tests.** `reality_engine/tests/test_pilot3_profile.py` (8 tests: the committed profile, the no-profile
  defaults, a manifest -> pages -> registry/pages/kpi/transcripts/guidance build with a sandbox root that does not
  exist, the window filter, `--symbols` scoping, `lookups_pilot3` on a `REALITY_PILOT3_DB` database, and
  `compute_start` / `extra_indices` / `price_start`). T-155's price-window behaviour is pinned in
  `reality_engine/tests/test_pilot3_price_window.py` (a 2020 price/index/valuation row under a 2023-10-01
  `window_start`, NULL ratios without inputs, the `price_start` refusal, and the disjoint `price_delivery_input`).

- **Generated profile (T-094, 6 Nov 2026).** `reality_engine/pilot3/make_profile.py` writes a profile from symbols or
  ISINs, so the company facts are looked up, never hand-written:

      python -m reality_engine.pilot3.make_profile DALBHARAT POWERGRID --name unseen5 --root <dir> [--raw-root <dir>] \
          --window-start 2023-10-01 --compute-start 2022-07-01 --out <profile.json> [--check-db <built.db>]

  `name`, `bse_code` and the ISINs come from the stores; `sector` comes from `company_industry`, joined by ISIN,
  through `reality_engine/pilot3/sector_map.yaml` (kept beside the code, not in `lexicon/`, because every yaml there
  is read as a KPI lexicon). Every ISIN a company has held is gathered from `symbol_isin_history`, `isin_rekey_log`,
  `corporate_documents`, `shp_index`, `results_xbrl.filings` and `master_companies` (same symbol or BSE code), and
  kept only when it is the same issuer (first 7 characters match, or the IN9 partly-paid form of the INE ISIN) or a
  recorded rekey: for the ten the generated set equals the hand profile's set, so no older filing is filtered out.
  The map lists all 191 basic industries of `company_industry`: 135 map to one of the 27 families the label
  dictionary carries (T-133, 9 Nov 2026: the ten lexicon families plus cement, retail, airlines, paints_chemicals,
  consumer_durables, jewellery_lifestyle, hotels, ports_logistics, mining, tyres_auto_ancillary, telecom,
  asset_management, metals_ferrous, utilities_power, healthcare_hospitals, realty and textiles_home) and 56 are an
  honest `unknown` (common lexicons only). By ISIN that is 1,620 of the 2,041 labelled ISINs (79.4%) in a family and
  421 (20.6%) honest unknown; across the 5,358 active companies 1,638 (30.6%) are in a family (1,565 by current ISIN,
  9 by a historical ISIN, 64 by the master-industry tier), 3,720 (69.4%) are unknown and 3,309 (61.8%) have no
  `company_industry` row at all. The label is looked up by every ISIN and then by the
  symbol (that rescue added 14 labels, 2 of them families); `master_companies.industry` is a second tier only where
  `company_industry` has nothing, and only for names that map cleanly (Information Technology, Fast Moving Consumer
  Goods, Construction, Capital Goods; it is usable for just 495 of 5,358 active companies, 9.2%).
  `master_companies.sector` is not used: 6,443 of its 6,940 rows are null, "General Diversified" or "Other". A
  company with no label is `unknown` and is printed with its taxonomy label (or `none`), never guessed from its name.
- **Lender.** `lender` is the taxonomy's own list (banks, NBFC, housing finance, microfinance, life and general
  insurance), independent of whether a lexicon family exists; `reality_engine/pilot3/lender.py` holds the filed-line
  test (`interest_income` / `interest_earned` / `gross_premium` / `net_premium` in `fin_quarter_xbrl`), used by
  `lookups_pilot3._is_lender`, by `make_profile --check-db` and by `profile.is_lender` when no profile is active
  (the default database's filed lines replace the old `ratios.LENDERS` list). The profile itself cannot run that
  test: it is written before the database it will build, so the flag comes from the taxonomy and the second check
  runs after the build (0 disagreements on `pilot10.db` for the ten).
- **Ten against the hand profile.** All ten sectors and lender flags match except SUNPHARMA (`unknown`, because
  `company_industry` holds no row for its symbol or any of its ISINs); names are the legal `Limited` form from
  `master_companies` instead of the hand's `Ltd`; BSE codes, ISINs, lender flags and the window match. The earlier
  scaffold lost six companies' legacy ISINs (KEC `INE389H01014`, HINDALCO `IN9038A01010`, HDFCBANK `INE040A01018`,
  BAJFINANCE `INE296A01016`, INFY `IN9009A01011`, SUNPHARMA `INE044A01010` / `INE044A01028`) because it read only
  master + `symbol_isin_history`; the store gatherer above restores them, and the guard test asserts every hand ISIN
  is present and no other issuer's ISIN enters.

- **Segments part.** `build --part segments` (after `extract` in `all`) runs `pilot3/xbrl_segments.py` for the
  profile's companies from the raw XBRL named in `results_xbrl.db.filings` (about 1 s for 10 companies); it needs no
  pages. First run on the pilot10 copy: A1 571 -> 601 of 898, `kpi_series.segment_revenue` and `segment_ebit` no longer
  unmet. Test: `reality_engine/tests/test_pilot3_xbrl_segments.py`.

### 9a. Compute-only history, bank and insurer lines, three new tables (T-056 loop 2, 4 Nov 2026)

- **Superseded direction (Shivam, 4 Nov, T-057):** the older quarters above are printed in the held results tables as QoQ and YoY comparatives, so they need no download. **T-073 (5 Nov 2026):** the pilot10 profile now sets `compute_start='2024-07-01'`; the older quarters are already held in `results_xbrl.quarterly`/`filings` (INFY 64, HDFCBANK 63, MARUTI 60, ETERNAL 44, KEC 63, SBILIFE 7 filings), so no fetch is needed. KEC's earlier ISIN (`INE389H01014`, 49 filings to Dec 2024) and SUNPHARMA's (`INE044A01028`) were added to the profile's `isins`; the stores filter by the profile's ISIN list, so their pre-2025 quarters had been invisible.
- **`compute_start`** (optional profile key, default = `window_start`, so nothing changes): rows of `fin_quarter_xbrl`,
  `fin_annual_line` and `price_delivery` dated from `compute_start` up to `window_start` move to `<table>_input` at the end
  of `--part stores` (`stores.apply_window`). `--part ratios` reads them through TEMP views named like the tables
  (`main.t UNION ALL main.t_input`), computes, drops the views and deletes `ratio_panel` rows dated before
  `window_start` (`stores.trim_derived`). T-155 (9 Nov 2026): the price tables keep their rows from `price_start`
  (2019-01-01 by default), `valuation_daily` is cut at `price_start` instead of `window_start`, and the
  `price_delivery_input` copy stops at `price_start` so the union never lists one day twice. The
  inputs are only already-held XBRL and price rows, nothing is fetched. Measured before T-155: `--part ratios` re-run gave
  byte-identical `ratio_panel` (1,815 rows) and `valuation_daily` (2,651, min 2025-10-01). Those two figures and that
  min date are stale after T-155: a rebuilt `valuation_daily` starts at `price_start`, so it holds more rows, and the
  days before the first known quarter have close and market cap with NULL PE/PB/EV. Point in time stays exact: a day's
  TTM uses the last four quarters
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
- **Share count**: every quarter end takes the exact `shareholding_pattern` total of `shp_category`
  (`source_kind='xbrl'`, `known_at` = the SHP's filing) into `share_capital` (`source_table='shp_category'`), written
  beside the paid-up/face-value row (T-073): SBILIFE 5 quarters (1,003,405,073 at 30 Sep 2026), ETERNAL 9,650,350,647,
  HINDUNILVR 2,349,591,262, HINDALCO 2,247,226,523. `ratios._share_count` (book value) and `valuation_daily` prefer the
  pattern row visible by the day and fall back to the rounded paid-up division only before that filing; `pilot3_holding`
  returns the same row. `valuation_daily` uses the basis that has both a share count and a quarterly statement
  (standalone for a company that files no consolidated one, SBILIFE; T-073).
- **Ratios**: half-year point-in-time ratios (`book_value_per_share`, `roe`, `roa`, `roce`, `net_debt_to_ebitda`, days, ...) are
  also written under the quarter label (`Q2FY27`, same value and formula; the NIM is a period measure and is not copied);
  `cost_to_income` (F_COST_INCOME, banks); `dividend_payout_pct` uses one DPS per fiscal year (the corporate-action sum wins over
  an annual-report figure); a zero `dividend_yield_pct` is written only when no dividend was declared in 12 months and the last
  filed annual cash flow shows none paid (ETERNAL).
- **New tables**, read by ISIN (every ISIN the company has had), no placeholder rows: `bulk_block_deal` (2 to 14 rows for BAJFINANCE,
  ETERNAL, HDFCBANK, HINDALCO, HINDUNILVR, INFY, SBILIFE, SUNPHARMA; none for KEC and MARUTI, which the store holds nothing for after
  23 Sep and 14 Jul 2025), `insider_trade` (INFY 363, BAJFINANCE 34, HINDUNILVR 7; the store holds no PIT rows after the window start for
  the others), `index_price` (measured before T-155: 268 days per company against `Nifty 50`; it now starts at
  `price_start`). `relative_return_*` = stock return (split-adjusted close) -
  index return, in points, null when the lookback day is before `price_start` (T-155; before it, `compute_start`
  else `window_start`). INFY 12 months to 3 Nov 2026:
  1,148.1 / 1,485.5 = -22.71%, Nifty 50 23,810.85 / 25,763.35 = -7.58%, relative -15.13 points.
- **Measured** (this MSI, copy of the pilot10 database, 10 companies): `--part stores` 140 s, `--part ratios` 1.4 s. A1 on `dev.jsonl`
  571 -> 679 of 898 questions fully answerable; 137 of the 147 listed structured needs are now met. Still unmet: KEC and MARUTI deals and
  ETERNAL, HDFCBANK, HINDALCO, SUNPHARMA insider trades (nothing held after 2025-10-01), HDFCBANK `nim_pct` Q2FY27 (needs interest-earning
  assets, not in the results XBRL; the loan book is not the bank's NIM base), SBILIFE and SUNPHARMA `pe` and SUNPHARMA `ev_ebitda` on
  2025-11-03 (the XBRL store holds those two from the quarter ended 2025-03-31, so four known quarters exist only from Jan/Feb 2026).
- Without a profile nothing changes (bank/insurer annual rows, restated EPS, payout selection, quarter-labelled copies, zero yield and the
  new tables are built under a profile only); `checkpages run` stays at 145 found.

### 9b. Printed comparative columns (T-057, 4 Nov 2026; fix round 5 Nov 2026)

- **`fin_quarter_printed`** (`schema.py`, 23 columns, index `ix_fqp` on `(symbol, basis, line_item, period_end)`): one row per cell
  a quarterly results table prints -- `period_start`, `period_end`, `fiscal_period` (`Q2FY27`; `H1FY27`/`9MFY27` for ytd; `FY26` for a
  year), `period_type` (`quarter`/`ytd`/`fy`), `column_role` (`current`, `preceding`, `year_ago`, `ytd`, `prior_ytd`, `last_fy`),
  `basis`, `statement`, `line_item`, `caption`, `value` (rupees, `unit` `inr` / `inr_per_share`, `scale` 1.0), `raw_token` (the printed
  words), `quote` (the printed row), `doc_key`, `page`, `known_at` (= `doc.known_at`, `known_at_source` `doc.known_at`),
  `check_status` (`xbrl_ok` / `sum_ok` / `repeat_ok` / `unchecked`), `check_detail` (`repaired`, `scale from XBRL`, `derived`,
  `header_used`, `bracketed costs`, `period from filing date`), `is_reported`.
- **The part** `reality_engine/pilot3/comparatives.py` (`--part comparatives`, after `stores`, before `ratios`; in `all` only under a
  profile) reads every `results` document of the `--symbols` companies. The table is created with `CREATE TABLE IF NOT EXISTS` (new
  `schema.ensure`) and only the named symbols' rows are deleted -- `schema.create` would drop every company's rows (the HANDOFF 4 Nov trap).
- **Reading.** Page word boxes (`page.get_text("words")`), rotated by the page's own `rotation_matrix` first (MARUTI's 2026-01-28/04-28 and
  INFY's 2026-01-14 print sideways; an empty page is listed for OCR, never guessed), rows by y-centre within 3.5 pt (as `kpi.py:1538`),
  column anchors from the x1 every column's numbers end at, numbers merged only when adjacent fragments belong to one printed token
  (`20,21 1` -> 20,211; a lone dash never merges), every numeric word binned by x. A page must carry a title with "results" (fuzzy:
  `Rcsulls`/`R6ulis` still count), no US-dollar unit, no auditor's report, cash-flow/equity statement, segment heading, non-IFRS
  reconciliation or `Less:` line before a profit line in its head, a header of period words and 8+ rows of 3+ numeric columns; a
  continuation page with no title inherits the previous page when the x-bins match and at least one line item is shared. It must carry
  a P&L shape -- an income and a profit line (a long statement table of 12+ numeric rows whose few readable lines are P&L lines counts
  too, MARUTI's badly scanned consolidated page). A row printed with 2+ of its 3+ cells is kept; a percentage or `margin` label never
  maps to a rupee line. Labels sit left or in the middle (HINDUNILVR) and are matched by `lexicon/results_lines.yaml` (longest pattern
  wins; OCR-tolerant ordered tokens and single words, `Baic` -> basic; no company names -- guard A5).
- **Roles and units.** The current period end is the latest quarter end the header/title prints on or before the filing day; a header the
  OCR destroyed falls back to the latest quarter end at most 60 days before the filing, kept only when XBRL or the page's own arithmetic
  confirms a cell (`period from filing date`). The role pool depends on that period end and the column count (`_role_set`, T-073): a
  Q2/Q3 table is a quarter pair + half/nine-month pair, plus `last_fy` at five or six columns; a Q4 table is the quarter pair + two full
  years. Quarter roles are permuted over the quarter columns and the ytd/year roles over the rest; the permutation the printed month/year
  supports best wins and the layout order breaks a tie (HDFCBANK's year-ago column misreads `39.09.2026`; HINDUNILVR prints the year-ago
  second; a Q2/Q3 header that says `Three months ended ... Six months ended` is `current, year_ago, ytd, prior_ytd` [+ `last_fy`]).
  Values are matched to columns monotonically (`_assign_tokens`, T-073): a cell missing from the middle (a merged or OCR-split number)
  leaves its column empty instead of sliding the later tokens one column left. Unit from
  crore/lakh/million/thousand words; with none, the power of ten in {1e5, 1e6, 1e7} that makes the current column equal XBRL
  (`scale from XBRL`). EPS keeps its own decimals, is never scaled, and a token whose separator the scan lost (`466 90`) is read under
  the table's EPS decimals.
- **Checks.** `xbrl_ok` = the value equals `fin_quarter_xbrl` for that basis, quarter and item, tolerance 2 units of the last printed
  decimal of the ITEM: rupees of the table's scale for a rupee line, its own printed decimals (about 0.02) for a per-share line -- never
  scaled, so a crore table cannot pass an EPS two million rupees away (MARUTI's 10,953 vs 109.63); `sum_ok` = an identity holds
  (`total_income = revenue + other_income`, `pbt_before_exceptional = total_income - total_expenses`, `pbt = pbt_before_exceptional +
  exceptional`, `tax` derived from `current_tax + deferred_tax` where only the components print, `pat = pbt - tax`,
  `total_comprehensive_income = pat + other OCI`, the bank set `total_income = interest + other`,
  `expenditure_excl_provisions = interest_expended + operating_expenses`, `operating_profit`, `pbt = operating_profit - provisions`,
  `pat = pbt - tax`, `current + preceding = ytd` on a Q2 table, EPS ~ pat / shares within 1.5%); `repeat_ok` = the same symbol, basis,
  `period_end`, `period_type` and item printed by a DIFFERENT filing (another date) at the same value within its printed tolerance --
  two independent readings agree, and each row keeps its own `known_at`. A failed check stores nothing (review CSV beside `--out`); a
  failure whose input or target row was printed more than once proves nothing and keeps the cells (`sum_ambiguous`); a repaired token
  enters only behind a confirming check; everything else is `unchecked` (stored, never used by ratios). A cost line in brackets makes
  the page a segment reconciliation unless every cost prints in brackets and an identity still holds. No row prints revenue
  (HINDUNILVR): `revenue_from_operations = total_income - other_income`, `is_reported` 0. Same period printed twice with different
  values: both rows kept, listed as restatements.
- **Ratios** (`ratios.py`): `_quarters` keeps XBRL where it holds the quarter and otherwise takes the printed quarter from the EARLIEST
  filing that printed it (that row's `known_at`); `period_start` comes from the merged rows (the old XBRL-only lookup crashed on a
  printed-only quarter). YoY uses the same filing's printed `year_ago` column when it is `xbrl_ok`, `repeat_ok` or
  `sum_ok` (the better check wins when one filing printed two cells) and the cell's fiscal label is the year-ago
  quarter; with no such cell the quarter store is used and its ref suffixed `@fallback`; a mismatch refuses the
  growth instead of using another quarter (T-088: INFY Q2 FY27 8.28% -> 10.69%, HINDUNILVR 14.49%). `pat_ttm` /
  `pat_before_exceptional_ttm` (`F_PAT_TTM`, `F_PAT_BE_TTM`) carry the last four quarters as
  `input_refs`, the exceptional item's quarter named when it is not zero; new `revenue_growth_qoq_pct` /
  `pat_growth_qoq_pct` (`F_REV_QOQ`, `F_PAT_QOQ`). `_valuation` still uses `last4` when four quarters are held and otherwise one filing's
  TTM, decided by the table's own shape: a table with a ytd column uses `last_fy + ytd - prior_ytd`, only a table with no ytd at all
  uses `last_fy + current - year_ago`, a Q4 table prints the year itself (`F_TTM_PRINTED`, `refs.ttm_printed`); a missing or unchecked
  cell never falls through to the other formula. Where the filing prints the ytd and prior-ytd columns but no last full year (a Q2/Q3
  table), the last year comes from its own `fin_annual_line` FY row known by that day (`last_fy(annual) + ytd - prior_ytd`, T-073) and
  `input_refs.ttm` states the route. A fiscal year without four quarters takes the printed `fy` rows (`F_FY_PRINTED`):
  flows, margins, `eps_basic_fy`. `repeat_ok` is accepted by `printed_quarters`, `ttm_filings`, `_printed_year_ago`, `_printed_fy` and
  `pilot3_fin`.
- **MCP**: `pilot3_fin` reads `fin_quarter_printed` after `fin_quarter_xbrl` returns no row for a line item and period,
  `definition` `printed_comparative`, provenance table `fin_quarter_printed`, doc + page, `as_of` honoured, and returns
  one preferred figure per quarter (T-088); `pilot3_ratio` returns a derived ratio and the company's own stated figure
  side by side (`definition` `derived` / `company_stated`); `pilot3_kpi` lists the company's rows before a subsidiary's
  and collapses exact duplicates. `pilot3_sql` and `catalog` list the tables.
- **Measured 5 Nov 2026 (pre-T-073 baseline)** on the pilot10 copy (`scratch/w_cmp2.db`, built from `scratch/l3_base.db`, old round's `scratch/w_cmp.db`):
  6,685 rows in 4 min 08 s for the 10 companies (fix round 5,587 -> 6,685; KEC 1,032, BAJFINANCE 1,253, HINDALCO 734, HDFCBANK 183,
  SBILIFE 273, INFY 657, SUNPHARMA 987, MARUTI 200, HINDUNILVR 798, ETERNAL 568), `xbrl_ok` 1,562, `sum_ok` 2,408, `repeat_ok` 1,313,
  `unchecked` 1,402 (was 2,136); 246 cells to `w_cmp2_comparatives_review.csv` (was 169; +101 `sum_ambiguous`, +60 repair, 49 failed, 35
  unreadable). Quarter rows checked: KEC 90.1%, SUNPHARMA 91.3%, HDFCBANK 85.6%, HINDALCO 83.1%, ETERNAL 78.9%, BAJFINANCE 78.0%,
  SBILIFE 74.4%, HINDUNILVR 73.9%, MARUTI 67.7%, INFY 65.4% -- two of ten at the 90% target: `fin_quarter_xbrl` holds only four
  quarters, so an older filing's quarter columns have no XBRL row, the year-ago and prior-ytd columns are printed by one filing only
  (INFY's are unchecked by design), SBILIFE's insurer total rows carry no canonical line item, and MARUTI's scan is partly unreadable.
  `--part ratios` after it: `valuation_daily.pe` days (old round -> now) BAJFINANCE 244 -> 188, ETERNAL 72 -> 130, HDFCBANK 11, HINDALCO
  245, HINDUNILVR 178, INFY 8, KEC 117 -> 188, MARUTI 6 -> 130, SBILIFE 6, SUNPHARMA 246. First `pe` day: BAJFINANCE 2025-11-10 (29.51 =
  26.89 + 15.41 - 12.79), ETERNAL 2026-04-28 (0.40 = FY26 printed), HDFCBANK 2026-10-19 (52.03, last four quarters), HINDALCO 2025-11-07
  (80.00 = 72.05 + 39.38 - 31.43), HINDUNILVR 2026-02-12 (61.76 = 45.32 + 51.28 - 34.84 on the total-operations EPS row that equals XBRL
  28.12; the continuing-only row would give 43.08 and is no longer chosen), INFY 2026-10-23 (75.69, last four quarters), KEC 2026-01-30
  (25.94 = 21.8 + 15.51 - 11.37, its first filing with all three checked EPS cells; 2025-11-10's H1FY25 6.72 is printed once and stays
  unchecked), MARUTI 2026-04-28 (466.90, the Q4 table's printed year), SBILIFE 2026-10-27 (26.46, last four quarters), SUNPHARMA
  2025-11-06 (43.60 = 45.6 + 22.5 - 24.5). A1 on `dev.jsonl` 651 -> 682 of 898 (old round 680), no company below the baseline
  (BAJFINANCE 77, ETERNAL 66, HDFCBANK 74, HINDALCO 76, HINDUNILVR 74, INFY 66, KEC 54, MARUTI 62, SBILIFE 67, SUNPHARMA 66); the two
  questions the old round met and this one does not exist -- none (MARUTI-026/117 came back once the FY26 EPS was confirmed).
- **Tests**: `reality_engine/tests/test_pilot3_comparatives.py` (18: word-box rows, the middle-label layout, the HINDUNILVR column
  order, a misread header year, separator and repair rules, unit from text and from XBRL, xbrl_ok/sum_ok, a failed check storing
  nothing, `known_at` = the filing's date, raw token inside its quote, per-symbol rerun scope, TTM by the table's own quarter layout
  with the four measured rows, EPS tolerance never scaled, a margin label never mapping, a segment page and bracketed costs refused,
  `repeat_ok` from a second filing) and one new test in `plugins/reality-data/tests/test_lookups_pilot3.py` (printed quarter through
  `pilot3_fin`, `as_of` filter).

## Answer calculator and the answer number check (T-072, 5 Nov 2026)
The 600-answer hand read put 31 of 120 misses on a worker sum or a ten-times unit slip with the data right, because the
only tools a worker had read rows and none of them computed. The reality-data MCP now serves `pilot3_calc`
(`plugins/reality-data/server/calc.py`): one expression over `+ - * / **`, parentheses and `sum/avg/min/max/round` with
named inputs carrying units (rupees, crore, lakh, lakh crore, million, billion, shares, percent). It walks the AST (never
`eval`), normalises every input once to a base unit and computes with `Fraction`, so the answer is exact and a unit mistake
is an error, not a number; money and count results also print crore, lakh crore and Indian digit grouping, a percent prints
bps. `reality_engine/pilot3/number_check.py` replays an answer file and recomputes what it states, and
`reality_engine/pilot3/answer_record.py` refuses to record an answer that fails (a retry with `check_override` records the
failures with it). The answer format gains optional `formula` and `inputs` on each `numbers` row. On the dev set (16 known
misses, 240 graded-right answers) the checker caught 10 of the 16 and flagged 3 of the 240; the two real ones are slips in
the `numbers` list itself and the false alarm is a digits coincidence. Commands, reason codes and the misses it cannot
catch: `docs/DEVELOPER_GUIDE.md` section O12.
### Second reading an answer (T-083, 5 Nov 2026)
`reality_engine/pilot3/second_read.py` sends one answer's question, prose and own `numbers` rows to the free `beam-free`
model and keeps only flags whose `claim` is a verbatim span of the prose: `contradicts_own_numbers` (a series called
"halving" or "steady" against its own figures, a count larger than the answer's list), `unsourced_cause` (an observed
change explained by a cause with no figure, quote or named source) and `question_misfit` (periods asked and not given, a
change before the window, standalone against consolidated, a total where a per-unit figure was asked). Resumable per
`qid` + `pass_no`; a truncated or unparseable reply is retried once and then recorded as a named failure, never as no
flags. On the 304-answer dev split it flagged 28 of 46 `read_miss` answers (19 for the graded fault, 41%) and 43 of 233
`right` answers, of which 22 are false alarms (9.4%) and 21 real slips the grade missed; two passes agreed on 261 of 304
verdicts. Those are the worker's own reads. Opus's read of the 296-answer hold-out, pass 1: 16 of 43 misread answers
flagged for the graded fault (13 if a flag on the right sentence for the wrong reason does not count), against a pass
mark of 18 fixed before the run, so **the test failed and this is not a gate**. Of 231 right answers 39 were flagged: 18
false alarms, 11 clear slips the hand read missed, 10 unsupported causes the hand read let through. 18 of the 39 were
read against the answer text, the other 21 from the flag alone. Two passes agreed on 255 of 296; no failed replies.
Commands, the misses it cannot see and the three prompt rounds: `docs/DEVELOPER_GUIDE.md` section O13.
Flagged-answer test (6 Nov, 70 hold-out answers, partly blind read by Opus): an answer worker given the old answer and its
flags 51 right, a plain re-answer in one batch 9, the old answers 39 on a more lenient read. Not a clean comparison: the
plain worker made about 4 calls per question against about 7.5 before and the flags worker kept the earlier research.
Whether the reader or the model limits the score is T-084. Two faults passed the number check: T-085.
### 9c. Store defects from the 600-answer test (T-073, 5 Nov 2026)

Four general rules, no company name in code.

- **Share count = the shareholding pattern's exact total.** `stores.build_share_fallback` writes the
  `shareholding_pattern` row of `shp_category` to `share_capital` for every quarter end and basis, beside the
  paid-up/face-value row, not only where the results filing gave none (`source_table='shp_category'`, the SHP's
  own `known_at`). `ratios._share_count` and `_valuation` take the latest pattern row the day may see and fall back
  to paid-up only before that filing; `lookups_pilot3.holding` orders the pattern row first on the same date. At
  30 Sep 2026: ETERNAL 9,650,350,647, HINDUNILVR 2,349,591,262, HINDALCO 2,247,226,523.
- **Stock-in-trade and inventory-change cost lines.** `stores.STOCK_COST_TAGS` maps `PurchasesOfStockInTrade` to
  `purchases_of_stock_in_trade` and `ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade` to
  `changes_in_inventories`; the `quarterly` view does not expose them, so `_quarter_extras` reads them from
  `results_xbrl.facts` (`context='OneD'`), and `lexicon/results_lines.yaml` maps the same captions in a printed
  table. `ratios._gross_margin` (`F_GROSS_M`) = 100 * (revenue - materials - stock-in-trade purchases - inventory
  change) / revenue, quarterly and annual, non-lenders only. HINDUNILVR Q2 FY27 consolidated 47.57% (materials
  6,408 cr + purchases 3,654 cr - inventory change 507 cr over revenue 18,226 cr).
- **Valuation history.** The printed role pool depends on the current quarter end and the column count
  (`_role_set`), so a Q1 table's "year ended" column is `last_fy`, a Q4 table's is `ytd`/`prior_ytd` and a five- or
  six-column Q2/Q3 table carries `last_fy`; `_assign_tokens` matches values to columns monotonically, so a missing
  middle cell cannot slide the half-year EPS under the year-ago quarter. `_valuation` picks the basis with both a
  share count and a quarterly statement (a stray consolidated printed page no longer strands the standalone filer,
  SBILIFE), and where the filing prints ytd + prior-ytd but no last full year the last year comes from its own
  `fin_annual_line` FY row known by that day (`last_fy(annual) + ytd - prior_ytd`, recorded in `input_refs.ttm`).
  With `compute_start='2024-07-01'` (T-073) the four quarters before the window are read through the TEMP views as
  inputs only, so once four are known `last4` forms the TTM directly; `fin_annual_line_input` supplies the FY net
  worth / net debt. EV/EBITDA uses the latest **filed** balance sheet, annual or half-year, and `input_refs.net_debt`
  states `bs <period_end> <FY|H1> known <date>`; HINDALCO's H1 BS has no derived `net_debt`, so its EV rests on FY26
  until the next annual, and the lenders keep none (by design).
  Every session keeps `known_at <= date`; `test_pilot3_ratios.py` proves it on a fixture.
- **Year-to-date flows.** A YTD flow in a document filed after the quarter ended, with no period mention in its own
  sentence, is stored as `fiscal_period='YTD'`, `period_type='YTD'`, `as_of_date` = the filing date
  (`kpi._ytd_period(..., filed)`); a period printed next to the qualifier keeps the half-year/nine-month label.
  KEC's 2 Nov release prints "YTD Order intake of over Rs. 13,500 crore" and states no H1 figure: the row is
  `YTD / 2026-11-02` and `dimension='total'`. `find_dimension` refuses a segment named after a share of the total
  ("~70% from T&D") instead of tagging the total with it.
- **A ratio carries the period its page prints (T-107, 8 Nov 2026).** A ratio row (`kpi._RATIO_METRICS`: ROE, ROA,
  NIM, cost of funds, credit cost, EBITDA / gross / contribution margin, opex and commission ratio) takes the period
  its page prints, never the document's year by default: on a quarterly document a ratio that names no period is the
  quarter's annualised rate (`sentence_rows(..., ratio_quarter=True)`, which the extractor sets for every document
  that is not an annual report and is at most 80 pages), while a year named beside the label ("for FY2026", "for the
  year ended 31 March 2026", "full year": `kpi._year_named`, which stops at the label's line so a table header's bare
  "FY26" does not count) keeps the year, and a table's column header decides each column as before. The quarter is
  taken only when the document could report it (`keep_period`), so a stale `FY27` default keeps its label instead of
  becoming a future Q4FY27 and being dropped. An insurer's ROEV and VNB margin are not in the set: both are a
  roll-forward over the year (SBILIFE's 19.7% ROEV is FY26), not a quarter's annualised rate. BAJFINANCE's Q4 FY26
  highlights table prints "ROE 20.0%" in its Q4 FY26 column and the year's 18.1% two columns later; eight rows were
  stored FY26 because a Q4 document's default period is the year, so "Bajaj Finance ROE for FY26" answered the
  quarter's 20.0%. Measured on `pilot10\scratch\t113_p10_v2.db` copies: BAJFINANCE `roe_pct` FY26 36 -> 28, Q4FY26
  11 -> 19; the ten-company KPI build moves **22** `sentence_default_v1` rows from FY to Q and loses none (ROE 8,
  credit cost 8, EBITDA margin 4, ROA 1, cost of funds 1; BAJFINANCE 16, HDFCBANK 2, SUNPHARMA 2, KEC 1,
  HINDUNILVR 1), and what stays FY is what names its year ("ROE for FY2026", "for the year ended 31 March 2026").
  Both `pilot3_ratio` and `pilot3_kpi` answer FY26 ROE 18.1 (consolidated) first: `pilot3_ratio` lists the company's
  stated row before the derived one (`stated + derived` in `lookups_pilot3.ratio`), so the stated 18.1 comes before
  the 16.96 that LTM PAT over closing net worth derives. Cases in `tests/test_pilot3_kpi_ratio_period.py` (5).
- **Measured** on `D:\RealityEngine\pilot10\scratch\w_t073.db` (copy of `pilot10.db`, stores + comparatives + ratios
  rebuilt for all ten with `compute_start='2024-07-01'`, KEC KPI rebuilt): A1 `dev.jsonl` 730 -> **759/898** (BAJFINANCE
  79, ETERNAL 72, HDFCBANK 84, HINDALCO 77, HINDUNILVR 81, INFY 72, KEC 64, MARUTI 81, SBILIFE 76, SUNPHARMA 73; no
  company below its round-1 score); `checkpages run` 145 found (29/59/57). Latest market cap uses ETERNAL 9,650,350,647 /
  HINDUNILVR 2,349,591,262 / HINDALCO 2,247,226,523 shares (book value per share at 30 Sep 2026: ETERNAL 33.96 -> 32.41,
  HINDUNILVR 207.79 -> 207.82, HINDALCO 615.24 -> 607.78). **PE and EV sessions: 269 of 269 for every company with a share
  count from window start** (before -> after: BAJFINANCE 188/0 -> 269/0, ETERNAL 130/10 -> 269/269, HDFCBANK 11/0 ->
  269/0, HINDALCO 245/113 -> 269/269, HINDUNILVR 255/128 -> 269/269, INFY 71/8 -> 269/269, KEC 188/117 -> 269/269,
  MARUTI 130/6 -> 269/269, SUNPHARMA 246/113 -> 269/269; lenders keep no EV by design). INFY's 2025-11-14 row: close
  1502.8, trailing EPS 67.87 = 16.43 + 16.98 + 16.70 + 17.76 (Q4FY25..Q2FY26, all known by then), PE 22.14,
  `input_refs.ttm='4_quarters'`; its first PE session is 2025-10-01. HINDUNILVR Q2 FY27 `gross_margin_pct` 47.57%
  consolidated (cost lines = total expenses for every non-lender's latest quarter, gap 0.00%; the two lenders' gaps are
  their interest/premium P&L, not missing cost captions).
- **Inputs stay inputs (measured before T-155).** After the build `fin_quarter_xbrl` starts 2025-12-31 and
  `fin_quarter_xbrl_input` ends 2025-09-30 (2,086 rows); `fin_annual_line` starts
  2025-12-31 and its input ends 2025-09-30. T-155 (9 Nov 2026) changes the price side: `price_delivery` now starts at
  `price_start` (2019-01-01 by default), and `valuation_daily` and `index_price` with it; the `price_delivery_input`
  copy holds only rows before `price_start`, so it ends where the main table starts. `ratio_panel` still starts at the
  window; 0 document rows precede the window, 0 valuation rows have `known_at > date`, 0 ratio rows are known before
  their period end.
- **SBILIFE, 230 sessions not 269.** Its first exact share count is the 30 Sep 2025 shareholding pattern known
  2025-11-28; a life insurer files no paid-up/face-value XBRL, so there is no earlier results-derived count. From that day
  it has 230 NSE sessions; PE starts 2026-01-28 (190 sessions) when the Q3 FY26 filing is the fourth known quarter, and
  the 40 sessions from 2025-11-28 to 2026-01-27 stay without PE for lack of that fourth quarter. Its EPS tag **is** read
  (`BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized` -> `eps_basic`), 7 XBRL
  filings since April 2025 (3 input + 4 window quarters).
- **INFY's Q3 filing cells.** With the input XBRL the prior-year quarter cells become `xbrl_ok` (Q3FY25 EPS 16.43 /
  15.31, PAT, revenue); the nine-month `prior_ytd` EPS cells stay `unchecked` because the XBRL store holds quarters, not
  cumulative 9M EPS. They no longer matter: the four-quarter route forms the TTM.
- **No stop condition remains.** KEC's 188 was not an absent filing: its earlier ISIN (`INE389H01014`, 49 filings to
  Dec 2024) was missing from the profile's `isins`, so the stores filtered those rows out; adding it (and SUNPHARMA's
  `INE044A01028`) brings the fourth pre-window quarter in. Every filing the named companies' TTM needs is held.
- **Test status.** `test_pilot3_comparatives.py` 21 passed, `test_pilot3_ratios.py` 12 passed, `test_pilot3_profile.py`
  6 of 7: `test_manifest_docs_build_and_window` fails on a pre-existing fixture (its PDF text is clipped at "Revenue for
  Q2 FY26 was R", and the HEAD `kpi.py` also returns no row for the clipped order-book sentence under the auto_oem
  profile), so it is not a T-073 regression; the fixture needs a wider text box or a transcript assertion.

### 9d. Named holders, the promoter pledge block and the percentage base (T-088, 6 Nov 2026)

Two T-087 answers had failed because no holder was named and the September 2025 quarter was missing.

- **The parse skipped every named holder.** A holder's facts sit in contexts whose only dimension is a
  `typedMember` (`DetailsOfSharesHeldByBodiesCorporateAxis`, `...MutualFundsOrUTIAxis`,
  `DetailsOfTheShareholdersActingAsPersonsInConcertForPublicAxis`, ...): the name is in the `D_` context, the counts
  in the bare one with the same member, and `parse_shp_xbrl` dropped any context carrying a typed member. It now
  reads them into `holders`, keyed by the axis and the filing's own member id: `NameOfTheShareholder`,
  `NumberOfShares`, `ShareholdingAsAPercentageOfTotalNumberOfShares`, `NumberOfShareholders`, `NameOfThePAC`,
  `PercentageOfShareholdingByPAC` and the holder's own pledged count when printed. The category is the
  `shp_category` name of the axis member (`MEMBERS`, else snake case): `...MutualFundsOrUTIAxis` -> `mutual_funds`,
  `DetailsSharesHeldByIndividualsOrHUFAxis` -> `promoter_individuals`, `...ForPublicAxis` -> `pac_public`,
  `...OthersIndianShareholdersAxis` -> `others_indian_shareholders` (the taxonomy reuses that axis for a promoter-group
  corporate and for a public other-Indian holder, so the category is the filing's member name, not a block claim).
- **`shp_holder`** (new): one row per `(symbol, isin, quarter_end, category, holder_name)` with shares, pct, holders,
  `pac_name`, `pac_pct`, the holder's `pledged_shares`, source file and `known_at`; index `(symbol, quarter_end)`. A
  persons-in-concert disclosure keeps its own `pac_*` category, so summing a `MEMBERS` category never counts the same
  holder twice (`SUM(shares) WHERE category NOT LIKE 'pac_%'` is the category total; ETERNAL 2026-09-30 keeps Info
  Edge's 1,194,687,095 shares once under `bodies_corporate` and once under `pac_public` with
  `pac_name='NAUKRI INTERNET SERVICES LIMITED'`).
- **`shp_pledge`** (new): one row per quarter with the file's three flags
  (`WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged`, `...UnderNonDisposalUndertaking`,
  `...OtherThanByWayOfPledgeOrNDU`; the older taxonomy's single `...PledgeOrOtherwiseEncumbered` folds into the pledge
  flag), the promoter rollup's shares, pledged shares and the filing's printed pledged percentage. 73 rows over the
  ten companies, 6 with the flag true (SUNPHARMA 2025-06-30..2026-09-30: 0.88, 0.97, 0.97, 1.42, 1.65, 0.01%). INFY
  prints the flag false and no count, so the row says exactly that.
- **The printed pledged percentage is of the promoter group's own shares, not of all shares** - arithmetic on the
  corpus, not the tag name: for every category that prints both an encumbrance count and a percentage, the printed
  number matches shares / the category's own shares (211 + 196 + 151 + 15 rows across the four count tags) and never
  only shares / all shares (0 rows). IDEA 2025-12-31 prints 11.84% for 3,280,000,000 encumbered shares of
  27,702,778,543 promoter shares (3.03% of the total). So "what share of promoter holding is pledged" is the filing's
  own number.
- **Percentage base.** INFY 2026-09-30 prints promoter 13.90% for 516,677,914 shares: that is 13.90% of
  3,716,041,606, the total 4,058,276,578 less the 342,234,972 shares held by `CustodianOrDRHolder` (the ADR
  depository), not 12.73% of the total. `stores._pct_base` picks the base that reproduces every printed percentage of
  the file (the total, or the total less DR custody when that differs) and every `shp_category` row of the quarter
  carries `pct_base_shares` + `pct_basis` (`total_shares` / `total_excluding_dr_custody`). 591-file corpus check: the
  total matches 571 files (551 with no DR custody + 20 whose DR flag is true but hold no custodian row), only the
  total-less-custody base matches 11, both match 9, neither 0. On the pilot10 copy only INFY and HDFCBANK print on
  `total_excluding_dr_custody`; the other eight print on the total.
- **Window.** `shp_category`, `shp_holder` and `shp_pledge` are `stores.HISTORY_TABLES`: `apply_window` keeps their
  rows from `compute_start` (2024-07-01) instead of `window_start` (2025-10-01), so 2025-09-30 is back; the price
  tables keep theirs from `price_start` (T-155, 2019-01-01 by default), and the three `INPUT_TABLES` still split their
  pre-window rows into `<table>_input` (the `price_delivery` copy stops at `price_start`, so it stays disjoint from
  the main table).
  Quarters held on the copy: 9 to 11 per company from 2024-09-30 (KEC from 2024-09-26); before a held XBRL file the
  quarter still has the `shp_index` promoter/public rows (ETERNAL 2024-09-30..2025-06-30, category level only).
  `ratios._share_count` and `_valuation` read `share_capital`, not `shp_category`, so a later quarter's count is
  unchanged, and `test_pilot3_shp_holder.py` pins it.
- **`pilot3_holding`** now returns `holders` (the quarter's top 12 named holders, `pac_*` rows left out;
  `all_holders=true` lists every named holder with `pac_name`), `promoter_pledge` (the three flags, promoter and
  pledged shares, the printed percentage and an `answer` sentence; T-108, 8 Nov: a flag that says no pledge gives `nil` true with 0 shares and 0%, and `previous_quarter` + `changed` carry the quarter before), `pct_basis`, and every reply states
  `quarters_held` (first/last/count) and `categories_held`. The lookups guard an older build without the two tables.
- **Every SHP category, the GoI line and a four-quarter path (T-165, 10 Nov 2026).** `pilot3_holding` used to answer
  from a fixed main-category list against the latest quarter with any row, so the Government of India line
  (`central_government_or_president_of_india`) was never returned and a newest quarter holding only its `shp_index`
  promoter/public rows hid the complete previous quarter (Vodafone Idea's GoI 49.0% at 30-Jun-26 sat behind a
  30-Sep-26 index row). It now returns every filed category with `pct` and `pct_basis`, picks the latest quarter with
  an XBRL filing, dedupes to one row per category and quarter (XBRL before the index copy, as `queries.shp` orders),
  maps the words investors use (`government` / `GoI` / `DIPAM`, `FPI` / `FII`, `MF`, `DII`, `retail`; a no-match filter
  returns no row and lists `categories_held`) and takes `quarters=N` (an SHP filed at a record date inside a quarter is
  skipped; one newer than the last quarter end is kept -- PERSISTENT's 26-Oct-26 filing). `pilot3_kpi` resolves
  `net interest margin`, `losses and provisions to assets` and `cost of borrowings` and reports `held_quarantined`
  when the row check hid the only row (CHOLAFIN Q2FY27 NIM 7.9). Re-ask of the audit's 11 routing rows on the u8/q12
  stores, re-run by an independent read-only dsh review (10 Nov): 11/11 reachable, 9 clean, 2 caveated (CHOLAFIN Q4FY26 NIM
  also returns the 0.68 wrong-scale row; Q1FY27 credit cost has 3 rows, 150 is the one the call states), 0 wrong; the
  cost-of-funds commentary half answers with `terms="cost of funds"` or `topic=rates`, not "repricing";
  `plugins/reality-data/tests/test_lookups_pilot3.py` 31 passed, 1 skipped. Store defects reported, not fixed:
  CHOLAFIN `nim_pct` Q4FY26 also holds 0.68 (wrong scale, the audit's own defect), Q2FY27's 7.9 is quarantined by a
  hard `unit_kind` check, and the three CHOLAFIN `credit_cost_bps` Q1FY27 rows (150 / 180 / 470) are extraction noise.
- **Accept on the copy** (`.tmp/pilot10_w.db`, `--part stores` 129 s, all ten companies): ETERNAL 2026-09-30 has
  Info Edge (India) Limited 1,194,687,095 shares / 12.38% under `bodies_corporate` and Foodie Bay Employees ESOP Trust
  437,576,304 / 4.53%; BAJFINANCE 2025-09-30 has `fpi_total` 21.97 (1,367,282,372 shares) and `mutual_funds` 8.89
  (552,952,827); INFY 2026-09-30 has its pledge flag (false) with base 3,716,041,606 `total_excluding_dr_custody`;
  every company has `shp_holder` rows for 2026-09-30 (BAJFINANCE 115, ETERNAL 64, HDFCBANK 17, HINDALCO 24,
  HINDUNILVR 13, INFY 36, KEC 29, MARUTI 121, SBILIFE 55, SUNPHARMA 23; 3,234 rows in all) and 73 `shp_pledge` rows.
- **Tests.** `reality_engine/tests/test_pilot3_shp_holder.py` 3 passed (0.1 s): the parse of a synthetic file with a
  DR-custody base, holder contexts, a PAC twin and the pledge block; `build_shp` writing the three tables; the
  `compute_start` window with `ratios._share_count` unchanged. `plugins/reality-data/tests/test_lookups_pilot3.py`
  24 tests OK (1 skipped), including the `pilot3_holding` holders/pledge/coverage reply.
- **Files.** `reality_engine/pilot3/stores.py` (`parse_shp_xbrl`, `_holder_category`, `_pct_base`, `_flag`,
  `build_shp`, `apply_window`, `HISTORY_TABLES`), `reality_engine/pilot3/schema.py` (`shp_category` columns,
  `shp_holder`, `shp_pledge`, indexes, `PARTS`), `plugins/reality-data/server/lookups_pilot3.py` (`holding`),
  `plugins/reality-data/server/server.py` and `catalog.py` (tool signature, table lists),
  `reality_engine/tests/test_pilot3_shp_holder.py` (new), `plugins/reality-data/tests/test_lookups_pilot3.py`.

### 9e. One preferred figure per period (T-088, 6 Nov 2026)

Store fixes 1 and 2 of the T-087 report. The 600-answer read and the DeepSeek dig test put misses on the financial
lines: `pilot3_fin` could return several rows for one line and quarter (a stale current beside a later restated
comparative), growth could use a printed cell that was not that line (INFY Q2 FY27 consolidated
`revenue_growth_yoy_pct` 8.276 = 49,244 / 45,479, the Q3 FY26 revenue, where the filing's year-ago is 44,490 and the
right answer 10.69%), `pilot3_ratio` returned only the derived ROE (Bajaj FY26 16.96 against its stated 18.1),
`kpi_series.basis` carried subsidiary names ('bhfl', 'bajaj_financial_securities') and `dimension` carried
'standalone', a quarter's TTM PAT had no row, and two INFY `fin_annual_line` rows were corrupt. Six general rules,
no company name in code.

- **Preferred comparative (`lookups_pilot3.fin`).** Quarterly rows are grouped by (measure, period, basis) and one
  figure is returned: the newest filing known at `as_of`, `restated: true` when it differs from the first printing,
  with the other values in `alternatives` carrying filing date, `role` (current / preceding / year_ago / xbrl) and
  check status. A tie on the filing date goes XBRL > `xbrl_ok` > `repeat_ok` > `sum_ok` > clean unchecked. A printed
  cell whose check failed may still be a restatement, so it is admitted when its `raw_token` is ONE printed number
  (`_printed_cell_ok`); a token carrying letters or a currency word ("9,176 cr") is not a figure. On the copy:
  `fin('BAJFINANCE','total_income','Q2FY26', as_of='2026-11-04')` -> one row, preferred **19,992.38 crore**
  (`restated`, the year-ago column of the 19 Oct 2026 filing) with **20,180.76 crore** as its alternative (current,
  10 Nov 2025); with `as_of='2026-01-01'` -> preferred **20,180.76 crore**, not restated.
- **Growth on the same quarter a year earlier (`ratios._printed_year_ago`).** The base is the current filing's own
  `year_ago` cell for that line when its check is `xbrl_ok`, `repeat_ok` or `sum_ok` and its fiscal label is the
  year-ago quarter (`sum_ok` means the column added up -- HINDUNILVR's Q2 FY27 filing prints Q2 FY26 revenue 15,919;
  its first printing 16,241 is pre-restatement). Where one filing printed two cells for the line the better check
  wins (`xbrl_ok` > `repeat_ok` > `sum_ok`), so INFY's cash-flow "Total income" `sum_ok` cannot beat the
  XBRL-confirmed revenue cell: INFY Q2 FY27 consolidated 8.276 -> **10.6855%** (49,244 / 44,490, `year_ago`
  `xbrl_ok`, same filing). With no such cell the quarter store is used and the base ref is suffixed `@fallback`
  (38 rows on the copy); a base whose fiscal label is another quarter refuses the row. Values on the copy:
  HINDUNILVR Q2 FY27 consolidated **14.4921** (18,226 / 15,919, `year_ago` `sum_ok`, same filing) and Q1 FY27
  **10.0527** (17,341 / 15,757); Q3 FY26 5.6891 (16,441 / 15,556) and Q4 FY26 -0.5474 (16,351 / 16,441) on their
  own filings' `year_ago` cells. Compared with live, **1 growth value changed** (INFY Q2 FY27 consolidated
  8.2762 -> 10.6855); every other row is on its live base, including the 18 the first round moved -- that rule
  refused `sum_ok` and fell back to a first printing, which HINDUNILVR's restated comparative showed to be wrong.
- **Stated and derived together (`lookups_pilot3.ratio`).** `ratio_panel` rows are `definition: derived` (formula and
  input refs); the company's own figure for the same ratio in `kpi_series` (metric name or its `_pct` form) is
  `definition: company_stated` with quote and page, for each period. Company rows only (entity = symbol), the
  consolidated basis first, then the best evidence. BAJFINANCE `roe` Q2 FY27: derived **17.914** and stated
  **20.6**; Q1 FY27 stated 20.4; FY26 derived **16.958** and stated **18.1**.
- **Entity apart from basis (`kpi_series.entity`).** A new `entity` column names the reporting company (its symbol)
  or the subsidiary the row's dimension/page heading/paragraph names ('bhfl', 'bajaj_financial_securities', ...);
  `basis` now only ever says consolidated / standalone / not_stated, and a basis word stored in `dimension` moves to
  `basis`. A segment word ('commercial', 'auto') is never an entity: only the lexicon entity tokens and the
  subsidiary names it prints count. `kpi()` lists the company's rows first, labels `entity`, and collapses exact
  duplicates (same metric, entity, dimension, period, value, unit). BAJFINANCE FY26 `roe_pct` went from 35 stored
  rows to **12 returned values**, company rows first (18.1 consolidated, 18.6 standalone, 19.2, 19.22, 18.76,
  18.05, 4.3, 20.0, 19.7) then bhfl 12.1, bajaj_financial_securities 12.01, bajaj_housing_finance 12.1. Q1 FY27
  cost of funds: the "cost of funds was 7.21%" row now carries entity **bhfl** (page 17's "Lead financial
  indicators for Q1 FY27 - BHFL"; `page_basis` now also reads the footer heading), beside the company's 7.46 and 7.40.
- **Trailing twelve months (`ratios._panel`).** `pat_ttm` (`F_PAT_TTM`) and `pat_before_exceptional_ttm`
  (`F_PAT_BE_TTM`) rows for every company whose last four quarters are held; `input_refs` names the four quarters,
  and the before-exceptional row names each quarter holding a non-zero `exceptional_items` **with its amount**.
  BAJFINANCE Q2 FY27 consolidated PAT TTM **22,066.48 crore** (Q3FY26 4,066.01 + Q4FY26 5,553.30 + Q1FY27 6,080.60
  + Q2FY27 6,366.57 crore, four inputs) and before exceptional **22,331.70 crore**, the Q3 FY26 item
  `-2,652,200,000` named in `inputs`.
- **The two INFY claims are both true and fixed (`stores.build_annual`).** (1) `lease_liabilities` held a row of
  917,626,822,725 labelled `inr_crore`: ar_facts doc 121629 page 339 reads "9,176 (FY26); 8,227 (FY25)" and the
  stored value is the two printed numbers glued, with `value_check='not_found'`. `_concatenated_value` drops a fact
  whose unverified value matches none of the two or more numbers its own `value_raw` prints. (2) 3,749 was stored
  `consolidated`: page 225 is the standalone note ("The Company ..."), page 339 the consolidated note ("The Group
  ..."), and ar_facts says consolidated for both. `_ar_page_bases` reads the page from pages.db (doc sha256 ->
  docs key) and `_statement_basis` counts "the Company" / "the Group", overriding the stored basis. After the
  rebuild FY26 `lease_liabilities` is consolidated **9,176** and standalone **3,749**, no glued row.
- **Measured** on `.tmp/pilot10_w.db` (copy of `pilot10.db`; `--part stores` for **all ten** companies, because
  `schema.create` drops the table and scoping it to two would delete the other eight companies' rows;
  `--part comparatives --symbols INFY,BAJFINANCE`; `--part ratios`; `--part kpi --symbols BAJFINANCE`): `ratio_panel`
  rows before -> after: BAJFINANCE 164 -> 180, ETERNAL 226 -> 242, HDFCBANK 100 -> 116, HINDALCO 150 -> 162,
  HINDUNILVR 228 -> 244, INFY 228 -> 244, KEC 228 -> 244, MARUTI 228 -> 244, SBILIFE 35 -> 43, SUNPHARMA 228 -> 244
  (the difference is the new TTM rows each company's four held quarters form); `kpi_series` BAJFINANCE 2,059;
  `checkpages run` **146** found (KEC 29 / BAJFINANCE 59 / HINDALCO 58); `test_pilot3_preferred.py` **11 passed**.

**T-090 (6 Nov 2026): the preferred figure now lives in the data, and `pilot3_sql` gets the same number.** In the
600-answer re-test 77 of 126 pilot calls went through `pilot3_sql`; BAJFINANCE Q2 FY27 total-income growth came out
21.8% because plain SQL summed/compared both 20,180.76 crore (the Q2 FY26 filing) and 19,992.38 crore (the Q2 FY27
filing's restated year-ago column) while `pilot3_fin` returned the second. The election has one home now.

- **One rule, one module.** `reality_engine/pilot3/preferred.py` holds `order_key` / `elect` / `evidence_rank` /
  `displayable_printed` / `apply` / `ensure_columns`. The rule: newest `known_at`, then evidence rank (XBRL 5,
  `xbrl_ok` 4, `repeat_ok` 2, `sum_ok` 1, unchecked 0), then the first stored row (`-rowid`, which keeps the answers
  `pilot3_fin` gave before the move). An XBRL row suppresses the printed twins of the same key (the lookup always
  treated them as duplicates); a printed cell whose `raw_token` is not one printed number never competes.
  `lookups_pilot3.fin` calls `elect`; its own `_preferred`, `_printed_cell_ok`, `_evidence_rank` and `_same_value`
  are gone.
- **Columns and view.** `fin_quarter_xbrl` and `fin_quarter_printed` carry `preferred_from` / `preferred_to` (YYYY-MM-DD
  days taken from `known_at`, not timestamps, because a bare date compares below a timestamp as text and would hide a
  figure on its own filing day; `preferred_to` NULL = current). Opus's sweep at each key's filing days found this: 736
  of 1,536 lookups differed before, 0 of 1,531 quarter lookups after. A row is preferred at day D when `preferred_from <= D` and
  (`preferred_to IS NULL` or `preferred_to > D`); the windows of one (symbol, line_item, fiscal_period, basis) tile
  its timeline, so exactly one row answers at any D. `fin_quarter_current` (schema view) is the row preferred now,
  one per (symbol, fiscal_period, basis, line_item), with `source_table`, `source`, `page`, `column_role`,
  `check_status` and `xbrl_tag`; `schema.ensure_views` leaves an older build without the columns alone.
- **Build.** New part `preferred`, after `comparatives` in `all`:
  `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --out .tmp/pilot10_w.db --part preferred`.
  It ALTERs the columns onto a database built before T-090, reads the union of both tables once for
  `profile.symbols()` (`--symbols` limits it like every other profile part), groups by key, sorts the candidates,
  writes the windows to a temp table and `UPDATE … FROM` both tables in two statements. `stores.build_quarterly`
  and `comparatives.run` now name their insert columns, so the preferred columns start NULL and the step fills them
  (re-run `preferred` after any part that rewrites those rows).
- **Tool text reads coverage from the database.** `pilot_symbols()` returns the database's `company` table (the
  whole universe a build covers); `PILOT3_SYMBOLS` is only the fallback when the table is absent, and it no longer
  decides coverage. The server instructions, the `pilot3_*` descriptions and the catalog say "every company the
  database holds", name no company, and `pilot3_sql` names `fin_quarter_current` and the `preferred_from` /
  `preferred_to` columns with the day predicate. A company the database does not hold returns `found: false`
  (error code `not_pilot3`) and the message states the company count, not a list.
- **Measured** on `.tmp/pilot10_w.db` (copy of `pilot10.db`), `--part preferred`: **0.1 s** for the ten companies,
  7,330 windows, 5,408 keys with a current row, no broken window link and no key left without a current row.
  (a) BAJFINANCE `total_income` Q2FY26 consolidated: **19,992.38 crore** at 2026-11-04 and **20,180.76 crore** at
  2026-01-01, from the columns and from `pilot3_fin` alike. (b) Sweep of **3,295** quarterly keys over all ten
  companies at as_of 2026-11-04: **0 differences** between `pilot3_fin` and the columns; the old and the shared
  election return the same figure for all 3,295 (**0 changed**). (c) `checkpages run` (default `pilot3.db`) still
  **146** found (29/59/58); the same command with `--db .tmp/pilot10_w.db` finds 0/314 because the fixture's 81
  `doc_key`s are the `pilot3.db` keys (the untouched live `pilot10.db` gives 0 too), which T-090 does not touch.
  (d) The server instructions contain no company name. (e) the step takes 0.1 s for ten companies.
- **`fin_annual_line` inspected, not elected.** It has 67 keys with more than one row and 59 with more than one
  distinct value, but the top case is not the quarter problem: INFY FY26 standalone `pat` has 12 rows at one/two
  annual-report `known_at`s, 11 of them sharing ONE filing instant, and no evidence rank separates values printed
  by the same filing. Applying the quarter rule there would pick a row by rowid, so annual rows pass through
  unchanged (reported, not forced).
- **Files.** `reality_engine/pilot3/preferred.py` (new), `schema.py` (columns, `FIN_QUARTER_CURRENT`,
  `ensure_views`), `build.py` (`preferred` part), `stores.py` / `comparatives.py` (named insert columns),
  `plugins/reality-data/server/lookups_pilot3.py` (shared election, coverage from `company`, `sql` text),
  `server.py` and `catalog.py` (text), `reality_engine/tests/test_pilot3_preferred_data.py` (new, **6 passed**),
  the seven existing test files that inserted the quarter rows positionally (named columns now).
  `test_pilot3_preferred.py` **11 passed**; plugin `test_lookups_pilot3.py` **24 tests OK (1 skipped)**; the other
  pilot3 suites 39 passed with 1 failure and 13 `tmp_path`/synthetic-PDF errors in this sandbox (ACL and extraction,
  not this change).





### 9f. Credit ratings, concentration and related-party notes (T-091, 6 Nov 2026)

Three new tables read from annual-report pages by script, for any listed company, with no company name, page number
or per-company rule in the code: `rating_event`, `concentration`, `related_party_txn` (`pilot3/notes.py`, wording in
`pilot3/notes_lexicon.yaml`, DDL in `pilot3/schema.py`, build part `notes`, `pilot3_sql` table list). Every row
carries `symbol, isin, fiscal_year, entity, basis, doc_key, page, quote, known_at, known_at_source, extractor_rule`.
`entity` is the company's legal name from the `company` table (never a literal); `basis` is read from the page's own
header ("Notes to the Standalone/Consolidated Financial Statements") and is `not_stated` where the page prints none;
`known_at` is the document's filing time, so every row is point-in-time.

- **`rating_event`** (`agency, instrument, rating, outlook, action, effective_date, trigger_text`). Three shapes, all
  by wording: (1) the rating table -- an agency cell (`CRISIL Rating Ltd.`, `India Ratings and Research Private
  Ltd.`, an agency name plus at most a name suffix) followed by programme/instrument cells and rating cells, with the
  migration cell read as the action (`Nil` -> `reaffirmed`, "Upgraded from" -> `upgraded`, "New ... Assigned" ->
  `assigned`), so BAJFINANCE p373 gives 4 India Ratings rows, 7 CRISIL, 4 ICRA, 2 CARE, 1 Moody's and 2 S&P; (2)
  prose when the page has no table -- "credit rating of AAA/Stable (long term) and A1+ (short term) on its bank
  facilities by CRISIL" gives two rows with the term appended to `instrument`; (3) a company that states it holds no
  rating gets one row with `action='not_rated'` (ETERNAL p181). A rating-linked clause in any filing is a `trigger`
  row with the clause in `trigger_text`: BAJFINANCE's 27 Aug 2026 NCD allotment (a `material_filing` announcement, so
  the reader reads `announcement` documents too) states a 25 bps coupon step-up if the rating falls to AA- or below
  and a recall right at A or below -- two rows, `rating` AA- and A. The rating each row carries is the symbol as
  printed (`IND AAA`, `CRISIL AAA`), `outlook` the printed stable/positive/condition word.
- **`concentration`** (`dimension, bucket, measure, pct, value, unit, scale, period_end`). A two-year table whose
  label names a bucket (top 5/10/20, single largest) or a whole population (all trading houses, all dealers) and a
  measure is read column by column against its own year header, so FY26 and FY25 are separate rows whatever order
  the columns print in and each value is anchored to its printed year: BAJFINANCE p374 (twenty largest depositors
  13,346.95 crore 19.49% / FY25 11,194.76, 15.69%; twenty largest borrowers 14,951.00 crore 3.35% / 14,032.99, 3.80%),
  INFY p241 standalone and p320 consolidated (top five customers 12.7% / 12.9%, top ten 20.5% / 20.5%), KEC p76
  (purchases from trading houses 2.63% / 3.62%, top ten 49.31% / 62.70%, dealers 11.51% / 8.64%). A prose sentence
  ("the top 20 depositors comprised of 4.81% of total deposits", HDFCBANK p415) is the same row. `pct` holds a
  percentage, `value`+`unit`+`scale` a money amount (`inr_cr`/1e7); a row whose dimension or measure cannot be named
  is dropped rather than guessed (a "commercial paper as a percentage of total liabilities" row is not one of the
  eight dimensions).
- **`related_party_txn`** (`counterparty, relationship, txn_type, amount, balance, unit, scale, period_end`). A
  related-party note is found by its wording, and a note's continuation pages (which carry only the table) are
  followed for up to four pages after the last page with a cue; each row is a counterparty (an entity name ending in
  a corporate suffix, or a party heading such as "Remuneration to KMP") with its two year columns, and the printed
  heading above the row is `txn_type`. ETERNAL p387 standalone: Blink Commerce 3,850 crore FY26 / 1,740 FY25 under
  "Reimbursement for delivery partner fees", Income from cross charge Blink 344 / 145 and Zomato Hyperpure 118 / 81;
  p273 consolidated: KMP salaries 146 / 165 and directors' remuneration 5 / 5, `basis='consolidated'` beside the
  standalone rows' `basis='standalone'`. A block whose heading says balances (outstanding, payable, receivable) fills
  `balance` instead of `amount`. A row whose label names no transaction (a bare "Member", "Chairman") and a page
  whose labels end in no corporate suffix ("Amount required to be spent by the Company during the year") are
  refused -- measured, that guard removed the largest class of false rows.
- **Measured** on `.tmp/pilot10_w.db` (a copy; `--part notes`, all ten companies, 11.0 s in all):

  | company | rating_event | concentration | related_party_txn | seconds |
  |---|---|---|---|---|
  | BAJFINANCE | 43 | 18 | 23 | 1.38 |
  | ETERNAL | 1 | 0 | 249 | 0.51 |
  | HDFCBANK | 17 | 12 | 24 | 0.70 |
  | HINDALCO | 2 | 4 | 14 | 1.83 |
  | HINDUNILVR | 1 | 8 | 0 | 0.84 |
  | INFY | 4 | 8 | 238 | 1.54 |
  | KEC | 8 | 8 | 0 | 1.16 |
  | MARUTI | 2 | 8 | 161 | 1.18 |
  | SBILIFE | 1 | 0 | 0 | 1.04 |
  | SUNPHARMA | 5 | 8 | 13 | 0.73 |

  Hand read (seed 11, 15 random rows per table, each against its page): `rating_event` 15/15 and `concentration`
  15/15 rows anchored to a page line and, read by eye, the right label and year; `related_party_txn` 15/15 anchored
  and, after the transaction-word and corporate-suffix guards, every sampled row a real transaction (KMP and
  director remuneration, Blink Commerce, Krishna Maruti, Utkal Alumina). Two earlier reads of the same tables were
  the reason for those guards: the cousin rows (`Amount required to be spent ... Company`, a CSR table read as
  related parties; "Member"/"Chairman" category rows; an employee-remuneration band table) are gone.
  Opus's own read of 12 rows per table on another seed (20261106) found what that read could not: 426 of 722
  related-party rows had no unit, 53 rating rows carried an assumed `reaffirmed`, `OTC` gave rating `C`, and balances
  such as `Other financial assets` sat in `amount`. Fixed: `page_unit` carries the unit a note prints once (this page,
  then up to 6 before), `action` is NULL unless the page states one, a rating letter inside a word is no rating, and
  balance lines go to `balance`. Result: all 722 related-party rows carry a unit, 136 balances against 74 before.
  Still open: 73 related-party rows have no `txn_type` because the heading is on an earlier page.
- **What the rules cannot read** (a zero is a "not read", never a "does not exist"): a note that prints one column
  per party category with no year pair in the header (HDFCBANK's schedule at p474, KEC's standalone note, HUL's
  note) is not read as `related_party_txn` -- that class is in the ticket's evidence for BAJFINANCE/HDFCBANK and is
  left for a targeted round rather than stored with a guessed column order; a continuation page more than four pages
  past the last page with a related-party cue; an entity name wrapped so that only its last word ("Ltd") sits on the
  row's own line; a concentration table whose labels wrap across three or more lines (the label fragments are joined,
  but the reader keeps only the closest one before the values); a single merged year column; a rating table whose
  extraction interleaves the agency column with the ratings so no agency cell survives; a trigger clause printed only
  as an image. `concentration` and `related_party_txn` are zero for ETERNAL and SBILIFE because their annual reports
  print no top-N or percent-of-total disclosure and no year-columned related-party table (the pages that carry the
  cue words were searched: ETERNAL 68, SBILIFE 68 pre-filtered pages).
- **Checks.** `reality_engine/tests/test_pilot3_note_tables.py` (**15 passed**): the fixture page text of BAJFINANCE
  p373/p374, INFY p125/p241/p320, ETERNAL p181/p273/p387, MARUTI p115, HDFCBANK p415, KEC p76 and the 27 Aug 2026
  NCD filing, one test per rule, plus a database round trip that writes and re-runs the part.

### 9g. Quarantined rows are never served (T-113 B, 8 Nov 2026)

The independent row checker (build guide section 13) now ships its verdicts inside the build and the tools read them.
`build --part checks` (last in `all`, after `guidance` and `notes`) runs `reality_engine/pilot3/row_checks.py` into a
temp file beside the build and copies `row_check` and `row_check_fail` into the build in one transaction
(`reality_engine/pilot3/build.py`); a build without `guidance`, or without financial tables, skips only that table,
and `row_checks.py` itself is not edited. `pilot3_kpi`, `pilot3_guidance` and the stated-ratio rows of `pilot3_ratio`
(`plugins/reality-data/server/lookups_pilot3.py`, tool text in `server.py`) LEFT JOIN the verdicts by `tbl` +
`row_id`: `status='quarantined'` is dropped unless the call passes `include_quarantined=true`, and every served row
carries `check_status` (`verified` / `unverified`, NULL when it has no verdict) plus `check_note` (the soft checks'
names) on an unverified row. The tool text tells the model to prefer verified rows and say "unverified" when quoting
one; the `available` / `held_options` / `held_period_dimension` hints never name a metric whose every row is
quarantined. A database without `row_check` (any build made before this part) serves exactly as it did. A part that
rewrites `guidance` or `kpi_series` (`guidance`, `kpi`, `extract`; all of them in `all`) first deletes that table's
verdicts, because a rebuilt row has a new id and the old verdict would hide or label the wrong row -- re-run
`--part checks` after any kpi or guidance rebuild. Measured on
the pilot10 dev copy (`D:/RealityEngine/pilot10/scratch/t113_p10_serve.db`, 8 Nov, round-2 checker): the part took
7.3 s and wrote 6,149 verdicts — guidance 46 / 26 / 34 and kpi_series 4,249 / 1,422 / 372 (verified / unverified /
quarantined). The checker has moved since (build guide section 13, round 10): it alone now takes 11.8-13.7 s warm
(median 12.0 s; up to 17.2 s with a cold page cache) on the same 6,149 rows and gives guidance
19 / 46 / 41 and kpi_series 2,298 / 3,293 / 452 — every verified kpi row is now corroborated by a second source or
is an `xbrl_segment` row (build guide section 13, `single_source`), so the build serves fewer but better verified
rows — re-run `--part checks` into a build and re-measure the part before quoting its time or counts again.
`kpi('BAJFINANCE','nnpa_pct','FY25')` lost the 1.18 gross-NPA row (8 rows -> 4), `guidance('HDFCBANK')` 3 -> 1 and
`guidance('SBILIFE')` 4 -> 2. Tests: `reality_engine/tests/test_pilot3_row_check_serve.py` (7 passed) and the existing
serving tests without a verdict table (`plugins/reality-data/tests/test_lookups_pilot3.py`, 24 passed).

### 9h. Consolidated first in pilot3_kpi; undated XBRL quarters (T-124, 8 Nov 2026)

- **pilot3_kpi orders the group figure first.** With no `basis` asked, a figure filed on both bases now comes back
  consolidated first (ORDER BY in `lookups_pilot3.kpi`, as `pilot3_fin` already defaulted). HINDUNILVR Q2FY27 Beauty &
  Wellbeing segment EBIT is stored right on both bases (consolidated 1,235 crore, results p8; standalone 1,242 crore,
  p15), but the standalone XBRL was filed four hours later and came back first, so it read as a wrong 1,242. The
  standalone row is in `tasks/regression/labels.csv` as right; the checker needed no change. Test:
  `test_kpi_gives_the_consolidated_figure_first`.
- **An XBRL quarter with no dissemination time takes the filing time.** 4,082 of `results_xbrl.quarterly` rows have
  neither `dissem_ts` nor `broadcast_ts` (newest filings, Oct 2026 onward); `fin_quarter_xbrl` and `share_capital`
  rows built from them had `known_at` NULL (q12 build: 416 and 18 rows), so every `as_of` lookup hid them.
  `gap_loop.prepare` now falls back to `filings.filing_ts` for the same file (3,759 of the 4,082 have one; it is the
  exchange's filing stamp, never later than dissemination in 98% of filings that carry both), and
  `xbrl_segments` does the same. A row still undated stays NULL and is never served under `as_of`.
- **Last resort: the file name stamp (9 Nov).** The other 323 undated rows (ULTRACEMCO Q2FY27 in u8: 45 rows) broke
  `ratios._quarters` (max over NULL known_at). `prepare.xbrl_file_ts` reads the IST stamp in the XBRL file name:
  `_DDMMYYYYhhmmss_WEB.xml` is a 12-hour clock, read as pm, so it is never earlier than dissemination (30,238 dated
  filings: equal for pm filings, 12 h late for am ones); `_YYYYMMDD_hhmmss<ms>.xml` is 24-hour. Used by
  `results_quarterly`, `results_filings` and `xbrl_segments`; `known_at_source` ends `|file name stamp`. `ratios`
  also skips an EBIT/EBITDA whose inputs carry an undated row. Test: `test_gap_loop_xbrl_file_ts.py`.
- **ratios skips an undated share count.** `ratios._valuation` crashed on a NULL `known_at` share row (q12 build,
  8 Nov); it now never uses one. Test: `test_an_undated_share_count_is_never_used`.
- **SHP known_at from the filing, not a re-broadcast (T-162).** `shp_category.known_at` is the earlier of `shp_index.broadcast_at` and the NSE file name's own submission stamp (`SHP_..._DDMMYYYYhhmmss_WEB`, `stores._shp_known`), because the index time is sometimes a later re-broadcast (ADANIPORTS 2021-09-30 filed 20 Oct 2021, broadcast 7 Jan 2022) and a strict `as_of` dropped quarters already public. The stamp is on a 12-hour clock with no AM/PM, so an hour below 12 is read as PM, and it only wins when even that reading is over an hour before the broadcast (`known_at_source` = `file name timestamp (pm-safe)`). Measured on the live stores: 29 of 198 p20 filings, 25 of 150 u8 and 34 of 202 q12 move earlier, almost all by a day or more; they take effect at the next `--part stores` rebuild. Test: `test_shp_known_at_takes_the_earlier_pm_safe_file_stamp`.
- **build_shp warns on an empty SHP folder.** Since raw files moved to Drive (7 Nov), `D:\RealityEngine\raw\nse_shp_xbrl_pilot` was empty, so the live pilot10.db had no `shp_pledge` or `shp_holder` rows and every pledge question failed. Fetch `gdrive:InfoDiffusion_archive/msi_raw/raw/nse_shp_xbrl_pilot` (591 files, 7 MB) before `--part stores`; `build_shp` now prints a WARNING when the folder is empty. Rebuilt on a pilot10 copy: shp_pledge 78 rows, shp_holder 3,372, all 10 companies.

### 9j. Year-to-date defaults, derived quarters, source-scale refusal (T-129, 8 Nov 2026)

- **A bare figure in a call or release takes the year-to-date period its own document states.** `kpi.doc_default_period`
  now ends with `_ytd_default`: a document whose text carries a year-to-date span ("for the period ended 30th
  September 2026", "nine months ended", "half-year ended", "H1/9M FYxx", "corresponding period") defaults a figure
  with no period of its own to the year-to-date period closing on the quarter its first pages name (Q1 -> Q1, Q2 ->
  H1, Q3 -> 9M). A Q4 document keeps FY, a figure whose own sentence names a period is untouched, and annual reports
  (any document over 80 pages) call it with `ytd=False` from `kpi.extract_company`, so their pages keep the page's
  headline. SBI Life: APE 117.5 billion from the Q2FY27 call is H1FY27 (was FY27); APE 185.2 and 168.8 billion and
  VNB 50.4 billion from the Q3FY26 call are 9MFY26 (were FY26). A quarterly figure whose own context says "for the
  quarter" / "in Q2" keeps the quarter: the quarterly-cue, quarter-after-comparative and T-107 ratio rules now also
  read an H1/9M default (ptype H / 9M / 6M). Measured on the pilot10 copy (control build with `_ytd_default` disabled
  vs the real build, same code otherwise): **215 periods changed** -- SBILIFE 75, KEC 46, BAJFINANCE 33, HDFCBANK 24,
  HINDALCO 21, SUNPHARMA 14, ETERNAL 1, MARUTI 1 (HINDUNILVR and INFY 0). Transitions: Q3FY26->9MFY26 60,
  Q2FY27->H1FY27 57, Q2FY26->H1FY26 51, FY26->9MFY26 19, FY27->H1FY27 11, YTD->9MFY26 5, FY27->Q1FY27 4,
  YTD->H1FY27 3, FY26/Q4FY26->9MFY26 3, YTD->H1FY26 2. The control build reproduces the live store's reported rows
  apart from one key (KEC `order_intake` 19,265 crore), so before -> after is the control -> after measurement.
- **Missing flow quarters are derived from the cumulative rows.** `kpi.derive_quarters` writes Q4 = FY - 9M, Q3 = 9M
  - H1, Q2 = H1 - Q1 per symbol / metric / dimension / basis / unit, from the best non-quarantined reported row of
  each period (highest `conf_rank`), skipped when that period's own rows disagree by more than 1%. The row is
  `extractor_rule='derived_cumulative_v1'`, `is_reported=0`, quote "FY26 242.7 - 9MFY26 185.2", `known_at` = the later
  input's. Only the named flow set `_DERIVABLE_FLOW` (APE, VNB, GWP, new business premium, revenue, PAT, EBITDA, order
  intake, new loans, export/domestic/total volumes, shipments) is derived; a stock (AUM, a book, a balance, a ratio,
  a margin) never is. 47 rows on pilot10: revenue 18, PAT 15, EBITDA 9, APE / GWP / new loans / order intake / volumes
  1 each; KEC 20, BAJFINANCE 9, HINDALCO 6, MARUTI 5, SUNPHARMA 4, SBILIFE 3. **All 47 come back quarantined** from
  `--part checks`: the checker's `quote_on_page` and `label_present` hard checks fail on the synthetic quote, so
  `pilot3_kpi` hides them until `row_checks.py` gains a derived-row rule -- it is not edited here, by the brief.
  A quote is formatted without scientific notation ("1746500", not "1.7465e+06").
- **A formula's `inputs` must be a name->value object (9 Nov).** HP workers that write answer events by hand
  (shell dead, no recorder) wrote `inputs` as a list, which crashed `number_check`; it now fails that number as
  `formula_mismatch` ("inputs must be a name->value object") and checks the rest (q12 D2: 14 such numbers).
- **A crore figure whose own source states the same digits in million fails.** `number_check.check_source_scale`
  reads a money entry's `source`; the digits of the entry found with a different explicit scale word (million / mn /
  lakh / crore / billion / bn) and the wrong amount is the fail code `source_scale_mismatch`. MARUTI-127:
  `{4136, "INR crore", "... Rs 4,136 million"}` fails; `{413.6, "INR crore", same source}` passes. Replayed over
  `D:/RealityEngine/pilot10/answer_reask/answers/*.jsonl` (136 answers): 2 failing findings, both MARUTI-127 (its
  4,136 and 18,740 crore entries, each sourced in million); no other answer gains the code.
- Tests: `reality_engine/tests/test_pilot3_kpi.py` + `test_pilot3_number_check.py` -> 123 passed and 6 `tmp_path`
  fixture errors that are a sandbox-only ACL defect (a directory created mode 0o700 is not listable; the same 6 error
  without this change); with the sandbox workaround (create temp dirs 0o755) 133 passed, and
  `test_pilot3_kpi_ratio_period.py` passes. Row-check verdicts on pilot10 `kpi_series` (reported rows): live before
  2,281 verified / 3,310 unverified / 452 quarantined; control (A off) 2,281 / 3,308 / 452; after (A on) 2,292 / 3,330
  / 427, plus the 47 derived rows, all quarantined.

**Retired reports (8 Nov 2026).** Shivam retired the 3-7 Nov reports on 8 Nov (answer checks, model-vs-store, dig, second read, re-ask, embedding, OCR, night-loop, doc-identity scans, database inventory): they are no longer in `D:\RealityEngine\reports`; copies are on `gdrive:InfoDiffusion_archive/reports/retired_2026-11-08/` under the same names.

### 9i. Price reaction and technicals computed in code (T-128, 8 Nov 2026)

The 8 Nov re-ask missed 9 of 136 answers on price arithmetic: a results filing that reached the exchange at 16:02
was read as a same-session reaction, a gap was scored close vs open, the RSI method was guessed, the last
moving-average cross was missed and a volume spike was measured against its own day. `pilot3_tech`
(`plugins/reality-data/server/lookups_tech.py`; registered and routed in `plugins/reality-data/server/server.py`;
`p3ask` runs it as `tech`) computes them once from `price_delivery` (NSE) and `index_price`:

- `reaction`: the last `limit` filings of `doc_type` (default `results`) before `as_of`, or in `start`/`end`.
  Day 0 is the filing date only when `known_at` is at or before 15:30 IST **and** that date is a session;
  otherwise the next session. Rows cover day 0 through day `sessions` (default 5): close-to-close % vs the
  previous session close, cumulative % vs the close before day 0, volume and its multiple over the mean of the 20
  sessions BEFORE day 0, delivery %, the index's same-day %, and per filing `cum_1d_pct`, `cum_5s_pct` (the
  fifth session counted from day 0) and `cum_window_pct`.
- `gaps`: sessions in `[start,end]` (default the last 365 days) with |open/prev_close-1| >= `threshold`
  (default 0.03; a number >= 1 is read as percent): gap %, close vs the previous close %, the share of the gap
  held = (close-prev_close)/(open-prev_close) (negative when the gap reverses), delivery % vs its trailing
  250-session mean, and the fill date (the first later session whose low touches prev_close for a gap up, whose
  high does for a gap down) with the price at which it filled.
- `rsi`: Wilder 14 on `adj_close` (first average = simple mean of the first 14 changes, then
  `avg=(prev*13+x)/14`), today's value, the last `window` (default 30) sessions, and the two lowest/two highest
  closes in that window with the RSI at each, plus `bullish_divergence` (lower price low, higher RSI low) and
  `bearish_divergence` (higher price high, lower RSI high).
- `ma`: SMA 50 and 200 on `adj_close` at `as_of`, the value, % above/below and the last close-vs-SMA cross date
  and direction (a cross is only reported once the SMA has its full window); `insufficient_history` when it has
  not.
- `volume_spikes`: sessions in the last 365 days with volume >= `threshold` (default 3) x the mean of the PRIOR
  20 sessions (the day itself excluded), with the multiple, close-to-close % and delivery %.
- `range`: 52-week high/low of raw `close` with dates, position = (close-low)/(high-low), % above the low and
  % below the high.

Rules shared by every kind: sessions come from `price_delivery` rows, never the calendar; `as_of` drops every
session after it; raw `close`/`prev_close` give the daily % and the gaps while `adj_close` gives the RSI, the
SMAs and the divergence points (a split must not read as a 50% fall); a prior-N mean excludes the day itself;
an unknown symbol raises the same `not_pilot3` DataError as the other pilot3 tools, and every row carries
`provenance` {table: `price_delivery`, source: `NSE <date>`, known_at}.

Measured live on pilot10 (as_of 2026-11-04) against the 8 Nov hand checks:

- ETERNAL Q3FY26 results, `known_at` 2026-01-21T16:02:01, day 0 is 2026-01-22 (the market was already closed).
- ETERNAL 2026-02-03: gap 7.83%, close +2.62% vs the previous close (an answer's -4.83% was close vs open),
  33.5% of the gap held, filled 2026-02-19.
- KEC 2026-10-26: gap up 3.43%, close +2.76%, 80.4% held, filled 2026-10-30 at the low 327.30.
- BAJFINANCE 2026-11-03 close 970.00; SMA50 999.43 (999.4 at 1 dp), SMA200 972.37 (972.4); last SMA50 cross
  2026-08-31 down, last SMA200 cross 2026-10-19 down (the 2026-09-29 down, 10-13 up, 10-14 down, 10-16 up,
  10-19 down sequence ends there).
- KEC volume spikes: 18 sessions from 2025-11-04, including 2025-11-11 at 13.01x and 2026-10-09 at 13.91x of
  the prior-20 mean.
- HDFCBANK RSI on 2026-11-03: 58.44 (the 5 Nov hand check's 58.4 is the same figure at 1 dp), no
  bullish/bearish divergence over the last 30 sessions.

Tests: `python -m pytest reality_engine/tests/test_pilot3_tech.py -q` 15 passed (a synthetic fixture exercises
every kind, the 15:30 rule and the exact Wilder recursion; the live checks above skip only when
`D:/RealityEngine/pilot10/pilot10.db` is absent); `python -m pytest
plugins/reality-data/tests/test_lookups_pilot3.py -q` 24 passed, 1 skipped; `python -m
reality_engine.scripts.p3ask --db D:/RealityEngine/pilot10/pilot10.db tech symbol=ETERNAL kind=reaction
as_of=2026-11-04` prints the JSON. No data rebuild: the tool reads existing tables, so a running reality-data
MCP serves it after a restart.

### 9k. Calc catalog: named formulas computed by code (T-135, 9 Nov 2026)

The 8-9 Nov 72-question re-ask still lost compute marks although the figures were right: BAJFINANCE-005 wrote a TTM
PAT growth of 14.12% (right 14.15%), KEC-081 set a TTM against the fiscal year it overlaps, MARUTI-023 put a
six-month balance change beside a year-on-year flow, ETERNAL-020's operating cash flow came out ten times too large,
HINDUNILVR-031 gave ROCE levels instead of the incremental ROCE, BAJFINANCE-123 called 41% up a range "upper half",
HDFCBANK-120 did the Gordon fair P/B backwards, SBILIFE-081 did not derive Q3/Q4 from 9M and FY, SBILIFE-105 called
an annualised 18.8% RoEV a half-year return and ETERNAL-113 added margin points to a PAT target ignoring tax and
depreciation. `plugins/reality-data/server/calc_catalog.py` makes each one a named formula: the caller gives the
inputs (strings like `"22,067 crore"` or `"14.5%"`, parsed and unit-checked by `calc.parse_input` / `Fraction`), and
the reply is `formula_id`, `value`, `unit`, the `formula` text with the numbers substituted, the `inputs` echoed back
as parsed, and `notes` — or `{"error", "formula_id"}`. It reads no database and re-implements no price maths (the
Wilder RSI, gaps, SMA crosses, volume spikes and 52-week range stay in `lookups_tech`; `name=list` prints them as
`see tech kind=...`).

The ids (14 numbered entries; FAIR_PB and IMPLIED_ROE are two ids, so 15 callable names):

- `GROWTH`: `now`, `before` -> `100*(now/before-1)`; refuses a zero or negative base.
- `TTM_SUM`: `q1`..`q4` + `periods` -> sum; refuses labels that are not four consecutive quarters.
- `TTM_GROWTH`: `ttm_now`, `ttm_year_ago`, optional labels -> percent; refuses two periods that overlap and names
  the overlapping quarters (KEC-081).
- `Q_FROM_CUMULATIVE`: `longer` + label, `shorter` + label -> FY-9M = Q4, 9M-H1 = Q3, H1-Q1 = Q2 (SBILIFE-081).
- `SHARE`: `part`, `total` -> percent.
- `CONTRIBUTION_TO_INCREASE`: part and total, now and before -> percent of the total change the part explains.
- `CASH_CONVERSION`: `ocf`, `pat`, `ebitda` -> ocf/pat and ocf/ebitda; one unit family for all three (ETERNAL-020).
- `INCREMENTAL_ROCE`: EBIT and capital employed, now and before -> percent on the capital added (HINDUNILVR-031).
- `RANGE_POSITION`: `x`, `low`, `high` -> percent and lower/middle/upper third (BAJFINANCE-123).
- `FAIR_PB`: `roe`, `cost_of_equity`, `growth` -> `(roe-g)/(coe-g)` (HDFCBANK-120); `IMPLIED_ROE`: `pb` + the same
  two -> `pb*(coe-g)+g`.
- `IMPLIED_GROWTH_PE`: `pe`, `payout`, `cost_of_equity` -> `g = (PE*r - payout)/(PE + payout)`.
- `ANNUALISE`: `rate`, `months`, `method` simple|compound -> percent, always labelled "annualised" (SBILIFE-105).
- `SAME_SPAN_GROWTH`: balance and flow, now and before, with four period labels -> both growths; refuses when the
  spans differ (MARUTI-023).
- `PROFIT_BRIDGE_MARGIN`: `target_pat`, `revenue`, `tax_rate`, `depreciation`, `finance_cost`, `other_income` -> the
  EBITDA margin the PAT target needs: `pat/(1-tax) + depreciation + finance cost - other income`, over revenue
  (ETERNAL-113).

Percent inputs parse to fractions and percent outputs stay percent points (14.15, not 0.1415); `value` is unrounded
(the text shows 2 decimals). Served by `p3ask` as `catalog` (`reality_engine/scripts/p3ask.py`); the reality-data MCP
tool is wired by the controller after review. Commands:

    python -m reality_engine.scripts.p3ask --db D:/RealityEngine/pilot10/pilot10.db catalog name=list
    python -m reality_engine.scripts.p3ask --db D:/RealityEngine/pilot10/pilot10.db catalog name=GROWTH \
        'inputs={"now": "22,067 crore", "before": "19,332 crore"}'

Tests: `python -m pytest -q reality_engine/tests/test_calc_catalog.py` 30 passed, at least one per id, including the
exact evidence cases (GROWTH 14.147527% -> 14.15, the TTM Q2FY27 vs FY26 refusal with Q3FY26/Q4FY26 named, Q4FY26 =
28 from FY26 100 and 9MFY26 72, cash conversion 1.727x and 0.523x, range position 40.68% middle third, fair P/B 1.5,
implied ROE 16.25%, annualised 18.8%, and the MARUTI-023 span refusal); `test_p3ask.py` 2 passed.

### 9l. Linked and missing transcripts (T-157, 9 Nov 2026)

`reality_engine/pilot3/linked_transcripts.py` fills the two holes behind the 19 pilot20 answers that failed
only because the call text was not held. It takes `--store <pilot3 db> --raw-out <dir> [--symbols A,B]` and
`--apply`; without `--apply` it prints the plan and writes nothing.

- **Linked stubs.** A `doc` row of `doc_type='transcript'` with `pages <= 2` is a cover letter: its page text
  and its PDF link annotations name the real transcript. The text layer splits the URL mid-token
  (`.../Q2-FY25-` then `Earnings-Call.pdf`), so the fragments are joined until `.pdf`; link annotations win
  when both exist (IHCL's text names the wrong file, its annotation the Q2 FY26 one). A one-page PDF reached
  from BSE is followed through its own link once. The downloader sends the browser User-Agent from
  `config.DEFAULT_HEADERS`, makes at most one request a second per host and retries 429/5xx; a non-PDF body is
  refused.
- **Missing calls.** Each `results` filing since 2024-04-01 is grouped with the other filings of the same call
  (intimation, outcome, audio link; gaps up to 45 days, a quarter is about 90) and the call is missing when no
  transcript of three pages or more falls inside the group or the 21 days after its last filing. The
  transcript announcement is looked for on BSE (`fetch_corporate_announcements` for the company's `bse_code`,
  subject containing *transcript*; the window end is clamped to today because BSE answers HTTP 400 for a future
  `strToDate`), then on the investor page named by an earlier stub link.
- **Apply.** `--apply` stores each PDF through `raw_store.store_bytes` (content-addressed; the sha index lives
  under `--raw-out`) and inserts one `doc` row plus one `doc_page` row per page, with
  `INSERT INTO doc_page_fts(rowid, text)` after each page exactly as `statements._import_pages` does. A linked
  stub keeps the stub's `known_at` for both `filing_date` and `known_at` (the link was public then, never
  earlier); a BSE filing takes its own `DissemDT`. A sha already in `doc` is skipped, so a second run adds
  nothing.

Measured 9 Nov 2026 on a copy of `D:\RealityEngine\p20\p20new.db` (348,594,176 bytes; the live file was only
read): `python -m reality_engine.pilot3.linked_transcripts --store .tmp/p20_copy.db --raw-out
.tmp/transcripts_raw --apply` added **16 documents and 300 pages, 0 skipped** (135 to 151 transcripts).

| company | stubs | resolved | missing calls looked | calls found | pages |
|---|---|---|---|---|---|
| ADANIPORTS | 13 | 13 | 0 | 0 | 240 |
| INDHOTEL | 2 | 1 | 0 | 0 | 17 |
| HAVELLS | 1 | 0 | 3 | 0 | 0 |
| APOLLOTYRE | 0 | 0 | 1 | 1 | 23 |
| PIDILITIND | 0 | 0 | 1 | 1 | 20 |
| COALINDIA | 0 | 0 | 9 | 0 | 0 |
| TITAN | 0 | 0 | 1 | 0 | 0 |

The 14 linked stubs came from adaniports.com (13) and ir.ihcltata.com (1). The two unresolved: HAVELLS
2026-01-13 is a conference-call intimation with only a Chorus Call registration link (not a transcript cover),
and INDHOTEL 2022-08-17 points at `www.primeinfobase.in`, which no longer resolves. The two calls found are
PIDILITIND Q2 FY27 (BSE transcript of 2026-11-05, 20 pages) and APOLLOTYRE Q2 FY27 (BSE announcement, 23
pages; its results filing of 2026-11-04 was still inside the window). The 13 calls reported not found
(COALINDIA 9, HAVELLS 3, TITAN 1) have no BSE announcement whose subject says *transcript* inside their 21-day
window; they are listed with their anchors so the next round can widen the subject filter instead of repeating
the search.

Tests: `python -m pytest -q reality_engine/tests/test_linked_transcripts.py` **5 passed** — the split-URL
rebuild from the Adani stub shape and from a link annotation, the annotation-over-text order, the 21-day
missing-call rule on a fixture (including a 28-day intimation/results group), and `--apply` on a tiny store
adding `doc` + `doc_page` with the FTS finding a new-page word, the stub `known_at` unchanged, and a second run
adding nothing. No network in tests (the downloader and the BSE lookup are monkeypatched); typecheck clean.
The live `p20new.db` still needs the `--apply` run by the controller after review.

**Follow-up 9 Nov 2026 (Wolf).** Two causes behind the 13 not-found calls. (1) `BSEClient.fetch_corporate_announcements`
read page 1 only; the endpoint answers 50 rows a page with the full count in `Table1[0].ROWCNT` (TITAN Dec 2025 - Nov 2026:
145 rows, 95 dropped). It now reads every page up to `ROWCNT` (cap 40 pages); test `test_bse_announcements_paging.py`.
(2) HAVELLS files its call transcript as *Analyst / Investor Meet - Outcome* (15-17 pages, about six days after results;
the one-page outcome on results day is the audio link). `bse_candidates` now returns subject-*transcript* filings first,
then meet-outcome filings, and `_missing_item` accepts a meet-outcome PDF only when its first pages read as a call
(`Moderator`, `transcript`, `conference call`). Dry run on `p20new.db`: HAVELLS 3 of 3 calls found, but all three are
**already held** as `doc_type='announcement'` (the store typed them from the BSE category). Across stores 16 call
transcripts are typed `announcement`/`results` (pages >= 3, `Moderator:` in the first three pages): p20 7 (HAVELLS 6,
INDHOTEL 1), u8 5 (CHOLAFIN 3, CIPLA 1, ULTRACEMCO 1), q12 4 (KIMS, SAIL, UBL 2). T-159 now types them from their
pages in `docs_collect` (section 9m): a measured 15 of those 16 on the live stores.
COALINDIA files no transcript on BSE (only meet intimations); its calls need the company website. TITAN 2026-10-06 is
the quarterly business update, not a results filing, so it is not a missing call.
Applied 10 Nov 00:20 on copies of u8 and q12, then swapped in (old files kept as `<set>_before_t157_2026-11-09.db`): u8 80 -> 82 transcripts (PERSISTENT stub, BEL Q2 FY27 call; +59 pages), q12 164 -> 180 (WELSPUNLIV 12 stubs, UBL 2, APOLLOHOSP 1 stub + 1 call; +245 pages); integrity_check ok on both.

### 9m. Misdated and mistyped documents (T-161/T-159, 10 Nov 2026)

A scan of every transcript/deck/results document (pages >= 3) on p20, u8, q12 and pilot10 for documents whose latest
printed date on pages 1-3 is two or more years before `filing_date` found 6 in q12, all transcripts with a date-only
`known_at` from the August/September 2026 company-website crawl (`.../NSCRIPT/2026...AnnPdfOpen.aspx.pdf`): TATAELXSI
calls of 2018-07-27 and 2018-01-22, APLAPOLLO 2017-12-13, EDELWEISS 2018-10-29, 2016-11-11 and 2016-08-10, all stored
as filed 2026-08-28/29 (the Tata Elxsi one was the only source of "JLR is 24% of revenue", answered as current). The
live q12 store now carries the printed call date as `filing_date` and `<date>T23:59:59` as `known_at` on `doc` and on
every derived row of those documents (doc_page, transcript_statement, kpi_series, guidance, ...); the old file is kept
as `q12_before_t161_2026-11-10.db`.

**The builder applies both rules now (T-161 + T-159).** `docs_collect.reconcile_doc` (called at the end of `collect`
and `collect_manifest`, so a rebuild and a profile build behave the same) reads pages 1-3 after extraction:

- **Type.** A document of 3+ pages whose first pages `classify_type()` reads as a transcript *and* which print the
  call's own moderator line (`doc_identity.moderator_line`, the marker the T-157 audit used) becomes
  `doc_type='transcript'` whatever the BSE category; the record's type is kept as `source_record.record_type`. The
  moderator line is required because the first draft — `classify_type()` alone — retyped 144 documents on p20, 137 of
  them wrongly: a call *intimation* says "followed by a Q&A session" (TITAN, BHARTIARTL, APLAPOLLO) and a results
  release says "a conference call will be held" (HINDALCO, ASIANPAINT). `Q&A`/`Management participants` are not
  sufficient markers either (INDHOTEL's deck agenda, ADANIPORTS' participant list).
- **Date.** A transcript whose printed call date (`call_dates.call_date`, the same reader the build already uses to
  raise a transcript's date to its call, T-049 review) is more than 120 days *before* `filing_date` takes that date as
  `filing_date` and `<date>T23:59:59` as `known_at`; `source_record.date_source='printed'` plus
  `record_filing_date`/`record_known_at`/`record_type` record the change. A date is never moved later and only pages
  1-3 are read, so a 2026 call that mentions 2018 on page 5 keeps its date. The date rule is a transcript's only: a
  results PDF prints its period end (SAIL 2020-09-14 -> 2015 comparatives only, and SAIL 2021-10-29 -> 2021-06-30 is a
  121-day gap) and a deck prints its period start (a HINDALCO Q4 FY25 deck filed 2025-11-21 prints "April 1, 2025"),
  so both were false positives of the first draft.

**Measured read-only** (`python -m reality_engine.pilot3.docs_collect --measure`, 10 Nov 2026, nothing written):
p20/p20new.db 0 re-dated / 7 re-typed (HAVELLS 6, INDHOTEL 1); u8/u8.db 0 / 4 (CHOLAFIN 3, ULTRACEMCO 1); q12/q12.db
0 / 4 (SAIL, KIMS, UBL 2); pilot10/pilot10.db 0 / 0. 0 re-dated because the live q12 store already holds the six
hand-fixed dates (checked: `call_date` reads 2017-12-13 on the APLAPOLLO page and every one of the six now reconciles
to itself). The audit's 16th document (u8 CIPLA) is not retyped: no CIPLA document typed `announcement`/`results` in
u8 prints a moderator line on its first pages (its transcripts already read `transcript`). p20, u8 and pilot10: 0
misdated found. Two SAIL 2020 results PDFs print 2015 comparatives only and are not misdated.

Tests: `reality_engine/tests/test_docs_collect.py` (15: the six date cases, the covering letter dated at filing, a
later printed date never moving a date, the page-5 mention, the HAVELLS meet outcome, the one-page audio link, the
call intimation, the results release, the results PDF, the deck period start) and
`reality_engine/tests/test_pilot3_docs.py::test_printed_pages_correct_the_record` (real PDFs through `collect`: a
re-filed 2018 call re-dated and typed, the page-5 mention ignored, the one-page meet outcome unchanged).

**Still to run on the controller (the live stores are not written here):** a `docs_collect` rebuild of p20, u8 and
q12, then `build --part transcripts` and `--part guidance` for the 15 retyped documents, so `pilot3_statements` and
the guidance rows see them; `--measure` itself writes nothing.
