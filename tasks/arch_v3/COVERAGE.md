# Coverage — what the master bank can answer now, and after the new tables

Built from `tasks/arch_v3/CASE_MAP.jsonl` (1,030 rows, one per master-bank case) and the
read-only fill probes in §2. Every number below is reproducible: `python .tmp/stats.py` prints it
from the JSONL; the probes are `.tmp/probe_fill.py`, `.tmp/probe_fill2.py`, `.tmp/probe_cols.py`.

---

## 1. Headline

| measure | cases | share |
|---|---:|---:|
| **answerable now** (no named gap, held stores cover the evidence) | **434** | **42.1%** |
| needs a new table, buildable from held data | 386 | 37.5% |
| needs a fetch (source exists, not held) | 201 | 19.5% |
| **NOT IN DATA** (nobody publishes it, or it is a forecast) | **14** | 1.4% |
| — of which justified as the answer (counts as answered) | 5 | 0.5% |
| — of which genuinely unanswerable | 9 | 0.9% |

**Projected:** 820 / 1030 = **79.6%** after the new tables on held data alone; **1,021 / 1030 =
99.1%** after the planned fetches. The ≥95% target is met **only with the fetch stream** — on held
data the design reaches 79.6%, and 127 of the 201 fetch-blocked cases sit behind three sources
(commodity series 62, exchange originals 46, bhavcopy backfill 19). This is the honest number:
the bank asks 79 questions about commodity/rainfall/freight series we have never fetched.

`needs_new_table:chunks_v3` names the **store** (`doc` / `chunk` / `chunk_tag` /
`chunk_fts` / `chunk_vec_ref`), not a single table; every other `needs_new_table`
value is a table in `SCHEMA_V3.sql`.

The 9 genuinely unanswerable cases, with reasons (§5 lists all 14 NID rows):

| cases | reason | why it stays NID |
|---|---|---|
| 6 (MB0191, MB0193–MB0195, MB0197, MB0198) | refurbished/second-hand electronics sales | no exchange, industry body or paid terminal publishes an Indian refurb-sales series |
| 1 (MB0445) | analyst consensus / target price | paid-only source; excluded by the no-paid-spend rule (target prices could be crawled from broker notes later, but not for a consistent cross-section) |
| 1 (MB0810) | "what will the price be on Diwali 2027" | forecast; the answer is a labelled scenario range, not a stored fact |
| 1 (MB0936) | Novelis cost curve | Novelis is an unlisted subsidiary of Hindalco; only consolidated segment numbers are held |

Note on "partial": the bank's own verdicts were `yes 241 / partial 607 / no 152`. `partial` does not
mean answerable: it means the text exists but the required structured field does not. The 386
`needs_new_table` cases are exactly those. A partial text answer exists for many of them today, and
the pilot will record that as `PARTIAL`, not `ANSWERED`.

Flags on ambiguous cases (kept, not dropped):

- **200** rows have `answer_kind = null` (the whole ripple bank): routed by `chain` + family.
- **85** rows have `family = []` (all reddit rows): routed by `source_bank` + `archetype`.
- **142** rows have no `as_of`: the PIT cutoff defaults to run time (nothing after "now" can leak).
- **1** row (MB0196) is a theme-level refurb question whose rubric explicitly asks for a NOT IN DATA
  statement, so it is answered today as a justified NID; its twin MB0195 asks for a number and is not.
- `results_xbrl.segment` and `results_xbrl.npa` appear in 27 rubrics but **do not exist** as tables;
  they are mapped to `results_xbrl.facts.concept` (segment concepts measured) and `xbrl_concept_map`
  (banking/NBFC concepts), and this drift is recorded in `CASE_MAP.jsonl` as the same reads.
- `shareholding` (view, 40 rows) is not the live shareholding store; `shp_index` is (50,838 rows,
  100% `promoter_pct` and `broadcast_at` fill). Cases naming `shareholding` were re-pointed.

