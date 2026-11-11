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
2. T-134 period engine and T-135 calc catalog in parallel (two code workers was the cap then; 4 since 10 Nov).
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
  words wholly outside are skipped as call-outs and a word running across the LEFT edge is trimmed (`Unit`), but a
  title that runs in from the left leaves only a fragment and is not a header row. A row is dropped when it is
  prose (one run of eight or more words with no digit, or a line ending in `.`), when it carries a non-date figure
  (a slide call-out such as `Rs 353 crores`), or when it names no date, period, unit or audit status; a wrapped
  date half (`31 2024`, inside a month row) is not a call-out; a `vs.` comparison line is a slide title unless it
  is a `Var.` / `Change` / `Growth` column. Three consecutive dropped rows stop the stack and the stack holds at
  most six rows. A group heading printed over its columns ("Quarter ended", "Nine months ended", "As at") names the
  run of columns on its side of the midpoint between it and the next heading, so two headings over one table never
  both name a column and a 3+2+1 band split (three quarter columns, two nine-month columns, one year) maps by
  position; a single heading applies to every column. A sub-header directly over the period row (`Coal | Other
  Dry | '000 TEUs | MMT`) refines only the columns of the group run it is printed over. **Every header phrase is
  placed by x-position, never by order**: a phrase owns each column centre inside its own x-span (a long heading
  owns two columns), else the nearest column within the column tolerance, else nothing - so a date line the text
  layer split onto a second y-row still lands on its own column. Two header cells the layer merged are split at
  their own separator (`Quarter ended I As of year ended I`), never when one cell intentionally names both
  readings. When a block is too short to sample every column (two of five anchors) and the header prints a full
  date row, those date phrases become the columns. A tall label box shares its TOP EDGE with the figures printed on its
  baseline, so a label whose y-centre sits between two numeric rows joins the row whose numbers share its top edge
  (round 5). `col_header` joins the rows top to bottom with `' > '`, e.g.
  `'Quarter ended > 30.09.2026'`. A statement continued on the next page (or a second table on the page with no header
  of its own) reuses the last header set seen. A measure group row printed over its period sub-columns
  (`REVENUE | EBITDA | EBITDA MARGIN`) is kept when it sits directly above a period header row and enters `col_header`
  as `measure=<text>`, so a legal-entity deck's `UOH Inc. - USA 19` says it is EBITDA. `measure=` is read only from
  header rows over the columns: a one-cell row label (`INCOME`, `Revenue from operations`, `1. Segment Revenue`) is
  the rows' section parent, never their measure (round 9).
- **b. Section labels.** A section label ("Expenses") ends where a new numbered row group starts: the first token is
  a row number (`2`, `II`, `IV`, `(2)`) or a parenthesised roman numeral (`(iv)`) at the same indent; a deeper
  `(i)`/`(ii)` stays inside the section, and lettered sub-labels (`(a)`, `(b)`) always do. The printed row-number
  column is dropped from `row_label` and from the cells. A label line printed under a row, or above the row whose
  numbers sit on its own line, belongs to that row: it is joined into that row's `row_label` (`Debtor Turnover
  Ratio (no. of months of Gross Sales)`), never used as the next row's section.
- **c. Tokens.** Figures split by the text layer merge (`2, 028` -> `2,028`, `1 ,234.5`, a lost thousands separator
  `5 088`); a decimal tail cut off by the layer (`7,601.5` + `1`, `2,016` + `32` whose point glyph is missing) joins
  back into `7,601.51` / `2,016.32` (round 5). `(1,234.5)` and `-1,234.5` are negative; `-` / an en dash is value NULL with `value_text` kept; `12.3%`
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
  `US$ Mn` row is `USD million`. A column header that prints its own physical unit sets it: `MMT` / `MT` is
  `unit_text='MMT'`, `'000 TEUs` is `count` at scale 1000 (round 9). The currency a label prints wins over the page's money unit together with the scale
  word beside it: `Average Revenue Per User (ARPU) US$` is USD at scale 1, `(US$ Mn)` USD million, and a section
  prefix `Revenue in ₹ Cr > Marine` is `Rs crore`, not bare `Rs` (round 5).
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
  is 9M and `Half year` / `Six months` / `6 months` is H1; only a bare date with no span text keeps the quarter rule.
  A span the header stack split into segments (`As > on > 30.06.2025`) is still read as `As on` (round 5). A balance or
  segment asset/liability row (`Segment Assets`, `Segment Liabilities`, `Statement of Assets and Liabilities`,
  `balance sheet`, `Total assets/liabilities/equity`, `Net worth`), or a page titled Balance Sheet, is a POINT on the
  column's own printed date (or the end date of a `Q1 FY27` / `9M 25-26` header), never the quarter's flow.
  The stock/flow word lists are consulted with FLOW FIRST: a balance word inside a flow label (`Return on
  Shareholder's Equity`, `Inventory turnover`, `Gain on investments at FVOCI`, `FX restatement of cash and cash
  equivalents`, `Net loss on FVTOCI equity securities`) never turns the printed quarter/half/year into a point;
  a point is a pure balance under an `As at` header or a stock label with no flow word (round 9). Operating counts
  (`Customer Base`, `Network Towers`, `Co-locations`) and balance ratios (`Long-term debt to working capital`,
  `Current Ratio`, `Debt Equity Ratio`, `Book Value per share`) are points at the column date. On a page titled
  `Key Financial Ratios` the bare period ends decide the kind: a 30-September column is the half year ending that day
  and a 31-March column the fiscal year, so in an H1 filing 30.09.25 / 31.03.25 / 30.09.24 are H1 / FY / H1, never
  quarters (round 9). In a results document a bare month-year header (`Mar-25`) is the quarter, not the fiscal year
  the month ends.
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
- **j. Garbled labels and bare ratios.** A broken text layer prints a label that is not words (`l:Jnallocable / el`,
  `Financial riabilities`): the cell is kept with its value and printed label and `method='text_layer;garbled'`
  (`;delta;garbled` when the column is a difference column) when more than 30% of the label's letters sit in tokens
  that are neither dictionary words nor known names - a row number, acronym or capitalised name. The dictionary is
  the repo's business lexicon (`reality_engine/pilot3/lexicon/*.yaml`) plus common statement words, so the flag is
  advisory and never drops a value. A bare ratio printed under a line item (`as a % of NR`, `% of revenue`,
  `margin %`) takes that line item as its parent (`Advertising & Sales Promotion > as a % of NR`), with a printed
  `Add:` / `Less:` prefix stripped. A canonical Roman-numeral row marker is a row number; `CIL` (a Coal India
  subsidiary) is not (round 5).

Measured 9 Nov 2026 for round 5 with `python -m reality_engine.v2.build_cells --store D:/RealityEngine/p20/p20new.db
--out .tmp/v2r5` (all 76 decks and 113 results filed since 2025-04-01, into a **fresh** output directory; 30 further
documents were skipped as duplicate sha256):

| doc type | documents | pages | skipped (no text / no table) | cells | period_id | scale | no header | seconds |
|---|---|---|---|---|---|---|---|---|
| deck | 76 | 3,124 | 2,760 (79 / 2,681) | 14,000 | 83.0% | 80.2% | 0.0% | 56.7 |
| results | 113 | 1,805 | 1,113 (33 / 1,080) | 60,259 | 97.7% | 86.5% | 0.0% | 36.1 |
| total | 189 | 4,929 | 3,873 (112 / 3,761) | 74,259 | 94.9% | 85.4% | 0.0% | 92.8 |

Round 4 measured 74,486 cells (94.9% a period, 81.9% a scale); round 5 stores 227 fewer because the top-edge row
pairing merges a label with its own figures (round 4 stored `2,016` where the printed figure is `2,016.32`, and a
row without its label could drop out) and the scale share rises 3.5 points from the currency labels of class 2.
Round 3 measured 75,394 cells (95.0% a period, 78.4% a scale); round 2 measured 88,941 cells with 64.6% a period and
6.1% no header. The Havells information update p5 still gives 36 segment-revenue
cells (9 rows x 4 columns, all headed `Q2 FY27` / `Q2 FY26` / `Q2 FY27` / `Q1 FY27`) and the Asian Paints results p5
still gives the `Revenue from operations` row with a Q2FY27 cell. Tests:
`python -m pytest -q reality_engine/tests/test_v2_table_cells.py reality_engine/tests/test_v2_periods.py
reality_engine/tests/test_v2_schema.py` (85 tests as of round 9: one fixture per round-1/2/3/4/5/6/7/8/9 defect class, the header
carry-over, the date-anchor repair, the sampler, and real-PDF smoke checks that skip when the files are absent).

The round-5 sampler, for the hand grade:

