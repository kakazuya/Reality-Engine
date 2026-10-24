# Task: build a Claude Code mod — a "DeepSeek workers" pane beside the chat

Owner: Shivam (2026-10-24: make DeepSeek worker progress visual). Builder: you. Tester/reviewer: Claude.

## What the pane shows

One row per dsh-worker job, newest first, from `C:/Users/warri/Downloads/Info_Diffusion_Model/plugins/dsh-worker/runtime/jobs/<job_id>/`:
- `status.json` (job record: phase running/finished/failed/..., started_at, updated_at, finished_at, outcome,
  workspace, permission, worktree branch, controller lease deadline if present) and `job.json` (brief/task, kind),
- `heartbeat.json` (`state`, `last_worker_activity_at`, `activity_count`, recent `events`, `awaiting_input`),
- data jobs from the jobs.yaml runner live in the same folder layout (`name` field; stdout.log/stderr.log).
Open each file read-only and tolerate missing/partial JSON (a job mid-write): show "unreadable", never crash.

Columns (compact, readable at ~40 characters wide): short job id (last 8 chars) + task title (first line of the
brief/task file name), phase with a coloured marker (running green, stalled amber when last activity > 20 min,
finished grey, failed red), elapsed time, "last activity N min ago", tool-call count (from heartbeat/events if
available), lease countdown (time until the controller-lease deadline; red under 15 min), worktree branch if any.
Show running/stalled first, then the 8 most recent finished. A header line with counts (running / stalled / finished
today). Refresh on a timer (every 15 s) and on pane open; no network, no writes, no process control from the pane
(read-only view; steering stays with Claude via the dsh-worker MCP).

Also add a slash command `/dsh-workers` that opens the pane, and a status-line entry like `dsh: 2 running, 1 stalled`.

## How mods work here (read these first — exact contract for this Claude Code build)

- Skill doc folder (read-only for you): `C:/Users/warri/AppData/Local/Temp/claude/bundled-skills/2.1.308/c21103d36fbfb01c1e250e8defb51a48/plugin-authoring/`
  - `reference.md` — full API: events, `ui.render` in depth, `$.state` contracts, `$.clock` timers, `$.fs` file reads,
    `$.command`, testing.
  - `examples/pane.tsx` + `examples/pane-state.d.ts` + `examples/pane.test.tsx` — a complete pane mod: copy its shape.
  - `types/claude-code.d.ts` — the API types (~14k lines; grep for `Pane: {`, `'ui.render'`, `$.fs`, `$.clock`).
- A mod is three/four files:
  - `.claude-plugin/plugin.json`: `{ "name": "dsh-workers", "version": "0.1.0", "description": "...", "types": "./types/index.d.ts" }`
  - `hooks/hooks.json`: `{ "modules": ["./register.tsx"] }`
  - `hooks/register.tsx`: `export const register: Register = (on, options) => { ... }` (type from `'claude-code'`).
    Pane: `$.ui.open({ id, title })` drawn by a `ui.render` hook on `{ component: 'Pane', requestId: id }`. Elements
    come from `$.ui.resolve(e)` (`Box`, `Text`, ...), JSX against global `h`. No DOM, no Node: all IO through `$`.
  - `types/index.d.ts`: declares every `$.state` value under `interface PluginState` for this mod.
- Check it: `claude plugin validate <mod folder>`, type-check with `tsc` using the tsconfig from the types file header
  (keep that tsconfig outside the mod folder), tests with `claude plugin test <mod folder>` (write `hooks/*.test.tsx`
  covering: row building from fixture status/heartbeat JSON, stalled detection, lease countdown colouring, missing or
  corrupt JSON, ordering). Use fixture files, not the live runtime folder, in tests.

## Where to build

Your sandbox is this git worktree. Build the mod at `plugins/dsh-workers-pane/` (that folder is the mod folder:
`.claude-plugin/`, `hooks/`, `types/`). The runtime path to read should come from a `userConfig` option or a constant
with that default path. Claude will copy the folder into the session's mods folder to load and test it live.

## Final answer

File list, how rows are computed (field by field), validate/tsc/test output, a text sketch of the pane with sample
rows, and anything in the API you were unsure about.
