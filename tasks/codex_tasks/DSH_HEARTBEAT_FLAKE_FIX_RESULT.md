# DSH heartbeat integration flake — fix result

Date: 2026-10-21. Scope: `reality_engine/tests/test_dsh_heartbeat.py` only. No implementation, plugin,
wrapper, STATE/AGENTS, database, secret, security, or package-install change.

## Failure cause (reproduced, not assumed)

The focused test failed on the first baseline run. Instrumented status showed:

- ping 1 was delivered (`200`, `delivery_ok=true`, agent `running`) but marked `missed` after its
  **2.0 s** window;
- ping 2 was issued at the miss boundary and returned `503 steer-failed` because the agent was already
  finishing; the first committed `tool_call` arrived immediately after and answered ping 2;
- the run itself still completed `rc=0`, with the final answer and listener closed.

So the supervisor behaved as documented: it starts the response window when the ping is delivered,
and a ping with no committed dsh event in that window is a miss. The test fixture was the problem:
`FakeChatCompletions` held its first model step for a fixed **1.2 s** while the response window was
**2.0 s**. dsh startup / control bind / first model step / tool boundary could consume the remainder
under normal Windows scheduling, so the fixed hold raced the window instead of guaranteeing a response
inside it. This was a fixture timing assumption, not a product defect.

## Exact change

In `reality_engine/tests/test_dsh_heartbeat.py`:

- `FakeChatCompletions.expect_ping_descriptor(control)` binds the fake model to the run's control
  descriptor. `wait_for_ping()` polls that descriptor until the control plugin records a delivered
  ping (`pings >= 1`), then the first model step is released immediately. The committed `tool_call`
  now falls inside ping 1's window by event order, not by a timed sleep.
- Applied to both real-dsh integration tests (direct transport test and `run_supervised()` test).
  The direct test keeps its explicit ping; the supervisor test no longer relies on the 1.2 s hold.
- Supervisor test response window changed from **2.0 s to 5.0 s** — a bounded scheduling budget for a
  real dsh process/tool boundary, not blanket timeout inflation. Idle remains **0.5 s**.
- Assertions strengthened: the answered ping must have `delivery_ok=true`, and `answered_by` must be
  a real committed event kind (`text`/`thinking`/`tool_call`/`tool_result`/`final`/`step_output`), so
  an HTTP acknowledgement alone cannot satisfy the test.
- Preserved: `rc=0`, final answer content, real same-agent steering (`heartbeat_seen`), two-miss
  semantics (untouched unit/process tests), listener cleanup, token absence.

No `dsh_heartbeat.py` or `dsh_heartbeat_control.mjs` change was needed.

## Commands and actual results

```
python -m unittest reality_engine.tests.test_dsh_heartbeat.RealDshControlIntegrationTests.test_run_supervised_parses_real_dsh_events_and_answers_heartbeat -q
```
Baseline (before fix): `Ran 1 test in 13.557s; FAILED (failures=1)` — `'missed' != 'answered'`.
Instrumented baseline: `Ran 1 test in 9.866s; FAILED` — ping 1 delivered then missed; ping 2
`steer-failed` then answered by `tool_call`.

After fix:
```
python -m unittest reality_engine.tests.test_dsh_heartbeat.RealDshControlIntegrationTests.test_run_supervised_parses_real_dsh_events_and_answers_heartbeat -q
Ran 1 test in 12.139s
OK
```

One combined suite (quiet output):
```
python -m unittest reality_engine.tests.test_deepseek_harness_controls reality_engine.tests.test_dsh_heartbeat reality_engine.tests.test_dsh_worker_plugin -q
Ran 50 tests in 127.536s
OK
```

## Remaining limitation

The fixture still requires the supervisor to issue a ping; with `idle_seconds=0.5` that is expected.
The coordination wait is bounded at 20 s and releases on timeout, so a genuinely broken heartbeat
would fail on the assertions instead of hanging. The 5 s window is test-local; production default
windows are unchanged. No live/paid inference, network model, database, or package install was used.
