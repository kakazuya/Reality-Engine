import csv
import sqlite3
import uuid
from pathlib import Path

import pymupdf
from PIL import Image

from reality_engine.v2 import page_reader as pr
from reality_engine.v2 import reference_pages as rp

BASE = Path(".tmp/test_page_reader")
FREE = "nvidia/nemotron-3.5-super-vl:free"


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
    dup = con.execute("SELECT COUNT(*) FROM (SELECT x0, y0 FROM page_cell WHERE x0 IS NOT NULL "
                      "GROUP BY x0, y0 HAVING COUNT(*) > 1)").fetchone()[0]
    assert dup == 0                                   # a printed word is one cell even when both passes give it
    assert con.execute("SELECT COUNT(*) FROM page_cell WHERE table_title<>''").fetchone()[0] > 0
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


# --- T-199: export for a Haiku file reader, and the file reader itself -----------------------------------------
def _multi_pdf(path, pages):
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        y = 72
        for line in lines:
            page.insert_text((72, y), line)
            y += 20
    doc.save(str(path))
    doc.close()
    return path


def _doc_store(base, docs):
    """docs: [(doc_key, doc_type, known_at, pdf, [(page, text, method), ...]), ...]."""
    db = base / "store.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, doc_type TEXT, known_at TEXT, "
                "pages INTEGER, source_key TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT, method TEXT, "
                "PRIMARY KEY (doc_key, page))")
    for doc_key, doc_type, known_at, pdf, pages in docs:
        con.execute("INSERT INTO doc VALUES (?,?,?,?,?,?)",
                    (doc_key, "SYM", doc_type, known_at, len(pages), str(pdf)))
        for page, text, method in pages:
            con.execute("INSERT INTO doc_page VALUES (?,?,?,?)", (doc_key, page, text, method))
    con.commit()
    con.close()
    return db


def _routes(base, rows):
    path = base / "routes.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["doc_key", "page", "doc_type", "route", "reason",
                                                "word_source", "quality"])
        writer.writeheader()
        for row in rows:
            writer.writerow({**{name: "" for name in writer.fieldnames}, **row})
    return path


def _cell_rows(con):
    """The printed cells without the ``reader`` column: the two readers are named differently by design."""
    return sorted(con.execute("SELECT doc_key, page, symbol, known_at, table_title, row_label, col_header, "
                              "value_text, unit_text, status, conflict, x0, y0, x1, y1 FROM page_cell").fetchall())


def test_export_writes_eight_page_batches_the_image_and_the_read_page_prompt(monkeypatch):
    base = _base()
    texts = [f"Q2FY26 Revenue {100 + i} Profit {40 + i}" for i in range(9)]
    pdf = _multi_pdf(base / "multi.pdf", [[text] for text in texts])
    db = _doc_store(base, [("dk", "deck", "2026-08-10T17:00:00", pdf,
                            [(i + 1, texts[i], "script_text") for i in range(9)])])
    routes = _routes(base, [{"doc_key": "dk", "page": page, "doc_type": "deck", "route": "table_or_chart"}
                            for page in range(1, 10)])
    out_dir = base / "reads"
    summary = pr.export_pages(db, routes, out_dir, batch=8)
    assert summary == {"pages": 9, "exported": 9, "duplicates": 0, "batches": 2, "no_image": 0}
    assert len(list((out_dir / "b001").glob("*.jpg"))) == 8
    assert len(list((out_dir / "b002").glob("*.jpg"))) == 1
    manifest = list(csv.DictReader((out_dir / "manifest.csv").open(newline="", encoding="utf-8")))
    assert len(manifest) == 9
    assert {row["batch"] for row in manifest} == {"b001", "b002"}
    assert manifest[0]["doc_key"] == "dk" and manifest[0]["doc_type"] == "deck"
    assert all(row["img_scale"] for row in manifest)
    with Image.open(out_dir / "b001" / f"{manifest[0]['stem']}.jpg") as image:
        assert max(image.size) == 1280
    assert float(manifest[0]["img_scale"]) > 1.0

    prompts: list[str] = []

    def fake(reader, prompt, image_b64):
        prompts.append(prompt)
        return {"output": "TABLE: R\nUNIT: Rs\nCOLUMNS: Q2FY26\nRevenue | 100", "seconds": 0.0,
                "in_tok": 0, "out_tok": 0, "error": None}

    monkeypatch.setattr(rp, "_model_call", fake)
    assert pr.main(["--store", str(db), "--out", str(base / "read.db"), "--routes", str(routes),
                    "--reader", FREE, "--workers", "1"]) == 0
    exported = [(out_dir / "b001" / f"{manifest[0]['stem']}.prompt.txt").read_text(encoding="utf-8"),
                (out_dir / "b002" / f"{manifest[-1]['stem']}.prompt.txt").read_text(encoding="utf-8")]
    for prompt in exported:
        assert prompt in prompts, "the exported prompt is exactly what read_page sends"


