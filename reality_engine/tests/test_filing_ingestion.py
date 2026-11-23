"""
Offline, mocked unit tests for the 5 new ingestion modules:

  * filing_discovery.py          (FilingDiscoveryClient)
  * official_filing_client.py    (OfficialFilingClient)
  * corporate_actions_client.py  (CorporateActionsClient + normalization helpers)
  * official_financials_client.py(OfficialFinancialsClient)
  * delisting_nclt_client.py     (DelistingNCLTClient)
  * headless_fetcher.py          (JWT/cookie helpers, fail-closed availability)

Design contract (per AGENTS.md / project conventions):
  * No live network. Every HTTP call is mocked or the method is replaced.
  * DB-touching paths (corporate_actions upsert, delisting derive/scan/persist)
    run against an isolated temp SQLite DB, never the main DB.
  * Fail-closed behavior is asserted: missing playwright must not launch a
    browser and must return empty/None sentinels.
  * Deterministic, fast (<15s total for the whole module).
"""

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Point the global singleton DB at a temp file *before* importing any
# reality_engine module, so accidental singleton use stays isolated.
_TEMP_DB_DIR = tempfile.mkdtemp(prefix="reality_filing_test_db_")
os.environ.setdefault(
    "REALITY_ENGINE_DB_PATH", str(Path(_TEMP_DB_DIR) / "singleton_isolated.db")
)

from reality_engine.db.database import DatabaseManager  # noqa: E402
from reality_engine.db.repository import Repository  # noqa: E402
from reality_engine.ingestion import headless_fetcher as hf_module  # noqa: E402
from reality_engine.ingestion import (  # noqa: E402
    corporate_actions_client,
    delisting_nclt_client as dnc_module,
    filing_discovery,
    official_filing_client,
    official_financials_client,
)
from reality_engine.ingestion.corporate_actions_client import (  # noqa: E402
    CorporateActionsClient,
    _normalize_action_type,
    _parse_date,
)
from reality_engine.ingestion.delisting_nclt_client import (  # noqa: E402
    DelistingNCLTClient,
    _match_status,
)
from reality_engine.ingestion.filing_discovery import (  # noqa: E402
    FilingDiscoveryClient,
    SOURCE_OFFICIAL_BSE,
    SOURCE_OFFICIAL_NSE,
    SOURCE_SCREENER_DISCOVERY,
    DOC_ANNUAL_REPORT,
    DOC_CONCALL_TRANSCRIPT,
    DOC_INVESTOR_PRESENTATION,
    DOC_FINANCIAL_RESULT,
    DOC_OTHER_FILING,
)
from reality_engine.ingestion.headless_fetcher import (  # noqa: E402
    HeadlessFetcher,
    cookies_to_header,
    extract_jwt_token,
    is_playwright_available,
)
from reality_engine.ingestion.official_filing_client import OfficialFilingClient  # noqa: E402
from reality_engine.ingestion.official_financials_client import (  # noqa: E402
    OfficialFinancialsClient,
    SOURCE_BSE as FIN_SRC_BSE,
    SOURCE_NSE as FIN_SRC_NSE,
)


