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
        # KEC files an order win as a Company Update / Press Release: the headline, not the sub-category,
        # says it is an order (T-049, 4 Nov 2026)
        (GUID_A, 999001, f"{GUID_A}.pdf", "s",
         "We are pleased to enclose a copy of the press release with respect to new orders of Rs. 1,236 crores "
         "secured by the Company.", "Company Update", "Press Release / Media Release",
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
    assert order[1] == "announcement"                                       # an order press release is an announcement
    assert order[2] == "2026-05-04" and order[3] == "2026-05-04T10:00:05"  # raw dissemination, not shifted
    title = str(con.execute("SELECT title FROM doc WHERE doc_key LIKE ?", (f"%{GUID_A}.pdf",)).fetchone()[0])
    assert title.startswith("We are pleased") and "1,236" in title          # titled by the order, not the sub-category
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


# ---------------------------------------------------------------- T-161/T-159: the printed first pages
OLD_GUID = "eeeeeeee-1111-2222-3333-444444444444"
NEW_GUID = "ffffffff-1111-2222-3333-444444444444"
LINK_GUID = "aaaaaaaa-1111-2222-3333-444444444444"


def _add_ann(cfg, newsid: str, subcat: str, dissem: str) -> None:
    """One BSE announcement row, so the file is dated and typed from a record (as the real stores do)."""
    con = sqlite3.connect(cfg.data_root / "bse_announcements.db")
    con.execute("INSERT INTO ann(NEWSID, SCRIP_CD, ATTACHMENTNAME, HEADLINE, CATEGORYNAME, SUBCATNAME, DissemDT,"
                " News_submission_dt, NEWS_DT, Fld_Attachsize, symbol)"
                " VALUES (?,999001,?,?,'Company Update',?,?,?,?,100,'TST')",
                (newsid, f"{newsid}.pdf", "Analyst / Investor Meet - Outcome", subcat, dissem, dissem, dissem))
    con.commit()
    con.close()


def test_printed_pages_correct_the_record(world):
    """T-161/T-159: a re-filed 2018 call takes its page-1 call date and becomes a transcript; a page-5 mention
    does not date a 2026 call, and the one-page meet outcome stays an announcement."""
    cfg, out = world
    folder = cfg.raw_roots[0] / "pilot60_history" / "TST" / "material_filing"
    _add_ann(cfg, OLD_GUID, "General", "2026-08-28T10:00:00")
    _add_ann(cfg, NEW_GUID, "General", "2026-08-28T10:00:00")
    _add_ann(cfg, LINK_GUID, "Analyst / Investor Meet - Outcome", "2026-08-28T10:00:00")
    _pdf(folder / f"{OLD_GUID}.pdf", [
        "TST Limited Earnings Call\nJuly 27, 2018\nModerator: Welcome to the call.",
        "Management Participants: the CFO. " + LONG,
        "Question and Answer session. " + LONG,
        "filler page",
        "The 2018 call said JLR was 24% of revenue. " + LONG,
    ])
    _pdf(folder / f"{NEW_GUID}.pdf", [
        "TST Limited Earnings Call\nAugust 28, 2026\nModerator: Welcome to the call.",
        "Management Participants: the CFO. " + LONG,
        "Question and Answer session. " + LONG,
        "filler page",
        "The 2018 call said JLR was 24% of revenue. " + LONG,
    ])
    _pdf(folder / f"{LINK_GUID}.pdf",
         ["Analyst / Investor Meet - Outcome. The audio recording is at https://example.invalid/a. " + LONG])
    counts = dc.collect(cfg, ("TST",), out, log=lambda *_: None)["TST"]
    assert (counts["redated"], counts["retyped"]) == (1, 2)
    con = sqlite3.connect(out)
    rows = {r[0].rsplit("/", 1)[-1]: r for r in con.execute(
        "SELECT doc_key, doc_type, filing_date, known_at, source_record FROM doc")}
    old = rows[f"{OLD_GUID}.pdf"]
    assert (old[1], old[2], old[3]) == ("transcript", "2018-07-27", "2018-07-27T23:59:59")
    meta = json.loads(old[4])
    assert (meta["date_source"], meta["record_filing_date"], meta["record_type"]) == (
        "printed", "2026-08-28", "announcement")
    assert {r[0] for r in con.execute("SELECT DISTINCT known_at FROM doc_page WHERE doc_key=?", (old[0],))} == {
        "2018-07-27T23:59:59"}                                   # the page dates move with the document
    new = rows[f"{NEW_GUID}.pdf"]
    assert (new[1], new[2], new[3]) == ("transcript", "2026-08-28", "2026-08-28T10:00:00")
    link = rows[f"{LINK_GUID}.pdf"]
    assert (link[1], link[2]) == ("announcement", "2026-08-28")
    con.close()
