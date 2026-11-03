# T-048 · One-company gap loop: what 300 answers prove, and the schema that takes the model out of answer time

**For Shivam · 3 Nov 2026 · from the three sandbox runs of 2 Nov** (KEC, BAJFINANCE, HINDALCO, 100 questions each).
Read-only review of the finished runs; nothing in `D:\RealityEngine\sandbox` was modified.

Companion files, same folder: `T048_SCHEMA_TABLES_2026-11-03.xlsx` (19 proposed tables, full column specs, rank) and `T048_QUESTION_COVERAGE_2026-11-03.xlsx` (300 rows, one per question: status, method, table that would serve it, gap class).

**Headline.** The loop answered 251 of 300 questions (83.7%). Of those 251, 241 quote a store row or a document page (222 a table plus rowid, 19 a page) and 10 cite nothing. What failed was not the model: of the 49 failures, 44 are a store, a fetch, a copy or a check defect that a table fixes, and only 5 are holes in the world (the company does not disclose the number, or the question is an assumption). The proposed 19-table schema turns 295 of 300 into one query or one formula with no model at answer time, at a one-time extraction cost of at most $64 across the three companies (upper-bound sum of the per-table estimates).

---

## 0. What was read (provenance)

| Source | Volume read | Used for |
|---|---:|---|
| `kec_loop/questions/KEC_QUESTIONS.jsonl` | 100 questions, 7 kinds | the bank and its kinds |
| `bajfinance_loop/questions/BAJFINANCE_QUESTIONS.jsonl` | 100 questions | same bank, NBFC wording |
| `hindalco_loop/questions/HINDALCO_QUESTIONS.jsonl` | 100 questions | same bank, metals wording |
| `kec.db` / `bajfinance.db` / `hindalco.db` `answers` | 175 / 163 / 255 rows; newest per qid = 251 answered of 300 | status, numbers, citations, gaps |
| `reports/round_*.xlsx` | KEC up to round 3, BAJ round 3, HIND round 5 | the manager-facing sheet (6 columns) |
| `state/ledger.jsonl` | 627,464 / 415,018 / 586,273 bytes | sessions, models, outcomes |
| `state/*escalations*.jsonl` | 10 / 8 / 14 escalations | what the checks rejected |
| `state/transcripts/*.jsonl` | 30 / 109 / 143 files, 7.4 / 24.8 / 34.9 MB (sampled, never printed whole) | what each session actually ran |
| `kec_loop/reports/KEC_EXTRACTION_PATTERNS_v2.xlsx` + `.xlsx` | 84 pattern rows, 101 per-question rows, 12 gap rows | KEC method per qid, which pattern worked |
| `reality_engine/gap_loop/*.py` | `checks.py` 424 lines, `loop.py` 833, `store.py` 234, `prepare.py` 422 | the checks and the store copy |
| `docs/DEVELOPER_GUIDE.md` §N | lines 483-518 | the loop as documented |
| `tasks/STATE.md` | T-048 paragraph | the run record, cross-checked against the stores |
| `tasks/DATA_INVENTORY.md` | generated 2026-11-02 08:35 IST | what the global corpus holds: `ar_facts.db` 32,981,115 rows, `bse_announcements.ann` 1,947,087, `cc_items` 720,692 |
| `D:\RealityEngine\raw` | folder inventory by hand | what raw really holds for these three |

**Drift check.** The brief names `docs/DEVELOPER_GUIDE.md` "section N"; it exists as `### N. One-company gap loop (T-048)` at line 483, and its text matches the code. `tasks/STATE.md` gives the same final counts as the stores (89 / 83 / 79). No drift found between the pack, the guide and the sandboxes.

Every count in this report is computed, not quoted: `.tmp/probe.py` indexes the three sandboxes, `.tmp/classify.py` parses every `answers.answer_json`, `.tmp/build_workbooks.py` builds the two companion workbooks, and the intermediate JSON sits in `.tmp/probe/`. The commands are at the end. Where a number comes from a document instead, the sentence names the file.

---

## A. Findings: what got answered, and how

### A1. The scoreboard

| Company | Answered | Partial | Unverified | Not found | Total | Note |
|---|---:|---:|---:|---:|---:|---|
| KEC | 89 | 4 | 5 | 2 | 100 | 3 rounds; 8 rows were accepted by `--recheck`, not by a new answer |
| BAJFINANCE | 83 | 11 | 2 | 4 | 100 | stopped after round 3 on your order; not a converged run |
| HINDALCO | 79 | 7 | 9 | 5 | 100 | 5 rounds; one stray row (see B3.1) |
| **all three** | **251** | **22** | **16** | **11** | **300** | 83.7% pass the loop's own checks |

Source: newest `answers` row per qid in each `<company>.db`. The three banks are the same instrument: 7 kinds, same difficulty curve, company-specific nouns. That is what makes 89 / 83 / 79 comparable.

### A2. The seven kinds, and pass rate per kind

| Kind | Questions | Answered | Pass | Per company (answered/total) |
|---|---:|---:|---:|---|
| lookup | 102 | 91 | 89% | KEC 27/31 / BAJFINANCE 33/36 / HINDALCO 31/35 |
| derived | 78 | 76 | 97% | KEC 26/26 / BAJFINANCE 27/28 / HINDALCO 23/24 |
| text | 46 | 35 | 76% | KEC 14/16 / BAJFINANCE 8/12 / HINDALCO 13/18 |
| guidance | 18 | 10 | 56% | KEC 6/6 / BAJFINANCE 3/6 / HINDALCO 1/6 |
| event | 16 | 9 | 56% | KEC 5/7 / BAJFINANCE 2/5 / HINDALCO 2/4 |
| ripple | 15 | 9 | 60% | KEC 3/5 / BAJFINANCE 2/5 / HINDALCO 4/5 |
| market | 25 | 21 | 84% | KEC 8/9 / BAJFINANCE 8/8 / HINDALCO 5/8 |
| **total** | **300** | **251** | **84%** | 89 / 83 / 79 |

Read it as a data map, not a model score: `derived` (76/78) and `lookup` (91/102) are where a table already existed; `guidance` (10/18), `event` (9/16), `ripple` (9/15) and `text` (35/46) are where the corpus, not the model, ran out.

### A3. How the answers were actually obtained

| Method, from the stored answer's own citation | Rows | Share | Answered | Partial | Unverified | Not found |
|---|---:|---:|---:|---:|---:|---:|
| SQL over a copied store (`numbers[].table` + `rowid`) | 253 | 84% | 222 | 14 | 14 | 3 |
| page read (`doc_key` + `page`, no table) | 21 | 7% | 19 | 0 | 2 | 0 |
| no citation stored (prose only) | 26 | 9% | 10 | 8 | 0 | 8 |

Method is derived from `answers.answer_json`: a `numbers[]` entry with a `table` and `rowid` counts as SQL; a `doc_key`+`page` only counts as a page read; no numbers at all counts as none. Across the 301 stored latest rows there are 852 number citations, mean 2.34 per answer: **784 cite a table row, 68 cite a page, and only 315 carry a verbatim quote** (source: `.tmp/probe` extraction of all `answer_json`). Two consequences, both defects: 37% of numbers cannot be re-checked against a quote, and **10 answers counted as answered cite nothing at all**.

### A4. What the four working methods were

