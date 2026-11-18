"""T-223 (R-012/R-014): turn a store's ``filing`` rows into fetch targets for missing documents.

Reads ``filing`` (``link_only`` cover letters and ``not_fetched`` transcripts/decks), ``doc`` and ``doc_page``
through a read-only connection, classifies cover letters, resolves PDFs or investor-page links through an
injectable HTTP fetcher, and emits new documents only via ``<store_dir>/raw/manifest.csv`` (never writing the
store SQLite database directly).

CLI: ``python -m reality_engine.pilot3.link_follow --store-dir <dir> [--plan-only] [--site] [--symbols A,B] [--json out]``
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import time
from collections import Counter
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urldefrag, urljoin, urlparse

from reality_engine import raw_store
from reality_engine.config import DEFAULT_HEADERS
from reality_engine.db.readonly import connect_ro
from reality_engine.pilot3 import call_dates, doc_identity, linked_transcripts

DEFAULT_RAW_ROOT = Path(r"D:\RealityEngine\raw\linked_docs")
MAX_BYTES = 40 * 1024 * 1024
REQUEST_TIMEOUT_S = 60.0
SITE_MAX_LINKS_PER_PAGE = 12
SITE_MAX_DEPTH = 2
SITE_MAX_PAGES = 40
SITE_MIN_HITS = 3

AUDIO_EXTS = (".mp3", ".mp4", ".m4a", ".wav", ".aac")
INVITATION_DOMAINS = (
    "choruscall.in",
    "zoom.us",
    "kaptify.in",
    "webex",
    "teams.microsoft",
    "reg.dsnl.in",
)
SITE_EXCLUDE_DOMAINS = (
    "bseindia",
    "nseindia",
    "sebi.gov",
    "mca.gov",
    "choruscall",
    "zoom",
    "kaptify",
    "linkintime",
    "kfintech",
    "cdsl",
    "nsdl",
    "gmail",
    "bigshareonline",
    "cameoindia",
    "purvashare",
    "skylinerta",
    "maserv",
    "beetalfinancial",
    "adroitcorporate",
    "integratedindia",
    "alankit",
    "datamatics",
    "mcsregistrars",
    "sharexindia",
    "in.mpms.mufg.com",
    "yahoo",
    "hotmail",
    "outlook",
    "rediffmail",
)
COMPANY_STOPWORDS = frozenset({"limited", "ltd", "india", "industries", "corporation"})
BSE_ATTACH_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}"

MANIFEST_HEADER: tuple[str, ...] = (
    "isin",
    "symbol_at_time",
    "scrip_code",
    "newsid",
    "bucket",
    "headline",
    "category",
    "subcat",
    "dissem_ts",
    "url",
    "source",
    "local_path",
    "bytes",
    "sha256",
    "http_status",
    "attempts",
    "is_pdf",
    "is_scanned_guess",
    "skip_reason",
    "fetched_at",
    "status",
    "error",
)

RUN_CSV_HEADER: tuple[str, ...] = (
    "exchange",
    "filing_id",
    "symbol",
    "isin",
    "bse_code",
    "filed_at",
    "source",
    "intent",
    "kind",
    "target",
    "outcome",
    "reason",
    "pages",
    "sha256",
    "url",
)

GetFn = Callable[[str], tuple[str, str, bytes]]

_AUDIO_TEXT_RE = re.compile(r"\b(?:audio\s+recording|audio\s+link|recording\s+of\s+the)\b", re.I)
_INVITE_TEXT_RE = re.compile(
    r"\b(?:is\s+scheduled|will\s+be\s+held|invite|invitation|registration|dial[- ]?in)\b",
    re.I,
)
_FUTURE_TRANSCRIPT_RE = re.compile(r"\btranscripts?\b[^.\n]{0,40}\bwill\s+be\b", re.I)
_TRANSCRIPT_WORD_RE = re.compile(r"\btranscripts?\b", re.I)
_DECK_TEXT_RE = re.compile(r"\b(?:investor\s+presentation|earnings\s+presentation|presentation)\b", re.I)

_TX_LINK_RE = re.compile(r"transcript|con[-_ ]?call|earnings[-_ ]?call|conference[-_ ]?call", re.I)
_DECK_LINK_RE = re.compile(r"presentation|investor[-_ ]?ppt|\bppt\b", re.I)
_NAV_LINK_RE = re.compile(
    r"investor|financial|results|presentation|transcript|con[-_ ]?call|analyst|shareholder",
    re.I,
)

_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_MAP = {m: i + 1 for i, m in enumerate(_MONTHS)}
_MONTH_RE = "|".join(_MONTHS)

_DMY_SEP_RE = re.compile(r"(?<!\d)(\d{1,2})[-./](\d{1,2})[-./](20\d{2})(?!\d)")
_YMD_SEP_RE = re.compile(r"(?<!\d)(20\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)")
_YMD_COMPACT_RE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_DMY_COMPACT_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)")
_MDY_NAME_RE = re.compile(rf"(?<![a-z])({_MONTH_RE})[-\s,]+(\d{{1,2}})(?:st|nd|rd|th)?[-\s,]+(20\d{{2}})(?!\d)", re.I)
_DMY_NAME_RE = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[-\s]+(?:of[-\s]+)?({_MONTH_RE})[-\s,]+(20\d{{2}})(?!\d)",
    re.I,
)
_QTAG_RE = re.compile(r"(?<![a-z0-9])q([1-4])[-_\s]*fy[-_\s]*(?:20)?(\d{2})(?![a-z0-9])", re.I)
_DOMAIN_URL_RE = re.compile(r"https?://([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)
_DOMAIN_WWW_RE = re.compile(r"\b(www\.[a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)


class _HttpStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _AnchorParser(HTMLParser):
    """Collect ``(href, anchor_text)`` from HTML ``<a href=...>`` tags."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((val for k, val in attrs if k.lower() == "href" and val), None)
        if href:
            self._href = href.strip()
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = " ".join("".join(self._buf).split())
            self.links.append((self._href, text))
            self._href = None
            self._buf = []


