"""Hermetic H02 tests. Never open the real snapshot."""
import json
import math
import random
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from reality_engine.harness.cards.h02_deals import (
    M1_EXCLUDE, M1_PATTERN, _dedupe_frame, aggregate_events, broker_prop_mask,
    exclude_promoters, load_deals, marquee_mask, normalize_client, pit_indices,
    select_m2, shuffle_dates_within_stock_year,
)
from reality_engine.harness.cards.h02_combine import (
    cluster_diff, combined_entry, tercile_labels, window_mask, zscore,
)


class MarqueeTests(unittest.TestCase):
    def test_declared_tokens_and_case(self):
        names = ["SBI MUTUAL FUND", "ABC MF", "XYZ AMC", "GIC PRIVATE LIMITED",
                 "CANADA PENSION PLAN", "THE CHINKERPOO FAMILY TRUST",
                 "GOVERNMENT OF SINGAPORE", "NORGES BANK", "ABU DHABI INVESTMENT AUTHORITY"]
        self.assertTrue(all(marquee_mask(names)))

    def test_declared_exclusions_win(self):
        names = ["XYZ SHARE BROKING PRIVATE LIMITED", "ABC SECURITIES PRIVATE LIMITED",
                 "STOCK BROKING FUND", "COMMODITIES TRUST"]
        self.assertFalse(any(marquee_mask(names)))

    def test_does_not_match_mfg_or_plain_names(self):
        self.assertFalse(any(marquee_mask(["MFG LIMITED", "ALPHA LEON ENTERPRISES LLP"])))
        self.assertTrue(broker_prop_mask(["A SHARE BROKING LTD"]).iloc[0])

    def test_normalize_client(self):
        self.assertEqual(normalize_client("  Alpha   Leon (LLP) "), "ALPHA LEON LLP")
        self.assertEqual(normalize_client(None), "")


class PitIndexTests(unittest.TestCase):
    def test_signal_is_deal_session_and_entry_is_strictly_next(self):
        days = np.array(["2021-01-04", "2021-01-05", "2021-01-06"], dtype="datetime64[D]")
        signal, entry = pit_indices(days, ["2021-01-04"])
        self.assertEqual(int(signal[0]), 0)
        self.assertEqual(int(entry[0]), 1)
        signal, entry = pit_indices(days, ["2021-01-03"])
        self.assertEqual(int(signal[0]), -1)
        self.assertEqual(int(entry[0]), 0)
        signal, entry = pit_indices(days, ["2021-01-06"])
        self.assertEqual(int(signal[0]), 2)
        self.assertEqual(int(entry[0]), 3)

    def test_shuffle_keeps_stock_year_identity(self):
        dates = np.array(["2021-01-04", "2021-03-05", "2022-02-07", "2022-09-09"],
                         dtype="datetime64[D]")
        issuers = np.array(["A", "A", "A", "B"])
        shuffled = shuffle_dates_within_stock_year(dates, issuers, np.random.default_rng(3))
        self.assertEqual(sorted(shuffled[:3].tolist()), sorted(dates[:3].tolist()))
        self.assertEqual(shuffled[3], dates[3])
        self.assertEqual(shuffled.astype("datetime64[Y]").astype(int).tolist(),
                         dates.astype("datetime64[Y]").astype(int).tolist())


