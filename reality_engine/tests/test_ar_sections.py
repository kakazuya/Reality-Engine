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
    assert (row["basis"], row.get("basis_source", "")) == ("standalone", "page_heading")
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


def test_ar_ckpt_0001_non_figures_and_outside_entities_are_unverified():
    """AR ckpt_0001 (25 Nov) J/W: page reference, clause number, label duration, industry projection."""
    def row(**kw):
        base = {"record_type": "number", "status": "verified", "unit": "", "entity_scope": "company",
                "printed_label": "", "period": "FY2025-26"}
        return {**base, **kw}
    rows = [row(measure="NEW:gri_disclosure_page_reference", printed_label="GRI 403-6", value=48.0),
            row(measure="NEW:internal_control_definition_clause_number", printed_label="(1)", value=1.0),
            row(measure="NEW:directorships_ceased_in_past_3_years", value=3.0, unit="years",
                printed_label="Listed companies from which ceased to be a director in the past 3 years"),
            row(measure="market.share", value=35.0, unit="%", entity_scope="industry",
                printed_label="organised retail projected to exceed 35% of the market"),
            # kept: a real figure, a portfolio fee, a customer split, and a 3-year count that is not the label's
            row(measure="revenue_from_operations", value=1200.0, unit="Rs crore", printed_label="Revenue"),
            row(measure="NEW:service_fees_for_management_of_assigned_portfolio_of_loans", value=18.35,
                unit="Rs crore", printed_label="Service fees for management of assigned portfolio of loans"),
            row(measure="NEW:top_10_customers_share", value=42.0, unit="%", entity_scope="customer"),
            row(measure="NEW:dividends_paid_past_3_years", value=12.5, unit="Rs crore",
                printed_label="Dividend paid in the past 3 years")]
    obs.apply_ar_row_gates(rows, "FY2025-26", "")
    assert [r["status"] for r in rows] == ["unverified"] * 4 + ["verified"] * 4
    assert rows[0]["status_reason"].startswith("ar_not_a_figure")
    assert rows[3]["status_reason"].startswith("ar_outside_entity")


def test_ar_duration_echo_variants_and_target_year_are_unverified():
    """T-242 follow-up: trailing/period duration echoes and target years (e.g. Net zero by 2040) are ar_not_a_figure."""
    def row(**kw):
        base = {"record_type": "number", "status": "verified", "unit": "", "entity_scope": "company",
                "printed_label": "", "period": "FY2025-26"}
        return {**base, **kw}

    unverified_rows = [
        # BAGFILMS shape + trailing/period duration variants across printed_label, period, measure
        row(measure="NEW:remuneration_period", value=5.0, unit="years",
            printed_label="a period of 5 years immediately preceding the balance sheet date"),
        row(measure="NEW:lookback_years", value=5.0, unit="years",
            printed_label="5 years immediately preceding"),
        row(measure="NEW:lookback_years", value=3.0, unit="",
            printed_label="three years ago"),
        row(measure="NEW:lookback_years", value=4.0, unit="",
            period="4 years before"),
        row(measure="NEW:period_of_five_years", value=5.0, unit="",
            printed_label="Bonus window"),
        row(measure="NEW:lookback_years", value=2.0, unit="",
            printed_label="2 years prior to listing"),
        # AMBUJACEM target-year shapes
        row(measure="NEW:net_zero_target", value=2040.0, unit="",
            printed_label="Net zero by 2040"),
        row(measure="NEW:emission_goal", value=2030.0, unit="year",
            printed_label="Goal"),
        row(measure="NEW:target_year", value=2035.0, unit="",
            printed_label="Carbon neutrality"),
    ]
    kept_rows = [
        row(measure="revenue_from_operations", value=2040.0, value_text="2,040", unit="Rs crore",
            printed_label="Revenue"),
        row(measure="employees", value=2040.0, unit="(count)", printed_label="Employees"),
        row(measure="NEW:dividends_paid_past_3_years", value=12.5, unit="Rs crore",
            printed_label="Dividend paid in the past 3 years"),
    ]
    all_rows = unverified_rows + kept_rows
    obs.apply_ar_row_gates(all_rows, "(Amount in Lakh) FY2025-26", "")
    assert [r["status"] for r in unverified_rows] == ["unverified"] * len(unverified_rows)
    assert all(r["status_reason"].startswith("ar_not_a_figure") for r in unverified_rows)
    assert [r["status"] for r in kept_rows] == ["verified"] * len(kept_rows)


def _make_recheck_ar_store(store_db: Path, symbol: str, name: str, doc_key: str,
                           page: int, text: str) -> None:
    store_db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(store_db)
    con.execute("CREATE TABLE company (symbol TEXT, name TEXT)")
    con.execute("CREATE TABLE doc (doc_key TEXT, title TEXT, symbol TEXT, doc_type TEXT, known_at TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT)")
    con.execute("INSERT INTO company VALUES (?,?)", (symbol, name))
    con.execute("INSERT INTO doc VALUES (?,?,?,?,?)", (doc_key, "Annual Report", symbol, "annual_report",
                                                       "2026-08-10T10:00:00"))
    con.execute("INSERT INTO doc_page VALUES (?,?,?)", (doc_key, page, text))
    con.commit()
    con.close()


