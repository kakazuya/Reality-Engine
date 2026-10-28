"""IMD weekly state-level rainfall departure % (free, public bulletins, monsoon weeks).

Why: rainfall drives rural demand and 4 master-bank cases name it directly.
IMD publishes a weekly bulletin every Thursday during the monsoon with a
state/region table: actual, normal and the departure % from normal. The weekly
cadence is exactly what Shivam ruled sufficient (2026-10-29), and it is the
only free point-in-time rainfall series that is not a model reanalysis.

Source
------
India Meteorological Department public bulletin pages on ``mausam.imd.gov.in``
(and ``imd.gov.in`` as a second listing). Bulletin URLs are DISCOVERED from
those pages -- the week-ending date in the link text or href names the week --
and never guessed; a week with no link is reported missing.

What is stored
--------------
One row per state per week: ``departure_pct`` (negative = deficient), the
week-ending date, ``known_at`` (the bulletin's issue date, else the Thursday
after the week ends). PDF bulletins are read with PyMuPDF when present and the
same table parser runs on the extracted text, so a text fixture covers both.

Usage:
    python -m reality_engine.scripts.fetch_imd_rainfall --dry-run
    python -m reality_engine.scripts.fetch_imd_rainfall --from 2019-06-01 --to 2026-09-30
    python -m reality_engine.scripts.fetch_imd_rainfall --list-links
"""

from __future__ import annotations

import argparse
import re
from datetime import date, timedelta
from pathlib import Path

from reality_engine.scripts.series_common import (
    anchors,
    html_rows,
    http_get,
    num,
    plan_minutes,
    text_of,
    text_rows,
    write_csv,
)

DEFAULT_OUT = r"D:\RealityEngine\raw\input_cost_series"
LANDING_URLS = (
    "https://mausam.imd.gov.in/",
    "https://mausam.imd.gov.in/imd_latest/contents/rainfall.php",
    "https://www.imd.gov.in/",
)
#: Year/archive pages followed from a landing page, capped so a run stays bounded.
MAX_ARCHIVE_PAGES = 8
MONSOON_MONTHS = (6, 7, 8, 9)
#: IMD weeks run Thursday-Wednesday; the bulletin is issued the Thursday after.
BULLETIN_LAG_DAYS = 1

CSV_COLUMNS = ("state", "week_end", "departure_pct", "known_at",
               "source_url", "pit_conf", "source")
SOURCE = "imd_weekly_rainfall"

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MNAME = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_WEEK_DOTTED = re.compile(
    r"(?i)week\s*(?:ending|ended)?\s*:?\s*(\d{1,2})[./-](\d{1,2})[./-](20\d{2})")
_WEEK_NAMED = re.compile(
    rf"(?i)week\s*(?:ending|ended)?\s*:?\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MNAME}\.?,?\s*(20\d{{2}})")
_BULLETIN_DATED = re.compile(
    rf"(?i)\b(?:dated|issued on|issue date)\s*:?\s*(\d{{1,2}})(?:st|nd|rd|th)?\s*"
    rf"{_MNAME}\.?,?\s*(20\d{{2}})")
_ANCHOR_DATE = re.compile(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})")
_ANCHOR_DMY = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)")
_DEP_HEADER = re.compile(r"(?i)\bdeparture\b|\bdep\.?\b|\banomaly\b|\bdeviation\b")
_STATE_HEADER = re.compile(r"(?i)^\s*(states?|state\s*/\s*ut|sub.?division|region|"
                           r"met.?sub.?division|homogeneous)s?\b")
#: "rainfall" is the usual title; "weekly" catches the weekly weather report,
#: whose rainfall table the parser then has to recognise or refuse.
_RAIN_HINT = re.compile(r"(?i)rain|weekly")
#: A week-numbered file (``w39_2026.html``) is a bulletin, not an archive page.
_WEEK_NUMBER = re.compile(r"(?i)week\s*[-_]?\s*\d{1,2}\b|[/_-]w\d{1,2}[_./-]")
_ARCHIVE_HINT = re.compile(r"(?i)(archive|monsoon|rainfall|weekly)")
_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z .&()'/-]{2,44}?)\s+((?:-?\d[\d., ]*)+)$")
_HEADER_WORDS = {"state", "states", "state ut", "sub division", "subdivisions", "region",
                 "regions", "met subdivision", "homogeneous region", "departure",
                 "actual", "normal", "total"}


