"""Content-addressed raw store: identical bytes are stored once (sha256 + hard links).

Companies file the same PDF twice (standalone/consolidated, revisions) and re-file decks
under new names, so the D raw pile is heading for hundreds of GB. A fetcher that writes
through ``store_bytes`` makes the second path a hard link to the first instead of a
second copy; the sha index lives in ``RAW_ROOT/_dedupe/sha_index.db``.

T-102 (Shivam, 7 Nov): raw files live only on Google Drive, so a reader asks
``RawStore`` for a path.  A local file is used as it is; a file the T-102 upload
manifest (``local_file.drive_path``) maps to Drive is downloaded into a temp folder,
checked against the manifest md5, and deleted when the reader is done.  ``prefetch``
gets a whole company's files in one ``rclone copy --files-from`` per Drive top.
"""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from reality_engine.config import PDFS_LEGACY_DIR, RAW_ROOT

INDEX_PATH = RAW_ROOT / "_dedupe" / "sha_index.db"
CHUNK = 1 << 20

_LOCK = threading.Lock()                      # sqlite3 handle is shared by fetcher workers
_CONNS: dict[Path, sqlite3.Connection] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sha_index (
  sha256 TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  first_path TEXT NOT NULL,
  stored_at TEXT NOT NULL);
"""


def sha256_file(path: Path) -> str:
    """sha256 of a whole file, read in ``CHUNK`` blocks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def same_file(a: Path, b: Path) -> bool:
    """True when both paths already name one file (a link appears twice in a scan)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def link_file(src: Path, dest: Path) -> None:
    """Make ``dest`` a hard link to ``src``: link to ``<dest>.lnk-tmp``, then replace.

    ``os.replace`` swaps the name atomically, so ``dest`` never vanishes between unlink
    and link and the group's canonical copy is untouched throughout.
    """
    tmp = dest.with_name(dest.name + ".lnk-tmp")
    tmp.unlink(missing_ok=True)
    try:
        os.link(src, tmp)
        os.replace(tmp, dest)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _write(dest: Path, data: bytes) -> None:
    """``dest`` via ``<dest>.part`` -> fsync -> replace, so a crash never leaves half a file."""
    part = dest.with_name(dest.name + ".part")
    try:
        with open(part, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(part, dest)
    except OSError:
        part.unlink(missing_ok=True)
        raise


def _connection(index_path: Path) -> sqlite3.Connection:
    con = _CONNS.get(index_path)
    if con is None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(index_path, timeout=60, check_same_thread=False)
        con.executescript(_SCHEMA)
        con.commit()
        _CONNS[index_path] = con
    return con


def store_bytes(dest: Path, data: bytes, index_path: Path | None = None) -> Path:
    """Store ``data`` at ``dest``; reuse an already stored copy of the same bytes.

    When the sha is in the index and the indexed file still holds those bytes, ``dest``
    becomes a hard link to it (same volume only — a cross-volume link raises, and the
    bytes are written normally instead). Otherwise the bytes are written atomically and
    recorded as the canonical copy.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    size = len(data)
    index = Path(index_path or INDEX_PATH)
    with _LOCK:
        con = _connection(index)
        row = con.execute(
            "SELECT first_path FROM sha_index WHERE sha256=? AND size=?", (sha, size)
        ).fetchone()
        if row:
            canonical = Path(row[0])
            try:
                if canonical.stat().st_size == size and sha256_file(canonical) == sha:
                    if same_file(dest, canonical):
                        return dest
                    link_file(canonical, dest)
                    return dest
            except OSError:
                pass                          # stale entry (moved/edited): store our own copy
        _write(dest, data)
        con.execute(
            "INSERT OR REPLACE INTO sha_index (sha256, size, first_path, stored_at) VALUES (?,?,?,?)",
            (sha, size, str(dest), datetime.now().isoformat(timespec="seconds")),
        )
        con.commit()
    return dest


# ---------------------------------------------------------------------------- T-102 fetch on demand
MANIFEST = Path(os.environ.get("REALITY_RAW_MANIFEST", r"D:\RealityEngine\drive_index\raw_to_drive.db"))
ARCHIVE = "gdrive:InfoDiffusion_archive"
ARCH17_REMOTE = "gdrive_ro:"                       # gdrive has drive.file scope; only this remote sees the 17 Oct upload
ARCH17_ROOT_ID = "1aSQEfkMMGmpEpDDq7tI9MH7kmNJNemTH"
ARCH17_TOP = "arch17"


