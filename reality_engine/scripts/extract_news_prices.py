"""Weekly news price points: India HRC steel and the Baltic Dry Index (free, no login).

Why: 31 master-bank cases name domestic HRC and 12 name freight. Neither is in
the World Bank/FRED set (a domestic HRC price is not "Steel" in USD, and the
Baltic Dry Index is published by a paid index provider). Public news pages
print both numbers often enough for a weekly series, and they carry a
publication time, so they can be used point-in-time.

Sources (declared, public, no login, no paywall, no captcha)
------------------------------------------------------------
RSS of four newsrooms -- The Economic Times, Business Standard, Mint,
Moneycontrol. For weeks older than the RSS window their ``robots.txt``
sitemaps are walked, one sampled day a week, so the crawl stays bounded and
deterministic. Nothing in this module logs in or solves a challenge; a feed
that 403s is reported, not retried with a disguise.

What is stored
--------------
value, unit, the date the price refers to, ``known_at`` (publication time,
IST), the source URL, the outlet, and a quote of **at most 15 words**. Article
text is never stored: the text is used in memory to find the sentence, and only
that sentence's first words survive in the CSV.

Extraction order
----------------
Deterministic regex first (:func:`extract_points`). Only sentences that mention
the series but yield no point go to ``--deepseek`` (the residue), and that pass
is skipped entirely when the key is absent. Nothing else is sent.

Usage:
    python -m reality_engine.scripts.extract_news_prices --dry-run
    python -m reality_engine.scripts.extract_news_prices --rss-only
    python -m reality_engine.scripts.extract_news_prices --from 2019-01-01 --to 2026-10-31
"""

from __future__ import annotations

import argparse
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from reality_engine.scripts.series_common import (
    http_get,
    plan_minutes,
    text_of,
    write_csv,
)

DEFAULT_OUT = r"D:\RealityEngine\raw\input_cost_series"
IST = timezone(timedelta(hours=5, minutes=30))

CSV_COLUMNS = ("series_code", "price_date", "value", "unit", "known_at", "quote",
               "source_url", "outlet", "price_date_basis", "pit_conf", "extractor")

#: series -> (unit, plausible level range, cue that must appear nearby).
SERIES = {
    "hrc_india": ("inr_per_tonne", (20_000.0, 90_000.0)),
    "baltic_dry_index": ("index_points", (200.0, 6_000.0)),
}

#: A series is only extracted from a sentence whose window names it. The HRC
#: window insists on HRC or hot-rolled: "steel prices" alone is a producer
#: outlook, not a transaction level.
_HRC_CUE = re.compile(r"(?i)\b(hrc|hr coil|hot[- ]rolled\s+(?:coil|steel|strip|sheet)s?)\b")
_BDI_CUE = re.compile(r"(?i)\bbaltic\s+dry(?:\s+index)?\b|\bbdi\b")
#: The few slugs that name the series itself: they are fetched first. "Baltic"
#: alone is the sea (geopolitics, 12 of 12 hits in the 2025 archive), so the
#: freight index needs its full name.
_SERIES_SLUG = re.compile(r"(?i)\bhrc\b|hot[-_ ]rolled|baltic[-_ ]dry|\bbdi\b")
#: The commodity beats worth a fetch when the slug names one. Industry words only:
#: "shipping" is dropped because the shipping beat covers cruise tourism and
#: shipbuilding (12 of 12 hits were not freight), while a freight-price story
#: says "baltic dry" or "freight". Broad enough to catch a steel story whose slug
#: does not say HRC -- the article's own text still makes the final call.
_COMMODITY_WORD = re.compile(
    r"(?i)\b(steel|cement|coking|coal|commodit\w*|metals?|freight|iron[-_ ]ore|"
    r"hrc|hot[-_ ]rolled|baltic[-_ ]dry|bdi|wpi)\b")
#: Or the URL sits in a commodity section (``/markets/commodities/``,
#: ``/industry/indl-goods/svs/steel/``), matched as whole path segments.
_COMMODITY_SECTION = re.compile(
    r"(?i)/(?:commodit\w*|steel|cement|coal|metals?|freight|indl-goods)/")
#: A ``robots.txt`` that declares several sitemaps lists its news archive after
#: unrelated ones (ET puts ``companylisting.cms`` first), so the news-shaped ones
#: are read first and the company listing never is.
_NEWS_SITEMAP = re.compile(r"(?i)news|article|story|sitemap-index|/sitemap")
#: Child sitemaps fetched per outlet. A year index expands to ~12 month files, so
#: one outlet costs at most a minute of paced requests, not the whole archive.
MAX_CHILD_FETCH = 36

