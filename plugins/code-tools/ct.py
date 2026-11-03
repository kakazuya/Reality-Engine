"""Command-line form of the code-tools MCP: JSON out, run and exit.

    python plugins/code-tools/ct.py outline path/to/file.py
    python plugins/code-tools/ct.py typecheck path/to/a.py path/to/b.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import tools


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ct.py", description="Run-and-exit code tools: outline and typecheck, JSON on stdout."
    )
    commands = ap.add_subparsers(dest="command", required=True)
    outline_cmd = commands.add_parser("outline", help="symbols in one Python file")
    outline_cmd.add_argument("file")
    check_cmd = commands.add_parser("typecheck", help="one basedpyright run over the given files")
    check_cmd.add_argument("files", nargs="+")
    check_cmd.add_argument("--root", default=None,
                           help="checkout holding pyrightconfig.json (default: CODE_TOOLS_ROOT or cwd)")
    args = ap.parse_args(argv)
    try:
        if args.command == "outline":
            path = Path(args.file)
            result = {"file": path.as_posix(), "symbols": tools.outline(path)}
        else:
            result = tools.typecheck(args.files, root=args.root)
    except Exception as exc:  # a tool error is still JSON for the caller
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
