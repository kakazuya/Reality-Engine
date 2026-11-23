# T-241 build speed brief: cut a store build's wall time without changing one stored row

Goal: the FY27 universe (4,652 companies) must be built by 27 Nov on an 8-thread, 16 GB laptop that is already at
99% CPU. Make `tg_measure_build` per-company builds at least 40% faster in CPU seconds, with byte-identical row
content in every store table (row order and timestamps excepted).

Ticket: T-241. Reviewer: Wolf (Opus). DeepSeek max effort.

Evidence: 107 companies built, `D:/RealityEngine/tg_build/full394/c*/parts.csv` and `c*_measure.json`:
- median wall 655 s, build 406 s, route 251 s, 2,584 pages, 205 raw files per company.
- part share of build seconds: docs_collect 39% (mean 204 s), stores 27% (138 s), kpi 18% (92 s), comparatives 4%,
  segments 4%, transcripts 2%, every other part under 7 s. `v2.page_route` (route) runs after, mean 313 s.
- `reality_engine/scripts/tg_measure_build.py:363-470` launches each part as its own `python -m` process
  (`pilot3.make_profile`, `pilot3.docs_collect`, `pilot3.build --part X`, `v2.page_route`); each re-imports and
  re-opens the store.

Steps:
1. Profile (cProfile, `--sort cumtime`) docs_collect, build --part stores, build --part kpi and page_route on two
   built companies copied to your worktree `.tmp` (copy `D:/RealityEngine/tg_build/full394/c01` and `c27`; never
   write under D:/RealityEngine). Report the top 10 functions per step.
2. Fix the measured hot spots only: repeated PDF opens/text extraction of the same file, per-row commits, missing
   indexes, regex compiled in loops, page rendering a route does not need, work redone across parts. Parallelism
   inside a step is allowed only if a `--jobs` flag defaults to 1.
3. Prove equality: rebuild both companies before and after into `.tmp`; for every table compare
   `SELECT * ORDER BY all columns` (exclude columns holding build time); routes.csv identical.
4. Test for each fix; docs: the tg_measure_build block in `docs/DEVELOPER_GUIDE.md` (timings before/after).

Files: reality_engine/pilot3/docs_collect.py, reality_engine/pilot3/build*.py and its part modules,
reality_engine/v2/page_route.py, reality_engine/scripts/tg_measure_build.py, tests, the guide.

Pitfalls: a running 394 build and the universe follow builder import these modules: keep every CLI flag and output
path unchanged. Do not loosen any row check, quarantine rule or route threshold. No models, no network.

Accept: equality report for 2 companies with 0 differing rows; CPU seconds per step before/after; new tests pass;
`python -m pytest -q reality_engine/tests/test_tg_measure_build.py` passes; typecheck 0 errors on changed files;
report under 25 lines.

Stop if: a speed-up needs a changed row, a model call, or a new dependency.

Budget: about 3 hours.
