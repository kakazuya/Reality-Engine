"""Stop and PreCompact hooks for this project.

``stop`` blocks one stop while a job is stalled, while a finished job or a failure still needs
review or an ack, or while a job runs with no live ``job_watch wait`` recorded.  It reads the
uncapped line list, so a review that ranks below the 12-line prompt cap still blocks.  It never
blocks twice (``stop_hook_active``), never in the Haiku doc loop, and it never waits itself.
``precompact`` prints what a summary must keep.  Every error exits 0: a hook must not break a
session.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import job_watch  # noqa: E402  (the hook runs as a script: its folder is the path)

KEEP = (
    "Keep in the summary: the exact next action, every running job and its id, uncommitted files, "
    "and each ruling Shivam gave in this session. Write the next action into tasks/STATE.md if it is not there."
)
ARM_WAIT = "arm a wait: run `python reality_engine/scripts/job_watch.py wait` with run_in_background"


def stop_output(payload: dict, lines: list[str], live_work: bool = False, waiter: bool = False) -> str:
    if payload.get("stop_hook_active") or os.environ.get("DOC_REVIEW_LOOP"):
        return ""
    stalled = [line for line in lines if line.startswith("STALLED")]
    if stalled:
        return _block("A job has stalled; check it before stopping:\n" + "\n".join(stalled))
    review = [line for line in lines if line.startswith(("FINISHED, NEEDS REVIEW", "ENDED BADLY"))]
    if review:
        return _block("review or ack these before stopping:\n" + "\n".join(review))
    if live_work and not waiter:
        return _block(ARM_WAIT)
    return ""


def _block(reason: str) -> str:
    return json.dumps({"decision": "block", "reason": reason})


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if args[:1] == ["precompact"]:
            print(KEEP)
        elif args[:1] == ["stop"]:
            payload = json.loads(sys.stdin.read() or "{}")
            if not (payload.get("stop_hook_active") or os.environ.get("DOC_REVIEW_LOOP")):
                lines = job_watch.status(limit=None)
                live_work = job_watch.live_jobs() or job_watch.live_registered()
                output = stop_output(payload, lines, live_work, job_watch.waiter_alive())
                if output:
                    print(output)
    except Exception as exc:
        print(f"session_hooks: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
