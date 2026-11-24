"""Generate a build profile from a list of companies, with no hand-written facts (T-094).

CLI: ``python -m reality_engine.pilot3.make_profile DALBHARAT POWERGRID --name unseen5 --root <dir>
     --window-start 2023-10-01 --compute-start 2022-07-01 --out <profile.json> [--check-db <built.db>]``

Name, BSE code and every ISIN come from the stores; the sector family and the lender flag from ``company_industry``,
joined by ISIN, through ``sector_map.yaml``.  ``master_companies.sector`` is not used: 6,443 of its 6,940 rows are
null, "General Diversified" or "Other".  A company with no label is ``unknown``: it builds on the common lexicons and
is reported, and no sector is guessed from its name.

Every ISIN a company has held is gathered from the data, never from a hand list: ``symbol_isin_history``, the
``isin_rekey_log`` audit, and the ISINs the stores actually hold under the same symbol or BSE code
(``corporate_documents``, ``shp_index``, ``results_xbrl.filings``, ``master_companies``).  A candidate is kept only
when it is the same issuer (the ISIN's first 7 characters match, or it is the IN9 partly-paid form of the same
issuer) or the rekey log records it; a profile that dropped a company's older filings would filter its history out
without any error.

The label is looked up by every one of those ISINs and then by the symbol; when the exchange taxonomy has no row at
all, ``master_companies.industry`` is a second tier but only for the coarse names that map cleanly to a family
(``master_industry`` in ``sector_map.yaml``), and the BSE industry its scrip master carries on ``board_meetings`` a
third (``bse_industry``, used only when every filing prints the same value).  A company still without a label stays
``unknown``.

The profile's ``lender`` flag comes from the exchange taxonomy, which exists before the build.  ``--check-db``
compares it with the filed lines of a built database (``lender.py``) and prints every disagreement; that second
check cannot run at profile time because it reads the database the build has not written yet.

Output has the shape of ``tasks/night_loop/pilot10_profile.json``.  ``mapped_share`` reports how many active
companies the taxonomy can place: a lexicon family (and which tier placed it), an honest ``unknown``, or no label.
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
from reality_engine.pilot3.lender import filed_lender

# Not under lexicon/: kpi.load_lexicon reads every yaml in that folder as a KPI lexicon.
SECTOR_MAP = Path(__file__).with_name("sector_map.yaml")
UNKNOWN = "unknown"
RESULTS_DB = "results_xbrl.db"


def main_store() -> Path:
    root = os.environ.get("REALITY_DATA_ROOT")
    return Path(root) / "equity_intelligence.db" if root else DATA_DIR / "equity_intelligence.db"


def results_store() -> Path | None:
    """The results XBRL store beside the main one (it holds the older ISINs of a results filing)."""
    path = main_store().with_name(RESULTS_DB)
    return path if path.is_file() else None


def sector_map() -> dict:
    return yaml.safe_load(SECTOR_MAP.read_text(encoding="utf-8"))


def same_issuer(isin: str, current: str) -> bool:
    """True when ``isin`` belongs to the same issuer as ``current``: the same first 7 characters, or the IN9
    partly-paid form of an INE ISIN (same issuer code at positions 3:7)."""
    if not isin or not current or len(isin) != 12 or len(current) != 12:
        return False
    if isin[:7] == current[:7]:
        return True
    return isin[:2] == current[:2] == "IN" and isin[3:7] == current[3:7] and {isin[2], current[2]} == {"E", "9"}


def family_of(basic_industry: str | None, industry: str | None, table: dict) -> str:
    """The lexicon family of a company: its basic industry first, then its industry, else ``unknown``."""
    for name, column in ((basic_industry, "basic_industry"), (industry, "industry")):
        if name and name in (table.get(column) or {}):
            return table[column][name]
    return UNKNOWN


def is_lender(basic_industry: str | None, industry: str | None, table: dict) -> bool:
    """A lender by the exchange taxonomy (bank, NBFC, housing / microfinance lender, insurer), independent of
    whether a lexicon family exists.  The filed-line check is ``cross_check`` on a built database."""
    for name, column in ((basic_industry, "lender_basic_industry"), (industry, "lender_industry")):
        if name and name in (table.get(column) or ()):
            return True
    return False


def issuer_isins(conn: sqlite3.Connection, symbol: str, current_isin: str, bse_code: str = "",
                 results_conn: sqlite3.Connection | None = None) -> list[str]:
    """Every ISIN the company has held, current first, kept only for the same issuer or a recorded rekey."""
    found: list[tuple[str, str]] = []
    rekeyed: set[str] = set()

    def add(isin: object, key: str = "") -> None:
        if isin:
            found.append((str(isin), key))

    for row in conn.execute("SELECT isin, first_date FROM symbol_isin_history WHERE symbol=? ORDER BY first_date",
                            (symbol,)):
        add(row[0], row[1] or "")
    for row in conn.execute("SELECT old_isin, new_isin FROM isin_rekey_log WHERE symbol=?", (symbol,)):
        for value in row:
            add(value)
            if value:
                rekeyed.add(str(value))
    for row in conn.execute("SELECT DISTINCT isin FROM corporate_documents WHERE symbol=?", (symbol,)):
        add(row[0])
    for row in conn.execute("SELECT DISTINCT isin FROM shp_index WHERE symbol=?", (symbol,)):
        add(row[0])
    for row in conn.execute("SELECT isin FROM master_companies WHERE nse_symbol=? OR bse_code=?",
                            (symbol, bse_code or symbol)):
        add(row[0])
    if results_conn is not None:
        for row in results_conn.execute("SELECT DISTINCT isin FROM filings WHERE symbol=? OR scrip_code=?",
                                        (symbol, bse_code or symbol)):
            add(row[0])
    out = [current_isin]
    for isin, _ in sorted(found, key=lambda item: item[1]):
        if isin and isin not in out and (isin in rekeyed or same_issuer(isin, current_isin)):
            out.append(isin)
    return out


def label_of(conn: sqlite3.Connection, isins: list[str], symbol: str | None = None) -> tuple[str | None, str | None]:
    """``(basic_industry, industry)`` of the first of ``isins`` (then of ``symbol``) the taxonomy labels."""
    if isins:
        marks = ",".join("?" * len(isins))
        row = conn.execute(f"SELECT basic_industry, industry FROM company_industry WHERE isin IN ({marks}) "
                           "AND (basic_industry IS NOT NULL OR industry IS NOT NULL) "
                           "ORDER BY CASE WHEN isin=? THEN 0 ELSE 1 END LIMIT 1", (*isins, isins[0])).fetchone()
        if row:
            return (row["basic_industry"], row["industry"])
    if symbol:
        row = conn.execute("SELECT basic_industry, industry FROM company_industry WHERE symbol=? "
                           "AND (basic_industry IS NOT NULL OR industry IS NOT NULL) LIMIT 1", (symbol,)).fetchone()
        if row:
            return (row["basic_industry"], row["industry"])
    return (None, None)


def bse_family(conn: sqlite3.Connection, isins: list[str], table: dict) -> str:
    """The BSE taxonomy family, used when ``company_industry`` has no row: ``board_meetings.industry`` is the BSE
    industry the scrip master carries, and only a single value across the issuer's filings is trusted."""
    isins = [isin for isin in isins if isin]
    if not isins:
        return UNKNOWN
    marks = ",".join("?" * len(isins))
    row = conn.execute("SELECT COUNT(DISTINCT industry), MIN(industry) FROM board_meetings "
                       "WHERE isin IN (" + marks + ") AND industry IS NOT NULL AND industry<>''", isins).fetchone()
    if row and row[0] == 1:
        return (table.get("bse_industry") or {}).get(row[1], UNKNOWN)
    return UNKNOWN


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def filed_name(conn: sqlite3.Connection, isin: str, bse_code: str,
               results_conn: sqlite3.Connection | None = None) -> str | None:
    """A company name some store files for this ISIN (then BSE code): the exchange security master, the results
    filings, then the shareholding index.  ``None`` when none holds one."""
    lookups: list[tuple[sqlite3.Connection | None, str, str, str]] = [
        (conn, "security_master", "SELECT name FROM security_master WHERE isin=? AND name IS NOT NULL AND name<>'' "
                                  "LIMIT 1", isin),
        (conn, "security_master", "SELECT name FROM security_master WHERE bse_code=? AND name IS NOT NULL "
                                  "AND name<>'' LIMIT 1", bse_code),
        (results_conn, "filings", "SELECT company FROM filings WHERE isin=? AND company IS NOT NULL AND company<>'' "
                                  "ORDER BY filing_ts DESC LIMIT 1", isin),
        (results_conn, "filings", "SELECT company FROM filings WHERE scrip_code=? AND company IS NOT NULL "
                                  "AND company<>'' ORDER BY filing_ts DESC LIMIT 1", bse_code),
        (conn, "shp_index", "SELECT name FROM shp_index WHERE isin=? AND name IS NOT NULL AND name<>'' "
                            "ORDER BY quarter_end DESC LIMIT 1", isin),
    ]
    for store, table_name, sql, value in lookups:
        if store is None or not value or not _has_table(store, table_name):
            continue
        row = store.execute(sql, (value,)).fetchone()
        if row and row[0]:
            return str(row[0]).strip()
    return None


