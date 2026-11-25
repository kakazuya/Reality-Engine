"""T-242: deck guards from the 60-row deck pilot grade (D:/RealityEngine/t242/deck_grade/deck_grade.md)."""
from __future__ import annotations

from reality_engine.v2 import observations as obs

DOC = "D:/x/investor_presentation/abc.pdf"


def _rows(page_text, reply, page=5, deck=True):
    return obs.build_observations(symbol="JKPAPER", doc_key=DOC, page=page, known_at="2026-08-10T10:00:00",
                                  page_text=page_text, reply_rows=reply, deck_guards=deck)


def test_decrease_word_makes_a_growth_row_negative_on_decks_only():
    text = "Pulp & Paper segment Q1 FY27: EBITDA decreased 79% YoY on lower realisations."
    reply = [{"type": "number", "measure": "ebitda_growth_yoy", "printed_label": "EBITDA decreased",
              "value_text": "79%", "unit": "%", "period": "Q1 FY27"}]
    assert _rows(text, reply)[0]["value"] == -79.0
    assert _rows(text, reply, deck=False)[0]["value"] == 79.0
    up = "EBITDA increased 12% YoY."
    assert _rows(up, [{"type": "number", "measure": "ebitda_growth_yoy", "printed_label": "EBITDA increased",
                       "value_text": "12%", "unit": "%", "period": "Q1 FY27"}])[0]["value"] == 12.0
    other = "Costs declined; revenue grew 12% YoY."          # Eagle: another clause's word never flips the value
    assert _rows(other, [{"type": "number", "measure": "revenue_growth_yoy", "printed_label": "revenue grew",
                          "value_text": "12%", "unit": "%", "period": "Q1 FY27"}])[0]["value"] == 12.0


def test_deck_cover_letter_page_gives_no_rows():
    text = ("Scrip Code: 532162 Sub: Investor Presentation under Regulation 30. Dear Sir/Madam, please find enclosed "
            "the investor presentation.")
    reply = [{"type": "number", "measure": "NEW:sebi_regulation_number", "printed_label": "Regulation",
              "value_text": "30", "unit": "", "period": "Q1 FY27"}]
    assert _rows(text, reply, page=1) == []


def test_new_measure_without_unit_is_never_verified():
    text = "Profit as per IGAAP 845 Profit as per Ind AS 812 Q1 FY27"
    rows = _rows(text, [{"type": "number", "measure": "NEW:profit_as_per_igaap", "printed_label": "Profit as per IGAAP",
                         "value_text": "845", "unit": "", "period": "Q1 FY27",
                         "new_definition": "x", "new_driver_node": "none"}])
    assert rows and rows[0]["status"] != "verified" and "no_unit" in rows[0]["status_reason"]


def test_industry_scope_is_never_verified_on_decks():
    text = "Central Govt. Capex (Rs Bn) FY26 11,110 Source: Union Budget"
    rows = _rows(text, [{"type": "number", "measure": "capex", "printed_label": "Central Govt. Capex",
                         "value_text": "11,110", "unit": "Rs Bn", "period": "FY26", "entity_scope": "country"}])
    assert rows and rows[0]["status"] != "verified" and "not_company" in rows[0]["status_reason"]


def test_deck_prompt_names_the_company_and_ar_prompt_is_unchanged():
    from reality_engine.v2 import observations as o
    deck = o.template_for("deck")
    assert "{company}" in deck and "{company}" not in o.template_for("annual_report")
    text = deck.format(dictionary="", text="", known_at="", call_quarter="", company="ACC Limited", symbol="ACC")
    assert "by ACC Limited (ACC)" in text and '"peer" for any other company' in text


def test_unnamed_subsidiary_row_is_not_verified_on_decks():
    rows = _rows("RBIC EBITDA margin 12.5%", [{"type": "number", "measure": "ebitda_margin",
                 "printed_label": "EBITDA margin", "value_text": "12.5%", "unit": "%", "period": "FY26",
                 "entity_scope": "subsidiary"}])
    assert rows and rows[0]["status"] != "verified" and "subsidiary_unnamed" in rows[0]["status_reason"]


