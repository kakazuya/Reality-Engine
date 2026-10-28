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

import calendar
import csv
import html as html_lib
import os
import re
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

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _pace(url: str) -> None:
    host = urlparse(url).netloc or url
    wait = PACE_SEC - (time.monotonic() - _LAST_HIT.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _LAST_HIT[host] = time.monotonic()


def http_get(url: str, timeout: int = 90, referer: str = "", retries: int = 1) -> bytes:
    """GET ``url`` as a browser would, paced per host; one retry on transport error only.

    A 4xx is never retried: a moved page is a permanent answer and retrying it
    just doubles the request count. Raises ``RuntimeError`` with the last error.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    last: object = None
    for attempt in range(retries + 1):
        try:
            _pace(url)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:                   # noqa: PERF203
            if 400 <= exc.code < 500:
                raise RuntimeError(f"GET {url}: HTTP {exc.code}") from exc
            last = exc
        except Exception as exc:                                # noqa: BLE001
            last = exc
        if attempt < retries:
            time.sleep(1.0 + attempt)
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
