"""Offline checks for the pilot T1 build (reality_engine.pilot.build_t1). No live DB, no network."""
import datetime as dt
import sqlite3
import unittest

from reality_engine.pilot import build_t1 as b


class SchemaTest(unittest.TestCase):
    def test_design_file_parses_every_t1_object(self):
        stmts = b.schema_statements(b.SCHEMA_SQL.read_text(encoding="utf-8"))
        names = {n for n, _ in stmts}
        for obj in ("company_state_daily", "event_day0", "event_leakage_window",
                    "company_membership_pit", "xbrl_concept_map", "company_metric_series",
                    "company_segment_pnl", "company_working_capital",
                    "company_interest_cover", "ix_csd_date_bucket", "mcap_bucket_interval",
                    "price_band_daily"):
            self.assertIn(obj, names)

    def test_statements_are_complete(self):
        for name, stmt in b.schema_statements(b.SCHEMA_SQL.read_text(encoding="utf-8")):
            self.assertFalse(stmt.rstrip().endswith("("), name)
            self.assertEqual(stmt.count("("), stmt.count(")"), name)

    def test_create_schema_and_compat_views(self):
        con = sqlite3.connect(":memory:")
        made = b.create_schema(con, b.T1_MARKET)
        self.assertIn("company_state_daily", made)
        con.execute("INSERT INTO company_state_daily (isin, date, price_band, known_at) "
                    "VALUES ('INE040A01034', '2026-08-03', 5, '2026-08-03T15:30:00')")
        b.compatibility_views(con)
        row = con.execute("SELECT band, has_band FROM price_band "
                          "WHERE isin='INE040A01034'").fetchone()
        self.assertEqual(row, (5, 1))
        row = con.execute("SELECT valid_from, valid_to FROM index_membership_interval").fetchall()
        self.assertEqual(row, [])
        con.close()


class Day0Test(unittest.TestCase):
    SESSIONS = ["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06", "2024-06-07",
                "2024-06-10"]  # Mon-Fri then next Monday (weekend skipped)

    def setUp(self):
        self.set_ = set(self.SESSIONS)

    def rule(self, ts):
        return b.day0(dt.datetime.fromisoformat(ts), self.SESSIONS, self.set_)

    def test_before_close_is_same_session(self):
        self.assertEqual(self.rule("2024-06-04T10:00:00"), ("2024-06-04", 0, 1))

    def test_exactly_1530_is_still_same_session(self):
        self.assertEqual(self.rule("2024-06-04T15:30:00"), ("2024-06-04", 0, 1))

    def test_after_close_is_next_session(self):
        self.assertEqual(self.rule("2024-06-04T15:31:00"), ("2024-06-05", 1, 0))
        self.assertEqual(self.rule("2024-06-04T23:59:00"), ("2024-06-05", 1, 0))

    def test_friday_after_close_skips_the_weekend(self):
        self.assertEqual(self.rule("2024-06-07T18:00:00"), ("2024-06-10", 1, 0))

    def test_weekend_stamp_goes_to_next_session(self):
        self.assertEqual(self.rule("2024-06-08T09:00:00"), ("2024-06-10", 1, 0))

    def test_holiday_is_not_a_session(self):
        # 2024-06-05 is a holiday here: a stamp that morning is not tradable that day
        sessions = [d for d in self.SESSIONS if d != "2024-06-05"]
        self.assertEqual(b.day0(dt.datetime.fromisoformat("2024-06-05T10:00:00"),
                                sessions, set(sessions)), ("2024-06-06", 1, 0))

    def test_past_the_calendar_has_no_session(self):
        self.assertEqual(self.rule("2026-01-01T10:00:00"), (None, None, 0))


class MembershipTest(unittest.TestCase):
    def test_exclusion_backcasts_the_prior_interval(self):
        snapshot = {("nifty50", "INE1")}
        notices = [("nifty50", "INE1", "2021-03-31", "exclusion"),
                   ("nifty50", "INE1", "2021-09-30", "inclusion")]
        out, anomalies = b.rebuild_membership(snapshot, notices)
        self.assertEqual(anomalies, 0)
        self.assertEqual(sorted(out), [
            ("INE1", "nifty50", "2019-01-01", "2021-03-31", "snapshot_backcast", 0.8),
            ("INE1", "nifty50", "2021-09-30", None, "nse_notice", 1.0),
        ])

    def test_snapshot_member_without_notices(self):
        out, _ = b.rebuild_membership({("nifty50", "INEA")}, [])
        self.assertEqual(out, [("INEA", "nifty50", "2019-01-01", None,
                                "snapshot_backcast", 0.8)])

    def test_removed_before_the_snapshot(self):
        out, _ = b.rebuild_membership(set(), [("nifty50", "INEB", "2021-03-31", "exclusion")])
        self.assertEqual(out, [("INEB", "nifty50", "2019-01-01", "2021-03-31",
                                "snapshot_backcast", 0.8)])

    def test_inclusion_of_a_snapshot_member_starts_one_interval(self):
        snapshot = {("nifty50", "INEC")}
        notices = [("nifty50", "INEC", "2022-03-31", "inclusion")]
        out, anomalies = b.rebuild_membership(snapshot, notices)
        self.assertEqual(anomalies, 0)
        self.assertEqual(out, [("INEC", "nifty50", "2022-03-31", None, "nse_notice", 1.0)])
        # an inclusion with no membership on either side is contradictory data: counted, skipped
        out2, anomalies2 = b.rebuild_membership(
            set(), [("nifty50", "INED", "2022-03-31", "inclusion")])
        self.assertEqual((out2, anomalies2), ([], 1))


