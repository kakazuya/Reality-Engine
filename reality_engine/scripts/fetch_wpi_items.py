"""WPI item-level monthly indices from the Office of the Economic Adviser (free, no key).

Why: 52 of the 1,073 master-bank cases name domestic input costs (steel 31,
freight 12, rainfall 4, pet coke 3, soda ash 2, ammonia 1). The world-market
series we already hold cannot stand in for them -- a domestic HRC index is not
Brent, and pet coke is not a Pink Sheet line.

Source
------
Office of the Economic Adviser, DPIIT (``eaindustry.nic.in``). Around the 14th
of every month it publishes the WPI press release (PDF or HTML) whose annexure
lists every item with its weight and its index on base 2011-12 = 100 for the
reference month. Release URLs are **discovered** from the site's own listing
pages (:func:`discover_release_links`), never hardcoded: the filenames change
every month and a stale guess fails silently.

Vintages
--------
A month is revised in the following release, so the CSV is keyed
``(series_code, date, known_at)``: one row per month per *vintage*, and a
revision is a second row carrying a later ``known_at``. Never collapse them --
the point of holding the vintage is to know what was published when.

``known_at`` is the release date printed on the release. Only when that date
cannot be read does the documented "14th of the following month" rule apply,
and then ``pit_conf`` drops to 0.8. A release whose reference month cannot be
read is refused, never dated today.

Usage:
    python -m reality_engine.scripts.fetch_wpi_items --dry-run
    python -m reality_engine.scripts.fetch_wpi_items --from 2019-01-01 --to 2026-10-31
    python -m reality_engine.scripts.fetch_wpi_items --index-url https://eaindustry.nic.in/x.asp
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from reality_engine.scripts.series_common import (
    anchors,
    html_rows,
    http_get,
    month_end,
    month_range,
    num,
    plan_minutes,
    text_of,
    text_rows,
    write_csv,
)

DEFAULT_OUT = r"D:\RealityEngine\raw\input_cost_series"
INDEX_URLS = ("https://eaindustry.nic.in/",)
#: Archive/listing pages are also *discovered* from the index page; this caps
#: how many of those are followed, so one run cannot walk the whole site.
MAX_ARCHIVE_PAGES = 3
#: The release is due on the 14th of the following month (OEA practice since 2017).
RELEASE_DAY_OF_MONTH = 14

CSV_COLUMNS = ("series_code", "date", "value", "unit", "weight",
               "known_at", "pit_conf", "source", "source_url")
SOURCE = "oea_wpi_press_release"
UNIT = "index_2011_12_100"

#: series_code -> regex over the NORMALISED item label (:func:`normalise_item`).
#: First match wins, so the specific items are declared before the groups.
#: ``wpi_steel_group`` is the "Iron & steel" sub-group, which is how "other
#: steel products" is held without inventing an average of unrelated items.
ITEM_MATCHERS: tuple[tuple[str, str], ...] = (
    ("wpi_hrc",              r"^(hot rolled coils?|hr coils?|hrc)\b"),
    ("wpi_cold_rolled",      r"^cold rolled coil"),
    ("wpi_pig_iron",         r"^pig iron"),
    ("wpi_sponge_iron",      r"^sponge iron"),
    ("wpi_coking_coal",      r"^coking coal"),
    ("wpi_non_coking_coal",  r"^non coking coal"),
    ("wpi_coal_group",       r"^coal\b"),
    ("wpi_pet_coke",         r"^(pet coke|petroleum coke|petcoke)\b"),
    ("wpi_soda_ash",         r"^soda ash"),
    ("wpi_caustic_soda",     r"^caustic soda"),
    ("wpi_ammonia",          r"^ammonia"),
    ("wpi_sulphuric_acid",   r"^(sulphuric|sulfuric) acid"),
    ("wpi_urea",             r"^urea"),
    ("wpi_dap",              r"^(dap|di ammonium phosphate|diammonium phosphate)\b"),
    ("wpi_npk",              r"^(npk|n p k)\b"),
    ("wpi_cement",           r"^cement\b"),
    ("wpi_aluminium",        r"^(aluminium|aluminum)\b"),
    ("wpi_copper",           r"^copper\b"),
    ("wpi_zinc",             r"^zinc\b"),
    ("wpi_lead",             r"^lead\b"),
    ("wpi_nickel",           r"^nickel\b"),
    ("wpi_cotton_yarn",      r"^cotton yarn"),
    ("wpi_plastics",         r"^(plastics?|polymer|polypropylene|polyethylene|polystyrene|poly vinyl|pvc)\b"),
    ("wpi_steel_group",      r"^(iron and steel|iron steel|basic metal)"),
)

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MNAME = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_MONTH_KEY_RE = re.compile(rf"(?i)\b{_MNAME}\.?\s*[,\-/ ]\s*(20\d{{2}})\b")
_YEAR_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})[-./](\d{1,2})(?!\d)")
_MONTH_YEAR_RE = re.compile(r"(?<![\d.])(\d{1,2})[-./](20\d{2})(?![\d.])")
_DATE_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)")
_DATED_WORD_RE = re.compile(
    rf"(?i)\bdated\s+(?:on\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MNAME}\.?,?\s*(20\d{{2}})")
_REF_MONTH_RE = re.compile(
    rf"(?i)\bfor\s+the\s+month\s+of\s+{_MNAME}\.?,?\s*(20\d{{2}})")
_INDEX_HEADER_RE = re.compile(r"(?i)\bindex\b|\bwpi\b")
_WEIGHT_HEADER_RE = re.compile(r"(?i)\bweight\b")
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Identifiers -- pure functions, so they are testable offline
# ---------------------------------------------------------------------------
def normalise_item(label: str) -> str:
    """``'Angles, channels & sections'`` -> ``'angles channels and sections'``."""
    text = (label or "").lower().replace("&", " and ")
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text)).strip()


def match_item(label: str) -> str | None:
    """Map one release row's item label to our series code, or ``None``."""
    norm = normalise_item(label)
    for code, pattern in ITEM_MATCHERS:
        if norm and re.match(pattern, norm):
            return code
    return None


