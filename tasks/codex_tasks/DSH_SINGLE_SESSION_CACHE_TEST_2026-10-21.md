# Single-session prompt-cache test — 21 October 2026

Shivam requested ten country-capital questions in one MCP worker session and actual prompt-cache evidence. Exactly one read-only DeepSeek V4.1 Flash/xhigh/Go2 worker was launched through native MCP, job `20261020T235050Z-c60cc959`. Rounds 2–10 were delivered sequentially through `message_worker` to the same actual conversation `session-037fc5b1-c687-49c7-b74a-d3615df1af62`. Every acknowledgement retained that conversation ID. Stable provider routing ID stayed `fb0219dd-4b70-5e7a-b486-81c4b4442f92`.

All ten answers were correct: Paris, Tokyo, New Delhi, Brasília, Ottawa, Canberra, Berlin, Nairobi, Buenos Aires and Bangkok. The worker finished naturally with exit 0; native MCP status verified both recorded processes dead, and final OS scan found zero active model workers. No kill, retry, second worker, H01, file edits by the worker or project implementation occurred.

Cache evidence comes from real streamed step_end usage, not an inference from stable IDs. The installed pi-ai OpenAI completions adapter maps upstream cached-token fields into cacheReadTokens and excludes them from inputTokens, so cache share is cacheReadTokens / (cacheReadTokens + inputTokens).

- 15 model steps for the ten questions, with cache-read tokens reported in every step.
- First step: 5,888 cached / 5,917 uncached input tokens.
- Remaining 14 steps: 189,184 cached / 4,161 uncached input tokens: **97.8479% cached input**.
- Full test: 195,072 cached input, 10,078 uncached input, 2,421 output tokens.
- Last step: 14,976 cached / 109 uncached input tokens.

Limits and rough edge: Codex instructed the worker to run one 15-second Start-Sleep tool call after each of rounds 1–9 so a subsequent MCP steering question could arrive before final exit. The read-only PowerShell sandbox rejected those commands with a constrained-language type-creation error; the worker continued receiving the steering messages but generated additional wait/status/summary model steps. Therefore this is ten questions across fifteen model requests, not a clean ten-request test. Cache works, but do not use failed sleep commands as a production waiting mechanism. No additional fix/model call was launched. This is provider-reported cache usage, not a provider invoice or independent HTTP attempt audit; exact billed savings were not estimated.

Machine-readable evidence: `reality_engine/data/logs/dsh_single_session_cache_audit.json`, with all usage counts and nine same-conversation message acknowledgements. Full local job event evidence is preserved under the job's runtime directory.