def _norm(path) -> str:
    """One spelling per path: forward slashes, lower case, no ``..`` (Windows callers vary)."""
    text = os.fspath(path).replace("\\", "/")
    return os.path.normcase(os.path.normpath(text)).replace("\\", "/")


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(4 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_rclone(cmd: list[str], timeout: float = 1800.0) -> None:
    """Run one rclone command; raise with stderr (never the config) on a non-zero exit."""
    exe = os.environ.get("RCLONE_BIN") or shutil.which("rclone")
    if not exe:
        raise FileNotFoundError("rclone is not on PATH (set REALITY_RAW_FETCH=0 to work offline)")
    proc = subprocess.run([exe, *cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"rclone {cmd[0]} exited {proc.returncode}: {(proc.stderr or '').strip()[-800:]}")


def _matches(rel: str, name: str, pattern: str) -> bool:
    """A pattern with a slash matches the folder-relative path, else the file name."""
    return fnmatch.fnmatch((rel if "/" in pattern else name).lower(), pattern.lower())


def _default_roots() -> dict[str, Path]:
    """Manifest root names -> folders. ``sandbox`` holds the pilot loop copies kpi/hp_ocr read (T-102, 7 Nov)."""
    return {"raw": RAW_ROOT, "pdfs": PDFS_LEGACY_DIR,
            "sandbox": Path(os.environ.get("REALITY_SANDBOX_ROOT", r"D:\RealityEngine\sandbox"))}


class RawStore:
    """Local raw files, with the Drive copy behind the T-102 manifest.

    ``roots`` maps the manifest's ``root`` names onto the folders that held the files
    (``raw`` -> ``RAW_ROOT``, ``pdfs`` -> ``PDFS_LEGACY_DIR``).  A path is keyed by the
    root it sits under plus its forward-slash path below it, never by its stored text.
    """

    def __init__(self, manifest: Path | str | None = None, roots: dict[str, Path] | None = None,
                 runner=None, transfers: int = 8):
        self.manifest = Path(manifest if manifest is not None else MANIFEST)
        self.roots = {str(name).lower(): Path(path) for name, path in
                      (roots or _default_roots()).items()}
        self._root_norm = {name: _norm(path) for name, path in self.roots.items()}
        self.runner = runner
        self.transfers = transfers
        # (root, lower-case rel) -> (drive_path, md5, the rel as written), so a Windows path matches a
        # manifest row whatever its case while the file is still named the way the raw store names it.
        self._rows: dict[tuple[str, str], tuple[str, str | None, str]] = {}
        self._children: dict[tuple[str, str], dict[str, str]] = {}
        self._fetched: dict[tuple[str, str], Path] = {}
        self._load()

    # -- index -------------------------------------------------------------------------------------
    def _load(self) -> None:
        """Read the manifest once (rows that have a Drive path; ``raw/user_research`` stays local)."""
        if not self.manifest.is_file():
            return
        try:
            con = sqlite3.connect(f"file:{self.manifest.as_posix()}?mode=ro", uri=True, timeout=30)
            try:
                rows = con.execute("SELECT root, rel, md5, drive_path FROM local_file "
                                   "WHERE drive_path IS NOT NULL AND drive_path != ''").fetchall()
            finally:
                con.close()
        except sqlite3.DatabaseError:
            return
        for root, rel, md5, drive in rows:
            root_key = str(root).strip().lower()
            rel_text = str(rel).replace("\\", "/").strip("/")
            key = (root_key, rel_text.lower())
            self._rows[key] = (str(drive), str(md5).lower() if md5 else None, rel_text)
            parent = ""
            for part in rel_text.split("/")[:-1]:
                self._children.setdefault((root_key, parent), {})[part.lower()] = part
                parent = f"{parent}/{part.lower()}" if parent else part.lower()

    def _drive_on(self) -> bool:
        return os.environ.get("REALITY_RAW_FETCH", "1").strip().lower() not in ("0", "false", "off", "no")

    def _key(self, path) -> tuple[str, str] | None:
        norm = _norm(path)
        for name, root in sorted(self._root_norm.items(), key=lambda item: len(item[1]), reverse=True):
            if norm == root:
                return name, ""
            if norm.startswith(root + "/"):
                return name, norm[len(root) + 1:]
        return None

    def _local_path(self, key: tuple[str, str]) -> Path:
        row = self._rows.get(key)
        return self.roots[key[0]] / (row[2] if row else key[1])

    def drive_path(self, path) -> str | None:
        """The manifest's Drive path for ``path`` (None when the file is not in the manifest)."""
        key = self._key(path)
        row = self._rows.get(key) if key else None
        return row[0] if row else None

    # -- queries -----------------------------------------------------------------------------------
    def exists(self, path) -> bool:
        """Local file, else a manifest row whose copy can be fetched."""
        if Path(path).is_file():
            return True
        key = self._key(path)
        return self._drive_on() and key is not None and key in self._rows

    def walk(self, folder, pattern: str = "*"):
        """Files under ``folder``: the local ones plus every manifest row under it (deduped)."""
        folder = Path(folder)
        seen: set[str] = set()
        if folder.is_dir():
            for dirpath, _dirs, files in os.walk(folder):
                for name in sorted(files):
                    path = Path(dirpath) / name
                    rel = path.relative_to(folder).as_posix()
                    if not _matches(rel, name, pattern):
                        continue
                    key = _norm(path)
                    if key not in seen:
                        seen.add(key)
                        yield path
        key = self._key(folder)
        if key is None or not self._drive_on():
            return
        root, prefix = key
        base = prefix.rstrip("/")
        for (row_root, rel_lower), (_drive, _md5, rel_text) in sorted(self._rows.items()):
            if row_root != root or not (not base or rel_lower == base or rel_lower.startswith(base + "/")):
                continue
            name = rel_text.rsplit("/", 1)[-1]
            rel_from_folder = rel_lower[len(base) + 1:] if base else rel_lower
            if not _matches(rel_from_folder, name, pattern):
                continue
            path = self.roots[root] / rel_text
            norm = _norm(path)
            if norm not in seen:
                seen.add(norm)
                yield path

    def glob(self, folder, pattern: str = "*"):
        """``walk`` with a pattern, like ``Path.glob`` (``glob(folder, '*/X.jsonl')``)."""
        return self.walk(folder, pattern)

    def subdirs(self, folder) -> list[Path]:
        """Immediate child folders from disk and from the manifest (needed by a folder walk)."""
        folder = Path(folder)
        found: dict[str, Path] = {}
        if folder.is_dir():
            for entry in os.scandir(folder):
                if entry.is_dir(follow_symlinks=False):
                    found[_norm(entry.path)] = Path(entry.path)
        key = self._key(folder)
        if key is not None and self._drive_on():
            root, prefix = key
            base = prefix.rstrip("/")
            for child_lower, _child_text in sorted(self._children.get((root, base), {}).items()):
                path = self.roots[root] / (f"{base}/{child_lower}" if base else child_lower)
                found.setdefault(_norm(path), path)
        return [found[item] for item in sorted(found)]

    # -- fetch -------------------------------------------------------------------------------------
    def _top_source(self, top: str) -> tuple[str, list[str]]:
        if top == ARCH17_TOP:
            return ARCH17_REMOTE, [f"--drive-root-folder-id={ARCH17_ROOT_ID}"]
        return f"{ARCHIVE}/{top}", []

    def _fetch(self, items: dict[tuple[str, str], tuple[str, str | None]], dest: Path) -> dict[tuple[str, str], Path]:
        """One ``rclone copy --files-from`` per Drive top; md5-check every fetched file."""
        by_top: dict[str, list[tuple[tuple[str, str], str, str | None]]] = {}
        for key, (drive, md5) in items.items():
            top, _slash, rest = drive.partition("/")
            by_top.setdefault(top, []).append((key, rest, md5))
        out: dict[tuple[str, str], Path] = {}
        for top, members in sorted(by_top.items()):
            listfile = dest / f"files_{top}.txt"
            listfile.write_text("\n".join(rest for _key, rest, _md5 in members) + "\n", encoding="utf-8")
            source, flags = self._top_source(top)
            cmd = ["copy", source, str(dest / top), "--files-from", str(listfile),
                   "--transfers", str(self.transfers), "--checksum", *flags]
            (self.runner or _run_rclone)(cmd)
            for key, rest, md5 in members:
                got = dest / top / rest
                if not got.is_file():
                    raise FileNotFoundError(f"rclone fetched no file for {key[0]}:{key[1]} ({source}/{rest})")
                if md5:
                    actual = _md5(got)
                    if actual != md5:
                        raise ValueError(f"md5 mismatch for {key[0]}:{key[1]}: manifest {md5}, fetched {actual}")
                out[key] = got
        return out

    @contextlib.contextmanager
    def local(self, path):
        """The local path to read; a Drive-only file is fetched now and deleted on exit."""
        target = Path(path)
        if target.is_file():
            yield target
            return
        key = self._key(target) if self._drive_on() else None
        if key is not None:
            fetched = self._fetched.get(key)
            if fetched is not None and fetched.is_file():
                yield fetched                       # inside prefetch: already downloaded
                return
            row = self._rows.get(key)
            if row is not None:
                temp = Path(tempfile.mkdtemp(prefix="raw_fetch_"))
                try:
                    got = self._fetch({key: row[:2]}, temp).get(key)
                    if got is None:
                        raise FileNotFoundError(str(target))
                    yield got
                finally:
                    shutil.rmtree(temp, ignore_errors=True)
                return
        raise FileNotFoundError(f"{target} is not local and not in the T-102 manifest {self.manifest}")

    @contextlib.contextmanager
    def prefetch(self, paths):
        """Download every Drive-only path in ``paths`` once (one rclone copy per top), delete on exit."""
        items: dict[tuple[str, str], tuple[str, str | None]] = {}
        if self._drive_on():
            for path in paths:
                target = Path(path)
                if target.is_file():
                    continue
                key = self._key(target)
                row = self._rows.get(key) if key is not None else None
                if row is not None:
                    items[key] = row[:2]
        if not items:
            yield
            return
        temp = Path(tempfile.mkdtemp(prefix="raw_fetch_"))
        previous = self._fetched
        try:
            self._fetched = {**previous, **self._fetch(items, temp)}
            yield
        finally:
            self._fetched = previous
            shutil.rmtree(temp, ignore_errors=True)


_DEFAULT: RawStore | None = None


def default_store() -> RawStore:
    """The process-wide store for ``config.RAW_ROOT`` / ``config.PDFS_LEGACY_DIR``."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = RawStore()
    return _DEFAULT