def test_group_scope_on_a_deck_is_a_peer_never_verified():
    rows = _rows("Consolidated Balance Sheet Share capital 494", [{"type": "number", "measure": "share_capital",
                 "printed_label": "Share capital", "value_text": "494", "unit": "Rs crore", "period": "FY26",
                 "entity_scope": "group"}])
    assert rows and rows[0]["entity_scope"] == "peer" and rows[0]["status"] != "verified"


def test_parts_sum_does_not_reverify_a_market_figure_on_decks():
    text = "Premium Liquor Market in India (USD Bn) Rum 10 Gin 21 Total 31"
    reply = [{"type": "number", "series_id": "s1", "measure": "market.value", "printed_label": lab, "value_text": v,
              "unit": "USD Bn", "period": "FY26", "entity_scope": "country", "is_total": tot}
             for lab, v, tot in (("Rum", "10", False), ("Gin", "21", False), ("Total", "31", True))]
    rows = _rows(text, reply)
    assert rows and all(r["status"] != "verified" for r in rows)


def test_printed_range_serves_both_ends():
    text = "Group revenue run-rate to approximately ₹22–25 Crore in FY26"
    reply = [{"type": "number", "measure": "NEW:group_revenue_run_rate",
              "printed_label": "Group revenue run-rate", "value_text": "₹22–25 Crore", "unit": "Crore",
              "period": "FY26"}]
    row = _rows(text, reply)[0]
    assert row["value"] == 22.0 and row["value_high"] == 25.0
    assert "range" in row["status_reason"]


def test_percent_range_fills_the_high_end():
    text = "EBITDA margin expanded to 22–25% in FY26"
    reply = [{"type": "number", "measure": "ebitda_margin", "printed_label": "EBITDA margin",
              "value_text": "22–25%", "unit": "%", "period": "FY26"}]
    row = _rows(text, reply)[0]
    assert row["value"] == 22.0 and row["value_high"] == 25.0


def test_minus_and_period_text_are_not_ranges():
    for value_text in ("-25%", "FY25-26", "2025-26", "Q1-Q2"):
        rows = _rows(f"Margin {value_text} FY26",
                     [{"type": "number", "measure": "ebitda_margin", "printed_label": "Margin",
                       "value_text": value_text, "unit": "%", "period": "FY26"}])
        assert rows and rows[0]["value_high"] is None, value_text


def test_date_value_is_never_a_verified_quantity():
    text = "Start of Production (SOP): Q1 FY28"
    rows = _rows(text, [{"type": "number", "measure": "NEW:start_of_production_quarter",
                         "printed_label": "Start of Production (SOP)", "value_text": "Q1 FY28", "unit": "",
                         "period": "FY26", "new_definition": "quarter production starts",
                         "new_driver_node": "capacity"}])
    assert rows and rows[0]["status"] != "verified"
    assert "date_value:" in rows[0]["status_reason"]


def test_plain_value_has_no_high_end():
    text = "Revenue ₹22 Crore FY26"
    row = _rows(text, [{"type": "number", "measure": "revenue.value", "printed_label": "Revenue",
                        "value_text": "22", "unit": "Crore", "period": "FY26"}])[0]
    assert row["value"] == 22.0 and row["value_high"] is None



def test_nine_million_is_not_a_period():
    from reality_engine.v2.observations import deck_date_value
    assert not deck_date_value("9M", "customers") and not deck_date_value("9M", "")
    assert deck_date_value("9M FY27", "") and deck_date_value("9MFY26", "")


