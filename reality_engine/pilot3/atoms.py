"""T-199: one ``page_atom`` per printed figure of a table/chart page, resolved by script only.

``page_reader`` reads a page into ``page_cell`` rows (one per printed cell, position-checked).  This module turns
each non-quarantined cell that holds a figure into one atom:

* **period** -- ``row_checks.period_key`` on the column header, then the table title, then the page's one printed
  header line.  A relative header ("Q2", "H1", "Current quarter") resolves only against a fiscal year printed on the
  same page.  An empty column header on a KPI tile page (``COLUMNS:  | Q2FY26`` in the prototype) resolves to the
  reporting period the build already assigns the document (``kpi_series.fiscal_period``,
  ``fin_quarter_printed.fiscal_period``, ``transcript_statement.call_period``, ``fin_annual_line.fiscal_year``,
  ``doc_identity.fiscal_year``), never parsed from the title, with reason ``period_from_document`` and status at
  most ``unverified``.  Anything else is empty with ``period_unresolved``.
* **basis** -- ``consolidated`` / ``standalone`` from the table title, else the page text when exactly one is
  printed alone.
* **unit and scale** -- the cell's own unit text; else the page's single scale declaration (``unit_scales`` /
  ``check_page_unit`` logic).  ``%``, ``x``, ``days`` and a count keep their unit with scale 1; two different
  declarations on the page leave the unit unresolved.  An empty header whose value carries a change marker
  (▲/▼, "up by", "bps") is a change, unit ``change``, never a level, and the serving tools never answer a metric
  with it.
* **value** -- ``(1,234)`` is negative, ``-`` / ``Nil`` is no figure (no atom), ``12.3%`` is 12.3 with unit ``pct``.
* **definition** -- a printed legend in the row label's brackets, else the label's own qualifier through
  ``row_checks.definition_key`` (T-198).  The full label is kept (the legend is part of what the row is).

``verified`` means the cell is position-checked AND its period and unit resolved; everything else is
``unverified`` with ``check_reasons`` naming what is missing.  Two rows of one document with the same row label,
period and basis but different values are both ``unverified`` (``same_doc_conflict``).

``duplicates.csv`` from ``page_reader export`` names identical pages the reader did not read; each canonical atom
is copied onto its duplicates with the duplicate's own document key and ``known_at``, and
``copied_from=<doc_key>#p<page>`` in ``check_reasons``.

CLI: ``python -m reality_engine.pilot3.atoms --store <db> [--duplicates <csv>]``; build part ``atoms`` runs last.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from reality_engine.pilot3 import row_checks
from reality_engine.pilot3 import schema

ATOM_COLUMNS = ("symbol", "isin", "doc_key", "doc_type", "page", "known_at", "table_title", "row_label",
                "col_header", "period", "basis", "unit", "scale", "value", "value_text", "definition",
                "x0", "y0", "x1", "y1", "reader", "check_status", "check_reasons", "created_at")

_PCT = re.compile(r"%|per\s*cent|percentage", re.I)
_BPS = re.compile(r"\bbps\b|basis\s*points?", re.I)
_X = re.compile(r"^\s*x\s*$|(?<=\d)\s*x\s*$|\btimes\b", re.I)
_DAYS = re.compile(r"\bdays?\b", re.I)
_COUNT = re.compile(r"\b(?:nos?|numbers?|count|units?|shares?|tonnes?|tons?|mt|gw|mw|kw|mm|sq\.?\s*ft|acres?|"
                    r"rooms?|seats?|beds?|patients?|persons?|employees?|customers?|stores?|branches?|"
                    r"franchises?)\b", re.I)
_CURRENCY = re.compile(r"[₹$`]|\brs\.?\b|\binr\b|\busd\b|\brupees?\b", re.I)
_PAGE_SCALE = {"million": 1e6, "mn": 1e6, "billion": 1e9, "bn": 1e9, "crore": 1e7, "cr": 1e7,
               "lakh": 1e5, "lac": 1e5, "thousand": 1e3}
_BASIS = re.compile(r"\b(consolidated|standalone)\b", re.I)
_NUMBER = re.compile(r"[-+]?\d[\d\u00a0\s,]*(?:\.\d+)?")
_NO_FIGURE = {"-", "–", "—", "na", "n/a", "nil", "none", "nm", "*"}
_CHANGE_MARK = re.compile(r"[▲▼△▽]|\b(?:up|down|higher|lower)\s+by\b|\bbps\b|basis\s*points?", re.I)
_LEGEND = re.compile(r"\(([^()]{2,})\)\s*$")
_HEAD_REL = re.compile(r"^(?:q([1-4])|h([12])|(9m|nine\s+months?)|(?:current|this)\s+(quarter|qtr)|"
                       r"(?:current|this)\s+half|(ytd|year[\s-]*to[\s-]*date))$", re.I)
_VOCAB: row_checks.Vocab | None = None


def _vocab() -> row_checks.Vocab:
    global _VOCAB
    if _VOCAB is None:
        _VOCAB = row_checks.load_vocab()
    return _VOCAB


# --- period ------------------------------------------------------------------------------------------
def _fiscal_year(page_text: str, table_title: str = "") -> str:
    """The one fiscal year printed on the page ('FY26', 'FY 2026', 'fiscal 2026') as two digits, else ''."""
    years = set()
    for text in (page_text or "", table_title or ""):
        for m in re.finditer(r"\b(?:fy|fiscal\s+(?:year\s+)?)\s*'?\s*(\d{2,4})\b", text, re.I):
            years.add(m.group(1)[-2:])
    return next(iter(years)) if len(years) == 1 else ""


def _header_line_period(page_text: str) -> str:
    """The period a page's printed header line names, when exactly one period is printed that way.

    A prose sentence that happens to mention a quarter is not a header line: the line must be a table's own header,
    i.e. carry at least two header words, or be a short single-column heading."""
    keys: set[str] = set()
    for line in (page_text or "").splitlines():
        cells = row_checks.header_cells(line)
        headers = [cell for cell in cells if row_checks.header_word(cell)]
        if len(headers) < 2 and not (len(headers) == 1 and len(cells) == 1):
            continue
        for cell in cells:
            key = row_checks.period_key(cell)
            if key:
                keys.add(key)
    return next(iter(keys)) if len(keys) == 1 else ""


def _current_quarter(known_at: str) -> tuple[str, str]:
    """(quarter head, fiscal year two digits) of an Indian fiscal quarter, from a filing date; ('', '') if none."""
    try:
        day = datetime.strptime((known_at or "")[:10], "%Y-%m-%d")
    except ValueError:
        return "", ""
    quarter = ((day.month - 4) % 12) // 3 + 1
    year = day.year + 1 if day.month >= 4 else day.year
    return f"q{quarter}", f"{year % 100:02d}"


def resolve_period(col_header: str, table_title: str, page_text: str, known_at: str = "",
                   doc_period: str = "") -> tuple[str, str]:
    """(period key like ``q2fy26``, why not resolved) for one printed cell."""
    for text in (col_header, table_title):
        key = row_checks.period_key(text)
        if key:
            return key, ""
    key = _header_line_period(page_text)
    if key:
        return key, ""
    rel = _HEAD_REL.match(re.sub(r"\s+", " ", (col_header or "").strip()))
    if not rel:
        rel = _HEAD_REL.match(re.sub(r"\s+", " ", (table_title or "").strip()))
    if rel:
        printed = _fiscal_year(page_text, table_title)
        if rel.group(1) and printed:
            return f"q{rel.group(1)}fy{printed}", ""
        if rel.group(2) and printed:
            return f"h{rel.group(2)}fy{printed}", ""
        if rel.group(3) and printed:
            return f"9mfy{printed}", ""
        if rel.group(4):                                   # "Current quarter" / "this quarter"
            quarter, own_year = _current_quarter(known_at)
            if quarter and own_year == printed:
                return f"{quarter}fy{printed}", ""
        elif rel.group(5):
            return "ytd", ""
        else:                                              # "current half"
            quarter, own_year = _current_quarter(known_at)
            if own_year and own_year == printed and quarter:
                return f"{'h1' if quarter in ('q1', 'q2') else 'h2'}fy{printed}", ""
    if doc_period:
        return doc_period, "period_from_document"
    return "", "period_unresolved"


# --- basis -------------------------------------------------------------------------------------------
def resolve_basis(table_title: str, page_text: str) -> str:
    """``consolidated`` / ``standalone`` from the table title, else the page when it prints exactly one alone."""
    title = {m.group(1).lower() for m in _BASIS.finditer(table_title or "")}
    if len(title) == 1:
        return title.pop()
    if len(title) > 1:
        return ""
    page = {m.group(1).lower() for m in _BASIS.finditer(page_text or "")}
    return page.pop() if len(page) == 1 else ""


# --- unit and scale ----------------------------------------------------------------------------------
def _unit_from(text: str) -> tuple[str, float, bool]:
    """(unit, scale, named) a unit text names; ``named`` is False when it names no unit at all."""
    text = text or ""
    if _PCT.search(text):
        return "pct", 1.0, True
    if _BPS.search(text):
        return "bps", 1.0, True
    if _X.search(text):
        return "x", 1.0, True
    if _DAYS.search(text):
        return "days", 1.0, True
    if re.search(r"\bthousand\b", text, re.I):
        return "inr", 1e3, True
    scales = row_checks.unit_scales(text)
    if len(scales) == 1:
        return "inr", next(iter(scales)), True
    if len(scales) > 1:
        return "", 1.0, False
    if _COUNT.search(text):
        return "count", 1.0, True
    if _CURRENCY.search(text):
        return ("usd" if re.search(r"\busd\b|\$", text, re.I) else "inr"), 1.0, True
    return "", 1.0, False


def _page_declarations(page_text: str) -> set[tuple[str, float]]:
    """The (currency, scale) declarations a page prints ("(Rs. in crore)", "All amounts in USD million")."""
    declared: set[tuple[str, float]] = set()
    for m in row_checks._PAGE_UNIT.finditer(page_text or ""):     # the checker's own page-declaration pattern
        raw = next((g for g in m.groups() if g), "").lower().rstrip("s")
        scale = _PAGE_SCALE.get(raw)
        if scale:
            declared.add((row_checks.unit_family(m.group(0)) or "inr", scale))
    return declared


def resolve_unit(value_text: str, unit_text: str, page_text: str) -> tuple[str, float, str]:
    """(unit, scale, why unresolved) for one value: its own text, the cell unit, then the page declaration.

    A value that prints only a currency word ("Rs 1,234") is rupees at scale 1 and must not override the cell's own
    unit ("Rs crore"): the cell unit carries the scale, so a non-currency unit in the value (%, x, days, count) is the
    only one that outranks it."""
    for text, currency_ok in ((value_text, False), (unit_text, True), (value_text, True)):
        unit, scale, named = _unit_from(text)
        if named and unit and (currency_ok or unit not in ("inr", "usd")):
            return unit, scale, ""
    declared = _page_declarations(page_text)
    if len(declared) == 1:
        unit, scale = next(iter(declared))
        return unit, scale, ""
    return "", 1.0, ("unit_conflict" if declared else "unit_unresolved")


# --- value -------------------------------------------------------------------------------------------
def parse_value(value_text: str) -> float | None:
    """The printed figure as a number: ``(1,234)`` is -1234, ``12.3%`` is 12.3, ``-`` / ``Nil`` is no figure."""
    text = (value_text or "").strip()
    if not text or text.lower() in _NO_FIGURE:
        return None
    negative = text.startswith("(") and text.endswith(")") or text.lstrip().startswith(("-", "−"))
    match = _NUMBER.search(text.strip("() \t").replace("−", "-"))
    if not match:
        return None
    raw = match.group(0).replace("\u00a0", "").replace(" ", "").replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    if negative and value > 0:
        value = -value
    return value


# --- definition --------------------------------------------------------------------------------------
def definition_of(row_label: str) -> str:
    """A printed legend in the row label's brackets, else the label's own qualifier through the checker's vocab."""
    label = row_label or ""
    legend = _LEGEND.search(label)
    if legend:
        words = [re.sub(r"[^a-z0-9]+", "", word.lower()) for word in re.findall(r"[A-Za-z0-9]+", legend.group(1))]
        words = [word for word in words if word]
        if words:
            return "legend:" + ",".join(words)
    text = row_checks.fold(label)
    if not text:
        return ""
    vocab = _vocab()
    for metric in vocab.metrics.values():
        if any(pattern.search(text) for pattern in metric.labels):
            return row_checks.definition_key(metric, text)
    return ""


