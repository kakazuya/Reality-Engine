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
- Auth: URL `?tavilyApiKey=${TAVILY_API_KEY}` + `Authorization: Bearer ${TAVILY_API_KEY}`. Set `TAVILY_API_KEY` as a persistent environment variable before VS Code starts; a value set in a terminal does not reach a running `Code.exe`. Never write the key into a file.
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

Type `/mcps` in the Kilo chat input. Expected: `tavily-heavy` shows `connected`, with tools `tavily-search`, `tavily-extract`, `tavily-crawl`, `tavily-map`. On an error, read the `Kilo` output panel.
