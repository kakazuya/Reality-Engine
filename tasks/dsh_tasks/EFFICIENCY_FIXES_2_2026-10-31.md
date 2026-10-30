# Task — efficiency fixes round 2, from the measured tool-usage report

## Goal
Apply the fixes the measurement ranked highest (`tasks/efficiency/TOOL_USAGE_2026-10-30.md`). Start only from a base that contains round 1 (`EFFICIENCY_FIXES_1_2026-10-30.md`).

## Fixes
1. **Compact controller outputs.** `worker_status` and `worker_result` were 42% of Claude's tool output (879k tokens); one `worker_result` carrying 5 KB of answer returned about 14 KB of envelope.
   - Default `worker_status`: phase, done, succeeded, the one-line summary, tool-call counts, lease seconds left, failure reason. Under 1,000 chars.
   - Default `worker_result`: outcome, exit code, content, worktree branch and head, changed-file count (not the list). Everything else needs `verbose=true`.
   - `list_workers`: default limit 5, one short line per job.
2. **No idle polling by workers.** 794 sleep/poll calls and 12.5 h of explicit sleeps. Add a blocking wait to the standing instruction route: long runs start detached and the worker waits with one blocking call (`job_output` with a wait, or a host-side wait until a process exits or a file appears) instead of sleeping in a loop. Add this to `CODE_INTEL_INSTRUCTION`, or rename it to a general standing instruction.
3. **Batch read-only calls.** 5,033 read-only steps could have been batches. Strengthen the standing instruction with one concrete example, and add a `batched_read_steps` count to the worker progress digest, so review can see it.
4. **Token ledger.** dsh input tokens are never recorded and Go API readers have no ledger (`cost_ledger.charge()` has no callers).
   - Record per-step input and cached tokens in dsh job progress where the provider returns them.
   - Add one small helper for direct Go API calls that appends model, tokens and caller to `tasks/ledgers/spend.jsonl`; use it in `tasks/arch_v4/nid_beam_preread.py` and the 4 scripts that post to `opencode.ai/zen/go`.
   - Teach `tool_usage_report.py` to read both.
5. **Targeted gate.** Add to `tasks/pilot60/gate_run.py`: `--regress` (re-run every currently strict-ANSWERED case) and `--blocker NAME[,NAME]` (every case whose current blocker matches), printing gained and lost cases against the last full results. Back-test: `tasks/efficiency/idea3_gate_sample.py`, `idea3b_blocker_share.py`. Expected: about 64 regression cases plus the target stratum, 2–10 minutes, against 24–51 for a full run. Do not change grading. Run it for real once on `--regress` and report the time and that it reproduces the 64.
6. **Repeated test failures.** Check the top failure signatures in the report §f (`unittest discover -s plugins/reality-data/tests`, `test_dsh_worker_plugin`, `.tmp/minipytest.py` — pytest is now installed in system python). Fix what is broken; drop what is obsolete.

## Rules
- Workspace writes only, except running the gate read-only. No paid models, no installs.
- Control-plane files: no new network calls beyond logging, no changes to lease, permission, write-scope or peak-hour logic.
- Old callers of status and result must still work via `verbose=true`; update tests.

## Acceptance checks
- `worker_status` default under 1,000 chars and `worker_result` envelope under 800 chars plus content, measured on a real finished job.
- `tool_usage_report.py` reads the ledger; fixture test added.
- `gate_run.py --regress` reproduces the current strict-ANSWERED set, or lists each difference.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_dsh_worker_plugin.py reality_engine/tests/test_tool_usage_report.py -q
```

## Report
Before and after sizes; the gate timing; each failure signature's fix; restart steps for the controller; code-intel calls vs grep/read/pwsh; calls before first edit; read-only steps batched.


## Added 31 Oct: count support for the fix trial
7. **`tool_usage_report.py`:** add `--until` and `--compare <baseline.json>`. The comparison prints the metrics in `tasks/efficiency/FIX_TRACKER_2026-10-31.md` as rates, baseline vs window: Claude cached tokens per step; Claude edit/write share of re-sent volume; tokens per worker-control call; inline DB share of DB calls and its failure rate; batchable steps as a share of steps; sleep seconds per worker-hour; LSP per job; calls before first edit; read share; tests/compile failure rate; shell share of calls. Add `--exclude-jobs` so workers started before the fixes can be left out.
