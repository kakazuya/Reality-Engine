"""T-189: routed page reading. Every page goes to exactly one route; a page that prints no
figures never reaches a reader, a jumbled text layer asks for OCR, and a table/chart page is
read by the page reader (from its image when ``--input image``)."""
import sqlite3
import uuid
from pathlib import Path

import pymupdf

from reality_engine.pilot3 import hp_ocr
from reality_engine.v2 import page_reader as pr
from reality_engine.v2 import page_route as route

BASE = Path(".tmp/test_page_route")


def _base():
    BASE.mkdir(parents=True, exist_ok=True)
    d = BASE / uuid.uuid4().hex
    d.mkdir()
    return d


def _pdf(path, lines):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line)
        y += 18
    doc.save(str(path))
    doc.close()
    return path


def _store(base, name, pdf, text, doc_type="results", doc_key=None):
    key = doc_key or name
    db = base / f"{name}.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, doc_type TEXT, known_at TEXT, "
                "pages INTEGER, source_key TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT, method TEXT, "
                "PRIMARY KEY (doc_key, page))")
    con.execute("INSERT INTO doc VALUES (?,?,?,?,?,?)", (key, "SYM", doc_type, "2026-01-01", 1, str(pdf)))
    con.execute("INSERT INTO doc_page VALUES (?,?,?,?)", (key, 1, text, "script_text"))
    con.commit()
    con.close()
    return db


COVER = ["Dear Sir/Madam,", "Sub: Intimation of the Board Meeting",
         "Pursuant to Regulation 30 of the SEBI (LODR) Regulations, 2015, we wish to inform you that the",
         "Board meeting will be held on 12 November 2026 at 3.00 p.m. at the registered office.",
         "Kindly take the above on record.", "Company Secretary"]
CONTENTS = ["Table of Contents", "Business overview .......... 5", "Financial review .......... 12",
            "Risk management .......... 18", "Corporate governance .......... 25"]
PROSE = ["Revenue grew from 100 to 120 in the quarter while profit after tax was 45.",
         "Margins improved 12.5 percent on lower input cost and the outlook stays positive.",
         "Management said the order pipeline is healthy for the coming year."]
TABLE_LINES = ["Q2FY26", "Q1FY26", "Revenue", "100", "200", "Profit", "40", "30"]
JUMBLE = ["XKCDQW RTYPSD MNBVCZ WQRTPS KLMNZ",
          "BDFGH JKLMN PQRS TVWX YZBCD",
          "Revenue 100 200 Profit 40 30"]


def _decide(base, name, lines, text):
    pdf = _pdf(base / f"{name}.pdf", lines)
    db = _store(base, name, pdf, text)
    return route.route_page(str(db), name, 1, [])


def test_routes():
    base = _base()
    assert _decide(base, "cover", COVER, " ".join(COVER))[0] == "no_figures"
    assert _decide(base, "contents", CONTENTS, " ".join(CONTENTS))[0] == "no_figures"
    assert _decide(base, "prose", PROSE, " ".join(PROSE))[0] == "text_ok"
    assert _decide(base, "table", TABLE_LINES,
                   "Q2FY26 Q1FY26 Revenue 100 200 Profit 40 30")[0] == "table_or_chart"
    assert _decide(base, "jumble", JUMBLE, " ".join(JUMBLE))[0] == "needs_ocr"


def test_image_page_with_numbers_is_table_or_chart():
    base = _base()
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Revenue 100 200 Profit 40 30 and the chart below shows the trend over time.")
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300))
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(72, 120, 472, 420), pixmap=pix)
    pdf = base / "img.pdf"
    doc.save(str(pdf))
    doc.close()
    text = "Revenue 100 200 Profit 40 30 and the chart below shows the trend over time."
    db = _store(base, "img", pdf, text)
    assert route.route_page(str(db), "img", 1, [])[0] == "table_or_chart"


def test_needs_ocr_export_maps_back_through_hp_ocr_plan():
    base = _base()
    pdf = _pdf(base / "j.pdf", JUMBLE)
    db = _store(base, "j", pdf, " ".join(JUMBLE), doc_key="a/b:jumbled")
    out = base / "routes.csv"
    export = base / "export"
    assert route.main(["--store", str(db), "--out", str(out), "--needs-ocr-pdf-dir", str(export)]) == 0
    assert [p.name for p in export.glob("*.pdf")] == ["a_b_jumbled__p1.pdf"]
    plan = hp_ocr.pdf_dir_plan(export)
    assert [(r["doc_key"], r["page"]) for r in plan] == [("a/b:jumbled", 1)]


def test_write_words_accepts_a_routed_doc_key():
    """A routed page's id carries a real doc_key: the word file name is safe and the log still names the page."""
    import csv
    import json

    base = _base()
    rows = [{"id": "frozen2|a/b:jumbled|7", "seconds": 1.0, "error": None,
             "line_rows": [{"words": [{"text": "Revenue", "confidence": 0.9, "box": [300, 300, 600, 360]}]}]}]
    report = hp_ocr.write_words(rows, base / "words")
    assert report["pages"] == 1
    log = list(csv.DictReader((base / "words" / "ocr_log.csv").open(encoding="utf-8")))
    assert (log[0]["page_id"], log[0]["file"]) == ("a/b:jumbled", "a_b_jumbled.json")
    assert json.loads((base / "words" / "a_b_jumbled.json").read_text(encoding="utf-8"))[0][4] == "Revenue"


