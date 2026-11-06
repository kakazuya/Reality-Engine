"""T-091: the annual-report note tables (rating_event, concentration, related_party_txn).

The page text below is copied from the pilot10 pages named in the ticket (BAJFINANCE annual report p373/p374,
INFY p125/p241/p320, ETERNAL p181/p273/p387, MARUTI p115, HDFCBANK p415, KEC p76, and the BAJFINANCE
27 August 2026 NCD-allotment filing p2), trimmed to the lines the readers use.  No model, no database.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

from reality_engine.pilot3 import notes
from reality_engine.pilot3.schema import NOTES_INDEXES, TABLES

DOC = {"doc_key": "X/annual_report/a.pdf", "doc_type": "annual_report", "isin": "INE000000000",
       "title": "", "filing_date": "2026-07-07", "known_at": "2026-07-07T18:00:00", "page": 1}
ANN = {**DOC, "doc_key": "X/material_filing/b.pdf", "doc_type": "announcement", "filing_date": "2026-08-27",
       "known_at": "2026-08-27T11:25:43"}
LEX = notes.lexicon()


def rows(kind, text, doc=DOC, page=1):
    fn = {"rating": notes.rating_rows, "concentration": notes.concentration_rows,
          "rpt": notes.related_party_rows}[kind]
    return fn("SYM", doc["isin"], "Test Ltd", doc, page, text, LEX)


# --- rating_event ------------------------------------------------------------------------------------------------
BAJFINANCE_RATING = """Notes to standalone financial statements for the year ended 31 March 2026 (Contd.)
(H) Details of ratings assigned by credit rating agencies and migration of ratings during the year
Rating agency
Programme
Ratings assigned
Migration in ratings
during the year
India Ratings
Non-convertible debenture
IND AAA/Stable
Nil
Short-term bank rating
IND A1+
Nil
CRISIL
Non-convertible debenture
CRISIL AAA/Stable
Nil
ICRA
Non-convertible debenture
ICRA AAA/Stable
Nil
CARE
Non-convertible debenture
CARE AAA/Stable
Nil
S&P Global
Entity level
Long-term issuer rating of 'BBB'
with Stable outlook
Upgraded from
BBB- with Positive outlook
Short-term rating of 'A-2'
Upgraded from A-3"""


def test_rating_table_rows():
    out = rows("rating", BAJFINANCE_RATING)
    seen = {(r["agency"], r["instrument"], r["rating"], r["outlook"], r["action"]) for r in out}
    assert ("India Ratings", "Non-convertible debenture", "IND AAA", "Stable", "reaffirmed") in seen
    assert ("India Ratings", "Short-term bank rating", "IND A1+", None, "reaffirmed") in seen
    assert ("CRISIL", "Non-convertible debenture", "CRISIL AAA", "Stable", "reaffirmed") in seen
    assert ("CARE", "Non-convertible debenture", "CARE AAA", "Stable", "reaffirmed") in seen
    assert ("S&P Global", "Entity level", "BBB", "Stable", "upgraded") in seen
    assert ("S&P Global", "Entity level", "A-2", None, "upgraded") in seen
    assert not any(r["rating"] == "BBB-" for r in out)          # the rating moved from, not the one in force
    assert all(r["basis"] == "standalone" for r in out)
    assert all(r["fiscal_year"] == "FY26" for r in out)


INFY_RATING = """Credit ratings
There has been no change in the credit ratings of Infosys from any of the agencies during the year.
Rating agency
Rating
Outlook
Moody's
Baa1
Stable
Standard & Poor's
A
Stable
Dun & Bradstreet
5A1
Condition: Strong
CRISIL
AAA
Stable"""


def test_rating_outlook_column_and_no_change():
    out = rows("rating", INFY_RATING)
    assert len(out) == 4
    by_agency = {r["agency"]: r for r in out}
    assert by_agency["Moody's"]["rating"] == "Baa1" and by_agency["Moody's"]["outlook"] == "Stable"
    assert by_agency["Standard & Poor's"]["rating"] == "A"
    assert by_agency["Dun & Bradstreet"]["rating"] == "5A1"
    assert by_agency["CRISIL"]["rating"] == "AAA"
    assert all(r["action"] == "reaffirmed" for r in out)


def test_rating_not_rated():
    text = """Credit Rating
