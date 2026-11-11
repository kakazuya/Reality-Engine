"""T-177: per-page completeness report and its build gate. No model call, no OCR.

Answers, for every page of a pilot3 store, how much of what the page prints reached the
store.  One row per (store, doc_key, page) in ``page_coverage.csv`` and in a sidecar
SQLite ``completeness.db`` table ``page_coverage``:

    store, symbol, doc_key, sha256, doc_type, page,
    unread, numbers_printed, numbers_stored, number_coverage,
    grid_rows, grid_cols, grid_cells_printed, grid_cells_stored, grid_coverage,
    cells_built, sums_checked, sums_closed, sources, stored_values

Usage::

    python -m reality_engine.v2.completeness run --store D:/RealityEngine/p20/p20new.db \
        [--cells D:/RealityEngine/v2/p20_r10] --out <dir> [--symbols A,B] \
        [--types deck,results,annual_report]
    python -m reality_engine.v2.completeness gate --prev <page_coverage.csv> \
        --new <page_coverage.csv> [--tolerance 0.02]
    python -m reality_engine.v2.completeness calibrate --coverage <page_coverage.csv> \
        --reference <reference_cells.csv> --pages <pages.csv> --split dev

Definitions and exclusion rules (each one is enforced in the code, in this order):

``unread``
    1 when the store has no ``doc_page`` row for the page, or its text is empty or under
    30 characters.  An unread page is counted, never scored: every coverage column is
    empty, and a page that goes from scored to unread fails the gate.

``numbers_printed``
    The distinct value-numbers printed in the page's text layer.  A value is one printed
    figure after number words are converted ("twenty-five" -> 25) and a scale word printed
    right after it is applied ("25 crore" -> forms 25 and 250,000,000; a figure is stored
    either as the printed magnitude or in base units, so both are matched).  Scale words:
    thousand 1e3, lakh/lac 1e5, crore/cr 1e7, million/mn 1e6, billion/bn 1e9.  A number
    word is only a value when a scale word, ``%``/``percent``/``bps`` or a physical unit
    follows it ("one of the largest" is prose and is not counted).  Printed figures are
    dropped when they are:

    - a date or a period: ``31.03.2026``, ``31/03/26``, ``31 March 2026``, ``March 31,
      2026``, ``Mar-25``, ``Mar'24``, ``Q2FY27``, ``H1 FY27``, ``9M 25-26``, ``FY2025-26``,
      ``2025-26``;
    - a year standing alone (1900-2100 as an integer);
    - a page number: ``Page 7``, ``Page 7 of 9``, ``7 of 9``, a whole line that is only
      the page's own folio;
    - a note / serial number: a line-leading 1-2 digit row number before a word (``1.
      Revenue``, ``12) Other``), and a number named beside ``Note``, ``Notes``,
      ``Sr. No.``, ``Sl. No.``, ``S. No.``, ``Clause``, ``Section``, ``Annexure``,
      ``Schedule``, ``Chapter``;
    - a footnote mark: ``(1)``/``(12)`` glued to the end of a word;
    - below 1, or a bare year (the ``keep`` rule of
      ``reality_engine.scripts.extract_deck_figures``, reused by import).

    A figure that appears twice is one printed value (distinct values, not occurrences).

``numbers_stored``
    Of those printed values, how many appear as a value in a stored row that cites this
    document and page: the v2 ``table_cell`` rows of the company files under ``--cells``
    (its ``value``, ``value/scale`` and printed ``value_text``) plus every table in the
    pilot3 store that carries both ``doc_key`` and ``page``.  That is discovered from the
    schema, not assumed: on u8/p20/q12 it is ``kpi_series``, ``fin_quarter_printed``,
    ``fin_annual_line``, ``guidance``, ``transcript_statement``, ``rating_event``,
    ``related_party_txn`` and ``concentration``; ``*_input`` tables are extraction inputs
    and are skipped, and a statement's prose ``quote`` is not a value.  A stored numeric
    value is matched as itself and divided by its printed scale (the store keeps base
    units in ``fin_*`` and printed magnitude with a ``unit``/``scale`` pair in
    ``kpi_series``); a row's own printed token (``raw_token``/``raw_value``/``value_text``)
    is matched too.  ``number_coverage = numbers_stored / numbers_printed``.

``grid_rows``, ``grid_cols``, ``grid_cells_printed``
    From the PDF's word boxes (the store only keeps flat text): a grid is a run of two or
    more consecutive printed rows that each hold two or more figures aligned to the same
    right-edge column anchors.  Rows, columns and aligned figures are summed over the
    page's grids.  The column-anchor logic is imported from
    ``reality_engine.v2.table_cells`` (``_rows_of``, ``_tokens``, ``_anchors_of``), not
    copied.  A page whose PDF is missing on disk or cannot be opened has empty grid
    columns, never zero: "not measurable" is not "nothing printed".

``grid_cells_stored``, ``grid_coverage``
    The v2 ``table_cell`` rows on the page that carry a value, when ``--cells`` covers the
    document (``cells_built=1``).  ``grid_coverage`` is capped at 1: the printed grid and
    the stored grid are found by different passes, so stored cells beyond this page's
    detected grid are not extra misses.  Without a cell store for the document both
    columns are empty.

``sums_checked``, ``sums_closed``
    Arithmetic closure of stored rows: for a stored ``table_cell`` whose row label starts
    with ``Total``, ``Sub-total`` or ``Net`` (case-insensitive), the stored cells above it
    in the same table and column - down to the previous total-labelled row - are added
    and compared with it.  Checked only when the total and at least two parts are stored;
    closed when ``|parts - total| <= max(0.5, 0.5% of total)`` (the reference pages'
    ``sums_ok`` tolerance).  Zero without a cell store.

``sources``
    The tables whose stored values matched a printed value on this page, ``+``-joined;
    ``stored_values`` is the sorted ``|``-joined set of stored magnitudes the page was
    scored against (it lets :func:`calibrate` compute reference recall from the CSV alone).
    ``cells_built`` is 1 when the document is present in the ``--cells`` store.

Gate rule (:func:`gate`): the pages are keyed by ``(store, doc_key, page)``.  Exit 1 and
list the page when a page's ``number_coverage`` or ``grid_coverage`` falls by more than
``--tolerance`` (absolute difference, default 0.02), when a page goes from scored to
``unread``, or when a page present in the previous report is missing from the new one.
Exit 0 when no page regresses.  This is the check that catches a dropped table column: a
column that vanishes lowers the page's number coverage even though every surviving cell
is still stored.  New pages (missing from the previous report) are reported but never
fail the gate.

Calibration (:func:`calibrate`) joins the coverage CSV to ``pages.csv`` by
``(sha256, page)`` for the chosen split only (``frozen`` rows are refused; the split is
never read), computes each page's reference recall = share of that page's reference cells
whose normalised value is in ``stored_values``, and reports the per-page table, the
Pearson correlation of coverage against recall, and the 0.8 disagreement counts
(hits = coverage < 0.8 and recall < 0.8, misses = coverage >= 0.8 and recall < 0.8,
false alarms = coverage < 0.8 and recall >= 0.8).

Notes: stores are opened read-only through :func:`reality_engine.db.readonly.connect_ro`
and every query is per document or over one explicit ``doc_key`` list; the only write is
``--out``.  The SQLite file is a report sidecar: rows for the stores in the run are
replaced, other stores' rows are kept; the CSV is written fresh.
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import pymupdf

from reality_engine.db.readonly import connect_ro
from reality_engine.scripts.extract_deck_figures import keep, parse_number
from reality_engine.v2.table_cells import (  # noqa: PLC2701 - the column-anchor logic is reused, not copied
    _ANCHOR_TOL,
    _anchors_of,
    _rows_of,
    _tokens,
)

__all__ = ["calibrate", "gate", "main", "printed_values", "run"]

FIELDS = [
    "store", "symbol", "doc_key", "sha256", "doc_type", "page",
    "unread", "numbers_printed", "numbers_stored", "number_coverage",
    "grid_rows", "grid_cols", "grid_cells_printed", "grid_cells_stored",
    "grid_coverage", "cells_built", "sums_checked", "sums_closed",
    "sources", "stored_values",
]

_UNREAD_CHARS = 30
_TOTAL_LABEL = re.compile(r"^\s*(?:total|sub[\s-]*total|net)\b", re.I)

# ------------------------------------------------------------------ document types
_TYPE_ALIAS = {
    "investor_presentation": "deck",
    "presentation": "deck",
    "quarterly_results": "results",
    "financial_results": "results",
    "annual_report": "annual_report",
    "annual report": "annual_report",
}
DEFAULT_TYPES = "deck,results,annual_report"


def _doc_type(value: str) -> str:
    text = (value or "").strip().lower()
    return _TYPE_ALIAS.get(text, text)


def _store_label(path: Path) -> str:
    parent = path.parent.name
    if parent in ("p20", "u8", "q12"):
        return parent
    return "p20" if path.stem == "p20new" else path.stem


# ------------------------------------------------------------------ printed numbers
_MONTH = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*")
_DATE_PATTERNS = [
    r"\b\d{1,4}[./-]\d{1,2}[./-]\d{1,4}\b",
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\.?\s+{_MONTH}\.?,?\s+\d{{2,4}}\b",
    rf"\b{_MONTH}\.?\s+\d{{1,2}},?\s+\d{{2,4}}\b",
    rf"\b{_MONTH}['’\-. ]\d{{2,4}}\b",
    r"\b(?:q[1-4]|h[12]|9m|ytd|fy)\s*[- ]?\s*(?:fy\s*)?\d{2,4}(?:\s*[-–]\s*\d{2,4})?\b",
    r"\b(?:19|20)\d{2}\s*[-–]\s*(?:19|20)?\d{2}\b",
]
_DATE_RE = re.compile("|".join(_DATE_PATTERNS), re.I)
_PAGE_REF = re.compile(r"\bpage\s+\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\b", re.I)
_NOTE_REF = re.compile(
    r"\b(?:note|notes|sr\.?\s*no\.?|sl\.?\s*no\.?|s\.?\s*no\.?|clause|section|annexure|"
    r"schedule|chapter)\s*(?:no\.?\s*)?[:\-]?\s*\(?\d{1,3}(?:\.\d{1,2})?\)?",
    re.I,
)
_WHOLE_FOLIO = re.compile(r"^\s*\(?\d{1,4}\)?\s*(?:of|/)\s*\(?\d{1,4}\)?\s*$")
_NUM_TOKEN = re.compile(r"(?<![A-Za-z\d.])[-+]?\d[\d,]*(?:\.\d+)?%?(?![A-Za-z\d])")
_FOOTNOTE = re.compile(r"^\d{1,2}$")

_SCALES: dict[str, float] = {
    "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
    "crore": 1e7, "crores": 1e7, "cr": 1e7, "crs": 1e7,
    "million": 1e6, "millions": 1e6, "mn": 1e6,
    "billion": 1e9, "billions": 1e9, "bn": 1e9,
}
_SCALE_AFTER = re.compile(
    r"^\s*(?:₹|rs\.?|inr)?\s*(thousand|lakhs?|lacs?|crores?|crs?|millions?|mn|billions?|bn)\b",
    re.I,
)
_UNIT_WORDS = {"percent", "pct", "bps", "bp", "pp", "tonnes", "tonne", "mt", "mw", "gw",
               "kwh", "teu", "teus", "times", "x", "mn", "lakh", "crore"}

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
         "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
         "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_WORD = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)?")


def _scale_after(line: str, pos: int) -> float | None:
    match = _SCALE_AFTER.match(line, pos)
    if not match:
        return None
    return _SCALES.get(match.group(1).lower())


def _token_value(token: str) -> float | None:
    try:
        value = parse_number(token)
    except (TypeError, ValueError):
        return None
    if value is None:
        return None
    value = abs(value)
    return round(value, 2) if keep(value) else None


def _read_number_words(words: list[tuple[str, int, int]], start: int) -> tuple[float, int] | None:
    """'twenty-five' at ``start`` -> (25, index after the run); None when not a number word."""
    total = 0.0
    used = False
    index = start
    while index < len(words):
        for part in words[index][0].lower().split("-"):
            if part in _ONES:
                total += _ONES[part]
            elif part in _TENS:
                total += _TENS[part]
            elif part == "hundred":
                total = (total or 1.0) * 100
            elif part == "and":
                pass
            else:
                return (total, index) if used and total else None
        used = True
        index += 1
    return (total, index) if used and total else None


def _word_forms(line: str) -> list[set[float]]:
    """A number word (or run) followed by a scale word, %, bps or a unit is a value."""
    words = [(match.group(0), match.start(), match.end()) for match in _WORD.finditer(line)]
    out: list[set[float]] = []
    index = 0
    while index < len(words):
        read = _read_number_words(words, index)
        if read is None:
            index += 1
            continue
        value, after = read
        following = words[after][0].lower() if after < len(words) else ""
        if value >= 1 and (following in _SCALES or following in _UNIT_WORDS):
            forms = {round(value, 2)}
            if following in _SCALES:
                forms.add(round(value * _SCALES[following], 2))
            out.append(forms)
        index = max(after, index + 1)
    return out


def printed_values(text: str, page_no: int) -> list[set[float]]:
    """The distinct value-numbers one page prints, each as the set of magnitudes it may be
    stored as (printed magnitude and base units after its scale word).  Rules: module
    docstring."""
    out: list[set[float]] = []
    for raw in (text or "").splitlines():
        line = _PAGE_REF.sub(" ", raw)
        line = _NOTE_REF.sub(" ", line)
        line = _DATE_RE.sub(" ", line)
        if _WHOLE_FOLIO.match(line):
            continue
        stripped = line.strip().strip("()")
        if re.fullmatch(r"\d{1,4}", stripped) and int(stripped) == page_no:
            continue                                      # the page's own folio
        matches = list(_NUM_TOKEN.finditer(line))
        values: list[tuple[Any, float]] = []
        for match in matches:
            value = _token_value(match.group(0))
            if value is not None:
                values.append((match, value))
        # A line-leading 1-2 digit number before a word is a printed row/section number.
        leading = len(line) - len(line.lstrip())
        if len(values) > 1 and values[0][0].start() <= leading + 2 \
                and values[0][0].group(0).isdigit() and len(values[0][0].group(0)) <= 2:
            rest = line[values[0][0].end():].lstrip(" \t.)]}:")
            if rest[:1].isalpha():
                values = values[1:]
        for match, value in values:
            if _FOOTNOTE.match(match.group(0)) and match.start() > 0 \
                    and line[match.start() - 1] == "(" and line[match.end():].startswith(")"):
                continue                                  # a footnote mark: 'Revenue(1)'
            forms = {value}
            scale = _scale_after(line, match.end())
            if scale:
                forms.add(round(value * scale, 2))
            out.append(forms)
        out.extend(_word_forms(line))
    unique: list[set[float]] = []
    seen: set[tuple[float, ...]] = set()
    for forms in out:
        key = tuple(sorted(forms))
        if key not in seen:
            seen.add(key)
            unique.append(forms)
    return unique


# ------------------------------------------------------------------ stored values
# A statement's quote and a count/id column are not values; an extraction-input table
# repeats a value already held by its output table.
_SKIP_TABLES = {"doc", "doc_page", "doc_alias", "period", "table_cell", "statement"}
_VALUE_NAMES = {"value", "low", "high", "amount", "balance", "pct", "ratio", "count"}
_TOKEN_COLUMNS = {"raw_token", "raw_value", "value_text", "printed_value"}
_DENY_COLUMNS = {"id", "page", "scale", "conf_rank", "ocr_conf", "seq", "rowid", "known_at"}
_NUMERIC_TYPES = ("REAL", "INTEGER", "NUMERIC", "FLOAT", "DOUBLE", "DECIMAL")


def _query(con: Any, sql: str, params: Iterable[Any] = ()) -> list[Any]:
    """Rows of one bounded statement (``connect_ro`` can type ``execute`` as optional)."""
    cursor = con.execute(sql, tuple(params))
    return list(cursor) if cursor is not None else []


def _table_columns(con: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    return [(str(row[1]), str(row[2] or "")) for row in _query(con, f'PRAGMA table_info("{table}")')]


def _fact_tables(con: sqlite3.Connection) -> list[str]:
    """Tables that cite both a document and a page (discovered, never assumed)."""
    names = [str(row[0]) for row in _query(
        con, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    out = []
    for name in names:
        if name in _SKIP_TABLES or name.endswith("_input") or "_fts" in name:
            continue
        columns = {column for column, _ in _table_columns(con, name)}
        if {"doc_key", "page"} <= columns:
            out.append(name)
    return out


def _value_columns(con: sqlite3.Connection, table: str) -> tuple[list[str], list[str]]:
    numeric: list[str] = []
    printed: list[str] = []
    for column, kind in _table_columns(con, table):
        if column in _TOKEN_COLUMNS:
            printed.append(column)
        elif column not in _DENY_COLUMNS and (
                kind.upper() in _NUMERIC_TYPES or column in _VALUE_NAMES):
            numeric.append(column)
    return numeric, printed


def _number_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _store_forms(value: Any, scale: Any) -> set[float]:
    number = _number_or_none(value)
    if number is None:
        return set()
    forms = {round(abs(number), 2)}
    factor = _number_or_none(scale)
    if factor and factor > 1:
        forms.add(round(abs(number) / factor, 2))
    return forms


def _chunks(items: list[str], size: int = 400) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def load_fact_values(store: Path, doc_keys: list[str]) -> dict[tuple[str, int], dict[str, set[float]]]:
    """(doc_key, page) -> table -> the value magnitudes a stored row cites there."""
    stored: dict[tuple[str, int], dict[str, set[float]]] = {}
    con = connect_ro(store, timeout_s=60)
    con.row_factory = sqlite3.Row
    try:
        for table in _fact_tables(con):
            numeric, printed = _value_columns(con, table)
            if not numeric and not printed:
                continue
            columns = {column for column, _ in _table_columns(con, table)}
            has_scale = "scale" in columns
            wanted = list(dict.fromkeys(numeric + printed + (["scale"] if has_scale else [])))
            select = ", ".join(f'"{column}"' for column in ["doc_key", "page", *wanted])
            for chunk in _chunks(doc_keys):
                sql = (f'SELECT {select} FROM "{table}" WHERE doc_key IN '
                       f'({",".join("?" * len(chunk))})')
                for row in _query(con, sql, chunk):
                    record = {name: row[name] for name in row.keys()}
                    try:
                        page = int(record["page"])
                    except (TypeError, ValueError):
                        continue
                    key = (str(record["doc_key"]), page)
                    forms: set[float] = set()
                    for column in numeric:
                        forms |= _store_forms(record.get(column),
                                              record.get("scale") if has_scale else None)
                    for column in printed:
                        text = record.get(column)
                        if isinstance(text, str):
                            for match in _NUM_TOKEN.finditer(text):
                                parsed = _token_value(match.group(0))
                                if parsed is not None:
                                    forms.add(parsed)
                    if forms:
                        stored.setdefault(key, {}).setdefault(table, set()).update(forms)
    finally:
        con.close()
    return stored


def load_cells(cells_dir: Path, doc_keys: set[str]) -> tuple[
        dict[tuple[str, int], list[dict[str, Any]]], set[str]]:
    """table_cell rows per (doc_key, page) and the documents the cell store covers."""
    cells: dict[tuple[str, int], list[dict[str, Any]]] = {}
    built: set[str] = set()
    directory = cells_dir / "company"
    if not directory.is_dir():
        raise FileNotFoundError(f"no company/ directory under {cells_dir}")
    for path in sorted(directory.glob("*.db")):
        con = connect_ro(path, timeout_s=60)
        try:
            present = {str(row[0]) for row in _query(con, "SELECT doc_key FROM doc")}
            wanted = present & doc_keys
            if not wanted:
                continue
            built |= wanted
            for chunk in _chunks(sorted(wanted)):
                sql = ("SELECT doc_key, page, table_no, row_no, col_no, row_label, value, "
                       "value_text, scale FROM table_cell WHERE doc_key IN "
                       f"({','.join('?' * len(chunk))})")
                for row in _query(con, sql, chunk):
                    doc_key, page, table_no, row_no, col_no, label, value, text, scale = row
                    key = (str(doc_key), int(page))
                    forms = _store_forms(value, scale)
                    for match in _NUM_TOKEN.finditer(str(text or "")):
                        parsed = _token_value(match.group(0))
                        if parsed is not None:
                            forms.add(parsed)
                    cells.setdefault(key, []).append({
                        "table_no": int(table_no), "row_no": int(row_no),
                        "col_no": int(col_no), "row_label": str(label or ""),
                        "value": _number_or_none(value), "forms": forms,
                    })
        finally:
            con.close()
    return cells, built


# ------------------------------------------------------------------ grid from the PDF
def grid_cells(page: Any) -> tuple[int, int, int]:
    """(rows, columns, printed cells) of the tables on one pymupdf page."""
    words = page.get_text("words")
    if not words:
        return 0, 0, 0
    rows = _rows_of(words)
    rows_out = cols_out = cells_out = 0
    block: list[list[dict[str, Any]]] = []

    def flush() -> None:
        nonlocal rows_out, cols_out, cells_out, block
        if len(block) >= 2:
            anchors = _anchors_of(block)
            if len(anchors) >= 2:
                for tokens in block:
                    aligned = [token for token in tokens if token.get("num")
                               and min(abs(token["x1"] - anchor) for anchor in anchors) <= _ANCHOR_TOL]
                    if len(aligned) >= 2:
                        rows_out += 1
                        cells_out += len(aligned)
                cols_out += len(anchors)
        block = []

    for row in rows:
        tokens = _tokens(row)
        if sum(1 for token in tokens if token.get("num")) >= 2:
            block.append(tokens)
        else:
            flush()
    flush()
    return rows_out, cols_out, cells_out


# ------------------------------------------------------------------ sums
def arithmetic_closure(page_cells: list[dict[str, Any]]) -> tuple[int, int]:
    """(checked, closed): stored parts above a Total/Sub-total/Net row add up to it."""
    checked = closed = 0
    columns: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for cell in page_cells:
        if cell["value"] is not None:
            columns.setdefault((cell["table_no"], cell["col_no"]), []).append(cell)
    for rows in columns.values():
        rows.sort(key=lambda cell: cell["row_no"])
        previous_total = -1
        for cell in rows:
            if not _TOTAL_LABEL.match(cell["row_label"]):
                continue
            parts = [row["value"] for row in rows
                     if previous_total < row["row_no"] < cell["row_no"]]
            previous_total = cell["row_no"]
            if len(parts) < 2 or cell["value"] is None:
                continue
            checked += 1
            total = float(cell["value"])
            if abs(sum(float(part) for part in parts if part is not None) - total) \
                    <= max(0.5, 0.005 * abs(total)):
                closed += 1
    return checked, closed


# ------------------------------------------------------------------ run
def _num(value: Any, digits: int = 4) -> Any:
    if value is None:
        return ""
    number = round(float(value), digits)
    return int(number) if digits == 0 else number


def _open_pdf(path: str) -> Any:
    try:
        if path and Path(path).is_file():
            return pymupdf.open(path)
    except Exception:
        pass
    return None


def _coverage_row(store: str, symbol: str, doc_key: str, sha256: str, doc_type: str,
                  page_no: int, text: str, pdf_page: Any,
                  page_cells: list[dict[str, Any]], covered: bool,
                  fact_values: dict[str, set[float]]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "store": store, "symbol": symbol, "doc_key": doc_key, "sha256": sha256,
        "doc_type": doc_type, "page": page_no,
    }
    if len((text or "").strip()) < _UNREAD_CHARS:
        row.update({field: "" for field in FIELDS if field not in row})
        row.update({"unread": 1, "numbers_printed": 0, "numbers_stored": 0,
                    "cells_built": int(covered), "sums_checked": "", "sums_closed": "",
                    "sources": "", "stored_values": ""})
        return row
    printed = printed_values(text, page_no)
    cell_values: dict[str, set[float]] = {}
    for cell in page_cells:
        cell_values.setdefault("table_cell", set()).update(cell["forms"])
    stored: dict[str, set[float]] = {}
    for source, values in list(fact_values.items()) + list(cell_values.items()):
        if values:
            stored.setdefault(source, set()).update(values)
    union = set().union(*stored.values()) if stored else set()
    matched = sum(1 for forms in printed if forms & union)
    sources = [name for name, values in sorted(stored.items())
               if any(forms & values for forms in printed)]
    row.update({
        "unread": 0,
        "numbers_printed": len(printed),
        "numbers_stored": matched,
        "number_coverage": _num(matched / len(printed)) if printed else "",
    })
    if pdf_page is not None:
        try:
            rows, cols, printed_cells = grid_cells(pdf_page)
        except Exception:
            rows, cols, printed_cells = None, None, None
    else:
        rows, cols, printed_cells = None, None, None
    if covered:
        stored_cells = sum(1 for cell in page_cells if cell["value"] is not None)
        checked, closed = arithmetic_closure(page_cells)
    else:
        stored_cells, checked, closed = None, None, None
    grid_coverage: Any = ""
    if covered and printed_cells:
        grid_coverage = _num(min(1.0, float(stored_cells or 0) / float(printed_cells)))
    row.update({
        "grid_rows": _num(rows, 0), "grid_cols": _num(cols, 0),
        "grid_cells_printed": _num(printed_cells, 0),
        "grid_cells_stored": _num(stored_cells, 0),
        "grid_coverage": grid_coverage,
        "cells_built": int(covered),
        "sums_checked": _num(checked, 0), "sums_closed": _num(closed, 0),
        "sources": "+".join(sources),
        "stored_values": "|".join(f"{value:.2f}" for value in sorted(union)),
    })
    return row


def _write_store(out: Path, rows: list[dict[str, Any]]) -> None:
    con = sqlite3.connect(out / "completeness.db")
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS page_coverage (
                store TEXT NOT NULL, symbol TEXT, doc_key TEXT NOT NULL, sha256 TEXT,
                doc_type TEXT, page INTEGER NOT NULL, unread INTEGER NOT NULL,
                numbers_printed INTEGER, numbers_stored INTEGER, number_coverage REAL,
                grid_rows INTEGER, grid_cols INTEGER, grid_cells_printed INTEGER,
                grid_cells_stored INTEGER, grid_coverage REAL, cells_built INTEGER,
                sums_checked INTEGER, sums_closed INTEGER, sources TEXT, stored_values TEXT,
                PRIMARY KEY (store, doc_key, page))""")
        stores = sorted({str(row["store"]) for row in rows})
        for store in stores:
            con.execute("DELETE FROM page_coverage WHERE store=?", (store,))
        con.executemany(
            "INSERT OR REPLACE INTO page_coverage (" + ", ".join(FIELDS) + ") VALUES ("
            + ",".join("?" * len(FIELDS)) + ")",
            [[row.get(field) if row.get(field) != "" else None for field in FIELDS]
             for row in rows])
        con.commit()
    finally:
        con.close()


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _p10(values: list[float]) -> float | None:
    if not values:
        return None
    return min(values) if len(values) < 10 else statistics.quantiles(values, n=10)[0]


