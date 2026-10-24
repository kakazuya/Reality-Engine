"""Small, dependency-free persistence helpers for the local dsh worker plugin.

Runtime records live under ``plugins/dsh-worker/runtime`` by default.  Every
JSON file is written with a same-directory temporary file plus ``os.replace``
so a reader never observes a half-written record.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

JOB_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
# The lock file names are data, not just names: the main checkout keeps the
# historical ``repository-mutation.json`` (so a worker started before the
# per-worktree upgrade still contends with a new one), and every other
# workspace -- a registered git worktree -- gets its own hashed lock.
MUTATION_LOCK_NAME = "repository-mutation.json"
LEASE_FILE = "controller_lease.json"
LEASE_SCHEMA = "dsh-worker-controller-lease/1"
# Every job-record/lease/steering write for one job is serialised inside the
# job directory by this OS-level byte-range lock (msvcrt on Windows).
JOB_LOCK_NAME = ".record.lock"
TOKEN_FILE = "control_token.bin"
STEERING_FILE = "steering.jsonl"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utc_now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def new_job_id() -> str:
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(4)}"


def valid_job_id(job_id: str) -> bool:
    return bool(JOB_ID_RE.fullmatch(str(job_id or "")))


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.tmp"
    )
    try:
        tmp.write_text(text, encoding=encoding, newline="")
        # A reader can briefly hold the destination open on Windows.  os.replace
        # then raises PermissionError; retry rather than losing a status update.
        last_error: OSError | None = None
        for attempt in range(50):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(min(0.02 * (attempt + 1), 0.1))
        if last_error is not None:
            raise last_error
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.tmp"
    )
    try:
        tmp.write_bytes(data)
        last_error: OSError | None = None
        for attempt in range(50):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(min(0.02 * (attempt + 1), 0.1))
        if last_error is not None:
            raise last_error
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------- file locks
_locks_held = threading.local()


def _lock_fd(fd: int, timeout: float) -> None:
    if os.name == "nt":
        import msvcrt

        deadline = time.monotonic() + timeout
        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for lock ({timeout:g}s)") from exc
                time.sleep(0.01)
    else:  # POSIX dev/CI fallback; the plugin itself is Windows-only
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock_fd(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def exclusive_lock(path: Path, timeout: float = 30.0) -> Iterator[None]:
    """Cross-process exclusive byte-range lock on ``path``.

    Re-entrant within the same thread so a caller may hold a job lock and call
    a helper that records steering for the same job.  A second *thread* or
    process blocks until the lock is released.
    """
    key = os.path.normcase(str(path))
    depths = getattr(_locks_held, "depths", None)
    if depths is None:
        depths = {}
        _locks_held.depths = depths
    if depths.get(key):
        depths[key] = int(depths[key]) + 1
        try:
            yield
        finally:
            depths[key] = int(depths[key]) - 1
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        _lock_fd(fd, timeout)
        depths[key] = 1
        try:
            yield
        finally:
            depths.pop(key, None)
            _unlock_fd(fd)
    finally:
        os.close(fd)


def atomic_write_json_locked(path: Path, value: Any, lock_path: Path | None = None) -> None:
    with exclusive_lock(lock_path or path.parent / JOB_LOCK_NAME):
        atomic_write_json(path, value)


def append_jsonl_locked(path: Path, record: dict[str, Any], lock_path: Path | None = None) -> None:
    """Append one complete JSON line under the shared job lock."""
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with exclusive_lock(lock_path or path.parent / JOB_LOCK_NAME):
        with path.open("a", encoding="utf-8", newline="") as fh:
            fh.write(line)
            fh.flush()


def read_json_bounded(path: Path, max_bytes: int = 262_144) -> tuple[Any | None, str | None]:
    """Read a JSON file with a hard byte bound.

    Returns ``(value, error)``.  A missing file is ``(None, "missing")``; a
    malformed or oversized file is ``(None, "invalid")``.  Callers decide
    whether missing is normal.
    """
    try:
        stat = path.stat()
    except OSError:
        return None, "missing"
    if not path.is_file():
        return None, "missing"
    if stat.st_size > max_bytes:
        return None, "too_large"
    try:
        with path.open("r", encoding="utf-8", errors="strict") as fh:
            value = json.load(fh)
    except PermissionError:
        # Windows reader/writer overlap: retry a few times before giving up.
        for attempt in range(5):
            time.sleep(0.02 * (attempt + 1))
            try:
                with path.open("r", encoding="utf-8", errors="strict") as fh:
                    value = json.load(fh)
                break
            except PermissionError:
                value = None
                if attempt == 4:
                    return None, "invalid"
            except (OSError, UnicodeError, json.JSONDecodeError):
                return None, "invalid"
        if value is None:
            return None, "invalid"
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "invalid"
    return value, None


def read_text_bounded(path: Path, max_bytes: int) -> tuple[str, bool, int]:
    """Return ``(text, truncated, total_bytes)`` without reading past the cap."""
    try:
        stat = path.stat()
    except OSError:
        return "", False, 0
    if not path.is_file():
        return "", False, 0
    limit = max(0, int(max_bytes))
    try:
        with path.open("rb") as fh:
            data = fh.read(limit + 1)
    except OSError:
        return "", False, 0
    truncated = len(data) > limit or stat.st_size > limit
    head = data[:limit]
    if truncated:
        # Do not cut a multi-byte UTF-8 character in half (a Hindi answer cut
        # at the byte cap used to end in U+FFFD).  Drop at most 3 bytes of an
        # incomplete trailing sequence.
        head = _trim_partial_utf8(head)
    text = head.decode("utf-8", errors="replace")
    return text, truncated, stat.st_size


def read_bytes_bounded(path: Path, max_bytes: int) -> tuple[bytes, str | None]:
    """Read at most ``max_bytes``; ``(b"", error)`` on missing/invalid/oversize."""
    try:
        stat = path.stat()
    except OSError:
        return b"", "missing"
    if not path.is_file():
        return b"", "missing"
    if stat.st_size > max_bytes:
        return b"", "too_large"
    try:
        return path.read_bytes(), None
    except OSError:
        return b"", "invalid"


def _trim_partial_utf8(data: bytes) -> bytes:
    for back in range(1, min(4, len(data)) + 1):
        byte = data[-back]
        if byte & 0b1100_0000 != 0b1000_0000:  # lead or ASCII byte
            need = 1 if byte < 0x80 else 2 if byte >> 5 == 0b110 else 3 if byte >> 4 == 0b1110 else 4
            return data if need <= back else data[:-back]
    return data


def read_text_bounded_tail(path: Path, max_bytes: int) -> str:
    """Return at most the last ``max_bytes`` of a text file ('' if unreadable)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read(max_bytes)
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def workspace_key(workspace: Path) -> str:
    normalized = os.path.normcase(str(workspace.resolve()))
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:32]


