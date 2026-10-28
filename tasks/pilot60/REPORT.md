# Pilot-60 — stratified universe, whole-market T1, instantiated master bank

- universe: 60 companies (10 large / 20 mid+small / 30 micro), 21 sectors; `UNIVERSE.csv`
- store: `.tmp/pilot60/chunks_v3_pilot.db` (433 docs, 36494 chunks, build 431.8 s)
- T1: `.tmp/pilot_all` (whole market, `build_t1 --universe all`; build time in `tasks/pilot60/T1_BUILD.json`)
- instances: 1608 (stock 3/bucket + peer sets); originals: 1073
- **answered: instances 491/1608 = 30.5%; originals 148/1073 = 13.8%**
- hand-check precision: 0.05

## 1. Universe

| bucket | companies | sectors |
|---|---:|---:|
| LARGE | 10 | 10 |
| MID-SMALL | 20 | 20 |
| MICRO | 30 | 6 |

Sector x bucket table: `SECTOR_BUCKET.md`.

## 2. Answered %

### Overall and by bucket

| group | answered | cases | % |
|---|---:|---:|---:|
| LARGE | 170 | 517 | 32.9% |
| MICRO | 150 | 517 | 29.0% |
| MID-SMALL | 162 | 517 | 31.3% |
| None | 9 | 57 | 15.8% |

### By sector

| group | answered | cases | % |
|---|---:|---:|---:|
| Automobile and Auto Components | 14 | 74 | 18.9% |
| Capital Goods | 55 | 199 | 27.6% |
| Chemicals | 30 | 72 | 41.7% |
| Construction | 5 | 21 | 23.8% |
| Construction Materials | 17 | 52 | 32.7% |
| Consumer Durables | 2 | 18 | 11.1% |
| Consumer Services | 5 | 35 | 14.3% |
| Fast Moving Consumer Goods | 17 | 58 | 29.3% |
| Financial Services | 64 | 156 | 41.0% |
| General Diversified | 107 | 340 | 31.5% |
| Healthcare | 18 | 62 | 29.0% |
| Information Technology | 6 | 23 | 26.1% |
| Metals & Mining | 18 | 85 | 21.2% |
| Oil Gas & Consumable Fuels | 12 | 42 | 28.6% |
| Other | 14 | 83 | 16.9% |
| Power | 30 | 89 | 33.7% |
| Realty | 11 | 33 | 33.3% |
| Services | 1 | 9 | 11.1% |
| Telecommunication | 32 | 67 | 47.8% |
| Textiles | 2 | 2 | 100.0% |
| Unclassified | 31 | 88 | 35.2% |

### By family

| group | answered | cases | % |
|---|---:|---:|---:|
| F1 | 127 | 322 | 39.4% |
| F10 | 12 | 42 | 28.6% |
| F11 | 3 | 6 | 50.0% |
| F12 | 18 | 126 | 14.3% |
| F14 | 33 | 89 | 37.1% |
| F15 | 3 | 57 | 5.3% |
| F16 | 13 | 41 | 31.7% |
| F17 | 37 | 100 | 37.0% |
| F18 | 0 | 6 | 0.0% |
| F19 | 0 | 16 | 0.0% |
| F2 | 133 | 345 | 38.6% |
| F20 | 3 | 37 | 8.1% |
| F3 | 63 | 145 | 43.4% |
| F4 | 9 | 22 | 40.9% |
| F6 | 0 | 63 | 0.0% |
| F8 | 2 | 7 | 28.6% |
| F9 | 35 | 184 | 19.0% |

### By entity level (instances keep the parent level)

| group | answered | cases | % |
|---|---:|---:|---:|
| stock | 491 | 1608 | 30.5% |

### Bucket x family heat table (answered %)

| family | LARGE | MID-SMALL | MICRO |
|---|---:|---:|---:|
| F1 | 39.6% | 40.6% | 37.7% |
| F2 | 40.7% | 38.9% | 36.3% |
| F3 | 48.9% | 44.7% | 36.2% |
| F4 | 42.9% | 42.9% | 42.9% |
| F6 | 0.0% | 0.0% | 0.0% |
| F8 | - | - | - |
| F9 | 21.7% | 18.3% | 18.3% |
| F10 | 28.6% | 28.6% | 28.6% |
| F11 | 50.0% | 50.0% | 50.0% |
| F12 | 15.4% | 15.4% | 15.4% |
| F14 | 37.9% | 41.4% | 34.5% |
| F15 | 5.3% | 5.3% | 5.3% |
| F16 | 44.4% | 44.4% | 44.4% |
| F17 | 45.5% | 33.3% | 33.3% |
| F18 | 0.0% | 0.0% | 0.0% |
| F19 | 0.0% | 0.0% | 0.0% |
| F20 | 8.3% | 8.3% | 8.3% |