_MONEY_PER_TONNE = re.compile(
    r"(?i)(?:rs\.?|\u20b9|inr)\s*([\d,]+(?:\.\d+)?)\s*(?:per\s+|/\s*|a\s+)"
    r"(?:t|ton|tonne|mt)\b")
_LEVEL_CUE = re.compile(r"(?i)(\bto|\bat|\bof|quoted|stood|settled|closed|level|price[sd]?|around|near)\s*$")
_NUMBER = re.compile(r"(?<![\d.,%])(\d[\d,]*(?:\.\d+)?)(?![\d%])")
_LEVEL_WORDS = re.compile(r"(?i)(\bto|\bat|\bof|closed|settled|ended|stood|was|is|quoted|level)\s*$")

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MNAME = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_DMY_TEXT = re.compile(rf"(?i)\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MNAME}\.?,?\s*(20\d{{2}})\b")
_MDY_TEXT = re.compile(rf"(?i)\b{_MNAME}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(20\d{{2}})\b")
_DAY_MONTH_NO_YEAR = re.compile(rf"(?i)\b(?:on|as\s+of)\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MNAME}\b")
#: "on April 29" -- group(1) is the month, group(2) the day (the month pattern's
#: own capture comes first). A four-digit year cannot match the day group. The
#: locative preposition is required: "since October 7" records a comparison, and
#: reading it as the price date pushed a June level into the previous year.
_MONTH_DAY_NO_YEAR = re.compile(rf"(?i)\b(?:on|as\s+of)\s+(?:{_MNAME})\.?\s+(\d{{1,2}})\b")
#: A bare month dates a price only after a locative preposition. "since October"
#: and "from April" compare against a level, and reading those as the price date
#: moved a June reading to the previous year.
_MONTH_ONLY = re.compile(rf"(?i)\b(?:in|during|as\s+of)\s+({_MNAME})\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")

