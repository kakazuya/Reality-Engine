"""Free dense retrieval over the stored, already-paid embedding indexes.

Neither leg here makes a paid query-embedding call:

* **seed_dense** (Nemotron / Qwen): FTS nails the best 3-5 chunks; their
  *stored* vectors are averaged into a query vector and scored against the same
  index.  This pulls in paraphrases FTS missed without embedding the query text.
* **local_dense** (old bge-small): the query is embedded locally by
  :class:`reality_engine.ingestion.onnx_embedder.OnnxEmbedder` (DirectML/CPU,
  free) and searched by the existing ``ChunkVectorIndex`` in ``search_docs``.

Query vectors are cached under ``.tmp/qcache/``, keyed by ``(model, text)`` —
and by the resolved seed chunk ids for seed vectors, because the same text
scoped to a different symbol yields a different seed set.  Hits are re-ordered
on equal scores by chunk id, so repeated queries rank identically.

Paid Nemotron/Qwen query embedding stays in :mod:`query_embed` behind
``REALITY_DATA_ALLOW_PAID_EMBED=1``; nothing in this module calls a provider.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger("reality_engine.plugins.dense_free")

SEED_K = 5
LOCAL_MODEL = "bge-small-en-v1.5"
QCACHE_DIR = Path(__file__).resolve().parents[3] / ".tmp" / "qcache"

_lock = threading.RLock()
_ids_cache: Dict[str, np.ndarray] = {}


def _index_path(index_name: str) -> "Path":
    import query_embed

    return query_embed.index_path(index_name)


def _ids(index_name: str) -> np.ndarray:
    """Sorted ``chunk_ids.npy`` for the index (mmap, cached per process)."""
    with _lock:
        cached = _ids_cache.get(index_name)
        if cached is not None:
            return cached
    path = _index_path(index_name) / "chunk_ids.npy"
    ids = np.load(path, mmap_mode="r")
    with _lock:
        _ids_cache[index_name] = ids
    return ids


def _safe_key(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(key)).strip("_") or "query"


def _cache_path(key: str, text: str) -> Path:
    digest = hashlib.sha1(str(text).encode("utf-8")).hexdigest()
    return QCACHE_DIR / f"{_safe_key(key)}_{digest}.npy"


def _unit(values: Sequence[float]) -> Optional[np.ndarray]:
    vec = np.asarray(values, dtype=np.float32).reshape(-1)
    if vec.size == 0 or not np.all(np.isfinite(vec)):
        return None
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(norm) or norm <= 0:
        return None
    return (vec / norm).astype(np.float32)


def cached_vector(key: str, text: str, produce) -> Optional[np.ndarray]:
    """Unit vector for ``(key, text)``; reads/writes ``.tmp/qcache``.

    ``produce`` returns a raw vector (or None).  A corrupt/stale cache file is
    recomputed, never raised; a read-only cache dir just means no persistence.
    """
    path = _cache_path(key, text)
    try:
        if path.exists():
            cached = _unit(np.load(path))
            if cached is not None:
                return cached
    except (OSError, ValueError):
        pass
    raw = produce() if produce is not None else None
    vector = _unit(raw) if raw is not None else None
    if vector is None:
        return None
    try:
        QCACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp.npy")
        np.save(tmp, vector)
        os.replace(tmp, path)
    except OSError as exc:
        logger.debug("dense_free: query cache write miss (%s): %s", path.name, exc)
    return vector


def seed_vector(
    index_name: str,
    seed_ids: Sequence[int],
    text: str = "",
    max_seeds: int = SEED_K,
) -> Optional[np.ndarray]:
    """Average the stored vectors of the seed chunks into one unit query vector.

    Keeps the caller's order (FTS bm25), drops ids absent from the index, and
    averages at most ``max_seeds`` of them.
    """
    import query_embed

    name = query_embed.normalise_index(index_name)
    ordered: List[int] = []
    seen: set = set()
    for cid in seed_ids:
        value = int(cid)
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    wanted = np.asarray(ordered, dtype=np.int64)
    if wanted.size == 0:
        return None
    ids = _ids(name)
    pos = np.searchsorted(ids, wanted)
    inside = pos < ids.shape[0]
    pos, wanted = pos[inside], wanted[inside]
    if pos.size == 0:
        return None
    keep = np.asarray(ids[pos]) == wanted
    pos = pos[keep][: max(1, int(max_seeds))]
    if pos.size == 0:
        return None
    found = sorted(int(cid) for cid in np.asarray(ids[pos]))
    cache_text = f"{text}\x1f" + ",".join(str(cid) for cid in found)

    def produce() -> np.ndarray:
        vectors = np.asarray(
            np.load(_index_path(name) / "chunk_vectors.npy", mmap_mode="r")[pos],
            dtype=np.float32,
        )
        return vectors.mean(axis=0)

    return cached_vector(f"seed-{name}", cache_text, produce)


def hit_score(hit: Dict[str, Any]) -> float:
    for key in ("score", "vector_score"):
        if key in hit:
            try:
                return float(hit[key])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def order_hits(hits: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic ranking: score desc, then chunk id asc."""
    return sorted(hits or [], key=lambda hit: (-hit_score(hit), int(hit["chunk_id"])))


def seed_search(
    query: str,
    index_name: str,
    seed_ids: Sequence[int],
    top_k: int = 10,
    allow_ids: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    """Cosine top-k using the seed-vector query; [] when no seed is in the index."""
    import query_embed

    query_vec = seed_vector(index_name, seed_ids, query)
    if query_vec is None:
        return []
    hits = query_embed.search_index(
        query_vec, index_name, top_k=max(1, int(top_k)), allow_ids=allow_ids
    )
    return order_hits(hits)


def local_query_vector(embedder, query: str, model: str = LOCAL_MODEL) -> Optional[np.ndarray]:
    """Free local query embed (ONNX/DirectML or CPU), cached by (model, text)."""
    if embedder is None or not str(query or "").strip():
        return None
    return cached_vector(model, query, lambda: embedder.embed(query, is_query=True))


def clear() -> None:
    """Drop the in-process chunk-id cache (tests; the on-disk query cache is left alone)."""
    with _lock:
        _ids_cache.clear()


__all__ = [
    "LOCAL_MODEL",
    "QCACHE_DIR",
    "SEED_K",
    "cached_vector",
    "clear",
    "hit_score",
    "local_query_vector",
    "order_hits",
    "seed_search",
    "seed_vector",
]
