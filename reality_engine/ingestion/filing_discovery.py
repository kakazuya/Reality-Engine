"""
Filing Discovery Module — Screener raw-link discovery layer.

DESIGN RULE (standing project convention):
    Screener.in is used ONLY as a *discovery* layer. It surfaces the raw official
    NSE/BSE filing URLs (annual reports, concall transcripts, investor
    presentations, XBRL) that point directly at bseindia.com / nseindia.com.
    This module MUST NEVER copy or parse Screener's rendered financial TABLES.
    Every record carries a ``source`` provenance tag pointing at the official
    exchange URL, never at Screener.

The companion module ``official_filing_client.py`` performs the actual download
and archival of those official URLs.
"""

import logging
import re
import time
from typing import Dict, Any, List, Optional
import requests

try:
    from bs4 import BeautifulSoup  # type: ignore
    _HAS_BS4 = True
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore
    _HAS_BS4 = False

from reality_engine.config import (
    DEFAULT_HEADERS,
    SCREENER_COMPANY_URL_TEMPLATE,
    SCREENER_STANDALONE_URL_TEMPLATE,
)

logger = logging.getLogger("reality_engine.filing_discovery")

# ---------------------------------------------------------------------------
# Provenance / classification constants
# ---------------------------------------------------------------------------
SOURCE_SCREENER_DISCOVERY = "screener_discovery"   # we found the link via Screener
SOURCE_OFFICIAL_BSE = "bse_official"               # the link target is bseindia.com
SOURCE_OFFICIAL_NSE = "nse_official"               # the link target is nseindia.com

DOC_ANNUAL_REPORT = "ANNUAL_REPORT"
DOC_CONCALL_TRANSCRIPT = "CONCALL_TRANSCRIPT"
DOC_INVESTOR_PRESENTATION = "INVESTOR_PRESENTATION"
DOC_FINANCIAL_RESULT = "FINANCIAL_RESULT"
DOC_OTHER_FILING = "OTHER_FILING"

# Raw official BSE filing patterns discovered on Screener pages.
# IMPORTANT: only match *document file* URLs (PDF/XBRL/XML). Navigation/quote
# pages on bseindia.com / nseindia.com are NOT filings and must be excluded.
_BSE_ATTACH_RE = re.compile(
    r"https?://(?:www\.)?bseindia\.com/xml-data/corpfiling/AttachHis/[^'\"\s?#]+\.pdf",
    re.IGNORECASE,
)
_BSE_ANN_PDF_RE = re.compile(
    r"https?://(?:www\.)?bseindia\.com/stockinfo/AnnPdfOpen\.aspx\?Pname=[^'\"\s]+\.pdf",
    re.IGNORECASE,
)
_BSE_ANNUAL_REPORT_RE = re.compile(
    r"https?://(?:www\.)?bseindia\.com/bseplus/AnnualReport/[^'\"\s]+\.pdf",
    re.IGNORECASE,
)
# NSE occasionally surfaces XBRL / corporate-results document URLs too.
_NSE_DOC_RE = re.compile(
    r"https?://(?:www\.)?nseindia\.com/(?:api|corporates|/media)[^'\"\s]*(?:xbrl|\.xml|\.pdf)",
    re.IGNORECASE,
)
# Union of all *document* URL patterns (used by the regex backstop).
_DOC_URL_PATTERNS = [_BSE_ATTACH_RE, _BSE_ANN_PDF_RE, _BSE_ANNUAL_REPORT_RE, _NSE_DOC_RE]


