"""T-049 C: pilot3 document collection on a tiny fixture (no real stores, no network)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")
pytest.importorskip("openpyxl")

from reality_engine.gap_loop.company import Company  # noqa: E402
from reality_engine.pilot3 import docs_collect as dc  # noqa: E402

GUID_A = "11111111-2222-3333-4444-555555555555"
GUID_B = "66666666-7777-8888-9999-aaaaaaaaaaaa"
GUID_C = "dddddddd-7777-8888-9999-bbbbbbbbbbbb"
LONG = "Order received worth Rs 500 crore from the Power Grid Corporation for transmission lines. " * 2


def _pdf(path: Path, pages: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(fitz.Rect(40, 40, 550, 800), text, fontsize=11)
    doc.save(str(path))
    doc.close()


@pytest.fixture()
def world(tmp_path: Path):
    data, raw = tmp_path / "data", tmp_path / "raw"
    data.mkdir()
    ann = sqlite3.connect(data / "bse_announcements.db")
    ann.execute("CREATE TABLE ann(NEWSID, SCRIP_CD, ATTACHMENTNAME, NEWSSUB, HEADLINE, CATEGORYNAME, SUBCATNAME,"
                " NEWS_DT, DT_TM, News_submission_dt, DissemDT, QUARTER_ID, Fld_Attachsize, ANNOUNCEMENT_TYPE, symbol)")
    rows = [
        (GUID_A, 999001, f"{GUID_A}.pdf", "s", "Order win", "Company Update", "Award of Order / Receipt of Order",
         "2026-05-04T10:00:00", "", "2026-05-04T10:00:00", "2026-05-04T10:00:05", None, 100, "A", "TST"),
        (GUID_B, 999001, f"{GUID_B}.pdf", "s", "Presentation", "Company Update", "Investor Presentation",
         "2026-08-10T18:00:00", "", "2026-08-10T18:00:00", "2026-08-10T18:00:01", None, 100, "A", "TST"),
        (GUID_C, 999001, f"{GUID_C}.pdf", "s", "Results", "Result", "Financial Results",
         "2026-05-06T10:00:00", "", "2026-05-06T10:00:00", "2026-05-06T10:00:09", None, 100, "A", "TST"),
        ("cccccccc-0000-0000-0000-000000000000", 999001, "cccccccc-0000-0000-0000-000000000000.pdf", "s",
         "Never fetched", "Company Update", "General", "2026-09-01T10:00:00", "", "2026-09-01T10:00:00",
         "2026-09-01T10:00:02", None, 100, "A", "TST"),
    ]
    ann.executemany("INSERT INTO ann VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    ann.commit()
    ann.close()
    eq = sqlite3.connect(data / "equity_intelligence.db")
    eq.execute("CREATE TABLE symbol_isin_history(exchange, symbol, isin, first_date, last_date, n_days)")
    eq.executemany("INSERT INTO symbol_isin_history VALUES ('NSE','TST',?,?,?,1)",
                   [("INE000A01001", "2019-01-01", "2026-07-01"), ("INE000A01019", "2026-07-02", "2026-10-19")])
    eq.execute("CREATE TABLE corporate_documents(id, isin, symbol, doc_type, title, publication_date, call_date,"
               " bse_dissem_ts, bse_newsid, sha256_hash, bse_subcat)")
    eq.commit()
    eq.close()
    # An order-win announcement dated by NEWSID, a deck dated by attachment name in a differently named
    # folder, a byte-identical copy of the first (dedupe), a file nothing dates, and a scanned page.
    _pdf(raw / "pilot60_history" / "TST" / "material_filing" / f"{GUID_A}.pdf", [LONG, ""])
    _pdf(raw / "annual_report" / "TST" / f"{GUID_B}.pdf", [LONG + " deck"])
    (raw / "pilot60_history" / "TST" / "quarterly_results").mkdir(parents=True)
    (raw / "pilot60_history" / "TST" / "quarterly_results" / f"{GUID_C}.pdf").write_bytes(
        (raw / "pilot60_history" / "TST" / "material_filing" / f"{GUID_A}.pdf").read_bytes())  # same file, filed again
    (raw / "material_announcement" / "TST").mkdir(parents=True)
    (raw / "material_announcement" / "TST" / "copy.pdf").write_bytes(
        (raw / "pilot60_history" / "TST" / "material_filing" / f"{GUID_A}.pdf").read_bytes())
    _pdf(raw / "material_announcement" / "TST" / "mystery.pdf", [LONG + " mystery"])
    company = Company(symbol="TST", name="Test Ltd", isins=("INE000A01001",), bse_code="999001",
                      db_name="t.db", questions="q.jsonl")
    cfg = dc.Config(data_root=data, raw_roots=(raw,), extra_roots=(), companies={"TST": company})
    return cfg, tmp_path / "out" / "pages.db"


def test_collect_dates_dedupes_and_flags_ocr(world):
    cfg, out = world
    counts = dc.collect(cfg, ("TST",), out, log=lambda *_: None)["TST"]
    assert counts["files"] == 5 and counts["docs"] == 3 and counts["dupes"] == 2
    con = sqlite3.connect(out)
    docs = {r[0].split("/")[-1]: r for r in con.execute(
        "SELECT doc_key, doc_type, filing_date, known_at, isin, pages FROM doc")}
    order = docs[f"{GUID_A}.pdf"]
    assert order[2] == "2026-05-04" and order[3] == "2026-05-04T10:00:05"  # raw dissemination, not shifted
    meta = json.loads(con.execute("SELECT source_record FROM doc WHERE doc_key LIKE ?", (f"%{GUID_A}.pdf",)).fetchone()[0])
    assert {f["NEWSID"] for f in meta["filings"]} == {GUID_A, GUID_C}      # every filing of the same bytes kept
    assert order[4] == "INE000A01001" and order[5] == 2                    # symbol-at-time ISIN
    deck = docs[f"{GUID_B}.pdf"]
    assert deck[1] == "deck" and deck[3] == "2026-08-10T18:00:01" and deck[4] == "INE000A01019"
    assert docs["mystery.pdf"][3] is None                                   # undated stays NULL
    methods = dict(con.execute("SELECT page, method FROM doc_page WHERE doc_key LIKE ?", (f"%{GUID_A}.pdf",)))
    assert methods == {1: "script_text", 2: "needs_ocr"}
    assert con.execute("SELECT text FROM doc_page WHERE method='needs_ocr'").fetchone()[0] == ""


def test_fts_and_rerun_is_idempotent(world):
    cfg, out = world
    dc.collect(cfg, ("TST",), out, log=lambda *_: None)
    again = dc.collect(cfg, ("TST",), out, log=lambda *_: None)["TST"]
    assert again["skipped"] == again["docs"] == 3
    con = sqlite3.connect(out)
    hits = con.execute("SELECT COUNT(*) FROM doc_page_fts WHERE doc_page_fts MATCH 'transmission'").fetchone()[0]
    assert hits == con.execute("SELECT COUNT(*) FROM doc_page WHERE text LIKE '%transmission%'").fetchone()[0] == 3
    assert con.execute("SELECT COUNT(*) FROM doc_page").fetchone()[0] == 4


def test_coverage_lists_unfetched_attachment(world):
    from openpyxl import load_workbook

    cfg, out = world
    dc.collect(cfg, ("TST",), out, log=lambda *_: None)
    book = out.parent / "DOC_COVERAGE.xlsx"
    summary = dc.coverage(cfg, ("TST",), out, book)
    assert summary["TST"]["_missing_attachments"] == 1  # the re-filed results PDF counts as held
    wb = load_workbook(book)
    assert {"summary", "missing", "fetch_worklist", "runs"} <= set(wb.sheetnames)
    work = list(wb["fetch_worklist"].iter_rows(min_row=2, values_only=True))
    assert len(work) == 1 and work[0][1].startswith("cccccccc")
    dc.coverage(cfg, ("TST",), out, book)  # a second run appends to the run history
    assert wb["runs"].max_row == 2 and load_workbook(book)["runs"].max_row == 3


def test_isin_at_uses_history():
    history = [("A", "2019-01-01", "2026-07-01"), ("B", "2026-07-02", "2026-10-19")]
    assert dc.isin_at(history, "2025-01-01") == "A" and dc.isin_at(history, "2026-08-01") == "B"
    assert dc.isin_at(history, None) == "B" and dc.isin_at([], "2025-01-01") is None
