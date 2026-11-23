"""Offline unit tests for the llama-server lens client.

Contract: no server process (all HTTP faked), deterministic, fast. Covers:
  * brace-scan JSON extraction (prose-wrapped output still parses)
  * extract_macro returns a Pydantic-valid MacroEventExtraction dict
  * synthesize returns summary + zero-defaulted moat deltas
  * health False when the server is down (fail-closed, never raises)
  * HTTP error propagates (callers own the regex/mock fallback)
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TEMP_DB_DIR = tempfile.mkdtemp(prefix="reality_lens_test_db_")
os.environ.setdefault(
    "REALITY_ENGINE_DB_PATH", str(Path(_TEMP_DB_DIR) / "singleton_isolated.db")
)

from reality_engine.ingestion.llm_lens_client import LensLLMClient, _scan_json  # noqa: E402


def _chat_resp(content: str):
    r = mock.MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    return r


MACRO_JSON = (
    '{"event_name": "Steel duty hike", "event_category": "Trade policy", '
    '"primary_effects": [{"target_type": "Industry", "target_name": "Steel", '
    '"transmission_channel": "input cost", "raw_magnitude": 2.5, '
    '"probability": 0.7, "lag_time_months": 3, "second_order_effects": []}]}'
)

MOAT_JSON = (
    '{"summary": {"business": "makes rail parts", "key_drivers": ["orders"], '
    '"key_risks": ["steel prices"]}, "moat_updates": '
    '{"switching_costs_delta": 1, "moat_trajectory": "Stable"}}'
)


class ScanJsonTest(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(_scan_json('{"a": 1}'), {"a": 1})

    def test_prose_wrapped(self):
        self.assertEqual(_scan_json('Here you go:\n```json\n{"a": 1}\n```\ndone'), {"a": 1})

    def test_nested_braces(self):
        self.assertEqual(_scan_json('x {"a": {"b": [1, {"c": 2}]}} y')["a"]["b"][1], {"c": 2})

    def test_no_object(self):
        self.assertIsNone(_scan_json("no braces here"))


class LensClientTest(unittest.TestCase):
    def setUp(self):
        self.client = LensLLMClient(base_url="http://127.0.0.1:9", timeout_s=5)

    def test_extract_macro_validates_lens(self):
        with mock.patch("requests.post", return_value=_chat_resp("Result: " + MACRO_JSON + " end")):
            out = self.client.extract_macro("steel duty context", {"title": "PIB Doc"})
        self.assertEqual(out["event_name"], "Steel duty hike")
        self.assertEqual(out["primary_effects"][0]["target_name"], "Steel")

    def test_synthesize_defaults_deltas(self):
        with mock.patch("requests.post", return_value=_chat_resp(MOAT_JSON)):
            out = self.client.synthesize("HAL", ["makes rail parts with brand pricing power"])
        self.assertEqual(out["summary"]["business"], "makes rail parts")
        self.assertEqual(out["moat_updates"]["switching_costs_delta"], 1)
        self.assertEqual(out["moat_updates"]["network_effects_delta"], 0)
        self.assertEqual(out["moat_updates"]["moat_trajectory"], "Stable")

    def test_health_false_when_down(self):
        with mock.patch("requests.get", side_effect=ConnectionError("down")):
            self.assertFalse(self.client.health())

    def test_http_error_propagates(self):
        bad = mock.MagicMock()
        bad.raise_for_status.side_effect = RuntimeError("500")
        with mock.patch("requests.post", return_value=bad):
            with self.assertRaises(RuntimeError):
                self.client.extract_macro("ctx", {})


if __name__ == "__main__":
    unittest.main()
