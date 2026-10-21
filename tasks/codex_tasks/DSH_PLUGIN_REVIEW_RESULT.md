# Reviewed and installed dsh-worker — 2026-10-21

DeepSeek implemented the plugin, heartbeat and fixes. Codex reviewed source, returned defects, ran independent checks, registered the catalog, installed the plugin and verified the installed backend. No Git push, Drive upload or antivirus exclusion was made.

## Outcome

- Installed and enabled: `dsh-worker@local-repo`, version `0.1.0`.
- Installed package: `C:/Users/warri/.codex/plugins/cache/local-repo/dsh-worker/0.1.0`.
- Editable source: `plugins/dsh-worker/`; local catalog `.agents/plugins/marketplace.json`.
- Six MCP tools: `start_worker`, `worker_status`, `message_worker`, `worker_result`, `cancel_worker`, `list_workers`.
- DeepSeek V4.1 Flash, xhigh, Go account 2, stable provider routing ID, off-peak start gate.
- Heartbeat default: 900 seconds idle, then a genuine same-agent status request; two complete unanswered response windows before stop. No default hard duration limit. Explicit troubleshooting timeout remains optional.
- Corrected worker-progress timestamps, repository-wide mutation lock including parent/subdirectory overlap, fail-closed Windows containment and lock retention, exact adapter-sized Unicode message validation, pinned Python runtime and correct tool annotations.

## Verification

Codex's independent initial combined run: 49 passed / 1 failed. The real-dsh test raced its fixed fake-model delay against the response window. Codex returned the failure to DeepSeek. DeepSeek changed ONLY the test fixture to wait for an actual delivered ping and use a bounded scheduling window, preserving functional assertions and production defaults.

- DeepSeek's final combined quiet suite: **50 tests passed**, 127.536 seconds; actual tool result reviewed.
- Codex independently reran the previously failing real-dsh test after the fix: **passed**, 13.018 seconds.
- Installed-package MCP initialize/list-tools/start/status/message/result live check: **passed**. Actual approved off-peak Go account 2 / xhigh job returned `DSH_PLUGIN_OK`, exit 0; two model steps/two assistant text messages, one final event, zero errors. A same-conversation nudge was queued and work continued. Containment explicitly reported `supervisor_and_worker`; hard timeout was null.
- Live audit: gitignored `reality_engine/data/logs/dsh_plugin_installed_smoke.json`; job `20261020T231343Z-5ad960ba` under repo-local plugin runtime. The first verification script asserted an obsolete containment label (`assigned`); corrected the check against the actual stronger label without another inference call. No implementation change was needed.
- CLI independently reports installed=true, enabled=true.

The correction worker's implementation/report were complete and reviewed; Codex stopped its remaining self-review process tree after ownership checks to freeze the approved source for installation. Its transport exit is therefore an interruption, not a claim of a graceful worker finish. The heartbeat fixture worker finished normally. All source, reports, status and logs were preserved.

## Usage and limits

Restart Codex once to load the newly installed plugin's tools into chat. This running chat's tool inventory did not hot-load them; the installed stdio backend was verified separately through the MCP SDK.

Supply a complete task file/context. Use explicit appropriate permissions for implementation; default is read-only. Codex reviews actual diffs and tests, returns off-peak fixes to DeepSeek, and never treats transport acknowledgement as a model response. Never start duplicate writers. Source remains uncommitted; no push authorized.

Control tokens are memory-only. After an MCP server restart, persisted status/results remain readable, but messaging an older running job requires the original server; otherwise the tool reports transport_unavailable. App/server shutdown can terminate its worker tree. Runtime records stay gitignored under the repository's `plugins/dsh-worker/runtime/` and survive plugin cache reinstalls.

Artifact hints enumerate newly dirty paths only; inspect full diffs for pre-existing dirty files. Current plugin config is bound to this laptop's repo and Python paths; update config if either moves. Raw event/reasoning logs are local evidence, not tool-result content.
