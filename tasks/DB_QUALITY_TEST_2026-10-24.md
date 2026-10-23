# Database quality test — 2026-10-24

Questions set by Shivam. Answered by one fresh DeepSeek worker (deepseek-v4.1-flash, max effort, dsh headless) using only the
reality-data MCP tools (commit 7a36ddd). Search was keyword + annual-report facts only, because paid query embedding is off
(commit 13a634c). Claude watched the run, re-checked every answer against the databases, and wrote this report.

## Timing

| | |
|---|---|
| Job | 20261023T234816Z-24da9abe |
| Start / end | 05:18:16 / 05:26:06 IST |
| Total | **7 min 50 s** for 5 questions (dsh run 460.7 s) |
| Model steps | 26 (38.5k output tokens of reasoning) |
| Tool calls | 67: sql 42, search_docs 9, resolve 4, price 3, facts 3, catalog 1, pwsh 5 (local reads of dsh's own spill file of the large catalog output) |
| Tool errors | 7 sql errors (wrong column/table names; it corrected each one) |
| Network / internet | **none** (checked every call) |

For comparison, the earlier PPL test without the tools took 39 steps / 9.5 min for 2 questions.

## Approach

1. `catalog` once for the map, then `resolve` on all four identifiers up front (AEROFLEX, 532627 -> JPPOWER, 544161 ->
   DPABHUSHAN, DEEDEV).
2. Easy facts went to the purpose-built tools (`price`, `facts`, `search_docs`); everything else went to `sql`, often with schema
   probes first (pragma/information_schema). That's where most of the calls and all 7 errors came from.
3. It checked its own answers. It cross-checked the stored P/B against price × shares / equity and found the stored ratio is
   stale; it ran a control search (Aditya Sahu appears in other companies' concalls) to prove the Q5 gap is DEEDEV-specific,
   not a search failure.

## Answers and verdicts (each re-checked by Claude)

| # | Answer (short) | Claude check | Verdict |
|---|---|---|---|
| 1 | AEROFLEX makes stainless-steel flexible hoses/assemblies, metal bellows, composite hoses, liquid-cooling skids (FY26 AR p100 quote + Jul-2026 deck). Close 14 Oct 2026 **₹568.70** | px_nse close 568.70 ✓ | **Correct** |
| 2 | 532627 = JPPOWER. Latest AR FY26 (doc 47212, filed 2026-07-04): Adani Enterprises' plan for Jaiprakash Associates approved by NCLT 17 Mar 2026; **Adani Power bought 24% of JPVL on 22 May 2026** and JPVL became an Adani Power associate; Adani executives joined the board (p4, p14, p17, p62) | doc 47212 is the latest AR ✓; p14 quote "Chief Commercial Officer of Adani Power" ✓ | **Correct** |
| 3 | 544161 = D.P. Abhushan (INE266Y01019): gold/silver/diamond jewellery retail, ~12 showrooms in MP/Rajasthan, one segment "Jewellery" | bse_code_isin 544161 -> INE266Y01019 ✓ | **Correct** |
| 4 | Stored P/B **4.77** (company_forensic_health, evaluated 2026-08-30) is stale: it matches the 14-Oct close. At the latest close **₹526.10 (19 Oct)**, P/B = **4.09x (computed)** from FY26 equity ₹890.39 cr and 6.926 cr shares | 613.30×6.926 cr/890.39 cr = 4.77 ✓; 526.10 -> 4.09 ✓ | **Correct, and it caught a data-quality flaw** |
| 5 | **Not answerable from the data.** The Aug-2026 DEEDEV concall exists only as a structured extraction attributed to management; the transcript text was never chunked or indexed | document_chunks has 1 DEEDEV doc (a YouTube video) ✓; 3 CONCALL_TRANSCRIPT rows dated 2026-08-28 are marked is_processed=1 ✓ | **Correct "no data"**; this is a real gap |

## Data gaps this test exposed (to fix)

1. **Concall transcripts marked processed but never chunked**: DEEDEV's Aug-2026 transcript PDFs are on disk and flagged
   `is_processed=1`, but they have no `document_chunks` rows. So questions about who asked what are impossible. Check how many other companies are
   affected.
2. **company_forensic_health mixes vintages**: pb_ratio and market_cap come from different price dates. Ratios should store their
   price date, or be computed on read.
3. **No quarterly net worth**: `quarterly_financials` has no equity column, so book value lags price by up to a year.
4. **Catalog errors**: it lists `company_forensic_health` and `financial_metrics` under the truth snapshot, but they live only in
   equity_intelligence. This cost the worker 4 failed calls. Fix catalog_descriptions.yaml.
5. **Search was keyword-only** during this test (paid embedding off). Q1-Q3 didn't need vectors. Turning on DeepInfra query
   embedding needs Shivam's permission.

## Tool improvements suggested by the run

- 42 of 67 calls were raw `sql`. A `fundamentals(symbol)` tool (latest equity, shares, BVPS, P/B at the latest price, with dates) and a
  `concall(symbol, period)` tool (speakers, Q&A by analyst) would cut this to about 10 calls.
- Return column lists in `catalog` for the most-used tables, so the worker stops probing schemas.
