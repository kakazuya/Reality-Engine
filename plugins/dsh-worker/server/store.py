"""Small, dependency-free persistence helpers for the local dsh worker plugin.

Runtime records live under ``plugins/dsh-worker/runtime`` by default.  Every
JSON file is written with a same-directory temporary file plus ``os.replace``
so a reader never observes a half-written record.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

JOB_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
# One mutation lock per repository, not per workspace.  Parent and subdirectory
# checkouts must contend for the same lock so they cannot bypass one-writer
# policy by choosing a narrower workspace path.
MUTATION_LOCK_NAME = "repository-mutation.json"
LEASE_FILE = "controller_lease.json"
LEASE_SCHEMA = "dsh-worker-controller-lease/1"


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
