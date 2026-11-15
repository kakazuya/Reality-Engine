"""T-178: can the first build be salvaged by re-keying? (script only, no model calls)

Arms on the 30 deck reference pages (``in_first_build=True`` in ``pages.csv``; the first-build
results/AR pages are not in it):

* ``a_script``  round-10 script cells: :func:`reality_engine.v2.table_cells.extract` on the page
  PDF (``PARSE_VERSION`` t132-cells-5).  The stored ``run_script_r10`` directory has rows for only
  7 of the 30 deck pages (39 of its 60 files are ``[]``), so the same extractor is re-run on every
  page for a uniform arm.
* ``b_stored``  ``deck_figures.facts`` as stored (``is_final=1``), no verification.
* ``c_rekey``   those facts kept only when the printed number appears in the page text layer, then
  re-keyed: label -> metric through the built v2 label map, period -> fiscal label through
  :mod:`reality_engine.v2.periods` (stored period text first, page-text header second).
* ``d_union``   ``a`` plus ``c``, with same-row same-column different-value pairs flagged.

Recall/precision reuse :func:`reality_engine.v2.truth_score.match`; truth is
``reference_cells.csv`` for the page.

Also: a 200-report fiscal-year check (seed 178) on ``ar_docs`` — the year is derived from the report's
text layer through :mod:`reality_engine.raw_store` when the PDF is reachable, else from the report's own
quoted year phrases in ``ar_facts`` (a proxy, labelled ``method=quotes``); a coverage count for the 93
symbols of ``tg_build/build_queue.csv`` (counts only, no company names); and the decision.

Output: ``.tmp/t178/t178_first_build_rekey.xlsx`` with sheets ``arms``, ``fy_check``, ``coverage``,
``decision``.

    python -m reality_engine.scripts.t178_salvage --out .tmp/t178
"""
from __future__ import annotations

import argparse
import calendar
import csv
import os
import random
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

from reality_engine import raw_store
from reality_engine.config import resolve_stored_path
from reality_engine.db.readonly import connect_ro
from reality_engine.v2 import periods
from reality_engine.v2.label_map import _rows, canonical_key
from reality_engine.v2.page_words import pdf_words
from reality_engine.v2.reference_pages import _norm_value
from reality_engine.v2.reference_vote import col_key, label_key
from reality_engine.v2.table_cells import extract
from reality_engine.v2.truth_score import match

DEFAULT_REF = Path("D:/RealityEngine/v2/reference_pages")
DEFAULT_LABEL_MAP = Path("D:/RealityEngine/v2/label_map/label_map.db")
DEFAULT_QUEUE = Path("D:/RealityEngine/tg_build/build_queue.csv")
SINCE = "2024-04-01"
FY_SEED = 178
FY_SAMPLE = 200
ARMS = ("a_script", "b_stored", "c_rekey", "d_union")


# ----------------------------------------------------------------------------------- numbers
_BRACKETS = re.compile(r"^\((.*)\)$")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_TILDES = re.compile(r"[~\u2248\u2243]")
_MINUS = ("\u2212", "\u2013", "\u2014")


def norm_number(text: Any) -> str:
    """Printed figure -> comparison key: commas dropped, brackets negative, ``~`` and ``%`` stripped.

    >>> norm_number("(1,234.5)")
    '-1234.5'
    >>> norm_number("~84.71")
    '84.71'
    """
    s = " ".join(str(text or "").split())
    if not s:
        return ""
    negative = False
    bracket = _BRACKETS.match(s)
    if bracket:
        negative, s = True, bracket.group(1)
    for dash in _MINUS:
        s = s.replace(dash, "-")
    s = _TILDES.sub("", s).replace(",", "")
    found = _NUMBER.search(s)
    if not found:
        return ""
    value = found.group(0)
    if negative and not value.startswith("-"):
        value = "-" + value
    return value


def verbatim_numbers(words: Iterable[str]) -> set[str]:
    """The set of :func:`norm_number` keys the page's printed text layer carries."""
    return {number for number in (norm_number(word) for word in words) if number}


def appears_verbatim(printed: Any, numbers: set[str]) -> bool:
    """True when ``printed`` names one of the numbers the page prints (same normalisation)."""
    wanted = norm_number(printed)
    return bool(wanted) and wanted in numbers


# ----------------------------------------------------------------------------------- periods
_Q_RE = re.compile(r"(?<![A-Za-z0-9])Q\s?([1-4])\s*FY\s*'?((?:19|20)?\d{2})(?!\d)", re.I)
_H_RE = re.compile(r"(?<![A-Za-z0-9])H\s?([12])\s*FY\s*'?((?:19|20)?\d{2})(?!\d)", re.I)
_9M_RE = re.compile(r"(?<![A-Za-z0-9])9\s?M\s*FY\s*'?((?:19|20)?\d{2})(?!\d)", re.I)
_FY_RE = re.compile(r"(?<![A-Za-z])FY\s*'?((?:19|20)?\d{2})(?:\s*[-\u2013/]\s*(\d{2,4}))?(?!\d)", re.I)
_MON_RE = re.compile(
    r"(?<![A-Za-z])(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
    r"([\s\-\u2013'.,]*)((?:19|20)\d{2}|\d{2})(?!\d)", re.I)
