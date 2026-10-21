"""Heartbeat supervision for one-shot dsh runs.

The old launcher killed a run after a fixed wall-clock timeout.  Productive work
must instead be allowed to continue while a worker is alive.  This module
implements the supervisor used by ``run_deepseek_harness.py``:

* stream ``dsh --json`` events and record committed model/tool activity;
* after ``idle_seconds`` without activity, ask the *same* live agent for a
  status update through the loopback control plugin (``dsh_heartbeat_control.mjs``);
* wait ``response_window_seconds`` for any real activity; two consecutive
  unanswered requests stop the run with exit 125;
* an explicitly requested hard timeout is still honoured and exits 124.

A queued HTTP acknowledgement is transport delivery only.  It never resets the
unanswered count; only committed dsh events (assistant text/thinking, tool calls,
tool results, or a final answer) do.
"""
from __future__ import annotations

import http.client
import json
import os
import queue
import re
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_IDLE_SECONDS = 900
DEFAULT_RESPONSE_WINDOW_SECONDS = 900
DEFAULT_MAX_UNANSWERED = 2
MAX_UNANSWERED_LIMIT = 10
# A waiting descriptor is trusted only until its absolute deadline plus a
# short delivery/event-loop grace.  The JS timer is not supervision evidence.
AWAITING_INPUT_GRACE_SECONDS = 5.0
MAX_FOLLOWUP_WAIT_SECONDS = 3600.0

HARD_TIMEOUT_EXIT = 124
HEARTBEAT_EXIT = 125
SUPERVISION_EXIT = 126

STATUS_SCHEMA = "dsh-heartbeat-status/1"
CONTROL_SCHEMA = "dsh-heartbeat-control/1"
PING_PATH = "/ping"


def _iso(epoch: float | None = None) -> str:
    return datetime.fromtimestamp(epoch if epoch is not None else time.time(), timezone.utc).isoformat(timespec="seconds")


def _parse_iso_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _bounded(value: Any, limit: int = 500) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, dict):
        return {str(k): _bounded(v, limit) for k, v in list(value.items())[:20]}
    if isinstance(value, list):
        return [_bounded(v, limit) for v in value[:20]]
    return value


@dataclass(frozen=True)
class HeartbeatConfig:
    """Heartbeat schedule.  ``hard_timeout`` is independent and optional."""

    idle_seconds: float = DEFAULT_IDLE_SECONDS
    response_window_seconds: float = DEFAULT_RESPONSE_WINDOW_SECONDS
    max_unanswered: int = DEFAULT_MAX_UNANSWERED
    hard_timeout: float | None = None

    def __post_init__(self) -> None:
        if not (isinstance(self.idle_seconds, (int, float)) and self.idle_seconds > 0):
            raise ValueError("idle_seconds must be positive")
        if not (isinstance(self.response_window_seconds, (int, float)) and self.response_window_seconds > 0):
            raise ValueError("response_window_seconds must be positive")
        if not (isinstance(self.max_unanswered, int) and 2 <= self.max_unanswered <= MAX_UNANSWERED_LIMIT):
            raise ValueError(f"max_unanswered must be an integer from 2 to {MAX_UNANSWERED_LIMIT}")
        if self.hard_timeout is not None and not (
            isinstance(self.hard_timeout, (int, float)) and self.hard_timeout > 0
        ):
            raise ValueError("hard_timeout must be positive when supplied")

    @property
    def interval(self) -> float:
        return float(self.idle_seconds)

    @property
    def window(self) -> float:
        return float(self.response_window_seconds)


@dataclass
class Delivery:
    """Result of one control-transport attempt (not a model response)."""

    ok: bool
    queued: bool = False
    status_code: int | None = None
    session_id: str | None = None
    agent_status: str | None = None
    error: str | None = None
    latency_ms: int | None = None
    kind: str = "status"
    delivery_mode: str | None = None
    awaiting_input: bool = False


@dataclass
class PingRecord:
    sequence: int
    ping_id: str
    queued_at: float
    queued_at_iso: str
    deadline: float
    delivery_ok: bool
    queued: bool
    delivery_error: str | None = None
    status_code: int | None = None
    session_id: str | None = None
    agent_status: str | None = None
    answered_at_iso: str | None = None
    answered_by: str | None = None
    outcome: str = "pending"  # pending | answered | missed

    def to_status(self, now: float) -> dict[str, Any]:
        remaining = max(0.0, self.deadline - now)
        return {
            "sequence": self.sequence,
            "ping_id": self.ping_id,
            "queued_at": self.queued_at_iso,
            "delivery_ok": self.delivery_ok,
            "queued": self.queued,
            "delivery_error": self.delivery_error,
            "status_code": self.status_code,
            "session_id": self.session_id,
            "agent_status": self.agent_status,
            "outcome": self.outcome,
            "answered_at": self.answered_at_iso,
            "answered_by": self.answered_by,
            "response_window_remaining_seconds": round(remaining, 3),
        }


