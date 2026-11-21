# T-228 stage 2c — progress notes

- 21 Nov, worktree 20261121T052428Z-17494c2e: implemented stage 2c (period_norm, units, order_kind, part
  scope, collapsed-range repair, event repair, --repair/--repair-report) — 101 tests passed, typechecked.
- First repair: verified 1,954 / unverified 5,724 / duplicate 2,256; Wolf review asked the event row to be the
  earliest VERIFIED member (no verified fact behind an unverified event).
- Re-done: event row = earliest verified member; earlier unverified copies keep their status with dup_of.
  Final DB `.tmp/t228/claims_91_s2c.db`: verified 2,036 / unverified 5,853 / duplicate 2,045 / quarantined
  168; 410 of 2,449 pre-repair verified rows folded (16.7%); 211 earlier unverified copies linked; 13 rows
  re-judged (10 passed). Verified capex 200; verified inflow orders 251. Tests 102, typecheck clean.
- Docs: `docs/research/T-228_driver_claims.md` §5, §6, §8, §10, §12 end and §13 reflect the verified-event rule
  and the final counts.

# T-231 — progress notes

- 21 Nov, worktree 20261121T075651Z-f3c13226: `reality_engine/research/filing_events.py` built and run over the 91
  stores (11,330 announcements). Stage A: 467 classified filings, 440 events (order_win 289 filings, fund_raise
  149, capex 21, capacity 8), 246 verified / 194 unverified / 0 quarantined, 81 model-needed (17.3%), 13 model rows,
  3 amend links. Tests `test_filing_events.py` 16 passed; typecheck 0 errors. Docs:
  `docs/research/T-231_filing_events.md`. `tasks/STATE.md` not touched (brief forbids it). Brief drift: the store's
  parent label is only on linked transcripts, not announcements; c08's JSW material is a transcript/deck, so no
  parent-scope event rows exist.
- 21 Nov stage B (Wolf read A): B1-B9 fixed (dedupe cover+annexure value, same-order twin fold + amend link,
  order_amendment class with increment/extension, annual vs total, consortium share, court/tax/ESOP/open-offer
  vetoes, bundled filing per class, new-order vs order-book, GST veto recall fix + loose order letter). Final run
  670 classified / 603 events, 340 verified / 263 unverified / 0 quarantined, 125 model-needed (18.7%), 19 model
  rows, 28 amend links. Tests 32 passed; typecheck 0 errors. Reports `.tmp/t231/report_b.md`,
  `.tmp/t231/recall_b.md`. Docs `docs/research/T-231_filing_events.md` updated.
- 21 Nov stage C (Wolf read B): C1 raise_stage/raise_id/raise_primary (157 raise ids, 157 primaries), C2 120-day
  recap fold, C3 buyer/exploring/completion/borrowing vetoes, C4 restatement drop + event_date, C5 customer/shares
  hygiene + multi-order seq rows. Final run 691 classified / 604 events, 439 verified / 165 unverified / 0
  quarantined, 106 model-needed (15.3%), 14 model rows, 36 amend links. Tests 46 passed; typecheck 0 errors.
  Reports `.tmp/t231/report_c.md`, `.tmp/t231/recall_c.md`; docs updated. Commit requested.
- 21 Nov stage D (T-229, factor study): `factor_store91_stagec.py --events` adds ev_order_inflow_12m,
  ev_capex_12m, ev_raise_12m (verified/company/PIT 15:30, amendments only increments, raises one per
  raise_id). Run on `.tmp/t229d`: ev_raise passes the gate (37 companies, 15 month-ends >=20; 3m IC
  +0.120 t 2.06, 6m +0.204, 12m +0.441); order inflow/capex fail coverage; all three have 0 residual
  months (residual cross-section peaks at 18 < 20). Tests 9 passed; typecheck clean. Doc section 11 added.

## T-233 fast fix loop (21 Nov)
- Golden sets 181/146/69 lines from all seven Wolf reads (89.7% keyed back), `scripts/regress.py` gate + baseline diff, common `--only` selector hooks in observations/filing_events/driver_claims repair. 17 new tests + 222 pipeline tests pass, typecheck 0. One real catch on the live observations DB: RSYSTEMS EBITDA stored `ebitda.delta` (read B #35).
- T-232 (worker): --parts/--doc-types on tg_measure_build, deck manifest from deck_sources, docs_collect doc-type filter, --raw-root for deck builds, measure_store guard; 9 tests pass; pilot 10 building under .tmp/t232/pilot (D: root needs the controller: sandbox denies D: writes).
- 2026-11-21 T-230I (stage I of T-230, model-free): per-unit/trillion scale, table-vs-chart axis ticks, comparison-word periods, area/energy units, Unicode dashes, area-delivered/ESG/peak-demand dictionary, lower bounds (`value_kind`), footnote basis, entity-scope cue. 394 recheck: verified 16,284 -> 17,683, gate 40 right / 14 fixed / 6 still wrong / 0 newly broken. 91 recheck: verified 70,387 -> 69,926, quarantined 1,927 -> 151, gate 118 right / 18 fixed / 34 still wrong / 11 changed / 0 newly broken. 272 tests, typecheck 0; golden set 181 -> 241 lines (60 graded rows from Wolf's decks394 read A).
- 2026-11-21 T-230J (stage J, after Wolf's review): axis ladder needs 5 values + not a table page + no printed label beside the value (523 of the 543 obs_91 rows stage I lost come back); `is_total` column persisted and re-derived on recheck, parts-sum pass restored (135 of 144 known losses); `regress` skips golden lines for companies a DB does not hold. 394 verified 16,284 -> 18,008; obs_91 70,387 -> 70,578 (quarantined 1,927 -> 151); gates 40/14/6/0 and 118/18/34/11/0; 128 tests, typecheck 0.
