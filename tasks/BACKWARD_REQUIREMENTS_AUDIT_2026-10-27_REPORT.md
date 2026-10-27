# Backward requirements audit — what must exist before the checklist, the ISIN map and `company_state_daily`

Date: 2026-10-27 · Worktree `20261027T125742Z-f402d945` · Read-only throughout.
Sources: `equity_intelligence.db`, `ar_facts.db`, `deck_figures.db`, `concall_facts.db`,
`results_xbrl.db`, `bse_announcements.db`, `chunks_v2.db`, `results_notes.db` (read via
`connect_ro` while a job owns it) and the dated snapshot `snapshots/truth_2026-10-19.duckdb`.
Every number below comes from a script in `tasks/audit_2026-10-27/` — see Appendix A for the
script-to-number map. Test command `python -c "print('audit only')"` → `audit only`.

**Status codes used below.** `E` exists and is usable as-of. `P` partial (state named).
`M` missing. Gaps are numbered `G0..G12` (§10); `G11`/`G12` were forced by the 30-question set that
joined `QUERY_TEMPLATES` mid-audit (§2.7).

---

## 0. Verdict in one page

1. **The order in `LABELS_TAGGING_PLAN` §8 is right but the effort is mis-sized.** The base is not
   broken in one place; it is broken in three: the ISIN anchor (§3), the share count (§4) and the
   real sector classification (§6). The first two need no network fetch; the sector repair is 1,556
   free rows plus one BSE scrip-master fetch. All three must land before `company_state_daily`
   (which does not exist) can be built.
2. **Layer 1 cannot be built on `document_chunks`.** The table has no `known_at`, `section`,
   `speaker`, `source_class`, `content_tags`, `forward_looking`, `has_numbers`, `quality_grade` or
   `pit_confidence` column at all — not "0% filled", absent. A tag that has no column cannot be
   back-filled; v3 chunking is a prerequisite, not a parallel track.
3. **ISIN history exists in a form nobody documented:** `truth_*.duckdb` `entity_id` already stitches
   549 multi-ISIN issuers (337 sequential windows), and `results_xbrl.filings_isin` already resolves
   106,405 filings to a trading ISIN. Both are built from *current* mappings, so **83 "ISIN changes"
   on 2021-10-27 are a bhavcopy source-switch artifact**, and `shp_index.isin` is stale for 74 of
   them. A naive map built from `symbol_isin_history` would encode this defect as corporate actions.
4. **Price bands are not what the plan says.** `price_bands` has **538 distinct dates** in total: one
   continuous block 2019-12-30 → 2022-02-18, then nothing until six sessions (2026-09-15 → 2026-09-22).
   2022-02-19 → 2026-09-14 is empty. "Price band by date" is answerable for ~26 months, not 6.7 years.
5. **Market-cap bucket as of a date is not computable today**, but the blocker is smaller than it
   looks: shares can be derived for 3,543 FY25+ ISINs (59% of the 5,969 with FY25+ prices) and the
   dated split/bonus factors that step the count between filings already exist
   (`adj_factor_cum`, 2,451 dated events over 1,309 entities). The missing pieces are the ISIN→entity
   map and the last 41% of share counts, not a new data feed.
6. **Index membership and F&O history do not exist in any form.** `index_membership` is 300 rows for
   one date (2026-09-30) covering Nifty 50/100/Midcap 150 only. F&O is a 200-row current flag on the
   master. `mkt_nse_index_daily` holds index *levels* for 174 indices — no constituents. Both need an
   NSE notice fetch (§5), and nothing local substitutes for it.
7. **Opinions: nothing exists.** No `opinions.db`; Telegram (4,527 posts with exact timestamps) and
   65 public videos are the only opinion-shaped rows. 25 opinion fields are `M`.
8. **Real sector fill is 9%, not 61%.** `master_companies.sector` is non-null for 4,230 of 6,940,
   but 3,733 of those are the placeholders `General Diversified` (1,981) and `Other` (1,752).
   The NSE 4-level classification covers 1,981 of 5,358 active names (37%). 1,556 of the placeholder
   rows can be repaired for free; 2,177 need a fetch.

---

## 1. Universes and denominators (measured)

| id | definition | n | split |
|---|---|---:|---|
| U_all | `master_companies` rows | 6,940 | INE equity 5,173 · non-INE prefix (ETF / partly-paid / DVR) 397 · synthetic `INE_AUTO_*` 1,370 |
| U_active | `is_active=1` | 5,358 | BSE+NSE 4,994 · BSE-only 42 · NSE-only 322 |
| U_active_eq | active and INE-equity (not synthetic) | 4,831 | — |
| U_screen | active, screenable, INE-equity | 2,744 | — |
| **U_FY25** | distinct ISIN with any `truth.events` row `known_at_utc ≥ 2024-04-01` | **6,621** | in master 4,956 → BSE+NSE 4,698 · BSE-only 133 · NSE-only 125 · **not in master 1,665** |
| U_px | distinct ISIN with a FY25+ price bar (`px_daily`) | 5,969 | — |
| U_xbrl | distinct ISIN with a FY25+ results filing | 3,543 | 45,517 filings |
| U_shp | distinct ISIN with a FY25+ shareholding quarter | 2,967 | 28,842 rows |
| U_deck | distinct ISIN with a FY25+ deck | 2,050 | 12,954 decks |
| U_ar | distinct ISIN with an AR filed since 2024-04-01 | 4,944 | — |
| U_cc_doc | distinct ISIN with a FY25+ concall doc row | 1,490 | 11,156 rows |

Coverage percentages below are against **U_FY25 = 6,621** unless a different denominator is named
(prices against U_px = 5,969; results against U_xbrl = 3,543). The 1,665 FY25+ ISINs missing from
`master_companies` are why coverage can never reach 100% until the master is rebuilt (§10, step 1).

---

## 2. Requirements table

Columns: **Needs** = the table.column that must supply it · **Exists** · **Coverage** (FY25+ unless
noted) · **History** = dated or snapshot · **PIT** = where "known at" comes from · **Spot-check**.

### 2.1 Layer-1 chunk tags (`LABELS_TAGGING_PLAN` §4; v3 `doc`/`chunk` DDL in `ARCHITECTURE_OVERHAUL` §2.2)

| # | Requirement | Needs | Exists | Coverage | History | PIT source | Spot-check |
|---|---|---|---|---|---|---|---|
| L1-01 | `isin` | `document_chunks.isin` | P | 94.1% of a 100k chunk sample (design doc: 100% on ARs) | per row, undated | none — value is the **current** ISIN, joined at load time | JISLDVREQS chunk rows carry the master ISIN ✔ |
| L1-02 | `symbol_at_time` | none | **M** | 0% | — | — | `document_chunks.symbol` is today's symbol; `symbol_isin_history` has windows but is derived from prices (BSE only from 2024-07-01) |
| L1-03 | `known_at` | `corporate_documents.bse_dissem_ts` → `publication_date` | P | 84% by dissemination (50,478/60,325 FY25+), 16% by publication date, **0 with neither** | per doc | BSE `DissemDT`; validated | RELIANCE concall: `bse_dissem_ts` 2026-07-19 vs crawl `doc_date` 2026-08-29 → crawl never used ✔ |
| L1-04 | `event_date` | `document_chunks.event_date` | P | 100% non-null on the sample, but equals `published_date`; `call_date` exists on only 5,989/21,778 concalls (27%) | per row | unclear (publisher date) | SJVN: `published_date` 2026-05-21 but `call_date` NULL → the call date and the filing date are not separable |
| L1-05 | `fiscal_period` (+confidence) | `document_chunks.fiscal_period` | P | **16.3%** of the 100k sample (design doc: 37.8% AR, 17% concall) | per row | parser; `fiscal_confidence` is non-null on 100% of rows, i.e. it is a default, not a measurement | — |
| L1-06 | `doc_type` | `raw_documents.source_type` / `corporate_documents.doc_type` | E (on other tables) | 20 source types / 8 doc types, both 100% filled | per doc | n/a | — |
| L1-07 | `source_class` (truth/opinion) | none | **M** | 0% | — | — | no opinions store exists |
| L1-08 | `section` | none | **M** | 0% | — | — | no column on `document_chunks`; `chunker_v2` can produce it |
| L1-09 | `speaker_role` | none | **M** | 0% | — | — | `concall_facts.cc_items` has statements, not speaker turns |
| L1-10 | `content_tags` (15 topics) | none | **M** | 0 of 15 topics | — | — | no `chunk_tag` / `tag_vocab` table anywhere |
| L1-11 | `forward_looking` | none | **M** | 0% | — | — | — |
| L1-12 | `has_numbers` | `results_notes.notes.has_numbers` only | P | 92,752/115,693 of that one store; 0 elsewhere | per row | parser | — |
| L1-13 | `quality_grade` | none | **M** | 0% | — | — | parse route is not recorded per chunk |
| L1-14 | `pit_confidence` | none | **M** | 0% | — | — | `corporate_documents.pit_source`/`pit_tier` exist but are not carried to chunks |

