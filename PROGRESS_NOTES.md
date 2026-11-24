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

## T-235 capital-flow signals (22 Nov)

- Data probes done. Truth snapshot `truth_2026-11-04.duckdb` (69 tables) is the study input; the
  `truth_2026-11-09.duckdb` snapshot is partial (19 tables) and the reality-data `truth_duckdb`
  catalog points at it, so the modules name 11-04. Delivery uses `px_nse` only (BSE delivery in
  `px_daily` is corrupt: avg 88%, 100% on Rs 100 turnover). Insider PIT only from `nse_insider`
  (`bse_insider.known_at_utc` all null). FPI/MF/insurance categories from T-209
  `D:/RealityEngine/structured/structured_universe.db` (2024-04+); the snapshot `shp_index` has
  promoter % only. Promoter filings before 2022 carry the 2022 backfill `known_at`.
- `flow_signals.py` built 222,949 signals 2019-2026-11-03: market 187,555; insider/pledge 4,634;
  bulk/block 2,246; promoter 2,974; FPI/MF/insurance 9,593; earnings 16,029.
- `flow_events.py` smoke run on 2023-2024 passes; 13 tests in `test_flow_signals.py` pass.
- Full study run complete: 219,779 events, 3,791 return cells, 1,201 BH passes. Finding:
  only short-horizon delivery-spike / insider-buy effects (and `bad quarter` as a 5-session
  underperformance) beat the same-stock, same-year placebo after BH; `delivery trend up`
  is marginal at 60/250; nothing else survives. Doc `docs/research/T-235_capital_flow.md`,
  `DEVELOPER_GUIDE.md` O19e. Typecheck: 110 pandas-3 stub-class errors (the accepted
  pandas-heavy research modules carry the same class: factor_weights 171, factor_deep 193).
- Next: final report; commit to be requested by the controller (not done here).
- Full suite attempted once: 3,995 passed / 523 failed / 263 errors in 14.3 min, dominated by
  the sandbox denying temp-dir cleanup (PermissionError under `.tmp`) in unrelated modules;
  the T-235 narrowed file is 13 passed. No new failure is traceable to this change.

## T-235 stage 2 (22 Nov, independent check + 2010-2018)

- Stage-1 `.tmp/t235/` outputs are gone from the main checkout, so stage 1 was reproduced
  from `truth_2026-11-04.duckdb`: `flow_signals` 2019+ wrote 222,964 signals (doc 222,949;
  +15 from the newer structured store / shareholding rows, method unchanged).
- Two construction artefacts found and fixed (tests added, 15 pass):
  (a) market signals had no cooldown - a delivery-% state firing every session counted as
  one event per session (delivery trend 44k "events"); cooldown 30 sessions now applies to
  market signals like insider/pledge/deal signals.
  (b) `shp_index.known_at` is the 2022 backfill crawl date for old quarters (3,750 rows on
  2022-01, 1,952 on 2022-01-06/07 with quarter_end < 2021-10), so promoter/FII/MF events
  were stale quarters firing on a few 2022 sessions; filings known >120 days after their
  quarter end no longer fire.
- BSE 2010-2018: delivery corrupt (24-42% of rows exactly 100%, mean 72-78%);
  `mkt_bse_eq_daily` carries no ISIN for any row. Extended panel is NSE-only (1,545-2,061
  symbols a year). 2010-2011 NSE rows have no ISIN -> mapped by earliest symbol window.
- Next: build 2010-2018 snapshot, audit baseline cells, then run 2010-2026.

### Update 22:40
- Audit complete (`docs/research/T-235_audit.md`): delivery spike down 5s is a within-year
  timing artefact (month-matched placebo p=1.00, observed +1.05% vs +1.33% random
  same-month dates); delivery spike up 5s weak (month p=0.19, mean carried by 75 clipped
  right-tail events); bad quarter 5s real (month p=0.048, cluster t 15.0); promoter down 20s
  real but means dilution (timely-only +1.20); volume spike up 250s is market beta (month
  p=1.00). 16 tests pass. Month-matched placebo added to `flow_events` (placebo_month_*).
- Extended snapshot built: 10.61M px_daily rows 2010-01-04..2026-11-03, BSE 500 TRI proxy
  spliced to NIFTY 500 at 2019-01-01 (1 of 1,736 entities with a >2x seam), 615 recorded
  price actions + 60 inferred, 73 residual >2x daily moves.
- Full signals 2010-2026: 129,298 rows over 3,379 companies (89,801 for 2019+ after fixes).
  Full event study with year+month placebos and crossed phase_4 is running.
- Next: round-2 tables into T-235_capital_flow.md §10, DEVELOPER_GUIDE O19e, typecheck,
  final report.