---

## 2. Held-data verification (every held table cited in CASE_MAP)

Measured 2026-10-28 with `connect_ro`; `fill` is the % non-null of the columns the case map relies
on. `approx` = catalog/`sqlite_stat1` because a fresh `COUNT(*)` exceeds the worker budget on a
cold 50 GB file.

| db.table | rows | max date | fill % | used by |
|---|---:|---|---|---|
| ei.master_companies | 6,940 | — | isin 100, basic_industry 100, tier 94 | RESOLVE/SCREEN |
| ei.security_master | 8,434 | — | isin 100 | RESOLVE |
| ei.symbol_isin_history | 9,360 | — | isin/first/last 100 | RESOLVE |
| ei.daily_price_delivery | 3,194,632 | 2026-10-23 | isin/close/delivery_pct 100 | SERIES/EVENT/SCREEN |
| ei.mkt_nse_full_daily | 4,314,909 | 2026-10-23 | delivery_pct 91 | SERIES |
| ei.mkt_bse_eq_daily | 7,527,246 | 2026-10-23 | **isin 36** | SERIES (BSE fallback) |
| ei.price_bands | 1,054,354 | 2026-09-22 | band 100 | SCREEN/price_band_daily |
| ei.circuit_hits | 243,049 | 2026-09-22 | symbol 100 | FACTS |
| ei.index_membership | 300 | 1 `as_of` (2026-09-30) | isin 100 | SCREEN (snapshot only) |
| ei.index_tri | 13,531 | 2026-10-16 | tri 100 | SERIES/COMPARE |
| ei.mkt_nse_index_daily | 206,437 | 2026-10-23 | close 100 | SERIES |
| ei.nse_index_breadth | 5,717 | 2026-10-23 | adv/dec 100 | FACTS |
| ei.corporate_actions | 18,240 | 2026-10-23 | isin/action/ex_date 100 | EVENT |
| ei.corporate_documents | 127,253 | 2026-10-10 | isin 100, **publication_date 37, bse_dissem_ts 59, call_date 5** | EVIDENCE |
| ei.raw_documents | 39,645 | 2026-10-24 | isin 67 | EVIDENCE |
| ei.document_chunks | 2,939,096 | — | isin 100, event_date 100, fiscal_period 26 | EVIDENCE |
| ei.policy_events | 21,552 | 2026-10-16 | published_at 100, quote_ok 20,970 | RIPPLE |
| ei.macro_events | 30 | 2026-08-14 | doc_id 80 | RIPPLE |
| ei.quarterly_financials | 15,173 | **2026-06-30** | revenue 90 | FACTS |
| ei.annual_financials | 12,933 | FY26 | interest_coverage 93, debt 78 | FACTS |
| ei.shp_index | 50,838 | 2026-10-16 | promoter_pct 100, broadcast_at 100 | FACTS/PIT |
| ei.shp_facts | 30,509 | — | raw XBRL cells | pledge (partial) |
| ei.insider_trades_v2 | 333,712 | 2026-10-23 | **known_at 55** | FACTS/EVENT |
| ei.bulk_block_deals | 271,800 | 2026-10-23 | isin 100 | FACTS/EVENT |
| ei.mkt_nse_deals / mkt_bse_deals | 139,311 / 135,672 | 2026-10-23 | client 100 | FACTS |
| ei.mkt_nse_participant | 19,255 | 2026-10-23 | 100 | FACTS (aggregate OI only) |
| ei.mkt_fii_dii_cash | 1,935 | 2026-10-23 | 100 | FACTS |
| ei.mkt_nsdl_fpi_daily | 30,128 | 2026-10-23 | 100 | FACTS |
| ei.mkt_commodity_daily | 25,255 | **2026-10-06** | commodity/close 100, **no known_at column** | SERIES (13 series) |
| ei.etf_master / etf_px / etf_inav / fund_nav | 432 / 315,259 / 6,800 / 323,489 | 2026-10-24 | 100 | FACTS |
| ei.geographic_exposure | 3,568 | undated | revenue_share 100 | FACTS (company_id-keyed) |
| ei.board_meetings | 120,451 | 2026-11-14 | purpose 100 | EVENT |
| xbrl.filings | 106,613 | 2026-09-30 | isin 99, broadcast_ts 96, dissem_ts 95, audit_opinion 63 | FACTS |
| xbrl.facts | 13,941,210 | — | concept 100; **554 distinct concepts**, 4 taxonomies | FACTS |
| ar.ar_docs | 33,705 | — | isin/filed_at 100 | FACTS |
| ar.ar_facts | 32,443,403 | — | quote 100, value 81, page 100 | FACTS |
| deck.deck_sources / pages | 26,572 / 815,837 | 2026-09-29 | isin/known_at 100 | FACTS |
| deck.facts | ~13.6M (approx) | — | metric 100 | FACTS |
| cc.cc_docs / cc_items | ~9,300 / ~645,000 (approx) | 2026-10-14 | isin 100, quote 100; 12 list_names, 404 ISINs | FACTS |
| bse.ann | 1,947,087 | 2026-10-19 | symbol 100, DissemDT 100, ATTACHMENTNAME 100 | EVIDENCE/EVENT |
| truth.events | ~3.3M | 2026-10-19 | isin/known_at_utc/kind 100 | EVENT |
| truth.px_daily / px_nse_adj / px_bse_adj | 7.3M / 4.3M / 6.8M | 2026-10-19 | adj_close 100 | SERIES |

