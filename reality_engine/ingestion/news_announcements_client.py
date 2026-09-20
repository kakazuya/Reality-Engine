"""NSE corporate-announcements ingest (Tier-0 news feed).

Fetches the official NSE corporate-announcement feed and normalizes rows into
the ``corporate_documents`` contract (``repo.upsert_corporate_documents``).

Fail-closed: any network/parse miss returns ``[]`` and logs; nothing is
synthesized. No network activity happens at import time.

Live READ probe (manual only -- never executed by tests)::

    curl -sk -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0" ^
      -H "Accept: */*" -H "Referer: https://www.nseindia.com/" ^
      "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=12-09-2026&to_date=19-09-2026"

Expected: HTTP 200 with a JSON payload shaped ``{"data": [...]}`` (or a bare
list), where each row carries ``symbol``, ``sm_isin``, ``desc``,
``sort_date``, ``attchmntFile`` and ``seq_id``.
"""

import hashlib
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

logger = logging.getLogger("reality_engine.news_announcements_client")

NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
NSE_HOME_URL = "https://www.nseindia.com"

SOURCE_NSE_OFFICIAL = "nse_official"
DISCOVERY_SOURCE = "nse_announcement_feed"
DOC_TYPE_ANNOUNCEMENT = "ANNOUNCEMENT"

RATE_LIMIT_SEC = 0.5

_SORT_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%d-%b-%Y %H:%M",
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d-%b-%y",
)


