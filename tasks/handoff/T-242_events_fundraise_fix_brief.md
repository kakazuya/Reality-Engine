# T-242: fund_raise round 5 - this step's own amount, raise stage map, duplicates, vetoes (DeepSeek, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: in `reality_engine/research/filing_events.py`, fix the fund_raise failures a strict per-kind grade found, so a
fresh grade can pass and fund_raise can join `VERIFIED_KINDS`. Do NOT add fund_raise to VERIFIED_KINDS yourself.

Files:
- Code: reality_engine/research/filing_events.py (fund_raise builder and amount: search `fund_raise`,
  `_raise_stage`, `_RAISE_VETO`, `_RAISE_AGREEMENT_VETO`, `_ALLOTMENT_DONE`, `_APPROVAL_ONLY`, `_fold_same_order` and
  the raise fold near `_RAISE_STAGE_RANK`). Use code-tools `outline` first.
- Tests: reality_engine/tests/test_filing_events.py (extend).
- Evidence: C:/RealityEngine/t242/events_grade_fundraise/grades.csv and pack.jsonl (rows with store and doc_key).
  The pages are in C:/RealityEngine/tg_build/full394/<store>/<store>.db, table doc_page (open it read-only).
- Docs: docs/research/T-231_filing_events.md and docs/DEVELOPER_GUIDE.md (beside the round-4 entries).

Evidence: strict grade of 60 fund_raise rows from 45 untuned stores (DeepSeek a8f57918): 30 R / 16 P / 10 W / 4 J.
- W, amount summed from unrelated printed figures (7):
  - #12/#20/#57: the 25% warrant money or the 75% balance added to the step's own value (#57: this step printed Rs
    4,00,00,000 = 16,00,000 shares at Rs 25; the row has 7.0 cr);
  - #13: an earlier step's aggregate reused (500 cr vs this conversion's 15.00 cr);
  - #32: a past year's QIP added;
  - #54: pre-issue paid-up capital added (1,060.283 vs the printed 1,000 cr);
  - #10: the wrong aggregate (printed Rs 1,85,49,99,790 = 185.50 cr; the row has 1,140.22).
- W, not an issuance (3): #19 a subsidiary's own rights allotment (the listed company issued nothing); #21 an NSE
  advisory on a warrant lock-in; #43 'fund raising through debt' with no security named.
- J, duplicates (4): #9 an errata re-filing the same board approval; #29 and #48 press releases repeating an
  allotment already filed; #60 a second letter for the same QIP allotment.
- P, raise_stage (13): completed allotments labelled approval or intimation (#1, #5, #23, #25, #40, #46, #49);
  postal-ballot notices labelled approval (#31, #51); a board that approved only a draft notice labelled approval
  (#53); board approvals labelled proposed (#6, #33); an exchange in-principle approval labelled listing (#7).

Steps:
1. Amount: the event amount is the printed value of THIS step only. Prefer the computed shares x price of this
   allotment when both are printed; never add the upfront 25% and the balance 75% of warrants, an earlier step's
   value, a past year's figure or pre-issue capital. When one total is printed for this step ("aggregating to Rs
   X"), use it. Write it as a pure function `raise_step_amount(text) -> (amount_cr, how)` and test it on #10, #12,
   #13, #20, #54 and #57.
2. Vetoes: a subsidiary's allotment (the subject is the subsidiary, or "our subsidiary has allotted"); an exchange
   advisory or lock-in letter; "fund raising" with no security named (no equity, QIP, preferential, rights,
   warrant, NCD, bond, debenture or CP).
3. Stage map, applied in this order:
   - a completed allotment ("allotted", "has allotted", "allotment of N shares/warrants on <date>") = allotment;
   - a postal-ballot or EGM notice = proposed;
   - a board that approved only a notice or draft = proposed;
   - a board or shareholder approval of an issue = approval;
   - an exchange in-principle approval = approval (not listing);
   - listing or trading approval = listing.
   Drop the 'intimation' value; map it by the rules above.
4. Duplicates: an errata/corrigendum or a press release repeating a step already filed (same company, the same
   stage, an amount within 0.5% or the same share count, within 10 days) folds into the earlier row
   (`duplicate_of` or the existing fold).
5. Tests: one per step from the quoted rows; patterns only, no company names in code.
6. Measure: re-run on fresh4 and fresh3 into NEW files in your worktree .tmp (copy C:/RealityEngine/t242/events_cache.db
   to .tmp first):
   `T228_STORE_ROOT=C:/RealityEngine/tg_build/full394 python -m reality_engine.research.filing_events --stores
   <stores> --workers 4 --out .tmp/events_r5_fresh4.db --cache .tmp/events_cache.db --report-file
   .tmp/events_r5_fresh4_report.md` (stores from C:/RealityEngine/t242/fresh4_stores.txt, then fresh3_stores.txt).
   Report, for the 60 graded rows (match by doc_key + kind): each W/J/P row's new state, and every graded R row
   that changed (target: none). Also report order_win verified counts against events_round4_fresh4.db (132) and
   events_round4_fresh3.db (193); they must not move.

Pitfalls:
- The Bash heredoc mangles `\n` and `\b` in Python source: use the edit tool.
- Do not change VERIFIED_KINDS or order_win logic.
- Run pytest on test_filing_events.py only.

Accept: `python -m pytest reality_engine/tests/test_filing_events.py -q` passes. The report shows the 10 W and 4 J
rows fixed or gone, at least 10 of the 13 stage P right, no graded R row broken, and order_win counts unchanged.
Stop if: an order_win count moves or a graded R row breaks and two attempts don't fix it. Report and stop.
Budget: about 2 hours; write scope is your worktree only.
