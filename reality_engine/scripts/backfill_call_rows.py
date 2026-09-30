"""Backfill missing ``eod_scrip_calls`` rows for attribution dates.

For every ``attribution_date`` in ``move_attribution`` that holds zero
``eod_scrip_calls`` rows, this script re-runs the ensemble screen for that
``target_date`` so entry/target/stop/forensic terms exist for the seed. The
writer stays ``composite_screener.ensemble_screen`` → ``repo.upsert_eod_scrip_calls``
(this script only invokes it per date, never reimplements it); screens
recompute indicators from price history, so output is deterministic given
the DB — no invented data.

Era survey (probed 2026-09-22; 11 existing call dates, 60 attribution dates):

* 2026-07-13 / 07-14 / 07-20 / 08-13: 50 rows each, nifty200-only.
* 2026-08-14: 132 rows; 08-21: 101; 08-26: 100; 08-27: 101 (mixed universes).
* 2026-08-28: 258 rows (existing max; majority non-nifty200).
* 2026-09-16: 35 rows; 2026-09-18: 129 rows (mixed universes).

Choice of parameters: attribution itself is the 200-symbol nifty200
universe (200 rows per attribution date, ``attribute_universe`` default), so
``universe="nifty200"`` matches the attribution universe exactly. ``top_n=200``
(the minimum allowed) covers every attribution name on a date when the screen
ranks the full universe, and is precedented by the existing 258-row max —
later mixed-universe dates show larger ``top_n`` values were already the norm,
so 200 is conservative, not novel.

Resumable and idempotent: ``upsert_eod_scrip_calls`` is
``ON CONFLICT(date, symbol) DO UPDATE``, and dates already holding call rows
are skipped, so re-running only fills what is still missing. Each date runs
inside its own try/except — one bad date is logged into ``failed_dates`` and
the run continues. Sequential, ascending date order.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine.db.repository import repo as default_repo  # noqa: E402

logger = logging.getLogger("reality_engine.backfill_call_rows")

DEFAULT_TOP_N = 200
DEFAULT_UNIVERSE = "nifty200"


def _default_screen(target_date: str, top_n: int, universe: str) -> Any:
    """Live screen path: ensemble screen (persists via ``upsert_eod_scrip_calls``)."""
    from reality_engine.processing.composite_screener import ensemble_screen

    return ensemble_screen(target_date=target_date, top_n=top_n, universe=universe)


def uncovered_attribution_dates(
    repo: Any,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> List[str]:
    """Attribution dates in ``[since, until]`` holding zero call rows, ascending."""
    try:
        with repo.db.session() as conn:
            sql = "SELECT DISTINCT attribution_date AS d FROM move_attribution"
            clauses: List[str] = []
            args: List[str] = []
            if since is not None:
                clauses.append("attribution_date >= ?")
                args.append(since)
            if until is not None:
                clauses.append("attribution_date <= ?")
                args.append(until)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY d ASC"
            dates = [str(r["d"]) for r in conn.execute(sql, args).fetchall() if r["d"] is not None]
            uncovered = [
                d
                for d in dates
                if conn.execute(
                    "SELECT COUNT(*) FROM eod_scrip_calls WHERE date = ?", (d,)
                ).fetchone()[0] == 0
            ]
    except Exception as exc:  # missing move_attribution table, locked DB, ...
        logger.warning("Could not list attribution coverage (%s); nothing to do.", exc)
        return []
    return uncovered


def date_call_count(repo: Any, date_iso: str) -> int:
    """Call rows present for one date (post-screen verification read)."""
    with repo.db.session() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM eod_scrip_calls WHERE date = ?", (date_iso,)
            ).fetchone()[0]
        )


def backfill_call_rows(
    since: Optional[str] = None,
    until: Optional[str] = None,
    dry_run: bool = False,
    limit_dates: Optional[int] = None,
    top_n: int = DEFAULT_TOP_N,
    universe: str = DEFAULT_UNIVERSE,
    repo: Any = None,
    screen_fn: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Fill call rows for uncovered attribution dates; return the summary dict.

    ``repo`` defaults to the singleton; ``screen_fn`` defaults to the live
    ensemble screen and is injectable (``(target_date, top_n, universe)``) so
    tests stay hermetic. Returns exactly
    ``{dates_requested, dates_filled, call_rows_written, failed_dates}``.
    """
    repo = repo if repo is not None else default_repo
    screen = screen_fn if screen_fn is not None else _default_screen
    if top_n < DEFAULT_TOP_N:
        logger.warning(
            "top_n=%d below the %d minimum; material names may stay uncovered.",
            top_n, DEFAULT_TOP_N,
        )

    dates = uncovered_attribution_dates(repo, since=since, until=until)
    if limit_dates is not None:
        dates = dates[: max(0, int(limit_dates))]

    summary: Dict[str, Any] = {
        "dates_requested": len(dates),
        "dates_filled": 0,
        "call_rows_written": 0,
        "failed_dates": [],
    }
    if dry_run:
        return summary  # report gaps; no screens, no writes

    for date_iso in dates:
        try:
            screen(target_date=date_iso, top_n=top_n, universe=universe)
        except Exception as exc:  # noqa: BLE001 - one bad date never aborts the run
            logger.warning("Ensemble screen failed for %s (%s); skipping.", date_iso, exc)
            summary["failed_dates"].append(date_iso)
            continue
        try:
            n_rows = date_call_count(repo, date_iso)
        except Exception as exc:  # noqa: BLE001 - unverifiable fill counts honestly
            logger.warning("Could not verify call rows for %s (%s); skipping.", date_iso, exc)
            summary["failed_dates"].append(date_iso)
            continue
        if n_rows > 0:
            summary["dates_filled"] += 1
            summary["call_rows_written"] += n_rows
        else:
            logger.warning("Ensemble screen wrote no call rows for %s; skipping.", date_iso)

    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default=None,
                    help="first attribution date YYYY-MM-DD (default: earliest)")
    ap.add_argument("--until", default=None,
                    help="last attribution date YYYY-MM-DD (default: latest)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report uncovered dates without screening or writing")
    ap.add_argument("--limit-dates", type=int, default=None,
                    help="cap on dates attempted, ascending (default: all uncovered)")
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N,
                    help="screen breadth per date, minimum %(default)s")
    ap.add_argument("--universe", default=DEFAULT_UNIVERSE,
                    help="screen universe (default: %(default)s, matches attribution)")
    args = ap.parse_args(argv)

    try:
        if args.since is not None:
            date.fromisoformat(args.since)
        if args.until is not None:
            date.fromisoformat(args.until)
        if (args.since is not None and args.until is not None
                and args.until < args.since):
            raise ValueError(f"--until {args.until} precedes --since {args.since}")
        summary = backfill_call_rows(
            since=args.since,
            until=args.until,
            dry_run=args.dry_run,
            limit_dates=args.limit_dates,
            top_n=args.top_n,
            universe=args.universe,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