def workspace_lock_name(workspace: Path, repo_root: Path | None = None) -> str:
    """One mutation lock per workspace path.

    The main checkout deliberately keeps the historical shared filename: a
    worker started before this upgrade still holds that file, so it must keep
    excluding new root-checkout writers.  Every other registered worktree gets
    its own hashed lock file.
    """
    resolved = Path(workspace).resolve()
    if repo_root is not None:
        try:
            same = os.path.normcase(str(resolved)) == os.path.normcase(
                str(Path(repo_root).resolve())
            )
        except OSError:
            same = False
        if same:
            return MUTATION_LOCK_NAME
    return f"workspace-{workspace_key(resolved)}.json"


def read_lease(
    path: Path,
    now: datetime | None = None,
    *,
    expected_job_id: str | None = None,
    expected_owner_id: str | None = None,
    max_seconds: int = 7200,
) -> tuple[dict[str, Any] | None, str | None]:
    """Read and validate the controller lease; never extends it.

    A missing/malformed/malformed-deadline lease is invalid, not an infinite
    lease.  The supervisor treats invalidity as a fail-closed expiry.  Binding
    the expected job/owner and the supported interval prevents a copied,
    wrong-owner, or arbitrarily future lease from extending a job.
    """
    value, error = read_json_bounded(path, 65_536)
    if not isinstance(value, dict):
        return None, error or "invalid"
    if value.get("schema") != LEASE_SCHEMA:
        return None, "schema_mismatch"
    if expected_job_id is not None and value.get("job_id") != expected_job_id:
        return None, "job_mismatch"
    if expected_owner_id is not None and value.get("owner_id") != expected_owner_id:
        return None, "owner_mismatch"
    deadline = parse_iso(value.get("deadline"))
    if deadline is None:
        return None, "deadline_invalid"
    now = now or utc_now()
    remaining = (deadline - now).total_seconds()
    if remaining > max_seconds + 60:
        return None, "deadline_too_far"
    lease = dict(value)
    lease["deadline"] = iso(deadline)
    lease["remaining_seconds"] = round(remaining, 3)
    lease["expired"] = remaining <= 0
    return lease, None


# ------------------------------------------------------------------- DPAPI
# The per-job control token is persisted DPAPI-encrypted (CurrentUser scope):
# any dsh-worker MCP server process of the same Windows user can decrypt it, and
# no other account can.  The plaintext token is never written to disk, logged or
# returned by a tool.
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


if os.name == "nt":  # pragma: no branch - platform is fixed on the target host
    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _crypt32.CryptProtectData.restype = ctypes.c_int
    _crypt32.CryptProtectData.argtypes = (
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DATA_BLOB),
    )
    _crypt32.CryptUnprotectData.restype = ctypes.c_int
    _crypt32.CryptUnprotectData.argtypes = (
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DATA_BLOB),
    )
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _kernel32.LocalFree.argtypes = (ctypes.c_void_p,)


def _make_blob(data: bytes) -> tuple[_DATA_BLOB, Any]:
    # Keep the backing buffer alive for the duration of the call.
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(
        ctypes.c_uint32(len(data)), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    )
    return blob, buffer


def dpapi_available() -> bool:
    return os.name == "nt"


def dpapi_protect(data: bytes, description: str = "dsh-worker control token") -> bytes | None:
    """Encrypt for the current Windows user only; ``None`` when unavailable."""
    if os.name != "nt" or not data:
        return None
    in_blob, _buffer = _make_blob(data)
    out_blob = _DATA_BLOB()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        description,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        return None
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def dpapi_unprotect(data: bytes) -> bytes | None:
    """Decrypt for the current Windows user only; ``None`` on any failure."""
    if os.name != "nt" or not data:
        return None
    in_blob, _buffer = _make_blob(data)
    out_blob = _DATA_BLOB()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        return None
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))
