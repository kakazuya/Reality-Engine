"""Offline unit tests for the ONNX embedding backend + vector-store wiring.

Contract: no model download (embedder forced unavailable OR faked session),
no live network, deterministic, fast. Covers:
  * embedder fail-closed (missing files -> available False, embed None)
  * download short-circuit when files already present
  * vector store keeps hash fallback when ONNX is missing
  * embed_many batches through the ONNX singleton when present
  * query prefix is applied on the search path (bge retrieval contract)
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TEMP_DB_DIR = tempfile.mkdtemp(prefix="reality_embed_test_db_")
os.environ.setdefault(
    "REALITY_ENGINE_DB_PATH", str(Path(_TEMP_DB_DIR) / "singleton_isolated.db")
)

from reality_engine.db.vector_store import VectorStoreManager  # noqa: E402
from reality_engine.ingestion import onnx_embedder as oe  # noqa: E402


class OnnxEmbedderTest(unittest.TestCase):
    def test_unavailable_without_files(self):
        emb = oe.OnnxEmbedder(model_dir=Path(tempfile.mkdtemp()), prefer_gpu=False)
        self.assertFalse(emb.available)
        self.assertIsNone(emb.provider)
        self.assertIsNone(emb.embed("hello"))
        self.assertIsNone(emb.embed_many(["a", "b"]))

    def test_download_short_circuits_when_present(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "onnx").mkdir(parents=True)
        (tmp / "onnx" / "model.onnx").write_bytes(b"fake")
        (tmp / "tokenizer.json").write_text("{}", encoding="utf-8")
        emb = oe.OnnxEmbedder(model_dir=tmp, prefer_gpu=False)
        self.assertTrue(emb.ensure_downloaded())

    def test_batched_inference_shape(self):
        emb = oe.OnnxEmbedder(model_dir=Path(tempfile.mkdtemp()), prefer_gpu=False)
        emb._probed = True
        emb._available = True
        emb._provider = "CPU"
        emb.batch_size = 2
        fake_tok = mock.MagicMock()
        all_ids = [[101, 200, 102], [101, 300, 400, 102], [101, 500, 102]]
        seen = {"n": 0}
        def fake_encode(texts):
            out = []
            for _ in texts:
                out.append(mock.MagicMock(ids=all_ids[seen["n"] % 3]))
                seen["n"] += 1
            return out
        fake_tok.encode_batch.side_effect = fake_encode
        emb._tokenizer = fake_tok
        import numpy as np
        emb._session = mock.MagicMock()
        emb._session.get_inputs.return_value = [
            mock.MagicMock(name="input_ids"), mock.MagicMock(name="attention_mask")]
        emb._session.get_inputs.return_value[0].name = "input_ids"
        emb._session.get_inputs.return_value[1].name = "attention_mask"
        emb._session.get_outputs.return_value = [mock.MagicMock(name="last_hidden_state")]
        emb._session.get_outputs.return_value[0].name = "last_hidden_state"
        hidden = np.random.RandomState(0).rand(3, 512, 5).astype(np.float32)

        def fake_run(_, inputs):
            n = list(inputs.values())[0].shape[0]
            return [hidden[:n]]
        emb._session.run.side_effect = fake_run
        vecs = emb.embed_many(["one", "two", "three"])
        self.assertEqual(len(vecs), 3)
        self.assertEqual(len(vecs[0]), 5)
        # L2-normalized rows
        for v in vecs:
            self.assertAlmostEqual(sum(x * x for x in v), 1.0, places=4)
        # batch_size=2 over 3 texts -> 2 session runs
        self.assertEqual(emb._session.run.call_count, 2)


class VectorStoreWiringTest(unittest.TestCase):
    def test_hash_fallback_without_onnx(self):
        with mock.patch.object(oe.OnnxEmbedder, "_ensure", return_value=False):
            v = VectorStoreManager(db_path=Path(tempfile.mkdtemp()))
            vec = v.embed("railway component manufacturer supply chain")
            self.assertEqual(len(vec), 384)
            self.assertAlmostEqual(sum(x * x for x in vec), 1.0, places=5)

    def test_embed_many_uses_onnx_singleton(self):
        fake_vecs = [[0.1] * 384, [0.2] * 384]
        with mock.patch.object(oe.onnx_embedder, "embed_many", return_value=fake_vecs) as m:
            v = VectorStoreManager(db_path=Path(tempfile.mkdtemp()))
            out = v.embed_many(["a", "b"])
            self.assertEqual(out, fake_vecs)
            m.assert_called_once()

    def test_search_applies_query_prefix(self):
        seen = {}

        def fake_embed(text, is_query=False):
            seen["is_query"] = is_query
            return [1.0] + [0.0] * 383

        with mock.patch.object(oe.onnx_embedder, "embed_many", return_value=[[1.0] + [0.0] * 383]):
            v = VectorStoreManager(db_path=Path(tempfile.mkdtemp()))
            v.embed = fake_embed
            v._rows = [{"id": "x", "text": "t", "vector": [1.0] + [0.0] * 383}]
            v.search("railway query")
            self.assertTrue(seen["is_query"])


if __name__ == "__main__":
    unittest.main()