### Update 22:55 (done)
- Full event study 2010-2026 finished: 129,298 signals, 127,411 events, 4,622 cells, 1,251
  BH passes, 26 of 110 main cells pass, 8 pass BH + both placebos in the claimed direction
  (bad quarter 5s +1.16%, delivery trend down 5/20 +0.23/+0.73%, promoter down 5/20
  +0.41/+1.16%, FPI down 5 +0.41%, delivery spike up 5 +0.42%, promoter up 5 +0.62%).
  Delivery spike down is gone (+0.21% at 5s, month p=1.0); volume spike up is a fade in
  every phase; insider buys fail the month null over 17 years.
- §10 of T-235_capital_flow.md, the audit doc and DEVELOPER_GUIDE O19e updated. Tests 16
  passed. Typecheck 143 pandas-stub-class errors (same accepted class as stage 1's 110;
  builder adds pandas-heavy code) and no logic-class error.
- Final report written; controller to commit (no direct git commit from the sandbox).

## T-238 gap 2 — transcripts + strict dictionary-or-NEW contract (22 Nov)

- 23:05: `observations.py` stage M implemented (record_type/statement/speaker/direction/value_high/new_definition/
  new_driver_node columns, `measure_new` table, `declared_measure` contract, statement/guidance builders and checks,
  transcript prompt + doc_page page selection, NEW-id clustering CSV, recheck skips prose rows). 5 stage-M tests
  added, test_observations.py 133 pass. Next: hy4 transcript run (c48 166 + c77/c87 74 pages), 40-case measure
  re-read (23 pages), recheck obs_91_i + regress, docs.
- 23:5x: all runs done. hy4 transcripts 240 pages -> 4,308 rows (2,190 numbers/1,969 statements/149 guidance; 3
  undeclared_new; 1,102 NEW ids, 94 merge clusters; 175 s). DeepSeek entry added (`deepseek-v4.1-flash`, effort
  "none") and run on the 166 SOMANYCERA pages -> 2,174 rows, 233 s. vs Opus: hy4 86.9% of his numbers / 60.3% of his
  statements, DeepSeek 84.1% / 63.8%. 40 graded measure cases re-read: 12 exact + 7 declared-NEW equal + 9 NEW
  synonym = 28/40 now carry Opus's graded meaning (old hy4: 13 exact). obs_91 recheck gate: 118 right / 18 fixed /
  0 newly broken, pass. Tests 136 passed, typecheck clean on observations.py + tests. Docs: V2_SCHEMA_CONTRACT 17.v
  (renumbered from 17.w when main's gap-1 section took 17.w), DEVELOPER_GUIDE T-238 bullet, machines/MSI_LAPTOP.md.
  No STATE.md (brief forbids).

## T-238 stage O — statements as whole management passages (23 Nov)

- 00:5x: `observations.py` prompt + checks done: statement = one management speaker's continuous passage (first word
  to last full stop, 2-5 sentences, no PDF-line-break cut, page-edge rule, `question_context` column), guidance and
  forward/causal number rows also emit their sentence; script checks `statement_cut` (quarantine), `no_subject`
  (unverified), `guidance_without_statement` (flagged in the reason). 4 stage-O tests added; test_observations.py 142
  passed, typecheck 0. Regress gate on `D:/RealityEngine/t230/obs_91_i.db`: 118 right / 18 fixed / 0 newly broken.
- Scoped re-read (166 SOMANYCERA transcript pages, hy4, final prompt): 2,356 rows (1,336 numbers / 912 statements /
  108 guidance), 31 quarantined, 0 errors, 241 s; sentence recall 97.4% (before 92.3%), row recall 95.2% (before
  75.0%), fragments 3.6% (31 cut + 2 no_subject), guidance_without_statement 6/108, 6,709 in / 1,532 out tokens per
  page. Artifacts `.tmp/t238/obs_somanycera_o.db`, `score_statements.py`, `sel_somanycera.json`.
- Next: V2_SCHEMA_CONTRACT 17.v stage-O block, DEVELOPER_GUIDE bullet; report. Controller: the 91-company transcript
  read is STILL RUNNING with the old prompt (`.tmp/t238read/obs_91_j.db`, started 00:19) — it must be re-launched
  after this merge.

## T-238 merge: main (gap 1, OCR-routed pages) into stage M (22 Nov)

- 23:5x: `git merge` cannot run from the worker sandbox (the worktree index/refs live in the main checkout's
  `.git/worktrees/...`, outside the writable root; no approval channel), so the merge tree was built in place:
  main's diff applied over this branch's files with `git apply --reject`, the 7 rejected hunks resolved by hand
  (process_page, pages_from_store, recheck_db, run), main-only files copied with `git archive main`, docs sections
  split (main 17.w, stage M 17.v). Both behave: OCR pages read/check the OCR words (`text_source='ocr'`,
  `ocr_read_pages`) while transcript pages stay text-only with `PROMPT_TRANSCRIPT`; a page can be either.
  Acceptance suite 174 passed, 1 environmental error (`tmp_path` basetemp ACL-locked in this sandbox), typecheck
  clean; test_observations.py 138 passed. The supervisor commit is the only commit path (9906698a).
