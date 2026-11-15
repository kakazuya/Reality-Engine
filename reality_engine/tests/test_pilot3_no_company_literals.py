"""T-094: no company symbol as a string in build or tool code, plus the generated profile.

Comments and docstrings are skipped: a real example belongs there.  ``OFFENDERS`` lists what is left and only ever
shrinks: a new literal fails, and so does a name still listed after its literal has gone.  T-094 ends with it empty.
"""
from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path

import pytest

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot3.make_profile import (UNKNOWN, bse_family, company_row, family_of, is_lender, main_store,
                                                mapped_share, results_store, same_issuer, sector_map)
from reality_engine.pilot3.scale_report import parts_from_log, report

ROOT = Path(__file__).resolve().parents[2]
SCANNED = (*sorted((ROOT / "reality_engine" / "pilot3").glob("*.py")),
           ROOT / "plugins" / "reality-data" / "server" / "lookups_pilot3.py",
           ROOT / "plugins" / "reality-data" / "server" / "server.py",
           ROOT / "plugins" / "reality-data" / "server" / "catalog.py")

OFFENDERS: set[tuple[str, str]] = set()


NOT_COMPANIES = {"BSE", "NSE", "TOTAL"}     # also listed symbols, but in code they mean the exchange or a table row


def _symbols() -> set[str]:
    conn = connect_ro(str(main_store()))
    rows = conn.execute("SELECT nse_symbol FROM master_companies WHERE nse_symbol IS NOT NULL") or []
    held = {row[0] for row in rows if row}
    return held - NOT_COMPANIES


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                out.add(id(body[0].value))
    return out


def found_literals(symbols: set[str]) -> set[tuple[str, str]]:
    """(file, symbol) for each string constant that is exactly a company symbol, in code outside docstrings."""
    out = set()
    for path in SCANNED:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip \
                    and node.value in symbols and len(node.value) >= 3 and node.value.isupper():
                out.add((path.name, node.value))
    return out


def test_no_new_literal_and_the_list_is_honest():
    found = found_literals(_symbols())
    assert found - OFFENDERS == set(), "new company literal in code"
    assert OFFENDERS - found == set(), "gone from the code: remove it from OFFENDERS"


def test_family_comes_from_the_taxonomy_and_unknown_is_never_a_guess():
    table = sector_map()
    assert family_of("Private Sector Bank", "Banks", table) == "bank"
    assert family_of("Something New", "Banks", table) == "bank"
    assert family_of("Something New", "Also New", table) == UNKNOWN
    assert family_of(None, None, table) == UNKNOWN


def test_sector_map_maps_only_the_unambiguous_industries_and_the_rest_stay_unknown():
    """T-214: an industry that fits one family cleanly maps to it; one no family fits stays an honest `unknown`
    (a wrong sector would verify wrong rows, so a guess is worse than the gap)."""
    table = sector_map()
    assert family_of("Software Products", "IT - Software", table) == "it_services"
    assert family_of("Explosives", "Chemicals & Petrochemicals", table) == "paints_chemicals"
    assert family_of("Investment Company", "Finance", table) == "nbfc"
    assert family_of("Plastic Products - Consumer", "Consumer Durables", table) == "consumer_durables"
    for basic, industry in (("Sugar", "Agricultural Food & other Products"),
                            ("Packaging", "Industrial Products"),
                            ("Paper & Paper Products", "Paper Forest & Jute Products"),
                            ("LPG/CNG/PNG/LNG Supplier", "Gas"),
                            ("Lubricants", "Petroleum Products"),
                            ("Oil Equipment & Services", "Oil"),
                            ("Diversified Commercial Services", "Commercial Services & Supplies"),
                            ("Film Production Distribution & Exhibition", "Entertainment")):
        assert family_of(basic, industry, table) == UNKNOWN, basic


def _taxonomy_db(industry: str | None, board: tuple[str, ...] = ()) -> sqlite3.Connection:
    """A company with no `company_industry` row, one master industry and the BSE values `board`."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE master_companies (isin TEXT, nse_symbol TEXT, bse_code TEXT, company_name TEXT, industry TEXT);
        CREATE TABLE company_industry (isin TEXT, symbol TEXT, basic_industry TEXT, industry TEXT);
        CREATE TABLE board_meetings (isin TEXT, symbol TEXT, industry TEXT);
        CREATE TABLE symbol_isin_history (symbol TEXT, isin TEXT, first_date TEXT);
        CREATE TABLE isin_rekey_log (symbol TEXT, old_isin TEXT, new_isin TEXT);
        CREATE TABLE corporate_documents (symbol TEXT, isin TEXT);
        CREATE TABLE shp_index (symbol TEXT, isin TEXT);
    """)
    conn.execute("INSERT INTO master_companies VALUES ('INE000000001', 'NOINDUSTRY', '500000', 'No Industry Ltd', ?)",
                 (industry,))
    for value in board:
        conn.execute("INSERT INTO board_meetings VALUES ('INE000000001', 'NOINDUSTRY', ?)", (value,))
    return conn


