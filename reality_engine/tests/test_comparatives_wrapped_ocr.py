"""T-208 round 3: a garbled results page is read from its OCR words, and a wrapped label is joined before it names
a row.  Every page here is built from inline word boxes (no real store, no D:); the OCR path is a temp PDF and a
temp ``ocr_page`` database under ``.tmp/``."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pymupdf

from reality_engine.pilot3 import comparatives as cmp
from reality_engine.pilot3 import schema
from reality_engine.v2 import page_words as pw

TMP = Path(".tmp/test_t208r3")
COLS = (200.0, 260.0, 320.0, 380.0, 440.0, 500.0)
DATES = ("30.09.2026", "30.06.2026", "30.09.2025", "30.09.2026", "30.09.2025", "31.03.2026")


def _w(x1: float, text: str, y: float) -> tuple:
    return (x1 - 7.0 * len(text), y - 3.0, x1, y + 3.0, text, 0, 0, 0)


def _row(y: float, label: str, values=()) -> list[tuple]:
    words, x = [], 20.0
    for word in label.split():
        width = 7.0 * len(word)
        words.append((x, y - 3.0, x + width, y + 3.0, word, 0, 0, 0))
        x += width + 3.0
    words += [_w(anchor, text, y) for anchor, text in zip(COLS, values)]
    return words


def _page(rows, unit="Rs. in million", title="Statement of Consolidated Unaudited Financial Results") -> list:
    words = [(40.0, 5.0, 120.0, 13.0, title, 0, 0, 0), (40.0, 15.0, 110.0, 23.0, unit, 0, 0, 0)]
    words += [_w(COLS[i], text, 30.0) for i, text in enumerate(DATES)]
    for i, (label, values) in enumerate(rows):
        words += _row(50.0 + 10.0 * i, label, values)
    return cmp.rows_from_words(words)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE company (symbol TEXT, isin TEXT, isin_from TEXT, isin_to TEXT, isin_source TEXT, bse_code TEXT, name TEXT);
        CREATE TABLE fin_quarter_xbrl (symbol TEXT, isin TEXT, period_start TEXT, period_end TEXT, fiscal_period TEXT,
            basis TEXT, audited TEXT, statement TEXT, line_item TEXT, xbrl_tag TEXT, value REAL, unit TEXT, scale REAL,
            source_file TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT, known_at TEXT, known_at_source TEXT,
            is_reported INTEGER);
        CREATE TABLE share_capital (symbol TEXT, isin TEXT, as_of_date TEXT, basis TEXT, event TEXT, ratio TEXT,
            shares_outstanding REAL, paid_up_capital REAL, face_value REAL, unit TEXT, scale REAL, known_at TEXT,
            known_at_source TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT, isin_effective_from TEXT,
            isin_effective_to TEXT);
        CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, isin TEXT, doc_type TEXT, doc_family TEXT, title TEXT,
            filing_date TEXT, known_at TEXT, pages INTEGER, sha256 TEXT, source TEXT, source_key TEXT);
    """)
    conn.execute("INSERT INTO company (symbol, isin, isin_from) VALUES ('AAAA', 'INE000A01001', '2019-01-01')")
    schema.ensure(conn, (cmp.TABLE,))
    return conn


def _stored(conn, table, page=6, ocr=False) -> list[tuple]:
    return cmp._table_rows(conn, "AAAA", "INE000A01001", "doc1", page, "2026-10-20T12:00:00", table,
                           cmp.xbrl_index(conn, "AAAA"), [], ocr=ocr)


P9_ROWS = [
    ("1 Revenue from operations", ("21,051", "16,222", "17,991", "37,273", "32,492", "66,462")),
    ("2 Other income", ("342", "261", "348", "603", "669", "1,835")),
    ("3 Total income", ("21,393", "16,483", "18,344", "37,876", "33,161", "68,297")),
    ("4 Total expenses", ("17,885", "15,726", "16,893", "33,611", "32,342", "65,545")),
    ("5 Profit before exceptional items and tax", ("3,508", "757", "1,451", "4,265", "819", "2,752")),
    ("6 Total tax expense", ("877", "192", "369", "1,069", "211", "2,508")),
    ("7 Profit for the period", ("2,631", "565", "1,082", "3,196", "608", "1,761")),
    ("8 Basic earnings per share", ("26.82", "5.75", "11.03", "32.57", "10.78", "26.34")),
]