class DedupeTests(unittest.TestCase):
    def frame(self):
        rows = [
            # cross-exchange duplicate
            dict(date="2021-01-04", deal_type="BULK", exch="NSE", client_n="A", side="BUY",
                 qty=100.0, px=10.0, issuer="I"),
            dict(date="2021-01-04", deal_type="BULK", exch="BSE", client_n="A", side="BUY",
                 qty=100.0, px=10.0, issuer="I"),
            # BULK/BLOCK duplicate within NSE
            dict(date="2021-01-05", deal_type="BULK", exch="NSE", client_n="A", side="BUY",
                 qty=200.0, px=10.0, issuer="I"),
            dict(date="2021-01-05", deal_type="BLOCK", exch="NSE", client_n="A", side="BUY",
                 qty=200.0, px=10.0, issuer="I"),
            # same exchange, same type: retained as possible separate trades
            dict(date="2021-01-06", deal_type="BULK", exch="NSE", client_n="A", side="BUY",
                 qty=300.0, px=10.0, issuer="I"),
            dict(date="2021-01-06", deal_type="BULK", exch="NSE", client_n="A", side="BUY",
                 qty=300.0, px=10.0, issuer="I"),
        ]
        frame = pd.DataFrame(rows)
        frame["value"] = frame["qty"] * frame["px"]
        return frame

    def test_one_for_one_dedupe(self):
        out, audit = _dedupe_frame(self.frame())
        self.assertEqual(audit["cross_exchange_duplicates_removed"], 1)
        self.assertEqual(audit["bulk_block_duplicates_removed"], 1)
        self.assertEqual(len(out), 4)
        self.assertEqual(len(out[(out.date == "2021-01-06")]), 2)

    def test_same_key_different_issuer_is_not_deduped(self):
        frame = self.frame().iloc[[0]].copy()
        second = frame.copy()
        second["issuer"] = "J"
        second["exch"] = "BSE"
        out, audit = _dedupe_frame(pd.concat([frame, second], ignore_index=True))
        self.assertEqual(audit["cross_exchange_duplicates_removed"], 0)
        self.assertEqual(len(out), 2)


class EventTests(unittest.TestCase):
    def test_net_buy_threshold_and_vwap(self):
        frame = pd.DataFrame([
            dict(issuer="I", date="2021-01-04", side="BUY", qty=100.0, px=100.0,
                 value=10_000.0, client_name="A"),
            dict(issuer="I", date="2021-01-04", side="SELL", qty=20.0, px=100.0,
                 value=2_000.0, client_name="B"),
            dict(issuer="J", date="2021-01-04", side="BUY", qty=50.0, px=100.0,
                 value=5_000.0, client_name="A"),
        ])
        events = aggregate_events(frame)
        self.assertEqual(len(events), 0)
        frame.loc[0, "qty"] = 200000.0
        frame.loc[0, "value"] = 20_000_000.0
        events = aggregate_events(frame)
        self.assertEqual(len(events), 1)
        self.assertEqual(events.iloc[0]["issuer"], "I")
        self.assertAlmostEqual(events.iloc[0]["net_value"], 19_998_000.0)
        self.assertAlmostEqual(events.iloc[0]["buy_vwap"], 100.0)

    def test_sell_only_is_not_a_buy_event(self):
        frame = pd.DataFrame([dict(issuer="I", date="2021-01-04", side="SELL", qty=200000.0,
                                   px=100.0, value=20_000_000.0, client_name="A")])
        self.assertEqual(len(aggregate_events(frame)), 0)


class PromoterTests(unittest.TestCase):
    def test_company_specific_exclusion_and_token(self):
        frame = pd.DataFrame([
            dict(issuer="I", client_n="INSIDER PERSON", client_name="Insider Person", value=1.0),
            dict(issuer="J", client_n="INSIDER PERSON", client_name="Insider Person", value=1.0),
            dict(issuer="I", client_n="XYZ PROMOTER TRUST", client_name="XYZ Promoter Trust", value=1.0),
            dict(issuer="I", client_n="SBI MUTUAL FUND", client_name="SBI Mutual Fund", value=1.0),
        ])
        pairs = pd.DataFrame([dict(issuer="I", n="INSIDER PERSON")])
        out, excluded = exclude_promoters(frame, pairs)
        self.assertEqual(excluded, 2)
        self.assertEqual(out["issuer"].tolist(), ["J", "I"])
        self.assertEqual(out["client_n"].tolist(), ["INSIDER PERSON", "SBI MUTUAL FUND"])


