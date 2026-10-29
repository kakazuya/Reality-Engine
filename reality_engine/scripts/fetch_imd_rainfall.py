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
import csv
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
#: Live rainfall pages (2026-10-29). The old ``imd_latest/contents/*rainfall*``
#: and ``imd.gov.in`` URLs this module used to open are gone (404 / timeout);
#: each live page carries a direct link to the table it renders
#: (``../Rainfall/<NAME>_COUNTRY_INDIA_c*.pdf``), so links are still discovered,
#: never guessed.
LANDING_URLS = (
    "https://mausam.imd.gov.in/responsive/rainfallinformation.php",
    "https://mausam.imd.gov.in/responsive/rainfall_statistics.php?PAGE=7",
    "https://mausam.imd.gov.in/responsive/rainfall_statistics.php?PAGE=5",
    "https://mausam.imd.gov.in/responsive/rainfall_statistics.php?PAGE=3",
)
#: The weekly departure tables: "SUBDIVISION_RAINFALL_DEPARTUREWEEKLY_..." is the
#: regional table IMD prints every Thursday (state-like regions with one column
#: per week); the district file is the same shape at district level and is only
#: used when the subdivision file is missing.
WEEKLY_TABLE_RE = re.compile(r"(?i)rainfall_departureweekly.*\.pdf$")
TABLE_SUB_RE = re.compile(r"(?i)subdivision")
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
_DATE_COL = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)")
#: The week-column header of the departure table: two or more dates in a row.
_DATE_SEQ_RE = re.compile(
    r"((?:\d{1,2}[-./]\d{1,2}[-./]20\d{2}\s+){1,}\d{1,2}[-./]\d{1,2}[-./]20\d{2})")
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


