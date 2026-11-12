# agy-worker (T-112)

Claude's control panel for Antigravity CLI (`agy`) coding jobs, modelled on dsh-worker. Model is pinned to
`gemini-3.8-flash-medium` (Shivam, 7 Nov 2026). Registered in `.mcp.json` as `agy-worker`. Code: `server/agy_worker_mcp.py` (the MCP tools), `server/agy_core.py`
(jobs, event parsing, quota), `server/runner.py` (the detached run; on exit it writes `exit.json` and sets `job.json` `phase` to `ended` with the outcome, T-200), `server/agy_tools_mcp.py` (Gemini's check runner).

| Tool | What it does |
|---|---|
| `start_worker(brief, use_worktree=True, base, timeout_seconds=3600, test_cmd)` | worktree `IDM-worktrees/Wolf-agy-<job_id>` on branch `Wolf-agy-<job_id>`, then a detached `runner.py` runs `agy -p <brief> --mode accept-edits --output-format stream-json`; returns at once |
| `worker_status(job_id)` | done, outcome, elapsed, tool calls by tool, tokens (input, output, thinking, cache), last tool, denied actions, tool errors; parsed from `events.jsonl`, no model call |
| `worker_result(job_id)` | final answer, branch, head, diff stat |
| `resume_worker(job_id, message)` | continues that job's own Gemini conversation (`agy --conversation <id>`) in the same worktree and branch, as a new job with `resumed_from`; for review notes and unfinished steps (one task stays in one worker session) |
| `list_workers`, `cancel_worker(confirm=true)`, `remove_worktree` | as in dsh-worker |
| `quota()` | the logged-in Google account's Gemini and Claude/GPT weekly and five-hour limits left (`agy -p /usage`) |

Job files: `plugins/agy-worker/runtime/jobs/<job_id>/` (`job.json`, `brief.md`, `events.jsonl`, `stderr.log`,
`exit.json`); gitignored. When the run ends the runner commits a non-empty worktree diff on the job branch.

**Permissions (Shivam, 8 Nov 2026).** Every job runs with `--dangerously-skip-permissions` (job field
`bypass_permissions`, default true), so Gemini has a real shell (PowerShell, python) like a dsh worker with full
access; the brief and the worktree are the fence. Before that ruling the setup below was the only way to run checks;
`agy-tools` stays registered as a fallback.

**Gemini's own tools.** agy's headless mode denies every shell command and an allow-rule for commands did not work
(8 Nov), and a denied action ends the whole turn. So the worker gets `agy-tools` (`server/agy_tools_mcp.py`, added
to agy's global MCP config): `run_check(command)` runs one allowlisted command (pytest, ruff, basedpyright,
py_compile, any `python -m reality_engine.<module>`, git status/diff/log/show; no pipes or chaining) in the job workspace, which the runner passes
as `AGY_JOB_WORKSPACE`. agy's permissions (`~/.gemini/antigravity-cli/settings.json`, `permissions.allow`) allow
`mcp(agy-tools/*)` and the pilot3 `reality-data` tools only; file reads and edits inside the workspace need no rule.
Briefs must say: no shell commands, use `run_check`. A refused `run_command` ends Gemini's whole turn with an empty answer (seen 8 Nov, T-105, step 343); `worker_status` then shows it under `denied_actions` and `tool_errors`, and `resume_worker` continues the work.

From a terminal: `python plugins/agy-worker/server/agy_core.py list` (or `status <job_id>`, `quota`).

Tests: `python -m pytest plugins/agy-worker/tests -q`.