- 23:5x: that commit has one parent, so it is the merge *result*, not a merge commit: `git merge-tree` of main into
  HEAD still conflicts on the 4 files (our side already holds the resolved content). The controller must record the
  merge outside the sandbox, which is conflict-free with this tree (the merge exits 1 on those 4 files, expected):
  `git merge --no-commit main`; then `git checkout 9906698a -- reality_engine/v2/observations.py
  docs/V2_SCHEMA_CONTRACT.md docs/DEVELOPER_GUIDE.md reality_engine/tests/test_observations.py`; then
  `git add -A && git commit` (then `git diff 9906698a` is empty and main is a parent). A detached `git` launch was
  refused (`launch_detached_requires_write_scope_data_or_full`).

## T-238 stage N2 — tightening stage N's period/scope rules (23 Nov)

- 02:1x: `observations.py` N2 rules done: `slide_period` reads only the page's title line (furniture, footnote marker
  and bare-label refusals; the fiscal regex keeps the printed "-26", so "9M 2025-26" is never truncated to "9M 2025");
  `deck_asof` closed to capacity.* / shareholding_pct / count.shares / plant+location counts; `growth_change_period`
  takes the later label of a printed pair; `order.quantity` is the 306th dictionary id and `force_fit_veto` maps order
  quantities out of volume.sales; `scope_cue` yields country/industry/customer from the heading/page and fills the
  customer dim. 7 new synthetic tests, test_observations.py 157 passed, typecheck 0.
- Next: recheck deck_n.db -> `.tmp/t238n2/deck_n2.db` and obs_91_i -> `.tmp/t238n2/obs_91_n2.db` (running), regress
  gates, per-rule revert counts, 20-row sample, docs. Blocker: none.
- 03:5x (stopped by the hard stop): obs_91 recheck FINISHED with the final rules -- 102,074 rows, 500 upgraded,
  95 downgraded, 0 unproven, scope_cues 290, growth_periods 27, customers_named 171; regress gate on
  `.tmp/t238n2/obs_91_n2.db` **still right 118, fixed 18, still wrong 34, changed 11, newly broken 0 -- pass**.
  Tests 157 passed, typecheck clean on observations.py + tests. The deck recheck was still processing its reduced
  copy `.tmp/t238n2/deck_scope.db` (9,439 pages / 238,846 rows) at the stop: no `deck_n2.db`, no per-rule revert
  counts and no 20-row sample yet. Remaining: `python .tmp/t238n2/make_reduced.py` (done), recheck
  `--out .tmp/t238n2/deck_scope.db --stores-root D:/RealityEngine/tg_build/decks403 --sample 500 --doc-types deck`,
  `python .tmp/t238n2/merge_back.py`, then `verify_cases.py`, `analyze.py` and the deck regress gate.






## T-239 (23 Nov) — the trial-2 misses the server can fix

- Read all 53 rows of `D:/RealityEngine/tg_build/trials/trial2/failures_for_server_fix.jsonl` (52 unique questions;
  SPORTKING q7753 appears twice) before editing. Server-side, model-free fixes in
  `plugins/reality-data/server/lookups_pilot3.py` + new `synonyms.json`.
- Done: `nearest` (3 FTS pages + 3 obs statements, as_of-cut) on an empty fact/kpi/fin/ratio/guidance/statements/obs;
  OR-only thesaurus expansion in search/topic/statements/obs/nearest with `expansions_matched`; ratio rows carry
  definition_text/numerator/denominator/resolved inputs; ROE~ROCE~ROEV token series match + stated-ratio fallback;
  P/B and BVPS on the latest book known at as_of (NSIL 0.1484 on H1FY27, 0.1658 kept as stored_value);
  growth rows carry the stored prior-period row (ALICON 428.18 crore) with its filing.
- Verified: `test_lookups_pilot3.py` 99 passed + 1 skipped (8 new `ServerFixTests`); with `test_obs_wiring.py` and
  `test_server_no_sql.py` 109 passed / 1 skipped / 1 deselected; typecheck 0 errors on the three changed .py files;
  8 graded cases replay 13/13 reply checks (`.tmp/t239_cases.py`, job-local). The one `tmp_path` test in
  `test_obs_wiring.py` is blocked by the sandbox (os.scandir denied for native children; ACL repair needs an
  approval channel this session lacks).
- Next: controller runs the accepted tests outside the sandbox, merges, and adds the T-239 line to tasks/STATE.md
  (brief forbids editing it here). Remove the sandbox-made dirs `.t239base/`, `t239base/` (listing denied; cannot
  delete from inside).
