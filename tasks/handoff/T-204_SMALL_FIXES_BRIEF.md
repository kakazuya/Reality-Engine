Ticket: T-204

Goal: three small general fixes found on 12 Nov, before the atom build (T-199). No company literal anywhere.

Evidence:
1. `python -m reality_engine.scripts.fetch_pilot60_history --fetch --universe <csv> --out D:/RealityEngine/bluestar/raw/manifest.csv`
   finished (267 ok) but never wrote `--out`; `manifest.write_csv()` is called with the default `MANIFEST_CSV`
   (`D:/RealityEngine/raw/pilot60_history/manifest.csv`, shared by every company), so the next step
   `reality_engine.pilot3.docs_collect` failed with `FileNotFoundError: ...\bluestar\raw\manifest.csv`.
2. `pilot3_topic symbol=KEC topic="order book" limit=2` on pilot10 returned ~15 kB: 2 items shown but `coverage.documents`
   listed 40 documents plus `hidden_documents` twice (once in `coverage`, once at the top level). A cheap model pays for
   that on every call.
3. Same reply: `coverage.searched` lists "page_cell (table and chart cells)" while `coverage.not_searched` also lists
   "page_cell" (the pilot10 store has no `page_cell` table). A source must be in exactly one list.

Method:
1. `reality_engine/scripts/fetch_pilot60_history.py`: when `--out` is given, write the manifest rows for the run's
   universe ISINs to `--out` (same columns as the shared CSV) in addition to the shared CSV; test with a fixture
   manifest (no network).
2. `plugins/reality-data/server/lookups_pilot3.py` coverage (T-197 helpers `_coverage` / `_documents_index` / `_shrink`):
   `coverage.documents` lists at most `max(limit*3, 10)` documents by default, the rest summed in `summarised_documents`
   (already exists) and counted in `documents_not_listed`; a new `documents=all` argument (topic, statements, search,
   semantic, cells, docs) returns the full list; `hidden_documents` appears once (inside `coverage` only). Keep the
   honest scope line unchanged. Update the T-197 tests that assume the old lengths; add a size test: a fixture theme
   with 60 documents at limit=2 stays under 6 kB.
3. A source the store lacks (no table) goes only to `not_searched`; test on a fixture store without `page_cell`.
4. Docs: `plugins/reality-data/README.md` (T-197 paragraph: default document list size, `documents=all`),
   `docs/DEVELOPER_GUIDE.md` one line, `tasks/handoff/T-189_AUROPHARMA_PLAN.md` step 1 (remove the workaround note once fixed).

Files: as named above; tests `plugins/reality-data/tests/test_lookups_pilot3.py`, a new
`reality_engine/tests/test_fetch_manifest_out.py`.

Accept: `python -m pytest plugins/reality-data/tests/test_lookups_pilot3.py -q`, the new test file,
`reality_engine/tests/test_pilot3_no_company_literals.py`, `plugins/reality-data/tests/test_store_routing.py` pass one file
per process (`--basetemp=.tmp/pt<n>`); a real `p3ask topic symbol=KEC topic="order book" limit=2 as_of=2026-10-19`
(read-only; routing finds pilot10) is under 6 kB and still names how many documents were not listed.

Stop if: a change needs a company literal or a reply loses the scope line.

Budget: 1.5 hours, DeepSeek off-peak. Never write live stores. Do not commit PROGRESS_NOTES.md.
