"""Fixture tests for the pilot-60 shareholding XBRL fetch/parse (2026-10-31).

``fixtures/shp_xbrl/`` holds hand-written copies of the shareholding XBRL shape the live
filings use: the 100% ``ShareholdingPattern`` row that sets the scale, one summary context
per holder class, and both conventions in the wild (percentages in current filings,
fractions in older ones).  They cover the acceptance cases: a class reported as zero, a
class the filing does not report at all, a revised filing, and a pledge stated only as a
boolean.

The work directory is under ``.tmp`` (the sandbox cannot open ``tempfile.mkdtemp``'s DACL
with sqlite), the same convention ``test_v4_fact_view.py`` uses.

The last test is the pilot seed check: 20 rows of the real run, re-read from the raw
files with the independent ElementTree reader in
:mod:`reality_engine.scripts.verify_shp_xbrl_seed`.  It skips when the raw folder is
absent, so a fresh checkout still passes on the fixtures alone.
"""
from __future__ import annotations

import gzip
import os
import shutil
from pathlib import Path

import pytest

from reality_engine.scripts import fetch_shp_xbrl_pilot as fx
from reality_engine.scripts.verify_shp_xbrl_seed import verify

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures" / "shp_xbrl"
RAW = Path(os.environ.get("SHP_XBRL_RAW") or ROOT / ".tmp" / "shp_xbrl_raw")
SEED = FIX / "seed20.json"
ISIN_A = "INE000A01001"
#: the atoms one fully-reported filing writes (fii, dii, mf, insurance, pledge)
ATOMS_PER_FILING = 5


def _text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _filing(rid: str, name: str, period_end: str, known_at: str, isin: str = ISIN_A,
            revised: str = "N", promoter: float | None = None,
            public: float | None = None) -> dict:
    return {"record_id": rid, "isin": isin, "symbol": "TESTCO", "filing_isin": isin,
            "period_end": period_end, "known_at": known_at, "revised": revised,
            "file": name, "url": "http://nsearchives.example/" + name,
            "promoter_pct": promoter, "public_pct": public}


def _open(monkeypatch, name: str, rows: list[dict]):
    """A throwaway pilot DB with ``rows`` seeded and their raw files staged as .gz."""
    work = ROOT / ".tmp" / f"shp_xbrl_test_{os.getpid()}_{name}"
    if work.exists():
        shutil.rmtree(work)
    raw = work / "raw"
    raw.mkdir(parents=True)
    for file in {r["file"] for r in rows}:
        (raw / f"{file}.gz").write_bytes(gzip.compress((FIX / file).read_bytes()))
    monkeypatch.setattr(fx, "RAW_DIR", raw)
    monkeypatch.setattr(fx, "DB_PATH", work / "pilot.db")
    con = fx.open_db()
    fx.seed(con, rows)
    return con


def test_percent_convention_reports_every_class():
    got = fx.parse_shp_xml(_text("pct_all.xml"))
    assert got["status"] == "ok"
    assert got["scale"] == "percent"
    assert got["classes"] == {"promoter": 50.0, "public": 50.0, "fii": 10.0,
                              "dii": 15.0, "mf": 8.0, "insurance": 2.0}
    assert got["missing"] == []
    assert got["pledge"] == 1.5 and got["pledge_basis"] == "numeric"
    assert got["period_end"] == "2024-07-05" and got["isin"] == ISIN_A


def test_fraction_convention_scales_and_keeps_a_reported_zero():
    got = fx.parse_shp_xml(_text("frac_missing_mf.xml"))
    assert got["scale"] == "fraction"
    assert got["classes"]["promoter"] == 50.0          # 0.5 of the shares, as a percent
    assert got["classes"]["fii"] == 0.0                # reported as zero, not missing
    assert "mf" in got["missing"] and "mf" not in got["classes"]
    assert got["pledge"] == 0.0 and got["pledge_basis"] == "numeric"


def test_pledge_from_the_boolean_when_no_number_is_filed():
    got = fx.parse_shp_xml(_text("pledge_flag_true.xml"))
    assert got["pledge"] is None
    assert got["pledge_basis"] == "flag_true_no_value"

    false_text = _text("pledge_flag_true.xml").replace(">true<", ">false<")
    assert fx.parse_shp_xml(false_text)["pledge"] == 0.0
    assert fx.parse_shp_xml(false_text)["pledge_basis"] == "boolean_false"


