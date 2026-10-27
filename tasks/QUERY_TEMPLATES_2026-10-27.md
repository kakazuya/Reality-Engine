# Query templates — questions the data must answer for any stock, industry, sector or policy (2026-10-27)

Standing rule (Shivam, 2026-10-27): the checklist's search tests must not be fixed questions about a few stocks. Every question is a **template with slots**. A dataset passes only when each template works, with small changes, for any entity at every level, and for the variations below.

## 1. Slots

| Slot | Values |
|---|---|
| `{entity}` | a **stock** (by symbol, old symbol, company name, short name, ISIN or BSE code); an **industry / basic industry**; a **sector**; a **theme** (railways, defence, EMS…); an **index** (Nifty 50 … Smallcap 250); a **market-cap bucket** (large / mid / small / micro *as of that date*); a **price band**; a **policy or macro event** (budget line, PLI, tariff, RBI rate, PIB notice) |
| `{period}` | quarter (Q2FY26), FY, date range, "as of <date>", "latest", "since <event>" |
| `{metric}` | revenue, EBITDA, PAT, margin, growth YoY/QoQ, order book, capex, capacity, debt, promoter/FII/DII %, pledge |
| `{topic}` | any content tag: guidance, order_book, capex, capacity, margin, pricing, demand, debt, working_capital, M&A, regulatory, management_change, dividend_buyback, risk, accounting_note |
| `{doc_type}` | concall, deck, AR, results_notes, announcement, PIB, budget, RBI, opinion (video / Drive report / Telegram) |
| `{condition}` | a numeric filter, e.g. PAT growth > 30%, market cap < ₹2,000 cr, promoter pledge > 15% |

## 2. Template families
Each family has to work at every entity level where it makes sense. A level marked n/a must be justified in the scorecard.

1. **Lookup.** What did `{entity}` say or report about `{topic}` in `{period}`, and in which `{doc_type}`?
2. **Number.** What was `{metric}` for `{entity}` in `{period}`?
   - Answered from verified values (XBRL / results), with the note or chunk that explains it.
3. **Change over time.** How did `{entity}`'s `{topic}` or `{metric}` change from `{period A}` to `{period B}`?
   - Includes guidance given vs what was delivered.
4. **Screen.** Which stocks in `{entity: sector / industry / theme / index / mcap bucket / price band}` meet `{condition}` as of `{period}`?
   - Membership is taken as of that date, never today's.
5. **Cross-document.** For `{entity}`, does the concall / deck / AR / results-notes account of `{topic}` agree?
   - List the contradictions.
6. **Policy → companies.** Which sectors, industries and stocks does `{policy}` affect, in which direction and how much? What did those companies later say about it?
   - Layer-3 macro links joined to layer-1 chunks.
7. **Company → policy.** Which policies or macro events since `{period}` touch `{entity}`'s sector or industry?
8. **Peers.** How does `{entity}` compare on `{metric}` / `{topic}` with its same-industry, same-size peers in `{period}`?
9. **Event window.** What was disclosed about `{entity}` in the N days before or after `{event}` (results, order win, management change, policy)?
   - Uses `known_at` order, so nothing from after the as-of time leaks in.
10. **Opinion vs truth.** What did the analysts (opinions.db) claim about `{entity}`, when (with `pit_confidence`), and did later results or announcements confirm it?
    - Opinions are never mixed into truth answers.
11. **Point in time.** Answer any family above as of `<date>`.
    - Only text with `known_at` ≤ that date, and company state as of that date.

**Added 2026-10-27 (Shivam):** families 1–11 only ask "what did `{entity}` say". The database's end goal is to answer the questions an investor actually asks, including inverse, timing, governance and reasoning questions. Families 12–20 cover those.

12. **When / timeline.** When does `{entity}`'s plant, capacity, product, order execution or demand go live or scale? How did the stated date move across calls (slippage)?
    - The answer is a date plus every dated statement of it, in `known_at` order.
13. **Inverse screen (topic → companies).** Which companies said `{topic claim}` in `{period}`? For example: demand revival in H2, a capacity going live this quarter, a price hike, a margin bottom.
    - The answer is a list, each with a quote and `known_at`.
14. **Governance and audit.** For `{entity}`:
    - the auditor's opinion type (unmodified, qualified, adverse, disclaimer, emphasis of matter) and what was said;
    - whether there is going-concern doubt;
    - whether the auditor resigned, when and why;
    - key audit matters, CARO remarks, related-party flags, CFO/KMP churn, pledge changes, SEBI or tax orders.
15. **Market move → why.** Why did `{index / sector / stock}` move on `{date / window}`? Examples: 4 Jun 2024 election results, Budget day, a tariff announcement, an RBI surprise.
    - The answer joins the price move to dated evidence published before or on that day. Later explanations are labelled as hindsight.
