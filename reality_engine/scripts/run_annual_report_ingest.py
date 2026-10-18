"""Annual-report ingestion: turn the 26k indexed-but-never-downloaded filings into substrate.

Why this is the highest-leverage ingestion left: `corporate_documents` already
*indexes* 26,614 annual reports (all screenable-universe, 2,430 Nifty200) with
real BSE URLs — but `local_file_path` is NULL on every one of them, so none is
ingested. Meanwhile the embedded chunk corpus covers only 54 of 200 Nifty200
names (it is dominated by SME prospectuses), which is exactly why large caps like
HAL have no business-substance cross-map at all.

Annual reports are the fundamental text for already-listed companies, so this
closes both gaps at once: retrieval coverage and cross-map anchors.

Ordering: Nifty200 first, then Nifty500, then the rest, newest filing first —
so the most valuable text lands first if the run is ever cut short.

Resumable: the candidate query skips any row whose ``local_file_path`` is set, so
re-running continues where it stopped. Each row is independent: one failure never
stops the batch.

    python -m reality_engine.scripts.run_annual_report_ingest --limit 5      # trial
    python -m reality_engine.scripts.run_annual_report_ingest               # full, resumable
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine import config as cfg  # noqa: E402

LOG_PATH = cfg.DATA_DIR / "logs" / "annual_report_ingest.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("annual_report_ingest")

CANDIDATE_SQL = """
SELECT cd.id, cd.symbol, cd.isin, cd.title, cd.doc_date, cd.source_url,
       COALESCE(mc.is_nifty200, 0) AS pri200,
       COALESCE(mc.is_nifty500, 0) AS pri500
FROM corporate_documents cd
LEFT JOIN master_companies mc ON mc.isin = cd.isin
WHERE cd.doc_type = ?
  AND cd.source_url IS NOT NULL AND cd.source_url <> ''
  AND (cd.local_file_path IS NULL OR cd.local_file_path = '')
  AND cd.symbol IS NOT NULL AND cd.symbol <> ''
  AND COALESCE(cd.is_processed, 0) <> 2
  AND (? = 0 OR COALESCE(mc.is_nifty200, 0) = 1)
  AND (? = 0 OR COALESCE(mc.is_nifty50, 0) = 1)
  AND (? = '' OR COALESCE(cd.bse_dissem_ts, cd.publication_date, '') >= ?)
  AND (? = '' OR cd.isin IN (SELECT isin FROM mkt_bse_eq_daily WHERE date >= ? AND isin LIKE 'INE%'
                             UNION SELECT isin FROM daily_price_delivery WHERE date >= ? AND isin LIKE 'INE%'))
ORDER BY pri200 DESC, pri500 DESC, COALESCE(cd.bse_dissem_ts, cd.publication_date, cd.doc_date) DESC
LIMIT ?
"""


# --local-only (2026-10-18): files already downloaded (download-only runs) but never chunked; --before keeps rows filed
# before a date. The date passed on is the real filing date, never doc_date (= crawl date: the first run on 2026-10-18
# stamped 5,725 transcripts with 2026 dates; repaired by scripts/repair_transcript_dates.py) (Shivam: pre-2026 transcripts go to CPU chunks + embeddings, 2026 ones to the DeepSeek reader)
LOCAL_SQL = """
SELECT cd.id, cd.symbol, cd.isin, cd.title,
       substr(COALESCE(cd.bse_dissem_ts, cd.publication_date, cd.call_date), 1, 10) AS real_date,
       cd.source_url, cd.local_file_path
FROM corporate_documents cd
WHERE cd.doc_type = ?
  AND cd.local_file_path IS NOT NULL AND cd.local_file_path <> ''
  AND COALESCE(cd.is_processed, 0) = 0
  AND (? = '' OR COALESCE(cd.bse_dissem_ts, cd.publication_date, cd.call_date, '') < ?)
  AND COALESCE(cd.bse_dissem_ts, cd.publication_date, cd.call_date, '') <> ''