```bash
python -m reality_engine.v2.cell_sample --store-dir <dir> --n 100 --type deck|results \
    --seed 17 --out .tmp/f5_deck.csv
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

**Round 5 (9 Nov 2026).** The five defect classes of the round-4 Opus sample are fixed and each has a test in
`reality_engine/tests/test_v2_table_cells.py`: (1) **six-month span** - `Six months ended` / `6 months ended` /
`Half year ended` over a date column is H1, so Titan's `6 months ended > 30-09-2025` is H1FY26, not Q2; (2) **label
currency** - the currency a label prints wins with the scale word beside it (`Average Revenue Per User (ARPU) US$`
USD scale 1, `(US$ Mn)` USD million, `Revenue in ₹ Cr > Marine` `Rs crore`); (3) **bare ratio parent** - `as a % of
NR` / `% of revenue` / `margin %` printed under a line item takes that line item's name (`Advertising & Sales
Promotion > as a % of NR`), with `Less:` / `Add:` stripped; (4) **top-edge row pairing** - a tall label box joins the
numeric row whose top edge it shares even when its centre sits nearer another row (the Coal India deck's
`MCL ... CMPDIL` rows), and a canonical Roman numeral is a row number while `CIL` is a subsidiary name; (5) **garbled
labels** - over 30% of a label's letters in non-words keeps the cell and its value with `method='text_layer;garbled'`
(`l:Jnallocable / el`, `Financial riabilities`). Also fixed on the way: a decimal tail cut off by the text layer
(`7,601.5` + `1`, `2,016` + `32`) merges back to `7,601.51` / `2,016.32`, and `As > on > 30.06.2025` is a POINT.
Wolf's own grade of the first 30 rows of each seed-17 sample (`.tmp/f5_results.csv`, `.tmp/f5_deck.csv`): **results
24/30**, **deck 23/30** fully right (label, header, period and value). The remaining misses are not from the five
classes: a header date assigned to the neighbouring year column on a six-column results table (`Profit for the
period` 705 given `30-09-2024` where the printed column is `30-09-2023`; `Finance Costs` 102 given `H1FY25` for the
`H1FY26` column), a span row above the five-row header window lost (`ended > 31.03.2025` read as the quarter), two
printed labels merged (`Bad Debts ... Current Liability Ratio`), a printed value merged into its label (`East Coast
Volume ... 22.4`), and a `12MFY25` column stored as `Q4FY25`. The build is `.tmp/v2r5` (74,259 cells, period 94.9%,
scale 85.4%); the round-4 store stays read-only at `D:/RealityEngine/v2/p20_r4`, the round-3 store at
`D:/RealityEngine/v2/p20_r3` and the round-1/2 stores at `D:/RealityEngine/v2/p20_r1` and `.tmp/v2r2`. Opus grades
rows 50-79 of each seed-17 sample independently.

**Round 6 (9 Nov 2026).** The round-5 **regression** is fixed first: a bare currency in a label (`EBIT Rs`, `Total
Revenue 1 US$`, `Total Assets ₹`) set scale 1 even though the row prints its unit in its own cell or the table title.
Scale now comes, in printed order, from (a) the row's own unit cell (`Rs Mn`, `₹ Cr`, `US$ Mn`, `US$ Bn`, `Mn Min`,
`Nos`), (b) the label's own scale word, (c) the nearest table note / section title (`Amount in US$ Mn, except ratios`,
`Consolidated Financials (Rs Mn)`), (d) the page unit; a per-unit row (ARPU, per share, per tonne, `/unit`) keeps
scale 1, and with no scale printed anywhere the scale is NULL, never 1. Cells with unit Rs/INR/USD at scale 1 and
value >= 1000 fall from **4,548** (round 5; round 4 1,838) to **18**. The eight structural classes each have a test:
(1) **row unit cell** - the cell is split from the label by x-position, and a currency-only cell still supplies the
currency; (2) **table note** - the nearest digit-free row above the table names the unit, so the `Amount in US$ Mn`
table's `Access charges` 61 is USD million, not Rs million; (3) **two-line labels** - a tail line joins its row when
the line above ends in `&`/`and`/`of`/`before`, leaves a bracket open, starts lowercase or is a single word under a
label that filled its column (`Cash profit ... Derivative &` + `Exchange Fluctuations`, `Logistics (other than
Trucking &` + `International Freight Network)`, `[Share capital + other equity]`, `Enterprises`); (4) **measure
rows** - a measure group names only the columns its x-span covers (a `Q-on-Q Growth` pair never names the level column
beside it) and a measure row above the five-row window is still added when it sits directly over the period row; (5)
**periods** - `H1 > FY27` / `Q2 > FY27` printed on two header lines are the half / quarter of FY27, not the full year,
a header segment that is only `Year` is FY, a balance row under `For the Quarter ended` is a POINT and keeps its
`Segment Liabilities` parent, and a cash-flow page titled `for the half year ended` fills a span the header stack
lost; (6) **spaced digits** - `3 1.03 .2025` squashes to `31.03.2025` (only when the whole run is one date) and a
date row the text layer split onto two y-rows still names its columns; (7) **row offset** - in a two-flow table
(labels and figures printed on separate lines) each label line takes the first figures below its baseline, so Coal
India's `Finance Costs` keeps its -290 and `Depreciation ...` its -670; (8) **bullets** - a label starting with a
bullet glyph, or a bracket-less sentence longer than twelve words, is not a row. Measured 9 Nov 2026 with
`python -m reality_engine.v2.build_cells --store D:/RealityEngine/p20/p20new.db --out .tmp/v2r6` (the same 76 decks
and 113 results since 2025-04-01):

| doc type | documents | pages | skipped (no text / no table) | cells | period_id | scale | no header | seconds |
|---|---|---|---|---|---|---|---|---|
| deck | 76 | 3,124 | 2,761 (79 / 2,682) | 13,543 | 83.5% | 79.6% | 0.0% | 80.5 |
| results | 113 | 1,805 | 1,099 (33 / 1,066) | 60,290 | 97.8% | 86.3% | 0.0% | 51.4 |
| total | 189 | 4,929 | 3,860 (112 / 3,748) | 73,833 | 95.1% | 85.1% | 0.0% | 131.9 |

Methods: `text_layer` 69,131, `text_layer;garbled` 1,112, `text_layer;delta` 3,584,
`text_layer;delta;garbled` 6. Wolf's own grade of the first 30 rows of each seed-23 sample (`.tmp/f6_results.csv`,
`.tmp/f6_deck.csv`): **results 26/30**, **deck 24/30** fully right (label leaf, header, period, unit and value),
against 24/30 and 23/30 in round 5. The remaining misses: a header that merges two printed dates into one phrase
(`30.09.2025 30.06.2025`), the class-1 ARPU regression (a bare `US$` unit cell loses its currency and falls back to
the page's Rs), two printed labels merged (`Bad debts ... Current Liability Ratio`), a cut label and a prose fragment
on decks, and the round-5 pairs still open (a span row above the header window, a printed value merged into its
label). The round-5 store stays read-only at `.tmp/v2r5` of the round-5 worktree and the round-4 store at
`D:/RealityEngine/v2/p20_r4`; the round-1/2/3 stores stay at `D:/RealityEngine/v2/p20_r1`, `.tmp/v2r2` and
`D:/RealityEngine/v2/p20_r3`. The sampler for this round:
`python -m reality_engine.v2.cell_sample --store-dir .tmp/v2r6 --n 100 --type results|deck --seed 23 --out .tmp/f6_results.csv`
(deck writes `f6_deck.csv`). Opus grades rows 50-79 of each seed-23 sample independently.

**Round 7 (9 Nov 2026).** The class order of the round-6 grade is fixed, each with a test in
`reality_engine/tests/test_v2_table_cells.py`: (1) **bare currency unit cell** - a unit cell with no scale word
(`US$` beside `Average Revenue Per User (ARPU)`) is that currency, scale 1 when the row is per-unit and scale NULL
otherwise, never the page's Rs; (2) **multi-measure span tables** - a period header printed once over a run of
measure columns (`Q1 FY27` over `Revenue | EBITDA | PAT`) is spread over the columns its group covers, the measure
row is kept on either side of the period row, and a measure may print its unit in brackets (`Total Income (Rs
crores)`), so every cell carries `measure=<text> > <period>`; (3) **labels inside tall figures** - a label whose box
sits inside a 28-point figure box belongs to that figure row, so the Coal India ratios' `Cost of Materials Consumed`
keeps 2,752 and `Changes in inventories` 3,052 (the text layer prints the figures before the label); (4) **merged
header dates** - `31.03.2025 I 31.03.2024` in one phrase is split into two column headers by character position, so
1,637.14 is FY25; (5) **periods** - a table title row (`Q3 FY26 & 9M FY26 key financials`) is not a column header, a
mixed `3 months ended | 6 months ended | Year ended` row is read as group spans (Titan's year column is FY25), a
block that yields no cell keeps its rows in the next block's header context, and a cash-flow table's later column is
the one whose opening cash equals the other column's closing cash (never the same period twice); (6) **units** - a
`bps` column is `bps`, scale 1, and a label printing `(MMT)` is `MMT`, not a bare count; (7) **two rows in one label** -
a roman/letter marker starting mid-label (`ii)`, `ii,`) begins its own printed row; (8) **interleaved dimensions** - a
repeated sub-header over date columns (`HDFC MF | Industry` under `Mar-24 | Dec-24 | Mar-25`) enters `col_header` as
`dimension=<text>`. Measured 9 Nov 2026 with
`python -m reality_engine.v2.build_cells --store D:/RealityEngine/p20/p20new.db --out .tmp/v2r7` (the same 76 decks
and 113 results since 2025-04-01):

| doc type | documents | pages | skipped (no text / no table) | cells | period_id | scale | no header | seconds |
|---|---|---|---|---|---|---|---|---|
| deck | 76 | 3,124 | 2,757 (79 / 2,678) | 13,995 | 83.3% | 82.7% | 0.0% | 81.3 |
| results | 113 | 1,805 | 1,090 (33 / 1,057) | 61,851 | 97.7% | 86.3% | 0.0% | 46.9 |
| total | 189 | 4,929 | 3,847 (112 / 3,735) | 75,846 | 95.1% | 85.7% | 0.0% | 128.3 |

Methods: `text_layer` 70,837, `text_layer;garbled` 1,276, `text_layer;delta` 3,726,
`text_layer;delta;garbled` 7. The round-6 scale regression check (cells whose label is not per-unit, unit Rs/INR/USD,
scale 1 and value >= 1000) is 0; the 150 cells at scale 1 and value >= 1000 are all per-unit rows (ARR/RevPAR in Rs,
`Price (In Rs./Te.)`, `Overall Average Realization`, ARPU), which are rupees per unit by design (d). Wolf's own grade
of the first 30 rows of each seed-29 sample (`.tmp/f7_results.csv`, `.tmp/f7_deck.csv`): **results 28/30**, **deck
26/30** fully right; the drops are a `Total` row whose segment parent is lost, a measure spread onto a level column, a
per-tonne realisation given `%`, an `Inc / (Dec) > Wrt 31.03.26` column read as a point, and one merged label. The r7
store loses **two** rows that an earlier round graded right: Coal India results p20's Key Financial Ratios table (the
two-column ratios-plus-remarks layout prints its header dates left of the figure anchors and the table's rows are
separated by label lines, so the block splits and the second part resolves no header) and Indhotel deck p33's
`Less : Share of Non Controlling Interest` -96% (the row no longer pairs with its value); both are the open merge
gate. No other r6 graded-right row changes label leaf, value, period, unit or scale (checked across `.tmp/f6_*.csv`
and the r5 seed-17 samples; the remaining r5 differences are the round-6 scale/unit fixes, not r7 regressions). The sampler for this
round:
`python -m reality_engine.v2.cell_sample --store-dir .tmp/v2r7 --n 100 --type results|deck --seed 29 --out .tmp/f7_results.csv`
(deck writes `f7_deck.csv`). Opus grades rows 50-79 of each seed-29 sample independently.

**Round 8 (10 Nov 2026).** The structural classes of the round-7 Opus grade are fixed, each with a test in
`reality_engine/tests/test_v2_table_cells.py` (8 new, `test_round8_step*`): (0) **lost right rows** - a word that
crosses only the table's RIGHT edge (the `Remarks` column of Coal India's Key Financial Ratios table) is trimmed
instead of dropping the header row, and the label line printed directly over a block's first figure line is that
row's label, so CIL results p20 gives `Debt Equity Ratio` / `Current Ratio` again; `_title_phrase` now needs three
non-glue words, so Indhotel's `Var. vs FY24` growth column is no longer taken for a table title and its
`Less : Share of Non Controlling Interest` -96% pairs again. (1) **point vs range** - the stock word list of
`label_map.STOCK_METRICS` bounds a POINT row (net debt, borrowings, shareholders'/owners' equity, net worth,
market capitalisation, enterprise value, cash level, AUM, order book, receivables/payables/inventory, population
and coverage), and a flow word in the same label (increase/decrease, adjustments, purchase, proceeds, net cash,
working capital, impairment loss) keeps the column's period; a page titled "... Assets and Liabilities as of and
for the quarter ended" is no longer read as a balance sheet. (2) **measure from a measure row** - a one-cell
measure heading at the left (`1. Segment Revenue`, `2. Segment Results`) names every column of its section,
taken from the label column and from a table title (`Revenue Analysis` -> `measure=Revenue`). (3) **title parent** -
the nearest table/segment title above the header stack is the parent of every row (`Airtel Business > Total
revenues`, `Passive Infrastructure Services > Total revenues`); letterheads (all caps / LIMITED) and statement
titles are rejected. (4) **column alignment** - `Q 2` / `H 1` count as period words, and a row that prints fewer
values than columns keeps the printed x-alignment (Adani p12 `(24.41)` is -24.41 on the Q4FY25 column, not FY25).
(5) **units, scale, sign** - `in 000's` / `000's` is scale 1000, a bare `Bn` on a population/coverage row is a
count and never Rs, `(400` + `bps)` joins to `(400 bps)` = -400 bps, and a decimal-free figure at least 50x both
its column neighbours is stored with `value` NULL and `method` carrying `;junk_suspect` (Havells' OCR 300.78 as
`30078`). (6) **values before labels** - a label printed up to 6 points above its figures pairs with that row
(Pidilite deck p28: `Staff Costs` 471, `Other Expenses` 485, `EBITDA` 2,071). (7) **two ratios on one label** -
the text layer gluing two ratio rows together keeps the row printed second (`Net Profit Margin on Net Sales`).
Measured 10 Nov 2026 with `python -m reality_engine.v2.build_cells --store D:/RealityEngine/p20/p20new.db
--out .tmp/v2r8` (the same 76 decks and 113 results since 2025-04-01):

| doc type | documents | pages | skipped (no text / no table) | cells | period_id | scale | no header | seconds |
|---|---|---|---|---|---|---|---|---|
| deck | 76 | 3,124 | 2,752 (79 / 2,673) | 13,540 | 82.4% | 86.9% | 0.0% | 77.3 |
| results | 113 | 1,805 | 1,096 (33 / 1,063) | 62,126 | 97.7% | 86.2% | 0.0% | 45.2 |
| total | 189 | 4,929 | 3,848 (112 / 3,736) | 75,666 | 95.0% | 86.3% | 0.0% | 122.6 |

Methods: `text_layer` 69,779, `text_layer;garbled` 1,717, `text_layer;delta` 3,705,
`text_layer;junk_suspect` 378, `text_layer;delta;garbled` 79, `text_layer;garbled;junk_suspect` 8. The round-6
scale regression check (cells whose label is not per-unit, unit Rs/INR/USD, scale 1 and value >= 1000) is **0**.
The two rows lost in round 7 are restored: the Coal India Key Financial Ratios table yields `Debt Equity Ratio`
0.13/0.09/0.07 at /2025-09-30, /2025-03-31, /2024-09-30 and the Indhotel `Less : Share of Non Controlling
Interest` row stores -96% / -83% with `period_id` NULL and `method='text_layer;delta'`. The sampler for this
round is
`python -m reality_engine.v2.cell_sample --store-dir .tmp/v2r8 --n 100 --type results|deck --seed 31 --out .tmp/f8_results.csv`
(deck writes `f8_deck.csv`); rows 50-79 are graded by Opus. The round-7 store stays read-only in its worktree.

**Round 9 (10 Nov 2026).** The classes of the round-8 Opus grade and replay check are fixed, each with a test in
`reality_engine/tests/test_v2_table_cells.py` (`test_round9_step1..5`; step 2 also has the HDFC AMC p6 regression):
(1) **flow beats stock** - the column header's printed Quarter / Half year / Nine months / Year ended decides the
kind first; a flow word (return, turnover, gain, loss, margin, income, expense, restatement, effect) inside a
label beats a balance word (equity, investments, inventory, cash), so Bharti's ROE pre/post tax, Titan's inventory
turnover and Havells/Adani's OCI gains, FX restatement and FVTOCI loss keep their quarter/half/year. Operating
counts (customer base, network towers, co-locations) and balance ratios (long-term debt to working capital,
current ratio, debt equity, book value per share) are points at the column date. (2) **measure only from header
rows** - a one-cell row label (`INCOME`, `Revenue from operations`, `1. Segment Revenue`) is the rows' section
parent, never `measure=`; the HDFC AMC standalone results page keeps all five columns (91 cells, round 8: 46) and
901.22 is Q4 FY25, because the wrapped date row ('March 31,' over the year and status rows) is no longer dropped by
a stray call-out figure. (3) **a ratios page's period ends** - on a page titled `Key Financial Ratios` a bare
30-September column is the half year and a 31-March column the fiscal year, so Coal India p20's Net Profit Margin
22% is H1 FY26 (not the July-September quarter) and its remarks column ('Increase in Average Inventory') is no
longer a parent; Debt Equity 0.13/0.09/0.07 stays a point. (4) **multi-level and year-sequence deck tables** - a
group-heading row names the run of columns on its side of the midpoint between headings, a sub-header refines only
the group run it is printed over, a row of period headings longer than 80 characters is still a header row, a
'Unit' cell crossing the derived left edge no longer drops its whole header row, and a dash placeholder is centred
in its cell so it no longer doubles a column's anchors. Adani's balance-sheet snapshot p49 (90 cells) and P&L
snapshot p61 (105) map FY22..FY25/9MFY26 by position; the port-volume tables p33/p42/p43 give 247 cells each with
`dimension=Total | Dry (MMT) | Containers | Liquid (MMT)`, their sub-headings (`Coal`, `Other Dry`, `'000 TEUs`,
`MMT`) and physical units (MMT, count x1000 for TEUs). Deck cells rise 13,995 -> **14,333** (round 8: 13,540),
1,039 round-7 deck cells that vanished are repaired rather than dropped. (5) **junk parents and page numbers** - a
bullet tail, a one-word letterhead, a lowercase title fragment (`th`), a remarks column and a boxed side figure no
longer become a row's parent; `Page 13 of 59` (even split across rows) is not a cell; and a restatement label split
by the text layer keeps both halves (`Regrouped Employee Benefits Expense`). Measured 10 Nov 2026 with
`python -m reality_engine.v2.build_cells --store D:/RealityEngine/p20/p20new.db --out .tmp/v2r9` (the same 76
decks and 113 results since 2025-04-01):

