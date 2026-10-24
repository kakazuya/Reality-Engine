"""Data-job registry: ``jobs.yaml`` loading, validation and freshness checks.

The registry is deliberately data, not code.  Every entry is a read-only
description of a recurring job; ``enabled: false`` means the runner refuses it
unless the caller passes ``confirm=true``.  Freshness is a read-only SQLite
query with an expected max-date (or minimum-count) rule, so a job that exits 0
while loading nothing is still reported stale.
"""
from __future__ import annotations

import re
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from store import parse_iso, read_json_bounded, valid_job_id

REGISTRY_SCHEMA = "dsh-worker-jobs/1"
CADENCES = frozenset(
    {"hourly", "daily", "weekly", "monthly", "quarterly", "once", "manual", "continuous"}
)
CADENCE_MAX_AGE_DAYS: dict[str, float] = {
    "hourly": 0.1,
    "daily": 2.0,  # a weekend of tolerated lag
    "weekly": 8.0,
    "monthly": 31.0,
    "quarterly": 92.0,
    "continuous": 1.0,
}
MARKET_HOURS = frozenset({"any", "avoid_market", "after_close"})
LOCK_PREFIXES = ("db:", "gpu", "net:")
READ_ONLY_SQL = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|replace|drop|alter|attach|detach|pragma|vacuum|create)\b",
    re.IGNORECASE,
)
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


class RegistryError(ValueError):
    """jobs.yaml is missing/malformed or an entry violates the schema."""


def validate_sql(sql: str) -> str:
    if not isinstance(sql, str) or not READ_ONLY_SQL.match(sql):
        raise RegistryError("success_check.sql must start with SELECT or WITH")
    stripped = sql.strip()
    if ";" in stripped.rstrip(";"):
        raise RegistryError("success_check.sql must be a single statement")
    if FORBIDDEN_SQL.search(stripped):
        raise RegistryError("success_check.sql must be read-only")
    return stripped.rstrip(";")


def _require(entry: dict[str, Any], key: str, kind: type, index: int) -> Any:
    value = entry.get(key)
    if not isinstance(value, kind):
        raise RegistryError(f"job #{index} field {key!r} must be {kind.__name__}")
    return value


def validate_job(entry: Any, index: int) -> None:
    if not isinstance(entry, dict):
        raise RegistryError(f"job #{index} is not a mapping")
    name = entry.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise RegistryError(f"job #{index} has an invalid name: {name!r}")
    argv = _require(entry, "argv", list, index)
    if not argv or not all(isinstance(arg, str) and arg and "\x00" not in arg for arg in argv):
        raise RegistryError(f"{name}: argv must be a non-empty list of non-empty strings")
    cwd = entry.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        raise RegistryError(f"{name}: cwd must be a non-empty string")
    env = entry.get("env", {})
    if not isinstance(env, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in env.items()
    ):
        raise RegistryError(f"{name}: env must map strings to strings")
    description = entry.get("description")
    if not isinstance(description, str) or not description.strip():
        raise RegistryError(f"{name}: description must be non-empty")
    writes = entry.get("writes", [])
    if not isinstance(writes, list) or not all(isinstance(item, str) for item in writes):
        raise RegistryError(f"{name}: writes must be a list of strings")
    locks = entry.get("resource_locks", [])
    if not isinstance(locks, list) or not all(isinstance(item, str) for item in locks):
        raise RegistryError(f"{name}: resource_locks must be a list of strings")
    for lock in locks:
        if not lock.startswith(LOCK_PREFIXES):
            raise RegistryError(
                f"{name}: resource_locks entries must start with db:, gpu or net: ({lock!r})"
            )
    cadence = entry.get("cadence")
    if cadence not in CADENCES:
        raise RegistryError(f"{name}: cadence must be one of {sorted(CADENCES)}")
    if not isinstance(entry.get("off_peak_only"), bool):
        raise RegistryError(f"{name}: off_peak_only must be a boolean")
    if entry.get("market_hours", "any") not in MARKET_HOURS:
        raise RegistryError(f"{name}: market_hours must be one of {sorted(MARKET_HOURS)}")
    for flag in ("needs_paid_api", "needs_gpu", "enabled"):
        if not isinstance(entry.get(flag), bool):
            raise RegistryError(f"{name}: {flag} must be a boolean")
    check = entry.get("success_check")
    if check is not None:
        if not isinstance(check, dict):
            raise RegistryError(f"{name}: success_check must be a mapping or null")
        db = check.get("db")
        if not isinstance(db, str) or not db or Path(db).is_absolute() or ".." in Path(db).parts:
            raise RegistryError(f"{name}: success_check.db must be a relative db filename")
        validate_sql(check.get("sql"))
        expect = check.get("expect")
        if not isinstance(expect, dict):
            raise RegistryError(f"{name}: success_check.expect must be a mapping")
        kind = expect.get("kind")
        if kind == "max_date":
            age = expect.get("max_age_days")
            if not isinstance(age, (int, float)) or age < 0:
                raise RegistryError(f"{name}: max_date needs a non-negative max_age_days")
        elif kind == "min_count":
            count = expect.get("min_count")
            if not isinstance(count, int) or count < 0:
                raise RegistryError(f"{name}: min_count needs a non-negative min_count")
        else:
            raise RegistryError(f"{name}: expect.kind must be max_date or min_count")