def company_row(conn: sqlite3.Connection, key: str, table: dict,
                results_conn: sqlite3.Connection | None = None, fallback: dict | None = None) -> dict:
    """One company entry from the stores.  ``key`` is a symbol or an ISIN; everything else is joined by ISIN.

    ``fallback`` (``{"isin": ..., "bse_code": ...}`` from the universe row) is used only when ``key`` finds no
    ``master_companies`` row: master is searched by that ISIN or BSE code, and failing that the entry is
    synthesized from the fallback ids (``"master": False``).  No fallback and no master row raises ``KeyError``.
    """
    text = key.strip().upper()
    master = conn.execute("SELECT isin, nse_symbol, bse_code, company_name, industry FROM master_companies "
                          "WHERE nse_symbol=? OR isin=? LIMIT 1", (text, text)).fetchone()
    fb_isin = str((fallback or {}).get("isin") or "").strip().upper()
    fb_bse = str((fallback or {}).get("bse_code") or "").strip()
    if master is None and (fb_isin or fb_bse):
        master = conn.execute("SELECT isin, nse_symbol, bse_code, company_name, industry FROM master_companies "
                              "WHERE (isin=? AND ?<>'') OR (CAST(bse_code AS TEXT)=? AND ?<>'') "
                              "ORDER BY CASE WHEN isin=? THEN 0 ELSE 1 END LIMIT 1",
                              (fb_isin, fb_isin, fb_bse, fb_bse, fb_isin)).fetchone()
    if master is None:
        if not (fb_isin or fb_bse):
            raise KeyError(f"{key!r} is not in master_companies")
        return synthesized_row(conn, text, fb_isin, fb_bse, table, results_conn)
    symbol = master["nse_symbol"] or text
    isins = issuer_isins(conn, symbol, master["isin"], str(master["bse_code"] or ""), results_conn)
    basic, industry = label_of(conn, isins, symbol)
    family = family_of(basic, industry, table)
    if family == UNKNOWN and basic is None and industry is None:
        family = (table.get("master_industry") or {}).get(master["industry"] or "", UNKNOWN)
        if family == UNKNOWN:
            family = bse_family(conn, isins, table)
    return {"symbol": symbol, "name": master["company_name"], "bse_code": str(master["bse_code"] or ""),
            "isins": isins, "sector": family, "lender": is_lender(basic, industry, table)}


