# Post-restart dsh-worker audit — 21 October 2026, about 05:08 IST

H01 is postponed until tomorrow, as Shivam requested. No backtest launched.

Found and fixed a packaging defect: `${PLUGIN_ROOT}` was not expanded by the actual Codex MCP loader. The skill loaded, but the server cwd pointed at a nonexistent literal placeholder directory. The previous SDK smoke manually expanded the placeholder and missed this integration issue. Codex's initial claim that the restarted chat had loaded the full plugin was premature and corrected during the audit.

DeepSeek through dsh/xhigh/Go2 implemented the narrow manifest fix (`cwd: .`, script `server/dsh_worker_mcp.py`) and added an unresolved-placeholder regression. Codex reviewed, reinstalled with `codex plugin add dsh-worker@local-repo --json`, and independently tested the exact transport returned by `codex mcp list --json`, with no manual placeholder replacement. Connection, six-tool discovery, persisted list/status/result reads and validation refusals passed. The installed backend works. This already-running chat still lacks native MCP tools; reload/restart is required to build its tool catalog from the corrected startup configuration. Native chat tool exposure must be confirmed next time, not assumed from backend success.

Evidence:
- Existing offline plugin suite: 19 tests passed, 58.987 seconds. Includes real MCP/fake launcher cancellation, host shutdown process cleanup, locks, ownership, messages and result bounds. Zero model calls.
- Independent post-fix manifest/layout and new placeholder regression: 2 passed, 0.048 seconds. No worker behavior changed.
- Exact installed transport audit: `reality_engine/data/logs/dsh_plugin_overnight_audit.json`; all six tools exposed by installed server. Existing production job `20261020T231343Z-5ad960ba` finished, result readable, both recorded supervisor and worker dead. Blank/invalid start/message/cancel rejected without inference.
- One approved implementation worker was launched for the discovered packaging fix, stable provider session, xhigh. After actual source changes and independent verification, Codex terminated its verified dsh PID 29392/tree to stop further self-review/API use. Wrapper exit 1 records deliberate reviewer termination, not a graceful worker completion. It had run about 620 seconds. No additional paid probe was made.
- Final OS process scan found no matching dsh/launcher/plugin supervisor/model processes. No production workers were active at audit start either.

Lifecycle limit: do not promise that simply closing a chat cancels every detached supervisor. Host process-tree shutdown is tested, and supervisor death closes its Windows job object and kills its worker; a surviving detached supervisor can continue authorized work. Persisted jobs remain visible. Explicit cancellation plus PID/creation-time inspection is the operational cleanup path. Memory-only control tokens do not survive an MCP-server restart, so an older running job may be inspectable/cancellable but no longer messageable from the new server.

No overnight jobs left running. No source-data downloads, H01, push/upload, credentials changes or antivirus changes. The corrected server does not call a model merely by starting, listing jobs, inspecting status or reading results.
