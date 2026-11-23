"""Offline checks for the pilot (b) build (reality_engine.pilot.build_b). No network.

The schema-match test builds every pilot table from the FINAL DDL in memory and compares
its columns and primary-key order with the DDL text itself. The PIT tests cover the rule
each table applies (end-of-day publication -> next session, the row's own session date,
notice effective dates, quarterly period windows). The built-file tests run only when
``.tmp/pilot_b/market_state_b.db`` exists and are skipped otherwise.
"""
import datetime as dt
import sqlite3
import unittest
from pathlib import Path

from reality_engine.pilot import build_b as b
from reality_engine.pilot import build_t1


class SchemaTest(unittest.TestCase):
    def setUp(self):
        self.text = b.SCHEMA_SQL.read_text(encoding="utf-8")

    def test_final_ddl_has_every_object_the_pilot_builds(self):
        names = {(dom, name) for dom, name, _ in b.schema_statements(self.text)}
        for dom, table in (("market_state", "index_list"),
                           ("market_state", "company_membership_pit"),
                           ("market_state", "series_meta"),
                           ("market_state", "series_observation"),
                           ("market_state", "commodity_price_daily"),
                           ("market_state", "fno_oi_daily"),
                           ("equity_intelligence", "mkt_nse_full_daily")):
            self.assertIn((dom, table), names, f"{dom}.{table}")

    def test_schema_match_every_table(self):
        """Column list and PK order of the built table == the final DDL, table by table."""
        market, bhav = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
        b.create_schema(market, "market_state", b.MARKET_KEEP, self.text)
        b.create_schema(bhav, "equity_intelligence", b.BHAVCOPY_KEEP, self.text)
        for con, domain, tables in (
                (market, "market_state", b.MARKET_KEEP),
                (bhav, "equity_intelligence", b.BHAVCOPY_KEEP)):
            for table in sorted(tables):
                kind = con.execute("SELECT type FROM sqlite_master WHERE name = ?",
                                   (table,)).fetchone()
                self.assertIsNotNone(kind, f"{domain}.{table} was not created")
                if kind[0] == "view":
                    continue
                cols, pk = b.expected_columns(self.text, domain, table)
                info = con.execute(f"PRAGMA table_info({table})").fetchall()
                self.assertEqual([(r[1], r[2].upper()) for r in info], cols, table)
                self.assertEqual([r[1] for r in info if r[5]], pk, table)
        market.close()
        bhav.close()

    def test_commodity_view_resolves_to_the_series_rows(self):
        con = sqlite3.connect(":memory:")
        b.create_schema(con, "market_state",
                        {"series_meta", "series_observation", "commodity_price_daily"},
                        self.text)
        con.execute("INSERT INTO series_meta (series_code, display_name, kind, source, unit, "
                    "cadence) VALUES ('wb_gold','Gold','commodity','worldbank','$/oz','monthly')")
        con.execute("INSERT INTO series_observation (series_code, dim_id, kind, period_start, "
                    "value, unit, source, known_at) VALUES ('wb_gold','wb_gold','commodity',"
                    "'2026-09-30',4100.0,'$/oz','worldbank','2026-10-02T23:59:59')")
        self.assertEqual(con.execute("SELECT commodity, close, known_at FROM "
                                     "commodity_price_daily").fetchone(),
                         ("wb_gold", 4100.0, "2026-10-02T23:59:59"))
        con.close()

    def test_dequalify_leaves_no_cross_domain_names(self):
        for _dom, _name, stmt in b.schema_statements(self.text):
            self.assertNotRegex(b.dequalify(stmt),
                                r"\b(market_state|metric_state|equity_intelligence)\.")


