"""Fixture tests for plugins/reality-data/server/lookups_pilot3.py and the pilot3_* MCP tools (T-049 F).

Run from the repo root:
    python -m unittest plugins/reality-data/tests/test_lookups_pilot3.py

A tiny pilot3.db is built under ``.tmp/`` from the real DDL (``reality_engine.pilot3.schema``, ``kpi.SCHEMA``,
``transcripts.SCHEMA``) and ``REALITY_PILOT3_DB`` points at it: no production database, network or model.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
SERVER = SERVER_DIR / "server.py"
TMP = ROOT / ".tmp"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_DIR))

import core  # noqa: E402
import lookups_pilot3 as p3  # noqa: E402
from reality_engine.pilot3 import kpi as kpi_mod, schema, transcripts  # noqa: E402

DB = TMP / "pilot3_fixture.db"
TOOLS = {"pilot3_kpi", "pilot3_fin", "pilot3_ratio", "pilot3_holding", "pilot3_statements", "pilot3_docs",
         "pilot3_search", "pilot3_sql"}


def build_fixture() -> None:
    TMP.mkdir(exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB) + suffix).unlink(missing_ok=True)
    c = sqlite3.connect(DB)
    schema.create(c, list(schema.TABLES))
    c.executescript(kpi_mod.SCHEMA + transcripts.SCHEMA)
    c.execute(schema.FTS)
    c.execute("INSERT INTO company VALUES ('KEC','INE389H01022',NULL,NULL,'t','532714','KEC International Limited')")
    c.executemany("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("pdfs/KEC/deck1.pdf", "KEC", "INE389H01022", "deck", "deck", "Investor Presentation", "2026-02-10",
         "2026-02-10T17:00:00", 2, "sha", "pages.db", "D:/raw/deck1.pdf"),
        ("pdfs/KEC/deck2.pdf", "KEC", "INE389H01022", "deck", "deck", "Investor Presentation", "2026-08-10",
         "2026-08-10T17:00:00", 1, "sha2", "pages.db", "D:/raw/deck2.pdf"),
        ("KEC:old/call.pdf", "KEC", "INE389H01022", "transcript", "transcript", "Conference Call Q3 FY26",
         "2026-02-12", "2026-02-14T10:00:00", 1, None, "sandbox", "k")])
    c.execute("INSERT INTO doc_alias VALUES ('KEC','old/deck.pdf','pdfs/KEC/deck1.pdf')")
    pages = [("pdfs/KEC/deck1.pdf", 1, "Order book stood at Rs 40,000 crore as on 31 Dec 2025", "2026-02-10T17:00:00"),
             ("pdfs/KEC/deck1.pdf", 2, "Transmission and distribution revenue grew strongly", "2026-02-10T17:00:00"),
             ("pdfs/KEC/deck2.pdf", 1, "Order book reached Rs 45,000 crore in June 2026", "2026-08-10T17:00:00"),
             # same words as page 1 of deck1 but printing the quarter: the period boost must lift it
             ("pdfs/KEC/deck2.pdf", 2, "Q3 FY26 update. The order book is discussed together with revenue, margins, "
                                       "capex, demand, capacity and working capital in the presentation.",
              "2026-08-10T17:00:00")]
    for i, (dk, pg, text, k) in enumerate(pages):
        c.execute("INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)", (dk, "KEC", pg, text, "script_text", len(text), k, None))
    c.execute("INSERT INTO doc_page_fts(rowid, text) SELECT rowid, text FROM doc_page")
    ins = ("INSERT INTO kpi_series(symbol,metric,dimension,value,unit,scale,period_type,fiscal_period,as_of_date,basis,"
           "doc_key,page,quote,known_at,known_at_source,is_reported,extractor_rule) "
           "VALUES ('KEC',?,?,?,?,1,'Q',?,?, 'consolidated',?,1,?,?,'docs.known_at',1,'t')")
    c.execute(ins, ("order_book", "total", 40000.0, "inr_cr", "Q3FY26", "2025-12-31", "old/deck.pdf",
                    "Order book Rs 40,000 crore", "2026-02-10T17:00:00"))
    c.execute(ins, ("order_book", "total", 45000.0, "inr_cr", "Q1FY27", "2026-06-30", "pdfs/KEC/deck2.pdf",
                    "Order book Rs 45,000 crore", "2026-08-10T17:00:00"))
    c.execute(ins, ("order_book", "total", 1.0, "inr_cr", "Q2FY27", "2026-09-30", "pdfs/KEC/deck2.pdf", "undated", None))
    # same KPI, two sources and confidence tiers: the deck row (better evidence) must come first
    c.execute(ins, ("order_intake", "total", 100.0, "inr_cr", "Q1FY27", "2026-06-30",
                    "old/call.pdf", "call remark", "2026-08-11T10:00:00"))
    c.execute(ins, ("order_intake", "total", 200.0, "inr_cr", "Q1FY27", "2026-06-30", "pdfs/KEC/deck2.pdf",
                    "deck table", "2026-08-10T17:00:00"))
    c.execute("UPDATE kpi_series SET conf_rank=1 WHERE metric='order_intake' AND value=100.0")
    c.execute("UPDATE kpi_series SET conf_rank=4 WHERE metric='order_intake' AND value=200.0")
    c.executemany("INSERT INTO fin_annual_line VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("KEC", "INE389H01022", "FY25", "2025-03-31", "consolidated", "PL", "pat", "PAT", 4.0e9, "inr", 1.0, "f.xml",
         None, "ProfitLoss = 4e9", "results_xbrl.db", "facts", "f.xml#1", "2025-05-20T10:00:00", "x", 1, 0,
         "xbrl_reported", "FY")])
    c.execute("INSERT INTO fin_quarter_xbrl VALUES ('KEC','INE389H01022','2025-10-01','2025-12-31','Q3FY26',"
              "'consolidated','a','PL','pat','Tag',1.5e9,'inr',1.0,'q.xml','results_xbrl.db','quarterly','q.xml',"
              "'2026-02-05T10:00:00','x',1)")
    c.execute("INSERT INTO formula VALUES ('F_ROE','roe','100*pat/net_worth','[]','pct',1,'n')")
    c.execute("INSERT INTO ratio_panel VALUES ('KEC','I','FY25','FY','2024-04-01','2025-03-31','consolidated','roe',"
              "12.5,'pct',1,'F_ROE','[\"a\"]','2025-05-20T10:00:00','x',1)")
    c.execute("INSERT INTO valuation_daily VALUES ('KEC','I','2026-03-30','consolidated',500,1e8,5e10,25,2.5e9,1e10,"
              "1e9,3e9,20,5,12,0.5,'2026-03-30','x','{}')")
    c.executemany("INSERT INTO shp_category VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("KEC", "I", "2025-12-31", "promoter", "Promoter", 1.0e8, 51.5, 10, "pct", "xbrl", "shp.xml", "db", "t", "1",
         None, "2026-01-20T10:00:00", "x", 1),
        ("KEC", "I", "2026-03-31", "promoter", "Promoter", 1.0e8, 52.0, 10, "pct", "xbrl", "shp2.xml", "db", "t", "2",
         None, "2026-04-20T10:00:00", "x", 1)])
    c.execute("INSERT INTO share_capital VALUES ('KEC','I','2025-12-31','consolidated',NULL,NULL,2.6e8,5e8,2,'inr',1,"
              "'2026-01-30T10:00:00','x','db','t','1',NULL,NULL)")
    c.execute("INSERT INTO transcript_statement(symbol,doc_key,call_date,call_period,page,seq,speaker,role,section,"
              "topics,period_discussed,period_source,numbers_json,statement,quote,is_fragment,known_at,known_at_source,"
              "extractor_rule) VALUES ('KEC','old/call.pdf','2026-02-12','Q3FY26',2,1,'A B','ceo','prepared',"
              "'margin,guidance','Q3FY26','t','[]','We expect margin to improve','We expect margin to improve by 50 bps.',"
              "0,'2026-02-14T10:00:00','x','t')")
    # a newer call with the same topic but not the asked words: relevance and period outrank recency
    c.execute("INSERT INTO transcript_statement(symbol,doc_key,call_date,call_period,page,seq,speaker,role,section,"
              "topics,period_discussed,period_source,numbers_json,statement,quote,is_fragment,known_at,known_at_source,"
              "extractor_rule) VALUES ('KEC','KEC:old/call.pdf','2026-08-01','Q1FY27',3,2,'C D','md','prepared',"
              "'margin','Q1FY27','t','[]','Margins were steady this quarter','Margins were steady this quarter.',"
              "0,'2026-08-02T10:00:00','x','t')")
    c.commit()
    c.close()


def payload(result):
    data = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if data is None:
        for block in result.content:
            if getattr(block, "type", None) == "text":
                return json.loads(block.text)
    return data


class Pilot3ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_fixture()
        os.environ["REALITY_PILOT3_DB"] = str(DB)
        p3.close()

    @classmethod
    def tearDownClass(cls):
        p3.close()
        os.environ.pop("REALITY_PILOT3_DB", None)

    def assertProvenance(self, rows):
        self.assertTrue(rows)
        for row in rows:
            prov = row["provenance"]
            self.assertTrue(prov["table"] and prov["source"], row)
            self.assertIn("known_at", prov)

    def test_symbol_resolution_and_rejection(self):
        self.assertEqual(p3.resolve_symbol("kec"), "KEC")
        self.assertEqual(p3.resolve_symbol("532714"), "KEC")
        self.assertEqual(p3.resolve_symbol("INE389H01022"), "KEC")
        with self.assertRaises(core.DataError) as ctx:
            p3.resolve_symbol("TCS")
        self.assertEqual(ctx.exception.code, "not_pilot3")

    def test_period_normaliser(self):
        for text, want in (("Q3 FY2026", ("Q", "Q3FY26")), ("FY2025-26", ("FY", "FY26")), ("2025-26", ("FY", "FY26")),
                           ("H1FY26", ("H1", "H1FY26")), ("fy26", ("FY", "FY26")), ("2025-12-31", ("Q", "Q3FY26")),
                           ("2026-05-01", ("Q", "Q1FY27")), (None, (None, None))):
            self.assertEqual(p3.norm_period(text), want, text)

    def test_kpi_provenance_alias_and_point_in_time(self):
        out = p3.kpi("KEC", "order book", "Q3FY26")
        self.assertEqual(out["rows"][0]["value"], 40000.0)
        self.assertProvenance(out["rows"])
        self.assertEqual(out["rows"][0]["provenance"]["source"], "pdfs/KEC/deck1.pdf p1")  # alias -> pilot3 doc key
        early = p3.kpi("KEC", "order_book", as_of="2026-03-01")
        self.assertEqual([r["value"] for r in early["rows"]], [40000.0])  # later deck and undated row hidden
        late = p3.kpi("KEC", "order_book", as_of="2026-12-31")
        self.assertEqual({r["value"] for r in late["rows"]}, {40000.0, 45000.0})  # undated row never shown
        miss = p3.kpi("KEC", "order_book", "Q2FY26")
        self.assertFalse(miss["found"])
        self.assertIn("Q1FY27 / total (1 rows)", miss["held_period_dimension"])
        self.assertIn("order_book", p3.kpi("KEC", "nonsense")["available"])

    def test_fin_annual_and_quarterly(self):
        annual = p3.fin("KEC", "pat", "FY25", basis="consolidated")
        self.assertEqual(annual["rows"][0]["value_inr"], 4.0e9)
        self.assertProvenance(annual["rows"])
        quarter = p3.fin("KEC", "pat", "Q3FY26")
        self.assertEqual(quarter["rows"][0]["provenance"]["table"], "fin_quarter_xbrl")
        self.assertFalse(p3.fin("KEC", "pat", "FY25", as_of="2025-05-01")["found"])
        both = p3.fin("KEC", "pat")
        self.assertEqual({r["provenance"]["table"] for r in both["rows"]}, {"fin_annual_line", "fin_quarter_xbrl"})

    def test_ratio_panel_and_valuation(self):
        roe = p3.ratio("KEC", "ROE", "FY25")
        self.assertEqual(roe["rows"][0]["formula"], "100*pat/net_worth")
        self.assertProvenance(roe["rows"])
        pe = p3.ratio("KEC", "pe", as_of="2026-04-30")
        self.assertEqual(pe["rows"][0]["value"], 20)
        self.assertProvenance(pe["rows"])
        self.assertFalse(p3.ratio("KEC", "pe", as_of="2026-03-01")["found"])

    def test_holding_is_point_in_time(self):
        a = p3.holding("KEC", "2026-02-01")
        self.assertEqual((a["quarter_end"], a["rows"][0]["pct"]), ("2025-12-31", 51.5))
        self.assertEqual(a["share_capital"]["shares_outstanding"], 2.6e8)
        self.assertProvenance(a["rows"])
        b = p3.holding("KEC", "2026-06-01")
        self.assertEqual((b["quarter_end"], b["rows"][0]["pct"]), ("2026-03-31", 52.0))
        self.assertFalse(p3.holding("KEC", "2025-06-01")["found"])
        with self.assertRaises(core.DataError):
            p3.holding("KEC", "")

    def test_statements_exact_quote(self):
        out = p3.statements("KEC", topic="margin", terms="improve 50")
        self.assertEqual(out["rows"][0]["quote"], "We expect margin to improve by 50 bps.")
        self.assertTrue(out["topic_matched"])
        self.assertProvenance(out["rows"])
        self.assertFalse(p3.statements("KEC", topic="margin", as_of="2026-02-01")["found"])
        # a tag nothing carries is a ranking preference, not a filter: the rows come with topic_matched=false
        untagged = p3.statements("KEC", topic="capex")
        self.assertTrue(untagged["found"])
        self.assertFalse(untagged["topic_matched"])

    def test_docs_listing(self):
        out = p3.docs("KEC", "decks")
        self.assertEqual([r["filing_date"] for r in out["rows"]], ["2026-08-10", "2026-02-10"])
        self.assertEqual(out["counts_by_type"], {"deck": 2})
        self.assertEqual(len(p3.docs("KEC", as_of="2026-03-01")["rows"]), 2)
        self.assertProvenance(out["rows"])

    def test_kpi_orders_by_confidence_then_source_type(self):
        """The extractor's confidence decides first, then a deck table beats a call remark."""
        out = p3.kpi("KEC", "order_intake", "Q1FY27")
        self.assertEqual([r["value"] for r in out["rows"]], [200.0, 100.0])
        self.assertEqual(out["rows"][0]["provenance"]["doc_type"], "deck")

    def test_statements_latest_keeps_the_newest_call(self):
        out = p3.statements("KEC", latest=True)
        self.assertEqual({r["call_date"] for r in out["rows"]}, {"2026-08-01"})
        early = p3.statements("KEC", latest=True, as_of="2026-07-01")   # the newer call is not held by then
        self.assertEqual({r["call_date"] for r in early["rows"]}, {"2026-02-12"})

    def test_statements_rank_by_period_and_question_words(self):
        """A newer call does not bury the statement that answers: the period and the question's words rank."""
        latest = p3.statements("KEC", topic="margin")
        self.assertEqual(latest["rows"][0]["call_date"], "2026-08-01")          # no signal: newest call first
        asked = p3.statements("KEC", topic="margin", period="Q3FY26", rank_terms="50 bps improve")
        self.assertEqual(asked["rows"][0]["quote"], "We expect margin to improve by 50 bps.")
        words = p3.statements("KEC", topic="margin", rank_terms="50 bps improve")
        self.assertEqual(words["rows"][0]["quote"], "We expect margin to improve by 50 bps.")

    def test_search_period_boost_lifts_the_page_that_prints_the_quarter(self):
        plain = p3.search("KEC", "order book")
        lifted = p3.search("KEC", "order book", period="Q3FY26")
        self.assertEqual(lifted["rows"][0]["provenance"]["source"], "pdfs/KEC/deck2.pdf p2")
        self.assertEqual(plain["rows"][0]["provenance"]["source"], "pdfs/KEC/deck2.pdf p1")   # bm25 alone
        self.assertEqual(lifted["period"], "Q3FY26")

    def test_search_fts_and_as_of(self):
        out = p3.search("KEC", "order book crore")
        self.assertGreaterEqual(len(out["rows"]), 2)
        crore = [r for r in out["rows"] if "crore" in (r["snippet"] or "")]
        self.assertEqual({r["provenance"]["source"] for r in crore[:2]},
                         {"pdfs/KEC/deck1.pdf p1", "pdfs/KEC/deck2.pdf p1"})   # all words first
        self.assertIn("[Order]", out["rows"][0]["snippet"])
        self.assertProvenance(out["rows"])
        early = p3.search("KEC", "order book", as_of="2026-03-01")
        self.assertEqual([r["page"] for r in early["rows"]], [1])
        self.assertEqual(early["rows"][0]["provenance"]["source"], "pdfs/KEC/deck1.pdf p1")
        fallback = p3.search("KEC", "order nonexistentword")  # AND finds nothing, OR does
        self.assertEqual(fallback["match_mode"], "or")

    def test_sql_is_read_only_and_bounded(self):
        out = p3.sql("select doc_type, count(*) n from doc group by 1", limit=1)
        self.assertEqual(out["row_count"], 1)
        self.assertTrue(out["truncated"])
        for bad in ("delete from doc", "select 1; select 2", "pragma table_info(doc)", "insert into doc select * from doc",
                    "attach database 'x' as y"):
            with self.assertRaises(core.DataError, msg=bad):
                p3.sql(bad)
        with self.assertRaises(core.DataError) as ctx:
            p3.sql("select * from nope")
        self.assertIn("Tables:", ctx.exception.message)
        self.assertLessEqual(p3.sql("select * from doc_page", limit=10_000)["row_count"], 500)

    def test_missing_db_is_a_clean_error(self):
        os.environ["REALITY_PILOT3_DB"] = str(TMP / "nope.db")
        try:
            with self.assertRaises(core.DataError) as ctx:
                p3.connect()
            self.assertEqual(ctx.exception.code, "pilot3_db_missing")
        finally:
            os.environ["REALITY_PILOT3_DB"] = str(DB)
            p3.close()