def test_recheck_db_applies_ar_row_gates_to_verified_ar_rows(tmp_path: Path):
    store_db = tmp_path / "c306.db"
    doc_key = "D:/raw/APTUS/annual_report/ar26.pdf"
    page_text = "GRI 403-6 48 FY2025-26 Total assets 2,345.67 INR crore"
    _make_recheck_ar_store(store_db, "APTUS", "Aptus Value Housing Finance India Limited",
                           doc_key, 12, page_text)
    con = obs.create_db(tmp_path / "obs.db")
    try:
        con.execute(
            "INSERT INTO observation (symbol, doc_key, page, known_at, measure, printed_label, value, value_text,"
            " unit, scale, period, period_kind, entity_scope, new_definition, new_driver_node, status,"
            " status_reason, record_type, adjusted) VALUES"
            " ('APTUS', ?, 12, '2026-08-10T10:00:00', 'NEW:gri_disclosure_page_reference', 'GRI 403-6', 48.0, '48',"
            " '', 1.0, 'FY2025-26', 'actual', 'company', 'Page reference in GRI index', 'none', 'verified',"
            " '', 'number', 0)",
            (doc_key,),
        )
        con.execute(
            "INSERT INTO observation (symbol, doc_key, page, known_at, measure, printed_label, value, value_text,"
            " unit, unit_family, scale, period, period_kind, entity_scope, status, status_reason, record_type,"
            " adjusted) VALUES"
            " ('APTUS', ?, 12, '2026-08-10T10:00:00', 'total_assets', 'Total assets', 2345.67, '2,345.67',"
            " 'INR crore', 'money', 1e7, 'FY2025-26', 'instant', 'company', 'unverified',"
            " 'ar_statement_line: XBRL holds statement lines; served labelled', 'number', 0)",
            (doc_key,),
        )
        con.commit()
        stats = obs.recheck_db(con, [str(store_db)])
        rows = con.execute(
            "SELECT measure, status, status_reason FROM observation ORDER BY observation_id"
        ).fetchall()
        assert rows[0][0] == "NEW:gri_disclosure_page_reference"
        assert rows[0][1] == "unverified"
        assert "ar_not_a_figure" in rows[0][2]
        assert rows[1][0] == "total_assets" and rows[1][1] == "unverified"
        assert "ar_statement_line" in rows[1][2]
        assert stats["downgraded"] == 1
    finally:
        con.close()


def test_recheck_cli_stores_root_scans_every_store_beyond_default_sample(tmp_path: Path):
    stores_root = tmp_path / "universe"
    base_db = tmp_path / "base.db"
    out_db = tmp_path / "out.db"
    con = obs.create_db(base_db)
    try:
        for idx in range(1, 8):
            code = f"c{idx:02d}"
            symbol = f"CO{idx:02d}"
            doc_key = f"D:/raw/{symbol}/annual_report/ar26.pdf"
            _make_recheck_ar_store(stores_root / code / f"{code}.db", symbol, f"{symbol} Limited",
                                   doc_key, 5, "GRI 403-6 48 FY2025-26")
            con.execute(
                "INSERT INTO observation (symbol, doc_key, page, known_at, measure, printed_label, value,"
                " value_text, unit, scale, period, period_kind, entity_scope, new_definition, new_driver_node,"
                " status, status_reason, record_type, adjusted) VALUES"
                " (?, ?, 5, '2026-08-10T10:00:00', 'NEW:gri_disclosure_page_reference', 'GRI 403-6', 48.0, '48',"
                " '', 1.0, 'FY2025-26', 'actual', 'company', 'Page reference in GRI index', 'none', 'verified',"
                " '', 'number', 0)",
                (symbol, doc_key),
            )
        con.commit()
    finally:
        con.close()

    rc = obs.main(["--recheck", "--baseline", str(base_db), "--out", str(out_db),
                   "--stores-root", str(stores_root), "--doc-types", "annual_report"])
    assert rc == 0
    check = sqlite3.connect(f"file:{out_db.as_posix()}?mode=ro", uri=True)
    try:
        got = check.execute("SELECT symbol, status, status_reason FROM observation ORDER BY symbol").fetchall()
    finally:
        check.close()
    assert len(got) == 7
    assert all(status == "unverified" and "ar_not_a_figure" in reason for _sym, status, reason in got), got


# T-242: a continuation page takes the one basis its previous page's heading names (the commonest AR P cause).
CONSOLIDATED_HEAD = "Consolidated Financial Statements\nBalance Sheet as at 31 March 2026"


def test_ar_row_gate_carries_the_previous_pages_basis_onto_a_continuation_page():
    row = _gate_row(measure="NEW:unquoted_equity", printed_label="Unquoted equity", unit="Rs crore")
    obs.apply_ar_row_gates([row], "Unquoted equity 1,704.09 1,520.31", "",
                           previous_text=CONSOLIDATED_HEAD)
    assert (row["basis"], row.get("basis_source", "")) == ("consolidated", "previous_page_heading")


