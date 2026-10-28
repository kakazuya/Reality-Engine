"""Offline checks for the pilot T1 build (reality_engine.pilot.build_t1). No live DB, no network."""
import csv
import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

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

    def test_snapshot_member_excluded_by_an_unpaired_notice_stays_current(self):
        # the media page can miss a re-inclusion: a notice excludes a name the held
        # snapshot still lists, so the current stint restarts at the exclusion date
        out, anomalies = b.rebuild_membership(
            {("nifty100", "INEX")},
            [("nifty100", "INEX", "2021-03-31", "exclusion")])
        self.assertEqual(anomalies, 0)
        self.assertEqual(sorted(out), [
            ("INEX", "nifty100", "2019-01-01", "2021-03-31", "snapshot_backcast", 0.8),
            ("INEX", "nifty100", "2021-03-31", None, "snapshot_backcast", 0.8)])

    def test_two_exclusions_never_create_current_membership(self):
        out, _ = b.rebuild_membership(set(), [
            ("nifty100", "INEZ", "2021-03-31", "exclusion"),
            ("nifty100", "INEZ", "2023-03-31", "exclusion")])
        self.assertEqual(set(out), {
            ("INEZ", "nifty100", "2019-01-01", "2021-03-31", "snapshot_backcast", 0.8)})

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


class MultiIndexNoticeTest(unittest.TestCase):
    NOTICE = """Changes in indices

NIFTY 50
The following 1 company is being excluded from the index effective from September 30, 2026

1
Company A Ltd
SYMA

NIFTY BANK
The following 1 company is being included in the index effective from September 30, 2026

1
Company B Ltd
SYMB
"""

    def test_two_indices_in_one_notice(self):
        from reality_engine.scripts.fetch_index_history import parse_notice
        rows = parse_notice(self.NOTICE, "2026-08-10")
        self.assertEqual(
            [(r["index_name"], r["symbol"], r["change_type"], r["effective_date"])
             for r in rows],
            [("NIFTY 50", "SYMA", "exclusion", "2026-09-30"),
             ("NIFTY BANK", "SYMB", "inclusion", "2026-09-30")])

    def test_clean_index_name_drops_sentence_tails(self):
        cases = {
            "NIFTY 50": "NIFTY 50",
            "NIFTY50": "NIFTY 50",
            "NIFTY MIDCAP 150": "NIFTY MIDCAP 150",
            "NIFTY HIGH BETA 50 INDEX ON ACCOUNT OF QUARTERLY REVIEW": "NIFTY HIGH BETA 50",
            "NIFTY SME EMERGE INDEX. THE CHANGE SHALL BECOME EFFECTIVE": "NIFTY SME EMERGE",
            "NIFTY INDIA CORPORATE GROUP INDEX - TATA GROUP":
                "NIFTY INDIA CORPORATE GROUP INDEX - TATA GROUP",
            "NIFTY PSU BOND PLUS SDL APR 2027 50": None,
            "": None,
        }
        for raw, want in cases.items():
            self.assertEqual(b.clean_index_name(raw), want, raw)

    def test_index_meta_sizes(self):
        self.assertEqual(b.index_meta("NIFTY 500"), ("broad", 500))
        self.assertEqual(b.index_meta("NIFTY MIDCAP 100"), ("broad", 100))
        self.assertEqual(b.index_meta("NIFTY BANK"), ("sector", 12))
        self.assertEqual(b.index_meta("NIFTY ALPHA 50"), ("thematic", 50))
        self.assertEqual(b.index_meta("NIFTY 500 SHARIAH"), ("thematic", None))
        self.assertEqual(b.index_meta("NIFTY IPO"), ("thematic", None))

    def test_changes_only_never_claims_an_unknown_start(self):
        out, unbounded = b.rebuild_changes_only("niftybank", [
            ("niftybank", "INE1", "2021-03-31", "inclusion"),
            ("niftybank", "INE1", "2023-03-31", "exclusion"),
            ("niftybank", "INE2", "2024-03-31", "inclusion"),
            ("niftybank", "INE3", "2022-03-31", "exclusion"),
        ])
        self.assertEqual(sorted(out), [
            ("INE1", "niftybank", "2021-03-31", "2023-03-31", "nse_notice_partial", 0.6),
            ("INE2", "niftybank", "2024-03-31", None, "nse_notice_partial", 0.6),
        ])
        self.assertEqual(unbounded, 1)


