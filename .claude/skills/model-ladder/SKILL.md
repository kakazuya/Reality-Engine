---
name: model-ladder
description: Which model/worker gets a job (Shivam's 26 Nov reasoning ladder) - Gemma on gemini-worker for errands, DeepSeek off-peak / Hydrogen in peak, Hydrogen high on repeated fails, Opus medium for hard review, Neon 4 sparingly; question search on Flash 3.8. Use before starting any worker, grader or model call.
---

# Reasoning ladder (Shivam 26 Nov 2026; his words in `docs/rulings/RULINGS_VERBATIM.md`)

| Rung | Job | Where |
|---|---|---|
| 1 | Simple errands (formatting, lookups, short classification) | gemini-worker MCP `gemma-4-31b-it` / `gemma-4-26b-a4b-it` - only if responding and quick |
| 2 | Slightly harder (code to a prescriptive brief, extraction fixes, grading) | DeepSeek (`dsh`, max effort) OFF-PEAK; agy `gemini-4-hydrogen-high` in PEAK |
| 3 | DeepSeek weak or failing repeated rounds (even off-peak) | agy `gemini-4-hydrogen-high` |
| 4 | Higher reasoning / review | Claude itself (Opus medium) |
| 5 | Hardest reasoning / review, only when Opus cannot work it out | agy `gemini-4-neon-high` / `gemini-4-neon-xhigh`, sparingly |
| - | Company investor-question search | agy `gemini-3.8-flash-medium` while its lifetime lasts. Never Argon. |

Peak: Mon-Fri 06:30-09:30 and 11:30-15:30 IST - read the clock (`date` in Git Bash is IST).

## Limits measured (26 Nov)
- gemini-worker AI Studio pool (37 keys): Hydrogen/Argon 10 req/key/day (pool 370) - near useless; Gemma 31B 14,000
  req/key/day, 25 rpm. Measured: a 5k-token grading prompt hit 429 (per-minute) or 503 on 191 of 214 calls, median 42 s
  -> Gemma fails "quick enough" for page grading; use it for short prompts only, move up a rung otherwise.
- agy allowlist (`plugins/agy-worker/server/agy_core.py MODELS`): hydrogen-high, neon-high, neon-xhigh,
  flash-3.8-medium, opus-5-5-medium. After an allowlist change: `/mcp` reconnect agy-worker.
- Free OpenCode Go readers (bake-off 26 Nov): only `hy4-flash-free` reads images fast; beam/iceman text-only and slower.

## Every start
- dsh: `permission` named, brief with Goal/Files/Accept/Evidence/Stop if/Budget/Ticket (skill `worker-brief-merge`).
- agy grader: brief line `permission: read-only`, `use_worktree=false`.
- Paid models only with Shivam's OK. Set `REALITY_READ_HARNESS` when a harness (agy, Claude Code, dsh) reads pages
  (skill `read-provenance`).
