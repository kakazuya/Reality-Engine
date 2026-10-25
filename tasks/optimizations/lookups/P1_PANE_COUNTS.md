# Task P1 — DeepSeek workers pane: make the bar's counts add up to the Finished list

## Goal
The pane's count tiles (bar) and the "Finished N" section always agree: tiles show ok / failed / cancelled, and
ok + failed + cancelled == N.

## Why
Shivam saw "✕ 2 failed ✓ 74 finished" on the bar but "Finished 83". On disk: 74 `finished/completed`,
7 `cancelled`, 2 failed starts. Cancelled jobs have no tile (`rows.ts` `statusMeta` counts phase `finished` and
`failed` only, while the Finished section lists every final phase). Also a `finished` job whose outcome is `failed`
(non-zero exit) is counted under the ✓ tile today.

## Files to touch
- `plugins/dsh-workers-pane/hooks/rows.ts` — `WorkerCounts` + the counts in `statusMeta` (~line 612): count by
  outcome: `finished` = outcome `ok`, `failed` = outcome `failed` (phase failed OR finished with failed outcome),
  new `cancelled` = outcome `cancelled`. Keep `running`/`stalled` as they are.
- `plugins/dsh-workers-pane/hooks/register.tsx` — the tiles (~lines 520–620): add a cancelled tile (neutral/grey,
  icon `⊘` or the one used for cancelled rows), shown only when > 0; the bar segment widths include it.
- The type file under `plugins/dsh-workers-pane/types/` if `WorkerCounts` is declared there.
- Tests: `plugins/dsh-workers-pane/hooks/rows.test.ts`, `pane.test.tsx`.
- Do not touch: anything outside `plugins/dsh-workers-pane/`.

## Steps
1. Read `plugins/dsh-workers-pane/README.md` for how tests run.
2. Change the counts; add the tile.
3. Add a test: a fixture with 3 ok, 1 finished-with-exit-1, 1 failed start, 2 cancelled → tiles 3 / 2 / 2 and
   Finished section count 7.

## Acceptance checks
1. The pane's test command from the README → all pass.
2. Typecheck from the README (if any) → clean.
3. `git diff --stat` only under `plugins/dsh-workers-pane/`.

## Budget
≤ 12 tool calls before the first edit; ≤ 45 total; ≤ 30 min; $0 paid.

## Report format
1. What changed  2. Verified (counts)  3. Outside-sandbox steps  4. Open problems  5. Tool calls before first edit / total.