During the financial year under review, the Company has not obtained any credit rating."""
    out = rows("rating", text)
    assert len(out) == 1 and out[0]["action"] == "not_rated" and out[0]["rating"] is None


def test_rating_prose_long_and_short_term():
    text = ("CRISIL Ratings\n"
            "The Company was awarded the highest financial credit rating of AAA/Stable (long term) and "
            "A1+ (short term) on its bank facilities by CRISIL.")
    out = rows("rating", text)
    assert [(r["rating"], r["outlook"], r["action"]) for r in out] == [("AAA", "Stable", "assigned"),
                                                                      ("A1+", None, "assigned")]
    assert out[0]["instrument"] == "bank facilities (long term)"
    assert out[1]["instrument"] == "bank facilities (short term)"


def test_rating_trigger_clause():
    text = """Special right/interest/privileges attached to the instrument and changes thereof
Step Up/Step Down Coupon Rate
1. If the rating of instrument is downgraded to "double A minus (AA-)" or below at any time, the first/
initial/primary/original investor(s) to the tranche reserves the right to increase the interest rate by up to
25bps for every notch of downgrade w.e.f. the date of downgrade.
2. In case the rating falls to "A" or below at any time, the first/ initial/primary/original investor(s) to the
tranche reserves the right to recall the outstanding principal amount on the aforesaid NCDs."""
    out = notes.trigger_rows("SYM", DOC["isin"], "Test Ltd", ANN, 2, text, LEX)
    assert [r["rating"] for r in out] == ["AA-", "A"]
    assert all(r["action"] == "trigger" and r["trigger_text"] for r in out)


# --- concentration -----------------------------------------------------------------------------------------------
BAJFINANCE_CONC = """Notes to standalone financial statements for the year ended 31 March 2026 (Contd.)
(L) Concentration of deposits, advances, exposures and NPAs
(I) Concentration of deposits
(C in crore)
As at 31 March
Particulars
2026
2025
Total deposits of twenty largest depositors
13,346.95
11,194.76
Percentage of deposits to twenty largest depositors to total deposits
19.49%
15.69%
(II) Concentration of advances
(C in crore)
As at 31 March
Particulars
2026
2025
Total advances to twenty largest borrowers
14,951.00
14,032.99
Percentage of advances to twenty largest borrowers to total advances
3.35%
3.80%"""


def test_concentration_table_both_years():
    out = rows("concentration", BAJFINANCE_CONC, page=374)
    got = {(r["measure"], r["fiscal_year"]): (r["pct"], r["value"]) for r in out}
    assert got[("deposits", "FY26")] == (None, 13346.95)
    assert got[("deposits", "FY25")] == (None, 11194.76)
    assert got[("share of deposits", "FY26")] == (19.49, None)
    assert got[("share of deposits", "FY25")] == (15.69, None)
    assert got[("share of advances", "FY26")] == (3.35, None)
    assert all(r["dimension"] == "depositor" for r in out if "deposit" in r["measure"])
    assert all(r["bucket"] == "top_20" for r in out)
    assert {(r["unit"], r["scale"]) for r in out if r["value"] is not None} == {("inr_cr", 1e7)}


INFY_CONC = """The following table gives details in respect of percentage of revenues generated from top five
customers and top ten customers:
(In %)
Particulars
Year ended March 31,
2026
2025
Revenue from top five customers
12.7
12.0
Revenue from top ten customers
20.5
19.9"""


def test_concentration_percent_table():
    out = rows("concentration", INFY_CONC, page=241)
    got = {(r["bucket"], r["fiscal_year"]): r["pct"] for r in out}
    assert got[("top_5", "FY26")] == 12.7 and got[("top_5", "FY25")] == 12.0
    assert got[("top_10", "FY26")] == 20.5 and got[("top_10", "FY25")] == 19.9
    assert all(r["measure"] == "share of revenue" and r["dimension"] == "customer" for r in out)


def test_concentration_prose():
    text = ("As of March 31, 2026, the top 20 depositors comprised of 4.81% of total deposits indicating a "
            "healthy and stable deposit profile.")
    out = rows("concentration", text, page=415)
    assert len(out) == 1
    assert out[0]["dimension"] == "depositor" and out[0]["bucket"] == "top_20"
    assert out[0]["measure"] == "share of deposits" and out[0]["pct"] == 4.81
    assert out[0]["period_end"] == "2026-03-31" and out[0]["fiscal_year"] == "FY26"


KEC_CONC = """9. Open-ness of business
Details of concentration of purchases and sales with trading houses, dealers, and related parties
Parameter
Metrics
FY 2025-26
FY 2024-25
Concentration of
Purchases
a.
Purchases from trading houses as % of total
purchases
2.63%
3.62%
b.
Number of trading houses where purchases are made from
455
89
c.
Purchases from top 10 trading houses as % of total purchases from trading houses
49.31%
62.70%"""


def test_concentration_trading_houses():
    out = rows("concentration", KEC_CONC, page=76)
    got = {(r["bucket"], r["fiscal_year"]): r["pct"] for r in out}
    assert got[(None, "FY26")] == 2.63 and got[(None, "FY25")] == 3.62
    assert got[("top_10", "FY26")] == 49.31 and got[("top_10", "FY25")] == 62.70
    assert all(r["dimension"] == "trading_house" and r["measure"] == "share of purchases" for r in out)


# --- related_party_txn -------------------------------------------------------------------------------------------
ETERNAL_RPT = """Notes to the Standalone Financial Statements
for the year ended March 31, 2026
B. Transactions and balances with related parties:
(INR crores)
Particulars
March 31, 2026
March 31, 2025
Reimbursement for delivery partner fees
Zomato Local Services Private Limited
 0
 20