def _print_summary(rows: list[dict[str, Any]], seconds: float) -> None:
    scored = [row for row in rows if not row["unread"]]
    unread = len(rows) - len(scored)
    print(f"pages {len(rows):,}, unread {unread:,} ({100.0 * unread / len(rows):.1f}%), "
          f"scored {len(scored):,}, wall {seconds:.1f}s")
    for doc_type in sorted({str(row["doc_type"]) for row in rows}):
        block = [row for row in scored if row["doc_type"] == doc_type]
        values = [float(row["number_coverage"]) for row in block
                  if row["number_coverage"] != ""]
        median = _median(values)
        p10 = _p10(values)
        print(f"  {doc_type:<14} scored {len(block):>5,}  number_coverage "
              f"median {'-' if median is None else f'{median:.3f}'}  "
              f"p10 {'-' if p10 is None else f'{p10:.3f}'}")


def run(stores: list[Path], out: Path, cells: Path | None = None,
        symbols: list[str] | None = None, types: tuple[str, ...] = ("deck", "results",
                                                                    "annual_report")) -> list[dict[str, Any]]:
    started = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for store_path in stores:
        label = _store_label(Path(store_path))
        con = connect_ro(store_path, timeout_s=60)
        con.row_factory = sqlite3.Row
        try:
            sql = ("SELECT doc_key, symbol, sha256, doc_type, pages, source_key FROM doc "
                   f"WHERE doc_type IN ({','.join('?' * len(types))}) AND pages > 0")
            params: list[Any] = list(types)
            if symbols:
                sql += f" AND symbol IN ({','.join('?' * len(symbols))})"
                params += symbols
            sql += " ORDER BY symbol, doc_key"
            docs = [{name: row[name] for name in row.keys()}
                    for row in _query(con, sql, params)]
            doc_keys = [str(doc["doc_key"]) for doc in docs]
            fact_values = load_fact_values(store_path, doc_keys) if doc_keys else {}
            cells_by_page: dict[tuple[str, int], list[dict[str, Any]]] = {}
            covered: set[str] = set()
            if cells is not None and doc_keys:
                cells_by_page, covered = load_cells(cells, set(doc_keys))
            for doc in docs:
                doc_key = str(doc["doc_key"])
                doc_type = _doc_type(str(doc["doc_type"]))
                total_pages = int(doc["pages"] or 0)
                page_text: dict[int, str] = {}
                for page_row in _query(con, "SELECT page, text FROM doc_page WHERE doc_key=?",
                                       (doc_key,)):
                    try:
                        page_text[int(page_row[0])] = str(page_row[1] or "")
                    except (TypeError, ValueError):
                        continue
                pdf = _open_pdf(str(doc["source_key"] or ""))
                try:
                    for page_no in range(1, total_pages + 1):
                        pdf_page = None
                        if pdf is not None and page_no <= pdf.page_count:
                            try:
                                pdf_page = pdf[page_no - 1]
                            except Exception:
                                pdf_page = None
                        rows.append(_coverage_row(
                            label, str(doc["symbol"] or ""), doc_key,
                            str(doc["sha256"] or ""), doc_type, page_no,
                            page_text.get(page_no, ""), pdf_page,
                            cells_by_page.get((doc_key, page_no), []),
                            doc_key in covered, fact_values.get((doc_key, page_no), {})))
                finally:
                    if pdf is not None:
                        pdf.close()
        finally:
            con.close()
    path = out / "page_coverage.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    _write_store(out, rows)
    _print_summary(rows, time.perf_counter() - started)
    print(f"wrote {path}")
    return rows


