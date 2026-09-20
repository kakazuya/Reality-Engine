"""Tests for policy_press_client: parse gates, record shapes, DB round-trip.

Zero network: all fetch paths use an injected fake fetcher.
Temp DB via DatabaseManager(tempfile); asserts upsert_raw_document only —
FTS is asserted by record shape, not by a live FTS write.
"""
import re
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion import policy_press_client as ppc


EN_HTML = """<html><head>
<meta property="og:title" content="Cabinet approves PM Research Fellowship Scheme" />
<title>PIB Press Release</title>
</head><body>
<p>Ministry of Education</p>
<p>Posted On: 15 SEP 2026 5:30PM by PIB Delhi</p>
<p>The Union Cabinet chaired by the Prime Minister today approved the scheme.</p>
</body></html>"""

HI_HTML = """<html><head>
<meta property="og:title" content="\u0915\u0947\u0902\u0926\u094d\u0930\u0940\u092f \u092e\u0902\u0924\u094d\u0930\u093f\u092e\u0902\u0921\u0932 \u0928\u0947 \u092f\u094b\u091c\u0928\u093e \u0915\u094b \u092e\u0902\u091c\u0942\u0930\u0940 \u0926\u0940" />
<title>PIB Press Release</title>
</head><body>
<p>\u0936\u093f\u0915\u094d\u0937\u093e \u092e\u0902\u0924\u094d\u0930\u093e\u0932\u092f</p>
<p>Posted On: 15 SEP 2026 5:30PM by PIB Delhi</p>
</body></html>"""

RBI_SHELL_HTML = """<html><head>
<meta property="og:title" content="RBI announces OMO calendar" />
<title>RBI Press Release</title>
</head><body><p>01 Aug 2026</p><div id="jsGrid"></div></body></html>"""


def _mk_repo(td):
    mgr = DatabaseManager(db_path=Path(td) / "t.db")
    return Repository(manager=mgr), mgr


def _pib_fake(mapping):
    """mapping: prid -> html or None. Unknown PRIDs -> None (miss)."""
    def _fetch(url, headers=None, timeout=15):
        m = re.search(r"PRID=(\d+)", url or "")
        if not m:
            return None
        return mapping.get(int(m.group(1)))
    return _fetch


class TestPibParse(unittest.TestCase):
    def test_english_parsed(self):
        parsed = ppc.parse_detail(EN_HTML)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["title"],
                         "Cabinet approves PM Research Fellowship Scheme")
        self.assertEqual(parsed["date"], "2026-09-15")
        self.assertIn("Ministry of", parsed["ministry"])

    def test_hindi_gated(self):
        self.assertFalse(ppc.is_english_title(
            "केन्द्रीय मंत्रिमंडल ने योजना को मंजूरी दी"))
        self.assertIsNone(ppc.parse_detail(HI_HTML))

    def test_none_and_empty_fail_closed(self):
        self.assertIsNone(ppc.parse_detail(None))
        self.assertIsNone(ppc.parse_detail(""))
        self.assertIsNone(ppc.pib_parse_detail("<html></html>"))


class TestRbiParse(unittest.TestCase):
    def test_unresolvable_body_returns_none(self):
        self.assertIsNone(ppc.rbi_parse_detail(RBI_SHELL_HTML))
        self.assertIsNone(ppc.rbi_parse_detail(None))
        self.assertIsNone(ppc.rbi_parse_detail("<html><body>hi</body></html>"))


class TestRecordShapes(unittest.TestCase):
    def test_pib_record_contract_keys(self):
        rec = ppc._pib_record(1951701, {
            "title": "T", "date": "2026-09-15",
            "ministry": "Ministry of X", "text": "body"})
        self.assertEqual(
            set(k for k in rec if k != "text"),
            {"title", "source_type", "published_date", "fiscal_period",
             "source_url", "creator_or_ministry", "sha256_hash",
             "local_file_path", "file_size_bytes"})
        self.assertEqual(rec["source_type"], "PIB_Press_Release")
        self.assertEqual(rec["published_date"], "2026-09-15")
        self.assertIsNone(rec["fiscal_period"])
        self.assertIsNone(rec["local_file_path"])
        self.assertIsNone(rec["file_size_bytes"])
        self.assertIn("PRID=1951701", rec["source_url"])

    def test_rbi_record_contract_keys(self):
        rec = ppc._rbi_record(12345, "RBI title", "2026-08-01", None)
        self.assertEqual(rec["source_type"], "RBI_Press_Release")
        self.assertEqual(rec["creator_or_ministry"], "Reserve Bank of India")
        self.assertEqual(rec["published_date"], "2026-08-01")
        self.assertIn("prid=12345", rec["source_url"])
        self.assertIsNone(rec["fiscal_period"])

    def test_bad_date_maps_to_none(self):
        self.assertIsNone(ppc._pib_record(
            1, {"title": "T", "date": "not-a-date"}))
        self.assertIsNone(ppc._rbi_record(1, "T", "yesterday", None))
        self.assertIsNone(ppc._rbi_record(1, "T", None, None))

    def test_fts_chunk_id_shape(self):
        fts = {"chunk_id": f"{ppc.PIB_SOURCE_TYPE}:42:0", "symbol": "",
               "isin": "", "source_type": ppc.PIB_SOURCE_TYPE,
               "document_date": "2026-09-15", "document_text": "body"}
        self.assertEqual(fts["chunk_id"], "PIB_Press_Release:42:0")
        self.assertEqual(
            set(fts),
            {"chunk_id", "symbol", "isin", "source_type",
             "document_date", "document_text"})


