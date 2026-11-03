"""A1: does the database answer each question's needs, point in time?

Every question names data needs (a typed-table row, or a text search in one document type).  A row need is met
when the table holds a row for that symbol, period, basis and metric with ``known_at`` <= the question's
``as_of``; a text need is met when the pilot3 bm25 search returns a page, of the document type asked and known
by ``as_of``, that carries every term.  The search is the ``pilot3_search`` tool's own function
(``plugins/reality-data/server/lookups_pilot3.py``), called directly, never through the MCP server.

``--hidden`` prints counts only (no qid, no question text); the dev run also groups the unmet needs by
(table or document type, metric) with counts, largest first, which is the next loop's work list.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "plugins" / "reality-data" / "server"
DEFAULT_DB = ROOT / "reality_engine" / "data" / "pilot3" / "pilot3.db"

# table -> (metric column, period column, period column kind: "label" (Q1FY27) or "date" (2026-06-30))
ROW_TABLES: dict[str, tuple[str | None, str, str]] = {
    "kpi_series": ("metric", "fiscal_period", "label"),
    "fin_annual_line": ("line_item", "fiscal_year", "label"),
    "fin_quarter_xbrl": ("line_item", "fiscal_period", "label"),
    "ratio_panel": ("metric", "fiscal_period", "label"),
    "guidance": ("metric", "target_period", "label"),
    "shp_category": ("category", "quarter_end", "date"),
    "share_capital": (None, "as_of_date", "date"),
    "dividend_event": (None, "fiscal_year", "label"),
    "price_delivery": (None, "date", "date"),
}

_LABEL = re.compile(r"^(Q[1-4]|H1|H2|9M|FY)?FY'?(\d{2,4})$", re.I)


def open_ro(path: Path) -> sqlite3.Connection:
    """Read-only sqlite connection (``mode=ro``), the only way this module touches a database."""
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def period_bounds(label: str) -> tuple[str, str] | None:
    """The first and last calendar day of a fiscal label (FY26, H1FY26, Q1FY27, 9MFY26); None when unparsable."""
    match = _LABEL.fullmatch(str(label or "").strip().upper())
    if not match:
        return None
    kind = (match.group(1) or "FY").upper()
    year = int(match.group(2))
    year = 2000 + year if year < 100 else year
    start_year = year - 1
    spans = {"FY": (4, 0, 3, 31), "H1": (4, 0, 9, 30), "H2": (10, 0, 3, 31), "9M": (4, 0, 12, 31),
             "Q1": (4, 0, 6, 30), "Q2": (7, 0, 9, 30), "Q3": (10, 0, 12, 31), "Q4": (1, 1, 3, 31)}
    start_month, start_add, end_month, end_day = spans[kind]
    start = f"{start_year + start_add:04d}-{start_month:02d}-01"
    end_year = start_year + 1 if kind in ("FY", "H2", "Q4") else start_year
    end = f"{end_year:04d}-{end_month:02d}-{end_day:02d}"
    return start, end


def _labels(period: str) -> list[str]:
    """Spellings a store may use for the same fiscal label (FY26 / FY2026)."""
    values = [period]
    match = _LABEL.fullmatch(str(period or "").strip().upper())
    if match:
        kind = match.group(1) or "FY"
        year = int(match.group(2))
        values.append(f"{kind}FY{year}")
        if year < 100:
            values.append(f"{kind}FY20{year:02d}")
    return sorted(set(values))


class Db:
    """The branch's pilot3 database, read-only, with a column cache and a page cache for the text needs."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.con = open_ro(self.path)
        self._columns: dict[str, list[str]] = {}
        self._pages: dict[tuple[str, int], str | None] = {}

    def columns(self, table: str) -> list[str]:
        if table not in self._columns:
            self._columns[table] = [r[1] for r in self.con.execute(f'PRAGMA table_info("{table}")')]
        return self._columns[table]

    def page_text(self, doc_key: str, page: int) -> str | None:
        key = (str(doc_key), int(page))
        if key not in self._pages:
            row = self.con.execute("SELECT text FROM doc_page WHERE doc_key=? AND page=?", key).fetchone()
            self._pages[key] = None if row is None else (row[0] or "")
        return self._pages[key]

    def close(self) -> None:
        self.con.close()


