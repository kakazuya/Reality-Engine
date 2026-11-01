"""Checks for the OCR number bench: the measure and the page rule, not the engines."""
from __future__ import annotations

from reality_engine.scripts.ocr_number_bench import (
    digit_count,
    is_table_page,
    numbers,
    page_stats,
    score_page,
    summarize,
)

TABLE_LINE = ("Segment revenue 1,433 2,098 31,733 21,692 24,737 27,281 1,691 1,788 "
              "1,206 4,560 7,890 12,345 67,890 98,765 43,210 5,432 6,789 ")


def test_numbers_drop_commas_and_duplicates():
    assert numbers("1,433 and 1433 and 1,433.50 and 12.") == ["1433", "1433.50", "12"]


def test_digit_count_ignores_separators():
    assert digit_count("1,433.50") == 6
    assert digit_count("206") == 3
    assert digit_count("14") == 2


def test_table_page_rule_needs_all_three_conditions():
    stats = page_stats(TABLE_LINE)
    assert stats["numeric_tokens"] >= 15 and stats["long_numeric"] >= 8
    assert is_table_page(stats)
    prose = page_stats("The company reported growth across its two segments this year.")
    assert not is_table_page(prose)


def test_score_page_recalls_truth_numbers_and_penalises_invention():
    truth = "Revenue 1,433 2,098 and PAT 31,733"
    good = score_page(truth, "Revenue 1433 2,098 and PAT 31,733")
    assert (good["recall"], good["precision"]) == (1.0, 1.0)
    lossy = score_page(truth, "Revenue 1433 and 99,999")
    assert lossy["recall"] == round(1 / 3, 4)
    assert lossy["precision"] == round(1 / 2, 4)
    assert lossy["missing"] == ["2098", "31733"]


def test_summarize_pools_counts_micro_and_averages_pages_macro():
    rows = [score_page("1 2 3 4", "1 2"), score_page("5 6", "5 6")]
    summary = summarize(rows)
    assert summary["truth_numbers"] == 6
    assert summary["micro_recall"] == round(4 / 6, 4)
    assert summary["macro_recall"] == round((0.5 + 1.0) / 2, 4)
    assert summary["micro_precision"] == 1.0
