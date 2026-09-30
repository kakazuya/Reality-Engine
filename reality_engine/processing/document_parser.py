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
    # Text handed to the embedder. ``text`` keeps the metadata header for FTS and
    # provenance; the header is machine-generated and identical on nearly every
    # chunk, so embedding it costs ~4% of every forward pass and adds a
    # corpus-common direction that has to be removed downstream.
    embed_text: str = ""
    # Statutory / financial-statement material (balance sheets, restated
    # accounts, audit notes). Kept in the lexical index — searchable — but not
    # worth a dense vector: the numbers themselves live in the structured tables.
    is_boilerplate: bool = False

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


# ---------------------------------------------------------------------------
# PUA-poison text-layer detector (Slice E, pre-registered threshold).
#
# Proven cause: a PDF whose embedded text layer is ~314k chars of U+F0xx PUA
# (299,549 PUA, 0 ASCII) from an unembedded custom font. prune() passes it
# through; the BPE tokenizer collapses it to 2 ids with empty decode -> 0
# chunks, surfacing as a generic ``no_chunks`` retry loop. PUA codepoints
# U+E000-U+F8FF are never legitimate body text in this corpus, so a layer
# dominated by them is a poison signal, not content.
# ---------------------------------------------------------------------------

#: Pre-registered PUA-poison threshold: fraction of chars in U+E000-U+F8FF
#: at or above which the text layer is distrusted in favour of OCR.
PUA_POISON_THRESHOLD = 0.5


def pua_rate(text: str) -> float:
    """Return the fraction of chars in the Unicode Private Use Area."""
    if not text:
        return 0.0
    return sum(1 for ch in text if 0xE000 <= ord(ch) <= 0xF8FF) / len(text)


def is_pua_poisoned(text: str, threshold: float = PUA_POISON_THRESHOLD) -> bool:
    """True when the PUA fraction meets/exceeds the poison threshold."""
    if not text:
        return False
    return pua_rate(text) >= threshold


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

    # Statutory / financial-statement vocabulary. A chunk matching this is
    # lexically useful (someone may search "restated consolidated financial
    # statements") but semantically inert — the figures are read from the
    # structured financial tables, not from prose. Measured at 33.5% of all
    # corpus chunks (35% of offer documents).
    _BOILER_SECTION = re.compile(
        r"(restated\s+(consolidated\s+)?(financial|statement)|statement of assets and liabilities|"
        r"cash flow statement|cashflow statement|notes to the (restated )?(financial|consolidated)|"
        r"balance sheet as at|statement of profit and loss|related party transactions|"
        r"significant accounting policies|auditor'?s? (report|opinion)|"
        r"definitions and abbreviations|capital structure of the company|"
        r"statement of possible (special )?tax benefits|offer for sale|bid lot|price band|"
        r"book running lead manager|registrar to the offer)",
        re.I,
    )

    @staticmethod
    def _bpe_tokenize(text: str) -> Optional[list]:
        """Tokenise with the same tokenizer the embedder uses, when available.

        The chunker historically counted WORDS while the ONNX embedder truncates
        at 512 BPE tokens, so a 512-word chunk (~730 tokens) stored 30% more text
        than it ever embedded — text that was FTS-searchable but invisible to
        vector retrieval. Chunking in the model's own units removes that blind
        spot. Returns None when the tokenizer is unavailable (word fallback).
        """
        try:
            from reality_engine.ingestion.onnx_embedder import onnx_embedder
            onnx_embedder._ensure()
            tok = onnx_embedder._tokenizer
            if tok is None:
                return None
            return tok.encode(text).ids
        except Exception:  # noqa: BLE001
            return None

    def chunk_text(self, text: str, metadata: Optional[dict[str, Any]] = None, source_path: str = "") -> list[DocumentChunk]:
        metadata = metadata or {}
        cleaned = re.sub(r"\s+", " ", self.pruner.prune(text) or "").strip()
        if not cleaned:
            return []
        words = cleaned.split(" ")
        header = self._metadata_header(metadata)
        chunk_meta = {k: metadata.get(k, "") for k in ("symbol", "isin", "fiscal_year", "doc_type", "document_date")}

        ids = self._bpe_tokenize(cleaned)
        if ids:
            # Decode per window so stored text and embedded text are identical.
            from reality_engine.ingestion.onnx_embedder import onnx_embedder
            tok = onnx_embedder._tokenizer
            step = max(1, self.chunk_tokens - self.overlap_tokens)
            spans = [(s, min(s + self.chunk_tokens, len(ids))) for s in range(0, len(ids), step)]
        else:
            step = max(1, self.chunk_tokens - self.overlap_tokens)
            spans = [(s, min(s + self.chunk_tokens, len(words))) for s in range(0, len(words), step)]

        chunks: list[DocumentChunk] = []
        for idx, (start, end) in enumerate(spans):
            if ids:
                body = tok.decode(ids[start:end]).strip()
            else:
                body = " ".join(words[start:end]).strip()
            if not body:
                continue
            chunks.append(DocumentChunk(
                id=f"{metadata.get('symbol', 'DOCUMENT')}-{idx}",
                text=f"{header}\n{body}",
                embed_text=body,
                is_boilerplate=bool(self._BOILER_SECTION.search(body)),
                source_path=source_path,
                **chunk_meta,
                industry_id=metadata.get("industry_id"),
            ))
            if end >= (len(ids) if ids else len(words)):
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

