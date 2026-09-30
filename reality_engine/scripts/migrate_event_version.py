"""Idempotent event-date/version migration for document tables (handover §4 item 1).

Unblocks the 24k-annual release: bulk ingest stays HELD until these columns land
(findings §14). Additive only: adds event_date TEXT + event_source TEXT +
doc_version INTEGER DEFAULT 1 to document_chunks + corporate_documents
(+ raw_documents when present), one event_date index per table, and one
AFTER-INSERT trigger per table so future rows are stamped without touching
ingestion code. content/embedding are NEVER rewritten.

Backfill derives event_date from the table's own date column
(document_chunks.published_date, corporate_documents.doc_date,
raw_documents.published_date) in 5k-row PK-ordered batches with a
checkpoint/resume JSON file. Rows whose source date is itself NULL keep
event_date NULL (honest undateable, counted as still_null/pending) but still
get doc_version=1 and event_source='unknown'. Re-running stamps only rows
still missing dates/versions (or re-labels NULL sources); it never overwrites
an explicit event_date.

Single writer: live runs hold the ingestion queue lock
(<db-dir>/ingestion_queue.lock, same semantics as
scripts/run_ingestion_queue._acquire_queue_lock) so hourly watchdog ticks skip
while this holds the writer. --dry-run takes no lock and writes nothing.
The embed server (:8099) is never touched.

Usage:
    python -m reality_engine.scripts.migrate_event_version --db PATH [--batch-size 5000] [--limit N] [--force] [--checkpoint PATH]
    python -m reality_engine.scripts.migrate_event_version --db PATH --dry-run
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DEFAULT_BATCH_SIZE = 5000
DEFAULT_CHECKPOINT = "migrate_event_version.checkpoint.json"
QUEUE_LOCK_NAME = "ingestion_queue.lock"

EVENT_COLUMNS = (
    ("event_date", "TEXT"),
    ("event_source", "TEXT"),
    ("doc_version", "INTEGER DEFAULT 1"),
)

# Per-table wiring. `fallback` is the table's own authoritative date column;
# `source` is the event_source label stamped when the date comes from it.
TABLES: Dict[str, Dict[str, str]] = {
    "document_chunks": {
        "pk": "chunk_id",
        "fallback": "published_date",
        "source": "published_date",
        "index": "idx_chunks_event_date",
        "trigger": "trg_chunks_event_stamp",
    },
    "corporate_documents": {
        "pk": "id",
        "fallback": "doc_date",
        "source": "doc_date",
        "index": "idx_corpdocs_event_date",
        "trigger": "trg_corpdocs_event_stamp",
    },
    "raw_documents": {
        "pk": "doc_id",
        "fallback": "published_date",
        "source": "published_date",
        "index": "idx_rawdocs_event_date",
        "trigger": "trg_rawdocs_event_stamp",
    },
}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=60.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return conn


def _table_names(conn: sqlite3.Connection) -> set:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _trigger_sql(table: str, spec: Mapping[str, str]) -> str:
    pk, fb, src, trg = spec["pk"], spec["fallback"], spec["source"], spec["trigger"]
    # Honest-NULL contract (same as backfill + fiscal pattern): when neither an
    # explicit event_date nor the table's own fallback date exists, the row stays
    # event_date NULL with event_source 'unknown' — never date('now'). Stamping
    # ingest time as event time would misdate undated docs for PIT readers.
    return (
        f"CREATE TRIGGER IF NOT EXISTS {trg} "
        f"AFTER INSERT ON {table} "
        "WHEN NEW.event_date IS NULL OR NEW.event_source IS NULL OR NEW.doc_version IS NULL "
        f"BEGIN UPDATE {table} SET "
        f"event_date = COALESCE(NEW.event_date, NEW.{fb}), "
        "event_source = COALESCE(NEW.event_source, "
        "CASE WHEN NEW.event_date IS NOT NULL THEN 'explicit' "
        f"WHEN NEW.{fb} IS NOT NULL THEN '{src}' "
        "ELSE 'unknown' END), "
        "doc_version = COALESCE(NEW.doc_version, 1) "
        f"WHERE {pk} = NEW.{pk}; END"
    )


def _ensure_schema(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Additive DDL for every event table present. Returns what was ensured."""
    present = _table_names(conn)
    ensured: Dict[str, Any] = {"tables": [], "indexes": [], "triggers": []}
    for table, spec in TABLES.items():
        if table not in present:
            continue  # minimal DBs may lack raw_documents; never crash.
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, ddl in EVENT_COLUMNS:
            if col not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        conn.execute(f"DROP TRIGGER IF EXISTS {spec['trigger']}")
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {spec['index']} ON {table}(event_date)"
        )
        conn.execute(_trigger_sql(table, spec))
        ensured["tables"].append(table)
        ensured["indexes"].append(spec["index"])
        ensured["triggers"].append(spec["trigger"])
    conn.commit()
    return ensured


