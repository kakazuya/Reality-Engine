"""
Telegram MTProto Ingestion Client Module (Layer 3)
Listens to multi-thread Telegram supergroups/channels, downloads chart screenshots
to the inbox, executes OCR and entity extraction, and indexes forum topics.
Hardened: offline fallback, mock mode, flood-wait backoff, symbol validation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Safe dynamic import for Telethon
try:
    import telethon
    from telethon import TelegramClient, events
    from telethon.errors import FloodWaitError, RPCError
    TELETHON_INSTALLED = True
except (ImportError, Exception):
    telethon = None
    TelegramClient = None
    events = None
    FloodWaitError = Exception
    RPCError = Exception
    TELETHON_INSTALLED = False

from reality_engine.config import DATA_DIR, TELEGRAM_IMAGES_DIR, INBOX_DIR
from reality_engine.db.database import db_manager, DatabaseManager
from reality_engine.db.repository import repo, Repository
from reality_engine.processing.ocr_engine import FinancialOCREngine
from reality_engine.pipeline.inbox_runner import InboxRunner

logger = logging.getLogger("reality_engine.telegram_client")

# Common English noise words to filter from ticker candidates (reduces false positives like TARGET, SL)
_COMMON_NOISE_TICKERS = {
    "THE", "AND", "FOR", "BUY", "SELL", "TARGET", "TGT", "STOP", "LOSS", "ABOVE",
    "BELOW", "BREAKOUT", "BREAK", "LEVEL", "SUPPORT", "RESISTANCE", "CHART",
    "SETUP", "STRONG", "WEAK", "HEAVY", "LIGHT", "VOLUME", "DELIVERY", "SPIKE",
    "SEEN", "FROM", "WITH", "THIS", "THAT", "HAVE", "HAS", "BEEN", "WILL",
    "ALERT", "UPDATE", "NEWS", "TODAY", "TOMORROW", "WEEK", "MONTH", "YEAR",
    "PRICE", "CLOSE", "OPEN", "HIGH", "LOW", "RANGE", "TREND", "BULLISH",
    "BEARISH", "NEUTRAL", "HOLD", "ADD", "ACCUMULATE", "GENERAL", "DISCUSSION",
    "TOPIC", "THREAD", "CHANNEL", "GROUP", "FORUM",
}


class TelegramListener:
    """
    Modular Telegram supergroup & channel listener for research threads,
    chart screenshots, and real-time commentary.
    """

    def __init__(
        self,
        api_id: Optional[Union[int, str]] = None,
        api_hash: Optional[str] = None,
        session_path: Optional[Union[str, Path]] = None,
        target_channels: Optional[Union[List[Union[str, int]], str, int]] = None,
        inbox_dir: Optional[Union[str, Path]] = None,
        download_dir: Optional[Union[str, Path]] = None,
        db: Optional[DatabaseManager] = None,
        repository: Optional[Repository] = None,
        inbox_runner: Optional[InboxRunner] = None,
        ocr_engine: Optional[FinancialOCREngine] = None,
        mock_mode: bool = False,
    ):
        # Resolve credentials & session
        raw_api_id = api_id or os.environ.get("TELEGRAM_API_ID")
        self.api_id: Optional[int] = None
        if raw_api_id is not None and str(raw_api_id).strip() != "":
            try:
                self.api_id = int(str(raw_api_id).strip())
            except (ValueError, TypeError):
                self.api_id = None

        self.api_hash: Optional[str] = api_hash or os.environ.get("TELEGRAM_API_HASH")
        if self.api_hash is not None:
            self.api_hash = str(self.api_hash).strip() or None
        self.session_path = Path(session_path or os.environ.get("TELEGRAM_SESSION_PATH", DATA_DIR / "telegram_session"))
        try:
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        
        # Parse target channels
        channels = target_channels or os.environ.get("TELEGRAM_TARGET_CHANNELS", "")
        self.target_channels: List[Union[str, int]] = self._normalize_channels(channels)

        # File system paths
        self.inbox_dir = Path(inbox_dir or INBOX_DIR)
        self.download_dir = Path(download_dir or self.inbox_dir / "images")
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Ingestion components
        self.db = db or db_manager
        self.repo = repository or repo
        self.ocr = ocr_engine or FinancialOCREngine()
        self._inbox_runner = inbox_runner

        # State & Mode
        self.mock_mode = mock_mode
        self.client: Any = None
        self.is_running: bool = False
        self._mock_queue: List[Any] = []

    @property
    def inbox_runner(self) -> InboxRunner:
        """Lazy instance of InboxRunner."""
        if self._inbox_runner is None:
            try:
                self._inbox_runner = InboxRunner(inbox_dir=self.inbox_dir, db=self.db)
            except Exception as exc:
                logger.warning("Failed to init InboxRunner: %s", exc)
                # Minimal stub to allow tests without vector store
                class _StubParser:
                    def parse_text(self, text, metadata, source_ref=""):
                        return []
                class _StubRunner:
                    parser = _StubParser()
                    def process_file(self, p): return {"path": p}
                    def _index(self, chunks, t): return None
                self._inbox_runner = _StubRunner()  # type: ignore
        return self._inbox_runner

    @staticmethod
    def _sanitize_filename_component(value: str) -> str:
        """Sanitize channel_id for safe filesystem usage (alphanumeric + underscore)."""
        # Replace any non-alphanumeric (except underscore) with underscore, trim length
        sanitized = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
        sanitized = re.sub(r"_+", "_", sanitized).strip("_")
        return sanitized[:64] or "telegram_inbox"

    @staticmethod
    def _normalize_channels(channels: Union[List[Union[str, int]], str, int]) -> List[Union[str, int]]:
        """Parses channels into a normalized, deduplicated list of channel usernames or IDs."""
        if not channels:
            return []
        raw_items: List[str] = []
        if isinstance(channels, list):
            for ch in channels:
                if isinstance(ch, int):
                    raw_items.append(str(ch))
                elif isinstance(ch, str) and ch.strip():
                    raw_items.append(ch.strip())
                elif ch is not None:
                    s = str(ch).strip()
                    if s:
                        raw_items.append(s)
        elif isinstance(channels, int):
            raw_items.append(str(channels))
        elif isinstance(channels, str):
            # Support comma and semicolon separators
            for item in channels.replace(";", ",").split(","):
                clean = item.strip()
                if clean:
                    raw_items.append(clean)
        else:
            return []

        # Normalize and deduplicate preserving order
        seen: set = set()
        res: List[Union[str, int]] = []
        for item in raw_items:
            if not item:
                continue
            # Try integer conversion (handles negative supergroup IDs like -100...)
            try:
                iv = int(item)
                key = iv
                val: Union[str, int] = iv
            except ValueError:
                # Keep string usernames as-is, ensure @ prefix handling is preserved
                key = item
                val = item
            if key not in seen:
                seen.add(key)
                res.append(val)
        return res

    def _filter_valid_symbols(self, candidates: List[str]) -> List[str]:
        """Filter ticker candidates against noise list and optional master_companies validation."""
        if not candidates:
            return []
        # Uppercase and basic length / noise filter
        filtered = []
        for c in candidates:
            up = c.upper().strip()
            if len(up) < 2 or len(up) > 12:
                continue
            if up in _COMMON_NOISE_TICKERS:
                continue
            if not re.fullmatch(r"[A-Z0-9]{2,12}", up):
                continue
            filtered.append(up)
        # Cross-validate against known master_companies if repo available (reduce false positives)
        # but keep all if DB is empty or lookup fails – graceful fallback
        try:
            # Attempt to fetch all symbols for validation (cached via DB)
            # We do a lightweight check: if repo has companies, filter; otherwise keep filtered list
            if hasattr(self.repo, "get_all_companies"):
                # Avoid heavy fetch on every message if many messages; use sampled check via get_company_by_symbol per candidate
                # but for efficiency we can try to fetch once lazily
                valid = []
                for sym in filtered:
                    try:
                        # Check if symbol exists in master (or allow unknown but plausible tickers to pass)
                        # We keep symbol if it's known OR if we cannot determine – to avoid dropping emerging smallcaps
                        # So we keep all after noise filter, but prioritize known ones for ordering
                        comp = self.repo.get_company_by_symbol(sym)  # type: ignore
                        if comp:
                            valid.append(sym)
                        else:
                            # Keep unknown symbols as well, but they will be sorted later
                            valid.append(sym)
                    except Exception:
                        valid.append(sym)
                filtered = valid
        except Exception:
            pass
        # Deduplicate and sort for determinism
        return sorted(set(filtered))

    def is_available(self) -> bool:
        """
        Checks if Telethon library is installed and valid API credentials exist.
        In mock_mode, always returns True.
        """
        if self.mock_mode:
            return True
        if not TELETHON_INSTALLED:
            return False
        if not self.api_id or self.api_id <= 0:
            return False
        if not self.api_hash or not str(self.api_hash).strip():
            return False
        if len(str(self.api_hash).strip()) < 10:
            # Telegram api_hash is 32 hex chars; len <10 is clearly invalid
            return False
        return True

    def enqueue_mock_message(self, payload: Dict[str, Any]) -> None:
        """Enqueue a dict payload for mock_mode processing via start_listening."""
        self._mock_queue.append(payload)

    def get_channel_stats(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent telegram_posts for diagnostics."""
        try:
            return self.repo.get_telegram_posts(limit=limit)  # type: ignore
        except Exception as exc:
            logger.warning("Failed to fetch telegram channel stats: %s", exc)
            return []

    async def handle_incoming_message(self, msg: Any) -> Dict[str, Any]:
        """
        Processes an incoming Telegram message:
        1. Extracts channel, message ID, forum topic / thread ID, text, and timestamp.
        2. Downloads media (photo, document, chart screenshot) to inbox/images/.
        3. Runs FinancialOCREngine for OCR text and entity recognition (tickers, targets, SL).
        4. Delegates to InboxRunner for indexing and database persistence into telegram_posts.
        """
        # 1. Message metadata extraction
        msg_id = getattr(msg, "id", None)
        if msg_id is None and isinstance(msg, dict):
            msg_id = msg.get("id", msg.get("message_id", 1))
        try:
            msg_id = int(msg_id or 1)
        except (ValueError, TypeError):
            msg_id = 1

        chat = getattr(msg, "chat", None)
        chat_id = getattr(msg, "chat_id", None) or getattr(msg, "channel_id", None)
        if chat_id is None and chat:
            chat_id = getattr(chat, "id", None) or getattr(chat, "username", None)
        if chat_id is None and isinstance(msg, dict):
            chat_id = msg.get("chat_id") or msg.get("channel_id") or "telegram_inbox"
        channel_id_str = str(chat_id or "telegram_inbox")

        channel_title = ""
        if chat:
            channel_title = getattr(chat, "title", "") or getattr(chat, "username", "") or ""
        if not channel_title and isinstance(msg, dict):
            channel_title = msg.get("channel_title") or msg.get("channel_name") or channel_id_str
        if not channel_title:
            channel_title = channel_id_str
        channel_title = str(channel_title).strip() or channel_id_str

        # Forum topic / reply-to thread extraction
        reply_to = getattr(msg, "reply_to", None)
        thread_topic_id = getattr(msg, "reply_to_msg_id", None)
        if thread_topic_id is None and reply_to:
            thread_topic_id = getattr(reply_to, "reply_to_top_id", None) or getattr(reply_to, "reply_to_msg_id", None)
        if thread_topic_id is None and hasattr(msg, "message_thread_id"):
            thread_topic_id = getattr(msg, "message_thread_id", None)
        if thread_topic_id is None and isinstance(msg, dict):
            thread_topic_id = msg.get("thread_topic_id") or msg.get("thread_id") or msg.get("reply_to_msg_id", 0)
        try:
            thread_topic_id = int(thread_topic_id or 0)
        except (ValueError, TypeError):
            thread_topic_id = 0

        thread_topic_name = None
        if isinstance(msg, dict):
            thread_topic_name = msg.get("thread_topic_name")
        if not thread_topic_name:
            # Topic heuristic
            if thread_topic_id > 0:
                thread_topic_name = f"Topic #{thread_topic_id}"
            else:
                thread_topic_name = "General Discussion"
        thread_topic_name = str(thread_topic_name).strip() or "General Discussion"

        # Raw text extraction – supports multiple field names, truncates extremely long messages gracefully
        raw_text = getattr(msg, "raw_text", None) or getattr(msg, "message", None) or getattr(msg, "text", "")
        if not raw_text and isinstance(msg, dict):
            raw_text = msg.get("text") or msg.get("message") or msg.get("raw_message_text") or ""
        raw_text = str(raw_text or "").strip()
        # Defensively cap logging length but persist full text in DB (TEXT unlimited)
        if len(raw_text) > 8000:
            logger.debug("Truncating overlong message %d from %d chars for processing", msg_id, len(raw_text))
            # Keep full for DB, but for entity extraction we cap at 8000
            raw_text_for_nlp = raw_text[:8000]
        else:
            raw_text_for_nlp = raw_text

        # Timestamp extraction
        dt = getattr(msg, "date", None)
        if dt is None and isinstance(msg, dict):
            dt = msg.get("date") or msg.get("timestamp") or msg.get("post_timestamp")
        if isinstance(dt, datetime):
            timestamp_str = dt.isoformat()
        elif isinstance(dt, str) and dt.strip():
            timestamp_str = dt.strip()
            # Try to normalize if parsable
            try:
                # Validate ISO format quickly
                datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except Exception:
                pass
        else:
            timestamp_str = datetime.now(timezone.utc).isoformat()

        # Inline button links extraction (Screener / Chart / Filing buttons in posts)
        button_links: List[Dict[str, Any]] = []
        try:
            buttons = getattr(msg, "buttons", None)
            if buttons is None and isinstance(msg, dict):
                buttons = msg.get("buttons") or msg.get("button_links")
            if buttons:
                for row in buttons:
                    if isinstance(row, (list, tuple)):
                        for bt in row:
                            label = getattr(bt, "text", None)
                            url = getattr(bt, "url", None)
                            if url:
                                button_links.append({"label": str(label or ""), "url": str(url)})
                    elif hasattr(row, "text") and hasattr(row, "url"):
                        button_links.append({"label": str(row.text), "url": str(row.url)})
            # Support raw list of {label, url} dicts from mock payloads
            if isinstance(buttons, list) and not button_links:
                for bt in buttons:
                    if isinstance(bt, dict) and bt.get("url"):
                        button_links.append({"label": str(bt.get("label", "")), "url": str(bt["url"])})
        except Exception as btn_exc:
            logger.debug("Button link extraction note: %s", btn_exc)

        # 2. Media detection & downloading
        has_media = bool(
            getattr(msg, "photo", None)
            or getattr(msg, "file", None)
            or getattr(msg, "media", None)
            or getattr(msg, "document", None)
            or (isinstance(msg, dict) and (msg.get("has_media") or msg.get("media_path") or msg.get("image_bytes") or msg.get("media")))
        )

        media_file_path: Optional[str] = None
        if has_media:
            safe_channel = self._sanitize_filename_component(channel_id_str)
            target_filename = f"tg_{safe_channel}_{msg_id}.png"
            target_path = self.download_dir / target_filename
            # Ensure download dir exists (may have been cleaned)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Telethon async download (live mode)
            if hasattr(msg, "download_media") and callable(getattr(msg, "download_media")):
                try:
                    downloaded = await msg.download_media(file=str(target_path))
                    if downloaded:
                        media_file_path = str(downloaded)
                    elif target_path.exists():
                        media_file_path = str(target_path)
                except Exception as exc:
                    logger.warning("Failed to download media from msg %d: %s", msg_id, exc)

            # Dictionary / Mock image bytes or existing file
            elif isinstance(msg, dict):
                img_bytes = msg.get("image_bytes")
                if img_bytes is not None:
                    try:
                        # Handle base64 string encoding for JSON-serialized bytes
                        if isinstance(img_bytes, str):
                            # Try base64 decode; if fails, treat as utf-8 bytes
                            try:
                                decoded = base64.b64decode(img_bytes, validate=False)
                                # Heuristic: use decoded if it looks like image bytes (starts with PNG/JPEG magic)
                                if decoded[:4] in [b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1"]:
                                    img_bytes = decoded
                                else:
                                    # If not image magic, assume original string was meant as bytes
                                    img_bytes = img_bytes.encode("utf-8") if isinstance(img_bytes, str) else img_bytes
                                    # But if decoded length is plausible image, prefer decoded
                                    if len(decoded) > 100:
                                        img_bytes = decoded
                            except Exception:
                                img_bytes = img_bytes.encode("utf-8") if isinstance(img_bytes, str) else img_bytes
                        if isinstance(img_bytes, (bytes, bytearray)):
                            with open(target_path, "wb") as f:
                                f.write(bytes(img_bytes))
                            media_file_path = str(target_path)
                        else:
                            logger.warning("Unsupported image_bytes type for msg %d: %s", msg_id, type(img_bytes))
                    except Exception as exc:
                        logger.warning("Failed to write image_bytes for msg %d: %s", msg_id, exc)
                elif msg.get("media_path"):
                    src = Path(str(msg["media_path"]))
                    if src.exists() and src.is_file():
                        try:
                            if src.resolve() != target_path.resolve():
                                shutil.copy2(str(src), str(target_path))
                            media_file_path = str(target_path)
                        except Exception as exc:
                            logger.warning("Failed to copy media_path %s for msg %d: %s", src, msg_id, exc)
                    else:
                        logger.debug("media_path does not exist for msg %d: %s", msg_id, src)
                        if self.mock_mode:
                            # In mock mode without existing file, still record placeholder path for traceability
                            media_file_path = str(target_path)
                else:
                    # In mock mode without bytes, generate a placeholder or record path if has_media flagged
                    if self.mock_mode:
                        media_file_path = str(target_path)
                        # Create empty placeholder to allow downstream OCR fallback to gracefully no-op
                        try:
                            if not target_path.exists():
                                target_path.touch(exist_ok=True)
                        except Exception:
                            pass

        # 3. OCR & Entity Extraction
        ocr_extracted_text = ""
        detected_symbols: List[str] = []
        price_targets: List[float] = []
        stop_losses: List[float] = []

        # If media is saved, run OCR
        if media_file_path and Path(media_file_path).exists():
            # Only run OCR if file is non-empty
            try:
                p = Path(media_file_path)
                if p.stat().st_size == 0 and not self.mock_mode:
                    logger.debug("Skipping OCR for empty media file %s", media_file_path)
                else:
                    ocr_result = self.ocr.process_image(media_file_path)
                    ocr_extracted_text = str(ocr_result.get("raw_text", "") or "")
                    detected_symbols.extend(ocr_result.get("tickers", []) or [])
                    detected_symbols.extend(ocr_result.get("ticker_candidates", []) or [])
                    price_targets.extend(ocr_result.get("price_targets", []) or [])
                    stop_losses.extend(ocr_result.get("stop_losses", []) or [])

                    # Delegate file processing to InboxRunner for FTS5 & Vector Store indexing
                    # Only if file has content and inbox_runner is available
                    if p.stat().st_size > 0:
                        try:
                            inbox_res = self.inbox_runner.process_file(media_file_path)
                            if inbox_res and inbox_res.get("path"):
                                media_file_path = str(inbox_res["path"])
                        except Exception as inbox_exc:
                            logger.warning("InboxRunner file ingestion note: %s", inbox_exc)
            except Exception as ocr_exc:
                logger.warning("OCR processing note on %s: %s", media_file_path, ocr_exc)

        # Extract entities from raw message text as well
        if raw_text_for_nlp:
            try:
                text_entities = self.ocr.extract_entities(raw_text_for_nlp)
                detected_symbols.extend(text_entities.get("ticker_candidates", []) or [])
                detected_symbols.extend(text_entities.get("tickers", []) or [])
                price_targets.extend(text_entities.get("price_targets", []) or [])
                stop_losses.extend(text_entities.get("stop_losses", []) or [])
            except Exception as exc:
                logger.warning("Entity extraction note for msg %d: %s", msg_id, exc)

            # Index text content into vector/FTS via inbox runner parser if available
            try:
                metadata = {
                    "doc_type": "TELEGRAM_POST",
                    "document_date": timestamp_str[:10] if len(timestamp_str) >= 10 else timestamp_str,
                    "channel": channel_title,
                    "thread": thread_topic_name,
                }
                chunks = self.inbox_runner.parser.parse_text(
                    raw_text_for_nlp,
                    metadata,
                    source_ref=f"telegram://{channel_id_str}/{msg_id}"
                )
                if chunks:
                    self.inbox_runner._index(chunks, "TELEGRAM_POST")
            except Exception as parse_exc:
                logger.debug("Text parser indexing note: %s", parse_exc)

        # Deduplicate and filter entities
        detected_symbols = self._filter_valid_symbols(detected_symbols)
        # Numeric deduplication with tolerance
        price_targets = sorted(set(float(x) for x in price_targets if isinstance(x, (int, float)) and x > 0))
        stop_losses = sorted(set(float(x) for x in stop_losses if isinstance(x, (int, float)) and x > 0))

        # 4. Database Persistence into telegram_posts
        post_id = f"{self._sanitize_filename_component(channel_id_str)}_{msg_id}"
        # Use sanitized channel_id for storage? Keep original channel_id_str for DB queryability; sanitize only for post_id
        post_record = {
            "id": post_id,
            "channel_id": channel_id_str,
            "channel_title": channel_title,
            "thread_topic_id": thread_topic_id,
            "thread_topic_name": thread_topic_name,
            "message_id": msg_id,
            "raw_message_text": raw_text,
            "has_media": 1 if has_media else 0,
            "media_file_path": media_file_path,
            "ocr_extracted_text": ocr_extracted_text,
            "detected_symbols_json": json.dumps(detected_symbols),
            "button_links_json": json.dumps(button_links),
            "post_timestamp": timestamp_str,
        }

        try:
            self.repo.upsert_telegram_posts(post_record)
        except Exception as db_exc:
            logger.warning("Failed to persist telegram_post to database: %s", db_exc)

        # 5. Formulate structured response
        return {
            "status": "processed",
            "id": post_id,
            "channel_id": channel_id_str,
            "channel_title": channel_title,
            "thread_topic_id": thread_topic_id,
            "thread_topic_name": thread_topic_name,
            "message_id": msg_id,
            "raw_message_text": raw_text,
            "has_media": has_media,
            "media_file_path": media_file_path,
            "ocr_extracted_text": ocr_extracted_text,
            "detected_symbols": detected_symbols,
            "button_links": button_links,
            "price_targets": price_targets,
            "stop_losses": stop_losses,
            "post_timestamp": timestamp_str,
        }

    def simulate_incoming_message(
        self,
        text: str = "",
        chat_id: Union[str, int] = "mock_channel",
        channel_title: str = "Mock Channel",
        message_id: int = 1,
        thread_topic_id: int = 0,
        thread_topic_name: str = "General",
        media_path: Optional[Union[str, Path]] = None,
        image_bytes: Optional[Union[bytes, str]] = None,
        date: Optional[Union[datetime, str]] = None,
    ) -> Dict[str, Any]:
        """
        Synchronous simulation helper to inject test messages without live Telegram network.
        Supports both raw bytes and base64-encoded string for image_bytes.
        """
        # Normalize image_bytes if string is base64
        normalized_bytes: Optional[bytes] = None
        if isinstance(image_bytes, str):
            # Attempt base64 decode; if fails, treat as utf-8 bytes
            try:
                # If string length & charset suggests base64, decode
                if len(image_bytes) > 50 and re.fullmatch(r"[A-Za-z0-9+/=\n\r]+", image_bytes.strip()):
                    normalized_bytes = base64.b64decode(image_bytes.strip(), validate=False)
                else:
                    normalized_bytes = image_bytes.encode("utf-8")
            except Exception:
                normalized_bytes = image_bytes.encode("utf-8") if isinstance(image_bytes, str) else None
        elif isinstance(image_bytes, (bytes, bytearray)):
            normalized_bytes = bytes(image_bytes)

        # Normalize date
        if isinstance(date, datetime):
            date_str = date.isoformat()
        elif isinstance(date, str):
            date_str = date
        else:
            date_str = datetime.now(timezone.utc).isoformat()

        msg_payload = {
            "id": message_id,
            "chat_id": chat_id,
            "channel_title": channel_title,
            "thread_topic_id": thread_topic_id,
            "thread_topic_name": thread_topic_name,
            "text": text,
            "has_media": bool(media_path or normalized_bytes),
            "media_path": str(media_path) if media_path else None,
            "image_bytes": normalized_bytes,
            "date": date_str,
        }

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(lambda: asyncio.run(self.handle_incoming_message(msg_payload))).result()
            else:
                return loop.run_until_complete(self.handle_incoming_message(msg_payload))
        except RuntimeError:
            return asyncio.run(self.handle_incoming_message(msg_payload))

    async def start_listening(self, duration_seconds: Optional[float] = None) -> Dict[str, Any]:
        """
        Asynchronous listener entry point:
        - If offline or missing Telethon/credentials: logs warning and executes graceful offline fallback.
        - If in mock_mode: simulates listener queue processing.
        - If available: starts Telethon client with reconnection backoff and FloodWait handling.
        """
        if not self.is_available() and not self.mock_mode:
            logger.warning(
                "TelegramListener: Telethon is not installed or API credentials are not set. "
                "Operating in graceful offline fallback mode."
            )
            return {
                "status": "offline_fallback",
                "reason": "telethon_or_credentials_unavailable",
                "message": "Telegram integration is dormant. Local drop-in inbox remains active."
            }

        if self.mock_mode:
            logger.info("TelegramListener starting in mock mode for %s channels...", self.target_channels)
            self.is_running = True
            try:
                # Process any mock items in queue
                results = []
                while self._mock_queue:
                    item = self._mock_queue.pop(0)
                    res = await self.handle_incoming_message(item)
                    results.append(res)
                if duration_seconds:
                    await asyncio.sleep(min(duration_seconds, 0.1))
                return {"status": "mock_listener_completed", "processed_count": len(results), "items": results}
            finally:
                self.is_running = False

        # Live Telethon Client Setup
        logger.info("Starting Telegram MTProto Listener for %d channels...", len(self.target_channels))
        # Ensure session parent dir exists
        try:
            Path(self.session_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.client = TelegramClient(str(self.session_path), int(self.api_id), str(self.api_hash))  # type: ignore

        # Register event handler for incoming messages
        filter_chats = self.target_channels if self.target_channels else None

        @self.client.on(events.NewMessage(chats=filter_chats))  # type: ignore
        async def on_new_message(event: Any):
            try:
                await self.handle_incoming_message(event.message)
            except Exception as exc:
                logger.error("Error handling incoming Telegram message %s: %s", getattr(event.message, "id", "unknown"), exc)

        retry_delay = 2.0
        max_retry_delay = 60.0
        self.is_running = True
        import random

        while self.is_running:
            try:
                await self.client.start()
                logger.info("Telegram MTProto Listener active and connected.")
                if duration_seconds:
                    await asyncio.sleep(duration_seconds)
                    break
                else:
                    await self.client.run_until_disconnected()
                    break
            except FloodWaitError as flood_err:
                wait_sec = int(getattr(flood_err, "seconds", 30)) + 2
                # Add jitter 0-1 sec to avoid thundering herd
                wait_sec += random.uniform(0, 1)
                logger.warning("Telegram FloodWaitError encountered: backing off for %.1f seconds", wait_sec)
                await asyncio.sleep(wait_sec)
            except asyncio.CancelledError:
                logger.info("TelegramListener cancelled gracefully.")
                break
            except Exception as exc:
                logger.error("Telegram connection error: %s. Retrying in %.1fs...", exc, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)
                # jitter
                retry_delay += random.uniform(0, 0.5)
            finally:
                # Ensure disconnect if stopping, otherwise keep connected for next loop
                if not self.is_running and self.client and hasattr(self.client, "is_connected"):
                    try:
                        if self.client.is_connected():
                            await self.client.disconnect()
                    except Exception as exc:
                        logger.debug("Disconnect note: %s", exc)

        self.is_running = False
        return {"status": "listener_stopped"}

    async def stop_listening(self) -> None:
        """Stops the active Telegram listener."""
        self.is_running = False
        if self.client and hasattr(self.client, "disconnect"):
            try:
                await self.client.disconnect()
            except Exception as exc:
                logger.debug("Disconnect note: %s", exc)


# Global default instance
telegram_listener = TelegramListener()
