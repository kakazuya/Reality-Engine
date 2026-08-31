"""Bounded detached RAG slice: archive + ingest in idempotent bounded batches.

Usage:
  python reality_engine/scripts/run_rag_slice.py --batch-size 200 --max-batches 5 --from-db --workers 1 --rate-limit 0.5
  python reality_engine/scripts/run_rag_slice.py --dry-run --batch-size 50
  python reality_engine/scripts/run_rag_slice.py --batch-size 100 --max-batches 2 --doc-type CONCALL_TRANSCRIPT

Single SQLite writer (workers=1 default), disk guard, detached-friendly logging, idempotent.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.db.database import db_manager
from reality_engine.db.repository import Repository

logger = logging.getLogger("run_rag_slice")

def parse_args():
    p = argparse.ArgumentParser(description="Bounded RAG slice: corporate_documents -> archive -> ingest")
    p.add_argument("--batch-size", type=int, default=200, help="Links per batch (default 200)")
    p.add_argument("--max-batches", type=int, default=5, help="Max batches to process (default 5)")
    p.add_argument("--from-db", action="store_true", default=True, help="Read discovered links from DB (default true)")
    p.add_argument("--workers", type=int, default=1, help="Download workers (default 1, SQLite single-writer)")
    p.add_argument("--rate-limit", type=float, default=0.5, help="Seconds between requests (default 0.5)")
    p.add_argument("--log-file", type=str, default=None, help="Optional log file path")
    p.add_argument("--disk-guard-mb", type=int, default=500, help="Abort if free disk < this MB (default 500)")
    p.add_argument("--dry-run", action="store_true", default=False, help="Plan without downloading/ingesting")
    p.add_argument("--doc-type", type=str, default=None, help="Filter doc_type e.g. CONCALL_TRANSCRIPT")
    return p.parse_args()

def check_disk_guard(path: Path, guard_mb: int) -> bool:
    try:
        free = shutil.disk_usage(str(path)).free / (1024 * 1024)
        if free < guard_mb:
            logger.warning("Disk guard triggered: free %.1f MB < %d MB at %s", free, guard_mb, path)
            return False
        return True
    except Exception:
        return True

def main():
    args = parse_args()
    log_handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        log_handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, handlers=log_handlers, format="%(asctime)s %(levelname)s %(message)s")
    repo = Repository(manager=db_manager)
    total_archived = 0
    total_ingested = 0
    total_skipped = 0
    batches = 0
    print(f"[run_rag_slice] batch_size={args.batch_size} max_batches={args.max_batches} workers={args.workers} dry_run={args.dry_run} doc_type={args.doc_type}")
    for b in range(args.max_batches):
        if not check_disk_guard(PROJECT_ROOT, args.disk_guard_mb):
            print(f"[ABORT] disk guard free < {args.disk_guard_mb} MB")
            break
        # query batch
        with db_manager.session() as conn:
            q = "SELECT id, symbol, doc_type, source_url, source, discovery_source, isin FROM corporate_documents WHERE discovery_source='screener_discovery' AND (local_file_path IS NULL OR is_processed=0)"
            params: List[Any] = []
            if args.doc_type:
                q += " AND doc_type=?"
                params.append(args.doc_type)
            q += " ORDER BY id LIMIT ?"
            params.append(int(args.batch_size))
            rows = conn.execute(q, params).fetchall()
        if not rows:
            print(f"[run_rag_slice] batch {b+1}: no more pending links, stopping")
            break
        print(f"[run_rag_slice] batch {b+1}: {len(rows)} links pending")
        if args.dry_run:
            for r in rows[:5]:
                print(f"  would archive {dict(r).get('symbol')} {dict(r).get('doc_type')} {dict(r).get('source_url')}")
            print(f"[dry-run] would process {len(rows)} links in batch {b+1}")
            batches += 1
            continue
        # archive via official_filing_client
        try:
            from reality_engine.ingestion.official_filing_client import official_filing_client
            # Build discoveries grouped by symbol
            by_sym: Dict[str, List[Dict[str, Any]]] = {}
            for r in rows:
                d = dict(r)
                sym = d.get("symbol") or "UNKNOWN"
                by_sym.setdefault(sym, []).append({
                    "source_url": d.get("source_url"),
                    "doc_type": d.get("doc_type"),
                    "source": d.get("source") or "bse_official",
                    "discovery_source": d.get("discovery_source") or "screener_discovery",
                })
            discoveries = [{"symbol": s, "bse_code": None, "links": links} for s, links in by_sym.items()]
            result = official_filing_client.archive_many(discoveries, max_workers=max(1, int(args.workers)), progress=False)
            archived = sum(1 for pr in result.get("per_symbol", []) for rr in pr.get("results", []) if rr.get("ok"))
            print(f"[run_rag_slice] batch {b+1}: archived {archived}/{len(rows)}")
            total_archived += archived
            # persist local_file_path back to DB
            with db_manager.session() as conn:
                for pr in result.get("per_symbol", []):
                    for rr in pr.get("results", []):
                        if rr.get("ok") and rr.get("local_file_path"):
                            conn.execute(
                                "UPDATE corporate_documents SET local_file_path=?, file_size_bytes=?, sha256_hash=?, is_processed=1 WHERE source_url=?",
                                (rr.get("local_file_path"), rr.get("file_size_bytes", 0), rr.get("sha256_hash"), rr.get("source_url")),
                            )
                conn.commit()
            time.sleep(float(args.rate_limit))
            # ingest each archived PDF into dense substrate with industry_id derivation
            try:
                from reality_engine.ingestion.pdf_ingestor import PDFIngestor
                ingestor = PDFIngestor(db=db_manager)
                ingested_this = 0
                for pr in result.get("per_symbol", []):
                    sym = pr.get("symbol")
                    for rr in pr.get("results", []):
                        p = rr.get("local_file_path")
                        if not p or not Path(p).exists():
                            continue
                        # resolve isin for symbol
                        try:
                            comp = repo.get_company_by_symbol(sym)
                            isin = comp.get("isin") if comp else None
                        except Exception:
                            isin = None
                        try:
                            res = ingestor.ingest_pdf(Path(p), symbol=sym, isin=isin, source_type=rr.get("doc_type") or "Investor_Presentation", source_url=rr.get("source_url"))
                            if res.get("status") == "ingested":
                                ingested_this += 1
                            elif res.get("status") == "skipped_duplicate":
                                total_skipped += 1
                        except Exception as exc:
                            logger.warning("ingest failed %s: %s", p, exc)
                total_ingested += ingested_this
                print(f"[run_rag_slice] batch {b+1}: ingested {ingested_this} PDFs into document_chunks")
            except Exception as exc:
                logger.warning("ingest phase note: %s", exc)
        except Exception as exc:
            logger.warning("archive batch %d failed: %s", b+1, exc)
        batches += 1
        time.sleep(float(args.rate_limit))
    print(f"[run_rag_slice] DONE batches={batches} archived={total_archived} ingested={total_ingested} skipped={total_skipped}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
