# T-114: three pilot3 test files that drifted from the code

Ticket: T-114

Goal: the three files pass, by bringing each test in line with the code's current, documented behaviour (or fixing the
code if the test shows a real regression). Decide per case from git history, not by guessing.

Files (only these): `reality_engine/tests/test_pilot3_ocr.py`, `reality_engine/tests/test_pilot3_no_company_literals.py`,
`reality_engine/tests/test_pilot3_profile.py`; the code under test only if step 2 shows a real regression
(`reality_engine/pilot3/registry.py`, `reality_engine/pilot3/docs_collect.py`); `docs/DEVELOPER_GUIDE.md` test counts if
they change.

Evidence (Opus, 8 Nov, on main):
- `test_pilot3_ocr.py:164` `test_build_pages_fills_doc_page_from_the_ocr_db_and_fts`: AttributeError: module
  `reality_engine.pilot3.registry` has no attribute `PAGES_DB` (the test monkeypatches it; the path now comes from
  `profile.pages_db()` presumably). 1 failed, 4 passed.
- `test_pilot3_no_company_literals.py:136` `test_a_company_manifest_folder_is_never_another_companys`:
  TypeError: `_company_manifest()` missing 1 required positional argument: 'store'. 1 failed, 6 passed.
- `test_pilot3_profile.py`: 1 failing test in the MARUTI docs_collect -> build chain (asserts `{d[1] for d in docs} ==
  {"deck","transcript"}`, doc counts, key "MARUTI/investor_presentation/1001.pdf"); run it to see which assert fails.

Steps:
1. Run each file alone: `python -m pytest reality_engine/tests/<file> -q -x`.
2. For each failure: `git log -L` / `git log -S` on the symbol (`PAGES_DB`, `_company_manifest`, the failing assert's
   subject) to find the commit that changed it and its message; decide test drift vs regression. Write that decision in
   your answer with the commit id.
3. Fix: keep each test's intent (what behaviour it guards); patch the setup to the new interface. A regression in code
   gets the smallest fix and a note.
4. Run each file alone again; then `python -m pytest reality_engine/tests/test_pilot3_lookups.py -q` (neighbour).

Accept: all three files pass, each run alone. Final answer starts with `Docs updated:` (or `Docs updated: none needed`
with the reason).
Limits: no db writes outside tmp_path; one test file per process; no new dependencies.
Budget: 50 tool calls, 45 minutes.
Stop if: a failure needs a real database or network; report it and stop.