### 2.2 Layer-2 `company_state_daily` fields (`LABELS_TAGGING_PLAN` §5; DDL §2.3)

| # | Requirement | Needs | Exists | Coverage | History | PIT source | Spot-check |
|---|---|---|---|---|---|---|---|
| L2-01 | close | `px_daily.close` / `adj_close` | E | 5,969 of U_FY25 (90%) | daily 2019-01-01→2026-10-19 | exchange close (T) | RELIANCE 1,202.00 on 2026-10-19 ✔ |
| L2-02 | 20-day avg traded value | `px_daily.value_inr` | E | same as L2-01 | daily | exchange | — |
| L2-03 | shares outstanding | `results_xbrl.facts` paid-up ÷ face, stepped by `adj_factor_cum` | P | **3,543 ISINs (59% of U_px)**; 106,172 files carry both concepts | step function at each filing; split/bonus steps dated for 1,309 entities | XBRL `dissem_ts` (95% filled) | 12/16 companies within 0.5%, median 0.004% (§4) |
| L2-04 | market cap | L2-01 × L2-03 | P | ≤59% | daily once L2-03 exists | derived | — |
| L2-05 | `mcap_bucket` (SEBI rank) | needs full cross-section of L2-04 | **M** | 0% | — | derived | `master_companies.market_cap_tier` is a **current** snapshot and is wrong: MICRO 6,031 / SMALL 315 / MID 108 / LARGE 102 / NULL 384 |
| L2-06 | price band | `price_bands.band` | P | 4,121 symbols globally, but only **538 dates / 28 months**: 2019-12-30→2022-02-18 continuous (≈1,900-2,000 symbols per session) + 6 sessions in 2026-09 | per date, hole 2022-02-19→2026-09-14 | exchange bhavcopy | 1,904-2,210 distinct symbols per year in the block vs 5,936 master symbols today |
| L2-07 | F&O eligible | `master_companies.is_fno_eligible` | P | 200 rows, current only | **snapshot** | none | no dated F&O list anywhere |
| L2-08 | index membership | `index_membership` | P | 300 rows, `as_of = 2026-09-30` only; Nifty 50/100/Midcap 150 only (no 200/500/Smallcap 250/sector) | **snapshot** | none | 50/50 join to master ✔ |
| L2-09 | sector / industry / basic industry | `company_industry` (NSE 4-level) | P | 1,981/5,358 active (37%); 2,055 rows total | **snapshot** (`fetched_at`, no valid_from) | none | master says "General Diversified" where NSE says "Capital Goods / Industrial Products / Plastic Products - Industrial" (JISLDVREQS) ✘ |
| L2-10 | themes (multi) | none | **M** | 0 | — | — | `theme_map` / `company_theme_pit` do not exist |
| L2-11 | last reported revenue/EBITDA/PAT/growth/margins | `results_xbrl` + `quarterly_financials` | P | XBRL: 3,543 ISINs, 45,517 filings; `quarterly_financials` only 15,173 rows and **stale** | per filing, dated | `filings.dissem_ts` (101,508/106,613 = 95%) | SJVN exact (1,394.38 cr both); MGL XBRL `RevenueFromOperations` 2,598.9 cr vs derived 2,372.7 cr → 9.5% apart (YTD vs quarter context) ✘ |
| L2-12 | promoter %, pledge %, FII/DII/MF % | `shp_index` | P | 2,967 ISINs (45% of U_FY25), 40 quarters-ish but **1,451 distinct `quarter_end` values** (dirty key) | quarterly | `broadcast_at` 100% filled | HDFCBANK has **0** shp rows; `shareholding` table is a 40-row stub |
| L2-13 | recent material events | `truth.events` / `bse_announcements.ann` | E | 822,936 FY25+ announcements across 5,069 ISINs | per event | exact `DissemDT` | JISLDVREQS `bse_dissem_ts` == `bse_ann.DissemDT` to the millisecond ✔ |
| L2-14 | `shares_source` | none | **M** | 0% | — | — | no provenance column today |
| L2-15 | `known_at` on the state row | none | **M** | 0% | — | — | table does not exist |

### 2.3 Layer-3 macro-link fields (`LABELS_TAGGING_PLAN` §6; DDL §2.3 `macro_claim*`)

| # | Requirement | Needs | Exists | Coverage | History | PIT source | Spot-check |
|---|---|---|---|---|---|---|---|
| L3-01 | `issuer` | `pib_releases.ministry`, corporate_documents creator | E | 11,690 PIB docs (only 175 with a FY25+ published date), 207 state-budget docs, 216 RBI docs | per doc | `posted_at` / release date | — |
| L3-02 | `doc_type` (pib/budget/rbi/news) | `raw_documents.source_type` | E | 20 types | per doc | — | news: 860 rows, **0 chunks** |
| L3-03 | `policy_type` | `policy_events.instrument/stage` | P | 21,552 rows, free text, no fixed vocabulary | per event | `published_at` | — |
| L3-04 | `direction` | `policy_events.direction_for_industry` | P | present but free text | per event | — | — |
| L3-05 | `effective_date`, `magnitude` | `policy_events.effective_date`, `amount_inr_crore` | P | filled on a minority; units not normalised | per event | — | no `INR_CRORE` normalisation column |
| L3-06 | `affected_sectors` | `policy_events.sectors` (text) | P | free text, no vocabulary | per event | — | — |
| L3-07 | `affected_basic_industries` | none | **M** | 0% | — | — | `policy_events` has no basic-industry column |
| L3-08 | named companies | `policy_events.companies` (text) | P | free text | per event | — | — |

### 2.4 Opinions DB fields (`ARCHITECTURE_OVERHAUL` §2.5; `LABELS_TAGGING_PLAN` §7)

No `opinions.db` file exists. Every field below is `M`; the "local source that could fill it" is given
so the build order can be priced. Telegram is the only opinion source already in a database.

