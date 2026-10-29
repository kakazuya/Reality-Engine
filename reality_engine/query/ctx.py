"""Query context: read-only connections and the tool handles the planners use.

One context per answer; it owns the SQLite connections (WAL readers), the lazy
DuckDB handle on the dated snapshot, and the ``reality-data`` tool functions.
Every planner takes the context so a test can point it at a temp data root or
override a tool.

Hops run concurrently (``answer`` submits a whole question's hops to one thread
pool), so each thread gets its own read-only SQLite connections while the DuckDB
handle is serialised by a lock.  The context also carries the per-question
result cache and the warm ``chunks_v3`` connection: nothing reconnects per hop.
"""
from __future__ import annotations

import copy
import importlib
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[2]
PLUGIN_SERVER = REPO / "plugins" / "reality-data" / "server"

DB_FILES = {
    "equity_intelligence": "equity_intelligence.db",
    "ar_facts": "ar_facts.db",
    "deck_figures": "deck_figures.db",
    "concall_facts": "concall_facts.db",
    "results_xbrl": "results_xbrl.db",
    "bse_announcements": "bse_announcements.db",
    # Built by reality_engine/pilot/macro_claims.py; absent in a plain data root.
    "macro_pilot": "macro_pilot.db",
}
#: The pilot DB lives in the worktree, not the read-only data root.
PILOT_DB_ENV = "REALITY_MACRO_PILOT_DB"
#: chunks_v3 pilot store (evidence.py reads it through this context).  The
#: controller names it with ``REALITY_CHUNKS_V3``; the build path is the default
#: so the bench does not depend on a shell variable.  A completed store, no WAL.
CHUNKS_V3_ENV = "REALITY_CHUNKS_V3"
CHUNKS_V3_DEFAULT = Path(r"D:\RealityEngine\pilot\chunks_v3_pilot.db")

# T1 pilot build (golden-rule step 4): the whole-market deterministic tier.  Off unless
# the run points at it: REALITY_MARKET_STATE / REALITY_FACTS name the two files, or
# REALITY_PILOT_T1 names the build directory.  Tests never see it by accident.
PILOT_T1_ENV = "REALITY_PILOT_T1"
T1_FILES = {
    "market_state": ("REALITY_MARKET_STATE", "market_state_pilot.db"),
    "facts_pilot": ("REALITY_FACTS", "facts_pilot.db"),
}

#: Pilot (b) store (``reality_engine.pilot.build_b``): commodity series, PIT index
#: membership, F&O open interest and the full NSE bhavcopy.  A finished build, so it
#: opens ``immutable=1``; the controller copies it into the SSD data root (the build
#: writes ``.tmp/pilot_b/``).  Absent on a machine without the pilot: every reader
#: below degrades instead of failing.
MARKET_STATE_B_ENV = "REALITY_MARKET_STATE_B"
MARKET_STATE_B_FILE = "market_state_b.db"
#: Sector PIT store (``reality_engine.pilot.build_sector_pit``): ``company_sector_pit``
#: alone, for the pilot universe, in its own small file.  The full T1 ``market_state``
#: DB carries the same table next to a 7.3M-row price panel; this alias lets RIPPLE read
#: the classification without opening that.  ``immutable=1``: a finished build.
SECTOR_PIT_ENV = "REALITY_SECTOR_PIT"
SECTOR_PIT_FILE = "sector_pit.db"
#: Aliases opened ``immutable=1``: finished pilot builds with no live WAL.  A read-only
#: sandbox cannot create the ``-shm``/``-wal`` sidecars a WAL open needs.
IMMUTABLE_ALIASES = {"metric_state", "market_state_b", "sector_pit", *T1_FILES}


def t1_path(name: str) -> Path | None:
    env_file, filename = T1_FILES[name]
    path = os.environ.get(env_file)
    if path:
        return Path(path)
    root = os.environ.get(PILOT_T1_ENV)
    return Path(root) / filename if root else None


