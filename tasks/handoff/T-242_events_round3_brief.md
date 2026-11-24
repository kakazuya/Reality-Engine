# T-242: order-filing events round 3: verify per kind, fund-raise veto, raise stage, customer forms (DeepSeek, 24 Nov 2026, Eagle)

Ticket: T-242

Goal: in `reality_engine/research/filing_events.py`, stop non-order events from being stored `verified` until each
kind passes its own strict grade, and fix the failure families the fresh grade found, by script.

Files:
- Code: reality_engine/research/filing_events.py. The two places that set `row["status"] = "verified"` are near lines
  1881 and 2367. Also `_RAISE_VETO` (~199), `_RAISE_CUE` (~166), `_raise_stage` (~1614), `_AMEND_CUE` (~272), the
  amendment builder (~1200-1260), and the order customer field (~1065).
- Tests: reality_engine/tests/test_filing_events.py (extend).
- Graded evidence: C:/RealityEngine/t242/events_grade_fresh3/grades.csv (id,grade,reason) and
  events_grade_fresh3/pack.jsonl (the row: store, doc_key, kind, amounts, customer, quote). The filing's pages are in
  C:/RealityEngine/tg_build/full394/<store>/<store>.db, table doc_page (open it read-only).
- Docs: docs/DEVELOPER_GUIDE.md, beside the "Order-filing round-2 fixes" paragraph.

Evidence: strict fresh grade (20 stores neither round was tuned on, DeepSeek a6e3b84d): 41 R / 9 P / 9 W / 1 J. By
kind:
- order_win: 25/5/0/0 (passes on its own);
- fund_raise: 13/3/5/1;
- order_amendment: 0/1/2/0;
- capacity_commissioned: 2/0/1/0;
- capex_approval: 1/0/1/0.
The W and P rows:
- fund_raise on non-issuances: #16 warrant forfeiture or lapse, #19 and #45 working-capital facility
  addendum/amendment, #21 overdraft surrender or limit reduction, #43 investment in a wholly owned subsidiary.
- order_amendment on #52 an L-1 lowest-bidder status and #58 a new letter of award stored with a negative amount.
- #6: a 2018 commissioning re-reported (the filing's news is a spray dryer added today).
- #51: a target company's project cost stored as capex (the company bought a 49% stake for Rs 20 cr).
- raise_stage: #29, #46 and #60 are board approvals of NCD or warrant issues, labelled allotment.
- customer printed but empty: #8 Jaypee Infratech, #23 and #38 U.P. Jal Nigam, #30 PGCIL, #47 MPMMCC/BHU. #11
  stored a sentence fragment instead of the MeitY society.
- J: #56, an errata re-submission of the same preferential issue.

Steps:
1. Per-kind verification gate: a constant `VERIFIED_KINDS = frozenset({"order_win"})`. At both status sites, a row
   whose kind is not in VERIFIED_KINDS gets `unverified` with detail `kind_not_gated: <kind> awaits its own 60-row
   grade`, instead of `verified` (quarantine logic unchanged). Document that each kind enters the set only after a
   fresh strict 60-row pass.
2. fund_raise veto: add to `_RAISE_VETO`: facility / sanction / renewal / enhancement of limits / addendum or
   amendment to a facility or loan agreement / surrender or reduction of a limit / forfeiture or lapse of warrants /
   investment in (or subscription to) a subsidiary, JV or associate's shares. Do not veto a company's own NCD,
   QIP, preferential or rights issue.
3. raise_stage: a board meeting outcome that approves an issue ("approved the issuance", "considered and approved",
   "subject to approval of shareholders", "enabling resolution") is `approval` even when the text also says
   "allotment" in a future sense ("allotment of up to", "to be allotted"). Only a completed allotment ("allotted",
   "has allotted", "allotment of N shares on <date>") is `allotment`. Fix with #29, #46 and #60 as tests.
4. order_amendment: an L-1 or lowest-bidder status is not an amendment (veto or reclassify as order_win when an
   amount is printed). A letter of award or new order never has a negative amount. Cases #52 and #58.
5. capacity_commissioned: veto when the commissioning date printed for the capacity is more than 12 months before
   the filing date (#6).
6. capex_approval: a stake acquisition ("acquire ... % stake", "share purchase agreement") is not capex; the target's
   project cost is never the company's capex (#51).
7. customer: parse the SEBI annexure forms "Name of the entity to which the order/contract is awarded",
   "awarded by", "from <Entity Name> (Limited|Ltd|Nigam|Corporation|Authority|...)", and "Name of the party",
   keeping only an entity name (title case or capitals, at most 12 words, no verb). Cases #8, #23, #30, #38, #47
   and #11.
8. Tests: one per step, built from the quoted rows (no per-company rules: patterns only).
9. Measure: re-run on the same 20 stores into a NEW file:
   `T228_STORE_ROOT=C:/RealityEngine/tg_build/full394 python -m reality_engine.research.filing_events --stores
   $(cat C:/RealityEngine/t242/fresh3_stores.txt) --workers 4 --out C:/RealityEngine/t242/events_round3.db --cache
   C:/RealityEngine/t242/events_cache.db --report-file C:/RealityEngine/t242/events_round3_report.md`
   Report:
   - counts by kind and status, before (events_fresh3.db) and after;
   - for the 60 graded rows, matched by doc_key + kind + amount: which W/J rows are now not verified or gone, and
     which customers got filled;
   - every order_win R row that lost verified or changed amount (target: none).
   Also run the same command on the 20 round-2 stores (C:/RealityEngine/t242/new_stores.txt, out
   events_round3_new20.db) and report the order_win verified count against events_new20 (target: no drop beyond 2%).

Pitfalls:
- The Bash heredoc mangles `\n` and `\b` in Python source: edit with the edit tool.
- `_flat` lowercases nothing; check the case handling of each regex.
- Do not touch v2/observations.py or obs_speaker.py (another branch).
- Run pytest on test_filing_events.py only.

Accept: `python -m pytest reality_engine/tests/test_filing_events.py -q` passes. The step 9 report shows: no
non-order kind verified; graded order_win R rows unchanged; at least 4 of the 6 missing customers filled; the
fund_raise W rows not stored as fund_raise.
Stop if: an order_win R row loses verified or its amount changes and two attempts don't fix it. Report and stop.
Budget: about 2 hours; write scope is your worktree only.
