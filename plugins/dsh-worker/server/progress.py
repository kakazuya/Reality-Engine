"""Bounded, incremental progress summary from a dsh ``--json`` event stream.

``result.md`` is written incrementally by the harness, so "file non-empty" is
not completion.  This module reads ``<out>.events.jsonl`` (the raw dsh event
stream) incrementally and counts committed worker activity: tool calls by
tool, failed tool results, model steps, output tokens, the last tool and the
files the worker most recently wrote or edited.  Each call reads at most
``MAX_SCAN_BYTES`` new bytes and remembers its offset, so a stdout flood or a
multi-hundred-MB stream never blocks a status read.  Only complete lines are
consumed; a half-written trailing line is left for the next call.

Nothing here returns reasoning/thinking text, tool output, shell commands or
file contents: only tool names, counts, file paths and short descriptions.
"""
from __future__ import annotations

import json
import os
import threading
from collections import Counter
from pathlib import Path
from typing import Any

MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
RECENT_FILES = 10
WRITE_TOOLS = frozenset({"write", "edit", "multiedit", "multi_edit", "apply_patch", "notebook_edit"})


class _State:
    __slots__ = (
        "offset", "identity", "tool_calls", "by_tool", "tool_failures", "steps",
        "output_tokens", "last_input_tokens", "turns", "text_events", "thinking_events",
        "errors", "last_error", "last_tool", "last_tool_hint", "recent_files",
        "final_seen", "lines", "unparsed_lines", "session_id",
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

    def scan(self, path: Path, max_bytes: int = MAX_SCAN_BYTES) -> dict[str, Any]:
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
            return self._summary(state, st.st_size, caught_up)

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
    def _summary(state: _State, size: int, caught_up: bool) -> dict[str, Any]:
        return {
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
            "tool_calls_by_tool": dict(state.by_tool.most_common(20)),
            "tool_failures": state.tool_failures,
            "last_tool": state.last_tool,
            "last_tool_target": state.last_tool_hint,
            "recent_file_writes": list(reversed(state.recent_files)),
            "text_events": state.text_events,
            "thinking_events": state.thinking_events,
            "errors": state.errors,
            "last_error": state.last_error,
            "final_event_seen": state.final_seen,
            "dsh_session_id": state.session_id,
        }


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