| # | Field | State | Where it would come from |
|---|---|---|---|
| O-01 | `opinion_sources.source_id/kind/name/space/access/licence_note` | M | Drive folder inventory, 18 Telegram topics, 179 videos |
| O-02 | `opinion_docs.doc_id`, `source_id`, `space`, `doc_type` | M | new file |
| O-03 | `opinion_docs.title`, `folder_path` | M | Drive inventory (3,171 files / 35 GB on D) |
| O-04 | `opinion_docs.published_at` | M | **weakest field in the design**: folder-name date → Drive `btime` (2025 even for 2024 folders) → Telegram exact |
| O-05 | `opinion_docs.date_source`, `pit_confidence` | M | derived; 331 of 529 research docs edited after upload → low |
| O-06 | `opinion_docs.edited_after_upload` | M | Drive revision metadata |
| O-07 | `opinion_docs.sha256`, `raw_path`, `page_count`, `language` | M | local PDFs / exports |
| O-08 | `opinion_docs.duration_sec`, `asr_model`, `ocr_done` | M | 179 videos / 2,066 chart PNGs; ASR not run |
| O-09 | `opinion_chunks.*` (header/body/section/speaker/t_start/t_end/isins/known_at) | M | ASR + chunker |
| O-10 | `opinion_calls.call_id/doc_id/isin/symbol/stance/conviction` | M | free-model extractor (not built) |
| O-11 | `opinion_calls.thesis/reasons_json/target_price/horizon_months/as_of` | M | same |
| O-12 | `opinion_calls.extracted_by/confidence` | M | same |
| O-13 | `opinion_claims.claim_type/metric/comparator/threshold/unit` | M | same |
| O-14 | `opinion_claims.horizon_months/quote/gradeable/grade_reason` | M | same |
| O-15 | `opinion_outcomes.horizon/measured_on/ret/bench/peer/excess` | M | needs prices (E) + peer set (G1/G4) |
| O-16 | `opinion_outcomes.verdict/evidence` | M | needs L2-11 results + announcements (E) |
| O-17 | Survivorship guard (unfinished/deleted ideas) | M | no inventory of deleted ideas |
| O-18 | Same-size random-peer benchmark | M | blocked by G1 |
| O-19 | Count of ungradeable claims | M | blocked by O-13 |
| O-20 | `source_class='opinion'` never in default search | M | needs L1-07 first |
| O-21 | Telegram posts (4,527 rows, 18 topics, 2025-05-22→2026-10-26, exact `post_timestamp`) | **E** | only opinion rows that exist |
| O-22 | 65 public DailyBytes videos / 3,571 chunks | P | older public set only, not the 179 member videos |
| O-23 | Drive research reports / DailyBytes / chart OCR | M | on D: 3,171 files; not loaded |
| O-24 | Video transcripts / ASR | M | 126.2 h; no ASR run |
| O-25 | Hinglish/devnagari symbol glossary | M | needed before O-10 can resolve ISINs |

### 2.5 `QUERY_TEMPLATES` slots

| # | Slot | Values | State |
|---|---|---|---|
| S-01 | `{entity: stock}` | symbol, old symbol, name, short name, ISIN, BSE code | P — resolution works (`resolve`) but the anchor is defective for 1,372 synthetic ISINs, 397 non-INE rows and 1,665 FY25+ ISINs absent from master (§3) |
| S-02 | `{entity: industry}` | NSE industry / basic industry | P — vocabulary exists (2,041 classified), membership dated? No: snapshot only (L2-09) |
| S-03 | `{entity: sector}` | NSE sector | P — same, plus 3,733 placeholder rows |
| S-04 | `{entity: theme}` | railways, defence, EMS… | **M** — no theme map |
| S-05 | `{entity: index}` | Nifty 50…Smallcap 250, sector indices | **M** — one snapshot, 3 indices |
| S-06 | `{entity: mcap bucket}` | large/mid/small/micro as of date | **M** — needs L2-04 |
| S-07 | `{entity: price band}` | 2/5/10/20/none | P — 28 months only |
| S-08 | `{entity: policy/macro event}` | budget line, PLI, tariff, RBI rate, PIB notice | P — 21,552 policy rows, free-text targets |
| S-09 | `{period}` | Q2FY26, FY, range, as-of, latest, since-event | P — fiscal periods 16.3% on chunks; "as-of" needs L2/L1 known_at |
| S-10 | `{metric}` | revenue | P (XBRL 3,543 ISINs) |
| S-11 | `{metric}` | EBITDA | P — XBRL concept set exists, mapping not verified per company |
| S-12 | `{metric}` | PAT | P (same as S-10) |
| S-13 | `{metric}` | margin | P — derived from S-10/S-11 |
| S-14 | `{metric}` | growth YoY/QoQ | P — `quarterly_financials` has columns but 15,173 rows only and stale |
| S-15 | `{metric}` | order book | **M** — no structured field; only prose/`content_tags` |
| S-16 | `{metric}` | capex / capacity | **M** — prose only; `deck_figures` has sporadic figures |
| S-17 | `{metric}` | debt | P — `results_xbrl` balance-sheet facts |
| S-18 | `{metric}` | promoter/FII/DII % | P — `shp_index` (2,967 ISINs) |
| S-19 | `{metric}` | pledge | P — **only** `shareholding` (40 rows) has `promoter_pledged_pct`; `shp_index` has no pledge column |
| S-20..S-34 | `{topic}` × 15 (guidance, order_book, capex, capacity, margin, pricing, demand, debt, working_capital, M&A, regulatory, management_change, dividend_buyback, risk, accounting_note) | — | **M** for all 15 (no `content_tag` store); the BSE announcement `SUBCATNAME` covers 4 of them as metadata (Financial Results, Investor Presentation, Earnings Call Transcript, Change in Management) |
| S-35 | `{doc_type: concall}` | — | P — 15,619 docs chunked, 11,156 FY25+ doc rows, 1,490 ISINs |
| S-36 | `{doc_type: deck}` | — | P — 23,321 decks / 203,368 chunks (old chunker); 1,993 FY25+ ISINs chunked of 2,050 with a FY25+ deck source |
| S-37 | `{doc_type: AR}` | — | P — 8,268 parsed of 46,573 in `corporate_documents` |
| S-38 | `{doc_type: results_notes}` | — | P — `results_notes.db` exists: 20,905 docs / 115,693 notes / 4,490 ISINs, but **Q4FY26 4,570 and Q3FY26 3,840 vs Q4FY25 93** → current quarters only |
| S-39 | `{doc_type: announcement}` | — | P — 1.95M metadata rows, **41 docs / 368 chunks** |
| S-40 | `{doc_type: PIB}` | — | P — 11,690 docs / 23,737 chunks, but body is stored lower-cased (99% per design doc) and only 175 FY25+ |
| S-41 | `{doc_type: budget}` | — | P — 35 Union + 207 state docs / 13,455 chunks |
| S-42 | `{doc_type: RBI}` | — | P — 216 docs / 2,203 chunks |
| S-43 | `{doc_type: opinion}` | — | **M** — §2.4 |
| S-44 | `{condition}` numeric filter | PAT growth >30%, mcap < ₹2,000 cr, pledge >15% | P — PAT growth yes (XBRL); mcap blocked (L2-03/04); pledge effectively missing (40 rows) |

### 2.6 Variations (`QUERY_TEMPLATES` §3)

| # | Variation | State |
|---|---|---|
| V-01 | Naming: symbol / old symbol / name / abbreviation / ISIN / BSE code / misspelling | P — 3,802 entities have >1 symbol; 2,710 ISINs have >1 symbol (ticker reuse); misspelling has no synonym table |
| V-02 | Wording: paraphrase, terse, long question, Hinglish | P — FTS5 only where chunks exist; Hinglish has no Devanagari glossary |
| V-03 | Period labels ("Q2FY26" = "Jul–Sep 2025") | P — no date-label resolver on the query path; `fiscal_period` 16.3% |
| V-04 | Scope: one stock → whole sector/index; empty case must say why | P — broad scope blocked by G1/G2/G4/G5; empty-case reasoning not implemented |
| V-05 | Basis standalone vs consolidated | P — XBRL has both (`consolidated` on 106,613 filings); `quarterly_financials` has one row per ISIN-quarter with no basis column |
| V-06 | Corporate actions: ISIN/symbol change still resolves to full history | P — prices yes (`entity_id`), documents no, ownership no (§3) |

