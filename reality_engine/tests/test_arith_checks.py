"""T-242 (26 Nov 2026): the arithmetic check layer, one synthetic case per graded evidence row."""
from __future__ import annotations

import pytest

from reality_engine.v2 import arith_checks as ac

DEFAULT = {
    "observation_id": 1, "symbol": "ACME", "doc_key": "doc.pdf", "page": 1, "series_id": "s1",
    "measure": "other_expenses", "printed_label": "", "value": 0.0, "value_text": "0.00", "unit": "Lakhs",
    "unit_family": "money", "scale": 1.0, "is_total": 0, "period": "Quarter ended June 30, 2026",
    "basis": "consolidated", "entity_scope": "company", "segment": "", "product": "", "geography": "",
    "plant": "", "customer": "", "group_path": "", "status": "verified",
}


def _rows(rows: list[dict]) -> list[dict]:
    return [DEFAULT | row for row in rows]


def _verdicts(rows: list[dict]) -> dict[int, str]:
    verdicts, _stats = ac.check_rows(_rows(rows))
    return {int(v["id"]): str(v["verdict"]) for v in verdicts}


def test_sum_mismatch_flags_total_and_every_child():
    got = _verdicts([
        {"observation_id": 1, "measure": "total_expenses", "printed_label": "Total Expenses", "value": 100.0,
         "value_text": "100.00", "is_total": 1, "group_path": "Expenses"},
        {"observation_id": 2, "measure": "employee_benefits_expense", "printed_label": "Employee benefits",
         "value": 40.0, "value_text": "40.00", "group_path": "Expenses"},
        {"observation_id": 3, "measure": "other_expenses", "printed_label": "Other expenses", "value": 50.0,
         "value_text": "50.00", "group_path": "Expenses"},
    ])
    assert got == {1: "arith_sum_mismatch", 2: "arith_sum_mismatch", 3: "arith_sum_mismatch"}


def test_sum_counter_a_right_total_is_clean():
    assert _verdicts([
        {"observation_id": 1, "measure": "total_expenses", "printed_label": "Total Expenses", "value": 100.0,
         "value_text": "100.00", "is_total": 1, "group_path": "Expenses"},
        {"observation_id": 2, "measure": "employee_benefits_expense", "printed_label": "Employee benefits",
         "value": 40.0, "value_text": "40.00", "group_path": "Expenses"},
        {"observation_id": 3, "measure": "other_expenses", "printed_label": "Other expenses", "value": 60.0,
         "value_text": "60.00", "group_path": "Expenses"},
    ]) == {}


def test_unit_suspect_avi_350_for_3_50_flags_only_that_child():
    verdicts, _stats = ac.check_rows(_rows([
        {"observation_id": 1, "measure": "total_expenses", "printed_label": "Total Expenses", "value": 2661.03,
         "value_text": "2,661.03", "is_total": 1, "group_path": "Expenses",
         "period": "Quarter ended September 30, 2025"},
        {"observation_id": 2, "measure": "purchase_of_finished_goods", "printed_label": "Purchases",
         "value": 2655.02, "value_text": "2,655.02", "group_path": "Expenses",
         "period": "Quarter ended September 30, 2025"},
        {"observation_id": 3, "measure": "employee_benefits_expense", "printed_label": "Employee benefits",
         "value": 350.0, "value_text": "350", "group_path": "Expenses",
         "period": "Quarter ended September 30, 2025"},
        {"observation_id": 4, "measure": "depreciation_and_amortisation_expense", "printed_label": "Depreciation",
         "value": 0.34, "value_text": "0.34", "group_path": "Expenses",
         "period": "Quarter ended September 30, 2025"},
        {"observation_id": 5, "measure": "other_expenses", "printed_label": "Other expenses", "value": 2.17,
         "value_text": "2.17", "group_path": "Expenses", "period": "Quarter ended September 30, 2025"},
    ]))
    assert [v["id"] for v in verdicts] == [3]
    assert verdicts[0]["verdict"] == "arith_unit_suspect"
    assert verdicts[0]["fixed_value"] == pytest.approx(3.5)
    assert verdicts[0]["fix_scale"] == pytest.approx(0.01)


def test_column_mismatch_advenzymes_2025_value_in_2026_column():
    got = _verdicts([
        {"observation_id": 1, "measure": "total_expenses", "printed_label": "Total Expenses", "value": 100.0,
         "value_text": "100.00", "is_total": 1, "group_path": "Expenses"},
        {"observation_id": 2, "measure": "raw_material_cost", "printed_label": "Cost of materials consumed",
         "value": 90.0, "value_text": "90.00", "group_path": "Expenses"},
        {"observation_id": 3, "measure": "other_expenses", "printed_label": "Other expenses", "value": 0.05,
         "value_text": "0.05", "group_path": "Expenses"},
    ])
    assert got == {1: "arith_sum_mismatch", 2: "arith_sum_mismatch", 3: "arith_sum_mismatch"}


def test_subset_as_total_archidply_chemicals_under_raw_material_cost():
    got = _verdicts([
        {"observation_id": 1, "measure": "raw_material_cost", "printed_label": "Chemicals in Kgs",
         "value": 5499.65, "value_text": "5,499.65", "period": "Year Ended 31.03.2025"},
        {"observation_id": 2, "measure": "raw_material_cost", "value": 19070.11, "value_text": "19,070.11",
         "is_total": 1, "period": "Year Ended 31.03.2025"},
    ])
    assert got == {1: "arith_subset_as_total"}