#: Public RSS feeds (RSS 2.0 unless noted). Long-stable URLs; a feed that has
#: moved is reported per-run by name instead of being silently replaced.
FEEDS = (
    ("economictimes", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("economictimes", "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms"),
    ("business-standard", "https://www.business-standard.com/rss/markets-106.rss"),
    ("business-standard", "https://www.business-standard.com/rss/companies-101.rss"),
    ("livemint", "https://www.livemint.com/rss/markets"),
    ("livemint", "https://www.livemint.com/rss/economy"),
    ("moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
    ("moneycontrol", "https://www.moneycontrol.com/rss/business.xml"),
)
OUTLET_BASES = {
    "economictimes": "https://economictimes.indiatimes.com",
    "business-standard": "https://www.business-standard.com",
    "livemint": "https://www.livemint.com",
    "moneycontrol": "https://www.moneycontrol.com",
}
MAX_QUOTE_WORDS = 15
MAX_ARTICLES_PER_FEED = 25


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
def _parse_dt(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)              # RFC 822 (RSS pubDate)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ist_iso(dt: datetime | None) -> str:
    """Publication time as an IST ISO string; ``''`` when unknown (never "now")."""
    return "" if dt is None else dt.astimezone(IST).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Feed / sitemap readers
# ---------------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(el, names: tuple[str, ...]) -> str:
    for child in el:
        if _local(child.tag) in names:
            return text_of("".join(child.itertext()))
    return ""


def _child_link(el) -> str:
    for child in el:
        if _local(child.tag) == "link":
            href = child.get("href")
            if href:
                return href.strip()
            return (child.text or "").strip()
    return ""


def parse_rss(payload: bytes) -> dict:
    """RSS 2.0 or Atom -> ``{'status', 'items': [{title, link, published, text}]}``."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        return {"status": "failed", "reason": f"not XML: {exc}", "items": []}
    items = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        items.append({
            "title": _child_text(el, ("title",)),
            "link": _child_link(el),
            "published": _parse_dt(_child_text(el, ("pubdate", "published", "updated", "date"))),
            "text": _child_text(el, ("description", "summary", "content", "encoded")),
        })
    return {"status": "ok" if items else "failed", "reason": None if items else "no items",
            "items": items}


def robots_sitemaps(txt: str) -> list[str]:
    """``Sitemap:`` directives from robots.txt, in file order."""
    return re.findall(r"(?im)^\s*sitemap:\s*(\S+)", txt or "")


def parse_sitemap(payload: bytes) -> dict:
    """``<sitemapindex>`` or ``<urlset>`` -> ``{'kind', 'entries': [{loc, lastmod}]}``."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        return {"kind": "invalid", "reason": f"not XML: {exc}", "entries": []}
    kind = _local(root.tag)
    entries = []
    for el in root:
        if _local(el.tag) not in ("sitemap", "url"):
            continue
        loc = _child_text(el, ("loc",))
        if loc:
            entries.append({"loc": loc, "lastmod": _child_text(el, ("lastmod",))[:10]})
    return {"kind": kind if kind in ("sitemapindex", "urlset") else "invalid",
            "reason": None, "entries": entries}


def _date_in(text: str) -> str:
    """``YYYY-MM-DD`` hidden in a URL or a ``lastmod`` -> ISO date, else ``''``.

    Two archive naming schemes matter here: both outlets publish their history as
    ``<year>-<month name>-<half>.xml`` (``2025-june-1.xml``), which carries no
    numeric date, and Business Standard also links a ``year-2025.xml`` index. A
    month file is dated to its own first or sixteenth, so the weekly pick lands on
    the file that holds that week instead of skipping the whole archive.
    """
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text or "")
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(?i)\b(20\d{2})-([a-z]{3,9})-(\d)\b", text or "")
    if m:
        month = _MONTHS.get(m.group(2).lower()[:3], 0)
        if 1 <= month <= 12:
            return f"{m.group(1)}-{month:02d}-{'01' if m.group(3) == '1' else '16'}"
    m = re.search(r"(?i)\byear[-_ ]?(20\d{2})\b", text or "")
    if m:
        return f"{m.group(1)}-01-01"
    return (text or "")[:10] if re.match(r"20\d{2}-\d{2}-\d{2}", text or "") else ""


def weekly_days(start: date, end: date, weekday: int = 4) -> list[date]:
    """One sampled day a week (Friday by default) -- a weekly series needs no more."""
    day = start + timedelta(days=(weekday - start.weekday()) % 7)
    out = []
    while day <= end:
        out.append(day)
        day += timedelta(days=7)
    return out


#: A year/month archive is published in several flavours: articles, video,
#: liveblog, AMP. They share a date, so a tie must prefer the article archive.
_NON_ARTICLE_SITEMAP = re.compile(r"(?i)/(?:video|liveblog|amp)[-/]")

def pick_weekly(entries: list[dict], days: list[date]) -> list[str]:
    """For each sampled day, the sitemap/url entry dated nearest on or before it.

    The date in the loc wins over ``lastmod``: an archive child is named for the
    period it holds (``year-2025.xml``), while its ``lastmod`` is when the file
    was last rebuilt -- often today, which would hide the whole archive. Equally
    dated children are ordered so an article archive sorts after its video and
    liveblog siblings, and the pick below takes the last one at or before the day.

    Deterministic: exact date wins, else the newest entry not after the day,
    else the oldest entry after it (a forward-only archive).
    """
    dated = sorted(((_date_in(e["loc"]) or e["lastmod"], e["loc"]) for e in entries
                    if (_date_in(e["loc"]) or e["lastmod"])),
                   key=lambda t: (t[0], not _NON_ARTICLE_SITEMAP.search(t[1]), t[1]))
    if not dated:
        return []
    picked: list[str] = []
    for day in days:
        iso = day.isoformat()
        chosen = next((loc for d, loc in dated if d == iso), None)
        if chosen is None:
            before = [(d, loc) for d, loc in dated if d <= iso]
            after = [(d, loc) for d, loc in dated if d > iso]
            chosen = before[-1][1] if before else (after[0][1] if after else None)
        if chosen and chosen not in picked:
            picked.append(chosen)
    return picked


# ---------------------------------------------------------------------------
# Article text and the extractor
# ---------------------------------------------------------------------------
_META_RE = re.compile(
    r"(?is)<meta\b[^>]*?(?:property|name)=[\"'](?:article:published_time|publish-date|"
    r"publication_date|date|pubdate)[\"'][^>]*?content=[\"']([^\"']+)[\"']")
_META_REV_RE = re.compile(
    r"(?is)<meta\b[^>]*?content=[\"']([^\"']+)[\"'][^>]*?(?:property|name)=[\"']"
    r"(?:article:published_time|publish-date|publication_date|date|pubdate)[\"']")
_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_H1_RE = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>")
_LD_DATE = re.compile(r'(?i)"datePublished"\s*:\s*"([^"]+)"')
_TIME_TAG = re.compile(r'(?is)<time\b[^>]*?datetime=["\']([^"\']+)["\']')
#: Scripts and styles are text nodes as far as a tag-stripping helper is
#: concerned: leaving them in front of the article pushed the story (and the
#: price it quotes) past the body limit on every outlet page.
_OPAQUE_RE = re.compile(r"(?is)<(script|style|noscript|svg)\b.*?</\1\s*>")
_BODY_LIMIT = 40_000


def article_text(html: str) -> dict:
    """Title, meta description, first body paragraphs and the publication time.

    Returns text only; nothing here is persisted except the 15-word quote that
    :func:`extract_points` derives from it.
    """
    published = ""
    for rx in (_META_RE, _META_REV_RE, _LD_DATE, _TIME_TAG):
        m = rx.search(html or "")
        if m:
            dt = _parse_dt(m.group(1))
            if dt:
                published = ist_iso(dt)
                break
    title = text_of((_TITLE_RE.search(html or "") or [None, ""])[1])
    heading = text_of((_H1_RE.search(html or "") or [None, ""])[1])
    desc = ""
    m = re.search(r"(?is)<meta\b[^>]*?name=[\"']description[\"'][^>]*?content=[\"']([^\"']+)", html or "")
    if m:
        desc = text_of(m.group(1))
    body = text_of(_OPAQUE_RE.sub(" ", html or ""))[:_BODY_LIMIT]
    return {"title": title, "heading": heading, "description": desc,
            "body": body, "published": published}


#: A price statement is a sentence; a "sentence" this long is a run of page
#: furniture that happens to end in a full stop (a footer glued to the story by
#: one period), and the number found in it is a year or a menu item. 600 chars
#: is well above any real market sentence and below the merged footer blocks.
MAX_SENTENCE_CHARS = 600


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "")
            if s.strip() and len(s) <= MAX_SENTENCE_CHARS]


