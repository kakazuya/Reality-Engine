"""T-182: word boxes for any page, with text-quality verdict."""
import json
import sqlite3
from pathlib import Path

import pymupdf

from reality_engine.v2 import page_words as pw
from reality_engine.v2.page_layout import layout_text

TMP = Path(".tmp/test_page_words")


def _ensure():
    TMP.mkdir(parents=True, exist_ok=True)


def test_pdf_words_sideways_page_upright():
    _ensure()
    pdf = TMP / "sideways.pdf"
    doc = pymupdf.open()
    p0 = doc.new_page()
    p0.insert_text((72, 72), "First page plain text with enough characters")
    p1 = doc.new_page()
    p1.insert_text((100, 100), "Alpha Beta Gamma", rotate=90)
    doc.save(str(pdf))
    doc.close()

    words = pw.pdf_words(pdf, 2)
    from reality_engine.v2.reference_geom import lines_of

    lines = lines_of(words)
    assert len(lines) == 1
    ordered = [words[i][4] for i in lines[0]]
    assert ordered == ["Alpha", "Beta", "Gamma"]


def test_ocr_words_reads_real_shape():
    _ensure()
    db = TMP / "ocr.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(str(db))
    con.executescript(
        """CREATE TABLE ocr_page (symbol TEXT, doc_key TEXT, page INTEGER, doc_type TEXT,
        known_at TEXT, text TEXT, words_json TEXT, ocr_conf REAL, n_boxes INTEGER, dpi INTEGER,
        seconds REAL, method TEXT);"""
    )
    words = [[10.0, 10.0, 50.0, 20.0, "Revenue", 0.9], [60.0, 10.0, 90.0, 20.0, "100", 0.95]]
    con.execute(
        "INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("SYM", "doc.pdf", 1, "results", "2026-01-01", "Revenue 100", json.dumps(words), 0.9, 2, 300, 1.0, "ocr_textrec"),
    )
    # also a rapid row to ensure preference
    con.execute(
        "INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("SYM", "doc.pdf", 1, "results", "2026-01-01", "rapid", json.dumps([[0, 0, 1, 1, "X", 0.5]]), 0.5, 1, 300, 1.0, "ocr_rapid"),
    )
    con.commit()
    con.close()

    got = pw.ocr_words([str(db)], "doc.pdf", 1)
    assert [w[4] for w in got] == ["Revenue", "100"]
    assert len(got[0]) == 5


def test_quality_verdicts():
    ok_words = [(0, 0, 10, 10, "Revenue")] * 5 + [(0, 0, 10, 10, "profit")]
    # build enough non-space chars
    ok_words = [(0, 0, 10, 10, "Revenue")] * 3
    q, r = pw.quality(ok_words)
    # "RevenueRevenueRevenue" = 21 chars -> ok
    assert q == "ok" and r == ""

    assert pw.quality([])[0] == "none"
    assert pw.quality([(0, 0, 1, 1, "x")])[0] == "none"

    jumbled = [(0, 0, 10, 10, "bcdfg")] * 5 + [(0, 0, 10, 10, "aaaa")]
    # total 6 words, 5 no-vowel alpha4 -> share 5/6? alpha4 all 6? "aaaa" has vowel. alpha4=6, nv=5 => 0.833 >0.3
    assert pw.quality(jumbled)[0] == "jumbled"

    longw = [(0, 0, 10, 10, "a" * 30)] * 2 + [(0, 0, 10, 10, "ok")] * 3
    assert pw.quality(longw)[0] == "jumbled"

    single = [(0, 0, 10, 10, "a")] * 8 + [(0, 0, 10, 10, "word")] * 4
    assert pw.quality(single)[0] == "jumbled"


def test_words_for_falls_back_to_ocr():
    _ensure()
    pdf = TMP / "empty.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()

    db = TMP / "ocr2.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(str(db))
    con.executescript(
        """CREATE TABLE ocr_page (symbol TEXT, doc_key TEXT, page INTEGER, doc_type TEXT,
        known_at TEXT, text TEXT, words_json TEXT, ocr_conf REAL, n_boxes INTEGER, dpi INTEGER,
        seconds REAL, method TEXT);"""
    )
    words = [[5.0, 5.0, 20.0, 15.0, "OCRWord", 0.8]]
    con.execute(
        "INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("SYM", "empty.pdf", 1, "results", "2026-01-01", "OCRWord", json.dumps(words), 0.8, 1, 300, 1.0, "ocr_rapid"),
    )
    con.commit()
    con.close()

    # need doc table for source_key
    store_db = TMP / "store.db"
    if store_db.exists():
        store_db.unlink()
    scon = sqlite3.connect(str(store_db))
    scon.executescript(
        """CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, source_key TEXT);"""
    )
    scon.execute("INSERT INTO doc VALUES (?,?,?)", ("empty.pdf", "SYM", str(pdf)))
    scon.commit()
    scon.close()

    pw_result = pw.words_for(str(store_db), "empty.pdf", 1, [str(db)])
    assert pw_result.source == "ocr_rapid"
    assert [w[4] for w in pw_result.words] == ["OCRWord"]
    assert pw_result.quality in ("ok", "none", "jumbled")


def test_show_layout_text_runs():
    # smoke: layout_text on empty list
    assert layout_text([]) == ""