def resolve_event_date(row: Mapping[str, Any]) -> Optional[str]:
    """Reader-side fallback: prefer event_date, else the table's own date col.

    Lets inference reads work identically before the migration lands (legacy
    rows carry no event_* keys) and after it. Returns None when nothing date-like
    is present — callers MUST treat that as undateable, never fabricate.
    """
    get = row.get if hasattr(row, "get") else (lambda k, d=None: row[k] if k in row else d)
    event = get("event_date")
    if event:
        return str(event)
    for key in ("published_date", "doc_date"):
        val = get(key)
        if val:
            return str(val)
    return None


def resolve_doc_version(row: Mapping[str, Any]) -> int:
    """Reader-side fallback: doc_version when stamped, else 1 (first version)."""
    get = row.get if hasattr(row, "get") else (lambda k, d=None: row[k] if k in row else d)
    ver = get("doc_version")
    return int(ver) if ver is not None else 1


def describe(db_path: str | Path) -> Dict[str, Any]:
    """Read-only audit: pending NULLs + missing DDL per table. Writes nothing."""
    db_path = Path(db_path)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        present = _table_names(conn)
        tables: Dict[str, Any] = {}
        for table, spec in TABLES.items():
            if table not in present:
                tables[table] = {"present": False}
                continue
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            missing = [c for c, _ in EVENT_COLUMNS if c not in cols]
            total = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if "event_date" in missing:
                pending: Optional[int] = total  # every row will need stamping
            else:
                pending = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE event_date IS NULL"
                    ).fetchone()[0]
                )
            idx = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?",
                (spec["index"],),
            ).fetchone()[0]
            trg = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name=?",
                (spec["trigger"],),
            ).fetchone()[0]
            tables[table] = {
                "present": True,
                "rows": total,
                "pending_nulls": pending,
                "columns_missing": missing,
                "index": bool(idx),
                "trigger": bool(trg),
            }
        return {"db": str(db_path), "dry_run": True, "tables": tables}
    finally:
        conn.close()


def _read_checkpoint(path: Path) -> Dict[str, int]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in raw.items() if k in TABLES}
    except Exception:
        return {}


def _write_checkpoint(path: Path, cursors: Dict[str, int]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cursors), encoding="utf-8")
    tmp.replace(path)


def _backfill_table(
    conn: sqlite3.Connection,
    table: str,
    spec: Mapping[str, str],
    start_after: int,
    batch_size: int,
    limit: Optional[int],
) -> Dict[str, int]:
    """Stamp one table in PK order. Only touches event_* columns."""
    pk, fb, src = spec["pk"], spec["fallback"], spec["source"]
    # Idempotent predicate: undateable-but-versioned rows (event_date NULL,
    # fallback NULL, doc_version set, event_source set) are never reselected.
    where = (
        f"({pk} > ?) AND ((event_date IS NULL AND {fb} IS NOT NULL) "
        "OR doc_version IS NULL OR event_source IS NULL)"
    )
    scanned = dated = 0
    last_id = start_after
    remaining = limit
    while remaining is None or remaining > 0:
        n = batch_size if remaining is None else min(batch_size, remaining)
        rows = conn.execute(
            f"SELECT {pk}, {fb}, event_date FROM {table} "
            f"WHERE {where} ORDER BY {pk} ASC LIMIT ?",
            (last_id, n),
        ).fetchall()
        if not rows:
            break
        updates = []
        for r in rows:
            fv = r[fb]
            updates.append((fv, src if fv is not None else "unknown", int(r[pk])))
            if fv is not None and r["event_date"] is None:
                dated += 1
        conn.executemany(
            f"UPDATE {table} SET event_date=COALESCE(event_date,?), "
            "event_source=COALESCE(event_source,?), "
            "doc_version=COALESCE(doc_version,1) "
            f"WHERE {pk}=?",
            updates,
        )
        conn.commit()
        last_id = int(rows[-1][pk])
        scanned += len(rows)
        if remaining is not None:
            remaining -= len(rows)
        if len(rows) < n:
            break
    return {"scanned": scanned, "dated": dated, "last_id": last_id}


