"""T-102: a raw reader gets a Drive-only file from the manifest, uses it, and leaves nothing behind.

A fake runner stands in for ``rclone copy --files-from``: it writes the requested files into the
destination the way rclone does.  No test touches the real Drive, the real raw folders or the real
manifest.  ``shared_cache`` (T-242) is the thread-safe variant a bulk read uses: one download per
file for every thread, capped on disk, deleted on exit.
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


def test_lazy_manifest_load_is_thread_safe(tmp_path, monkeypatch):
    """T-220 review: a lookup on a second thread during the first load must wait for the full index."""
    import threading
    import time

    from reality_engine import raw_store as rs

    store = rs.RawStore(manifest=tmp_path / "none.db", roots={"raw": tmp_path / "raw"})
    started = threading.Event()

    def slow_load(self=store):
        started.set()
        time.sleep(0.3)
        self._rows_data[("raw", "a/b.pdf")] = ("top/a/b.pdf", None, "a/b.pdf")

    monkeypatch.setattr(store, "_load", slow_load)
    first = threading.Thread(target=lambda: store._rows)
    first.start()
    started.wait(2)
    assert ("raw", "a/b.pdf") in store._rows          # blocks until the first load has finished
    first.join()


def test_lazy_manifest_load_retries_after_error(tmp_path, monkeypatch):
    from reality_engine import raw_store as rs

    store = rs.RawStore(manifest=tmp_path / "none.db", roots={"raw": tmp_path / "raw"})
    calls = []

    def failing():
        calls.append(1)
        raise OSError("drive index busy")

    monkeypatch.setattr(store, "_load", failing)
    for _ in range(2):
        try:
            store._rows
        except OSError:
            pass
    assert len(calls) == 2


def test_keep_fetches_on_first_use_once_and_cleans_up(tmp_path):
    from reality_engine import raw_store as rs

    calls = []

    def runner(cmd):
        calls.append(cmd)
        dest = Path(cmd[2])
        listing = Path(cmd[cmd.index("--files-from") + 1]).read_text(encoding="utf-8").split()
        for rel in listing:
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / rel).write_bytes(b"%PDF-1.4")

    store = rs.RawStore(manifest=tmp_path / "none.db", roots={"raw": tmp_path / "raw"}, runner=runner)
    store._loaded = True
    store._rows_data[("raw", "a/b.pdf")] = ("top/a/b.pdf", None, "a/b.pdf")
    target = tmp_path / "raw" / "a" / "b.pdf"
    with store.keep():
        assert not calls                                  # nothing fetched until asked
        with store.local(target) as first:
            kept = first
        with store.local(target) as second:
            assert second == kept and second.is_file()
        assert len(calls) == 1
    assert not kept.exists()                              # deleted on exit
    assert store._keep_dir is None


def test_busy_manifest_raises_then_loads(tmp_path, monkeypatch):
    """T-241: a locked manifest raises (never loads as empty), the failure is remembered, and rows load once free."""
    import sqlite3 as _sq

    from reality_engine import raw_store as rs
    m = tmp_path / "m.db"
    con = _sq.connect(m)
    con.execute("CREATE TABLE local_file (path TEXT PRIMARY KEY, root TEXT, rel TEXT, size INTEGER, mtime REAL, "
                "md5 TEXT, status TEXT, drive_path TEXT, deleted_at TEXT)")
    con.execute("INSERT INTO local_file VALUES ('x','raw','a/b.pdf',1,0,'d41d','on_drive','msi_raw/raw/a/b.pdf',NULL)")
    con.commit()
    monkeypatch.setattr(rs, "LOAD_TIMEOUT_S", 0.1)
    monkeypatch.setattr(rs.time, "sleep", lambda s: None)
    con.execute("BEGIN EXCLUSIVE")
    store = rs.RawStore(roots={"raw": tmp_path / "raw"}, manifest=m)
    import pytest as _pt
    with _pt.raises(RuntimeError):
        store.drive_path(tmp_path / "raw" / "a" / "b.pdf")
    with _pt.raises(RuntimeError, match="retry later"):          # remembered: no second wait
        store.drive_path(tmp_path / "raw" / "a" / "b.pdf")
    con.rollback()
    con.close()
    monkeypatch.setattr(rs, "LOAD_BACKOFF_S", 0)
    store._fail = None
    assert store.drive_path(tmp_path / "raw" / "a" / "b.pdf") == "msi_raw/raw/a/b.pdf"


def test_shared_cache_fetches_one_drive_pdf_once_for_eight_threads(tmp_path):
    """T-242: 8 reader threads x 5 pages of one Drive-only document = exactly one rclone fetch."""
    import threading

    payload = b"%PDF-1.7 one deck read by 30 workers"
    remote = tmp_path / "remote"
    _remote_file(remote, "pdfs/KEC/DECK/d.pdf", payload)
    calls: list[list[str]] = []
    store = _store(tmp_path, [(
        "D:/RealityEngine/raw\\decks/KEC/d.pdf", RAW, "decks/KEC/d.pdf",
        hashlib.md5(payload).hexdigest(), "pdfs/KEC/DECK/d.pdf")], remote=remote, calls=calls)
    target = tmp_path / "raw" / "decks" / "KEC" / "d.pdf"
    before = _fetched_dirs()
    seen: list[Path] = []
    errors: list[BaseException] = []
    start = threading.Barrier(8)

    def reader() -> None:
        try:
            start.wait(10)
            for _page in range(5):
                with store.local(target) as got:
                    assert got.read_bytes() == payload
                    seen.append(got)
        except BaseException as exc:            # noqa: BLE001 - re-raised as a failed assertion below
            errors.append(exc)

    with store.shared_cache():
        threads = [threading.Thread(target=reader) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
    assert not errors
    assert len(seen) == 40 and len(set(seen)) == 1          # every page read the one fetched copy
    assert len(calls) == 1                                  # not 40 downloads of the whole PDF
    assert not seen[0].exists()                             # deleted with the cache folder on exit
    assert not (_fetched_dirs() - before)
    assert store._shared_dir is None and store._shared_bytes == 0


def test_shared_cache_evicts_the_least_recently_used_file_above_the_cap(tmp_path):
    first, second = b"a" * 8, b"b" * 8
    remote = tmp_path / "remote"
    _remote_file(remote, "pdfs/KEC/a.pdf", first)
    _remote_file(remote, "pdfs/KEC/b.pdf", second)
    calls: list[list[str]] = []
    store = _store(tmp_path, [
        ("p1", RAW, "decks/KEC/a.pdf", hashlib.md5(first).hexdigest(), "pdfs/KEC/a.pdf"),
        ("p2", RAW, "decks/KEC/b.pdf", hashlib.md5(second).hexdigest(), "pdfs/KEC/b.pdf"),
    ], remote=remote, calls=calls)
    a = tmp_path / "raw" / "decks" / "KEC" / "a.pdf"
    b = tmp_path / "raw" / "decks" / "KEC" / "b.pdf"

    with store.shared_cache(max_bytes=10):
        with store.local(a) as got_a:
            assert got_a.read_bytes() == first
        with store.local(b) as got_b:
            assert got_b.read_bytes() == second
        assert not got_a.exists() and got_b.exists()        # 16 bytes on a 10-byte cap: the LRU file goes
        assert store._shared_bytes == len(second)
        with store.local(a) as again:                       # evicted a is fetched again, not served stale
            assert again.read_bytes() == first
        assert len(calls) == 3                              # a, b, a


def test_shared_cache_removes_its_folder_on_exit_and_on_error(tmp_path):
    remote = tmp_path / "remote"
    _remote_file(remote, "pdfs/KEC/x.pdf", b"x")
    store = _store(tmp_path, [("px", RAW, "decks/KEC/x.pdf", hashlib.md5(b"x").hexdigest(),
                               "pdfs/KEC/x.pdf")], remote=remote, calls=[])
    target = tmp_path / "raw" / "decks" / "KEC" / "x.pdf"

    before = _fetched_dirs()
    with pytest.raises(RuntimeError, match="reader died"):
        with store.shared_cache():
            with store.local(target) as got:
                assert got.is_file()
            raise RuntimeError("reader died")
    assert store._shared_dir is None and not got.exists()
    assert not (_fetched_dirs() - before)
    with pytest.raises(RuntimeError, match="already active"):
        with store.shared_cache():
            with store.shared_cache():
                pass
