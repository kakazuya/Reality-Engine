"""Telegram -> FTS backfill: index telegram_posts rows into intelligence_fts (news-feed Tier-2).

READ-ONLY vs source data: this module only SELECTs from ``telegram_posts`` and
INSERTs derived rows into ``intelligence_fts``. It never synthesizes content —
a query miss returns zero counts + a log line, never fabricated rows.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("reality_engine.rumor_backfill")

_SOURCE_TYPE = "TELEGRAM_POST"
_MAX_TEXT_LEN = 4000


def _resolve_manager(db: Any) -> Any:
    """Accept a DatabaseManager, a Repository, or None (default manager)."""
    if db is None:
        from reality_engine.db.database import db_manager as _default_mgr

        return _default_mgr
    if hasattr(db, "session"):
        return db
    inner = getattr(db, "db", None)
    if inner is not None and hasattr(inner, "session"):
        return inner
    return db


def _first_symbol(raw: Any) -> str:
    """First detected symbol from detected_symbols_json; '' on anything bad."""
    if not raw:
        return ""
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return ""
    try:
        if isinstance(parsed, list):
            if not parsed:
                return ""
            first = parsed[0]
            if isinstance(first, dict):
                return str(first.get("symbol", "") or "").strip()
            return str(first or "").strip()
        if isinstance(parsed, dict):
            sym = parsed.get("symbol", "")
            if sym:
                return str(sym).strip()
            syms = parsed.get("symbols", [])
            if isinstance(syms, list) and syms:
                return str(syms[0] or "").strip()
            return ""
        if isinstance(parsed, str):
            return parsed.strip()
    except Exception:
        return ""
    return ""


def backfill_telegram_fts(
    db: Any = None,
    limit: int = 0,
    since: Optional[str] = None,
) -> Dict[str, int]:
    """Index telegram_posts rows into intelligence_fts (idempotent).

    Reads ``telegram_posts`` ordered by ``post_timestamp`` DESC with an optional
    ``since`` filter (``post_timestamp >= since``) and optional ``limit``. Rows
    with empty ``raw_message_text`` are skipped; rows whose ``'tg:<id>'``
    chunk already exists in ``intelligence_fts`` are skipped so re-runs are
    no-ops. One FTS row per new post: chunk_id ``'tg:<id>'``, first detected
    symbol (else ``''``), ``isin`` ``''``, source_type ``'TELEGRAM_POST'``,
    ``document_date`` = ``post_timestamp[:10]``, ``document_text`` = raw text
    plus ``' | OCR: '`` + OCR text when present, capped at 4000 chars.
    """
    counts = {"posts_seen": 0, "chunks_written": 0, "skipped_empty": 0, "skipped_dup": 0}
    mgr = _resolve_manager(db)
    try:
        query = (
            "SELECT id, raw_message_text, ocr_extracted_text, "
            "detected_symbols_json, post_timestamp FROM telegram_posts"
        )
        params: List[Any] = []
        if since is not None:
            query += " WHERE post_timestamp >= ?"
            params.append(since)
        query += " ORDER BY post_timestamp DESC"
        if limit and limit > 0:
            query += " LIMIT ?"
            params.append(int(limit))
        with mgr.session() as conn:
            try:
                cur = conn.execute(query, tuple(params))
                posts = [{k: row[k] for k in row.keys()} for row in cur.fetchall()]
            except Exception as exc:
                logger.warning("rumor_backfill telegram_posts miss: %s", exc)
                return counts
            counts["posts_seen"] = len(posts)
            # Idempotency: which candidate chunk_ids already exist?
            chunk_ids = [f"tg:{p.get('id')}" for p in posts]
            existing = set()
            if chunk_ids:
                try:
                    placeholders = ",".join("?" for _ in chunk_ids)
                    cur = conn.execute(
                        f"SELECT chunk_id FROM intelligence_fts WHERE chunk_id IN ({placeholders})",
                        tuple(chunk_ids),
                    )
                    existing = {r[0] for r in cur.fetchall()}
                except Exception as exc:
                    logger.warning("rumor_backfill dedup miss: %s", exc)
                    return {**counts, "posts_seen": len(posts)}
            for post in posts:
                raw_text = post.get("raw_message_text") or ""
                if not str(raw_text).strip():
                    counts["skipped_empty"] += 1
                    continue
                chunk_id = f"tg:{post.get('id')}"
                if chunk_id in existing:
                    counts["skipped_dup"] += 1
                    continue
                text = str(raw_text)
                ocr = post.get("ocr_extracted_text") or ""
                if str(ocr).strip():
                    text = f"{text} | OCR: {ocr}"
                text = text[:_MAX_TEXT_LEN]
                ts = post.get("post_timestamp") or ""
                doc_date = str(ts)[:10]
                conn.execute(
                    "INSERT INTO intelligence_fts "
                    "(chunk_id, symbol, isin, source_type, document_date, document_text) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (chunk_id, _first_symbol(post.get("detected_symbols_json")), "",
                     _SOURCE_TYPE, doc_date, text),
                )
                existing.add(chunk_id)
                counts["chunks_written"] += 1
    except Exception as exc:  # fail-closed: miss -> counts so far, never raise
        logger.warning("rumor_backfill miss: %s", exc)
    return counts