def test_deck_page_footnote_pairs_each_period_with_its_basis():
    """BAIKAKAJI p33 (obs 30422): the footer prints FY26 CONSOLIDATED, FY25 STANDALONE, so the page-level rule
    stored the FY26 column as standalone.  Each period takes its own basis."""
    text = ("BALANCE SHEET\nEQUITY & LIABILITIES\n\u20b9 CR\nFY26\nFY25\n"
            "Share capital\n21.40\n2.25\nOther current liab. & provisions\n11.37\n22.99\n"
            "AUDITED \u00b7 AS AT 31 MAR \u00b7 FY26 CONSOLIDATED, FY25 STANDALONE \u00b7 ALL FIGURES IN \u20b9 CR")
    reply = [{"type": "number", "measure": "other_liabilities_and_provisions",
              "printed_label": "Other current liab. & provisions", "value_text": "11.37", "unit": "Rs crore",
              "period": "FY26"},
             {"type": "number", "measure": "other_liabilities_and_provisions",
              "printed_label": "Other current liab. & provisions", "value_text": "22.99", "unit": "Rs crore",
              "period": "FY25"},
             {"type": "number", "measure": "share_capital", "printed_label": "Share capital",
              "value_text": "21.40", "unit": "Rs crore", "period": "FY 2025-26"},
             {"type": "number", "measure": "share_capital", "printed_label": "Share capital",
              "value_text": "2.25", "unit": "Rs crore", "period": "FY25"}]
    rows = _rows(text, reply)
    assert [r["basis"] for r in rows] == ["consolidated", "standalone", "consolidated", "standalone"]
    assert {r["basis_source"] for r in rows} == {"page_footnote"}
    from reality_engine.v2.observations import fiscal_year_key
    assert fiscal_year_key("FY26") == fiscal_year_key("FY2026") == fiscal_year_key("FY 2025-26") == "26"


def test_deck_page_with_one_consolidated_heading_is_untouched():
    text = "Consolidated Balance Sheet\nShare capital\n494\nFY26"
    reply = [{"type": "number", "measure": "share_capital", "printed_label": "Share capital",
              "value_text": "494", "unit": "Rs crore", "period": "FY26"}]
    row = _rows(text, reply)[0]
    assert row["basis"] == "consolidated" and row["basis_source"] != "page_footnote"
    one_pair = _rows("Share capital 494 FY26\nFY26 figures are consolidated", reply)[0]
    assert one_pair["basis_source"] != "page_footnote"      # a single pairing is not this rule


def test_deck_period_not_in_the_footnote_pairing_is_untouched():
    text = "Revenue\n100\n90\nFY26 CONSOLIDATED, FY25 STANDALONE"
    reply = [{"type": "number", "measure": "revenue.value", "printed_label": "Revenue",
              "value_text": "100", "unit": "Rs crore", "period": "FY26"},
             {"type": "number", "measure": "revenue.value", "printed_label": "Revenue",
              "value_text": "90", "unit": "Rs crore", "period": "FY24"}]
    rows = _rows(text, reply)
    assert rows[0]["basis"] == "consolidated" and rows[0]["basis_source"] == "page_footnote"
    # FY24 is not in the pairing: it keeps the page-level result and no page_footnote source
    assert rows[1]["basis"] == "standalone" and rows[1]["basis_source"] == ""


# --------------------------------------------------------------------------- T-242 audit_deck1 gates (3 rules)


def _deck_row(**kw):
    row = {"record_type": "number", "status": "verified", "status_reason": "", "measure": "revenue.value",
           "printed_label": "Revenue", "value": 1234.0, "value_text": "1,234", "unit": "Rs Cr",
           "period": "FY26", "basis": "", "basis_source": ""}
    row.update(kw)
    return row