def test_export_filters_doc_types_and_includes_needs_ocr_pages():
    base = _base()
    decks = _multi_pdf(base / "decks.pdf", [["Q2FY26 Revenue 100 Profit 40"], ["Scan only 1 2 3 4 5"]])
    transcript = _pdf(base / "call.pdf", ["Q2FY26 Revenue 200 Profit 50"])
    db = _doc_store(base, [
        ("deck1", "deck", "2026-08-10T17:00:00", decks,
         [(1, "Q2FY26 Revenue 100 Profit 40", "script_text"), (2, "", "needs_ocr")]),
        ("call1", "transcript", "2026-08-11T17:00:00", transcript,
         [(1, "Q2FY26 Revenue 200 Profit 50", "script_text")])])
    routes = _routes(base, [
        {"doc_key": "deck1", "page": 1, "doc_type": "deck", "route": "table_or_chart"},
        {"doc_key": "deck1", "page": 2, "doc_type": "deck", "route": "needs_ocr"},
        {"doc_key": "call1", "page": 1, "doc_type": "transcript", "route": "table_or_chart"}])
    out_dir = base / "reads"
    summary = pr.export_pages(db, routes, out_dir, doc_types=["deck"])
    assert summary["exported"] == 2
    manifest = list(csv.DictReader((out_dir / "manifest.csv").open(newline="", encoding="utf-8")))
    assert {row["doc_key"] for row in manifest} == {"deck1"}
    assert {pr.page_stem("deck1", 2)} <= {row["stem"] for row in manifest}


def test_export_dedupes_identical_page_text_keeps_the_earliest_and_lists_the_duplicate():
    base = _base()
    first = _pdf(base / "a.pdf", ["Revenue 100 200"])
    second = _pdf(base / "b.pdf", ["Revenue 100 200"])
    third = _pdf(base / "c.pdf", ["Profit 40 30"])
    fourth = _pdf(base / "d.pdf", ["Loss 5 6"])
    db = _doc_store(base, [
        ("a", "results", "2026-01-05T17:00:00", first, [(1, "Revenue 100 200", "script_text")]),
        ("b", "announcement", "2026-02-05T17:00:00", second, [(1, "Revenue   100\n200 ", "script_text")]),
        ("c", "results", "2026-03-05T17:00:00", third, [(1, "", "needs_ocr")]),
        ("d", "results", "2026-04-05T17:00:00", fourth, [(1, "   ", "needs_ocr")])])
    routes = _routes(base, [{"doc_key": key, "page": 1, "doc_type": doc_type, "route": "table_or_chart"}
                            for key, doc_type in (("a", "results"), ("b", "announcement"),
                                                  ("c", "results"), ("d", "results"))])
    out_dir = base / "reads"
    summary = pr.export_pages(db, routes, out_dir)
    assert summary["pages"] == 4
    assert summary["exported"] == 3                     # b is a duplicate of a; the two text-less pages stay
    assert summary["duplicates"] == 1
    manifest = list(csv.DictReader((out_dir / "manifest.csv").open(newline="", encoding="utf-8")))
    assert {row["doc_key"] for row in manifest} == {"a", "c", "d"}
    duplicates = list(csv.DictReader((out_dir / "duplicates.csv").open(newline="", encoding="utf-8")))
    assert duplicates == [{"canonical_doc_key": "a", "canonical_page": "1",
                           "duplicate_doc_key": "b", "duplicate_page": "1"}]


