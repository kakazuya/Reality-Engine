"""Bounded, incremental progress from a dsh ``--json`` event stream.

``result.md`` is written incrementally by the harness, so "file non-empty" is
not completion.  This module reads ``<out>.events.jsonl`` (the raw dsh event
stream) incrementally and counts committed worker activity: tool calls by
tool, failed tool results, model steps, output tokens, the last tool and the
files the worker most recently wrote or edited.  Each call reads at most
``MAX_SCAN_BYTES`` new bytes and remembers its offset, so a stdout flood or a
multi-hundred-MB stream never blocks a status read.  Only complete lines are
consumed; a half-written trailing line is left for the next call.

It also owns the supervisor's model-free progress digests (``DigestWriter``):
one compact JSON line every interval in ``progress.jsonl`` plus a rewritten
``progress.md``.  A digest is bookkeeping, never a message to the worker and
never a model call, so an update exists with no Claude/Codex session open.

Nothing here returns reasoning/thinking text, tool output, shell commands or
file contents: only tool names, counts, file paths and short descriptions.
The digest deliberately also carries the last committed assistant text lines
(the worker's own answer stream), which is what makes it readable to a human.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from store import (
    JOB_LOCK_NAME,
    append_jsonl_locked,
    atomic_write_text,
    iso,
    parse_iso,
    read_text_bounded_tail,
    utc_now,
)

MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
RECENT_FILES = 10
WRITE_TOOLS = frozenset({"write", "edit", "multiedit", "multi_edit", "apply_patch", "notebook_edit"})

# Progress digests (supervisor, model-free).
PROGRESS_SCHEMA = "dsh-worker-progress/1"
PROGRESS_FILE = "progress.jsonl"
PROGRESS_MD_FILE = "progress.md"
PROGRESS_NOTES_FILE = "PROGRESS_NOTES.md"
STALL_SECONDS = 20 * 60
TEXT_TAIL_LINES = 3
MAX_TEXT_LINE = 160
DIGEST_MD_HISTORY = 6
DIGEST_READ_BYTES = 1_048_576
NOTES_READ_BYTES = 4_096
MAX_DIGESTS = 50


class _State:
    __slots__ = (
        "offset", "identity", "tool_calls", "by_tool", "tool_failures", "steps",
        "output_tokens", "last_input_tokens", "turns", "text_events", "thinking_events",
        "errors", "last_error", "last_tool", "last_tool_hint", "recent_files",
        "file_writes", "text_tail", "final_seen", "lines", "unparsed_lines",
        "session_id",
    )

    def __init__(self) -> None:
        self.offset = 0
        self.identity: tuple[int, int] | None = None
        self.tool_calls = 0
        self.by_tool: Counter[str] = Counter()
        self.tool_failures = 0
        self.steps = 0
        self.output_tokens = 0
        self.last_input_tokens: int | None = None
        self.turns = 0
        self.text_events = 0
        self.thinking_events = 0
        self.errors = 0
        self.last_error: str | None = None
        self.last_tool: str | None = None
        self.last_tool_hint: str | None = None
        self.recent_files: list[str] = []
        self.file_writes = 0
        self.text_tail: list[str] = []
        self.final_seen = False
        self.lines = 0
        self.unparsed_lines = 0
        self.session_id: str | None = None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _tool_input(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("input")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _hint(tool: str, args: dict[str, Any]) -> str | None:
    for key in ("file_path", "path", "notebook_path", "pattern"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value[:300]
    # Shell tools: the human description only, never the command text, which
    # may contain anything the worker typed.
    value = args.get("description")
    if isinstance(value, str) and value:
        return value[:160]
    return None


class EventScanner:
    """Per-file incremental scanner; safe to share across threads."""

    def __init__(self) -> None:
        self._states: dict[str, _State] = {}
        self._lock = threading.Lock()

    def scan(
        self,
        path: Path,
        max_bytes: int = MAX_SCAN_BYTES,
        *,
        top_tools: int | None = 20,
        text: bool = False,
    ) -> dict[str, Any]:
        """Scan new bytes and return cumulative counters.

        ``top_tools`` caps the by-tool map (``None`` keeps every tool name, for
        digest deltas); ``text`` adds the last committed assistant text lines,
        which only the digest wants.
        """
        key = os.path.normcase(str(path))
        with self._lock:
            state = self._states.get(key)
            try:
                st = path.stat()
            except OSError:
                return {"available": False, "reason": "events_file_missing"}
            identity = (getattr(st, "st_ino", 0) or 0, getattr(st, "st_ctime_ns", 0) or 0)
            if state is None or st.st_size < state.offset or (
                state.identity is not None and identity[0] and identity != state.identity
            ):
                # New, truncated or replaced file: rescan from the start.
                state = _State()
                self._states[key] = state
            state.identity = identity
            caught_up = True
            if st.st_size > state.offset:
                try:
                    with path.open("rb") as fh:
                        fh.seek(state.offset)
                        chunk = fh.read(max_bytes)
                except OSError as exc:
                    return {"available": False, "reason": f"events_unreadable:{type(exc).__name__}"}
                end = chunk.rfind(b"\n")
                if end < 0 and len(chunk) >= max_bytes:
                    # One line longer than the window: skip it rather than stall.
                    state.offset += len(chunk)
                    state.unparsed_lines += 1
                elif end >= 0:
                    for line in chunk[: end + 1].splitlines():
                        self._consume(state, line)
                    state.offset += end + 1
                caught_up = state.offset >= st.st_size
            return self._summary(state, st.st_size, caught_up, top_tools, text)

    @staticmethod
    def _consume(state: _State, line: bytes) -> None:
        if not line.strip():
            return
        state.lines += 1
        if len(line) > MAX_LINE_BYTES:
            state.unparsed_lines += 1
            return
        try:
            event = json.loads(line.decode("utf-8", errors="replace"))
        except (ValueError, TypeError):
            state.unparsed_lines += 1
            return
        if not isinstance(event, dict):
            state.unparsed_lines += 1
            return
        kind = event.get("type")
        if kind == "tool_call":
            tool = str(event.get("tool") or event.get("name") or "unknown")[:80]
            args = _tool_input(event)
            state.tool_calls += 1
            state.by_tool[tool] += 1
            state.last_tool = tool
            state.last_tool_hint = _hint(tool, args)
            if tool.lower() in WRITE_TOOLS:
                target = args.get("file_path") or args.get("path") or args.get("notebook_path")
                if isinstance(target, str) and target:
                    target = target[:300]
                    state.file_writes += 1
                    if target in state.recent_files:
                        state.recent_files.remove(target)
                    state.recent_files.append(target)
                    state.recent_files = state.recent_files[-RECENT_FILES:]
        elif kind == "tool_result":
            status = event.get("status")
            if event.get("ok") is False or (isinstance(status, str) and status not in ("completed", "ok", "success")):
                state.tool_failures += 1
        elif kind == "status":
            phase = event.get("phase")
            if phase == "step_end":
                state.steps += 1
                usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
                state.output_tokens += _int(usage.get("outputTokens") or usage.get("output_tokens"))
                inp = usage.get("inputTokens") or usage.get("input_tokens")
                if inp is not None:
                    state.last_input_tokens = _int(inp)
            elif phase == "turn_start":
                state.turns += 1
        elif kind == "text":
            state.text_events += 1
            text = event.get("text")
            if isinstance(text, str) and text.strip():
                lines = [
                    " ".join(line.split())[:MAX_TEXT_LINE]
                    for line in text.splitlines()
                    if line.strip()
                ]
                if lines:
                    state.text_tail = (state.text_tail + lines)[-TEXT_TAIL_LINES:]
        elif kind == "thinking":
            state.thinking_events += 1
        elif kind == "final":
            state.final_seen = True
        elif kind == "error":
            state.errors += 1
            state.last_error = str(event.get("message") or "dsh error")[:300]
        elif kind == "session":
            sid = event.get("sessionId") or event.get("session_id")
            if isinstance(sid, str):
                state.session_id = sid[:200]

    @staticmethod
    def _summary(
        state: _State,
        size: int,
        caught_up: bool,
        top_tools: int | None = 20,
        text: bool = False,
    ) -> dict[str, Any]:
        summary = {
            "available": True,
            "events_bytes": size,
            "scanned_bytes": state.offset,
            "caught_up": caught_up,
            "events": state.lines,
            "unparsed_lines": state.unparsed_lines,
            "turns": state.turns,
            "model_steps": state.steps,
            "output_tokens": state.output_tokens,
            "last_input_tokens": state.last_input_tokens,
            "tool_calls": state.tool_calls,
            "tool_calls_by_tool": dict(state.by_tool.most_common(top_tools)),
            "tool_failures": state.tool_failures,
            "last_tool": state.last_tool,
            "last_tool_target": state.last_tool_hint,
            "recent_file_writes": list(reversed(state.recent_files)),
            "file_writes": state.file_writes,
            "text_events": state.text_events,
            "thinking_events": state.thinking_events,
            "errors": state.errors,
            "last_error": state.last_error,
            "final_event_seen": state.final_seen,
            "dsh_session_id": state.session_id,
        }
        if text:
            summary["worker_text_tail"] = list(state.text_tail)
        return summary


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def latest_note(job_dir: Path) -> str | None:
    """Latest line of the worker's cooperative PROGRESS_NOTES.md, if any."""
    text = read_text_bounded_tail(Path(job_dir) / PROGRESS_NOTES_FILE, NOTES_READ_BYTES)
    for line in reversed(text.splitlines()):
        clean = " ".join(line.split())
        if clean:
            return clean[:300]
    return None


