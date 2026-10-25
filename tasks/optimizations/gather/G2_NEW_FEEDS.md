# Task G2 — three missing feeds: deck page text, results-notes text, ETF premium

## Goal
Add three new deterministic jobs to `plugins/dsh-worker/jobs.yaml`. They fill data the EVAL25 questions need.
- Code only, shipped with `enabled: false`.
- Each is tested on a temp copy. Claude runs them live after review.

## Why
- **Deck page text** is not stored, so every page read fetches the PDF from Drive at about 15 s. Q9, Q17 and Q25 need it.
- **Notes text of quarterly-results PDFs** is not stored. Q14 asks for "Note 5" of the latest quarterly results.
- **`etf_premium`** is empty. Q19 compares ETF price with NAV.

## Files to touch
- New scripts in `reality_engine/scripts/`: `build_deck_page_text.py`, `fetch_results_notes_text.py`,
  `build_etf_premium.py`.
- New tests: `reality_engine/tests/test_new_feeds_g2.py`.
- New entries in `plugins/dsh-worker/jobs.yaml`. Mirror an existing entry: argv, writes, locks, freshness rule, cadence.
- Any downloaded PDF goes under `os.environ.get("REALITY_RAW_ROOT", r"D:\RealityEngine\raw")/<feed>/`, never under
  `reality_engine/data/`. Raw data lives on D (Shivam's rule).
- Do not touch: existing fetchers or tables, `reality_engine/config.py` (another worker owns it).

## Feeds
1. **deck_page_text**
   - Writes a new table `deck_figures.db:deck_page_text(sha256, page_no, text, chars, method, extracted_at,
     PRIMARY KEY(sha256, page_no))` plus an FTS5 index `deck_page_text_fts`.
   - Source: `deck_sources.local_path` when the file exists; otherwise the Drive fetch in
     `reality_engine/toolbelt/drive_fetch.py` (read its `--help`).
   - Extract with PyMuPDF. A page with fewer than 40 characters gets `method='empty'`; OCR is a later pass.
   - The job is resumable, processes the newest decks first, and takes `--limit` and `--since`.
2. **results_notes_text**
   - Writes `results_xbrl.db:results_notes(isin, period_end, source_newsid, page_no, text, known_at)` plus FTS5.
   - Source: the results PDF attached to that filing's BSE announcement (`bse_announcements.db:ann`, category Result).
   - `known_at` is the announcement time.
3. **etf_premium**
   - Fills `equity_intelligence.db:etf_premium` from the `etf_px` close against the `fund_nav` NAV, matched on ISIN
     and date.
   - Stores `premium_pct`, plus the iNAV gap from `etf_inav` when present.
   - Writes as an idempotent upsert.

## Steps
1. Read the schemas (`python -m reality_engine.toolbelt.sample_rows --help`) and one existing job for the pattern.
2. Implement each feed with `--db` pointing at a temp copy in tests.
3. Dry-run each against **temp copies** of the live DBs and print samples:
   - 5 real decks;
   - 5 real results filings;
   - MONQ50 (INF247L01AU3) for September 2026.

## Acceptance checks
1. The tests pass, and the new jobs.yaml entries pass the dsh-worker tests.
2. The report shows these samples:
   - one deck page's text;
   - one results-notes page that mentions "Note";
   - the MONQ50 premium rows for 2026-09-10..28.
3. No live DB was written: `git status` is clean for them and the live DBs' modification times are unchanged.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_new_feeds_g2
```

## Budget
≤ 20 tool calls before the first edit; ≤ 110 total; $0 paid.

## Report format
1. What changed  2. Samples (trimmed)  3. Estimated full-run time and size per feed  4. Open problems  5. Tool calls before first edit / total.
