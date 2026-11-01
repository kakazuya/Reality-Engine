# Task: dsh-worker MCP — automatic progress reports every 20 min, without interrupting the worker

Owner: Shivam (2026-10-24): "add this functionality in the MCP itself, so it forces the dsh-worker to report a status
update every 20 mins without stopping on the task". Reviewer: Claude.

## Why

Today a `message_worker kind=status` ping made a worker answer it as its final result and exit early (job
20261024T154434Z-b952dbc2). Claude now polls `list_workers` on a session-only cron. The supervisor should produce
progress itself, model-free, so updates exist even with no Claude session open and never touch the worker's turn.

## Build (plugins/dsh-worker/server/ — read core.py, the supervisor, jobs.py, and the existing progress/events code
that computes tool_calls / model_steps / output_tokens / recent_file_writes / last_tool from result.md.events.jsonl)

1. **Supervisor progress digests.** Every `progress_interval_seconds` (default 1200, start_worker/start_job param,
   0 = off) the supervisor appends one JSON line to `<job_dir>/progress.jsonl` and rewrites `<job_dir>/progress.md`
   (latest + last 6 entries): timestamp, phase, elapsed, tool calls (total + by tool, delta since last digest),
   model steps, output tokens, last tool + target, files written since last digest, idle seconds, lease time left,
   a stall flag (no activity > 20 min), and the last 3 lines of the worker's own text output if any. Computed from the
   events file incrementally (remember byte offset; never re-read the whole file). Also on finish: a final digest.
   No model calls, no messages into the worker's conversation.
2. **Worker self-notes (optional, cooperative).** Append to every brief a short standing instruction: "Every ~20
   minutes of work, or at each milestone, append one line to PROGRESS_NOTES.md in your job dir: what's done, what's
   next, blockers. Do not stop or wait after writing it." Expose the path via an env var. The digest includes the
   latest note. This must never be phrased as a question to answer.
3. **MCP tool `worker_progress(job_id=None, since=None)`**: returns the digests (all running jobs when job_id is None),
   newest first, compact. `list_workers` rows gain `last_digest_at` + one-line digest summary.
4. **Status line for humans:** the DeepSeek workers pane mod (`plugins/dsh-workers-pane`) can read progress.jsonl —
   add `progress.jsonl` to what its rows read if cheap (optional, separate commit).
5. Make `message_worker kind="status"` safer: its delivered text is prefixed "Status check — answer in one line,
   then continue your task; this is not the end of your task." (keep the existing transport).

## Tests

Unit tests in the existing dsh-worker test suite: digest cadence with a fake clock, incremental offset resume,
stall flag, final digest on finish, progress_interval 0 disables, worker_progress output shape, status-ping prefix.
Run the full dsh-worker suite (it was 66 tests at phase 2). Update the README.

Final answer: what changed, sample progress.md from a short live demo job, test output.
