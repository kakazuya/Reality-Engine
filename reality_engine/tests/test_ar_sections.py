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



def test_ar_gate_spares_off_statement_notes_and_dimensioned_rows():
    for m in ("contingent_liabilities", "NEW:contingent_liability_tax", "NEW:related_party_sales", "segment_revenue"):
        assert not obs.is_statement_line(m), m
    rows = [{"record_type": "number", "status": "verified", "status_reason": "", "measure": "revenue.value",
             "segment": "Cement"},
            {"record_type": "number", "status": "verified", "status_reason": "", "measure": "inventories"}]
    obs.apply_ar_statement_gate(rows)
    assert [r["status"] for r in rows] == ["verified", "unverified"]


# T-242: four script-catchable AR number errors (T-242 fresh grade: 7 of 60 verified rows wrong).
def _gate_row(**kw):
    row = {"record_type": "number", "status": "verified", "status_reason": "", "measure": "",
           "printed_label": "", "printed_axis": "", "series_title": "", "value_text": "1.00", "unit": "",
           "unit_family": "", "scale": 1.0, "basis": "", "new_driver_node": "",
           "entity_scope": "company", "segment": ""}
    row.update(kw)
    return row


def test_ar_row_gate_gates_an_ageing_bucket_stored_as_the_headline_measure():
    row = _gate_row(measure="trade_payables", printed_label="More than 3 years", unit="Lakh",
                    printed_axis="As at 31st March, 2025")
    obs.apply_ar_row_gates([row], "(Amount in Lakh)")
    assert row["status"] == "unverified" and "ar_qualified_label" in row["status_reason"]
    plain = _gate_row(measure="trade_payables", unit="Lakh",
                      printed_label="(ii) Total outstanding dues of creditors other than MSME")
    obs.apply_ar_row_gates([plain], "(Amount in Lakh)")
    assert plain["status"] == "verified"


def test_ar_row_gate_gates_a_related_party_transaction_stored_as_the_headline_measure():
    row = _gate_row(measure="raw_material_cost", unit="Lakh",
                    printed_label="Purchase of raw materials Beekaylon Synthetics Private Limited",
                    series_title="RELATED PARTY DISCLOSURES")
    obs.apply_ar_row_gates([row], "` In Lakhs")
    assert row["status"] == "unverified" and "ar_qualified_label" in row["status_reason"]
    # a party-only label is the row's dimension, not a mixed-up transaction: it stays
    for measure, label in (("loans", "A2Z Waste Management (Moradabad) Limited"),
                           ("shareholding_pct", "Asian Paints International Private Limited")):
        party = _gate_row(measure=measure, printed_label=label, unit="%")
        obs.apply_ar_row_gates([party], "")
        assert party["status"] == "verified", (measure, party["status_reason"])


def test_ar_row_gate_gates_a_narrative_change_label_with_no_measure():
    row = _gate_row(measure="profit_before_tax_growth_yoy", printed_label="an increase of", unit="%")
    obs.apply_ar_row_gates([row], "")
    assert row["status"] == "unverified" and "ar_narrative_growth" in row["status_reason"]
    for measure, label in (("pat_margin", "Net profit ratio"), ("gross_profit_growth_yoy", "Gross Margin")):
        named = _gate_row(measure=measure, printed_label=label, unit="%")
        obs.apply_ar_row_gates([named], "")
        assert named["status"] == "verified", (label, named["status_reason"])


def test_ar_row_gate_gates_an_unknown_unit_and_a_label_noun_as_the_unit():
    unknown = _gate_row(measure="raw_material_cost", printed_label="Purchase of raw materials", unit="`")
    obs.apply_ar_row_gates([unknown], "")
    assert unknown["status"] == "unverified" and "ar_unit_unknown" in unknown["status_reason"]
    noun = _gate_row(measure="NEW:current_maturities_vehicle_loans", printed_label="- vehicle loans",
                     unit="vehicle", new_driver_node="debt")
    obs.apply_ar_row_gates([noun], "")
    assert noun["status"] == "unverified" and "ar_unit_unknown" in noun["status_reason"]
    for unit, node in (("per equity share", "equity"), ("years", "equity")):
        ok = _gate_row(measure="NEW:share_premium_per_equity_share", printed_label="at a premium of",
                       unit=unit, new_driver_node=node)
        obs.apply_ar_row_gates([ok], "")
        assert ok["status"] == "verified", (unit, ok["status_reason"])


