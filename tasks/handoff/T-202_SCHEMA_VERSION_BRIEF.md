Ticket: T-202

Goal: every pilot3 store knows its schema version; schema changes are numbered migrations applied in order by one
function; every build part and every reality-data lookup works on a store of any older version (migrate on write,
tolerate on read) and says clearly when a store is too old for a feature. No more piecemeal `ensure_columns` calls
scattered across build parts. General for all stores.

Evidence (12 Nov): T-192 added `share_capital.count_basis` and `guidance.entity/entity_unsure` through
`schema.ensure_columns` calls inside individual build parts (`stores.py` added it; `ratios.py` read it without adding it).
Result: `build --part ratios` crashed on the pilot10 copy (`sqlite3.OperationalError: no such column: count_basis`),
and after a reality-data restart `pilot3_holding` would have failed on all six live stores. The fix was ad hoc
(`_has_column` checks in lookups). The atom table (T-199) and T-197's event columns are next, so this must be settled
first.

Method:
1. `reality_engine/pilot3/schema.py`: add table `schema_meta(key TEXT PRIMARY KEY, value TEXT)` holding
   `schema_version` and `migrated_at`; a `MIGRATIONS` list of `(version:int, name:str, fn)` where each fn is idempotent
   and additive (CREATE TABLE IF NOT EXISTS / ADD COLUMN when absent / CREATE INDEX IF NOT EXISTS; never drop or
   rewrite data); `migrate(conn) -> (from_version, to_version)` applies the missing ones in order inside a transaction
   and records the version; `version(conn)` reads it (a store with no `schema_meta` is version 0).
2. Fold every existing addition into numbered migrations: `SHARE_CAPITAL_ADDITIONS`, `GUIDANCE_ADDITIONS`,
   `TRANSCRIPT_STATEMENT_ADDITIONS`, the `row_check.definition` column, the `event` table, views and indexes created by
   `ensure_*`. Replace the scattered `ensure_columns` / `ensure` calls in build parts (`stores.py`, `ratios.py`,
   `guidance.py`, `transcripts.py`, `events.py`, `row_checks.py` output, `build.py`) with one `schema.migrate(conn)` call at
   the start of every `build --part` run (in `build.py`). Keep `ensure_columns` as a thin helper used only inside
   migrations.
3. Read side (`plugins/reality-data/server/lookups_pilot3.py`): read-only connections never migrate. Add one helper
   `store_version()` cached per connection, and replace the ad hoc `_has_column`/`_columns` checks with version checks
   where a feature needs a column (fall back exactly as now when the store is older). Every tool reply's provenance
   carries `schema_version`. Coordinate: T-197 is editing lookups_pilot3 (topic/statements/search/docs/cells); touch only
   `connect`/provenance helpers and the `_has_column` call sites, keep diffs small.
4. CLI: `python -m reality_engine.pilot3.schema --db <copy> --migrate|--status` prints the version and pending migrations.
5. Docs: `docs/PILOT3_BLUEPRINT.md` schema section (version table, how to add a migration: next number, additive,
   idempotent, test), `docs/DB_BUILD_GUIDELINES.md` one rule, `docs/DEVELOPER_GUIDE.md`.

Files: `reality_engine/pilot3/schema.py`, `reality_engine/pilot3/build.py`, the build parts named above,
`plugins/reality-data/server/lookups_pilot3.py` (helpers only), tests `reality_engine/tests/test_pilot3_schema_version.py`
(new: version 0 store with the old 18-column share_capital and no guidance.entity migrates to latest; migrate twice is a
no-op; data rows unchanged; a read-only lookup on a version-0 fixture still answers holding and guidance), plus the
existing `test_pilot3_ratios.py`, `test_pilot3_preferred.py`, `test_pilot3_guidance.py`, `test_lookups_pilot3.py`.

Accept: all those tests pass one file per process (`--basetemp=.tmp/pt<n>`); on COPIES of
`D:/RealityEngine/{pilot10/pilot10.db,aurobindo/aurobindo.db,u8/u8.db}` (copy recipe: checkpoint, copy into `.tmp`,
`PRAGMA journal_mode=DELETE`) `--migrate` runs, row counts of every table are identical before/after, and `--status`
shows the latest version; `test_pilot3_no_company_literals.py` passes.

Stop if: a migration would need to rewrite or drop data (report); the change set in lookups_pilot3 grows beyond the
helpers (coordinate instead).

Budget: 3 hours, DeepSeek off-peak. Never write live stores. Do not commit PROGRESS_NOTES.md.
