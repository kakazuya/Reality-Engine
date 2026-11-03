"""CLI: ``python -m reality_engine.pilot3.build --out <db> [--part registry|pages|stores|ratios|extract|kpi|transcripts|all]``
       ``[--ocr-db <ocr.db> ...]``.

Builds every pilot3 table in one file.  No network, no model.  Pages and documents come from pages.db (sandbox
pages only where pages.db lacks a document); ``--ocr-db`` (once per company OCR database, as ``pilot3.ocr`` writes
it) fills the text of a ``needs_ocr`` page into ``doc_page`` and feeds the same pages to the extractors.  ``extract``
runs the KPI and transcript extractors into the same db.  Each part drops and recreates its own tables (extract: its
own symbols' rows), so parts can be re-run; ``ratios`` needs ``stores`` built first."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from reality_engine.pilot3 import PAGES_DB, REAL_DB, SANDBOX, SYMBOLS, registry, schema, stores


EXTRACT_TABLES = ("kpi_series", "transcript_statement")


def row_counts(conn: sqlite3.Connection) -> dict:
    """``{table: {symbol: rows}}`` for every pilot3 core table that exists."""
    out = {}
    for name in (*schema.TABLES, *EXTRACT_TABLES):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
            continue
        if name in ("formula", "doc_alias"):
            out[name] = {"-": conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]}
            continue
        out[name] = dict(conn.execute(f"SELECT symbol, COUNT(*) FROM {name} GROUP BY symbol ORDER BY symbol"))
    return out


def extract(out: Path, only: str | None = None, ocr_dbs=()) -> dict:
    """KPI and transcript extractors into ``out`` (their own tables; each deletes its symbols' rows first).
    ``ocr_dbs`` are the ``ocr_page`` databases, so the KPI extractor reads the OCR'd pages too."""
    from reality_engine.pilot3 import kpi, transcripts

    result = {}
    for label, module in (("kpi", kpi), ("transcripts", transcripts)):
        if only and only != label:
            continue
        started = time.time()
        if label == "kpi":
            stats = module.run(str(out), list(SYMBOLS), SANDBOX, ocr_db=list(ocr_dbs) or None, pages_db=PAGES_DB)
        else:
            stats = module.run(str(out), list(SYMBOLS), SANDBOX)
        result[label] = {"seconds": round(time.time() - started, 1),
                         **{sym: {k: v for k, v in stats.get(sym, {}).items() if isinstance(v, (int, float))}
                            for sym in SYMBOLS}}
    return result


def build(out: Path, part: str = "all", ocr_dbs=()) -> dict:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(out)
    conn.execute("PRAGMA journal_mode=WAL")
    log = {}
    parts = ("registry", "pages", "stores", "ratios", "extract") if part == "all" else (part,)
    only = part if part in ("kpi", "transcripts") else None
    for name in parts:
        started = time.time()
        if name == "registry":
            log["company"] = registry.build_company(conn)
            log["doc"] = registry.build_doc(conn)
        elif name == "pages":
            log["doc_page"] = registry.build_pages(conn, ocr_dbs)
        elif name == "stores":
            log["stores"] = stores.build_stores(conn)
        elif name == "ratios":
            from reality_engine.pilot3 import ratios

            log["ratios"] = ratios.build_ratios(conn)
        elif name in ("extract", "kpi", "transcripts"):
            conn.commit()
            conn.close()  # the extractors open the db file themselves
            log["extract"] = extract(out, only, ocr_dbs)
            conn = sqlite3.connect(out)
        log[f"seconds_{name}"] = round(time.time() - started, 1)
    log["rows"] = row_counts(conn)
    conn.close()
    return log


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REAL_DB), help="default: the real pilot3.db on C")
    ap.add_argument("--part", default="all", choices=("registry", "pages", "stores", "ratios", "extract", "kpi", "transcripts", "all"))
    ap.add_argument("--ocr-db", action="append", default=[], help="ocr_page database written by pilot3.ocr (repeat for one per company)")
    args = ap.parse_args(argv)
    print(json.dumps(build(Path(args.out), args.part, tuple(args.ocr_db)), indent=1, default=str))


if __name__ == "__main__":
    main()