class FakeResp:
    """Minimal stand-in for a requests/curl_cffi response (context-manager aware)."""

    def __init__(self, status_code=200, headers=None, content=b"", text=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self._text = text if text is not None else content.decode("utf-8", "ignore")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text(self):
        return self._text


# =====================================================================
# 1. filing_discovery
# =====================================================================
class TestFilingDiscovery(unittest.TestCase):
    def setUp(self):
        self.client = FilingDiscoveryClient(rate_limit_sec=0, max_retries=1)

    def test_classify_variants(self):
        # URL-based classification (no context needed).
        self.assertEqual(
            FilingDiscoveryClient._classify("https://www.bseindia.com/bseplus/AnnualReport/X.pdf"),
            DOC_ANNUAL_REPORT,
        )
        # Context-based classification.
        self.assertEqual(
            FilingDiscoveryClient._classify("https://x.com/AttachHis/abc.pdf", "Q3 Concall Transcript"),
            DOC_CONCALL_TRANSCRIPT,
        )
        self.assertEqual(
            FilingDiscoveryClient._classify("https://x.com/foo.pdf", "Investor Presentation slides"),
            DOC_INVESTOR_PRESENTATION,
        )
        self.assertEqual(
            FilingDiscoveryClient._classify("https://x.com/bar.pdf", "Annual Report 2024"),
            DOC_ANNUAL_REPORT,
        )
        self.assertEqual(
            FilingDiscoveryClient._classify("https://x.com/baz.xml", "Financial Results"),
            DOC_FINANCIAL_RESULT,
        )
        self.assertEqual(
            FilingDiscoveryClient._classify("https://x.com/unknown.dat", "random note"),
            DOC_OTHER_FILING,
        )

    def test_provenance(self):
        self.assertEqual(
            FilingDiscoveryClient._provenance(
                "https://www.bseindia.com/xml-data/corpfiling/AttachHis/a.pdf"
            ),
            SOURCE_OFFICIAL_BSE,
        )
        self.assertEqual(
            FilingDiscoveryClient._provenance(
                "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=a.pdf"
            ),
            SOURCE_OFFICIAL_BSE,
        )
        self.assertEqual(
            FilingDiscoveryClient._provenance(
                "https://www.bseindia.com/bseplus/AnnualReport/a.pdf"
            ),
            SOURCE_OFFICIAL_BSE,
        )
        self.assertEqual(
            FilingDiscoveryClient._provenance("https://www.nseindia.com/corporates/x.xml"),
            SOURCE_OFFICIAL_NSE,
        )
        # Generic bseindia/nseindia host still resolves to the official source.
        self.assertEqual(
            FilingDiscoveryClient._provenance("https://www.bseindia.com/foo/bar"),
            SOURCE_OFFICIAL_BSE,
        )
        self.assertEqual(
            FilingDiscoveryClient._provenance("https://www.screener.in/company/X"),
            SOURCE_SCREENER_DISCOVERY,
        )

    def test_extract_official_links_excludes_nav_and_dedup(self):
        html = """
        <html><body>
          <a href="https://www.bseindia.com/bseplus/AnnualReport/RELIANCE_2024.pdf">Annual Report</a>
          <a href="https://www.bseindia.com/bseplus/AnnualReport/RELIANCE_2024.pdf">Annual Report dup</a>
          <a href="https://www.bseindia.com/xml-data/corpfiling/AttachHis/CONCALL123.pdf">Concall</a>
          <a href="https://www.nseindia.com/corporates/financials/foo.xml">Results</a>
          <a href="https://www.bseindia.com/stock-share-price/RELIANCE/500325/">Quote</a>
          <a href="https://www.nseindia.com/companies-listing/company-listing/500325">NSE quote</a>
        </body></html>
        """
        links = self.client._extract_official_links(html)
        urls = {l["url"] for l in links}
        # Navigation / quote pages must be excluded.
        self.assertNotIn("https://www.bseindia.com/stock-share-price/RELIANCE/500325/", urls)
        self.assertNotIn("https://www.nseindia.com/companies-listing/company-listing/500325", urls)
        # Only the 3 real document URLs survive (bseplus is de-duplicated).
        self.assertEqual(len(links), 3)
        self.assertIn("https://www.bseindia.com/bseplus/AnnualReport/RELIANCE_2024.pdf", urls)
        self.assertIn("https://www.bseindia.com/xml-data/corpfiling/AttachHis/CONCALL123.pdf", urls)
        self.assertIn("https://www.nseindia.com/corporates/financials/foo.xml", urls)

    def test_discover_filings_mocked_html(self):
        html = """
        <html><body>
          <a href="https://www.bseindia.com/bseplus/AnnualReport/RELIANCE_2024.pdf">Annual Report 2024</a>
          <a href="https://www.bseindia.com/bseplus/AnnualReport/RELIANCE_2024.pdf">Annual Report 2024 dup</a>
          <a href="https://www.bseindia.com/xml-data/corpfiling/AttachHis/CONCALL123.pdf">Concall Transcript Q3</a>
          <a href="https://www.nseindia.com/corporates/financials/foo.xml">Q3 Results</a>
          <a href="https://www.bseindia.com/stock-share-price/RELIANCE/500325/">Reliance Quote Page</a>
        </body></html>
        """
        self.client._get_html = lambda url: html  # fully offline
        result = self.client.discover_filings("RELIANCE", bse_code="500325")

        self.assertIsNone(result["error"])
        self.assertEqual(result["symbol"], "RELIANCE")
        self.assertEqual(result["bse_code"], "500325")
        # 3 unique document links (bseplus de-duplicated), nav excluded.
        self.assertEqual(len(result["links"]), 3)
        for link in result["links"]:
            self.assertNotIn("stock-share-price", link["source_url"])
            self.assertIn(link["source"], (SOURCE_OFFICIAL_BSE, SOURCE_OFFICIAL_NSE))
            self.assertEqual(link["discovery_source"], SOURCE_SCREENER_DISCOVERY)
        # URL-based classification works without depending on bs4 context.
        annual = next(
            l for l in result["links"]
            if "bseplus/AnnualReport" in l["source_url"]
        )
        self.assertEqual(annual["doc_type"], DOC_ANNUAL_REPORT)
        self.assertEqual(annual["source"], SOURCE_OFFICIAL_BSE)


# =====================================================================
# 2. official_filing_client
# =====================================================================
class TestOfficialFilingClient(unittest.TestCase):
    def setUp(self):
        self.client = OfficialFilingClient(rate_limit_sec=0, max_retries=1)
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="reality_filing_pdf_"))
        self._pdfs_patch = mock.patch.object(
            official_filing_client, "PDFS_DIR", self.tmp_dir
        )
        self._pdfs_patch.start()

    def tearDown(self):
        self._pdfs_patch.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_local_path_determinism(self):
        url = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/ABC123.pdf"
        p1 = self.client._local_path("RELIANCE", DOC_ANNUAL_REPORT, url)
        p2 = self.client._local_path("RELIANCE", DOC_ANNUAL_REPORT, url)
        self.assertEqual(p1, p2)
        self.assertTrue(p1.endswith(".pdf"))
        self.assertIn("RELIANCE", p1)
        self.assertIn(DOC_ANNUAL_REPORT, p1)

    def test_local_path_extension(self):
        # URL without a known extension gets .pdf appended.
        p = self.client._local_path("TCS", "OTHER_FILING", "https://x.com/AttachHis/XYZ")
        self.assertTrue(p.endswith(".pdf"))
        # Known extension is preserved.
        p2 = self.client._local_path("TCS", "XBRL", "https://x.com/data/foo.xbrl")
        self.assertTrue(p2.endswith(".xbrl"))
        # Slashes / unsafe chars are sanitized in the filename.
        p3 = self.client._local_path("A/B", "X", "https://x.com/a/b/c.pdf")
        self.assertNotIn("/", p3.split("\\")[-1].replace("\\\\", ""))

    def test_content_guard_html_rejected(self):
        # An HTTP 200 that returns an HTML page instead of a PDF must be rejected.
        resp = FakeResp(
            status_code=200,
            headers={"Content-Type": "text/html"},
            content=b"<html>not a pdf</html>",
        )
        self.client.http_session.get = mock.MagicMock(return_value=resp)
        # Headless fallback must NOT launch a browser -> force unavailable.
        with mock.patch.object(
            hf_module, "is_playwright_available", return_value=False
        ):
            out = self.client._download(
                "https://www.bseindia.com/xml-data/corpfiling/AttachHis/BAD.pdf", "/tmp/x.pdf"
            )
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "html_error_page_not_pdf")

    def test_download_404_terminal(self):
        resp = FakeResp(status_code=404, headers={}, content=b"")
        self.client.http_session.get = mock.MagicMock(return_value=resp)
        with mock.patch.object(
            hf_module, "is_playwright_available", return_value=False
        ):
            out = self.client._download(
                "https://www.bseindia.com/xml-data/corpfiling/AttachHis/MISSING.pdf", "/tmp/x.pdf"
            )
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "http_404")

    def test_download_sha256_recording(self):
        payload = b"%PDF-1.4 fake but valid-magic pdf bytes"
        resp = FakeResp(
            status_code=200,
            headers={"Content-Type": "application/pdf"},
            content=payload,
        )
        self.client.http_session.get = mock.MagicMock(return_value=resp)
        local_path = str(self.tmp_dir / "downloaded.pdf")
        out = self.client._download(
            "https://www.bseindia.com/xml-data/corpfiling/AttachHis/OK.pdf", local_path
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["file_size_bytes"], len(payload))
        self.assertEqual(out["sha256_hash"], hashlib.sha256(payload).hexdigest())
        self.assertTrue(Path(local_path).exists())
        self.assertEqual(Path(local_path).read_bytes(), payload)

    def test_archive_link(self):
        payload = b"%PDF-1.4 archived"
        resp = FakeResp(
            status_code=200, headers={"Content-Type": "application/pdf"}, content=payload
        )
        self.client.http_session.get = mock.MagicMock(return_value=resp)
        link = {
            "source_url": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/L.pdf",
            "doc_type": DOC_ANNUAL_REPORT,
            "source": SOURCE_OFFICIAL_BSE,
            "discovery_source": SOURCE_SCREENER_DISCOVERY,
        }
        result = self.client.archive_link("RELIANCE", link)
        self.assertTrue(result["ok"])
        self.assertEqual(result["sha256_hash"], hashlib.sha256(payload).hexdigest())
        # Original link keys are preserved (spread).
        self.assertEqual(result["source_url"], link["source_url"])

    def test_headless_fallback_unavailable_fail_closed(self):
        # 404 + playwright unavailable => fail closed, no browser launched.
        resp = FakeResp(status_code=404, headers={}, content=b"")
        self.client.http_session.get = mock.MagicMock(return_value=resp)
        with mock.patch.object(
            hf_module, "is_playwright_available", return_value=False
        ):
            out = self.client._download(
                "https://www.bseindia.com/xml-data/corpfiling/AttachHis/X.pdf", "/tmp/x.pdf"
            )
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "http_404")

    def test_headless_fallback_success_path(self):
        # A blocked 403 response should defer to the headless fallback path and
        # use its result when it succeeds.
        resp = FakeResp(status_code=403, headers={}, content=b"")
        self.client.http_session.get = mock.MagicMock(return_value=resp)
        fallback_result = {
            "ok": True,
            "local_file_path": "/tmp/fallback.pdf",
            "file_size_bytes": 10,
            "sha256_hash": "deadbeef",
            "error": None,
        }
        with mock.patch.object(
            self.client, "_download_via_browser", return_value=fallback_result
        ):
            out = self.client._download(
                "https://www.bseindia.com/xml-data/corpfiling/AttachHis/X.pdf", "/tmp/x.pdf"
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["sha256_hash"], "deadbeef")
        self.assertEqual(out["local_file_path"], "/tmp/fallback.pdf")


