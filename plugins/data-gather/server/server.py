#!/usr/bin/env python3
"""MCP stdio surface for the data-gather plugin.

Five deterministic tools over the existing dsh-worker registry/supervisor:
list feeds with freshness, report date gaps, run an approved feed, poll a run,
and verify what it wrote.  The server never runs a model and never writes a
database row.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from mcp.server import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

import gather  # noqa: E402
from core import PluginError  # noqa: E402

SERVER_VERSION = "0.1.0"

INSTRUCTIONS = (
    "Data feeds for this repository. list_feeds shows every jobs.yaml feed with "
    "its live freshness (dsh-worker's own max-date/count rule), age versus "
    "cadence, last run and whether a human approved it in "
    "plugins/data-gather/approved.yaml. gap_report compares expected NSE trading "
    "days against the dates actually stored, per market feed. run_feed starts an "
    "APPROVED feed ONLY, through the same dsh-worker supervisor, controller lease "
    "and db:/net: resource locks as start_job; it refuses unapproved feeds, "
    "net-heavy feeds during peak hours (Mon-Fri 06:30-09:30 and 11:30-15:30 IST) "
    "and windows longer than the feed's approved max_days, and returns run_id or "
    "resource_busy. feed_status gives phase/outcome plus at most 40 lines of "
    "stdout/stderr. verify_feed compares the before/after row counts and max "
    "dates captured when run_feed started the job, compares the first new rows' "
    "stored date against the source's known_at/filing date (doc_date is a crawl "
    "date and is never trusted), and checks that raw files landed under "
    "REALITY_RAW_ROOT rather than under the data root. All reads are bounded and "
    "read-only; neither this server nor its tools writes DB rows."
)

server = MCPServer(
    name="data-gather",
    version=SERVER_VERSION,
    instructions=INSTRUCTIONS,
)


def _safe(call) -> dict[str, Any]:
    try:
        return call()
    except PluginError as exc:
        return {"ok": False, "error": exc.as_dict()}
    except Exception as exc:  # never turn a bug into an MCP protocol failure
        return {
            "ok": False,
            "error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"},
        }


@server.tool(
    name="list_feeds",
    description=(
        "One compact row per jobs.yaml feed: name, description, cadence, live "
        "freshness (the existing max-date or min-count rule), age versus cadence, "
        "last run and its outcome, net-heavy flag, approved yes/no and approved "
        "max_days. approved_path is the file a human edits; unknown_approved lists "
        "approvals for feeds the registry does not have. Read-only."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def list_feeds() -> dict[str, Any]:
    return _safe(lambda: gather.service().list_feeds())


@server.tool(
    name="gap_report",
    description=(
        "Per feed, expected dates versus dates actually present and the missing "
        "ranges. Expected dates are NSE trading days from the index bhavcopy; the "
        "window is the cadence lookback (daily 30d, weekly 120d, monthly 400d). "
        "Feeds whose writes are not dated market tables (mkt_/etf_/index_) are "
        "reported not_a_market_feed instead of guessed at. Read-only and bounded "
        "by a 20s deadline."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def gap_report(names: list[str] | None = None) -> dict[str, Any]:
    return _safe(lambda: gather.service().gap_report(names))


@server.tool(
    name="run_feed",
    description=(
        "Start one feed from jobs.yaml through the dsh-worker supervisor (same "
        "lease, status records and db:/net: resource locks as start_job). Refuses "
        "unless the feed is listed in plugins/data-gather/approved.yaml, refuses a "
        "net-heavy feed during peak hours (Mon-Fri 06:30-09:30 and 11:30-15:30 "
        "IST), and refuses a date window longer than the feed's approved max_days. "
        "start/end (YYYY-MM-DD) replace the job's {start}/{date} tokens; omit both "
        "to keep the job's own default window. Returns run_id, or an error with "
        "code resource_busy when another job holds a needed lock. No paid or GPU "
        "feed is special-cased here; approval is the gate."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, open_world_hint=True
    ),
)
def run_feed(
    name: str, start: str | None = None, end: str | None = None
) -> dict[str, Any]:
    return _safe(lambda: gather.service().run_feed(name, start, end))


@server.tool(
    name="feed_status",
    description=(
        "Phase, outcome, exit code and at most 40 lines each of stdout and stderr "
        "for a run id (a feed name resolves to its newest run). Never returns the "
        "full log. Read-only."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def feed_status(run_id: str) -> dict[str, Any]:
    return _safe(lambda: gather.service().feed_status(run_id))


@server.tool(
    name="verify_feed",
    description=(
        "Pass/fail per check for a run started by run_feed: row counts before vs "
        "after and the new max date for every table in the feed's writes; the "
        "first 5 new rows' stored date against the source's known_at/filing date "
        "(doc_date is a crawl date and is never used as evidence); raw files "
        "landed under REALITY_RAW_ROOT and none landed under the data root. "
        "ok=false means at least one check failed; ok=null checks are reported as "
        "not applicable (no snapshot baseline, no source-date column, missing raw "
        "root). Refuses while the run is not final. Read-only."
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    ),
)
def verify_feed(name: str, run_id: str) -> dict[str, Any]:
    return _safe(lambda: gather.service().verify_feed(name, run_id))


def main() -> int:
    try:
        server.run("stdio")
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
