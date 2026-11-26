# T-242 brief: free OpenCode Go reader bake-off vs hy4 (skill free-model-bakeoff)

Goal: measure whether any other FREE model on the OpenCode Go endpoint reads our pages as accurately and as fast as hy4-flash-free, using the same reader (reality_engine/v2/observations.py) and prompt, so heavy reading is not tied to one model.
Files: none in the repo required (read-only measurement); scratch under your worktree .tmp only. If the reader cannot select a model without a code change, make the smallest change (a MODELS/--reader entry) in reality_engine/v2/observations.py with a test, and say so.
Accept: a results table per model (pages read, rows, verified share, errors, median and p90 seconds per call, 429s/quota, cost reported) on the SAME page sample, plus a 30-row-per-model grade pack (C:/RealityEngine/t242/go_bakeoff/<model>/pack.jsonl built with reality_engine.scripts.grade_pack) for Wolf's graders.
Evidence: Shivam 26 Nov 11:15: "most of the heavy lifting is being done by opencode go only ... see what other models are free on opencode go and check if they are also as fast & accurate as HY4". `opencode models` lists these Go ids ending -free: opencode-go/beam-free, opencode-go/hungerg-free, opencode-go/iceman-contributor-free, opencode-go/hy4-flash-free (baseline). Every other Go model (deepseek-v4-pro, glm-5.3, kimi-k3, qwen*, mimo*, minimax*, longcat-2.5, hy4, hy4-preview, ...) uses the paid Go subscription - DO NOT CALL THEM. Baseline speed from logs: hy4 median 5.6-8.6 s per call, p90 ~10-13 s. Reader endpoint base https://opencode.ai/zen/go/v1 (observations.py ~8268), READER = "hy4-flash-free" (line 99), `--reader` CLI flag exists (MODELS registry entry).
Stop if: a candidate reports a non-zero cost (stop that model at once); a candidate refuses or errors 3 times in a row (drop it, record why); any call would need a key other than Go key 1.
Budget: ~100 tool calls; at most 40 pages per model.
Ticket: T-242

## Steps (skill: .claude/skills/free-model-bakeoff/SKILL.md - follow it)
1. Gate each candidate with ONE reader call on one page (cost must be 0; record model reply format errors).
2. Sample: 40 pages with random.Random(1127) from the universe stores - 15 transcript windows, 15 deck table/chart pages, 10 results pages - the same list for every model. Write the list to .tmp/go_bakeoff_pages.json.
3. Run the reader per model on exactly those pages into separate scratch DBs (e.g. `--only` selector or a scratch page list; --out .tmp/go_bakeoff/<model>.db; workers 10). hy4 baseline on the same pages into its own scratch DB (do not reuse live DBs).
4. Measure per model: pages read, rows, verified/unverified/quarantined share, parse failures, median/p90 call seconds, 429s.
5. Cross-check: for deck/results numbers, % of each model's verified rows whose (doc_key, page, value, period) also appears in hy4's verified rows, and vice versa (agreement both ways).
6. Build a 30-row grade pack per model (seeded, verified+unverified) for Wolf's non-author graders; do not grade yourself.

## Limits
Free models only; Go key 1 only; never write live DBs under D:/RealityEngine/hy4_out or C:/RealityEngine/tg_build; never kill processes by name; no key printed. Report table + pack paths.