# --------------------------------------------------------------------------- HTTP
def default_get(url: str, *, attempts: int = 3, backoff: float = 2.0, sleep=time.sleep) -> tuple[str, str, bytes]:
    """Polite HTTP GET using ``linked_transcripts`` per-host pacing, 60 s timeout, max 40 MB."""
    import requests

    host = (urlparse(url).netloc or "").lower()
    session = requests.Session()
    try:
        for attempt in range(1, attempts + 1):
            gap = linked_transcripts.LAST_REQUEST.get(host, 0.0) + linked_transcripts.MIN_INTERVAL_S - time.monotonic()
            if gap > 0:
                sleep(gap)
            linked_transcripts.LAST_REQUEST[host] = time.monotonic()
            try:
                resp = session.get(
                    url,
                    headers=DEFAULT_HEADERS,
                    timeout=REQUEST_TIMEOUT_S,
                    allow_redirects=True,
                    stream=True,
                )
            except Exception:  # noqa: BLE001 - network
                if attempt == attempts:
                    raise
                sleep(backoff * attempt)
                continue
            try:
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt == attempts:
                        raise _HttpStatusError(resp.status_code)
                    sleep(backoff * (2 ** (attempt - 1)))
                    continue
                if resp.status_code != 200:
                    raise _HttpStatusError(resp.status_code)
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit() and int(cl) > MAX_BYTES:
                    raise ValueError(f"response exceeds {MAX_BYTES} bytes")
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError(f"response exceeds {MAX_BYTES} bytes")
                    chunks.append(chunk)
                ctype = str(resp.headers.get("Content-Type") or "")
                return str(resp.url or url), ctype, b"".join(chunks)
            finally:
                resp.close()
        raise RuntimeError("unreachable")
    finally:
        session.close()


# --------------------------------------------------------------------------- URL helpers
def _clean_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw.lower().startswith(("http://", "https://")):
        return ""
    defragged, _frag = urldefrag(raw)
    return defragged.strip()