# ------------------------------------------------------------------ gate
def _read_coverage(path: Path) -> dict[tuple[str, str, int], dict[str, str]]:
    pages: dict[tuple[str, str, int], dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["store"], row["doc_key"], int(row["page"]))
            pages[key] = row
    return pages


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def gate(prev: Path, new: Path, tolerance: float = 0.02) -> int:
    """Exit 1 when a page's coverage drops, it turns unread, or it disappears."""
    old_pages = _read_coverage(prev)
    new_pages = _read_coverage(new)
    failures: list[str] = []
    for key, old in sorted(old_pages.items()):
        store, doc_key, page = key
        label = f"{store} {doc_key} p{page} ({old.get('doc_type') or '?'})"
        fresh = new_pages.get(key)
        if fresh is None:
            failures.append(f"MISSING   {label}")
            continue
        if not int(old["unread"]) and int(fresh["unread"]):
            failures.append(f"UNREAD    {label}  went from scored to unread")
            continue
        for field in ("number_coverage", "grid_coverage"):
            before, after = _number(old.get(field)), _number(fresh.get(field))
            if before is None or after is None:
                continue
            if after < before - tolerance:
                failures.append(f"{field.upper():<9} {label}  {before:.3f} -> {after:.3f} "
                                f"({after - before:+.3f})")
    added = len(set(new_pages) - set(old_pages))
    print(f"gate: {len(old_pages):,} previous pages, {len(new_pages):,} new pages, "
          f"{added:,} new pages, {len(failures):,} regressions "
          f"(tolerance {tolerance:g})")
    for line in failures:
        print(f"  {line}")
    return 1 if failures else 0