| doc type | documents | pages | skipped (no text / no table) | cells | period_id | scale | no header | seconds |
|---|---|---|---|---|---|---|---|---|
| deck | 76 | 3,124 | 2,755 (79 / 2,676) | 14,333 | 83.4% | 87.2% | 0.0% | 76.9 |
| results | 113 | 1,805 | 1,097 (33 / 1,064) | 62,772 | 97.7% | 86.1% | 0.0% | 45.3 |
| total | 189 | 4,929 | 3,852 (112 / 3,740) | 77,105 | 95.1% | 86.3% | 0.0% | 122.2 |

Methods: `text_layer` 71,355, `text_layer;garbled` 1,543, `text_layer;delta` 3,738,
`text_layer;junk_suspect` 388, `text_layer;delta;garbled` 73, `text_layer;garbled;junk_suspect` 8 (deck:
11,658 / 273 / 2,339 / 16 / 47 / 0; results: 59,697 / 1,270 / 1,399 / 372 / 26 / 8). The earliest-round scale
regression check (cells whose label is not per-unit, unit Rs/INR/USD, scale 1 and value >= 1000) stays **0**.
Replay gate: `.tmp/replay_r9.py` re-checks every row graded right in the r5, r6, r7 and r8 Opus grade files
(136 rows) against `.tmp/v2r9` by doc + page + printed value, comparing label leaf, value, period, unit and scale:
**136 kept, 0 lost** (r5 40/40, r6 33/33, r7 26/26, r8 37/37; one line per row in `.tmp/v2r9/replay.csv`). The
eight rows lost in round 8 and the seven junk-parent rows are all restored; the three rows that needed a
label-prefix or point-period tolerance are listed in the CSV with their old and new values. New seed-37 samples for
hand grading: `.tmp/f9_results.csv` and `.tmp/f9_deck.csv` (100 each, ungraded). Merged 10 Nov 09:45 after the independent Opus grade (seed 37 rows 50-79: results 21/30 strict, deck 22/30; replay 136/136 verified by script; grades `D:/RealityEngine/v2/review/T-132_r9_opus_grades.csv`). The round-9 store is kept read-only at `D:/RealityEngine/v2/p20_r9`; every round's samples (f5-f9), `replay_r9.py` and `replay_r9.csv` are in `D:/RealityEngine/v2/review/samples` (the worktrees are removed).

The full rule set (a-j) was last rewritten for round 5; round 6 adds, under d: the row's own unit cell is split from
the label and read before the label's scale word; under e: a two-line period label, a bare `Year` segment and the page
title's span; under a: the two-flow label/figure pairing and the tail-line join; under g: bullets are not rows.
Round 7 adds, under d: a bare-currency unit cell keeps its currency (scale 1 on a per-unit row, NULL otherwise) and a
`bps` column is `bps`; under a: a label printed inside a tall figure box stays with that row, a measure row may sit
below the period row and a repeated sub-header becomes `dimension=`; under c: a phrase holding two printed dates is
two headers; under e: a table title is not a header, a block that yields no cell leaves its rows to the block below,
and the cash-flow cross-check orders columns; under b: an `ii)` / `ii,` marker starts a new row.

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

