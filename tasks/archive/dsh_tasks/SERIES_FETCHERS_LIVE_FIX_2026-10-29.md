# Task — make the three new input-cost fetchers work live (WPI items, news HRC/BDI, IMD rainfall)

## Goal
The fetchers merged on 29 Oct (`reality_engine/scripts/fetch_wpi_items.py`, `extract_news_prices.py`, `fetch_imd_rainfall.py`, shared `series_common.py`) pass 41 offline tests. Their first live run (01:50 IST, 29 Oct) wrote **0 rows** from all three:
- **WPI:** `GET https://eaindustry.nic.in/` → `SSL: CERTIFICATE_VERIFY_FAILED (unable to get local issuer certificate)`. The government site serves an incomplete chain. Logs: `D:\RealityEngine\raw\wpi_2025.log`.
- **IMD:** `https://mausam.imd.gov.in/imd_latest/contents/rainfall.php` → HTTP 404; `https://www.imd.gov.in/` → connect timeout (WinError 10060). Log: `D:\RealityEngine\raw\imd_links.log`.
- **News `--rss-only`:** 8 feeds OK, 50 items each, 0 HRC/BDI hits. That may be correct (rare topic), but prove it. Log: `D:\RealityEngine\raw\news_prices_rss.log`.

You have network access. Make each fetcher return real rows, and show they are right.

## Do
1. **WPI:**
   - Fix TLS the safe way. Fetch the missing intermediate certificate (the AIA URL in the leaf certificate) and build an `ssl` context with the system store plus that intermediate. Do NOT set `verify=False` or `CERT_NONE`.
   - If OEA's page layout differs from the regexes, update the discovery patterns.
   - Run `--from 2025-01-01`, then the full 2019 window.
   - Hand-check 3 months against the PDF: HRC, cement, coking coal.
2. **IMD:**
   - Find the current live URLs of the weekly rainfall bulletins (state-wise departure %) by browsing from `mausam.imd.gov.in`. Update them. Retry timeouts with backoff.
   - Run `--list-links`, then 2025 Jun–Sep, then 2019+.
   - Hand-check 2 weeks.
3. **News:**
   - Run the sitemap backfill for 2025 only, with `--max-articles 100`.
   - Report hits per outlet, and hand-check 5 HRC and 5 BDI points against the article text (the value, the unit and the date).
   - If yields are near zero, find the reason (the slug patterns or the sitemap structure) and fix it.
4. Add a test fixture for each fix (a TLS context builder test with a fake chain is fine), and keep all the old tests green.

## Rules
- Write outputs only inside this worktree: `.tmp/input_cost_series/`. Use each script's out/raw-root option, or add one if a script lacks it. The controller copies the CSVs to D: afterwards. Use no paid models and make no commits.
- Pace requests at 1 per second per host. Stop a host on 403/429 and report it.

## Acceptance checks
- `python -m unittest reality_engine.tests.test_extra_series reality_engine.tests.test_missing_series_fetchers` passes.
- `wpi_items.csv` has ≥90% of the 2019+ months for the 23 codes. `imd_rainfall.csv` has the monsoon weeks for 2019+, state-level. News rows exist, with hand-checked precision.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_extra_series reality_engine.tests.test_missing_series_fetchers
```

## Report
Give:
- the rows per series and the month/week coverage;
- the hand-check results;
- what you changed and why;
- the requests made and any blocks;
- your tool-call count.
