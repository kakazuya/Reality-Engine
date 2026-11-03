# Pilot 10 (Shivam, 4 Nov 2026)

Ten companies, one per sector, all distinct. The 95% gate is measured here first; the next test adds one listed
peer per company (20 companies) and applies the same scripts unchanged.

| Symbol | Company | Sector family (`questions/sector_vocab.json`) | Note |
|---|---|---|---|
| KEC | KEC International | epc_capital_goods | from pilot3 |
| BAJFINANCE | Bajaj Finance | nbfc | from pilot3 |
| HINDALCO | Hindalco Industries | metals_nonferrous | from pilot3 |
| HDFCBANK | HDFC Bank | bank | new |
| SBILIFE | SBI Life Insurance | insurance_life | new |
| INFY | Infosys | it_services | new |
| SUNPHARMA | Sun Pharmaceutical | pharma | new |
| MARUTI | Maruti Suzuki | auto_oem | new |
| HINDUNILVR | Hindustan Unilever | fmcg | new |
| ETERNAL | Eternal (Zomato, Blinkit) | consumer_internet | new |

## Time window: last four quarters only (TTM)
Quarters Q3 FY26, Q4 FY26, Q1 FY27, Q2 FY27 (Oct 2025 - Sep 2026). Questions ask only about this window (TTM,
quarter-on-quarter, YoY against the same quarter is allowed where the filing itself prints the comparison).
Documents: results filings (XBRL + PDF) for those quarters, investor presentations, concall transcripts, results
press releases (filed about Jan 2026 - Nov 2026), the FY26 annual report, and announcements from 1 Nov 2025 to today.
Structured data from the existing stores for the same window: XBRL results, shareholding (4 quarters), pledges,
prices and delivery (1 year), corporate actions, bulk/block deals, credit ratings. Nothing older.

## Sandbox
Raw documents: `D:\RealityEngine\pilot10\raw\<SYMBOL>\<doc_type>\` plus `manifest.csv` (url, sha256, doc_type,
title, filing date, dissemination time). Database: `D:\RealityEngine\pilot10\pilot10.db` (built by the pilot3
scripts, generalised to take a symbol list and paths). The pilot3 database stays as it is.

Held stores already have most documents up to Aug-Sep 2026 (`equity_intelligence.corporate_documents`); the Q2 FY27
results season (Oct-Nov 2026) and most announcement PDFs have to be fetched (`reality_engine/ingestion/bse_client.py`,
`reality_engine/scripts/fetch_originals.py`, runner examples in `D:\RealityEngine\raw\runners\`).
