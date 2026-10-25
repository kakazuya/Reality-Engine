"""Task G0: raw files live under RAW_ROOT on D, and the C -> D migration is safe.

Temp dirs only: nothing here reads or writes the real raw folders or any database.
"""
import io
import json
import shutil
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest import mock

from reality_engine import config as cfg
import importlib
bse_client = importlib.import_module("reality_engine.ingestion.bse_client")
nse_client = importlib.import_module("reality_engine.ingestion.nse_client")
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

    # -- defect 2: the manifest merges by src across plans/runs -----------------
    def test_second_apply_keeps_the_manifest_entries(self):
        self._write(self.src / "bhavcopy" / "sec_bhavdata_full_011026.csv", "rows")
        self._run_apply()

        rows, _ = self._run_apply()   # nothing left in the source: an empty plan

        self.assertEqual(rows, [])
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual([Path(r["src"]).name for r in payload["files"]],
                         ["sec_bhavdata_full_011026.csv"])
        self.assertEqual(payload["folders"]["bhavcopy"]["files"], 1)

    def test_saving_a_later_plan_merges_the_earlier_manifest_rows(self):
        self._write(self.src / "bhavcopy" / "a.csv", "a")
        self._run_apply()
        self._write(self.src / "raw_market" / "b.csv", "b")

        rows = mig.plan(self.src, self.dest, self.pdfs)
        mig.save(self.manifest, rows, self.src, self.dest)   # a resume writes a partial plan

        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(sorted(Path(r["src"]).name for r in payload["files"]), ["a.csv", "b.csv"])
        self.assertEqual(payload["folders"]["bhavcopy"]["files"], 1)

    # -- defect 8: resume after a kill; locked copy -----------------------------
    def test_resume_after_a_kill_keeps_every_manifest_row(self):
        for name in ("a.csv", "b.csv", "c.csv"):
            self._write(self.src / "raw_market" / name, name)
        rows = mig.plan(self.src, self.dest, self.pdfs)

        mig.apply(rows[:1], self.manifest, self.src, self.dest)   # killed after one file
        rows2 = mig.plan(self.src, self.dest, self.pdfs)
        self.assertEqual(len(rows2), 2)
        mig.apply(rows2, self.manifest, self.src, self.dest)

        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(sorted(Path(r["src"]).name for r in payload["files"]),
                         ["a.csv", "b.csv", "c.csv"])

    def test_locked_copy_keeps_the_c_copy(self):
        src_file = self._write(self.src / "raw_market" / "a.csv", "x")
        rows = mig.plan(self.src, self.dest, self.pdfs)

        with mock.patch.object(mig.shutil, "copy2", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                mig.apply(rows, self.manifest, self.src, self.dest)

        self.assertTrue(src_file.exists())
        self.assertFalse((self.dest / "raw_market" / "a.csv").exists())

    # -- defect 1: re-verify the destination right before unlink ----------------
    def test_dest_removed_after_plan_is_copied_again_before_unlink(self):
        src_file = self._write(self.src / "raw_market" / "a.csv", "same")
        self._write(self.dest / "raw_market" / "a.csv", "same")
        rows = mig.plan(self.src, self.dest, self.pdfs)
        self.assertEqual(rows[0]["status"], "already_on_d")
        (self.dest / "raw_market" / "a.csv").unlink()   # vanished between plan and apply

        done = mig.apply(rows, self.manifest, self.src, self.dest)

        self.assertFalse(src_file.exists())
        self.assertEqual((self.dest / "raw_market" / "a.csv").read_text(encoding="utf-8"), "same")
        self.assertEqual(done["moved"], 1)

    def test_dest_changed_after_plan_is_copied_again_before_unlink(self):
        src_file = self._write(self.src / "raw_market" / "a.csv", "same")
        self._write(self.dest / "raw_market" / "a.csv", "same")
        rows = mig.plan(self.src, self.dest, self.pdfs)
        self.assertEqual(rows[0]["status"], "already_on_d")
        (self.dest / "raw_market" / "a.csv").write_text("tampered", encoding="utf-8")

        mig.apply(rows, self.manifest, self.src, self.dest)

        self.assertFalse(src_file.exists())
        self.assertEqual((self.dest / "raw_market" / "a.csv").read_text(encoding="utf-8"), "same")

    # -- defect 3: refuse dest==src / nested dest / empty source ----------------
    def _main(self, *args):
        with mock.patch("sys.stderr", new=io.StringIO()), mock.patch("sys.stdout", new=io.StringIO()):
            return mig.main(list(args))

    def test_main_refuses_dest_equal_to_source(self):
        src_file = self._write(self.src / "raw_market" / "a.csv", "x")
        rc = self._main("--source", str(self.src), "--dest", str(self.src),
                        "--pdfs-dest", str(self.root / "pdfs"))
        self.assertEqual(rc, 2)
        self.assertTrue(src_file.exists())

    def test_main_refuses_dest_nested_in_source(self):
        src_file = self._write(self.src / "raw_market" / "a.csv", "x")
        rc = self._main("--source", str(self.src), "--dest", str(self.src / "new"),
                        "--pdfs-dest", str(self.root / "pdfs"))
        self.assertEqual(rc, 2)
        self.assertTrue(src_file.exists())

    def test_main_refuses_pdfs_dest_that_is_the_source_pdfs(self):
        src_file = self._write(self.src / "pdfs" / "AAA" / "ar.pdf", "x")
        rc = self._main("--source", str(self.src), "--dest", str(self.dest),
                        "--pdfs-dest", str(self.src / "pdfs"))
        self.assertEqual(rc, 2)
        self.assertTrue(src_file.exists())

    def test_main_refuses_an_empty_source(self):
        self.assertEqual(self._main("--source", str(self.src / "missing"),
                                    "--dest", str(self.dest)), 2)
        self.src.mkdir()
        self.assertEqual(self._main("--source", str(self.src), "--dest", str(self.dest)), 2)

    # -- defect 9: fsync the destination before unlinking the source ------------
    def test_destination_is_fsynced_while_the_c_copy_still_exists(self):
        src_file = self._write(self.src / "raw_market" / "a.csv", "bytes")
        rows = mig.plan(self.src, self.dest, self.pdfs)
        source_alive = []

        def _fake_fsync(fd):
            source_alive.append(src_file.exists())

        with mock.patch.object(mig.os, "fsync", side_effect=_fake_fsync):
            mig.apply(rows, self.manifest, self.src, self.dest)

        self.assertTrue(source_alive)
        self.assertTrue(all(source_alive))
        self.assertFalse(src_file.exists())


class StoredPathTest(unittest.TestCase):
    """Defect 5: DB rows still store the old C paths; reads must resolve them onto D."""

    def setUp(self):
        self.root = _scratch()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.raw = self.root / "d_raw"
        self.pdfs = self.root / "d_pdfs"
        for name, value in (("RAW_ROOT", self.raw), ("PDFS_DIR", self.pdfs),
                            ("BHAVCOPY_DIR", self.raw / "bhavcopy"),
                            ("MACRO_PDFS_DIR", self.raw / "macro_pdfs")):
            patcher = mock.patch.object(cfg, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write(self, path: Path, payload: str = "x") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path

    def test_old_c_pdf_path_resolves_to_the_d_pile(self):
        d_file = self._write(self.pdfs / "X" / "AR" / "a.pdf")
        stored = r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pdfs\X\AR\a.pdf"

        self.assertEqual(cfg.resolve_stored_path(stored), d_file)
        self.assertEqual(cfg.resolve_stored_path(stored.replace("\\", "/")), d_file)

    def test_an_existing_stored_path_is_returned_unchanged(self):
        c_file = self._write(self.root / "c" / "reality_engine" / "data" / "pdfs" / "X" / "AR" / "b.pdf")

        self.assertEqual(cfg.resolve_stored_path(c_file), c_file)
        self.assertEqual(cfg.resolve_stored_path(str(c_file)), c_file)

    def test_every_migrated_folder_maps_to_its_new_root(self):
        roots = cfg.stored_raw_roots()
        for folder in ("pdfs", "decks", "raw_market", "bhavcopy", "macro_pdfs",
                       "ar_queue", "tax_sources", "index_constituents"):
            d_file = self._write(roots[folder] / "f.bin")
            stored = rf"C:\old\reality_engine\data\{folder}\f.bin"
            self.assertEqual(cfg.resolve_stored_path(stored), d_file, folder)

    def test_unknown_stored_paths_are_returned_as_is(self):
        stored = Path(self.root / "somewhere" / "else" / "x.bin")
        self.assertEqual(cfg.resolve_stored_path(stored), stored)
        self.assertEqual(cfg.resolve_stored_path(""), Path(""))


class BhavcopyWriterDirTest(unittest.TestCase):
    """Defect 4: the raw dirs are created lazily, so every writer must mkdir first."""

    def setUp(self):
        self.root = _scratch()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_bhavcopy_writers_create_their_raw_folder(self):
        bhav_csv = (
            "SYMBOL,SERIES,DATE1,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,"
            "CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER\n"
            "AAA,EQ,01-10-2026,1,1,1,1,1,1,1,100,1,10,50,50.0\n"
        )
        index_csv = "INDEX,DATE1,OPEN\nNIFTY 50,01-10-2026,100\n"
        client = nse_client.NSEClient()
        client.session = mock.Mock()
        client.session.get.return_value = mock.Mock(status_code=200, text=bhav_csv)

        nse_dir = self.root / "nse_bhavcopy"   # deliberately absent
        with mock.patch.object(nse_client, "BHAVCOPY_DIR", nse_dir):
            self.assertIsNotNone(client.fetch_bhavcopy(datetime(2026, 10, 1)))
        self.assertTrue((nse_dir / "sec_bhavdata_full_01102026.csv").is_file())

        index_dir = self.root / "nse_index_bhavcopy"   # deliberately absent
        client.session.get.return_value = mock.Mock(status_code=200, text=index_csv)
        with mock.patch.object(nse_client, "BHAVCOPY_DIR", index_dir):
            self.assertIsNotNone(client.fetch_index_bhavcopy(datetime(2026, 10, 1)))
        self.assertTrue((index_dir / "ind_close_all_01102026.csv").is_file())

        bse_dir = self.root / "bse_bhavcopy"   # deliberately absent
        bse_text = "TradDt,ISIN,SecurityID\n2026-10-01,INE000000000,AAA\n"
        with mock.patch.object(bse_client, "BHAVCOPY_DIR", bse_dir), \
                mock.patch.object(bse_client.BSEClient, "_warmup_session", return_value=None), \
                mock.patch.object(bse_client, "bse_csv", return_value=bse_text):
            self.assertIsNotNone(bse_client.BSEClient().fetch_bhavcopy(datetime(2026, 10, 1)))
        self.assertTrue((bse_dir / "BhavCopy_BSE_20261001.csv").is_file())


if __name__ == "__main__":
    unittest.main()
