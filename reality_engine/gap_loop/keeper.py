"""Keep the T-048 gap loop going overnight with no model call.

Waits for a running loop's pid to end, then restarts the loop after a failure or a crash.  DONE,
the budget stop and a refused sandbox end the keeper; so do 12 restarts.  Its lines go to the
loop's log, prefixed ``KEEPER``.

    python -m reality_engine.gap_loop.keeper --sandbox D:\\RealityEngine\\sandbox\\kec_loop \\
        --log D:\\RealityEngine\\sandbox\\kec_loop\\logs\\loop.log --wait-pid N
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from reality_engine.gap_loop.loop import REPO_ROOT, log
from reality_engine.scripts import job_watch

FINAL_CODES = {3: "budget reached", 4: "refused sandbox or prepare"}
MAX_RESTARTS = 12
RESTART_WAIT = 20 * 60


def finished(rc: int, log_text: str) -> str | None:
    if "DONE" in log_text[-600:]:
        return "done"
    return FINAL_CODES.get(rc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--wait-pid", type=int)
    args = parser.parse_args(argv)
    try:
        while args.wait_pid and job_watch._pid_alive(args.wait_pid):
            time.sleep(30)
        why = finished(0, args.log.read_text(encoding="utf-8"))
        if why == "done":
            log(args.log, "KEEPER ended: done")
            return 0
        for attempt in range(1, MAX_RESTARTS + 1):
            log(args.log, f"KEEPER restart {attempt} in {RESTART_WAIT // 60} min")
            time.sleep(RESTART_WAIT)
            done = subprocess.run(
                [sys.executable, "-m", "reality_engine.gap_loop", "--sandbox", str(args.sandbox)],
                cwd=str(REPO_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            why = finished(done.returncode, args.log.read_text(encoding="utf-8"))
            if why:
                log(args.log, f"KEEPER ended: {why}")
                return 0
        log(args.log, f"KEEPER ended: gave up after {MAX_RESTARTS} restarts")
        return 1
    except Exception as exc:  # a keeper must leave one terminal line whatever happened
        log(args.log, f"KEEPER STOPPED {type(exc).__name__}: {str(exc)[:300]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