def digest_line(record: dict[str, Any] | None) -> str | None:
    """One compact human line for one digest (also the list_workers summary)."""
    if not isinstance(record, dict):
        return None
    parts = [str(record.get("phase") or "?")]
    if record.get("final"):
        parts.append("final")
    elapsed = record.get("elapsed_seconds")
    if elapsed is not None:
        parts.append(f"elapsed {fmt_duration(elapsed)}")
    if record.get("events_available"):
        total = int(record.get("tool_calls") or 0)
        delta = int(record.get("tool_calls_delta") or 0)
        parts.append(f"{total} tool calls (+{delta})")
        last_tool = record.get("last_tool")
        if last_tool:
            target = record.get("last_tool_target")
            parts.append(
                f"last {last_tool}" + (f" on {_clip(str(target), 120)}" if target else "")
            )
    written = int(record.get("files_written_count") or 0)
    if written:
        parts.append(f"{written} file write{'s' if written != 1 else ''}")
    idle = record.get("idle_seconds")
    if idle is not None:
        parts.append(f"idle {fmt_duration(idle)}")
    if record.get("stall"):
        parts.append("STALL no activity > 20m")
    lease = record.get("lease_seconds_left")
    if lease is not None:
        parts.append(f"lease {fmt_duration(lease)} left")
    note = record.get("note")
    if note:
        parts.append(f"note: {_clip(str(note), 140)}")
    return " · ".join(parts)