def test_sector_falls_back_to_the_bse_industry_last_and_only_a_single_value():
    """T-214: with no company_industry row, master_companies.industry comes first, then the BSE industry on
    board_meetings; two BSE values or an unmapped name never pick a family."""
    table = sector_map()
    conn = _taxonomy_db("General Diversified", ("Construction",))
    assert company_row(conn, "NOINDUSTRY", table)["sector"] == "epc_capital_goods"
    conn = _taxonomy_db("General Diversified", ("Construction", "Packaging"))
    assert company_row(conn, "NOINDUSTRY", table)["sector"] == UNKNOWN       # two values: never pick one
    conn = _taxonomy_db("General Diversified", ("Packaging",))
    assert company_row(conn, "NOINDUSTRY", table)["sector"] == UNKNOWN       # a name no family fits
    conn = _taxonomy_db("Information Technology", ("Packaging",))
    assert company_row(conn, "NOINDUSTRY", table)["sector"] == "it_services"  # the master tier comes first
    assert bse_family(conn, ["INE000000001"], table) == UNKNOWN
    conn.close()


def test_profile_row_from_the_stores():
    conn = connect_ro(str(main_store()))
    conn.row_factory = sqlite3.Row
    row = company_row(conn, "BAJFINANCE", sector_map())
    assert row["bse_code"] == "500034" and row["sector"] == "nbfc" and row["lender"] is True
    assert {"INE296A01024", "INE296A01032"} <= set(row["isins"])
    with pytest.raises(KeyError):
        company_row(conn, "NOSUCHCOMPANY", sector_map())


def test_generated_profile_keeps_every_held_isin_and_no_other_issuer():
    """Every ISIN the hand profile lists (added for the store filters, T-073) is found from the data, and an ISIN
    of another issuer never enters: the same-issuer check is the guard."""
    hand = json.loads((ROOT / "tasks" / "night_loop" / "pilot10_profile.json").read_text(encoding="utf-8"))
    conn = connect_ro(str(main_store()))
    conn.row_factory = sqlite3.Row
    results = results_store()
    results_conn = connect_ro(str(results)) if results else None
    table = sector_map()
    for company in hand["companies"]:
        row = company_row(conn, company["symbol"], table, results_conn)
        assert set(company["isins"]) <= set(row["isins"]), company["symbol"]
        assert all(isin == row["isins"][0] or same_issuer(isin, row["isins"][0])
                   for isin in row["isins"]), company["symbol"]


def test_lender_is_the_taxonomy_and_the_mapped_share_is_reported():
    """The lender flag is the taxonomy's own list, even with no lexicon family (a general insurer); the mapping
    report names the three groups of active companies rather than leaving the uncovered ones silent."""
    table = sector_map()
    assert is_lender("Private Sector Bank", "Banks", table)
    assert is_lender("Housing Finance Company", "Finance", table)
    assert is_lender("General Insurance", "Insurance", table)
    assert not is_lender("Cement & Cement Products", "Cement & Cement Products", table)
    conn = connect_ro(str(main_store()))
    conn.row_factory = sqlite3.Row
    share = mapped_share(conn, table)
    assert share["active"] == share["family"] + share["unknown"] and share["active"] > 0
    assert share["family"] and share["no_label"]
    assert share["by_bse_industry"] >= 0


def test_scale_report_separates_a_fixed_cost():
    seconds = parts_from_log('{"seconds_stores": 65.5}\n{"seconds_guidance": 0.6, "seconds_stores": 10.0}')
    assert seconds == {"stores": 75.5, "guidance": 0.6}
    text = report({"stores": 65.0}, companies=2, db_mb=8.4, pages_mb=0.0, universe=100, fixed={"stores": 60.0})
    assert "| stores | 65.0 | 60.0 | 2.50 |" in text


def test_a_company_manifest_folder_is_never_another_companys():
    """ABB must not read ``abbott_transcripts``: exact name or ``<symbol>_`` only."""
    import shutil
    import uuid

    from reality_engine.pilot3.docs_collect import _company_manifest
    from reality_engine.raw_store import RawStore

    root = Path(__file__).resolve().parents[2] / ".tmp" / f"manifest_match_{uuid.uuid4().hex[:8]}"
    store = RawStore(root / "_no_manifest.db", {"raw": root})     # local folders only, no Drive manifest
    try:
        for name in ("abbott_transcripts", "kec_transcripts", "maruti_notes"):
            (root / name).mkdir(parents=True)
        (root / "abbott_transcripts" / "_manifest.json").write_text("{}", encoding="utf-8")
        (root / "kec_transcripts" / "_known_at.json").write_text("{}", encoding="utf-8")
        assert _company_manifest(root, "ABB", store) is None
        assert _company_manifest(root, "KEC", store) == root / "kec_transcripts"
        assert _company_manifest(root, "MARUTI", store) is None, "a folder with no manifest is not a manifest folder"
    finally:
        shutil.rmtree(root, ignore_errors=True)
