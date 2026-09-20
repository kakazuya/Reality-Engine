"""NSE bulk/block deals ingest (Tier-0 news feed).

Fetches the official NSE ``bulk.csv`` / ``block.csv`` archives and normalizes
rows into the ``bulk_block_deals`` contract (``repo.upsert_bulk_block_deals``).

Fail-closed: any network/parse miss returns ``""`` / ``([], stats)`` and logs;
nothing is synthesized. No network activity happens at import time.

Live READ probe (manual only -- never executed by tests)::

    curl -sk -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0" ^
      -H "Referer: https://www.nseindia.com/" ^
      https://nsearchives.nseindia.com/content/equities/bulk.csv | head -3

Expected: HTTP 200 with a CSV whose header contains ``Date, Symbol,
Client Name, Buy / Sell, Quantity Traded, Trade Price``.
"""

import csv
import hashlib
import io
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from curl_cffi import requests as _requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    import requests as _requests  # type: ignore
    _HAS_CURL_CFFI = False

from reality_engine.config import NSE_HEADERS

logger = logging.getLogger("reality_engine.deals_client")

NSE_HOME_URL = "https://www.nseindia.com"
NSE_BULK_CSV_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
NSE_BLOCK_CSV_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"

RATE_LIMIT_SEC = 0.5

MARQUEE_KEYWORDS = (
    "MUTUAL FUND", "MUTUAL FUNDS", "AMC", "LIC", "LIFE INSURANCE",
    "SBI", "HDFC", "ICICI", "AXIS", "KOTAK", "NIPPON", "FRANKLIN",
    "FIDELITY", "BLACKROCK", "VANGUARD", "STATE STREET",
    "GOVERNMENT OF SINGAPORE", "GIC", "TEMASEK", "ABU DHABI",
    "SOVEREIGN", "PENSION", "PROVIDENT FUND", "GRATUITY FUND",
    "INSURANCE COMPANY", "BANK", "FOREIGN PORTFOLIO", "FPI",
)

_DATE_FORMATS = ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y")


def _to_iso_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _norm_side(value: Any) -> Optional[str]:
    text = str(value or "").strip().upper().replace("/", " ").replace("-", " ")
    if text in ("B", "BUY", "BOUGHT", "PURCHASE", "PURCHASED"):
        return "BUY"
    if text in ("S", "SELL", "SOLD", "SALE"):
        return "SELL"
    if "BUY" in text:
        return "BUY"
    if "SELL" in text or text == "SALE":
        return "SELL"
    return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _col(row: Dict[str, Any], *names: str) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for name in names:
        if name in lowered:
            return lowered[name]
    # prefix-tolerant fallback (e.g. 'trade price / wtd.avg.price')
    for name in names:
        for key, val in lowered.items():
            if key.startswith(name):
                return val
    return None


def is_marquee_institution(client_name: Optional[str]) -> int:
    text = str(client_name or "").upper()
    return 1 if any(k in text for k in MARQUEE_KEYWORDS) else 0


