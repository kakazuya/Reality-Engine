"""T-209: the structured universe store -- SHP categories, pledge and balance-sheet lines.

Two hand-written SHP XBRL files (fractional taxonomy: one with a numeric pledge, one that
states no pledge) and one results fixture database cover the row contract; the last test is
the known answer for Blue Star 2024-06-30 re-read from the real raw file (skipped when the
raw cache is absent).  The expected Blue Star numbers are the ``shp_index`` promoter/public
columns for that filing, which the pilot store's cross-check found equal to the XBRL.

    python -m pytest reality_engine/tests/test_structured_universe.py reality_engine/tests/test_pilot3_shp_holder.py -q
"""
from __future__ import annotations

import gzip
import os
import sqlite3
import uuid
from pathlib import Path

import pytest

from reality_engine.structured import universe_build as ub

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".tmp" / f"t209_{os.getpid()}_{uuid.uuid4().hex[:6]}"
BLUE_STAR = Path(r"D:\RealityEngine\raw\nse_shp_xbrl_pilot\SHP_189892_1190288_17072024071055_WEB.xml.gz")

NS = ('xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
      'xmlns:in-bse-shp="http://example.com/shp"')
TOTAL = 1_000.0
PROMOTER = 500.0
PLEDGED = 125.0          # 25 % of the promoter holding, 12.5 % of total


def _ctx(member: str) -> str:
    return (f'<xbrli:context id="C_{member}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
            f'</xbrli:entity><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period>'
            f'<xbrli:scenario><xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
            f'in-bse-shp:{member}Member</xbrldi:explicitMember></xbrli:scenario></xbrli:context>')


def _fact(tag: str, cid: str, value: object) -> str:
    return f'<in-bse-shp:{tag} contextRef="{cid}">{value}</in-bse-shp:{tag}>'


def _shp_xml(pledge: bool) -> bytes:
    """A fractional-taxonomy filing: every category divides the promoter/public 100 %."""
    rows = (("ShareholdingOfPromoterAndPromoterGroup", PROMOTER, 0.5),
            ("PublicShareholding", TOTAL - PROMOTER, 0.5),
            ("InstitutionsDomestic", 300.0, 0.3),
            ("MutualFundsOrUti", 100.0, 0.1),
            ("InsuranceCompanies", 50.0, 0.05),
            ("InstitutionsForeign", 200.0, 0.2),
            ("Governments", 0.0, 0.0),
            ("ShareholdingPattern", TOTAL, 1.0))
    body = "".join(_ctx(m) for m, _s, _p in rows)
    body += _fact("ISIN", "C_ShareholdingPattern", "INE000A01010")
    body += _fact("Symbol", "C_ShareholdingPattern", "TESTCO")
    body += _fact("DateOfReport", "C_ShareholdingPattern", "2026-09-30")
    for member, shares, pct in rows:
        body += _fact("NumberOfShares", f"C_{member}", shares)
        body += _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", f"C_{member}", pct)
    body += ('<xbrli:context id="MainI"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
             '</xbrli:entity><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period>'
             '</xbrli:context>')
    body += _fact("WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged",
                  "MainI", "true" if pledge else "false")
    body += _fact("WhetherAnySharesHeldByPromotersAreEncumberedUnderNonDisposalUndertaking",
                  "MainI", "false")
    body += _fact("WhetherAnySharesHeldByPromotersAreEncumberedOtherThanByWayOfPledgeOrNDU",
                  "MainI", "false")
    body += _fact("PledgedOrEncumberedNumberOfShares",
                  "C_ShareholdingOfPromoterAndPromoterGroup", PLEDGED if pledge else 0.0)
    body += _fact("PledgedOrEncumberedSharesHeldAsPercentageOfTotalNumberOfShares",
                  "C_ShareholdingOfPromoterAndPromoterGroup", 0.25 if pledge else 0.0)
    return f"<xbrli:xbrl {NS}>{body}</xbrli:xbrl>".encode()


def _record(rid: str, file: str, known_at: str, revised: str = "N",
            quarter: str = "2026-09-30") -> dict:
    return {"record_id": rid, "symbol": "TESTCO", "isin": "INE000A01010",
            "filing_isin": "INE000A01010", "period_end": quarter,
            "quarter_end": quarter, "known_at": known_at,
            "known_at_source": "shp_index.broadcast_at", "revised": revised, "file": file}


def _store(name: str) -> sqlite3.Connection:
    WORK.mkdir(parents=True, exist_ok=True)
    return ub.open_store(WORK / f"{name}.db")


