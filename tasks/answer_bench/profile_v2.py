"""Profile every hop of the 150-case bench: per planner, per SQL statement, per tool call.

Run against whatever ``reality_engine.query`` is on disk right now:

    python tasks/answer_bench/profile_v2.py [--out profile_before.json]

It times ``ReadOnlyCursor`` statements (execute + fetchall) for every
``connect_ro`` connection, the plugin helper calls (``_run_sqlite`` /
``_run_duck``) and every ``Ctx.tool`` call, then writes the per-hop totals, the
top-20 slow statements (with their params, so ``EXPLAIN QUERY PLAN`` can be
reproduced) and the top tool calls. Read-only on every database.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import reality_engine.db.readonly as RO  # noqa: E402

_RECORDS: list[dict] = []
_TOOLS: list[dict] = []
_LOCK = threading.Lock()
_SKIP = ("PRAGMA", "SELECT name FROM sqlite_master")


def _short(value, limit=300):
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _emit(rec: dict) -> None:
    if rec.get("sql", "").lstrip().upper().startswith(_SKIP):
        return
    with _LOCK:
        _RECORDS.append(rec)


_orig_connect = RO.connect_ro


def _connect(path, *args, **kwargs):
    con = _orig_connect(path, *args, **kwargs)
    con._prof_db = str(path)
    return con


RO.connect_ro = _connect

_orig_exec = RO.ReadOnlyCursor.execute
_orig_fetchall = RO.ReadOnlyCursor.fetchall
_orig_fetchone = RO.ReadOnlyCursor.fetchone


def _exec(self, sql, parameters=()):
    started = time.perf_counter()
    cur = _orig_exec(self, sql, parameters)
    self._prof = {"db": getattr(self.connection, "_prof_db", "?"),
                  "sql": " ".join(str(sql).split())[:600],
                  "params": [str(v)[:120] if not isinstance(v, (int, float, type(None))) else v
                             for v in (parameters if isinstance(parameters, (list, tuple)) else [parameters])],
                  "seconds": time.perf_counter() - started,
                  "thread": threading.get_ident()}
    return cur


def _fetchall(self):
    started = time.perf_counter()
    try:
        return _orig_fetchall(self)
    finally:
        rec = getattr(self, "_prof", None)
        if rec is not None:
            rec["seconds"] += time.perf_counter() - started
            self._prof = None
            _emit(rec)


def _fetchone(self):
    started = time.perf_counter()
    try:
        return _orig_fetchone(self)
    finally:
        rec = getattr(self, "_prof", None)
        if rec is not None:
            rec["seconds"] += time.perf_counter() - started
            self._prof = None
            _emit(rec)


RO.ReadOnlyCursor.execute = _exec
RO.ReadOnlyCursor.fetchall = _fetchall
RO.ReadOnlyCursor.fetchone = _fetchone

sys.path.insert(0, str(REPO / "plugins" / "reality-data" / "server"))
import core  # noqa: E402
import lookups_docs  # noqa: E402


def _wrap(fn, db):
    def wrapped(sql, params=(), *args, **kwargs):
        started = time.perf_counter()
        try:
            return fn(sql, params, *args, **kwargs)
        finally:
            _emit({"db": db, "sql": " ".join(str(sql).split())[:600],
                   "params": [str(v)[:120] if not isinstance(v, (int, float, type(None))) else v
                              for v in (params if isinstance(params, (list, tuple)) else [params])],
                   "seconds": time.perf_counter() - started,
                   "thread": threading.get_ident()})
    return wrapped


lookups_docs._run_sqlite = _wrap(lookups_docs._run_sqlite, "<plugin sqlite>")
lookups_docs._run_duck = _wrap(lookups_docs._run_duck, "<plugin duckdb>")

import run_bench  # noqa: E402
from reality_engine.query import Ctx, answer  # noqa: E402

_orig_tool = Ctx.tool


def _tool(self, name):
    fn = _orig_tool(self, name)

    def wrapped(*args, **kwargs):
        started = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            with _LOCK:
                _TOOLS.append({"tool": name, "seconds": time.perf_counter() - started,
                               "thread": threading.get_ident()})
    return wrapped


Ctx.tool = _tool


def case_map() -> dict[str, dict]:
    path = REPO / "tasks" / "arch_v3" / "CASE_MAP.jsonl"
    return {row["mid"]: row for row in
            (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())}


def main(argv: list[str]) -> int:
    out = HERE / "profile_before.json"
    if "--out" in argv:
        out = HERE / argv[argv.index("--out") + 1]
    cmap = case_map()
    cases = run_bench.load_cases()
    ctx = Ctx()
    sys.path.insert(0, str(REPO / "plugins" / "reality-data" / "server"))
    import search_docs as _search_docs
    warm_started = time.perf_counter()
    try:
        _search_docs.warm()
    except Exception:  # noqa: BLE001 - corpus search will degrade
        pass
    warm_seconds = time.perf_counter() - warm_started
    hops: list[dict] = []
    cases_out: list[dict] = []
    started = time.perf_counter()
    for index, case in enumerate(cases, 1):
        row = dict(case)
        row["case_status"] = str(cmap.get(case["mid"], {}).get("status") or "")
        t0 = time.perf_counter()
        result = answer(row, ctx, close=False)
        seconds = time.perf_counter() - t0
        for sub in result["subs"]:
            for hop in sub["hops"]:
                hops.append({"mid": case["mid"], "hop": hop["hop"],
                             "seconds": hop.get("seconds", 0.0),
                             "ok": bool(hop.get("ok")), "na": bool(hop.get("na")),
                             "chain": sub["chain"]})
        cases_out.append({"mid": case["mid"], "seconds": round(seconds, 3)})
        print(f"{index:3d} {case['mid']} {seconds:6.2f}s", flush=True)
    ctx.close()
    elapsed = time.perf_counter() - started
    stmts = sorted(_RECORDS, key=lambda r: -r["seconds"])
    plans = []
    for rec in stmts[:20]:
        plan = []
        db = rec["db"]
        if db and Path(db).exists() and not db.startswith("<"):
            try:
                import sqlite3
                con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
                try:
                    for r in con.execute("EXPLAIN QUERY PLAN " + rec["sql"], ()):
                        plan.append(str(tuple(r)))
                finally:
                    con.close()
            except Exception as exc:  # noqa: BLE001
                plan = [f"explain failed: {type(exc).__name__}: {exc}"]
        plans.append({"db": db, "sql": rec["sql"], "params": rec["params"],
                      "seconds": round(rec["seconds"], 4), "plan": plan})
    grouped: dict[tuple, dict] = {}
    for rec in _RECORDS:
        key = (rec["db"], rec["sql"])
        item = grouped.setdefault(key, {"db": rec["db"], "sql": rec["sql"],
                                        "n": 0, "total": 0.0, "max": 0.0,
                                        "params": rec["params"]})
        item["n"] += 1
        item["total"] += rec["seconds"]
        item["max"] = max(item["max"], rec["seconds"])
    all_statements = [dict(item, total=round(item["total"], 3), max=round(item["max"], 3))
                      for item in sorted(grouped.values(), key=lambda x: -x["total"])[:40]]
    hops_by = {}
    for hop in hops:
        key = hop["hop"]
        item = hops_by.setdefault(key, {"n": 0, "total": 0.0, "max": 0.0})
        item["n"] += 1
        item["total"] += hop["seconds"]
        item["max"] = max(item["max"], hop["seconds"])
    tools_by = {}
    for tool in _TOOLS:
        item = tools_by.setdefault(tool["tool"], {"n": 0, "total": 0.0, "max": 0.0})
        item["n"] += 1
        item["total"] += tool["seconds"]
        item["max"] = max(item["max"], tool["seconds"])
    payload = {
        "cases": len(cases),
        "wall_seconds": round(elapsed, 1),
        "warm_seconds": round(warm_seconds, 1),
        "hop_totals": {k: {kk: round(vv, 3) for kk, vv in v.items()}
                       for k, v in sorted(hops_by.items(), key=lambda kv: -kv[1]["total"])},
        "tool_totals": {k: {kk: round(vv, 3) for kk, vv in v.items()}
                        for k, v in sorted(tools_by.items(), key=lambda kv: -kv[1]["total"])},
        "top_statements": plans,
        "all_statements": all_statements,
        "top_hops": sorted(hops, key=lambda h: -h["seconds"])[:25],
        "cases_seconds": cases_out,
    }
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\n{len(cases)} cases in {elapsed:.1f}s; {len(_RECORDS)} statements; wrote {out}")
    for name, item in payload["hop_totals"].items():
        print(f"  {name:12s} n={item['n']:4d} total={item['total']:8.1f}s max={item['max']:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
