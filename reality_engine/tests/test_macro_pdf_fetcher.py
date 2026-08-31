"""
Tests for the Macro PDF Fetcher (second-tier peer data: Central/State Budgets,
PIB circulars, RBI reports).
"""

from __future__ import annotations

import sys
import argparse
import hashlib
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.config import (
    CENTRAL_BUDGET_URLS,
    STATE_BUDGET_URLS,
    MACRO_DIRECT_ALLOW_HOSTS,
    MACRO_BROWSER_REQUIRED_HOSTS,
)
from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion.macro_pdf_fetcher import MacroPDFFetcher


def _make_repo(tmp_path: Path):
    """Create a fresh Repository backed by a temp SQLite DB (has raw_documents)."""
    db_path = tmp_path / "macro_test.db"
    mgr = DatabaseManager(db_path=db_path)
    return Repository(manager=mgr)


class TestMacroPDFConfig(unittest.TestCase):
    """Validates endpoint constants from the research wave."""

    def test_01_central_budget_urls_complete(self):
        """Central list must cover 3 speeches + 3 surveys across FY2024-25/2025-26."""
        self.assertEqual(len(CENTRAL_BUDGET_URLS), 6)

        unions = [e for e in CENTRAL_BUDGET_URLS if e["source_type"] == "Union_Budget"]
        surveys = [e for e in CENTRAL_BUDGET_URLS if e["source_type"] == "Economic_Survey"]
        self.assertEqual(len(unions), 3)
        self.assertEqual(len(surveys), 3)

        # The three verified speech URLs from the research summary.
        urls = {e["url"] for e in unions}
        self.assertIn("https://www.indiabudget.gov.in/doc/bspeech/bs2024_25(I).pdf", urls)
        self.assertIn("https://www.indiabudget.gov.in/doc/bspeech/bs2024_25.pdf", urls)
        self.assertIn("https://www.indiabudget.gov.in/doc/bspeech/bs2025_26.pdf", urls)

        # Each fiscal year represented for both speech + survey.
        for fy in ("2024-25", "2025-26"):
            self.assertTrue(any(e["year"] == fy and e["source_type"] == "Union_Budget" for e in CENTRAL_BUDGET_URLS))
            self.assertTrue(any(e["year"] == fy and e["source_type"] == "Economic_Survey" for e in CENTRAL_BUDGET_URLS))

    def test_02_state_budget_dict_has_8_states_x_2_years(self):
        """All 8 states present with 2024-25 and 2025-26 entries + headless flag."""
        self.assertEqual(len(STATE_BUDGET_URLS), 8)
        expected = {
            "UP", "Tamil_Nadu", "Maharashtra", "Karnataka",
            "Telangana", "Gujarat", "Haryana", "Andhra_Pradesh",
        }
        self.assertEqual(set(STATE_BUDGET_URLS.keys()), expected)
        # (state, year) entries that still require the browser fallback (JS-rendered
        # listings with no direct PDF). Tamil Nadu + Karnataka 2025-26 are now direct
        # (verified PDFs); Karnataka 2024-25 and Gujarat/Andhra_Pradesh remain browser.
        browser_required = {
            ("Karnataka", "2024-25"),
            ("Gujarat", "2024-25"), ("Gujarat", "2025-26"),
            ("Andhra_Pradesh", "2024-25"), ("Andhra_Pradesh", "2025-26"),
        }
        for code, state in STATE_BUDGET_URLS.items():
            self.assertIn("name", state)
            self.assertIn("2024-25", state, f"{code} missing 2024-25")
            self.assertIn("2025-26", state, f"{code} missing 2025-26")
            for yr in ("2024-25", "2025-26"):
                entry = state[yr]
                self.assertIn("url", entry)
                self.assertIn("headless_ok", entry)
                if (code, yr) in browser_required:
                    self.assertFalse(entry["headless_ok"], f"{code} {yr} should need browser")
                else:
                    self.assertTrue(entry["headless_ok"], f"{code} {yr} should be headless_ok")


