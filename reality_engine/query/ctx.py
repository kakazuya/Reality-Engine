"""Query context: read-only connections and the tool handles the planners use.

One context per answer; it owns the SQLite connections (WAL readers), the lazy
DuckDB handle on the dated snapshot, and the ``reality-data`` tool functions.
Every planner takes the context so a test can point it at a temp data root or
override a tool.
"""
from __future__ import annotations

import importlib
import os
import sys
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

# T1 pilot build (golden-rule step 4): the whole-market deterministic tier.  Off unless
# the run points at it: REALITY_MARKET_STATE / REALITY_FACTS name the two files, or
# REALITY_PILOT_T1 names the build directory.  Tests never see it by accident.
PILOT_T1_ENV = "REALITY_PILOT_T1"
T1_FILES = {
    "market_state": ("REALITY_MARKET_STATE", "market_state_pilot.db"),
    "facts_pilot": ("REALITY_FACTS", "facts_pilot.db"),
}


def t1_path(name: str) -> Path | None:
    env_file, filename = T1_FILES[name]
    path = os.environ.get(env_file)
    if path:
        return Path(path)
    root = os.environ.get(PILOT_T1_ENV)
    return Path(root) / filename if root else None


class QueryUnavailable(RuntimeError):
    """A store/table this planner needs is not present in this data root."""


def default_root() -> Path:
    env = os.environ.get("REALITY_DATA_ROOT")
    return Path(env) if env else REPO / "reality_engine" / "data"


@dataclass
class Ctx:
    root: Path | str | None = None
    overrides: dict[str, Callable[..., Any]] = field(default_factory=dict)
    _sql: dict[str, Any] = field(default_factory=dict, repr=False)
    _duck: Any = field(default=None, repr=False)
    duck_error: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root) if self.root else default_root()

    # -- SQLite -----------------------------------------------------------
    def sqlite(self, name: str) -> Any:
        """Connection for one database alias (``equity_intelligence`` ... or a T1 pilot DB)."""
        if name not in self._sql:
            if name in T1_FILES:
                path = t1_path(name)
                if path is None or not path.is_file():
                    raise QueryUnavailable(f"T1 pilot database {name} not configured "
                                           f"(set {T1_FILES[name][0]} or {PILOT_T1_ENV})")
            else:
                path = Path(self.root) / DB_FILES[name]
                if name == "macro_pilot":
                    override = os.environ.get(PILOT_DB_ENV)
                    if override:
                        path = Path(override)
            if not path.exists():
                raise QueryUnavailable(f"{name} database missing: {path}")
            from reality_engine.db.readonly import connect_ro
            import sqlite3
            con = connect_ro(path, timeout_s=30, check_same_thread=False,
                             cache_size_kib=-131072)
            con.row_factory = sqlite3.Row
            self._sql[name] = con
        return self._sql[name]

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

    # -- DuckDB snapshot --------------------------------------------------
    def duck(self) -> Any:
        if self._duck is None:
            if self.duck_error:
                raise QueryUnavailable(self.duck_error)
            try:
                import duckdb
            except Exception as exc:  # noqa: BLE001 - a missing optional dep is a degraded path
                self.duck_error = f"duckdb not installed: {exc}"
                raise QueryUnavailable(self.duck_error)
            candidates = sorted((Path(self.root) / "snapshots").glob("truth_*.duckdb"))
            if not candidates:
                self.duck_error = f"no truth_*.duckdb under {Path(self.root) / 'snapshots'}"
                raise QueryUnavailable(self.duck_error)
            path = max(candidates, key=lambda p: p.name)
            self._duck = duckdb.connect(str(path), read_only=True)
        return self._duck

    def duck_rows(self, sql: str, params: Any = ()) -> list[dict[str, Any]]:
        cur = self.duck().execute(sql, list(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

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
        for con in self._sql.values():
            try:
                con.close()
            except Exception:
                pass
        self._sql.clear()
        if self._duck is not None:
            try:
                self._duck.close()
            except Exception:
                pass
            self._duck = None
