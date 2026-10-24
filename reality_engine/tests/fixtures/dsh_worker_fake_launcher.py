"""Deterministic offline stand-in for run_deepseek_harness.py in plugin tests.

It never imports dsh, never reads credentials, and never calls a model.  Test
code copies this file into a temporary fake repository and selects behavior
with environment variables.  The heartbeat/control shapes mirror the landed
``dsh-heartbeat-status/1`` and ``dsh-heartbeat-control/1`` contracts.
"""
from __future__ import annotations

import http.server
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONTROL_SCHEMA = "dsh-heartbeat-control/1"
STATUS_SCHEMA = "dsh-heartbeat-status/1"
CONVERSATION = "conv-test-1"
RUN_ID = "fake-run-1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _value(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        index = args.index(flag) + 1
        if index < len(args):
            return args[index]
    return default


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    for attempt in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows readers may briefly hold the destination open.
            time.sleep(min(0.02 * (attempt + 1), 0.1))
    os.replace(tmp, path)


def _status(
    status_path: Path,
    *,
    state: str,
    conversation: str,
    control: dict | None,
    pings: list[dict] | None = None,
    exit_code: int | None = None,
    failure: str | None = None,
    failure_detail: str | None = None,
    partial: bool = False,
) -> None:
    activity_at = os.environ.get("FAKE_LAUNCHER_ACTIVITY_AT") or _now()
    _atomic(
        status_path,
        {
            "schema": STATUS_SCHEMA,
            "run_id": RUN_ID,
            "state": state,
            "exit_code": exit_code,
            "failure": failure,
            "failure_detail": failure_detail,
            "partial": partial,
            "started_at": _now(),
            "ended_at": _now() if state in {"completed", "failed"} else None,
            "duration_seconds": 0.1,
            "pid": os.getpid(),
            "model": "deepseek-v4.1-flash",
            "reasoning_effort": "xhigh",
            "account": "2",
            "permission": "workspace-write",
            "cwd": os.getcwd(),
            "provider_routing_session_id": "provider-session-test",
            "dsh_conversation_id": conversation,
            "control": control
            or {
                "schema": CONTROL_SCHEMA,
                "host": None,
                "port": None,
                "endpoint_file": None,
                "session_id": None,
                "listener_closed": None,
            },
            "heartbeat": {
                "enabled": True,
                "idle_seconds": 900,
                "response_window_seconds": 900,
                "max_unanswered": 2,
                "hard_timeout_seconds": None,
                "last_activity_at": activity_at,
                "last_activity_kind": "text",
                "current_idle_seconds": 0,
                "consecutive_unanswered": 0,
                "activity_count": 1,
                "pings": pings or [],
                "events": [],
            },
            "counters": {"stdout_events": 0, "worker_activity": 1},
            "outputs": {},
        },
    )


