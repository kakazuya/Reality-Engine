"""Lexical plus dense search using reciprocal rank fusion.

PG primary: pgvector ivfflat cosine 1536 (document_chunks.embedding VECTOR(1536))
  -> LanceDB fallback
  -> SQLite FTS5 fallback per AGENTS.md:5

Partition reference (postgres_schema.sql:359-398):
  -- CREATE TABLE document_chunks (...) PARTITION BY RANGE (published_date);
  -- CREATE TABLE document_chunks_2026_q1 PARTITION OF document_chunks FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
  -- CREATE TABLE document_chunks_2026_q2 PARTITION OF document_chunks FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
  -- CREATE TABLE document_chunks_2026_q3 PARTITION OF document_chunks FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
  -- CREATE TABLE document_chunks_2026_q4 PARTITION OF document_chunks FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');
  -- CREATE INDEX ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);
  Local SQLite WAL keeps non-partitioned table with TEXT JSON embedding (commented alternative ok).

Fallback chain: pgvector ivfflat cosine 1536 -> LanceDB (VectorStoreManager) -> FTS5.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Optional

from reality_engine.db.database import db_manager
from reality_engine.db.vector_store import VectorStoreManager

logger = logging.getLogger("reality_engine.hybrid_search")


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
    def __init__(self, db=None, vector_store: Optional[VectorStoreManager] = None, pg_dsn: Optional[str] = None):
        self.db = db or db_manager
        self.vector_store = vector_store or VectorStoreManager()
        # PG DSN: env DATABASE_URL / PG_DSN / POSTGRES_DSN ; None => skip pgvector, use fallbacks
        self.pg_dsn = pg_dsn or os.environ.get("DATABASE_URL") or os.environ.get("PG_DSN") or os.environ.get("POSTGRES_DSN")

    # ------------------------------------------------------------------
    # PG vector embedding helper (1536 dim) - graceful hash fallback
    # ------------------------------------------------------------------
    def _embed_1536(self, text: str) -> list[float]:
        # Try sentence_transformers with 1536 model if available
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            # Cache model per dimension
            cache_attr = "_st_model_1536"
            if not hasattr(self, cache_attr):
                # Prefer bge-m3 which can be 1024; fallback to hash if not 1536
                # Try text-embedding-3-large equivalent via local hash if model dim !=1536
                model = SentenceTransformer("BAAI/bge-m3", device="cpu")
                dim = model.get_sentence_embedding_dimension()
                if dim == 1536:
                    setattr(self, cache_attr, model)
                else:
                    # Keep but pad/truncate to 1536
                    setattr(self, cache_attr, model)
                    setattr(self, "_st_dim", dim)
            model = getattr(self, cache_attr)
            vec = model.encode([text], normalize_embeddings=True)[0].tolist()
            # Pad/truncate to 1536 for pgvector compatibility
            if len(vec) != 1536:
                if len(vec) < 1536:
                    vec = vec + [0.0] * (1536 - len(vec))
                else:
                    vec = vec[:1536]
                # Renormalize
                norm = math.sqrt(sum(x * x for x in vec)) or 1.0
                vec = [x / norm for x in vec]
            return vec
        except (ImportError, Exception) as exc:
            # Hash fallback 1536 (consistent with VectorStoreManager but 1536 dim)
            logger.debug("1536 embed fallback hash (%s)", exc)
            dim = 1536
            vector = [0.0] * dim
            for token in re.findall(r"\w+", text.lower()):
                idx = int(hashlib.sha256(token.encode()).hexdigest(), 16) % dim
                vector[idx] += 1.0
            norm = math.sqrt(sum(x * x for x in vector)) or 1.0
            return [x / norm for x in vector]

    def _pgvector_search(self, query: str, symbol: Optional[str], top_k: int) -> Optional[list[dict[str, Any]]]:
        """Try PG ivfflat cosine 1536. Returns None if PG unavailable/fails so caller falls back."""
        if not self.pg_dsn:
            return None
        # Quick check: psycopg2/pgvector availability
        try:
            import psycopg2  # type: ignore
            import psycopg2.extras  # type: ignore
        except ImportError:
            logger.debug("pgvector search skipped: psycopg2 not installed")
            return None
        try:
            qvec = self._embed_1536(query)
            # Use pgvector cosine operator <=> (distance) ; we convert to similarity as 1 - distance
            # Partition pruning: if query has date hint we could add published_date filter, but generic search uses no partition filter
            sql = """
                SELECT chunk_id::text AS id,
                       content AS text,
                       COALESCE(symbol,'') AS symbol,
                       COALESCE(published_date::text,'') AS document_date,
                       1 - (embedding <=> %s::vector) AS vector_score
                FROM document_chunks
                WHERE embedding IS NOT NULL
            """
            params: list[Any] = [qvec]
            if symbol:
                # Symbol stored in document_chunks.symbol or via doc join; we filter on symbol column for partitioned table
                sql += " AND symbol = %s"
                params.append(symbol)
            sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
            params.extend([qvec, top_k * 3])

            # PG connection with short timeout
            conn = psycopg2.connect(self.pg_dsn, connect_timeout=3)
            try:
                conn.set_session(readonly=True, autocommit=True)
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
                    # Convert RealDictRow to plain dict
                    out = [dict(r) for r in rows]
                    logger.info("pgvector ivfflat cosine 1536 hit %d rows for query '%s'", len(out), query[:40])
                    return out
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("pgvector search fallback (will use LanceDB): %s", exc)
            return None

    def _ft5_lexical(self, query: str, symbol: Optional[str], top_k: int) -> list[Any]:
        try:
            with self.db.session() as conn:
                sql = "SELECT rowid, chunk_id, symbol, document_date, document_text, bm25(intelligence_fts) AS rank FROM intelligence_fts WHERE intelligence_fts MATCH ?"
                params: list[Any] = [query]
                if symbol:
                    sql += " AND symbol = ?"
                    params.append(symbol)
                rows = conn.execute(sql + " ORDER BY rank LIMIT ?", (*params, top_k * 3)).fetchall()
                return rows
        except Exception as exc:
            logger.debug("FTS5 lexical note: %s", exc)
            return []

    def search(self, query: str, symbol: Optional[str] = None, top_k: int = 10) -> list[HybridHit]:
        lexical = self._ft5_lexical(query, symbol, top_k)

        # Dense: try pgvector first, then LanceDB
        dense: list[dict[str, Any]] = []
        pg_res = self._pgvector_search(query, symbol, top_k)
        if pg_res is not None:
            dense = pg_res
            logger.info("Hybrid search dense tier: pgvector ivfflat (1536)")
        else:
            try:
                dense = self.vector_store.search(query, symbol, top_k * 3)
                if dense:
                    logger.info("Hybrid search dense tier: LanceDB fallback (%d hits)", len(dense))
                else:
                    logger.info("Hybrid search dense tier: LanceDB fallback (0 hits) -> FTS5 only")
            except Exception as exc:
                logger.debug("LanceDB search note: %s", exc)
                dense = []

        # If both dense and lexical empty, return empty
        merged: dict[str, HybridHit] = {}
        for rank, row in enumerate(lexical, 1):
            try:
                key = row["chunk_id"] or str(row["rowid"])
                text = row["document_text"]
                sym = row["symbol"]
                doc_date = row["document_date"]
            except Exception:
                # row may be dict-like
                key = row.get("chunk_id") or str(row.get("rowid", rank))
                text = row.get("document_text", "")
                sym = row.get("symbol", "")
                doc_date = row.get("document_date", "")
            merged[key] = HybridHit(key, text, sym, f"{sym} {doc_date}", 1 / (60 + rank), 1 / (60 + rank), 0.0)
        for rank, row in enumerate(dense, 1):
            key = str(row.get("id", row.get("chunk_id", f"dense_{rank}")))
            hit = merged.setdefault(key, HybridHit(key, row.get("text", row.get("content", "")), row.get("symbol", ""), f"{row.get('symbol', '')} {row.get('document_date', '')}"))
            # vector_score already cosine similarity 0-1 (pgvector) or hash cosine (LanceDB)
            hit.vector_score = float(row.get("vector_score", 0.0) or 0.0)
            hit.score += 1 / (60 + rank)
        # If no lexical at all but dense exists, ensure sorting by vector_score weighted RRF already done
        # FTS5 is final fallback guaranteed even when embeddings unavailable per AGENTS.md:5
        return sorted(merged.values(), key=lambda h: h.score, reverse=True)[:top_k]