def quote_of(sentence: str, start: int, end: int, max_words: int = MAX_QUOTE_WORDS) -> str:
    """A <=15-word window of one sentence that still contains the matched number."""
    words = sentence.split()
    if not words:
        return ""
    # The word that holds the match start, then a window that keeps it inside.
    pos = min(len(words) - 1, len(sentence[:start].split()))
    first = max(0, min(pos - max_words // 2, len(words) - max_words))
    return " ".join(" ".join(words[first:first + max_words]).strip(" ,;:").split())


def _same_year_month(month: int, day: int, fallback: str) -> str | None:
    """A date written without its year -> the year it must belong to, or ``None``.

    The publication year, or the year before it when that month had not arrived
    yet (a June story saying "in January"). Never a year ahead of publication.
    """
    published = (fallback or "")[:10]
    if not re.match(r"20\d{2}-\d{2}", published):
        return None
    year = int(published[:4]) - (1 if month > int(published[5:7]) else 0)
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def price_date_in(sentence: str, fallback: str) -> tuple[str, str]:
    """The date the price refers to, with how it was established."""
    m = _DMY_TEXT.search(sentence or "")
    if m and 1 <= int(m.group(1)) <= 31:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(2).lower()[:3]],
                        int(m.group(1))).isoformat(), "stated"
        except ValueError:
            pass
    m = _MDY_TEXT.search(sentence or "")
    if m and 1 <= int(m.group(2)) <= 31:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(1).lower()[:3]],
                        int(m.group(2))).isoformat(), "stated"
        except ValueError:
            pass
    # "on April 29" / "in January": the outlet drops the year, and defaulting
    # those to the publication date puts an April level in June.
    m = _DAY_MONTH_NO_YEAR.search(sentence or "")
    if m and 1 <= int(m.group(1)) <= 31:
        iso = _same_year_month(_MONTHS[m.group(2).lower()[:3]], int(m.group(1)), fallback)
        if iso:
            return iso, "stated"
    m = _MONTH_DAY_NO_YEAR.search(sentence or "")
    if m and 1 <= int(m.group(2)) <= 31:
        iso = _same_year_month(_MONTHS[m.group(1).lower()[:3]], int(m.group(2)), fallback)
        if iso:
            return iso, "stated"
    m = _MONTH_ONLY.search(sentence or "")
    if m:
        iso = _same_year_month(_MONTHS[m.group(1).lower()[:3]], 1, fallback)
        if iso:
            return iso, "stated"
    return fallback, "pubdate"


