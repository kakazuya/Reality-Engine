"""MCP stdio surface for the dsh-worker plugin.

The server is intentionally small: six deterministic tools over persisted job
records.  It does not run a model, does not scrape logs for answers, and does
not append to dsh stdin.  Tool errors are returned as structured objects so
Codex can distinguish an unavailable transport from a real worker failure.
"""
from __future__ import annotations

import sys
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from core import (
    DEFAULT_RESULT_BYTES,
    Manager,
    PluginError,
    load_config,
)

INSTRUCTIONS = (
    "Local DeepSeek/dsh worker control. start_worker returns immediately with a "
    "job_id; poll worker_status rather than assuming PID liveness is progress. "
    "Use worker_result for the bounded final answer and artifact hints, never the "
    "reasoning log. message_worker kind='status' is a status nudge; kind='followup' "
    "is a genuine same-conversation question delivered to an explicit bounded wait. "
    "Both reject text over the adapter's 4000-character limit; if a call returns "
    "transport_unavailable, do not append stdin or start a second writer against "
    "the same session. cancel_worker is destructive and needs confirm=true. "
    "Default policy: one mutating worker per repository, DeepSeek V4.1 Flash at "
    "max effort, Go account 2, no peak-hour starts, no implicit hard timeout, and no "
    "secrets in briefs."
)

server = MCPServer(
    name="dsh-worker",
    version="0.1.0",
    instructions=INSTRUCTIONS,
)

_manager: Manager | None = None


def _get_manager() -> Manager:
    global _manager
    if _manager is None:
        _manager = Manager(load_config())
    return _manager


def _safe(call) -> dict[str, Any]:
    try:
        return call()
    except PluginError as exc:
        return {"ok": False, "error": exc.as_dict()}
    except Exception as exc:  # never let a stack trace become an MCP protocol failure
        return {
            "ok": False,
            "error": {
                "code": "internal_error",
                "message": f"{type(exc).__name__}: {exc}",
            },
        }


@server.tool(
    name="start_worker",
    description=(
        "Start one DeepSeek/dsh worker from a complete brief or repo-local task "
        "file. Returns promptly with job_id and persisted status/result paths. "
        "Pins deepseek-v4.1-flash, max effort, Go account 2, rejects peak starts, "
        "requires heartbeat/control capabilities, and defaults to one mutating "
        "worker per repository. Hard timeout defaults to None. "
        "followup_wait_seconds=0 keeps ordinary one-shot exit; a positive value "
        "adds a bounded host-side wait for explicit same-conversation follow-ups."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, open_world_hint=True
    ),
)
def start_worker(
    brief: str | None = None,
    task_file: str | None = None,
    workspace: str = ".",
    permission: str = "read-only",
    heartbeat_interval_seconds: int = 900,
    missed_replies: int = 2,
    max_output_tokens: int | None = None,
    max_result_bytes: int = DEFAULT_RESULT_BYTES,
    hard_timeout_seconds: int | None = None,
    followup_wait_seconds: int = 0,
    controller_lease_seconds: int = 1800,
    refresh_context: bool = True,
) -> dict[str, Any]:
    return _safe(
        lambda: _get_manager().start_worker(
            brief=brief,
            task_file=task_file,
            workspace=workspace,
            permission=permission,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            missed_replies=missed_replies,
            max_output_tokens=max_output_tokens,
            max_result_bytes=max_result_bytes,
            hard_timeout_seconds=hard_timeout_seconds,
            followup_wait_seconds=followup_wait_seconds,
            controller_lease_seconds=controller_lease_seconds,
            refresh_context=refresh_context,
        )
    )


@server.tool(
    name="worker_status",
    description=(
        "Read persisted job, process, heartbeat and session state. Distinguishes "
        "running, stale, dead/lost and finished; PID liveness is never treated as "
        "model progress. Makes no inference call."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def worker_status(job_id: str) -> dict[str, Any]:
    return _safe(lambda: _get_manager().get_status(job_id))


@server.tool(
    name="worker_result",
    description=(
        "Return a bounded final/partial answer, exit outcome, artifact hints and "
        "limits for a job. Never returns reasoning stderr or credentials."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def worker_result(job_id: str, max_bytes: int | None = None) -> dict[str, Any]:
    return _safe(lambda: _get_manager().worker_result(job_id, max_bytes))


@server.tool(
    name="message_worker",
    description=(
        "Send a status nudge or an explicit follow-up to the same running worker "
        "through dsh-heartbeat-control/1. kind='status' (default) posts to /ping "
        "and is framed as a status check; kind='followup' posts to /followup and "
        "delivers the genuine question without a status prefix. A follow-up is "
        "handed to an active bounded turn-stopping wait and steered exactly once, "
        "or steered directly while a running turn can accept it. Text over 4000 "
        "characters is rejected with message_too_long. Fails explicitly with "
        "transport_unavailable when the adapter/token is unavailable."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, open_world_hint=True
    ),
)
def message_worker(
    job_id: str,
    message: str,
    kind: str = "status",
    conversation_id: str | None = None,
) -> dict[str, Any]:
    return _safe(
        lambda: _get_manager().message_worker(
            job_id, message, kind=kind, conversation_id=conversation_id
        )
    )


@server.tool(
    name="renew_worker_lease",
    description=(
        "Explicitly extend the controller lease for a running job by at most 30 "
        "minutes. This is the only renewal path: worker activity, model calls, "
        "status/result/list reads and a restarted MCP server never renew it. "
        "Refuses finished, expired, malformed, or not-owned leases; the lease "
        "deadline remains a hard upper bound even if Codex disappears."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, open_world_hint=False
    ),
)
def renew_worker_lease(job_id: str, extend_seconds: int = 1800) -> dict[str, Any]:
    return _safe(lambda: _get_manager().renew_worker_lease(job_id, extend_seconds))


@server.tool(
    name="cancel_worker",
    description=(
        "Destructively stop a job after validating the recorded supervisor PID and "
        "kernel creation time. Requires confirm=true. Never kills by image name."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=True, open_world_hint=False
    ),
)
def cancel_worker(
    job_id: str, confirm: bool = False, reason: str = "cancelled by Codex"
) -> dict[str, Any]:
    return _safe(lambda: _get_manager().cancel_worker(job_id, confirm, reason))


@server.tool(
    name="list_workers",
    description=(
        "List persisted jobs, optionally filtered to one workspace, newest first. "
        "Read-only and bounded."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def list_workers(workspace: str | None = None, limit: int = 20) -> dict[str, Any]:
    return _safe(lambda: _get_manager().list_workers(workspace, limit))


def main() -> int:
    try:
        server.run("stdio")
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