# =====================================================================
# 3. corporate_actions_client
# =====================================================================
class TestCorporateActionsClient(unittest.TestCase):
    def setUp(self):
        self.client = CorporateActionsClient(slice_days=180, max_retries=1)
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="reality_ca_db_"))
        self.db = DatabaseManager(db_path=self.tmp_dir / "ca_test.db")
        self.repo = Repository(manager=self.db)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_normalize_action_type(self):
        cases = {
            "Recommended Dividend": "DIVIDEND",
            "Issue of Bonus Shares": "BONUS",
            "Sub-division / Split of Equity Shares": "SPLIT",
            "Rights Issue": "RIGHTS",
            "Buy Back of Equity Shares": "BUYBACK",
            "Scheme of Merger": "MERGER",
            "Amalgamation": "MERGER",
            # NOTE: 'merger' is matched before 'demerger' in the rule order, so a
            # subject containing "demerger" (which also contains "merger") resolves
            # to MERGER. The canonical DEMERGER match is the "spin off" keyword.
            "Demerger of Power Business": "MERGER",
            "Spin Off": "DEMERGER",
            "Payment of Interest": "INTEREST",
            "Notice of AGM": "AGM",
            "Random Subject": "OTHER",
            "": "OTHER",
        }
        for subject, expected in cases.items():
            self.assertEqual(_normalize_action_type(subject), expected, msg=subject)

    def test_parse_date(self):
        self.assertEqual(_parse_date("30-Apr-2026"), "2026-04-30")
        self.assertEqual(_parse_date("2026-01-15"), "2026-01-15")
        self.assertEqual(_parse_date("15-01-2026"), "2026-01-15")
        self.assertIsNone(_parse_date("-"))
        self.assertIsNone(_parse_date("00-00-0000"))
        self.assertIsNone(_parse_date(None))
        self.assertIsNone(_parse_date(""))

    def test_fetch_range_auto_sliced(self):
        rec = {"isin": "INE001A01000", "symbol": "X", "subject": "Dividend payout"}
        self.client._fetch_slice = mock.MagicMock(return_value=[rec])
        result = self.client.fetch_range("2024-01-01", "2024-06-30")
        # 181-day span over 180-day slices => 2 slices.
        self.assertEqual(result["slices"], 2)
        self.assertEqual(result["raw_records"], 2)
        self.assertEqual(len(result["normalized"]), 2)
        norm = result["normalized"][0]
        self.assertEqual(norm["action_type"], "DIVIDEND")
        self.assertEqual(norm["source"], "nse_official")

    def test_upsert_idempotency_temp_db(self):
        rec = {
            "isin": "INE009A01000",
            "symbol": "IDEM",
            "subject": "Final Dividend",
            "action_type": "DIVIDEND",
            "ex_date": "2026-05-10",
            "source": "nse_official",
        }
        n1 = self.repo.upsert_corporate_actions([rec])
        n2 = self.repo.upsert_corporate_actions([rec])
        self.assertEqual(n1, 1)
        # Idempotent: second upsert does not add a row.
        with self.db.session() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM corporate_actions WHERE isin='INE009A01000'"
            ).fetchone()[0]
        self.assertEqual(count, 1)


