"""Build (or rebuild) the local dense-retrieval index over document_chunks.

    python -m reality_engine.scripts.build_chunk_vector_index
    python -m reality_engine.scripts.build_chunk_vector_index --stats   # no build, just report

Idempotent: regenerates the whole snapshot (cheap — one pass over SQLite plus a
BLAS-free write). Safe to run while ingest is writing; the snapshot simply
reflects the corpus at build time, and ``stale`` info is reported so callers
know how far behind it is.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine import config as cfg  # noqa: E402
from reality_engine.search.chunk_vector_index import ChunkVectorIndex  # noqa: E402

logger = logging.getLogger("reality_engine.build_chunk_vector_index")


def _source_chunk_count(db_path: Optional[Path] = None) -> Optional[int]:
    """Cheap read-only ``COUNT(*)`` pre-check; None when the corpus is unreadable."""
    dbp = Path(db_path) if db_path else cfg.DB_PATH
    try:
        con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
        try:
            return int(con.execute("select count(*) from document_chunks").fetchone()[0])
        finally:
            con.close()
    except Exception as exc:
        logger.debug("chunk count pre-check unavailable: %s", exc)
        return None

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the document_chunks dense-retrieval index.")
    ap.add_argument("--stats", action="store_true", help="report current index state only")
    ap.add_argument("--db", default=None, help="override DB path")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress stdout; the fresh/built status line is still logged")
    args = ap.parse_args(argv)

    idx = ChunkVectorIndex()
    if args.stats:
        print(json.dumps(idx.stats(), indent=2))
        return 0

    db_override = Path(args.db) if args.db else None
    if idx.exists():
        current = _source_chunk_count(db_override)
        if current is not None:
            try:
                baseline = json.loads(
                    idx.paths[2].read_text(encoding="utf-8")).get("source_chunks_at_build")
            except Exception:
                baseline = None
            if baseline is not None and current <= int(baseline):
                msg = f"index fresh: {current} chunks (built at {baseline})"
                logger.info(msg)
                if not args.quiet:
                    print(msg)
                return 0

    meta = idx.build(db_path=db_override)
    idx2 = ChunkVectorIndex().load()
    rows = meta.get("rows", 0)
    logger.info("chunk vector index rebuilt: rows=%s source_chunks_at_build=%s",
                rows, meta.get("source_chunks_at_build"))
    if not args.quiet:
        print(json.dumps({**meta, "verify_shape": list(idx2._vecs.shape)}, indent=2))
        print(f"ALL CHECKS PASSED: {rows > 0 and idx2._vecs.shape[0] == rows}")
    return 0 if rows > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
