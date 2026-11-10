# Store v2 schema contract (T-131)

Owner: Wolf (Opus). Status: DRAFT, 9 Nov 2026 02:30 IST, waiting for Shivam's OK. DDL: `reality_engine/v2/schema_v2.sql`
(applied by `reality_engine.v2.schema.create`, test `reality_engine/tests/test_v2_schema.py`). Plan and lanes:
`D:/RealityEngine/reports/2026-11-09_v2_design_plan.html`.

Every v2 lane (T-132 table store, T-133 label dictionary, T-134 period engine, T-135 calc catalog, T-137 guidance,
T-138 notes, T-140 events, T-141 disclosure map) writes to these tables and nothing else. A change to the contract is
one commit by its owner, with this file and the DDL together.

## 1. Why v2

Today's store extracts the KPIs we have words for, and the answering model reads tables and does sums itself. Of the
pilot10 re-asks (8 and 9 Nov: 136 then 72 questions), the faults that remain fall into five shapes, each a table
below: a printed figure the store has no row for (Stage 2 share, retail CASA, contribution margin, strong-hybrid
share); a label read wrong (Infosys growth and utilisation labels swapped twice); a period the model had to derive
(SBI Life Q3/Q4 APE from 9M and FY, TTM against FY); a computation done by hand (Eternal cash conversion ten times
too large, Wilder RSI, gap fill, fair P/B); and a chain the store cannot hold (policy since a date, rating rationale,
guidance a year ago, parent guarantees). A correct "not disclosed, searched X" counts as right, so non-disclosure is
stored too.

## 2. Layout (T-145)

- **Per-company file** `<root>/company/<ISIN>.db` (SQLite, WAL): every table in `schema_v2.sql`. No question reads
  more than one company's file, so the hot path is a primary-key lookup (1-5 ms) and full-text search stays small.
- **Catalog** `<root>/catalog.db`: company, ISIN history, symbol at time, sector family, file path. Routes a symbol,
  BSE code, ISIN or name to its file.
- **Market and screens**: DuckDB over Parquet split by year (prices, delivery, valuation by day, index, holdings by
  quarter) plus a column export of `fact` for "which companies" screens (0.3-0.8 s).
- **Parsed-once cache** (T-147): each document's parsed tables, sections and statements kept beside the store,
  keyed by `doc.sha256` and `doc.parse_version`, so a schema change re-maps without fetching PDFs from Drive.

## 3. Tables, what each answers, and the failed questions behind it

Each table names at least five real failed or partly-answered questions (qid from
`D:/RealityEngine/reports/2026-11-08_t124_reask_136_partials_answers.csv` and `2026-11-09_t124_reask2_72_answers.csv`).

| Table | Holds | Failed questions it fixes |
|---|---|---|
| `entity`, `entity_alias` (T-149) | the company, its segments, subsidiaries, brands, geographies, JVs; listed ISIN and stake | BAJFINANCE-011 (BHFL share of PAT), HINDALCO-048 (Novelis ratings), HINDALCO-095 (Novelis US mix), ETERNAL-100 (Blinkit margins), ETERNAL-091 (Blinkit customers), HDFCBANK-119 (listed subsidiaries' value), INFY-051 (subsidiary ratings) |
| `period` (T-134) | exact start/end of every value; Q, H1, 9M, FY, TTM, month, point | SBILIFE-081 (Q3/Q4 APE from 9M and FY), SBILIFE-010 (Q3 FY26 left out), KEC-081 (TTM against FY), MARUTI-023 (six months against YoY), BAJFINANCE-118 (year-ago ROE picked from the wrong quarter), ETERNAL-106 (quarterly share-based cost) |
| `doc`, `doc_page` | documents keyed by content hash, page text with section names | HDFCBANK-094 (branches on results p21), HDFCBANK-097 (NPA on p2), KEC-121 (FX table on the AR page), INFY-051 (guarantee on AR p267), HINDUNILVR-045 (ESG agencies) |
| `table_cell` (T-132) | every printed table cell, label and header verbatim, value in base units | BAJFINANCE-098 (Stage 2 share), HDFCBANK-108 (retail CASA), ETERNAL-100 (contribution margin), KEC-011 (business-line mix from the deck), INFY-100 (geography growth table), MARUTI-100 (strong-hybrid share), SBILIFE-119 (group protection) |
| `label_map` (T-133) | printed label to metric per sector family, Opus-approved, with a review queue | INFY-100 and INFY-106 and INFY-108 (reported vs constant-currency, including vs excluding trainees swapped), HDFCBANK-108 (retail CASA), MARUTI-100, SBILIFE-119, ETERNAL-091 |
| `metric_def` (T-133) | what each metric is: `flow`, `stock`, `ratio`, `per_share`, `count` or `price`, with its unit kind, so the period engine sums only flows | SBILIFE-081 (Q3/Q4 APE), BAJFINANCE-005 (TTM PAT), KEC-081 (TTM against FY), ETERNAL-020 (cash conversion), INFY-118 (cumulative payout against target) |
| `fact`, `fact_evidence` (T-146, T-150) | one figure per entity, metric, period, basis, definition; several sources agree or are flagged; base units | MARUTI-127 (other income ten times too large), ETERNAL-020 (operating cash flow scale), HINDUNILVR-053 (standalone RPT against consolidated net worth), MARUTI-083 (net debt without investments), BAJFINANCE-006 (other opex path misread) |
| `derivation` (T-134, T-135) | derived quarters, TTM, YoY, shares, stored with formula and input fact ids | SBILIFE-081, BAJFINANCE-005 (TTM PAT growth), KEC-081, HINDUNILVR-031 (incremental ROCE), ETERNAL-020 (cash conversion), INFY-118 (cumulative payout vs target) |
| `statement` | verbatim quotes with speaker, role, the analyst question, topics, entity | ETERNAL-015 (guidance across four calls), SBILIFE-091 (VNB walk drivers), HDFCBANK-016, KEC-109, INFY-109, SUNPHARMA-103 |
| `guidance` (T-137) | each forward target, the call it was said on, the target it revises, the outcome fact | ETERNAL-015, SBILIFE-099 (year-ago guidance not found), BAJFINANCE-103, HINDUNILVR-015, KEC-109, INFY-109 |
| `event`, `event_entity` (T-140) | dated results, calls, orders, policies, tariffs, rating actions, deals; day 0 precomputed | MARUTI-085 and MARUTI-086 (chain started before the window), HINDALCO-086, ETERNAL-066 (day 0 after a post-close filing), ETERNAL-067 (largest announcements), BAJFINANCE-112 (Allianz completion), KEC-096 (government capex) |
| `note_item` (T-138) | AR notes as typed rows: guarantees, contingent liabilities, related parties, FX sensitivity and exposure, ratings, borrowings by currency, share-based payments | INFY-051, KEC-121, HINDUNILVR-053, HINDALCO-025, HINDALCO-048, MARUTI-051, ETERNAL-106 |
| `disclosure` (T-141) | per entity, metric and period kind: disclosed, not disclosed, not held, stopped; what was searched | SBILIFE-124 (new business strain), SUNPHARMA-108 (NLEM share), SUNPHARMA-129 (US-only specialty), ETERNAL-107 (gig-law cost per order), KEC-052 (covenants), HINDUNILVR-095 (rural share), MARUTI-101 (domestic EV volume), SUNPHARMA-100 (chronic share) |
| `outside_doc` (T-139) | rating rationales, monthly industry data, budget and PIB lines, regulator circulars | BAJFINANCE-046 and MARUTI-051 (rating rationale and triggers), KEC-096 (transmission and railway capex), HINDALCO-048 (Novelis agencies), HINDUNILVR-095 (monsoon, rural) |
| `question_template` (T-151) | question patterns compiled to the facts, calcs and events they need; a script reports which the store can fill before any answering | every class above; first use: the 1,305 pilot10 questions and the pilot20 set (202 questions, 9 Nov) |

Market tables (Parquet, unchanged in content from today's `price_delivery`, `valuation_daily`, `index_price`,
`shp_*`, `bulk_block_deal`, `insider_trade`) answer ETERNAL-133 (gap held by close), KEC-070 (gap fill), KEC-064
(volume against the prior 20 sessions), HDFCBANK-068 and SBILIFE-066 (Wilder RSI), HINDUNILVR-080 (trailing PE with
a one-off), SUNPHARMA-039 (FPI/MF path by quarter). The calculations over them are calc-catalog entries (T-135), not
stored rows.

## 4. Rules the tables enforce

1. **Point in time.** `known_at` on every fact, statement, guidance, note and event; a restatement is a new fact row
   and the old row gets `superseded_at`. `as_of` reads `known_at <= as_of AND (superseded_at IS NULL OR
   superseded_at > as_of)`. Index `(entity_id, metric, period_id, known_at)`.
2. **Base units at write.** `fact.value` is rupees, units, tonnes, percent points; `table_cell` keeps `value_text`,
   `unit_text` and `scale` so the page can be shown. The read side never converts (T-150).
3. **One fact, many sources.** The same figure in deck, results and press release is one `fact` with several
   `fact_evidence` rows; a source printing a different number is kept with `agrees=0` and fails the row check.
4. **Derived rows hold formula and input ids only** (`derivation`), so a restatement of an input re-derives; the
   model never subtracts or sums.
5. **Labels map once, by family.** A `table_cell` becomes a `fact` only through an approved `label_map` row; an
   unmapped frequent label lands in the queue for Opus. Model output may propose a mapping, never a value.
6. **Verbatim first.** Management, officials and regulators are stored as said (`statement`, `note_item.quote`,
   `outside_doc.text`); the model judges at query time.
7. **Not disclosed is a fact.** `disclosure` rows are written by a script that searched named document types and
   periods; the answer cites the search.
8. **Checks.** `fact.check_status` is set by the independent row checks (T-142): parts sum to totals, printed QoQ
   and YoY columns agree with derived rows, XBRL reconciles. A fact that passes is verified without a second source.

## 5. Keys and vocabularies

- `metric`: snake_case ids from `label_map`; financial lines reuse today's `line_item` names (`revenue_from_operations`,
  `pat`, `ebitda`, `finance_cost`...) so pilot3 tools keep working during the move.
