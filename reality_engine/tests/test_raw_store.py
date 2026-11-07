"""T-102: a raw reader gets a Drive-only file from the manifest, uses it, and leaves nothing behind.

A fake runner stands in for ``rclone copy --files-from``: it writes the requested files into the
destination the way rclone does.  No test touches the real Drive, the real raw folders or the real
manifest.
"""
import hashlib
import sqlite3
import tempfile
from pathlib import Path

import pytest

from reality_engine import raw_store

RAW = "raw"
PDFS = "pdfs"


def _manifest(path: Path, rows: list[tuple]) -> Path:
    """rows: (path, root, rel, md5, drive_path) — ``drive_path`` None is a kept-local row."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE local_file (path TEXT PRIMARY KEY, root TEXT, rel TEXT, size INTEGER, "
                "mtime REAL, md5 TEXT, status TEXT, drive_path TEXT, deleted_at TEXT)")
    con.executemany(
        "INSERT INTO local_file (path, root, rel, md5, status, drive_path) VALUES (?,?,?,?,'on_drive',?)",
        [(p, root, rel, md5, drive) for p, root, rel, md5, drive in rows])
    con.commit()
    con.close()
    return path


def _remote_file(remote: Path, drive_path: str, data: bytes) -> None:
    target = remote / drive_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _fake_runner(calls: list[list[str]], remote: Path):
    def run(cmd: list[str]) -> None:
        calls.append(list(cmd))
        assert cmd[0] == "copy"
        source, dest = cmd[1], Path(cmd[2])
        top = "arch17" if source.startswith("gdrive_ro:") else source.rsplit("/", 1)[-1]
        listfile = Path(cmd[cmd.index("--files-from") + 1])
        for rel in [line for line in listfile.read_text(encoding="utf-8").splitlines() if line]:
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((remote / top / rel).read_bytes())
    return run


def _store(tmp_path: Path, rows: list[tuple], remote: Path | None = None,
           calls: list[list[str]] | None = None) -> raw_store.RawStore:
    manifest = _manifest(tmp_path / "manifest.db", rows)
    runner = _fake_runner(calls, remote) if remote is not None and calls is not None else None
    return raw_store.RawStore(manifest=manifest, roots={RAW: tmp_path / "raw", PDFS: tmp_path / "pdfs"},
                              runner=runner)


def _fetched_dirs() -> set[Path]:
    return set(Path(tempfile.gettempdir()).glob("raw_fetch_*"))


@pytest.fixture(autouse=True)
def _fetch_enabled(monkeypatch):
    monkeypatch.delenv("REALITY_RAW_FETCH", raising=False)


def test_walk_merges_local_and_manifest_and_skips_kept_rows(tmp_path):
    local = tmp_path / "raw" / "annual_report" / "KEC" / "local.pdf"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"local")
    kept = tmp_path / "raw" / "user_research" / "note.pdf"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"keep me")
    only_drive = b"drive only"
    store = _store(tmp_path, [
        ("D:/RealityEngine/raw\\annual_report\\KEC\\drive-only.pdf", RAW, "annual_report/KEC/drive-only.pdf",
         hashlib.md5(only_drive).hexdigest(), "pdfs/KEC/ANNUAL_REPORT/20261010_x.pdf"),
        ("D:/RealityEngine/raw\\user_research\\gone.pdf", RAW, "user_research/gone.pdf",
         hashlib.md5(b"gone").hexdigest(), None),
    ])

    walked = {p.name for p in store.walk(tmp_path / "raw")}
    assert walked == {"local.pdf", "drive-only.pdf", "note.pdf"}      # kept row gone.pdf: neither local nor Drive
    assert {p.name for p in store.walk(tmp_path / "raw" / "annual_report")} == {"local.pdf", "drive-only.pdf"}
    assert {p.name for p in store.glob(tmp_path / "raw", "*.pdf")} == {"local.pdf", "drive-only.pdf", "note.pdf"}
    assert store.exists(tmp_path / "raw" / "annual_report" / "KEC" / "drive-only.pdf")
    assert not store.exists(tmp_path / "raw" / "user_research" / "gone.pdf")


def test_named_pattern_matches_the_relative_path(tmp_path):
    store = _store(tmp_path, [
        ("p", RAW, "nse_announcements/2026-10/KEC.jsonl", None, "pdfs/KEC/nse/KEC.jsonl"),
    ])
    assert [p.name for p in store.glob(tmp_path / "raw" / "nse_announcements", "*/KEC.jsonl")] == ["KEC.jsonl"]
    assert [p.name for p in store.glob(tmp_path / "raw" / "nse_announcements", "*/OTHER.jsonl")] == []


def test_local_file_is_read_where_it_is(tmp_path):
    local = tmp_path / "raw" / "decks" / "KEC" / "deck.pdf"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"deck")
    store = _store(tmp_path, [("p", RAW, "decks/KEC/deck.pdf", None, "pdfs/KEC/deck.pdf")],
                   remote=tmp_path / "remote", calls=[])

    with store.local(local) as got:
        assert got == local and got.read_bytes() == b"deck"
    assert store._fetched == {} and not list(tmp_path.glob("raw_fetch_*"))


def test_drive_only_file_is_fetched_once_and_deleted(tmp_path):
    payload = b"%PDF-1.7 drive copy"
    remote = tmp_path / "remote"
    _remote_file(remote, "pdfs/KEC/ANNUAL_REPORT/20261010_x.pdf", payload)
    calls: list[list[str]] = []
    store = _store(tmp_path, [(
        "D:/RealityEngine/raw\\annual_report\\KEC\\x.pdf", RAW, "annual_report/KEC/x.pdf",
        hashlib.md5(payload).hexdigest(), "pdfs/KEC/ANNUAL_REPORT/20261010_x.pdf")],
        remote=remote, calls=calls)
    target = tmp_path / "raw" / "annual_report" / "KEC" / "x.pdf"

    before = _fetched_dirs()
    with store.local(target) as got:
        assert got != target and got.read_bytes() == payload
        fetched = got
    assert not fetched.exists()
    assert len(calls) == 1 and calls[0][0] == "copy"
    assert Path(calls[0][calls[0].index("--files-from") + 1]).name.startswith("files_pdfs")
    assert not (_fetched_dirs() - before)


def test_md5_mismatch_raises_and_cleans_the_temp_folder(tmp_path):
    remote = tmp_path / "remote"
    _remote_file(remote, "pdfs/KEC/ANNUAL_REPORT/x.pdf", b"tampered")
    store = _store(tmp_path, [(
        "p", RAW, "annual_report/KEC/x.pdf", hashlib.md5(b"original").hexdigest(),
        "pdfs/KEC/ANNUAL_REPORT/x.pdf")], remote=remote, calls=[])

    before = _fetched_dirs()
    with pytest.raises(ValueError, match="md5 mismatch"):
        with store.local(tmp_path / "raw" / "annual_report" / "KEC" / "x.pdf"):
            pass
    assert not (_fetched_dirs() - before)


def test_fetch_off_never_calls_rclone(tmp_path, monkeypatch):
    monkeypatch.setenv("REALITY_RAW_FETCH", "0")
    remote = tmp_path / "remote"
    _remote_file(remote, "pdfs/KEC/x.pdf", b"x")
    calls: list[list[str]] = []
    store = _store(tmp_path, [("px", RAW, "annual_report/KEC/x.pdf", hashlib.md5(b"x").hexdigest(),
                               "pdfs/KEC/x.pdf")], remote=remote, calls=calls)
    target = tmp_path / "raw" / "annual_report" / "KEC" / "x.pdf"

    assert not store.exists(target)
    with pytest.raises(FileNotFoundError):
        with store.local(target):
            pass
    with store.prefetch([target]):
        pass
    assert calls == []


def test_prefetch_is_one_copy_per_top_and_local_reads_the_fetched_copy(tmp_path):
    first = b"first"
    second = b"second"
    old = b"arch17"
    remote = tmp_path / "remote"
    _remote_file(remote, "pdfs/KEC/ANNUAL_REPORT/a.pdf", first)
    _remote_file(remote, "pdfs/KEC/ANNUAL_REPORT/b.pdf", second)
    _remote_file(remote, "arch17/Old/c.pdf", old)
    calls: list[list[str]] = []
    store = _store(tmp_path, [
        ("p1", RAW, "annual_report/KEC/a.pdf", hashlib.md5(first).hexdigest(), "pdfs/KEC/ANNUAL_REPORT/a.pdf"),
        ("p2", RAW, "annual_report/KEC/b.pdf", hashlib.md5(second).hexdigest(), "pdfs/KEC/ANNUAL_REPORT/b.pdf"),
        ("p3", RAW, "old_upload/c.pdf", hashlib.md5(old).hexdigest(), "arch17/Old/c.pdf"),
    ], remote=remote, calls=calls)
    targets = [tmp_path / "raw" / "annual_report" / "KEC" / "a.pdf",
               tmp_path / "raw" / "annual_report" / "KEC" / "b.pdf",
               tmp_path / "raw" / "old_upload" / "c.pdf"]

    with store.prefetch(targets):
        assert len(calls) == 2                                     # one copy for pdfs, one for arch17
        arch17 = [c for c in calls if c[1].startswith("gdrive_ro:")]
        assert arch17 and any(a.startswith("--drive-root-folder-id=") for a in arch17[0])
        for target, want in zip(targets, (first, second, old)):
            with store.local(target) as got:
                assert got.read_bytes() == want
        fetched = [store._fetched[store._key(target)] for target in targets]
        assert len(calls) == 2                                     # no per-file download inside prefetch
    assert not any(path.exists() for path in fetched)


def test_missing_everywhere_raises_like_a_missing_file(tmp_path):
    store = _store(tmp_path, [])
    with pytest.raises(FileNotFoundError):
        with store.local(tmp_path / "raw" / "nowhere.pdf"):
            pass
