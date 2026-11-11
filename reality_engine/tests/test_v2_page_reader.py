import sqlite3
import uuid
from pathlib import Path

import pymupdf

from reality_engine.v2 import page_reader as pr
from reality_engine.v2 import reference_pages as rp

BASE = Path(".tmp/test_page_reader")


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
        y += 20
    doc.save(str(path))
    doc.close()
    return path


def _store(base, pdf, text, doc_type="results", doc_key="dk"):
    db = base / "store.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, doc_type TEXT, known_at TEXT, pages INTEGER, source_key TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT, method TEXT, PRIMARY KEY (doc_key, page))")
    con.execute("INSERT INTO doc VALUES (?,?,?,?,?,?)", (doc_key, "SYM", doc_type, "2026-01-01", 1, str(pdf)))
    con.execute("INSERT INTO doc_page VALUES (?,?,?,?)", (doc_key, 1, text, "script_text"))
    con.commit()
    con.close()
    return db


GRID = ("TABLE: P&L\nUNIT: Rs\nCOLUMNS: Q2FY26 | Q1FY26\n"
        "Revenue | 100 | 200\nProfit | 40 | 30")


def _table_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((120, 72), "Q2FY26")
    page.insert_text((180, 72), "Q1FY26")
    page.insert_text((72, 92), "Revenue")
    page.insert_text((120, 92), "100")
    page.insert_text((180, 92), "200")
    page.insert_text((72, 112), "Profit")
    page.insert_text((120, 112), "40")
    page.insert_text((180, 112), "30")
    doc.save(str(path))
    doc.close()
    return path


def test_table_page_read_and_stored(monkeypatch):
    base = _base()
    pdf = _table_pdf(base / "t.pdf")
    text = "Q2FY26 Q1FY26 Revenue 100 200 Profit 40 30 " + " ".join(str(i) for i in range(1, 12))
    db = _store(base, pdf, text)
    out = base / "out.db"
    monkeypatch.setattr(rp, "_model_call", lambda reader, prompt, image_b64: {
        "output": GRID, "seconds": 1.0, "in_tok": 10, "out_tok": 20, "error": None})
    rc = pr.main(["--store", str(db), "--out", str(out), "--reader", "nvidia/nemotron-3.5-super-vl:free", "--workers", "1"])
    assert rc == 0
    con = sqlite3.connect(str(out))
    statuses = [r[0] for r in con.execute("SELECT status FROM page_read").fetchall()]
    assert statuses == ["read"]
    cells = con.execute("SELECT status FROM page_cell").fetchall()
    assert any(r[0] == "verified" for r in cells)
    con.close()


def test_prose_page_no_table_no_model_call(monkeypatch):
    base = _base()
    pdf = _pdf(base / "p.pdf", ["Para 10 20 30 40 50 60 70 80 90 100"])
    text = "Para 10 20 30 40 50 60 70 80 90 100"
    db = _store(base, pdf, text)
    out = base / "out.db"
    calls = {"n": 0}

    def fake(reader, prompt, image_b64):
        calls["n"] += 1
        return {"output": "", "seconds": 0.0, "in_tok": 0, "out_tok": 0, "error": None}

    monkeypatch.setattr(rp, "_model_call", fake)
    rc = pr.main(["--store", str(db), "--out", str(out), "--reader", "nvidia/nemotron-3.5-super-vl:free", "--workers", "1"])
    assert rc == 0
    assert calls["n"] == 0
    con = sqlite3.connect(str(out))
    statuses = [r[0] for r in con.execute("SELECT status FROM page_read").fetchall()]
    assert statuses == ["no_table"]
    con.close()


def test_second_pass_adds_missed_row(monkeypatch):
    base = _base()
    lines = ["Line1 1 2", "Line2 3 4", "Line3 5 6", "Line4 7 8", "Line5 9 10", "Line6 11 12"]
    pdf = _pdf(base / "t.pdf", lines)
    text = " ".join(lines) + " " + " ".join(str(i) for i in range(1, 20))
    db = _store(base, pdf, text)
    out = base / "out.db"

    first = "TABLE: P&L\nUNIT: Rs\nCOLUMNS: Q2 | Q1\nLine1 | 1 | 2"
    full = ("TABLE: P&L\nUNIT: Rs\nCOLUMNS: Q2 | Q1\n" +
            "\n".join(f"Line{i} | {i*2-1} | {i*2}" for i in range(1, 7)))
    calls = {"n": 0}

    def fake(reader, prompt, image_b64):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"output": first, "seconds": 1.0, "in_tok": 10, "out_tok": 20, "error": None}
        return {"output": full, "seconds": 1.0, "in_tok": 10, "out_tok": 20, "error": None}

    monkeypatch.setattr(rp, "_model_call", fake)
    rc = pr.main(["--store", str(db), "--out", str(out), "--reader", "nvidia/nemotron-3.5-super-vl:free", "--workers", "1"])
    assert rc == 0
    con = sqlite3.connect(str(out))
    passes = con.execute("SELECT passes FROM page_read").fetchone()[0]
    cells = con.execute("SELECT COUNT(*) FROM page_cell").fetchone()[0]
    assert passes == 2
    assert cells >= 10
    con.close()


def test_resume_skips_already_read(monkeypatch):
    base = _base()
    pdf = _pdf(base / "t.pdf", ["Revenue 100 200", "Profit 40 30"])
    text = "Revenue 100 200 Profit 40 30 " + " ".join(str(i) for i in range(1, 12))
    db = _store(base, pdf, text)
    out = base / "out.db"
    calls = {"n": 0}

    def fake(reader, prompt, image_b64):
        calls["n"] += 1
        return {"output": GRID, "seconds": 1.0, "in_tok": 10, "out_tok": 20, "error": None}

    monkeypatch.setattr(rp, "_model_call", fake)
    pr.main(["--store", str(db), "--out", str(out), "--reader", "nvidia/nemotron-3.5-super-vl:free", "--workers", "1"])
    first_calls = calls["n"]
    pr.main(["--store", str(db), "--out", str(out), "--reader", "nvidia/nemotron-3.5-super-vl:free", "--workers", "1"])
    assert calls["n"] == first_calls
    con = sqlite3.connect(str(out))
    assert con.execute("SELECT COUNT(*) FROM page_read").fetchone()[0] == 1
    con.close()


def test_paid_reader_refused():
    base = _base()
    pdf = _pdf(base / "t.pdf", ["Revenue 100 200"])
    db = _store(base, pdf, "Revenue 100 200")
    out = base / "out.db"
    try:
        pr.main(["--store", str(db), "--out", str(out), "--reader", "muse-spark-1.3-contributor", "--workers", "1"])
        raised = False
    except SystemExit:
        raised = True
    assert raised
