"""Acceptance checks for the pilot-60 history chunk store (manifest mode).

    python -m pytest reality_engine/tests/test_pilot60_history_chunks.py -q

The tests use a throwaway manifest and dummy bytes; PDF text is injected, so no
real PDF or live database is touched.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / ".tmp" / "history-chunk-tests"
DOC = "The company reported revenue of 1,234 crore and EBITDA of 210 crore. " * 30


def _load():
    path = REPO / "tasks" / "pilot60" / "build_chunks60_history.py"
    spec = importlib.util.spec_from_file_location("history_builder_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _row(**over) -> dict:
    row = {"isin": "INE000A01000", "symbol_at_time": "TESTCO",
           "newsid": "n-" + uuid.uuid4().hex[:12], "bucket": "material_filing",
           "headline": "Board meeting outcome", "category": "Others",
           "subcat": "General", "dissem_ts": "2020-01-02T15:04:05",
           "url": "https://example.invalid/x.pdf", "source": "bse_api",
           "local_path": "", "bytes": 4, "sha256": _sha(uuid.uuid4().hex),
           "status": "ok", "error": None, "is_scanned_guess": 0}
    row.update(over)
    return row


def _write_manifest(path: Path, rows: list[dict]) -> None:
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE docs (
        isin TEXT, symbol_at_time TEXT, scrip_code TEXT, newsid TEXT PRIMARY KEY,
        bucket TEXT, headline TEXT, category TEXT, subcat TEXT, dissem_ts TEXT,
        url TEXT, source TEXT, local_path TEXT, bytes INTEGER, sha256 TEXT,
        http_status INTEGER, attempts INTEGER DEFAULT 0, is_pdf INTEGER,
        is_scanned_guess INTEGER, skip_reason TEXT, fetched_at TEXT,
        status TEXT DEFAULT 'pending', error TEXT)""")
    for r in rows:
        con.execute("INSERT INTO docs (isin, symbol_at_time, newsid, bucket, headline, category, "
                    "subcat, dissem_ts, url, source, local_path, bytes, sha256, is_scanned_guess, "
                    "status, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["isin"], r["symbol_at_time"], r["newsid"], r["bucket"], r["headline"],
                     r["category"], r["subcat"], r["dissem_ts"], r["url"], r["source"],
                     r["local_path"], r["bytes"], r["sha256"], r["is_scanned_guess"],
                     r["status"], r["error"]))
    con.commit()
    con.close()


class HistoryChunkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        BASE.mkdir(parents=True, exist_ok=True)
        cls.h = _load()

    def setUp(self):
        self.tmp = BASE / uuid.uuid4().hex[:10]
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.root = self.tmp / "raw"
        self.manifest = self.tmp / "manifest.db"
        self.db = self.tmp / "chunks.db"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _file(self, row: dict, payload: bytes = b"pdf!") -> Path:
        path = self.root / row["symbol_at_time"] / row["bucket"] / f"{row['newsid']}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def test_known_at_comes_from_manifest_not_file_time(self):
        row = _row(dissem_ts="2020-01-02T15:04:05")
        path = self._file(row)
        os.utime(path, (2_000_000_000, 2_000_000_000))  # a 2033 file mtime
        con = self.h.open_store(self.db)
        result = self.h.process_row(con, row, self.root, "test",
                                    extractor=lambda _p: [DOC])
        doc = con.execute("SELECT known_at, known_at_src, pit_conf, needs_ocr "
                          "FROM doc WHERE doc_id=?", (result["doc_id"],)).fetchone()
        chunk = con.execute("SELECT known_at FROM chunk LIMIT 1").fetchone()
        con.close()
        self.assertEqual(result["known_at"], "2020-01-02T15:04:05")
        self.assertEqual(doc[0], "2020-01-02T15:04:05")
        self.assertEqual(doc[1], "bse_dissem")
        self.assertEqual(doc[2], 1.0)
        self.assertEqual(chunk[0], "2020-01-02T15:04:05")
        self.assertEqual(doc[3], 0)

    def test_duplicate_content_is_skipped_and_counted(self):
        sha = _sha("same bytes")
        first = _row(dissem_ts="2020-01-02T10:00:00", sha256=sha)
        second = _row(dissem_ts="2020-02-02T10:00:00", sha256=sha)
        for row in (first, second):
            self._file(row)
        canonical, duplicates = self.h.plan_rows([second, first])
        self.assertEqual([r["newsid"] for r in canonical], [first["newsid"]])
        self.assertEqual(len(duplicates), 1)
        con = self.h.open_store(self.db)
        result = self.h.process_row(con, canonical[0], self.root, "test",
                                    extractor=lambda _p: [DOC])
        self.h.finalize(con, [first, second], duplicates, None)
        outcomes = dict(con.execute("SELECT newsid, outcome FROM history_outcome"))
        counts = dict(con.execute("SELECT outcome, COUNT(*) FROM history_outcome "
                                  "GROUP BY outcome"))
        docs = con.execute("SELECT COUNT(*) FROM doc").fetchone()[0]
        chunks = con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
        dup_reason = con.execute("SELECT reason FROM history_outcome WHERE newsid=?",
                                 (second["newsid"],)).fetchone()[0]
        con.close()
        self.assertEqual(outcomes[first["newsid"]], "chunked")
        self.assertEqual(outcomes[second["newsid"]], "duplicate")
        self.assertEqual(docs, 1)
        self.assertEqual(chunks, result["chunks"])
        self.assertEqual(counts["duplicate"], 1)
        self.assertEqual(dup_reason, f"duplicate_of:{first['newsid']}")

    def test_resume_does_not_double_write(self):
        row = _row()
        self._file(row)
        con = self.h.open_store(self.db)
        first = self.h.process_row(con, row, self.root, "test", extractor=lambda _p: [DOC])
        before = (con.execute("SELECT COUNT(*) FROM doc").fetchone()[0],
                  con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0],
                  con.execute("SELECT COUNT(*) FROM history_outcome").fetchone()[0])
        second = self.h.process_row(con, row, self.root, "test", extractor=lambda _p: [DOC])
        after = (con.execute("SELECT COUNT(*) FROM doc").fetchone()[0],
                 con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0],
                 con.execute("SELECT COUNT(*) FROM history_outcome").fetchone()[0])
        con.close()
        self.assertEqual(first["doc_id"], second["doc_id"])
        self.assertEqual(before, after)
        self.assertEqual(after, (1, first["chunks"], 1))

    def test_scanned_pdf_is_grade_c_needs_ocr_without_chunks(self):
        row = _row()
        self._file(row)
        con = self.h.open_store(self.db)
        result = self.h.process_row(con, row, self.root, "test",
                                    extractor=lambda _p: ["", "  "])
        doc = con.execute("SELECT quality_grade, needs_ocr, char_count FROM doc").fetchone()
        chunks = con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
        con.close()
        self.assertEqual(result["outcome"], "needs_ocr")
        self.assertEqual(doc[0], "C")
        self.assertEqual(doc[1], 1)
        self.assertEqual(chunks, 0)

    def test_every_manifest_row_gets_exactly_one_outcome(self):
        ok = _row(dissem_ts="2020-01-02T10:00:00")
        ok2 = _row(dissem_ts="2020-03-02T10:00:00", sha256=ok["sha256"])
        skipped = _row(status="skipped", sha256=None, bytes=None)
        no_file = _row(status="no_file", sha256=None, bytes=None)
        error = _row(status="error", sha256=None, bytes=None)
        rows = [ok, ok2, skipped, no_file, error]
        _write_manifest(self.manifest, rows)
        self._file(ok)
        loaded = self.h.load_manifest(self.manifest)
        canonical, duplicates = self.h.plan_rows(loaded)
        con = self.h.open_store(self.db)
        self.h.process_row(con, canonical[0], self.root, "test", extractor=lambda _p: [DOC])
        self.h.finalize(con, loaded, duplicates, None)
        counts = self.h.outcome_counts(con)
        reasons = dict(con.execute("SELECT newsid, reason FROM history_outcome "
                                   "WHERE outcome='failed'"))
        con.close()
        self.assertEqual(len(loaded), 5)
        self.assertEqual(len(canonical), 1)
        self.assertEqual(counts["chunked"], 1)
        self.assertEqual(counts["duplicate"], 1)
        self.assertEqual(counts["failed"], 3)
        self.assertEqual(counts["total"], len(loaded))
        self.assertEqual(reasons[skipped["newsid"]], "skipped")
        self.assertEqual(reasons[no_file["newsid"]], "no_file")
        self.assertEqual(reasons[error["newsid"]], "error")

    def test_fiscal_period_rules(self):
        f = self.h.fiscal_period_for
        self.assertEqual(f("quarterly_results", "2019-05-03T10:00:00"), "Q4FY19")
        self.assertEqual(f("quarterly_results", "2019-08-03T10:00:00"), "Q1FY20")
        self.assertEqual(f("quarterly_results", "2020-01-15T10:00:00"), "Q3FY20")
        self.assertEqual(f("annual_report", "2019-07-15T10:00:00",
                           "Annual Report 2018-19"), "FY19")
        self.assertEqual(f("material_filing", "2024-03-31T10:00:00"), "FY24")

    def test_audio_link_bucket_is_an_announcement(self):
        # the bucket is the "link to audio recording" announcement, not a transcript
        self.assertEqual(self.h.doc_type_for("concall_audio_link"), "announcement")
        self.assertEqual(self.h.doc_type_for("concall_transcript"), "concall")

    def test_known_at_parse_never_uses_a_date_only_fallback(self):
        self.assertEqual(self.h.parse_known_at("2020-01-02 15:04:05.123"),
                         "2020-01-02T15:04:05")
        self.assertEqual(self.h.parse_known_at("2020-01-02"), "2020-01-02T23:59:59")
        self.assertEqual(self.h.parse_known_at(None), "")


if __name__ == "__main__":
    unittest.main()