class DerivedSnapshotTest(unittest.TestCase):
    FILES = {
        "nifty50": [("A", "INE000000001"), ("B", "INE000000002")],
        "nifty100": [("A", "INE000000001"), ("B", "INE000000002"),
                     ("C", "INE000000003"), ("D", "INE000000004"), ("E", "INE000000005")],
        "niftymidcap150": [("C", "INE000000003"), ("D", "INE000000004"),
                           ("E", "INE000000005")],
        "niftysmallcap250": [("F", "INE000000006"), ("G", "INE000000007")],
    }

    def test_csv_snapshots_and_exact_derivations(self):
        old_root, old_csv = b.RAW_ROOT, b.CSV_SNAPSHOTS
        # tempfile.mkdtemp sets a 0700 DACL the sandbox token cannot write through; a
        # plain mkdir under the workspace-owned .tmp/ is the repo's standard fixture root
        tmp = Path(__file__).resolve().parents[2] / ".tmp" / "tests" / "pilot_index"
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        raw, root = tmp / "raw", tmp / "raw" / "index_history"
        root.mkdir(parents=True)
        try:
            for slug, rows in self.FILES.items():
                with (root / f"current_{slug}.csv").open("w", encoding="utf-8",
                                                          newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["Company Name", "Industry", "Symbol", "Series", "ISIN Code"])
                    for sym, isin in rows:
                        w.writerow([f"{sym} Ltd", "x", sym, "EQ", isin])
                    if slug in ("nifty50", "niftysmallcap250"):   # exchange placeholder row
                        w.writerow(["Dummy HEG Ltd.", "x", "DUMMYHEG", "EQ",
                                    "DUM545A01024"])
            try:
                b.RAW_ROOT = raw
                b.CSV_SNAPSHOTS = {
                    slug: (f"NIFTY {slug.upper()}", f"current_{slug}.csv")
                    for slug in self.FILES}
                snapshots, meta, symbols = b.load_snapshots(lambda _: None)
            finally:
                b.RAW_ROOT, b.CSV_SNAPSHOTS = old_root, old_csv
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(len(snapshots["nifty50"]), 2)           # placeholder dropped
        self.assertEqual(snapshots["niftynext50"], {"INE000000003", "INE000000004",
                                                    "INE000000005"})
        self.assertEqual(snapshots["niftylargemidcap250"], snapshots["nifty100"])
        self.assertEqual(len(snapshots["niftymidsmallcap400"]), 5)
        self.assertEqual(meta["niftynext50"][1], "derived")
        self.assertEqual(symbols["nifty50"]["A"], "INE000000001")


class ShareCountTest(unittest.TestCase):
    def test_action_ratio(self):
        cases = [
            ("BONUS", "Bonus 1:1", None, 2.0),
            ("BONUS", "Bonus 2:5", None, 1.4),
            ("BONUS", "Bonus 13:10", None, 2.3),
            ("SPLIT", "Face Value Split (Sub-Division) - From Rs 10/- Per Share "
                      "To Re 1/- Per Share", 1.0, 10.0),
            (None, "Stock Split From Rs 5 To Rs 2", None, 2.5),
            ("BONUS", "Scheme Of Arrangement - Bonus Ncrps 4:1", None, None),
            ("DIVIDEND", "Dividend - Rs 5 Per Share", None, None),
            ("SPLIT", "Face Value Split - From Rs 2 To Rs 2", 2.0, None),
        ]
        for typ, subject, fv, want in cases:
            self.assertEqual(b.action_ratio(typ, subject, fv), want, subject)

    def test_share_steps_pit_and_backcast(self):
        anchors = [("2019-03-31", "2019-07-01", 1000, "ar_shareholding")]
        actions = [("2019-05-01", 2.0), ("2019-09-19", 2.0)]
        steps = b.share_steps(anchors, actions, "2020-12-31")
        self.assertEqual(steps, [
            # before the first known count: backcast, low confidence
            ("2019-01-01", 1000, "action_adjusted", 0.6),
            ("2019-03-31", 1000, "action_adjusted", 0.6),
            # the balance date precedes the filing date, and the split is applied
            ("2019-05-01", 2000, "action_adjusted", 0.6),
            ("2019-07-01", 2000, "action_adjusted", 0.9),
            ("2019-09-19", 4000, "action_adjusted", 0.9),
        ])

    def test_share_steps_direct_fact_needs_no_adjustment(self):
        steps = b.share_steps([("2020-03-31", "2020-07-01", 5000, "xbrl_paidup")], [],
                              "2021-03-31")
        self.assertIn(("2020-07-01", 5000, "xbrl_paidup", 1.0), steps)
        self.assertIn(("2020-03-31", 5000, "action_adjusted", 0.6), steps)


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