Blink Commerce Private Limited
 3,850
 1,740
Income from cross charge
Zomato Hyperpure Private Limited
 118
 81
Blink Commerce Private Limited
 344
 145"""


def test_rpt_entity_rows_by_year_and_heading():
    out = rows("rpt", ETERNAL_RPT, page=387)
    got = {(r["counterparty"], r["txn_type"], r["fiscal_year"]): r["amount"] for r in out}
    assert got[("Blink Commerce Private Limited", "Reimbursement for delivery partner fees", "FY26")] == 3850.0
    assert got[("Blink Commerce Private Limited", "Reimbursement for delivery partner fees", "FY25")] == 1740.0
    assert got[("Blink Commerce Private Limited", "Income from cross charge", "FY26")] == 344.0
    assert got[("Blink Commerce Private Limited", "Income from cross charge", "FY25")] == 145.0
    assert got[("Zomato Hyperpure Private Limited", "Income from cross charge", "FY26")] == 118.0
    assert all(r["basis"] == "standalone" and r["unit"] == "inr_cr" for r in out)
    assert {r["period_end"] for r in out} == {"2026-03-31", "2025-03-31"}


ETERNAL_RPT_CONS = """Notes to the Consolidated Financial Statements
for the year ended March 31, 2026
B. Transactions and balances with related parties:
(INR crores)
Particulars
March 31, 2026
March 31, 2025
Remuneration to KMP
Salaries and other employee benefits (1)
 146
 165
Directors remuneration and sitting fees (2)
 5
 5
Payment made on behalf of KMP
 0
 0
