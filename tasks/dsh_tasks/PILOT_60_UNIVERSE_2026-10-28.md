# Task — expand the pilot to a stratified 60-company universe + whole-market T1, and instantiate the bank's templates on it

## Goal
Shivam (2026-10-28): testing only the companies the questions already name is too lenient. It hides gaps for other caps, sectors and data shapes. The pilot must let most of the 1,073 master-bank questions be asked and answered across a diverse universe:
- **60 companies:** 10 large caps, 20 mid + small caps, 30 micro caps;
- spread across **≥15 sectors** (our sector label → BSE sector, per decision 8; resolve by ISIN);
- plus the companies named in the bank, so the 30 regressions keep their answers.

This is step 4 of the golden rule (pilot). No full run.

## Do
1. **Universe selection:** `reality_engine/pilot/universe60.py`.
   - Market-cap buckets as of 2026-09-30, from `company_state_daily` (or the held mcap tier where it is missing). Large = top 100, mid+small = 101–750, micro = the rest, with traded value > 0 on ≥ 200 sessions in FY26.
   - Stratify by sector so each bucket covers as many sectors as possible. Prefer companies with all doc types FY25+: concall, deck, AR, results notes, announcements. Require at least 1 concall and 1 AR for large/mid, and at least 1 of each where they exist for micro.
   - Write `tasks/pilot60/UNIVERSE.csv`: isin, symbol, bucket, sector, doc counts by type. Add a sector × bucket table.
2. **T1 for the whole market** (sector/index/market-wide screens need everyone):
   - run `python -m reality_engine.pilot.build_t1 --universe all --out .tmp/pilot_all`;
   - if the index-coverage worker's branch (`dsh/20261028T165609Z-069a714a`) has merged into main by the time you start, use its build. Otherwise use main's, and note it;
   - report the build time and row counts.
3. **T2 chunks** for the 60 + bank-named ISINs:
   - use `reality_engine/processing/chunker_v3.py`. Take the latest main; the T2 pilot worker's fixes may have merged. If `dsh/20261028T155107Z-484394b6` hasn't merged, cherry-pick nothing; use main and note it;
   - source the FY25+ originals from D: (`concall_pdfs`, `deck`, `decks*`, `annual_report`, `pdfs`, `results_pdfs`, `material_announcement`, `nse_announcements/*/attachments`);
   - known_at comes from the filing records;
   - build into `.tmp/pilot60/chunks_v3_pilot.db`, with coverage per ISIN × doc type and every missing original listed.
4. **Instantiate the templates:** `tasks/pilot60/instantiate.py`.
   - For each master-bank case with a single-company entity, make 3 instantiations on pilot companies: one per bucket, same sector when the case has one, otherwise random with seed 20261028.
   - Keep the original case as well.
   - Multi-company/peer cases: substitute a same-sector pilot peer set.
   - Sector/industry/index/theme/mcap/market-wide/policy/macro cases run as they are on the whole-market T1.
   - Shift period/as_of only when the original's date doesn't exist for the new company. Otherwise keep it.
   - Write `INSTANCES.jsonl` with parent `mid`, the substituted entities and the bucket.
5. **Run** the query layer (`reality_engine/query/`, the latest main) over every instance + original. Point it at the pilot DBs: market_state/facts at `.tmp/pilot_all`, and `REALITY_CHUNKS_V3=.tmp/pilot60/chunks_v3_pilot.db`.
   - Grade strictly: every sub-question must be answered for ANSWERED; it must use the named or latest document; and the PIT audit must pass.
   - Ground truth is unknown for instances, so grading checks answerability + evidence + PIT.
   - Then **hand-check 60 instance answers**, 20 per bucket, for correctness against the source rows. Report the precision.
6. **Report** in `tasks/pilot60/REPORT.md`:
   - answered % overall;
   - by bucket (large / mid-small / micro);
   - by sector;
   - by family;
   - by entity level;
   - the bucket × family heat table;
   - the top gaps per bucket (what micro caps lack vs large);
   - each gap mapped to the table/fetch/tool that fixes it, ranked by cases unblocked;
   - PIT violations;
   - latency p50/p95 per planner.

## Rules
- Read-only on live DBs and D:. Write only in this worktree (code, tests, `.tmp/`, `tasks/pilot60/`). No network, no paid embeddings, no commits.
- No grading leniency. A wrong-company or stale-document answer is WRONG, not PARTIAL.

## Acceptance checks
1. UNIVERSE.csv has 60 rows: 10/20/30 across ≥15 sectors.
2. INSTANCES.jsonl covers ≥ 90% of master-bank cases, either instantiated or run as they are, and every skipped case has a reason.
3. REPORT.md has every breakdown above, plus the 60-answer hand check.
4. `python -m unittest reality_engine.tests.test_pilot_t1 reality_engine.tests.test_chunker_v3` passes.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_pilot_t1 reality_engine.tests.test_chunker_v3
```

## Report
Give:
- the universe table;
- the overall and per-bucket answered %;
- the hand-check precision;
- the top 15 gaps with their fixes;
- PIT and latency;
- your tool-call count.
