# Fix task — G2 new-feeds review defects (verdict FAIL)

## Goal
Fix all 7 reviewer defects below in this worktree (`C:\Users\warri\Downloads\IDM-worktrees\20261025T123258Z-007ac55f`,
branch `dsh/20261025T123258Z-007ac55f`), with tests, and re-run the temp-copy dry runs.

## Reviewer defects (verbatim)
1. `reality_engine/scripts/fetch_results_notes_text.py:185` — limit applied before the done-check; backfill stalls after one run. Fix: iterate all filings, skip existing, `break` when processed reaches the limit.
2. `reality_engine/scripts/fetch_results_notes_text.py:34,140` — notes kept only when the page contains `\bnotes?\b`; IDBI 045d7744 page 15 (1869 chars, "(b) Details of loans…", "Bank has reversed provisions…") has no "Note" and is lost. Fix: store all pages of the opened results PDF.
3. `reality_engine/scripts/build_etf_premium.py:50-57` + `reality_engine/scripts/fetch_etf_nav.py:141-144` — two owners of `etf_premium`; fetch-after-build drops `inav`/`inav_gap_pct`. Fix: single owner.
4. `reality_engine/scripts/fetch_results_notes_text.py:106-124` — non-atomic `write_bytes` plus reuse of any `size>0` cache; a killed download wedges the run, and there is no sleep/retry. Fix: `.part` + `os.replace`, validate the PDF before caching, 0.5 s sleep + 3 backoff retries.
5. `reality_engine/scripts/fetch_results_notes_text.py:88-103` — nearest-time pick ignores standalone/consolidated; split-attachment revisions can lose a basis. Fix: match `filings.consolidated`/basis or process each Result announcement once.
6. `plugins/dsh-worker/jobs.yaml:519,718` — 30-day `max_age` for quarterly/opportunistic feeds reports stale between quarters/quiet months. Fix: 100–120 days or `min_count`.
7. `reality_engine/tests/test_new_feeds_g2.py:80-95` — `--limit`/newest-first test asserts only "1 distinct sha". Fix: assert the newest sha and add a two-run limit-progress test.

## Manager decisions
- Defect 2: store **every page** of each results PDF. Keep the table name `results_notes`, add a `has_note_word`
  flag column so searches can still prefer note pages.
- Defect 3: do **not** touch `fetch_etf_nav.py` (another worker edits it). `build_etf_premium.py` becomes the sole
  owner of a new table `etf_premium_daily` (date, isin, symbol, close, nav, premium_pct, inav, inav_gap_pct, built_at;
  PK date+isin). It does not create, drop or replace the existing `etf_premium` view. Update the job's `writes`, the
  freshness rule and the tests.
- Defect 5: process each Result announcement (NEWSID) once, storing its `source_newsid`, and link it to the
  filing(s) it matches. When a filing matches several announcements, keep them all, so no basis is lost.
- Defect 6: `max_age` 120 days for `results_notes_text` and `deck_page_text`.

## Files to touch
- `reality_engine/scripts/fetch_results_notes_text.py`, `build_etf_premium.py`, `build_deck_page_text.py` (only if
  needed for defect 7), `reality_engine/tests/test_new_feeds_g2.py`, `plugins/dsh-worker/jobs.yaml`,
  `reality_engine/tests/test_dsh_worker_plugin.py` (only if the jobs entry changes).
- Do not touch: `fetch_etf_nav.py`, `reality_engine/config.py`, any live DB.

## Acceptance checks
1. One test per defect, each failing before the fix and passing after (a two-run limit-progress test for defect 1).
2. `python -m unittest reality_engine.tests.test_new_feeds_g2` passes; if the sandbox blocks temp dirs, use a
   directory under the workspace `.tmp` and say exactly what was blocked.
3. Re-run the dry runs against temp copies:
   - VISHNU 2026-06-30: page count and all pages stored;
   - IDBI 045d7744: page 15 present;
   - MONQ50: `etf_premium_daily` rows for 2026-09-10..28, with the `etf_premium` view untouched.
   Print each.
4. `git diff --stat` touches only the files listed.

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_new_feeds_g2
```

## Budget
≤ 10 tool calls before the first edit; ≤ 80 total; $0 paid. Do not commit (Claude commits).

## Report format
1. Per defect: what changed (file:line) + test name  2. Dry-run outputs (trimmed)  3. Open problems  4. Tool calls.
