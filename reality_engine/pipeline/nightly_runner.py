"""
Nightly Runner (thin wrapper over the missed-days catcher).

Exposes ``run_nightly(mode)`` which delegates to
``reality_engine.pipeline.catchup_scheduler.run_catchup``. The twice-daily
scheduled task (Windows Task Scheduler / cron) targets this module (or the
catcher module directly) at 16:00 IST (pre-close) and 23:00 IST (post-close).

Owns ONLY this file. Never edits peer processing modules.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Sequence

# Allow direct execution.
_PROJECT_ROOT = __file__.resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from reality_engine.pipeline.catchup_scheduler import run_catchup  # noqa: E402


def run_nightly(mode: str = "auto", dry_run: bool = False, universe: str = "nifty200") -> dict:
    """Run the full nightly improvement loop (catches up any missed days first)."""
    return run_catchup(dry_run=dry_run, mode=mode, universe=universe)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Reality Engine nightly runner.")
    parser.add_argument("--mode", choices=["auto", "pre-close", "post-close"], default="auto")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--universe", default="nifty200")
    args = parser.parse_args(argv)
    summary = run_nightly(mode=args.mode, dry_run=args.dry_run, universe=args.universe)
    import json
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
