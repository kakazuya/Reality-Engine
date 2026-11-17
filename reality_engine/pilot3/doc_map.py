"""Document map (Shivam 17 Nov): label every held page with the section it prints, and check each section's rows.

``doc_map.yaml`` says, per document type (annual report, results, presentation, call transcript), which sections it
carries, how each section reads (heading, row labels, words that rule it out), roughly where it sits, the data it
holds, the store table that data must land in, the reader that fills it, and a must-exist rule.

    python -m reality_engine.pilot3.doc_map scan  --root D:/RealityEngine/tg_build/measure10 [--stores c01,c02]
    python -m reality_engine.pilot3.doc_map report --out D:/RealityEngine/reports/2026-11-17_doc_map.xlsx

``scan`` reads each store read-only and writes one row per labelled page into ``<root>/../doc_map.db``
(store, symbol, doc_key, doc_type, fiscal_year, page, pages, position, section), plus one row per store and section
with the rows the section's table holds (``expect``).  ``report`` writes the Excel: sheet ``map`` is the YAML as a
table (what Shivam reviews), ``coverage`` gives per section how many held documents print it and where, ``gaps``
lists each store x section whose documents print it but whose table holds no row for that year.

No model, no network, no write to a store.  A page may carry two sections (a cash-flow statement and the start of
its notes); both are labelled.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

MAP_PATH = Path(__file__).with_name("doc_map.yaml")
# a store's doc_type -> the map's document type
DOC_TYPES = {"annual_report": "annual_report", "results": "results", "deck": "deck", "transcript": "transcript"}


@dataclass
class Section:
    doc_type: str
    name: str
    heading: list = field(default_factory=list)
    all: list = field(default_factory=list)
    any: list = field(default_factory=list)
    min_any: int = 1
    none: list = field(default_factory=list)
    where: tuple = (0.0, 1.0)
    items: list = field(default_factory=list)
    table: str = ""
    reader: str = ""
    expect: dict = field(default_factory=dict)

    def matches(self, text: str, head_chars: int) -> bool:
        head = text[:head_chars]
        if self.heading and not any(r.search(head) for r in self.heading):
            return False
        if not all(r.search(text) for r in self.all):
            return False
        if self.any and sum(1 for r in self.any if r.search(text)) < self.min_any:
            return False
        if any(r.search(text) for r in self.none):
            return False
        return bool(self.heading or self.all or self.any)


def load(path: Path = MAP_PATH) -> tuple[int, list[Section]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for dt, spec in raw["doc_types"].items():
        for name, s in spec["sections"].items():
            comp = {k: [re.compile(p, re.I | re.M) for p in (s.get(k) or [])] for k in ("heading", "all", "any", "none")}
            out.append(Section(dt, name, **comp, min_any=int(s.get("min_any", 1)), where=tuple(s.get("where") or (0, 1)),
                               items=list(s.get("items") or []), table=str(s.get("table") or ""),
                               reader=str(s.get("reader") or ""), expect=dict(s.get("expect") or {})))
    return int(raw.get("head_chars", 600)), out


def label(text: str, doc_type: str, sections: list[Section], head_chars: int) -> list[str]:
    """Every section of ``doc_type`` the page text prints."""
    if not text:
        return []
    return [s.name for s in sections if s.doc_type == doc_type and s.matches(text, head_chars)]


def fiscal_year(doc_type: str, filing_date: str | None) -> str:
    """The fiscal year a document reports: an annual report filed Apr-Mar of year Y+1 reports FY ending March Y
    (filed Jul 2024 -> FY24); other documents keep '' (their periods are read per page)."""
    if doc_type != "annual_report" or not filing_date:
        return ""
    y, m = int(filing_date[:4]), int(filing_date[5:7])
    return f"FY{(y if m >= 4 else y - 1) % 100:02d}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS page_section(store TEXT, symbol TEXT, doc_key TEXT, doc_type TEXT, fiscal_year TEXT,
  filing_date TEXT, page INT, pages INT, position REAL, section TEXT);
CREATE TABLE IF NOT EXISTS section_rows(store TEXT, section TEXT, doc_type TEXT, fiscal_year TEXT, rows INT);
CREATE TABLE IF NOT EXISTS scanned(store TEXT PRIMARY KEY, symbol TEXT, docs INT, pages INT);
"""


def _expect_rows(conn: sqlite3.Connection, s: Section, fy: str) -> int | None:
    """Rows the section's table holds for that fiscal year (None when the section has no rule or no year)."""
    e = s.expect
    if not e or not e.get("table") or not fy:
        return None
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({e['table']})")}
    if not cols:
        return 0
    year_col = "fiscal_year" if "fiscal_year" in cols else "fiscal_period" if "fiscal_period" in cols else None
    if year_col is None:
        return None
    where = e.get("where") or "1=1"
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {e['table']} WHERE ({where}) AND {year_col} = ?", (fy,)).fetchone()[0]
    except sqlite3.Error:
        return None