class TestFetchNew(unittest.TestCase):
    def test_pib_fetch_new_counts(self):
        with tempfile.TemporaryDirectory() as td:
            repo, _ = _mk_repo(td)
            seed = ppc.last_prid(repo)
            self.assertEqual(seed, ppc.PIB_SEED_PRID)
            mapping = {seed + 1: EN_HTML, seed + 2: HI_HTML,
                       seed + 3: None}
            records, stats = ppc.fetch_new(
                "PIB", cap=3, repo=repo,
                fetcher=_pib_fake(mapping))
            self.assertEqual(len(records), 1)
            self.assertEqual(stats["records"], 1)
            self.assertEqual(stats["skipped"], 1)  # Hindi gate
            self.assertEqual(stats["misses"], 1)  # None fetch
            self.assertEqual(records[0]["source_type"], "PIB_Press_Release")

    def test_rbi_fetch_new_keeps_permalink_row(self):
        def fake(url, headers=None, timeout=15):
            if url == ppc.RBI_HOMEPAGE_URL:
                return ('<a href="/Scripts/BS_PressReleaseDisplay.aspx'
                        '?prid=777001">x</a>')
            if "prid=777001" in url:
                return RBI_SHELL_HTML
            return None

        records, stats = ppc.fetch_new("RBI", cap=10, fetcher=fake)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["source_type"], "RBI_Press_Release")
        self.assertEqual(rec["published_date"], "2026-08-01")
        self.assertIn("prid=777001", rec["source_url"])
        self.assertIsNone(rec["text"])

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            ppc.fetch_new("BSE", cap=1,
                          fetcher=lambda *a, **k: None)


class TestDbRoundTrip(unittest.TestCase):
    def test_upsert_raw_document_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            repo, _ = _mk_repo(td)
            rec = ppc._pib_record(1951701, {
                "title": "Cabinet approves PM Research Fellowship Scheme",
                "date": "2026-09-15", "ministry": "Ministry of Education",
                "text": "body"})
            contract = {k: rec[k] for k in (
                "title", "source_type", "published_date", "fiscal_period",
                "source_url", "creator_or_ministry", "sha256_hash",
                "local_file_path", "file_size_bytes")}
            doc_id = repo.upsert_raw_document(contract)
            self.assertGreater(doc_id, 0)
            row = repo.get_raw_document_by_hash(contract["sha256_hash"])
            self.assertIsNotNone(row)
            self.assertEqual(row["title"], contract["title"])
            self.assertEqual(row["source_type"], "PIB_Press_Release")
            self.assertEqual(row["published_date"], "2026-09-15")

    def test_persist_text_chunk_shape_with_stub_repo(self):
        seen = {}

        class StubRepo:
            def upsert_raw_document(self, contract):
                seen["contract"] = contract
                return 7

            def get_raw_document_by_hash(self, sha):
                return {"doc_id": 7, "sha256_hash": sha}

            def insert_fts_chunks(self, recs):
                seen["fts"] = recs
                return len(recs)

        rec = ppc._pib_record(1951701, {
            "title": "T", "date": "2026-09-15",
            "ministry": None, "text": "hello body"})
        n = ppc.persist_text([rec], repo=StubRepo())
        self.assertEqual(n, 1)
        self.assertEqual(seen["fts"][0]["chunk_id"],
                         "PIB_Press_Release:7:0")
        self.assertEqual(seen["fts"][0]["symbol"], "")
        self.assertEqual(seen["fts"][0]["isin"], "")


if __name__ == "__main__":
    unittest.main()