def _by_tool_text(values: dict[str, Any], limit: int = 6) -> str:
    pairs = sorted(
        ((str(name), int(count or 0)) for name, count in values.items()),
        key=lambda pair: (-pair[1], pair[0]),
    )[:limit]
    return ", ".join(f"{name} {count}" for name, count in pairs)


def _digest_section(record: dict[str, Any]) -> list[str]:
    lines = [
        f"## Digest {record.get('digest')} — {record.get('at')}",
        "",
        f"- phase: {record.get('phase')}"
        + (" (final)" if record.get("final") else ""),
        f"- elapsed: {fmt_duration(record.get('elapsed_seconds'))}"
        f" · idle: {fmt_duration(record.get('idle_seconds'))}"
        f" · lease left: {fmt_duration(record.get('lease_seconds_left'))}"
        f" · stall: {'yes' if record.get('stall') else 'no'}",
    ]
    if record.get("events_available"):
        tools = int(record.get("tool_calls") or 0)
        delta = int(record.get("tool_calls_delta") or 0)
        steps = int(record.get("model_steps") or 0)
        steps_delta = int(record.get("model_steps_delta") or 0)
        tokens = int(record.get("output_tokens") or 0)
        tokens_delta = int(record.get("output_tokens_delta") or 0)
        lines.append(
            f"- tool calls: {tools} (+{delta}) · model steps: {steps} (+{steps_delta})"
            f" · output tokens: {tokens:,} (+{tokens_delta:,})"
        )
        by_tool = record.get("tool_calls_by_tool")
        if isinstance(by_tool, dict) and by_tool:
            lines.append(f"- by tool: {_by_tool_text(by_tool)}")
        delta_by_tool = record.get("tool_calls_by_tool_delta")
        if isinstance(delta_by_tool, dict) and delta_by_tool:
            lines.append(f"- new since last digest: {_by_tool_text(delta_by_tool)}")
        last_tool = record.get("last_tool")
        if last_tool:
            target = record.get("last_tool_target")
            lines.append(
                f"- last tool: {last_tool}" + (f" → {_clip(str(target), 200)}" if target else "")
            )
        written = record.get("files_written")
        if isinstance(written, list) and written:
            count = int(record.get("files_written_count") or len(written))
            listed = ", ".join(_clip(str(path), 120) for path in written)
            extra = max(0, count - len(written))
            lines.append(
                f"- files written since last digest ({count}): {listed}"
                + (f" (+{extra} more)" if extra else "")
            )
    else:
        lines.append("- event stream: not available (data job or no dsh --json stream yet)")
    note = record.get("note")
    lines.append(f"- worker note: {note}" if note else "- worker note: none")
    text_tail = record.get("worker_text_tail")
    if isinstance(text_tail, list) and text_tail:
        lines.append("- worker text:")
        lines.extend(f"  > {line}" for line in text_tail)
    return lines


