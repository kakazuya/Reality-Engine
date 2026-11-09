"""T-132: every printed table cell of a PDF page from word boxes (text layer only), no model.

Rules (docs/V2_SCHEMA_CONTRACT.md section 10):

a. The header of a table is every row between the previous table block on the page (or the page
   top) and this block.  A header phrase that spans several column anchors ("Quarter ended") is
   assigned to every column under its x-span; ``col_header`` joins the rows top to bottom with
   ``' > '`` (``'Quarter ended > 30.09.2026'``).
b. A section label ("Expenses") ends where a new numbered row group starts (first token is a row
   number: ``2``, ``II``, ``IV``).  Parenthesised sub-labels (``(a)``) stay inside the section.
   The printed row-number column is dropped from ``row_label`` and from the cells.
c. Figures split by the text layer ("2, 028", "1 ,234.5") merge; ``(1,234.5)`` and ``-1,234.5``
   are negative; ``-`` / an en dash is value NULL with ``value_text`` kept; ``12.3%`` is percent.
d. The unit is read from the table's header rows, else the page's top 15%.  crore 1e7, lakh 1e5,
   million/mn 1e6, billion/bn 1e9, thousand 1e3.  Percent stays in percent points
   (``unit_text='%'``, ``scale=1``).  No unit found means ``scale`` and ``value`` are NULL: never
   guess a scale.
e. ``period_id`` comes from the column header and the document date through
   :func:`reality_engine.v2.periods.period_row`.
f. ``basis`` is standalone/consolidated from the page title (top 20%), else NULL.
g. An infographic page -- numbers scattered with no two-row aligned block -- yields no cells.
h. ``bbox`` is the merged token's box and ``method`` is ``'text_layer'``.
"""
from __future__ import annotations

import calendar
import re
import statistics
from datetime import date, timedelta
from typing import Any

import pymupdf

from reality_engine.v2.periods import period_row

__all__ = ["extract", "extract_page", "period_from_header"]

_DAY = timedelta(days=1)
_ROW_TOL = 3.0
_MERGE_GAP = 5.0
_PHRASE_GAP = 8.0
_ANCHOR_TOL = 6.0

NUM = re.compile(
    r"^\(?[-–—−]?(?:(?:₹|Rs\.?|INR)\s*)?\d[\d,]*(?:\.\d+)?\)?%?$"
    r"|^[-–—−]$"
    r"|^\(?\d*\.\d+\)?%?$")
NUMISH = re.compile(r"^\(?[-–—−]?(?:₹|Rs\.?|INR)?\s*\d[\d,]*(?:\.\d*)?\)?%?$")
ROWNUM = re.compile(r"^(?:\d{1,2}\.?|[IVXLC]{1,4}\.?)$")
GROWTH = re.compile(r"\b(yoy|y-o-y|qoq|q-o-q|growth|change|var(?:iation)?)\b|%", re.I)
UNIT = re.compile(
    r"(?:(?:\b(?:rs\.?|inr|rupees?)\b|₹)\s*(?:in\s+)?|\bin\s+)"
    r"(crores?|cr|lakhs?|lacs?|millions?|mn|billions?|bn|thousands?)",
    re.I)

_MONTHS = {name: i for i, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_SCALES = {
    "crore": (1e7, "crore"), "crores": (1e7, "crore"), "cr": (1e7, "crore"),
    "lakh": (1e5, "lakh"), "lakhs": (1e5, "lakh"), "lac": (1e5, "lakh"), "lacs": (1e5, "lakh"),
    "million": (1e6, "million"), "millions": (1e6, "million"), "mn": (1e6, "million"),
    "billion": (1e9, "billion"), "billions": (1e9, "billion"), "bn": (1e9, "billion"),
    "thousand": (1e3, "thousand"), "thousands": (1e3, "thousand"),
}

_DATE_DMY = re.compile(r"(?<!\d)(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})(?!\d)")
_DATE_FULL = re.compile(r"^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}$")
_DATE_DMY_WORD = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s\-]([A-Za-z]{3,9})[\s,\-]+(\d{2,4})(?!\d)")
_DATE_MDY = re.compile(
    r"([A-Za-z]{3,9})[\s\-]+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,\s*|\s+)(\d{4}|\d{2})(?!\d)")
