"""Digital/scanned document extraction and financial transcript chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


@dataclass
class DocumentChunk:
    id: str
    text: str
    symbol: str = ""
    isin: str = ""
    fiscal_year: str = ""
    doc_type: str = "DOCUMENT"
    document_date: str = ""
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    source_path: str = ""
    industry_id: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConcallSectionPruner:
    """Remove low-value transcript boilerplate while retaining discussion sections."""

    _start = re.compile(r"\b(management\s+(?:remarks|commentary)|question\s*(?:and|&)\s*answer|analyst\s*q\s*&?\s*a)\b", re.I)
    _noise = re.compile(r"^\s*(?:safe harbor|forward[- ]looking statements?|operator:|good morning everyone|welcome to the conference call|thank you for joining)\b.*$", re.I)

    def prune(self, text: str) -> str:
        text = re.sub(r"\r\n?", "\n", text or "")
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line and not self._noise.fullmatch(line)]
        cleaned = "\n".join(lines)
        # Drop opening boilerplate only up to the first useful transcript heading.
        match = self._start.search(cleaned)
        if match and match.start() > 0:
            cleaned = cleaned[match.start():]
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


class DocumentParser:
    def __init__(self, ocr_engine: Optional[Callable[[Any], dict[str, Any]]] = None, chunk_tokens: int = 512, overlap_tokens: int = 64):
        self.ocr_engine = ocr_engine
        self.chunk_tokens = chunk_tokens
        self.overlap_tokens = overlap_tokens
        self.pruner = ConcallSectionPruner()

    @staticmethod
    def _metadata_header(metadata: dict[str, Any]) -> str:
        return "[Metadata: Symbol: {symbol} | FY: {fy} | Doc: {doc} | Date: {date}]".format(
            symbol=metadata.get("symbol", ""), fy=metadata.get("fiscal_year", metadata.get("fy", "")),
            doc=metadata.get("doc_type", metadata.get("doc", "DOCUMENT")), date=metadata.get("document_date", metadata.get("date", "")),
        )

    def chunk_text(self, text: str, metadata: Optional[dict[str, Any]] = None, source_path: str = "") -> list[DocumentChunk]:
        metadata = metadata or {}
        words = re.findall(r"\S+", self.pruner.prune(text))
        if not words:
            return []
        step = max(1, self.chunk_tokens - self.overlap_tokens)
        header = self._metadata_header(metadata)
        chunks = []
        for start in range(0, len(words), step):
            body = " ".join(words[start:start + self.chunk_tokens])
            if not body:
                break
            chunk_id = f"{metadata.get('symbol', 'DOCUMENT')}-{start // step}"
            chunks.append(DocumentChunk(chunk_id, f"{header}\n{body}", source_path=source_path, **{
                k: metadata.get(k, "") for k in ("symbol", "isin", "fiscal_year", "doc_type", "document_date")
            }, industry_id=metadata.get("industry_id")))
            if start + self.chunk_tokens >= len(words):
                break
        return chunks

    def parse_text(self, text: str, metadata: Optional[dict[str, Any]] = None, source_path: str = "") -> list[DocumentChunk]:
        return self.chunk_text(text, metadata, source_path)

    def extract_pdf(self, path: str | Path, metadata: Optional[dict[str, Any]] = None) -> list[DocumentChunk]:
        path = Path(path)
        metadata = dict(metadata or {})
        pages: list[str] = []
        try:
            import fitz  # type: ignore
            with fitz.open(path) as pdf:
                pages = [page.get_text("text") for page in pdf]
                if sum(len(p) for p in pages) < 300 and self.ocr_engine:
                    pages = [self.ocr_engine(page.get_pixmap(matrix=fitz.Matrix(2, 2))) .get("raw_text", "") for page in pdf]
        except ImportError:
            try:
                import pdfplumber  # type: ignore
                with pdfplumber.open(path) as pdf:
                    pages = [(page.extract_text() or "") for page in pdf.pages]
            except ImportError as exc:
                raise RuntimeError("Install PyMuPDF or pdfplumber to parse PDFs") from exc
        metadata.setdefault("doc_type", "PDF")
        return self.chunk_text("\n\n".join(pages), metadata, str(path))

    def parse(self, path: str | Path, metadata: Optional[dict[str, Any]] = None) -> list[DocumentChunk]:
        path = Path(path)
        if path.suffix.lower() == ".pdf":
            return self.extract_pdf(path, metadata)
        return self.parse_text(path.read_text(encoding="utf-8", errors="replace"), metadata, str(path))
