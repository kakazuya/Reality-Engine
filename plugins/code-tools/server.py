"""code-tools MCP server (stdio): ``outline`` and ``typecheck``, both run-and-exit.

Nothing stays resident.  ``outline`` parses one file with ``ast`` and
``typecheck`` runs basedpyright once and lets it exit, so a worker pays no
~800 MB language server between calls.  Both tools are read-only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

import tools

INSTRUCTIONS = """Two run-and-exit code tools for this checkout; no language server stays resident.

outline(file) — every class, function and method with its line range, in one call. Prefer it to reading a whole file.
typecheck(files) — run basedpyright once over the .py files you changed, before you report done; returns errors, error_count and seconds.

Paths are relative to CODE_TOOLS_ROOT (this worker's checkout). Use read/grep/glob for everything else."""

server = MCPServer(name="code-tools", version="0.1.0", instructions=INSTRUCTIONS)

_RO = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
_ROOT = Path(os.environ.get("CODE_TOOLS_ROOT") or Path.cwd()).resolve()


def _safe(call) -> dict[str, Any]:
    try:
        return {"ok": True, **call()}
    except Exception as exc:  # a tool error must not become an MCP protocol failure
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@server.tool(
    name="outline",
    description=(
        "Symbols in one Python file, in source order: name, kind (class/function/"
        "method), line, end_line, parent class and the first docstring line. One "
        "call instead of reading the file whole."
    ),
    annotations=_RO,
)
def outline(file: str) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        path = Path(file)
        path = path if path.is_absolute() else _ROOT / path
        return {"file": tools._relative(str(path), _ROOT), "symbols": tools.outline(path)}
    return _safe(run)


@server.tool(
    name="typecheck",
    description=(
        "Type-check the given files with one basedpyright run (--outputjson, the "
        "repo's pyrightconfig.json, 120 s cap) and exit. Returns errors as "
        "{file, line, message}, error_count and seconds. Run it on every changed "
        ".py file once before reporting."
    ),
    annotations=_RO,
)
def typecheck(files: list[str]) -> dict[str, Any]:
    return _safe(lambda: tools.typecheck(files, root=_ROOT))


def main() -> int:
    try:
        server.run("stdio")
    except (KeyboardInterrupt, BrokenPipeError):
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
