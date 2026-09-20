"""Official-outlet broad-market RSS ingest (Tier-1 news feed).

Ingests the *official publisher* RSS feeds of six Indian business outlets
(Mint markets/companies, Business Standard markets, The Hindu BusinessLine
markets, Economic Times markets, NDTV Profit). Telegram "e-paper" re-upload
channels are deliberately out of scope: they are copyright re-distributions of
paywalled newspapers and cannot be verified.

Contract: rows land in ``raw_documents`` (via ``repo.upsert_raw_document``) with
``source_type = f"{SOURCE_PREFIX}{feed_key}"`` and one ``intelligence_fts`` chunk
per row with ``chunk_id = f"{source_type}:{doc_id}:0"``.

Fail-closed: any network/parse miss returns an empty list and logs; nothing is
synthesized. No network activity happens at import time.

Live READ probe (manual only -- never executed by tests)::

    curl -sk -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0" \
      -H "Accept: application/rss+xml, */*" https://www.livemint.com/rss/markets

Expected: HTTP 200 with an RSS 2.0 document whose ``<item>`` nodes carry
``<title>``, ``<link>``, ``<pubDate>`` and ``<description>``.
"""

import hashlib
import html as _html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from curl_cffi import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    import requests as _curl_requests  # type: ignore
    _HAS_CURL_CFFI = False

import urllib3

urllib3.disable_warnings()

logger = logging.getLogger("reality_engine.news_feed_client")

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SOURCE_PREFIX = "News_"

#: feed key -> official RSS URL (all verified HTTP 200 + publishing same-day).
FEEDS: Dict[str, str] = {
    "livemint": "https://www.livemint.com/rss/markets",
    "livemint_co": "https://www.livemint.com/rss/companies",
    "bs": "https://www.business-standard.com/rss/markets-106.rss",
    "businessline": "https://www.thehindubusinessline.com/markets/feeder/default.rss",
    "et": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "ndtvprofit": "https://www.ndtvprofit.com/rss",
}

#: feed key -> creator_or_ministry display name.
OUTLET_NAMES: Dict[str, str] = {
    "livemint": "Mint",
    "livemint_co": "Mint",
    "bs": "Business Standard",
    "businessline": "The Hindu BusinessLine",
    "et": "The Economic Times",
    "ndtvprofit": "NDTV Profit",
}

#: feed key -> raw_documents.source_type.
SOURCE_TYPES: Dict[str, str] = {k: f"{SOURCE_PREFIX}{k}" for k in FEEDS}

RSS_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "application/rss+xml, application/atom+xml, application/xml, "
        "text/xml, */*"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

SUMMARY_MAX_CHARS = 1500
MAX_SYMBOLS = 8

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
#: Uppercase NSE-style ticker token (mirrors the repo's symbol alphabet).
SYMBOL_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9&-]{2,14}\b")
#: Corporate suffixes stripped when turning a company name into a match key.
_CORP_SUFFIX_RE = re.compile(
    r"\b(?:ltd|limited|pvt|private|inc|corp|corporation|co|company|plc|llp)\b\.?",
    re.IGNORECASE,
)
#: Word-boundary match for a prose company name (multi-word keys only).
_NAME_WORD_RE_CACHE: Dict[str, "re.Pattern[str]"] = {}

_CONTRACT_KEYS = (
    "title", "source_type", "published_date", "fiscal_period", "source_url",
    "creator_or_ministry", "sha256_hash", "local_file_path", "file_size_bytes",
)

# ---------------------------------------------------------------------------
# Session (repo NSE pattern: curl_cffi impersonate chrome120, verify=False,
# plain requests fallback). Lazy: no network at import.
# ---------------------------------------------------------------------------

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


def _call_fetcher(fetcher: Callable, url: str,
                  headers: Dict[str, str]) -> Optional[str]:
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
# Text helpers
# ---------------------------------------------------------------------------

def _strip_html(raw: Any, limit: Optional[int] = None) -> str:
    """Unescape + drop tags + collapse whitespace; optional length cap."""
    if raw is None:
        return ""
    text = raw if isinstance(raw, str) else str(raw)
    if not text:
        return ""
    text = _html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    if limit is not None:
        text = text[:limit]
    return text


