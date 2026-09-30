"""Register the hourly annual-drain watchdog as a Windows Scheduled Task.

Quoting is done in a Python arg list (no shell), so there is nothing for the
terminal to split mid-line. Run ELEVATED (right-click Terminal -> Run as
administrator):

    python -m reality_engine.scripts.install_annual_drain_task

Mirrors continuous_loop.install_task. Verifies with a /query afterwards.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "RealityEngine-AnnualDrain"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _task_command() -> str:
    scripts = _PROJECT_ROOT / "reality_engine" / "scripts"
    return f'wscript.exe "{scripts / "run_hidden.vbs"}" "{scripts / "run_annual_drain.cmd"}"'


def main() -> int:
    if os.name != "nt":
        print("not Windows — add a cron entry instead")
        return 2
    cmd = ["schtasks", "/create", "/tn", TASK_NAME,
           "/sc", "HOURLY", "/tr", _task_command(), "/f"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    print((proc.stdout or "").strip())
    if proc.stderr.strip():
        print(proc.stderr.strip())
    if proc.returncode != 0:
        return 1
    q = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME],
                       capture_output=True, text=True, check=False)
    print(q.stdout.strip() or q.stderr.strip())
    return 0 if q.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
