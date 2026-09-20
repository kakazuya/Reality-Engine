"""
BSE Ingestion Client Module
Handles downloading and parsing of BSE Scrip Master, BSE Bhavcopy, and Corporate Disclosures.

HTTP 200 is NOT success on BSE.  Every untrusted body passes a content guard
(``_SOFT_FAIL_GUARD`` / ``BSE_SOFT_FAIL_MARKERS``) before it is parsed or
cached, and the module-level helpers ``bse_json`` / ``bse_csv`` / ``bse_bytes``
are the single HTTP convention shared by the rest of the engine.
"""

import io
import json
import logging
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
try:
    from curl_cffi import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:
    import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = False
import urllib3

from reality_engine.config import (
    BSE_HEADERS,
    BSE_SCRIP_LIST_URL,
    BSE_BHAVCOPY_URL_TEMPLATE,
    BSE_ANNOUNCEMENTS_URL_TEMPLATE,
    BHAVCOPY_DIR
)

urllib3.disable_warnings()
logger = logging.getLogger("reality_engine.bse_client")

# ---------------------------------------------------------------------------
# 1. Content guards — "HTTP 200" means nothing on BSE
# ---------------------------------------------------------------------------
# Bodies BSE serves with HTTP 200 that are NOT the requested data.  All three
# forms were verified live (2026-09-19) while probing the download/API hosts:
#   1. the Angular SPA shell of www.bseindia.com (contains ``<app-root>`` and
#      "LIVE Stock/Share Market"); a bhavcopy request for a missing or
#      non-trading date answers 200 + ~14 KB of HTML instead of the CSV;
#   2. an ASP.NET soft-404 template whose body literally contains
#      ``<%= Response.StatusCode=404 %>`` — an unknown path returns the
#      identical 1,814-byte body, so a 200 proves nothing;
#   3. a JSON error envelope ``{"Status":false,"Message":"..."}`` (e.g. the
#      corporate-announcements 12-month window cap).
BSE_SOFT_FAIL_MARKERS = ("<app-root>", "Response.StatusCode=404", "<!DOCTYPE html>")

_SOFT_FAIL_GUARD = """\
Content guard applied to EVERY BSE response before it is parsed or cached.

A BSE 200 is not an answer.  Three non-answer forms were verified live
(2026-09-19) and each one must be treated as "no data" — never parsed, never
written to a cache file:

1. Angular SPA shell (``<app-root>`` / "LIVE Stock/Share Market"): a bhavcopy
   request for a missing or non-trading date returns 200 with ~14 KB of HTML
   rather than the UDiFF CSV.
2. ASP.NET soft-404 template containing ``<%= Response.StatusCode=404 %>``:
   an unknown path returns the identical 1,814-byte body, so the status code
   carries no information.
3. JSON error envelope ``{"Status":false,"Message":"..."}``: the endpoint
   answered, but with an error (e.g. the announcements 12-month window cap).

``_is_soft_fail`` implements (1) and (2) for text bodies; ``bse_json`` also
implements (3) and additionally unwraps the double-encoded payloads several
BSE endpoints return (``r.json()`` yields a ``str`` needing a second
``json.loads``); ``bse_csv`` / ``bse_bytes`` fail closed on a wrong prefix.
"""

_UDIFF_CSV_PREFIX = "TradDt,"

_BSE_API_BASE = "https://api.bseindia.com/BseIndiaAPI/api/"

# Legacy (pre-UDiFF) daily Bhavcopy archive: a ZIP whose only member is
# ``EQ<DDMMYY>.CSV``.  Verified live 200 from 2006-06-16 to 2024-04-18; the
# format was retired by 2024-07-18.
BSE_LEGACY_BHAVCOPY_URL_TEMPLATE = "https://www.bseindia.com/download/BhavCopy/Equity/EQ{ddmmyy}_CSV.ZIP"

# AnnSubCategoryGetData rejects a window wider than 12 months with
# {"Status":false,"Message":"Date range cannot exceed 12 months."}.
_MAX_ANNOUNCEMENT_WINDOW_DAYS = 365

# Request pacing: BSE tolerated 1-2s spacing with no 403/429 in live probing.
# The floor is enforced PER THREAD: a process-wide lock would serialise every
# worker and make ``--workers N`` a no-op (measured: 16.3 s/scrip regardless of
# N). Each worker therefore keeps its own floor, and each worker must also use
# its own session — a curl_cffi Session is not safe for concurrent use.
_PACE_MIN_SECONDS = 1.0
_PACE_MAX_SECONDS = 2.0
_pace_state = threading.local()