# ---------------------------------------------------------------------------
# Fiscal-period extraction (findings §11, FYAudit 5k-sample spec).
#
# BODY-ONLY: callers MUST pass body text (via chunk_body) — never raw content.
# Every stored chunk carries a machine-generated header containing a literal
# ``FY:`` (``[Metadata: Symbol: … | FY: … | …]``), empty 99.94% of the time, so
# a naive content regex is 100% noise. Patterns below run on the body only.
#
# Priority: P1 Q-FY > P2 FY-range > P3/P4 FY-short/year > P5 anchored YY-range
# > P6 quarter-end date (corroboration only, never overrides P1–P5 on the same
# chunk). Tie-breaks: specificity > rightmost match > multi-conflict → NULL.
# Confidence: 1.0 P1/P7, 0.9 P2/P4, 0.7 P3-anchored (else 0.5, still stored),
# 0.5 P5, 0.3 P6, 0.2 MULTI → NULL, 0.0 NONE. Backtest scope: confidence >= 0.5.
# ---------------------------------------------------------------------------

_METADATA_STRIP = re.compile(r"^\s*\[Metadata:.*?\]\s*")

_P1_QFY = re.compile(r"\bQ\s*([1-4])\s*FY\s*(\d{2}|\d{4})(?:\s*[-–]\s*(\d{2}|\d{4}))?\b", re.IGNORECASE)
_P2_FY_RANGE = re.compile(r"\bFY\s*(20\d{2})\s*[-–]\s*(\d{2}|\d{4})\b", re.IGNORECASE)
_P3_FY_SHORT = re.compile(r"\bFY\s*(\d{2})\b", re.IGNORECASE)
_P4_FY_YEAR = re.compile(r"\bFY\s*(20\d{2})\b", re.IGNORECASE)
_P5_YY_RANGE = re.compile(r"\b(20\d{2})\s*[-–/]\s*(\d{2})\b", re.IGNORECASE)
# Quarter-end date, day-first ("30 June 2024") or month-first ("December 31,
# 2023"); months restricted to Indian quarter-ends.
_P6_QTR_DATE = re.compile(
    r"\bquarter\s+ended\s+(?:(\d{1,2})(?:st|nd|rd|th)?\s+)?"
    r"(June|September|December|March)\s*,?\s*"
    r"(?:(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*)?(20\d{2})\b",
    re.IGNORECASE,
)
_P7_HFY = re.compile(r"\bH\s*([12])\s*FY\s*(\d{2}|\d{4})\b", re.IGNORECASE)
_ANCHOR = re.compile(
    r"\b(?:FY|fiscal|financial\s+year|quarter|Q[1-4]|H[12]|annual\s+report|results)\b",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+")
_ANCHOR_WINDOW = 80

# Indian FY mapping for quarter-end months: (quarter, year offset to the March
# that ends the fiscal year). June 2024 → Q1 of FY ending Mar 2025 → Q1FY25.
_P6_QTR: dict[str, tuple[str, int]] = {
    "june": ("Q1", 1),
    "september": ("Q2", 1),
    "december": ("Q3", 1),
    "march": ("Q4", 0),
}


def chunk_body(content: str) -> str:
    """Return the body of a stored chunk: content after the first newline.

    The first line is the machine-generated ``[Metadata: …]`` header; a stray
    leading header (no newline) is stripped as well. All fiscal patterns run
    on this return value, never on raw ``content``.
    """
    text = content or ""
    if "\n" in text:
        text = text.split("\n", 1)[1]
    return _METADATA_STRIP.sub("", text).strip()


def _fy(tok: str) -> str:
    """Normalise a 2- or 4-digit year token to ``FY{YY}`` (range → end year)."""
    return f"FY{int(tok[-2:]):02d}"


def extract_fiscal_period(body: str) -> tuple[Optional[str], float, str]:
    """Label body text with (fiscal_period, confidence, source).

    ``body`` MUST already be header-stripped (see chunk_body). Returns
    ``(None, 0.2, "MULTI")`` on same-tier conflicting years, ``(None, 0.0,
    "NONE")`` when nothing body-genuine fires. Sources: QFY | FY_RANGE |
    FY_SHORT | FY_YEAR | YY_RANGE | QTR_DATE | H_FY | MULTI | NONE.
    """
    text = body or ""
    if not text.strip():
        return (None, 0.0, "NONE")
    url_spans = [(m.start(), m.end()) for m in _URL.finditer(text)]

    def _in_url(start: int) -> bool:
        return any(s <= start < e for s, e in url_spans)

    def _anchored(start: int, end: int) -> bool:
        before = text[max(0, start - _ANCHOR_WINDOW):start]
        after = text[end:end + _ANCHOR_WINDOW]
        return _ANCHOR.search(before) is not None or _ANCHOR.search(after) is not None

    # Tier 0: P1 quarter + P7 half-year (P1-level specificity).
    t0: list[tuple[int, str, float, str]] = []
    for m in _P1_QFY.finditer(text):
        yy_tok = m.group(3) if m.group(3) else m.group(2)
        t0.append((m.start(), f"Q{int(m.group(1))}{_fy(yy_tok)}", 1.0, "QFY"))
    for m in _P7_HFY.finditer(text):
        t0.append((m.start(), f"H{int(m.group(1))}{_fy(m.group(2))}", 1.0, "H_FY"))
    # Tier 1: P2 FY range.
    t1 = [(m.start(), _fy(m.group(2)), 0.9, "FY_RANGE") for m in _P2_FY_RANGE.finditer(text)]
    # Tier 2: P3 FY short + P4 FY year (URL-guarded).
    t2: list[tuple[int, str, float, str]] = []
    for m in _P3_FY_SHORT.finditer(text):
        if _in_url(m.start()):
            continue
        conf = 0.7 if _anchored(m.start(), m.end()) else 0.5
        t2.append((m.start(), _fy(m.group(1)), conf, "FY_SHORT"))
    for m in _P4_FY_YEAR.finditer(text):
        if _in_url(m.start()):
            continue
        t2.append((m.start(), _fy(m.group(1)), 0.9, "FY_YEAR"))
    # Tier 3: P5 YY range, anchored only (URL-guarded).
    t3: list[tuple[int, str, float, str]] = []
    for m in _P5_YY_RANGE.finditer(text):
        if _in_url(m.start()):
            continue
        if not _anchored(m.start(), m.end()):
            continue
        t3.append((m.start(), _fy(m.group(2)), 0.5, "YY_RANGE"))
    # Tier 4: P6 quarter-end date (corroboration only — evaluated last so it
    # never overrides P1–P5 on the same chunk).
    t4: list[tuple[int, str, float, str]] = []
    for m in _P6_QTR_DATE.finditer(text):
        quarter, offset = _P6_QTR[m.group(2).lower()]
        year = int(m.group(4)) + offset
        t4.append((m.start(), f"{quarter}FY{year % 100:02d}", 0.3, "QTR_DATE"))

    for tier in (t0, t1, t2, t3, t4):
        if not tier:
            continue
        # Same-tier matches sharing one year (all values end FY{YY}):
        # rightmost wins (results sections trail cover). Conflicting years
        # (e.g. P2 FY24 + P2 FY25) have no winner → NULL + MULTI + 0.2.
        if len({value[-2:] for _, value, _, _ in tier}) > 1:
            return (None, 0.2, "MULTI")
        start, value, conf, source = max(tier, key=lambda t: t[0])
        return (value, conf, source)
    return (None, 0.0, "NONE")
