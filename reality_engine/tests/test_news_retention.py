"""Tests for news_retention: extract-then-delete with fail-closed extraction proof.

Deterministic, zero network. Fresh temp-file SQLite DB via DatabaseManager; the
live DB is never opened. Seeded shape (mirrors the NewsRss writer contract):
``source_type = "News_<feed>"`` and ``intelligence_fts.chunk_id =
f"{source_type}:{doc_id}:0"``.

Covered:
  1. dry_run counts candidates/would-delete but removes nothing.
  2. apply deletes ONLY the old extracted news row (+ its FTS chunk).
  3. unextracted, structural-milestone, fresh, and non-news rows survive.
  4. a chunk belonging to a different source_type is NOT extraction proof.
  5. local_file_path outside the data dir is refused (no unlink) + recorded as error.
  6. delete_files=False never touches files; delete_files=True unlinks an in-dir file.
  7. news_retention_report splits fresh vs aged at the same cutoff.
"""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reality_engine.config import DATA_DIR
from reality_engine.db.database import DatabaseManager
from reality_engine.pipeline.news_retention import (
    news_retention_report,
    prune_news,
    prune_news_images,
)

OLD = (dt.date.today() - dt.timedelta(days=60)).isoformat()
FRESH = dt.date.today().isoformat()
OLD_TS = f"{OLD} 00:00:00"
FRESH_TS = f"{FRESH} 00:00:00"


def _mgr(tmp: Path) -> DatabaseManager:
    mgr = DatabaseManager(db_path=tmp / "news_retention_test.db")
    with mgr.session() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info('raw_documents')").fetchall()}
        if "is_structural_milestone" not in cols:
            conn.execute(
                "ALTER TABLE raw_documents ADD COLUMN is_structural_milestone INTEGER DEFAULT 0"
            )
    return mgr


def _seed_doc(mgr, source_type: str, published: str, *, milestone: int = 0,
              local_file_path=None) -> int:
    key = uuid.uuid4().hex
    with mgr.session() as conn:
        cur = conn.execute(
            "INSERT INTO raw_documents "
            "(title, source_type, published_date, source_url, sha256_hash, "
            " local_file_path, is_structural_milestone) "
            "VALUES (?,?,?,?,?,?,?)",
            (f"title-{key}", source_type, published, f"https://example.test/{key}",
             f"sha-{key}", local_file_path, milestone),
        )
        return int(cur.lastrowid)


def _seed_chunk(mgr, chunk_id: str, source_type: str, document_date: str) -> None:
    with mgr.session() as conn:
        conn.execute(
            "INSERT INTO intelligence_fts "
            "(chunk_id, symbol, isin, source_type, document_date, document_text) "
            "VALUES (?,?,?,?,?,?)",
            (chunk_id, None, None, source_type, document_date, "extracted body text"),
        )


def _row_exists(mgr, doc_id: int) -> bool:
    with mgr.session() as conn:
        return conn.execute(
            "SELECT 1 FROM raw_documents WHERE doc_id = ?", (doc_id,)
        ).fetchone() is not None


def _chunk_count(mgr, chunk_id: str) -> int:
    with mgr.session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM intelligence_fts WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        return int(row[0])


def _raw_count(mgr) -> int:
    with mgr.session() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM raw_documents").fetchone()[0])


# --- news_visual_artifacts (news_vision's table; mirror of its DDL contract) ---

_IMAGE_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS news_visual_artifacts ("
    " artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " doc_id INTEGER, symbol TEXT, source_type TEXT, source_url TEXT, media_url TEXT,"
    " local_path TEXT, ocr_text TEXT, ocr_confidence REAL, ocr_chars INTEGER,"
    " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
)

IMAGE_OCR_TEXT = "DALAL STREET -0.48% +1.24%"


def _ensure_image_table(mgr) -> None:
    with mgr.session() as conn:
        conn.execute(_IMAGE_TABLE_DDL)


