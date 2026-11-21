# T-233 brief: fast fix loop (golden regression sets + selector-scoped re-runs)

Ticket: T-233 (Shivam 21 Nov 2026). Reviewer: Wolf (Opus).

Goal: Shivam: "we waste too much time rebuilding stores and re-running everything per fix; build only the parts that
broke and test that nothing else broke." Today every review round re-ran all 91 stores and Wolf re-sampled 50 random
rows. Make a fix cost: re-run only the rows/pages it touches + a golden regression check in minutes.

Evidence: (real)
- Hand-graded reads (per-row grades with ids, RIGHT/MINOR/WRONG and defect): `D:/RealityEngine/t230/wolf_read_{b,c,d}.md`,
  `D:/RealityEngine/t230/wolf_visual_audit.md` (24 pages, per-number), `D:/RealityEngine/t228/wolf_read_91_s2.md`,
  `D:/RealityEngine/t228/wolf_read_91_s2c.md`, `D:/RealityEngine/t228/s2a/wolf_read_s2a.md`,
  `D:/RealityEngine/t231_wolf_read_a.md`, `D:/RealityEngine/t231_wolf_read_b.md`.
- Pipelines: `reality_engine/v2/observations.py` (has `--recheck` model-free and `--resume`; stage F/G workers are
  editing it now in other worktrees - touch only a thin hook, see Files), `reality_engine/research/filing_events.py`
  (model reply cache exists), `reality_engine/research/driver_claims.py` (has `--repair`).

Steps:
1. Golden sets: parse every read above into `tests/golden/<pipeline>.jsonl` (one line per graded row/page: key
   (store, doc_key, page, and the row's identifying fields - not the DB id, which changes across runs), expected
   fields when RIGHT, the defect class when WRONG/MINOR, the grader file). Where the read gives the correct value for
   a WRONG row, store it as the expected value. Report counts per pipeline.
2. `reality_engine/scripts/regress.py <pipeline> --db <out.db> [--baseline <old.db>]`: match golden rows to the DB by
   key; report fixed / still wrong / newly broken (a RIGHT golden row that changed or vanished) / still right; and
   the global diff vs baseline (rows added/removed/changed status, by measure/class). Exit nonzero on any newly
   broken row. Seconds, no model.
3. Selector-scoped re-runs: a common `--only <selector.json>` for observations.py, filing_events.py and
   driver_claims.py repair: a selector lists stores/doc_keys/pages (or a SQL WHERE over the output DB) and the run
   re-processes only those (recheck or re-read) into a copy of the baseline DB, leaving everything else untouched.
   For observations.py add only argument parsing + a page filter call; keep the rest of the file untouched.
4. Tests (synthetic DBs): golden match by key, newly-broken detection, selector filtering.
5. Doc `docs/FIX_LOOP.md`: the loop in 5 lines - write selector, run scoped, run regress, review changed rows only,
   merge on zero newly broken. Link from `AGENTS.md` only if under its 150-line limit, else from DEVELOPER_GUIDE.

Files: new `reality_engine/scripts/regress.py`, `tests/golden/*.jsonl` (or `reality_engine/tests/golden/` - follow
the repo's test layout), `reality_engine/tests/test_regress.py`, `docs/FIX_LOOP.md`; thin `--only` hooks in the three
pipeline files. Do not edit tasks/STATE.md.

Accept: tests pass; typecheck clean; `regress.py observations --db D:/RealityEngine/t230/obs_91.db` runs and reports.

Stop if: fewer than 60% of graded rows can be keyed back to a DB row (report why).

Budget: about 2 hours, DeepSeek max effort.
