"""CLI: ``python -m reality_engine.pilot3.build --out <db> [--part registry|pages|stores|ratios|all]``.

Builds the pilot3 core tables.  No network, no model.  Each part drops and recreates its own tables, so
parts can be re-run; ``ratios`` needs ``stores`` built first."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from reality_engine.pilot3 import registry, schema, stores


def row_counts(conn: sqlite3.Connection) -> dict:
    """``{table: {symbol: rows}}`` for every pilot3 core table that exists."""
    out = {}
    for name in schema.TABLES:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
            continue
        if name == "formula":
            out[name] = {"-": conn.execute("SELECT COUNT(*) FROM formula").fetchone()[0]}
            continue
        out[name] = dict(conn.execute(f"SELECT symbol, COUNT(*) FROM {name} GROUP BY symbol ORDER BY symbol"))
    return out


def build(out: Path, part: str = "all") -> dict:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(out)
    conn.execute("PRAGMA journal_mode=WAL")
    log = {}
    parts = ("registry", "pages", "stores", "ratios") if part == "all" else (part,)
    for name in parts:
        started = time.time()
        if name == "registry":
            log["company"] = registry.build_company(conn)
            log["doc"] = registry.build_doc(conn)
        elif name == "pages":
            log["doc_page"] = registry.build_pages(conn)
        elif name == "stores":
            log["stores"] = stores.build_stores(conn)
        elif name == "ratios":
            from reality_engine.pilot3 import ratios

            log["ratios"] = ratios.build_ratios(conn)
        log[f"seconds_{name}"] = round(time.time() - started, 1)
    log["rows"] = row_counts(conn)
    conn.close()
    return log


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--part", default="all", choices=("registry", "pages", "stores", "ratios", "all"))
    args = ap.parse_args(argv)
    print(json.dumps(build(Path(args.out), args.part), indent=1, default=str))


if __name__ == "__main__":
    main()
