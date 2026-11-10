"""T-088: named holders, the promoter pledge block and the percentage base of a shareholding pattern.

A synthetic SHP XBRL file carries what a real one does: holder facts under typed-member contexts (the name in a
``D_`` context, the counts in the bare one with the same member), a persons-in-concert twin, a depository-receipt
custody line that moves the printed percentage base, and the promoter encumbrance block.  ``build_shp`` must write
``shp_holder`` and ``shp_pledge`` with the same ``known_at`` as ``shp_category``; ``apply_window`` must keep the
shareholding quarters from ``compute_start`` while the other stores still stop at ``window_start``.

    python -m pytest reality_engine/tests/test_pilot3_shp_holder.py -q
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest

from reality_engine.pilot3 import profile, ratios, schema, stores

TOTAL = 1_000_000_000
CUSTODY = 100_000_000
BASE = TOTAL - CUSTODY            # promoter 360,000,000 is 40% of the base, 36% of the total
INFO_EDGE = 111_420_000           # 12.38% of the base
ESOP_TRUST = 40_000_000           # 4.44% of the base
PROMOTER = 360_000_000
PLEDGED = 90_000_000              # 25% of the promoter holding

NS = ('xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
      'xmlns:s="http://example.com/shp"')


def _cat_ctx(member: str) -> str:
    return (f'<xbrli:context id="C_{member}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
            f'</xbrli:entity><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period><xbrli:scenario>'
            f'<xbrldi:explicitMember dimension="s:CategoryOfShareholdersAxis">s:{member}Member</xbrldi:explicitMember>'
            f'</xbrli:scenario></xbrli:context>')


def _holder_ctx(cid: str, axis: str, domain: str, prefix: str = "") -> str:
    return (f'<xbrli:context id="{prefix}{cid}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
            f'</xbrli:entity><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period><xbrli:scenario>'
            f'<xbrldi:typedMember dimension="s:{axis}"><s:Domain>{domain}</s:Domain></xbrldi:typedMember>'
            f'</xbrli:scenario></xbrli:context>')


def _fact(tag: str, cid: str, value: object) -> str:
    return f'<s:{tag} contextRef="{cid}">{value}</s:{tag}>'


def _shp_xml() -> bytes:
    """One fractional-taxonomy file (percentages as fractions, as the 2025-05 taxonomy files print them)."""
    body = "".join(_cat_ctx(m) for m in ("ShareholdingOfPromoterAndPromoterGroup", "PublicShareholding",
                                         "CustodianOrDRHolder", "ShareholdingPattern"))
    body += _fact("ISIN", "C_ShareholdingPattern", "INE000A01010")
    body += _fact("Symbol", "C_ShareholdingPattern", "TESTCO")
    body += _fact("DateOfReport", "C_ShareholdingPattern", "2026-09-30")
    body += _fact("NumberOfShares", "C_ShareholdingOfPromoterAndPromoterGroup", PROMOTER)
    body += _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "C_ShareholdingOfPromoterAndPromoterGroup", 0.4)
    body += _fact("NumberOfShares", "C_PublicShareholding", BASE - PROMOTER)
    body += _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "C_PublicShareholding", 0.6)
    body += _fact("NumberOfShares", "C_CustodianOrDRHolder", CUSTODY)
    body += _fact("NumberOfShares", "C_ShareholdingPattern", TOTAL)
    body += _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "C_ShareholdingPattern", 1.0)
    body += _fact("NumberOfSharesEncumberedUnderPledged", "C_ShareholdingOfPromoterAndPromoterGroup", PLEDGED)
    body += _fact("EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares",
                  "C_ShareholdingOfPromoterAndPromoterGroup", 0.25)
    body += _fact("NumberOfSharesEncumbered", "C_ShareholdingOfPromoterAndPromoterGroup", PLEDGED)
    body += _fact("NumberOfSharesEncumberedUnderOtherEncumbrances", "C_ShareholdingOfPromoterAndPromoterGroup", 0)
    body += ('<xbrli:context id="MainI"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
             '</xbrli:entity><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>')
    for tag, value in (("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged", "true"),
                       ("WhetherAnySharesHeldByPromotersAreEncumberedUnderNonDisposalUndertaking", "false"),
                       ("WhetherAnySharesHeldByPromotersAreEncumberedOtherThanByWayOfPledgeOrNDU", "false")):
        body += _fact(tag, "MainI", value)
    # the body corporate: its name in the D_ context, its counts in the bare one (the real files split them so)
    body += _holder_ctx("BodiesCorporate_Context15", "DetailsOfSharesHeldByBodiesCorporateAxis",
                        "BodiesCorporate_Context15", prefix="D_")
    body += _holder_ctx("BodiesCorporate_Context15", "DetailsOfSharesHeldByBodiesCorporateAxis",
                        "BodiesCorporate_Context15")
    body += _fact("NameOfTheShareholder", "D_BodiesCorporate_Context15", "Info Edge (India) Limited")
    body += _fact("NumberOfShares", "BodiesCorporate_Context15", INFO_EDGE)
    body += _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "BodiesCorporate_Context15", 0.1238)
    body += _fact("NumberOfShareholders", "BodiesCorporate_Context15", 1)
    body += _holder_ctx("EmployeeBenefitsTrusts_Context15", "DetailsOfSharesHeldByEmployeeBenefitsTrustsAxis",
                        "EmployeeBenefitsTrusts_Context15", prefix="D_")
    body += _holder_ctx("EmployeeBenefitsTrusts_Context15", "DetailsOfSharesHeldByEmployeeBenefitsTrustsAxis",
                        "EmployeeBenefitsTrusts_Context15")
    body += _fact("NameOfTheShareholder", "D_EmployeeBenefitsTrusts_Context15", "Foodie Bay Employees ESOP Trust")
    body += _fact("NumberOfShares", "EmployeeBenefitsTrusts_Context15", ESOP_TRUST)
    body += _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "EmployeeBenefitsTrusts_Context15", 0.0444)
    # the same holder under the persons-in-concert disclosure: its own row, never part of a category sum
    body += _holder_ctx("PAC_Public19", "DetailsOfTheShareholdersActingAsPersonsInConcertForPublicAxis",
                        "PAC_Public19", prefix="D_")
    body += _holder_ctx("PAC_Public19", "DetailsOfTheShareholdersActingAsPersonsInConcertForPublicAxis", "PAC_Public19")
    body += _fact("NameOfTheShareholder", "D_PAC_Public19", "Info Edge (India) Limited")
    body += _fact("NameOfThePAC", "D_PAC_Public19", "Naukri Internet Services Limited")
    body += _fact("NumberOfShares", "PAC_Public19", INFO_EDGE)
    body += _fact("PercentageOfShareholdingByPAC", "PAC_Public19", 0.1238)
    return f"<xbrli:xbrl {NS}>{body}</xbrli:xbrl>".encode()


def test_the_parse_reads_holders_the_pledge_block_and_the_percentage_base():
    parsed = stores.parse_shp_xbrl(_shp_xml())
    assert stores._quarter(parsed) == "2026-09-30"
    assert parsed["head"]["ISIN"] == "INE000A01010"
    # INFY 2026-09-30 in miniature: the printed percentages are on the shares outside depository-receipt custody
    base, label = stores._pct_base(parsed)
    assert base == pytest.approx(BASE) and label == "total_excluding_dr_custody"
    by_axis = {axis: f for (axis, _domain), f in parsed["holders"].items()}
    body = by_axis["DetailsOfSharesHeldByBodiesCorporateAxis"]
    assert body["NameOfTheShareholder"] == "Info Edge (India) Limited"
    assert body["NumberOfShares"] == INFO_EDGE
    assert body["ShareholdingAsAPercentageOfTotalNumberOfShares"] == pytest.approx(12.38)   # fraction -> percent
    pac = by_axis["DetailsOfTheShareholdersActingAsPersonsInConcertForPublicAxis"]
    assert pac["NameOfThePAC"] == "Naukri Internet Services Limited"
    assert pac["PercentageOfShareholdingByPAC"] == pytest.approx(12.38)
    assert stores._holder_category("DetailsOfSharesHeldByBodiesCorporateAxis") == "bodies_corporate"
    assert stores._holder_category("DetailsOfTheShareholdersActingAsPersonsInConcertForPublicAxis") == "pac_public"
    assert stores._holder_category("SignificantBeneficialOwnersAxis") is None
    assert parsed["pledge"]["WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged"] == "true"


def test_build_shp_writes_one_holder_row_per_name_and_the_pledge_block(monkeypatch):
    folder = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / f"pilot3_shp_holder_{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    try:
        with gzip.open(folder / "SHP_0001_01102026100000_WEB.xml.gz", "wb") as fh:
            fh.write(_shp_xml())
        index = [{"file": "SHP_0001_01102026100000_WEB.xml", "isin": "INE000A01010", "quarter_end": "2026-09-30",
                  "promoter_pct": 36.0, "public_pct": 54.0, "record_id": "1", "revised": None,
                  "broadcast_at": "2026-10-01T10:00:00", "submission_date": "2026-09-30"}]
        monkeypatch.setattr(stores, "SHP_XBRL", folder)
        monkeypatch.setattr(stores, "fetch", lambda symbol, table: index if table == "shp_index" else [])
        monkeypatch.setattr(stores, "all_isins", lambda symbol: ("INE000A01010",))
        conn = sqlite3.connect(":memory:")
        schema.create(conn, list(schema.TABLES))
        stores.build_shp(conn)
        # the index says 36% of the total, the file itself prints 40% of the base: both kept, with the base named
        pct = {(r[0], r[1]): r[2] for r in conn.execute(
            "SELECT category, source_kind, pct FROM shp_category WHERE symbol='KEC'")}
        assert pct[("promoter", "index")] == pytest.approx(36.0)
        assert pct[("promoter", "xbrl")] == pytest.approx(40.0)
        assert conn.execute("SELECT DISTINCT pct_base_shares, pct_basis FROM shp_category WHERE symbol='KEC'"
                            ).fetchall() == [(BASE, "total_excluding_dr_custody")]
        holders = conn.execute("SELECT category, holder_name, shares, pct, pac_name, pledged_shares, known_at "
                               "FROM shp_holder WHERE symbol='KEC' ORDER BY category").fetchall()
        assert holders == [
            ("bodies_corporate", "Info Edge (India) Limited", INFO_EDGE, 12.38, None, None, "2026-10-01T10:00:00"),
            ("employee_benefits_trusts", "Foodie Bay Employees ESOP Trust", ESOP_TRUST, 4.44, None, None,
             "2026-10-01T10:00:00"),
            ("pac_public", "Info Edge (India) Limited", INFO_EDGE, 12.38, "Naukri Internet Services Limited", None,
             "2026-10-01T10:00:00")]
        # the PAC twin never enters a category sum
        assert conn.execute("SELECT SUM(shares) FROM shp_holder WHERE symbol='KEC' AND category NOT LIKE 'pac_%'"
                            ).fetchone()[0] == INFO_EDGE + ESOP_TRUST
        assert conn.execute("SELECT quarter_end, pledge_flag, ndu_flag, other_flag, promoter_shares, pledged_shares, "
                            "pledged_pct, known_at FROM shp_pledge WHERE symbol='KEC'").fetchall() == [
            ("2026-09-30", 1, 0, 0, PROMOTER, PLEDGED, 25.0, "2026-10-01T10:00:00")]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _profile(folder: Path) -> Path:
    data = {"name": "shp-window", "pages_db": str(folder / "pages.db"), "raw_root": str(folder / "raw"),
            "manifest": str(folder / "manifest.csv"), "out": str(folder / "pilot.db"),
            "window_start": "2025-10-01", "compute_start": "2024-07-01",
            "companies": [{"symbol": "TESTCO", "name": "Test Co", "bse_code": "1", "isins": ["INE000A01010"],
                           "sector": "x", "lender": False}]}
    path = folder / "profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_window_keeps_shareholding_quarters_from_compute_start():
    folder = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / f"pilot3_shp_window_{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    conn = sqlite3.connect(":memory:")
    try:
        profile.activate(profile.load(_profile(folder)))
        schema.create(conn, list(schema.TABLES))
        for end in ("2025-09-30", "2025-12-31"):
            conn.execute("INSERT INTO shp_category VALUES (" + ",".join("?" * 20) + ")",
                         ("TESTCO", "INE000A01010", end, "promoter", "Promoter", 1e8, 40.0, 1, "pct", "xbrl",
                          "shp.xml", "db", "t", "1", None, "2025-11-01T10:00:00", "x", 1, BASE, "total_shares"))
            conn.execute("INSERT INTO shp_holder VALUES (" + ",".join("?" * 16) + ")",
                         ("TESTCO", "INE000A01010", end, "bodies_corporate", "A Holder", 1e7, 10.0, 1, None, None,
                          None, "shp.xml", "db", "xml.gz", "2025-11-01T10:00:00", "x"))
            conn.execute("INSERT INTO shp_pledge VALUES (" + ",".join("?" * 14) + ")",
                         ("TESTCO", "INE000A01010", end, 0, 0, 0, 1e8, 0.0, 0.0, 0.0, 0.0, "shp.xml",
                          "2025-11-01T10:00:00", "x"))
            conn.execute("INSERT INTO fin_quarter_xbrl (symbol, isin, period_start, period_end, fiscal_period, basis, "
                         "audited, statement, line_item, xbrl_tag, value, unit, scale, source_file, source_db, "
                         "source_table, source_rowid, known_at, known_at_source, is_reported) "
                         "VALUES (" + ",".join("?" * 20) + ")",
                         ("TESTCO", "INE000A01010", "2025-07-01", end, "Q2FY26", "consolidated", "a", "PL", "pat",
                          "Tag", 1.5e9, "inr", 1.0, "q.xml", "results_xbrl.db", "quarterly", "q.xml",
                          "2025-11-01T10:00:00", "x", 1))
        deleted = stores.apply_window(conn)
        assert deleted["fin_quarter_xbrl"] == 1                     # a store outside the shareholding tables: unchanged
        assert deleted["shp_category"] == deleted["shp_holder"] == deleted["shp_pledge"] == 0
        assert [r[0] for r in conn.execute("SELECT quarter_end FROM shp_category ORDER BY 1")] == \
            ["2025-09-30", "2025-12-31"]
        # what ratios.py reads for a later quarter is still the latest pattern count, not the added older one
        conn.executemany("INSERT INTO share_capital VALUES ('TESTCO','INE000A01010',?,'consolidated',NULL,NULL,?,"
                         "NULL,NULL,'shares',1.0,'2025-11-01','x','d','shp_category','r',NULL,NULL)",
                         [("2025-09-30", 9e7), ("2025-12-31", 1e8)])
        assert ratios._share_count(conn, "TESTCO", "consolidated", "2026-03-31") == \
            (1e8, "2025-11-01", "shp_category")
    finally:
        conn.close()
        profile.activate(None)
        shutil.rmtree(folder, ignore_errors=True)


def test_build_shp_warns_when_the_xbrl_folder_is_empty(tmp_path, monkeypatch, capsys):
    """8 Nov: raw SHP files moved to Drive left the folder empty and pledge/holder tables silently empty."""
    import sqlite3 as _sq
    from reality_engine.pilot3 import stores as _st
    monkeypatch.setattr(_st, "SHP_XBRL", tmp_path)
    monkeypatch.setattr(_st.profile, "symbols", lambda: ())
    _st.build_shp(_sq.connect(":memory:"))
    assert "no SHP XBRL files" in capsys.readouterr().err


def test_shp_known_at_takes_the_earlier_pm_safe_file_stamp():
    """T-162: a re-broadcast index time never hides a filing already public; the 12-hour stamp is read as PM."""
    from reality_engine.pilot3.stores import _shp_known
    # ADANIPORTS 2021-09-30: filed 20 Oct 2021 09:40 (stamp), index broadcast 7 Jan 2022 -> the stamp, read 21:40
    assert _shp_known("SHP_162947_542024_20102021094050_WEB.xml", "2022-01-07T01:55:01") == (
        "2021-10-20T21:40:50", "file name timestamp (pm-safe)")
    # 06:45 in the name, 18:45 broadcast: PM reading equals the broadcast, keep the broadcast
    assert _shp_known("SHP_1481231_11072025064527_WEB.xml", "2025-07-11T18:45:32")[1] == "shp_index.broadcast_at"
    # 10:36 AM stamp and broadcast: the PM reading is later, keep the broadcast (never earlier than certain)
    assert _shp_known("SHP_182563_961791_20102023103636_WEB.xml", "2023-10-20T10:36:37") == (
        "2023-10-20T10:36:37", "shp_index.broadcast_at")
    # stamp later than the broadcast: keep the broadcast; no stamp: keep the broadcast
    assert _shp_known("SHP_1490050_22072025114302_WEB.xml", "2025-07-09T15:49:24")[0] == "2025-07-09T15:49:24"
    assert _shp_known("other.xml", "2025-07-09T15:49:24") == ("2025-07-09T15:49:24", "shp_index.broadcast_at")
    # no index row: the PM-safe stamp alone
    assert _shp_known("SHP_1_2_08102020101735_WEB.xml", None) == ("2020-10-08T22:17:35", "file name timestamp (pm-safe)")