## 11. Label map (T-133, v8.1 10 Nov 2026)

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
("39l" in "> ?,39L.64"), or - **v8** - the share of its words that are **OCR damage**. The vocabulary is the
built-in label/line words, the common lexicon phrases, **the corpus** (every word the cells print in two or more
documents, collected by `read_cells` and `run` through `set_corpus_vocabulary`) **and, from v8.1, pilot3's
`en_vocab.txt` ordinary-English list**; a word counts as damage only when
it is out of that vocabulary and within edit distance 2 of a word in it, and a label of two or more words is
garbled when at least 40% of its words are damaged. **v8.1** a token shorter than five letters is not damage on
edit distance alone (the unit `mmt` is not `mt`; `west`, `golf`, `teus` are words), a three-letter token counts
only one edit from a **statement-line** word (`lax` for `tax`), and an English-list token is never damage, so
`revenue from golf course operations`, `west coast volume mmt share`, `personal care`, `others` and
`rail container volume teus` queue instead of being rejected; `con sumed` rejoins to `consumed`, and the OCR
measure forms the review named are repaired (`totalexpenses` -> `total expenses`, `lialrilities` -> `liabilities`,
`jnvesunents` -> `investments`, `lnve.1otmc11ts` -> `investments`, `Divider) el received` -> `dividend received`).
"CRAR (standalone)", "purchase of treasury shares", "employee
benefits expense", "revenue from top ten customers", "optic fibre network r kms" and "mundra volume mmt share" are
real lines, so they queue; "iopening balance", "gpwis mmt" and a no-vowel word soup ("xqzt vbnm") are rejected. A
label that matches a lexicon phrase whole is never garbled, a container child (`JVs > ...`) is exempt so an acronym
member survives, and **v6/v7: a label with a clean numeric cell in two periods of one document or in two or more
documents is never garbled** - the evidence is checked before the dictionary, so real members the dictionary lacks
(`krishnapatnam`, `lighting and fixtures`, `lloyd consumer`) and real lines with a date or OCR-damaged numbering
(`Order Book - 31 Mar26`, `Real Estate`, `Non Participating Health`) are proposed, not rejected; **v8:** a trusted
label still has to look like a word (`ddutcd`, one vowel in six letters, is not a member), and a token one edit from
a dictionary word ("lax" for "tax") is damage whatever the trust evidence says; **v8.1** an untrusted `real estate`
queues with no metric rather than being rejected, because both words are ordinary English.
One-edit OCR typos are repaired token by token (`Provisiuns` -> `provisions`), and a truncated label whose
unmatched bracket ends the cell ("`(Excl.`") is rejected as `truncated label`; an OCR footnote inside a whole
label ("`(loss}`", "`(A+B\\`") is not truncation. **v7:** a label whose only damage is a digit glued into one token
is readable when the rest of it is a dictionary line, so `0ther expenses`, `1c1 provisions`, `total rrabi6ties` and
`lec1se liabilities` queue instead of being rejected; only a label with no readable part (`9b bb`, `to1al`) stays
character-level junk. The OCR fixer never rewrites a token the dictionary holds: `consumer` stays `consumer`
(never `consumed`), so `Electrical Consumer Durables` and `Lloyd consumer` keep their member names. A printed date
tail is a column reference, not part of a metric (`Order Book - 31 Mar26` is `order_book`).

**Normalisation.** Lower case; OCR tokens repaired (above); leading numbering (`1.`, `(a)`, `i)`, `iv.`) dropped;
bracketed units and currency (`(Rs crore)`, `(₹ in Lakhs)`, `(%)`, `(as a % of revenue)`) dropped; `%`, currency
marks and punctuation dropped; `&` becomes `and`; `/` becomes a space. A parent is joined with `' > '` only when
the child is ambiguous alone (`Others`, `Other`, `Total`, `Sub-total`); before v2 every generic child kept its
parent, which hid "Total expenses" under "Expenses".