def test_ar_row_gate_fills_a_blank_unit_from_the_page_scale_note():
    money = _gate_row(measure="NEW:tax_on_other_disallowance", printed_label="(D) Other Disallowance")
    obs.apply_ar_row_gates([money], "Reconciliation (Rs.in lacs) 31.03.2025 (D) Other Disallowance 0.00")
    assert (money["unit"], money["scale"], money["status"]) == ("Lakhs", 1e5, "verified")
    ratio = _gate_row(measure="dscr", printed_label="Debt Service Coverage ratio (times)")
    obs.apply_ar_row_gates([ratio], "Ratio Analysis Current ratio (times) Debt Service Coverage ratio (times)")
    assert (ratio["unit"], ratio["scale"]) == ("Times", 1.0)
    shares = _gate_row(measure="count.shares", printed_label="No. of Shares")
    obs.apply_ar_row_gates([shares], "(Amount in Lakh)")
    assert shares["unit"] == ""                        # a count is never given a money page's scale
    ambiguous = _gate_row(measure="NEW:other_disallowance")
    obs.apply_ar_row_gates([ambiguous], "(₹ in million) (Amount in Lakh)")
    assert ambiguous["unit"] == ""                     # two scale notes prove nothing


def test_ar_row_gate_sets_the_basis_the_page_heading_prints():
    row = _gate_row(measure="NEW:trade_receivables_ageing_unbilled", printed_label="Undisputed - considered good",
                    printed_axis="Unbilled", unit="(₹ in million)", basis="consolidated")
    obs.apply_ar_row_gates([row], "Notes to the standalone financial statements for the year ended 31 March, 2026")
    assert (row["basis"], row["basis_source"]) == ("standalone", "page_heading")
    both = _gate_row(measure="NEW:trade_receivables_ageing_unbilled", printed_label="Undisputed", basis="consolidated")
    obs.apply_ar_row_gates([both], "Standalone financial statements\nConsolidated financial statements")
    assert both["basis"] == "consolidated"             # both headings: nothing to override with


def test_basis_mention_in_body_text_does_not_flip_a_row():
    from reality_engine.v2 import observations as o
    body = "Directors' Report. " + "Revenue grew on strong demand across all segments. " * 8 +         "Details are in the standalone financial statements."
    row = {"record_type": "number", "status": "verified", "basis": "consolidated", "measure": "revenue",
           "printed_label": "Revenue from operations", "unit": "Rs crore", "scale": 1e7, "value": 120.0}
    o.apply_ar_row_gates([row], body)
    assert row["basis"] == "consolidated"


# T-242 fresh2: a 'Net cash / EBITDA' chart (net cash is the opposite of debt) and a subsidiary's statements bound
# inside the parent's annual report (Blue Dart Aviation Limited's ROIC).
def test_ar_row_gate_gates_a_net_cash_chart_stored_as_net_debt():
    row = _gate_row(measure="net_debt_to_ebitda", series_title="Net cash / EBITDA", value_text="1.3")
    obs.apply_ar_row_gates([row], "Financial Highlights Net Cash (INR Mn) FY 26 1.3")
    assert row["status"] == "unverified" and row["status_reason"].startswith("ar_net_cash_sign:")
    # a net cash FLOW is a cash-flow line, not the net cash stock the measure signs the wrong way
    flow = _gate_row(measure="net_debt", printed_label="Net cash flow from operating activities")
    obs.apply_ar_row_gates([flow], "")
    assert flow["status"] == "verified"
    # a net-debt chart keeps its sign
    debt = _gate_row(measure="net_debt_to_ebitda", series_title="Net debt / EBITDA")
    obs.apply_ar_row_gates([debt], "")
    assert debt["status"] == "verified"


