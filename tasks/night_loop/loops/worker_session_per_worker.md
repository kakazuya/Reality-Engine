# Worker: one OpenCode session id per worker

Goal: every dsh worker sends its own `x-opencode-session`, stable for that worker's whole run, follow-ups and restart of the same job included, and different from every other worker's. Shivam's ruling, 5 Nov.

Ticket: T-069

Evidence: measured by Opus on 5 Nov.
- `reality_engine/scripts/run_deepseek_harness.py:96` writes the header as `session_id("dsh", model, key_env)`, and line 288 records the same as `provider_session_id`.
- `plugins/dsh-worker/server/core.py:764` `_provider_session` computes the same value and returns it in `start_worker` (lines 1467-1472, 1531, 1657).
- `reality_engine/scripts/go_session.py:24` `session_id(job, model, key="", lane_no=None)`: uuid5 of those parts; `lane()` reads the thread name, so a harness main thread is always lane 0. Result: jobs `20261104T184919Z-f7c4d41b`, `20261104T195121Z-636c4920`, `20261104T195138Z-3c358974`, `20261104T195142Z-de08992e` and `20261104T195309Z-cc9dbbe9` all show `fb0219dd-4b70-5e7a-b486-81c4b4442f92`.
- OpenCode's documentation asks for a stable id for each conversation.
- Conversations themselves are already separate: each worktree has its own folder under `~/.dsh/sessions`.

Do: pass the job id into the id as `job`, for example `session_id(f"dsh-{job_id}", model, key_env)`. First find how the harness learns its job (arguments in `core.py` where it builds the `MODEL_LAUNCHER_MODULE` command, and the `run_deepseek_harness` argument parser). A run started by hand with no job id derives the id from its resolved `--out-file` path, so it is stable when repeated and differs between runs. The value `start_worker` reports and the value the header sends must be equal, computed by one shared function. HP jobs (`hp_worker.py`) get the same rule if they use this function: check, and report what you found. Do not change `go_session.session_id`'s signature or any other caller.

Files: `reality_engine/scripts/run_deepseek_harness.py`, `plugins/dsh-worker/server/core.py`, the tests that assert the id (`grep -rl "provider_session" reality_engine/tests plugins/dsh-worker`), your lines in `docs/DEVELOPER_GUIDE.md` and `tasks/OPENCODE_ORCHESTRATION.md` line 99. Do not touch `tasks/STATE.md`.

Accept:
1. New tests: two job ids give two ids; the same job id gives the same id twice; the id `start_worker` reports equals the header the patch writes.
2. `python -m pytest <each test file you changed or added> -q`, one file per process; print each result. No assertion loosened except the ones that stated the old single id; list those.
3. `mcp__code-tools__typecheck` on the changed files: no new errors.

Rules: do not start any model run or worker as a test. Four answer workers are running from the main checkout's code: do not touch their job folders, `~/.dsh/profiles`, or the main checkout.

Stop if: the job id cannot reach the harness without changing the supervisor's process contract; then report the smallest change that would.

Budget: 30 tool calls. End with what changed, test results, and a `Docs updated:` line.