def test_ar_row_gate_does_not_carry_the_basis_onto_a_page_that_starts_a_note_or_statement():
    for head in ("Notes to the financial statements for the year ended 31 March 2026",
                 "Notes forming part of the Balance Sheet as at 31 March 2026",
                 "Note 12 Unquoted equity",
                 "Statement of Profit and Loss for the year ended 31 March 2026"):
        row = _gate_row(measure="NEW:unquoted_equity", printed_label="Unquoted equity", unit="Rs crore")
        obs.apply_ar_row_gates([row], head + "\nUnquoted equity 1,704.09 1,520.31", "",
                               previous_text=CONSOLIDATED_HEAD)
        assert (row["basis"], row.get("basis_source", "")) == ("", ""), head


def test_ar_row_gate_does_not_carry_the_basis_when_this_page_names_one_later_on():
    row = _gate_row(measure="NEW:unquoted_equity", printed_label="Unquoted equity", unit="Rs crore")
    body = ("Unquoted equity 1,704.09 1,520.31 "
            + "Revenue grew on strong demand across all segments. " * 8
            + "Details are in the standalone financial statements.")
    obs.apply_ar_row_gates([row], body, "", previous_text=CONSOLIDATED_HEAD)
    assert (row["basis"], row.get("basis_source", "")) == ("", "")


def test_ar_row_gate_does_not_carry_a_basis_the_previous_head_does_not_single_out():
    for previous in ("Standalone financial statements\nConsolidated financial statements", "",
                     "Unquoted equity 1,704.09 1,520.31"):
        row = _gate_row(measure="NEW:unquoted_equity", printed_label="Unquoted equity", unit="Rs crore")
        obs.apply_ar_row_gates([row], "Unquoted equity 1,704.09", "", previous_text=previous)
        assert (row["basis"], row.get("basis_source", "")) == ("", ""), previous


def test_ar_row_gate_never_replaces_a_stated_basis_with_the_previous_pages():
    row = _gate_row(measure="NEW:unquoted_equity", printed_label="Unquoted equity", unit="Rs crore",
                    basis="standalone")
    obs.apply_ar_row_gates([row], "Unquoted equity 1,704.09", "", previous_text=CONSOLIDATED_HEAD)
    assert (row["basis"], row.get("basis_source", "")) == ("standalone", "")


def test_ar_ckpt2_period_printed_and_relative_fy_resolved():
    """T-242 AR ckpt_0002: unprinted years (#46 AFSL, #49 63MOONS) go unverified; relative periods resolve to AR FY."""
    afsl = _gate_row(measure="count.shares", printed_label="Nirbhay Vassa", value_text="166,667",
                     unit="No. of shares", period="December 2019")
    moons = _gate_row(measure="shareholding_pct", printed_label="IEPF", value_text="0.23", unit="%",
                      period="March 2022")
    aiaeng = _gate_row(measure="NEW:total_differently_abled_employees_female",
                       printed_label="Total differently abled employees (D + E)", value_text="0",
                       period="end of Financial Year")
    during = _gate_row(measure="NEW:csr_amount_required", printed_label="CSR required", value_text="17.94",
                       period="during the year")
    beg = _gate_row(measure="shareholding_pct", printed_label="Promoter", value_text="50.0", unit="%",
                    period="beginning of the year")
    py_row = _gate_row(measure="count.shares", printed_label="Shares", value_text="100", period="P.Y.")
    non_cal = _gate_row(measure="capex", printed_label="Phase I capex", value_text="500", period="Phase I")
    kept = _gate_row(measure="shareholding_pct", printed_label="IEPF", value_text="0.23", unit="%",
                     period="As at 31 March 2026")
    qtr_fy = _gate_row(measure="NEW:orders", printed_label="Orders", value_text="410", period="Q4FY26")
    obs.apply_ar_row_gates([afsl, moons, aiaeng, during, beg, py_row, non_cal, kept, qtr_fy],
                           "Annual Report 2025-26 Shareholding Pattern As at 31 March 2026 Q4FY26", "")
    assert afsl["status"] == "unverified" and "period_not_printed" in afsl["status_reason"]
    assert moons["status"] == "unverified" and "period_not_printed" in moons["status_reason"]
    assert aiaeng["status"] == "verified" and aiaeng["period"] == "31 March 2026"
    assert during["status"] == "verified" and during["period"] == "FY2025-26"
    assert beg["status"] == "verified" and beg["period"] == "1 April 2025"
    assert py_row["status"] == "verified" and py_row["period"] == "FY2024-25"
    assert all(r["period_source"] == "ar_report_year" for r in (aiaeng, during, beg, py_row))
    assert non_cal["status"] == "verified" and non_cal["period"] == "Phase I"
    assert kept["status"] == "verified" and qtr_fy["status"] == "verified"

    # Without a discoverable split-year or year-ended date (single-year title), period and status stay unchanged
    single_rel = _gate_row(measure="NEW:csr", printed_label="CSR", value_text="10", period="during the year")
    no_fy_noncal = _gate_row(measure="NEW:energy", printed_label="Energy", value_text="10",
                             period="180-day monitoring period")
    obs.apply_ar_row_gates([single_rel, no_fy_noncal], "Annual Report 2025 plain text without year-end", "")
    assert single_rel["status"] == "verified" and single_rel["period"] == "during the year"
    assert single_rel.get("period_source", "") == ""
    assert no_fy_noncal["status"] == "verified" and no_fy_noncal["period"] == "180-day monitoring period"

    # ABB-style Jan-Dec AR (year ended 31 December 2025) resolves to CY2025 / 31 December 2025 / 1 January 2025
    abb_curr = _gate_row(measure="capex", printed_label="Capitalised", value_text="100", period="during the year")
    abb_end = _gate_row(measure="employees", printed_label="Employees", value_text="500",
                        period="end of Financial Year")
    abb_beg = _gate_row(measure="employees", printed_label="Employees", value_text="480",
                        period="beginning of the year")
    abb_prev = _gate_row(measure="capex", printed_label="Capitalised", value_text="90", period="P.Y.")
    obs.apply_ar_row_gates([abb_curr, abb_end, abb_beg, abb_prev],
                           "ABB India Limited\nFinancial year ended December 31, 2025", "")
    assert abb_curr["period"] == "CY2025" and abb_curr["status"] == "verified"
    assert abb_end["period"] == "31 December 2025" and abb_end["period_kind"] == "instant"
    assert abb_beg["period"] == "1 January 2025" and abb_beg["period_kind"] == "instant"
    assert abb_prev["period"] == "CY2024"
    assert all(r["period_source"] == "ar_report_year" for r in (abb_curr, abb_end, abb_beg, abb_prev))

    # Non-March non-December year end (e.g. Oct-Sep SIEMENS) resolves to that year end
    sep_curr = _gate_row(measure="capex", printed_label="Capex", value_text="50", period="during the year")
    sep_beg = _gate_row(measure="employees", printed_label="Employees", value_text="50",
                        period="beginning of the year")
    obs.apply_ar_row_gates([sep_curr, sep_beg], "Financial year ended 30 September 2025", "")
    assert sep_curr["period"] == "Year ended 30 September 2025"
    assert sep_beg["period"] == "1 October 2024" and sep_beg["period_kind"] == "instant"


