Ticket: T-199

Goal: one row per printed figure of every table/chart page (`page_atom`), read by Haiku subagent sessions from the
page image + text layer, independently checked, and served by the reality-data tools beside the existing tables.
Plan and why: `tasks/handoff/T-199_BLUESTAR_ATOM_PLAN.md` section 1 and step 6. No company literal anywhere.

Evidence (T-196, `reports/2026-11-12_why_answers_stop.html`): on Aurobindo ~1,850 of 2,134 table/chart pages were
never read into figures, so answers that needed a deck or results-table figure stopped at raw text. The pieces exist:
`v2/page_route.py` routes pages, `v2/page_reader.py` turns a GRID reply into position-checked `page_cell` rows
(`rg.settle_page`, digit check -> quarantined), `reference_pages.GRID_PROMPT` / `parse_grid` / `_page_image_b64`,
`pilot3/row_checks.py` has `period_key`, `header_cells`, `unit_scales`, `definition_key`, and
`plugins/reality-data/server/lookups_pilot3.py::cells` already serves `page_cell`. What is missing: (a) a way for a
reader that is NOT an HTTP model (a Claude Code Haiku subagent writing files) to feed `read_page`; (b) resolved
period / basis / unit / scale / numeric value per cell; (c) the tools reading that.

Method (numbered; do them in order, commit after each):
1. `page_reader.py export --store S [--ocr-db D] --routes CSV --out DIR [--batch 8]`: for every `table_or_chart` page,
   write `DIR/b<NNN>/<stem>.jpg` (the `_page_image_b64` render) and `DIR/b<NNN>/<stem>.prompt.txt`
   (`GRID_PROMPT + LAYOUT_NOTE + layout + ">>>"`, exactly what `read_page` would send), 8 pages per batch folder, and
   `DIR/manifest.csv` (batch, stem, doc_key, page, doc_type, known_at). Stem rule = `page_route._export_page`'s.
2. Reply-file reader: `--reader file:<DIR>` makes `_call` return the text of `DIR/b*/<stem>.reply.txt` (missing file
   -> `error: no reply`, status `error`, never a guess); everything after the call (parse_grid, settle_page, second
   pass skipped for file readers, digit check, statuses) is unchanged. `reader` column stores `haiku_sub`.
   `--into-store` writes `page_read` / `page_cell` into the store as today.
3. Migration v10 in `pilot3/schema.py` (T-202 pattern; additive, idempotent): table `page_atom(symbol, isin, doc_key,
   doc_type, page, known_at, table_title, row_label, col_header, period, basis, unit, scale, value REAL, value_text,
   definition, x0, y0, x1, y1, reader, check_status, check_reasons, created_at)`, indexes on (symbol, period),
   (symbol, doc_key, page). Update the T-202 schema tests and `docs/` schema list.
4. `pilot3/atoms.py` (`python -m reality_engine.pilot3.atoms --store S`, also a build `--part atoms` after `checks`):
   one `page_atom` per non-quarantined `page_cell` with a value, resolved by script only:
   - period: `row_checks.period_key` on col_header, then table_title, then the page's printed header line; a
     relative header ("Current quarter", "Q2", "H1") resolves only against a fiscal year printed on the same page;
     unresolved -> period '' and reason `period_unresolved`.
   - basis: consolidated / standalone from table_title, then the page text (one of them printed alone); else ''.
   - unit + scale: from unit_text, else the page's single scale declaration (`unit_scales`, `check_page_unit` logic);
     '%' / x / days / count kept as unit with scale 1; two different declarations on the page -> unresolved.
   - value: parse value_text ("(1,234)" negative, "-" none, "12.3%" -> 12.3 with unit %); no parse -> no atom.
   - definition: `row_checks.definition_key(row_label)`.
   - check_status: `verified` only when the cell is position-verified AND period and unit resolved; anything else
     `unverified` with check_reasons listing what is missing. Same document, same row_label+period+basis, two
     different values -> both `unverified`, reason `same_doc_conflict`.
5. Tools (`plugins/reality-data/server/lookups_pilot3.py`): `cells` reads `page_atom` when the store has it (resolved
   period/basis/unit/value in each row, period filter on the resolved column, `page_cell` fallback otherwise);
   `fact` and `kpi`: when the existing tables return nothing for the asked metric + period, look for atoms whose
   row_label matches the metric's labels (the vocab `fact`/`kpi` already use), served as `source: page_atom` with
   doc + page, the company's printed figure; the T-197 coverage block names `page_atom` in searched / not_searched
   (exactly one list). `topic` lists atoms on the theme's pages. Verified first, unverified labelled, never quarantined.
6. Docs: `docs/PILOT3_BLUEPRINT.md` (atom section: table, readers, resolution rules, statuses), `plugins/reality-data/
   README.md` (cells/fact/kpi paragraph), `docs/DEVELOPER_GUIDE.md` (export -> Haiku -> file reader -> atoms commands).

Files: `reality_engine/v2/page_reader.py`, `reality_engine/pilot3/schema.py`, new `reality_engine/pilot3/atoms.py`,
`reality_engine/pilot3/build.py` (part `atoms`), `plugins/reality-data/server/lookups_pilot3.py`, the docs in step 6,
tests `reality_engine/tests/test_v2_page_reader.py`, new `reality_engine/tests/test_pilot3_atoms.py`,
`plugins/reality-data/tests/test_lookups_pilot3.py`, the T-202 schema test.

Tests (fixtures only, no network, no live store): export writes 8-page batches with prompt == read_page's prompt;
file reader on a fixture reply gives the same page_cell rows as the same text through a fake model; missing reply ->
error row; atoms: period from header, relative header with and without a printed year, page scale declaration,
conflicting declarations, parenthesis negative, same-doc conflict; migration v9 -> v10 on a fixture store and twice
idempotent; `cells`/`fact` on a fixture store with and without `page_atom`; `test_pilot3_no_company_literals.py`.

Accept: each new/changed test file passes one file per process (`--basetemp=.tmp/pt<n>`), plus
`plugins/reality-data/tests/test_lookups_pilot3.py`, `plugins/reality-data/tests/test_store_routing.py`,
`reality_engine/tests/test_v2_page_reader.py`, the T-202 schema test; `doc_gate` clean.

Pitfalls: never call a model from this code (Haiku runs outside it); never write `D:/RealityEngine/*` stores; a
resolution guess is worse than '' (unsure = unverified, never verified); keep `page_cell` as is (other stores use it);
do not open `D:/RealityEngine/bluestar/questions/`.

Stop if: a step needs a company literal, or the file reader would need to change parse/settle behaviour.

Budget: 3 hours, DeepSeek off-peak, max effort. Do not commit PROGRESS_NOTES.md.