def month_in(text: str) -> str | None:
    """First ``YYYY-MM`` mentioned in ``text`` (``'October, 2026'``, ``'2026-10'``, ``'14.10.2026'``)."""
    text = text or ""
    m = _MONTH_KEY_RE.search(text)
    if m:
        return f"{m.group(2)}-{_MONTHS[m.group(1).lower()[:3]]:02d}"
    m = _YEAR_MONTH_RE.search(text)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = _MONTH_YEAR_RE.search(text)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = _DATE_DMY_RE.search(text)                    # dd.mm.yyyy, the OEA filename form
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(3)}-{int(m.group(2)):02d}"
    return None


def release_date(text: str, url: str, ref_month: str) -> tuple[str, float]:
    """``(known_at, pit_conf)`` for one release.

    Order: the date printed on the release -> a ``dd.mm.yyyy`` in the URL ->
    the documented 14th of the following month (``pit_conf`` 0.8). The last
    rule is a documented publication rule, not today's date.
    """
    m = _DATED_WORD_RE.search(text or "")
    if m:
        day, mon, year = int(m.group(1)), _MONTHS[m.group(2).lower()[:3]], int(m.group(3))
        if 1 <= day <= 31:
            try:
                return date(year, mon, day).isoformat(), 1.0
            except ValueError:
                pass
    for blob in (url or "", text or ""):
        m = _DATE_DMY_RE.search(blob)
        if m:
            day, mon, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            # A body date ("as on 30.09.2026") is only trusted when it belongs
            # to the release window; otherwise it is some other table's date.
            if 1 <= day <= 31 and 1 <= mon <= 12 and year in (
                    int(ref_month[:4]), int(ref_month[:4]) + 1):
                try:
                    return date(year, mon, day).isoformat(), 1.0
                except ValueError:
                    pass
    year, month = (int(p) for p in ref_month.split("-"))
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(year, month, RELEASE_DAY_OF_MONTH).isoformat(), 0.8