1. **`ar_facts` row lookup** — 70 answers cite it alone, 152 citations in total. The best shape is a reported line plus a page: `KEC003`, "What was KEC's consolidated EBITDA and EBITDA margin for FY26?" → 1,659 crore (rowid 1,048, page 158) over 23,505.54 revenue (rowid 1,231), margin 7.06%.
2. **`deck_figures` row lookup** — 68 answers cite it alone, 207 citations. It is the densest store per row because a deck prints the KPI the company wants read: `KEC005-007`, `BAJ021-032`, `HIND021-041` are all deck rows.
3. **`results_quarterly` sum / difference** — 174 citations, 29 answers on it alone. `HINDALCO007`, "What was Hindalco's standalone (India business) revenue for FY26?" → 112,552 = 24,264 + 24,780 + 29,264 + 34,244, four XBRL rows. `HINDALCO006`, Q1 FY27 PAT vs Q1 FY26 → 7,013 vs 4,004, +75.1% (rowid 61). This is the method the schema should make automatic, because it needs no judgement at all.
4. **Page read + quote** — 21 answers. `doc_text` holds the page; the answer keeps the quote so a human can check it. `KEC060-065` (guidance vs delivered) and `KEC045-048` (business outlook) are all this shape.
5. **Hand-written formula** — only where someone thought to register one: 8 formulas in `kec.db`, 5 in `bajfinance.db`, 11 in `hindalco.db`, every one invented for that session (`fy26_diluted_eps_inr`, `nii_to_average_auf_fy26`, `india_share_of_consolidated_ebitda_fy26`, …). A formula that answers a question is exactly a row the schema should own.

### A5. Where it plateaued, and why that is a data statement

The 49 non-answered rows split by the loop's own gap type: `absent` 21, `unverified` 16, `text_missing` 7, `needs_formula` 3, `not_extracted` 2.

Re-classified by root cause in this review (the column `gap class` in the coverage workbook): **fetch gap 25**, **extract gap 13**, **copy defect 4**, **check defect 2**, **not disclosed 3**, **judgement 2**. Only the last two are real holes in the world; the first four are holes in our pipeline.

### A6. Point-in-time behaviour was correct where it was tested

Seven questions ask a dated snapshot ("As of 1 July 2026, what was the latest order book KEC had reported?" `KEC095`; same shape at `BAJ095`, `BAJ096`, `HIND094`, `HIND095`, `HIND100`, `KEC096`). Six passed, one partial. The answers cite the filing date they used (`known_at`), which is the behaviour the schema must preserve. The single PIT failure was not logic: `BAJ096`'s latest Q3 FY26 PAT was not in the copy.

### A7. Cost and throughput

`tasks/STATE.md` reports KEC Haiku $3.85 over 129 attempts, Sonnet $1.11 over 7, and BAJ/HIND at $2.50+$1.37 and $3.57+$0.96+$0.25. The sandbox ledger stores model and outcome per attempt, not tokens, so those figures cannot be recomputed here; they are the run owner's numbers, not mine. What is recomputable: 593 stored answer rows were written for 300 questions, i.e. the loop re-answered about twice on average, and 13 of the 32 escalations were usage-limit replies rather than answer defects.

---

## B. Flaws

### B1. The data stores

**B1.1 The shareholding copy loses every BAJFINANCE and HINDALCO row — and the data is not missing.** `shp_index` in `equity_intelligence.db` holds 23 BAJFINANCE rows (2021-09-30 to 2026-09-30) and 20 HINDALCO rows (2021-09-30 to 2026-06-30). Both sandbox copies hold 0, while KEC's copy holds all 22. Cause: the copy filters on the ISINs declared in `company.py`, but `shp_index` stores the ISIN of the filing year — BAJFINANCE `INE296A01016` (declared: `INE296A01032`, `INE296A01024`), HINDALCO `IN9038A01010` (declared: `INE038A01020`, and the stored value is malformed). `prepare.store_copies` (`reality_engine/gap_loop/prepare.py:75-78`) has no `symbol_isin_history` expansion. This alone turned six questions into `absent`: `BAJ088`, `BAJ089`, `BAJ090`, `HIND086`, `HIND087`, `HIND088` ("What was Hindalco's promoter holding at the end of June 2026?").

**B1.2 `shp_index` has no holder categories.** The table is `promoter_pct, public_pct` only. Even with the copy fixed, "What was the holding of mutual funds and foreign portfolio investors in KEC at the end of June 2026?" (`KEC090`) needs the SHP XBRL detail, which is on disk but never loaded (`raw/nse_shp_xbrl_pilot`, 563 files). The loop answered it `not_found`/`absent` with the reason "the shp_index copy has only promoter and public totals" — correct about the table, wrong about the data.

**B1.3 The quarterly store is a one-year window for two of the three companies.** `results_quarterly` holds KEC 12 rows, BAJ 12, HIND 61 (period_end 2025-03-31 to 2026-06-30 for KEC/BAJ; HIND from 2018-12-31). So "How did KEC's quarterly EBITDA margin trend from Q1 FY25 to Q1 FY27?" (`KEC098`) and its BAJ twin (`BAJ098`) cannot be a trend: the FY25 quarters are not in the file. They still passed, because the answer used the four FY26 quarters only — a pass that hides a gap.

**B1.4 `ar_facts` for a bank is a notes bag, not a P&L.** BAJ has 22,186 rows (2,944 for FY26) but a search for margin items returns "Advance received towards ECB variation margin", "Government securities kept as margin for securities segment" — and no net interest margin, no diluted EPS, no ROE. That is why "What net interest margin did Bajaj Finance report for FY26?" (`BAJ033`) went `not_found` while `deck_figures` holds 2,148 FY26 deck rows. The extraction prompt is line-item-hunting; it needs a KPI list per sector.

**B1.5 `concall_items` is empty exactly where the transcript questions are.** KEC 0, BAJ 526, HIND 1518 rows. KEC has 53 transcript documents and 898 pages, so its text questions had to fall back to FTS over `doc_text` (`KEC057` says so in its gap detail).