_DATE_MY = re.compile(r"([A-Za-z]{3,9})[\s\-]+(\d{2})(?!\d)(?!\s*[,.\-/]\s*\d)")
_KINDS = (
    (re.compile(r"\bas\s+(?:at|on|of)\b", re.I), "POINT"),
    (re.compile(r"\bnine\s+months?\b|\b9\s*m(?:onths?)?\b", re.I), "9M"),
    (re.compile(r"\bsix\s+months?\b|\bhalf[\s-]year\b|\bh1\b", re.I), "H1"),
    (re.compile(r"\bquarter\b|\bq[1-4]\b", re.I), "Q"),
    (re.compile(r"\byear[\s-]?ended\b|\bfor\s+the\s+year\b|\bfy\b", re.I), "FY"),
)


# ------------------------------------------------------------------------------- word boxes

def _rows_of(words: list[Any], tol: float = _ROW_TOL) -> list[list[Any]]:
    rows: list[list[Any]] = []
    current: list[Any] = []
    y: float | None = None
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        centre = (w[1] + w[3]) / 2
        if y is None or abs(centre - y) <= tol:
            current.append(w)
            y = centre if y is None else y
        else:
            rows.append(sorted(current, key=lambda t: t[0]))
            current, y = [w], centre
    if current:
        rows.append(sorted(current, key=lambda t: t[0]))
    return rows


def _joinable(previous: dict[str, Any], word: Any, text: str) -> bool:
    gap = word[0] - previous["x1"]
    if gap > _MERGE_GAP:
        return False
    left = previous["text"]
    if gap <= 3.0 and _DATE_FULL.match(left + text):
        return True                         # the layer split a date: '3' + '1.03.2026'
    if gap <= 2.5 and left[-1].isdigit() and text[0].isdigit():
        return bool(re.fullmatch(r"\d{1,7}", left + text))   # a lost thousands separator
    if left[-1] in ",.-–—−(₹" or text[0] in ",.)%":
        return bool(NUMISH.match(left + text))
    return False


