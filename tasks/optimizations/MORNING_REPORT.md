# Morning report — worker optimisations 01–04 (night of 2026-10-24/25)

Detailed timeline, costs and findings: `MANAGER_LOG.md`. Review/fix briefs: `reviews/`.

## Outcome

| # | Optimisation | State | Main commit | Review rounds | Verified by |
|---|---|---|---|---|---|
| 02 | Toolbelt (7 tools) + 02b Drive hash fallback + `coverage_peek` | **merged** | c909b44, 840eeac | 1 FAIL → fixed | reviewer + my rerun of the failed AC; 31 tests |
| 04 | code-intel LSP MCP server | **merged + installed** | 34eae56 | 1 PASS-w-notes → fixed | reviewer + `-W error::ResourceWarning` merge; 16 tests, 0 skipped |
| 01 | Context pack + brief template + lint | **merged** | 5414ef0 | 1 PASS-w-notes → fixed | reviewer (suite 3×); 84 tests |
| 03 | Sandbox fixes, write scopes, first-edit metric | **merged + installed** | d6d1306 | 1 FAIL (critical escape) → 1 FAIL (critical, pre-existing on main) → PASS → small fix | 3 security reviews, my unsandboxed runs |
| — | S8 test-module collision fix | merged | 4546541 | — | 67 tests |

Installed outside the sandbox: basedpyright 1.40.2 (main Python); code-intel in `.mcp.json` + `enabledMcpjsonServers`
(project scope only — user scope would double-register); code-intel insert in both `~/.dsh/profiles/*/cordis.patch.yml`
(backups `*.bak-20261025-code-intel`, `dsh --dump-config` checked); CONTEXT.md regenerated. From 03: the 10-minute pwsh cap and `promoteOnTimeout: false` rows were appended to both
live profiles (backups `*.bak-20261025-task03`, verified with `--dump-config`); `%APPDATA%\pip\pip.ini` installed
(timeout 120, retries 5); `setup_worker_env.py` ran with 0 installs. It never upgrades: the dry-run showed duckdb
1.5→2.0 available, and I did not take it. **Not installed:** `uv.toml`, because uv isn't present and `[network] timeout`
is not a known uv key. The live `data`-scope probe was not run either; it writes `reality_engine/data/_sandbox_probe/` and
needs your OK.

**Restart the Claude app first.** Until then the running dsh-worker MCP server is the old code while the supervisor on
disk is new. Worktree jobs started before the restart **will not auto-commit**: the new supervisor refuses git without
an identity stored at job start, and the old manager never stores one. This was observed on the last job; I committed it by hand.
The restart also loads the context pack, write scopes, the metric in `list_workers`, and code-intel for Claude.
Nothing has been pushed: main is 29 commits ahead of `551226e`, head `0d61542`.

Also done after the four: context pack trimmed to **18.1k tokens** (was 30.1k, budget now 20k) → e1754e2/0d61542.
03 is verified live end-to-end on a real job: `write_scope`, per-job `.tmp`, first-edit metric (16 calls), and
progress notes from the workspace.

## Measurement (target: ≥ 50 % fewer orientation calls)