ORDER BY COALESCE(cd.bse_dissem_ts, cd.publication_date, cd.call_date) DESC
LIMIT ?
"""


def _local_only(conn_rows, doc_type, ingestor, db_manager) -> int:
    ok = failed = 0
    t0 = time.time()
    for n, (did, sym, isin, title, ddate, url, path) in enumerate(conn_rows, 1):
        try:
            if not Path(path).exists():
                failed += 1; log.warning("missing file %s %s", sym, path); continue
            res = ingestor.ingest_pdf(Path(path), title=title, source_type=doc_type, published_date=ddate,
                                      source_url=url, symbol=sym, isin=isin)
            status = (res or {}).get("status")
            if status not in ("ingested", "skipped_duplicate"):
                failed += 1; log.warning("ingest %s %s: %s %s", sym, ddate, status, str((res or {}).get("error"))[:120]); continue
            with db_manager.session() as conn:
                conn.execute("UPDATE corporate_documents SET is_processed=1 WHERE id=?", (did,))
            ok += 1
            if n % 25 == 0:
                log.info("[%d/%d] local ok=%d failed=%d (%.0fs)", n, len(conn_rows), ok, failed, time.time() - t0)
        except Exception as exc:  # noqa: BLE001
            failed += 1; log.warning("row error %s: %s", sym, str(exc)[:160])
    log.info("RUN_COMPLETE local ingested=%d failed=%d seconds=%.0f", ok, failed, time.time() - t0)
    return 0 if ok or failed == 0 else 1


def _candidates(conn, limit: int, doc_type: str = "ANNUAL_REPORT", nifty200_only: bool = False, nifty50_only: bool = False,
                since: str = "", active_since: str = "") -> List[Dict[str, Any]]:
    """`since` (YYYY-MM-DD) keeps rows filed on/after that date by their real filing time (BSE feed or BSE annual-report
    list); rows with no known filing date are left out when `since` is set, because doc_date is the crawl date.
    `active_since` keeps companies that traded on/after that date (BSE or NSE), i.e. skips delisted ones."""
    rows = conn.execute(CANDIDATE_SQL, (doc_type, 1 if nifty200_only else 0, 1 if nifty50_only else 0,
                                        since, since, active_since, active_since, active_since, limit)).fetchall()
    return [dict(zip(("id", "symbol", "isin", "title", "doc_date", "source_url", "pri200", "pri500"), r)) for r in rows]


def _download_only(todo, doc_type, workers, fc, guard, db_manager) -> int:
    """Fetch the PDFs and record their path, without chunking them (is_processed stays 0, so a later ingest pass can
    pick them up once the chunking strategy for the document type is settled). Downloads run in `workers` threads;
    each row is independent."""
    from concurrent.futures import ThreadPoolExecutor
    fc._download_via_browser = lambda *a, **k: None   # no headless-browser fallback from worker threads
    started = time.time()
    counts = {"ok": 0, "failed": 0}

    def one(rec):
        # any exception must stay inside this row: an exception escaping ex.map ended the whole 2026-10-10 run
        # silently after ~430 of 12,778 reports
        try:
            guard.wait_for_headroom("download")
            # plain download only: archive_link also runs a content classifier that can start the DirectML OCR, which is
            # not safe across threads (two 2026-10-10 runs died with no traceback after ~400 files)
            arch = fc._download(rec["source_url"], fc._local_path(rec["symbol"], doc_type, rec["source_url"]))
            if not arch.get("ok") or not arch.get("local_file_path"):
                return rec, None, arch.get("error")
            with db_manager.session() as conn:
                conn.execute("UPDATE corporate_documents SET local_file_path=?, file_size_bytes=?, sha256_hash=? WHERE id=?",
                             (arch.get("local_file_path"), arch.get("file_size_bytes"), arch.get("sha256_hash"), rec["id"]))
            return rec, arch, None
        except Exception as exc:  # noqa: BLE001
            return rec, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for n, (rec, arch, err) in enumerate(ex.map(one, todo), 1):
            if arch is None:
                counts["failed"] += 1
                log.warning("download failed %s %s: %s", rec["symbol"], rec["doc_date"], str(err)[:120])
            else:
                counts["ok"] += 1
            if n % 50 == 0:
                log.info("[%d/%d] downloaded ok=%d failed=%d (%.1f docs/min)", n, len(todo), counts["ok"], counts["failed"],
                         n / max(1e-9, (time.time() - started) / 60))
    log.info("DOWNLOAD_COMPLETE ok=%d failed=%d seconds=%.0f", counts["ok"], counts["failed"], time.time() - started)
    return 0 if counts["ok"] or not counts["failed"] else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Ingest indexed annual reports into raw_documents/chunks.")
    ap.add_argument("--limit", type=int, default=0, help="max documents this run (0 = all pending)")
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--ingest-workers", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2, help="download workers")
    ap.add_argument("--doc-type", dest="doc_type", default="ANNUAL_REPORT",
                    help="corporate_documents.doc_type to ingest (ANNUAL_REPORT, CONCALL_TRANSCRIPT, OTHER_FILING, ...)")
    ap.add_argument("--nifty200-only", action="store_true", dest="nifty200_only",
                    help="restrict to Nifty200 issuers (large-cap coverage first)")
    ap.add_argument("--nifty50-only", action="store_true", dest="nifty50_only",
                    help="restrict to Nifty50 issuers (test-ground slice)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since", default="", help="only rows filed on/after YYYY-MM-DD (real filing date; undated rows skipped)")
    ap.add_argument("--active-since", default="", dest="active_since",
                    help="only companies that traded on/after YYYY-MM-DD (skips delisted ones)")
    ap.add_argument("--download-only", action="store_true", dest="download_only",
                    help="fetch PDFs and record paths without chunking them (chunking strategy decided separately)")
    ap.add_argument("--local-only", action="store_true", dest="local_only",
                    help="chunk + embed files already downloaded but never processed (no downloads)")
    ap.add_argument("--before", default="", help="with --local-only: only rows filed before YYYY-MM-DD (undated skipped)")
    args = ap.parse_args(argv)

    from reality_engine.db.database import db_manager
    from reality_engine.ingestion.official_filing_client import official_filing_client as fc
    from reality_engine.ingestion.pdf_ingestor import PDFIngestor
    from reality_engine.ingestion.resource_guard import ResourceGuard

    started = time.time()
    if args.local_only:
        with db_manager.session() as conn:
            rows = conn.execute(LOCAL_SQL, (args.doc_type, args.before, args.before, args.limit or 1000000)).fetchall()
        log.info("local-only %s: %d pending (before %s)", args.doc_type, len(rows), args.before or "-")
        if args.dry_run or not rows:
            return 0
        guard = ResourceGuard.from_env(root=cfg.PROJECT_ROOT)
        return _local_only(rows, args.doc_type, PDFIngestor(db=db_manager, resource_guard=guard), db_manager)
    with db_manager.session() as conn:
        todo = _candidates(conn, args.limit or 100000, args.doc_type, args.nifty200_only, args.nifty50_only, args.since,
                           args.active_since)
    n200 = sum(1 for r in todo if r["pri200"])
    log.info("pending %s: %d (nifty200: %d, since %s) | ingest_workers=%d%s", args.doc_type, len(todo), n200,
             args.since or "-", args.ingest_workers, " | download only" if args.download_only else "")
    if args.dry_run or not todo:
        return 0

    guard = ResourceGuard.from_env(root=cfg.PROJECT_ROOT)
    if args.download_only:
        return _download_only(todo, args.doc_type, args.workers, fc, guard, db_manager)
    ingestor = PDFIngestor(db=db_manager, resource_guard=guard)
    ok = failed = 0
    for i in range(0, len(todo), args.batch):
        sl = todo[i : i + args.batch]
        t0 = time.time()
        for rec in sl:
            t1 = time.time()
            try:
                guard.wait_for_headroom("download")
                arch = fc.archive_link(rec["symbol"], {
                    "source_url": rec["source_url"],
                    "doc_type": args.doc_type,
                    "source": "bse_official",
                    "discovery_source": "filing_backfill",
                    "title": rec["title"],
                    "doc_date": rec["doc_date"],
                })
                if not arch.get("ok") or not arch.get("local_file_path"):
                    failed += 1
                    log.warning("download failed %s %s: %s", rec["symbol"], rec["doc_date"], str(arch.get("error"))[:120])
                    continue
                res = ingestor.ingest_pdf(
                    Path(arch["local_file_path"]),
                    title=rec["title"], source_type=args.doc_type,
                    published_date=rec["doc_date"], source_url=rec["source_url"],
                    symbol=rec["symbol"], isin=rec["isin"],
                )
                status = (res or {}).get("status")
                if status not in ("ingested", "skipped_duplicate"):
                    failed += 1
                    log.warning("ingest %s %s: %s %s", rec["symbol"], rec["doc_date"], status,
                                str((res or {}).get("error"))[:120])
                    continue
                with db_manager.session() as conn:
                    conn.execute(
                        "UPDATE corporate_documents SET local_file_path=?, file_size_bytes=?, sha256_hash=?, is_processed=1 WHERE id=?",
                        (arch.get("local_file_path"), arch.get("file_size_bytes"),
                         arch.get("sha256_hash"), rec["id"]),
                    )
                ok += 1
                log.info("[%d/%d] %s %s -> %s chunks (%.0fs)",
                         i + sl.index(rec) + 1, len(todo), rec["symbol"], rec["doc_date"],
                         (res or {}).get("chunks"), time.time() - t1)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log.warning("row error %s: %s", rec["symbol"], str(exc)[:160])
        log.info("batch %d-%d done: ok=%d failed=%d (%.0fs) cumulative ok=%d",
                 i, i + len(sl), ok, failed, time.time() - t0, ok)

    log.info("RUN_COMPLETE ingested=%d failed=%d seconds=%.0f", ok, failed, time.time() - started)
    return 0 if ok or failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