### 2.7 The 30 fixed regression questions (`QUERY_TEMPLATES` §5, added mid-audit)

`tasks/QUERY_TEMPLATES_2026-10-27.md` gained a §5 during this audit (I did not write it: the file
was 63 lines when I read it and 106 lines later — another writer shares this worktree; see §12). It
lists 30 concrete questions as fixed regression cases. Reconciling their "gap it exposed" column
with my gap ids:

| exposed gap (their column) | gap id | state today |
|---|---|---|
| stored ratios mix price dates; no quarterly net worth | G1 | ratio inputs do not exist; `company_state_daily` absent |
| transcripts marked processed but never chunked | G6 (+ originals fetch) | 21,778 concall docs vs 15,619 chunked docs; design doc's sample: 0 of 300 concall originals on disk |
| XBRL share capital is rounded | G1 | measured: 184,207/184,474 paid-up facts are multiples of ₹1,000 → ≤ 500/face shares |
| no cross-source "latest" | G6 | no chunk `known_at`, so "latest" cannot mean "latest known" |
| segment contexts in XBRL | **new — G11** | `results_facts`/`facts` carry `context`; no per-taxonomy concept map. My MGL spot check hit exactly this (2,598.9 vs 2,372.7 cr = 9.5%) |
| banking taxonomy differs from Ind AS | **new — G11** | same map; 45,517 FY25+ filings, no bank-specific concept list |
| must use adjusted prices | none | ready (`px_daily.adj_close`, `px_nse_adj`) |
| results notes not stored | G9 | `results_notes.db` exists but only Q4FY26 4,570 / Q3FY26 3,840 docs; Q4FY25 93 |
| no "gold stocks" universe → theme map | G5 | no theme map |
| no HFC universe / peer table | G4 + G1 | no industry universe as-of; peers keyed on current industry only |
| commodity series end dates | **new — G12** | not measured here; `processing/factor_spine.py` is the intended home |
| ETFs not resolved; `etf_premium` empty | G0 | 397 non-INE rows (ETFs) inside `master_companies`; ETF tables not measured |
| no rolling-correlation tool; no dated tariff series | G12 | tool + series both absent |
| provenance across sources | G10 | macro claims have no target vocabulary |
| thin sources; "NOT IN DATA" must be stated | G10 | no empty-case reason path in the query layer |
| no dairy universe → industry peers | G4 | same as HFC row |

**Implication for the build order:** G11 and G12 are new rows the 30-question set forces. G11 is a
mapping job over data we already hold (`results_facts.context` + taxonomy), no fetch, ~1 day. G12 is
a data-coverage question outside this audit's scope and must be measured before the checklist can
promise Q18/Q20/Q23/Q24.

---

## 3. ISIN history

### 3.1 What exists today

| object | rows | what it really is |
|---|---:|---|
| `security_master` (eq + snapshot) | 8,434 | one row per ISIN incl. delisted; 246 names have >1 ISIN; no old→new link |
| `symbol_isin_history` | 9,360 | observed symbol→ISIN windows from price files; NSE 2019-01-01→, BSE **2024-07-01→**; 577 symbols with >1 ISIN, 2,710 ISINs with >1 symbol (reuse, not history) |
| `px_daily.entity_id` + `entity` | 6,250 entities | **549 entities have >1 ISIN, 337 sequential windows; 0 ISINs have 2 entities.** This is the only working multisource stitch |
| `results_xbrl.filings_isin` | 106,613 | `isin_filed`, resolved `isin`, `method`: nse_symbol 106,044 · filed 353 · bse_code 8 · unresolved 208; `same_issuer=0` on 399 |
| `isin_rekey_log` | — | repairs synthetic `INE_AUTO_*` only — not ISIN history |
| `corporate_actions` | 18,240 | SPLIT 308 · BONUS 319 · MERGER 95 · RIGHTS 253 · BUYBACK 234; `face_value` on 18,237, `ex_date` 0 null |

**There is no `symbol_isin_history` table of the kind `ARCHITECTURE_OVERHAUL` assumes**: there is no
row for "old ISIN → new ISIN with valid_from/valid_to". `entity_id` can produce one, at price-file
granularity, for 549 issuers.

### 3.2 The 2021-10-27 defect (must be fixed before any map is trusted)

| check | result |
|---|---|
| NSE `px_nse` ISIN changes with a clean sequential window | 246-334 depending on the join |
| of those, switching on exactly 2021-10-27 | **83** (79 in the `px_daily` variant), all sharing the same 9-char ISIN prefix, last NSIN digit +1 |
| BSE `px_bse` (independent feed) rows for the same scrips | **one ISIN over all 1,925 days** (HAL 541154 = `INE066F01020`; EICHERMOT 505200 = `INE066A01021`; TRIDENT 521064 = `INE064C01022`) |
| which store holds the wrong value | the **pre-2021-10-27 NSE rows**: HAL `INE066F01012` does not exist on BSE at any date; `master_companies`/`deck_sources`/`cc_docs`/`ar_docs` all say `INE066F01020` |
| blast radius | `shp_index.isin` matches the stale NSE value for **74 of the 83**; overall `shp_index.isin` disagrees with the price-file ISIN on 618 of 3,339 (18.5%) 2024+ symbol×ISIN pairs |
| other data defects in the anchor | `master_companies`: 1,370 synthetic `INE_AUTO_*` (all `is_screenable=1`), 397 non-INE (ETF/partly-paid/DVR), 2 `INE999PHASE5*`; `results_xbrl.filings`: 54 distinct invalid ISINs (`IN0000000000`, `INE 439A0401`); `shp_index`: `None`, `IN0000000000`, `INE 439A0401` |

So a map built naively from `symbol_isin_history`/`px_nse` would invent 83 corporate actions on one
day. Every ISIN in `security_master`, `symbol_isin_history`, `company_industry` and `px_daily` passes
the ISIN check digit (0 invalid); `master_companies` fails it on 19.8% of rows.

### 3.3 Ten real ISIN changes and how each joins today

All ten are confirmed by a corporate action plus a clean price window. **prices** = does the adjusted
series continue (`entity_id`); **docs** = does the document store hold anything under the old ISIN;
**shp** = which ISIN `shp_index` carries; **results** = filings split across the two ISINs.

| # | entity | kind | date | old ISIN | new ISIN | prices | docs (old/new) | shp | results (old/new) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | HDFCBANK | split 2→1 | 2019-09-20 | INE040A01026 | INE040A01034 | ✔ (177 days before) | 0 / 57 | **0 rows** | 48 / 0 |
| 2 | TRIDENT | split 10→1 | 2019-12-16 | INE064C01014 | INE064C01022 | ✔ (233) | 0 / 70 | old, 20 | 49 / 13 |
| 3 | LAURUSLABS | split 10→2 | 2020-09-30 | INE947Q01010 | INE947Q01028 | ✔ (431) | 0 / 98 | old, 20 | 48 / 13 |
| 4 | EICHERMOT | split 10→1 | 2020-08-25 | INE066A01013 | INE066A01021 | ✔ (405) | 0 / 84 | old, 21 | 50 / 12 |
| 5 | DIXON | split 10→2 | 2021-03-19 | INE935N01012 | INE935N01020 | ✔ (547) | 0 / 62 | old, 21 | 46 / 14 |
| 6 | APLAPOLLO | split 10→2 | 2020-12-16 | INE702C01019 | INE702C01027 | ✔ (483) | 0 / 85 | old, 22 | not run |
| 7 | ALKYLAMINE | split 5→2 | 2021-05-12 | INE150B01021 | INE150B01039 | ✔ (581) | 0 / 45 | 0 rows | not run |
| 8 | FINPIPE | split 10→2 | 2021-04-19 | INE183A01016 | INE183A01024 | ✔ (565) | 0 / 88 | old, 21 | not run |
| 9 | 3IINFOTECH→3IINFOLTD | demerger + rename | 2021-10-22 | INE748C01020 | INE748C01038 | ✔ | 0 / 60 | 0 old / 20 new | 22 / 43 |
| 10 | LTI→LTIM→LTM | rename, ISIN unchanged | 2022-12-05 / 2026-02-27 | INE214T01019 | INE214T01019 | ✔ | 110 / — (one ISIN) | 21, same ISIN | 64, same ISIN |