class TextRulesTest(unittest.TestCase):
    def test_ist_text_converts_utc_to_ist(self):
        self.assertEqual(b.ist_text(dt.datetime(2024, 6, 3, 10, 0)), "2024-06-03T15:30:00")
        self.assertEqual(b.ist_text(dt.datetime(2024, 6, 3, 20, 0)), "2024-06-04T01:30:00")
        self.assertEqual(b.ist_text("2024-06-03T10:00:00"), "2024-06-03T15:30:00")
        self.assertIsNone(b.ist_text(None))
        self.assertIsNone(b.ist_text("not a date"))

    def test_fy_end(self):
        self.assertEqual(b.fy_end("FY26"), "2026-03-31")
        self.assertEqual(b.fy_end("FY09"), "2009-03-31")
        self.assertIsNone(b.fy_end(""))

    def test_period_kind(self):
        self.assertEqual(b.period_kind_of("2024-04-01", "2024-06-30", "quarter"), "quarter")
        self.assertEqual(b.period_kind_of("2024-04-01", "2024-09-30", "year_to_date"), "half")
        self.assertEqual(b.period_kind_of("2023-04-01", "2024-03-31", "year_to_date"), "fy")
        self.assertEqual(b.period_kind_of(None, "2024-03-31", "instant"), "instant")
        self.assertIsNone(b.period_kind_of(None, None, "other"))

    def test_unit_to_crore(self):
        cases = {
            "Rs lakh": 0.01, "Rs Lakhs": 0.01, "INR lakhs": 0.01, "Lakhs": 0.01,
            "Rs crore": 1.0, "Rs. in Crore": 1.0, "Rs million": 0.1, "Rs in Lakhs": 0.01,
            "Rs thousand": 0.0001, "Rs bn": 100.0, "Rs": 1e-7, "%": None,
            "": None, "Nos": None,
        }
        for unit, want in cases.items():
            got = b.unit_to_crore(unit)
            if want is None:
                self.assertIsNone(got, unit)
            else:
                self.assertAlmostEqual(got, want, places=9, msg=unit)

    def test_parse_segment_item(self):
        cases = {
            "Real Estate segment revenue FY26": ("Real Estate", "revenue"),
            "Health Care Services segment revenue (FY25: 4,73,311.85)":
                ("Health Care Services", "revenue"),
            "Segment assets - Real Estate FY26": ("Real Estate", "segment_assets"),
            "Digital Marketing segment profit before tax and interest (FY25: 1)":
                ("Digital Marketing", "ebit"),
            "Automotive segment capex FY26": ("Automotive", "capex"),
            "Total sales/income from operations, net of inter-segment revenue (FY25: 5)": None,
            "No segment report required - single business segment": None,
            "Segment assets total FY26": None,
            "Company has a single operating segment": None,
        }
        for item, want in cases.items():
            self.assertEqual(b.parse_segment_item(item), want, item)


class BandParserTest(unittest.TestCase):
    CSV = ("Symbol,Series,Security Name,Band,Remarks\n"
           "RELIANCE,EQ,Reliance Industries,20,-\n"
           "ABC,BE,ABC Ltd,5,GSM Stage 1\n"
           "XYZ,EQ,XYZ Ltd,No Band,-\n")

    def test_parse_band_csv(self):
        from reality_engine.scripts.fetch_price_bands import parse_band_csv
        rows = parse_band_csv(self.CSV, "2024-06-03")
        self.assertEqual([(r["symbol"], r["band_pct"]) for r in rows],
                         [("RELIANCE", 20), ("ABC", 5), ("XYZ", None)])
        self.assertEqual(rows[1]["remarks"], "GSM Stage 1")


class UniverseTest(unittest.TestCase):
    def test_bank_universe_is_the_named_isins(self):
        universe = b.bank_universe()
        self.assertGreaterEqual(len(universe), 480)
        self.assertLessEqual(len(universe), 500)
        self.assertTrue(all(i.startswith("INE") and len(i) == 12 for i in universe))
        self.assertIn("INE040A01034", universe)      # HDFCBANK, PILOT_SPEC §1


if __name__ == "__main__":
    unittest.main()