def _localname(tag: Any) -> str:
    """``{ns}item`` -> ``item`` (lowercased, namespace-agnostic)."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


_RSS_DATE_FORMATS = (
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M %z",
    "%a, %d %b %Y %H:%M",
    "%d %b %Y %H:%M:%S %z",
    "%d %b %Y %H:%M:%S",
    "%d %b %Y",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d-%b-%Y %H:%M",
    "%d-%b-%Y",
)


def _to_iso_date(value: Any) -> Optional[str]:
    """Parse a feed ``pubDate``/``published`` into ``YYYY-MM-DD``, else None.

    Same strptime-table approach as
    ``news_announcements_client._to_iso_date``, extended with RFC-822
    (``email.utils``) and ISO-8601 fallbacks so both of these work::

        "Sat, 19 Sep 2026 17:50:01 +0530"  -> "2026-09-19"
        "2026-09-19T12:45:56Z"             -> "2026-09-19"
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in _RSS_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    parsed = None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    try:
        return parsed.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Feed parsing (RSS <item> + Atom <entry>)
# ---------------------------------------------------------------------------

_ATOM_LINK_RELATIVE = ("alternate", "")


def _child(node: ET.Element, names: Tuple[str, ...]) -> Optional[ET.Element]:
    for child in list(node):
        if _localname(child.tag) in names:
            return child
    return None


def _child_text(node: ET.Element, names: Tuple[str, ...]) -> str:
    child = _child(node, names)
    if child is None:
        return ""
    return (child.text or "").strip()