def test_deck_bound_gates_floors_and_bounds_but_keeps_exact_values():
    # Positive audit cases: BANKBARODA '>10,000 ATMs' and AEQUS '>100% YoY'
    atms = _deck_row(measure="count.atms", printed_label="ATMs", value=10000.0, value_text=">10,000", unit="ATMs")
    yoy = _deck_row(measure="revenue_growth_yoy", printed_label="Consumer Revenue", value=100.0,
                    value_text=">100% YoY", unit="%")
    lbl_bound = _deck_row(measure="count.atms", printed_label=">10,000 ATMs and Cash Recyclers",
                          value=10000.0, value_text="10,000", unit="ATMs")
    for tok_row in (
        _deck_row(value_text="≤ 5%", value=5.0, unit="%"),
        _deck_row(value_text="≥10", value=10.0),
        _deck_row(value_text=">=10", value=10.0),
        _deck_row(value_text="<=5%", value=5.0, unit="%"),
        _deck_row(value_text="<5%", value=5.0, unit="%"),
        _deck_row(value_text="up to 25%", value=25.0, unit="%"),
        _deck_row(value_text="upto 25%", value=25.0, unit="%"),
        _deck_row(printed_label="Order book of over", value_text="Rs. 350", value=350.0),
        _deck_row(printed_label="EBITDA margin stayed below", value_text="15%", value=15.0, unit="%"),
        _deck_row(printed_label="Sales less than", value_text="100", value=100.0),
        _deck_row(printed_label="Sales more than", value_text="100", value=100.0),
        _deck_row(printed_label="Margin above", value_text="20%", value=20.0, unit="%"),
        _deck_row(printed_label="Revenue at least", value_text="500", value=500.0),
        _deck_row(printed_label="Revenue exceeding", value_text="500", value=500.0),
    ):
        assert obs.deck_bound_reason(tok_row).startswith("deck_bound_not_exact:"), tok_row
    rows = [atms, yoy, lbl_bound]
    obs.apply_number_gates(rows, "deck")
    assert all(r["status"] == "unverified" and "deck_bound_not_exact:" in r["status_reason"] for r in rows)

    # Negative cases that must stay verified (including '~', 'nearly', 'approx' approximations)
    exact = _deck_row(measure="revenue.value", printed_label="Revenue", value=1234.0, value_text="1,234")
    tilde_exp = _deck_row(measure="NEW:cumulative_positive_outcomes_exposure",
                          printed_label="Cumulative Exposure", value=61348.0, value_text="~₹61,348")
    tilde_nw = _deck_row(measure="total_equity", printed_label="net worth",
                         value=14727.8, value_text="~Rs. 14,727.8 Cr")
    nearly_row = _deck_row(measure="NEW:operating_profit_growth_yoy",
                           printed_label="Decorative business delivered nearly 20% growth in operating profit",
                           value=20.0, value_text="20%", unit="%")
    approx_row = _deck_row(printed_label="Installed capacity of approx.", value_text="500", value=500.0)
    other_above = _deck_row(measure="other_bank_balances",
                            printed_label="(iii) Bank balances other than (ii) above",
                            value=707.0, value_text="707")
    bucket = _deck_row(measure="NEW:asset_liability_maturity_outflow", printed_label="<3 Months",
                       value=1406.0, value_text="1,406")
    other_num = _deck_row(measure="count.schools",
                          printed_label="school science labs equipped, benefiting >5,000 students",
                          value=7.0, value_text="7", unit="schools")
    neg_rows = [exact, tilde_exp, tilde_nw, nearly_row, approx_row, other_above, bucket, other_num]
    obs.apply_number_gates(neg_rows, "deck")
    assert all(r["status"] == "verified" for r in neg_rows), [(r["value_text"], r["status_reason"]) for r in neg_rows]


