# Manager log — optimisation workers 01–04 (night of 2026-10-24/25)

Manager: Claude Code session. Workers: DeepSeek V4.1 Flash (dsh), Go acct 2, max effort.
Goal from Shivam: optimisations in place by morning; maximum delegation; manage at lowest token/cost/time.

## Operating playbook (what I commit to)

1. **Definition of done is the brief's "Acceptance checks".** I judge against those, nothing else.
2. **Event-driven, not polling.** A model-free watcher (`watch_jobs.py`, 60 s file reads, zero tokens) wakes me only
   on finish / stall >25 min / lease <20 min. No status pings (they can end a run).
3. **Tiered QA, cheapest first.**
   - L0 automatic: `merge_worker` runs the job's test_cmd and rolls back on failure; diff-stat + file-ownership check
     (01 and 03 split `plugins/dsh-worker/server/`); secrets grep.
   - L1 delegated: a fresh read-only-intent DeepSeek reviewer re-runs every acceptance check in the finished
     worktree and returns PASS/FAIL per check with the command and its output. The author never grades itself.
   - L2 me: read the reviewer verdict + the author's 5-point report, spot-check one claim with one command.
4. **Rework goes back with evidence.** Failed checks → one follow-up / fix worker whose brief is the failing checks
   verbatim. No vague "please improve".
5. **I do only what needs me:** merges, installs outside the sandbox, conflict calls, and the final measurement.
6. **Track the cost of managing**: wake-ups, my tool calls, interventions, rework rounds, defects found after merge.

## Timeline

