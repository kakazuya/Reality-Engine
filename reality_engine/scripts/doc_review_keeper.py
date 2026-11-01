"""Keep the T-045 doc loop going overnight with no model call.

Waits for a running loop's pid to end, then restarts the loop after a failure or a crash.  Done,
the budget stop, the refusal to run on main and a file too large for one batch all end the keeper;
so do 12 restarts.  Its lines go to the loop's log, prefixed ``KEEPER``; a final one says why it ended.

    python reality_engine/scripts/doc_review_keeper.py --root <worktree> --log <file> --wait-pid N
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import doc_review_loop as loop  # noqa: E402
import job_watch  # noqa: E402

FINAL_CODES = {0: "done", 2: "refused main", 3: "budget reached", 4: "file too large for a batch"}
MAX_RESTARTS = 12
RESTART_WAIT = 20 * 60


def finished(rc: int) -> str | None:
    """Why the keeper should stop after this exit code, or None to restart."""
    return FINAL_CODES.get(rc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--wait-pid", type=int)
    args = parser.parse_args(argv)
    script = str(Path(loop.__file__).resolve())
    while args.wait_pid and job_watch._pid_alive(args.wait_pid):
        time.sleep(30)
    if args.wait_pid and "DONE" in args.log.read_text(encoding="utf-8")[-400:]:
        loop.log(args.log, "KEEPER ended: done")
        return 0
    if args.wait_pid and "STOPPED budget" in args.log.read_text(encoding="utf-8")[-400:]:
        loop.log(args.log, "KEEPER ended: budget reached")
        return 0
    for attempt in range(1, MAX_RESTARTS + 1):
        loop.log(args.log, f"KEEPER restart {attempt} in {RESTART_WAIT // 60} min")
        time.sleep(RESTART_WAIT)
        rc = subprocess.run([sys.executable, script, "--root", str(args.root), "--log", str(args.log)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        why = finished(rc)
        if why:
            loop.log(args.log, f"KEEPER ended: {why}")
            return 0
    loop.log(args.log, f"KEEPER ended: gave up after {MAX_RESTARTS} restarts")
    return 1


if __name__ == "__main__":
    sys.exit(main())
