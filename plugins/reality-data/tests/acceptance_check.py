#!/usr/bin/env python3
"""End-to-end acceptance check for the reality-data MCP server.

Speaks real MCP over stdio, warms every tool, then measures and asserts the
PPL acceptance case. Run from the repo root:

    python plugins/reality-data/tests/acceptance_check.py
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER = PLUGIN_ROOT / "server" / "server.py"
sys.path.insert(0, str(PLUGIN_ROOT / "server"))
import query_embed  # noqa: E402


def payload(result):
    data = getattr(result, "structured_content", None)
    if data is None:
        data = getattr(result, "structuredContent", None)
    if data is None:
        for block in result.content:
            if getattr(block, "type", None) == "text":
                data = json.loads(block.text)
                break
    if data is None:
        raise AssertionError(f"tool returned no JSON payload: {result!r}")
    return data


async def call(session, name, arguments, timeout=120):
    result = await session.call_tool(name, arguments, read_timeout_seconds=timeout)
    return payload(result)


async def timed(session, name, arguments, calls=5):
    await call(session, name, arguments)  # warm
    samples = []
    for _ in range(calls):
        t = time.perf_counter()
        await call(session, name, arguments)
        samples.append(round((time.perf_counter() - t) * 1000, 1))
    return samples, round(statistics.median(samples), 1), min(samples), max(samples)


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    failures = []
    report = {}
    providers = {}
    for index, question in (
        ("nemotron8b", "management commentary on demand slowdown in pipes"),
        ("qwen8b_ar", "segment revenue PVC pipes flexible packaging"),
    ):
        query_embed.clear_cache()
        try:
            t = time.perf_counter()
            vec = query_embed.embed_query(question, index)
            providers[index] = {"ok": True, "latency_ms": round((time.perf_counter() - t) * 1000, 1),
                                "dim": int(vec.shape[0])}
        except Exception as exc:
            providers[index] = {"ok": False, "error_type": type(exc).__name__,
                                "error": str(exc)[:200]}
    report["providers"] = providers
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            report["tools"] = tools

            resolved = await call(session, "resolve", {"query": "PPL"})
            m = resolved["matches"][0]
            report["resolve"] = {"isin": m["isin"], "name": m["name"], "symbol": m["nse_symbol"],
                                 "match_type": m["match_type"]}
            if m["isin"] != "INE050001010" or "PRAKASH PIPES" not in m["name"].upper():
                failures.append("resolve mismatch")

            priced = await call(session, "price", {"symbol": "PPL", "start": "2026-03-30"})
            close = priced["rows"][0]["close"]
            report["price"] = {"close": close, "adj_close": priced["rows"][0]["adj_close"],
                               "delivery_pct": priced["rows"][0]["delivery_pct"],
                               "delivery_qty": priced["rows"][0]["deliverable_qty"],
                               "value_inr": priced["rows"][0]["value_inr"]}
            if abs(close - 164.15) > 0.001:
                failures.append(f"price close {close} != 164.15")

            seg = await call(session, "facts", {"symbol": "PPL", "kind": "segments", "period": "FY25"})
            seg_values = {}
            for f in seg["facts"]:
                if f.get("source") == "ar_facts" and f.get("value") in (41302.0, 36746.0):
                    seg_values[f["item"]] = f["value"]
            report["segments"] = {"PVC Pipes & Fittings": 41302.0, "Flexible Packaging": 36746.0,
                                  "matched": len(seg_values) >= 2}
            if 41302.0 not in seg_values.values() or 36746.0 not in seg_values.values():
                failures.append("segment values missing")

            fin = await call(session, "facts", {"symbol": "PPL", "kind": "financials", "period": "FY26"})
            fy26 = [f for f in fin["facts"] if abs(float(f.get("value_cr") or 0) - 788.71) < 0.02]
            report["fy26_total"] = [{"source": f["source"], "item": f["item"], "value_cr": f["value_cr"]}
                                    for f in fy26[:4]]
            if not fy26:
                failures.append("FY26 788.71 cr missing")

            cat = await call(session, "catalog", {}, timeout=180)
            report["catalog"] = {"databases": len(cat["databases"]),
                                 "tables": sum(db["table_count"] for db in cat["databases"]),
                                 "curated": cat["descriptions"]["curated_tables"],
                                 "cache_missing": cat["cache_missing"]}
            if len(cat["databases"]) != 7:
                failures.append("catalog databases != 7")

            sq = await call(session, "sql", {"query": "select 1 as x", "db": "truth"})
            report["sql"] = sq["rows"]
            bad = await call(session, "sql", {"query": "delete from ar_facts", "db": "ar_facts"})
            report["sql_rejected_write"] = not bad.get("ok", True)

            latency = {}
            for name, args in (
                ("resolve", {"query": "PPL"}),
                ("price", {"symbol": "PPL", "start": "2026-03-30"}),
                ("facts", {"symbol": "PPL", "kind": "segments", "period": "FY25"}),
            ):
                samples, med, lo, hi = await timed(session, name, args)
                latency[name] = {"samples_ms": samples, "median_ms": med}
                if med >= 200:
                    failures.append(f"{name} median {med} ms >= 200 ms")
            report["latency"] = latency

            if (PLUGIN_ROOT / "server" / "search_docs.py").exists():
                args = {"query": "PPL segment revenue", "top_k": 10}
                await call(session, "search_docs", args, timeout=180)  # warm indexes
                samples, med, lo, hi = await timed(session, "search_docs", args)
                hits = await call(session, "search_docs", args, timeout=180)
                ar_hits = [h for h in hits["results"] if "annual" in str(h.get("doc_type", "")).lower()]
                report["search_docs"] = {"count": len(hits["results"]), "ar_hits": len(ar_hits),
                                         "median_ms": med, "samples_ms": samples}
                if med >= 2000:
                    failures.append(f"search_docs median {med} ms >= 2000 ms")
                if not ar_hits:
                    failures.append("search_docs returned no AR passages")

                rbi = await call(session, "search_docs",
                                 {"query": "repo rate decision", "doc_types": ["rbi"], "top_k": 5},
                                 timeout=180)
                report["rbi"] = {"count": len(rbi["results"]),
                                 "doc_types": sorted({r.get("doc_type") for r in rbi["results"]})}
                if not rbi["results"]:
                    failures.append("RBI query returned no results")

                semantic = await call(session, "search_docs",
                                      {"query": "management commentary on demand slowdown in pipes",
                                       "top_k": 5}, timeout=180)
                sources = [r.get("source") for r in semantic["results"]]
                report["semantic"] = {"count": len(semantic["results"]), "sources": sources,
                                      "symbols": [r.get("symbol") for r in semantic["results"]]}
                if not any(s in ("vector", "both") for s in sources):
                    failures.append("semantic query returned no vector/both hit")
                await call(session, "search_docs",
                           {"query": "management commentary on demand slowdown in pipes", "top_k": 5},
                           timeout=180)
                samples2, med2, _, _ = await timed(
                    session, "search_docs",
                    {"query": "management commentary on demand slowdown in pipes", "top_k": 5})
                report["semantic_latency_ms"] = {"median_ms": med2, "samples_ms": samples2}
                if med2 >= 2000:
                    failures.append(f"semantic search median {med2} ms >= 2000 ms")
            else:
                stub = await call(session, "search_docs", {"query": "PPL segment revenue"})
                report["search_docs"] = {"pending": True, "error": stub.get("error", {}).get("code")}

    report["failures"] = failures
    print(json.dumps(report, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