def _hrc_points(sentence: str) -> list[dict]:
    """Levels in ₹/tonne near an HRC mention; a change ("by Rs 500/t") is not a level."""
    low, high = SERIES["hrc_india"][1]
    best, best_score = None, -1
    for m in _MONEY_PER_TONNE.finditer(sentence):
        value = float(m.group(1).replace(",", ""))
        if not low <= value <= high:
            continue
        score = 2 if _LEVEL_CUE.search(sentence[max(0, m.start() - 18):m.start()]) else 1
        if _HRC_CUE.search(sentence[max(0, m.start() - 160):m.end() + 160]):
            score += 1
        if score >= best_score:
            best, best_score = {"value": value, "start": m.start(), "end": m.end()}, score
    return [best] if best else []


def _bdi_points(sentence: str) -> list[dict]:
    """Levels in index points near the cue; a percentage move is never the level."""
    low, high = SERIES["baltic_dry_index"][1]
    cue = _BDI_CUE.search(sentence)
    if not cue:
        return []
    best, best_score = None, -1
    for m in _NUMBER.finditer(sentence):
        value = float(m.group(1).replace(",", ""))
        if not low <= value <= high:
            continue
        score = 2 if _LEVEL_WORDS.search(sentence[max(0, m.start() - 12):m.start()]) else 1
        if m.start() <= cue.start() <= m.end():    # "BDI 1,850" -- number right at the cue
            score += 2
        if score >= best_score:
            best, best_score = {"value": value, "start": m.start(), "end": m.end()}, score
    return [best] if best else []


def extract_points(text: str, source_url: str, outlet: str, known_at: str,
                   price_date_default: str) -> tuple[list[dict], list[str]]:
    """One article's text -> rows plus the sentences that mention a series but did not parse."""
    rows: list[dict] = []
    residue: list[str] = []
    index_of: dict[tuple[str, float], int] = {}
    for sentence in sentences(text):
        for code, cue, picker in (("hrc_india", _HRC_CUE, _hrc_points),
                                  ("baltic_dry_index", _BDI_CUE, _bdi_points)):
            if not cue.search(sentence):
                continue
            found = picker(sentence)
            if not found:
                stripped = quote_of(sentence, 0, 0)
                if stripped and len(stripped.split()) >= 3:
                    residue.append(stripped)
                continue
            for hit in found:
                key = (code, hit["value"])
                price_date, basis = price_date_in(sentence, price_date_default)
                published_day = (known_at or "")[:10]
                if basis == "stated" and published_day and price_date > published_day:
                    # A date printed on the page itself (the render date in the
                    # masthead) is ahead of publication, so the "level" beside it
                    # is the year. Impossible dates are dropped, not re-dated.
                    continue
                row = {
                    "series_code": code,
                    "price_date": price_date,
                    "value": hit["value"],
                    "unit": SERIES[code][0],
                    "known_at": known_at,
                    "quote": quote_of(sentence, hit["start"], hit["end"]),
                    "source_url": source_url,
                    "outlet": outlet,
                    "price_date_basis": basis,
                    "pit_conf": 1.0 if basis == "stated" else 0.9,
                    "extractor": "regex",
                }
                if key in index_of:
                    # The same level in a headline and in a dated body sentence:
                    # the dated one carries the better price date.
                    if rows[index_of[key]]["price_date_basis"] == "stated" or basis != "stated":
                        continue
                    rows[index_of[key]] = row
                else:
                    index_of[key] = len(rows)
                    rows.append(row)
    return rows, residue


# ---------------------------------------------------------------------------
# Optional residue pass -- skipped entirely when the key is absent
# ---------------------------------------------------------------------------
GO_BASE = "https://opencode.ai/zen/go/v1"
GO_MODEL = "deepseek-v4.1-flash"