def _cells(rows, item, role):
    return [r for r in rows if r[9] == item and r[6] == role]


# ---------------------------------------------------------------- (i) wrapped labels ------------------------------------------------
def test_wrapped_label_is_joined_before_it_matches():
    """A label printed over two lines names the row: the numbers belong to the whole label, not the continuation."""
    rows = [("1 Revenue from operations", ("1,000", "900", "800", "1,900", "1,700", "3,500")),
            ("2 Other income", ("100", "90", "80", "190", "170", "350")),
            ("3 Total income", ("1,100", "990", "880", "2,090", "1,870", "3,850")),
            ("4 Total expenses", ("800", "720", "640", "1,520", "1,360", "2,800")),
            ("5 Profit before exceptional items", ()),
            ("and tax (1-2)", ("300", "270", "240", "570", "510", "1,050")),
            ("6 Total tax expense", ("75", "67", "60", "142", "127", "262")),
            ("7 Profit for the period", ("225", "203", "180", "428", "383", "788")),
            ("8 Basic earnings per share", ("10.5", "9.5", "8.4", "20.0", "17.9", "36.8"))]
    table = cmp.read_page(_page(rows))
    assert table is not None
    # "and tax" alone names nothing; the joined label names pbt_before_exceptional
    assert "pbt_before_exceptional" in table["values"][0]
    assert table["values"][0]["pbt_before_exceptional"][0]["text"] == "300"


def test_wrapped_profit_line_is_not_the_exceptional_line():
    """p9 prints "Profit before share in net profit /(loss) of joint venture," then "exceptional items and tax
    (1-2) 3,511": the continuation alone must not become exceptional_items."""
    rows = [("1 Revenue from operations", ("21,051", "16,222", "17,991", "37,273", "32,492", "66,462")),
            ("2 Other income", ("342", "261", "348", "603", "669", "1,835")),
            ("3 Total income", ("21,393", "16,483", "18,344", "37,876", "33,161", "68,297")),
            ("4 Total expenses", ("17,885", "15,726", "16,893", "33,611", "32,342", "65,545")),
            ("Profit before share in net profit /(loss) of joint venture,", ()),
            ("exceptional items and tax (1-2)", ("3,511", "756", "1,453", "4,267", "822", "2,757")),
            ("5 Profit before exceptional items and tax (3+4)", ("3,508", "757", "1,451", "4,265", "819", "2,752")),
            ("6 Total tax expense", ("877", "192", "369", "1,069", "211", "2,508")),
            ("7 Profit for the period", ("2,631", "565", "1,082", "3,196", "608", "1,761")),
            ("8 Basic earnings per share", ("26.82", "5.75", "11.03", "32.57", "10.78", "26.34"))]
    table = cmp.read_page(_page(rows))
    assert table is not None
    assert "exceptional_items" not in table["values"][0]
    stored = _stored(_conn(), table, ocr=False)
    assert not [r for r in stored if r[9] == "exceptional_items"]
    assert _cells(stored, "pbt_before_exceptional", "current")[0][11] == 3508 * 1e6


# ---------------------------------------------------------------- (ii) dictionary threshold -----------------------------------------
def test_a_page_the_label_dictionary_scores_low_takes_its_ocr_words():
    TMP.mkdir(parents=True, exist_ok=True)
    garbled = [f"Zxv{i}omer Qlarton{i} Vroptex" for i in range(15)]     # 45 vowel-carrying non-words
    pdf_path = TMP / "garbled.pdf"
    doc = pymupdf.open()
    doc.new_page()
    for line_no, text in enumerate(garbled):
        doc[0].insert_text((40, 40 + 10 * line_no), text)
    doc.save(str(pdf_path))
    doc.close()

    pdf_words = pw.pdf_words(pdf_path, 1)
    verdict = pw.dictionary_score(pdf_words)
    assert verdict is not None and verdict["scored"] >= 30
    assert verdict["share"] < pw.DICTIONARY_SCORE_THRESHOLD
    assert pw.quality(pdf_words)[0] == "jumbled"

    ocr_db = TMP / "garbled_ocr.db"
    ocr_db.unlink(missing_ok=True)
    con = sqlite3.connect(str(ocr_db))
    con.executescript("""CREATE TABLE ocr_page (symbol TEXT, doc_key TEXT, page INTEGER, doc_type TEXT,
        known_at TEXT, text TEXT, words_json TEXT, ocr_conf REAL, n_boxes INTEGER, dpi INTEGER, seconds REAL,
        method TEXT);""")
    ocr_words = [[5.0, 5.0, 40.0, 15.0, "Revenue", 0.9], [45.0, 5.0, 80.0, 15.0, "21,051", 0.95]]
    con.execute("INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAAA", "garbled.pdf", 1, "results", "2026-10-20", "Revenue 21,051", json.dumps(ocr_words),
                 0.9, 2, 300, 1.0, "ocr_textrec"))
    con.commit()
    con.close()

    store_db = TMP / "garbled_store.db"
    store_db.unlink(missing_ok=True)
    scon = sqlite3.connect(str(store_db))
    scon.executescript("CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, source_key TEXT);")
    scon.execute("INSERT INTO doc VALUES (?,?,?)", ("garbled.pdf", "AAAA", str(pdf_path)))
    scon.commit()
    scon.close()

    got = pw.words_for(str(store_db), "garbled.pdf", 1, [str(ocr_db)])
    assert got.source == "ocr_textrec"
    assert [w[4] for w in got.words] == ["Revenue", "21,051"]


