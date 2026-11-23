"""Tests for NewsAnnouncementsClient (Tier-0 feed). Temp DB, zero network."""
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion.news_announcements_client import NewsAnnouncementsClient, _to_iso_date

ROWS = [
    {
        "symbol": "RELIANCE",
        "sm_isin": "INE002A01018",
        "desc": "Outcome of the board meeting held on 19-Sep-2026",
        "sort_date": "19-Sep-2026 16:30",
        "attchmntFile": "https://www.nseindia.com/corporate/RELIANCE_19Sep2026.pdf",
        "seq_id": "AN001",
    },
    {
        # empty-attachment row: text-only announcement, pseudo-URL path
        "symbol": "TCS",
        "sm_isin": "INE467B01029",
        "desc": "Press release - strategic partnership",
        "sort_date": "18-Sep-2026",
        "attchmntFile": "",
        "seq_id": "AN002",
    },
    {
        # bad-isin row: no sm_isin and no map entry -> SKIPPED + counted
        "symbol": "FAKECO",
        "sm_isin": "",
        "desc": "Junk row",
        "sort_date": "18-Sep-2026",
        "attchmntFile": "https://example.com/junk.pdf",
        "seq_id": "AN003",
    },
]


class _FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {"data": []}

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload=None, status=200, fail=False):
        self.payload = payload
        self.status = status
        self.fail = fail
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if self.fail:
            raise ConnectionError("boom")
        if "corporate-announcements" in url:
            return _FakeResp(self.status, self.payload)
        return _FakeResp(200, {})


def _mk_repo(td):
    mgr = DatabaseManager(db_path=Path(td) / "t.db")
    return Repository(manager=mgr), mgr


class TestNormalize(unittest.TestCase):
    def test_shapes_and_skip_counts(self):
        records, stats = NewsAnnouncementsClient.normalize(ROWS)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["skipped_no_isin"], 1)
        self.assertEqual(stats["skipped_bad_date"], 0)
        self.assertEqual(len(records), 2)
        expected_keys = {
            "isin", "symbol", "doc_type", "title", "doc_date", "source_url",
            "source", "discovery_source", "local_file_path", "file_size_bytes",
            "sha256_hash", "is_processed",
        }
        for rec in records:
            self.assertEqual(set(rec.keys()), expected_keys)
            self.assertEqual(rec["doc_type"], "ANNOUNCEMENT")
            self.assertEqual(rec["source"], "nse_official")
            self.assertEqual(rec["discovery_source"], "nse_announcement_feed")
            self.assertEqual(rec["is_processed"], 0)
        by_sym = {r["symbol"]: r for r in records}
        self.assertEqual(by_sym["RELIANCE"]["isin"], "INE002A01018")
        self.assertEqual(by_sym["RELIANCE"]["doc_date"], "2026-09-19")
        self.assertEqual(
            by_sym["RELIANCE"]["source_url"],
            "https://www.nseindia.com/corporate/RELIANCE_19Sep2026.pdf",
        )
        # empty-attachment row gets a stable pseudo-URL keyed on seq_id
        self.assertIn("seq_id=AN002", by_sym["TCS"]["source_url"])
        self.assertEqual(by_sym["TCS"]["doc_date"], "2026-09-18")

    def test_symbol_map_fallback_and_bad_date(self):
        rows = [
            {"symbol": "INFY", "sm_isin": "", "desc": "Mapped isin",
             "sort_date": "17-Sep-2026", "attchmntFile": "https://x/y.pdf", "seq_id": "M1"},
            {"symbol": "INFY", "sm_isin": "INE009A01021", "desc": "Bad date",
             "sort_date": "not-a-date", "attchmntFile": "https://x/z.pdf", "seq_id": "M2"},
        ]
        records, stats = NewsAnnouncementsClient.normalize(
            rows, symbol_to_isin={"INFY": "INE009A01021"})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["isin"], "INE009A01021")
        self.assertEqual(stats["skipped_bad_date"], 1)
        self.assertEqual(stats["skipped_no_isin"], 0)

    def test_seq_id_dedup(self):
        dup = [dict(ROWS[0]), dict(ROWS[0])]
        records, stats = NewsAnnouncementsClient.normalize(dup)
        self.assertEqual(len(records), 1)
        self.assertEqual(stats["duplicates"], 1)

    def test_upsert_round_trip(self):
        records, _ = NewsAnnouncementsClient.normalize(ROWS)
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            repo.upsert_master_companies([
                {"isin": "INE002A01018", "nse_symbol": "RELIANCE",
                 "company_name": "Reliance", "is_active": 1},
                {"isin": "INE467B01029", "nse_symbol": "TCS",
                 "company_name": "TCS", "is_active": 1},
            ])
            n = NewsAnnouncementsClient.persist(records, repo=repo)
            self.assertGreaterEqual(n, 0)
            with mgr.session() as conn:
                got = conn.execute(
                    "SELECT isin, symbol, doc_type, title, doc_date, source, discovery_source"
                    " FROM corporate_documents ORDER BY symbol").fetchall()
                self.assertEqual(len(got), 2)
                self.assertEqual(got[0]["symbol"], "RELIANCE")
                self.assertEqual(got[0]["doc_type"], "ANNOUNCEMENT")
                self.assertEqual(got[0]["source"], "nse_official")
                # idempotent re-upsert: no new rows
                n2 = NewsAnnouncementsClient.persist(records, repo=repo)
                cnt = conn.execute("SELECT COUNT(*) FROM corporate_documents").fetchone()[0]
                self.assertEqual(cnt, 2)
                self.assertGreaterEqual(n2, 0)


