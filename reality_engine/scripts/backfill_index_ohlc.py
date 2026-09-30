"""Backfill universe-index OHLC rows into ``nse_index_breadth``.

Covers the four goal-loop universe legs (``Nifty 50``, ``Nifty Midcap 150``,
``Nifty Smallcap 250``, ``Nifty Microcap 250``) from ``--since``
(default 2025-09-01, a year back so 365-day forward windows from recent
entries resolve as new EODs land) through ``--until`` (default: latest
closed EOD, i.e. yesterday).

Per calendar date the script reuses ``nse_client.fetch_index_bhavcopy``
(local ``BHAVCOPY_DIR/ind_close_all_DDMMYYYY.csv`` cache first, else NSE
fetch — same shared client session, sequential with a small rate-limit
sleep), parses only the 4 universe rows, and upserts via
``Repository.upsert_index_breadth`` (``ON CONFLICT(date, index_name)
DO UPDATE`` — idempotent).

Resumable: dates already holding all 4 names are skipped without any
network call. Weekends / holidays / expired NSE history 404 honestly into
``missing_dates`` — never fabricated, never forward-filled.

Usage:
    python -m reality_engine.scripts.backfill_index_ohlc [--since YYYY-MM-DD]
        [--until YYYY-MM-DD] [--dry-run]

Prints a single JSON summary line:
    {"dates_requested": N, "dates_filled": M, "rows_upserted": K,
     "missing_dates": ["YYYY-MM-DD", ...]}
(dry-run: no writes and no fetches; ``missing_dates`` lists the dates that
lack full coverage and would be attempted.)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402

from reality_engine.db.repository import repo as default_repo  # noqa: E402
from reality_engine.ingestion.nse_client import nse_client  # noqa: E402

logger = logging.getLogger("reality_engine.backfill_index_ohlc")

UNIVERSE_INDEX = (
    "Nifty 50",
    "Nifty Midcap 150",
    "Nifty Smallcap 250",
    "Nifty Microcap 250",
)
DEFAULT_SINCE = "2025-09-01"
RATE_LIMIT_SEC = 1.0


def _safe_float(val: Any) -> float:
    v = pd.to_numeric(val, errors="coerce")
    return float(v) if pd.notna(v) else 0.0


def _safe_int(val: Any) -> int:
    v = pd.to_numeric(val, errors="coerce")
    return int(v) if pd.notna(v) else 0


def extract_universe_records(df: pd.DataFrame, date_iso: str) -> List[Dict[str, Any]]:
    """Pull the universe-leg breadth records out of one index-bhavcopy frame."""
    wanted = set(UNIVERSE_INDEX)
    records: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        name = str(r.get("Index Name", "")).strip()
        if name not in wanted:
            continue
        records.append(
            {
                "date": date_iso,
                "index_name": name,
                "open": _safe_float(r.get("Open Index Value")),
                "high": _safe_float(r.get("High Index Value")),
                "low": _safe_float(r.get("Low Index Value")),
                "close": _safe_float(r.get("Closing Index Value")),
                "change_pct": _safe_float(r.get("Change(%)")),
                "points_change": _safe_float(r.get("Points Change")),
                "volume": _safe_int(r.get("Volume")),
                "turnover_cr": _safe_float(r.get("Turnover (Rs. Cr.)")),
                "advances_count": 0,
                "declines_count": 0,
                "advance_decline_ratio": 1.0,
                "pe_ratio": _safe_float(r.get("P/E")),
                "pb_ratio": _safe_float(r.get("P/B")),
                "dividend_yield": _safe_float(r.get("Div Yield")),
            }
        )
    return records


def date_has_full_coverage(repo: Any, date_iso: str) -> bool:
    """True when all 4 universe names are present for ``date_iso``."""
    with repo.db.session() as conn:
        rows = conn.execute(
            "SELECT DISTINCT index_name FROM nse_index_breadth "
            "WHERE date = ? AND index_name IN (?, ?, ?, ?)",
            (date_iso, *UNIVERSE_INDEX),
        ).fetchall()
    return len({r[0] for r in rows}) >= len(UNIVERSE_INDEX)


def _iter_dates(since: date, until: date):
    day = since
    while day <= until:
        yield day
        day += timedelta(days=1)


def backfill_index_ohlc(
    since: str = DEFAULT_SINCE,
    until: Optional[str] = None,
    dry_run: bool = False,
    repo: Any = None,
    fetcher: Optional[Callable[[datetime], Optional[pd.DataFrame]]] = None,
    rate_limit_sec: float = RATE_LIMIT_SEC,
) -> Dict[str, Any]:
    """Backfill the 4 universe index legs over ``[since, until]`` (calendar days).

    ``repo`` defaults to the singleton; ``fetcher`` defaults to
    ``nse_client.fetch_index_bhavcopy`` (shared session). Both are
    injectable so tests stay hermetic. Returns the summary dict.
    """
    repo = repo if repo is not None else default_repo
    fetch = fetcher if fetcher is not None else nse_client.fetch_index_bhavcopy

    since_d = date.fromisoformat(since)
    until_d = date.fromisoformat(until) if until else date.today() - timedelta(days=1)
    if until_d < since_d:
        raise ValueError(f"--until {until_d} precedes --since {since_d}")

    summary: Dict[str, Any] = {
        "dates_requested": 0,
        "dates_filled": 0,
        "rows_upserted": 0,
        "missing_dates": [],
    }

    for day in _iter_dates(since_d, until_d):
        date_iso = day.isoformat()
        summary["dates_requested"] += 1

        if date_has_full_coverage(repo, date_iso):
            continue  # resumable: already complete, no network call

        if dry_run:
            # No writes and no fetches; report what a real run would attempt.
            summary["missing_dates"].append(date_iso)
            continue

        target = datetime(day.year, day.month, day.day, 12, 0)
        try:
            df = fetch(target)
        except Exception as exc:  # noqa: BLE001 - one bad day never aborts the run
            logger.warning("Index bhavcopy fetch failed for %s (%s); skipping.", date_iso, exc)
            summary["missing_dates"].append(date_iso)
            continue
        if rate_limit_sec and rate_limit_sec > 0:
            time.sleep(rate_limit_sec)

        if df is None or df.empty:
            # Weekend / holiday / NSE 404 on expired history — count honestly.
            summary["missing_dates"].append(date_iso)
            continue

        records = extract_universe_records(df, date_iso)
        if len(records) < len(UNIVERSE_INDEX):
            logger.warning(
                "Index bhavcopy for %s held %d/4 universe legs; skipping.",
                date_iso, len(records),
            )
            summary["missing_dates"].append(date_iso)
            continue

        summary["rows_upserted"] += repo.upsert_index_breadth(records)
        summary["dates_filled"] += 1

    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default=DEFAULT_SINCE,
                    help="first calendar date YYYY-MM-DD (default %(default)s)")
    ap.add_argument("--until", default=None,
                    help="last calendar date YYYY-MM-DD (default: yesterday, latest closed EOD)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report coverage gaps without fetching or writing")
    args = ap.parse_args(argv)

    try:
        summary = backfill_index_ohlc(since=args.since, until=args.until, dry_run=args.dry_run)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