def sector_pit_path(root: Path | None = None) -> Path | None:
    """The sector PIT store: env override, else the data root, else the worktree build.

    The worktree build (``.tmp/sector_pit.db``) is only consulted for the *default* data
    root: a caller that points the context at its own root (a fixture, another machine's
    copy) gets that root's store or nothing, never this checkout's scratch build.
    """
    override = os.environ.get(SECTOR_PIT_ENV)
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    base = Path(root) if root is not None else default_root()
    candidate = base / "pilot" / "pilot60" / SECTOR_PIT_FILE
    if candidate.is_file():
        return candidate
    if base.resolve() == default_root().resolve():
        candidate = REPO / ".tmp" / SECTOR_PIT_FILE
        if candidate.is_file():
            return candidate
    return None


def market_state_b_path(root: Path | None = None) -> Path | None:
    """The pilot (b) store: env override, else the data root, else the build output."""
    override = os.environ.get(MARKET_STATE_B_ENV)
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    base = Path(root) if root is not None else default_root()
    for candidate in (base / "pilot" / "pilot60" / MARKET_STATE_B_FILE,
                      REPO / ".tmp" / "pilot_b" / MARKET_STATE_B_FILE):
        if candidate.is_file():
            return candidate
    return None


class QueryUnavailable(RuntimeError):
    """A store/table this planner needs is not present in this data root."""


def default_root() -> Path:
    env = os.environ.get("REALITY_DATA_ROOT")
    return Path(env) if env else REPO / "reality_engine" / "data"


