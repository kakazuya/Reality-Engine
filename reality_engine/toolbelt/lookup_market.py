"""One-call market lookups from the shell (same functions the MCP tools expose).

    python -m reality_engine.toolbelt.lookup_market delivery ATHERENERG 2026-04-13 2026-04-14
    python -m reality_engine.toolbelt.lookup_market price_extreme 532810
    python -m reality_engine.toolbelt.lookup_market holding LUMAXTECH --as-of 2026-09-30

Prints JSON so a worker without the reality-data MCP gets the same answer.  Read
only; the logic lives in plugins/reality-data/server/lookups_market.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ._common import main_guard

# lookups_market.py imports core.py by filename, so the server dir must be on sys.path.
_SERVER_DIR = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))


def _module() -> Any:
    import lookups_market  # noqa: WPS433 - deferred so --help works without the data root
    return lookups_market


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m reality_engine.toolbelt.lookup_market",
        description="One-call market lookups (delivery / price_extreme / holding) as JSON.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_delivery = sub.add_parser("delivery", help="deliverable qty + delivery %% per exchange")
    p_delivery.add_argument("symbol", help="NSE symbol, BSE code, ISIN or company name")
    p_delivery.add_argument("dates", nargs="+", help="one or more YYYY-MM-DD dates")
    p_delivery.add_argument("--end", help="with a single date, extend to an inclusive span")

    p_extreme = sub.add_parser("price_extreme", help="YTD/selected-window high/low per exchange")
    p_extreme.add_argument("symbol", help="NSE symbol, BSE code, ISIN or company name")
    p_extreme.add_argument("--start", help="YYYY-MM-DD (default: Jan 1 of the snapshot date)")
    p_extreme.add_argument("--end", help="YYYY-MM-DD (default: snapshot last date)")
    p_extreme.add_argument("--kind", choices=("high", "low", "both"), default="high")
    p_extreme.add_argument("--adjusted", action="store_true", help="use adjusted prices")

    p_holding = sub.add_parser("holding", help="promoter %%, public %%, total shares, candidates")
    p_holding.add_argument("symbol", help="NSE symbol, BSE code, ISIN or company name")
    p_holding.add_argument("--as-of", dest="as_of", help="YYYY-MM-DD (default: today)")

    args = parser.parse_args(argv)
    module = _module()
    if args.command == "delivery":
        dates: Any = args.dates if (len(args.dates) > 1 or not args.end) else args.dates[0]
        if len(args.dates) > 1 and args.end:
            parser.error("pass several dates OR one date with --end")
        result = module.delivery(args.symbol, dates, end=args.end)
    elif args.command == "price_extreme":
        result = module.price_extreme(args.symbol, start=args.start, end=args.end,
                                      kind=args.kind, adjusted=args.adjusted)
    else:
        result = module.holding(args.symbol, as_of=args.as_of)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    main_guard(main)
