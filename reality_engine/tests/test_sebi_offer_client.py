"""Offline unit tests for the SEBI offer-document client.

Contract: no live network (every HTTP call is faked), deterministic, fast.
Covers the behaviours fetch-offer-docs depends on:
  * ajax search HTML parses into filing hits (title + page URL + ISO date)
  * non-answer / empty bodies parse to [] (fail-closed)
  * filing-page HTML resolves the direct attachdocs PDF (viewer prefix stripped)
  * discover_offer_documents shapes links for official_filing_client and
    never raises when the network misses
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TEMP_DB_DIR = tempfile.mkdtemp(prefix="reality_sebi_offer_test_db_")
os.environ.setdefault(
    "REALITY_ENGINE_DB_PATH", str(Path(_TEMP_DB_DIR) / "singleton_isolated.db")
)

from reality_engine.ingestion.sebi_offer_client import (  # noqa: E402
    DISCOVERY_SOURCE,
    DOC_OFFER_DOCUMENT,
    SOURCE_SEBI_OFFICIAL,
    SebiOfferClient,
)


SEARCH_HTML = """
<table><tr><td>Sep 23, 2025</td>
<td><a href="https://www.sebi.gov.in/filings/public-issues/sep-2025/airfloa-rail-technology-limited-prospectus_96778.html">Airfloa Rail Technology Limited - Prospectus</a></td></tr>
<tr><td>Sep 10, 2025</td>
<td><a href="/filings/public-issues/sep-2025/example-limited-drhp_12345.html">Example Limited - DRHP</a></td></tr>
</table>
"""

FILING_HTML = """
<html><body><iframe src="../../../web/?file=https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1758608206692.pdf">
Airfloa Rail Technology Limited - Prospectus</iframe></body></html>
"""


class FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class SebiOfferClientTest(unittest.TestCase):
    def setUp(self):
        self.client = SebiOfferClient(rate_limit_sec=0)

    # -- pure parsers ----------------------------------------------------
    def test_parse_search_html_extracts_hits(self):
        hits = SebiOfferClient._parse_search_html(SEARCH_HTML, "final", 10)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["title"], "Airfloa Rail Technology Limited - Prospectus")
        self.assertTrue(hits[0]["filing_page_url"].endswith("_96778.html"))
        self.assertEqual(hits[0]["doc_date"], "2025-09-23")
        self.assertEqual(hits[0]["stage"], "final")
        # Relative href is absolutized; DRHP title maps to draft.
        self.assertTrue(hits[1]["filing_page_url"].startswith("https://www.sebi.gov.in/"))
        self.assertEqual(hits[1]["stage"], "final")  # searched stage wins

    def test_parse_search_html_fail_closed(self):
        self.assertEqual(SebiOfferClient._parse_search_html("", "final", 10), [])
        self.assertEqual(
            SebiOfferClient._parse_search_html("<html><body>No record(s)</body></html>", "final", 10),
            [],
        )

    def test_parse_pdf_url_strips_viewer(self):
        pdf = SebiOfferClient._parse_pdf_url(FILING_HTML)
        self.assertEqual(
            pdf,
            "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1758608206692.pdf",
        )
        self.assertIsNone(SebiOfferClient._parse_pdf_url("<html><body>no pdf</body></html>"))

    # -- network paths (faked session) ------------------------------------
    def _fake_session(self, listing_ok=True, ajax_text=SEARCH_HTML, filing_text=None):
        sess = mock.MagicMock()
        listing = FakeResp(200, "<html>listing</html>") if listing_ok else FakeResp(500, "")
        ajax = FakeResp(200, ajax_text)

        def get(url, timeout=30):
            if "HomeAction.do" in url:
                return listing
            # Distinct PDF per filing page so link-dedup keeps both hits.
            pdf = "1758608206692.pdf" if "96778" in url else "1758608206693.pdf"
            return FakeResp(200, filing_text or FILING_HTML.replace("1758608206692.pdf", pdf))

        sess.get.side_effect = get
        sess.post.return_value = ajax
        return sess

    def test_search_uses_ajax_contract(self):
        self.client.http_session = self._fake_session()
        hits = self.client.search("airfloa", stage="final")
        self.assertEqual(len(hits), 2)
        post_args, post_kwargs = self.client.http_session.post.call_args
        self.assertIn("getnewslistinfo.jsp", post_args[0])
        self.assertEqual(post_kwargs["headers"]["X-Requested-With"], "XMLHttpRequest")
        posted = post_kwargs["data"]
        self.assertEqual(posted["search"], "airfloa")
        self.assertEqual(posted["smid"], "12")

    def test_search_fail_closed_on_http_miss(self):
        sess = self._fake_session()
        sess.post.return_value = FakeResp(530, "blocked")
        self.client.http_session = sess
        self.assertEqual(self.client.search("airfloa"), [])
        self.assertEqual(self.client.search("airfloa", stage="bogus"), [])
        self.assertEqual(self.client.search(""), [])

    def test_discover_shapes_links_for_filing_client(self):
        self.client.http_session = self._fake_session()
        disc = self.client.discover_offer_documents(
            "AIRFLOA", company_name="Airfloa Rail Technology Limited", stage="final"
        )
        self.assertEqual(disc["symbol"], "AIRFLOA")
        self.assertIsNone(disc["error"])
        self.assertEqual(len(disc["links"]), 2)
        for ln in disc["links"]:
            self.assertEqual(ln["doc_type"], DOC_OFFER_DOCUMENT)
            self.assertEqual(ln["source"], SOURCE_SEBI_OFFICIAL)
            self.assertEqual(ln["discovery_source"], DISCOVERY_SOURCE)
            self.assertTrue(ln["source_url"].endswith(".pdf"))
            self.assertIn("filing_page_url", ln)
        # company-name query hit short-circuits the symbol fallback: one
        # search call per stage, not two.
        self.assertEqual(self.client.http_session.post.call_count, 1)

    def test_discover_never_raises(self):
        sess = mock.MagicMock()
        sess.get.side_effect = RuntimeError("net down")
        sess.post.side_effect = RuntimeError("net down")
        self.client.http_session = sess
        disc = self.client.discover_offer_documents("X", stage="both")
        self.assertEqual(disc["links"], [])
        self.assertEqual(disc["error"], "no_offer_documents_found")
        bad = self.client.discover_offer_documents("X", stage="bogus")
        self.assertTrue(bad["error"].startswith("unknown_stage"))


if __name__ == "__main__":
    unittest.main()
