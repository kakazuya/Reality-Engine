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