- `metric_def.kind`: `flow` (P&L lines, volumes, capex, cash flow) is the only additive kind; `stock` (balance sheet,
  AUM, order book, counts at a date), `ratio`, `per_share`, `count` and `price` are never summed across periods.
  `unit_kind` names the unit without a scale (`inr`, `usd`, `pct`, `count`, `tonnes`, `days`, `x`, `inr_per_share`).
- `dimension`: `key=value` pairs joined by `;` in a fixed order (`geography`, `segment`, `product`, `measure`,
  `currency`), empty for the whole company.
- `basis`: standalone, consolidated, segment, na. `definition`: reported, adjusted, company_stated, plus metric
  variants (incl_trainees, excl_trainees, constant_currency).
- `period_id`: `start/end` (or `/end` for a point). Fiscal labels are derived from dates.

## 6. Order of work after the OK

1. T-132 prototype (Wolf) on three pilot20 decks and one results PDF: `table_cell` rows, bbox, base units.
   (Shipped as `reality_engine/v2/table_cells.py` and `build_cells.py`, section 10.)
2. T-134 period engine and T-135 calc catalog in parallel (two code workers is the cap).
3. T-133 label families for the pilot20 sectors, Opus approval per family (shipped 9 Nov: section 11).
4. Pilot20 v2 build, same questions as the baseline (`D:/RealityEngine/p20/answers/questions_{P,Q}.json`), grade,
   delta report. Then a fresh unseen set (T-144).

## 7. Shivam's decisions (9 Nov 2026, 16:50)

- **Contract approved (T-131 OK).** Work order as in section 6; T-134 period engine started first (DeepSeek worker), T-132 table store next.
- **Semantic search runs alongside the table store, not after it.** Page vectors (Nemotron 8B text, `<store>/embed/`) are part of v2: built per `doc.sha256` page at ingest, served by `pilot3_semantic` today and the v2 read tools later. Measured on pilot20 re-asks (A+B, 78 questions): 33 of 54 partly/wrong answers became right, 22 of 24 right answers stayed right; with semantic 28/44, without 5/10 (no clean control).
- **`outside_doc`: free sources only, lean on disk.** Rating rationales from agency sites, industry monthly data (SIAM, cement, DGCA), regulator circulars; keep the text and key figures, not bulk PDFs or full archives; nothing paid without his OK.

## 8. T-132 prototype findings (9 Nov 02:20, Wolf)

Prototype `tasks/v2/T-132_proto_cells.py` (word boxes only, no model, ~0.05 s a page): rows from word y-centres,
numeric tokens merged when the text layer splits them, a table block = a run of rows with two or more numbers,
column anchors = clusters of the numbers' right edges, header = words in the six rows above assigned to the nearest
anchor, a printed row-number column dropped, label = words left of the first column, section rows carried as
`section > label`. On the October pilot20 decks and results:

| Document | Pages | Cells | No column | No header |
|---|---|---|---|---|
| Havells Q2 FY27 information update | 10 | 447 | 0 | 0 |
| Adani Ports Q2 FY27 deck | 58 | 1,234 | 73 | 87 |
| Coal India Q2 FY27 deck | 53 | 676 | 69 | 69 |
| HDFC AMC Q2 FY27 deck | 41 | 351 | 25 | 82 |
| Indian Hotels Q2 FY27 deck | 48 | 447 | 9 | 44 |
| Pidilite Q2 FY27 deck | 42 | 188 | 10 | 10 |
| Asian Paints Q2 FY27 deck | 31 | 25 | 5 | 7 |
| Asian Paints Q2 FY27 results (standalone + consolidated) | 19 | 842 | 40 | 43 |

What it shows for the T-132 brief:
1. Ruled and aligned tables (results statements, segment tables, information updates) come out right: Havells p5
   segment revenue 36 of 36 cells with the right label and period header; Asian Paints results p5 every P&L line with
   its label.
2. `pymupdf.find_tables` is not enough: the default finds no table in the Havells deck (no ruling lines) and the
   `text` strategy splits numbers ('2, | 028').
3. Headers need the full stack: the period row ('30.09.2026') is found, the span row above it ('Quarter ended',
   'Half year ended') sits more than six rows up or spans several columns; a header must be built from every row
   between the previous block and this one, with spanning text assigned to all columns under it.
4. Infographic slides (Asian Paints deck, Indian Hotels p7 call-outs) are not tables: numbers with arrows and labels
   scattered. They need a separate call-out reader (number + nearest label + slide title), or stay page text only.
5. A section label must end where a new numbered row group starts ('Expenses >' stuck to the tax lines).
6. The same deck is often filed twice (Coal India 29 and 30 Oct, identical cells): build by `doc.sha256`, not by filing.

The production version that fixes findings 1-6 and adds units, scale, periods, basis and the build CLI is section 10.

## 9. Period engine (T-134, 9 Nov 2026)

`reality_engine/v2/periods.py` fills `period`, `fact` (kind `derived`) and `derivation`; tests
`reality_engine/tests/test_v2_periods.py`. `period_row(start, end, fy_end_month=3)` returns the `period` row and
`fiscal_label` its label. The Indian FY ends 31 March; `fy_end_month=12` labels a December-year company (there
2026-01-01..2026-03-31 is Q1FY26). A point (`start=None`) is kind POINT and label `30 Sep 2026`; a rolling twelve months that is not the fiscal year is TTM; a span that is no fiscal shape
raises `ValueError` unless `allow_other=True` (kind OTHER).

`derive(conn, entity_id, metric, dimension='', basis='na', definition='reported', additive=True, as_of=None)`
writes derived facts for one key and returns `{"written", "conflicts", "skipped"}` (the caller commits). Formula ids,
inputs in formula order: `Q_FROM_H1_LESS_Q1` (Q2 = H1 - Q1), `Q_FROM_9M_LESS_H1` (Q3 = 9M - H1),
`Q_FROM_FY_LESS_9M` (Q4 = FY - 9M), `H2_FROM_FY_LESS_H1`, `TTM_SUM4Q` (four consecutive quarters),
`TTM_FY_PLUS_YTD_LESS_PRIOR_YTD` (FY + current YTD - prior-year YTD), `YOY_PCT` (same kind of period one year
earlier), `QOQ_PCT` (quarters only). `derivation.input_ids` is the JSON list of input fact ids.

