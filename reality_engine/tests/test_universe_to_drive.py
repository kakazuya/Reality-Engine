"""T-241: universe_to_drive archives a finished company's stores and moves exactly its raw files to Drive.

A fake ``rclone`` replaces ``subprocess.run`` for rclone calls: it holds files under a temp "Drive" folder and
answers ``md5sum``/``lsjson`` from it. No test touches the real Drive, the real raw folders or the real stores.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from reality_engine.scripts import raw_to_drive as r
from reality_engine.scripts import universe_to_drive as u


class FakeRclone:
    """Minimal rclone: copy/copyto into ``drive``, md5sum and lsjson read back from it."""

    def __init__(self, drive: Path):
        self.drive = drive
        self.calls: list[list[str]] = []
        self.fail_upload = False

    def path_of(self, remote: str) -> Path:
        assert remote.startswith("gdrive:"), remote
        return self.drive.joinpath(*remote[len("gdrive:"):].lstrip("/\\").split("/"))

    @staticmethod
    def md5(path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()

    def __call__(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(list(cmd))
        args, out = cmd[1:], ""
        if args[0] == "md5sum":
            target = self.path_of(args[1])
            if not target.is_file():
                return subprocess.CompletedProcess(cmd, 3, "", "not found")
            out = f"{self.md5(target)}  {target.name}\n"
        elif args[0] == "copyto":
            target = self.path_of(args[2])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(Path(args[1]).read_bytes())
        elif args[0] == "copy":
            if self.fail_upload:
                return subprocess.CompletedProcess(cmd, 1, "", "upload failed")
            src, dest = Path(args[1]), self.path_of(args[2])
            listfile = Path(args[args.index("--files-from") + 1])
            for rel in listfile.read_text(encoding="utf-8").split():
                parts = rel.replace("\\", "/").split("/")
                target = dest.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(src.joinpath(*parts).read_bytes())
        elif args[0] == "lsjson":
            root = self.path_of(args[-1])
            entries = []
            if root.is_dir():
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        entries.append({"Path": path.relative_to(root).as_posix(), "Size": path.stat().st_size,
                                        "Hashes": {"md5": self.md5(path)}})
            out = json.dumps(entries)
            if kwargs.get("stdout") is not None:
                kwargs["stdout"].write(out)
                out = ""
        else:
            return subprocess.CompletedProcess(cmd, 2, "", f"unsupported: {args[0]}")
        return subprocess.CompletedProcess(cmd, 0, out, "")


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    drive = tmp_path / "drive"
    drive.mkdir()
    runner = FakeRclone(drive)
    real_run = subprocess.run

    def run(cmd, **kwargs):
        if cmd and cmd[0] == "rclone":
            return runner(cmd, **kwargs)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    return runner


def make_db(path: Path, wal: bool = False) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x TEXT)")
    con.execute("INSERT INTO t VALUES ('stored')")
    con.commit()
    if not wal:
        con.close()
    return con       # an open writer leaves the row in the -wal file, the case the backup API must survive


def build(tmp_path: Path):
    root = tmp_path / "universe"
    (root / "c1").mkdir(parents=True)
    (root / "c1" / "c1_measure.json").write_text(json.dumps({"company": "c1", "symbol": "SYM"}), encoding="utf-8")
    writer = make_db(root / "c1" / "c1.db", wal=True)
    make_db(root / "c1" / "pages.db")
    (root / "universe_fy27.csv").write_text("isin,symbol,bse_code\nINE000000001,SYM,500001\n", encoding="utf-8")
    raw_root = tmp_path / "raw"
    pdf = raw_root / "pilot60_history" / "SYM" / "annual_report" / "x.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"raw pdf bytes")
    manifest = tmp_path / "history_manifest.db"
    con = sqlite3.connect(manifest)
    con.execute("CREATE TABLE docs (isin TEXT, symbol_at_time TEXT, local_path TEXT, bytes INTEGER, "
                "sha256 TEXT, status TEXT)")
    con.execute("INSERT INTO docs VALUES (?,?,?,?,?,?)",
                ("INE000000001", "SYM", str(pdf), pdf.stat().st_size, "", "ok"))
    con.commit()
    con.close()
    return root, raw_root, manifest, pdf, writer


def args(root: Path, raw_root: Path, manifest: Path, *extra: str) -> list[str]:
    return ["--root", str(root), "--manifest-db", str(manifest), "--raw-root", str(raw_root), "--once", *extra]


def test_once_archives_stores_and_deletes_verified_raws(tmp_path, fake):
    root, raw_root, manifest, pdf, writer = build(tmp_path)
    assert u.main(args(root, raw_root, manifest, "--delete")) == 0
    archive = fake.drive / "InfoDiffusion_archive"
    store = archive / "universe_fy27" / "stores" / "c1_SYM" / "c1.db"
    assert store.is_file() and (store.parent / "pages.db").is_file()
    con = sqlite3.connect(store)
    assert con.execute("SELECT x FROM t").fetchone() == ("stored",)
    con.close()
    moved = archive / "msi_raw" / "raw" / "pilot60_history" / "SYM" / "annual_report" / "x.pdf"
    assert moved.read_bytes() == b"raw pdf bytes"
    assert not pdf.exists()
    state = sqlite3.connect(root / "to_drive.db")
    assert state.execute("SELECT raw_files, raw_on_drive, raw_deleted_at IS NOT NULL FROM company "
                         "WHERE name='c1'").fetchone() == (1, 1, 1)
    state.close()
    writer.close()


def test_without_delete_keeps_the_raw_file(tmp_path, fake):
    root, raw_root, manifest, pdf, writer = build(tmp_path)
    assert u.main(args(root, raw_root, manifest)) == 0
    assert pdf.exists()
    state = sqlite3.connect(root / "to_drive.db")
    assert state.execute("SELECT raw_deleted_at FROM company WHERE name='c1'").fetchone() == (None,)
    state.close()
    assert (fake.drive / "InfoDiffusion_archive/msi_raw/raw/pilot60_history/SYM/annual_report/x.pdf").is_file()
    writer.close()


def test_failed_raw_upload_keeps_the_file_and_records_nothing(tmp_path, fake):
    root, raw_root, manifest, pdf, writer = build(tmp_path)
    fake.fail_upload = True
    assert u.main(args(root, raw_root, manifest, "--delete")) == 0
    assert pdf.exists()
    state = sqlite3.connect(root / "to_drive.db")
    assert state.execute("SELECT COUNT(*) FROM company").fetchone() == (0,)
    state.close()
    writer.close()


def test_dry_run_lists_and_moves_nothing(tmp_path, fake, capsys):
    root, raw_root, manifest, pdf, writer = build(tmp_path)
    assert u.main(args(root, raw_root, manifest, "--delete", "--dry-run")) == 0
    out = capsys.readouterr().out
    assert "DRY RUN c1 SYM" in out and "1 companies" in out
    assert pdf.exists()
    assert not (fake.drive / "InfoDiffusion_archive").exists()
    assert not (root / "to_drive.db").exists()
    assert not fake.calls
    writer.close()


def test_files_from_scopes_hash_upload_and_delete(tmp_path, fake):
    raw_root = tmp_path / "rawroot"
    raw_root.mkdir()
    a, b = raw_root / "a.pdf", raw_root / "b.pdf"
    a.write_bytes(b"aa")
    b.write_bytes(b"bb")
    listing = tmp_path / "drive_index"
    listing.mkdir()
    con = r.open_manifest(str(tmp_path / "raw_to_drive.db"))
    r.step_hash(con, [str(raw_root)])
    r.step_compare(con, listing)
    top = fake.drive / "InfoDiffusion_archive" / "msi_raw" / "rawroot"
    r.step_upload(con, listing, [str(raw_root)], "0", files=[str(a)])
    assert (top / "a.pdf").is_file() and not (top / "b.pdf").exists()
    r.step_upload(con, listing, [str(raw_root)], "0", files=[str(b)])
    assert (top / "b.pdf").is_file()
    r.step_delete(con, really=True, roots=[str(raw_root)], files=[str(a)])
    assert not a.exists() and b.exists()
