"""
Official Financials Client — source-resolver for canonical NSE/BSE numeric financials.

This module is the *official* financials ingestion path. It resolves, in priority order:
    1. NSE financial-results feed (filing metadata + XBRL URLs)   [PRIMARY, official]
    2. BSE corporate results XBRL                                 [SECONDARY, official]
    3. yfinance                                                   [TERTIARY fallback only]

It is intentionally FAIL-CLOSED: if no official source yields data for a symbol, the
caller (fundamentals_client) returns an EMPTY record rather than synthesizing numbers.

PROVENANCE / INTEGRITY RULES (standing project conventions):
    * We never copy derived/displayed tables from Screener as the canonical dataset.
    * The canonical archive is the raw official NSE/BSE filing (XBRL/standalone).
    * Every normalized row carries a ``source`` tag (nse_official / bse_official /
      yfinance) so downstream consumers know exactly where each number came from.
    * No synthetic defaults are ever produced here.

LIVE-FEED STATUS (probed 2026-08-28):
    * NSE financial-results API responded 200 but returned an empty array for the
      probed ranges — likely seasonal/parameter dependent. The adapter is wired and
      activates automatically when the feed returns records.
    * BSE ComWinQuery/results endpoints return an HTML error page without the
      browser-issued JWT cookie, so they are not bulk-reachable from this environment
      yet. The adapter is wired and fails closed (returns nothing) until reachable.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from curl_cffi import requests as _requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    import requests as _requests  # type: ignore
    _HAS_CURL_CFFI = False

from reality_engine.config import NSE_HEADERS, BSE_HEADERS
from reality_engine.ingestion.headless_fetcher import (
    get_bse_cookies,
    cookies_to_header,
    is_playwright_available,
)

logger = logging.getLogger("reality_engine.official_financials_client")

SOURCE_NSE = "nse_official"
SOURCE_BSE = "bse_official"
SOURCE_YFINANCE = "yfinance"


class OfficialFinancialsClient:
    """Resolves official NSE/BSE financials for a single symbol, fail-closed."""

    def __init__(self, max_retries: int = 2):
        if _HAS_CURL_CFFI:
            self.session = _requests.Session(impersonate="chrome120", verify=False)  # type: ignore[call-arg]
        else:
            self.session = _requests.Session()
            try:
                self.session.verify = False  # type: ignore[attr-defined]
            except Exception:
                pass
        self.session.headers.update(NSE_HEADERS)
        self._warmed = False
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # 1. NSE financial-results (PRIMARY)
    # ------------------------------------------------------------------
    def _warmup(self):
        if not self._warmed:
            try:
                self.session.get("https://www.nseindia.com", timeout=10)
                self._warmed = True
            except Exception as e:  # pragma: no cover
                logger.warning("NSE warmup note: %s", e)

    def fetch_nse_results(self, symbol: str, bse_code: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch NSE financial-results filing metadata + XBRL URLs for a symbol.

        Returns a list of normalized filing-metadata records (NOT parsed XBRL numbers
        yet — that requires an XBRL parser fed by the returned URLs). Fail-closed.
        """
        self._warmup()
        # NSE financial-results is a market-wide incremental feed; query by date and
        # filter to the requested symbol. Use a rolling window to bound the range.
        from datetime import timedelta
        to_d = datetime.now()
        from_d = to_d - timedelta(days=400)
        url = (
            "https://www.nseindia.com/api/corporates-financial-results"
            "?index=equities"
            f"&from_date={from_d.strftime('%d-%m-%Y')}&to_date={to_d.strftime('%d-%m-%Y')}"
        )
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                logger.debug("NSE financial-results HTTP %s for %s", resp.status_code, symbol)
                return []
            payload = resp.json()
            rows = payload if isinstance(payload, list) else payload.get("data", [])
            out: List[Dict[str, Any]] = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                sym = (r.get("symbol") or "").upper()
                if sym and sym != symbol.upper():
                    continue
                out.append({
                    "symbol": sym or symbol.upper(),
                    "isin": r.get("isin"),
                    "company_name": r.get("comp"),
                    "period": r.get("period"),
                    "result_date": r.get("resultDate") or r.get("broadcastDate"),
                    "xbrl_url": r.get("xbrl") or r.get("url") or r.get("attachmentUrl"),
                    "source": SOURCE_NSE,
                })
            return out
        except Exception as e:
            logger.debug("NSE financial-results fetch error for %s: %s", symbol, e)
            return []

    # ------------------------------------------------------------------
    # 2. BSE corporate results (SECONDARY) — needs browser JWT; fail-closed
    # ------------------------------------------------------------------
    def fetch_bse_results(self, bse_code: str) -> List[Dict[str, Any]]:
        """Fetch BSE corporate results for a scrip code.

        NOTE: The BSE ComWinQuery/results endpoints return an HTML error page without
        the browser-issued JWT cookie, so this is not bulk-reachable from this
        environment yet. Wired and fail-closed; returns [] until reachable.
        """
        if not bse_code:
            return []
        url = (
            "https://api.bseindia.com/BseIndiaAPI/api/ComWinQuery/w"
            f"?CompanyCode={bse_code}&QRType=Q&FromDate=&ToDate="
        )
        # OPTIONAL browser-cookie enrichment (fail-closed). When Playwright is
        # available we replay the browser-issued BSE cookie/JWT so the endpoint is
        # no longer blocked. If unavailable or empty, behaviour is unchanged.
        headers = dict(BSE_HEADERS)
        if is_playwright_available():
            bse_cookies = get_bse_cookies()
            if bse_cookies:
                headers["Cookie"] = cookies_to_header(bse_cookies)
        try:
            resp = self.session.get(url, headers=headers, timeout=20)
            txt = resp.text.strip()
            if not txt or txt.startswith("<!DOCTYPE") or txt.startswith("<html"):
                logger.debug("BSE results endpoint returned non-JSON (needs JWT) for %s", bse_code)
                return []
            # If reachable, parse and normalize here. Left as extension point.
            return []
        except Exception as e:
            logger.debug("BSE results fetch error for %s: %s", bse_code, e)
            return []

    # ------------------------------------------------------------------
    # 3. Source-resolver entry point
    # ------------------------------------------------------------------
    def resolve(self, symbol: str, bse_code: Optional[str] = None) -> Dict[str, Any]:
        """Resolve official financials metadata for one symbol.

        Returns::
            {
                "symbol": str,
                "filings": [ ... NSE/BSE filing-metadata records ... ],
                "primary_source": "nse_official" | "bse_official" | None,
                "xbrl_urls": [ ... ],
                "note": str,
            }
        Fail-closed: filings may be empty; never synthesizes numbers.
        """
        nse = self.fetch_nse_results(symbol, bse_code)
        bse = self.fetch_bse_results(bse_code) if bse_code else []
        filings = nse + bse
        primary = SOURCE_NSE if nse else (SOURCE_BSE if bse else None)
        xbrl = [f["xbrl_url"] for f in filings if f.get("xbrl_url")]
        note = (
            "official feed returned filings" if filings
            else "no official NSE/BSE financials reachable this session; "
                 "yfinance tertiary fallback applies in fundamentals_client"
        )
        return {
            "symbol": symbol.upper(),
            "filings": filings,
            "primary_source": primary,
            "xbrl_urls": xbrl,
            "note": note,
        }


def discover_microcap_official_filing_candidates(limit: int = 12, repo=None):
    """Identify operating microcaps missing annual_financials for official filing recovery.

    Delegates to repository helper (operating-equity filter). No network I/O.
    Returns up to *limit* candidates (default 12) ordered by nse_symbol ASC.
    Never fabricates zeros; only identifies candidates for BSE/NSE XBRL fetch.
    """
    try:
        from reality_engine.db.repository import repo as _repo

        target = repo or _repo
        if hasattr(target, "discover_microcap_official_filing_candidates"):
            return target.discover_microcap_official_filing_candidates(limit=limit)
    except Exception:
        pass
    try:
        from reality_engine.processing.financial_validator import discover_microcap_official_filing_candidates as _disc
        from reality_engine.db.database import db_manager

        with db_manager.session() as conn:
            return _disc(conn, limit=limit)
    except Exception:
        return []


# Singleton
official_financials_client = OfficialFinancialsClient()
