"""agy-worker MCP server (T-112): Claude's control panel for Antigravity CLI coding jobs, modelled on dsh-worker.
Tools: start_worker, worker_status, worker_result, list_workers, cancel_worker, quota, remove_worktree."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp.server import MCPServer  # noqa: E402

import agy_core as core  # noqa: E402

INSTRUCTIONS = (
    "Antigravity CLI (agy) coding workers, model pinned to gemini-3.8-flash-medium (Shivam's ruling). start_worker "
    "returns at once with a job_id; each job runs headless in its own Wolf-agy-<job_id> worktree and auto-commits its "
    "diff when it ends. worker_status gives done/outcome, elapsed, tool calls by tool, tokens (input, output, thinking, "
    "cache) and denied actions, parsed from the job's event log without any model call. worker_result gives the final "
    "answer, branch, head and diff stat. quota shows the account's limits left. Gemini has no shell: it runs checks "
    "through the agy-tools MCP (run_check, allowlisted pytest/ruff/basedpyright/git read commands).")
server = MCPServer(name="agy-worker", version="0.1.0", instructions=INSTRUCTIONS)


@server.tool(name="start_worker", description=(
    "Start one agy coding job from a complete prescriptive brief. use_worktree (default true) creates branch "
    "Wolf-agy-<job_id> from base (default HEAD). timeout_seconds is the hard limit (default 3600). test_cmd is "
    "recorded for the reviewer. Returns job_id at once."))
def start_worker(brief: str, use_worktree: bool = True, base: str | None = None, timeout_seconds: int = 3600,
                 test_cmd: str | None = None) -> dict[str, Any]:
    return core.start(brief, use_worktree, base, timeout_seconds, test_cmd)


@server.tool(name="resume_worker", description=(
    "Continue a finished job's own Gemini conversation in the same worktree and branch with a follow-up message "
    "(review notes, 'finish steps 2-4'). Returns a new job_id that points back with resumed_from."))
def resume_worker(job_id: str, message: str, timeout_seconds: int = 3600) -> dict[str, Any]:
    return core.resume(job_id, message, timeout_seconds)


@server.tool(name="worker_status", description="Done flag, outcome, elapsed, tool calls by tool, tokens, last tool, "
             "denied actions and tool errors of one job. No model call.")
def worker_status(job_id: str) -> dict[str, Any]:
    return core.status(job_id)


@server.tool(name="worker_result", description="Final answer text (bounded), outcome, branch, head and diff stat.")
def worker_result(job_id: str, max_bytes: int = 20000) -> dict[str, Any]:
    return core.result(job_id, max_bytes)


@server.tool(name="list_workers", description="Recent jobs, newest first: done, outcome, elapsed, tool calls, "
             "output tokens, branch.")
def list_workers(limit: int = 20) -> dict[str, Any]:
    return core.list_jobs(limit)


@server.tool(name="cancel_worker", description="Kill a job's runner and agy process tree; needs confirm=true.")
def cancel_worker(job_id: str, confirm: bool = False) -> dict[str, Any]:
    return core.cancel(job_id, confirm)


@server.tool(name="quota", description="Gemini and Claude/GPT weekly and five-hour limits left on the logged-in "
             "Google account, from `agy -p /usage`.")
def quota() -> dict[str, Any]:
    return core.quota()


@server.tool(name="remove_worktree", description="Remove a finished job's worktree; delete_branch=true also "
             "deletes its branch (only after merge or rejection).")
def remove_worktree(job_id: str, delete_branch: bool = False) -> dict[str, Any]:
    return core.remove_worktree(job_id, delete_branch)


if __name__ == "__main__":
    server.run("stdio")