def test_deck_combined_label_gates_split_measures_and_keeps_allowlist():
    # Positive catches (one combined figure per row/column):
    assoc = _deck_row(measure="share_of_profit_of_jv_and_associates",
                      printed_label="Other income & share of associate", value=8.4, value_text="8.4")
    atms = _deck_row(measure="count.atms", printed_label="ATMs and cash recyclers",
                     value=12796.0, value_text="12,796", unit="ATMs")
    goodwill = _deck_row(measure="goodwill", printed_label="Goodwill & Intangibles Assets",
                         value=15175.0, value_text="15,175")
    tci = _deck_row(measure="total_comprehensive_income",
                    printed_label="Revenue + Other Comprehensive Income", value=300.8, value_text="300.8")
    obs.apply_number_gates([assoc], "deck", page_text="Other income & share of associate\n8.4\n16.5")
    obs.apply_number_gates([atms], "deck", page_text="the Bank had 12,796 ATMs and cash recyclers across India.")
    obs.apply_number_gates([goodwill], "deck", page_text="Goodwill & Intangibles Assets\n15,175")
    obs.apply_number_gates([tci], "deck", page_text="Revenue + Other Comprehensive Income\n300.8")
    right_catches = [assoc, atms, goodwill, tci]
    assert all(r["status"] == "unverified" and "deck_combined_label:" in r["status_reason"] for r in right_catches), [
        (r["printed_label"], r["status"], r["status_reason"]) for r in right_catches
    ]

    # Four round-3 right cases that must stay verified:
    # 1) 'EBITDA and PAT margins for Q2 stood at 22.1% / 10.5%'
    asahi_page = "EBITDA and PAT margins for Q2 stood at 22.1% and 10.5%, respectively."
    asahi_ebitda = _deck_row(measure="ebitda_margin", printed_label="EBITDA and PAT margins for Q2 stood at",
                             value=22.1, value_text="22.1%", unit="%")
    asahi_pat = _deck_row(measure="pat_margin", printed_label="EBITDA and PAT margins for Q2 stood at",
                          value=10.5, value_text="10.5%", unit="%")
    obs.apply_number_gates([asahi_ebitda, asahi_pat], "deck", page_text=asahi_page)
    assert asahi_ebitda["status"] == "verified" and asahi_pat["status"] == "verified"

    # 2) 'GNPA & NNPA stood at 0.29% and 0.12%'
    bajaj_page = "16. GNPA & NNPA stood at 0.29% and 0.12% as of 30 June 2026."
    bajaj_gnpa = _deck_row(measure="gnpa_pct", printed_label="GNPA & NNPA stood at",
                           value=0.29, value_text="0.29%", unit="%")
    bajaj_nnpa = _deck_row(measure="nnpa_pct", printed_label="GNPA & NNPA stood at 0.29% and",
                           value=0.12, value_text="0.12%", unit="%")
    obs.apply_number_gates([bajaj_gnpa, bajaj_nnpa], "deck", page_text=bajaj_page)
    assert bajaj_gnpa["status"] == "verified" and bajaj_nnpa["status"] == "verified"

    # 3) 'EBIT Margin & PBT Margin ... 8.0%'
    crompton_page = "EBIT Margin & PBT Margin expanded by 10 bps to 8.0% and 30 bps to 6.5%"
    crompton_ebit = _deck_row(measure="ebit_margin", printed_label="EBIT Margin & PBT Margin expanded by 10 bps to",
                              value=8.0, value_text="8.0%", unit="%")
    obs.apply_number_gates([crompton_ebit], "deck", page_text=crompton_page)
    assert crompton_ebit["status"] == "verified"

    # 4) 'EBITDA & EBITDA Margin' column header -> ebitda 531 (and 'EBITDA & Margin')
    bbox_ebitda = _deck_row(measure="ebitda", printed_label="EBITDA & Margin", value=531.0, value_text="531")
    aequs_ebitda = _deck_row(measure="ebitda", printed_label="EBITDA & EBITDA Margin", value=215.0, value_text="215")
    obs.apply_number_gates([bbox_ebitda, aequs_ebitda], "deck", page_text="EBITDA & EBITDA Margin\n215")
    assert bbox_ebitda["status"] == "verified" and aequs_ebitda["status"] == "verified"

    # Negative cases, single-term allowlist, and all wrongly caught labels from Wolf's review (must stay verified)
    kept = [
        _deck_row(measure="revenue.value", printed_label="Revenue", value=1234.0, value_text="1,234"),
        _deck_row(measure="NEW:rd_spend", printed_label="R&D spend", value=45.0, value_text="45"),
        _deck_row(measure="profit_before_tax", printed_label="Profit & Loss before tax", value=90.0, value_text="90"),
        _deck_row(measure="revenue.value", printed_label="Oil & Gas segment revenue", value=200.0, value_text="200"),
        _deck_row(measure="depreciation_and_amortisation_expense",
                  printed_label="Depreciation & Amortisation", value=24.2, value_text="24.2"),
        _deck_row(measure="exceptional_items",
                  printed_label="Exceptional & Extraordinary items", value=12.0, value_text="12"),
        _deck_row(measure="total_equity_and_liabilities",
                  printed_label="Total equity and liabilities", value=500.0, value_text="500"),
        _deck_row(measure="NEW:instagram_followers",
                  printed_label="Digital Milestone: 1M+ Instagram Followers", value=1000000.0, value_text="1M"),
        _deck_row(measure="changes_in_inventories",
                  printed_label="Change in inventories of Finished goods, W.I.P. and stock-in-trade",
                  value=-1822.0, value_text="(1,822)"),
        _deck_row(measure="other_expenses", printed_label="Admin and Other Costs", value=118.0, value_text="118"),
        _deck_row(measure="NEW:industry_npa", printed_label="Basic Metals & Metal Industry",
                  value=437.0, value_text="437"),
        _deck_row(measure="count.employees",
                  printed_label="Employees Dedicated to Design, Engineering & Development",
                  value=66.0, value_text="66"),
        _deck_row(measure="NEW:child_care_units_supported",
                  printed_label="Child Care Units supported with education and livelihood programs",
                  value=27.0, value_text="27"),
        _deck_row(measure="changes_in_payables",
                  printed_label="Change in Payables and Other Liabilities", value=-25.0, value_text="(25)"),
        _deck_row(measure="count.states", printed_label="Branches across 18 states and 3 UTs",
                  value=18.0, value_text="18"),
        _deck_row(measure="count.stores", printed_label="Stores in Bihar + Jharkhand + UP",
                  value=207.0, value_text="207"),
        _deck_row(measure="ebitda_margin",
                  printed_label="Healthy Revenue Growth with 35.0% Gross Margin & 13.0% EBITDA Margin",
                  value=13.0, value_text="13.0%", unit="%"),
        _deck_row(measure="profit_before_exceptional_items_and_tax",
                  printed_label="Profit before tax and share of profit/(loss) from JV and exceptional items",
                  value=466.0, value_text="466"),
    ]
    obs.apply_number_gates(kept, "deck")
    assert all(r["status"] == "verified" for r in kept), [(r["printed_label"], r["status_reason"]) for r in kept]


