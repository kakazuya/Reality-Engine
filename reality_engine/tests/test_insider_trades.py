"""Contract for build_insider_trades: source mapping, XBRL grouping, revisions, dedupe, PIT filter.

In-memory SQLite fixtures only; no network and no live DB.
"""
import json
import sqlite3
import unittest
import uuid
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.scripts import build_insider_trades as bit

SOURCE_DDL = """
CREATE TABLE mkt_nse_insider (
    did TEXT, symbol TEXT, company TEXT, acquirer_name TEXT, person_category TEXT,
    security_type TEXT, transaction_type TEXT, acquisition_mode TEXT,
    securities_qty REAL, securities_value REAL, buy_qty REAL, buy_value REAL,
    sell_qty REAL, sell_value REAL, before_pct TEXT, after_pct TEXT,
    acq_from TEXT, acq_to TEXT, intimation_date TEXT, disseminated_at TEXT);
CREATE TABLE mkt_nse_pit_filings (
    app_id TEXT, segment TEXT, symbol TEXT, company TEXT, submission_type TEXT,
    broadcast_at TEXT, disseminated_at TEXT, revision_remark TEXT, prev_app_id TEXT,
    xml_url TEXT);
CREATE TABLE mkt_nse_pit_xbrl_facts (
    xml_file TEXT, context_id TEXT, concept TEXT, seq INTEGER, value TEXT, unit TEXT);
CREATE TABLE mkt_bse_insider (
    file TEXT, line_no INTEGER, company TEXT, isin TEXT, person TEXT, raw_json TEXT);
CREATE TABLE symbol_isin_history (
    exchange TEXT, symbol TEXT, isin TEXT, first_date TEXT, last_date TEXT, n_days INTEGER);
CREATE TABLE security_master (isin TEXT, nse_symbol TEXT);
CREATE TABLE master_companies (isin TEXT, nse_symbol TEXT);
"""


def legacy_row(did, symbol, **kw):
    base = {
        "did": did, "symbol": symbol, "company": "Test Ltd", "acquirer_name": "Mr. Test Person",
        "person_category": "Promoter", "security_type": "Equity Shares",
        "transaction_type": "Buy", "acquisition_mode": "Market Purchase",
        "securities_qty": 1000.0, "securities_value": 50000.0, "buy_qty": None, "buy_value": None,
        "sell_qty": None, "sell_value": None, "before_pct": "1.5", "after_pct": "1.6",
        "acq_from": "2021-01-05", "acq_to": "2021-01-05", "intimation_date": "2021-01-06",
        "disseminated_at": "2021-01-06 18:00",
    }
    base.update(kw)
    return base


def bse_row(file, line_no, **kw):
    raw = {
        bit.BSE_COMPANY: "Test Ltd",
        bit.BSE_ISIN: kw.pop("isin", "INE000D01010"),
        bit.BSE_PERSON: "TEST PERSON",
        bit.BSE_QTY: "1000",
        bit.BSE_VALUE: "50000",
        bit.BSE_TXN: "Acquisition",
        bit.BSE_BEFORE_PCT: "1.5",
        bit.BSE_AFTER_PCT: "1.6",
        bit.BSE_DATE: "1/5/2021 12:00:00 AM",
        bit.BSE_MODE: "Market",
        bit.BSE_PROMOTER: "Promoter",
    }
    raw.update(kw)
    return (file, line_no, raw[bit.BSE_COMPANY], raw[bit.BSE_ISIN], raw[bit.BSE_PERSON],
            json.dumps(raw))


class InsiderTradeBuildTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(SOURCE_DDL)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()

    def history(self, rows):
        self.conn.executemany(
            "INSERT INTO symbol_isin_history VALUES (?,?,?,?,?,0)", rows)

    def build(self):
        return bit.build(self.conn)

    def v2(self, sql="SELECT * FROM insider_trades_v2 ORDER BY source_key", params=()):
        return [dict(row) for row in self.conn.execute(sql, params)]

    # ------------------------------------------------------------------
    def test_legacy_mapping_and_isin_history(self):
        self.history([("NSE", "AAA", "INE000A01010", "2019-01-01", "2020-12-31"),
                      ("NSE", "AAA", "INE000B01010", "2021-01-01", "2025-12-31")])
        self.conn.executemany(
            "INSERT INTO mkt_nse_insider VALUES (:did,:symbol,:company,:acquirer_name,"
            ":person_category,:security_type,:transaction_type,:acquisition_mode,"
            ":securities_qty,:securities_value,:buy_qty,:buy_value,:sell_qty,:sell_value,"
            ":before_pct,:after_pct,:acq_from,:acq_to,:intimation_date,:disseminated_at)",
            [legacy_row("1", "AAA", acq_from="2020-06-01", acq_to="2020-06-01"),
             legacy_row("2", "AAA", transaction_type="Pledge Invoke",
                        acquisition_mode="Invocation of pledge", securities_qty=200.0,
                        securities_value=4000.0, acq_from="2021-02-01", acq_to="2021-02-01")])
        self.build()
        rows = self.v2()

        first, second = rows
        self.assertEqual(first["source"], "nse_legacy")
        self.assertEqual(first["source_key"], "nse_legacy:1")
        self.assertEqual(first["isin"], "INE000A01010")  # ISIN valid on the trade date
        self.assertEqual(first["transaction_type"], "BUY")
        self.assertEqual(first["mode"], "MARKET_PURCHASE")
        self.assertEqual(first["qty"], 1000.0)
        self.assertEqual(first["value_inr"], 50000.0)
        self.assertEqual(first["before_pct"], 1.5)
        self.assertEqual(first["known_at"], "2021-01-06 18:00:00")
        self.assertEqual(first["also_on"], None)

        self.assertEqual(second["isin"], "INE000B01010")  # symbol re-ISINed in 2021
        self.assertEqual(second["transaction_type"], "OTHER")
        self.assertEqual(second["mode"], "PLEDGE_INVOCATION")

    def test_pit_xbrl_grouping_and_concept_mapping(self):
        self.history([("NSE", "CCC", "INE000C01010", "2019-01-01", "2026-12-31")])
        self.conn.execute(
            "INSERT INTO mkt_nse_pit_filings VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("10", "equities", "CCC", "Cee Ltd", "Original", "2026-05-10 10:00",
             "2026-05-10 10:00", None, None, "https://x/IT_WebXMLFile_100.xml"))
        facts = [
            ("MainI", "Symbol", "CCC"), ("MainI", "ISINCode", "INE000C01010"),
            ("MainI", "NameOfTheCompany", "Cee Ltd"), ("MainI", "RevisedFilling", "false"),
            ("Disclosure1", "NameOfThePerson", "Alice"),
            ("Disclosure1", "CategoryOfPerson", "Promoter"),
            ("Disclosure1", bit.PIT_TXN, "Buy"), ("Disclosure1", bit.PIT_MODE, "Market Purchase"),
            ("Disclosure1", "TypeOfInstrument", "Equity"),
            ("Disclosure1", bit.PIT_QTY, "1000"), ("Disclosure1", bit.PIT_VALUE, "50000"),
            ("Disclosure1", bit.PIT_BEFORE_PCT, "0.015"),
            ("Disclosure1", bit.PIT_AFTER_PCT, "0.016"),
            ("Disclosure1", bit.PIT_FROM, "2026-05-08"), ("Disclosure1", bit.PIT_TO, "2026-05-08"),
            ("Disclosure1", bit.PIT_INTIM, "2026-05-09"),
            ("Disclosure2", "NameOfThePerson", "Bob"),
            ("Disclosure2", "CategoryOfPerson", "KMP"),
            ("Disclosure2", bit.PIT_TXN, "Sell"), ("Disclosure2", bit.PIT_MODE, "Off Market"),
            ("Disclosure2", "TypeOfInstrument", "Equity"),
            ("Disclosure2", bit.PIT_QTY, "500"), ("Disclosure2", bit.PIT_VALUE, "24000"),
            ("Disclosure2", bit.PIT_BEFORE_PCT, "0.02"), ("Disclosure2", bit.PIT_AFTER_PCT, "0.01"),
            ("Disclosure2", bit.PIT_FROM, "2026-05-09"), ("Disclosure2", bit.PIT_TO, "2026-05-09"),
            ("Disclosure2", bit.PIT_INTIM, "2026-05-09"),
            ("Disclosure3", "NameOfThePerson", "Carol"),
            ("Disclosure3", "CategoryOfPerson", "Designated Person"),
            ("Disclosure3", "TypeOfInstrument", "Derivative"),
            ("Disclosure3", "TypeOfContract", "Options"),
            ("Disclosure3", "NumberOfUnits", "1500"),
            ("Disclosure3", "NotionalValue", "491250"),
            ("Disclosure3", "BuyNumberOfUnits", "1500"),
            ("Disclosure3", bit.PIT_FROM, "2026-05-08"), ("Disclosure3", bit.PIT_TO, "2026-05-08"),
            ("Disclosure3", bit.PIT_INTIM, "2026-05-09"),
        ]
        self.conn.executemany(
            "INSERT INTO mkt_nse_pit_xbrl_facts VALUES ('01052026_IT_WebXMLFile_100.xml',?,?,1,?,NULL)",
            [(context, concept, value) for context, concept, value in facts])
        summary = self.build()
        rows = self.v2()

        self.assertEqual(len(rows), 3)  # one row per non-MainI context
        by_person = {row["person_name"]: row for row in rows}
        alice = by_person["Alice"]
        self.assertEqual(alice["source"], "nse_pit_xbrl")
        self.assertEqual(alice["source_key"],
                         "nse_pit_xbrl:01052026_IT_WebXMLFile_100.xml:Disclosure1")
        self.assertEqual(alice["symbol"], "CCC")
        self.assertEqual(alice["isin"], "INE000C01010")
        self.assertEqual(alice["company"], "Cee Ltd")
        self.assertEqual(alice["transaction_type"], "BUY")
        self.assertEqual(alice["mode"], "MARKET_PURCHASE")
        self.assertEqual(alice["qty"], 1000.0)
        self.assertEqual(alice["value_inr"], 50000.0)
        self.assertEqual(alice["before_pct"], 1.5)   # XBRL "pure" fraction -> percent
        self.assertEqual(alice["after_pct"], 1.6)
        self.assertEqual(alice["trade_from"], "2026-05-08")
        self.assertEqual(alice["intimation_date"], "2026-05-09")
        self.assertEqual(alice["known_at"], "2026-05-10 10:00:00")
        self.assertEqual(by_person["Bob"]["transaction_type"], "SELL")
        self.assertEqual(by_person["Bob"]["mode"], "OFF_MARKET")
        carol = by_person["Carol"]
        self.assertEqual(carol["transaction_type"], "BUY")
        self.assertEqual(carol["mode"], "DERIVATIVE_CONTRACT")
        self.assertEqual(carol["qty"], 1500.0)
        self.assertEqual(carol["value_inr"], 491250.0)
        self.assertIn("Derivative", carol["security_type"])
        self.assertEqual(summary["audit"]["trade_contexts"], 2)
        self.assertEqual(summary["audit"]["contract_contexts"], 1)

    def test_revision_supersedes_original(self):
        self.history([("NSE", "CCC", "INE000C01010", "2019-01-01", "2026-12-31")])
        self.conn.executemany(
            "INSERT INTO mkt_nse_pit_filings VALUES (?,?,?,?,?,?,?,?,?,?)",
            [("20", "equities", "CCC", "Cee Ltd", "Original", "2026-06-01 10:00",
              "2026-06-01 10:00", None, None, "https://x/A.xml"),
             ("21", "equities", "CCC", "Cee Ltd", "Revision", "2026-06-05 10:00",
              "2026-06-05 10:00", "qty corrected", None, "https://x/B.xml")])
        facts = [
            ("A.xml", "MainI", "Symbol", "CCC"), ("A.xml", "MainI", "ISINCode", "INE000C01010"),
            ("A.xml", "Disclosure1", bit.PIT_TXN, "Buy"),
            ("A.xml", "Disclosure1", "NameOfThePerson", "Alice"),
            ("A.xml", "Disclosure1", bit.PIT_QTY, "100"),
            ("A.xml", "Disclosure1", bit.PIT_FROM, "2026-05-28"),
            ("A.xml", "Disclosure1", bit.PIT_TO, "2026-05-28"),
            ("B.xml", "MainI", "Symbol", "CCC"), ("B.xml", "MainI", "ISINCode", "INE000C01010"),
            ("B.xml", "MainI", "RevisedFilling", "true"),
            ("B.xml", "Disclosure1", bit.PIT_TXN, "Buy"),
            ("B.xml", "Disclosure1", "NameOfThePerson", "Alice"),
            ("B.xml", "Disclosure1", bit.PIT_QTY, "150"),
            ("B.xml", "Disclosure1", bit.PIT_FROM, "2026-05-28"),
            ("B.xml", "Disclosure1", bit.PIT_TO, "2026-05-28"),
        ]
        self.conn.executemany(
            "INSERT INTO mkt_nse_pit_xbrl_facts VALUES (?,?,?,1,?,NULL)", facts)
        summary = self.build()
        rows = self.v2()
        original = next(r for r in rows if r["source_key"].endswith("A.xml:Disclosure1"))
        revision = next(r for r in rows if r["source_key"].endswith("B.xml:Disclosure1"))
        self.assertEqual(original["is_superseded"], 1)
        self.assertEqual(revision["is_revision"], 1)
        self.assertIn(original["source_key"], revision["supersedes"])
        self.assertEqual(revision["qty"], 150.0)
        self.assertEqual(summary["audit"]["revision_filings"], 1)
        self.assertEqual(summary["audit"]["superseded_rows"], 1)

    def test_nse_bse_dedupe_keeps_nse_row(self):
        self.history([("NSE", "DDD", "INE000D01010", "2019-01-01", "2025-12-31")])
        self.conn.execute("INSERT INTO security_master VALUES ('INE000E01010', 'EEE')")
        self.conn.execute(
            "INSERT INTO mkt_nse_insider VALUES ('1','DDD','Test Ltd','Mr. Test Person',"
            "'Promoter','Equity Shares','Buy','Market Purchase',1000.0,50000.0,NULL,NULL,"
            "NULL,NULL,'1.5','1.6','2021-01-05','2021-01-05','2021-01-06','2021-01-06 18:00')")
        self.conn.executemany(
            "INSERT INTO mkt_bse_insider VALUES (?,?,?,?,?,?)",
            [bse_row("2021-01.csv", 1),
             bse_row("2021-02.csv", 1, isin="INE000E01010", **{bit.BSE_PERSON: "ONLY BSE",
                                                              bit.BSE_QTY: "50",
                                                              bit.BSE_VALUE: "2500",
                                                              bit.BSE_DATE: "2/1/2021 12:00:00 AM"})])
        summary = self.build()
        rows = self.v2()
        nse = [r for r in rows if r["source"] == "nse_legacy"]
        bse = [r for r in rows if r["source"] == "bse"]
        self.assertEqual(len(nse), 1)
        self.assertEqual(nse[0]["also_on"], "bse")
        self.assertEqual(len(bse), 1)  # only the BSE-only row survives
        self.assertEqual(bse[0]["person_name"], "ONLY BSE")
        self.assertEqual(bse[0]["symbol"], "EEE")  # filled from security_master by ISIN
        self.assertEqual(bse[0]["transaction_type"], "BUY")
        self.assertEqual(bse[0]["mode"], "MARKET")
        self.assertEqual(bse[0]["value_inr"], 2500.0)
        self.assertIsNone(bse[0]["known_at"])
        self.assertEqual(summary["audit"]["dedupe_matched"], 1)
        self.assertEqual(summary["audit"]["bse_rows_dropped"], 1)

    def test_dry_run_writes_nothing(self):
        self.history([("NSE", "DDD", "INE000D01010", "2019-01-01", "2025-12-31")])
        summary = bit.build(self.conn, dry_run=True)
        self.assertTrue(summary["dry_run"])
        tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("insider_trades_v2", tables)

    def test_rebuild_is_idempotent(self):
        self.history([("NSE", "DDD", "INE000D01010", "2019-01-01", "2025-12-31")])
        self.conn.execute(
            "INSERT INTO mkt_nse_insider VALUES ('1','DDD','Test Ltd','Mr. Test Person',"
            "'Promoter','Equity Shares','Buy','Market Purchase',1000.0,50000.0,NULL,NULL,"
            "NULL,NULL,'1.5','1.6','2021-01-05','2021-01-05','2021-01-06','2021-01-06 18:00')")
        self.build()
        self.build()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM insider_trades_v2").fetchone()[0], 1)


