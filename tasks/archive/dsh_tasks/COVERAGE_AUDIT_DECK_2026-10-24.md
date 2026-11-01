# Task: document-coverage audit + slide-style HTML report (parallel fan-out)

Owner: Shivam (2026-10-24): "how many concalls in total have been chunked and where are the gaps; same for investor
PPTs, PIB filings, quarterly financials, RBI and finance docs. Create a nice table and chart, PPT style, in HTML I can
analyze. Make it fast: parallelize." Reviewer: Claude.

## Parallelism (required)

Use your `subagent` tool: spawn 6 children at once, one per document family below, each READ-ONLY, each returning a
JSON blob of its numbers + gap lists. You (the parent) only assemble the report. maxDepth is 1 (children cannot spawn).
There is no wall-clock cap on children: check `list_agents` every few minutes and `interrupt_agent` any child running
over 15 minutes, then compute its family yourself with a simpler query. Each child must open SQLite only through
`reality_engine.db.readonly.connect_ro(path, timeout_s=60)` (temp_store=MEMORY, per-statement timeout), use indexed
columns, never correlated subqueries or unindexed GROUP BY over `document_chunks` (2.9M rows, 54 GB DB) — aggregate
`document_chunks` once by doc_id into a temp/CTE and join that. `raw_documents` now has `symbol`/`isin` columns.
Databases in `reality_engine/data/`: equity_intelligence.db, concall_facts.db, deck_figures.db, results_xbrl.db,
ar_facts.db, bse_announcements.db; vector indexes: `vector_index_nemotron8b` (chunk_ids.npy, done rows = all),
`vector_index_qwen8b_ar` (done.npy), `vector_index` (old bge). Use `catalog_descriptions.yaml` in plugins/reality-data
and the reality-data `catalog` tool to find tables.

## Families and the funnel to measure for each (by year 2019..2026, and by universe Nifty50/200/500/all listed where a company applies)

1. **Concall transcripts** — filed/known (corporate_documents doc_type CONCALL_TRANSCRIPT, BSE feed), PDF on disk on
   this laptop, chunked (raw_documents+document_chunks), embedded (in vector_index_nemotron8b), read by DeepSeek
   (concall_facts.db). Gap lists: 2026 transcripts read by DeepSeek but not chunked (STATE.md says ~583); companies
   with concalls filed but none chunked (e.g. DEEDEV); undated (doc_date is crawl date — use bse_dissem_ts/publication_date/call_date).
2. **Investor presentations (decks)** — known, downloaded (deck_sources.local_path exists here?), page figures extracted
   (deck_figures.db), chunked, embedded.
3. **PIB releases** — rows by month (English + regional), with body text, chunked/embedded, gaps by month (STATE.md: a
   9-month English hole Dec-2025..Sep-2026 was reported; verify current state).
4. **Quarterly financials** — results_xbrl filings by quarter (Mar-2025 onward integrated + legacy), companies covered
   per quarter vs listed companies, quarters missing per Nifty-200 company.
5. **RBI documents** — circulars/notifications/MPC/annual report etc.: counts by year and type, chunked/embedded.
6. **Finance / macro documents** — Union Budget, Economic Survey, state budgets, other macro_documents: counts,
   chunked/embedded, missing years.

Also a summary row per family: total known → on disk → chunked → embedded → structured-extracted, with % at each step.

## Report

Write `tasks/coverage/COVERAGE_2026-10-24.html`: one self-contained file, slide-deck style (16:9 "slides" stacked
vertically, keyboard ←/→ navigation optional), dark theme, colourful. Slide 1: executive summary funnel for all six
families (one table + a horizontal stacked bar chart). Then one slide per family: KPI tiles, a year-by-year chart
(stacked bars: chunked / on disk not chunked / known not downloaded), a gap table (top 25 gaps with company, period,
what is missing), and 2-3 bullet takeaways. Last slide: prioritized fix list (what to chunk/download/embed first and
estimated counts). Charts with Chart.js from `https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js`;
data embedded as JSON in the page; tables sortable (small inline JS). Also save the raw numbers to
`tasks/coverage/coverage_2026-10-24.json`.

## Rules

Read-only on all databases. No network except that CDN link in the HTML. Final answer: per-family summary numbers,
the biggest gaps, which children ran in parallel and their wall times, and anything you could not measure.
