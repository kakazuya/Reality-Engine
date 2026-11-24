from pathlib import Path
import sqlite3

from reality_engine.v2 import ar_sections as ars
from reality_engine.v2 import observations as obs


def test_drop_heading_beats_keep_words():
    assert ars.section_of("INDEPENDENT AUDITOR'S REPORT ... contingent liabilities") == ("auditor_report", False)


def test_keep_mdna_and_note_lower_on_page():
    assert ars.keep("Management Discussion and Analysis Industry overview revenue grew")
    table = "\n".join(f"Claim {i} 1,{i}23.45 1,{i}10.20" for i in range(10))
    assert ars.section_of("Notes to accounts 31 March 2026 ... 38 Contingent liabilities and commitments\n"
                          + table)[0] == "notes_offbalance"


def test_unrecognised_page_continues_running_section_then_stops():
    pages = [(10, "Management Discussion and Analysis"), (11, "plain text no heading"),
             (12, "more plain text"), (13, "Report on Corporate Governance"), (14, "plain text")]
    assert ars.kept_pages(pages) == {10: "mdna", 11: "mdna", 12: "mdna"}


def _make_ar_store(store_dir: Path, pages: list[str], doc_type: str = "annual_report") -> Path:
    store_db = store_dir / "store.db"
    con = sqlite3.connect(store_db)
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT)")
    for number, text in enumerate(pages, 1):
        con.execute("INSERT INTO doc_page VALUES (?,?,?)", ("ar.pdf", number, text))
    con.commit()
    con.close()
    with (store_dir / "routes.csv").open("w", newline="", encoding="utf-8") as fh:
        fh.write("doc_key,page,route,doc_type\n")
        for number in range(1, len(pages) + 1):
            fh.write(f"ar.pdf,{number},table_or_chart,{doc_type}\n")
    return store_db


def test_pages_from_store_ar_sections_filters_only_when_enabled(tmp_path: Path):
    store_db = _make_ar_store(tmp_path, [
        "Management Discussion and Analysis\nRevenue grew 18% YoY",
        "Capacity rose from 20 mtpa to 30 mtpa across plants",
        "Report on Corporate Governance\nBoard meetings held: 5",
        "INDEPENDENT AUDITOR'S REPORT\nTo the Members",
    ])
    all_pages = obs.pages_from_store(store_db, doc_types=("annual_report",), ar_sections=False)
    assert [p["page"] for p in all_pages] == [1, 2, 3, 4]
    dropped: dict[str, int] = {}
    kept_pages = obs.pages_from_store(store_db, doc_types=("annual_report",), ar_sections=True, dropped=dropped)
    assert [p["page"] for p in kept_pages] == [1, 2]
    assert dropped == {"ar_section": 2}


TABLE = "\n".join(f"Line item {i} 1,{i}23.45 1,{i}10.20" for i in range(10))


def test_round2_notes_running_header_does_not_drop_offbalance_notes():
    page = "Notes forming part of the Balance Sheet as at 31 March 2026\n38 Contingent liabilities\n" + TABLE
    assert ars.section_of(page) == ("notes_offbalance", True)


def test_round2_phrase_in_prose_is_not_kept_but_a_table_is():
    prose = "Directors' Report. All related party transactions were on an arm's length basis and approved."
    assert not ars.keep("The Board is pleased to present the report. " + prose)
    assert ars.section_of("Statement of something\n" + TABLE) == ("table", True)
    assert ars.section_of("Note 5 Property, plant and equipment\n" + TABLE) == ("xbrl_schedule", False)
