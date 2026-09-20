"""News infographic capture — RSS media -> download -> OCR -> FTS chunk + artifact row.

The RSS *text* of a Tier-1 news item loses the layer that actually carries the
numbers: the published chart / infographic (``media:content``,
``media:thumbnail``, ``enclosure``). This module captures that layer.

Contract (frozen — coordinated with the news ingest + retention slices):

* input records are the ``news_feed_client`` records: the 9 ``raw_documents``
  contract keys plus the ``text`` and ``symbols`` extras, and a ``media_url``
  pointing at the publisher's own CDN image;
* the image is downloaded to ``config.DATA_DIR/news_images/YYYY-MM-DD/``;
* OCR text (``FinancialOCREngine``) is written as an ``intelligence_fts`` chunk
  with ``chunk_id = f"{source_type}:{doc_id}:img"`` — a separate shape from the
  article chunk ``f"{source_type}:{doc_id}:0"``, so both coexist;
* one row per stored image lands in ``news_visual_artifacts`` (owned by this
  module via :func:`ensure_schema`; nothing else in the schema is touched).

Fail-closed everywhere: no network at import, no engine construction at import,
never raises, no writes for a miss.

Two signal gates matter in production: livemint infographics OCR to ~200 chars
of real index/level data, whereas an outlet whose ``media:content`` points at a
wordmark OCRs to ``"BS"`` (2 chars). Anything under :data:`MIN_OCR_CHARS` (or
confidence 0) is treated as a logo, not an infographic: no chunk, no artifact,
downloaded file removed (:data:`skipped_low_signal`).

A third gate is a within-batch dedupe: Business Standard emits the *same*
generic asset for most of its items, so an asset URL is downloaded + OCR'd once
per call and repeats are counted under ``skipped_duplicate_media``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from reality_engine.config import DATA_DIR, DEFAULT_HEADERS

logger = logging.getLogger("reality_engine.processing.news_vision")

try:
    from curl_cffi import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = False

import urllib3

urllib3.disable_warnings()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Subdirectory of ``config.DATA_DIR`` holding captured news images.
IMAGE_DIR_NAME = "news_images"

#: Hard cap on a downloaded image payload (payload + declared Content-Length).
MAX_IMAGE_BYTES = 8 * 1024 * 1024

#: An OCR result shorter than this is a logo/wordmark or scan noise, not an
#: infographic. Calibrated on 27 real captures: 20 chars admitted junk like
#: "555 15.067- 1.23" and "lenskart 00 lenskart"; 60 keeps every genuine chart
#: (shortest real one was 67 chars: "NIFTY 50 DALAL STREET Losses Uncertainty").
MIN_OCR_CHARS = 60

#: Cap on the composed ``intelligence_fts.document_text`` (prefix included).
MAX_OCR_TEXT = 3000

#: Chunk suffix separating the infographic chunk from the article chunk (``:0``).
CHUNK_SUFFIX = "img"

#: Prefix marking a chunk as OCR output rather than article prose.
CHUNK_PREFIX = "[infographic] "

DOWNLOAD_TIMEOUT = 20
_READ_CHUNK_BYTES = 65536

_IMAGE_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".tif", ".tiff",
)

_CONTENT_TYPE_SUFFIX: Dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/x-png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}

#: Content types that are not images but are commonly served for image bytes by
#: CDNs; these are accepted only when the payload magic confirms an image.
_OPAQUE_CONTENT_TYPES = ("application/octet-stream", "binary/octet-stream")

#: Magic prefixes -> content type (used when the server declares no type).
_MAGIC: Tuple[Tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)

_WS_RE = re.compile(r"\s+")

_EMPTY_OCR: Dict[str, Any] = {"text": "", "confidence": 0.0}

# ---------------------------------------------------------------------------
# Session (repo NSE pattern: curl_cffi impersonate chrome120, verify=False,
# plain requests fallback). Lazy: no network at import.
# ---------------------------------------------------------------------------

_session = None


def _get_session():
    global _session
    if _session is None:
        if _HAS_CURL_CFFI:
            try:
                _session = _curl_requests.Session(impersonate="chrome120", verify=False)  # type: ignore[call-arg]
            except TypeError:
                _session = _curl_requests.Session(verify=False)  # type: ignore
        else:
            _session = _curl_requests.Session()
            try:
                _session.verify = False  # type: ignore[attr-defined]
            except Exception:
                pass
    return _session


def _origin(url: str) -> str:
    """``https://host/path`` -> ``https://host/`` (Referer anti-hotlink pass)."""
    try:
        parts = urlsplit(str(url or ""))
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}/"
    except Exception:
        pass
    return ""