def scan_store(db: Path, store: str, sections: list[Section], head_chars: int, out: sqlite3.Connection) -> dict:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    symbol = conn.execute("SELECT group_concat(DISTINCT symbol) FROM company").fetchone()[0]
    docs = conn.execute("SELECT doc_key, doc_type, filing_date, pages FROM doc WHERE doc_type IN (%s)"
                        % ",".join("?" * len(DOC_TYPES)), list(DOC_TYPES)).fetchall()
    out.execute("DELETE FROM page_section WHERE store = ?", (store,))
    out.execute("DELETE FROM section_rows WHERE store = ?", (store,))
    n_pages, years = 0, defaultdict(set)
    for doc_key, doc_type, filing_date, pages in docs:
        dt = DOC_TYPES[doc_type]
        fy = fiscal_year(dt, filing_date)
        rows = conn.execute("SELECT page, text FROM doc_page WHERE doc_key = ? ORDER BY page", (doc_key,)).fetchall()
        total = pages or (rows[-1][0] if rows else 0) or 1
        for page, text in rows:
            n_pages += 1
            for name in label(text or "", dt, sections, head_chars):
                out.execute("INSERT INTO page_section VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (store, symbol, doc_key, dt, fy, filing_date, page, total, round(page / total, 3), name))
                if fy:
                    years[(dt, name)].add(fy)
    for s in sections:
        for fy in sorted(years.get((s.doc_type, s.name), ())):
            n = _expect_rows(conn, s, fy)
            if n is not None:
                out.execute("INSERT INTO section_rows VALUES (?,?,?,?,?)", (store, s.name, s.doc_type, fy, n))
    out.execute("INSERT OR REPLACE INTO scanned VALUES (?,?,?,?)", (store, symbol, len(docs), n_pages))
    out.commit()
    conn.close()
    return {"store": store, "symbol": symbol, "docs": len(docs), "pages": n_pages}


def scan(root: Path, stores: list[str] | None = None, out_db: Path | None = None) -> list[dict]:
    head_chars, sections = load()
    out_db = out_db or root.parent / "doc_map.db"
    out = sqlite3.connect(out_db)
    out.executescript(SCHEMA)
    done = []
    for d in sorted(root.glob("c[0-9][0-9]")):
        db = d / f"{d.name}.db"
        if db.is_file() and (not stores or d.name in stores):
            done.append(scan_store(db, d.name, sections, head_chars, out))
            print(done[-1], flush=True)
    out.close()
    return done


def report(db: Path, xlsx: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    head_chars, sections = load()
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "map"
    ws.append(["document", "section", "heading patterns", "must contain", "any of (min)", "ruled out by",
               "usual position", "data items", "store table", "reader today", "must-exist rule"])
    for s in sections:
        ws.append([s.doc_type, s.name, " | ".join(r.pattern for r in s.heading), " | ".join(r.pattern for r in s.all),
                   (" | ".join(r.pattern for r in s.any) + f"  (min {s.min_any})") if s.any else "",
                   " | ".join(r.pattern for r in s.none), f"{s.where[0]:.0%} - {s.where[1]:.0%}", ", ".join(s.items),
                   s.table, s.reader or "NONE", str(s.expect or "")])
    held = dict(con.execute("SELECT doc_type, COUNT(DISTINCT doc_key) FROM (SELECT DISTINCT doc_key, doc_type "
                            "FROM page_section) GROUP BY doc_type"))
    cov = wb.create_sheet("coverage")
    cov.append(["document", "section", "documents printing it", "documents of that type with any section",
                "share", "pages labelled", "median position", "in usual position", "reader today"])
    for s in sections:
        r = con.execute("SELECT COUNT(DISTINCT doc_key), COUNT(*) FROM page_section WHERE doc_type=? AND section=?",
                        (s.doc_type, s.name)).fetchone()
        pos = sorted(p for (p,) in con.execute("SELECT position FROM page_section WHERE doc_type=? AND section=?",
                                               (s.doc_type, s.name)))
        inside = sum(1 for p in pos if s.where[0] <= p <= s.where[1])
        n_docs = held.get(s.doc_type, 0)
        cov.append([s.doc_type, s.name, r[0], n_docs, f"{r[0] / n_docs:.0%}" if n_docs else "", r[1],
                    f"{pos[len(pos) // 2]:.0%}" if pos else "", f"{inside / len(pos):.0%}" if pos else "",
                    s.reader or "NONE"])
    gaps = wb.create_sheet("gaps")
    gaps.append(["store", "symbol", "document", "section", "fiscal year", "rows in store table", "store table"])
    sym = dict(con.execute("SELECT store, symbol FROM scanned"))
    tables = {(s.doc_type, s.name): s.table for s in sections}
    for store, section, doc_type, fy, rows in con.execute(
            "SELECT store, section, doc_type, fiscal_year, rows FROM section_rows WHERE rows = 0 "
            "ORDER BY section, store, fiscal_year"):
        gaps.append([store, sym.get(store), doc_type, section, fy, rows, tables.get((doc_type, section), "")])
    summ = wb.create_sheet("gap_summary", 1)
    summ.append(["section", "store-years printed but empty", "stores affected", "store-years printed"])
    for section, empty, stores, total in con.execute(
            "SELECT section, SUM(rows = 0), COUNT(DISTINCT CASE WHEN rows = 0 THEN store END), COUNT(*) "
            "FROM section_rows GROUP BY section ORDER BY 2 DESC"):
        summ.append([section, empty, stores, total])
    for sheet in wb.worksheets:
        for c in sheet[1]:
            c.font = Font(bold=True)
        for row in sheet.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    for col, w in zip("ABCDEFGHIJK", (14, 22, 40, 40, 40, 24, 12, 40, 30, 22, 40)):
        ws.column_dimensions[col].width = w
    xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx)
    con.close()
    return xlsx


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--root", required=True)
    s.add_argument("--stores", default=None)
    s.add_argument("--out-db", default=None)
    r = sub.add_parser("report")
    r.add_argument("--db", default="D:/RealityEngine/tg_build/doc_map.db")
    r.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        scan(Path(a.root), a.stores.split(",") if a.stores else None, Path(a.out_db) if a.out_db else None)
    else:
        print(report(Path(a.db), Path(a.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
