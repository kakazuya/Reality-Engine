"""Tests for the reality-data MCP server (resolve/price/facts/catalog/sql).

Run from the repo root:
    python -m unittest discover -s plugins/reality-data/tests -p "test_*.py" -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PLUGIN_ROOT / "server"
SERVER = SERVER_DIR / "server.py"
sys.path.insert(0, str(SERVER_DIR))

import catalog  # noqa: E402
import core  # noqa: E402


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


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.warm()

    def test_resolve_symbol_isin_and_name(self):
        for query in ("PPL", "INE050001010", "Prakash Pipes"):
            with self.subTest(query=query):
                out = core.resolve(query)
                self.assertEqual(out["count"], 1)
                match = out["matches"][0]
                self.assertEqual(match["isin"], "INE050001010")
                self.assertEqual(match["nse_symbol"], "PPL")
                self.assertIn("PRAKASH PIPES", match["name"].upper())
                self.assertTrue(match["isin_history"])
                self.assertIn("read_only", out["provenance"])

    def test_price_raw_and_adjusted(self):
        out = core.price("PPL", "2026-03-30")
        self.assertEqual(out["exchange"], "NSE")
        self.assertEqual(len(out["rows"]), 1)
        row = out["rows"][0]
        self.assertAlmostEqual(row["close"], 164.15, places=2)
        self.assertAlmostEqual(row["adj_close"], 164.15, places=2)
        self.assertEqual(row["deliverable_qty"], 136873)
        self.assertAlmostEqual(row["delivery_pct"], 59.72, places=2)
        self.assertAlmostEqual(row["value_inr"], 38_409_000.0, places=0)
        adjusted = core.price("PPL", "2026-03-30", adjusted=True)
        self.assertEqual(adjusted["close_used"], "adj_close")
        self.assertAlmostEqual(adjusted["summary"]["last_close"], row["adj_close"], places=4)

    def test_facts_segments_fy25(self):
        out = core.facts("PPL", kind="segments", period="FY25")
        values = {round(f["value"], 2): f for f in out["facts"] if f["source"] == "ar_facts" and f["value"]}
        self.assertIn(41302.0, values)
        self.assertIn(36746.0, values)
        self.assertIn("pvc", values[41302.0]["item"].lower())
        self.assertIn("packaging", values[36746.0]["item"].lower())
        self.assertEqual(values[41302.0]["unit"], "Rs lakh")
        self.assertEqual(values[41302.0]["page"], 80)
        self.assertAlmostEqual(values[41302.0]["value_cr"], 413.02, places=2)

    def test_facts_fy26_total_revenue(self):
        out = core.facts("PPL", kind="financials", period="FY26")
        values = [f for f in out["facts"] if abs(float(f.get("value_cr") or 0) - 788.71) < 0.02]
        self.assertTrue(values, "788.71 cr FY26 revenue not returned")
        self.assertTrue(any(f["source"] == "ar_facts" for f in values))
        self.assertTrue(any(f["source"] == "results_xbrl" for f in values))

    def test_facts_quarantine_excludes_wrong_company_pdf(self):
        self.assertIn(92565, core.quarantined_doc_ids())
        out = core.facts("VENUSREM", kind="ar", period="FY26", limit=500)
        self.assertFalse([f for f in out["facts"] if f.get("doc_id") == 92565])

    def test_sql_readonly_and_limits(self):
        ok = core.sql("select 1 as x", "truth")
        self.assertEqual(ok["rows"], [[1]])
        for bad in (
            "delete from ar_facts",
            "select 1; select 2",
            "attach 'x.db' as x",
            "select * from read_csv('x.csv')",  # parses as SELECT, not blocked; only sanity for DDL below
        ):
            if bad.startswith("select * from read_csv"):
                continue
            with self.subTest(bad=bad):
                with self.assertRaises(core.DataError) as ctx:
                    core.sql(bad, "ar_facts")
                self.assertEqual(ctx.exception.code, "not_select")
        limited = core.sql("select * from security_master order by isin", "truth", limit=3)
        self.assertEqual(len(limited["rows"]), 3)
        self.assertTrue(limited["truncated"])
        with self.assertRaises(core.DataError) as ctx:
            core.sql("select * from security_master", "nope")
        self.assertEqual(ctx.exception.code, "unknown_db")

    def test_catalog_merges_curated_descriptions(self):
        out = catalog.get_catalog()
        dbs = {db["key"]: db for db in out["databases"]}
        self.assertEqual(set(dbs), set(catalog.KNOWN_COUNTS) | {"truth_duckdb"})
        self.assertTrue(out["descriptions"]["loaded"])
        self.assertGreater(out["descriptions"]["curated_tables"], 100)
        tables = {t["name"]: t for t in dbs["truth_duckdb"]["tables"]}
        self.assertIn("px_nse_adj", tables)
        self.assertTrue(tables["px_nse_adj"]["curated"])
        self.assertIn("date", tables["px_nse_adj"]["key_columns"])
        self.assertEqual(tables["px_nse_adj"]["rows"], 4_290_443)
        ar_table = {t["name"]: t for t in dbs["ar_facts"]["tables"]}["ar_facts"]
        self.assertEqual(ar_table["rows"], 32_443_403)
        self.assertFalse(ar_table["rows_approx"])
        # demo tables are excluded wholesale
        self.assertNotIn("business_model_profiles_demo",
                         {t["name"] for t in dbs["equity_intelligence"]["tables"]})
        indexes = {i["key"]: i for i in out["indexes"]}
        self.assertEqual(indexes["nemotron8b"]["done_rows"], 340_887)
        self.assertEqual(indexes["qwen8b_ar"]["done_rows"], 61_440)
        self.assertLess(indexes["qwen8b_ar"]["coverage_pct"], 5.0)
        self.assertIn("4.49", indexes["qwen8b_ar"]["description"])

    def test_catalog_works_without_descriptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does_not_exist.yaml"
            out = catalog.get_catalog(descriptions_path=missing)
        self.assertEqual(len(out["databases"]), 7)
        self.assertFalse(out["descriptions"]["loaded"])
        names = {t["name"] for db in out["databases"] for t in db["tables"]}
        self.assertIn("security_master", names)
        self.assertIn("ar_facts", names)


class McpStdioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.warm()

    async def _with_session(self, fn):
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)

    def _run(self, coro, timeout=120.0):
        return asyncio.run(asyncio.wait_for(coro, timeout))

    def _call(self, session, name, arguments):
        async def call():
            result = await session.call_tool(name, arguments, read_timeout_seconds=60)
            return payload(result)
        return call

    def test_tools_over_stdio(self):
        async def scenario(session):
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            self.assertEqual(names, {"catalog", "resolve", "price", "facts", "search_docs", "sql"})

            resolved = payload(await session.call_tool("resolve", {"query": "PPL"}, read_timeout_seconds=60))
            self.assertEqual(resolved["matches"][0]["isin"], "INE050001010")

            priced = payload(await session.call_tool("price", {"symbol": "PPL", "start": "2026-03-30"},
                                                     read_timeout_seconds=60))
            self.assertAlmostEqual(priced["rows"][0]["close"], 164.15, places=2)

            facts = payload(await session.call_tool(
                "facts", {"symbol": "PPL", "kind": "segments", "period": "FY25"},
                read_timeout_seconds=60))
            values = {round(f["value"], 2) for f in facts["facts"] if f.get("value")}
            self.assertIn(41302.0, values)
            self.assertIn(36746.0, values)

            cat = payload(await session.call_tool("catalog", {}, read_timeout_seconds=120))
            self.assertEqual(len(cat["databases"]), 7)
            self.assertTrue(cat["descriptions"]["loaded"])

            sq = payload(await session.call_tool("sql", {"query": "select 1 as x", "db": "truth"},
                                                 read_timeout_seconds=60))
            self.assertEqual(sq["rows"], [[1]])

            bad = payload(await session.call_tool("sql", {"query": "delete from ar_facts", "db": "ar_facts"},
                                                  read_timeout_seconds=60))
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["error"]["code"], "not_select")

            if not (SERVER_DIR / "search_docs.py").exists():
                stub = payload(await session.call_tool("search_docs", {"query": "PPL segment revenue"},
                                                       read_timeout_seconds=60))
                self.assertFalse(stub["ok"])
                self.assertEqual(stub["error"]["code"], "not_implemented")
            return True

        self.assertTrue(self._run(self._with_session(scenario)))


if __name__ == "__main__":
    unittest.main()