def row_need_met(db: Db, symbol: str, need: dict[str, Any], as_of: str) -> bool:
    """One typed-table need.  Unknown table, missing column or no point-in-time row means unmet."""
    table = str(need.get("table") or "")
    if table not in ROW_TABLES:
        return False
    metric_col, period_col, kind = ROW_TABLES[table]
    columns = db.columns(table)
    if period_col not in columns or "symbol" not in columns:
        return False
    where, args = ["symbol=?"], [symbol]
    period = str(need.get("period") or "")
    if kind == "date" and "-" in period:
        where.append(f"{period_col}=?")
        args.append(period)
    else:
        bounds = period_bounds(period)
        if kind == "date" and bounds:
            where.append(f"{period_col}>=? AND {period_col}<=?")
            args.extend(bounds)
        else:
            labels = _labels(period)
            where.append(f"{period_col} IN ({','.join('?' for _ in labels)})")
            args.extend(labels)
    if metric_col and need.get("metric"):
        if metric_col not in columns:
            return False
        # stores key metrics lower-case with underscores; accept the question's own spelling too
        spelled = str(need["metric"]).strip()
        where.append(f"lower({metric_col}) IN (?, ?)")
        args.extend([spelled.lower(), re.sub(r"[\s\-]+", "_", spelled.lower())])
    basis = need.get("basis")
    if basis and "basis" in columns:
        where.append("basis=?")
        args.append(basis)
    if "known_at" in columns:
        where.append("known_at IS NOT NULL AND substr(known_at, 1, 10) <= ?")
        args.append(as_of)
    if table == "guidance":
        where.append("(low IS NOT NULL OR high IS NOT NULL)")
    metric = need.get("metric")
    if table == "price_delivery" and metric and str(metric).lower() in columns:
        where.append(f'"{str(metric).lower()}" IS NOT NULL')
    sql = f'SELECT 1 FROM "{table}" WHERE {" AND ".join(where)} LIMIT 1'
    try:
        return db.con.execute(sql, tuple(args)).fetchone() is not None
    except sqlite3.Error:
        return False


_PILOT3_MODULE: Any = None


def _pilot3_search():
    """The pilot3 module's own ``search`` function; the MCP server is not started.

    The server modules import each other by bare name (``import core``), so a checkout module of the same
    name already in ``sys.modules`` (another test suite's ``core``) would shadow the server's: it is moved
    aside for the import and put back afterwards, while the server module keeps its own reference.
    """
    global _PILOT3_MODULE
    if _PILOT3_MODULE is not None:
        return _PILOT3_MODULE
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))
    foreign = sys.modules.get("core")
    if foreign is not None and not hasattr(foreign, "connect_ro"):
        del sys.modules["core"]
    try:
        import lookups_pilot3  # noqa: PLC0415 - the server path is added just above
    finally:
        if foreign is not None:
            sys.modules["core"] = foreign
    _PILOT3_MODULE = lookups_pilot3
    return lookups_pilot3


def text_need_met(db: Db, symbol: str, need: dict[str, Any], as_of: str) -> bool:
    """A text need: a hit page of the asked document type, known by as_of, carrying every term."""
    terms = [str(t) for t in need.get("terms") or [] if str(t).strip()]
    if not terms:
        return False
    os.environ["REALITY_PILOT3_DB"] = str(db.path)
    module = _pilot3_search()
    try:
        reply = module.search(symbol, " ".join(terms), as_of=as_of, limit=25,
                              doc_type=need.get("doc_type"), period=need.get("period"))
    except Exception:  # a symbol pilot3 does not hold, or a bad fts query: the need is not met
        return False
    wanted = [t.lower() for t in terms]
    for row in reply.get("rows") or []:
        source = str((row.get("provenance") or {}).get("source") or "")
        doc_key = source.rsplit(" p", 1)[0] if " p" in source else source
        page = row.get("page")
        text = db.page_text(doc_key, int(page)) if page is not None else None
        if text is None:
            text = re.sub(r"[\[\]]", "", str(row.get("snippet") or ""))
        lowered = text.lower()
        if all(term in lowered for term in wanted):
            return True
    return False


