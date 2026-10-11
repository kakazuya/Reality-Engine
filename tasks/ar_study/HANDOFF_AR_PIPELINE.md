# Hand-off: annual-report (AR) ingestion pipeline (from the AR study session, 2026-10-12)

Read this file first; it is self-contained. Details: `tasks/ar_study/CHALLENGER_FINDINGS.md` (Parts 1-3),
`tasks/ar_study/CPU_LEVERS.md`, `tasks/ar_study/challenger/step4_report.md`. Shivam's goal: **all relevant AR data
stored at true quality**. Efficiency is secondary, but no bulk AR reading by Claude; bulk LLM work goes to the free
OpenCode Go / Kilo models, and only the useful slice.

## Design (approved by Shivam 2026-10-11)

The CPU does the bulk; LLMs get only what the CPU cannot verify.

1. **Statements from XBRL** (`reality_engine/data/results_xbrl.db`, filings with `reporting_quarter='Yearly'`;
   context `FourD` = full year, `OneI` = year-end balance; values in rupees). The AR statement pages are only a
   cross-check.
2. **Tables in the AR** are parsed by CPU (`challenger/columns.py`: template-free; columns from right-aligned
   figures, headers from words above, spreads split, wrapped labels, year and unit from the table header,
   confidence per table).
3. **Validation gate** (`challenger/gate.py`). A table is trusted when:
   - an XBRL figure matches; or
   - subtotals add up; or
   - **prior-year tie**: its FY23 column equals the FY24 figures in last year's AR (the strongest general check).

   Rows also need a label plus a year (or % / count).
4. **Year-over-year diff** (`challenger/yoy.py`, 8-word shingles, numbers masked). Repeated prose is stored once;
   only new prose goes on.
5. **Free LLM gets:**
   - new prose that is flagged (auditor/CARO/C&AG/secretarial pages, red-flag words) or is a long narrative
     paragraph in the notes or directors' report;
   - tables that fail the gate, as that table only;
   - **compact CPU rows** for label clean-up (see suggestion 1).

## Measured (13 FY24 reports: COCHINSHIP, CONCOR, GESHIP + 10 unseen incl. a bank and an NBFC)

- **XBRL ↔ AR tie:** 60-90% of XBRL figures found in the AR tables with correct labels (Axis Bank 38-50/85: bank
  taxonomy).
- **CPU parse:** 9-17 s per report including last year's report. No GPU needed: OCR found 0 figures on 21
  image-only pages.
- **Table cells stored by CPU:**
  - 33% via the table-level gate + row filter;
  - 28% verified at row level (a cell in that row matches XBRL or last year's AR).
- **Hand check of stored rows:** ~74% fully right. Value, year and unit are right ~87% of the time; the errors are
  mostly messy labels plus some counts/tonnes tagged as ₹. **Target 90% not met by CPU alone.**
- **Must-find signals** (17 hand-verified items): 15 reach a verified table or the LLM slice.
  - K2 is repeated from FY23 (by design: read once in the baseline year).
  - G5 sits on a BRSR two-page spread the parser misses.
- **LLM load per report:** new-prose slice 28% of characters (~87 page-equivalents; flagged-only tier 21%) plus
  failing tables ~44 page-equivalents. An earlier 9% estimate was too optimistic, because that filter missed
  untriggered surprises.
- **Repetition:** 59% of AR text repeats the previous year's AR.

## Shivam's decisions, 2026-10-12 (relayed from the main session)

- Suggestion 1 (row-mode clean-up): **yes**.
- Suggestion 2 (prose slice to 12-15%): **skip**. Keep the wider ~28% slice, because quality beats efficiency.
  Load: ~130 page-equivalents per AR.
- Readers need not be vision models. Any free text model that passes the must-find test may be used: LongCat
  passed 25/25; Nemotron 3 Ultra/Super are being tested in `tasks/ar_study/free_test`.
- **Scale correction:** 34,278 ARs filed since 2019-07 are already downloaded (5,373 companies), not 12.7k.
  Multiply the totals in suggestion 6 by ~2.7: CPU ~2-3 days on a few workers; free-LLM load ~4.5M
  page-equivalents at ~130 per AR.
- Extra Kilo keys add no free capacity (one shared quota per model). Distinct models do.

## Suggestions (in order)

1. **Row-mode LLM pass instead of page reading for tables.** Send CPU rows as compact lines
   (`label | column header | year | unit | value | page`, ~60 characters each) to a free model.
   - It returns: canonical label, unit (₹ scale / % / count / physical unit), keep or drop.
   - The value is never re-typed by the LLM; it stays tied to the CPU match.
   - About 2k verified cells per report, ~30 page-equivalents.
   - This is the cheapest path to ≥ 90% row quality.
   - Test first on the 78 hand-checked rows in `step4_report.md` and the `row_verify.py` sample.
2. **Tighten the prose slice** to reach ~12-15% of characters:
   - novelty ≥ 0.6 for red-flag lines (statutory pages stay at 0.4);
   - shorten the lexicon (`upgrade`, `revers*`, `demand` fire too often);
   - drop BRSR and governance prose unless flagged.

   Re-run `run_step4.py` after each change and keep the must-find column at ≥ 15/17.
3. **Parser fixes still open:**
   - BRSR two-page spreads (G5);
   - physical units (tonnes, m3, GJ) and counts in BRSR/environment tables;
   - the bank schedule format and balance sheets split over two pages.
4. **Free-model test** (`tasks/ar_study/FREE_MODEL_QUALITY_PLAN.md`) on the slice only, scored against
   `challenger/gold_mustfind.json` and `challenger/gold_numbers.json`. Start only after concall ingestion has freed
   the Kilo throttle; the deck extractor shares it.
5. **Storage**, once 1-4 pass:
   - AR facts: ISIN, FY, filing time, page, unit, scope, period, source = xbrl/cpu/llm, check status;
   - AR text: new prose only, plus changed-only sections;
   - ~25-50 search chunks per AR instead of 388;
   - process newest-first, so every report has last year's AR for the diff. A company's first AR has no baseline
     and costs more.
6. **Expected total** after 1-2: ~40-60 page-equivalents of free-LLM work per AR. Across ~12.7k ARs that is
   ~0.5-0.75M page-equivalents, about the size of the deck job. The CPU part is ~1 day on a few workers. The
   download (~110 GB) is the slow part.

## Cautions

- **Prototype, not production.** All code is in `tasks/ar_study/challenger/`; move it into `reality_engine/` once
  suggestion 1 passes.
- **Overfitting.** Rules were tuned on these 13 reports. Keep a fresh unseen set for each round.
- **Shared resources.** Run at below-normal priority (`xbrl_tie.low_priority()`); the deck extractor and concall
  ingestion share CPU and the Kilo throttle. Never use the GPU.
- **Python patching.** Patching these files via inline Python in bash broke `\b` into backspace characters several
  times. Use the Edit tool or a script file, and check with `s.count(chr(8)) == 0`.
- **Uncommitted.** Nothing is committed. Two downloaded GESHIP PDFs are in `tasks/ar_study/src/`, not in the DB.
