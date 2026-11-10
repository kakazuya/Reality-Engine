"""Beam runs only while OpenCode lists it as free (Shivam, 10 Nov 2026)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from reality_engine.scripts import free_model_check as fmc
from reality_engine.scripts.run_deepseek_harness import free_model_refusal

# Shapes copied from https://opencode.ai/docs/zen/ on 10 Nov 2026: the endpoint
# table (id + URL) comes before the pricing table.
ENDPOINT_ROW = ("<tr><td>Beam Free</td><td>beam-free</td>"
                "<td>https://opencode.ai/inference/openai/v1/chat/completions</td></tr>")
FREE_ROW = "<tr><td>Beam Free</td><td>Free</td><td>Free</td><td>Free</td><td>-</td></tr>"
PAID_ROW = "<tr><td>Beam Free</td><td>$0.40</td><td>$1.60</td><td>$0.04</td><td>-</td></tr>"


def test_free_row_is_read_after_skipping_the_endpoint_table():
    free, row = fmc.parse_price_row(ENDPOINT_ROW + FREE_ROW, "Beam Free")
    assert free is True and row == "Beam Free | Free | Free | Free"


def test_a_priced_row_is_not_free():
    free, _ = fmc.parse_price_row(ENDPOINT_ROW + PAID_ROW, "Beam Free")
    assert free is False


def test_missing_row_returns_none():
    assert fmc.parse_price_row("<p>nothing here</p>", "Beam Free") is None


def test_harness_refuses_beam_once_it_charges(tmp_path):
    flag = tmp_path / "free_models.json"
    assert free_model_refusal("beam-free", flag, fetch=lambda url: ENDPOINT_ROW + PAID_ROW)
    assert json.loads(flag.read_text())["beam-free"]["free"] is False


def test_harness_allows_beam_while_free_and_ignores_other_models(tmp_path):
    flag = tmp_path / "free_models.json"
    assert free_model_refusal("beam-free", flag, fetch=lambda url: FREE_ROW) is None
    assert free_model_refusal("deepseek-v4.1-flash", flag, fetch=lambda url: PAID_ROW) is None


def test_unreachable_page_keeps_the_last_state(tmp_path):
    flag = tmp_path / "free_models.json"
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    flag.write_text(json.dumps({"beam-free": {"free": False, "checked_at": old, "row": "x"}}))

    def down(url):
        raise OSError("offline")

    assert free_model_refusal("beam-free", flag, fetch=down)   # still refused
    flag.write_text(json.dumps({"beam-free": {"free": True, "checked_at": old, "row": "x"}}))
    assert free_model_refusal("beam-free", flag, fetch=down) is None