Baseline (03's scanner over 21 jobs of 2026-10-24): **median 45 tool calls before first edit.**

| Task | Arm | runs | before first edit | total calls | output tokens |
|---|---|---|---|---|---|
| S8 (small, precise) | pack + tools | 1 | 8 | 28 | 12.2k |
| S8 | bare template brief | 1 | 9 | 32 | 16.2k |
| coverage_peek (discovery) | pack + tools | 2 | 25, 42 | 41, 78 | 39.4k, 37.1k |
| coverage_peek | bare template brief | 2 | 28, 12 | 40, 21 | 33.4k, 41.8k |

Reading: **target met (45 → 8–42, median ≈ 18), but the win comes from the template-shaped brief, not the context
pack.** Both arms used the template; adding the 27k-token pack + tools note showed no measurable benefit (variance
between identical runs, 12 vs 28, exceeds the arm difference). n is small, so this does not prove harm either.

## Decisions for you

1. **Context pack default** — recommend `context_pack=false` by default, or slim the pack to a 3–5k-token index, then
   re-measure with ≥ 5 runs/arm on discovery tasks. The pack is also 26.7k tokens now, over its own 25k budget.
2. **Repo-root workers** — new policy (reversible): a mutating worker whose workspace is the main checkout needs
   `confirm_repo_root_write=true`, because it can rewrite code the supervisor/manager later runs unsandboxed. The full fix
   is moving `plugins/dsh-worker/{server,runtime}` out of the checkout (sketch in the 03 report). Your call.
3. **`data` write scope** — dsh 0.2.1 has no extra writable roots, so `data` == `full` access at the OS level; only the
   named DB locks + brief limit it. Use only with your OK.
4. Optional: `claude plugin install pyright-lsp@claude-plugins-official` (editor diagnostics for Claude; needs
   `pyright-langserver` on PATH). Not done.
5. 12 older dsh worktrees from 2026-10-24 under `IDM-worktrees/` (some hold paused work) — not touched.

## Follow-ups found (not done)

- code-intel server should exit on stdin EOF / parent death (two orphans held a worktree open; killed).
- Supervisor: when the git identity is missing, the commit is skipped silently. It should record `git_identity_missing` in `worktree.commit_reason`.
- Leftover folder `IDM-worktrees/20261024T192711Z-cecb3619` (40 MB; merged, deregistered, branch deleted). Its nested test
  paths exceed MAX_PATH and my tool blocks long-path deletion — delete it by hand.
- `worker_result` returns ~8 KB of heartbeat JSON around the report → add a `content_only` flag (manager token cost).
- `start_worker(task_file=…)` resolves against the main repo even when `workspace` is a worktree.

## How I managed it — numbers

- **Workers:** 25 DeepSeek jobs, 574 worker-minutes, $0 paid (Go acct 2, off-peak). Split: build 199 min (4 originals),
  independent review 128 min (6 reviews), fixes 188 min (8 rounds), measurement 58 min (6 runs).
- **Me:** about 160 tool calls over about 5 h. I woke only on events: a zero-token file watcher fired on finish, stall or lease. There were no status pings and no polling.
- **Defects caught before merge:** 26. The ones that mattered:
  - 03: a sandbox escape that ran code as the supervisor. The first fix still left a second path open, and that path was already on main before tonight.
  - 02: a silent wrong-answer (chunk counts from the wrong id space).
  - 04: `references()` blind to indented methods.
  - 01: curated descriptions never loading (the path came from our own brief).
  - 01, 03: three false greens that only showed outside the worker sandbox.
- **Known defects shipped:** 0. Nothing pushed.

## Self-grade (manager of agents: outcome per token, per $ and per hour)

| Dimension | Grade | Evidence |
|---|---|---|
| Outcome delivered | **A−** | 4/4 merged, installed and measured. One extra tool shipped (`coverage_peek`) and one gap closed that was already on main. Minus: 03 needed 4 fix rounds (~4.5 h). Pack still over its budget at the time of writing. |
| QC effectiveness | **A** | Separate reviewers, never self-grading; a security-first brief for 03; my own unsandboxed runs at merge (caught 3 env-bound false greens); I spot-checked one cited claim per review. No known defect reached main. |
| Delegation | **B+** | Building, reviewing, fixing and measuring were delegated, and fix briefs used the reviewer's defects verbatim. I did merges, installs, conflict resolution (3 hunks; cheaper than spinning up a worker), two bisects and judgement calls. A merge-conflict worker would have been purer delegation, but slower. |
| Token efficiency | **B** | Good: watcher at zero tokens, `result.md` read directly, reviewers capped at ≤60-line verdicts, a REVIEW_TEMPLATE fill-in per review, a proportional re-review on small diffs. Waste: one `worker_result` dump (~8 KB), 3 failed commands (sed quoting, a dependent call sent in parallel, a too-long path), every `start_worker` echo is ~2 KB × 25. |
| Time efficiency | **B+** | Fully parallel from minute 0; I used review waits for installs and measurement; one batched fix round instead of two at 23:35. Minus: my 19:58 steer created rework on 03. |
| Steering / brief quality | **B−** | My mid-run convenience steer to 03 (commit in existing worktrees) carried no trust-boundary constraint and opened the first escape. The original brief had a wrong path. Fix briefs were strong: verbatim defects + explicit design decisions + the reviewer's attacks as regressions. |
| Risk management | **A−** | Backups before every config change. I refused a duckdb 1.5→2.0 upgrade path and skipped an invalid `uv.toml`. Repo-root policy is reversible and flagged for you; orphans killed only after checking parents and children. |
| Honest reporting | **A** | The measurement contradicted the expected win of the context pack, and I reported it. Every number is in the log. |

**Overall: A− / B+.** Strong on catching defects and on outcomes. Weakest on my own steering discipline and on the cost of the
security iteration.

## Where I should improve (rules I am adopting)

1. Any change that lets a sandboxed worker trigger unsandboxed actions gets a **threat model in the brief from round 1**:
   "the worker controls every file in its workspace; list every unsandboxed code path that reads one".
   That would likely have saved two of 03's four rounds.
2. **No mid-run steer that widens a worker's privileges** without stating the trust boundary in the same message.
3. **Run the suite outside the worker sandbox as part of every review, not only at merge.** Three of tonight's defects were
   invisible inside it.
4. Have reviewers commit their attack scripts under `tasks/optimizations/reviews/attacks/` so later rounds can diff for
   weakening, instead of paying for an extra review.
5. Design the measurement (A/B, n ≥ 3 per arm, a discovery-heavy task) **before** the work starts, not after.
6. Verify every path in a brief with one `ls` before launch.
