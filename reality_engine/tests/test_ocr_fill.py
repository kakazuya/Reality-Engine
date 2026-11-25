"""T-242: selection, the ocr_page row, resume and the reader's method priority for the Nemotron OCR fill."""
import csv
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from reality_engine.scripts import ocr_fill as of
from reality_engine.v2 import page_words as pw

TMP = Path(".tmp/test_ocr_fill")


def _fresh(name: str) -> Path:
    path = TMP / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def _store(root: Path, name: str, routes: list[dict], docs: list[tuple]) -> Path:
    """A universe store directory: ``<name>.db`` with a doc table plus its routes.csv."""
    store_dir = root / name
    store_dir.mkdir(parents=True)
    con = sqlite3.connect(store_dir / f"{name}.db")
    con.executescript("CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, doc_type TEXT, "
                      "known_at TEXT, source_key TEXT);")
    con.executemany("INSERT INTO doc VALUES (?,?,?,?,?)", docs)
    con.commit()
    con.close()
    with (store_dir / "routes.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["doc_key", "page", "doc_type", "route", "reason",
                                                "word_source", "quality"])
        writer.writeheader()
        writer.writerows(routes)
    return store_dir


def _pdf(tmp: Path, name: str = "page.pdf") -> Path:
    import pymupdf

    path = tmp / name
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


ROUTES = [
    {"doc_key": "a.pdf", "page": 1, "doc_type": "deck", "route": "needs_ocr",
     "reason": "text layer none: fewer than 20 non-space characters; no OCR words yet", "word_source": "script_text",
     "quality": "none"},
    {"doc_key": "a.pdf", "page": 2, "doc_type": "deck", "route": "needs_ocr",
     "reason": "text layer jumbled: label-dictionary share 0.50 < 0.75", "word_source": "script_text", "quality": "none"},
    {"doc_key": "a.pdf", "page": 3, "doc_type": "deck", "route": "table_or_chart", "reason": "numbered table",
     "word_source": "script_text", "quality": "ok"},
    {"doc_key": "b.pdf", "page": 1, "doc_type": "results", "route": "needs_ocr",
     "reason": "text layer none: fewer than 20 non-space characters; no OCR words yet", "word_source": "script_text",
     "quality": "none"},
    {"doc_key": "missing.pdf", "page": 1, "doc_type": "deck", "route": "needs_ocr",
     "reason": "text layer none: fewer than 20 non-space characters; no OCR words yet", "word_source": "script_text",
     "quality": "none"},
]


def test_select_keeps_only_image_only_deck_pages():
    root = _fresh("select")
    _store(root, "c01", ROUTES, [("a.pdf", "AAA", "deck", "2026-01-01", "D:/raw/a.pdf"),
                                 ("b.pdf", "BBB", "results", "2026-01-02", "D:/raw/b.pdf")])
    pages = of.select(root)
    assert [(p["doc_key"], p["page"]) for p in pages] == [("a.pdf", 1)]
    assert pages[0]["symbol"] == "AAA"
    assert pages[0]["pdf"] == "D:/raw/a.pdf"
    assert pages[0]["store"].endswith("c01.db")


def test_select_symbol_filter_seed_and_limit():
    root = _fresh("select_filter")
    for name, symbol in (("c01", "AAA"), ("c02", "BBB")):
        _store(root, name, [dict(ROUTES[0]), {**ROUTES[0], "page": 4}],
               [("a.pdf", symbol, "deck", "2026-01-01", f"D:/raw/{name}.pdf")])
    assert [p["symbol"] for p in of.select(root, symbols=["bbb"])] == ["BBB", "BBB"]
    first = of.select(root, seed=1125, limit=3)
    assert len(first) == 3
    assert of.select(root, seed=1125, limit=3) == first
    assert of.select(root, limit=100) == sorted(of.select(root), key=lambda p: (p["store"], p["doc_key"], p["page"]))


def test_pseudo_words_one_per_line_and_reader_reads_them():
    text = "Revenue 1,234\n\nPAT 56 (7%)\nEBITDA margin 12.5%"
    words = of.pseudo_words(text)
    assert [w[4] for w in words] == ["Revenue 1,234", "PAT 56 (7%)", "EBITDA margin 12.5%"]
    assert [w[1] for w in words] == sorted(w[1] for w in words)
    assert words[0][2] == float(len("Revenue 1,234"))
    assert of.figures(text) == 4

    db = TMP / "read_shapes.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript(of.SCHEMA)
    con.execute("INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAA", "a.pdf", 1, "deck", "2026-01-01", text, json.dumps(words), None, len(words), 150, 1.0,
                 of.METHOD))
    con.commit()
    con.close()
    assert [w[4] for w in pw.ocr_words([db], "a.pdf", 1)] == [w[4] for w in words]


def test_run_writes_row_under_out_dir_only(monkeypatch):
    root = _fresh("write")
    pdf = _pdf(root)
    store_dir = _store(root / "u", "c01", [ROUTES[0]], [("a.pdf", "AAA", "deck", "2026-01-01", str(pdf))])
    pages = of.select(root / "u")
    out_dir = root / "out"
    monkeypatch.setattr(of, "render_page", lambda pdf_path, page: b"png")
    monkeypatch.setattr(of, "ask", lambda route, png, timeout=420: "Revenue 1,234\nPAT 56")
    stats = of.run(pages, ["kilo"], out_dir=out_dir, enabled={"kilo": True})

    out = out_dir / "c01_ocr.db"
    assert out.is_file()
    assert not (store_dir / "c01_ocr.db").exists()          # nothing beside the live store
    con = sqlite3.connect(f"file:{out.as_posix()}?mode=ro", uri=True)
    row = con.execute("SELECT symbol, doc_key, page, doc_type, known_at, text, words_json, ocr_conf, n_boxes, dpi, "
                      "method FROM ocr_page").fetchone()
    con.close()
    assert row[:6] == ("AAA", "a.pdf", 1, "deck", "2026-01-01", "Revenue 1,234\nPAT 56")
    assert len(json.loads(row[6])) == 2
    assert row[7] is None and row[8] == 2 and row[9] == 150 and row[10] == of.METHOD
    assert stats["written"] == 1 and stats["route"]["kilo"] == 1 and stats["pages_with_4_figures"] == 0
    assert (out_dir / "ocr_fill.jsonl").is_file()
    assert (out_dir / "samples.txt").is_file()


