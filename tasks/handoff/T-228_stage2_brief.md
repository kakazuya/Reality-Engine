# T-228 stage 2 brief: driver-tree claims from annual reports, press releases and announcements

Ticket: T-228 (Shivam 20-21 Nov 2026). Reviewer: Wolf (Opus). Stage 2a only: build and pilot, then stop and report.

Goal: the factor study (T-229, merged; `docs/research/T-229_factor_store91.md` section 9) could test only one text
factor, because claims come from call transcripts alone (52 of 91 companies, mostly since 2024). claim_rev_growth missed
its coverage gate by one month. Widen the sources so more companies and more months carry dated, quantified forward
claims: annual-report MD&A / outlook / directors' report pages, press releases, and exchange announcements (order wins,
capex or capacity approvals and commissioning, fund raises: QIP, warrants, rights; debt raises).

Evidence: (real)
- Extractor, checks and judge: `reality_engine/research/driver_claims.py` (merged 57c805e2; 60 tests;
  `docs/research/T-228_driver_claims.md`). Its items come from `transcript_statement` and `guidance` only.
- Final claims so far: `D:/RealityEngine/t228/claims_91.db` (1,159 verified / 2,901 unverified / 10 quarantined).
- Docs in the 91 stores (`D:/RealityEngine/tg_build/measure10/cNN/cNN.db`, read-only): `doc` doc_type counts:
  announcement 11,330; results 1,259; deck 572; transcript 404; annual_report 291; press_release 192. Page text is in
  `doc_page` (check its columns; some pages are OCR in `cNN_ocr.db`). known_at is on `doc`; never from the model.
- hy4 on Go is rate limited at about 250 page-sized requests per minute per key, shared with two other hy4 jobs now
  running (T-230 deck observations at 20 workers, a page reader). Run at --start 15 without --unleashed; the existing
  429 backoff and quota_event log stay on.

Steps (stage 2a):
1. Item builder (script, no model) in `driver_claims.py`: from the doc types above, cut each page into paragraphs and
   keep those with a forward cue (expect, target, plan, will, guidance, outlook, order, awarded, commission, approve,
   capex, capacity, raise, allot) and a number with a unit. Announcements: the whole text when short. Log in/out counts
   per doc type. Item ids carry (doc_key, page, paragraph index); the source table is recorded as `doc_page`.
2. Announcement-specific script parse before any model call: order-win value and execution period ("order worth Rs X
   crore ... to be executed over N months"), board-approved capex amount, QIP/warrant/rights size and price. Rows the
   script parses fully become claims with method 'script'. The rest go to the model.
3. A new claim field `source_kind` (transcript, guidance, annual_report, press_release, announcement). Same checks and
   judge. An announcement claim is "past" only if it reports a completed event without a forward amount; an order won
   today with execution ahead IS forward (revenue.order_book).
4. Tests for the item builder, the announcement parses (use 3 real announcement texts from the stores as fixtures,
   quoted with doc_key), and source_kind.
5. Pilot: the 7 pilot stores of stage 1 plus 5 stores WITHOUT transcripts (seed 31), all of these doc types; output
   `.tmp/t228/claims_s2_pilot.db`.
6. Report (under 30 lines; full detail in `.tmp/t228/report_s2a.md`): items per doc type, claims by status, node and
   source_kind, companies gained (with claims where they had none), months gained, 429 count, and 40 random verified
   claims (seed 61) with full paragraph text in the md.

Files: `reality_engine/research/driver_claims.py`, `reality_engine/tests/test_driver_claims.py`,
`docs/research/T-228_driver_claims.md`. No other file; do not edit tasks/STATE.md.

Accept: `python -m pytest -q reality_engine/tests/test_driver_claims.py` passes; typecheck clean; pilot report written.

Limits and pitfalls:
- Read-only on every store and on D:/RealityEngine/t228/claims_91.db; write only in your worktree.
- hy4-flash-free and beam-free only (free on Go). No paid model.
- Annual reports repeat boilerplate (CSR, risk lists, director bios): the cue filter must drop them; report the drop.
- An AR is published months after its fiscal year: known_at is the AR's filing date, and "FY25 revenue grew 20%" in it
  is past, not forward.
- Run pytest per file.

Stop if:
- The pilot yields more than 30% quarantined or empty model replies.
- The item builder sends more than 5,000 model items for the 12 pilot stores (report the counts and stop).

Budget: about 2-3 hours, DeepSeek max effort.
