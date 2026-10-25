# Task — fix the L2 document-lookup review defects

## Goal
Fix every defect the independent reviewer found in `lookups_docs.py`, with a regression test each; every call
≤ 5 s warm; tests green.

## Why
Review of L2 returned FAIL: default `doc_find` crashes (D1), `docs()` merges same-day documents and ignores `limit`,
and three stores are scanned without an index (12 s, timeouts silently swallowed).

## Files to touch
- `plugins/reality-data/server/lookups_docs.py`, `plugins/reality-data/tests/test_lookups_docs.py`.
- `git rm` the stray `PROGRESS_NOTES.md` at the worktree root and remove the empty `tmp_739bq9u/` dir if you can.
- Do not touch: `core.py`, `server.py`, any database (no new indexes: these DBs are read-only for this task).

## Reviewer defects (verbatim)
DEFECTS:
1. `plugins/reality-data/server/lookups_docs.py:913` — `deck.get("local_path")` on a `sqlite3.Row`: every `doc_find` without `doc_type="transcript"` (the documented default) returns `{"ok":false,"error":"AttributeError: 'sqlite3.Row' object has no attribute 'get'"}` (reproduced through MCP `call_tool`); fix: `deck["local_path"]`.
2. `lookups_docs.py:159-175` — merge key `(doc_type, date)` collapses same-day documents: INDIAGLYCO has 4 decks on 2026-09-02, `docs()` returns count=1 (AUBANK 2→1); fix: include sha256/doc_id/newsid in `_merge_key`.
3. `lookups_docs.py:707-713` + `:412` — `limit` never caps output: `docs("GANECOS", limit=1/5/20)` returns count=70 while `filters.limit` echoes 1; fix: `entries[:limit]` after `_merge` (keep `max(limit,20)` only as a fetch cap).
4. `lookups_docs.py:866` — `_ar_passages` filters `(isin IN (…) OR upper(symbol) IN (…))`, so EXPLAIN = `SCAN ar_facts`; 12 s timeout is swallowed and `doc_find(doc_type="ar")` silently returns only chunk hits; fix: query `isin IN (…)` only (uses `ar_facts_isin`).
5. `lookups_docs.py:133-135` — `_query` swallows `DataError`/timeouts returning `[]`, so partial answers look complete; fix: collect a `warnings`/`partial: true` flag in every result.
6. `lookups_docs.py:341-347` and `:381` — `COALESCE(...)`/`cast(SCRIP_CD as text)` defeat indexes → `docs()` 12.1 s and announcement `doc_find` 10.3 s (>5 s budget), incl. a 4.9 s scan of 1.95M `ann` rows; fix: filter the real date/symbol columns (or use `truth_duckdb.docs`) and bound the BSE store.
7. `lookups_docs.py:927` — `if out: continue` after one deck matches: all older decks skip the stored-extraction fallback; fix: per-deck hit flag.
8. `lookups_docs.py:854` — `"chunk_index": None` always (dead field); fix: select and return `chunk_index`, or drop the key.
9. `lookups_docs.py:352` — `int(row["id"]) in quarantine` applies ar_facts doc ids to `corporate_documents.id` (id 92565 collides today, same filing — latent wrong-company drop); fix: apply only the ar_facts key set to ar_docs.
10. `lookups_docs.py:494-514` — a failed 7–31 s Drive fetch with stored text reports `fetched:false` and no `fetch_note`; fix: always surface `fetch_note` when a fetch was attempted.


## Manager decisions
- D4/D6: if a store has no usable index for the filter, query `truth_duckdb.docs` / `ar_docs` / `cc_docs` (DuckDB) for
  the document list instead, and only open the SQLite store by its primary key. Measure each tool warm on 5 companies
  and report the times; any store still > 2 s is skipped with `warnings: ["<store> skipped: no index on <col>"]`.
- D5: every result gets `warnings: []` and `partial: bool`; a timed-out store sets `partial: true` and names the store.
- Tests must write only under the worktree's `.tmp/` (use `tempfile.mkdtemp(dir=...)` from `TMP`) so they run in the sandbox.

## Acceptance checks
1. `python -m unittest discover -s plugins/reality-data/tests -p "test_lookups_docs.py"` → all pass (new regressions included).
2. Live: `doc_find("SAILIFE", "facility")` (no doc_type) → passages, no AttributeError; `docs("INDIAGLYCO", "deck", "2026-09-02", "2026-09-02")` → 4 decks;
   `docs("GANECOS", limit=5)` → 5 entries; `docs("GANECOS")` warm ≤ 5 s.
3. The brief's original live checks (L2_DOC_LOOKUPS.md AC2) still give the same answers.
4. `git diff --stat` touches only the files above.

## Test command(s)
```bash
python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"
```

## Budget
≤ 10 tool calls before the first edit; ≤ 70 total; ≤ 60 min; $0 paid.

## Report format
1. What changed per defect  2. Verified (counts, live answers, warm timings)  3. Outside-sandbox steps  4. Open problems  5. Tool calls before first edit / total.
