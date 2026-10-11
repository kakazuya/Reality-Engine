# Retrieval and labelling gaps (audit 2026-10-12, deferred by Shivam until the AR pipeline is done)

Goal: every stored fact resolves to its stock, its publication time, the indices the stock was in on that date, and
price/delivery data before and after. Measured on equity_intelligence.db and deck_figures.db.

## What is fine
- Deck figures: all 627,251 read pages carry an ISIN and a filing time (208 have a date only).
- corporate_documents: every row has an ISIN.
- document_chunks: every chunk has published_date.

## Gaps, in proposed order

1. **No single point-in-time price/delivery view.** Six tables, three keys:
   | table | key | dates |
   |---|---|---|
   | daily_price_delivery | isin | 2021-10-27 .. 2026-09-24 |
   | mkt_nse_eq_daily | isin | 2019-01-01 .. 2021-10-29 |
   | mkt_bse_eq_daily | isin, sc_code | 2019-01-01 .. 2026-10-09 |
   | mkt_nse_full_daily (OHLC + delivery) | symbol | 2019-06-27 .. 2026-10-09 |
   | mkt_nse_sme_daily | symbol | 2019-01-01 .. 2025-10-10 |
   | mkt_bse_delivery_daily | sc_code | 2019-01-01 .. 2026-10-09 |
   Sample of 400 deck filings, ±10 days: daily_price_delivery alone covers 75%; all sources joined give price for
   93% and delivery for 99.8%. Symbol joins break on renames. There is no ISIN/symbol history map (AGENTS.md notes ISINs
   change on splits and face-value changes).
   Fix: an ISIN/symbol/sc_code history map plus one view `price_delivery_pit(isin, date, ...)` over all sources.

2. **Placeholder ISINs in deck figures.** 47 companies, 54 decks, 1,226 pages, 14,426 final facts carry
   `INE_AUTO_*` ISINs. The trust layer (AGENTS rule 13) hides them, so they are invisible to analysis.
   Fix: resolve the real ISINs (BSE scrip code from the deck path, symbol history) and re-tag pages.

3. **Index membership is not point-in-time.** `index_membership` holds only nifty50, nifty100 and
   niftymidcap150, as one snapshot (as_of 2026-09-30). There are no smallcap, sectoral or BSE indices. Using it on
   past dates brings in survivorship bias.
   Fix: historical constituents as date ranges (NSE monthly constituent files and index-change notices; then BSE).

4. **Missing publication time on some corporate_documents:** OTHER_FILING 8,025, CONCALL_TRANSCRIPT 1,736,
   ANNOUNCEMENT 825, FINANCIAL_RESULT 200, ANNUAL_REPORT 197, OFFER_DOCUMENT all 904. pit_source is recorded only
   for annual reports (other types show 'unknown' even when a timestamp exists).

5. **document_chunks:** 9,176 chunks have no ISIN; 1.63M of 2.05M (80%) have no fiscal_period.

6. **Retrieval test.** Add a sampled check to `coverage_report`: for N facts per source, resolve stock → filing time
   → indices on that date → price/delivery ±k trading days, and report the pass rate. Strategy tests inherit the
   gate (the "data before testing" rule).

Audit scripts were ad-hoc (session scratchpad); rerun the queries above when picking this up.