def test_deck_heading_basis_fills_empty_basis_and_documents_starred_column():
    # Positive audit case: BLUESTONE p40 (id 32)
    bluestone_page = ("39\n39\nCash Flow Statement\nConsolidated | INR mn\n"
                      "Cash and cash equivalents at the beginning of the year 487.75")
    row = _deck_row(measure="opening_cash_and_cash_equivalents",
                    printed_label="Cash and cash equivalents at the beginning of the year",
                    value=487.75, value_text="487.75", basis="", basis_source="")
    obs.apply_number_gates([row], "deck", page_text=bluestone_page)
    assert (row["basis"], row["basis_source"], row["status"]) == ("consolidated", "page_heading", "verified")

    # Standalone in first 300 chars
    stand_row = _deck_row(basis="", basis_source="")
    obs.apply_number_gates([stand_row], "deck", page_text="Standalone Financial Highlights\nRevenue 1,234")
    assert (stand_row["basis"], stand_row["basis_source"]) == ("standalone", "page_heading")

    # Negative cases: both bases, existing basis, basis beyond 300 chars
    both = _deck_row(basis="", basis_source="")
    obs.apply_number_gates([both], "deck", page_text="Standalone and Consolidated Results\nRevenue 1,234")
    assert (both["basis"], both["basis_source"]) == ("", "")

    preset = _deck_row(basis="standalone", basis_source="page_footnote")
    obs.apply_number_gates([preset], "deck", page_text="Consolidated Results\nRevenue 1,234")
    assert (preset["basis"], preset["basis_source"]) == ("standalone", "page_footnote")

    late = _deck_row(basis="", basis_source="")
    obs.apply_number_gates([late], "deck", page_text=("Revenue 1,234. " * 25) + "Consolidated results.")
    assert (late["basis"], late["basis_source"]) == ("", "")

    # Known starred-column case (ALLTIME p12, audit id 3): unstarred H1FY27 column stored as consolidated
    # under '*Consolidated' footer; rule intentionally leaves it untouched.
    alltime_page = ("Cashflow Statement\nParticulars (Rs. Cr)\nH1FY27*\nH1FY27\nH1FY26\n"
                    "Cash and cash equivalents at the end of the period\n47.4\n46.0\n136.1\n11\n*Consolidated")
    starred = _deck_row(measure="cash_and_cash_equivalents",
                        printed_label="Cash and cash equivalents at the end of the period",
                        value=46.0, value_text="46.0", period="H1FY27", basis="consolidated", basis_source="")
    obs.apply_number_gates([starred], "deck", page_text=alltime_page)
    assert (starred["basis"], starred["basis_source"], starred["status"]) == ("consolidated", "", "verified")


