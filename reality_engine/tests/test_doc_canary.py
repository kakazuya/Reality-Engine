"""T-121: the build's ``ocr`` part and the stratified document canary.

The canary fixtures are a fake manifest and local PDFs with a fake ``raw_store``: no network, no real OCR
(``ocr.ocr_page`` is monkeypatched), no live database.  pytest's own ``tmp_path`` is unusable in the DSH sandbox
(it is created mode 0700), so the local fixture makes an ordinary ``.tmp`` directory, as the other tests do.
"""
from __future__ import annotations

import contextlib
import csv
import json
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from reality_engine.pilot3 import build, doc_canary, docs_collect, ocr, profile  # noqa: E402

LONG = "Order book of 37,697 crore and revenue of 12,345 crore for the quarter"
SHA = "c" * 64


@pytest.fixture
def tmp_path():
    """A writable empty dir under the repo's ``.tmp`` (the sandbox denies pytest's mode-0700 temp root)."""
    directory = Path(__file__).resolve().parents[2] / ".tmp" / f"doc_canary_{uuid.uuid4().hex[:10]}"
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _text_pdf(path: Path, text: str = LONG) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 550, 800), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def _scanned_pdf(path: Path) -> Path:
    """One page with no text layer: render a page to an image and put that image on a fresh page."""
    path.parent.mkdir(parents=True, exist_ok=True)
    source = fitz.open()
    page = source.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 550, 800), LONG, fontsize=11)
    pixmap = page.get_pixmap(dpi=120)
    source.close()
    doc = fitz.open()
    doc.new_page(width=595, height=842).insert_image(fitz.Rect(0, 0, 595, 842), pixmap=pixmap)
    doc.save(str(path))
    doc.close()
    return path


def _pages_db(path: Path, symbol: str, pdf: Path) -> Path:
    """The collector's pages.db shape: one document whose page 1 has no text layer."""
    con = sqlite3.connect(path)
    con.executescript(docs_collect.SCHEMA)
    con.execute("INSERT INTO doc VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"{symbol}/deck/{pdf.stem}.pdf", symbol, "INE389H01022", "deck", "Scanned deck", "2026-08-01",
                 "2026-08-01T18:00:00", str(pdf), SHA, 1, "", "bse_announcements.ann"))
    con.execute("INSERT INTO doc_page VALUES(?,?,?,?,?)", (f"{symbol}/deck/{pdf.stem}.pdf", 1, "", "needs_ocr",
                                                           "2026-08-01"))
    con.commit()
    con.close()
    return path


def _fake_ocr(page, dpi=300, device="cpu", max_side=2400):
    return LONG, [[0.0, 0.0, 99.0, 9.0, "Order", 0.9]], 0.9, 7


def _profile_dir(root: Path, symbols: tuple[str, ...]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "test_profile.json").write_text(
        json.dumps({"name": "t", "companies": [{"symbol": s} for s in symbols]}), encoding="utf-8")
    return root


def test_ocr_part_fills_the_page_and_pages_reads_it(tmp_path, monkeypatch):
    """--part ocr writes <out>_ocr.db; --part pages then fills a scanned page with text and method ocr_rapid."""
    pdf = _scanned_pdf(tmp_path / "raw" / "deck" / "KEC" / "scan.pdf")
    pages = _pages_db(tmp_path / "pages.db", "KEC", pdf)
    prof = profile.Profile(name="t121", pages_db=pages, raw_root=tmp_path, manifest=tmp_path / "manifest.csv",
                           out=tmp_path / "out.db",
                           companies=(profile.ProfileCompany("KEC", isins=("INE389H01022",)),))
    monkeypatch.setattr(ocr, "ocr_page", _fake_ocr)
    out = tmp_path / "out.db"
    profile.activate(prof)
    try:
        assert build.build(out, "ocr", symbols=["KEC"])["ocr"]["KEC"]["done"] == 1
        assert build.ocr_target(out).is_file()
        build.build(out, "pages", symbols=["KEC"])
    finally:
        profile.activate(None)
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT text, method FROM doc_page").fetchone() == (_fake_ocr(None)[0], "ocr_rapid")
        assert con.execute("SELECT COUNT(*) FROM doc_page_fts WHERE doc_page_fts MATCH 'orderbook'").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM doc_page_fts WHERE doc_page_fts MATCH 'order'").fetchone()[0] == 1
    finally:
        con.close()