def _image_headers(url: str) -> Dict[str, str]:
    headers = {
        "User-Agent": DEFAULT_HEADERS.get("User-Agent", ""),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": DEFAULT_HEADERS.get("Accept-Language", "en-US,en;q=0.9"),
    }
    referer = _origin(url)
    if referer:
        headers["Referer"] = referer
    return headers


# ---------------------------------------------------------------------------
# Payload plumbing (always fail-closed: None / 0, never raises)
# ---------------------------------------------------------------------------

def _header(source: Any, name: str) -> str:
    """Case-insensitive header lookup on a dict-like or response-like object."""
    try:
        headers = getattr(source, "headers", source)
        if headers is None:
            return ""
        getter = getattr(headers, "get", None)
        if callable(getter):
            value = getter(name)
            if value is None:
                value = getter(name.title())
            return str(value).strip() if value is not None else ""
        return ""
    except Exception:
        return ""


def _clean_content_type(value: Any) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _declared_oversized(source: Any) -> bool:
    """True iff the source declares a body larger than :data:`MAX_IMAGE_BYTES`."""
    raw = _header(source, "content-length")
    if not raw:
        return False
    try:
        return int(str(raw).strip()) > MAX_IMAGE_BYTES
    except (TypeError, ValueError):
        return False


def _sniff(data: bytes) -> str:
    for magic, content_type in _MAGIC:
        if data.startswith(magic):
            return content_type
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _resolve_content_type(data: bytes, content_type: Any) -> str:
    """Declared type if it is an image; else a magic-confirmed type; else ``""``.

    ``""`` means reject: an explicitly non-image type (``text/html``,
    ``application/json``) is never overridden by magic bytes, and an unknown or
    opaque type must be confirmed by the payload magic.
    """
    declared = _clean_content_type(content_type)
    if declared.startswith("image/"):
        return declared
    if declared and declared not in _OPAQUE_CONTENT_TYPES:
        return ""
    return _sniff(data)


def _url_suffix(url: str) -> str:
    try:
        name = Path(urlsplit(str(url or "")).path).name
        suffix = Path(name).suffix.lower()
        return suffix if suffix in _IMAGE_SUFFIXES else ""
    except Exception:
        return ""


def _final_path(dest: Any, url: str, content_type: str) -> Optional[Path]:
    """``dest`` with an image suffix: honored if already one, else appended."""
    try:
        path = Path(dest)
    except Exception:
        return None
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        return path
    suffix = (
        _CONTENT_TYPE_SUFFIX.get(_clean_content_type(content_type))
        or _url_suffix(url)
        or ".jpg"
    )
    try:
        return path.with_name(path.name + suffix)
    except Exception:
        return None


def _read_stream(resp: Any) -> Optional[bytes]:
    """Stream a response body, aborting over :data:`MAX_IMAGE_BYTES`."""
    iterator = getattr(resp, "iter_content", None)
    if callable(iterator):
        buffer = bytearray()
        try:
            for chunk in iterator(chunk_size=_READ_CHUNK_BYTES):
                if not chunk:
                    continue
                buffer += chunk
                if len(buffer) > MAX_IMAGE_BYTES:
                    logger.warning("image payload exceeded %s bytes; aborting", MAX_IMAGE_BYTES)
                    return None
            return bytes(buffer)
        except TypeError:  # pragma: no cover - signature-less fake
            pass
        except Exception as exc:  # pragma: no cover - transport failure mid-stream
            logger.warning("image stream failed: %s", exc)
            return None
    data = getattr(resp, "content", None)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        return None
    data = bytes(data)
    return data if 0 < len(data) <= MAX_IMAGE_BYTES else None


