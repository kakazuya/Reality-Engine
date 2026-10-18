"""LanceDB-backed vectors with a dependency-free JSON/NumPy fallback."""

from __future__ import annotations

import hashlib
import json
import math
import os
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
        # Append-only fallback store avoids copying the complete corpus on every document.
        self._append_vectors_path = self.path / "vectors.f32"
        self._append_meta_path = self.path / "vectors_meta.jsonl"
        self._append_shape_path = self.path / "vectors_shape.json"
        self._append_store = False
        self._append_rows = 0
        self._append_capacity = 0
        self._rows: list[dict[str, Any]] = self._load()
        self._embed_cache: dict[tuple[str, bool], tuple[float, ...]] = {}
        # LanceDB is connected on first *write* (see _table_handle). Read paths use the
        # in-memory JSON rows only, and connecting eagerly cost ~7s of every read-only
        # process (every CLI verb, every test module).
        self._table = None
        self._table_disabled = False

    def close(self) -> None:
        """Release memory-mapped vector files (important on Windows)."""
        matrix = getattr(self, "_matrix", None)
        if matrix is None:
            return
        base = matrix
        while getattr(base, "base", None) is not None:
            base = base.base
        mmap_handle = getattr(base, "_mmap", None)
        if mmap_handle is not None:
            mmap_handle.close()
        self._matrix = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

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
        # Append-only raw matrix preferred. Metadata is line-delimited so a
        # document does not rewrite the entire sidecar.
        if self._append_vectors_path.exists() and self._append_meta_path.exists() and self._append_shape_path.exists():
            try:
                import numpy as np

                shape = json.loads(self._append_shape_path.read_text(encoding="utf-8"))
                rows_count = int(shape["rows"])
                self._append_capacity = int(shape["capacity"])
                self.dimension = int(shape["dimension"])
                if rows_count < 0 or self._append_capacity < rows_count or self.dimension <= 0:
                    raise ValueError("invalid append-store shape")
                expected_bytes = self._append_capacity * self.dimension * 4
                if self._append_vectors_path.stat().st_size < expected_bytes:
                    raise ValueError("truncated append-store matrix")
                rows = []
                with self._append_meta_path.open("r", encoding="utf-8") as fh:
                    for i, line in enumerate(fh):
                        if i >= rows_count:
                            break
                        meta = json.loads(line)
                        rows.append({
                            "id": meta.get("id"), "symbol": meta.get("symbol", ""),
                            "isin": meta.get("isin", ""), "source_type": meta.get("source_type", ""),
                            "document_date": meta.get("document_date", ""),
                            "text": meta.get("text", ""), "_idx": i,
                        })
                if len(rows) != rows_count:
                    raise ValueError("append-store metadata is incomplete")
                self._append_rows = rows_count
                self._append_store = True
                matrix = np.memmap(
                    str(self._append_vectors_path), mode="r", dtype="float32",
                    shape=(self._append_capacity, self.dimension),
                )
                self._matrix = matrix[:rows_count]
                return rows
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                self._append_store = False

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
                        "text": m.get("text", ""), "_idx": i,
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

    @staticmethod
    def _meta_row(row: dict[str, Any]) -> dict[str, Any]:
        return {k: row.get(k) for k in ("id", "symbol", "isin", "source_type", "document_date", "text")}

    def _write_append_shape(self) -> None:
        tmp = self._append_shape_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "rows": self._append_rows,
            "capacity": self._append_capacity,
            "dimension": self.dimension,
        }), encoding="utf-8")
        os.replace(tmp, self._append_shape_path)

    def _create_append_store(self, existing_rows: int) -> None:
        """Create the append-only matrix once, preserving legacy stores."""
        import numpy as np

        old_matrix = None
        old_n = int(existing_rows)
        npy = self.path / "vectors.npy"
        meta = self.path / "vectors_meta.json"
        if npy.exists() and meta.exists():
            old_matrix = np.load(str(npy), mmap_mode="r")
            old_n = min(old_n, int(old_matrix.shape[0]))
            self.dimension = int(old_matrix.shape[1])
        elif self._rows and self._rows[0].get("vector"):
            self.dimension = len(self._rows[0]["vector"])

        capacity = max(1024, old_n + max(1024, old_n // 2))
        raw_tmp = self._append_vectors_path.with_suffix(".f32.tmp")
        with raw_tmp.open("wb") as fh:
            fh.truncate(capacity * self.dimension * 4)
        matrix = np.memmap(str(raw_tmp), mode="r+", dtype="float32", shape=(capacity, self.dimension))
        try:
            for start in range(0, old_n, 1024):
                end = min(start + 1024, old_n)
                if old_matrix is not None:
                    matrix[start:end] = np.asarray(old_matrix[start:end], dtype="float32")
                else:
                    matrix[start:end] = np.asarray(
                        [self._rows[i].get("vector", [0.0] * self.dimension) for i in range(start, end)],
                        dtype="float32",
                    )
            matrix.flush()
        finally:
            del matrix
        os.replace(raw_tmp, self._append_vectors_path)

        meta_tmp = self._append_meta_path.with_suffix(".jsonl.tmp")
        with meta_tmp.open("w", encoding="utf-8") as fh:
            for row in self._rows[:old_n]:
                fh.write(json.dumps(self._meta_row(row), separators=(",", ":")) + "\n")
        os.replace(meta_tmp, self._append_meta_path)
        self._append_rows = old_n
        self._append_capacity = capacity
        self._append_store = True
        self._write_append_shape()

    def _grow_append_store(self, required: int) -> None:
        import numpy as np

        if required <= self._append_capacity:
            return
        # Windows refuses os.replace on a file that is still memory-mapped: release our read map first. Without this
        # (2026-10-18) every add after the store filled hit OSError and fell back to rewriting the whole vectors.json
        # (~450 MB per document, ~150 MB/s of writes), and those vectors never reached vectors.f32.
        self.close()
        new_capacity = max(required, max(1024, self._append_capacity * 2))
        raw_tmp = self._append_vectors_path.with_suffix(".f32.tmp")
        with raw_tmp.open("wb") as fh:
            fh.truncate(new_capacity * self.dimension * 4)
        old = np.memmap(
            str(self._append_vectors_path), mode="r", dtype="float32",
            shape=(self._append_capacity, self.dimension),
        )
        new = np.memmap(str(raw_tmp), mode="r+", dtype="float32", shape=(new_capacity, self.dimension))
        try:
            for start in range(0, self._append_rows, 1024):
                end = min(start + 1024, self._append_rows)
                new[start:end] = old[start:end]
            new.flush()
        finally:
            del old
            del new
        os.replace(raw_tmp, self._append_vectors_path)
        self._append_capacity = new_capacity

    def _save_append(self, vecs: list, metas: list, existing_rows: int) -> None:
        """Append vectors/metadata without copying the complete corpus."""
        if not vecs:
            return
        try:
            import numpy as np

            if not self._append_store:
                self._create_append_store(existing_rows)
            arr = np.asarray(vecs, dtype="float32")
            if arr.ndim != 2 or arr.shape[1] != self.dimension:
                raise ValueError("vector dimensions do not match append store")
            start = self._append_rows
            end = start + len(arr)
            self._grow_append_store(end)
            matrix = np.memmap(
                str(self._append_vectors_path), mode="r+", dtype="float32",
                shape=(self._append_capacity, self.dimension),
            )
            try:
                matrix[start:end] = arr
                matrix.flush()
            finally:
                del matrix
            with self._append_meta_path.open("a", encoding="utf-8") as fh:
                for meta in metas:
                    fh.write(json.dumps(meta, separators=(",", ":")) + "\n")
            self._append_rows = end
            self._write_append_shape()
            matrix = np.memmap(
                str(self._append_vectors_path), mode="r", dtype="float32",
                shape=(self._append_capacity, self.dimension),
            )
            self._matrix = matrix[:end]
        except (ImportError, OSError, TypeError, ValueError) as exc:
            # Keep the dependency-free legacy path as a correctness fallback, but say so: it rewrites the full corpus.
            import logging
            logging.getLogger(__name__).warning("append store failed (%s); falling back to full vectors.json rewrite", exc)
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
        if not rows:
            return 0
        # PDF ingestion supplies vectors already computed for the dense subset;
        # re-embedding here doubled GPU work and memory. Other callers retain
        # the original convenience behavior.
        precomputed = all(
            isinstance(r.get("vector"), list) and len(r["vector"]) == self.dimension
            for r in rows
        )
        vecs = [r["vector"] for r in rows] if precomputed else self.embed_many([r.get("text", "") for r in rows])
        for data, vec in zip(rows, vecs):
            data["vector"] = vec
        known = {row["id"] for row in self._rows}
        fresh = [row for row in rows if row["id"] not in known]
        existing_rows = len(self._rows)
        for i, row in enumerate(fresh, start=existing_rows):
            row["_idx"] = i
        self._rows.extend(fresh)
        self._save_append(
            [r.get("vector", []) for r in fresh],
            [self._meta_row(r) for r in fresh],
            existing_rows=existing_rows,
        )
        table = self._table_handle()
        if table and rows:
            table.add(rows)
        if self._append_store and self._append_rows == len(self._rows):
            # the matrix holds these vectors; keeping Python float lists in self._rows as well grew a long ingest run
            # by ~1 GB per 1,000 transcripts (2026-10-18: 2.4 GB after 1,900, machine RAM free 1.5 GB)
            for row in fresh:
                row.pop("vector", None)
        return len(rows)

    def search(self, query: str, symbol: Optional[str] = None, top_k: int = 10) -> list[dict[str, Any]]:
        query_vector = self.embed(query, is_query=True)
        return self.search_by_vector(query_vector, symbol=symbol, top_k=top_k)

    def search_by_vector(self, query_vec: list[float], symbol: Optional[str] = None, top_k: int = 10) -> list[dict[str, Any]]:
        # npy path: numpy dot over the symbol-filtered index (no per-candidate zip).
        mat = getattr(self, "_matrix", None)
        if mat is not None:
            import numpy as np
            idx = [i for i, r in enumerate(self._rows) if not symbol or r.get("symbol") == symbol]
            if not idx:
                return []
            q = np.asarray(query_vec, dtype="float32")
            scores = mat[idx] @ q
            order = np.argsort(-scores, kind="stable")[: max(0, top_k)]
            return [dict(self._rows[idx[i]], vector_score=float(scores[i])) for i in order]
        candidates = [r for r in self._rows if not symbol or r.get("symbol") == symbol]
        scored = [(sum(a * b for a, b in zip(query_vec, r.get("vector", []))), r) for r in candidates]
        return [dict(row, vector_score=score) for score, row in sorted(scored, key=lambda x: x[0], reverse=True)[:top_k]]