Rules: only additive (flow) metrics get sums and differences; `additive=False` writes only YoY and QoQ. A
reported/stated value for the target period is never replaced: the engine compares, and when the two differ by more
than 0.5% writes `derived X vs reported Y` on that row's `check_detail` only (value and status unchanged). A
conflict -- two current facts for one key and period with different values -- blocks every formula that needs the
period and is returned in `conflicts`; ambiguous derivations are listed in `skipped` with a reason. When two
formulas reach the same period with the same value the second writes nothing (`agrees_with_derivation`); when they
disagree it writes nothing and reports `derives_disagree`. Inputs must
share a unit, and a derived row takes its latest input's `known_at`. YoY and QoQ store percent points in
`unit='pct'`; being a different measure from the level, their fact row carries `definition='<definition>:yoy_pct'`
(or `:qoq_pct`) so it never collides with the reported level. A derived fact feeds no other derivation except
`TTM_SUM4Q`, which may sum derived quarters and records their fact ids. `as_of` reads only the facts visible that
day (`known_at <= as_of` and not superseded then), so a year-ago figure is the one known at that date. Re-running
writes nothing new.

The read-only report `reality_engine/v2/period_report.py`
(`python -m reality_engine.v2.period_report --db <pilot3 store> [--symbol SYMBOL]`) maps
`kpi_series` into an in-memory v2 file (value x scale, period from `fiscal_period`), runs `derive` per key and prints
per-symbol written / conflicts / skipped counts plus the SBILIFE `ape` rows; it opens the store with
`reality_engine.db.readonly.connect_ro` and writes nothing back.

## 10. Table store (T-132, 9 Nov 2026)

`reality_engine/v2/table_cells.py` turns the text layer of a PDF page into `table_cell` rows: no model, no OCR,
no `pymupdf.find_tables` (it finds no table in an unruled deck and splits numbers, section 8). `extract(pdf_path,
filing_date=None, stats=None) -> list[dict]` returns one dict per cell with the `table_cell` columns except
`cell_id`/`doc_key`; `extract_page(page, pno, filing_date=None)` is the page pass and
`period_from_header(header, filing_date=None)` the period resolver. `reality_engine/v2/build_cells.py` reads the
`doc` rows of a pilot3 store read-only (`reality_engine.db.readonly.connect_ro`), hashes each PDF, skips a sha256
already in that company's file (the same deck is often filed twice) and writes `doc`, `period` and `table_cell`
into `<out>/company/<ISIN>.db` (ISIN from the store's `company` table) created with `reality_engine.v2.schema`:

```bash
python -m reality_engine.v2.build_cells --store <pilot3.db> --out <dir> \
    [--since 2025-04-01] [--types deck,results] [--symbols A,B]
```

A page with no text layer is counted, not OCR'd. A PDF that crashes pymupdf is logged and skipped; ten of them stop
the run.

Rules, each fixing a prototype finding in section 8:

- **a. Header stack.** The stack is built upward from the table and a row is kept only when its words lie inside
  the table's x-range (left edge = first column's left edge, right edge = last column anchor + 1.5 column gaps):
  words wholly outside are trimmed, a word running across either edge drops the row. A row is dropped when it is
  prose (one run of eight or more words with no digit, or a line ending in `.`), when it carries a non-date figure
  (a slide call-out such as `Rs 353 crores`), or when it names no date, period, unit or audit status; a wrapped
  date half (`31 2024`, inside a month row) is not a call-out. Three consecutive dropped rows stop the stack and the
  stack holds at most five rows. A group heading printed over its columns ("Quarter ended", "Nine months ended",
  "As at") belongs to the one column whose centre is nearest it, so two headings over one table never both name a
  column; a single heading applies to every column. **Every header phrase is placed by x-position, never by order**:
  a phrase owns each column centre inside its own x-span (a long heading owns two columns), else the nearest column
  within the column tolerance, else nothing - so a date line the text layer split onto a second y-row still lands on
  its own column. When a block is too short to sample every column (two of five anchors) and the header prints a full
  date row, those date phrases become the columns. `col_header` joins the rows top to bottom with `' > '`, e.g.
  `'Quarter ended > 30.09.2026'`. A statement continued on the next page (or a second table on the page with no header
  of its own) reuses the last header set seen. A measure group row printed over its period sub-columns
  (`REVENUE | EBITDA | EBITDA MARGIN`) is kept when it sits directly above a period header row and enters `col_header`
  as `measure=<text>`, so a legal-entity deck's `UOH Inc. - USA 19` says it is EBITDA.
- **b. Section labels.** A section label ("Expenses") ends where a new numbered row group starts: the first token is
  a row number (`2`, `II`, `IV`, `(2)`) or a parenthesised roman numeral (`(iv)`) at the same indent; a deeper
  `(i)`/`(ii)` stays inside the section, and lettered sub-labels (`(a)`, `(b)`) always do. The printed row-number
  column is dropped from `row_label` and from the cells. A label line printed under a row, or above the row whose
  numbers sit on its own line, belongs to that row: it is joined into that row's `row_label` (`Debtor Turnover
  Ratio (no. of months of Gross Sales)`), never used as the next row's section.
- **c. Tokens.** Figures split by the text layer merge (`2, 028` -> `2,028`, `1 ,234.5`, a lost thousands separator
  `5 088`); `(1,234.5)` and `-1,234.5` are negative; `-` / an en dash is value NULL with `value_text` kept; `12.3%`
  is percent. A comma-grouped figure must follow Western (`1,234,567`) or Indian (`12,34,567`) grouping exactly
  (last group three digits, earlier groups two or three consistently); anything else keeps `value_text` with
  `value` NULL (`860,19`, `44,86`). A date fragment (`31,2026`, `30.09.2026`, `31,`) is not a cell at all.
- **d. Unit and scale.** The scale word is read anywhere in the header rows and the lines above the table, tolerant
  of the text layer splitting the currency (`f Lakhs` from `(₹ in Lakhs)`) and of one stray trailing letter
  (`Croresl`): `Rs. in crore`, `₹ in Crores`, `(Rs in Lakhs)`, `INR Mn`, `Rs. Million`, `(Amount in ₹ crore)`;
  else the page's top 15%, else the row label (`EBIT ( ₹ crores)`). Scale crore 1e7, lakh 1e5, million/mn 1e6,
  billion/bn 1e9, thousand 1e3; percent stays in percent points (`unit_text='%'`, `scale=1`); no unit found means
  `value` and `scale` are NULL, never guessed. A row that names its own unit keeps scale 1 and that unit, and the
  row's own label decides it (not a section heading it sits under): a per-share row is `inr_per_share` (a share
  capital / face value row stays money), a count / `No. of` / tonnes / MW / stores / key row is `count`, a
  ratio / times / turnover / days row is `ratio`, an `in Rs` / `₹ per tonne` row is `Rs`, a per-tonne / per-unit /
  per-key / per-room-night / `ARPU` / `ARR` / `RevPAR` / `realisation` row is `Rs` (money per unit, scale 1), and a
  `US$ Mn` row is `USD million`.
- **e. Period.** `period_id` comes from the column header and the document date through `periods.period_row`:
  `30.09.2026` / `30-Sep-26` / `Sep 30, 2026` under `Quarter ended` -> that quarter, `Half year ended` -> H1/H2,
  `Nine months ended` -> 9M, `Year ended` -> FY, `As at 30.09.2026` -> POINT; `Q2 FY27` / `H1 FY27` / `FY26`
  labels directly. Wrapped header lines are assembled before the date is parsed (`March 31,` over `2026` gives
  `/2026-03-31`, a month row over a day/year row resolves, `Asat` is `As at`), and `Q1 25-26` / `Q2 26-27` (quarter
  of FY 2025-26 / 2026-27), `FY25-26`, `9M 25-26`, `9M FY27`, `H1 26-27`, `Dec-24`, `Jun-26`, `Mar'24` resolve.
  `YTD FY26` is the fiscal year to the latest quarter end before the filing date (9M FY26 for a January filing). A
  bare date header is the quarter ending that day in a results P&L and a POINT on a balance-sheet page or a deck; a
  bare `9M` / `FY` / `Quarter ended` takes the printed FY range or the latest period ending before the filing date.
  `Year ended` / `Year Ended` / `twelve months` is FY and its text-layer garble `Vear Ended` is FY too; `Nine months`
  is 9M and `Half year` / `Six months` is H1; only a bare date with no span text keeps the quarter rule. A balance or
  segment asset/liability row (`Segment Assets`, `Segment Liabilities`, `Statement of Assets and Liabilities`,
  `balance sheet`, `Total assets/liabilities/equity`, `Net worth`), or a page titled Balance Sheet, is a POINT on the
  column's own printed date (or the end date of a `Q1 FY27` / `9M 25-26` header), never the quarter's flow.
  A header date that does not parse to a real date within three years of the filing date (the file's own date when
  given) is dropped, never guessed. An unresolved header leaves `period_id` NULL, and a cell whose header names no
  resolvable period is not stored.
