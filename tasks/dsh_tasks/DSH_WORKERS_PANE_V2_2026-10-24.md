# Task: redesign the "DeepSeek workers" pane (v2): denser, colourful, gradients

Owner: Shivam (2026-10-24, after seeing v1 live): "not visually appealing nor information dense; keep the layout like
yours [Claude's answers: compact tables, status marks, bold key numbers], using more colors and gradients".
Builder: you. Tester: Claude (loads it live in the desktop app).

## Starting point

v1 is merged at `plugins/dsh-workers-pane/` (register.tsx, rows.ts, tests, types). Same mod contract and docs as
before: `C:/Users/warri/AppData/Local/Temp/claude/bundled-skills/2.1.308/c21103d36fbfb01c1e250e8defb51a48/plugin-authoring/`
(`reference.md`, `examples/pane.tsx`, `types/claude-code.d.ts`). Shivam uses the **desktop** surface: its element
table has `Box, Text, Button, Input, Select, Svg, Link, Code, Markdown, Client`; `Box`/`Text` take `color` /
`backgroundColor` (`Color = ThemeKey | string`, so hex works), `borderStyle`; `Svg` can draw `linearGradient`
fills. Grep the types for `SvgProps`, `BoxProps`, `TextProps`, `ThemeKey` before designing. Keep a plain but
working terminal/mobile fallback (`e.surface` switch).

## What was wrong with v1 (from Shivam's screenshot)

- Each worker took 3–4 sparse lines; most of the pane was white space; everything was grey.
- `tc` was misleading: it counted tool calls in heartbeat's last-20-events window (15–18 for every job).
- Finished rows said "last 5h16 ago", which reads like a stall; data jobs and workers were mixed together.

## v2 design

1. **Header card** with a subtle gradient background: title, then coloured count chips (running green, stalled
   amber, failed red, finished-today blue), and a thin stacked gradient bar showing the mix.
2. **Sections**: "Running" (expanded), "Data jobs" (from jobs.yaml runs), "Finished today" (compact), older hidden
   behind a "show N older" Button.
3. **Running worker row = one dense card, 2 lines**:
   - line 1: phase chip (filled colour), short id (dim mono), title (bold, truncated), right side: elapsed.
   - line 2 as small metric pills: real tool-call total, model steps, output tokens (k), files written, last tool
     (e.g. `pwsh`), idle time (amber > 10 min, red > 20 min), and the controller-lease as a **gradient progress bar**
     (Svg: green→amber→red by fraction remaining, label "1h50 left").
   - a tiny activity sparkline (Svg) of events per minute over the last 30 min if the data allows.
4. **Finished row = one line**: outcome chip (✓ green / ✕ red / cancelled grey), id, title, duration, "ended 2h ago",
   branch chip if a worktree (and "merged" if the branch is merged into main, if cheap to know; else omit).
5. Colour palette defined once (tokens), readable on the dark theme; respect light theme via ThemeKey where possible.

## Data fixes

- Real totals: the dsh-worker MCP already computes `progress.events` (tool_calls, model_steps, output_tokens,
  recent_file_writes, last_tool) by scanning `<job>/result.md.events.jsonl` (see `plugins/dsh-worker/server/core.py`,
  search for `tool_calls_by_tool` / `model_steps`). Reproduce the same counts in the mod for **running** jobs only,
  reading the file incrementally (remember byte offset + counts in `$.state` keyed by job id, read only the new tail
  each tick); finished jobs: compute once and cache. Never re-read whole large files every 15 s.
- Finished: show end time, not "last activity". Data jobs: name from jobs.yaml run, exit code, duration.

## Checks

`claude plugin validate`, tsc (tsconfig outside the mod, as before), and tests via
`claude plugin test --file <test> <mod>` (the sandbox can't spawn the multi-file runner). Update/add tests: incremental
events counting (offset resume, partial last line), finished vs running rows, colour thresholds, lease bar fraction,
sections/ordering, terminal fallback renders. Build in this worktree at `plugins/dsh-workers-pane/`; Claude copies it
to the live mods folder.

## Final answer

What changed, a text sketch of the new layout, validate/tsc/test output, and anything the desktop surface could not
do (e.g. if Svg gradients are not supported, what you used instead).
