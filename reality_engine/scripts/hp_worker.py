#!/usr/bin/env python3
"""Start and supervise real dsh workers on the HP OmniBook over ssh.

    python -m reality_engine.scripts.hp_worker start <brief.md> [--dbs a.db,b.db]
        [--test-cmd CMD] [--commit HEAD] [--permission workspace-write]
        [--timeout S] [--max-output-tokens N] [--account 1|2] [--peak-ok]
    python -m reality_engine.scripts.hp_worker status [<id>]
    python -m reality_engine.scripts.hp_worker result <id>
    python -m reality_engine.scripts.hp_worker fetch-patch <id> [--branch NAME]
    python -m reality_engine.scripts.hp_worker cancel <id>
    python -m reality_engine.scripts.hp_worker poll [<id>] [--once]

Each job is ``C:\\RE\\jobs\\<id>\\``: a fresh ``git archive`` of ``--commit``
under ``repo\\`` with a throwaway local ``git init``/base commit, the brief with
the same context-pack header and standing instructions MSI workers get, a
per-run MCP patch (code-intel on the job checkout, reality-data on
``C:\\RE\\data``), and ``run.cmd`` launched detached through WMI -- the launch
measured to survive the ssh session closing.  The worker runs
``run_deepseek_harness`` from its own checkout under Node-backed ``dsh``.

Every start also writes the same job record the MSI dsh-worker uses
(``job.json`` + ``status.json``) into the MSI runtime, with ``host: "hp"``, so
``list_workers``, ``worker_status``, ``worker_result`` and the ``/dsh-workers``
pane show HP jobs.  A detached ``poll`` process refreshes that record over ssh
with a bounded timeout; reads only ever touch the cached record, so a laptop
that is off can never hang the controller.

``fetch-patch`` brings ``git diff`` against the base commit back and applies it
on a ``dsh-hp/<id>`` branch here (a throwaway worktree under ``.tmp/hp/review``)
for normal review.

Env: ``HP_RUN_HOST`` / ``HP_RUN_ROOT`` / ``HP_RUN_SSH`` / ``HP_RUN_SCP`` as in
``hp_run``; ``HP_WORKER_PY`` (remote interpreter; default the ARM64 Python 3.14
already carrying ``mcp`` + ``cryptography``); ``REALITY_DATA_ROOT`` (source of
``--dbs``); ``HP_WORKER_ACCOUNT`` (default 1: the HP uses Go key 1,
``OPENCODE_GO_API_KEY``); ``DSH_WORKER_RUNTIME_DIR`` (where the dsh-worker MCP
keeps its jobs; default the main checkout's ``plugins/dsh-worker/runtime``).

Peak-hour rule: a start is refused Mon-Fri 06:30-09:30 and 11:30-15:30 IST,
exactly as the local dsh-worker refuses, unless ``--peak-ok`` is passed.  Every
job also gets a hard wall-clock stop (``--timeout``, default 1800 s), so an HP
worker cannot outlive its controller.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reality_engine.scripts import hp_run
from reality_engine.scripts.run_deepseek_harness import off_peak

HOST = hp_run.HOST
ROOT = hp_run.ROOT
REPO = hp_run.REPO
DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT") or REPO / "reality_engine" / "data")
GIT = r"C:\Program Files\Git\cmd\git.exe"
NODE_DIR = r"C:\RE\node24\node-v24.22.2-win-arm64"
PY_DEFAULT = r"%USERPROFILE%\AppData\Local\Programs\Python\Python314-arm64\python.exe"
MODEL = "deepseek-v4.1-flash"
EFFORT = "max"
ACCOUNT = os.environ.get("HP_WORKER_ACCOUNT", "1")
LEASE_SECONDS = int(os.environ.get("HP_WORKER_LEASE_SECONDS", "1800"))
POLL_INTERVAL = int(os.environ.get("HP_WORKER_POLL_SECONDS", "10"))
POLL_TIMEOUT = int(os.environ.get("HP_WORKER_POLL_TIMEOUT", "15"))
RUNTIME_ENV = "DSH_WORKER_RUNTIME_DIR"
FINAL_PHASES = ("finished", "failed", "cancelled", "lost", "orphaned")
IST = timezone(timedelta(hours=5, minutes=30))
JOBS = REPO / ".tmp" / "hp" / "jobs"
PROGRESS_RELATIVE = "PROGRESS_NOTES.md"
# Worker scratch files that must never appear in the reviewable patch.
EXCLUDES = ("PROGRESS_NOTES.md", "exit.txt", "pid.txt", "job.log", "test.log",
            "_pytest*", "pytest-of-*", ".pytest*")


def main_checkout() -> Path:
    """The checkout that owns the generated context pack (this may be a worktree)."""
    completed = subprocess.run(["git", "-C", str(REPO), "worktree", "list", "--porcelain"],
                               capture_output=True, text=True)
    for line in completed.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):])
    return REPO


def context_pack_paths() -> tuple[Path, Path]:
    root = main_checkout() / "tasks" / "worker_context"
    pack, template = root / "CONTEXT.md", root / "BRIEF_TEMPLATE.md"
    missing = [str(p) for p in (pack, template) if not p.is_file()]
    if missing:
        raise SystemExit("worker context pack missing: " + ", ".join(missing))
    return pack, template


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def new_job_id() -> str:
    return f"hp-{datetime.now(IST):%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"


def check_id(job_id: str) -> str:
    return hp_run.check_name(job_id)


def job_parts(job_id: str) -> dict[str, str]:
    """Remote and local paths of one job."""
    remote = hp_run.remote("jobs", job_id)
    return {
        "remote": remote,
        "repo": remote + "\\repo",
        "brief": remote + "\\brief.md",
        "patch": remote + "\\hp_mcp.yml",
        "result": remote + "\\result.md",
        "local": str(JOBS / job_id),
    }


# --------------------------------------------------------------------------- #
# dsh-worker runtime record (what list_workers / the pane read)
# --------------------------------------------------------------------------- #
_RUNTIME_CACHE: Path | None = None


def runtime_dir() -> Path:
    """The dsh-worker runtime the MCP server and the pane read (main checkout)."""
    global _RUNTIME_CACHE
    if _RUNTIME_CACHE is None:
        raw = os.environ.get(RUNTIME_ENV)
        _RUNTIME_CACHE = (
            Path(raw).expanduser().resolve()
            if raw
            else (main_checkout() / "plugins" / "dsh-worker" / "runtime").resolve()
        )
    return _RUNTIME_CACHE


def record_paths(job_id: str) -> dict[str, str]:
    """Absolute paths of one HP job's record in the dsh-worker runtime."""
    directory = runtime_dir() / "jobs" / check_id(job_id)
    return {
        "dir": str(directory),
        "job": str(directory / "job.json"),
        "status": str(directory / "status.json"),
        "brief": str(directory / "brief.md"),
        "result": str(directory / "result.md"),
        "events": str(directory / "result.md.events.jsonl"),
        "log": str(directory / "result.md.log"),
    }


