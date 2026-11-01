"""Stop and PreCompact hooks for this project.

``stop`` blocks one stop while a job is stalled, so a session cannot end its turn past it.  It never
blocks twice (``stop_hook_active``), and never in the Haiku doc loop.  ``precompact`` prints what a
summary must keep.  Every error exits 0: a hook must not break a session.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

KEEP = (
    "Keep in the summary: the exact next action, every running job and its id, uncommitted files, "
    "and each ruling Shivam gave in this session. Write the next action into tasks/STATE.md if it is not there."
)


def stop_output(payload: dict, lines: list[str]) -> str:
    if payload.get("stop_hook_active") or os.environ.get("DOC_REVIEW_LOOP"):
        return ""
    stalled = [line for line in lines if line.startswith("STALLED")]
    if not stalled:
        return ""
    return json.dumps({"decision": "block", "reason": "A job has stalled; check it before stopping:\n" + "\n".join(stalled)})


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if args[:1] == ["precompact"]:
            print(KEEP)
        elif args[:1] == ["stop"]:
            payload = json.loads(sys.stdin.read() or "{}")
            if not (payload.get("stop_hook_active") or os.environ.get("DOC_REVIEW_LOOP")):
                import job_watch

                output = stop_output(payload, job_watch.status())
                if output:
                    print(output)
    except Exception as exc:
        print(f"session_hooks: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