def load_registry(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"cannot read jobs registry {path}: {exc}") from exc
    try:
        import yaml
    except ImportError as exc:  # declared in requirements.txt, but fail cleanly
        raise RegistryError("PyYAML is required to read jobs.yaml") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RegistryError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegistryError(f"{path} must contain a mapping")
    if raw.get("schema") != REGISTRY_SCHEMA:
        raise RegistryError(f"{path}: schema must be {REGISTRY_SCHEMA!r}")
    jobs = raw.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise RegistryError(f"{path}: jobs must be a non-empty list")
    registry: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, entry in enumerate(jobs):
        validate_job(entry, index)
        name = entry["name"]
        if name in registry:
            raise RegistryError(f"duplicate job name {name!r}")
        registry[name] = entry
        order.append(name)
    return {"schema": REGISTRY_SCHEMA, "path": str(path), "jobs": registry, "order": order}


def cadence_max_age_days(entry: dict[str, Any]) -> float | None:
    return CADENCE_MAX_AGE_DAYS.get(str(entry.get("cadence")))


def expand_argv(
    entry: dict[str, Any],
    extra_args: list[str] | None,
    repo_root: Path,
    data_root: Path,
    now: datetime | None = None,
) -> list[str]:
    today = (now or datetime.now(timezone.utc)).date()
    replacements = {
        "{date}": today.isoformat(),
        "{start}": date.fromordinal(today.toordinal() - 10).isoformat(),
        "{repo_root}": str(repo_root),
        "{data_root}": str(data_root),
    }
    argv: list[str] = []
    for arg in entry["argv"]:
        expanded = arg
        for token, value in replacements.items():
            expanded = expanded.replace(token, value)
        argv.append(expanded)
    if extra_args:
        argv.extend(extra_args)
    return argv


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed.date()
    return None


