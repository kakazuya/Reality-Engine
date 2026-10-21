# Implement dsh worker heartbeat supervision — 2026-10-21

You are DeepSeek V4.1 Flash at xhigh through dsh. Shivam explicitly delegates off-peak implementation and fixes to you. Codex is your orchestrator/reviewer. This is an implementation task, not an advice-only response. Work in this repository, edit the allowed source files, run meaningful isolated tests, and return a compact final handoff describing the actual changes and checks. Do not delegate to another model.

## Authority and complete context

Read `tasks/FRAMEWORK.md`, global/repo AGENTS instructions, `tasks/STATE.md`, `tasks/codex_tasks/WORKING_PROTOCOL.md`, and `tasks/codex_tasks/PROVIDER_PROBES_2026-10-21.md`. Project is Reality Engine on the hometown laptop Sumit (Windows, PowerShell, Python 3.14, Node 24 under C:/Program Files/nodejs). Live data just restored; H01 is provisional and awaits fixes after this infrastructure change. Do not open or write project databases/snapshots. Many unrelated local changes/untracked H01/Telegram artifacts exist; preserve all of them. No commit, stash, push, package install, cleanup or deletion. No keys or auth file reads. Go account 2 is approved for this project coding task. Stable IDs and xhigh must remain intact. Do not invoke paid APIs or make live model calls yourself: Codex will handle any necessary live verification. No GPU or bulk filesystem/DB scans.

Current implementation: `reality_engine/scripts/run_deepseek_harness.py` starts dsh headless, buffers communicate(), and kills the process tree after --timeout (default 900 seconds). It has stable go_session IDs, xhigh defaults, optional output caps, optional local audit proxy for bounded smoke tests, Node24 PATH setup, and capped-run title suppression. Preserve these features. Existing checks are `reality_engine/tests/test_deepseek_harness_controls.py` (4 passed). Installed dsh is 0.2.1-rc.2 at `C:/Users/warri/.bun/bin/dsh.exe`; packages are under `C:/Users/warri/.bun/install/global/node_modules/@deepseek-ai/`.

## User request and interpretation

The existing 15-minute hard deadline must become a heartbeat. Long productive work must not be killed just because total runtime exceeds 15 minutes. After 15 minutes without meaningful worker activity, ask the SAME running worker for status and allow it to continue. Stop/report failure only after TWO consecutive status requests have each received no worker response. Use a well-defined response window and document the schedule. Reasonable default: idle 15m -> ping 1, wait 15m for a response -> ping 2, wait 15m -> stop if still silent. Any real worker activity/reply resets consecutive misses. No unconditional 15m/30m/45m runtime cutoff when work is progressing.

Installed headless reads its task from stdin once; stdin append is NOT a supported live conversation channel. Do not pretend that writing another line to stdin pings the model. Do not start a second worker concurrently against the same mutable session. Study native SDK/ACP/web control and choose a supported minimal solution, e.g. a per-invocation local Cordis plugin that queues a real follow-up on the same agent, with a strictly local control channel. You may create such a repo-local adapter file, loaded via temporary dsh config, if supported by this installed version. Research installed package READMEs/types/source, particularly dsh-headless, dsh-agent-loop, dsh-agent, dsh-session, dsh-llm, and Cordis loading. Avoid changing installed vendor packages.

Distinguish successful delivery/transport acknowledgement from an actual worker response. A control-server HTTP 200 saying "queued" by itself must not reset the unanswered-ping count. Model output, real tool activity/events, and actual status responses can establish worker activity. Track activity honestly. Do not count timer ticks, the supervisor's own ping logs, proxy acknowledgements or CPU usage alone as model responses. Queue status nudges for delivery at a valid model/tool boundary; don't cancel a productive reasoning call merely to demand status.

## Requirements

1. Default supervision: heartbeat mode, 900-second idle/check interval, two unanswered requests, no implicit wall-clock hard kill. Keep an explicitly requested optional hard timeout for troubleshooting/backward compatibility; clearly distinguish it from heartbeat configuration. Existing callers using `--timeout 100` for probes should still get an explicit hard timeout. Omission must no longer mean kill at 900.
2. Stream/drain stdout and stderr safely while running (avoid pipe deadlock); keep stdout final answer and log compatibility. Log useful start/progress/ping/reply/miss/end metadata and persist a small machine-readable status/session record for Codex monitoring. Do not print reasoning text to the Codex stdout; retain stderr in its existing local log. Track exact dsh conversation ID separately from provider routing/cache session ID; these are different identities.
3. Real same-agent status follow-up mechanism as above. Scope per-run control endpoint/mailbox safely to localhost, protect it from unrelated jobs, clean up listeners/processes on exit, and do not leave detached helpers. Preserve evidence and partial outputs on failed or interrupted runs. Don't silently claim success on truncation/error or confuse pid liveness with a response.
4. xhigh and stable provider IDs stay default; off-peak check remains. Preserve credentials via environment references only, no secrets in config/status/logs. Runtime environment remains Node24. Default implementation permission is chosen explicitly by Codex; do not broaden all worker permissions globally.
5. Meaningful tests with fake workers/clock/transport: healthy long run survives multiple intervals; actual same-worker ping and response reset misses; queued ack alone does not; two fully unanswered requests stop with clear failure; partial output preserved; stdout/stderr draining; explicit hard timeout; early process failure and clean completion; listener cleanup. No test should sleep 15 minutes or call external inference. Include a deterministic end-to-end local fake dsh/agent integration if practical, not only tests mirroring a counter implementation.
6. Document exact semantics, flags, status path, transport behavior, and limitations. If genuine mid-run messaging is impossible with this dsh build, report that clearly with evidence rather than implementing a fake ping. Prefer a supported local plugin/control mechanism to a large new bridge ecosystem.

## Allowed edits

- `reality_engine/scripts/run_deepseek_harness.py`
- New narrowly named `reality_engine/scripts/dsh_heartbeat*.py` / `dsh_heartbeat*.mjs` files if needed
- `reality_engine/tests/test_deepseek_harness_controls.py`
- New `reality_engine/tests/test_dsh_heartbeat*.py` files if needed
- New `tasks/codex_tasks/DSH_HEARTBEAT_IMPLEMENTATION.md` explaining the result

Do not edit STATE, FRAMEWORK, AGENTS, memories, unrelated sources or the H01 harness. Codex will update state after review. A baseline copy of current wrapper/tests is kept under gitignored `reality_engine/data/logs/dsh_heartbeat_bootstrap/` so the reviewer can distinguish your edits from earlier local modifications.

## Delivery

Implement and test. Return: files changed; actual ping transport; timer schedule; completed test commands/results; limitations; any blockers. If blocked by the installed SDK, say exactly what is missing. No unverified success claims. No full source dumps or secret/config dumps in the final answer.