def deepseek_points(sentences_in: list[str], key: str, timeout: int = 90) -> list[dict]:
    """Ask the free Go model to read ONLY the unparsed sentences.

    Best effort by design: any transport or shape error returns ``[]`` and the
    deterministic rows stay. The prompt carries the sentences, never the article.
    """
    if not sentences_in:
        return []
    prompt = (
        "Extract price levels from these news sentences. Reply with a JSON array only, "
        'each {"series": "hrc_india"|"baltic_dry_index", "value": number, '
        '"unit": "inr_per_tonne"|"index_points", "date": "YYYY-MM-DD"|null, '
        '"quote": "<=15 words"}. No prose. Sentences:\n'
        + "\n".join(f"- {s}" for s in sentences_in[:40])
    )
    try:
        import requests                                        # noqa: PLC0415
        resp = requests.post(
            f"{GO_BASE}/chat/completions", timeout=timeout,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": GO_MODEL, "max_tokens": 1500,
                  "messages": [{"role": "user", "content": prompt}]})
        if resp.status_code != 200:
            return []
        body = resp.json()["choices"][0]["message"].get("content") or ""
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", body.strip())
        start, end = raw.find("["), raw.rfind("]")
        parsed = json.loads(raw[start:end + 1]) if 0 <= start < end else []
    except Exception:                                          # noqa: BLE001
        return []
    out = []
    for item in parsed if isinstance(parsed, list) else []:
        code = item.get("series")
        if code not in SERIES:
            continue
        try:
            value = float(str(item.get("value", "")).replace(",", ""))
        except ValueError:
            continue
        if not SERIES[code][1][0] <= value <= SERIES[code][1][1]:
            continue
        quote = " ".join(str(item.get("quote") or "").split()[:MAX_QUOTE_WORDS])
        out.append({"series_code": code, "value": value, "unit": SERIES[code][0],
                    "date": item.get("date"), "quote": quote})
    return out


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------
def rss_articles(feeds, stats: dict, article_budget: int, fetcher=http_get) -> list[dict]:
    """Fetch the declared feeds and keep the items whose own text names a series."""
    out: list[dict] = []
    for outlet, url in feeds:
        stats["requests"] += 1
        try:
            payload = fetcher(url, timeout=60)
        except Exception as exc:                              # noqa: BLE001
            stats["feeds"].append({"outlet": outlet, "url": url, "status": "failed",
                                   "reason": str(exc)[:160]})
            continue
        parsed = parse_rss(payload)
        hits = [i for i in parsed["items"]
                if _HRC_CUE.search(f"{i['title']} {i['text']}")
                or _BDI_CUE.search(f"{i['title']} {i['text']}")]
        stats["feeds"].append({"outlet": outlet, "url": url, "status": parsed["status"],
                               "items": len(parsed["items"]), "hits": len(hits),
                               "reason": parsed["reason"]})
        out += [{"outlet": outlet, "url": i["link"], "published": ist_iso(i["published"]),
                 "title": i["title"], "text": i["text"]} for i in hits[:MAX_ARTICLES_PER_FEED]]
        if len(out) >= article_budget:
            break
    return out


def candidate(url: str) -> bool:
    """A sitemap URL worth one article fetch: it names a series or a commodity beat."""
    return bool(_SERIES_SLUG.search(url) or _COMMODITY_WORD.search(url)
                or _COMMODITY_SECTION.search(url))


