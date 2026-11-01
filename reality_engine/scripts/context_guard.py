"""PostToolUse hook: tell Claude to wrap up at 400k context tokens, and again at 440k.

Reads the hook JSON from stdin (``transcript_path``, ``session_id``, ``cwd``), tails the last
256 KB of the transcript and sums the last assistant message's input, cache-read and
cache-creation tokens.  At 400,000 it prints one PostToolUse ``additionalContext`` payload per
session; at 440,000 it prints one more.  Below 400,000 it prints nothing.  It must never fail a
tool call: every error exits 0.  Standard library only, so it stays fast.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

TAIL_BYTES = 256 * 1024
THRESHOLDS = (400_000, 440_000)
SESSION_LIMIT = 450_000
MESSAGES = {
    400_000: (
        "Context is at {tokens:,} tokens of the {limit:,} session limit. Write the wrap-up NOW: "
        "commit the work, write the exact next action into tasks/STATE.md, run the doc sweep "
        "(`python reality_engine/scripts/doc_gate.py --sweep`) and update every doc this work "
        "touched. Start nothing new."
    ),
    440_000: (
        "Context is at {tokens:,} tokens: the {limit:,} session limit is close. Stop work now. "
        "Commit what passes, put the next action in tasks/STATE.md, run the doc sweep and finish "
        "the report. Do not start or continue anything else."
    ),
}


def last_token_usage(transcript: Path) -> int | None:
    """input + cache-read + cache-creation of the last assistant message, or None."""
    try:
        with Path(transcript).open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        total = 0
        for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total += int(value)
        return total
    return None


def _marker_dir(root: Path) -> Path:
    return Path(root) / ".tmp" / "context_guard"


def evaluate(tokens: int, session_id: str, root: Path) -> str | None:
    """The additionalContext text this reading fires (and its marker), or None."""
    fired = [threshold for threshold in THRESHOLDS if tokens >= threshold]
    if not fired:
        return None
    marker_dir = _marker_dir(root)
    name = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "session")[:80]
    try:
        marker_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    for threshold in reversed(fired):
        marker = marker_dir / f"{name}_{threshold}"
        if marker.exists():
            continue
        try:
            # A session first seen above 440k gets the 440k message only once, not
            # the 400k one afterwards.
            for consumed in THRESHOLDS:
                if consumed <= threshold:
                    (marker_dir / f"{name}_{consumed}").write_text(str(tokens), encoding="utf-8")
        except OSError:
            return None
        return MESSAGES[threshold].format(tokens=tokens, limit=SESSION_LIMIT)
    return None


def _payload(text: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                              "additionalContext": text}})


def main() -> int:
    try:
        hook = json.loads(sys.stdin.buffer.read() or b"{}")
        if not isinstance(hook, dict):
            return 0
        transcript = hook.get("transcript_path")
        if not isinstance(transcript, str) or not transcript:
            return 0
        tokens = last_token_usage(Path(transcript))
        if tokens is None:
            return 0
        root = Path(hook.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        text = evaluate(tokens, str(hook.get("session_id") or ""), root)
        if text:
            print(_payload(text))
    except Exception:  # a hook must never fail the tool call it observes
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