def _is_bare_homepage(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.path in ("", "/") and not parsed.query


def _is_audio_url(url: str) -> bool:
    parsed = urlparse(url)
    path_l = parsed.path.lower()
    host_l = parsed.netloc.lower()
    if path_l.endswith(AUDIO_EXTS):
        return True
    if host_l in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
        return True
    if "mediafire.com" in host_l and "/file" in path_l:
        return True
    return False


def _is_invitation_url(url: str) -> bool:
    lower = url.lower()
    host = urlparse(url).netloc.lower()
    return "diamondpass" in lower or any(dom in host for dom in INVITATION_DOMAINS)


def _is_pdf_url(url: str) -> bool:
    lower = url.lower()
    path_l = urlparse(url).path.lower()
    return path_l.endswith(".pdf") or ".pdf?" in lower or lower.endswith(".pdf")


# --------------------------------------------------------------------------- classify_letter
def classify_letter(text: str, urls: Iterable[str]) -> tuple[str, list[str]]:
    """Classify a cover letter's ``(intent, targets)`` from its text and extracted URLs."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in urls or ():
        u = _clean_url(str(raw))
        if u and u not in seen:
            seen.add(u)
            cleaned.append(u)

    usable = [u for u in cleaned if not _is_bare_homepage(u)]
    has_pdf = any(_is_pdf_url(u) for u in usable)
    non_ignored = [u for u in usable if not _is_audio_url(u) and not _is_invitation_url(u)]
    targets = [u for u in non_ignored if _is_pdf_url(u)] + [u for u in non_ignored if not _is_pdf_url(u)]

    body = text or ""
    if (usable and all(_is_audio_url(u) for u in usable)) or (not has_pdf and _AUDIO_TEXT_RE.search(body)):
        return "audio", []
    if (not has_pdf and _INVITE_TEXT_RE.search(body)) or (
        usable and not has_pdf and all(_is_invitation_url(u) for u in usable)
    ):
        return "invitation", []

    text_no_future = _FUTURE_TRANSCRIPT_RE.sub("", body)
    if _TRANSCRIPT_WORD_RE.search(text_no_future):
        return "transcript", targets
    if (usable or targets) and _DECK_TEXT_RE.search(body):
        return "deck", targets

    for u in targets:
        if _TX_LINK_RE.search(u):
            return "transcript", targets
        if _DECK_LINK_RE.search(u):
            return "deck", targets
    return "unknown", targets


# --------------------------------------------------------------------------- dates & scoring
def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _dates_from_text(text: str) -> list[date]:
    found: list[date] = []
    for m in _DMY_SEP_RE.finditer(text):
        dt = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if dt:
            found.append(dt)
    for m in _YMD_SEP_RE.finditer(text):
        dt = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            found.append(dt)
    for m in _YMD_COMPACT_RE.finditer(text):
        dt = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            found.append(dt)
    for m in _DMY_COMPACT_RE.finditer(text):
        dt = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if dt:
            found.append(dt)
    for m in _MDY_NAME_RE.finditer(text):
        dt = _safe_date(int(m.group(3)), _MONTH_MAP[m.group(1).lower()], int(m.group(2)))
        if dt:
            found.append(dt)
    for m in _DMY_NAME_RE.finditer(text):
        dt = _safe_date(int(m.group(3)), _MONTH_MAP[m.group(2).lower()], int(m.group(1)))
        if dt:
            found.append(dt)
    return found


def _quarter_matches_text(text: str, tag: str) -> bool:
    if not tag or "FY" not in tag:
        return False
    q_part, fy_part = tag.split("FY", 1)
    q_num = q_part.lstrip("Qq")
    return bool(re.search(rf"(?<![a-z0-9])q[-_\s]*{q_num}[-_\s]*fy[-_\s]*(?:20)?{fy_part}(?![a-z0-9])", text, re.I))


def _score_pdf_link(href: str, anchor_text: str, intent: str, anchor_date: str | None) -> int:
    combined = f"{href} {anchor_text}"
    score = 0
    if intent == "transcript" and _TX_LINK_RE.search(combined):
        score += 3
    elif intent == "deck" and _DECK_LINK_RE.search(combined):
        score += 3
    elif intent == "unknown" and (_TX_LINK_RE.search(combined) or _DECK_LINK_RE.search(combined)):
        score += 3

    if anchor_date:
        try:
            anchor_dt = date.fromisoformat(anchor_date[:10])
        except ValueError:
            anchor_dt = None
        if anchor_dt is not None:
            if any(abs((dt - anchor_dt).days) <= 30 for dt in _dates_from_text(combined)):
                score += 3
            tag = linked_transcripts.quarter_tag(anchor_date[:10])
            if tag and _quarter_matches_text(combined, tag):
                score += 2
    return score


def _extract_html_links(html: str, base_url: str) -> list[tuple[str, str]]:
    parser = _AnchorParser()
    parser.feed(html)
    parser.close()
    out: list[tuple[str, str]] = []
    for raw_href, text in parser.links:
        abs_url = _clean_url(urljoin(base_url, raw_href))
        if abs_url:
            out.append((abs_url, text))
    return out


# --------------------------------------------------------------------------- validation & resolve
def _company_tokens(company_names: Iterable[str] | str | None) -> list[tuple[str, bool]]:
    if company_names is None:
        return []
    items = [company_names] if isinstance(company_names, str) else list(company_names)
    tokens: list[tuple[str, bool]] = []
    seen: set[tuple[str, bool]] = set()
    for raw in items:
        s = str(raw or "").strip()
        if not s:
            continue
        if " " not in s and s.isupper() and s.isalnum() and 2 <= len(s) <= 16:
            tok = (s, True)
            if tok not in seen:
                seen.add(tok)
                tokens.append(tok)
        for word in re.findall(r"[A-Za-z0-9]{4,}", s):
            lw = word.lower()
            if lw in COMPANY_STOPWORDS:
                continue
            tok = (lw, False)
            if tok not in seen:
                seen.add(tok)
                tokens.append(tok)
    return tokens


def _check_company(first2: str, company_names: Iterable[str] | str | None) -> bool:
    tokens = _company_tokens(company_names)
    if not tokens:
        return True
    for tok, exact_case in tokens:
        flags = 0 if exact_case else re.I
        if re.search(rf"\b{re.escape(tok)}\b", first2, flags):
            return True
    return False


def _check_candidate(
    url: str,
    data: bytes,
    texts: list[str],
    intent: str,
    anchor_date: str | None,
    company_names: Iterable[str] | str | None,
) -> dict[str, Any]:
    pages = len(texts)
    min_pages = 5 if intent == "deck" else 3
    if pages < min_pages:
        return {"status": "failed", "reason": "too_short"}

    first3 = "\n".join(texts[:3])
    is_tx = bool(linked_transcripts.TRANSCRIPT_TEXT.search(first3) or doc_identity.moderator_line(first3))
    is_strict_tx = bool(doc_identity.moderator_line(first3) or _TRANSCRIPT_WORD_RE.search(first3))

    if intent == "transcript":
        if not is_tx:
            return {"status": "failed", "reason": "not_transcript"}
        kind = "transcript"
    elif intent == "deck":
        if is_strict_tx:
            return {"status": "failed", "reason": "not_transcript"}
        kind = "deck"
    else:
        kind = "transcript" if is_tx else "deck"
        if kind == "deck" and pages < 5:
            return {"status": "failed", "reason": "too_short"}

    first2 = "\n".join(texts[:2])
    if not _check_company(first2, company_names):
        return {"status": "failed", "reason": "wrong_company"}

    if anchor_date:
        try:
            anchor_dt = date.fromisoformat(anchor_date[:10])
        except ValueError:
            anchor_dt = None
        if anchor_dt is not None:
            printed = call_dates.call_date(texts)
            if printed:
                printed_dt = date.fromisoformat(printed[:10])
                if not (anchor_dt - timedelta(days=60) <= printed_dt <= anchor_dt + timedelta(days=5)):
                    return {"status": "failed", "reason": "date_mismatch"}

    return {"status": "resolved", "url": url, "data": data, "pages": pages, "texts": texts, "kind": kind}


def _safe_fetch(get_fn: GetFn, url: str) -> tuple[tuple[str, str, bytes] | None, str]:
    try:
        final_url, ctype, data = get_fn(url)
    except Exception as exc:  # noqa: BLE001 - caller maps to reason
        code = getattr(exc, "status_code", None)
        if code is None:
            resp = getattr(exc, "response", None)
            code = getattr(resp, "status_code", None) if resp is not None else None
        if code is not None:
            return None, f"http_{int(code)}"
        return None, "network"
    if data is None:
        return None, "network"
    if not data:
        return None, "not_pdf"
    return (final_url or url, ctype or "", data), ""


def _validate_pdf_bytes(
    url: str,
    data: bytes,
    intent: str,
    anchor_date: str | None,
    company_names: Iterable[str] | str | None,
    get_fn: GetFn,
) -> dict[str, Any]:
    try:
        texts, uris = linked_transcripts.pdf_info(data)
    except Exception:  # noqa: BLE001 - broken PDF
        return {"status": "failed", "reason": "not_pdf"}

    if len(texts) <= 2:
        following = linked_transcripts.urls_from_links(uris) + [
            u for u in linked_transcripts.urls_from_text("\n".join(texts)) if _is_pdf_url(u)
        ]
        last_err: dict[str, Any] | None = None
        for nxt in dict.fromkeys(following):
            if nxt == url:
                continue
            got, err = _safe_fetch(get_fn, nxt)
            if got is None:
                last_err = {"status": "failed", "reason": err}
                continue
            nxt_url, _ctype, nxt_data = got
            if nxt_data[:5] != b"%PDF-":
                last_err = {"status": "failed", "reason": "not_pdf"}
                continue
            try:
                nxt_texts, _ = linked_transcripts.pdf_info(nxt_data)
            except Exception:  # noqa: BLE001
                last_err = {"status": "failed", "reason": "not_pdf"}
                continue
            res = _check_candidate(nxt_url, nxt_data, nxt_texts, intent, anchor_date, company_names)
            if res["status"] == "resolved":
                return res
            last_err = res
        return last_err if last_err and last_err["reason"] != "too_short" else {"status": "failed", "reason": "too_short"}

    return _check_candidate(url, data, texts, intent, anchor_date, company_names)


def _is_html(ctype: str, data: bytes) -> bool:
    if "html" in ctype.lower():
        return True
    head = data[:4096].lower()
    return b"<html" in head or b"<!doctype" in head or b"<a " in head


def resolve(
    target: str,
    intent: str,
    anchor_date: str | None,
    company_names: Iterable[str] | str | None,
    *,
    get: GetFn | None = None,
) -> dict[str, Any]:
    """Fetch ``target`` (PDF, 1-2 page PDF cover, or HTML investor page) and validate the candidate document."""
    get_fn = get or default_get
    got, err = _safe_fetch(get_fn, target)
    if got is None:
        return {"status": "failed", "reason": err}
    final_url, ctype, data = got
    if data[:5] == b"%PDF-":
        return _validate_pdf_bytes(final_url, data, intent, anchor_date, company_names, get_fn)
    if not _is_html(ctype, data):
        return {"status": "failed", "reason": "not_pdf"}

    html = data.decode("utf-8", errors="replace")
    all_links = _extract_html_links(html, final_url)
    pdf_links = [(href, text) for href, text in all_links if _is_pdf_url(href)]
    if not pdf_links:
        return {"status": "failed", "reason": "no_pdf_on_page"}

    scored: list[tuple[int, int, str]] = []
    seen_href: set[str] = set()
    for idx, (href, anchor_text) in enumerate(pdf_links):
        if href in seen_href:
            continue
        seen_href.add(href)
        sc = _score_pdf_link(href, anchor_text, intent, anchor_date)
        if sc >= 4:
            scored.append((sc, -idx, href))

    if not scored:
        return {"status": "failed", "reason": "no_matching_pdf"}

    scored.sort(reverse=True)
    first_fail: dict[str, Any] | None = None
    for _sc, _neg_idx, pdf_url in scored[:3]:
        c_got, c_err = _safe_fetch(get_fn, pdf_url)
        if c_got is None:
            first_fail = first_fail or {"status": "failed", "reason": c_err}
            continue
        c_url, _c_type, c_data = c_got
        if c_data[:5] != b"%PDF-":
            first_fail = first_fail or {"status": "failed", "reason": "not_pdf"}
            continue
        res = _validate_pdf_bytes(c_url, c_data, intent, anchor_date, company_names, get_fn)
        if res["status"] == "resolved":
            return res
        first_fail = first_fail or res
    return first_fail or {"status": "failed", "reason": "no_matching_pdf"}


# --------------------------------------------------------------------------- plan_store
def _open_ro(store_db: Path | str | sqlite3.Connection) -> tuple[sqlite3.Connection, bool]:
    if isinstance(store_db, sqlite3.Connection):
        return store_db, False
    conn = connect_ro(Path(store_db), timeout_s=60)
    if conn is None:
        raise RuntimeError(f"Could not open read-only connection to {store_db}")
    return conn, True


def _company_meta(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    cols = {row[1] for row in conn.execute("PRAGMA table_info(company)")}
    name_col = "name" if "name" in cols else ("company_name" if "company_name" in cols else "NULL")
    for sym, isin, bse_code, name in conn.execute(
        f"SELECT symbol, isin, bse_code, {name_col} FROM company ORDER BY symbol"
    ):
        sym_u = str(sym or "").strip().upper()
        if not sym_u:
            continue
        entry = meta.setdefault(sym_u, {"isin": isin, "bse_code": str(bse_code) if bse_code else None, "names": [sym_u]})
        if isin and not entry["isin"]:
            entry["isin"] = isin
        if bse_code and not entry["bse_code"]:
            entry["bse_code"] = str(bse_code)
        if name and str(name).strip() and str(name).strip() not in entry["names"]:
            entry["names"].append(str(name).strip())
    return meta


def _letter_text(conn: sqlite3.Connection, doc_key: str | None) -> str:
    if not doc_key:
        return ""
    rows = conn.execute("SELECT text FROM doc_page WHERE doc_key=? ORDER BY page", (doc_key,)).fetchall()
    return "\n".join(str(r[0] or "") for r in rows)


def _exchange_target_url(exchange: str, attachment: str | None) -> str | None:
    att = str(attachment or "").strip()
    if not att:
        return None
    if att.lower().startswith(("http://", "https://")):
        return _clean_url(att)
    if exchange.upper() == "BSE":
        return BSE_ATTACH_URL.format(name=att.lstrip("/"))
    return None


def _base_item(
    *,
    exchange: str,
    filing_id: str,
    symbol: str,
    isin: str | None,
    bse_code: str | None,
    filed_at: str | None,
    source: str,
    intent: str,
    target: str | None,
) -> dict[str, Any]:
    return {
        "exchange": exchange,
        "filing_id": filing_id,
        "symbol": symbol,
        "isin": isin,
        "bse_code": bse_code,
        "filed_at": filed_at,
        "source": source,
        "intent": intent,
        "kind": intent if intent in ("transcript", "deck") else None,
        "target": target,
        "outcome": None,
        "reason": "",
        "pages": 0,
        "sha256": None,
        "url": None,
    }


def _resolve_target_to_item(
    item: dict[str, Any],
    target: str,
    intent: str,
    anchor_date: str | None,
    company_names: list[str],
    held_shas: set[str],
    get_fn: GetFn,
) -> dict[str, Any]:
    res = resolve(target, intent, anchor_date, company_names, get=get_fn)
    if res["status"] != "resolved":
        return {**item, "target": target, "outcome": "failed", "reason": res["reason"]}
    sha = linked_transcripts._sha256(res["data"])
    if sha in held_shas:
        return {
            **item,
            "target": target,
            "kind": res["kind"],
            "outcome": "held",
            "pages": res["pages"],
            "sha256": sha,
            "url": res["url"],
        }
    return {
        **item,
        "target": target,
        "kind": res["kind"],
        "outcome": "resolved",
        "pages": res["pages"],
        "sha256": sha,
        "url": res["url"],
        "data": res["data"],
        "texts": res["texts"],
    }


def plan_store(
    store_db: Path | str | sqlite3.Connection,
    *,
    get: GetFn | None = None,
    symbols: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Build fetch plan items for ``link_only`` and ``not_fetched`` transcript/deck ``filing`` rows."""
    get_fn = get or default_get
    wanted = {s.strip().upper() for s in symbols if s and s.strip()} if symbols is not None else None
    conn, should_close = _open_ro(store_db)
    try:
        has_filing = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='filing'"
        ).fetchone()
        if not has_filing:
            return []
        held_shas = {str(sha).lower() for (sha,) in conn.execute("SELECT sha256 FROM doc WHERE sha256 IS NOT NULL")}
        meta = _company_meta(conn)

        link_rows = conn.execute(
            "SELECT exchange, filing_id, symbol, isin, filed_at, held_doc_key, link_urls "
            "FROM filing WHERE status='link_only' "
            "ORDER BY symbol, COALESCE(filed_at, ''), exchange, filing_id"
        ).fetchall()
        nf_rows = conn.execute(
            "SELECT exchange, filing_id, symbol, isin, filed_at, kind_hint, attachment "
            "FROM filing WHERE status='not_fetched' AND kind_hint IN ('transcript', 'deck') "
            "AND attachment IS NOT NULL AND attachment != '' "
            "ORDER BY symbol, COALESCE(filed_at, ''), exchange, filing_id"
        ).fetchall()

        plan: list[dict[str, Any]] = []
        seen_targets: set[tuple[str, str]] = set()

        for exchange, filing_id, symbol, isin, filed_at, held_doc_key, link_urls_json in link_rows:
            sym_u = str(symbol or "").strip().upper()
            if wanted is not None and sym_u not in wanted:
                continue
            info = meta.get(sym_u, {"isin": None, "bse_code": None, "names": [sym_u]})
            use_isin = isin or info["isin"]
            bse_code = info["bse_code"]
            try:
                urls = json.loads(link_urls_json or "[]")
            except ValueError:
                urls = []
            text = _letter_text(conn, held_doc_key)
            intent, targets = classify_letter(text, urls)
            base = _base_item(
                exchange=str(exchange),
                filing_id=str(filing_id),
                symbol=sym_u,
                isin=use_isin,
                bse_code=bse_code,
                filed_at=filed_at,
                source="link_follow",
                intent=intent,
                target=targets[0] if targets else None,
            )
            if intent == "audio":
                plan.append({**base, "outcome": "audio_only"})
                continue
            if intent == "invitation":
                plan.append({**base, "outcome": "invitation"})
                continue
            if not targets:
                plan.append({**base, "outcome": "no_target"})
                continue

            fresh_targets = [t for t in targets if (sym_u, t) not in seen_targets]
            if not fresh_targets:
                continue
            anchor = str(filed_at)[:10] if filed_at else None
            chosen: dict[str, Any] | None = None
            for t in fresh_targets:
                seen_targets.add((sym_u, t))
                attempt = _resolve_target_to_item(
                    base, t, intent, anchor, info["names"], held_shas, get_fn
                )
                if attempt["outcome"] in ("resolved", "held"):
                    chosen = attempt
                    break
                if chosen is None:
                    chosen = attempt
            if chosen is not None:
                plan.append(chosen)

        for exchange, filing_id, symbol, isin, filed_at, kind_hint, attachment in nf_rows:
            sym_u = str(symbol or "").strip().upper()
            if wanted is not None and sym_u not in wanted:
                continue
            target = _exchange_target_url(str(exchange), attachment)
            if not target or (sym_u, target) in seen_targets:
                continue
            seen_targets.add((sym_u, target))
            info = meta.get(sym_u, {"isin": None, "bse_code": None, "names": [sym_u]})
            use_isin = isin or info["isin"]
            intent = str(kind_hint)
            base = _base_item(
                exchange=str(exchange),
                filing_id=str(filing_id),
                symbol=sym_u,
                isin=use_isin,
                bse_code=info["bse_code"],
                filed_at=filed_at,
                source="exchange",
                intent=intent,
                target=target,
            )
            anchor = str(filed_at)[:10] if filed_at else None
            plan.append(_resolve_target_to_item(base, target, intent, anchor, info["names"], held_shas, get_fn))

        return plan
    finally:
        if should_close:
            conn.close()