Reading of the table:

- **Prices survive every change** — but only through the snapshot's `entity_id`. In SQLite
  (`daily_price_delivery`, keyed by symbol) nothing breaks on a split, and nothing joins an old
  symbol on a rename.
- **Documents do not hold the old ISIN at all**: 0 rows under the old ISIN in all 10 cases below
  (and in the 6 further cases). That is not a success — it means the doc store's ISIN was
  *rejoined to the current ISIN at load time*, so the filing's own ISIN is lost and a document can
  never be attributed to the security that was actually listed that day.
- **Ownership breaks**: `shp_index` carries the **old** ISIN for 5 of the 8 split cases, and
  `master_companies` has no row with that ISIN → the shareholding series cannot join the master.
- **Results are split**: 46-50 filings under the old ISIN and 12-14 under the new one for the same
  company, because `filings_isin` resolves by *current* symbol.
- **Renames are the bigger population**: 3,802 entities have >1 symbol with one ISIN
  (e.g. KALPATPOWR→KPIL 2023-06-06, NITESHEST→SATCH 2024-07-01, LKPFIN→GYFTR 2026-04-28,
  YAARII→YAARI→IBULLSLTD), and 2,710 ISINs have >1 symbol because a ticker was reassigned to a
  different company — the entity table handles the first group and cannot handle the second.

The remaining confirmed cases (measured, same join columns):

| entity | kind | date | old ISIN | new ISIN | docs old/new | shp old/new | master old/new | xbrl old/new |
|---|---|---|---|---:|---:|---:|---|---|
| SUPPETRO→SPLPETRO | rename + new ISIN | 2022-05-24 | INE663A01017 | INE663A01033 | 0 / 63 | 0 / 0 | inactive / active | 14 / 10 |
| HEXAWARE→HEXT | rename + new ISIN (delisted) | 2025-02-19 | INE093A01033 | INE093A01041 | 0 / 53 | 0 / 8 | none / active | 14 / 15 |
| PHILIPCARB→PCBL | rename + new ISIN | 2022-01-13 | INE602A01023 | INE602A01031 | 0 / 75 | 0 / 0 | inactive / active | 45 / 14 |
| FOURTHDIM→GVPTECH | rename + new ISIN | 2023-07-31 | INE382T01014 | INE382T01030 | 0 / 0 | 2 / 0 | none / inactive | 0 / 17 |
| SONAMCLOCK→SONAMLTD | rename + new ISIN | 2023-11-15 | INE00LM01011 | INE00LM01029 | 0 / 0 | 21 / 0 | inactive / inactive | 12 / 7 |
| KRATOSENER→LORDSMARK | ticker reassigned to another issuer | 2025-10-16 | INE567L01017 | INE567L01025 | 0 / 7 | 0 / 0 | none / active | 0 / 0 |

The last row is the dangerous pattern: `KRATOSENER` and `LORDSMARK` are different companies that
shared a ticker, and `px_daily.entity_id` stitches them into one "entity" (INE567L) because one ISIN
window looks sequential. Any map built from windows alone will inherit that error.

Also confirmed as renames-with-new-ISIN: SUPPETRO→SPLPETRO (2022-05-24, `INE663A01017` →
`INE663A01033`, now delisted), HEXAWARE→HEXT (2025-02-19, `INE093A01033`, delisted),
FOURTHDIM→GVPTECH (2023-07-31, `INE382T01014`), SONAMCLOCK→SONAMLTD (2023-11-15,
`INE00LM01011` → `INE00LM01029`), PHILIPCARB→PCBL (2022-01-13, `INE602A01023` → `INE602A01031`),
KRATOSENER→LORDSMARK (2025-10-16, `INE567L01017` → `INE567L01025`).

---

## 4. Shares outstanding: XBRL paid-up ÷ face value vs the AR-stated total

Method: latest filing with both `PaidUpValueOfEquityShareCapital` and
`FaceValueOfEquityShareCapital` (both present in **106,172** files, 45,408 of them FY25+), divided by
face value; compared with the exact total-share line in `ar_facts` (`unit='number'`,
strict total-share item, weighted-average/EPS rows excluded). 20 companies drawn by hash from active
screenable names.

| symbol | tier | XBRL period | face | derived shares | AR total | AR FY | err % | cause |
|---|---|---|---:|---:|---:|---|---:|---|
| RELIANCE | LARGE | 2026-06-30 | 10 | 13,533,000,000 | 13,532,472,634 | FY26 | 0.004 | rounding |
| INFY | LARGE | 2026-06-30 | 5 | 4,050,000,000 | 216,233,685 | FY26 | 1773.0 | AR row is **not** the total-share line (matcher artifact); the XBRL count matches the real 4.05 bn |
| SIEMENS | LARGE | 2026-06-30 | 2 | 356,000,000 | 356,120,255 | FY23 | −0.034 | stale AR |
| IDBI | SMALL | 2026-09-30 | 10 | 10,752,400,000 | 10,752,402,175 | FY26 | −0.000 | rounding |
| SJVN | SMALL | 2026-06-30 | 10 | 3,929,800,000 | 3,929,795,175 | FY26 | 0.000 | rounding |
| MGL | SMALL | 2026-06-30 | 10 | 98,780,000 | 98,777,778 | FY26 | 0.002 | rounding |
| CRISIL | SMALL | 2026-06-30 | 1 | 73,100,000 | 73,129,790 | FY25 | −0.041 | rounding |
| ASTRAL | MID | 2026-06-30 | 1 | 269,000,000 | 268,650,163 | FY26 | 0.130 | rounding + ESOP |
| KRBL | MICRO | 2026-06-30 | 1 | 228,900,000 | 228,889,892 | FY25 | 0.004 | rounding |
| AVANTEL | MICRO | 2026-06-30 | 2 | 265,714,000 | 265,710,850 | FY26 | 0.001 | rounding |
| GEOJITFSL | MICRO | 2026-06-30 | 1 | 279,122,000 | 279,122,119 | FY26 | −0.000 | exact |
| BIKAJI | MICRO | 2026-06-30 | 1 | 250,736,000 | 250,736,400 | FY26 | −0.000 | exact |
| PROTEAN | MICRO | 2026-06-30 | 10 | 40,620,000 | 40,446,732 | FY24 | 0.428 | new issue after AR |
| FEDFINA | MICRO | 2026-09-30 | 10 | 375,140,000 | 368,957,088 | FY24 | 1.676 | new issue after AR |
| TREJHARA | MICRO | 2026-06-30 | 10 | 24,116,700 | 14,516,298 | FY26 | 66.1 | rights/pref issue not in AR total |
| JISLDVREQS | MICRO | 2026-06-30 | 2 | 733,900,000 | 19,294,304 | FY23 | 3703.7 | AR row is the DVR line; XBRL covers equity+DVR |
| PREMCO, RTSPOWR | MICRO | — | — | no paid-up/face pair in the last 8 filings | — | — | — | coverage hole |
| ARVEE, SVLL | MICRO | — | — | derived only | no strict AR row | — | — | AR fact missing |

