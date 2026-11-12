Ticket: T-201

Goal: one command that answers "what does this branch change in the stores?" before a merge, so nobody rebuilds
store copies by hand again. It copies a store, builds the named parts once with main's code and once with a branch's
code from the SAME starting copy, diffs every touched table, and fails when the branch loses a row a gate marks as
right. General for every store and table; no company literal.

Evidence (12 Nov, T-192 review): Opus rebuilt pilot10 three times by hand (copy, `build --part` per side, ad-hoc SQL
diffs) and found what the worker's own report missed: round 3 crashed `--part ratios` (`no such column: count_basis`);
round 3 hid 6 group guidance targets, round 4 hid 4 more (rows still in the table, only a column changed, so plain row
counts did not show it); round 4 relabelled 113 KPI rows' periods (FY26 -> Q4FY26 etc.), half of them wrong. A row-count
diff misses all three kinds; a keyed diff with "what the serving tool would return" catches them.

Method:
1. New module `reality_engine/scripts/store_diff.py`, CLI:
   `python -m reality_engine.scripts.store_diff --store <db> --profile <json> --parts transcripts,kpi,guidance,ratios
   --base main --head <branch|worktree path> --out <dir>`.
   - Copy recipe for each side: checkpoint the source, copy into `<out>/base.db` and `<out>/head.db`,
     `PRAGMA journal_mode=DELETE`. Never write the source store.
   - Build each side with that side's code: run `python -m reality_engine.pilot3.build ...` with `cwd` = a checkout of that
     ref (use `git worktree add --detach <tmp> <ref>` for a ref; reuse a given worktree path; remove temp worktrees
     after). Hidden subprocesses only (CREATE_NO_WINDOW on Windows; no shell). Record each part's exit code and seconds;
     a non-zero exit on either side is a finding, not a crash of the tool.
2. Keyed diff per table: a key spec per table in one dict (e.g. kpi_series: symbol, metric, dimension, value rounded,
   doc_key, page -> compare fiscal_period; guidance: symbol, metric, target_period, low, high, doc_key, page -> compare
   entity, served?; ratio_panel: symbol, metric, fiscal_period, basis -> compare value; transcript_statement: doc_key,
   page, seq -> compare call_period; share_capital, row_check: sensible keys). Unknown tables fall back to full-row
   hashing. Report per table and per symbol: removed, added, changed-by-column, and "no longer served" (guidance rows
   that the lookup's filter would now hide, quarantined check rows).
3. Gates (exit code 1 when hit): any build part fails on head but not on base; any row in a "known right" list is lost
   or changed (`--golden <csv>`: table, key columns, expected value; optional); any table's removed+changed share above
   `--max-churn` (default 2%) in a store other than the one named by `--target`.
4. Output `<out>/STORE_DIFF.md` (counts, gates, 10 sampled changed rows per table with quote/page when the table has
   them) and `<out>/store_diff.json`.
5. Hook into the merge recipe: document the command in `docs/DEVELOPER_GUIDE.md` (merge recipe) and in the dsh brief
   template, so a worker's branch is diffed by Opus with one command.

Files: `reality_engine/scripts/store_diff.py` (new), `reality_engine/tests/test_store_diff.py` (new; build two tiny fixture
stores with sqlite in a temp dir and diff them directly through the diff function: removed/added/period-changed, the
"no longer served" guidance case, a failing-part case via a fake builder callable; no real store, no git in unit
tests), docs `docs/DEVELOPER_GUIDE.md`, `tasks/STATE.md` one line.

Accept: `python -m pytest reality_engine/tests/test_store_diff.py -q` passes; one real run on a COPY of
`D:/RealityEngine/pilot10/pilot10.db` with `--base main --head main --parts guidance` reports zero changes (sanity) and
its seconds; `test_pilot3_no_company_literals.py` passes.

Stop if: a real run would write a live store; a build part needs network or a model (stop and report).

Budget: 3 hours, DeepSeek off-peak. Do not touch `plugins/reality-data/server/*` (T-197 and T-203 work there). Do not
commit PROGRESS_NOTES.md. Tests one file per process with `--basetemp=.tmp/pt<n>`.