class FilingDiscoveryClient:
    """Discovers raw official NSE/BSE filing URLs from Screener company pages."""

    def __init__(self, rate_limit_sec: float = 1.0, max_retries: int = 3):
        self.http_session = requests.Session()
        self.http_session.headers.update(DEFAULT_HEADERS)
        self.http_session.verify = False
        self.rate_limit_sec = max(0.0, rate_limit_sec)
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Low-level fetch (rate-limited, retry-with-backoff, fail-closed)
    # ------------------------------------------------------------------
    def _get_html(self, url: str) -> Optional[str]:
        """Fetch a page with retry/backoff. Returns HTML string or None on failure.

        Fail-closed: on persistent failure (incl. HTTP 429 rate-limit) we return
        None rather than fabricating content.
        """
        backoff = self.rate_limit_sec
        for attempt in range(self.max_retries):
            try:
                resp = self.http_session.get(url, timeout=15)
                if resp.status_code == 200 and resp.text:
                    if self.rate_limit_sec:
                        time.sleep(self.rate_limit_sec)
                    return resp.text
                if resp.status_code == 429:
                    # Screener rate-limit: back off exponentially, do not hammer.
                    wait = backoff * (2 ** attempt)
                    logger.warning("Screener 429 on %s; backing off %0.1fs", url, wait)
                    time.sleep(wait)
                    continue
                logger.warning("Screener HTTP %s for %s", resp.status_code, url)
                if self.rate_limit_sec:
                    time.sleep(self.rate_limit_sec)
                return None
            except Exception as e:  # network/SSL/etc.
                logger.debug("Screener fetch error for %s: %s", url, e)
                time.sleep(backoff * (2 ** attempt))
        return None

    # ------------------------------------------------------------------
    # Link extraction (NO table parsing — only anchors/hrefs)
    # ------------------------------------------------------------------
    @staticmethod
    def _classify(url: str, context: str = "") -> str:
        """Classify a filing by URL pattern first, then by nearby anchor/text context.

        Screener embeds raw BSE UUID PDFs whose URLs carry no descriptive word,
        so we fall back to the link's surrounding text (e.g. 'Annual Report',
        'Concall', 'Investor Presentation') for an accurate doc_type.
        """
        low_url = url.lower()
        low_ctx = (context or "").lower()
        blob = low_url + " " + low_ctx
        if "annualreport" in low_url or "bseplus" in low_url:
            return DOC_ANNUAL_REPORT
        if "concall" in blob or "transcript" in blob:
            return DOC_CONCALL_TRANSCRIPT
        if "presentation" in low_ctx or "investor" in low_ctx:
            return DOC_INVESTOR_PRESENTATION
        if "annual" in low_ctx:
            return DOC_ANNUAL_REPORT
        if "result" in blob or "financial" in low_ctx:
            return DOC_FINANCIAL_RESULT
        return DOC_OTHER_FILING

    @staticmethod
    def _provenance(url: str) -> str:
        if _BSE_ATTACH_RE.match(url) or _BSE_ANN_PDF_RE.match(url) or _BSE_ANNUAL_REPORT_RE.match(url):
            return SOURCE_OFFICIAL_BSE
        if _NSE_DOC_RE.match(url):
            return SOURCE_OFFICIAL_NSE
        if "bseindia.com" in url.lower():
            return SOURCE_OFFICIAL_BSE
        if "nseindia.com" in url.lower():
            return SOURCE_OFFICIAL_NSE
        return SOURCE_SCREENER_DISCOVERY

    def _extract_official_links(self, html: str) -> List[Dict[str, str]]:
        """Pull every official BSE/NSE PDF/XBRL href from the raw HTML.

        We deliberately scan the full HTML for official-exchange URL patterns
        instead of parsing Screener's tables. This avoids ingesting any Screener
        computed metric and only harvests the raw filing destinations. Each hit
        is returned with a ``context`` string (anchor text / nearby heading) used
        for accurate doc_type classification.
        """
        found: List[Dict[str, str]] = []
        seen = set()

        # 1) BeautifulSoup anchor sweep (preferred: captures link text for typing).
        if _HAS_BS4:
            try:
                soup = BeautifulSoup(html, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    # Only accept real *document* URLs; skip navigation/quote pages.
                    is_doc = any(p.match(href) for p in _DOC_URL_PATTERNS)
                    if not is_doc:
                        continue
                    if href.startswith("//"):
                        href = "https:" + href
                    norm = href.split("#")[0].rstrip("/")
                    if norm in seen:
                        continue
                    seen.add(norm)
                    # Context: anchor text + nearest heading/parent label.
                    ctx = a.get_text(" ", strip=True)
                    parent = a.find_parent(["h1", "h2", "h3", "h4", "li", "td", "th"])
                    if parent and not ctx:
                        ctx = parent.get_text(" ", strip=True)
                    found.append({"url": norm, "context": ctx})
            except Exception as e:  # pragma: no cover
                logger.debug("BeautifulSoup anchor sweep failed: %s", e)

        # 2) Regex backstop over the whole document (covers inline data-/JS URLs
        #    that BeautifulSoup may miss). Context left blank -> URL-only typing.
        for pat in _DOC_URL_PATTERNS:
            for m in pat.finditer(html):
                u = m.group(0).split("#")[0].rstrip("'\"\\/")
                if u not in seen:
                    seen.add(u)
                    found.append({"url": u, "context": ""})

        return found

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def discover_filings(
        self, symbol: str, bse_code: Optional[str] = None, consolidated: bool = True
    ) -> Dict[str, Any]:
        """Discover raw official filing links for one symbol.

        Returns a record shaped for ``official_filing_client`` consumption::

            {
                "symbol": str,
                "bse_code": str | None,
                "discovered_at": ISO date,
                "links": [
                    {
                        "source_url": <official bse/nse url>,
                        "doc_type": DOC_*,
                        "source": SOURCE_OFFICIAL_BSE | SOURCE_OFFICIAL_NSE,
                        "discovery_source": "screener_discovery",
                    }, ...
                ],
                "error": str | None,
            }
        """
        from datetime import datetime

        clean_sym = symbol.strip().upper()
        url = (
            SCREENER_COMPANY_URL_TEMPLATE.format(symbol=clean_sym)
            if consolidated
            else SCREENER_STANDALONE_URL_TEMPLATE.format(symbol=clean_sym)
        )
        html = self._get_html(url)
        if not html:
            return {
                "symbol": clean_sym,
                "bse_code": bse_code,
                "discovered_at": datetime.now().strftime("%Y-%m-%d"),
                "links": [],
                "error": "screener_unreachable_or_rate_limited",
            }

        raw_links = self._extract_official_links(html)
        links: List[Dict[str, Any]] = []
        for item in raw_links:
            u = item["url"]
            ctx = item.get("context", "")
            links.append(
                {
                    "source_url": u,
                    "doc_type": self._classify(u, ctx),
                    "source": self._provenance(u),
                    "discovery_source": SOURCE_SCREENER_DISCOVERY,
                }
            )

        # De-duplicate by URL while preserving order.
        deduped = []
        seen_urls = set()
        for ln in links:
            if ln["source_url"] not in seen_urls:
                seen_urls.add(ln["source_url"])
                deduped.append(ln)

        return {
            "symbol": clean_sym,
            "bse_code": bse_code,
            "discovered_at": datetime.now().strftime("%Y-%m-%d"),
            "links": deduped,
            "error": None,
        }


# Singleton
filing_discovery_client = FilingDiscoveryClient()