def test_subset_as_total_abb_nelamangala_under_cwip():
    got = _verdicts([
        {"observation_id": 1, "measure": "capital_work_in_progress", "printed_label": "Nelamangala",
         "value": 17.07, "value_text": "17.07", "period": "As at December 31, 2024"},
        {"observation_id": 2, "measure": "capital_work_in_progress", "value": 94.77, "value_text": "94.77",
         "is_total": 1, "period": "As at December 31, 2024"},
    ])
    assert got == {1: "arith_subset_as_total"}


def test_sign_arvsmart_net_loss_stored_positive():
    got = _verdicts([
        {"observation_id": 1, "measure": "pat", "printed_label": "total net loss after tax", "value": 1207.22,
         "value_text": "1,207.22", "is_total": 1},
        {"observation_id": 2, "measure": "total_comprehensive_income", "printed_label": "total comprehensive loss",
         "value": 1207.22, "value_text": "1,207.22", "is_total": 1},
    ])
    assert got == {1: "arith_sign", 2: "arith_sign"}


def test_sign_counter_a_negative_exceptional_item_is_clean():
    assert _verdicts([
        {"observation_id": 1, "measure": "exceptional_items", "printed_label": "Exceptional item (charge)",
         "value": -240.0, "value_text": "(240.00)"},
    ]) == {}


def test_sign_printed_parentheses_with_positive_value_is_flagged():
    got = _verdicts([
        {"observation_id": 1, "measure": "changes_in_inventories", "printed_label": "Changes in inventories",
         "value": 13.58, "value_text": "{13.58)"},
        {"observation_id": 2, "measure": "employee_benefits_expense", "printed_label": "Employee benefits",
         "value": 0.1, "value_text": "- 0.10"},
        {"observation_id": 3, "measure": "total_expenses", "printed_label": "Total expenses", "value": 100.0,
         "value_text": "100.00", "is_total": 1, "group_path": "Expenses"},
    ])
    assert got == {1: "arith_sign", 2: "arith_sign"}


def test_jump_flags_the_unit_outlier_only():
    got = _verdicts([
        {"observation_id": 1, "measure": "pat", "printed_label": "Profit", "value": 100.0, "value_text": "100.00",
         "scale": 100000.0, "period": "Quarter ended June 30, 2025"},
        {"observation_id": 2, "measure": "pat", "printed_label": "Profit", "value": 102.0, "value_text": "102.00",
         "scale": 100000.0, "period": "Quarter ended September 30, 2025"},
        {"observation_id": 3, "measure": "pat", "printed_label": "Profit", "value": 10100.0,
         "value_text": "10,100.00", "scale": 100000.0, "period": "Quarter ended December 31, 2025"},
        {"observation_id": 4, "measure": "pat", "printed_label": "Profit", "value": 103.0, "value_text": "103.00",
         "scale": 100000.0, "period": "Quarter ended March 31, 2026"},
    ])
    assert got == {3: "arith_jump"}


def test_jump_counter_a_real_doubling_is_clean():
    assert _verdicts([
        {"observation_id": 1, "measure": "pat", "printed_label": "Profit", "value": 100.0, "value_text": "100.00",
         "scale": 100000.0, "period": "Quarter ended June 30, 2025"},
        {"observation_id": 2, "measure": "pat", "printed_label": "Profit", "value": 200.0, "value_text": "200.00",
         "scale": 100000.0, "period": "Quarter ended September 30, 2025"},
        {"observation_id": 3, "measure": "pat", "printed_label": "Profit", "value": 210.0, "value_text": "210.00",
         "scale": 100000.0, "period": "Quarter ended December 31, 2025"},
    ]) == {}


def test_duplicate_labels_skip_the_sum_check():
    assert _verdicts([
        {"observation_id": 1, "measure": "total_expenses", "printed_label": "Total expenses", "value": 100.0,
         "value_text": "100.00", "is_total": 1, "group_path": "Expenses"},
        {"observation_id": 2, "measure": "other_expenses", "printed_label": "Other expenses", "value": 30.0,
         "value_text": "30.00", "group_path": "Expenses"},
        {"observation_id": 3, "measure": "other_expenses", "printed_label": "Other expenses", "value": 40.0,
         "value_text": "40.00", "group_path": "Expenses"},
    ]) == {}


def test_period_kind_and_end_read_the_printed_period_forms():
    assert ac.period_kind("Quarter ended 30.09.2026") == "q"
    assert ac.period_kind("Half year ended 30.09.2026") == "h"
    assert ac.period_kind("Year ended 31-Mar-26") == "y"
    assert ac.period_kind("As at December 31, 2024") == "i"
    assert ac._period_end("Year ended 31-Mar-26") == (2026, 3, 31)
    assert ac._period_end("For the year ended on March 31,2026") == (2026, 3, 31)
    assert ac._period_end("As at December 31, 2024") == (2024, 12, 31)
    assert ac._period_end("Year ended 31.03.2026") == (2026, 3, 31)


def test_verdict_shape_matches_the_check_layer_contract():
    verdicts, _stats = ac.check_rows(_rows([
        {"observation_id": 1, "measure": "total_expenses", "printed_label": "Total Expenses", "value": 100.0,
         "value_text": "100.00", "is_total": 1, "group_path": "Expenses"},
        {"observation_id": 2, "measure": "other_expenses", "printed_label": "Other expenses", "value": 50.0,
         "value_text": "50.00", "group_path": "Expenses"},
        {"observation_id": 3, "measure": "employee_benefits_expense", "printed_label": "Employee benefits",
         "value": 40.0, "value_text": "40.00", "group_path": "Expenses"},
    ]))
    assert verdicts
    for verdict in verdicts:
        assert verdict["checker"] == "arith_checks"
        assert verdict["rule"] in {"sum_mismatch", "subset_as_total", "sign", "jump"}
        assert verdict["verdict"].startswith("arith_")
        assert verdict["evidence"]
