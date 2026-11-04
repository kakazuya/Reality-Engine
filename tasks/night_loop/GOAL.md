# Goal, evals and boundaries for the loop (v2, 4 Nov 2026, after Shivam's correction; awaiting approval)

Authoritative copy. Every loop session reads this first and obeys it over anything else except `tasks/RULINGS.md`.
Only Shivam changes it; a loop that edits it is rejected.

## 1. The goal
For every company we pick, an investor's reasonable questions about it can be answered by an LLM through the
`reality-data` MCP from a database built by deterministic scripts out of the documents we hold: concall transcripts,
order wins and other announcements, annual reports, investor presentations, press releases, results filings (XBRL),
price-volume-delivery data, shareholding patterns, pledge reports, credit ratings. Target: at least 95% of the
questions answered correctly, NOT IN DATA only where the documents truly do not hold it.

Two phases, in order. Phase 2 does not start until Shivam approves Phase 1's question set.

## 2. Phase 1: the question set (Claude's work; no worker does bank reasoning)
Make, per company, the questions a fundamental or technical investor would ask before investing (holding a year or
more), and only those that make sense for that company's business. Inputs, in order (Shivam, 4 Nov):
1. Research: what investors check before investing in each sector, which metrics each sector uses to judge
   profitability and going concern, and what technical investors look at (trend, relative strength, volume and
   delivery, event reactions, levels, bulk/block deals).
2. The 1,073-case master bank (`tasks/master_bank/MASTER_BANK.jsonl`) and the frozen 1,901 bank as idea sources.
   Drop document-specific probes ("what does page N of the deck dated X say"): they tested the store, not an
   investor's need. Sorted list: `tasks/night_loop/questions/BANK_IDEAS_2026-11-04.xlsx` (keyword sort, reviewable).
3. The library built from 1 and 2: `questions/LIBRARY_universal_technical.jsonl` (every company),
   `questions/LIBRARY_sectors.jsonl` (per sector family) and `questions/sector_vocab.json` (metrics per sector).
4. Company sets instantiate the library for each company with its own segments, products and documents.
- Layers: a sector question set per sector family (lender, EPC/infrastructure, metals, ...), then each company's
  rewrite of it with its own segments, products and documents.
- Orders: first order (a stated fact), second order (computed, trend, comparison, consistency across documents),
  third order (ripple: what a policy, commodity, rate or peer event means for this company).
- Lenses: results and margins, segments, orders and order book, guidance and delivery against it, balance sheet and
  cash, capital allocation, ownership (promoter, FII/DII, pledge), credit ratings, governance and management,
  price-volume-delivery and technical behaviour around events, valuation.
- Variations: each core question in several forms (name / ticker / BSE code, terse / full, dated / relative
  "last quarter", different period kinds).
- Every question carries: id, company, text, variations, order, lens, sector-fit tag, the master-bank ids it came
  from (or "new" with a reason), `as_of`, answer kind, and the **data items it needs** (document type and
  table/metric/period, or "text search in <doc type>"). Phase 2 is measured against those data items.

| # | Phase 1 check | Rule |
|---|---|---|
| Q1 | Sector fit: every metric a question names is in that sector's vocabulary (no hospital beds for a cable maker, no NIM for a smelter) | 0 violations (script) |
| Q2 | Coverage: every lens and every held document type is needed by questions for each company; orders spread | each lens >= 10 per company; 1st >= 40%, 2nd >= 25%, 3rd >= 10% |
| Q3 | Variation and duplicates: core questions have >= 3 forms; near-duplicates (token overlap > 0.8) flagged | 0 unflagged duplicates |
| Q4 | Traceability: diff against the frozen banks; every dropped bank idea for a company has a reason | full diff written |
| Q5 | Reasonableness, hand-read: 50 random questions per company read by the wrapper | >= 48 reasonable |
| Q6 | Shivam approves the set | before Phase 2. Approved 5 Nov 2026: "solid for practical life queries" |
After approval the set is frozen and split by a fixed hash: dev 70% (loops see it), hidden 30% (wrapper only).