# ---------------------------------------------------------------------------
# Identifiers -- pure functions
# ---------------------------------------------------------------------------
def _iso(year, month, day) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except (TypeError, ValueError):
        return None


def week_end_in(text: str) -> str | None:
    """``'Week ending 30.09.2026'`` / ``'week ending 30 September, 2026'`` -> ISO date."""
    m = _WEEK_DOTTED.search(text or "")
    if m:
        return _iso(m.group(3), m.group(2), m.group(1))
    m = _WEEK_NAMED.search(text or "")
    if m:
        return _iso(m.group(3), _MONTHS[m.group(2).lower()[:3]], m.group(1))
    return None


def bulletin_date(text: str, week_end: str) -> tuple[str, float]:
    """``(known_at, pit_conf)``: the printed issue date, else the Thursday after the week ended."""
    m = _BULLETIN_DATED.search(text or "")
    if m:
        iso = _iso(m.group(3), _MONTHS[m.group(2).lower()[:3]], m.group(1))
        if iso:
            return iso, 1.0
    try:
        return (date.fromisoformat(week_end) + timedelta(days=BULLETIN_LAG_DAYS)).isoformat(), 0.85
    except ValueError:
        return "", 0.0


def clean_state(name: str) -> str:
    text = re.sub(r"[^A-Za-z .&()/'-]", " ", name or "")
    return re.sub(r"\s+", " ", text).strip(" .-").lower().title()


# ---------------------------------------------------------------------------
# Table parser -- one contract for HTML rows and PDF text lines
# ---------------------------------------------------------------------------
def _rows_from_html(payload: str) -> tuple[list[list[str]], str]:
    return html_rows(payload), text_of(payload)


def _rows_from_text(payload: str) -> tuple[list[list[str]], str]:
    rows = []
    for line in (payload or "").splitlines():
        m = _LINE_RE.match(line.strip())
        if m:
            rows.append([m.group(1).strip()] + m.group(2).split())
    return (rows or text_rows(payload)), payload


def parse_rows(rows: list[list[str]], from_html: bool) -> list[dict]:
    """State rows from cell lists. HTML uses the header row; text uses the last number.

    Refuses (``[]``) when the header or a plausible state count is missing: a
    departure table read off the wrong column is worse than no table.
    """
    out: list[dict] = []
    if from_html:
        header_at = dep_col = name_col = None
        for i, row in enumerate(rows):
            joined = " | ".join(row)
            if _DEP_HEADER.search(joined) and _STATE_HEADER.search(joined):
                header_at = i
                dep_col = next(j for j, c in enumerate(row) if _DEP_HEADER.search(c))
                name_col = next(j for j, c in enumerate(row) if _STATE_HEADER.search(c))
                break
        if header_at is None:
            return []
        for row in rows[header_at + 1:]:
            if max(dep_col, name_col) >= len(row):
                continue
            value = num(row[dep_col])
            if value is None or not -100.0 <= value <= 100.0:
                continue
            name = clean_state(row[name_col])
            if name and name.lower() not in _HEADER_WORDS:
                out.append({"state": name, "departure_pct": value})
        return out if len(out) >= 5 else []
    for row in rows:
        if len(row) < 2:
            continue
        numbers = [v for v in (num(c) for c in row[1:]) if v is not None]
        if not numbers:
            continue
        value = numbers[-1]
        if not -100.0 <= value <= 100.0:
            continue
        name = clean_state(row[0])
        if len(name) < 3 or name.lower() in _HEADER_WORDS:
            continue
        out.append({"state": name, "departure_pct": value})
    return out if len(out) >= 5 else []


