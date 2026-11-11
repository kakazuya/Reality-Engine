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
from typing import Any

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
TOOLS = {"pilot3_fact", "pilot3_kpi", "pilot3_fin", "pilot3_ratio", "pilot3_holding", "pilot3_statements",
         "pilot3_docs", "pilot3_search", "pilot3_guidance", "pilot3_sql", "pilot3_cells"}


def build_fixture() -> None:
    TMP.mkdir(exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB) + suffix).unlink(missing_ok=True)
    c = sqlite3.connect(DB)
    schema.create(c, list(schema.TABLES))
    c.executescript(kpi_mod.SCHEMA + transcripts.SCHEMA)
    c.execute(schema.FTS)
    # T-113 row verdicts: a figure the checker quarantined is still held (T-165)
    c.execute("CREATE TABLE row_check (tbl TEXT, row_id INTEGER, symbol TEXT, metric TEXT, canon TEXT, sector TEXT, "
              "doc_type TEXT, rule TEXT, status TEXT, corroborated INTEGER, checker TEXT)")
    c.execute("CREATE TABLE row_check_fail (tbl TEXT, row_id INTEGER, check_name TEXT, hard INTEGER, why TEXT)")
    c.execute("INSERT INTO company VALUES ('KEC','INE389H01022',NULL,NULL,'t','532714','KEC International Limited')")
    c.executemany("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("pdfs/KEC/deck1.pdf", "KEC", "INE389H01022", "deck", "deck", "Investor Presentation", "2026-02-10",
         "2026-02-10T17:00:00", 2, "sha", "pages.db", "D:/raw/deck1.pdf"),
        ("pdfs/KEC/deck2.pdf", "KEC", "INE389H01022", "deck", "deck", "Investor Presentation", "2026-08-10",
         "2026-08-10T17:00:00", 1, "sha2", "pages.db", "D:/raw/deck2.pdf"),
        ("KEC:old/call.pdf", "KEC", "INE389H01022", "transcript", "transcript", "Conference Call Q3 FY26",
         "2026-02-12", "2026-02-14T10:00:00", 1, None, "sandbox", "k"),
        # no filing record at all: pilot3_search must not crash on it (it has no known_at to sort on)
        ("KEC:undated/call.pdf", "KEC", "INE389H01022", "transcript", "transcript", "Undated call", None,
         None, 1, None, "sandbox", "k2")])
    c.execute("INSERT INTO doc_alias VALUES ('KEC','old/deck.pdf','pdfs/KEC/deck1.pdf')")
    pages = [("pdfs/KEC/deck1.pdf", 1, "Order book stood at Rs 40,000 crore as on 31 Dec 2025", "2026-02-10T17:00:00"),
             ("pdfs/KEC/deck1.pdf", 2, "Transmission and distribution revenue grew strongly", "2026-02-10T17:00:00"),
             ("pdfs/KEC/deck2.pdf", 1, "Order book reached Rs 45,000 crore in June 2026", "2026-08-10T17:00:00"),
             # same words as page 1 of deck1 but printing the quarter: the period boost must lift it
             ("pdfs/KEC/deck2.pdf", 2, "Q3 FY26 update. The order book is discussed together with revenue, margins, "
                                       "capex, demand, capacity and working capital in the presentation.",
              "2026-08-10T17:00:00"),
             # a call page with a topic no statement tag carries: pilot3_statements falls back to it
             ("KEC:old/call.pdf", 1, "Power transmission capacity is being expanded across the country.",
              "2026-02-14T10:00:00"),
             # the undated call page: no filing record, no known_at
             ("KEC:undated/call.pdf", 1, "A special undated page about tariffs.", None)]
    for i, (dk, pg, text, k) in enumerate(pages):
        c.execute("INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)", (dk, "KEC", pg, text, "script_text", len(text), k, None))
    c.execute("INSERT INTO doc_page_fts(rowid, text) SELECT rowid, text FROM doc_page")
    # T-189: the page reader's cells; verified and unverified are served, quarantined never is
    c.execute("CREATE TABLE page_cell (doc_key TEXT, page INTEGER, symbol TEXT, known_at TEXT, reader TEXT, "
              "table_title TEXT, row_label TEXT, col_header TEXT, value_text TEXT, unit_text TEXT, status TEXT, "
              "conflict TEXT, x0 REAL, y0 REAL, x1 REAL, y1 REAL)")
    c.executemany(
        "INSERT INTO page_cell VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL)", [
            ("pdfs/KEC/deck1.pdf", 1, "KEC", "2026-02-10T17:00:00", "dots", "Order Book", "Order book", "Q3FY26",
             "40,000", "Rs crore", "verified"),
            ("pdfs/KEC/deck1.pdf", 2, "KEC", "2026-02-10T17:00:00", "dots", "", "Order book", "Q3FY26",
             "41,500", "Rs crore", "unverified"),
            ("pdfs/KEC/deck2.pdf", 1, "KEC", "2026-08-10T17:00:00", "dots", "Order Book", "Order book", "Q1FY27",
             "45,000", "Rs crore", "verified"),
            ("pdfs/KEC/deck2.pdf", 1, "KEC", "2026-08-10T17:00:00", "dots", "Order Book", "Order book", "Q2FY27",
             "99,999", "Rs crore", "quarantined"),
            ("pdfs/KEC/deck2.pdf", 2, "KEC", "2026-08-10T17:00:00", "dots", "", "Gross written premium", "Q2FY27",
             "2,100", "Rs crore", "verified")])
    c.executemany(
        "INSERT INTO guidance(id,symbol,isin,metric,target_period,low,high,unit,direction,said_on,doc_key,page,quote,"
        "speaker,known_at,known_at_source,revision_of,extractor_rule) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'t')", [
            (1, "KEC", "INE389H01022", "revenue_growth", "FY27", 12.0, 15.0, "pct", "up", "2026-02-10",
             "pdfs/KEC/deck1.pdf", 1, "We expect revenue growth of 12% to 15% for FY27.", None,
             "2026-02-10T17:00:00", "doc.known_at", None),
            (2, "KEC", "INE389H01022", "revenue_growth", "FY27", 12.0, 15.0, "pct", "up", "2026-08-10",
             "pdfs/KEC/deck2.pdf", 1, "We still expect revenue growth of 12% to 15% for FY27.", "Vimal Kejriwal",
             "2026-08-10T17:00:00", "doc.known_at", 1),
            (3, "KEC", "INE389H01022", "ebitda_margin", "FY26", 7.0, 7.5, "pct", "down", "2026-02-12",
             "KEC:old/call.pdf", 1, "We have cut our margin guidance for the year to 7% to 7.5%.", "Vimal Kejriwal",
             "2026-02-14T10:00:00", "doc.known_at", None)])
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
    # T-165: the KPI words investors use (NIM / net interest margin, credit cost, cost of funds) resolve to these
    c.execute(ins, ("nim_pct", "total", 8.2, "pct", "Q1FY27", "2026-06-30", "pdfs/KEC/deck2.pdf", "NIM 8.2%",
                    "2026-08-10T17:00:00"))
    c.execute(ins, ("credit_cost_bps", "total", 140.0, "bps", "Q1FY27", "2026-06-30", "pdfs/KEC/deck2.pdf",
                    "Credit cost 140 bps", "2026-08-10T17:00:00"))
    c.execute(ins, ("cost_of_funds_pct", "total", 6.7, "pct", "Q1FY27", "2026-06-30", "pdfs/KEC/deck2.pdf",
                    "Cost of funds 6.7%", "2026-08-10T17:00:00"))
    c.execute(ins, ("gnpa_pct", "total", 4.2, "pct", "Q1FY27", "2026-06-30", "pdfs/KEC/deck2.pdf", "GNPA 4.2",
                    "2026-08-10T17:00:00"))
    gid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO row_check VALUES ('kpi_series',?,'KEC','gnpa_pct','gnpa','nbfc','deck','table_v1',"
              "'quarantined',0,'t')", (gid,))
    c.execute("INSERT INTO row_check_fail VALUES ('kpi_series',?,'unit_kind',1,'pct row without % at the number')",
              (gid,))
    # one segment figure filed on both bases, standalone later: no basis asked must give the group figure first
    seg = ins.replace("'consolidated'", "?")
    c.execute(seg, ("segment_ebit", "beauty", 1235.0, "inr_cr", "Q2FY27", "2026-09-30", "consolidated", "c.xml",
                    "", "2026-10-28T19:24:48"))
    c.execute(seg, ("segment_ebit", "beauty", 1242.0, "inr_cr", "Q2FY27", "2026-09-30", "standalone", "s.xml",
                    "", "2026-10-28T23:11:55"))
    c.execute("UPDATE kpi_series SET conf_rank=1 WHERE metric='order_intake' AND value=100.0")
    c.execute("UPDATE kpi_series SET conf_rank=4 WHERE metric='order_intake' AND value=200.0")
    c.executemany("INSERT INTO fin_annual_line VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("KEC", "INE389H01022", "FY25", "2025-03-31", "consolidated", "PL", "pat", "PAT", 4.0e9, "inr", 1.0, "f.xml",
         None, "ProfitLoss = 4e9", "results_xbrl.db", "facts", "f.xml#1", "2025-05-20T10:00:00", "x", 1, 0,
         "xbrl_reported", "FY"),
        # the same measure filed standalone and consolidated: no basis asked must mean the group statement
        ("KEC", "INE389H01022", "FY25", "2025-03-31", "standalone", "PL", "eps_diluted", "Diluted EPS", 45.31,
         "inr_per_share", 1.0, "s.xml", None, "Diluted EPS 45.31", "results_xbrl.db", "facts", "s.xml#1",
         "2025-05-20T10:00:00", "x", 1, 0, "xbrl_reported", "FY"),
        ("KEC", "INE389H01022", "FY25", "2025-03-31", "consolidated", "PL", "eps_diluted", "Diluted EPS", 60.20,
         "inr_per_share", 1.0, "c.xml", None, "Diluted EPS 60.20", "results_xbrl.db", "facts", "c.xml#1",
         "2025-05-20T10:00:00", "x", 1, 0, "xbrl_reported", "FY")])
    c.execute("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, audited, "
              "statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, source_table, source_rowid, "
              "known_at, known_at_source, is_reported) VALUES ('KEC','INE389H01022','2025-10-01','2025-12-31','Q3FY26',"
              "'consolidated','a','PL','pat','Tag',1.5e9,'inr',1.0,'q.xml','results_xbrl.db','quarterly','q.xml',"
              "'2026-02-05T10:00:00','x',1)")
    c.execute("INSERT INTO formula VALUES ('F_ROE','roe','100*pat/net_worth','[]','pct',1,'n')")
    c.execute("INSERT INTO ratio_panel VALUES ('KEC','I','FY25','FY','2024-04-01','2025-03-31','consolidated','roe',"
              "12.5,'pct',1,'F_ROE','[\"a\"]','2025-05-20T10:00:00','x',1)")
    c.execute("INSERT INTO valuation_daily VALUES ('KEC','I','2026-03-30','consolidated',500,1e8,5e10,25,2.5e9,1e10,"
              "1e9,3e9,20,5,12,0.5,'2026-03-30','x','{}')")
    c.executemany("INSERT INTO shp_category VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("KEC", "I", "2025-09-30", "promoter", "Promoter", 1.0e8, 52.0, 10, "pct", "xbrl", "shp0.xml", "db", "t", "0",
         None, "2025-10-20T10:00:00", "x", 1, 1.0e9, "total_shares"),
        ("KEC", "I", "2025-12-31", "promoter", "Promoter", 1.0e8, 51.5, 10, "pct", "xbrl", "shp.xml", "db", "t", "1",
         None, "2026-01-20T10:00:00", "x", 1, 1.0e9, "total_shares"),
        ("KEC", "I", "2025-12-31", "fpi_total", "InstitutionsForeign (FII/FPI line)", 8.5e7, 8.5, None, "pct", "xbrl",
         "shp.xml", "db", "t", "2", None, "2026-01-20T10:00:00", "x", 1, 1.0e9, "total_shares"),
        ("KEC", "I", "2025-12-31", "mutual_funds", "MutualFundsOrUTI", 9.5e7, 9.5, 20, "pct", "xbrl", "shp.xml", "db",
         "t", "3", None, "2026-01-20T10:00:00", "x", 1, 1.0e9, "total_shares"),
        ("KEC", "I", "2026-03-31", "promoter", "Promoter", 1.0e8, 52.0, 10, "pct", "xbrl", "shp2.xml", "db", "t", "4",
         None, "2026-04-20T10:00:00", "x", 1, 1.0e9, "total_shares"),
        # the shp_index copy of promoter/public: one value per category and quarter, the XBRL row wins
        ("KEC", "I", "2026-03-31", "promoter", "promoter", None, 52.0, None, "pct", "index", "shp_index",
         "equity_intelligence.db", "shp_index", "9", None, "2026-04-20T10:00:00", "x", 1, None, None),
        ("KEC", "I", "2026-03-31", "fpi_total", "InstitutionsForeign (FII/FPI line)", 8.0e7, 8.0, None, "pct", "xbrl",
         "shp2.xml", "db", "t", "5", None, "2026-04-20T10:00:00", "x", 1, 1.0e9, "total_shares"),
        ("KEC", "I", "2026-03-31", "mutual_funds", "MutualFundsOrUTI", 9.0e7, 9.0, 20, "pct", "xbrl", "shp2.xml", "db",
         "t", "6", None, "2026-04-20T10:00:00", "x", 1, 1.0e9, "total_shares"),
        ("KEC", "I", "2026-02-10", "promoter", "Promoter", 1.0e8, 51.8, 10, "pct", "xbrl", "shp1b.xml", "db", "t",
         "11", None, "2026-02-20T10:00:00", "x", 1, 1.0e9, "total_shares"),
        # T-165: the Government of India line (Vodafone Idea's 49%) and a newest quarter that holds only the
        # shp_index promoter row, before its XBRL categories arrive
        ("KEC", "I", "2026-03-31", "central_government_or_president_of_india", "CentralGovernmentOrPresidentOfIndia",
         2.6e8, 26.0, 1, "pct", "xbrl", "shp2.xml", "db", "t", "7", None, "2026-04-20T10:00:00", "x", 1, 1.0e9,
         "total_shares"),
        ("KEC", "I", "2026-06-30", "promoter", "promoter", None, 52.0, None, "pct", "index", "shp_index",
         "equity_intelligence.db", "shp_index", "10", None, "2026-07-05T10:00:00", "x", 1, None, None)])
    # T-088: the named holders and the promoter encumbrance block of the latest quarter
    c.executemany("INSERT INTO shp_holder VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("KEC", "I", "2026-03-31", "promoter_individuals", "A Promoter", 2.0e7, 20.0, 1, None, None, None,
         "shp2.xml", "db", "xml.gz", "2026-04-20T10:00:00", "x"),
        ("KEC", "I", "2026-03-31", "pac_public", "A Promoter", 2.0e7, 20.0, 1, "A Concert Party", 20.0, None,
         "shp2.xml", "db", "xml.gz", "2026-04-20T10:00:00", "x")])
    c.execute("INSERT INTO shp_pledge VALUES ('KEC','I','2026-03-31',1,0,0,1.0e8,1.25e7,12.5,0.0,1.25e7,"
              "'shp2.xml','2026-04-20T10:00:00','x')")
    # T-108: the quarter before states a nil pledge (flag 0, no counts printed)
    c.execute("INSERT INTO shp_pledge VALUES ('KEC','I','2025-12-31',0,0,0,1.0e8,NULL,NULL,NULL,NULL,"
              "'shp1.xml','2026-01-20T10:00:00','x')")
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


