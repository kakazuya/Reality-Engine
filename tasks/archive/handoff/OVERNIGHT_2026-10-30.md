# Overnight hand-off — 30 Oct 2026 (Wolf). Read this first in the morning.

## 1. LSP (code-intel) for dsh workers — ANSWERED, FIXED, COMMITTED

**Your question:** instead of asking workers to use LSP in the brief, can it be fixed in the MCP server so they use it by default?

**Finding — my earlier claim was wrong.** dsh workers have had code-intel as a *native* MCP tool since 25 Oct: the `headless` dsh profile (`~/.dsh/profiles/headless/cordis.patch.yml`) loads it as `mcp__code-intel__*`. I had said "0 calls" from a summary counter that only listed the top tools.

The real usage across all 183 worker jobs:

| tool | calls |
|---|---:|
| `mcp__code-intel__diagnostics` | 84 |
| `mcp__code-intel__symbols` | 28 |
| `mcp__code-intel__definition` | 2 |
| `mcp__code-intel__references` | 0 |
| grep | 651 |
| read | 2,593 |
| pwsh | 8,037 |

So workers had it but almost never used it for navigation.

**Three real defects, all fixed:**
1. **Stale answers.** Name lookups used old line numbers after git merges or edits (e.g. `period_bounds` was given as line 210; the truth is 219). Fixed in `plugins/code-intel/server/core.py` (merge `42bf8cb`): every query first re-syncs changed files (mtime sweep + git HEAD diff), checks that the line still holds the symbol, and falls back to an AST index. Freshness regression tests: 8 OK.
2. **Wrong checkout.** The profile pinned code-intel to the MAIN checkout, so a worker in a worktree got answers about main, not its own edited files. Fixed in the launcher, `reality_engine/scripts/run_deepseek_harness.py` (`1035dbb`): every run adds an overlay that re-roots the code-intel MCP server at the worker's own workspace. **Verified end to end:** a worktree with 9 extra lines in `router.py` returned `router.py:228` (main: 219) through the native `mcp__code-intel__definition`. This is now automatic for every worker; no brief text is needed for it to work.
3. **Not nudged.** Every brief now gets a standing instruction appended by the dsh-worker server (`plugins/dsh-worker/server/core.py`, `CODE_INTEL_INSTRUCTION`): use definition/references/symbols/module_map before grep or whole-file reads, run diagnostics on changed files, and report the code-intel call count plus the calls before the first edit.

A fallback CLI also exists: `python plugins/code-intel/ci.py <cmd>`, JSON output, ~0.3 s warm.

**Needs you:** restart the dsh-worker MCP server once (`/mcp` → reconnect `dsh-worker`). It loaded the old code, so new workers won't get the standing instruction until then. The worktree re-rooting is in the launcher, so it already applies.

**Measure on the next build worker:** code-intel calls vs grep/read, and calls before the first edit. Tonight's baseline is 13–77 calls before the first edit.

**Also found:** `reality_engine.tests.test_dsh_worker_plugin` has 8 pre-existing failures (worktree/merge tests), present before my change. A small fix worker is worth it.

## 2. GPU vs CPU benchmark — DONE, see section 3

Worker `20261029T213416Z-ca99007d`, lease until 06:15 IST. If section 3 is still empty, it has not finished: check with `worker_status`.

## 3. GPU result — DONE (merged; full tables in `tasks/arch_v4/bench_gpu.md`)

Measured on the GTX 1050 Ti with CuPy 14.2 against numpy fp32 (median of runs; GPU time includes host↔device transfer; CUDA cold start 0.75 s, paid once per process):

| tier | workload | CPU | GPU incl. transfer | speed-up | use |
|---|---|---:|---:|---:|---|
| hot | incremental 1-day update (4,042 × 33) | 1.47 ms | 3.25 ms | 0.45× | **CPU** |
| hot | 3-hop shock walk (2,000 × 500) | 5.29 ms | 1.93 ms | 2.75× (unstable) | tie → CPU (no CUDA start-up on the hot path) |
| nightly | full daily screen, pilot (492 days × 4,042 × 33) | 159 ms | 12.0 ms | **13.3×** | **GPU** |
| nightly | rolling stability, 20 windows × 10 lags | 546 ms | 118 ms | 4.6× | **GPU** |
| cold | permutation test, 1,000 shuffles | ~2.65 s per 20 shuffles | 8.97 s for all 1,000 | **14.5×** | **GPU** |
| cold | A²/A³, 8,000 × 8,000 | 5.37 s | 1.36 s | 4.0× | **GPU** |
| cold | covariance + top-20 eigenvectors, N=4,042 | 7.22 s | 1.38 s | 5.2× | **GPU** |

**Verdict:** my thesis was half right. CPU keeps the hot path (lookups, incremental update). But the GPU wins the **nightly** tier too, not just the weekly batch: the full screen is 13× faster at pilot size. It wins the cold tier by 4–15×. Crossovers are small: the screen wins on GPU from ~1,000 companies, covariance from N≈512.

**Correctness:** 23/30 rows match numpy within tolerance. The 7 misses are fp32 rounding on near-zero correlations, and the GPU fp32 was actually closer to the fp64 truth than numpy fp32 was.

**Real findings for the v4.2 worker:**
1. `tasks/arch_v4/bench_screen.py` multiplied returns by raw driver LEVELS (values up to 55,385), so its "screen" was not a correlation and any p-value from it would be meaningless. Drivers must be standardised. Fix `bench_screen.md` too: its GPU guess is wrong.
2. **The false-discovery design has a problem.** The permutation null's max |corr| is ~0.95, not ~0.05. After stripping the 20 factors, companies in small index-membership groups nearly reproduce the group mean (near-collinear), so a max-statistic null is far too conservative. The design needs a different null (per-pair or block permutation, or dropping self-membership drivers).
3. numpy fp32 eigendecomposition is no faster than fp64 (LAPACK-bound).
4. Any sandboxed CuPy use needs `CUPY_CACHE_IN_MEMORY=1` (the dsh sandbox blocks CuPy's temp-file kernel cache).

The worker made its first edit at call 13 (~95 total). It re-ran the full benchmark 7 times because each run exposed a real bug (unstandardised drivers, tie-breaking that made CPU and GPU solve different walks, label mismatches).

**Commits:** the merge of this benchmark and this section are committed locally after `36ff086` and NOT pushed. A new session on this machine sees them.

## 4. Other state from tonight (all on main, pushed to `c7b1010`; later commits are local)
- **Gate:** strict 61/2,681 = 2.3% (was 1.0%).
- **Merged:**
  - v4 design `6ec90e8`;
  - NID triage `d1ad769`: 150 → 74 fetch / 74 proxy / 2 absent, 121 h;
  - v4.1 design `f2a0c04`;
  - code-intel `42bf8cb`.
- **Next:** the v4.2 worker. Fold NID triage into the work packages, add the GPU results, re-estimate the sector build in worker-hours (v4.1 said 19–24 person-days), and note the opinions store (529 raw files, covers 1/60 pilot names).
- **Not pushed:** local commits after `c7b1010` (`1035dbb` and this file). Push only with your OK.
- **Still to check:** the `macro_all.db` rebuild (commodity targets) was started detached at ~02:50. Output is in `.tmp/pilot_all/`; it needs copying to `reality_engine/data/pilot/macro_all.db` once checked. Log: `.tmp/macro_claims_rebuild.log`.
- **Worktrees:** IDM-worktrees went from 49 GB to ~7 GB (57 merged worktrees removed). Rule saved: remove the worktree after every merge.