def _interpret_fetcher_result(result: Any) -> Tuple[Optional[bytes], str]:
    """Normalize an injected fetcher result -> ``(payload, content_type)``.

    Accepted shapes: raw ``bytes``; ``(bytes, content_type)`` (either order);
    or a response-like object exposing ``.content`` / ``.headers`` /
    ``.status_code``. Text payloads are never images.
    """
    if result is None:
        return None, ""
    if isinstance(result, (bytes, bytearray, memoryview)):
        return bytes(result), ""
    if isinstance(result, str):
        return None, ""
    if isinstance(result, (tuple, list)) and len(result) == 2:
        first, second = result
        if isinstance(first, (bytes, bytearray, memoryview)):
            return bytes(first), _clean_content_type(second)
        if isinstance(second, (bytes, bytearray, memoryview)):
            return bytes(second), _clean_content_type(first)
        return None, ""
    status = getattr(result, "status_code", None)
    if status is not None:
        try:
            if int(status) != 200:
                return None, _header(result, "content-type")
        except (TypeError, ValueError):
            return None, ""
    if _declared_oversized(result):
        logger.warning("declared image payload exceeds %s bytes; rejecting",
                       MAX_IMAGE_BYTES)
        return None, _header(result, "content-type")
    data = getattr(result, "content", None)
    if data is None:
        data = getattr(result, "body", None)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        return None, ""
    return bytes(data), _header(result, "content-type")


def _call_fetcher(fetcher: Callable, url: str,
                  headers: Dict[str, str]) -> Tuple[Optional[bytes], str]:
    """Injectable fetch for tests (zero network). Never raises."""
    try:
        try:
            result = fetcher(url, headers=headers, timeout=DOWNLOAD_TIMEOUT)
        except TypeError:
            result = fetcher(url)
    except Exception as exc:
        logger.warning("fetcher failed for %s: %s", url, exc)
        return None, ""
    return _interpret_fetcher_result(result)


def _fetch_bytes(url: str, fetcher: Optional[Callable] = None
                 ) -> Tuple[Optional[bytes], str]:
    """GET/DL an image payload -> ``(bytes|None, content_type)``. Never raises."""
    headers = _image_headers(url)
    if fetcher is not None:
        return _call_fetcher(fetcher, url, headers)
    try:
        resp = _get_session().get(url, headers=headers, timeout=DOWNLOAD_TIMEOUT,
                                  stream=True)
        code = getattr(resp, "status_code", 200)
        if code != 200:
            logger.warning("GET %s -> HTTP %s", url, code)
            return None, _header(resp, "content-type")
        content_type = _header(resp, "content-type")
        if _declared_oversized(resp):
            logger.warning("GET %s declares a body over %s bytes; skipping",
                           url, MAX_IMAGE_BYTES)
            return None, content_type
        return _read_stream(resp), content_type
    except Exception as exc:
        logger.warning("GET %s failed: %s", url, exc)
        return None, ""


def _unlink(path: Any) -> bool:
    try:
        Path(path).unlink()
        return True
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.warning("unlink %s failed: %s", path, exc)
        return False


