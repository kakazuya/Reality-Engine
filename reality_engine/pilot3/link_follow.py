"""T-223 (R-012/R-014): turn a store's ``filing`` rows into fetch targets for missing documents.

Reads ``filing`` (``link_only`` cover letters and ``not_fetched`` transcripts/decks/results/annual reports),
``doc`` and ``doc_page`` through a read-only connection, classifies cover letters, resolves PDFs or investor-page
links through an injectable HTTP fetcher, and emits new documents only via ``<store_dir>/raw/manifest.csv``
(never writing the store SQLite database directly).

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
    "held_doc_key",
    "printed_company",
    "parent_company",
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
_TX_INVITE_EXTRA_RE = re.compile(
    r"\b(?:pleased\s+to\s+invite|registration\s+link|diamond\s*pass|dial[- ]?in|universal\s+access)\b",
    re.I,
)
_FUTURE_TRANSCRIPT_RE = re.compile(r"\btranscripts?\b[^.\n]{0,40}\bwill\s+be\b", re.I)
_TRANSCRIPT_WORD_RE = re.compile(r"\btranscripts?\b", re.I)
_DECK_TEXT_RE = re.compile(r"\b(?:investor\s+presentation|earnings\s+presentation|presentation)\b", re.I)
_NOTICE_SKIP_RE = re.compile(
    r"newspaper|publication|advertis|corrigendum|reasons?\s+for\s+delay|non[- ]?submission|"
    r"intimation\s+of\s+board\s+meeting|trading\s+window",
    re.I,
)
_RESULTS_TEXT_RE = re.compile(
    r"\b(?:statement\s+of\s+(?:un)?audited|financial\s+results|results\s+for\s+the\s+quarter)\b",
    re.I,
)
_AR_TEXT_RE = re.compile(
    r"\b(?:annual\s+report|directors['’]?\s*report|board['’]?s\s+report)\b",
    re.I,
)
_COMPANY_SUFFIX_RE = re.compile(r"\b(?:Limited|Ltd)\b(?!\s+Review\b)", re.I)
_PUBLIC_HOLDER_RE = re.compile(r"\b(?:limited|ltd)\b", re.I)
_PRIVATE_HOLDER_RE = re.compile(r"\b(?:private|pvt)\b", re.I)
_GROUP_TOKEN_STOP = frozenset({"THE", "SHRI", "SMT", "MR", "MRS", "M/S"})
_MARKET_BODY_RE = re.compile(
    r"\b(?:BSE|National\s+Stock\s+Exchange|Stock\s+Exchange|Metropolitan\s+Stock|MSEI|NSDL|CDSL|"
    r"Central\s+Depository|National\s+Securities\s+Depository|Link\s+Intime|KFin|Kfintech|Bigshare|"
    r"Registrar|SEBI|Securities\s+and\s+Exchange\s+Board|CRISIL|ICRA|CARE\s+Ratings|India\s+Ratings|"
    r"Acuite|Brickwork|Infomerics)\b",
    re.I,
)

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
_QTAG_RE = re.compile(
    r"(?<!\d)q([1-4])[-_\s]*(?:(?:&|and)[-_\s]*)?fy[-_\s]*(?:20)?(\d{2})(?:[-–/](?:20)?(\d{2}))?(?![a-z0-9])",
    re.I,
)
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


_BROWSER_HEADERS: dict[str, str] = {
    **DEFAULT_HEADERS,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "text/html,application/pdf,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
}


# --------------------------------------------------------------------------- HTTP
def default_get(url: str, *, attempts: int = 3, backoff: float = 2.0, sleep=time.sleep) -> tuple[str, str, bytes]:
    """Polite HTTP GET using ``linked_transcripts`` per-host pacing, 60 s timeout, max 40 MB."""
    import requests

    host = (urlparse(url).netloc or "").lower()
    session = requests.Session()
    headers = dict(DEFAULT_HEADERS)
    retried_403 = False
    try:
        attempt = 0
        while attempt < attempts:
            attempt += 1
            gap = linked_transcripts.LAST_REQUEST.get(host, 0.0) + linked_transcripts.MIN_INTERVAL_S - time.monotonic()
            if gap > 0:
                sleep(gap)
            linked_transcripts.LAST_REQUEST[host] = time.monotonic()
            try:
                resp = session.get(
                    url,
                    headers=headers,
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
                if resp.status_code == 403 and not retried_403:
                    retried_403 = True
                    headers = dict(_BROWSER_HEADERS)
                    attempt -= 1
                    continue
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


def _match_to_qtag(m: re.Match[str]) -> str:
    q_num, y1, y2 = m.group(1), m.group(2), m.group(3)
    fy = y2 if (y2 is not None and int(y2) == (int(y1) + 1) % 100) else y1
    return f"Q{q_num}FY{fy}"


def parse_quarter_tag(text: str) -> str | None:
    """Parse ``Q1 FY 2026-27`` / ``Q2 FY25`` style quarter tags into ``Q1FY27``."""
    m = _QTAG_RE.search(text or "")
    return _match_to_qtag(m) if m else None


def _quarter_matches_text(text: str, tag: str) -> bool:
    if not tag or "FY" not in tag:
        return False
    want = tag.upper()
    return any(_match_to_qtag(m) == want for m in _QTAG_RE.finditer(text or ""))


def _intent_matches(text: str, intent: str) -> bool:
    if intent == "transcript":
        return bool(_TX_LINK_RE.search(text))
    if intent == "deck":
        return bool(_DECK_LINK_RE.search(text))
    if intent == "unknown":
        return bool(_TX_LINK_RE.search(text) or _DECK_LINK_RE.search(text))
    return False


def _score_pdf_link(
    href: str,
    anchor_text: str,
    intent: str,
    anchor_date: str | None,
    page_url: str = "",
) -> int:
    combined = f"{href} {anchor_text}"
    score = 0
    if _intent_matches(combined, intent) or (page_url and _intent_matches(page_url, intent)):
        score += 3

    if anchor_date:
        try:
            anchor_dt = date.fromisoformat(anchor_date[:10])
        except ValueError:
            anchor_dt = None
        if anchor_dt is not None:
            if any(-45 <= (dt - anchor_dt).days <= 10 for dt in _dates_from_text(combined)):
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


def _distinctive_name_tokens(company_names: Iterable[str] | str | None) -> list[str]:
    if company_names is None:
        return []
    items = [company_names] if isinstance(company_names, str) else list(company_names)
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in items:
        s = str(raw or "").strip()
        if not s:
            continue
        if " " not in s and s.isupper() and s.isalnum() and 2 <= len(s) <= 16:
            continue
        for word in re.findall(r"[A-Za-z0-9]{4,}", s):
            lw = word.lower()
            if lw in COMPANY_STOPWORDS or lw in seen:
                continue
            seen.add(lw)
            tokens.append(lw)
    return tokens


def _page1_company_names(page1: str) -> list[str]:
    names: list[str] = []
    for line in (page1 or "").splitlines():
        pos = 0
        for m in _COMPANY_SUFFIX_RE.finditer(line):
            prefix = line[pos : m.start()].strip(" ,.;:|/-")
            pos = m.end()
            words = prefix.split()[-6:]
            if not words or not any(re.search(r"[A-Za-z0-9]", w) for w in words):
                continue
            cand = f"{' '.join(words)} {m.group(0)}"
            if _MARKET_BODY_RE.search(cand):
                continue
            names.append(cand)
    return names


def _group_company_mismatch(page1: str, company_names: Iterable[str] | str | None) -> str | None:
    printed_names = _page1_company_names(page1)
    if not printed_names:
        return None
    distinctive = _distinctive_name_tokens(company_names)
    if not distinctive:
        return None
    for name in printed_names:
        if all(re.search(rf"\b{re.escape(tok)}\b", name, re.I) for tok in distinctive):
            return None
    return printed_names[0]


def _printed_company_line(page1: str) -> str | None:
    for line in (page1 or "").splitlines():
        clean = " ".join(line.split())
        if clean and re.search(r"\b(?:limited|ltd)\b", clean, re.I):
            return clean[:120]
    return None


def _has_tx_invite_wording(first2: str) -> bool:
    return bool(_INVITE_TEXT_RE.search(first2) or _TX_INVITE_EXTRA_RE.search(first2))


def _is_transcript_candidate(pages: int, first2: str, first3: str) -> bool:
    if doc_identity.moderator_line(first3):
        return True
    if pages >= 5 and (_TRANSCRIPT_WORD_RE.search(first3) or doc_identity.moderator_line(first3)):
        return not _has_tx_invite_wording(first2)
    return False


def _check_candidate(
    url: str,
    data: bytes,
    texts: list[str],
    intent: str,
    anchor_date: str | None,
    company_names: Iterable[str] | str | None,
    *,
    check_company: bool = True,
    parent_names: Iterable[str] | str | None = None,
) -> dict[str, Any]:
    pages = len(texts)
    min_pages = {"deck": 5, "results": 2, "annual_report": 40}.get(intent, 3)
    if pages < min_pages:
        return {"status": "failed", "reason": "too_short"}

    first2 = "\n".join(texts[:2])
    if len(first2.strip()) < 50:
        return {"status": "failed", "reason": "needs_ocr"}

    first3 = "\n".join(texts[:3])
    is_tx = _is_transcript_candidate(pages, first2, first3)
    is_strict_tx = bool(doc_identity.moderator_line(first3) or _TRANSCRIPT_WORD_RE.search(first3))

    if intent == "transcript":
        if not is_tx:
            return {"status": "failed", "reason": "not_transcript"}
        kind = "transcript"
    elif intent == "deck":
        if is_strict_tx:
            return {"status": "failed", "reason": "not_transcript"}
        kind = "deck"
    elif intent == "results":
        first4 = "\n".join(texts[:4])
        if not _RESULTS_TEXT_RE.search(first4):
            return {"status": "failed", "reason": "not_results"}
        kind = "results"
    elif intent == "annual_report":
        first10 = "\n".join(texts[:10])
        if not _AR_TEXT_RE.search(first10):
            return {"status": "failed", "reason": "not_annual_report"}
        kind = "annual_report"
    else:
        kind = "transcript" if is_tx else "deck"
        if kind == "deck" and pages < 5:
            return {"status": "failed", "reason": "too_short"}

    parent_company: str | None = None
    if check_company:
        page1 = texts[0] if texts else ""
        own_fail: dict[str, Any] | None = None
        if not _check_company(first2, company_names):
            own_fail = {
                "status": "failed",
                "reason": "other_company",
                "printed_company": _printed_company_line(page1),
            }
        else:
            mismatch_co = _group_company_mismatch(page1, company_names)
            if mismatch_co is not None:
                own_fail = {
                    "status": "failed",
                    "reason": "other_company",
                    "printed_company": mismatch_co,
                }
        if own_fail is not None:
            parent_list = (
                [parent_names.strip()]
                if isinstance(parent_names, str)
                else [str(p).strip() for p in (parent_names or ()) if str(p).strip()]
            )
            if kind == "transcript" and parent_list:
                for p in parent_list:
                    if _check_company(first2, [p]) and _group_company_mismatch(page1, [p]) is None:
                        parent_company = p
                        break
                if parent_company is None:
                    return own_fail
            else:
                return own_fail

    if anchor_date and kind in ("transcript", "deck"):
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

    out: dict[str, Any] = {
        "status": "resolved",
        "url": url,
        "data": data,
        "pages": pages,
        "texts": texts,
        "kind": kind,
    }
    if parent_company is not None:
        out["parent_company"] = parent_company
    return out


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
    *,
    check_company: bool = True,
    parent_names: Iterable[str] | str | None = None,
) -> dict[str, Any]:
    try:
        texts, uris = linked_transcripts.pdf_info(data)
    except Exception:  # noqa: BLE001 - broken PDF
        return {"status": "failed", "reason": "not_pdf"}

    direct: dict[str, Any] | None = None
    if intent == "results" and len(texts) == 2:
        direct = _check_candidate(
            url, data, texts, intent, anchor_date, company_names, check_company=check_company, parent_names=parent_names
        )
        if direct["status"] == "resolved":
            return direct

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
            res = _check_candidate(
                nxt_url,
                nxt_data,
                nxt_texts,
                intent,
                anchor_date,
                company_names,
                check_company=check_company,
                parent_names=parent_names,
            )
            if res["status"] == "resolved":
                return res
            last_err = res
        if direct is not None and last_err is None:
            return direct
        return last_err if last_err and last_err["reason"] != "too_short" else {"status": "failed", "reason": "too_short"}

    return _check_candidate(
        url, data, texts, intent, anchor_date, company_names, check_company=check_company, parent_names=parent_names
    )


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
    check_company: bool = True,
    parent_names: Iterable[str] | str | None = None,
) -> dict[str, Any]:
    """Fetch ``target`` (PDF, 1-2 page PDF cover, or HTML investor page) and validate the candidate document."""
    get_fn = get or default_get
    got, err = _safe_fetch(get_fn, target)
    if got is None:
        return {"status": "failed", "reason": err}
    final_url, ctype, data = got
    if data[:5] == b"%PDF-":
        return _validate_pdf_bytes(
            final_url,
            data,
            intent,
            anchor_date,
            company_names,
            get_fn,
            check_company=check_company,
            parent_names=parent_names,
        )
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
        sc = _score_pdf_link(href, anchor_text, intent, anchor_date, page_url=final_url)
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
        res = _validate_pdf_bytes(
            c_url,
            c_data,
            intent,
            anchor_date,
            company_names,
            get_fn,
            check_company=check_company,
            parent_names=parent_names,
        )
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


def _holder_first_word(name: str) -> str:
    parts = name.split()
    return parts[0].strip(".,;:").upper() if parts else ""


def _parent_names(
    conn: sqlite3.Connection,
    symbol: str,
    own_names: Iterable[str] | str | None,
) -> list[str]:
    has_shp = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shp_holder'"
    ).fetchone()
    if not has_shp:
        return []
    sym_u = str(symbol or "").strip().upper()
    qrow = conn.execute(
        "SELECT MAX(quarter_end) FROM shp_holder WHERE symbol=? AND quarter_end IS NOT NULL",
        (sym_u,),
    ).fetchone()
    if not qrow or not qrow[0]:
        return []
    rows = conn.execute(
        "SELECT holder_name, pct FROM shp_holder WHERE symbol=? AND quarter_end=? ORDER BY rowid",
        (sym_u, str(qrow[0])),
    ).fetchall()

    parsed: list[tuple[str, float]] = []
    group_tokens: set[str] = set()
    for raw_name, raw_pct in rows:
        name = " ".join(str(raw_name or "").split())
        if not name:
            continue
        try:
            pct = float(raw_pct) if raw_pct is not None else 0.0
        except (TypeError, ValueError):
            pct = 0.0
        parsed.append((name, pct))
        if pct >= 50.0:
            tok = _holder_first_word(name)
            if len(tok) >= 3 and tok not in _GROUP_TOKEN_STOP:
                group_tokens.add(tok)

    own_tokens = set(_distinctive_name_tokens(own_names))
    parents: list[str] = []
    seen: set[str] = set()
    for name, pct in parsed:
        if not _PUBLIC_HOLDER_RE.search(name) or _PRIVATE_HOLDER_RE.search(name):
            continue
        if pct < 50.0 and _holder_first_word(name) not in group_tokens:
            continue
        if own_tokens:
            cand_tokens = set(_distinctive_name_tokens(name))
            if own_tokens.issubset(cand_tokens):
                continue
        key = name.lower()
        if key not in seen:
            seen.add(key)
            parents.append(name)
    return parents


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
        entry = meta.setdefault(
            sym_u,
            {"isin": isin, "bse_code": str(bse_code) if bse_code else None, "names": [sym_u], "parents": []},
        )
        if isin and not entry["isin"]:
            entry["isin"] = isin
        if bse_code and not entry["bse_code"]:
            entry["bse_code"] = str(bse_code)
        if name and str(name).strip() and str(name).strip() not in entry["names"]:
            entry["names"].append(str(name).strip())
    for sym_u, entry in meta.items():
        entry["parents"] = _parent_names(conn, sym_u, entry["names"])
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
        "kind": intent if intent in ("transcript", "deck", "results", "annual_report") else None,
        "target": target,
        "outcome": None,
        "reason": "",
        "held_doc_key": None,
        "printed_company": None,
        "parent_company": None,
        "pages": 0,
        "sha256": None,
        "url": None,
    }


def _parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _load_held_call_index(
    conn: sqlite3.Connection,
) -> tuple[dict[str, list[tuple[str, list[date]]]], dict[str, list[tuple[str, date]]]]:
    """Load held transcript call/filing dates and deck filing dates once per store."""
    tx_pages: dict[tuple[str, str], tuple[str | None, str | None, list[str]]] = {}
    for sym, dk, fd, ka, text in conn.execute(
        "SELECT d.symbol, d.doc_key, d.filing_date, d.known_at, dp.text "
        "FROM doc d "
        "LEFT JOIN doc_page dp ON dp.doc_key = d.doc_key AND dp.page <= ? "
        "WHERE d.doc_type = 'transcript' AND d.pages >= 3 "
        "ORDER BY d.symbol, d.doc_key, dp.page",
        (call_dates.PAGES,),
    ):
        sym_u = str(sym or "").strip().upper()
        key = (sym_u, str(dk))
        if key not in tx_pages:
            tx_pages[key] = (fd, ka, [])
        if text:
            tx_pages[key][2].append(str(text))

    held_tx: dict[str, list[tuple[str, list[date]]]] = {}
    for (sym_u, dk), (fd, ka, texts) in tx_pages.items():
        dates_list: list[date] = []
        if texts:
            printed = _parse_iso_date(call_dates.call_date(texts))
            if printed is not None:
                dates_list.append(printed)
        f_dt = _parse_iso_date(fd or ka)
        if f_dt is not None and f_dt not in dates_list:
            dates_list.append(f_dt)
        if dates_list:
            held_tx.setdefault(sym_u, []).append((dk, dates_list))

    held_decks: dict[str, list[tuple[str, date]]] = {}
    for sym, dk, fd, ka in conn.execute(
        "SELECT symbol, doc_key, filing_date, known_at "
        "FROM doc WHERE doc_type = 'deck' ORDER BY symbol, doc_key"
    ):
        sym_u = str(sym or "").strip().upper()
        f_dt = _parse_iso_date(fd or ka)
        if f_dt is not None:
            held_decks.setdefault(sym_u, []).append((str(dk), f_dt))

    return held_tx, held_decks


def _load_held_doc_dates(
    conn: sqlite3.Connection, doc_types: tuple[str, ...]
) -> dict[str, dict[str, list[tuple[str, date]]]]:
    out: dict[str, dict[str, list[tuple[str, date]]]] = {dt: {} for dt in doc_types}
    placeholders = ",".join("?" for _ in doc_types)
    for sym, dk, dtype, fd, ka in conn.execute(
        f"SELECT symbol, doc_key, doc_type, filing_date, known_at "
        f"FROM doc WHERE doc_type IN ({placeholders}) ORDER BY symbol, doc_key",
        doc_types,
    ):
        sym_u = str(sym or "").strip().upper()
        f_dt = _parse_iso_date(fd or ka)
        if f_dt is not None:
            out.setdefault(str(dtype), {}).setdefault(sym_u, []).append((str(dk), f_dt))
    return out


def _held_same_day_doc(
    symbol: str,
    kind: str,
    filed_at: str | None,
    held_by_type: dict[str, dict[str, list[tuple[str, date]]]],
) -> str | None:
    filed_dt = _parse_iso_date(filed_at)
    if filed_dt is None:
        return None
    window = 2 if kind == "results" else 120
    for dk, hd in held_by_type.get(kind, {}).get(symbol, ()):
        if abs((filed_dt - hd).days) <= window:
            return dk
    return None


def _check_same_call_or_dup(
    symbol: str,
    kind: str,
    texts: list[str],
    anchor_date: str | None,
    held_tx: dict[str, list[tuple[str, list[date]]]],
    held_decks: dict[str, list[tuple[str, date]]],
    planned_calls: dict[tuple[str, str], list[date]],
) -> tuple[str, str | None]:
    if kind == "transcript":
        cand_call_dt = _parse_iso_date(call_dates.call_date(texts))
        if cand_call_dt is not None:
            for dk, dts in held_tx.get(symbol, ()):
                if any(abs((cand_call_dt - hd).days) <= 7 for hd in dts):
                    return "held_same_call", dk
        plan_dt = cand_call_dt or _parse_iso_date(anchor_date)
        dup_window = 7
    elif kind == "deck":
        cand_anchor_dt = _parse_iso_date(anchor_date)
        if cand_anchor_dt is not None:
            for dk, hd in held_decks.get(symbol, ()):
                if abs((cand_anchor_dt - hd).days) <= 10:
                    return "held_same_call", dk
        plan_dt = cand_anchor_dt
        dup_window = 7
    else:
        plan_dt = _parse_iso_date(anchor_date)
        dup_window = 2 if kind == "results" else 120

    if plan_dt is not None:
        existing = planned_calls.get((symbol, kind), [])
        if any(abs((plan_dt - pd).days) <= dup_window for pd in existing):
            return "dup_in_plan", None
        planned_calls.setdefault((symbol, kind), []).append(plan_dt)
    return "resolved", None


def _resolve_target_to_item(
    item: dict[str, Any],
    target: str,
    intent: str,
    anchor_date: str | None,
    company_names: list[str],
    held_shas: set[str],
    held_tx: dict[str, list[tuple[str, list[date]]]],
    held_decks: dict[str, list[tuple[str, date]]],
    planned_calls: dict[tuple[str, str], list[date]],
    get_fn: GetFn,
    parent_names: list[str] | None = None,
) -> dict[str, Any]:
    check_co = item.get("source") != "exchange"
    res = resolve(
        target,
        intent,
        anchor_date,
        company_names,
        get=get_fn,
        check_company=check_co,
        parent_names=parent_names,
    )
    if res["status"] != "resolved":
        return {
            **item,
            "target": target,
            "outcome": "failed",
            "reason": res["reason"],
            "printed_company": res.get("printed_company"),
        }
    sha = linked_transcripts._sha256(res["data"])
    if sha in held_shas:
        return {
            **item,
            "target": target,
            "kind": res["kind"],
            "outcome": "held",
            "parent_company": res.get("parent_company"),
            "pages": res["pages"],
            "sha256": sha,
            "url": res["url"],
        }
    outcome, held_doc_key = _check_same_call_or_dup(
        str(item["symbol"]),
        str(res["kind"]),
        res["texts"],
        anchor_date,
        held_tx,
        held_decks,
        planned_calls,
    )
    out: dict[str, Any] = {
        **item,
        "target": target,
        "kind": res["kind"],
        "outcome": outcome,
        "held_doc_key": held_doc_key,
        "parent_company": res.get("parent_company"),
        "pages": res["pages"],
        "sha256": sha,
        "url": res["url"],
    }
    if outcome == "resolved":
        out["data"] = res["data"]
        out["texts"] = res["texts"]
    return out


def plan_store(
    store_db: Path | str | sqlite3.Connection,
    *,
    get: GetFn | None = None,
    symbols: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Build fetch plan items for ``link_only`` and ``not_fetched`` (transcript/deck/results/annual_report) rows."""
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
        held_tx, held_decks = _load_held_call_index(conn)
        held_res_ar = _load_held_doc_dates(conn, ("results", "annual_report"))
        meta = _company_meta(conn)

        link_rows = conn.execute(
            "SELECT exchange, filing_id, symbol, isin, filed_at, held_doc_key, link_urls "
            "FROM filing WHERE status='link_only' "
            "ORDER BY symbol, COALESCE(filed_at, ''), exchange, filing_id"
        ).fetchall()
        nf_rows = conn.execute(
            "SELECT exchange, filing_id, symbol, isin, filed_at, kind_hint, attachment, "
            "exchange_subcategory, headline "
            "FROM filing WHERE status='not_fetched' "
            "AND (kind_hint IN ('transcript', 'deck') "
            "OR (kind_hint IN ('results', 'annual_report') AND substr(COALESCE(filed_at, ''), 1, 10) >= '2024-04-01')) "
            "AND attachment IS NOT NULL AND attachment != '' "
            "ORDER BY symbol, COALESCE(filed_at, ''), exchange, filing_id"
        ).fetchall()

        plan: list[dict[str, Any]] = []
        seen_targets: set[tuple[str, str]] = set()
        planned_calls: dict[tuple[str, str], list[date]] = {}

        for exchange, filing_id, symbol, isin, filed_at, held_doc_key, link_urls_json in link_rows:
            sym_u = str(symbol or "").strip().upper()
            if wanted is not None and sym_u not in wanted:
                continue
            info = meta.get(sym_u, {"isin": None, "bse_code": None, "names": [sym_u], "parents": []})
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
                    base,
                    t,
                    intent,
                    anchor,
                    info["names"],
                    held_shas,
                    held_tx,
                    held_decks,
                    planned_calls,
                    get_fn,
                    parent_names=info.get("parents"),
                )
                if attempt["outcome"] in ("resolved", "held", "held_same_call", "dup_in_plan"):
                    chosen = attempt
                    break
                if chosen is None:
                    chosen = attempt
            if chosen is not None:
                plan.append(chosen)

        for exchange, filing_id, symbol, isin, filed_at, kind_hint, attachment, subcat, headline in nf_rows:
            sym_u = str(symbol or "").strip().upper()
            if wanted is not None and sym_u not in wanted:
                continue
            target = _exchange_target_url(str(exchange), attachment)
            if not target:
                continue
            info = meta.get(sym_u, {"isin": None, "bse_code": None, "names": [sym_u], "parents": []})
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
            if intent in ("results", "annual_report"):
                if _NOTICE_SKIP_RE.search(f"{subcat or ''} {headline or ''}"):
                    plan.append({**base, "outcome": "skipped_notice"})
                    continue
                held_dk = _held_same_day_doc(sym_u, intent, filed_at, held_res_ar)
                if held_dk is not None:
                    plan.append({**base, "outcome": "held_same_day", "held_doc_key": held_dk})
                    continue
            if (sym_u, target) in seen_targets:
                continue
            seen_targets.add((sym_u, target))
            anchor = str(filed_at)[:10] if filed_at else None
            plan.append(
                _resolve_target_to_item(
                    base,
                    target,
                    intent,
                    anchor,
                    info["names"],
                    held_shas,
                    held_tx,
                    held_decks,
                    planned_calls,
                    get_fn,
                    parent_names=info.get("parents"),
                )
            )

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


