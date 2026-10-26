# Plan — labels and tagging for every chunk (2026-10-27)

Draft for review by Shivam and outside reviewers. Comments welcome on any section; open questions are in §9.

## 1. Goal
Every piece of text we store (concall, deck, annual report, results notes, announcement, PIB, budget, RBI, news,
analyst opinion) must be findable by **who, when, what kind, about what, and in what market context**, using fast
filters before any vector search. Example queries the design must answer quickly:

- "Small caps with PAT growth > 30% that talked about order-book visibility in FY24 concalls."
- "Everything said about railway wagon makers within 30 days of the Budget 2025 rail capex line."
- "Nifty Midcap 150 companies whose management guided margin expansion, as of 2023-06-30, not today's list."
- "Stocks in the 5% price band whose deck mentioned a capacity addition."
- "Every analyst call on a defence stock, and whether its thesis played out within 12 months."

## 2. What the audit found (2026-10-27, read-only)
Method: every row of `raw_documents`, a random sample of 20,000 of the 2.94M `document_chunks`, `master_companies`,
and the new deck store `chunks_v2.db`.

| Label | State today | Correct? |
|---|---|---|
| Company (symbol + ISIN) | 99–100% on company docs and chunks; ISIN matches master 98–100%; chunk↔doc mismatch 0 | ✅ |
| Date (published / event) | 100% filled | ⚠️ not re-checked against filing records this run; older "investor presentation" rows are cover letters |
| Fiscal period | 0% at doc level; chunks 17% (concalls), 35% (ARs), 37% (decks) | ⚠️ sparse |
| Sector / industry | `sector_id`/`industry_id` are **0%** on chunks; master has sector for 61% (4,230 / 6,940) | ❌ |
| Market-cap bucket | not on chunks; master holds a **current-only** tier | ⚠️ not point-in-time |
| Index membership | not on chunks; `index_membership` has **one snapshot** (2026-09-30: Nifty 50/100, Midcap 150) | ⚠️ not point-in-time |
| Theme | none | ❌ |
| Price band | none on chunks; `price_bands` has 1.05M rows (2019-12 → 2026-09) | ❌ not linked |
| PAT / revenue | none on chunks; XBRL results exist | ❌ not linked |
| Content type (guidance, order book, capex, analyst vs management) | none | ❌ |
| Macro docs (PIB, budget, RBI) → sector/company | no link at all | ❌ |

Sources already in hand: `company_industry` (NSE 4-level classification: macro / sector / industry / basic industry,
2,055 ISINs), `shp_index` (quarterly promoter/public holding since 2016, 50,838 rows), `price_bands`, adjusted
prices in `truth_<date>.duckdb`, and XBRL results with filing timestamps.

## 3. Design principle: three layers, never stamp changing facts into chunks
A chunk is immutable text. A company's market cap, index membership and growth change every day or quarter.
Writing them into the chunk makes the tag stale and creates look-ahead in back-tests. So:

1. **Chunk tags (fixed at write time)** describe the text itself.
2. **Company-state tags (point-in-time, keyed by ISIN + date)** describe the company on any date.
3. **Macro-link tags** connect non-company documents to the sectors and companies they affect.

A query filters on layer 1, joins layer 2 **as of the chunk's `known_at`** (or as of a date the user names), and
joins layer 3 for macro documents. Nothing is looked up "as of today" unless the query asks for today.

## 4. Layer 1 — chunk tags
Stored on every chunk row (v2 chunk store), filled by the chunker plus a cheap classifier.

| Tag | Values | How filled |
|---|---|---|
| `isin`, `symbol_at_time` | ISIN anchor + the symbol in use on that date | from the source doc via the ISIN-history map |
| `known_at` | timestamp the market could first see the text | exchange dissemination time; else filing date; never crawl date |
| `event_date` | date the text is about (call date, meeting date) | parser |
| `fiscal_period` | FY / quarter the text discusses (Q2FY25) | parser rules + doc title + XBRL match; confidence 0–1 |
| `doc_type` | concall, deck, AR, results_notes, announcement, PIB, budget, RBI, news, opinion | source |
| `source_class` | `truth` (exchange, company, government) or `opinion` (analysts, media views) | source; opinions never mix with truth (§7) |
| `section` | concall: opening remarks / Q&A; AR: MD&A, notes, risk, related party…; deck: slide title | chunker |
| `speaker_role` | management / analyst / moderator / unknown (concalls, videos) | transcript structure |
| `content_tags` (multi) | guidance, order_book, capex, capacity, margin, pricing, demand, debt, working_capital, M&A, regulatory, management_change, dividend_buyback, risk, accounting_note | free-model classifier; precision measured on a hand-checked sample before roll-out |
| `forward_looking` | yes / no | classifier |
| `has_numbers` | yes / no, plus extracted (metric, value, unit, period) when present | parser; numbers kept apart from interpretation |
| `quality_grade` | A / B / C: parse quality (OCR or text, table damage, truncation) | chunker heuristics |
| `pit_confidence` | high / medium / low | from how `known_at` was derived |