class PitTest(unittest.TestCase):
    """The 15:30 IST day-0 rule, one assertion per table's time key."""

    SESSIONS = ["2026-10-01", "2026-10-02", "2026-10-05"]

    def rule(self, stamp):
        return build_t1.day0(dt.datetime.fromisoformat(stamp), self.SESSIONS,
                             set(self.SESSIONS))

    def test_series_timestamp_is_end_of_day_never_the_crawl_date(self):
        self.assertEqual(b.series_known_at("2026-10-02"), "2026-10-02T23:59:59")
        with self.assertRaises(ValueError):
            b.series_known_at("")
        # an end-of-day publication is usable from the NEXT session under the 15:30 rule
        self.assertEqual(self.rule("2026-10-02T23:59:59"), ("2026-10-05", 1, 0))

    def test_bhavcopy_and_fno_rows_are_keyed_by_their_session(self):
        self.assertEqual(b.session_known_at("2026-10-01"), "2026-10-01T15:30:00")
        self.assertEqual(self.rule("2026-10-01T15:30:00"), ("2026-10-01", 0, 1))

    def test_fo_date_falls_back_to_both_archive_naming_schemes(self):
        self.assertEqual(b.fo_date_from_name(
            "BhavCopy_NSE_FO_0_0_0_20240708_F_0000.csv.zip"), "2024-07-08")
        self.assertEqual(b.fo_date_from_name("fo02MAR2021bhav.csv.zip"), "2021-03-02")
        self.assertIsNone(b.fo_date_from_name("_manifest.csv"))

    NEW_HEADER = ["TradDt", "BizDt", "Sgmt", "Src", "FinInstrmTp", "FinInstrmId", "ISIN",
                  "TckrSymb", "SctySrs", "XpryDt", "FininstrmActlXpryDt", "StrkPric",
                  "OptnTp", "FinInstrmNm", "OpnPric", "HghPric", "LwPric", "ClsPric",
                  "LastPric", "PrvsClsgPric", "UndrlygPric", "SttlmPric", "OpnIntrst",
                  "ChngInOpnIntrst", "TtlTradgVol", "TtlTrfVal", "TtlNbOfTxExctd"]
    OLD_HEADER = ["INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "OPEN",
                  "HIGH", "LOW", "CLOSE", "SETTLE_PR", "CONTRACTS", "VAL_INLAKH", "OPEN_INT",
                  "CHG_IN_OI", "TIMESTAMP"]

    def test_fo_normalize_new_format_takes_the_rows_own_date(self):
        row = ["2024-07-09", "2024-07-08", "FO", "NSE", "STO", "67522", "", "ABFRL", "",
               "2024-07-25", "2024-07-25", "250.00", "PE", "ABFRL24JUL250PE", "0.00", "0.00",
               "0.00", "0.15", "0.15", "0.15", "322.25", "0.10", "26000", "0", "0", "0.00", "0"]
        self.assertEqual(b.fo_format(self.NEW_HEADER), "new")
        self.assertEqual(b.fo_normalize("new", self.NEW_HEADER, row),
                         ("2024-07-08", "ABFRL", "2024-07-25", 250.0, "PE", 26000.0, 0.0,
                          0.0, 0.1, None))

    def test_fo_normalize_old_format_maps_futures_and_expiry(self):
        fut = ["FUTIDX", "BANKNIFTY", "25-Mar-2021", "0", "XX", "35460.05", "35754.8",
               "34983.05", "35454.85", "35454.85", "211862", "1872084.26", "1594025",
               "107425", "02-Mar-2021"]
        self.assertEqual(b.fo_format(self.OLD_HEADER), "old")
        self.assertEqual(b.fo_normalize("old", self.OLD_HEADER, fut),
                         ("2021-03-02", "BANKNIFTY", "2021-03-25", 0.0, "FUT", 1594025.0,
                          107425.0, 211862.0, 35454.85, None))
        bad = fut[:]
        bad[1] = ""                                  # no underlying: not a contract row
        self.assertIsNone(b.fo_normalize("old", self.OLD_HEADER, bad))

    def test_period_window_end_for_the_reclassification(self):
        cases = {"Q4FY26-Q1FY27": "2026-06-30", "FY27": "2027-03-31",
                 "FY22-FY26": "2026-03-31", "2024-2026": "2026-12-31",
                 "7-19 Oct 2026": "2026-10-19", "as of 17 September 2026": "2026-09-17",
                 "2026-07/2026-09": "2026-09-30", "15 Jul 2026": "2026-07-15",
                 "2026-09-30": "2026-09-30", "forward 2 years": None, "latest": None}
        for text, want in cases.items():
            self.assertEqual(b.period_end(text), want, text)

    def test_named_series_maps_the_question_and_admits_the_gap(self):
        self.assertEqual(b.named_series("OMCs: crude trend into Q1"), ["wb_crude_brent"])
        self.assertEqual(b.named_series("coal gasification scheme"), ["wb_coal_aus"])
        self.assertEqual(b.named_series("aluminium premium"), ["wb_aluminium"])
        self.assertEqual(b.named_series("how did the members react"), [])