_KIND_BUCKET_SUBCAT: dict[str, tuple[str, str]] = {
    "transcript": ("concall_transcript", "Earnings Call Transcript"),
    "deck": ("investor_presentation", "Investor Presentation"),
    "results": ("quarterly_results", "Financial Results"),
    "annual_report": ("annual_report", "Annual Report"),
}


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
        bucket, subcat = _KIND_BUCKET_SUBCAT.get(kind, ("concall_transcript", "Earnings Call Transcript"))
        label = linked_transcripts.call_label(url, subcat)
        parent_co = str(item.get("parent_company") or "").strip()
        if parent_co:
            headline = f"{label} - parent company call: {parent_co} (linked from {exchange} filing {filing_id})"
        else:
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
    tag = parse_quarter_tag(combined)
    if tag:
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


def _missing_site_kinds(conn: sqlite3.Connection, symbol: str, since: str) -> set[str]:
    has_tx = conn.execute(
        "SELECT 1 FROM doc WHERE symbol=? AND doc_type='transcript' AND pages>=3 "
        "AND substr(COALESCE(NULLIF(filing_date, ''), known_at, ''), 1, 10) >= ? LIMIT 1",
        (symbol, since),
    ).fetchone()
    has_deck = conn.execute(
        "SELECT 1 FROM doc WHERE symbol=? AND doc_type='deck' "
        "AND substr(COALESCE(NULLIF(filing_date, ''), known_at, ''), 1, 10) >= ? LIMIT 1",
        (symbol, since),
    ).fetchone()
    missing: set[str] = set()
    if not has_tx:
        missing.add("transcript")
    if not has_deck:
        missing.add("deck")
    return missing