def _to_iso_date(value: Any) -> Optional[str]:
    """Parse an NSE ``sort_date`` (e.g. '19-Sep-2026 16:30') to YYYY-MM-DD."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in _SORT_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _is_valid_isin(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 12
        and value.startswith("IN")
        and value.isalnum()
    )


def _source_url_for(row: Dict[str, Any], seq_id: str) -> str:
    att = (row.get("attchmntFile") or "")
    if not isinstance(att, str):
        att = str(att)
    att = att.strip()
    if att:
        if att.startswith("http"):
            return att
        if att.startswith("/"):
            return NSE_HOME_URL + att
        return NSE_HOME_URL + "/" + att
    # Text-only announcement: synthesize a stable, unique pseudo-URL so the
    # UNIQUE(source_url) upsert key still deduplicates idempotently.
    if seq_id:
        return f"{NSE_ANNOUNCEMENTS_URL}?seq_id={seq_id}"
    title = (row.get("desc") or row.get("subject") or "").strip()
    symbol = (row.get("symbol") or "").strip()
    digest = hashlib.sha256(f"{symbol}|{title}".encode()).hexdigest()[:12]
    return f"{NSE_ANNOUNCEMENTS_URL}?synthetic={digest}"


class NewsAnnouncementsClient:
    """Fetches + normalizes NSE corporate announcements (Tier-0 feed)."""

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
    def fetch_window(
        self, from_date: str, to_date: str, index: str = "equities"
    ) -> List[Dict[str, Any]]:
        """Fetch raw announcement rows between two ISO dates (YYYY-MM-DD).

        Fail-closed: returns ``[]`` on any network/HTTP/parse miss.
        """
        try:
            frm = datetime.strptime(from_date, "%Y-%m-%d").strftime("%d-%m-%Y")
            to = datetime.strptime(to_date, "%Y-%m-%d").strftime("%d-%m-%Y")
        except ValueError as e:
            logger.warning("NSE announcements bad window %s->%s: %s", from_date, to_date, e)
            return []
        self._warmup()
        url = (
            f"{NSE_ANNOUNCEMENTS_URL}"
            f"?index={index}&from_date={frm}&to_date={to}"
        )
        try:
            resp = self.session.get(url, headers=NSE_HEADERS, timeout=30)
            if resp.status_code != 200:
                logger.warning("NSE announcements HTTP %s (%s->%s)", resp.status_code, frm, to)
                return []
            payload = resp.json()
            if isinstance(payload, list):
                rows = payload
            elif isinstance(payload, dict):
                rows = payload.get("data", [])
            else:
                logger.warning("NSE announcements unexpected payload type %s", type(payload))
                return []
            return [r for r in rows if isinstance(r, dict)]
        except Exception as e:
            logger.warning("NSE announcements fetch failed (%s->%s): %s", frm, to, e)
            return []
        finally:
            try:
                time.sleep(self.rate_limit_sec)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Normalize to the corporate_documents contract
    # ------------------------------------------------------------------
    @staticmethod
    def normalize(
        rows: List[Dict[str, Any]],
        symbol_to_isin: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """Map raw NSE rows to ``corporate_documents`` upsert records.

        Rows without a resolvable ISIN (``sm_isin``, else ``symbol_to_isin``
        lookup) or with an unparseable ``sort_date`` are SKIPPED + counted.
        ``seq_id`` duplicates are dropped + counted.
        """
        sym_map = symbol_to_isin or {}
        records: List[Dict[str, Any]] = []
        seen: set = set()
        stats = {
            "total": len(rows),
            "normalized": 0,
            "skipped_no_isin": 0,
            "skipped_bad_date": 0,
            "skipped_malformed": 0,
            "duplicates": 0,
        }
        for row in rows:
            if not isinstance(row, dict):
                stats["skipped_malformed"] += 1
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            seq_id = str(row.get("seq_id") or "").strip()
            raw_isin = str(row.get("sm_isin") or "").strip().upper()
            isin = raw_isin if _is_valid_isin(raw_isin) else sym_map.get(symbol)
            if not isin:
                stats["skipped_no_isin"] += 1
                continue
            doc_date = _to_iso_date(row.get("sort_date"))
            if not doc_date:
                stats["skipped_bad_date"] += 1
                continue
            title = str(row.get("desc") or row.get("subject") or "").strip()
            if not title:
                title = f"{symbol} corporate announcement {doc_date}"
            source_url = _source_url_for(row, seq_id)
            dedup_key = seq_id or source_url
            if dedup_key in seen:
                stats["duplicates"] += 1
                continue
            seen.add(dedup_key)
            sha = hashlib.sha256(f"{source_url}|{title}".encode()).hexdigest()
            records.append({
                "isin": isin,
                "symbol": symbol,
                "doc_type": DOC_TYPE_ANNOUNCEMENT,
                "title": title,
                "doc_date": doc_date,
                "source_url": source_url,
                "source": SOURCE_NSE_OFFICIAL,
                "discovery_source": DISCOVERY_SOURCE,
                "local_file_path": None,
                "file_size_bytes": None,
                "sha256_hash": sha,
                "is_processed": 0,
            })
        stats["normalized"] = len(records)
        return records, stats

    # ------------------------------------------------------------------
    # Persist (CLI-facing: persist(records) / persist(records, repo))
    # ------------------------------------------------------------------
    @staticmethod
    def persist(records: List[Dict[str, Any]], repo: Any = None,
                known_isins: Any = None) -> int:
        """Upsert normalized records via ``repo.upsert_corporate_documents``.

        CLI contract: returns ``int`` (rows written). FK-safe: rows whose
        ``isin`` is absent from ``master_companies`` would violate
        ``FOREIGN KEY(isin)`` at write time, so they are dropped here per
        the repo contract ("rows without resolvable isin are SKIPPED").
        The known-isin set is resolved with a single light query
        (``SELECT isin FROM master_companies``) via ``repo.db.session``
        when ``known_isins`` is not supplied; pass ``known_isins`` explicitly
        to skip even that query. Fail-closed: if the set cannot be resolved,
        all records are passed through. The dropped count is logged and
        exposed as ``persist.last_dropped`` for observability.
        """
        if repo is None:
            from reality_engine.db.repository import repo as _repo  # lazy: no live-DB touch at import
            repo = _repo
        if not records:
            NewsAnnouncementsClient.persist.last_dropped = 0  # type: ignore[attr-defined]
            return repo.upsert_corporate_documents(records)
        known = set(known_isins) if known_isins is not None else None
        if known is None:
            try:
                db = getattr(repo, "db", None)
                session_fn = getattr(db, "session", None) if db is not None else None
                if callable(session_fn):
                    with db.session() as conn:
                        rows = conn.execute("SELECT isin FROM master_companies").fetchall()
                        known = {r[0] for r in rows}
            except Exception as e:
                logger.warning("NSE announcements persist: known-isin probe failed: %s", e)
                known = None
        if known is None:
            filtered = list(records)
            dropped = 0
        else:
            filtered = [r for r in records if r.get("isin") in known]
            dropped = len(records) - len(filtered)
            if dropped:
                logger.warning("NSE announcements persist: dropped %d record(s) with unknown isin", dropped)
        NewsAnnouncementsClient.persist.last_dropped = dropped  # type: ignore[attr-defined]
        return repo.upsert_corporate_documents(filtered)


# Singleton
news_announcements_client = NewsAnnouncementsClient()
