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


def test_pages_from_store_ar_sections_filters_only_when_enabled(tmp_path: Path, monkeypatch):
    seen: list = []

    def fake_triage(texts, workers=10, db=None):        # round 3: only safe-drop survivors reach hy4
        seen.extend(sorted(texts))
        return {key: "Capacity" not in text for key, text in texts.items()}

    monkeypatch.setattr(ars, "triage", fake_triage)
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
    assert seen == []                                       # Eagle: no triage while listing candidates
    assert [p["page"] for p in kept_pages] == [1, 2]        # governance and auditor pages are safe drops
    assert dropped == {"ar_section": 2}
    out = obs.triage_selection(kept_pages[:1], pool=kept_pages, limit=1, seed=1, dropped=dropped)
    assert [p["page"] for p in out] == [1] and seen[0] == ("ar.pdf", 1)     # sample first, then triage
    seen.clear()
    out = obs.triage_selection([kept_pages[1]], pool=kept_pages, limit=1, seed=1, dropped=dropped)
    assert [p["page"] for p in out] == [1] and dropped["ar_triage"] == 2    # a 'not useful' page is topped up


def test_triage_caches_and_reads_unsure_as_useful(tmp_path: Path, monkeypatch):
    calls = []

    def fake_call(prompt, image, doc_key="", page=0):
        calls.append(page)
        return {"output": '{"useful": false, "section": "notice"}' if page == 1 else "garbled"}

    monkeypatch.setattr(obs, "call_reader", fake_call)
    db = tmp_path / "t.db"
    texts = {("a.pdf", 1): "x", ("a.pdf", 2): "y"}
    assert ars.triage(texts, workers=2, db=db) == {("a.pdf", 1): False, ("a.pdf", 2): True}
    assert ars.triage(texts, workers=2, db=db) == {("a.pdf", 1): False, ("a.pdf", 2): True}
    assert sorted(calls) == [1, 2, 2]                       # the cached verdict is not asked again; unsure is


TABLE = "\n".join(f"Line item {i} 1,{i}23.45 1,{i}10.20" for i in range(10))


def test_round2_notes_running_header_does_not_drop_offbalance_notes():
    page = "Notes forming part of the Balance Sheet as at 31 March 2026\n38 Contingent liabilities\n" + TABLE
    assert ars.section_of(page) == ("notes_offbalance", True)


def test_round2_phrase_in_prose_is_not_kept_but_a_table_is():
    prose = "Directors' Report. All related party transactions were on an arm's length basis and approved."
    assert not ars.keep("The Board is pleased to present the report. " + prose)
    assert ars.section_of("Statement of something\n" + TABLE) == ("table", True)
    assert ars.section_of("Note 5 Property, plant and equipment\n" + TABLE) == ("xbrl_schedule", False)


# T-242: an annual report's statement line is never verified by the page check; the XBRL stays as filed.
AR_PAGE = ("Balance Sheet as at 31 March 2026 (INR crore) FY26\n"
           "Total assets 2,345.67\nCash and cash equivalents 12.00\n"
           "Installed capacity 500 MW\n"
           "Number of employees 1,200")


def _ar_reply(**kw):
    base = {"series_id": "s1", "series_title": "", "measure": "total_assets", "printed_label": "",
            "printed_axis": "FY26", "value_text": "", "unit": "", "scale": 1, "period": "FY26",
            "period_kind": "actual", "segment": "", "product": "", "geography": "", "plant": "",
            "customer": "", "group_path": "", "group_source": "", "stage": "",
            "entity_scope": "company", "is_total": False}
    base.update(kw)
    return base


def _ar_rows():
    return obs.build_observations(symbol="ARCO", doc_key="D:/x/annual_report/a.pdf", page=10,
                                  known_at="2026-08-10T10:00:00", page_text=AR_PAGE, reply_rows=[
                                      _ar_reply(printed_label="Total assets", value_text="2,345.67",
                                                unit="INR crore"),
                                      _ar_reply(measure="cash_and_cash_equivalents",
                                                printed_label="Cash and cash equivalents",
                                                value_text="12.00", unit="INR crore"),
                                      _ar_reply(measure="capacity.total", printed_label="Installed capacity",
                                                value_text="500", unit="MW"),
                                      _ar_reply(measure="count.employees", printed_label="Number of employees",
                                                value_text="1,200", unit="count")])


def test_ar_statement_lines_go_unverified_and_an_operating_measure_stays():
    rows = _ar_rows()
    assert all(row["status"] == "verified" for row in rows)   # what the page check alone says today
    obs.apply_ar_statement_gate(rows)
    status = {row["measure"]: row["status"] for row in rows}
    assert status == {"total_assets": "unverified", "cash_and_cash_equivalents": "unverified",
                      "capacity.total": "verified", "count.employees": "verified"}
    assert "XBRL holds statement lines" in rows[0]["status_reason"]


def test_a_new_statement_line_name_is_gated_and_an_operating_name_is_not():
    assert obs.is_statement_line("NEW:other_financial_liability_item")
    assert obs.is_statement_line("NEW:trade_payables_others")
    assert not obs.is_statement_line("NEW:coal_quantity")
    assert not obs.is_statement_line("capacity.total")
    rows = [{"record_type": "number", "status": "verified", "measure": "NEW:trade_payables_others",
             "status_reason": ""}]
    obs.apply_ar_statement_gate(rows)
    assert rows[0]["status"] == "unverified"


def test_a_deck_row_is_untouched_and_only_an_annual_report_statement_line_is_gated():
    rows = [{"record_type": "number", "status": "verified", "measure": "total_assets", "status_reason": ""}]
    obs.apply_number_gates(rows, "deck")
    assert rows[0]["status"] == "verified"
    call = [{"record_type": "number", "status": "verified", "measure": "pat", "status_reason": ""}]
    obs.apply_number_gates(call, "transcript")
    assert call[0]["status"] == "unverified" and "transcript_number" in call[0]["status_reason"]
    obs.apply_number_gates(rows, "annual_report")
    assert rows[0]["status"] == "unverified" and "ar_statement_line" in rows[0]["status_reason"]