class TestMacroPDFBranching(unittest.TestCase):
    """Verifies direct-GET vs browser-fallback host branching logic."""

    def test_03_headless_vs_browser_branching(self):
        fetcher = MacroPDFFetcher(use_browser_fallback=True)

        # Direct allow-list hosts -> plain GET (needs_browser False).
        # RBI (rbi.org.in / rbidocs.rbi.org.in) is now on the direct allow-list:
        # the listing pages and the rbidocs PDFs are served without the Imperva TSPD
        # challenge, so discovery uses plain GET (verified -> %PDF-1.6).
        direct = [
            "https://www.indiabudget.gov.in/doc/bspeech/bs2025_26.pdf",
            "https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/feb/doc202521492801.pdf",
            "https://archive.pib.gov.in/xyz.pdf",
            "https://budget.up.nic.in/budgetbhashan/budgetbhashan_2025_2026.pdf",
            "https://finance.telangana.gov.in/PreviewPage.do?filePath=budget-2025-26-books&fileName=english.pdf",
            "https://cdnbbsr.s3waas.gov.in/20250313303390883/uploads/financial_budget_2025_26.pdf",
            "https://pib.gov.in/PressReleasePage.aspx?PRID=123456",
            "https://rbidocs.rbi.org.in/rdocs/AnnualReport/PDFs/0ANNUALREPORT202425DA4AE08189C848.PDF",
            "https://rbi.org.in/Scripts/AnnualReportPublications.aspx?year=2025",
            "https://apfinance.gov.in/budget-speech.html",
            "https://apfinance.gov.in/...Bud@et26-27/documents/SpeechEnglish.pdf",
        ]
        for url in direct:
            self.assertFalse(
                fetcher.needs_browser(url),
                f"{url} should be a direct GET (allow-listed host)",
            )

        # Browser-required hosts -> needs_browser True (JS-rendered listings).
        # After promoting TN + KA to the direct allow-list, only Gujarat remains.
        browser = [
            "https://financedepartment.gujarat.gov.in/budget.html",
            "https://financedepartment.gujarat.gov.in/178/budget-volumes/en",
        ]
        for url in browser:
            self.assertTrue(
                fetcher.needs_browser(url),
                f"{url} should require the browser fallback",
            )

        # When browser fallback is disabled, needs_browser must still report truthfully
        # but the available check returns False.
        fetcher_off = MacroPDFFetcher(use_browser_fallback=False)
        self.assertFalse(fetcher_off._browser_available())
        # TN / KA / RBI / AP are no longer browser-required (direct allow-list); use a
        # JS-state host (Gujarat) to prove the truthful branching still holds for hosts
        # that DO need a browser.
        self.assertTrue(fetcher_off.needs_browser("https://financedepartment.gujarat.gov.in/budget.html"))


class TestMacroPDFHelpers(unittest.TestCase):
    """Unit tests for the new filename sanitization + link-extraction helpers."""

    def test_sanitize_filename_telangana_query(self):
        # Telangana PreviewPage.do -> illegal Windows filename with ? & =.
        ugly = "https://finance.telangana.gov.in/PreviewPage.do?filePath=budget-2025-26-books&fileName=english.pdf"
        clean = MacroPDFFetcher._sanitize_filename(ugly)
        self.assertEqual(clean, "english.pdf")
        # No illegal characters remain.
        for bad in '<>:"/\\|?*%':
            self.assertNotIn(bad, clean)

    def test_sanitize_filename_plain_pdf(self):
        self.assertEqual(
            MacroPDFFetcher._sanitize_filename("https://x.com/uploads/annual_report_2025.pdf"),
            "annual_report_2025.pdf",
        )

    def test_sanitize_filename_strips_query_and_pct(self):
        ugly = "https://host/report?token=abc%20def&id=1#frag.PDF"
        clean = MacroPDFFetcher._sanitize_filename(ugly)
        self.assertTrue(clean.lower().endswith(".pdf"))
        self.assertNotIn("?", clean)
        self.assertNotIn("%", clean)
        self.assertNotIn("&", clean)

    def test_sanitize_filename_fallback_ext(self):
        self.assertTrue(
            MacroPDFFetcher._sanitize_filename("https://host/noext", fallback="doc.pdf").endswith(".pdf")
        )

    def test_extract_pdf_links_bs4_and_regex(self):
        html = (
            '<html><body>'
            '<a href="speech.pdf">Speech</a>'
            '<a href="/docs/Volume1.PDF">V1</a>'
            '<a href="page.html">next</a>'
            '<area href="map.pdf" alt="m"/>'
            "</body></html>"
        )
        links = MacroPDFFetcher._extract_pdf_links(html, "https://example.com/budget/")
        self.assertEqual(len(links), 3)
        self.assertIn("https://example.com/budget/speech.pdf", links)
        self.assertIn("https://example.com/docs/Volume1.PDF", links)
        self.assertIn("https://example.com/budget/map.pdf", links)
        # Deduped + order preserving.
        again = MacroPDFFetcher._extract_pdf_links(html + '<a href="speech.pdf">dup</a>', "https://example.com/budget/")
        self.assertEqual(len(again), 3)

    def test_extract_pdf_links_regex_fallback(self):
        # Force the regex path by temporarily hiding BeautifulSoup.
        real_bs4 = MacroPDFFetcher._extract_pdf_links.__func__ if hasattr(MacroPDFFetcher._extract_pdf_links, "__func__") else None
        import reality_engine.ingestion.macro_pdf_fetcher as mpf
        saved = mpf.BeautifulSoup, mpf._HAS_BS4
        mpf.BeautifulSoup, mpf._HAS_BS4 = None, False
        try:
            html = '<a href="a.pdf">a</a><A HREF="b.pdf">b</A>'
            links = MacroPDFFetcher._extract_pdf_links(html, "https://h/")
            self.assertEqual(set(links), {"https://h/a.pdf", "https://h/b.pdf"})
        finally:
            mpf.BeautifulSoup, mpf._HAS_BS4 = saved


