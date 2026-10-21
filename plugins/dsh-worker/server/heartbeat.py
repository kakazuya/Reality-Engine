"""Integration with the dsh heartbeat supervisor's actual control contract.

The heartbeat worker owns the launcher format.  Verified against the landed
sources:

* status: ``<out>.status.json`` with schema ``dsh-heartbeat-status/1``
* control: ``<out>.control.json`` with schema ``dsh-heartbeat-control/1``
* ping: ``POST /ping`` with ``X-DSH-Heartbeat-Token`` and a body containing
  ``run_id``, ``ping_id``, ``sequence``, ``session_id`` and a text-block
  ``message`` array
* acknowledgement: HTTP 200 with ``ok``/``queued``; ``worker_response`` is false

The plugin passes a per-job token to the launcher through
``--control-token-env DSH_WORKER_CONTROL_TOKEN``.  The token exists only in the
MCP server process and the supervisor/launcher/dsh environment; it is never
written to a manifest, job record, status file, control descriptor, or argv.
"""
from __future__ import annotations

import http.client
import json
import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import procutil
from store import read_json_bounded

STATUS_SCHEMA = "dsh-heartbeat-status/1"
CONTROL_SCHEMA = "dsh-heartbeat-control/1"
HEARTBEAT_FLAGS = ("--heartbeat-interval", "--heartbeat-misses", "--status-file")
MAX_DESCRIPTOR_BYTES = 65_536
MAX_MESSAGE_BYTES = 32_768
MAX_CONTROL_RESPONSE_BYTES = 32_768
MAX_ACTIVITY_ITEMS = 20
CONTROL_TOKEN_ENV = "DSH_WORKER_CONTROL_TOKEN"
# dsh_heartbeat_control.mjs does `message.slice(0, 4000)` before steering, so a
# longer manual nudge would be silently truncated.  Count UTF-16 code units to
# match JavaScript's string length, not Python code points.
MAX_ADAPTER_MESSAGE_CHARS = 4000


def adapter_message_length(message: str) -> int:
    return len(message.encode("utf-16-le", errors="replace")) // 2


def message_length_error(message: str) -> str | None:
    length = adapter_message_length(message)
    if length <= MAX_ADAPTER_MESSAGE_CHARS:
        return None
    return (
        f"message is {length} characters (UTF-16 units); the dsh-heartbeat control "
        f"adapter silently truncates at {MAX_ADAPTER_MESSAGE_CHARS}. Shorten it "
        "before sending; no text was transmitted."
    )


@dataclass(frozen=True)
class LauncherCapabilities:
    flags: frozenset[str]
    help_error: str | None = None

    @property
    def heartbeat_supported(self) -> bool:
        return all(flag in self.flags for flag in HEARTBEAT_FLAGS)

    @property
    def control_token_supported(self) -> bool:
        return "--control-token-env" in self.flags

    def as_dict(self) -> dict[str, Any]:
        return {
            "heartbeat_supported": self.heartbeat_supported,
            "control_token_supported": self.control_token_supported,
            "help_error": self.help_error,
        }


