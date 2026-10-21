# Build a deterministic local Codex plugin for DeepSeek/dsh — 2026-10-21

You are DeepSeek V4.1 Flash, xhigh, acting as the implementation worker. Shivam has explicitly requested a real Codex plugin so Codex can start/check/message/read dsh workers through named tools with settings defined once, rather than repeatedly assembling PowerShell calls. Implement the plugin and meaningful tests; return a compact handoff. Codex reviews; you fix defects it finds. No further model delegation or inference calls from this worker.

## Context and authority

Read tasks/FRAMEWORK.md, tasks/STATE.md, tasks/codex_tasks/WORKING_PROTOCOL.md and tasks/codex_tasks/PROVIDER_PROBES_2026-10-21.md. Shivam -> Codex orchestrator/reviewer -> DeepSeek implementation. Off-peak DeepSeek project coding is approved. Go 2 is the default paid account; xhigh fixed, stable routing IDs, clock-based off-peak check. Peak: Mon-Fri 06:30-09:30 and 11:30-15:30 IST. Do not ask for timing. Do not expose keys or read auth/secret files. Laptop Sumit, Python 3.14, Node24, bun, dsh 0.2.1-rc.2, Codex CLI 0.163.0-alpha.10.2. Current repo HEAD c980314, many preserved uncommitted H01/Telegram/dsh wrapper changes. No commits, stashes, pushes, deletions or DB reads/writes.

The existing worker launcher is `reality_engine/scripts/run_deepseek_harness.py`. IMPORTANT: ANOTHER DeepSeek worker is currently replacing its hard timeout with heartbeat supervision from `tasks/codex_tasks/DSH_HEARTBEAT_TASK.md`. It owns that wrapper, `dsh_heartbeat*.py/.mjs`, heartbeat tests and `DSH_HEARTBEAT_IMPLEMENTATION.md`. Do not edit those files or interfere with its process. Your edits MUST be disjoint. The heartbeat worker's final interface may appear while you work. Integrate by reading its source/report after available, or state the exact pending integration seam rather than inventing an unsupported status/message format. Codex may send you an integration follow-up after the first worker completes.

The launcher already enforces xhigh, account choice, stable `go_session.session_id`, Node24 environment, paid consent flag, optional output caps and off-peak gating. Keep DeepSeek executing through this dsh launcher: no direct model API replacements, no community provider-switching bridge, no change to Codex's main model.

## Desired interface

Create a local desktop-only Codex plugin named `dsh-worker`, using Python MCP SDK (Codex is installing `mcp`; check availability). Prefer the SDK over handwritten MCP framing. It should expose a small deterministic interface such as:

- start_worker: accept a complete brief or a repo-local task file plus optional bounded settings; pin DeepSeek V4.1 Flash, xhigh, Go account2 by default, heartbeat interval900, missed replies2; reject invalid/outside-root paths and peak starts. A call returns promptly with job ID and status/result paths, not after the whole job.
- worker_status: read actual persisted process/heartbeat/session state; report unavailable/stale/dead/finished accurately, never confuse PID alone with progress. No inference call to ask whether a process is alive.
- message_worker: send a genuine follow-up/status nudge to the same running dsh worker using the heartbeat control adapter. Never pretend appending stdin works; never spawn a concurrent mutation of the same session. Fail explicitly if transport not available.
- worker_result: compact final answer, exit/outcome, artifacts and important limits; do not dump reasoning stderr or secrets.
- optional cancel_worker with explicit destructiveHint metadata and exact owned-process validation; no broad process-name kills.

Jobs need scoped persistent records under a gitignored repo-local runtime directory, unique IDs, per-job output/status paths, and a concurrency policy (default one mutating worker per workspace). Do not overwrite results or lose track of jobs when an MCP tool call returns. Make server shutdown semantics explicit; don't leave uncontrolled orphan writers. Avoid automatic paid retries. Any separate background process must be hidden on Windows and have robust ownership/provenance. Bound file reads and output sizes. Keep credentials in inherited environment/Windows-user env handling, never manifest/config files or command-line arguments.

The plugin should be useful beyond a single hardcoded smoke task. Its skill must teach Codex to supply full context, use the tools, review actual diffs/tests, send defects back to DeepSeek, preserve working files and avoid duplicate writers. Clarify that a stable provider cache session and actual dsh conversation ID are different identities. The shared launcher currently uses deterministic provider session IDs; don't reset them on each call.

## Official plugin format inspected by Codex

Fetched official docs (use these, not third-party installation payloads):
- https://developers.openai.com/plugins/build/plugins
- https://developers.openai.com/plugins/deploy/desktop-only
- https://learn.chatgpt.com/docs/extend/mcp?surface=cli

Supported compatibility layout: plugin root `.codex-plugin/plugin.json`, `.mcp.json`, `skills/<name>/SKILL.md`, plus bundled scripts/server. Manifest references `skills: "./skills/"`, `mcpServers: "./.mcp.json"`, `requires_local_executor: true`. Plugin-relative manifest paths start ./, no .. components. Local stdio MCP config can use `${PLUGIN_ROOT}` for launch path/cwd. Portable root plugin.json/mcp.json is also supported; choose one correct minimal layout rather than creating redundant contradictory manifests.

Local repo marketplace: `.agents/plugins/marketplace.json` with a stable displayName and a plugin source.path prefixed ./ relative to the documented marketplace root. Verify official schema/examples instead of guessing format. This file may already exist: inspect and preserve other entries. CLI `codex plugin marketplace ...` and `codex plugin add ...` exist; root Codex will perform actual registration after review. Do NOT edit ~/.codex/config.toml, ~/.agents, globals, install anything, or register the plugin yourself. Supply precise local install/test instructions and the runtime dependency declaration.

## Allowed edits

- New `plugins/dsh-worker/**` files only (if it exists, inspect before modifying).
- New `reality_engine/tests/test_dsh_worker_plugin.py` and isolated fixtures needed for those tests.
- `.agents/plugins/marketplace.json` only if necessary, preserving existing entries.
- New `tasks/codex_tasks/DSH_PLUGIN_IMPLEMENTATION.md`.

No edits to the heartbeat worker's owned files, STATE, AGENTS, FRAMEWORK, memories, other package manifests, DBs, user global settings or H01 code. No external publishing/uploading.

## Verification and delivery

Use fake launcher/control process integration so tests are deterministic, fast, offline and do not consume paid model tokens. Cover actual MCP initialize/list_tools/call_tool over stdio, start returning promptly, results preserved, status updates, wrong/stale session behavior, path traversal/outside-root rejection, default xhigh/off-peak enforcement, concurrency, result bounds and clean shutdown/owned cancellation. The message integration may need a second pass once the heartbeat adapter lands; do not mark it working without testing a real supported adapter.

Report changed files; test commands/results; manifest validation; startup/session/heartbeat integration; explicit pending pieces; exact registration/reload steps. Do not dump source or logs in the final answer. Codex will review, run its own checks and return defects to you.
