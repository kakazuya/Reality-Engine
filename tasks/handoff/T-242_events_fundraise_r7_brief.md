# T-242: fund_raise round 7 - structural rules after the fresh-store fail (DeepSeek, 25 Nov 2026, Eagle)

Ticket: T-242

Goal: round 5 fixed all 30 failing rows of its graded 60, but a strict grade on 40 UNTUNED stores (fresh5) gives
31 R / 7 P / 22 W / 0 J. Round 5 fitted rows, not the kind. Write STRUCTURAL rules that hold on unseen filings.
Measure them on fresh5 (the evidence) and ALSO on a held-out set that this brief does not show you. Do not add
fund_raise to VERIFIED_KINDS.

Files: reality_engine/research/filing_events.py (fund_raise: `raise_step_amount`, `_raise_step_sizes`, `_raise_stage`,
the vetoes), tests in reality_engine/tests/test_filing_events.py, docs docs/research/T-231_filing_events.md and
docs/DEVELOPER_GUIDE.md.

Evidence: C:/RealityEngine/t242/events_grade_fundraise_fresh5/pack.jsonl and grades.csv (id,grade,reason). Pages:
C:/RealityEngine/tg_build/full394/<store>/<store>.db, doc_page (open read-only). The run DB is
C:/RealityEngine/t242/fresh5/events_r6_fresh5.db.
- W, amount (15): #17/#19/#21/#31/#41 multiply a SUM of earlier and current share/warrant counts by the price; the
  step is only the shares allotted in this filing ("allotted 75,000 equity shares" -> 75,000 x price). #2 counts
  a green shoe twice. #7 takes only the premium amounts. #49/#60 add cash consideration to a QIP. #23 uses the
  original CCD issue instead of this conversion. #32 uses face value instead of the printed consideration. #6
  misses "aggregating to Rs 808,00,00,000". #45 uses an NCD resolution for a QIP row. #5 and #16 overlap
  components.
- W, not the company's own issue (7): #10 and #24 subscribe to a subsidiary's or associate's rights/OCRPS issue;
  #14 is an acquisition of another company's shares; #29 is the sale of a stake paid in another company's CCPS;
  #33 is a loan to a subsidiary; #38 and #50 invest in a subsidiary's CCPS.
- P, stage (6): #11, #47 and #59 are a board recommendation or AGM notice (= proposed); #22 and #51 are a board
  approval subject to EGM (= approval, not allotment); #55 is a post-completion press release (= allotment).

Steps:
1. Issuer rule (structural). A fund_raise needs the LISTED company as the ISSUER: the security is "of the Company"
   or "equity shares of the Company", and the sentence's subject allots or issues it. Subscription to, investment
   in, or acquisition of another entity's securities ("subscribe to", "invest in", "acquire ... shares of <other>",
   "of <subsidiary/associate name>"), loans, and sale of a stake are never fund_raise: veto them as round 5 did.
2. Step amount (structural). The amount is, in this order: (a) the printed total of this step ("aggregating to Rs
   X", "for an amount of Rs X", "issue size Rs X"); (b) the shares or warrants ALLOTTED IN THIS FILING times the
   issue price. Never a cumulative count, a sum of counts, face value times count, or cash/acquisition
   consideration. A green shoe is counted once: when the base plus the shoe is printed as "up to X including
   green shoe", X is the amount.
3. Stage (structural). The stage follows from what THIS filing records:
   - an allotment done -> allotment;
   - a board approval that needs members' approval -> approval;
   - a notice, recommendation or postal ballot -> proposed;
   - an in-principle or listing approval -> approval/listing;
   - a press release after completion -> allotment.
4. Tests from the quoted shapes (patterns only, no company names).
5. Measure on fresh5: re-run into a NEW file in your worktree .tmp (copy C:/RealityEngine/t242/fresh5/events_cache.db
   first; stores from C:/RealityEngine/t242/fresh5_stores.txt; `T228_STORE_ROOT=C:/RealityEngine/tg_build/full394`).
   Report the new state of each of the 29 W/P rows, every R row that changed (target none), and order_win
   verified counts (fresh5 215, and on fresh4/fresh3 132/179). They must not move.
6. Docs: a round-7 section in T-231_filing_events.md and DEVELOPER_GUIDE.md.

Pitfalls: the Bash heredoc mangles `\b` and `\n`, so use the edit tool. Do not change order_win logic. Run pytest on
test_filing_events.py only.

Accept: test_filing_events.py passes; at least 18 of the 22 W are fixed or gone; 0 R broken; order_win counts are
unchanged.
Stop if: a rule changes more than 25% of fund_raise rows on fresh4/fresh3 (report the count) or breaks an R row
after two attempts.
Budget: about 2 hours; write scope is your worktree only.
