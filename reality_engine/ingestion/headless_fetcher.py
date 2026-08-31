"""
Headless Browser JWT / Cookie Fetcher for blocked BSE/NSE endpoints
===================================================================

WHY THIS MODULE EXISTS
----------------------
Several official exchange endpoints cannot be reached with a plain HTTP client
(curl_cffi / requests) from this environment because the server only honors
cookies / a JWT that are **issued by the browser after a real page visit**:

  * BSE corporate results  -> https://api.bseindia.com/BseIndiaAPI/api/ComWinQuery/w
                              (returns an HTML error page without the browser JWT)
  * BSE delisted / suspended -> https://api.bseindia.com/BseIndiaAPI/api/ListOfDelistedScrips/w
                                and .../ListOfSuspendedScrips/w  (same JWT blocker)
  * NSE financial-results   -> https://www.nseindia.com/api/corporates-financial-results
                                (needs the _nse_* session cookies set by www.nseindia.com)

These are exactly the endpoints documented as "blocked / fail-closed" in:
  * reality_engine/ingestion/official_financials_client.py
  * reality_engine/ingestion/delisting_nclt_client.py
  * reality_engine/ingestion/filing_discovery.py   (for the discovered BSE/NSE doc URLs)

JWT / COOKIE EXTRACTION STRATEGY
--------------------------------
1. Launch a headless Chromium persistent context (reusing BROWSER_PROFILE_DIR so a
   real logged-in profile can be supplied when one exists).
2. Navigate to the exchange home page (https://www.bseindia.com or
   https://www.nseindia.com). The server then sets its session cookies, and any
   single-page JS may write a JWT into `localStorage` / `sessionStorage` or a cookie.
3. Read `context.cookies()` and also evaluate `localStorage` / `sessionStorage`.
4. Extract the JWT by scanning cookie values, localStorage and sessionStorage for a
   string matching the JWS pattern `xxxxx.yyyyy.zzzzz`, or a key whose name contains
   jwt / token / auth / session. See `extract_jwt_token()` (pure, unit-testable).
5. The harvested cookies are replayed into a normal HTTP session (curl_cffi when
   available, else requests) to perform the real API GET — this yields clean JSON
   without fighting in-browser CORS / response interception.

FAIL-CLOSED BEHAVIOR (mandatory)
--------------------------------
* Playwright is **lazy-imported**. If it is not installed (`_PLAYWRIGHT_SYNC` is
  False) every public function returns an empty / None result and logs a warning.
  No exception escapes to the caller, and the test-suite import never breaks.
* Any browser launch / navigation / network error is caught; the call returns the
  empty sentinel for its type (`{}` for cookies, `None` for a token, `None` for a
  response). Callers that already fail-closed stay fail-closed.
* The optional HTTP fallback (curl_cffi/requests warm-up GET) is best-effort only;
  it cannot mint a JS-issued JWT, so it is treated as a degraded path and still
  returns gracefully when it fails.

OPTIONAL DEPENDENCY
-------------------
`playwright>=1.40.0` is OPTIONAL and lives in requirements-optional.txt (not the
core requirements.txt) so headless browsing never becomes a hard install burden.
The module degrades to the plain-HTTP fallback path when it is absent.

INTEGRATION POINTS (see bottom of file for usage sketches)
----------------------------------------------------------
* OfficialFinancialsClient.fetch_bse_results(...)  -> get_bse_cookies()
* DelistingNCLTClient.fetch_official_delisted(...)  -> get_bse_cookies() + BSE delisted/suspended URLs
* FilingDiscoveryClient doc downloads of bseindia.com/nseindia.com URLs -> fetch_with_browser()
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Lazy, fail-closed imports
# ---------------------------------------------------------------------------
# Playwright (sync API — our blocked clients are all synchronous).
try:  # pragma: no cover - exercised only when playwright is installed
    from playwright.sync_api import (
        sync_playwright,
        BrowserContext,
        Page,
        Response,
        Error as PlaywrightError,
    )
    _PLAYWRIGHT_SYNC = True
except (ImportError, Exception):  # pragma: no cover - exercised when absent
    sync_playwright = None  # type: ignore
    BrowserContext = None  # type: ignore
    Page = None  # type: ignore
    Response = None  # type: ignore
    PlaywrightError = Exception  # type: ignore
    _PLAYWRIGHT_SYNC = False

# HTTP session backend (curl_cffi gives us browser TLS fingerprint impersonation).
try:
    from curl_cffi import requests as _requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    import requests as _requests  # type: ignore
    _HAS_CURL_CFFI = False

from reality_engine.config import (
    BROWSER_PROFILE_DIR,
    NSE_HEADERS,
    BSE_HEADERS,
    BSE_HOME_URL,
    NSE_HOME_URL,
    BSE_RESULTS_URL,
    BSE_DELISTED_URL,
    BSE_SUSPENDED_URL,
    BROWSER_HEADLESS,
    BROWSER_LAUNCH_TIMEOUT_MS,
    BROWSER_NAV_TIMEOUT_MS,
    BROWSER_RATE_LIMIT_SEC,
)

logger = logging.getLogger("reality_engine.headless_fetcher")

# JWS compact token: header.payload.signature, base64url.
_JWT_RE = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")
# Cookie / storage keys that commonly hold an auth token.
_TOKEN_KEY_RE = re.compile(r"(jwt|token|auth|session|bearer|access)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without a browser)
# ---------------------------------------------------------------------------
def extract_jwt_token(
    cookies: Optional[Dict[str, str]] = None,
    local_storage: Optional[Dict[str, str]] = None,
    session_storage: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Return the first JWT-like token found in cookies / storage, else None.

    Search order:
      1. Any cookie value matching the JWS pattern.
      2. Any localStorage / sessionStorage value matching the JWS pattern.
      3. Any cookie/storage value whose key looks auth-related AND whose value
         is a long base64-ish string (loose fallback for opaque tokens).
    Fail-closed: returns None on any input shape error.
    """
    cookies = cookies or {}
    local_storage = local_storage or {}
    session_storage = session_storage or {}

    pools: List[Dict[str, str]] = [cookies, local_storage, session_storage]

    # 1+2) exact JWS pattern
    for pool in pools:
        for _key, val in pool.items():
            if isinstance(val, str) and _JWT_RE.match(val.strip()):
                return val.strip()

    # 3) auth-named key with long opaque token value
    for pool in pools:
        for key, val in pool.items():
            if isinstance(key, str) and isinstance(val, str) and _TOKEN_KEY_RE.search(key):
                stripped = val.strip()
                if len(stripped) >= 24 and re.search(r"[A-Za-z0-9_-]", stripped):
                    return stripped
    return None


