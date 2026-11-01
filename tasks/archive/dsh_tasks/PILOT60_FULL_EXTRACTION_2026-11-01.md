# Task: extract every measure the bank needs, for all 60 pilot companies

## Goal
Shivam's rule: every question must become a query, and held documents are read so nobody has to read them again. Today the text holds far more than the stores. Names with the text in `document_chunks` vs names with rows in `fact`: order book 25 vs 5, trade receivables 49 vs 3, capacity utilisation 39 vs 4, operating cash flow 48 vs 0, CWIP 49 vs 0, sales volume 46 vs 0, gross NPA 8 vs 0, NIM 6 vs 0, tax reconciliation 42 vs 0.

`reality_engine/pilot/extract60.py` already does this well: 150 of 150 hand-checked rows were right. It only ran as a sample, reading 12 to 60 documents per table. Finish the job.

## Method, in this order
- **Code first, no model:** anything XBRL or a parsable PDF table can give comes from code (`results_xbrl.db` for results, balance sheet and cash flow lines; PDF table parsing for annual report statements and the tax note). The model reads only what code cannot.
- **Then the reader:** selector picks passages, DeepSeek V4.1 Flash reads them through the Go path. Use max effort (`REALITY_EXTRACT_MODEL=deepseek-v4.1-flash`, not `~low`), a stable session id, and `REALITY_EXTRACT_SPEND=0` or a cap high enough not to stop the run. Check how the code treats 0 before relying on it.
- **Recall loop, because the selector is the weak point:** earlier recall was 1/3 on two tables. For each table, have the reader go through 5 whole documents without the selector, list what the selector missed, widen it, and repeat until misses are under 10% or a stated reason explains the rest.
- **Scanned PDFs:** list files with no usable text (`is_scanned_guess`) with counts per measure. Do not OCR them; Claude runs that on the HP and they are read afterwards.

## Work
1. Run the existing 11 tables over every selected document for the 60 names in `tasks/pilot60/UNIVERSE.csv`, with no document cap. It resumes through `extract_done`.
2. Add these tables, same method (selector, Flash, deterministic validator): `balance_sheet_lines` (trade receivables, payables, inventory, investments, CWIP, total debt, cash, book equity), `cash_flow_lines` (operating, investing, financing, capex), `tax_reconciliation` (profit before tax, tax expense, tax at statutory rate, each reconciling item with its label, deductions and exemptions, effective rate), `lender_metrics` (gross and net NPA, loan book, NIM, credit cost, CASA, capital adequacy; lenders only), `unit_volume` (volume, unit, product, period).
3. Sources: annual reports, presentations, concalls, results notes, including `chunks_v3_pilot.db`, `chunks_v3_history.db` and `results_notes_chunks.db` under `reality_engine/data/pilot/pilot60/`. Tables inside PDFs matter most for balance sheets and tax notes: if chunks mangle a table, read the PDF page text.
4. Period and consolidated or standalone basis are required on every number. `known_at` comes from the filing record, never the crawl date.

Write only to `reality_engine/data/pilot/pilot60/extract_pilot60.db`. Back it up first to `D:\RealityEngine\backups`. Do not touch `fact_v4_pilot.db`, `v4.db`, the bank or `tasks/STATE.md`: Claude reviews and installs. Pilot names only; no other company. Use the free Go path with stable session ids. No DeepInfra and no paid models.

## Acceptance checks
- Every row keeps the existing validator: verbatim quote, number printed on the page, page, `known_at`.
- Report one table: measure, names with rows, names whose text holds the term, rows, and why the difference remains, with 3 real examples per measure.
- Recall check: for 5 companies per measure, a value read directly from the document compared with the stored row.
- Arithmetic checks on what can be checked: balance sheet totals, statutory tax plus reconciling items equals tax expense. Report the pass rate.
- Hand back 20 random rows per new table with source page text, for Claude's review, at `tasks/pilot60/EXTRACTION_FULL_SAMPLE_2026-11-01.md`.

## Test command(s)
`python -m pytest reality_engine/tests -q -k extract60`

End with a `Docs updated:` line; update `tasks/pilot60/EXTRACTION_REPORT.md`.
