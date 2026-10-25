"""Feed orchestration for the data-gather MCP server.

The dsh-worker plugin already owns the registry, the supervisor, the controller
lease and the ``db:``/``net:`` resource locks, so this module composes those
(``Manager.list_jobs`` for freshness, ``Manager.start_job`` for execution)
instead of copying them.  It never writes a database row: the only file it
writes is the per-run before/after snapshot under ``data-gather/runtime``.
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_WORKER_SERVER = _HERE.parents[1] / "dsh-worker" / "server"
_REPO_ROOT = _HERE.parents[2]
for _path in (_WORKER_SERVER, _REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import core  # noqa: E402
import feeds  # noqa: E402
import jobs  # noqa: E402
import store  # noqa: E402
from core import Manager, PluginError, is_peak, load_config  # noqa: E402

SCHEMA = "data-gather/1"
SNAPSHOT_SCHEMA = "data-gather-snapshot/1"
RUNTIME_ENV = "DSH_DATA_GATHER_RUNTIME"
APPROVED_ENV = "DSH_DATA_GATHER_APPROVED"
RAW_ROOT_ENV = "REALITY_RAW_ROOT"
DEFAULT_WINDOW_DAYS = 31  # cap when an approval omits max_days
TAIL_LINES = 40
MAX_TABLES = 12
GAP_DEADLINE_SECONDS = 20.0
MAX_SNAPSHOT_BYTES = 262_144
MAX_NAME_ITEMS = 100


class GatherService:
    """Feed tools over one dsh-worker :class:`Manager`."""

    def __init__(
        self,
        manager: Manager | None = None,
        *,
        now: datetime | Any | None = None,
        approved_path: Path | str | None = None,
        raw_root: Path | str | None = None,
        runtime_dir: Path | str | None = None,
        data_root: Path | str | None = None,
        calendar: tuple[str, str] = (feeds.CALENDAR_DB, feeds.CALENDAR_TABLE),
    ) -> None:
        self._manager = manager
        self._now = now
        self._approved_path = Path(approved_path) if approved_path else None
        self._raw_root = Path(raw_root) if raw_root else None
        self._runtime_dir = Path(runtime_dir) if runtime_dir else None
        self._data_root = Path(data_root) if data_root else None
        self._calendar = calendar

    # ------------------------------------------------------------- plumbing
    @property
    def manager(self) -> Manager:
        if self._manager is None:
            self._manager = Manager(load_config())
        return self._manager

    @property
    def config(self) -> core.PluginConfig:
        return self.manager.config

    @property
    def data_root(self) -> Path:
        return self._data_root or self.config.data_root

    @property
    def raw_root(self) -> Path:
        return self._raw_root or Path(
            os.environ.get(RAW_ROOT_ENV) or feeds.DEFAULT_RAW_ROOT
        )

    @property
    def approved_path(self) -> Path:
        return self._approved_path or Path(
            os.environ.get(APPROVED_ENV)
            or Path.home() / ".dsh" / "data-gather" / feeds.APPROVED_FILENAME
        )

    @property
    def runtime_dir(self) -> Path:
        return self._runtime_dir or Path(
            os.environ.get(RUNTIME_ENV) or (self.config.runtime_dir / "data-gather")
        )

    def now(self) -> datetime:
        value = self._now
        if value is None:
            return datetime.now(timezone.utc)
        return value() if callable(value) else value

    def registry(self) -> dict[str, Any]:
        path = self.config.jobs_file
        if not Path(path).is_file():
            raise PluginError(
                "jobs_registry_missing",
                f"no data-job registry at {path}",
                recovery="Point DSH_WORKER_JOBS_FILE at a jobs.yaml file.",
            )
        try:
            return jobs.load_registry(Path(path))
        except jobs.RegistryError as exc:
            raise PluginError("jobs_registry_invalid", str(exc), path=str(path)) from exc

    def approved(self) -> dict[str, dict[str, Any]]:
        try:
            return feeds.load_approved(self.approved_path)
        except feeds.ApprovedError as exc:
            raise PluginError(
                "approved_invalid", str(exc), path=str(self.approved_path)
            ) from exc

    @staticmethod
    def _net_heavy(locks: list[str]) -> bool:
        return any(str(lock).startswith("net:") for lock in locks)

    @staticmethod
    def _stamp(value: datetime | None) -> str | None:
        return value.isoformat(timespec="seconds") if value else None

    # ------------------------------------------------------------ list_feeds
    def list_feeds(self) -> dict[str, Any]:
        """One compact row per feed; freshness is dsh-worker's own rule."""
        listed = self.manager.list_jobs()
        approved = self.approved()
        rows: list[dict[str, Any]] = []
        for job in listed["jobs"]:
            name = job["name"]
            approval = approved.get(name)
            freshness = job.get("freshness") or {}
            cadence_days = jobs.CADENCE_MAX_AGE_DAYS.get(str(job.get("cadence")))
            age_days = freshness.get("age_days")
            if age_days is None:
                age_days = job.get("last_success_age_days")
            age_vs_cadence = None
            if cadence_days is not None and age_days is not None:
                age_vs_cadence = {
                    "age_days": round(float(age_days), 1),
                    "cadence_days": cadence_days,
                    "over": float(age_days) > cadence_days,
                }
            latest = job.get("last_run")
            rows.append(
                {
                    "name": name,
                    "description": job.get("description"),
                    "cadence": job.get("cadence"),
                    "freshness": freshness or None,
                    "age_days": round(float(age_days), 1) if age_days is not None else None,
                    "age_vs_cadence": age_vs_cadence,
                    "last_run": (
                        {
                            "run_id": latest.get("job_id"),
                            "phase": latest.get("phase"),
                            "outcome": latest.get("outcome"),
                            "finished_at": latest.get("finished_at"),
                        }
                        if isinstance(latest, dict)
                        else None
                    ),
                    "stale": job.get("stale"),
                    "stale_reasons": job.get("stale_reasons") or [],
                    "enabled": job.get("enabled"),
                    "net_heavy": self._net_heavy(job.get("resource_locks") or []),
                    "approved": approval is not None,
                    "max_days": (approval or {}).get("max_days"),
                }
            )
        known = {row["name"] for row in rows}
        return {
            "ok": True,
            "schema": SCHEMA,
            "generated_at": core.iso(self.now()),
            "count": len(rows),
            "registry": listed.get("registry"),
            "approved_path": str(self.approved_path),
            "unknown_approved": sorted(set(approved) - known),
            "feeds": rows,
        }

    # ------------------------------------------------------------ gap_report
    def gap_report(self, names: list[str] | None = None) -> dict[str, Any]:
        """Expected trading days vs stored dates, per market feed."""
        registry = self.registry()
        if names is None:
            wanted = list(registry["order"])
        else:
            if not isinstance(names, list) or not names:
                raise PluginError("names_invalid", "names must be a non-empty list of feed names")
            wanted = []
            for name in names:
                if not isinstance(name, str) or name not in registry["jobs"]:
                    raise PluginError(
                        "feed_unknown",
                        f"no data job named {name!r}",
                        available=sorted(registry["jobs"])[:MAX_NAME_ITEMS],
                    )
                wanted.append(name)
        approved = self.approved()
        today = self.now().date()
        deadline = time.monotonic() + GAP_DEADLINE_SECONDS
        rows: list[dict[str, Any]] = []
        for name in wanted:
            entry = registry["jobs"][name]
            approval = approved.get(name) or {}
            row: dict[str, Any] = {
                "name": name,
                "cadence": entry["cadence"],
                "market": None,
                "table": None,
                "window": None,
                "expected": None,
                "present": None,
                "max_date": None,
                "missing_ranges": [],
                "missing_days": None,
                "skipped": None,
                "error": None,
            }
            targets = feeds.write_targets(entry.get("writes"))
            market_target = next(
                ((db, table) for db, table in targets if feeds.is_market_table(table)), None
            )
            if approval.get("market") is False or market_target is None:
                row["market"] = False
                row["skipped"] = "not_a_market_feed"
                rows.append(row)
                continue
            if time.monotonic() > deadline:
                row["market"] = True
                row["skipped"] = "deadline_exceeded"
                rows.append(row)
                continue
            row["market"] = True
            db_name, table = market_target
            row["table"] = f"{db_name}:{table}"
            lookback = feeds.CADENCE_LOOKBACK_DAYS.get(
                str(entry["cadence"]), feeds.DEFAULT_LOOKBACK_DAYS
            )
            window_start = today - timedelta(days=lookback)
            calendar = feeds.trading_days(
                self.data_root,
                window_start,
                today,
                db_name=self._calendar[0],
                table=self._calendar[1],
            )
            if not calendar["available"]:
                row["error"] = calendar.get("error") or "calendar_unavailable"
                row["skipped"] = "calendar_unavailable"
                rows.append(row)
                continue
            expected = [day for day in calendar["dates"] if window_start <= day <= today]
            present, error = feeds.present_dates(
                self.data_root, db_name, table, window_start, today
            )
            row["window"] = {"start": window_start.isoformat(), "end": today.isoformat()}
            if error:
                row["error"] = error
                row["expected"] = len(expected)
                rows.append(row)
                continue
            ranges = feeds.missing_ranges(expected, present)
            row["expected"] = len(expected)
            row["present"] = len(present)
            row["max_date"] = max(present).isoformat() if present else None
            row["missing_ranges"] = ranges
            row["missing_days"] = sum(item["days"] for item in ranges)
            rows.append(row)
        return {
            "ok": True,
            "schema": SCHEMA,
            "generated_at": core.iso(self.now()),
            "calendar": f"{self._calendar[0]}:{self._calendar[1]}",
            "count": len(rows),
            "feeds": rows,
        }

    # --------------------------------------------------------------- run_feed
    @staticmethod
    def _day(value: Any, label: str, name: str) -> date:
        """A caller-supplied window bound: exactly YYYY-MM-DD and a real date."""
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise PluginError(
                "window_invalid", f"{label} must be a YYYY-MM-DD date", name=name
            )
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise PluginError(
                "window_invalid", f"{label} must be a real YYYY-MM-DD date", name=name
            ) from exc

    def _window(
        self,
        name: str,
        approval: dict[str, Any],
        start: str | None,
        end: str | None,
    ) -> tuple[str | None, str | None]:
        window_start = self._day(start, "start", name) if start is not None else None
        window_end = self._day(end, "end", name) if end is not None else None
        if window_start is None and window_end is None:
            return None, None
        max_days = approval.get("max_days") or DEFAULT_WINDOW_DAYS
        if window_end is None:
            window_end = self.now().date()
        if window_start is None:
            window_start = window_end - timedelta(days=max_days - 1)
        if window_end < window_start:
            raise PluginError("window_invalid", "end is before start", name=name)
        span = (window_end - window_start).days + 1
        if span > max_days:
            raise PluginError(
                "window_too_large",
                f"feed {name!r} is approved for at most {max_days} days per run "
                f"(requested {span})",
                name=name,
                max_days=max_days,
                requested_days=span,
            )
        return window_start.isoformat(), window_end.isoformat()

    def _capture(self, entry: dict[str, Any]) -> dict[str, Any]:
        targets = feeds.write_targets(entry.get("writes"))
        return {
            "raw_since": time.time(),
            "raw_root": str(self.raw_root),
            "tables": [
                feeds.table_stat(self.data_root, db_name, table)
                for db_name, table in targets[:MAX_TABLES]
            ],
            "tables_total": len(targets),
            "tables_truncated": len(targets) > MAX_TABLES,
        }

    def run_feed(
        self, name: str, start: str | None = None, end: str | None = None
    ) -> dict[str, Any]:
        """Start one approved feed through the dsh-worker supervisor."""
        registry = self.registry()
        entry = registry["jobs"].get(name) if isinstance(name, str) else None
        if entry is None:
            raise PluginError(
                "feed_unknown",
                f"no data job named {name!r}",
                available=sorted(registry["jobs"])[:MAX_NAME_ITEMS],
            )
        approved_path = self.approved_path
        if not approved_path.is_file():
            raise PluginError(
                "approval_file_missing",
                f"no approval file at {approved_path}; data-gather runs nothing until "
                "a human creates it from plugins/data-gather/approved.yaml",
                name=name,
                approved_path=str(approved_path),
            )
        approval = self.approved().get(name)
        if approval is None:
            raise PluginError(
                "feed_not_approved",
                f"feed {name!r} is not listed in {approved_path}; a human must "
                "add it before a worker may run it",
                name=name,
                approved_path=str(approved_path),
            )
        window_start, window_end = self._window(name, approval, start, end)
        locks = [str(lock) for lock in entry.get("resource_locks") or []]
        net_heavy = self._net_heavy(locks)
        now = self.now()
        if entry.get("off_peak_only") and is_peak(now):
            raise PluginError(
                "off_peak_hours",
                f"feed {name!r} is off-peak-only (Mon-Fri 06:30-09:30 and "
                "11:30-15:30 IST); run_feed's confirm override only covers "
                "enabled:false, not the hours gates",
                name=name,
                now=now.astimezone(core.IST).isoformat(timespec="minutes"),
            )
        # The same gate start_job applies when confirm is false.
        if entry.get("market_hours") == "avoid_market" and core._market_session(now):
            raise PluginError(
                "market_hours",
                f"feed {name!r} does not start between 09:15 and 15:30 IST on weekdays",
                name=name,
                now=now.astimezone(core.IST).isoformat(timespec="minutes"),
            )
        if net_heavy and is_peak(now):
            raise PluginError(
                "peak_hours",
                f"feed {name!r} is net-heavy and peak hours are Mon-Fri "
                "06:30-09:30 and 11:30-15:30 IST; retry after the window closes",
                name=name,
                net_heavy=True,
                now=now.astimezone(core.IST).isoformat(timespec="minutes"),
            )
        snapshot = self._capture(entry)
        started = self.manager.start_job(
            name, confirm=True, window_start=window_start, window_end=window_end
        )
        run_id = str(started["run_id"])
        snapshot.update(
            {
                "schema": SNAPSHOT_SCHEMA,
                "name": name,
                "run_id": run_id,
                "created_at": core.iso(now),
                "window": {"start": window_start, "end": window_end},
                "locks": locks,
                "net_heavy": net_heavy,
                "approved": approval,
            }
        )
        store.atomic_write_json(self._snapshot_path(run_id), snapshot)
        return {
            "ok": True,
            "schema": SCHEMA,
            "run_id": run_id,
            "name": name,
            "phase": started.get("phase"),
            "window": snapshot["window"],
            "resource_locks": locks,
            "net_heavy": net_heavy,
            "max_days": approval.get("max_days") or DEFAULT_WINDOW_DAYS,
            "argv": started.get("argv"),
            "status_tool": f"feed_status(run_id='{run_id}')",
            "verify_tool": f"verify_feed(name='{name}', run_id='{run_id}')",
        }

    # ----------------------------------------------------------- feed_status
    def feed_status(self, run_id: str) -> dict[str, Any]:
        """Phase, outcome and bounded log tails for one run."""
        if not isinstance(run_id, str) or not run_id.strip():
            raise PluginError("run_id_invalid", "run_id must be a non-empty string")
        log = self.manager.job_log(run_id.strip(), tail=TAIL_LINES)
        return {
            "ok": True,
            "schema": SCHEMA,
            "run_id": log["run_id"],
            "name": log.get("name"),
            "phase": log.get("phase"),
            "outcome": log.get("outcome"),
            "final": log.get("final"),
            "exit_code": log.get("exit_code"),
            "tail": log.get("tail", TAIL_LINES),
            "stdout": list(log.get("stdout") or [])[-TAIL_LINES:],
            "stderr": list(log.get("stderr") or [])[-TAIL_LINES:],
        }

    # ----------------------------------------------------------- verify_feed
    def _snapshot_path(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not store.valid_job_id(run_id):
            raise PluginError("run_id_invalid", "run_id must be a job id")
        return self.runtime_dir / "verify" / f"{run_id}.json"

    def _read_snapshot(self, run_id: str) -> tuple[dict[str, Any], Path]:
        path = self._snapshot_path(run_id)
        snapshot, error = store.read_json_bounded(path, MAX_SNAPSHOT_BYTES)
        if not isinstance(snapshot, dict):
            raise PluginError(
                "no_snapshot",
                f"no before-run snapshot for {run_id!r} at {path} ({error}); "
                "verify_feed only works for runs started by run_feed",
                run_id=run_id,
                path=str(path),
            )
        return snapshot, path

    def verify_feed(self, name: str, run_id: str) -> dict[str, Any]:
        """Pass/fail per check: row deltas, new max date, new rows, raw files."""
        snapshot, path = self._read_snapshot(run_id)
        if snapshot.get("name") != name:
            raise PluginError(
                "snapshot_mismatch",
                f"run {run_id!r} started feed {snapshot.get('name')!r}, not {name!r}",
                run_id=run_id,
                name=snapshot.get("name"),
            )
        status = self.manager.get_status(run_id)
        phase = status.get("phase")
        if phase not in core.FINAL_PHASES:
            raise PluginError(
                "run_not_finished",
                f"run {run_id!r} is {phase}; verify after it reaches a final phase",
                run_id=run_id,
                phase=phase,
            )
        checks: list[dict[str, Any]] = []
        for before in snapshot.get("tables") or []:
            if not isinstance(before, dict):
                continue
            after = feeds.table_stat(self.data_root, before["db"], before["table"])
            before_rows, after_rows = before.get("rows"), after.get("rows")
            delta = (
                after_rows - before_rows
                if isinstance(before_rows, int) and isinstance(after_rows, int)
                else None
            )
            error = after.get("error") or before.get("error")
            checks.append(
                {
                    "check": "row_count",
                    "db": before["db"],
                    "table": before["table"],
                    "ok": None if error else delta is not None and delta >= 0,
                    "before": before_rows,
                    "after": after_rows,
                    "delta": delta,
                    "error": error,
                }
            )
            before_max, after_max = before.get("max_date"), after.get("max_date")
            checks.append(
                {
                    "check": "max_date",
                    "db": before["db"],
                    "table": before["table"],
                    "ok": (
                        None
                        if error or after_max is None
                        else before_max is None or str(after_max) >= str(before_max)
                    ),
                    "before": before_max,
                    "after": after_max,
                }
            )
        for before in (snapshot.get("tables") or [])[:MAX_TABLES]:
            if not isinstance(before, dict):
                continue
            new_rows = feeds.first_new_rows(
                self.data_root, before["db"], before["table"], before.get("max_date")
            )
            comparison = [
                row for row in new_rows["rows"] if isinstance(row.get("match"), bool)
            ]
            checks.append(
                {
                    "check": "new_rows_source_date",
                    "db": before["db"],
                    "table": before["table"],
                    "ok": (
                        all(row["match"] for row in comparison) if comparison else None
                    ),
                    "stored_column": new_rows.get("stored_column"),
                    "source_column": new_rows.get("source_column"),
                    "rows": new_rows.get("rows") or [],
                    "skipped": None
                    if comparison
                    else (new_rows.get("error") or "no_new_rows"),
                }
            )
        raw_since = float(snapshot.get("raw_since") or 0.0)
        raw = feeds.new_files(
            self.raw_root, raw_since, suffixes=feeds.RAW_SUFFIXES, limit=25
        )
        checks.append(
            {
                "check": "raw_files",
                "ok": None if not raw["available"] else bool(raw["files"]),
                "root": raw["root"],
                "count": len(raw["files"]),
                "files": [item["rel"] for item in raw["files"][:5]],
                "skipped": raw.get("error") if not raw["available"] else None,
                "truncated": raw.get("truncated"),
            }
        )
        misplaced = feeds.new_files(
            self.data_root,
            raw_since,
            suffixes=feeds.RAW_SUFFIXES,
            limit=10,
            max_entries=1500,
            max_depth=2,
        )
        checks.append(
            {
                "check": "raw_not_in_data_root",
                "ok": (
                    None
                    if not misplaced["available"]
                    else not misplaced["files"]
                ),
                "root": misplaced["root"],
                "count": len(misplaced["files"]),
                "files": [item["rel"] for item in misplaced["files"][:5]],
                "truncated": misplaced.get("truncated"),
            }
        )
        captured = [
            before for before in snapshot.get("tables") or [] if isinstance(before, dict)
        ]
        truncated = snapshot.get("tables_truncated")
        total = snapshot.get("tables_total")
        checks.append(
            {
                "check": "table_snapshot_complete",
                "ok": None if truncated is None else not truncated,
                "checked": len(captured),
                "total": total if isinstance(total, int) else None,
                "skipped": (
                    None
                    if truncated is not None
                    else "snapshot_has_no_truncation_flag"
                ),
            }
        )
        failed = [check for check in checks if check["ok"] is False]
        verified = [check for check in checks if check["ok"] is not None]
        return {
            "ok": not failed,
            "schema": SCHEMA,
            "name": name,
            "run_id": run_id,
            "phase": phase,
            "outcome": status.get("outcome"),
            "window": snapshot.get("window"),
            "raw_root": str(self.raw_root),
            "snapshot": str(path),
            "checked": len(verified),
            "failed": len(failed),
            "not_applicable": len(checks) - len(verified),
            "tables_checked": len(captured),
            "tables_total": total if isinstance(total, int) else None,
            "tables_truncated": None if truncated is None else bool(truncated),
            "checks": checks,
        }


def _default_service() -> GatherService:
    return GatherService()


_SERVICE: GatherService | None = None


def service() -> GatherService:
    """The process-wide service (one Manager, one loaded config)."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = _default_service()
    return _SERVICE