class HeartbeatSupervisor:
    """Deterministic heartbeat state machine.

    ``clock`` is monotonic (seconds).  ``ping_fn`` performs the transport call and
    must not update this state machine; only :meth:`note_activity` does that.
    """

    def __init__(
        self,
        config: HeartbeatConfig,
        *,
        run_id: str,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        ping_fn: Callable[..., Delivery] | None = None,
        session_id: str | None = None,
        started_at: float | None = None,
    ) -> None:
        self.config = config
        self.run_id = run_id
        self._clock = clock
        self._wall_clock = wall_clock
        self._ping_fn = ping_fn
        self.session_id = session_id
        self.started_at = clock() if started_at is None else started_at
        self.started_at_iso = _iso(wall_clock())
        self.last_activity_at = self.started_at
        self.last_activity_at_iso = self.started_at_iso
        self.last_activity_kind = "start"
        self.last_activity_detail: dict[str, Any] = {}
        self.consecutive_unanswered = 0
        self.pings: list[PingRecord] = []
        self.pending: PingRecord | None = None
        self.events: list[dict[str, Any]] = []
        self.state = "running"
        self.failure: str | None = None
        self.failure_detail: str | None = None
        self.stopped = False
        self.activity_count = 0
        self.last_status_phase: str | None = None
        self.last_status_detail: dict[str, Any] = {}
        self.error: str | None = None
        self.final_seen = False
        self.turn_end_reason: dict[str, Any] | None = None
        # Deliberate host-side input wait (agent/turn-stopping).  It is not
        # worker progress, but it is also not a stalled heartbeat: suppress
        # idle pings until the wait ends.  Hard timeout still applies.
        self.awaiting_input = False
        self.awaiting_since: float | None = None
        self.awaiting_since_iso: str | None = None
        self.awaiting_deadline_iso: str | None = None
        self.awaiting_ended_at: float | None = None

    # -- activity ---------------------------------------------------------
    def note_activity(self, kind: str, *, now: float | None = None, detail: dict[str, Any] | None = None) -> None:
        """Record real committed worker activity and reset consecutive misses."""
        if self.stopped:
            return
        now = self._clock() if now is None else now
        self.last_activity_at = now
        self.last_activity_at_iso = _iso(self._wall_clock())
        self.last_activity_kind = kind
        self.last_activity_detail = _bounded(detail or {})
        self.activity_count += 1
        self.consecutive_unanswered = 0
        self.state = "running"
        if self.pending is not None and now >= self.pending.queued_at:
            self.pending.outcome = "answered"
            self.pending.answered_at_iso = self.last_activity_at_iso
            self.pending.answered_by = kind
            self.pending = None
        self.events.append({
            "at": self.last_activity_at_iso,
            "kind": kind,
            "detail": self.last_activity_detail,
        })
        self.events = self.events[-50:]

    def note_status_phase(self, phase: str, detail: dict[str, Any] | None = None) -> None:
        self.last_status_phase = phase
        self.last_status_detail = _bounded(detail or {})

    def set_awaiting_input(
        self,
        value: bool,
        *,
        now: float | None = None,
        ended_at: float | None = None,
        deadline_iso: str | None = None,
    ) -> bool:
        """Track a deliberate follow-up wait without faking worker activity.

        While true, ``tick`` does not send idle status pings.  On exit the idle
        anchor is restarted so a long deliberate wait does not immediately
        trigger a ping; ``last_activity_at`` itself remains committed-worker
        activity only.  ``ended_at`` may backdate the anchor to a stale
        descriptor's lease deadline, so an overdue wait does not add another
        full interval of silence.  ``deadline_iso`` is published for monitoring
        so a persisted status record can be re-validated after a wedge.
        Returns whether the value changed.
        """
        now = self._clock() if now is None else now
        value = bool(value)
        if value == self.awaiting_input:
            if value and deadline_iso:
                self.awaiting_deadline_iso = deadline_iso
            return False
        self.awaiting_input = value
        if value:
            self.awaiting_since = now
            self.awaiting_since_iso = _iso(self._wall_clock())
            self.awaiting_deadline_iso = deadline_iso
        else:
            self.awaiting_since = None
            self.awaiting_since_iso = None
            self.awaiting_deadline_iso = None
            self.awaiting_ended_at = now if ended_at is None else min(now, ended_at)
        return True

    # -- scheduling -------------------------------------------------------
    def idle_seconds(self, now: float | None = None) -> float:
        now = self._clock() if now is None else now
        anchor = self.last_activity_at
        if self.awaiting_ended_at is not None:
            anchor = max(anchor, self.awaiting_ended_at)
        return max(0.0, now - anchor)

    def tick(self, now: float | None = None) -> str:
        """Return ``none``, ``ping``, ``stop``, ``hard_timeout``, or ``stopped``."""
        if self.stopped:
            return "stopped"
        now = self._clock() if now is None else now
        if self.config.hard_timeout is not None and now - self.started_at >= self.config.hard_timeout:
            self.stop("hard_timeout", f"explicit hard timeout after {self.config.hard_timeout:g}s")
            return "hard_timeout"
        if self.pending is not None:
            if now - self.pending.queued_at >= self.config.window:
                self.pending.outcome = "missed"
                self.pending.answered_at_iso = _iso(self._wall_clock())
                self.pending.answered_by = None
                self.consecutive_unanswered += 1
                self.events.append({
                    "at": _iso(self._wall_clock()),
                    "kind": "miss",
                    "detail": {"sequence": self.pending.sequence, "consecutive": self.consecutive_unanswered},
                })
                self.events = self.events[-50:]
                self.pending = None
                if self.consecutive_unanswered >= self.config.max_unanswered:
                    if self._all_pings_undelivered():
                        self.stop(
                            "heartbeat_no_delivery",
                            f"{self.consecutive_unanswered} consecutive status requests could not be delivered "
                            "to the worker control channel",
                        )
                    else:
                        self.stop(
                            "heartbeat_no_response",
                            f"{self.consecutive_unanswered} consecutive status requests received no worker activity",
                        )
                    return "stop"
                # ping 2 follows immediately after ping 1's response window.
                return "ping"
            return "none"
        if self.consecutive_unanswered >= self.config.max_unanswered:
            self.stop("heartbeat_no_response", "unanswered status request limit reached")
            return "stop"
        if self.awaiting_input:
            # A deliberate input wait is not a stalled productive worker.
            return "none"
        if self.idle_seconds(now) >= self.config.idle_seconds:
            return "ping"
        return "none"

    def _all_pings_undelivered(self) -> bool:
        missed = [p for p in self.pings if p.outcome == "missed"]
        return bool(missed) and all(not p.delivery_ok for p in missed)

    def make_ping(
        self,
        message: str,
        *,
        now: float | None = None,
        session_id: str | None = None,
    ) -> PingRecord | None:
        """Create and transport one status request.  Returns ``None`` if stopped."""
        if self.stopped:
            return None
        now = self._clock() if now is None else now
        sequence = len(self.pings) + 1
        ping_id = f"{self.run_id}-ping-{sequence}"
        delivery = Delivery(ok=False, error="transport not configured")
        if self._ping_fn is not None:
            try:
                delivery = self._ping_fn(
                    ping_id=ping_id,
                    sequence=sequence,
                    message=message,
                    session_id=session_id or self.session_id,
                )
            except Exception as exc:  # noqa: BLE001 - transport failure is data, not a crash
                delivery = Delivery(ok=False, error=f"{type(exc).__name__}: {exc}")
        record = PingRecord(
            sequence=sequence,
            ping_id=ping_id,
            queued_at=now,
            queued_at_iso=_iso(self._wall_clock()),
            deadline=now + self.config.window,
            delivery_ok=bool(delivery.ok and delivery.queued),
            queued=bool(delivery.queued),
            delivery_error=delivery.error,
            status_code=delivery.status_code,
            session_id=delivery.session_id or session_id or self.session_id,
            agent_status=delivery.agent_status,
        )
        self.pings.append(record)
        self.pending = record
        self.state = f"ping-{sequence}"
        self.events.append({
            "at": record.queued_at_iso,
            "kind": "ping",
            "detail": {
                "sequence": sequence,
                "delivery_ok": record.delivery_ok,
                "delivery_error": record.delivery_error,
            },
        })
        self.events = self.events[-50:]
        return record

    def stop(self, reason: str, detail: str | None = None) -> None:
        if self.stopped:
            return
        self.stopped = True
        self.failure = reason
        self.failure_detail = detail
        self.state = "hard_timeout" if reason == "hard_timeout" else "heartbeat_stopped"
        self.events.append({
            "at": _iso(self._wall_clock()),
            "kind": "stop",
            "detail": {"reason": reason, "detail": detail},
        })
        self.events = self.events[-50:]

    # -- reporting --------------------------------------------------------
    def ping_message(self, sequence: int, idle_seconds: float) -> str:
        return (
            f"Automated supervisor heartbeat #{sequence}: no committed model output or tool activity "
            f"has been observed for about {int(idle_seconds)} seconds. This is not a new task, not a "
            "request to restart, and not a replacement for your final answer. Do not abandon or restart "
            "your work. Continue the current task; if you are blocked, state the blocker briefly and what "
            "you will do next. Do not end your turn solely to answer this status check; keep working if "
            "work remains."
        )

    def snapshot(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        now = self._clock()
        data: dict[str, Any] = {
            "heartbeat": {
                "enabled": True,
                "idle_seconds": self.config.interval,
                "response_window_seconds": self.config.window,
                "max_unanswered": self.config.max_unanswered,
                "hard_timeout_seconds": self.config.hard_timeout,
                "last_activity_at": self.last_activity_at_iso,
                "last_activity_kind": self.last_activity_kind,
                "last_activity_detail": self.last_activity_detail,
                "current_idle_seconds": round(self.idle_seconds(now), 3),
                "consecutive_unanswered": self.consecutive_unanswered,
                "activity_count": self.activity_count,
                "pings": [p.to_status(now) for p in self.pings],
                "events": self.events,
                "last_status_phase": self.last_status_phase,
                "last_status_detail": self.last_status_detail,
                "turn_end_reason": self.turn_end_reason,
                "awaiting_input": self.awaiting_input,
                "awaiting_since": self.awaiting_since_iso,
                "awaiting_deadline": self.awaiting_deadline_iso,
            },
            "dsh_conversation_id": self.session_id,
            "failure": self.failure,
            "failure_detail": self.failure_detail,
            "state": self.state,
        }
        if extra:
            data.update(extra)
        return data


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------

def parse_event_line(line: str) -> dict[str, Any] | None:
    """Parse one stdout line.  Non-JSON output stays evidence, never activity."""
    raw = line.strip()
    if not raw:
        return None
    try:
        event = json.loads(raw)
    except (ValueError, TypeError):
        return {"type": "unparsed_stdout", "bytes": len(line.encode("utf-8", "replace"))}
    if not isinstance(event, dict):
        return {"type": "unparsed_stdout", "bytes": len(line.encode("utf-8", "replace"))}
    return event


def activity_kind(event: dict[str, Any]) -> str | None:
    """Return the activity kind for a committed event, else ``None``."""
    kind = event.get("type")
    if kind == "text":
        return "text" if event.get("text") else None
    if kind == "thinking":
        return "thinking" if event.get("thinking") else None
    if kind == "tool_call":
        return "tool_call"
    if kind == "tool_result":
        return "tool_result"
    if kind == "final":
        return "final"
    if kind == "status" and event.get("phase") == "step_end":
        usage = event.get("usage") or {}
        try:
            output_tokens = int(usage.get("outputTokens") or usage.get("output_tokens") or 0)
        except (TypeError, ValueError):
            output_tokens = 0
        return "step_output" if output_tokens > 0 else None
    return None


def _event_detail(event: dict[str, Any]) -> dict[str, Any]:
    kind = event.get("type")
    if kind == "text":
        return {"chars": len(str(event.get("text") or ""))}
    if kind == "thinking":
        return {"chars": len(str(event.get("thinking") or ""))}
    if kind == "tool_call":
        return {"tool": event.get("name") or event.get("tool") or "unknown"}
    if kind == "tool_result":
        return {"tool": event.get("name") or event.get("tool") or "unknown", "ok": event.get("ok")}
    if kind == "final":
        return {"chars": len(str(event.get("text") or ""))}
    if kind == "status":
        detail = {"phase": event.get("phase")}
        reason = event.get("reason")
        if isinstance(reason, dict):
            detail["reason"] = _bounded(reason, 200)
        return detail
    return {}


# ---------------------------------------------------------------------------
# Control transport
# ---------------------------------------------------------------------------

@dataclass
class ControlEndpoint:
    host: str
    port: int
    pid: int | None
    session_id: str | None
    state: str | None
    path: Path
    raw: dict[str, Any]
    awaiting_input: bool = False
    followup_deadline: str | None = None
    followup_deadline_epoch: float | None = None


def read_control_endpoint(path: Path) -> ControlEndpoint | None:
    """Read and validate the plugin's descriptor.  No token is ever stored there."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("schema") != CONTROL_SCHEMA:
        return None
    host = raw.get("host")
    port = raw.get("port")
    if host != "127.0.0.1" or not isinstance(port, int) or not 1 <= port <= 65535:
        return None
    session_id = raw.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        return None
    state = raw.get("state") if isinstance(raw.get("state"), str) else None
    deadline = raw.get("followup_deadline")
    deadline_epoch = _parse_iso_epoch(deadline)
    awaiting_input = raw.get("awaiting_input") is True or state == "awaiting-input"
    if awaiting_input:
        # Do not let a stale/wedged descriptor suppress heartbeat supervision
        # forever.  The lease must have a parseable absolute deadline that is
        # not already past (plus a small grace) and is within the supported cap.
        now = time.time()
        if deadline_epoch is None:
            awaiting_input = False
        elif deadline_epoch + AWAITING_INPUT_GRACE_SECONDS < now:
            awaiting_input = False
        elif deadline_epoch - now > MAX_FOLLOWUP_WAIT_SECONDS + AWAITING_INPUT_GRACE_SECONDS:
            awaiting_input = False
    return ControlEndpoint(
        host=host,
        port=port,
        pid=raw.get("pid") if isinstance(raw.get("pid"), int) else None,
        session_id=session_id,
        state=state,
        path=path,
        raw=raw,
        awaiting_input=awaiting_input,
        followup_deadline=deadline if isinstance(deadline, str) else None,
        followup_deadline_epoch=deadline_epoch,
    )


def wait_control_endpoint(
    path: Path,
    *,
    process: subprocess.Popen | None,
    timeout: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    require_session: bool = True,
) -> ControlEndpoint | None:
    """Wait for a valid listener (and, by default, a bound dsh session)."""
    deadline = clock() + timeout
    while True:
        endpoint = read_control_endpoint(path)
        if endpoint is not None and (not require_session or endpoint.session_id):
            return endpoint
        if process is not None and process.poll() is not None:
            return None
        if clock() >= deadline:
            return None
        sleep(0.05)


class ControlTransport:
    """Loopback HTTP client for the per-run Cordis plugin."""

    def __init__(
        self,
        endpoint_path: Path,
        *,
        token: str,
        run_id: str,
        timeout: float = 5.0,
        session_id: str | None = None,
    ) -> None:
        self.endpoint_path = Path(endpoint_path)
        self.token = token
        self.run_id = run_id
        self.timeout = timeout
        self.session_id = session_id

    def _endpoint(self) -> ControlEndpoint:
        endpoint = read_control_endpoint(self.endpoint_path)
        if endpoint is None:
            raise RuntimeError("control endpoint is unavailable")
        return endpoint

    def ping(
        self,
        *,
        ping_id: str,
        sequence: int,
        message: str,
        session_id: str | None = None,
    ) -> Delivery:
        return self._post(
            PING_PATH,
            kind="status",
            ping_id=ping_id,
            sequence=sequence,
            message=message,
            session_id=session_id,
        )

    def followup(
        self,
        *,
        followup_id: str,
        sequence: int,
        message: str,
        session_id: str | None = None,
    ) -> Delivery:
        """Deliver one genuine question to the same conversation (not a ping)."""
        return self._post(
            "/followup",
            kind="followup",
            ping_id=followup_id,
            sequence=sequence,
            message=message,
            session_id=session_id,
        )

    def _post(
        self,
        path: str,
        *,
        kind: str,
        ping_id: str,
        sequence: int,
        message: str,
        session_id: str | None,
    ) -> Delivery:
        started = time.monotonic()
        try:
            endpoint = self._endpoint()
            body = json.dumps({
                "run_id": self.run_id,
                "ping_id": ping_id,
                "sequence": sequence,
                "kind": kind,
                "session_id": session_id or endpoint.session_id,
                "message": [{"type": "text", "text": message}],
            }).encode("utf-8")
            connection = http.client.HTTPConnection(endpoint.host, endpoint.port, timeout=self.timeout)
            try:
                connection.request(
                    "POST",
                    path,
                    body=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-DSH-Heartbeat-Token": self.token,
                        "Content-Length": str(len(body)),
                    },
                )
                response = connection.getresponse()
                payload = response.read(64 * 1024)
                status = response.status
            finally:
                connection.close()
            latency = int((time.monotonic() - started) * 1000)
            try:
                data = json.loads(payload.decode("utf-8", "replace")) if payload else {}
            except ValueError:
                data = {}
            ok = status == 200 and bool(data.get("ok")) and bool(data.get("queued"))
            return Delivery(
                ok=ok,
                queued=bool(data.get("queued")),
                status_code=status,
                session_id=data.get("session_id") if isinstance(data.get("session_id"), str) else None,
                agent_status=data.get("agent_status") if isinstance(data.get("agent_status"), str) else None,
                error=None if ok else str(data.get("error") or f"http {status}"),
                latency_ms=latency,
                kind=kind,
                delivery_mode=data.get("delivered") if isinstance(data.get("delivered"), str) else None,
                awaiting_input=bool(data.get("awaiting_input")),
            )
        except (OSError, http.client.HTTPException, RuntimeError) as exc:
            return Delivery(
                ok=False,
                queued=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=int((time.monotonic() - started) * 1000),
                kind=kind,
            )


# ---------------------------------------------------------------------------
# Status/log helpers
# ---------------------------------------------------------------------------

class StatusWriter:
    """Atomically persist the small monitoring record; never includes secrets."""

    def __init__(self, path: Path, base: dict[str, Any]) -> None:
        self.path = Path(path)
        self.base = base
        self._lock = threading.Lock()
        self._last = 0.0

    def write(self, snapshot: dict[str, Any], *, force: bool = False) -> None:
        with self._lock:
            now = time.time()
            if not force and now - self._last < 0.2:
                return
            self._last = now
            data = dict(self.base)
            data.update(snapshot)
            data["schema"] = STATUS_SCHEMA
            data["updated_at"] = _iso(now)
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass


class _Log:
    def __init__(self, path: Path, header: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = self.path.open("w", encoding="utf-8", errors="replace")
        self.write(header)

    def write(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            try:
                self._fh.write(text)
                if not text.endswith("\n"):
                    self._fh.write("\n")
                self._fh.flush()
            except (OSError, ValueError):
                pass

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.close()
            except (OSError, ValueError):
                pass


@dataclass
class RunResult:
    rc: int
    reason: str | None
    detail: str | None
    out_text: str
    partial: bool
    status: dict[str, Any]
    status_path: Path
    log_path: Path
    events_path: Path
    control_path: Path


def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)


def _default_kill(pid: int) -> None:
    if os.name == "nt":
        _kill_tree(pid)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def _listener_closed(host: str, port: int, *, attempts: int = 10, delay: float = 0.1) -> bool:
    import socket
    for _ in range(attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.15)
            if sock.connect_ex((host, port)) != 0:
                return True
        time.sleep(delay)
    return False


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_supervised(
    *,
    argv: list[str],
    env: dict[str, str],
    cwd: str,
    task_text: str,
    out_path: Path,
    log_path: Path,
    status_path: Path,
    control_path: Path,
    heartbeat: HeartbeatConfig,
    control_token: str,
    run_id: str,
    metadata: dict[str, Any] | None = None,
    popen: Callable[..., subprocess.Popen] | None = None,
    kill: Callable[[int], None] = _default_kill,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    control_ready_timeout: float = 30.0,
) -> RunResult:
    """Start dsh, drain both pipes, supervise, and preserve partial output."""
    out_path = Path(out_path)
    log_path = Path(log_path)
    status_path = Path(status_path)
    control_path = Path(control_path)
    events_path = out_path.with_name(out_path.name + ".events.jsonl")
    env = dict(env)
    # The plugin must authenticate with the exact token this supervisor uses.
    # Supplying it here prevents a caller/plugin mismatch without writing it to
    # a config, status, or log file.
    env["DSH_HEARTBEAT_TOKEN"] = control_token
    env["DSH_HEARTBEAT_RUN_ID"] = run_id
    out_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    control_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.parent.mkdir(parents=True, exist_ok=True)

    base = {
        "run_id": run_id,
        "started_at": _iso(),
        "started_epoch": time.time(),
        "host": "127.0.0.1",
        "outputs": {
            "out_file": str(out_path),
            "log_file": str(log_path),
            "events_file": str(events_path),
            "status_file": str(status_path),
            "control_file": str(control_path),
        },
        "provider_routing_session_id": (metadata or {}).get("provider_session_id"),
        "provider_routing_note": "x-opencode-session header; separate from the dsh conversation id",
        "model": (metadata or {}).get("model"),
        "reasoning_effort": (metadata or {}).get("effort"),
        "account": (metadata or {}).get("account"),
        "permission": (metadata or {}).get("permission"),
        "followup_wait_seconds": (metadata or {}).get("followup_wait_seconds") or 0,
        "cwd": cwd,
        "partial": False,
    }
    header = " ".join(
        f"{key}={value}" for key, value in {
            "model": base["model"],
            "effort": base["reasoning_effort"],
            "account": base["account"],
            "permission": base["permission"],
            "cwd": base["cwd"],
            "run_id": run_id,
            "heartbeat_idle": heartbeat.interval,
            "heartbeat_window": heartbeat.window,
            "heartbeat_max_unanswered": heartbeat.max_unanswered,
            "hard_timeout": heartbeat.hard_timeout,
        }.items()
    )
    log = _Log(log_path, header)
    status = StatusWriter(status_path, base)
    event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    reader_count_lock = threading.Lock()
    reader_count = [0]
    readers_done = threading.Event()

    def _reader_finished() -> None:
        with reader_count_lock:
            reader_count[0] += 1
            if reader_count[0] >= 2:
                readers_done.set()

    stderr_tail: list[str] = []
    state_lock = threading.Lock()
    raw_events_lock = threading.Lock()
    text_write_lock = threading.Lock()
    last_persisted_text = [""]

    def persist_committed_text(text: str) -> None:
        """Persist committed assistant text (never thinking) before final exit.

        A controller-lease expiry/cancel can kill the launcher before its
        finally block.  Writing each committed text event atomically keeps the
        last answer available to bounded worker_result without exposing
        reasoning or periodic logs.
        """
        if not text or text == last_persisted_text[0]:
            return
        with text_write_lock:
            if text == last_persisted_text[0]:
                return
            tmp = out_path.with_name(f".{out_path.name}.{os.getpid()}.partial.tmp")
            try:
                tmp.write_text(text, encoding="utf-8")
                os.replace(tmp, out_path)
                last_persisted_text[0] = text
            except OSError:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
    try:
        events_path.write_text("", encoding="utf-8")
        out_path.write_text("", encoding="utf-8")
    except OSError:
        pass
    try:
        control_path.unlink(missing_ok=True)
    except OSError:
        pass

    process: subprocess.Popen | None = None
    supervisor: HeartbeatSupervisor | None = None
    transport: ControlTransport | None = None
    rc = 1
    reason: str | None = None
    detail: str | None = None
    final_text = ""
    last_text = ""
    partial = False
    final_seen = False
    session_id: str | None = None
    error_message: str | None = None
    listener_closed: bool | None = None

    try:
        status.write({"state": "starting", "exit_code": None, "failure": None, "partial": False}, force=True)
        popen_fn = popen or subprocess.Popen
        process_started = clock()
        try:
            process = popen_fn(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            reason, detail = "launch_failed", f"{type(exc).__name__}: {exc}"
            log.write(f"run_deepseek_harness: launch failed: {detail}")
            snapshot = {"state": "failed", "failure": reason, "failure_detail": detail, "exit_code": 1}
            status.write(snapshot, force=True)
            out_path.write_text("", encoding="utf-8")
            return RunResult(1, reason, detail, "", False, snapshot, status_path, log_path, events_path, control_path)

        base["pid"] = process.pid
        try:
            assert process.stdin is not None
            process.stdin.write(task_text)
            process.stdin.close()
        except (BrokenPipeError, OSError, ValueError) as exc:
            log.write(f"run_deepseek_harness: stdin delivery failed: {type(exc).__name__}: {exc}")

        def read_stdout() -> None:
            nonlocal last_text, final_text, final_seen, session_id, error_message
            assert process is not None and process.stdout is not None
            try:
                for line in process.stdout:
                    try:
                        with raw_events_lock:
                            with events_path.open("a", encoding="utf-8", errors="replace") as events_file:
                                events_file.write(line if line.endswith("\n") else line + "\n")
                    except OSError:
                        pass
                    event = parse_event_line(line)
                    if event is None:
                        continue
                    kind = event.get("type")
                    if kind == "session":
                        value = event.get("sessionId") or event.get("session_id")
                        if isinstance(value, str) and value:
                            session_id = value
                    elif kind == "final":
                        final_seen = True
                        final_text = str(event.get("text") or "")
                    elif kind == "text":
                        last_text = str(event.get("text") or "")
                        persist_committed_text(last_text)
                    elif kind == "error":
                        error_message = str(event.get("message") or "dsh error")[:500]
                    elif kind == "thinking":
                        text = str(event.get("thinking") or "")
                        if text:
                            log.write("dsh: reasoning:\n" + text)
                    event_queue.put(event)
            except (OSError, ValueError):
                pass
            finally:
                _reader_finished()

        def read_stderr() -> None:
            assert process is not None and process.stderr is not None
            try:
                for line in process.stderr:
                    with state_lock:
                        stderr_tail.append(line)
                        if len(stderr_tail) > 50:
                            stderr_tail.pop(0)
                    log.write(line.rstrip("\n"))
            except (OSError, ValueError):
                pass
            finally:
                _reader_finished()

        threading.Thread(target=read_stdout, name="dsh-stdout", daemon=True).start()
        threading.Thread(target=read_stderr, name="dsh-stderr", daemon=True).start()

        # Wait for the control plugin to bind the live agent.  If dsh exits
        # first, that is a normal/dsh failure and no supervisor kill is needed.
        wait_started = clock()
        wait_timeout = control_ready_timeout
        if heartbeat.hard_timeout is not None:
            wait_timeout = min(wait_timeout, max(0.0, heartbeat.hard_timeout - (wait_started - process_started)))
        endpoint = wait_control_endpoint(
            control_path,
            process=process,
            timeout=wait_timeout,
            clock=clock,
            sleep=sleep,
        )
        if endpoint is None:
            if process.poll() is None:
                if heartbeat.hard_timeout is not None and clock() - process_started >= heartbeat.hard_timeout:
                    reason, detail = "hard_timeout", (
                        f"explicit hard timeout after {heartbeat.hard_timeout:g}s before control was ready"
                    )
                    rc = HARD_TIMEOUT_EXIT
                else:
                    reason, detail = "control_not_ready", "heartbeat control plugin did not bind before timeout"
                    rc = SUPERVISION_EXIT
                log.write(f"run_deepseek_harness: {detail}")
                try:
                    kill(process.pid)
                    process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            else:
                rc = int(process.returncode if process.returncode is not None else 1)
            supervisor = HeartbeatSupervisor(
                heartbeat, run_id=run_id, clock=clock, started_at=process_started
            )
            if reason:
                supervisor.stop(reason, detail)
        else:
            session_id = endpoint.session_id or session_id
            transport = ControlTransport(
                control_path,
                token=control_token,
                run_id=run_id,
                session_id=session_id,
            )
            supervisor = HeartbeatSupervisor(
                heartbeat,
                run_id=run_id,
                clock=clock,
                ping_fn=transport.ping,
                session_id=session_id,
                started_at=process_started,
            )
            status.write({
                "state": "running",
                "pid": process.pid,
                "control": {
                    "schema": CONTROL_SCHEMA,
                    "host": endpoint.host,
                    "port": endpoint.port,
                    "endpoint_file": str(control_path),
                    "session_id": endpoint.session_id,
                },
                "dsh_conversation_id": session_id,
            }, force=True)
            log.write(
                f"run_deepseek_harness: heartbeat ready control={endpoint.host}:{endpoint.port} "
                f"session={session_id} idle={heartbeat.interval:g}s window={heartbeat.window:g}s "
                f"max_unanswered={heartbeat.max_unanswered} hard_timeout={heartbeat.hard_timeout}"
            )

        # Main supervision loop.  The event queue is fed by the stdout drainer;
        # stderr is written directly to the log so neither pipe can deadlock.
        while True:
            now = clock()
            # A deliberate agent/turn-stopping follow-up wait is surfaced by the
            # control plugin.  While it is active, do not manufacture a status
            # request: the wait itself is not stalled work.  Hard timeout and
            # pending-ping semantics still apply.
            if supervisor is not None and endpoint is not None and supervisor.pending is None:
                live_endpoint = read_control_endpoint(control_path)
                awaiting = bool(live_endpoint and live_endpoint.awaiting_input)
                ended_at = None
                if (
                    not awaiting
                    and supervisor.awaiting_input
                    and live_endpoint is not None
                    and live_endpoint.followup_deadline_epoch is not None
                ):
                    overdue = time.time() - live_endpoint.followup_deadline_epoch
                    if overdue > 0:
                        # The lease expired before the JS side flipped the
                        # descriptor (or the event loop is wedged).  Treat the
                        # deadline as when the wait ended, not "now", so the
                        # next idle check is due immediately.
                        ended_at = now - overdue
                if supervisor.set_awaiting_input(
                    awaiting,
                    now=now,
                    ended_at=ended_at,
                    deadline_iso=live_endpoint.followup_deadline if live_endpoint else None,
                ):
                    if awaiting and last_text:
                        # Expose the most recent committed assistant answer while
                        # the turn waits for input.  Thinking/text streams are
                        # not written; a later answer or the final overwrites it.
                        persist_committed_text(last_text)
                    status.write({
                        "state": "running",
                        "dsh_conversation_id": session_id,
                        "awaiting_input": awaiting,
                        "interim_result": bool(awaiting and last_text),
                        "result_kind": "awaiting_input" if awaiting and last_text else "live",
                        "heartbeat": supervisor.snapshot()["heartbeat"],
                    }, force=True)
                    log.write(
                        f"run_deepseek_harness: {'awaiting follow-up input' if awaiting else 'follow-up wait ended'}"
                    )
            activity_changed = False
            while True:
                try:
                    event = event_queue.get_nowait()
                except queue.Empty:
                    break
                if supervisor is not None:
                    kind = activity_kind(event)
                    if kind is not None:
                        had_pending_ping = supervisor.pending is not None
                        supervisor.note_activity(kind, now=clock(), detail=_event_detail(event))
                        activity_changed = True
                        if had_pending_ping:
                            log.write(
                                f"run_deepseek_harness: reply after ping kind={kind} "
                                f"session={session_id}"
                            )
                    elif event.get("type") == "status":
                        supervisor.note_status_phase(str(event.get("phase") or ""), _event_detail(event))
                        if event.get("phase") == "turn_end":
                            supervisor.turn_end_reason = _bounded(event.get("reason") or {}, 300)
                    if event.get("type") == "final":
                        supervisor.final_seen = True
                    if event.get("type") == "error":
                        supervisor.error = str(event.get("message") or "dsh error")[:500]

            if activity_changed:
                status.write({
                    "state": "running",
                    "dsh_conversation_id": session_id,
                    "heartbeat": supervisor.snapshot()["heartbeat"],
                })

            if process.poll() is not None and event_queue.empty():
                break

            if supervisor is not None:
                action = supervisor.tick(now)
                if action == "ping":
                    if supervisor.pings and supervisor.pings[-1].outcome == "missed":
                        missed = supervisor.pings[-1]
                        log.write(
                            f"run_deepseek_harness: miss {missed.sequence} "
                            f"(consecutive={supervisor.consecutive_unanswered})"
                        )
                    sequence = len(supervisor.pings) + 1
                    message = supervisor.ping_message(sequence, supervisor.idle_seconds(now))
                    record = supervisor.make_ping(message, now=now, session_id=session_id)
                    if record is not None:
                        log.write(
                            f"run_deepseek_harness: ping {record.sequence} queued "
                            f"(delivery_ok={record.delivery_ok} status={record.status_code} "
                            f"error={record.delivery_error})"
                        )
                        status.write({
                            "state": "running",
                            "dsh_conversation_id": session_id,
                            "heartbeat": supervisor.snapshot()["heartbeat"],
                        }, force=True)
                elif action in ("stop", "hard_timeout"):
                    if supervisor.pings and supervisor.pings[-1].outcome == "missed":
                        missed = supervisor.pings[-1]
                        log.write(
                            f"run_deepseek_harness: miss {missed.sequence} "
                            f"(consecutive={supervisor.consecutive_unanswered})"
                        )
                    reason = supervisor.failure
                    detail = supervisor.failure_detail
                    rc = HARD_TIMEOUT_EXIT if action == "hard_timeout" else HEARTBEAT_EXIT
                    log.write(f"run_deepseek_harness: supervisor stop reason={reason} detail={detail}")
                    try:
                        kill(process.pid)
                        process.wait(timeout=10)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    # Drain what arrived during teardown.
                    while True:
                        try:
                            event = event_queue.get_nowait()
                        except queue.Empty:
                            break
                        kind = activity_kind(event)
                        if kind is not None:
                            supervisor.note_activity(kind, now=clock(), detail=_event_detail(event))
                    break

            try:
                sleep(0.2)
            except (OSError, ValueError):
                pass

        # Ensure both reader threads have finished and the pipe is drained.
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                kill(process.pid)
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        readers_done.wait(timeout=5)
        while True:
            try:
                event = event_queue.get_nowait()
            except queue.Empty:
                break
            if supervisor is not None:
                kind = activity_kind(event)
                if kind is not None:
                    supervisor.note_activity(kind, now=clock(), detail=_event_detail(event))
                elif event.get("type") == "status":
                    supervisor.note_status_phase(str(event.get("phase") or ""), _event_detail(event))
                    if event.get("phase") == "turn_end":
                        supervisor.turn_end_reason = _bounded(event.get("reason") or {}, 300)
                if event.get("type") == "final":
                    supervisor.final_seen = True
                if event.get("type") == "error":
                    error_message = str(event.get("message") or "dsh error")[:500]
                    supervisor.error = error_message

        if rc in (HEARTBEAT_EXIT, HARD_TIMEOUT_EXIT, SUPERVISION_EXIT):
            pass
        else:
            code = int(process.returncode if process.returncode is not None else 1)
            if code != 0:
                rc = code
                reason = reason or "dsh_exit_nonzero"
                detail = detail or _tail_text(stderr_tail) or f"dsh exited {code}"
            elif not final_seen:
                rc = 1
                reason = "missing_final"
                detail = "dsh exited 0 without a final event"
            elif not final_text:
                rc = 1
                reason = "empty_final"
                detail = "dsh final event contained no answer"
            elif error_message:
                rc = 1
                reason = "dsh_error"
                detail = error_message
            else:
                rc = 0
                reason = None
                detail = None

        if supervisor is not None and supervisor.turn_end_reason:
            turn_reason = supervisor.turn_end_reason
            if isinstance(turn_reason, dict):
                kind = turn_reason.get("kind") or turn_reason.get("type")
                if kind and kind not in ("completed", "complete"):
                    if rc == 0:
                        rc = 1
                        reason = "turn_not_completed"
                        detail = f"dsh turn ended with {kind}"
        if error_message and rc == 0:
            rc = 1
            reason = "dsh_error"
            detail = error_message

        out_text = final_text if rc == 0 else (final_text or last_text)
        partial = bool(rc != 0 and out_text)
        out_path.write_text(out_text, encoding="utf-8")
        if endpoint is not None:
            listener_closed = _listener_closed(endpoint.host, endpoint.port)
        snapshot = {
            "state": "completed" if rc == 0 else (
                "hard_timeout" if rc == HARD_TIMEOUT_EXIT else (
                    "heartbeat_stopped" if rc == HEARTBEAT_EXIT else "failed"
                )
            ),
            "exit_code": rc,
            "failure": reason,
            "failure_detail": detail,
            "partial": partial,
            "final_event": final_seen,
            "ended_at": _iso(),
            "duration_seconds": round(time.time() - base["started_epoch"], 3),
            "dsh_conversation_id": session_id,
            "awaiting_input": bool(supervisor.awaiting_input) if supervisor else False,
            "interim_result": False,
            "result_kind": "final" if rc == 0 else ("partial" if out_text else "none"),
            "control": {
                "schema": CONTROL_SCHEMA,
                "host": endpoint.host if endpoint else None,
                "port": endpoint.port if endpoint else None,
                "endpoint_file": str(control_path),
                "session_id": endpoint.session_id if endpoint else None,
                "listener_closed": listener_closed,
            },
            "counters": {
                "stdout_events": _count_events(events_path),
                "worker_activity": supervisor.activity_count if supervisor else 0,
            },
            "stderr_tail": _tail_text(stderr_tail),
        }
        if supervisor is not None:
            if not supervisor.stopped:
                supervisor.state = "completed" if rc == 0 else "failed"
            snapshot["heartbeat"] = supervisor.snapshot()["heartbeat"]
            if rc != 0 and supervisor.failure:
                snapshot["failure"] = supervisor.failure
                snapshot["failure_detail"] = supervisor.failure_detail or detail
        status.write(snapshot, force=True)
        log.write(
            f"run_deepseek_harness: end rc={rc} reason={reason} "
            f"partial={partial} duration={snapshot['duration_seconds']:.3f}s"
        )
        return RunResult(
            rc=rc,
            reason=reason,
            detail=detail,
            out_text=out_text,
            partial=partial,
            status=snapshot,
            status_path=status_path,
            log_path=log_path,
            events_path=events_path,
            control_path=control_path,
        )
    finally:
        if process is not None and process.poll() is None:
            try:
                kill(process.pid)
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for stream in (process.stdout, process.stderr, process.stdin) if process is not None else ():
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        log.close()


def _tail_text(lines: Iterable[str], limit: int = 1200) -> str:
    text = "".join(lines).strip()
    return text[-limit:]


def _count_events(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def make_control_token() -> str:
    return secrets.token_hex(32)


def resolve_control_token(env: dict[str, str], token_env: str | None = None) -> str:
    """Return a per-run control token, optionally supplied by a parent process.

    ``token_env`` names an environment variable; the value never enters a
    config, status, control, or log file.  An explicitly named but missing or
    short value is an error rather than a silent fallback, so an orchestrator
    cannot believe it knows a token that the child is not using.
    """
    if not token_env:
        return make_control_token()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
        raise ValueError("control token environment variable name is invalid")
    value = env.get(token_env)
    if not isinstance(value, str) or len(value) < 32:
        raise ValueError(f"{token_env} must contain at least 32 characters")
    return value