# ---------------------------------------------------------------------------
# Table readers: HTML rows and PDF-text lines collapse to the same shape
# ---------------------------------------------------------------------------
def _header(rows: list[list[str]]) -> tuple[int, int, int] | None:
    """Locate ``(row_index, name_col, index_col)`` of the annexure header.

    The row must name a weight and an index column; the name column is the
    leftmost cell that is not one of those. Refusing (``None``) is deliberate:
    a table without headers is a layout we do not understand, and guessing a
    column would put the weight where the index belongs.
    """
    for i, row in enumerate(rows):
        weight_col = next((j for j, c in enumerate(row) if _WEIGHT_HEADER_RE.search(c)), None)
        index_cols = [j for j, c in enumerate(row) if _INDEX_HEADER_RE.search(c)]
        if weight_col is None or not index_cols:
            continue
        index_col = index_cols[0]
        if index_col <= weight_col:                        # "Index ... Weight" layout
            after = [j for j in index_cols if j > weight_col]
            index_col = after[0] if after else weight_col + 1
        name_col = next((j for j in range(len(row))
                         if j not in (weight_col, index_col) and row[j]
                         and not _INDEX_HEADER_RE.search(row[j])
                         and not _WEIGHT_HEADER_RE.search(row[j])), 0)
        return i, name_col, index_col
    return None


def parse_release(payload: bytes | str, url: str = "") -> dict:
    """One release -> ``{'status', 'rows', 'info'}``; rows are tidy CSV dicts.

    ``rows`` are keyed by ``(series_code, date, known_at)`` and carry the
    vintage, so two releases that both cover a month produce two rows when the
    index was revised.
    """
    raw = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else (payload or "")
    head = raw.lstrip()[:400].lower()
    is_html = head.startswith("<!doctype") or head.startswith("<html") or "<table" in raw[:8000].lower()
    rows_in = html_rows(raw) if is_html else text_rows(raw)
    plain = text_of(raw) if is_html else raw
    info = {"source_url": url, "format": "html" if is_html else "text",
            "rows_in": len(rows_in), "unmatched": 0, "rejected": 0,
            "collisions": 0, "item_names": []}
    if not rows_in:
        return {"status": "failed", "reason": "no table rows found", "rows": [], "info": info}

    ref = None
    m = _REF_MONTH_RE.search(plain)
    if m:
        ref = f"{m.group(2)}-{_MONTHS[m.group(1).lower()[:3]]:02d}"
    if not ref:
        # The release filename carries its own reference month; the body also
        # mentions the base year ("2011-12"), so a body-only month before 2019
        # is the base-year footnote, not this release.
        from_url = month_in(url)
        from_body = month_in(plain)
        ref = from_url or (from_body if from_body and from_body[:4] >= "2019" else None)
    if not ref:
        return {"status": "refused", "reason": "reference month unreadable; "
                "a release is never dated today", "rows": [], "info": info}
    known_at, conf = release_date(plain, url, ref)
    period_end = month_end(int(ref[:4]), int(ref[5:]))

    found = _header(rows_in)
    if not found:
        return {"status": "refused", "reason": "annexure header (weight/index) not found",
                "rows": [], "info": {**info, "reference_month": ref}}
    header_at, name_col, index_col = found
    # Month-aware column pick: a release that prints "Index Aug | Index Sep"
    # must not be read off the older column. When no header names a month the
    # first index column after the weight is the reference month (OEA order).
    header = rows_in[header_at]
    index_col = next((j for j, c in enumerate(header)
                      if _INDEX_HEADER_RE.search(c) and month_in(c) == ref), index_col)
    weight_col = next((j for j, c in enumerate(header)
                       if _WEIGHT_HEADER_RE.search(c)), None)

    # One row per code per release: the smallest weight is the most specific
    # row when a label family matches both a group and its item.
    by_code: dict[str, dict] = {}
    for row in rows_in[header_at + 1:]:
        if not row or name_col >= len(row):
            continue
        code = match_item(row[name_col])
        if not code:
            if row[name_col] and re.search(r"[A-Za-z]{3}", row[name_col]):
                info["unmatched"] += 1
                if len(info["item_names"]) < 20:
                    info["item_names"].append(row[name_col][:60])
            continue
        index = num(row[index_col]) if index_col < len(row) else None
        weight = num(row[weight_col]) if weight_col is not None and weight_col < len(row) else None
        if index is None or not 20.0 <= index <= 1000.0:
            info["rejected"] += 1
            continue
        if weight is not None and not 0.0 < weight <= 100.0:
            weight = None
        candidate = {"series_code": code, "date": period_end, "value": index,
                     "unit": UNIT, "weight": weight, "known_at": known_at,
                     "pit_conf": conf, "source": SOURCE, "source_url": url}
        kept = by_code.get(code)
        if kept is None:
            by_code[code] = candidate
        else:
            info["collisions"] += 1
            if (weight is not None and kept["weight"] is not None
                    and weight < kept["weight"]):
                by_code[code] = candidate
    info.update({"reference_month": ref, "known_at": known_at, "pit_conf": conf,
                 "series_matched": len(by_code)})
    rows = sorted(by_code.values(), key=lambda r: r["series_code"])
    return {"status": "ok" if rows else "failed",
            "reason": None if rows else "no mapped item in the annexure",
            "rows": rows, "info": info}


