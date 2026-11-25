# T-242: filing events - model reads, script checks (order wins + fund raises) (agy Hydrogen high, 26 Nov 2026, Eagle)

Ticket: T-242

Ruling (Shivam, 26 Nov 01:00 IST): switch order-win and fund-raise filings from script-only rules to a model + script
collaboration. The hy4 reader reads each candidate filing; the script never invents a value, it only CHECKS the
model's row against the printed pages and keeps, labels or quarantines it.

Why: eight script rounds did not reach the bar (>= 42 R and <= 3 W+J of 60). Latest fresh grades:
- order wins fresh7 (round 8, cb741c24): 35/10/14/1, C:/RealityEngine/t242/audit_orderwin_fresh7/grades.csv + pack.jsonl
- fund raises fresh7 (round 7b): 31/8/16/0, C:/RealityEngine/t242/events_grade_fundraise_fresh7/grades.csv + pack.jsonl
The W rows are reading errors a reader gets right and regex does not:
- not an order: a Ministry order appointing a director (ids 5, 29, 31, 41), a SEBI or Regional Director order (37, 40),
  a block termination or a PLI ineligibility (53, 55), L1-only status (30; 47 is its duplicate);
- wrong amount role: an annual value x tenure (11), USD stored as rupees (51), a subsidiary's own order whose scope
  became "Company of Coal India Limited" (23, 38), a UK subsidiary's EUR MSA dropped (2);
- fund raises: a divestment or asset purchase (11, 30), a withdrawn rights issue (21), a bonus issue (53), the board
  limit or offered size stored instead of the allotted / issue amount (16, 20, 35, 44, 49, 51), one tranche or the
  equity leg only (19, 22, 43), a double count (18), a threshold that is not the issue size (45), an NCLT scheme (25).

Files: reality_engine/research/filing_events.py (model path: model_prompt, parse_model_reply, model_rows, ask,
run_model, build), reality_engine/tests/ (new test_filing_events_model.py), docs/DEVELOPER_GUIDE.md (filing events
entry), docs/FIX_LOOP.md if the commands change.

Steps:
1. Model first for kinds order_win and fund_raise: every filing the existing title/keyword classifier puts in either
   kind (and every filing it vetoes only by a soft rule) goes to the model; the script parse is kept only as a
   cross-check. Other kinds (capex, capacity, amendment) stay as they are. Remove the 30% MODEL_STOP_SHARE stop for
   these two kinds only.
2. New prompt (versioned, fingerprinted like observations.TRANSCRIPT_PROMPT) asks per event, as STRICT JSON:
   - is_event (bool) and event_type: order_win | fund_raise | not_event with a short not_event_reason;
   - stage: order: received | loa | l1_only | amended | cancelled; raise: approved_board | approved_shareholders |
     filed_offer_doc | allotted | in_principle | withdrawn;
   - instrument (equity, warrants, ncd, ccd, qip, rights, preferential, ipo, bonus, other);
   - amounts as a list of {value_text (exact printed text), number, unit as printed, currency, role}, role in
     order_size | annual_value | tranche | total_issue | equity_leg | warrant_leg | board_limit | offered_size |
     threshold | other; plus tenure_years if printed;
   - awardee (the company or the named subsidiary, exactly as printed), customer, execution period.
   Pages: the filing's first 4 pages (annexures carry sizes), not just 2.
3. Script check (no model judgement): each amount's value_text must be a whitespace-normalised substring of the
   pages and its number must parse from it; the unit and currency must be printed in value_text (USD stays in
   amount_usd_mn, never rupees); the stored amount is order_size, or annual_value x printed tenure (kept unverified),
   or for a raise the total_issue, else the sum of tranche/leg rows when the page prints each one (a printed total wins
   over a sum; never add a board_limit or offered_size to an allotment). awardee must be printed; a subsidiary
   awardee keeps entity_scope subsidiary with its printed name. not_event, l1_only, cancelled, withdrawn and bonus give
   no stored event row (store them in a skip log with the reason). Mismatch between the script parse and the model on
   amount -> unverified with both values in detail.
4. Cache every reply by (doc_key, prompt fp) as run_model does; honour 429 Retry-After. Count requests; the fresh
   stores below hold a few thousand filings, so a full re-read fits the hy4 window.
5. Tests: one per W shape above (use the quoted page text from the packs), plus counter-tests: a real order with a
   rupee size, a USD order, a subsidiary order, a QIP allotment with a printed total, a two-tranche NCD allotment.
6. Measure on copies only: rebuild fresh5, fresh6 and fresh7 stores (C:/RealityEngine/t242/fresh{5,6,7}_stores.txt)
   into C:/RealityEngine/t242/model_v1/events_fresh{5,6,7}.db. Report per kind: rows stored, verified, unverified,
   skipped by reason; every graded row in audit_orderwin_fresh5/6/7 and events_grade_fundraise_fresh5/7 with its old
   grade and new state (target: every graded R row still stored with the same amount; every W/J row fixed, skipped or
   unverified); requests used.
Do NOT grade your own output and do NOT pick the grade sample; Eagle will draw a fresh 60-row sample per kind from a
new store set (fresh8) no fix was tuned on.

Accept: tests pass (run per file); >= 90% of graded R rows unchanged; >= 80% of graded W/J rows fixed, skipped or
unverified; no stored amount whose value_text is not on the page; prompt fp printed in the build meta.
Stop if: more than 10% of graded R rows change after two attempts, or hy4 returns errors on more than 5% of requests.
Budget: about 3 hours. Write scope: your worktree only; never write to D:/RealityEngine/hy4_out or live stores.
Docs: DEVELOPER_GUIDE filing-events entry (model-first flow, prompt fp, script checks, skip reasons) in the same branch.
