"""Clock-time Oh My Pi routines (Claude Code local-schedule analog).

A routine is a named prompt that fires at a wall-clock slot (hourly / daily /
weekdays / weekly). Each run is a **fresh** headless ``omp -p`` session
(``--no-session``). The previous run's cleaned stdout is written to
``LAST.md`` and attached as ``@LAST.md`` on the next run, so the model keeps
working the same task without a growing session.

The 30-minute ``continuous_loop`` is a different animal (harness health +
``--continue``). This module does not call it.

Owns ONLY this file, ``reality_engine/agent/routines.json``,
``reality_engine/agent/prompts/routines/``, and
``reality_engine/scripts/run_routines.cmd``.
"""

from __future__ import annotations

import argparse
import errno
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("reality_engine.routines")

IST = timezone(timedelta(hours=5, minutes=30))
LOCK_NAME = "routines.lock"
LAST_NAME = "LAST.md"
LAST_META = "last_run.json"
RUN_LOG_NAME = "run_log.jsonl"
STALE_LOCK_SECONDS = 45 * 60
DEFAULT_MAX_TIME = "20m"
AGENT_TIMEOUT_GRACE_SECONDS = 300
MAX_LAST_CHARS = 16_000
LOG_TAIL_LINES = 60
TASK_NAME = "RealityEngine-Routines"
TASK_INTERVAL_MINUTES = 5
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
KINDS = ("hourly", "daily", "weekdays", "weekly")
WEEKDAY_NAMES = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

AgentRunner = Callable[..., Dict[str, Any]]


def repo_root() -> Path:
    return _PROJECT_ROOT


def default_catalog_path() -> Path:
    return repo_root() / "reality_engine" / "agent" / "routines.json"


def default_prompts_dir() -> Path:
    return repo_root() / "reality_engine" / "agent" / "prompts" / "routines"


