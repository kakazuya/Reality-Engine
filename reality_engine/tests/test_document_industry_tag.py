"""Document chunk industry tagging — derived via master_companies -> industries."""
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion.pdf_ingestor import PDFIngestor, backfill_document_chunk_industry_tags, derive_industry_id_for_symbol


def _make_pdf(path: Path, text: str = "Hello world financial report revenue growth"):
    try:
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text)
        doc.save(str(path))
        doc.close()
        return
    except Exception:
        # fallback: minimal pdf bytes
        path.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF")


class StubVectorStore:
    def embed(self, text):
        return [0.1] * 8
    def add_chunks(self, recs):
        return len(recs)
    def search(self, q, sym, k):
        return []


class TestDocumentIndustryTag(unittest.TestCase):
    def _setup_db(self, td):
        db_path = Path(td) / "test.db"
        mgr = DatabaseManager(db_path=db_path)
        repo = Repository(manager=mgr)
        # ensure industries table
        with mgr.session() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS industries (industry_id INTEGER PRIMARY KEY AUTOINCREMENT, sector_name TEXT, industry_name TEXT UNIQUE, secular_growth_score REAL, lifecycle_stage TEXT, tam_growth_cagr REAL)")
            conn.execute("INSERT OR IGNORE INTO industries (industry_name, sector_name) VALUES (?,?)", ("Capital Goods", "Industrials"))
            conn.execute("INSERT OR IGNORE INTO industries (industry_name, sector_name) VALUES (?,?)", ("IT Services", "Technology"))
        # fetch ids
        with mgr.session() as conn:
            cg_id = conn.execute("SELECT industry_id FROM industries WHERE industry_name='Capital Goods'").fetchone()[0]
            it_id = conn.execute("SELECT industry_id FROM industries WHERE industry_name='IT Services'").fetchone()[0]
        # master
        repo.upsert_master_companies([
            {"isin": "INE066F01020", "nse_symbol": "HAL", "company_name": "HINDUSTAN AERONAUTICS LTD", "industry": "Capital Goods", "is_active": 1},
            {"isin": "INE467B01029", "nse_symbol": "TCS", "company_name": "TATA CONSULTANCY SERVICES LTD", "industry": "IT Services", "is_active": 1},
        ])
        return mgr, repo, cg_id, it_id

    def test_chunk_industry_derived_from_company_join(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, repo, cg_id, _ = self._setup_db(td)
            # derive helper directly
            with mgr.session() as conn:
                iid = derive_industry_id_for_symbol("HAL", conn)
                self.assertEqual(iid, cg_id)
                self.assertIsNone(derive_industry_id_for_symbol("UNKNOWN", conn))
            # ingest PDF with symbol HAL -> chunk should have industry_id
            pdf = Path(td) / "hal.pdf"
            _make_pdf(pdf, "HAL Defence order book capex guidance")
            ingestor = PDFIngestor(db=mgr, vector_store=StubVectorStore())
            res = ingestor.ingest_pdf(pdf, symbol="HAL", isin="INE066F01020", source_type="Investor_Presentation")
            self.assertIn(res["status"], ("ingested", "skipped_duplicate"))
            with mgr.session() as conn:
                rows = conn.execute("SELECT industry_id, symbol FROM document_chunks WHERE symbol='HAL'").fetchall()
                self.assertGreater(len(rows), 0)
                for r in rows:
                    iid = r["industry_id"] if hasattr(r, "keys") and "industry_id" in r.keys() else r[0]
                    self.assertEqual(int(iid), int(cg_id))

    def test_backfill_fills_null_industry(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, repo, cg_id, it_id = self._setup_db(td)
            pdf = Path(td) / "tcs.pdf"
            _make_pdf(pdf, "TCS IT services revenue")
            # insert chunk with NULL industry manually - ensure document_chunks exists
            from reality_engine.ingestion.pdf_ingestor import _ensure_raw_tables
            with mgr.session() as conn:
                _ensure_raw_tables(conn)
                conn.execute("INSERT OR IGNORE INTO raw_documents (doc_id, title, source_type, published_date, sha256_hash) VALUES (1,'TCS doc','Investor_Presentation','2026-01-01','hash-tcs-1')")
                conn.execute("INSERT INTO document_chunks (doc_id, chunk_index, content, symbol, isin, industry_id) VALUES (1,0,'test content','TCS','INE467B01029',NULL)")
            updated = backfill_document_chunk_industry_tags(limit=100, manager=mgr)
            self.assertGreaterEqual(updated, 1)
            with mgr.session() as conn:
                iid = conn.execute("SELECT industry_id FROM document_chunks WHERE symbol='TCS' LIMIT 1").fetchone()[0]
                self.assertEqual(int(iid), int(it_id))

    def test_ingest_idempotent_preserves_industry(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, repo, cg_id, _ = self._setup_db(td)
            pdf = Path(td) / "hal2.pdf"
            _make_pdf(pdf, "HAL duplicate ingest test")
            ingestor = PDFIngestor(db=mgr, vector_store=StubVectorStore())
            r1 = ingestor.ingest_pdf(pdf, symbol="HAL", isin="INE066F01020")
            self.assertEqual(r1["status"], "ingested")
            with mgr.session() as conn:
                cnt1 = conn.execute("SELECT COUNT(*) FROM document_chunks WHERE symbol='HAL'").fetchone()[0]
                iid1 = conn.execute("SELECT industry_id FROM document_chunks WHERE symbol='HAL' LIMIT 1").fetchone()[0]
            r2 = ingestor.ingest_pdf(pdf, symbol="HAL", isin="INE066F01020")
            self.assertEqual(r2["status"], "skipped_duplicate")
            with mgr.session() as conn:
                cnt2 = conn.execute("SELECT COUNT(*) FROM document_chunks WHERE symbol='HAL'").fetchone()[0]
                iid2 = conn.execute("SELECT industry_id FROM document_chunks WHERE symbol='HAL' LIMIT 1").fetchone()[0]
            self.assertEqual(cnt1, cnt2)
            self.assertEqual(int(iid1), int(iid2))
            self.assertEqual(int(iid1), int(cg_id))


if __name__ == "__main__":
    unittest.main()
