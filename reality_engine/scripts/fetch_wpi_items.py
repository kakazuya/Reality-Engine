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
INDEX_SOURCE = "oea_wpi_monthly_index"
#: The release this module reads for one released row at item level.
BASE_YEAR = "2011_12"
UNIT = f"index_{BASE_YEAR}_100"
#: Listing pages whose linked workbook holds every item for every month since
#: Apr-2012 (2011-12 base) and Apr-2023 (2022-23 base). One request per base
#: replaces ~90 per-month release fetches and reaches months whose release is a
#: .doc summary that never printed item rows.
INDEX_PAGES = ("https://eaindustry.nic.in/download_data_1112.asp",
               "https://eaindustry.nic.in/download_data_2223.asp")
BASE_BY_PATH = {"1112": "2011_12", "2223": "2022_23"}
#: The workbook carries revised values, so a row is stamped with the documented
#: release date of its month (the 14th of the next month), not with a vintage we
#: could observe. ``pit_conf`` says so instead of claiming a printed date.
INDEX_PIT_CONF = 0.75
_BASE_RE = re.compile(r"(?i)base\s*year\s*[:\-]?\s*(20\d\d)\s*[-/]\s*(\d\d)")
#: A workbook names the weight column "COMM_WT" (2011-12) or "Commodity Weight"
#: (2022-23); ``\bweight\b`` alone misses the first, which silently disables the
#: group-vs-item tie-break.
_WT_HEADER_RE = re.compile(r"(?i)weight|(?:^|[^a-z])wt\b")
_MONTH_COLS = (
    re.compile(r"(?i)^indx\s*(\d{2})(20\d{2})$"),            # INDX042012
    re.compile(r"(?i)^([a-z]{3})[a-z]*[- /](\d{2,4})$"),     # Apr-23 / Apr-2012
)


def release_base(text: str) -> str:
    """``'2011_12'`` for a release whose printed base year can be read, else ``''``."""
    m = _BASE_RE.search(text or "")
    return f"{m.group(1)}_{m.group(2)}" if m else ""


def unit_for(base: str) -> str:
    return f"index_{base}_100"


