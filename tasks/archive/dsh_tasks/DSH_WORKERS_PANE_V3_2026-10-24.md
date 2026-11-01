# Task: DeepSeek workers pane v3 — colours, persistence, hide when idle, mobile fallback

Owner: Shivam (2026-10-24). Builder: you. Tester/installer: Claude.

Mod source: `plugins/dsh-workers-pane/` (v2, merged). Mod docs/types:
`C:/Users/warri/AppData/Local/Temp/claude/bundled-skills/2.1.308/c21103d36fbfb01c1e250e8defb51a48/plugin-authoring/`
(`reference.md` — read the sections on `--plugin-dir`, `CLAUDE_CODE_PLUGIN_DIRS`, sharing/installing a mod,
`$.store`, `session.start`, `AbovePrompt`, `command.run`, and `viewport.isFullscreen` / `$.ui.open` → `isPlaced`).

## 1. Colours (header chips, row dots, mix bar, detail cards — everywhere the phase colour appears)

- running: **sunset yellow** (e.g. `#FFB627` / gradient `#FFD166 → #FF9F1C`)
- stalled: **mango orange** (e.g. `#FF8243` / `#FFA552 → #FF7518`)
- finished: **lime green** (e.g. `#9BE15D` / `#B8F35A → #32CD32`)
- failed stays red, cancelled grey. Keep text readable on the dark card (contrast ≥ 4.5:1; dark text on the bright chips if needed).
  Change it in `hooks/palette.ts` only, update tests that assert colours.

## 2. Persistent across sessions, never drops mid-session

Today the live copy is in a per-session dev-mods folder, so it only exists in this one Claude session. Make it load in
every Claude Code session on this laptop (desktop app sessions included), the way a normal installed plugin does,
and survive app restarts. Find the supported way in `reference.md` (e.g. a local marketplace in this repo with
`.claude-plugin/marketplace.json` + `claude plugin install`, or `CLAUDE_CODE_PLUGIN_DIRS` in user settings `env`).
Prefer the one that the desktop app honours and that hot-reloads from `plugins/dsh-workers-pane/` so future edits
apply without reinstalling. Write the exact install commands/settings for Claude; you cannot write outside the repo.
Robustness inside the mod: every hook wrapped so one bad job record or IO error can never throw out of a hook
(log via `$.ui.log`/status and keep drawing the last good view); the 15 s timer re-armed on `session.start`, on
reload, and lazily on the next render if it was lost; no unbounded reads.

## 3. Hidden when idle

Show nothing (no pane auto-open, no band, empty/absent status line) when no DeepSeek worker or data job has started
since the Claude app started. Use the earliest reliable "app/session start" time the API exposes (session.start time,
kept in `$.state`; document what you used). As soon as a job starts after that time, the status line and band appear;
`/dsh-workers` always opens the pane on demand regardless.

## 4. Mobile fallback

The Android app never places panes (`$.ui.open` → `isPlaced: false`; mobile `viewport.isFullscreen === false`).
When the pane is not placed: `/dsh-workers` returns a compact Markdown summary as command output (running rows with
elapsed, tool calls, idle, lease left; then "N finished · M failed today"), and add an `AbovePrompt` band (one line
per running worker, colours as above, hidden when nothing runs) that works on mobile and desktop.

## Checks

validate, tsc, and `claude plugin test --file <each test> <mod>`; add tests for the new colours, idle-hiding rule,
mobile fallback text, and hook error containment. Final answer: what changed, the install steps, test output.
