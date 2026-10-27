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