def weekly_tables(pages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """``(url, 'subdivision'|'district')`` weekly departure tables named by the pages."""
    found: list[tuple[str, str]] = []
    for page_url, html in pages:
        for url, _text in anchors(html, page_url):
            if not WEEKLY_TABLE_RE.search(url.rsplit("/", 1)[-1]):
                continue
            kind = "subdivision" if TABLE_SUB_RE.search(url) else "district"
            if not any(kind == k for _, k in found):
                found.append((url, kind))
    # The subdivision table first: the district table is 30 pages of the same
    # numbers at a granularity a state-level series does not want.
    return sorted(found, key=lambda item: item[1] != "subdivision")


_NUM_TOKEN = re.compile(r"^-?\d+(?:\.\d+)?$")


def parse_week_table(text: str) -> dict:
    """``Week by week departures`` table -> one row per region per week.

    The printed header carries the week-ending dates and every region line
    carries one departure per week, in that order. The PDF's text layer arrives
    as one token stream, so rows are rebuilt from tokens (a serial number, the
    region's words, then exactly as many numbers as the header has weeks) and a
    line that does not add up is skipped, never padded or shifted.
    """
    stream = re.sub(r"\s+", " ", text or "")
    headers = list(_DATE_SEQ_RE.finditer(stream))
    if not headers:
        return {"status": "refused", "reason": "no week-ending header", "weeks": [], "rows": []}
    rows: dict[tuple[str, str], dict] = {}
    weeks: list[str] = []
    for k, header in enumerate(headers):
        # Every page of the table repeats the header, so each block is parsed
        # against its own date list; the "Period: a To b" line is a two-date
        # block whose rows never match and is skipped by the length check.
        block = [_iso(m.group(3), m.group(2), m.group(1))
                 for m in _DATE_COL.finditer(header.group(0))]
        body_end = headers[k + 1].start() if k + 1 < len(headers) else len(stream)
        tokens = stream[header.end():body_end].split()
        weeks = weeks or block
        i = 0
        while i < len(tokens):
            if not tokens[i].isdigit():
                i += 1
                continue
            j, name = i + 1, []
            while j < len(tokens) and not _NUM_TOKEN.match(tokens[j]):
                name.append(tokens[j])
                j += 1
            values = []
            while j < len(tokens) and _NUM_TOKEN.match(tokens[j]) and len(values) < len(block):
                values.append(tokens[j])
                j += 1
            if not name or len(values) != len(block):
                i += 1
                continue
            label = clean_state(" ".join(name))
            if len(label) < 3 or label.lower() in _HEADER_WORDS:
                i += 1
                continue
            for week, raw in zip(block, values):
                value = num(raw)
                if value is not None and -100.0 <= value <= 2000.0:
                    rows[(label, week)] = {"state": label, "week_end": week,
                                           "departure_pct": value}
            i = j
    if len(rows) < 5:
        return {"status": "refused", "reason": "week table rows not recognised",
                "weeks": weeks, "rows": []}
    return {"status": "ok", "reason": None, "weeks": weeks,
            "rows": sorted(rows.values(), key=lambda r: (r["week_end"], r["state"]))}


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
                  "weeks_missing": [], "failed": [], "weekly_tables": []}
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
    first, last = start.isoformat(), end.isoformat()
    for url, kind in weekly_tables(pages)[:1]:       # subdivision first, district as fallback
        info["requests"] += 1
        try:
            payload = http_get(url, timeout=120)
        except Exception as exc:                                  # noqa: BLE001
            info["failed"].append({"weekly_table": url, "reason": str(exc)[:160]})
            continue
        suffix = ".pdf" if payload[:4] == b"%PDF" else ".html"
        (raw_dir / f"imd_weekly_{kind}{suffix}").write_bytes(payload)
        body = pdf_text(payload) or payload.decode("utf-8", "replace")
        parsed = parse_week_table(body)
        info["weekly_tables"].append({"url": url, "kind": kind,
                                      "weeks": parsed["weeks"], "rows": len(parsed["rows"]),
                                      "status": parsed["status"]})
        print(f"  weekly table {kind}: {parsed['status']}, {len(parsed['rows'])} rows, "
              f"weeks {parsed['weeks'][:1]}..{parsed['weeks'][-1:]}")
        for row in parsed["rows"]:
            if not first <= row["week_end"] <= last:
                continue
            known_at, conf = bulletin_date("", row["week_end"])
            rows.append({"state": row["state"], "week_end": row["week_end"],
                         "departure_pct": row["departure_pct"], "known_at": known_at,
                         "source_url": url, "pit_conf": conf, "source": SOURCE})
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


def merge_previous(path: Path, rows: list[dict]) -> list[dict]:
    """Rows already in the CSV plus this run's, one per (state, week_end).

    The live table carries only the weeks of the current month, so a run would
    otherwise overwrite last month's weeks with nothing added. Keeping what an
    earlier run published is how this series accumulates a history the source
    itself does not archive; a re-fetched week simply replaces its own row.
    """
    merged: dict[tuple[str, str], dict] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for old in csv.DictReader(f):
                if old.get("state") and old.get("week_end"):
                    merged[(old["state"], old["week_end"])] = old
    for row in rows:
        merged[(row["state"], row["week_end"])] = {k: row.get(k, "") for k in CSV_COLUMNS}
    return sorted(merged.values(), key=lambda r: (r["week_end"], r["state"]))


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
        for url, kind in weekly_tables(pages):
            print(f"  weekly table ({kind})  {url}")
        for week_end, url in discover_bulletins(pages).items():
            print(f"  {week_end}  {url}")
        return 0

    out = Path(args.out)
    rows, info = fetch_weeks(out, start, end, LANDING_URLS)
    info["weeks_missing"] = f"{len(info['weeks_missing'])} weeks not published by the source"
    print(f"imd: {info}")
    path = out / "imd_rainfall_departure.csv"
    merged = merge_previous(path, rows)
    written = write_csv(path, CSV_COLUMNS, merged)
    states = sorted({r["state"] for r in merged})
    print(f"wrote {written} rows, {len(states)} states -> {path}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
