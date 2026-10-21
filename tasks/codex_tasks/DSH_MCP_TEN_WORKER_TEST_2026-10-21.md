# Ten-worker native MCP lifecycle test — 21 October 2026, about 05:17 IST

Shivam explicitly requested ten instances answering capitals of different countries, checking persistent sessions and unwanted continued API activity. Codex launched exactly ten read-only workers through native `mcp__dsh_worker.start_worker`, xhigh/Go2, refresh_context=false, output cap 1024 per request. No additional inference probes or retries.

All ten returned naturally with exit 0. No cancellation needed. Each recorded exactly one model step start, one final event, zero tool calls and zero error events. All ten supervisor/launcher processes died. Native MCP listing showed zero running jobs. After an additional observation of at least 30 seconds, result/event/heartbeat/status lengths and timestamps were unchanged, with zero active model worker processes. This demonstrates no continuing activity for these completed jobs during this observation; it is not a network-level count of HTTP attempts or a provider billing audit.

Ten distinct actual dsh conversation IDs; all share stable provider routing/cache ID `fb0219dd-4b70-5e7a-b486-81c4b4442f92`. Persisted job/session records and answers survive completion; the processes do not remain waiting or keep making calls. A stable provider routing ID does not make these independent conversations one shared conversation.

Answer behavior (raw final content):

| Country | Answer |
|---|---|
| France | COUNTRY: CAPITAL |
| Japan | JAPAN: TOKYO |
| India | COUNTRY: CAPITAL |
| Brazil | Brazil: Brasília |
| Canada | Canada: Ottawa |
| Australia | Australia: Canberra |
| Germany | COUNTRY: CAPITAL |
| Kenya | COUNTRY: KENYA |
| Argentina | Argentina: Buenos Aires |
| Thailand | Included Thailand: Bangkok, plus commentary about the format being ambiguous |

Six responses contained the correct capital; four were placeholder/incomplete answers. The brief said "Return exactly COUNTRY: CAPITAL", which was ambiguous and invited copying the literal template. This test proves lifecycle success, not ten correct answers or clean instruction following. No extra paid rerun was made. Future prompts should simply ask the question and request the city name, without uppercase placeholder text.

Jobs: `20261020T234634Z-7824d99b`, `20261020T234635Z-667232ff`, `20261020T234635Z-77b5dc0c`, `20261020T234636Z-6814abad`, `20261020T234637Z-e0c97bfc`, `20261020T234638Z-d16064ab`, `20261020T234639Z-e974952d`, `20261020T234640Z-94d4e03e`, `20261020T234642Z-4e0b8284`, `20261020T234643Z-3646c74f`.

Local event/file baseline: `reality_engine/data/logs/dsh_capitals_baseline.json`. Runtime evidence and exact briefs/results are in each `plugins/dsh-worker/runtime/jobs/<job_id>/` folder. No project implementation, database writes or H01 work. No overnight worker left running.