### Originals, by entity level

| group | answered | cases | % |
|---|---:|---:|---:|
| index | 0 | 35 | 0.0% |
| industry | 7 | 181 | 3.9% |
| macro | 0 | 23 | 0.0% |
| market-cap bucket | 1 | 15 | 6.7% |
| market-wide | 12 | 95 | 12.6% |
| policy | 0 | 93 | 0.0% |
| price band | 1 | 4 | 25.0% |
| sector | 0 | 15 | 0.0% |
| stock | 127 | 584 | 21.7% |
| theme | 0 | 28 | 0.0% |

### Grade distribution

| grade | instances | originals |
|---|---:|---:|
| ANSWERED | 491 | 148 |
| PARTIAL | 860 | 753 |
| BLOCKED_SCHEMA | 126 | 90 |
| BLOCKED_TOOL | 81 | 53 |
| NOT_IN_DATA | 50 | 27 |
| WRONG | 0 | 2 |

## 3. Top gaps per bucket (what micro caps lack vs large)

Gap = the field the failed hop named (or the CASE_MAP blocker). Fix = the table, fetch or planner wiring that closes it, ranked by cases unblocked.

| bucket | companies | mean annual_report | mean concall | mean deck | mean results_notes | mean announcement | no concall | no AR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LARGE | 10 | 2.9 | 10.7 | 13.5 | 1.5 | 392.5 | 0 | 0 |
| MID-SMALL | 20 | 3.1 | 11.2 | 13.6 | 1.3 | 329.4 | 0 | 0 |
| MICRO | 30 | 2.8 | 7.0 | 8.1 | 0.8 | 163.8 | 10 | 3 |

