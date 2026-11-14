# T-210 panel run under 4.5 GB: make factor_deep fit this machine, then run it

Ticket: T-210
Goal: `python -m reality_engine.research.factor_deep --out .tmp/t210` must complete on this laptop (16 GB, about
5.9 GB free at idle, about 10 GB used by the OS and resident apps; Shivam 14 Nov: 7 GB free will never happen). Cut
the run's peak memory to <= 4.5 GB without changing any statistic, then run it in full and write the results into
`docs/research/T-210_factor_deep_study.md`.

Evidence:
- `docs/DEVELOPER_GUIDE.md` section O19d describes the study and all outputs. The run was never started: the brief's
  7 GB free-RAM gate was a guess, never measured (free RAM 2.6-4.7 GB while three workers ran, 14 Nov 00:12-01:42).
- `reality_engine/research/factor_deep.py` `main()` builds the panel with `factor_weights.build_panel(con, start, end)`
  over the DuckDB truth snapshot (`default_snapshot()`), writes `.tmp/t210/panel.parquet`, then runs the sector IC
  table, correlations, Fama-MacBeth, 595 pair interactions with 20 placebo permutations, sparse walk-forward and the
  KPI arm. Tests: `reality_engine/tests/test_factor_deep.py` (13 passed).
- Another worker (DeepSeek, T-213) runs at the same time; it uses little RAM.

Steps:
1. Measure first. Run `python -m reality_engine.research.factor_deep --out .tmp/t210 --project` under a sampler that
   logs the process's peak working set (psutil, once a second, to `.tmp/t210/mem.log`). Record peak RAM separately for
   the panel build, the panel load and the projection loop, and the projected full-run minutes.
2. Find where the peak comes from (read the code; DuckDB `.df()` of the whole price table, float64 frames, panel copies
   per sector, permutation copies). Fix with general means only:
   - build the panel per year range or per entity batch and append to the parquet;
   - set the DuckDB `memory_limit` (e.g. '2GB') and `threads` to bounded values;
   - downcast factor columns to float32 only where the result is unchanged at the printed precision;
   - read only the columns each step needs, and drop per-sector copies after use;
   - generate placebo permutations one at a time.
   Do not change any statistic, threshold, factor list or output format.
3. Prove the outputs are unchanged. On a small fixed slice (2 sector groups, `--placebo-runs 2`), produce the outputs
   before and after the change and diff the CSVs: equal to 1e-9, or to float32 rounding where you downcast (say which).
   Add a test to `test_factor_deep.py` for any new chunking function.
4. Run the full study: `python -m reality_engine.research.factor_deep --out .tmp/t210` (add `--rebuild-panel` if the
   panel format changed), with the memory sampler running. Guard: if system free RAM falls under 1.2 GB, stop the run
   cleanly and report the step it was in. Keep `.tmp/t210` (it stays in the worktree; Claude copies it).
5. Write the results section of `docs/research/T-210_factor_deep_study.md`:
   - the per-sector rewarded sets and their mode;
   - redundant factors;
   - claimed interactions against the placebo;
   - the sparse combinations against EQUAL and DYNAMIC;
   - the company gaps and the KPI arm, labelled as a method pilot;
   - the measured peak RAM and minutes.
   Update O19d in `docs/DEVELOPER_GUIDE.md`: the new memory behaviour, the measured peak, and the 7 GB note replaced by
   the measured figure.

Files: `reality_engine/research/factor_deep.py`, `reality_engine/research/factor_weights.py` (panel build only, if it
is the peak), `reality_engine/tests/test_factor_deep.py`, `docs/research/T-210_factor_deep_study.md`,
`docs/DEVELOPER_GUIDE.md`. Do not edit `tasks/STATE.md`. Read the snapshot and pilot stores read-only; write nothing
under D:/RealityEngine.
Accept: python -m pytest reality_engine/tests/test_factor_deep.py -q
Test command: python -m pytest reality_engine/tests/test_factor_deep.py -q
Pitfalls: the T-118 reproduction gate (< 0.005) must still pass on the rebuilt panel. Never run two full studies at
once. The `.tmp` folder must stay in your worktree. Report every number from files you produced, not from memory.
Stop if: peak RAM cannot get under 4.5 GB without changing a statistic (report the measured peaks and the cause); the
T-118 gate fails; the full run is projected over 4 hours (report the projection and stop before running it).
Budget: 4 hours wall time including the run; code changes within the first 90 minutes.
