"""code-intel CLI for dsh workers: ask the checkout instead of grepping it.

Run from the worktree you are standing in (paths are relative to that root):

    python plugins/code-intel/ci.py definition period_bounds
    python plugins/code-intel/ci.py references period_bounds --limit 20
    python plugins/code-intel/ci.py outline reality_engine/query/planners/screen.py
    python plugins/code-intel/ci.py module_map reality_engine/query
    python plugins/code-intel/ci.py symbols connect_ro
    python plugins/code-intel/ci.py diagnostics reality_engine/query/planners/screen.py

JSON on stdout, exit code 0 on success and 1 on an error payload.  definition,
references, symbols, outline and module_map answer from the ast index
(``astindex.py``, mtime-invalidated, cached under ``<root>/.tmp``) and never
start a language server; only ``diagnostics`` starts basedpyright (cold ~3-10 s,
then warm per file).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

import astindex  # noqa: E402


def default_root() -> Path:
    """The checkout this script lives in: ``<root>/plugins/code-intel/ci.py``."""
    return PLUGIN_DIR.parents[1]


def core_module(root: Path):
    """Import ``server/core.py`` against ``root`` (only the LSP-backed commands need it)."""
    server_dir = PLUGIN_DIR / "server"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    os.environ.setdefault("CODE_INTEL_REPO_ROOT", str(root))
    import core  # noqa: PLC0415  (deliberate: keeps the fast paths free of the LSP client)

    core.REPO_ROOT = root
    return core


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def fail(command: str, code: str, message: str, started: float) -> int:
    emit({"ok": False, "command": command, "error": {"code": code, "message": message},
          "elapsed_ms": int((time.monotonic() - started) * 1000)})
    return 1


def _index_payload(index: dict) -> dict:
    return {"source": "ast", "indexed": index.get("indexed"), "reparsed": index.get("reparsed")}


def command_definition(root: Path, symbol: str, started: float) -> int:
    index = astindex.load(root)
    hits = astindex.definitions(index, symbol)
    if not hits:
        return fail("definition", "not_found", f"no symbol matching {symbol!r}", started)
    payload = {"ok": True, "command": "definition", "root": str(root), "symbol": symbol,
               "count": len(hits), "definitions": hits}
    payload.update(_index_payload(index))
    payload["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    emit(payload)
    return 0


def command_references(root: Path, symbol: str, limit: int, started: float) -> int:
    index = astindex.load(root)
    hits, total = astindex.references(index, symbol, limit=limit)
    if not total:
        return fail("references", "not_found", f"{symbol!r} appears in no indexed file", started)
    payload = {"ok": True, "command": "references", "root": str(root), "symbol": symbol,
               "count": len(hits), "total": total, "limit": limit,
               "truncated": total > len(hits), "references": hits}
    payload.update(_index_payload(index))
    payload["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    emit(payload)
    return 0


def command_symbols(root: Path, query: str, limit: int, started: float) -> int:
    index = astindex.load(root)
    hits, total = astindex.search_names(index, query, limit=limit)
    payload = {"ok": True, "command": "symbols", "root": str(root), "query": query,
               "count": len(hits), "total": total, "truncated": total > len(hits), "symbols": hits}
    payload.update(_index_payload(index))
    payload["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    emit(payload)
    return 0


def command_outline(root: Path, file: str, limit: int, started: float) -> int:
    core = core_module(root)
    try:
        payload = dict(core.symbols(file=file, limit=limit))
    except Exception as exc:  # CodeIntelError carries a machine-readable code
        return fail("outline", getattr(exc, "code", "internal_error"),
                    getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}", started)
    payload.update({"command": "outline", "root": str(root), "source": "ast",
                    "elapsed_ms": int((time.monotonic() - started) * 1000)})
    emit(payload)
    return 0


def command_module_map(root: Path, package: str, limit: int, started: float) -> int:
    core = core_module(root)
    try:
        payload = dict(core.module_map(package, limit=limit))
    except Exception as exc:
        return fail("module_map", getattr(exc, "code", "internal_error"),
                    getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}", started)
    payload.update({"command": "module_map", "root": str(root), "source": "ast",
                    "elapsed_ms": int((time.monotonic() - started) * 1000)})
    emit(payload)
    return 0


def command_diagnostics(root: Path, files: list[str], changed: bool, started: float) -> int:
    if not files and not changed:
        return fail("diagnostics", "bad_request", "pass at least one file, or --changed", started)
    core = core_module(root)
    cold = core._server.started_at is None  # noqa: SLF001  (reported, not acted on)
    try:
        payload = dict(core.diagnostics(files=files, changed=changed))
    except Exception as exc:
        return fail("diagnostics", getattr(exc, "code", "internal_error"),
                    getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}", started)
    payload.update({"command": "diagnostics", "root": str(root), "source": "lsp",
                    "language_server": "cold" if cold else "warm",
                    "elapsed_ms": int((time.monotonic() - started) * 1000)})
    emit(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ci.py", description="code-intel for dsh workers (JSON on stdout)")
    parser.add_argument("--root", default=None,
                        help="checkout root (default: this script's checkout, then CODE_INTEL_REPO_ROOT)")
    sub = parser.add_subparsers(dest="command", required=True)
    item = sub.add_parser("definition", help="where a symbol is defined")
    item.add_argument("symbol")
    item = sub.add_parser("references", help="every line that mentions a name")
    item.add_argument("symbol")
    item.add_argument("--limit", type=int, default=50)
    item = sub.add_parser("symbols", help="workspace symbol search by name substring")
    item.add_argument("query")
    item.add_argument("--limit", type=int, default=100)
    item = sub.add_parser("outline", help="classes/functions/methods of one module")
    item.add_argument("file")
    item.add_argument("--limit", type=int, default=300)
    item = sub.add_parser("module_map", help="one line of purpose per module in a package")
    item.add_argument("package", nargs="?", default="reality_engine")
    item.add_argument("--limit", type=int, default=300)
    item = sub.add_parser("diagnostics", help="type/import errors (starts basedpyright)")
    item.add_argument("files", nargs="*")
    item.add_argument("--changed", action="store_true", help="the git-changed Python files")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.monotonic()
    root = Path(args.root).resolve() if args.root else \
        Path(os.environ.get("CODE_INTEL_REPO_ROOT") or default_root()).resolve()
    if not (root / "reality_engine").is_dir() and not (root / "plugins").is_dir() \
            and not (root / "pyrightconfig.json").is_file():
        return fail(args.command, "not_found", f"{root} does not look like the repo root", started)
    if args.command == "definition":
        return command_definition(root, args.symbol, started)
    if args.command == "references":
        return command_references(root, args.symbol, args.limit, started)
    if args.command == "symbols":
        return command_symbols(root, args.query, args.limit, started)
    if args.command == "outline":
        return command_outline(root, args.file, args.limit, started)
    if args.command == "module_map":
        return command_module_map(root, args.package, args.limit, started)
    return command_diagnostics(root, args.files, args.changed, started)


if __name__ == "__main__":
    sys.exit(main())