# ---------------------------------------------------------------------------
# Discovery -- the site names its own releases; we never guess filenames
# ---------------------------------------------------------------------------
_RELEASE_HINT_RE = re.compile(r"(?i)(press|release|wpi|wholesale|index)")
_ARCHIVE_HINT_RE = re.compile(r"(?i)(archive|press|release|wpi)")
_SUPPORTED_SUFFIXES = (".pdf", ".htm", ".html", ".shtml", ".asp", ".aspx")


def _suffix(url: str) -> str:
    base = re.split(r"[?#]", url, maxsplit=1)[0].lower()
    for suf in sorted(_SUPPORTED_SUFFIXES, key=len, reverse=True):
        if base.endswith(suf):
            return suf
    return ""


def discover_release_links(pages: list[tuple[str, str]]) -> dict:
    """All ``(url, html)`` listing pages -> ``{reference_month: release_url}``.

    A link is kept only when its text or href names the release and a month can
    be read from either. First occurrence wins (the listing pages are newest
    first), so the newest vintage of a month is the one fetched.
    """
    found: dict[str, str] = {}
    for page_url, html in pages:
        for url, text in anchors(html, page_url):
            suffix = _suffix(url)
            if suffix not in _SUPPORTED_SUFFIXES or not _RELEASE_HINT_RE.search(f"{text} {url}"):
                continue
            month = month_in(f"{text} {url}")
            if not month or month in found:
                continue
            found[month] = url
    return dict(sorted(found.items()))


def archive_links(html: str, page_url: str, limit: int = MAX_ARCHIVE_PAGES) -> list[str]:
    """Listing-page URLs worth following (an archive that lists old releases)."""
    out: list[str] = []
    for url, text in anchors(html, page_url):
        if url in out or not url.startswith("http"):
            continue
        if _ARCHIVE_HINT_RE.search(f"{text} {url}") and not _suffix(url).endswith(".pdf"):
            out.append(url)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
def pdf_text(payload: bytes) -> str:
    """PDF bytes -> text. Refuses a workbook: its layout is a different contract."""
    if payload[:4] == b"%PDF":
        try:
            import pymupdf                                    # noqa: PLC0415
            with pymupdf.open(stream=payload, filetype="pdf") as doc:
                return "\n".join(page.get_text() for page in doc)
        except Exception:                                     # noqa: BLE001
            return ""
    return ""


