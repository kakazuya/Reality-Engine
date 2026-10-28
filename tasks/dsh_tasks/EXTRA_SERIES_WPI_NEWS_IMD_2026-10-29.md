# Task — input-cost series Shivam asked for: WPI item indices, weekly news price points (India HRC steel, Baltic Dry), IMD rainfall

## Goal
Shivam ruled (2026-10-29) that weekly or monthly is enough, with no paid sources. Up to 52 of the 1,073 master-bank cases touch these inputs: steel 31, freight 12, rainfall 4, pet coke 3, soda ash 2, ammonia 1. Global commodity series are already held (`D:\RealityEngine\raw\commodity_series\commodity_series.csv`: 22 series from the World Bank and FRED).

## Do
1. **`reality_engine/scripts/fetch_wpi_items.py`:** the Office of the Economic Adviser's WPI item-level indices, monthly, 2019 → today.
   - Items: HRC and other steel products, pet coke, soda ash, ammonia, urea, coal, cement, aluminium, copper, cotton yarn, plastics, and the major inputs the bank names.
   - known_at = the release date (WPI comes out on about the 14th of the following month; revisions are kept as separate vintages).
2. **`reality_engine/scripts/extract_news_prices.py`:** weekly price points for **India HRC steel (₹/t)** and the **Baltic Dry Index** from free public news pages. Use the RSS/sitemaps of ET, Business Standard, Mint and Moneycontrol.
   - Extract only: value, unit, date of the price, publication time (= known_at), source URL, and a quote of ≤15 words.
   - **Never store article text beyond the quote.**
   - Extraction must be deterministic regex first. A DeepSeek pass is only for the residue; skip it if unavailable.
3. **`reality_engine/scripts/fetch_imd_rainfall.py`:** IMD weekly state-level rainfall departure % from the public weekly bulletins (PDF/HTML), June–September each year, 2019+.
4. **Tests:** offline, with fixtures, in `reality_engine/tests/test_extra_series.py`. A dry run prints the request counts.

## Rules
- **No network in this task** (the controller runs the fetches). No logins, no paywalled pages, no captcha bypass. Read-only DBs. Write only in this worktree. No commits.

## Acceptance checks
`python -m unittest reality_engine.tests.test_extra_series` passes. The report gives the URL patterns, the commands and the request estimates.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_extra_series
```

## Report
Give:
- the sources;
- the item list;
- the commands;
- the estimates;
- your tool-call count.