def _seed_image_artifact(mgr, doc_id: int, source_type: str, *, created_at=OLD_TS,
                         local_path=None) -> int:
    with mgr.session() as conn:
        cur = conn.execute(
            "INSERT INTO news_visual_artifacts "
            "(doc_id, symbol, source_type, source_url, media_url, local_path, "
            " ocr_text, ocr_confidence, ocr_chars, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (doc_id, None, source_type, "https://example.test/a",
             "https://cdn.example.test/chart.png", local_path, IMAGE_OCR_TEXT,
             0.99, len(IMAGE_OCR_TEXT), created_at),
        )
        return int(cur.lastrowid)


def _image_row(mgr, artifact_id: int):
    """The artifact row's (local_path, ocr_text, media_url) or None if gone."""
    with mgr.session() as conn:
        row = conn.execute(
            "SELECT local_path, ocr_text, media_url FROM news_visual_artifacts "
            "WHERE artifact_id = ?", (artifact_id,),
        ).fetchone()
    if row is None:
        return None
    return {"local_path": row[0], "ocr_text": row[1], "media_url": row[2]}


def _image_artifact_count(mgr) -> int:
    with mgr.session() as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM news_visual_artifacts").fetchone()[0]
        )


class NewsRetentionTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.mgr = _mgr(self.tmp)
        self._scratch: list[Path] = []

    def tearDown(self):
        for p in self._scratch:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        self._tmp.cleanup()

    def _in_dir_file(self) -> Path:
        """Unique scratch artifact under the repo data dir (removed in tearDown)."""
        p = Path(DATA_DIR) / f"_news_retention_test_{uuid.uuid4().hex}.pdf"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4 test artifact")
        self._scratch.append(p)
        return p

    def _in_image_dir_file(self) -> Path:
        """Unique scratch bitmap under DATA_DIR/news_images (removed in tearDown)."""
        p = Path(DATA_DIR) / "news_images" / f"_news_vision_test_{uuid.uuid4().hex}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n\x1a\n test bitmap")
        self._scratch.append(p)
        return p

    def _proven_image(self) -> tuple:
        """(doc_id, artifact_id, bitmap_path): old row WITH its ':img' OCR chunk."""
        bmp = self._in_image_dir_file()
        doc = _seed_doc(self.mgr, "News_livemint", OLD)
        _seed_chunk(self.mgr, f"News_livemint:{doc}:img", "News_livemint", OLD)
        art = _seed_image_artifact(self.mgr, doc, "News_livemint", local_path=str(bmp))
        return doc, art, bmp

    def _seed_world(self, *, outside_path=None, in_dir_path=None):
        """extracted-old | unextracted-old | structural-old | fresh | non-news-old."""
        extracted = _seed_doc(self.mgr, "News_livemint", OLD)
        unextracted = _seed_doc(self.mgr, "News_et", OLD)
        structural = _seed_doc(self.mgr, "News_bs", OLD, milestone=1)
        fresh = _seed_doc(self.mgr, "News_livemint_co", FRESH)
        other = _seed_doc(self.mgr, "PIB_Press_Release", OLD)
        _seed_chunk(self.mgr, f"News_livemint:{extracted}:0", "News_livemint", OLD)
        # Wrong-source chunk: same doc_id, different source_type -> NOT proof.
        _seed_chunk(self.mgr, f"News_livemint:{unextracted}:0", "News_livemint", OLD)
        _seed_chunk(self.mgr, f"News_bs:{structural}:0", "News_bs", OLD)
        _seed_chunk(self.mgr, f"PIB_Press_Release:{other}:0", "PIB_Press_Release", OLD)
        return extracted, unextracted, structural, fresh, other