def sitemap_articles(outlets, start: date, end: date, stats: dict,
                     fetcher=http_get) -> list[dict]:
    """Walk ``robots.txt`` -> sitemap index -> the child sitemap nearest each sampled week.

    Both outlets publish their history as month files behind a year index, so a
    child that is itself an index is expanded one level (bounded by
    :data:`MAX_CHILD_FETCH`). Without that, the archive is unreachable and the
    backfill reads only the last few days.
    """
    days = weekly_days(start, end)
    first, last = start.isoformat(), end.isoformat()
    found: list[dict] = []

    def take(entries: list[dict]) -> None:
        """Append the entries a fetch could use, skipping a point dated off-window."""
        for entry in entries:
            published = entry["lastmod"] or ""
            if published and not first <= published <= last:
                continue                     # a today/yesterday sitemap in a historic run
            if candidate(entry["loc"]):
                found.append({"outlet": outlet, "url": entry["loc"],
                              "published": entry["lastmod"], "title": "", "text": ""})

    for outlet, base in outlets.items():
        stats["requests"] += 1
        try:
            robots = fetcher(f"{base}/robots.txt", timeout=30).decode("utf-8", "replace")
        except Exception as exc:                              # noqa: BLE001
            stats["sitemaps"].append({"outlet": outlet, "status": "failed",
                                      "reason": str(exc)[:160]})
            continue
        urls = sorted(robots_sitemaps(robots),
                      key=lambda u: 0 if _NEWS_SITEMAP.search(u) else 1)
        if not urls:
            stats["sitemaps"].append({"outlet": outlet, "status": "no-sitemap"})
            continue
        child_locs: list[str] = []
        for index_url in urls[:2]:
            stats["requests"] += 1
            try:
                payload = fetcher(index_url, timeout=60)
            except Exception as exc:                          # noqa: BLE001
                stats["sitemaps"].append({"outlet": outlet, "index": index_url,
                                          "status": "failed", "reason": str(exc)[:160]})
                continue
            parsed = parse_sitemap(payload)
            if parsed["kind"] == "sitemapindex":
                dated = [(_date_in(e["loc"]) or e["lastmod"], e["loc"])
                         for e in parsed["entries"] if _date_in(e["loc"]) or e["lastmod"]]
                # The files that DESCRIBE the window first: a year index
                # ("year-2025.xml") is what holds January, and the nearest-dated
                # rule would otherwise pick a fresher unrelated listing.
                covering = [loc for d, loc in dated if first <= d <= last]
                child_locs += list(dict.fromkeys(covering + pick_weekly(parsed["entries"], days)))
            else:
                take(parsed["entries"])
        queue, fetched = list(dict.fromkeys(child_locs))[:MAX_CHILD_FETCH], 0
        while queue and fetched < MAX_CHILD_FETCH:
            child = queue.pop(0)
            fetched += 1
            stats["requests"] += 1
            try:
                payload = fetcher(child, timeout=120)
            except Exception as exc:                          # noqa: BLE001
                stats["sitemaps"].append({"outlet": outlet, "child": child,
                                          "status": "failed", "reason": str(exc)[:160]})
                continue
            parsed = parse_sitemap(payload)
            if parsed["kind"] == "sitemapindex":              # a year -> its month files
                queue += [loc for loc in pick_weekly(parsed["entries"], days)
                          if loc not in queue][:MAX_CHILD_FETCH - fetched]
                continue
            take(parsed["entries"])
        stats["sitemaps"].append({"outlet": outlet, "index": urls[0],
                                  "status": "ok" if fetched else "index-only",
                                  "children": fetched})
    # The budget is far smaller than the candidate list, so the few URLs whose
    # own slug names the series go first, then one candidate per month at a time:
    # a weekly series needs a candidate in every month, not the first hundred
    # January ones. Undated candidates come last (they cost a fetch to date).
    ordered = sorted(found, key=lambda c: (_slug_rank(c["url"]), c["published"] or "",
                                           c["url"]))
    spread: list[dict] = []
    for rank in sorted({_slug_rank(c["url"]) for c in ordered}):
        by_month: dict[str, list[dict]] = {}
        for item in (c for c in ordered if _slug_rank(c["url"]) == rank):
            by_month.setdefault((item["published"] or "")[:7] or "9999", []).append(item)
        for i in range(max((len(v) for v in by_month.values()), default=0)):
            for month in sorted(by_month):
                if i < len(by_month[month]):
                    spread.append(by_month[month][i])
    return spread


#: Outlet article ids (ET ``/articleshow/117798403.cms``, BS ``...-125061700311_1.html``).
#: A section hub carries the beat in its path but has no id and no publication
#: time, so pages carrying an id are fetched first.
_ARTICLE_ID = re.compile(r"\d{6,}")
#: A slug that says "price" is where a level gets printed (measured on BS June
#: 2025: 2 HRC levels in 40 price/commodity articles, 0 in the rest); the
#: commodity word alone is usually company news ("commissions galvanising line").
_PRICE_WORD = re.compile(r"(?i)\b(price|prices|rate|rates|quotations?)\b")


def _slug_rank(url: str) -> int:
    """0 names the series, 1 a price story on a commodity beat, 2 the beat, 3 a hub."""
    if not _ARTICLE_ID.search(url):
        return 3
    if _SERIES_SLUG.search(url):
        return 0
    if _COMMODITY_WORD.search(url) and _PRICE_WORD.search(url):
        return 1
    return 2


def _article_default_date(candidate: dict) -> str:
    stamp = candidate.get("published") or ""
    return stamp[:10] if re.match(r"20\d{2}-\d{2}-\d{2}", stamp) else ""