# --------------------------------------------------------------------------- apply_plan
def _existing_manifest_keys(manifest: Path) -> tuple[set[str], set[str], list[str]]:
    if not manifest.is_file() or manifest.stat().st_size == 0:
        return set(), set(), list(MANIFEST_HEADER)
    shas: set[str] = set()
    newsids: set[str] = set()
    with manifest.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or MANIFEST_HEADER)
        for row in reader:
            sha = str(row.get("sha256") or "").strip().lower()
            if sha:
                shas.add(sha)
            nid = str(row.get("newsid") or "").strip()
            if nid:
                newsids.add(nid)
    return shas, newsids, fieldnames


def apply_plan(
    store_dir: Path | str,
    items: list[dict[str, Any]],
    raw_root: Path | str = DEFAULT_RAW_ROOT,
    store=raw_store.store_bytes,
) -> dict[str, int]:
    """Store resolved PDFs, append new rows to ``<store_dir>/raw/manifest.csv``, and log the run CSV."""
    store_dir = Path(store_dir)
    raw_root = Path(raw_root)
    manifest = store_dir / "raw" / "manifest.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)

    existing_shas, existing_newsids, fieldnames = _existing_manifest_keys(manifest)
    need_header = not manifest.is_file() or manifest.stat().st_size == 0
    need_leading_newline = False
    if not need_header:
        with manifest.open("rb") as rf:
            rf.seek(-1, 2)
            need_leading_newline = rf.read(1) not in (b"\n", b"\r")

    new_rows: list[dict[str, Any]] = []
    now_iso = datetime.now().isoformat(timespec="seconds")
    for item in items:
        if item.get("outcome") != "resolved":
            continue
        data = item.get("data")
        if not isinstance(data, (bytes, bytearray)):
            continue
        raw_bytes = bytes(data)
        sha = str(item.get("sha256") or linked_transcripts._sha256(raw_bytes)).lower()
        symbol = str(item["symbol"])
        exchange = str(item["exchange"])
        filing_id = str(item["filing_id"])
        newsid = f"link:{exchange}:{filing_id}"
        if sha in existing_shas or newsid in existing_newsids:
            continue

        dest = raw_root / symbol / f"{exchange}_{filing_id}_{sha[:12]}.pdf"
        store(dest, raw_bytes, index_path=raw_root / "_dedupe" / "sha_index.db")

        url = str(item.get("url") or item.get("target") or "")
        kind = str(item.get("kind") or item.get("intent") or "transcript")
        is_deck = kind == "deck"
        bucket = "investor_presentation" if is_deck else "concall_transcript"
        subcat = "Investor Presentation" if is_deck else "Earnings Call Transcript"
        label = linked_transcripts.call_label(url, None)
        headline = f"{label} (linked from {exchange} filing {filing_id})"
        texts = item.get("texts") or []
        mean_chars = (sum(len(t) for t in texts) / len(texts)) if texts else 0.0
        source = str(item.get("source") or "link_follow")
        dissem_ts = now_iso if (source == "company_site" or exchange == "SITE") else str(item.get("filed_at") or now_iso)

        row = {
            "isin": item.get("isin") or "",
            "symbol_at_time": symbol,
            "scrip_code": item.get("bse_code") or "",
            "newsid": newsid,
            "bucket": bucket,
            "headline": headline,
            "category": "Company Update",
            "subcat": subcat,
            "dissem_ts": dissem_ts,
            "url": url,
            "source": source,
            "local_path": str(dest),
            "bytes": len(raw_bytes),
            "sha256": sha,
            "http_status": 200,
            "attempts": 1,
            "is_pdf": 1,
            "is_scanned_guess": 1 if mean_chars < 50 else 0,
            "skip_reason": "",
            "fetched_at": now_iso,
            "status": "ok",
            "error": "",
        }
        new_rows.append(row)
        existing_shas.add(sha)
        existing_newsids.add(newsid)

    if new_rows or need_header:
        with manifest.open("a", encoding="utf-8", newline="") as fh:
            if need_leading_newline:
                fh.write("\n")
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            if need_header:
                writer.writeheader()
            for row in new_rows:
                writer.writerow(row)

    run_dir = store_dir / "link_follow"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S_%f")
    run_csv = run_dir / f"{run_id}.csv"
    with run_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(RUN_CSV_HEADER), extrasaction="ignore")
        writer.writeheader()
        for item in items:
            clean = {k: v for k, v in item.items() if k not in ("data", "texts")}
            writer.writerow(clean)

    return dict(Counter(str(item.get("outcome") or "unknown") for item in items))


