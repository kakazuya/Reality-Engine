"""News retention — "extract the info, then delete the papers" (fail-closed).

Daily broad-market news is ingested as ``raw_documents`` rows (``source_type``
``news_<outlet>``) plus one ``intelligence_fts`` chunk per ingested article. The
FTS chunk *is* the extracted information; the ``raw_documents`` row (and, when
present, its cached ``local_file_path`` artifact) is the paper. Retention is
therefore gated on extraction proof:

    no FTS chunk for this document  ->  the row is KEPT (never deleted).

Contract
--------
* ``NEWS_SOURCE_PREFIXES`` — only ``LOWER(source_type) LIKE 'news_%'`` rows are
  ever considered. Every other source (PIB/RBI/filings/...) is out of scope.
* Candidates are news rows with ``published_date < cutoff`` (ISO-8601 string
  compare) and ``COALESCE(is_structural_milestone, 0) = 0``.
* Structural-milestone news rows are counted as ``skipped_structural`` and are
  never deleted.
* ``dry_run=True`` (the default) counts everything and deletes nothing: the
  ``raw_deleted`` / ``fts_deleted`` / ``files_deleted`` keys then report
  *would-delete* counts.
* Every row runs in its own try/except; failures are collected in ``errors``
  and never raise out of the function. Any failure to *prove* extraction keeps
  the row.
* File deletion, when requested, is only performed for an existing
  ``local_file_path`` that resolves inside this repo's data directory. A path
  that escapes the data dir is refused (no unlink) and recorded as an error —
  the DB row is still pruned, because extraction proof exists; only the file
  gate refuses. The unlink always happens *after* the DB delete succeeded.

Usage:
    from reality_engine.pipeline.news_retention import prune_news
    prune_news(before_days=30, dry_run=True)            # report only
    prune_news(before_days=30, dry_run=False)           # delete DB rows
    prune_news(before_days=30, dry_run=False, delete_files=True)
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from reality_engine.config import DATA_DIR

logger = logging.getLogger("reality_engine.pipeline.news_retention")

# Only these source_type prefixes are in scope for news retention.
NEWS_SOURCE_PREFIXES = ("news_",)

DEFAULT_BEFORE_DAYS = 30

# LIKE escape char for the prefix/proof patterns ('_' and '%' are wildcards).
_LIKE_ESCAPE = "\\"


def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters so a literal ``news_`` prefix matches literally."""
    out = str(value or "")
    for ch in (_LIKE_ESCAPE, "%", "_"):
        out = out.replace(ch, _LIKE_ESCAPE + ch)
    return out


# ---------------------------------------------------------------------------
# DB plumbing (DatabaseManager / Repository both expose session(); never raises)
# ---------------------------------------------------------------------------

def _resolve_session_factory(db: Any):
    """Return a callable producing a session context manager for ``db``.

    ``db=None`` uses the live ``DatabaseManager`` (config.DB_PATH). A Repository
    (or any wrapper exposing ``.db``) is unwrapped to its manager.
    """
    target = db
    if target is None:
        from reality_engine.db.database import DatabaseManager
        target = DatabaseManager()
    if hasattr(target, "session"):
        return target.session
    inner = getattr(target, "db", None)
    if inner is not None and hasattr(inner, "session"):
        return inner.session
    raise TypeError(f"db object has no session(): {type(target).__name__}")


