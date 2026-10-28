"""Read-only SQLite connections with a per-statement wall-clock guard.

Agents query the 53 GB ``equity_intelligence.db`` through this helper (or the
``reality-data`` MCP tools), never through a bare connection: SQLite has no
server-side query timeout, so one correlated subquery over ``document_chunks``
can pin a subagent for minutes.

``connect_ro`` opens ``file:...?mode=ro`` (never ``immutable=1``: the live WAL
holds the recent writes), keeps temp b-trees in memory (the default temp
directory can be unwritable on this machine), sets ``query_only`` so a caller
cannot write by accident, and aborts any statement that runs past its budget
with :class:`QueryTimeout`.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Union

__all__ = ["QueryTimeout", "ReadOnlyConnection", "ReadOnlyCursor", "connect_ro"]


class QueryTimeout(sqlite3.OperationalError):
    """A read-only statement exceeded its wall-clock budget."""


class ReadOnlyCursor(sqlite3.Cursor):
    """Cursor that turns SQLite's ``interrupted`` into :class:`QueryTimeout`.

    The progress handler aborts the statement, but CPython reports that as a
    plain ``OperationalError('interrupted')``; the connection flag tells us the
    guard (not a caller) caused it.  Translation lives on the cursor too because
    a row-returning SELECT usually times out in ``fetchall``, not ``execute``.
    """

    def _translate(self, exc: sqlite3.OperationalError) -> None:
        con = self.connection
        if getattr(con, "_timed_out", False) and "interrupted" in str(exc).lower():
            raise QueryTimeout(
                f"query exceeded {con._budget_s:g}s on a read-only connection"
            ) from exc
        raise exc

    def fetchone(self):  # type: ignore[override]
        try:
            return super().fetchone()
        except sqlite3.OperationalError as exc:
            self._translate(exc)

    def fetchmany(self, size=1):  # type: ignore[override]
        try:
            return super().fetchmany(size)
        except sqlite3.OperationalError as exc:
            self._translate(exc)

    def fetchall(self):  # type: ignore[override]
        try:
            return super().fetchall()
        except sqlite3.OperationalError as exc:
            self._translate(exc)

    def __next__(self):
        try:
            return super().__next__()
        except sqlite3.OperationalError as exc:
            self._translate(exc)


class ReadOnlyConnection(sqlite3.Connection):
    """``mode=ro`` connection whose statements obey a wall-clock budget."""

    _budget_s = 30.0
    _deadline = 0.0
    _timed_out = False

    def set_timeout(self, seconds: float) -> None:
        """Change the budget for the next statement (e.g. the 5 s sql tool)."""
        self._budget_s = max(float(seconds), 0.001)
        self._deadline = 0.0

    def _arm(self) -> None:
        self._deadline = time.monotonic() + self._budget_s
        self._timed_out = False

    def _guard(self) -> int:
        if self._deadline and time.monotonic() > self._deadline:
            self._timed_out = True
            return 1  # abort the running statement
        return 0

    def _translate(self, exc: sqlite3.OperationalError) -> None:
        if self._timed_out and "interrupted" in str(exc).lower():
            raise QueryTimeout(
                f"query exceeded {self._budget_s:g}s on a read-only connection"
            ) from exc
        raise exc

    def execute(self, sql, parameters=(), /):  # type: ignore[override]
        self._arm()
        # Create the cursor ourselves: Connection.execute uses the C cursor
        # type, which would bypass ReadOnlyCursor.fetchall() translation.
        try:
            return self.cursor().execute(sql, parameters)
        except sqlite3.OperationalError as exc:
            self._translate(exc)

    def executemany(self, sql, parameters, /):  # type: ignore[override]
        self._arm()
        try:
            return self.cursor().executemany(sql, parameters)
        except sqlite3.OperationalError as exc:
            self._translate(exc)

    def cursor(self, factory=ReadOnlyCursor):  # type: ignore[override]
        return super().cursor(factory)


def connect_ro(
    path: Union[str, Path],
    timeout_s: float = 30.0,
    *,
    check_same_thread: bool = True,
    cache_size_kib: int = -65536,
    immutable: bool = False,
) -> ReadOnlyConnection:
    """Open ``path`` read-only with a per-statement timeout of ``timeout_s``.

    ``cache_size_kib`` is negative because SQLite reads a negative
    ``cache_size`` as KiB (default 64 MiB here).  ``timeout_s`` also bounds a
    lock wait (``busy_timeout``) and can be lowered per call with
    ``con.set_timeout(seconds)``.

    ``immutable=True`` is only for a finished, never-written store whose WAL
    files are gone (the pilot ``chunks_v3`` build): a live WAL database needs
    its ``-shm`` and must be opened without it.
    """
    p = Path(path).expanduser().resolve()
    uri = f"file:{p.as_posix()}?mode=ro" + ("&immutable=1" if immutable else "")
    con = sqlite3.connect(
        uri,
        uri=True,
        timeout=min(max(float(timeout_s), 0.1), 30.0),
        check_same_thread=check_same_thread,
        factory=ReadOnlyConnection,
    )
    con._budget_s = max(float(timeout_s), 0.001)
    # PRAGMAs before query_only: temp_store needs to be set while the
    # connection can still configure itself, and MEMORY is what keeps a query
    # needing temp b-trees from failing with "unable to open database file".
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute(f"PRAGMA cache_size={int(cache_size_kib)}")
    con.execute(f"PRAGMA busy_timeout={int(min(max(timeout_s, 1.0), 30.0) * 1000)}")
    con.execute("PRAGMA query_only=1")
    con.set_progress_handler(con._guard, 10_000)
    return con