def _download(url: str, dest: Any, fetcher: Optional[Callable] = None
              ) -> Tuple[Optional[Path], int, str]:
    """Fetch + validate + write -> ``(path|None, bytes_written, content_type)``.

    Rejects non-image content types, image payloads over
    :data:`MAX_IMAGE_BYTES`, and empty bodies. A partial write is removed, so a
    non-zero return always means a complete image on disk.
    """
    data, content_type = _fetch_bytes(url, fetcher)
    if not data:
        return None, 0, content_type
    if len(data) > MAX_IMAGE_BYTES:
        logger.warning("image payload for %s is %s bytes (> cap)", url, len(data))
        return None, 0, content_type
    resolved = _resolve_content_type(data, content_type)
    if not resolved:
        logger.warning("rejecting non-image payload for %s (content-type=%r)",
                       url, content_type)
        return None, 0, content_type
    path = _final_path(dest, url, resolved)
    if path is None:
        return None, 0, content_type
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
    except Exception as exc:
        logger.warning("writing %s failed: %s", path, exc)
        _unlink(path)
        return None, 0, content_type
    return path, len(data), resolved


def download_image(url: str, dest: Any, fetcher: Optional[Callable] = None) -> int:
    """Download ``url`` to ``dest`` -> bytes written (0 on any failure).

    ``dest`` is the exact destination path; when it carries no recognizable
    image suffix the suffix derived from the response content type (else from
    the URL, else ``.jpg``) is appended.
    """
    _path, written, _content_type = _download(url, dest, fetcher)
    return int(written)


# ---------------------------------------------------------------------------
# OCR (lazy import + lazy singleton; never constructed at import time)
# ---------------------------------------------------------------------------

_ocr_engine = None


def _get_ocr_engine():
    """Lazy ``FinancialOCREngine`` singleton (heavy: ~3s/image, GPU-backed)."""
    global _ocr_engine
    if _ocr_engine is None:
        from reality_engine.processing.ocr_engine import FinancialOCREngine
        _ocr_engine = FinancialOCREngine()
    return _ocr_engine


def _to_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence != confidence:  # NaN
        return 0.0
    return min(max(confidence, 0.0), 1.0)


def _normalize_ocr_result(result: Any) -> Dict[str, Any]:
    if result is None:
        return dict(_EMPTY_OCR)
    if isinstance(result, dict):
        text = result.get("raw_text")
        confidence = result.get("avg_confidence")
    else:
        text = getattr(result, "raw_text", None)
        confidence = getattr(result, "avg_confidence", None)
    cleaned = _WS_RE.sub(" ", str(text or "")).strip()
    if not cleaned:
        # Confidence describes text: an engine reporting 0.97 over no text is
        # reporting nothing, and a non-zero confidence must never make an empty
        # capture look like a signal.
        return dict(_EMPTY_OCR)
    return {"text": cleaned, "confidence": _to_confidence(confidence)}


def ocr_image(path: Any, ocr: Any = None) -> Dict[str, Any]:
    """OCR ``path`` -> ``{"text": str, "confidence": float}``.

    ``ocr`` is injectable (any object with ``process_image``); otherwise the lazy
    :class:`FinancialOCREngine` singleton is used. Any failure (missing engine,
    unreadable image, engine error) returns ``{"text": "", "confidence": 0.0}``
    — never raises, so an OCR miss can only ever *skip* a capture.
    """
    try:
        engine = ocr if ocr is not None else _get_ocr_engine()
        if engine is None:
            return dict(_EMPTY_OCR)
        return _normalize_ocr_result(engine.process_image(str(path)))
    except Exception as exc:
        logger.warning("OCR failed for %s: %s", path, exc)
        return dict(_EMPTY_OCR)


# ---------------------------------------------------------------------------
# Schema (owned by this module: additive + idempotent, no other table touched)
# ---------------------------------------------------------------------------

_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS news_visual_artifacts (
        artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id INTEGER,
        symbol TEXT,
        source_type TEXT,
        source_url TEXT,
        media_url TEXT,
        local_path TEXT,
        ocr_text TEXT,
        ocr_confidence REAL,
        ocr_chars INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_news_visual_artifacts_doc_id"
    " ON news_visual_artifacts(doc_id)",
)

_ARTIFACT_INSERT = """
INSERT INTO news_visual_artifacts
    (doc_id, symbol, source_type, source_url, media_url, local_path,
     ocr_text, ocr_confidence, ocr_chars)
VALUES (:doc_id, :symbol, :source_type, :source_url, :media_url, :local_path,
        :ocr_text, :ocr_confidence, :ocr_chars)
"""


