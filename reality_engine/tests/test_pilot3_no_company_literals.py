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
from reality_engine.pilot3.make_profile import (UNKNOWN, company_row, family_of, is_lender, main_store, mapped_share,
                                                results_store, same_issuer, sector_map)
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
    held = {row[0] for row in conn.execute("SELECT nse_symbol FROM master_companies WHERE nse_symbol IS NOT NULL")}
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

    root = Path(__file__).resolve().parents[2] / ".tmp" / f"manifest_match_{uuid.uuid4().hex[:8]}"
    try:
        for name in ("abbott_transcripts", "kec_transcripts", "maruti_notes"):
            (root / name).mkdir(parents=True)
        (root / "abbott_transcripts" / "_manifest.json").write_text("{}", encoding="utf-8")
        (root / "kec_transcripts" / "_known_at.json").write_text("{}", encoding="utf-8")
        assert _company_manifest(root, "ABB") is None
        assert _company_manifest(root, "KEC") == root / "kec_transcripts"
        assert _company_manifest(root, "MARUTI") is None, "a folder with no manifest is not a manifest folder"
    finally:
        shutil.rmtree(root, ignore_errors=True)