def test_ar_ckpt2_previous_page_year_carries_over_and_instant_resolves():
    """T-242 AR ckpt_0002 counter-tests: previous page's year keeps row verified; instant label resolves no-year."""
    carried = _gate_row(measure="count.shares", printed_label="Shares", value_text="500",
                        period="Year ended March 31, 2025")
    obs.apply_ar_row_gates([carried], "Continuation table Shares 500", "",
                           previous_text="Statement for the Year ended March 31, 2025")
    assert carried["status"] == "verified"
    # Instant/label rule resolves 'end of Financial Year' to a printed date before apply_ar_row_gates runs
    built = obs.build_observations(
        symbol="TESTCO", doc_key="D:/x/annual_report/a.pdf", page=10, known_at="2026-08-10T10:00:00",
        page_text="Closing as on 31st March 2026 100",
        reply_rows=[_ar_reply(measure="count.shares", printed_label="Closing as on 31st March 2026",
                              printed_axis="", value_text="100", unit="shares",
                              period="end of Financial Year")],
    )
    obs.apply_number_gates(built, "annual_report", page_text="Closing as on 31st March 2026 100")
    assert built[0]["period"] == "March 2026" and built[0]["status"] == "verified"


def test_ar_ckpt2_date_as_value_is_dropped():
    """T-242 AR ckpt_0002: a number row whose value_text parses as a date is dropped whatever the measure."""
    rows = [
        _gate_row(measure="NEW:director_term_effective_date", printed_label="with effect from",
                  value_text="December 01, 2026", value=1.0, period="December 01, 2026"),
        _gate_row(measure="NEW:appointment_date", printed_label="Appointed on",
                  value_text="23.10.2024", value=23.10, period="2024-25"),
        _gate_row(measure="NEW:cutoff_date", printed_label="Cut-off",
                  value_text="31/03/2026", value=31.0, period="31/03/2026"),
        _gate_row(measure="NEW:effective_date", printed_label="Effective",
                  value_text="2026-03-31", value=2026.0, period="2026-03-31"),
        _gate_row(measure="count.shares", printed_label="Shares",
                  value_text="166,667", value=166667.0, period="As at 31 March 2026"),
    ]
    obs.apply_ar_row_gates(rows, "As at 31 March 2026 23.10.2024 31/03/2026 2026-03-31", "")
    assert len(rows) == 1 and rows[0]["value_text"] == "166,667"


