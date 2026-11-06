"""Generate a build profile from a list of companies, with no hand-written facts (T-094).

CLI: ``python -m reality_engine.pilot3.make_profile DALBHARAT POWERGRID --name unseen5 --root <dir>
     --window-start 2023-10-01 --compute-start 2022-07-01 --out <profile.json>``

Name, BSE code and every ISIN come from ``master_companies`` and ``symbol_isin_history``; the sector family and the lender
flag from ``company_industry``, joined by ISIN, through ``sector_map.yaml``.  ``master_companies.sector`` is not used:
6,443 of its 6,940 rows are null, "General Diversified" or "Other".  A company with no label is ``unknown``: it builds on
the common lexicons and is reported, and no sector is guessed from its name.

Working now: one company at a time, by symbol or ISIN.  Output has the shape of ``tasks/night_loop/pilot10_profile.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

import yaml

from reality_engine.config import DATA_DIR
from reality_engine.db.readonly import connect_ro

# Not under lexicon/: kpi.load_lexicon reads every yaml in that folder as a KPI lexicon.
SECTOR_MAP = Path(__file__).with_name("sector_map.yaml")
UNKNOWN = "unknown"


def main_store() -> Path:
    root = os.environ.get("REALITY_DATA_ROOT")
    return Path(root) / "equity_intelligence.db" if root else DATA_DIR / "equity_intelligence.db"


def sector_map() -> dict:
    return yaml.safe_load(SECTOR_MAP.read_text(encoding="utf-8"))


def family_of(basic_industry: str | None, industry: str | None, table: dict) -> str:
    """The lexicon family of a company: its basic industry first, then its industry, else ``unknown``."""
    for name, column in ((basic_industry, "basic_industry"), (industry, "industry")):
        if name and name in (table.get(column) or {}):
            return table[column][name]
    return UNKNOWN


def is_lender(family: str, table: dict) -> bool:
    """TODO(T-094): cross-check against filed lines through ``lookups_pilot3._is_lender`` moved to one shared home, and
    report a disagreement.  That reads the built database, so decide where the second check runs and say why."""
    return family in (table.get("lender_families") or ())


def company_row(conn: sqlite3.Connection, key: str, table: dict) -> dict:
    """One company entry from the stores.  ``key`` is a symbol or an ISIN; everything else is joined by ISIN."""
    text = key.strip().upper()
    master = conn.execute("SELECT isin, nse_symbol, bse_code, company_name FROM master_companies "
                          "WHERE nse_symbol=? OR isin=? LIMIT 1", (text, text)).fetchone()
    if master is None:
        raise KeyError(f"{key!r} is not in master_companies")
    symbol = master["nse_symbol"] or text
    held = [row[0] for row in conn.execute("SELECT DISTINCT isin FROM symbol_isin_history WHERE symbol=? "
                                           "ORDER BY first_date", (symbol,))]
    isins = list(dict.fromkeys([master["isin"], *held]))
    marks = ",".join("?" * len(isins))
    label = conn.execute(f"SELECT basic_industry, industry FROM company_industry WHERE isin IN ({marks}) "
                         "AND basic_industry IS NOT NULL LIMIT 1", isins).fetchone()
    family = family_of(label["basic_industry"], label["industry"], table) if label else UNKNOWN
    return {"symbol": symbol, "name": master["company_name"], "bse_code": str(master["bse_code"] or ""),
            "isins": isins, "sector": family, "lender": is_lender(family, table)}


def make_profile(keys: list[str], name: str, root: Path, window_start: str | None, compute_start: str | None,
                 conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or connect_ro(str(main_store()))
    conn.row_factory = sqlite3.Row
    table = sector_map()
    return {"name": name, "pages_db": str(root / "pages.db"), "raw_root": str(root / "raw"),
            "manifest": str(root / "raw" / "manifest.csv"), "out": str(root / f"{name}.db"),
            "window_start": window_start, "compute_start": compute_start,
            "companies": [company_row(conn, key, table) for key in keys]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("companies", nargs="+", help="symbols or ISINs")
    ap.add_argument("--name", required=True)
    ap.add_argument("--root", required=True, type=Path, help="folder of the build's pages.db, raw and output")
    ap.add_argument("--window-start", default=None)
    ap.add_argument("--compute-start", default=None)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    profile = make_profile(args.companies, args.name, args.root, args.window_start, args.compute_start)
    args.out.write_text(json.dumps(profile, indent=1), encoding="utf-8")
    for company in profile["companies"]:
        print(company["symbol"], company["sector"], "lender" if company["lender"] else "", len(company["isins"]), "ISINs")


if __name__ == "__main__":
    main()