16. **Input-cost / commodity transmission.** How does `{commodity, FX or rate move}` hit `{industry / stock}`? Examples: copper on cables, crude on paints, rubber on tyres.
    - Needed: the commodity series, the input's share of costs (AR/notes), pass-through history (margins in past moves) and what management said.
17. **Business economics.** How does `{driver}` change `{business model}`'s profitability? Example: delivery fees on quick-commerce margins.
    - Needed: segment unit economics from filings and calls, peer disclosures, and the evidence each reasoning step rests on. Gaps are stated, never filled by guesswork.
18. **Forward policy impact.** A new `{policy}` is announced. Which companies does it affect, in which direction, through which channel, and how material is it relative to their revenue or costs?
    - Ranks by exposure; families 6–7 only list links.
19. **Second-order and supply chain.** Who supplies or buys from `{entity / industry}`, and who benefits second-hand from `{event}`?
20. **Out-of-scope and bizarre.** Questions the data cannot fully answer.
    - The answer must split what the data supports, what is reasoned inference (labelled as such), and what is NOT IN DATA.

For families 15–20 there is no single right number. They are graded by a rubric:
- **Required evidence:** the stores, documents and series a good answer must cite.
- **Required reasoning steps.**
- **Forbidden moves:** hindsight leaks, invented numbers, opinion mixed into fact.

## 3. Variations every template must survive
- **Naming:** symbol, old symbol after a rename, company name, abbreviation, ISIN, BSE code, a common misspelling.
- **Wording:** a paraphrase, a terse keyword query, a long natural question, Hinglish phrasing.
- **Period:** fiscal vs calendar labels ("Q2FY26" = "Jul–Sep 2025" = "September quarter"), "latest", "last 4 quarters".
- **Scope:** narrow (one stock) up to broad (a whole sector or index), and an empty case that should return none with the reason stated, never invented.
- **Basis:** standalone vs consolidated where results apply.
- **Corporate actions:** an entity whose ISIN or symbol changed (split, merger, demerger) still resolves to its full history.

## 4. How the checklist tests it
- **Generate instances, don't hand-pick them.** Each family is filled with random draws stratified across all levels: at least 5 stocks across the large/mid/small/micro buckets, BSE-only and NSE-only, plus 3 industries, 3 sectors, 2 themes, 2 indices and 3 policies, crossed with 2 periods.
  - Seeds are fixed so the runs are reproducible.
  - Draws are redone per release so the tests can't be overfit.
- **Ground truth** comes from verified tables wherever possible:
  - XBRL numbers;
  - BSE filing times;
  - index and sector membership as of the date;
  - the 400-question hand-made set in `tasks/optimizations/learn/quality_set_wide.jsonl` (244 symbols, 21 sectors; types qa, guidance, table_or_chart, narrative). Each of those questions is converted to its template family, then re-instantiated on new entities.
- **Every answer is checked for:**
  - correct entity resolution;
  - point-in-time correctness: nothing after the as-of date, and symbol/ISIN as at that time;
  - recall and precision of the returned chunks;
  - provenance: doc, page or second, `known_at`;
  - latency against a limit per family.
- **Pass rule.** A dataset passes only when every family that applies to it passes at every entity level and on every variation. Each failure is reported with the instance that broke it.
- **Scorecard:** family × entity level × doc type, showing pass rate and latency, with failing instances listed.

## 5. Shivam's 30 test questions as templates (required set)
These are the 30 questions Shivam set to test database quality:
- 5 in `tasks/DB_QUALITY_TEST_2026-10-24.md`;
- 10 in `tasks/optimizations/measure/QA10_BRIEF.md`;
- 15 in `tasks/optimizations/measure/EVAL25.md` (Q11–Q25).

Each one is kept as written, as a fixed regression case, **and** generalised into a template that the checklist re-draws across stocks, industries, sectors and policies (§4). The gaps these questions exposed are listed so the checklist confirms each one is closed.

