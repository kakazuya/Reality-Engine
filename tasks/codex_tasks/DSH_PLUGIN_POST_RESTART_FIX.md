# Post-restart plugin packaging fix — 21 October 2026

Shivam asks Codex to check the complete dsh-worker MCP and ensure no orphan API spend before sleep. H01 is postponed until tomorrow. You implement; Codex reviews. Read AGENTS.md, tasks/FRAMEWORK.md and relevant plugin source. Keep scope narrow. Do not edit databases, unrelated code, secrets, security settings, push or upload. Do not launch other model workers or live paid probes.

Confirmed defect: plugin installed/enabled and skill loaded, but MCP tools absent in this chat. `codex mcp list --json` resolves dsh-worker cwd to `C:\Users\warri\.codex\plugins\cache\local-repo\dsh-worker\0.1.0\${PLUGIN_ROOT}` and leaves arg `${PLUGIN_ROOT}/server/dsh_worker_mcp.py` literal. Earlier SDK smoke manually expanded placeholder and therefore missed this real integration defect.

Fix plugin .mcp.json startup using supported Codex semantics (relative cwd `.` and relative script path if those resolve correctly, or this laptop's explicit source paths if necessary). Verify actual resolved `codex mcp list --json` transport, then initialize real MCP directly using EXACT resolved command/args/cwd/env without replacing placeholders yourself. List six tools and list existing workers/status/results, making zero model calls. Add a focused regression that rejects unsupported unresolved startup placeholders. Do not reinstall/cache-copy yourself; Codex will review then install/copy verified package.

Review shutdown semantics briefly: supervisor intentionally detached, host may kill its tree; Windows job object kills worker when supervisor dies. Do not claim server EOF alone always stops supervisor. Existing test server_shutdown tests SDK host tree shutdown. If a real money-wasting orphan flaw is found, report precise evidence and smallest fix; don't broaden into refactor. No active production workers existed at audit start.

Run only focused relevant checks, write concise report tasks/codex_tasks/DSH_PLUGIN_POST_RESTART_FIX_RESULT.md with exact changed files/resolved config/test output and remaining restart limitation. Finish promptly after evidence; no repeated self-review.