def test_ar_ckpt2_prose_consolidated_basis_cleared_and_headings_kept():
    """T-242 AR ckpt_0002: consolidated from running prose (#39 5PAISA) is cleared; headings/titles stay."""
    prose = _gate_row(measure="count.shares", printed_label="Rights entitlement on 376 equity shares",
                      series_title="R. DETAILS OF UNCLAIMED SHARES OF THE COMPANY",
                      value_text="376", unit="equity shares", period="FY26", basis="consolidated")
    obs.apply_ar_row_gates([prose],
                           "S. DETAILS OF UNCLAIMED FRACTIONAL SHARES\n"
                           "However, 12,707 equity shares arose as fractional entitlements, which were consolidated, "
                           "sold in the market. FY26", "")
    assert prose["basis"] == "" and prose["basis_source"] == ""

    headed = _gate_row(measure="count.shares", printed_label="Shares", value_text="100",
                       period="FY26", basis="consolidated")
    obs.apply_ar_row_gates([headed],
                           "NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS\nFY26 Shares 100", "")
    assert headed["basis"] == "consolidated"

    wrapped_head = _gate_row(measure="count.shares", printed_label="Shares", value_text="100",
                             period="FY26", basis="consolidated")
    obs.apply_ar_row_gates([wrapped_head],
                           "NOTES TO ACCOUNTS FORMING PART OF CONSOLIDATED STATEMENT OF PROFIT AND LOSS\nFY26 Shares 100", "")
    assert wrapped_head["basis"] == "consolidated"

    stmt_head = _gate_row(measure="count.shares", printed_label="Shares", value_text="100",
                          series_title="Statement of Consolidated Profit and Loss", period="FY26",
                          basis="consolidated")
    obs.apply_ar_row_gates([stmt_head], "Statement of Consolidated Profit and Loss\nFY26 Shares 100", "")
    assert stmt_head["basis"] == "consolidated"

    titled = _gate_row(measure="count.shares", printed_label="Shares", value_text="100",
                       series_title="Consolidated Financial Highlights", period="FY26", basis="consolidated")
    obs.apply_ar_row_gates([titled], "FY26 Shares 100\nWhich were consolidated earlier.", "")
    assert titled["basis"] == "consolidated"


def test_ar_ckpt2_consolidated_subsidiary_scope_resets_when_label_names_none():
    """T-242 AR ckpt_0002: plain consolidated items reset to company; NCI/stake/Schedule III/entities stay."""
    bkt = _gate_row(measure="NEW:currency_sensitivity_strengthening_weakening_percentage",
                    printed_label="USD", series_title="Sensitivity analysis", value_text="3%", unit="%",
                    period="31st March, 2025", basis="consolidated", entity_scope="subsidiary")
    cash = _gate_row(measure="cash_and_cash_equivalents", printed_label="Cash and cash equivalents",
                     value_text="100", unit="Rs crore", period="31st March, 2025", basis="consolidated",
                     entity_scope="subsidiary")
    sub = _gate_row(measure="shareholding_pct", printed_label="Asian Paints (Vanuatu) Limited",
                    value_text="60.00", unit="%", period="31st March, 2025", basis="consolidated",
                    entity_scope="subsidiary")
    nci = _gate_row(measure="NEW:nci", printed_label="Non-controlling interest percentage",
                    value_text="25.0", unit="%", period="31st March, 2025", basis="consolidated",
                    entity_scope="subsidiary")
    stake = _gate_row(measure="shareholding_pct", printed_label="previously held 49.9% stake in BAIHAG",
                      value_text="49.9", unit="%", period="31st March, 2025", basis="consolidated",
                      entity_scope="subsidiary")
    fze = _gate_row(measure="revenue", printed_label="Accelya Middle East FZE",
                    value_text="50", unit="Rs crore", period="31st March, 2025", basis="consolidated",
                    entity_scope="subsidiary")
    sched3 = _gate_row(measure="net_worth", printed_label="Parent",
                       series_title="Additional Information to Consolidated Financial Statements",
                       value_text="1000", unit="Rs crore", period="31st March, 2025", basis="consolidated",
                       entity_scope="subsidiary")
    obs.apply_ar_row_gates([bkt, cash, sub, nci, stake, fze, sched3],
                           "Notes forming part of the Consolidated Financial Statements\nAs at 31st March, 2025",
                           "Balkrishna Industries Limited")
    assert bkt["entity_scope"] == "company"
    assert cash["entity_scope"] == "company"
    assert all(r["entity_scope"] == "subsidiary" for r in (sub, nci, stake, fze, sched3))


