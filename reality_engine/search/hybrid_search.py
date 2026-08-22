"""Lexical plus dense search using reciprocal rank fusion."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

from reality_engine.db.database import db_manager
from reality_engine.db.vector_store import VectorStoreManager


@dataclass
class HybridHit:
    chunk_id: str
    text: str
    symbol: str = ""
    citation: str = ""
    score: float = 0.0
    fts_score: float = 0.0
    vector_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HybridSearchEngine:
    def __init__(self, db=None, vector_store: Optional[VectorStoreManager] = None):
        self.db = db or db_manager
        self.vector_store = vector_store or VectorStoreManager()

    def search(self, query: str, symbol: Optional[str] = None, top_k: int = 10) -> list[HybridHit]:
        lexical: list[Any] = []
        try:
            with self.db.session() as conn:
                sql = "SELECT rowid, chunk_id, symbol, document_date, document_text, bm25(intelligence_fts) AS rank FROM intelligence_fts WHERE intelligence_fts MATCH ?"
                params: list[Any] = [query]
                if symbol:
                    sql += " AND symbol = ?"
                    params.append(symbol)
                lexical = conn.execute(sql + " ORDER BY rank LIMIT ?", (*params, top_k * 3)).fetchall()
        except Exception:
            lexical = []
        dense = self.vector_store.search(query, symbol, top_k * 3)
        merged: dict[str, HybridHit] = {}
        for rank, row in enumerate(lexical, 1):
            key = row["chunk_id"] or str(row["rowid"])
            merged[key] = HybridHit(key, row["document_text"], row["symbol"], f"{row['symbol']} {row['document_date']}", 1 / (60 + rank), 1 / (60 + rank), 0.0)
        for rank, row in enumerate(dense, 1):
            key = row.get("id", "")
            hit = merged.setdefault(key, HybridHit(key, row.get("text", ""), row.get("symbol", ""), f"{row.get('symbol', '')} {row.get('document_date', '')}"))
            hit.vector_score = row.get("vector_score", 0.0)
            hit.score += 1 / (60 + rank)
        return sorted(merged.values(), key=lambda h: h.score, reverse=True)[:top_k]
