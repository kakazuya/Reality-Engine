"""T-052: pilot3 OCR reads pages.db needs_ocr pages too, and build fills doc_page/FTS from the OCR databases.

Fixture stores and a tiny PDF; ``ocr_page`` is monkeypatched, so no model, no real OCR run and no store is touched.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from reality_engine.pilot3 import build, kpi, ocr, registry, transcripts  # noqa: E402

SHA = "a" * 64
PDF_KEY = "deck/KEC/aaa.pdf"
LONG = "text layer page with more than twenty characters on it"


def _pdf(path: Path, texts: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        if text:
            page.insert_textbox(fitz.Rect(40, 40, 550, 800), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def _sandbox(root: Path) -> Path:
    """Sandbox loop db: a scanned document that pages.db also holds (same sha256, so it aliases), and one that
    pages.db does not hold (kept under ``KEC:<key>``).  Only the aliased document's PDF is on disk."""
    d = root / "kec_loop"
    d.mkdir(parents=True)
    con = sqlite3.connect(d / "kec.db")
    con.executescript("""
      CREATE TABLE docs(doc_key TEXT, doc_type TEXT, title TEXT, filing_date TEXT, known_at TEXT, pages INT,
                        source TEXT, source_key TEXT);
      CREATE TABLE doc_text(doc_key TEXT, page INT, text TEXT, method TEXT, known_at TEXT);
      CREATE TABLE deck_figures(sha256 TEXT, known_at TEXT);
    """)
    con.execute("INSERT INTO docs VALUES('scan.pdf','deck','Scanned deck','2026-08-01','2026-08-01T18:00:00',2,'s',?)",
                (SHA,))
    con.execute("INSERT INTO doc_text VALUES('scan.pdf',1,?,'script_text','2026-08-01')", (LONG,))
    con.execute("INSERT INTO doc_text VALUES('scan.pdf',2,'','needs_ocr','2026-08-01')")
    con.execute("INSERT INTO docs VALUES('other.pdf','announcement','Notice','2026-08-02','2026-08-02T10:00:00',1,'s',?)",
                ("b" * 64,))
    con.execute("INSERT INTO doc_text VALUES('other.pdf',1,'','needs_ocr','2026-08-02')")
    con.commit()
    con.close()
    _pdf(d / "raw" / "scan.pdf", [LONG, ""])
    return root


def _empty_sandbox(root: Path) -> Path:
    d = root / "kec_loop"
    d.mkdir(parents=True)
    con = sqlite3.connect(d / "kec.db")
    con.executescript("""
      CREATE TABLE docs(doc_key TEXT, doc_type TEXT, title TEXT, filing_date TEXT, known_at TEXT, pages INT,
                        source TEXT, source_key TEXT);
      CREATE TABLE doc_text(doc_key TEXT, page INT, text TEXT, method TEXT, known_at TEXT);
      CREATE TABLE deck_figures(sha256 TEXT, known_at TEXT);
    """)
    con.execute("INSERT INTO deck_figures VALUES(?, '2026-08-01T18:00:00')", (SHA,))
    con.commit()
    con.close()
    return root


