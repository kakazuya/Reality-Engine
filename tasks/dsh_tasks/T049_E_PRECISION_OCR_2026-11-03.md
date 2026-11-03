# T-049 E: KPI precision, growth/mix formulas, local OCR for image pages. Brief by Opus (Wolf), 3 Nov 2026

Goal: raise the pilot3 oracle further with our own compute only. Read `docs/DEVELOPER_GUIDE.md` sections O and O2 first (pilot3 core and extractors are merged on main). After parts A, B, D: KPI oracle 68 of 111 numbers reproduced, 17 mismatched (period and segment confusion on chart pages: Hindalco shipments_kt / production_kt, KEC net_debt), 23 unmapped labels (growth percentages, shares, mixes); generic labels over-match on narrative pages (KEC ebitda_margin_pct 2,646 rows, mostly noise); segment reliable only on table pages; image pages skipped (needs_ocr: KEC 66, BAJFINANCE 227, HINDALCO 859 in sandbox docs, plus 141 in decks_full).

Do, in order, measuring the oracle after each step:
1. Precision: restrict generic labels (margin, revenue, ebitda) to table rows and to sentences that also carry a period and a unit; carry segment from the table's row/column header; take a chart page's period from the axis labels nearest the value (word positions); add a confidence column (table_row > table_chart > sentence > sentence_default) and make the oracle and queries prefer the highest.
2. Growth, share and mix questions as formulas over stored rows (add them to the formula registry / `queries.py`, not as extracted values): YoY / QoQ growth, share of total, mix by segment, book-to-bill, coverage years.
3. Image pages: OCR with RapidOCR (already used in this repo; local ONNX on CPU, GPU allowed via DirectML or CUDA) at 300 DPI grayscale for every `needs_ocr` page of the three companies, store as `method='ocr_rapid'` with the OCR confidence, then rerun the KPI extractor on those pages. No paid or remote OCR. Report pages/minute and the oracle gain.
4. Rerun `python -m reality_engine.pilot3.oracle` and `.tmp/kpi_oracle.py` (rebuild it from the merged code if needed) and report before/after per KPI.

Files: `reality_engine/pilot3/kpi.py`, `transcripts.py`, `lexicon/*.yaml`, `queries.py`, `ratios.py`, `oracle.py`, new `reality_engine/pilot3/ocr.py`, tests `reality_engine/tests/test_pilot3_kpi.py`, `docs/DEVELOPER_GUIDE.md` sections O/O2. Do not edit `docs_collect.py` (another session).

Accept: tests pass; builds and extractors run with no network and no remote model; every stored value's quote is in its page text (OCR text for OCR pages); oracle before/after table; final message lists files, numbers, pages OCRed and speed, remaining misses with causes, and "Docs updated: <files>".

Stop if: a paid or remote model would be needed.

Never use run_in_background for a command you need the result of: background processes die when your turn ends. Run long commands in the foreground with a Bash timeout up to 600000 ms, in chunks if needed.

Budget: 3 hours.

Ticket: T-049
