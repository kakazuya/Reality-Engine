# Task: prototype extraction on 3 companies, to measure cost, accuracy and feasibility

## Goal
Shivam's order: no DeepSeek run on all 60 yet. Prove the method on BAJFINANCE (lender), HINDALCO (manufacturer, volumes) and KEC (order book), using every held annual report, earnings call, presentation and results filing since FY2024-25, and measure what it costs and how much it gets right. Claude decides from this report whether a wider run is worth doing.

## Budget: hard stops
- Reader spend cap stays at the default `REALITY_EXTRACT_SPEND=1.50`. Also stop at 3M input tokens. Whichever comes first ends the run; report what finished.
- Use the cheap path first: start at `deepseek-v4.1-flash~low`. Max effort only in the comparison in step 4.
- Filter to these 3 ISINs with `REALITY_EXTRACT_DB` pointing at `reality_engine/data/extract_proto3.db`. Do not write to `extract_pilot60.db` or any other store. Nothing else may be read or fetched for other companies.

## Method: three arms, run in this order, each recorded separately
1. **Arm A, no model:** XBRL (`results_xbrl.db`), PDF tables from the text layer, CPU OCR text where a page has none (RapidOCR or Windows OCR on CPU; no GPU), keyword and existing embedding search. Store what code alone can fill. Tokens: 0.
2. **Arm B, reader:** only for what Arm A left empty: selector picks passages, Flash reads them, the existing validator checks them (verbatim quote, number on the page, period, `known_at`). Include the existing 11 tables plus `balance_sheet_lines`, `cash_flow_lines`, `tax_reconciliation`, `lender_metrics`, `unit_volume`.
3. **Arm C, existing Haiku deck facts:** `deck_figures.db` holds Haiku 5.5 deck facts. Read `tasks/archive/handoff/LOCAL_OCR_PILOT_2026-10-24.md` and its `partial_metrics.json`, where OCR text alone was compared with Haiku but no verdict was reached. On these companies' decks, compare CPU OCR plus search, DeepSeek and Haiku values against each other, then hand-check every disagreement against the slide.
4. **Effort comparison:** run 30 of the same passages at low and at max. Report tokens, rows, wrong rows, missed rows.

## Measure and report
- Per document type and company: pages in the documents; pages sent to the model; tokens in, out and reasoning; tokens as a percent of whole-document tokens; cost at Go rates; wall time; which machine did what. Report the percent of the Go allowance used if the account exposes it; if it does not, say so rather than guess.
- Per measure: rows, by arm, and how many were found by code alone.
- Accuracy: 30 random rows per arm, read back against the source page. Recall: for each company and document type, take 3 documents, list every in-scope number by reading them whole with code plus a single reader pass, and report what the store missed.
- Cost forecast from measured rates, with low and high, for all 60 names and for the whole universe. Separate model tokens from worker agent tokens.

Prepare, do not grade: write `tasks/pilot60/PROTOTYPE3_ANSWERS_2026-11-01.jsonl`, with every question in `tasks/pilot60/PILOT_BANK_2026-10-31.jsonl` that names only these 3 companies, and for each the rows that answer it, with quote, page and the formula if computed, or 'not found'. Claude reads and grades these: DeepSeek does not grade the bank or rewrite it. Copy the bank file in from `C:\Users\warri\Downloads\Info_Diffusion_Model\tasks\pilot60\` if the worktree lacks it; read only.

## Acceptance checks
Every number in the report is traceable to a logged call or a stored row. No write outside the prototype database, `tasks/pilot60/` reports and the code. `known_at` comes from the filing record.

## Test command(s)
`python -m pytest reality_engine/tests -q -k extract60`

End with `Docs updated:`. Report at `tasks/pilot60/PROTOTYPE3_REPORT_2026-11-01.md`; no docs, no merge.