def _stage(con: sqlite3.Connection, raw: Path, files: dict[str, bytes]) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (raw / f"{name}.gz").write_bytes(gzip.compress(body))
    for rid, name in (("1", "pledge.xml"), ("2", "no_pledge.xml")):
        con.execute(
            "INSERT INTO filing(record_id, symbol, isin, filing_isin, period_end, known_at,"
            " known_at_source, revised, file) VALUES (?,?,?,?,?,?,?,?,?)",
            (rid, "TESTCO", "INE000A01010", "INE000A01010", "2026-09-30",
             f"2026-10-0{rid}T10:00:00", "shp_index.broadcast_at", "N", name))


def test_shp_rows_read_every_category_and_derive_other_dii():
    parsed = ub.pilot_stores.parse_shp_xbrl(_shp_xml(pledge=True))
    rows, pledge = ub._shp_rows(parsed, _record("1", "pledge.xml", "2026-10-01T10:00:00"))
    cats = {r[5]: r for r in rows}
    assert set(cats) == {"promoter", "public", "fpi_total", "mf", "insurance", "other_dii",
                         "government"}
    assert cats["promoter"][7] == pytest.approx(PROMOTER)
    assert cats["promoter"][8] == pytest.approx(50.0)
    assert cats["fpi_total"][8] == pytest.approx(20.0)
    assert cats["mf"][8] == pytest.approx(10.0)
    assert cats["insurance"][8] == pytest.approx(5.0)
    assert cats["other_dii"][7] == pytest.approx(150.0)       # 300 - 100 - 50 shares
    assert cats["other_dii"][8] == pytest.approx(15.0)
    assert cats["other_dii"][12] == 0                          # derived, is_reported=0
    assert cats["government"][8] == pytest.approx(0.0)
    assert cats["promoter"][9] == pytest.approx(TOTAL)          # percentage base is stored
    assert pledge is not None and pledge[9] == pytest.approx(PLEDGED)
    assert pledge[10] == pytest.approx(25.0)
    assert pledge[11] == "of_promoter_holding"
    assert pledge[5] == 1                                      # pledge flag true


def test_no_pledge_is_reported_zero_not_missing():
    parsed = ub.pilot_stores.parse_shp_xbrl(_shp_xml(pledge=False))
    _rows, pledge = ub._shp_rows(parsed, _record("2", "no_pledge.xml", "2026-10-02T10:00:00"))
    assert pledge is not None
    assert pledge[5] == 0
    assert pledge[9] == 0.0 and pledge[10] == 0.0
    assert pledge[11] == "zero_ambiguous"                      # zero fits both bases: not guessed


def test_parse_is_idempotent_and_a_revision_keeps_its_own_known_at():
    con = _store("parse")
    raw = WORK / "raw"
    _stage(con, raw, {"pledge.xml": _shp_xml(True), "no_pledge.xml": _shp_xml(False)})
    first = ub.parse(con, raw_dir=raw, canon={})
    counts = (con.execute("SELECT COUNT(*) FROM shp_category").fetchone()[0],
              con.execute("SELECT COUNT(*) FROM shp_pledge").fetchone()[0])
    second = ub.parse(con, raw_dir=raw, canon={})               # already parsed: no work
    assert first == {"ok": 2} and second == {}
    assert counts == (14, 2)                                   # 7 categories per filing
    con.execute(
        "INSERT INTO filing(record_id, symbol, isin, filing_isin, period_end, known_at,"
        " known_at_source, revised, file) VALUES ('3',?,?,?,?,?,?,?,?)",
        ("TESTCO", "INE000A01010", "INE000A01010", "2026-09-30", "2026-10-09T10:00:00",
         "shp_index.broadcast_at", "Revised", "pledge.xml"))
    assert ub.parse(con, raw_dir=raw, canon={}) == {"ok": 1}
    by_known = con.execute(
        "SELECT known_at, COUNT(*) FROM shp_category WHERE category='promoter' "
        "GROUP BY known_at ORDER BY known_at").fetchall()
    assert [k for k, _n in by_known] == ["2026-10-01T10:00:00", "2026-10-02T10:00:00",
                                         "2026-10-09T10:00:00"]


