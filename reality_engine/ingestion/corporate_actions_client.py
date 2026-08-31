"""
Corporate Actions Ingestion Client — official NSE corporate-actions feed.

Pulls the market-wide NSE corporate-actions API and normalizes each record into a
typed corporate action (DIVIDEND / BONUS / SPLIT / RIGHTS / BUYBACK / MERGER /
DEMERGER / INTEREST / AGM / OTHER). Persisted to ``corporate_actions`` with full
provenance (source = 'nse_official').

COVERAGE NOTE:
    NSE corporate-actions covers Dividend, Bonus, Split, Rights, Buyback, Merger,
    Demerger, Interest, AGM, etc. **Delisting is NOT present in this feed** and must
    be ingested from a separate source (flagged, never fabricated).

DESIGN:
    The API enforces a max date range, so we fetch in bounded date slices and merge.
    Fail-closed: a failed slice is logged and skipped; we never invent records.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    from curl_cffi import requests as _requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    import requests as _requests  # type: ignore
    _HAS_CURL_CFFI = False

from reality_engine.config import NSE_HEADERS

logger = logging.getLogger("reality_engine.corporate_actions_client")

NSE_CORP_ACTIONS_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
)

SOURCE_NSE_OFFICIAL = "nse_official"

# Normalization map: keyword (lower) -> action_type. Order matters (first match wins).
_ACTION_RULES: List[tuple] = [
    ("bonus", "BONUS"),
    ("split", "SPLIT"),
    ("right", "RIGHTS"),
    ("buy back", "BUYBACK"),
    ("buyback", "BUYBACK"),
    ("merger", "MERGER"),
    ("amalgamation", "MERGER"),
    ("demerger", "DEMERGER"),
    ("spin off", "DEMERGER"),
    ("interest", "INTEREST"),
    ("agm", "AGM"),
    ("dividend", "DIVIDEND"),
    ("distribution", "DIVIDEND"),
    ("payout", "DIVIDEND"),
]


def _normalize_action_type(subject: str) -> str:
    if not subject:
        return "OTHER"
    low = subject.lower()
    for kw, atype in _ACTION_RULES:
        if kw in low:
            return atype
    return "OTHER"


def _parse_date(value: Any) -> Optional[str]:
    """NSE dates look like '30-Apr-2026' or '-' / null. Return ISO or None."""
    if not value or value in ("-", "00-00-0000", "0000-00-00"):
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


class CorporateActionsClient:
    """Ingests NSE corporate actions for the full equity universe."""

    def __init__(self, slice_days: int = 180, max_retries: int = 3):
        if _HAS_CURL_CFFI:
            self.session = _requests.Session(impersonate="chrome120", verify=False)  # type: ignore[call-arg]
        else:
            self.session = _requests.Session()
            try:
                self.session.verify = False  # type: ignore[attr-defined]
            except Exception:
                pass
        self.session.headers.update(NSE_HEADERS)
        self.slice_days = slice_days
        self.max_retries = max_retries
        self._warmed_up = False

    def _warmup(self):
        if not self._warmed_up:
            try:
                self.session.get("https://www.nseindia.com", timeout=10)
                self._warmed_up = True
            except Exception as e:  # pragma: no cover
                logger.warning("NSE warmup note: %s", e)

    # ------------------------------------------------------------------
    # Raw fetch (single date slice)
    # ------------------------------------------------------------------
    def _fetch_slice(self, from_d: str, to_d: str) -> List[Dict[str, Any]]:
        self._warmup()
        url = (
            "https://www.nseindia.com/api/corporates-corporateActions"
            f"?index=equities&from_date={from_d}&to_date={to_d}"
        )
        last_err: Optional[str] = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code != 200:
                    last_err = f"http_{resp.status_code}"
                    if resp.status_code in (403, 429):
                        # Throttle then retry.
                        import time
                        time.sleep(2 * (attempt + 1))
                        continue
                    logger.warning("NSE corp-actions HTTP %s (%s->%s)", resp.status_code, from_d, to_d)
                    return []
                payload = resp.json()
                if isinstance(payload, list):
                    return payload
                # Some shapes wrap under 'data'
                return payload.get("data", []) if isinstance(payload, dict) else []
            except Exception as e:
                last_err = str(e)
                import time
                time.sleep(2 * (attempt + 1))
        logger.warning("NSE corp-actions slice failed (%s->%s): %s", from_d, to_d, last_err)
        return []

    # ------------------------------------------------------------------
    # Normalize one raw record
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(rec: Dict[str, Any]) -> Dict[str, Any]:
        subject = (rec.get("subject") or "").strip()
        return {
            "isin": rec.get("isin"),
            "symbol": rec.get("symbol"),
            "company_name": rec.get("comp"),
            "subject": subject,
            "action_type": _normalize_action_type(subject),
            "ex_date": _parse_date(rec.get("exDate")),
            "rec_date": _parse_date(rec.get("recDate")),
            "bc_start_date": _parse_date(rec.get("bcStartDate")),
            "bc_end_date": _parse_date(rec.get("bcEndDate")),
            "nd_start_date": _parse_date(rec.get("ndStartDate")),
            "nd_end_date": _parse_date(rec.get("ndEndDate")),
            "broadcast_date": _parse_date(rec.get("caBroadcastDate")),
            "face_value": _to_float(rec.get("faceVal")),
            "series": rec.get("series"),
            "industry": rec.get("ind"),
            "source": SOURCE_NSE_OFFICIAL,
        }

    # ------------------------------------------------------------------
    # Public API — fetch a date range, auto-sliced
    # ------------------------------------------------------------------
    def fetch_range(
        self, from_date: str, to_date: str
    ) -> Dict[str, Any]:
        """Fetch corporate actions between two ISO dates, auto-sliced.

        Returns::
            {"slices": int, "raw_records": int, "normalized": [...], "errors": int}
        """
        start = datetime.strptime(from_date, "%Y-%m-%d")
        end = datetime.strptime(to_date, "%Y-%m-%d")
        slices: List[Dict[str, Any]] = []
        errors = 0
        cur = start
        while cur <= end:
            nxt = min(cur + timedelta(days=self.slice_days), end)
            frm = cur.strftime("%d-%m-%Y")
            to = nxt.strftime("%d-%m-%Y")
            raw = self._fetch_slice(frm, to)
            if raw is None:
                errors += 1
                raw = []
            slices.append(raw)
            cur = nxt + timedelta(days=1)
            # small politeness delay between slices
            import time
            time.sleep(0.5)

        normalized: List[Dict[str, Any]] = []
        raw_total = 0
        for sl in slices:
            raw_total += len(sl)
            for r in sl:
                if isinstance(r, dict) and r.get("isin"):
                    normalized.append(self._normalize(r))
        return {
            "slices": len(slices),
            "raw_records": raw_total,
            "normalized": normalized,
            "errors": errors,
        }

    def fetch_full_history(
        self, from_date: str = "2023-01-01"
    ) -> Dict[str, Any]:
        """Fetch from a start date to today (default since 2023-01-01)."""
        to_date = datetime.now().strftime("%Y-%m-%d")
        return self.fetch_range(from_date, to_date)


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "-":
        return None
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return None


# Singleton
corporate_actions_client = CorporateActionsClient()
