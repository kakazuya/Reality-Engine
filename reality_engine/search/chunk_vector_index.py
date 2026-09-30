"""Local dense-retrieval index over ``document_chunks.embedding``.

Why this exists: the documented fallback chain is pgvector -> LanceDB -> FTS5.
On a machine with neither PostgreSQL nor LanceDB, that collapses to **lexical
only** — the ~240k chunk embeddings we compute (including every DRHP) are
written but never read for similarity. This module gives the local tier its own
dense index: a float32 ``.npy`` matrix (mmap'd, BLAS-scored) plus a compact
``int64`` row->chunk_id map, both aligned with a rebuildable snapshot.

Design notes:
* Embeddings live in SQLite as TEXT JSON (384 floats, ~8.4 KB/chunk); the
  float32 matrix is ~1.5 KB/chunk, i.e. ~5x smaller and directly mmap-able.
* Brute-force exact cosine over 240k x 384 is a single BLAS GEMM (~50-150 ms),
  which beats approximate indexing at this scale and needs no new dependency.
* A ``stale`` marker is written with each build so callers can detect a corpus
  that has grown since the snapshot (the weekly/hourly ingest keeps adding rows).

Build:  ``python -m reality_engine.scripts.build_chunk_vector_index``
Query:  ``ChunkVectorIndex.load().search(vec, top_k=10, symbol="HAL")``
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from reality_engine import config as cfg

logger = logging.getLogger("reality_engine.chunk_vector_index")

INDEX_DIR = cfg.DATA_DIR / "vector_index"
VECTORS_FILE = "chunk_vectors.npy"
IDS_FILE = "chunk_ids.npy"
META_FILE = "chunk_index_meta.json"


class ChunkVectorIndex:
    """Exact cosine search over the mmap'd chunk embedding matrix."""

    def __init__(self, index_dir: Optional[Path] = None):
        self.dir = Path(index_dir) if index_dir else INDEX_DIR
        self._vecs: Optional[np.ndarray] = None
        self._ids: Optional[np.ndarray] = None
        self._meta: Dict[str, Any] = {}
        self._norms: Optional[np.ndarray] = None

    # ------------------------------------------------------------------
    # Build / load
    # ------------------------------------------------------------------
    @property
    def paths(self) -> Tuple[Path, Path, Path]:
        return self.dir / VECTORS_FILE, self.dir / IDS_FILE, self.dir / META_FILE

    def exists(self) -> bool:
        return all(p.exists() for p in self.paths)

    def build(self, db_path: Optional[Path] = None, batch: int = 20000) -> Dict[str, Any]:
        """Materialise the index from ``document_chunks`` (skips empty embeddings)."""
        db_path = Path(db_path) if db_path else cfg.DB_PATH
        self.dir.mkdir(parents=True, exist_ok=True)
        vpath, ipath, mpath = self.paths
        started = time.time()

        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.execute("PRAGMA cache_size=-65536")
        total = con.execute(
            "select count(*) from document_chunks where embedding is not null and embedding <> ''"
        ).fetchone()[0]
        vectors = np.lib.format.open_memmap(
            vpath, mode="w+", dtype=np.float32, shape=(max(total, 1), 384)
        )
        ids = np.zeros(max(total, 1), dtype=np.int64)

        written = 0
        skipped = 0
        error = None
        try:
            cur = con.execute(
                "select chunk_id, embedding from document_chunks "
                "where embedding is not null and embedding <> '' order by chunk_id"
            )
            for chunk_id, emb in cur:
                try:
                    vec = np.asarray(json.loads(emb), dtype=np.float32)
                except Exception:  # malformed JSON / wrong shape
                    skipped += 1
                    continue
                if vec.shape[0] != 384:
                    skipped += 1
                    continue
                vectors[written] = vec
                ids[written] = int(chunk_id)
                written += 1
                if written % batch == 0:
                    vectors.flush()
                    logger.info("indexed %d/%d chunks", written, total)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:200]
            logger.warning("index build stopped at %d rows: %s", written, error)

        vectors.flush()
        del vectors
        np.save(ipath, ids[:written])
        meta = {
            "rows": written,
            "skipped_malformed": skipped,
            "skipped_empty": int(total) - written - skipped,
            "dim": 384,
            "dtype": "float32",
            "db_path": str(db_path),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "build_seconds": round(time.time() - started, 1),
            "error": error,
            "source_chunks_at_build": int(
                con.execute("select count(*) from document_chunks").fetchone()[0]
            ),
        }
        mpath.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        con.close()
        logger.info("chunk vector index built: %s", meta)
        return meta

    def load(self) -> "ChunkVectorIndex":
        if not self.exists():
            raise FileNotFoundError(f"chunk vector index missing in {self.dir} — run build_chunk_vector_index")
        vpath, ipath, mpath = self.paths
        self._vecs = np.load(vpath, mmap_mode="r")          # (N, 384) float32
        self._ids = np.load(ipath)                          # (N,)     int64
        self._meta = json.loads(mpath.read_text(encoding="utf-8"))
        rows = self._meta.get("rows", 0)
        if rows and self._vecs.shape[0] != rows:            # truncated file after a kill
            self._vecs = self._vecs[:rows]
        # Pre-normalise once per process (mmap -> RAM only when scored).
        self._norms = None
        return self

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(
        self,
        query_vec: Sequence[float],
        top_k: int = 10,
        symbol: Optional[str] = None,
        allow_ids: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        """Exact cosine top-k. ``symbol``/``allow_ids`` restrict candidates."""
        if self._vecs is None:
            self.load()
        q = np.asarray(query_vec, dtype=np.float32)
        if q.shape[0] != self._vecs.shape[1]:
            raise ValueError(f"query dim {q.shape[0]} != index dim {self._vecs.shape[1]}")
        qn = float(np.linalg.norm(q)) or 1.0

        if allow_ids:
            id_to_row = {int(cid): i for i, cid in enumerate(self._ids)}
            rows = np.array([id_to_row[i] for i in allow_ids if i in id_to_row], dtype=np.int64)
        elif symbol:
            rows = self._rows_for_symbol(symbol)
        else:
            rows = np.arange(self._ids.shape[0], dtype=np.int64)
        if rows.size == 0:
            return []

        block = self._vecs[rows]                             # (M, 384) read from mmap
        scores = (block @ q) / ((np.linalg.norm(block, axis=1) * qn) + 1e-12)
        k = min(top_k, scores.shape[0])
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx])]
        return [
            {"chunk_id": int(self._ids[rows[i]]), "vector_score": float(scores[i])}
            for i in idx
        ]

    def _rows_for_symbol(self, symbol: str) -> np.ndarray:
        """Row indices whose chunk_id belongs to ``symbol`` (id index is sorted)."""
        db = self._meta.get("db_path", str(cfg.DB_PATH))
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            cids = {int(r[0]) for r in con.execute(
                "select chunk_id from document_chunks where symbol = ?", (symbol.upper(),))}
        finally:
            con.close()
        if not cids:
            return np.empty(0, dtype=np.int64)
        return np.searchsorted(self._ids, np.fromiter(sorted(cids), dtype=np.int64))

    def stats(self) -> Dict[str, Any]:
        if self._vecs is None:
            try:
                self.load()
            except FileNotFoundError:
                return {"available": False}
        return {"available": True, **self._meta,
                "bytes_on_disk": self.paths[0].stat().st_size + self.paths[1].stat().st_size}


_INDEX: Optional[ChunkVectorIndex] = None


def get_index() -> Optional[ChunkVectorIndex]:
    """Process-wide lazy singleton; None when no index has been built yet."""
    global _INDEX
    if _INDEX is None:
        idx = ChunkVectorIndex()
        if not idx.exists():
            return None
        try:
            _INDEX = idx.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning("chunk vector index load failed: %s", exc)
            return None
    return _INDEX