def _table_exists(conn, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE (type='table' OR type='view') AND name=?",
            (name,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _column_exists(conn, table: str, column: str) -> bool:
    try:
        return column in {r[1] for r in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}
    except Exception:
        return False


def _ensure_schema(conn) -> None:
    """Additive, idempotent: raw_documents.is_structural_milestone (Wave C flag).

    Best-effort — a backend that cannot ALTER simply keeps the COALESCE default.
    """
    if _table_exists(conn, "raw_documents") and not _column_exists(
        conn, "raw_documents", "is_structural_milestone"
    ):
        try:
            conn.execute(
                "ALTER TABLE raw_documents ADD COLUMN is_structural_milestone INTEGER DEFAULT 0"
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("could not add raw_documents.is_structural_milestone: %s", exc)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _cutoff_iso(before_days: int) -> str:
    return (dt.date.today() - dt.timedelta(days=int(before_days))).isoformat()


def _news_prefix_clause() -> str:
    """SQL fragment: LOWER(source_type) starts with a literal 'news_' prefix."""
    likes = " OR ".join(
        f"LOWER(COALESCE(source_type,'')) LIKE ? ESCAPE '{_LIKE_ESCAPE}'"
        for _ in NEWS_SOURCE_PREFIXES
    )
    return f"({likes})"


def _news_prefix_params() -> List[str]:
    return [f"{_escape_like(p)}%" for p in NEWS_SOURCE_PREFIXES]


def _fetch_candidates(conn, cutoff: str) -> List[Any]:
    sql = (
        "SELECT doc_id, source_type, published_date, source_url, local_file_path "
        "FROM raw_documents "
        f"WHERE {_news_prefix_clause()} "
        "  AND COALESCE(published_date,'') < ? "
        "  AND COALESCE(is_structural_milestone,0) = 0 "
        "ORDER BY published_date ASC, doc_id ASC"
    )
    return conn.execute(sql, (*_news_prefix_params(), cutoff)).fetchall()


def _count_structural(conn, cutoff: str) -> int:
    sql = (
        "SELECT COUNT(*) FROM raw_documents "
        f"WHERE {_news_prefix_clause()} "
        "  AND COALESCE(published_date,'') < ? "
        "  AND COALESCE(is_structural_milestone,0) <> 0"
    )
    row = conn.execute(sql, (*_news_prefix_params(), cutoff)).fetchone()
    return int(row[0]) if row else 0


def _chunk_patterns(source_type: Optional[str], doc_id: Any) -> List[str]:
    """intelligence_fts.chunk_id shapes proving this document was extracted.

    Canonical write is ``f"{source_type}:{doc_id}:0"`` (one chunk per article);
    a bare ``f"{source_type}:{doc_id}"`` is accepted as a direct doc_id match.
    """
    st = _escape_like(source_type or "")
    did = _escape_like(str(doc_id))
    return [f"{st}:{did}:%", f"{st}:{did}"]


def _extraction_chunk_count(conn, source_type: Optional[str], doc_id: Any) -> int:
    like_pat, exact_pat = _chunk_patterns(source_type, doc_id)
    row = conn.execute(
        f"SELECT COUNT(*) FROM intelligence_fts "
        f"WHERE chunk_id LIKE ? ESCAPE '{_LIKE_ESCAPE}' OR chunk_id = ?",
        (like_pat, exact_pat),
    ).fetchone()
    return int(row[0]) if row else 0


def _delete_chunks(conn, source_type: Optional[str], doc_id: Any) -> int:
    before = _extraction_chunk_count(conn, source_type, doc_id)
    if before:
        like_pat, exact_pat = _chunk_patterns(source_type, doc_id)
        conn.execute(
            f"DELETE FROM intelligence_fts "
            f"WHERE chunk_id LIKE ? ESCAPE '{_LIKE_ESCAPE}' OR chunk_id = ?",
            (like_pat, exact_pat),
        )
    return before


# ---------------------------------------------------------------------------
# File gate
# ---------------------------------------------------------------------------

def _resolve_under_data_dir(raw_path: Any):
    """Resolve ``raw_path`` and decide whether it is safely inside the data dir.

    Returns ``(path, status)`` with status in
    ``{"absent", "outside", "missing", "ok", "error"}``.
    """
    if raw_path is None:
        return None, "absent"
    text = str(raw_path).strip()
    if not text:
        return None, "absent"
    try:
        data_dir = Path(DATA_DIR).resolve()
        path = Path(text)
        if not path.is_absolute():
            path = (Path.cwd() / path)
        resolved = path.resolve()
    except Exception as exc:
        logger.warning("unresolvable local_file_path %r: %s", raw_path, exc)
        return None, "error"
    if resolved != data_dir and data_dir not in resolved.parents:
        return resolved, "outside"
    if not resolved.exists():
        return resolved, "missing"
    if resolved.is_dir():
        return resolved, "error"
    return resolved, "ok"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def prune_news(before_days: int = DEFAULT_BEFORE_DAYS, dry_run: bool = True,
               delete_files: bool = False, db: Any = None) -> Dict[str, Any]:
    """Prune extracted news documents older than ``before_days``. Never raises.

    Returns a dict with keys: ``cutoff``, ``candidates``, ``raw_deleted``,
    ``fts_deleted``, ``files_deleted``, ``skipped_unextracted``,
    ``skipped_structural``, ``errors``.

    Extraction proof = an ``intelligence_fts`` chunk whose ``chunk_id`` is
    ``f"{source_type}:{doc_id}:..."`` (or exactly ``f"{source_type}:{doc_id}"``).
    Without proof the row is kept and counted in ``skipped_unextracted``.
    With ``dry_run=True`` nothing is deleted and the delete-count keys report
    what *would* happen.
    """
    counts: Dict[str, Any] = {
        "cutoff": None,
        "candidates": 0,
        "raw_deleted": 0,
        "fts_deleted": 0,
        "files_deleted": 0,
        "skipped_unextracted": 0,
        "skipped_structural": 0,
        "errors": [],
    }
    errors: List[str] = counts["errors"]

    try:
        cutoff = _cutoff_iso(before_days)
    except Exception as exc:
        errors.append(f"invalid before_days={before_days!r}: {exc}")
        return counts
    counts["cutoff"] = cutoff

    try:
        session_factory = _resolve_session_factory(db)
    except Exception as exc:
        logger.warning("news retention: no DB session (%s)", exc)
        errors.append(f"no DB session: {exc}")
        return counts

    # --- read phase -------------------------------------------------------
    try:
        with session_factory() as conn:
            _ensure_schema(conn)
            if not _table_exists(conn, "raw_documents"):
                errors.append("raw_documents table missing; nothing pruned")
                logger.warning("news retention: raw_documents table missing")
                return counts
            if not _table_exists(conn, "intelligence_fts"):
                errors.append("intelligence_fts missing; no extraction proof possible")
                logger.warning("news retention: intelligence_fts missing; keeping all rows")
                return counts
            candidates = _fetch_candidates(conn, cutoff)
            counts["skipped_structural"] = _count_structural(conn, cutoff)
    except Exception as exc:
        logger.warning("news retention: candidate scan failed: %s", exc)
        errors.append(f"candidate scan failed: {exc}")
        return counts

    counts["candidates"] = len(candidates)
    if not candidates:
        logger.info("news retention: no candidates before %s", cutoff)
        return counts

    # --- mutation phase (per-row isolation; nothing raises) ---------------
    for row in candidates:
        try:
            doc_id = row["doc_id"]
            source_type = row["source_type"]
        except Exception as exc:
            errors.append(f"unreadable candidate row: {exc}")
            continue

        try:
            with session_factory() as conn:
                # 1. Extraction proof. Absent or unprovable -> KEEP the row.
                try:
                    chunk_count = _extraction_chunk_count(conn, source_type, doc_id)
                except Exception as exc:
                    counts["skipped_unextracted"] += 1
                    errors.append(
                        f"doc_id={doc_id}: extraction proof query failed ({exc}); row kept"
                    )
                    continue
                if chunk_count <= 0:
                    counts["skipped_unextracted"] += 1
                    logger.info(
                        "news retention: doc_id=%s (%s) has no FTS chunk; kept",
                        doc_id, source_type,
                    )
                    continue

                # 2. File gate (evaluated before the unlink; the DB row is still
                #    pruned because extraction is proven — only the file is refused).
                file_path = None
                if delete_files:
                    file_path, status = _resolve_under_data_dir(row["local_file_path"])
                    if status == "outside":
                        errors.append(
                            f"doc_id={doc_id}: local_file_path outside data dir, "
                            f"not deleted: {file_path}"
                        )
                        file_path = None
                    elif status == "error":
                        errors.append(
                            f"doc_id={doc_id}: unusable local_file_path, not deleted: "
                            f"{row['local_file_path']!r}"
                        )
                        file_path = None
                    elif status == "missing":
                        logger.info(
                            "news retention: doc_id=%s local file already gone: %s",
                            doc_id, file_path,
                        )
                        file_path = None

                if dry_run:
                    counts["raw_deleted"] += 1
                    counts["fts_deleted"] += chunk_count
                    if file_path is not None:
                        counts["files_deleted"] += 1
                    continue

                # 3. Delete chunks, then the row. Only after that, the file.
                deleted_chunks = _delete_chunks(conn, source_type, doc_id)
                conn.execute("DELETE FROM raw_documents WHERE doc_id = ?", (doc_id,))
                counts["raw_deleted"] += 1
                counts["fts_deleted"] += deleted_chunks

                if file_path is not None:
                    try:
                        file_path.unlink()
                        counts["files_deleted"] += 1
                    except FileNotFoundError:
                        logger.info(
                            "news retention: doc_id=%s file vanished before unlink: %s",
                            doc_id, file_path,
                        )
                    except Exception as exc:
                        errors.append(
                            f"doc_id={doc_id}: unlink failed for {file_path}: {exc}"
                        )
        except Exception as exc:
            errors.append(f"doc_id={doc_id}: prune failed: {exc}")
            logger.warning("news retention: doc_id=%s prune failed: %s", doc_id, exc)

    logger.info(
        "news retention%s: candidates=%d raw_deleted=%d fts_deleted=%d files=%d "
        "unextracted=%d structural=%d errors=%d",
        " (dry-run)" if dry_run else "",
        counts["candidates"], counts["raw_deleted"], counts["fts_deleted"],
        counts["files_deleted"], counts["skipped_unextracted"],
        counts["skipped_structural"], len(errors),
    )
    return counts


def news_retention_report(db: Any = None,
                          before_days: int = DEFAULT_BEFORE_DAYS) -> Dict[str, int]:
    """Count news rows split at the retention cutoff. Never raises.

    ``fresh`` = news rows at/after the cutoff, ``aged_untouched`` = news rows
    still present that are older than the cutoff (kept for lack of extraction
    proof or because they are structural milestones), ``total`` = both.
    """
    report = {"fresh": 0, "aged_untouched": 0, "total": 0}
    try:
        cutoff = _cutoff_iso(before_days)
        session_factory = _resolve_session_factory(db)
        with session_factory() as conn:
            if not _table_exists(conn, "raw_documents"):
                return report
            prefix_sql = _news_prefix_clause()
            prefix_params = _news_prefix_params()
            row = conn.execute(
                f"SELECT "
                f"  SUM(CASE WHEN COALESCE(published_date,'') >= ? THEN 1 ELSE 0 END), "
                f"  SUM(CASE WHEN COALESCE(published_date,'') <  ? THEN 1 ELSE 0 END), "
                f"  COUNT(*) "
                f"FROM raw_documents WHERE {prefix_sql}",
                (cutoff, cutoff, *prefix_params),
            ).fetchone()
            if row is not None and row[2]:
                report["fresh"] = int(row[0] or 0)
                report["aged_untouched"] = int(row[1] or 0)
                report["total"] = int(row[2] or 0)
    except Exception as exc:
        logger.warning("news retention report failed: %s", exc)
    return report


# ====================================================================
# Image (infographic) retention — the dense record survives, the bitmap does not
# ====================================================================
# A news infographic is captured by ``reality_engine.processing.news_vision`` as
# a downloaded bitmap under ``DATA_DIR/news_images/`` *plus* two dense records:
#
#   * ``intelligence_fts`` chunk ``f"{source_type}:{doc_id}:img"`` — the OCR text
#     (the information, searchable forever), and
#   * a ``news_visual_artifacts`` row — OCR text, confidence, ``media_url``.
#
# The bitmap is ~2 MB apiece (tens of images per day), so it is prunable as soon
# as those two rows exist: the OCR text keeps the numbers, and ``media_url``
# keeps the publisher-CDN URL the image is re-fetchable from. Retention here
# therefore only ever deletes *files* and clears the local pointer — the dense
# record is never deleted (unlike ``prune_news``, which prunes FTS + raw rows).
#
# ``news_visual_artifacts`` is owned by news_vision (which creates it
# idempotently); this module never creates or alters it.

# Column shape this module reads (news_vision DDL contract):
#   artifact_id, doc_id, symbol, source_type, source_url, media_url, local_path,
#   ocr_text, ocr_confidence, ocr_chars, created_at

IMAGE_CHUNK_SUFFIX = "img"


def _image_chunk_id(source_type: Optional[str], doc_id: Any) -> str:
    """The exact intelligence_fts chunk_id news_vision writes for an image."""
    return f"{source_type}:{doc_id}:{IMAGE_CHUNK_SUFFIX}"


def _image_chunk_exists(conn, source_type: Optional[str], doc_id: Any) -> bool:
    """True iff the OCR chunk for this image is present (extraction proof)."""
    row = conn.execute(
        "SELECT 1 FROM intelligence_fts WHERE chunk_id = ?",
        (_image_chunk_id(source_type, doc_id),),
    ).fetchone()
    return row is not None


def _fetch_image_candidates(conn, cutoff: str) -> List[Any]:
    """Aged ``news_visual_artifacts`` rows. Unknown (NULL) created_at is retained."""
    sql = (
        "SELECT artifact_id, doc_id, source_type, local_path "
        "FROM news_visual_artifacts "
        "WHERE created_at IS NOT NULL AND created_at < ? "
        "ORDER BY created_at ASC, artifact_id ASC"
    )
    return conn.execute(sql, (cutoff,)).fetchall()


def _clear_local_path(conn, artifact_id: Any) -> int:
    cur = conn.execute(
        "UPDATE news_visual_artifacts SET local_path = NULL WHERE artifact_id = ?",
        (artifact_id,),
    )
    return int(cur.rowcount or 0)


def prune_news_images(before_days: int = DEFAULT_BEFORE_DAYS, dry_run: bool = True,
                      delete_files: bool = False, db: Any = None) -> Dict[str, Any]:
    """Prune the *bitmaps* of aged news infographics; keep every dense record.

    Never raises. Returns a dict with keys ``cutoff``, ``candidates``,
    ``files_deleted``, ``rows_cleared``, ``skipped_no_chunk``, ``errors``.

    * ``candidates`` = ``news_visual_artifacts`` rows with
      ``created_at < cutoff`` (rows with a NULL ``created_at`` are unprovably old
      and are therefore retained).
    * Extraction proof = the OCR chunk ``f"{source_type}:{doc_id}:img"`` in
      ``intelligence_fts``. Without proof the row is kept — bitmap included — and
      counted in ``skipped_no_chunk``. The text chunk ``...:0`` is *not* proof
      for an image.
    * The bitmap is unlinked only when ``delete_files=True`` **and**
      ``local_path`` resolves inside this repo's data directory; a path that
      escapes it (or cannot be resolved) is refused, recorded in ``errors`` and
      never unlinked.
    * ``local_path`` is then cleared (``rows_cleared``); the artifact row with
      its ``ocr_text`` / ``media_url`` survives, so the image is re-fetchable
      from the publisher CDN. A failed unlink keeps the pointer so a later run
      can retry.
    * ``dry_run=True`` (the default) reports *would-delete* / *would-clear*
      counts and mutates nothing.

    Usage:
        from reality_engine.pipeline.news_retention import prune_news_images
        prune_news_images(before_days=30, dry_run=True)                     # report
        prune_news_images(before_days=30, dry_run=False, delete_files=True)
    """
    counts: Dict[str, Any] = {
        "cutoff": None,
        "candidates": 0,
        "files_deleted": 0,
        "rows_cleared": 0,
        "skipped_no_chunk": 0,
        "errors": [],
    }
    errors: List[str] = counts["errors"]

    try:
        cutoff = _cutoff_iso(before_days)
    except Exception as exc:
        errors.append(f"invalid before_days={before_days!r}: {exc}")
        return counts
    counts["cutoff"] = cutoff

    try:
        session_factory = _resolve_session_factory(db)
    except Exception as exc:
        logger.warning("news image retention: no DB session (%s)", exc)
        errors.append(f"no DB session: {exc}")
        return counts

    # --- read phase -------------------------------------------------------
    try:
        with session_factory() as conn:
            if not _table_exists(conn, "news_visual_artifacts"):
                errors.append("news_visual_artifacts table missing; nothing pruned")
                logger.warning("news image retention: news_visual_artifacts missing")
                return counts
            if not _table_exists(conn, "intelligence_fts"):
                errors.append("intelligence_fts missing; no extraction proof possible")
                logger.warning("news image retention: intelligence_fts missing; keeping all rows")
                return counts
            candidates = _fetch_image_candidates(conn, cutoff)
    except Exception as exc:
        logger.warning("news image retention: candidate scan failed: %s", exc)
        errors.append(f"candidate scan failed: {exc}")
        return counts

    counts["candidates"] = len(candidates)
    if not candidates:
        logger.info("news image retention: no candidates before %s", cutoff)
        return counts

    # --- mutation phase (per-row isolation; nothing raises) ---------------
    for row in candidates:
        try:
            artifact_id = row["artifact_id"]
            doc_id = row["doc_id"]
            source_type = row["source_type"]
        except Exception as exc:
            errors.append(f"unreadable image candidate row: {exc}")
            continue

        try:
            with session_factory() as conn:
                # 1. Extraction proof. Absent -> KEEP the row and its bitmap.
                try:
                    proven = _image_chunk_exists(conn, source_type, doc_id)
                except Exception as exc:
                    errors.append(
                        f"artifact_id={artifact_id}: extraction proof query failed "
                        f"({exc}); row kept"
                    )
                    continue
                if not proven:
                    counts["skipped_no_chunk"] += 1
                    logger.info(
                        "news image retention: artifact_id=%s doc_id=%s has no %s chunk; kept",
                        artifact_id, doc_id, _image_chunk_id(source_type, doc_id),
                    )
                    continue

                # 2. File gate (evaluated before the unlink; the pointer is still
                #    cleared because the dense record is proven — only the bitmap
                #    is refused).
                file_path = None
                clear_pointer = True
                if delete_files:
                    file_path, status = _resolve_under_data_dir(row["local_path"])
                    if status == "outside":
                        errors.append(
                            f"artifact_id={artifact_id}: local_path outside data dir, "
                            f"not deleted: {file_path}"
                        )
                        file_path = None
                    elif status == "error":
                        errors.append(
                            f"artifact_id={artifact_id}: unusable local_path, "
                            f"not deleted: {row['local_path']!r}"
                        )
                        file_path = None
                    elif status == "missing":
                        logger.info(
                            "news image retention: artifact_id=%s bitmap already gone: %s",
                            artifact_id, file_path,
                        )
                        file_path = None

                if dry_run:
                    if file_path is not None:
                        counts["files_deleted"] += 1
                    counts["rows_cleared"] += 1
                    continue

                # 3. Unlink the bitmap, then clear the pointer. A failed unlink
                #    keeps the pointer so a later run can retry the file.
                if file_path is not None:
                    try:
                        file_path.unlink()
                        counts["files_deleted"] += 1
                    except FileNotFoundError:
                        logger.info(
                            "news image retention: artifact_id=%s bitmap vanished "
                            "before unlink: %s", artifact_id, file_path,
                        )
                    except Exception as exc:
                        errors.append(
                            f"artifact_id={artifact_id}: unlink failed for {file_path}: {exc}"
                        )
                        clear_pointer = False

                if clear_pointer:
                    _clear_local_path(conn, artifact_id)
                    counts["rows_cleared"] += 1
        except Exception as exc:
            errors.append(f"artifact_id={artifact_id}: image prune failed: {exc}")
            logger.warning(
                "news image retention: artifact_id=%s prune failed: %s", artifact_id, exc
            )

    logger.info(
        "news image retention%s: candidates=%d files_deleted=%d rows_cleared=%d "
        "no_chunk=%d errors=%d",
        " (dry-run)" if dry_run else "",
        counts["candidates"], counts["files_deleted"], counts["rows_cleared"],
        counts["skipped_no_chunk"], len(errors),
    )
    return counts