def payload(result) -> Any:
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

    def test_kpi_gives_the_consolidated_figure_first(self):
        rows = p3.kpi("KEC", "segment_ebit", "Q2FY27")["rows"]
        self.assertEqual([(r["value"], r["basis"]) for r in rows], [(1235.0, "consolidated"), (1242.0, "standalone")])

    def test_fin_defaults_to_consolidated_and_labels_basis(self):
        """No basis asked means the group statement (HINDALCO FY26 diluted EPS: consolidated 60.20, not 45.31),
        and every row says which basis it is."""
        out = p3.fin("KEC", "eps_diluted", "FY25")
        self.assertEqual([(r["basis"], r["value"]) for r in out["rows"]], [("consolidated", 60.20)])
        self.assertEqual(out["basis_assumed"], "consolidated")
        self.assertProvenance(out["rows"])
        standalone = p3.fin("KEC", "eps_diluted", "FY25", basis="standalone")
        self.assertEqual([(r["basis"], r["value"]) for r in standalone["rows"]], [("standalone", 45.31)])
        self.assertIsNone(standalone["basis_assumed"])
        self.assertEqual(p3.fin("KEC", "pat", "FY25")["rows"][0]["basis"], "consolidated")  # single-basis measure

    def test_fin_printed_comparative_when_xbrl_lacks_the_quarter(self):
        """T-057: a quarter fin_quarter_xbrl does not hold comes back from the printed results columns."""
        c = sqlite3.connect(DB)
        c.execute("INSERT INTO fin_quarter_printed (symbol, isin, period_start, period_end, fiscal_period, period_type, "
                  "column_role, basis, statement, line_item, caption, value, unit, scale, raw_token, quote, doc_key, "
                  "page, known_at, known_at_source, check_status, check_detail, is_reported) "
                  "VALUES ('KEC','INE389H01022','2025-07-01','2025-09-30','Q2FY26',"
                  "'quarter','year_ago','consolidated','P&L','revenue_from_operations','Revenue from operations',"
                  "6.09156e10,'inr',1.0,'6,091.56','1 Revenue from operations 6,091.56 5,023.54','pdfs/KEC/results.pdf',"
                  "6,'2026-11-02T20:55:39','doc.known_at','sum_ok',NULL,1)")
        c.commit()
        c.close()
        try:
            out = p3.fin("KEC", "revenue", "Q2FY26", "consolidated")
            row = next(r for r in out["rows"] if r["period"] == "Q2FY26")
            self.assertEqual(row["definition"], "printed_comparative")
            self.assertEqual(row["provenance"]["table"], "fin_quarter_printed")
            self.assertEqual(row["value_inr"], 6.09156e10)
            self.assertEqual(row["column_role"], "year_ago")
            early = p3.fin("KEC", "revenue", "Q2FY26", "consolidated", as_of="2025-10-01")
            self.assertFalse([r for r in early["rows"] if r["definition"] == "printed_comparative"])
        finally:
            c = sqlite3.connect(DB)
            c.execute("DELETE FROM fin_quarter_printed")
            c.commit()
            c.close()

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
        promoter = next(r for r in a["rows"] if r["category"] == "promoter")
        self.assertEqual((a["quarter_end"], promoter["pct"]), ("2025-12-31", 51.5))
        self.assertEqual(a["share_capital"]["shares_outstanding"], 2.6e8)
        self.assertProvenance(a["rows"])
        b = p3.holding("KEC", "2026-06-01")
        promoter = next(r for r in b["rows"] if r["category"] == "promoter")
        self.assertEqual((b["quarter_end"], promoter["pct"]), ("2026-03-31", 52.0))
        self.assertFalse(p3.holding("KEC", "2025-06-01")["found"])
        with self.assertRaises(core.DataError):
            p3.holding("KEC", "")

    def test_holding_names_holders_the_pledge_block_and_what_it_covers(self):
        """T-088: the named holders of the quarter, the filing's own pledge answer and the coverage."""
        out = p3.holding("KEC", "2026-06-01")
        self.assertEqual(out["quarters_held"], {"first": "2025-09-30", "last": "2026-03-31", "count": 4})
        self.assertIn("promoter", out["categories_held"])
        # default: the named holders, the persons-in-concert twin left out so it never doubles a sum
        self.assertEqual([(h["holder"], h["category"], h["shares"], h["pct"]) for h in out["holders"]],
                         [("A Promoter", "promoter_individuals", 2.0e7, 20.0)])
        full = p3.holding("KEC", "2026-06-01", all_holders=True)
        self.assertEqual({h["category"] for h in full["holders"]}, {"promoter_individuals", "pac_public"})
        self.assertEqual(next(h for h in full["holders"] if h["category"] == "pac_public")["pac_name"], "A Concert Party")
        pledge = out["promoter_pledge"]
        self.assertTrue(pledge["pledge_flag"])
        self.assertEqual(pledge["pledged_pct_of_promoter_holding"], 12.5)      # the filing's own percentage
        self.assertIn("12.5% of the promoter holding is pledged", pledge["answer"])
        self.assertEqual(pledge["provenance"]["table"], "shp_pledge")
        # T-108: the quarter before is carried for "has it changed?"
        self.assertTrue(pledge["previous_quarter"]["nil"])
        self.assertEqual(pledge["previous_quarter"]["pledged_pct_of_promoter_holding"], 0.0)
        self.assertTrue(pledge["changed"])
        # a quarter filed before the holder table reached it says so, it does not claim there is no holder
        early = p3.holding("KEC", "2026-02-01")
        nil = early["promoter_pledge"]                                          # nil is a fact, not 'not found'
        self.assertTrue(nil["nil"])
        self.assertEqual((nil["pledged_shares"], nil["pledged_pct_of_promoter_holding"]), (0.0, 0.0))
        self.assertTrue(nil["answer"].startswith("nil:"))
        self.assertEqual(early["holders"], [])
        self.assertIn("no named holder row", early["holders_note"])

    def test_holding_returns_every_category_with_its_basis(self):
        """T-165: every filed shp_category row of the quarter, not promoter/public only, each with its basis."""
        out = p3.holding("KEC", "2026-06-01")
        got = {r["category"]: r for r in out["rows"]}
        self.assertEqual(got["promoter"]["pct"], 52.0)
        self.assertEqual(got["fpi_total"]["pct"], 8.0)
        self.assertEqual(got["mutual_funds"]["pct"], 9.0)
        self.assertEqual(got["central_government_or_president_of_india"]["pct"], 26.0)
        self.assertEqual(got["promoter"]["pct_basis"], "total_shares")
        self.assertEqual(got["promoter"]["pct_base_shares"], 1.0e9)
        # one value per category and quarter: the XBRL parse, never the shp_index copy beside it
        self.assertEqual([r["source_kind"] for r in out["rows"] if r["category"] == "promoter"], ["xbrl"])
        self.assertProvenance(out["rows"])

    def test_holding_category_words_and_government(self):
        """T-165: GoI maps to central_government_or_president_of_india; FPI/MF filter; a miss lists what exists."""
        goi = p3.holding("KEC", "2026-06-01", category="GoI")
        self.assertEqual([(r["category"], r["pct"]) for r in goi["rows"]],
                         [("central_government_or_president_of_india", 26.0)])
        self.assertEqual(goi["matched_categories"], ["central_government_or_president_of_india"])
        self.assertEqual(p3.holding("KEC", "2026-06-01", category="government")["rows"][0]["pct"], 26.0)
        both = p3.holding("KEC", "2026-06-01", category="FPI, MF")
        self.assertEqual([(r["category"], r["pct"]) for r in both["rows"]],
                         [("fpi_total", 8.0), ("mutual_funds", 9.0)])
        miss = p3.holding("KEC", "2026-06-01", category="sovereign")
        self.assertFalse(miss["found"])
        self.assertIn("central_government_or_president_of_india", miss["categories_held"])
        self.assertIn("no filed category matches", miss["hint"])

    def test_holding_quarters_series_and_the_latest_complete_filing(self):
        """T-165: quarters=N gives the path in one call; a newest quarter holding only the index promoter row does
        not hide the last complete XBRL quarter (Vodafone Idea's GoI 49% sat behind exactly that)."""
        out = p3.holding("KEC", "2026-07-10", category="promoter, fpi", quarters=2)
        self.assertEqual([(r["quarter_end"], r["category"], r["pct"]) for r in out["rows"]],
                         [("2026-03-31", "fpi_total", 8.0), ("2026-03-31", "promoter", 52.0),
                          ("2025-12-31", "fpi_total", 8.5), ("2025-12-31", "promoter", 51.5)])
        self.assertEqual(out["quarters_returned"], ["2026-03-31", "2025-12-31"])
        # a filing dated inside a quarter is not a trend point; the quarter ends stay comparable
        trend = p3.holding("KEC", "2026-06-01", category="promoter", quarters=3)
        self.assertEqual(trend["quarters_returned"], ["2026-03-31", "2025-12-31", "2025-09-30"])
        latest = p3.holding("KEC", "2026-07-10")           # 2026-06-30 has only its shp_index promoter row
        self.assertEqual(latest["quarter_end"], "2026-03-31")
        self.assertIn("mutual_funds", {r["category"] for r in latest["rows"]})

    def test_kpi_matches_the_words_investors_use(self):
        """T-165: NIM / net interest margin, credit cost and cost of funds resolve to the stored metric names."""
        for word, metric, value in (("NIM", "nim_pct", 8.2), ("net interest margin", "nim_pct", 8.2),
                                    ("credit cost", "credit_cost_bps", 140.0),
                                    ("losses and provisions to assets", "credit_cost_bps", 140.0),
                                    ("cost of funds", "cost_of_funds_pct", 6.7),
                                    ("cost of borrowings", "cost_of_funds_pct", 6.7)):
            out = p3.kpi("KEC", word, "Q1FY27")
            self.assertTrue(out["found"], word)
            self.assertEqual(out["metrics_matched"], [metric], word)
            self.assertEqual(out["rows"][0]["value"], value, word)

    def test_kpi_says_when_a_quarantined_row_holds_the_figure(self):
        """T-165/T-113: an empty reply separates 'not held' from 'held but quarantined' (Chola Q2FY27 NIM)."""
        out = p3.kpi("KEC", "GNPA", "Q1FY27")
        self.assertFalse(out["found"])
        self.assertTrue(any("Q1FY27 / total" in h and "include_quarantined" in h
                            for h in out["held_quarantined"]))
        shown = p3.kpi("KEC", "GNPA", "Q1FY27", include_quarantined=True)
        self.assertEqual(shown["rows"][0]["check_status"], "quarantined")
        self.assertEqual(shown["rows"][0]["value"], 4.2)

    def test_cells_serve_verified_and_unverified_and_hide_quarantined(self):
        """T-189: unverified cells are served labelled (recall), quarantined cells never are."""
        out = p3.cells("KEC", "order book")
        self.assertTrue(out["found"])
        self.assertEqual({r["status"] for r in out["rows"]}, {"verified", "unverified"})
        self.assertNotIn("99,999", [r["value_text"] for r in out["rows"]])
        self.assertProvenance(out["rows"])
        verified = p3.cells("KEC", "order book", include_unverified=False)
        self.assertEqual({r["status"] for r in verified["rows"]}, {"verified"})

    def test_cells_are_point_in_time(self):
        out = p3.cells("KEC", "order book", as_of="2026-06-01")
        self.assertEqual(sorted(r["value_text"] for r in out["rows"]), ["40,000", "41,500"])

    def test_cells_period_narrows_the_column(self):
        out = p3.cells("KEC", "order book", period="Q1FY27")
        self.assertEqual([r["value_text"] for r in out["rows"]], ["45,000"])

    def test_fact_falls_back_to_cells(self):
        out = p3.fact("KEC", "gross written premium")
        self.assertTrue(out["found"])
        self.assertEqual(out["route"], "cells")
        self.assertEqual(out["answer"]["source"]["table"], "page_cell")
        self.assertEqual(out["answer"]["value"], "2,100")
        self.assertEqual(out["answer"]["check_status"], "verified")

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

    def test_guidance_rows_and_revision_chain(self):
        out = p3.guidance("KEC", metric="revenue")
        self.assertTrue(out["found"])
        # T-105: the default view is the current target per metric+period; the February row is superseded
        self.assertEqual([r["said_on"] for r in out["rows"]], ["2026-08-10"])
        self.assertEqual(out["rows"][0]["superseded_rows"], 1)
        history = p3.guidance("KEC", metric="revenue", history=True)
        self.assertEqual([r["said_on"] for r in history["rows"]], ["2026-08-10", "2026-02-10"])
        latest = out["rows"][0]
        self.assertEqual((latest["low"], latest["high"], latest["period"], latest["unit"]),
                         (12.0, 15.0, "FY27", "pct"))
        self.assertEqual(latest["revision_of"], 1)
        self.assertEqual(latest["previous"]["said_on"], "2026-02-10")
        self.assertFalse(latest["changed"])               # the same 12-15% repeated: nothing changed
        self.assertProvenance(out["rows"])
        margins = p3.guidance("KEC", metric="margin", period="FY26")
        self.assertEqual((margins["rows"][0]["low"], margins["rows"][0]["high"], margins["rows"][0]["direction"]),
                         (7.0, 7.5, "down"))
        self.assertFalse(p3.guidance("KEC", metric="margin", as_of="2026-02-01")["found"])   # not public yet
        miss = p3.guidance("KEC", metric="nonsense")
        self.assertFalse(miss["found"])
        self.assertIn("revenue_growth", miss["available"])

    def test_statements_falls_back_to_the_call_page_text(self):
        """A topic no statement tag carries is searched in the calls' own page text, not answered with nothing."""
        out = p3.statements("KEC", topic="power")
        self.assertTrue(out["found"])
        self.assertFalse(out["topic_matched"])
        self.assertEqual(out["fallback"], "doc_page_bm25")
        self.assertEqual(out["rows"][0]["provenance"]["table"], "doc_page")
        self.assertIn("transmission", out["rows"][0]["quote"].lower())
        # a topic the tagger does carry keeps using the tagged statements, with no fallback
        tagged = p3.statements("KEC", topic="margin")
        self.assertIsNone(tagged["fallback"])

    def test_analyst_questions_view(self):
        # the view exists and serves rows inserted into transcript_question
        import sqlite3
        c = sqlite3.connect(DB)
        c.execute("INSERT INTO transcript_question(symbol,doc_key,call_date,call_period,page,analyst,firm,question,topics,entities,answer_turn,known_at,known_at_source,extractor_rule) "
                  "VALUES ('KEC','pdfs/KEC/call.pdf','2026-02-12','Q3FY26',1,'Ravi Kumar','Axis Capital','Could you explain the safeguard duty?','trade_policy','safeguard',1,'2026-02-14T10:00:00','docs.known_at','t')")
        c.commit()
        c.close()
        out = p3.analyst_questions("KEC", n_calls=4)
        self.assertTrue(out["found"])
        self.assertEqual(out["rows"][0]["analyst"], "Ravi Kumar")
        self.assertEqual(out["rows"][0]["firm"], "Axis Capital")
        self.assertIn("safeguard", out["rows"][0]["question"])
        # the view is queryable directly
        c = sqlite3.connect(DB)
        v = c.execute("SELECT COUNT(*) FROM analyst_questions WHERE symbol='KEC'").fetchone()[0]
        c.close()
        self.assertGreaterEqual(v, 1)

    def test_statements_whole_turn_with_entities_filter(self):
        # whole_turn=True must not crash when an entities filter is supplied (T-164 E)
        out = p3.statements("KEC", entities="transmission", whole_turn=True)
        self.assertIn("found", out)
        out2 = p3.statements("KEC", whole_turn=True)
        self.assertIn("found", out2)

    def test_statements_whole_turn_limit_counts_turns_not_rows(self):
        """Step 5 (T-164 r7): limit=1 returns one answer turn (all its sentences), not 1 matching row plus
        its siblings from several turns."""
        c = sqlite3.connect(DB)
        cols = ("symbol,doc_key,call_date,call_period,page,seq,speaker,role,section,topics,period_discussed,"
                "period_source,numbers_json,statement,quote,is_fragment,entities,answer_turn,known_at,"
                "known_at_source,extractor_rule")
        for turn, seq0 in ((101, 1), (102, 4)):
            for k in range(3):
                stmt = f"Turnword sentence {turn}.{k}."
                c.execute(f"INSERT INTO transcript_statement({cols}) VALUES ('KEC','r7/turns.pdf','2026-09-01',"
                          "'Q2FY27',2,?,'A B','ceo','qa','margin','Q2FY27','t','[]',?,?,0,'',?,'2026-09-02T10:00:00',"
                          "'x','t')", (seq0 + k, stmt, stmt, turn))
        c.commit()
        c.close()
        out = p3.statements("KEC", terms="turnword", limit=1, whole_turn=True)
        rows = out["rows"]
        self.assertEqual(len({r["answer_turn"] for r in rows}), 1)
        self.assertEqual(len(rows), 3)          # the whole turn, not just the matched sentence
        self.assertEqual(rows[0]["answer_turn"], 101)   # seq order inside the same call

    def test_whole_turn_is_keyed_by_document_and_never_sweeps_prepared_remarks(self):
        """Step 2 (T-164 r8): answer-turn ids collide across two calls of one company and prepared remarks carry
        negative ids.  limit=2 returns exactly two (document, turn) groups; a prepared-remarks turn appears only
        when the match itself selected it."""
        c = sqlite3.connect(DB)
        cols = ("symbol,doc_key,call_date,call_period,page,seq,speaker,role,section,topics,period_discussed,"
                "period_source,numbers_json,statement,quote,is_fragment,entities,answer_turn,known_at,"
                "known_at_source,extractor_rule")
        for doc, day, seq0 in (("r8/crossA.pdf", "2026-09-03", 20), ("r8/crossB.pdf", "2026-09-04", 20)):
            for k in range(2):
                stmt = f"Crossdoc answer {doc[-6]}.{k}."
                c.execute(f"INSERT INTO transcript_statement({cols}) VALUES ('KEC',?,?,'Q2FY27',2,?,"
                          "'A B','ceo','qa','margin','Q2FY27','t','[]',?,?,0,'',7,'2026-09-05T10:00:00','x','t')",
                          (doc, day, seq0 + k, stmt, stmt))
        for k in range(2):
            stmt = f"Preparedword remark {k}."
            c.execute(f"INSERT INTO transcript_statement({cols}) VALUES ('KEC','r8/crossA.pdf','2026-09-03',"
                      "'Q2FY27',2,?,'A B','ceo','prepared','margin','Q2FY27','t','[]',?,?,0,'',-1,"
                      "'2026-09-05T10:00:00','x','t')", (30 + k, stmt, stmt))
        c.commit()
        c.close()
        out = p3.statements("KEC", terms="crossdoc", limit=2, whole_turn=True)
        rows = out["rows"]
        groups = {(r["provenance"]["source"], r["answer_turn"]) for r in rows}
        self.assertEqual(len(groups), 2, groups)          # two documents, not one id seen twice
        self.assertEqual(len(rows), 4)                    # both turns in full
        self.assertFalse(any("Preparedword" in r["quote"] for r in rows))
        prep = p3.statements("KEC", terms="preparedword", limit=1, whole_turn=True)["rows"]
        self.assertEqual({r["answer_turn"] for r in prep}, {-1})
        self.assertEqual(len(prep), 2)                    # selected prepared remarks expand as their own turn

    def test_statements_entity_search(self):
        out = p3.statements("KEC", entities="transmission")
        # no entity named transmission in fixture; ensure no crash and found flag sensible
        self.assertIn("found", out)

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

    def test_search_period_is_normalised_never_prefixed_twice(self):
        """A period of FY26 / Q3 FY2026 goes through norm_period: the reply echoes FY26 / Q3FY26, never FYFY26."""
        for asked, want in (("FY26", "FY26"), ("Q3 FY2026", "Q3FY26"), ("2025-26", "FY26")):
            out = p3.search("KEC", "order book", period=asked)
            self.assertEqual(out["period"], want, asked)
            self.assertNotIn("FYFY", json.dumps(out))
        # an unrecognised period is not a label: the query's own period is used instead
        out = p3.search("KEC", "order book Q3FY26", period="next year")
        self.assertEqual(out["period"], "Q3FY26")

    def test_search_survives_a_document_without_a_filing_date(self):
        """The ranker used to read a 'known_at' column the SELECT did not return: a page under an undated document
        raised IndexError.  It now falls back to the page's known_at / the document's."""
        out = p3.search("KEC", "special undated tariffs")
        self.assertTrue(out["found"])
        self.assertEqual(out["rows"][0]["filing_date"], None)
        self.assertProvenance(out["rows"])

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

    def test_sql_as_of_hides_later_pages_and_rows(self):
        # T-156: a dated question read a transcript filed after its date through sql; as_of shadows the tables
        q = "SELECT d.doc_key, p.page FROM doc_page p JOIN doc d ON d.doc_key = p.doc_key WHERE p.symbol='KEC'"
        everything = {tuple(r) for r in p3.sql(q)["rows"]}
        early = p3.sql(q, as_of="2026-03-01")
        self.assertEqual(early["as_of"], "2026-03-01")
        keys = {r[0] for r in early["rows"]}
        self.assertIn("pdfs/KEC/deck1.pdf", keys)
        self.assertNotIn("pdfs/KEC/deck2.pdf", keys)             # filed 2026-08-10
        self.assertNotIn("KEC:undated/call.pdf", keys)           # no known_at: never served for a dated question
        self.assertGreater(len(everything), len(early["rows"]))
        docs = p3.sql("SELECT COUNT(*) FROM doc", as_of="2026-03-01")["rows"][0][0]
        self.assertLess(docs, p3.sql("SELECT COUNT(*) FROM doc")["rows"][0][0])
        self.assertEqual(p3.sql("SELECT COUNT(*) FROM doc")["rows"], [[4]])   # shared connection untouched after

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

    def test_sql_max_chars_widens_text_and_is_capped(self):
        """A text cell is cut at 400 by default; max_chars widens it to a hard cap of 8000 (T-049, 4 Nov 2026)."""
        default = p3.sql("select hex(zeroblob(400)) as t")["rows"][0][0]
        self.assertEqual(len(default), 402)                    # 400 + " …"
        self.assertEqual(default[-2:], " …")
        wide = p3.sql("select hex(zeroblob(400)) as t", max_chars=8000)
        self.assertEqual((len(wide["rows"][0][0]), wide["max_chars"]), (800, 8000))
        capped = p3.sql("select hex(zeroblob(5000)) as t", max_chars=99_999)
        self.assertEqual((len(capped["rows"][0][0]), capped["max_chars"]), (8002, 8000))
        with self.assertRaises(core.DataError) as ctx:
            p3.sql("select 1", max_chars="lots")
        self.assertEqual(ctx.exception.code, "bad_max_chars")

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
                    self.assertIn("PILOT3 FIRST", init.instructions or "")
                    self.assertIn("company table", init.instructions or "")
                    for sym in ("KEC", "BAJFINANCE", "HINDALCO"):
                        self.assertNotIn(sym, init.instructions or "")   # T-090: coverage is never a fixed company list
                    names = {t.name for t in (await session.list_tools()).tools}
                    self.assertTrue(TOOLS <= names)
                    calls = {
                        "pilot3_kpi": {"symbol": "KEC", "kpi": "order_book", "period": "Q3FY26"},
                        "pilot3_fin": {"symbol": "KEC", "measure": "pat", "period": "FY25"},
                        "pilot3_ratio": {"symbol": "KEC", "ratio": "roe", "period": "FY25"},
                        "pilot3_holding": {"symbol": "KEC", "as_of": "2026-06-01"},
                        "pilot3_statements": {"symbol": "KEC", "topic": "margin"},
                        "pilot3_guidance": {"symbol": "KEC", "metric": "revenue"},
                        "pilot3_docs": {"symbol": "KEC", "doc_type": "deck"},
                        "pilot3_search": {"symbol": "KEC", "query": "order book"},
                    }
                    for name, args in calls.items():
                        out = payload(await session.call_tool(name, args, read_timeout_seconds=60))
                        self.assertTrue(out["found"], name)
                        self.assertTrue(all(r["provenance"]["source"] for r in out["rows"]), name)
                    one = payload(await session.call_tool("pilot3_fact", {"symbol": "KEC", "metric": "pat",
                                                                          "period": "FY25"},
                                                          read_timeout_seconds=60)) or {}
                    self.assertTrue(one.get("found"))
                    self.assertEqual((one.get("answer") or {}).get("period"), "FY25")
                    self.assertEqual(((one.get("answer") or {}).get("source") or {}).get("table"), "fin_annual_line")
                    sql = payload(await session.call_tool("pilot3_sql", {"query": "select count(*) from doc"},
                                                          read_timeout_seconds=60))
                    self.assertEqual(sql["rows"], [[4]])  # fixture has 4 docs since the undated-document test (T-049 guidance)
                    bad = payload(await session.call_tool("pilot3_sql", {"query": "drop table doc"},
                                                          read_timeout_seconds=60))
                    self.assertFalse(bad["ok"])
                    other = payload(await session.call_tool("pilot3_kpi", {"symbol": "TCS", "kpi": "x"},
                                                            read_timeout_seconds=60))
                    self.assertEqual(other["error"]["code"], "not_pilot3")

        try:
            asyncio.run(asyncio.wait_for(scenario(), 120))
        except PermissionError as exc:
            # a confined dsh worker cannot create child-process pipes (the same skip McpStdioTests uses)
            self.skipTest(f"the sandbox denies child-process pipes: {exc}")


