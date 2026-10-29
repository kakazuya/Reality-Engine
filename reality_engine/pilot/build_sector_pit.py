"""Sector PIT store: ``company_sector_pit`` for the pilot universe, in one small file.

The full T1 build (``reality_engine.pilot.build_t1``) writes this table next to the
7.3M-row price panel; this builder writes the same rows alone, so the query layer can
open it as its own alias (``sector_pit``) without carrying the panel.  The source is the
live ``equity_intelligence`` classification — ``company_industry`` first, then
``master_companies`` for an ISIN it does not cover — which is a *current* snapshot, so
every row is backcast to ``valid_from = 2019-01-01`` with ``source='nse_classification'``
(the T1 build's own convention).  A label adopted later therefore never answers an
earlier decision day: the planner filters ``valid_from <= as_of``, and this table's
``valid_to`` is NULL until a real classification history (NSE/BSE circulars) replaces
the backcast.

    python -m reality_engine.pilot.build_sector_pit                 # -> .tmp/sector_pit.db
    python -m reality_engine.pilot.build_sector_pit --checks        # validate the build
    python -m reality_engine.pilot.build_sector_pit --universe all  # every held ISIN
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot.build_t1 import BACKCAST_START, bank_universe, create_schema

REPO = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT", REPO / "reality_engine" / "data"))
EI = DATA_ROOT / "equity_intelligence.db"
UNIVERSE = REPO / "tasks" / "pilot60" / "T2_ISINS.txt"
DB_NAME = "sector_pit.db"
KEEP = {"company_sector_pit", "ix_csp_basic", "ix_csp_sector"}
COLUMNS = ["isin", "macro", "sector", "industry", "basic_industry", "valid_from",
           "valid_to", "source"]


def universe(mode: str = "pilot") -> list[str]:
    """The universe ISINs: the T1 pilot universe, the T2 list, or [] for every ISIN.

    ``pilot`` is ``build_t1.bank_universe()`` — the ISINs the master bank itself names,
    which is the universe the T1 tables were built for.  ``tasks/pilot60/T2_ISINS.txt``
    is the 88-name stratified sample, not the whole bank.
    """
    if mode == "all":
        return []
    if mode == "t2" and UNIVERSE.is_file():
        seen: list[str] = []
        for line in UNIVERSE.read_text(encoding="utf-8").splitlines():
            isin = line.strip().upper()
            if isin and isin not in seen:
                seen.append(isin)
        return seen
    return bank_universe()


def read_rows(ei_path: Path, isins: list[str]) -> list[tuple]:
    """One classification row per ISIN: ``company_industry`` first, then the master."""
    clause, params = "", []
    if isins:
        clause = " AND isin IN (%s)" % ",".join("?" * len(isins))
        params = list(isins)
    con = connect_ro(ei_path, timeout_s=120)
    try:
        rows = con.execute(
            "SELECT isin, macro, sector, industry, basic_industry FROM company_industry "
            "WHERE isin IS NOT NULL AND isin <> ''" + clause, params).fetchall()
    finally:
        con.close()
    seen = {row[0] for row in rows}
    con = connect_ro(ei_path, timeout_s=120)
    try:  # the master's sector/industry is coarser, so it only fills the gap
        for isin, sector, industry in con.execute(
                "SELECT isin, sector, industry FROM master_companies "
                "WHERE isin IS NOT NULL AND isin <> ''" + clause, params):
            if isin not in seen and (sector or industry):
                rows.append((isin, None, sector, industry, None))
                seen.add(isin)
    finally:
        con.close()
    # A row with no label at all is not a classification: it would answer "this ISIN
    # exists" and nothing else, so it never enters the PIT store.
    return [(isin, macro, sector, industry, basic, BACKCAST_START, None,
             "nse_classification")
            for isin, macro, sector, industry, basic in rows
            if any(str(value or "").strip() for value in (macro, sector, industry, basic))]


def build(out: Path, mode: str = "pilot") -> dict:
    """Write ``<out>/sector_pit.db``; returns the row counts and the universe size."""
    isins = universe(mode)
    rows = read_rows(EI, isins)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / DB_NAME
    if path.exists():
        resolved = path.resolve()
        if REPO not in resolved.parents and resolved.parent != REPO:
            raise RuntimeError(f"refusing to overwrite outside the worktree: {resolved}")
        path.unlink()
    con = sqlite3.connect(path)
    try:
        create_schema(con, KEEP)
        con.executemany(
            f"INSERT INTO company_sector_pit ({','.join(COLUMNS)}) "
            f"VALUES ({','.join('?' * len(COLUMNS))})", rows)
        con.commit()
    finally:
        con.close()
    summary = {"db": str(path), "universe": len(isins) or "all", "rows": len(rows),
               "isins": len({row[0] for row in rows}), "valid_from": BACKCAST_START}
    (out / "sector_pit_meta.json").write_text(json.dumps(summary, indent=1),
                                              encoding="utf-8")
    return summary


def checks(path: Path) -> dict[str, object]:
    """The build's own validation: as-of semantics and the source label."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        total = con.execute("SELECT COUNT(*) FROM company_sector_pit").fetchone()[0]
        out = {
            "rows": total,
            "isins": con.execute(
                "SELECT COUNT(DISTINCT isin) FROM company_sector_pit").fetchone()[0],
            "labelled": con.execute(
                "SELECT COUNT(*) FROM company_sector_pit WHERE COALESCE("
                "macro,sector,industry,basic_industry) IS NOT NULL").fetchone()[0],
            "sources": [dict(row) for row in con.execute(
                "SELECT source, COUNT(*) n FROM company_sector_pit GROUP BY source")],
            "valid_from": [dict(row) for row in con.execute(
                "SELECT valid_from, COUNT(*) n FROM company_sector_pit GROUP BY valid_from")],
            "open_intervals": con.execute(
                "SELECT COUNT(*) FROM company_sector_pit WHERE valid_to IS NULL"
            ).fetchone()[0],
            # The as-of read the planner runs: a row adopted after the decision day must
            # not answer it.  Every row here is backcast, so this is the whole table.
            "as_of_2026_10_19": con.execute(
                "SELECT COUNT(*) FROM company_sector_pit WHERE COALESCE("
                "macro,sector,industry,basic_industry) IS NOT NULL "
                "AND valid_from <= '2026-10-19' AND (valid_to IS NULL OR "
                "valid_to >= '2026-10-19')").fetchone()[0],
            "as_of_2018_12_31": con.execute(
                "SELECT COUNT(*) FROM company_sector_pit WHERE COALESCE("
                "macro,sector,industry,basic_industry) IS NOT NULL "
                "AND valid_from <= '2018-12-31' AND (valid_to IS NULL OR "
                "valid_to >= '2018-12-31')").fetchone()[0],
        }
    finally:
        con.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / ".tmp"))
    ap.add_argument("--universe", choices=("pilot", "t2", "all"), default="pilot")
    ap.add_argument("--checks", action="store_true",
                    help="do not build: validate the file at --out")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.checks:
        path = out / DB_NAME
        if not path.is_file():
            print(f"missing {path}", file=sys.stderr)
            return 2
        result = checks(path)
        print(json.dumps(result, indent=1))
        ok = (result["rows"] > 0 and result["labelled"] == result["rows"]
              and result["open_intervals"] == result["rows"]
              and result["as_of_2018_12_31"] == 0
              and result["as_of_2026_10_19"] == result["labelled"])
        print("ALL CHECKS PASSED" if ok else "CHECKS FAILED")
        return 0 if ok else 1
    summary = build(out, args.universe)
    print(json.dumps(summary, indent=1))
    return 0 if summary["rows"] else 1


if __name__ == "__main__":
    sys.exit(main())