def default_state_dir() -> Path:
    from reality_engine import config

    return Path(config.DATA_DIR) / "logs" / "routines"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_ist(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------
def acquire_lock(lock_path: Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age > STALE_LOCK_SECONDS:
            logger.warning("breaking stale routines lock (%.0fs old): %s", age, lock_path)
            lock_path.unlink(missing_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise RuntimeError(f"routines lock held: {lock_path}") from exc
        raise
    os.write(fd, f"{os.getpid()} {_utc_now_iso()}\n".encode("utf-8"))
    return fd


def release_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    Path(lock_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
def _empty_catalog() -> Dict[str, Any]:
    return {"version": 1, "routines": []}


def load_catalog(catalog_path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(catalog_path) if catalog_path else default_catalog_path()
    if not path.exists():
        return _empty_catalog()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable routines catalog {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("routines catalog must be a JSON object")
    data.setdefault("version", 1)
    data.setdefault("routines", [])
    if not isinstance(data["routines"], list):
        raise ValueError("routines catalog.routines must be a list")
    return data


def save_catalog(catalog: Dict[str, Any], catalog_path: Optional[Path] = None) -> Path:
    path = Path(catalog_path) if catalog_path else default_catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def list_routines(catalog_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    return list(load_catalog(catalog_path).get("routines") or [])


def get_routine(name: str, catalog_path: Optional[Path] = None) -> Dict[str, Any]:
    for row in list_routines(catalog_path):
        if row.get("name") == name:
            return dict(row)
    raise KeyError(f"no routine named {name!r}")


def parse_at(value: Optional[str]) -> Optional[dt_time]:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{1,2}", text):
        text = f"{text}:00"
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"time must be HH:MM, got {value!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {value!r}")
    return dt_time(hour, minute)


def parse_weekday(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        if 0 <= value <= 6:
            return value
        raise ValueError(f"weekday int must be 0-6, got {value}")
    key = str(value).strip().lower()
    if key in WEEKDAY_NAMES:
        return WEEKDAY_NAMES[key]
    if key.isdigit():
        return parse_weekday(int(key))
    raise ValueError(f"unknown weekday {value!r}")


def _default_prompt_body(name: str, prompt: str) -> str:
    body = (prompt or "").strip() or "(no standing instructions — continue LAST.md)"
    return (
        f"# Routine: {name}\n\n"
        "You are an unattended Oh My Pi agent pass. Nobody is watching this run.\n"
        "Hard wall-clock cap applies. One finished increment beats three started ones.\n\n"
        "## Task\n\n"
        f"{body}\n\n"
        "## Chain\n\n"
        "If a previous output is attached (`LAST.md`), that is **your own last reply**.\n"
        "Continue that work — do not restart, do not summarize the whole history.\n"
        "Write the next concrete increment.\n\n"
        "## Output\n\n"
        "Your entire reply becomes the next run's input. End with:\n\n"
        "## Next\n"
        "<one concrete action the next run should take>\n"
    )


def add_routine(
    *,
    name: str,
    kind: str = "daily",
    at: Optional[str] = "09:00",
    weekday: Any = None,
    prompt: str = "",
    prompt_file: Optional[str] = None,
    max_time: str = DEFAULT_MAX_TIME,
    model: Optional[str] = None,
    chain: bool = True,
    catalog_path: Optional[Path] = None,
    prompts_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    name = (name or "").strip().lower()
    if not NAME_RE.match(name):
        raise ValueError(
            f"routine name must be kebab-case [a-z][a-z0-9-]{{0,47}}, got {name!r}"
        )
    kind = (kind or "daily").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    if kind != "hourly":
        parse_at(at)  # validate
    wd = parse_weekday(weekday)
    if kind == "weekly" and wd is None:
        raise ValueError("weekly routines need --weekday (mon..sun or 0-6)")
    catalog = load_catalog(catalog_path)
    if any(r.get("name") == name for r in catalog["routines"]):
        raise ValueError(f"routine {name!r} already exists")
    pdir = Path(prompts_dir) if prompts_dir else default_prompts_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    if prompt_file:
        src = Path(prompt_file)
        dest = pdir / f"{name}.md"
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        stored_prompt = str(dest)
    else:
        dest = pdir / f"{name}.md"
        dest.write_text(_default_prompt_body(name, prompt), encoding="utf-8")
        stored_prompt = str(dest)
    row = {
        "name": name,
        "enabled": True,
        "kind": kind,
        "at": None if kind == "hourly" else (at or "09:00"),
        "weekday": wd,
        "prompt_file": stored_prompt,
        "max_time": max_time or DEFAULT_MAX_TIME,
        "model": model or None,
        "chain": bool(chain),
    }
    catalog["routines"].append(row)
    save_catalog(catalog, catalog_path)
    return row


def set_enabled(name: str, enabled: bool, catalog_path: Optional[Path] = None) -> Dict[str, Any]:
    catalog = load_catalog(catalog_path)
    for row in catalog["routines"]:
        if row.get("name") == name:
            row["enabled"] = bool(enabled)
            save_catalog(catalog, catalog_path)
            return dict(row)
    raise KeyError(f"no routine named {name!r}")


# ---------------------------------------------------------------------------
# Due slots
# ---------------------------------------------------------------------------
def _parse_last_run(last_run: Optional[str]) -> Optional[datetime]:
    if not last_run:
        return None
    text = str(last_run).strip()
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def slot_start(routine: Dict[str, Any], now: datetime) -> Optional[datetime]:
    """Start of the current period's slot, or None if this period has no slot yet.

    For daily/weekdays/weekly: today's (or this week's) HH:MM.
    Returns that datetime even if it is still in the future — ``is_due``
    compares ``now`` against it. For hourly: the top of the current hour.
    """
    now = _as_ist(now)
    kind = (routine.get("kind") or "daily").lower()
    if kind == "hourly":
        return now.replace(minute=0, second=0, microsecond=0)
    at = parse_at(routine.get("at") or "09:00")
    assert at is not None
    today_slot = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if kind == "weekdays" and now.weekday() >= 5:
        return None
    if kind == "weekly":
        wd = parse_weekday(routine.get("weekday"))
        if wd is None or now.weekday() != wd:
            return None
    return today_slot


def is_due(routine: Dict[str, Any], now: datetime, last_run: Optional[str] = None) -> bool:
    if not routine.get("enabled", True):
        return False
    now = _as_ist(now)
    slot = slot_start(routine, now)
    if slot is None:
        return False
    if now < slot:
        return False
    prev = _parse_last_run(last_run)
    if prev is not None and prev >= slot:
        return False
    return True


def read_last_run(state_dir: Path, name: str) -> Optional[str]:
    path = Path(state_dir) / name / LAST_META
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("last_run_at")


def write_last_run(state_dir: Path, name: str, record: Dict[str, Any]) -> Path:
    path = Path(state_dir) / name / LAST_META
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# LAST.md chain
# ---------------------------------------------------------------------------
def _clean_stdout(text: str) -> str:
    lines = (text or "").splitlines()
    while lines and lines[0].strip() in ("Working...", "Working…", ""):
        lines.pop(0)
    body = "\n".join(lines).strip()
    return (body + "\n") if body else ""


def write_last_md(state_dir: Path, name: str, stdout: str) -> Path:
    path = Path(state_dir) / name / LAST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _clean_stdout(stdout)
    if len(cleaned) > MAX_LAST_CHARS:
        cleaned = cleaned[-MAX_LAST_CHARS:]
        nl = cleaned.find("\n")
        if 0 <= nl < 200:
            cleaned = cleaned[nl + 1:]
        cleaned = "…[truncated]\n" + cleaned
        if not cleaned.endswith("\n"):
            cleaned += "\n"
    path.write_text(cleaned, encoding="utf-8")
    return path


def resolve_timeout(max_time: str) -> int:
    text = str(max_time).strip().lower()
    multipliers = {"s": 1, "m": 60, "h": 3600}
    try:
        if text and text[-1] in multipliers:
            base = int(float(text[:-1]) * multipliers[text[-1]])
        else:
            base = int(float(text))
    except (ValueError, IndexError):
        base = int(float(DEFAULT_MAX_TIME[:-1]) * 60)
    return max(60, base + AGENT_TIMEOUT_GRACE_SECONDS)


def build_agent_command(
    routine: Dict[str, Any],
    state_dir: Path,
    run_index: int = 1,
    max_time: Optional[str] = None,
) -> List[str]:
    prompt_path = Path(routine["prompt_file"])
    name = routine["name"]
    cmd: List[str] = [
        os.environ.get("OMP_BIN", "omp"),
        "-p",
        "--cwd",
        str(repo_root()),
        "--no-session",
        "--auto-approve",
        "--no-title",
        "--max-time",
        max_time or routine.get("max_time") or DEFAULT_MAX_TIME,
    ]
    model = routine.get("model")
    if model:
        cmd.extend(["--model", str(model)])
    cmd.append(f"@{prompt_path}")
    last = Path(state_dir) / name / LAST_NAME
    if routine.get("chain", True) and last.exists() and last.stat().st_size > 0:
        cmd.append(f"@{last}")
    cmd.append(
        f"Routine `{name}` run #{run_index}. "
        "Continue from the attached previous output if present. "
        "Your entire reply becomes the next run's input."
    )
    return cmd


def run_agent(
    cmd: Sequence[str],
    timeout_seconds: int,
    log_path: Optional[Path] = None,
) -> Dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        rc, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        rc, timed_out = 124, True
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = ((exc.stderr or "") if isinstance(exc.stderr, str) else "") + "\n[routines] hard timeout"
    except FileNotFoundError as exc:
        rc, timed_out, out, err = 127, False, "", f"omp not found: {exc}"
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(out + ("\n--- stderr ---\n" + err if err else ""), encoding="utf-8")
        except OSError as exc:
            logger.warning("could not write agent log %s: %s", log_path, exc)
    return {
        "rc": rc,
        "timed_out": timed_out,
        "duration_seconds": round(time.time() - started, 1),
        "stdout": out,
        "stdout_tail": "\n".join(out.splitlines()[-LOG_TAIL_LINES:]),
        "stderr_tail": "\n".join(err.splitlines()[-LOG_TAIL_LINES:]),
        "log_file": str(log_path) if log_path else None,
    }


def _run_count(state_dir: Path, name: str) -> int:
    path = Path(state_dir) / name / RUN_LOG_NAME
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def _append_run_log(state_dir: Path, name: str, record: Dict[str, Any]) -> None:
    path = Path(state_dir) / name / RUN_LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def run_routine(
    name: str,
    catalog_path: Optional[Path] = None,
    state_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
    agent_runner: Optional[AgentRunner] = None,
    force: bool = True,
) -> Dict[str, Any]:
    """Run one named routine. ``force=True`` (CLI ``run``) ignores the clock."""
    routine = get_routine(name, catalog_path)
    state = Path(state_dir) if state_dir else default_state_dir()
    now_ist = _as_ist(now)
    last = read_last_run(state, name)
    if not force and not is_due(routine, now_ist, last):
        return {"name": name, "skipped": True, "reason": "not due"}
    run_index = _run_count(state, name) + 1
    cmd = build_agent_command(routine, state, run_index=run_index)
    stamp = now_ist.strftime("%H%M")
    day = now_ist.strftime("%Y-%m-%d")
    log_path = state / name / day / f"agent_{stamp}.log"
    runner = agent_runner or run_agent
    agent = runner(cmd, timeout_seconds=resolve_timeout(routine.get("max_time") or DEFAULT_MAX_TIME), log_path=log_path)
    write_last_md(state, name, agent.get("stdout") or agent.get("stdout_tail") or "")
    record = {
        "last_run_at": now_ist.isoformat(),
        "run_index": run_index,
        "rc": agent.get("rc"),
        "timed_out": agent.get("timed_out"),
        "duration_seconds": agent.get("duration_seconds"),
        "log_file": agent.get("log_file"),
    }
    write_last_run(state, name, record)
    _append_run_log(state, name, record)
    return {"name": name, "skipped": False, "run_index": run_index, **record, "agent": agent}


def tick(
    catalog_path: Optional[Path] = None,
    state_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
    agent_runner: Optional[AgentRunner] = None,
) -> Dict[str, Any]:
    """Run every due routine, serialized under one lock."""
    state = Path(state_dir) if state_dir else default_state_dir()
    lock_path = state / LOCK_NAME
    now_ist = _as_ist(now)
    try:
        fd = acquire_lock(lock_path)
    except RuntimeError:
        return {"skipped": True, "reason": "lock held", "ran_names": []}
    ran: List[Dict[str, Any]] = []
    try:
        for row in list_routines(catalog_path):
            last = read_last_run(state, row["name"])
            if not is_due(row, now_ist, last):
                continue
            ran.append(
                run_routine(
                    row["name"],
                    catalog_path=catalog_path,
                    state_dir=state,
                    now=now_ist,
                    agent_runner=agent_runner,
                    force=True,
                )
            )
        return {
            "skipped": False,
            "ran_names": [r["name"] for r in ran],
            "ran": ran,
            "now": now_ist.isoformat(),
        }
    finally:
        release_lock(fd, lock_path)


# ---------------------------------------------------------------------------
# Windows Task Scheduler
# ---------------------------------------------------------------------------
def _task_command() -> str:
    scripts = repo_root() / "reality_engine" / "scripts"
    return f'wscript.exe "{scripts / "run_hidden.vbs"}" "{scripts / "run_routines.cmd"}"'


def install_task(interval_minutes: int = TASK_INTERVAL_MINUTES) -> Dict[str, Any]:
    if os.name != "nt":
        return {
            "ok": False,
            "reason": "not Windows — add a crontab entry instead",
            "cron": (
                f"*/{interval_minutes} * * * * cd {repo_root()} && "
                "python -m reality_engine.pipeline.routines --tick"
            ),
        }
    cmd = [
        "schtasks", "/create", "/tn", TASK_NAME,
        "/sc", "MINUTE", "/mo", str(int(interval_minutes)),
        "/tr", _task_command(), "/f",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "ok": proc.returncode == 0,
        "command": " ".join(cmd),
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def uninstall_task() -> Dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "reason": "not Windows"}
    proc = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, text=True, check=False,
    )
    return {"ok": proc.returncode == 0, "stdout": (proc.stdout or "").strip(), "stderr": (proc.stderr or "").strip()}


def task_status() -> Dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "reason": "not Windows"}
    proc = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST", "/v"],
        capture_output=True, text=True, check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "registered": proc.returncode == 0,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clock-time Oh My Pi routines with LAST.md output chaining."
    )
    parser.add_argument("--catalog", default=None, help="Override routines.json path")
    parser.add_argument("--state-dir", default=None, help="Override state directory")
    parser.add_argument("--prompts-dir", default=None, help="Override prompt directory")
    sub = parser.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", help="Create a named routine")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--kind", default="daily", choices=list(KINDS))
    p_add.add_argument("--at", default="09:00", help="HH:MM local IST (ignored for hourly)")
    p_add.add_argument("--weekday", default=None, help="mon..sun or 0-6 (weekly)")
    p_add.add_argument("--prompt", default="", help="Standing instructions")
    p_add.add_argument("--prompt-file", default=None, help="Copy this markdown as the standing prompt")
    p_add.add_argument("--max-time", default=DEFAULT_MAX_TIME)
    p_add.add_argument("--model", default=None, help="omp --model id (default: your omp default)")
    p_add.add_argument("--no-chain", action="store_true", help="Do not attach LAST.md on the next run")

    sub.add_parser("list", help="Print the catalog")
    p_run = sub.add_parser("run", help="Run one routine now (ignores the clock)")
    p_run.add_argument("--name", required=True)
    sub.add_parser("tick", help="Run every routine whose slot is due (what the scheduler calls)")
    p_pause = sub.add_parser("pause", help="Disable a routine without deleting it")
    p_pause.add_argument("--name", required=True)
    p_resume = sub.add_parser("resume", help="Re-enable a paused routine")
    p_resume.add_argument("--name", required=True)
    sub.add_parser("install", help=f"Register the {TASK_INTERVAL_MINUTES}-minute Windows scheduled task")
    sub.add_parser("uninstall", help="Delete the scheduled task")
    sub.add_parser("status", help="Show scheduled-task status")

    # Also accept the continuous_loop flag style: --tick as a top-level flag.
    parser.add_argument("--tick", action="store_true", dest="tick_flag", help=argparse.SUPPRESS)
    parser.add_argument("--install", action="store_true", dest="install_flag", help=argparse.SUPPRESS)
    parser.add_argument("--uninstall", action="store_true", dest="uninstall_flag", help=argparse.SUPPRESS)
    parser.add_argument("--status", action="store_true", dest="status_flag", help=argparse.SUPPRESS)
    parser.add_argument("--list", action="store_true", dest="list_flag", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    catalog = Path(args.catalog) if args.catalog else None
    state = Path(args.state_dir) if args.state_dir else None
    prompts = Path(args.prompts_dir) if args.prompts_dir else None
    cmd = args.cmd
    if args.tick_flag:
        cmd = "tick"
    elif args.install_flag:
        cmd = "install"
    elif args.uninstall_flag:
        cmd = "uninstall"
    elif args.status_flag:
        cmd = "status"
    elif args.list_flag:
        cmd = "list"
    if not cmd:
        parser.print_help()
        return 2

    try:
        if cmd == "add":
            row = add_routine(
                name=args.name,
                kind=args.kind,
                at=args.at,
                weekday=args.weekday,
                prompt=args.prompt,
                prompt_file=args.prompt_file,
                max_time=args.max_time,
                model=args.model,
                chain=not args.no_chain,
                catalog_path=catalog,
                prompts_dir=prompts,
            )
            print(json.dumps(row, indent=2))
            return 0
        if cmd == "list":
            print(json.dumps(list_routines(catalog), indent=2))
            return 0
        if cmd == "pause":
            print(json.dumps(set_enabled(args.name, False, catalog), indent=2))
            return 0
        if cmd == "resume":
            print(json.dumps(set_enabled(args.name, True, catalog), indent=2))
            return 0
        if cmd == "run":
            result = run_routine(args.name, catalog_path=catalog, state_dir=state, force=True)
            print(json.dumps({k: v for k, v in result.items() if k != "agent"}, indent=2, default=str))
            agent = result.get("agent") or {}
            if agent.get("stdout_tail"):
                print("\n--- agent output (tail) ---\n" + agent["stdout_tail"])
            return 0 if result.get("rc") == 0 else 1
        if cmd == "tick":
            result = tick(catalog_path=catalog, state_dir=state)
            print(json.dumps({k: v for k, v in result.items() if k != "ran"}, indent=2, default=str))
            return 0
        if cmd == "install":
            res = install_task()
            print(json.dumps(res, indent=2))
            return 0 if res.get("ok") else 1
        if cmd == "uninstall":
            res = uninstall_task()
            print(json.dumps(res, indent=2))
            return 0 if res.get("ok") else 1
        if cmd == "status":
            res = task_status()
            print(json.dumps(res, indent=2))
            return 0 if res.get("ok") else 1
    except (ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
