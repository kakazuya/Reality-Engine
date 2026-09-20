"""News extractor: structured extraction + importance ranking + brief builder.

Pure text processing over already-ingested news rows (Tier-0 news-feed v1):
no DB access, no network, no synthesis. Fail-closed — a record that is not a
dict, or carries no title/text, yields an empty STRUCTURE (category ``other``,
severity ``LOW``) plus a log line, never invented content.

Severity is NOT re-derived here: it delegates to
``news_explainer._severity_for_title`` / ``KEYWORD_SEVERITY`` so the whole
pipeline shares one severity vocabulary.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from reality_engine.processing.news_explainer import (
    KEYWORD_SEVERITY,
    _severity_for_title,
)

logger = logging.getLogger("reality_engine.news_extractor")

# Category vocabulary; ``other`` is the fallback and is never keyword-matched.
CATEGORIES: tuple = (
    "results",
    "orders_deals",
    "ratings",
    "management",
    "legal_regulatory",
    "policy_macro",
    "markets",
    "other",
)

# Ordered first-match-wins keyword map: the first category (in dict order)
# whose keyword occurs in the lowercased title+text claims the item.
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "results": [
        "q1", "q2", "q3", "q4", "profit", "revenue", "pat", "earnings",
        "margin", "beats", "misses",
    ],
    "orders_deals": [
        "order", "contract", "tender", "acquisition", "stake", "bulk deal",
        "block deal", "buyback", "merger", "demerger",
    ],
    "ratings": [
        "upgrade", "downgrade", "target price", "rating", "brokerage",
    ],
    "management": [
        "ceo", "cfo", "resign", "appoint", "md ", "kmp",
    ],
    "legal_regulatory": [
        "sebi", "nclt", "penalty", "probe", "investigation", "raid", "court",
        "tax notice", "fine",
    ],
    "policy_macro": [
        "rbi", "budget", "gst", "tariff", "duty", "subsidy", "pli", "policy",
        "inflation", "cpi", "wpi", "repo rate", "fiscal",
    ],
    "markets": [
        "sensex", "nifty", "fii", "dii", "rupee", "crude", "gold", "ipo",
        "listing",
    ],
}

# Category bonus in the importance score.
_PRIORITY_CATEGORIES = frozenset(("results", "orders_deals", "legal_regulatory"))

# Severity weights (mirrors news_explainer's HIGH > MEDIUM > LOW ranking).
_SEV_WEIGHT: Dict[str, int] = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

_MAX_NUMBERS = 5
_MAX_SCORE_NUMBERS = 3

_PCT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
_RUPEE_RE = re.compile(
    r"(?<![A-Za-z])(?:₹|Rs\.?|INR)(?![A-Za-z])\s*"
    r"([\d,]*\d(?:\.\d+)?)\s*(crore|cr|bn|lakh|lk|mn)?",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r"(?<![\d,])\d{2,6}(?:\.\d+)?(?![\d,])")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SYMBOL_SPLIT_RE = re.compile(r"[,;|/\s]+")

# Record key fallbacks (tolerant contract: the RSS ingestion shape may vary).
_TITLE_KEYS = ("title", "headline", "subject")
_TEXT_KEYS = ("text", "summary", "description", "content", "body")
_DATE_KEYS = ("published_date", "pubDate", "pub_date", "date", "doc_date")
_SOURCE_KEYS = ("source_type", "source", "feed", "publisher")
_SYMBOL_KEYS = ("symbols", "symbol", "tickers", "nse_symbols")


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _first_str(rec: Dict[str, Any], keys: tuple) -> str:
    """First non-empty string among ``keys`` (whitespace-trimmed), else ''."""
    for key in keys:
        value = rec.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _symbols(rec: Dict[str, Any]) -> List[str]:
    """Normalized, de-duplicated, order-preserving ticker list from the row."""
    raw: Any = None
    for key in _SYMBOL_KEYS:
        if rec.get(key) not in (None, "", [], ()):
            raw = rec.get(key)
            break
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = _SYMBOL_SPLIT_RE.split(raw)
    elif isinstance(raw, (list, tuple, set, frozenset)):
        parts = [str(p) for p in raw]
    else:
        parts = []
    out: List[str] = []
    for part in parts:
        sym = str(part).strip().upper()
        if sym and sym not in out:
            out.append(sym)
    return out


def _normalize_date(value: Any) -> Optional[str]:
    """ISO date prefix, else RFC-822 (RSS ``pubDate``) -> YYYY-MM-DD, else raw."""
    text = str(value or "").strip()
    if not text:
        return None
    m = _ISO_DATE_RE.search(text)
    if m:
        return m.group(0)
    try:
        parsed = parsedate_to_datetime(text)
        if parsed is not None:
            return parsed.date().isoformat()
    except (TypeError, ValueError):
        pass
    return text


# ---------------------------------------------------------------------------
# Category + numbers
# ---------------------------------------------------------------------------

def classify_category(text: Any) -> str:
    """First category (dict order) with a keyword hit in lowercased ``text``."""
    blob = str(text or "").lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in blob:
                return category
    return "other"


def extract_numbers(text: Any) -> Dict[str, List[str]]:
    """Percentages, rupee amounts and standalone price levels from ``text``.

    Percent/rupee spans are blanked before the price-level scan so a currency
    figure or a percentage is not also reported as a bare price level. Each
    list is de-duplicated, order-preserving and capped at 5.
    """
    blob = str(text or "")
    percentages: List[str] = []
    rupee_amounts: List[str] = []

    def _add(target: List[str], value: str) -> None:
        if value not in target and len(target) < _MAX_NUMBERS:
            target.append(value)

    def _blank(match: "re.Match") -> str:
        return " " * (match.end() - match.start())

    for m in _PCT_RE.finditer(blob):
        _add(percentages, re.sub(r"\s+", "", m.group(0)))

    masked = _PCT_RE.sub(_blank, blob)

    def _rupee(match: "re.Match") -> str:
        amount = match.group(1).strip(",")
        unit = (match.group(2) or "").lower()
        _add(rupee_amounts, f"₹{amount} {unit}".strip() if unit else f"₹{amount}")
        return " " * (match.end() - match.start())

    masked = _RUPEE_RE.sub(_rupee, masked)

    price_levels: List[str] = []
    for m in _PRICE_RE.finditer(masked):
        _add(price_levels, m.group(0))

    return {
        "percentages": percentages,
        "rupee_amounts": rupee_amounts,
        "price_levels": price_levels,
    }


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _empty_item(title: str = "", source_type: str = "") -> Dict[str, Any]:
    return {
        "symbols": [],
        "category": "other",
        "severity": "LOW",
        "numbers": {"percentages": [], "rupee_amounts": [], "price_levels": []},
        "title": title,
        "published_date": None,
        "source_type": source_type,
    }


def extract_item(record: Any) -> Dict[str, Any]:
    """Structure one news row -> {symbols, category, severity, numbers, ...}.

    Fail-closed: a non-dict record, or one with neither title nor text,
    returns the empty structure + a log line. Never raises.
    """
    try:
        rec: Dict[str, Any] = record if isinstance(record, dict) else {}
        title = _first_str(rec, _TITLE_KEYS)
        text = _first_str(rec, _TEXT_KEYS)
        source_type = _first_str(rec, _SOURCE_KEYS)
        if not title and not text:
            logger.warning("extract_item: empty record (%r) -> empty item", record)
            return _empty_item(source_type=source_type)

        # Feed rows often carry text == "title :: summary"; avoid doubling it.
        if title and text.startswith(title):
            blob = text.strip()
        else:
            blob = f"{title} {text}".strip()
        return {
            "symbols": _symbols(rec),
            "category": classify_category(blob),
            # Single severity vocabulary: delegated to news_explainer.
            "severity": _severity_for_title(title or text),
            "numbers": extract_numbers(blob),
            "title": title or text,
            "published_date": _normalize_date(_first_str(rec, _DATE_KEYS)),
            "source_type": source_type,
        }
    except Exception as e:  # fail-closed: never raise into the caller
        logger.warning("extract_item failed (%s) -> empty item", e)
        return _empty_item()


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _number_count(item: Dict[str, Any]) -> int:
    numbers = item.get("numbers")
    if not isinstance(numbers, dict):
        return 0
    total = 0
    for key in ("percentages", "rupee_amounts", "price_levels"):
        value = numbers.get(key)
        if isinstance(value, (list, tuple)):
            total += len(value)
    return total


def score_item(item: Any) -> int:
    """Importance score: severity weight*2 + symbol + numbers + category bonus."""
    if not isinstance(item, dict):
        return 0
    severity = str(item.get("severity") or "LOW").upper()
    score = _SEV_WEIGHT.get(severity, _SEV_WEIGHT["LOW"]) * 2
    if item.get("symbols"):
        score += 1
    score += min(_number_count(item), _MAX_SCORE_NUMBERS)
    if item.get("category") in _PRIORITY_CATEGORIES:
        score += 1
    return score


def rank_importance(items: Any) -> List[Dict[str, Any]]:
    """Stable sort of extracted items by descending importance score.

    Non-dict entries are dropped with a log line (fail-closed); equal scores
    keep their incoming order.
    """
    if not items:
        return []
    try:
        rows = [it for it in items if isinstance(it, dict)]
        dropped = len(list(items)) - len(rows)
        if dropped:
            logger.warning("rank_importance: dropped %d non-dict item(s)", dropped)
        return sorted(rows, key=score_item, reverse=True)
    except Exception as e:
        logger.warning("rank_importance failed (%s) -> empty list", e)
        return []


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------

def _brief_date(items: List[Dict[str, Any]]) -> str:
    """Newest published_date (ISO-comparable), else today."""
    dates = sorted(
        str(it.get("published_date"))
        for it in items
        if _ISO_DATE_RE.fullmatch(str(it.get("published_date") or ""))
    )
    if dates:
        return dates[-1]
    return date.today().isoformat()


def _brief_line(item: Dict[str, Any]) -> str:
    symbols = item.get("symbols") or []
    tag = ", ".join(str(s) for s in symbols) if symbols else "-"
    title = str(item.get("title") or "").strip() or "(untitled)"
    severity = str(item.get("severity") or "LOW").upper()
    source = str(item.get("source_type") or "").strip() or "unknown"
    pub = str(item.get("published_date") or "").strip() or "n/a"
    return f"- [{tag}] {title} ({severity}) — {source} {pub}"


def build_brief(items: Any, top_n: int = 15) -> str:
    """Markdown brief: header (date + per-category counts) then category sections.

    ``items`` are ranked internally (``rank_importance``) and truncated to
    ``top_n``; counts and the tagged-symbol total describe what is shown.
    Empty/degenerate input -> header-only brief.
    """
    try:
        ranked = rank_importance(items)[: max(int(top_n), 0)]
    except Exception as e:
        logger.warning("build_brief ranking failed (%s) -> header-only", e)
        ranked = []

    by_category: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORIES}
    for item in ranked:
        category = item.get("category")
        if category not in by_category:
            category = "other"
        by_category[category].append(item)

    counts = ", ".join(
        f"{c} {len(by_category[c])}" for c in CATEGORIES if by_category[c]
    ) or "no items"
    symbols_tagged = sum(len(it.get("symbols") or []) for it in ranked)

    lines = [
        f"# Market News Brief — {_brief_date(ranked)}",
        f"Items: {len(ranked)} | Categories: {counts} | Symbols tagged: {symbols_tagged}",
    ]
    for category in CATEGORIES:
        rows = by_category[category]
        if not rows:
            continue
        lines.append("")
        lines.append(f"## {category}")
        lines.extend(_brief_line(it) for it in rows)
    return "\n".join(lines) + "\n"