def _now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def _short_time(value: str | None) -> str:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(IST).strftime("%H:%M")


def read_status(job_id: str) -> dict:
    for _ in range(3):
        try:
            data = json.loads(Path(record_paths(job_id)["status"]).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            time.sleep(0.05)
    return {}


def write_status(job_id: str, status: dict) -> None:
    """Atomically replace the cached record; readers never see a half write."""
    path = Path(record_paths(job_id)["status"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def initial_status(job_id: str, started_at: str, host_address: str,
                   timeout: int, title: str = "") -> dict:
    deadline = (datetime.fromisoformat(started_at)
                + timedelta(seconds=timeout)).isoformat(timespec="seconds")
    return {
        "schema": 1,
        "job_id": job_id,
        "host": "hp",
        "kind": "worker",
        "title": title,
        "phase": "starting",
        "started_at": started_at,
        "updated_at": started_at,
        "finished_at": None,
        "worker_activity_at": started_at,
        "outcome": None,
        "exit_code": None,
        "controller_lease": {
            "schema": "dsh-worker-controller-lease/1",
            "job_id": job_id,
            "lease_seconds": timeout,
            "created_at": started_at,
            "deadline": deadline,
            "owner_session": "hp_worker",
        },
        "hp": {
            "reachable": None,
            "last_seen": started_at,
            "checked_at": None,
            "last_error": None,
            "host_address": host_address,
            "hard_timeout_seconds": timeout,
            "pid": None,
        },
        "progress": {
            "summary": "HP job starting (archive upload)",
            "done": False,
            "succeeded": None,
            "events": {},
            "tool_calls_before_first_edit": None,
        },
        "warnings": [],
    }


def create_record(job_id: str, *, meta: dict, brief: str, status: dict) -> str:
    record = record_paths(job_id)
    directory = Path(record["dir"])
    directory.mkdir(parents=True, exist_ok=True)
    Path(record["job"]).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    Path(record["brief"]).write_text(brief, encoding="utf-8")
    write_status(job_id, status)
    return record["dir"]


def update_status(job_id: str, *, hp: dict | None = None,
                  progress: dict | None = None, warnings: list[str] | None = None,
                  **changes) -> dict:
    status = read_status(job_id) or {}
    if status.get("phase") in FINAL_PHASES and changes.get("phase") not in (
            None, status.get("phase")) and changes["phase"] not in FINAL_PHASES:
        changes.pop("phase", None)
    status.update(changes)
    if hp is not None:
        status["hp"] = {**(status.get("hp") or {}), **hp}
    if progress is not None:
        status["progress"] = {**(status.get("progress") or {}), **progress}
    if warnings is not None:
        status["warnings"] = list(warnings)[-5:]
    status["updated_at"] = _now()
    write_status(job_id, status)
    return status


def fail_record(job_id: str, exc: BaseException) -> None:
    message = f"{type(exc).__name__}: {exc}"[:300]
    update_status(job_id, phase="failed", outcome="failed", summary=message,
                  error=message, finished_at=_now(),
                  progress={"done": True, "succeeded": False, "summary": message})


def posix(path: str) -> str:
    return path.replace("\\", "/")


def remote_home() -> str:
    home = hp_run.ps("Write-Output $env:USERPROFILE").strip().replace("/", "\\")
    if not home:
        raise SystemExit("could not read the HP user profile directory")
    return home


def remote_python(home: str) -> str:
    py = os.environ.get("HP_WORKER_PY") or PY_DEFAULT
    return py.replace("%USERPROFILE%", home)


# --------------------------------------------------------------------------- #
# inputs the job needs
# --------------------------------------------------------------------------- #
def archive(commit: str = "HEAD") -> tuple[bytes, str]:
    """``git archive`` of the commit (the local repo is shallow: no remote worktrees)."""
    sha = subprocess.run(["git", "rev-parse", commit], cwd=REPO, capture_output=True,
                         text=True, check=True).stdout.strip()
    tar = subprocess.run(["git", "archive", "--format=tar", sha], cwd=REPO,
                         capture_output=True, check=True).stdout
    if not tar:
        raise SystemExit(f"git archive {sha} returned nothing")
    return tar, sha


def mcp_patch(home: str, paths: dict[str, str]) -> str:
    """Per-run dsh patch: both MCP servers, pointed at this job's checkout and data."""
    py = posix(remote_python(home))
    repo = posix(paths["repo"])
    data = posix(ROOT + "\\data")
    return (
        "- insert:\n"
        "    - id: mcp-reality-data\n"
        '      name: "@deepseek-ai/dsh-mcp-client"\n'
        "      config:\n"
        "        serverName: reality-data\n"
        "        transport: stdio\n"
        f"        command: {json.dumps(py)}\n"
        "        args:\n"
        f"          - {json.dumps(repo + '/plugins/reality-data/server/server.py')}\n"
        f"        cwd: {json.dumps(repo)}\n"
        "        env:\n"
        f"          REALITY_DATA_ROOT: {json.dumps(data)}\n"
        f"          REALITY_DATA_REPO_ROOT: {json.dumps(repo)}\n"
        '          PYTHONUTF8: "1"\n'
        "        toolCallTimeoutMs: 120000\n"
        "        reconnect:\n"
        "          enabled: true\n"
        "          initialDelayMs: 500\n"
        "          maxDelayMs: 30000\n"
        "          maxAttempts: 40\n"
        "    - id: mcp-code-intel\n"
        '      name: "@deepseek-ai/dsh-mcp-client"\n'
        "      config:\n"
        "        serverName: code-intel\n"
        "        transport: stdio\n"
        f"        command: {json.dumps(py)}\n"
        "        args:\n"
        f"          - {json.dumps(repo + '/plugins/code-intel/server/server.py')}\n"
        f"        cwd: {json.dumps(repo)}\n"
        "        env:\n"
        f"          CODE_INTEL_REPO_ROOT: {json.dumps(repo)}\n"
        '          PYTHONUTF8: "1"\n'
        "        toolCallTimeoutMs: 60000\n"
        "        reconnect:\n"
        "          enabled: true\n"
        "          initialDelayMs: 500\n"
        "          maxDelayMs: 30000\n"
        "          maxAttempts: 40\n"
    )


def _standing_instructions() -> str:
    """The same two standing blocks the dsh-worker appends to every MSI brief."""
    sys.path.insert(0, str(REPO / "plugins" / "dsh-worker" / "server"))
    import core  # noqa: PLC0415 - local plugin module, path inserted above
    return f"{core.CODE_INTEL_INSTRUCTION}\n\n{core.PROGRESS_NOTES_INSTRUCTION}\n"


def compose_brief(text: str, *, job_id: str, paths: dict[str, str],
                  dbs: list[str], test_cmd: str | None) -> str:
    """Standing header (points at the copied pack) + HP job facts + the brief."""
    sys.path.insert(0, str(REPO / "plugins" / "dsh-worker" / "server"))
    from context_pack import STANDING_HEADER  # noqa: PLC0415

    header = STANDING_HEADER.format(
        pack=paths["remote"] + "\\CONTEXT.md",
        template=paths["remote"] + "\\BRIEF_TEMPLATE.md",
    )
    data_line = (
        "DBs mounted read-only at C:\\RE\\data: " + ", ".join(dbs)
        if dbs else "No DBs are mounted for this job (REALITY_DATA_ROOT=C:\\RE\\data is empty)."
    )
    test_line = f"Test command: {test_cmd}" if test_cmd else "No test command was supplied."
    facts = (
        f"\n## HP job {job_id}\n"
        f"You are a dsh worker on the HP OmniBook (Windows 11 ARM64).\n"
        f"- Checkout to edit: {paths['repo']} (the only writable root).\n"
        f"- Job directory (brief, logs, result): {paths['remote']}.\n"
        f"- {data_line}\n"
        f"- {test_line}\n"
        f"- Progress notes: append one line per milestone to "
        f"{paths['repo']}\\{PROGRESS_RELATIVE} (the job reads it from there).\n"
        f"- Model/effort: {MODEL} at {EFFORT}; report tool calls before your first edit and the total.\n"
    )
    return f"{header}{facts}\n{text.rstrip()}\n\n{_standing_instructions()}"


def worker_command(paths: dict[str, str], home: str, *, permission: str,
                   timeout: int | None, max_output_tokens: int | None,
                   account: str | None = None) -> str:
    """The command line ``run.cmd`` runs inside the job checkout."""
    python = remote_python(home)
    account = str(account or ACCOUNT)
    if account not in ("1", "2"):
        raise SystemExit("--account must be 1 or 2")
    argv = [
        f'"{python}" -m reality_engine.scripts.run_deepseek_harness',
        f"--model {MODEL}",
        f'--task-file "{paths["brief"]}"',
        f'--out-file "{paths["result"]}"',
        f'--cwd "{paths["repo"]}"',
        f"--account {account}",
        f"--permission {permission}",
        "--allow-paid",
        "--no-refresh",
        f'--extra-patch "{paths["patch"]}"',
    ]
    if timeout is not None:
        argv.append(f"--timeout {timeout}")
    if max_output_tokens is not None:
        argv.append(f"--max-output-tokens {max_output_tokens}")
    return " ".join(argv)


def run_cmd(job_id: str, paths: dict[str, str], home: str, *, permission: str,
            timeout: int | None, max_output_tokens: int | None,
            test_cmd: str | None, account: str | None = None) -> str:
    """The .cmd body: environment the HP worker needs, the harness call, then the tests."""
    command = worker_command(paths, home, permission=permission, timeout=timeout,
                             max_output_tokens=max_output_tokens, account=account)
    body = "\r\n".join([
        f'cd /d "{paths["repo"]}"',
        f'set "PATH={GIT.rsplit(chr(92), 1)[0]};{NODE_DIR};%PATH%"',
        'set "PYTHONUTF8=1"',
        'set "REALITY_DATA_ROOT=C:\\RE\\data"',
        f'set "DSH_WORKER_PROGRESS_NOTES={paths["repo"]}\\{PROGRESS_RELATIVE}"',
        command,
    ])
    if test_cmd:
        body += (f'\r\nif not errorlevel 1 (\r\n  {test_cmd} > "{paths["remote"]}\\test.log" 2>&1\r\n)')
    return hp_run.build_wrapper(paths["remote"], body)


# --------------------------------------------------------------------------- #
# remote repo + dbs
# --------------------------------------------------------------------------- #
def init_remote_repo(paths: dict[str, str], tar: bytes) -> str:
    """Extract the archive, make the throwaway base commit, return its sha."""
    hp_run.ps("$ErrorActionPreference='Stop'\n"
              f"New-Item -ItemType Directory -Force -Path '{paths['repo']}' | Out-Null")
    completed = hp_run._ssh(["tar", "-xf", "-", "-C", paths["repo"]], input_bytes=tar)
    if completed.returncode != 0:
        raise SystemExit(f"tar extract failed: {completed.stderr.decode(errors='replace').strip()}")
    out = hp_run.ps(
        "$ErrorActionPreference='Stop'\n"
        f"$g = '{GIT}'\n"
        f"$r = '{paths['repo']}'\n"
        "& $g -c 'safe.directory=*' -C $r init -q\n"
        f"[IO.File]::WriteAllLines(\"$r\\.git\\info\\exclude\", @({', '.join(repr(p) for p in EXCLUDES)}))\n"
        "& $g -c 'safe.directory=*' -C $r add -A\n"
        "& $g -c 'safe.directory=*' -C $r -c user.name='hp-worker' -c user.email='hp-worker@local' "
        "commit -q -m 'hp base'\n"
        "& $g -c 'safe.directory=*' -C $r rev-parse HEAD\n"
    )
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return lines[-1]


def db_stamp(path: Path) -> dict:
    stat = path.stat()
    return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}


def stage_db(src: Path) -> Path:
    """WAL-consistent copy of a live DB, via SQLite's backup API (never a raw file copy)."""
    staged = REPO / ".tmp" / "hp" / "db" / src.name
    staged.parent.mkdir(parents=True, exist_ok=True)
    if staged.is_file() and staged.stat().st_mtime_ns >= src.stat().st_mtime_ns:
        return staged
    if staged.exists():
        staged.unlink()
    import sqlite3  # noqa: PLC0415 - only the db sync needs it

    source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True, timeout=60)
    try:
        target = sqlite3.connect(str(staged))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    os.utime(staged, ns=(src.stat().st_atime_ns, src.stat().st_mtime_ns))
    return staged


def sync_dbs(names: list[str]) -> list[str]:
    """Copy each named DB once to C:\\RE\\data; re-copy only when the local DB is newer."""
    if not names:
        return []
    hp_run.ps("$ErrorActionPreference='Stop'\n"
              f"New-Item -ItemType Directory -Force -Path '{ROOT}\\data' | Out-Null")
    copied: list[str] = []
    for name in names:
        src = DATA_ROOT / name
        if not src.is_file():
            raise SystemExit(f"db not found: {src}")
        staged = stage_db(src)
        remote = f"{ROOT}\\data\\{name}"
        meta = remote + ".meta.json"
        stored: dict = {}
        try:
            raw = hp_run.ps(f"if (Test-Path '{meta}') {{ Get-Content -Raw '{meta}' }}").strip()
            stored = json.loads(raw) if raw else {}
        except (SystemExit, json.JSONDecodeError):
            stored = {}
        stamp = db_stamp(staged)
        state = "kept"
        if stored.get("mtime_ns") != stamp["mtime_ns"] or stored.get("size") != stamp["size"]:
            hp_run.ps(f"if (Test-Path '{remote}') {{ (Get-Item -LiteralPath '{remote}').IsReadOnly = $false }}")
            completed = hp_run._scp([str(staged), f"{HOST}:{posix(remote)}"])
            if completed.returncode != 0:
                raise SystemExit(f"scp failed: {completed.stderr.decode(errors='replace').strip()}")
            hp_run.ps(f"Set-Content -LiteralPath '{meta}' -Value '{json.dumps(stamp)}' "
                      "-Encoding ASCII")
            state = "copied"
        hp_run.ps(f"if (Test-Path '{remote}') {{ (Get-Item -LiteralPath '{remote}').IsReadOnly = $true }}")
        copied.append(f"{name}:{state}")
    return copied


def launch_script(job_id: str) -> str:
    """Detached WMI launch of run.cmd (the launch measured to survive the ssh session).

    run.cmd is scp'd with the other payload: embedding it here pushed the
    encoded remote command past cmd.exe's 8 KiB command-line limit.
    """
    paths = job_parts(job_id)
    directory = paths["remote"]
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$d = '{directory}'",
        'Remove-Item "$d\\exit.txt" -ErrorAction SilentlyContinue',
        'Remove-Item "$d\\pid.txt" -ErrorAction SilentlyContinue',
        '$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create '
        '-Arguments @{ CommandLine = "cmd /c `"$d\\run.cmd`"" }',
        'if ($r.ReturnValue -ne 0) { throw "WMI create failed: $($r.ReturnValue)" }',
        '[IO.File]::WriteAllText("$d\\pid.txt", "$($r.ProcessId)")',
        '"method=wmi pid=$($r.ProcessId)"',
    ])


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def start(brief: Path, dbs: list[str], test_cmd: str | None, commit: str,
          permission: str, timeout: int | None, max_output_tokens: int | None,
          peak_ok: bool, account: str | None = None) -> str:
    """Create one HP job, launch it detached, and return its job id."""
    if not off_peak() and not peak_ok:
        now = datetime.now(IST)
        raise SystemExit(
            f"{now:%H:%M} IST is in DeepSeek peak hours (Mon-Fri 06:30-09:30, 11:30-15:30 IST); "
            "the MSI dsh-worker refuses the same window. Pass --peak-ok only if Shivam confirms.")
    text = Path(brief).read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"brief is empty: {brief}")
    account = str(account or ACCOUNT)
    if account not in ("1", "2"):
        raise SystemExit("--account must be 1 or 2")
    if timeout is None:
        timeout = LEASE_SECONDS  # lease-like hard stop: an HP worker never outlives its controller
    job_id = new_job_id()
    paths = job_parts(job_id)
    started_at = _now()
    tar, sha = archive(commit)

    local = Path(paths["local"])
    local.mkdir(parents=True, exist_ok=True)
    composition = compose_brief(text, job_id=job_id, paths=paths, dbs=dbs, test_cmd=test_cmd)
    (local / "brief.md").write_text(composition, encoding="utf-8")
    meta = {
        "schema": 1, "job_id": job_id, "created_at": started_at,
        "brief": str(Path(brief).resolve()), "commit": sha, "model": MODEL,
        "effort": EFFORT, "account": account, "permission": permission,
        "test_cmd": test_cmd, "dbs": dbs, "host": hp_run.HOST,
        "hard_timeout_seconds": timeout,
    }
    (local / "job.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    record = record_paths(job_id)
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "HP worker")
    record_meta = {
        "schema": 1, "job_id": job_id, "host": "hp", "kind": "worker",
        "created_at": started_at, "workspace": paths["repo"],
        "brief_first_line": first_line,
        "permission": permission, "permission_requested": permission,
        "write_scope": "workspace", "writes": [], "resource_locks": [],
        "model": MODEL, "effort": EFFORT, "account": account, "test_cmd": test_cmd,
        "limits": {"hard_timeout_seconds": timeout, "max_result_bytes": 65_536},
        "hp": {
            "host": hp_run.HOST, "remote": paths["remote"], "repo": paths["repo"],
            "dbs": dbs, "account": account, "hard_timeout_seconds": timeout,
        },
        "paths": {
            "job_dir": record["dir"], "job_record": record["job"],
            "brief": record["brief"], "status": record["status"],
            "result": record["result"], "events": record["events"],
            "launcher_log": record["log"],
        },
        "warnings": [],
    }
    create_record(job_id, meta=record_meta, brief=composition,
                  status=initial_status(job_id, started_at, hp_run.HOST, timeout,
                                        title=first_line))

    print(f"job      {job_id}")
    print(f"record   {record['dir']}")
    print(f"remote   {paths['remote']}")
    print(f"account  {account} (model {MODEL}, hard stop {timeout}s)")
    try:
        home = remote_home()
        (local / "hp_mcp.yml").write_text(mcp_patch(home, paths), encoding="utf-8")
        base = init_remote_repo(paths, tar)
        print(f"base     {base[:12]} ({len(tar) / 2**20:.1f} MiB archive)")
        for line in sync_dbs(dbs):
            print(f"db       {line}")
        wrapper = run_cmd(job_id, paths, home, permission=permission, timeout=timeout,
                          max_output_tokens=max_output_tokens, test_cmd=test_cmd,
                          account=account)
        (local / "run.cmd").write_bytes(wrapper.encode("utf-8"))
        payload = [local / "brief.md", local / "hp_mcp.yml", local / "job.json",
                   local / "run.cmd", *context_pack_paths()]
        target = f"{hp_run.HOST}:{posix(paths['remote'])}/"
        completed = hp_run._scp([str(p) for p in payload] + [target])
        if completed.returncode != 0:
            raise SystemExit(f"scp failed: {completed.stderr.decode(errors='replace').strip()}")
        hp_run.ps(f"Set-Content -LiteralPath '{paths['remote']}\\base.txt' -Value '{base}' "
                  "-Encoding ASCII")
        launch = hp_run.ps(launch_script(job_id)).strip()
    except BaseException as exc:
        fail_record(job_id, exc)
        raise
    pid = None
    for token in launch.split():
        if token.startswith("pid="):
            pid = int(token.split("=", 1)[1]) if token.split("=", 1)[1].isdigit() else None
    update_status(job_id, phase="running",
                  hp={"reachable": True, "last_seen": _now(), "checked_at": _now(), "pid": pid},
                  progress={"summary": "HP worker launched"})
    spawn_poller(job_id)
    print(f"launch   {launch or 'wmi'}")
    print(f"watch    python -m reality_engine.scripts.hp_worker status {job_id}")
    return job_id


