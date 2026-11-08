"""T-124: call one reality-data pilot3 lookup from the shell, against any build (``--db``).

The reality-data MCP serves one database per server start (``REALITY_PILOT3_DB``); a test store (q12, a hold-out)
needs its own server.  This CLI runs the SAME lookup code the MCP tools run (``lookups_pilot3`` and ``calc``), so a
subagent with only a shell asks the test store exactly as a model would ask the MCP.

    python -m reality_engine.scripts.p3ask --db <file.db> kpi symbol=KIMS kpi=occupancy period=Q1FY27
    python -m reality_engine.scripts.p3ask --db <file.db> sql "query=SELECT COUNT(*) FROM doc"
    python -m reality_engine.scripts.p3ask --db <file.db> calc "expression=a/b" 'inputs={"a": 1, "b": 2}'

Tools: kpi fin ratio holding statements guidance docs search tech sql calc (the ``pilot3_`` prefix is optional).
A value that parses as JSON (numbers, true/false, objects) is passed as that type, otherwise as text.
Prints the reply as JSON (UTF-8).  Read-only: the lookups open the database read-only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"
TOOLS = ("kpi", "fin", "ratio", "holding", "statements", "guidance", "docs", "search", "tech", "sql", "calc")


def _value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def run(db: str, tool: str, args: dict) -> dict:
    os.environ["REALITY_PILOT3_DB"] = db
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))
    name = tool.removeprefix("pilot3_")
    if name not in TOOLS:
        return {"error": f"unknown tool {tool!r}; choose from {', '.join(TOOLS)}"}
    try:
        if name == "calc":
            import calc
            return calc.evaluate(args.get("expression", ""), args.get("inputs"))
        if name == "tech":
            import lookups_tech
            return lookups_tech.tech(**args)
        import lookups_pilot3 as p3
        return getattr(p3, name)(**args)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:  # the MCP's _safe returns errors as data, so does this
        return {"error": f"{type(exc).__name__}: {exc}"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3 or argv[0] != "--db":
        print(__doc__)
        return 2
    db, tool, rest = argv[1], argv[2], argv[3:]
    args = {}
    for item in rest:
        key, sep, val = item.partition("=")
        if not sep:
            print(json.dumps({"error": f"argument {item!r} is not key=value"}))
            return 2
        args[key] = _value(val)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run(db, tool, args), ensure_ascii=False, default=str, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
