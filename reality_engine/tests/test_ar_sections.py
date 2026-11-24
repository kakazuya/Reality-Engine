from reality_engine.v2 import ar_sections as ars


def test_drop_heading_beats_keep_words():
    assert ars.section_of("INDEPENDENT AUDITOR'S REPORT ... contingent liabilities") == ("auditor_report", False)


def test_keep_mdna_and_note_lower_on_page():
    assert ars.keep("Management Discussion and Analysis Industry overview revenue grew")
    assert ars.section_of("Notes to accounts 31 March 2026 ... 38 Contingent liabilities and commitments")[0] == \
        "notes_offbalance"


def test_unrecognised_page_continues_running_section_then_stops():
    pages = [(10, "Management Discussion and Analysis"), (11, "plain text no heading"),
             (12, "more plain text"), (13, "Report on Corporate Governance"), (14, "plain text")]
    assert ars.kept_pages(pages) == {10: "mdna", 11: "mdna", 12: "mdna"}