Drift from the context pack and the gap roll-up (they are wrong, the probes are right):

1. `document_chunks` is **2,939,096 rows**, not 2.3M (`sqlite_stat1` is stale; ANALYZE has not run).
2. `shareholding` is a **view with 40 rows**; the live PIT store is `shp_index` (50,838 rows). NG05's
   "shareholding is a stub" is true of the view and false of the store — 5 cases move to
   answerable_now.
3. NG06 "insider store is empty" is stale: `insider_trades_v2` holds **333,712 rows** (known_at 55%).
4. `results_xbrl.segment` / `.npa` do not exist; segment data is `results_xbrl.facts` (64,033
   `SegmentRevenue` facts across 36,294 files) but the **segment member is lost** in the stored
   context (`context='OneD'`), which is the real reason `company_segment_pnl` is needed.
5. `mkt_commodity_daily` has **no `known_at`** column: the 13 held series cannot be used as PIT
   evidence without a release-lag assumption; `commodity_price_daily` adds `known_at` + `pit_conf`.
6. `annual_financials.interest_coverage` has 0 rows <2.5× across 3,245 FY26 rows — the column cannot
   rank solvency, so `company_interest_cover` is computed from EBIT/finance cost.
7. `bse_announcements.ann` has **no index on symbol/DissemDT** (2.4 s query, `SPEED_PLAN.md §2`).
8. `mkt_bse_eq_daily.isin` is 36% filled; BSE price joins must key on `sc_code`.

---

## 3. Marginal coverage: which table to build first

Greedy set-cover over `CASE_MAP.blocking` (each case counted once, at its highest-ranked blocker):