def fetch_releases(out: Path, start: date, end: date, index_urls: tuple[str, ...],
                   ) -> tuple[list[dict], dict]:
    out.mkdir(parents=True, exist_ok=True)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pages: list[tuple[str, str]] = []
    info: dict = {"index_pages": [], "requests": 0, "months_fetched": 0,
                  "months_missing": [], "failed": []}
    archive_budget = MAX_ARCHIVE_PAGES
    for url in index_urls:
        try:
            html = http_get(url, timeout=60).decode("utf-8", "replace")
        except Exception as exc:                              # noqa: BLE001
            info["index_pages"].append({"url": url, "status": "failed", "reason": str(exc)[:160]})
            info["requests"] += 1
            continue
        info["index_pages"].append({"url": url, "status": "ok", "bytes": len(html)})
        info["requests"] += 1
        pages.append((url, html))
        for extra in archive_links(html, url, limit=archive_budget):
            if archive_budget <= 0:
                break
            archive_budget -= 1
            try:
                sub = http_get(extra, timeout=60).decode("utf-8", "replace")
            except Exception as exc:                          # noqa: BLE001
                info["index_pages"].append({"url": extra, "status": "failed",
                                            "reason": str(exc)[:160]})
                info["requests"] += 1
                continue
            info["index_pages"].append({"url": extra, "status": "ok", "bytes": len(sub)})
            info["requests"] += 1
            pages.append((extra, sub))

    links = discover_release_links(pages)
    info["links_found"] = len(links)
    rows: list[dict] = []
    for year, month in month_range(start, end):
        ref = f"{year}-{month:02d}"
        url = links.get(ref)
        if not url:
            info["months_missing"].append(ref)
            continue
        try:
            payload = http_get(url, timeout=120)
        except Exception as exc:                              # noqa: BLE001
            info["failed"].append({"month": ref, "reason": str(exc)[:160]})
            info["requests"] += 1
            continue
        info["requests"] += 1
        name = f"wpi_{ref}{_suffix(url) or '.bin'}"
        (raw_dir / name).write_bytes(payload)
        body = pdf_text(payload)
        parsed = parse_release(body if body else payload, url)
        if parsed["status"] != "ok":
            info["failed"].append({"month": ref, "status": parsed["status"],
                                   "reason": parsed.get("reason")})
            continue
        rows += parsed["rows"]
        info["months_fetched"] += 1
        print(f"  {ref}: {len(parsed['rows'])} series, known_at {parsed['info']['known_at']}")
    return rows, info


def plan(start: date, end: date) -> dict:
    months = sum(1 for _ in month_range(start, end))
    index_pages = len(INDEX_URLS) + MAX_ARCHIVE_PAGES
    requests = index_pages + months
    return {
        "months": months,
        "index_pages_max": index_pages,
        "requests_p50": requests,
        "requests_max": requests + months // 10,           # ~10% refetch on error
        "est_minutes_p50": plan_minutes(requests),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--from", dest="start", default="2019-01-01")
    ap.add_argument("--to", dest="end", default=date.today().isoformat())
    ap.add_argument("--index-url", action="append", default=[],
                    help="extra listing page to read (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="plan only: no network, no writes")
    args = ap.parse_args(argv)

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    index_urls = tuple(INDEX_URLS) + tuple(args.index_url)
    for key, value in plan(start, end).items():
        print(f"  {key:20} {value}")
    if args.dry_run:
        print("dry-run: no request made")
        return 0

    out = Path(args.out)
    rows, info = fetch_releases(out, start, end, index_urls)
    print(f"wpi: {info}")
    written = write_csv(out / "wpi_items.csv", CSV_COLUMNS, rows)
    codes = sorted({r["series_code"] for r in rows})
    print(f"wrote {written} rows, {len(codes)} series -> {out / 'wpi_items.csv'}")
    print(f"  {codes}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