def probe_launcher(launcher_cmd: list[str], cwd: Path, env: dict[str, str]) -> LauncherCapabilities:
    """Ask the launcher for its real flags.  Never raises into start_worker."""
    try:
        completed = subprocess.run(
            [*launcher_cmd, "--help"],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return LauncherCapabilities(frozenset(), f"{type(exc).__name__}: {exc}")
    text = (completed.stdout or "") + "\n" + (completed.stderr or "")
    flags = frozenset(token.rstrip(",") for token in text.split() if token.startswith("--"))
    return LauncherCapabilities(flags, None)


def heartbeat_launch_args(
    capabilities: LauncherCapabilities,
    job_dir: Path,
    interval_seconds: int,
    missed_replies: int,
) -> tuple[list[str], dict[str, Any]]:
    """Return launcher args and the heartbeat mode record.

    There is deliberately no fallback mode: a launcher without the heartbeat
    flags is refused by ``start_worker`` rather than silently given a wall-clock
    kill.  An explicit ``--timeout`` remains available separately.
    """
    missing = [flag for flag in HEARTBEAT_FLAGS if flag not in capabilities.flags]
    if missing:
        raise RuntimeError(
            "launcher is missing required heartbeat flags: " + ", ".join(missing)
        )
    if not capabilities.control_token_supported:
        raise RuntimeError(
            "launcher is missing --control-token-env; follow-up control cannot be authenticated"
        )
    status_path = job_dir / "heartbeat.json"
    return (
        [
            "--heartbeat-interval",
            str(int(interval_seconds)),
            "--heartbeat-misses",
            str(int(missed_replies)),
            "--status-file",
            str(status_path),
        ],
        {
            "mode": "launcher_heartbeat",
            "interval_seconds": int(interval_seconds),
            "missed_replies_allowed": int(missed_replies),
            "status_path": str(status_path),
            "control_token_env": CONTROL_TOKEN_ENV,
            "degraded": False,
        },
    )


def _bounded_list(value: Any, limit: int = MAX_ACTIVITY_ITEMS) -> list[Any]:
    if not isinstance(value, list):
        return []
    result: list[Any] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            cleaned: dict[str, Any] = {}
            for key, val in list(item.items())[:20]:
                if isinstance(val, str):
                    cleaned[str(key)] = val[:500]
                elif isinstance(val, (int, float, bool)) or val is None:
                    cleaned[str(key)] = val
            result.append(cleaned)
        elif isinstance(item, str):
            result.append(item[:500])
        elif isinstance(item, (int, float, bool)) or item is None:
            result.append(item)
    return result


def read_heartbeat(job_dir: Path, max_bytes: int = 262_144) -> tuple[dict[str, Any] | None, str | None]:
    """Read the actual ``dsh-heartbeat-status/1`` record, bounded and sanitised."""
    path = job_dir / "heartbeat.json"
    value, error = read_json_bounded(path, max_bytes)
    if not isinstance(value, dict):
        return None, error or "invalid"
    if value.get("schema") == STATUS_SCHEMA:
        hb = value.get("heartbeat") if isinstance(value.get("heartbeat"), dict) else {}
        control = value.get("control") if isinstance(value.get("control"), dict) else None
        return {
            "present": True,
            "schema": STATUS_SCHEMA,
            "path": str(path),
            "state": value.get("state"),
            "run_id": value.get("run_id"),
            "conversation_id": value.get("dsh_conversation_id"),
            # This nested timestamp is advanced only by committed model/tool
            # events in the landed heartbeat supervisor.  Do not substitute the
            # status file mtime or supervisor poll time.
            "last_activity_at": hb.get("last_activity_at"),
            "last_worker_activity_at": hb.get("last_activity_at"),
            "last_activity_kind": hb.get("last_activity_kind"),
            "unanswered_pings": hb.get("consecutive_unanswered"),
            "misses_allowed": hb.get("max_unanswered"),
            "interval_seconds": hb.get("idle_seconds"),
            "response_window_seconds": hb.get("response_window_seconds"),
            "current_idle_seconds": hb.get("current_idle_seconds"),
            "activity_count": hb.get("activity_count"),
            "awaiting_input": bool(hb.get("awaiting_input")),
            "awaiting_since": hb.get("awaiting_since"),
            "awaiting_deadline": hb.get("awaiting_deadline"),
            "pings": _bounded_list(hb.get("pings")),
            "events": _bounded_list(hb.get("events")),
            "failure": value.get("failure"),
            "failure_detail": value.get("failure_detail"),
            "partial": value.get("partial"),
            "exit_code": value.get("exit_code"),
            "started_at": value.get("started_at"),
            "ended_at": value.get("ended_at"),
            "duration_seconds": value.get("duration_seconds"),
            "pid": value.get("pid"),
            "control": _sanitise_control(control),
            "outputs": value.get("outputs") if isinstance(value.get("outputs"), dict) else None,
        }, None
    # Tolerate the provisional/legacy shape only for status display; the real
    # launcher writes the schema above.
    return {
        "present": True,
        "schema": value.get("schema"),
        "path": str(path),
        "state": value.get("state"),
        "conversation_id": value.get("conversation_id") or value.get("dsh_conversation_id"),
        "last_activity_at": value.get("last_worker_activity_at"),
        "last_worker_activity_at": value.get("last_worker_activity_at"),
        "unanswered_pings": value.get("consecutive_unanswered") or value.get("unanswered_pings"),
        "misses_allowed": value.get("max_unanswered") or value.get("misses_allowed"),
        "awaiting_input": bool(value.get("awaiting_input")),
        "control": _sanitise_control(value.get("control")),
    }, None


def _sanitise_control(control: Any) -> dict[str, Any] | None:
    if not isinstance(control, dict):
        return None
    allowed: dict[str, Any] = {}
    for key in (
        "schema",
        "host",
        "port",
        "pid",
        "run_id",
        "session_id",
        "state",
        "agent_status",
        "endpoint_file",
        "listener_closed",
        "updated_at",
    ):
        if key in control and (
            control[key] is None or isinstance(control[key], (str, int, float, bool))
        ):
            allowed[key] = control[key]
    return allowed


def read_control(path: Path) -> tuple[dict[str, Any] | None, str]:
    value, error = read_json_bounded(path, MAX_DESCRIPTOR_BYTES)
    if not isinstance(value, dict):
        return None, error or "invalid"
    if value.get("schema") != CONTROL_SCHEMA:
        return None, "schema_mismatch"
    return value, "ok"


def control_available(control_path: Path, heartbeat: dict[str, Any] | None) -> bool:
    control, _ = read_control(control_path)
    if control is None:
        return False
    if control.get("state") not in {"bound", "awaiting-input"}:
        return False
    host = control.get("host")
    port = control.get("port")
    return host == "127.0.0.1" and isinstance(port, int) and 1 <= port <= 65535


def _validate_control(
    control: dict[str, Any],
    status: dict[str, Any] | None,
    expected_conversation_id: str | None,
    *,
    kind: str = "status",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if control.get("schema") != CONTROL_SCHEMA:
        return {"code": "control_invalid", "message": "unexpected control descriptor schema"}, None
    state = control.get("state")
    if state in {"closed", "server-error", "agent-disposed"}:
        return {
            "code": "transport_expired",
            "message": f"heartbeat control listener is {state}",
        }, None
    if state == "listening":
        return {
            "code": "transport_unavailable",
            "message": "heartbeat listener is up but the dsh agent is not bound yet",
        }, None
    if state not in {"bound", "awaiting-input"}:
        return {
            "code": "transport_unavailable",
            "message": f"heartbeat control listener is not ready (state={state!r})",
        }, None
    host = control.get("host")
    port = control.get("port")
    if host != "127.0.0.1" or not isinstance(port, int) or not 1 <= port <= 65535:
        return {
            "code": "control_invalid",
            "message": "control descriptor must be a 127.0.0.1 loopback HTTP endpoint",
        }, None
    pid = control.get("pid")
    if isinstance(pid, int) and pid > 0:
        if not procutil.process_alive(pid):
            return {
                "code": "transport_unavailable",
                "message": "heartbeat control process is not running",
            }, None
    run_id = control.get("run_id") or (status or {}).get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return {
            "code": "control_invalid",
            "message": "control descriptor has no run_id",
        }, None
    conversation = control.get("session_id") or (status or {}).get("conversation_id")
    if expected_conversation_id and conversation and expected_conversation_id != conversation:
        return {
            "code": "session_mismatch",
            "message": "conversation ID does not match the running dsh conversation",
        }, None
    return None, {
        "host": host,
        "port": port,
        "path": "/followup" if kind == "followup" else "/ping",
        "run_id": run_id,
        "conversation_id": conversation,
        "state": state,
        "agent_status": control.get("agent_status"),
        "awaiting_input": bool(control.get("awaiting_input")) or state == "awaiting-input",
    }


def send_nudge(
    control_path: Path,
    status: dict[str, Any] | None,
    job_id: str,
    message: str,
    kind: str,
    expected_conversation_id: str | None,
    token: str | None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    if not isinstance(token, str) or len(token) < 32:
        return {
            "ok": False,
            "error": {
                "code": "transport_unavailable",
                "message": (
                    "the per-job control token is not available in this MCP server "
                    "process; a restarted server cannot authenticate existing jobs"
                ),
            },
        }
    control, error = read_control(control_path)
    if control is None:
        return {
            "ok": False,
            "error": {
                "code": "transport_unavailable",
                "message": (
                    "no dsh-heartbeat-control/1 descriptor is present; the launcher "
                    "heartbeat control adapter is not ready or has closed"
                ),
                "descriptor_error": error,
            },
        }
    validation_error, details = _validate_control(
        control, status, expected_conversation_id, kind=kind
    )
    if validation_error:
        return {"ok": False, "error": validation_error}
    assert details is not None
    length_error = message_length_error(message)
    if length_error is not None:
        return {
            "ok": False,
            "error": {
                "code": "message_too_long",
                "message": length_error,
                "characters": adapter_message_length(message),
                "limit": MAX_ADAPTER_MESSAGE_CHARS,
            },
        }
    if len(message.encode("utf-8", errors="replace")) > MAX_MESSAGE_BYTES:
        return {
            "ok": False,
            "error": {"code": "message_too_large", "message": "message exceeds 32 KiB"},
        }
    run_id = details["run_id"]
    ping_id = f"{run_id}-plugin-{secrets.token_hex(4)}"
    existing_pings = (status or {}).get("pings")
    sequence = len(existing_pings) + 1 if isinstance(existing_pings, list) else 1
    body = json.dumps(
        {
            "run_id": run_id,
            "ping_id": ping_id,
            "sequence": sequence,
            "kind": "followup" if kind == "followup" else "status",
            "session_id": details.get("conversation_id"),
            "message": [{"type": "text", "text": message}],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    connection = http.client.HTTPConnection(details["host"], details["port"], timeout=timeout)
    try:
        connection.request(
            "POST",
            details["path"],
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-DSH-Heartbeat-Token": token,
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        raw = response.read(MAX_CONTROL_RESPONSE_BYTES + 1)
        status_code = response.status
    except (OSError, http.client.HTTPException) as exc:
        return {
            "ok": False,
            "error": {
                "code": "transport_error",
                "message": f"{type(exc).__name__}: {exc}",
            },
        }
    finally:
        connection.close()
    payload: Any = None
    if raw:
        try:
            payload = json.loads(raw[:MAX_CONTROL_RESPONSE_BYTES].decode("utf-8", "replace"))
        except (UnicodeError, json.JSONDecodeError):
            payload = None
    if status_code != 200 or not isinstance(payload, dict) or not payload.get("ok") or not payload.get("queued"):
        error_text = payload.get("error") if isinstance(payload, dict) else None
        return {
            "ok": False,
            "error": {
                "code": "transport_rejected",
                "message": str(error_text or f"control endpoint returned HTTP {status_code}"),
                "http_status": status_code,
            },
        }
    return {
        "ok": True,
        "transport": "dsh-heartbeat-control/1",
        "kind": "followup" if kind == "followup" else "status",
        "delivered": True,
        "queued": True,
        "acknowledged": True,
        "worker_response": bool(payload.get("worker_response")),
        "ack_is_not_a_worker_response": True,
        "http_status": status_code,
        "conversation_id": payload.get("session_id") or details.get("conversation_id"),
        "agent_status": payload.get("agent_status"),
        "awaiting_input": bool(payload.get("delivered") == "awaiting-turn"),
        "delivery_mode": payload.get("delivered"),
        "ping_id": ping_id,
        "note": (
            "The Cordis control plugin accepted and queued the steering message. "
            "That is transport delivery, not a model reply; verify activity via "
            "worker_status/heartbeat before treating the worker as responsive."
        ),
    }