- **f. Basis.** `standalone` / `consolidated` from the page title text (top 20%) when printed, else NULL.
- **g. Infographic.** A table block needs at least two rows, each with at least two numbers aligned to the column
  anchors; a row whose label is longer than 80 characters or carries a sentence break (`'. '` before a capital)
  drops the row. A page that yields no such block gives no cells and is counted as skipped. A cell with no row
  label, or with a header that names no resolvable period and is not a difference column, is not stored.
- **h. Box and method.** `bbox` is the merged token's `x0,y0,x1,y1`; `method` is `'text_layer'`, or
  `'text_layer;delta'` for a difference / growth / `bps` column (`Inc/Dec`, `Inc/Dec%`, `Change`, `YoY %`,
  `Growth (%)`, `QoQ`, `Q-on-Q`, `Var. vs FY24`). A delta column is stored with `period_id` NULL, so no reader takes
  it as a period's value.
- **i. Rows that are not cells.** A row whose label is punctuation only (`-------`), a two-letter fragment (`St`), a
  long punctuation run (`TOTAL EQUITY ... -----`) or a printed figure (`CT2, Yes 529.40`) is not stored; a
  punctuation-only line does not become the next rows' section, so `Depreciation` keeps its own name.

Measured 9 Nov 2026 with `python -m reality_engine.v2.build_cells --store D:/RealityEngine/p20/p20new.db
--out .tmp/v2r4d` (all 76 decks and 113 results filed since 2025-04-01, into a **fresh** output directory; 30 further
documents were skipped as duplicate sha256):

| doc type | documents | pages | skipped (no text / no table) | cells | period_id | scale | no header | seconds |
|---|---|---|---|---|---|---|---|---|
| deck | 76 | 3,124 | 2,776 (79 / 2,697) | 13,858 | 82.9% | 80.4% | 0.0% | 55.2 |
| results | 113 | 1,805 | 1,099 (33 / 1,066) | 60,628 | 97.7% | 82.2% | 0.0% | 33.2 |
| total | 189 | 4,929 | 3,875 (112 / 3,763) | 74,486 | 94.9% | 81.9% | 0.0% | 88.4 |

Round 3 measured 75,394 cells (95.0% a period, 78.4% a scale); round 4 stores 908 fewer because a garbled label is
no longer stored (class 6) and the scale share rises 3.5 points from the per-unit rows (class 4). Round 2 measured
88,941 cells with 64.6% a period and 6.1% no header. The Havells information update p5 still gives 36 segment-revenue
cells (9 rows x 4 columns, all headed `Q2 FY27` / `Q2 FY26` / `Q2 FY27` / `Q1 FY27`) and the Asian Paints results p5
still gives the `Revenue from operations` row with a Q2FY27 cell. Tests:
`python -m pytest -q reality_engine/tests/test_v2_table_cells.py reality_engine/tests/test_v2_periods.py
reality_engine/tests/test_v2_schema.py` (45 tests: one fixture per round-1/2/3/4 defect class, the header carry-over,
the date-anchor repair, the sampler, and real-PDF smoke checks that skip when the files are absent).

The round-4 sampler, for the hand grade:

```bash
python -m reality_engine.v2.cell_sample --store-dir <dir> --n 100 --type deck|results \
    --seed 13 --out .tmp/f4_deck.csv
```

It writes `doc, page, label, header, period_id, value_text, unit_text, scale, value, method, snippet` with a
300-character page-text window around the printed value, so a reviewer can grade a cell without opening the PDF and
can see whether the column is a difference column (`method='text_layer;delta'`, period NULL by design).

**Round 3 (9 Nov 2026).** The six defect classes of the round-2 samples are fixed and each has a test: (1) a point
header (`31-12-2024 > (Unaudited)`, `Mar-26`) resolves to the quarter ending that day in a results P&L and to a
POINT on a balance-sheet page or a deck, and a bare `9M` / `FY` takes the printed FY range (`9M 25-26`) or the
latest period ending before the filing date; (2) a cell with no row label, no column header or a header that names
no resolvable period is not stored; (3) a per-share, count, ratio or own-unit row (`EPS`, `No. of employees`,
`Debt Equity Ratio (in times)`, `Qty.(In Mill. Te)`, `US$ Mn`) keeps scale 1 and its own `unit_text`, and a share
capital / face-value row stays money; (4) a garbled header date (`30.011.2028`) is dropped, never guessed, and its
column is left unheaded; (5) `Inc/Dec`, `Inc/Dec%`, `Change`, `YoY %`, `Growth (%)`, `QoQ` and `bps` columns are
stored with `period_id` NULL and `method='text_layer;delta'`; (6) a label line printed under a row, or above the
row whose numbers sit on its own line, joins that row's `row_label` instead of becoming the next row's section
(`Debtor Turnover Ratio (no. of months of Gross Sales)`), and a column takes the group heading nearest its centre
so `Quarter ended` and `Nine months ended` never both name it. Wolf's own grade of the first 30 rows of each
seed-11 sample (`.tmp/f_results.csv`, `.tmp/f_deck.csv`): **results 27/30 (90%)**, **deck 21/30 (70%)** fully right
(label, header, period and value) against 13/30 and 15/30 in round 2. The deck misses that remain are three
families, none of them one of the six classes: a subset of the Coal India decks prints a row's label on a slightly
different y than its numbers, so the pair is off by one row (`Stripping activity adjustment` takes the row above's
`Inc/Dec`); a six-column `value | % of NR | value | % of NR` deck table still lands the date header on the wrong
half; and a garbled label (`ta)Finarcialliabilities (iJBorrowings`) stays as printed. The 90/100 target is met on
results and not yet on decks; not ready for the 95% accept. The round-1 store is kept at `D:/RealityEngine/v2/p20_r1`;
the round-2 store is `.tmp/v2r2` (seed-9 samples `.tmp/s_results.csv`, `.tmp/s_deck.csv`) and the round-3 build
`.tmp/v2r6`. Opus graded rows 50-79 of each seed-11 sample independently (below).


