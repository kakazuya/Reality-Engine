"""Fetch a document from ``gdrive:InfoDiffusion_archive`` by path, sha256 or stale DB path.

The DB keeps local paths from two machines (``...\\reality_engine\\data\\pdfs\\X``
and ``D:\\RealityEngine\\pdfs\\X``); both map to the archive's ``pdfs/X`` and
``D_pdfs/X``.  Decks map to ``decks/...``.  Lookups use a small on-disk index of
one Drive folder (``rclone lsjson -R --hash``), so a worker does not re-list the
whole archive; ``--reindex`` refreshes it.

Examples:
    python -m reality_engine.toolbelt.drive_fetch --dry-run \\
        "C:\\...\\reality_engine\\data\\pdfs\\20MICRONS\\ANNUAL_REPORT\\20261010_9041611d_x.pdf"
    python -m reality_engine.toolbelt.drive_fetch --dest .tmp/fetched \\
        pdfs/20MICRONS/ANNUAL_REPORT/20261010_9041611d_x.pdf
    python -m reality_engine.toolbelt.drive_fetch --sha256 <64-hex> --folder pdfs/TITAGARH --dest .tmp

    from reality_engine.toolbelt.drive_fetch import fetch
    result = fetch(["pdfs/TITAGARH/ANNUAL_REPORT/x.pdf"], dest=".tmp/fetched", dry_run=True)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ._common import add_format, data_root, main_guard, print_result

DEFAULT_REMOTE = "gdrive:InfoDiffusion_archive"
DEFAULT_INDEX = Path(".tmp") / "drive_index.json"
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_REMOTE_PREFIXES = ("pdfs/", "decks/", "d_pdfs/", "macro_pdfs/", "bhavcopy/",
                    "raw_market/", "snapshots/", "vector_index", "work_files/",
                    "telegram_media/", "lancedb/")
_SANDBOX_ENV = ("DSH_WORKER_JOB_ID", "DSH_WORKER_PROGRESS_NOTES", "DSH_SESSION_ID", "DSH_SANDBOX")


def local_to_remote(value: str) -> str:
    """Map a DB/Windows local path to its archive-relative path."""
    s = str(value).strip().replace("\\", "/")
    low = s.lower()
    if low.startswith("d:/realityengine/"):
        rest = s[len("d:/realityengine/"):]
        head, _, tail = rest.partition("/")
        if head.lower() in ("pdfs", "remaining_pdfs"):
            return "D_pdfs/" + tail
        return rest
    marker = "reality_engine/data/"
    idx = low.find(marker)
    if idx >= 0:
        return s[idx + len(marker):]
    if low.startswith(_REMOTE_PREFIXES):
        return s
    raise ValueError(f"cannot map local path to the Drive archive: {value}")


def classify(value: str) -> tuple[str, str]:
    """``("sha256"|"local"|"remote", value)`` for one CLI item."""
    s = str(value).strip()
    if _HASH.fullmatch(s):
        return "sha256", s.lower()
    if s.lower().startswith(_REMOTE_PREFIXES):
        return "remote", s
    if re.match(r"^[A-Za-z]:[\\/]", s) or "\\" in s or s.lower().startswith("reality_engine/"):
        return "local", s
    return "remote", s


def _rclone(rclone: Sequence[str] | None) -> list[str]:
    if rclone:
        return list(rclone)
    env = os.environ.get("RCLONE_BIN")
    if env:
        return [env]
    return [shutil.which("rclone") or "rclone"]


def _run(cmd: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def _clean_stderr(text: str) -> str:
    """Drop the harmless sandbox warning when rclone cannot rewrite its config."""
    lines = [ln for ln in (text or "").splitlines()
             if "Failed to save config" not in ln]
    return "\n".join(lines).strip()


def _empty_index(remote: str) -> dict[str, Any]:
    return {"schema": 1, "remote": remote, "folders": {}}


def load_index(path: Path, remote: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_index(remote)
    if not isinstance(data, dict) or data.get("remote") != remote or not isinstance(data.get("folders"), dict):
        return _empty_index(remote)
    return data


def save_index(path: Path, index: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=1), encoding="utf-8")


def _lsjson(remote: str, folder: str, rclone: Sequence[str], timeout: float) -> list[dict[str, Any]]:
    target = remote.rstrip("/") + ("/" + folder if folder else "")
    proc = _run([*_rclone(rclone), "lsjson", "-R", "--hash", "--files-only",
                 "--no-mimetype", target], timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"rclone lsjson failed for {target}: {_clean_stderr(proc.stderr)[-600:]}")
    try:
        items = json.loads(proc.stdout or "[]")
    except ValueError as exc:
        raise RuntimeError(f"rclone lsjson returned non-JSON for {target}: {exc}") from exc
    return [it for it in items if not it.get("IsDir")]


def index_folder(index: dict[str, Any], folder: str, rclone: Sequence[str] | None = None,
                 force: bool = False, timeout: float = 600.0) -> dict[str, Any]:
    """List one archive folder into the index (no-op when cached and not forced)."""
    folder = (folder or "").strip("/")
    if not force and folder in index["folders"]:
        return index["folders"][folder]
    remote = index["remote"]
    files: dict[str, dict[str, Any]] = {}
    for item in _lsjson(remote, folder, _rclone(rclone), timeout):
        rel = posixpath.join(folder, str(item.get("Path") or "")) if folder else str(item.get("Path") or "")
        hashes = {str(k).lower(): v for k, v in (item.get("Hashes") or {}).items()}
        files[rel] = {"size": item.get("Size"), "md5": hashes.get("md5"),
                      "sha1": hashes.get("sha1"), "sha256": hashes.get("sha256"),
                      "mod_time": item.get("ModTime")}
    index["folders"][folder] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "files": files}
    return index["folders"][folder]


def find_path(index: dict[str, Any], rel: str, rclone: Sequence[str] | None = None,
              reindex: bool = False, timeout: float = 600.0) -> dict[str, Any] | None:
    rel = rel.replace("\\", "/").lstrip("/")
    folder = posixpath.dirname(rel)
    index_folder(index, folder, rclone, force=reindex, timeout=timeout)
    entry = index["folders"][folder]["files"].get(rel)
    if entry is None:  # Drive is case-sensitive; Windows callers are not.
        low = rel.lower()
        entry = next((v for k, v in index["folders"][folder]["files"].items()
                      if k.lower() == low), None)
    return entry


def find_sha(index: dict[str, Any], sha256: str, folder: str | None = None,
             rclone: Sequence[str] | None = None, reindex: bool = False,
             timeout: float = 600.0) -> tuple[str, dict[str, Any]] | None:
    sha = sha256.lower()

    def search() -> tuple[str, dict[str, Any]] | None:
        for bucket in index["folders"].values():
            for rel, entry in bucket["files"].items():
                if str(entry.get("sha256") or "").lower() == sha:
                    return rel, entry
        return None

    hit = search()
    if hit or not folder:
        if hit:
            return hit
        raise ValueError("sha256 not in the cached index; pass --folder <archive folder> "
                         "to list the folder that should contain it")
    index_folder(index, folder, rclone, force=reindex, timeout=timeout)
    return search()


def _in_sandbox() -> bool:
    return any(key in os.environ for key in _SANDBOX_ENV)


def _file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(remote: str, rel: str, dest: Path, rclone: Sequence[str] | None,
              timeout: float) -> tuple[str, str | None]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = _run([*_rclone(rclone), "copyto", f"{remote.rstrip('/')}/{rel}", str(dest)], timeout)
    if proc.returncode == 0:
        return "ok", None
    err = _clean_stderr(proc.stderr)
    low = err.lower()
    if "403" in low and any(token in low for token in ("abusive", "malware", "spam", "cannot download")):
        return "blocked", "Drive 403 abusive; fetch this file from its BSE source_url instead"
    return "error", err[-600:] or f"rclone copyto exited {proc.returncode}"


def fetch(items: Sequence[str], dest: str | Path | None = None, *, remote: str = DEFAULT_REMOTE,
          folder: str | None = None, reindex: bool = False, transfers: int = 8,
          dry_run: bool = False, verify: bool = False, index_path: str | Path = DEFAULT_INDEX,
          rclone: Sequence[str] | None = None, timeout: float = 600.0) -> dict[str, Any]:
    """Resolve and (unless ``dry_run``) download each item; per-file ok/missing/blocked."""
    if not items:
        raise ValueError("give at least one path, sha256 or DB local path")
    if dest is None and _in_sandbox():
        raise ValueError("--dest is required inside a sandbox (the original DB path may be unwritable)")
    index_file = Path(index_path)
    index = load_index(index_file, remote)
    dest_dir = Path(dest) if dest else None
    resolved: list[dict[str, Any]] = []
    for raw in items:
        kind, value = classify(raw)
        record: dict[str, Any] = {"input": raw, "kind": kind}
        try:
            if kind == "sha256":
                hit = find_sha(index, value, folder, rclone, reindex, timeout)
                rel, entry = hit if hit else (None, None)
                record.update({"sha256": value, "remote_path": rel, "entry": entry})
            else:
                rel = local_to_remote(value) if kind == "local" else value.replace("\\", "/")
                entry = find_path(index, rel, rclone, reindex, timeout)
                record.update({"remote_path": rel, "entry": entry})
            if not record.get("entry"):
                record["status"] = "missing"
                record["reason"] = "not found in the Drive folder index"
            elif dry_run:
                record["status"] = "present"
            else:
                if dest_dir is not None:
                    target = dest_dir / Path(record["remote_path"]).name
                elif kind == "local":
                    target = Path(value)
                else:
                    target = data_root() / record["remote_path"]
                record["dest"] = str(target)
        except (ValueError, RuntimeError, OSError) as exc:
            record["status"] = "error"
            record["reason"] = f"{type(exc).__name__}: {exc}"
        resolved.append(record)

    pending = [r for r in resolved if r.get("entry") and r.get("status") not in ("missing", "present")]
    if pending:
        def finish(record: dict[str, Any]) -> None:
            target = Path(record["dest"])
            status, reason = _download(remote, record["remote_path"], target, rclone, timeout)
            record["status"] = status
            if reason:
                record["reason"] = reason
            if status == "ok" and verify:
                entry = record["entry"]
                if entry.get("md5"):
                    record["verified"] = _file_hash(target, "md5") == str(entry["md5"]).lower()
                    record["verify_algo"] = "md5"
                elif entry.get("sha256"):
                    record["verified"] = _file_hash(target, "sha256") == str(entry["sha256"]).lower()
                    record["verify_algo"] = "sha256"
                else:
                    record["verified"] = None
                if record["verified"] is False:
                    record["status"] = "verify_failed"

        with ThreadPoolExecutor(max_workers=max(1, int(transfers))) as pool:
            list(pool.map(finish, pending))
    for record in resolved:
        record.pop("entry", None)
    save_index(index_file, index)
    summary: dict[str, int] = {}
    for record in resolved:
        summary[record["status"]] = summary.get(record["status"], 0) + 1
    return {"remote": remote, "index": str(index_file), "dry_run": dry_run,
            "summary": summary, "items": resolved}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m reality_engine.toolbelt.drive_fetch",
        description="Fetch files from the InfoDiffusion Drive archive by path, sha256 or DB local path.")
    ap.add_argument("items", nargs="+", help="archive-relative path, sha256, or DB local_path")
    ap.add_argument("--dest", help="destination directory (required in a sandbox)")
    ap.add_argument("--remote", default=DEFAULT_REMOTE, help=f"rclone remote (default: {DEFAULT_REMOTE})")
    ap.add_argument("--folder", help="archive folder to index for a sha256 lookup")
    ap.add_argument("--reindex", action="store_true", help="refresh the cached Drive folder index")
    ap.add_argument("--transfers", type=int, default=8, help="parallel downloads (default: 8)")
    ap.add_argument("--dry-run", action="store_true", help="report present/missing without downloading")
    ap.add_argument("--verify", action="store_true", help="compare the downloaded file's md5/sha256")
    ap.add_argument("--index", default=str(DEFAULT_INDEX), help=f"index cache (default: {DEFAULT_INDEX})")
    ap.add_argument("--rclone", help="rclone executable (default: rclone on PATH)")
    ap.add_argument("--timeout", type=float, default=600.0, help="seconds per rclone call")
    add_format(ap)
    args = ap.parse_args(argv)
    result = fetch(args.items, args.dest, remote=args.remote, folder=args.folder,
                   reindex=args.reindex, transfers=args.transfers, dry_run=args.dry_run,
                   verify=args.verify, index_path=args.index,
                   rclone=[args.rclone] if args.rclone else None, timeout=args.timeout)
    print_result(result, args.format,
                 columns=["input", "kind", "remote_path", "status", "dest", "verified", "reason"])
    bad = {"missing", "blocked", "error", "verify_failed"}
    return 1 if any(record["status"] in bad for record in result["items"]) else 0


if __name__ == "__main__":
    main_guard(main)
