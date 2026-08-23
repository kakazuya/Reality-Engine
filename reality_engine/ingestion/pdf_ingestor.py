"""
Layout-aware PDF ingestor for Fundamental Reality Engine.
Marker / PyMuPDF -> raw_documents + document_chunks (VECTOR 1536) + FTS5 + LanceDB.

PG primary: document_chunks with VECTOR(1536) ivfflat cosine + partitioned alternative.
SQLite fallback: same tables created as TEXT embedding JSON, keeps timestamp_start_sec for
audio/video diarization compatibility.

Graceful fallbacks per AGENTS.md:5:
  Marker layout -> PyMuPDF text -> RapidOCR DirectML (RX 6700 XT) if GPU present.
  pgvector -> LanceDB -> FTS5 handled in search layer, not here.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from reality_engine.config import DATA_DIR
from reality_engine.db.database import db_manager
from reality_engine.db.vector_store import VectorStoreManager
from reality_engine.processing.document_parser import DocumentParser
from reality_engine.processing.ocr_engine import FinancialOCREngine

logger = logging.getLogger("reality_engine.pdf_ingestor")

# ---------------------------------------------------------------------------
# Optional Marker import (layout-aware). Falls back to PyMuPDF.
# Marker API varies; we guard all imports.
# ---------------------------------------------------------------------------
_MARKER_AVAILABLE = False
_marker_convert = None
try:
    # marker-pdf >=0.2 provides marker.convert.convert_single_pdf
    from marker.convert import convert_single_pdf  # type: ignore
    _marker_convert = convert_single_pdf
    _MARKER_AVAILABLE = True
except ImportError:
    try:
        from marker.converters.pdf import PdfConverter  # type: ignore
        from marker.models import create_model_dict  # type: ignore
        _marker_convert = PdfConverter  # placeholder
        _MARKER_AVAILABLE = True
    except ImportError:
        _MARKER_AVAILABLE = False

# PG partitioned DDL reference (commented alternative for local SQLite):
# -- CREATE TABLE document_chunks (
# --     chunk_id BIGSERIAL,
# --     doc_id INT NOT NULL REFERENCES raw_documents(doc_id) ON DELETE CASCADE,
# --     chunk_index INT NOT NULL,
# --     content TEXT NOT NULL,
# --     embedding VECTOR(1536),
# --     published_date DATE NOT NULL,
# --     timestamp_start_sec INT,
# --     timestamp_end_sec INT,
# --     sector_id INT,
# --     industry_id INT REFERENCES industries(industry_id),
# --     PRIMARY KEY (chunk_id, published_date)
# -- ) PARTITION BY RANGE (published_date);
# -- CREATE TABLE document_chunks_2026_q1 PARTITION OF document_chunks FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
# -- CREATE TABLE document_chunks_2026_q2 PARTITION OF document_chunks FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
# -- CREATE TABLE document_chunks_2026_q3 PARTITION OF document_chunks FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
# -- CREATE TABLE document_chunks_2026_q4 PARTITION OF document_chunks FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');
# -- CREATE INDEX ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);
# SQLite fallback keeps non-partitioned table with JSON embedding.


def _ensure_raw_tables(conn) -> None:
    """Create raw_documents + document_chunks for SQLite fallback if missing.
    PG cluster already has these via postgres_schema.sql; this is SQLite WAL only.
    """
    # raw_documents: mirror PG DDL with SQLite types
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_documents (
            doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source_type TEXT NOT NULL,
            published_date TEXT NOT NULL,
            fiscal_period TEXT,
            source_url TEXT,
            creator_or_ministry TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            sha256_hash TEXT UNIQUE,
            local_file_path TEXT,
            file_size_bytes INTEGER
        )
        """
    )
    # document_chunks: VECTOR 1536 in PG -> TEXT JSON in SQLite
    # published_date duplicated for PARTITION BY RANGE reference; nullable for SQLite
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_chunks (
            chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER REFERENCES raw_documents(doc_id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT,
            published_date TEXT,
            timestamp_start_sec INTEGER,
            timestamp_end_sec INTEGER,
            sector_id INTEGER,
            industry_id INTEGER,
            symbol TEXT,
            isin TEXT,
            UNIQUE(doc_id, chunk_index)
        )
        """
    )
    # Helpful index for hybrid search fallback
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_docchunks_doc ON document_chunks(doc_id, chunk_index)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rawdoc_hash ON raw_documents(sha256_hash)")
    except Exception:
        pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(blk)
    return h.hexdigest()


class PDFIngestor:
    """Layout-aware PDF ingestor: Marker/PyMuPDF -> chunks -> pgvector/FTS5."""

    def __init__(
        self,
        db=None,
        vector_store: Optional[VectorStoreManager] = None,
        ocr_engine: Optional[FinancialOCREngine] = None,
        chunk_tokens: int = 512,
        overlap_tokens: int = 64,
    ):
        self.db = db or db_manager
        self.vector_store = vector_store or VectorStoreManager()
        self.ocr = ocr_engine or FinancialOCREngine()
        self.parser = DocumentParser(ocr_engine=self.ocr.process_image if self.ocr else None, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens)
        # Ensure tables exist for SQLite fallback (idempotent)
        try:
            with self.db.session() as conn:
                _ensure_raw_tables(conn)
        except Exception as exc:
            logger.debug("ensure raw tables note: %s", exc)

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def _extract_with_marker(self, path: Path) -> Optional[str]:
        if not _MARKER_AVAILABLE or _marker_convert is None:
            return None
        try:
            # Try new marker-pdf API: convert_single_pdf(path, model_dict, ...)
            if _marker_convert.__name__ == "convert_single_pdf":
                # This API needs model_dict; we attempt lightweight call
                from marker.models import create_model_dict  # type: ignore
                model_dict = create_model_dict()
                result = _marker_convert(str(path), model_dict, max_pages=None)  # type: ignore
                # result is (markdown, metadata, images)
                if isinstance(result, tuple) and len(result) >= 1:
                    return str(result[0])
                return str(result)
            # Fallback class API
            from marker.models import create_model_dict  # type: ignore
            from marker.converters.pdf import PdfConverter  # type: ignore
            converter = PdfConverter(artifact_dict=create_model_dict())
            rendered = converter(str(path))
            return getattr(rendered, "markdown", str(rendered))
        except Exception as exc:
            logger.debug("Marker extraction fallback (%s): %s", path.name, exc)
            return None

    def _extract_with_pymupdf(self, path: Path) -> tuple[str, bool]:
        """Returns (text, is_scanned_heuristic). is_scanned if text length <300."""
        pages_text: List[str] = []
        is_scanned = False
        try:
            import fitz  # type: ignore
            with fitz.open(path) as doc:
                for page in doc:
                    try:
                        pages_text.append(page.get_text("text") or "")
                    except Exception:
                        pages_text.append("")
                full = "\n\n".join(pages_text)
                if len(full.strip()) < 300:
                    is_scanned = True
                    # If scanned and OCR available, attempt RapidOCR per page pixmap
                    if self.ocr and self.ocr.engine is not None:
                        ocr_pages = []
                        for page in doc:
                            try:
                                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                                # Save pixmap to temp for ocr_engine
                                # Use preprocess-less direct: write to PNG bytes
                                import tempfile
                                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                                    pix.save(tmp.name)
                                    res = self.ocr.process_image(tmp.name)
                                    ocr_pages.append(res.get("raw_text", ""))
                                    try:
                                        Path(tmp.name).unlink(missing_ok=True)
                                    except Exception:
                                        pass
                            except Exception as e:
                                logger.debug("OCR page fallback: %s", e)
                                ocr_pages.append("")
                        if any(ocr_pages):
                            return "\n\n".join(ocr_pages), True
                return full, is_scanned
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("PyMuPDF extraction note %s: %s", path.name, exc)
        # Fallback pdfplumber
        try:
            import pdfplumber  # type: ignore
            with pdfplumber.open(path) as pdf:
                pages_text = [(p.extract_text() or "") for p in pdf.pages]
            full = "\n\n".join(pages_text)
            return full, len(full.strip()) < 300
        except ImportError:
            raise RuntimeError("Install PyMuPDF (fitz) or pdfplumber to parse PDFs")
        except Exception as exc:
            logger.warning("pdfplumber fallback failed %s: %s", path.name, exc)
            return "", True

    def extract_text(self, path: str | Path) -> str:
        path = Path(path)
        # 1) Marker layout-aware if available
        marker_text = self._extract_with_marker(path)
        if marker_text and len(marker_text.strip()) > 200:
            logger.info("PDF extracted via Marker: %s (%d chars)", path.name, len(marker_text))
            return marker_text
        # 2) PyMuPDF + RapidOCR DirectML per AGENTS.md:5 (RX 6700 XT, no cloud)
        text, scanned = self._extract_with_pymupdf(path)
        if scanned and self.ocr and self.ocr.provider != "NONE":
            logger.info("PDF %s flagged scanned, used RapidOCR %s fallback", path.name, self.ocr.provider)
        else:
            logger.info("PDF extracted via PyMuPDF: %s (%d chars, scanned=%s)", path.name, len(text), scanned)
        return text

    # ------------------------------------------------------------------
    # Persistence: raw_documents + document_chunks (+ FTS5 + LanceDB)
    # ------------------------------------------------------------------
    def _insert_raw_document(
        self,
        conn,
        path: Path,
        title: Optional[str],
        source_type: str,
        published_date: str,
        fiscal_period: Optional[str],
        source_url: Optional[str],
        sha256_hash: str,
    ) -> int:
        # Use INSERT OR IGNORE for SQLite fallback (sha256 unique)
        conn.execute(
            """
            INSERT OR IGNORE INTO raw_documents
                (title, source_type, published_date, fiscal_period, source_url, creator_or_ministry, sha256_hash, local_file_path, file_size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title or path.stem,
                source_type,
                published_date,
                fiscal_period,
                source_url,
                None,
                sha256_hash,
                str(path),
                path.stat().st_size if path.exists() else None,
            ),
        )
        row = conn.execute("SELECT doc_id FROM raw_documents WHERE sha256_hash=?", (sha256_hash,)).fetchone()
        if row:
            return int(row[0] if isinstance(row, tuple) else row["doc_id"])
        # Fallback: last row id
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def ingest_pdf(
        self,
        path: str | Path,
        title: Optional[str] = None,
        source_type: str = "Investor_Presentation",
        published_date: Optional[str] = None,
        fiscal_period: Optional[str] = None,
        source_url: Optional[str] = None,
        symbol: Optional[str] = None,
        isin: Optional[str] = None,
        sector_id: Optional[int] = None,
        industry_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Ingest single PDF: extract -> chunk -> embed -> persist.
        Idempotent via sha256_hash; does NOT re-ingest if hash exists (preserves 40 filings).
        Returns {doc_id, chunks, status}.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        sha = _sha256(path)
        published_date = published_date or path.stat().st_mtime.__format__("%Y-%m-%d") if False else (published_date or "2026-08-14")
        # Normalize date: if not YYYY-MM-DD, keep as provided
        if published_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(published_date)):
            try:
                from datetime import datetime
                published_date = datetime.fromisoformat(str(published_date).replace("Z", "+00:00")).date().isoformat()
            except Exception:
                published_date = "2026-08-14"

        with self.db.session() as conn:
            _ensure_raw_tables(conn)
            # Skip if already ingested (preserve existing 40 filings + POLYPLEX PPT)
            existing = conn.execute("SELECT doc_id FROM raw_documents WHERE sha256_hash=?", (sha,)).fetchone()
            if existing:
                doc_id = int(existing[0] if isinstance(existing, tuple) else existing["doc_id"])
                cnt = conn.execute("SELECT COUNT(*) FROM document_chunks WHERE doc_id=?", (doc_id,)).fetchone()[0]
                fts_cnt = conn.execute("SELECT COUNT(*) FROM intelligence_fts WHERE chunk_id LIKE ?", (f"{doc_id}-%",)).fetchone()[0] if self._fts_exists(conn) else 0
                logger.info("PDF already ingested %s -> doc_id %d (%d chunks, %d fts)", path.name, doc_id, cnt, fts_cnt)
                return {"doc_id": doc_id, "chunks": int(cnt), "status": "skipped_duplicate", "sha256": sha}

        text = self.extract_text(path)
        if not text or len(text.strip()) < 10:
            logger.warning("PDF %s produced no text (scanned image only, OCR may have failed)", path.name)
            text = f"[No extractable text from {path.name}; OCR fallback returned empty]"

        # Chunk via DocumentParser (512 / 64)
        metadata = {
            "symbol": symbol or "",
            "isin": isin or "",
            "fiscal_year": fiscal_period or "",
            "doc_type": source_type,
            "document_date": published_date,
        }
        chunks = self.parser.chunk_text(text, metadata, str(path))
        if not chunks:
            logger.warning("No chunks produced for %s", path.name)
            return {"doc_id": None, "chunks": 0, "status": "no_chunks", "sha256": sha}

        # Persist
        with self.db.session() as conn:
            _ensure_raw_tables(conn)
            doc_id = self._insert_raw_document(conn, path, title, source_type, published_date, fiscal_period, source_url, sha)
            # Insert chunks with embedding JSON + FTS + LanceDB
            fts_records = []
            lancedb_records = []
            for idx, ch in enumerate(chunks):
                content = ch.text
                # Preserve timestamp_start_sec for compatibility (PDFs = NULL/0)
                # Embed via VectorStoreManager (hash fallback if no model)
                try:
                    vec = self.vector_store.embed(content)
                except Exception:
                    vec = []
                vec_json = json.dumps(vec) if vec else None
                # SQLite document_chunks
                # Use INSERT OR IGNORE for idempotency
                conn.execute(
                    """
                    INSERT OR IGNORE INTO document_chunks
                        (doc_id, chunk_index, content, embedding, published_date, timestamp_start_sec, timestamp_end_sec, sector_id, industry_id, symbol, isin)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (doc_id, idx, content, vec_json, published_date, None, None, sector_id, industry_id, symbol or "", isin or ""),
                )
                # Resolve chunk_id for FTS/Vectors
                row = conn.execute("SELECT chunk_id FROM document_chunks WHERE doc_id=? AND chunk_index=?", (doc_id, idx)).fetchone()
                chunk_id_str = str(row[0] if isinstance(row, tuple) else row["chunk_id"]) if row else f"{doc_id}-{idx}"
                fts_records.append({
                    "chunk_id": chunk_id_str,
                    "symbol": symbol or "",
                    "isin": isin or "",
                    "source_type": source_type,
                    "document_date": published_date,
                    "document_text": content,
                })
                lancedb_records.append({
                    "id": chunk_id_str,
                    "symbol": symbol or "",
                    "isin": isin or "",
                    "text": content,
                    "document_date": published_date,
                    "source_type": source_type,
                })
            # FTS5 insert (SQLite)
            if fts_records and self._fts_exists(conn):
                try:
                    conn.executemany(
                        "INSERT INTO intelligence_fts(chunk_id, symbol, isin, source_type, document_date, document_text) VALUES (:chunk_id, :symbol, :isin, :source_type, :document_date, :document_text)",
                        fts_records,
                    )
                except Exception as exc:
                    logger.warning("FTS insert note %s: %s", path.name, exc)
            # LanceDB / JSON fallback
            try:
                self.vector_store.add_chunks(lancedb_records)
            except Exception as exc:
                logger.warning("Vector store add note %s: %s", path.name, exc)

            # Also register in corporate_documents for backward compat (preserve existing 4003)
            # Insert minimal corporate_documents entry if not exists (title+doc_date uniqueness not enforced)
            try:
                conn.execute(
                    """
                    INSERT INTO corporate_documents (isin, symbol, doc_type, title, doc_date, source_url, local_file_path, file_size_bytes, sha256_hash, is_processed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        isin or symbol or "UNKNOWN",
                        symbol or "UNKNOWN",
                        source_type,
                        title or path.stem,
                        published_date,
                        source_url,
                        str(path),
                        path.stat().st_size if path.exists() else None,
                        sha,
                    ),
                )
            except Exception as exc:
                logger.debug("corporate_documents compat insert note: %s", exc)

        logger.info("PDF ingested %s -> doc_id %d (%d chunks) via %s", path.name, doc_id, len(chunks), "Marker" if _MARKER_AVAILABLE else "PyMuPDF+RapidOCR" if self.ocr and self.ocr.provider != "NONE" else "PyMuPDF")
        return {"doc_id": doc_id, "chunks": len(chunks), "status": "ingested", "sha256": sha, "provider": self.ocr.provider if self.ocr else "NONE"}

    def _fts_exists(self, conn) -> bool:
        try:
            conn.execute("SELECT 1 FROM intelligence_fts LIMIT 1")
            return True
        except Exception:
            return False

    def ingest_directory(
        self,
        directory: str | Path,
        pattern: str = "*.pdf",
        **kwargs,
    ) -> List[Dict[str, Any]]:
        directory = Path(directory)
        results = []
        for pdf in directory.glob(pattern):
            try:
                results.append(self.ingest_pdf(pdf, **kwargs))
            except Exception as exc:
                logger.warning("Directory ingest skip %s: %s", pdf.name, exc)
                results.append({"path": str(pdf), "status": "failed", "error": str(exc)})
        return results


# Singleton for convenience
pdf_ingestor = PDFIngestor()