#: series_code -> regex over the NORMALISED item label (:func:`normalise_item`).
#: First match wins, so the specific items are declared before the groups.
#: ``wpi_steel_group`` is the "basic metals" sub-group, which is how "other
#: steel products" is held without inventing an average of unrelated items.
#: Patterns follow the labels the source actually prints (2011-12 series and the
#: 2022-23 series that replaced it in May 2026), e.g. "Hot Rolled (HR) Coils &
#: Sheets, including Narrow Strip" and "Hot Rolled Steel Coils/Sheets/Strips".
ITEM_MATCHERS: tuple[tuple[str, str], ...] = (
    ("wpi_hrc",              r"^(hot rolled|hr coils?|hrc)\b"),
    ("wpi_cold_rolled",      r"^cold rolled\b"),
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
    ("wpi_npk",              r"^(npk|n p k|mixed fertilizer)\b"),
    ("wpi_cement",           r"^(cement|manufacture of cement|ordinary portland|opc)\b"),
    ("wpi_aluminium",        r"^(aluminium|aluminum)\b"),
    ("wpi_copper",           r"^copper\b"),
    ("wpi_zinc",             r"^zinc\b"),
    ("wpi_lead",             r"^lead\b"),
    ("wpi_nickel",           r"^nickel\b"),
    ("wpi_cotton_yarn",      r"^cotton yarn"),
    ("wpi_plastics",         r"^(plastics?|polymer|polypropylene|polyethylene|polystyrene|poly vinyl|pvc)\b"),
    ("wpi_steel_group",      r"^(manufacture of basic metals?|manufacture of basic iron and steel|"
                             r"basic metals?|iron and steel|iron steel group)\b"),
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
#: "(A).", "a.", "a1.", "b.)", "i." -- the tree enumerator the source puts in
#: front of every group and sub-group label.
_ENUM_RE = re.compile(r"^\s*(?:\(\s*[a-z0-9]{1,4}\s*\)|[a-z0-9ivx]{1,4}\s*[.)]+)\s*")


# ---------------------------------------------------------------------------
# Identifiers -- pure functions, so they are testable offline
# ---------------------------------------------------------------------------
def normalise_item(label: str) -> str:
    """``'Angles, channels & sections'`` -> ``'angles channels and sections'``.

    The leading enumerator of a tree label (``'(A). COAL'``, ``'a1. CEREALS'``,
    ``'e.Manufacture of cement'``) is dropped, so a sub-group matches the same
    pattern as the item a press release prints on its own.
    """
    text = (label or "").lower().replace("&", " and ")
    text = _ENUM_RE.sub("", text, count=1)
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
    plain = text_of(raw) if is_html else raw
    info = {"source_url": url, "format": "html" if is_html else "text",
            "rows_in": 0, "unmatched": 0, "rejected": 0,
            "collisions": 0, "item_names": []}
    base = release_base(plain)
    if base and base != BASE_YEAR:
        # The series changed base (2011-12 -> 2022-23 in May 2026). Its index is
        # not this column's index, and a wrong base in a level series is worse
        # than a gap: the workbook path holds the new base separately.
        return {"status": "refused", "reason": f"release is on base {base}, "
                f"this series is {BASE_YEAR}", "rows": [], "info": info}
    rows_in = html_rows(raw) if is_html else text_rows(raw)
    info["rows_in"] = len(rows_in)
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
# Monthly index workbook -- one file holds every item for every month
# ---------------------------------------------------------------------------
def month_columns(header: list[str]) -> list[tuple[int, str]]:
    """``(column, 'YYYY-MM')`` for each month column of a workbook header."""
    out: list[tuple[int, str]] = []
    for col, cell in enumerate(header or []):
        text = (cell or "").strip()
        m = _MONTH_COLS[0].match(text)                       # INDX042012
        if m:
            month, year = int(m.group(1)), int(m.group(2))
        else:
            m = _MONTH_COLS[1].match(text)                   # Apr-23 / Apr-2012
            if not m:
                continue
            month = _MONTHS.get(m.group(1).lower()[:3], 0)
            year = int(m.group(2)) + (2000 if len(m.group(2)) <= 2 else 0)
        if 1 <= month <= 12:
            out.append((col, f"{year}-{month:02d}"))
    return out


def workbook_matrix(payload: bytes) -> tuple[list[str], list[list]]:
    """Header cells and data rows of an ``.xls``/``.xlsx`` index workbook.

    The two bases ship in different containers (BIFF8 ``.xls`` for 2011-12,
    OOXML ``.xlsx`` for 2022-23); both are read here so the parser below sees one
    shape. A workbook without a month header is refused, not guessed at.
    """
    if payload[:4] == b"PK\x03\x04":
        import io                                    # noqa: PLC0415
        import openpyxl                              # noqa: PLC0415
        book = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        sheet = book[book.sheetnames[0]]
        rows = [list(r) for r in sheet.iter_rows(values_only=True)]
        book.close()
    elif payload[:4] == b"\xd0\xcf\x11\xe0":
        import xlrd                                  # noqa: PLC0415
        book = xlrd.open_workbook(file_contents=payload)
        sheet = book.sheet_by_index(0)
        rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
                for r in range(sheet.nrows)]
    else:
        return [], []
    header_at = next((i for i, row in enumerate(rows)
                      if month_columns([str(c) if c is not None else "" for c in row])), None)
    if header_at is None:
        return [], []
    header = [str(c) if c is not None else "" for c in rows[header_at]]
    return header, [row for row in rows[header_at + 1:]
                    if any(value not in (None, "") for value in row)]