class Pilot3McpTests(unittest.TestCase):
    """The real server over stdio: tools are listed, routed in the instructions, and answer with provenance."""

    @classmethod
    def setUpClass(cls):
        build_fixture()

    def test_server_starts_and_serves_pilot3_tools(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def scenario():
            env = {**os.environ, "REALITY_PILOT3_DB": str(DB)}
            params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    self.assertIn("PILOT3 FIRST", init.instructions)
                    for sym in ("KEC", "BAJFINANCE", "HINDALCO"):
                        self.assertIn(sym, init.instructions)
                    names = {t.name for t in (await session.list_tools()).tools}
                    self.assertTrue(TOOLS <= names)
                    calls = {
                        "pilot3_kpi": {"symbol": "KEC", "kpi": "order_book", "period": "Q3FY26"},
                        "pilot3_fin": {"symbol": "KEC", "measure": "pat", "period": "FY25"},
                        "pilot3_ratio": {"symbol": "KEC", "ratio": "roe", "period": "FY25"},
                        "pilot3_holding": {"symbol": "KEC", "as_of": "2026-06-01"},
                        "pilot3_statements": {"symbol": "KEC", "topic": "margin"},
                        "pilot3_docs": {"symbol": "KEC", "doc_type": "deck"},
                        "pilot3_search": {"symbol": "KEC", "query": "order book"},
                    }
                    for name, args in calls.items():
                        out = payload(await session.call_tool(name, args, read_timeout_seconds=60))
                        self.assertTrue(out["found"], name)
                        self.assertTrue(all(r["provenance"]["source"] for r in out["rows"]), name)
                    sql = payload(await session.call_tool("pilot3_sql", {"query": "select count(*) from doc"},
                                                          read_timeout_seconds=60))
                    self.assertEqual(sql["rows"], [[3]])
                    bad = payload(await session.call_tool("pilot3_sql", {"query": "drop table doc"},
                                                          read_timeout_seconds=60))
                    self.assertFalse(bad["ok"])
                    other = payload(await session.call_tool("pilot3_kpi", {"symbol": "TCS", "kpi": "x"},
                                                            read_timeout_seconds=60))
                    self.assertEqual(other["error"]["code"], "not_pilot3")

        asyncio.run(asyncio.wait_for(scenario(), 120))


if __name__ == "__main__":
    unittest.main()