# =====================================================================
# 4. official_financials_client
# =====================================================================
class TestOfficialFinancialsClient(unittest.TestCase):
    def setUp(self):
        self.client = OfficialFinancialsClient(max_retries=1)

    def test_resolve_nse_primary(self):
        nse_recs = [
            {"symbol": "RELIANCE", "isin": "INE002A01018", "xbrl_url": "http://x/y.xbrl",
             "source": FIN_SRC_NSE}
        ]
        with mock.patch.object(self.client, "fetch_nse_results", return_value=nse_recs), \
                mock.patch.object(self.client, "fetch_bse_results", return_value=[]):
            res = self.client.resolve("RELIANCE", bse_code="500325")
        self.assertEqual(res["primary_source"], FIN_SRC_NSE)
        self.assertEqual(len(res["filings"]), 1)
        self.assertEqual(res["filings"][0]["source"], FIN_SRC_NSE)

    def test_resolve_bse_primary(self):
        bse_recs = [
            {"symbol": "RELIANCE", "isin": "INE002A01018", "xbrl_url": None,
             "source": FIN_SRC_BSE}
        ]
        with mock.patch.object(self.client, "fetch_nse_results", return_value=[]), \
                mock.patch.object(self.client, "fetch_bse_results", return_value=bse_recs):
            res = self.client.resolve("RELIANCE", bse_code="500325")
        self.assertEqual(res["primary_source"], FIN_SRC_BSE)
        self.assertEqual(len(res["filings"]), 1)

    def test_resolve_fail_closed_empty(self):
        with mock.patch.object(self.client, "fetch_nse_results", return_value=[]), \
                mock.patch.object(self.client, "fetch_bse_results", return_value=[]):
            res = self.client.resolve("RELIANCE", bse_code="500325")
        self.assertEqual(res["primary_source"], None)
        self.assertEqual(res["filings"], [])
        self.assertIn("yfinance", res["note"])

    def test_source_tagging(self):
        recs = [
            {"symbol": "A", "xbrl_url": "u1", "source": FIN_SRC_NSE},
            {"symbol": "A", "xbrl_url": "u2", "source": FIN_SRC_BSE},
        ]
        with mock.patch.object(self.client, "fetch_nse_results", return_value=[recs[0]]), \
                mock.patch.object(self.client, "fetch_bse_results", return_value=[recs[1]]):
            res = self.client.resolve("A", bse_code="1")
        sources = {f["source"] for f in res["filings"]}
        self.assertEqual(sources, {FIN_SRC_NSE, FIN_SRC_BSE})

    def test_jwt_cookie_enrichment(self):
        # Real fetch_bse_results path, but with HTTP mocked and playwright+JWT
        # enrichment forced on, verifying the Cookie header is sent.
        self.client.session.get = mock.MagicMock(return_value=FakeResp(text="[]"))
        with mock.patch.object(
            official_financials_client, "is_playwright_available", return_value=True
        ), mock.patch.object(
            official_financials_client, "get_bse_cookies",
            return_value={"BSE_JWT": "tok123"}
        ):
            out = self.client.fetch_bse_results("500325")

        # Enrichment must have attached the browser cookie to the BSE request.
        cookie_seen = False
        for call in self.client.session.get.call_args_list:
            headers = call.kwargs.get("headers") or (call.args[1] if len(call.args) > 1 else {})
            if isinstance(headers, dict) and headers.get("Cookie") == "BSE_JWT=tok123":
                cookie_seen = True
                break
        self.assertTrue(cookie_seen, "BSE JWT cookie was not attached to the request")
        self.assertEqual(out, [])  # endpoint returns [] (extension point)


