"""LanceDB-backed vectors with a dependency-free JSON/NumPy fallback."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Optional

from reality_engine.config import LANCEDB_DIR

# Query embeddings are memoized per process. The same query string is embedded once per
# candidate scrip in a report (the query literal in
# orchestrator.evaluate_candidate_scrip is identical for every candidate), and each ONNX
# call costs ~0.6s. Cache is bounded and process-scoped, so a model swap cannot serve
# stale vectors -- the key never outlives the process that produced it.
_EMBED_CACHE_MAX = 256


class VectorStoreManager:
    def __init__(self, db_path: Optional[str | Path] = None, dimension: int = 384):
        self.path = Path(db_path) if db_path is not None else LANCEDB_DIR
        self.path.mkdir(parents=True, exist_ok=True)
        self.dimension = dimension
        self._rows_path = self.path / "vectors.json"
        self._rows: list[dict[str, Any]] = self._load()
        self._embed_cache: dict[tuple[str, bool], tuple[float, ...]] = {}
        # LanceDB is connected on first *write* (see _table_handle). Read paths use the
        # in-memory JSON rows only, and connecting eagerly cost ~7s of every read-only
        # process (every CLI verb, every test module).
        self._table = None
        self._table_disabled = False

    def _table_handle(self):
        """LanceDB table handle, connected lazily on first use. None when unavailable."""
        if self._table is not None or self._table_disabled:
            return self._table
        try:
            import lancedb  # type: ignore
            self._table = lancedb.connect(str(self.path)).create_table(
                "concall_embeddings",
                data=self._rows or [{"id": "_init", "text": "", "vector": [0.0] * self.dimension}],
                exist_ok=True,
            )
            if not self._rows:
                self._table.delete("id = '_init'")
        except (ImportError, Exception):
            self._table = None
            self._table_disabled = True
        return self._table

    def _load(self) -> list[dict[str, Any]]:
        # npy + sidecar preferred (mmap, no 585 MB JSON parse); JSON fallback kept.
        npy = self.path / "vectors.npy"
        meta = self.path / "vectors_meta.json"
        if npy.exists() and meta.exists():
            try:
                import numpy as np
                self._matrix = np.load(str(npy), mmap_mode="r")
                metas = json.loads(meta.read_text(encoding="utf-8"))
                rows = []
                for i, m in enumerate(metas):
                    rows.append({
                        "id": m.get("id"), "symbol": m.get("symbol", ""),
                        "isin": m.get("isin", ""), "source_type": m.get("source_type", ""),
                        "document_date": m.get("document_date", ""),
                        "text": m.get("text", ""),
                        "_idx": i,
                    })
                return rows
            except (OSError, ValueError):
                pass
        self._matrix = None
        if not self._rows_path.exists():
            return []
        try:
            rows = json.loads(self._rows_path.read_text(encoding="utf-8"))
            for i, r in enumerate(rows):
                r["_idx"] = i
            return rows
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self) -> None:
        self._rows_path.write_text(json.dumps(self._rows), encoding="utf-8")

    def _save_append(self, vecs: list, metas: list) -> None:
        """Persist fresh rows: npy + sidecar when migrated, else legacy JSON."""
        npy = self.path / "vectors.npy"
        meta = self.path / "vectors_meta.json"
        if npy.exists() and meta.exists() and vecs:
            try:
                import numpy as np
                old = np.load(str(npy), mmap_mode="r")
                mat = np.concatenate(
                    [np.asarray(old), np.asarray(vecs, dtype="float32")], axis=0)
                np.save(str(npy), mat)
                cur = json.loads(meta.read_text(encoding="utf-8"))
                cur.extend(metas)
                meta.write_text(json.dumps(cur), encoding="utf-8")
                self._matrix = np.load(str(npy), mmap_mode="r")
                return
            except (OSError, ValueError):
                pass
        self._save()

    def embed(self, text: str, is_query: bool = False) -> list[float]:
        # Memoized: identical (text, is_query) within one process reuses the vector.
        cache_key = (text or "", bool(is_query))
        cached = self._embed_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        vector = self._embed_uncached(text, is_query)
        if len(self._embed_cache) >= _EMBED_CACHE_MAX:
            # dict preserves insertion order; drop the oldest entry
            self._embed_cache.pop(next(iter(self._embed_cache)), None)
        self._embed_cache[cache_key] = tuple(vector)
        return vector

    def _embed_uncached(self, text: str, is_query: bool = False) -> list[float]:
        # Local ONNX (DirectML) first; hash fallback when unavailable.
        try:
            from reality_engine.ingestion.onnx_embedder import onnx_embedder
            vec = onnx_embedder.embed(text or "", is_query=is_query)
            if vec:
                if len(vec) != self.dimension:
                    self.dimension = len(vec)
                return vec
        except (ImportError, Exception):
            pass
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            if not hasattr(self, "_model"):
                self._model = SentenceTransformer("BAAI/bge-m3", device="cpu")
                self.dimension = self._model.get_sentence_embedding_dimension()
            vector = self._model.encode([text], normalize_embeddings=True)[0].tolist()
            return vector
        except (ImportError, Exception):
            vector = [0.0] * self.dimension
            for token in re.findall(r"\w+", (text or "").lower()):
                index = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dimension
                vector[index] += 1.0
            norm = math.sqrt(sum(x * x for x in vector)) or 1.0
            return [x / norm for x in vector]

    def embed_many(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        """Batched embed (one ONNX session call per batch; hash fallback per text)."""
        if not texts:
            return []
        try:
            from reality_engine.ingestion.onnx_embedder import onnx_embedder
            vecs = onnx_embedder.embed_many(list(texts), is_query=is_query)
            if vecs and len(vecs) == len(texts):
                if len(vecs[0]) != self.dimension:
                    self.dimension = len(vecs[0])
                return vecs
        except (ImportError, Exception):
            pass
        return [self.embed(t, is_query=is_query) for t in texts]

    def add_chunks(self, chunks: list[dict[str, Any] | Any]) -> int:
        rows = []
        for chunk in chunks:
            data = chunk.to_dict() if hasattr(chunk, "to_dict") else dict(chunk)
            data["id"] = data.get("id") or hashlib.sha256(data["text"].encode()).hexdigest()
            rows.append(data)
        # One batched ONNX call (not one session Run per chunk).
        vecs = self.embed_many([r.get("text", "") for r in rows])
        for data, vec in zip(rows, vecs):
            data["vector"] = vec
        known = {row["id"] for row in self._rows}
        fresh = [row for row in rows if row["id"] not in known]
        self._rows.extend(fresh)
        self._save_append([r.get("vector", []) for r in fresh],
                          [{k: r.get(k) for k in ("id", "symbol", "isin", "source_type", "document_date", "text")} for r in fresh])
        table = self._table_handle()
        if table and rows:
            table.add(rows)
        return len(rows)

    def search(self, query: str, symbol: Optional[str] = None, top_k: int = 10) -> list[dict[str, Any]]:
        query_vector = self.embed(query, is_query=True)
        # npy path: numpy dot over the symbol-filtered index (no per-candidate zip).
        mat = getattr(self, "_matrix", None)
        if mat is not None:
            import numpy as np
            idx = [i for i, r in enumerate(self._rows) if not symbol or r.get("symbol") == symbol]
            if not idx:
                return []
            q = np.asarray(query_vector, dtype="float32")
            scores = mat[idx] @ q
            order = np.argsort(-scores, kind="stable")[: max(0, top_k)]
            return [dict(self._rows[idx[i]], vector_score=float(scores[i])) for i in order]
        candidates = [r for r in self._rows if not symbol or r.get("symbol") == symbol]
        scored = [(sum(a * b for a, b in zip(query_vector, r.get("vector", []))), r) for r in candidates]
        return [dict(row, vector_score=score) for score, row in sorted(scored, key=lambda x: x[0], reverse=True)[:top_k]]