def _atom_link(node: ET.Element) -> str:
    fallback = ""
    for child in list(node):
        if _localname(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        if not href:
            continue
        rel = (child.get("rel") or "").strip().lower()
        if rel in _ATOM_LINK_RELATIVE:
            return href
        if not fallback:
            fallback = href
    return fallback


#: Prose payloads scanned for an inline ``<img src>``, in preference order.
_IMAGE_CHILD_NAMES = ("description", "encoded", "summary", "content")
#: ``<img src="...">`` / ``<img src='...'>`` inside a (escaped) prose payload.
_IMG_SRC_RE = re.compile(
    r"<img\b[^>]*?\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)


def _attr_url(node: ET.Element) -> str:
    """``url`` (media/enclosure) or ``href`` attribute, stripped; else ``""``."""
    return str(node.get("url") or node.get("href") or "").strip()


def _dimensions(node: ET.Element) -> Tuple[int, int]:
    """Declared ``width``/``height`` as non-negative ints; unparsable -> 0."""
    values: List[int] = []
    for name in ("width", "height"):
        raw = str(node.get(name) or "").strip()
        try:
            values.append(max(0, int(raw)))
        except (TypeError, ValueError):
            values.append(0)
    return values[0], values[1]


def _clean_tracking_query(url: str) -> str:
    """Drop the query string, but only when the path has no file extension.

    ``.../chart?id=7&w=1200`` -> ``.../chart`` (the query is CDN tracking, not
    part of the resource); ``.../chart.png?w=1200`` is left untouched.
    """
    if not url:
        return ""
    head, sep, query = url.partition("?")
    if not sep or not query:
        return url
    segment = head.rsplit("/", 1)[-1]
    if "." in segment and not segment.endswith("."):
        return url
    return head


def _inline_image_url(node: ET.Element) -> str:
    """First ``<img src>`` found inside the item's prose payloads; else ``""``."""
    for name in _IMAGE_CHILD_NAMES:
        for child in list(node):
            if _localname(child.tag) != name:
                continue
            markup = child.text or ""
            for sub in list(child):
                try:
                    markup += ET.tostring(sub, encoding="unicode")
                except Exception:  # pragma: no cover - defensive
                    continue
            match = _IMG_SRC_RE.search(_html.unescape(markup))
            if match:
                return (match.group(1) or match.group(2) or "").strip()
    return ""


def _media_url(node: ET.Element) -> str:
    """Best image URL carried by an ``<item>``/``<entry>``; else ``""``.

    Priority (namespace-agnostic on the local name, so ``media:content``,
    ``{http://search.yahoo.com/mrss/}content`` and a bare ``<content>`` all
    work): ``media:content`` (largest declared width x height wins), then
    ``media:thumbnail``, then an ``image/*`` ``<enclosure>``, then the first
    ``<img src>`` in the description/summary/content payload.
    """
    best = ""
    best_key = (-1, -1)
    for el in node.iter():
        if el is node or _localname(el.tag) != "content":
            continue
        url = _attr_url(el)
        if not url:
            continue
        width, height = _dimensions(el)
        key = (width * height, width + height)
        if key > best_key:
            best_key, best = key, url
    if best:
        return _clean_tracking_query(best)
    for el in node.iter():
        if el is node or _localname(el.tag) != "thumbnail":
            continue
        url = _attr_url(el)
        if url:
            return _clean_tracking_query(url)
    for el in node.iter():
        if el is node or _localname(el.tag) != "enclosure":
            continue
        url = _attr_url(el)
        if not url:
            continue
        if str(el.get("type") or "").strip().lower().startswith("image/"):
            return _clean_tracking_query(url)
    return _clean_tracking_query(_inline_image_url(node))


def _rss_item(node: ET.Element) -> Optional[Dict[str, str]]:
    link = _child_text(node, ("link",)) or _child_text(node, ("guid",))
    item = {
        "title": _child_text(node, ("title",)),
        "link": link,
        "published_raw": (
            _child_text(node, ("pubdate",))
            or _child_text(node, ("date",))
            or _child_text(node, ("published",))
            or _child_text(node, ("updated",))
        ),
        "summary": (
            _child_text(node, ("description",))
            or _child_text(node, ("encoded",))
            or _child_text(node, ("summary",))
            or _child_text(node, ("content",))
        ),
        "media_url": _media_url(node),
    }
    if not item["title"] and not item["link"]:
        return None
    return item


def _atom_entry(node: ET.Element) -> Optional[Dict[str, str]]:
    item = {
        "title": _child_text(node, ("title",)),
        "link": _atom_link(node),
        "published_raw": (
            _child_text(node, ("published",))
            or _child_text(node, ("updated",))
            or _child_text(node, ("pubdate",))
            or _child_text(node, ("date",))
        ),
        "summary": (
            _child_text(node, ("summary",))
            or _child_text(node, ("content",))
            or _child_text(node, ("description",))
        ),
        "media_url": _media_url(node),
    }
    if not item["title"] and not item["link"]:
        return None
    return item


def fetch_feed(url: str, fetcher: Optional[Callable] = None) -> List[Dict[str, str]]:
    """Fetch + parse one RSS/Atom feed ->
    ``[{title, link, published_raw, summary, media_url}]``.

    ``media_url`` is the item's chart/infographic image (publisher RSS/CDN), or
    ``""`` when the item carries none.

    Fail-closed: an invalid URL, a network miss, a non-200, a non-XML body or a
    malformed document returns ``[]`` (and logs). Never raises.
    """
    if not url or not isinstance(url, str):
        logger.warning("fetch_feed: invalid url %r", url)
        return []
    if fetcher is not None:
        raw = _call_fetcher(fetcher, url, RSS_HEADERS)
    else:
        raw = _http_get(url, headers=RSS_HEADERS)
    if not raw:
        logger.warning("fetch_feed: empty body for %s", url)
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        logger.warning("fetch_feed: unparseable XML for %s: %s", url, e)
        return []
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("fetch_feed: parse error for %s: %s", url, e)
        return []

    items: List[Dict[str, str]] = []
    try:
        for node in root.iter():
            name = _localname(node.tag)
            if name == "item":
                parsed = _rss_item(node)
            elif name == "entry":
                parsed = _atom_entry(node)
            else:
                continue
            if parsed is not None:
                items.append(parsed)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("fetch_feed: node walk failed for %s: %s", url, e)
        return []
    logger.info("fetch_feed: %s -> %d items", url, len(items))
    return items


# ---------------------------------------------------------------------------
# Symbol tagging
# ---------------------------------------------------------------------------

def tag_symbols(text: str, symbol_map: Optional[Dict[str, str]]) -> List[str]:
    """Tag up to ``MAX_SYMBOLS`` TICKERS mentioned in ``text`` (sorted).

    Two match modes over ``symbol_map`` keys (``{key: isin}``):
      * symbol-shaped keys (``\\b[A-Z][A-Z0-9&-]{2,14}\\b``) match uppercase
        tokens and are returned as-is;
      * prose keys (company names, e.g. ``"HDFC Bank"`` after suffix stripping)
        match case-insensitively on a word boundary and are resolved back to the
        ticker sharing their ISIN, so callers always receive tickers.

    Fail-closed: no text or no map -> ``[]``.
    """
    if not text or not symbol_map:
        return []
    body = text if isinstance(text, str) else str(text)
    if not body or not re.search(r"[A-Za-z]", body):
        return []
    tokens = set(SYMBOL_TOKEN_RE.findall(body))

    # ISIN -> ticker, so a prose-name hit yields the tradeable symbol.
    isin_to_symbol: Dict[str, str] = {}
    for key, isin in symbol_map.items():
        if isinstance(key, str) and SYMBOL_TOKEN_RE.fullmatch(key) and isin:
            isin_to_symbol.setdefault(str(isin), key)

    hits = []
    for key, isin in symbol_map.items():
        if not isinstance(key, str) or not key:
            continue
        if SYMBOL_TOKEN_RE.fullmatch(key):
            if key in tokens:
                hits.append(key)
            continue
        if len(key) < 5:
            continue
        rx = _NAME_WORD_RE_CACHE.get(key)
        if rx is None:
            rx = re.compile(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])",
                            re.IGNORECASE)
            if len(_NAME_WORD_RE_CACHE) < 50_000:
                _NAME_WORD_RE_CACHE[key] = rx
        if rx.search(body):
            ticker = isin_to_symbol.get(str(isin or ""))
            if ticker:
                hits.append(ticker)
    return sorted(set(hits))[:MAX_SYMBOLS]