def migrate(
    db_path: str | Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: Optional[int] = None,
    force: bool = False,
    checkpoint: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Ensure event DDL + backfill every present table. Returns run summary."""
    db_path = Path(db_path)
    ckpt = Path(checkpoint) if checkpoint else db_path.parent / DEFAULT_CHECKPOINT
    conn = _connect(db_path)
    try:
        schema = _ensure_schema(conn)
        cursors = {} if force else _read_checkpoint(ckpt)
        tables: Dict[str, Any] = {}
        batches = 0
        live_cursors: Dict[str, int] = dict(cursors)
        for table, spec in TABLES.items():
            if table not in schema["tables"]:
                continue
            start = 0 if force else int(cursors.get(table, 0))
            res = _backfill_table(conn, table, spec, start, batch_size, limit)
            still_null = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE event_date IS NULL"
                ).fetchone()[0]
            )
            tables[table] = {
                "scanned": res["scanned"],
                "dated": res["dated"],
                "still_null": still_null,
                "last_id": res["last_id"],
            }
            batches += 1
            live_cursors[table] = res["last_id"]
            if not force:
                _write_checkpoint(ckpt, live_cursors)
        if not force:
            _write_checkpoint(ckpt, live_cursors)
        return {
            "db": str(db_path),
            "schema": schema,
            "tables": tables,
            "batches": batches,
            "checkpoint": str(ckpt),
        }
    finally:
        conn.close()


def _acquire_queue_lock(db_path: Path):
    """Hold the ingestion queue lock (non-blocking). None = writer busy."""
    lock_path = db_path.parent / QUEUE_LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0)
    handle.write(b"0")
    handle.flush()
    try:
        import os

        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError):
        handle.close()
        return None
    return handle


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="SQLite DB path")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--limit", type=int, default=None, help="max rows per table this run (default: all)")
    ap.add_argument("--force", action="store_true", help="ignore checkpoint, re-sweep all rows (still NULL-only, never overwrites)")
    ap.add_argument("--checkpoint", default=None, help="checkpoint file (default: <db-dir>/migrate_event_version.checkpoint.json)")
    ap.add_argument("--dry-run", action="store_true", help="report pending NULLs + missing DDL; writes nothing, takes no lock")
    args = ap.parse_args(argv)
    t0 = time.time()
    if args.dry_run:
        try:
            summary = describe(args.db)
        except Exception as exc:  # noqa: BLE001 - report honestly, nonzero exit
            print(json.dumps({"error": str(exc)[:300]}))
            return 1
        summary["seconds"] = round(time.time() - t0, 1)
        print(json.dumps(summary))
        return 0
    lock = _acquire_queue_lock(Path(args.db))
    if lock is None:
        print(json.dumps({"error": "queue lock held by another writer; retry when free"}))
        return 3
    try:
        try:
            summary = migrate(
                args.db, batch_size=max(1, args.batch_size), limit=args.limit,
                force=args.force, checkpoint=args.checkpoint,
            )
        except Exception as exc:  # noqa: BLE001 - report honestly, nonzero exit
            print(json.dumps({"error": str(exc)[:300]}))
            return 1
    finally:
        lock.close()
    summary["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