def make_deal_id(deal_date: str, symbol: str, client: str, side: str, qty: int, price: float) -> str:
    raw = f"{deal_date}|{symbol}|{client}|{side}|{qty}|{price}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class DealsClient:
    """Fetches + normalizes NSE bulk/block deals (Tier-0 feed)."""

    URLS = {"BULK": NSE_BULK_CSV_URL, "BLOCK": NSE_BLOCK_CSV_URL}

    def __init__(self, session: Any = None, rate_limit_sec: float = RATE_LIMIT_SEC):
        if session is not None:
            self.session = session
        else:
            if _HAS_CURL_CFFI:
                self.session = _requests.Session(impersonate="chrome120", verify=False)  # type: ignore[call-arg]
            else:
                self.session = _requests.Session()
                try:
                    self.session.verify = False  # type: ignore[attr-defined]
                except Exception:
                    pass
            try:
                self.session.headers.update(NSE_HEADERS)
            except Exception:
                pass
        self.rate_limit_sec = rate_limit_sec
        self._warmed_up = False
        self._cache: Dict[str, str] = {}

    def _warmup(self) -> None:
        if not self._warmed_up:
            try:
                self.session.get(NSE_HOME_URL, headers=NSE_HEADERS, timeout=10)
                self._warmed_up = True
            except Exception as e:
                logger.warning("NSE warmup note: %s", e)

    # ------------------------------------------------------------------
    # Raw fetch
    # ------------------------------------------------------------------
    def fetch_csv(self, kind: str) -> str:
        """Fetch the raw CSV text for ``kind`` (``'BULK'`` or ``'BLOCK'``).

        Fail-closed: returns ``""`` on any network/HTTP miss.
        """
        key = str(kind or "").strip().upper()
        url = self.URLS.get(key)
        if url is None:
            logger.warning("Deals fetch: unknown kind %r", kind)
            return ""
        self._warmup()
        try:
            resp = self.session.get(url, headers=NSE_HEADERS, timeout=30)
            if resp.status_code != 200:
                logger.warning("NSE %s deals HTTP %s", key, resp.status_code)
                return ""
            text = resp.text or ""
            if not text.strip():
                return ""
            self._cache[key] = text
            return text
        except Exception as e:
            logger.warning("NSE %s deals fetch failed: %s", key, e)
            return ""
        finally:
            try:
                time.sleep(self.rate_limit_sec)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Normalize to the bulk_block_deals contract
    # ------------------------------------------------------------------
    @staticmethod
    def parse_csv(text: str) -> List[Dict[str, Any]]:
        """Parse CSV text into raw row dicts. Fail-closed: ``[]`` on miss."""
        if not text or not text.strip():
            return []
        try:
            reader = csv.DictReader(io.StringIO(text.strip()))
            if not reader.fieldnames:
                return []
            return [dict(r) for r in reader if any((v or "").strip() for v in r.values() if isinstance(v, str))]
        except Exception as e:
            logger.warning("Deals CSV parse failed: %s", e)
            return []

    @classmethod
    def normalize(
        cls, rows_or_text: Any, kind: str = "BULK"
    ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """Normalize raw CSV rows (or CSV text) to ``bulk_block_deals`` records.

        Malformed rows (bad date / side / quantity / price / missing
        symbol+client) are SKIPPED + counted.
        """
        deal_type = str(kind or "").strip().upper()
        if deal_type not in ("BULK", "BLOCK"):
            return [], {"total": 0, "normalized": 0, "skipped_malformed": 0, "duplicates": 0}
        rows: List[Dict[str, Any]]
        if isinstance(rows_or_text, str):
            rows = cls.parse_csv(rows_or_text)
        else:
            rows = list(rows_or_text or [])
        records: List[Dict[str, Any]] = []
        seen: set = set()
        stats = {"total": len(rows), "normalized": 0, "skipped_malformed": 0, "duplicates": 0}
        for row in rows:
            if not isinstance(row, dict):
                stats["skipped_malformed"] += 1
                continue
            deal_date = _to_iso_date(_col(row, "date"))
            symbol = str(_col(row, "symbol") or "").strip().upper()
            client = str(_col(row, "client name") or "").strip()
            side = _norm_side(_col(row, "buy / sell", "buy/sell", "buy sell"))
            qty = _to_int(_col(row, "quantity traded", "quantity"))
            price = _to_float(_col(row, "trade price / wtd.avg.price", "trade price"))
            if not deal_date or not symbol or not client or not side or qty is None or price is None:
                stats["skipped_malformed"] += 1
                continue
            deal_id = make_deal_id(deal_date, symbol, client, side, qty, price)
            if deal_id in seen:
                stats["duplicates"] += 1
                continue
            seen.add(deal_id)
            records.append({
                "id": deal_id,
                "deal_date": deal_date,
                "symbol": symbol,
                "client_name": client,
                "deal_type": deal_type,
                "buy_sell": side,
                "quantity": qty,
                "trade_price": price,
                "is_marquee_institution": is_marquee_institution(client),
            })
        stats["normalized"] = len(records)
        return records, stats

    def fetch_normalize(self, kind: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """Fetch + normalize in one step (fail-closed)."""
        text = self.fetch_csv(kind)
        if not text:
            return [], {"total": 0, "normalized": 0, "skipped_malformed": 0, "duplicates": 0}
        return self.normalize(text, kind)

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    @staticmethod
    def persist(records: List[Dict[str, Any]], repo: Any = None) -> int:
        """Upsert normalized records via ``repo.upsert_bulk_block_deals``."""
        if repo is None:
            from reality_engine.db.repository import repo as _repo  # lazy: no live-DB touch at import
            repo = _repo
        return repo.upsert_bulk_block_deals(records)


# Singleton
deals_client = DealsClient()
