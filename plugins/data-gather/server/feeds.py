"""Feed metadata and read-only probes.

Everything here is a pure, bounded read: approved-feed parsing, ``writes``
targets, date-column discovery, the trading-day calendar, gap maths and the raw
file scan.  Every database access goes through
``reality_engine.db.readonly.connect_ro``; nothing in this module writes a row.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from reality_engine.db.readonly import QueryTimeout, connect_ro  # noqa: E402

APPROVED_SCHEMA = "data-gather-approved/1"
APPROVED_FILENAME = "approved.yaml"
DEFAULT_RAW_ROOT = Path("D:/RealityEngine/raw")
# The NSE index bhavcopy keys on (date, index_name), so a date range is an index
# seek.  mkt_nse_full_daily is 4.3M rows; using it as the calendar would make
# every gap report a full scan.
CALENDAR_DB = "equity_intelligence.db"
CALENDAR_TABLE = "mkt_nse_index_daily"
# Stored date columns, most specific first.  ``doc_date`` is deliberately absent:
# it is usually the crawl date, not the filing date.
DATE_COLUMNS = ("date", "as_of", "published_date", "month", "period")
# Columns that carry the source system's own date.  ``doc_date`` is never used
# as evidence about correct dating.
SOURCE_DATE_COLUMNS = (
    "known_at",
    "filing_date",
    "filed_at",
    "announced_at",
    "src_date",
    "source_date",
    "published_date",
)
UNTRUSTED_DATE_COLUMNS = ("doc_date",)
MARKET_TABLE_PREFIXES = ("mkt_", "etf_", "index_")
RAW_SUFFIXES = (
    ".csv",
    ".json",
    ".jsonl",
    ".xlsx",
    ".xls",
    ".pdf",
    ".html",
    ".htm",
    ".xml",
    ".zip",
    ".txt",
)
CADENCE_LOOKBACK_DAYS = {
    "hourly": 7,
    "daily": 30,
    "weekly": 120,
    "monthly": 400,
    "quarterly": 800,
    "continuous": 30,
}
DEFAULT_LOOKBACK_DAYS = 90
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ApprovedError(ValueError):
    """approved.yaml is malformed."""


def load_approved(path: Path) -> dict[str, dict[str, Any]]:
    """Read approved.yaml: ``{feed: {"max_days": int|None, "market": bool|None}}``.

    A missing file means nothing is approved.  An unreadable or malformed file
    raises instead of silently approving or blocking every feed.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ApprovedError(f"cannot read {path}: {exc}") from exc
    try:
        import yaml
    except ImportError as exc:  # declared in requirements.txt
        raise ApprovedError("PyYAML is required to read approved.yaml") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ApprovedError(f"invalid YAML in {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ApprovedError(f"{path} must contain a mapping")
    if raw.get("schema") != APPROVED_SCHEMA:
        raise ApprovedError(f"{path}: schema must be {APPROVED_SCHEMA!r}")
    feeds = raw.get("feeds")
    if feeds is None:
        return {}
    if not isinstance(feeds, dict):
        raise ApprovedError(f"{path}: feeds must be a mapping")
    approved: dict[str, dict[str, Any]] = {}
    for name, spec in feeds.items():
        if not isinstance(name, str) or not _IDENTIFIER.match(name):
            raise ApprovedError(f"{path}: invalid feed name {name!r}")
        if spec is None:
            spec = {}
        if not isinstance(spec, dict):
            raise ApprovedError(f"{path}: {name} must be a mapping or null")
        max_days = spec.get("max_days")
        if max_days is not None and (
            isinstance(max_days, bool) or not isinstance(max_days, int) or not 1 <= max_days <= 3650
        ):
            raise ApprovedError(f"{path}: {name}.max_days must be an integer in 1..3650")
        market = spec.get("market")
        if market is not None and not isinstance(market, bool):
            raise ApprovedError(f"{path}: {name}.market must be true or false")
        approved[name] = {"max_days": max_days, "market": market}
    return approved


def write_targets(writes: Iterable[Any] | None) -> list[tuple[str, str]]:
    """``["equity_intelligence.db:mkt_x", ...]`` -> ``[("equity_intelligence.db", "mkt_x")]``.

    Entries that do not name a db:table pair (free-text ``writes`` in offline
    fake jobs) are skipped rather than guessed at.
    """
    targets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in writes or []:
        if not isinstance(raw, str):
            continue
        db_name, sep, table = raw.partition(":")
        db_name, table = db_name.strip(), table.strip()
        if (
            not sep
            or not db_name.endswith(".db")
            or Path(db_name).name != db_name
            or not _IDENTIFIER.match(table)
        ):
            continue
        if (db_name, table) not in seen:
            seen.add((db_name, table))
            targets.append((db_name, table))
    return targets


def parse_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def is_market_table(table: str) -> bool:
    return str(table).startswith(MARKET_TABLE_PREFIXES)


def _quote(identifier: str) -> str:
    if not _IDENTIFIER.match(identifier):
        raise ValueError(f"unsafe SQL identifier: {identifier!r}")
    return '"' + identifier + '"'


def _data_db(data_root: Path, db_name: str) -> Path:
    root = Path(data_root).resolve()
    candidate = (root / db_name).resolve()
    if candidate.parent != root or not candidate.is_file():
        raise FileNotFoundError(f"{db_name} is not a file in {root}")
    return candidate


def _open(data_root: Path, db_name: str, timeout_s: float):
    return connect_ro(_data_db(data_root, db_name), timeout_s=timeout_s)


def _columns(con, table: str) -> set[str]:
    return {row[0] for row in con.execute("SELECT name FROM pragma_table_info(?)", (table,))}


def stored_column(columns: set[str], *, dated_only: bool = False) -> str | None:
    candidates = ("date", "as_of") if dated_only else DATE_COLUMNS
    return next((name for name in candidates if name in columns), None)


def source_column(columns: set[str], stored: str | None) -> str | None:
    return next(
        (name for name in SOURCE_DATE_COLUMNS if name in columns and name != stored), None
    )


def table_stat(
    data_root: Path, db_name: str, table: str, timeout_s: float = 10.0
) -> dict[str, Any]:
    """Row count and max stored date for one table; never raises for SQL trouble."""
    stat: dict[str, Any] = {
        "db": db_name,
        "table": table,
        "rows": None,
        "max_date": None,
        "date_column": None,
        "error": None,
    }
    try:
        con = _open(data_root, db_name, timeout_s)
    except FileNotFoundError:
        stat["error"] = "db_missing"
        return stat
    except Exception as exc:  # noqa: BLE001 - a probe failure is data, not a crash
        stat["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return stat
    try:
        columns = _columns(con, table)
        if not columns:
            stat["error"] = "table_missing"
            return stat
        column = stored_column(columns)
        stat["date_column"] = column
        try:
            stat["rows"] = int(
                con.execute(f"SELECT count(*) FROM {_quote(table)}").fetchone()[0]
            )
        except QueryTimeout:
            stat["error"] = "count_timeout"
        if column:
            row = con.execute(
                f"SELECT max({_quote(column)}) FROM {_quote(table)}"
            ).fetchone()
            if row and row[0] is not None:
                stat["max_date"] = str(row[0])[:10]
    except Exception as exc:  # noqa: BLE001
        stat["error"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        con.close()
    return stat


def first_new_rows(
    data_root: Path,
    db_name: str,
    table: str,
    after_max: str | None,
    limit: int = 5,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    """Up to ``limit`` rows dated after ``after_max``, stored date vs source date.

    ``after_max`` is the previous max of the stored date column; rows at or below
    it are not new.  The source column is the file's own known_at/filing date --
    ``doc_date`` is never compared because it is the crawl date.
    """
    result: dict[str, Any] = {
        "rows": [],
        "stored_column": None,
        "source_column": None,
        "error": None,
    }
    try:
        con = _open(data_root, db_name, timeout_s)
    except FileNotFoundError:
        result["error"] = "db_missing"
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return result
    try:
        columns = _columns(con, table)
        if not columns:
            result["error"] = "table_missing"
            return result
        stored = stored_column(columns)
        result["stored_column"] = stored
        if stored is None:
            result["error"] = (
                "only_untrusted_doc_date"
                if any(name in columns for name in UNTRUSTED_DATE_COLUMNS)
                else "no_date_column"
            )
            return result
        source = source_column(columns, stored)
        result["source_column"] = source
        if source is None:
            result["error"] = "no_source_date_column"
            return result
        where, params = "", ()
        if after_max:
            where, params = f"WHERE {_quote(stored)} > ?", (str(after_max),)
        rows = con.execute(
            f"SELECT {_quote(stored)}, {_quote(source)} FROM {_quote(table)} "
            f"{where} ORDER BY {_quote(stored)} LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return result
    finally:
        con.close()
    for stored_value, source_value in rows:
        stored_day, source_day = parse_day(stored_value), parse_day(source_value)
        lag = (stored_day - source_day).days if stored_day and source_day else None
        result["rows"].append(
            {
                "stored": str(stored_value)[:10] if stored_value is not None else None,
                "source": str(source_value)[:10] if source_value is not None else None,
                "match": (stored_day == source_day) if stored_day and source_day else None,
                "lag_days": lag,
            }
        )
    return result


def present_dates(
    data_root: Path,
    db_name: str,
    table: str,
    start: date,
    end: date,
    timeout_s: float = 10.0,
) -> tuple[set[date], str | None]:
    """Stored dates in ``[start, end]`` for one feed table."""
    try:
        con = _open(data_root, db_name, timeout_s)
    except FileNotFoundError:
        return set(), "db_missing"
    except Exception as exc:  # noqa: BLE001
        return set(), f"{type(exc).__name__}: {exc}"[:200]
    try:
        columns = _columns(con, table)
        if not columns:
            return set(), "table_missing"
        column = stored_column(columns, dated_only=True)
        if column is None:
            return set(), "no_day_column"
        rows = con.execute(
            f"SELECT DISTINCT {_quote(column)} FROM {_quote(table)} "
            f"WHERE {_quote(column)} >= ? AND {_quote(column)} <= ?",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        return set(), f"{type(exc).__name__}: {exc}"[:200]
    finally:
        con.close()
    days = {day for day in (parse_day(row[0]) for row in rows) if day is not None}
    return days, None


def trading_days(
    data_root: Path,
    start: date,
    end: date,
    db_name: str = CALENDAR_DB,
    table: str = CALENDAR_TABLE,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    """NSE trading days in ``[start, end]`` from the index bhavcopy."""
    try:
        con = _open(data_root, db_name, timeout_s)
    except FileNotFoundError:
        return {"available": False, "error": "calendar_db_missing", "dates": []}
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}"[:200],
            "dates": [],
        }
    try:
        if not _columns(con, table):
            return {"available": False, "error": "calendar_table_missing", "dates": []}
        rows = con.execute(
            f"SELECT DISTINCT date FROM {_quote(table)} WHERE date >= ? AND date <= ? "
            "ORDER BY date",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}"[:200],
            "dates": [],
        }
    finally:
        con.close()
    days = sorted(day for day in (parse_day(row[0]) for row in rows) if day is not None)
    return {"available": True, "error": None, "dates": days}


def missing_ranges(expected: Iterable[date], present: set[date]) -> list[dict[str, Any]]:
    """Coalesce consecutive missing expected days into inclusive ranges."""
    ranges: list[dict[str, Any]] = []
    run_start: date | None = None
    previous: date | None = None
    for day in sorted(expected):
        if day in present:
            if run_start is not None and previous is not None:
                ranges.append(
                    {
                        "start": run_start.isoformat(),
                        "end": previous.isoformat(),
                        "days": (previous - run_start).days + 1,
                    }
                )
            run_start = None
        elif run_start is None:
            run_start = day
        previous = day
    if run_start is not None and previous is not None:
        ranges.append(
            {
                "start": run_start.isoformat(),
                "end": previous.isoformat(),
                "days": (previous - run_start).days + 1,
            }
        )
    return ranges


def new_files(
    root: Path,
    since_epoch: float,
    *,
    suffixes: tuple[str, ...] | None = None,
    limit: int = 25,
    max_entries: int = 4000,
    max_depth: int = 4,
) -> dict[str, Any]:
    """Files whose mtime is at or after ``since_epoch``, bounded in depth and count.

    mtime (not a path diff) is the signal because a run may overwrite an
    existing file; a file copied with a preserved source mtime reads as "not
    new" -- see the README's open problems.
    """
    root = Path(root)
    result: dict[str, Any] = {
        "available": False,
        "root": str(root),
        "files": [],
        "scanned": 0,
        "truncated": False,
        "error": None,
    }
    if not root.is_dir():
        result["error"] = "raw_root_missing"
        return result
    result["available"] = True
    found: list[dict[str, Any]] = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        relative = Path(dirpath).relative_to(root)
        if len(relative.parts) >= max_depth:
            dirnames[:] = []
        dirnames.sort()
        for name in sorted(filenames):
            scanned += 1
            result["scanned"] = scanned
            if scanned > max_entries:
                result["truncated"] = True
                break
            path = Path(dirpath) / name
            if suffixes and path.suffix.lower() not in suffixes:
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            if info.st_mtime + 2.0 < since_epoch:
                continue
            found.append(
                {
                    "path": str(path),
                    "rel": str(path.relative_to(root)).replace("\\", "/"),
                    "mtime": datetime.fromtimestamp(info.st_mtime).isoformat(timespec="seconds"),
                    "size": int(info.st_size),
                }
            )
        if result["truncated"] or len(found) >= limit:
            break
    found.sort(key=lambda item: item["mtime"], reverse=True)
    result["files"] = found[:limit]
    return result