def test_ar_ckpt2_regrade_row_gates_and_negatives():
    """T-242 AR ckpt_0002 re-grade: rows 14, 18, 36, 37, 46, 48, 40, 57 gated/fixed; valid negatives stay."""
    # Row 14: ASIANHOTNR p184 'Notes annexed to and forming part of the Consolidated Financial Statements' keeps basis
    row14 = _gate_row(measure="NEW:contract_labour_and_services", printed_label="Contract labour and services",
                      series_title="29 Employee Benefit Expenses and Payment to Contractors",
                      value_text="1,396.99", unit="₹ in Lakhs", period="2024-2025", basis="consolidated")
    obs.apply_ar_row_gates(
        [row14],
        "Annual Report 2025-26 183\nNotes annexed to and forming part of the Consolidated Financial Statements "
        "for the year ended 31st March, 2026\n29 Employee Benefit Expenses\nContract labour and services 1,396.99\n"
        "consolidated earlier",
        "Asian Hotels (North) Limited",
    )
    assert row14["basis"] == "consolidated" and row14["basis_source"] == "page_heading"
    assert row14["status"] == "verified"

    # Row 18: BEMHY p165 MSME trade payables stored as headline trade_payables -> ar_subset_as_total
    row18 = _gate_row(measure="trade_payables", printed_label="- Due to Micro Enterprises & Small Enterprises",
                      series_title="5.23 Trade Payables", value_text="392.44", unit="₹ in Lakhs",
                      period="31-03-2025", segment="Due to Micro Enterprises & Small Enterprises")
    # Row 37: ABFRL p267 one class of preference shares stored as NEW:preference_share_capital -> ar_subset_as_total
    row37 = _gate_row(measure="NEW:preference_share_capital", printed_label="Preference shares of ` 10/- each",
                      series_title="NOTE 21 : EQUITY SHARE CAPITAL > Authorised share capital > Preference share capital",
                      value_text="10.00", unit="` in Crore", period="As at March 31, 2025")
    # Row 46: BANSWRAS p42 Yarn division stored as revenue_from_operations -> ar_subset_as_total
    row46 = _gate_row(measure="revenue_from_operations", printed_label="Yarn",
                      printed_axis="Revenue (Rs. In Crores)", group_path="SEGMENT-WISE PERFORMANCE",
                      value_text="459", unit="Rs. In Crores", period="2024-25", segment="Yarn")
    # Negatives for subset gate that must stay verified
    rev_tot = _gate_row(measure="revenue_from_operations", printed_label="Revenue from operations",
                        value_text="1,342", unit="Rs. In Crores", period="2025-26")
    tp_tot = _gate_row(measure="trade_payables", printed_label="Trade payables - Total",
                       series_title="5.23 Trade Payables", value_text="1,818.49", unit="₹ in Lakhs",
                       period="31-03-2025")
    obs.apply_ar_row_gates([row18, row37, row46, rev_tot, tp_tot],
                           "FY 2025-26 2024-25 31-03-2025 As at March 31, 2025", "")
    assert row18["status"] == "unverified" and "ar_subset_as_total" in row18["status_reason"]
    assert row37["status"] == "unverified" and "ar_subset_as_total" in row37["status_reason"]
    assert row46["status"] == "unverified" and "ar_subset_as_total" in row46["status_reason"]
    assert rev_tot["status"] == "verified" and tp_tot["status"] == "verified"

    # Row 36: ARVSMART p261 'Investments made during the year' stored as investments -> ar_flow_as_stock
    row36 = _gate_row(measure="investments", printed_label="Arvind Infracon LLP",
                      series_title="38. Related party transactions (contd.)",
                      group_path="Investments made during the year", value_text="1,400.80",
                      unit="INR Lakhs", period="March 31, 2026", entity_scope="subsidiary")
    inv_close = _gate_row(measure="investments", printed_label="Investments",
                          series_title="Note 6 : Investments", value_text="500.00",
                          unit="INR Lakhs", period="March 31, 2026")
    obs.apply_ar_row_gates([row36, inv_close],
                           "March 31, 2026\nInvestments made during the year\nArvind Infracon LLP 1,400.80\n"
                           "Note 6 : Investments\nInvestments 500.00", "")
    assert row36["status"] == "unverified" and "ar_flow_as_stock" in row36["status_reason"]
    assert inv_close["status"] == "verified"

    # Row 48: BHARTIARTL p190 non-current unsecured term loans stored as ..._current_net -> ar_current_mismatch
    row48 = _gate_row(measure="NEW:unsecured_term_loans_current_net", printed_label="Unsecured Term loans",
                      group_path="Non-current", value_text="1,095", unit="INR Million", period="March 31, 2026")
    cur_mat = _gate_row(measure="NEW:current_maturities_of_long_term_debt",
                        printed_label="Current maturities of long-term debt",
                        series_title="24 NON-CURRENT BORROWINGS", value_text="18,656",
                        unit="INR Million", period="March 31, 2026")
    obs.apply_ar_row_gates([row48, cur_mat], "March 31, 2026", "")
    assert row48["status"] == "unverified" and "ar_current_mismatch" in row48["status_reason"]
    assert cur_mat["status"] == "verified"

    # Row 40: BHARATWIRE p20 MD&A ratio tagged subsidiary (no MD&A in head) -> ar_subsidiary_unnamed
    row40 = _gate_row(measure="roe", printed_label="Return on Net worth", series_title="Ratios",
                      value_text="9.36%", unit="%", period="FY 2025-2026", entity_scope="subsidiary")
    obs.apply_ar_row_gates([row40], "Bharat Wire Ropes Limited\nVIII. Financial Performance\nFY 2025-2026 9.36%",
                           "Bharat Wire Ropes Limited")
    assert row40["status"] == "unverified" and "ar_subsidiary_unnamed" in row40["status_reason"]

    # Row 57: BHEL p92 Board Report captive solar tagged subsidiary -> entity_scope='company', stays verified
    row57 = _gate_row(measure="generation.volume",
                      printed_label="renewable energy output from captive solar installations reached",
                      value_text="44.21", unit="million units", period="FY 2025-26",
                      entity_scope="subsidiary", segment="renewable energy")
    obs.apply_ar_row_gates([row57], "FY 2025-26 renewable energy output 44.21\nANNUAL REPORT 2025-26\nBoard Report\n89",
                           "Bharat Heavy Electricals Limited")
    assert row57["entity_scope"] == "company" and row57.get("scope_source") == "no_subsidiary_named"
    assert row57["status"] == "verified"

    # Rule 5 negatives: named subsidiary, SpA/JV/AOC-1/related-party stay subsidiary and verified
    adani = _gate_row(measure="shareholding_pct", printed_label="Adani Agri Logistics (Darbhanga) Limited",
                      value_text="100%", unit="%", period="FY 2025-26", entity_scope="subsidiary")
    alkem = _gate_row(measure="revenue.value", printed_label="Ascend Laboratories SpA",
                      series_title="Details of Transactions with Related Parties",
                      value_text="1,910.4", unit="INR Lakhs", period="FY 2025-26", entity_scope="subsidiary")
    ajr = _gate_row(measure="ownership_stake_pct", printed_label="GIPL - GECPL JV",
                    series_title="Notes to Consolidated Financial Statements",
                    value_text="40.00%", unit="%", period="FY 2025-26", entity_scope="subsidiary")
    bosch = _gate_row(measure="count.shares", printed_label="Nos.",
                      series_title='Part "B": Associates and Joint Ventures',
                      value_text="6,400,000", unit="Nos.", period="FY 2025-26", entity_scope="subsidiary")
    obs.apply_ar_row_gates([adani, alkem, ajr, bosch], "FY 2025-26", "")
    assert all(r["entity_scope"] == "subsidiary" and r["status"] == "verified" for r in (adani, alkem, ajr, bosch))