class BuiltFileTest(unittest.TestCase):
    """Runs only after the pilot build wrote .tmp/pilot_b/market_state_b.db."""

    @classmethod
    def setUpClass(cls):
        if not b.MARKET_DB.exists():
            raise unittest.SkipTest("pilot (b) build not present")
        cls.con = b.readonly(b.MARKET_DB)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_every_built_table_has_rows(self):
        expected = {"index_list": 100, "company_membership_pit": 1000, "series_meta": 20,
                    "series_observation": 7000, "fno_oi_daily": 1,
                    "mkt_nse_full_daily": 1}
        for table, floor in expected.items():
            n = self.con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            self.assertGreaterEqual(n, floor, table)

    def test_series_pit_never_precedes_its_own_month(self):
        for known, start in self.con.execute(
                "SELECT known_at, period_start FROM series_observation "
                "LIMIT 200"):
            self.assertGreater(known, start)
            self.assertTrue(known.endswith("T23:59:59") or known[10] == "T")
        # series_meta carries the PIT note and a fetched_to inside the held window
        bad = self.con.execute(
            "SELECT COUNT(*) FROM series_meta WHERE pit_note IS NULL OR pit_note = '' "
            "OR fetched_to > '2026-09-30'").fetchone()[0]
        self.assertEqual(bad, 0)

    def test_membership_intervals_are_ordered_and_started(self):
        bad = self.con.execute(
            "SELECT COUNT(*) FROM company_membership_pit WHERE added_on < '2019-01-01' "
            "OR (removed_on IS NOT NULL AND removed_on <= added_on)").fetchone()[0]
        self.assertEqual(bad, 0)
        conf = {src: (lo, hi) for src, lo, hi in self.con.execute(
            "SELECT source, MIN(pit_conf), MAX(pit_conf) FROM company_membership_pit "
            "GROUP BY source").fetchall()}
        self.assertEqual(conf.get("nse_notice"), (1.0, 1.0))
        self.assertEqual(conf.get("snapshot_backcast"), (0.8, 0.8))
        # index_list is the PIT gate for membership: a snapshot-dated index must carry
        # its snapshot date, and every row a documented confidence
        bad = self.con.execute(
            "SELECT COUNT(*) FROM index_list WHERE pit_conf NOT IN (1.0, 0.9, 0.6) "
            "OR (coverage = 'snapshot' AND (snapshot_date IS NULL "
            "OR snapshot_date > '2026-09-30'))").fetchone()[0]
        self.assertEqual(bad, 0)

    def test_fno_and_bhavcopy_dates_are_held_sessions(self):
        lo, hi = self.con.execute("SELECT MIN(date), MAX(date) FROM fno_oi_daily").fetchone()
        self.assertGreaterEqual(lo, "2019-01-01")
        self.assertLessEqual(hi, "2026-10-29")
        lo, hi = self.con.execute(
            "SELECT MIN(date), MAX(date) FROM mkt_nse_full_daily").fetchone()
        self.assertEqual(lo, "2019-01-01")
        self.assertLessEqual(hi, "2026-10-19")


if __name__ == "__main__":
    unittest.main()
