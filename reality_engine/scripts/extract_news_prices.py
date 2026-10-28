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
    """``YYYY-MM-DD`` hidden in a URL or a ``lastmod`` -> ISO date, else ``''``."""
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text or "")
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return (text or "")[:10] if re.match(r"20\d{2}-\d{2}-\d{2}", text or "") else ""


def weekly_days(start: date, end: date, weekday: int = 4) -> list[date]:
    """One sampled day a week (Friday by default) -- a weekly series needs no more."""
    day = start + timedelta(days=(weekday - start.weekday()) % 7)
    out = []
    while day <= end:
        out.append(day)
        day += timedelta(days=7)
    return out


def pick_weekly(entries: list[dict], days: list[date]) -> list[str]:
    """For each sampled day, the sitemap/url entry dated nearest on or before it.

    Deterministic: exact date wins, else the newest entry not after the day,
    else the oldest entry after it (a forward-only archive).
    """
    dated = sorted(((e["lastmod"] or _date_in(e["loc"]), e["loc"]) for e in entries
                    if (e["lastmod"] or _date_in(e["loc"]))), key=lambda t: t[0])
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
_BODY_LIMIT = 12_000


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
    body = text_of(html or "")[:_BODY_LIMIT]
    return {"title": title, "heading": heading, "description": desc,
            "body": body, "published": published}


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def quote_of(sentence: str, start: int, end: int, max_words: int = MAX_QUOTE_WORDS) -> str:
    """A <=15-word window of one sentence that still contains the matched number."""
    words = sentence.split()
    if not words:
        return ""
    # The word that holds the match start, then a window that keeps it inside.
    pos = min(len(words) - 1, len(sentence[:start].split()))
    first = max(0, min(pos - max_words // 2, len(words) - max_words))
    return " ".join(" ".join(words[first:first + max_words]).strip(" ,;:").split())


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


def sitemap_articles(outlets, start: date, end: date, stats: dict,
                     fetcher=http_get) -> list[dict]:
    """Walk ``robots.txt`` -> sitemap index -> the child sitemap nearest each sampled week."""
    days = weekly_days(start, end)
    found: list[dict] = []
    for outlet, base in outlets.items():
        stats["requests"] += 1
        try:
            robots = fetcher(f"{base}/robots.txt", timeout=30).decode("utf-8", "replace")
        except Exception as exc:                              # noqa: BLE001
            stats["sitemaps"].append({"outlet": outlet, "status": "failed",
                                      "reason": str(exc)[:160]})
            continue
        urls = robots_sitemaps(robots)
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
            entries = parsed["entries"]
            if parsed["kind"] == "sitemapindex":
                child_locs += pick_weekly(entries, days)
            else:
                found += [{"outlet": outlet, "url": e["loc"], "published": "",
                           "title": "", "text": ""} for e in entries
                          if _HRC_CUE.search(e["loc"]) or _BDI_CUE.search(e["loc"])]
        stats["sitemaps"].append({"outlet": outlet, "index": urls[0],
                                  "status": "ok" if child_locs else "index-only",
                                  "children": len(child_locs)})
        for child in child_locs:
            stats["requests"] += 1
            try:
                payload = fetcher(child, timeout=60)
            except Exception as exc:                          # noqa: BLE001
                stats["sitemaps"].append({"outlet": outlet, "child": child,
                                          "status": "failed", "reason": str(exc)[:160]})
                continue
            for entry in parse_sitemap(payload)["entries"]:
                if _HRC_CUE.search(entry["loc"]) or _BDI_CUE.search(entry["loc"]):
                    found.append({"outlet": outlet, "url": entry["loc"],
                                  "published": entry["lastmod"], "title": "", "text": ""})
    return found


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
    out = Path(args.out)
    written = write_csv(out / "news_price_points.csv", CSV_COLUMNS, rows)
    print(f"news: {stats}")
    print(f"wrote {written} rows -> {out / 'news_price_points.csv'}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