**Error rate.** 12 of 16 comparable companies agree within 0.5% (10 within 0.01%). The 4 outliers are
not derivation errors: 1 DVR/partly-paid artifact (JISLDVREQS), 1 where the AR row is not a
total-share line (INFY — the derived value is the correct one), and 2 where capital was raised after
the AR date (FEDFINA +1.7%, TREJHARA +66%). Two companies (PREMCO, RTSPOWR) have no paid-up/face pair
in their last 8 filings; two (ARVEE, SVLL) have no strict AR row to compare against. The real ceiling
is structural, not accuracy:

- paid-up is rounded to the nearest ₹1,000 in **184,207 of 184,474** facts, so the derived count is
  off by at most `500/face` shares (500 at face ₹1, ≤ 3 shares for a 1-billion-share company, but
  0.5% for a company with 100k shares);
- 99.9% of paid-up values are in **rupees** in this store, not thousands (the `holding()` docstring's
  "reported in thousands" is wrong — the gap is rounding to ₹1,000, not scaling);
- coverage: 3,543 FY25+ ISINs have a derivable count = **59% of U_px**; 2,426 FY25+ price ISINs have
  no paid-up/face pair (a share of those are non-equity rows that should not get a count anyway).

**To turn the step function into a daily series** you need the dated split/bonus factors:
`truth.adj_factor_cum` has 2,451 dated events over 1,309 entities (HDFCBANK: one event 2019-09-19,
`exp(tot_l)=0.25` covering two 2:1 splits). Outside `adj_factor_cum` there is no dated share-step
source, and rights/buyback changes are not in it — they only appear at the next XBRL filing.

---

## 5. Index membership history and F&O list history

