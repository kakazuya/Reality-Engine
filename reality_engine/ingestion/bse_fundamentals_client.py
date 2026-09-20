"""BSE fundamentals client: financials, shareholding, sector identity, announcements.

One scrip, four verified BSE JSON endpoints (all probed live, no browser, no
cookies), each read fail-closed — a null answer becomes an entry in ``errors``
and the scrip still completes.  The single HTTP layer is
``reality_engine.ingestion.bse_client.bse_json`` (paced, content-guarded,
double-decode aware); this module never opens its own connection, and every
fetcher may be injected so tests run with zero network.

Endpoint contract
-----------------
``ComHeadernew/w?scripcode=<code>``
    Sector identity: SecurityId, SecurityCode, ISIN, Industry, IndustryNew,
    Group, FaceVal, EPS, CEPS, PE.
``TabResults_PAR/w?scripcode=<code>&tabtype=RESULTS``
    ``tabtype`` is required (without it the body is empty).  ``col2/col3/col4``
    are PERIOD LABELS for ``v1/v2/v3``; ``resultinCr`` holds crore values and
    ``resultinM`` the same rows in MILLIONS of rupees (verified live: UNIFIED
    544406 Mar-26 revenue is ``138.97`` crore in ``resultinCr`` and
    ``1,389.74`` in ``resultinM``; 1 crore = 10 million), so ``resultinM`` is the
    finer-precision source and is scaled back to crore by a factor measured from
    the payload.  SME filers report half-yearly plus the FY total, some scrips
    report quarterly with a blank ``col2`` — the labels are read, never assumed,
    and ``v1 + v2`` is reconciled against the FY total ``v3`` whenever the dated
    columns are halves of the year (two consecutive quarters cover about half a
    year and are never summed against it).  A malformed FY label that ends before
    the earliest period shown is flagged, and never written as a fiscal year.
``CorporatesSHPSecuritybeta/w?scripcode=<code>[&qtrid=<Qtr_Id>]``
    Filing index (``Qtr_Id`` / ``Fld_qtrname``, newest first) and, with
    ``qtrid``, the aggregate ``Table1`` rows (``STA1A2`` promoter,
    ``STB1B2B3`` public, ``STABC`` grand total); the aggregate is ``{}`` for
    some scrips.
``TabResults_SHP/w?scripcode=<code>``
    Per-quarter SHP rows, and the ONLY source that reveals "never filed": BSE
    emits a placeholder row (promoter ``0.00``/``--``/empty, total ``100.00``
    or ``0.00``) for quarters it never received — including the NEWEST quarter
    of a scrip whose older quarters are filed, so placeholder rows are skipped
    in favour of the newest row that carries real percentages.  A placeholder is
    "not filed" — never ``0.00%`` data.
``Corp_shpSec_SHPPubShold_ng/w?SCRIPCODE=<code>&QtrCode=<Qtr_Id>``
    Public split (params MUST be uppercase — lowercase silently answers an
    all-zero template).  ``Table1`` rows carry ``Fld_SubCategory``
    (``Institutions (Domestic)`` = DII, ``Institutions (Foreign)`` = FII,
    ``Non-Institutions`` = retail) whose ``Fld_Level`` "Sub Total" rows are the
    aggregates, plus named holders in ``Fld_ShareHolderName``.
``Corp_shpPromoterNGroup_ng/w?SCRIPCODE=<code>&QtrCode=<Qtr_Id>``
    Per-promoter names and percentages (``Fld_ShareHolderName`` + Sub Total rows).
``AnnSubCategoryGetData/w?pageno=&strCat=-1&subcategory=-1&strPrevDate=YYYYMMDD
&strToDate=YYYYMMDD&strSearch=P&strscrip=<code>&strType=C``
    Announcements; hard 12-month window cap, 50 rows per page with the total in
    ``Table1[0].ROWCNT``.  Windows and pages are both looped.

Storage rules (non-negotiable)
------------------------------
* Financials -> ``quarterly_financials`` (``source='bse_halfyearly'``, or
  ``'bse_quarterly'`` when the labels say quarterly) and FY totals ->
  ``annual_financials``; upsert on the natural key, so re-runs never duplicate.
* Ownership -> ``company_forensic_health``: promoter/FII/DII/public percentages
  ONLY.  BSE carries no pledge, no interest coverage and no debt/equity, so
  those columns are never written, and ``is_solvency_approved`` is NEVER set or
  cleared — an unknown gate stays unknown.
* A missing percentage is NULL, never ``0.0``; a scrip with no SHP gets no
  ownership row at all.
* Only columns that actually exist (``PRAGMA table_info``) are written.
"""

from __future__ import annotations

import calendar
import json
import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from reality_engine.db.database import db_manager

logger = logging.getLogger("reality_engine.bse_fundamentals_client")

# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
BSE_API_BASE = "https://api.bseindia.com/BseIndiaAPI/api"

EP_HEADER = f"{BSE_API_BASE}/ComHeadernew/w"
EP_RESULTS = f"{BSE_API_BASE}/TabResults_PAR/w"
EP_SHP_TAB = f"{BSE_API_BASE}/TabResults_SHP/w"
EP_SHP_INDEX = f"{BSE_API_BASE}/CorporatesSHPSecuritybeta/w"
EP_SHP_PUBLIC = f"{BSE_API_BASE}/Corp_shpSec_SHPPubShold_ng/w"
EP_SHP_PROMOTER = f"{BSE_API_BASE}/Corp_shpPromoterNGroup_ng/w"
EP_ANNOUNCEMENTS = f"{BSE_API_BASE}/AnnSubCategoryGetData/w"

ANNOUNCEMENT_PDF_URL = "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={attachment}"
ANNOUNCEMENT_ATTACH_URL = "https://www.bseindia.com/AttachLive/{attachment}"

# Provenance tokens for the two BSE statement cadences.
SOURCE_HALF_YEARLY = "bse_halfyearly"
SOURCE_QUARTERLY = "bse_quarterly"

KIND_QUARTERLY = "quarterly"
KIND_HALF_YEARLY = "halfyearly"
KIND_FY = "fy"

# The endpoint rejects a wider range with {"Status":false,"Message":"Date range
# cannot exceed 12 months."}; 365 days is the widest verified-safe window.
MAX_ANNOUNCEMENT_WINDOW_DAYS = 365
ANN_PAGE_SIZE = 50
ANN_MAX_PAGES = 200

# Reconciliation tolerance for v1 + v2 == v3.  BSE's own halves/FY totals really
# disagree (AFCOM 544224 revenue by 8.6%, YASHHV 544310 by 0.24%) and the drift
# is identical in both statement tables — it is the filing, not the unit — so a
# mismatch is recorded rather than smoothed away.
RECONCILE_REL_TOL = 5e-4
RECONCILE_ABS_TOL = 0.01
# v1 + v2 is only meant to be the FY total when the dated columns are HALVES of
# the year.  Two consecutive quarters cover ~0.5 of the FY (ABB 500002: two
# quarters = 0.51), so anything below this is a quarterly presentation and
# summing it against the FY total would flag a non-anomaly on every quarter.
RECONCILE_MIN_FY_COVERAGE = 0.75

# ``resultinM`` is the same statement in millions of rupees, so 10 M = 1 crore.
# Verified live: UNIFIED 544406 Mar-26 revenue 138.97 Cr == 1,389.74 M.
RESULTIN_M_TO_CR = 0.1
_M_TABLE_AMOUNT_FIELDS = ("revenue", "net_profit")

PERSIST_ERROR_LIMIT = 50

__all__ = [
    "fetch_header",
    "fetch_results",
    "fetch_shp",
    "fetch_announcements",
    "fetch_company",
    "fetch_universe",
    "persist_company",
    "announcement_pdf_url",
    "parse_period_label",
    "SOURCE_HALF_YEARLY",
    "SOURCE_QUARTERLY",
    "KIND_QUARTERLY",
    "KIND_HALF_YEARLY",
    "KIND_FY",
]


# --------------------------------------------------------------------------
# Value / key helpers
# --------------------------------------------------------------------------
_NULL_TOKENS = {"", "-", "--", "---", "na", "n/a", "nil", "null", "none", "nan", "abc"}
_NUM_CLEAN = re.compile(r"[^0-9eE+\-.]")


