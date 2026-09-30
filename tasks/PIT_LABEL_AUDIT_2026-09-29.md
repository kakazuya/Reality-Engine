# Point-in-time label audit — live DB, read-only, 2026-09-29

All figures queried today from `equity_intelligence.db` (mode=ro). Chunk figures are three 10k-row chunk_id windows (start, middle, end), not a full scan.

| Data | Has a PIT ("known as of") date? | Finding |
|---|---|---|
| Prices `daily_price_delivery` | YES | 2021-10-27 to 2026-09-24, 1,269 sessions. `prev_close` is the only split adjustment (corporate_actions starts 2023-01-02). |
| Quarterly financials | NO | Only `quarter_end_date`; `created_at` is fetch time (yfinance 2026-08/09, BSE 2026-09-20). 18 distinct quarters with holes (no 2023 at all, none for 2021-12, 2022-03, 2022-06, 2024-09). N200: 12/200 have 4 consecutive quarters 2025-03 to 2025-12. YoY revenue growth is 0.0 on 43% of rows, YoY PAT growth on 87%. |
| Annual financials | NO | `fiscal_year` only. ROCE null/0 on 94%, revenue null 16%. |
| Concall/AR/PPT docs (corporate_documents) | PARTIAL, unreliable | `event_date` filled on 100% but `event_source='doc_date'` on all 103,631 rows. CONCALL doc_date all in 2026 (2026-05-11 to 08-29); 11,273/18,516 equal the crawl date. ANNUAL_REPORT dates span 2 days (08-28/29). |
| Chunks (2.03M) | event_date yes, meaningless | event_date 100%, copied from the doc date. fiscal_period 21-45%, fiscal_source NONE ~49%. `industry_id` and `sector_id` 0% in all 3 windows. |
| Master company labels | Snapshot only | N200: industry/sector 0 of 200 missing (18 industries, NSE-style). Whole master: 5,945/6,445 sector NULL/Other/General Diversified. `is_nifty200` etc. is today's flag, no membership history (survivorship). |
| Business model, moat, policy exposure, geographic | NO | `updated_at` / `eval_date` / `last_updated_date` = when generated (Aug-Sep 2026). Moat history 2 dates, policy history 1. geographic_exposure: USA rows 37, CHN 24, EU 33 (of 3,568). |
| Revenue segments, suppliers, customers, order book, market cap series | NOT PRESENT | No table or column. `company_distilled_parameters` has 5 prose-JSON keys, e.g. order_book_metrics (3,474 companies), all stamped Aug-Sep 2026. `company_forensic_health.market_cap_inr_cr` is a single value. |
| Entity edges | NO date | 73.5k edges. supply edges: 2,036 to `theme_supply` nodes on 405 companies, not company-to-company. business_analog edges' shared terms are stopwords ('question', 'moderator', 'there'). |
| Macro/policy docs | Yes for 2024-2025 | Budget/Survey/RBI/PIB: about 30 docs total. |

## Verdict
The DB has good price history (2021-10 on) and dated raw text. It has no dated fundamentals or labels. A test that says "what did the market know about company X on date T" can be run on prices and document dates only. Fundamental, exposure and business-model features for past dates are today's values, so using them is look-ahead.

## Repair order (cheapest first)
1. Apply `analysis/proposed_changes.csv` (7,019 rows: true call_date + publication_date from transcript bodies). Not applied yet, needs writer window.
2. Add a `filing_date` for results from the exchange result-announcement date (BSE/NSE, free), stored beside each quarter. Backfill quarters 2021-2026 from BSE XBRL, not yfinance.
3. Add dated tables: `company_segment_revenue`, `company_industry_history`, `index_membership_history`, all keyed (isin, period, first_public_at).
4. Populate chunk `industry_id` from master industry (single UPDATE by symbol, no LLM).
5. Only then label exposures (US revenue share etc.) by reading the dated filings.

## Root cause and recovery decision (2026-09-29 evening)
- Cause: bulk docs (CONCALL/ANNUAL/OTHER, 82k rows) were discovered via Screener links (`discovery_source='screener_discovery'`), never via the BSE/NSE announcement feeds. `fundamentals_client.py:390` keeps `NEWS_DT[:10]` (time discarded, `datetime.now()` fallback); Screener-found rows got the crawl date.
- Trial, 8 large caps: BSE `AnnSubCategoryGetData` (needs curl_cffi chrome120 impersonation; plain requests get Akamai 403; 50 rows/page; windows over 1 year return empty) matches our stored PDF name exactly. Match rate: CONCALL 115/124, PPT 10/10, RESULT 6/6, ANNOUNCEMENT 60/62, OTHER 183/234, ANNUAL_REPORT 0/93 (different feed).
- DB `doc_date` vs true dissemination date: concalls correct 0.9% (median 858 days late, max 2,418), other filings 1.1%. Every concall-dated result to date is mis-timed.
- PDF text route: 9,539/9,652 concalls extract without OCR (only 77 need it), but only ~11% yield a letter/publication date; the rest give the call date. Useful as tier-2 fallback and cross-check (6/6 exact vs feed), not a source of publication timestamps.
- Decision: A (feed metadata by PDF name) primary, B fallback. Harvester: `analysis/bse_announcement_harvest.py` -> `analysis/bse_announcements.db` (live DB untouched).
