"""CLI for the one-call document lookups (same functions as the MCP tools).

    python -m reality_engine.toolbelt.lookup_docs docs GANECOS --doc-type deck \\
        --from 2026-08-01 --to 2026-08-10
    python -m reality_engine.toolbelt.lookup_docs doc_page 540879 2026-10-24 21
    python -m reality_engine.toolbelt.lookup_docs doc_find COCHINSHIP "KSOE" \\
        --doc-type transcript --date 2026-09-18

Prints the tool result as JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SERVER_DIR = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"


def _module() -> Any:
    if str(_SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(_SERVER_DIR))
    import lookups_docs  # type: ignore
    return lookups_docs


def docs(symbol: str, doc_type: str | None = None, date_from: str | None = None,
         date_to: str | None = None, limit: int = 20) -> dict[str, Any]:
    return _module().docs(symbol, doc_type=doc_type, date_from=date_from, date_to=date_to,
                          limit=limit)


def doc_page(symbol: str, date: str, page: int, doc_type: str | None = None) -> dict[str, Any]:
    return _module().doc_page(symbol, date, page, doc_type=doc_type)


def doc_find(symbol: str, terms: str, doc_type: str | None = None, date: str | None = None,
             top_k: int = 8) -> dict[str, Any]:
    return _module().doc_find(symbol, terms, doc_type=doc_type, date=date, top_k=top_k)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m reality_engine.toolbelt.lookup_docs",
        description="List a company's documents, read one page, or find a passage.")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("docs", help="list documents across all stores")
    p.add_argument("symbol", help="NSE/BSE symbol, ISIN or company name")
    p.add_argument("--doc-type", help="deck | transcript | ar | announcement")
    p.add_argument("--from", dest="date_from", help="filing date lower bound (YYYY-MM-DD)")
    p.add_argument("--to", dest="date_to", help="filing date upper bound (YYYY-MM-DD)")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("doc_page", help="one page of the document nearest a date")
    p.add_argument("symbol")
    p.add_argument("date", help="YYYY-MM-DD")
    p.add_argument("page", type=int)
    p.add_argument("--doc-type", help="deck | transcript | ar | announcement")

    p = sub.add_parser("doc_find", help="lexical search inside a company's documents")
    p.add_argument("symbol")
    p.add_argument("terms", help="words to find, e.g. 'fuel cell'")
    p.add_argument("--doc-type", help="deck | transcript | ar | announcement")
    p.add_argument("--date", help="filing date, matched within ±3 days")
    p.add_argument("--top-k", type=int, default=8)

    args = ap.parse_args(argv)
    if args.command == "docs":
        result = docs(args.symbol, args.doc_type, args.date_from, args.date_to, args.limit)
    elif args.command == "doc_page":
        result = doc_page(args.symbol, args.date, args.page, args.doc_type)
    else:
        result = doc_find(args.symbol, args.terms, args.doc_type, args.date, args.top_k)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
