"""Fixture tests for the rating-rationale loader and ``pilot3_ratings`` (T-139 step 2).

    python -m pytest -q plugins/reality-data/tests/test_lookups_ratings.py

Two short rationale texts (one CARE style, one ICRA style) are written under ``.tmp/`` with an ``index.csv``,
loaded into ``.tmp/ratings_fixture.db`` by the real loader, and ``REALITY_RATINGS_DB`` points the lookup at
it: no production store, network or paid call.
"""
from __future__ import annotations

import csv
import hashlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_DIR))

import lookups_ratings as lr  # noqa: E402
from core import DataError  # noqa: E402
from reality_engine.ingestion import rating_rationale_load as load_mod  # noqa: E402

TMP = ROOT / ".tmp"
SRC = TMP / "ratings_fixture_src"
DB = TMP / "ratings_fixture.db"

CARE_TEXT = """CARE Ratings Ltd. 
Press Release 
Havells India Limited 
October 01, 2026 
 
Facilities/Instruments 
Name of the Regulator1 
Amount (₹ crore) 
Rating2 
Rating Action 
Long Term Bank Facilities 
RBI 
500.00 
CARE AAA; Stable 
Assigned 
Short Term Bank Facilities 
RBI 
1,427.50 
CARE A1+ 
Reaffirmed 
Details of instruments/facilities in Annexure-1. 
 
Rationale and key rating drivers 
CareEdge Ratings has reaffirmed the ratings of Havells India Limited at CARE AAA; Stable. 
Rating sensitivities: Factors likely to lead to rating actions 
Positive factors 
Not Applicable 
Negative factors 
Overall gearing beyond 0.5x on a sustained basis. 
Outlook: Stable 
The Stable outlook reflects the expected steady performance. 
Key strengths 
Established brand and distribution network. 
Key weaknesses 
Exposure to raw material price volatility. 
Liquidity: Strong 
Cash and liquid investments of Rs 6,000 crore as on March 31, 2026. 
Annexure-1: Details of instruments/facilities 
Long Term Bank Facilities 
RBI 
900.00 
CARE AAA; Stable 
Reaffirmed 
"""

ICRA_TEXT = """www.icra.in 
Page |1 
Sensitivity Label : Public 
July 15, 2026 
Titan Company Limited: Ratings reaffirmed 
Summary of rating action 
Instrument* 
Current rated amount (Rs. crore) 
Rating action 
Commercial Paper 
5,000.00 
[ICRA]A1+ ; Reaffirmed 
RBI 
Long-term - Fund-based/Non- 
fund based - Others 
3,000.00 
[ICRA]AAA (Stable); 
Reaffirmed 
RBI 
Rationale 
The reaffirmed ratings factor in Titan's market leadership in jewellery. 
Key rating drivers and their description 
Credit strengths 
Strong brand and store network. 
Credit challenges 
Exposure to gold price volatility. 
Rating sensitivities 
Negative factors - Decline in operating margin below 8%. 
Liquidity position: Strong 
Cash and liquid investments of Rs 5,000 crore. 
Outlook: Stable 
The Stable outlook reflects steady demand. 
"""


def _row(symbol: str, agency: str, rating_date: str, rating: str, outlook: str, action: str,
         instrument: str, text: str, url: str) -> dict[str, str]:
    return {"symbol": symbol, "agency": agency, "rating_date": rating_date, "url": url,
            "instrument": instrument, "rating": rating, "outlook": outlook, "action": action,
            "chars": str(len(text)), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "fetched_at": "2026-11-09T00:00:00Z"}


