"""code-intel MCP server (stdio).

Ask the language server instead of grepping: where is X defined, who calls it,
what does this module expose, what type errors does my diff have.  One
long-lived ``basedpyright-langserver`` child is started in a background thread
after the handshake is answered, so ``initialize`` never waits for the index.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

import core

INSTRUCTIONS = """LSP code intelligence for this checkout. Ask instead of grepping: definition() finds where a
symbol is defined, references() every use, callers() only the call sites, symbols() a module outline or a workspace
name search, hover() the signature and docstring at a position, diagnostics() the type/import errors of given files
or of the git-changed files, module_map() one line of purpose per module. Every path is relative to the repo root.

Examples: definition("connect_ro"); references("connect_ro", limit=50); callers("connect_ro");
symbols("reality_engine/db/readonly.py"); symbols(query="connect_ro"); hover("reality_engine/db/readonly.py", 40, 5);
diagnostics(changed=True); module_map("reality_engine/processing"). Prefer these over grep + reading whole files:
one call replaces a search and a 500-line read. Errors come back as {ok: false, error}."""

server = MCPServer(name="code-intel", version="0.1.0", instructions=INSTRUCTIONS)


def _safe(call) -> dict[str, Any]:
    try:
        return call()
    except (core.CodeIntelError, core.LspError) as exc:
        return {"ok": False, "error": exc.as_dict()}
    except Exception as exc:  # never turn a tool bug into an MCP protocol failure
        return {"ok": False, "error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}}


_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


@server.tool(
    name="definition",
    description=(
        "Where a symbol is defined. definition(symbol='connect_ro') resolves a name through "
        "the workspace index; definition(file='reality_engine/db/readonly.py', line=40, col=5) "
        "asks the language server at a position. Returns file:line plus a 5-line snippet, "
        "paths relative to the repo root."
    ),
    annotations=_READ_ONLY,
)
def definition(symbol: str | None = None, file: str | None = None, line: int | None = None,
               col: int | None = None) -> dict[str, Any]:
    return _safe(lambda: core.definition(symbol=symbol, file=file, line=line, col=col))


@server.tool(
    name="references",
    description=(
        "Every use of a symbol (declaration excluded). references(symbol='connect_ro') or "
        "references(file=..., line=..., col=...). Each hit is file:line plus the line text; "
        "limit defaults to 50 and is capped at 500. Sorted by file then line."
    ),
    annotations=_READ_ONLY,
)
def references(symbol: str | None = None, file: str | None = None, line: int | None = None,
               col: int | None = None, limit: int = 50) -> dict[str, Any]:
    return _safe(lambda: core.references(symbol=symbol, file=file, line=line, col=col, limit=limit))


@server.tool(
    name="callers",
    description=(
        "Only the call sites of a function (references filtered to lines that call it, "
        "imports excluded). callers('connect_ro') answers 'who calls this' in one call."
    ),
    annotations=_READ_ONLY,
)
def callers(function: str, limit: int = 50) -> dict[str, Any]:
    return _safe(lambda: core.callers(function, limit=limit))


@server.tool(
    name="symbols",
    description=(
        "symbols(file='plugins/dsh-worker/server/core.py') is the module outline: classes, "
        "functions and methods with line numbers and the first docstring line (instant, read "
        "with ast). symbols(query='connect_ro') is a workspace-wide symbol search by name "
        "substring."
    ),
    annotations=_READ_ONLY,
)
def symbols(file: str | None = None, query: str | None = None, limit: int = 100) -> dict[str, Any]:
    return _safe(lambda: core.symbols(file=file, query=query, limit=limit))


@server.tool(
    name="hover",
    description=(
        "Signature plus docstring at a position: hover('reality_engine/db/readonly.py', 40, 5). "
        "line and col are 1-based. Use it after a grep hit to learn what a symbol is without "
        "reading the file."
    ),
    annotations=_READ_ONLY,
)
def hover(file: str, line: int, col: int = 1) -> dict[str, Any]:
    return _safe(lambda: core.hover(file, line, col=col))


@server.tool(
    name="diagnostics",
    description=(
        "Type and import errors for files: diagnostics(files=['reality_engine/db/readonly.py']) "
        "or diagnostics(changed=True) for the git-changed/untracked Python files (max 20 files, "
        "100 diagnostics per file, ~25 s budget). Returns line, col, severity, code and message. "
        "Run it on your diff before reporting done."
    ),
    annotations=_READ_ONLY,
)
def diagnostics(files: list[str] | None = None, changed: bool = False) -> dict[str, Any]:
    return _safe(lambda: core.diagnostics(files=files, changed=changed))


@server.tool(
    name="module_map",
    description=(
        "One line of purpose per module in a package, from each module docstring: "
        "module_map('reality_engine/processing') or module_map('plugins'). Cheap orientation "
        "before opening any file."
    ),
    annotations=_READ_ONLY,
)
def module_map(package: str = "reality_engine", limit: int = 300) -> dict[str, Any]:
    return _safe(lambda: core.module_map(package, limit=limit))


def _warm() -> None:
    # 2026-10-24 reality-data lesson: warming before server.run() delays the initialize
    # reply past the client's version probe, so the language server starts in the background.
    threading.Thread(target=core.warm, name="code-intel-warm", daemon=True).start()


def main() -> int:
    core.lifecycle("start")
    _warm()
    reason = "stdin closed by client"
    try:
        server.run("stdio")
    except KeyboardInterrupt:
        reason = "KeyboardInterrupt"
        return 0
    except BrokenPipeError:
        reason = "BrokenPipeError"
        return 0
    except BaseException as exc:
        reason = f"crash {type(exc).__name__}: {exc}"
        raise
    finally:
        core.lifecycle(f"exit ({reason})")
        core.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