# ------------------------------------------------- T-242 r4: entity scope from the page, junk ordinals (AR ckpt_0003)


def _r4_row(**kw):
    base = {"record_type": "number", "status": "verified", "unit": "", "entity_scope": "company",
            "printed_label": "", "period": "FY2025-26", "measure": "revenue_from_operations"}
    return {**base, **kw}


def test_ar_jv_scope_comes_from_the_page_and_an_unnamed_jv_figure_never_verifies():
    """Ckpt_0003 #11 BLIL p174 / #31 ATGL p283: a JV/associate note's unlabelled total is not the company's."""
    key = _r4_row(measure="NEW:capital_commitments", printed_label="Capital Commitments",
                  value=13941.76, unit="lakhs", value_text="13,941.76")
    excise = _r4_row(measure="excise_duty", printed_label="Excise Duty on Sale of Compressed Natural Gas",
                     value=263.08, unit="crore", value_text="263.08")
    obs.apply_ar_row_gates(
        [key, excise],
        "Notes to Consolidated Financial Statements FY2025-26\n46 Interest in Joint Venture Entities\n"
        "(` in crore) Particulars IndianOil-Adani Gas Private Limited\n"
        "Excise Duty on Sale of Compressed Natural Gas 263.08",
        "",
        previous_text="FY2025-26 (c) Interest in Associates and Joint Ventures of Balmer Lawrie & Co. Ltd.\n"
                      "Capital Commitments 13,941.76",
    )
    assert key["entity_scope"] == excise["entity_scope"] == "jv"
    assert key["status"] == "unverified" and "ar_jv_unnamed" in key["status_reason"]
    assert excise["status"] == "unverified" and "ar_jv_unnamed" in excise["status_reason"]

    # a JV figure whose own label names the entity stays verified, labelled
    named = _r4_row(measure="revenue.value", printed_label="Smartmeters Technologies Private Limited",
                    value=50.0, unit="crore", value_text="50")
    obs.apply_ar_row_gates([named], "FY2025-26\n46 Interest in Joint Venture Entities\n"
                                    "Smartmeters Technologies Private Limited 50", "")
    assert (named["entity_scope"], named["status"]) == ("jv", "verified")
    assert obs.gate_not_company([named]) == 0 and named["status"] == "verified"


def test_ar_parent_scope_without_a_printed_parent_is_unbacked():
    """Ckpt_0003 #15 BHATEXT p91: the AOC-2 rent row was tagged 'parent'; no parent company is printed."""
    row = _r4_row(measure="NEW:related_party_transaction_value",
                  printed_label="Jitendra Bhandari (Relatives of Directors & Key Management Personnel)",
                  value=3.0, unit="Lakhs", value_text="3.00", entity_scope="parent")
    obs.apply_ar_row_gates([row], "ANNEXURE -D FORM NO. AOC -2 FY2025-26\nName of the related party\n"
                                  "Jitendra Bhandari Rent 3.00 Lakhs", "")
    assert row["entity_scope"] == "company"
    assert row["status"] == "unverified" and "scope_unbacked" in row["status_reason"]

    keep = _r4_row(measure="revenue.value", printed_label="Revenue", value=100.0, unit="Rs crore",
                   value_text="100", entity_scope="parent")
    obs.apply_ar_row_gates([keep], "XYZ Holdings Limited, the parent company\nFY2025-26 Revenue 100", "")
    assert (keep["entity_scope"], keep["status"]) == ("parent", "verified")


