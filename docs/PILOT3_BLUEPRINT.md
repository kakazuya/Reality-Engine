# Pilot database blueprint (KEC, BAJFINANCE, HINDALCO)

The one persistent record of how the pilot database was designed, tested and improved, and what the tests found.
Read this before changing the schema, an extractor or the scale-up plan. It keeps the method and the results;
the code's own detail stays in `docs/DEVELOPER_GUIDE.md` sections O to O8, and the live step in `tasks/STATE.md`.
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
| `ratio_panel`, `formula` | derived ratios with formula id and input row ids | computed from fin lines |
| `kpi_series` | company-stated KPIs (order book, AUM, EBITDA/t, NIM, mixes) with period, dimension, entity, quote, page | decks, results, press releases, transcripts |
| `transcript_statement` | call quotes with speaker, role, topic tags | transcripts |
| `guidance` | one row per forward target: metric, period, low/high, unit, revision link | transcripts, decks, results, press releases |
| `shp_category`, `share_capital`, `dividend_event`, `price_delivery`, `valuation_daily` | holdings, share count, dividends, prices, PE/PB/EV | exchange data stores |

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

## 8. Where the evidence lives
- Reports: `D:\RealityEngine\reports\2026-11-03_mcp_answer_grade.html`, `2026-11-04_mcp_reanswer_grade.html`,
  `2026-11-04_embedding_test.html`, `2026-11-03_answer_check_final.html`, `2026-11-03_ocr_hp_vs_msi.html`.
- Grades and answers: `D:\RealityEngine\pilot3\answer_run\`, `answer_run2\` (`regrades.tsv`).
- Retrieval evidence: `D:\RealityEngine\pilot3\embed_test\` (gold.json, EVAL.xlsx, split.json, by_doc_type.json,
  image_test.json, question_sources.json, ar_sections.json). Vector caches there are disposable.
- Decisions: `D:\RealityEngine\plans\DECISION_LOG.md`. Briefs: `tasks/dsh_tasks/T049_*`.
- Disposable: `D:\RealityEngine\pilot3\pilot3_before_*.db` backups, `pages_before_*.db`, worker `.tmp` folders.