def need_key(need: dict[str, Any]) -> str:
    """The work-list key: ``table.metric`` for a row need, ``doc:<type>`` for a text need."""
    if need.get("kind") == "row":
        return f"{need.get('table')}.{need.get('metric') or '*'}"
    return f"doc:{need.get('doc_type')}"


def score(questions: list[dict[str, Any]], db: Db, hidden: bool = False) -> dict[str, Any]:
    started = time.time()
    row_cache: dict[tuple, bool] = {}
    text_cache: dict[tuple, bool] = {}
    per_company: dict[str, dict[str, float]] = {}
    rows: list[dict[str, Any]] = []
    unmet: dict[str, int] = {}
    for q in questions:
        symbol = str(q.get("symbol") or "?")
        as_of = str(q.get("as_of") or "")
        counts = per_company.setdefault(symbol, {"questions": 0, "all": 0, "some": 0, "none": 0})
        needs = [n for n in (q.get("needs") or []) if isinstance(n, dict)]
        met = 0
        missed: list[str] = []
        for need in needs:
            if need.get("kind") == "row":
                key = (symbol, need.get("table"), need.get("metric"), need.get("period"), need.get("basis"), as_of)
                if key not in row_cache:
                    row_cache[key] = row_need_met(db, symbol, need, as_of)
                ok = row_cache[key]
            else:
                key = (symbol, need.get("doc_type"), tuple(str(t).lower() for t in need.get("terms") or []),
                       need.get("period"), as_of)
                if key not in text_cache:
                    text_cache[key] = text_need_met(db, symbol, need, as_of)
                ok = text_cache[key]
            if ok:
                met += 1
            else:
                missed.append(need_key(need))
                unmet[need_key(need)] = unmet.get(need_key(need), 0) + 1
        status = "all" if needs and met == len(needs) else ("none" if not met else "some")
        counts["questions"] += 1
        counts[status] += 1
        if not hidden:
            rows.append({"qid": q.get("qid"), "symbol": symbol, "needs": len(needs), "met": met,
                         "status": status, "unmet": missed})
    total: dict[str, float] = {"questions": len(questions), "all": sum(c["all"] for c in per_company.values()),
                               "some": sum(c["some"] for c in per_company.values()),
                               "none": sum(c["none"] for c in per_company.values())}
    for block in [*per_company.values(), total]:
        block["rate"] = round(block["all"] / block["questions"], 4) if block["questions"] else 0.0
    report: dict[str, Any] = {
        "db": str(db.path), "hidden": hidden, "a1": {"companies": dict(sorted(per_company.items())),
                                                     "total": total}}
    if not hidden:
        report["questions"] = rows
        report["unmet"] = [{"key": key, "count": count}
                           for key, count in sorted(unmet.items(), key=lambda item: (-item[1], item[0]))]
    report["elapsed_s"] = round(time.time() - started, 2)
    return report


def _print(report: dict[str, Any]) -> None:
    a1 = report["a1"]
    print(f"A1 {report['db']}{' (hidden)' if report['hidden'] else ''}:"
          f" {a1['total']['all']}/{a1['total']['questions']} questions fully answerable"
          f" ({a1['total']['rate']:.0%}) in {report['elapsed_s']} s")
    for symbol, block in a1["companies"].items():
        print(f"  {symbol}: all {block['all']}  some {block['some']}  none {block['none']}"
              f"  of {block['questions']}  ({block['rate']:.0%})")
    if report["hidden"]:
        return
    if report.get("unmet"):
        print("  unmet needs (largest first):")
        for item in report["unmet"][:20]:
            print(f"    {item['count']:3d}  {item['key']}")
        if len(report["unmet"]) > 20:
            print(f"    ... {len(report['unmet']) - 20} more in the json")
    else:
        print("  unmet needs: none")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="answerable", description="A1 answerability of a question set")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="pilot3 database (opened read-only)")
    parser.add_argument("--qset", required=True, help="question set jsonl (dev or hidden file)")
    parser.add_argument("--hidden", action="store_true", help="counts only, no qid and no question text")
    parser.add_argument("--out", default="", help="write the report json here")
    args = parser.parse_args(argv)
    path = Path(args.qset)
    questions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    db = Db(Path(args.db))
    try:
        report = score(questions, db, args.hidden)
    finally:
        db.close()
    _print(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