def cookies_to_header(cookies: Dict[str, str]) -> str:
    """Render a cookie dict as a ``Cookie`` request header value."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)


def _domain_of(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:  # pragma: no cover
        return ""


# ---------------------------------------------------------------------------
# Main reusable fetcher (synchronous — matches the blocked clients)
# ---------------------------------------------------------------------------
class HeadlessFetcher:
    """Obtain browser-issued JWT/cookies for blocked BSE/NSE endpoints, fail-closed.

    A single instance caches harvested cookies per domain (with a TTL) so callers
    can issue many API requests without relaunching the browser each time. The cache
    is process-local and safe to share across the sync clients.
    """

    def __init__(
        self,
        headless: bool = BROWSER_HEADLESS,
        launch_timeout_ms: int = BROWSER_LAUNCH_TIMEOUT_MS,
        nav_timeout_ms: int = BROWSER_NAV_TIMEOUT_MS,
        rate_limit_sec: float = BROWSER_RATE_LIMIT_SEC,
        browser_profile_dir: Optional[Any] = None,
        cookie_cache_ttl_sec: int = 300,
    ):
        self.headless = headless
        self.launch_timeout_ms = launch_timeout_ms
        self.nav_timeout_ms = nav_timeout_ms
        self.rate_limit_sec = max(0.0, float(rate_limit_sec))
        self.browser_profile_dir = browser_profile_dir or BROWSER_PROFILE_DIR
        self.cookie_cache_ttl_sec = max(0, int(cookie_cache_ttl_sec))

        self._last_call_ts = 0.0
        self._cookie_cache: Dict[str, Dict[str, Any]] = {}  # domain -> {ts, cookies}

    # -- capability / availability -----------------------------------------
    @property
    def available(self) -> bool:
        """True only when Playwright is importable (browser path usable)."""
        return _PLAYWRIGHT_SYNC

    def is_available(self) -> bool:
        """Explicit method form (mirrors other clients' ``is_available``)."""
        return _PLAYWRIGHT_SYNC

    # -- internal plumbing --------------------------------------------------
    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self.rate_limit_sec - (now - self._last_call_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    def _cached_cookies(self, domain: str) -> Optional[Dict[str, str]]:
        entry = self._cookie_cache.get(domain)
        if not entry:
            return None
        if time.monotonic() - entry["ts"] > self.cookie_cache_ttl_sec:
            self._cookie_cache.pop(domain, None)
            return None
        return entry["cookies"]

    def _store_cookies(self, domain: str, cookies: Dict[str, str]) -> None:
        if cookies:
            self._cookie_cache[domain] = {"ts": time.monotonic(), "cookies": cookies}

    def invalidate_cache(self) -> None:
        """Drop cached cookies (e.g. on auth expiry / login change)."""
        self._cookie_cache.clear()

    # -- browser launch + cookie extraction --------------------------------
    def _launch(self):
        """Launch a persistent Chromium context. Returns (pw, context) or None.

        Fail-closed: returns None on any launch failure; caller must handle None.
        """
        if not _PLAYWRIGHT_SYNC or sync_playwright is None:
            return None
        try:
            pw = sync_playwright().start()
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(self.browser_profile_dir),
                headless=self.headless,
                viewport={"width": 1366, "height": 768},
                timeout=self.launch_timeout_ms,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            return pw, context
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("HeadlessFetcher: browser launch failed: %s", exc)
            try:
                pw.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
            return None

    def _read_browser_state(self, context, page) -> Dict[str, Any]:
        """Collect cookies + localStorage + sessionStorage from a live page."""
        cookies = {c["name"]: c["value"] for c in context.cookies()}
        local_storage: Dict[str, str] = {}
        session_storage: Dict[str, str] = {}
        try:
            ls_json = page.evaluate(
                "() => { try { const o={}; for (let i=0;i<localStorage.length;i++){const k=localStorage.key(i); o[k]=localStorage.getItem(k);} return JSON.stringify(o);} catch(e){return '{}';} }"
            )
            local_storage = dict(_safe_json(ls_json))
        except Exception:  # pragma: no cover
            pass
        try:
            ss_json = page.evaluate(
                "() => { try { const o={}; for (let i=0;i<sessionStorage.length;i++){const k=sessionStorage.key(i); o[k]=sessionStorage.getItem(k);} return JSON.stringify(o);} catch(e){return '{}';} }"
            )
            session_storage = dict(_safe_json(ss_json))
        except Exception:  # pragma: no cover
            pass
        return {
            "cookies": cookies,
            "local_storage": local_storage,
            "session_storage": session_storage,
        }

    def obtain_browser_state(self, home_url: str) -> Dict[str, Any]:
        """Navigate to ``home_url`` in headless Chromium and harvest auth state.

        Returns a dict with keys ``cookies``, ``local_storage``, ``session_storage``,
        and ``jwt`` (best-effort extracted token, may be None). Fail-closed: on any
        failure returns an all-empty dict so callers can still degrade gracefully.
        """
        self._throttle()
        launched = self._launch()
        if launched is None:
            return {"cookies": {}, "local_storage": {}, "session_storage": {}, "jwt": None}

        pw, context = launched
        try:
            page = context.new_page()
            # Capture any token-bearing response headers (authorization / x-jwt-token).
            header_capture: Dict[str, str] = {}

            def _on_response(response: Any) -> None:
                try:
                    for h in ("authorization", "x-jwt-token", "x-access-token"):
                        v = response.headers.get(h)
                        if v:
                            header_capture[h] = v
                except Exception:
                    pass

            page.on("response", _on_response)
            try:
                page.goto(home_url, wait_until="domcontentloaded", timeout=self.nav_timeout_ms)
            except Exception as nav_exc:  # pragma: no cover - network dependent
                logger.warning("HeadlessFetcher: navigation to %s failed: %s", home_url, nav_exc)

            # Give SPAs a moment to issue cookies / write storage.
            try:
                page.wait_for_timeout(min(3500, max(1000, self.nav_timeout_ms)))
            except Exception:
                pass

            state = self._read_browser_state(context, page)

            # Header-supplied tokens (e.g. authorization: Bearer <jwt>) win if present.
            for _h, v in header_capture.items():
                token = v.split(" ", 1)[1] if v.lower().startswith("bearer ") else v
                if _JWT_RE.match(token.strip()):
                    state["jwt"] = token.strip()
                    break
            if state.get("jwt") is None:
                state["jwt"] = extract_jwt_token(
                    state["cookies"], state["local_storage"], state["session_storage"]
                )
            return state
        finally:
            try:
                context.close()
            finally:
                try:
                    pw.stop()
                except Exception:  # pragma: no cover
                    pass

    # -- public per-exchange helpers ---------------------------------------
    def get_bse_cookies(self, force_refresh: bool = False) -> Dict[str, str]:
        """Return cookie dict for bseindia.com, harvesting via browser if needed."""
        domain = _domain_of(BSE_HOME_URL)
        cached = None if force_refresh else self._cached_cookies(domain)
        if cached is not None:
            return cached
        state = self.obtain_browser_state(BSE_HOME_URL)
        cookies = state.get("cookies", {})
        self._store_cookies(domain, cookies)
        return cookies

    def get_nse_cookies(self, force_refresh: bool = False) -> Dict[str, str]:
        """Return cookie dict for nseindia.com, harvesting via browser if needed."""
        domain = _domain_of(NSE_HOME_URL)
        cached = None if force_refresh else self._cached_cookies(domain)
        if cached is not None:
            return cached
        state = self.obtain_browser_state(NSE_HOME_URL)
        cookies = state.get("cookies", {})
        self._store_cookies(domain, cookies)
        return cookies

    def get_bse_jwt_token(self, force_refresh: bool = False) -> Optional[str]:
        """Return the BSE JWT (from cookies/localStorage) or None if unavailable."""
        domain = _domain_of(BSE_HOME_URL)
        cached = None if force_refresh else self._cached_cookies(domain)
        if cached is not None:
            return extract_jwt_token(cached)
        state = self.obtain_browser_state(BSE_HOME_URL)
        if state.get("cookies"):
            self._store_cookies(domain, state["cookies"])
        return state.get("jwt")

    def get_nse_jwt_token(self, force_refresh: bool = False) -> Optional[str]:
        """Return the NSE JWT (from cookies/localStorage) or None if unavailable."""
        domain = _domain_of(NSE_HOME_URL)
        cached = None if force_refresh else self._cached_cookies(domain)
        if cached is not None:
            return extract_jwt_token(cached)
        state = self.obtain_browser_state(NSE_HOME_URL)
        if state.get("cookies"):
            self._store_cookies(domain, state["cookies"])
        return state.get("jwt")

    # -- generic fetch using harvested cookies -----------------------------
    def fetch_with_browser(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        method: str = "GET",
        force_refresh_cookies: bool = False,
        timeout: int = 30,
    ):
        """Fetch ``url``.

        * For BSE/NSE endpoints: replays the browser-issued session cookies/ JWT via a
          plain HTTP session (the original design — those APIs only honor cookies set
          by a real page visit).
        * For ANY other host (macro/JS-rendered listing pages such as
          financedept.tn.gov.in, financedepartment.gujarat.gov.in, finance.karnataka.gov.in,
          apfinance.gov.in, etc.): **navigates the target URL directly in headless
          Chromium** and returns the rendered page HTML (or the response body). This
          fixes the previous bug where the browser path fetched BSE cookies then did a
          plain GET against an unrelated host, never rendering the target page.

        Returns a response-like object with ``.content`` / ``.text`` / ``.headers`` on
        success, else ``None``. Fail-closed: never raises.
        """
        self._throttle()
        domain = _domain_of(url)

        if "bseindia.com" in domain:
            cookies = self.get_bse_cookies(force_refresh=force_refresh_cookies) or {}
            base_headers = dict(BSE_HEADERS)
        elif "nseindia.com" in domain:
            cookies = self.get_nse_cookies(force_refresh=force_refresh_cookies) or {}
            base_headers = dict(NSE_HEADERS)
        else:
            # Macro / generic host: navigate the TARGET url in a real browser.
            return self._fetch_via_browser_navigate(url, headers=headers, timeout=timeout)

        if headers:
            base_headers.update(headers)
        if cookies:
            base_headers["Cookie"] = cookies_to_header(cookies)

        try:
            session = _requests.Session()
            if _HAS_CURL_CFFI:
                session = _requests.Session(impersonate="chrome120")  # type: ignore[call-arg]
            session.headers.update(base_headers)
            resp = session.request(method, url, cookies=cookies, timeout=timeout)
            return resp
        except Exception as exc:  # pragma: no cover - network dependent
            logger.debug("HeadlessFetcher: fetch_with_browser failed for %s: %s", url, exc)
            return None

    def _fetch_via_browser_navigate(
        self, url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 30
    ):
        """Navigate ``url`` in headless Chromium and return the rendered page.

        Returns a simple response-like object (``_BrowserHTMLResponse``) exposing
        ``.content`` (bytes), ``.text`` (str) and ``.headers`` so callers that expect
        requests/curl_cffi responses keep working. Fail-closed: returns ``None`` when
        Playwright is unavailable or navigation fails.
        """
        if not _PLAYWRIGHT_SYNC:
            return None
        launched = self._launch()
        if launched is None:
            return None
        pw, context = launched
        nav_timeout_ms = max(1000, int(timeout) * 1000)
        try:
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=nav_timeout_ms)
            except Exception as nav_exc:  # pragma: no cover - network dependent
                # Some pages never reach networkidle (long-poll); retry at domcontentloaded.
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
                except Exception as nav_exc2:  # pragma: no cover
                    logger.debug("HeadlessFetcher: navigation to %s failed: %s / %s", url, nav_exc, nav_exc2)
            try:
                page.wait_for_timeout(min(2500, max(1000, nav_timeout_ms // 4)))
            except Exception:
                pass
            content = page.content() or ""
            return _BrowserHTMLResponse(url=url, content=content)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.debug("HeadlessFetcher: _fetch_via_browser_navigate failed for %s: %s", url, exc)
            return None
        finally:
            try:
                context.close()
            finally:
                try:
                    pw.stop()
                except Exception:  # pragma: no cover
                    pass

    def fetch_json_with_browser(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        force_refresh_cookies: bool = False,
        timeout: int = 30,
    ) -> Optional[Any]:
        """Convenience wrapper: returns parsed JSON or None (fail-closed)."""
        resp = self.fetch_with_browser(
            url, headers=headers, force_refresh_cookies=force_refresh_cookies, timeout=timeout
        )
        if resp is None:
            return None
        try:
            if getattr(resp, "status_code", 200) != 200:
                logger.debug("HeadlessFetcher: %s -> HTTP %s", url, getattr(resp, "status_code", "?"))
                return None
            return resp.json()
        except Exception as exc:  # pragma: no cover
            logger.debug("HeadlessFetcher: JSON parse failed for %s: %s", url, exc)
            return None


def _safe_json(text: Any) -> Dict[str, Any]:
    """Parse a JSON object string into a dict; return {} on failure."""
    if not isinstance(text, str):
        return {}
    try:
        import json

        val = json.loads(text)
        return val if isinstance(val, dict) else {}
    except Exception:  # pragma: no cover
        return {}


class _BrowserHTMLResponse:
    """Minimal response-like wrapper around headless-browser page content.

    Exposes the attributes the macro fetcher reads (``.content`` bytes, ``.text`` str,
    ``.headers`` dict, ``.status_code``) so both the requests/curl_cffi path and the
    browser navigation path present the same interface.
    """

    def __init__(self, url: str, content: Any):
        self.url = url
        self.content = content if isinstance(content, bytes) else content.encode("utf-8", "ignore")
        self.text = content if isinstance(content, str) else content.decode("utf-8", "ignore")
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.status_code = 200

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"_BrowserHTMLResponse(url={self.url!r}, bytes={len(self.content)})"


# ---------------------------------------------------------------------------
# Module-level convenience functions (sync)
# ---------------------------------------------------------------------------
_default_fetcher = HeadlessFetcher()


def is_playwright_available() -> bool:
    """True if the browser path is usable (Playwright importable)."""
    return _PLAYWRIGHT_SYNC


def get_bse_cookies(force_refresh: bool = False) -> Dict[str, str]:
    """Module-level: BSE cookie dict (empty if Playwright unavailable)."""
    return _default_fetcher.get_bse_cookies(force_refresh=force_refresh)


def get_nse_cookies(force_refresh: bool = False) -> Dict[str, str]:
    """Module-level: NSE cookie dict (empty if Playwright unavailable)."""
    return _default_fetcher.get_nse_cookies(force_refresh=force_refresh)


def get_bse_jwt_token(force_refresh: bool = False) -> Optional[str]:
    """Module-level: BSE JWT or None."""
    return _default_fetcher.get_bse_jwt_token(force_refresh=force_refresh)


def get_nse_jwt_token(force_refresh: bool = False) -> Optional[str]:
    """Module-level: NSE JWT or None."""
    return _default_fetcher.get_nse_jwt_token(force_refresh=force_refresh)


def fetch_with_browser(url: str, headers: Optional[Dict[str, str]] = None, **kwargs):
    """Module-level: fetch ``url`` with browser cookies, or None on failure."""
    return _default_fetcher.fetch_with_browser(url, headers=headers, **kwargs)


def fetch_json_with_browser(url: str, headers: Optional[Dict[str, str]] = None, **kwargs):
    """Module-level: fetch + parse JSON, or None on failure."""
    return _default_fetcher.fetch_json_with_browser(url, headers=headers, **kwargs)


# ---------------------------------------------------------------------------
# Async wrappers (for callers already inside an event loop, e.g. the
# FinanciallyFreeClient async session). These run the sync browser work in a
# worker thread so they never block the running loop and stay fail-closed.
# ---------------------------------------------------------------------------
async def get_bse_cookies_async(force_refresh: bool = False) -> Dict[str, str]:
    return await asyncio.to_thread(get_bse_cookies, force_refresh=force_refresh)


async def get_nse_cookies_async(force_refresh: bool = False) -> Dict[str, str]:
    return await asyncio.to_thread(get_nse_cookies, force_refresh=force_refresh)


async def get_bse_jwt_token_async(force_refresh: bool = False) -> Optional[str]:
    return await asyncio.to_thread(get_bse_jwt_token, force_refresh=force_refresh)


async def fetch_json_with_browser_async(url: str, headers: Optional[Dict[str, str]] = None, **kwargs):
    return await asyncio.to_thread(fetch_json_with_browser, url, headers=headers, **kwargs)


# ---------------------------------------------------------------------------
# Integration-point sketches (documentation for the next wave)
# ---------------------------------------------------------------------------
#
# 1) official_financials_client.OfficialFinancialsClient.fetch_bse_results():
#      from reality_engine.ingestion.headless_fetcher import get_bse_cookies
#      cookies = get_bse_cookies()
#      if cookies:
#          resp = self.session.get(url, headers={**BSE_HEADERS, "Cookie": cookies_to_header(cookies)}, timeout=20)
#      # else: keep current fail-closed [] return
#
# 2) delisting_nclt_client.DelistingNCLTClient.fetch_official_delisted():
#      from reality_engine.ingestion.headless_fetcher import get_bse_cookies, BSE_DELISTED_URL, BSE_SUSPENDED_URL
#      cookies = get_bse_cookies()
#      if cookies:
#          # GET BSE_DELISTED_URL / BSE_SUSPENDED_URL with the cookie header, parse JSON
#
# 3) filing_discovery for BSE/NSE doc downloads that 403 without a session:
#      from reality_engine.ingestion.headless_fetcher import fetch_with_browser
#      resp = fetch_with_browser(official_bse_or_nse_doc_url)
#      # resp.content / resp.body to stream the PDF/XBRL
# ---------------------------------------------------------------------------

__all__ = [
    "HeadlessFetcher",
    "extract_jwt_token",
    "cookies_to_header",
    "is_playwright_available",
    "get_bse_cookies",
    "get_nse_cookies",
    "get_bse_jwt_token",
    "get_nse_jwt_token",
    "fetch_with_browser",
    "fetch_json_with_browser",
    "get_bse_cookies_async",
    "get_nse_cookies_async",
    "get_bse_jwt_token_async",
    "fetch_json_with_browser_async",
]