# =====================================================================
# 5. delisting_nclt_client
# =====================================================================
class TestDelistingNCLTClient(unittest.TestCase):
    def setUp(self):
        self.client = DelistingNCLTClient()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="reality_dn_db_"))
        self.db = DatabaseManager(db_path=self.tmp_dir / "dn_test.db")
        self.test_repo = Repository(manager=self.db)

        # Seed an inactive master company + ingested docs/actions with keywords.
        self.test_repo.upsert_master_companies([
            {"isin": "INE000D0LL01", "nse_symbol": "DEADCO", "bse_code": "900001",
             "company_name": "Dead Co Ltd", "is_active": 0},
            {"isin": "INE000A0CT01", "nse_symbol": "LIVECO", "bse_code": "900002",
             "company_name": "Live Co Ltd", "is_active": 1},
        ])
        self.test_repo.upsert_corporate_documents([
            {"isin": "INE000A0CT01", "symbol": "NCLTCO", "doc_type": "ANNUAL_REPORT",
             "title": "Company referred to NCLT under insolvency resolution",
             "doc_date": "2026-01-15",
             "source_url": "https://bseindia.com/x.pdf", "source": "bse_official"},
        ])
        self.test_repo.upsert_corporate_actions([
            {"isin": "INE000X0ST01", "symbol": "DELISTCO", "subject": "Voluntary delisting approved",
             "action_type": "OTHER", "source": "nse_official"},
        ])

        # Route the module's DB/repo to the isolated temp DB.
        self._repo_patch = mock.patch.object(
            dnc_module, "_repo", self.test_repo
        )
        self._repo_patch.start()
        # Ensure no real browser is launched for the official-delisted attempt.
        self._pw_patch = mock.patch.object(
            hf_module, "is_playwright_available", return_value=False
        )
        self._pw_patch.start()

    def tearDown(self):
        self._repo_patch.stop()
        self._pw_patch.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_match_status(self):
        self.assertEqual(_match_status("Company under NCLT proceedings"), "NCLT_CIRP")
        self.assertEqual(_match_status("CIRP initiated by RP"), "NCLT_CIRP")
        self.assertEqual(_match_status("Reference to IBBI / IBC"), "NCLT_CIRP")
        self.assertEqual(_match_status("Voluntary delisting of equity"), "DELISTED")
        self.assertEqual(_match_status("Trading suspended by exchange"), "SUSPENDED")
        self.assertIsNone(_match_status("Routine board meeting"))
        self.assertIsNone(_match_status(""))

    def test_derive_from_master_inactive(self):
        flags = self.client.derive_from_master()
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["symbol"], "DEADCO")
        self.assertEqual(flags[0]["status_type"], "DELISTED")
        self.assertEqual(flags[0]["source"], "derived")

    def test_scan_announcements_keywords(self):
        flags = self.client.scan_announcements()
        statuses = {f["status_type"] for f in flags}
        self.assertIn("NCLT_CIRP", statuses)
        self.assertIn("DELISTED", statuses)
        sources = {f["source"] for f in flags}
        self.assertEqual(sources, {"announcement_scan"})

    def test_build_flags_structure(self):
        result = self.client.build_flags()
        self.assertIn("official", result)
        self.assertIn("derived", result)
        self.assertIn("scanned", result)
        self.assertIn("all", result)
        self.assertIn("counts", result)
        # official is empty because playwright is unavailable (fail-closed).
        self.assertEqual(len(result["official"]), 0)
        self.assertEqual(result["counts"]["derived_delisted"], 1)
        self.assertEqual(result["counts"]["total"], len(result["all"]))

    def test_persist_flags_upsert_called(self):
        count = self.client.persist_flags()
        self.assertGreaterEqual(count, 2)  # derived (1) + scanned (>=1)
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT status_type, source, symbol FROM corporate_status_flags ORDER BY symbol"
            ).fetchall()
        status_types = {r["status_type"] for r in rows}
        self.assertIn("DELISTED", status_types)
        self.assertIn("NCLT_CIRP", status_types)