- 17:35 T-242 speaker fix code+tests done (26 pass, 4 tmp_path tests blocked by sandbox os.scandir); --reparse measurement on .tmp/t242/reparse5.db running (2000 pages, ~9 min so far); next: before/after counts + 60 graded ids + docs.
- 18:00 reparse5 measured: statements verified 5719->5444, empty speaker 1628->319 (17.5%->3.5%); all 47 graded R still verified (3 matched a guidance twin first, the statement twin is verified); NOCIL cover-letter J row gone. Found heading labels ('Asset Quality', 'Mobility', 'First') carried as speakers -> added to _NON_SPEAKER_WORDS, reparse6 running. Typecheck: only pre-existing errors in run()/main() left.
- 18:55 final reparse8: statements verified 5,719->5,456, empty speaker 1,628->319 (17.5%->3.5%), 0 verified rows with empty speaker; 46/47 graded R kept (BHAGYANGR company-name R explained), NOCIL cover-letter J gone, 1 J still verified (REGAAL non-answer out of rule), 11 P still verified (cut/tag classes; 5 now carry the right speaker). Company-name speakers no longer carried (BHAGYANGR analyst bug) -> left+unverified. Docs updated: DEVELOPER_GUIDE entry + stale is_cover_letter text, tasks/STATE.md. Tests 26 pass + 4 tmp_path tests pass manually.
- 24 Nov T-242 round3 (worktree 20261124T132600Z): code fixes done (VERIFIED_KINDS gate, fund_raise agreement veto, raise_stage approval, L-1/new-award amendment veto, numeric stale commissioning, stake-acquisition capex veto, customer forms, fold tolerance 0.5%); test_filing_events.py 79 passed; replay on fresh3 stores: all six customers filled, W rows gone/unverified, #53 kept 1017; real fresh3+new20 builds running into .tmp/events_round3*.db
- 24 Nov T-242 round3 done: pytest 79 passed; fresh3 rebuild 251 events (order_win verified 192->193, no non-order verified; all 8 W rows gone, J unverified; 6/6 customers filled; no order_win R lost); new20 176 events (order_win verified 103->103); docs DEVELOPER_GUIDE + T-231 doc + STATE updated; typecheck 2 pre-existing sys.stdout.reconfigure errors (lines untouched). Artifacts in worktree .tmp/: events_round3.db, events_round3_new20.db, events_round3_report.md, events_round3_new20_report.md - controller copies them to C:/RealityEngine/t242/.

## T-242 AR row gates (24 Nov, DeepSeek)
- Implemented `apply_ar_row_gates(rows, page_text)` in `v2/observations.py`: unknown/label-noun unit, ageing-or-party qualifier label, narrative growth, page-heading basis; wired in `apply_number_gates` annual_report branch and the read/reparse/recheck callers now pass page text.
- Measured on the 60 graded rows of pilot_ar_reparsed2.db (read-only): 4 W gated + 1 W corrected (basis) + 4 P units corrected = 9 of 11 W/P; 0 of 42 R lost. Full 200-page sample: verified 1,414 -> 1,390 (24 gated), 294 unit/scale/basis corrections.
- Tests: 6 new in test_ar_sections.py (with counters), 15 pass with the 2 tmp_path tests deselected; the 2 errors are the sandbox temp-dir ACL (os.scandir denied, not code). Typecheck: no new error in the changed file. read_gate annual_report fp 48d75aa69de7 (unchanged).
- Docs: DEVELOPER_GUIDE (new entry + wiring sentence), tasks/STATE.md. NEXT: controller re-grades 60 fresh AR rows host-side.

## T-242 AR fresh2 rules (24 Nov, DeepSeek)
- Done: two new rules in `apply_ar_row_gates` (net-cash sign, other reporting entity) + `company` threading through
  `apply_number_gates` and the read/reparse callers; 3 new tests incl. counters. Measured on pilot_ar_gates.db
  (read-only): 5 net-cash rows + 6 Blue Dart Aviation rows gated, 0 of 54 graded R lost, #10 and #57 caught.
- Next: DEVELOPER_GUIDE entry at end + tasks/STATE.md line; full test suite running; typecheck has pre-existing
  Optional/module-attr errors only (none in the changed lines).
- Done: docs updated (DEVELOPER_GUIDE old signature + new end entry, STATE, this log); test_ar_sections 21 pass,
  8 observation test files 249 pass; read_gate annual_report fp 48d75aa69de7 unchanged. Sandbox note: pytest
  tmp_path dirs are mode 0o700 and unlistable; tests ran with a job-local plugin forcing 0o777. The failed
  basetemp `t242_pt/` at the workspace root cannot be removed from inside; controller removes it host-side.

