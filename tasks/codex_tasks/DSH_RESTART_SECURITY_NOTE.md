# Restart instructions after Bitdefender interruption — 2026-10-21

Shivam explicitly requested continuing the plugin build. Both earlier worker trees were stopped. No heartbeat/plugin source was delivered. Read your original task brief, then implement; do not repeat a long research-only pass. Prior worker reasoning logs are local evidence, not verified results:
- `reality_engine/data/logs/dsh_heartbeat_bootstrap/worker_result.md.log`
- `reality_engine/data/logs/dsh_plugin_bootstrap/worker_result.md.log`

Bitdefender blocked a long inline PowerShell payload writing a fake Node SSE server to TEMP and starting it hidden. Do not repeat that command or try another interpreter/encoding to evade the block. Do not alter security settings or request exclusions. The user said they could add an exclusion if needed; Codex has not added any.

Write ordinary, reviewable source/test files inside your allowed repository paths. Use short normal commands such as `python -m unittest ...` or a direct Node test-file invocation. Integration test servers should be in-process Python threads where possible, or normal owned subprocess fixtures with reliable cleanup. Do not put huge source here-strings in shell commands. Do not create new executable test scripts in TEMP. Python TemporaryDirectory for fixture data is fine. If antivirus blocks a revised command, stop that test, record exact evidence, and report; do not retry around it.

Prior installed-source research established:
- dsh custom local Cordis plugins can load with a `file:///...mjs` name in an `insert` patch and export `name`/`apply`.
- `dsh-agent` exposes ctx.agents and live agent `.steer()` / `.followup()`; inspect only exact needed signatures.
- Headless task stdin is one-shot. Genuine control requires the local plugin adapter; never fake messages by stdin append.
- MCP Python 2.3.0 is installed.
- Source scripts are still the pre-heartbeat baseline. Other worker edits are disjoint as specified in the original briefs.

Implement actual files early, then tests. Do not spend the whole turn planning the full design in prose. Keep the design minimal, reliable, and honest about unsupported behavior. No paid inference inside your tests. Return a compact report with actual completed checks.