_module_session_lock = threading.Lock()


def _is_soft_fail(body: Optional[str]) -> bool:
    """True when ``body`` is one of the non-answer forms in ``_SOFT_FAIL_GUARD``."""
    if not body or not body.strip():
        return True
    head = body[:8192]
    return any(marker in head for marker in BSE_SOFT_FAIL_MARKERS)


def _pace() -> None:
    """Space this thread's BSE requests 1.0-2.0s apart.

    Thread-local by design: a shared lock throttles every worker to one
    request per gap, which is why ``workers=4`` measured no faster than
    ``workers=1``. Per-thread state gives N workers N× throughput while every
    individual connection still respects the floor BSE tolerated in probing.
    """
    last = getattr(_pace_state, "last_request_at", 0.0)
    wait = _PACE_MIN_SECONDS - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)
    time.sleep(random.uniform(0.0, _PACE_MAX_SECONDS - _PACE_MIN_SECONDS))
    _pace_state.last_request_at = time.monotonic()


def _module_session():
    """The single warmed BSE session every module-level fetch shares.

    ``bse_client`` (the module singleton) is that session, so the class methods
    and the ``bse_json`` / ``bse_csv`` / ``bse_bytes`` helpers put all traffic
    on one connection pool, one warm-up, and one pacing clock.
    """
    global bse_client
    with _module_session_lock:
        if bse_client is None:  # pragma: no cover — only if import order broke
            bse_client = BSEClient()
        client = bse_client
    if not client._warmed_up:
        client._warmup_session()
    return client.session


def _http_get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30,
              session: Any = None):
    """Paced GET on the shared BSE session; returns the response or None on failure."""
    sess = session if session is not None else _module_session()
    _pace()
    try:
        return sess.get(url, params=params, headers=BSE_HEADERS, timeout=timeout)
    except Exception as e:
        logger.warning("BSE request failed for %s: %s", url, e)
        return None


def bse_json(path_or_url: str, params: Optional[Dict[str, Any]] = None, *,
             session: Any = None, timeout: int = 25) -> Optional[Any]:
    """GET a BSE JSON endpoint and return the payload, or None on any non-answer.

    ``path_or_url`` may be a full URL or a path relative to the BSE API root
    (``"AnnSubCategoryGetData/w"``).  None is returned for a non-200, an empty
    body, any ``BSE_SOFT_FAIL_MARKERS`` hit, a ``{"Status": false}`` envelope,
    a body that is not JSON, and a still-unparseable double-encoded payload.
    Never raises.  See ``_SOFT_FAIL_GUARD`` for the verified failure forms.
    """
    url = path_or_url
    if not url.lower().startswith(("http://", "https://")):
        url = _BSE_API_BASE + url.lstrip("/")

    res = _http_get(url, params=params, timeout=timeout, session=session)
    if res is None:
        return None
    if res.status_code != 200:
        logger.warning("BSE JSON %s returned HTTP %d", url, res.status_code)
        return None

    body = res.text or ""
    if _is_soft_fail(body):
        logger.info("BSE JSON guard: %s returned a soft-fail body (%d bytes)", url, len(body))
        return None

    try:
        data = res.json()
    except Exception as e:
        logger.warning("BSE JSON %s body unparseable: %s", url, e)
        return None

    # Several endpoints double-encode: r.json() hands back a str of JSON.
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception as e:
            logger.warning("BSE JSON %s double-encoded body unparseable: %s", url, e)
            return None

    if not isinstance(data, (dict, list)):
        logger.warning("BSE JSON %s returned %s, not an object/array", url, type(data).__name__)
        return None
    if not data:
        return None
    if isinstance(data, dict):
        status = data.get("Status")
        if status is False or (isinstance(status, str) and status.strip().lower() == "false"):
            logger.info("BSE JSON %s returned Status:false (%s)", url, data.get("Message"))
            return None
    return data