def test_recheck_db_applies_deck_row_gates(tmp_path):
    import sqlite3
    store_db = tmp_path / "store.db"
    scon = sqlite3.connect(store_db)
    scon.executescript(
        "CREATE TABLE company(symbol TEXT, name TEXT);"
        "CREATE TABLE doc(doc_key TEXT, symbol TEXT, doc_type TEXT, known_at TEXT);"
        "CREATE TABLE doc_page(doc_key TEXT, page INTEGER, text TEXT);"
    )
    scon.execute("INSERT INTO company VALUES ('BLUESTONE', 'BlueStone Jewellery')")
    scon.execute("INSERT INTO doc VALUES ('d.pdf', 'BLUESTONE', 'deck', '2026-08-10T10:00:00')")
    page_text = (
        "39\n39\nCash Flow Statement\nConsolidated | INR mn\n"
        "FY26\nRevenue 1,234\nATMs >10,000\nCelebrating 40 years of innovation\nLine 4\nLine 5\nLine 6"
    )
    scon.execute("INSERT INTO doc_page VALUES ('d.pdf', 1, ?)", (page_text,))
    scon.execute("INSERT INTO doc_page VALUES ('d.pdf', 2, 'Standalone Results Summary')")
    scon.commit()
    scon.close()

    obs_db = tmp_path / "obs.db"
    ocon = obs.create_db(obs_db)
    rows = obs.build_observations(
        symbol="BLUESTONE", doc_key="d.pdf", page=1, known_at="2026-08-10T10:00:00",
        page_text=page_text,
        reply_rows=[
            {"type": "number", "measure": "revenue.value", "printed_label": "Revenue",
             "value_text": "1,234", "unit": "INR mn", "period": "FY26", "entity_scope": "company"},
            {"type": "number", "measure": "count.atms", "printed_label": "ATMs",
             "value_text": ">10,000", "unit": "ATMs", "period": "FY26", "entity_scope": "company"},
            {"type": "number", "measure": "NEW:company_age_years",
             "printed_label": "Celebrating 40 years of innovation", "value_text": "40", "unit": "years",
             "period": "FY26", "new_definition": "years since incorporation", "new_driver_node": "capacity"},
        ],
        deck_guards=True,
    )
    obs.write_rows(ocon, rows)
    stats = obs.recheck_db(ocon, [str(store_db)])
    got = ocon.execute(
        "SELECT printed_label, basis, basis_source, status, status_reason FROM observation ORDER BY observation_id"
    ).fetchall()
    ocon.close()
    assert stats["basis_deck_heading"] == 2
    assert stats["deck_dropped"] == 1 and len(got) == 2       # the celebration row is deleted, not served
    assert got[0][1:4] == ("consolidated", "page_heading", "verified")
    assert got[1][3] == "unverified" and "deck_bound_not_exact:" in got[1][4]


