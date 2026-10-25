# Task L1 — one-call market lookups in reality-data: `delivery`, `price_extreme`, `holding`

## Goal
Three new read-only reality-data MCP tools that each answer one common question shape in **one call**, with
provenance, and say clearly what is missing instead of returning empty rows.

## Why
In a 10-question test (2026-10-25) workers spent ~80 of ~115 tool calls guessing raw SQL; simple lookups took 9–12 min.
The data is there; the routing is not. These tools hard-code the right table, join and preference order.

## Files to touch
- New: `plugins/reality-data/server/lookups_market.py` (all logic here; reuse helpers from `core.py`:
  `resolve_one`, `_identity_isins`, `_identity_symbols`, `_parse_date`, `_run_duck`, `_run_sqlite`, `provenance`, `DataError`).
- `plugins/reality-data/server/server.py`: register the three tools **in one block inserted directly after the
  `facts` tool and before the `search_docs` tool**, delimited by `# --- lookups: market ---` / `# --- end lookups: market ---`.
  Another worker inserts its own block after `sql`; do not touch anything else in server.py, and do not edit the
  server instructions string (the manager writes the routing guide).
- New tests: `plugins/reality-data/tests/test_lookups_market.py`.
- New CLI: `reality_engine/toolbelt/lookup_market.py` (`python -m reality_engine.toolbelt.lookup_market delivery ATHERENERG 2026-04-13 2026-04-14`)
  that calls the same functions and prints JSON, so workers without the MCP get the same answer.
- Do not touch: `core.py` (import from it only), `search_docs.py`, any database.

## Inputs/data (verified sources workers used successfully)
- Prices/delivery: DuckDB snapshot `truth_duckdb` tables `px_nse`, `px_bse` (raw) and `px_nse_adj`, `px_bse_adj`;
  delivery column `deliverable_qty`, `delivery_pct`. NSE keyed by isin/symbol, BSE by isin / `sc_code`.
  Example: Ather Energy = NSE `ATHERENERG`, BSE 544397, ISIN INE0LEZ01016.
- Shareholding: `truth_duckdb.shp_index` (from `equity_intelligence.shp_index`), keys `isin`, `quarter_end`, broadcast time.
- Exact share count: `ar_facts.ar_facts` (annual report; e.g. LUMAXTECH doc 53803 p121 says 6,81,57,705 shares) and
  `results_xbrl.facts` (`PaidUpValueOfEquityShareCapital` / `FaceValueOfEquityShareCapital` — this division gives a
  ROUNDED count, 68,157,500 for LUMAXTECH, which is WRONG as an exact count).
- Read through `connect_ro` / the core.py helpers only. Never a bare `sqlite3.connect`. No writes.

## Tool contracts
1. `delivery(symbol, dates: list[str] | str, end: str | None = None)` — for each date: NSE deliverable qty, BSE
   deliverable qty, sum, traded volume per exchange, delivery % per exchange. Always raw (unadjusted) tables. A date
   with no row on either exchange → `status: "no_trading"` if it is not a trading day market-wide (check whether any
   row exists in px_nse for that date), else `status: "missing_for_symbol"` naming the exchange(s) missing.
2. `price_extreme(symbol, start=None, end=None, kind="high"|"low"|"both", adjusted=False)` — default window = calendar
   YTD of the latest snapshot date. Returns value, date, exchange, and the same for the other exchange; says which
   is the overall extreme. Note the snapshot end date in the answer (data freshness).
3. `holding(symbol, as_of=None)` — promoter %, public %, total shares, from the latest `shp_index` quarter ≤ as_of;
   plus `share_count_candidates`: every share count found (shp_index, ar_facts, xbrl paid-up/face value), each with
   source and date, and a `best_share_count` chosen by: exact integer from a filing text (AR / shareholding pattern)
   over a derived XBRL division; flag `xbrl_rounded: true` when the XBRL-derived figure differs.
- Every tool: resolves NSE symbol, BSE code (numeric string), ISIN or name via `resolve_one`; returns `provenance`;
  on nothing found returns `{"found": false, "checked": [<table + key>...], "hint": "<next best call>"}` — never `[]`.
- Each tool ≤ 2 s on the live data (bounded queries, indexed keys only).

## Steps
1. Read `core.py` helpers you reuse (use `python -m reality_engine.toolbelt.sample_rows` / `coverage_peek` for schemas).
2. Implement + unit tests with small fixtures (mirror how `test_reality_data.py` builds fixtures).
3. Live check against the real data (read-only) for the acceptance questions below.

## Acceptance checks
1. `python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"` → all pass (existing + new).
2. Live, one call each, answers printed in your report:
   - `delivery("Ather Energy", ["2026-04-13","2026-04-14"])` → NSE, BSE, sum per day (or the correct status).
   - `price_extreme("532810")` → 2026 YTD high value + date.
   - `holding("BLACKBUCK", "2026-09-30")` → promoter %.
   - `holding("LUMAXTECH")` → best_share_count 68157705 with xbrl_rounded flagged.
3. `git diff --stat` touches only the files above.

## Test command(s)
```bash
python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"
```

## Budget
≤ 20 tool calls before the first edit; ≤ 90 total; ≤ 60 min; $0 paid.

## Report format
1. What changed  2. Verified (test counts + the 4 live answers verbatim)  3. Outside-sandbox steps  4. Open problems /
data gaps found (table + key)  5. Tool calls before first edit / total.
