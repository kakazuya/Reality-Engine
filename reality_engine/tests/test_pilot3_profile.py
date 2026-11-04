"""Profile builds (T-056): a company list, its paths and its history window come from one JSON file.

A profile drives ``docs_collect`` (manifest only), ``build`` and its parts, the extractors and the MCP lookups,
with no company literal in the code path.  Without a profile every command keeps its present defaults, and
these tests pin that too.  The fixture builds a raw root, a manifest, a pages.db and a pilot database under
``.tmp/`` (pytest's own temp root is denied in the dsh sandbox), with a sandbox root that does not exist: a
profile build must never open a sandbox path.

    python -m pytest reality_engine/tests/test_pilot3_profile.py -q
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from reality_engine import pilot3
from reality_engine.pilot3 import answer_check, build, docs_collect, kpi, profile, schema, stores

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / ".tmp" / "test_pilot3_profile"
PROFILE_JSON = ROOT / "tasks" / "night_loop" / "pilot10_profile.json"
MANIFEST_COLUMNS = ("isin", "symbol_at_time", "scrip_code", "newsid", "bucket", "headline", "category", "subcat",
                    "dissem_ts", "url", "source", "local_path", "bytes", "sha256", "http_status", "attempts",
                    "is_pdf", "is_scanned_guess", "skip_reason", "fetched_at", "status", "error")


def _fresh(name: str) -> Path:
    path = TMP / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def _pdf(path: Path, pages: list[str]) -> None:
    """A small real PDF, so docs_collect reads a text layer (and not a needs_ocr page)."""
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _profile_json(base: Path, raw: Path, manifest: Path, window_start: str | None = "2025-10-01") -> Path:
    data = {"name": "fixture", "pages_db": str(base / "pages.db"), "raw_root": str(raw), "manifest": str(manifest),
            "out": str(base / "pilot.db"), "window_start": window_start,
            "companies": [{"symbol": "MARUTI", "name": "Maruti Suzuki India Ltd", "bse_code": "532500",
                           "isins": ["INE585B01010"], "sector": "auto_oem", "lender": False}]}
    path = base / "profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _manifest(path: Path, raw: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{name: "" for name in MANIFEST_COLUMNS}, **row})
    return path


@pytest.fixture
def sandbox_off(monkeypatch):
    """Every sandbox root points at a directory that does not exist: a profile build must not touch it."""
    gone = TMP / "no-such-sandbox"
    monkeypatch.setattr(build, "SANDBOX", gone)
    monkeypatch.setattr(kpi, "SANDBOX_ROOT", gone)
    yield gone
    profile.activate(None)


def test_load_committed_profile():
    """The committed pilot10 profile parses; the company literals live in the JSON, not in the module."""
    prof = profile.load(PROFILE_JSON)
    assert prof.name == "pilot10"
    assert len(prof.symbols) == 10
    assert prof.window_start == "2025-10-01"
    assert prof.pages_db.name == "pages.db" and prof.out.name == "pilot10.db"
    assert prof.is_lender("HDFCBANK") and not prof.is_lender("MARUTI")
    assert prof.company("MARUTI").isins == ("INE585B01010",)
    assert prof.company("MARUTI").gap_company().db_name == ""
    with pytest.raises(KeyError):
        prof.company("NOT-A-COMPANY")


def test_no_profile_keeps_the_present_defaults():
    profile.activate(None)
    assert profile.symbols() == pilot3.SYMBOLS
    assert profile.pages_db() == pilot3.PAGES_DB
    assert profile.window_start() is None
    assert profile.is_lender("BAJFINANCE")
    con = sqlite3.connect(":memory:")
    schema.create(con, ("fin_quarter_xbrl",))
    assert stores.apply_window(con) == {}      # no profile: no filter, no row deleted
    con.close()


def test_manifest_docs_build_and_window(sandbox_off):
    """docs_collect reads the manifest only; the build parts write the company, the pages, the KPIs and the
    window-filtered stores without opening a sandbox or a company-specific path."""
    base = _fresh("build")
    raw = base / "raw"
    _pdf(raw / "MARUTI" / "investor_presentation" / "1001.pdf",
         ["Q2 FY26 Investor Presentation. Order book of Rs 40,000 crore as of Q2 FY26. "
          "Revenue for Q2 FY26 was Rs 45,000 crore and EBITDA margin for Q2 FY26 was 12.5%."])
    _pdf(raw / "MARUTI" / "concall_transcript" / "1002.pdf",
         ["Maruti Suzuki India Limited Earnings Call October 28, 2025\n"
          "Management: We expect revenue growth of 12% to 15% for FY27, and our order book is at Rs 45,000 crore."])
    manifest = _manifest(raw / "manifest.csv", raw, [
        {"isin": "INE585B01010", "symbol_at_time": "MARUTI", "scrip_code": "532500", "newsid": "1001",
         "bucket": "investor_presentation", "headline": "Q2 FY26 investor presentation", "dissem_ts": "2025-10-29T10:00:00",
         "url": "https://example.invalid/1001.pdf", "local_path": str(raw / "MARUTI" / "investor_presentation" / "1001.pdf"),
         "sha256": "a" * 64, "status": "ok"},
        {"isin": "INE585B01010", "symbol_at_time": "MARUTI", "scrip_code": "532500", "newsid": "1002",
         "bucket": "concall_transcript", "headline": "Q2 FY26 earnings call transcript", "dissem_ts": "2025-10-28T18:00:00",
         "url": "https://example.invalid/1002.pdf", "local_path": str(raw / "MARUTI" / "concall_transcript" / "1002.pdf"),
         "sha256": "b" * 64, "status": "ok"},
        {"isin": "INE585B01010", "symbol_at_time": "MARUTI", "scrip_code": "532500", "newsid": "1003",
         "bucket": "concall_audio_link", "dissem_ts": "2025-10-28T18:00:00", "status": "ok"},
        {"isin": "INE585B01010", "symbol_at_time": "MARUTI", "scrip_code": "532500", "newsid": "1004",
         "bucket": "quarterly_results", "dissem_ts": "2025-10-29T10:00:00", "status": "ok"},   # status ok, no file
    ])
    pj = _profile_json(base, raw, manifest)
    pages = base / "pages.db"
    assert docs_collect.main(["--profile", str(pj), "--symbols", "MARUTI", "--out", str(pages)]) == 0
    con = sqlite3.connect(pages)
    try:
        docs = con.execute("SELECT doc_key, doc_type, known_at FROM doc ORDER BY doc_key").fetchall()
    finally:
        con.close()
    assert {d[1] for d in docs} == {"deck", "transcript"}      # the audio link and the unfetched row are not documents
    assert all(d[2] for d in docs)                             # known_at on every row

    prof = profile.activate(profile.load(pj))
    out = base / "pilot.db"
    build.build(out, "registry", symbols=["MARUTI"])
    build.build(out, "pages", symbols=["MARUTI"])
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT COUNT(*) FROM company").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM doc").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM doc WHERE known_at IS NULL").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM doc_page").fetchone()[0] > 0
        key = con.execute("SELECT doc_key FROM doc WHERE doc_type='deck'").fetchone()[0]
        assert key == "MARUTI/investor_presentation/1001.pdf"
    finally:
        con.close()

    with pytest.raises(ValueError):
        build.build(out, "registry", symbols=["NOT-A-COMPANY"])

    build.build(out, "kpi", symbols=["MARUTI"])
    build.build(out, "transcripts", symbols=["MARUTI"])
    stats = build.build(out, "guidance", symbols=["MARUTI"])
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT COUNT(*) FROM kpi_series WHERE symbol='MARUTI'").fetchone()[0] > 0
        assert con.execute("SELECT COUNT(*) FROM transcript_statement WHERE symbol='MARUTI'").fetchone()[0] > 0
    finally:
        con.close()
    assert "MARUTI" in stats["rows"]["guidance"]


def test_symbols_limit_every_part_under_a_profile():
    """--symbols limits registry/pages/stores too under a profile: a database built for one company holds one."""
    base = _fresh("scope")
    raw = base / "raw"
    raw.mkdir()
    pj = _profile_json(base, raw, _manifest(raw / "manifest.csv", raw, []))
    data = json.loads(pj.read_text(encoding="utf-8"))
    data["companies"].append({"symbol": "TESTCO", "name": "Test Co Ltd", "bse_code": "999999",
                              "isins": ["INE000000000"], "sector": "test", "lender": False})
    pj.write_text(json.dumps(data), encoding="utf-8")
    profile.activate(profile.load(pj))
    out = base / "pilot.db"
    try:
        build.build(out, "registry", symbols=["MARUTI"])
        con = sqlite3.connect(out)
        try:
            assert con.execute("SELECT GROUP_CONCAT(DISTINCT symbol) FROM company").fetchone()[0] == "MARUTI"
        finally:
            con.close()
        build.build(out, "registry")          # no --symbols: every company of the profile
        con = sqlite3.connect(out)
        try:
            assert set(r[0] for r in con.execute("SELECT DISTINCT symbol FROM company")) == {"MARUTI", "TESTCO"}
        finally:
            con.close()
    finally:
        profile.set_scope(None)
        profile.activate(None)


def test_window_keeps_only_rows_from_window_start():
    """Under a profile the five dated stores keep only rows dated on or after window_start."""
    base = _fresh("window")
    raw = base / "raw"
    raw.mkdir()
    prof = profile.load(_profile_json(base, raw, _manifest(raw / "manifest.csv", raw, [])))
    profile.activate(prof)
    assert prof.window_start == "2025-10-01"
    con = sqlite3.connect(":memory:")
    schema.create(con, ("fin_quarter_xbrl", "shp_category"))
    quarter = ("MARUTI", "INE585B01010", "2025-10-01", "{}", "Q3FY26", "consolidated", "a", "PL", "pat", "Tag",
               1.5e9, "inr", 1.0, "q.xml", "results_xbrl.db", "quarterly", "q.xml", "2026-02-05T10:00:00", "x", 1)
    for end in ("2025-06-30", "2025-12-31"):
        con.execute("INSERT INTO fin_quarter_xbrl VALUES (" + ",".join("?" * 20) + ")",
                    tuple(end if v == "{}" else v for v in quarter))
    con.executemany("INSERT INTO shp_category VALUES (" + ",".join("?" * 18) + ")",
                    [("MARUTI", "I", end, "promoter", "Promoter", 1e8, 51.5, 10, "pct", "xbrl", "shp.xml", "db", "t", "1",
                      None, "2026-01-20T10:00:00", "x", 1) for end in ("2025-06-30", "2025-12-31")])
    deleted = stores.apply_window(con)
    assert deleted == {"fin_quarter_xbrl": 1, "shp_category": 1}
    assert con.execute("SELECT DISTINCT period_end FROM fin_quarter_xbrl").fetchall() == [("2025-12-31",)]
    assert con.execute("SELECT DISTINCT quarter_end FROM shp_category").fetchall() == [("2025-12-31",)]
    con.close()
    profile.activate(None)


def test_lookups_serve_the_profile_database():
    """REALITY_PILOT3_DB: the MCP lookups accept the database's own companies, not only pilot3's three."""
    base = _fresh("lookups")
    db = base / "pilot.db"
    con = sqlite3.connect(db)
    schema.create(con, ("company", "doc", "doc_alias"))
    con.executescript(kpi.SCHEMA)
    con.execute("INSERT INTO company VALUES ('MARUTI','INE585B01010',NULL,NULL,'t','532500','Maruti Suzuki India Ltd')")
    con.execute("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               ("MARUTI/investor_presentation/1001.pdf", "MARUTI", "INE585B01010", "deck", "deck",
                "Q2 FY26 investor presentation", "2025-10-29", "2025-10-29T10:00:00", 2, "a", "pages.db", "D:/1001.pdf"))
    con.execute("INSERT INTO kpi_series(symbol,metric,dimension,value,unit,scale,period_type,fiscal_period,basis,"
                "doc_key,page,quote,known_at,known_at_source,is_reported,extractor_rule) "
                "VALUES ('MARUTI','order_book','total',40000.0,'inr_cr',1,'Q','Q2FY26','consolidated',?,1,?,"
                "'2025-10-29T10:00:00','doc.known_at',1,'t')",
                ("MARUTI/investor_presentation/1001.pdf", "Order book of Rs 40,000 crore as of Q2 FY26"))
    con.commit()
    con.close()

    previous = os.environ.get("REALITY_PILOT3_DB")
    p3 = answer_check.lookups()
    with answer_check.on_db(db):
        assert p3.pilot_symbols() == ("MARUTI",)      # the database's own company table, not pilot3's three
        assert p3.resolve_symbol("MARUTI") == "MARUTI"
        assert p3.resolve_symbol("532500") == "MARUTI"
        assert p3.resolve_symbol("INE585B01010") == "MARUTI"
        reply = p3.kpi("MARUTI", "order book")
        assert reply["found"] and reply["rows"]
        assert reply["rows"][0]["metric"] == "order_book"
    assert os.environ.get("REALITY_PILOT3_DB") == previous


def test_compute_start_and_extra_indices_are_optional(tmp_path):
    """T-056 loop 2: the committed profile sets neither; a profile that does is read through profile.py only."""
    assert profile.load(PROFILE_JSON).compute_start is None
    try:
        profile.activate(profile.load(PROFILE_JSON))
        assert profile.compute_start() is None and profile.extra_indices() == ()
        data = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
        for key in ("pages_db", "raw_root", "manifest", "out"):
            data[key] = str(tmp_path / key)
        data.update(compute_start="2024-10-01", extra_indices=["Nifty Bank"])
        path = tmp_path / "p.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        profile.activate(profile.load(path))
        assert profile.compute_start() == "2024-10-01" and profile.extra_indices() == ("Nifty Bank",)
        data["compute_start"] = "2025-10-01"          # not earlier than the window: nothing is held back
        path.write_text(json.dumps(data), encoding="utf-8")
        profile.activate(profile.load(path))
        assert profile.compute_start() is None
    finally:
        profile.activate(None)
    assert profile.compute_start() is None and profile.extra_indices() == ()