def test_unknown_scale_and_no_facts_never_impute():
    assert fx.parse_shp_xml("<xbrli:xbrl/>")["status"] == "no_facts"
    solo_fii = (
        '<xbrli:xbrl xmlns:in-bse-shp="http://x" xmlns:xbrldi="http://y" '
        'xmlns:xbrli="http://z"><xbrli:context id="C"><xbrli:period>'
        '<xbrli:instant>2024-06-30</xbrli:instant></xbrli:period><xbrli:scenario>'
        '<xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
        'in-bse-shp:InstitutionsForeignMember</xbrldi:explicitMember></xbrli:scenario>'
        '</xbrli:context><in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares '
        'contextRef="C" unitRef="pure">10</in-bse-shp:'
        'ShareholdingAsAPercentageOfTotalNumberOfShares></xbrli:xbrl>')
    assert fx.parse_shp_xml(solo_fii)["status"] == "scale_unknown"


def test_zero_row_written_and_missing_class_not_written(monkeypatch):
    con = _open(monkeypatch, "zero_missing", [
        _filing("3", "frac_missing_mf.xml", "2024-09-30", "2024-10-04T09:00:00",
                isin="INE000B01002")])
    assert fx.parse(con) == {"ok": 1}
    values = dict(con.execute("SELECT dims, value FROM fact WHERE atom='hold.pct'"))
    assert values["holder_class=fii"] == 0.0
    assert "holder_class=mf" not in values
    reported, missing, scale = con.execute(
        "SELECT classes_reported, classes_missing, scale FROM filings").fetchone()
    assert "fii=0" in reported and "mf" not in reported
    assert missing == "mf" and scale == "fraction"


def test_revised_filing_is_its_own_row_and_the_original_survives(monkeypatch):
    rows = [_filing("1", "pct_all.xml", "2024-06-30", "2024-07-05T10:00:00"),
            _filing("2", "pct_revised.xml", "2024-06-30", "2024-07-19T11:00:00",
                    revised="Revised")]
    con = _open(monkeypatch, "revised", rows)
    assert fx.parse(con) == {"ok": 2}
    got = con.execute(
        "SELECT known_at, value FROM fact WHERE entity_id=? AND atom='hold.pct' "
        "AND dims='holder_class=fii' ORDER BY known_at", (ISIN_A,)).fetchall()
    assert got == [("2024-07-05T10:00:00", 10.0), ("2024-07-19T11:00:00", 12.5)]
    # the original is usable before the revision lands
    before = con.execute("SELECT COUNT(*) FROM fact WHERE known_at <= '2024-07-06'").fetchone()[0]
    assert before == ATOMS_PER_FILING
    # the pledge value also moves with the revision, on its own key
    pledge = con.execute("SELECT value FROM fact WHERE atom='hold.pledge_pct' "
                         "ORDER BY known_at").fetchall()
    assert [v for (v,) in pledge] == [1.5, 2.0]


def test_promoter_public_crosscheck_against_shp_index(monkeypatch):
    rows = [_filing("1", "pct_all.xml", "2024-06-30", "2024-07-05T10:00:00",
                    promoter=50.0, public=50.0),
            _filing("2", "pct_revised.xml", "2024-06-30", "2024-07-19T11:00:00",
                    revised="Revised", promoter=44.19, public=50.0)]
    con = _open(monkeypatch, "xcheck", rows)
    assert fx.parse(con) == {"ok": 2}
    matches = dict(con.execute("SELECT record_id, match FROM xcheck").fetchall())
    assert matches == {"1": 1, "2": 0}
    px, shp, delta = con.execute(
        "SELECT promoter_xbrl, promoter_shp, promoter_delta FROM xcheck "
        "WHERE record_id='2'").fetchone()
    assert px == 50.0 and shp == 44.19 and round(delta, 4) == 5.81


def test_seed_rows_match_the_independent_reread():
    if not RAW.is_dir():
        pytest.skip(f"no raw folder at {RAW}")
    rows = verify(SEED, RAW)
    assert len(rows) == 20
    bad = [r for r in rows if not r["ok"]]
    assert not bad, bad
    assert {r["atom"] for r in rows} == {"hold.pct", "hold.pledge_pct"}
    assert {r["dims"] for r in rows} == {"holder_class=fii", "holder_class=dii",
                                        "holder_class=mf", "holder_class=insurance",
                                        "holder_class=promoter"}