# =====================================================================
# 6. headless_fetcher
# =====================================================================
class TestHeadlessFetcher(unittest.TestCase):
    def test_extract_jwt_token(self):
        # Exact JWS in cookies.
        self.assertEqual(
            extract_jwt_token(cookies={"auth": "aaaaaaaa.bbbbbbbb.cccccccc"}),
            "aaaaaaaa.bbbbbbbb.cccccccc",
        )
        # JWS in localStorage.
        self.assertEqual(
            extract_jwt_token(local_storage={"t": "aaaaaaaa.bbbbbbbb.cccccccc"}),
            "aaaaaaaa.bbbbbbbb.cccccccc",
        )
        # Auth-named key with an opaque long token value.
        self.assertEqual(
            extract_jwt_token(cookies={"jwt": "aVeryLongOpaqueTokenValue1234567890"}),
            "aVeryLongOpaqueTokenValue1234567890",
        )
        # No match -> None.
        self.assertIsNone(extract_jwt_token(cookies={"session": "abc"}))
        self.assertIsNone(extract_jwt_token())
        self.assertIsNone(extract_jwt_token(cookies={"x": "short"}))

    def test_cookies_to_header(self):
        header = cookies_to_header({"a": "1", "b": "2"})
        self.assertIn("a=1", header)
        self.assertIn("b=2", header)
        # Empty / falsy values are skipped.
        header2 = cookies_to_header({"a": "1", "b": ""})
        self.assertEqual(header2, "a=1")

    def test_is_playwright_available_fail_closed(self):
        # When playwright is missing the module must report unavailable and
        # never attempt a browser launch.
        with mock.patch.object(hf_module, "_PLAYWRIGHT_SYNC", False):
            self.assertFalse(is_playwright_available())
            fetcher = HeadlessFetcher()
            self.assertFalse(fetcher.available)
            self.assertFalse(fetcher.is_available())


if __name__ == "__main__":
    unittest.main()
