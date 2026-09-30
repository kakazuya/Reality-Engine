"""Fan-out PDF resolver for SEBI offer-document filings.

For every matched record without a resolved ``pdf_url``, resolve the PDF link
by fetching the filing page with a FRESH session per worker (per-session SEBI
throttling has been observed to degrade long-lived connections to ~10-20s per
GET, while each new session is fast). Mirrors ``SebiOfferClient.resolve_pdf_url``
but with per-worker client instances. Updates and period-saves ``state.json``.

Usage:
    python -m reality_engine.scripts.run_offer_pdf_resolve --workers 6
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine.pipeline import offer_backfill as ob  # noqa: E402
from reality_engine.ingestion.sebi_offer_client import SebiOfferClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pdf_resolve")

_clients: Dict[int, SebiOfferClient] = {}


def _client(wi: int) -> SebiOfferClient:
    if wi not in _clients:
        _clients[wi] = SebiOfferClient(rate_limit_sec=0.35)
    return _clients[wi]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="cap records resolved (0=all)")
    ap.add_argument("--loop-dir", default=None)
    args = ap.parse_args(argv)

    loop_dir = Path(args.loop_dir) if args.loop_dir else ob.default_loop_dir()
    state = ob.load_state(loop_dir)
    todo = [
        (url, rec)
        for url, rec in state["records"].items()
        if rec.get("symbol") and not rec.get("pdf_url")
    ]
    if args.limit:
        todo = todo[: args.limit]
    log.info("to resolve: %d", len(todo))
    if not todo:
        return 0

    done = failed = 0
    t0 = time.time()

    def _work(item):
        wi, (url, rec) = item
        try:
            return url, _client(wi).resolve_pdf_url(url), None
        except Exception as exc:  # noqa: BLE001
            return url, None, str(exc)[:120]

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (url, pdf, err) in enumerate(ex.map(_work, enumerate(todo))):
            if pdf:
                state["records"][url]["pdf_url"] = pdf
                done += 1
            else:
                failed += 1
                if err:
                    state["records"][url].setdefault("resolve_errors", []).append(err)
            if (i + 1) % 100 == 0:
                save = time.time()
                ob.save_state(loop_dir, state)
                log.info("%d/%d resolved=%d failed=%d (%.0fs elapsed)",
                         i + 1, len(todo), done, failed, time.time() - t0)

    ob.save_state(loop_dir, state)
    log.info("RESOLVE_COMPLETE resolved=%d failed=%d elapsed=%.0fs", done, failed, time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