def test_ar_subsidiary_holding_pct_in_a_subsidiaries_table_is_the_company_s_own_figure():
    """Ckpt_0003 #10 APOLLOHOSP p163: '% of holding' rows in the subsidiaries table are the Group's own."""
    stake = _r4_row(measure="ownership_stake_pct", printed_label="Apollo Dialysis Philippines Inc.",
                    value=69.2, unit="%", value_text="69.20%", entity_scope="subsidiary")
    obs.apply_ar_row_gates([stake], "FY2025-26\nName of the Subsidiary Country of Incorporation % of holding\n"
                                    "Step down subsidiaries\nApollo Dialysis Philippines Inc. 69.20%", "")
    assert stake["entity_scope"] == "company" and stake["status"] == "verified"

    # the page or the label is not a subsidiaries table: the entity's own figure keeps its scope
    rev = _r4_row(measure="revenue.value", printed_label="Ascend Laboratories SpA", value=1910.4,
                  unit="INR Lakhs", value_text="1,910.4", entity_scope="subsidiary")
    obs.apply_ar_row_gates([rev], "FY2025-26\nAscend Laboratories SpA 1,910.4", "")
    assert rev["entity_scope"] == "subsidiary" and rev["status"] == "verified"


def test_ar_junk_ordinals_are_dropped_not_served():
    """Ckpt_0003 J: '34th Annual Report' and 'consecutive term of five (5) years' are not figures."""
    edition = _r4_row(measure="NEW:annual_report_edition_number", printed_label="Annual Report",
                      value_text="34th", value=34.0, unit="")
    term = _r4_row(measure="NEW:director_term_duration",
                   printed_label="consecutive term of five (5) years, effective from March 25, 2025",
                   value_text="five (5)", value=5.0, unit="years")
    keep = _r4_row(measure="NEW:employee_average_tenure", printed_label="Average employee tenure",
                   value_text="4.5", value=4.5, unit="years")
    rows = [edition, term, keep]
    obs.apply_ar_row_gates(rows, "34th Annual Report 2025-26\nFY2025-26 Average employee tenure 4.5 years", "")
    assert rows == [keep]
    assert keep["status"] == "verified"


def test_ar_junk_r6_fy_tokens_and_boilerplate_counts_are_dropped_while_real_rows_survive():
    """AR r4 regrade #50 APOORVA p.20 and #52 ABLBL p.126 drop; real counts, column headers and unit rows stay."""
    # (a) bare FY token stored as first year (both AR and deck, with '' or 'Financial Year' pseudo-unit)
    fy_apoorva = _r4_row(
        measure="NEW:secretarial_audit_term_start", printed_label="i.e. from the Financial Year",
        value_text="2026-27", value=2026.0, unit="Financial Year", period="2026-27")
    fy_short = _r4_row(
        measure="NEW:auditor_appointment_fy", printed_label="from F.Y. 2026-2027",
        value_text="2026", value=2026.0, unit="", period="FY 2026-27")
    fy_page = _r4_row(
        measure="NEW:tenure_start", printed_label="Audit term start",
        value_text="2026-27", value=2026.0, unit="", period="2026-27")
    # (b) 'N (word)' boilerplate count in statutory-notice / publication / appointment sentence
    newspaper = _r4_row(
        measure="NEW:newspaper_edition_count",
        printed_label="All Editions - 1 (one) English language national daily newspaper",
        value_text="1", value=1.0, unit="English language national daily newspaper", period="FY 2025-26")
    quorum = _r4_row(
        measure="NEW:committee_quorum_members", printed_label="quorum of 2 (two) members",
        value_text="2", value=2.0, unit="", period="FY 2025-26")

    # Negatives that MUST survive:
    # 1) real "1 (one) Executive Director" count with a dictionary measure
    exec_dir = _r4_row(
        measure="count.employees", printed_label="1 (one) Executive Director",
        value_text="1", value=1.0, unit="", period="FY 2025-26")
    # 2) year column header value (a real count 2026 sitting under a "Financial Year 2026-27" column header)
    col_val = _r4_row(
        measure="NEW:active_dealers", printed_label="Active dealers",
        value_text="2026", value=2026.0, unit="", period="Financial Year 2026-27")
    # 3) a "Financial Year 2026-27" revenue row with a real unit
    fy_rev = _r4_row(
        measure="revenue.value", printed_label="Revenue for Financial Year 2026-27",
        value_text="2,026", value=2026.0, unit="INR Lakhs", period="FY 2026-27")
    fy_rev_new = _r4_row(
        measure="NEW:segment_revenue", printed_label="Revenue for Financial Year 2026-27",
        value_text="2,026", value=2026.0, unit="Rs crore", period="FY 2026-27")

    page = (
        "Financial Year 2026-27\nActive dealers 2026\n"
        "for a term of five (5) consecutive Financial Years, i.e. \n"
        "from the Financial Year 2026-27 till the Financial Year 2030-31\n"
        "All Editions - 1 (one) English language national daily newspaper\n"
        "quorum of 2 (two) members\n"
        "Corporate Affairs Committee comprised of 1 (one) Executive Director.\n"
        "Revenue for Financial Year 2026-27 2,026"
    )
    rows = [fy_apoorva, fy_short, fy_page, newspaper, quorum, exec_dir, col_val, fy_rev, fy_rev_new]
    obs.apply_ar_row_gates(rows, page, "")
    assert rows == [exec_dir, col_val, fy_rev, fy_rev_new]
    assert all(r["status"] == "verified" for r in rows)

    # Deck path shares junk_ordinal_reason too
    deck_rows = [dict(fy_apoorva), dict(newspaper), dict(fy_rev)]
    obs.apply_number_gates(deck_rows, "deck", page_text=page)
    assert len(deck_rows) == 1 and deck_rows[0]["measure"] == "revenue.value"




