# Focused heartbeat integration failure — Codex review

Shivam -> Codex review/orchestration -> DeepSeek implementation/fixes, off-peak xhigh. Read tasks/FRAMEWORK.md and the existing heartbeat source/report as needed. No broad research, no package install, no live inference, no database/secret reads, no security changes. Another worker is finishing ONLY plugin packaging/docs under plugins/dsh-worker and its report; your ownership is disjoint.

Allowed edits ONLY `reality_engine/tests/test_dsh_heartbeat.py`, narrowly necessary `reality_engine/scripts/dsh_heartbeat.py` or `dsh_heartbeat_control.mjs` if an actual implementation defect is proven, and new `tasks/codex_tasks/DSH_HEARTBEAT_FLAKE_FIX_RESULT.md`. Do not edit plugin files or its tests, wrapper, STATE, AGENTS, other sources.

Codex independently ran:
`python -m unittest reality_engine.tests.test_deepseek_harness_controls reality_engine.tests.test_dsh_heartbeat reality_engine.tests.test_dsh_worker_plugin -q`

Actual result: Ran 50 tests in 85.052s; FAILED (failures=1). Only failure:
```
test_run_supervised_parses_real_dsh_events_and_answers_heartbeat
  reality_engine/tests/test_dsh_heartbeat.py line 650
  self.assertEqual(pings[0]['outcome'], 'answered')
  AssertionError: 'missed' != 'answered'
```
Prior checks in that test passed (completed real dsh run/final answer); earlier runs passed. This looks like a scheduling-sensitive fake integration response window, but diagnose rather than assume. Test uses actual installed dsh, the shipped Cordis adapter and local fake SSE model; paid network is forbidden.

Make the test deterministic under normal Windows process scheduling, preserving real same-agent steering, meaningful activity reset, ACK != reply, genuine two-miss behavior and listener cleanup. Prefer explicit fixture event coordination and a reasonable bounded response budget over subsecond timing assumptions. Do not weaken functional assertions merely to hide a product defect; if you assert a particular ping is answered, arrange the fixture so its response actually arrives within that ping's window. No 10-run loops, no sleeps of 15 minutes, no blanket timeout inflation. Run the focused failing test after the fix, then ONE combined 50-test suite with quiet output so the full summary is captured. Only re-run a focused test if a new concrete failure requires a real change.

Return a compact actual handoff immediately when checks pass. Explain the failure cause, exact change, commands/results and any remaining limitation. Codex will review/install. Do not spend time repeatedly polishing already complete docs.