class TestDryRun(NewsRetentionTestBase):
    def test_dry_run_counts_would_deletes_but_removes_nothing(self):
        extracted, unextracted, structural, fresh, other = self._seed_world()
        before = _raw_count(self.mgr)

        out = prune_news(before_days=30, dry_run=True, db=self.mgr)

        # candidates = the two prunable old news rows (extracted is provable; the
        # unextracted one is a candidate too but gets skipped below).
        self.assertEqual(out["candidates"], 2)
        self.assertEqual(out["skipped_structural"], 1)
        self.assertEqual(out["skipped_unextracted"], 1)
        self.assertEqual(out["raw_deleted"], 1)     # would-delete
        self.assertEqual(out["fts_deleted"], 1)     # would-delete
        self.assertEqual(out["files_deleted"], 0)
        self.assertEqual(out["errors"], [])
        self.assertEqual(
            out["cutoff"], (dt.date.today() - dt.timedelta(days=30)).isoformat()
        )

        # Nothing deleted.
        self.assertEqual(_raw_count(self.mgr), before)
        for doc_id in (extracted, unextracted, structural, fresh, other):
            self.assertTrue(_row_exists(self.mgr, doc_id), f"doc_id={doc_id} vanished")
        self.assertEqual(_chunk_count(self.mgr, f"News_livemint:{extracted}:0"), 1)


class TestApply(NewsRetentionTestBase):
    def test_apply_prunes_only_extracted_news(self):
        extracted, unextracted, structural, fresh, other = self._seed_world()

        out = prune_news(before_days=30, dry_run=False, db=self.mgr)

        self.assertEqual(out["candidates"], 2)
        self.assertEqual(out["raw_deleted"], 1)
        self.assertEqual(out["fts_deleted"], 1)
        self.assertEqual(out["files_deleted"], 0)
        self.assertEqual(out["skipped_unextracted"], 1)
        self.assertEqual(out["skipped_structural"], 1)
        self.assertEqual(out["errors"], [])

        # The one fully-extracted old news row is gone, chunk included.
        self.assertFalse(_row_exists(self.mgr, extracted))
        self.assertEqual(_chunk_count(self.mgr, f"News_livemint:{extracted}:0"), 0)

        # Everything else survives, chunks intact.
        self.assertTrue(_row_exists(self.mgr, unextracted))
        self.assertEqual(_chunk_count(self.mgr, f"News_livemint:{unextracted}:0"), 1)
        self.assertTrue(_row_exists(self.mgr, structural))
        self.assertTrue(_row_exists(self.mgr, fresh))
        self.assertTrue(_row_exists(self.mgr, other))
        self.assertEqual(_chunk_count(self.mgr, f"PIB_Press_Release:{other}:0"), 1)

        # Re-running is a no-op: the pruned row is gone, the rest stays.
        again = prune_news(before_days=30, dry_run=False, db=self.mgr)
        self.assertEqual(again["raw_deleted"], 0)
        self.assertEqual(again["candidates"], 1)
        self.assertEqual(again["skipped_unextracted"], 1)
        self.assertTrue(_row_exists(self.mgr, unextracted))
        self.assertTrue(_row_exists(self.mgr, structural))

    def test_candidates_empty_when_nothing_is_old_enough(self):
        doc = _seed_doc(self.mgr, "News_ndtvprofit", FRESH)
        _seed_chunk(self.mgr, f"News_ndtvprofit:{doc}:0", "News_ndtvprofit", FRESH)

        out = prune_news(before_days=30, dry_run=False, db=self.mgr)

        self.assertEqual(out["candidates"], 0)
        self.assertEqual(out["raw_deleted"], 0)
        self.assertEqual(out["fts_deleted"], 0)
        self.assertTrue(_row_exists(self.mgr, doc))