# --------------------------------------------------------------------------- website finder
def _is_excluded_domain(domain: str) -> bool:
    dom = domain.lower()
    return any(excl in dom for excl in SITE_EXCLUDE_DOMAINS)


def _detect_website(conn: sqlite3.Connection, symbol: str) -> str | None:
    rows = conn.execute(
        "SELECT dp.text FROM doc d "
        "JOIN doc_page dp ON dp.doc_key = d.doc_key AND dp.page = 1 "
        "WHERE d.symbol=? ORDER BY d.doc_key LIMIT 30",
        (symbol,),
    ).fetchall()
    hits: Counter[str] = Counter()
    preferred_host: dict[str, Counter[str]] = {}
    for (text,) in rows:
        body = str(text or "")
        spans: list[str] = []
        for m in _DOMAIN_URL_RE.finditer(body):
            spans.append(m.group(1).lower())
        for m in _DOMAIN_WWW_RE.finditer(body):
            spans.append(m.group(1).lower())
        for raw_dom in spans:
            if _is_excluded_domain(raw_dom):
                continue
            base = raw_dom[4:] if raw_dom.startswith("www.") else raw_dom
            hits[base] += 1
            preferred_host.setdefault(base, Counter())[raw_dom] += 1
    if not hits:
        return None
    best_base, count = hits.most_common(1)[0]
    if count < SITE_MIN_HITS:
        return None
    best_host = preferred_host[best_base].most_common(1)[0][0]
    return f"https://{best_host}/"


