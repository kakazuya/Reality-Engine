"""
Tests for macro-policy PDF ingestion into the dense substrate.

Covers :class:`PDFIngestor.ingest_macro_file` / ``ingest_macro_directory`` and the
``--ingest`` flag path of ``cmd_fetch_macro``. A tiny *real* PDF is generated with
PyMuPDF (fitz) so extraction is exercised without a model download; vector
embeddings are stubbed so no sentence-transformers model is fetched.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion.pdf_ingestor import PDFIngestor
from reality_engine.processing.pruning_engine import macro_source_type_to_category


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_repo(tmp_path: Path):
    """Return (DatabaseManager, Repository) backed by a fresh temp SQLite DB."""
    db_path = tmp_path / "macro_ingest_test.db"
    mgr = DatabaseManager(db_path=db_path)
    return mgr, Repository(manager=mgr)


class _StubVectorStore:
    """Dependency-free stand-in for VectorStoreManager (no model load, no LanceDB)."""

    def embed(self, text):  # noqa: D401 - intentional stub
        return [0.0, 1.0, 0.0]

    def add_chunks(self, chunks):
        return 0


def _make_pdf(path: Path, text: str) -> None:
    """Write a tiny real, text-extractable PDF using PyMuPDF (fitz)."""
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


class TestMacroIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="macro_ingest_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    def test_01_ingest_macro_file_creates_raw_and_chunks(self):
        mgr, repo = _make_repo(self.tmp)

        # Regression guard: pdf_ingestor must handle a *missing* FTS table
        # gracefully (it must never hard-fail when intelligence_fts is absent).
        with mgr.session() as conn:
            try:
                conn.execute("DROP TABLE IF EXISTS intelligence_fts")
            except Exception:
                pass

        pdf = self.tmp / "union_budget_2025.pdf"
        _make_pdf(
            pdf,
            "Union Budget 2025-26 capital expenditure outlay increased for "
            "infrastructure and railways by the Government of India.",
        )

        ingestor = PDFIngestor(db=mgr, vector_store=_StubVectorStore())
        res = ingestor.ingest_macro_file(
            pdf,
            source_type="Union_Budget",
            fiscal_period="FY2025-26",
            published_date="2025-02-01",
            creator_or_ministry="Ministry of Finance (GoI)",
        )

        self.assertEqual(res["status"], "ingested")

        # raw_documents must have exactly one row.
        rows = repo.list_raw_documents_by_source("")
        self.assertEqual(len(rows), 1, "exactly one raw_documents row expected")
        self.assertEqual(rows[0]["source_type"], "Union_Budget")

        # document_chunks must have >= 1 chunk and contain the PDF text.
        with mgr.session() as conn:
            n = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
            contents = [r[0] for r in conn.execute("SELECT content FROM document_chunks").fetchall()]
        self.assertGreaterEqual(n, 1, "expected at least one chunk")
        blob = "\n".join(contents)
        self.assertIn("capital expenditure outlay", blob, "chunk content must contain PDF text")

        # Regression guard: the macro source_type must map to a decay category and
        # ensure_decay_category_for_source must have recorded it in pruning_decay_config.
        self.assertEqual(macro_source_type_to_category("State_Budget_UP"), "State Budget")
        self.assertEqual(macro_source_type_to_category("PIB_Circular"), "PIB Circular")
        self.assertEqual(macro_source_type_to_category("RBI_Annual_Report"), "RBI Report / Economic Survey")
        with mgr.session() as conn:
            cat_row = conn.execute(
                "SELECT category FROM pruning_decay_config WHERE category=?",
                ("Union Budget / Tax Reform",),
            ).fetchone()
        self.assertIsNotNone(cat_row, "decay category for Union_Budget must be ensured")

    # ------------------------------------------------------------------
    def test_02_second_ingest_idempotent(self):
        mgr, repo = _make_repo(self.tmp)

        pdf = self.tmp / "pib_circular.pdf"
        _make_pdf(
            pdf,
            "PIB circular clarifies GST rates for renewable energy equipment "
            "effective FY2025-26 for domestic manufacturers.",
        )

        ingestor = PDFIngestor(db=mgr, vector_store=_StubVectorStore())
        r1 = ingestor.ingest_macro_file(
            pdf, source_type="PIB_Circular", published_date="2025-02-10"
        )
        self.assertEqual(r1["status"], "ingested")

        with mgr.session() as conn:
            first_chunks = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
        self.assertGreaterEqual(first_chunks, 1)

        # Second ingest of the SAME file must be a no-op.
        r2 = ingestor.ingest_macro_file(
            pdf, source_type="PIB_Circular", published_date="2025-02-10"
        )
        self.assertEqual(r2["status"], "skipped_duplicate")
        self.assertEqual(r2["doc_id"], r1["doc_id"], "same doc_id on re-ingest")

        rows = repo.list_raw_documents_by_source("")
        self.assertEqual(len(rows), 1, "no duplicate raw_documents row on re-ingest")

        with mgr.session() as conn:
            second_chunks = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
        self.assertEqual(second_chunks, first_chunks, "no duplicate chunks on re-ingest")

    # ------------------------------------------------------------------
    def test_03_process_macro_directory_scans_and_ingests(self):
        mgr, repo = _make_repo(self.tmp)

        scan_dir = self.tmp / "macro_pdfs"
        (scan_dir / "pib").mkdir(parents=True)
        (scan_dir / "rbi").mkdir(parents=True)
        p1 = scan_dir / "pib" / "pib1.pdf"
        p2 = scan_dir / "rbi" / "rbi1.pdf"
        _make_pdf(p1, "PIB circular about export incentive scheme for textiles sector announced.")
        _make_pdf(p2, "RBI annual report highlights inflation targeting and monetary policy stance.")

        ingestor = PDFIngestor(db=mgr, vector_store=_StubVectorStore())
        results = ingestor.ingest_macro_directory(scan_dir, recursive=True, dry_run=False)

        self.assertEqual(len(results), 2, "both PDFs should be scanned")
        for r in results:
            self.assertEqual(r.get("status"), "ingested", r)

        rows = repo.list_raw_documents_by_source("")
        self.assertEqual(len(rows), 2, "two raw_documents rows expected")

        # source_type should be derived from the category folder name.
        types = {r["source_type"] for r in rows}
        self.assertIn("PIB_Circular", types)
        self.assertIn("RBI_Annual_Report", types)

    # ------------------------------------------------------------------
    def test_04_cli_fetch_macro_ingest_flag_triggers_ingestion(self):
        from reality_engine.cli import cmd_fetch_macro

        pdf = self.tmp / "cli_macro.pdf"
        _make_pdf(pdf, "Union Budget 2025-26 infrastructure capex allocation document.")

        # Fake fetcher: only the central source returns a real local path; the
        # others return empty so we don't touch the network.
        fake_fetcher = mock.MagicMock()
        detail = {
            "ok": True,
            "path": str(pdf),
            "source_type": "Union_Budget",
            "title": "Union Budget 2025-26 Speech",
            "fiscal_period": "FY2025-26",
            "source_url": "http://example.com/ub.pdf",
            "published_date": "2025-02-01",
            "creator_or_ministry": "Ministry of Finance (GoI)",
        }
        fake_fetcher.fetch_central_budgets.return_value = {"details": [detail]}
        fake_fetcher.fetch_state_budgets.return_value = {"details": []}
        fake_fetcher.fetch_pib_circulars.return_value = {"details": []}
        fake_fetcher.fetch_rbi_reports.return_value = {"details": []}

        args = argparse.Namespace(
            source="central",
            years="2025-26",
            state_filter=None,
            workers=1,
            pib_limit=0,
            since_date=None,
            rate_limit=0.0,
            dry_run=False,
            ingest=True,
        )

        with mock.patch(
            "reality_engine.ingestion.macro_pdf_fetcher.MacroPDFFetcher",
            return_value=fake_fetcher,
        ), mock.patch(
            "reality_engine.ingestion.pdf_ingestor.PDFIngestor.ingest_macro_file",
            return_value={"status": "ingested", "chunks": 3},
        ) as m:
            cmd_fetch_macro(args)
            self.assertTrue(m.called, "cmd_fetch_macro --ingest must call ingest_macro_file")
            self.assertEqual(m.call_count, 1, "exactly one macro PDF should be ingested")
            _, kwargs = m.call_args
            self.assertEqual(kwargs.get("source_type"), "Union_Budget")
            self.assertEqual(kwargs.get("fiscal_period"), "FY2025-26")


if __name__ == "__main__":
    unittest.main(verbosity=2)
