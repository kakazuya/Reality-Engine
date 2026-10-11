# Annual reports: CPU levers to raise quality and cut LLM, chunk and compute load

Written 2026-10-11. Goal: only useful data goes to the free LLMs. Measured on 13 FY24 reports (the 3 study reports
plus 10 unseen ones), each compared with the same company's FY23 report. Scripts: `challenger/redundancy*.py`,
`challenger/llm_slice*.py`.

## Measured

| Lever | Measurement |
|---|---|
| **Text repeated from last year's report** (8-word shingles, numbers masked) | **59%** of text (45-75% per report); 32% of pages are ≥80% repeated |
| Boilerplate shared across companies (sentence level) | only ~2%, not worth building |
| Consolidated notes repeating standalone notes | 2-29% (CONCOR 2%, Dabur 10%, GESHIP 29%) |
| **Statements already in XBRL** (`results_xbrl.db`, parsed in another session: 76k filings, 2,773 companies, to Dec 2024) | FY24 balance sheet, P&L, cash flow and segments present. Cochin standalone operating cash flow there is ₹-172.83 cr, the same as the report |
| **LLM slice = text the CPU keeps (statutory blocks + red-flag lines) AND new vs last year** | **~9% of characters, about 12-32 page-equivalents per report** (5-9% for most). Axis Bank 31%: banking vocabulary trips the lexicon, so banks need their own word list |
| Whether "new vs last year" catches the item no rule found | Yes. Cochin's 1,200-passenger vessel note is 79% new; the SBFA / C&AG passages are 77-96% new |

## Levers, in order of payoff

1. **Take the statements from XBRL, not the PDF.** Use the report's statement pages only as a cross-check (two
   sources agreeing = verified). This removes the hardest parsing (multi-column statements) and the largest block
   of tables.
2. **Diff against last year's report.** Repeated text is stored once, then only when it changes (59% of text). New
   paragraphs in notes, MD&A and the directors' report go to the LLM even without a red-flag word; this is what
   catches untriggered surprises.
   - The first report of each company has no baseline (about 1 in 6 reports for FY20-26).
   - To fix that, run the newest year first and diff backwards.
3. **Validation gate (CPU):** a table is trusted without an LLM when its subtotals add to its totals, the balance
   sheet balances, or a figure matches XBRL. A matching figure also fixes the table's unit and year columns for
   certain.
4. **Per-company layout memory:** once a company's table parses and validates one year, keep its header-to-column
   mapping and reuse it next year. Layouts barely change year to year. Still dynamic, but learned per company.
5. **Sector word lists:** banks/NBFCs need their own list (default, NPA, provisioning are normal vocabulary there),
   plus the schedule-format statements.
6. **Drop consolidated notes that repeat standalone notes** (up to 29%).
7. **Better layout engine:** test `pymupdf_layout` / `pymupdf4llm` (CPU), which PyMuPDF itself suggests, against
   our parser on the gold set.
8. **BRSR from exchange XBRL** (filed in XBRL since FY23) instead of parsing 15-80 BRSR pages per report. Not
   fetched yet; needs checking.

## Compute: annual reports vs the deck job

| | Deck figures (running) | Annual reports, read whole by LLM | Annual reports with the levers above |
|---|---|---|---|
| Volume | ~776k slide pages | ~12.7k reports × ~250 pages ≈ 3.2M pages | CPU parse of 3.2M pages + LLM on ~28 page-equivalents per report ≈ **360k page-equivalents** |
| LLM load vs deck job | 1× | **~4×** | **~0.5×** (more in the first year per company with no diff) |
| CPU | page gating + RapidOCR | — | ~5 s per report in one process: ~18 CPU-hours total, ~2-3 h on 8 workers. No GPU needed (OCR found 0 figures on image pages) |
| Search chunks | — | 388 per report today (4.9M for 12.7k reports) | ~25-50 per report (kept-and-new prose only); ~10× less embedding and index work |

So annual reports cost **more** than the deck job only if an LLM reads them whole. With XBRL for the statements,
the year-over-year diff and the validation gate, the LLM load is about half the deck job, and the CPU part takes
hours, not days. The download (~110 GB) will take longer than the CPU parsing.
