"""Read-only, point-in-time access to ``chunks_v3_pilot.db``.

The database is WAL-mode and sits on a read-only mount without its ``-shm`` file, so
SQLite refuses a plain ``mode=ro`` open ("unable to open database file").  ``immutable=1``
is the honest read-only open here: the file cannot change under us, and no journal/shm
write is attempted.  The job brief requires this store to be read-only; this module never
writes.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(os.environ.get("READER_CHUNKS_DB") or r"C:\RE\data\pilot\pilot60\chunks_v3_pilot.db")

# Only these documents can be shown to the model.  ``quality_grade='C'`` chunks are the
# garbled-font / OCR failures and are excluded before retrieval, not after.
OK_GRADES = ("A", "B")


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    uri = "file:///" + str(p).replace("\\", "/") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def as_of_ceiling(as_of: str) -> str:
    """The as_of date is inclusive of that whole day (documents filed that evening count)."""
    s = (as_of or "").strip()
    if len(s) == 10:
        return s + "T23:59:59"
    return s


def _in_clause(n: int) -> str:
    return "(" + ",".join("?" for _ in range(n)) + ")"


def search(
    con: sqlite3.Connection,
    *,
    isin: str,
    doc_types: list[str],
    as_of: str,
    fts_query: str,
    limit: int = 80,
    body_only: bool = True,
) -> list[sqlite3.Row]:
    """Entity + doc-type + known_at filters are applied in SQL before FTS is scored.

    ``body_only`` keeps the company name in the header out of the match: that is what
    turned naive OR search into letterhead retrieval.
    """
    if not doc_types or not fts_query:
        return []
    match = f"body : ({fts_query})" if body_only else fts_query
    sql = f"""
        select c.chunk_id, c.doc_id, c.doc_type, c.header, c.body, c.section, c.speaker,
               c.speaker_role, c.unit_kind, c.known_at, c.event_date, c.fiscal_period,
               c.page_from, c.page_to, c.char_len, c.quality_grade,
               bm25(chunk_fts, 0.3, 1.0) as bm25
        from chunk_fts
        join chunk c on c.chunk_id = chunk_fts.rowid
        where chunk_fts match ?
          and c.isin = ?
          and c.known_at <= ?
          and c.doc_type in {_in_clause(len(doc_types))}
          and c.quality_grade in ('A','B')
          and c.char_len between 80 and 6000
        order by bm25
        limit ?
    """
    params = [match, isin, as_of_ceiling(as_of), *doc_types, int(limit)]
    try:
        return list(con.execute(sql, params))
    except sqlite3.OperationalError as exc:
        if "fts5: syntax error" in str(exc) or "no such column" in str(exc):
            raise ValueError(f"bad FTS query {fts_query!r}: {exc}") from exc
        raise


def corpus_stats(con: sqlite3.Connection, isin: str, as_of: str) -> dict:
    row = con.execute(
        """select count(*) n, min(known_at) lo, max(known_at) hi
           from chunk where isin=? and known_at<=? and quality_grade in ('A','B')""",
        (isin, as_of_ceiling(as_of)),
    ).fetchone()
    per = con.execute(
        """select doc_type, count(*) n from chunk
           where isin=? and known_at<=? and quality_grade in ('A','B')
           group by doc_type order by n desc""",
        (isin, as_of_ceiling(as_of)),
    ).fetchall()
    return {"chunks": row["n"], "min_known_at": row["lo"], "max_known_at": row["hi"],
            "by_type": {r["doc_type"]: r["n"] for r in per}}
