# T-231 brief: filing-level event table (order wins, capex approvals, fund raises)

Ticket: T-231 (Wolf 21 Nov 2026, from Shivam's plan step 2). Reviewer: Wolf (Opus). Stage A only, then stop.

Goal: the factor study needs dated, quantified corporate events, one row per filing. The generic claim extractor
(T-228) over every transcript and annual report gave 18 of 50 verified rows wrong at 91-store scale, mostly the same
fact restated across calls and reports, and parent-company facts filed under a subsidiary. Exchange announcements
are filed once, dated, and carry the event itself. Build an `event` table from announcements only.

Evidence: (real)
- 91 stores `D:/RealityEngine/tg_build/measure10/cNN/cNN.db` (read-only): table `doc` (doc_key, symbol, doc_type,
  title, filing_date, known_at, pages) with doc_type 'announcement' (11,330 docs); page text in `doc_page`
  (OCR pages may be in `cNN_ocr.db`). Title keyword counts across the 91: order/contract/LoA 322 filings in 54
  companies; QIP/preferential/warrant/rights/allotment 328 in 49; capex/expansion/capacity/commission 77 in 34.
- Existing parsers to reuse, not rewrite: `reality_engine/research/driver_claims.py` announcement script parse
  (order value + execution period, board capex, QIP/warrant/rights size and price) and the item builder; its
  `doc_announcement_script` matched only 67 filings, so the parse needs widening.
- Store parent label: the store's own company tables say which documents belong to a parent (Shivam's 18 Nov
  ruling: a subsidiary store keeps the parent's calls, labelled). NAVKARCORP's store holds JSW Infrastructure
  filings; an event filed by the parent is never the subsidiary's.
- T-228 defects to avoid: `D:/RealityEngine/t228/wolf_read_91_s2c.md`.

Steps:
1. Classify every announcement by script on title + first page text: order_win, capex_approval,
   capacity_commissioned, fund_raise (qip / preferential / warrant / rights / ncd / borrowing), other. Count per
   class; keep a 'why' (matched cue) column.
2. Parse fields by script: order value (to inr_cr; USD kept with unit), customer, execution period (months), order
   kind (new order vs order book update); capex amount, purpose, completion date; capacity added + unit + plant;
   raise size (inr_cr), price per share, shares, instrument. Every number must be printed on the page
   (value_text verbatim + page).
3. Model only where the script cannot fill the amount on a classified filing: one hy4-flash-free read of that
   filing's first 2 pages with a strict JSON schema; the same printed-value check; model rows are labelled
   method='model'. Honour Retry-After (hy4 quota window cap hit twice on 21 Nov).
4. One event per filing; an addendum/clarification filing that names an earlier filing is linked (`amends`), not a
   new event. Same order announced by both parent and subsidiary: keep the issuer's own; subsidiary store rows of a
   parent filing get entity_scope='parent'.
5. Status: verified (all printed, script or model, scope company), unverified (any field inferred), quarantined
   (value not on the page). known_at from `doc`, never the model.
6. Output DB `--out` (default `.tmp/t231/events.db`); never write a store. CLI --stores --limit --workers.
7. Tests (synthetic + 3 real announcement texts per class as fixtures, quoted with doc_key).
8. Run on all 91 stores. Report under 30 lines (detail `.tmp/t231/report_a.md`): filings per class, events by
   status and method, companies and month-ends with >=1 verified order_win / capex / fund_raise, 30 random verified
   events (seed 7) with the printed text around each value.

Files: new `reality_engine/research/filing_events.py`, `reality_engine/tests/test_filing_events.py`,
`docs/research/T-231_filing_events.md`. No other file; do not edit tasks/STATE.md.

Accept: `python -m pytest -q reality_engine/tests/test_filing_events.py` passes; typecheck clean; report written.

Limits and pitfalls:
- Read-only on stores; writes only in your worktree. hy4-flash-free only; no paid model.
- A board meeting intimation ("to consider fund raising") is not a raise; an outcome with the approved size is.
- Results/outcome filings that bundle many items: classify by the item that carries an amount; one filing may yield
  at most one event per class.
- Run pytest per file.

Stop if: more than 30% of classified filings need the model (report counts and examples first); more than 10% of
events quarantined.

Budget: about 2-3 hours, DeepSeek max effort.
