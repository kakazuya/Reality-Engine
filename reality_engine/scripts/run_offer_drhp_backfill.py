"""Resumable DRHP/Offer-document download + ingest + distill driver (v3).

Behaviour:
* Reads state.json (crawl + resolved ``pdf_url`` per record).
* Skips records already registered in ``raw_documents`` (source_url match).
* RECOVERS already-downloaded files: the archive path encodes
  ``sha256(pdf_url)[:8]``, so an existing file is found by glob and ingested
  without any HTTP request.
* Processes NEWEST FIRST (recent listings matter most; pre-2021 listings fall
  back to the annual-report corpus).
* Saves state + appends a progress log after every batch, so a kill resumes.

Usage:
    python -m reality_engine.scripts.run_offer_drhp_backfill --batch 25 --workers 4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine.pipeline import offer_backfill as ob  # noqa: E402
from reality_engine import config as cfg  # noqa: E402

LOG_PATH = cfg.DATA_DIR / "logs" / "offer_backfill" / "backfill_run.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("drhp_backfill")


def _find_existing(symbol: str, pdf_url: str) -> str | None:
    folder = cfg.PDFS_DIR / (symbol or "UNKNOWN").upper().replace("/", "_") / "OFFER_DOCUMENT"
    if not folder.exists():
        return None
    h = hashlib.sha256(pdf_url.encode("utf-8")).hexdigest()[:8]
    hits = sorted(folder.glob(f"*_{h}_*"))
    return str(hits[0]) if hits else None


def _registered_urls() -> set:
    from reality_engine.db.repository import repo as R
    with R.db.session() as conn:
        return {r[0] for r in conn.execute(
            "select source_url from raw_documents where source_type='OFFER_DOCUMENT'")}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=25, help="records per persist batch")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--ingest-workers", type=int, default=2,
                    help="concurrent PDF ingest threads (SQLite is single-writer; >2 causes lock timeouts)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--since", type=int, default=0, help="skip records older than this year (0=all)")
    ap.add_argument("--loop-dir", default=None)
    args = ap.parse_args(argv)

    loop_dir = Path(args.loop_dir) if args.loop_dir else ob.default_loop_dir()
    state = ob.load_state(loop_dir)
    registered = _registered_urls()

    todo: List[Dict[str, Any]] = []
    recovered = 0
    isin_by_symbol: Dict[str, str] = {}
    try:
        from reality_engine.db.repository import repo as R
        with R.db.session() as conn:
            isin_by_symbol = {
                r[1]: r[0]
                for r in conn.execute(
                    "select isin, nse_symbol from master_companies where nse_symbol is not null")
            }
    except Exception as exc:  # noqa: BLE001
        log.warning("isin map unavailable: %s", exc)

    for url, rec in state["records"].items():
        if not (rec.get("symbol") and rec.get("pdf_url")):
            continue
        if rec.get("distilled"):          # fully processed end-to-end (idempotent resume)
            continue
        year = int((rec.get("doc_date") or "0")[:4] or 0)
        if args.since and year and year < args.since:
            continue
        rec["isin"] = rec.get("isin") or isin_by_symbol.get(rec["symbol"])
        existing = rec.get("local_file_path") if rec.get("local_file_path") and Path(rec["local_file_path"]).exists() else _find_existing(rec["symbol"], rec["pdf_url"])
        if existing:
            rec["local_file_path"] = existing
            recovered += 1
        todo.append({"filing_page_url": url, **rec})

    todo.sort(key=lambda r: (r.get("doc_date") or ""), reverse=True)
    if args.limit:
        todo = todo[: args.limit]
    log.info("todo=%d (recovered from disk=%d, already registered=%d, since=%s)",
             len(todo), recovered, len(registered), args.since or "all")
    if not todo:
        return 0

    from reality_engine.ingestion.official_filing_client import official_filing_client as fc
    from reality_engine.db.database import db_manager
    mgr = db_manager

    done_ing = done_fail = 0
    for i in range(0, len(todo), args.batch):
        sl = todo[i : i + args.batch]
        t0 = time.time()

        # 1) resolve which records need a network download
        on_disk = {r["pdf_url"]: r["local_file_path"] for r in sl if r.get("local_file_path")}
        to_fetch = [r for r in sl if not r.get("local_file_path")]

        fetched: Dict[str, Dict[str, Any]] = {}
        if to_fetch:
            by_symbol: Dict[str, List[Dict[str, Any]]] = {}
            for rec in to_fetch:
                by_symbol.setdefault(rec["symbol"], []).append(
                    {
                        "source_url": rec["pdf_url"],
                        "doc_type": "OFFER_DOCUMENT",
                        "source": "sebi_official",
                        "discovery_source": "sebi_offer_backfill",
                        "title": rec.get("title"),
                        "doc_date": rec.get("doc_date"),
                        "filing_page_url": rec.get("filing_page_url"),
                        "offer_stage": rec.get("stage"),
                    }
                )
            res = fc.archive_many([{"symbol": s, "links": L} for s, L in by_symbol.items()],
                                  max_workers=args.workers, progress=False)
            for sym_res in res.get("per_symbol", []):
                for r in sym_res.get("results", []):
                    if r.get("source_url"):
                        fetched[r["source_url"]] = r

        # 2) build ingest records (from disk or fresh download)
        ingest_recs: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        for rec in sl:
            arch = fetched.get(rec["pdf_url"])
            if arch and arch.get("ok") and arch.get("local_file_path"):
                rec["local_file_path"] = arch["local_file_path"]
            elif rec.get("local_file_path"):
                arch = {"ok": True, "local_file_path": rec["local_file_path"], "error": None}
            if arch and arch.get("ok"):
                ingest_recs.append({**rec, "archive": arch})
            else:
                errors[rec["filing_page_url"]] = (arch or {}).get("error") or "not_found_on_disk"
        # 3) ingest + distill
        ingested = ob.ingest_records(ingest_recs, persist=True, manager=mgr, max_workers=args.workers,
                                     ingest_workers=args.ingest_workers) if ingest_recs else []
        n_ing = 0
        for rr in ingested:
            st = (rr.get("ingest") or {}).get("status")
            if st == "ingested":
                n_ing += 1
                s0 = state["records"].setdefault(rr["filing_page_url"], {})
                s0["local_file_path"] = rr.get("local_file_path") or rr.get("archive", {}).get("local_file_path")
                s0["ingested"] = True
                s0["distilled"] = True
            elif st == "skipped_duplicate":
                s0 = state["records"].setdefault(rr["filing_page_url"], {})
                s0["distilled"] = True
            else:
                done_fail += 1
                log.warning("ingest %s %s: %s", st, rr.get("symbol"),
                            str((rr.get("ingest") or {}).get("error"))[:200])
        dist = ob.distill_records(ingested, manager=mgr) if ingested else {}
        done_ing += n_ing

        # 4) persist state every batch
        for rec in sl:
            if rec.get("local_file_path"):
                state["records"].setdefault(rec["filing_page_url"], {})["local_file_path"] = rec["local_file_path"]
        for url, err in errors.items():
            state["records"].setdefault(url, {}).setdefault("download_errors", []).append(err[:160])
        ob.save_state(loop_dir, state)

        log.info("batch %d-%d: ingested=%d cumulative=%d failed=%d batch_time=%.0fs distill=%s",
                 i, i + len(sl), n_ing, done_ing, done_fail, time.time() - t0,
                 json.dumps(dist, default=str)[:140])

    log.info("RUN_COMPLETE ingested=%d failed=%d", done_ing, done_fail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