def _control_server(job_dir: Path, status_path: Path, conversation: str, token: str) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def _reply(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.headers.get("Origin"):
                self._reply(403, {"ok": False, "error": "origin-not-allowed"})
                return
            if self.path not in {"/ping", "/followup"}:
                self._reply(404, {"ok": False, "error": "not-found"})
                return
            if self.headers.get("X-DSH-Heartbeat-Token") != token:
                self._reply(403, {"ok": False, "error": "token-mismatch"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(min(length, 65_536)).decode("utf-8"))
            except (ValueError, UnicodeError, json.JSONDecodeError):
                self._reply(400, {"ok": False, "error": "invalid-json"})
                return
            if payload.get("run_id") != RUN_ID:
                self._reply(403, {"ok": False, "error": "run-mismatch"})
                return
            if payload.get("session_id") and payload["session_id"] != conversation:
                self._reply(409, {"ok": False, "error": "session-mismatch"})
                return
            message = payload.get("message")
            if not isinstance(message, list) or not any(
                isinstance(block, dict) and block.get("type") == "text" and block.get("text")
                for block in message
            ):
                self._reply(400, {"ok": False, "error": "empty-message"})
                return
            target = "followup.json" if self.path == "/followup" else "nudge.json"
            (job_dir / target).write_text(
                json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
            )
            self._reply(
                200,
                {
                    "ok": True,
                    "queued": True,
                    "worker_response": False,
                    "session_id": conversation,
                    "agent_status": "working",
                    "kind": "followup" if self.path == "/followup" else "status",
                    "delivered": "awaiting-turn" if self.path == "/followup" else "steered",
                },
            )

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state = os.environ.get("FAKE_CONTROL_STATE", "bound")
    awaiting = state == "awaiting-input"
    control = {
        "schema": CONTROL_SCHEMA,
        "state": state,
        "host": "127.0.0.1",
        "port": server.server_port,
        "pid": os.getpid(),
        "run_id": RUN_ID,
        "session_id": conversation,
        "agent_status": "working",
        "awaiting_input": awaiting,
        "followup_deadline": (
            (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(timespec="seconds")
            if awaiting else None
        ),
        "started_at": _now(),
        "updated_at": _now(),
        "closed_at": None,
    }
    _atomic(job_dir / "result.md.control.json", control)
    _status(status_path, state="running", conversation=conversation, control=control)


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args:
        print(
            "usage: fake_launcher --model M --task-file T --out-file O --cwd C "
            "--timeout S --account 2 --permission P --allow-paid "
            "--max-output-tokens N --no-refresh"
        )
        if os.environ.get("FAKE_HEARTBEAT_FLAGS") == "1":
            print(
                "--heartbeat-interval S --heartbeat-response-window S "
                "--heartbeat-misses N --status-file F"
            )
            if os.environ.get("FAKE_NO_CONTROL_TOKEN_FLAG") != "1":
                print("--control-token-env NAME")
        return 0

    out = Path(str(_value(args, "--out-file")))
    job_dir = out.parent
    job_dir.mkdir(parents=True, exist_ok=True)
    task_file = _value(args, "--task-file")
    record = {
        "argv": args,
        "cwd": os.getcwd(),
        "task": Path(str(task_file)).read_text(encoding="utf-8") if task_file else "",
        "env_job_dir": os.environ.get("DSH_WORKER_JOB_DIR"),
        "env_progress_notes": os.environ.get("DSH_WORKER_PROGRESS_NOTES"),
        "env_reality_data_root": os.environ.get("REALITY_DATA_ROOT"),
    }
    (job_dir / "launcher_argv.json").write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
    )

    # Simulate a worker writing into its workspace (--cwd), never the runtime.
    write_name = os.environ.get("FAKE_LAUNCHER_WRITE_FILE")
    if write_name:
        target = Path(str(_value(args, "--cwd") or os.getcwd())) / write_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            os.environ.get("FAKE_LAUNCHER_WRITE_TEXT", "fake worker change\n"),
            encoding="utf-8",
        )

    mode = os.environ.get("FAKE_LAUNCHER_MODE", "fast")
    sleep_seconds = float(os.environ.get("FAKE_LAUNCHER_SLEEP", "5"))
    output = os.environ.get("FAKE_LAUNCHER_OUTPUT", "fake final answer")
    partial = os.environ.get("FAKE_LAUNCHER_PARTIAL", "partial output\n")
    status_file = _value(args, "--status-file")
    status_path = Path(status_file) if status_file else out.with_name(out.name + ".status.json")
    token_env = _value(args, "--control-token-env")
    token = os.environ.get(token_env) if token_env else os.environ.get("DSH_HEARTBEAT_TOKEN")

    heartbeat_mode = any(flag in args for flag in ("--heartbeat-interval", "--heartbeat-misses"))
    if heartbeat_mode:
        _status(status_path, state="starting", conversation=CONVERSATION, control=None)
    if mode == "control" or os.environ.get("FAKE_CONTROL") == "1":
        if not token:
            print("fake launcher: control mode requires a token env", file=sys.stderr)
            return 2
        _control_server(job_dir, status_path, CONVERSATION, token)
    elif heartbeat_mode:
        _status(status_path, state="running", conversation=CONVERSATION, control=None)

    events_path = out.with_name(out.name + ".events.jsonl")
    if os.environ.get("FAKE_LAUNCHER_EVENTS") == "1":
        lines = [
            {"type": "session", "sessionId": "session-fake"},
            {"type": "status", "phase": "turn_start", "turn": 1},
            {"type": "thinking", "text": "secret thinking must not be returned"},
            {"type": "tool_call", "callId": "c1", "tool": "read", "input": {"file_path": "tasks/FRAMEWORK.md"}},
            {"type": "tool_result", "callId": "c1", "status": "completed", "result": "x"},
            {"type": "tool_call", "callId": "c2", "tool": "pwsh",
             "input": {"command": "Get-Secret -Value hunter2", "description": "list files"}},
            {"type": "tool_result", "callId": "c2", "status": "error", "result": "boom"},
            {"type": "tool_call", "callId": "c3", "tool": "write", "input": {"file_path": "out/report.md", "content": "c"}},
            {"type": "text", "text": "Implemented the fake change.\nRunning the tests now."},
            {"type": "status", "phase": "step_end", "usage": {"inputTokens": 100, "outputTokens": 42}},
        ]
        with events_path.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line) + chr(10))
            fh.write('{"type": "tool_call", "tool": "edit", "inp')  # half-written trailing line
    stderr_text = os.environ.get("FAKE_LAUNCHER_STDERR")
    if stderr_text:
        print(stderr_text, file=sys.stderr)
        return int(os.environ.get("FAKE_LAUNCHER_RC", "1"))
    if mode == "fail":
        print("dsh: reasoning: secret reasoning must not be returned", file=sys.stderr)
        out.write_text(partial, encoding="utf-8")
        if heartbeat_mode:
            _status(
                status_path,
                state="failed",
                conversation=CONVERSATION,
                control=None,
                exit_code=3,
                failure="fake_failure",
                failure_detail="fake failure detail",
                partial=True,
            )
        return 3

    if mode in {"slow", "control", "heartbeat"}:
        out.write_text(partial, encoding="utf-8")
        deadline = time.monotonic() + max(0.0, sleep_seconds)
        while time.monotonic() < deadline:
            if heartbeat_mode:
                _status(status_path, state="running", conversation=CONVERSATION, control=None)
            time.sleep(0.2)
    out.write_text(output, encoding="utf-8")
    if heartbeat_mode:
        _status(status_path, state="completed", conversation=CONVERSATION, control=None, exit_code=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