def run_success_check(check: dict[str, Any], data_root: Path, timeout: float = 2.0) -> dict[str, Any]:
    """Execute one read-only freshness query with a bounded time budget."""
    sql = validate_sql(check["sql"])
    root = Path(data_root).resolve()
    db_path = (root / str(check["db"])).resolve()
    try:
        inside = db_path == root or root in db_path.parents
    except OSError:
        inside = False
    if not inside:
        return {"available": False, "ok": False, "error": "db_outside_data_root"}
    if not db_path.is_file():
        return {"available": False, "ok": False, "error": "db_missing", "db": str(check["db"])}
    connection: sqlite3.Connection | None = None
    deadline = time.monotonic() + max(0.2, float(timeout))
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=timeout)
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA query_only = ON")
        connection.set_progress_handler(
            lambda: 1 if time.monotonic() > deadline else 0, 2000
        )
        row = connection.execute(sql).fetchone()
    except sqlite3.Error as exc:
        return {
            "available": False,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}"[:300],
            "db": str(check["db"]),
        }
    finally:
        if connection is not None:
            connection.close()
    value = row[0] if row else None
    expect = check["expect"]
    if expect["kind"] == "max_date":
        parsed = _parse_date(value)
        if parsed is None:
            return {
                "available": True,
                "ok": False,
                "value": value,
                "expected": dict(expect),
                "error": "value_is_not_a_date",
                "db": str(check["db"]),
            }
        age_days = (datetime.now(timezone.utc).date() - parsed).days
        return {
            "available": True,
            "ok": age_days <= float(expect["max_age_days"]),
            "value": parsed.isoformat(),
            "age_days": age_days,
            "expected": dict(expect),
            "db": str(check["db"]),
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    try:
        count = int(value)
    except (TypeError, ValueError):
        return {
            "available": True,
            "ok": False,
            "value": value,
            "expected": dict(expect),
            "error": "value_is_not_an_integer",
            "db": str(check["db"]),
        }
    return {
        "available": True,
        "ok": count >= int(expect["min_count"]),
        "value": count,
        "expected": dict(expect),
        "db": str(check["db"]),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _run_record(job_dir: Path, job: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": str(job.get("job_id") or job_dir.name),
        "name": (job.get("data_job") or {}).get("name"),
        "phase": status.get("phase", "unknown"),
        "final": status.get("phase") in {"finished", "failed", "cancelled", "lost"},
        "started_at": status.get("started_at") or job.get("created_at"),
        "finished_at": status.get("finished_at"),
        "exit_code": status.get("exit_code"),
        "outcome": status.get("outcome"),
        "status_path": str(job_dir / "status.json"),
    }


def run_history(jobs_dir: Path, limit: int = 1000) -> dict[str, dict[str, Any]]:
    """Latest run and last successful run per data-job name, from job dirs."""
    history: dict[str, dict[str, Any]] = {}
    if not jobs_dir.is_dir():
        return history
    try:
        entries = sorted(
            (p for p in jobs_dir.iterdir() if p.is_dir()),
            key=lambda p: p.name,
            reverse=True,
        )[:limit]
    except OSError:
        return history
    for job_dir in entries:
        if not valid_job_id(job_dir.name):
            continue
        job, _error = read_json_bounded(job_dir / "job.json", 262_144)
        if not isinstance(job, dict) or job.get("kind") != "data_job":
            continue
        name = (job.get("data_job") or {}).get("name")
        if not isinstance(name, str) or not name:
            continue
        status, _status_error = read_json_bounded(job_dir / "status.json", 262_144)
        if not isinstance(status, dict):
            status = {"phase": "unknown"}
        record = _run_record(job_dir, job, status)
        slot = history.setdefault(name, {"latest": None, "last_success": None, "runs": 0})
        slot["runs"] += 1
        if slot["latest"] is None:
            slot["latest"] = record
        if record["final"] and record["phase"] == "finished" and slot["last_success"] is None:
            slot["last_success"] = record
    return history


def find_run(jobs_dir: Path, run_id: str, limit: int = 1000) -> tuple[Path, dict[str, Any]] | None:
    """Resolve a run id or a job name to the newest matching job dir."""
    if valid_job_id(run_id):
        job_dir = jobs_dir / run_id
        job, _error = read_json_bounded(job_dir / "job.json", 262_144)
        if isinstance(job, dict):
            return job_dir, job
    for job_dir in run_history_dirs(jobs_dir, limit):
        job, _error = read_json_bounded(job_dir / "job.json", 262_144)
        if isinstance(job, dict) and (job.get("data_job") or {}).get("name") == run_id:
            return job_dir, job
    return None


def run_history_dirs(jobs_dir: Path, limit: int = 1000) -> list[Path]:
    if not jobs_dir.is_dir():
        return []
    try:
        return sorted(
            (p for p in jobs_dir.iterdir() if p.is_dir() and valid_job_id(p.name)),
            key=lambda p: p.name,
            reverse=True,
        )[:limit]
    except OSError:
        return []


def last_success_age_days(last_success: dict[str, Any] | None) -> float | None:
    if not isinstance(last_success, dict):
        return None
    parsed = parse_iso(last_success.get("finished_at"))
    if parsed is None:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds() / 86_400.0
