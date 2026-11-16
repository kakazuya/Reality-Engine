"""T-025 / store-repair note R-003: order wins read from the prescribed Regulation 30 table and from headlines.

Every case is the shape of a real filing that broke the first version on the ten measured stores; the company and
customer names are invented.
"""
from __future__ import annotations

import sqlite3

from reality_engine.pilot3 import order_wins as ow, schema

TABLE = """Sub: Intimation of Work Order Received
Ref: Announcement under Regulation 30 of SEBI (LODR) Regulations, 2015
we are pleased to intimate that Acme Builders Limited has secured an order worth ₹ 200.02 Crores as per details given below:
S.No. Particulars Disclosure
A Name of entity awarding the order(s)/ contract(s) Northside Developers Private Limited
B Significant terms and conditions of order(s)/contract(s) awarded in brief Commercial Building Civil Structure Work
C Whether order(s)/contract(s) have been awarded by domestic / international entity Domestic
D Nature of order(s)/contract(s) Civil & Structural Works
E Whether domestic/international Domestic
F Time period by which the order(s)/ contract(s) is to be executed 25 months approx.
G Broad consideration or size of the order(s)/contract(s) ₹ 200.02 Crores (Excl. GST)
H Whether promoter /promoter group companies have any interest in the entity that awarded the order(s) /contract(s)? if yes, nature of interest and details thereof No
I Whether order(s)/contract(s) would fall within related party transactions? If yes whether the same is done at “arm’s length” No
The LOA has been received on 15.10.2026 at 4:15 pm. The above may kindly be taken on records."""


def test_prescribed_table_gives_every_field_and_flags_a_headline_slip():
    (row,) = ow.parse("The Company has secured an order worth Rs. 202.02 Crores.", TABLE)
    assert row["extractor_rule"] == ow.RULE_TABLE and row["value_source"] == "table"
    assert row["awarder"] == "Northside Developers Private Limited"
    assert row["value_cr"] == 200.02 and row["title_value_cr"] == 202.02 and row["title_mismatch"] == 1
    assert row["duration_months"] == 25.0 and row["duration_text"].startswith("25 months")
    assert row["domestic"] == "domestic" and row["promoter_interest"] == "no" and row["related_party"] == "no"
    assert row["nature"] == "Civil & Structural Works" and "secured an order" in row["quote"]


def test_two_orders_in_one_filing_give_two_rows_that_add_up_to_the_headline():
    second = TABLE.replace("Northside Developers Private Limited", "Eastgate Homes Ltd.").replace("200.02", "300")
    rows = ow.parse("The Company has secured two new orders aggregating to Rs. 500.02 crores", TABLE + "\nOrder No.2\n" + second)
    assert [(r["seq"], r["awarder"], r["value_cr"]) for r in rows] == [
        (1, "Northside Developers Private Limited", 200.02), (2, "Eastgate Homes Ltd.", 300.0)]
    assert all(r["title_mismatch"] == 0 for r in rows)


def test_full_rupee_figure_dollars_and_an_unreadable_duration():
    text = TABLE.replace("₹ 200.02 Crores (Excl. GST)", "Total size of the order: Rs. 28,59,32,004/- (Rupees Twenty-Eight Crore only)")
    text = text.replace("25 months approx.", "commence within three (03) months and complete within eighteen (18) months; licence 35 years")
    (row,) = ow.parse("Disclosure under Regulation 30", text.replace("worth ₹ 200.02 Crores", ""))
    assert row["value_cr"] == 28.5932 and row["duration_months"] is None and "eighteen" in row["duration_text"]
    usd = TABLE.replace("₹ 200.02 Crores (Excl. GST)", "approximately USD 16.72 million exclusive of GST").replace("worth ₹ 200.02 Crores", "")
    (row,) = ow.parse("Intimation on Receipt of Contract", usd)
    assert row["value_cr"] is None and row["value_usd_mn"] == 16.72 and row["value_source"] == "table"


def test_headline_win_without_a_table_and_a_win_with_no_printed_size():
    (row,) = ow.parse("Acme Infra wins Rs. 1,438 Crore Order to Transform Water Access", "Press release. Acme Infra wins Rs. 1,438 Crore order.")
    assert row["extractor_rule"] == ow.RULE_TEXT and row["value_cr"] == 1438.0 and row["awarder"] is None
    (row,) = ow.parse("Intimation of Award of New Contract", "Sub: Award of contract. Details will follow.")
    assert row["value_cr"] is None and row["value_source"] is None


def test_orders_that_are_not_customer_orders_give_no_row():
    tax = ("Sub: Disclosure under Regulation 30. we wish to inform you that the Company has received an order under section "
           "254 of the Income tax Act, 1961. As per the order, the Company is entitled to a refund of INR 7.11 Crores.")
    assert ow.parse("Disclosure under Regulation 30 of the SEBI Regulations, 2015", tax) == []
    assert ow.parse("The Hon'ble High Court of Delhi passed the order in terms of settlement", "order passed") == []
    assert ow.parse("The company has received NCLT Order regarding dispensation of meeting", "NCLT order") == []
    results = "Press Release: Unaudited Financial Results for the quarter. During the quarter the company secured orders worth Rs. 100 Crore."
    assert ow.parse("Please find attached Press Release pertaining to the Unaudited Financial Results", results) == []
    assert ow.parse("Draft Letter of Offer to the Public Shareholders", "Letter of Offer") == []


def test_a_scanned_table_whose_values_run_into_labels_leaves_those_fields_empty():
    scan = ("Sub: Receipt of Letter of Acceptance. We are pleased to inform that the company has received Letter of Acceptance. "
            "1 Name of the entity awarding the Metro Water Board order(s) / contract(s) "
            "6 Time period by which the order(s)/ contract(s) is to be executed 7 Broad consideration or size of the "
            "order(s) / contract(s) 8 Whether the promoter/ promoter group / Group companies have any interest in the entity "
            "that awarded the order(s)/ contract(s)? If yes, nature of interest and details thereof")
    rows = ow.parse("Intimation of Receipt of Letter of Acceptance as attached", scan)
    assert len(rows) == 1 and rows[0]["value_cr"] is None and rows[0]["duration_months"] is None


def test_build_writes_rows_once_for_a_filing_the_feed_repeats():
    conn = sqlite3.connect(":memory:")
    schema.migrate(conn)
    conn.execute(schema.TABLES["doc"].replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
    conn.execute(schema.TABLES["doc_page"].replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
    for key in ("d1", "d2"):
        conn.execute("INSERT INTO doc (doc_key, symbol, isin, doc_type, title, filing_date, known_at) VALUES "
                     "(?, 'ACME', 'INE000A01001', 'announcement', 'The Company has secured an order worth Rs. 200.02 Crores', "
                     "'2026-10-16', '2026-10-16T10:00:00')", (key,))
        conn.execute("INSERT INTO doc_page (doc_key, symbol, page, text) VALUES (?, 'ACME', 1, ?)", (key, TABLE))
    stats = ow.build(conn)
    assert stats["rows"] == 1 and stats["duplicates"] == 1 and stats[ow.RULE_TABLE] == 1
    row = conn.execute("SELECT symbol, announced, seq, value_cr, awarder, known_at FROM order_win").fetchone()
    assert row == ("ACME", "2026-10-16", 1, 200.02, "Northside Developers Private Limited", "2026-10-16T10:00:00")
