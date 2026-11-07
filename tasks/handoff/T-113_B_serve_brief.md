# T-113 B: build the row-check verdicts into the database and serve them (serving worker)

Ticket: T-113

Goal: the pilot3 tools never serve a quarantined `guidance` or `kpi_series` row, and every served row says whether it
is `verified` or `unverified`. The checker itself (`reality_engine/pilot3/row_checks.py`, `row_checks_vocab.yaml`)
belongs to another worker: import it, never edit it. Read `docs/DB_BUILD_GUIDELINES.md` section 13 first.

Files (only these): `reality_engine/pilot3/build.py` (new part `checks`), `plugins/reality-data/server/lookups_pilot3.py`
(`kpi` line 235, `_stated_ratios` line 493, `guidance` line 763), `plugins/reality-data/server/server.py` (tool text of
`pilot3_kpi` line 427 and `pilot3_guidance` line 525 only), new `reality_engine/tests/test_pilot3_row_check_serve.py`,
`docs/PILOT3_BLUEPRINT.md` (one short section), `docs/DB_BUILD_GUIDELINES.md` section 13 (one paragraph on serving).

Evidence:
- `row_checks.run(db, out, profile, tables)` opens `db` read-only and writes tables `row_check(tbl, row_id, symbol,
  metric, canon, sector, doc_type, rule, status, corroborated, checker)` and `row_check_fail(tbl, row_id, check_name,
  hard, why)` into `out`, replacing them. Statuses: verified / unverified / quarantined.
- Dev copy for your runs (yours alone, you may write to it): `D:/RealityEngine/pilot10/scratch/t113_p10_serve.db`
  (pilot10 + guidance v2). Profile `tasks/night_loop/pilot10_profile.json`. Today on it: guidance 34 quarantined of
  106, kpi 372 of 6,043.
- Tool reads: `kpi()` selects `FROM kpi_series k {_DOC_JOIN}`; `_stated_ratios` reads kpi_series for stated ROE etc;
  `guidance()` selects `FROM guidance g LEFT JOIN doc d`.

Steps:
1. build part `checks` (add to the parts list after `guidance` and `notes`, and to `--part` choices): runs
   `row_checks.run` with `out` = a temp file next to the build db, then copies both tables into the build db in one
   transaction (`DROP TABLE IF EXISTS` + `CREATE TABLE AS` / attach). Never hold the checker's read connection open
   while writing. Works on a db without fin tables or without guidance (skip that table).
2. Serving: when the db has `row_check`, `kpi()`, `_stated_ratios()` and `guidance()` LEFT JOIN it
   (`rc.tbl='kpi_series' AND rc.row_id=k.id`), drop `status='quarantined'` unless the new argument
   `include_quarantined=True`, and add `check_status` (verified / unverified / null when unchecked) plus, for
   unverified rows, `check_note` (the soft checks' names) to every returned row. A db without `row_check` behaves
   exactly as today (test it). `{"found": false}` hints must not list a metric whose every row is quarantined.
3. Tool text: one sentence each in `pilot3_kpi` and `pilot3_guidance`: quarantined rows are hidden, `check_status` says
   verified or unverified, prefer verified rows, say "unverified" when quoting an unverified one. Add the
   `include_quarantined` parameter.
4. Tests (`test_pilot3_row_check_serve.py`, tmp fixtures, no real db): build part on a fixture writes both tables;
   kpi / guidance hide a quarantined row, show verified/unverified status; include_quarantined returns it; no
   row_check table = old behaviour; as_of still applies.
5. Run the part on the dev copy and show 3 tool calls before/after: `kpi('BAJFINANCE','nnpa_pct','FY25')` (1.18 is a
   gross NPA figure the checker quarantines), `guidance('HDFCBANK')`, `guidance('SBILIFE')`.
6. Docs as listed. Final answer must start with `Docs updated:`.

Accept: `python -m pytest reality_engine/tests/test_pilot3_row_check_serve.py -q` passes, and the existing
`python -m pytest reality_engine/tests -q -k "pilot3 and (lookup or guidance or kpi)" -m "not slow"` still passes
(run per file if memory climbs; report any failure that also fails on main before your change).

Limits and pitfalls:
- Never write to `D:/RealityEngine/pilot10/pilot10.db` (live) or any db other than the dev copy above.
- `PYTHONIOENCODING=utf-8` for any run that prints quotes.
- No model calls, no new dependencies. Do not touch `row_checks.py` even if you find a bug: report it with the row id.

Budget: 120 tool calls, 2.5 hours.
Stop if: the lookups need a schema change to `kpi_series` or `guidance` tables, or the existing tests fail on main
before your change in a way that blocks you: report and stop.