| UTC | Event | Action | Cost to me |
|---|---|---|---|
| 19:27 | 01–04 started in worktrees (lease 2 h, digests 20 min) | — | 4 calls |
| 19:43 | Shivam hands over for the night | watcher started; acceptance checks extracted (not full briefs); REVIEW_TEMPLATE.md written so every review is a fill-in, not a fresh brief | 8 calls |
| 19:53 | 02 finished (25 min, ~99 tool calls, ~42 before first edit). Self-report: 21 tests OK, live smokes pass. Scope clean (12 files, all deliverables) | L0 scope check; reviewer `cf5504ae` started on 02's worktree | 7 calls (2 wasted: sed quoting, task_file resolves vs main repo) |
| 20:10 | Reviewer on 02: **FAIL** (16 min). AC3 fails (`--dry-run` needs `--dest`); 6 defects incl. a silent wrong-answer bug (`find_docs` chunk counts from the wrong id space) and a false-green in `mod_test`. Author's report had claimed all smokes pass — it used `--dest` itself, masking AC3. | L2 spot-check: read 2 cited lines, both confirmed. Fix worker `0a8cd96b` started with defects verbatim as its brief | 5 calls |
| 20:13 | 01 finished (46 min, 32 calls before first edit, ~95 total). Self-report: 81 tests OK (73+8), CONTEXT.md 20.1k tokens / 3.8 s, one "transient" suite failure. Scope respects 03's ownership (no supervisor.py). | Reviewer `0663e71c` started; told to run the suite 3× and probe the secret filter for over-dropping | 4 calls |
| 20:20 | 02 fixer done (10 min): all 6 defects fixed, each with a named test; 22 tests OK. Could not commit (worktree git index is outside the sandbox). | Proportional re-review: I re-ran the tests + the brief's exact AC3 command (2 cmds) instead of a 2nd reviewer. AC3 command now runs; my random AR said `missing` → checked Drive: present under a different crawl-date prefix (same hash). Not an AC failure → committed fixes, **merged 02 to main 8845232 (22/22)**, queued 02b (hash-suffix fallback) as its own worktree job `7d479a4e`. | 7 calls (1 wasted: a watcher started with `&` in a foreground shell never notifies) |
| 20:29 | 02b done (7 min): hash-suffix fallback, 26 tests, scope 3 files | Re-ran its live check myself (present, `hash_suffix`); small diff → no reviewer; **merged c909b44 (26/26)**; removed 02/02b worktrees | 5 calls |
| 20:30 | 04 finished (63 min). Self-report: 13 tests OK, acceptance script ALL PASSED; handshake 1.9–3.0 s vs AC2 < 2 s (author: SDK import floor); found+fixed a 600 MB node-child leak itself. 14 new files, 0 modified. | Reviewer `98fd2c20` with three pointed questions (measure the floor claim; tests ran vs skipped; kill-test for the leak). | 4 calls |
| 20:34 | 03 finished (67 min). Self-report: 88 tests OK; temp/pip/npx work in sandbox; write_scope data/full with confirm flags; first-edit metric live; baseline median **45** calls before first edit (21 jobs); both manager follow-ups folded in. But: `data` = dsh `danger-full-access` (dsh 0.2.1 has no extra writable roots), plus new WMI `launch_detached` and worker-commit request handlers. | Reviewer `1ea12c6b`, **security-first**: can a default-scope worker escape via the request handlers; commit only to own branch; confirm flags unbypassable; sitecustomize side effects; suite ×2. | 4 calls |
| 20:41 | Reviewer on 01: **PASS-WITH-NOTES** (28 min; suite 3/3 green, flake did not reproduce). 9 defects; #1 = curated table descriptions never load (wrong path) — **the wrong path came from our own brief**; #2 secret filter over-drops (my probe question found it). | Spot-checked #1 (1 cmd, confirmed). Fix worker `cac341d2` with the 9 defects verbatim, told the brief was wrong. | 4 calls (1 wasted: launched worker in parallel with the file-writing step it depended on) |
| 20:55 | Reviewer on 04: **PASS-WITH-NOTES** (24 min). Measured the floor claim: `import mcp.server` median 2.04 s, server 2.19 s → accept AC2 as floor-bound. 3 defects: `references()` returns 0 for indented methods (most of the codebase), cold-start `definition` flake, leaked handles. Kill-test: no leak. | Fix worker `561ef17e` (3 consecutive runs + ResourceWarning-as-error required). Used the wait to install basedpyright 1.40.2 in main Python (out-of-sandbox step from README). | 4 calls |
| 20:57 | Reviewer on 03: **FAIL — CRITICAL sandbox escape** (23 min). All 6 ACs pass, suite 88 ×2 green, but: a default-scope worker can rewrite `.git` so the unsandboxed supervisor's commit handler runs worker-owned hooks (PoC: hook executed; redirected commit moved another repo's HEAD). Plus HIGH: data scope accepts empty `writes`; MEDIUM: global mkdir patch unguarded. | Verified main repo untouched (`c909b44`, clean); read the handler (confirmed gitdir resolved at request time). Fix worker `cf67559c` with defects verbatim **plus explicit design decisions** (stored gitdir from job start, `--no-verify`, `core.hooksPath=NUL`, own-branch only, 3 regression tests). | 4 calls |
| 21:04 | 04 fixer done (8 min): 3 defects fixed, 16 tests ×3 runs, no ResourceWarnings. | Committed; **merged 34eae56** with `-W error::ResourceWarning` (16/16 ran, 0 skipped — basedpyright now installed). Installed code-intel at **project scope** (`.mcp.json` + `enabledMcpjsonServers`, backups `*.bak-20261025-code-intel`); skipped user scope (would double-register). acceptance_check in main: ALL PASSED (handshake 1.57 s). dsh profile insert deferred until 03 lands (03 ships full replacement profiles; one merged install). Worktree removed. | 6 calls |
| 21:08 | 01 fixer done (26 min): 9/9 defects with tests; 84 tests OK; curated descriptions 60/60 rows; 21.3k tokens. | Committed; first merge refused (`.mcp.json` dirty from my install — committed it as `2842652`); **merged 5414ef0 (84/84, 185 s)**; worktree removed. CONTEXT.md regeneration deferred until 03 lands (SANDBOX.md feeds it). Note: the running dsh-worker MCP server still has the old code — context packs start working after the app restart. | 5 calls |
| 21:32 | 03 security fixer done (34 min): 8/8 defects, 95 tests ×2, PoC "ALL POC EXPECTATIONS HELD". | Committed `158e04e`; merged main into the 03 branch first so the re-review sees what will land: 3 conflicts (core.py, plugin_server.py, README) — all independent additions, resolved as union by script (+1 missing space in concatenated literals). Integrated suites running; security **re-review** brief written with new attack variants (git filters/.gitattributes, worktree config, gpg/editor, junctions, request-field injection, launch refusal) + conflict-resolution check. | 6 calls |
| 21:44 | Integrated 03 suites, run by me **unsandboxed**: toolbelt 26 OK, code-intel 16 OK, dsh 106 → **2 failures**. Bisected on the pre-merge commit in a throwaway worktree: (1) auto-commit refused `git_workspace_moved` also on 158e04e → regression from the round-1 security fix, not my merge (fixer's "95 OK ×2" missed it — ran sandboxed); (2) bootstrap ACL test passes in a fresh dir, fails in the reused worktree → fragile assertion (matches the inherited integrity label). | Committed the resolved merge `07ea26d`; round-2 fixer `d0240da4` with both failures + "do not weaken the check" constraint. Scratch worktrees removed. | 7 calls (1 wasted: scratchpad path too long for git worktrees) |
| 22:04 | 03 round-2 fixer done (19 min): root cause = git output decoded as cp1252 (no `encoding=`) in my unsandboxed shell vs UTF-8 in the worker's (`PYTHONUTF8=1`) — explains why the worker never saw it; check not weakened; regression test runs with `PYTHONUTF8=0`; 107 OK ×3 incl. my mode. | Committed `4ac509b`; security re-reviewer `1e48a1bd` started on the final integrated head. | 3 calls |
| 22:29 | Security re-review of 03: **FAIL** (25 min). Round-1 commit path holds (PoC 6/6 blocked; request fields inert; launch refused for workspace scope), but NEW-1 CRITICAL: post-run *snapshot* still runs plain `git -C <workspace>` → a fake gitdir's `core.fsmonitor` executes as the supervisor (end-to-end repro). Checked: this snapshot path **is already on main** (pre-03) — every worktree job tonight was theoretically exposed. Also: filters/gpg not neutralised; `git add -A` follows junctions; and a repo-root (main-checkout) mutating worker can rewrite code the manager later runs unsandboxed (context-pack builder, supervisor.py, .git/config). | Round-3 fixer `5e5e35ab`: all git via stored identity + hardened runner; filters/gpg/editor/attributes inert; junctions refused; **policy decision (reversible): mutating repo-root workers need `confirm_repo_root_write=true`**; the reviewer's attack scripts are the regression suite. Moving plugin/runtime outside the checkout left to Shivam. | 4 calls |
| 22:31 | Measurement started early (doesn't need 03 merged: the first-edit metric can be recomputed from event logs). Installed code-intel insert into both live dsh profiles (backups `*.bak-20261025-code-intel`, YAML-parsed, `dsh --dump-config` shows it). Regenerated CONTEXT.md at 5414ef0 — **26.7k tokens, over the 25k budget** (repo map grew with toolbelt + code-intel; builder exits 1) → follow-up. A/B on the same small real task (S8 test-import collision): TREATMENT `6ce317e0` = brief + context pack header (01's own `attach_brief`) + tools note; CONTROL `fdaa1f6e` = bare brief. | 9 calls |
| 22:45 | A/B done (12 min each). Same scanner as the baseline (03's `EventScanner`, re-run on event logs). **TREATMENT: 8 calls before first edit / 28 total / 12.2k output tokens. CONTROL: 9 / 32 / 16.2k.** Baseline median: 45 before first edit. Treatment read CONTEXT.md first and used code-intel diagnostics; both fixes correct (1 file, 67 tests). | Committed regenerated pack `4e03f28`; **merged treatment 4546541** (67/67); control discarded; both worktrees removed. | 7 calls |

**Measurement reading (honest):** both arms are ~5× below the baseline, and they barely differ from each other. The
template-shaped brief (exact files, steps, numbered acceptance checks) — present in BOTH arms — explains most of the
drop on this task; the context pack + tools added ~10% fewer calls and ~25% fewer output tokens. n = 1 and the task
was small and precisely specified, which is exactly where a context pack helps least. The ≥50% target is met against
the baseline but cannot be attributed to the pack alone. A fair test of the pack needs a vaguer, data-touching task
(e.g. "find which table holds X and add a check"), 2–3 per arm.
| 22:48 | Second, fairer A/B: discovery-heavy data task (`coverage_peek` toolbelt tool: find which stores/tables hold a symbol's data and how they key it), **2 runs per arm** — TREATMENT `eabc5fa2`, `a0f6360e`; CONTROL `2ae5d9bb`, `ce940fed`. The pack auto-regenerated on build (header HEAD mismatch → stale, 01's fix working). Watcher gained `--all` (one wake for the whole batch). | 7 calls |
| 22:59 | Coverage A/B done (all 4 in 7–10 min). Before first edit / total / output tokens — **TREATMENT 25/41/39.4k and 42/78/37.1k; CONTROL 28/40/33.4k and 12/21/41.8k.** All four tools correct and mutually consistent on live DEEDEV data (9–10 stores, same counts), all pass every AC. | My first quality check ran without `REALITY_DATA_ROOT` and showed nothing — re-ran with it before judging (would have been a false FAIL ×4). **Merged the best: control `ce940fed` → 840eeac** (most complete: adds BSE announcements + XBRL facts; 31/31). Other three discarded, worktrees removed. | 6 calls |
| 23:28 | 03 round-3 fixer done (58 min): all git on worker workspaces through stored identity + hardened runner (`GIT_ATTR_SOURCE` empty tree on git 2.55, info/attributes drivers refused, gpg/editor/pager inert, global config off), junctions refused, `confirm_repo_root_write` policy; 114 tests ×3 incl. `PYTHONUTF8=0`; all prior attack scripts BLOCKED. Found + fixed a side effect itself (hardened commits lost CRLF/author settings). | Committed `f7b06e5`. The author edited the attack scripts and they are not in git → can't diff for weakening → **one more short independent review** (`d20b523f`) that must write its own attacks, incl. injection via the new author-identity replay. My unsandboxed suite run in parallel. | 5 calls |
| 23:35 | My unsandboxed run on `f7b06e5`: 114 tests, **1 fail, deterministic ×3 in isolation**: `test_context_pack_is_not_regenerated_while_a_repo_root_writer_runs` — "the manager executed the builder". Passed for the fixer (sandboxed). The real MCP server runs unsandboxed like me, so this is a real gap in the NEW-2 guard. | Holding it to batch with the final reviewer's findings (one fix round, not two). | 2 calls |
| 23:44 | Final independent review of 03: **PASS** (15 min) — own fresh attacks for all 5 classes BLOCKED, each with a live control proving the attack works against raw git; identity-replay injection (`user.name` with newline+`[core]`) dropped. One LOW: `.tmp` junction redirects request-result writes outside the workspace. | Round-4 fixer `ce690db0`: my unsandboxed guard failure + the LOW item. I will verify both myself (rerun the failing test in my shell + suite) rather than another review — small diff, and the decisive check is environmental. | 3 calls |
| 00:13 | Round-4 fixer done (29 min): root cause = pack attached *before* the repo-root lock was taken (sandbox masked it via inherited `PYTHONPATH`); guard now fails closed; `.tmp` reparse point refused. | Verified the formerly failing test + new junction test in **my** shell (OK); committed `14d6662`; **merged 03 → d6d1306, 116/116 unsandboxed**. All four optimisations now on main. | 4 calls |
| 00:20 | Installs: 03's profile rows (10-min pwsh cap, `promoteOnTimeout: false`) appended to live profiles that already carry code-intel (backups `*.bak-20261025-task03`; YAML + `--dump-config` verified). `pip.ini` → `%APPDATA%\pip` (timeout 120, retries 5). **Skipped `uv.toml`**: uv not installed and `[network] timeout` is not a known uv setting — would risk breaking uv later. `setup_worker_env.py`: checked first that it never upgrades (dry-run showed duckdb 1.5→2.0 available — a major upgrade could break DuckDB snapshots); real run = 0 installs. Regenerated pack: **30.1k tokens** (SANDBOX.md verbatim) → delegated trim to ≤ 20k (`79891139`). | 8 calls |
| 00:33 | Pack trim done (12 min): 25.2k → 16.3k (sandbox verbatim → 17-line digest, repo map halved, Tools section added; 60/60 curated tables kept). Worker corrected my brief: the builder never exited 1 (the "exit 1" I saw was my own heredoc error). **End-to-end proof of 03 on this live job:** `write_scope`, per-job `.tmp`, `tool_calls_before_first_edit=16` (orientation 256 s), progress note read from `<workspace>/.tmp` (S1 fixed). But **no auto-commit**: job created by the old in-memory MCP code (no stored git identity) + new supervisor on disk → fails closed, silently (commit fields empty, should say `git_identity_missing`). Expected until the app restart. | Committed by hand, **merged e1754e2 (53/53)**; regenerated pack **18.1k** → `0d61542`. 03 worktree: deregistered + branch deleted; folder (40 MB) left on disk because long-path deletion is blocked by the tool's safety rule — not worked around. | 9 calls |

**Measurement conclusion (2 tasks, 6 runs):** the brief template is the big, consistent win (baseline median 45 calls
before first edit → 8–12 on well-specified briefs). The context pack shows **no measurable benefit** on these samples
(discovery task: treatment mean 33.5 vs control mean 20; small task: 8 vs 9), while adding a ~27k-token read to every
worker. Variance between identical runs (12 vs 28; 25 vs 42) is larger than the treatment effect, so n=2 cannot prove
harm either. Recommendation: keep the template + brief lint as the default; make the pack opt-in (`context_pack=false`
default) or slim it to a 3–5k-token index (paths to schemas, rules, tools) and re-measure with ≥5 runs/arm on
discovery tasks. Toolbelt/code-intel usage was light in all runs; they help most when the brief names them.

**Lesson L5:** a worker's "tests pass" is environment-bound. Running the suite once more outside the worker's sandbox
(on the manager's side, at merge time) catches a class of failures the worker cannot see. Keep that step; it is cheap.

**Lesson L3 (manager-side, my error):** my 19:58 follow-up to 03 ("make commits work for workspaces pointed at existing
worktrees") is what added the worker-controlled gitdir lookup. I steered for convenience without a security constraint.
Rule: any steer that widens what the unsandboxed supervisor does on a worker's request must state the trust boundary.
**Lesson L4:** "all acceptance checks pass + all tests green" was true for 03 and it was still unmergeable. The
security-first framing of the review (attack the new handlers) is what found it; acceptance checks alone would not.

**Lesson L2 (manager-side):** a brief defect propagates to every worker that trusts it. Paths in briefs should be
verified by the brief writer (one `ls`) before launch. Counts against us, not the worker.

**Lesson L1:** the author's self-report was accurate on what it ran but chose inputs that hid the failing case; the
independent reviewer earned its cost on the first job (a silent data-correctness bug would have reached every worker).

## Systemic findings (feed into 01/03 or a follow-up)

- S1: Workers cannot append to `PROGRESS_NOTES.md` — supervisor puts it in `runtime/jobs/<id>/`, outside the
  worker's sandbox (02 reported it). The standing instruction is unfulfillable; notes should live in the workspace
  (e.g. `.tmp/PROGRESS_NOTES.md`) and the digest reader should look there. **19:55: sent to 03 as a scoped follow-up
  (its ownership area, one test, explicit fence around 01's brief assembly).** Delivered/steered.
- S2 (manager cost): `worker_result` returns ~8 KB of heartbeat/path JSON around a ~4 KB report. Reading `result.md`
  directly is cheaper; tool should get a `content_only` flag.
- S3: `start_worker(task_file=...)` resolves against the main repo even when `workspace` is a worktree.
- S4: A worker running in an existing worktree (not created by its own job) cannot `git add/commit`: the worktree's
  index lives in `<main>/.git/worktrees/<id>/`, outside the sandbox. 03's AC3 ("worktree demo job can git commit")
  must cover this case too — check in 03's review.
- S6 (compute waste, reported per standing rule): worktree removal of 04 failed because two orphaned
  `code-intel/server/server.py` python processes (4 MB each, started 19:50/19:59 UTC by the original 04 run, still
  held by their launcher pythons) kept files open. Killed both PIDs (36228, 208) after checking they had no node
  children (so the node-leak fix holds); removed the 93 MB leftover folder. Follow-up: the server should exit on stdin
  EOF / parent death.
- S7 (disk): 12 older dsh worktrees from 2026-10-24 remain under `IDM-worktrees/` (some hold paused work per
  `tasks/handoff/`). Not touched; listed for Shivam.
- S8: `plugins/dsh-worker/server/core.py` and `plugins/code-intel/server/core.py` are both imported as top-level
  `core`; running their test modules in one `unittest` process fails at import. Run suites per process for now;
  follow-up: package-qualify the imports (or give code-intel a distinct module name).
- S5: Crawl-date filename prefixes drift between DB, disk and Drive (same `<hash8>_<rest>`). Any path-keyed lookup
  will miss; 02b fixes it for drive_fetch.
