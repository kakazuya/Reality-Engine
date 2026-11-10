from __future__ import annotations
import json, os, sys, time
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"
_BASE_TOOLS = ("kpi","fin","ratio","holding","statements","guidance","docs","search","semantic","tech","ratings","sql","calc","catalog")

def _no_sql():
    return os.environ.get("P3ASK_NO_SQL") == "1"

def _tools():
    if _no_sql():
        return tuple(t for t in _BASE_TOOLS if t != "sql")
    return _BASE_TOOLS

TOOLS = _tools()

def _value(text):
    try: return json.loads(text)
    except ValueError: return text

def _append_log(log_path, record):
    p = Path(log_path)
    try: p.parent.mkdir(parents=True, exist_ok=True)
    except Exception: pass
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

def run(db, tool, args, qid=None, log=None):
    if qid is None: qid = os.environ.get("P3ASK_QID")
    if log is None: log = os.environ.get("P3ASK_LOG")
    ts_start = time.time()
    os.environ["REALITY_PILOT3_DB"] = db
    if str(SERVER) not in sys.path: sys.path.insert(0, str(SERVER))
    name = tool.removeprefix("pilot3_")
    if name == "sql" and _no_sql():
        reply = {"error": "sql tool is not available in this run; use the typed tools"}
    elif name not in _tools():
        reply = {"error": "unknown tool %r; choose from %s" % (tool, ", ".join(_tools()))}
    else:
        try:
            if name == "calc":
                import calc; reply = calc.evaluate(args.get("expression",""), args.get("inputs"))
            elif name == "catalog":
                import calc_catalog; reply = calc_catalog.run(args)
            elif name == "semantic":
                import lookups_semantic; reply = lookups_semantic.semantic(**args)
            elif name == "tech":
                import lookups_tech; reply = lookups_tech.tech(**args)
            elif name == "ratings":
                import lookups_ratings; reply = lookups_ratings.ratings(**args)
            else:
                import lookups_pilot3 as p3; reply = getattr(p3, name)(**args)
        except TypeError as exc:
            reply = {"error": "bad arguments for %s: %s" % (name, exc)}
        except Exception as exc:
            reply = {"error": "%s: %s" % (type(exc).__name__, exc)}
    ts_end = time.time()
    if log:
        try:
            rows_returned = None
            if isinstance(reply, list): rows_returned = len(reply)
            elif isinstance(reply, dict):
                for v in reply.values():
                    if isinstance(v, list):
                        rows_returned = len(v); break
            ok = not (isinstance(reply, dict) and "error" in reply)
            reply_bytes = len(json.dumps(reply, ensure_ascii=False, default=str).encode("utf-8"))
            record = {"ts_start": ts_start, "ts_end": ts_end, "seconds": ts_end-ts_start,
                      "qid": qid, "tool": tool,
                      "args": json.dumps(args, ensure_ascii=False, default=str)[:300],
                      "ok": ok, "reply bytes": reply_bytes, "reply_bytes": reply_bytes}
            if rows_returned is not None:
                record["rows returned"] = rows_returned
                record["rows_returned"] = rows_returned
            _append_log(log, record)
        except Exception: pass
    return reply

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    db = None; qid = os.environ.get("P3ASK_QID"); log = os.environ.get("P3ASK_LOG")
    tool = None; rest = []; i = 0
    while i < len(argv):
        if argv[i] == "--db":
            db = argv[i+1]; i += 2; continue
        if argv[i] == "--qid":
            qid = argv[i+1]; i += 2; continue
        if argv[i] == "--log":
            log = argv[i+1]; i += 2; continue
        if db is not None and tool is None and not argv[i].startswith("--"):
            tool = argv[i]; i += 1; continue
        rest.append(argv[i]); i += 1
    if db is None or tool is None:
        print("usage"); return 2
    args = {}
    for item in rest:
        key, sep, val = item.partition("=")
        if not sep:
            print(json.dumps({"error": "argument %r is not key=value" % item})); return 2
        args[key] = _value(val)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    reply = run(db, tool, args, qid=qid, log=log)
    print(json.dumps(reply, ensure_ascii=False, default=str, indent=1))
    return 0

if __name__ == "__main__":
    sys.exit(main())