**B1.6 The fact layer is empty, so every answer re-derives.** `facts` holds 171 / 6 / 1 rows; `row_facts` 0 / 0 / 93 (KEC's copy has no `row_facts` table at all). There is no shared formula registry either: 8 / 5 / 11 formulas, all session-local.

**B1.7 Page coverage is complete; the calendar is not.** `doc_text` holds 6,267 / 6,450 / 6,782 pages against 6,264 / 6,450 / 6,782 recorded in `docs.pages`, and **no registered document has zero text** in any of the three stores. So no page of a held PDF is missing. But the newest `doc_text.known_at` is **2026-09-14 for KEC, 2024-03-30 for BAJFINANCE, 2024-03-29 for HINDALCO**. The sandbox raw copy itself stops in March 2024 for the two (B2.1): `raw/pilot60_history/BAJFINANCE` and `.../HINDALCO` contain no 2025-26 annual report at all. Every `text_missing` gap is this one fact.

### B2. The raw documents

**B2.1 The raw folder is a 2024 snapshot for two of the three companies.** `raw/pilot60_history/KEC` = 386 PDFs (annual_report 5, material_filing 276, investor_presentation 39, quarterly_results 46, concall_transcript 11, results_press_release 8); BAJFINANCE = 422 (5 / 326 / 24 / 45 / 11 / 0); HINDALCO = 556 (6 / 451 / 48 / 34 / 3 / 10). The global corpus is far larger (`ar_facts.db` 32,981,115 rows; `ann` 1,947,087 rows), so this is a copy choice, not a data shortage. Consequence: `BAJ039` ("What reasons did Bajaj Finance give for the movement in its net interest margin in FY26?"), `BAJ048`, `HIND029`, `HIND060` and the whole `HINDALCO` guidance block are unanswerable in this sandbox while the PDFs exist in the main library.

**B2.2 Attachment bodies are not carried.** The registry has the announcement headline, not the attached PDF. `BAJ074` ("Did Bajaj Finance announce any fund raise (NCDs, commercial paper or equity) between July and October 2026? Give amount and date.") fails because "amounts sit in the allotment attachments"; `KEC074`'s ESG grade is in attachment `bcb4f70f-…`; `KEC099`, `BAJ077`, `HIND073` (AGM voting results) and `HIND066/068/070` (deals and management changes) are the same shape.

**B2.3 Announcements stop before the questions do.** KEC 1,083 rows end 2026-09-28T17:25:24.7, BAJ 804 end 2026-09-28T19:17:49.237, HIND 1,209 end 2026-10-16T16:31:19.677. KEC037 asks for 10 October 2026 and BAJ073 for the 1 October 2026 board outcome; both are after the cut-off. HINDALCO's copy reaches 16 Oct, which is why its event block did better.

**B2.4 Raw file names carry no type and no date.** All three folders are UUID/sha-named PDFs (`017eaa1b-3989-4f81-a03f-1a0dd09f1952.pdf`). `docs` is therefore the only index; if a PDF is not registered it is invisible, and if it is registered with a NULL `filing_date` it is invisible to a PIT filter. BAJ has 64 undated rows, HIND 103, KEC 71.

**B2.5 The series we do hold were never copied.** `raw/nse_shp_xbrl_pilot` (563 `.xml.gz` SHP filings) and `raw/commodity_series` (325 files: `commodity_series.csv`, RBI reference-rate pages) are exactly what `KEC078/090`, `HIND076/077/079/086-088` and `BAJ088-090` need. The sandbox has neither.

### B3. The loop code and the checks

**B3.1 A row for a qid that is not in the bank was stored.** `HINDALCO029b`, round 2, `not_found`, empty answer — 101 qids in a 100-question bank. Cause is one loop: `loop.drain` writes **every row of the payload** (`reality_engine/gap_loop/loop.py:565-567`), while `accept_answers` only validates the rows it iterates from `unit.items` (`loop.py:200-217`); an extra row is neither rejected nor dropped. One guard — `if answer.get('qid') in {q['id'] for q in unit.items}` — closes it. It also inflates HINDALCO's `not_found` count by one and makes the report 101 rows wide. **Fixed in T-051 (3 Nov):** `accept_answers` now validates every payload row against the unit and the company's bank (`loop.bank_questions`) and records an unknown qid in the `invalid` map, so the report fails and `drain` stores nothing; a bank qid outside the unit is checked against its own booked `as_of`. The stored `HINDALCO029b` row in `D:\RealityEngine\sandbox\hindalco_loop\hindalco.db` is the controller's delete.

**B3.2 The check's `known_at` rule assumes one page, one date.** `checks.check_known_at` compares the answer's `known_at` with the cited page's filing date. Five KEC escalations read "proposal line 1: known_at: not the cited page's filing date" (`state/escalations_run1.jsonl`), because a number can legitimately sit in a later restatement. The rule should accept any filing date at or before the as-of date, and prefer the earliest.

**B3.3 The quote-substring rule breaks on real PDFs.** `check_number` requires the number to appear in the quote with its unit. Transcript pages arrive with newlines inside numbers and curly apostrophes; 5 KEC escalations are "number: does not occur in the quote with that unit", and 9 HIND escalations are "page not in `doc_text`" when the page was in the PDF under a different `doc_key` (`state/escalations_rowcite_defect_2026-11-02.jsonl`). KEC's own pattern workbook records the fix (`raw_span` normalisation).

**B3.4 The unit vocabulary was too narrow, and still is at the edges.** Sixteen rows are `unverified` with reasons like "unit: 'INR crores' is not a known unit", "unit: 'US$ million' is not a known unit", "unit: 'tonnes per annum' is not a known unit", and "unit: 'pct' does not suit 'Opex to net total income, Q1 FY27' (a money measure)". The USD/per-tonne/rate fix landed mid-run; the scale problem (a crore value, a lakh-crore value and an absolute rupee value in the same column) did not, which is why the schema below fixes `unit` **and** `scale` on every row.

**B3.5 A usage-limit reply was treated as a failed attempt.** 8 BAJ and 5 HIND escalations are the literal text "You've hit your 5-hour limit · resets 10:50pm (Asia/Kolkata)". Fixed after the run (`session_runner.LIMIT_PATTERN` now sleeps and retries), but the escalations they caused are still in the record and still counted as failures.

**B3.6 "Answered" is partly a measure of check calibration.** Thirty-five stored rows carry `rechecked: true` (eight of them KEC's: KEC032-036, KEC058, KEC077, KEC079), and `--recheck` re-runs the checks with no model call. A row whose status moves there was not answered better; the check moved. KEC's final 89 therefore includes rows accepted by a check change, which is why any 95% target has to be measured by a read grade — the loop already keeps `round1_sonnet_grades.json` (94 rows: 74 right, 19 partly, 1 wrong, `tasks/STATE.md`) — and not by the checks alone.

**B3.7 The manager-facing report throws the reason away.** `reports/round_N.xlsx` has six columns (`qid, status, answer, sources, gap, tier`); the useful `gap_detail` lives only inside `answer_json` in the db. The report is what a human reads first, and it is the least informative artefact of the run.

**B3.8 An answered row can carry no citation.** HINDALCO001 and HINDALCO002 store `sources: []`; 10 answered rows cite nothing. The accept path counts a row answered on its status field, not on whether a reader could find the number.

### B4. The answers themselves

**B4.1 "Absent" was used where the data was held or computable — the exact failure the scope rule forbids.** Twenty-one rows were marked `absent`; this review reclassifies 25 of the 49 failures as fetch gaps, 13 as extract gaps and 4 as copy defects, which leaves 5 genuinely unanswerable (section D). Four of the `absent` verdicts are wrong on their own evidence: `BAJ033` (NIM; 2,148 FY26 deck rows exist, none labelled NIM), `BAJ100` (book value per share; net worth and share count are both in the store), `HIND086` and `BAJ088` (promoter holding; 20 and 23 rows exist under a stale ISIN), `KEC078` (aluminium and copper prices; 325 series files are on disk).

**B4.2 Formula questions were marked partial on a definition nobody had written down.** `KEC009` ("What was KEC's diluted EPS for FY26?") answered "the quarterly sum is consistent with FY26 consolidated PAT of Rs 605.60 crore over about 26.62 crore shares … but that is an approximation" and was kept `partial`. `HIND009` did the same. The right move is a formula row with an explicit definition and its inputs, which is `T03`.

**B4.3 A ratio answer is not checked as arithmetic.** `KEC003` cites EBITDA 1,659 and revenue 23,505.54 and states 7.1%. The check validates each number against its row; nothing validates 1,659/23,505.54 = 7.06%. A wrong margin over right inputs would pass.

**B4.4 Units and scales are mixed inside one answer.** `KEC005` stores `50,235,400,000` with unit `inr`; `KEC001` stores `23,505.54` with unit `inr_cr`. Both are readable by a human and neither is safe for a downstream formula. A single scale column per row removes the class of error that produced "unit: 'inr_lakh_cr' is not a known unit".

**B4.5 The formula that produced an answer is not stored with the answer.** `HINDALCO020` ("What share of Hindalco's FY26 consolidated EBITDA came from the India business, and what share from Novelis?") cites two deck rowids and a `formulas` entry; the answer names neither the formula id nor its inputs, so the number cannot be replayed. Same for `KEC100`'s ROCE attempt.

**B4.6 One "answered" row is a stale-restatement trap.** `KEC047` ("What did KEC say about its renewables (solar EPC) business strategy in FY26?") was flagged in the round-1 read grade for adding FY26 renewables revenue as if it were Q4. The loop's own read grade caught it (`tasks/STATE.md`); the checks did not, and the final status is `answered`.

---

## C. Schema: extract once, answer by query

### C1. Five rules

1. **One row per (entity, metric, period, basis, dimension).** No prose, no sentence, no answer-shaped row.
2. **Every row carries its own provenance:** `source_doc_key` + `page` for a document, or `source_table` + `source_rowid` for a store; `known_at` from the *filing record*; `unit` and `scale`; `period_start/period_end`; `basis`.
3. **Reported and derived never mix.** `is_reported=1` for a number printed in a filing; `is_derived=1` plus `input_refs` and `formula_id` for a computed one. A derived row is reproducible from the registry alone.
4. **The registry is the index.** `docs` (doc_key, type, filing_date, pages, sha256) and `doc_page` are built first; nothing else may cite a PDF that has no registry row, and no registry row may have a NULL filing date.
5. **An empty table means not extracted.** A NOT IN DATA verdict requires the row to be absent from the table *and* the phrase to be absent from `doc_page` — both, as the scope rule says.

### C2. Ranked list (questions unlocked / effort)

Effort points: 1 = 1-3 engineer-days, 2 = 3-10, 4 = 10+. Score = questions unlocked / points. The full column specs are in `T048_SCHEMA_TABLES_2026-11-03.xlsx`.

| Rank | Table | Unlocks | Effort | Score | Model cost |
|---:|---|---:|---|---:|---|
| 1 | `ratio_panel` | 55 | S (1-3 days) | 55.0 | $0 |
| 2 | `kpi_series` | 49 | M (3-10 days) | 24.5 | one-time label mapping: ~2,000 distinct labels x 3 companies, ~$0.002 each -> <=$15 |
| 3 | `transcript_statement` | 42 | M (3-10 days) | 21.0 | 1,037 pages x ~$0.005 -> ~$5 one-time for all three |
| 4 | `price_delivery` | 21 | S (1-3 days) | 21.0 | $0 |
| 5 | `fin_quarter_xbrl` | 18 | S (1-3 days) | 18.0 | $0 |
| 6 | `guidance_actual` | 18 | S (1-3 days) | 18.0 | $0 after T11 (the model cost is T11's) |
| 7 | `fin_annual_line` | 25 | M (3-10 days) | 12.5 | $0 for the locator; ~$0.005/page for unmatched pages, ~1,900 pages/company -> <=$5/company |
| 8 | `event_ledger` | 20 | M (3-10 days) | 10.0 | ~2,100 attachments/company x $0.002 -> <=$4/company |
| 9 | `shp_category` | 9 | S (1-3 days) | 9.0 | $0 |
| 10 | `segment_series` | 15 | M (3-10 days) | 7.5 | $0 for text-layer grids; ~$0.005/page for image decks, ~40 pages/company -> <=$1/company |
| 11 | `commodity_price` | 5 | S (1-3 days) | 5.0 | $0 |
| 12 | `rating_esg` | 5 | S (1-3 days) | 5.0 | <=$1/company |
| 13 | `corp_action` | 4 | S (1-3 days) | 4.0 | $0 for headlines; <=$2/company if attachments must be read |
| 14 | `macro_series` | 6 | M (3-10 days) | 3.0 | $0 |
| 15 | `valuation_daily` | 3 | S (1-3 days) | 3.0 | $0 |
| 16 | `subsidiary_pnl` | 3 | M (3-10 days) | 1.5 | $0 |
| 17 | `cost_structure` | 2 | M (3-10 days) | 1.0 | ~60 pages x $0.005 -> <=$1/company |
| E1 | `share_capital` | 0 | S (1-3 days) | 0.0 | $0 |
| E2 | `doc_page` | 0 | S (1-3 days) | 0.0 | $0 |

The top five unlock 192 of 300 (64%). `share_capital` and `doc_page` are enablers: no question is assigned to them because they are the inputs to the ratio and text tables, and without them those tables are wrong.

### C3. The tables, one by one

#### 1. `ratio_panel` — 55 questions, effort S (1-3 days), $0

*What it holds.* Every derived measure, per period, with the input row ids it was computed from. Answers a ratio with a query, not a formula invented per session.

*Columns.* isin, fiscal_period, period_start, period_end, basis, metric (ebitda_margin, pat_margin, ebit_margin, roe, roce, roa, debt_to_equity, net_debt_to_ebitda, interest_coverage, bvps, eps, pe, pb, ev_to_ebitda, payout, receivable_days, inventory_days, payable_days, nwc_days, book_to_bill, order_cover_years, aum_growth_pct, credit_cost_bps, cost_of_funds_bps), value NUMERIC, unit (pct|bps|days|inr_per_share|ratio|x), period_type (FY|Q), input_refs TEXT (T01/T02 row ids), formula_id -> formula registry, known_at (max of the inputs' known_at), known_at_source, is_derived=1

*Point in time.* known_at = the later of the inputs' filing dates, so a ratio never quotes a quarter it could not know

*Filled from.* T01 + T02 + T04 + T07; the three sandboxes already hold 8/5/11 hand-written formulas, which is the seed of the registry

*Extraction and cost.* formula registry (closed set, versioned) + Python evaluation at load, no model. $0

*Unlocks.* BAJFINANCE009, BAJFINANCE013, BAJFINANCE014, BAJFINANCE015, BAJFINANCE016, BAJFINANCE018, BAJFINANCE019, BAJFINANCE020, BAJFINANCE028, BAJFINANCE029, BAJFINANCE032, BAJFINANCE037, BAJFINANCE038, BAJFINANCE046, BAJFINANCE053, BAJFINANCE054, BAJFINANCE059, BAJFINANCE091, BAJFINANCE092, BAJFINANCE093, BAJFINANCE098, BAJFINANCE100, HINDALCO009, HINDALCO013, HINDALCO014, HINDALCO015, HINDALCO016, HINDALCO018, HINDALCO019, HINDALCO034, HINDALCO042, HINDALCO049, HINDALCO053, HINDALCO054, HINDALCO089, HINDALCO090, HINDALCO091, HINDALCO096, HINDALCO098, KEC009, KEC013, KEC014, KEC015, KEC016, KEC019, KEC020, KEC027, KEC029, KEC030, KEC051, KEC052, KEC053, KEC054, KEC098, KEC100

*Defect it closes.* Book value/share, ROCE, EPS, P/E, EV/EBITDA and payout were re-derived per session; two of them failed on a missing share count.

#### 2. `kpi_series` — 49 questions, effort M (3-10 days), one-time label mapping: ~2,000 distinct labels x 3 companies, ~$0.002 each -> <=$15

*What it holds.* Company-reported operating KPIs in long form: one row per (metric, dimension, period, basis). The single biggest unlock.

*Columns.* isin, metric (order_book, order_intake, order_intake_l1, aum, new_loans, customer_franchise, customers_added, deposits, gnpa_pct, nnpa_pct, pcr_stage3, credit_cost_bps, nim_pct, cost_of_funds_pct, crar_pct, tier1_pct, net_debt, working_capital_days, capex, shipments_kt, production_kt, ebitda_per_tonne, cost_of_production, ebitda_upstream, ebitda_downstream, ebitda_copper, ebitda_novelis_usd, capacity, utilisation), dimension TEXT (total|T&D|civil|transportation|renewables|cables|oil_gas|india|novelis|aluminium_upstream|copper|mortgage|consumer|rural|sme|commercial|auto|gold|geography), value NUMERIC, unit (inr_cr|usd_mn|tonnes|kt|count|pct|days|inr_per_tonne|usd_per_tonne|bps), scale (1|1e7), period_type (FY|Q|M), fiscal_period, as_of_date, basis, doc_key, page, quote, known_at, known_at_source (filing/deck date), is_reported INT, `source_type` (deck|results|press_release|transcript|annual_report|announcement, added 3 Nov 2026 so a reader can keep a call's number apart from the deck's), `confidence` / `conf_rank` (table_row > table_chart > sentence > sentence_default; a transcript row sits two ranks lower). 31 March is labelled FY (the fiscal year end), an explicit "Q4 FY26" header stays a quarter (3 Nov 2026).

*Point in time.* known_at = the deck/press-release/transcript filing date; deck_figures already carries known_at per sha256

*Filled from.* deck_figures (KEC 9,849 / BAJ 74,074 / HIND 49,033 rows; BAJ FY26 alone 2,148), results_press_release, quarterly_results, concall_items (KEC 0 / BAJ 526 / HIND 1,518)

*Extraction and cost.* SQL copy + a metric-label lexicon (deck_figures has ~thousands of free-text labels) mapped once; model read only for labels the lexicon misses. one-time label mapping: ~2,000 distinct labels x 3 companies, ~$0.002 each -> <=$15

*Unlocks.* BAJFINANCE021, BAJFINANCE022, BAJFINANCE023, BAJFINANCE024, BAJFINANCE025, BAJFINANCE026, BAJFINANCE033, BAJFINANCE034, BAJFINANCE035, BAJFINANCE036, BAJFINANCE041, BAJFINANCE042, BAJFINANCE043, BAJFINANCE044, BAJFINANCE045, BAJFINANCE050, BAJFINANCE051, BAJFINANCE052, BAJFINANCE095, BAJFINANCE097, HINDALCO021, HINDALCO022, HINDALCO023, HINDALCO024, HINDALCO025, HINDALCO026, HINDALCO027, HINDALCO031, HINDALCO032, HINDALCO033, HINDALCO037, HINDALCO038, HINDALCO039, HINDALCO040, HINDALCO041, HINDALCO048, HINDALCO050, HINDALCO097, HINDALCO099, HINDALCO100, KEC021, KEC022, KEC023, KEC024, KEC026, KEC028, KEC050, KEC095, KEC097

*Defect it closes.* This is where 'empty store means not extracted' bites: order book, AUM and per-tonne figures were read out of decks by hand each round.

#### 3. `transcript_statement` — 42 questions, effort M (3-10 days), 1,037 pages x ~$0.005 -> ~$5 one-time for all three

*What it holds.* One row per substantive paragraph of every call/deck with speaker, topic tags, period and the exact quote.

*Columns.* isin, doc_key, call_date, page, speaker, role (md|ceo|cfo|analyst), topic (margin|order_book|cost|guidance|capacity|demand|competition|working_capital|risk|mna|other), period_discussed, statement TEXT, quote TEXT, known_at (=call date), known_at_source, model, prompt_version

*Point in time.* known_at = the call date; a statement about Q4 FY26 made on the Q1 FY27 call is dated by the call

*Filled from.* transcripts: KEC 53 docs / 898 pages, BAJ 11 docs / 79 pages, HIND 3 docs / 60 pages (docs table counts)

*Extraction and cost.* one model read per page (Haiku 5.5, strict JSON: speaker, topic, quote, period), no free text. 1,037 pages x ~$0.005 -> ~$5 one-time for all three

*Unlocks.* BAJFINANCE039, BAJFINANCE040, BAJFINANCE047, BAJFINANCE048, BAJFINANCE049, BAJFINANCE060, BAJFINANCE067, BAJFINANCE068, BAJFINANCE069, BAJFINANCE070, BAJFINANCE071, HINDALCO028, HINDALCO029, HINDALCO030, HINDALCO035, HINDALCO036, HINDALCO044, HINDALCO045, HINDALCO046, HINDALCO047, HINDALCO055, HINDALCO056, HINDALCO064, HINDALCO065, HINDALCO066, HINDALCO067, HINDALCO068, HINDALCO075, KEC045, KEC046, KEC047, KEC048, KEC057, KEC058, KEC066, KEC067, KEC068, KEC069, KEC070, KEC071, KEC072, KEC076

*Defect it closes.* HIND has 3 transcripts total: the 'what did they say' failures there are a fetch gap, not a text-layer problem.

#### 4. `price_delivery` — 21 questions, effort S (1-3 days), $0

*What it holds.* Daily OHLCV, delivery quantity/percent and adjusted returns, both exchanges.

*Columns.* isin, symbol, exchange (NSE|BSE), date, open, high, low, close, prev_close, volume, value_inr, num_trades, deliverable_qty, delivery_pct, adj_factor, adj_close, known_at (=bhavcopy date), source_file

*Point in time.* known_at = the trading date of the bhavcopy (EOD data is known that evening)

*Filled from.* px_nse/px_bse copies (1,926 rows each, 2019-01-01..2026-10-19) + the truth snapshot for adjusted prices

*Extraction and cost.* SQL copy of the snapshot (already done for raw, not for adjusted), no model. $0

*Unlocks.* BAJFINANCE083, BAJFINANCE084, BAJFINANCE085, BAJFINANCE086, BAJFINANCE087, BAJFINANCE094, BAJFINANCE099, HINDALCO081, HINDALCO082, HINDALCO083, HINDALCO084, HINDALCO085, HINDALCO092, HINDALCO093, KEC082, KEC083, KEC084, KEC085, KEC086, KEC087, KEC094

*Defect it closes.* The loop answered market questions from raw closes; the split-adjusted series is needed for FY26 return questions.

#### 5. `fin_quarter_xbrl` — 18 questions, effort S (1-3 days), $0

*What it holds.* Every reported quarter, both bases, every XBRL line item. The spine for quarter maths and sum-of-quarters.

*Columns.* isin, symbol, period_start, period_end, fiscal_period (Q1FY26..Q4FY26), basis (consolidated|standalone), statement (P&L|BS|CF), line_item (canonical: revenue_from_operations, ebitda, ebit, pat, pat_owners, finance_cost, depreciation, other_income, tax, eps_basic, eps_diluted, paid_up_capital, face_value, net_worth, borrowings, cash), value NUMERIC, unit (inr), scale (1), xbrl_tag TEXT, source_file, source_rowid, known_at (=filings.dissem_ts or broadcast_ts), known_at_source (filing record), is_reported INT

*Point in time.* known_at = results_xbrl.filings.dissem_ts/broadcast_ts, never the crawl date

*Filled from.* results_xbrl.db quarterly (KEC 12 rows, BAJ 12, HIND 61 in the sandbox copies) widened to every quarter FY24-Q1FY27, plus equity_intelligence results tables where the XBRL payload lacks BS/CF items

*Extraction and cost.* SQL copy + XBRL tag map (no model). $0

*Unlocks.* BAJFINANCE005, BAJFINANCE006, BAJFINANCE011, BAJFINANCE017, BAJFINANCE096, HINDALCO005, HINDALCO006, HINDALCO011, HINDALCO017, HINDALCO094, HINDALCO095, KEC005, KEC006, KEC007, KEC011, KEC017, KEC018, KEC096

*Defect it closes.* KEC and BAJ copies hold only 12 quarters (FY26 x 2 bases + Q1FY27 x 2), so 'trend from Q1 FY25' cannot be served today.

#### 6. `guidance_actual` — 18 questions, effort S (1-3 days), $0 after T11 (the model cost is T11's)

*What it holds.* What was guided, on which call, for which period, and what was later delivered, with the variance.

*Columns.* isin, metric, horizon (FY26|FY27|Q1FY27), guided_low NUMERIC, guided_high NUMERIC, guided_point NUMERIC, unit, firmness (target|expect|aspire|range), call_date, doc_key, page, quote, actual_value, actual_period, actual_ref (T01/T02/T04 row id), variance_pct, known_at (=call date), actual_known_at, is_hit (1|0|NULL)

*Point in time.* two clocks: known_at for the guidance, actual_known_at for the delivery; a comparison is only valid after both

*Filled from.* T11 rows tagged guidance + the metrics in T01/T02/T04

*Extraction and cost.* rules over T11 (a sentence with a metric, a number/range and a horizon) + join to actuals, no new model call. $0 after T11 (the model cost is T11's)

*Unlocks.* BAJFINANCE061, BAJFINANCE062, BAJFINANCE063, BAJFINANCE064, BAJFINANCE065, BAJFINANCE066, HINDALCO058, HINDALCO059, HINDALCO060, HINDALCO061, HINDALCO062, HINDALCO063, KEC060, KEC061, KEC062, KEC063, KEC064, KEC065

*Defect it closes.* Guidance is the weakest kind in all three banks (10/18 answered); it needs both a call corpus and a horizon lexicon.

#### 7. `fin_annual_line` — 25 questions, effort M (3-10 days), $0 for the locator; ~$0.005/page for unmatched pages, ~1,900 pages/company -> <=$5/company

*What it holds.* The reported annual statement lines, one row per (year, basis, statement, item), with the page and the quote.

*Columns.* isin, fiscal_year, period_start, period_end, basis, statement (P&L|BS|CF|notes), line_item (same lexicon as T01 plus net_debt, capex, cfo, capital_employed, receivables, inventory, payables, total_debt, dividend_per_share, order_book_intake-note), value NUMERIC, unit, scale (1|1e7), doc_key, page INT, quote TEXT, known_at (docs.filing_date or ar_facts.filed_at), known_at_source, is_reported INT, is_derived INT

*Point in time.* known_at = the annual report's own filing/board date; a figure restated in a later AR keeps both rows keyed by known_at

*Filled from.* raw/pilot60_history/<CO>/annual_report + extra_annual_report PDFs; ar_facts.db (KEC 22,422 / BAJ 22,186 / HIND 33,733 rows, of which FY26: BAJ 2,944)

*Extraction and cost.* PDF text layer -> statement-page locator (headings 'Balance Sheet', 'Statement of Profit and Loss', 'Cash Flow') -> row-caption regex against a fixed lexicon; one model read per unmatched page. $0 for the locator; ~$0.005/page for unmatched pages, ~1,900 pages/company -> <=$5/company

*Unlocks.* BAJFINANCE001, BAJFINANCE002, BAJFINANCE003, BAJFINANCE004, BAJFINANCE007, BAJFINANCE008, BAJFINANCE010, HINDALCO001, HINDALCO002, HINDALCO003, HINDALCO004, HINDALCO007, HINDALCO008, HINDALCO010, HINDALCO051, HINDALCO052, KEC001, KEC002, KEC003, KEC004, KEC008, KEC010, KEC049, KEC055, KEC056

*Defect it closes.* ar_facts today is a bag of snippets: BAJ's FY26 items are dominated by notes (VAT/ESI matters), with no NIM, no EPS.

#### 8. `event_ledger` — 20 questions, effort M (3-10 days), ~2,100 attachments/company x $0.002 -> <=$4/company

*What it holds.* Typed corporate events with the numbers attached: order wins, board outcomes, fund raises, guarantees, JV/acquisition, management change, AGM/voting, RBI action.

*Columns.* isin, event_at DATE, event_type (order_win|board_outcome|fund_raise|guarantee|jv|acquisition|mgmt_change|agm|rating_action|rbi_action|esg_rating|business_update), headline, counterparty, business, geography, value NUMERIC, unit, currency, doc_key (attachment), page, quote, known_at (=DissemDT/NEWS_DT), known_at_source, newsid -> announcements.NEWSID

*Point in time.* known_at = exchange dissemination time (DissemDT), which is the only correct PIT stamp for an announcement

*Filled from.* bse_announcements.db announcements (to 2026-09-28 in KEC/BAJ copies, 2026-10-16 in HIND) + the attachment PDFs

*Extraction and cost.* regex on headline/category for the type + one model read per attachment first page for value/counterparty. ~2,100 attachments/company x $0.002 -> <=$4/company

*Unlocks.* BAJFINANCE073, BAJFINANCE074, BAJFINANCE075, BAJFINANCE076, BAJFINANCE077, HINDALCO069, HINDALCO070, HINDALCO071, HINDALCO072, HINDALCO073, KEC032, KEC033, KEC034, KEC035, KEC036, KEC037, KEC038, KEC059, KEC073, KEC099

*Defect it closes.* Order announcements are the KEC 'event' bank: 7 questions, 5 answered, because the headline often has no value.

#### 9. `shp_category` — 9 questions, effort S (1-3 days), $0

*What it holds.* Shareholding by holder category per quarter, from the SHP XBRL, not just promoter/public totals.

*Columns.* isin, symbol, quarter_end, category (promoter, promoter_group, promoter_pledged_pct, fii, dii_mf, dii_insurance, dii_other, public_retail, public_other, shareholder_count), shares NUMERIC, pct NUMERIC, unit (shares|pct), source_kind (xbrl|pdf_table), source_file, source_row, known_at (=submission/broadcast date), known_at_source, is_reported

*Point in time.* known_at = the SHP filing date (submission_date/broadcast_at), which is 2-4 weeks after quarter_end

*Filled from.* raw/nse_shp_xbrl_pilot (563 .xml.gz) + the exchange SHP XBRL + equity_intelligence shp_index (KEC 22 / BAJ 23 / HIND 20 quarter rows exist globally)

*Extraction and cost.* gzip + XML parse by tag (PromoterAndPromoterGroup, PublicShareholding > Institutions > MutualFunds/ForeignPortfolioInvestors), no model. $0

*Unlocks.* BAJFINANCE088, BAJFINANCE089, BAJFINANCE090, HINDALCO086, HINDALCO087, HINDALCO088, KEC088, KEC089, KEC090

*Defect it closes.* The sandbox copies are empty for BAJ/HIND although the source holds 23/20 rows: shp_index stores the ISIN of the filing year (BAJ INE296A01016, HIND IN9038A01010) while company.py filters INE296A01032/INE296A01024 and INE038A01020.

#### 10. `segment_series` — 15 questions, effort M (3-10 days), $0 for text-layer grids; ~$0.005/page for image decks, ~40 pages/company -> <=$1/company

*What it holds.* Segment/business/geography revenue and EBITDA per period, from the segment note and the deck segment tables.

*Columns.* isin, fiscal_period, period_type, segment (T&D, civil, transportation, renewables, cables, oil_gas, aluminium_upstream, aluminium_downstream, copper, novelis, india, housing_finance, securities, mortgage, consumer, rural, sme, commercial, auto, gold), metric (revenue, ebitda, pbit, ebitda_margin, assets), value, unit, scale, share_pct, doc_key, page, quote, known_at, known_at_source, is_reported

*Point in time.* known_at = segment note's annual report date / deck date

*Filled from.* annual_report segment notes, investor_presentation segment pages, results_press_release

*Extraction and cost.* statement-page locator + table-aware row parse (a segment note is a grid: label x period); model read for the deck segment pages that are images. $0 for text-layer grids; ~$0.005/page for image decks, ~40 pages/company -> <=$1/company

*Unlocks.* BAJFINANCE027, BAJFINANCE030, BAJFINANCE031, BAJFINANCE080, BAJFINANCE082, HINDALCO020, HINDALCO043, KEC025, KEC031, KEC039, KEC040, KEC041, KEC042, KEC043, KEC044

*Defect it closes.* KEC sells oil-and-gas and renewables as one 'Others' line - the table can only record what the company discloses.

#### 11. `commodity_price` — 5 questions, effort S (1-3 days), $0

*What it holds.* Monthly and fiscal-year commodity series, so a price question stops being unanswerable.

*Columns.* series (lme_aluminium, lme_copper, alumina, zinc, steel_hrc_india, iron_ore, usdinr), period_start, period_end, period_type (M|FY), value NUMERIC, unit (usd_per_tonne|inr_per_tonne|usd_per_kg|inr), scale, source (LME/WB/RBI/steel_mill), fetched_at, known_at (=series publication date), source_file, source_row

*Point in time.* known_at = the publication date of the series point, not the fetch date

*Filled from.* raw/commodity_series (325 files: commodity_series.csv + RBI reference-rate HTML), raw/input_cost_series (22)

*Extraction and cost.* CSV/SQL copy + FY average/period-end aggregation, no model. $0

*Unlocks.* HINDALCO076, HINDALCO077, HINDALCO079, KEC077, KEC078

*Defect it closes.* KEC078 and HIND076/077/079 were failed as 'absent' while raw/commodity_series holds 325 series files - a copy gap.

#### 12. `rating_esg` — 5 questions, effort S (1-3 days), <=$1/company

*What it holds.* Credit ratings and ESG ratings with agency, instrument, action and date.

*Columns.* isin, kind (credit|esg), agency (CRISIL|ICRA|CARE|India Ratings|MSCI|Sustainalytics|CDP), instrument, rating TEXT, outlook, action (assigned|upgraded|downgraded|affirmed|withdrawn), score NUMERIC, scale TEXT, doc_key, page, quote, known_at (=rating press release date), known_at_source

*Point in time.* known_at = the agency's action date, not the day the intimation was filed

*Filled from.* announcements (rating intimation + attachment) and annual report credit-rating note

*Extraction and cost.* regex on announcement headline ('Credit Rating') + one model read of the attachment. <=$1/company

*Unlocks.* BAJFINANCE055, HINDALCO057, HINDALCO074, KEC074, KEC075

*Defect it closes.* Four questions (KEC074/075, BAJ055, HIND057/074); KEC074's grade sits in an attachment that was never copied.

#### 13. `corp_action` — 4 questions, effort S (1-3 days), $0 for headlines; <=$2/company if attachments must be read

*What it holds.* Dividends, splits, bonus, buyback, rights: amount, type, ex/record date, FY, source page.

*Columns.* isin, action (dividend_final|dividend_interim|dividend_special|split|bonus|buyback|rights), fiscal_year, amount_per_share NUMERIC, ratio TEXT, face_value NUMERIC, announced_at DATE, ex_date DATE, record_date DATE, doc_key, page, quote, known_at (=announcement dissemination), known_at_source, is_reported

*Point in time.* known_at = the board/intimation date; record_date is a future fact at announcement time and is kept as its own column

*Filled from.* announcements (KEC 1,083 / BAJ 804 / HIND 1,209 rows) + annual report dividend notes + results XBRL

*Extraction and cost.* regex on announcement text ('dividend of Rs X per share', 'record date') + XBRL, model read only when the amount is in an attachment. $0 for headlines; <=$2/company if attachments must be read

*Unlocks.* BAJFINANCE012, BAJFINANCE072, HINDALCO012, KEC012

*Defect it closes.* KEC012 failed its check twice on the unit ('Rs per share' unknown) - the unit vocabulary, not the data, was wrong.

#### 14. `macro_series` — 6 questions, effort M (3-10 days), $0

*What it holds.* India macro and policy series that the ripple questions reference: repo rate, CPI, credit growth, capex plans, tariffs.

*Columns.* series (repo_rate, cpi, iip, bank_credit_growth, retail_credit_growth, transmission_capex_plan, railway_capex, us_tariff_232), period_start, period_end, period_type, value NUMERIC, unit, source (RBI|PIB|Budget|CEA), published_at DATE, known_at, source_file, source_row

*Point in time.* known_at = publication date; a budget number is known from the speech date, not the fiscal year

*Filled from.* raw/rbi (106), raw/index_history, raw/macro_pdfs, budget/PIB documents where held

*Extraction and cost.* SQL copy + one parser per source family, no model. $0

*Unlocks.* BAJFINANCE078, BAJFINANCE079, BAJFINANCE081, HINDALCO078, KEC080, KEC081

*Defect it closes.* BAJ078/079/081 and KEC080 failed for lack of this; the question text assumes the series exists.

#### 15. `valuation_daily` — 3 questions, effort S (1-3 days), $0

*What it holds.* Market cap, P/E, P/B, EV/EBITDA and yield computed per day from T07 share count and trailing T01/T02 financials.

*Columns.* isin, date, close, shares_outstanding (T07 as of date), market_cap, trailing_eps, trailing_pat, net_worth, net_debt, trailing_ebitda, pe, pb, ev_ebitda, dividend_yield_pct, known_at (=the later of price date and the financials' known_at), input_refs

*Point in time.* known_at must be the later of the two inputs: a 16 Oct P/E cannot use a 30 Oct filing

*Filled from.* T15 + T07 + T01/T02/T03

*Extraction and cost.* formula over the four tables, no model. $0

*Unlocks.* KEC091, KEC092, KEC093

*Defect it closes.* Six market-derived questions (KEC091-093, BAJ091-093, HIND089-091) needed this and three were answered only approximately.

#### 16. `subsidiary_pnl` — 3 questions, effort M (3-10 days), $0

*What it holds.* Subsidiary and segment-entity results, including the USD-reporting Novelis block.

*Columns.* isin, entity (bajaj_housing_finance, bajaj_financial_securities, novelis, hindalco_India, utkal_alumina), period, basis, metric (revenue, pat, aum, ebitda, net_income), value, unit (inr_cr|usd_mn), scale, fx_rate_num, doc_key, page, quote, known_at, known_at_source

*Point in time.* known_at = the subsidiary's filing date / the parent's results date, whichever is later

*Filled from.* annual report subsidiary note, results_press_release, Novelis 10-K/earnings release where held

*Extraction and cost.* statement-page parse + a fixed FX column, no model. $0

*Unlocks.* BAJFINANCE056, BAJFINANCE057, BAJFINANCE058

*Defect it closes.* Five BAJ questions and three HIND Novelis questions invert around this; USD figures were rejected by the old unit vocabulary.

#### 17. `cost_structure` — 2 questions, effort M (3-10 days), ~60 pages x $0.005 -> <=$1/company

*What it holds.* The cost/price mix a sensitivity question needs, per unit of output.

*Columns.* isin, period, basis, output_unit (tonne|kw|project), cost_line (coal, power, alumina, carbon, other_raw_material, labour, freight, subcontracting), value_per_unit NUMERIC, unit, currency, share_pct, contract_type (fixed_price|price_variation), doc_key, page, quote, known_at, known_at_source

*Point in time.* known_at = the deck/call date the split was disclosed

*Filled from.* decks (cost-per-tonne bridges), transcripts (cost commentary), annual report notes

*Extraction and cost.* model read per cost-bridge page (a grid with 4-6 lines) + arithmetic check that the lines sum to the reported total. ~60 pages x $0.005 -> <=$1/company

*Unlocks.* HINDALCO080, KEC079

*Defect it closes.* KEC079 and HIND080 ask for a split the companies do not publish; without it the answer is an assumption, and the table must say so.

#### E1. `share_capital` — 0 questions, effort S (1-3 days), $0

*What it holds.* Share count over time: paid-up capital, face value, shares outstanding, split/bonus events, ISIN history.

*Columns.* isin, as_of_date, shares_outstanding NUMERIC, paid_up_capital NUMERIC, face_value NUMERIC, unit (shares|inr), event (issue|split|bonus|buyback), ratio TEXT (1:5), doc_key, page, known_at, known_at_source (board/filing date), isin_effective_from, isin_effective_to

*Point in time.* known_at = the board/exchange date of the change; a share count is only usable after that date

*Filled from.* results_quarterly PaidUpValueOfEquityShareCapital + FaceValueOfEquityShareCapital (all three copy rows carry it), corporate-action announcements, symbol_isin_history

*Extraction and cost.* SQL division paid_up/face_value + corporate-action events from T08, no model. $0

*Unlocks.* none directly; it is required by the tables above (see E-rank).

*Defect it closes.* enabler: scored through the tables it feeds, not by direct assignment. FY26 share count is derivable today: BAJ 1,241,700,000 at face 2 then 6,212,400,000 at face 1 (1:5 split); HIND 2,220,000,000; KEC 534,200,000 at face 2.

#### E2. `doc_page` — 0 questions, effort S (1-3 days), $0

*What it holds.* Page-level text of every held PDF with a correct registry date; the fallback that makes every 'what did they say' question citable.

*Columns.* doc_key, doc_type, title, filing_date, known_at, page INT, text, method (pdf_text|ocr), chars INT, sha256, source_path, isin, doc_family (annual_report|deck|transcript|results|announcement|press_release)

*Point in time.* known_at from the filing record (BSE DissemDT / SEBI filing / call date), never the crawl date (doc_date)

*Filled from.* raw/pilot60_history/<CO>/* (KEC 386 / BAJ 422 / HIND 556 PDFs; doc_text today 6,267/6,450/6,782 pages and no registered doc without text, so page coverage is complete but the dates are stale)

*Extraction and cost.* PyMuPDF page loop + FTS5 index, no model. $0

*Unlocks.* none directly; it is required by the tables above (see E-rank).

*Defect it closes.* enabler: scored through the tables it feeds, not by direct assignment. BAJ/HIND text stops at filing 2024-03-30/2024-03-29 because the raw copy itself stops there; KEC reaches 2026-09-14.

### C4. What each kind of question becomes

| Kind | Today | With the schema |
|---|---|---|
| lookup | SQL or a page read, chosen per session | one SELECT on T02/T01/T04/T05 + one row of provenance |
| derived | a formula invented per session, sometimes marked partial | one SELECT on T03 (`formula_id` + `input_refs`) |
| text | FTS + quote crafting, 35/46 | one `doc_find` on T10/T11, answer is the quoted paragraph + page |
| guidance | call page vs actual, hand-joined | one join T12 → T01/T02/T04, variance computed |
| event | headline scan + attachment read | one SELECT on T09 by type/date/business |
| ripple | qualitative or absent | one join T13/T14 → T18 → T04 (assumption stated, not hidden) |
| market | px_nse selects, some missing adjusted series | one SELECT on T15/T16, split-adjusted, share count from T07 |

### C5. Coverage arithmetic

- 251 answered today by a store or a page read → unchanged, now one query each.
- 13 extract gaps and 4 copy defects → served by T02/T03/T04/T06/T07/T13/T14 without a new document.
- 2 check defects → served today, the answer was right and the check was wrong.
- 25 fetch gaps → served by a table once the document is fetched; the table is already specified.
- 3 not disclosed, 2 judgement → no table can serve them (section D).

**295 of 300 (98.3%) become a plain query or formula**, at a one-time extraction cost of **at most $64** across three companies: $0 for the SQL/XBRL tables (T01, T03, T06, T07, T10, T13, T15, T16), $15 for the KPI label mapping (T04), $15 for the annual-report caption reads (T02), $12 for the announcement attachments (T09), $5 for the transcript extraction (T11), and the rest small. At answer time: **$0 and no model call**.

---

## D. Unservable questions: what no table can serve, and why

### D1. The company does not disclose it

- **`KEC025`** "How was KEC's order book at the end of FY26 split across T&D, civil, transportation, renewables, oil and gas, and cables?" — KEC reports oil-and-gas and renewables as one combined 1% "Others" line. No extraction can split what the filing merges; the honest answer is the 5-way split plus a note that two lines are merged.
- **`BAJ080`** "What share of Bajaj Finance's AUM is consumer durable and digital product finance, and how exposed is it to a slowdown in festive season consumer spending?" — the product-wise AUM split was published up to FY24 and is not disclosed for FY25/FY26 in any held document. The exposure half is an assumption; the share half does not exist for the year asked.
- **`BAJ067`** "What did Bajaj Finance say about its FINAI or artificial intelligence programme and its effect on operating costs?" — "FINAI" appears in no held document. Either the term is ours and wrong, or it is from a call we do not have; until one of those is settled, no table can serve it.

### D2. It is an assumption, not a fact

- **`BAJ079`** "How might RBI's changes to risk weights on consumer credit and NBFC bank loans affect Bajaj Finance's capital adequacy?" — needs the RBI circular (held), the risk-weight mapping, and the bank's RWA mix by product (not disclosed). Any number is a model of the bank, so it belongs in a scenario table with the assumption in the row, not in an answer.
- **`HIND080`** "How might a 10% rise in domestic coal prices affect Hindalco's aluminium cost of production, based on its disclosed cost structure?" — the per-tonne cost split (coal/power/alumina/carbon) is not disclosed at the precision the question needs. `T18` can store what is disclosed and the answer must state the residual assumption.

### D3. Everything else marked "absent" is a fetch, not a hole

The other 25 non-answered questions are waiting on a document, and the coverage workbook names the table that will serve each the day it lands. The four with the highest yield: the FY26 annual report text for BAJ and HIND (unlocks `BAJ039`, `BAJ048`, `HIND098`), the Q1 FY27 and Q4 FY26 call transcripts for HIND and BAJ (unlocks the guidance block: `BAJ063/065/066`, `HIND059-063`), the announcement attachments (unlocks `KEC074/099`, `BAJ074/077`, `HIND066/068/070`), and the March-2026-onwards announcements for KEC and BAJ (unlocks `KEC037`, `BAJ073`).

---

## E. Next steps, in order, each with its acceptance test

1. **Fix the store copy (1 day).** Expand the ISIN filter with `symbol_isin_history` and reject a malformed ISIN; assert row counts against the source. *Accept:* `select count(*) from shp_index` returns 23 / 20 / 22 in the three sandboxes (today 22 / 0 / 0).
2. **Build the registry plus page table (1-2 days).** `docs` with a non-null filing date for every PDF, `doc_page` for every page, FTS5 on it. *Accept:* newest `doc_page.known_at` >= 2026-10-16 for all three; zero PDFs in `raw` without a registry row.
3. **Fetch the missing documents (1-2 days).** FY26 AR + Q1/Q4 FY26 calls for BAJ and HIND; attachments for the 40 announcements the questions name; KEC/BAJ announcements after 28 Sep 2026. *Accept:* section D3's list drops to zero fetch gaps.
4. **Build T01/T02/T03 + the formula registry (2-3 days).** *Accept:* re-answer KEC's 26 `derived` questions with SQL only, no model call, and reproduce the 26 stored answers to the rupee.
5. **Build T04 with the KPI lexicon (3-5 days).** *Accept:* order book, AUM, NIM, cost of funds, EBITDA/tonne and GNPA each answer with one SELECT; the 49 questions assigned to T04 pass.
6. **Build T06 from the SHP XBRL (1 day).** *Accept:* 9 holding questions, with MF/FPI/pledge, from the XML alone.
7. **Build T13/T14 series (1 day).** *Accept:* the 5 commodity and 6 macro questions answer with a joined series.
8. **Extract T11/T12 on 1,037 transcript pages (~$5).** *Accept:* the 18 guidance questions answer with horizon, guided value, delivered value and variance; every quote is a substring of the page.
9. **Re-run all 300 with the model out of the loop, then grade by reading.** *Accept:* >= 95% answered with a read grade (not the checks), and no answer that cites nothing.
10. **Only then replicate to 60 companies.** The per-company cost after step 4-8 is the extraction, not the answering.

### What I deliberately did not do

No fetch, no model call, no write outside `tasks/arch_v4/` and `.tmp/`. `tasks/STATE.md` and `docs/DEVELOPER_GUIDE.md` §N are marked read-only in the brief, so the state line for this report is in this file and in the ticket, not in `STATE.md` — that is the one documentation rule this change cannot satisfy from inside the sandbox, and it needs your call.

### Reproduce

```
python .tmp/probe.py            # index the three sandboxes -> .tmp/probe/summary.json
python .tmp/classify.py         # answers -> .tmp/probe/rows.json
python .tmp/build_workbooks.py  # the two xlsx + .tmp/probe/facts.json
python .tmp/build_md.py         # this file
```
