# dsh-worker MCP stress pass — 2026-10-22 (01:44–02:30 IST)

Branch `claude/dsh-mcp-hardening-22ffa5` (worktree). Nothing was installed over the
live server, `~/.claude.json` was only read, and the live H02 run
(`dsh-20261022T010730-dea93bc4`) and its files were not touched. No paid DeepSeek
call was made (see "Not done"). Every case ran against the fake launcher fixture,
temporary repositories whose path contains a space and a Devanagari letter, and
processes this pass started itself.

Probe scripts: a pre-fix probe recorded the "observed" column below; the same probe
was re-run after the fixes. The regression tests are in
`reality_engine/tests/test_dsh_worker_stress.py` (24 tests).

## Incidents from tonight

| # | Incident | Finding | Fix |
|---|---|---|---|
| 1 | Server "removed from the configuration" twice | The server process does not depend on cwd: it is launched with absolute paths and an absolute `DSH_WORKER_REPO_ROOT`, and a test starts it from inside a `runtime/jobs/<dir>` cwd and it works. `~/.claude.json` now has the user-scope entry; no project or local entry exists for a `runtime/jobs` path, so the "cwd moved" cause is **plausible but not proven** from config evidence. A bigger problem turned up instead: **when the host closes the server, the host's job object kills the supervisor and worker too**, so a vanished server took every running MCP job down, with no final status. Breakaway from that job is refused under both Claude Desktop and the Python MCP client (`WinError 5`, tested from this session). | User-scope registration documented (README). A relative `DSH_WORKER_REPO_ROOT` is now refused (`repo_root_relative`). The supervisor is spawned with `CREATE_BREAKAWAY_FROM_JOB` when the host allows it, falling back otherwise. The start response reports `survives_server_exit`, with a warning when it is false. A restarted server can take over a still-valid lease with `renew_worker_lease(adopt=true)`. New `server_info` tool answers "is it up, which process". |
| 2 | Almost no progress signal; non-empty `result.md` looked finished | `result_ready` was `result_bytes > 0`, so it was true while running (observed: `running, result_ready=true`). | `result_ready` now means final and non-empty. Added `result_is_streaming`, `result_final`, and a `progress` block: `done`, `succeeded`, `answer_empty`, elapsed time, seconds since activity, last activity kind, `events` (tool calls by tool, failed tool results, model steps, output tokens, last tool + target, last 10 files written), lease time left, `latest_finish_by` (hard upper bound), `eta: null` (dsh gives none, so nothing is invented), and a one-line `summary`. `list_workers` rows carry the summary. |
| 3 | Raw-harness worker unreachable | Messaging is impossible by design: the harness keeps the control token in memory (or in an env var the server never sees). | New read-only `inspect_run(out_file)` gives the same progress view from `<out>.status.json` + `.events.jsonl`. It checks the dsh PID against its creation time versus the run start, so a recycled PID shows as `pid_reused`. Verified on a real past run (`dsh_heartbeat_flake_fix`: "done: finished; elapsed 10m; 31 tool calls, 28 model steps; last tool pwsh ..."). |

## Edge-case table

Each row says what was done, what was expected, what was observed before the fix,
whether it was fixed and how, and the retest result. A "Retest" entry that names a
test lives in `test_dsh_worker_stress.py` unless it says otherwise.