**Rule 2 — seeds.** A `kpi_series` raw label seeds a proposal only when its own label passes rule 1 and the lexicon
does not disagree (the lexicon is the reviewed contract, the seed a usage witness). A failing seed is ignored and
listed in `rejected_seeds.csv` with the metric the new rule would give it. v6 adds one exception: a `total
revenue(s)` seed may say either `revenue` or `total_income`, because rule 8 decides it at the table, so the 1,922
seed rows v5 rejected as "metric conflict" are accepted again (zero total-revenue conflicts in v6). **v7:** the
same whole-label rule is implemented in `reality_engine/pilot3/kpi.py` as `row_label_hits`/`label_text`, but it is
the **dry-run diagnostic**, not the live path: the `table_v1` extraction path stays on `main`'s
`label_matches` + `_own_row_hits` (with `total revenues?` under `revenue` in `common.yaml`), so the next KPI
rebuild loses no right row. `kpi.py` has no table
arithmetic, so the diagnostic maps a `total revenue(s)` row through the restored alias rather than guessing
`total_income`; `seed_changes.csv` lists every row the diagnostic rule would change.

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
never from the label map (v1 carried `inr` for dollar lines). **v8:** the label's own unit word wins over the
metric definition in `metric_def` (`(Excl. Other Qty.(In Mill. Te)` is `volume` in `tonnes`, `Total Minutes on
Network` is a `count`, `Current Ratio` is `x`); the unit word lives in `Proposal.unit_kind` and `_metric_defs`
takes the majority of the proposals' stated units before `resolve_unit_kind`. A sales row printed in tonnes is
`sales_volume`, not money (`Sales Million Tonne`).

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
stock id. **v7 `from_header`:** a parent that names the measure owns its child (`Share of profit of: > Associate
and joint venture` is `share_of_jv_profit[associate and joint venture]`), a child under a cash-flow
movement/adjustment parent is the change (`Changes in assets and liabilities > Provisions` is
`change_in_provisions`), never a member, a one-letter child (`Segment Assets > A`) is a parsing fragment that
queues, and a child of an "attributable to" parent made only of short/OCR fragments is the parent's total. A
`Total ...` row whose qualifier is OCR damage (`Segment Liabilities > Total raabinties`) is the section total, not
a member. `ARR (LFL)`, `Occupancy % (LFL)` and `Cheques, draft on hand` are measures (the `LFL` basis is a
qualifier, the cheque line is a statement line), never `from_header` members. **v8:** a weak member leaf with no
word the vocabulary or the corpus knows queues instead of becoming `from_header` (`Receivables > Jnvesunents`,
`Ddutcd`), while a measure header, an entity name, a container parent or the two-document evidence still carries a
real name (`JVs > AICTPL (CT-3), JV with MSC`, `krishnapatnam`). The parent's own wording decides an attribution
row: `... attributable to > Owners oftl1c Parent Company` is `total_comprehensive_income_attributable`
(`attribution=owners_of_parent`), and a TCI total that names no owner is `total_comprehensive_income`, not the
owners' line. A period note under a measure is the measure (`[b) Deferred Tax > Period/ Year (7'B)` is
`deferred_tax[period year 7 b]`; the scan's `[b)` is read as the numbering mark `(b)`), and an OCR-split "profit
from segments before finance costs..." parent owns its member (`profit from gm nt b f fin n t nd t > Jewellery` is
`segment_results[jewellery]`). **v8.1:** a reporting-basis word (`conso`, `consol`) is a heading, never a member; an
OCR-near measure leaf maps to the measure instead of a member (`Receivables > Jnvesunents` is `investments`,
`Divider el received` is `dividend_received`, `Trade lialrilities` queues); `All-India container` (market share) and
`Cargo (MMT)` (volume) are measures, not members; under `Expenses`, `Food and Beverages Consumed` is a cost line,
not `total_expenses`; a TCI leaf under an OCI parent is `total_comprehensive_income_attributable` (the OCR `tota`
is repaired to `total`); and one OCR-merged row carrying Other Equity plus an EPS line queues (the EPS guard now
reads `EPS` in any case).

**Rule 6 — junk, headings and garbage.** A label of digits/period tokens only, a digit glued to a word
("expe1", "39l"), a value token ("45,000 160% EBITDA"), a sentence fragment ending in an auxiliary verb ("The Parent
Company has"), a truncated label ("`(Excl.`"), or a statement heading ("Financial assets", "Particulars") is
`status='rejected'`, never a proposal; "45 000 160 ebitda" no longer seeds `ebitda`. A trailing footnote digit
is not a glued word (`ebitdaal1`, `mundra1`). A one-edit OCR variant of a one-word heading is that
heading (`Particulats` -> `particulars`), and a heading row whose cells are all dash/blank in a table (`Current
assets` with only "-" at Apollo Tyres) is rejected for that family only: the same label with numbers is that
table's total and stays mapped. **v7:** a digit glued into a readable line is not junk; the rejection is kept for
character-level junk only (`9b bb`, `to1al`, the OCR `39l`), so readable rows go to the review queue instead.
Heading fragments (`Particulars`, `Less`, the OCR `otal`) are `status='rejected'`
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

**Rule 10 — suffixes, evidence, replay honesty and the live path (v6/v7).** A suffix that names the metric's own unit is never
stripped into a broader metric: `EBITDA/ton`, `EBITDA/tonne`, `EBITDA/tonne $/tonne` stay
`ebitda_per_tonne`, and `CASA %` is `casa_ratio` (percent, not the `casa` money line). A seed stands whenever the
lexicon agrees or is silent on the label's own wording (rule 2), so `VoNB margin` keeps `vnb_margin`. The garbled
rule reads evidence first (rule 1). A row the reviewer already graded right is **LOST**, not fixed, when it now
maps to NULL, a queue with no metric or a rejection; the `--replay <grade.csv>` pass (`replay_grade`) applies
that rule, treats a documented v4 id rename (`revenue_from_operations` -> `revenue`,
`cash_generated_from_operations` -> `cash_flow_from_operations`, the two v3 `_pct` slugs) as kept, and treats a
right `from_header` that now has the section's metric as an upgrade, not a loss. Every kept-with-reason and
changed row is carried by the per-row `grade_replay_*.csv`. **v7 splits the two jobs** (the whole-label rule is the map's rule and
the dry-run diagnostic, the live `table_v1` extraction path of `reality_engine/pilot3/kpi.py` stays on `main`'s
`label_matches` + `_own_row_hits`); **v8 corrects v7's claim that the lexicon edits do not reach that live path:**
they do, because `label_matches` reads every yaml. The exclusions therefore sit **in the label pattern**, not in the
`neg` list whose window is 10 characters before and 14 after a match: `net cash(?! ... generated|from|used|flows?|
operating|...)`, `\barr\b` (never "carried"/"arrangement"), `(?<!margin\son\s)revenue from operations?(?! margin)`,
`^(?:net\s+)?working\s+capital\s*$` for the balance and a `working capital ... days|cycle` lookahead for the days
KPI, `^total equity (and|&) liabilities\s*$`, and the `dividend income` / `dividend received` split. `_own_row_hits`
drops a shorter hit that starts where a longer whole label starts, so "Revenue per tower per month" and "Sales and
marketing expenses" no longer store a `revenue` row beside their own metric. **v8.1** `_own_row_hits(hit, label)`
makes a `section > leaf` row the leaf's row: a hit inside the leaf must start the leaf (a numbering mark or a
filler word such as `Total` may precede it, so `> (f) Net profit after tax` and `> Total segment revenue` still
match, while `Note: > ... Total Income include` does not), a leaf that is another line owns the value
(`Dividend income > Finance costs` is `finance_cost`, not `dividend_income`), and a section phrase survives only
before a member leaf (`Segment Liabilities > APMEA`) or a bracketed note leaf (`Debt equity ratio > (i) [Debt
comprises ...]`). The gate is the live A/B (`D:/RealityEngine/v2/review/label_map_v81/live_kpi_ab.py`, output
`D:/RealityEngine/v2/review/label_map_v81/live_kpi_ab.md`): the live matcher over the distinct `table_v1`
labels of the five stores (22,005 rows, 1,083 distinct labels) and the p20_r4 cells (59,326 numeric cells), with
`main`'s lexicon vs the branch's (the review's method) and v8 code + lexicon vs v8.1; every metric
moving more than 10 rows or cells must be right-added or junk-removed. The A/B passes: the lexicon adds
`net_debt_to_ebitda` 36 stored rows (SRF's `Net Debt to EBIDTA`) and nothing else; against v8 the leaf rule adds
`operating_free_cash_flow` 298 cells (the OFCF lines v8 stored as `capex`), removes 23 `dividend_income` junk
cells, 4 `total_income` junk cells, 177 `ebitda` margin cells (`As a % of Total revenues > EBITDA`), 124 `pat`
margin cells and 15 `revenue` cells (4 of them right, `Revenue in Rs Cr > Total` - under 10); no stored row is
lost. The whole-label dry run resolves each company's sector family exactly as the build does (without it every
`sectors:` entry looks lost).

**Outputs** in `--out`: `label_map.db` (the `label_map` and `metric_def` tables, the v2 DDL; `label_map` rows carry
`dimension`, `unit_kind` and `status`), `review_<family>.csv` and `review_common.csv` (label_norm, example raw
labels, frequency, companies, proposed_metric, dimension, unit_kind, reason, **rule**, **confidence**,
**status**; every observed label, mapped or not, sorted by frequency), `coverage.txt` (mapped share of the numeric
`table_cell` rows per family and overall, the rejected count, the mapped-or-queued share, and the 50 most frequent
unmapped labels), `rejected_seeds.csv`, `seed_changes.csv` (the read-only dry run of the new rule over the
`table_v1` rows of the `kpi_series` stores, by `(old, new)` metric pair, with each company's sector family
resolved as the build does), `sample_seed61.csv` (200 proposed
rows at `random.Random(61)`, spread over families, ungraded, for Opus to grade) and `rejected_seed61.csv`
(40 labels that stay rejected, `random.Random(59)`, ungraded, so the garbled rule is reviewed on its rejects, not
only on its proposals). `rule` is the step that proposed the row (`1-match`, `2-seed`, `3-qualifier`, `3-member`,
`5-context`, `8-table`, `section:parent`, `section:total`, `table:total`, `section:change`, `section:channel`,
`percent:label`, `child:total`,
`6-reject`, `heading`, `garbled`); `confidence` is `exact`, `synonym` or `section`. `from_header` has no
`metric_def` row: its kind comes from the header's measure. `--replay <grade.csv>` writes
`grade_replay_seed31.csv`, `grade_replay_seed37.csv`, `grade_replay_seed41.csv`, `grade_replay_seed43.csv` and
`grade_replay_seed47.csv`
(the graded row, its graded metric, every v6 metric the label can take, the kept/changed/unchanged/LOST status and
the reason); the `grade_replay_seed*.csv` files carry the zero-lost summary, every right row kept through a sanctioned rename or
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

**Measured 10 Nov 2026 (v8.1)** on `D:/RealityEngine/v2/p20_r4` (read-only, 10 company files, 74,486 `table_cell`
rows) and the `kpi_series` of `pilot10.db`, `p20/p20new.db`, `u8/u8.db`, `q12/q12.db` and `n10/n10.db` (34,910 rows;
v7 measured four stores): 5,436 `(label, family)` observations, 2,020 proposed mappings (rule 1 match 709, seed
485, member 231, qualifier 30, context 541, table total 22, label unit 2) and 236 `metric_def` rows (flow 99,
stock 62, ratio 68, per_share 3, price 4; the new one is `net_revenue`, Bharti's net-of-access line). Of the 59,326
numeric table rows, 42,237 (71.2%) map to a proposed metric, 617 are rejected as junk/heading/garbled (290
rejected labels, 57 of them garbled over 105 numeric cells), and 59,172
(99.7%) are mapped or queued in the review CSVs; 154 rows have no label. Before v8.1 (v8, same stores): 42,341
(71.4%) mapped, 882 rejected cells and 431 labels, 197 garbled over 397 cells. The small mapped decrease is
deliberate: the v8.1 guards queue rows v8 mapped wrongly (the Other-Equity+EPS merges, cost lines under `Expenses`,
measure leaves), and the English-vocabulary garbled rule removed 332 rejections. `ports_logistics` is the only
family below the 60% per-family line (59.2%, v8 60.1%); the stop rule (below 60% **overall** coverage) was not hit.
The seed dry run (sector-aware; see rule 10) changes 3,230 of the 22,005
`table_v1` `kpi_series` rows of the five stores in 34 pairs; every metric moving more than 10 stored rows or cells is
right-added or junk-removed in the live A/B of rule 10, which is the merge gate. Output kept at `D:/RealityEngine/v2/review/label_map_v81`
(`label_map.db`, the review CSVs,
`coverage.txt`, `rejected_seeds.csv`, `seed_changes.csv`, `sample_seed61.csv`, `rejected_seed61.csv`,
`grade_replay_seed31.csv` ... `grade_replay_seed53.csv`, `live_kpi_ab.md`, `build.log`); nothing is `approved` until
Opus works through the review files.

**Opus grade replay (v8.1, zero lost right rows).** The v5 replay counted a right row dropped to NULL as "fixed";
v6 counts it LOST (step 8), and v8/v8.1 keep that rule over all six grade files. Seed-31 (139/200 right) keeps all
139, LOST 0 (32 wrong rows change, 9 stay the same, 20 still unmapped); seed-37 (170) keeps all 170, LOST 0 (13
changed, 12 unchanged, 5 unmapped); seed-41 (177) keeps all 177, LOST 0 (4 changed, 14 unchanged, 5 unmapped);
seed-43 (180) keeps all 180, LOST 0 (5 changed, 12 unchanged, 3 unmapped); seed-47 (181) keeps all 181, LOST 0
(8 changed, 6 unchanged, 5 unmapped); seed-53 (184/200 right, the v7 grade) keeps all 184, LOST 0 (9 changed, 6
unchanged, 1 unmapped, the extra changes being the v8.1 member/measure routing). The v8 run first queued seven
graded `from_header` names (mobile services south asia,
tower infrastructure services, benares hotels ltd, p11ssive infrastructure services, appdcl, trucking and
asia > passive infrastructure servi) - a near-word damage test was flagging names the corpus had made neighbours
of ordinary words - so the member guard now reads only a one-edit distance to a **statement-line** word and keeps
the graded members (zero lost restored).
Right rows whose answer changed but stayed right are listed per row in the `grade_replay_*.csv` files: a documented v4
canonical rename (`cash_profit_from_operations_before_derivative_and_pct` ->
`cash_profit_from_operations_pct`, `operating_expenses_excluding_..._pct` -> `operating_expenses_pct`,
`revenue_from_operations` -> `revenue`) and a `from_header` row that now has its section's metric (three seed-31
segment-liability rows). The rule changes the review named all land: the total-revenue table proof (IHCL
`total_income`, Bharti `revenue`), the flow/stock split (`change_in_trade_receivables`/
`change_in_trade_payables`, `profit_attributable` and `other_comprehensive_income` attribution), the unit suffixes
(`ebitda_per_tonne`, `casa_ratio`, `vnb_margin`), the 19 seed-31 NULL rows now mapping (inventories, borrowings,
depreciation, finance costs, cogs, exceptional items, securities premium, sales and marketing, intangible assets,
the cash-flow changes, owners' profit), the mixed unit rows (`eliminations` money, `current_liability_ratio` x),
the channel/mix members (`volume[fsa]`, `vertical_mix[retail]`, `aum_mix[asset_class=liquid]`), the
truncated/OCR/merged-label rejects and `Provisiuns` -> `provisions`. The per-row detail is in
`grade_replay_seed31.csv`, `grade_replay_seed37.csv`, `grade_replay_seed41.csv`, `grade_replay_seed43.csv`,
`grade_replay_seed47.csv`, `grade_replay_seed53.csv` in `D:/RealityEngine/v2/review/label_map_v81`.

Tests: `reality_engine/tests/test_v2_label_map.py` (73 passed) cover the normalisation and unit-tail stripping, the
OCR repair table, the OCR space-join and the fuzzy section repair, rule 1 whole-label matching, garbled
rejection, the seed rule and seed-vs-lexicon conflict, qualifiers/dimensions, the definition basis, the exclusion
qualifier, measure parents and leaf-wins (CWIP/EPS), member -> `from_header` with the v3 evidence and the keep
list, statement lines never becoming members, the profit-attributable/dividend context fixes, the ratio-of-the-
previous-line base, the percent base metric, the section/known-child guard, unit kinds from
`metric_def`/quantity word/cells with NULL unknown and NULL `from_header`, canonical ids, junk/headings, the v5
rules 1-7, every line of the T-133 v2-v5 evidence lists, the review CSV columns and the seed-53 samples, the
`metric_def` check constraint, the sector map over the four pilot stores (skipped when the stores are absent),
one test per v6 step (the table total proof, the flow/stock split, the suffix/seed rules, the garbled evidence
rule, the 18 missed common lines, the `from_header` misuses, the smaller context rows, and the replay LOST rule)
and one test per v7 step (character-level junk only with the two-period evidence, the OCR fixer never rewriting a
dictionary word, `from_header` only for measures with ARR/occupancy/share-of-profit, and the smaller context rows:
net cash, working capital, the exceptional-items qualifier, the damaged total, the one-letter child and the
attributable total) and one test per v8 step (the corpus garbled rule against the 21 over-rejected labels with at
most 4 left, the measure parent / OCR leaf / attributable total / label units, and the live lexicon exclusions)
and one v8.1 test per fix (the 12 seed-59 over-rejected labels with at most 4 still rejected, the split-word and
OCR-leaf repairs, the `from_header` guard's basis/measure/cost/TCI/EPS cases, and `net_revenue` vs `total_revenue`).
`reality_engine/tests/test_pilot3_kpi.py` (108 pass, 6 fail at setup only
because pytest's `tmp_path` is denied in this dsh sandbox) covers `row_label_hits` (whole label, block heading,
plural), `label_text`, the evidence labels, the v7 step-1 test that the live path keeps `Total revenues` and
`ROA–PBT`, the v8 live-lexicon tests (net cash vs cash-flow totals, `arr` anchored, Coal India EBITDA margin
kept, the borrowing rows and the dividend split, the longest-hit rule) and the v8.1 leaf-match tests (the merged
`Dividend income > <line>` rows, the leaf's own metric winning, the Total Income note/sentence guard, SRF's
`EBIDTA` spelling and Bharti's `Net revenues`).

**Opus reviews (9-10 Nov 2026, history).** Families were right for all 40 pilot companies, but no family was
approved: v1's substring matcher produced systematic wrong proposals, v2 (whole-label matching) was graded
139/200 on its seed-31 sample with three structural classes left (member fallback, unit-kind default, a few wrong
metrics), v3 (context/member rules) was graded 170/200 on its seed-37 sample with one right row lost (the
exclusion qualifier in `operating_expenses_pct`), v4 was graded 177/200 on its seed-41 sample with no
previously right row lost, and v5 was graded 180/200 on its seed-43 sample: the Opus replay check found the
blanket `total revenue` -> `total_income` rule wrong for Bharti (1,922 seeds overridden), unit suffixes stripped
into broader metrics (`EBITDA/ton` -> `ebitda`), flow/stock ids sharing one key (cash-flow changes and NCI), the
garbled rule over-rejecting 979 labels / 7,907 cells, 18 common metrics with no map row, and a replay that
counted a right row dropped to NULL as fixed. v6 fixed those classes structurally (rules 8-10) with zero lost
right rows over the four grade files; Opus graded v6 181/200 on seed-47 and confirmed the replay (25/25 kept rows,
the dropped labels mapped again, the total-revenue arithmetic right) but **blocked the merge**: the same
whole-label rule on `kpi.py`'s live `table_v1` path would have dropped ~2,800 right rows on the next rebuild
(3,083 `revenue`, 581 `roa_pct`, 132 `ebitda`, 96 `pat`, 43 `crar_pct`, 41 `debt_to_equity`), the OCR fixer rewrote
`consumer` to `consumed` in 15 rows, 25 of 40 rejected labels were real lines, and ten `from_header` proposals were
measures. v7 fixes that structurally: the live path returns to `main` (`label_matches` + `_own_row_hits`, with
`total revenues?` back under `revenue`), the dry-run rule recovers `Total revenues`/`ROA–PBT`/`EBITDA Pre IND
AS`/`PAT after Minorities`/`CRAR`/`D/E`/`net debt excluding ...`, only character-level junk is rejected (two
periods of one document count as evidence), the OCR fixer leaves dictionary words alone, `from_header` is kept for
measure rows (ARR, occupancy, cheques, share of profit) and the smaller row classes (net cash, working capital,
exceptional items' NCI qualifier, the damaged total, the one-letter segment, the attributable total) are routed -
with zero lost right rows over all five grade files (rule 10). Opus graded v7 184/200 on seed-53 (v6 181),
19/40 true junk (v6 15) and confirmed the replay (0 lost over seeds 31-47, 25/25 kept rows), but **blocked the
merge**: the lexicon edits reach the live matcher, and Opus's live A/B over the 22,005 `table_v1` rows showed
~1,500 right rows gained but ~470 junk rows **added** (`net_cash` cash-flow totals, working-capital borrowing
lines, `dividend income` counted as a receipt, unanchored `arr`, revenue margins, and the old revenue row kept
beside the per-tower/S&M rows). v8 fixes those structurally: every exclusion is in the label pattern (so the live
matcher's short neg window no longer matters), the longer whole label wins in `_own_row_hits`, the corpus vocabulary
halves the garbled rejections (708 -> 431 rejected labels), the measure-parent/OCR-leaf/attribution/unit rules route
the seed-53 errors, and the live A/B gate passes (0 junk added >10, 0 right lost >10; 253 stored rows gain their
own right metric and 302 junk metric hits are removed, while the cells show ~1,000 right hits added and 105 junk
hits removed). Opus's v8 review (10 Nov) passed sample 190/200, rejected 28/40 and replay 0 lost, but named three
fixes before the next KPI rebuild: the new table lines must match the row's **leaf**, the garbled rule must spare
ordinary English words, and the `from_header` guard must keep basis tokens, measure leaves and cost/TCI rows out of
the member bucket. **v8.1 (10 Nov 2026)** lands all three (rules 1, 3 and 10 above): the live A/B passes with the
lexicon adding 36 right `net_debt_to_ebitda` rows and nothing else, and against v8 the leaf rule adds 298 right
`operating_free_cash_flow` cells while removing 23 `dividend_income` junk cells and the margin-in-parent rows; the
build maps 42,237/59,326 cells (71.2%) and rejects 617 cells (v8 882, garbled 397 -> 105), and all six grade files
replay with zero lost right rows. v1's build `D:/RealityEngine/v2/label_map`, v2's
`.tmp/label_map_v2` build
and seed-31 sample, v3's `.tmp/label_map_v3` build and seed-37 sample, v4's/v5's builds, v6's build and v7's build
are superseded by `D:/RealityEngine/v2/review/label_map_v81`.

## 12. Reference pages (T-177, 11 Nov 2026)

Whole-page ground truth for the completeness report (design: `tasks/FABLE_TESTS_2026-11-10.md` section 1). Module:
`reality_engine/v2/reference_pages.py`; test: `reality_engine/tests/test_v2_reference_pages.py`. Uses the free-reader client
from `reality_engine/scripts/extract_deck_figures.py` (`MODELS`, `render_jpeg_b64`), re-imported not copied.

Commands:

```
python -m reality_engine.v2.reference_pages sample --stores <db,...> --out <dir> --seed 20261110
python -m reality_engine.v2.reference_pages transcribe --pages <pages.csv> --reader <MODELS name> --input text|image --out <dir> [--split dev]
python -m reality_engine.v2.reference_pages reconcile --pages <pages.csv> --runs <dirA> <dirB> --out <dir>
```

- `sample` reads `doc`/`doc_page` in p20, u8 and q12 (read-only) and writes `pages.csv`: 60 pages, 30 deck / 20
  results / 10 annual report, only pages with a text layer and >= 15 value-numbers except 4 chart-only/no-text deck
  pages kept and flagged `unread`. Columns: `page_id, store, symbol, doc key, sha256, doc type, page, stratum,
  in_first_build, split`. Split rule: 30 `dev` and 30 `frozen`, balanced by doc type, no company above 4 pages; same
  seed -> byte-identical file (11 Nov: two runs, 60 rows, identical SHA-256 `BEED9B07D7274D24...`, 36.8 s and 40.2 s).
- `transcribe` saves `<page_id>.raw.txt` (every raw reply, also on error), `<page_id>.rows.json` and
  `transcribe_log.csv` (`page_id, reader, input, seconds, in_tok, out_tok, error, n_rows`). It refuses any reader whose
  `price` is not `(0.0, 0.0)` or whose id carries no free marker, and resumes by skipping existing `.rows.json` files.
  The prompt asks for JSON Lines, one object per cell: `table, row_label, col_header, value, unit`.
- `reconcile` writes `reference_cells.csv` (`page_id, table, row_label, col_header, value_text, unit_text, agreed,
  verbatim, sums_ok, settled_by`) and `disputes.csv` (both readers side by side). A cell is `agreed` when both readers
  give the same normalised value for the same table + row label + column header; `verbatim` when the value string is in
  the page text layer; `sums_ok` when a printed total equals the sum of the parts within 0.5% / 0.5; `settled_by=script`
  only when agreed and verbatim. A row with no table, row label and column header cannot be located in the grid and is
  dropped as `unlabeled` (counted in the per-page print), so prose pages do not collapse into one cell.

Readers tried on 11 Nov 2026 (8 dev pages, same 4 as round 1 plus 4 more: 4 deck, 2 results, 2 annual report; no paid
model called):

| Reader | Input | Pages with rows | Rows | Verbatim share | Mean s/page | Errors |
|---|---|---|---|---|---|---|
| `dots-studio/dots-3-note-preview:free` (Kilo) | text | 8/8 | 233 | 0.987 | 15.5 | 0 |
| `dots-studio/dots-3-note-preview:free` (Kilo) | image | 8/8 | 225 | 0.956 | 15.9 | 0 |
| `nvidia/nemotron-3.5-super-vl:free` (Kilo) | text | 8/8 | 228 | 0.987 | 11.6 | 0 |
| `nvidia/nemotron-3.5-super-vl:free` (Kilo) | image | 6/8 | 367 | 0.608 | 22.5 | 0 |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (Kilo) | text | 8/8 | 189 | 0.984 | 16.1 | 0 |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (Kilo) | image | 3/8 | 41 | 0.244 | 5.8 | 0 |
| `nvidia/nemotron-3-ultra-550b-a55b:free` (Kilo) | text | 8/8 | 229 | 0.987 | 26.1 | 0 |
| `nvidia/nemotron-3.5-lightning:free` (Kilo) | text | 8/8 | 320 | 0.678 | 28.5 | 0 |
| `longcat-2.5-preview-free` (Go) | text | 0/1 | 0 | - | 0.4 | HTTP 400 `Upstream request failed: Model is unavailable.` |

Working readers: the Dots model on both inputs, and the four Nemotron models on text. Image input is only worth using
with `nemotron-3.5-super-vl` (6/8). LongCat on Go stays unavailable (HTTP 400 with text input, 11 Nov). Step 5 is paid
now and is not called on any provider; `mimo` (Zen) is skipped because the sandbox denies its log file (EPERM).
`p012` (stratum `unread`, no text layer) and `p041` (results PDF page 4 is an auditor's review in prose, not a table)
are why not every page yields real cells.

Root cause of the round-1 empty replies: the model answered, and the reply was literally `[]` (`out_tok` 2), so the
parser was not dropping rows. The array-of-cells prompt with an explicit "Output [] if the page has no table" fallback
made the small readers take the fallback; the JSON Lines prompt with a two-line example and "output nothing if the page
has no printed numbers" returns rows on all 8 pages for six readers. Fence lines are stripped from the reply before
parsing (JSON array, JSON Lines and single objects all accepted).

Reconcile of the best two distinct readers (Dots text + `nemotron-3.5-super-vl` text) on the 8 pages: 277 cells, 128
agreed (0.462), 275 verbatim (0.993), 126 settled by script (0.455). Per page (cells / agreed / verbatim): p001
10/1.000/1.000, p002 18/1.000/1.000, p011 22/0.455/1.000, p012 0/0/0, p013 55/0.000/1.000, p014 90/1.000/0.978,
p041 20/0.000/1.000, p042 62/0.000/1.000. Agreement is low because the readers key the same printed values to
different table titles, row labels and headers (on p013 both read the EPS column but one anchors the values to `EPS`
and the other to the company name row); `verbatim` only proves the string is somewhere on the page, not that it belongs
to that cell, so it is necessary but not sufficient for a settled cell.

Test runtime: `python -m pytest -p no:cacheprovider reality_engine/tests/test_v2_reference_pages.py -q` -> 3 passed in
0.43 s (fixtures are small SQLite files under `.tmp`; `tmp_path` is not usable in this sandbox because
`.tmp/pytest-of-SYSTEM` is ACL-locked by an earlier SYSTEM session). Typecheck: basedpyright 0 errors on the module and
its test.

**Vote of readers (T-177, 11 Nov 2026).** `python -m reality_engine.v2.reference_vote --pages <pages.csv> --runs
<dirA> <dirB> [<dirC> ...] --out <dir>` replaces the exact-text reconcile for building reference cells: a cell is
(row label key, value, n-th occurrence); settled by script when two or more readers give it and the value is printed
on the page; `label_dispute` marks a value two readers put under different row labels in the same column. Output
columns: page_id, split, row_label, col_header, value_text, unit_text, readers, agree_n, verbatim, label_dispute,
settled_by. Measured on the 60 pages with three free readers: 4,143 candidate cells, 2,063 settled, 1,048 label
disputes (see `tasks/FABLE_TESTS_2026-11-10.md` section 1). Label unification (11 Nov, Eagle): two readers' labels
are one row when the text is a spelling of the same label (one contains the other, or `SequenceMatcher` ratio >= 0.8,
e.g. a garbled text layer "Oeprecintlon nnd nmortisation") AND the two rows carry at least half the same values, and
the pairing is unique both ways; "CSEL" and "VF" over the same numbers stay a dispute. New column `label_aliases`.

**Settled by printed position (T-177/T-180, 11 Nov 2026, Eagle).** `reality_engine/v2/reference_geom.py`:
`python -m reality_engine.v2.reference_geom --pages <pages.csv> --pdf-pages <dir> --runs <dirA> <dirB> ... --out
<dir>`. `--pdf-pages` holds one single-page PDF per page_id (`D:/RealityEngine/v2/reference_pages/pdf_pages/`, cut
from the source PDF, fetched from Drive where not local). Each reader cell is placed on the page from the PDF word
boxes (sideways pages turned upright; a page-column gutter ends a label): the row holds when the value word sits on a
line whose text left of it spells the row label (or that line joined with a number-less line above/below, for wrapped
labels); the column holds when a header word with a digit (else any header word) is printed above the value and over
it; a chart value holds when the panel title is printed above it and the axis label below it. `settled_by` =
`script+position` (two or more readers, row confirmed), `position` (one reader, row and column confirmed), `script`
(two or more readers, label or value not locatable, e.g. no text layer); otherwise empty with `conflict`
(`row_elsewhere`, `column_elsewhere`, `two_labels_fit_line`, `lone_unlocated`, `lone_column_unlocated`,
`value_not_printed`). A dash or "nil" is an empty cell. `unread_numbers.csv` lists numbers printed in a table column
(numbers on two or more other lines under it) on a labelled line that no reader gave: the recall gap. Why: a text
reader given the text layer in reading order sees a results table column by column, so a blank cell shifts every later
number one row down, and two readers can make the same shift (IHCL p049: "Exceptional items 45271" where that cell is
blank); a vote cannot see it, word positions can. Test: `reality_engine/tests/test_v2_reference_geom.py`.

**Layout input for readers (T-180, 11 Nov 2026, Eagle).** `reality_engine/v2/page_layout.py` renders word boxes as
fixed-width text, one output line per printed line with horizontal position kept (`python -m
reality_engine.v2.page_layout <one-page.pdf>`). `reference_pages transcribe --input layout|layout_image --pdf-pages
<dir>` sends that text (plus the page image for `layout_image`, or the image alone when the page has no text layer)
with a note that a blank in a column is an empty cell. The same renderer takes OCR word boxes, so text-layer and
image-only pages reach a reader the same way.

**Grid output (`--format grid`, 11 Nov 2026, Eagle).** The cell-per-JSON-line reply costs about 35 output tokens a
cell and every free reader stops at its 8,000-token cap: on wide results pages all three readers ended mid-table
(IHCL p049: 82-93 cells of about 230; Bharti p046: about 155 of about 400). `GRID_PROMPT` asks for `TABLE:`, `UNIT:`,
`COLUMNS: h1 | h2 | ...` and one line per printed row (`label | v1 | v2 | ...`, an empty field for a blank cell);
`parse_grid` turns it back into cells (a COLUMNS list one longer than the row, i.e. naming the label column, drops its
first entry; a field without a digit is not a figure; a row whose first field has no letters takes the label printed on
the line above). Trial on p046 and p049, three readers, layout input: 401 and 229 cells each, 2,100-3,800 output
tokens, 14-68 s a page; position-verified 364-365 of 401 and 199-200 of 229; numbers left unread fell from 292 to 90
(p046) and 158 to 23 (p049). Dots ignores the grid instruction under the cell prompt only; under `GRID_PROMPT` it
complies. When two readers place the same printed word, `reference_geom` takes the column name from a reader whose
column check passed. A row label ending in a footnote digit ("EBITDA 1") also matches without it.

**Word boxes for every page (T-182, 11 Nov 2026, Eagle).** `reality_engine/v2/page_words.py` is the single input of
the layout renderer and the position check: `pdf_words(pdf_path, page_no)` turns the PDF text layer upright for any
page of a multi-page PDF (same logic as `reference_geom.page_words`, now a one-line delegate), `ocr_words(ocr_dbs,
doc_key, page_no)` reads `ocr_page` rows preferring `ocr_textrec` over `ocr_rapid` and parses `words_json` into
`(x0, y0, x1, y1, text)` tuples, `quality(words)` returns `("none", reason)` under 20 non-space characters,
`("jumbled", reason)` when the vowel-less 4+ letter word share exceeds 0.3, words longer than 25 characters exceed
0.2, or single-character words exceed 0.6 (thresholds are named constants pending T-175 tuning), else `("ok", "")`,
and `words_for(store_db, doc_key, page_no, ocr_dbs=())` tries the text layer first and falls back to OCR when its
quality is not `ok`. `PageWords(source, words, quality, reason)` carries the verdict; `source` is `"none"` when no
words exist. CLI: `python -m reality_engine.v2.page_words survey --store <db> [--ocr-db <db> ...] --out <csv>` (one
row per document with `text_pages`/`ocr_pages`/`none_pages` from `doc_page.method`, no PDFs opened) and `show
--store <db> --doc-key <k> --page <n>` (prints source, quality and `page_layout.layout_text`). Test:
`reality_engine/tests/test_v2_page_words.py`.

**Scoring reader runs (T-180, 11 Nov 2026, Eagle).** `reality_engine/v2/reader_score.py` (script only, no model call)
turns finished transcription runs into one row per reader+input from the position-settled reference cells:
`python -m reality_engine.v2.reader_score --pages <pages.csv> --pdf-pages <dir> --runs <dir>... [--pair a b]...
--out <xlsx>` writes sheets `readers` (one row per run x split: dev/frozen/all), `by_type` (per doc type) and `pages`
(run, page, rows, verified, recall, unread), plus a CSV of the readers sheet beside the XLSX. Recall = reference cells
(printed words that a position check settles over all runs) on which one of the run's own verified cells sits, divided
by the reference words on the pages the run covered; matching is by word position, so label and header spelling do not
matter and a word counts once (Eagle at merge; the first version matched on label and column text and undercounted); precision_verified = verified cells (settled_by position) divided
by located cells. It also reports pages_done, pages_with_error, rows given, unread numbers, mean seconds per page and
tokens from `transcribe_log.csv`, and pair consistency (share of one run's verified cells that the other also gives) for
each `--pair`.

**Production page reader (T-183, 11 Nov 2026).** `reality_engine/v2/page_reader.py` reads every table page of a store's
documents into `page_read`/`page_cell` (WAL SQLite, created if absent): `select_pages(store_db, symbols=None,
doc_types=("deck","results","annual_report"), limit=None)` picks candidate pages from `doc_page` whose stored text has
at least 8 number tokens (regex, cheap) or whose `method='needs_ocr'` (OCR words may exist), ordered by `doc_key`,
`page`; `is_table_page(words)` is true when at least 2 printed lines carry a label and 2+ numbers or the page has 12+
number words (charts), otherwise the page is logged with status `no_table` with no model call; `read_page(...)` gets
words via `page_words.words_for`, returns `no_words` (reason kept) when quality is not ok and no OCR words exist, builds
layout text, sends the page image too (rendered from the PDF via `raw_store`, as `reference_pages` does) when more than
half the number words sit on lines with no label, calls a FREE reader (refused otherwise) with `GRID_PROMPT` +
`LAYOUT_NOTE` + layout + `>>>`, parses with `parse_grid` (falling back to `_parse_rows`), normalises, and
`settle_page([rows], words)`; a second pass runs when unread >= 5, re-asking once with the distinct unread
`line_text` values plus the layout text, adding rows and re-settling, with `pass=2` recorded. Output:
`page_read(doc_key, page, symbol, doc_type, known_at, word_source, quality, reason, status in
{read,no_table,no_words,error}, reader, input in {layout,layout_image}, passes, seconds, in_tok, out_tok, rows, cells,
verified, unread, error, read_at, PRIMARY KEY(doc_key,page,reader))` and `page_cell(doc_key, page, symbol, known_at,
reader, table_title, row_label, col_header, value_text, unit_text, status ('verified' when settled_by=='position' else
'unverified'), conflict, x0, y0, x1, y1)`. A page already present in `page_read` for that reader is skipped (resume);
`--workers N` (default 3) runs under `concurrent.futures` with one writer (main thread) committing results and a single
20 s retry on a model error before status `error`. CLI:
`python -m reality_engine.v2.page_reader --store <db> [--ocr-db <db> ...] --out <db> [--symbols A,B]
[--doc-types deck,results] [--limit N] [--reader <MODELS name>] [--workers 3]`. Test:
`reality_engine/tests/test_v2_page_reader.py`. Eagle at merge (11 Nov): each page is written and committed as it finishes (one writer), a rerun retries pages
whose status is `error`, three free-model quota refusals in a row (HTTP 429 / usage limit) cancel the remaining pages,
and each invocation writes one `page_reader` row to the run ledger (pages, errors, cells, verified, unread, tokens). After the read-only grade (20261111T085743Z-ec6c70f6): a cancelled page is skipped, a failed second pass keeps the
first pass and records its error, a chart page without an image adds that to the word-source reason, `page_cell`
keeps the reader's table title (`reference_vote.cells_of` and `reference_geom` now carry `table`), and a page needs 4
number tokens (was 8) to reach `is_table_page`.

## 13. Completeness report (T-177, 11 Nov 2026)

`reality_engine/v2/completeness.py` answers, page by page and with no model call, how much of what a page prints
reached the store. It is the check that the precision samples cannot be: T-132 round 11 dropped a whole column on
two-level-header tables while a replay test still passed because only old cells were compared; the page's number
coverage falls at once. Test: `reality_engine/tests/test_v2_completeness.py`.

```bash
python -m reality_engine.v2.completeness run --store <pilot3.db> [<pilot3.db> ...] [--cells <v2 root>] \
    --out <dir> [--symbols A,B] [--types deck,results,annual_report]
python -m reality_engine.v2.completeness gate --prev <page_coverage.csv> --new <page_coverage.csv> [--tolerance 0.02]
python -m reality_engine.v2.completeness calibrate --coverage <page_coverage.csv> \
    --reference <reference_cells.csv> --pages <pages.csv> --split dev
```

`--store` takes one or more stores, opened read-only through `reality_engine.db.readonly.connect_ro`; every query is
per document or over one explicit `doc_key` list. `--cells` is a `<out>/company/<ISIN>.db` cell-store root
(section 10). `run` writes `page_coverage.csv` and the sidecar `completeness.db`, replacing `page_coverage` rows for
the stores in the run; the summary prints pages, unread pages, and median and 10th-percentile `number_coverage` per
doc type.

One row per `(store, doc_key, page)`:

| column | meaning |
|---|---|
| `store, symbol, doc_key, sha256, doc_type, page` | the page's identity |
| `unread` | 1 when there is no `doc_page` row, or its text is empty or under 30 characters; counted, never scored |
| `numbers_printed` | distinct value-numbers in the page text (rules below) |
| `numbers_stored` | of those, how many appear as a value in a stored row that cites this document and page |
| `number_coverage` | `numbers_stored / numbers_printed` (empty when the page prints none) |
| `grid_rows, grid_cols, grid_cells_printed` | printed table grid from the PDF's word boxes: runs of two or more consecutive rows each with two or more figures aligned to the same right-edge column anchors, summed over the page's grids |
| `grid_cells_stored` | v2 `table_cell` rows on the page carrying a value |
| `grid_coverage` | `min(1, grid_cells_stored / grid_cells_printed)`; empty when the PDF is missing, the page has no printed grid, or `--cells` does not cover the document |
| `cells_built` | 1 when the document is present in the `--cells` store |
| `sums_checked, sums_closed` | arithmetic closure of stored rows (rules below) |
| `sources` | the tables whose stored values matched a printed value, `+`-joined |
| `stored_values` | the sorted `\|`-joined stored magnitudes the page was scored against (lets `calibrate` work from the CSV alone) |

**Number words, scale words and exclusions.** A printed figure is a value after number words are converted
("twenty-five" -> 25) and a scale word printed right after it is applied ("25 crore" gives the magnitudes 25 and
250,000,000, because the store keeps either the printed magnitude or base units). Scale words: thousand 1e3,
lakh/lac 1e5, crore/cr 1e7, million/mn 1e6, billion/bn 1e9. A number word counts only when a scale word, `%`,
`percent`, `bps` or a physical unit follows it ("one of the largest" is prose). A printed figure is **not** counted
when it is: a date or period (`31.03.2026`, `31/03/26`, `31 March 2026`, `March 31, 2026`, `Mar-25`, `Mar'24`,
`Q2FY27`, `H1 FY27`, `9M 25-26`, `FY2025-26`, `2025-26`); a year standing alone (1900-2100 integer); a page number
(`Page 7`, `Page 7 of 9`, `7 of 9`, a whole line that is the page's own folio); a note or serial number (a
line-leading 1-2 digit row number before a word: `1. Revenue`, `12) Other`; a number named beside `Note`, `Notes`,
`Sr. No.`, `Sl. No.`, `S. No.`, `Clause`, `Section`, `Annexure`, `Schedule`, `Chapter`); a footnote mark (`(1)`,
`(12)` glued to a word); below 1; or a bare year (the `keep` rule of `reality_engine/scripts/extract_deck_figures.py`,
reused by import). A figure printed twice is one printed value.