## 3. Phase 2: extraction until the database answers (dsh workers build; Opus manages)
Scripts (CPU / GPU / NPU, no model call while building) extract from the raw documents into the pilot database so
the MCP tools return what each question needs, reading as little as possible.

| # | Phase 2 measure | Kind | Rule |
|---|---|---|---|
| A1 | Data answerability, every question: the MCP tools return each needed data item with `known_at` <= as_of | score | dev up; hidden not down; no company down |
| A2 | Answer test: a fixed random sample (60 per company) answered by a model through the MCP only, hand-read graded by the wrapper | reported score | not down; the target is 95% right |
| A3 | Provenance: a new row's value is in its quote and the quote is on the cited page | guard | >= 98% |
| A4 | XBRL agreement of deck / press-release / transcript figures; point-in-time violations; duplicate documents; junk rows | guard | not up |
| A5 | No model or network in the build (sockets blocked); no company literals in extractor code. Exception (Shivam, 5 Nov 2026): a separate step after the build may send KPI rows the scripts cannot settle to free `beam-free` on the two OpenCode Go keys; no other model, no spend | guard | pass |
| A6 | Tests: fast suite each loop, full suite and `checkpages run` (>= 145 found) at merge | guard | green |
| A7 | Cost: pages read, OCR pages, build seconds per company | score | not up > 20% without an A1 gain |
A1 is the guide; A2 is what gets reported to Shivam (hand-read only). A loop is accepted only if A1-dev rises,
A1-hidden and every company hold, and every guard passes; every second accepted loop runs A2, which must not fall.
Overfit alarm: dev up while hidden flat over two accepted loops stops the run.

## 4. Roles
- Wrapper (visible Eagle session): launches one loop at a time, re-runs every check itself, reads every diff,
  merges, backs up and promotes the database, keeps the scoreboard, grades A2 by hand, stops the run.
- Loop session (headless `claude -p`, Opus 5.5, effort medium, same config and MCPs, no subagents): one work item,
  then a report in `tasks/night_loop/loops/loop_NN.md`, then exit. Phase 1: it writes the questions itself.
  Phase 2: it gathers evidence, briefs and steers at most 2 dsh workers, runs the checks on their branch.

## 5. Not the goal (rejected)
Rows added that no question needs; commentary extraction by rules (commentary stays searchable text); company-
specific code; new downloads, OCR runs, embeddings, paid calls; editing questions after the freeze, gold, graders,
checks, tests' assertions, rulings, guidelines or this file; writing the live database, merging or pushing from a
loop; work outside the queue.

## 6. Boundaries
Companies and window: `PILOT10.md` (10 companies, one per sector; last 4 quarters only). Never rebuild the whole
database to test a fix: rebuild only the parts and companies it touches (Shivam, 4 Nov). At most 2 dsh workers at
once, tied to the running loop; one headless loop at a time, context budget about 400k (killed at 480k), 5 loops
before Shivam reviews (loop 1 Phase 1 + raw data, loops 2-5 Phase 2); standing loop rules `LOOP_BRIEF.md`,
learnings passed on in `HANDOFF.md`; no dsh starts in peak hours (weekdays 06:30-09:30, 11:30-15:30 IST); pause starts under
2.5 GB free RAM; tests one file per process. The wrapper greps loop and worker transcripts for reads of the hidden
split; a hit rejects the loop. Docs updated with every merge.

## 7. Queue
1. Phase 1 for KEC, BAJFINANCE, HINDALCO: sector sets for EPC/infrastructure, lender, metals, then company sets,
   checks Q1-Q5; the wrapper presents it to Shivam.
2. In parallel (dsh, T-055): the check scripts for Q1-Q3 and A1, A3-A7, built against the question format above.
3. After approval: baseline A1 and A2, then Phase 2 loops, each taking the largest group of unanswerable dev
   questions by needed data item (structured feeds first, then XBRL segments, period labels, XBRL calibration,
   duplicate documents, core-document triage).

## 8. Stop when
3 loops in a row rejected; the overfit alarm; a guard fails on `main`; the Claude usage limit (stop, do not wait);
4 loops done; or Shivam says stop. Then the wrapper writes `D:\RealityEngine\reports\<date>_loop_run.html`.