def find_site_docs(
    store_db: Path | str | sqlite3.Connection,
    symbol: str,
    *,
    get: GetFn | None = None,
    since: str = "2024-04-01",
    kinds: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Discover a company's website from held doc page-1 text, crawl investor pages, and validate call PDFs."""
    get_fn = get or default_get
    sym_u = symbol.strip().upper()
    conn, should_close = _open_ro(store_db)
    try:
        if kinds is None:
            wanted_kinds = _missing_site_kinds(conn, sym_u, since)
        else:
            wanted_kinds = {str(k).strip().lower() for k in kinds if k}
        if not wanted_kinds:
            return {"website": None, "pages_crawled": 0, "pdfs_seen": 0, "undated_skipped": 0,
                    "items": [], "verdict": "not_needed"}
        website = _detect_website(conn, sym_u)
        if not website:
            return {"website": None, "pages_crawled": 0, "pdfs_seen": 0, "undated_skipped": 0,
                    "items": [], "verdict": "no_website"}
        held_shas = {str(sha).lower() for (sha,) in conn.execute("SELECT sha256 FROM doc WHERE sha256 IS NOT NULL")}
        held_tx, held_decks = _load_held_call_index(conn)
        meta = _company_meta(conn)
        info = meta.get(sym_u, {"isin": None, "bse_code": None, "names": [sym_u], "parents": []})
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
    planned_calls: dict[tuple[str, str], list[date]] = {}
    for pdf_url, anchor_text in pdfs_seen.items():
        intent = _site_link_intent(pdf_url, anchor_text)
        if intent is None or intent not in wanted_kinds:
            continue
        link_date = _site_link_date(pdf_url, anchor_text)
        if not link_date:
            undated_skipped += 1
            continue
        if link_date < since:
            continue

        res = resolve(pdf_url, intent, link_date, info["names"], get=get_fn, parent_names=info.get("parents"))
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
                "printed_company": res.get("printed_company"),
            })
            continue

        sha = linked_transcripts._sha256(res["data"])
        if sha in held_shas:
            items.append({
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
                "outcome": "held",
                "parent_company": res.get("parent_company"),
                "pages": res["pages"],
                "sha256": sha,
                "url": res["url"],
            })
            continue

        outcome, held_doc_key = _check_same_call_or_dup(
            sym_u,
            str(res["kind"]),
            res["texts"],
            link_date,
            held_tx,
            held_decks,
            planned_calls,
        )
        item: dict[str, Any] = {
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
            "held_doc_key": held_doc_key,
            "parent_company": res.get("parent_company"),
            "pages": res["pages"],
            "sha256": sha,
            "url": res["url"],
        }
        if outcome == "resolved":
            item["data"] = res["data"]
            item["texts"] = res["texts"]
        items.append(item)

    has_docs = any(it["outcome"] in ("resolved", "held", "held_same_call") for it in items)
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


