---
description: Wire substrate peer runners into CLI
---

# lane-code-cli — Wire substrate scripts into `reality_engine/cli.py`

> Worktree: `WORKTREE_PATH` (your checkout), `REPO_PATH` (main repo). DB is EMPTY in worktree — read-only queries only.

## 0. Read contract first

- Read `.kilo/LANES.md` before any edit. You own ONLY `reality_engine/cli.py` (plus `reality_engine/tests/test_cli_and_dashboard.py` to fix assertions). **never edit files you do not own; never write DB tables you do not own; worktree-local helper scripts must be deleted before merge or listed in the lane report**

## 1. Discover entry points (read file, don't assume)

Read each runner first to find its `main()`/argparse entry point:
- `reality_engine/scripts/run_supply_peer.py`
- `reality_engine/scripts/run_quality_peer.py`
- `reality_engine/scripts/run_policy_peer.py`
- `reality_engine/scripts/run_factor_peer.py`
- `reality_engine/scripts/run_moe_eod.py`

Scripts may concurrently gain optional args (`--universe {nifty200,nifty500,all}`, `--limit`, `--include-derived`) from another lane. Import robustly: prefer `subprocess [sys.executable, script, ...]` so new flags don't break your wiring. If importing, use `try/except` around unknown kwargs.

## 2. Wire 5 peer commands + orchestrator

In `reality_engine/cli.py`:
- `seed-quality-peer` → delegates to `run_quality_peer` (tolerates optional `--universe/--limit/--include-derived`)
- `seed-policy-peer` → delegates to `run_policy_peer`
- `seed-factor-peer` → delegates to `run_factor_peer`
- `seed-supply-peer` → delegates to `run_supply_peer` (which also handles geographic exposure extension)
- `run-moe-eod` → delegates to `run_moe_eod`
- `seed-peers` orchestrator: runs in dependency order **supply → quality → policy → factor → moe**. Each step is `try/except` isolated, prints per-step `OK/FAIL`, continues on failure, exits non-zero only if all fail. Reuse subprocess invocation for robustness.

Register each via `subparsers.add_parser(...).set_defaults(func=...)` following the existing pattern in `cli.py`. Keep `--help` working for each.

Args: `$ARGUMENTS` forwarded to the underlying command; `seed-peers` takes no extra `$1` (uses `$ARGUMENTS` if supplied).

## 3. Parallel sub-agent fan-out

Fan out via **Task tool** where marked:
- One sub-agent per command wiring (5–6 parallel agents). Each sub-agent reads ONE runner file and drafts the wiring snippet for that single command + its argparse block.
- Parent integrates snippets **serially** into `cli.py` to avoid double-editing (single writer).

## 4. Tests (run in worktree)

```powershell
python reality_engine/cli.py --help
python reality_engine/cli.py seed-peers --help
python -m unittest reality_engine.tests.test_cli_and_dashboard
```

`--help` must list the six new commands. `test_cli_and_dashboard` must stay green (fix only assertions that assume old help text).

## 5. Do NOT git commit/merge

Do NOT run `git commit`, `git merge`, or `git stash` (stashes are global across worktrees). The local session integrates; Agent Manager merges branches (user-driven).

## 6. REPORT (end with this block)

```
REPORT lane-code-cli
- Files changed: reality_engine/cli.py, [reality_engine/tests/test_cli_and_dashboard.py if touched]
- Tests: python reality_engine/cli.py --help => OK/FAIL, seed-peers --help => OK/FAIL, test_cli_and_dashboard => GREEN/RED (counts)
- Artifacts: commands registered [seed-quality-peer, seed-policy-peer, seed-factor-peer, seed-supply-peer, run-moe-eod, seed-peers]; subprocess invocation used: YES/NO
- Worktree-local helpers deleted or listed: none / [list]
```
