# T-209: structured layer at universe scale (shareholding categories, pledge, balance-sheet lines), script only

Ticket: T-209

Goal: one universe store `D:/RealityEngine/structured/structured_universe.db` holding, for every NSE company with
filings since 2024-04-01: (a) shareholding by category per filing (promoter, fpi_total, mf, insurance, other DII,
public, government) and promoter shares pledged/encumbered %, from the NSE shareholding XBRL; (b) balance-sheet lines
(total equity, borrowings current + non-current, cash and equivalents, total assets, capital employed derived as
equity + borrowings - cash, labelled derived) from filed results XBRL. Every row: isin, symbol, period end, basis
(consolidated/standalone), value, unit, source file, known_at (exchange dissemination time). These feed the factors
T-207 could not measure (pledge, FPI/MF change, ROE/ROCE; `docs/research/T-207_factor_rewards.md` section 11).
Script only: no model calls.

Evidence (checked by Claude 13 Nov):
- `reality_engine/scripts/fetch_shp_xbrl_pilot.py` already fetches and parses SHP XBRL for any `--universe` CSV
  (isin,symbol) from `equity_intelligence.shp_index` (every NSE SHP filing with its XBRL link), matching on ISIN or
  symbol via `symbol_isin_history`, writing filings/fact/xcheck; raw gz layout `raw_market/nse_shp_xbrl/`. A parsed
  example: `D:/RealityEngine/bluestar/shp_xbrl.db` (tables filings, fact, xcheck). Store-side tables to mirror:
  `shp_category`, `shp_pledge` in `reality_engine/pilot3/schema.py`; FPI sums use fpi_total, never components added.
- Results XBRL: `reality_engine/data/results_xbrl.db` (read-only via `reality_engine.db.readonly.connect_ro`). Measure
  first whether it holds the half-year statement of assets and liabilities lines; if not, find which raw holds them
  (`tasks/DATA_INVENTORY.md`, `docs/RAW_DATA_FAMILIES.md`) and report before fetching anything new.
- Raw files live on Drive (`raw_store`); new fetches go there; NSE tolerated ~400 requests/min bursts on 28 Oct but
  start at a measured lower rate and ramp.

Steps:
1. Measure: count SHP filings since 2024-04-01 in `shp_index` and how many XBRL files are already held locally or on
   Drive; count companies x half-years with balance-sheet lines in results_xbrl. Write the counts to PROGRESS_NOTES.md.
   If the balance-sheet source is not held, do (a) only and report (b)'s gap.
2. New module `reality_engine/structured/universe_build.py` (reuse the pilot fetcher's parser; do not copy it:
   import or move it into a shared function with its tests kept green): fetch missing XBRL (resumable), parse, write
   the universe store with the columns above; idempotent re-runs.
3. Tests `reality_engine/tests/test_structured_universe.py` on two fixture XBRL files (one with pledge, one without)
   and one results fixture; a known-answer check against the Blue Star numbers in `shp_xbrl.db`.
4. Full run. Then a coverage table per quarter (companies with a row / companies with a filing) and a 20-row random
   sample (seed recorded) with the source file and value, for Claude's hand check:
   `D:/RealityEngine/structured/coverage.csv`, `sample20.csv`.
5. Docs: `docs/DEVELOPER_GUIDE.md` block, `tasks/DATA_INVENTORY.md` is generated (run
   `python -m reality_engine.scripts.data_inventory`, never hand-edit), PROGRESS_NOTES.md lines.

Files: `reality_engine/structured/` (new), the pilot fetcher if you extract a shared parser, its tests, the new test
file, `docs/DEVELOPER_GUIDE.md`; data writes only `D:/RealityEngine/structured/` and the raw cache.
Test command(s): python -m pytest reality_engine/tests/test_structured_universe.py reality_engine/tests/test_pilot3_shp_holder.py -q
Accept: tests pass; the store exists with coverage.csv and sample20.csv; typecheck clean on changed files.
Pitfalls: ISINs change on splits (follow `symbol_isin_history`); SHP percentages have a basis (of total shares vs of
promoter holding for pledge) - store it; a revised filing supersedes the earlier one for the same quarter but both
keep their known_at; no unbounded GROUP BY over document_chunks; no pop-up windows (CREATE_NO_WINDOW).
Stop if: the balance-sheet source needs a new exchange endpoint (report, do not build); fetch error rate over 5% for
10 minutes; RAM over 90%; 4 hours.
Budget: 4 hours, 350 tool calls.