def test_candidates_exclude_pilot_companies_and_pick_is_seeded(tmp_path):
    raw = tmp_path / "raw"
    pdf = _text_pdf(raw / "pilot60_history" / "AAA" / "quarterly_results" / "r1.pdf")
    manifest = tmp_path / "manifest.csv"
    rows = [{"symbol_at_time": symbol, "bucket": "quarterly_results", "newsid": f"n{i}", "dissem_ts": "2020-05-01",
             "local_path": str(pdf), "sha256": SHA, "status": "ok"}
            for i, symbol in enumerate(("KEC", "KEC", "AAA", "BBB"))]
    with manifest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    class Store:
        roots = {"raw": raw}

        def exists(self, path):
            return Path(path).is_file()

    found = doc_canary.candidates(Store(), {"KEC"}, manifest)  # type: ignore[arg-type]  # duck-typed store
    assert {r["symbol"] for r in found} == {"AAA", "BBB"}          # KEC is in a pilot profile
    assert all(r["doc_type"] == "results" and r["year"] == 2020 for r in found)

    many = [{"symbol": f"S{i}", "doc_type": "deck", "year": 2020, "newsid": f"n{i}",
             "known_at": f"2020-01-{i + 1:02d}", "path": Path("x"), "sha256": ""} for i in range(10)]
    first = doc_canary.pick(many, 3, 7)[("deck", 2020)]
    again = doc_canary.pick(list(reversed(many)), 3, 7)[("deck", 2020)]
    assert len(first) == 3
    assert [r["newsid"] for r in first] == [r["newsid"] for r in again]   # manifest order does not change the set


def test_run_writes_the_table_and_a_second_run_flags_a_drop(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    text_pdf = _text_pdf(raw / "pilot60_history" / "AAA" / "quarterly_results" / "r1.pdf")
    scan_pdf = _scanned_pdf(raw / "pilot60_history" / "BBB" / "investor_presentation" / "d1.pdf")
    manifest = tmp_path / "manifest.csv"
    rows = [
        {"symbol_at_time": "AAA", "bucket": "quarterly_results", "newsid": "n1", "dissem_ts": "2020-05-01",
         "local_path": str(text_pdf), "sha256": SHA, "status": "ok"},
        {"symbol_at_time": "BBB", "bucket": "investor_presentation", "newsid": "n2", "dissem_ts": "2021-08-02",
         "local_path": str(scan_pdf), "sha256": SHA, "status": "ok"},
        {"symbol_at_time": "KEC", "bucket": "quarterly_results", "newsid": "n3", "dissem_ts": "2020-05-01",
         "local_path": str(text_pdf), "sha256": SHA, "status": "ok"},     # pilot company: never picked
    ]
    with manifest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    class Store:
        roots = {"raw": raw}

        def exists(self, path):
            return Path(path).is_file()

        @contextlib.contextmanager
        def local(self, path):
            yield Path(path)

    out = tmp_path / "canary"
    monkeypatch.setattr(doc_canary.raw_store, "default_store", lambda: Store())
    monkeypatch.setattr(doc_canary, "REAL_DB", tmp_path / "no_pilot3.db")   # no live database is read
    monkeypatch.setattr(ocr, "ocr_page", _fake_ocr)
    created = doc_canary.run(out, per_cell=3, seed=1, manifest=manifest,
                             profile_dir=_profile_dir(tmp_path / "profiles", ("KEC",)))
    assert created["documents"] == 2 and created["cells"] == 2 and created["errors"] == 0
    summary = {(r["type"], r["year"]): r for r in created["summary"]}
    assert summary[("results", 2020)]["text_pages_pct"] == 100.0
    deck = summary[("deck", 2021)]
    assert deck["ocr_pages"] == 1 and deck["text_pages_pct"] == 100.0 and deck["mean_ocr_conf"] == 0.9
    assert deck["kpi_rows_per_doc"] == 0.0
    with (out / "canary.csv").open(encoding="utf-8", newline="") as fh:
        canary = list(csv.DictReader(fh))
    assert {row["type"] for row in canary} == {"results", "deck"}
    assert {row["doc"] for row in canary} == {"pilot60_history/AAA/quarterly_results/r1.pdf",
                                              "pilot60_history/BBB/investor_presentation/d1.pdf"}

    # a later run with a document format the OCR cannot read is a drop, not a silent loss
    with (out / "summary.csv").open(newline="", encoding="utf-8") as fh:
        previous = list(csv.DictReader(fh))
        columns = list(previous[0])
    for row in previous:
        row["kpi_rows_per_doc"] = "9"
        row["text_pages_pct"] = "100"
    with (out / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(previous)
    monkeypatch.setattr(ocr, "ocr_page", lambda *args, **kwargs: ("", [], 0.0, 0))   # a format OCR now loses
    second = doc_canary.run(out, per_cell=3, seed=1, manifest=manifest,
                            profile_dir=_profile_dir(tmp_path / "profiles", ("KEC",)))
    assert any("KPI rows/doc" in line for line in second["drops"])
    assert any("text coverage" in line and "deck 2021" in line for line in second["drops"])