# --- the document's own period -----------------------------------------------------------------------
# The store already assigns every filing a reporting period: KPI and printed-comparative rows carry it, a call's
# statements carry ``call_period``, an annual line and the document identity carry the fiscal year.  The atom
# resolver reads that, never the document title.
_PERIOD_SOURCES = (("kpi_series", "fiscal_period"), ("fin_quarter_printed", "fiscal_period"),
                   ("transcript_statement", "call_period"), ("fin_annual_line", "fiscal_year"),
                   ("doc_identity", "fiscal_year"))


def document_periods(conn: sqlite3.Connection) -> dict[str, str]:
    """doc_key -> the one reporting period the build already assigns that document, else absent."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    seen: dict[str, set[str]] = {}
    for table, column in _PERIOD_SOURCES:
        if table not in tables:
            continue
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            continue
        for doc_key, value in conn.execute(
                f"SELECT doc_key, {column} FROM {table} WHERE doc_key IS NOT NULL AND {column} IS NOT NULL "
                f"AND {column}<>'' GROUP BY doc_key, {column}"):
            key = row_checks.period_key(value)
            if key:
                seen.setdefault(doc_key, set()).add(key)
    return {doc_key: next(iter(keys)) for doc_key, keys in seen.items() if len(keys) == 1}


# --- the atom ----------------------------------------------------------------------------------------
def _conflict_key(atom: dict[str, Any]) -> tuple[str, str, str, str] | None:
    if not atom["period"]:
        return None
    return (atom["doc_key"], row_checks.squash(atom["row_label"] or ""), atom["period"], atom["basis"] or "")


def mark_conflicts(atoms: list[dict[str, Any]]) -> None:
    """Same document, row label, period and basis with two different values: both unverified (T-199)."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for atom in atoms:
        key = _conflict_key(atom)
        if key is not None:
            groups.setdefault(key, []).append(atom)
    for group in groups.values():
        if len({atom["value"] for atom in group}) < 2:
            continue
        for atom in group:
            atom["check_status"] = "unverified"
            atom["check_reasons"] = _add_reason(atom["check_reasons"], "same_doc_conflict")


