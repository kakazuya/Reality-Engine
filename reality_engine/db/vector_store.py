"""LanceDB-backed vectors with a dependency-free JSON/NumPy fallback."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Optional

from reality_engine.config import LANCEDB_DIR


class VectorStoreManager:
    def __init__(self, db_path: Optional[str | Path] = None, dimension: int = 384):
        self.path = Path(db_path) if db_path is not None else LANCEDB_DIR
        self.path.mkdir(parents=True, exist_ok=True)
        self.dimension = dimension
        self._rows_path = self.path / "vectors.json"
        self._rows: list[dict[str, Any]] = self._load()
        self._table = None
        try:
            import lancedb  # type: ignore
            self._table = lancedb.connect(str(self.path)).create_table("concall_embeddings", data=self._rows or [{"id": "_init", "text": "", "vector": [0.0] * dimension}], exist_ok=True)
            if not self._rows:
                self._table.delete("id = '_init'")
        except (ImportError, Exception):
            self._table = None

    def _load(self) -> list[dict[str, Any]]:
        if not self._rows_path.exists():
            return []
        try:
            return json.loads(self._rows_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self) -> None:
        self._rows_path.write_text(json.dumps(self._rows), encoding="utf-8")

    def embed(self, text: str) -> list[float]:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            if not hasattr(self, "_model"):
                self._model = SentenceTransformer("BAAI/bge-m3", device="cpu")
                self.dimension = self._model.get_sentence_embedding_dimension()
            vector = self._model.encode([text], normalize_embeddings=True)[0].tolist()
            return vector
        except (ImportError, Exception):
            vector = [0.0] * self.dimension
            for token in re.findall(r"\w+", text.lower()):
                index = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dimension
                vector[index] += 1.0
            norm = math.sqrt(sum(x * x for x in vector)) or 1.0
            return [x / norm for x in vector]

    def add_chunks(self, chunks: list[dict[str, Any] | Any]) -> int:
        rows = []
        for chunk in chunks:
            data = chunk.to_dict() if hasattr(chunk, "to_dict") else dict(chunk)
            data["id"] = data.get("id") or hashlib.sha256(data["text"].encode()).hexdigest()
            data["vector"] = self.embed(data.get("text", ""))
            rows.append(data)
        known = {row["id"] for row in self._rows}
        self._rows.extend(row for row in rows if row["id"] not in known)
        self._save()
        if self._table and rows:
            self._table.add(rows)
        return len(rows)

    def search(self, query: str, symbol: Optional[str] = None, top_k: int = 10) -> list[dict[str, Any]]:
        query_vector = self.embed(query)
        candidates = [r for r in self._rows if not symbol or r.get("symbol") == symbol]
        scored = [(sum(a * b for a, b in zip(query_vector, r.get("vector", []))), r) for r in candidates]
        return [dict(row, vector_score=score) for score, row in sorted(scored, key=lambda x: x[0], reverse=True)[:top_k]]
