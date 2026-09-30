"""Weekly SEBI filing ingestion (new DRHP/Prospectus filings -> dense substrate).

Full chain, self-contained and idempotent:
  1. crawl  — SEBI public-issues listings, both stages (draft DRHP + final RHP),
              matched against master_companies in state.json
  2. resolve — filing page -> PDF link (fresh session per worker; SEBI throttles
              long-lived sessions)
  3. archive+ingest+distill — download, extract, chunk, embed, promote into
              moat_evaluations / business_model_profiles /
              company_distilled_parameters / regulatory_political_risks

Runs the archive/ingest stage as a SUBPROCESS and retries it, because the
DirectML embedder exits the interpreter natively every ~15 min (no Python
traceback); the subprocess boundary keeps this driver alive and the state file
makes every restart resume.

Designed for Windows Task Scheduler (see run_weekly_sebi_ingest.cmd).

Usage:
    python -m reality_engine.scripts.weekly_sebi_ingest --since 2021
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine import config as cfg  # noqa: E402
from reality_engine.pipeline import offer_backfill as ob  # noqa: E402

LOG_PATH = cfg.DATA_DIR / "logs" / "offer_backfill" / "weekly_ingest.log"
LOCK_NAME = "weekly_ingest.lock"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("weekly_sebi_ingest")


def _acquire(lock_path: Path) -> bool:
    """Single-flight guard: stale locks (dead PID) are reclaimed."""
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid:
            try:
                os.kill(pid, 0)
                log.warning("another weekly run is active (pid=%d) — exiting", pid)
                return False
            except OSError:
                log.info("reclaiming stale lock (pid=%d gone)", pid)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _release(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        pass


def _pending(loop_dir: Path, since: int) -> List[Dict[str, Any]]:
    state = ob.load_state(loop_dir)
    out = []
    for url, rec in state["records"].items():
        if not (rec.get("symbol") and rec.get("pdf_url") and not rec.get("distilled")):
            continue
        year = int((rec.get("doc_date") or "0")[:4] or 0)
        if since and year and year < since:
            continue
        out.append(rec)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Weekly SEBI filing ingestion.")
    ap.add_argument("--since", type=int, default=2021, help="ignore filings older than this year")
    ap.add_argument("--workers", type=int, default=4, help="download workers")
    ap.add_argument("--ingest-workers", type=int, default=2, help="PDF ingest threads (SQLite single-writer)")
    ap.add_argument("--resolve-workers", type=int, default=6)
    ap.add_argument("--max-pages", type=int, default=0, help="cap listing pages per stage (0=all)")
    ap.add_argument("--attempts", type=int, default=40, help="max archive subprocess restarts")
    ap.add_argument("--skip-archive", action="store_true", help="crawl + match + resolve only")
    ap.add_argument("--skip-refresh", action="store_true",
                    help="skip rebuilding the chunk vector index + business cross-map afterwards")
    ap.add_argument("--loop-dir", default=None)
    args = ap.parse_args(argv)

    loop_dir = Path(args.loop_dir) if args.loop_dir else ob.default_loop_dir()
    lock_path = loop_dir / LOCK_NAME
    if not _acquire(lock_path):
        return 2

    started = time.time()
    summary: Dict[str, Any] = {"crawl": None, "resolved": None, "archive": None}
    try:
        # 1) crawl + match (dry_run => zero downloads, only state.json is written)
        log.info("step 1/3: crawl + match (stages=draft,final, max_pages=%s)",
                 args.max_pages or "all")
        crawl_res = ob.run_once(
            loop_dir=loop_dir, dry_run=True,
            stages=("final", "draft"), max_pages=args.max_pages,
        )
        summary["crawl"] = {k: crawl_res.get(k) for k in ("crawled", "matched", "unmatched", "rc", "error")}
        log.info("crawl result: %s", summary["crawl"])

        # 2) resolve PDF links for matched-but-unresolved records
        log.info("step 2/3: resolve filing pages -> PDF links")
        from reality_engine.scripts.run_offer_pdf_resolve import main as resolve_main
        rc = resolve_main(["--workers", str(args.resolve_workers), "--loop-dir", str(loop_dir)])
        summary["resolved"] = rc
        log.info("resolve rc=%s", rc)

        pending = _pending(loop_dir, args.since)
        log.info("pending archive/ingest: %d (since=%d)", len(pending), args.since)
        if args.skip_archive or not pending:
            summary["archive"] = {"skipped": args.skip_archive, "pending": len(pending)}
        else:
            # 3) archive + ingest + distill in a subprocess, retried on native exits
            env = dict(os.environ)
            env.setdefault("REALITY_ENGINE_GPU_DUTY", "0.85")
            cmd = [
                sys.executable, "-m", "reality_engine.scripts.run_offer_drhp_backfill",
                "--batch", "10", "--workers", str(args.workers),
                "--ingest-workers", str(args.ingest_workers),
                "--since", str(args.since), "--loop-dir", str(loop_dir),
            ]
            attempts = 0
            stalled = 0
            prev_remaining = len(pending)
            while attempts < args.attempts:
                attempts += 1
                remaining = len(_pending(loop_dir, args.since))
                if remaining == 0:
                    break
                log.info("step 3/3: archive subprocess attempt %d (remaining=%d)", attempts, remaining)
                proc = subprocess.run(cmd, cwd=str(cfg.PROJECT_ROOT), env=env)
                now = len(_pending(loop_dir, args.since))
                log.info("attempt %d exit=%s remaining=%d", attempts, proc.returncode, now)
                if now >= prev_remaining:      # no progress: SEBI down or nothing fetchable
                    stalled += 1
                    if stalled >= 3:
                        log.warning("no progress across 3 attempts — stopping this run")
                        break
                    time.sleep(60)
                else:
                    stalled = 0
                prev_remaining = now
            summary["archive"] = {"attempts": attempts, "remaining": len(_pending(loop_dir, args.since))}

        # 4) refresh the derived retrieval/cross-map layers over whatever is now
        #    ingested. Both are idempotent and cheap (index ~30s, cross-map ~100s),
        #    and without this step new documents would be stored but unqueryable.
        if not args.skip_refresh:
            try:
                log.info("step 4/4: rebuilding chunk vector index + business cross-map")
                from reality_engine.scripts.build_chunk_vector_index import main as build_index
                from reality_engine.scripts.run_business_peer_graph import main as build_business_map
                summary["index_rc"] = build_index([])
                summary["business_map_rc"] = build_business_map(["--top-k", "20"])
            except Exception as exc:  # noqa: BLE001
                log.warning("refresh step failed: %s", str(exc)[:200])
                summary["refresh_error"] = str(exc)[:200]

        return 0 if summary.get("archive", {}).get("remaining", 0) == 0 else 1
    finally:
        summary["seconds"] = round(time.time() - started, 1)
        log.info("WEEKLY_RUN_DONE %s", json.dumps(summary, default=str))
        _release(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
