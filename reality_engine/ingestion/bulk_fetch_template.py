"""
Bulk Fundamentals Fetch Template
=================================

Reference, runnable template for ingesting 5-year historical fundamentals for
the full Indian-equity universe (e.g. 2730 companies) using the resilient,
rate-limited :meth:`FundamentalsClient.fetch_all_fundamentals` helper.

WHY THIS EXISTS
---------------
`reality_engine/ingestion/fundamentals_client.py:103` only exposes a
per-symbol `fetch_company_fundamentals(symbol, isin, bse_code)`. The caller had
to orchestrate threading, throttling, and error isolation itself. This module
documents the canonical bulk pattern so callers (CLI, cron, notebooks) stay
consistent and resilient.

USAGE (as a script)
-------------------
    python reality_engine/ingestion/bulk_fetch_template.py \
        --top 2730 --workers 4 --rate-limit 0.5 --universe all --persist

    # Dry run (fetch, collect, print counts, do NOT write to DB):
    python reality_engine/ingestion/bulk_fetch_template.py --top 5 --no-persist

EXPECTED RUNTIME
----------------
    companies / (workers / (1 + rate_limit_sec))
    ~ 2730 / (4 / 1.5)  ~= 1023s per "effective worker pass" ... empirically
    observed at ~2-3h for the full universe with workers=4, rate_limit=0.5.

INTEGRATION POINTS
------------------
- CLI: `python reality_engine/cli.py fetch-fundamentals --top 200 --workers 4`
- Pipeline: `Phase1PipelineRunner.run_phase1_pipeline` (Step 3) already drives a
  bulk fundamentals loop; it can be swapped to call `fetch_all_fundamentals`
  with `persist=True` to reuse the same resilient path.

The function signature (unchanged from the handoff spec)::

    fetch_all_fundamentals(
        self,
        companies: List[Dict],
        max_workers: int = 4,
        rate_limit_sec: float = 0.5,
        max_companies: Optional[int] = None,
        progress: bool = True,
        persist: bool = False,
        repo: Any = None,
    ) -> Dict[str, Any]

Returned counts dict keys:
    attempted, succeeded, failed, quarterly_rows, annual_rows,
    forensic_rows, document_rows, failed_symbols, quarterly, annual,
    forensic, documents
"""

from __future__ import annotations

import argparse
import logging
from typing import Any, Dict, List

from reality_engine.db.repository import repo
from reality_engine.ingestion.fundamentals_client import fundamentals_client

logger = logging.getLogger("reality_engine.bulk_fetch_template")


def build_company_list(universe: str, top: int) -> List[Dict[str, Any]]:
    """Resolve a list of company dicts from the repository.

    Each dict carries at least ``isin`` and ``nse_symbol`` (or ``symbol``) and
    optionally ``bse_code`` -- exactly what ``fetch_all_fundamentals`` expects.
    """
    if universe == "nifty200":
        companies = repo.get_nifty200_companies()
    else:
        companies = repo.get_all_companies(active_only=True)
    if top and top > 0:
        companies = companies[:top]
    return companies


def run_bulk_fetch(
    universe: str = "all",
    top: int = 2730,
    workers: int = 4,
    rate_limit_sec: float = 0.5,
    persist: bool = True,
) -> Dict[str, Any]:
    """Fetch (and optionally persist) fundamentals for the chosen universe."""
    companies = build_company_list(universe, top)
    logger.info(
        "Bulk fundamentals: %d companies | workers=%d rate_limit=%.2fs persist=%s",
        len(companies), workers, rate_limit_sec, persist,
    )
    result = fundamentals_client.fetch_all_fundamentals(
        companies,
        max_workers=workers,
        rate_limit_sec=rate_limit_sec,
        max_companies=top,
        persist=persist,
    )
    logger.info(
        "Done: attempted=%d succeeded=%d failed=%d | q=%d a=%d f=%d docs=%d",
        result["attempted"], result["succeeded"], result["failed"],
        result["quarterly_rows"], result["annual_rows"],
        result["forensic_rows"], result["document_rows"],
    )
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Bulk 5y fundamentals fetch template")
    parser.add_argument("--universe", type=str, default="all", choices=["all", "nifty200"])
    parser.add_argument("--top", type=int, default=2730, help="Cap on companies to fetch")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent worker threads")
    parser.add_argument("--rate-limit", type=float, default=0.5, help="Sleep between submissions (s)")
    parser.add_argument("--no-persist", action="store_true", default=False, help="Fetch but do not write DB")
    args = parser.parse_args()

    run_bulk_fetch(
        universe=args.universe,
        top=args.top,
        workers=args.workers,
        rate_limit_sec=args.rate_limit,
        persist=not args.no_persist,
    )


if __name__ == "__main__":
    main()
