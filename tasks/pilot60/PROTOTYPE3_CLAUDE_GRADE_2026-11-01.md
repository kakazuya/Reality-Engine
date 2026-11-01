# Prototype on 3 companies: Claude's grade, 1 Nov 2026

Worker report: `tasks/pilot60/PROTOTYPE3_REPORT_2026-11-01.md`, in worktree `IDM-worktrees/20261031T215040Z-4ef5184a`, not merged. Graded by reading a random 25 of the 45 "answered" rows, 15 of the 99 "evidence" rows, and all 9 "not found" rows, from `PROTOTYPE3_ANSWERS_2026-11-01.jsonl`.

## Verdict: cost is fine, quality is not. Do not scale yet.

| Measure | Result |
|---|---|
| Reader cost for 3 companies | $0.72 to build, about $1.16 with the tests, 930,414 tokens in, 1,572,093 out |
| Forecast, 60 companies, build only | $13 to $26, from the worker's document counts. Before any recall fix, so expect it to rise |
| Answers truly right, of 25 "answered" sampled | **0**; about 3 partly right (`MB0083#L`, `MB0053#L`, `MB0930#MS`) |
| Answers truly right, of 15 "evidence" sampled | **0** |
| Missed by the store, in the recall check | 91 of 117 numbers (78%), on 25 of 36 planned documents |

## What is wrong, with real examples

1. **The 30 of 30 accuracy scores are too generous.** They only check that the quote and number are on the page, not that the row means what it says.
   - `lender_metrics`: `nim_pct = 90` for Bajaj Finance, from "30% digital contribution... 100MM loans". Code-only arm, and false.
   - `company_capacity_utilisation`: Hindalco "125 megawatts" stored with unit `inr_cr`.
   - `results_xbrl`: Bajaj EPS of 10 stored as `0.0 inr_cr`.
   - `order_intake`: KEC 37,697 crore looks like the order book, not intake.
2. **The answer file is a keyword lookup, not a query engine.** The same two KEC rows answer at least 8 different questions, such as "EPC vs HAM" and "orders awaiting approval". Hindalco's capex rows answer payout and net debt questions.
3. **Price and filing questions never reach the stores that hold them.** "What was the YTD high" and "close on 16 October 2026" came back not found, though prices are held. "Delivered quantity on 21 September" returned a passage on unclaimed shares.
4. **Text is thin or missing for important documents.** KEC: 10 calls with 10 pages and 1,598 characters. Bajaj decks: 956 pages and 70,904 characters, about 74 per page. So readers see little of these documents.
5. **The reader is unstable.** Same 30 passages at low and max effort: 25 and 19 rows, only 1 in common by the worker's key. Max cost 2.1 times as much.
6. **Report inconsistencies to check:** "108,078 chunks" against a table summing to about 3,000; "whole universe" forecast barely above 60 companies, because it counts held documents only; 2,916 of 3,984 pages sent, against 29.87% of text.

## Presentations: Haiku, DeepSeek, CPU OCR (only 9 pages)
Haiku gave 464 facts, DeepSeek 129. CPU OCR text contained 458 of Haiku's values (98.7%). Of 8 hand-checked disagreements: Haiku wrong 2, Haiku right and OCR missed 4, DeepSeek right and Haiku missed 1, all wrong 1. Haiku reads far more; some of its values are digits lifted from labels ("Q4" as 4.0). Too small a sample to settle it.

## What I would change before any wider run
1. Meaning checks at write time: unit fits the measure, range checks (NIM of 90% fails), and label checks. Typed contracts do this.
2. Fix text first: KEC calls and deck text. Use the deck store or OCR where chunks are thin.
3. Recall: read number-dense pages whole, since the passage picker misses 78%.
4. Route questions by measure to the right store, through the query engine and its fix for returning nearby measures, not keyword rules.
5. Rerun on the same 3 companies, and grade the same questions.
