"""Guards for the shared heavy-engine test fixtures (see tests/conftest.py).

Hermetic: no temp DB, no network, no GPU required. Never warms the engines
(no ``.provider`` / ``.engine`` / ``embed`` access), so this file stays ~ms.
"""
import unittest


def _load():
    # Lazy imports: this module must add ~zero cost to --collect-only.
    from reality_engine.ingestion import onnx_embedder as oe
    from reality_engine.tests import conftest as shared
    return oe, shared


class TestSharedEngines(unittest.TestCase):
    def test_ocr_getter_returns_singleton(self):
        _, shared = _load()
        self.assertIs(shared.get_shared_ocr_engine(), shared.get_shared_ocr_engine())

    def test_onnx_getter_returns_process_singleton_without_warming(self):
        # Laziness guard: requesting the shared embedder must not itself flip
        # _probed, whatever state earlier tests in this worker left behind.
        oe, shared = _load()
        probed_before = oe.onnx_embedder._probed
        emb = shared.get_shared_onnx_embedder()
        self.assertIs(emb, oe.onnx_embedder)
        self.assertEqual(oe.onnx_embedder._probed, probed_before)


if __name__ == "__main__":
    unittest.main()