def _dedupe_combined_plan(items: list[dict[str, Any]]) -> None:
    """Mark duplicate resolved calls across ``plan_store`` + ``find_site_docs`` in one run as ``dup_in_plan``."""
    seen: dict[tuple[str, str], list[date]] = {}
    for item in items:
        if item.get("outcome") != "resolved":
            continue
        sym = str(item.get("symbol") or "")
        kind = str(item.get("kind") or item.get("intent") or "")
        texts = item.get("texts") or []
        dt = _parse_iso_date(call_dates.call_date(texts)) if kind == "transcript" and texts else None
        if dt is None:
            dt = _parse_iso_date(item.get("filed_at") or _site_link_date(str(item.get("target") or ""), ""))
        if dt is None:
            continue
        existing = seen.get((sym, kind), [])
        if any(abs((dt - pd).days) <= 7 for pd in existing):
            item["outcome"] = "dup_in_plan"
            item.pop("data", None)
            item.pop("texts", None)
        else:
            seen.setdefault((sym, kind), []).append(dt)


def format_report(
    items: list[dict[str, Any]],
    site_results: dict[str, dict[str, Any]] | None = None,
    symbols: Iterable[str] | None = None,
) -> str:
    """Format per-symbol summary tables for link-follow, exchange, site-finder, and letter intents."""
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for sym in symbols or ():
        by_sym.setdefault(sym, [])
    for item in items:
        by_sym.setdefault(str(item["symbol"]), []).append(item)
    for sym in site_results or ():
        by_sym.setdefault(sym, [])

    lines = [
        "| symbol | link_only | resolved | held | held_same_call | dup_in_plan | audio_only | invitation | "
        "other_company | parent_resolved | failed | exch_resolved | results_resolved | ar_resolved | skipped_notice | "
        "held_same_day | site_verdict | site_docs |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for sym in sorted(by_sym):
        mine = by_sym[sym]
        links = [i for i in mine if i.get("source") == "link_follow"]
        exch = [i for i in mine if i.get("source") == "exchange"]
        site_items = [i for i in mine if i.get("source") == "company_site"]
        c_links = Counter(str(i.get("outcome") or "") for i in links)
        c_all = Counter(str(i.get("outcome") or "") for i in mine)
        other_co = sum(1 for i in mine if i.get("outcome") == "failed" and i.get("reason") == "other_company")
        parent_res = sum(1 for i in mine if i.get("outcome") == "resolved" and i.get("parent_company"))
        failed_reasons = Counter(str(i.get("reason") or "unknown") for i in mine if i.get("outcome") == "failed")
        fail_str = (
            f"{sum(failed_reasons.values())} ({','.join(f'{k}:{v}' for k, v in sorted(failed_reasons.items()))})"
            if failed_reasons
            else "0"
        )
        exch_res = sum(1 for i in exch if i.get("outcome") == "resolved")
        results_res = sum(1 for i in mine if i.get("outcome") == "resolved" and i.get("kind") == "results")
        ar_res = sum(1 for i in mine if i.get("outcome") == "resolved" and i.get("kind") == "annual_report")
        site_info = (site_results or {}).get(sym)
        site_verdict = str(site_info["verdict"]) if site_info else "-"
        site_docs = sum(1 for i in site_items if i.get("outcome") in ("resolved", "held")) if site_info else 0
        lines.append(
            f"| {sym} | {len(links)} | {c_links['resolved']} | {c_links['held']} | {c_all['held_same_call']} | "
            f"{c_all['dup_in_plan']} | {c_links['audio_only']} | {c_links['invitation']} | {other_co} | "
            f"{parent_res} | {fail_str} | {exch_res} | {results_res} | {ar_res} | {c_all['skipped_notice']} | "
            f"{c_all['held_same_day']} | {site_verdict} | {site_docs} |"
        )

    lines.append("")
    lines.append("link letters by intent")
    lines.append("| symbol | transcript | deck | audio | invitation | unknown |")
    lines.append("|---|---|---|---|---|---|")
    for sym in sorted(by_sym):
        links = [i for i in by_sym[sym] if i.get("source") == "link_follow"]
        ic = Counter(str(i.get("intent") or "unknown") for i in links)
        lines.append(
            f"| {sym} | {ic['transcript']} | {ic['deck']} | {ic['audio']} | {ic['invitation']} | {ic['unknown']} |"
        )

    other_items = [
        i for i in items if i.get("outcome") == "failed" and i.get("reason") == "other_company"
    ]
    if other_items:
        lines.append("")
        lines.append("other_company PDFs")
        for it in other_items:
            lines.append(
                f"OTHER_COMPANY {it['symbol']} {it['exchange']}:{it['filing_id']} "
                f"printed={it.get('printed_company') or '-'} target={it.get('target') or '-'}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--store-dir", required=True, help="store folder holding <store>.db and raw/manifest.csv")
    parser.add_argument("--plan-only", action="store_true", help="plan only; do not write PDFs or manifest.csv")
    parser.add_argument("--site", action="store_true", help="also crawl each symbol's company website for missing kinds")
    parser.add_argument("--site-all", action="store_true", help="search website for both transcript and deck")
    parser.add_argument("--symbols", default="", help="comma-separated symbols (default: all)")
    parser.add_argument("--json", default="", help="write plan items (without data/texts) to JSON")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT), help="raw root for resolved PDFs")
    args = parser.parse_args(argv)

    store_dir = Path(args.store_dir)
    store_db = _resolve_store_db(store_dir)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or None

    items = plan_store(store_db, symbols=symbols)
    site_results: dict[str, dict[str, Any]] = {}
    run_site = args.site or args.site_all
    if run_site:
        if symbols is None:
            conn, _ = _open_ro(store_db)
            try:
                syms = [str(r[0]).strip().upper() for r in conn.execute("SELECT DISTINCT symbol FROM company ORDER BY symbol") if r[0]]
            finally:
                conn.close()
        else:
            syms = symbols
        kinds = ("transcript", "deck") if args.site_all else None
        for sym in syms:
            res = find_site_docs(store_db, sym, kinds=kinds)
            site_results[sym] = res
            items.extend(res["items"])
        _dedupe_combined_plan(items)

    if not args.plan_only:
        apply_plan(store_dir, items, raw_root=Path(args.raw_root))

    print(format_report(items, site_results if run_site else None, symbols=symbols))
    if args.json:
        payload = [{k: v for k, v in item.items() if k not in ("data", "texts")} for item in items]
        Path(args.json).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
