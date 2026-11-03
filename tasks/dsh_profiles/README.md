# dsh profile patches

The live profiles are `~/.dsh/profiles/headless/cordis.patch.yml` and `~/.dsh/profiles/web/cordis.patch.yml`. Workers cannot write them; Claude changes them, backing up first and then checking `dsh --profile <name> --dump-config`.

The copies here, `headless.cordis.patch.yml` and `web.cordis.patch.yml`, are the 24 Oct versions and have drifted: on 2 Nov the live files differed from them. The live files are the authority. `code-tools.insert.yml` is the row that adds the run-and-exit `outline`/`typecheck` tools (`plugins/code-tools/README.md`); it replaces the `mcp-code-intel` row, which was retired on 4 Nov 2026 (T-054).

## Shell tool-call cap

`dsh-pwsh-local` / `dsh-pwsh-sandbox` expose `timeoutMs` (default 120,000 ms) and `maxTimeoutMs` (default 600,000 ms, the ceiling for a per-call override). Both live profiles pin them and turn promotion off (checked 2 Nov), so a command that reaches the 10-minute deadline is killed, not handed to a background job:

```yaml
- id: pwsh-sandbox
  name: "@deepseek-ai/dsh-pwsh-sandbox"
  config:
    timeoutMs: 600000
    maxTimeoutMs: 600000
- id: tool-pwsh
  name: "@deepseek-ai/dsh-tool-pwsh"
  config:
    promoteOnTimeout: false
```

A `run_in_background` call never has a timeout. A worker that needs a process to outlive its shell uses the supervisor's `.tmp/launch.request.json` path (`write_scope` data or full; `tasks/worker_context/SANDBOX.md`).

## Per-child wall-clock cap: no setting exists

In dsh 0.2.1 (`dsh-subagent`, `dsh-subagent-spawn-in-process`, `dsh-tool-subagent`, `dsh-base`) there is no per-child wall-clock limit:

- `dsh-subagent` host config has only `maxDepth` (default 1) and `maxActiveSubagents` (default 8).
- `dsh-tool-subagent` config has `provider`, `toolName`, `modelSelectionSettings`, `agentOptions`, `agentPreset`, `allowedAgentPresets`, `maxDepth`.
- `dsh-subagent-spawn-in-process` has no timeout setting; a start returns the child id immediately and the parent gets a completion notice later.

`dsh-tool-call-timeout-policy` only enforces a `timeoutMs` declared on a tool's `ToolDefinition`; it is cooperative and cannot hard-stop a tool that ignores cancellation. The subagent start tool declares none. So the parent must call `interrupt_agent` on a child that has run over 15 minutes; it reaches a child stuck inside a tool call, unlike a steering `send_message`.
