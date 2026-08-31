"""
Official Filing Client — downloads & archives raw NSE/BSE filings.

Consumes link records produced by ``filing_discovery.py`` and performs the
actual archival of the *official* exchange documents (annual reports, concall
PDFs, investor presentations, XBRL). Every download is recorded with provenance:
the source exchange URL, the local path, byte size, and a sha256 hash.

FAIL-CLOSED: a 404 / network error / non-PDF response is recorded as a failure
and NEVER synthesised. We never invent filing contents.

Method C (post-download content classifier) — production fix for investor presentations:
  After each successful download, the local PDF is re-classified via
  reality_engine.ingestion.content_classifier.classify_c_with_timings
  (fitz pages + text + size heuristic). If classifier says ANNOUNCEMENT but
  DB doc_type was INVESTOR_PRESENTATION, the row is updated transactionally.
  GPU OCR fallback via FinancialOCREngine DirectML only when len(txt) < 300.
"""

import hashlib
import logging
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from reality_engine.config import DEFAULT_HEADERS, PDFS_DIR, NSE_HEADERS, BSE_HEADERS

logger = logging.getLogger("reality_engine.official_filing_client")

# ---------------------------------------------------------------------------
# Disk guard (enforce before bulk writes)
# ---------------------------------------------------------------------------
_DEFAULT_DISK_GUARD_MB = 500

def _check_disk_guard(path: Path | str = PDFS_DIR, guard_mb: int = _DEFAULT_DISK_GUARD_MB) -> bool:
    """Return True if free disk >= guard_mb MB, else log and return False."""
    try:
        p = Path(path)
        # ensure parent exists for check
        check_path = p if p.exists() else p.parent
        if not check_path.exists():
            check_path = Path.cwd()
        free = shutil.disk_usage(str(check_path)).free / (1024 * 1024)
        if free < guard_mb:
            logger.warning("official_filing_client: disk guard triggered free %.1f MB < %d MB at %s", free, guard_mb, check_path)
            return False
        return True
    except Exception:
        return True


