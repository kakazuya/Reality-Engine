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

## 2. GPU vs CPU benchmark — SEE SECTION 3 (filled in when the worker finishes)

Worker `20261029T213416Z-ca99007d`, lease until 06:15 IST. If section 3 is still empty, it has not finished: check with `worker_status`.

## 3. GPU result
(pending)

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