| need | what exists | what blocks it | what would fill it |
|---|---|---|---|
| Index membership by date (Nifty 50/100/200/500, Midcap 150, Smallcap 250, sector indices) | `index_membership` 300 rows, one `as_of` 2026-09-30, 3 indices; `master_companies.is_nifty50/100/200/500` current flags only (50/100/200/496) | no constituent history anywhere; `mkt_nse_index_daily` has 174 index **levels**, not members; BSE announcement feed has no index-change category (0 rows) | NSE index-change notices (circulars + "Index maintenance" notices) 2019→2026. One notice per rebalance; broad indices rebalance semi-annually (Sep/Mar) → ~15 notices per index → ~100 documents for the 8 broad indices. **Fetch needed.** |
| Sector-index membership | nothing | sector indices are not in `index_membership` at all | same NSE notices (sector index factsheets give current members only — history needs notices) |
| F&O eligible by date | `master_companies.is_fno_eligible` 200 rows (current); 11 BSE headlines mention futures | no dated list; securities are added/removed monthly and banned periodically | NSE "securities in F&O" monthly circulars + ban-period list, 2019→2026 (~96 files). **Fetch needed.** |
| Index weights / free-float | nothing | — | index factsheets (current only) |
| Backcast alternative | index TRI + price of each stock can *infer* membership only weakly (a stock's correlation), not reliably | inference is not evidence | not recommended |

The fieldwork needed is small (≈200 documents for all 8 years) but it is a **network fetch** and the
only one of the three "base" gaps that cannot be closed locally.

---

## 6. Sector, industry and basic industry

| measure | BSE+NSE | BSE-only | NSE-only | total |
|---|---:|---:|---:|---:|
| active in master | 4,994 | 42 | 322 | 5,358 |
| `master_companies.sector` non-empty | 2,306 | 42 | 322 | 2,670 |
| of those, placeholder (`General Diversified`/`Other`) | 1,813 | 42 | 320 | **2,175** |
| **real master sector** | 493 | 0 | 2 | **495 (9.2%)** |
| NSE 4-level classification (`company_industry`) | 1,888 | 17 | 76 | **1,981 (37.0%)** |
| missing a real classification | 3,106 | 25 | 246 | **3,377** |

- The plan's "master has sector for 61%" is a non-null count that includes 3,733 placeholders.
- `company_industry` is complete within itself (2,041/2,055 have all four levels, 728 also carry
  `index_list`), but it is a **snapshot** (`fetched_at`, no `valid_from`) and covers only the NSE
  list at fetch time.
- **1,556 of the 3,733 placeholders already have a NSE classification in `company_industry`** — a
  free, no-fetch repair.
- 2,177 active names have no classification anywhere: **25 of them are the BSE-only actives** (the
  other 17 BSE-only names are classified through the NSE list), and the remaining 2,152 are BSE+NSE
  names never in an NSE list. BSE's own `Industry`/`Sector` fields on the scrip master are the only
  local-source-free filler; that fetch is one BSE scrip-master call, not a per-company crawl.
- Nothing is dated: classification changes (NSE revises the 4-level tree) would need `valid_from`
  intervals; today a single `fetched_at` is all there is.

---

## 7. Market-cap bucket as of a date: can it be computed today?

**No, but the blocker is 3 local jobs, not a feed.**

| input | state | verdict |
|---|---|---|
| adjusted close, daily 2019→2026-10-19 | `px_daily.adj_close`, 5,969 FY25+ ISINs | ready |
| shares outstanding, dated | XBRL steps for 3,543 ISINs (59% of U_px) + split/bonus factors 2,451 events | ready for ~59% |
| split/bonus stepping between filings | `adj_factor_cum` (dated, per entity) | ready |
| ISIN→entity stitch | `entity_id` in the snapshot | ready inside the snapshot only; not in SQLite, not with `master_companies` |
| SEBI rank cut | needs a complete cross-section: 5,969 prices but 3,543 shares | **blocked by the 41% missing share counts** |
| current-only tier check | master tier is MICRO for 6,031 of 6,940 — unusable as a sanity check | must be rebuilt, not trusted |

Also blocking a *correct* mcap: partially-paid shares (11 `*PP` symbols), DVR lines (`JISLDVREQS`),
ETFs (118 non-INE rows in master) and preference capital must be excluded, or mcap double-counts.

---

## 8. Price bands by date

`price_bands`: 1,054,354 rows, `date` 2019-12-30 → 2026-09-22, 4,121 distinct symbols, band values
`20` (563,189), `5` (310,561), `10` (91,807), `No Band` (86,984), `2` (1,472), `40` (332),
`No band` (9 — casing defect that will break a strict equality filter).

| month | rows | symbols |
|---|---:|---:|
| 2019-12 (30-31 only) | 3,812 | 1,904 |
| 2020-10 … 2022-01 | 38,611 … 42,760 | 1,947 … 2,090 |
| 2022-02 (to the 18th) | 28,606 | 2,087 |
| **2022-02-19 … 2026-09-14** | **0** | **0** |
| 2026-09 (15th-22nd, 6 sessions) | 21,203 | 3,554 |

28 distinct months and **538 distinct dates** exist in total. The plan's "none from 2019-12" is right
at the start, but the series is **not** continuous to 2026-09: 4.6 years are missing. "Stocks in the
5% price band" works for 2019-12→2022-02 and for the six sessions in 2026-09. Filling it needs the NSE
`sec_bhavdata_full` "price band" field (or the NSE surveillance files) for 2022-02-19 onward — a
**fetch**.

---

## 9. Template feasibility: 11 families × 8 entity levels

Codes: **NOW** = answerable with correct PIT today · **Gx** = answerable once gap `Gx` closes
(numbers in §10) · **NO** = not answerable from our data (reason given).

| family \ level | stock | industry | sector | theme | index | mcap bucket | price band | policy |
|---|---|---|---|---|---|---|---|---|
| 1 Lookup | **NOW** for doc/period; G6 for `{topic}` | G6+G4 | G6+G4 | G5 | G2 | G1 | **NOW** 2019-12→2022-02, else G8 | G10 |
| 2 Number | **NOW** for Ind AS metrics (XBRL 3,543 ISINs); G11 for banks/segments | G4 (no dated industry membership) | G4 | G5 | G2 | G1 | G8 | G10 |
| 3 Change over time | **NOW** for metrics; G6 for guidance-vs-delivered | G4 | G4 | G5 | G2 | G1 | G8 | G10 |
| 4 Screen | G1 (mcap conditions), G6 (topic conditions) | G4 | G4 | G5 | G2 | G1 | G8 | G10 |
| 5 Cross-document | G6 + originals fetch (B5a) | G6+G4+fetch | G6+G4+fetch | G5 | G2 | G1 | G8 | NO (no per-company macro text per level) |
| 6 Policy → companies | G10 | G10+G4 | G10+G4 | G10+G5 | n/a (an index is not a policy target) | G10+G1 | G10+G8 | **NOW** (21,552 policy events with direction/amount as text) |
| 7 Company → policy | G10 | G10+G4 | G10+G4 | G10+G5 | G2+G10 | G1+G10 | G8+G10 | **NOW** (same rows, one join) |
| 8 Peers | **NOW** (same-industry via `company_industry`) for metrics; G1 for same-size | G4 | G4 | G5 | G2 | G1 | G8 | NO (a policy has no peers) |
| 9 Event window | **NOW** for announcements (822,936 FY25+ with exact `DissemDT`); G6 for chunk text | G4 (needs per-company windows first) | G4 | G5 | G2 | G1 | G8 | G10 |
| 10 Opinion vs truth | G7 | G7 | G7 | G7+G5 | G7+G2 | G7+G1 | G7+G8 | G7+G10 |
| 11 Point-in-time (any family as of `<date>`) | G6+G1 (chunk `known_at`, daily state) | G4+G6 | G4+G6 | G5+G6 | G2 | G1 | G8 | G10 |

Notes that make the matrix honest:

- **"NOW" for stock-level families** means: entity resolves, price and XBRL metrics answer as-of with
  a filing timestamp, and announcement text is dated. It does **not** mean the answer includes typed
  topic tags or `company_state_daily` — those are G6/G1.
- **Every level above "stock" needs a membership table that is dated.** Today not one of them is
  (industry snapshot, 3-index snapshot, no theme, no bucket, 538 band dates). Family 4 therefore fails
  at 7 of its 8 levels outright and only partially works at stock level (metric conditions only).
- **Family 10 fails everywhere** because `opinions.db` does not exist; it is the only family with no
  partial credit at all.
- **Family 6/7 are half-built**: `policy_events` is real and dated (21,552 rows), but its
  sector/company targets are free text, so the "→ companies" join has to go through a vocabulary
  that does not exist yet (G10).
- **G11 is not optional**: two of the 30 fixed questions (Q11 segment revenue, Q12 bank NPA) fail
  without it, and my MGL spot check already showed a 9.5% mismatch caused by an unfiltered XBRL
  context.

---

## 10. Build order — smallest set of gaps, dependency order

| # | gap | close it by | effort (est.) | source | fetch? | unblocks |
|---|---|---|---|---|---|---|
| **G0** | ISIN anchor is defective (83 false changes, 1,370 synthetic ISINs, 1,665 FY25+ ISINs absent from master, stale `shp_index.isin`) | Build `security(self, isin, valid_from, valid_to, source, confidence)` from BSE scrip-code windows (independent, clean) + `px_daily.entity_id` + `corporate_actions`; validate every ISIN (check digit + one-source rule); repair `shp_index.isin`; move synthetic rows to a quarantine list | **2 days** | local: `px_bse`, `security_master`, `entity`, `corporate_actions`, `symbol_isin_history` | no | everything below |
| **G1** | shares outstanding + daily market cap | XBRL paid-up/face step function × `adj_factor_cum` steps; exclude partly-paid/DVR/ETF; write `company_state_daily` with `known_at` per row | **2 days** | local: `results_xbrl.facts`, `adj_factor_cum`, `px_daily` | no (41% coverage holed) | F2/F4/F8/F11 at bucket level; checklist conditions |
| **G4** | sector/industry PIT | (a) copy the 1,556 placeholders from `company_industry`; (b) fetch BSE scrip-master industry for the rest; (c) store as `valid_from` intervals | **0.5 day** + fetch | local + BSE scrip master | yes, small | F2-F5, F8 at industry/sector; family 4 at 2 levels |
| **G8** | price band 2022-02-19→2026-09-14 | pull the band field from NSE bhavcopy/surveillance files per date; normalise `No band` casing | **0.5 day** + fetch | NSE | yes | family 1/4 at price-band level |
| **G2** | index membership history | parse NSE index-change notices 2019→2026; store `company_membership_pit` | **1.5 days** + fetch | NSE circulars | yes | F1-F5 at index; "as of 2023-06-30" variants |
| **G3** | F&O history | parse NSE monthly F&O lists + ban periods | **1 day** + fetch | NSE | yes | `is_fno` in state |
| **G5** | theme map | curated `theme_map` (basic industry + keywords) from the 15-topic vocabulary; analyst themes later from opinions | **1 day** | local + curation | no | F1-F5 at theme |
| **G6** | layer-1 v3 chunk tags (`known_at`, `section`, `speaker_role`, `content_tags`, `forward_looking`, `has_numbers`, `quality_grade`, `pit_confidence`) | chunker v3 + deterministic tagger, then the 300-chunk hand check at precision ≥ 0.90 | **5-8 days** (of which 2-3 days are originals inventory, G6a) | local chunker_v2 + free models | **yes for originals** (§3.1 of the design doc: concalls 0/300 on disk) | F1/F3/F5/F11, topic slots, families 1-5 |
| **G10** | macro claim targets | `macro_claim` / `macro_claim_target` reader over PIB/budget/RBI with the fixed vocabulary | **3 days** | local text (`pib_releases.body`) | no (bodies held) | F6/F7, family 4 at policy level |
| **G7** | opinions DB | pilot: 10 videos, 10 reports, 200 Telegram posts → `opinions.db` | **3 days** pilot | local Drive/D: + Telegram | no (ASR may need a paid endpoint) | family 10 |
| **G9** | results-notes backfill | one PDF per company-quarter, notes pages only | **largest**: ~41.6k filings to dedupe and fetch | BSE | yes | F1/F5 at results_notes |
| **G11** | XBRL concept map per taxonomy (Ind AS / banking / NBFC / insurance) + segment contexts | map `concept`+`context` → metric for the 45,517 FY25+ filings; validate against annual-report totals | **1 day** | local: `results_xbrl.facts` | no | family 2 for banks/segments; my MGL 9.5% discrepancy |
| **G12** | dated macro/commodity series (crude, coal, tariff, FX, El Niño) with end dates | bring `factor_spine` series up to date and expose them to queries | **not measured** | external series | probably yes | Q18/Q20/Q23/Q24 in `QUERY_TEMPLATES` §5 |

**Dependency order for a first full run:** G0 → G4 → G1 → G8 → G3 → G2 → G5 → G6 → G10 → G7 → G9
(G11 parallel to G1, G12 measured before the checklist commits to the macro questions).
G2/G3/G8 are fetches that can run in parallel with G1; G6 cannot start before its originals inventory
(design doc step B5a). The **smallest set that makes one shared checklist script possible** is
**G0 + G4 + G1 + G2 + G5 + G6 + G11** — seven items, of which G2 is a fetch and G6 needs its
originals inventory (also a fetch); that still leaves family 10, G12 and the results-notes doc type
out.

---

## 11. Open questions for Shivam

1. **Is "as-of" defined by filing time or by the end of the day the filing landed?** The XBRL
   `dissem_ts` is a timestamp; the daily state rows are per session. A 19:50 filing on T should not be
   in T's close-based mcap. Pick one rule before G1 writes 13M rows.
2. **`company_state_daily` daily or intervals?** At 5,969 price ISINs × 1,936 sessions ≈ 11.6M rows
   for the price part, but only ~40-60 change dates per company for shares/bucket/band. Daily rows are
   simpler to query; intervals are ~50× smaller for the piecewise fields. I would do daily for
   close/band and intervals for shares/bucket — confirm.
3. **Do partly-paid, DVR and ETF lines get their own state rows, or are they excluded from mcap ranks?**
   Today they are inside `master_companies` (397 non-INE + 11 `*PP` + `JISLDVREQS`), and that alone
   corrupts a SEBI rank cut.
4. **The 1,665 FY25+ ISINs missing from `master_companies`: rebuild the master from `security_master`
   (8,434 rows) or keep the 6,940-row master and mark the rest out-of-universe?** These are the
   delisted and BSE-only names the FY25+ universe still contains.
5. **Price band gap:** is the band needed before 2022 for the tests, or is "since 2022" acceptable?
   That decides whether G8 is 0.5 day or a 4-year backfill.
6. **Index history depth:** 2019 (our price start) or earlier? The 2023-06-30 example in
   `LABELS_TAGGING_PLAN` §1 needs 2019-2026; anything earlier is a new fetch budget.
7. **Opinions dating:** with 331/529 docs edited after upload, do we accept folder-name dates at
   `pit_confidence ≤ 0.5`, or is any claim graded from them void (§7 says edited docs are low
   confidence — the checklist needs a floor, e.g. "never grade a claim below 0.6")?
8. **Do we trust the BSE scrip-master industry field as the filler for the 2,177 unclassified names?**
   It is a second classification tree, not the NSE one; mixing them silently would break sector
   aggregation.

---

## 12. Context-pack drift (repo/data disagree with the pack)

1. `results_notes.db` **exists and is live** (20,905 docs / 115,693 notes, Q4FY26 4,570) but the pack's
   DB table does not list it (only the task brief mentions it, as a running job's file).
2. The pack says `document_chunks` is 2.3M via `sqlite_stat1`; the actual `COUNT(*)` is **2,939,096**
   (the design doc already flags this).
3. The pack's `price_bands` row implies coverage 2019-12→2026-09; the middle 4.6 years are absent (538 dates in total).
4. The pack's `symbol_isin_history` row reads like an ISIN-history map; it is a symbol→ISIN observation
   table, and `equity_intelligence.shareholding` (40 rows) is a stub, not a shareholding store.
5. `master_companies` sector "61%" is a non-null count; real coverage is 9%.
6. `company_industry` is 2,055 rows in `equity_intelligence.db` and 3,178 in the snapshot (the snapshot
   copy is older/newer than the live one — use the live table).
7. **Concurrent writer in this worktree.** `tasks/QUERY_TEMPLATES_2026-10-27.md` was 63 lines when I
   first read it and 106 lines later, with a new §5 (30 fixed questions). I did not modify it
   (`git status` shows it as a working-tree change I did not make); I reconciled it in §2.7 rather
   than reverting it. The controller should check whether another worker shares this checkout.

---

## Appendix A — where every number comes from

Scripts are in `tasks/audit_2026-10-27/`, all read-only (`connect_ro`, DuckDB `read_only=True`), all
bounded. Run: `python tasks/audit_2026-10-27/<script>`.

| script | answers |
|---|---|
| `01_schema.py` | table/column inventory; absence of `company_state_daily`, `market_cap`, F&O, `chunks_v3.db`, `opinions.db`; `results_notes.db` presence |
| `02_universe.py` | master universe and exchange split; sector/industry fill; `index_membership`; price-band range and by-year; `symbol_isin_history`; `corporate_actions`; `shp_index`; `results_xbrl` totals |
| `03_duckdb.py` | snapshot table list; `px_daily` entity/ISIN stitching (549 multi-ISIN entities, 0 shared ISINs); `events` kinds |
| `04_isin.py` | 334 sequential ISIN windows from `px_daily`; old ISINs in master 17/334 |
| `05_isin_classify.py` | switch-date clustering (2021-10-27 ×79); corporate action within 90 days |
| `06_isin_truth.py` | corrected check-digit validation per store (master 19.8% invalid; others 0-1.4%); per-case cross-source ISIN |
| `07_isin_source.py` | the independent BSE proof (HAL/EICHERMOT/TRIDENT single ISIN over 1,925 days); `shp_index` agreement 2,721/3,339; 83-case store comparison |
| `08_isin_real.py` | 262 BSE scrip-code ISIN windows; 103 with a split/bonus; symbol-rename populations |
| `09_isin_final.py` | the 8 split cases with old/new ISIN, action, doc/shp/master/prices join counts |
| `10b_shares_cov.py` | 106,172 files with both XBRL concepts; 45,408 FY25+; paid-up rupee units; 184,207/184,474 multiples of 1,000 |
| `10c_shares_table.py`, `10d_shares_strict.py` | the 20-company table in §4 |
| `11_market_state.py` | `adj_factor_cum` events; index/F&O inventory; price bands by month; sector fill split |
| `12_layer1.py` | `document_chunks` fill (16.3% fiscal, 0% sector/industry); `corporate_documents` PIT fill; `results_notes.db`; `chunks_v2.db`; 5-entity spot checks |
| `13_spot.py` | non-equity rows in master; BSE announcement FY25+ volume and categories; `events` FY25+; 5 equity spot checks (concall date, XBRL revenue, price) |
| `14_universe.py` | U_FY25 = 6,621 with the 4,956/133/125 split and 1,665 outside master; per-store FY25+ ISIN counts; `filings_isin` method counts; placeholder-sector repair counts |
| `15_isin_extra.py` | join results for the six rename/demerger cases and the LTI control (§3.3 second table) |
| `16_bands_dates.py` | price-band date continuity: 538 dates, the 6 sessions in 2026-09, the 2022-02-18 stop |

Key queries, verbatim, in the scripts: `px_daily` windows
(`GROUP BY entity_id, isin` + `LEAD()`), the paid-up/face join
(`facts WHERE concept IN ('PaidUpValueOfEquityShareCapital','FaceValueOfEquityShareCapital') GROUP BY file HAVING COUNT(DISTINCT concept)=2`),
the price-band month histogram (`GROUP BY substr(date,1,7)`), the FY25+ universe
(`SELECT DISTINCT isin FROM events WHERE known_at_utc >= TIMESTAMP '2024-04-01'`), and the
known-at fill (`corporate_documents WHERE (publication_date>='2024-04-01' OR bse_dissem_ts>='2024-04-01')`).

## Appendix B — coverage table used throughout (one screen)

| store | FY25+ ISINs | known/filed dated? |
|---|---:|---|
| prices (`px_daily`) | 5,969 | daily, exchange close |
| results (`results_xbrl.filings`) | 3,543 | 95% `dissem_ts` |
| shareholding (`shp_index`) | 2,967 | 100% `broadcast_at` |
| annual reports (`ar_docs`) | 4,944 | filing date |
| decks (`deck_sources`) | 2,050 | 100% BSE announce time |
| concalls (`corporate_documents`) | 1,490 | 92% `bse_dissem_ts`, 27% `call_date` |
| announcements (`events`) | 5,069 | exact `DissemDT` |
| **U_FY25 (union)** | **6,621** | — |

Tool calls before the first worktree edit: **9** (context pack, 3 input docs, 2 probes, 2 shell
checks, one read of `readonly.py`). Total tool calls for this audit: **≈90** (18 audit scripts,
6 schema/probe scripts, 1 DuckDB probe, 1 test run, ~30 report edits, 1 progress note).


