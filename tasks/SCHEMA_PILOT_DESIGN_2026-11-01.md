# Pilot schema design, first pass, 1 Nov 2026 (Wolf)

Shivam accepted the rewritten bank on 1 Nov as good enough to design from. This pass measures what the bank asks against what the v4 stores hold. It replaces the coverage numbers in `SCHEMA_FINAL_2026-10-29.md`, which were on the old bank; that file's table list stays as reference.

**Method and limit:** the v4 decomposer was run over the 1,899 questions, then each measure was counted in `fact_v4_pilot.db` and `v4.db`. The decomposer is imperfect (1,652 mapped, 142 not in data, 105 unmapped; 73 had no parts), so question counts are a guide to size, not a final map. A question-by-question map is the next step.

## Scope (Shivam, 1 Nov): this overrides the wording below
Every question becomes a query, and the system computes what filings do not state. "No rows" below means **not extracted yet**, never missing. Text held vs rows held, in names: order book 25 vs 5, receivables 49 vs 3, capacity utilisation 39 vs 4, operating cash flow 48 vs 0, CWIP 49 vs 0, sales volume 46 vs 0, gross NPA 8 vs 0, NIM 6 vs 0, tax reconciliation 42 vs 0. This count covers `document_chunks` only, not the 21,212 raw pilot PDFs.

**Three layers:** (1) read each document once and store every number with quote, page, basis, period and `known_at`; (2) compute from those with named formulas, showing the inputs; for example tax benefit = tax at the normal rate minus tax paid, from the tax reconciliation note; (3) the query layer only looks up layers 1 and 2. F&O joins after the main database is built.

## Decisions

1. **Keep the v4 shape:** one long `fact` table, plus `claim` and `membership`, in SQLite. Nothing measured points at the table shape. The gaps are unfilled measures, and an executor that returns a nearby measure (66 of 127 read-graded rows).
2. **Widen `claim` first.** About 907 questions need something a company said. For the 60 pilot names it holds 28,823 claims, from earnings calls only, for 44 names, and 46% have the topic `other`. It needs annual reports, presentations, results notes and filings, for every pilot name, with topics taken from what the bank asks.
3. **Every document-derived number carries its verbatim quote, page and `known_at`**, and a code check that the quote is in the source. Values and interpretation stay separate.
4. **Stock F&O, ADR and US overnight data, index weights, retail losses and similar stay out**, by Shivam's rulings. `macro.oi` (1.9 GB side file) is left out of the pilot. It is not deleted, and the raw F&O files stay on D.
5. **`edge` stays empty until the question map shows which kept questions need it.** Shivam parked most of the deep chain questions for later gates.
6. **The schema alone will not pass the gate.** The nearby-measure fix (queue item 3) still has to land, or filled measures will keep answering the wrong question.

## Measured gaps

| Measure | Questions asking (approx.) | Held for the pilot | Action |
|---|---:|---|---|
| What a company said (`claim`) | 907 | 28,823 rows, calls only, 44 of 60 names | Widen sources and topics |
| Capex | 75 | 39 of 60 names | Extract from documents |
| Segment values | 80 | 32 of 60 names | Extract from documents |
| Order book | 69 | 5 names, 6 rows | Extract from documents |
| Corporate actions (per share) | 36 | No rows | Build point-in-time from held actions |
| NPA | 27 | No rows | Extract, lenders only |
| Receivables | 23 | 3 names | Balance-sheet lines from annual reports |
| Order intake | 18 | 3 names | Extract from documents |
| Unit volume | 17 | No rows | Extract from documents |
| Loan book | 16 | No rows | Extract, lenders only |
| Investments | 14 | No rows | Balance-sheet lines |
| Capacity utilisation | 13 | 4 names | Extract from documents |
| Cash flow from operations | 12 | No rows | Results and annual reports |
| NIM | 10 | No rows | Extract, lenders only |
| Credit cost | 8 | No rows | Extract, lenders only |
| Free float | 8 | No rows | Build from shareholding |
| CWIP | 6 | No rows | Balance-sheet lines |
| FII sector flows | 1 restored | Held raw in `mkt_report_cells` (186 files, to 30 Sep 2026), not a measure | Add a measure; pull later fortnights |

`atom_status` is out of date: it says `claim.claim` is not built, and it has no row for the measures above that hold nothing.

## Pilot companies

Going from 60 to 63, per Shivam's comments: **Apollo Hospitals and KIMS** (a large and a smaller chain; Apollo also runs pharmacies), and **Ola Electric** with a registrations feed. Their raw documents come first; the bank then gets questions for them, written by Claude.

Sources for Ola: the Vahan dashboard page is reachable, but no fetcher has been proven on it. `financiallyfree.in/tools/auto-tool` redirects to a Google login, so it cannot run unattended without Shivam's account. Vahan reports registrations, not deliveries, so the question will ask for registrations.

## Next, in order

**Shivam, 1 Nov: prototype first.** Extraction runs on BAJFINANCE, HINDALCO and KEC with measured tokens and accuracy (report: `tasks/pilot60/PROTOTYPE3_REPORT_2026-11-01.md`; the dsh_tasks brief is not in the repo). No DeepSeek run on all 60 until that report says it is worth it.

1. Fetch raw documents for the three new names, and a Vahan series. Fetch the NSDL fortnight after 30 Sep 2026.
2. Claude writes the question-by-question map: each question to its measures, source and table. Output in Excel. Done for the 3 prototype companies on 2 Nov: `tasks/pilot60/question_map/rules.py` holds Claude's mapping, `tasks/pilot60/question_map/build_map.py` is the only thing that sets a status, and its result says what is held, not whether an answer is right.
3. Final schema from that map, then a pilot on the 63 names. The checklist script and the 95% rule in `AGENTS.md` still decide whether any full run starts.
