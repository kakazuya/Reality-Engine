"""Ingestion queue: run every pending filing/backfill stage ONE AT A TIME.

Why a queue rather than parallel jobs: the GPU duty cap is applied *per process*,
so three concurrent ingest jobs each respecting "keep the desktop responsive"
still add up past the cap and break the guarantee. Running stages sequentially
keeps total load inside the cap while still draining every backlog.

Stage order is by value-per-document, because that is what the cross-maps and
retrieval actually consume:

  1. drhp          — the in-scope SEBI offer documents (SME-heavy, in flight)
  2. annual_n200   — annual reports, Nifty200 first (large-cap fundamental text)
  3. concall_n    — concalls (company-specific, least boilerplate → best edges)
  4. annual_all    — the rest of the annual-report corpus
  5. concall_all   — the rest of the concalls
  6. refresh       — rebuild chunk vector index + business cross-map afterwards

Every stage is resumable and skips already-processed rows, so the queue can be
stopped and restarted at any point without losing work.

    python -m reality_engine.scripts.run_ingestion_queue
    python -m reality_engine.scripts.run_ingestion_queue --only concall_n --limit 50
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine import config as cfg  # noqa: E402

LOG_PATH = cfg.DATA_DIR / "logs" / "ingestion_queue.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("ingestion_queue")

Stages = Sequence[Tuple[str, List[str]]]


def _acquire_queue_lock():
    """Hold one OS-level lock so hourly watchdog ticks never overlap a writer."""
    lock_path = cfg.DATA_DIR / "ingestion_queue.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0)
    handle.write(b"0")
    handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError):
        handle.close()
        return None
    return handle


def _stages(args) -> Stages:
    py = sys.executable
    filings = "reality_engine.scripts.run_annual_report_ingest"
    base = ["--batch", str(args.batch), "--ingest-workers", "1"]
    return [
        ("drhp", [py, "-m", "reality_engine.scripts.run_offer_drhp_backfill",
                  "--batch", str(args.batch), "--workers", "4", "--ingest-workers", "2", "--since", "2021"]),
        ("annual_n200", [py, "-m", filings, *base, "--doc-type", "ANNUAL_REPORT",
                         "--nifty200-only", "--limit", str(args.n200_limit)]),
        ("concall_n200", [py, "-m", filings, *base, "--doc-type", "CONCALL_TRANSCRIPT",
                          "--nifty200-only", "--limit", str(args.n200_limit)]),
        ("annual_all", [py, "-m", filings, *base, "--doc-type", "ANNUAL_REPORT"]),
        ("concall_all", [py, "-m", filings, *base, "--doc-type", "CONCALL_TRANSCRIPT"]),
        ("refresh", [py, "-m", "reality_engine.scripts.build_chunk_vector_index"]),
        ("business_map", [py, "-m", "reality_engine.scripts.run_business_peer_graph", "--top-k", "20"]),
    ]


FAIL_FAST_THRESHOLD = 3


def _fail_fast_enabled() -> bool:
    """Per-stage fail-fast gate (env REALITY_ENGINE_FAIL_FAST_DOC, default off)."""
    return os.environ.get("REALITY_ENGINE_FAIL_FAST_DOC", "").strip().lower() not in (
        "", "0", "off", "no", "false")


def _run_queue(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Sequential ingestion queue (one stage at a time).")
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--n200-limit", type=int, default=0, help="cap Nifty200 stages (0 = all pending)")
    ap.add_argument("--only", default=None, help="run a single named stage")
    ap.add_argument("--retries", type=int, default=20, help="max restarts per stage (native-exit recovery)")
    args = ap.parse_args(argv)

    stages = [s for s in _stages(args) if not args.only or s[0] == args.only]
    if not stages:
        log.error("no such stage: %s", args.only)
        return 2

    total_start = time.time()
    failed_stages: List[str] = []
    fail_fast = _fail_fast_enabled()
    for name, cmd in stages:
        log.info("=== stage %s ===", name)
        log.info("env GPU_DUTY=%s VULKAN_BATCH=%s EMBED_BACKEND=%s EMBED_SERVER=%s",
                 os.environ.get("REALITY_ENGINE_GPU_DUTY", "0.90(default)"),
                 os.environ.get("REALITY_ENGINE_VULKAN_BATCH", "96(default)"),
                 os.environ.get("REALITY_ENGINE_EMBED_BACKEND", "auto(default)"),
                 os.environ.get("REALITY_ENGINE_EMBED_SERVER", "127.0.0.1:8099(default)"))
        attempts = 0
        consecutive_failures = 0
        stage_ok = False
        fail_fast_tripped = False
        while attempts < args.retries:
            attempts += 1
            t0 = time.time()
            proc = subprocess.run(cmd, cwd=str(cfg.PROJECT_ROOT), env=dict(os.environ))
            log.info("stage %s attempt %d exit=%s (%.0fs)", name, attempts, proc.returncode, time.time() - t0)
            if proc.returncode == 0:
                stage_ok = True
                consecutive_failures = 0
                break
            consecutive_failures += 1
            if fail_fast and consecutive_failures >= FAIL_FAST_THRESHOLD:
                log.warning("POISON_GUARD stage %s failed %d consecutive attempts "
                            "(no_chunks poison-doc class); breaking retry loop for this stage",
                            name, consecutive_failures)
                fail_fast_tripped = True
                break
            time.sleep(15)
        log.info("=== stage %s finished (attempts=%d%s) ===", name, attempts,
                 " POISON_GUARD fail-fast" if fail_fast_tripped else "")
        if not stage_ok:
            failed_stages.append(name)
    if failed_stages:
        log.error("QUEUE_INCOMPLETE stages=%s in %.0fs (embed backend=%s)",
                  ",".join(failed_stages), time.time() - total_start,
                  os.environ.get("REALITY_ENGINE_EMBED_BACKEND", "auto"))
        return 1
    log.info("QUEUE_COMPLETE in %.0fs (embed backend=%s)", time.time() - total_start,
             os.environ.get("REALITY_ENGINE_EMBED_BACKEND", "auto"))
    return 0
def main(argv: Optional[Sequence[str]] = None) -> int:
    lock = _acquire_queue_lock()
    if lock is None:
        log.info("queue lock held by another run; skipping overlapping invocation")
        return 0
    try:
        return _run_queue(argv)
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
