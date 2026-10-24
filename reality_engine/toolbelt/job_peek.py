"""Compact view of a dsh job directory without loading whole event files.

Reads only bounded slices: ``status.json`` (bounded), ``heartbeat.json``,
the last progress digest, the tail of ``result.md.events.jsonl`` for tool
counts, and the head of ``result.md``.  One call answers "what phase, how long,
which tools, what happened last, what is the result so far".

Examples:
    python -m reality_engine.toolbelt.job_peek \\
        C:\\Users\\warri\\Downloads\\Info_Diffusion_Model\\plugins\\dsh-worker\\runtime\\jobs\\<job_id>
    python -m reality_engine.toolbelt.job_peek <job_dir> --activity 20 --format table

    from reality_engine.toolbelt.job_peek import peek
    view = peek("<job_dir>")
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._common import add_format, main_guard, print_result

FINISHED = {"finished", "failed", "cancelled", "canceled", "done", "complete", "completed", "error"}
DEFAULT_TAIL = 262_144


def _read_json(path: Path, max_bytes: int = 262_144) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes)
        value = json.loads(data.decode("utf-8", "replace"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _read_head(path: Path, max_bytes: int = 4096) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(max_bytes).decode("utf-8", "replace")
    except OSError:
        return ""


def _tail_lines(path: Path, max_bytes: int = DEFAULT_TAIL) -> tuple[list[str], int]:
    """Read at most ``max_bytes`` from the end; the first partial line is dropped."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()
            data = handle.read()
    except OSError:
        return [], 0
    return data.decode("utf-8", "replace").splitlines(), len(data)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _hint(event: dict[str, Any]) -> str | None:
    args = event.get("input")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        return None
    # Shell command text is never echoed (it can carry tokens); the human
    # description is enough to identify the step.
    for key in ("file_path", "path", "pattern", "description"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value[:160]
    return None


def _tool_counts_from_events(lines: list[str]) -> tuple[Counter, int]:
    counts: Counter = Counter()
    calls = 0
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "tool_call":
            calls += 1
            counts[str(event.get("tool") or "?")] += 1
    return counts, calls


def _activity_from_events(lines: list[str], limit: int) -> list[dict[str, Any]]:
    out = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind not in ("tool_call", "tool_result", "text", "status", "error", "step_output"):
            continue
        item = {"kind": kind}
        if event.get("tool"):
            item["tool"] = event["tool"]
        hint = _hint(event)
        if hint:
            item["hint"] = hint
        out.append(item)
    return out[-limit:]


def peek(job_dir: str | Path, tail_bytes: int = DEFAULT_TAIL, activity: int = 10) -> dict[str, Any]:
    """Return the compact job view; all reads are bounded."""
    root = Path(job_dir)
    status = _read_json(root / "status.json")
    if status is None:
        raise FileNotFoundError(f"status.json not found or unreadable in {root}")
    heartbeat = _read_json(root / "heartbeat.json") or {}
    live = status.get("heartbeat_live") or heartbeat
    phase = status.get("phase") or live.get("state")
    started = _parse_iso(status.get("started_at") or live.get("started_at"))
    updated = _parse_iso(status.get("updated_at") or live.get("last_activity_at"))
    now = datetime.now(timezone.utc)
    end = now if (phase or "").lower() not in FINISHED else (updated or now)
    elapsed = (end - started).total_seconds() if started else None

    progress: dict[str, Any] | None = None
    progress_lines, _ = _tail_lines(root / "progress.jsonl", tail_bytes)
    for line in reversed(progress_lines):
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            progress = candidate
            break

    events_path = root / "result.md.events.jsonl"
    event_lines, scanned = _tail_lines(events_path, tail_bytes)
    counts, calls = _tool_counts_from_events(event_lines)
    windowed = True
    if progress:
        by_tool = progress.get("tool_calls_by_tool")
        if isinstance(by_tool, dict) and by_tool:
            counts = Counter({str(k): int(v) for k, v in by_tool.items()})
            windowed = False
        calls = int(progress.get("tool_calls") or calls)

    hb_events = live.get("events") if isinstance(live.get("events"), list) else []
    if hb_events:
        activity_rows = [{"at": e.get("at"), "kind": e.get("kind")}
                         for e in hb_events[-max(1, activity):] if isinstance(e, dict)]
    else:
        activity_rows = _activity_from_events(event_lines, max(1, activity))

    result_path = root / "result.md"
    result_head = _read_head(result_path)
    progress_md = _read_head(root / "progress.md", 4096) if not progress else None
    return {
        "job_id": status.get("job_id") or root.name,
        "phase": phase,
        "outcome": status.get("outcome"),
        "exit_code": status.get("exit_code"),
        "started_at": status.get("started_at") or live.get("started_at"),
        "updated_at": status.get("updated_at"),
        "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
        "elapsed": _duration(elapsed),
        "tool_calls": calls,
        "tool_calls_by_tool": dict(counts.most_common()),
        "tool_calls_window": windowed,
        "events_bytes_scanned": scanned,
        "activity": activity_rows,
        "progress": progress,
        "progress_md_head": progress_md,
        "result_head": "\n".join(result_head.splitlines()[:30]),
        "result_bytes": result_path.stat().st_size if result_path.exists() else 0,
        "job_dir": str(root),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m reality_engine.toolbelt.job_peek",
        description="Compact phase/elapsed/tools/activity/progress/result view of a dsh job dir.")
    ap.add_argument("job_dir", help="dsh job directory (holds status.json and result.md)")
    ap.add_argument("--tail-bytes", type=int, default=DEFAULT_TAIL,
                    help=f"bytes read from each event/progress file tail (default: {DEFAULT_TAIL})")
    ap.add_argument("--activity", type=int, default=10, help="activity lines (default: 10)")
    add_format(ap)
    args = ap.parse_args(argv)
    result = peek(args.job_dir, args.tail_bytes, args.activity)
    print_result(result, args.format)
    return 0


if __name__ == "__main__":
    main_guard(main)
