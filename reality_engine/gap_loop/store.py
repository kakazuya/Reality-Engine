"""The loop's SQLite store and the sandbox write guard (T-048).

``kec.db`` holds ``doc_text`` (and its FTS5 index), ``docs``, the KEC rows copied out of the
read-only stores with their source recorded in ``sources``, and the loop's own ``facts``,
``formulas`` and ``answers``.  Every path the loop writes goes through ``inside()``: the sandbox
root is the only writable place, and a path that resolves outside it raises ``SandboxViolation``
before anything is opened.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

DB_NAME = "kec.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_text(
    doc_key TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL,
    method TEXT NOT NULL, known_at TEXT, PRIMARY KEY(doc_key, page));
CREATE TABLE IF NOT EXISTS docs(
    doc_key TEXT PRIMARY KEY, doc_type TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
    filing_date TEXT, known_at TEXT, pages INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '', source_key TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS sources(
    table_name TEXT PRIMARY KEY, source_db TEXT NOT NULL, source_table TEXT NOT NULL,
    key TEXT NOT NULL DEFAULT '', rows INTEGER NOT NULL, built_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, measure TEXT NOT NULL, value REAL NOT NULL,
    unit TEXT NOT NULL, period TEXT NOT NULL, basis TEXT NOT NULL DEFAULT '',
    doc_key TEXT NOT NULL, page INTEGER NOT NULL, quote TEXT NOT NULL,
    known_at TEXT NOT NULL, tier INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS formulas(
    name TEXT PRIMARY KEY, expression TEXT NOT NULL, inputs TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS answers(
    round INTEGER NOT NULL, qid TEXT NOT NULL, status TEXT NOT NULL,
    answer_json TEXT NOT NULL, gap_type TEXT, tier INTEGER NOT NULL,
    PRIMARY KEY(round, qid));
CREATE INDEX IF NOT EXISTS facts_measure ON facts(measure, period);
CREATE INDEX IF NOT EXISTS docs_known_at ON docs(known_at);
CREATE VIRTUAL TABLE IF NOT EXISTS doc_text_fts USING fts5(text);
CREATE TRIGGER IF NOT EXISTS doc_text_ai AFTER INSERT ON doc_text BEGIN
    INSERT INTO doc_text_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS doc_text_ad AFTER DELETE ON doc_text BEGIN
    DELETE FROM doc_text_fts WHERE rowid = old.rowid;
END;
CREATE TRIGGER IF NOT EXISTS doc_text_au AFTER UPDATE ON doc_text BEGIN
    DELETE FROM doc_text_fts WHERE rowid = old.rowid;
    INSERT INTO doc_text_fts(rowid, text) VALUES (new.rowid, new.text);
END;
"""


class SandboxViolation(RuntimeError):
    """A write was refused because its target resolves outside the sandbox root."""


def inside(root: Path, *parts: str | Path) -> Path:
    """``root / parts`` resolved, refusing anything outside ``root`` (case-insensitive on Windows)."""
    resolved_root = Path(root).resolve()
    target = Path(parts[0]) if len(parts) == 1 and Path(parts[0]).is_absolute() else resolved_root.joinpath(*parts)
    resolved = target.resolve()
    left = os.path.normcase(str(resolved_root) + os.sep)
    right = os.path.normcase(str(resolved) + os.sep)
    if right != left and not right.startswith(left):
        raise SandboxViolation(f"refusing to write outside the sandbox: {resolved}")
    return resolved