| order | table | marginal cases | cumulative | build effort |
|---:|---|---:|---:|---|
| 1 | `chunks_v3` | 64 | 64 | 260 min parse + 15 min index |
| 2 | `commodity_price_daily` (fetch) | 62 | 126 | 1 day fetch + 10 min load |
| 3 | `macro_claim_target` | 58 | 184 | 4 h reader |
| 4 | exchange originals (fetch, U-DOC) | 46 | 230 | queue, unknown volume |
| 5 | `company_metric_series` | 42 | 272 | 20 min (+1 d concept map) |
| 6 | `xbrl_concept_map` | 35 | 307 | 1 d curation |
| 7 | `company_cost_structure` | 34 | 341 | 3 h reader |
| 8 | `company_segment_pnl` | 29 | 370 | 45 min + validation |
| 9 | `event_day0` | 24 | 394 | 6 min |
| 10 | `company_capacity_utilisation` | 23 | 417 | 6 h reader |
| 11 | `bhavcopy_backfill` (fetch) | 19 | 436 | queue |
| 12 | `company_operating_metrics` | 15 | 451 | 4 h reader |
| 13 | `capex_project` | 12 | 463 | 4 h reader |
| 14 | `company_revenue_geography` | 11 | 474 | 40 min |
| 15 | `audit_opinion_detail` | 10 | 484 | 2 h reader |
| 16 | `company_state_daily` | 9 | 493 | 15 min |
| 17 | `industry_capacity_pipeline` | 8 | 501 | 2 h |
| 18 | `company_debt_mix` | 8 | 509 | 25 min + reader |

(The greedy order is not the build order: `chunks_v3` is last in the golden rule because the pilot
must pass first. The build order is in `PILOT_SPEC.md §4`.)

---

## 4. Per-bank, per-level, per-family

Status counts, primary status only (`answerable_now` / `needs_new_table` / `needs_new_fetch` / NID):

| bank | n | now | table | fetch | NID |
|---|---:|---:|---:|---:|---:|
| shivam30 (regressions) | 30 | 15 | 10 | 5 | 0 |
| variations300 | 300 | 166 | 44 | 82 | 8 |
| open300 | 300 | 65 | 212 | 19 | 4 |
| ripple200 | 200 | 0 | 120 | 79 | 1 |
| reddit200 | 200 | 183 | 2 | 16 | 1 |

| entity level | n | now | table | fetch | NID |
|---|---:|---:|---:|---:|---:|
| stock | 568 | 349 | 149 | 67 | 3 |
| industry | 178 | 37 | 69 | 71 | 1 |
| policy | 92 | 8 | 66 | 18 | 0 |
| market-wide | 91 | 21 | 64 | 5 | 1 |
| index | 32 | 4 | 3 | 24 | 1 |
| theme | 25 | 4 | 14 | 1 | 6 |
| macro | 20 | 0 | 9 | 10 | 1 |
| market-cap bucket | 13 | 5 | 6 | 1 | 1 |
| sector | 10 | 1 | 5 | 4 | 0 |
| price band | 1 | 0 | 1 | 0 | 0 |

| family | n (membership; a case can be in several) | now | table | fetch | NID |
|---|---:|---:|---:|---:|---:|
| 1 lookup | 136 | 75 | 30 | 31 | 0 |
| 2 number | 182 | 109 | 34 | 39 | 0 |
| 3 change over time | 88 | 27 | 50 | 11 | 0 |
| 4 screen | 47 | 24 | 12 | 11 | 0 |
| 5 cross-document | 11 | 9 | 1 | 1 | 0 |
| 6 policy→companies | 88 | 37 | 27 | 16 | 8 |
| 7 company→policy | 33 | 9 | 15 | 1 | 8 |
| 8 peers | 38 | 21 | 8 | 9 | 0 |
| 9 event window | 84 | 42 | 25 | 17 | 0 |
| 11 point in time | 64 | 24 | 10 | 29 | 1 |
| 12 when/timeline | 80 | 16 | 54 | 10 | 0 |
| 13 inverse screen | 15 | 0 | 14 | 1 | 0 |
| 14 governance/audit | 60 | 25 | 35 | 0 | 0 |
| 15 move→why | 35 | 20 | 12 | 2 | 1 |
| 16 input cost | 135 | 7 | 70 | 57 | 1 |
| 17 business economics | 40 | 24 | 15 | 1 | 0 |
| 18 forward policy | 55 | 4 | 38 | 13 | 0 |
| 19 second order | 60 | 5 | 30 | 25 | 0 |
| 20 out of scope | 20 | 5 | 9 | 3 | 3 |
| undeclared (reddit) | 200 | 183 | 2 | 14 | 1 |

