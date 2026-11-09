"""Fixture tests for plugins/reality-data/server/lookups_semantic.py (T-154 ``pilot3_semantic``).

    python -m unittest plugins/reality-data/tests/test_lookups_semantic.py

Reuses the tiny pilot3 fixture of test_lookups_pilot3; vectors are written by hand and the query vector comes from
the hash cache, so no network, key or spend.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_lookups_pilot3 as fx  # noqa: E402

import lookups_pilot3 as p3  # noqa: E402
import lookups_semantic as sem  # noqa: E402

EMBED = fx.TMP / "semantic_embed"
QUERY = "how large is the order book"


def _unit(*values: float) -> list[float]:
    v = np.asarray(values, dtype=np.float32)
    return [float(x) for x in v / np.linalg.norm(v)]


class SemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fx.build_fixture()
        os.environ["REALITY_PILOT3_DB"] = str(fx.DB)
        os.environ["REALITY_PILOT3_EMBED_DIR"] = str(EMBED)
        os.environ.pop(sem.PAID_EMBED_FLAG, None)
        p3.close()
        EMBED.mkdir(parents=True, exist_ok=True)
        keys = [("pdfs/KEC/deck1.pdf", 1), ("pdfs/KEC/deck1.pdf", 2), ("pdfs/KEC/deck2.pdf", 1)]
        vectors = [_unit(0.9, 0.1, 0.0), _unit(0.0, 1.0, 0.0), _unit(1.0, 0.0, 0.0)]
        np.save(EMBED / "8b_text.npy", np.asarray(vectors, dtype=np.float32))
        (EMBED / "8b_text.index.json").write_text(json.dumps(
            [{"doc_key": k, "page": p, "kind": "text"} for k, p in keys]), encoding="utf-8")
        digest = hashlib.sha256(QUERY.encode("utf-8")).hexdigest()
        (EMBED / "query_cache_8b.json").write_text(json.dumps({digest: _unit(1.0, 0.0, 0.0)}), encoding="utf-8")
        sem._cache.clear()

    @classmethod
    def tearDownClass(cls) -> None:
        os.environ.pop("REALITY_PILOT3_EMBED_DIR", None)
        p3.close()

    def test_ranks_by_cosine_and_reports_coverage(self):
        out = sem.semantic("KEC", QUERY, limit=5)
        pages = [(r["provenance"]["source"]) for r in out["rows"]]
        self.assertEqual(pages[0], "pdfs/KEC/deck2.pdf p1")
        self.assertEqual(pages[1], "pdfs/KEC/deck1.pdf p1")
        self.assertFalse(out["paid_query"])
        self.assertEqual(out["coverage"]["pages_with_vectors"], 3)
        self.assertGreater(out["coverage"]["pool_pages"], 3)     # pages without a vector are counted, not ranked

    def test_as_of_drops_later_pages(self):
        out = sem.semantic("KEC", QUERY, as_of="2026-03-01", limit=5)
        sources = {r["provenance"]["source"] for r in out["rows"]}
        self.assertNotIn("pdfs/KEC/deck2.pdf p1", sources)
        self.assertTrue(all(r["provenance"]["known_at"][:10] <= "2026-03-01" for r in out["rows"]))

    def test_new_query_text_needs_the_paid_gate(self):
        with self.assertRaises(p3.DataError) as caught:
            sem.semantic("KEC", "an uncached question", limit=3)
        self.assertIn("REALITY_DATA_ALLOW_PAID_EMBED", str(caught.exception))

    def test_empty_pool_returns_not_found_without_a_paid_call(self):
        out = sem.semantic("KEC", "anything at all", as_of="2020-01-01")
        self.assertFalse(out["found"])
        self.assertEqual(out["coverage"]["pages_with_vectors"], 0)


if __name__ == "__main__":
    unittest.main()