| Set # | Question (short) | Family | Template (generalised) | Gap it exposed |
|---|---|---|---|---|
| DBQ1 | AEROFLEX products + close on a date | 1, 2 | What does `{stock}` make, and its close on `{date}`? | — |
| DBQ2 | 532627 latest AR: control change | 1, 9 | What did `{stock}`'s latest `{doc_type}` disclose about `{topic: ownership/control}`? | — |
| DBQ3 | 544161 business + segments | 1 | Business and segments of `{stock}` (resolved by BSE code / ISIN) | — |
| DBQ4 | P/B now vs stored | 2, 11 | `{metric}` of `{stock}` as of `{date}`, computed from price and book at matching dates | stored ratios mix price dates; no quarterly net worth |
| DBQ5 | DEEDEV Aug-2026 concall remark | 1 | What did `{speaker}` of `{stock}` say about `{topic}` on the `{date}` call? | transcripts marked processed but never chunked |
| QA1 | Ather delivery NSE+BSE on 2 dates | 2 | Delivered quantity of `{stock}` on `{dates}`, NSE + BSE + total | — |
| QA2 | BLACKBUCK promoter % Sep 2026 | 2, 11 | `{holding metric}` of `{stock}` as of `{period}` | — |
| QA3 | Ganesha facilities per a dated deck | 1 | `{fact}` per `{stock}`'s `{doc_type}` of `{date}` | — |
| QA4 | Chemcon products + acquisition per deck | 1 | Products and `{topic: M&A}` per `{stock}`'s deck of `{date}` | — |
| QA5 | Lumax shares + promoter %, latest | 2 | Share count and promoter % of `{stock}`, latest, from filings | XBRL share capital is rounded |
| QA6 | 540879 deck page 21 (licence) | 1 | What does page `{n}` of `{stock}`'s deck of `{date}` say about `{topic}`? | — |
| QA7 | INE864I01014 fuel-cell capacity, transcript | 1, 3 | What did `{stock}` (by ISIN) say about `{topic: capacity}` timelines on the `{date}` call? | — |
| QA8 | 532810 YTD high 2026 | 2 | YTD / range high or low of `{stock}` in `{period}`, value and date | — |
| QA9 | SAILIFE new facilities, latest | 1, 5 | Latest statement on `{topic}` for `{stock}` across all doc types | no cross-source "latest" |
| QA10 | COCHINSHIP MOU + margin path, transcript | 1, 3 | `{stock}` on `{partner/MOU}` and `{metric}` trajectory per the `{date}` call | — |
| Q11 | KRISHNADEF segment revenue, latest quarter | 2, 8 | Segment `{metric}` of `{stock}` for `{period}` (works for any industry) | segment contexts in XBRL |
| Q12 | Bank of Maharashtra net NPA % | 2 | `{bank/NBFC metric}` of `{stock}` for `{period}` | banking taxonomy differs from Ind AS |
| Q13 | ZENTEC 3-yr price CAGR | 2 | `{n}`-year adjusted price CAGR of `{stock / index / sector basket}` | must use adjusted prices |
| Q14 | VISHNU Note 5 of latest results + geo split | 1, 2 | Note `{n}` of `{stock}`'s results for `{period}` + `{segment/geo}` split | **results notes not stored**; this is what `results_notes.db` fixes |
| Q15 | VINCOFE public shareholding Sep 2026 | 2, 11 | `{holder class}` % of `{stock}` as of `{period}` | — |
| Q16 | Why gold stocks fell Jun–Jul 2026 | 6, 4 | Why did `{theme / sector}` move in `{period}`? Macro, PIB and company evidence | no "gold stocks" universe → **theme map** |
| Q17 | HFC securitisation leader, QoQ/YoY with NPA guard | 4, 8 | Leader in `{metric}` within `{industry}` with `{condition}` for `{period}` | no HFC universe / peer table |
| Q18 | OMCs: record Q4 then loss Q1; earliest PIT signal | 6, 9, 11 | For `{industry}`, when was `{trend}` first visible point-in-time, and from which data? | commodity series end dates |
| Q19 | MONQ50 ETF jump/fall + tracking error | 2, 9 | `{ETF}` move in `{window}`, explained by its index + FX; NAV tracking error | **ETFs not resolved**; etf_premium empty |
| Q20 | Garware: tariff hit, then negative correlation | 6, 9 | Sensitivity of `{stock}` to `{policy/event series}` over `{periods}` (rolling) | no rolling-correlation tool; no dated tariff series |
| Q21 | RBI repo hike causes; PIB or RBI only | 6, 7 | Causes of `{policy action}`, and which source published it first | provenance across sources |
| Q22 | Second-hand electronics boom CY2026: who benefits | 6, 7 | Why did `{theme/demand}` rise in `{period}`, who benefits, structural or cyclical? | thin sources; "NOT IN DATA" parts must be stated |
| Q23 | Coal gasification drafts vs the earlier scheme | 6, 3 | How does `{policy}` draft differ from `{earlier policy}`, and which industries does it hit? | coal price series ends 2025-12 |
| Q24 | PARAGMILK on El Niño; dairy peers | 6, 8 | What did `{stock}` and its `{industry}` peers say about `{macro event}`, and how are they handling it? | no dairy universe → **industry peers** |
| Q25 | Data-centre tax holiday outcome so far | 6, 7 | How has `{policy}` played out so far for `{industry}` players? | — |

**Required in the checklist:** all 30 originals as fixed regressions, and each template re-drawn on 5 stocks, 3 industries, 3 sectors and 2 policies, with the §3 variations. A gap in the right-hand column counts as closed only when its question passes.
