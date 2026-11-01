"""MCP stdio surface for the dsh-worker plugin.

The server is intentionally small: deterministic tools over persisted job
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
    DEFAULT_PROGRESS_INTERVAL_SECONDS,
    DEFAULT_RESULT_BYTES,
    Manager,
    PluginError,
    SERVER_VERSION,
    load_config,
)

INSTRUCTIONS = (
    "Local DeepSeek/dsh worker control. start_worker returns immediately with a "
    "job_id; do not poll in a loop - worker_status defaults to one compact view "
    "(phase, done, succeeded, one-line summary, tool calls, lease seconds left) "
    "and worker_result to outcome/exit/content/branch/head/changed-file count; "
    "pass verbose=true for the full record. worker_status.done (verbose: "
    "progress.done) is the reliable finished flag (result.md is streamed while "
    "running, so a non-empty file is NOT completion). To wait on a long run, "
    "start it detached and make ONE blocking call (a harness job_output with "
    "wait=true, or a host-side wait on process exit/a file) instead of sleeping "
    "in a loop. "
    "inspect_run gives the same read-only view of a run launched with the raw "
    "harness. Use worker_result for the bounded final answer, never the "
    "reasoning log. The supervisor also writes model-free progress digests "
    "(progress.jsonl/progress.md) every progress_interval_seconds (default 1200, "
    "0=off); read them with worker_progress instead of pinging a running worker. "
    "message_worker kind='status' is a status nudge prefixed 'Status check — answer "
    "in one line, then continue your task; this is not the end of your task.'; "
    "kind='followup' "
    "is a genuine same-conversation question delivered to an explicit bounded wait. "
    "Both reject text over the adapter's 4000-character limit; if a call returns "
    "transport_unavailable, do not append stdin or start a second writer against "
    "the same session. cancel_worker is destructive and needs confirm=true. "
    "Session independence: each server has a session_label and the per-job control "
    "token is persisted DPAPI-encrypted for this Windows user, so any dsh-worker "
    "server can list/message/cancel a job; claim_worker takes lease ownership. "
    "HP jobs have no control channel: message_worker returns not_supported_on_hp. "
    "worktree jobs (start_worker use_worktree=true) create dsh/<job_id> in "
    "DSH_WORKTREES_ROOT, auto-commit on success, and on any ended outcome (failed, "
    "cancelled, lease-expired) commit a non-empty diff with the subject prefix "
    "'WIP ended <reason>:', and read gitignored data from "
    "REALITY_DATA_ROOT read-only. merge_worker merges a finished worktree branch "
    "into the checked-out target under a repo-wide merge lock, runs its declared "
    "test command (or a compile-only default), and rolls the target back if tests "
    "fail; conflicts are reported and aborted cleanly. push refuses unless "
    "confirm=true and only after Shivam's explicit go-ahead. Data jobs come from "
    "jobs.yaml: list_jobs reports run history and a live read-only SQL freshness "
    "check, start_job runs them through the same supervisor/lease/steering "
    "machinery with named db:/gpu/net: resource locks (every job ships disabled; "
    "confirm=true is required), and job_log returns bounded stdout/stderr tails. "
    "Default policy: one mutating worker per workspace/checkout (each worktree has "
    "its own lock), DeepSeek V4.1 Flash at max effort, Go account 2, no peak-hour "
    "starts, a 4-hour hard timeout by default, and no secrets in briefs."
)

server = MCPServer(
    name="dsh-worker",
    version=SERVER_VERSION,
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


# The default views are the ones a controller reads on every step; the full
# record is behind verbose=true.  Keep these under 1,000 chars (status) and
# 800 chars plus the answer (result).
def _compact_status(status: dict[str, Any]) -> dict[str, Any]:
    progress_view = status.get("progress") or {}
    events = progress_view.get("events") or {}
    reason = status.get("failure_reason")
    if isinstance(reason, dict):
        tail = reason.get("launcher_stderr_tail") or []
        reason = {
            "likely_cause": reason.get("likely_cause"),
            "detail": str(tail[-1])[:200] if tail else None,
        }
    return {
        "ok": status.get("ok", True),
        "job_id": status.get("job_id"),
        "host": status.get("host") or "msi",
        "phase": status.get("phase"),
        "done": progress_view.get("done", status.get("final")),
        "succeeded": progress_view.get("succeeded"),
        "summary": progress_view.get("summary"),
        "tool_calls": events.get("tool_calls"),
        "tool_calls_before_first_edit": progress_view.get("tool_calls_before_first_edit"),
        "lease_seconds_left": progress_view.get("controller_lease_remaining_seconds"),
        "hp": (
            {
                "reachable": (status.get("hp") or {}).get("reachable"),
                "last_seen": (status.get("hp") or {}).get("last_seen"),
                "host_address": (status.get("hp") or {}).get("host_address"),
            }
            if status.get("host") == "hp"
            else None
        ),
        "failure_reason": reason,
    }


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok", True):
        return result
    worktree = result.get("worktree") or {}
    return {
        "ok": True,
        "job_id": result.get("job_id"),
        "host": result.get("host") or "msi",
        "outcome": result.get("outcome"),
        "exit_code": result.get("exit_code"),
        "content": result.get("content"),
        "truncated": result.get("truncated"),
        "result_bytes": result.get("result_bytes"),
        "worktree": (
            {
                "branch": worktree.get("branch"),
                "head": worktree.get("head"),
                "changed_files": worktree.get("files_changed"),
            }
            if worktree.get("enabled")
            else None
        ),
    }


def _compact_jobs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "job_id": row.get("job_id"),
            "host": row.get("host") or "msi",
            "phase": row.get("phase"),
            "line": row.get("digest_summary") or row.get("summary"),
        }
        for row in rows
    ]


@server.tool(
    name="start_worker",
    description=(
        "Start one DeepSeek/dsh worker from a complete brief or repo-local task "
        "file. Returns promptly with job_id and persisted status/result paths. "
        "Pins deepseek-v4.1-flash, max effort, Go account 2, rejects peak starts, "
        "requires heartbeat/control capabilities, and allows one mutating worker "
        "per workspace (the main checkout and each worktree have their own lock). "
        "The per-job control token is persisted DPAPI-encrypted for this Windows "
        "user, so other dsh-worker servers can message/renew/cancel this job. "
        "Use use_worktree=true to create <DSH_WORKTREES_ROOT>/<job_id> on branch "
        "dsh/<job_id> from base (default HEAD); the supervisor auto-commits a "
        "non-empty diff when the worker finishes successfully. test_cmd is the "
        "command merge_worker runs later for this job. hard_timeout_seconds "
        "defaults to 4 hours (14400 s) for MSI jobs and is the real limit; the "
        "supervisor renews the controller lease itself while the worker lives. "
        "followup_wait_seconds=0 keeps ordinary one-shot exit; "
        "a positive value adds a bounded host-side wait for explicit "
        "same-conversation follow-ups. progress_interval_seconds (default 1200, "
        "0=off) is the supervisor's model-free progress-digest cadence; every "
        "brief gets a standing instruction to append one line to PROGRESS_NOTES.md. "
        "write_scope='workspace' (default) writes only the workspace + its .tmp; "
        "'data' additionally approves REALITY_DATA_ROOT and D:\\RealityEngine for "
        "an approved data job and needs confirm_data_write=true plus a non-empty "
        "writes=[db files] (refused as writes_required otherwise; the supervisor "
        "holds db:<file> locks so two writers never share a DB); 'full' disables "
        "the dsh file sandbox and needs confirm_full_access=true after Shivam's "
        "approval. dsh 0.2.1 runs both data and full as danger-full-access, so the "
        "OS sandbox does not separate them: the named DB locks and the brief are "
        "the real scope. approved_by records who approved a data/full job. The "
        "supervisor creates <workspace>/.tmp and points TMP/TEMP/caches at it. "
        "context_pack (default true) prepends the generated "
        "tasks/worker_context/CONTEXT.md path + standing header to the brief and "
        "regenerates the pack when it is older than 26 h (bounded 60 s; failure is "
        "a warning); pass context_pack=false to opt out. The path is the main "
        "checkout's, so a worktree worker gets the same pack by absolute path. "
        "Briefs must carry six labelled fields Goal:, Files:, Accept: (or Test "
        "command(s):), Stop if:, Budget: and Ticket: (or No-ticket: <reason>); a "
        "start missing any is refused as "
        "brief_incomplete (small_fix=true allows a one-line brief with an accept "
        "command). A Ticket naming an id absent from the main checkout's "
        "tasks/TASKS.md is refused as ticket_unknown, and the worker's brief then "
        "carries that one row. "
        "permission is required on every start (read-only, "
        "workspace-write or danger-full-access); there is no default and a start "
        "without it is refused as permission_required. A mutating worker whose "
        "workspace is "
        "the main checkout root needs confirm_repo_root_write=true (refused as "
        "repo_root_write_requires_confirmation otherwise): such a worker can "
        "rewrite code that later runs unsandboxed (the context-pack builder, "
        "supervisor.py, .git/config, other jobs' records). Read-only and worktree "
        "workers are unaffected. host='hp' routes the start to hp_worker.py on "
        "the HP OmniBook (Go account 1 by default; account overrides it) and "
        "ignores workspace/use_worktree/write_scope: the HP checkout is C:\\RE. "
        "HP jobs get the same peak-hour refusal and a lease-like hard stop "
        "(hard_timeout_seconds defaults to 1800). dbs names the DB files to "
        "mirror read-only to the HP for this job."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, open_world_hint=True
    ),
)
def start_worker(
    brief: str | None = None,
    task_file: str | None = None,
    workspace: str = ".",
    permission: str | None = None,
    small_fix: bool = False,
    write_scope: str = "workspace",
    confirm_data_write: bool = False,
    confirm_full_access: bool = False,
    confirm_repo_root_write: bool = False,
    writes: list[str] | None = None,
    approved_by: str | None = None,
    heartbeat_interval_seconds: int = 900,
    missed_replies: int = 2,
    max_output_tokens: int | None = None,
    max_result_bytes: int = DEFAULT_RESULT_BYTES,
    hard_timeout_seconds: int | None = None,
    followup_wait_seconds: int = 0,
    controller_lease_seconds: int = 1800,
    refresh_context: bool = True,
    context_pack: bool = True,
    use_worktree: bool = False,
    base: str | None = None,
    test_cmd: str | None = None,
    progress_interval_seconds: int = DEFAULT_PROGRESS_INTERVAL_SECONDS,
    host: str = "msi",
    dbs: list[str] | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    return _safe(
        lambda: _get_manager().start_worker(
            brief=brief,
            task_file=task_file,
            workspace=workspace,
            permission=permission,
            small_fix=small_fix,
            write_scope=write_scope,
            confirm_data_write=confirm_data_write,
            confirm_full_access=confirm_full_access,
            confirm_repo_root_write=confirm_repo_root_write,
            writes=writes,
            approved_by=approved_by,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            missed_replies=missed_replies,
            max_output_tokens=max_output_tokens,
            max_result_bytes=max_result_bytes,
            hard_timeout_seconds=hard_timeout_seconds,
            followup_wait_seconds=followup_wait_seconds,
            controller_lease_seconds=controller_lease_seconds,
            refresh_context=refresh_context,
            context_pack=context_pack,
            use_worktree=use_worktree,
            base=base,
            test_cmd=test_cmd,
            progress_interval_seconds=progress_interval_seconds,
            host=host,
            dbs=dbs,
            account=account,
        )
    )


@server.tool(
    name="worker_status",
    description=(
        "Compact job view by default (under 1,000 chars): phase, done, "
        "succeeded, one-line summary, tool-call counts, lease seconds left and "
        "failure reason. done is the finished flag; PID liveness is never model "
        "progress. verbose=true returns the full record: persisted process / "
        "heartbeat / session state, running vs stale/dead/lost/unknown, owner "
        "and worktree branch/base/head/commits/changed-file paths, resource "
        "locks, limits and paths. Makes no inference call."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def worker_status(job_id: str, verbose: bool = False) -> dict[str, Any]:
    if verbose:
        return _safe(lambda: _get_manager().get_status(job_id, hp_refresh=True))
    status = _safe(lambda: _get_manager().get_status(job_id, hp_refresh=True))
    return status if not status.get("ok", True) else _safe(lambda: _compact_status(status))


@server.tool(
    name="worker_result",
    description=(
        "Return the bounded final/partial answer in a compact envelope (under "
        "800 chars plus content): outcome, exit code, content, worktree branch "
        "and head, changed-file count. verbose=true adds paths, artifacts, "
        "heartbeat, limits, warnings and the full worktree record. Never "
        "returns reasoning stderr or credentials."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def worker_result(
    job_id: str, max_bytes: int | None = None, verbose: bool = False
) -> dict[str, Any]:
    if verbose:
        return _safe(lambda: _get_manager().worker_result(job_id, max_bytes))
    result = _safe(lambda: _get_manager().worker_result(job_id, max_bytes))
    return result if not result.get("ok", True) else _safe(lambda: _compact_result(result))


@server.tool(
    name="message_worker",
    description=(
        "Send a status nudge or an explicit follow-up to the same running worker "
        "through dsh-heartbeat-control/1. kind='status' (default) posts to /ping "
        "and the delivered text is prefixed 'Status check — answer in one line, "
        "then continue your task; this is not the end of your task.' so the ping "
        "is never answered as the final result; kind='followup' posts to /followup "
        "and delivers the genuine question without a status prefix. A follow-up is "
        "handed to an active bounded turn-stopping wait and steered exactly once, "
        "or steered directly while a running turn can accept it. Text over 4000 "
        "characters is rejected with message_too_long. Works from any dsh-worker "
        "server of this Windows user: the per-job control token is persisted "
        "DPAPI-encrypted and the attempt is appended to job_dir/steering.jsonl. "
        "Fails explicitly with transport_unavailable when the adapter is not ready "
        "or a legacy job has no persisted token, and with not_supported_on_hp for "
        "an HP job (those have no control channel)."
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
        "Explicitly extend the controller lease for a running job by at most 7200 "
        "seconds (2 hours; default 1800). The supervisor renews the lease itself "
        "while the worker lives, so this is only for ownership/takeover or an "
        "explicit controller extension; the job's hard_timeout_seconds is the real "
        "limit. Renewal works for the recorded owner session; after a restart pass "
        "adopt=true to take the still-valid lease over explicitly, or call "
        "claim_worker first (an expired lease cannot be adopted). Refuses finished, "
        "expired, malformed, or not-owned leases."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, open_world_hint=False
    ),
)
def renew_worker_lease(
    job_id: str, extend_seconds: int = 1800, adopt: bool = False
) -> dict[str, Any]:
    return _safe(lambda: _get_manager().renew_worker_lease(job_id, extend_seconds, adopt=adopt))


@server.tool(
    name="claim_worker",
    description=(
        "Take over ownership of a running job's controller lease and record who "
        "and why in job_dir/steering.jsonl. The stable lease owner id is kept (the "
        "supervisor validates it); the recorded owner session becomes this server, "
        "so subsequent renew_worker_lease calls need no adopt=true. Works from any "
        "dsh-worker MCP server of this Windows user because the job's control token "
        "is persisted DPAPI-encrypted. Refuses finished jobs."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, open_world_hint=False
    ),
)
def claim_worker(job_id: str, reason: str = "manual claim") -> dict[str, Any]:
    return _safe(lambda: _get_manager().claim_worker(job_id, reason))


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
        "List persisted jobs (default 5, running first then newest started), "
        "optionally filtered to "
        "one workspace: one short line each (job_id, phase, latest digest or "
        "summary). verbose=true returns the full rows with owner session, "
        "steerer, worktree branch, paths and digest fields. Read-only."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def list_workers(
    workspace: str | None = None, limit: int = 5, verbose: bool = False
) -> dict[str, Any]:
    if verbose:
        return _safe(lambda: _get_manager().list_workers(workspace, limit))
    listing = _safe(lambda: _get_manager().list_workers(workspace, limit))
    if not listing.get("ok", True):
        return listing
    listing["jobs"] = _compact_jobs(listing.get("jobs") or [])
    return listing


@server.tool(
    name="worker_progress",
    description=(
        "Return the supervisor's model-free progress digests, newest first. "
        "Omit job_id to read every running job. Each digest has timestamp, "
        "phase, elapsed, tool calls (total, by tool, delta), model steps, "
        "output tokens, last tool and target, files written since the previous "
        "digest, idle seconds, lease time left, a stall flag (no activity for "
        "more than 20 minutes), the worker's last 3 committed text lines and "
        "the latest PROGRESS_NOTES.md line. since accepts an ISO-8601 timestamp "
        "or a duration like 30m or 2h. Read-only; no model call, and nothing is "
        "sent into the worker's conversation."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def worker_progress(
    job_id: str | None = None, since: str | None = None
) -> dict[str, Any]:
    return _safe(lambda: _get_manager().worker_progress(job_id, since))


@server.tool(
    name="inspect_run",
    description=(
        "Read-only progress view of a dsh run started with the raw "
        "run_deepseek_harness.py (not start_worker), given its --out-file path "
        "inside the repository (or its .status.json/.events.jsonl). Returns phase, "
        "PID check (creation time verified), last activity, tool-call counts, last "
        "tool, recent file writes and failure reason. Cannot message, renew or "
        "cancel such runs: their control token never reaches this server."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def inspect_run(out_file: str) -> dict[str, Any]:
    return _safe(lambda: _get_manager().inspect_run(out_file))


@server.tool(
    name="server_info",
    description=(
        "Liveness/config check for this MCP server: version, process id, start "
        "time, repository root, runtime directory and whether the launcher "
        "advertises the heartbeat/control contract. Makes no inference call."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def server_info() -> dict[str, Any]:
    return _safe(lambda: _get_manager().server_info())


@server.tool(
    name="merge_worker",
    description=(
        "Merge a finished worktree job's dsh/<job_id> branch into target (default "
        "main) from the checked-out main checkout, under a repo-wide merge lock. "
        "Refuses when the target is not checked out, has a merge in progress, or "
        "has local changes to files the branch touches. Uses git merge --no-ff "
        "with a DSH-Job trailer; uses mergiraf as a per-command merge driver only "
        "when it is already on PATH. Runs test_cmd (or the job's declared test "
        "command, or a compile-only quick suite); on failure the target is reset "
        "to its pre-merge HEAD. On conflict it runs merge --abort and returns the "
        "conflicted files and hunk summaries with the target clean. Never pushes."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, open_world_hint=False
    ),
)
def merge_worker(
    job_id: str,
    target: str = "main",
    run_tests: bool = True,
    test_cmd: str | None = None,
) -> dict[str, Any]:
    return _safe(
        lambda: _get_manager().merge_worker(
            job_id, target=target, run_tests=run_tests, test_cmd=test_cmd
        )
    )


@server.tool(
    name="remove_worktree",
    description=(
        "Remove a finished job's worktree with a safe git worktree remove (it "
        "refuses when the worktree is dirty). delete_branch=true also deletes the "
        "merged branch with git branch -d; unmerged branches are reported, not "
        "forced."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, open_world_hint=False
    ),
)
def remove_worktree(job_id: str, delete_branch: bool = False) -> dict[str, Any]:
    return _safe(lambda: _get_manager().remove_worktree(job_id, delete_branch))


@server.tool(
    name="push",
    description=(
        "Push target to origin. Refuses unless confirm=true; only pass confirm=true "
        "on Shivam's explicit go-ahead. Never forces or pushes tags automatically."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=True, open_world_hint=True
    ),
)
def push(target: str = "main", confirm: bool = False) -> dict[str, Any]:
    return _safe(lambda: _get_manager().push(target, confirm))


@server.tool(
    name="list_jobs",
    description=(
        "List the jobs.yaml data-job registry with last run/last successful run "
        "from job history, a live read-only SQL freshness check (max-date or "
        "minimum-count rule), staleness against cadence, never-ran flag, enabled "
        "state, resource locks and paid/GPU/freshness metadata. Read-only; no job "
        "is started."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def list_jobs() -> dict[str, Any]:
    return _safe(lambda: _get_manager().list_jobs())


@server.tool(
    name="start_job",
    description=(
        "Start one data job from jobs.yaml through the same supervisor/status/"
        "lease/steering machinery as workers. Jobs ship enabled=false; a disabled "
        "job requires confirm=true (re-enable only on Shivam's word). Takes named "
        "resource locks (db:<file>, gpu, net:<host>) so two jobs never share one; "
        "refuses with resource_busy otherwise. args are extra argv entries. No "
        "paid/GPU/off-peak job starts without confirm=true during a restricted "
        "window. progress_interval_seconds (default 1200, 0=off) is the same "
        "model-free progress-digest cadence as start_worker. Returns run_id "
        "(the job_id); read job_log for output and worker_progress for digests."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, open_world_hint=True
    ),
)
def start_job(
    name: str,
    args: list[str] | None = None,
    confirm: bool = False,
    progress_interval_seconds: int = DEFAULT_PROGRESS_INTERVAL_SECONDS,
) -> dict[str, Any]:
    return _safe(
        lambda: _get_manager().start_job(
            name,
            args=args,
            confirm=confirm,
            progress_interval_seconds=progress_interval_seconds,
        )
    )


@server.tool(
    name="job_log",
    description=(
        "Return the last `tail` lines (1..2000) of a data job run's stdout, stderr "
        "and supervisor log. run_id is a run/job id, or a jobs.yaml job name to "
        "resolve to its newest run. Bounded and read-only."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def job_log(run_id: str, tail: int = 200) -> dict[str, Any]:
    return _safe(lambda: _get_manager().job_log(run_id, tail))


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
