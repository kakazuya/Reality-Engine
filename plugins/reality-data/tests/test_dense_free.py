"""Synthetic-folder tests for plugins/reality-data/server/dense_free.py.

No production database, model download, GPU or provider call is touched: the
index folders are tiny ``.npy`` files written into ``tests/fixtures/``.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER))

import numpy as np  # noqa: E402

import dense_free  # noqa: E402
import query_embed  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures"
DIM = 4096


def _vec(*pairs):
    out = np.zeros(DIM, dtype=np.float32)
    for index, value in pairs:
        out[index] = value
    return out


def _unit(vec):
    return (vec / np.linalg.norm(vec)).astype(np.float32)


class DenseFreeTest(unittest.TestCase):
    def setUp(self):
        FIXTURE.mkdir(exist_ok=True)
        self.root = FIXTURE / f"dense_free_{self._testMethodName}"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self._old_root = os.environ.get("REALITY_DATA_ROOT")
        os.environ["REALITY_DATA_ROOT"] = str(self.root)
        dense_free.clear()
        query_embed.close()
        self._cache = mock.patch.object(query_embed, "CACHE_DIR", self.root / ".qcache")
        self._qcache = mock.patch.object(dense_free, "QCACHE_DIR", self.root / ".qcache_vectors")
        self._cache.start()
        self._qcache.start()

    def tearDown(self):
        self._cache.stop()
        self._qcache.stop()
        query_embed.close()
        dense_free.clear()
        if self._old_root is None:
            os.environ.pop("REALITY_DATA_ROOT", None)
        else:
            os.environ["REALITY_DATA_ROOT"] = self._old_root
        shutil.rmtree(self.root, ignore_errors=True)

    def _index(self, name, vectors, ids, done=None):
        folder = self.root / f"vector_index_{name}"
        folder.mkdir(parents=True, exist_ok=True)
        np.save(folder / "chunk_vectors.npy", np.asarray(vectors, dtype=np.float16))
        np.save(folder / "chunk_ids.npy", np.asarray(ids, dtype=np.int64))
        (folder / "chunk_index_meta.json").write_text(
            json.dumps({"rows": len(ids), "dim": DIM}), encoding="utf-8"
        )
        if done is not None:
            np.save(folder / "done.npy", np.asarray(done, dtype=bool))
        return folder

    # ------------------------------------------------------------------
    def test_seed_vector_averages_only_ids_in_the_index(self):
        self._index(
            "nemotron8b",
            [_unit(_vec((0, 1.0))), _unit(_vec((1, 1.0))), _unit(_vec((2, 1.0)))],
            [10, 11, 12],
        )
        vec = dense_free.seed_vector("nemotron8b", [10, 11, 999])
        self.assertIsNotNone(vec)
        self.assertAlmostEqual(float(np.linalg.norm(vec)), 1.0, places=5)
        self.assertAlmostEqual(float(vec[0]), 0.70710678, places=4)
        self.assertAlmostEqual(float(vec[1]), 0.70710678, places=4)
        # Unknown-only seed set has no vector.
        self.assertIsNone(dense_free.seed_vector("nemotron8b", [999]))
        # Same text, different seeds -> different cached vectors.
        other = dense_free.seed_vector("nemotron8b", [12])
        self.assertAlmostEqual(float(other[2]), 1.0, places=5)

    def test_seed_search_finds_paraphrase_and_is_reproducible(self):
        near = _unit(_vec((0, 0.98), (1, 0.2)))     # close to the query but FTS-missed
        far = _unit(_vec((2, 1.0)))
        self._index(
            "nemotron8b",
            [_unit(_vec((0, 1.0))), near, far],
            [10, 11, 12],
        )
        first = dense_free.seed_search("milk procurement", "nemotron8b", [10], top_k=3)
        second = dense_free.seed_search("milk procurement", "nemotron8b", [10], top_k=3)
        self.assertEqual([int(h["chunk_id"]) for h in first], [10, 11, 12])
        self.assertEqual(first, second)
        # Symbol/type scoping still applies through allow_ids.
        scoped = dense_free.seed_search("milk procurement", "nemotron8b", [10], top_k=3,
                                        allow_ids={12})
        self.assertEqual([int(h["chunk_id"]) for h in scoped], [12])

    def test_equal_scores_break_ties_by_chunk_id(self):
        same = _unit(_vec((0, 1.0)))
        self._index("nemotron8b", [same, same, same], [10, 20, 30])
        hits = dense_free.seed_search("any query", "nemotron8b", [20], top_k=3)
        self.assertEqual([int(h["chunk_id"]) for h in hits], [10, 20, 30])

    def test_seed_search_skips_chunks_outside_done_mask(self):
        self._index(
            "qwen8b_ar",
            [_unit(_vec((0, 1.0))), _unit(_vec((0, 0.9), (1, 0.1)))],
            [40, 41],
            done=[True, False],
        )
        hits = dense_free.seed_search("annual report", "qwen8b_ar", [40], top_k=5)
        self.assertEqual([int(h["chunk_id"]) for h in hits], [40])

    def test_query_vectors_are_cached_on_disk(self):
        calls = []

        def produce():
            calls.append(1)
            return [1.0, 0.0, 0.0]

        first = dense_free.cached_vector("fake-model", "same text", produce)
        second = dense_free.cached_vector("fake-model", "same text", produce)
        self.assertEqual(len(calls), 1)
        self.assertTrue(np.allclose(first, [1.0, 0.0, 0.0]))
        self.assertTrue(np.allclose(first, second))
        files = list(dense_free.QCACHE_DIR.glob("*.npy"))
        self.assertEqual(len(files), 1)
        dense_free.cached_vector("fake-model", "other text", produce)
        self.assertEqual(len(calls), 2)

    def test_local_query_vector_uses_embedder_once(self):
        class FakeEmbedder:
            def __init__(self):
                self.calls = 0

            def embed(self, text, is_query=False):
                self.calls += 1
                return [0.0, 2.0, 0.0]

        embedder = FakeEmbedder()
        first = dense_free.local_query_vector(embedder, "milk procurement")
        second = dense_free.local_query_vector(embedder, "milk procurement")
        self.assertEqual(embedder.calls, 1)
        self.assertTrue(np.allclose(first, [0.0, 1.0, 0.0]))
        self.assertTrue(np.allclose(first, second))
        self.assertIsNone(dense_free.local_query_vector(None, "anything"))

    def test_order_hits_is_deterministic(self):
        hits = [
            {"chunk_id": 5, "score": 0.5},
            {"chunk_id": 2, "score": 0.5},
            {"chunk_id": 9, "score": 0.9},
        ]
        self.assertEqual(
            [h["chunk_id"] for h in dense_free.order_hits(hits)], [9, 2, 5]
        )
        self.assertEqual(
            [h["chunk_id"] for h in dense_free.order_hits(list(reversed(hits)))], [9, 2, 5]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
