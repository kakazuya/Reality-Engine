"""T-241: make_profile builds a profile for a company master_companies lacks, from the universe row's ISIN/BSE code.

Order: master by key (unchanged) -> master by the fallback ISIN or BSE code -> a synthesized entry marked
``"master": False``.  No fallback and no master row still raises ``KeyError``.  The store is an in-memory sqlite
with only the tables make_profile reads; no real data.

    python -m pytest reality_engine/tests/test_make_profile_fallback.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from reality_engine.pilot3.make_profile import UNKNOWN, company_row, make_profile

TABLE = {"basic_industry": {"Computers - Software & Consulting": "it_services"},
         "industry": {}, "master_industry": {}, "bse_industry": {"Software": "it_services"},
         "lender_basic_industry": [], "lender_industry": []}

SCHEMA = """
CREATE TABLE master_companies (isin TEXT, nse_symbol TEXT, bse_code TEXT, company_name TEXT, industry TEXT,
                               is_active INTEGER);
CREATE TABLE symbol_isin_history (exchange TEXT, symbol TEXT, isin TEXT, first_date TEXT, last_date TEXT,
                                  n_days INTEGER);
CREATE TABLE isin_rekey_log (symbol TEXT, old_isin TEXT, new_isin TEXT);
CREATE TABLE corporate_documents (isin TEXT, symbol TEXT);
CREATE TABLE shp_index (symbol TEXT, isin TEXT, name TEXT, quarter_end TEXT);
CREATE TABLE company_industry (isin TEXT, symbol TEXT, industry TEXT, basic_industry TEXT);
CREATE TABLE board_meetings (symbol TEXT, isin TEXT, industry TEXT);
CREATE TABLE security_master (isin TEXT, name TEXT, nse_symbol TEXT, bse_code TEXT, bse_symbol TEXT);
"""


@pytest.fixture()
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.execute("INSERT INTO master_companies VALUES ('INE000A01011','ALPHA','500001','Alpha Ltd','',1)")
    db.execute("INSERT INTO company_industry VALUES ('INE000A01011','ALPHA',NULL,'Computers - Software & Consulting')")
    # BETA is in master under another symbol: only its ISIN or BSE code finds it.
    db.execute("INSERT INTO master_companies VALUES ('INE000B01012','BETANEW','500002','Beta Ltd','',1)")
    # GAMMA is BSE-only: no master row; the security master files its name, board meetings its BSE industry.
    db.execute("INSERT INTO security_master VALUES ('INE000C01013','GAMMA SYSTEMS',NULL,'500003','GAMMA')")
    db.execute("INSERT INTO corporate_documents VALUES ('INE000C01013','GAMMA')")
    db.execute("INSERT INTO board_meetings VALUES ('GAMMA','INE000C01013','Software')")
    return db


def test_master_row_wins_and_carries_no_master_flag(conn):
    row = company_row(conn, "ALPHA", TABLE, fallback={"isin": "INE999Z01019", "bse_code": "999999"})
    assert row == {"symbol": "ALPHA", "name": "Alpha Ltd", "bse_code": "500001", "isins": ["INE000A01011"],
                   "sector": "it_services", "lender": False}
    assert company_row(conn, "ALPHA", TABLE) == row


def test_fallback_isin_recovers_master_row(conn):
    row = company_row(conn, "BETA", TABLE, fallback={"isin": "INE000B01012", "bse_code": ""})
    assert row["symbol"] == "BETANEW" and row["name"] == "Beta Ltd" and "master" not in row


def test_fallback_bse_code_recovers_master_row(conn):
    row = company_row(conn, "BETA", TABLE, fallback={"isin": "", "bse_code": "500002"})
    assert row["isins"] == ["INE000B01012"] and row["bse_code"] == "500002"


def test_synthesized_row_for_a_company_master_lacks(conn):
    row = company_row(conn, "gamma", TABLE, fallback={"isin": "INE000C01013", "bse_code": "500003"})
    assert row == {"symbol": "GAMMA", "name": "GAMMA SYSTEMS", "bse_code": "500003", "isins": ["INE000C01013"],
                   "sector": "it_services", "lender": False, "master": False}


def test_synthesized_row_from_bse_code_alone_finds_the_isin(conn):
    row = company_row(conn, "GAMMA", TABLE, fallback={"bse_code": "500003"})
    assert row["isins"] == ["INE000C01013"] and row["master"] is False


def test_synthesized_row_without_any_label_stays_unknown_and_named_by_symbol(conn):
    row = company_row(conn, "DELTA", TABLE, fallback={"isin": "INE000D01014", "bse_code": "500004"})
    assert row["sector"] == UNKNOWN and row["name"] == "DELTA" and row["master"] is False


def test_no_fallback_and_no_master_row_raises(conn):
    with pytest.raises(KeyError, match="not in master_companies"):
        company_row(conn, "GAMMA", TABLE)
    with pytest.raises(KeyError):
        company_row(conn, "GAMMA", TABLE, fallback={"isin": "", "bse_code": ""})


def test_profile_fallback_needs_exactly_one_company(conn, tmp_path):
    with pytest.raises(ValueError):
        make_profile(["ALPHA", "GAMMA"], "x", tmp_path, None, None, conn, fallback={"isin": "INE000C01013"})