def test_resume_skips_and_never_overwrites_another_method(monkeypatch):
    root = _fresh("resume")
    pdf = _pdf(root)
    _store(root / "u", "c01", [ROUTES[0]], [("a.pdf", "AAA", "deck", "2026-01-01", str(pdf))])
    pages = of.select(root / "u")
    out_dir = root / "out"
    calls: list[str] = []

    def fake_ask(route, png, timeout=420):
        calls.append(route)
        return f"Revenue {len(calls)}"

    monkeypatch.setattr(of, "render_page", lambda pdf_path, page: b"png")
    monkeypatch.setattr(of, "ask", fake_ask)
    of.run(pages, ["kilo"], out_dir=out_dir, enabled={"kilo": True})
    assert calls == ["kilo"]
    first = of._held(out_dir / "c01_ocr.db")[("AAA", "a.pdf", 1)]
    assert first == of.METHOD

    stats = of.run(pages, ["kilo"], out_dir=out_dir, resume=True, enabled={"kilo": True})
    assert calls == ["kilo"] and stats["skipped"] == 1 and stats["written"] == 0

    stats = of.run(pages, ["kilo"], out_dir=out_dir, resume=False, enabled={"kilo": True})
    assert calls == ["kilo", "kilo"] and stats["written"] == 1
    con = sqlite3.connect(out_dir / "c01_ocr.db")
    assert con.execute("SELECT text FROM ocr_page").fetchone()[0] == "Revenue 2"
    con.execute("UPDATE ocr_page SET method='ocr_rapid'")
    con.commit()
    con.close()
    stats = of.run(pages, ["kilo"], out_dir=out_dir, enabled={"kilo": True})
    assert stats["skipped"] == 1 and calls == ["kilo", "kilo"]     # another reader owns the page


def test_method_priority_prefers_box_readers():
    assert pw.OCR_METHOD_PRIORITY["ocr_rapid"] < pw.OCR_METHOD_PRIORITY["ocr_nemotron_vl"]
    assert pw.OCR_METHOD_PRIORITY["ocr_textrec"] < pw.OCR_METHOD_PRIORITY["ocr_nemotron_vl"]
    db = TMP / "priority.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript(of.SCHEMA)
    con.execute("INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAA", "a.pdf", 1, "deck", "2026-01-01", "nemotron line", json.dumps(of.pseudo_words("nemotron line")),
                 None, 1, 150, 1.0, of.METHOD))
    con.commit()
    assert [w[4] for w in pw.ocr_words([db], "a.pdf", 1)] == ["nemotron line"]
    assert pw._ocr_method([db], "a.pdf", 1) == of.METHOD
    con.execute("INSERT OR REPLACE INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAA", "a.pdf", 1, "deck", "2026-01-01", "rapid box", json.dumps([[0, 0, 9, 9, "rapid box", 0.9]]),
                 0.9, 1, 300, 1.0, "ocr_rapid"))
    con.commit()
    con.close()
    assert [w[4] for w in pw.ocr_words([db], "a.pdf", 1)] == ["rapid box"]
    assert pw._ocr_method([db], "a.pdf", 1) == "ocr_rapid"


def test_shared_acl_tempdir_is_writable():
    import tempfile

    original = tempfile.mkdtemp
    with of._shared_acl_tempdirs():
        folder = Path(tempfile.mkdtemp(prefix="ocr_fill_test_"))
        (folder / "a.txt").write_text("x", encoding="utf-8")
    assert (folder / "a.txt").read_text(encoding="utf-8") == "x"
    assert tempfile.mkdtemp is original
    shutil.rmtree(folder, ignore_errors=True)


def test_free_only_guard_and_paid_cost_stop(monkeypatch):
    assert of.parse_routes("kilo,zen") == ["kilo", "zen"]
    with pytest.raises(SystemExit):
        of.parse_routes("kilo,step-5-preview@stepfun")
    assert all(cfg["id"] in of.FREE_IDS for cfg in of.FREE_ROUTES.values())
    assert of.parse_events('{"type":"step_finish","part":{"cost":0.0}}')[1] == 0.0
    assert of.parse_events('{"type":"text","part":{"text":"hello"}}\n'
                           '{"type":"step_finish","part":{"cost":0.25}}') == ("hello", 0.25, "")

    root = _fresh("paid")
    pdf = _pdf(root)
    _store(root / "u", "c01", [ROUTES[0]], [("a.pdf", "AAA", "deck", "2026-01-01", str(pdf))])
    monkeypatch.setattr(of, "render_page", lambda pdf_path, page: b"png")

    def paid(route, png, timeout=420):
        raise of.PaidModel("zen reported a cost of 0.25 on a free model")

    monkeypatch.setattr(of, "ask", paid)
    stats = of.run(of.select(root / "u"), ["zen"], out_dir=root / "out", enabled={"zen": True})
    assert stats["paid"] and stats["errors"] == 1 and stats["written"] == 0
