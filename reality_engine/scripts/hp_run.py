#!/usr/bin/env python3
"""Drive the HP OmniBook (Windows 11 ARM64) from this laptop over ssh/scp.

    python -m reality_engine.scripts.hp_run sync            # git archive HEAD -> C:\\RE\\repo
    python -m reality_engine.scripts.hp_run copy-db data.db # -> C:\\RE\\db\\data.db
    python -m reality_engine.scripts.hp_run run bench -- "C:\\...\\python.exe" C:\\RE\\bench.py
    python -m reality_engine.scripts.hp_run status [bench]
    python -m reality_engine.scripts.hp_run fetch C:\\RE\\jobs\\bench\\job.log

The remote shell is cmd.exe, which mangles inline quoting, so nothing is quoted inline:
every PowerShell snippet is base64 ``-EncodedCommand``-ed and every job body is written
once as ``run.cmd``.  A job is detached through Task Scheduler running as SYSTEM, because
that is the only launch that was measured to survive the ssh session closing (see
``machines/HP_ACCEL_BENCH_2026-10-31.md``); ``--method wmi`` and ``--method start``
are kept for the comparison.

Env: ``HP_RUN_HOST`` (default ``zen7s@192.168.1.42``, the LAN address; it falls
back to Tailscale ``zen7s@100.78.87.112`` when the LAN ssh is refused),
``HP_RUN_ROOT`` (default C:\\RE), ``HP_RUN_SSH`` / ``HP_RUN_SCP`` (defaults
``ssh`` / ``scp``).
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
from pathlib import Path

HOST = os.environ.get("HP_RUN_HOST", "zen7s@192.168.1.42")
FALLBACK_HOST = os.environ.get("HP_RUN_HOST_FALLBACK", "zen7s@100.78.87.112")
ROOT = os.environ.get("HP_RUN_ROOT", r"C:\RE")
SSH = os.environ.get("HP_RUN_SSH", "ssh")
SCP = os.environ.get("HP_RUN_SCP", "scp")
REPO = Path(__file__).resolve().parents[2]

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
TASK_PREFIX = "RE_hpjob_"


def remote(*parts: str) -> str:
    """One path under the HP root, e.g. remote("jobs", "bench") -> C:\\RE\\jobs\\bench."""
    return "\\".join([ROOT.rstrip("\\"), *parts])


def _ps_argv(script: str) -> list[str]:
    """The single remote command argument: an encoded PowerShell script (cmd.exe-safe)."""
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-EncodedCommand", enc]


#: The detached poller has no console, so without this every ssh it starts opens a
#: new terminal window on the desktop.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _run_ssh(host: str, argv: list[str], input_bytes: bytes | None,
             timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [SSH, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, *argv],
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        creationflags=NO_WINDOW,
    )


def _ssh(argv: list[str], input_bytes: bytes | None = None,
         timeout: int = 600) -> subprocess.CompletedProcess:
    """Run one remote command. Tests replace this; it is the only network call in the CLI.

    The default LAN address is retried once on the Tailscale address when ssh
    refuses the connection (exit 255): the 2026-10-31 bench saw Tailscale flap
    while the LAN stayed up, so the reverse must not strand every job either.
    ``timeout`` bounds the call for pollers that must never hang a read path.
    """
    r = _run_ssh(HOST, argv, input_bytes, timeout)
    if r.returncode == 255 and HOST != FALLBACK_HOST:
        r2 = _run_ssh(FALLBACK_HOST, argv, input_bytes, timeout)
        if r2.returncode != 255:
            globals()["HOST"] = FALLBACK_HOST
            return r2
    return r


def _scp(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([SCP, "-q", *argv], capture_output=True, timeout=3600,
                          creationflags=NO_WINDOW)


def ps(script: str, timeout: int = 600) -> str:
    """Run a PowerShell snippet on the HP and return stdout (raises on a non-zero ssh)."""
    r = _ssh(_ps_argv(script), timeout=timeout)
    if r.returncode != 0:
        raise SystemExit(
            f"remote PowerShell failed (ssh {r.returncode}):\n"
            f"{r.stderr.decode(errors='replace').strip()}"
        )
    return r.stdout.decode(errors="replace")


def check_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise SystemExit(f"invalid job name {name!r}: letters, digits, '_', '.', '-' only")
    return name


# --------------------------------------------------------------------------- #
# job wrapper: one .cmd that owns job.log and exit.txt
# --------------------------------------------------------------------------- #
def build_wrapper(job_dir: str, command: str) -> str:
    """The job body. ``call :TASK`` keeps the command's own & and > out of our parsing."""
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        f'cd /d "{job_dir}"\r\n'
        "call :HP_TASK > job.log 2>&1\r\n"
        'set "RC=%ERRORLEVEL%"\r\n'
        "> exit.txt echo %RC%\r\n"
        "exit /b %RC%\r\n"
        "\r\n"
        ":HP_TASK\r\n"
        f"{command}\r\n"
        "exit /b %ERRORLEVEL%\r\n"
    )


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def build_run_script(name: str, command: str, method: str = "schtasks") -> str:
    """PowerShell that writes run.cmd and launches it detached (returned, so tests can see it)."""
    job_dir = remote("jobs", name)
    task = TASK_PREFIX + name
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$d = '{job_dir}'",
        "New-Item -ItemType Directory -Force -Path $d | Out-Null",
        f"[IO.File]::WriteAllBytes(\"$d\\run.cmd\", [Convert]::FromBase64String('{_b64(build_wrapper(job_dir, command))}'))",
        f"[IO.File]::WriteAllText(\"$d\\command.txt\", '{_b64(command)}')",
        'Remove-Item "$d\\exit.txt" -ErrorAction SilentlyContinue',
        'Remove-Item "$d\\pid.txt" -ErrorAction SilentlyContinue',
    ]
    if method == "schtasks":
        lines += [
            f"schtasks /Create /TN {task} /TR {job_dir}\\run.cmd /SC ONCE /ST 00:00 /RU SYSTEM /F | Out-Null",
            f"schtasks /Run /TN {task} | Out-Null",
            f"if ($LASTEXITCODE -ne 0) {{ throw 'schtasks failed' }}",
            "'method=schtasks (SYSTEM)'",
        ]
    elif method == "wmi":
        lines += [
            # hidden start-up info: a detached run.cmd must not pop a console
            # window if this is ever launched from the interactive session
            '$si = Get-CimClass -ClassName Win32_ProcessStartup | New-CimInstance -ClientOnly',
            '$si.ShowWindow = [uint16]0',
            '$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create '
            f'-Arguments @{{ CommandLine = "cmd /c `"$d\\run.cmd`""; ProcessStartupInformation = $si }}',
            "if ($r.ReturnValue -ne 0) { throw \"WMI create failed: $($r.ReturnValue)\" }",
            '[IO.File]::WriteAllText("$d\\pid.txt", "$($r.ProcessId)")',
            '"method=wmi pid=$($r.ProcessId)"',
        ]
    elif method == "start":
        lines += [
            'Start-Process -FilePath cmd.exe -ArgumentList "/c", "$d\\run.cmd" -WindowStyle Hidden',
            "'method=Start-Process (dies with the ssh session)'",
        ]
    else:
        raise SystemExit(f"unknown launch method {method!r}")
    return "\n".join(lines)


