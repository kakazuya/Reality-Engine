# T-242 brief: fund_raise model-first r3 - the step's own amount, every tranche, pages past 4, same-day repeats (agy Hydrogen high, 26 Nov, Wolf)

Ticket: T-242
permission: write (your worktree only)
Base: main (order_win now gated; fund_raise stays unverified until it passes a fresh grade).

Goal: fund_raise failed the fresh9 strict grade 49 R / 5 P / 4 W / 2 J (bar: >=42 R, <=3 W+J). Fix the four causes
by STRUCTURAL rules in reality_engine/research/filing_events.py (model-first r2 path from 4a3c41b3 + the script
helpers `raise_step_amount`, `_raise_step_sizes`, `_RAISE_COMPONENT`, `_fold_same_raise`); never per company.

Evidence: grades in the Hydrogen job result (copied here), pack C:/RealityEngine/t242/events_grade_fundraise_fresh9/
pack.jsonl (id = line `id`; doc_key + store per row); page text C:/RealityEngine/tg_build/full394/<store>/<store>.db
table doc_page (read-only, `file:...?mode=ro`, uri=True). Stored rows: C:/RealityEngine/t242/fresh9/events_mf_fresh9.db.
W1 double-counted leg: #49 stored 509.0275 cr = swap 499.0525 + cash 4.9875 + cash 4.9875 again (right 504.04, shares
   70,742,458 not 71,442,458); #55 stored 74.7469 = equity 50.9003 + warrants 11.9234 twice (right 62.8236).
W2 one tranche of two: #37 stored 500 cr; filing allots Series 1 (50,000 NCDs, 500 cr) + Series 2 (50,000 NCDs,
   500 cr) = 1,000 cr.
W3 warrant conversion priced at 100%: #43 stored 1,303.9207 = 1,76,20,550 x Rs 740; the step received the 65%
   balance Rs 481 x 1,76,20,550 = 847.55 cr.
P  amount printed after page 4: #5 (p5 'raise funds upto Rs. 100,00,00,000'), #9 (p5 'not exceeding Rs.600 Crores'),
   #25 (p5 'up to ... ₹15,000 million'), #52 (p8 'not exceeding 100 Crore'); #40 pages 1-2 empty text, total on p7-8.
J  same-day repeat letters: #17 (letter /40 points to /39 = #46), #48 (voting results for the postal ballot of #12).

## Steps
1. Reproduce: for each id above, read the stored row and the page text; confirm the cause in code (file:line).
2. W1: a figure (amount or share count) appearing twice in the legs list - same value from the same printed span or
   a repeated table row - is counted once; sum legs only over distinct printed spans.
3. W2: when the filing prints several series/tranches allotted in THIS step and a total, store the total; with no
   printed total, store the sum of distinct series (each series' own printed amount once).
4. W3: a warrant conversion/balance step stores the amount received in this step (shares x balance per warrant, or
   the printed received amount), never shares x full warrant price. Keep r5's 25%/75% component rule.
5. P: read the resolution/annexure pages beyond page 4 (up to the doc's last text page, cap 12) when pages 1-4 print
   no amount for a raise; when the first pages have no text, use the later pages.
6. J: two filings of the same company on the same day (or a voting-results/scrutiniser letter for a ballot already
   stored) that describe one step fold into one event; the repeat names the kept row in `amend`.
7. Tests in reality_engine/tests/test_filing_events.py (and test_filing_events_model.py for model-path code): one per
   case above as synthetic text, plus counter-tests that two genuinely distinct same-day raises stay two.
8. Docs: one DEVELOPER_GUIDE.md bullet (r3 fund_raise) naming each rule and test.

Files: reality_engine/research/filing_events.py, reality_engine/tests/test_filing_events.py,
reality_engine/tests/test_filing_events_model.py, docs/DEVELOPER_GUIDE.md. Nothing else.

Accept (yours): python -m pytest -q reality_engine/tests/test_filing_events.py ; then test_filing_events_model.py ;
test_load_observations_gate.py - each separately, all pass. Do NOT change VERIFIED_KINDS or any order_win logic.
Accept (Wolf after you): re-run on fresh9 from the cache (0 new model calls) - 49/49 graded R rows unchanged in
amount/stage/status, the 4 W and 5 P fixed or empty, the 2 J folded; then a fresh grade on fresh10 by a non-author.

Stop if: a rule changes any graded-R fund_raise row or any order_win row and 2 tries do not fix it: report and stop.
Pitfalls: pytest, not unittest; never write under C:/RealityEngine or D:/RealityEngine; no model calls; never kill
processes by name; regexes edited with the file editor; empty beats wrong.
Budget: ~75 minutes, ~150 tool calls.