Read the table by column, not by row: family 13 (inverse screen) is **0 now** because every case
needs the daily market-cap/band state; family 16 (input cost) is **7 now, 57 fetch** because the
trigger series are external. Those two are the clearest statement of what the new tables buy.

---

## 5. Every NOT IN DATA case

| mid | level | answer kind | status | justification | projected |
|---|---|---|---|---|---:|
| MB0191 | theme | list | NOT_IN_DATA:refurb_sales | no published Indian refurb/second-hand electronics sales series from any exchange, body or free source | never |
| MB0193 | theme | explanation | NOT_IN_DATA:refurb_sales | same | never |
| MB0194 | theme | ranking | NOT_IN_DATA:refurb_sales | same | never |
| MB0195 | theme | number | NOT_IN_DATA:refurb_sales | same | never |
| MB0196 | theme | list | NOT_IN_DATA:refurb_sales | same, but the rubric asks for the NID statement itself | answered as NID |
| MB0197 | industry | explanation | NOT_IN_DATA:refurb_sales | same | never |
| MB0198 | index | ranking | NOT_IN_DATA:refurb_sales | same | never |
| MB0200 | theme | fact | NOT_IN_DATA:refurb_sales | same, NID statement is the expected answer | answered as NID |
| MB0445 | stock | number | NOT_IN_DATA:consensus | consensus/target price is a paid source; no free consistent cross-section | never |
| MB0616 | stock | number | NOT_IN_DATA:consensus | same, NID statement is expected | answered as NID |
| MB0627 | market-cap bucket | ranking | NOT_IN_DATA:consensus | same, NID statement is expected | answered as NID |
| MB0629 | market-wide | list | NOT_IN_DATA:investor_holdings | investor-level holdings are not published for Indian listed equities | answered as NID |
| MB0810 | macro | list | NOT_IN_DATA:forecast_not_stored | asks for a 2027 price; no forecast store, answer is a labelled scenario | never |
| MB0936 | stock | explanation | NOT_IN_DATA:unlisted_subsidiary_cost_curve | Novelis is an unlisted subsidiary; only consolidated segment P&L is held | never |

The 9 `never` rows are 0.9% of the bank. Every other case is closed by a table or a fetch — that is
the design claim, and `CASE_MAP.jsonl` names which one per case.

---

## 6. Top gaps still open (ordered by cases, after this design)

| gap | cases | why it is still open | owner |
|---|---:|---|---|
| commodity/freight/rainfall/wage series | 62 | external fetch (LME/MCX, WCI/Baltic, IMD, MGNREGA); no free bulk history for some series | fetch stream |
| originals for U-DOC cases | 46 | ARs/concall PDFs/announcement attachments not on disk; BSE pace is the constraint | fetch stream |
| bhavcopy backfill (delisted/SME/BSE-only names) | 19 | NSE/BSE archive fetch; needs `sc_code` joins | fetch stream |
| macro_claim_target quality | 47 | reader over 80k macro docs; precision must be hand-checked at ≥0.90 before use | reader stream |
| `chunks_v3` tags | 64 | needs the chunk pass; model tags gated at ≥0.90 precision | chunk stream |
| cost structure / capacity / orders / price revision | 34+23+25+33 | reader cost (2–6 h each), not schema risk | reader stream |
| index membership + sector PIT history | 7 | NSE circulars + BSE master history fetch | fetch stream |
| 10Y G-sec series (ROIC vs WACC) | 1 | not held anywhere in the DBs | fetch stream |

What is **not** on this list: any schema question. Every gap has a table in `SCHEMA_V3.sql` or a
named source in the fetch queue, or it is one of the 9 NID rows.
