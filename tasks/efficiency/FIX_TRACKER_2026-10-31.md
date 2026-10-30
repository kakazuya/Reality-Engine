# Efficiency fix tracker — 31 Oct and 1 Nov 2026

Shivam asked (31 Oct): apply all 9 fixes, count for today and tomorrow, then judge which gains were worth taking.

**How it is counted:** nothing needs to run in the background, because the logs persist. On the night of 1 Nov run:

```
python reality_engine/scripts/tool_usage_report.py --since 2026-10-31T00:30+05:30 --compare tasks/efficiency/TOOL_USAGE_2026-10-30.json --out tasks/efficiency/TOOL_USAGE_2026-11-01
```

(`--compare` and `--until` arrive with round 2.) Exclude the 3 workers started before the fixes when comparing dsh rates.

| # | Fix | Live from | Baseline (to 30 Oct) | Metric to compare | Saving promised |
|---|---|---|---|---|---|
| 1 | Claude hands off and restarts at about 150k context | Next session | 290k cached tokens per step | Cached tokens per step | 40–50% of Claude quota |
| 2 | Workers write long code, not Claude | Now | 1,026 edits; 561M of 1.88B re-sent | Claude edit/write share of re-sent volume | 10–20% of Claude quota |
| 3 | Short `worker_status` and `worker_result` | Round 2 merge + dsh-worker reconnect | 879k tokens, 42% of Claude tool output | Tokens per control call | About 10% of Claude quota |
| 4 | `sql` tool, not inline Python | Round 1 merge | Inline DB 894 calls, 20% failed; `sql` 613, 0% failed | Inline DB share of DB calls; failure rate | About 180 failed calls |
| 5 | Batch read-only calls | Round 2 merge | 5,033 of about 21,600 steps (23%) | Batchable steps as a share of steps | About 10% of steps |
| 6 | No sleeping in loops | Round 2 merge | 794 calls, 12.5 h explicit sleep (11% of 114 worker-hours) | Sleep seconds per worker-hour | Up to 10% of worker time |
| 7 | LSP and context pack | Round 1 merge | LSP 0.65 per job; 18 calls before first edit | LSP per job; calls before first edit; read share | About 8% of worker tokens |
| 8 | Repeat test failures | pytest live 31 Oct 00:15; rest in round 2 | Tests/compile 234 of 819 failed | Failure rate | Small |
| 9 | Shell reads to read/grep tools | Round 1 merge | 3,517 calls; shell 42% of calls | Shell share of calls | Small |

**Verdict rule on 1 Nov:** a fix is worth keeping if its metric moved by at least half of what was promised and the work it took was less than what it saved. Small samples get called small samples. Worker tasks differ by day, so compare rates, not totals.
