"""CLI: ``python -m reality_engine.pilot3.build --out <db> [--part registry|pages|stores|comparatives|ratios|extract|segments|kpi|transcripts|guidance|all]``
       ``[--symbols KEC[,BAJFINANCE,HINDALCO]] [--ocr-db <ocr.db> ...]``.

Builds every pilot3 table in one file.  No network, no model.  Pages and documents come from pages.db (sandbox
pages only where pages.db lacks a document); ``--ocr-db`` (once per company OCR database, as ``pilot3.ocr`` writes
it) fills the text of a ``needs_ocr`` page into ``doc_page`` and feeds the same pages to the extractors.  ``extract``
runs the KPI and transcript extractors into the same db; ``guidance`` runs the guidance extractor over the pages
already in it.  ``comparatives`` (T-057) reads the printed comparative columns of each results PDF into
``fin_quarter_printed``; it runs after ``stores`` and before ``ratios``, and in ``all`` only under a profile.
Each part drops and recreates its own tables (extract: its own symbols' rows; comparatives: its own symbols'
rows, with ``CREATE TABLE IF NOT EXISTS``), so parts can be re-run; ``ratios`` needs ``stores`` built first and
``guidance`` needs ``pages``.

``--symbols`` limits ONLY the extractors (extract, kpi, transcripts, guidance), which already delete and rewrite
one company's rows; registry, pages, stores and ratios rebuild every company's rows and ignore it (``--help``
says so).  ``build --part kpi --symbols <SYM>`` therefore gives exactly that company's rows of a full part build.
``--profile <json>`` (T-056) reads the company list, pages db, raw root, manifest, output and history window from
a profile file, and then ``--symbols`` limits every part: a profile database built for one company holds one
company.  ``--out`` and ``--pages-db`` override the profile's paths."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sqlite3
import time
from pathlib import Path

from reality_engine.pilot3 import REAL_DB, SANDBOX, profile, registry, schema, stores


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


def extract(out: Path, only: str | None = None, ocr_dbs=(), symbols=None, pages_db=None) -> dict:
    """KPI and transcript extractors into ``out`` (their own tables; each deletes its symbols' rows first).
    ``ocr_dbs`` are the ``ocr_page`` databases, so the KPI extractor reads the OCR'd pages too.  A profile build
    reads pages.db only (no sandbox) and the profile's pages database unless ``pages_db`` says otherwise."""
    from reality_engine.pilot3 import kpi, transcripts

    symbols = list(symbols or profile.symbols())
    pages = Path(pages_db) if pages_db else profile.pages_db()
    sandbox = None if profile.under_profile() else SANDBOX
    result = {}
    for label, module in (("kpi", kpi), ("transcripts", transcripts)):
        if only and only != label:
            continue
        started = time.time()
        if label == "kpi":
            stats = module.run(str(out), symbols, sandbox, ocr_db=list(ocr_dbs) or None, pages_db=pages)
        else:
            stats = module.run(str(out), symbols, sandbox)
        result[label] = {"seconds": round(time.time() - started, 1),
                         **{sym: {k: v for k, v in stats.get(sym, {}).items() if isinstance(v, (int, float))}
                            for sym in symbols}}
    return result


def build(out: Path, part: str = "all", ocr_dbs=(), symbols=None, pages_db=None) -> dict:
    out = Path(out)
    known = profile.symbols()
    symbols = [s.strip().upper() for s in (symbols or known) if s and s.strip()]
    unknown = set(symbols) - set(known)
    if not symbols or unknown:
        raise ValueError(f"--symbols must be a non-empty subset of {', '.join(known)}; got {', '.join(sorted(unknown)) or 'nothing'}")
    out.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(out)
    conn.execute("PRAGMA journal_mode=WAL")
    log = {}
    parts = (["registry", "pages", "stores", "comparatives", "ratios", "extract", "segments", "guidance"]
             if part == "all" else [part])
    if "comparatives" in parts and not profile.under_profile():
        parts.remove("comparatives")  # no profile: the pilot3 build keeps its present rows (T-057)
    only = part if part in ("kpi", "transcripts") else None
    # A profile build limits every part to --symbols (a pilot10 database for one company holds one company);
    # without a profile the registry/pages/stores/ratios parts keep rebuilding every company, as they always did.
    profile.set_scope(tuple(symbols) if profile.under_profile() else None)
    try:
        for name in parts:
            started = time.time()
            if name == "registry":
                log["company"] = registry.build_company(conn)
                log["doc"] = registry.build_doc(conn)
            elif name == "pages":
                log["doc_page"] = registry.build_pages(conn, ocr_dbs)
            elif name == "stores":
                log["stores"] = stores.build_stores(conn)
            elif name == "comparatives":
                from reality_engine.pilot3 import comparatives

                log["comparatives"] = comparatives.run(
                    conn, symbols, out.with_name(f"{out.stem}_comparatives_review.csv"))
            elif name == "ratios":
                from reality_engine.pilot3 import ratios

                log["ratios"] = ratios.build_ratios(conn)
            elif name in ("extract", "kpi", "transcripts"):
                conn.commit()
                conn.close()  # the extractors open the db file themselves
                log["extract"] = extract(out, only, ocr_dbs, symbols, pages_db)
                conn = sqlite3.connect(out)
            elif name == "segments":
                from reality_engine.pilot3.xbrl_segments import run as run_segments

                conn.commit()
                conn.close()  # the segment reader opens the db file itself and needs kpi_series from the extract part
                log["segments"] = run_segments(str(out), symbols)
                conn = sqlite3.connect(out)
            elif name == "guidance":
                from reality_engine.pilot3.guidance import run as run_guidance

                conn.commit()
                conn.close()  # guidance reads doc_page and transcript_statement from the db file
                log["guidance"] = run_guidance(str(out), symbols)
                conn = sqlite3.connect(out)
            log[f"seconds_{name}"] = round(time.time() - started, 1)
        log["rows"] = row_counts(conn)
    finally:
        conn.close()
        profile.set_scope(None)
    return log


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default=None,
                    help="build profile JSON (T-056): companies, pages db, raw root, manifest, output, window start")
    ap.add_argument("--out", default=None, help="default: the profile's output, else the real pilot3.db on C")
    ap.add_argument("--pages-db", default=None, help="override the profile's pages database")
    ap.add_argument("--part", default="all", choices=("registry", "pages", "stores", "comparatives", "ratios", "extract", "segments", "kpi", "transcripts", "guidance", "all"))
    ap.add_argument("--symbols", default=None,
                    help="comma list: without a profile it limits extract/kpi/transcripts/guidance only (registry/pages/stores/ratios rebuild every company); a profile build limits every part (default: the profile's companies, else the pilot3 three)")
    ap.add_argument("--ocr-db", action="append", default=[], help="ocr_page database written by pilot3.ocr (repeat for one per company)")
    args = ap.parse_args(argv)
    if args.profile:
        loaded = profile.load(args.profile)
        if args.pages_db:
            loaded = dataclasses.replace(loaded, pages_db=Path(args.pages_db))
        profile.activate(loaded)
    symbols = args.symbols.split(",") if args.symbols else None
    current = profile.active()
    out = Path(args.out) if args.out else (current.out if current is not None else REAL_DB)
    print(json.dumps(build(out, args.part, tuple(args.ocr_db), symbols, args.pages_db), indent=1, default=str))


if __name__ == "__main__":
    main()
