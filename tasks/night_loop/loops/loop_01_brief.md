# Loop 1 brief: Phase 1 question sets for 10 companies, and the raw data for the 7 new ones

## A. Question sets (you write them; this is Claude's work, no worker reasons about the bank)
For each company in `PILOT10.md`, write `tasks/night_loop/questions/<SYMBOL>.jsonl` from the library:
universal + technical + its sector family's questions, rewritten with the company's own segments, products,
subsidiaries and the metrics it actually reports (check its latest investor presentation and results through the
`reality-data` tools before writing: `docs`, `doc_find`, `doc_page`, `search_docs`, `facts`; for KEC, BAJFINANCE,
HINDALCO the `pilot3_*` tools). Add company-specific questions an investor would ask (e.g. HDFC Bank merger
after-effects on CD ratio; Eternal Blinkit contribution margin; Maruti export share; Infosys large deals).
- Window: last 4 quarters only (Q3 FY26 - Q2 FY27, TTM). `as_of` = 2026-11-04 unless the question is dated.
- Format per line (GOAL section 2 and T-055 brief): {qid, symbol, sector, text, variations, order, lens,
  sector_fit, from_mids or "new" + new_reason, as_of, answer_kind, needs}. `needs` names the data the answer needs:
  `{"kind":"row","table":...,"metric":...,"period":...,"basis":...}` or `{"kind":"text","doc_type":...,"terms":[...]}`.
  Use table names of the pilot3 schema (`docs/PILOT3_BLUEPRINT.md`); a need with no table yet uses the table name
  it should have and `"new_table": true` (that is a Phase 2 work item, not a reason to drop the question).
- Size: about 80-120 questions per company; order-1 questions get at least 3 variations (name / ticker / BSE code,
  terse / full, dated / "last quarter"). Orders: 1st >= 40%, 2nd >= 25%, 3rd >= 10%. Every lens >= 10 per company.
- Sector fit: every metric in `sector_fit` and every row-need metric must be in the company's sector list or
  the universal / technical lists of `sector_vocab.json`. Extend a sector list only with a metric the company
  itself reports, and say so in the report.
- Checks: when T-055's `reality_engine/night_eval/qset.py check` is merged or available on its branch, run it from
  the worker's worktree on your files; until then check counts and duplicates with a short script of your own in
  `.tmp`. Then hand-read 30 random questions per company yourself and fix any that are unreasonable.
- Do not split dev / hidden; the wrapper does that after this loop.

## B. Raw data for HDFCBANK, SBILIFE, INFY, SUNPHARMA, MARUTI, HINDUNILVR, ETERNAL (last 4 quarters)
Goal: `D:\RealityEngine\pilot10\raw\<SYMBOL>\...` holds, per company, the results filings, investor presentations,
concall transcripts and results press releases for Q3 FY26 - Q2 FY27, the FY26 annual report, and announcement
PDFs from 1 Nov 2025 to today, with `manifest.csv`. Copy what the stores already hold (local paths in
`equity_intelligence.corporate_documents`, `deck_figures`, `ar_facts`; held mostly to Aug-Sep 2026) and fetch the
rest (Q2 FY27 season, announcement PDFs) with the existing fetchers (`reality_engine/ingestion/bse_client.py`,
`reality_engine/scripts/fetch_originals.py`; runner examples `D:\RealityEngine\raw\runners\*.ps1`; pace 1.5 s, BSE
needs the curl_cffi session). Running existing scripts is allowed for you; if a new fetch script is needed, brief a
dsh worker with the evidence. Report per company and document type: expected (from the exchange list), held, fetched,
missing with reason. Also confirm the structured stores cover the window for all 10: XBRL results
(`results_xbrl.db`), shareholding, prices and delivery, corporate actions.

## C. Worker slots
dsh `20261103T224355Z-ef762679` (T-055 check scripts) is already running and takes one slot; review its result when
it finishes (accept checks in its brief), record the verdict in your report; the wrapper merges. The second slot is
yours (e.g. a fetch script, or generalising `reality_engine/pilot3` to a symbol list + data root + output path,
which loop 2 needs first). Starts only off-peak (next window 09:30 IST).

## Done when
Ten question files written and checked, raw data in place with a coverage table, loop report and hand-off written
and committed.
