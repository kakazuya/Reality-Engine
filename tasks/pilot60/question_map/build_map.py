"""Check script for the question map: the only thing that sets a row's status.

For each bank question naming BAJFINANCE, HINDALCO or KEC, count what the stores hold for each
measure and each of those companies:
  INPUTS_HELD     every measure has rows for every one of the 3 companies the question names
  INPUTS_PARTIAL  some do
  NOT_EXTRACTED   none do; empty means not extracted yet, never that the data does not exist
Status says what is held, not that an answer is right. Reading decides that.
Writes QUESTION_MAP_PROTO3.jsonl and .xlsx here. Read-only on every store.

    python tasks/pilot60/question_map/build_map.py
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = REPO / "reality_engine" / "data"
BANK = REPO / "tasks" / "pilot60" / "PILOT_BANK_2026-10-31.jsonl"
OUT = HERE / "QUESTION_MAP_PROTO3.jsonl"
XLSX = HERE / "QUESTION_MAP_PROTO3.xlsx"
COMPANIES = {"BAJFINANCE": "INE296A01032", "HINDALCO": "INE038A01020", "KEC": "INE389H01022"}
#: stated for the reader; not a score
MEANING = "INPUTS_HELD means rows exist for the measures. It does not mean the answer is right."


def load_rules() -> dict[str, tuple[list[str], str]]:
    spec = importlib.util.spec_from_file_location("question_map_rules", HERE / "rules.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out: dict[str, tuple[list[str], str]] = {}
    for mids, measures, formula in module.RULES:
        for mid in mids.split():
            if mid in out:
                raise ValueError(f"{mid} mapped twice")
            out[mid] = (measures, formula)
    return out


def bank_rows() -> list[dict]:
    rows = [json.loads(line) for line in BANK.open(encoding="utf-8")]
    return [r for r in rows if named(r)]


def named(row: dict) -> list[str]:
    symbols = {e.get("symbol") for e in row.get("entities") or [] if isinstance(e, dict)}
    return sorted(symbols & set(COMPANIES))


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _company_columns(con: sqlite3.Connection, table: str) -> list[str]:
    """Some tables fill ISIN on some rows and symbol on others, so a row counts by either."""
    columns = [r[1] for r in con.execute(f"pragma table_info('{table}')")]
    found = [c for c in ("isin", "symbol", "entity_id") if c in columns]
    if not found:
        raise ValueError(f"{table} has no company column: {columns[:12]}")
    return found


class Stores:
    def __init__(self) -> None:
        self.fact = _ro(DATA / "pilot" / "v4" / "fact_v4_pilot.db")
        self.v4 = _ro(DATA / "pilot" / "v4" / "v4.db")
        self.p3 = _ro(DATA / "extract_proto3.db")
        self.ei = _ro(DATA / "equity_intelligence.db")
        self.ann = _ro(DATA / "bse_announcements.db")
        self.chunks = [_ro(DATA / "pilot" / "pilot60" / n) for n in ("chunks_v3_pilot.db", "chunks_v3_history.db")]
        self.cache: dict[tuple[str, str], int] = {}

    def count(self, measure: str, symbol: str) -> int:
        key = (measure, symbol)
        if key not in self.cache:
            self.cache[key] = self._count(measure, symbol, COMPANIES[symbol])
        return self.cache[key]

    def _table_count(self, con: sqlite3.Connection, table: str, symbol: str, isin: str) -> int:
        columns = _company_columns(con, table)
        where = " or ".join(f"{c}=?" for c in columns)
        values = [symbol if c == "symbol" else isin for c in columns]
        return con.execute(f"select count(*) from {table} where {where}", values).fetchone()[0]

    def _count(self, measure: str, symbol: str, isin: str) -> int:
        kind, _, rest = measure.partition(":")
        if kind == "none":
            return 0
        if kind == "fact":
            return self.fact.execute("select count(*) from fact where entity_id=? and atom=?", (isin, rest)).fetchone()[0]
        if kind == "macro":
            return self.fact.execute("select count(*) from (select 1 from fact where atom=? limit 1)", (rest,)).fetchone()[0]
        if kind == "p3":
            table, _, metric = rest.partition(":")
            if metric:
                return self.p3.execute(f"select count(*) from {table} where isin=? and metric=?", (isin, metric)).fetchone()[0]
            return self._table_count(self.p3, table, symbol, isin)
        if kind == "doc":
            return sum(c.execute("select count(*) from doc where isin=? and doc_type=?", (isin, rest)).fetchone()[0] for c in self.chunks)
        if kind == "claim":
            return self.v4.execute("select count(*) from claim where entity_id=?", (isin,)).fetchone()[0]
        if kind == "member":
            return self._table_count(self.fact, "membership", symbol, isin)
        if kind == "ei":
            return self._table_count(self.ei, rest, symbol, isin)
        if kind == "ann":
            table = next(t for (t,) in self.ann.execute("select name from sqlite_master where type='table' and name not like 'sqlite%' and name not like '%fts%'"))
            return self._table_count(self.ann, table, symbol, isin)
        raise ValueError(f"unknown measure {measure}")


def status_of(row_counts: dict[str, dict[str, int]]) -> str:
    cells = [n for per in row_counts.values() for n in per.values()]
    if cells and all(cells):
        return "INPUTS_HELD"
    return "INPUTS_PARTIAL" if any(cells) else "NOT_EXTRACTED"


def build() -> list[dict]:
    rules, stores, out = load_rules(), Stores(), []
    for row in bank_rows():
        measures, formula = rules[row["mid"]]
        names = named(row)
        counts = {m: {s: stores.count(m, s) for s in names} for m in measures}
        others = sorted({e.get("symbol") for e in row["entities"] if isinstance(e, dict)} - set(COMPANIES))
        status = status_of(counts)
        out.append({"mid": row["mid"], "question": row["question"], "bank_label": row.get("answer_kind"),
                    "companies": names, "other_companies": others, "measures": measures,
                    "formula": formula, "rows_held": counts,
                    "missing": sorted(f"{m} {s}" for m, per in counts.items() for s, n in per.items() if not n),
                    "status": status,
                    "label_conflict": row.get("answer_kind") == "NOT IN DATA" and status == "INPUTS_HELD"})
    return out


def write(rows: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    book = Workbook()
    sheet = book.active
    sheet.title = "Question map"
    heads = ["Question id", "Question", "Bank label", "Companies", "Also names", "Measures needed", "How it is answered", "Status", "Missing", "Label conflict"]
    sheet.append(heads)
    fills = {"INPUTS_HELD": "C6EFCE", "INPUTS_PARTIAL": "FFEB9C", "NOT_EXTRACTED": "F8CBAD"}
    for row in rows:
        sheet.append([row["mid"], row["question"], row["bank_label"], ", ".join(row["companies"]), ", ".join(row["other_companies"]),
                      ", ".join(row["measures"]), row["formula"], row["status"], "; ".join(row["missing"]), "yes" if row["label_conflict"] else ""])
        sheet.cell(sheet.max_row, 8).fill = PatternFill("solid", fgColor=fills[row["status"]])
    for cell in sheet[1]:
        cell.font = Font(name="Arial", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
    for col, width in zip("ABCDEFGHIJ", (13, 70, 13, 18, 22, 42, 46, 16, 42, 9)):
        sheet.column_dimensions[col].width = width
    for line in sheet.iter_rows(min_row=2):
        for cell in line:
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    gaps = book.create_sheet("What to extract")
    gaps.append(["Measure and company", "Questions blocked"])
    for key, n in Counter(m for row in rows for m in row["missing"]).most_common():
        gaps.append([key, n])
    gaps.column_dimensions["A"].width = 60
    gaps.column_dimensions["B"].width = 18
    book.save(XLSX)


def main() -> int:
    rows = build()
    write(rows)
    print(MEANING)
    print("rows", len(rows), dict(Counter(r["status"] for r in rows)))
    print("label says NOT IN DATA but inputs held:", sum(r["label_conflict"] for r in rows))
    print("questions also naming other companies:", sum(bool(r["other_companies"]) for r in rows))
    for key, n in Counter(m for r in rows for m in r["missing"]).most_common(25):
        print(f"  {n:4d}  {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