# --------------------------------------------------- T-242 r4: untied chart/matrix values and junk ordinals


def test_deck_unlabelled_chart_bar_is_untied_but_a_named_chart_title_ties_it():
    """Ckpt-4 #11 ASIANPAINT p26: ten unlabelled bar percentages under a section title."""
    bar = _deck_row(measure="gross_profit_growth_yoy", printed_label="", value=6.0, value_text="6%",
                    unit="%", period="Q2 FY27", series_title="Summary Standalone Financials")
    obs.apply_number_gates([bar], "deck")
    assert bar["status"] == "unverified" and "deck_untied_value" in bar["status_reason"]

    # a chart whose own title names the measure ties its bars (graded right: BATLIBOI machines installed)
    machines = _deck_row(measure="NEW:count.machines_installed", printed_label="", value=2.0,
                         value_text="2", unit="machines", period="1QFY26",
                         series_title="Number of machines installed")
    obs.apply_number_gates([machines], "deck")
    assert machines["status"] == "verified", machines["status_reason"]

    # a label beside the value ties it even when the series title is a section heading
    labelled = _deck_row(measure="revenue.value", printed_label="Revenue", value=1234.0, value_text="1,234")
    obs.apply_number_gates([labelled], "deck")
    assert labelled["status"] == "verified"


def test_deck_matrix_cell_carrying_another_period_as_its_label_is_untied():
    """Ckpt-4 #56 ANGELONE p14: the cohort matrix's bare 7,924 under the FY24 column, filed as FY26."""
    cell = _deck_row(measure="NEW:total_net_income_by_acquisition_cohort", printed_label="FY24",
                     printed_axis="Cohorts Acquired In", value=7924.0, value_text="7,924",
                     unit="Rs Mn", period="FY26",
                     series_title="Revenue contribution from every cohort")
    obs.apply_number_gates([cell], "deck")
    assert cell["status"] == "unverified" and "deck_untied_value" in cell["status_reason"]

    # the same column token as the row's own period is a data label, not a detached coordinate
    ok = _deck_row(measure="pat", printed_label="FY26", value=6596.0, value_text="6,596", unit="Rs Mn",
                   period="FY26")
    obs.apply_number_gates([ok], "deck")
    assert ok["status"] == "verified", ok["status_reason"]


def test_deck_junk_slogan_edition_and_appointment_term_are_dropped():
    slogan = _deck_row(measure="NEW:company_age_years",
                       printed_label="Celebrating 40 years of innovation and service excellence",
                       value=40.0, value_text="40", unit="years", period="2024")
    edition = _deck_row(measure="NEW:annual_report_edition_number", printed_label="Annual Report",
                        value=34.0, value_text="34th", unit="", period="2025-26")
    term = _deck_row(measure="NEW:director_term_duration",
                     printed_label="consecutive term of three (3) years as managing director",
                     value=3.0, value_text="3", unit="years", period="FY26")
    kept = _deck_row(measure="NEW:employee_average_tenure", printed_label="Average employee tenure",
                     value=4.5, value_text="4.5", unit="years", period="FY26")
    rows = [slogan, edition, term, kept]
    obs.apply_number_gates(rows, "deck")
    assert rows == [kept] and kept["status"] == "verified"


def test_gate_not_company_holds_jv_and_associate_figures_unless_the_entity_is_named():
    unnamed = _deck_row(measure="revenue.value", printed_label="Revenue", value=100.0, value_text="100",
                        entity_scope="associate")
    named = _deck_row(measure="revenue.value", printed_label="Smartmeters Technologies Private Limited",
                      value=100.0, value_text="100", entity_scope="associate")
    obs.gate_not_company([unnamed, named])
    assert unnamed["status"] == "unverified" and "not_company" in unnamed["status_reason"]
    assert named["status"] == "verified" and named["entity_scope"] == "associate"
    from reality_engine.v2.observations import canonical_scope
    assert canonical_scope("Joint Venture") == "jv" and canonical_scope("Associates") == "associate"

