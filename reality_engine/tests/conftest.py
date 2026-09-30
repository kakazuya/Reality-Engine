"""Shared heavy-engine fixtures for the Reality Engine test-suite (test-infra only).

Why this exists: several ingestion tests build :class:`PDFIngestor`, whose default
``ocr_engine`` constructs a fresh :class:`FinancialOCREngine`, and embedding tests
touch the :class:`OnnxEmbedder` singleton. Each DirectML session build costs ~1s
(OCR) / ~0.6-2s (ONNX) and is process-global state, so per-test construction
multiplies suite wall time with byte-identical results. These session-scoped
fixtures build each engine once per worker process and hand out the same instance.

Laziness contract (the perf_guards precedent — lazy properties, graceful fallback):
* Nothing is imported from ``reality_engine`` at collection time: every heavy
  import lives inside the fixture/getter body, so ``--collect-only`` stays fast.
* Nothing is *built* until first use: the OCR engine's ``engine``/``provider``
  are lazy properties and ``OnnxEmbedder._ensure`` runs on first ``embed`` call.
  Requesting the fixture alone never touches the GPU.
* GPU/driver absence never fails collection or the fixture: ``FinancialOCREngine``
  degrades to ``engine=None``/``provider="NONE"`` and ``OnnxEmbedder`` to
  ``available=False`` (hash fallback) — the same graceful-fallback pattern the
  engines already implement. Callers keep working; they just get CPU/fallback paths.

unittest bridge: most suite files are ``unittest.TestCase``, which cannot take
pytest fixture params. Those files use :func:`get_shared_ocr_engine` /
:func:`get_shared_onnx_embedder` directly (the same cached singletons the fixtures
return). pytest-style tests should prefer the ``shared_ocr_engine`` /
``shared_onnx_session`` fixture params.

Under ``pytest -n N`` (xdist) each worker is its own process, so "session-scoped"
means one shared instance per worker — still O(workers) builds, not O(tests).
"""

from __future__ import annotations

try:
    import pytest
except ImportError:  # plain `python -m unittest` without the dev-only pytest install
    class _NoPytest:
        def fixture(self, *args, **kwargs):
            def deco(fn):
                return fn
            return deco
    pytest = _NoPytest()  # type: ignore[assignment]

_cached_ocr_engine = None
_cached_ocr_failed = False
_cached_onnx_embedder = None


def get_shared_ocr_engine():
    """Process-scoped shared FinancialOCREngine (lazy, never raises).

    Returns None only if the (cheap, flag-storing) constructor itself raises;
    callers pass the result straight into ``PDFIngestor(ocr_engine=...)``, where
    None falls back to a fresh engine — identical behavior, no sharing.
    """
    global _cached_ocr_engine, _cached_ocr_failed
    if _cached_ocr_engine is None and not _cached_ocr_failed:
        from reality_engine.processing.ocr_engine import FinancialOCREngine

        try:
            _cached_ocr_engine = FinancialOCREngine()
        except Exception:
            _cached_ocr_failed = True
            return None
    return _cached_ocr_engine


def get_shared_onnx_embedder():
    """Process ``onnx_embedder`` singleton, returned COLD (no ``_ensure`` call).

    Warming is left to the first real ``embed`` call so merely requesting the
    fixture never pays session-init or probes the network.
    """
    global _cached_onnx_embedder
    if _cached_onnx_embedder is None:
        from reality_engine.ingestion.onnx_embedder import onnx_embedder

        _cached_onnx_embedder = onnx_embedder
    return _cached_onnx_embedder


@pytest.fixture(scope="session")
def shared_ocr_engine():
    """Session-scoped shared FinancialOCREngine. Lazy; safe without GPU/drivers."""
    return get_shared_ocr_engine()


@pytest.fixture(scope="session")
def shared_onnx_session():
    """Session-scoped shared ONNX embedder (the process singleton, cold).

    Named for the DirectML session it owns; the object handed out is the
    :class:`OnnxEmbedder` whose ``_ensure`` builds that session on first use.
    """
    return get_shared_onnx_embedder()
