# T-178: can the first-build facts be salvaged by re-keying? (script only, no model calls)

Ticket: T-178
Goal: decide how much of the Telegram build (T-214) can come from facts already extracted in the first build,
with no new model call. Measure, on the reference pages and on the T-214 queue, whether first-build facts,
once verified against the page text and re-keyed with the v2 label map + period engine, are complete and right.

Files (all READ-ONLY; open SQLite with `file:...?mode=ro` URIs):
- `reality_engine/data/deck_figures.db` (10.6 GB): `facts(sha256, page_no, metric, period, raw_number, value, unit, model, is_final)`,
  `pages(sha256, page_no, symbol, isin, doc_type, known_at, route, status, n_facts)`, `deck_sources`.
- `reality_engine/data/ar_facts.db` (21.9 GB, 33M rows): `ar_facts(doc_id, symbol, fiscal_year, filed_at, page, item, value_raw, value, unit, period, basis, quote, value_check)`,
  `ar_docs(doc_id, symbol, fiscal_year, fiscal_year_source, filed_at, sha256, path, n_pages)`. Index use only; no full scans without a WHERE on an indexed column (check `pragma index_list`).
- `reality_engine/data/concall_facts.db`: `cc_items`, `cc_docs`.
- Reference truth: `D:/RealityEngine/v2/reference_pages/pages.csv` (60 pages, `in_first_build` True = the 30 deck pages, 15 dev + 15 frozen; join on sha256 + page) and `reference_cells.csv` (row_label, col_header, value_text, unit_text, verbatim).
- Script arm (a): `reality_engine/v2/table_cells.py` round-10 cells (see `D:/RealityEngine/v2/p20_r10/`); label map `reality_engine/v2/label_map.py`; periods `reality_engine/v2/periods.py`; scorer `reality_engine/v2/truth_score.py` / `reader_score.py` (reuse their value matching; do not write a new matcher).
- Page text: `reality_engine/v2/page_words.py` (text layer per page); raw PDFs via `reality_engine/raw_store.py` when not local.
- Plan source: `tasks/FABLE_TESTS_2026-11-10.md` section 2.
- Queue: `D:/RealityEngine/tg_build/build_queue.csv` (93 companies; PRIVATE, never copy its contents into the repo).

Steps:
1. Arms on the 30 deck reference pages: (a) r10 script cells; (b) deck_figures facts as stored (is_final=1); (c) (b) kept only when the value appears verbatim in the page text layer (number normalisation: commas, brackets as negative, ~ and % stripped), then label -> metric via label_map and period via periods.py; (d) union of (a) and (c), conflicts flagged.
   Per arm, dev and frozen separately: recall vs reference cells, precision, share keyed to a metric, share with a resolved period, share verified verbatim.
2. Fiscal-year check: 200 random `ar_docs` (seed 178): derive the fiscal year from the report's own text (first pages: "Annual Report 2024-25", "for the year ended 31 March 2025") and compare with `fiscal_year`; report error rate by `fiscal_year_source`.
3. Coverage for the build: for the 93 queue symbols, documents filed >= 2024-04-01: count deck docs/pages in deck_figures, AR docs in ar_facts, call docs in concall_facts (status ok), and facts per doc. Output only counts per tier, no company names in the repo.
4. Decision per rule: (c) wins if its recall >= arm (a) AND precision >= 95% on frozen pages; else audit-only.

Outputs: `.tmp/t178/` in your worktree: `t178_first_build_rekey.xlsx` (sheets arms, fy_check, coverage, decision), the script as
`reality_engine/scripts/t178_salvage.py` with a small test `reality_engine/tests/test_t178_salvage.py` (number normaliser + verbatim check), and a 15-line summary in your final answer.

Accept: `python -m pytest -q reality_engine/tests/test_t178_salvage.py` passes; xlsx has the four sheets; summary states the decision with sample sizes.
Evidence: reference pages in first build = 30 deck pages only (results/AR reference pages are not); deck_figures facts sample: MAXESTATES p2 "Land accruing to Max Estates" raw "~84.71" acres, period "-" (period often missing -> periods.py must infer from header/doc date). ar_docs.fiscal_year_source e.g. 'filing_month_rule' (suspect).
Pitfalls: the DBs are 10-22 GB on C: — never copy them, never write to them; keep RAM < 2 GB (stream rows, no pandas of whole tables); MSI RAM is short. Do not touch `D:/RealityEngine/tg_build` except reading build_queue.csv.
Stop if: label_map/periods APIs can't take first-build labels without code changes > 100 lines (report and stop); or any query runs > 10 minutes.
Budget: 3 hours, DeepSeek max effort.
