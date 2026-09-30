"""Backfill body-genuine fiscal-period labels on document_chunks (findings §11).

Additive only: stamps fiscal_period / fiscal_confidence / fiscal_source from
processing/document_parser.extract_fiscal_period run on the header-stripped
body (content after the first newline). content/embedding are NEVER rewritten.

Idempotent + checkpoint-resumable: each 5k-row batch commits on its own
connection; a checkpoint file records the last fully-committed chunk_id, so a
restart resumes after it. Re-running labels only rows still NULL (or all rows
with --force). Single writer: pause the ingest loop / nightly jobs while this
runs — same rule as every other backfill.

Usage:
    python -m reality_engine.scripts.backfill_fiscal_periods --db PATH [--batch-size 5000] [--limit N] [--force] [--checkpoint PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine.processing.document_parser import chunk_body, extract_fiscal_period  # noqa: E402

DEFAULT_BATCH_SIZE = 5000
DEFAULT_CHECKPOINT = "backfill_fiscal_periods.checkpoint.json"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=60.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(document_chunks)").fetchall()}
    if not cols:
        raise RuntimeError("document_chunks table missing")
    for col, ddl in (
        ("fiscal_period", "TEXT"),
        ("fiscal_confidence", "REAL"),
        ("fiscal_source", "TEXT"),
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE document_chunks ADD COLUMN {col} {ddl}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_fiscal "
        "ON document_chunks(fiscal_period, fiscal_confidence)"
    )
    conn.commit()


def _read_checkpoint(path: Path) -> int:
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("last_chunk_id", 0))
    except Exception:
        return 0


def _write_checkpoint(path: Path, last_chunk_id: int) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"last_chunk_id": int(last_chunk_id)}), encoding="utf-8")
    tmp.replace(path)


def backfill_fiscal_periods(
    db_path: str | Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: Optional[int] = None,
    force: bool = False,
    checkpoint: Optional[str | Path] = None,
    checkpoint_every_batches: int = 1,
) -> Dict[str, Any]:
    """Label document_chunks in id order; return the run summary dict."""
    db_path = Path(db_path)
    ckpt = Path(checkpoint) if checkpoint else db_path.parent / DEFAULT_CHECKPOINT
    conn = _connect(db_path)
    try:
        _ensure_columns(conn)
        resume_from = 0 if force else _read_checkpoint(ckpt)
        where = "chunk_id > ? AND fiscal_period IS NULL" if not force else "chunk_id > ?"
        total = batch_no = labeled = nulled = 0
        last_id = resume_from
        remaining = limit
        while remaining is None or remaining > 0:
            n = batch_size if remaining is None else min(batch_size, remaining)
            rows = conn.execute(
                f"SELECT chunk_id, content FROM document_chunks WHERE {where} "
                "ORDER BY chunk_id ASC LIMIT ?",
                (last_id, n),
            ).fetchall()
            if not rows:
                break
            updates = []
            for r in rows:
                try:
                    period, conf, src = extract_fiscal_period(chunk_body(r["content"]))
                except Exception:
                    period, conf, src = (None, 0.0, "NONE")
                updates.append((period, conf, src, int(r["chunk_id"])))
                if period is None:
                    nulled += 1
                else:
                    labeled += 1
            conn.executemany(
                "UPDATE document_chunks SET fiscal_period=?, fiscal_confidence=?, fiscal_source=? "
                "WHERE chunk_id=?",
                updates,
            )
            conn.commit()
            last_id = int(rows[-1]["chunk_id"])
            total += len(rows)
            batch_no += 1
            if batch_no % max(1, checkpoint_every_batches) == 0 and not force:
                _write_checkpoint(ckpt, last_id)
            if remaining is not None:
                remaining -= len(rows)
            if len(rows) < n:
                break
        if not force:
            _write_checkpoint(ckpt, last_id)
        return {
            "rows_scanned": total,
            "rows_labeled": labeled,
            "rows_null": nulled,
            "batches": batch_no,
            "last_chunk_id": last_id,
            "checkpoint": str(ckpt),
        }
    finally:
        conn.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="SQLite DB path (single writer: pause ingest first)")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--limit", type=int, default=None, help="max rows this run (default: all)")
    ap.add_argument("--force", action="store_true", help="relabel ALL rows, ignore checkpoint/NULL filter")
    ap.add_argument("--checkpoint", default=None, help="checkpoint file (default: <db-dir>/backfill_fiscal_periods.checkpoint.json)")
    args = ap.parse_args(argv)
    t0 = time.time()
    try:
        summary = backfill_fiscal_periods(
            args.db, batch_size=max(1, args.batch_size), limit=args.limit,
            force=args.force, checkpoint=args.checkpoint,
        )
    except Exception as exc:  # noqa: BLE001 - report honestly, nonzero exit
        print(json.dumps({"error": str(exc)[:300]}))
        return 1
    summary["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
