"""Offline unit tests for the SEBI offer-document bulk backfill.

Contract: no live network (crawler/archive/ingest/distill all faked or temp-DB),
deterministic, fast. Covers what offer-backfill needs:
  * name normalization + token-subset company matching
  * crawl dedup across stages
  * run_once dry-run: crawl -> match report, zero writes
  * distill dry-run: signal extraction counts without DB writes
  * DRHP signal extraction (business sentences, supply/capex/regulated hits)
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TEMP_DB_DIR = tempfile.mkdtemp(prefix="reality_offer_backfill_test_db_")
os.environ.setdefault(
    "REALITY_ENGINE_DB_PATH", str(Path(_TEMP_DB_DIR) / "singleton_isolated.db")
)

from reality_engine.db.database import DatabaseManager  # noqa: E402
from reality_engine.pipeline import offer_backfill as ob  # noqa: E402


COMPANIES = [
    {"nse_symbol": "AIRFLOA", "company_name": "Airfloa Rail Technology Limited",
     "isin": "INE0XXX", "listing_source": "DUAL"},
    {"nse_symbol": "RELIANCE", "company_name": "Reliance Industries Limited",
     "isin": "INE002A", "listing_source": "DUAL"},
]

CRAWL_FINAL = [
    {"title": "Airfloa Rail Technology Limited - Prospectus",
     "filing_page_url": "https://www.sebi.gov.in/filings/public-issues/sep-2025/a_96778.html",
     "doc_date": "2025-09-23", "stage": "final"},
]
CRAWL_DRAFT = [
    {"title": "Example Widgets Limited - DRHP",
     "filing_page_url": "https://www.sebi.gov.in/filings/public-issues/sep-2025/e_1.html",
     "doc_date": "2025-09-01", "stage": "draft"},
]


class FakeClient:
    def __init__(self):
        self.crawls = []

    def crawl_listing(self, stage="final", max_pages=0):
        self.crawls.append((stage, max_pages))
        return list(CRAWL_FINAL) if stage == "final" else list(CRAWL_DRAFT)

    def resolve_pdf_url(self, url):
        return "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/x.pdf"


class BackfillPureTest(unittest.TestCase):
    def test_normalize_strips_suffixes(self):
        self.assertEqual(
            ob.normalize_name("Airfloa Rail Technology Limited - Prospectus"),
            "airfloa rail technology",
        )
        self.assertEqual(ob.normalize_name("Example Widgets Ltd - DRHP"), "example widgets")

    def test_match_token_subset(self):
        hit = ob.match_company("Airfloa Rail Technology Limited - Prospectus", COMPANIES)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["nse_symbol"], "AIRFLOA")
        self.assertIsNone(ob.match_company("Totally Unrelated Foo - Prospectus", COMPANIES))
        self.assertIsNone(ob.match_company("", COMPANIES))

    def test_match_sme_alias_variants(self):
        sme = [
            {"nse_symbol": "VEEGALAND", "company_name": "Veegaland Developers Ltd",
             "isin": "INE1", "listing_source": "NSE"},
            {"nse_symbol": "HEXAGON", "company_name": "Hexagon Nutrition Ltd",
             "isin": "INE2", "listing_source": "NSE"},
        ]
        hit = ob.match_company("Veegaland Developers Limited - PROSPECTUS", sme)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["nse_symbol"], "VEEGALAND")
        hit = ob.match_company("Hexagon Nutrition Limited - Prospectus", sme)
        self.assertEqual(hit["nse_symbol"], "HEXAGON")
        # Single-token titles never substring-match (SKM must not hit SKM EGG).
        egg = [{"nse_symbol": "SKMEGG", "company_name": "SKM Egg Products Export Limited",
                "isin": "INE3", "listing_source": "NSE"}]
        self.assertIsNone(ob.match_company("SKM - Prospectus", egg))

    def test_crawl_dedups_across_stages(self):
        dup = dict(CRAWL_FINAL[0])
        client = mock.MagicMock()
        client.crawl_listing.side_effect = [[dup], [dup]]
        recs = ob.crawl(["final", "draft"], client=client)
        self.assertEqual(len(recs), 1)

    def test_extract_signals(self):
        text = (
            "Our Company is engaged in the manufacture of rail components. "
            "We import raw material from China and manage supply chain logistics. "
            "We plan a capex for a new manufacturing facility. "
            "Our brand and patents give us pricing power on platform contracts."
        )
        sig = ob.extract_drhp_signals(text)
        self.assertEqual(len(sig["business_sentences"]), 1)
        self.assertIn("raw material", sig["supply_hits"])
        self.assertIn("china", sig["supply_hits"])
        self.assertIn("capex", sig["capex_hits"])
        self.assertGreaterEqual(sig["moat"]["total"], 1.0)

    def test_extract_skips_prospectus_boilerplate(self):
        boiler = (
            "BOOK RUNNING LEAD MANAGERS Names and Logos of the Book Running Lead Managers "
            "Contact Person E-mail: rentomojo.ipo@motilaloswal.com Tel: +91 22 7193 4380. "
            "Our Company is engaged in the business of online furniture rental services "
            "and provides furnishing solutions across Indian cities."
        )
        sig = ob.extract_drhp_signals(boiler)
        self.assertEqual(len(sig["business_sentences"]), 1)
        self.assertIn("furniture rental", sig["business_sentences"][0])

class BackfillDryRunTest(unittest.TestCase):
    def setUp(self):
        fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        fh.close()
        self.mgr = DatabaseManager(Path(fh.name))
        self.db_file = fh.name
        self.tmp = tempfile.TemporaryDirectory()
        self.loop_dir = Path(self.tmp.name) / "offer"

    def tearDown(self):
        self.tmp.cleanup()
        for path in (self.db_file, self.db_file + "-wal", self.db_file + "-shm"):
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_dry_run_reports_match_without_writes(self):
        client = FakeClient()
        with mock.patch.object(ob, "load_match_companies", return_value=COMPANIES):
            result = ob.run_once(
                loop_dir=self.loop_dir, manager=self.mgr, dry_run=True,
                stages=("final", "draft"), client=client,
            )
        self.assertEqual(result["rc"], 0)
        self.assertEqual(result["crawled"], 2)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["unmatched"], 1)
        self.assertEqual(result["match_sample"][0]["symbol"], "AIRFLOA")
        self.assertTrue(result["dry_run"])
        # Crawl+match state persisted; archive/distill never ran.
        state = json.loads((self.loop_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["records"]), 2)
        self.assertNotIn("distill", result)

    def test_lock_contention_skips(self):
        fd = ob.acquire_lock(self.loop_dir / ob.LOCK_NAME)
        try:
            result = ob.run_once(loop_dir=self.loop_dir, manager=self.mgr, dry_run=True)
            self.assertTrue(result["skipped"])
            self.assertEqual(result["rc"], 2)
        finally:
            ob.release_lock(fd, self.loop_dir / ob.LOCK_NAME)


if __name__ == "__main__":
    unittest.main()