def _add_reason(reasons: str, reason: str) -> str:
    parts = [p for p in (reasons or "").split(",") if p]
    if reason not in parts:
        parts.append(reason)
    return ",".join(parts)


def atom_from_cell(cell: dict[str, Any]) -> dict[str, Any] | None:
    """One atom from one non-quarantined ``page_cell`` row, or None when the cell prints no figure."""
    value = parse_value(cell.get("value_text") or "")
    if value is None:
        return None
    page_text = cell.get("page_text") or ""
    row_label = cell.get("row_label") or ""
    col_header = cell.get("col_header") or ""
    period, period_why = resolve_period(col_header, cell.get("table_title") or "", page_text,
                                        cell.get("known_at") or "", cell.get("doc_period") or "")
    basis = resolve_basis(cell.get("table_title") or "", page_text)
    change = not col_header.strip() and bool(_CHANGE_MARK.search(cell.get("value_text") or ""))
    if change:                                   # a change marker is never the metric's level
        unit, scale, unit_why = "change", 1.0, ""
    else:
        unit, scale, unit_why = resolve_unit(cell.get("value_text") or "", cell.get("unit_text") or "", page_text)
    reasons = []
    if (cell.get("status") or "") != "verified":
        reasons.append("position_unverified")
    if period_why:
        reasons.append(period_why)
    if unit_why:
        reasons.append(unit_why)
    if change:
        reasons.append("change_not_level")
    if not row_label.strip():
        reasons.append("label_missing")
    return {
        "symbol": cell.get("symbol") or "", "isin": cell.get("isin") or "",
        "doc_key": cell.get("doc_key") or "", "doc_type": cell.get("doc_type") or "",
        "page": int(cell.get("page") or 0), "known_at": cell.get("known_at") or "",
        "table_title": cell.get("table_title") or "", "row_label": row_label,
        "col_header": col_header, "period": period, "basis": basis,
        "unit": unit, "scale": scale, "value": value, "value_text": cell.get("value_text") or "",
        "definition": definition_of(row_label),
        "x0": cell.get("x0"), "y0": cell.get("y0"), "x1": cell.get("x1"), "y1": cell.get("y1"),
        "reader": cell.get("reader") or "",
        "check_status": "unverified" if reasons else "verified",
        "check_reasons": ",".join(reasons),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


CELL_SQL = """SELECT c.doc_key, c.page, c.symbol, c.reader, c.table_title, c.row_label, c.col_header,
       c.value_text, c.unit_text, c.status, c.x0, c.y0, c.x1, c.y1,
       COALESCE(d.symbol, c.symbol) AS doc_symbol, d.isin AS isin, d.doc_type AS doc_type,
       COALESCE(d.known_at, c.known_at) AS known_at, p.text AS page_text
FROM page_cell c
LEFT JOIN doc d ON d.doc_key=c.doc_key
LEFT JOIN doc_page p ON p.doc_key=c.doc_key AND p.page=c.page
WHERE COALESCE(c.status,'')<>'quarantined'
ORDER BY c.doc_key, c.page, c.rowid"""


def atoms_from_cells(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    cells = [dict(row) for row in conn.execute(CELL_SQL)]
    doc_periods = document_periods(conn)
    atoms: list[dict[str, Any]] = []
    for cell in cells:
        cell["doc_period"] = doc_periods.get(cell.get("doc_key") or "", "")
        atom = atom_from_cell(cell)
        if atom is None:
            continue
        atom["symbol"] = cell.get("doc_symbol") or atom["symbol"]
        atom["isin"] = cell.get("isin") or atom["isin"]
        atom["doc_type"] = cell.get("doc_type") or atom["doc_type"]
        atoms.append(atom)
    mark_conflicts(atoms)
    return atoms, {"cells": len(cells)}


def _read_duplicates(path: str | Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh) if (row.get("duplicate_doc_key") or "").strip()]


def copy_atoms(conn: sqlite3.Connection, atoms: list[dict[str, Any]],
               duplicates_csv: str | Path | None) -> list[dict[str, Any]]:
    """Copy each canonical atom onto the identical pages ``page_reader export`` did not read."""
    duplicates = _read_duplicates(duplicates_csv)
    if not duplicates or not atoms:
        return []
    by_page: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for atom in atoms:
        by_page.setdefault((atom["doc_key"], int(atom["page"])), []).append(atom)
    docs = {row[0]: {"symbol": row[1] or "", "doc_type": row[2] or "", "isin": row[3] or "",
                     "known_at": row[4] or ""}
            for row in conn.execute("SELECT doc_key, symbol, doc_type, isin, known_at FROM doc")}
    copied: list[dict[str, Any]] = []
    made: set[tuple[str, int]] = set()
    for row in duplicates:
        canonical = ((row.get("canonical_doc_key") or "").strip(), int(row.get("canonical_page") or 0))
        target_key = (row.get("duplicate_doc_key") or "").strip()
        target_page = int(row.get("duplicate_page") or 0)
        if not target_key or (target_key, target_page) in made:
            continue
        info = docs.get(target_key, {})
        known_at = info.get("known_at") or ""
        for atom in by_page.get(canonical, []):
            copy = dict(atom)
            copy.update({"doc_key": target_key, "page": target_page,
                         "symbol": info.get("symbol") or atom["symbol"],
                         "isin": info.get("isin") or atom["isin"],
                         "doc_type": info.get("doc_type") or atom["doc_type"],
                         "known_at": known_at or atom["known_at"]})
            copy["check_reasons"] = _add_reason(copy["check_reasons"],
                                                f"copied_from={canonical[0]}#p{canonical[1]}")
            copy["created_at"] = datetime.now().isoformat(timespec="seconds")
            copied.append(copy)
        made.add((target_key, target_page))
    return copied


def run(store: str | Path, duplicates_csv: str | Path | None = None) -> dict[str, Any]:
    """Rebuild every store's ``page_atom`` rows from its non-quarantined ``page_cell`` rows (additive schema)."""
    conn = sqlite3.connect(str(store))
    try:
        schema.migrate(conn)
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='page_cell'").fetchone():
            return {"skipped": "no page_cell table"}
        conn.execute("DELETE FROM page_atom")
        atoms, stats = atoms_from_cells(conn)
        copied = copy_atoms(conn, atoms, duplicates_csv)
        atoms += copied
        if atoms:
            marks = ",".join("?" * len(ATOM_COLUMNS))
            conn.executemany(f"INSERT INTO page_atom ({','.join(ATOM_COLUMNS)}) VALUES ({marks})",
                             [tuple(atom[column] for column in ATOM_COLUMNS) for atom in atoms])
        conn.commit()
    finally:
        conn.close()
    return {"cells": stats["cells"], "atoms": len(atoms), "copied": len(copied),
            "verified": sum(1 for atom in atoms if atom["check_status"] == "verified"),
            "unverified": sum(1 for atom in atoms if atom["check_status"] != "verified"),
            "no_period": sum(1 for atom in atoms if not atom["period"]),
            "no_unit": sum(1 for atom in atoms if not atom["unit"])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m reality_engine.pilot3.atoms", description=__doc__)
    ap.add_argument("--store", required=True, help="the pilot3 store to write page_atom into")
    ap.add_argument("--duplicates", default=None,
                    help="page_reader export's duplicates.csv: copy each canonical atom to its identical pages")
    args = ap.parse_args(argv)
    print(json.dumps(run(args.store, args.duplicates), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