def bse_csv(url: str, expected_prefix: str = _UDIFF_CSV_PREFIX, *,
            session: Any = None, timeout: int = 30) -> Optional[str]:
    """GET a BSE CSV and return its text, or None when the body is not that CSV.

    Fail-closed: a body that does not start with ``expected_prefix`` (the UDiFF
    bhavcopy starts with ``TradDt,``; pass the legacy header for the old
    archive) is a soft-fail page, an error page, or an empty file — never data.
    """
    res = _http_get(url, timeout=timeout, session=session)
    if res is None:
        return None
    if res.status_code != 200:
        logger.warning("BSE CSV %s returned HTTP %d", url, res.status_code)
        return None

    body = (res.text or "").lstrip("\ufeff")
    if not body.strip():
        logger.info("BSE CSV %s returned an empty body", url)
        return None
    if not body.startswith(expected_prefix):
        logger.info(
            "BSE CSV guard: %s body does not start with %r (len=%d) — treated as no data",
            url, expected_prefix, len(body),
        )
        return None
    return body


def bse_bytes(url: str, expected_magic: bytes = b"PK\x03\x04", *,
              session: Any = None, timeout: int = 45) -> Optional[bytes]:
    """GET a binary BSE artifact (legacy bhavcopy ZIP); None unless the magic matches."""
    res = _http_get(url, timeout=timeout, session=session)
    if res is None:
        return None
    if res.status_code != 200:
        logger.warning("BSE download %s returned HTTP %d", url, res.status_code)
        return None
    body = res.content or b""
    if not body.startswith(expected_magic):
        logger.info(
            "BSE binary guard: %s body lacks magic %r (len=%d) — treated as no data",
            url, expected_magic, len(body),
        )
        return None
    return body


def _cached_csv_is_valid(path, expected_prefix: str = _UDIFF_CSV_PREFIX) -> bool:
    """True when a cached bhavcopy file still starts with the expected CSV header.

    Guards against a soft-fail page that an earlier (pre-guard) run cached as a
    CSV: such a file is ignored and re-fetched rather than parsed as data.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(len(expected_prefix) + 4)
    except OSError as e:
        logger.warning("BSE cache %s unreadable: %s", path, e)
        return False
    return head.lstrip("\ufeff").startswith(expected_prefix)


def _parse_yyyymmdd(value: Optional[str]) -> Optional[datetime]:
    """Parse a ``YYYYMMDD`` string; None when absent or malformed."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y%m%d")
    except ValueError:
        return None


