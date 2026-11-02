# Prototype-3 extraction report (BAJFINANCE, HINDALCO, KEC)

Generated 2026-11-01 by `python -m reality_engine.pilot.proto3 report`; every number here reads from `extract_proto3.db` (`extract_arm`, `extract_call`, the 16 measure tables) or the JSON files named beside it.

## 1. Scope and documents held

| company | doc type | docs | pages | chunks | chars |
|---|---|---:|---:|---:|---:|
| BAJFINANCE | annual_report | 1 | 515 | 380 | 1,455,587 |
| BAJFINANCE | concall | 10 | 191 | 322 | 61,080 |
| BAJFINANCE | deck | 13 | 956 | 807 | 70,904 |
| BAJFINANCE | results_notes | 1 | 28 | 32 | 72,604 |
| HINDALCO | annual_report | 1 | 413 | 505 | 2,381,932 |
| HINDALCO | concall | 11 | 263 | 403 | 55,719 |
| HINDALCO | deck | 22 | 824 | 660 | 43,253 |
| HINDALCO | results_notes | 1 | 15 | 10 | 35,448 |
| KEC | annual_report | 2 | 390 | 817 | 543,008 |
| KEC | concall | 10 | 10 | 10 | 1,598 |
| KEC | deck | 13 | 327 | 260 | 26,044 |
| KEC | results_notes | 1 | 14 | 19 | 42,939 |

Total documents in scope: 94, chunks 108,078. Scope: held documents first known on/after 2024-04-01. The table lists the four extraction document types; the total also counts the 8 announcements in scope (feed metadata, no passages).

## 2. Per measure, by arm

| table | rows | results_xbrl | chunks_v3 | bse_ann | rows added by Arm A | rows added by Arm B |
|---|---:|---:|---:|---:|---:|---:|
| `company_operating_metrics` | 378 | 0 | 378 | 0 | 0 | 378 |
| `company_segment_pnl` | 72 | 0 | 72 | 0 | 0 | 72 |
| `company_cost_structure` | 3 | 0 | 3 | 0 | 0 | 3 |
| `order_intake` | 12 | 0 | 12 | 0 | 0 | 12 |
| `order_book_contract` | 4 | 0 | 4 | 0 | 1 | 3 |
| `company_capacity_utilisation` | 156 | 0 | 156 | 0 | 0 | 156 |
| `capex_project` | 4 | 0 | 4 | 0 | 0 | 4 |
| `company_price_revision` | 6 | 0 | 6 | 0 | 5 | 1 |
| `company_debt_mix` | 6 | 0 | 6 | 0 | 0 | 6 |
| `rating_action` | 16 | 0 | 0 | 16 | 16 | 0 |
| `supply_link` | 0 | 0 | 0 | 0 | 0 | 0 |
| `balance_sheet_lines` | 173 | 166 | 7 | 0 | 173 | 0 |
| `cash_flow_lines` | 91 | 90 | 1 | 0 | 91 | 0 |
| `tax_reconciliation` | 200 | 200 | 0 | 0 | 200 | 0 |
| `lender_metrics` | 60 | 0 | 60 | 0 | 60 | 0 |
| `unit_volume` | 19 | 0 | 19 | 0 | 19 | 0 |

Arm A total: 565 rows, 0 model calls. Arm B total: 635 rows added.

### The `rating_action` scope defect (found 2026-11-01)

- **In scope?** No. The store held 223 rows for 37 companies; 34 companies (207 rows) are outside the three-name prototype.
- **Model tokens?** None produced those rows: they came from the code-only BSE announcement feed (a read of `bse_announcements.db`). The one model call on the table (2,933 in / 5,821 out, $0.003933) accepted 0 rows.
- **Cause:** universe_symbols() ignored its isins argument and _announcement_rating_pass called universe_isins() (the 60-name pilot) instead of SCOPE_ISINS. **Fix:** extract60.universe_symbols filters by the ISINs it is given; _announcement_rating_pass defaults to SCOPE_ISINS; proto3 scope prunes every measure table and rebuilds the feed under the scope.
- **Excluded now:** every count, accuracy sample and forecast below is computed after the prune. `rating_action` holds 16 rows for 3 companies, 0 out of scope. Record: `PROTOTYPE3_SCOPE_2026-11-01.json`.