# ------------------------------------------------------------------ calibrate
def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    left = math.sqrt(sum((x - mx) ** 2 for x in xs))
    right = math.sqrt(sum((y - my) ** 2 for y in ys))
    return numerator / (left * right) if left and right else None


def calibrate(coverage: Path, reference: Path, pages: Path, split: str = "dev") -> int:
    """Score coverage against reference recall on the dev pages only; frozen is refused."""
    if split == "frozen":
        print("calibrate: the frozen split is never read", file=sys.stderr)
        return 2
    page_rows = [row for row in csv.DictReader(pages.open(newline="", encoding="utf-8"))
                 if row.get("split") == split]
    by_sha = {(str(row.get("sha256") or ""), int(row["page"])): row
              for row in _read_coverage(coverage).values()}
    reference_values: dict[str, set[float]] = {}
    with reference.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            value = parse_number(row.get("value_text") or "")
            if value is None or not keep(abs(value)):
                continue
            reference_values.setdefault(row["page_id"], set()).add(round(abs(value), 2))
    table: list[dict[str, Any]] = []
    covered = 0
    for meta in page_rows:
        page_id = meta["page_id"]
        page_no = int(meta["page"])
        row = by_sha.get((str(meta.get("sha256") or ""), page_no))
        truth = reference_values.get(page_id, set())
        if row is None:
            table.append({"page_id": page_id, "store": meta["store"],
                          "doc_type": meta["doc type"], "page": meta["page"],
                          "numbers_printed": "", "number_coverage": "",
                          "grid_coverage": "", "reference_cells": len(truth),
                          "reference_recall": ""})
            continue
        covered += 1
        stored = {float(value) for value in str(row.get("stored_values") or "").split("|") if value}
        recall = len(truth & stored) / len(truth) if truth else None
        table.append({
            "page_id": page_id, "store": meta["store"],
            "doc_type": meta["doc type"], "page": meta["page"],
            "numbers_printed": row["numbers_printed"],
            "number_coverage": row["number_coverage"],
            "grid_coverage": row["grid_coverage"],
            "reference_cells": len(truth),
            "reference_recall": "" if recall is None else round(recall, 4),
        })
    pairs = [(float(row["number_coverage"]), float(row["reference_recall"]))
             for row in table if row["number_coverage"] != "" and row["reference_recall"] != ""]
    grid_pairs = [(float(row["grid_coverage"]), float(row["reference_recall"]))
                  for row in table if row["grid_coverage"] != "" and row["reference_recall"] != ""]
    hits = sum(1 for coverage_v, recall_v in pairs if coverage_v < 0.8 and recall_v < 0.8)
    misses = sum(1 for coverage_v, recall_v in pairs if coverage_v >= 0.8 and recall_v < 0.8)
    false_alarms = sum(1 for coverage_v, recall_v in pairs if coverage_v < 0.8 and recall_v >= 0.8)
    out_path = coverage.parent / f"calibration_{split}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]) if table else
                                ["page_id", "store", "doc_type", "page"])
        writer.writeheader()
        writer.writerows(table)
    print(f"calibrate: split={split}, reference pages {len(page_rows)}, covered "
          f"{covered}, scored {len(pairs)}")
    print(f"  {'page':<6} {'store':<5} {'type':<13} {'printed':>7} {'coverage':>8} "
          f"{'grid':>6} {'cells':>5} {'recall':>7}")
    for row in sorted(table, key=lambda entry: entry["page_id"]):
        print(f"  {row['page_id']:<6} {str(row['store']):<5} {str(row['doc_type']):<13} "
              f"{str(row['numbers_printed']):>7} {str(row['number_coverage']):>8} "
              f"{str(row['grid_coverage']):>6} {row['reference_cells']:>5} "
              f"{str(row['reference_recall']):>7}")
    correlation = _pearson([pair[0] for pair in pairs], [pair[1] for pair in pairs])
    grid_correlation = _pearson([pair[0] for pair in grid_pairs], [pair[1] for pair in grid_pairs])
    print(f"  correlation number_coverage/recall: "
          f"{'-' if correlation is None else f'{correlation:.3f}'} over {len(pairs)} pages; "
          f"grid_coverage/recall: "
          f"{'-' if grid_correlation is None else f'{grid_correlation:.3f}'} "
          f"over {len(grid_pairs)} pages")
    print(f"  coverage<0.8 vs recall<0.8: hits {hits}, misses {misses}, "
          f"false alarms {false_alarms}")
    print(f"wrote {out_path}")
    return 0


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-page completeness report and gate (T-177)")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="score every page of a pilot3 store")
    run_parser.add_argument("--store", required=True, nargs="+", type=Path,
                            help="pilot3 store(s), opened read-only")
    run_parser.add_argument("--cells", type=Path, default=None, help="v2 cell store root")
    run_parser.add_argument("--out", required=True, type=Path)
    run_parser.add_argument("--symbols", default=None, help="comma separated")
    run_parser.add_argument("--types", default=DEFAULT_TYPES)

    gate_parser = sub.add_parser("gate", help="fail when a page's coverage drops")
    gate_parser.add_argument("--prev", required=True, type=Path)
    gate_parser.add_argument("--new", required=True, type=Path)
    gate_parser.add_argument("--tolerance", type=float, default=0.02)

    cal_parser = sub.add_parser("calibrate", help="score coverage against reference pages")
    cal_parser.add_argument("--coverage", required=True, type=Path)
    cal_parser.add_argument("--reference", required=True, type=Path)
    cal_parser.add_argument("--pages", required=True, type=Path)
    cal_parser.add_argument("--split", default="dev")

    args = parser.parse_args(argv)
    if args.command == "run":
        types = tuple(_doc_type(part) for part in str(args.types).split(",") if part.strip())
        symbols = [name.strip().upper() for name in str(args.symbols).split(",")] \
            if args.symbols else None
        run([Path(store) for store in args.store], args.out, args.cells, symbols, types)
        return 0
    if args.command == "gate":
        return gate(args.prev, args.new, args.tolerance)
    return calibrate(args.coverage, args.reference, args.pages, args.split)


if __name__ == "__main__":
    raise SystemExit(main())