def parse_bulletin(payload: bytes | str, url: str, fallback_week_end: str = "") -> dict:
    """One bulletin -> ``{'status', 'rows', 'info'}`` with one row per state."""
    raw = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else (payload or "")
    head = raw.lstrip()[:400].lower()
    is_html = head.startswith("<!doctype") or head.startswith("<html") or "<table" in raw[:8000].lower()
    rows_in, plain = _rows_from_html(raw) if is_html else _rows_from_text(raw)
    if not rows_in:
        return {"status": "failed", "reason": "no table rows found", "rows": [], "info": {}}
    week_end = week_end_in(plain) or fallback_week_end
    if not week_end:
        return {"status": "refused", "reason": "week-ending date unreadable",
                "rows": [], "info": {}}
    states = parse_rows(rows_in, is_html)
    if not states:
        return {"status": "refused", "reason": "state/departure table not recognised",
                "rows": [], "info": {"format": "html" if is_html else "text"}}
    known_at, conf = bulletin_date(plain, week_end)
    if not known_at:
        return {"status": "refused", "reason": "bulletin date unreadable", "rows": [], "info": {}}
    out = [{"state": s["state"], "week_end": week_end,
            "departure_pct": s["departure_pct"], "known_at": known_at,
            "source_url": url, "pit_conf": conf, "source": SOURCE} for s in states]
    return {"status": "ok", "reason": None, "rows": out,
            "info": {"format": "html" if is_html else "text", "states": len(out),
                     "week_end": week_end, "known_at": known_at, "pit_conf": conf}}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def date_in_link(text: str) -> str | None:
    """The week-ending date a bulletin link or its label carries, or ``None``.

    Tries the ``week ending ...`` wording, then an ISO date, then
    ``dd.mm.yyyy`` (how the IMD archive names its PDFs).
    """
    iso = week_end_in(text)
    if iso:
        return iso
    m = _ANCHOR_DATE.search(text or "")
    if m:
        return _iso(m.group(1), m.group(2), m.group(3))
    m = _ANCHOR_DMY.search(text or "")
    if m and 1 <= int(m.group(2)) <= 12:
        return _iso(m.group(3), m.group(2), m.group(1))
    return None


def discover_bulletins(pages: list[tuple[str, str]]) -> dict:
    """Listing pages -> ``{week_end: url}``. Only links that name rainfall and a date."""
    found: dict[str, str] = {}
    for page_url, html in pages:
        for url, text in anchors(html, page_url):
            if not _RAIN_HINT.search(f"{text} {url}") or url.lower().endswith((".zip", ".xls", ".xlsx")):
                continue
            week_end = date_in_link(text) or date_in_link(url)
            if week_end and week_end not in found:
                found[week_end] = url
    return dict(sorted(found.items()))


def archive_pages(html: str, page_url: str, limit: int = MAX_ARCHIVE_PAGES) -> list[str]:
    out: list[str] = []
    for url, text in anchors(html, page_url):
        if url in out or not url.startswith("http"):
            continue
        if not _ARCHIVE_HINT.search(f"{text} {url}") or url.lower().endswith((".pdf", ".zip")):
            continue
        if date_in_link(text) or date_in_link(url):
            continue                                   # a bulletin, not an archive page
        if _WEEK_NUMBER.search(f"{text} {url}"):
            continue
        out.append(url)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
def monsoon_weeks(start: date, end: date) -> list[date]:
    """The Wednesday ending each monsoon week inside ``start..end``."""
    day = start + timedelta(days=(2 - start.weekday()) % 7)      # 2 = Wednesday
    out = []
    while day <= end:
        if day.month in MONSOON_MONTHS:
            out.append(day)
        day += timedelta(days=7)
    return out


