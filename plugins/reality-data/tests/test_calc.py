"""Tests for plugins/reality-data/server/calc.py (the ``pilot3_calc`` tool, T-072).

Run from the repo root:
    python -m pytest plugins/reality-data/tests/test_calc.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import calc  # noqa: E402


def test_money_difference_and_the_indian_views() -> None:
    out = calc.evaluate("revenue - pat", {"revenue": "23506 crore", "pat": "493 crore"})
    assert out["ok"] is True
    assert out["unit"] == "rupees"
    assert out["crore"] == 23013
    assert out["rupees"] == 230130000000
    assert out["lakh_crore"] == 0.23013
    assert out["indian"] == "2,30,13,00,00,000.00"


def test_ratio_and_exact_fraction() -> None:
    out = calc.evaluate("ebit / finance_cost", {"ebit": "11178 crore", "finance_cost": "115 crore"})
    assert out["unit"] == "ratio"
    assert out["value"] == 97.2
    assert out["exact"] == "486/5"


def test_percent_costs_and_bps() -> None:
    # A percent input is a fraction of 1, so "9 percent" of a crore amount multiplies correctly.
    out = calc.evaluate("pat * 0.09", {"pat": "22066.48 crore"})
    assert out["crore"] == 1985.9832
    bps = calc.evaluate("target - current", {"target": "9.5 percent", "current": "5 percent"})
    assert bps["percentage_points"] == 4.5    # T-109: a gap between two percentages is in pp
    assert bps["bps"] == 450


def test_lakh_crore_and_market_cap() -> None:
    out = calc.evaluate("price * shares", {"price": "349.45 rupees", "shares": "318.5 crore shares"})
    assert round(out["lakh_crore"], 3) == 1.113
    assert calc.evaluate("a", {"a": "3.22 lakh crore"})["crore"] == 322000


def test_rupees_per_share() -> None:
    out = calc.evaluate("pat / count", {"pat": "19859.83 crore", "count": "622.39 crore shares"})
    assert out["unit"] == "rupees_per_share"
    assert round(out["rupees"], 2) == 31.91


def test_functions() -> None:
    assert calc.evaluate("sum(a, b, c)", {"a": "8.29 crore", "b": "1.92 crore", "c": "5.6 crore"})["crore"] == 15.81
    assert calc.evaluate("avg(10, 20, 30)")["value"] == 20
    assert calc.evaluate("min(3, 1, 2)")["value"] == 1
    assert calc.evaluate("max(3, 1, 2)")["value"] == 3
    assert calc.evaluate("round(10 / 3, 2)")["value"] == 3.33
    assert calc.evaluate("(1 + 2) ** 3")["value"] == 27


def test_unit_mistakes_are_errors_not_numbers() -> None:
    assert calc.evaluate("a - b", {"a": "100 shares", "b": "1 crore"})["ok"] is False
    assert "cannot subtract" in calc.evaluate("a - b", {"a": "100 shares", "b": "1 crore"})["error"]
    doubled = calc.evaluate("a * b", {"a": "10 crore", "b": "10 crore"})
    assert doubled["ok"] is False and "cannot multiply" in doubled["error"]
    assert calc.evaluate("1 / 0")["ok"] is False
    assert "division by zero" in calc.evaluate("1 / 0")["error"]


def test_bad_input_is_a_clear_error() -> None:
    assert "unknown unit" in calc.evaluate("a", {"a": "3 furlongs"})["error"]
    assert "unknown unit" in calc.evaluate("a + 1", {"a": "1 barrel of oil"})["error"]
    assert calc.evaluate("nope / 2")["ok"] is False
    assert "unknown input" in calc.evaluate("nope / 2")["error"]
    assert calc.evaluate("(1 + 2")["ok"] is False
    assert "does not parse" in calc.evaluate("(1 + 2")["error"]
    assert calc.evaluate("")["ok"] is False


def test_no_eval() -> None:
    for expression in ("__import__('os').system('echo hi')", "open('x')", "[1, 2][0]", "lambda: 1",
                       "1 if True else 2", "a.__class__"):
        out = calc.evaluate(expression, {"a": "1 crore"})
        assert out["ok"] is False, expression
        assert "not allowed" in out["error"] or "only" in out["error"], (expression, out["error"])


def test_indian_grouping() -> None:
    assert calc.indian_grouping(123456789) == "12,34,56,789.00"
    assert calc.indian_grouping(1000, 0) == "1,000"
    assert calc.indian_grouping(-1234567.5, 1) == "-12,34,567.5"
    assert calc.indian_grouping(0) == "0.00"

def test_a_currency_prefix_alone_is_rupees() -> None:
    # "Rs 349.45" x 9,650,350,647 shares is a market cap: rupees, with the crore views the answers need.
    out = calc.evaluate("p * s", {"p": "Rs 349.45", "s": "9650350647 shares"})
    assert out["ok"] is True and out["unit"] == "rupees"
    assert round(out["crore"], 2) == 337231.5
    assert round(out["lakh_crore"], 4) == 3.3723
    assert out["indian"] == "33,72,31,50,33,594.15"
    # a scale word after the prefix still decides the scale
    assert calc.evaluate("a", {"a": "Rs 5 crore"})["crore"] == 5
    assert calc.evaluate("a", {"a": "Rs 5 crore"})["unit"] == "rupees"
    # and a bare number stays a plain quantity
    assert calc.evaluate("a", {"a": "5"})["unit"] == "ratio"


def test_a_change_between_two_percentages_is_percentage_points() -> None:
    # T-109 (INFY-035): FPI holding 27.09% -> 27.44% is +0.35 percentage points and +1.29% relative, never "0.35%"
    out = calc.evaluate("new - old", {"new": "27.44 percent", "old": "27.09 percent"})
    assert out["ok"] is True
    assert out["unit"] == "percentage_points"
    assert out["percentage_points"] == 0.35
    assert out["bps"] == 35
    assert "percentage points" in out["display"]
    assert round(out["relative_change_pct"], 2) == 1.29


def test_a_scaled_percentage_stays_percent() -> None:
    out = calc.evaluate("a * 2", {"a": "5 percent"})
    assert out["unit"] == "percent" and out["percent"] == 10
