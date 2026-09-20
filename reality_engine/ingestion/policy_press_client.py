"""Probe-forward press-release fetchers for PIB + RBI (Tier-1 news-feed v1).

Fail-closed everywhere: network/parse misses return empty/None + log, never
synthesize. No PDF downloads anywhere in v1.
"""

import hashlib
import html as _html
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("reality_engine.policy_press_client")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIB_SOURCE_TYPE = "PIB_Press_Release"
RBI_SOURCE_TYPE = "RBI_Press_Release"
PIB_CREATOR = "Press Information Bureau (GoI)"
RBI_CREATOR = "Reserve Bank of India"

PIB_SEED_PRID = 1951700
PIB_DETAIL_URL_TEMPLATE = "https://pib.gov.in/PressReleseDetailm.aspx?PRID={prid}"
PIB_REFERER = "https://pib.gov.in/"

RBI_HOMEPAGE_URL = "https://www.rbi.org.in/"
RBI_DISPLAY_URL_TEMPLATE = (
    "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid={prid}"
)
RBI_PRID_LINK_RE = re.compile(r"PressReleaseDisplay\.aspx\?prid=(\d+)", re.IGNORECASE)

_MONTHS = {
    "jan": "01", "january": "01",
    "feb": "02", "february": "02",
    "mar": "03", "march": "03",
    "apr": "04", "april": "04",
    "may": "05",
    "jun": "06", "june": "06",
    "jul": "07", "july": "07",
    "aug": "08", "august": "08",
    "sep": "09", "sept": "09", "september": "09",
    "oct": "10", "october": "10",
    "nov": "11", "november": "11",
    "dec": "12", "december": "12",
}
_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_OG_TITLE_RES = (
    re.compile(
        r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']',
        re.IGNORECASE,
    ),
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_MINISTRY_RE = re.compile(r"(Ministry of[^<\"\n]{0,120})", re.IGNORECASE)
_PRID_IN_URL_RE = re.compile(r"PRID=(\d+)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

# ---------------------------------------------------------------------------
# Session (repo NSE pattern: curl_cffi impersonate chrome120, verify=False,
# plain requests fallback). Lazy: no network at import.
# ---------------------------------------------------------------------------

try:
    from curl_cffi import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = False

import urllib3

urllib3.disable_warnings()

_session = None


def _get_session():
    global _session
    if _session is None:
        if _HAS_CURL_CFFI:
            try:
                _session = _curl_requests.Session(impersonate="chrome120", verify=False)  # type: ignore[call-arg]
            except TypeError:
                _session = _curl_requests.Session(verify=False)  # type: ignore
        else:
            _session = _curl_requests.Session()
            try:
                _session.verify = False  # type: ignore[attr-defined]
            except Exception:
                pass
    return _session


def _http_get(url: str, headers: Optional[Dict[str, str]] = None,
              timeout: int = 15) -> Optional[str]:
    """GET url, fail-closed None. Never raises."""
    try:
        sess = _get_session()
        resp = sess.get(url, headers=headers or {}, timeout=timeout)
        code = getattr(resp, "status_code", 200)
        if code != 200:
            logger.warning("GET %s -> HTTP %s", url, code)
            return None
        return resp.text
    except Exception as e:
        logger.warning("GET %s failed: %s", url, e)
        return None


def _call_fetcher(fetcher: Callable, url: str, headers: Dict[str, str]) -> Optional[str]:
    """Injectable fetch for tests (zero network). Never raises."""
    try:
        try:
            return fetcher(url, headers=headers, timeout=15)
        except TypeError:
            return fetcher(url)
    except Exception as e:
        logger.warning("fetcher failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Language gate + parsing helpers
# ---------------------------------------------------------------------------

def is_english_title(title: Optional[str]) -> bool:
    """Latin-ratio gate: True iff latin letters / all letters >= 0.6."""
    if not title:
        return False
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if ("A" <= c <= "Z" or "a" <= c <= "z"))
    return (latin / len(letters)) >= 0.6


def _clean(s: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", _TAG_RE.sub(" ", s or ""))).strip()


def _extract_og_title(html_text: str) -> Optional[str]:
    for rx in _OG_TITLE_RES:
        m = rx.search(html_text or "")
        if m:
            t = _html.unescape(m.group(1)).strip()
            if t:
                return t
    m = _TITLE_RE.search(html_text or "")
    if m:
        t = _clean(m.group(1))
        return t or None
    return None


def _extract_date(html_text: str) -> Optional[str]:
    """First 'dd Mon yyyy' string -> YYYY-MM-DD, else None."""
    for m in _DATE_RE.finditer(html_text or ""):
        day, mon, year = m.groups()
        key = mon.lower()
        if key in _MONTHS:
            return f"{year}-{_MONTHS[key]}-{int(day):02d}"
    return None


def _extract_ministry(html_text: str) -> Optional[str]:
    m = _MINISTRY_RE.search(_clean(html_text or ""))
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def pib_parse_detail(html_text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse PIB detail HTML -> {title, date, ministry, text} or None.

    None when title missing, date missing/unparseable, or the
    non-English language gate rejects the title.
    """
    if not html_text:
        return None
    title = _extract_og_title(html_text)
    if not title:
        return None
    if not is_english_title(title):
        return None
    date = _extract_date(html_text)
    if not date:
        return None
    return {
        "title": title,
        "date": date,
        "ministry": _extract_ministry(html_text),
        "text": _clean(html_text)[:8000] or None,
    }


# Back-compat alias: module-level parse_detail is the PIB variant.
def parse_detail(html_text: Optional[str]) -> Optional[Dict[str, Any]]:
    return pib_parse_detail(html_text)


def rbi_parse_detail(html_text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse RBI display HTML.

    v1: the release body on RBI pages is JS-table rendered and unresolvable
    server-side, so this returns None for body-less pages (fail-closed).
    Returns a dict only when a substantive release body is resolvable.
    """
    if not html_text:
        return None
    text = _clean(html_text)
    # Heuristic: a resolvable release body needs substantive text beyond
    # chrome/navigation. RBI JS-table shells fall well below this.
    if len(text) < 400:
        return None
    title = _extract_og_title(html_text)
    date = _extract_date(html_text)
    if not title or not date:
        return None
    return {"title": title, "date": date, "ministry": None,
            "text": text[:8000] or None}


# ---------------------------------------------------------------------------
# Record mapping (raw_documents contract)
# ---------------------------------------------------------------------------

def _sha(url: str, title: str) -> str:
    return hashlib.sha256(f"{url}|{title}".encode("utf-8")).hexdigest()


def _pib_record(prid: int, parsed: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    date = parsed.get("date")
    if not date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
        return None
    url = PIB_DETAIL_URL_TEMPLATE.format(prid=prid)
    title = parsed.get("title") or f"PIB Press Release {prid}"
    return {
        "title": title,
        "source_type": PIB_SOURCE_TYPE,
        "published_date": date,
        "fiscal_period": None,
        "source_url": url,
        "creator_or_ministry": parsed.get("ministry") or PIB_CREATOR,
        "sha256_hash": _sha(url, title),
        "local_file_path": None,
        "file_size_bytes": None,
        "text": parsed.get("text"),
    }


def _rbi_record(prid: int, title: Optional[str], date: Optional[str],
                text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
        return None
    url = RBI_DISPLAY_URL_TEMPLATE.format(prid=prid)
    title = title or f"RBI Press Release {prid}"
    return {
        "title": title,
        "source_type": RBI_SOURCE_TYPE,
        "published_date": date,
        "fiscal_period": None,
        "source_url": url,
        "creator_or_ministry": RBI_CREATOR,
        "sha256_hash": _sha(url, title),
        "local_file_path": None,
        "file_size_bytes": None,
        "text": text,
    }


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def pib_fetch_detail(prid: int,
                     fetcher: Optional[Callable] = None) -> Optional[str]:
    url = PIB_DETAIL_URL_TEMPLATE.format(prid=prid)
    headers = {"Referer": PIB_REFERER,
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if fetcher is not None:
        return _call_fetcher(fetcher, url, headers)
    return _http_get(url, headers=headers)


# Alias matching the "<source> fetch_detail(prid)" contract.
def fetch_detail(prid: int, kind: str = "PIB",
                 fetcher: Optional[Callable] = None) -> Optional[str]:
    if str(kind).upper() == "RBI":
        return rbi_fetch_detail(prid, fetcher=fetcher)
    return pib_fetch_detail(prid, fetcher=fetcher)


def last_prid(repo: Any = None) -> int:
    """MAX PRID seen in raw_documents (PIB rows), else PIB_SEED_PRID."""
    try:
        if repo is None:
            from reality_engine.db.repository import Repository
            repo = Repository()
        with repo.db.session() as conn:
            rows = conn.execute(
                "SELECT source_url FROM raw_documents "
                "WHERE source_type = ? AND source_url LIKE ?",
                (PIB_SOURCE_TYPE, "%PRID=%"),
            ).fetchall()
        best = 0
        for r in rows:
            try:
                url = r["source_url"] if isinstance(r, dict) else r[0]
            except Exception:
                continue
            m = _PRID_IN_URL_RE.search(url or "")
            if m:
                best = max(best, int(m.group(1)))
        return best if best > 0 else PIB_SEED_PRID
    except Exception as e:
        logger.warning("last_prid fallback to seed: %s", e)
        return PIB_SEED_PRID


def rbi_frontier_prids(fetcher: Optional[Callable] = None,
                       cap: int = 200) -> List[int]:
    """Scrape PressReleaseDisplay.aspx?prid=N links from the RBI homepage."""
    if fetcher is not None:
        html_text = _call_fetcher(fetcher, RBI_HOMEPAGE_URL, {})
    else:
        html_text = _http_get(RBI_HOMEPAGE_URL)
    if not html_text:
        return []
    seen: List[int] = []
    for m in RBI_PRID_LINK_RE.finditer(html_text):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if n not in seen:
            seen.append(n)
        if len(seen) >= max(1, cap):
            break
    return seen


# Alias for the contract name.
def frontier_prids(kind: str = "RBI", fetcher: Optional[Callable] = None,
                   cap: int = 200) -> List[int]:
    return rbi_frontier_prids(fetcher=fetcher, cap=cap)


def rbi_fetch_detail(prid: int,
                     fetcher: Optional[Callable] = None) -> Optional[str]:
    url = RBI_DISPLAY_URL_TEMPLATE.format(prid=prid)
    headers = {"Referer": RBI_HOMEPAGE_URL,
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if fetcher is not None:
        return _call_fetcher(fetcher, url, headers)
    return _http_get(url, headers=headers)


def fetch_new(kind: str, cap: int = 200, repo: Any = None,
              fetcher: Optional[Callable] = None
              ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Probe-forward fetch for kind in {PIB, RBI}.

    Returns (records, stats). Records follow the raw_documents contract
    (+ a 'text' extra for persist_text). Unparseable-date rows are skipped
    and counted in stats['skipped'].
    """
    k = str(kind or "").upper()
    if k in ("PIB", PIB_SOURCE_TYPE.upper(), "PIB_PRESS_RELEASE"):
        return _fetch_new_pib(cap=cap, repo=repo, fetcher=fetcher)
    if k in ("RBI", RBI_SOURCE_TYPE.upper(), "RBI_PRESS_RELEASE"):
        return _fetch_new_rbi(cap=cap, fetcher=fetcher)
    raise ValueError(f"unknown kind: {kind!r} (expected 'PIB' or 'RBI')")


def _fetch_new_pib(cap: int = 200, repo: Any = None,
                   fetcher: Optional[Callable] = None
                   ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    start = last_prid(repo) + 1
    records: List[Dict[str, Any]] = []
    stats = {"kind": "PIB", "start_prid": start, "probed": 0,
             "fetched": 0, "records": 0, "skipped": 0, "misses": 0}
    for prid in range(start, start + max(0, cap)):
        stats["probed"] += 1
        html_text = pib_fetch_detail(prid, fetcher=fetcher)
        if not html_text:
            stats["misses"] += 1
            continue
        stats["fetched"] += 1
        parsed = pib_parse_detail(html_text)
        if parsed is None:
            stats["skipped"] += 1
            continue
        rec = _pib_record(prid, parsed)
        if rec is None:
            stats["skipped"] += 1
            continue
        records.append(rec)
    stats["records"] = len(records)
    return records, stats


def _fetch_new_rbi(cap: int = 200,
                   fetcher: Optional[Callable] = None
                   ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    prids = rbi_frontier_prids(fetcher=fetcher, cap=cap)
    records: List[Dict[str, Any]] = []
    stats = {"kind": "RBI", "start_prid": None, "probed": 0,
             "fetched": 0, "records": 0, "skipped": 0, "misses": 0}
    for prid in prids[: max(0, cap)]:
        stats["probed"] += 1
        html_text = rbi_fetch_detail(prid, fetcher=fetcher)
        if not html_text:
            stats["misses"] += 1
            continue
        stats["fetched"] += 1
        parsed = rbi_parse_detail(html_text)
        if parsed is not None:
            rec = _rbi_record(prid, parsed.get("title"), parsed.get("date"),
                              parsed.get("text"))
        else:
            # Body unresolvable (JS table): keep the permalink row with
            # whatever title/date the shell page carries. Rows with
            # unparseable dates are skipped + counted (NOT NULL contract).
            rec = _rbi_record(prid, _extract_og_title(html_text),
                              _extract_date(html_text), None)
        if rec is None:
            stats["skipped"] += 1
            continue
        records.append(rec)
    stats["records"] = len(records)
    return records, stats


def persist_text(records_with_text: List[Dict[str, Any]],
                 repo: Any = None) -> int:
    """Upsert records then write one FTS chunk each.

    chunk_id format: f"{source_type}:{doc_id}:0" where doc_id is resolved
    via repo.get_raw_document_by_hash(sha) after upsert_raw_document.
    Records without text are skipped. Returns chunks inserted.
    """
    if not records_with_text:
        return 0
    if repo is None:
        from reality_engine.db.repository import Repository
        repo = Repository()
    n = 0
    for rec in records_with_text:
        text = (rec or {}).get("text")
        if not text:
            continue
        contract = {k: rec.get(k) for k in (
            "title", "source_type", "published_date", "fiscal_period",
            "source_url", "creator_or_ministry", "sha256_hash",
            "local_file_path", "file_size_bytes")}
        try:
            repo.upsert_raw_document(contract)
            row = repo.get_raw_document_by_hash(contract["sha256_hash"])
            if not row:
                continue
            doc_id = row["doc_id"] if isinstance(row, dict) else row[0]
            fts_rec = {
                "chunk_id": f"{contract['source_type']}:{doc_id}:0",
                "symbol": "",
                "isin": "",
                "source_type": contract["source_type"],
                "document_date": contract["published_date"],
                "document_text": text,
            }
            n += int(repo.insert_fts_chunks([fts_rec]) or 0)
        except Exception as e:
            logger.warning("persist_text skip %s: %s",
                           contract.get("source_url"), e)
            continue
    return n
