# Task G3 — point-in-time theme universes that stay current, and resolving ETFs/MFs

## Goal
1. `resolve` and `resolve_one` also return ETFs and mutual funds.
2. A new read-only tool, `universe(theme, as_of=None)`, returns the companies in a theme on a date, each with its
   weight and evidence.
3. A builder job keeps the membership table current from the data itself.

## Why
- `resolve("543437")` returns nothing today. The code is MONQ50, Motilal Oswal Nasdaq Q 50 ETF, ISIN INF247L01AU3.
- Reasoning questions name themes, not companies: "gold stocks", "OMCs", "listed HFCs", "dairy", "data-centre
  players".
- Shivam's rule: a fixed list goes stale every quarter. Companies pivot into a new sector, buy a subsidiary in it, or
  watch a new segment become their main revenue driver. Membership must follow that, and stay point-in-time so a
  question about an older date sees that date's universe.

## Files to touch
- `plugins/reality-data/server/core.py`: extend `resolve` (~line 393) and `resolve_one` (~line 462) with ETF/MF
  matches from `etf_master`, `bse_master` INF* codes and `fund_nav`. Each match gets `kind: equity|etf|mf`.
- New: `plugins/reality-data/server/universe.py`, the `universe` tool.
- `plugins/reality-data/server/server.py`: register the tool in one block delimited by
  `# --- lookups: universe ---` / `# --- end lookups: universe ---`. Insert it directly before the
  `# --- lookups: docs ---` block. Touch nothing else in server.py.
- New: `reality_engine/scripts/build_universe_membership.py`.
  - Writes `equity_intelligence.db:universe_membership(theme, isin, valid_from, valid_to, weight, method,
    evidence_id, evidence_quote, built_at)`.
  - Writes one diff per run to `universe_membership_runs(run_id, built_at, joins, exits, pivots, report_json)`.
  - Ships with a `--db` option for temp copies.
- New: `plugins/reality-data/server/universes.yaml`. Per theme it holds:
  - keywords for segment names and statements;
  - NSE industry codes;
  - optional curated seeds, each with a reason.
  - Start with at least: gold_jewellery_finance, omc_refining, housing_finance, dairy, data_centres, defence,
    specialty_chemicals, textiles_exporters.
- New tests: `plugins/reality-data/tests/test_universe.py`, `reality_engine/tests/test_universe_builder.py`.
- Do not touch: `lookups_docs.py`, `lookups_market.py`, `search_docs.py`.

## Membership rules (builder)
A company joins a theme, from the date the evidence became known, on any of these signals:
- **segment:** an XBRL segment (`results_xbrl.db` facts) or a deck/AR segment matches the theme.
  `weight` = that segment's share of revenue.
- **subsidiary:** a BSE announcement of a subsidiary, acquisition or JV in the theme (`bse_announcements.db:ann`).
- **stated_pivot:** a concall or deck statement of entering the theme (`concall_facts.db:cc_items_fts`).
- **industry:** NSE industry classification. **curated:** a seed in `universes.yaml`.

Further rules:
- A company exits when its segment drops to 0 or disappears for 2 consecutive quarters.
- `pivot = true` when the theme's segment becomes the company's largest by revenue.
- Every row cites `evidence_id` (`db.table:key`) and a short quote or value.

## Tool contract
`universe(theme, as_of=None, min_weight=0)`:
- Returns members valid on `as_of`, sorted by weight. Each row has: symbol, ISIN, weight, method, since, evidence_id,
  pivot.
- Also returns `stale_days`, the age of the last build.
- If the theme is unknown, it returns the closest themes.

## Steps
1. Read the `core.py` resolve code and the segment fact layout. Sample with `python -m reality_engine.toolbelt.sample_rows --help`.
2. Implement resolve, then the builder against a temp copy of `equity_intelligence.db`, then the tool and the tests.
3. Dry-run the builder on a temp copy and print the members of omc_refining, housing_finance, dairy and data_centres,
   with their evidence.

## Acceptance checks
1. `python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"` and the new builder test pass.
2. `resolve("543437")` returns MONQ50 with `kind: etf`. `resolve("MONQ50")` matches too.
3. The dry run shows IOC, BPCL and HPCL in omc_refining, and PARAGMILK in dairy, each with evidence.
4. A fixture where a company's new segment becomes its largest shows a join plus `pivot = true` from the right date.
5. No live DB written.

## Test command(s)
```bash
python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"
```

## Budget
≤ 20 tool calls before the first edit; ≤ 110 total; $0 paid.

## Report format
1. What changed  2. Dry-run members (trimmed)  3. jobs.yaml entry for the builder (text only; Claude adds it)  4. Open problems  5. Tool calls before first edit / total.