def test_ar_row_gate_unverifies_a_subsidiarys_statements_and_keeps_the_own_company():
    row = _gate_row(measure="NEW:return_on_invested_capital",
                    printed_label="Return on Invested Capital (ROIC)", unit="%", value_text="0.64%")
    obs.apply_ar_row_gates([row], "Blue Dart Aviation Limited\nNotes to the standalone financial statements\n"
                                  "Return on Invested Capital (ROIC) 0.64%", company="Blue Dart Express Limited")
    assert (row["entity_scope"], row["segment"]) == ("subsidiary", "Blue Dart Aviation Limited")
    assert row["status"] == "unverified" and row["status_reason"].startswith("ar_other_entity:")
    own = _gate_row(measure="NEW:return_on_invested_capital",
                    printed_label="Return on Invested Capital (ROIC)", unit="%", value_text="0.64%")
    obs.apply_ar_row_gates([own], "Blue Dart Express Limited Notes to the standalone financial statements\n"
                                  "Blue Dart Aviation Limited is a wholly owned subsidiary.\n"
                                  "Return on Invested Capital (ROIC) 0.64%", company="Blue Dart Express Limited")
    assert (own["entity_scope"], own["status"], own["segment"]) == ("company", "verified", "")
    # the store's name is abbreviated and its initials spaced: those are the company's own statement pages
    for printed, store_name in (("A. K. Capital Services Limited\nNOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS",
                                 "AK Capital Services Limited"),
                                ("The Bombay Dyeing and Manufacturing Company Limited | Annual Report 2025-26\n"
                                 "NOTES to the Consolidated Financial Statements",
                                 "Bombay Dyeing & Mfg Company Limited")):
        kept = _gate_row(measure="NEW:return_on_invested_capital", printed_label="ROIC", unit="%")
        obs.apply_ar_row_gates([kept], printed, company=store_name)
        assert (kept["entity_scope"], kept["status"]) == ("company", "verified"), (printed, kept["status_reason"])


def test_ar_row_gate_reads_a_bound_subsidiarys_running_header():
    # the W #57 page: the entity is named only in the printed running header, after its ratio table
    page = ("276\n37 FINANCIAL INSTRUMENTS\nReturn on Invested Capital (ROIC) 0.64%\n"
            "Notes forming part of Financial Statements as of and for the year ended March 31, 2026\n"
            "BLUE DART AVIATION LIMITED | FINANCIALS | ANNUAL REPORT 2025-2026\n")
    row = _gate_row(measure="NEW:return_on_invested_capital",
                    printed_label="Return on Invested Capital (ROIC)", unit="%", value_text="0.64%")
    obs.apply_ar_row_gates([row], page, company="Blue Dart Express Limited")
    assert (row["entity_scope"], row["segment"]) == ("subsidiary", "BLUE DART AVIATION LIMITED")
    assert row["status"] == "unverified" and "ar_other_entity" in row["status_reason"]
    # a page naming only the store company stays company scope
    own = _gate_row(measure="NEW:return_on_invested_capital",
                    printed_label="Return on Invested Capital (ROIC)", unit="%", value_text="0.64%")
    obs.apply_ar_row_gates([own], "BLUE DART EXPRESS LIMITED | FINANCIALS | ANNUAL REPORT 2025-2026\n"
                                  "Return on Invested Capital (ROIC) 0.64%", company="Blue Dart Express Limited")
    assert (own["entity_scope"], own["status"]) == ("company", "verified")


def test_parent_name_plus_words_is_another_entity():
    from reality_engine.v2.observations import _is_own_entity
    assert not _is_own_entity("Tata Motors Finance Limited", "Tata Motors Limited")
    assert _is_own_entity("The Bombay Dyeing and Manufacturing Company Limited", "Bombay Dyeing & Mfg Company Limited")
    assert _is_own_entity("A. K. Capital Services Limited", "AK Capital Services Limited")