def rows_from_matrix(header: list[str], rows: list[list], base: str, url: str,
                     start: date, end: date) -> tuple[list[dict], dict]:
    """Item rows of one workbook, one value per series per month inside the window.

    The workbook prints the whole tree, so a family matches its group *and* its
    items. The largest weight wins: that is the aggregate the release prints, not
    one grade of it ("Non-Coking Coal", not its G15-G17 sub-row).
    """
    columns = month_columns(header)
    info = {"base": base, "month_columns": len(columns), "matrix_rows": len(rows),
            "unmatched": 0, "rejected": 0, "months": 0}
    if not columns:
        return [], {**info, "reason": "no month column in the workbook header"}
    name_col = next((j for j, c in enumerate(header) if re.search(r"(?i)name", c)), 0)
    weight_col = next((j for j, c in enumerate(header)
                       if _WT_HEADER_RE.search(c)), None)
    first, last = start.isoformat()[:7], end.isoformat()[:7]
    wanted = [(j, month) for j, month in columns if first <= month <= last]
    best: dict[tuple[str, str], tuple[float, dict]] = {}
    for row in rows:
        label = str(row[name_col]) if name_col < len(row) and row[name_col] is not None else ""
        code = match_item(label)
        if not code:
            info["unmatched"] += 1
            continue
        weight = num(str(row[weight_col])) if weight_col is not None and \
            weight_col < len(row) else None
        rank = weight if weight is not None else 0.0
        for col, month in wanted:
            value = num(str(row[col])) if col < len(row) else None
            if value is None or not 20.0 <= value <= 1000.0:
                info["rejected"] += 1
                continue
            known_at, _ = release_date("", "", month)
            candidate = {"series_code": code,
                         "date": month_end(int(month[:4]), int(month[5:])),
                         "value": value, "unit": unit_for(base), "weight": weight,
                         "known_at": known_at, "pit_conf": INDEX_PIT_CONF,
                         "source": INDEX_SOURCE, "source_url": url, "base": base}
            kept = best.get((code, month))
            if kept is None or rank >= kept[0]:
                best[(code, month)] = (rank, candidate)
    out = sorted((row for _, row in best.values()),
                 key=lambda r: (r["series_code"], r["date"]))
    return out, {**info, "series_matched": len({r["series_code"] for r in out}),
                 "months": len({r["date"] for r in out})}


def read_index_workbook(payload: bytes, url: str, start: date, end: date,
                        ) -> tuple[list[dict], dict]:
    """One workbook payload -> rows for the window, with the base read from its URL."""
    base = next((name for key, name in BASE_BY_PATH.items() if key in url), "")
    if not base:
        return [], {"reason": f"base year not in the workbook url: {url}"}
    header, rows = workbook_matrix(payload)
    if not header:
        return [], {"base": base, "reason": "not an index workbook, or no header"}
    return rows_from_matrix(header, rows, base, url, start, end)


def discover_index_files(pages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """``(base, url)`` for the monthly WPI index workbook linked by each data page.

    Only the WPI monthly file is kept: the same pages also link output-PPI and
    yearly-average workbooks, whose rows are different series, not this base's.
    """
    out: list[tuple[str, str]] = []
    for page_url, html in pages:
        for url, _text in anchors(html, page_url):
            low = url.lower()
            if not low.endswith((".xls", ".xlsx")) or "monthly" not in low:
                continue
            if any(skip in low for skip in ("oppi", "ippi", "yearly", "cal_year",
                                            "fin_year")):
                continue
            base = next((name for key, name in BASE_BY_PATH.items() if key in low), "")
            if base and (base, url) not in out:
                out.append((base, url))
    return out


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
        if _suffix(url) and _suffix(url) not in (".htm", ".html", ".shtml", ".asp", ".aspx"):
            continue                       # a deck or a spreadsheet is not a listing page
        if _ARCHIVE_HINT_RE.search(f"{text} {url}"):
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
                  "months_missing": [], "failed": [], "index_files": []}
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
    for base, url in discover_index_files(pages):
        info["requests"] += 1
        try:
            payload = http_get(url, timeout=240)
        except Exception as exc:                              # noqa: BLE001
            info["failed"].append({"index_file": url, "reason": str(exc)[:160]})
            continue
        (raw_dir / f"wpi_index_{base}."
         f"{url.split('?')[0].rsplit('.', 1)[-1]}").write_bytes(payload)
        got, meta = read_index_workbook(payload, url, start, end)
        rows += got
        info["index_files"].append({"url": url, **meta, "rows": len(got)})
        print(f"  index {base}: {len(got)} rows, "
              f"{meta.get('months', 0)} months, {meta.get('series_matched', 0)} series")
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
    # One row per (series, month, known_at): the workbook and a monthly release
    # can describe the same month, and only a later known_at is a new vintage.
    # A month covered by both bases keeps the one in force then (2011-12 before
    # the May 2026 switch, 2022-23 after), so the level never jumps bases inside
    # one vintage; the unit column names which base each row is on.
    unique: dict[tuple, dict] = {}
    for row in sorted(rows, key=lambda r: (r["date"], r.get("base", ""))):
        unique.setdefault((row["series_code"], row["date"], row["known_at"]), row)
    return sorted(unique.values(),
                  key=lambda r: (r["series_code"], r["date"], r["known_at"])), info


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
    index_urls = tuple(INDEX_URLS) + tuple(INDEX_PAGES) + tuple(args.index_url)
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
