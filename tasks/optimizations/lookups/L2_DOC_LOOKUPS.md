# Task L2 — one-call document lookups in reality-data: `docs`, `doc_page`, `doc_find`

## Goal
Three new read-only reality-data MCP tools that take a company + a date (+ a page or a few words) and return the
document text with provenance in **one call**, across decks, transcripts, annual reports and announcements.

## Why
In a 10-question test (2026-10-25) workers spent ~80 of ~115 tool calls guessing raw SQL across five stores to find
"the 5 Aug presentation", "page 21 of 79", "the 18 Sep transcript". Each store keys documents differently
(sha256, doc_id, BSE filing). These tools hide that.

## Files to touch
- New: `plugins/reality-data/server/lookups_docs.py` (reuse helpers from `core.py`: `resolve_one`, `_identity_isins`,
  `_identity_symbols`, `_parse_date`, `_run_duck`, `_run_sqlite`, `provenance`, `quarantined_doc_ids`, `DataError`).
- `plugins/reality-data/server/server.py`: register the three tools **in one block inserted directly after the `sql`
  tool and before `_warm_data`**, delimited by `# --- lookups: docs ---` / `# --- end lookups: docs ---`. Another
  worker inserts its own block after `facts`; touch nothing else in server.py, and do not edit the server instructions
  string (the manager writes the routing guide).
- New tests: `plugins/reality-data/tests/test_lookups_docs.py`.
- New CLI: `reality_engine/toolbelt/lookup_docs.py` (`python -m reality_engine.toolbelt.lookup_docs doc_page 540879 2026-10-24 21`), same functions, prints JSON.
- Do not touch: `core.py`, `search_docs.py`, any database or index.

## Inputs/data (verified sources workers used successfully)
- Decks: `deck_figures.db` — `deck_sources(…, local_path, sha256, known_at)`, `pages(sha256, page_no, …)`,
  `facts(sha256, page_no, metric, raw_number, value, unit, is_final)`, `outputs(sha256, page_no, raw_output)`.
  Deck page TEXT is not stored; the PDF is at `local_path` or fetchable by sha via `reality_engine/toolbelt/drive_fetch.py`
  (read its `--help`); extract a page's text with PyMuPDF (`fitz`). Example: Sai Life deck 2026-08-07, sha256 563d861c…,
  page 10 of 31 reads "Operationalized a new 100,000 sq. ft. R&D facility at Genome Valley".
- Transcripts: `equity_intelligence.document_chunks` (metadata line `Symbol: X`, doc_id, page), `concall_facts.db`
  `cc_items` (doc_id, lists such as `capacity_and_projects`), `truth_duckdb.cc_docs`.
- Annual reports: `ar_facts.ar_facts` (doc_id, page), `truth_duckdb.ar_docs`.
- Announcements: `bse_announcements.db`; `equity_intelligence.corporate_documents`; `truth_duckdb.docs`.
- Dates: a filing's date is its BSE/known_at time, which can be the evening of or a day after the date a user names;
  `doc_date` in some tables is the CRAWL date — prefer filing/known_at. Match a requested date within ±3 days and
  report the exact date matched.
- Never a bare `sqlite3.connect`; never an unbounded scan or GROUP BY over `document_chunks` (use indexed keys / FTS5).
  No paid embeddings: do not call `query_embed`.

## Tool contracts
1. `docs(symbol, doc_type=None, date_from=None, date_to=None, limit=20)` — list the company's documents across all
   stores, newest first: type (deck/transcript/ar/announcement), filing date, title, page count, the store keys
   (sha256 / doc_id), and `has_text` / `has_facts` per store. Answers "what is the latest X".
2. `doc_page(symbol, date, page, doc_type=None)` — pick the document of that type nearest the date (say which and
   why if several), return the page's full text (stored chunk text, else PDF extraction from local/Drive file) plus
   any extracted facts on that page and the page count ("page 21 of 79").
3. `doc_find(symbol, terms, doc_type=None, date=None, top_k=8)` — lexical search (FTS5 / LIKE over bounded,
   per-document rows, plus PDF text for decks) inside that company's documents (one date if given), returning
   passages with doc, page and exact quote. This is the "what did they say about X in the Y transcript" tool.
- Every tool: resolves NSE symbol, BSE code, ISIN or name via `resolve_one`; applies `quarantined_doc_ids()`; returns
  `provenance`; on nothing found returns `{"found": false, "checked": [...], "nearest": [<closest docs by date>], "hint": "..."}` — never `[]`.
- Each call ≤ 5 s when the PDF is local; a Drive fetch may take longer — say so in the result (`fetched: true`).

## Steps
1. Read the `core.py` helpers and the five stores' schemas (`python -m reality_engine.toolbelt.sample_rows`,
   `coverage_peek`, `find_docs` — read `--help` first).
2. Implement + unit tests with small fixtures (mirror `test_reality_data.py`).
3. Live check (read-only) against the acceptance questions.

## Acceptance checks
1. `python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"` → all pass (existing + new).
2. Live, one call each, answers printed in your report:
   - `doc_page("540879", "2026-10-24", 21)` → text about a licence to manufacture, or `found:false` with nearest docs.
   - `doc_page("SAILIFE", "2026-08-07", 10)` → contains "100,000 sq. ft.".
   - `doc_find("INE864I01014", "fuel cell", doc_type="transcript", date="2026-08-06")` → quote with page.
   - `doc_find("COCHINSHIP", "KSOE", doc_type="transcript", date="2026-09-18")` and `"electric tug EBITDA"`.
   - `docs("Ganesha Ecosphere", "deck", "2026-08-01", "2026-08-10")` → the Aug 2026 deck.
3. `git diff --stat` touches only the files above.

## Test command(s)
```bash
python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"
```

## Budget
≤ 20 tool calls before the first edit; ≤ 100 total; ≤ 75 min; $0 paid.

## Report format
1. What changed  2. Verified (test counts + the live answers verbatim, trimmed to ≤ 3 lines each)  3. Outside-sandbox
steps  4. Open problems / data gaps found (store + key + what's missing)  5. Tool calls before first edit / total.