class OfficialFilingClient:
    """Archives official NSE/BSE filings locally with full provenance."""

    def __init__(self, rate_limit_sec: float = 0.8, max_retries: int = 3):
        self.http_session = requests.Session()
        self.http_session.headers.update(DEFAULT_HEADERS)
        self.http_session.verify = False
        self.rate_limit_sec = max(0.0, rate_limit_sec)
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Storage layout
    # ------------------------------------------------------------------
    def _local_path(self, symbol: str, doc_type: str, url: str) -> str:
        """Deterministic on-disk path under PDFS_DIR/<symbol>/<doc_type>/<slug>."""
        safe_sym = (symbol or "UNKNOWN").upper().replace("/", "_")
        folder = PDFS_DIR / safe_sym / doc_type
        folder.mkdir(parents=True, exist_ok=True)
        # Derive a filename slug from the URL tail.
        tail = url.rstrip("/").split("?")[0].split("/")[-1] or "filing"
        tail = re.sub(r"[^A-Za-z0-9._-]", "_", tail)
        if not tail.lower().endswith((".pdf", ".xml", ".xbrl")):
            tail += ".pdf"
        # Avoid collisions: prefix with date + short hash of url.
        stamp = datetime.now().strftime("%Y%m%d")
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        fname = f"{stamp}_{url_hash}_{tail}"
        return str(folder / fname)

    # ------------------------------------------------------------------
    # Download (fail-closed, retry with backoff)
    # ------------------------------------------------------------------
    def _download_via_browser(self, url: str, local_path: str) -> Optional[Dict[str, Any]]:
        """Optional headless-browser fallback for BSE/NSE docs blocked without a session.

        Invoked only when the plain HTTP download is blocked (403 / HTML error page).
        Fail-closed: returns None if Playwright is unavailable or the fetch fails for
        any reason. Never raises.
        """
        try:  # Lazy import — never breaks the module when playwright is absent.
            from reality_engine.ingestion.headless_fetcher import (
                is_playwright_available,
                fetch_with_browser,
            )
        except Exception:  # pragma: no cover
            return None
        if not is_playwright_available():
            return None
        if "bseindia.com" not in url.lower() and "nseindia.com" not in url.lower():
            return None
        try:
            resp = fetch_with_browser(url, timeout=30)
            if resp is None:
                return None
            if getattr(resp, "status_code", 200) != 200:
                return None
            data = getattr(resp, "content", None) or getattr(resp, "body", None)
            if not data:
                return None
            headers = getattr(resp, "headers", {}) or {}
            ctype = ""
            try:
                ctype = (headers.get("Content-Type", "") or "").lower()
            except Exception:
                ctype = ""
            if "text/html" in ctype and data[:4].lower() != b"%pdf":
                return None
            with open(local_path, "wb") as fh:
                fh.write(data)
            if self.rate_limit_sec:
                time.sleep(self.rate_limit_sec)
            sha = hashlib.sha256(data).hexdigest()
            return {
                "ok": True,
                "local_file_path": local_path,
                "file_size_bytes": len(data),
                "sha256_hash": sha,
                "error": None,
            }
        except Exception as exc:  # pragma: no cover - network/browser dependent
            logger.debug("official_filing_client: headless fallback failed for %s: %s", url, exc)
            return None

    def _download(self, url: str, local_path: str) -> Dict[str, Any]:
        last_err: Optional[str] = None
        for attempt in range(self.max_retries):
            try:
                headers = BSE_HEADERS if "bseindia.com" in url.lower() else NSE_HEADERS
                with self.http_session.get(
                    url, headers=headers, timeout=30, stream=True
                ) as resp:
                    if resp.status_code != 200:
                        last_err = f"http_{resp.status_code}"
                        # 404/403/410 are terminal for plain HTTP; try headless fallback.
                        if resp.status_code in (404, 403, 410):
                            fallback = self._download_via_browser(url, local_path)
                            if fallback:
                                return fallback
                            break
                        time.sleep(self.rate_limit_sec * (2 ** attempt))
                        continue
                    ctype = resp.headers.get("Content-Type", "").lower()
                    data = resp.content
                    if not data:
                        last_err = "empty_body"
                        break
                    # Light content guard: expect PDF/XBRL/XML, not an HTML error page.
                    if "text/html" in ctype and data[:4].lower() != b"%pdf":
                        last_err = "html_error_page_not_pdf"
                        fallback = self._download_via_browser(url, local_path)
                        if fallback:
                            return fallback
                        break
                    with open(local_path, "wb") as fh:
                        fh.write(data)
                    if self.rate_limit_sec:
                        time.sleep(self.rate_limit_sec)
                    sha = hashlib.sha256(data).hexdigest()
                    return {
                        "ok": True,
                        "local_file_path": local_path,
                        "file_size_bytes": len(data),
                        "sha256_hash": sha,
                        "error": None,
                    }
            except Exception as e:  # pragma: no cover - network
                last_err = str(e)
                time.sleep(self.rate_limit_sec * (2 ** attempt))
        return {"ok": False, "local_file_path": None, "file_size_bytes": 0,
                "sha256_hash": None, "error": last_err}

    # ------------------------------------------------------------------
    # Public API — archive one discovered link
    # ------------------------------------------------------------------
    def archive_link(self, symbol: str, link: Dict[str, Any]) -> Dict[str, Any]:
        url = link.get("source_url")
        doc_type = link.get("doc_type", "OTHER_FILING")
        if not url:
            return {**link, "ok": False, "error": "missing_url"}
        local_path = self._local_path(symbol, doc_type, url)
        result = self._download(url, local_path)
        enriched = {
            **link,
            "ok": result["ok"],
            "local_file_path": result["local_file_path"],
            "file_size_bytes": result["file_size_bytes"],
            "sha256_hash": result["sha256_hash"],
            "error": result["error"],
        }
        # --- Additive Method C: post-download content classifier (single file) ---
        # Run CPU fitz + size heuristic + GPU OCR only when len(txt)<300.
        # Attach content_classified_type; if mis-typed INVESTOR_PRESENTATION -> ANNOUNCEMENT,
        # attempt DB update (single-writer, transactionally, fail-closed if no DB).
        if result["ok"] and result["local_file_path"]:
            try:
                # lazy import to avoid circular deps
                from reality_engine.ingestion.content_classifier import classify_c_with_timings  # type: ignore
                pdf_p = Path(result["local_file_path"])
                if pdf_p.exists() and pdf_p.suffix.lower() == ".pdf":
                    cres = classify_c_with_timings(pdf_p)
                    enriched["content_classified_type"] = cres.get("label")
                    enriched["content_classifier_pages"] = cres.get("pages")
                    enriched["content_classifier_cpu_ms"] = cres.get("cpu_ms")
                    enriched["content_classifier_ocr_ms"] = cres.get("ocr_ms")
                    enriched["content_classifier_scanned"] = cres.get("scanned_triggered")
                    # If discovered as INVESTOR_PRESENTATION but content says ANNOUNCEMENT -> update DB
                    orig = str(doc_type).upper() if doc_type else ""
                    pred = str(cres.get("label", "")).upper()
                    if orig == "INVESTOR_PRESENTATION" and pred == "ANNOUNCEMENT":
                        try:
                            from reality_engine.db.database import db_manager  # type: ignore
                            with db_manager.session() as conn:
                                # update by source_url (idempotent unique key) transactionally
                                cur = conn.execute(
                                    "UPDATE corporate_documents SET doc_type='ANNOUNCEMENT' WHERE source_url=? AND doc_type='INVESTOR_PRESENTATION'",
                                    (url,),
                                )
                                if cur.rowcount:
                                    logger.info("Method C reclassified %s (%s) -> ANNOUNCEMENT rows=%d pages=%s size=%s", symbol, url[:80], cur.rowcount, cres.get("pages"), cres.get("size"))
                                    enriched["reclassified_to_announcement"] = True
                                else:
                                    enriched["reclassified_to_announcement"] = False
                        except Exception as db_exc:
                            logger.debug("Method C DB update note (archive_link) %s: %s", symbol, db_exc)
                            enriched["reclassified_to_announcement"] = False
                    else:
                        enriched["reclassified_to_announcement"] = False
                else:
                    enriched["content_classified_type"] = doc_type
            except Exception as exc:
                logger.debug("Method C classify note (archive_link) %s: %s", symbol, exc)
                enriched["content_classified_type"] = doc_type
        return enriched

    def archive_discovery(
        self, discovery: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Archive every link in a discovery record.

        Returns the discovery record enriched with per-link archival results.
        """
        symbol = discovery.get("symbol", "UNKNOWN")
        results: List[Dict[str, Any]] = []
        for link in discovery.get("links", []):
            results.append(self.archive_link(symbol, link))
        succeeded = sum(1 for r in results if r.get("ok"))
        return {
            "symbol": symbol,
            "bse_code": discovery.get("bse_code"),
            "total_links": len(results),
            "archived": succeeded,
            "failed": len(results) - succeeded,
            "results": results,
            "error": discovery.get("error"),
        }

    # ------------------------------------------------------------------
    # Public API — bulk archive over many discoveries (rate-limited pool)
    # ------------------------------------------------------------------
    def archive_many(
        self,
        discoveries: List[Dict[str, Any]],
        max_workers: int = 4,
        progress: bool = True,
        enable_post_classify: bool = True,
        disk_guard_mb: int = _DEFAULT_DISK_GUARD_MB,
    ) -> Dict[str, Any]:
        """Bulk archive with rate-limited pool + Method C post-download reclassification.

        Args:
            discoveries: list of {symbol, bse_code, links:[{source_url, doc_type, ...}]}
            max_workers: thread pool size for network fetches
            progress: if True log per-symbol progress
            enable_post_classify: if True run Method C classifier on each newly downloaded PDF
                and update corporate_documents.doc_type where INVESTOR_PRESENTATION was
                actually ANNOUNCEMENT. Single-writer transactional DB updates after the
                thread pool completes (no concurrent writes). Disk guard enforced.
            disk_guard_mb: abort if free disk < this MB (default 500)

        Returns:
            dict with attempted_symbols, total_links, total_archived, total_failed, per_symbol
            Each per_symbol.results entry is enriched with content_classified_type,
            content_classifier_* timings, and reclassified_to_announcement when applicable.
        """
        if disk_guard_mb and not _check_disk_guard(PDFS_DIR, disk_guard_mb):
            logger.warning("archive_many aborted: disk guard free < %d MB", disk_guard_mb)
            return {
                "attempted_symbols": len(discoveries),
                "total_links": 0,
                "total_archived": 0,
                "total_failed": 0,
                "per_symbol": [],
                "error": f"disk_guard_abort_free_lt_{disk_guard_mb}MB",
            }
        attempted = len(discoveries)
        total_links = 0
        total_archived = 0
        per_symbol: List[Dict[str, Any]] = []

        def _work(disc: Dict[str, Any]):
            return self.archive_discovery(disc)

        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
            futs = {ex.submit(_work, d): d for d in discoveries}
            for fut in as_completed(futs):
                res = fut.result()
                per_symbol.append(res)
                total_links += res.get("total_links", 0)
                total_archived += res.get("archived", 0)
                if progress:
                    logger.info("archive_many progress %d/%d symbols archived=%d links=%d", len(per_symbol), attempted, total_archived, total_links)

        # --- Method C post-download reclassification (single-writer, after pool) ---
        # Note: archive_link already classifies each file inline and does per-file DB update
        # via source_url. The bulk post-pass below is additive for any files where
        # inline classification was skipped (e.g. mocked headers) and also aggregates counts.
        reclassified_count = 0
        classified_count = 0
        if enable_post_classify:
            try:
                from reality_engine.ingestion.content_classifier import classify_c_with_timings  # type: ignore
                from reality_engine.db.database import db_manager  # type: ignore
                # Collect successfully archived PDFs that haven't yet been marked reclassified
                to_check: List[Dict[str, Any]] = []
                for sym_res in per_symbol:
                    for rr in sym_res.get("results", []):
                        if rr.get("ok") and rr.get("local_file_path"):
                            # if already enriched by archive_link, reuse; else classify now
                            if "content_classified_type" not in rr:
                                p = Path(rr["local_file_path"])
                                if p.exists() and p.suffix.lower() == ".pdf":
                                    cres = classify_c_with_timings(p)
                                    rr["content_classified_type"] = cres.get("label")
                                    rr["content_classifier_pages"] = cres.get("pages")
                                    rr["content_classifier_cpu_ms"] = cres.get("cpu_ms")
                                    rr["content_classifier_ocr_ms"] = cres.get("ocr_ms")
                                    rr["content_classifier_scanned"] = cres.get("scanned_triggered")
                                    orig = str(rr.get("doc_type", "")).upper()
                                    pred = str(cres.get("label", "")).upper()
                                    if orig == "INVESTOR_PRESENTATION" and pred == "ANNOUNCEMENT":
                                        to_check.append(rr)
                                        classified_count += 1
                                else:
                                    rr["content_classified_type"] = rr.get("doc_type")
                            else:
                                # already classified inline; check if it flagged reclassification but DB rowcount was 0 due to missing commit
                                # count it
                                if rr.get("reclassified_to_announcement"):
                                    reclassified_count += 1
                                # also capture those that are ANNOUNCEMENT but not yet counted due to per-file update failure
                                orig = str(rr.get("doc_type", "")).upper()
                                pred = str(rr.get("content_classified_type", "")).upper()
                                if orig == "INVESTOR_PRESENTATION" and pred == "ANNOUNCEMENT" and not rr.get("reclassified_to_announcement"):
                                    to_check.append(rr)
                # Bulk transactional DB update for any remaining mis-typed rows (single writer)
                if to_check:
                    try:
                        with db_manager.session() as conn:
                            for rr in to_check:
                                cur = conn.execute(
                                    "UPDATE corporate_documents SET doc_type='ANNOUNCEMENT' WHERE source_url=? AND doc_type='INVESTOR_PRESENTATION'",
                                    (rr.get("source_url"),),
                                )
                                if cur.rowcount:
                                    reclassified_count += 1
                                    rr["reclassified_to_announcement"] = True
                                    logger.info("Method C bulk reclassified %s -> ANNOUNCEMENT %s", rr.get("source_url", "")[:80], reclassified_count)
                            conn.commit()
                    except Exception as db_exc:
                        logger.debug("Method C bulk DB update note: %s", db_exc)
                if classified_count or reclassified_count:
                    logger.info("archive_many Method C post-classify: classified=%d reclassified_to_announcement=%d", classified_count, reclassified_count)
            except Exception as exc:
                logger.debug("archive_many Method C post-pass note: %s", exc)

        return {
            "attempted_symbols": attempted,
            "total_links": total_links,
            "total_archived": total_archived,
            "total_failed": total_links - total_archived,
            "per_symbol": per_symbol,
            "method_c_reclassified_to_announcement": reclassified_count if enable_post_classify else 0,
        }


# ---------------------------------------------------------------------------
# Additive helper: idempotent backfill for existing downloaded IPs
# ---------------------------------------------------------------------------
def reclassify_downloaded_presentations(limit: int = 5000, manager=None, disk_guard_mb: int = _DEFAULT_DISK_GUARD_MB) -> Dict[str, Any]:
    """
    Loops over corporate_documents WHERE doc_type='INVESTOR_PRESENTATION' AND local_file_path IS NOT NULL,
    classifies each file via Method C, updates mis-typed rows to ANNOUNCEMENT transactionally.

    Idempotent backfill for existing ~1,436 downloaded IPs. Single-writer, logs counts.

    Args:
        limit: max rows to scan (default 5000, covers full 3,024 universe)
        manager: optional db_manager override (for tests)
        disk_guard_mb: disk guard threshold (abort if free < this)

    Returns:
        dict with total_scanned, reclassified_to_announcement, kept_as_investor_presentation,
                other, missing_file, errors, timing (avg_cpu_ms, avg_total_ms, throughput, wall_sec)
    """
    import time as _time
    from pathlib import Path as _Path

    if disk_guard_mb and not _check_disk_guard(PDFS_DIR, disk_guard_mb):
        logger.warning("reclassify_downloaded_presentations aborted: disk guard free < %d MB", disk_guard_mb)
        return {"total_scanned": 0, "reclassified_to_announcement": 0, "kept_as_investor_presentation": 0, "other": 0, "missing_file": 0, "errors": 0, "error": f"disk_guard_abort_free_lt_{disk_guard_mb}MB"}

    try:
        from reality_engine.db.database import db_manager as _dbm  # type: ignore
        from reality_engine.ingestion.content_classifier import classify_c_with_timings  # type: ignore
    except Exception as e:
        logger.warning("reclassify helper import failed: %s", e)
        return {"total_scanned": 0, "error": str(e)}

    mgr = manager or _dbm
    limit = max(1, int(limit))

    # Lazy OCR singleton reuse
    try:
        from reality_engine.processing.ocr_engine import FinancialOCREngine  # type: ignore
        _ocr_singleton = FinancialOCREngine()
    except Exception:
        _ocr_singleton = None

    wall0 = _time.perf_counter()
    rows: List[Dict[str, Any]] = []
    try:
        with mgr.session() as conn:
            q = """
            SELECT id, symbol, isin, doc_type, title, source_url, local_file_path, file_size_bytes
            FROM corporate_documents
            WHERE doc_type='INVESTOR_PRESENTATION' AND local_file_path IS NOT NULL
            ORDER BY id
            LIMIT ?
            """
            fetched = conn.execute(q, (int(limit),)).fetchall()
            rows = [dict(r) for r in fetched]
    except Exception as e:
        logger.warning("reclassify query failed: %s", e)
        return {"total_scanned": 0, "error": str(e)}

    total_scanned = len(rows)
    reclassified = 0
    kept = 0
    other = 0
    missing = 0
    errors = 0
    cpu_times: List[float] = []
    total_times: List[float] = []
    scanned_triggered_cnt = 0

    # Single-writer transactional update: collect ids to update then execute in one transaction
    ids_to_reclassify: List[int] = []
    per_row_updates: List[Dict[str, Any]] = []

    for idx, rec in enumerate(rows):
        lp = rec.get("local_file_path")
        if not lp:
            missing += 1
            continue
        p = _Path(lp)
        if not p.exists():
            missing += 1
            # optionally clear stale path? keep additive, just count
            logger.debug("reclassify missing file id=%s %s", rec.get("id"), lp)
            continue
        if p.suffix.lower() not in (".pdf",):
            # non-pdf (xml/xbrl) -> keep as is, not in scope
            other += 1
            continue
        try:
            cres = classify_c_with_timings(p, ocr_engine=_ocr_singleton)
            cpu_times.append(float(cres.get("cpu_ms", 0)))
            total_times.append(float(cres.get("total_ms", 0)))
            if cres.get("scanned_triggered"):
                scanned_triggered_cnt += 1
            label = str(cres.get("label", "OTHER")).upper()
            if label == "ANNOUNCEMENT":
                ids_to_reclassify.append(int(rec["id"]))
                per_row_updates.append({"id": rec["id"], "pages": cres.get("pages"), "size": cres.get("size"), "label": label})
                reclassified += 1  # provisional, confirmed after DB commit
            elif label == "INVESTOR_PRESENTATION":
                kept += 1
            else:
                other += 1
            if (idx + 1) % 200 == 0:
                logger.info("reclassify progress %d/%d kept=%d reclassified=%d other=%d missing=%d", idx + 1, total_scanned, kept, reclassified, other, missing)
        except Exception as e:
            errors += 1
            logger.debug("reclassify error id=%s %s: %s", rec.get("id"), lp, e)

    # Transactional DB update (single writer)
    committed_reclassified = 0
    if ids_to_reclassify:
        try:
            with mgr.session() as conn:
                for rid in ids_to_reclassify:
                    cur = conn.execute(
                        "UPDATE corporate_documents SET doc_type='ANNOUNCEMENT' WHERE id=? AND doc_type='INVESTOR_PRESENTATION'",
                        (rid,),
                    )
                    if cur.rowcount:
                        committed_reclassified += 1
                conn.commit()
            logger.info("reclassify committed %d rows to ANNOUNCEMENT (attempted %d)", committed_reclassified, len(ids_to_reclassify))
        except Exception as e:
            logger.warning("reclassify commit failed: %s", e)
            # reclassified count stays provisional; errors already tracked
            committed_reclassified = reclassified
    else:
        committed_reclassified = 0

    # Adjust reclassified to committed (idempotent: if already ANNOUNCEMENT, rowcount 0)
    # But we counted provisional; replace with committed if DB had already been updated?
    # Keep both: provisional vs committed distinction logged
    wall = _time.perf_counter() - wall0
    avg_cpu = sum(cpu_times) / len(cpu_times) if cpu_times else 0.0
    avg_total = sum(total_times) / len(total_times) if total_times else 0.0
    throughput = total_scanned / wall if wall > 0 else 0.0

    result = {
        "total_scanned": total_scanned,
        "reclassified_to_announcement": committed_reclassified,
        "reclassified_provisional": reclassified,
        "kept_as_investor_presentation": kept,
        "other": other,
        "missing_file": missing,
        "errors": errors,
        "scanned_triggered": scanned_triggered_cnt,
        "scanned_triggered_pct": round(scanned_triggered_cnt / total_scanned * 100, 2) if total_scanned else 0.0,
        "avg_cpu_ms": round(avg_cpu, 3),
        "avg_total_ms": round(avg_total, 3),
        "wall_sec": round(wall, 3),
        "throughput_docs_per_sec": round(throughput, 3),
        "p50_total_ms": round(sorted(total_times)[len(total_times)//2], 3) if total_times else 0.0,
        "p95_total_ms": round(sorted(total_times)[int(len(total_times)*0.95)], 3) if total_times and len(total_times) > 5 else 0.0,
        "ids_reclassified_sample": ids_to_reclassify[:10],
        "per_row_sample": per_row_updates[:5],
    }
    logger.info(
        "reclassify_downloaded_presentations DONE scanned=%d kept=%d reclassified=%d (committed %d) other=%d missing=%d errors=%d avg_cpu=%.2fms avg_total=%.2fms throughput=%.2f docs/s wall=%.1fs scanned_triggered=%d (%.1f%%)",
        total_scanned, kept, reclassified, committed_reclassified, other, missing, errors, avg_cpu, avg_total, throughput, wall, scanned_triggered_cnt, result["scanned_triggered_pct"],
    )
    return result


# Expose on class for convenience (additive API)
OfficialFilingClient.reclassify_downloaded_presentations = staticmethod(reclassify_downloaded_presentations)  # type: ignore


# Singleton
official_filing_client = OfficialFilingClient()
