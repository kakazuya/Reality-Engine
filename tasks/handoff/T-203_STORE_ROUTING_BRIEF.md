Ticket: T-203

Goal: the reality-data `pilot3_*` tools answer any company held in ANY registered store without editing `.mcp.json`:
each call resolves its symbol to the store that holds it and opens that store read-only. One environment setting can
still pin a single store (tests, A/B runs). General; no company literal.

Evidence (12 Nov): to answer Aurobindo through the MCP, Shivam had to add `REALITY_PILOT3_DB=D:/RealityEngine/aurobindo/aurobindo.db`
to `.mcp.json` and reconnect; that switched the default 3-company store off and, being a committed file, also
switched Wolf's sessions. The next test company (BLUESTARCO, T-199) gets its own store. Stores today:
`reality_engine/data/pilot3/pilot3.db` (3 companies), `D:/RealityEngine/{pilot10/pilot10.db, u8/u8.db, p20/p20new.db,
q12/q12.db, n10/n10.db, aurobindo/aurobindo.db}`; each has a `company` table (symbol, ...).

Method:
1. Registry: `REALITY_PILOT3_STORES` = a path to a small JSON file (default `D:/RealityEngine/stores.json`, generated)
   listing store paths in priority order. A generator `python -m reality_engine.scripts.store_registry --scan
   D:/RealityEngine --out D:/RealityEngine/stores.json` finds `*.db` files whose `company` table exists (skip backups
   matching `*_before_*`, `*_ab*`, `*copy*`, `pages.db`, `*_ocr.db`), and records per store: path, built date, symbols.
2. Resolution (`plugins/reality-data/server/lookups_pilot3.py` + `core.py`): if `REALITY_PILOT3_DB` is set, use only it
   (current behaviour, pins tests and A/B runs). Otherwise `resolve_symbol(symbol)` (already the first call of every
   tool) looks the symbol (or ISIN, BSE code, name, as today) up in the registry and sets a per-call context variable
   (`contextvars.ContextVar`) naming the store; `connect()` / `db_path()` read it; connections are cached per path,
   read-only, thread-safe. A symbol held in several stores: the store listed first in the registry wins; the reply's
   provenance names the store path and says `also_held_in`.
3. `pilot3_sql` and catalog/schema tools: accept an optional `store` argument (path or store name) and otherwise use
   the store of the `symbol` argument if given; without either they list the registered stores instead of guessing.
4. `{"found": false}` / `not_pilot3` replies list which stores were searched.
5. Revert the `.mcp.json` pin (remove `REALITY_PILOT3_DB` there) once routing works, so the default serves every store;
   generate `D:/RealityEngine/stores.json` and set `REALITY_PILOT3_STORES` in `.mcp.json` instead.
6. Coordinate with T-197 (editing topic/statements/search/docs/cells in lookups_pilot3) and T-202 (connection
   helpers): touch only `db_path`, `connect`, `resolve_symbol` and the sql/catalog entry points; keep the diff small.

Files: `plugins/reality-data/server/lookups_pilot3.py` (resolution helpers only), `plugins/reality-data/server/core.py`,
`reality_engine/scripts/store_registry.py` (new), `.mcp.json`, tests `plugins/reality-data/tests/test_store_routing.py`
(new: two fixture stores with different companies, a symbol resolves to its own store, a pinned env var wins, a symbol
in both stores takes the first and reports `also_held_in`, not-found lists stores, sql without symbol lists stores),
existing `test_lookups_pilot3.py`; docs `plugins/reality-data/README.md`, `docs/DEVELOPER_GUIDE.md`.

Accept: new and existing tests pass one file per process (`--basetemp=.tmp/pt<n>`); with `REALITY_PILOT3_STORES` pointing at
a registry of the real stores (read-only), `python -m reality_engine.scripts.p3ask fact symbol=AUROPHARMA metric=revenue
period=FY26` and the same for `KEC` and `BHARTIARTL` each answer from their own store (p3ask must use the same
resolution; show the provenance paths); `test_pilot3_no_company_literals.py` passes.

Stop if: routing needs per-tool changes beyond the shared helpers (report the count); a store cannot be opened read-only.

Budget: 3 hours, DeepSeek off-peak. Never write live stores. Do not commit PROGRESS_NOTES.md.
