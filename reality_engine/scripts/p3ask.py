"""T-124: call one reality-data pilot3 lookup from the shell, against any build (``--db``).

The reality-data MCP serves one database per server start (``REALITY_PILOT3_DB``); a test store (q12, a hold-out)
needs its own server.  ``semantic`` (T-154) ranks one company's pages by embedding; it reads the vectors in
``embed/`` next to the store and needs ``REALITY_DATA_ALLOW_PAID_EMBED=1`` for a new query text.  This CLI runs the SAME lookup code the MCP tools run (``lookups_pilot3`` and ``calc``), so a
subagent with only a shell asks the test store exactly as a model would ask the MCP.

    python -m reality_engine.scripts.p3ask --db <file.db> fact symbol=KIMS metric=revenue period=Q1FY27
    python -m reality_engine.scripts.p3ask --db <file.db> kpi symbol=KIMS kpi=occupancy period=Q1FY27
    python -m reality_engine.scripts.p3ask --db <file.db> sql "query=SELECT COUNT(*) FROM doc"
    python -m reality_engine.scripts.p3ask --db <file.db> calc "expression=a/b" 'inputs={"a": 1, "b": 2}'
    python -m reality_engine.scripts.p3ask --db <file.db> catalog name=GROWTH \
        'inputs={"now": "22,067 crore", "before": "19,332 crore"}'

Tools: fact cells kpi fin ratio holding statements guidance docs search semantic tech ratings sql calc catalog (the ``pilot3_``
prefix is optional).  ``ratings`` reads the outside-doc rating-rationale store (``REALITY_RATINGS_DB``, default
``D:/RealityEngine/outside_doc/ratings.db``) instead of ``--db``.  ``catalog name=list`` prints the named formulas;
each one returns value, unit, the substituted
formula text and the parsed inputs (``calc_catalog``).
A value that parses as JSON (numbers, true/false, objects) is passed as that type, otherwise as text.
Prints the reply as JSON (UTF-8).  Read-only: the lookups open the database read-only.

T-179: ``--qid <id>`` and ``--log <file.jsonl>`` (or env ``P3ASK_QID`` / ``P3ASK_LOG``), given before the tool
name, append one JSON line per call (ts_start, ts_end, seconds, qid, tool, args cut at 300 chars, ok, rows_returned,
reply_bytes); logging never changes the reply and never fails the call.  ``page doc_key=<key> page=<n> [to_page=<n>]``
returns page text (at most 5 pages) without raw SQL.  ``P3ASK_NO_SQL=1`` refuses the ``sql``
tool and leaves it out of the tool list (the no-SQL arm of the answer test).  ``P3ASK_NO_SEMANTIC=1`` does the same
for ``semantic`` (T-191: arm A of the semantic A/B, everything else identical).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"
TOOLS = ("fact", "cells", "kpi", "fin", "ratio", "holding", "statements", "guidance", "docs", "search", "semantic", "tech",
         "ratings", "page", "sql", "calc", "catalog")


def _value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def _page(p3, doc_key: str, page: int, to_page: int | None = None, as_of: str | None = None,
          max_chars: int = 8000) -> dict:
    """T-179: the text of one page (or ``page``..``to_page``, at most 5) of a held document, by its doc_key.

    The typed way to read a page, so the no-SQL arm of the answer test can still open the page a row cites.
    """
    if "'" in str(doc_key) or ";" in str(doc_key):
        return {"error": "doc_key must be the key printed by docs/search, unchanged"}
    first, last = int(page), int(to_page if to_page is not None else page)
    last = min(max(first, last), first + 4)
    query = ("SELECT doc_key, page, method, known_at, text FROM doc_page "
             f"WHERE doc_key = '{doc_key}' AND page BETWEEN {first} AND {last} ORDER BY page")
    return p3.sql(query, limit=5, max_chars=int(max_chars), as_of=as_of)


def _no_sql() -> bool:
    return os.environ.get("P3ASK_NO_SQL") == "1"


def _no_semantic() -> bool:
    return os.environ.get("P3ASK_NO_SEMANTIC") == "1"


def tools() -> tuple[str, ...]:
    return tuple(t for t in TOOLS
                 if not (t == "sql" and _no_sql()) and not (t == "semantic" and _no_semantic()))


def _log_call(log: str, qid: str | None, tool: str, args: dict, reply, ts_start: float, ts_end: float) -> None:
    """One JSON line per call; any failure here is swallowed so the lookup's reply is never affected."""
    try:
        rows = None
        if isinstance(reply, list):
            rows = len(reply)
        elif isinstance(reply, dict):
            lists = {k: len(v) for k, v in reply.items() if isinstance(v, list)}
            rows = lists.get("rows", max(lists.values())) if lists else None
        record = {"ts_start": ts_start, "ts_end": ts_end, "seconds": round(ts_end - ts_start, 4), "qid": qid,
                  "tool": tool.removeprefix("pilot3_"),
                  "args": json.dumps(args, ensure_ascii=False, default=str)[:300],
                  "ok": not (isinstance(reply, dict) and "error" in reply), "rows_returned": rows,
                  "reply_bytes": len(json.dumps(reply, ensure_ascii=False, default=str).encode("utf-8"))}
        path = Path(log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + chr(10))
    except Exception:
        pass


def run(db: str, tool: str, args: dict, qid: str | None = None, log: str | None = None) -> dict:
    qid = qid or os.environ.get("P3ASK_QID")
    log = log or os.environ.get("P3ASK_LOG")
    ts_start = time.time()
    reply = _run(db, tool, args)
    if log:
        _log_call(log, qid, tool, args, reply, ts_start, time.time())
    return reply


def _run(db: str, tool: str, args: dict) -> dict:
    os.environ["REALITY_PILOT3_DB"] = db
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))
    name = tool.removeprefix("pilot3_")
    if name == "sql" and _no_sql():
        return {"error": "sql tool is not available in this run; use the typed tools"}
    if name not in tools():
        return {"error": f"unknown tool {tool!r}; choose from {', '.join(tools())}"}
    try:
        if name == "calc":
            import calc
            return calc.evaluate(args.get("expression", ""), args.get("inputs"))
        if name == "catalog":
            import calc_catalog
            return calc_catalog.run(args)
        if name == "semantic":
            import lookups_semantic
            return lookups_semantic.semantic(**args)
        if name == "tech":
            import lookups_tech
            return lookups_tech.tech(**args)
        if name == "ratings":
            import lookups_ratings
            return lookups_ratings.ratings(**args)
        import lookups_pilot3 as p3
        if name == "page":
            return _page(p3, **args)
        return getattr(p3, name)(**args)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:  # the MCP's _safe returns errors as data, so does this
        return {"error": f"{type(exc).__name__}: {exc}"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    opts: dict[str, str] = {}
    while len(argv) >= 2 and argv[0] in ("--db", "--qid", "--log"):
        opts[argv[0][2:]] = argv[1]
        argv = argv[2:]
    if "db" not in opts or not argv:
        doc = __doc__ or ""
        print(doc.replace(" ratings sql calc", " ratings calc") if _no_sql() else doc)
        return 2
    db, tool, rest = opts["db"], argv[0], argv[1:]
    args = {}
    for item in rest:
        key, sep, val = item.partition("=")
        if not sep:
            print(json.dumps({"error": f"argument {item!r} is not key=value"}))
            return 2
        args[key] = _value(val)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run(db, tool, args, qid=opts.get('qid'), log=opts.get('log')), ensure_ascii=False, default=str, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
