"""Local-first drop-in inbox ingestion pipeline."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Optional

from reality_engine.config import ENGINE_DIR
from reality_engine.db.database import db_manager
from reality_engine.db.vector_store import VectorStoreManager
from reality_engine.processing.document_parser import DocumentParser
from reality_engine.processing.ocr_engine import FinancialOCREngine


class InboxRunner:
    def __init__(self, inbox_dir: str | Path | None = None, db=None, vector_store: Optional[VectorStoreManager] = None):
        self.inbox = Path(inbox_dir or ENGINE_DIR / "data" / "inbox")
        self.db = db or db_manager
        self.vector_store = vector_store or VectorStoreManager()
        self.parser = DocumentParser()
        self.ocr = FinancialOCREngine()
        for name in ("images", "pdfs", "text", "processed", "failed"):
            (self.inbox / name).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _index(self, chunks: list[Any], file_type: str) -> None:
        records = [chunk.to_dict() for chunk in chunks]
        self.vector_store.add_chunks(records)
        with self.db.session() as conn:
            conn.executemany("INSERT INTO intelligence_fts(chunk_id, symbol, isin, source_type, document_date, document_text) VALUES (?, ?, ?, ?, ?, ?)", [
                (c["id"], c.get("symbol", ""), c.get("isin", ""), file_type, c.get("document_date", ""), c["text"]) for c in records
            ])

    def process_file(self, path: str | Path) -> dict[str, Any]:
        path = Path(path)
        file_hash = self._hash(path)
        with self.db.session() as conn:
            if conn.execute("SELECT 1 FROM inbox_ingestion_manifest WHERE file_hash = ?", (file_hash,)).fetchone():
                return {"status": "skipped", "path": str(path), "hash": file_hash}
        try:
            suffix = path.suffix.lower()
            metadata = {"doc_type": suffix.lstrip(".").upper(), "document_date": ""}
            if suffix == ".pdf":
                chunks = self.parser.parse(path, metadata)
            elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                result = self.ocr.process_image(path)
                chunks = self.parser.parse_text(result["raw_text"], metadata, str(path))
            else:
                chunks = self.parser.parse(path, metadata)
            self._index(chunks, suffix.lstrip(".").upper())
            destination = self.inbox / "processed" / path.name
            shutil.move(str(path), str(destination))
            with self.db.session() as conn:
                conn.execute(
                    "INSERT INTO inbox_ingestion_manifest(file_hash, original_filename, file_type, detected_entity_type, summary, processed_file_path) VALUES (?, ?, ?, ?, ?, ?)",
                    (file_hash, path.name, suffix.lstrip(".").upper(), "IMAGE_SCREENSHOT" if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"} else "DOCUMENT", f"Indexed {len(chunks)} chunks", str(destination))
                )
            return {"status": "processed", "path": str(destination), "chunks": len(chunks), "hash": file_hash}
        except Exception as exc:
            failed = self.inbox / "failed" / path.name
            if path.exists():
                shutil.move(str(path), str(failed))
            return {"status": "failed", "path": str(failed), "error": str(exc), "hash": file_hash}

    def run(self) -> list[dict[str, Any]]:
        files = [p for folder in ("images", "pdfs", "text") for p in (self.inbox / folder).iterdir() if p.is_file()]
        return [self.process_file(path) for path in files]
