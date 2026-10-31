# Scope options and their costs, 31 Oct 2026

Sizing only, for Shivam's scope ruling (Gate 95% review, idea 6). **No recommendation is made here**: he has said no re-scope (`D:\RealityEngine\plans\DECISION_LOG.md:329`, 2026-10-30 01:30 IST, "keep pushing to 95% (no re-scope)"). This file puts numbers on the options so the ruling is informed.

Measured 31 Oct 2026, read-only, from `tasks/master_bank/MASTER_BANK.jsonl`, `tasks/pilot60/INSTANCES.jsonl`, `tasks/pilot60/UNIVERSE.csv` and the stores named under each table. Nothing here changes a bank, store or engine file.

## 1. What the bank asks for outside the 60

| Measure | Value | Source |
|---|---:|---|
| Parents naming at least one stock outside the pilot | 945 of 1,073 | bank `entities[].isin` vs the 60 pilot ISINs |
| Distinct outside ISINs named by parents | 450 | same |
| ... LARGE / MID / SMALL / MICRO / unknown | 80 / 74 / 122 / 173 / 1 | `equity_intelligence.master_companies.market_cap_tier` |
| Stock-level parents / non-stock parents | 584 / 489 | bank `entity_level` (the review's 489 non-stock matches) |
| Parents with stock or peer-set instances / as-is only | 574 / 490 | measured from `INSTANCES.jsonl` (the review's 529/371 split is its run classification, not this file's) |
| Pilot members of requested indices | 12 of 149 NIFTY MIDCAP 150; 24 of 250 NIFTY LARGEMIDCAP 250; 1 of 10 FPI-150 membership windows | `market_state_pilot.company_membership_pit` |

The difference from the review's ~394 distinct names is definitional: this count takes every `entities[].isin` in the bank, including parents whose entity list names companies that never received instances. The review's 34.6% is a row-level classification of its own run, which this worktree does not hold.

## 2. What the structured stores already hold for the 450 names

| Store | Names covered (of 450) | Rows | Note |
|---|---:|---:|---|
| `equity_intelligence.master_companies` | 450 | 450 | identity, sector, BSE code |
| `equity_intelligence.daily_price_delivery` | 450 | - | NSE daily price |
| `equity_intelligence.mkt_bse_eq_daily` | 443 | - | BSE daily price |
| `equity_intelligence.annual_financials` | 445 | - | annual financials |
| `equity_intelligence.quarterly_financials` | 436 | - | quarterly financials |
| `equity_intelligence.corporate_documents` | 443 | 25,774 | document metadata |
| `equity_intelligence.shareholding` | 4 | 40 | the market-wide table holds 40 rows in total |
| `equity_intelligence.document_chunks` | 435 | 1,182,801 | legacy chunk store, already searchable |
| `results_xbrl.filings` | 434 | 14,955 | quarterly XBRL filings |
| `ar_facts.ar_docs` | 432 | 2,844 | annual reports registered with pages |
| `deck_figures.deck_sources` | 378 | 6,608 | investor presentations |
| `concall_facts.cc_docs` | 351 | 2,811 | concall transcripts processed |
| `bse_announcements.ann` | 439 | 304,626 | announcement metadata |

So identity, prices, annual/quarterly financials and XBRL are already held for almost every named company; the thin spots are shareholding (4 of 450) and processed concalls (351 of 450).

## 3. Documents held for the 450 names

| Document type | Docs | Pages | Source |
|---|---:|---:|---|
| Annual reports | 2,844 | 787,789 (775,780 text pages, avg 277) | `ar_facts.ar_docs.n_pages` |
| Investor presentations (decks) | 6,608 | 213,078 page images | `deck_figures.deck_sources` + `deck_figures.pages` |
| Concall transcripts | 2,811 | ~43,300 (15.4 pages avg from the pilot mix) | `concall_facts.cc_docs` |
| Results notes | 304 | ~4,800 (15.8 pages avg) | `corporate_documents.doc_type='FINANCIAL_RESULT'` |
| Announcements (metadata) | 304,626 | not paginated | `bse_announcements.ann` |

The four paginated types total about **1.05 million pages**. The pilot's own chunk store (60 names) holds 2,488 documents and 93,579 pages, i.e. about 41.5 documents and 1,560 pages per name.

## 4. Chunking hours, from measured rates

Measured inputs:
- The reviewed chunk builder is single-threaded at **~10 s per annual report** (`tasks/pilot60/build_chunks60_all.py:5`).
- The pilot build run `pilot-20261029-065007` chunked **1,207 documents / 45,807 pages in 985 s** (`chunks_v3_pilot.db build_run`), i.e. ~0.82 s per non-AR document.
- The pilot v3 store is **529 MB for 93,579 pages** (5,660 bytes per page), i.e. the output size follows pages.

| Workload | Docs | Pages | Single-threaded | On the pilot's 6 shards | Output store |
|---|---:|---:|---:|---:|---:|
| A. Same selection as the pilot (~41.5 docs and ~1,560 pages per name) | 18,675 | ~702,000 | ~7 h | ~1.2 h | ~4 GB |
| B. Every held AR, deck, concall and results note | ~12,600 | ~1,050,000 | ~10 h | ~1.7 h | ~6 GB |

Arithmetic: A = 450 x 2.8 ARs x 10 s + 450 x 38.7 other docs x 0.82 s; B = 2,844 x 10 s + ~9,700 x 0.82 s. Wall clock assumes the shards run in parallel, as the pilot build did.

**Not in this number: OCR.** The pilot build recorded `scanned=0`; every scan-needing annual report or deck would add minutes per document on the OCR path, not seconds. The 450 names' scans are not counted or sized here.

## 5. The options, as the review framed them

**(a) Count each parent through its instances and report parents apart (no data change).** Cost is engine/reporting work only: 574 parents already have stock or peer-set instances whose rows are pilot-scoped; the 490 as-is parents are set questions over the market, not over 60 names. Nothing in this option closes the 450 outside names.

**(b) Widen the data pilot to the 450 names.** The structured stores in section 2 are already held, so the build steps are the pilot builders (T1 market state, extraction, the fact view) over 450 names, plus the chunking in section 4. The chunking is the sized part: ~7-10 h single-threaded, ~1.2-1.7 h on 6 shards, 4-6 GB of chunk store, OCR extra. The fact/atom rebuilds over 450 names were **not timed** here; the pilot fact view is 614 MB for 60 names, which a linear scale would put at ~4.6 GB (not measured).

**(c) Keep the 60 and answer set questions scoped to them.** Measured in `SHIVAM_SHEET_SCOPE.md`: 7 of 20 set questions get a usable list or count over the 60, 4 of those 7 are concall text-mention counts, 2 are weak proxies and 11 have no 60-name answer. The pilot's share of the requested universes is 12 of 149 and 24 of 250 members, so a scoped set answer is a small slice of any NIFTY constituent list even when the metric is held.

## 6. What is not sized here

- The T1/extraction/fact-view rebuild for 450 names (deterministic, on held data, not timed in this worktree).
- OCR workload for scanned documents (not counted; the pilot avoided it).
- Any new fetch: this file only sizes what is already on disk. Names whose documents are not held are outside it.