# ---------------------------------------------------------------- (iii) arithmetic gate ---------------------------------------------
def test_an_ocr_figure_that_breaks_the_arithmetic_is_not_stored():
    """The OCR reads 21,051 as "1,051"; 1,051 + 342 is not 21,393, so that figure is never stored -- the revenue
    derived from the figures that do reconcile is."""
    rows = [(label, ("1,051" if label.startswith("1 ") else values[0],) + values[1:])
            for label, values in P9_ROWS]
    table = cmp.read_page(_page(rows), ocr=True)
    assert table is not None
    stored = _stored(_conn(), table, ocr=True)
    revenue = _cells(stored, "revenue_from_operations", "current")
    assert all(r[11] != 1051 * 1e6 for r in stored)
    assert revenue and revenue[0][11] == (21393 - 342) * 1e6
    assert revenue[0][20] == "sum_ok"
    assert revenue[0][22] == 0            # derived, not printed: no row beat a wrong row


# ---------------------------------------------------------------- (iv) truncated label ---------------------------------------------
TRUNCATED = [
    ("1 Revenue fro", ("20,620", "15,822", "7,577", "36,442", "15,306", "64,462")),
    ("2 Other income", ("287", "224", "337", "511", "649", "1,770")),
    ("3 Total income", ("20,907", "16,046", "17,914", "36,953", "15,955", "66,232")),
    ("4 Total expenses", ("17,522", "15,355", "16,523", "32,877", "31,247", "63,148")),
    ("5 Profit before exceptional items and tax", ("3,385", "691", "1,391", "4,076", "708", "3,084")),
    ("6 Total tax expense", ("853", "175", "352", "1,028", "181", "649")),
    ("7 Profit for the period", ("2,532", "516", "1,039", "3,048", "527", "2,685")),
    ("8 Basic earnings per share", ("23.72", "3.21", "10.53", "30.96", "5.34", "27.23")),
]


def test_a_truncated_ocr_label_is_kept_only_when_its_figure_reconciles():
    """"Revenue fro" matches the start of "revenue from operations", but the figure behind it enters only when the
    page's arithmetic confirms it (20,620 + 287 = 20,907)."""
    table = cmp.read_page(_page(TRUNCATED), ocr=True)
    assert table is not None
    stored = _stored(_conn(), table, ocr=True)
    revenue = _cells(stored, "revenue_from_operations", "current")
    assert revenue and revenue[0][11] == 20620 * 1e6
    assert revenue[0][20] == "sum_ok"
    assert revenue[0][14] == "20,620"      # the printed figure, not a derived one


def test_a_truncated_ocr_label_whose_figure_does_not_reconcile_stores_no_row():
    rows = [("1 Revenue fro", ("1,051",) + TRUNCATED[0][1][1:])] + TRUNCATED[1:]
    table = cmp.read_page(_page(rows), ocr=True)
    assert table is not None
    stored = _stored(_conn(), table, ocr=True)
    assert all(r[11] != 1051 * 1e6 for r in stored)
    revenue = _cells(stored, "revenue_from_operations", "current")
    assert revenue[0][11] == (20907 - 287) * 1e6     # total income - other income, the page's own arithmetic
    assert revenue[0][14] != "1,051"