def cmd_start(brief: Path, dbs: list[str], test_cmd: str | None, commit: str,
              permission: str, timeout: int | None, max_output_tokens: int | None,
              peak_ok: bool, account: str | None = None) -> int:
    start(brief, dbs, test_cmd, commit, permission, timeout, max_output_tokens,
          peak_ok, account=account)
    return 0


STATUS_SCRIPT = r"""
$jobs = '@ROOT@\jobs'
if (-not (Test-Path $jobs)) { return }
Get-ChildItem $jobs -Directory | Sort-Object Name | ForEach-Object {
    if (-not (Test-Path (Join-Path $_.FullName 'job.json'))) { return }
    $exit = ''
    $ef = Join-Path $_.FullName 'exit.txt'
    if (Test-Path $ef) { $exit = (Get-Content $ef -Raw).Trim() }
    $rc = ''
    $lf = Join-Path $_.FullName 'job.log'
    if (Test-Path $lf) {
        $m = Get-Content $lf -ErrorAction SilentlyContinue | Select-String -Pattern '^rc=(\d+)' | Select-Object -Last 1
        if ($m) { $rc = $m.Matches[0].Groups[1].Value }
    }
    if ($exit -eq '' -and $rc -ne '') { $exit = $rc }
    $procId = ''
    $pf = Join-Path $_.FullName 'pid.txt'
    if (Test-Path $pf) { $procId = (Get-Content $pf -Raw).Trim() }
    $alive = $false
    if ($procId) { $alive = [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue) }
    $state = if ($exit -ne '') { 'done' } elseif ($alive) { 'running' } else { 'stopped' }
    $result = Join-Path $_.FullName 'result.md'
    $rsize = if (Test-Path $result) { (Get-Item $result).Length } else { 0 }
    $test = ''
    $tf = Join-Path $_.FullName 'test.log'
    if (Test-Path $tf) { $test = (Get-Content $tf -Tail 1 -ErrorAction SilentlyContinue) }
    $notes = Join-Path $_.FullName 'repo\PROGRESS_NOTES.md'
    $nline = ''
    if (Test-Path $notes) { $nline = (Get-Content $notes -Tail 1 -ErrorAction SilentlyContinue) }
    $last = ''
    $log = Join-Path $_.FullName 'result.md.log'
    if (Test-Path $log) { $last = (Get-Content $log -Tail 1 -ErrorAction SilentlyContinue) }
    $act = ''
    $hs = Join-Path $_.FullName 'result.md.status.json'
    if (Test-Path $hs) {
        try { $h = Get-Content $hs -Raw | ConvertFrom-Json; $act = [string]$h.heartbeat.last_activity_at } catch { }
    }
    "{0}|{1}|{2}|{3}|{4}|{5}`t{6}`t{7}`t{8}" -f $_.Name, $state, $exit, $rsize, $last, $nline, $test, $act, $procId
}
""".replace("@ROOT@", ROOT.rstrip("\\"))


