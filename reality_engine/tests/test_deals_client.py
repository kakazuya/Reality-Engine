"""Tests for DealsClient (Tier-0 feed). Temp DB, zero network."""
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion.deals_client import DealsClient, make_deal_id


CSV_TEXT = """Date,Symbol,Security Name,Client Name,Buy / Sell,Quantity Traded,Trade Price / Wtd.Avg.Price,Remarks
18-Sep-2026,RELIANCE,Reliance Industries Ltd,HDFC MUTUAL FUND - GROWTH OPTION,BUY,125000,2985.40,-
18-Sep-2026,TCS,Tata Consultancy Services Ltd,RETAIL INVESTOR XYZ,S,5000,4120.10,-
19-Sep-2026,INFY,Infosys Ltd,GOVERNMENT OF SINGAPORE,B,200000,1875.00,-
19-Sep-2026,BADCO,Bad Co Ltd,Some Client,X,notanumber,100,-
"""


class _FakeResp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text


class _FakeSession:
    def __init__(self, text="", status=200, fail=False):
        self.text = text
        self.status = status
        self.fail = fail
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if self.fail:
            raise ConnectionError("boom")
        return _FakeResp(self.status, self.text)


def _mk_repo(td):
    mgr = DatabaseManager(db_path=Path(td) / "t.db")
    return Repository(manager=mgr), mgr


class TestNormalize(unittest.TestCase):
    def test_shapes_skip_counts_and_marquee(self):
        records, stats = DealsClient.normalize(CSV_TEXT, "BULK")
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["skipped_malformed"], 1)
        self.assertEqual(len(records), 3)
        expected_keys = {
            "id", "deal_date", "symbol", "client_name", "deal_type",
            "buy_sell", "quantity", "trade_price", "is_marquee_institution",
        }
        for rec in records:
            self.assertEqual(set(rec.keys()), expected_keys)
            self.assertEqual(rec["deal_type"], "BULK")
            self.assertEqual(len(rec["id"]), 32)
        by_cli = {r["client_name"]: r for r in records}
        hdfc = by_cli["HDFC MUTUAL FUND - GROWTH OPTION"]
        self.assertEqual(hdfc["buy_sell"], "BUY")
        self.assertEqual(hdfc["quantity"], 125000)
        self.assertAlmostEqual(hdfc["trade_price"], 2985.40)
        self.assertEqual(hdfc["deal_date"], "2026-09-18")
        self.assertEqual(hdfc["is_marquee_institution"], 1)
        retail = by_cli["RETAIL INVESTOR XYZ"]
        self.assertEqual(retail["buy_sell"], "SELL")  # 'S' single-letter form
        self.assertEqual(retail["is_marquee_institution"], 0)
        gis = by_cli["GOVERNMENT OF SINGAPORE"]
        self.assertEqual(gis["buy_sell"], "BUY")
        self.assertEqual(gis["is_marquee_institution"], 1)

    def test_id_determinism(self):
        a = make_deal_id("2026-09-18", "RELIANCE", "HDFC MF", "BUY", 125000, 2985.4)
        b = make_deal_id("2026-09-18", "RELIANCE", "HDFC MF", "BUY", 125000, 2985.4)
        c = make_deal_id("2026-09-18", "RELIANCE", "HDFC MF", "SELL", 125000, 2985.4)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        recs1, _ = DealsClient.normalize(CSV_TEXT, "BULK")
        recs2, _ = DealsClient.normalize(CSV_TEXT, "BULK")
        self.assertEqual([r["id"] for r in recs1], [r["id"] for r in recs2])

    def test_block_kind_and_duplicates(self):
        recs, stats = DealsClient.normalize(CSV_TEXT, "BLOCK")
        self.assertTrue(all(r["deal_type"] == "BLOCK" for r in recs))
        rows = DealsClient.parse_csv(CSV_TEXT)
        recs2, stats2 = DealsClient.normalize(rows + rows, "BULK")
        self.assertEqual(stats2["duplicates"], 3)
        self.assertEqual(len(recs2), 3)

    def test_upsert_round_trip(self):
        records, _ = DealsClient.normalize(CSV_TEXT, "BULK")
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            n = DealsClient.persist(records, repo=repo)
            self.assertGreaterEqual(n, 0)
            with mgr.session() as conn:
                got = conn.execute(
                    "SELECT symbol, deal_type, buy_sell, quantity, is_marquee_institution"
                    " FROM bulk_block_deals ORDER BY symbol").fetchall()
                self.assertEqual(len(got), 3)
                # idempotent re-upsert: no new rows
                DealsClient.persist(records, repo=repo)
                cnt = conn.execute("SELECT COUNT(*) FROM bulk_block_deals").fetchone()[0]
                self.assertEqual(cnt, 3)


class TestFetchCsv(unittest.TestCase):
    def test_fetch_ok_with_fake_session(self):
        client = DealsClient(session=_FakeSession(text=CSV_TEXT), rate_limit_sec=0)
        text = client.fetch_csv("BULK")
        self.assertIn("HDFC MUTUAL FUND", text)
        self.assertTrue(any("bulk.csv" in u for u in client.session.calls))
        block_client = DealsClient(session=_FakeSession(text=CSV_TEXT), rate_limit_sec=0)
        block_client.fetch_csv("block")
        self.assertTrue(any("block.csv" in u for u in block_client.session.calls))

    def test_fetch_fail_closed(self):
        client = DealsClient(session=_FakeSession(fail=True), rate_limit_sec=0)
        self.assertEqual(client.fetch_csv("BULK"), "")
        bad = DealsClient(session=_FakeSession(text=CSV_TEXT, status=403), rate_limit_sec=0)
        self.assertEqual(bad.fetch_csv("BULK"), "")
        unknown = DealsClient(session=_FakeSession(text=CSV_TEXT), rate_limit_sec=0)
        self.assertEqual(unknown.fetch_csv("NOPE"), "")

    def test_fetch_normalize_end_to_end_fake(self):
        client = DealsClient(session=_FakeSession(text=CSV_TEXT), rate_limit_sec=0)
        records, stats = client.fetch_normalize("BULK")
        self.assertEqual(len(records), 3)
        self.assertEqual(stats["skipped_malformed"], 1)


if __name__ == "__main__":
    unittest.main()