def pdf_text(payload: bytes) -> str:
    if payload[:4] != b"%PDF":
        return ""
    try:
        import pymupdf                                            # noqa: PLC0415
        with pymupdf.open(stream=payload, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception:                                             # noqa: BLE001
        return ""


def fetch_weeks(out: Path, start: date, end: date, landing: tuple[str, ...],
                ) -> tuple[list[dict], dict]:
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pages: list[tuple[str, str]] = []
    info: dict = {"landing": [], "requests": 0, "weeks_fetched": 0,
                  "weeks_missing": [], "failed": []}
    archive_budget = MAX_ARCHIVE_PAGES
    for url in landing:
        info["requests"] += 1
        try:
            html = http_get(url, timeout=60).decode("utf-8", "replace")
        except Exception as exc:                                  # noqa: BLE001
            info["landing"].append({"url": url, "status": "failed", "reason": str(exc)[:160]})
            continue
        info["landing"].append({"url": url, "status": "ok", "bytes": len(html)})
        pages.append((url, html))
        for extra in archive_pages(html, url, limit=archive_budget):
            if archive_budget <= 0:
                break
            archive_budget -= 1
            info["requests"] += 1
            try:
                sub = http_get(extra, timeout=60).decode("utf-8", "replace")
            except Exception as exc:                              # noqa: BLE001
                info["landing"].append({"url": extra, "status": "failed",
                                        "reason": str(exc)[:160]})
                continue
            info["landing"].append({"url": extra, "status": "ok", "bytes": len(sub)})
            pages.append((extra, sub))

    links = discover_bulletins(pages)
    info["links_found"] = len(links)
    rows: list[dict] = []
    for week_end in monsoon_weeks(start, end):
        iso = week_end.isoformat()
        url = links.get(iso)
        if not url:
            info["weeks_missing"].append(iso)
            continue
        info["requests"] += 1
        try:
            payload = http_get(url, timeout=120)
        except Exception as exc:                                  # noqa: BLE001
            info["failed"].append({"week_end": iso, "reason": str(exc)[:160]})
            continue
        suffix = ".pdf" if payload[:4] == b"%PDF" else ".html"
        (raw_dir / f"imd_rainfall_{iso}{suffix}").write_bytes(payload)
        body = pdf_text(payload)
        parsed = parse_bulletin(body if body else payload, url, fallback_week_end=iso)
        if parsed["status"] != "ok":
            info["failed"].append({"week_end": iso, "status": parsed["status"],
                                   "reason": parsed.get("reason")})
            continue
        rows += parsed["rows"]
        info["weeks_fetched"] += 1
        print(f"  {iso}: {len(parsed['rows'])} states, known_at {parsed['info']['known_at']}")
    return rows, info


def plan(start: date, end: date) -> dict:
    weeks = len(monsoon_weeks(start, end))
    landings = len(LANDING_URLS) + MAX_ARCHIVE_PAGES
    requests = landings + weeks
    return {
        "monsoon_weeks": weeks,
        "landing_pages_max": landings,
        "requests_p50": requests,
        "requests_max": requests + weeks // 10,
        "est_minutes_p50": plan_minutes(requests),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--from", dest="start", default="2019-06-01")
    ap.add_argument("--to", dest="end", default=date.today().isoformat())
    ap.add_argument("--list-links", action="store_true",
                    help="print the discovered bulletins and exit (no parsing, no writes)")
    ap.add_argument("--dry-run", action="store_true", help="plan only: no network, no writes")
    args = ap.parse_args(argv)

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    for key, value in plan(start, end).items():
        print(f"  {key:20} {value}")
    if args.dry_run:
        print("dry-run: no request made")
        return 0

    if args.list_links:
        pages: list[tuple[str, str]] = []
        for url in LANDING_URLS:
            try:
                pages.append((url, http_get(url, timeout=60).decode("utf-8", "replace")))
            except Exception as exc:                              # noqa: BLE001
                print(f"  {url}: {str(exc)[:160]}")
        for week_end, url in discover_bulletins(pages).items():
            print(f"  {week_end}  {url}")
        return 0

    out = Path(args.out)
    rows, info = fetch_weeks(out, start, end, LANDING_URLS)
    print(f"imd: {info}")
    written = write_csv(out / "imd_rainfall_departure.csv", CSV_COLUMNS, rows)
    states = sorted({r["state"] for r in rows})
    print(f"wrote {written} rows, {len(states)} states -> "
          f"{out / 'imd_rainfall_departure.csv'}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