| Case | What I did | Expected | Observed (pre-fix) | Fixed? / how | Retest |
|---|---|---|---|---|---|
| Missing args | `worker_status {}` over MCP | structured error | MCP validation error | n/a | `test_server_from_foreign_cwd...` pass |
| Wrong arg type | `missed_replies="two"` | refused | MCP validation error | n/a | same test, pass |
| brief and task_file both / neither | over MCP | `brief_required` | correct | n/a | pass |
| Huge brief | 262 145 bytes | `brief_too_large` | correct | n/a | pass |
| Unicode/Hindi brief | Devanagari + CJK + ✓ | stored byte-exact | correct | n/a | pass (brief.md compared) |
| Paths with spaces / Devanagari | repo root `dsh stress ू xxx` | works | worked | n/a | whole stress suite runs there |
| task_file outside repo | `AGENTS.md` of the real repo | refused | `task_file_outside_repo` | n/a | probe + existing `test_peak_and_path_validation` |
| job_id traversal | `..\..\x`, a harness run id | refused | `job_id_invalid` | n/a | `test_cancel_variants` |
| Non-integer PID/ticks in status.json | `"supervisor_pid": "abc"`, `5.5`, `true` | degraded answer | **ValueError → `internal_error`** | `_as_pid` coercion; invalid fields → phase `unknown` and `record_invalid_fields`; the lock code fails closed | `test_non_integer_pid_fields...` |
| One corrupt job in list_workers | as above, plus `job.json` = `[1,2]` | other jobs still listed | **whole list failed** | per-entry catch; `unreadable` list | same test |
| start_failed record with no workspace | `list_workers(workspace=".")` | listed or skipped | **TypeError** | guarded filter; start_failed → `failed/start_failed` | `test_start_failed_record...` |
| status.json briefly unreadable (AV/indexer lock, garbled read) on a live job | patched reader returns invalid | not final | **phase `lost`, final=true, failed=true** | retry 4× with backoff, then phase `unknown` (not final, never "lost") | `test_transiently_unreadable_status...` |
| Partial status.json | — | — | not reachable: every write is tmp + `os.replace` | n/a | existing atomic-write tests |
| status write fails (full disk / lock > 50 retries) in supervisor loop | `atomic_write_json` raises | worker keeps running | **exception reached the generic handler, which killed the worker** | `_write_status_soft` (log and retry next poll); final status retried for up to 30 s | `test_supervisor_status_write_failure_is_not_fatal` |
| Read-only job finishing | fast read-only job | no lock warning | **false "repository mutation lock retained" warning on every read-only job** | supervisor `_release_lock` returns True when the lock is not held by this job | `test_read_only_job_has_no_false_lock_retained_warning` |
| Empty model answer | exit 0, empty result | flagged | `finished/completed`, no signal beyond `result_ready=false` | `progress.answer_empty`, warning, summary "with an EMPTY answer" | `test_empty_answer_is_flagged` |
| Launcher failure cause (missing key, missing dsh, peak refusal, provider timeout, HTTP 502) | fake launcher prints the real harness messages, exit 1 | cause visible | **generic "launcher exited nonzero"** | `failure_reason`: exit code, heartbeat failure, last stderr lines (reasoning lines dropped, ≥32-char tokens redacted), `likely_cause` | `test_failure_reason_surfaces...` (5 subcases, also checks that no reasoning text or token leaks) |
| dsh binary missing | `DSH_WORKER_PREFLIGHT=1`, bad path | refuse before launch | job launched, then failed | pre-flight → `dsh_missing` (real launcher only) | `test_preflight_refuses...` |
| API key env missing | key popped | refuse before launch, value never shown | job launched, then failed | pre-flight → `api_key_missing` (presence only: process env, then HKCU/HKLM Environment) | same test |
| Peak boundaries 06:30/09:30/11:30/15:30, ±1 s, weekend, UTC input | `is_peak` table, 13 stamps | per policy | all correct | n/a | `test_peak_boundaries...` |
| Start seconds before peak | 06:28:30 IST | refuse | **accepted; the harness then refuses on the real clock → opaque failure** | `peak_hours_imminent` within 120 s of a window | `test_start_refused_just_before_peak_window` |
| Concurrent mutating starts | 4 managers, barrier, `workspace-write` | exactly one | one started, three `workspace_busy` | n/a | `test_concurrent_mutating_starts...` |
| Read-only alongside mutating | while the writer runs | allowed, with warning | allowed, with warning | n/a (policy) | same test |
| Lock released after writer finishes | new writer | starts | starts | n/a | same test |
| Lease expiry | 2 s test lease, 30 s job | stopped, `controller_lease_expired` | correct | n/a | `test_expired_lease_cannot_be_adopted` + existing tests |
| Lease renewal limits | existing tests (max 1800 s, owner-bound) | — | correct | n/a | `test_dsh_worker_plugin` |
| Server restarted mid-job: renew | new Manager | some explicit path | **impossible: job always died at deadline** | `renew_worker_lease(adopt=true)`; an expired lease cannot be adopted; `adoptions` recorded | `test_restarted_server_adopts_lease_explicitly` |
| Server restarted mid-job: message | new Manager | explicit refusal | `transport_unavailable` | n/a (token stays memory-only by security decision) | same test |
| Server killed while job runs | close the Python MCP client session | job survives or the loss is reported | worker died silently | breakaway attempt + `survives_server_exit` and warning (here false: the host refuses breakaway) | `test_server_exit_while_job_runs_is_reported` |
| Supervisor killed alone | `taskkill /PID sup /F` (no /T) | worker dies, lock held | worker dies (job object), phase `lost`, lock held | n/a | `test_supervisor_killed_alone...` (also checks that cancel releases the lock and a new writer starts) |
| Worker killed alone | kill worker tree | failed, with reason | `failed/launcher_error` | now also carries `failure_reason` | `test_worker_killed_alone_fails_with_reason` |
| PID reuse | live PID with a wrong creation time | not alive | not alive → `lost` | n/a | `test_pid_reuse_is_not_reported_alive` |
| Cancel without confirm | — | refused | `confirmation_required` | n/a | `test_cancel_variants` |
| Cancel finished / unknown / foreign job | — | idempotent / not found | correct | n/a | same test |
| message_worker over 4000 chars | 4001 Devanagari chars (UTF-16 count) | `message_too_long`, nothing sent | correct | n/a | MCP test |
| Follow-up with no wait | `kind=followup`, `followup_wait_seconds=0` | steered or refused clearly | correct | n/a | existing `test_message_route_selection...` |
| worker_result cut mid UTF-8 character | 400 × "न", cap 257 | no U+FFFD | **ended in U+FFFD** | trim the incomplete trailing sequence | `test_utf8_result_truncation...` |
| stdout / event flood | 20 MB events.jsonl | status stays fast | (scanner is new) | scanner reads at most 8 MB per call, keeps its offset, consumes only complete lines, rescans a replaced file | `test_event_scanner_incremental...` (<5 s first call; catches up later) |
| Real event stream | 832 KB real events from 21-Oct | sane counts | — | — | 0.02 s; 213 tool calls, 204 steps, 10 recent writes |
| Relative repo root from a foreign cwd | `DSH_WORKER_REPO_ROOT=.` | refused | misleading `repo_root_invalid` | `repo_root_relative` | `test_relative_repo_root_is_rejected` |
| Server launched from a job dir cwd | MCP stdio with `cwd=runtime/jobs/some job dir` | works | works | n/a | `test_server_from_foreign_cwd...` |

