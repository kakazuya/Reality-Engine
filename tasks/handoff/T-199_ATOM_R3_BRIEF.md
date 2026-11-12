Ticket: T-199

Goal: round 3 of the atom pipeline: three defects measured on the Blue Star 20-page Opus truth sample (13 Nov 03:00,
`D:/RealityEngine/bluestar/truth/grades_a.csv`, `grades_b.csv`). Values are right (211/211 on financial pages); what fails is
section, duplicate values and units. General fixes only, no company literal.

Evidence:
1. Section lost (43 of 211 sampled rows ambiguous). Results segment tables print "(a) Electro-mechanical projects..." four
   times, under the headings "Segment Revenue", "Segment Result", "Segment Assets", "Segment Liabilities"; balance sheets print
   "(a) Contract liabilities" under non-current and current. Haiku's reply keeps the heading as a label-only line
   (`Segment Revenue |  |  |`) or as a line with no `|`; `reference_pages.parse_grid` drops label-only rows (no digit) and
   keeps a no-`|` line only as `pending` for the next row's empty label. So page_cell.row_label is "(a) Electro..." with no
   section, atoms then mark 8,822 rows `same_doc_conflict`.
2. Equal values in one row dropped (12 of 18 recall misses on financial pages). When two columns of a row print the same
   figure ("Current ratio | 1.23 | ... | 1.23", "Equity share capital 41.12 | 41.12"), only one cell survives.
   `reference_geom.settle_page` groups records by the page word they were placed on (`placed[rec["at"]]`); `place()` puts
   both cells on the same first matching word, so the second cell is merged away.
3. Unit wrong or missing (61 of 291 sampled rows): the page's "(Rs in crore)" declaration is given to serial numbers, share
   counts, dates, text cells, "2.5 million tonnes", service-call counts; ratios / "(No. of days)" / turnover / voting counts
   and percentages get no unit.

Method:
1. Section: in `parse_grid`, a row whose label has letters and whose fields hold no figure, or a no-`|` line followed by
   rows, starts a section; every following row's cell carries `section` until the next section or TABLE line. `_normalize_row`
   keeps it. `page_reader` writes it into `page_cell.row_label` as `<section> > <label>` ONLY when the label starts with a
   list marker ((a), (b), i., 1., a)) or the same label occurs twice in the table; other labels unchanged (so earlier stores
   and tests keep their labels). atoms.py: the conflict key uses the full label (with section). Tests: a segment table with
   four sections; a balance sheet with the same label under two headings; a table without sections unchanged.
2. Equal values: in `settle_page` / `place`, a word already taken by a cell of a DIFFERENT column of the same row label must
   not take a second cell; the second cell is placed on the next matching word of that line whose x fits its column, else
   kept as a loose unverified cell (never merged away). Test: a row printing 1.23 in two columns keeps both cells, each
   verified when its column fits; the existing reference_geom tests still pass.
3. Units in atoms.resolve_unit: label/header words decide first: `ratio`, `times`, `(x)` -> x; `days`, `no. of days` -> days;
   `%`, `percent`, `margin`, `share of` in the label or the value -> pct; `no.`, `number of`, `count`, `shares`, `votes`,
   `units`, `tonnes`, `towns`, `dealers`, `partners`, `calls`, `countries`, `facilities`, `stores` -> count (keep the word in
   check_reasons as `count_unit=<word>`); `sr`, `s.no`, `sl. no` labels and year-like values (1943) -> no atom. Only a label
   with none of these takes the page's money declaration. A value with a non-money word next to it ("2.5 million tonnes") is
   never inr. Tests for each, built from the examples above.
4. Docs: `docs/PILOT3_BLUEPRINT.md` T-199 block (three rules), `docs/V2_SCHEMA_CONTRACT.md` one line on section labels.

Files: `reality_engine/v2/reference_pages.py`, `reality_engine/v2/reference_geom.py`, `reality_engine/v2/page_reader.py`,
`reality_engine/pilot3/atoms.py`, tests `reality_engine/tests/test_pilot3_atoms.py`, `reality_engine/tests/test_v2_page_reader.py`,
the reference_geom test file, docs above.

Accept: one per process with --basetemp=.tmp/pt<n>: `reality_engine/tests/test_pilot3_atoms.py`,
`reality_engine/tests/test_v2_page_reader.py`, every `reality_engine/tests/test_v2_reference*.py`,
`plugins/reality-data/tests/test_lookups_pilot3.py`, `reality_engine/tests/test_pilot3_no_company_literals.py`.

Stop if: a fix needs a company literal, or an existing reference_geom test must be loosened (report instead).

Budget: 75 minutes, max effort. Never write D:/RealityEngine stores; never open D:/RealityEngine/bluestar/questions/ or
D:/RealityEngine/bluestar/truth/. Do not commit PROGRESS_NOTES.md.