class M2Tests(unittest.TestCase):
    def test_top_20_2021_only_and_broker_exclusion(self):
        rows = []
        for i in range(25):
            for d in range(1, i + 1):
                rows.append(dict(client_n=f"CLIENT{i:02d}", client_name=f"Client {i:02d}",
                                 date=f"2021-{1 + (d - 1) // 28:02d}-{1 + (d - 1) % 28:02d}",
                                 value=1.0))
        rows.append(dict(client_n="BROKER SHARE BROKING", client_name="Broker Share Broking",
                         date="2021-01-01", value=1.0))
        rows.append(dict(client_n="LATE CLIENT", client_name="Late Client",
                         date="2022-01-01", value=1.0))
        frame = pd.DataFrame(rows)
        selected, names = select_m2(frame)
        self.assertEqual(len(selected), 20)
        self.assertNotIn("BROKER SHARE BROKING", names)
        self.assertNotIn("LATE CLIENT", names)
        self.assertIn("CLIENT24", names)
        self.assertNotIn("CLIENT04", names)


class CombinationTests(unittest.TestCase):
    def test_window_is_inclusive_and_rejects_post_entry(self):
        self.assertTrue(window_mask(100, 80))
        self.assertTrue(window_mask(100, 105))
        self.assertFalse(window_mask(100, 79))
        self.assertFalse(window_mask(100, 106))

    def test_entry_is_later_of_the_two(self):
        self.assertEqual(combined_entry(10, 12), 12)
        self.assertEqual(combined_entry(10, 8), 10)

    def test_terciles_equal_count(self):
        labels = tercile_labels(np.arange(9))
        self.assertEqual([int(np.sum(labels == i)) for i in range(3)], [3, 3, 3])

    def test_zscore_constant_is_zero(self):
        self.assertTrue(np.all(zscore([2.0, 2.0, 2.0]) == 0))

    def test_cluster_diff_detects_difference(self):
        from reality_engine.harness.stats import student_p
        days = np.array([date(2021, m, 1) for m in range(1, 13)])
        a = np.array([0.10] * 12)
        b = np.array([0.00] * 12)
        result = cluster_diff(a, np.arange(12), b, np.arange(12), days, student_p)
        self.assertAlmostEqual(result["diff"], 0.10)
        self.assertLess(result["p"], 0.05)