class TestLiveSortDateFormat(unittest.TestCase):
    def test_iso_datetime_with_seconds(self):
        # Live NSE sort_date shape: '2026-09-18 23:59:24'.
        self.assertEqual(_to_iso_date("2026-09-18 23:59:24"), "2026-09-18")


class TestPersistFkFilter(unittest.TestCase):
    def test_drops_unknown_isin_single_write(self):
        import contextlib

        class _FakeConn:
            def __init__(self, known):
                self._known = known

            def execute(self, query):
                self._query = query
                return self

            def fetchall(self):
                return [(isin,) for isin in self._known]

        class _FakeRepo:
            def __init__(self, known):
                self._known = known
                self.written = None
                self.write_calls = 0
                self.db = self

            @contextlib.contextmanager
            def session(self):
                yield _FakeConn(self._known)

            def upsert_corporate_documents(self, records):
                self.write_calls += 1
                self.written = list(records)
                return len(records)

        records, _ = NewsAnnouncementsClient.normalize(ROWS)
        self.assertEqual(len(records), 2)
        fake = _FakeRepo(known={"INE002A01018"})  # TCS isin absent
        n = NewsAnnouncementsClient.persist(records, repo=fake)
        self.assertEqual(n, 1)
        self.assertEqual(fake.write_calls, 1)  # single write call
        self.assertEqual([r["symbol"] for r in fake.written], ["RELIANCE"])
        self.assertEqual(NewsAnnouncementsClient.persist.last_dropped, 1)


class TestFetchWindow(unittest.TestCase):
    def test_fetch_ok_with_fake_session(self):
        payload = {"data": [dict(ROWS[0]), dict(ROWS[1])]}
        client = NewsAnnouncementsClient(
            session=_FakeSession(payload=payload), rate_limit_sec=0)
        rows = client.fetch_window("2026-09-18", "2026-09-19")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["symbol"], "RELIANCE")
        api_calls = [u for u in client.session.calls if "corporate-announcements" in u]
        self.assertEqual(len(api_calls), 1)
        self.assertIn("from_date=18-09-2026", api_calls[0])
        self.assertIn("to_date=19-09-2026", api_calls[0])
        self.assertIn("index=equities", api_calls[0])

    def test_fetch_fail_closed(self):
        client = NewsAnnouncementsClient(
            session=_FakeSession(fail=True), rate_limit_sec=0)
        self.assertEqual(client.fetch_window("2026-09-18", "2026-09-19"), [])
        bad = NewsAnnouncementsClient(
            session=_FakeSession(payload={"data": []}, status=403), rate_limit_sec=0)
        self.assertEqual(bad.fetch_window("2026-09-18", "2026-09-19"), [])

    def test_no_network_at_import(self):
        # importing the module must not touch the network: client construction
        # with an injected session performs zero calls until fetch_window.
        sess = _FakeSession(payload={"data": []})
        client = NewsAnnouncementsClient(session=sess, rate_limit_sec=0)
        self.assertEqual(sess.calls, [])


if __name__ == "__main__":
    unittest.main()