class TestMacroPDFRepository(unittest.TestCase):
    """Repo upsert dedup + lookup helpers are transactional and idempotent."""

    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / "tmp_macro"
        self.tmp.mkdir(exist_ok=True)
        self.repo = _make_repo(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_04_upsert_dedup_same_sha256(self):
        rec = {
            "title": "Union Budget 2024-25 Speech (Part I)",
            "source_type": "Union_Budget",
            "published_date": "2024-07-23",
            "fiscal_period": "FY2024-25",
            "source_url": "https://www.indiabudget.gov.in/doc/bspeech/bs2024_25(I).pdf",
            "creator_or_ministry": "Ministry of Finance (GoI)",
            "sha256_hash": "deadbeef" * 8,
            "local_file_path": "/tmp/bs2024_25(I).pdf",
            "file_size_bytes": 1488972,
        }
        id1 = self.repo.upsert_raw_document(rec)
        # Same sha256, different source_url -> must NOT create a second row (sha wins).
        rec2 = dict(rec, source_url="https://mirror.example.com/bs2024_25(I).pdf")
        id2 = self.repo.upsert_raw_document(rec2)

        rows = self.repo.list_raw_documents_by_source("")
        self.assertEqual(len(rows), 1, "duplicate sha256 must not create a new row")
        self.assertEqual(id1, id2)

        # Lookup by hash works.
        by_hash = self.repo.get_raw_document_by_hash("deadbeef" * 8)
        self.assertIsNotNone(by_hash)
        self.assertEqual(by_hash["source_type"], "Union_Budget")

        # Prefix listing works.
        by_prefix = self.repo.list_raw_documents_by_source("Union_Budget")
        self.assertEqual(len(by_prefix), 1)

    def test_04b_upsert_handles_empty(self):
        self.assertEqual(self.repo.upsert_raw_document({}), 0)
        self.assertIsNone(self.repo.get_raw_document_by_hash("does-not-exist"))


class TestMacroPDFDryRun(unittest.TestCase):
    """CLI dry-run must plan URLs but never write to raw_documents."""

    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / "tmp_macro_cli"
        self.tmp.mkdir(exist_ok=True)
        self.repo = _make_repo(self.tmp)
        self.tmp_dir = self.tmp / "pdfs"
        self.tmp_dir.mkdir(exist_ok=True)
        self.fetcher = MacroPDFFetcher(data_dir=self.tmp_dir, repo=self.repo)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_05_cli_dry_run_does_not_write(self):
        from reality_engine.cli import cmd_fetch_macro

        args = argparse.Namespace(
            source="all", years="2024-25,2025-26", state_filter=None,
            workers=4, pib_limit=10, since_date=None, rate_limit=1.0, dry_run=True,
        )
        # Patch the fetcher class so cmd uses our temp-DB / temp-dir instance.
        with mock.patch(
            "reality_engine.ingestion.macro_pdf_fetcher.MacroPDFFetcher",
            return_value=self.fetcher,
        ):
            cmd_fetch_macro(args)

        # No downloads => raw_documents must remain empty.
        rows = self.repo.list_raw_documents_by_source("")
        self.assertEqual(len(rows), 0)

    def test_05b_plan_matches_config_counts(self):
        plan = self.fetcher.plan(source="all", years=["2024-25", "2025-26"])
        # central: 3 Union Budget speeches + 2 Economic Surveys in requested years
        # (the FY2023-24 consolidated survey is outside the requested window).
        self.assertEqual(plan["_total"], 5 + 16 + 1 + 2)
        self.assertEqual(len(plan["central"]), 5)
        self.assertEqual(len(plan["states"]), 16)  # 8 states x 2 years
        self.assertEqual(len(plan["pib"]), 1)
        self.assertEqual(len(plan["rbi"]), 2)

        # TN is now a direct (headless_ok=True) source in the plan.
        tn = [p for p in plan["states"] if p["source_type"] == "State_Budget_Tamil_Nadu"]
        self.assertEqual(len(tn), 2)
        self.assertEqual(tn[0]["headless_ok"], "True")


if __name__ == "__main__":
    unittest.main(verbosity=2)