def synthesized_row(conn: sqlite3.Connection, symbol: str, isin: str, bse_code: str, table: dict,
                    results_conn: sqlite3.Connection | None = None) -> dict:
    """The entry of a company ``master_companies`` lacks (BSE-only, SME, a new listing), built from the universe
    row's ids.  The sector comes from the same taxonomy path as a master row; it is never guessed from the symbol
    text, so a company no taxonomy labels stays ``unknown``."""
    if not isin and bse_code and _has_table(conn, "security_master"):
        row = conn.execute("SELECT isin FROM security_master WHERE bse_code=? AND isin IS NOT NULL AND isin<>'' "
                           "LIMIT 1", (bse_code,)).fetchone()
        isin = str(row[0]) if row else ""
    isins = issuer_isins(conn, symbol, isin, bse_code, results_conn) if isin else []
    basic, industry = label_of(conn, isins, symbol)
    family = family_of(basic, industry, table)
    if family == UNKNOWN and basic is None and industry is None:
        family = bse_family(conn, isins, table)
    name = filed_name(conn, isins[0] if isins else "", bse_code, results_conn) or symbol
    return {"symbol": symbol, "name": name, "bse_code": bse_code, "isins": isins, "sector": family,
            "lender": is_lender(basic, industry, table), "master": False}


def cross_check(profile: dict, db: Path) -> list[dict]:
    """``lender`` disagreements between the taxonomy and the filed lines of a built pilot3 database."""
    conn = connect_ro(str(db))
    conn.row_factory = sqlite3.Row
    out = []
    for company in profile["companies"]:
        filed = filed_lender(conn, company["symbol"])
        if filed != bool(company["lender"]):
            out.append({"symbol": company["symbol"], "taxonomy": bool(company["lender"]), "filed": filed})
    return out