def _render_markdown(job_id: str, history: list[dict[str, Any]]) -> str:
    """Latest digest expanded, then the previous six as one-line entries."""
    latest = history[-1]
    lines = [
        f"# Progress — {job_id}",
        "",
        f"**{digest_line(latest)}**",
        "",
        *_digest_section(latest),
        "",
    ]
    earlier = history[:-1]
    if earlier:
        lines.append(f"## Earlier ({len(earlier)})")
        lines.append("")
        for record in reversed(earlier):
            lines.append(f"- {record.get('at')} — {digest_line(record)}")
        lines.append("")
    return "\n".join(lines)


class DigestWriter:
    """One job's model-free progress digests, driven by the supervisor loop.

    ``tick`` is cheap between intervals and only reads bytes appended to the
    event stream since the previous digest.  Digests are appended under the
    per-job record lock so a concurrent MCP reader never sees half a line.
    """

    def __init__(
        self,
        job_dir: Path,
        job_id: str,
        started_at: Any,
        interval_seconds: int,
        *,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.job_dir = Path(job_dir)
        self.job_id = job_id
        self.started_at = parse_iso(started_at)
        self.interval_seconds = int(interval_seconds)
        self._clock = clock
        self._monotonic = monotonic
        self._scanner = EventScanner()
        self._next_due: float | None = None
        self._previous: dict[str, Any] = {}
        self._history: list[dict[str, Any]] = []

    def tick(
        self,
        *,
        phase: str,
        last_activity: datetime | None = None,
        lease_remaining: float | None = None,
        final: bool = False,
    ) -> dict[str, Any] | None:
        """Emit a digest when one is due (or unconditionally on ``final``)."""
        if not final:
            now = self._monotonic()
            if self._next_due is None:
                self._next_due = now + self.interval_seconds
                return None
            if now < self._next_due:
                return None
            self._next_due = now + self.interval_seconds
        return self.emit(
            phase=phase,
            last_activity=last_activity,
            lease_remaining=lease_remaining,
            final=final,
        )

    def emit(
        self,
        *,
        phase: str,
        last_activity: datetime | None = None,
        lease_remaining: float | None = None,
        final: bool = False,
    ) -> dict[str, Any]:
        now = self._clock()
        events = self._scanner.scan(
            self.job_dir / "result.md.events.jsonl", top_tools=None, text=True
        )
        available = bool(events.get("available"))
        tools = int(events.get("tool_calls") or 0) if available else 0
        by_tool = dict(events.get("tool_calls_by_tool") or {}) if available else {}
        steps = int(events.get("model_steps") or 0) if available else 0
        tokens = int(events.get("output_tokens") or 0) if available else 0
        file_writes = int(events.get("file_writes") or 0) if available else 0
        recent = list(events.get("recent_file_writes") or []) if available else []
        previous = self._previous
        previous_by_tool = dict(previous.get("by_tool") or {})
        delta_by_tool = {
            name: count - int(previous_by_tool.get(name, 0))
            for name, count in by_tool.items()
        }
        known_files = set(previous.get("recent_files") or [])
        # ponytail: names come from the 10-file recent window, so more than 10
        # writes in one interval list a subset (the count stays exact). Bump
        # RECENT_FILES or keep a per-interval list if every path must show.
        written = [path for path in recent if path not in known_files]
        elapsed = (
            max(0.0, (now - self.started_at).total_seconds())
            if self.started_at is not None
            else None
        )
        idle = (
            max(0.0, (now - last_activity).total_seconds())
            if last_activity is not None
            else None
        )
        display_phase = str(phase or "unknown")
        record: dict[str, Any] = {
            "schema": PROGRESS_SCHEMA,
            "job_id": self.job_id,
            "digest": int(previous.get("digest") or 0) + 1,
            "at": iso(now),
            "final": bool(final),
            "phase": display_phase,
            "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
            "events_available": available,
            "tool_calls": tools,
            "tool_calls_delta": max(0, tools - int(previous.get("tools") or 0)),
            "tool_calls_by_tool": by_tool,
            "tool_calls_by_tool_delta": {
                name: count for name, count in sorted(delta_by_tool.items()) if count > 0
            },
            "model_steps": steps,
            "model_steps_delta": max(0, steps - int(previous.get("steps") or 0)),
            "output_tokens": tokens,
            "output_tokens_delta": max(0, tokens - int(previous.get("tokens") or 0)),
            "last_tool": events.get("last_tool") if available else None,
            "last_tool_target": events.get("last_tool_target") if available else None,
            "files_written": written,
            "files_written_count": max(0, file_writes - int(previous.get("files") or 0)),
            "file_writes_total": file_writes,
            "idle_seconds": round(idle, 1) if idle is not None else None,
            "stall": bool(not final and idle is not None and idle > STALL_SECONDS),
            "lease_seconds_left": (
                round(float(lease_remaining), 1)
                if isinstance(lease_remaining, (int, float))
                and not isinstance(lease_remaining, bool)
                else None
            ),
            "worker_text_tail": (
                list(events.get("worker_text_tail") or []) if available else []
            ),
            "note": latest_note(self.job_dir),
        }
        append_jsonl_locked(
            self.job_dir / PROGRESS_FILE, record, self.job_dir / JOB_LOCK_NAME
        )
        self._previous = {
            "digest": record["digest"],
            "tools": tools,
            "by_tool": by_tool,
            "steps": steps,
            "tokens": tokens,
            "files": file_writes,
            "recent_files": recent,
        }
        self._history.append(record)
        self._history = self._history[-(DIGEST_MD_HISTORY + 1):]
        atomic_write_text(
            self.job_dir / PROGRESS_MD_FILE,
            _render_markdown(self.job_id, self._history),
        )
        return record


def read_digests(
    job_dir: Path,
    limit: int = MAX_DIGESTS,
    max_bytes: int = DIGEST_READ_BYTES,
) -> list[dict[str, Any]]:
    """Newest-first digests from ``progress.jsonl``; malformed lines are skipped."""
    text = read_text_bounded_tail(Path(job_dir) / PROGRESS_FILE, max_bytes)
    records: list[dict[str, Any]] = []
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and value.get("schema") == PROGRESS_SCHEMA:
            records.append(value)
            if len(records) >= limit:
                break
    return records