**Round 4 (9 Nov 2026).** The six defect classes of the round-3 Opus sample are fixed and each has a test in
`reality_engine/tests/test_v2_table_cells.py`: (1) **wrong column** - every header phrase is now placed by
x-position (a date line the text layer split onto a second y-row, as on the Asian Paints results p7, keeps its own
column) and a block too short to sample every column takes the printed date row as its columns (Adani Ports notes
p25: five columns were read as two, 'March 31, 2026' over 'December 31, 2025*'); (2) **'Year ended' read as the
quarter** - `Year ended`, its `Vear Ended` garble and `twelve months` are FY, `Nine months` 9M, `Half year` /
`Six months` H1, and only a bare date keeps the quarter rule; (3) **balance rows under a quarter heading** - a
`Segment Assets` / `Segment Liabilities` / balance-sheet / `Total assets|liabilities|equity` / `Net worth` row is a
POINT on the column date (or the end of a `Q1 FY27` header); (4) **per-unit values at a crore scale** - a per-tonne,
`/te`, per-unit, per-key, per-room-night, `ARPU`, `ARR`, `RevPAR` or `realisation` row is `Rs` with scale 1 (Coal
India's 'Overall Average Realization' was 1,673 crore); (5) **measure group header** - a `REVENUE | EBITDA |
EBITDA MARGIN` row over the period sub-columns enters `col_header` as `measure=<text>` (Indian Hotels deck p28 now
says which of UOH Inc.'s three numbers is EBITDA); (6) **garbled labels** - 'St', '-------' and 'CT2, Yes 529.40'
rows are not stored, and a punctuation-only line no longer becomes the next rows' section. Also fixed on the way:
`in ₹` / `US$` were missed by a word-boundary test, `Q-on-Q` was read as a measure group, and a word ending in 'rs'
followed by 'per' ('Customers per employee') made a count row money.
Wolf's own grade of the first 30 rows of each seed-13 sample (`.tmp/f4_results.csv`, `.tmp/f4_deck.csv`):
**results 27/30 (90%)**, **deck 27/30 (90%)** fully right (label, header, period and value), against 27/30 and
21/30 in round 3. Remaining misses are not from the six classes: a label fragment or two labels merged
(`(₹ per tonne)`, `Dighi ports, Tuna & Goa terminals) South Coast (...)`), a P&L column whose span heading the text
layer lost (`ended e > 31.03.2026` read as the quarter when it is the year column), a bracket merged into a total
(`(201,851)` for total assets) and a quantity row with no unit word ('Overall Sales' 384.55 given a crore scale).
The build is `.tmp/v2r4d` (74,486 cells, period 94.9%, scale 81.9%); the round-3 store stays at
`D:/RealityEngine/v2/p20_r3` and the round-1/2 stores at `D:/RealityEngine/v2/p20_r1` and `.tmp/v2r2`. Opus grades
rows 50-79 of each seed-13 sample independently.

**Opus sample, round 3 (9 Nov 2026, rows 50-79 of each seed-11 sample, unseen by the worker):** results 20/30 strictly
right (24/30 if a segment-asset/liability balance tagged with its quarter instead of a POINT period is accepted), deck
~22/30. Store kept at `D:/RealityEngine/v2/p20_r3` (75,394 cells, period 95.0%). That sample's six misses - a P&L
'Year ended' column read as the quarter, a wrong-column pick when a results page prints two quarters side by side,
balance items under 'Quarter ended' headers given the quarter not POINT, per-tonne realisations given a crore scale, a
'Revenue / EBITDA / margin' group header not carried into the cell, and garbled labels ('St', '-----',
'CT2, Yes 529.40') - are the six classes fixed in round 4 above.

**Opus sample, round 4 (9 Nov 2026, rows 50-79 of each seed-13 sample, unseen by the worker):** results ~25/30,
deck ~27/30 fully right (worker: 27/30 and 27/30). Store `D:/RealityEngine/v2/p20_r4` (74,486 cells). Left: '6 months
ended' column given the quarter, a US$ ARPU labelled Rs, a '₹ Cr' label prefix not turned into a crore scale
('Revenue in ₹ Cr > Marine' 190 'Rs'), a bare 'as a % of NR' label with no parent line, one Coal India row whose value
belongs to the next label, and garbled labels from a broken text layer. Close to the 90% accept on decks, a few points
short on results.

**Opus sample, round 2 (9 Nov 2026, 30 cells the worker did not grade: rows 60-74 of each seed-9 sample):** results 9 of 15
and deck 9 of 15 fully right (~60%, up from ~27% in round 1; the worker graded its own first 30 at 13/30 and 15/30). Remaining
classes: point headers ('31-12-2024', 'Mar-26') and bare '9M' left without a period; cells with no label or no header kept;
per-share rows ('EPS') given a crore scale; garbled text-layer headers ('30.011.2028') parsed as data; 'Inc/Dec' difference
columns read as values. Not yet at the 90% accept.

## 11. Label map (T-133, v6 10 Nov 2026)

`reality_engine/v2/label_map.py` turns the printed row labels of the table store and `kpi_series` into one proposed
metric per sector family, and writes the review queue Opus approves from. The whole-label phrases live in
`reality_engine/pilot3/lexicon/*.yaml` (the cross-company statement lines are the phrases in
`reality_engine/pilot3/lexicon/common.yaml`; the common financial lines are `label_map.EXTRA_COMMON` in
`reality_engine/v2/label_map.py`).

Build it with:

```bash
python -m reality_engine.v2.label_map --cells-dir <v2 store dir> \
    --kpi-db <pilot3 db> [--kpi-db <pilot3 db> ...] --out <dir> [--taxonomy-db <equity_intelligence.db>] \
    [--replay <opus grade.csv> ...]
```

The cells store is built first with `python -m reality_engine.v2.build_cells --store <pilot3.db> --out <dir>`
(section 10). A company file is named by its ISIN; `company_family` places it through the same
`company_industry` -> `sector_map.yaml` path as `make_profile`, with `master_companies.industry` as the second
tier.

**Rule 1 — OCR repair and whole-label matching (v4).** OCR spellings already seen in the cells are repaired
first, one token at a time, through an explicit table (`liabi6ties`/`liabiities`/`fiabilities` -> `liabilities`,
`seoment` -> `segment`, `lncome` -> `income`, `mobife` -> `mobile`, ...; phrases `pro fit` -> `profit`,
`un allocable` -> `unallocable`, `compreh ensive` -> `comprehensive`). A known section name is repaired by edit
distance after its spaces are removed (`segment liabilties`, `segment l iabifties` -> `segment liabilities`), never
by adding the spelling to the table; a section printed without its `>` separator
(`Segment Results a) Switchgears` -> `segment results > switchgears`) still owns the member after it. A word OCR
split across spaces is rejoined when the concatenation is a known word (`Total Com pre hensive Income`, `Own ers`,
`pe riod` -> `total comprehensive income`, `owners`, `period`), so a mis-parented child is matched by its own
wording again. A label is
then normalised and must equal a lexicon phrase whole, or a yaml
`labels` regex must consume the whole label (`re.fullmatch`). A label that carries a metric phrase plus other
words is **not** that metric. v1 matched any substring, which is why "Operating Free Cash Flow (EBITDA - Capex)"
became `capex` (2,062 review rows), "Sales and marketing expenses" became `revenue` and every "non financial
assets" line became `total_financial_assets`; none of those can happen now. Unit/footnote tails (`rs`, `us`,
`mn`, `cr`, `nos`, `000 s`, a trailing digit or column formula `C=A+B`) are stripped before matching, so
"capex 1 US$" is `capex` and "Net Debt US$ mn" is `net_debt`; a single footnote digit glued to a word is that
footnote, so `ebitdaal1` is `ebitdaal` and `mundra1` is `mundra` (v6), and a per-unit denominator is never
stripped (`EBITDA per tonne` stays `ebitda_per_tonne`). A **garbled** label is `status='rejected'` with
`rule='garbled'`, never a proposal: a token with a digit/letter swap ("0ther"), a digit/letter soup
("39l" in "> ?,39L.64"), or no dictionary hit for 40% or more of its tokens ("gpwis mmt"), or a single
lower-case word of six or more letters the dictionary does not hold. The dictionary is the label filler plus the
common lexicon phrases; a label that matches a lexicon phrase whole is never garbled, a container child
(`JVs > ...`) is exempt so an acronym member survives, and **v6: a label seen in two or more documents with a
clean numeric cell is never garbled** - the evidence is checked before the dictionary, so real members the
dictionary lacks (`krishnapatnam`, `lighting and fixtures`, `lloyd consumer`) are proposed, not rejected.
One-edit OCR typos are repaired token by token (`Provisiuns` -> `provisions`), and a truncated label whose
unmatched bracket ends the cell ("`(Excl.`") is rejected as `truncated label`; an OCR footnote inside a whole
label ("`(loss}`", "`(A+B\\`") is not truncation.

**Normalisation.** Lower case; OCR tokens repaired (above); leading numbering (`1.`, `(a)`, `i)`, `iv.`) dropped;
bracketed units and currency (`(Rs crore)`, `(₹ in Lakhs)`, `(%)`, `(as a % of revenue)`) dropped; `%`, currency
marks and punctuation dropped; `&` becomes `and`; `/` becomes a space. A parent is joined with `' > '` only when
the child is ambiguous alone (`Others`, `Other`, `Total`, `Sub-total`); before v2 every generic child kept its
parent, which hid "Total expenses" under "Expenses".

**Rule 2 — seeds.** A `kpi_series` raw label seeds a proposal only when its own label passes rule 1 and the lexicon
does not disagree (the lexicon is the reviewed contract, the seed a usage witness). A failing seed is ignored and
listed in `rejected_seeds.csv` with the metric the new rule would give it. v6 adds one exception: a `total
revenue(s)` seed may say either `revenue` or `total_income`, because rule 8 decides it at the table, so the 1,922
seed rows v5 rejected as "metric conflict" are accepted again (zero total-revenue conflicts in v6). The same
mapping rule is implemented in `reality_engine/pilot3/kpi.py` (`row_label_hits`, used by the `table_v1` path), so
the next extraction stores `operating_free_cash_flow` where it used to store `capex`; `kpi.py` has no table
arithmetic, so a `total revenue(s)` row there now matches no line rather than guessing either id (the v6 dry run
lists these rows in `seed_changes.csv`).

**Rule 3 — qualifiers, members and dimensions (v4).** `pre`/`post` tax, `including`/`excluding` lease obligations
or acceptances, and a definition bracket's basis leave the matched phrase and become `dimension` entries
(`pre_tax`, `post_tax`, `incl_lease`, `excl_lease`, `excl_acceptances`, `basis=ebitda`, `basis=ebitdaal`); an
"excluding access charges and licence fee" list becomes `excl=access_charges,cogs,licence_fee,...` on the base
metric, because the exclusion changes the meaning. A bracketed definition ("(EBITDA - Capex)") is not part of a
metric's name. A **member** row (a segment/port/subsidiary name) becomes metric `from_header` with
`dimension=<member>` only with evidence in the cells: its own column headers carry `measure=`, it sits under a
`segment`/container parent (`JVs`, `Subsidiaries`, `Ports`, `Segments`), or it is a known entity name (the file's
`entity`/`entity_alias`; the p20_r4 build has no entity rows, so the evidence there is the measure headers and the
container/segment context). v2 made every unmatched short row in a table with metric rows or three unmapped peers
a member (629 proposals); 48 of its 67 sampled `from_header` rows were financial statement lines. A **statement
line** is never a member: a leaf that names a line item or a measure (`Inventory`, `Securities premium`, `COGS`,
`Exceptional item refer note`, `micro small and medium`, ...), a heading, or a label used as a section parent in
its own table gets no proposal and sits in the review queue. A parent that names a measure (`Revenue in`,
`Segment Sales`, `Segment Assets`, `Segment Results`, `Segment Liabilities`, `Profit from segments`, OCI sections,
profit attributable) owns the metric of a child that names none, with the child as its dimension
(`revenue in > logistics` is `segment_revenue[logistics]`, never `from_header`); a leaf that is itself a common
metric (CWIP, basic/diluted EPS, "cwip rs cr") keeps its own line over the section and over `from_header`. A key
that carries two meanings (the OCR "items not to be reclassified" section holding both profit and OCI
attributable) queues with no metric, and a member whose name also exists at company level (`Asia > Unallocated`)
keeps its parent in the dimension. **v5:** a generic member named `Others`/`Other` stays in the dimension
(`segment_assets[others]`); only the segment total (`Total`/`Sub total`) is at the empty dimension, so the member
no longer collides with the total. A leaf that is only split-header text (`before finance costs and taxes`,
`after exceptional items`) is the section's total with an empty dimension, not a member. A child whose own
wording names a statement total wins over the mis-parented parent: `total comprehensive income ...` (OCR joined)
is `total_comprehensive_income`, `total income` is `total_income`, `total revenue(s)` is resolved by its own
table (rule 8), `total liabilities` is `total_liabilities`. A parent that says its child is a component of the parent line
(`... comprising of`, `consists of`, `represents`, `details of`, `analysis of`) queues the child; it is a
sub-line, never a `from_header` member. A member row that is a unit-bearing quantity - its own cells carry a
count/tonnes/data/power unit, its printed label states a count (`Tugs 10`), or it is a lone aggregating
adjective (`Cumulative`) - is a KPI row, not a name, and queues. **v6:** a section measure owns its component
rows (`segment results > exceptional item refer note` is `segment_results[exceptional item refer note]`, while
the same words standalone are `exceptional_items`), and a leaf `kpi_series` seed never replaces the section
measure. A `<metric>_mix` row keeps the printed member in the dimension (`Retail` is
`vertical_mix[retail]`, `Liquid` in an AMC AUM table is `aum_mix[asset_class=liquid]`). A quantity label that
carries its channel (`FSA Qty.(In Mill. Te)` -> `volume[fsa]`) keeps it, and a bare `Qty.(In Mill. Te)` takes
the channel of the "`... Price (In Rs./Te.)`" row printed next to it, so FSA/E-Auction/Washed no longer share
one key.

**Rule 4 — unit kind (v5).** `unit_kind` comes from `metric_def` when the lexicon states it (`pcr_stage3` ->
`pct`, `production_kt`/`volume` -> `tonnes`, `employees` -> `count`, `interest_coverage` -> `x`), else from the
metric's own quantity word (`population_covered` -> `count`, `total_gbs_on_network` -> `data`,
`debtors_turnover` -> `x`), else from the majority unit of **that label's numeric** cells (`%` -> `pct`,
`count` -> `count`, `kt`/`tonne` -> `tonnes`, `x`/`days`, currency (`Rs crore`, `Rs million`, `inr_per_share`) ->
`money`, `MW`/`GW` -> `power`, `GB` -> `data`); only a currency unit gives `money`, an unknown or tied unit is
NULL, and a cell with no value is not unit evidence (a `%` column printed but empty does not split the vote).
The metric's quantity word is what stops a scale parser's "Rs billion" on `Population Covered Bn` (a count of
people) or "Mn" on `Total GBs on the network` (data volume) from making the row money. v2 defaulted every
non-pct/x metric to `money`. **v6:** a metric whose definition fixes its unit takes precedence over the cell
majority: `eliminations` is `money` (money cells and % mix cells in one label no longer make the money cells
ratios), `current_liability_ratio` is `x` (printed fractions 0.89/0.73 are not 0.89%), `aum_mix`/`vertical_mix`
are `pct`. A `from_header` row is always NULL because its column header carries the measure and
unit (a segment member with 20-26% margin cells is not a money row), while a currency line item (`Unallocable
Expenses`) keeps `money` from its numeric cells. A money figure's currency still comes from the cell's own unit,
never from the label map (v1 carried `inr` for dollar lines).

**Rule 5 — statement context (v4).** The cell's `section > label` parent separates rows printed in two
statements: "Interest received" in the cash flow is `interest_received`, on the P&L it is `interest_income`
(dimension `statement=…`); "Owners of the parent" and "Non controlling interest" under an attributable heading
are the attribution lines (`profit_attributable` / `total_comprehensive_income_attributable` /
`other_comprehensive_income`, dimension `attribution=…`; a parent that names profit, including "PROFIT
ATTRIBUTABLE TO", is `profit_attributable` — v2 sent it to OCI), and only an equity section makes it
`owners_equity`. A bare ratio row ("as a % of NR") has no measure of its own: its base is the row above in the
same table, so its key is `<base> > as a % of nr` and its dimension is `base=contribution` /
`base=a_and_p_spend` / `base=other_sga`, never one key for every ratio in the table. A generated `_pct` name comes
from the base metric already mapped for the leaf (`operating_expenses` -> `operating_expenses_pct`,
`cash_profit_from_operations` -> `cash_profit_from_operations_pct`), found whole or as the longest known metric
phrase that starts the leaf; v2 slugged the raw OCR text, so one printed label could yield two metric ids. A
parent's metric is not applied to a leaf that itself carries a known metric phrase of a different kind (a paid-up
equity share capital line under an attributable heading stays in the queue). The brief named `doc_page.section` as
a second source; `p20/p20new.db`'s `doc_page` has no `section` column, so the parent is the only statement context
used. **v6:** a bare `Attributable to:` parent is the P&L attribution
(`profit_attributable[attribution=non_controlling]`), an OCI/reclassified parent is
`other_comprehensive_income`, a total-comprehensive parent is `total_comprehensive_income_attributable`, and only
an equity/balance-sheet parent keeps the stock `non_controlling_interest`; the parent is part of the key, so the
flow and the stock never share a row (v5 queued the bare parent, which hid the flow). A working-capital label
under a cash-flow "Adjustments for increase/decrease in operating assets/liabilities" parent is the *change*
(`change_in_trade_receivables`, `change_in_trade_payables`, `changes_in_inventories`), never the balance-sheet
stock id.

**Rule 6 — junk, headings and garbage.** A label of digits/period tokens only, a digit glued to a word
("expe1", "39l"), a value token ("45,000 160% EBITDA"), a sentence fragment ending in an auxiliary verb ("The Parent
Company has"), a truncated label ("`(Excl.`"), or a statement heading ("Financial assets", "Particulars") is
`status='rejected'`, never a proposal; "45 000 160 ebitda" no longer seeds `ebitda`. A trailing footnote digit
is not a glued word (`ebitdaal1`, `mundra1`). A one-edit OCR variant of a one-word heading is that
heading (`Particulats` -> `particulars`), and a heading row whose cells are all dash/blank in a table (`Current
assets` with only "-" at Apollo Tyres) is rejected for that family only: the same label with numbers is that
table's total and stays mapped. Heading fragments (`Particulars`, `Less`, the OCR `otal`) are `status='rejected'`
with `rule='heading'`. An OCR-garbled label is also `rejected`, with `rule='garbled'` (rule 1). Line-specific
metrics that the label itself does not name stay unmapped in the queue.

**Rule 7 — percent labels and redundant tax qualifiers (v5).** A raw label ending in `%` or `(%)` is a margin,
never the money line: `PBT %` is `pbt_margin`, `EBIT %` is `ebit_margin`, `EBITDA %`/`PAT %` are
`ebitda_margin_pct`/`pat_margin_pct`, each with `unit_kind='pct'`, and the key keeps the suffix (`pbt %`) so the
money row (`pbt`) and the margin row no longer share one key; a percent label with no base metric stays in the
queue. A qualifier that only restates the metric's own definition is not a dimension: `pre_tax` is dropped from
`pbt`/`pbt_before_exceptional` and `post_tax` from `pat`/`pat_before_exceptional`, so one figure no longer sits
under two dimension keys; `return on equity` keeps `pre_tax`/`post_tax` because lenders print both.

**Rule 8 — total revenue is decided by the table (v6).** `total revenue`/`total revenues` is a marker
(`label_map.TOTAL_REVENUE`) in the label tier, never a blanket `total_income`: `resolve_total_revenue` reads the
same table's numeric cells by column and maps the row to `total_income` only when a `revenue` row and an
`other_income` row in that column add up to the total (Indian Hotels 2,425 + 62 = 2,487 Rs crore), otherwise to
`revenue` (Bharti "Total revenues" 494,626 Rs mn is the sum of segment revenues, other income separate). Percent
columns (`Var. vs FY26`) are not proof. The label map stores the family's resolved answer (a proven
`total_income` wins over a default from another of the family's tables) and every cell carries its own table's
answer; a label with no proving table defaults to `revenue`. A child whose own wording names the statement total
still routes before this rule.

**Rule 9 — flow vs stock under one label key (v6).** A working-capital movement under a cash-flow
"Adjustments for increase/decrease in operating assets/liabilities" parent is `change_in_trade_receivables` /
`change_in_trade_payables` / `changes_in_inventories`; the same words under "Financial assets"/"Trade payables"
stay the stock ids. An attribution label under a P&L `Attributable to` parent is `profit_attributable`, under an
OCI/reclassified parent `other_comprehensive_income`, under a total-comprehensive parent
`total_comprehensive_income_attributable`, always `attribution=non_controlling` / `attribution=owners_of_parent`;
`Equity > Non-controlling interests` is the only path to the stock `non_controlling_interest`. The parent is part
of the key, and the NCI alias/plural (`Non Controlling Interest (NCI)`, `non-controlling interests`) normalises
to one phrase. A cash-flow change line that states the movement itself (`Decrease/(Increase) in trade
receivables`) matches the change metric whole.

**Rule 10 — suffixes, evidence and replay honesty (v6).** A suffix that names the metric's own unit is never
stripped into a broader metric: `EBITDA/ton`, `EBITDA/tonne`, `EBITDA/tonne $/tonne` stay
`ebitda_per_tonne`, and `CASA %` is `casa_ratio` (percent, not the `casa` money line). A seed stands whenever the
lexicon agrees or is silent on the label's own wording (rule 2), so `VoNB margin` keeps `vnb_margin`. The garbled
rule reads evidence first (rule 1). A row the reviewer already graded right is **LOST**, not fixed, when it now
maps to NULL, a queue with no metric or a rejection; the `--replay <grade.csv>` pass (`replay_grade`) applies
that rule, treats a documented v4 id rename (`revenue_from_operations` -> `revenue`,
`cash_generated_from_operations` -> `cash_flow_from_operations`, the two v3 `_pct` slugs) as kept, and treats a
right `from_header` that now has the section's metric as an upgrade, not a loss. Every kept-with-reason and
changed row is listed in `replay_report.md`.

**Outputs** in `--out`: `label_map.db` (the `label_map` and `metric_def` tables, the v2 DDL; `label_map` rows carry
`dimension`, `unit_kind` and `status`), `review_<family>.csv` and `review_common.csv` (label_norm, example raw
labels, frequency, companies, proposed_metric, dimension, unit_kind, reason, **rule**, **confidence**,
**status**; every observed label, mapped or not, sorted by frequency), `coverage.txt` (mapped share of the numeric
`table_cell` rows per family and overall, the rejected count, the mapped-or-queued share, and the 50 most frequent
unmapped labels), `rejected_seeds.csv`, `seed_changes.csv` (the read-only dry run of the new rule over the
`table_v1` rows of the `kpi_series` stores, by `(old, new)` metric pair), `sample_seed47.csv` (200 proposed
rows at `random.Random(47)`, spread over families, ungraded, for Opus to grade) and `rejected_seed47.csv`
(40 labels that stay rejected, `random.Random(47)`, ungraded, so the garbled rule is reviewed on its rejects, not
only on its proposals). `rule` is the step that proposed the row (`1-match`, `2-seed`, `3-qualifier`, `3-member`,
`5-context`, `8-table`, `table:total`, `section:change`, `section:channel`, `percent:label`, `child:total`,
`6-reject`, `heading`, `garbled`); `confidence` is `exact`, `synonym` or `section`. `from_header` has no
`metric_def` row: its kind comes from the header's measure. `--replay <grade.csv>` writes
`grade_replay_seed31.csv`, `grade_replay_seed37.csv`, `grade_replay_seed41.csv` and `grade_replay_seed43.csv`
(the graded row, its graded metric, every v6 metric the label can take, the kept/changed/unchanged/LOST status and
the reason); `replay_report.md` carries the zero-lost summary, every right row kept through a sanctioned rename or
`from_header` upgrade, every changed wrong row with its reason, the wrong rows still unmapped and the families
under 60%. A family-specific
`rejected` row (`current assets` at `tyres_auto_ancillary`) masks a common `*` proposal for that family; a
consumer must read the exact `sector_family` row before the `*` row.

**Sector families.** `reality_engine/pilot3/sector_map.yaml` now carries 27 families: the eleven lexicons (bank, nbfc,
insurance_life, auto_oem, consumer_internet, fmcg, it_services, metals_nonferrous, epc_capital_goods, pharma,
asset_management - the last added in v6 for the AMC AUM mix) plus
cement, retail, airlines, paints_chemicals, consumer_durables, jewellery_lifestyle, hotels, ports_logistics, mining,
tyres_auto_ancillary, telecom, asset_management, metals_ferrous, utilities_power, healthcare_hospitals, realty and
textiles_home. Of the 191 basic industries, 135 map and 56 stay `unknown`; none of those 56 is used by a company in
`pilot10.db`, `p20/p20new.db`, `u8/u8.db` or `q12/q12.db` (63 company rows, every one now has a family; the
`master_industry` tier covers TITAN, TRENT, ULTRACEMCO, SUNPHARMA and WELSPUNLIV, which have no `company_industry`
row).

**Measured 10 Nov 2026 (v6)** on `D:/RealityEngine/v2/p20_r4` (read-only, 10 company files, 74,486 `table_cell`
rows) and the `kpi_series` of `pilot10.db`, `p20/p20new.db`, `u8/u8.db` and `q12/q12.db` (30,298 rows): 5,276
`(label, family)` observations, 1,902 proposed mappings (rule 1 match 705, seed 447, member 200, qualifier 31,
context 498, table total 21) and 228 `metric_def` rows (flow 94, stock 60, ratio 67, per_share 3, price 4). Of the
59,326 numeric table rows, 41,882 (70.6%) map to a proposed metric, 2,284 are rejected as junk/heading/garbled
(887 rejected labels, 559 of them garbled over 1,554 numeric cells; v5 rejected 4,881 cells and the Opus review
counted 979 garbled labels / 7,907 cells), and 59,172 (99.7%) are mapped or queued in the review CSVs; 154 rows
have no label. Only `ports_logistics` stays under 60% mapped (59.9%); the other eight cell families are
62.1%-76.8%. The stop rule (below 60% overall coverage means stop and report lexicon gaps) was not hit. The seed
dry run changes 6,770 of the 19,231 `table_v1` `kpi_series` rows in 62 pairs: 3,083 rows that carried `revenue`
now match no line (`total revenue(s)` is table-dependent and `kpi.py` has no table arithmetic), `capex` ->
`operating_free_cash_flow` (1,466), `roa_pct` -> no line (581), `revenue` -> `revenue_per_tower_per_month` (188),
`working_capital_days` -> no line (142), `ebitda` -> no line (132), `revenue_usd` -> `revenue` (126) and
`vertical_mix` -> no line (98); 8,704 seed label rows across the four stores fail rule 1/lexicon and are listed
in `rejected_seeds.csv`. Output kept at `.tmp/label_map_v6` (`label_map.db`, the review CSVs, `coverage.txt`,
`rejected_seeds.csv`, `seed_changes.csv`, `sample_seed47.csv`, `rejected_seed47.csv`,
`grade_replay_seed31.csv`, `grade_replay_seed37.csv`, `grade_replay_seed41.csv`, `grade_replay_seed43.csv`,
`replay_report.md`, `build.log`); nothing is `approved` until Opus works through the review files.

**Opus grade replay (v6, zero lost right rows).** The v5 replay counted a right row dropped to NULL as "fixed";
v6 counts it LOST (step 8). Seed-31 (139/200 right) keeps all 139, LOST 0; of the 61 wrong rows 33 change, 8 stay
the same and 20 are still unmapped (a wrong row may not map, but it is never counted as fixed). Seed-37 (170)
keeps all 170, LOST 0 (13 changed, 12 unchanged, 5 unmapped). Seed-41 (177) keeps all 177, LOST 0 (4 changed, 14
unchanged, 5 unmapped). Seed-43 (180) keeps all 180, LOST 0 (5 changed, 13 unchanged, 2 unmapped). Right rows
whose answer changed but stayed right are listed per row in `replay_report.md`: a documented v4 canonical rename
(`cash_profit_from_operations_before_derivative_and_pct` -> `cash_profit_from_operations_pct`,
`operating_expenses_excluding_..._pct` -> `operating_expenses_pct`, `revenue_from_operations` -> `revenue`) and a
`from_header` row that now has its section's metric (three seed-31 segment-liability rows). The rule changes the
review named all land: the total-revenue table proof (IHCL `total_income`, Bharti `revenue`), the flow/stock
split (`change_in_trade_receivables`/`change_in_trade_payables`, `profit_attributable` and
`other_comprehensive_income` attribution), the unit suffixes (`ebitda_per_tonne`, `casa_ratio`, `vnb_margin`),
the 19 seed-31 NULL rows now mapping (inventories, borrowings, depreciation, finance costs, cogs, exceptional
items, securities premium, sales and marketing, intangible assets, the cash-flow changes, owners' profit), the
mixed unit rows (`eliminations` money, `current_liability_ratio` x), the channel/mix members
(`volume[fsa]`, `vertical_mix[retail]`, `aum_mix[asset_class=liquid]`), the truncated/OCR/merged-label rejects and
`Provisiuns` -> `provisions`. The per-row detail is in `grade_replay_seed31.csv`, `grade_replay_seed37.csv`,
`grade_replay_seed41.csv`, `grade_replay_seed43.csv` and `replay_report.md` in `.tmp/label_map_v6`.

Tests: `reality_engine/tests/test_v2_label_map.py` (61 passed) cover the normalisation and unit-tail stripping, the
OCR repair table, the OCR space-join and the fuzzy section repair, rule 1 whole-label matching, garbled
rejection, the seed rule and seed-vs-lexicon conflict, qualifiers/dimensions, the definition basis, the exclusion
qualifier, measure parents and leaf-wins (CWIP/EPS), member -> `from_header` with the v3 evidence and the keep
list, statement lines never becoming members, the profit-attributable/dividend context fixes, the ratio-of-the-
previous-line base, the percent base metric, the section/known-child guard, unit kinds from
`metric_def`/quantity word/cells with NULL unknown and NULL `from_header`, canonical ids, junk/headings, the v5
rules 1-7, every line of the T-133 v2-v5 evidence lists, the review CSV columns and the seed-47 samples, the
`metric_def` check constraint, the sector map over the four pilot stores (skipped when the stores are absent),
and one test per v6 step: the table total proof, the flow/stock split, the suffix/seed rules, the garbled
evidence rule, the 18 missed common lines, the `from_header` misuses, the smaller context rows, and the replay
LOST rule. `reality_engine/tests/test_pilot3_kpi.py` (105 collected: 99 pass, 6 fail at setup only because
pytest's `tmp_path` is denied in this dsh sandbox) covers `row_label_hits` (whole label, block heading, plural),
`label_text` and the evidence labels.

**Opus reviews (9-10 Nov 2026, history).** Families were right for all 40 pilot companies, but no family was
approved: v1's substring matcher produced systematic wrong proposals, v2 (whole-label matching) was graded
139/200 on its seed-31 sample with three structural classes left (member fallback, unit-kind default, a few wrong
metrics), v3 (context/member rules) was graded 170/200 on its seed-37 sample with one right row lost (the
exclusion qualifier in `operating_expenses_pct`), v4 was graded 177/200 on its seed-41 sample with no
previously right row lost, and v5 was graded 180/200 on its seed-43 sample: the Opus replay check found the
blanket `total revenue` -> `total_income` rule wrong for Bharti (1,922 seeds overridden), unit suffixes stripped
into broader metrics (`EBITDA/ton` -> `ebitda`), flow/stock ids sharing one key (cash-flow changes and NCI), the
garbled rule over-rejecting 979 labels / 7,907 cells, 18 common metrics with no map row, and a replay that
counted a right row dropped to NULL as fixed. v6 fixes those classes structurally (rules 8-10) with zero lost
right rows over the four grade files. v1's build `D:/RealityEngine/v2/label_map`, v2's `.tmp/label_map_v2` build
and seed-31 sample, v3's `.tmp/label_map_v3` build and seed-37 sample, and v4's and v5's builds are superseded by
`.tmp/label_map_v6`.