def _to_float(value: Any) -> Optional[float]:
    """Parse a BSE scalar (``"1,23,456.78"``, ``"--"``, ``None``) into a float or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        return num if math.isfinite(num) else None
    text = str(value).strip().replace(",", "").replace("%", "").strip()
    if text.lower() in _NULL_TOKENS:
        return None
    cleaned = _NUM_CLEAN.sub("", text)
    if not cleaned or cleaned in {"-", "+", ".", "-."}:
        return None
    try:
        num = float(cleaned)
    except ValueError:
        return None
    return num if math.isfinite(num) else None


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm_key(key: Any) -> str:
    """Normalise a payload key: lowercase, drop ``ns1:`` prefixes and punctuation."""
    text = str(key).strip().lower()
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return re.sub(r"[^a-z0-9]+", "", text)


def _row_lookup(row: Any, names: Sequence[str]) -> Any:
    """Value of the first key in ``names`` (priority order, case/namespace-insensitive)."""
    if not isinstance(row, dict) or not names:
        return None
    normalised = {_norm_key(k): v for k, v in row.items()}
    for name in names:
        value = normalised.get(_norm_key(name))
        if value is not None and value != "":
            return value
    return None


_LABEL_KEYS = ("name", "particulars", "category", "holder", "shareholder", "promotername",
               "promoter", "quarter", "description")


def _table_rows(payload: Any) -> List[Dict[str, Any]]:
    """Rows of the first list-of-dicts inside a BSE payload (Table/Data/... wrappers)."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("Table", "table", "Data", "data", "rows", "result"):
        value = payload.get(key)
        if isinstance(value, list) and any(isinstance(r, dict) for r in value):
            return [r for r in value if isinstance(r, dict)]
        if isinstance(value, dict) and value:
            nested = [r for r in value.values() if isinstance(r, dict)]
            if nested:
                return nested
    for value in payload.values():
        if isinstance(value, list) and any(isinstance(r, dict) for r in value):
            return [r for r in value if isinstance(r, dict)]
    if any(_norm_key(k) in _LABEL_KEYS for k in payload):
        return [payload]
    return []


def _unwrap_object(payload: Any) -> Any:
    """Unwrap single-object ``Table``/``Data``/``d`` envelopes and one-row arrays."""
    if isinstance(payload, list):
        return payload[0] if payload and isinstance(payload[0], dict) else payload
    if isinstance(payload, dict):
        for key in ("Table", "Data", "d"):
            value = payload.get(key)
            if isinstance(value, dict) and value:
                return value
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value[0]
    return payload


# --------------------------------------------------------------------------
# Percentage recovery from loosely-shaped BSE objects
# --------------------------------------------------------------------------
def _first_pct_leaf(obj: Any, depth: int = 0) -> Optional[float]:
    """First 0..100 numeric leaf, for payloads with no obvious percentage key."""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        for value in obj.values():
            found = _first_pct_leaf(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _first_pct_leaf(value, depth + 1)
            if found is not None:
                return found
    else:
        num = _to_float(obj)
        if num is not None and 0.0 <= num <= 100.0:
            return num
    return None


def _pct_from_value(value: Any, depth: int = 0) -> Optional[float]:
    if isinstance(value, (dict, list)):
        for name in ("total", "percentage", "percent", "pct", "promotertotal", "publictotal"):
            found = _find_pct(value, (name,), depth + 1)
            if found is not None:
                return found
        return _first_pct_leaf(value, depth + 1)
    return _to_float(value)


def _find_pct(obj: Any, names: Sequence[str], depth: int = 0) -> Optional[float]:
    """First percentage under a key named in ``names``, at any nesting depth."""
    if obj is None or depth > 6:
        return None
    wanted = {_norm_key(name) for name in names}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if _norm_key(key) in wanted:
                found = _pct_from_value(value, depth)
                if found is not None:
                    return found
        for value in obj.values():
            found = _find_pct(value, names, depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_pct(value, names, depth + 1)
            if found is not None:
                return found
    return None


# --------------------------------------------------------------------------
# Period labels
# --------------------------------------------------------------------------
_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_FY_LABEL_RE = re.compile(r"^\s*fy\s*(\d{2,4})\s*[-–/]?\s*(\d{2,4})?\s*$", re.IGNORECASE)


def _is_fy_label(label: Any) -> bool:
    """True for a fiscal-year label (``FY25-26``, ``FY 2025-2026``, ``FY26``)."""
    text = str(label or "").strip()
    if not text:
        return False
    if _MONTH_ABBR.get(text[:3].lower()) is not None:
        return False
    return _FY_LABEL_RE.match(text) is not None


def fiscal_year_label(label: Any) -> Optional[str]:
    """``FY25-26`` / ``FY 2025-2026`` / ``FY26`` -> ``FY26`` (None when not an FY label)."""
    match = _FY_LABEL_RE.match(str(label or "").strip())
    if not match:
        return None
    end = match.group(2) or match.group(1)
    start = match.group(1)
    if match.group(2):
        end = match.group(2)
    else:
        # A single token: FY26 -> FY26, FY2026 -> FY26.
        end = start
    try:
        end_year = int(end)
    except ValueError:
        return None
    if end_year < 100:
        end_year += 2000
    elif end_year < 1000:
        return None
    return f"FY{end_year % 100:02d}"


def parse_period_label(label: Any) -> Optional[str]:
    """``Mar-26`` / ``Mar 2026`` / ``31-Mar-2026`` -> ``YYYY-MM-DD`` period end."""
    text = str(label or "").strip()
    if not text:
        return None
    iso = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).isoformat()
        except ValueError:
            return None
    if re.match(r"^\d{8}$", text):
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
        except ValueError:
            return None

    tokens = re.findall(r"[A-Za-z]+|\d+", text)
    month = None
    for token in tokens:
        if token.isdigit():
            continue
        month = _MONTH_ABBR.get(token.lower()[:3])
        if month is not None:
            break
    if month is None:
        return None

    digits = [t for t in tokens if t.isdigit()]
    four_digit = [d for d in digits if len(d) == 4]
    day = None
    if four_digit:
        year = int(four_digit[0])
        for token in digits:
            if token == four_digit[0]:
                continue
            value = int(token)
            if 1 <= value <= 31:
                day = value
                break
    else:
        if not digits:
            return None
        year = int(digits[-1]) if len(digits[-1]) == 4 else int(digits[-1]) + 2000
        for token in digits[:-1]:
            value = int(token)
            if 1 <= value <= 31:
                day = value
                break
    if day is not None:
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day).isoformat()


def _month_index(iso_date: str) -> int:
    year, month, _ = (int(part) for part in iso_date.split("-"))
    return year * 12 + month


def _infer_kind(labels: Sequence[Any]) -> str:
    """Quarterly vs half-yearly, read from the cadence of the period labels.

    The shortest gap between dated labels decides: ~3 months apart is quarterly,
    ~6 months is half-yearly (SME norm).  A single dated column cannot reveal its
    cadence and is treated as half-yearly, the SME default.
    """
    dated = []
    for label in labels:
        if not label or _is_fy_label(label):
            continue
        iso = parse_period_label(label)
        if iso:
            dated.append(iso)
    dated = sorted(set(dated))
    if len(dated) >= 2:
        gaps = [_month_index(b) - _month_index(a) for a, b in zip(dated, dated[1:])]
        return KIND_QUARTERLY if min(gaps) <= 4 else KIND_HALF_YEARLY
    return KIND_HALF_YEARLY


def _supplementary_labels(payload: Any) -> List[str]:
    """Quarter labels from ``resultinS`` (``LQ``/``SQ``), which expose the cadence.

    Verified live on AFCOM 544224: ``col2`` is blank and ``col4`` is the FY
    total, so the quarterly presentation only shows up in this table.
    """
    rows = payload.get("resultinS") if isinstance(payload, dict) else None
    if isinstance(rows, dict):
        rows = [rows]
    labels: List[str] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in ("LQ", "SQ", "lq", "sq"):
                label = _clean_str(row.get(key))
                if label:
                    labels.append(label)
    return labels


def _fiscal_quarter(period_end: str) -> str:
    """``2026-03-31`` -> ``FY26-Q4`` (Indian fiscal year ending in March)."""
    year, month, _ = (int(part) for part in period_end.split("-"))
    quarter = {3: 4, 6: 1, 9: 2, 12: 3}.get(month, 4)
    fy_year = year if month == 3 else year + 1
    return f"FY{fy_year % 100:02d}-Q{quarter}"


def _fy_end_date(label: Any) -> Optional[str]:
    """``FY25-26`` -> ``2026-03-31`` (the Indian fiscal year ends in March)."""
    fiscal_year = fiscal_year_label(label)
    if fiscal_year is None:
        return None
    return f"{2000 + int(fiscal_year[2:]):04d}-03-31"


# --------------------------------------------------------------------------
# Fetcher plumbing
# --------------------------------------------------------------------------
Fetcher = Callable[..., Any]

_default_fetcher_cache: Optional[Fetcher] = None
_default_fetcher_lock = threading.Lock()