| bucket | cases | gap | fix (table / fetch / tool) |
|---|---:|---|---|
| LARGE | 47 | consensus_estimates | no consensus store by design: EXPECTATIONS uses the company's own guidance proxy |
| MID-SMALL | 47 | consensus_estimates | no consensus store by design: EXPECTATIONS uses the company's own guidance proxy |
| MICRO | 47 | consensus_estimates | no consensus store by design: EXPECTATIONS uses the company's own guidance proxy |
| MICRO | 29 | company_sector_pit | built in T1 (2,055 rows): wire RIPPLE's policy->sector hop to it (planner change, no fetch) |
| LARGE | 26 | company_sector_pit | built in T1 (2,055 rows): wire RIPPLE's policy->sector hop to it (planner change, no fetch) |
| MID-SMALL | 26 | company_sector_pit | built in T1 (2,055 rows): wire RIPPLE's policy->sector hop to it (planner change, no fetch) |
| MICRO | 19 | hop failed: EVENT (event store unavailable and no price window) | event_day0 (15:30 session rule) and announcement dissemination index |
| LARGE | 17 | CASE_MAP blocker needs_new_fetch:exchange_originals: v0 measured only an adjacent held-dat | exchange_originals (new fetch: BSE/NSE original filing files) |
| MID-SMALL | 16 | company_segment_pnl | built in T1 (34,451 rows): wire the segment hop to it |
| MID-SMALL | 16 | CASE_MAP blocker needs_new_fetch:exchange_originals: v0 measured only an adjacent held-dat | exchange_originals (new fetch: BSE/NSE original filing files) |
| MICRO | 16 | company_segment_pnl | built in T1 (34,451 rows): wire the segment hop to it |
| MICRO | 15 | CASE_MAP blocker needs_new_fetch:exchange_originals: v0 measured only an adjacent held-dat | exchange_originals (new fetch: BSE/NSE original filing files) |
| LARGE | 14 | company_segment_pnl | built in T1 (34,451 rows): wire the segment hop to it |
| LARGE | 11 | hop failed: EVENT (no event row around 2026-10-19 | event_day0 (15:30 session rule) and announcement dissemination index |
| MID-SMALL | 11 | hop failed: EVENT (no event row around 2026-10-19 | event_day0 (15:30 session rule) and announcement dissemination index |

## 4. PIT

- instance rows with a PIT breach: 0/1608; originals: 0/1073
- T2 chunk known_at audit: 0 mismatches on the sampled docs (filing-record timestamps only, never the crawl date)

## 5. Latency per planner (instance runs)

| planner | calls | p50 s | p95 s | max s |
|---|---:|---:|---:|---:|
| COMPARE | 208 | 0.013 | 0.267 | 0.532 |
| EVENT | 497 | 0.002 | 0.004 | 0.011 |
| EVIDENCE | 1067 | 0.025 | 0.067 | 25.721 |
| EXPECTATIONS | 148 | 0.000 | 0.000 | 0.000 |
| FACTS | 1491 | 0.037 | 0.316 | 1.619 |
| RIPPLE | 195 | 0.027 | 0.073 | 0.144 |
| SCREEN | 28 | 0.000 | 1.604 | 2.024 |
| SERIES | 1122 | 0.013 | 0.035 | 1.013 |
| resolve | 1608 | 0.013 | 0.027 | 0.055 |

## 6. T2 chunk coverage (FY25+, 60 + regression ISINs)

The build keeps the latest docs per company and type — 1 annual report, 2 concalls, 2 decks, 1 results note, 1 announcement — because the uncropped FY25+ set is ~2,060 documents on one disk (an annual report parses at ~10 s). `expected` below is the uncropped registry, so `missing` mixes the cap with files that are truly not on D: (70 registry docs had no resolvable file).

| doc type | expected | found | missing originals |
|---|---:|---:|---:|
| annual_report | 259 | 77 | 182 |
| concall | 792 | 146 | 646 |
| deck | 858 | 140 | 718 |
| results_notes | 78 | 0 | 78 |
| announcement | 72 | 70 | 2 |

missing original files (all ISIN x type): **1629**; the full list is in `coverage.json` (`by_isin`).

## 7. Hand check (60 answers, 20 per bucket)

- precision: **5.0%** (3 OK / 60 checked), {'WRONG': 55, 'OK': 3, 'PARTIAL': 2}

| bucket | checked | OK | PARTIAL | WRONG |
|---|---:|---:|---:|---:|
| LARGE | 20 | 3 | 2 | 15 |
| MID-SMALL | 20 | 0 | 0 | 20 |
| MICRO | 20 | 0 | 0 | 20 |

| # | instance | bucket | verdict | note |
|---:|---|---|---|---|
| 1 | MB0001#L | LARGE | WRONG | asks AEROFLEX products+close; answer gives IDEA close and AR section headings, not products |
| 2 | MB0002#L | LARGE | WRONG | asks latest AR control change; answer gives close and a concall quote, no AR/control change |
| 3 | MB0008#L | LARGE | OK | 3-yr price CAGR computed for the substituted company (POWERGRID): 199.6->250.3 = 25.5%, CAGR 7.7% |
| 4 | MB0010#L | LARGE | WRONG | asks public shareholding Sep-2026; answer gives shares outstanding and a Feb-2026 deck ownership split, no pub |
| 5 | MB0022#L | LARGE | WRONG | asks promoter holding; answer returns an employee NPS and an unrelated acquisition stake |
| 6 | MB0023#L | LARGE | WRONG | asks manufacturing facilities per the 5-Aug-2026 deck; answer gives 2024 deck plants and unrelated ESG values |
| 7 | MB0024#L | LARGE | WRONG | asks Chemcon's products per its 22-May-2026 deck; answer gives Grasim revenue % changes |
| 8 | MB0028#L | LARGE | OK | YTD-2026 high 1,159 on 2026-08-05 for the substituted company (BAJFINANCE) |
| 9 | MB0034#L | LARGE | WRONG | RELIANCE products+close: close is right, products not answered |
| 10 | MB0035#L | LARGE | PARTIAL | KRBL products+close: close right; spectrum/awards are not a product list |
| 11 | MB0071#L | LARGE | WRONG | asks management commentary on demand/margins; answer returns a deck margin formula and AR margin-money lines |
| 12 | MB0079#L | LARGE | PARTIAL | concall passage does discuss transmission demand, but the margin values are 2024/2025 decks and do not answer  |
| 13 | MB0086#L | LARGE | WRONG | asks absolute Q1FY27 segment revenue; answer gives a YoY % and unrelated deck lines |
| 14 | MB0089#L | LARGE | WRONG | asks Q1FY27 segment revenue; answer gives 2022 'business segment wise AUM' deck values |
| 15 | MB0096#L | LARGE | WRONG | asks net NPA Q1FY27 + XBRL concept; answer gives a deck NPA and a 2024 AR NPA, no concept and not the quarter |
| 16 | MB0099#L | LARGE | WRONG | asks Q1FY27 net NPA; answer gives a 2026-04-29 (Q4FY26) deck NPA and a 2024 AR NPA |
| 17 | MB0109#L | LARGE | WRONG | asks 3-yr adjusted CAGR; answer gives only a close |
| 18 | MB0110#L | LARGE | OK | 3-yr adjusted CAGR computed for the substituted company (IDEA): 0.8% |
| 19 | MB0121#L | LARGE | WRONG | asks public shareholding Sep-2026; answer gives shares outstanding and a Feb-2026 promoter %, no public % |
| 20 | MB0122#L | LARGE | WRONG | asks public shareholding Sep-2026; answer gives a Feb-2026 GoI/FII split and shares outstanding, not the Sep-2 |
| 21 | MB0397#MS | MID-SMALL | WRONG | asks a rating action and press-release date; answer gives a price move |
| 22 | MB0441#MS | MID-SMALL | WRONG | asks volume and delivery; answer gives close only |
| 23 | MB0577#MS | MID-SMALL | WRONG | asks last-quarter promoter holding; answer gives FY22/FY23 AR shareholding lines and a price |
| 24 | MB0890#MS | MID-SMALL | WRONG | asks Zomato->Eternal ISIN mapping; answer gives Piem Hotels shareholding |
| 25 | MB0899#MS | MID-SMALL | WRONG | asks price band and base-price reset; answer gives capex/cost deck lines and a close |
| 26 | MB0900#MS | MID-SMALL | WRONG | asks band and delivery behaviour; answer gives TEJASNET's close |
| 27 | MB0901#MS | MID-SMALL | WRONG | asks band change and volume spike; answer gives NLCINDIA's close |
| 28 | MB0916#MS | MID-SMALL | WRONG | asks DII accumulation vs daily flow; answer gives PAT growth and plant values |
| 29 | MB0944#MS | MID-SMALL | WRONG | asks passive buying implied by index entry; answer gives the Nifty 50 close |
| 30 | MB0946#MS | MID-SMALL | WRONG | asks index-driven share of volume; answer gives Nifty close and an ESG deck line |
| 31 | MB0951#MS | MID-SMALL | WRONG | asks volume vs price/mix growth; answer gives a UBL close and a transcript header |
| 32 | MB0955#MS | MID-SMALL | WRONG | asks incremental ROIC vs cost of capital; answer gives unrelated AR healthcare/EPS lines |
| 33 | MB0956#MS | MID-SMALL | WRONG | asks ROIC vs cost of capital; answer gives an APLAPOLLO close |
| 34 | MB0957#MS | MID-SMALL | WRONG | asks where ROIC is earned; answer gives FY22 AR tube/project lines |
| 35 | MB0961#MS | MID-SMALL | WRONG | asks retained-capital return vs cost of equity; answer gives AR notes pages that do not address it |
| 36 | MB0963#MS | MID-SMALL | WRONG | asks capex destination and return; answer gives 2022 EPS lines |
| 37 | MB0964#MS | MID-SMALL | WRONG | asks receivables/inventory vs revenue; answer gives dividend/interest adjustments and an AR page |
| 38 | MB0966#MS | MID-SMALL | WRONG | asks spectrum-liability accounting; answer gives 2024 EPS lines |
| 39 | MB0968#MS | MID-SMALL | WRONG | asks provisions vs stressed book; answer gives 2022 PBT lines |
| 40 | MB0970#MS | MID-SMALL | WRONG | asks which call cut margin guidance; answer gives FY22 margin lines and an unrelated Q&A |
| 41 | MB0530#MI | MICRO | WRONG | asks whether the KEI Sanand date was met; answer gives a close |
| 42 | MB0621#MI | MICRO | WRONG | asks FII ownership; answer gives a return (and the unadjusted 651->219 move is a split artefact) |
| 43 | MB0863#MI | MICRO | WRONG | asks stake-sale spread; answer gives promoter changes and a close |
| 44 | MB1060#MI | MICRO | WRONG | asks futures basis; answer gives deck 'experience' values |
| 45 | MB1061#MI | MICRO | WRONG | asks OI addition interpretation; answer gives deck experience values and a close |
| 46 | MB1062#MI | MICRO | WRONG | asks short covering/OI; answer gives a close |
| 47 | MB1063#MI | MICRO | WRONG | asks rollover; answer gives a close and a concall Q&A |
| 48 | MB0397#MI | MICRO | WRONG | asks a rating action and date; answer gives a price move |
| 49 | MB0441#MI | MICRO | WRONG | asks volume and delivery; answer gives close only |
| 50 | MB0577#MI | MICRO | WRONG | asks last-quarter promoter holding; answer gives FY22-FY24 AR shareholding lines and a close |
| 51 | MB0890#MI | MICRO | WRONG | asks ISIN mapping; answer gives promoter change and unrelated deck lines |
| 52 | MB0899#MI | MICRO | WRONG | asks band/base price; answer gives capex/EPS lines |
| 53 | MB0900#MI | MICRO | WRONG | asks band and delivery; answer gives a close |
| 54 | MB0901#MI | MICRO | WRONG | asks band change; answer gives a close |
| 55 | MB0916#MI | MICRO | WRONG | asks DII accumulation; answer gives PET-chips capacity values |
| 56 | MB0944#MI | MICRO | WRONG | asks passive buying; answer gives the Nifty 50 close |
| 57 | MB0946#MI | MICRO | WRONG | asks index-driven volume; answer gives Nifty close and AR notes |
| 58 | MB0951#MI | MICRO | WRONG | asks growth drivers; answer gives a close and evidence quoting Oriental Carbon while the entity is AGVENTURES |
| 59 | MB0955#MI | MICRO | WRONG | asks incremental ROIC; answer gives unrelated AR lines |
| 60 | MB0956#MI | MICRO | WRONG | asks ROIC vs cost of capital; answer gives a close |

- per-row verdicts with the source rows: `HAND_CHECK_60.json` / `HAND_CHECK_60.md`

## 8. Method, scope and deviations

- Every instance keeps the parent question text and swaps the entity; the parent company's own sector is preferred inside the bucket when it maps to a pilot sector, otherwise the seeded (20261028) random pick. 9 cases are skipped (ETF/bond ISINs and one old symbol); each reason is in `INSTANTIATE_STATS.md`.
- Instances inherit the parent CASE_MAP status. 36 instance rows and 9 original rows whose only blocker was `needs_new_table:<t>` for a table the T1 build now fills were restored to ANSWERED (`regrade.py`); fetch blockers were not cleared.
- Entity-level breakdown is the parent level: every instantiated case is a stock-level case by construction, so the non-stock levels appear in the originals table above, not in the instance table.
- Sector labels follow decision 8 as far as held data allows: `UNIVERSE.csv` carries our label (NSE sector/industry, by ISIN) and a BSE-umbrella column, which is empty because the 200-company sector pilot does not overlap the 60. `company_sector_pit` was still empty when the selection ran (the T1 build finished afterwards), so the 60 are labelled from `master_companies`. Micro caps are labelled coarsely (General Diversified / Other / Unclassified), which is why the micro bucket spans 6 sectors, not 20.
- Market cap: the 2026-09-30 session from `company_state_daily`, top 100 / 101-750 / rest, with FY26 traded value > 0 on >= 200 sessions. 8 rows whose computed bucket was two steps from the held tier were dropped as broken mcap rows and the list re-ranked (e.g. a large cap implying Rs 3.5 cr). That is a real `shares_out` defect (paid-up/face parse) and a gap in its own right.
- T2 chunks: the reviewed `tasks/pilot_t2/build_chunks_v3.py` was reused unchanged (chunker_v3, FY25+ filing registries, known_at from the filing record), with three module globals pointed at this pilot and sharded 3 ways. The per-company cap (latest 1 AR / 2 concall / 2 deck / 1 results / 1 announcement) is the time/disk constraint; the uncropped registry is what `coverage.json` scores, so the missing list is honest. 70 registry docs had no resolvable file anywhere on D:.
- T2 ISIN set = 60 universe + 30 bank-regression ISINs (28 of them outside the 60). The wider 511 ISINs named anywhere in the bank hold ~9,100 FY25+ documents; chunking all of them is a feed-scale job and was not run.
- The query-layer change is additive: `Ctx` opens the T1 build only when `REALITY_PILOT_T1` / `REALITY_MARKET_STATE` is set, and SCREEN uses `company_state_daily` / `company_membership_pit` for cap and index screens. FACTS still reads the live XBRL/AR/deck stores (the same rows `facts_pilot` copies); wiring the planner to `company_metric_series` is a follow-up.
- Originals ran without `REALITY_CHUNKS_V3` (13.8% answered); instances ran with the pilot chunk store (30.5%). The difference is partly the store, partly the T1 wiring, so the two rates are not a like-for-like A/B.
- The hand check is the honest check: the bench grade only requires every hop to return rows, so 55 of 60 sampled instance answers were substantively wrong against the source rows even though the grader called them ANSWERED. The planner needs an entity/relevance gate, not just a row-count gate.
