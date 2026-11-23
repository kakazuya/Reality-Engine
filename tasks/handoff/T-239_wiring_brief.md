# T-239 wiring brief: serve hy4 observations and T-231 events from the 91 stores through the MCP

Ticket: T-239 (Shivam 23 Nov 2026: "go ahead with T-239"). Reviewer: Wolf (Opus).

Goal: the T-238 hy4 reads sit in separate DBs the answer tools never see. Load them into each of the 91 Telegram
stores as new tables and make the pilot3 tools return them, so trial 2 (200 frozen questions) can test them.

Evidence (all read-only):
- Observation DBs, table `observation` (same columns in all three; `record_type` number/statement/guidance;
  `status` verified/unverified/quarantined; `doc_key`, `page`, `known_at`, `measure`, `period`, `basis`, `unit`,
  `scale`, `value`, `value_high`, `statement`, `speaker`, `direction`, `question_context`, `segment`, `geography`,
  `customer`, `entity_scope`, `status_reason`):
  - decks `D:/RealityEngine/t230/obs_91_j.db` (61 companies; 132,455 verified, 71,047 unverified, 215 quarantined)
  - annual reports `D:/RealityEngine/t230/obs_ar_91_m.db` (88 companies; 111,745 / 341,960 / 5,388)
  - transcripts `D:/RealityEngine/t238/obs_transcripts_91o.db` (54 companies; 49,510 / 28,542 / 1,397)
  - each has `measure_dict` (id, name, unit_family, driver_node) and `measure_new` (NEW ids with definitions).
- Events `D:/RealityEngine/t231/events.db` table `event` (604 rows: order wins, capex, fund raises; columns
  event_id, store, symbol, doc_key, kind, status, entity_scope, filing_date, known_at, page, amount_inr_cr,
  customer, execution_months, order_kind, capacity_value, quote, ...).
- Stores: `D:/RealityEngine/tg_build/measure10/cNN/cNN.db` (symbol map: `tg_trial.store_map()` in
  `reality_engine/scripts/tg_trial.py`). Store tables already served: transcript_statement, guidance, kpi_series, doc,
  doc_page (see `docs/PILOT3_BLUEPRINT.md`).
- Tools: `plugins/reality-data/server/lookups_pilot3.py` (3,823 lines; kpi ~745, cells ~930, fin ~1108, statements
  ~1876-2030, guidance ~2198, topic ~2500), `server.py`; `reality_engine/scripts/p3ask.py` mirrors them for workers.

Steps:
1. New `reality_engine/scripts/load_observations.py`: for one store (or `--all` over the 91), copy that symbol's
   verified and unverified rows (never quarantined) from the three DBs into a store table `obs_fact` (all observation
   columns + `source` in {deck, annual_report, transcript} + `doc_type`), and NEW-id definitions into
   `obs_measure_new`; T-231 events into `filing_event` (verified/unverified only). Idempotent: delete rows of that
   source then insert, in one transaction; indexes on (symbol, measure, period), (symbol, record_type, known_at).
   Write a store_repair note (why / problem / missing / fix / next) per the existing `repair` folder convention.
2. Tools: `fact`/`kpi`/`fin` fall back to `obs_fact` number rows when the store's own tables have no row (store
   rows win on a tie), label `status`, `source`, doc + page, period_source/basis_source. `statements` and `topic`
   also return `obs_fact` statement rows (verbatim, speaker, question_context); `guidance` also returns `obs_fact`
   guidance rows. A new `pilot3_obs(symbol, measure|terms, period, record_type, status, as_of, limit)` tool for
   direct search, and `pilot3_events(symbol, kind, as_of)` over `filing_event`. `as_of` drops rows known after it,
   as every other tool. Unverified rows are served labelled, quarantined never. p3ask gets the same two commands.
3. Tests (synthetic store in tmp): load idempotency, quarantined excluded, as_of cut, fallback precedence, statement
   merge, the two new tools. Run per file (memory rule).
4. Dry run on COPIES of 3 stores in this worktree's `.tmp/t239/` (one deck+AR+transcript company, one AR-only, one
   with events): row counts per source and table, size growth, timings of each tool call (< 1 s each).
5. Docs: `docs/PILOT3_BLUEPRINT.md` (tables + tools), the MCP tool listing/instructions text in server.py,
   `docs/DEVELOPER_GUIDE.md` one line.

Files: the loader, lookups_pilot3.py, server.py, p3ask.py, tests, the two docs. Do not edit tasks/STATE.md.

Pitfalls: never write any DB under D:/ or the main checkout (Wolf runs the real load after review); the three
observation DBs are 66-357 MB: read them with `mode=ro` URIs and filter by symbol; the 394-company OCR job writes
`D:/RealityEngine/tg_build/decks403/` - do not touch it; keep existing tool replies unchanged when obs_fact is absent
(old stores must still answer); no model calls.

Accept: tests pass; typecheck clean on changed files; existing pilot3 tests pass; dry-run report under 20 lines with
counts and timings.

Stop if: an existing pilot3 test breaks and the fix would change an existing reply shape.

Budget: about 3 hours.