class EvAllInvestmentsTests(unittest.TestCase):
    """MARUTI-083: EV/EBITDA also served on net debt after non-current investments, with a note when they differ."""

    def test_ev_ebitda_gives_the_all_investments_variant(self):
        build_fixture()
        c = sqlite3.connect(DB)
        c.execute("INSERT INTO fin_annual_line VALUES ('KEC','I','FY26','2026-03-31','consolidated','BS',"
                  "'net_debt_all_investments','c',-2.0e10,'inr',1.0,'f.xml',NULL,'q','d','t','r',"
                  "'2026-03-01T10:00:00','x',1,1,'xbrl_derived','FY')")
        c.commit()
        c.close()
        os.environ["REALITY_PILOT3_DB"] = str(DB)
        p3.close()
        try:
            got = p3.ratio("KEC", "ev_ebitda", as_of="2026-03-31")
        finally:
            p3.close()
            os.environ.pop("REALITY_PILOT3_DB", None)
        inputs = got["rows"][0]["inputs"]
        self.assertEqual(inputs["net_debt_all_investments"], -2.0e10)
        self.assertAlmostEqual(inputs["ev_ebitda_all_investments"], (5e10 - 2.0e10) / 3e9, places=2)
        self.assertIn("non-current investments", got["note"])


class FactTests(unittest.TestCase):
    """T-186: one call returns the preferred figure with the source, the period, the basis and the formula inputs."""

    @classmethod
    def setUpClass(cls):
        build_fixture()
        c = sqlite3.connect(DB)
        c.execute("INSERT INTO fin_annual_line VALUES ('KEC','INE389H01022','FY26','2026-03-31','consolidated',"
                  "'PL','revenue_from_operations','Revenue from operations',1.234e11,'inr',1.0,'rev.pdf',7,"
                  "'Revenue from operations 12,340 crore','results','t','r','2026-05-20T10:00:00','x',1,0,"
                  "'reported','FY')")
        # T-186: a later annual-report page must not replace the XBRL filing's figure
        c.executemany("INSERT INTO fin_annual_line VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            ("KEC", "INE389H01022", "FY25", "2025-03-31", "consolidated", "PL", "revenue_from_operations",
             "Revenue from operations", 9.5e10, "inr", 1.0, "ar.pdf", 13, "Revenue 95,130 crore",
             "ar_facts.db", "ar_facts", "9703", "2026-08-28T15:25:34", "x", 1, 0, "reported", "FY"),
            ("KEC", "INE389H01022", "FY25", "2025-03-31", "consolidated", "PL", "revenue_from_operations",
             "Revenue from operations", 2.1794e11, "inr", 1.0, "rev_xbrl.xml", None, "Revenue 21,794 crore",
             "results_xbrl.db", "facts", "rev_xbrl.xml#1", "2025-05-30T22:45:53", "x", 1, 0, "xbrl_reported", "FY")])
        # T-186: a row the independent checker quarantined is never the answer
        c.execute("INSERT INTO fin_annual_line VALUES ('KEC','INE389H01022','FY25','2025-03-31','consolidated',"
                  "'BS','borrowings','Borrowings',3.0e10,'inr',1.0,'bor.pdf',4,'Borrowings 30,000 crore',"
                  "'results_xbrl.db','facts','bor.xml#1','2025-05-20T10:00:00','x',1,0,'xbrl_reported','FY')")
        rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO row_check VALUES ('fin_annual_line',?,'KEC','borrowings','borrowings','infra',"
                  "'results','table_v1','quarantined',0,'t')", (rid,))
        c.commit()
        c.close()
        os.environ["REALITY_PILOT3_DB"] = str(DB)
        p3.close()

    @classmethod
    def tearDownClass(cls):
        p3.close()
        os.environ.pop("REALITY_PILOT3_DB", None)

    def test_a_reported_line_is_one_answer_with_doc_page_quote_and_known_at(self):
        out = p3.fact("KEC", "revenue", period="FY26")
        self.assertTrue(out["found"])
        self.assertEqual(out["route"], "fin")
        answer = out["answer"]
        self.assertEqual(answer["value"], 1.234e11)
        self.assertEqual(answer["unit"], "inr")
        self.assertEqual(answer["scale_word"], "rupee")
        self.assertEqual(answer["period"], "FY26")
        self.assertEqual(answer["basis"], "consolidated")
        self.assertEqual(answer["source"]["table"], "fin_annual_line")
        self.assertEqual(answer["source"]["doc_key"], "rev.pdf")
        self.assertEqual(answer["source"]["page"], 7)
        self.assertIn("12,340", answer["source"]["quote"])
        self.assertEqual(answer["known_at"], "2026-05-20T10:00:00")
        self.assertIsNone(answer["computed"])
        self.assertTrue(out["why_this_one"])

    def test_basis_asked_is_respected(self):
        consolidated = p3.fact("KEC", "eps diluted", "FY25")["answer"]
        self.assertEqual((consolidated["value"], consolidated["basis"]), (60.20, "consolidated"))
        standalone = p3.fact("KEC", "eps diluted", "FY25", basis="standalone")["answer"]
        self.assertEqual((standalone["value"], standalone["basis"]), (45.31, "standalone"))
        self.assertEqual(standalone["unit"], "inr_per_share")

    def test_a_ratio_carries_its_formula_and_inputs(self):
        out = p3.fact("KEC", "roe", "FY25")
        self.assertTrue(out["found"])
        self.assertEqual(out["route"], "ratio")
        answer = out["answer"]
        self.assertEqual(answer["value"], 12.5)
        self.assertEqual((answer["unit"], answer["scale_word"]), ("pct", "percent"))
        self.assertEqual(answer["computed"]["formula"], "100*pat/net_worth")
        self.assertEqual(answer["computed"]["inputs"][0]["name"], "a")

    def test_as_of_before_the_filing_is_not_found_with_the_search_list(self):
        out = p3.fact("KEC", "pat", period="FY25", as_of="2025-01-01")
        self.assertFalse(out["found"])
        self.assertTrue(out["searched"])
        self.assertTrue(any(row["names_matched"] for row in out["searched"]))
        self.assertIn("filed after", out["hint"])
        self.assertTrue(any("pat" in row["names_matched"] for row in out["searched"]))

    def test_an_unknown_metric_returns_the_nearest_rows(self):
        out = p3.fact("KEC", "roa")
        self.assertFalse(out["found"])
        self.assertTrue(out["nearest"])
        self.assertTrue(out["nearest"][0]["nearest"])
        self.assertEqual(out["nearest"][0]["metric"], "roe")
        self.assertEqual(out["nearest"][0]["table"], "ratio_panel")

    def test_a_holding_word_asks_the_filing_in_force(self):
        out = p3.fact("KEC", "promoter holding", as_of="2026-06-01")
        self.assertTrue(out["found"])
        self.assertEqual(out["route"], "holding")
        answer = out["answer"]
        self.assertEqual(answer["value"], 52.0)
        self.assertEqual((answer["unit"], answer["period"]), ("pct", "2026-03-31"))
        self.assertEqual(answer["source"]["table"], "shp_category")
        self.assertIsNotNone(answer["known_at"])

    def test_a_company_stated_kpi_is_one_call(self):
        out = p3.fact("KEC", "order book", "Q3FY26")
        self.assertTrue(out["found"])
        self.assertEqual(out["route"], "kpi")
        answer = out["answer"]
        self.assertEqual(answer["value"], 40000.0)
        self.assertEqual((answer["unit"], answer["scale_word"]), ("inr_cr", "crore"))
        self.assertEqual(answer["period"], "Q3FY26")
        self.assertEqual(answer["source"]["page"], 1)
        self.assertIn("40,000", answer["source"]["quote"])

    def test_a_share_count_comes_from_share_capital(self):
        out = p3.fact("KEC", "shares outstanding", as_of="2026-06-01")
        self.assertTrue(out["found"])
        self.assertEqual(out["route"], "shares")
        answer = out["answer"]
        self.assertEqual(answer["value"], 2.6e8)
        self.assertEqual((answer["unit"], answer["period"]), ("shares", "2025-12-31"))
        self.assertEqual(answer["source"]["table"], "share_capital")

    def test_an_annual_line_prefers_the_xbrl_filing_over_a_later_report_page(self):
        out = p3.fact("KEC", "revenue", period="FY25")
        self.assertTrue(out["found"])
        self.assertEqual(out["answer"]["value"], 2.1794e11)
        self.assertNotEqual(out["answer"]["value"], 9.5e10)
        self.assertTrue(any(a.get("value") == 9.5e10 for a in out.get("alternatives", [])), out)

    def test_a_quarantined_row_is_never_the_answer(self):
        out = p3.fact("KEC", "borrowings", period="FY25")
        answer = out.get("answer") or {}
        self.assertNotEqual(answer.get("value"), 3.0e10, out)

    def test_a_holding_asked_for_a_fiscal_year_says_what_it_returned(self):
        out = p3.fact("KEC", "promoter holding", period="FY25", as_of="2026-06-01")
        if out.get("found"):
            self.assertTrue(out["answer"].get("mismatch"), out)


if __name__ == "__main__":
    unittest.main()