def _tokens(row: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for word in row:
        text = str(word[4]).strip()
        if not text:
            continue
        if out and _joinable(out[-1], word, text):
            out[-1]["text"] += text
            out[-1]["x1"] = max(out[-1]["x1"], float(word[2]))
            out[-1]["y1"] = max(out[-1]["y1"], float(word[3]))
            continue
        out.append({"x0": float(word[0]), "y0": float(word[1]),
                    "x1": float(word[2]), "y1": float(word[3]), "text": text})
    for token in out:
        token["num"] = bool(NUM.match(token["text"]))
    return out


_DATE_TOKEN = re.compile(
    r"^(?:(?:19|20)\d{2}"
    r"|[A-Za-z]{3,9}[ .\-]\d{2,4}"
    r"|\d{1,2}[ .\-][A-Za-z]{3,9}(?:[ .\-]\d{2,4})?"
    r"|\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}"
    r"|\d{1,2},\d{4}"
    r"|(?:Q[1-4]|H[12]|9M)(?:\s*FY\s*\d{2,4})?"
    r"|FY\s*\d{2,4})$", re.I)
_ALPHA = re.compile(r"[A-Za-z]")


def _numeric_count(row: list[dict[str, Any]]) -> int:
    """Data numbers in a row; a date header row or a lone row number is not data."""
    texts = [token["text"] for token in row if token["text"].strip()]
    if len(texts) >= 2 and all(_DATE_TOKEN.match(text) for text in texts):
        return 0                              # '2023 2024 2025 Jun-25 ...' is a header row
    numbers = [token for token in row if token["num"]]
    if len(numbers) == 1 and ROWNUM.match(numbers[0]["text"]):
        first = next((token for token in row if token["text"].strip()), None)
        if first is numbers[0]:
            return 0
    return len(numbers)


def _anchors_of(block: list[list[dict[str, Any]]]) -> list[float]:
    xs = sorted(token["x1"] for row in block for token in row if token["num"])
    clusters: list[list[float]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= _ANCHOR_TOL:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    need = max(2, 0.3 * len(block))
    return [sum(cluster) / len(cluster) for cluster in clusters if len(cluster) >= need]


def _phrases(row: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phrases: list[dict[str, Any]] = []
    for token in sorted(row, key=lambda t: t["x0"]):
        if phrases and token["x0"] - phrases[-1]["x1"] <= _PHRASE_GAP:
            phrases[-1]["x1"] = max(phrases[-1]["x1"], token["x1"])
            phrases[-1]["text"] += " " + token["text"]
        else:
            phrases.append({"x0": token["x0"], "x1": token["x1"], "text": token["text"]})
    return phrases


def _centers(anchors: list[float]) -> tuple[list[float], float]:
    """Approximate centre of each right-aligned column and the typical column width."""
    gap = min((b - a for a, b in zip(anchors, anchors[1:])), default=40.0)
    gap = max(gap, 1.0)
    centers = []
    for k, anchor in enumerate(anchors):
        width = anchor - anchors[k - 1] if k else gap
        centers.append(anchor - max(width, 1.0) / 2)
    return centers, gap


def _date_phrase(text: str) -> bool:
    return bool(_DATE_DMY.search(text) or _DATE_DMY_WORD.search(text)
                or _DATE_MDY.search(text) or _DATE_MY.search(text))


def _kind_like(text: str) -> bool:
    return bool(_kind_in(text) or re.search(
        r"\b(?:quarter|half|year|months?|ended|ytd|nine|six|as\s+(?:at|on|of))\b",
        text, re.I))


def _refined_centers(header_rows: list[list[dict[str, Any]]], anchors: list[float],
                     left: float) -> tuple[list[float], float]:
    """Column centres from the date row when the header stack prints one."""
    centers, gap = _centers(anchors)
    for row in reversed(header_rows):
        phrases = _phrases([t for t in row if t["x1"] >= left])
        if (len(phrases) >= max(2, (len(centers) + 1) // 2)
                and all(_date_phrase(p["text"]) for p in phrases)):
            refined = list(centers)
            for phrase in phrases:
                centre = (phrase["x0"] + phrase["x1"]) / 2
                k = min(range(len(refined)), key=lambda j: abs(refined[j] - centre))
                refined[k] = centre
            centers = refined
            break
    return centers, gap


def _period_blocks(phrases: list[dict[str, Any]],
                   centers: list[float]) -> list[tuple[int, int]] | None:
    """Partition columns into consecutive blocks, one per phrase, centred on the phrase."""
    count, width = len(phrases), len(centers)
    if count > width:
        return None
    infinity = float("inf")
    best = [[infinity] * (width + 1) for _ in range(count + 1)]
    back = [[0] * (width + 1) for _ in range(count + 1)]
    best[0][0] = 0.0
    for i in range(1, count + 1):
        centre = (phrases[i - 1]["x0"] + phrases[i - 1]["x1"]) / 2
        for end in range(i, width - (count - i) + 1):
            for start in range(i - 1, end):
                if best[i - 1][start] == infinity:
                    continue
                mean = sum(centers[start:end]) / (end - start)
                cost = best[i - 1][start] + (mean - centre) ** 2
                if cost < best[i][end]:
                    best[i][end] = cost
                    back[i][end] = start
    if best[count][width] == infinity:
        return None
    blocks: list[tuple[int, int]] = []
    end = width
    for i in range(count, 0, -1):
        start = back[i][end]
        blocks.append((start, end))
        end = start
    return list(reversed(blocks))


def _headers(header_rows: list[list[dict[str, Any]]], anchors: list[float],
             left: float) -> list[str | None]:
    centers, gap = _refined_centers(header_rows, anchors, left)
    columns: list[list[str]] = [[] for _ in anchors]
    for row in header_rows:
        phrases = _phrases([t for t in row if t["x1"] >= left])
        if not phrases:
            continue
        widths = [phrase["x1"] - phrase["x0"] for phrase in phrases]
        if len(phrases) == 1:
            phrase = phrases[0]
            centre = (phrase["x0"] + phrase["x1"]) / 2
            if _kind_like(phrase["text"]) and not _date_phrase(phrase["text"]) \
                    and widths[0] <= 4.0 * gap:
                for k in range(len(centers)):            # a heading over the whole table
                    columns[k].append(phrase["text"])
                continue
            k = min(range(len(centers)), key=lambda j: abs(centers[j] - centre))
            if abs(centers[k] - centre) <= 2.0 * gap:
                columns[k].append(phrase["text"])
            continue
        all_dates = all(_date_phrase(phrase["text"]) for phrase in phrases)
        all_kinds = all(_kind_like(phrase["text"]) for phrase in phrases)
        if ((all_dates and len(phrases) >= len(centers) - 1) or all_kinds) \
                and len(phrases) <= len(centers) and max(widths) <= 4.0 * gap:
            blocks = _period_blocks(phrases, centers)
            if blocks:
                for (start, end), phrase in zip(blocks, phrases):
                    for k in range(start, end):
                        columns[k].append(phrase["text"])
                continue
        phrase_centers = [(p["x0"] + p["x1"]) / 2 for p in phrases]
        for k, centre in enumerate(centers):
            nearest = min(range(len(phrases)),
                          key=lambda j: abs(phrase_centers[j] - centre))
            if abs(phrase_centers[nearest] - centre) <= 2.0 * gap:
                columns[k].append(phrases[nearest]["text"])
    return [" > ".join(parts) if parts else None for parts in columns]


# ------------------------------------------------------------------------------------- values

def _number(text: str) -> tuple[float | None, bool]:
    """Printed token -> (number, is_percent); a dash placeholder is (None, False)."""
    raw = text.strip()
    percent = raw.endswith("%")
    if raw in ("-", "–", "—", "−"):
        return None, percent
    clean = raw.replace(",", "")
    for marker in ("₹", "Rs.", "Rs", "INR"):
        clean = clean.replace(marker, "")
    clean = clean.strip()
    negative = clean.startswith("(") and clean.endswith(")")
    clean = clean.strip("()").replace("–", "-").replace("—", "-").replace("−", "-")
    clean = clean.rstrip("%")
    try:
        value = float(clean)
    except ValueError:
        return None, percent
    return (-value if negative else value), percent


def _unit_of(text: str) -> tuple[str, float] | None:
    matches = list(UNIT.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    currency = "INR" if "inr" in match.group(0).lower() else "Rs"
    scale, word = _SCALES[match.group(1).lower()]
    return f"{currency} {word}", scale


def _top_text(page: Any, height: float) -> str:
    clip = pymupdf.Rect(0, 0, page.rect.width, height * 0.15)
    return str(page.get_text("text", clip=clip))


def _basis(page: Any) -> str | None:
    clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.20)
    text = str(page.get_text("text", clip=clip)).lower()
    found = {name for name in ("standalone", "consolidated")
             if re.search(rf"\b{name}\b", text)}
    return found.pop() if len(found) == 1 else None


# ------------------------------------------------------------------------------------ periods

def _add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _fy_start(day: date) -> date:
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def _year(text: str) -> int:
    value = int(text)
    return 2000 + value if value < 100 else value


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _filing_day(filing_date: Any) -> date | None:
    if filing_date is None:
        return None
    if isinstance(filing_date, date):
        return filing_date
    try:
        return date.fromisoformat(str(filing_date)[:10])
    except ValueError:
        return None


def _last_date(text: str, filing_date: Any = None) -> date | None:
    candidates: list[tuple[int, date]] = []
    for match in _DATE_DMY.finditer(text):
        try:
            candidates.append((match.end(), date(_year(match.group(3)), int(match.group(2)),
                                                 int(match.group(1)))))
        except ValueError:
            pass
    for match in _DATE_DMY_WORD.finditer(text):
        month = _MONTHS.get(match.group(2)[:3].lower())
        if month:
            try:
                candidates.append((match.end(), date(_year(match.group(3)), month,
                                                     int(match.group(1)))))
            except ValueError:
                pass
    for match in _DATE_MDY.finditer(text):
        month = _MONTHS.get(match.group(1)[:3].lower())
        if month:
            try:
                candidates.append((match.end(), date(_year(match.group(3)), month,
                                                     int(match.group(2)))))
            except ValueError:
                pass
    for match in _DATE_MY.finditer(text):
        month = _MONTHS.get(match.group(1)[:3].lower())
        if month:
            candidates.append((match.end(), _month_end(_year(match.group(2)), month)))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _period_id(start: date | None, end: date) -> str | None:
    try:
        return str(period_row(start, end)["period_id"])
    except ValueError:
        return None


def _quarter_id(quarter: int, fy_end_year: int) -> str | None:
    fy_start = date(fy_end_year - 1, 4, 1)
    return _period_id(_add_months(fy_start, 3 * (quarter - 1)),
                      _add_months(fy_start, 3 * quarter) - _DAY)


def _half_id(half: int, fy_end_year: int) -> str | None:
    fy_start = date(fy_end_year - 1, 4, 1)
    return _period_id(_add_months(fy_start, 6 * (half - 1)),
                      _add_months(fy_start, 6 * half) - _DAY)


def _direct_label(text: str) -> str | None:
    match = re.search(r"\bQ([1-4])\s*[-/]?\s*FY\s*(\d{2,4})\b", text, re.I)
    if match:
        return _quarter_id(int(match.group(1)), _year(match.group(2)))
    match = re.search(r"\bH([12])\s*[-/]?\s*FY\s*(\d{2,4})\b", text, re.I)
    if match:
        return _half_id(int(match.group(1)), _year(match.group(2)))
    match = re.search(r"\b9\s*M\s*FY\s*(\d{2,4})\b", text, re.I)
    if match:
        fy_start = date(_year(match.group(1)) - 1, 4, 1)
        return _period_id(fy_start, _add_months(fy_start, 9) - _DAY)
    match = re.search(r"\bFY\s*(\d{2,4})\b", text, re.I)
    if match:
        fy_start = date(_year(match.group(1)) - 1, 4, 1)
        return _period_id(fy_start, _add_months(fy_start, 12) - _DAY)
    return None


def _kind_in(segment: str) -> str | None:
    """The most specific period word in one header row: as-at, 9M, half, quarter, year."""
    for pattern, kind in _KINDS:
        if pattern.search(segment):
            return kind
    return None


def _date_kind(text: str, filing_date: Any = None) -> str | None:
    kind = None
    for segment in reversed([s.strip() for s in text.split(" > ") if s.strip()]):
        kind = _kind_in(segment)
        if kind:
            break
    if kind is None:
        return None
    day = _last_date(text, filing_date)
    if day is None:
        day = _last_date(text.replace(" > ", " "), filing_date)   # a wrapped date row
    if day is None and kind == "FY":
        years = re.findall(r"\b((?:19|20)\d{2})\b", text)
        if years:                                 # 'Full Year Ended > 2024'
            day = date(int(years[-1]), 3, 31)
    if day is None:
        return None
    first_of_month = date(day.year, day.month, 1)
    if kind == "POINT":
        return _period_id(None, day)
    if kind == "Q":
        return _period_id(_add_months(first_of_month, -2), day)
    if kind == "H1":
        return _period_id(_add_months(first_of_month, -5), day)
    if kind == "9M":
        return _period_id(_fy_start(day), day)
    return _period_id(_add_months(first_of_month, -11), day)


def period_from_header(header: str | None, filing_date: Any = None) -> str | None:
    """The period a printed column header names, or None when it does not resolve."""
    if not header:
        return None
    segments = [segment.strip() for segment in header.split(" > ") if segment.strip()]
    if not segments:
        return None
    last = segments[-1]
    if GROWTH.search(last) and _last_date(last, filing_date) is None:
        return None
    resolved = _direct_label(last)
    if resolved:
        return resolved
    resolved = _date_kind(header, filing_date)
    if resolved:
        return resolved
    for segment in reversed(segments[:-1]):
        resolved = _direct_label(segment)
        if resolved:
            return resolved
    return None


# --------------------------------------------------------------------------------------- page

def _cells_of_block(rows: list[list[dict[str, Any]]], indices: list[int], table_no: int,
                    header_rows: list[list[dict[str, Any]]], page_unit: tuple[str, float] | None,
                    basis: str | None, filing_date: Any, page_no: int) -> list[dict[str, Any]]:
    block = [rows[i] for i in indices]
    anchors = _anchors_of(block)
    if not anchors:
        return []
    label_x = [token["x0"] for row in block for token in row
               if not token["num"] and len(token["text"]) > 2]
    if len(anchors) > 1 and label_x and anchors[0] < statistics.median(label_x):
        anchors = anchors[1:]                     # the printed row-number column
    gap = min((b - a for a, b in zip(anchors, anchors[1:])), default=60.0)
    left = anchors[0] - max(gap, 40.0)
    headers = _headers(header_rows, anchors, left)
    unit = _unit_of(" ".join(token["text"] for row in header_rows for token in row)) or page_unit
    data_rows = [row for row in block if any(token["num"] and token["x1"] > left + 2
                                             for token in row)]
    labeled_rows = [row for row in data_rows
                    if any(token["x1"] <= left + 2 and _ALPHA.search(token["text"])
                           for token in row)]
    if len(data_rows) >= 2 and len(labeled_rows) < 0.5 * len(data_rows):
        return []                                 # scattered call-outs, not a labelled table
    cells: list[dict[str, Any]] = []
    section = ""
    for row_no, index in enumerate(indices):
        row = rows[index]
        label_tokens = [token for token in row if token["x1"] <= left + 2]
        data = [token for token in row if token["num"] and token["x1"] > left + 2]
        first = next((token for token in row if token["text"].strip()), None)
        numbered = bool(first is not None and first["x1"] <= left + 2
                        and ROWNUM.match(first["text"]))
        if numbered:
            section = ""                          # a new numbered row group ends the section
            label_tokens = [token for token in label_tokens if token is not first]
        label = " ".join(token["text"] for token in label_tokens).strip()
        if not data:
            if label:
                section = label
            continue
        row_label = f"{section} > {label}" if section and label else (label or section or None)
        for token in data:
            column = min(range(len(anchors)), key=lambda k: abs(anchors[k] - token["x1"]))
            if abs(anchors[column] - token["x1"]) > max(8.0, 0.45 * gap):
                column = -1
            value, percent = _number(token["text"])
            if percent:
                unit_text, scale, value = "%", 1.0, value
            elif unit is not None:
                unit_text, scale = unit
                value = None if value is None else round(value * scale, 2)
            else:
                unit_text, scale, value = None, None, None
            cells.append({
                "page": page_no, "table_no": table_no, "row_no": row_no,
                "col_no": column, "row_label": row_label,
                "col_header": headers[column] if column >= 0 else None,
                "period_id": period_from_header(headers[column] if column >= 0 else None,
                                                filing_date),
                "basis": basis, "value_text": token["text"], "value": value,
                "unit_text": unit_text, "scale": scale,
                "bbox": f"{token['x0']:.1f},{token['y0']:.1f},{token['x1']:.1f},{token['y1']:.1f}",
                "method": "text_layer"})
    return cells


def extract_page(page: Any, pno: int, filing_date: Any = None) -> list[dict[str, Any]]:
    """Every table cell printed on one page, as ``table_cell`` column dicts (minus ids)."""
    height = float(page.rect.height)
    basis = _basis(page)
    page_unit = _unit_of(_top_text(page, height))
    rows = [_tokens(row) for row in _rows_of(page.get_text("words"))]

    blocks: list[list[int]] = []
    current: list[int] = []
    gap = 0
    for i, row in enumerate(rows):
        numbers = _numeric_count(row)
        if numbers >= 2:
            current.append(i)
            gap = 0
        elif current and gap < 2 and numbers == 0:
            current.append(i)
            gap += 1
        else:
            if sum(1 for j in current if _numeric_count(rows[j]) >= 2) >= 2:
                blocks.append(current)
            current, gap = ([i] if numbers >= 2 else []), 0
    if sum(1 for j in current if _numeric_count(rows[j]) >= 2) >= 2:
        blocks.append(current)

    cells: list[dict[str, Any]] = []
    previous_end = -1
    for table_no, indices in enumerate(blocks):
        while indices and _numeric_count(rows[indices[-1]]) < 2:
            indices = indices[:-1]
        if not indices:
            previous_end = blocks[table_no][-1]
            continue
        cells.extend(_cells_of_block(rows, indices, table_no, rows[previous_end + 1:indices[0]],
                                     page_unit, basis, filing_date, pno))
        previous_end = indices[-1]
    return cells


def extract(pdf_path: str, filing_date: Any = None,
            stats: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Every table cell of a PDF; ``stats`` (optional) collects pages, no-text and no-table pages."""
    if stats is None:
        stats = {}
    for key in ("pages", "pages_no_text", "pages_no_table"):
        stats.setdefault(key, 0)
    cells: list[dict[str, Any]] = []
    with pymupdf.open(pdf_path) as document:
        stats["pages"] += len(document)
        for number in range(len(document)):
            page = document[number]
            if not str(page.get_text("text")).strip():
                stats["pages_no_text"] += 1
                continue
            found = extract_page(page, number + 1, filing_date)
            if not found:
                stats["pages_no_table"] += 1
            cells.extend(found)
    return cells