def write_text_inside(root: Path, relative: str, text: str) -> Path:
    path = inside(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def append_jsonl_inside(root: Path, relative: str, row: dict) -> Path:
    path = inside(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def connect(root: Path, name: str = DB_NAME) -> sqlite3.Connection:
    path = inside(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def page_lookup(conn: sqlite3.Connection):
    """A ``page_lookup(doc_key, page) -> (text, known_at)`` bound to this store."""

    def lookup(doc_key, page):
        try:
            row = conn.execute(
                "SELECT text, known_at FROM doc_text WHERE doc_key=? AND page=?", (str(doc_key), int(page))
            ).fetchone()
        except (TypeError, ValueError):
            return None
        return (row[0], row[1]) if row else None

    return lookup


def row_lookup(conn: sqlite3.Connection):
    """A ``row_lookup(table, rowid) -> {column: value}`` over this store's own tables.

    A number may cite a row of any table in ``kec.db`` instead of a page; the check reads that row
    here.  The table name is validated and must exist, so it is safe in the statement.
    """

    def lookup(table, rowid):
        name = str(table or "").strip()
        if not (name.isidentifier() and not name.startswith("sqlite_")):
            return None
        try:
            cursor = conn.execute(f'SELECT * FROM "{name}" WHERE rowid=?', (int(rowid),))
        except (TypeError, ValueError, sqlite3.OperationalError):
            return None
        row = cursor.fetchone()
        if row is None:
            return None
        return {column[0]: value for column, value in zip(cursor.description, row)}

    return lookup


def put_doc(conn: sqlite3.Connection, row: dict) -> None:
    """One ``docs`` row per PDF under ``raw``."""
    conn.execute(
        "INSERT INTO docs(doc_key, doc_type, title, filing_date, known_at, pages, source, source_key) "
        "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(doc_key) DO UPDATE SET doc_type=excluded.doc_type, "
        "title=excluded.title, filing_date=excluded.filing_date, known_at=excluded.known_at, "
        "pages=excluded.pages, source=excluded.source, source_key=excluded.source_key",
        (row["doc_key"], row.get("doc_type") or "", row.get("title") or "", row.get("filing_date"),
         row.get("known_at"), int(row.get("pages") or 0), row.get("source") or "",
         row.get("source_key") or ""),
    )


def put_source(conn: sqlite3.Connection, table: str, source_db: str, source_table: str, key: str,
               rows: int, built_at: str) -> None:
    """Record which read-only table a copied ``kec.db`` table came from and how many rows it has."""
    conn.execute(
        "INSERT INTO sources(table_name, source_db, source_table, key, rows, built_at) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(table_name) DO UPDATE SET source_db=excluded.source_db, "
        "source_table=excluded.source_table, key=excluded.key, rows=excluded.rows, "
        "built_at=excluded.built_at",
        (table, source_db, source_table, key, int(rows), built_at),
    )


def put_doc_text(conn: sqlite3.Connection, doc_key: str, page: int, text: str, method: str,
                 known_at: str | None) -> bool:
    """Insert one page; True when it is new, False when an existing page was replaced."""
    existed = conn.execute("SELECT 1 FROM doc_text WHERE doc_key=? AND page=?", (doc_key, page)).fetchone() is not None
    conn.execute(
        "INSERT INTO doc_text(doc_key, page, text, method, known_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(doc_key, page) DO UPDATE SET text=excluded.text, method=excluded.method, known_at=excluded.known_at",
        (doc_key, int(page), text, method, known_at),
    )
    return not existed



def add_fact(conn: sqlite3.Connection, row: dict) -> int:
    cur = conn.execute(
        "INSERT INTO facts(measure, value, unit, period, basis, doc_key, page, quote, known_at, tier) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (row["measure"], float(row["value"]), row["unit"], row["period"], row.get("basis") or "",
         row["doc_key"], int(row["page"]), row["quote"], row["known_at"], int(row.get("tier") or 1)),
    )
    return int(cur.lastrowid or 0)


def add_formula(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        "INSERT INTO formulas(name, expression, inputs, description) VALUES(?,?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET expression=excluded.expression, inputs=excluded.inputs, "
        "description=excluded.description",
        (row["name"], row["expression"], row.get("inputs") or "", row.get("description") or ""),
    )


def put_answer(conn: sqlite3.Connection, round_no: int, row: dict) -> None:
    conn.execute(
        "INSERT INTO answers(round, qid, status, answer_json, gap_type, tier) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(round, qid) DO UPDATE SET status=excluded.status, answer_json=excluded.answer_json, "
        "gap_type=excluded.gap_type, tier=excluded.tier",
        (int(round_no), row["qid"], row["status"], json.dumps(row, ensure_ascii=False),
         row.get("gap_type") or "", int(row.get("tier") or 1)),
    )


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("doc_text", "docs", "facts", "formulas", "answers")}


def latest_answers(conn: sqlite3.Connection) -> dict[str, dict]:
    """The newest stored row per question."""
    rows = conn.execute(
        "SELECT a.qid, a.status, a.answer_json, a.gap_type, a.tier FROM answers a "
        "JOIN (SELECT qid, MAX(round) AS r FROM answers GROUP BY qid) m ON a.qid=m.qid AND a.round=m.r"
    ).fetchall()
    return {qid: {"qid": qid, "status": status, "answer": json.loads(payload),
                  "gap_type": gap, "tier": tier}
            for qid, status, payload, gap, tier in rows}