def _session_factory(target: Any):
    """Session context-manager factory for a DatabaseManager / Repository / None.

    ``None`` uses the live ``DatabaseManager`` (``config.DB_PATH``); a wrapper
    exposing ``.db`` is unwrapped to its manager.
    """
    if target is None:
        from reality_engine.db.database import DatabaseManager
        target = DatabaseManager()
    if hasattr(target, "session"):
        return target.session
    inner = getattr(target, "db", None)
    if inner is not None and hasattr(inner, "session"):
        return inner.session
    raise TypeError(f"db object has no session(): {type(target).__name__}")


def ensure_schema(db: Any = None) -> bool:
    """Create ``news_visual_artifacts`` (+ doc_id index) if absent. Idempotent.

    ``db`` accepts a ``DatabaseManager``, a ``Repository``, or ``None`` for the
    live database. Returns True on success; False (logged, never raised) on any
    failure.
    """
    try:
        session = _session_factory(db)
        with session() as conn:
            for statement in _SCHEMA_SQL:
                conn.execute(statement)
        return True
    except Exception as exc:
        logger.warning("news_visual_artifacts ensure failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def _iso_day(value: Any) -> str:
    candidate = str(value or "")[:10]
    try:
        return dt.date.fromisoformat(candidate).isoformat()
    except (TypeError, ValueError):
        return ""


def _first_symbol(symbols: Any) -> str:
    try:
        for symbol in symbols or []:
            candidate = str(symbol or "").strip()
            if candidate:
                return candidate
    except Exception:
        pass
    return ""


def _tag_from_ocr(ocr_text: str, repo: Any) -> List[str]:
    """Tickers named inside an infographic's own OCR text (fail-closed).

    Infographic labels are Title Case or caps ("Nestle", "ITC", "Kellton"), so
    the text is also scanned upper-cased. Ticker matching is word-bounded and
    restricted to real master symbols, but English words that are also NSE
    tickers still collide ("TECH", "FOCUS", "GLOBAL"), so hits are filtered
    through the repo's shared noise list (telegram_client._COMMON_NOISE_TICKERS)
    plus the collisions observed in real infographics.
    """
    if not ocr_text or repo is None:
        return []
    try:
        from reality_engine.ingestion.news_feed_client import (
            load_symbol_map, tag_symbols,
        )

        symbol_map = load_symbol_map(repo, include_names=True)
        hits = tag_symbols(ocr_text, symbol_map)
        if not hits:
            hits = tag_symbols(ocr_text.upper(), symbol_map)
        noise = _ocr_noise_tickers()
        return [h for h in hits if h.upper() not in noise]
    except Exception as exc:
        logger.debug("ocr symbol tagging unavailable: %s", exc)
        return []


def _ocr_noise_tickers() -> set:
    """Shared noise list + English-word collisions seen in real infographics."""
    noise = {"TECH", "FOCUS", "GLOBAL", "GROWTH", "VALUE", "MONEY", "MEDIA",
             "PRIME", "SMART", "IDEA", "POWER", "IN", "ON", "AT", "IT"}
    try:
        from reality_engine.ingestion.telegram_client import (
            _COMMON_NOISE_TICKERS,
        )

        noise |= set(_COMMON_NOISE_TICKERS)
    except Exception as exc:
        logger.debug("noise ticker list unavailable: %s", exc)
    return noise


def _make_isin_lookup(repo: Any):
    """Lazy ``symbol -> isin`` lookup over the active master (``""`` on miss)."""
    master: Optional[Dict[str, str]] = None

    def lookup(symbol: str) -> str:
        nonlocal master
        if not symbol or repo is None:
            return ""
        if master is None:
            try:
                rows = repo.get_all_companies(active_only=True) or []
                master = {
                    str(row.get("nse_symbol")): str(row.get("isin") or "")
                    for row in rows
                    if isinstance(row, dict) and row.get("nse_symbol")
                }
            except Exception as exc:
                logger.warning("master lookup unavailable: %s", exc)
                master = {}
        return master.get(symbol, "")

    return lookup


def _chunk_exists(session_factory, chunk_id: str) -> bool:
    with session_factory() as conn:
        row = conn.execute(
            "SELECT 1 FROM intelligence_fts WHERE chunk_id = ? LIMIT 1",
            (chunk_id,),
        ).fetchone()
    return row is not None


def _delete_under_data_dir(path: Any, stats: Dict[str, Any]) -> None:
    """Unlink ``path`` only when it resolves inside ``config.DATA_DIR``."""
    try:
        resolved = Path(path).resolve()
        resolved.relative_to(Path(DATA_DIR).resolve())
    except ValueError:
        stats["errors"].append(f"refusing to delete outside DATA_DIR: {path}")
        return
    except Exception as exc:
        stats["errors"].append(f"path check failed for {path}: {exc}")
        return
    if _unlink(resolved):
        stats["files_deleted"] += 1


def _capture_one(record: Any, repo: Any, session_factory, fetcher: Any, ocr: Any,
                 keep_files: bool, isin_lookup, seen_media: set,
                 stats: Dict[str, Any]) -> None:
    """Process one record. Raises only into the caller's per-record guard."""
    if not isinstance(record, dict):
        stats["errors"].append(f"record is not a mapping: {type(record).__name__}")
        return
    media_url = str(record.get("media_url") or "").strip()
    text = str(record.get("text") or "").strip()
    if not media_url or not text:
        stats["skipped_no_media"] += 1
        return
    # Business Standard emits one generic asset for ~30 of its 35 items: OCR it
    # once per batch, not 30 times. A URL is claimed only by a *successful*
    # download, so a transient failure does not poison later occurrences.
    if media_url in seen_media:
        stats["skipped_duplicate_media"] += 1
        return

    digest = str(record.get("sha256_hash") or "").strip()
    row = repo.get_raw_document_by_hash(digest) if (repo is not None and digest) else None
    if not row:
        stats["errors"].append(f"no raw_document for sha256={digest[:16]}")
        return
    doc_id = row.get("doc_id")
    if doc_id is None:
        stats["errors"].append(f"raw_document without doc_id for sha256={digest[:16]}")
        return
    source_type = str(record.get("source_type") or row.get("source_type") or "")
    chunk_id = f"{source_type}:{int(doc_id)}:{CHUNK_SUFFIX}"

    if _chunk_exists(session_factory, chunk_id):
        stats["skipped_existing"] += 1
        return

    day = _iso_day(record.get("published_date")) or _iso_day(row.get("published_date")) \
        or dt.date.today().isoformat()
    key = hashlib.sha256(media_url.encode("utf-8")).hexdigest()[:16]
    dest = Path(DATA_DIR) / IMAGE_DIR_NAME / day / key
    path, written, _content_type = _download(media_url, dest, fetcher)
    if not path or written <= 0:
        stats["errors"].append(f"download failed: {media_url}")
        return
    stats["downloaded"] += 1
    seen_media.add(media_url)

    result = ocr_image(path, ocr=ocr)
    ocr_text = str(result.get("text") or "")
    confidence = _to_confidence(result.get("confidence"))
    if ocr_text:
        stats["ocr_ok"] += 1
    if len(ocr_text) < MIN_OCR_CHARS or confidence <= 0.0:
        # A logo/wordmark is not an infographic: no chunk, no artifact, and the
        # file is removed (it has no further use).
        stats["skipped_low_signal"] += 1
        _delete_under_data_dir(path, stats)
        return

    # The chart's own labels often name the scrip even when the headline does
    # not ("ITC HOTELS / NESTLE / KELLTON TECH"), so fall back to tagging the
    # OCR text before giving up on a symbol.
    symbol = _first_symbol(record.get("symbols"))
    if not symbol:
        symbol = _first_symbol(_tag_from_ocr(ocr_text, repo))
    chunk_written = repo.insert_fts_chunks([{
        "chunk_id": chunk_id,
        "symbol": symbol,
        "isin": isin_lookup(symbol),
        "source_type": source_type,
        "document_date": record.get("published_date") or row.get("published_date"),
        "document_text": (CHUNK_PREFIX + ocr_text)[:MAX_OCR_TEXT],
    }])
    if chunk_written is None or int(chunk_written) >= 1:
        stats["chunks_written"] += 1

    with session_factory() as conn:
        cursor = conn.execute(_ARTIFACT_INSERT, {
            "doc_id": int(doc_id),
            "symbol": symbol,
            "source_type": source_type,
            "source_url": str(record.get("source_url") or row.get("source_url") or ""),
            "media_url": media_url,
            "local_path": str(path),
            "ocr_text": ocr_text,
            "ocr_confidence": float(confidence),
            "ocr_chars": len(ocr_text),
        })
    if cursor.rowcount is None or cursor.rowcount >= 1:
        stats["artifacts_written"] += 1

    if not keep_files:
        _delete_under_data_dir(path, stats)


def capture_images(records: Any, repo: Any = None, db: Any = None, limit: Any = 20,
                   fetcher: Optional[Callable] = None, ocr: Any = None,
                   keep_files: bool = True) -> Dict[str, Any]:
    """Capture the infographics of ``records`` (news feed contracts). Never raises.

    ``records``: ``news_feed_client`` records carrying ``media_url`` + ``text``
    (plus the raw_documents contract keys). ``repo``/``db``: where to resolve the
    persisted ``doc_id`` and write the chunk + artifact row. ``fetcher``/``ocr``:
    injection points for tests (bytes-returning callable / ``process_image``).
    ``keep_files=False`` deletes each stored image after its rows are written.

    Returns counts: ``attempted`` (records examined), ``downloaded``,
    ``ocr_ok`` (OCR returned text), ``chunks_written``, ``artifacts_written``,
    ``files_deleted``, ``skipped_no_media``, ``skipped_duplicate_media`` (same
    asset already captured earlier in this batch), ``skipped_existing`` (chunk
    already there — idempotent re-run), ``skipped_low_signal`` (logo/empty OCR:
    nothing written, file removed), ``errors`` (per-record messages).
    """
    stats: Dict[str, Any] = {
        "attempted": 0,
        "downloaded": 0,
        "ocr_ok": 0,
        "chunks_written": 0,
        "artifacts_written": 0,
        "files_deleted": 0,
        "skipped_no_media": 0,
        "skipped_duplicate_media": 0,
        "skipped_existing": 0,
        "skipped_low_signal": 0,
        "errors": [],
    }
    try:
        items: List[Any] = list(records or [])
    except Exception as exc:
        stats["errors"].append(f"records not iterable: {exc}")
        return stats
    try:
        cap = int(limit) if limit is not None else None
    except (TypeError, ValueError):
        cap = None
    if cap is not None and cap >= 0:
        items = items[:cap]

    target = db if db is not None else repo
    try:
        session_factory = _session_factory(target)
    except Exception as exc:
        stats["errors"].append(f"db unavailable: {exc}")
        return stats
    ensure_schema(target)

    if repo is None:
        try:
            from reality_engine.db.repository import Repository
            repo = Repository(manager=db) if db is not None else Repository()
        except Exception as exc:
            stats["errors"].append(f"repository unavailable: {exc}")
            repo = None

    isin_lookup = _make_isin_lookup(repo)
    seen_media: set = set()
    for record in items:
        stats["attempted"] += 1
        try:
            _capture_one(record, repo, session_factory, fetcher, ocr, keep_files,
                         isin_lookup, seen_media, stats)
        except Exception as exc:
            stats["errors"].append(f"{type(exc).__name__}: {exc}")
    return stats
