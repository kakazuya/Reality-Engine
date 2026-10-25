# EVAL25: question bank (Q1–Q10 from QA10_BRIEF.md, Q11–Q25 from Shivam 2026-10-25)

Tiers: **F** = pure fact, one store. **R1–R5** = fact + reasoning, denser as the number rises.
"Needs" lists the stores a correct answer must cite. "Coverage" is what Claude checked on 2026-10-25.
Reference answers (key) live in `EVAL25_KEY.md` and are verified by Claude before they are used to grade.

| # | Tier | Question (short) | Needs | Coverage / known gap |
|---|---|---|---|---|
| 1–10 | F | see `QA10_BRIEF.md` | — | Q6: BSE announcements end 2026-10-19; Q9: no cross-source "latest" |
| 11 | F | KRISHNADEF revenue segments + absolute numbers, latest quarter | results XBRL segment facts, deck facts | check segment contexts in `results_facts` |
| 12 | F | Bank of Maharashtra net NPA %, latest quarter | results XBRL (banking taxonomy), deck | banking concepts differ from Ind AS taxonomy |
| 13 | F | 3-year stock price CAGR of BSE 533339 (ZENTEC) | `px_bse_adj` / `px_nse_adj` | must use adjusted prices; state start/end dates |
| 14 | F | Scrip 516072 (VISHNU): Note 5 of the latest quarterly results, and the geographic split | results filing text, XBRL segment/geo | **gap risk:** results PDF notes text is not stored |
| 15 | F | VINCOFE public shareholding as of Sep 2026 | `shp_index` / `shp_facts` | — |
| 16 | R1 | Why gold stocks fell in Jun–Jul 2026 (PIB before transcripts/decks) | `pib_releases_fts`, `mkt_commodity_daily` gold + usdinr, prices of the gold universe, concalls | needs a "gold stocks" universe |
| 17 | R2 | Leader in home-finance securitised disbursement among listed NBFC/HFCs; QoQ/YoY winner with net NPA rise ≤ 2 pp | XBRL + deck facts + concall items across the HFC universe | needs an HFC universe and a peer table; securitisation is mostly in decks/concalls |
| 18 | R3 | OMCs (IOC, BPCL, HPCL): record Q4FY26 profit then bigger Q1FY27 loss; graded on the **earliest PIT date** the trend was visible | crude_brent/wti, usdinr, PIB (pricing/excise), results, concalls, prices | commodity daily ends 2026-10-06 (fine for this window) |
| 19 | R3 | BSE 543437 = MONQ50 (Motilal Oswal Nasdaq Q 50 ETF): jump 10–18 Sep 2026, fall 18–28 Sep; NAV tracking error | `etf_px`, `fund_nav`, `etf_inav` (underlying index + FX), usdinr | `resolve("543437")` returns nothing today (ETFs not resolved); `etf_premium` table is empty |
| 20 | R4 | BSE 500655 (Garware Hi-Tech): sharp US-tariff impact in Mar 2025, but from Mar 2026 negative correlation with price | prices, tariff event timeline (PIB/news), concalls, AR geo exposure | needs a rolling-correlation tool and a dated tariff-event series |
| 21 | R4 | RBI repo hike on 7 Oct 2026, first in 44 months: causes; was it published by PIB or only by RBI? | `raw_documents` RBI_Monetary_Policy (to 2026-10-07), MPC minutes, PIB FTS, CPI/commodity series | grade includes the PIB-vs-RBI provenance check |
| 22 | R5 | Why second-hand electronics/laptop sales rose in CY2026; who benefits; structural or cyclical | PIB, policy_events, concalls/decks, news (only 2026-09-17..26) | thin sources; "NOT IN DATA" parts are acceptable if stated |
| 23 | R5 | India's coal gasification policy drafts; what differs from the earlier scheme | PIB FTS, policy_events, Budget docs | coal_newcastle price ends 2025-12-26 |
| 24 | R5 | BSE 539889 (PARAGMILK) on El Niño 2026 in transcripts; impact on dairy companies and how they tackle it | concall items/chunks for PARAGMILK + dairy universe | needs a dairy universe |
| 25 | R5 | How the tax holiday for data-centre operations in India has played out so far | Budget, PIB, policy_events, concalls/decks of DC players | — |

## Rules for every run
- Local data only. No internet, no model memory: every claim cites an evidence id (db.table + key, or doc + page).
  A claim without a valid citation scores 0, even if true.
- `as_of` = the question's date context; evidence with `known_at` after it does not count (matters for Q18 and later forecasting sets).
- Score per question: correctness (key rubric) / evidence valid / tool calls / wall time / output tokens.