class TestFileGate(NewsRetentionTestBase):
    def test_outside_data_dir_path_is_refused_and_recorded(self):
        outside = self.tmp / "outside_artifact.pdf"   # tempdir != repo data dir
        outside.write_bytes(b"not ours to delete")
        doc = _seed_doc(self.mgr, "News_businessline", OLD, local_file_path=str(outside))
        _seed_chunk(self.mgr, f"News_businessline:{doc}:0", "News_businessline", OLD)

        out = prune_news(before_days=30, dry_run=False, delete_files=True, db=self.mgr)

        self.assertTrue(out["errors"], "outside path must be recorded as an error")
        self.assertTrue(any("outside data dir" in e for e in out["errors"]), out["errors"])
        self.assertEqual(out["files_deleted"], 0)
        self.assertTrue(outside.exists(), "outside file must never be unlinked")
        # Extraction was proven, so the DB row is still pruned.
        self.assertEqual(out["raw_deleted"], 1)
        self.assertFalse(_row_exists(self.mgr, doc))

    def test_delete_files_false_leaves_files_alone(self):
        in_dir = self._in_dir_file()
        doc = _seed_doc(self.mgr, "News_livemint", OLD, local_file_path=str(in_dir))
        _seed_chunk(self.mgr, f"News_livemint:{doc}:0", "News_livemint", OLD)

        out = prune_news(before_days=30, dry_run=False, delete_files=False, db=self.mgr)

        self.assertEqual(out["files_deleted"], 0)
        self.assertEqual(out["errors"], [])
        self.assertTrue(in_dir.exists(), "delete_files=False must leave the file")
        self.assertFalse(_row_exists(self.mgr, doc))
        self.assertEqual(_chunk_count(self.mgr, f"News_livemint:{doc}:0"), 0)

    def test_delete_files_true_unlinks_in_dir_file_after_db_delete(self):
        in_dir = self._in_dir_file()
        doc = _seed_doc(self.mgr, "News_livemint", OLD, local_file_path=str(in_dir))
        _seed_chunk(self.mgr, f"News_livemint:{doc}:0", "News_livemint", OLD)

        out = prune_news(before_days=30, dry_run=False, delete_files=True, db=self.mgr)

        self.assertEqual(out["files_deleted"], 1)
        self.assertEqual(out["errors"], [])
        self.assertFalse(_row_exists(self.mgr, doc))
        self.assertFalse(in_dir.exists(), "in-data-dir artifact should be unlinked")

    def test_dry_run_never_unlinks_even_with_delete_files(self):
        in_dir = self._in_dir_file()
        doc = _seed_doc(self.mgr, "News_livemint", OLD, local_file_path=str(in_dir))
        _seed_chunk(self.mgr, f"News_livemint:{doc}:0", "News_livemint", OLD)

        out = prune_news(before_days=30, dry_run=True, delete_files=True, db=self.mgr)

        self.assertEqual(out["files_deleted"], 1)   # would-delete count
        self.assertTrue(in_dir.exists())
        self.assertTrue(_row_exists(self.mgr, doc))


class TestReport(NewsRetentionTestBase):
    def test_report_splits_fresh_and_aged_at_default_cutoff(self):
        _, _, _, fresh, _ = self._seed_world()
        rep = news_retention_report(db=self.mgr)

        # 4 news rows: 1 fresh, 3 old (extracted, unextracted, structural).
        self.assertEqual(rep["total"], 4)
        self.assertEqual(rep["fresh"], 1)
        self.assertEqual(rep["aged_untouched"], 3)
        self.assertEqual(rep["fresh"] + rep["aged_untouched"], rep["total"])

    def test_report_decreases_after_apply(self):
        self._seed_world()
        prune_news(before_days=30, dry_run=False, db=self.mgr)

        rep = news_retention_report(db=self.mgr)

        self.assertEqual(rep["total"], 3)
        self.assertEqual(rep["fresh"], 1)
        self.assertEqual(rep["aged_untouched"], 2)

    def test_report_accepts_db_as_first_positional(self):
        """Contract: news_retention_report(db=None) — db is positional #1."""
        _, _, _, _, _ = self._seed_world()

        rep = news_retention_report(self.mgr)

        self.assertEqual(rep["total"], 4)

    def test_report_empty_db_is_zeroed(self):
        rep = news_retention_report(db=self.mgr)
        self.assertEqual(rep, {"fresh": 0, "aged_untouched": 0, "total": 0})


class TestFailClosed(NewsRetentionTestBase):
    def test_missing_fts_table_keeps_everything(self):
        doc = _seed_doc(self.mgr, "News_livemint", OLD)
        with self.mgr.session() as conn:
            conn.execute("DROP TABLE intelligence_fts")

        out = prune_news(before_days=30, dry_run=False, db=self.mgr)

        self.assertEqual(out["raw_deleted"], 0)
        self.assertTrue(out["errors"])
        self.assertTrue(_row_exists(self.mgr, doc))

    def test_bad_db_object_never_raises(self):
        out = prune_news(before_days=30, dry_run=False, db=object())
        self.assertEqual(out["raw_deleted"], 0)
        self.assertTrue(out["errors"])