def load_symbol_map(repo: Any = None,
                    include_names: bool = False) -> Dict[str, str]:
    """``{nse_symbol: isin}`` from the active master; ``{}`` on any failure.

    ``include_names=True`` additionally maps ``company_name -> isin`` so
    :func:`tag_symbols` can match company names written out in prose.
    """
    try:
        if repo is None:
            from reality_engine.db.repository import Repository
            repo = Repository()
        rows = repo.get_all_companies(active_only=True) or []
    except Exception as e:
        logger.warning("load_symbol_map failed: %s", e)
        return {}
    mapping: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("nse_symbol") or "").strip()
        isin = str(row.get("isin") or "").strip()
        if symbol:
            mapping[symbol] = isin
        if include_names:
            # "HDFC Bank Ltd." -> "HDFC Bank" so prose ("HDFC Bank shares gain")
            # matches; bare acronyms/short names are skipped as too collision-prone.
            name = _CORP_SUFFIX_RE.sub(" ", str(row.get("company_name") or ""))
            name = _WS_RE.sub(" ", name.replace("&", "and")).strip(" .,-")
            if len(name) >= 5 and name not in mapping:
                mapping[name] = isin
    return mapping


# ---------------------------------------------------------------------------
# Normalization (raw_documents contract + text/symbols extras)
# ---------------------------------------------------------------------------

def _sha(link: str, title: str) -> str:
    return hashlib.sha256(f"{link}|{title}".encode("utf-8")).hexdigest()


