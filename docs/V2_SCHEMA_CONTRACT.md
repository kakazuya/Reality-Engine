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
- `dimension`: `key=value` pairs joined by `;` in a fixed order (`geography`, `segment`, `product`, `measure`,
  `currency`), empty for the whole company.
- `basis`: standalone, consolidated, segment, na. `definition`: reported, adjusted, company_stated, plus metric
  variants (incl_trainees, excl_trainees, constant_currency).
- `period_id`: `start/end` (or `/end` for a point). Fiscal labels are derived from dates.

## 6. Order of work after the OK

1. T-132 prototype (Wolf) on three pilot20 decks and one results PDF: `table_cell` rows, bbox, base units.
   (Shipped as `reality_engine/v2/table_cells.py` and `build_cells.py`, section 10.)
2. T-134 period engine and T-135 calc catalog in parallel (two code workers is the cap).
3. T-133 label families for the pilot20 sectors, Opus approval per family.
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

- **a. Header stack.** A table's header is every row between the previous table block on the page (or the page top)
  and this block. A period heading centered over a group of columns ("Quarter ended", "Full Year Ended") is assigned
  to every column of its group: the columns are partitioned into consecutive blocks whose mean centre matches each
  heading (so a heading over five date columns reaches all five), and a date row assigns each date to its column.
  `col_header` joins the rows top to bottom with `' > '`, e.g. `'Quarter ended > 30.09.2026'`.
- **b. Section labels.** A section label ("Expenses") ends where a new numbered row group starts: the first token is
  a row number (`2`, `II`, `IV`). Parenthesised sub-labels (`(a)`, `(b)`) stay inside the section. The printed
  row-number column is dropped from `row_label` and from the cells.
- **c. Tokens.** Figures split by the text layer merge (`2, 028` -> `2,028`, `1 ,234.5`, a lost thousands separator
  `5 088`); `(1,234.5)` and `-1,234.5` are negative; `-` / an en dash is value NULL with `value_text` kept; `12.3%`
  is percent.
- **d. Unit and scale.** The unit is read from the table's header rows, else the page's top 15%: `Rs. in crore`,
  `₹ in Crores`, `(Rs in Lakhs)`, `INR Mn`, `Rs. Million`, `(Amount in ₹ crore)`. Scale crore 1e7, lakh 1e5,
  million/mn 1e6, billion/bn 1e9, thousand 1e3; percent stays in percent points (`unit_text='%'`, `scale=1`); no
  unit found means `value` and `scale` are NULL, never guessed.
- **e. Period.** `period_id` comes from the column header and the document date through `periods.period_row`:
  `30.09.2026` / `30-Sep-26` / `Sep 30, 2026` under `Quarter ended` -> that quarter, `Half year ended` -> H1/H2,
  `Nine months ended` -> 9M, `Year ended` -> FY, `As at 30.09.2026` -> POINT; `Q2 FY27` / `H1 FY27` / `FY26`
  labels directly. A wrapped date row ("June" over "30,2025") and a bare year under `Year ended` resolve; an
  unresolved header leaves `period_id` NULL.
- **f. Basis.** `standalone` / `consolidated` from the page title text (top 20%) when printed, else NULL.
- **g. Infographic.** A page with numbers scattered and no two-row aligned block, or a block where fewer than half
  the data rows carry a label, gives no cells and is counted as skipped.
- **h. Box.** `bbox` is the merged token's `x0,y0,x1,y1`; `method` is `'text_layer'`.

Measured 9 Nov 2026 with `python -m reality_engine.v2.build_cells --store D:/RealityEngine/p20/p20new.db
--out .tmp/v2p20` (all 76 decks and 113 results filed since 2025-04-01; 30 further documents were skipped as
duplicate sha256):

| doc type | documents | pages | skipped (no text / no table) | cells | period_id | scale | no header | seconds |
|---|---|---|---|---|---|---|---|---|
| deck | 76 | 3,124 | 2,573 (79 / 2,494) | 19,378 | 42.6% | 64.4% | 12.5% | 45.7 |
| results | 113 | 1,805 | 835 (33 / 802) | 74,897 | 46.8% | 55.5% | 17.7% | 24.5 |
| total | 189 | 4,929 | 3,408 (112 / 3,296) | 94,275 | 45.9% | 57.3% | 16.6% | 70.2 |

The Havells information update p5 still gives 36 segment-revenue cells (9 rows x 4 columns) and the Asian Paints
results p5 gives the `Revenue from operations` row with a Q2FY27 cell. Tests:
`python -m pytest -q reality_engine/tests/test_v2_table_cells.py` (8 tests; the two real-PDF smoke tests skip when
the files are absent).