def mapped_share(conn: sqlite3.Connection, table: dict) -> dict:
    """Active companies by what the taxonomy can place, and the tier that placed each family:

    ``family`` (any tier), ``unknown`` (no family), ``no_label`` (no ``company_industry`` row by ISIN or symbol),
    and the family counts by tier (current ISIN, a historical ISIN, the symbol, ``master_companies.industry``,
    the BSE ``board_meetings.industry``).
    """
    out = {"active": 0, "family": 0, "unknown": 0, "no_label": 0,
           "by_current_isin": 0, "by_history_isin": 0, "by_symbol": 0, "by_master_industry": 0,
           "by_bse_industry": 0}
    rows = conn.execute("SELECT isin, nse_symbol, industry FROM master_companies WHERE is_active=1").fetchall()
    for row in rows:
        out["active"] += 1
        current, symbol = row["isin"], row["nse_symbol"]
        candidates = [current] if current else []
        basic, industry = label_of(conn, candidates)
        tier = "by_current_isin" if basic or industry else None
        if tier is None and symbol:
            history = [r[0] for r in conn.execute("SELECT DISTINCT isin FROM symbol_isin_history WHERE symbol=?",
                                                  (symbol,)) if r[0] != current]
            candidates += history
            basic, industry = label_of(conn, history)
            tier = "by_history_isin" if basic or industry else None
        if tier is None and symbol:
            basic, industry = label_of(conn, [], symbol)
            tier = "by_symbol" if basic or industry else None
        family = family_of(basic, industry, table)
        if tier is None:
            family = (table.get("master_industry") or {}).get(row["industry"] or "", UNKNOWN)
            if family != UNKNOWN:
                tier = "by_master_industry"
            else:
                family = bse_family(conn, candidates, table)
                tier = "by_bse_industry" if family != UNKNOWN else tier
        if tier is None:
            out["no_label"] += 1
        if family == UNKNOWN:
            out["unknown"] += 1
        else:
            out["family"] += 1
            if tier:
                out[tier] += 1
    return out


def make_profile(keys: list[str], name: str, root: Path, window_start: str | None, compute_start: str | None,
                 conn: sqlite3.Connection | None = None, raw_root: Path | None = None,
                 fallback: dict | None = None) -> dict:
    """The build profile of ``keys``.  ``fallback`` (``{"isin", "bse_code"}``) applies to a single key only."""
    if fallback and len(keys) != 1:
        raise ValueError("an isin/bse_code fallback needs exactly one company")
    conn = conn or connect_ro(str(main_store()))
    conn.row_factory = sqlite3.Row
    results_path = results_store()
    results_conn = connect_ro(str(results_path)) if results_path else None
    table = sector_map()
    return {"name": name, "pages_db": str(root / "pages.db"), "raw_root": str(raw_root or root / "raw"),
            "manifest": str(root / "raw" / "manifest.csv"), "out": str(root / f"{name}.db"),
            "window_start": window_start, "compute_start": compute_start,
            "companies": [company_row(conn, key, table, results_conn, fallback) for key in keys]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("companies", nargs="+", help="symbols or ISINs")
    ap.add_argument("--name", required=True)
    ap.add_argument("--root", required=True, type=Path, help="folder of the build's pages.db, raw and output")
    ap.add_argument("--raw-root", type=Path, default=None,
                    help="where the documents live, when not <root>/raw (the manifest still is <root>/raw/manifest.csv)")
    ap.add_argument("--window-start", default=None)
    ap.add_argument("--compute-start", default=None)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--check-db", type=Path, default=None,
                    help="a built pilot3 database: compare each lender flag with the company's filed lines")
    ap.add_argument("--isin", default=None,
                    help="the universe row's ISIN: used when the company is not in master_companies (one company)")
    ap.add_argument("--bse-code", default=None,
                    help="the universe row's BSE code: used when the company is not in master_companies (one company)")
    args = ap.parse_args(argv)
    fallback = {"isin": args.isin or "", "bse_code": args.bse_code or ""} if (args.isin or args.bse_code) else None
    if fallback and len(args.companies) != 1:
        ap.error("--isin/--bse-code take exactly one company")
    conn = connect_ro(str(main_store()))
    conn.row_factory = sqlite3.Row
    profile = make_profile(args.companies, args.name, args.root, args.window_start, args.compute_start, conn,
                           args.raw_root, fallback)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(profile, indent=1), encoding="utf-8")
    for company in profile["companies"]:
        basic, industry = label_of(conn, company["isins"], company["symbol"])
        note = f"  label={basic or industry or 'none'}" if company["sector"] == UNKNOWN else ""
        print(company["symbol"], company["sector"], "lender" if company["lender"] else "", len(company["isins"]),
              "ISINs" + note)
    if args.check_db:
        disagreements = cross_check(profile, args.check_db)
        print(f"lender cross-check against {args.check_db}: {len(disagreements)} disagreement(s)")
        for row in disagreements:
            print(f"  {row['symbol']}: taxonomy={'lender' if row['taxonomy'] else 'not'} "
                  f"filed={'lender' if row['filed'] else 'not'}")
    share = mapped_share(conn, sector_map())
    total = share["active"]
    print(f"active companies: {total}; family {share['family']} ({100 * share['family'] / total:.1f}%: "
          f"current ISIN {share['by_current_isin']}, history ISIN {share['by_history_isin']}, "
          f"symbol {share['by_symbol']}, master industry {share['by_master_industry']}, "
          f"BSE industry {share['by_bse_industry']}), "
          f"unknown {share['unknown']} ({100 * share['unknown'] / total:.1f}%), "
          f"no label {share['no_label']} ({100 * share['no_label'] / total:.1f}%)")


if __name__ == "__main__":
    main()