Donation income
ACAD Foundation
 0
 -"""


def test_rpt_consolidated_stays_apart_from_standalone():
    out = rows("rpt", ETERNAL_RPT_CONS, page=273)
    got = {(r["counterparty"], r["txn_type"], r["fiscal_year"]): r["amount"] for r in out}
    assert got[("KMP", "Salaries and other employee benefits", "FY26")] == 146.0
    assert got[("KMP", "Salaries and other employee benefits", "FY25")] == 165.0
    assert got[("Directors", "remuneration and sitting fees", "FY26")] == 5.0
    assert all(r["basis"] == "consolidated" for r in out)
    standalone = rows("rpt", ETERNAL_RPT, page=387)
    assert {r["basis"] for r in standalone} == {"standalone"}


def test_rpt_footnote_marker_is_not_a_value():
    out = rows("rpt", ETERNAL_RPT_CONS, page=273)
    assert all(r["txn_type"] is None or "(" not in r["txn_type"] for r in out)


def test_rpt_non_note_table_is_not_read():
    text = """Statement of particulars
(INR crores)
Particulars
March 31, 2026
March 31, 2025
Amount required to be spent by the Company during the year
 2,454
 1,664
Bank and NBFC deposits
 1,747
 1,691
Others - quoted
 112
 171"""
    assert rows("rpt", text, page=9) == []


# --- schema and the part -----------------------------------------------------------------------------------------
def test_tables_and_indexes_exist():
    for name in notes.NOTES:
        assert "CREATE TABLE " + name in TABLES[name]
        assert name in notes.COLS
    assert all("CREATE INDEX" in sql for sql in NOTES_INDEXES)


def test_run_writes_rows_and_reruns():
    work = Path(".tmp") / f"notes_test_{os.getpid()}"
    work.mkdir(parents=True, exist_ok=True)
    db = work / "notes.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.executescript(TABLES["doc"] + ";" + TABLES["company"] + ";" + TABLES["doc_page"])
    con.execute("INSERT INTO company(symbol, isin, name) VALUES('SYM', 'INE000000000', 'Test Ltd')")
    con.execute("INSERT INTO doc(doc_key, symbol, isin, doc_type, filing_date, known_at) "
                "VALUES(?, 'SYM', 'INE000000000', 'annual_report', '2026-07-07', '2026-07-07T18:00:00')",
                (DOC["doc_key"],))
    for page, text in ((373, BAJFINANCE_RATING), (374, BAJFINANCE_CONC), (387, ETERNAL_RPT)):
        con.execute("INSERT INTO doc_page(doc_key, symbol, page, text) VALUES(?, 'SYM', ?, ?)",
                    (DOC["doc_key"], page, text))
    con.commit()
    con.close()
    first = notes.run(str(db), ["SYM"])
    assert first["SYM"]["rating_event"] >= 6
    assert first["SYM"]["concentration"] >= 8
    assert first["SYM"]["related_party_txn"] >= 6
    again = notes.run(str(db), ["SYM"])
    assert again["rows"]["rating_event"]["SYM"] == first["rows"]["rating_event"]["SYM"]
    assert again["rows"]["related_party_txn"]["SYM"] == first["rows"]["related_party_txn"]["SYM"]


def test_unit_comes_from_the_statement_or_an_earlier_page_of_the_note():
    pages = [(220, "(All amounts in I million, unless otherwise stated)\nNotes"), (221, "no unit here"), (222, "Party 1 2")]
    assert notes.page_unit(pages, 2) == ("inr_mn", 1e6)
    assert notes.unit_of("Particulars\n₹ in Million\nFY26") == ("inr_mn", 1e6)
    assert notes.page_unit([(1, "no unit"), (2, "still none")], 1) == (None, None)


def test_rating_action_is_only_what_the_page_says():
    text = ("Credit rating\nThese CP are having a Credit Rating of CRISIL A1+ and are listed on BSE Limited.\n")
    found = notes.rating_rows("S", "I", "E", DOC, 1, text, notes.lexicon())
    assert found and all(r["action"] is None for r in found)


def test_rating_letter_inside_a_word_is_no_rating():
    assert notes._rating_cell("OTC", notes.lexicon()) is None


def test_balance_lines_are_balances_not_amounts():
    lex = notes.lexicon()
    assert any(cue.search("Other financial assets") for cue in lex["balance_cues"])
    assert not any(cue.search("Sale of fixed/other assets") for cue in lex["balance_cues"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