## 3. Reading cost

- Reader calls logged: 443 (one row each in `extract_call`), of which 322 are Arm B extraction reads; the recall and effort reads are logged the same way (Arm C's 9 deck calls predate the ledger; see open problems).
- Tokens in / out: 930,414 / 1,572,093. The Go chat-completions response used here exposes prompt and completion tokens only; reasoning tokens are not split out, so `out` includes any reasoning.
- Cost at Go off-peak rates ($0.15/M in, $0.60/M out): $1.0828.
- Sum of per-call time (not wall clock): 10535.8 s; documents read: 77; passages' pages sent: 2916 of 3984 pages held.
- Arm B input tokens as a share of the whole text of the documents read: 29.87% (667,305 of 2,233,875).
- Reader spend cap: $1.50; input-token cap: 3,000,000. Errors: {"selection": {"tax_reconciliation": 7}, "rejected": {}, "extra_ann": 0, "scope": ["INE296A01032", "INE038A01020", "INE389H01022"], "since": "2024-04-01", "known_at": {"ar_date_fixed": 32, "ar_period_fixed": 31, "ar_checked": 170, "deck_checked": 824}, "errors": {}}

| doc type | calls | pages sent | in tokens | out tokens | cost USD | wall s |
|---|---:|---:|---:|---:|---:|---:|
| announcement | 6 | 41 | 12,743 | 8,215 | 0.0068 | 45.9 |
| annual_report | 18 | 259 | 47,497 | 58,678 | 0.0423 | 400.6 |
| concall | 77 | 447 | 163,209 | 248,392 | 0.1735 | 1587.4 |
| deck | 221 | 1496 | 443,856 | 710,316 | 0.4928 | 4210.1 |

Arm B extraction reads by company:

| company | calls | pages sent | in tokens | out tokens | cost USD | wall s |
|---|---:|---:|---:|---:|---:|---:|
| BAJFINANCE | 94 | 728 | 225,416 | 173,851 | 0.1381 | 1165.7 |
| HINDALCO | 152 | 1095 | 325,745 | 679,449 | 0.4565 | 3961.7 |
| KEC | 76 | 420 | 116,144 | 172,301 | 0.1208 | 1116.7 |

Spend by step (`extract_call.table_name`):

| step | calls | in tokens | out tokens | cost USD |
|---|---:|---:|---:|---:|
| `capex_project` | 68 | 132,549 | 223,448 | 0.154 |
| `company_capacity_utilisation` | 58 | 105,307 | 156,716 | 0.1098 |
| `company_cost_structure` | 4 | 10,703 | 7,370 | 0.006 |
| `company_debt_mix` | 4 | 12,606 | 29,506 | 0.0196 |
| `company_operating_metrics` | 56 | 115,070 | 328,640 | 0.2144 |
| `company_price_revision` | 7 | 7,749 | 3,746 | 0.0034 |
| `company_segment_pnl` | 51 | 135,890 | 202,373 | 0.1418 |
| `effort` | 96 | 184,518 | 384,357 | 0.2583 |
| `order_book_contract` | 58 | 120,605 | 22,577 | 0.0316 |
| `order_intake` | 15 | 23,893 | 45,404 | 0.0308 |
| `rating_action` | 1 | 2,933 | 5,821 | 0.0039 |
| `recall` | 25 | 78,591 | 162,135 | 0.1091 |

## 4. Accuracy (30 random rows per arm, read back to the source page)

- Arm A: 30/30 RIGHT (population 565 rows).
- Arm B: 30/30 RIGHT (population 635 rows).

Checks: the quote is verbatim on the source page, the row's number is printed on that page, and XBRL rows re-read the concept/context value from `results_xbrl.facts` (a derived tax-rate row re-reads both facts and recomputes the percentage; a feed row is checked against its BSE announcement headline). Row-level verdicts: `PROTOTYPE3_ACCURACY_2026-11-01.json`.

## 5. Recall (3 documents per type per company, one reader pass per document)

- documents read: 25 of the 36 planned (a company with fewer than three held documents of a type, or a document with no number-dense passage, is skipped); baseline rows accepted: 117; missed by the store: 91.
  - BAJFINANCE annual_report: baseline 0, missed 0 (1 number-dense pages read)
  - BAJFINANCE concall: baseline 14, missed 13 (3 number-dense pages read)
  - BAJFINANCE concall: baseline 15, missed 9 (3 number-dense pages read)
  - BAJFINANCE deck: baseline 18, missed 12 (6 number-dense pages read)
  - BAJFINANCE concall: baseline 12, missed 10 (2 number-dense pages read)
  - BAJFINANCE deck: baseline 3, missed 0 (5 number-dense pages read)
  - BAJFINANCE results_notes: baseline 0, missed 0 (2 number-dense pages read)
  - BAJFINANCE deck: baseline 8, missed 3 (6 number-dense pages read)
  - HINDALCO annual_report: baseline 0, missed 0 (2 number-dense pages read)
  - HINDALCO concall: baseline 3, missed 3 (3 number-dense pages read)
  - HINDALCO deck: baseline 2, missed 2 (5 number-dense pages read)
  - HINDALCO concall: baseline 5, missed 5 (2 number-dense pages read)
- missed by table: `balance_sheet_lines` 2, `company_operating_metrics` 46, `lender_metrics` 13, `order_intake` 8, `unit_volume` 22
  - e.g. BAJFINANCE concall `lender_metrics`: {"doc_id": "sha256:38b727e9eadf30596cdadc3744bc059195bc2b23ff9a4c71e1dc3108706b4b64", "isin": "INE296A01032", "known_at": "2026-02-07T15:07:37", "metric": "credit_cost_pct", "page": 4, "period_end": "2025-12-31", "quote"
  - e.g. BAJFINANCE concall `company_operating_metrics`: {"doc_id": "sha256:38b727e9eadf30596cdadc3744bc059195bc2b23ff9a4c71e1dc3108706b4b64", "isin": "INE296A01032", "known_at": "2026-02-07T15:07:37", "metric": "cost_of_funds", "page": 4, "period_end": "2025-12-31", "quote": 
  - e.g. BAJFINANCE concall `company_operating_metrics`: {"doc_id": "sha256:38b727e9eadf30596cdadc3744bc059195bc2b23ff9a4c71e1dc3108706b4b64", "isin": "INE296A01032", "known_at": "2026-02-07T15:07:37", "metric": "active_distribution", "page": 4, "period_end": "2025-12-31", "qu

## 6. Arm C (decks: Haiku vs DeepSeek vs CPU OCR)

- pages: 9; Haiku facts: 464; Haiku values found in OCR text: 458 (98.7%); DeepSeek rows: 129; OCR misses: 6; DeepSeek-only values: 2; Haiku values DeepSeek did not repeat: 289.
- hand-checked disagreements: 8; verdicts: {'HAIKU_WRONG': 2, 'HAIKU_RIGHT_OCR_MISS': 4, 'DEEPSEEK_RIGHT_HAIKU_MISS': 1, 'BOTH_WRONG_NON_FACT': 1}.
- Reading: Haiku's dense-table values are mostly right but its narrative-slide facts include digits lifted out of period labels ('Q4' -> 4.0); CPU OCR loses chart labels and dense table rows; DeepSeek keeps precision by quoting verbatim but returns a subset on time-series pages.

## 7. Effort comparison (30 passages at low and max)

- low: 30 calls, in 63,826, out 90,879, $0.0641, 148.7 s, rows 25, wrong 95.
- max: 27 calls, in 56,866, out 214,501, $0.1372, 723.4 s, rows 19, wrong 51; call errors {"ReadTimeout: HTTPSConnectionPool(host='opencode.ai', port=443): Read timed out. (read timeout=120)": 9}.
- rows found in both: 1; only low: 21; only max: 18. The compare key is the quote plus period, so two phrasings of one fact count as two rows.
- The low arm's first pass (30 calls, $0.057) was discarded on a row-pairing defect; both passes are in `extract_call` under `effort`, only the second is reported.

## 8. Cost forecast

Arm B build cost for the three companies: $0.7155 and 667,305 input tokens; every reader step together (build, recall, effort, deck comparison): $1.0828. Scaling by held document counts is the only honest forecast from this sample:

- 60 names: $12.97 low, $25.93 high (2x for harder documents).
- Whole universe: $18.24 low, $36.49 high.
- Measured per document: concall $0.008, deck $0.010, annual_report $0.011, announcement $0.002. Held documents: pilot-60 {'annual_report': 175, 'concall': 540, 'deck': 648, 'results_notes': 65}, universe {'announcement': 572, 'annual_report': 170, 'concall': 848, 'deck': 824, 'results_notes': 74}.
- A flat 60-name extrapolation from the three companies would be $4.77; the document-count forecast above is the one to use.
- Model tokens above are the reader. Worker-agent tokens are the harness's own tokens and are not visible to this process; they are a separate line item.

## 9. Answers prepared for Claude

- rows in `PROTOTYPE3_ANSWERS_2026-11-01.jsonl`: 153; answered with rows: 45; evidence passages only: 99; not found: 9.
- DeepSeek did not grade or rewrite the bank; each row carries quote, page, period and the formula when computed.

## 10. Machine split

- `SUMIT` (Python 3.14.7): Arm A code, Arm B reader, CPU RapidOCR, measurement and report.
- Haiku deck facts: held store `deck_figures.db` (produced by the deck pipeline before this run); this run only read them.

## 11. Open problems

- The reader's Go response does not expose reasoning tokens separately.
- The Go account does not expose a usage/allowance endpoint here, so the percent of the allowance is not reported; only the brief's $1.50 cap is enforced.
- `deck_figures` carried facts but no page text when this ran; Arm C OCR was the only way to re-check a slide that the text layer does not reproduce. `build_deck_page_text.py` now writes a `deck_page_text` table to the same DB.
- The chunks store attached the FY24 filing date (2024-06-26) to BAJFINANCE's FY26 annual report (sha256 5535038a...); `reconcile_known_at` now takes the date from `ar_docs` (2026-07-07) before extraction.
- Three runs sit outside the per-call ledger: the aborted effort-max pass (killed on the row-pairing defect; the 9 read timeouts in the recorded max arm are its tail), the `supply_link` tail of the Arm B build (killed after its last committed table, no rows), and Arm C's 9 deck calls (made before `extract_call` existed). Together about $0.07-0.08, so real reader spend is about $1.16 against the $1.50 cap.

## 12. Docs updated

- `tasks/STATE.md` — links the prototype-3 grade file (`PROTOTYPE3_CLAUDE_GRADE_2026-11-01.md`); it does not repeat these numbers.
- `tasks/pilot60/EXTRACTION_REPORT.md` — scope note: 16 tables, prototype-3 numbers live in this file.
- `tasks/pilot60/PROTOTYPE3_REPORT_2026-11-01.md` (this file), `PROTOTYPE3_ANSWERS_2026-11-01.jsonl`, `PROTOTYPE3_MEASUREMENTS_2026-11-01.json`, `PROTOTYPE3_ACCURACY_2026-11-01.json`, `PROTOTYPE3_RECALL_2026-11-01.json`, `PROTOTYPE3_ARM_C_2026-11-01.json`, `PROTOTYPE3_ARM_C_HANDCHECK_2026-11-01.json`, `PROTOTYPE3_EFFORT_2026-11-01.json`, `PROTOTYPE3_SCOPE_2026-11-01.json`.