## Test results

- `test_dsh_worker_plugin` (24, two assertions updated for the new `result_ready`
  meaning and two new tools) and `test_dsh_worker_stress` (24): **all pass**.
- `test_dsh_heartbeat` + `test_deepseek_harness_controls` (unchanged code):
  pass. The four modules together ran 84 tests, OK.
- Full `unittest discover`: see the commit message / bottom of this file.

## Install (after H02 finishes — not done here)

Merge the branch into the main checkout. The user-scope registration already
points at the main checkout's `server/dsh_worker_mcp.py`, so the next server
start picks it up. Then restart the session (or `/mcp` reconnect) and call
`server_info`; it should report `version: 0.2.0`. No `~/.claude.json` edit is
needed. Codex's server (PID seen tonight under `codex.exe`) also needs a restart.

## Live smoke (Fri 2026-10-23 23:39 IST, off-peak, Shivam approved; H02 had completed)

Two tiny real calls through this branch's `Manager` (deepseek-v4.1-flash, max
effort, Go account 2, read-only, `refresh_context=False`):

| Brief | Result | progress.summary at the end |
|---|---|---|
| "Reply with exactly: OK" | finished in 8 s, answer `OK` | `done: finished; elapsed 8s; 0 tool calls, 1 model steps` |
| read the first line of AGENTS.md | finished in 10 s, correct line | `done: finished; elapsed 10s; 1 tool calls, 2 model steps; last tool read on AGENTS.md` |

While the jobs ran, the summary showed `running ... result.md 0 B so far
(streaming, not final); hard stop by ... (controller_lease_deadline)`. `server_info`
reported version 0.2.0 with the heartbeat and control-token contract.
`survives_server_exit=false`, as expected under Claude Desktop. Item 5 of "Left
unfixed" is now done.

## Left unfixed, and why

1. **Survival when the host closes the server.** Claude Desktop and the Python
   MCP client refuse job breakaway, so the supervisor still dies with the
   server tree there. The only ways around this, such as launching through
   WMI or Task Scheduler, are job-object escapes that look like evasion to
   Bitdefender and change security posture. That is Shivam's call. The loss is
   now reported (`survives_server_exit=false` plus a warning) instead of silent.
2. **Messaging after a restart, or a raw-harness run.** The control token is
   memory-only by an earlier security decision (`DSH_RESTART_SECURITY_NOTE.md`
   context). Persisting it would reverse that. `inspect_run` covers visibility.
3. **No real ETA.** dsh publishes no completion estimate. `latest_finish_by` is
   the honest upper bound; `eta` stays null.
4. **Incident 1 cause** is not proven: no config evidence ties it to the cwd.
   User-scope registration removes the dependency either way.
5. **Live smoke not run.** It is off-peak, but a paid call on account 2 would
   share the stable provider session with the running H02 job. Run one tiny
   smoke after H02 ends, e.g. `start_worker(brief="Reply with OK only.")` then
   `worker_status` until `progress.done`.
6. `stdout.log`/`stderr.log` from the launcher are unbounded. The harness
   prints only one line, so this is low risk; dsh's own stream goes to
   `events.jsonl`, which the scanner bounds.
7. The worker ignoring "write progress every 15 min" is model behaviour; the
   event-derived progress makes it unnecessary.