**Stored values.** Every table that carries both `doc_key` and `page` is discovered from the schema, not assumed: on
p20/u8/q12 that is `kpi_series`, `fin_quarter_printed`, `fin_annual_line`, `guidance`, `transcript_statement`,
`rating_event`, `related_party_txn` and `concentration`; `*_input` tables are extraction inputs and a statement's prose
`quote` is not a value. A row contributes its numeric value columns, the value divided by its printed scale (the
store keeps base units in `fin_*` and printed magnitude with a `unit`/`scale` pair in `kpi_series`), and numbers
parsed from its own printed token (`raw_token`/`raw_value`/`value_text`). With `--cells`, `table_cell` contributes its
`value`, `value/scale` and `value_text`. Numbers are matched as positive magnitudes rounded to 2 decimals.

**Sums.** For a stored `table_cell` whose row label starts with `Total`, `Sub-total` or `Net` (case-insensitive), the
stored cells above it in the same table and column - down to the previous total-labelled row - are added and compared
with it; checked only when the total and at least two parts are stored, closed when within `max(0.5, 0.5% of total)`
(the reference pages' `sums_ok` tolerance). Sections are not modelled, so a total whose parts span a section heading
or a `Less:` row reads as not closed: the closed share is a lower bound.

**Gate.** Pages are keyed by `(store, doc_key, page)`. Exit 1 and list the page when `number_coverage` or
`grid_coverage` falls by more than `--tolerance` (absolute, default 0.02), when a page goes from scored to `unread`,
or when a page in the previous report is missing from the new one; exit 0 otherwise. Pages only in the new report are
counted and never fail. This is the check that catches a dropped column.

**Calibration.** Joins the coverage CSV to `pages.csv` by `(sha256, page)` for the chosen split only; `frozen` is
refused and never read. Reference recall is the share of the page's reference cells whose normalised value is in
`stored_values`. Prints the per-page table, the Pearson correlation of `number_coverage` against recall (and of
`grid_coverage` where measurable), and the 0.8 disagreement counts: hits = coverage < 0.8 and recall < 0.8, misses =
coverage >= 0.8 and recall < 0.8, false alarms = coverage < 0.8 and recall >= 0.8. Writes
`<coverage dir>/calibration_<split>.csv`.

**Measured 11 Nov 2026.** `run` over p20 with its cell store (`--store D:/RealityEngine/p20/p20new.db --cells
D:/RealityEngine/v2/p20_r10`): 27,717 pages, 1,339 unread (4.8%), 26,378 scored, **219.8 s (7.9 s per 1,000 pages)**.
Median `number_coverage` is 0.000 and p10 0.000 for every doc type, because most scored pages were never extracted:
2,603 of the 26,378 scored pages (9.9%) hold any stored value and only 4,929 pages belong to the 159 documents of the
p20_r10 cell store. Among pages with a stored value: deck 781 pages, median 0.250; results 1,459, median 0.477;
annual report 363, median 0.063. Grid was measurable on 7,263 pages and scored on the 1,303 pages that have both a
printed grid and a cell store (median `grid_coverage` 0.894, p10 0.000). Sums: 2,157 checked, 561 closed (26.0%).
`gate` on that report against itself: 0 regressions, exit 0. The test's dropped-column fixture exits 1.

Calibration on the dev split (19 p20 pages, and 11 q12 pages in a separate run restricted to the five q12 companies
that hold them; the q12 run has no cell store, so its coverage comes from the pilot3 fact tables only):

| run | dev pages in report | scored | number_coverage vs recall (Pearson) | grid_coverage vs recall | hits / misses / false alarms |
|---|---|---|---|---|---|
| p20 + p20_r10 cells | 19 | 18 | 0.993 | 0.955 over 4 pages | 16 / 0 / 1 |
| q12, no cells | 11 | 11 | 1.000 | - | 11 / 0 / 0 |

The one false alarm is `p049` (coverage 0.782, recall 0.959); of the 13 pages with recall 0, 12 also have coverage 0
and the thirteenth (`p046`) has 0.005.
q12's `run` took 40.3 s for 19,421 pages (2.1 s per 1,000). u8 has no cell store, so the ticket's p20 fallback was
used for the live run above; a u8 `run` without `--cells` measured 15,335 pages, 832 unread (5.4%), 14,503 scored in
**164.2 s (10.7 s per 1,000 pages)**. The median number coverage is 0.000 for every doc type on u8 too (the same
never-extracted-page effect); its calibration is not computable because all 13 u8 reference pages are in the frozen
split.

Limitations. `fin_annual_line` rows read from `ar_facts.db` carry that store's document id, not the pilot3
`doc_key` (`doc_alias` is empty in p20 and u8), so only 83 of its 233 distinct document keys join and annual-report
coverage is a floor. A page whose PDF is missing on disk (147 of the 542 deck/results/annual-report documents of p20)
has empty grid columns, never zero. Prose figures count as printed, so coverage sits below a table-only recall
measurement. Cross-source XBRL agreement (design item 4 in `tasks/FABLE_TESTS_2026-11-10.md`) is not part of this
report.

Test runtime: `python -m pytest -p no:cacheprovider reality_engine/tests/test_v2_completeness.py -q` -> 4 passed in
0.78 s. The module overrides the builtin `tmp_path` fixture (a plainly created directory under
`tempfile.gettempdir()`), because this sandbox's `.tmp` holds the ACL-locked `pytest-of-SYSTEM` and a `mkdtemp`
directory there is created with an ACL that denies the test's own writes. Typecheck: basedpyright 0 errors on the
module and its test.

