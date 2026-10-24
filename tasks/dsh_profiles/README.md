# Staged dsh profile changes (2026-10-24)

These are full copies of the two live profile patch layers. Claude installs them
after review by replacing `~/.dsh/profiles/<name>/cordis.patch.yml`; the current
file is backed up first (as with the earlier `*-20261024` backups).

- `headless.cordis.patch.yml` — copy of `~/.dsh/profiles/headless/cordis.patch.yml`
  plus the `pwsh-sandbox` row below.
- `web.cordis.patch.yml` — copy of `~/.dsh/profiles/web/cordis.patch.yml`
  plus the same row.

## Shell tool-call cap (staged)

`dsh-pwsh-local` / `dsh-pwsh-sandbox` expose `timeoutMs` (default 120,000 ms) and
`maxTimeoutMs` (default 600,000 ms, the ceiling for a per-call override).
`dsh-base` mounts `pwsh-sandbox` without config, so the live profile gets the
defaults. The staged row pins the requested 10-minute cap explicitly:

```yaml
- id: pwsh-sandbox
  name: "@deepseek-ai/dsh-pwsh-sandbox"
  config:
    timeoutMs: 600000
    maxTimeoutMs: 600000
```

Residual gap: `dsh-tool-pwsh` defaults to `promoteOnTimeout: true`, so a command
that reaches the 10-minute deadline is handed to a background job and the tool
call returns, but the process keeps running; a `run_in_background` call never
has a timeout. Setting `promoteOnTimeout: false` on `tool-pwsh` would kill the
command at the deadline instead. That changes a default and is left for review.
The staged row also raises the default foreground budget from 2 to 10 minutes;
if that is too long, drop `timeoutMs` and keep only `maxTimeoutMs: 600000`.

## Per-child wall-clock cap (no setting exists)

In dsh 0.2.1 (`dsh-subagent`, `dsh-subagent-spawn-in-process`,
`dsh-tool-subagent`, `dsh-base`) there is **no per-child wall-clock limit** and no
per-child timeout config:

- `dsh-subagent` host config has only `maxDepth` (default 1) and
  `maxActiveSubagents` (default 8).
- `dsh-tool-subagent` config has `provider`, `toolName`,
  `modelSelectionSettings`, `agentOptions`, `agentPreset`,
  `allowedAgentPresets`, `maxDepth`.
- `dsh-subagent-spawn-in-process` has no timeout setting; a start returns the
  child id immediately and the parent gets a completion notice later.

`dsh-tool-call-timeout-policy` only enforces a `timeoutMs` declared on a tool's
`ToolDefinition`; it is cooperative and cannot hard-stop a tool that ignores
cancellation. The shell executors declare their own per-call timeout (above);
the subagent start tool declares none.

Smallest alternative (already added to `AGENTS.md` §3): the parent must call
`interrupt_agent` on a child that has run over 15 minutes. `interrupt_agent`
works through the runtime and reaches a child stuck inside a tool call, unlike a
steering `send_message`.

## Validation

Staged `DSH_HOME` with both profiles copied (including `node_modules`):

```powershell
$env:DSH_HOME = "<staged home>"
dsh --profile headless --dump-config   # exit 0, no warnings
dsh --profile web --dump-config        # exit 0, no warnings
```

Both dumps show the `pwsh-sandbox` row with `timeoutMs: 600000` and
`maxTimeoutMs: 600000`.