def _pages_db(path: Path, pdf: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE doc(doc_key TEXT PRIMARY KEY, symbol TEXT NOT NULL, isin TEXT, doc_type TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL DEFAULT '', filing_date TEXT, known_at TEXT, source_path TEXT NOT NULL,
          sha256 TEXT NOT NULL, pages INTEGER NOT NULL DEFAULT 0, source_record TEXT NOT NULL DEFAULT '',
          known_at_source TEXT NOT NULL DEFAULT '');
      CREATE TABLE doc_page(doc_key TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL, method TEXT NOT NULL,
          known_at TEXT, PRIMARY KEY(doc_key, page));
    """)
    con.execute("INSERT INTO doc VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (PDF_KEY, "KEC", "INE389H01022", "deck", "Scanned deck", "2026-08-01", "2026-08-01T18:00:00",
                 str(pdf), SHA, 2, "", "bse_announcements.ann"))
    con.execute("INSERT INTO doc_page VALUES(?,1,?,'script_text','2026-08-01')", (PDF_KEY, LONG))
    con.execute("INSERT INTO doc_page VALUES(?,2,'','needs_ocr','2026-08-01')", (PDF_KEY,))
    con.commit()
    con.close()
    return path


def _ocr_db(path: Path, rows: list[tuple]) -> Path:
    con = sqlite3.connect(path)
    con.executescript(ocr.SCHEMA)
    con.executemany("INSERT INTO ocr_page VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


def test_pending_reads_pages_db_keyed_as_the_build_does(tmp_path):
    pdf = _pdf(tmp_path / "raw" / "deck" / "KEC" / "aaa.pdf", [LONG, ""])
    pages, sb = _pages_db(tmp_path / "pages.db", pdf), _sandbox(tmp_path / "sb")
    assert ocr.pending("KEC", sb, None, set(), pages) == [(PDF_KEY, 2, "deck", "2026-08-01T18:00:00", pdf)]
    # already OCR'd under the sandbox alias key, or under the decks_full sha key: not a second read
    assert ocr.pending("KEC", sb, None, {("scan.pdf", 2)}, pages) == []
    assert ocr.pending("KEC", sb, None, {(f"decks_full/{SHA[:2]}/{SHA}.pdf", 2)}, pages) == []
    # pages.db off: the sandbox source is what the run had before T-052
    assert ocr.pending("KEC", sb, None, set(), None) == [
        ("scan.pdf", 2, "deck", "2026-08-01T18:00:00", sb / "kec_loop" / "raw" / "scan.pdf")]


def test_pending_pages_db_wins_over_the_decks_full_copy(tmp_path):
    fitz_pdf = _pdf(tmp_path / "raw" / "deck" / "KEC" / "aaa.pdf", [LONG, ""])
    decks = _pdf(tmp_path / "raw" / "decks_full" / SHA[:2] / f"{SHA}.pdf", [LONG, ""])
    pages, sb = _pages_db(tmp_path / "pages.db", fitz_pdf), _empty_sandbox(tmp_path / "sb")
    todo = ocr.pending("KEC", sb, tmp_path / "raw", set(), pages)
    assert [(r[0], r[1]) for r in todo] == [(PDF_KEY, 2)]
    assert decks.is_file() and ocr.pending("KEC", sb, tmp_path / "raw", set(), None)[0][:2] == (
        f"decks_full/{SHA[:2]}/{SHA}.pdf", 2)


def test_run_stores_the_pages_db_key_without_a_real_ocr_call(tmp_path, monkeypatch):
    pdf = _pdf(tmp_path / "raw" / "deck" / "KEC" / "aaa.pdf", [LONG, ""])
    pages, sb = _pages_db(tmp_path / "pages.db", pdf), _sandbox(tmp_path / "sb")
    monkeypatch.setattr(ocr, "ocr_page",
                        lambda page, dpi=300, device="cpu", max_side=2400: ("Order book 37,697 crore",
                                                                            [[0.0, 0.0, 9.0, 9.0, "Order", 0.9]],
                                                                            0.91, 7))
    out = tmp_path / "ocr.db"
    stats = ocr.run(str(out), ["KEC"], sb, None, 60, None, 300, "cpu", pages_db=pages)
    assert stats["KEC"]["pending_at_start"] == 1 and stats["KEC"]["done"] == 1
    con = sqlite3.connect(out)
    assert con.execute("SELECT doc_key, page, text, ocr_conf, method FROM ocr_page").fetchall() == [
        (PDF_KEY, 2, "Order book 37,697 crore", 0.91, "ocr_rapid")]


def test_cli_pages_db_empty_disables_the_pages_db_source(tmp_path, monkeypatch):
    pdf = _pdf(tmp_path / "raw" / "deck" / "KEC" / "aaa.pdf", [LONG, ""])
    _pages_db(tmp_path / "pages.db", pdf)                     # present but must not be read
    sb = _sandbox(tmp_path / "sb")
    monkeypatch.setattr(ocr, "ocr_page", lambda page, dpi=300, device="cpu", max_side=2400: ("x", [], 0.9, 1))
    out = tmp_path / "ocr.db"
    assert ocr.main(["--out", str(out), "--symbols", "KEC", "--sandbox-root", str(sb), "--raw-root", "",
                     "--pages-db", ""]) == 0
    con = sqlite3.connect(out)
    assert con.execute("SELECT doc_key, page FROM ocr_page").fetchall() == [("scan.pdf", 2)]


def test_build_pages_fills_doc_page_from_the_ocr_db_and_fts(tmp_path, monkeypatch):
    pdf = _pdf(tmp_path / "raw" / "deck" / "KEC" / "aaa.pdf", [LONG, ""])
    pages, sb = _pages_db(tmp_path / "pages.db", pdf), _sandbox(tmp_path / "sb")
    odb = _ocr_db(tmp_path / "ocr.db", [
        # the running OCR jobs wrote sandbox keys: doc_alias maps them back to the pages.db document
        ("KEC", "scan.pdf", 2, "deck", "2026-08-01T18:00:00", "Orderbook of 37,697 crore",
         json.dumps([[0.0, 0.0, 9.0, 9.0, "Orderbook", 0.9]]), 0.88, 5, 300, 1.2, "ocr_rapid"),
        # a sandbox document pages.db does not hold keeps the KEC:<key> form of doc_page
        ("KEC", "other.pdf", 1, "announcement", "2026-08-02", "Notice of board meeting",
         json.dumps([[0.0, 0.0, 9.0, 9.0, "Notice", 0.9]]), 0.75, 4, 300, 1.0, "ocr_rapid"),
    ])
    monkeypatch.setattr(registry, "PAGES_DB", pages)
    monkeypatch.setattr(registry, "SYMBOLS", ("KEC",))
    monkeypatch.setattr(registry, "SANDBOX_DB", {"KEC": sb / "kec_loop" / "kec.db"})
    con = sqlite3.connect(":memory:")
    assert registry.build_pages(con, [str(odb)]) == {"KEC": 3}          # 2 pages.db pages + 1 sandbox-only page
    text = "Orderbook of 37,697 crore"
    assert con.execute("SELECT text, method, chars, ocr_conf FROM doc_page WHERE doc_key=? AND page=2",
                       (PDF_KEY,)).fetchone() == (text, "ocr_rapid", len(text), 0.88)
    assert con.execute("SELECT method, ocr_conf FROM doc_page WHERE doc_key='KEC:other.pdf'").fetchone() == (
        "ocr_rapid", 0.75)
    assert con.execute("SELECT text FROM doc_page_fts WHERE doc_page_fts MATCH 'orderbook'").fetchone()[0] == \
        text                                  # FTS searches the OCR text like a text layer


def test_extract_passes_every_ocr_db_to_kpi(tmp_path, monkeypatch):
    calls: dict = {}

    def fake_kpi(out, symbols, sandbox, **kw):
        calls["kpi"] = kw.get("ocr_db")
        return {}

    def fake_transcripts(out, symbols, sandbox, **kw):
        calls["tr"] = True
        return {}

    monkeypatch.setattr(kpi, "run", fake_kpi)
    monkeypatch.setattr(transcripts, "run", fake_transcripts)
    a, b, out = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "pilot3.db"
    build.main(["--out", str(out), "--part", "extract", "--ocr-db", str(a), "--ocr-db", str(b)])
    assert calls["kpi"] == [str(a), str(b)] and calls["tr"]


def test_kpi_run_merges_ocr_dbs_and_remaps_doc_alias(tmp_path, monkeypatch):
    out = tmp_path / "kpi.db"
    con = sqlite3.connect(out)
    con.execute("CREATE TABLE doc_alias(symbol TEXT, alias_key TEXT, doc_key TEXT)")
    con.execute("INSERT INTO doc_alias VALUES('KEC','scan.pdf',?)", (PDF_KEY,))
    con.commit()
    con.close()
    dbs = [_ocr_db(tmp_path / f"o{i}.db", [("KEC", key, 1, "deck", "2026-08-01", f"text of {key}",
                                            json.dumps([[0.0, 0.0, 9.0, 9.0, "x", 0.9]]), 0.9, 1, 300, 0.5,
                                            "ocr_rapid")])
           for i, key in enumerate((PDF_KEY, "other.pdf"))]
    seen: dict = {}

    def fake_extract(sym, sandbox, stats, limit_docs=None, raw_root=None, ocr=None, only_docs=None):
        seen[sym] = ocr
        stats.setdefault(sym, {})
        return iter(())

    monkeypatch.setattr(kpi, "extract_company", fake_extract)
    kpi.run(str(out), ["KEC"], tmp_path / "sb", None, None, [str(d) for d in dbs])
    assert set(seen["KEC"]) == {PDF_KEY, "scan.pdf", "other.pdf"}        # both dbs, plus the alias key