@dataclass
class Ctx:
    root: Path | str | None = None
    overrides: dict[str, Callable[..., Any]] = field(default_factory=dict)
    _tls: threading.local = field(default_factory=threading.local, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _all_conns: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _duck: Any = field(default=None, repr=False)
    duck_error: str | None = field(default=None, repr=False)
    _v3: dict[str, Any] = field(default_factory=dict, repr=False)
    cache: dict[Any, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root) if self.root else default_root()

    def _root(self) -> Path:
        return Path(self.root) if self.root else default_root()

    # -- per-thread SQLite connections ------------------------------------
    def _conns(self) -> dict[str, Any]:
        conns = getattr(self._tls, "conns", None)
        if conns is None:
            conns = {}
            self._tls.conns = conns
            with self._lock:
                self._all_conns.append(conns)
        return conns

    def sqlite(self, name: str) -> Any:
        """Connection for one database alias (``equity_intelligence`` ... or a T1 pilot DB)."""
        conns = self._conns()
        if name not in conns:
            if name == "metric_state":
                # The pilot-60 extraction build (reality_engine/pilot/extract60.py);
                # absent until built, so every caller degrades instead of failing.
                from reality_engine.query import metrics
                path = metrics.path()
                if path is None:
                    raise QueryUnavailable("metric_state store not built "
                                           "(run reality_engine.pilot.extract60 build)")
            elif name in T1_FILES:
                path = t1_path(name)
                if path is None or not path.is_file():
                    raise QueryUnavailable(f"T1 pilot database {name} not configured "
                                           f"(set {T1_FILES[name][0]} or {PILOT_T1_ENV})")
            elif name == "market_state_b":
                path = market_state_b_path(self._root())
                if path is None:
                    raise QueryUnavailable(f"pilot (b) database market_state_b not found "
                                           f"(set {MARKET_STATE_B_ENV})")
            elif name == "sector_pit":
                path = sector_pit_path(self._root())
                if path is None:
                    raise QueryUnavailable(f"sector PIT store not found "
                                           f"(run reality_engine.pilot.build_sector_pit, or "
                                           f"set {SECTOR_PIT_ENV})")
            else:
                path = self._root() / DB_FILES[name]
                if name == "macro_pilot":
                    override = os.environ.get(PILOT_DB_ENV)
                    if override:
                        path = Path(override)
            if not path.exists():
                raise QueryUnavailable(f"{name} database missing: {path}")
            from reality_engine.db.readonly import connect_ro
            import sqlite3
            con = connect_ro(path, timeout_s=30, check_same_thread=False,
                             cache_size_kib=-65536,
                             immutable=name in IMMUTABLE_ALIASES)
            con.row_factory = sqlite3.Row
            conns[name] = con
            try:
                con.execute("PRAGMA mmap_size=268435456")
            except Exception:  # noqa: BLE001 - an mmap refusal is not fatal
                pass
        return conns[name]

    def rows(self, db: str, sql: str, params: Any = ()) -> list[dict[str, Any]]:
        cur = self.sqlite(db).execute(sql, tuple(params))
        return [dict(row) for row in cur.fetchall()]

    def one(self, db: str, sql: str, params: Any = ()) -> dict[str, Any] | None:
        found = self.rows(db, sql, params)
        return found[0] if found else None

    def has_table(self, db: str, table: str) -> bool:
        try:
            return bool(self.one(db, "SELECT name FROM sqlite_master WHERE name=?", (table,)))
        except Exception:
            return False

    # -- chunks_v3 pilot store --------------------------------------------
    def chunks_v3(self) -> tuple[str, Any] | None:
        """(path, thread-local warm connection) for chunks_v3, or None.

        The store is a finished build (no WAL), so it opens ``immutable=1``.
        Like the main databases, each worker thread gets its own connection: a
        sqlite3 connection is not safe to share across threads.
        """
        if "path" not in self._v3:
            path = Path(os.environ.get(CHUNKS_V3_ENV) or CHUNKS_V3_DEFAULT)
            if not path.is_absolute():
                path = Path.cwd() / path
            with self._lock:
                self._v3["path"] = str(path) if path.is_file() else None
        found_path = self._v3["path"]
        if not found_path:
            return None
        conns = getattr(self._tls, "v3", None)
        if conns is None:
            conns = {}
            self._tls.v3 = conns
            with self._lock:
                self._all_conns.append(conns)
        if "conn" not in conns:
            try:
                from reality_engine.db.readonly import connect_ro
                conns["conn"] = connect_ro(found_path, timeout_s=10, immutable=True)
            except Exception:  # noqa: BLE001 - a broken pilot DB must not break the answer
                self._v3["path"] = None
                return None
        return found_path, conns["conn"]

    # -- DuckDB snapshot --------------------------------------------------
    def duck(self) -> Any:
        with self._lock:
            if self._duck is None:
                if self.duck_error:
                    raise QueryUnavailable(self.duck_error)
                try:
                    import duckdb
                except Exception as exc:  # noqa: BLE001 - a missing optional dep is a degraded path
                    self.duck_error = f"duckdb not installed: {exc}"
                    raise QueryUnavailable(self.duck_error)
                candidates = sorted((self._root() / "snapshots").glob("truth_*.duckdb"))
                if not candidates:
                    self.duck_error = f"no truth_*.duckdb under {self._root() / 'snapshots'}"
                    raise QueryUnavailable(self.duck_error)
                path = max(candidates, key=lambda p: p.name)
                self._duck = duckdb.connect(str(path), read_only=True)
            return self._duck

    def duck_rows(self, sql: str, params: Any = ()) -> list[dict[str, Any]]:
        # DuckDB connections are not thread-safe: one handle, one statement at a
        # time.  The statements are small (indexed snapshot lookups).
        with self._lock:
            cur = self.duck().execute(sql, list(params))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    # -- per-question result cache ---------------------------------------
    def cache_get(self, key: Any) -> Any:
        with self._lock:
            value = self.cache.get(key)
        return copy.deepcopy(value) if value is not None else None

    def cache_put(self, key: Any, value: Any) -> None:
        with self._lock:
            self.cache[key] = copy.deepcopy(value)

    def cache_clear(self) -> None:
        with self._lock:
            self.cache.clear()

    # -- reality-data tools ----------------------------------------------
    def tool(self, name: str) -> Callable[..., Any]:
        """The MCP tool function (or a test override) by name."""
        if name in self.overrides:
            return self.overrides[name]
        if str(PLUGIN_SERVER) not in sys.path:
            sys.path.insert(0, str(PLUGIN_SERVER))
        module = {"doc_find": "lookups_docs", "docs": "lookups_docs",
                  "doc_page": "lookups_docs", "resolve": "core",
                  "facts": "core", "price": "core",
                  "search_docs": "search_docs"}.get(name)
        if module is None:
            raise QueryUnavailable(f"unknown tool {name!r}")
        return getattr(importlib.import_module(module), name)

    def close(self) -> None:
        with self._lock:
            groups, self._all_conns = self._all_conns, []
            self._v3.clear()
            duck, self._duck = self._duck, None
        for conns in groups:
            for con in conns.values():
                try:
                    con.close()
                except Exception:
                    pass
        if duck is not None:
            try:
                duck.close()
            except Exception:
                pass