def harvest(candidates: list[dict], stats: dict, max_articles: int,
            deepseek_key: str = "", fetcher=http_get) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    for cand in candidates[:max_articles]:
        stats["requests"] += 1
        try:
            html = fetcher(cand["url"], timeout=60).decode("utf-8", "replace")
        except Exception as exc:                              # noqa: BLE001
            stats["articles_failed"].append({"url": cand["url"], "reason": str(exc)[:160]})
            continue
        page = article_text(html)
        known_at = page["published"] or cand.get("published") or ""
        if not known_at:
            stats["articles_no_known_at"].append(cand["url"])
            continue                              # never date a point to today
        text = ". ".join(filter(None, (cand.get("title"), page["title"],
                                       page["description"], page["body"])))
        default_day = _article_default_date({"published": known_at})
        got, residue = extract_points(text, cand["url"], cand["outlet"], known_at, default_day)
        rows += got
        if not got and residue and deepseek_key:
            for item in deepseek_points(residue, deepseek_key):
                rows.append({
                    "series_code": item["series_code"],
                    "price_date": item["date"] or default_day,
                    "value": item["value"], "unit": item["unit"],
                    "known_at": known_at, "quote": item["quote"],
                    "source_url": cand["url"], "outlet": cand["outlet"],
                    "price_date_basis": "stated" if item["date"] else "pubdate",
                    "pit_conf": 0.6, "extractor": "deepseek_residue"})
        stats["articles_parsed"] += 1
    return rows, stats


def dedupe(rows: list[dict]) -> list[dict]:
    """One row per (series, price date, value), keeping the earliest ``known_at``.

    Two outlets quoting different levels for the same day are both kept: the
    disagreement is evidence, not noise to average away.
    """
    best: dict[tuple, dict] = {}
    for row in sorted(rows, key=lambda r: (r["series_code"], r["price_date"],
                                           r["value"], r["known_at"])):
        best.setdefault((row["series_code"], row["price_date"], row["value"]), row)
    return sorted(best.values(), key=lambda r: (r["series_code"], r["price_date"], r["value"]))


def plan(start: date, end: date, sitemap: bool = True) -> dict:
    weeks = len(weekly_days(start, end))
    outlets = len(OUTLET_BASES)
    rss = len(FEEDS)
    robots = outlets
    indexes = outlets * 2
    children = weeks * outlets
    articles = (rss * 2) + (children * 2 if sitemap else 0)
    requests = rss + (robots + indexes + children + articles if sitemap else articles)
    return {
        "weeks_sampled": weeks,
        "rss_feeds": rss,
        "sitemap_outlets": outlets if sitemap else 0,
        "sitemap_children": children if sitemap else 0,
        "requests_p50": requests,
        "requests_max": int(requests * 1.2),
        "est_minutes_p50": plan_minutes(requests),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--from", dest="start", default="2019-01-01")
    ap.add_argument("--to", dest="end", default=date.today().isoformat())
    ap.add_argument("--rss-only", action="store_true",
                    help="skip the sitemap walk (going-forward only)")
    ap.add_argument("--max-articles", type=int, default=400)
    ap.add_argument("--deepseek", action="store_true",
                    help="run the residue pass when OPENCODE_GO_API_KEY is set")
    ap.add_argument("--dry-run", action="store_true", help="plan only: no network, no writes")
    args = ap.parse_args(argv)

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    for key, value in plan(start, end, sitemap=not args.rss_only).items():
        print(f"  {key:20} {value}")
    if args.dry_run:
        print("dry-run: no request made")
        return 0

    key = os.environ.get("OPENCODE_GO_API_KEY", "") if args.deepseek else ""
    if args.deepseek and not key:
        print("deepseek: skipped (OPENCODE_GO_API_KEY not set) -- deterministic rows only")
    stats = {"requests": 0, "feeds": [], "sitemaps": [], "articles_failed": [],
             "articles_no_known_at": [], "articles_parsed": 0}
    candidates = rss_articles(FEEDS, stats, args.max_articles)
    if not args.rss_only:
        candidates += sitemap_articles(OUTLET_BASES, start, end, stats)
    rows, stats = harvest(candidates, stats, args.max_articles, key)
    rows = dedupe(rows)
    # The archive walk reaches today's sitemaps too, so an explicit window is
    # enforced on the point's own date: a 2025 backfill never emits a 2026 level.
    first, last = start.isoformat(), end.isoformat()
    rows = [r for r in rows if first <= (r["price_date"] or "") <= last]
    out = Path(args.out)
    written = write_csv(out / "news_price_points.csv", CSV_COLUMNS, rows)
    print(f"news: {stats}")
    print(f"wrote {written} rows -> {out / 'news_price_points.csv'}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
