"""T-093: the company check on real first-page text.  Pure functions: no store, no file."""
from __future__ import annotations

import sqlite3

from reality_engine.pilot3 import schema
from reality_engine.pilot3.doc_identity import Expected, check

KEC_PAGE = ("KEC INTERNATIONAL LTD. RPG House 463, Dr. Annie Besant Road Worli, Mumbai 400030, India +91 22 66670200 "
            "kecindia@kecrpg.com www.kecrpg.com Registered Office: RPG House, 463, Dr. Annie Besant Road Worli, Mumbai "
            "400030, CIN: L45200MH2005PLC152061, India. An RPG Company. Integrated Report 2025-26.")
LETTER = ("June 10, 2026 BSE Limited Corporate Relationship Department 1st Floor, New Trading Ring, Rotunda Bldg., P. J. "
          "Towers, Dalal Street, Fort, Mumbai 400 001. Scrip Code: 500400 National Stock Exchange of India Limited "
          "Exchange Plaza, Bandra Kurla Complex. Sub: Annual Report for the Financial Year 2025-26 and notice of AGM.")


def _expected(name, code="", prefix=""):
    return Expected(symbol="S", doc_type="ANNUAL_REPORT", names=(name,), bse_codes=(code,) if code else (),
                    isin_prefixes=(prefix,) if prefix else ())


def test_name_in_the_first_pages_is_the_company():
    result = check({1: KEC_PAGE}, _expected("KEC International Ltd"))
    assert (result.verdict, result.company) == ("ok", "ok")


def test_scrip_code_in_a_covering_letter_is_the_company():
    result = check({1: LETTER}, _expected("A Name Not On The Letter", code="500400"))
    assert result.company == "ok" and "500400" in result.company_reason


def test_a_swapped_pair_is_set_aside():
    result = check({1: KEC_PAGE}, _expected("Tata Power Company Limited", code="500400", prefix="INE245A"))
    assert (result.verdict, result.company) == ("set_aside", "mismatch")


def test_thin_text_is_unknown_never_a_guess():
    result = check({1: "scanned", 2: ""}, _expected("KEC International Ltd"))
    assert (result.verdict, result.company) == ("unknown", "thin")


def test_table_exists():
    conn = sqlite3.connect(":memory:")
    conn.execute(schema.TABLES["doc_identity"])
    columns = {row[1] for row in conn.execute("PRAGMA table_info(doc_identity)")}
    assert {"doc_key", "verdict", "company", "fiscal_year", "type", "date", "filing_date", "file_where"} <= columns