## 5. Layer 2 — company-state table (point-in-time)
New table `company_state_daily(isin, date, …)`, rebuilt from truth data, one row per ISIN per trading day (or stored
as change intervals `valid_from` / `valid_to` to keep it small).

| Field | Source | Gap to close |
|---|---|---|
| close, 20-day avg traded value | adjusted prices | none |
| market cap + bucket (large / mid / small / micro by rank on that date, SEBI-style) | price × shares outstanding | **shares outstanding history**: derive from XBRL paid-up capital ÷ face value, and check against shareholding filings |
| price band (2 / 5 / 10 / 20 / none) | `price_bands` | none from 2019-12; before that, absent |
| F&O eligible | NSE F&O lists by date | history needed |
| index membership (Nifty 50 / 100 / 200 / 500, Midcap 150, Smallcap 250, sector indices) | NSE index-change notices | **history missing**: only the 2026-09-30 snapshot today |
| sector / industry / basic industry | `company_industry` (NSE), BSE classification for BSE-only names | fill the 39% without a sector; keep classification changes dated |
| themes (multi: railways, defence, EMS, capital goods, power T&D…) | curated theme map: basic industry + keywords + analyst themes | theme list needs agreement (§9) |
| last reported revenue, EBITDA, PAT, YoY / QoQ growth, margins | XBRL results **as of their filing time** | none; must use filing timestamp, not period end |
| promoter %, pledge %, FII / DII / MF % | `shp_index` and shareholding filings, as of broadcast time | none |
| recent material events (order wins, results date, corporate actions) | announcements | P3 announcement load |

## 6. Layer 3 — macro links
For PIB, budgets (Union and state), RBI policy and news:

- `issuer` (ministry / state / RBI department), `policy_type` (tariff, subsidy, PLI, capex allocation, rate,
  regulation, tender…), `direction` (positive / negative / neutral for the affected group), `effective_date`,
  `magnitude` when stated (₹ cr, % change).
- `affected_sectors` and `affected_basic_industries` (multi), and an optional list of directly named companies.
- Filled by a free-model reader with a fixed vocabulary; a sample hand-checked before roll-out.

This lets a query go from "Budget raised rail capex" to the wagon makers' concall chunks in one join.

## 7. Opinions database (analyst research), kept separate
The subscribed analysts' Drive reports, member videos, DailyBytes and Telegram posts are **opinions**, not truth.
They go in a separate `opinions.db` and are tagged `source_class = opinion`.

- `opinion_docs`: file or post, channel, `published_at`, `pit_source`, `pit_confidence`, video second / page.
- `opinion_calls`: ISIN, stance (buy / accumulate / watch / avoid), thesis, reasons, and testable claims
  (type, metric, threshold, horizon).
- `opinion_outcomes`: returns vs index and vs same-size peers at 1 / 3 / 6 / 12 / 24 months; each claim checked
  against later results and announcements (yes / partial / no, with evidence).
- **Dating rules.** Most Drive files were created in Drive in 2025, even where the folder name says Sep 2024, and
  331 of 529 research docs were edited after upload. So:
  - folder-name dates come first;
  - then the Drive created time;
  - docs edited after creation are `pit_confidence = low`;
  - Telegram timestamps are exact.
- **Guards:**
  - survivorship: track unfinished or deleted ideas;
  - benchmark against same-size random peers;
  - report the count of claims too vague to grade.

## 8. Order of work
1. **Fix the base.**
   - Re-check stored dates against filing records (first rows of every write job).
   - Fill master sector / industry for the 39% gap.
   - Build the ISIN-history map.
2. **Close the source gaps for layer 2:** shares outstanding history, index-membership history, F&O list history.
3. **Build `company_state_daily`** and its tests: no look-ahead, and spot-checks against known dates.
4. **v2 re-chunk with layer-1 tags** for concalls, decks, ARs, circulars (free, local).
   - Classifier tags are measured on a 300-chunk hand-checked sample before the full run.
5. **Macro-link reader** over PIB / budget / RBI.
6. **Opinions pilot**, then the full opinions load:
   - pilot: 10 videos, 10 reports, 200 Telegram posts;
   - ASR test result picks the transcriber.
7. **Coverage scorecard per tag:** fill rate and checked precision per doc type. A tag counts as "done" only when
   the scorecard shows it.
8. **Full re-embed** (paid, needs Shivam's OK) only after steps 1–7, so embeddings carry the final headers.

## 9. Open questions for reviewers
1. Market-cap buckets: SEBI rank-based (top 100 / 101–250 / rest) or fixed ₹ thresholds? Rank-based is closer to
   how funds classify.
2. Theme list: who owns it, and should analyst themes from the opinions DB feed it?
3. `company_state_daily` as daily rows (simple, large) or change intervals (small, slightly harder queries)?
4. Is a free-model classifier good enough for `content_tags`, or should a paid model label a training sample once?
5. How far back must index-membership history go: 2019 (our price start) or earlier?
6. Should opinions ever appear in normal search results, or only when asked for explicitly?