class InsiderTradeRepositoryTests(unittest.TestCase):
    def setUp(self):
        # A file next to the test (not the system temp dir, which some CI sandboxes deny).
        self.db_path = (Path(__file__).resolve().parent /
                        f".insider_trades_{uuid.uuid4().hex}.db")
        self.db = DatabaseManager(self.db_path)
        self.repo = Repository(self.db)
        with self.db.session() as conn:
            conn.execute(bit.DDL)
            cols = bit.ROW_COLS
            self.rows = [
                self.row("nse_legacy:1", "AAA", "2026-05-08", "2026-05-10 10:00:00", 5000000.0),
                self.row("nse_legacy:2", "AAA", "2026-05-30", "2026-06-01 10:00:00", 7000000.0),
                self.row("bse:f:1", "AAA", "2026-05-09", None, 1000000.0, source="bse"),
                self.row("nse_legacy:3", "AAA", "2026-05-01", "2026-05-02 10:00:00", 100.0,
                         superseded=1),
            ]
            conn.executemany(
                f"INSERT INTO insider_trades_v2 ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})",
                [tuple(r[c] for c in cols) for r in self.rows])

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.db_path) + suffix).unlink(missing_ok=True)

    @staticmethod
    def row(source_key, symbol, trade_from, known_at, value_inr, source="nse_legacy", superseded=0):
        row = {c: None for c in bit.ROW_COLS}
        row.update({
            "source": source, "source_key": source_key, "symbol": symbol, "isin": "INE000D01010",
            "company": "Test Ltd", "person_name": "Test Person", "person_category": "Promoter",
            "transaction_type": "BUY", "mode": "MARKET_PURCHASE", "security_type": "Equity",
            "qty": 1000.0, "value_inr": value_inr, "before_pct": 1.0, "after_pct": 1.5,
            "trade_from": trade_from, "trade_to": trade_from, "intimation_date": trade_from,
            "known_at": known_at, "is_revision": 0, "supersedes": None,
            "is_superseded": superseded, "also_on": None,
        })
        return row

    def test_as_of_filter_uses_known_at_and_legacy_aliases(self):
        df = self.repo.get_recent_insider_trades(days=3650, as_of_date="2026-05-31")
        self.assertEqual(list(df["id"]), ["nse_legacy:1"])  # future, BSE-only and superseded gone
        for legacy in ("id", "symbol", "isin", "acquirer_name", "category_of_person",
                       "transaction_type", "num_shares", "value_inr_lacs",
                       "mode_of_acquisition", "acquisition_date", "intimation_date"):
            self.assertIn(legacy, df.columns)
        self.assertEqual(df.iloc[0]["acquirer_name"], "Test Person")
        self.assertEqual(df.iloc[0]["value_inr_lacs"], 50.0)
        self.assertEqual(df.iloc[0]["mode_of_acquisition"], "MARKET_PURCHASE")

    def test_no_as_of_includes_bse_rows_but_never_superseded(self):
        df = self.repo.get_recent_insider_trades(days=3650)
        self.assertEqual(sorted(df["id"]), ["bse:f:1", "nse_legacy:1", "nse_legacy:2"])

    def test_symbol_filter(self):
        df = self.repo.get_recent_insider_trades(symbol="AAA", days=3650, as_of_date="2026-05-31")
        self.assertEqual(list(df["id"]), ["nse_legacy:1"])
        empty = self.repo.get_recent_insider_trades(symbol="ZZZ", days=3650)
        self.assertTrue(empty.empty)


if __name__ == "__main__":
    unittest.main()
