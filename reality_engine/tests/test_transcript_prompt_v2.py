"""T-241: the v2 transcript prompt (fiscal periods, range upper end, sign, speaker) and its row fields."""
from __future__ import annotations

from reality_engine.v2 import observations as obs

DOC = "D:/x/concall_transcript/abc.pdf"
PAGE = "Rasik Mittal: Profit after tax for the quarter stood at INR26.5 crores, that is a degrowth of 5%. " \
       "Our inventory days decreased to 69 days. We expect 10% to 12% revenue growth."


def _rows(reply):
    return obs.build_observations(symbol="MUFTI", doc_key=DOC, page=4, known_at="2024-10-29T10:00:00",
                                  page_text=PAGE, reply_rows=reply)


def test_call_quarter_is_the_quarter_ended_before_the_filing():
    assert obs.call_quarter("2024-08-09T10:00") == "Q1 FY25"
    assert obs.call_quarter("2025-02-10") == "Q3 FY25"
    assert obs.call_quarter("2025-05-20") == "Q4 FY25"
    assert obs.call_quarter("2025-11-14") == "Q2 FY26"
    assert obs.call_quarter("") == "the quarter just reported"


def test_v2_prompt_formats_with_the_call_quarter():
    text = obs.PROMPT_TRANSCRIPT_V2.format(dictionary="d", text="t", known_at="2024-10-29", call_quarter="Q2 FY25")
    assert "it discusses Q2 FY25" in text and '"high_text"' in text and '"sign"' in text


def test_sign_negates_a_growth_row_but_never_a_level():
    rows = _rows([
        {"type": "number", "measure": "pat_growth_yoy", "printed_label": "that is a degrowth of",
         "value_text": "5%", "unit": "%", "period": "Q2 FY25", "sign": "-", "speaker": "Rasik Mittal"},
        {"type": "number", "measure": "inventory_days", "printed_label": "inventory days decreased to",
         "value_text": "69", "unit": "days", "period": "Q2 FY25", "sign": "-"},
    ])
    by = {r["measure"]: r for r in rows}
    assert by["pat_growth_yoy"]["value"] == -5.0 and by["pat_growth_yoy"]["direction"] == "down"
    assert by["pat_growth_yoy"]["speaker"] == "Rasik Mittal"
    assert by["inventory_days"]["value"] == 69.0


def test_range_upper_end_and_printed_period_words_are_kept():
    rows = _rows([{"type": "number", "measure": "revenue_growth_yoy", "printed_label": "We expect",
                   "value_text": "10%", "high_text": "12%", "unit": "%", "period": "Q2 FY25",
                   "period_printed": "for the quarter"}])
    assert rows and rows[0]["value_high"] == 12.0 and rows[0]["period_source"] == "for the quarter"


def test_a_v1_reply_is_unchanged():
    rows = _rows([{"type": "number", "measure": "pat_growth_yoy", "printed_label": "that is a degrowth of",
                   "value_text": "5%", "unit": "%", "period": "the quarter"}])
    assert rows[0]["value"] == 5.0 and rows[0]["speaker"] == "" and rows[0]["value_high"] is None