def test_a_file_reader_gives_the_same_cells_as_the_same_reply_through_a_model(monkeypatch):
    base = _base()
    pdf = _table_pdf(base / "t.pdf")
    text = "Q2FY26 Q1FY26 Revenue 100 200 Profit 40 30 " + " ".join(str(i) for i in range(1, 12))
    db = _store(base, pdf, text)
    routes = _routes(base, [{"doc_key": "dk", "page": 1, "doc_type": "results", "route": "table_or_chart"}])
    out_dir = base / "reads"
    pr.export_pages(db, routes, out_dir)
    (out_dir / "b001" / f"{pr.page_stem('dk', 1)}.reply.txt").write_text(GRID, encoding="utf-8")
    file_db = base / "file.db"
    assert pr.main(["--store", str(db), "--out", str(file_db), "--routes", str(routes),
                    "--reader", f"file:{out_dir}", "--workers", "1"]) == 0
    fake_db = base / "fake.db"
    monkeypatch.setattr(rp, "_model_call", lambda reader, prompt, image_b64: {
        "output": GRID, "seconds": 0.0, "in_tok": 0, "out_tok": 0, "error": None})
    assert pr.main(["--store", str(db), "--out", str(fake_db), "--routes", str(routes),
                    "--reader", FREE, "--workers", "1"]) == 0
    con = sqlite3.connect(str(file_db))
    assert con.execute("SELECT reader, status, passes, cells FROM page_read").fetchone()[0:3] == \
        ("haiku_sub", "read", 1)
    assert {row[0] for row in con.execute("SELECT reader FROM page_cell")} == {"haiku_sub"}
    file_cells = _cell_rows(con)
    con.close()
    con = sqlite3.connect(str(fake_db))
    model_cells = _cell_rows(con)
    con.close()
    assert file_cells == model_cells


def test_a_missing_reply_is_an_error_never_a_guess():
    base = _base()
    pdf = _table_pdf(base / "t.pdf")
    text = "Q2FY26 Q1FY26 Revenue 100 200 Profit 40 30 " + " ".join(str(i) for i in range(1, 12))
    db = _store(base, pdf, text)
    routes = _routes(base, [{"doc_key": "dk", "page": 1, "doc_type": "results", "route": "table_or_chart"}])
    out_dir = base / "reads"
    pr.export_pages(db, routes, out_dir)                 # a session was asked, no reply file was written
    out = base / "out.db"
    assert pr.main(["--store", str(db), "--out", str(out), "--routes", str(routes),
                    "--reader", f"file:{out_dir}", "--workers", "1"]) == 0
    con = sqlite3.connect(str(out))
    status, error, cells = con.execute("SELECT status, error, cells FROM page_read").fetchone()
    con.close()
    assert status == "error" and error.startswith("no reply")
    assert cells == 0


GRID_SECTIONS = ("TABLE: Segment report\nUNIT: Rs crore\nCOLUMNS: Q2FY26 | Q1FY26\n"
                 "Segment Revenue\n"
                 "(a) Electro-mechanical projects | 100 | 90\n"
                 "Segment Result\n"
                 "(a) Electro-mechanical projects | 10 | 9\n"
                 "Total income | 250 | 240")


def test_a_section_heading_labels_a_list_marked_row_and_leaves_other_labels_alone():
    """T-199: four headings print the same "(a) Electro-mechanical projects" label; the stored row label carries
    its section so two headings are two rows.  A label printed once with no list marker keeps its old text."""
    base = _base()
    pdf = _pdf(base / "t.pdf", ["Segment Revenue", "(a) Electro-mechanical projects 100 90",
                                "Segment Result", "(a) Electro-mechanical projects 10 9",
                                "Total income 250 240"])
    text = "(a) Electro-mechanical projects 100 90 10 9 Total income 250 240"
    db = _store(base, pdf, text)
    routes = _routes(base, [{"doc_key": "dk", "page": 1, "doc_type": "results", "route": "table_or_chart"}])
    out_dir = base / "reads"
    pr.export_pages(db, routes, out_dir)
    (out_dir / "b001" / f"{pr.page_stem('dk', 1)}.reply.txt").write_text(GRID_SECTIONS, encoding="utf-8")
    out = base / "out.db"
    assert pr.main(["--store", str(db), "--out", str(out), "--routes", str(routes),
                    "--reader", f"file:{out_dir}", "--workers", "1"]) == 0
    con = sqlite3.connect(str(out))
    labels = sorted(row[0] for row in con.execute("SELECT row_label FROM page_cell"))
    con.close()
    assert "Segment Revenue > (a) Electro-mechanical projects" in labels
    assert "Segment Result > (a) Electro-mechanical projects" in labels
    assert "Total income" in labels