def test_reader_accepts_only_table_or_chart_routes(monkeypatch):
    """--routes sends the table_or_chart page to the reader and leaves the text_ok page alone."""
    base = _base()
    table_db = _store(base, "t", _pdf(base / "t.pdf", TABLE_LINES), "Q2FY26 Q1FY26 Revenue 100 200 Profit 40 30")
    prose = _store(base, "p", _pdf(base / "p.pdf", PROSE), " ".join(PROSE))
    # one store with both pages
    store = base / "store.db"
    con = sqlite3.connect(str(store))
    con.execute("CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, doc_type TEXT, known_at TEXT, "
                "pages INTEGER, source_key TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT, method TEXT, "
                "PRIMARY KEY (doc_key, page))")
    for db, key, text_lines, text in ((table_db, "t", TABLE_LINES, "Q2FY26 Q1FY26 Revenue 100 200 Profit 40 30"),
                                      (prose, "p", PROSE, " ".join(PROSE))):
        src = sqlite3.connect(str(db))
        sk = src.execute("SELECT source_key FROM doc").fetchone()[0]
        src.close()
        con.execute("INSERT INTO doc VALUES (?,?,?,?,?,?)", (key, "SYM", "results", "2026-01-01", 1, sk))
        con.execute("INSERT INTO doc_page VALUES (?,?,?,?)", (key, 1, text, "script_text"))
    con.commit()
    con.close()
    routes_csv = base / "routes.csv"
    rows = [{"doc_key": "t", "page": 1, "doc_type": "results", "route": "table_or_chart", "reason": "",
             "word_source": "", "quality": ""},
            {"doc_key": "p", "page": 1, "doc_type": "results", "route": "text_ok", "reason": "",
             "word_source": "", "quality": ""}]
    import csv
    with routes_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    calls = {"n": 0}

    def fake(reader, prompt, image_b64):
        calls["n"] += 1
        return {"output": "TABLE: P&L\nUNIT: Rs\nCOLUMNS: Q2FY26 | Q1FY26\nRevenue | 100 | 200\nProfit | 40 | 30",
                "seconds": 1.0, "in_tok": 10, "out_tok": 20, "error": None}

    monkeypatch.setattr(pr.rp, "_model_call", fake)
    rc = pr.main(["--store", str(store), "--out", str(base / "out.db"), "--routes", str(routes_csv),
                  "--reader", "nvidia/nemotron-3.5-super-vl:free", "--workers", "1"])
    assert rc == 0
    assert calls["n"] == 1
    con = sqlite3.connect(str(base / "out.db"))
    assert con.execute("SELECT doc_key, status FROM page_read").fetchall() == [("t", "read")]
    con.close()


def test_input_image_sends_the_page_image(monkeypatch):
    base = _base()
    db = _store(base, "t", _pdf(base / "t.pdf", TABLE_LINES), "Q2FY26 Q1FY26 Revenue 100 200 Profit 40 30")
    seen = {}

    def fake(reader, prompt, image_b64):
        seen["image"] = image_b64
        return {"output": "TABLE: P&L\nUNIT: Rs\nCOLUMNS: Q2FY26 | Q1FY26\nRevenue | 100 | 200\nProfit | 40 | 30",
                "seconds": 1.0, "in_tok": 10, "out_tok": 20, "error": None}

    monkeypatch.setattr(pr.rp, "_model_call", fake)
    out = base / "out.db"
    assert pr.main(["--store", str(db), "--out", str(out), "--input", "image",
                    "--reader", "nvidia/nemotron-3.5-super-vl:free", "--workers", "1"]) == 0
    assert seen["image"]                            # the page image, not only layout text
    con = sqlite3.connect(str(out))
    assert con.execute("SELECT input FROM page_read").fetchone()[0] == "image_layout"
    con.close()


def test_three_tries_then_error(monkeypatch):
    base = _base()
    db = _store(base, "t", _pdf(base / "t.pdf", TABLE_LINES), "Q2FY26 Q1FY26 Revenue 100 200 Profit 40 30")
    calls = {"n": 0}

    def fake(reader, prompt, image_b64):
        calls["n"] += 1
        return {"output": "", "seconds": 0.0, "in_tok": 0, "out_tok": 0, "error": "HTTP 429: rate limit"}

    monkeypatch.setattr(pr.rp, "_model_call", fake)
    monkeypatch.setattr(pr.time, "sleep", lambda seconds: None)
    out = base / "out.db"
    assert pr.main(["--store", str(db), "--out", str(out), "--reader",
                    "nvidia/nemotron-3.5-super-vl:free", "--workers", "1"]) == 0
    assert calls["n"] == 3
    con = sqlite3.connect(str(out))
    assert con.execute("SELECT status FROM page_read").fetchone()[0] == "error"
    con.close()