def cmd_run(name: str, command: str, method: str = "wmi") -> int:
    check_name(name)
    script = build_run_script(name, command, method)
    out = ps(script).strip()
    print(f"job    {name}")
    print(f"dir    {remote('jobs', name)}")
    print(f"task   {TASK_PREFIX + name}")
    print(f"launch {out or method}")
    return 0


# --------------------------------------------------------------------------- #
# sync / copy-db / fetch
# --------------------------------------------------------------------------- #
def archive_head() -> tuple[bytes, str]:
    """``git archive HEAD`` as a tar: the repo is shallow, so this is the only honest snapshot."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()
    tar = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"], cwd=REPO, capture_output=True, check=True
    ).stdout
    return tar, head


def cmd_sync(tar: bytes, head: str) -> int:
    """Extract into repo.new, swap it in: a removed file must not linger in the snapshot."""
    new, old = remote("repo.new"), remote("repo.old")
    ps(
        f"New-Item -ItemType Directory -Force -Path '{new}' | Out-Null\n"
        f"Remove-Item '{old}' -Recurse -Force -ErrorAction SilentlyContinue\n"
        f"Set-Content -LiteralPath '{new}\\.hp_head' -Value '{head}' -Encoding ASCII"
    )
    r = _ssh(["tar", "-xf", "-", "-C", new], input_bytes=tar)
    if r.returncode != 0:
        raise SystemExit(f"tar extract failed: {r.stderr.decode(errors='replace').strip()}")
    ps(
        f"if (Test-Path '{remote('repo')}') {{ Move-Item -LiteralPath '{remote('repo')}' -Destination '{old}' }}\n"
        f"Move-Item -LiteralPath '{new}' -Destination '{remote('repo')}'\n"
        f"Remove-Item '{old}' -Recurse -Force -ErrorAction SilentlyContinue"
    )
    print(f"synced {head[:12]} ({len(tar) / 2**20:.1f} MiB) -> {remote('repo')}")
    return 0


def cmd_copy_db(src: Path) -> int:
    if not src.is_file():
        raise SystemExit(f"not a file: {src}")
    ps(f"New-Item -ItemType Directory -Force -Path '{remote('db')}' | Out-Null")
    dst = f"{HOST}:{remote('db', src.name).replace(chr(92), '/')}"
    r = _scp([str(src), dst])
    if r.returncode != 0:
        raise SystemExit(f"scp failed: {r.stderr.decode(errors='replace').strip()}")
    print(f"copied {src} ({src.stat().st_size / 2**20:.1f} MiB) -> {dst}")
    return 0


def cmd_fetch(path: str, dest: str | None = None) -> int:
    src = path if path.startswith(HOST + ":") else f"{HOST}:{path.replace(chr(92), '/')}"
    out = Path(dest) if dest else REPO / ".tmp" / "hp" / Path(path.replace(chr(92), "/")).name
    out.parent.mkdir(parents=True, exist_ok=True)
    r = _scp([src, str(out)])
    if r.returncode != 0:
        raise SystemExit(f"scp failed: {r.stderr.decode(errors='replace').strip()}")
    print(out)
    return 0


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
STATUS_SCRIPT = r"""
$jobs = '@ROOT@\jobs'
if (-not (Test-Path $jobs)) { return }
Get-ChildItem $jobs -Directory | Sort-Object Name | ForEach-Object {
    $n = $_.Name
    $exit = ''
    $ef = Join-Path $_.FullName 'exit.txt'
    if (Test-Path $ef) { $exit = (Get-Content $ef -Raw).Trim() }
    $t = Get-ScheduledTask -TaskName '@PREFIX@' + $n -ErrorAction SilentlyContinue
    $alive = $false
    $pf = Join-Path $_.FullName 'pid.txt'
    if (Test-Path $pf) {
        $procId = (Get-Content $pf -Raw).Trim()
        $alive = [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue)
    }
    $st = if ($exit -ne '') { 'done' } elseif ($alive) { 'running' } elseif ($t) { "$($t.State)" } else { 'unknown' }
    $last = ''
    $lf = Join-Path $_.FullName 'job.log'
    if (Test-Path $lf) { $last = (Get-Content $lf -Tail 1 -ErrorAction SilentlyContinue) }
    '{0}|{1}|{2}|{3}|{4}' -f $n, $st, $exit, $_.LastWriteTime.ToString('MM-dd HH:mm'), $last
}
""".replace("@ROOT@", ROOT.rstrip("\\")).replace("@PREFIX@", TASK_PREFIX)


def parse_status(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        name, state, code, when, last = (line.split("|", 4) + [""] * 5)[:5]
        rows.append({"name": name, "state": state, "exit": code, "when": when, "last": last})
    return rows


def cmd_status(name: str | None = None) -> int:
    rows = parse_status(ps(STATUS_SCRIPT))
    if name:
        rows = [r for r in rows if r["name"] == name]
        if not rows:
            raise SystemExit(f"no job named {name!r}")
    if not rows:
        print("no jobs")
        return 0
    print(f"{'job':20s} {'state':10s} {'exit':>4s}  {'updated':12s}  last log line")
    for r in rows:
        print(f"{r['name']:20s} {r['state']:10s} {r['exit'] or '-':>4s}  "
              f"{r['when']:12s}  {r['last'][:110]}")
    return 0


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run jobs on the HP OmniBook over ssh.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync", help="git archive HEAD -> C:\\RE\\repo")
    p = sub.add_parser("copy-db", help="copy one local file -> C:\\RE\\db")
    p.add_argument("file", type=Path)
    p = sub.add_parser("run", help="launch a detached job: run <name> -- <command>")
    p.add_argument("name")
    p.add_argument("--method", default="wmi", choices=("wmi", "schtasks", "start"))
    p.add_argument("command", nargs=argparse.REMAINDER)
    p = sub.add_parser("status", help="job states, exit codes and last log line")
    p.add_argument("name", nargs="?")
    p = sub.add_parser("fetch", help="copy one remote path back here")
    p.add_argument("path")
    p.add_argument("--dest")

    args = ap.parse_args(argv)
    if args.cmd == "sync":
        tar, head = archive_head()
        return cmd_sync(tar, head)
    if args.cmd == "copy-db":
        return cmd_copy_db(args.file)
    if args.cmd == "run":
        if args.command[:1] in (["--"], ["--method"]):
            if args.command[0] == "--method":
                raise SystemExit("--method goes before the job name: run --method M <name> -- <cmd>")
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            raise SystemExit("run needs a command after --")
        return cmd_run(args.name, " ".join(command), args.method)
    if args.cmd == "status":
        return cmd_status(args.name)
    return cmd_fetch(args.path, args.dest)


if __name__ == "__main__":
    sys.exit(main())