def parse_status(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = (line.split("|", 5) + [""] * 6)[:6]
        note, _, rest = parts[5].partition("\t")
        test, _, rest = rest.partition("\t")
        activity, _, pid = rest.partition("\t")
        rows.append({"job": parts[0], "state": parts[1], "exit": parts[2], "result": parts[3],
                     "last": parts[4], "note": note, "test": test,
                     "activity": activity, "pid": pid})
    return rows


def cmd_status(job_id: str | None = None) -> int:
    rows = parse_status(hp_run.ps(STATUS_SCRIPT))
    if job_id:
        rows = [r for r in rows if r["job"] == job_id]
        if not rows:
            raise SystemExit(f"no HP job {job_id!r}")
    if not rows:
        print("no HP jobs")
        return 0
    print(f"{'job':30s} {'state':8s} {'exit':>4s} {'res':>8s}  last log line")
    for r in rows:
        tail = r["test"] and f"test: {r['test']}" or r["note"] or r["last"]
        print(f"{r['job']:30s} {r['state']:8s} {r['exit'] or '-':>4s} {r['result']:>8s}  {tail[:110]}")
    return 0


# --------------------------------------------------------------------------- #
# status cache for the MCP + pane (reads never touch the network)
# --------------------------------------------------------------------------- #
def _remote_row(job_id: str) -> dict | None:
    rows = parse_status(hp_run.ps(STATUS_SCRIPT, timeout=POLL_TIMEOUT))
    return next((r for r in rows if r["job"] == job_id), None)


def fetch_result(job_id: str) -> list[str]:
    """Fetch the finished artifacts into the runtime record; returns what landed."""
    check_id(job_id)
    local = Path(record_paths(job_id)["dir"])
    local.mkdir(parents=True, exist_ok=True)
    paths = job_parts(job_id)
    got: list[str] = []
    for name in ("result.md", "result.md.status.json", "result.md.log",
                 "result.md.events.jsonl"):
        if _fetch(paths["remote"] + "\\" + name, local / name):
            got.append(name)
    return got


def _enrich_from_status(job_id: str, status: dict) -> dict:
    path = Path(record_paths(job_id)["dir"]) / "result.md.status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return status
    if not isinstance(data, dict):
        return status
    hb = data.get("heartbeat") or {}
    events = hb.get("events") or []
    tools = sum(1 for e in events if isinstance(e, dict) and e.get("kind") == "tool_call")
    steps = sum(1 for e in events if isinstance(e, dict) and e.get("kind") == "step_output")
    elapsed = data.get("duration_seconds")
    status["elapsed_seconds"] = elapsed
    status["conversation_id"] = data.get("dsh_conversation_id")
    progress = dict(status.get("progress") or {})
    progress["events"] = {"tool_calls": tools, "model_steps": steps}
    progress["elapsed_seconds"] = elapsed
    if elapsed is not None:
        progress["summary"] = f"{status.get('phase')} · {elapsed:.1f}s · {tools} tool calls"
    status["progress"] = progress
    return status


def poll_once(job_id: str) -> dict:
    """Refresh one HP job's cached record.

    This is the only network path in the status flow and every call is bounded
    by ``POLL_TIMEOUT``; ``list_workers``/``worker_status``/the pane only ever
    read the cache this writes (``HP unreachable, last seen HH:MM`` when the
    laptop is off).
    """
    check_id(job_id)
    status = read_status(job_id)
    if not status:
        raise SystemExit(f"no HP job record {job_id!r} under {runtime_dir()}")
    if status.get("phase") in FINAL_PHASES:
        return status
    hp = dict(status.get("hp") or {})
    reachable = True
    error = None
    row = None
    try:
        row = _remote_row(job_id)
    except (SystemExit, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        reachable = False
        error = f"{type(exc).__name__}: {exc}"[:300]
    now = _now()
    progress = dict(status.get("progress") or {})
    if not reachable:
        hp.update({"reachable": False, "checked_at": now, "last_error": error})
        summary = ("HP unreachable, last seen "
                   f"{_short_time(hp.get('last_seen') or status.get('started_at'))}")
        progress["summary"] = summary
        warnings = [w for w in (status.get("warnings") or []) if w != summary]
        status.update({"hp": hp, "progress": progress, "updated_at": now,
                       "warnings": (warnings + [summary])[-5:]})
        write_status(job_id, status)
        return status

    hp.update({"reachable": True, "checked_at": now, "last_seen": now, "last_error": None})
    if row is None:
        progress["summary"] = "HP job folder not visible yet"
        status.update({"hp": hp, "progress": progress, "updated_at": now})
        write_status(job_id, status)
        return status
    if str(row.get("pid") or "").isdigit():
        hp["pid"] = int(row["pid"])

    state = str(row.get("state") or "")
    finished: str | None = None
    if state == "running":
        phase, outcome, exit_code = "running", None, None
        summary = (row.get("test") or row.get("note") or row.get("last")
                   or "HP worker running")
        activity = row.get("activity") or now
    elif state == "done":
        raw_exit = str(row.get("exit") or "").strip()
        exit_code = int(raw_exit) if raw_exit.lstrip("-").isdigit() else None
        phase = "finished" if exit_code in (0, None) else "failed"
        outcome = "ok" if phase == "finished" else "failed"
        finished, activity = now, row.get("activity") or now
        summary = f"{phase} (exit {raw_exit or '?'})"
    elif state == "stopped":
        phase, outcome, exit_code = "lost", "lost", None
        finished, activity = now, row.get("activity") or now
        summary = "HP worker stopped without writing an exit code"
    else:
        phase = status.get("phase") if status.get("phase") in ("starting", "running") else "running"
        outcome, exit_code = None, None
        activity = row.get("activity") or now
        summary = f"HP state {state or 'unknown'}"
    progress["summary"] = summary
    status.update({"hp": hp, "progress": progress, "updated_at": now,
                   "worker_activity_at": activity, "phase": phase, "outcome": outcome})
    if exit_code is not None:
        status["exit_code"] = exit_code
    if finished:
        status["finished_at"] = finished
        progress["done"] = phase in FINAL_PHASES
        progress["succeeded"] = phase == "finished"
    if phase in FINAL_PHASES:
        if fetch_result(job_id):
            _enrich_from_status(job_id, status)
            progress = dict(status.get("progress") or progress)
        else:
            progress["summary"] = f"{summary}; result fetch failed"
    status["progress"] = progress
    # A cancel that landed while this poll was in flight owns the final label.
    if read_status(job_id).get("phase") == "cancelled" and phase != "cancelled":
        return read_status(job_id)
    write_status(job_id, status)
    return status


def pending_jobs() -> list[str]:
    """HP job ids whose cached phase is not final (used by a restart/re-attach)."""
    jobs: list[str] = []
    try:
        entries = sorted((runtime_dir() / "jobs").iterdir(), key=lambda p: p.name,
                         reverse=True)
    except OSError:
        return jobs
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            job = json.loads((entry / "job.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(job, dict) or job.get("host") != "hp":
            continue
        if read_status(entry.name).get("phase") not in FINAL_PHASES:
            jobs.append(entry.name)
    return jobs


def spawn_poller(job_id: str) -> subprocess.Popen:
    """Start the detached MSI-side poller that refreshes this job's cache."""
    flags = 0
    if os.name == "nt":
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                 | subprocess.CREATE_NO_WINDOW)
    return subprocess.Popen(
        [sys.executable, "-m", "reality_engine.scripts.hp_worker", "poll", job_id],
        cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True,
    )


def cmd_poll(job_id: str | None, interval: int = POLL_INTERVAL, once: bool = False,
             max_seconds: int = 12 * 3600) -> int:
    jobs = [job_id] if job_id else pending_jobs()
    if not jobs:
        print("no HP jobs to poll")
        return 0
    started = time.monotonic()
    while True:
        for name in jobs:
            try:
                status = poll_once(name)
                summary = str((status.get("progress") or {}).get("summary") or "")
                print(f"{name:30s} {status.get('phase', '?'):9s} {summary[:90]}")
            except SystemExit as exc:
                print(f"{name:30s} poll error: {exc}")
        if once or time.monotonic() - started > max_seconds:
            return 0
        jobs = [name for name in jobs if read_status(name).get("phase") not in FINAL_PHASES]
        if not jobs:
            return 0
        time.sleep(max(3, interval))


def _fetch(remote: str, dest: Path) -> bool:
    completed = hp_run._scp([f"{hp_run.HOST}:{posix(remote)}", str(dest)])
    return completed.returncode == 0


def cmd_result(job_id: str) -> int:
    check_id(job_id)
    paths = job_parts(job_id)
    local = Path(paths["local"])
    local.mkdir(parents=True, exist_ok=True)
    got = []
    for name in ("job.json", "result.md", "result.md.status.json", "result.md.log",
                 "result.md.events.jsonl"):
        if _fetch(paths["remote"] + "\\" + name, local / name):
            got.append(name)
    print(f"fetched {local} ({', '.join(got) or 'nothing'})")
    result = local / "result.md"
    if result.is_file():
        text = result.read_text(encoding="utf-8", errors="replace")
        print(f"--- result.md ({len(text)} chars) ---")
        print(text[:6000] + ("\n... [truncated]" if len(text) > 6000 else ""))
    status = local / "result.md.status.json"
    if status.is_file():
        try:
            record = json.loads(status.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            record = {}
        keep = {k: record.get(k) for k in
                ("phase", "rc", "elapsed_seconds", "detail", "stderr_tail") if record.get(k) is not None}
        print(f"--- status ---\n{json.dumps(keep, indent=2)[:2000]}")
    if not got:
        raise SystemExit(f"nothing to fetch for {job_id}")
    return 0


def latest_patch(paths: dict[str, str], base: str) -> bytes:
    # One quoted command line: the remote shell is cmd.exe, and the git path
    # contains a space.  safe.directory: the HP tree can be owned by
    # Administrators while the ssh user is zen7s, which makes git refuse it.
    git = f'"{GIT}" -c "safe.directory=*" -C "{paths["repo"]}"'
    hp_run._ssh([f"{git} reset -q"])  # drop earlier staging so .git/info/exclude applies
    hp_run._ssh([f"{git} add -A"])
    completed = hp_run._ssh([f"{git} diff --cached --binary {base}"])
    if completed.returncode != 0:
        raise SystemExit(f"git diff failed: {completed.stderr.decode(errors='replace').strip()}")
    return completed.stdout


def cmd_fetch_patch(job_id: str, branch: str | None) -> int:
    check_id(job_id)
    paths = job_parts(job_id)
    local = Path(paths["local"])
    local.mkdir(parents=True, exist_ok=True)
    meta_file = local / "job.json"
    if not meta_file.is_file():
        if not _fetch(paths["remote"] + "\\job.json", meta_file):
            raise SystemExit(f"no job.json for {job_id}")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    remote_base = hp_run.ps(f"Get-Content -Raw '{paths['remote']}\\base.txt'").strip()
    if not remote_base:
        raise SystemExit(f"no base.txt on the HP for {job_id}")
    patch = latest_patch(paths, remote_base)
    (local / "patch.diff").write_bytes(patch)
    if not patch.strip():
        print(f"{job_id}: patch is empty (base {remote_base[:12]})")
        return 0

    branch = branch or f"dsh-hp/{job_id}"
    base = meta["commit"]  # the MSI commit the archive was taken from
    review = REPO / ".tmp" / "hp" / "review" / job_id
    if review.exists():
        raise SystemExit(f"review worktree already exists: {review}")
    review.parent.mkdir(parents=True, exist_ok=True)
    for argv in (
        ["git", "worktree", "add", "-b", branch, str(review), base],
        ["git", "apply", "--index", str(local / "patch.diff")],
        ["git", "-c", "user.name=hp-worker", "-c", "user.email=hp-worker@local",
         "commit", "-q", "-m", f"hp worker {job_id}"],
    ):
        completed = subprocess.run(argv, cwd=review if "--index" in argv or "commit" in argv else REPO,
                                   capture_output=True, text=True)
        if completed.returncode != 0:
            raise SystemExit(f"{' '.join(argv[:3])} failed:\n{completed.stderr.strip()}")
    print(f"branch   {branch}")
    print(f"worktree {review}")
    print(f"patch    {local / 'patch.diff'} ({len(patch)} bytes)")
    return 0


def cancel(job_id: str) -> dict:
    """Kill the job's remote process tree (bounded ssh); returns what was killed."""
    check_id(job_id)
    paths = job_parts(job_id)
    pid = hp_run.ps(f"if (Test-Path '{paths['remote']}\\pid.txt') "
                    "{ (Get-Content -Raw '" + paths["remote"] + "\\pid.txt').Trim() }",
                    timeout=POLL_TIMEOUT).strip()
    if not pid:
        return {"already_final": True, "pid": None,
                "detail": "no pid.txt on the HP (the job never launched or already stopped)"}
    out = hp_run.ps(f"taskkill /PID {int(pid)} /T /F 2>&1", timeout=POLL_TIMEOUT)
    return {"already_final": False, "pid": int(pid), "detail": out.strip()[:200]}


def cmd_cancel(job_id: str) -> int:
    detail = cancel(job_id)
    print(detail.get("detail") or f"cancelled pid {detail.get('pid')}")
    return 0


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start", help="archive the commit, set up the job, launch detached")
    p.add_argument("brief", type=Path)
    p.add_argument("--dbs", default="", help="comma-separated DB names under REALITY_DATA_ROOT")
    p.add_argument("--test-cmd", default=None)
    p.add_argument("--commit", default="HEAD")
    p.add_argument("--permission", default="workspace-write",
                   choices=("read-only", "workspace-write", "danger-full-access"))
    p.add_argument("--timeout", type=int, default=None, help="hard wall-clock cutoff, seconds")
    p.add_argument("--max-output-tokens", type=int, default=None)
    p.add_argument("--account", default=None, choices=("1", "2"),
                   help="OpenCode Go key: 1 = OPENCODE_GO_API_KEY (HP default), 2 = _2 (MSI default)")
    p.add_argument("--peak-ok", action="store_true",
                   help="allow a DeepSeek start in the MSI's peak window (needs Shivam's go-ahead)")
    p = sub.add_parser("status", help="job states, exit codes, result size, last progress")
    p.add_argument("job_id", nargs="?")
    p = sub.add_parser("result", help="fetch and print the final answer")
    p.add_argument("job_id")
    p = sub.add_parser("fetch-patch", help="pull the diff back and apply it on a local branch")
    p.add_argument("job_id")
    p.add_argument("--branch")
    p = sub.add_parser("cancel", help="kill the job's process tree")
    p.add_argument("job_id")
    p = sub.add_parser("poll", help="refresh the cached status the MCP/pane read")
    p.add_argument("job_id", nargs="?")
    p.add_argument("--interval", type=int, default=POLL_INTERVAL)
    p.add_argument("--once", action="store_true")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "start":
            dbs = [n.strip() for n in args.dbs.split(",") if n.strip()]
            return cmd_start(args.brief, dbs, args.test_cmd, args.commit, args.permission,
                             args.timeout, args.max_output_tokens, args.peak_ok,
                             account=args.account)
        if args.cmd == "status":
            return cmd_status(args.job_id)
        if args.cmd == "result":
            return cmd_result(args.job_id)
        if args.cmd == "fetch-patch":
            return cmd_fetch_patch(args.job_id, args.branch)
        if args.cmd == "poll":
            return cmd_poll(args.job_id, interval=args.interval, once=args.once)
        return cmd_cancel(args.job_id)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"{' '.join(map(str, exc.cmd))} failed: {exc.stderr}") from exc


if __name__ == "__main__":
    sys.exit(main())