def _same_domain(url_a: str, url_b: str) -> bool:
    ha = urlparse(url_a).netloc.lower().removeprefix("www.")
    hb = urlparse(url_b).netloc.lower().removeprefix("www.")
    return bool(ha and hb and ha == hb)


def _quarter_nominal_date(tag: str) -> date | None:
    """Representative call date for a quarter tag (e.g. ``Q2FY26`` -> ``2025-11-20``)."""
    m = re.fullmatch(r"Q([1-4])FY(\d{2})", tag)
    if not m:
        return None
    q = int(m.group(1))
    fy_end_year = 2000 + int(m.group(2))
    # Q1 (Apr-Jun) call ~Aug 20; Q2 (Jul-Sep) ~Nov 20; Q3 (Oct-Dec) ~Feb 20; Q4 (Jan-Mar) ~May 25.
    month, day, year = {
        1: (8, 20, fy_end_year - 1),
        2: (11, 20, fy_end_year - 1),
        3: (2, 20, fy_end_year),
        4: (5, 25, fy_end_year),
    }[q]
    return date(year, month, day)


def _site_link_date(href: str, anchor_text: str) -> str | None:
    combined = f"{href} {anchor_text}"
    dates = _dates_from_text(combined)
    if dates:
        return dates[0].isoformat()
    m = _QTAG_RE.search(combined)
    if m:
        tag = f"Q{m.group(1)}FY{m.group(2)}"
        nom = _quarter_nominal_date(tag)
        if nom:
            return nom.isoformat()
    return None