def _results_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE filings(file TEXT, isin TEXT, symbol TEXT, period_end TEXT,
            consolidated TEXT, broadcast_ts TEXT, dissem_ts TEXT, filing_ts TEXT, status TEXT);
        CREATE TABLE facts(file TEXT, concept TEXT, context TEXT, period_start TEXT,
            period_end TEXT, instant TEXT, value REAL, unit TEXT, decimals TEXT);
        CREATE TABLE filings_isin(file TEXT, isin_filed TEXT, isin TEXT, method TEXT,
            same_issuer INTEGER, as_of TEXT, resolved_at TEXT);
    """)
    con.executemany(
        "INSERT INTO filings VALUES (?,?,?,?,?,?,?,?,?)",
        [("F1.xml", "INEOLD01011", "TESTCO", "2026-09-30", "Consolidated",
          "2026-10-20T18:00:00", None, None, "ok"),
         ("F2.xml", "INE000A01010", "TESTCO", "2026-03-31", "Standalone",
          None, "2026-05-01T09:00:00", "2026-05-01T09:00:00", "ok")])
    con.executemany(
        "INSERT INTO filings_isin VALUES (?,?,?,?,?,?,?)",
        [("F1.xml", "INEOLD01011", "INENEW01012", "symbol_isin_history", 1,
          "2026-10-20", "2026-10-20"),
         ("F2.xml", "INE000A01010", "INE000A01010", "direct", 1, "2026-05-01", "2026-05-01")])
    facts = []
    for concept, value in (("Equity", 1000.0), ("Assets", 1800.0),
                           ("LongTermBorrowings", 300.0), ("ShortTermBorrowings", 200.0),
                           ("CashAndCashEquivalents", 100.0)):
        facts.append(("F1.xml", concept, "OneI", None, None, "2026-09-30", value))
    # a comparative instant in the same file must never leak into the 2026-09-30 figures
    facts.append(("F1.xml", "Equity", "PriorI", None, None, "2025-09-30", 900.0))
    for concept, value in (("ShareholdersFunds", 500.0), ("MinorityInterest", 20.0),
                           ("EquityAndLiabilities", 800.0), ("CashAndCashEquivalents", 50.0)):
        facts.append(("F2.xml", concept, "OneI", None, None, "2026-03-31", value))
    con.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?)",
                    [(f, c, x, p0, p1, inst, v, "INR", None) for f, c, x, p0, p1, inst, v in facts])
    con.commit()
    con.close()
    return path


def test_balance_sheet_lines_and_derived_capital_employed():
    con = _store("balance")
    results = _results_db(WORK / "results.db")
    counts = ub.balance_sheet(con, results_db=results)
    assert counts["filings"] == 2 and counts["with_balance_sheet"] == 2
    got = {line: (value, tag, reported, known) for line, value, tag, reported, known in con.execute(
        "SELECT line_item, value, xbrl_tag, is_reported, known_at_source FROM balance_sheet"
        " WHERE source_file='F1.xml'")}
    assert got["total_equity"][0] == pytest.approx(1000.0)      # Equity, not the comparative 900
    assert got["total_assets"][0] == pytest.approx(1800.0)
    assert got["borrowings_noncurrent"][0] == pytest.approx(300.0)
    assert got["borrowings_current"][0] == pytest.approx(200.0)
    assert got["cash_and_cash_equivalents"][0] == pytest.approx(100.0)
    assert got["capital_employed"][0] == pytest.approx(1400.0)  # 1000 + 500 - 100
    assert got["capital_employed"][1] == "derived" and got["capital_employed"][2] == 0
    assert got["total_equity"][3] == "filings.broadcast_ts"
    isin, basis = con.execute(
        "SELECT isin, basis FROM balance_sheet WHERE source_file='F1.xml' LIMIT 1").fetchone()
    assert isin == "INENEW01012" and basis == "consolidated"    # follows the ISIN change
    f2 = dict(con.execute(
        "SELECT line_item, value FROM balance_sheet WHERE source_file='F2.xml'"))
    assert f2["total_equity"] == pytest.approx(520.0)            # funds + minority interest
    assert f2["total_assets"] == pytest.approx(800.0)            # EquityAndLiabilities
    assert "capital_employed" not in f2                          # no borrowings: not derived
    n_filings, n_bs = con.execute(
        "SELECT COUNT(*), SUM(has_balance_sheet) FROM bs_filing").fetchone()
    assert (n_filings, n_bs) == (2, 2)


def test_known_answer_blue_star_2024_06_30():
    if not BLUE_STAR.exists():
        pytest.skip(f"no raw SHP cache at {BLUE_STAR}")
    parsed = ub.pilot_stores.parse_shp_xbrl(gzip.decompress(BLUE_STAR.read_bytes()))
    quarter = ub.pilot_stores._quarter(parsed)
    assert quarter == "2024-06-30"
    rows, pledge = ub._shp_rows(parsed, _record("1", BLUE_STAR.name[:-3], "2024-07-17T19:10:57",
                                                quarter=quarter))
    cats = {r[5]: r for r in rows}
    assert cats["promoter"][7] == pytest.approx(75_088_874.0)
    assert cats["promoter"][8] == pytest.approx(36.52)          # shp_index promoter_pct
    assert cats["public"][8] == pytest.approx(63.48)            # shp_index public_pct
    assert cats["fpi_total"][8] == pytest.approx(17.05)
    assert cats["mf"][8] == pytest.approx(21.60)
    assert cats["insurance"][8] == pytest.approx(1.57)
    assert cats["other_dii"][8] == pytest.approx(0.40)
    assert cats["government"][8] == pytest.approx(0.0)
    assert cats["promoter"][9] == pytest.approx(205_614_788.0)
    assert pledge is not None and pledge[9] == 0.0 and pledge[11] == "zero_ambiguous"
