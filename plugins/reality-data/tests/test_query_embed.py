"""Unit tests for plugins/reality-data/server/query_embed.py.

HTTP is mocked; no provider key is read and no paid call is made.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "server"))

import query_embed  # noqa: E402


class FakeResponse:
    def __init__(self, status=200, embedding=None):
        self.status_code = status
        self._embedding = embedding
        self.text = "provider error body"

    def json(self):
        return {"data": [{"index": 0, "embedding": self._embedding}]}


def vec(first=3.0, second=4.0):
    values = np.zeros(4096, dtype=np.float32)
    values[0] = first
    values[1] = second
    return values.tolist()


class QueryEmbedTests(unittest.TestCase):
    def setUp(self):
        query_embed.clear_cache()
        self.env = {"DEEPINFRA_API_KEY": "test-di", "NEBIUS_API_KEY": "test-neb",
                    query_embed.PAID_EMBED_FLAG: "1"}

    def _call_with(self, response, index, text="question"):
        with mock.patch.object(query_embed, "_env", return_value=self.env), \
                mock.patch("requests.post", return_value=response) as post:
            out = query_embed.embed_query(text, index)
        return out, post

    def test_nemotron_prompt_model_url_and_normalisation(self):
        out, post = self._call_with(FakeResponse(embedding=vec()), "nemotron8b")
        self.assertEqual(out.shape, (4096,))
        self.assertAlmostEqual(float(np.linalg.norm(out)), 1.0, places=5)
        self.assertAlmostEqual(float(out[0]), 0.6, places=5)
        self.assertAlmostEqual(float(out[1]), 0.8, places=5)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.deepinfra.com/v1/openai/embeddings")
        self.assertEqual(kwargs["json"]["model"], "nvidia/Nemotron-3-Embed-8B")
        self.assertEqual(kwargs["json"]["input"], ["query: question"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-di")
        self.assertEqual(kwargs["timeout"], 10.0)

    def test_qwen_prompt_model_and_fallback_base(self):
        out, post = self._call_with(FakeResponse(embedding=vec()), "qwen8b_ar")
        self.assertEqual(out.shape, (4096,))
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.tokenfactory.nebius.com/v1/embeddings")
        self.assertEqual(kwargs["json"]["model"], "Qwen/Qwen3-Embedding-8B")
        self.assertEqual(kwargs["json"]["input"], [query_embed.QWEN_INSTRUCT + "question"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-neb")

    def test_lru_cache_avoids_second_call(self):
        with mock.patch.object(query_embed, "_env", return_value=self.env), \
                mock.patch("requests.post", return_value=FakeResponse(embedding=vec())) as post:
            query_embed.embed_query("cached question", "nemotron8b")
            query_embed.embed_query("cached question", "nemotron8b")
        self.assertEqual(post.call_count, 1)

    def test_one_retry_after_transport_error(self):
        import requests
        responses = [requests.Timeout("slow"), FakeResponse(embedding=vec())]
        with mock.patch.object(query_embed, "_env", return_value=self.env), \
                mock.patch("requests.post", side_effect=responses) as post, \
                mock.patch.object(query_embed.time, "sleep", return_value=None):
            out = query_embed.embed_query("retry question", "nemotron8b")
        self.assertEqual(post.call_count, 2)
        self.assertAlmostEqual(float(np.linalg.norm(out)), 1.0, places=5)

    def test_missing_key_is_clear_and_makes_no_call(self):
        with mock.patch.object(query_embed, "_env", return_value={query_embed.PAID_EMBED_FLAG: "1"}), \
                mock.patch("requests.post") as post:
            with self.assertRaises(query_embed.MissingAPIKeyError) as ctx:
                query_embed.embed_query("question", "qwen8b_ar")
        self.assertIn("NEBIUS_API_KEY", str(ctx.exception))
        self.assertEqual(post.call_count, 0)

    def test_paid_embedding_off_by_default_makes_no_call(self):
        env = {"DEEPINFRA_API_KEY": "test-di"}
        with mock.patch.object(query_embed, "_env", return_value=env), \
                mock.patch("requests.post") as post:
            with self.assertRaises(query_embed.MissingAPIKeyError) as ctx:
                query_embed.embed_query("question", "nemotron8b")
        self.assertIn(query_embed.PAID_EMBED_FLAG, str(ctx.exception))
        self.assertEqual(post.call_count, 0)

    def test_unknown_index(self):
        with self.assertRaises(query_embed.UnknownIndexError):
            query_embed.embed_query("x", "not-an-index")

    def test_aliases(self):
        self.assertEqual(query_embed.normalise_index("vector_index_nemotron8b"), "nemotron8b")
        self.assertEqual(query_embed.normalise_index("qwen_ar"), "qwen8b_ar")

    def test_index_coverage_matches_done_mask(self):
        nem = query_embed.index_info("nemotron8b")
        qwen = query_embed.index_info("qwen8b_ar")
        self.assertEqual(nem["done_rows"], 340_887)
        self.assertEqual(nem["coverage_pct"], 100.0)
        self.assertEqual(qwen["done_rows"], 61_440)
        self.assertEqual(qwen["rows"], 1_367_706)
        self.assertLess(qwen["coverage_pct"], 5.0)
        self.assertIn("4.49", qwen["description"])


if __name__ == "__main__":
    unittest.main()