class TestImagePrune(NewsRetentionTestBase):
    """prune_news_images: drop the bitmap, keep the dense (OCR) record."""

    def setUp(self):
        super().setUp()
        _ensure_image_table(self.mgr)

    def test_image_dry_run_deletes_nothing(self):
        _, art, bmp = self._proven_image()

        out = prune_news_images(before_days=30, dry_run=True, delete_files=True, db=self.mgr)

        self.assertEqual(out["cutoff"], (dt.date.today() - dt.timedelta(days=30)).isoformat())
        self.assertEqual(out["candidates"], 1)
        self.assertEqual(out["files_deleted"], 1)      # would-delete
        self.assertEqual(out["rows_cleared"], 1)       # would-clear
        self.assertEqual(out["skipped_no_chunk"], 0)
        self.assertEqual(out["errors"], [])

        self.assertTrue(bmp.exists(), "dry run must not unlink the bitmap")
        self.assertEqual(_image_row(self.mgr, art)["local_path"], str(bmp))

    def test_apply_removes_only_proven_images_and_clears_the_pointer(self):
        doc, proven, proven_bmp = self._proven_image()
        # Second row: only the article text chunk (...:0) exists — documents and
        # bitmaps are separate extractions, so a text chunk proves nothing here.
        unproven_bmp = self._in_image_dir_file()
        other = _seed_doc(self.mgr, "News_et", OLD)
        _seed_chunk(self.mgr, f"News_et:{other}:0", "News_et", OLD)
        unproven = _seed_image_artifact(self.mgr, other, "News_et",
                                        local_path=str(unproven_bmp))

        out = prune_news_images(before_days=30, dry_run=False, delete_files=True, db=self.mgr)

        self.assertEqual(out["candidates"], 2)
        self.assertEqual(out["files_deleted"], 1)
        self.assertEqual(out["rows_cleared"], 1)
        self.assertEqual(out["skipped_no_chunk"], 1)
        self.assertEqual(out["errors"], [])

        # Proven row: bitmap gone, pointer cleared, OCR text + chunk retained.
        self.assertFalse(proven_bmp.exists())
        self.assertIsNone(_image_row(self.mgr, proven)["local_path"])
        self.assertEqual(_image_row(self.mgr, proven)["ocr_text"], IMAGE_OCR_TEXT)
        self.assertEqual(_image_row(self.mgr, proven)["media_url"],
                         "https://cdn.example.test/chart.png")
        self.assertEqual(_chunk_count(self.mgr, f"News_livemint:{doc}:img"), 1)

        # Unproven row: kept whole — row, bitmap, pointer.
        self.assertTrue(unproven_bmp.exists(), "unproven bitmap must never be unlinked")
        self.assertEqual(_image_row(self.mgr, unproven)["local_path"], str(unproven_bmp))
        self.assertEqual(_image_row(self.mgr, unproven)["ocr_text"], IMAGE_OCR_TEXT)
        self.assertEqual(_image_artifact_count(self.mgr), 2)

    def test_outside_data_dir_path_is_refused_and_recorded(self):
        outside = self.tmp / "outside_chart.png"      # tempdir != repo data dir
        outside.write_bytes(b"\x89PNG not ours to delete")
        doc = _seed_doc(self.mgr, "News_businessline", OLD)
        _seed_chunk(self.mgr, f"News_businessline:{doc}:img", "News_businessline", OLD)
        art = _seed_image_artifact(self.mgr, doc, "News_businessline",
                                   local_path=str(outside))

        out = prune_news_images(before_days=30, dry_run=False, delete_files=True, db=self.mgr)

        self.assertEqual(out["files_deleted"], 0)
        self.assertTrue(any("outside data dir" in e for e in out["errors"]), out["errors"])
        self.assertTrue(outside.exists(), "outside file must never be unlinked")
        self.assertEqual(out["rows_cleared"], 1)
        self.assertIsNone(_image_row(self.mgr, art)["local_path"])
        self.assertEqual(_image_row(self.mgr, art)["ocr_text"], IMAGE_OCR_TEXT)

    def test_delete_files_false_clears_pointer_without_unlinking(self):
        _, art, bmp = self._proven_image()

        out = prune_news_images(before_days=30, dry_run=False, delete_files=False, db=self.mgr)

        self.assertEqual(out["files_deleted"], 0)
        self.assertEqual(out["rows_cleared"], 1)
        self.assertEqual(out["errors"], [])
        self.assertTrue(bmp.exists(), "delete_files=False must leave the bitmap")
        self.assertIsNone(_image_row(self.mgr, art)["local_path"])
        self.assertEqual(_image_row(self.mgr, art)["ocr_text"], IMAGE_OCR_TEXT)

    def test_pointer_to_already_unlinked_bitmap_is_cleared_without_error(self):
        """Dominant real case: capture_images(keep_files=False) wrote local_path and
        then unlinked the bitmap, so the row points at a path that no longer exists.
        Fewer files_deleted than candidates is expected, not a broken gate."""
        doc = _seed_doc(self.mgr, "News_livemint", OLD)
        _seed_chunk(self.mgr, f"News_livemint:{doc}:img", "News_livemint", OLD)
        gone = (Path(DATA_DIR) / "news_images"
                / f"_already_unlinked_{uuid.uuid4().hex}.jpg")
        art = _seed_image_artifact(self.mgr, doc, "News_livemint", local_path=str(gone))

        out = prune_news_images(before_days=30, dry_run=False, delete_files=True, db=self.mgr)

        self.assertEqual(out["files_deleted"], 0, "nothing left to unlink")
        self.assertEqual(out["rows_cleared"], 1, "stale pointer is still tidied")
        self.assertEqual(out["errors"], [], "an absent bitmap is not a failure")
        self.assertIsNone(_image_row(self.mgr, art)["local_path"])
        self.assertEqual(_image_row(self.mgr, art)["ocr_text"], IMAGE_OCR_TEXT)

    def test_fresh_image_rows_are_not_candidates(self):
        bmp = self._in_image_dir_file()
        doc = _seed_doc(self.mgr, "News_livemint", FRESH)
        _seed_chunk(self.mgr, f"News_livemint:{doc}:img", "News_livemint", FRESH)
        art = _seed_image_artifact(self.mgr, doc, "News_livemint",
                                   created_at=FRESH_TS, local_path=str(bmp))

        out = prune_news_images(before_days=30, dry_run=False, delete_files=True, db=self.mgr)

        self.assertEqual(out["candidates"], 0)
        self.assertEqual(out["files_deleted"], 0)
        self.assertTrue(bmp.exists())
        self.assertEqual(_image_row(self.mgr, art)["local_path"], str(bmp))

    def test_unknown_created_at_is_unprovably_old_and_kept(self):
        doc = _seed_doc(self.mgr, "News_livemint", OLD)
        _seed_chunk(self.mgr, f"News_livemint:{doc}:img", "News_livemint", OLD)
        art = _seed_image_artifact(self.mgr, doc, "News_livemint", created_at=None)

        out = prune_news_images(before_days=30, dry_run=False, delete_files=True, db=self.mgr)

        self.assertEqual(out["candidates"], 0)
        self.assertEqual(out["rows_cleared"], 0)
        self.assertIsNotNone(_image_row(self.mgr, art))


class TestImageFailClosed(NewsRetentionTestBase):
    def test_missing_artifact_table_never_raises(self):
        out = prune_news_images(before_days=30, dry_run=False, delete_files=True, db=self.mgr)

        self.assertEqual(out["candidates"], 0)
        self.assertEqual(out["files_deleted"], 0)
        self.assertEqual(out["rows_cleared"], 0)
        self.assertTrue(out["errors"])

    def test_bad_db_object_never_raises(self):
        out = prune_news_images(before_days=30, dry_run=False, db=object())

        self.assertEqual(out["rows_cleared"], 0)
        self.assertTrue(out["errors"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
