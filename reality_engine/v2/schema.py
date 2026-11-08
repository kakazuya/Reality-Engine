"""Create a v2 company file from the schema contract (``schema_v2.sql``). Idempotent: every statement is
``IF NOT EXISTS``, so a build part may call it before writing."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DDL_PATH = Path(__file__).with_name("schema_v2.sql")


def ddl() -> str:
    return DDL_PATH.read_text(encoding="utf-8")


def create(conn: sqlite3.Connection) -> list[str]:
    """Apply the contract to ``conn``; returns the table names now present."""
    conn.executescript(ddl())
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
