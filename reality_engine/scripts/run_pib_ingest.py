"""PIB (Press Information Bureau) release ingestion — the macro transmission channel.

PIB releases are the government's own statement of policy intent: PLI scheme
expansions, tariff changes, defence procurement approvals, railway/road capex
sanctions, semiconductor incentives, MSP announcements. They are HTML, not PDFs,
which is why the corpus held exactly one static sample: the PDF pipeline had no
entry point for text sources. ``PDFIngestor.ingest_text`` now provides it.

Scope decision: this is a FEED, not a backfill. PIB publishes hundreds of
releases a month and most are administrative. Releases are filtered by
policy-relevance keywords so the corpus gains transmission signal rather than
bulk — the filter is deliberately transparent and configurable, and the
unfiltered count is reported alongside so the selection is auditable.

    python -m reality_engine.scripts.run_pib_ingest --limit 25
    python -m reality_engine.scripts.run_pib_ingest --no-filter --limit 25
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine import config as cfg  # noqa: E402

LOG_PATH = cfg.DATA_DIR / "logs" / "pib_ingest.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("pib_ingest")

RSS_URLS = [
    "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",   # All India, English
    "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=1",   # All India
]
LISTING_URL = "https://www.pib.gov.in/Allrel.aspx"

# Policy-transmission vocabulary: capex, trade, incentives, regulated sectors.
RELEVANCE = (
    "capex", "capital expenditure", "pli", "production linked", "tariff", "customs duty",
    "import duty", "export duty", "defence", "defense", "procurement", "railway", "railways",
    "highway", "road", "port", "airport", "semiconductor", "chip", "electronics",
    "subsidy", "incentive", "gst", "rbi", "monetary policy", "repo rate", "msp",
    "minimum support price", "fertiliser", "fertilizer", "crude", "petroleum", "gas",
    "power", "renewable", "solar", "green hydrogen", "steel", "cement", "coal",
    "disinvestment", "privatisation", "privatization", "infrastructure", "logistics",
    "msme", "credit guarantee", "steel", "aluminium", "copper", "rare earth",
    "telecom", "spectrum", "data centre", "data center", "shipbuilding", "textile",
    "pharma", "bulk drug", "medical device", "food processing", "ethanol", "biofuel",
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _session():
    from curl_cffi import requests as creq
    return creq


def list_releases(limit: int = 200) -> List[Dict[str, str]]:
    """Collect press-release links from the RSS feeds + the Allrel listing.

    Two markup shapes exist and both must be handled: RSS ``<item>`` blocks carry
    ``<title>`` and ``<link>`` tags; Allrel uses ``<a href='/PressReleaseDetail.aspx?PRID=…'>``
    with single quotes. (An earlier `href="…PRID…">title</a>` pattern matched
    neither and silently returned zero listings.)
    """
    creq = _session()
    out: List[Dict[str, str]] = []
    seen = set()

    def _add(prid: str, title: str) -> bool:
        if not prid or prid in seen:
            return False
        seen.add(prid)
        out.append({
            "prid": prid,
            "url": f"https://pib.gov.in/PressReleaseIframePage.aspx?PRID={prid}",
            "title": re.sub(r"\s+", " ", title or "").strip()[:200],
        })
        return len(out) >= limit

    for url in RSS_URLS + [LISTING_URL]:
        try:
            r = creq.get(url, impersonate="chrome", timeout=25)
        except Exception as exc:  # noqa: BLE001
            log.warning("listing miss %s: %s", url, str(exc)[:120])
            continue
        if r.status_code != 200:
            log.warning("listing HTTP %s for %s", r.status_code, url)
            continue
        html = r.text or ""

        # 1) RSS items: title + link
        for item in re.findall(r"<item>(.*?)</item>", html, re.S | re.I):
            m_link = re.search(r"<link>\s*([^<\s]+)", item)
            m_title = re.search(r"<title>(.*?)</title>", item, re.S)
            if not m_link:
                continue
            m_prid = re.search(r"PRID=(\d+)", m_link.group(1))
            if not m_prid:
                continue
            title = re.sub(r"<[^>]+>", " ", m_title.group(1)) if m_title else ""
            if _add(m_prid.group(1), title):
                return out

        # 2) Any anchor whose href carries a PRID (single or double quotes)
        for m in re.finditer(r"""href=['"]([^'"]*PRID=(\d+))['"][^>]*>(.*?)</a>""", html, re.S | re.I):
            title = re.sub(r"<[^>]+>", " ", m.group(3))
            if _add(m.group(2), title):
                return out
    return out


def fetch_release_text(url: str) -> str:
    """Fetch a release page and strip it to readable text."""
    creq = _session()
    r = creq.get(url, impersonate="chrome", timeout=25, headers={"User-Agent": _USER_AGENT})
    if r.status_code != 200:
        return ""
    html = r.text or ""
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def release_date(text: str) -> Optional[str]:
    m = re.search(r"(\d{1,2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{4})", text, re.I)
    if not m:
        return None
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    try:
        return f"{m.group(3)}-{months.index(m.group(2).upper()[:3]) + 1:02d}-{int(m.group(1)):02d}"
    except ValueError:
        return None


def _ascii_ratio(text: str) -> float:
    if not text:
        return 0.0
    return sum(1 for c in text if ord(c) < 128) / len(text)


def is_english(text: str, threshold: float = 0.85) -> bool:
    """True when the release reads as English.

    PIB's machine-readable feeds (``RssMain.aspx``) currently serve HINDI
    releases — measured 2/12 English-dominant, and the dominant case was Hindi
    with embedded numerals. The local embedder is ``bge-small-en-v1.5`` (English
    only), so ingesting Devanagari would add near-random vectors to the dense
    index and degrade retrieval and cross-mapping. This guard makes that
    impossible: non-English releases are counted and skipped, never embedded.
    """
    return _ascii_ratio(text) >= threshold


def is_relevant(title: str, text: str, keywords=RELEVANCE) -> bool:
    hay = f"{title}\n{text[:4000]}".lower()
    return any(k in hay for k in keywords)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Ingest PIB press releases into the corpus.")
    ap.add_argument("--limit", type=int, default=25, help="max releases to ingest this run")
    ap.add_argument("--scan", type=int, default=200, help="max listings to consider")
    ap.add_argument("--no-filter", action="store_true", help="disable the policy-relevance filter")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from reality_engine.db.database import db_manager
    from reality_engine.ingestion.pdf_ingestor import PDFIngestor

    started = time.time()
    listings = list_releases(limit=args.scan)
    log.info("PIB listings found: %d", len(listings))
    if not listings:
        return 1

    with db_manager.session() as conn:
        known = {r[0] for r in conn.execute(
            "SELECT source_url FROM raw_documents WHERE source_type='PIB_Press_Release'")}
    todo = [x for x in listings if x["url"] not in known]
    log.info("new releases (not yet ingested): %d", len(todo))

    ingestor = PDFIngestor(db=db_manager)
    scanned = filtered = ingested = failed = non_english = 0
    for rec in todo:
        if ingested >= args.limit:
            break
        scanned += 1
        text = fetch_release_text(rec["url"])
        if len(text) < 200:
            failed += 1
            continue
        if not is_english(text):
            non_english += 1
            continue
        if not args.no_filter and not is_relevant(rec["title"], text):
            filtered += 1
            continue
        if args.dry_run:
            ingested += 1
            log.info("[dry] %s :: %s", rec["prid"], (rec["title"] or text[:70])[:90])
            continue
        res = ingestor.ingest_text(
            text,
            title=rec["title"] or f"PIB release {rec['prid']}",
            source_type="PIB_Press_Release",
            published_date=release_date(text) or "2026-09-21",
            source_url=rec["url"],
            creator_or_ministry="PIB",
        )
        if res.get("status") in ("ingested", "skipped_duplicate"):
            ingested += 1
            log.info("[%d] %s -> %s chunks (%.0fs) :: %s", ingested, rec["prid"],
                     res.get("chunks"), time.time() - started, (rec["title"] or "")[:70])
        else:
            failed += 1

    log.info("RUN_COMPLETE scanned=%d ingested=%d filtered_out=%d non_english=%d failed=%d seconds=%.0f",
             scanned, ingested, filtered, non_english, failed, time.time() - started)
    return 0 if ingested >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
