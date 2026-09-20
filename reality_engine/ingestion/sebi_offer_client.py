"""SEBI offer-document client: DRHP / Prospectus discovery + PDF resolution.

Two-stage flow (both verified live 2026-09-20, no browser, no auth):

1. ``search`` — POST ``sebiweb/ajax/home/getnewslistinfo.jsp`` with the same
   form fields the listing page's ``searchFormNewsList`` sends. Requires the
   ``JSESSIONID`` cookie from a prior GET of the listing page plus
   ``X-Requested-With: XMLHttpRequest`` — a bare POST answers 530
   "Unauthorized Activity Has Been Detected". Returns filing-page URLs
   (``/filings/public-issues/<mon-yyyy>/<slug>_<id>.html``).
2. ``resolve_pdf`` — GET the filing page, extract the ``sebi_data/attachdocs/``
   PDF behind the viewer ``iframe`` (verified: ``HEAD -> 200
   application/pdf``). The PDF is fetched directly, never through the viewer.

Stages: ``draft`` (ssid=15/smid=10, DRHP) and ``final`` (ssid=15/smid=12,
Prospectus / Red Herring). ``discover_offer_documents`` returns a record
shaped exactly like ``filing_discovery.discover_filings`` so
``official_filing_client.archive_link`` consumes it unchanged.

Fail-closed throughout: any network/parse miss returns ``[]`` / ``None`` /
an ``error`` record. Never raises, never synthesizes a URL.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("reality_engine.sebi_offer_client")

SOURCE_SEBI_OFFICIAL = "sebi_official"
DISCOVERY_SOURCE = "sebi_offer_search"
DOC_OFFER_DOCUMENT = "OFFER_DOCUMENT"

BASE = "https://www.sebi.gov.in"
LISTING_URL = BASE + "/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid={smid}"
AJAX_URL = BASE + "/sebiweb/ajax/home/getnewslistinfo.jsp"

# sid=3 (Filings) / ssid=15 (Public Issues); smid selects the document stage.
STAGES = {
    "draft": {"ssid": "15", "smid": "10", "sm_text": "Draft Offer Documents filed with SEBI"},
    "final": {"ssid": "15", "smid": "12", "sm_text": "Final Offer Documents filed with ROC"},
}

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_FILING_LINK_RE = re.compile(
    r'href=["\']([^"\']*?/filings/public-issues/[^"\']*?\.html)["\'][^>]*>([^<]{0,150})',
    re.IGNORECASE,
)
_ROW_DATE_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\s*([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
_PDF_RE = re.compile(r"sebi_data/attachdocs/[^'\"\s<>]+\.pdf", re.IGNORECASE)
# Filing slugs look like "...-prospectus_96778.html" / "...-drhp_12345.html".
_ID_RE = re.compile(r"_(\d{4,})\.html$", re.IGNORECASE)

RATE_LIMIT_SEC = 1.0


def _stage_key(stage: str) -> Optional[str]:
    key = (stage or "").strip().lower()
    return key if key in STAGES else None


def _title_stage(title: str) -> str:
    low = (title or "").lower()
    if "drhp" in low or "draft" in low:
        return "draft"
    if "prospectus" in low or "red herring" in low or "rhp" in low:
        return "final"
    return "unknown"


class SebiOfferClient:
    """Discovers SEBI DRHP/Prospectus filings and resolves their PDFs."""

    def __init__(self, rate_limit_sec: float = RATE_LIMIT_SEC):
        self.http_session = requests.Session()
        self.http_session.headers.update(
            {
                "User-Agent": _BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.rate_limit_sec = max(0.0, rate_limit_sec)

    # ------------------------------------------------------------------
    # 1. Search (ajax listing)
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        stage: str = "final",
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search one stage's listing; each hit is ``{title, filing_page_url,
        doc_date, stage}``. Fail-closed: ``[]`` on any miss."""
        key = _stage_key(stage)
        if key is None:
            logger.warning("sebi_offer_client: unknown stage %r", stage)
            return []
        query = (query or "").strip()
        if not query:
            return []
        cfg = STAGES[key]
        try:
            # Establishes the JSESSIONID cookie the ajax endpoint requires.
            self.http_session.get(LISTING_URL.format(smid=cfg["smid"]), timeout=30)
            data = {
                "nextValue": "1",
                "next": "s",
                "search": query,
                "fromDate": "",
                "toDate": "",
                "fromYear": "",
                "toYear": "",
                "deptId": "-1",
                "sid": "3",
                "ssid": cfg["ssid"],
                "smid": cfg["smid"],
                "ssidhidden": cfg["ssid"],
                "intmid": "-1",
                "sText": "Filings",
                "ssText": "Public Issues",
                "smText": cfg["sm_text"],
                "doDirect": "-1",
            }
            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Referer": LISTING_URL.format(smid=cfg["smid"]),
                "Origin": BASE,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }
            resp = self.http_session.post(AJAX_URL, data=data, headers=headers, timeout=30)
            if self.rate_limit_sec:
                time.sleep(self.rate_limit_sec)
            if resp.status_code != 200:
                logger.warning("sebi_offer_client: ajax HTTP %s for %r", resp.status_code, query)
                return []
            return self._parse_search_html(resp.text or "", key, max_results)
        except Exception as exc:
            logger.warning("sebi_offer_client: search miss for %r: %s", query, exc)
            return []

    @staticmethod
    def _parse_search_html(html: str, stage: str, max_results: int) -> List[Dict[str, Any]]:
        """Parse ajax rows into filing hits. Pure function — unit-tested."""
        if not html or "public-issues" not in html.lower():
            return []
        # Row dates precede their row's link; pair positionally.
        dates = _ROW_DATE_RE.findall(html)
        links = _FILING_LINK_RE.findall(html)
        hits: List[Dict[str, Any]] = []
        for i, (href, title) in enumerate(links):
            title = (title or "").strip()
            if not title:
                continue
            url = href if href.lower().startswith("http") else BASE + href
            doc_date: Optional[str] = None
            if i < len(dates):
                try:
                    doc_date = datetime.strptime(dates[i].strip(), "%b %d, %Y").strftime("%Y-%m-%d")
                except ValueError:
                    doc_date = None
            hits.append(
                {
                    "title": title,
                    "filing_page_url": url,
                    "doc_date": doc_date,
                    "stage": _title_stage(title) if stage == "unknown" else stage,
                }
            )
            if len(hits) >= max(1, max_results):
                break
        return hits

    def _ajax_post(self, data: Dict[str, Any], smid: str) -> Optional[str]:
        """POST the ajax listing endpoint; body text or None on any miss."""
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": LISTING_URL.format(smid=smid),
            "Origin": BASE,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        try:
            resp = self.http_session.post(AJAX_URL, data=data, headers=headers, timeout=30)
        except Exception as exc:
            logger.warning("sebi_offer_client: ajax post miss: %s", exc)
            return None
        if self.rate_limit_sec:
            time.sleep(self.rate_limit_sec)
        if resp.status_code != 200:
            logger.warning("sebi_offer_client: ajax HTTP %s", resp.status_code)
            return None
        return resp.text or ""

    def _listing_form(self, stage_key: str) -> Dict[str, Any]:
        """Base ajax form fields for one stage (search/page overrides applied by callers)."""
        cfg = STAGES[stage_key]
        return {
            "nextValue": "1",
            "next": "s",
            "search": "",
            "fromDate": "",
            "toDate": "",
            "fromYear": "",
            "toYear": "",
            "deptId": "-1",
            "sid": "3",
            "ssid": cfg["ssid"],
            "smid": cfg["smid"],
            "ssidhidden": cfg["ssid"],
            "intmid": "-1",
            "sText": "Filings",
            "ssText": "Public Issues",
            "smText": cfg["sm_text"],
            "doDirect": "-1",
        }

    def crawl_listing(
        self,
        stage: str = "final",
        max_pages: int = 0,
    ) -> List[Dict[str, Any]]:
        """Crawl a whole stage listing page-by-page (no search term).

        ``max_pages=0`` means all pages (63 final + 89 draft as of Sep 2026).
        Each record is ``{title, filing_page_url, doc_date, stage}``. Dedup by
        filing-page URL; stops when a page yields no ``public-issues`` links.
        Fail-closed: ``[]`` when even page 1 misses.
        """
        key = _stage_key(stage)
        if key is None:
            logger.warning("sebi_offer_client: unknown stage %r", stage)
            return []
        cfg = STAGES[key]
        try:
            self.http_session.get(LISTING_URL.format(smid=cfg["smid"]), timeout=30)
        except Exception as exc:
            logger.warning("sebi_offer_client: listing warmup miss: %s", exc)
            return []
        records: List[Dict[str, Any]] = []
        seen: set = set()
        page = 1
        while True:
            if max_pages and page > max_pages:
                break
            form = self._listing_form(key)
            form["nextValue"] = str(page)
            if page == 1:
                form["next"] = "s"
                form["doDirect"] = "-1"
            else:
                form["next"] = "n"
                form["doDirect"] = str(page - 1)
            body = self._ajax_post(form, cfg["smid"])
            if body is None:
                break
            hits = self._parse_search_html(body, key, max_results=10_000)
            fresh = [h for h in hits if h["filing_page_url"] not in seen]
            if not fresh:
                break
            for h in fresh:
                seen.add(h["filing_page_url"])
            records.extend(fresh)
            page += 1
        return records

    # ------------------------------------------------------------------
    # 2. PDF resolution (filing page -> direct attachdocs PDF)
    # ------------------------------------------------------------------
    def resolve_pdf_url(self, filing_page_url: str) -> Optional[str]:
        """GET a filing page, return the direct ``attachdocs`` PDF URL or None."""
        if not filing_page_url:
            return None
        try:
            resp = self.http_session.get(filing_page_url, timeout=30)
            if self.rate_limit_sec:
                time.sleep(self.rate_limit_sec)
            if resp.status_code != 200:
                logger.warning(
                    "sebi_offer_client: filing page HTTP %s (%s)",
                    resp.status_code, filing_page_url,
                )
                return None
            return self._parse_pdf_url(resp.text or "")
        except Exception as exc:
            logger.warning("sebi_offer_client: resolve miss for %s: %s", filing_page_url, exc)
            return None

    @staticmethod
    def _parse_pdf_url(html: str) -> Optional[str]:
        """First ``sebi_data/attachdocs/*.pdf`` ref, absolutized. Pure — tested."""
        m = _PDF_RE.search(html or "")
        if not m:
            return None
        ref = m.group(0)
        if ref.lower().startswith("http"):
            return ref
        return BASE + "/" + ref.lstrip("/")

    # ------------------------------------------------------------------
    # 3. Discovery record (filing_discovery shape -> official_filing_client)
    # ------------------------------------------------------------------
    def discover_offer_documents(
        self,
        symbol: str,
        company_name: Optional[str] = None,
        stage: str = "both",
        max_results: int = 10,
    ) -> Dict[str, Any]:
        """Search SEBI listings and shape hits for ``official_filing_client``.

        ``stage`` is ``draft`` | ``final`` | ``both``. ``query`` prefers the
        full company name (the listing searches titles, not tickers) and falls
        back to the symbol. Never raises.
        """
        clean_sym = (symbol or "").strip().upper() or "UNKNOWN"
        queries = [q for q in ((company_name or "").strip(), clean_sym) if q]
        requested = (stage or "").strip().lower()
        stages = ("draft", "final") if requested in ("both", "", "all") else ((requested,) if requested in STAGES else ())
        if not stages:
            logger.warning("sebi_offer_client: unknown stage %r", stage)
            return {
                "symbol": clean_sym, "discovered_at": datetime.now().strftime("%Y-%m-%d"),
                "links": [], "error": f"unknown_stage:{stage}",
            }
        links: List[Dict[str, Any]] = []
        seen: set = set()
        error: Optional[str] = None
        for st in stages:
            for q in queries:
                try:
                    hits = self.search(q, stage=st, max_results=max_results)
                except Exception as exc:  # search is fail-closed; belt and braces
                    logger.debug("sebi_offer_client: search note %s: %s", q, exc)
                    continue
                for h in hits:
                    pdf = self.resolve_pdf_url(h["filing_page_url"])
                    if not pdf or pdf in seen:
                        continue
                    seen.add(pdf)
                    links.append(
                        {
                            "source_url": pdf,
                            "doc_type": DOC_OFFER_DOCUMENT,
                            "source": SOURCE_SEBI_OFFICIAL,
                            "discovery_source": DISCOVERY_SOURCE,
                            "title": h["title"],
                            "doc_date": h.get("doc_date"),
                            "filing_page_url": h["filing_page_url"],
                            "offer_stage": h.get("stage", st),
                        }
                    )
                if links:
                    break  # company-name query hit; symbol fallback unneeded
            if self.rate_limit_sec:
                time.sleep(self.rate_limit_sec)
        if not links:
            error = "no_offer_documents_found"
        return {
            "symbol": clean_sym,
            "company_name": (company_name or "").strip() or None,
            "discovered_at": datetime.now().strftime("%Y-%m-%d"),
            "links": links,
            "error": error,
        }


# Singleton
sebi_offer_client = SebiOfferClient()
