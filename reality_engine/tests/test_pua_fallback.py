"""PUA-poison text-layer fallback (Slice E).

Proven cause: a PDF whose text layer is ~314k chars of U+F0xx PUA
(299,549 PUA, 0 ASCII) from an unembedded custom font. prune() passes
it through; the BPE tokenizer collapses it to 2 ids with empty decode
-> 0 chunks, surfacing as a generic ``no_chunks`` poison-doc retry loop.

Contract:
* :func:`pua_rate` (fraction of chars in U+E000-U+F8FF) with the
  pre-registered threshold 0.5 lives in document_parser.
* pdf_ingestor routes PUA-poisoned PDFs to the scanned-image OCR path
  (RapidOCR pixmap) instead of trusting the text layer.
* If OCR also yields nothing the result status is ``no_text_layer``
  (distinct from ``no_chunks``) so the queue can quarantine by cause.
* Normal text is unaffected (no OCR detour, ingests as before).

Temp/synthetic fixtures only -- never touches the live DB.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.db.database import DatabaseManager
from reality_engine.ingestion.pdf_ingestor import PDFIngestor
from reality_engine.processing.document_parser import (
    PUA_POISON_THRESHOLD,
    is_pua_poisoned,
    pua_rate,
)

# Synthetic fixtures -----------------------------------------------------
PUA_TEXT = "\uf001\uf002\uf003\uf004" * 800  # 3200 chars, 100% PUA
NORMAL_TEXT = (
    "Union Budget 2025-26 capital expenditure outlay increased for "
    "infrastructure, railways and rural housing. The Finance Minister "
    "announced a revised fiscal deficit target with higher devolution "
    "to the states for centrally sponsored schemes and irrigation. "
) * 6  # >300 chars of plain ASCII
RECOVERED_TEXT = (
    "Annual report revenue from operations grew twelve percent with "
    "operating margins expanding on lower input costs and strong "
    "rural demand across the tractor and farm equipment portfolio. "
) * 6


class _StubVectorStore:
    """Dependency-free stand-in (no model load, no LanceDB)."""

    def embed_many(self, texts):
        return [None] * len(texts)

    def embed(self, text):
        return [0.0, 1.0, 0.0]

    def add_chunks(self, chunks):
        return 0


def _stub_ocr(raw_text, called):
    def _process_image(_path):
        called.append(True)
        return {"raw_text": raw_text}

    return SimpleNamespace(engine=object(), provider="STUB", process_image=_process_image)


class _FakePix:
    def save(self, name):
        Path(name).write_bytes(b"fake-pixmap")


class _FakePage:
    def __init__(self, text):
        self._text = text

    def get_text(self, *args, **kwargs):
        return self._text

    def get_pixmap(self, *args, **kwargs):
        return _FakePix()


class _FakeDoc:
    """Mimics the fitz Document surface pdf_ingestor uses (context manager + pages)."""

    def __init__(self, pages):
        self._pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self._pages)


def _make_pdf(path: Path, text: str) -> None:
    """Write a tiny real, text-extractable PDF using PyMuPDF (fitz)."""
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(72, 72, 523, 770), text)
    doc.save(str(path))
    doc.close()


class TestPuaFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pua_fallback_"))
        self.mgr = DatabaseManager(db_path=self.tmp / "pua_test.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- detector ------------------------------------------------------
    def test_01_pua_rate_detector(self):
        self.assertEqual(PUA_POISON_THRESHOLD, 0.5)
        self.assertGreater(pua_rate(PUA_TEXT), 0.5)
        self.assertTrue(is_pua_poisoned(PUA_TEXT))
        self.assertEqual(pua_rate(NORMAL_TEXT), 0.0)
        self.assertFalse(is_pua_poisoned(NORMAL_TEXT))
        self.assertEqual(pua_rate(""), 0.0)
        self.assertFalse(is_pua_poisoned(""))
        # Mostly-normal text with a few stray PUA glyphs stays below threshold.
        self.assertFalse(is_pua_poisoned(NORMAL_TEXT + "\uf001\uf002"))

    # -- OCR route ------------------------------------------------------
    def test_02_poisoned_pdf_routes_to_ocr(self):
        called: list = []
        ingestor = PDFIngestor(
            db=self.mgr, vector_store=_StubVectorStore(), ocr_engine=_stub_ocr(RECOVERED_TEXT, called)
        )
        fake = _FakeDoc([_FakePage(PUA_TEXT)])
        with mock.patch("fitz.open", return_value=fake):
            text = ingestor.extract_text(self.tmp / "poison.pdf")
        self.assertTrue(called, "PUA-poisoned text layer must trigger the pixmap OCR path")
        self.assertIn("tractor and farm equipment", text)
        self.assertFalse(is_pua_poisoned(text), "OCR output must replace the poison layer")

    def test_03_normal_pdf_unaffected(self):
        called: list = []
        ingestor = PDFIngestor(
            db=self.mgr, vector_store=_StubVectorStore(), ocr_engine=_stub_ocr(RECOVERED_TEXT, called)
        )
        pdf = self.tmp / "normal.pdf"
        _make_pdf(pdf, NORMAL_TEXT)
        res = ingestor.ingest_pdf(pdf, source_type="Test_Doc", published_date="2026-08-14")
        self.assertFalse(called, "normal text must not take the OCR detour")
        self.assertEqual(res["status"], "ingested")
        self.assertGreaterEqual(res["chunks"], 1)

    # -- no_text_layer ---------------------------------------------------
    def test_04_ocr_empty_returns_no_text_layer(self):
        called: list = []
        ingestor = PDFIngestor(
            db=self.mgr, vector_store=_StubVectorStore(), ocr_engine=_stub_ocr("", called)
        )
        pdf = self.tmp / "poison_empty.pdf"
        _make_pdf(pdf, NORMAL_TEXT)  # real file for sha; text layer is faked below
        fake = _FakeDoc([_FakePage(PUA_TEXT)])
        with mock.patch("fitz.open", return_value=fake):
            res = ingestor.ingest_pdf(pdf, source_type="Test_Doc", published_date="2026-08-14")
        self.assertTrue(called, "poisoned layer must still attempt OCR first")
        self.assertEqual(res["status"], "no_text_layer")
        self.assertNotEqual(res["status"], "no_chunks")
        self.assertEqual(res["chunks"], 0)
        self.assertIsNone(res["doc_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
