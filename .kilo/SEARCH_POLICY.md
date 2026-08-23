# Dual Search Routing Policy

This project has **two** web search tools active:

1.  **Default Kilo `web_search`** — light single-shot queries. Use for: syntax checks, single error lookup, doc page fetch, quick fact.
2.  **Tavily MCP (`tavily-heavy`) — `tavily-search`, `tavily-extract`, `tavily-crawl`, `tavily-map`** — heavy research. Use for: multi-hop research, 2-5 searches, market/macro research, news aggregation, deep extraction.

## Routing Rule (must follow)

- If the task needs **1 search** → use `web_search`.
- If the task needs **≥2 searches, synthesis, recent news, or structured extraction** → use Tavily MCP tools (`tavily-search` with `search_depth: advanced`, `max_results: 10`, `include_answer: true`).
- For URL content after search, prefer `tavily-extract` over `webfetch` when you came from Tavily.
- Do not call both for the same query — pick one per intent to save cost.

## Tavily MCP Details

- Server: `https://mcp.tavily.com/mcp` (remote, `type: remote`)
- Auth: URL `?tavilyApiKey=${TAVILY_API_KEY}` + `Authorization: Bearer ${TAVILY_API_KEY}` — set env var `TAVILY_API_KEY` **before VS Code starts**.
  - **Why your reload failed:** `$env:TAVILY_API_KEY="..."` in a PowerShell terminal does NOT propagate to the already-running `Code.exe` process. You must launch VS Code from that same terminal, or set a persistent env var.
  - Option A (quick test, current window): In the SAME PowerShell where you set the key, run `code "C:\Users\warri\Downloads\Info_Diffusion_Model"` then `Reload Window` (`Ctrl+Shift+P` → `Developer: Reload Window`). Do NOT launch Kilo from old VS Code shortcut.
  - Option B (persistent, recommended): `setx TAVILY_API_KEY "tvly-..."` → close all VS Code → reopen. Verify with new PowerShell: `echo $env:TAVILY_API_KEY`.
  - Option C (no env expansion, most reliable): Edit `.kilo/kilo.jsonc` and replace `${TAVILY_API_KEY}` literally with your key in BOTH `url` and `headers.Authorization` — e.g. `https://mcp.tavily.com/mcp/?tavilyApiKey=tvly-abc123` and `"Authorization": "Bearer tvly-abc123"`. Restart VS Code. Do not commit the file with real key.
  - bash / Agent Manager worktree: `TAVILY_API_KEY=tvly-... kilo` or put `TAVILY_API_KEY=tvly-...` in `.env` at repo root (copied to worktrees via `setup-script`).
- Defaults injected via `DEFAULT_PARAMETERS` header: `{"max_results":10,"search_depth":"advanced","include_answer":true}`

## Fallback Local Alternative

If remote MCP is blocked, swap `.kilo/kilo.jsonc` entry to local:

```jsonc
"tavily-heavy": {
  "type": "local",
  "command": ["npx", "-y", "tavily-mcp@latest"],
  "environment": {
    "TAVILY_API_KEY": "${TAVILY_API_KEY}",
    "DEFAULT_PARAMETERS": "{\"max_results\":10,\"search_depth\":\"advanced\",\"include_answer\":true}"
  },
  "enabled": true,
  "timeout": 20000
}
```

Requires Node.js >=20 (`node --version`).

## Verification

- **Your screenshot is VS Code's palette, not Kilo's.** Do this instead: Click the Kilo Code icon in the Activity Bar (left sidebar) to focus Kilo, then either:
  - Press `Ctrl+P` **while Kilo input is focused** → `Toggle MCPs`, OR
  - Type `/mcps` **in the Kilo chat input at the bottom** (the `Type a message...` box) and press Enter.
- VS Code's top bar `Ctrl+P` → `/mcps` will always say `No matching results` — that's expected.
- Expected: `tavily-heavy` shows `connected`, tools: `tavily-search`, `tavily-extract`, `tavily-crawl`, `tavily-map`. If it shows `error` or `disconnected`, check `Output` panel → `Kilo` logs for `tavily-heavy: failed to fetch headers/Authorization`.
- `web_search` stays enabled for light queries (check `Settings > Plugins > Web search`).