_DAY_RE = re.compile(
    r"(?<![A-Za-z0-9])(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s,'.]*((?:19|20)\d{2})(?!\d)",
    re.I)
_MONTH_NO = {name: index + 1 for index, name in
             enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


def _add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _end_year(first: str, second: str | None = None) -> int:
    """End year of a printed fiscal pair: '25-26' -> 2026, '2025-26' -> 2026, 'FY26' -> 2026."""
    if second:
        return int(second) + 2000 if len(second) == 2 else int(second)
    return int(first) + 2000 if len(first) == 2 else int(first)


def _fy_span(end_year: int, quarter: int = 0, months: int = 12, second_half: bool = False) -> tuple[date, date]:
    start = date(end_year - 1, 4, 1)
    if quarter:
        span_start = _add_months(start, 3 * (quarter - 1))
        return span_start, _add_months(span_start, 3) - timedelta(days=1)
    if second_half:
        span_start = _add_months(start, 6)
        return span_start, _add_months(span_start, 6) - timedelta(days=1)
    return start, _add_months(start, months) - timedelta(days=1)


def _fiscal_label(start: date | None, end: date) -> str:
    try:
        return periods.fiscal_label(start, end)
    except ValueError:
        return ""


def _slice(text: str) -> list[tuple[re.Match[str], str]]:
    """Every period-shaped match in ``text`` as ``(match, kind)``, in printed order.

    A bare ``FY26`` inside ``Q2 FY26`` (or ``9M FY25-26``) is the same printed period, not a second one.
    """
    strong: list[tuple[re.Match[str], str]] = []
    for regex, kind in ((_Q_RE, "quarter"), (_H_RE, "half"), (_9M_RE, "9m")):
        strong.extend((found, kind) for found in regex.finditer(text))
    spans = [(found.start(), found.end()) for found, _kind in strong]
    for found in _FY_RE.finditer(text):
        if not any(start <= found.start() and found.end() <= end for start, end in spans):
            strong.append((found, "fy"))
    strong.sort(key=lambda item: item[0].start())
    return strong


def _match_label(found: re.Match[str], kind: str) -> tuple[str, str]:
    """``(printed, fiscal label)`` for one period match; ``("", "")`` when it is not a span."""
    printed = " ".join(found.group(0).split())
    if kind == "quarter":
        start, end = _fy_span(_end_year(found.group(2)), quarter=int(found.group(1)))
    elif kind == "half":
        start, end = _fy_span(_end_year(found.group(2)), second_half=found.group(1) == "2")
    elif kind == "9m":
        start, end = _fy_span(_end_year(found.group(1)), months=9)
    else:
        start, end = _fy_span(_end_year(found.group(1), found.group(2)))
    return printed, _fiscal_label(start, end)


def period_label(printed: Any) -> str:
    """Fiscal label the printed period field names ('Q1 FY26' -> 'Q1FY26'), or ''."""
    text = " ".join(str(printed or "").split())
    text = re.sub(r"^(?:as\s+(?:at|on)|for\s+the\s+(?:quarter|year|half[ -]year|period)\s+ended)\s*", "",
                  text, flags=re.I)
    if not text or text in {"-", "\u2013", "\u2014"}:
        return ""
    for found, kind in _slice(text):
        label = _match_label(found, kind)[1]
        if label:
            return label
    return ""


def period_mentions(text: str) -> list[tuple[str, str]]:
    """Every printed period on a page as ``(printed, fiscal label)``, deduped by label."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for found, kind in _slice(text):
        printed, label = _match_label(found, kind)
        if label and label not in seen:
            seen.add(label)
            out.append((printed, label))
    for found in _DAY_RE.finditer(text):
        day, month, year = int(found.group(1)), found.group(2).lower(), int(found.group(3))
        try:
            point = date(year, _MONTH_NO[month[:3]], day)
        except ValueError:
            continue
        label = _fiscal_label(None, point)
        if label and label not in seen:
            seen.add(label)
            out.append((" ".join(found.group(0).split()), label))
    for found in _MON_RE.finditer(text):
        month, separator, year = found.group(1).lower()[:3], found.group(2), found.group(3)
        if len(year) == 2 and int(year) <= 31 and " " in separator and not any(
                mark in separator for mark in "-'\u2013/."):
            continue                     # "January 31" is a month and a day, not a month and a year
        end_year = _end_year(year)
        try:
            point = _month_end(date(end_year, _MONTH_NO[month], 1))
        except ValueError:
            continue
        label = _fiscal_label(None, point)
        if label and label not in seen:
            seen.add(label)
            out.append((" ".join(found.group(0).split()), label))
    return out


def _latest_quarter_label(filed: date) -> str:
    """Fiscal label of the latest quarter that ended on or before the filing date."""
    ends = [date(filed.year, month, _month_end(date(filed.year, month, 1)).day) for month in (3, 6, 9, 12)]
    ends += [date(filed.year - 1, 12, 31)]
    end = max(day for day in ends if day <= filed)
    start = date(end.year, end.month - 2, 1)
    return _fiscal_label(start, end)


def resolve_period(stored: Any, mentioned: Sequence[tuple[str, str]], filed: date | None,
                   infer: bool) -> tuple[str, str]:
    """``(printed header for matching, fiscal label)`` from the stored field, then the page text.

    The stored field is usually the printed column header, which is often not a period at all
    ("Var %", "yoy (%)", a segment name): it stays the header for matching but gets no fiscal
    label.  The page-text inference fills a header only when the model printed none.
    """
    text = " ".join(str(stored or "").split())
    label = period_label(text)
    header = text if text and text not in {"-", "\u2013", "\u2014"} else ""
    if label:
        return header, label
    if infer and not header and mentioned:
        if len(mentioned) == 1:
            return mentioned[0]
        if filed is not None:
            wanted = _latest_quarter_label(filed)
            for printed, found in mentioned:
                if found == wanted:
                    return printed, found
    return header, ""


def _filed_date(known_at: Any) -> date | None:
    text = str(known_at or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _filed_year(filed_at: Any) -> int | None:
    filed = _filed_date(filed_at)
    return filed.year if filed else None


# ------------------------------------------------------------------------------------- label map
def load_map_metrics(db_path: Path) -> dict[str, set[str]]:
    """``label_norm -> metrics`` from the built map, opened read-only (``load_map_metrics`` is rw)."""
    metrics: dict[str, set[str]] = defaultdict(set)
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        for label, metric in con.execute(
                "SELECT label_norm, metric FROM label_map WHERE metric IS NOT NULL AND metric <> ''"):
            metrics[str(label)].add(str(metric))
    finally:
        con.close()
    return dict(metrics)


def leaf_metrics(metrics: dict[str, set[str]]) -> dict[str, set[str]]:
    """``leaf label -> metrics`` so a context key's leaf still keys a printed label."""
    leaves: dict[str, set[str]] = defaultdict(set)
    for key, found in metrics.items():
        leaf = key.rsplit(" > ", 1)[-1]
        if " > " in key and leaf:
            leaves[leaf] |= found
    return dict(leaves)


def key_metric(raw: Any, metrics: dict[str, set[str]], leaves: dict[str, set[str]]) -> str:
    """The built map's metric for a printed label, '' when it has none."""
    text = canonical_key(str(raw or ""))
    if not text:
        return ""
    found = metrics.get(text) or leaves.get(text.rsplit(" > ", 1)[-1], set())
    return sorted(found)[0] if found else ""


# ------------------------------------------------------------------------------------- reference
def reference_pages(ref: Path) -> list[dict[str, Any]]:
    """The 30 deck reference pages (``in_first_build=True``), dev and frozen."""
    pages: list[dict[str, Any]] = []
    with (ref / "pages.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("in_first_build", "")).strip().lower() != "true":
                continue
            pages.append({"pid": row["page_id"], "split": row["split"],
                          "sha256": row["sha256"], "page": int(row["page"]),
                          "pdf": ref / "pdf_pages" / f"{row['page_id']}.pdf"})
    return pages


def reference_truth(ref: Path) -> dict[str, list[dict[str, str]]]:
    truth: dict[str, list[dict[str, str]]] = defaultdict(list)
    with (ref / "reference_cells.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            truth[row["page_id"]].append({"row_label": row.get("row_label", ""),
                                          "col_header": row.get("col_header", ""),
                                          "value": row.get("value_text", "")})
    return dict(truth)


def page_meta(data: Path, pages: Sequence[dict[str, Any]]) -> dict[tuple[str, int], str]:
    """``known_at`` per (sha256, page_no) from the deck pages table."""
    con = connect_ro(data / "deck_figures.db", timeout_s=60)
    try:
        marks = ",".join("?" * len(pages))
        rows = _rows(con, f"SELECT sha256, page_no, known_at FROM pages WHERE sha256 IN ({marks})",
                     [page["sha256"] for page in pages])
    finally:
        con.close()
    return {(str(row[0]), int(row[1])): str(row[2] or "") for row in rows}


def stored_facts(data: Path, sha256: str, page_no: int) -> list[dict[str, Any]]:
    con = connect_ro(data / "deck_figures.db", timeout_s=60)
    try:
        rows = _rows(con, "SELECT metric, period, raw_number, value, unit FROM facts "
                          "WHERE sha256=? AND page_no=? AND is_final=1 ORDER BY line_no", (sha256, page_no))
    finally:
        con.close()
    return [{"metric": row[0], "period": row[1], "raw_number": row[2], "value": row[3], "unit": row[4]}
            for row in rows]


def _printed_value(fact: dict[str, Any]) -> str:
    raw = str(fact.get("raw_number") or "").strip()
    if raw:
        return raw
    value = fact.get("value")
    return f"{value:g}" if isinstance(value, (int, float)) else ""


def script_cells(pdf: Path, filed: date | None) -> list[dict[str, Any]]:
    """Round-10 script cells on one page PDF, in the arms' cell shape."""
    cells: list[dict[str, Any]] = []
    for cell in extract(str(pdf), filed.isoformat() if filed else None, {}, "deck"):
        period_id = str(cell.get("period_id") or "")
        label = ""
        if period_id.startswith("/"):
            label = _fiscal_label(None, date.fromisoformat(period_id[1:]))
        elif "/" in period_id:
            start, _, end = period_id.partition("/")
            label = _fiscal_label(date.fromisoformat(start), date.fromisoformat(end))
        cells.append({"row_label": str(cell.get("row_label") or ""),
                      "col_header": str(cell.get("col_header") or ""),
                      "value": str(cell.get("value_text") or ""),
                      "period": label})
    return cells


# ---------------------------------------------------------------------------------------- scoring
def score(cells: Sequence[dict[str, Any]], truth: Sequence[dict[str, str]]) -> dict[str, int]:
    """Greedy match of the arm's cells against the page's reference cells (same matcher as truth_score).

    ``value_hits`` is a diagnostic only: cells whose printed value is some reference cell's value on the
    page, whatever their row/column (separates a wrong fact from a right fact keyed to the wrong row).
    """
    used: set[int] = set()
    figures = matched = keyed = resolved = verified = value_hits = 0
    values = {_norm_value(cell["value"]) for cell in truth}
    for cell in cells:
        if not any(char.isdigit() for char in str(cell.get("value") or "")):
            continue
        figures += 1
        if cell.get("keyed"):
            keyed += 1
        if cell.get("period"):
            resolved += 1
        if cell.get("verified"):
            verified += 1
        if _norm_value(cell.get("value", "")) in values:
            value_hits += 1
        found = match({"row_label": cell.get("row_label", ""), "col_header": cell.get("col_header", ""),
                       "value": cell.get("value", "")}, list(truth), used)
        if found is not None:
            used.add(found)
            matched += 1
    return {"cells": figures, "matched": matched, "found": len(used), "truth": len(truth),
            "keyed": keyed, "period": resolved, "verified": verified, "value_hits": value_hits}


def _same_row(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return label_key(left.get("row_label")) == label_key(right.get("row_label")) and col_key(
        left.get("col_header")) == col_key(right.get("col_header"))


def build_page_arms(page: dict[str, Any], facts: list[dict[str, Any]], words: Sequence[Any],
                    metrics: dict[str, set[str]], leaves: dict[str, set[str]],
                    filed: date | None) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """The four arms' cells for one page, plus the union's same-row value conflicts."""
    tokens = [word[4] for word in words]
    numbers = verbatim_numbers(tokens)
    text = " ".join(tokens)
    mentioned = period_mentions(text)
    script = script_cells(page["pdf"], filed)
    for cell in script:
        cell["keyed"] = key_metric(cell["row_label"], metrics, leaves)
        cell["verified"] = appears_verbatim(cell["value"], numbers)
    stored: list[dict[str, Any]] = []
    rekeyed: list[dict[str, Any]] = []
    for fact in facts:
        printed, label = resolve_period(fact.get("period"), mentioned, filed, infer=False)
        value = _printed_value(fact)
        cell = {"row_label": str(fact.get("metric") or ""), "col_header": printed, "value": value,
                "period": label, "keyed": key_metric(fact.get("metric"), metrics, leaves),
                "verified": appears_verbatim(value, numbers)}
        stored.append(cell)
        if not cell["verified"]:
            continue
        inferred_header, inferred_label = resolve_period(fact.get("period"), mentioned, filed, infer=True)
        rekeyed.append({"row_label": cell["row_label"], "col_header": inferred_header, "value": value,
                        "period": inferred_label, "keyed": cell["keyed"], "verified": True})
    conflicts = sum(1 for left in script for right in rekeyed
                    if _same_row(left, right) and norm_number(left["value"]) != norm_number(right["value"]))
    return {"a_script": script, "b_stored": stored, "c_rekey": rekeyed,
            "d_union": script + rekeyed}, conflicts


def arm_sheet(pages: Sequence[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for arm in ARMS:
        tally = {"pages": 0, "cells": 0, "matched": 0, "found": 0, "truth": 0,
                 "keyed": 0, "period": 0, "verified": 0, "value_hits": 0, "conflicts": 0}
        for page in pages:
            if split != "all" and page["split"] != split:
                continue
            tally["pages"] += 1
            tally["conflicts"] += page.get("conflicts", 0) if arm == "d_union" else 0
            for key, value in score(page[arm], page["truth"]).items():
                tally[key] += value
        cells = tally["cells"] or 1
        truth = tally["truth"] or 1
        rows.append({
            "arm": arm, "split": split, "pages": tally["pages"], "cells": tally["cells"],
            "matched": tally["matched"], "precision": round(tally["matched"] / cells, 4),
            "truth_cells": tally["truth"], "found": tally["found"],
            "recall": round(tally["found"] / truth, 4),
            "keyed": tally["keyed"], "keyed_share": round(tally["keyed"] / cells, 4),
            "period_resolved": tally["period"], "period_share": round(tally["period"] / cells, 4),
            "verbatim": tally["verified"], "verbatim_share": round(tally["verified"] / cells, 4),
            "value_only": tally["value_hits"],
            "value_only_share": round(tally["value_hits"] / cells, 4),
            "conflicts": tally["conflicts"]})
    return rows


# -------------------------------------------------------------------------------- fiscal year
_FY_PATTERNS = (
    re.compile(r"annual\s+report\s*[:\-\u2013]?\s*((?:19|20)\d{2})\s*[-\u2013/]\s*(\d{2,4})", re.I),
    re.compile(r"(?:year|period)\s+ended\s+(?:on\s+)?(?:[0-9]{1,2}(?:st|nd|rd|th)?\s+)?"
               r"(?:march|mar\.?)\s*,?\s*((?:19|20)\d{2})", re.I),
    re.compile(r"(?:financial|fiscal)\s+year\s*[:\-\u2013]?\s*((?:19|20)\d{2})\s*[-\u2013/]\s*(\d{2,4})", re.I),
    re.compile(r"\bFY\s*((?:19|20)\d{2})\s*[-\u2013/]\s*(\d{2,4})", re.I),
    re.compile(r"annual\s+report\s*[:\-\u2013]?\s*((?:19|20)\d{2})", re.I),
)


def derive_fiscal_year(text: str) -> int | None:
    """End year the report's own text names ('Annual Report 2024-25' -> 2025), or None."""
    for pattern in _FY_PATTERNS:
        found = pattern.search(text)
        if found:
            return _end_year(found.group(1), found.group(2) if found.lastindex and found.lastindex > 1 else None)
    return None


def pdf_text(path: Path, pages: int = 3) -> tuple[str, str]:
    """``(text of the first pages, error reason)`` from a local PDF's text layer."""
    chunks: list[str] = []
    for number in range(1, pages + 1):
        try:
            words = pdf_words(str(path), number)
        except Exception as exc:                       # noqa: BLE001 - report, never crash the sample
            return "\n".join(chunks), f"{type(exc).__name__}: {exc}"[:160]
        if not words:
            break
        chunks.append(" ".join(word[4] for word in words))
    return "\n".join(chunks), ""


def quote_evidence(data: Path, doc_id: int, pages: int = 0) -> str:
    """The document's own quoted text where it may name its year (fallback when no PDF is reachable)."""
    con = connect_ro(data / "ar_facts.db", timeout_s=60)
    try:
        rows = _rows(con, "SELECT quote FROM ar_facts WHERE doc_id=? AND quote<>'' AND "
                          "(quote LIKE '%nnual %eport%' OR quote LIKE '%year ended%' OR "
                          "quote LIKE '%inancial year%' OR quote LIKE '%iscal year%') ORDER BY page LIMIT 500",
                     (doc_id,))
    finally:
        con.close()
    return "\n".join(str(row[0]) for row in rows)


_YEAR_MENTION = (
    re.compile(r"annual\s+report\s*(?:for\s+the\s+year\s*)?[:\-\u2013]?\s*((?:19|20)\d{2})"
               r"\s*[-\u2013/]\s*(\d{2,4})", re.I),
    re.compile(r"(?:year|period)\s+ended\s+(?:on\s+)?(?:31(?:st)?\s+)?(?:march|mar\.?)\s*,?\s*"
               r"((?:19|20)\d{2})", re.I),
    re.compile(r"(?:financial|fiscal)\s+year\s*[:\-\u2013]?\s*((?:19|20)\d{2})\s*[-\u2013/]\s*(\d{2,4})", re.I),
)


def derive_fiscal_year_from_quotes(text: str, filed_year: int | None = None) -> int | None:
    """The year the document's own quotes name most often, or None on a tie/none.

    "for the year ended 31 March YYYY" wins when present: that phrase names the report's own period,
    while "financial year 2022-23" can be forward language in the directors' report.
    """
    for patterns in ((_YEAR_MENTION[1],), _YEAR_MENTION):
        counts: dict[int, int] = defaultdict(int)
        for pattern in patterns:
            for found in pattern.finditer(text):
                second = found.group(2) if (found.lastindex or 0) > 1 else None
                counts[_end_year(found.group(1), second)] += 1
        if not counts:
            continue
        ranked = sorted(counts.items(), key=lambda item: -item[1])
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            return None
        year = ranked[0][0]
        if filed_year is not None and year > filed_year:
            return None                      # a report cannot be for a year that has not ended by its filing
        return year
    return None


def fiscal_year_check(data: Path, sample: int, seed: int) -> tuple[list[dict[str, Any]],
                                                                  list[dict[str, Any]]]:
    """Read ``sample`` random ``ar_docs``, derive the year from the report and compare."""
    con = connect_ro(data / "ar_facts.db", timeout_s=60)
    try:
        rows = [{"doc_id": int(row[0]), "fiscal_year": row[1], "fiscal_year_source": row[2],
                 "path": row[3], "filed_at": row[4]}
                for row in _rows(con, "SELECT doc_id, fiscal_year, fiscal_year_source, path, filed_at "
                                      "FROM ar_docs ORDER BY doc_id")]
    finally:
        con.close()
    picked = random.Random(seed).sample(rows, min(sample, len(rows)))
    store = raw_store.default_store()
    paths = [resolve_stored_path(row["path"]) for row in picked]
    fetch_error = ""
    try:
        with store.prefetch(paths):
            details = [_fiscal_one(row, path, store, data) for row, path in zip(picked, paths)]
    except Exception as exc:                           # noqa: BLE001 - the fetch channel may be blocked
        fetch_error = f"{type(exc).__name__}: {exc}"[:200]
        details = [_fiscal_one(row, path, None, data) for row, path in zip(picked, paths)]
    for detail in details:
        detail["fetch_error"] = fetch_error
    return _fiscal_summary(details), details


def _fiscal_one(row: dict[str, Any], path: Path, store: Any, data: Path) -> dict[str, Any]:
    text, reason, method = "", "", "quotes"
    if path.is_file():
        text, reason = pdf_text(path)
        method = "pdf_text"
    elif store is not None:
        try:
            with store.local(path) as local:
                text, reason = pdf_text(Path(local))
            method = "pdf_text"
        except Exception as exc:                       # noqa: BLE001 - not local, not in the manifest
            reason = f"{type(exc).__name__}: {exc}"[:160]
    derived = (derive_fiscal_year(text) if method == "pdf_text"
               else derive_fiscal_year_from_quotes(quote_evidence(data, int(row["doc_id"])),
                                                   _filed_year(row.get("filed_at"))))
    stored = str(row.get("fiscal_year") or "")[:4]
    agree = bool(derived) and stored.isdigit() and int(stored) == derived
    return {"doc_id": int(row["doc_id"]), "stored_fiscal_year": stored, "derived_end_year": derived or "",
            "fiscal_year_source": str(row.get("fiscal_year_source") or ""), "method": method,
            "result": "agree" if agree else ("wrong" if derived else "underived"),
            "reason": reason}


def _fiscal_summary(details: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"sampled": 0, "derived": 0, "agree": 0, "wrong": 0})
    for detail in details:
        tally = by_key[(detail["method"], detail["fiscal_year_source"])]
        tally["sampled"] += 1
        if detail["derived_end_year"]:
            tally["derived"] += 1
            tally["agree" if detail["result"] == "agree" else "wrong"] += 1
    rows = []
    for (method, source), tally in sorted(by_key.items()):
        derived = tally["derived"] or 1
        rows.append({"method": method, "fiscal_year_source": source, "sampled": tally["sampled"],
                     "derived": tally["derived"], "agree": tally["agree"], "wrong": tally["wrong"],
                     "error_rate": round(tally["wrong"] / derived, 4) if tally["derived"] else ""})
    return rows


# ------------------------------------------------------------------------------------- coverage
def _queue(queue: Path) -> dict[str, list[dict[str, str]]]:
    tiers: dict[str, list[dict[str, str]]] = defaultdict(list)
    with queue.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            tiers[str(row.get("tier") or "all")].append(row)
    tiers["all"] = [row for rows in tiers.values() for row in rows]
    return dict(tiers)


def _marks(values: Sequence[str]) -> str:
    return ",".join("?" * len(values))


def coverage(data: Path, queue: Path) -> list[dict[str, Any]]:
    """Documents/pages/facts per tier since 2024-04-01.  Counts only; the queue is private."""
    tiers = _queue(queue)
    out: list[dict[str, Any]] = []
    deck_types = "upper(doc_type) IN ('DECK','INVESTOR_PRESENTATION')"
    for tier in sorted(tiers, key=lambda name: (name != "all", name)):
        rows = tiers[tier]
        isins = sorted({str(row.get("isin") or "").strip() for row in rows if row.get("isin")})
        symbols = sorted({str(row.get("symbol") or "").strip() for row in rows if row.get("symbol")})
        con = connect_ro(data / "deck_figures.db", timeout_s=60)
        try:
            marks, params = _marks(isins), [*isins, SINCE]
            docs = int(_rows(con, f"SELECT COUNT(DISTINCT sha256) FROM pages WHERE isin IN ({marks}) "
                                  f"AND {deck_types} AND known_at>=?", params)[0][0])
            pages = int(_rows(con, f"SELECT COUNT(*) FROM (SELECT DISTINCT sha256, page_no FROM pages "
                                   f"WHERE isin IN ({marks}) AND {deck_types} AND known_at>=?)", params)[0][0])
            facts = int(_rows(con, f"SELECT COUNT(*) FROM (SELECT DISTINCT sha256, page_no FROM pages "
                                   f"WHERE isin IN ({marks}) AND {deck_types} AND known_at>=?) p JOIN facts f "
                                   f"ON f.sha256=p.sha256 AND f.page_no=p.page_no AND f.is_final=1",
                              params)[0][0])
        finally:
            con.close()
        out.append({"tier": tier, "doc_type": "deck", "documents": docs, "pages": pages,
                    "facts": facts, "facts_per_doc": round(facts / docs, 1) if docs else 0})
        marks = _marks(symbols)
        con = connect_ro(data / "ar_facts.db", timeout_s=60)
        try:
            docs, pages = _rows(con, f"SELECT COUNT(*), COALESCE(SUM(n_pages),0) FROM ar_docs "
                                     f"WHERE symbol IN ({marks}) AND filed_at>=?", [*symbols, SINCE])[0]
            facts = int(_rows(con, f"SELECT COUNT(*) FROM ar_facts WHERE isin IN ({_marks(isins)}) "
                                   f"AND filed_at>=?", [*isins, SINCE])[0][0])
        finally:
            con.close()
        out.append({"tier": tier, "doc_type": "annual_report", "documents": int(docs), "pages": int(pages),
                    "facts": facts, "facts_per_doc": round(facts / int(docs), 1) if docs else 0})
        con = connect_ro(data / "concall_facts.db", timeout_s=60)
        try:
            docs = int(_rows(con, f"SELECT COUNT(*) FROM cc_docs WHERE symbol IN ({marks}) AND filed_at>=? "
                                  f"AND status='ok'", [*symbols, SINCE])[0][0])
            facts = int(_rows(con, f"SELECT COUNT(*) FROM cc_items i JOIN cc_docs d ON d.doc_id=i.doc_id "
                                   f"WHERE d.symbol IN ({marks}) AND d.filed_at>=? AND d.status='ok'",
                              [*symbols, SINCE])[0][0])
        finally:
            con.close()
        out.append({"tier": tier, "doc_type": "concall", "documents": docs, "pages": "",
                    "facts": facts, "facts_per_doc": round(facts / docs, 1) if docs else 0})
    return out


# ------------------------------------------------------------------------------------- decision
def decide(arms: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The ticket's rule: (c) wins when its recall >= (a)'s and its frozen precision >= 95%."""
    by_key = {(row["arm"], row["split"]): row for row in arms}
    recall_a = by_key[("a_script", "all")]["recall"]
    recall_c = by_key[("c_rekey", "all")]["recall"]
    precision_c = by_key[("c_rekey", "frozen")]["precision"]
    wins = recall_c >= recall_a and precision_c >= 0.95
    return {"recall_a": recall_a, "recall_c": recall_c, "precision_c_frozen": precision_c,
            "wins": wins}


def decision_sheet(arms: Sequence[dict[str, Any]], fy: Sequence[dict[str, Any]],
                   fetch_error: str) -> list[dict[str, Any]]:
    verdict = decide(arms)
    by_key = {(row["arm"], row["split"]): row for row in arms}
    frozen = [row for row in fy if row["method"] == "pdf_text"]
    rows = [
        {"key": "rule", "value": "(c) wins when its recall >= arm (a) AND its precision on frozen pages "
                                 ">= 95%; else audit-only"},
        {"key": "arm_a_recall_all", "value": verdict["recall_a"]},
        {"key": "arm_a_precision_frozen", "value": by_key[("a_script", "frozen")]["precision"]},
        {"key": "arm_c_recall_all", "value": verdict["recall_c"]},
        {"key": "arm_c_precision_frozen", "value": verdict["precision_c_frozen"]},
        {"key": "arm_c_value_only_share_all", "value": by_key[("c_rekey", "all")]["value_only_share"]},
        {"key": "arm_c_value_only_share_frozen", "value": by_key[("c_rekey", "frozen")]["value_only_share"]},
        {"key": "verdict", "value": "salvage (c wins)" if verdict["wins"] else "audit-only"},
        {"key": "deck_pages", "value": 30},
        {"key": "fy_sample", "value": sum(int(row["sampled"]) for row in fy)},
        {"key": "fy_derived", "value": sum(int(row["derived"]) for row in fy)},
        {"key": "fy_derived_from_pdf_text", "value": sum(int(row["derived"]) for row in frozen)},
        {"key": "fy_fetch_error", "value": fetch_error or "none"},
        {"key": "note", "value": "value_only is the share of the arm's printed values that occur among the "
                                 "page's reference values under any row/column: it separates a wrong fact from a "
                                 "right fact keyed to the wrong row. AR PDFs are not local on this machine and "
                                 "rclone cannot run in the worker sandbox, so fy rows with method=quotes derive "
                                 "the year from the report's own quoted text (a proxy, not the text layer)."},
    ]
    return rows


# ---------------------------------------------------------------------------------------- output
def write_xlsx(path: Path, arms: Sequence[dict[str, Any]], fy: Sequence[dict[str, Any]],
               fy_detail: Sequence[dict[str, Any]], coverage_rows: Sequence[dict[str, Any]],
               decision_rows: Sequence[dict[str, Any]]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet: Any = workbook.active
    sheet.title = "arms"
    _table(sheet, arms)
    fy_sheet = workbook.create_sheet("fy_check")
    _table(fy_sheet, fy)
    fy_sheet.append([])
    _table(fy_sheet, fy_detail, start=fy_sheet.max_row + 1)
    cover = workbook.create_sheet("coverage")
    _table(cover, coverage_rows)
    decided = workbook.create_sheet("decision")
    _table(decided, decision_rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def _table(sheet: Any, rows: Sequence[dict[str, Any]], start: int = 1) -> None:
    if not rows:
        return
    headers = list(rows[0])
    for column, header in enumerate(headers, start=1):
        sheet.cell(row=start, column=column, value=header)
    for offset, row in enumerate(rows, start=start + 1):
        for column, header in enumerate(headers, start=1):
            sheet.cell(row=offset, column=column, value=row.get(header))


# ------------------------------------------------------------------------------------------ main
def run(ref: Path, data: Path, label_map_path: Path, queue: Path, out: Path,
        fy_sample: int = FY_SAMPLE, fy_seed: int = FY_SEED, fy: bool = True) -> dict[str, Any]:
    pages = reference_pages(ref)
    truth = reference_truth(ref)
    meta = page_meta(data, pages)
    metrics = load_map_metrics(label_map_path)
    leaves = leaf_metrics(metrics)
    print(f"reference deck pages {len(pages)} (dev {sum(p['split'] == 'dev' for p in pages)}, "
          f"frozen {sum(p['split'] == 'frozen' for p in pages)}); label map {len(metrics):,} labels")
    for page in pages:
        known_at = meta.get((page["sha256"], page["page"]), "")
        page["filed"] = _filed_date(known_at)
        page["truth"] = truth.get(page["pid"], [])
        words = pdf_words(str(page["pdf"]), 1) if page["pdf"].is_file() else []
        facts = stored_facts(data, page["sha256"], page["page"])
        cells, conflicts = build_page_arms(page, facts, words, metrics, leaves, page["filed"])
        page.update(cells)
        page["conflicts"] = conflicts
        print(f"  {page['pid']} {page['split']:6} cells a={len(page['a_script']):3} b={len(page['b_stored']):3} "
              f"c={len(page['c_rekey']):3} truth={len(page['truth']):3}")
    arms = [row for split in ("dev", "frozen", "all") for row in arm_sheet(pages, split)]
    fy_rows: list[dict[str, Any]] = []
    fy_detail: list[dict[str, Any]] = []
    fetch_error = ""
    if fy:
        try:
            fy_rows, fy_detail = fiscal_year_check(data, fy_sample, fy_seed)
            fetch_error = next((str(detail.get("fetch_error") or "") for detail in fy_detail
                                if detail.get("fetch_error")), "")
        except Exception as exc:                       # noqa: BLE001 - a blocked fetch channel is reported
            fetch_error = f"{type(exc).__name__}: {exc}"[:200]
            fy_rows = [{"method": "none", "fiscal_year_source": "", "sampled": fy_sample, "derived": 0,
                        "agree": 0, "wrong": 0, "error_rate": "", "error": fetch_error}]
    else:
        fy_rows = [{"method": "skipped", "fiscal_year_source": "", "sampled": 0, "derived": 0,
                    "agree": 0, "wrong": 0, "error_rate": ""}]
    coverage_rows = coverage(data, queue)
    decisions = decision_sheet(arms, fy_rows, fetch_error)
    out.mkdir(parents=True, exist_ok=True)
    write_xlsx(out / "t178_first_build_rekey.xlsx", arms, fy_rows, fy_detail, coverage_rows, decisions)
    print(f"wrote {out / 't178_first_build_rekey.xlsx'}")
    for row in arms:
        if row["split"] == "all":
            print(f"  {row['arm']:9} cells {row['cells']:5} precision {row['precision']:.3f} "
                  f"recall {row['recall']:.3f} keyed {row['keyed_share']:.2f} "
                  f"period {row['period_share']:.2f} verbatim {row['verbatim_share']:.2f}")
    print(f"  decision {decisions[7]['value']}")
    return {"arms": arms, "fy": fy_rows, "coverage": coverage_rows, "decision": decisions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-178 first-build salvage test")
    parser.add_argument("--ref", type=Path, default=DEFAULT_REF, help="reference_pages directory")
    parser.add_argument("--data-root", type=Path,
                        default=Path(os.environ.get("REALITY_DATA_ROOT") or
                                     Path(__file__).resolve().parents[1] / "data"))
    parser.add_argument("--label-map", type=Path, default=DEFAULT_LABEL_MAP)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--out", type=Path, default=Path(".tmp/t178"))
    parser.add_argument("--fy-sample", type=int, default=FY_SAMPLE)
    parser.add_argument("--fy-seed", type=int, default=FY_SEED)
    parser.add_argument("--no-fy", action="store_true", help="skip the 200-report fiscal-year check")
    args = parser.parse_args(argv)
    run(args.ref, args.data_root, args.label_map, args.queue, args.out, args.fy_sample,
        args.fy_seed, not args.no_fy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
