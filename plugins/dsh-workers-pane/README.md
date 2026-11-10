# dsh-workers — DeepSeek workers pane

A read-only rail beside the chat for `/dsh-worker` jobs: running and finished
lists, expandable detail cards, the pane colours, an above-prompt band and the
`/dsh-workers` command. Hooks only; no tools, no network.

## Install (once, on this laptop)

The repo is the marketplace: `.claude-plugin/marketplace.json` at the repo root
points at this folder. An install copies the mod to
`~/.claude/plugins/cache/reality-engine/dsh-workers/<version>/` and runs that copy, not this folder:
T-082's fields stayed invisible on 5 Nov because the version was not bumped.

From a terminal, at the repo root, at the prompt of a Claude Code session:

```
/plugin install dsh-workers --marketplace C:\Users\warri\Downloads\Info_Diffusion_Model
```

or from a shell:

```
claude plugin install dsh-workers --marketplace C:\Users\warri\Downloads\Info_Diffusion_Model
```

Answer `y` to add the `reality-engine` marketplace if asked, and pick the
**user** scope: the mod then loads in every session this machine starts, the
desktop app's sessions included, and survives app restarts. In a session that
is already open, run `/reload-plugins` (or restart it) to pick the mod up.

After editing anything under `plugins/dsh-workers-pane/`: bump `version` in
`.claude-plugin/plugin.json`, run `claude plugin marketplace update reality-engine` and
`claude plugin update dsh-workers@reality-engine`, then `/reload-plugins` in the open session.

### Alternative: load the folder directly (development)

If you would rather have saves hot-reload without `/reload-plugins`, name the
mod folder in user settings instead of installing it. In
`~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_PLUGIN_DIRS": "C:\\Users\\warri\\Downloads\\Info_Diffusion_Model\\plugins\\dsh-workers-pane",
    "CLAUDE_CODE_PLUGIN_DIR_WATCH": "1"
  }
}
```

This is read by desktop-app and SDK sessions too, and the watch flag makes their
long-lived process reload on save. Use one route or the other, never both: two
loads of one mod register every hook twice.

## Jobs folder

`userConfig.jobsRoot` defaults to
`C:/Users/warri/Downloads/Info_Diffusion_Model/plugins/dsh-worker/runtime/jobs`
(the folder holding one subfolder per job). Change it with
`claude plugin configure dsh-workers` or under `pluginConfigs` in settings.

## What it shows, and when

- **Idle**: nothing is drawn until a DeepSeek worker or data job has started
  after the session began. "The app started" is the `session.start` hook's
  `$.clock.now()`, kept in `$.state` (`startedAt`) so a hot reload keeps the
  same window; a job already running when the app restarted still counts. A
  mod hot-loaded into a running session has no start time and never claims
  idle. `/dsh-workers` always opens the pane on demand.
- **Phase colours**: running is sunset yellow (`#ffb627`, gradient
  `#ffd166 → #ff9f1c`), stalled mango orange (`#ff8243`, `#ffa552 → #ff7518`),
  finished lime green (`#9be15d`, `#b8f35a → #32cd32`), failed red, cancelled
  grey. Chips carry dark text on the bright fill so they stay readable.
- **Band**: one line per running job above the prompt, on the terminal, the
  desktop and the mobile app; hidden when nothing runs and while a survey holds
  the band. Each line shows, in this order (Shivam, 10 Nov 2026): tool calls, output tokens, cached
  (cache-read) tokens, idle minutes, elapsed time and lease left: `4 tools · 3.6k out · 50k cached · idle 5m
  · 20m 00s · lease 1h40 left`. No session id, total tokens or rate on this line (the detail card keeps them). The title truncates first when the band is
  narrow. A fact the job has not stated shows `–`, never `0`; jobs written
  before these fields existed still render, with `–` in each new slot.
- **Detail card**: the tiles are tools, steps, `output` (the output-token count
  only, never the total), `cached`, `total`, `t/s`, files and idle minutes; the
  metadata block adds `provider session <full>` (the stable id) and `dsh session
  <session-…>` (the `session` event in `result.md.events.jsonl`, the dsh
  conversation, labelled so it is not mistaken for the OpenCode id).
- **Tokens per second**: the median of each output step's `outputTokens` over
  its model generation time. The dsh event stream carries no per-step time
  today (no `time` on `step_start` / `step_end`), and the dsh session store
  (`~/.dsh/sessions/<cwd>/<session>/session.v4.jsonl.zstd`) is zstd-compressed,
  which the plugin's `$.fs` cannot decode; so the band and the card show
  `– t/s`. To light it up, the stream's `step_end` usage needs a `durationMs`
  (or `duration_ms`) holding the model's generation time for that step, tools
  excluded — `hooks/events.ts` already computes the median from it. Timing
  `step_start` → `step_end` would include tool execution and understate the
  rate, so it is not used.
- **No pane can be placed** (the Android app, a narrow surface): `/dsh-workers`
  answers with a compact Markdown summary as command output — one line per
  live job (the same facts as the band), then
  `N finished · M failed today` (UTC day).

Every hook is contained: a bad job record or an IO error is logged through
`$.ui.log` (debug log) and the pane keeps drawing the last good view with a
`· stale` status line.