def _default_fetcher() -> Optional[Fetcher]:
    """The shared ``bse_json`` helper, bound to a PER-THREAD warmed session.

    A ``curl_cffi`` Session is not safe for concurrent use, so ``workers>1``
    must not share one connection pool. The pacing floor already lives in
    ``bse_client._pace`` (thread-local), so this wrapper only owns the session.
    """
    global _default_fetcher_cache
    if _default_fetcher_cache is not None:
        return _default_fetcher_cache
    with _default_fetcher_lock:
        if _default_fetcher_cache is None:
            try:
                from reality_engine.ingestion.bse_client import BSEClient, bse_json
            except Exception as exc:  # pragma: no cover - only when the layer is absent
                logger.warning("BSE JSON layer unavailable: %s", exc)
                return None

            tls = threading.local()

            def _thread_bound_fetcher(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
                session = getattr(tls, "session", None)
                if session is None:
                    client = BSEClient()          # its own connection pool per thread
                    if not getattr(client, "_warmed_up", False):
                        client._warmup_session()
                    session = tls.session = client.session
                return bse_json(path, params=params, session=session)

            _default_fetcher_cache = _thread_bound_fetcher
    return _default_fetcher_cache


def _resolve_fetcher(fetcher: Optional[Fetcher]) -> Optional[Fetcher]:
    return fetcher if fetcher is not None else _default_fetcher()


def _status_false_message(payload: Any) -> Optional[str]:
    if isinstance(payload, dict) and str(payload.get("Status")).strip().lower() == "false":
        return str(payload.get("Message") or "Status:false")
    return None


def _fetch_json(fetcher: Optional[Fetcher], url: str, params: Dict[str, Any],
                errors: List[Dict[str, Any]], label: str) -> Any:
    payload, message = _fetch_json_raw(fetcher, url, params)
    if payload is None:
        errors.append({"endpoint": label, "error": message or "no_data"})
    return payload


def _fetch_json_raw(fetcher: Optional[Fetcher], url: str,
                    params: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """GET one endpoint; returns (payload, error message).  Never raises."""
    if fetcher is None:
        return None, "fetcher_unavailable"
    try:
        payload = fetcher(url, params)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    message = _status_false_message(payload)
    if message is not None:
        return None, message
    if payload is None:
        return None, "no_data"
    return payload, None


class _Pacer:
    """Per-thread request spacer.

    Was process-wide, which serialised every worker and made ``workers=4`` no
    faster than ``workers=1`` (measured 16.3 s/scrip either way). Thread-local
    state keeps each connection's floor while letting workers run concurrently.
    """

    def __init__(self, pace: float):
        self.pace = max(0.0, float(pace or 0.0))
        self._state = threading.local()

    def wait(self) -> None:
        if self.pace <= 0:
            return
        last = getattr(self._state, "last", 0.0)
        delay = last + self.pace - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._state.last = time.monotonic()


_ENDPOINT_KEYS = (
    ("comheadernew", "header"),
    ("tabresults_par", "results"),
    ("tabresults_shp", "shp"),
    ("corporatesshpsecuritybeta", "shp"),
    ("shppubshold", "shp"),
    ("promoternandgroup", "shp"),
    ("promotern", "shp"),
    ("annsubcategorygetdata", "announcements"),
)


def _endpoint_key(url: Any) -> str:
    text = str(url or "").lower()
    for needle, key in _ENDPOINT_KEYS:
        if needle in text:
            return key
    return "other"


class _CountingFetcher:
    """Wraps a fetcher: shared pacing plus per-endpoint call/success counts.

    Used by :func:`fetch_universe` for the run report; errors are converted to a
    ``None`` payload so a single flaky call can never abort a scrip.
    """

    def __init__(self, fetcher: Fetcher, pacer: _Pacer, lock: threading.Lock,
                 stats: Dict[str, Dict[str, int]]):
        self._fetcher = fetcher
        self._pacer = pacer
        self._lock = lock
        self._stats = stats

    def __call__(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        key = _endpoint_key(path)
        self._pacer.wait()
        try:
            payload = self._fetcher(path, params)
        except Exception as exc:
            logger.warning("BSE fetch error on %s: %s", path, exc)
            payload = None
        with self._lock:
            bucket = self._stats.setdefault(key, {"calls": 0, "ok": 0})
            bucket["calls"] += 1
            if payload is not None:
                bucket["ok"] += 1
        return payload


# --------------------------------------------------------------------------
# 1. Sector identity
# --------------------------------------------------------------------------
def fetch_header(bse_code: Any, fetcher: Optional[Fetcher] = None) -> Optional[Dict[str, Any]]:
    """Fetch scrip identity/sector from ``ComHeadernew``; None when BSE has no answer."""
    code = str(bse_code).strip()
    if not code:
        return None
    resolved = _resolve_fetcher(fetcher)
    payload, message = _fetch_json_raw(resolved, EP_HEADER, {"scripcode": code})
    if payload is None:
        logger.info("BSE header unavailable for %s: %s", code, message)
        return None
    obj = _unwrap_object(payload)
    if not isinstance(obj, dict) or not obj:
        return None

    security_id = _clean_str(_row_lookup(obj, ("securityid", "scrip_id", "scripcode")))
    return {
        "bse_code": _clean_str(_row_lookup(obj, ("securitycode", "scripcode", "scripcd"))) or code,
        "security_id": security_id,
        "symbol": security_id,
        "name": _clean_str(_row_lookup(
            obj, ("securityname", "scripname", "issuername", "companyname", "slongname", "coname"))),
        "isin": _clean_str(_row_lookup(obj, ("isin", "isincode"))),
        "industry": _clean_str(_row_lookup(obj, ("industry",))),
        "industry_new": _clean_str(_row_lookup(obj, ("industrynew", "newindustry"))),
        "sector": _clean_str(_row_lookup(obj, ("sector",))),
        "igroup": _clean_str(_row_lookup(obj, ("igroup",))),
        "isubgroup": _clean_str(_row_lookup(obj, ("isubgroup",))),
        "group": _clean_str(_row_lookup(obj, ("group",))),
        "face_value": _to_float(_row_lookup(obj, ("faceval", "facevalue"))),
        "eps": _to_float(_row_lookup(obj, ("eps",))),
        "ceps": _to_float(_row_lookup(obj, ("ceps", "cashedeps", "cash_eps"))),
        "pe": _to_float(_row_lookup(obj, ("pe", "peratio", "p_e"))),
        "opm_pct": _to_float(_row_lookup(obj, ("opm",))),
        "npm_pct": _to_float(_row_lookup(obj, ("npm",))),
        "pb": _to_float(_row_lookup(obj, ("pb",))),
        "roe_pct": _to_float(_row_lookup(obj, ("roe",))),
        "con_eps": _to_float(_row_lookup(obj, ("coneps",))),
        "con_ceps": _to_float(_row_lookup(obj, ("conceps",))),
        "con_pe": _to_float(_row_lookup(obj, ("conpe",))),
        "con_opm_pct": _to_float(_row_lookup(obj, ("conopm",))),
        "con_npm_pct": _to_float(_row_lookup(obj, ("connpm",))),
        "con_pb": _to_float(_row_lookup(obj, ("conpb",))),
        "con_roe_pct": _to_float(_row_lookup(obj, ("conroe",))),
    }


# --------------------------------------------------------------------------
# 2. Financial results
# --------------------------------------------------------------------------
_RESULT_FIELDS = (
    ("cash_eps", re.compile(r"^cash\s*eps")),
    ("eps", re.compile(r"^(basic\s*|diluted\s*)?eps")),
    ("revenue", re.compile(r"^(total\s*)?(revenue|income|sales|turnover)")),
    ("net_profit", re.compile(r"^net\s*profit")),
    ("opm_pct", re.compile(r"^(opm|operating\s*(profit\s*)?margin|pbdit)")),
    ("npm_pct", re.compile(r"^(npm|net\s*profit\s*margin|npat\s*margin)")),
)


def _parse_result_rows(entries: Any) -> Dict[str, Dict[str, Optional[float]]]:
    """``resultinCr``/``resultinM`` rows -> {field: {v1, v2, v3}}."""
    rows: Dict[str, Dict[str, Optional[float]]] = {}
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return rows
    for row in entries:
        if not isinstance(row, dict):
            continue
        title = _norm_key(_row_lookup(row, ("title", "particulars", "name", "field")))
        if not title:
            continue
        title = title.replace("%", "")
        for field, pattern in _RESULT_FIELDS:
            if pattern.match(title):
                rows[field] = {
                    "v1": _to_float(_row_lookup(row, ("v1", "value1", "col2"))),
                    "v2": _to_float(_row_lookup(row, ("v2", "value2", "col3"))),
                    "v3": _to_float(_row_lookup(row, ("v3", "value3", "col4"))),
                }
                break
    return rows


def _reconcile_scope(labels: Dict[str, Optional[str]],
                     rows: Dict[str, Dict[str, Optional[float]]]) -> str:
    """``halves`` when v1/v2 are halves of the FY, else ``quarters``/``unknown``.

    The labels decide when they can: two dated columns ~3 months apart are
    consecutive quarters, ~6 months apart are the two halves.  BSE's blank-col2
    SME shape leaves one dated column, and there the revenue coverage decides —
    halves reach the FY total, quarters reach about half of it.
    """
    dated = []
    for column in ("col2", "col3"):
        label = labels.get(column)
        if label and not _is_fy_label(label):
            period_end = parse_period_label(label)
            if period_end:
                dated.append(period_end)
    dated = sorted(set(dated))
    if len(dated) >= 2:
        gap = _month_index(dated[-1]) - _month_index(dated[0])
        return "halves" if gap >= 5 else "quarters"
    revenue = rows.get("revenue") or {}
    v1, v2, v3 = revenue.get("v1"), revenue.get("v2"), revenue.get("v3")
    if v1 is None or v2 is None or not v3:
        return "unknown"
    return "halves" if (v1 + v2) / abs(v3) >= RECONCILE_MIN_FY_COVERAGE else "quarters"


def _fy_coverage(rows: Dict[str, Dict[str, Optional[float]]]) -> Optional[float]:
    """Revenue (v1 + v2) / v3 — ~1.0 for a half-yearly presentation, ~0.5 quarterly."""
    revenue = rows.get("revenue") or {}
    v1, v2, v3 = revenue.get("v1"), revenue.get("v2"), revenue.get("v3")
    if v1 is None or v2 is None or not v3:
        return None
    return round((v1 + v2) / abs(v3), 4)


def _reconcile(rows: Dict[str, Dict[str, Optional[float]]], labels: Dict[str, Optional[str]]
               ) -> List[Dict[str, Any]]:
    """v1 + v2 vs the FY total v3 for the additive lines.

    The check is on the VALUES: an FY label on ``col4`` and three numbers is
    enough (AFCOM 544224 serves a blank ``col2`` label and still fills v1, and
    392.86 + 240.28 must be seen against its 583.11 FY total).  It only applies
    when the dated columns are halves of the FY — two quarters never add up to a
    year — and when a figure is missing there is nothing to check, so no
    mismatch is invented.
    """
    fy_label = labels.get("col4")
    if not fy_label or not _is_fy_label(fy_label):
        return []
    if _reconcile_scope(labels, rows) != "halves":
        return []
    mismatches: List[Dict[str, Any]] = []
    for field in ("revenue", "net_profit", "eps", "cash_eps"):
        values = rows.get(field)
        if not values:
            continue
        v1, v2, v3 = values.get("v1"), values.get("v2"), values.get("v3")
        if v1 is None or v2 is None or v3 is None:
            continue
        total = v1 + v2
        tolerance = max(RECONCILE_ABS_TOL, abs(v3) * RECONCILE_REL_TOL)
        delta = total - v3
        if abs(delta) > tolerance:
            mismatches.append({
                "label": str(fy_label),
                "field": field,
                "sum_v1_v2": round(total, 4),
                "total_v3": round(v3, 4),
                "delta": round(delta, 4),
                "delta_pct": round(delta / v3 * 100.0, 4) if v3 else None,
            })
    return mismatches


def _m_table_scale(crore_rows: Dict[str, Dict[str, Optional[float]]],
                   rupee_rows: Dict[str, Dict[str, Optional[float]]]) -> float:
    """Factor converting ``resultinM`` values to crore, measured from the payload.

    Only the additive amount lines are measured — EPS and the margins are quoted
    in the same unit in both tables, so a ratio over them would read 1.0.
    """
    ratios = []
    for field in _M_TABLE_AMOUNT_FIELDS:
        crore = crore_rows.get(field) or {}
        rupees = rupee_rows.get(field) or {}
        for slot in ("v1", "v2", "v3"):
            crore_value, rupee_value = crore.get(slot), rupees.get(slot)
            if crore_value and rupee_value:
                ratios.append(crore_value / rupee_value)
    if not ratios:
        return RESULTIN_M_TO_CR
    ratios.sort()
    median = ratios[len(ratios) // 2]
    for candidate in (RESULTIN_M_TO_CR, 1e-7):
        if candidate * 0.85 <= median <= candidate * 1.15:
            return candidate
    logger.warning("BSE resultinM scale %r unrecognised; using %r", median, RESULTIN_M_TO_CR)
    return RESULTIN_M_TO_CR


def fetch_results(bse_code: Any, fetcher: Optional[Fetcher] = None) -> Dict[str, Any]:
    """Fetch the BSE result table for one scrip, labels read (never assumed).

    Both statement tables are parsed.  ``resultinM`` (millions of rupees) is the
    value source whenever BSE serves it — the same filing at finer precision,
    converted back to crore by a factor measured from the payload — and the
    crore table is reconciled as well, so no mismatch is ever silent.

    Returns ``{"periods": [...], "reconciled": bool, "mismatches": [...],
    "cr_reconciled": bool, "cr_mismatches": [...], "value_table": ...}``; never
    raises.
    """
    code = str(bse_code).strip()
    out: Dict[str, Any] = {
        "periods": [], "reconciled": True, "mismatches": [],
        "cr_reconciled": True, "cr_mismatches": [],
        "value_table": None, "value_scale": None, "labels": {}, "errors": [],
    }
    errors = out["errors"]
    if not code:
        errors.append({"endpoint": "TabResults_PAR", "error": "empty_scripcode"})
        return out

    resolved = _resolve_fetcher(fetcher)
    payload = _fetch_json(resolved, EP_RESULTS, {"scripcode": code, "tabtype": "RESULTS"},
                          errors, "TabResults_PAR")
    if payload is None:
        return out
    payload = _unwrap_object(payload)
    if not isinstance(payload, dict):
        errors.append({"endpoint": "TabResults_PAR", "error": "unexpected_payload_shape"})
        return out

    labels = {
        "col2": _clean_str(payload.get("col2")),
        "col3": _clean_str(payload.get("col3")),
        "col4": _clean_str(payload.get("col4")),
    }
    out["labels"] = labels

    crore_rows = _parse_result_rows(payload.get("resultinCr"))
    rupee_rows = _parse_result_rows(payload.get("resultinM"))
    if not crore_rows and not rupee_rows:
        errors.append({"endpoint": "TabResults_PAR", "error": "no_result_rows"})
        return out

    crore_mismatches = _reconcile(crore_rows, labels)
    out["cr_mismatches"] = crore_mismatches
    out["cr_reconciled"] = not crore_mismatches

    if rupee_rows:
        chosen, table = rupee_rows, "resultinM"
        scale = _m_table_scale(crore_rows, rupee_rows) if crore_rows else RESULTIN_M_TO_CR
        mismatches = _reconcile(rupee_rows, labels)
    else:
        chosen, table, scale = crore_rows, "resultinCr", 1.0
        mismatches = crore_mismatches

    out["value_table"] = table
    out["value_scale"] = scale
    out["mismatches"] = mismatches
    out["reconciled"] = not mismatches
    # ~1.0 when the dated columns are halves of the FY, ~0.5 when they are two
    # consecutive quarters (in which case v1 + v2 vs v3 is not a valid check).
    out["fy_coverage"] = _fy_coverage(chosen)

    kind = _infer_kind([labels.get("col2"), labels.get("col3"), labels.get("col4")]
                       + _supplementary_labels(payload))
    out["kind"] = kind
    periods: List[Dict[str, Any]] = []
    for slot, column in (("v1", "col2"), ("v2", "col3"), ("v3", "col4")):
        label = labels.get(column)
        if not label:
            continue
        if _is_fy_label(label):
            period_kind, period_end = KIND_FY, None
        else:
            period_end = parse_period_label(label)
            if period_end is None:
                # A label we cannot read is never guessed into a period.
                errors.append({"endpoint": "TabResults_PAR",
                               "error": f"unparsed_period_label:{label}"})
                continue
            period_kind = kind
        period = {
            "label": label,
            "kind": period_kind,
            "period_end": period_end,
            "revenue": _scaled(chosen.get("revenue", {}).get(slot), scale),
            "net_profit": _scaled(chosen.get("net_profit", {}).get(slot), scale),
            "eps": chosen.get("eps", {}).get(slot),
            "cash_eps": chosen.get("cash_eps", {}).get(slot),
            "opm_pct": chosen.get("opm_pct", {}).get(slot),
            "npm_pct": chosen.get("npm_pct", {}).get(slot),
        }
        if all(period[key] is None
               for key in ("revenue", "net_profit", "eps", "cash_eps", "opm_pct", "npm_pct")):
            # A column with no numbers at all is not a filing.
            continue
        periods.append(period)
    if not periods:
        errors.append({"endpoint": "TabResults_PAR", "error": "no_result_values"})
    else:
        # BSE ships malformed FY labels (ABB 500002 answers "FY25-25" beside a
        # Mar-26 quarter, i.e. an FY that ended a year before the periods it is
        # meant to total).  A quarterly column legitimately sits AFTER the FY
        # total's year, so the test is one-sided: the FY may not end before the
        # EARLIEST period shown.
        earliest_period_end = min((p["period_end"] for p in periods if p["period_end"]),
                                  default=None)
        for period in periods:
            if period["kind"] != KIND_FY:
                continue
            fy_end = _fy_end_date(period["label"])
            consistent = not (fy_end and earliest_period_end and fy_end < earliest_period_end)
            period["label_consistent"] = consistent
            if not consistent:
                errors.append({"endpoint": "TabResults_PAR",
                               "error": f"fy_label_precedes_period:{period['label']}"})
    out["periods"] = periods
    return out


def _scaled(value: Optional[float], scale: float) -> Optional[float]:
    if value is None:
        return None
    return round(value * scale, 4) if scale != 1.0 else value


# --------------------------------------------------------------------------
# 3. Shareholding
# --------------------------------------------------------------------------
_PCT_KEYS = ("fldtotalpercentageofabc2", "fldtotalvotingrightspercent",
             "percentage", "percent", "pct", "shareholding")
_NAME_KEYS = ("fldshareholdername", "shareholdername", "name", "holder",
              "fldshortname", "particulars")
_CODE_KEYS = ("fldcode", "code")
_CATEGORY_KEYS = ("fldshortcatg", "fldshortcategory", "fldcategory", "category", "fldshortname")
_SUBCATEGORY_KEYS = ("fldsubcategory", "subcategory")
_LEVEL_KEYS = ("fldlevel", "level")

# BSE's SHP detail rows: Table1 of each SHP endpoint, keyed by Fld_* codes.
_SHP_PROMOTER_CODES = ("sta1a2", "sta1", "sta2")
_SHP_PUBLIC_CODES = ("stb1b2b3",)
_SHP_TOTAL_CODES = ("stabc",)


def _shp_table_rows(payload: Any) -> List[Dict[str, Any]]:
    """Rows of the SHP detail table (``Table1``) — the Fld_* rows BSE fills."""
    if isinstance(payload, dict):
        for key in ("Table1", "Table"):
            rows = payload.get(key)
            if isinstance(rows, list) and any(
                    isinstance(row, dict)
                    and any(str(k).lower().startswith("fld_") for k in row)
                    for row in rows):
                return [row for row in rows if isinstance(row, dict)]
    return _table_rows(payload)


def _shp_pct(row: Dict[str, Any]) -> Optional[float]:
    """Shareholding percentage of one SHP row; None when BSE served no percentage."""
    return _to_float(_row_lookup(row, _PCT_KEYS))


def _pick_latest_quarter(payload: Any) -> Tuple[Optional[int], Optional[str]]:
    """Latest ``(Qtr_Id, Fld_qtrname)`` from the SHP filing index."""
    best: Optional[Tuple[int, str]] = None
    for row in _table_rows(payload):
        qtr_id = _to_float(_row_lookup(row, ("qtrid", "qtr_id", "qtrcode", "qtr")))
        label = _clean_str(_row_lookup(row, ("fldqtrname", "qtrname", "quarter", "qtrname1")))
        if qtr_id is None or label is None:
            continue
        candidate = (int(qtr_id), label)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is not None:
        return best
    # A dict keyed by quarter name -> Qtr_Id.
    if isinstance(payload, dict):
        for key, value in payload.items():
            qtr_id = _to_float(value)
            if qtr_id is None or not str(key).strip():
                continue
            candidate = (int(qtr_id), str(key).strip())
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is not None:
        return best
    return None, None


def _shp_aggregate(payload: Any) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """(promoter, public, grand total) from the SHP aggregate payload."""
    promoter = public = total = None
    for row in _shp_table_rows(payload):
        code = _norm_key(_row_lookup(row, _CODE_KEYS))
        name = _norm_key(_row_lookup(row, _CATEGORY_KEYS))
        pct = _shp_pct(row)
        if pct is None:
            continue
        if code in _SHP_PROMOTER_CODES or name.startswith("promoterandpromotergroup"):
            promoter = pct
        elif code in _SHP_PUBLIC_CODES or name.startswith("publicshareholder"):
            public = pct
        elif code in _SHP_TOTAL_CODES or name.startswith("grandtotal"):
            total = pct
    if promoter is None and public is None and total is None:
        # Other BSE shapes nest the totals under named keys.
        promoter = _find_pct(payload, ("promoter", "promotertotal", "promoterandpromotergroup"))
        public = _find_pct(payload, ("public", "publictotal", "publicshareholder"))
        total = _find_pct(payload, ("grandtotal", "total", "totalholding"))
    return promoter, public, total


def _tab_shp_rows(payload: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if isinstance(payload, dict) and _row_lookup(payload, ("promoter", "promotertotal")) is not None:
        rows.append(payload)
    rows.extend(row for row in _table_rows(payload)
                if _row_lookup(row, ("promoter", "promotertotal")) is not None)
    return rows


def _tab_shp_row(payload: Any) -> Optional[Dict[str, Any]]:
    """Newest ``TabResults_SHP`` row that is not BSE's never-filed template.

    The newest quarter is frequently the placeholder even for a scrip whose
    older quarters are filed, so a placeholder is skipped rather than reported
    as "not filed".
    """
    rows = _tab_shp_rows(payload)
    for row in rows:
        promoter = _to_float(_row_lookup(row, ("promoter", "promotertotal")))
        total = _to_float(_row_lookup(row, ("total", "grandtotal")))
        if not _is_placeholder_shp(promoter, total):
            return row
    return rows[0] if rows else None


def _is_placeholder_shp(promoter: Optional[float], total: Optional[float]) -> bool:
    """BSE's never-filed SHP template: no promoter and/or a 0.00-or-100.00 total.

    A missing promoter is never rendered as ``0.00%`` data — it is "not filed".
    """
    if promoter is None or promoter <= 0.0:
        return True
    if total is not None and total <= 0.0:
        return True
    return False


def _shp_level_key(row: Dict[str, Any]) -> str:
    return _norm_key(_row_lookup(row, _LEVEL_KEYS))


def _parse_public_split(payload: Any) -> Tuple[Optional[float], Optional[float], Optional[float],
                                               List[Dict[str, Any]]]:
    """(dii, fii, retail, named holders) from ``Corp_shpSec_SHPPubShold_ng``.

    Each bucket's ``Sub Total`` row is the aggregate; the section header rows
    (which BSE fills with zeros) are never mistaken for it, and when no sub
    total is served the largest non-zero row of that bucket is used.
    """
    buckets: Dict[str, List[float]] = {"dii": [], "fii": [], "retail": []}
    subtotals: Dict[str, float] = {}
    holders: List[Dict[str, Any]] = []
    for row in _shp_table_rows(payload):
        pct = _shp_pct(row)
        if pct is None:
            continue
        name = _clean_str(_row_lookup(row, _NAME_KEYS))
        subcategory = _norm_key(_row_lookup(row, _SUBCATEGORY_KEYS))
        level = _shp_level_key(row)
        if name and not level.startswith("subtotal"):
            holders.append({"name": name, "pct": pct})
            continue
        if subcategory.startswith("institutionsdomestic"):
            bucket = "dii"
        elif subcategory.startswith("institutionsforeign"):
            bucket = "fii"
        elif subcategory.startswith("noninstitutions"):
            bucket = "retail"
        else:
            continue
        buckets[bucket].append(pct)
        if level.startswith("subtotal"):
            subtotals[bucket] = pct

    def resolve(bucket: str) -> Optional[float]:
        if bucket in subtotals:
            return subtotals[bucket]
        positives = [pct for pct in buckets[bucket] if pct > 0]
        return max(positives) if positives else None

    return resolve("dii"), resolve("fii"), resolve("retail"), holders


def _parse_promoters(payload: Any) -> List[Dict[str, Any]]:
    """Named promoters and their percentages (Sub Total rows excluded)."""
    promoters: List[Dict[str, Any]] = []
    for row in _shp_table_rows(payload):
        name = _clean_str(_row_lookup(row, _NAME_KEYS))
        if not name or _shp_level_key(row).startswith("subtotal"):
            continue
        pct = _shp_pct(row)
        if pct is None:
            continue
        promoters.append({"name": name, "pct": pct})
    return promoters


def fetch_shp(bse_code: Any, fetcher: Optional[Fetcher] = None) -> Dict[str, Any]:
    """Fetch the latest shareholding pattern; ``filed=False`` for never-filed scrips."""
    code = str(bse_code).strip()
    out: Dict[str, Any] = {
        "filed": False, "quarter": None, "qtr_id": None, "promoter_pct": None,
        "public_pct": None, "fii_pct": None, "dii_pct": None, "retail_pct": None,
        "holders": [], "promoters": [], "errors": [],
    }
    errors = out["errors"]
    if not code:
        errors.append({"endpoint": "CorporatesSHPSecuritybeta", "error": "empty_scripcode"})
        return out

    resolved = _resolve_fetcher(fetcher)
    index = _fetch_json(resolved, EP_SHP_INDEX, {"scripcode": code}, errors,
                        "CorporatesSHPSecuritybeta")
    qtr_id, qtr_label = _pick_latest_quarter(index) if index is not None else (None, None)

    promoter = public = total = None
    if qtr_id is not None:
        aggregate = _fetch_json(resolved, EP_SHP_INDEX, {"scripcode": code, "qtrid": qtr_id},
                                errors, "CorporatesSHPSecuritybeta?qtrid")
        if isinstance(aggregate, dict) and aggregate:
            promoter, public, total = _shp_aggregate(aggregate)

    tab = _fetch_json(resolved, EP_SHP_TAB, {"scripcode": code}, errors, "TabResults_SHP")
    tab_row = _tab_shp_row(tab)
    tab_promoter = _to_float(_row_lookup(tab_row, ("promoter", "promotertotal"))) if tab_row else None
    tab_public = _to_float(_row_lookup(tab_row, ("public", "publictotal"))) if tab_row else None
    tab_total = _to_float(_row_lookup(tab_row, ("total", "grandtotal"))) if tab_row else None
    tab_quarter = _clean_str(_row_lookup(tab_row, ("quarter", "qtr", "qtrname"))) if tab_row else None
    tab_placeholder = tab_row is not None and _is_placeholder_shp(tab_promoter, tab_total)

    if promoter is not None and promoter <= 0.0:
        promoter = None
    if promoter is None:
        # Only TabResults_SHP can say "never filed".
        if tab_row is None or tab_placeholder:
            out["quarter"] = qtr_label or tab_quarter
            return out
        promoter, public, total = tab_promoter, tab_public, tab_total
        source_quarter = tab_quarter
    else:
        source_quarter = qtr_label or tab_quarter
    if _is_placeholder_shp(promoter, total):
        out["quarter"] = qtr_label or tab_quarter
        return out

    out.update({
        "filed": True,
        "quarter": source_quarter,
        "qtr_id": qtr_id,
        "promoter_pct": promoter,
        "public_pct": public if public is not None else tab_public,
    })
    if out["public_pct"] is None and total is not None and promoter is not None:
        # Public shareholding is the complement of the promoter block; only used
        # when BSE itself gave the total (never invented from a missing value).
        out["public_pct"] = round(total - promoter, 4)

    if qtr_id is None:
        return out

    public_payload = _fetch_json(resolved, EP_SHP_PUBLIC,
                                 {"SCRIPCODE": code, "QtrCode": qtr_id}, errors,
                                 "Corp_shpSec_SHPPubShold_ng")
    dii, fii, retail, holders = _parse_public_split(public_payload)
    out["dii_pct"], out["fii_pct"], out["retail_pct"] = dii, fii, retail
    out["holders"] = holders

    promoter_payload = _fetch_json(resolved, EP_SHP_PROMOTER,
                                   {"SCRIPCODE": code, "QtrCode": qtr_id}, errors,
                                   "Corp_shpPromoterNGroup_ng")
    out["promoters"] = _parse_promoters(promoter_payload)
    return out


# --------------------------------------------------------------------------
# 4. Announcements
# --------------------------------------------------------------------------
_ANN_DATE_KEYS = ("newsdt", "dt", "dtfmt", "newdt", "announcementdate", "newstime", "date")
_ANN_CATEGORY_KEYS = ("categoryname", "newscategory", "catname", "category")
_ANN_SUBCATEGORY_KEYS = ("subcategoryname", "subcatname", "subcategory", "subcat")
_ANN_HEADLINE_KEYS = ("headline", "newssubject", "subject", "newsheading", "slongname",
                      "newstitle", "companyname")
_ANN_ATTACHMENT_KEYS = ("attachmentname", "attachname", "attachment", "filename", "attfilename")
_ANN_ID_KEYS = ("newsid", "newsno", "srno", "id")

_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y%m%d",
    "%d %b %Y", "%b %d, %Y", "%d-%b-%Y",
)


def _norm_ann_date(value: Any) -> Tuple[Optional[str], Optional[str]]:
    """(``YYYY-MM-DD``, raw) for a BSE announcement timestamp."""
    text = _clean_str(value)
    if text is None:
        return None, None
    if len(text) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10], text
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat(), text
        except ValueError:
            continue
    return None, text


def announcement_pdf_url(attachment: Any, live: bool = False) -> Optional[str]:
    """Public PDF URL for an announcement attachment name."""
    name = _clean_str(attachment)
    if not name:
        return None
    template = ANNOUNCEMENT_ATTACH_URL if live else ANNOUNCEMENT_PDF_URL
    return template.format(attachment=name)


def _normalise_announcement(row: Dict[str, Any], bse_code: str) -> Optional[Dict[str, Any]]:
    headline = _clean_str(_row_lookup(row, _ANN_HEADLINE_KEYS))
    attachment = _clean_str(_row_lookup(row, _ANN_ATTACHMENT_KEYS))
    date_iso, date_raw = _norm_ann_date(_row_lookup(row, _ANN_DATE_KEYS))
    news_id = _clean_str(_row_lookup(row, _ANN_ID_KEYS))
    if headline is None and attachment is None and date_iso is None and date_raw is None:
        return None
    return {
        "bse_code": bse_code,
        "date": date_iso,
        "date_raw": date_raw,
        "category": _clean_str(_row_lookup(row, _ANN_CATEGORY_KEYS)),
        "subcategory": _clean_str(_row_lookup(row, _ANN_SUBCATEGORY_KEYS)),
        "headline": headline,
        "attachment": attachment,
        "news_id": news_id,
        "pdf_url": announcement_pdf_url(attachment),
    }


def _ann_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        table = payload.get("Table")
        if isinstance(table, list):
            return [r for r in table if isinstance(r, dict)]
        data = payload.get("Table1")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return [r for r in _table_rows(payload)]


def _ann_rowcount(payload: Any) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    for key in ("Table", "Table1"):
        table = payload.get(key)
        if isinstance(table, list) and table and isinstance(table[0], dict):
            count = _to_float(_row_lookup(table[0], ("rowcnt", "rowcount", "totalrows", "total")))
            if count is not None:
                return int(count)
    count = _find_pct(payload, ("rowcnt", "rowcount"))
    return int(count) if count is not None else None


def _month_windows(today: date, months: int) -> List[Tuple[date, date]]:
    """Contiguous windows of at most 365 days covering the last ``months`` months.

    The endpoint rejects a wider range outright, so the requested coverage is
    split into equal windows that each stay inside the cap and leave no gap and
    no overlap (a tail shorter than a month is folded into its neighbour).
    """
    try:
        span_days = max(1, int(round(float(months) * 30.44)))
    except (TypeError, ValueError):
        span_days = MAX_ANNOUNCEMENT_WINDOW_DAYS
    # Inclusive of today, so a 12-month request is exactly one 365-day window.
    coverage_start = today - timedelta(days=span_days - 1)
    window_count = max(1, math.ceil(span_days / MAX_ANNOUNCEMENT_WINDOW_DAYS))
    step = math.ceil(span_days / window_count)
    windows: List[Tuple[date, date]] = []
    cursor = coverage_start
    while cursor <= today:
        end = min(cursor + timedelta(days=step - 1), today)
        windows.append((cursor, end))
        cursor = end + timedelta(days=1)
    return windows


def _ann_params(code: str, start: date, end: date, page: int) -> Dict[str, Any]:
    return {
        "pageno": page,
        "strCat": -1,
        "subcategory": -1,
        "strPrevDate": start.strftime("%Y%m%d"),
        "strToDate": end.strftime("%Y%m%d"),
        "strSearch": "P",
        "strscrip": code,
        "strType": "C",
    }


def _collect_window(fetcher: Optional[Fetcher], code: str, start: date, end: date,
                    errors: List[Dict[str, Any]], stats: Dict[str, int],
                    depth: int = 0) -> List[Dict[str, Any]]:
    """One window, paginated; a range-cap answer splits the window instead of failing."""
    rows: List[Dict[str, Any]] = []
    page = 1
    total: Optional[int] = None
    while page <= ANN_MAX_PAGES:
        payload, message = _fetch_json_raw(fetcher, EP_ANNOUNCEMENTS,
                                           _ann_params(code, start, end, page))
        if payload is None:
            if page == 1:
                span = (end - start).days + 1
                if message and "12 month" in message.lower() and span > 31 and depth < 4:
                    mid = start + timedelta(days=span // 2)
                    stats["windows_shrunk"] = stats.get("windows_shrunk", 0) + 1
                    logger.info("BSE window %s..%s rejected (%s); splitting", start, end, message)
                    rows.extend(_collect_window(fetcher, code, start, mid, errors, stats, depth + 1))
                    rows.extend(_collect_window(fetcher, code, mid + timedelta(days=1), end,
                                                errors, stats, depth + 1))
                    return rows
                if page == 1 and message != "no_data":
                    errors.append({"endpoint": "AnnSubCategoryGetData", "error": message or "no_data"})
            elif rows:
                errors.append({"endpoint": "AnnSubCategoryGetData",
                               "error": f"page_{page}_failed:{message or 'no_data'}"})
            break
        stats["pages"] = stats.get("pages", 0) + 1
        page_rows = _ann_rows(payload)
        if total is None:
            total = _ann_rowcount(payload)
        for row in page_rows:
            normalised = _normalise_announcement(row, code)
            if normalised is not None:
                rows.append(normalised)
        if not page_rows:
            break
        if total is not None and len(rows) >= total:
            break
        if total is None and len(page_rows) < ANN_PAGE_SIZE:
            break
        page += 1
    return rows


def _collect_announcements(code: str, months: int, fetcher: Optional[Fetcher],
                           errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    resolved = _resolve_fetcher(fetcher)
    if resolved is None:
        errors.append({"endpoint": "AnnSubCategoryGetData", "error": "fetcher_unavailable"})
        return []
    try:
        month_count = max(1, int(months))
    except (TypeError, ValueError):
        month_count = 12
    today = date.today()
    stats: Dict[str, int] = {}
    collected: List[Dict[str, Any]] = []
    seen = set()
    for start, end in _month_windows(today, month_count):
        for row in _collect_window(resolved, code, start, end, errors, stats):
            key = row.get("news_id") or (row.get("date"), row.get("headline"), row.get("attachment"))
            if key in seen:
                continue
            seen.add(key)
            collected.append(row)
    return collected


def fetch_announcements(bse_code: Any, months: int = 12,
                        fetcher: Optional[Fetcher] = None) -> List[Dict[str, Any]]:
    """Corporate announcements for the last ``months`` months (12-month capped, paged)."""
    code = str(bse_code).strip()
    if not code:
        return []
    return _collect_announcements(code, months, fetcher, [])


# --------------------------------------------------------------------------
# 5. Persistence
# --------------------------------------------------------------------------
def _table_columns(conn: Any, table: str) -> set:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _upsert(conn: Any, table: str, rows: List[Dict[str, Any]], key_columns: Sequence[str]) -> int:
    """Upsert rows on ``key_columns``, writing only columns that exist."""
    if not rows:
        return 0
    columns = _table_columns(conn, table)
    if not columns:
        return 0
    key_columns = tuple(key_columns)
    written = 0
    seen_keys = set()
    for row in rows:
        filtered = {k: v for k, v in row.items() if k in columns}
        if any(filtered.get(key) is None for key in key_columns):
            continue
        identity = tuple(filtered[key] for key in key_columns)
        if identity in seen_keys:
            continue
        seen_keys.add(identity)
        names = list(filtered)
        placeholders = ", ".join(f":{name}" for name in names)
        updates = [name for name in names if name not in key_columns]
        sql = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})"
        if updates:
            sql += " ON CONFLICT({}) DO UPDATE SET {}".format(
                ", ".join(key_columns),
                ", ".join(f"{name} = excluded.{name}" for name in updates),
            )
        else:
            sql += f" ON CONFLICT({', '.join(key_columns)}) DO NOTHING"
        conn.execute(sql, filtered)
        written += 1
    return written


def _quarterly_rows(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    isin, symbol = result.get("isin"), result.get("symbol")
    rows = []
    for period in (result.get("results") or {}).get("periods", []):
        if period.get("kind") not in (KIND_QUARTERLY, KIND_HALF_YEARLY):
            continue
        period_end = period.get("period_end")
        if not period_end:
            continue
        rows.append({
            "isin": isin,
            "symbol": symbol,
            "quarter_end_date": period_end,
            "financial_year": _fiscal_quarter(period_end),
            "revenue_inr_cr": period.get("revenue"),
            "net_profit_inr_cr": period.get("net_profit"),
            "eps_inr": period.get("eps"),
            "pat_margin_pct": period.get("npm_pct"),
            "source": (SOURCE_QUARTERLY if period.get("kind") == KIND_QUARTERLY
                       else SOURCE_HALF_YEARLY),
        })
    return rows


def _annual_rows(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    isin, symbol = result.get("isin"), result.get("symbol")
    rows = []
    for period in (result.get("results") or {}).get("periods", []):
        if period.get("kind") != KIND_FY:
            continue
        # A malformed FY label that precedes the periods it totals is never
        # written as a fiscal year: it would land on another year's natural key.
        if period.get("label_consistent") is False:
            continue
        fiscal_year = fiscal_year_label(period.get("label"))
        if fiscal_year is None:
            continue
        rows.append({
            "isin": isin,
            "symbol": symbol,
            "fiscal_year": fiscal_year,
            "revenue_inr_cr": period.get("revenue"),
            "net_profit_inr_cr": period.get("net_profit"),
            "eps_inr": period.get("eps"),
            "opm_pct": period.get("opm_pct"),
            "npm_pct": period.get("npm_pct"),
            "source": (SOURCE_QUARTERLY
                       if (result.get("results") or {}).get("kind") == KIND_QUARTERLY
                       else SOURCE_HALF_YEARLY),
        })
    return rows


def _ownership_row(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ownership percentages only — never pledge / coverage / D-E / solvency gate."""
    shp = result.get("shp") or {}
    if not shp.get("filed"):
        return None
    if shp.get("promoter_pct") is None:
        return None
    return {
        "isin": result.get("isin"),
        "symbol": result.get("symbol"),
        "fiscal_year": fiscal_year_label(shp.get("quarter")) or _shp_fiscal_year(shp.get("quarter")),
        "promoter_holding_pct": shp.get("promoter_pct"),
        "fii_holding_pct": shp.get("fii_pct"),
        "dii_holding_pct": shp.get("dii_pct"),
        "public_holding_pct": shp.get("public_pct"),
        "last_evaluated_date": date.today().isoformat(),
    }


def _shp_fiscal_year(quarter: Any) -> Optional[str]:
    """``Mar-2026`` -> ``FY26``; None when the quarter label is unreadable."""
    period_end = parse_period_label(quarter)
    if not period_end:
        return None
    year, month, _ = (int(part) for part in period_end.split("-"))
    fy_year = year if month == 3 else year + 1
    # The forensic table stores one row per ISIN and requires a fiscal_year.
    return f"FY{fy_year % 100:02d}"


def persist_company(db: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    """Write financials + ownership for a :func:`fetch_company` payload, idempotently."""
    counts = {"quarterly": 0, "annual": 0, "ownership": 0}
    errors: List[Dict[str, Any]] = []
    manager = db if db is not None else db_manager
    if result.get("isin") is None or result.get("symbol") is None:
        errors.append({"endpoint": "persist", "error": "missing_isin_or_symbol"})
        return {"written": counts, "errors": errors}

    annual_rows = _annual_rows(result)
    for period in (result.get("results") or {}).get("periods", []):
        if period.get("kind") == KIND_FY and period.get("label_consistent") is False:
            errors.append({"endpoint": "persist",
                           "error": f"fy_label_contradicts_periods:{period.get('label')}"})
    ownership = _ownership_row(result)
    if ownership is not None and ownership.get("fiscal_year") is None:
        ownership["fiscal_year"] = _shp_fiscal_year(result.get("shp", {}).get("quarter"))
        if ownership["fiscal_year"] is None:
            ownership["fiscal_year"] = f"FY{date.today().year % 100:02d}"
    try:
        with manager.session() as conn:
            counts["quarterly"] = _upsert(
                conn, "quarterly_financials", _quarterly_rows(result),
                ("isin", "quarter_end_date"))
            counts["annual"] = _upsert(
                conn, "annual_financials", annual_rows, ("isin", "fiscal_year"))
            if ownership is not None:
                counts["ownership"] = _upsert(
                    conn, "company_forensic_health", [ownership], ("isin",))
    except Exception as exc:
        errors.append({"endpoint": "persist", "error": f"{type(exc).__name__}: {exc}"})
    return {"written": counts, "errors": errors}


# --------------------------------------------------------------------------
# 6. One scrip
# --------------------------------------------------------------------------
def fetch_company(bse_code: Any, symbol: Optional[str] = None, isin: Optional[str] = None,
                  db: Any = None, persist: bool = False, fetcher: Optional[Fetcher] = None,
                  months: int = 12) -> Dict[str, Any]:
    """Fetch everything BSE holds for one scrip; a null sub-call lands in ``errors``."""
    code = str(bse_code).strip()
    errors: List[Dict[str, Any]] = []

    resolved = _resolve_fetcher(fetcher)
    header = fetch_header(code, fetcher=resolved)
    if header is None:
        errors.append({"endpoint": "ComHeadernew", "error": "no_data"})

    results = fetch_results(code, fetcher=resolved)
    errors.extend(results.get("errors", []))
    shp = fetch_shp(code, fetcher=resolved)
    errors.extend(shp.get("errors", []))
    announcements = _collect_announcements(code, months, resolved, errors)

    resolved_isin = isin or (header or {}).get("isin")
    resolved_symbol = symbol or (header or {}).get("security_id") or code

    out: Dict[str, Any] = {
        "bse_code": code,
        "symbol": resolved_symbol,
        "isin": resolved_isin,
        "header": header,
        "results": results,
        "shp": shp,
        "announcements_count": len(announcements),
        "errors": errors,
    }

    if persist:
        if resolved_isin is None:
            errors.append({"endpoint": "persist", "error": "no_isin"})
        else:
            outcome = persist_company(db, out)
            out["persisted"] = outcome["written"]
            errors.extend(outcome["errors"])
    return out


# --------------------------------------------------------------------------
# 7. Universe
# --------------------------------------------------------------------------
def _select_universe(conn: Any, only_bse_only: bool, limit: int
                     ) -> Tuple[List[Dict[str, Any]], str]:
    """Universe rows + the selector actually used (provenance column may be absent)."""
    columns = _table_columns(conn, "master_companies")
    if only_bse_only:
        if "listing_source" in columns:
            where = "listing_source = 'BSE_ONLY' AND bse_code IS NOT NULL"
            selector = "listing_source='BSE_ONLY'"
        else:
            where = "nse_symbol IS NOT NULL AND bse_code IS NOT NULL"
            selector = "nse_symbol IS NOT NULL AND bse_code IS NOT NULL (listing_source absent)"
    else:
        where = "bse_code IS NOT NULL"
        selector = "bse_code IS NOT NULL"

    query = f"SELECT isin, nse_symbol, bse_code FROM master_companies WHERE {where} "
    query += "ORDER BY bse_code"
    if limit and int(limit) > 0:
        query += f" LIMIT {int(limit)}"
    try:
        rows = [dict(row) for row in conn.execute(query).fetchall()]
    except Exception as exc:
        logger.warning("BSE universe selection failed: %s", exc)
        return [], selector
    return [row for row in rows if _clean_str(row.get("bse_code"))], selector


def _load_checkpoint(path: Optional[Any]) -> set:
    if not path:
        return set()
    done = set()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                code = _clean_str(record.get("bse_code"))
                if code:
                    done.add(code)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("BSE checkpoint %s unreadable: %s", path, exc)
    return done


def fetch_universe(db: Any = None, limit: int = 0, dry_run: bool = True, workers: int = 1,
                   pace: float = 1.5, checkpoint_path: Optional[Any] = None,
                   only_bse_only: bool = True, fetcher: Optional[Fetcher] = None,
                   months: int = 12) -> Dict[str, Any]:
    """Fetch every admitted BSE security, resumable and paced; never raises.

    ``dry_run=True`` fetches but writes nothing.  ``checkpoint_path`` appends one
    JSON line per completed scrip, so a killed run resumes where it stopped.
    """
    started = time.monotonic()
    manager = db if db is not None else db_manager
    explicit_fetcher = fetcher is not None
    resolved = _resolve_fetcher(fetcher)
    effective_pace = float(pace or 0.0) if explicit_fetcher else 0.0
    pace_note = ("caller pacer" if explicit_fetcher else
                 "disabled: the shared bse_json already paces itself")

    with manager.session() as conn:
        universe, selector = _select_universe(conn, only_bse_only, limit)

    done = _load_checkpoint(checkpoint_path)
    pending = [row for row in universe if str(row.get("bse_code")).strip() not in done]

    lock = threading.Lock()
    endpoint_stats: Dict[str, Dict[str, int]] = {}
    errors: List[Dict[str, Any]] = []
    counters = {
        "scrips_processed": 0,
        "scrips_with_results": 0,
        "scrips_with_shp": 0,
        "scrips_no_filing": 0,
        "scrips_reconciled": 0,
        "scrips_unreconciled": 0,
        "scrips_cr_unreconciled": 0,
        "scrips_fy_label_flagged": 0,
        "announcements_total": 0,
        "periods_total": 0,
        "error_count": 0,
        "written": {"quarterly": 0, "annual": 0, "ownership": 0},
    }

    counting = _CountingFetcher(resolved, _Pacer(effective_pace), lock, endpoint_stats) \
        if resolved is not None else None

    checkpoint_handle = None
    if checkpoint_path:
        try:
            Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
            checkpoint_handle = open(checkpoint_path, "a", encoding="utf-8")
        except OSError as exc:
            logger.warning("BSE checkpoint %s unwritable: %s", checkpoint_path, exc)

    def _record_error(entry: Dict[str, Any]) -> None:
        counters["error_count"] += 1
        if len(errors) < PERSIST_ERROR_LIMIT:
            errors.append(entry)

    def _process(row: Dict[str, Any]) -> None:
        code = str(row.get("bse_code")).strip()
        try:
            result = fetch_company(code, symbol=row.get("nse_symbol"), isin=row.get("isin"),
                                   db=manager, persist=not dry_run, fetcher=counting,
                                   months=months)
        except Exception as exc:  # fetch_company never raises; belt and braces
            with lock:
                _record_error({"bse_code": code, "endpoint": "fetch_company",
                               "error": f"{type(exc).__name__}: {exc}"})
                counters["scrips_processed"] += 1
            return

        periods = (result.get("results") or {}).get("periods") or []
        results_summary = result.get("results") or {}
        filed = bool((result.get("shp") or {}).get("filed"))
        with lock:
            counters["scrips_processed"] += 1
            if periods:
                counters["scrips_with_results"] += 1
                if results_summary.get("reconciled"):
                    counters["scrips_reconciled"] += 1
                else:
                    counters["scrips_unreconciled"] += 1
                if results_summary.get("cr_reconciled") is False:
                    counters["scrips_cr_unreconciled"] += 1
                if any(period.get("kind") == KIND_FY
                       and period.get("label_consistent") is False for period in periods):
                    counters["scrips_fy_label_flagged"] += 1
            if filed:
                counters["scrips_with_shp"] += 1
            if not periods and not filed:
                counters["scrips_no_filing"] += 1
            counters["periods_total"] += len(periods)
            counters["announcements_total"] += int(result.get("announcements_count") or 0)
            for entry in result.get("errors", []):
                _record_error({"bse_code": code, **entry})
            for key, value in (result.get("persisted") or {}).items():
                counters["written"][key] = counters["written"].get(key, 0) + int(value or 0)
            if checkpoint_handle is not None:
                try:
                    checkpoint_handle.write(json.dumps({
                        "bse_code": code,
                        "ok": not result.get("errors"),
                        "periods": len(periods),
                        "filed": filed,
                        "announcements": int(result.get("announcements_count") or 0),
                        "ts": datetime.now().isoformat(timespec="seconds"),
                    }) + "\n")
                    checkpoint_handle.flush()
                except OSError as exc:
                    logger.warning("BSE checkpoint write failed: %s", exc)

    if resolved is None:
        _record_error({"endpoint": "bse_json", "error": "fetcher_unavailable"})
    else:
        worker_count = max(1, min(4, int(workers or 1)))
        if worker_count == 1:
            for row in pending:
                _process(row)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                list(pool.map(_process, pending))

    if checkpoint_handle is not None:
        try:
            checkpoint_handle.close()
        except OSError:
            pass

    elapsed = round(time.monotonic() - started, 3)
    return {
        "universe_size": len(universe),
        "universe_selector": selector,
        "scrips_processed": counters["scrips_processed"],
        "scrips_skipped_checkpoint": len(universe) - len(pending),
        "scrips_with_results": counters["scrips_with_results"],
        "scrips_with_shp": counters["scrips_with_shp"],
        "scrips_no_filing": counters["scrips_no_filing"],
        "scrips_reconciled": counters["scrips_reconciled"],
        "scrips_unreconciled": counters["scrips_unreconciled"],
        "scrips_cr_unreconciled": counters["scrips_cr_unreconciled"],
        "scrips_fy_label_flagged": counters["scrips_fy_label_flagged"],
        "periods_total": counters["periods_total"],
        "announcements_total": counters["announcements_total"],
        "endpoint_success": {key: bucket.get("ok", 0) for key, bucket in sorted(endpoint_stats.items())},
        "endpoint_calls": {key: bucket.get("calls", 0) for key, bucket in sorted(endpoint_stats.items())},
        "rows_written": counters["written"],
        "error_count": counters["error_count"],
        "errors": errors,
        "elapsed_sec": elapsed,
        "dry_run": bool(dry_run),
        "workers": max(1, min(4, int(workers or 1))),
        "pace": effective_pace,
        "pace_note": pace_note,
        "checkpoint_path": str(checkpoint_path) if checkpoint_path else None,
        "fetcher_available": resolved is not None,
    }