def build_fixture() -> None:
    shutil.rmtree(SRC, ignore_errors=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB) + suffix).unlink(missing_ok=True)
    rows = []
    for symbol, agency, rating_date, text, rating, outlook, action, instrument in (
        ("HAVELLS", "CARE", "2026-10-14", CARE_TEXT, "CARE AAA", "Stable", "reaffirmed",
         "Long Term Bank Facilities"),
        ("TITAN", "ICRA", "2026-07-15", ICRA_TEXT, "[ICRA]AAA", "Stable", "reaffirmed",
         "Long-term - Fund-based/Non- fund based - Others"),
    ):
        folder = SRC / symbol
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{agency}_{rating_date}_1.txt").write_text(text, encoding="utf-8")
        rows.append(_row(symbol, agency, rating_date, rating, outlook, action, instrument, text,
                         f"https://example.invalid/{symbol}/{rating_date}"))
    with (SRC / "index.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    load_mod.load(SRC, DB)


@pytest.fixture(scope="module", autouse=True)
def fixture():
    build_fixture()
    os.environ["REALITY_RATINGS_DB"] = str(DB)
    yield
    os.environ.pop("REALITY_RATINGS_DB", None)


def _actions(out: dict, agency: str | None = None) -> list[dict]:
    return [a for a in out["actions"] if agency is None or a["agency"] == agency]


def test_tables_match_the_schema_and_carry_the_text():
    con = sqlite3.connect(DB)
    try:
        columns = [row[1] for row in con.execute("PRAGMA table_info(outside_doc)")]
        assert columns == ["outside_id", "source", "kind", "title", "published_at", "url", "sha256", "text"]
        assert con.execute("SELECT COUNT(*) FROM outside_doc").fetchone()[0] == 2
        stored = con.execute("SELECT text FROM outside_doc WHERE source='care'").fetchone()[0]
        assert "Established brand and distribution network." in stored
    finally:
        con.close()


def test_care_sections_split():
    sections = load_mod.split_sections(CARE_TEXT)
    assert set(sections) == {"rationale", "sensitivities", "outlook", "strengths", "weaknesses", "liquidity"}
    assert "Established brand and distribution network." in sections["strengths"]
    assert "raw material price volatility" in sections["weaknesses"]
    assert "Overall gearing beyond 0.5x" in sections["sensitivities"]
    assert "Cash and liquid investments" in sections["liquidity"]
    assert "steady performance" in sections["outlook"]


def test_icra_sections_split():
    sections = load_mod.split_sections(ICRA_TEXT)
    # "Key rating drivers and their description" is a wrapper: its own body is empty (the strengths and
    # challenges below it are the content), so it is not stored as a section.
    assert set(sections) == {"rationale", "strengths", "weaknesses", "sensitivities", "liquidity", "outlook"}
    assert "market leadership in jewellery" in sections["rationale"]
    assert "Strong brand and store network." in sections["strengths"]
    assert "gold price volatility" in sections["weaknesses"]
    assert "operating margin below 8%" in sections["sensitivities"]


def test_care_instrument_rows_parsed():
    rows = load_mod.parse_actions(CARE_TEXT, "2026-10-14")
    assert len(rows) == 2  # the Annexure repeat above the first rationale heading is not counted twice
    by_instrument = {row["instrument"]: row for row in rows}
    long_term = by_instrument["Long Term Bank Facilities"]
    assert long_term["rating"] == "CARE AAA"
    assert long_term["outlook"] == "Stable"
    assert long_term["action"] == "assigned"
    assert long_term["amount_crore"] == 500.0
    short_term = by_instrument["Short Term Bank Facilities"]
    assert short_term["rating"] == "CARE A1+"
    assert short_term["action"] == "reaffirmed"
    assert short_term["amount_crore"] == 1427.5


def test_icra_instrument_rows_parsed():
    rows = load_mod.parse_actions(ICRA_TEXT, "2026-07-15")
    by_rating = {row["rating"]: row for row in rows}
    assert by_rating["[ICRA]A1+"]["action"] == "reaffirmed"
    assert by_rating["[ICRA]A1+"]["amount_crore"] == 5000.0
    graded = by_rating["[ICRA]AAA"]
    assert graded["outlook"] == "Stable"
    assert graded["action"] == "reaffirmed"
    assert graded["instrument"] == "Long-term - Fund-based/Non- fund based - Others"


def test_printed_date_is_used_as_the_known_at_floor():
    assert load_mod.printed_date(CARE_TEXT) == "2026-10-01"
    assert load_mod.printed_date(ICRA_TEXT) == "2026-07-15"
    out = lr.ratings("HAVELLS")
    assert out["documents"][0]["known_at"] == "2026-10-14"  # the upload stamp is later, it wins


def test_ratings_returns_actions_and_sections():
    out = lr.ratings("HAVELLS")
    assert out["found"] is True
    assert {(a["agency"], a["rating"], a["outlook"]) for a in out["actions"]} == {
        ("CARE", "CARE AAA", "Stable"), ("CARE", "CARE A1+", "")}
    document = out["documents"][0]
    assert "strengths" in document["sections"]
    assert "Established brand and distribution network." in document["sections"]["strengths"]
    assert document["provenance"]["agency"] == "CARE"
    assert document["provenance"]["source"].endswith("/HAVELLS/2026-10-14")
    assert out["latest_by_agency"]["CARE"]["rating"] == "CARE AAA"


def test_as_of_drops_a_later_action():
    out = lr.ratings("TITAN", as_of="2026-08-01")
    assert out["found"] is True
    assert out["as_of"] == "2026-08-01"
    assert {doc["agency"] for doc in out["documents"]} == {"ICRA"}
    assert {action["agency"] for action in out["actions"]} == {"ICRA"}
    out = lr.ratings("HAVELLS", as_of="2026-08-01")
    assert out["found"] is False
    assert out["held"] == [{"agency": "CARE", "latest": "2026-10-14", "docs": 1,
                            "first_known": "2026-10-14"}]


def test_agency_filter():
    out = lr.ratings("TITAN", agency="CARE")
    assert out["found"] is False
    out = lr.ratings("TITAN", agency="icra")
    assert out["found"] is True
    assert {action["agency"] for action in out["actions"]} == {"ICRA"}


def test_section_filter_returns_only_that_section():
    out = lr.ratings("HAVELLS", section="triggers")
    document = out["documents"][0]
    assert list(document["sections"]) == ["sensitivities"]
    assert "Overall gearing beyond 0.5x" in document["sections"]["sensitivities"]
    with pytest.raises(DataError) as excinfo:
        lr.ratings("HAVELLS", section="dividend policy")
    assert excinfo.value.code == "bad_section"


def test_unknown_symbol_returns_found_false():
    out = lr.ratings("NOSUCHCO")
    assert out["found"] is False
    assert out["actions"] == []
    assert out["available_symbols"] == ["HAVELLS", "TITAN"]
