"""Task G0: raw files live under RAW_ROOT on D, and the C -> D migration is safe.

Temp dirs only: nothing here reads or writes the real raw folders or any database.
"""
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from reality_engine import config as cfg
from reality_engine.scripts import migrate_raw_to_d as mig

_IMPORT_RAW_ROOT = cfg.RAW_ROOT  # resolved once at import, before any patch


def _scratch() -> Path:
    """A writable temp dir. tempfile.mkdtemp() leaves a 0o700 ACL that the DSH sandbox
    cannot write into, so the directory is made here and removed by the caller."""
    d = Path(tempfile.gettempdir()) / f"g0_raw_root_{uuid.uuid4().hex}"
    d.mkdir()
    return d


class RawDirTest(unittest.TestCase):
    def setUp(self):
        self.root = _scratch()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        patcher = mock.patch.object(cfg, "RAW_ROOT", self.root / "raw")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_raw_dir_creates_the_folder_under_raw_root(self):
        d = cfg.raw_dir("bhavcopy")
        self.assertEqual(d, self.root / "raw" / "bhavcopy")
        self.assertTrue(d.is_dir())
        self.assertTrue(cfg.raw_dir("raw_market").is_dir())

    def test_raw_constants_do_not_point_into_the_c_data_dir(self):
        self.assertEqual(cfg.BHAVCOPY_DIR.parent, _IMPORT_RAW_ROOT)
        self.assertEqual(cfg.MACRO_PDFS_DIR.parent, _IMPORT_RAW_ROOT)
        self.assertFalse(str(cfg.PDFS_DIR).startswith(str(cfg.DATA_DIR)))
        self.assertIn(cfg.PDFS_DIR.parent, (cfg.PDFS_LEGACY_DIR.parent, _IMPORT_RAW_ROOT))


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.root = _scratch()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.src = self.root / "c_data"
        self.dest = self.root / "d_raw"
        self.pdfs = self.dest / "pdfs"  # reused pdf pile on D
        self.manifest = self.dest / "_migration" / "2026-10-25.json"

    def _write(self, path: Path, payload: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path

    def _run_apply(self):
        rows = mig.plan(self.src, self.dest, self.pdfs)
        return rows, mig.apply(rows, self.manifest, self.src, self.dest)

    def test_dry_run_summarises_without_copying_or_deleting(self):
        self._write(self.src / "raw_market" / "amfi_nav" / "2026-10.txt.gz", "raw")
        self._write(self.src / "pdfs" / "AAA" / "ANNUAL_REPORT" / "ar.pdf", "pdf-bytes")

        summary = mig.summarise(mig.plan(self.src, self.dest, self.pdfs))

        self.assertEqual(summary["raw_market"], {"files": 1, "bytes": 3, "already_on_d": 0,
                                                 "conflict": 0, "to_copy": 1, "to_copy_bytes": 3})
        self.assertEqual(summary["pdfs"]["files"], 1)
        self.assertFalse(self.dest.exists())
        self.assertTrue((self.src / "raw_market" / "amfi_nav" / "2026-10.txt.gz").exists())
        self.assertFalse(self.manifest.exists())

    def test_apply_copies_verifies_deletes_and_writes_the_manifest(self):
        src_file = self._write(self.src / "raw_market" / "nse_pr" / "PR011026.zip", "zip-bytes")
        self._write(self.src / "pdfs" / "AAA" / "ANNUAL_REPORT" / "ar.pdf", "pdf-bytes")

        rows, done = self._run_apply()

        self.assertEqual(done["moved"], 2)
        self.assertFalse(src_file.exists())
        moved = self.dest / "raw_market" / "nse_pr" / "PR011026.zip"
        self.assertEqual(moved.read_text(encoding="utf-8"), "zip-bytes")
        recorded = next(r for r in rows if r["dest"].endswith("PR011026.zip"))
        self.assertEqual((recorded["status"], recorded["sha256"]), ("moved", mig.sha256(moved)))
        self.assertTrue((self.pdfs / "AAA" / "ANNUAL_REPORT" / "ar.pdf").exists())  # reused pile
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["folders"]["raw_market"]["files"], 1)
        self.assertEqual({r["status"] for r in payload["files"]}, {"moved"})

    def test_apply_unlinks_a_c_file_already_on_d_without_recopying(self):
        self._write(self.dest / "raw_market" / "a.csv", "same")
        src_file = self._write(self.src / "raw_market" / "a.csv", "same")

        rows, done = self._run_apply()

        self.assertEqual((done["already_on_d"], done["moved"]), (1, 0))
        self.assertEqual(rows[0]["status"], "already_on_d")
        self.assertFalse(src_file.exists())
        self.assertEqual((self.dest / "raw_market" / "a.csv").read_text(encoding="utf-8"), "same")

    def test_apply_keeps_the_c_copy_when_the_dest_differs(self):
        self._write(self.dest / "raw_market" / "a.csv", "old")
        src_file = self._write(self.src / "raw_market" / "a.csv", "new")

        rows, done = self._run_apply()

        self.assertEqual(done["conflict"], 1)
        self.assertEqual(rows[0]["reason"], "sha256")
        self.assertTrue(src_file.exists())
        self.assertEqual((self.dest / "raw_market" / "a.csv").read_text(encoding="utf-8"), "old")

    def test_pdf_already_on_d_under_another_name_is_reused_not_recopied(self):
        self._write(self.pdfs / "OLD" / "ANNUAL_REPORT" / "old-name.pdf", "same-pdf")
        src_file = self._write(self.src / "pdfs" / "AAA" / "ANNUAL_REPORT" / "new-name.pdf", "same-pdf")

        summary = mig.summarise(mig.plan(self.src, self.dest, self.pdfs))
        self.assertEqual((summary["pdfs"]["already_on_d"], summary["pdfs"]["to_copy"]), (1, 0))

        rows, done = self._run_apply()

        self.assertEqual((done["already_on_d"], done["moved"]), (1, 0))
        self.assertFalse(src_file.exists())
        self.assertEqual((self.pdfs / "AAA" / "ANNUAL_REPORT" / "new-name.pdf").read_text(encoding="utf-8"),
                         "same-pdf")

    def test_second_apply_is_a_no_op_and_empty_folders_are_pruned(self):
        self._write(self.src / "bhavcopy" / "sec_bhavdata_full_011026.csv", "rows")
        self._run_apply()

        rows, done = self._run_apply()

        self.assertEqual(rows, [])
        self.assertEqual(done["moved"], 0)
        self.assertFalse((self.src / "bhavcopy").exists())


if __name__ == "__main__":
    unittest.main()