class LoadDealsFixtureTests(unittest.TestCase):
    """Temporary DuckDB fixture; the real snapshot is never opened."""

    def setUp(self):
        import uuid
        self.path = (Path(__file__).resolve().parent /
                     f".h02_fixture_{uuid.uuid4().hex}.duckdb")
        import duckdb
        con = duckdb.connect(str(self.path))
        con.execute("CREATE TABLE security_master(isin VARCHAR,issuer VARCHAR,name VARCHAR,"
                    "nse_symbol VARCHAR,bse_code VARCHAR,first_trade VARCHAR,last_trade VARCHAR)")
        con.execute("CREATE TABLE symbol_isin_history(exchange VARCHAR,symbol VARCHAR,isin VARCHAR,"
                    "first_date VARCHAR,last_date VARCHAR,n_days BIGINT)")
        con.execute("CREATE TABLE nse_deals(date VARCHAR,deal_type VARCHAR,symbol VARCHAR,"
                    "client_name VARCHAR,buy_sell VARCHAR,quantity BIGINT,price DOUBLE)")
        con.execute("CREATE TABLE bse_deals(date VARCHAR,deal_type VARCHAR,sc_code VARCHAR,"
                    "client_name VARCHAR,buy_sell VARCHAR,quantity DOUBLE,price DOUBLE)")
        con.execute("CREATE TABLE nse_insider(symbol VARCHAR,acquirer_name VARCHAR,"
                    "person_category VARCHAR,disseminated_at VARCHAR)")
        con.execute("CREATE TABLE bse_insider(isin VARCHAR,raw_json VARCHAR)")
        con.executemany("INSERT INTO security_master VALUES (?,?,?,?,?,?,?)", [
            ("INE000A01010", "ISS_A", "Alpha Ltd", "AAA", "500001", "2021-01-01", "2025-12-31"),
            ("INE000B01010", "ISS_B", "Beta Ltd", "BBB", "500002", "2023-01-01", "2025-12-31"),
            ("INE000C01010", "ISS_C", "Gamma Ltd", "CCC", "500003", "2021-01-01", "2025-12-31"),
        ])
        con.executemany("INSERT INTO symbol_isin_history VALUES (?,?,?,?,?,?)", [
            ("NSE", "AAA", "INE000A01010", "2021-01-01", "2022-12-31", 500),
            ("NSE", "AAA", "INE000B01010", "2023-01-01", "2025-12-31", 500),
            ("NSE", "CCC", "INE000C01010", "2021-01-01", "2025-12-31", 1000),
        ])
        con.executemany("INSERT INTO nse_deals VALUES (?,?,?,?,?,?,?)", [
            ("2021-01-04", "BULK", "AAA", "SBI MUTUAL FUND", "BUY", 200000, 100.0),
            ("2021-01-05", "BULK", "AAA", "SBI MUTUAL FUND", "BUY", 200000, 100.0),
            ("2021-01-05", "BLOCK", "AAA", "SBI MUTUAL FUND", "BUY", 200000, 100.0),
            ("2021-01-06", "BULK", "AAA", "INSIDER PERSON", "BUY", 500000, 100.0),
            ("2021-01-07", "BULK", "CCC", "INSIDER PERSON", "BUY", 500000, 100.0),
            ("2021-01-07", "BULK", "CCC", "SBI MUTUAL FUND", "BUY", 500000, 100.0),
            ("2023-01-04", "BULK", "AAA", "SBI MUTUAL FUND", "BUY", 300000, 100.0),
        ])
        con.executemany("INSERT INTO bse_deals VALUES (?,?,?,?,?,?,?)", [
            ("2021-01-04", "BULK", "500001", "SBI MUTUAL FUND", "BUY", 200000, 100.0),
            ("2021-01-08", "BULK", "500001", "BSE PROMOTER", "BUY", 500000, 100.0),
        ])
        con.execute("INSERT INTO nse_insider VALUES ('AAA','Insider Person','Promoters','2021-01-01')")
        con.execute("INSERT INTO bse_insider VALUES ('INE000A01010',?)",
                    [json.dumps({"Name(s) of the promoter and/or persons in promoter group":
                                 "BSE PROMOTER"})])
        con.close()

    def tearDown(self):
        for suffix in ("", ".wal"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                p.unlink(missing_ok=True)

    def test_mapping_dedupe_and_promoter_exclusion(self):
        data = load_deals(self.path)
        self.assertEqual(data.audit["cross_exchange_duplicates_removed"], 1)
        self.assertEqual(data.audit["bulk_block_duplicates_removed"], 1)
        # 2023 AAA is mapped through the date-valid ISIN history to ISS_B.
        self.assertIn("ISS_B", set(data.clean["issuer"]))
        self.assertNotIn("INSIDER PERSON",
                         set(data.clean.loc[data.clean.issuer == "ISS_A", "client_n"]))
        self.assertIn("INSIDER PERSON",
                      set(data.clean.loc[data.clean.issuer == "ISS_C", "client_n"]))
        events = data.events("M1")
        keys = set(zip(events["issuer"], events["date"]))
        self.assertIn(("ISS_A", "2021-01-04"), keys)
        self.assertIn(("ISS_A", "2021-01-05"), keys)
        self.assertIn(("ISS_B", "2023-01-04"), keys)
        self.assertIn(("ISS_C", "2021-01-07"), keys)
        # Duplicate removal means the 2021-01-04 net is Rs 2 crore, not 4.
        row = events[(events.issuer == "ISS_A") & (events.date == "2021-01-04")].iloc[0]
        self.assertAlmostEqual(row["net_value"], 20_000_000.0)


if __name__ == "__main__":
    unittest.main()
