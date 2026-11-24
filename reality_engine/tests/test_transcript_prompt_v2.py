"""T-241: the v2 transcript prompt (fiscal periods, range upper end, sign, speaker) and its row fields."""
from __future__ import annotations

from pathlib import Path

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


def test_v2d_claim_type_drops_hypotheticals_and_third_party_guidance():
    rows = _rows([
        {"type": "number", "measure": "capacity.utilisation", "printed_label": "even if you assume",
         "value_text": "80%", "unit": "%", "claim_type": "hypothetical"},
        {"type": "number", "measure": "NEW:expressway_plan_km", "printed_label": "the government plans",
         "value_text": "17,000", "unit": "km", "claim_type": "third_party", "new_definition": "x",
         "new_driver_node": "none"},
        {"type": "guidance", "measure": "order.intake", "low": "40,000", "unit": "crores",
         "text": "NHAI targets 40,000 crores of awards this year.", "claim_type": "third_party"},
    ])
    assert [r["value"] for r in rows if r["record_type"] == "number"] == [17000.0]
    assert next(r for r in rows if r["record_type"] == "number")["entity_scope"] == "industry"
    assert not [r for r in rows if r["record_type"] == "guidance"]


def test_v2d_percent_unit_lakh_crore_scale_and_section_basis():
    assert obs._scale_factor("Lakh Crores") == 1e12 and obs._scale_factor("crores") == 1e7
    text = ("Starting with the standalone numbers. Total income stood at INR 1,303 crores. Coming to the "
            "consolidated results: Total income of Q2 stood at INR 1,908 crores.")
    assert obs.section_basis(text, "Total income of Q2 stood at", "INR 1,908 crores") == "consolidated"
    assert obs.section_basis(text, "Total income stood at", "INR 1,303 crores") == "standalone"
    rows = _rows([{"type": "number", "measure": "pat_growth_yoy", "printed_label": "that is a degrowth of",
                   "value_text": "5%", "unit": "", "period": "Q2 FY25", "claim_type": "company_actual"}])
    assert rows[0]["unit"] == "%"


def test_v2e_basis_skips_a_comparison_and_bps_counts_as_a_movement():
    text = ("Now coming on to the consolidated performance, our consolidated performance is much better than "
            "standalone performance. So our revenue from operation was Rs.158 Crores")
    assert obs.section_basis(text, "So our revenue from operation was", "Rs.158 Crores") == "consolidated"
    assert obs.SIGNED_MEASURE.search("ebitda_margin bps") and not obs.SIGNED_MEASURE.search("inventory_days days")
    assert "\x08" not in obs.COMPARED_BASIS_RE.pattern + obs.SIGNED_MEASURE.pattern + obs.LAKH_CRORE_RE.pattern


def test_v2e_a_by_x_change_is_never_stored_as_the_level():
    rows = obs.build_observations(
        symbol="MUFTI", doc_key=DOC, page=3, known_at="2024-10-29",
        page_text="Our inventory days have decreased by 8 days to 69 days.",
        reply_rows=[{"type": "number", "measure": "inventory_days", "printed_label": "Our inventory days have "
                     "decreased by", "value_text": "8", "unit": "days", "claim_type": "company_actual"},
                    {"type": "number", "measure": "inventory_days", "printed_label": "8 days to",
                     "value_text": "69", "unit": "days", "claim_type": "company_actual"}])
    got = {r["measure"]: r["value"] for r in rows}
    assert got == {"NEW:inventory_days_change": -8.0, "inventory_days": 69.0}


def test_no_control_characters_in_the_reader_source():
    """T-241: a shell that eats one backslash turned three regex word boundaries into backspace characters."""
    source = Path(obs.__file__).read_text(encoding="utf-8")
    assert not [c for c in source if ord(c) < 32 and c not in "\n\r\t"]


def test_mix_part_extracts_named_parts_and_rejects_empty_labels():
    assert obs.mix_part("Road HAM contributed") == "Road HAM"
    assert obs.mix_part("Power T&D accounts for") == "Power T&D"
    assert obs.mix_part("exports were") == "exports"
    assert obs.mix_part("share of domestic") == "domestic"
    assert obs.mix_part("out of which domestic") == "domestic"
    for empty_label in ("out of that", "and", "which is", "around", "contributed"):
        assert obs.mix_part(empty_label) == "", empty_label


def test_mix_guard_sets_segment_from_label_when_dims_empty():
    page = "Road HAM contributed 11.8 crores in Q2 FY25."
    base = obs.build_observations(
        symbol="ASHOKA", doc_key=DOC, page=4, known_at="2024-10-29T10:00:00",
        page_text=page,
        reply_rows=[{"type": "number", "measure": "revenue.mix", "printed_label": "Road HAM contributed",
                     "value_text": "11.8", "unit": "crores", "period": "Q2 FY25", "segment": "Road HAM",
                     "entity_scope": "company", "claim_type": "company_actual"}],
    )
    rows = obs.build_observations(
        symbol="ASHOKA", doc_key=DOC, page=4, known_at="2024-10-29T10:00:00",
        page_text=page,
        reply_rows=[{"type": "number", "measure": "revenue.mix", "printed_label": "Road HAM contributed",
                     "value_text": "11.8", "unit": "crores", "period": "Q2 FY25",
                     "entity_scope": "company", "claim_type": "company_actual"}],
    )
    assert len(rows) == 1
    assert rows[0]["segment"] == "Road HAM"
    assert rows[0]["status"] == base[0]["status"] == "verified"
    assert rows[0]["status_reason"] == base[0]["status_reason"]


def test_mix_guard_marks_mix_without_segment_unverified():
    page = "out of that 50% in Q2 FY25."
    rows = obs.build_observations(
        symbol="KPGEL", doc_key=DOC, page=4, known_at="2024-10-29T10:00:00",
        page_text=page,
        reply_rows=[{"type": "number", "measure": "mix.share", "printed_label": "out of that",
                     "value_text": "50%", "unit": "%", "period": "Q2 FY25",
                     "entity_scope": "company", "claim_type": "company_actual"}],
    )
    assert len(rows) == 1
    assert rows[0]["segment"] == ""
    assert rows[0]["status"] == "unverified"
    assert "mix_without_segment" in rows[0]["status_reason"]


def test_mix_guard_leaves_row_with_customer_or_non_mix_measure_untouched():
    page = "out of that 14 crores to merchant sales and PAT stood at 26.5 crores in Q2 FY25."
    rows = obs.build_observations(
        symbol="DEEPAKFERT", doc_key=DOC, page=4, known_at="2024-10-29T10:00:00",
        page_text=page,
        reply_rows=[
            {"type": "number", "measure": "revenue.mix", "printed_label": "out of that",
             "value_text": "14", "unit": "crores", "period": "Q2 FY25", "customer": "merchant sales",
             "entity_scope": "company", "claim_type": "company_actual"},
            {"type": "number", "measure": "pat", "printed_label": "out of that",
             "value_text": "26.5", "unit": "crores", "period": "Q2 FY25",
             "entity_scope": "company", "claim_type": "company_actual"},
        ],
    )
    by = {r["measure"]: r for r in rows}
    assert by["revenue.mix"]["customer"] == "merchant sales"
    assert by["revenue.mix"]["segment"] == ""
    assert by["revenue.mix"]["status"] == "verified"
    assert by["pat"]["segment"] == ""
    assert by["pat"]["status"] == "verified"