def normalize(items: List[Dict[str, Any]], outlet: str,
              symbol_map: Optional[Dict[str, str]] = None
              ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Map feed items -> raw_documents contracts + ``text``/``symbols`` extras.

    ``media_url`` rides along as an extra key too (never part of the
    ``raw_documents`` contract: that table has no such column).

    Rows with a missing/unparseable date are skipped and counted (the column is
    NOT NULL); rows with neither title nor link are skipped and counted. Exact
    ``sha256_hash`` repeats inside the batch are dropped and counted.
    """
    stats: Dict[str, Any] = {
        "items": 0,
        "records": 0,
        "skipped_no_date": 0,
        "skipped_empty": 0,
        "duplicates": 0,
    }
    records: List[Dict[str, Any]] = []
    if not items:
        return records, stats
    source_type = f"{SOURCE_PREFIX}{outlet}"
    creator = OUTLET_NAMES.get(outlet, outlet)
    seen = set()
    for raw in items:
        stats["items"] += 1
        item = raw if isinstance(raw, dict) else {}
        title = _strip_html(item.get("title"))
        link = str(item.get("link") or "").strip()
        if not title or not link:
            stats["skipped_empty"] += 1
            continue
        published_date = _to_iso_date(item.get("published_raw"))
        if not published_date:
            stats["skipped_no_date"] += 1
            continue
        summary = _strip_html(item.get("summary"), limit=SUMMARY_MAX_CHARS)
        text = f"{title} :: {summary}" if summary else title
        digest = _sha(link, title)
        if digest in seen:
            stats["duplicates"] += 1
            continue
        seen.add(digest)
        records.append({
            "title": title,
            "source_type": source_type,
            "published_date": published_date,
            "fiscal_period": None,
            "source_url": link,
            "creator_or_ministry": creator,
            "sha256_hash": digest,
            "local_file_path": None,
            "file_size_bytes": None,
            "text": text,
            "symbols": tag_symbols(text, symbol_map) if symbol_map else [],
            "media_url": str(item.get("media_url") or "").strip(),
        })
    stats["records"] = len(records)
    return records, stats


# ---------------------------------------------------------------------------
# Fetch orchestration
# ---------------------------------------------------------------------------

def fetch_outlet(key: str, fetcher: Optional[Callable] = None,
                 limit: Optional[int] = None) -> List[Dict[str, str]]:
    """``fetch_feed(FEEDS[key])``; unknown key or feed miss -> ``[]``."""
    url = FEEDS.get(key)
    if not url:
        logger.warning("fetch_outlet: unknown feed key %r", key)
        return []
    items = fetch_feed(url, fetcher=fetcher)
    if limit is not None:
        items = items[: max(0, int(limit))]
    return items


def fetch_feeds(keys: Optional[List[str]] = None,
                limit: Optional[int] = None,
                symbol_map: Optional[Dict[str, str]] = None,
                fetcher: Optional[Callable] = None
                ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Fetch + normalize several outlets -> ``(records, stats)``.

    ``keys=None`` means every registered feed. Each feed is fail-closed
    independently: one dead feed never suppresses the others.
    """
    selected = list(keys) if keys else list(FEEDS)
    records: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {
        "feeds_requested": len(selected),
        "feeds_ok": 0,
        "feeds_failed": 0,
        "items": 0,
        "records": 0,
        "skipped_no_date": 0,
        "skipped_empty": 0,
        "duplicates": 0,
        "per_feed": {},
    }
    for key in selected:
        if key not in FEEDS:
            logger.warning("fetch_feeds: unknown feed key %r", key)
            stats["feeds_failed"] += 1
            continue
        items = fetch_outlet(key, fetcher=fetcher, limit=limit)
        if not items:
            stats["feeds_failed"] += 1
            stats["per_feed"][key] = {"items": 0, "records": 0}
            continue
        stats["feeds_ok"] += 1
        feed_records, feed_stats = normalize(items, key, symbol_map=symbol_map)
        records.extend(feed_records)
        for bucket in ("items", "records", "skipped_no_date",
                       "skipped_empty", "duplicates"):
            stats[bucket] += feed_stats[bucket]
        stats["per_feed"][key] = {
            "items": feed_stats["items"],
            "records": feed_stats["records"],
        }
    return records, stats


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _first_symbol(symbols: List[str], symbol_map: Dict[str, str]) -> str:
    """First tagged entry that is both a known symbol and symbol-shaped."""
    for name in symbols or []:
        if isinstance(name, str) and name in symbol_map and \
                SYMBOL_TOKEN_RE.fullmatch(name):
            return name
    for name in symbols or []:
        if isinstance(name, str) and SYMBOL_TOKEN_RE.fullmatch(name):
            return name
    return ""


def persist(records: List[Dict[str, Any]], repo: Any = None) -> Dict[str, int]:
    """Upsert raw_documents rows, then write one FTS chunk each.

    ``chunk_id = f"{source_type}:{doc_id}:0"`` where ``doc_id`` is resolved via
    ``repo.get_raw_document_by_hash(sha256_hash)`` after the upsert. Records
    without ``text`` are skipped. Idempotent: the existing chunk for a
    ``chunk_id`` is deleted first, so re-persisting the same batch leaves one
    raw row and one FTS row.

    Returns ``{"raw_written": new rows, "raw_updated": existing rows refreshed,
    "fts_written": chunks inserted}``.
    """
    out = {"raw_written": 0, "raw_updated": 0, "fts_written": 0}
    if not records:
        return out
    if repo is None:
        from reality_engine.db.repository import Repository
        repo = Repository()
    symbol_map = load_symbol_map(repo, include_names=True)
    for rec in records:
        rec = rec if isinstance(rec, dict) else {}
        text = rec.get("text")
        if not text:
            continue
        contract = {k: rec.get(k) for k in _CONTRACT_KEYS}
        try:
            digest = contract.get("sha256_hash")
            existed = bool(digest) and repo.get_raw_document_by_hash(digest) is not None
            repo.upsert_raw_document(contract)
            row = repo.get_raw_document_by_hash(digest)
            if not row:
                logger.warning("persist: no raw_documents row for %s", digest)
                continue
            doc_id = row.get("doc_id") if isinstance(row, dict) else row[0]
            if existed:
                out["raw_updated"] += 1
            else:
                out["raw_written"] += 1
            chunk_id = f"{contract['source_type']}:{doc_id}:0"
            symbols = rec.get("symbols") or []
            if not symbols and symbol_map:
                # Callers that normalize without a symbol map (e.g. a bare CLI
                # fetch) still get tagging here — one place, always applied.
                symbols = tag_symbols(text, symbol_map)
            symbol = _first_symbol(symbols, symbol_map)
            delete = getattr(repo, "delete_fts_document", None)
            if callable(delete):
                delete(chunk_id)
            written = repo.insert_fts_chunks([{
                "chunk_id": chunk_id,
                "symbol": symbol,
                "isin": symbol_map.get(symbol, ""),
                "source_type": contract["source_type"],
                "document_date": contract["published_date"],
                "document_text": text,
            }])
            out["fts_written"] += int(written or 0)
        except Exception as e:
            logger.warning("persist skip %s: %s", contract.get("source_url"), e)
            continue
    return out