class BSEClient:
    """Client for fetching BSE official equity master and bhavcopy files."""

    def __init__(self):
        if _HAS_CURL_CFFI:
            self.session = _curl_requests.Session(impersonate="chrome120", verify=False)  # type: ignore[call-arg]
        else:
            self.session = _curl_requests.Session()
            try:
                self.session.verify = False  # type: ignore[attr-defined]
            except Exception:
                pass
        self._warmed_up = False

    def _warmup_session(self):
        if not self._warmed_up:
            try:
                self.session.get("https://www.bseindia.com", headers=BSE_HEADERS, timeout=10)
                self._warmed_up = True
            except Exception as e:
                logger.warning(f"BSE Session warmup note: {e}")

    def fetch_scrip_master(self) -> pd.DataFrame:
        """Fetches the official BSE Active Equity Scrip list."""
        self._warmup_session()
        logger.info("Fetching BSE Scrip Master from %s", BSE_SCRIP_LIST_URL)
        res = self.session.get(BSE_SCRIP_LIST_URL, headers=BSE_HEADERS, timeout=20)
        if res.status_code != 200:
            raise RuntimeError(f"Failed to fetch BSE Scrip Master: HTTP {res.status_code}")

        try:
            data = res.json()
        except Exception as e:
            raise RuntimeError(f"Failed to parse BSE Scrip Master JSON: {e}")

        df = pd.DataFrame(data)
        if df.empty:
            return df

        # Clean columns and strings
        df.columns = df.columns.str.strip()
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].astype(str).str.strip()

        # Rename standard columns
        rename_map = {
            "SCRIP_CD": "bse_code",
            "Scrip_Name": "bse_name",
            "ISIN_NUMBER": "isin",
            "scrip_id": "bse_symbol",
            "GROUP": "bse_group",
            "Mktcap": "bse_mktcap_cr"
        }
        df = df.rename(columns=rename_map)
        logger.info("Loaded %d active BSE equity records", len(df))
        return df

    def fetch_bhavcopy(self, target_date: datetime) -> Optional[pd.DataFrame]:
        """Fetches the daily BSE UDiFF CM Bhavcopy CSV.

        Returns None (never a bogus frame) when the session has no file — BSE
        answers a missing/non-trading date with HTTP 200 + the SPA shell — and
        caches the download ONLY after the content guard has accepted it.
        """
        self._warmup_session()
        date_str = target_date.strftime("%Y%m%d")
        url = BSE_BHAVCOPY_URL_TEMPLATE.format(date_str=date_str)
        local_file = BHAVCOPY_DIR / f"BhavCopy_BSE_{date_str}.csv"

        text: Optional[str] = None
        if local_file.exists():
            if _cached_csv_is_valid(local_file, _UDIFF_CSV_PREFIX):
                logger.info("Loading cached BSE Bhavcopy from %s", local_file)
                try:
                    text = local_file.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    logger.warning("Cached BSE Bhavcopy %s unreadable: %s", local_file, e)
                    text = None
            else:
                logger.warning(
                    "Ignoring invalid cached BSE Bhavcopy %s (does not start with %r — "
                    "a soft-fail body was cached before the content guard existed)",
                    local_file, _UDIFF_CSV_PREFIX,
                )

        if text is None:
            logger.info("Downloading BSE Bhavcopy for %s", target_date.strftime('%Y-%m-%d'))
            text = bse_csv(url, _UDIFF_CSV_PREFIX)
            if text is None:
                logger.warning(
                    "No BSE UDiFF Bhavcopy for %s (no session file / soft-fail body)", date_str
                )
                return None
            try:
                local_file.write_text(text, encoding="utf-8")
            except OSError as e:
                logger.warning("Could not cache BSE Bhavcopy for %s: %s", date_str, e)

        try:
            df = pd.read_csv(io.StringIO(text))
        except Exception as e:
            logger.warning("Could not parse BSE Bhavcopy for %s: %s", date_str, e)
            return None
        df.columns = df.columns.str.strip()
        if df.empty:
            return None
        return df

    def fetch_corporate_announcements(self, scrip_code: str = "", category: str = "Result",
                                     from_date: str = "", to_date: str = "") -> List[Dict[str, Any]]:
        """Fetches corporate announcements for a scrip.

        Working contract (verified live; ``fundamentals_client`` uses the same
        one): ``AnnSubCategoryGetData/w`` with ``strCat`` (-1 = all, or a
        category name such as ``Result``), ``subcategory=-1``, ``strSearch=P``,
        ``strType=C`` and the window as ``strPrevDate`` / ``strToDate`` in
        ``YYYYMMDD``.  The endpoint hard-caps the window at 12 months — a wider
        range answers ``{"Status":false,"Message":"Date range cannot exceed 12
        months."}`` — so the range is clamped here.  Returns [] on any failure.
        """
        self._warmup_session()
        end = _parse_yyyymmdd(to_date) or datetime.now()
        start = _parse_yyyymmdd(from_date) or (end - timedelta(days=_MAX_ANNOUNCEMENT_WINDOW_DAYS))
        if start > end:
            start, end = end, start
        if (end - start).days > _MAX_ANNOUNCEMENT_WINDOW_DAYS:
            logger.info("BSE announcements window clamped to 12 months (endpoint cap)")
            start = end - timedelta(days=_MAX_ANNOUNCEMENT_WINDOW_DAYS)

        params = {
            "pageno": 1,
            "strCat": (str(category).strip() if str(category).strip() not in ("", "-1", "None") else "-1"),
            "subcategory": -1,
            "strPrevDate": start.strftime("%Y%m%d"),
            "strToDate": end.strftime("%Y%m%d"),
            "strSearch": "P",
            "strScrip": str(scrip_code).strip(),
            "strType": "C",
        }
        try:
            data = bse_json(BSE_ANNOUNCEMENTS_URL_TEMPLATE, params=params)
        except Exception as e:  # bse_json never raises, but stay fail-closed
            logger.error("Error fetching BSE announcements for %s: %s", scrip_code, e)
            return []
        if data is None:
            logger.info("No BSE announcements for scrip %s", scrip_code)
            return []
        table = data.get("Table") if isinstance(data, dict) else data
        return table if isinstance(table, list) else []


# Singleton client — also the session every module-level fetch shares.
bse_client = BSEClient()

__all__ = [
    "BSEClient",
    "bse_client",
    "bse_json",
    "bse_csv",
    "bse_bytes",
    "BSE_SOFT_FAIL_MARKERS",
    "BSE_LEGACY_BHAVCOPY_URL_TEMPLATE",
]
