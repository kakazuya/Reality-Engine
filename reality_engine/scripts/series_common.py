"""Shared stdlib plumbing for the input-cost series fetchers.

Three scripts (``fetch_wpi_items``, ``extract_news_prices``,
``fetch_imd_rainfall``) each fetch a few small public HTML/PDF/JSON files and
write one CSV. They share exactly four things -- a browser-shaped GET with one
retry, the pace between requests, the visible-text helper and the atomic CSV
writer -- so those live here instead of being copied three times.

Deliberately not here: any third-party HTTP client. ``urllib`` is enough for
GETs of public pages, and it keeps the fetchers runnable from a bare stdlib
Python (the controller runs them outside this sandbox).
"""

from __future__ import annotations

import base64
import calendar
import csv
import html as html_lib
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
#: Seconds between requests to the same host. Public, unauthenticated sources;
#: one request a second is polite and still finishes a backfill fast. Enforced
#: centrally in :func:`http_get` so no fetcher has to remember it.
PACE_SEC = 1.0
_LAST_HIT: dict[str, float] = {}
#: Host -> HTTP code of a 403/429 seen this run. A host that says "no" once is
#: not asked again: the report names it, and the rest of the run continues.
BLOCKED: dict[str, int] = {}
#: host -> verified context (system store plus the AIA intermediate, when the
#: server omits it). Cached so one handshake fix serves the whole run.
_CONTEXTS: dict[str, ssl.SSLContext] = {}
#: Hosts whose chain was already completed once; a second failure is permanent.
_FIXED: set[str] = set()

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _pace(url: str) -> None:
    host = urlparse(url).netloc or url
    if host in BLOCKED:
        raise RuntimeError(f"{host}: not asked again after HTTP {BLOCKED[host]}")
    wait = PACE_SEC - (time.monotonic() - _LAST_HIT.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _LAST_HIT[host] = time.monotonic()


#: An AIA URI is a DER ``IA5String`` (tag 0x86, one-byte length, then the ASCII
#: URL), so the issuer the server forgot to send is readable without an X.509
#: library. The length byte is honoured: the neighbouring ASN.1 bytes are often
#: printable and a bare "http://" scan would eat them.
_IA5_TAG = 0x86


def aia_urls(der: bytes) -> list[str]:
    """``caIssuers`` URLs named inside a certificate's DER blob.

    This is the AIA extension (``http://yr1.i.lencr.org/`` for the OEA site): the
    certificate says where its issuer can be downloaded, which is exactly what a
    server that omits the intermediate makes necessary.
    """
    out: list[str] = []
    for i, byte in enumerate(der or b""):
        if byte != _IA5_TAG or i + 2 >= len(der):
            continue
        end = i + 2 + der[i + 1]
        if end > len(der):
            continue
        blob = der[i + 2:end]
        if not blob.startswith(b"http"):
            continue
        url = blob.decode("ascii", "replace")
        if "." in urlparse(url).netloc and url not in out:
            out.append(url)
    return out


def context_with_chain(extra_pems: tuple[str, ...] = ()) -> ssl.SSLContext:
    """A verifying context: the system store plus the intermediates the server omitted.

    ``CERT_NONE`` never appears here. A host whose chain cannot be completed
    stays unverifiable and its request fails, which is the safe answer.
    """
    ctx = ssl.create_default_context()
    for pem in extra_pems:
        ctx.load_verify_locations(cadata=pem)
    return ctx


def _aia_intermediate(url: str, timeout: int) -> str:
    """PEM of the issuer certificate named by the leaf's AIA extension, or ``""``.

    The unverified handshake here reads the certificate only; the data GET that
    matters always runs on :func:`context_with_chain`, never on this context.
    """
    host = urlparse(url).netloc.split(":")[0]
    try:
        with socket.create_connection((host, 443), timeout=timeout) as sock:
            with ssl._create_unverified_context().wrap_socket(  # noqa: SLF001
                    sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
        for aia in aia_urls(der):
            if aia.lower().endswith(".crl"):
                continue                     # the leaf also names its revocation list
            for _attempt in range(2):        # one retry: the issuer host is a third party
                try:
                    payload = http_get(aia, timeout=timeout, retries=0)
                    break
                except Exception:                            # noqa: BLE001
                    payload = b""
                    time.sleep(1.0)
            if payload[:1] == b"\x30":                      # DER SEQUENCE
                body = base64.encodebytes(payload).decode("ascii")
                return ("-----BEGIN CERTIFICATE-----\n"
                        + body + "-----END CERTIFICATE-----\n")
    except Exception:                                      # noqa: BLE001
        return ""
    return ""


def _context(url: str) -> ssl.SSLContext:
    host = urlparse(url).netloc
    if host not in _CONTEXTS:
        _CONTEXTS[host] = context_with_chain()
    return _CONTEXTS[host]


def _cert_error(exc: BaseException) -> bool:
    """True for an incomplete-chain failure, wrapped by urllib or not.

    ``ssl.SSLError`` carries a string ``reason``, so testing only
    ``getattr(exc, "reason", exc)`` misses the bare exception that urllib lets
    through on some paths -- and the run then reports a chain failure it could
    have repaired.
    """
    for candidate in (exc, getattr(exc, "reason", None)):
        if isinstance(candidate, ssl.SSLCertVerificationError):
            return True
        if isinstance(candidate, str) and "CERTIFICATE_VERIFY_FAILED" in candidate:
            return True
    return False


def http_get(url: str, timeout: int = 90, referer: str = "", retries: int = 2) -> bytes:
    """GET ``url`` as a browser would, paced per host; transport errors are retried.

    A 4xx is never retried: a moved page is a permanent answer and retrying it
    just doubles the request count. A 403/429 also parks the host for the rest of
    the run (:data:`BLOCKED`), which is the rule for every source here. A chain
    the server sends incomplete is completed from the leaf's AIA URL and retried
    once on a verifying context -- never by relaxing verification.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    host = urlparse(url).netloc
    last: object = None
    for attempt in range(retries + 1):
        try:
            _pace(url)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=_context(url)) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:                   # noqa: PERF203
            if exc.code in (403, 429):
                BLOCKED[host] = exc.code
            if 400 <= exc.code < 500:
                raise RuntimeError(f"GET {url}: HTTP {exc.code}") from exc
            last = exc
        except Exception as exc:                                # noqa: BLE001
            if _cert_error(exc):
                pem = "" if host in _FIXED else _aia_intermediate(url, timeout)
                if not pem:
                    raise RuntimeError(f"GET {url} failed: {exc}") from exc
                _FIXED.add(host)
                _CONTEXTS[host] = context_with_chain((pem,))
            last = exc
        if attempt < retries:
            time.sleep(1.0 + 2 ** attempt)                       # 1s, 3s, 7s
    raise RuntimeError(f"GET {url} failed: {last}")


def text_of(fragment: str) -> str:
    """Visible text of an HTML fragment: tags dropped, entities decoded, spaces collapsed."""
    return _WS_RE.sub(" ", html_lib.unescape(_TAG_RE.sub(" ", fragment or ""))).strip()


_ANCHOR_RE = re.compile(r"(?is)<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>")
_ROW_SPLIT_RE = re.compile(r"(?i)<tr\b")
_CELL_RE = re.compile(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>")
_NUM_RE = re.compile(r"^[+-]?\d[\d,]*(?:\.\d+)?$")


def anchors(html: str, base_url: str) -> list[tuple[str, str]]:
    """``(absolute_url, visible_text)`` for every ``<a href>`` on a page."""
    from urllib.parse import urljoin

    out = []
    for href, label in _ANCHOR_RE.findall(html or ""):
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        out.append((href if href.startswith("http") else urljoin(base_url, href), text_of(label)))
    return out


def html_rows(payload: str) -> list[list[str]]:
    """``<tr>`` blocks -> cleaned cell lists, ``<th>`` included (headers matter)."""
    rows = []
    for chunk in _ROW_SPLIT_RE.split(payload or ""):
        cells = [text_of(c) for c in _CELL_RE.findall(chunk)]
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def text_rows(payload: str) -> list[list[str]]:
    """Plain text (a PDF's text layer) -> cell lists split on a tab or two-plus spaces."""
    rows = []
    for line in (payload or "").splitlines():
        cells = [c.strip() for c in re.split(r"\t| {2,}", line.strip()) if c.strip()]
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def num(cell: str) -> float | None:
    """A table cell as a number, or ``None``. Strips thousands commas, ``%``, ``*``.

    U+2212 (the minus sign PDFs emit) is folded to ASCII ``-``; without that a
    deficient-rainfall cell reads as a positive number.
    """
    raw = (cell or "").replace("\u2212", "-").replace("*", "").replace("%", "").strip()
    if not raw or not _NUM_RE.match(raw):
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> int:
    """Write ``rows`` atomically (``.part`` then replace), returning the count.

    A killed run therefore never leaves a half-written series behind, and a
    re-run overwrites the artefact instead of appending to it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(columns), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)
    return len(rows)


def month_end(year: int, month: int) -> str:
    """ISO date of the last day of ``year``-``month``; the period key of a monthly index."""
    return date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def month_range(start: date, end: date):
    """Yield ``(year, month)`` from ``start``'s month through ``end``'s, inclusive."""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def plan_minutes(requests: int, pace: float = PACE_SEC) -> float:
    """Rough wall-clock estimate: one paced request plus its latency."""
    return round(requests * (pace + 1.0) / 60, 1)