def _site_link_intent(href: str, anchor_text: str) -> str | None:
    combined = f"{href} {anchor_text}"
    if _TX_LINK_RE.search(combined):
        return "transcript"
    if _DECK_LINK_RE.search(combined):
        return "deck"
    return None


def find_site_docs(
    store_db: Path | str | sqlite3.Connection,
    symbol: str,
    *,
    get: GetFn | None = None,
    since: str = "2024-04-01",
) -> dict[str, Any]:
    """Discover a company's website from held doc page-1 text, crawl investor pages, and validate call PDFs."""
    get_fn = get or default_get
    sym_u = symbol.strip().upper()
    conn, should_close = _open_ro(store_db)
    try:
        website = _detect_website(conn, sym_u)
        if not website:
            return {"website": None, "pages_crawled": 0, "pdfs_seen": 0, "undated_skipped": 0,
                    "items": [], "verdict": "no_website"}
        held_shas = {str(sha).lower() for (sha,) in conn.execute("SELECT sha256 FROM doc WHERE sha256 IS NOT NULL")}
        meta = _company_meta(conn)
        info = meta.get(sym_u, {"isin": None, "bse_code": None, "names": [sym_u]})
    finally:
        if should_close:
            conn.close()

    home_got, _home_err = _safe_fetch(get_fn, website)
    if home_got is None or not _is_html(home_got[1], home_got[2]):
        return {"website": website, "pages_crawled": 0, "pdfs_seen": 0, "undated_skipped": 0,
                "items": [], "verdict": "site_unreachable"}

    home_url = home_got[0]
    visited: set[str] = {website, home_url}
    queue: list[tuple[str, int]] = []
    pdfs_seen: dict[str, str] = {}
    pages_crawled = 1

    def _enqueue_from_html(page_url: str, html_bytes: bytes, depth: int) -> None:
        html = html_bytes.decode("utf-8", errors="replace")
        queued_here = 0
        for href, anchor_text in _extract_html_links(html, page_url):
            if _is_pdf_url(href):
                pdfs_seen.setdefault(href, anchor_text)
                continue
            if depth >= SITE_MAX_DEPTH or queued_here >= SITE_MAX_LINKS_PER_PAGE:
                continue
            if href in visited or not _same_domain(href, home_url):
                continue
            if _NAV_LINK_RE.search(f"{href} {anchor_text}"):
                visited.add(href)
                queue.append((href, depth + 1))
                queued_here += 1

    _enqueue_from_html(home_url, home_got[2], 0)
    idx = 0
    while idx < len(queue) and pages_crawled < SITE_MAX_PAGES:
        next_url, depth = queue[idx]
        idx += 1
        got, _err = _safe_fetch(get_fn, next_url)
        if got is None or not _is_html(got[1], got[2]):
            continue
        pages_crawled += 1
        _enqueue_from_html(got[0], got[2], depth)

    undated_skipped = 0
    items: list[dict[str, Any]] = []
    for pdf_url, anchor_text in pdfs_seen.items():
        intent = _site_link_intent(pdf_url, anchor_text)
        if intent is None:
            continue
        link_date = _site_link_date(pdf_url, anchor_text)
        if not link_date:
            undated_skipped += 1
            continue
        if link_date < since:
            continue

        res = resolve(pdf_url, intent, link_date, info["names"], get=get_fn)
        if res["status"] != "resolved":
            fid = hashlib.sha256(pdf_url.encode("utf-8")).hexdigest()[:16]
            items.append({
                **_base_item(
                    exchange="SITE",
                    filing_id=fid,
                    symbol=sym_u,
                    isin=info["isin"],
                    bse_code=info["bse_code"],
                    filed_at=None,
                    source="company_site",
                    intent=intent,
                    target=pdf_url,
                ),
                "outcome": "failed",
                "reason": res["reason"],
            })
            continue

        sha = linked_transcripts._sha256(res["data"])
        outcome = "held" if sha in held_shas else "resolved"
        item = {
            **_base_item(
                exchange="SITE",
                filing_id=sha[:16],
                symbol=sym_u,
                isin=info["isin"],
                bse_code=info["bse_code"],
                filed_at=None,
                source="company_site",
                intent=intent,
                target=pdf_url,
            ),
            "kind": res["kind"],
            "outcome": outcome,
            "pages": res["pages"],
            "sha256": sha,
            "url": res["url"],
        }
        if outcome == "resolved":
            item["data"] = res["data"]
            item["texts"] = res["texts"]
        items.append(item)

    has_docs = any(it["outcome"] in ("resolved", "held") for it in items)
    verdict = "found" if has_docs else "no_call_documents_on_site"
    return {
        "website": website,
        "pages_crawled": pages_crawled,
        "pdfs_seen": len(pdfs_seen),
        "undated_skipped": undated_skipped,
        "items": items,
        "verdict": verdict,
    }


