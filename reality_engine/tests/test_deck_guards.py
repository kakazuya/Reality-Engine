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