# --------------------------------------------------------------------------- CLI & report
def _resolve_store_db(store_dir: Path) -> Path:
    for prof in sorted(store_dir.glob("*_profile.json")):
        name = prof.name[: -len("_profile.json")]
        cand = prof.with_name(f"{name}.db")
        if cand.is_file():
            return cand
    for cand_name in (f"{store_dir.name}.db", "pilot3.db", "store.db"):
        cand = store_dir / cand_name
        if cand.is_file():
            return cand
    dbs = [p for p in sorted(store_dir.glob("*.db")) if p.name != "pages.db" and "before" not in p.name]
    if len(dbs) == 1:
        return dbs[0]
    raise FileNotFoundError(f"Could not find store database in {store_dir}")


def format_report(
    items: list[dict[str, Any]],
    site_results: dict[str, dict[str, Any]] | None = None,
    symbols: Iterable[str] | None = None,
) -> str:
    """Format a per-symbol summary table of planned/applied link-follow and site-finder items."""
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for sym in symbols or ():
        by_sym.setdefault(sym, [])
    for item in items:
        by_sym.setdefault(str(item["symbol"]), []).append(item)
    for sym in site_results or ():
        by_sym.setdefault(sym, [])

    lines = [
        "| symbol | link_only | resolved | held | audio_only | invitation | failed | exch_resolved | site_verdict | site_docs |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for sym in sorted(by_sym):
        mine = by_sym[sym]
        links = [i for i in mine if i.get("source") == "link_follow"]
        exch = [i for i in mine if i.get("source") == "exchange"]
        site_items = [i for i in mine if i.get("source") == "company_site"]
        c = Counter(str(i.get("outcome") or "") for i in links)
        failed_reasons = Counter(str(i.get("reason") or "unknown") for i in mine if i.get("outcome") == "failed")
        fail_str = (
            f"{sum(failed_reasons.values())} ({','.join(f'{k}:{v}' for k, v in sorted(failed_reasons.items()))})"
            if failed_reasons
            else "0"
        )
        exch_res = sum(1 for i in exch if i.get("outcome") == "resolved")
        site_info = (site_results or {}).get(sym)
        site_verdict = str(site_info["verdict"]) if site_info else "-"
        site_docs = sum(1 for i in site_items if i.get("outcome") in ("resolved", "held")) if site_info else 0
        lines.append(
            f"| {sym} | {len(links)} | {c['resolved']} | {c['held']} | {c['audio_only']} | "
            f"{c['invitation']} | {fail_str} | {exch_res} | {site_verdict} | {site_docs} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--store-dir", required=True, help="store folder holding <store>.db and raw/manifest.csv")
    parser.add_argument("--plan-only", action="store_true", help="plan only; do not write PDFs or manifest.csv")
    parser.add_argument("--site", action="store_true", help="also crawl each symbol's company website")
    parser.add_argument("--symbols", default="", help="comma-separated symbols (default: all)")
    parser.add_argument("--json", default="", help="write plan items (without data/texts) to JSON")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT), help="raw root for resolved PDFs")
    args = parser.parse_args(argv)

    store_dir = Path(args.store_dir)
    store_db = _resolve_store_db(store_dir)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or None

    items = plan_store(store_db, symbols=symbols)
    site_results: dict[str, dict[str, Any]] = {}
    if args.site:
        if symbols is None:
            conn, _ = _open_ro(store_db)
            try:
                syms = [str(r[0]).strip().upper() for r in conn.execute("SELECT DISTINCT symbol FROM company ORDER BY symbol") if r[0]]
            finally:
                conn.close()
        else:
            syms = symbols
        for sym in syms:
            res = find_site_docs(store_db, sym)
            site_results[sym] = res
            items.extend(res["items"])

    if not args.plan_only:
        apply_plan(store_dir, items, raw_root=Path(args.raw_root))

    print(format_report(items, site_results if args.site else None, symbols=symbols))
    if args.json:
        payload = [{k: v for k, v in item.items() if k not in ("data", "texts")} for item in items]
        Path(args.json).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
